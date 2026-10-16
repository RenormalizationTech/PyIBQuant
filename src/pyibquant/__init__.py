"""Market research without exposing brokerage API objects."""

from .bars import Bar, BarSeries
from .data.cache import HistoricalCache
from .dataset import BarDataset, CoverageAudit
from .errors import HistoricalRangeError
from .market import Market
from .options import OptionChain, OptionChainGroup
from .quote_recording import QuoteRecording, record_quotes
from .quote_recording_set import QuoteRecordingSet, record_quotes_rotating
from .quote_stream import QuoteStream
from .quotes import Option, Quote

__all__ = [
    "Bar", "BarDataset", "BarSeries", "CoverageAudit", "HistoricalCache", "HistoricalRangeError",
    "Market", "Option", "OptionChain", "OptionChainGroup", "Quote", "QuoteRecording",
    "QuoteRecordingSet", "QuoteStream", "record_quotes", "record_quotes_rotating",
]
