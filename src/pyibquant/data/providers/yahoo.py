"""Optional daily chart previews; IBKR remains the research data provider."""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

from ...bars import Bar, BarSeries
from ...errors import DataError

PREVIEW_WARNING = (
    "Yahoo Finance preview only (via unofficial yfinance, for personal research). "
    "Prices are split/dividend adjusted and may differ from IBKR. Coverage and accuracy "
    "are not verified; the latest daily bar may be incomplete. "
    "No live updates, session schedules, or historical options."
)


def _start_date(end: date, duration: str) -> date:
    match = re.fullmatch(r"([1-9][0-9]*)\s+([DWMY])", duration.strip())
    if match is None:
        raise ValueError("Yahoo preview duration must be a positive D/W/M/Y lookback, e.g. '1 Y'")
    count, unit = int(match[1]), match[2]
    try:
        if unit in {"D", "W"}:
            return end - timedelta(days=count * (7 if unit == "W" else 1))
        months = end.year * 12 + end.month - 1 - count * (12 if unit == "Y" else 1)
        year, month = divmod(months, 12)
        return date(year, month + 1, min(end.day, monthrange(year, month + 1)[1]))
    except (ValueError, OverflowError) as exc:
        raise ValueError("Yahoo preview duration is outside the supported calendar") from exc


def preview_bars(symbol: str, *, duration: str = "1 Y", timeout: float = 30) -> BarSeries:
    """Download a daily US equity/ETF snapshot without TWS or the IBKR SDK.

    Imported only by the explicit CLI preview path. This is deliberately not a
    Market provider: it supplies no broker connection, recovery or subscriptions.
    """
    symbol = symbol.strip().upper()
    if not symbol or timeout <= 0:
        raise ValueError("Use a nonempty symbol and positive timeout")
    end = datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)
    start = _start_date(end, duration)
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError(
            "Yahoo preview requires the optional dependency. "
            "Install with: python -m pip install -e '.[yahoo]'"
        ) from exc

    try:
        ticker = yf.Ticker(symbol)
        frame = ticker.history(
            start=start.isoformat(), end=end.isoformat(), interval="1d",
            auto_adjust=True, back_adjust=False, actions=False, repair=False, timeout=timeout,
        )
        if frame is None or frame.empty:
            raise DataError(
                f"Yahoo returned no preview data for {symbol}; check symbol/access limits"
            )
        metadata = ticker.get_history_metadata()
        if (metadata.get("currency") != "USD"
                or metadata.get("exchangeTimezoneName") != "America/New_York"
                or metadata.get("instrumentType") not in {"EQUITY", "ETF"}):
            raise DataError("Yahoo preview currently supports US stocks/ETFs in USD only")
        columns = ["Open", "High", "Low", "Close", "Volume"]
        if not set(columns).issubset(frame.columns):
            raise DataError("Yahoo preview response is missing OHLCV columns")
        series = BarSeries(symbol, "1d")
        series.provider = "Yahoo Finance · Preview"
        series.currency = "USD"
        series.asset_type = "equity"
        series.multiplier = 1
        series.session_timezone = "America/New_York"
        series.data_type = "TRADES"
        series.adjustment = "splits_and_dividends"
        series.duration = duration
        series.requested_start, series.requested_end = start, end
        series.warnings.append(PREVIEW_WARNING)
        skipped = 0
        for stamp, row in frame[columns].iterrows():
            values = [float(value) for value in row]
            if not all(isfinite(value) for value in values[:4]):
                skipped += 1
                continue
            # Keep the exchange session date; converting midnight to UTC first
            # would manufacture a timestamp for what is a calendar-date bar.
            day = stamp.date()
            if start <= day < end:
                series.update(Bar(
                    day, values[0], values[1], values[2], values[3],
                    values[4] if isfinite(values[4]) else None,
                ))
        if not len(series):
            raise DataError(f"Yahoo returned no usable preview prices for {symbol}")
        if skipped:
            series.warnings.append(f"Skipped {skipped} rows with missing/nonfinite OHLC prices.")
        # A successful HTTP response does not establish complete market coverage.
        series.download_complete = None
        series.download_pages = 1
        series.status = "Yahoo historical preview"
        return series
    except DataError:
        raise
    except Exception as exc:
        raise DataError(f"Yahoo preview failed for {symbol}: {exc}") from exc
