"""Small standard-library study starters; source data and assumptions stay visible."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from math import isfinite, log
from statistics import StatisticsError, correlation, fmean
from typing import Any
from zoneinfo import ZoneInfo

from .collection import BarDatasetCollection
from .dataset import BarDataset


def _usable(dataset: BarDataset) -> None:
    if not len(dataset) or dataset.metadata().get('download', {}).get('complete') is not True:
        raise ValueError('Study inputs must be nonempty with completed downloads')
    if any(bar.close <= 0 for bar in dataset.snapshot()):
        raise ValueError('Log-return studies require strictly positive closes')


def daily_correlations(inputs: BarDatasetCollection) -> dict[str, Any]:
    """Daily log-return panel and descriptive Pearson matrix, no dependencies.

    Returns are formed on adjacent UNION dates before listwise selection, so a
    missing instrument cannot silently acquire a multi-day return paired with a
    one-day return. Dates absent from every input remain unknown without a calendar.
    No filling, calendar inference, currency conversion or statistical inference.
    """
    for dataset in inputs.values():
        _usable(dataset)
        if dataset.metadata()['interval'] != '1d':
            raise ValueError('Daily correlations require daily inputs')
    aligned = inputs.align(join='outer')
    rows: list[dict[str, Any]] = []
    for i in range(1, len(aligned.timestamps)):
        values: dict[str, float | None] = {}
        for key, column in aligned.columns.items():
            current, previous = column[i], column[i - 1]
            values[key] = (log(current) - log(previous)
                           if current is not None and previous is not None else None)
        rows.append(dict(start=aligned.timestamps[i - 1].isoformat(),
                         end=aligned.timestamps[i].isoformat(), values=values))
    complete = [row for row in rows if all(value is not None for value in row['values'].values())]
    matrix: dict[str, dict[str, float | None]] = {}
    for left in inputs:
        matrix[left] = {}
        for right in inputs:
            value = None
            if len(complete) >= 2:
                try:
                    value = correlation([row['values'][left] for row in complete],
                                        [row['values'][right] for row in complete])
                except StatisticsError:
                    pass  # Constant series have undefined Pearson correlation, including self.
            matrix[left][right] = value
    return dict(
        schema_version=1, study='daily_log_return_correlations',
        settings=dict(price='close', return_type='log', alignment='adjacent_union_dates',
                      missing='no_fill', correlation_selection='listwise_complete'),
        quality=inputs.quality_report(join='outer'), returns=rows,
        correlation=dict(samples=len(complete), excluded_rows=len(rows) - len(complete),
                         matrix=matrix),
        notes=['Descriptive sample correlations; no significance or causal claims.',
               'Common missing market dates require an external expected calendar.',
               'Source currencies and adjustments are preserved, not harmonized.'],
    )


def intraday_scaling(
    dataset: BarDataset, *, lags: Iterable[int] = (1, 2, 4, 8),
    session_timezone: str | None = None,
) -> dict[str, Any]:
    """Export uninterrupted within-date log increments and first/second moments.

    Lag units are input bars. Every intermediate start must exist on the exact
    interval grid; endpoints must share a date in the stated timezone. This is
    a date boundary filter, not an exchange-calendar/session/finality audit.
    Overlapping increments are descriptive, not independent observations. No
    exponent fitting, Hurst estimate or multifractality conclusion is attempted.
    """
    _usable(dataset)
    metadata = dataset.metadata()
    spans = {'30s': 30, '1min': 60, '5min': 300, '15min': 900, '30min': 1800,
             '1h': 3600, '2h': 7200, '4h': 14400}
    if metadata['interval'] not in spans:
        raise ValueError('Scaling preparation requires fixed intraday intervals')
    selected = tuple(lags)
    if not selected or any(isinstance(lag, bool) or not isinstance(lag, int) or lag <= 0
                           for lag in selected) or len(set(selected)) != len(selected):
        raise ValueError('lags must be distinct positive whole numbers')
    zone_name = (session_timezone if session_timezone is not None
                 else metadata.get('session_timezone'))
    if not isinstance(zone_name, str) or not zone_name:
        raise ValueError('Supply an explicit session_timezone when source timezone is unknown')
    zone = ZoneInfo(zone_name)
    bars = dataset.snapshot()
    stamps = [bar.timestamp.astimezone(UTC) for bar in bars if isinstance(bar.timestamp, datetime)]
    if len(stamps) != len(bars):
        raise ValueError('Intraday inputs require datetime timestamps')
    span = spans[metadata['interval']]
    # Segment on a missing/irregular step or a local date change. Lag endpoints
    # in the same segment imply every intermediate bar start is present.
    segments = [0]
    for i in range(1, len(stamps)):
        broken = (stamps[i] - stamps[i - 1] != timedelta(seconds=span)
                  or stamps[i].astimezone(zone).date() != stamps[i - 1].astimezone(zone).date())
        segments.append(segments[-1] + int(broken))
    rows = []
    moments = []
    for lag in selected:
        values = []
        for i in range(lag, len(bars)):
            if segments[i] != segments[i - lag]:
                continue
            increment = log(bars[i].close) - log(bars[i - lag].close)
            values.append(increment)
            rows.append(dict(lag_bars=lag, elapsed_seconds=lag * span,
                             start=stamps[i - lag].isoformat(), end=stamps[i].isoformat(),
                             log_increment=increment))
        first = fmean(abs(value) for value in values) if values else None
        second = fmean(value * value for value in values) if values else None
        if any(value is not None and not isfinite(value) for value in (first, second)):
            raise ValueError('Moment calculation overflowed')
        moments.append(dict(lag_bars=lag, elapsed_seconds=lag * span, samples=len(values),
                            excluded_candidates=max(0, len(bars) - lag) - len(values),
                            mean_absolute_increment=first, mean_squared_increment=second))
    return dict(
        schema_version=1, study='intraday_log_increment_scaling',
        settings=dict(price='close', lags=list(selected), session_timezone=zone_name,
                      boundary='uninterrupted_grid_within_local_date', overlapping=True),
        quality=dataset.quality_report(), increments=rows, moments=moments,
        notes=['No filling/resampling; gaps and local date boundaries break sequences.',
               'Local dates are not an exchange session calendar; bar finality remains unverified.',
               'Overlapping increments are dependent; moments are descriptive only.',
               'No fitted scaling exponent or evidence of multifractality is claimed.'],
    )
