"""Explicit historical request selectors, independent of the broker SDK."""

from dataclasses import dataclass

from .quotes import Option


@dataclass(frozen=True)
class BarRequest:
    """Per-input selector/source for Market.datasets(), sharing range and sampling.

    A string instrument selects a US equity/ETF (TRADES only). An explicit Option
    also supports MIDPOINT, BID and ASK. primary_exchange is equity-only. No
    option contract universe, multiplier or history availability is inferred.
    """

    instrument: str | Option
    data_type: str = 'TRADES'
    primary_exchange: str = ''

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, (str, Option)):
            raise ValueError('instrument must be a symbol or explicit Option')
        if isinstance(self.instrument, str):
            if not self.instrument.strip():
                raise ValueError('instrument symbol must be nonempty')
            object.__setattr__(self, 'instrument', self.instrument.strip().upper())
        if not isinstance(self.data_type, str) or self.data_type not in {
            'TRADES', 'MIDPOINT', 'BID', 'ASK',
        }:
            raise ValueError('data_type must be TRADES, MIDPOINT, BID or ASK')
        if not isinstance(self.primary_exchange, str):
            raise ValueError('primary_exchange must be a string')
        object.__setattr__(self, 'primary_exchange', self.primary_exchange.strip().upper())
        if isinstance(self.instrument, Option):
            if self.primary_exchange:
                raise ValueError('primary_exchange is unsupported for option history')
        elif self.data_type != 'TRADES':
            raise ValueError('Equity history currently supports data_type=TRADES only')
