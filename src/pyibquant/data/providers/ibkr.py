"""Small, data-only adapter for the official TWS Python API (10.33+)."""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from threading import Event, Lock, RLock, Thread
from time import time as current_time
from typing import Any
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

from ...bars import Bar, BarSeries
from ...errors import CacheError, ConnectionError, DataError, RequestTimeout
from ..cache import HistoricalCache, Query

try:
    from ibapi import get_version_string
    from ibapi.client import EClient
    from ibapi.contract import Contract
    from ibapi.wrapper import EWrapper
except ImportError as exc:
    raise ImportError(
        "Install the official TWS API Python client (10.33+), not the old PyPI ibapi. "
        "See README.md for installation instructions."
    ) from exc

if tuple(int(n) for n in get_version_string().split(".")[:2]) < (10, 33):
    raise ImportError("PyIBQuant requires the official TWS Python API 10.33 or newer.")

INTERVALS = {
    "30s": "30 secs",
    "1min": "1 min",
    "5min": "5 mins",
    "15min": "15 mins",
    "30min": "30 mins",
    "1h": "1 hour",
    "2h": "2 hours",
    "4h": "4 hours",
    "1d": "1 day",
    "1w": "1 week",
    # TWS has no annual bar size; monthly callbacks are aggregated below.
    "1y": "1 month",
}

# Bounded pages, with a week minimum to cross weekends/US market holidays.
HISTORY_PAGES = {
    "30s": "1 W",
    "1min": "1 W",
    "5min": "1 M",
    "15min": "3 M",
    "30min": "3 M",
    "1h": "3 M",
    "2h": "3 M",
    "4h": "3 M",
    "1d": "1 Y",
    "1w": "5 Y",
    "1y": "10 Y",
}


@dataclass
class _Request:
    done: Event = field(default_factory=Event)
    contracts: list[Any] = field(default_factory=list)
    series: BarSeries | None = None
    error: Exception | None = None
    monthly_bars: dict[date, Bar] = field(default_factory=dict)
    allow_empty: bool = False
    start_date: date | None = None


def normalize_bar(raw: Any, interval: str) -> Bar:
    """formatDate=2 gives epoch seconds intraday, dates for daily/coarser bars."""
    timestamp = (
        datetime.strptime(str(raw.date), "%Y%m%d").date()
        if interval in {"1d", "1w", "1y"}
        else datetime.fromtimestamp(int(raw.date), UTC)
    )
    if interval == "1y":
        timestamp = date(timestamp.year, timestamp.month, 1)
    elif interval == "1w":
        timestamp -= timedelta(days=timestamp.weekday())
    return Bar(
        timestamp,
        float(raw.open),
        float(raw.high),
        float(raw.low),
        float(raw.close),
        max(0.0, float(raw.volume)),
    )


def calendar_window(interval: str, duration: str, ending: datetime) -> tuple[str, date]:
    """Fetch complete source periods for the requested calendar week/year buckets."""
    local = ending.astimezone(ZoneInfo("America/New_York"))
    amount, unit = duration.split()
    count = int(amount)
    if unit in {"M", "Y"}:
        months = local.year * 12 + local.month - 1 - count * (12 if unit == "Y" else 1)
        year, month = divmod(months, 12)
        start = local.replace(
            year=year, month=month + 1, day=min(local.day, monthrange(year, month + 1)[1])
        )
    elif unit == "S":
        start = (local.astimezone(UTC) - timedelta(seconds=count)).astimezone(local.tzinfo)
    else:
        start = local - timedelta(days=count * (7 if unit == "W" else 1))
    floor = (
        date(start.year, 1, 1)
        if interval == "1y"
        else start.date() - timedelta(days=start.weekday())
    )
    # An extra source year prevents the first displayed month/week from being clipped.
    return f"{min(68, local.year - floor.year + 1)} Y", floor


