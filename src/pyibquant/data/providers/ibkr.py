"""Small, data-only adapter for the official TWS Python API (10.33+)."""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from threading import Event, Lock, RLock, Thread
from time import time as current_time
from typing import Any
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...bars import Bar, BarSeries
from ...errors import CacheError, ConnectionError, DataError, HistoricalRangeError, RequestTimeout
from ...options import OptionChain, OptionChainGroup
from ...quote_stream import QuoteStream
from ...quotes import DATA_TYPES, Option, Quote, QuoteInstrument, _number, _QuoteState
from ..cache import HistoricalCache, Query
from ..history import HistoryRange
from ._pacing import HistoryPacer

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

# Fixed request windows, independent of whether a page happens to contain bars.
RANGE_DAYS = {
    "1min": 1, "5min": 7, "15min": 28, "30min": 28,
    "1h": 28, "2h": 28, "4h": 28, "1d": 365, "1w": 1825, "1y": 3650,
}


def range_page_start(ending: date | datetime, interval: str) -> date | datetime:
    start = ending - (timedelta(hours=8) if interval == "30s"
                      else timedelta(days=RANGE_DAYS[interval]))
    if interval == "1w":
        start -= timedelta(days=start.weekday())
    elif interval == "1y":
        start = start.replace(month=1, day=1)
    return start


def range_duration(start: date | datetime, end: date | datetime, interval: str) -> str:
    if isinstance(start, datetime):
        assert isinstance(end, datetime)
        seconds = ceil((end - start).total_seconds())
    else:
        assert not isinstance(end, datetime)
        seconds = (end - start).days * 86400
    return f"{max(60, seconds)} S" if interval == "30s" else f"{max(1, ceil(seconds / 86400))} D"


