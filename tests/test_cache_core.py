"""Parquet and CLI tests requiring no broker SDK or account."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from subprocess import run
from sys import executable
from unittest.mock import MagicMock, Mock, patch

import pytest

pytest.importorskip("pyarrow")

from pyibquant import Bar, HistoricalCache
from pyibquant.cli import main
from pyibquant.errors import CacheError


@pytest.fixture
def cache(tmp_path):
    return HistoricalCache(tmp_path / "cache")



@pytest.fixture
def query():
    return {"provider": "synthetic", "symbol": "DEMO", "interval": "1min", "end": "fixed"}



@pytest.mark.parametrize("stamp", [date(2026, 10, 15), datetime(2026, 10, 15, 14, 30, tzinfo=UTC)])
def test_parquet_roundtrip_metadata_and_deferred_directory(cache, query, stamp):
    bars = (Bar(stamp, 100, 103, 99, 102, 1000),)
    assert cache.get(query) is None
    assert not cache.directory.exists()
    cache.put(query, bars)
    entry = cache.get(query)
    assert entry.bars == bars
    assert entry.created_at.tzinfo == UTC
    metadata = cache.inspect()[0]
    assert metadata["query"] == query
    assert metadata["rows"] == 1
    assert not metadata["expired"]
    assert metadata["first"] == stamp.isoformat()
    assert metadata["bytes"] > 0



def test_expiry_relative_cap_future_clock_and_cannot_extend_written_ttl(cache, query):
    bars = [Bar(date(2026, 10, 15), 100, 103, 99, 102, 1)]
    with patch("pyibquant.data.cache.time.time", return_value=1000):
        cache.put(query, bars)
        cache.put({**query, "end": ""}, bars)
    with patch("pyibquant.data.cache.time.time", return_value=1300):
        assert cache.get(query) is not None
        assert cache.get({**query, "end": ""}) is None  # Relative snapshots: at most five minutes.
        assert HistoricalCache(cache.directory, max_age=100).get(query) is None
    with patch("pyibquant.data.cache.time.time", return_value=999):
        assert cache.get(query) is None  # Clock moved backwards.
    with patch("pyibquant.data.cache.time.time", return_value=87400):
        assert HistoricalCache(cache.directory, max_age=172800).get(query) is None
        assert cache.inspect()[0]["expired"]



def test_exact_query_keys_do_not_mix_hours_contracts_or_bar_sizes(cache, query):
    bars = [Bar(date(2026, 10, 15), 100, 103, 99, 102, 1)]
    cache.put(query, bars)
    for field, value in [
        ("regular_hours", False),
        ("contract_id", 42),
        ("interval", "1w"),
        ("end", "another"),
        ("symbol", "OTHER"),
    ]:
        assert cache.get({**query, field: value}) is None
    assert cache.get(dict(reversed(list(query.items())))).bars == tuple(bars)



def test_corrupt_entry_and_query_mismatch_are_not_returned(cache, query):
    bars = [Bar(date(2026, 10, 15), 100, 103, 99, 102, 1)]
    cache.put(query, bars)
    path = cache.directory / cache.inspect()[0]["file"]
    target = cache._path({**query, "symbol": "OTHER"})
    target.write_bytes(path.read_bytes())
    with pytest.raises(CacheError, match="does not match"):
        cache.get({**query, "symbol": "OTHER"})
    path.write_bytes(b"not a parquet file")
    with pytest.raises(CacheError):
        cache.get(query)
    assert "error" in next(row for row in cache.inspect() if row["file"] == path.name)



def test_schema_and_invalid_bar_data_are_rejected(cache, query):
    import pyarrow as pa
    import pyarrow.parquet as pq

    bars = [Bar(date(2026, 10, 15), 100, 103, 99, 102, 1)]
    cache.put(query, bars)
    path = cache._path(query)
    table = pq.read_table(path)
    bad = pa.table({"unexpected": [1]}).replace_schema_metadata(table.schema.metadata)
    pq.write_table(bad, path)
    with pytest.raises(CacheError, match="schema"):
        cache.get(query)
    rows = table.to_pylist()
    rows[0]["close"] = float("nan")
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    with pytest.raises(CacheError):
        cache.get(query)



def test_atomic_failed_replacement_keeps_existing_file_and_cleans_temporary(cache, query):
    old = (Bar(date(2026, 10, 15), 100, 103, 99, 102, 1),)
    cache.put(query, old)
    with patch("pyibquant.data.cache.os.replace", side_effect=OSError("write denied")):
        with pytest.raises(CacheError):
            cache.put(query, [Bar(date(2026, 10, 15), 100, 105, 99, 104, 2)])
    assert cache.get(query).bars == old
    assert not list(cache.directory.glob(".pyibquant-*"))



def test_no_negative_cache_clear_is_namespaced_and_inspection_is_safe(cache, query):
    cache.put(query, [])
    assert not cache.directory.exists()
    cache.put(query, [Bar(date(2026, 10, 15), 100, 103, 99, 102, 1)])
    unrelated = cache.directory / "other.parquet"
    unrelated.write_text("unrelated")
    corrupt = cache.directory / "pyibquant-v1-corrupt.parquet"
    corrupt.write_text("bad")
    assert len(cache.inspect()) == 2
    assert cache.clear() == 2
    assert unrelated.read_text() == "unrelated"
    assert cache.clear() == 0



@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_cache_lifetime(value, tmp_path):
    with pytest.raises(ValueError):
        HistoricalCache(tmp_path, max_age=value)



def test_basic_package_import_does_not_load_optional_dependencies():
    result = run(
        [
            executable,
            "-c",
            "import sys; import pyibquant; "
            "assert 'ibapi' not in sys.modules; assert 'pyarrow' not in sys.modules; "
            "assert 'pandas' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr



def test_missing_optional_dependency_has_an_actionable_error(tmp_path):
    import builtins

    original = builtins.__import__

    def without_arrow(name, *args, **kwargs):
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=without_arrow):
        with pytest.raises(ImportError, match=r"pyibquant\[cache\]"):
            HistoricalCache(tmp_path)



def test_concurrent_writers_publish_complete_entries(cache, query):
    def write_and_read(value):
        cache.put(query, [Bar(date(2026, 10, 15), 100, 110, 99, value, 1)])
        result = cache.get(query)
        assert len(result.bars) == 1
        assert result.bars[0].close in {101, 102, 103, 104}

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(write_and_read, [101, 102, 103, 104]))
    assert len(cache.inspect()) == 1
    assert not list(cache.directory.glob(".pyibquant-*"))



def test_cache_cli_inspection_and_clear_do_not_connect(tmp_path, monkeypatch, capsys):
    cache = HistoricalCache(tmp_path)
    cache.put({"end": "fixed"}, [Bar(date(2026, 10, 15), 100, 103, 99, 102, 1)])
    monkeypatch.setattr("pyibquant.cli.Market.ibkr", Mock(side_effect=AssertionError("connection")))
    monkeypatch.setattr("sys.argv", ["pyibquant", "cache", "inspect", "--cache-dir", str(tmp_path)])
    assert main() == 0
    assert '"rows": 1' in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["pyibquant", "cache", "clear", "--cache-dir", str(tmp_path)])
    assert main() == 0
    assert "Removed 1" in capsys.readouterr().out
    assert cache.inspect() == []



@pytest.mark.parametrize("disabled", [False, True])
def test_cli_cache_flags_are_explicit(tmp_path, monkeypatch, disabled):
    market = MagicMock()
    market.__enter__.return_value = market
    market.bars.return_value.__len__.return_value = 1
    connect = Mock(return_value=market)
    monkeypatch.setattr("pyibquant.cli.Market.ibkr", connect)
    args = ["pyibquant", "chart", "AAPL", "--no-browser", "--cache-dir", str(tmp_path)]
    if disabled:
        args.append("--no-cache")
    else:
        args.append("--refresh-cache")
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    assert connect.call_args.kwargs["cache_dir"] == (None if disabled else Path(tmp_path))
    assert connect.call_args.kwargs["refresh_cache"] == (not disabled)