class IBKRProvider(EWrapper, EClient):
    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        timeout: float,
        *,
        cache: HistoricalCache | None = None,
        refresh_cache: bool = False,
    ) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self._host, self._port, self._client_id = host, port, client_id
        self.timeout = timeout
        self._ready = Event()
        self._connection_error: Exception | None = None
        self._requests: dict[int, _Request] = {}
        self._request_lock = Lock()
        self._counter = 0
        self._thread: Thread | None = None
        self._closing = False
        self._history_lock = RLock()
        self._monthly_bars: WeakKeyDictionary[BarSeries, dict[date, Bar]] = WeakKeyDictionary()
        self.cache = cache
        self.refresh_cache = refresh_cache

    def open(self) -> None:
        def run() -> None:
            try:
                self.connect(self._host, self._port, self._client_id)
                if self._closing:
                    self.disconnect()
                else:
                    self.run()
            except Exception as exc:
                self._connection_error = ConnectionError(str(exc))
                self._fail_pending(self._connection_error)
                self._ready.set()

        self._thread = Thread(target=run, daemon=True, name="pyibquant-ibkr")
        self._thread.start()
        if not self._ready.wait(self.timeout) or not self.isConnected():
            self.close()
            raise ConnectionError(
                f"Cannot connect to TWS/IB Gateway at {self._host}:{self._port}. "
                "Check login, API socket settings and client ID. "
                f"{self._connection_error or 'Connection handshake timed out.'}"
            ) from self._connection_error
        if self._connection_error:
            self.close()
            raise self._connection_error

    def nextValidId(self, orderId: int) -> None:
        self._ready.set()

    def _new_request(self, series: BarSeries | None = None) -> tuple[int, _Request]:
        if not self.isConnected():
            raise ConnectionError("IBKR is disconnected; create a new Market connection.")
        with self._request_lock:
            self._counter += 1
            request = _Request(series=series)
            self._requests[self._counter] = request
            return self._counter, request

    def _wait(self, request: _Request) -> None:
        if not request.done.wait(self.timeout):
            raise RequestTimeout(f"IBKR request timed out after {self.timeout:g}s")
        if request.error:
            raise request.error

    def contractDetails(self, reqId: int, contractDetails: Any) -> None:
        if request := self._requests.get(reqId):
            request.contracts.append(contractDetails.contract)

    def contractDetailsEnd(self, reqId: int) -> None:
        if request := self._requests.get(reqId):
            request.done.set()

    def _resolve(self, symbol: str, primary_exchange: str) -> Any:
        contract = Contract()
        contract.symbol, contract.secType = symbol, "STK"
        contract.exchange, contract.currency = "SMART", "USD"
        contract.primaryExchange = primary_exchange
        req_id, request = self._new_request()
        try:
            self.reqContractDetails(req_id, contract)
            self._wait(request)
            if len(request.contracts) != 1:
                raise DataError(
                    f"Expected one US stock/ETF contract for {symbol}, got "
                    f"{len(request.contracts)}. Specify primary_exchange to disambiguate."
                )
            return request.contracts[0]
        finally:
            self._requests.pop(req_id, None)

    def bars(
        self,
        symbol: str,
        *,
        interval: str = "1min",
        duration: str = "1 D",
        live: bool = False,
        regular_hours: bool = True,
        primary_exchange: str = "",
        refresh: bool = False,
        _end: datetime | date | None = None,
        _allow_empty: bool = False,
    ) -> BarSeries:
        symbol = symbol.strip().upper()
        if not symbol or interval not in INTERVALS:
            raise ValueError(f"Provide a symbol and an interval from {', '.join(INTERVALS)}")
        duration = re.sub(r"\s+", "", duration.upper())
        if not re.fullmatch(r"[1-9]\d*[SDWMY]", duration):
            raise ValueError("duration must look like '1 D', '2 W', or '6 M'")
        duration = f"{duration[:-1]} {duration[-1]}"
        end = ""
        if _end is not None:
            if live:
                raise ValueError("An ending timestamp cannot be used with live updates")
            if isinstance(_end, datetime):
                if _end.utcoffset() is None:
                    raise ValueError("The history end must be timezone-aware")
                ending = _end
            else:
                ending = datetime.combine(_end, time.min, ZoneInfo("America/New_York"))
            end = ending.astimezone(UTC).strftime("%Y%m%d %H:%M:%S UTC")
        contract = self._resolve(symbol, primary_exchange)
        source_duration = duration
        start_date = None
        if interval in {"1w", "1y"}:
            source_duration, start_date = calendar_window(
                interval,
                duration,
                ending if _end is not None else datetime.fromtimestamp(current_time(), UTC),
            )
        series = BarSeries(symbol, interval, live=live)
        series.duration = duration
        series.regular_hours = regular_hours
        series.primary_exchange = primary_exchange
        if interval == "1y":
            series.warnings.append(
                "Yearly candles combine IBKR monthly bars by calendar year. "
                "The first and current years may be partial; use multi-year History (e.g. 10 Y)."
            )
        query: Query = {
            "provider": "IBKR",
            "contract_id": int(contract.conId),
            "symbol": symbol,
            "exchange": str(contract.exchange),
            "primary_exchange": str(contract.primaryExchange),
            "currency": str(contract.currency),
            "interval": INTERVALS[interval],
            "duration": duration,
            "end": end,
            "regular_hours": regular_hours,
            "data_type": "TRADES",
            "normalization": 2 if interval in {"1w", "1y"} else 1,
            "source_duration": source_duration,
            "start": start_date.isoformat() if start_date else "",
        }
        if self.cache is not None and not live and not (refresh or self.refresh_cache):
            try:
                cached = self.cache.get(query)
                if cached is not None:
                    if interval == "1y":
                        with self._history_lock:
                            monthly = {bar.timestamp: bar for bar in cached.bars}
                            self._monthly_bars[series] = monthly
                            for year in {stamp.year for stamp in monthly}:
                                series.update(self._year_bar(monthly, year))
                    else:
                        for bar in cached.bars:
                            series.update(bar)
                    series.cache_hit = True
                    series.cache_created_at = cached.created_at.isoformat()
                    series.status = f"Historical snapshot (cached {series.cache_created_at})"
                    return series
            except CacheError as exc:
                series.warnings.append(f"Historical cache read failed; requesting IBKR data. {exc}")
        req_id, request = self._new_request(series)
        request.allow_empty = _allow_empty
        request.start_date = start_date
        if interval == "1y":
            with self._history_lock:
                self._monthly_bars[series] = request.monthly_bars
        try:
            self.reqHistoricalData(
                req_id,
                contract,
                end,
                source_duration,
                INTERVALS[interval],
                "TRADES",
                int(regular_hours),
                2,
                live,
                [],
            )
            self._wait(request)
            if not len(series) and not _allow_empty:
                raise DataError(
                    f"No bars returned for {symbol}; check data permissions and session."
                )
            series.status = "Subscribed to bar updates" if live else "Historical snapshot"
            if self.cache is not None and not live:
                try:
                    source = (
                        tuple(request.monthly_bars[key] for key in sorted(request.monthly_bars))
                        if interval == "1y"
                        else series.snapshot()
                    )
                    self.cache.put(query, source)
                except CacheError as exc:
                    series.warnings.append(
                        f"Historical cache write failed; data remains usable. {exc}"
                    )
            return series
        except BaseException:
            self.cancelHistoricalData(req_id)
            self._requests.pop(req_id, None)
            raise
        finally:
            if not live:
                self._requests.pop(req_id, None)

    @staticmethod
    def _year_bar(monthly: dict[date, Bar], year: int) -> Bar:
        months = [value for stamp, value in sorted(monthly.items()) if stamp.year == year]
        return Bar(
            date(year, 1, 1),
            months[0].open,
            max(month.high for month in months),
            min(month.low for month in months),
            months[-1].close,
            sum(month.volume for month in months),
        )

    def load_older(self, series: BarSeries, *, refresh: bool = False) -> int:
        """Extend an existing series without replacing its live subscription."""
        current = series.snapshot()
        if not current or (series.history_exhausted and not refresh):
            return 0
        with self._history_lock:
            monthly = self._monthly_bars.get(series)
            before = min(monthly) if monthly else current[0].timestamp
        page = self.bars(
            series.symbol,
            interval=series.interval,
            duration=HISTORY_PAGES[series.interval],
            regular_hours=series.regular_hours,
            primary_exchange=series.primary_exchange,
            _end=before,
            _allow_empty=True,
            refresh=refresh,
        )
        if series.interval == "1y":
            with self._history_lock:
                target = self._monthly_bars.get(series)
                if target is None:
                    raise DataError("Yearly source months are unavailable; reload the chart.")
                incoming = self._monthly_bars.get(page, {})
                older = {stamp: bar for stamp, bar in incoming.items() if stamp < before}
                for stamp, bar in older.items():
                    target.setdefault(stamp, bar)
                count = len(series)
                for year in {stamp.year for stamp in older}:
                    series.update(self._year_bar(target, year))
                added = len(series) - count
                progressed = bool(older)
        else:
            added = series.prepend(page.snapshot())
            progressed = added > 0
        series.history_exhausted = not progressed
        series.history_cache_hit = page.cache_hit
        for warning in page.warnings:
            if warning not in series.warnings:
                series.warnings.append(warning)
        return added

    def historicalData(self, reqId: int, bar: Any) -> None:
        request = self._requests.get(reqId)
        if request is None or request.series is None:
            return
        try:
            normalized = normalize_bar(bar, request.series.interval)
            if request.start_date is not None and normalized.timestamp < request.start_date:
                return
            if request.series.interval == "1y":
                # Replacements must recompute OHLCV so updates never double-count volume
                # and corrected highs/lows can shrink as well as grow.
                with self._history_lock:
                    request.monthly_bars[normalized.timestamp] = normalized
                    request.series.update(
                        self._year_bar(request.monthly_bars, normalized.timestamp.year)
                    )
            else:
                request.series.update(normalized)
        except (ValueError, TypeError, OverflowError) as exc:
            request.error = DataError(f"Invalid IBKR bar: {exc}")
            request.series.error = str(request.error)
            request.done.set()

    def historicalDataUpdate(self, reqId: int, bar: Any) -> None:
        self.historicalData(reqId, bar)

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:
        if request := self._requests.get(reqId):
            request.done.set()

    def error(
        self,
        reqId: int,
        errorTime: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:
        # Status messages and permission warnings must not discard valid historical bars.
        if errorCode in {2104, 2106, 2107, 2108, 2158}:
            return
        message = f"IBKR {errorCode}: {errorString}"
        if errorCode in {1100, 1101, 1102, 1300}:
            self._fail_pending(ConnectionError(message + "; reconnect to resume data."))
            return
        if errorCode in {502, 503, 504, 326}:
            self._connection_error = ConnectionError(message)
            self._fail_pending(self._connection_error)
            self._ready.set()
        request = self._requests.get(reqId)
        if request is None:
            return
        if (
            request.allow_empty
            and errorCode in {162, 165}
            and "query returned no data" in errorString.lower()
        ):
            request.done.set()
            return
        if errorCode in {2174, 2176, 2188, 10167}:
            if request.series is not None:
                request.series.warnings.append(message)
            return
        request.error = DataError(message)
        if request.series is not None:
            request.series.error = message
            request.series.status = "Data request failed"
        request.done.set()

    def _fail_pending(self, error: Exception) -> None:
        with self._request_lock:
            for request in list(self._requests.values()):
                request.error = error
                if request.series is not None:
                    request.series.error = str(error)
                    request.series.status = "Disconnected"
                request.done.set()

    def connectionClosed(self) -> None:
        self._connection_error = ConnectionError("IBKR connection closed")
        self._ready.set()
        self._fail_pending(self._connection_error)

    def cancel_bars(self, series: BarSeries) -> None:
        """Release just this series, leaving other market requests connected."""
        for req_id, request in list(self._requests.items()):
            if request.series is series:
                if series.live and self.isConnected():
                    self.cancelHistoricalData(req_id)
                self._requests.pop(req_id, None)
                series.status = "Subscription closed"

    def close(self) -> None:
        self._closing = True
        for req_id, request in list(self._requests.items()):
            if request.series is not None and request.series.live and self.isConnected():
                self.cancelHistoricalData(req_id)
        self.disconnect()
        self._fail_pending(ConnectionError("Market connection closed"))
        if self._thread is not None:
            self._thread.join(timeout=2)
