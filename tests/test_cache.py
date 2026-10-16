from unittest.mock import Mock

import pytest

pytest.importorskip("pyarrow")

from test_cache_core import cache as cache
from test_cache_core import query as query
from test_history import history, raw
from test_history import provider as provider

from pyibquant.errors import CacheError, DataError
from pyibquant.visualization.chart import render_chart


@pytest.fixture
def cached_provider(provider, cache):
    provider.cache = cache
    return provider


def test_snapshot_hit_refresh_and_normalized_queries(cached_provider):
    history(cached_provider, [raw("20261015")])
    first = cached_provider.bars(" aapl ", interval="1d", duration="1D")
    second = cached_provider.bars("AAPL", interval="1d", duration="1 D")
    assert not first.cache_hit
    assert second.cache_hit
    assert second.snapshot() == first.snapshot()
    assert second.cache_created_at in second.status
    assert cached_provider.reqHistoricalData.call_count == 1
    html = render_chart(second)
    assert "Historical snapshot (cached" in html
    assert second.cache_created_at in html
    assert '"cache_hit": true' in html
    history(cached_provider, [raw("20261015", close=106)])
    refreshed = cached_provider.bars("AAPL", interval="1d", refresh=True)
    assert not refreshed.cache_hit
    assert refreshed.snapshot()[0].close == 106
    assert cached_provider.bars("AAPL", interval="1d").snapshot() == refreshed.snapshot()
    assert cached_provider.reqHistoricalData.call_count == 1


def test_live_requests_never_read_or_write_cache(cached_provider):
    store = cached_provider.cache
    store.get, store.put = Mock(wraps=store.get), Mock(wraps=store.put)
    history(cached_provider, [raw("20261015")])
    series = cached_provider.bars("AAPL", interval="1d", live=True)
    assert not series.cache_hit
    assert series.status == "Subscribed to bar updates"
    store.get.assert_not_called()
    store.put.assert_not_called()


def test_corrupt_cache_falls_back_and_write_failure_keeps_broker_data(cached_provider):
    store = cached_provider.cache
    history(cached_provider, [raw("20261015")])
    cached_provider.bars("AAPL", interval="1d")
    path = store.directory / store.inspect()[0]["file"]
    path.write_bytes(b"bad")
    history(cached_provider, [raw("20261015", close=104)])
    series = cached_provider.bars("AAPL", interval="1d")
    assert series.snapshot()[0].close == 104
    assert not series.cache_hit
    assert "cache read failed" in series.warnings[0]
    store.put = Mock(side_effect=CacheError("disk full"))
    series = cached_provider.bars("AAPL", interval="1d", refresh=True)
    assert series.snapshot()[0].close == 104
    assert "cache write failed" in series.warnings[0]


def test_failed_refresh_does_not_overwrite_valid_cache(cached_provider):
    history(cached_provider, [raw("20261015")])
    original = cached_provider.bars("AAPL", interval="1d")
    cached_provider.reqHistoricalData = Mock(
        side_effect=lambda req_id, *args: cached_provider.error(req_id, 0, 162, "No permissions")
    )
    with pytest.raises(DataError):
        cached_provider.bars("AAPL", interval="1d", refresh=True)
    assert cached_provider.bars("AAPL", interval="1d").snapshot() == original.snapshot()


def test_cached_yearly_months_restore_and_extend_across_live_updates(cached_provider):
    history(cached_provider, [raw("20261001", volume=10), raw("20261101", volume=20)])
    cached_provider.bars("AAPL", interval="1y")
    hit = cached_provider.bars("AAPL", interval="1y")
    assert hit.cache_hit
    assert len(cached_provider._monthly_bars[hit]) == 2
    history(cached_provider, [raw("20250901", volume=50), raw("20260101", volume=40)])
    assert cached_provider.load_older(hit) == 1
    assert hit.snapshot()[-1].volume == 70
    # A fresh live subscription reuses that older page without replacing live data.
    history(cached_provider, [raw("20261001", volume=11), raw("20261101", volume=21)])
    live = cached_provider.bars("AAPL", interval="1y", live=True)
    live_id = cached_provider.reqHistoricalData.call_args.args[0]
    cached_provider.reqHistoricalData = Mock(
        side_effect=AssertionError("unexpected history download")
    )
    assert cached_provider.load_older(live) == 1
    assert live.history_cache_hit
    assert live.snapshot()[-1].volume == 72
    cached_provider.historicalDataUpdate(live_id, raw("20261101", close=106, volume=25))
    assert live.snapshot()[-1].volume == 76
    assert live.snapshot()[-1].close == 106
    assert not live.cache_hit
    cached_provider.reqHistoricalData.assert_not_called()


def test_run_level_refresh_bypasses_cache(cached_provider):
    history(cached_provider, [raw("20261015")])
    cached_provider.bars("AAPL", interval="1d")
    cached_provider.refresh_cache = True
    history(cached_provider, [raw("20261015", close=108)])
    assert cached_provider.bars("AAPL", interval="1d").snapshot()[0].close == 108
    assert cached_provider.reqHistoricalData.call_count == 1
