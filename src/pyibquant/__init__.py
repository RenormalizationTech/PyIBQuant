"""Market research without exposing brokerage API objects."""

from .bars import Bar, BarSeries
from .collection import AlignedData, BarDatasetCollection
from .data.cache import HistoricalCache
from .dataset import BarDataset, CoverageAudit
from .errors import DatasetCollectionError, HistoricalRangeError
from .market import Market
from .options import OptionChain, OptionChainGroup
from .quote_stream import QuoteStream
from .quotes import Option, Quote
from .requests import BarRequest

__all__ = [
    "AlignedData", "Bar", "BarDataset", "BarDatasetCollection", "BarSeries",
    "BarRequest", "CoverageAudit", "DatasetCollectionError", "HistoricalCache",
    "HistoricalRangeError",
    "Market", "Option", "OptionChain", "OptionChainGroup", "Quote", "QuoteStream",
]
