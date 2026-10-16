"""Small research calculations on collected values, independent of a broker/chart."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from math import isfinite
from statistics import fmean


def _values(values: Iterable[float]) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not all(isfinite(value) for value in result):
        raise ValueError("Research inputs must be finite numbers")
    return result


def simple_returns(closes: Iterable[float]) -> tuple[float | None, ...]:
    """Close-to-close fractional returns; first/zero-denominator results are None."""
    values = _values(closes)
    result = tuple(
        None if index == 0 or values[index - 1] == 0
        else value / values[index - 1] - 1
        for index, value in enumerate(values)
    )
    if any(value is not None and not isfinite(value) for value in result):
        raise ValueError("Return calculation overflowed; rescale or inspect the input values")
    return result


def sma(values: Iterable[float], window: int = 20) -> tuple[float | None, ...]:
    """Trailing simple mean including the current value; warm-up results are None."""
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        raise ValueError("window must be a positive integer")
    trailing: deque[float] = deque(maxlen=window)
    output: list[float | None] = []
    for value in _values(values):
        trailing.append(value)
        output.append(fmean(trailing) if len(trailing) == window else None)
    return tuple(output)
