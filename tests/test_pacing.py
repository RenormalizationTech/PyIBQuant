from threading import Event
from unittest.mock import Mock

import pytest

from pyibquant.data.providers._pacing import HistoryPacer
from pyibquant.errors import ConnectionError


def clock_and_stop(monkeypatch):
    now = [0.0]
    monkeypatch.setattr('pyibquant.data.providers._pacing.monotonic', lambda: now[0])

    def advance(seconds):
        now[0] += seconds
        return False

    stop = Mock()
    stop.wait.side_effect = advance
    return now, stop


def test_small_bar_requests_respect_global_and_identical_spacing(monkeypatch):
    now, stop = clock_and_stop(monkeypatch)
    pacer = HistoryPacer()
    pacer.acquire(('one',), small=True, stop=stop)
    assert now[0] == 0
    pacer.acquire(('two',), small=True, stop=stop)
    assert now[0] == 11
    pacer.acquire(('two',), small=True, stop=stop)
    assert now[0] == pytest.approx(26.1)
    pacer.acquire(('three',), small=True, stop=stop)
    assert now[0] == pytest.approx(37.1)
    assert ('one',) not in pacer._identical  # Old keys do not grow memory unboundedly.


def test_normal_bars_have_soft_spacing_and_close_interrupts_pacing(monkeypatch):
    now, stop = clock_and_stop(monkeypatch)
    pacer = HistoryPacer()
    pacer.acquire(('one',), small=False, stop=stop)
    pacer.acquire(('two',), small=False, stop=stop)
    assert now[0] == 0.25
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ConnectionError, match='interrupted'):
        pacer.acquire(('three',), small=True, stop=cancelled)