@dataclass
class _Request:
    done: Event = field(default_factory=Event)
    contracts: list[Any] = field(default_factory=list)
    series: BarSeries | None = None
    error: Exception | None = None
    monthly_bars: dict[date, Bar] = field(default_factory=dict)
    allow_empty: bool = False
    start_date: date | None = None
    sessions: list[dict[str, Any]] = field(default_factory=list)
    regular_hours: bool = True
    initialized: bool = False
    quote: _QuoteState | None = None
    chain_underlying: int | None = None
    chain_groups: dict[tuple[str, str, float], OptionChainGroup] = field(default_factory=dict)


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
        self._pacer = HistoryPacer()
        self._pacing_stop = Event()
        self._quote_lock = Lock()

    def new_connection(self) -> IBKRProvider:
        """Create a disconnected replacement retaining normalized yearly sources."""
        replacement = IBKRProvider(
            self._host, self._port, self._client_id, self.timeout,
            cache=self.cache, refresh_cache=self.refresh_cache,
        )
        replacement._pacer = self._pacer
        with self._history_lock:
            for series, monthly in list(self._monthly_bars.items()):
                replacement._monthly_bars[series] = dict(monthly)
        return replacement

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

    def _send_history(
        self, req_id: int, contract: Any, end: str, duration: str, size: str,
        data_type: str, regular: int, date_format: int, live: bool,
    ) -> None:
        key = (getattr(contract, "conId", 0), getattr(contract, "symbol", ""),
               getattr(contract, "exchange", ""), end, duration, size, data_type, regular)
        self._pacer.acquire(key, small=size == "30 secs", stop=self._pacing_stop)
        self.reqHistoricalData(
            req_id, contract, end, duration, size, data_type, regular, date_format, live, []
        )

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

    def option_chain(self, symbol: str, *, primary_exchange: str = "") -> OptionChain:
        """Fetch chain definitions, without enumerating or quoting every combination."""
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("Option-chain discovery requires a stock symbol")
        contract = self._resolve(symbol.strip().upper(), primary_exchange)
        if contract.secType != "STK" or contract.conId <= 0:
            raise DataError("Option-chain discovery requires a resolved stock/ETF underlying")
        req_id, request = self._new_request()
        request.chain_underlying = contract.conId
        try:
            self.reqSecDefOptParams(req_id, contract.symbol, "", "STK", contract.conId)
            self._wait(request)
            return OptionChain(
                contract.symbol, contract.conId, contract.currency,
                tuple(request.chain_groups[key] for key in sorted(request.chain_groups)),
                datetime.now(UTC),
            )
        finally:
            self._requests.pop(req_id, None)

    def securityDefinitionOptionParameter(
        self, reqId: int, exchange: str, underlyingConId: int, tradingClass: str,
        multiplier: str, expirations: set[str], strikes: set[float],
    ) -> None:
        request = self._requests.get(reqId)
        if request is None or request.chain_underlying is None or request.done.is_set():
            return
        try:
            multiple = _number(multiplier, allow_zero=False)
            if underlyingConId != request.chain_underlying or multiple is None:
                raise ValueError("Unexpected underlying or invalid contract multiplier")
            dates = {datetime.strptime(value, "%Y%m%d").date() for value in expirations}
            prices = {_number(value, allow_zero=False) for value in strikes}
            if None in prices or not exchange or not tradingClass:
                raise ValueError("Invalid exchange, trading class or strikes")
            key = (exchange, tradingClass, multiple)
            previous = request.chain_groups.get(key)
            if previous is not None:
                dates.update(previous.expirations)
                prices.update(previous.strikes)
            request.chain_groups[key] = OptionChainGroup(
                exchange, tradingClass, multiple, tuple(sorted(dates)),
                tuple(sorted(value for value in prices if value is not None)),
            )
        except (ValueError, TypeError, OverflowError) as exc:
            request.error = DataError(f"Invalid IBKR option-chain response: {exc}")
            request.done.set()

    def securityDefinitionOptionParameterEnd(self, reqId: int) -> None:
        request = self._requests.get(reqId)
        if request is not None and request.chain_underlying is not None:
            request.done.set()

    def _resolve_option(self, option: Option) -> Any:
        contract = Contract()
        contract.symbol, contract.secType = option.symbol, "OPT"
        contract.exchange, contract.currency = "SMART", "USD"
        contract.lastTradeDateOrContractMonth = option.expiry.strftime("%Y%m%d")
        contract.strike, contract.right = float(option.strike), option.right
        contract.tradingClass = option.trading_class
        if option.multiplier is not None:
            contract.multiplier = f"{option.multiplier:g}"
        req_id, request = self._new_request()
        try:
            self.reqContractDetails(req_id, contract)
            self._wait(request)
            if len(request.contracts) != 1:
                raise DataError(f"Expected one option contract, got {len(request.contracts)}. "
                                "Check expiry/strike/right and specify trading_class/multiplier "
                                "to disambiguate adjusted contracts.")
            return request.contracts[0]
        finally:
            self._requests.pop(req_id, None)

    @staticmethod
    def _quote_instrument(contract: Any, option: bool) -> QuoteInstrument:
        if contract.secType != ("OPT" if option else "STK") or contract.conId <= 0:
            raise DataError("IBKR returned an unexpected or unresolved quote contract")
        return QuoteInstrument(
            contract.symbol, contract.conId, "option" if option else "equity",
            contract.currency, contract.exchange, contract.primaryExchange,
            contract.localSymbol, contract.tradingClass,
            _number(contract.multiplier, allow_zero=False) if option else 1.0,
            contract.lastTradeDateOrContractMonth if option else None,
            float(contract.strike) if option else None, contract.right if option else None,
        )

    def _quote_contract(self, symbol: str | Option, primary_exchange: str) -> Any:
        if not isinstance(symbol, (str, Option)) or isinstance(symbol, str) and not symbol.strip():
            raise ValueError("Quote requires a stock symbol or explicit Option selector")
        if isinstance(symbol, Option):
            if primary_exchange:
                raise ValueError("Option selectors use trading_class/multiplier, "
                                 "not primary_exchange")
            return self._resolve_option(symbol)
        return self._resolve(symbol.strip().upper(), primary_exchange)

    def _set_quote_mode(self, market_data_type: str) -> None:
        # Caller owns _quote_lock. Active streams prevent connection-wide mode
        # changes; use separate Market connections for simultaneous different modes.
        active = {request.quote.requested_type for request in list(self._requests.values())
                  if request.quote is not None and request.quote.streaming
                  and request.quote.completed_at is None}
        if active and active != {market_data_type}:
            raise DataError("Active quote streams use another market_data_type. "
                            "Close them or use a separate Market connection.")
        if not active:
            self.reqMarketDataType(DATA_TYPES[market_data_type])

    def quote(
        self, symbol: str | Option, *, primary_exchange: str = "",
        market_data_type: str = "live",
    ) -> Quote:
        """Collect one standard Level-one snapshot; never request a regulatory snapshot."""
        if market_data_type not in DATA_TYPES:
            raise ValueError(f"market_data_type must be one of {', '.join(DATA_TYPES)}")
        with self._quote_lock:
            contract = self._quote_contract(symbol, primary_exchange)
            instrument = self._quote_instrument(contract, isinstance(symbol, Option))
            self._set_quote_mode(market_data_type)
            req_id, request = self._new_request()
            request.quote = _QuoteState(instrument, market_data_type)
            try:
                self.reqMktData(req_id, contract, "", True, False, [])
                self._wait(request)
                return request.quote.snapshot()
            finally:
                self._requests.pop(req_id, None)
                if request.quote.completed_at is None and self.isConnected():
                    self.cancelMktData(req_id)

    def stream_quote(
        self, symbol: str | Option, *, primary_exchange: str = "",
        market_data_type: str = "live",
        reconnect: bool = False,
    ) -> QuoteStream:
        """Subscribe without waiting for prices; errors/status arrive on the handle."""
        if market_data_type not in DATA_TYPES:
            raise ValueError(f"market_data_type must be one of {', '.join(DATA_TYPES)}")
        with self._quote_lock:
            contract = self._quote_contract(symbol, primary_exchange)
            instrument = self._quote_instrument(contract, isinstance(symbol, Option))
            self._set_quote_mode(market_data_type)
            req_id, request = self._new_request()
            request.quote = _QuoteState(instrument, market_data_type, streaming=True,
                                        reconnect=reconnect)
            stream = QuoteStream(request.quote, lambda: self._cancel_quote(req_id))
            try:
                self.reqMktData(req_id, contract, "", False, False, [])
                if request.error:
                    raise request.error
                return stream
            except Exception:
                self._cancel_quote(req_id)
                raise

    def detach_quote(self, stream: QuoteStream) -> None:
        """Remove this generation's callback route without closing the owner."""
        for req_id, request in list(self._requests.items()):
            if request.quote is stream._state:
                self._requests.pop(req_id, None)
                if self.isConnected():
                    self.cancelMktData(req_id)

    def restore_quote(self, stream: QuoteStream) -> None:
        """Restore the exact resolved contract into a fresh, empty generation."""
        state = stream._state
        with self._quote_lock, state.lock:
            if state.completed_at is not None:
                return
            instrument = state.instrument
            contract = Contract()
            contract.conId = instrument.instrument_id
            contract.symbol = instrument.symbol
            contract.secType = 'OPT' if instrument.asset_type == 'option' else 'STK'
            contract.exchange, contract.currency = instrument.exchange, instrument.currency
            contract.primaryExchange = instrument.primary_exchange
            self._set_quote_mode(state.requested_type)
            req_id, request = self._new_request()
            request.quote = state
            stream._cancel = lambda: self._cancel_quote(req_id)
            state.resume()
            try:
                self.reqMktData(req_id, contract, '', False, False, [])
                if request.error:
                    raise request.error
            except Exception:
                self.detach_quote(stream)
                state.interrupt('Quote subscription restore failed')
                raise

    def _cancel_quote(self, req_id: int) -> None:
        request = self._requests.pop(req_id, None)
        if request is not None and request.quote is not None:
            try:
                if self.isConnected():
                    self.cancelMktData(req_id)
            finally:
                request.quote.finish("closed")
                request.done.set()

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: Any) -> None:
        request = self._requests.get(reqId)
        if request is not None and request.quote is not None:
            state = request.quote
            with state.lock:
                if self._requests.get(reqId) is request:
                    state.tick(tickType, price)

    def tickSize(self, reqId: int, tickType: int, size: Any) -> None:
        request = self._requests.get(reqId)
        if request is not None and request.quote is not None:
            state = request.quote
            with state.lock:
                if self._requests.get(reqId) is request:
                    state.tick(tickType, size, size=True)

    def marketDataType(self, reqId: int, marketDataType: int) -> None:
        request = self._requests.get(reqId)
        if request is not None and request.quote is not None:
            state = request.quote
            with state.lock:
                if (self._requests.get(reqId) is not request or state.completed_at is not None
                        or state.status == 'disconnected'):
                    return
                actual = {value: key for key, value in DATA_TYPES.items()}.get(marketDataType)
                if state.actual_type is not None and actual != state.actual_type:
                    state.values.clear()
                    state.receipts.clear()
                    state.tick_types.clear()
                    state.greeks.clear()
                    state.delayed = False
                    state.warnings.append("Market data type changed; earlier fields discarded.")
                state.actual_type = actual
                state.notify()

    def tickOptionComputation(
        self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float | None,
        delta: float | None, optPrice: float | None, pvDividend: float | None,
        gamma: float | None, vega: float | None, theta: float | None, undPrice: float | None,
    ) -> None:
        request = self._requests.get(reqId)
        if request is not None and request.quote is not None:
            state = request.quote
            with state.lock:
                if self._requests.get(reqId) is request:
                    state.computation(tickType, (impliedVol, delta, optPrice, pvDividend,
                                                gamma, vega, theta, undPrice))

    def tickSnapshotEnd(self, reqId: int) -> None:
        request = self._requests.get(reqId)
        if request is not None and request.quote is not None and not request.quote.streaming:
            with request.quote.lock:
                if request.quote.completed_at is None:
                    request.quote.completed_at = datetime.now(UTC)
                    request.quote.notify()
                request.done.set()

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
        _contract: Any | None = None,
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
        contract = self._resolve(symbol, primary_exchange) if _contract is None else _contract
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
        self._set_identity(series, contract)
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
            self._send_history(
                req_id,
                contract,
                end,
                source_duration,
                INTERVALS[interval],
                "TRADES",
                int(regular_hours),
                2,
                live,
            )
            self._wait(request)
            if not len(series) and not _allow_empty:
                raise DataError(
                    f"No bars returned for {symbol}; check data permissions and session."
                )
            series.status = "Subscribed to bar updates" if live else "Historical snapshot"
            series.connection_state = "subscribed" if live else "snapshot"
            request.initialized = True
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

    def bars_range(
        self, symbol: str, *, interval: str, bounds: HistoryRange,
        regular_hours: bool = True, primary_exchange: str = "", refresh: bool = False,
    ) -> BarSeries:
        if interval not in INTERVALS or not symbol.strip():
            raise ValueError("Provide a symbol and a supported bar interval")
        now = datetime.fromtimestamp(current_time(), UTC)
        ending = (
            bounds.end if isinstance(bounds.end, datetime)
            else datetime.combine(bounds.end, time.min, ZoneInfo("America/New_York"))
        )
        if ending > now:
            raise ValueError("A fixed historical range cannot end in the future")
        result = BarSeries(symbol.strip().upper(), interval)
        result.regular_hours = regular_hours
        result.primary_exchange = primary_exchange
        result.requested_start, result.requested_end = bounds.start, bounds.end
        result.duration = range_duration(bounds.start, bounds.end, "1min")
        result.download_complete = False
        cursor = bounds.end
        monthly: dict[date, Bar] = {}
        if interval == "1y":
            with self._history_lock:
                self._monthly_bars[result] = monthly
        contract = None
        while cursor > bounds.start:
            lower = max(bounds.start, range_page_start(cursor, interval))
            try:
                if contract is None:
                    contract = self._resolve(symbol.strip().upper(), primary_exchange)
                    self._set_identity(result, contract)
                page = self.bars(
                    symbol, interval=interval, duration=range_duration(lower, cursor, interval),
                    regular_hours=regular_hours, primary_exchange=primary_exchange,
                    refresh=refresh, _end=cursor, _allow_empty=True,
                    _contract=contract,
                )
            except (ConnectionError, DataError, OSError) as exc:
                result.status = "Historical range incomplete"
                result.error = f"Range download failed for [{lower}, {cursor}): {exc}"
                raise HistoricalRangeError(
                    result.error, result, remaining_start=bounds.start, remaining_end=cursor,
                ) from exc
            result.download_pages += 1
            result.download_cached_pages += int(page.cache_hit)
            if not len(page):
                result.empty_windows.append((lower, cursor))
            if interval == "1y":
                with self._history_lock:
                    for stamp, bar in self._monthly_bars.get(page, {}).items():
                        if lower <= date(stamp.year, 1, 1) < cursor:
                            monthly.setdefault(stamp, bar)
                    for year in {stamp.year for stamp in monthly}:
                        result.update(self._year_bar(monthly, year))
            else:
                # Newer pages win overlaps; fixed time windows still advance on empties.
                result.prepend(bar for bar in page.snapshot() if lower <= bar.timestamp < cursor)
            for warning in page.warnings:
                if warning not in result.warnings:
                    result.warnings.append(warning)
            cursor = lower
        result.download_complete = True
        result.status = "Historical range downloaded"
        if result.empty_windows:
            result.warnings.append(
                f"{len(result.empty_windows)} requested windows returned no bars; "
                "provider availability and trading sessions were not independently verified."
            )
        return result

    @staticmethod
    def _set_identity(series: BarSeries, contract: Any) -> None:
        series.instrument_id = int(contract.conId)
        series.currency, series.exchange = str(contract.currency), str(contract.exchange)
        series.primary_exchange = str(contract.primaryExchange)
        series.asset_type, series.multiplier = "equity", 1.0
        series.data_type, series.adjustment = "TRADES", "splits_only"
        series.session_timezone = "America/New_York"

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

    def restore_series(self, target: BarSeries) -> None:
        """Backfill from the last loaded candle and rebind callbacks atomically."""
        latest = target.snapshot()[-1].timestamp if len(target) else None
        now = datetime.now(UTC)
        days = (now.date() - latest.date()).days if isinstance(latest, datetime) else (
            (now.date() - latest).days if latest else 0
        )
        fresh = self.bars(
            target.symbol, interval=target.interval,
            duration=f"{max(2, days + 2)} D", live=True,
            regular_hours=target.regular_hours, primary_exchange=target.primary_exchange,
            refresh=True,
        )
        with self._history_lock:
            if target.interval == "1y":
                # Older source months are required to retain complete years.
                old_months = self._monthly_bars.get(target, {})
                monthly = self._monthly_bars[fresh]
                combined = {**old_months, **monthly}
                monthly.clear()
                monthly.update(combined)
                self._monthly_bars[target] = monthly
                for year in {stamp.year for stamp in monthly}:
                    target.update(self._year_bar(monthly, year))
            else:
                for bar in fresh.snapshot():
                    target.update(bar)
            for request in self._requests.values():
                if request.series is fresh:
                    request.series = target
            target.last_live_update = fresh.last_live_update
            target.error = None
            target.status = "Subscribed to bar updates (reconnected and backfilled)"
            target.connection_state = "subscribed"
            for warning in fresh.warnings:
                if warning not in target.warnings:
                    target.warnings.append(warning)

    def historicalData(self, reqId: int, bar: Any) -> None:
        with self._history_lock:
            self._historical_data(reqId, bar)

    def _historical_data(self, reqId: int, bar: Any) -> None:
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
        if (request := self._requests.get(reqId)) and request.series and not request.error:
            with request.series._lock:
                request.series.last_live_update = datetime.now(UTC)

    def load_sessions(
        self, series: BarSeries, *, before: datetime | None = None, recent_only: bool = False
    ) -> None:
        """Annotate bars with actual IBKR regular/extended session windows.

        Schedule failure never invalidates usable OHLCV. No local holiday calendar
        or standard-hours guess is substituted for missing provider metadata.
        """
        bars = series.snapshot()
        if not bars:
            return
        ending = before or datetime.now(UTC)
        earliest = (
            bars[0].timestamp if isinstance(bars[0].timestamp, datetime) and not recent_only
            else ending - timedelta(days=7)
        )
        days = max(1, (ending.date() - earliest.date()).days + 2)
        end = ending.strftime("%Y%m%d %H:%M:%S UTC") if before else ""
        try:
            contract = self._resolve(series.symbol, series.primary_exchange)
            incoming = []
            for regular in (True, False):
                req_id, request = self._new_request()
                request.regular_hours = regular
                try:
                    self._send_history(
                        req_id, contract, end, f"{days} D", "1 day", "SCHEDULE",
                        int(regular), 1, False,
                    )
                    self._wait(request)
                    incoming.extend(request.sessions)
                finally:
                    self._requests.pop(req_id, None)
                    if not request.done.is_set():
                        self.cancelHistoricalData(req_id)
            series.merge_sessions(incoming)
            series.schedule_error = None
        except (ConnectionError, DataError, ValueError, OSError) as exc:
            series.schedule_error = f"Session schedule unavailable: {exc}"

    def historicalSchedule(
        self, reqId: int, startDateTime: str, endDateTime: str,
        timeZone: str, sessions: list[Any],
    ) -> None:
        if (request := self._requests.get(reqId)) is None:
            return
        try:
            zone = ZoneInfo({"US/Eastern": "America/New_York"}.get(timeZone, timeZone))
            for session in sessions:
                start = datetime.strptime(session.startDateTime, "%Y%m%d-%H:%M:%S")
                end = datetime.strptime(session.endDateTime, "%Y%m%d-%H:%M:%S")
                start = start.replace(tzinfo=zone).astimezone(UTC)
                end = end.replace(tzinfo=zone).astimezone(UTC)
                if end <= start:
                    raise ValueError("Session end must follow its start")
                request.sessions.append(dict(
                    start=int(start.timestamp()), end=int(end.timestamp()),
                    date=datetime.strptime(session.refDate, "%Y%m%d").date().isoformat(),
                    regular=request.regular_hours,
                ))
        except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
            request.error = DataError(f"Invalid IBKR session schedule: {exc}")
        request.done.set()

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
        if errorCode == 1102:
            # IBKR explicitly reports that subscriptions were maintained.
            for active in list(self._requests.values()):
                if active.series is not None and active.series.live and active.initialized:
                    active.error = None
                    active.series.error = None
                    active.series.status = "Subscribed to bar updates"
                    active.series.connection_state = "subscribed"
            return
        if errorCode in {1100, 1101, 1300}:
            self._fail_pending(ConnectionError(message + "; waiting for connection recovery."))
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
        if request.quote is not None and errorCode in {10090, 10091, 10167}:
            with request.quote.lock:
                if self._requests.get(reqId) is not request:
                    return
                request.quote.warnings.append(message)
                request.quote.notify()
            return
        if errorCode in {2174, 2176, 2188, 10167}:
            if request.series is not None:
                request.series.warnings.append(message)
            if request.quote is not None:
                with request.quote.lock:
                    if self._requests.get(reqId) is not request:
                        return
                    request.quote.warnings.append(message)
                    request.quote.notify()
            return
        request.error = DataError(message)
        if request.quote is not None and request.quote.streaming:
            with request.quote.lock:
                if self._requests.get(reqId) is not request:
                    return
                request.quote.finish("failed", message)
        if request.series is not None:
            request.series.error = message
            request.series.status = "Data request failed"
        request.done.set()

    def _fail_pending(self, error: Exception) -> None:
        with self._request_lock:
            requests = list(self._requests.items())
        for req_id, request in requests:
            request.error = error
            if request.quote is not None and request.quote.streaming:
                with request.quote.lock:
                    if self._requests.get(req_id) is not request:
                        continue
                    if request.quote.reconnect and not self._closing:
                        request.quote.interrupt(str(error))
                    else:
                        request.quote.finish("closed" if self._closing else "disconnected",
                                             str(error))
            if request.series is not None:
                request.series.error = str(error)
                request.series.status = "Disconnected"
                request.series.connection_state = "disconnected"
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
                series.connection_state = "closed"

    def close(self) -> None:
        self._closing = True
        self._pacing_stop.set()
        for req_id, request in list(self._requests.items()):
            if request.series is not None and request.series.live and self.isConnected():
                self.cancelHistoricalData(req_id)
            if (request.quote is not None
                    and (request.quote.streaming or request.quote.completed_at is None)
                    and self.isConnected()):
                self.cancelMktData(req_id)
        self.disconnect()
        self._fail_pending(ConnectionError("Market connection closed"))
        if self._thread is not None:
            self._thread.join(timeout=2)
