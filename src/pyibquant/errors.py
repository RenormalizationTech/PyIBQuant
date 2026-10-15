"""Errors callers can handle without importing a provider's SDK."""


class PyIBQuantError(Exception):
    """Base error."""


class ConnectionError(PyIBQuantError):
    """TWS connection failed or was lost."""


class DataError(PyIBQuantError):
    """A market-data request failed."""


class RequestTimeout(DataError):
    """The provider did not finish a request in time."""
