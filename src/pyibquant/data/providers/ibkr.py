"""Small, data-only adapter for the official TWS Python API (10.33+)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from typing import Any

from ...bars import Bar, BarSeries
from ...errors import ConnectionError, DataError, RequestTimeout

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
    "1d": "1 day",
}


@dataclass
class _Request:
    done: Event = field(default_factory=Event)
    contracts: list[Any] = field(default_factory=list)
    series: BarSeries | None = None
    error: Exception | None = None


def normalize_bar(raw: Any, interval: str) -> Bar:
    """formatDate=2 gives epoch seconds intraday, YYYYMMDD for daily bars."""
    timestamp = (
        datetime.strptime(str(raw.date), "%Y%m%d").date()
        if interval == "1d"
        else datetime.fromtimestamp(int(raw.date), UTC)
    )
    return Bar(
        timestamp,
        float(raw.open),
        float(raw.high),
        float(raw.low),
        float(raw.close),
        max(0.0, float(raw.volume)),
    )


class IBKRProvider(EWrapper, EClient):
    def __init__(self, host: str, port: int, client_id: int, timeout: float) -> None:
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
    ) -> BarSeries:
        symbol = symbol.strip().upper()
        if not symbol or interval not in INTERVALS:
            raise ValueError(f"Provide a symbol and an interval from {', '.join(INTERVALS)}")
        duration = re.sub(r"\s+", "", duration.upper())
        if not re.fullmatch(r"[1-9]\d*[SDWMY]", duration):
            raise ValueError("duration must look like '1 D', '2 W', or '6 M'")
        duration = f"{duration[:-1]} {duration[-1]}"
        contract = self._resolve(symbol, primary_exchange)
        series = BarSeries(symbol, interval, live=live)
        series.duration = duration
        series.regular_hours = regular_hours
        series.primary_exchange = primary_exchange
        req_id, request = self._new_request(series)
        try:
            self.reqHistoricalData(
                req_id,
                contract,
                "",
                duration,
                INTERVALS[interval],
                "TRADES",
                int(regular_hours),
                2,
                live,
                [],
            )
            self._wait(request)
            if not len(series):
                raise DataError(
                    f"No bars returned for {symbol}; check data permissions and session."
                )
            series.status = "Subscribed to bar updates" if live else "Historical snapshot"
            return series
        except BaseException:
            self.cancelHistoricalData(req_id)
            self._requests.pop(req_id, None)
            raise
        finally:
            if not live:
                self._requests.pop(req_id, None)

    def historicalData(self, reqId: int, bar: Any) -> None:
        request = self._requests.get(reqId)
        if request is None or request.series is None:
            return
        try:
            request.series.update(normalize_bar(bar, request.series.interval))
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
