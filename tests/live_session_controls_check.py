"""Read-only live session controls and stock/option quote recovery.

Requires a regular market session. Disconnects only its own data socket.
Broker order methods are disabled; this does not validate execution recovery.
"""

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import Mock

from pyibquant import Market, Option, PaperBroker
from pyibquant.trading.runner import EquityRunner, RunnerConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expiry", type=date.fromisoformat, required=True)
    parser.add_argument("--strike", type=float, required=True)
    parser.add_argument("--seconds", type=float, default=360)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 180 <= args.seconds <= 1800:
        parser.error("Use a bounded duration between 180 and 1800 seconds")
    args.output.mkdir(parents=True, exist_ok=True)
    result = dict(started_at=datetime.now(UTC).isoformat(), passed=False, checks=[])

    def record(name, **details):
        result["checks"].append(dict(name=name, at=datetime.now(UTC).isoformat(), **details))
        print(f"PASS: {name}", flush=True)

    try:
        with PaperBroker.ibkr(
            client_id=305, readonly=True, journal=args.output / "account.sqlite3"
        ) as broker, Market.ibkr(client_id=306, timeout=20) as market:
            adapter = broker._adapter
            names = ("send_order", "placeOrder", "cancel_order", "cancelOrder")
            for name in names:
                setattr(adapter, name, Mock(side_effect=AssertionError("Read-only session check")))
            runner = None
            try:
                series = market.bars(
                    "AAPL", interval="1min", duration="1 D", live=True, include_sessions=True
                )
                option = Option("AAPL", args.expiry, args.strike, "C", "AAPL", 100)
                with market.stream_quote("AAPL", reconnect=True) as stock, market.stream_quote(
                    option, reconnect=True
                ) as derivative:
                    streams = (stock, derivative)

                    def ready():
                        at = datetime.now(UTC)
                        if not series.last_live_update or not (
                            0 <= (at - series.last_live_update).total_seconds() < 15
                        ):
                            return False
                        for stream in streams:
                            q = stream.latest()
                            stamps = dict(q.field_received_at)
                            if not (
                                q.status == "active" and q.market_data_type == "live"
                                and not q.is_delayed and not q.crossed
                                and q.bid is not None and q.ask is not None
                                and all(
                                    key in stamps
                                    and 0 <= (at - stamps[key]).total_seconds() < 15
                                    for key in ("bid", "ask")
                                )
                            ):
                                return False
                        return series.connection_state == "subscribed"

                    deadline = monotonic() + args.seconds
                    while not ready() and monotonic() < deadline:
                        sleep(.1)
                    assert ready(), "Fresh live stock/option quotes and bars unavailable"
                    at = datetime.now(UTC).timestamp()
                    assert any(
                        s["regular"] and s["start"] <= at < s["end"] for s in series.sessions
                    ), "Provider-confirmed regular session required"
                    identities = [s.latest().instrument for s in streams]
                    initial_sequences = [s.latest().sequence for s in streams]
                    record("Fresh live stock/option streams and provider regular session")
                    runner = EquityRunner(broker, RunnerConfig("AAPL"))
                    runner.start(series)
                    result["run_id"] = runner.run_id
                    phase = "first_signal"
                    pause_until = 0
                    first_count = 0
                    recovered_count = 0
                    original = None
                    while monotonic() < deadline:
                        runner.step(series, stock.latest())
                        signals = [
                            e for e in broker.journal.events(broker.account)
                            if e["kind"] == "signal"
                            and e["payload"].get("run_id") == runner.run_id
                        ]
                        if phase == "first_signal" and signals:
                            record("Completed live bar produced an observation signal")
                            runner.pause("Live read-only user-control check")
                            first_count = len(signals)
                            pause_until = monotonic() + 5
                            phase = "paused"
                        elif phase == "paused" and monotonic() >= pause_until:
                            assert len(signals) == first_count and runner.status == "paused"
                            runner.resume(series)
                            assert runner.status == "running"
                            record("Explicit pause suppresses decisions; resume succeeds")
                            original = market._provider
                            original.disconnect()
                            # EClient.disconnect completes connectionClosed before returning.
                            runner.step(series, stock.latest())
                            assert runner.status == "paused", "Disconnect did not pause runner"
                            record("Own data socket disconnect pauses runner")
                            phase = "recovering"
                        elif phase == "recovering" and market._provider is not original and ready():
                            for i, stream in enumerate(streams):
                                q = stream.latest()
                                assert q.instrument == identities[i]
                                assert q.generation >= 1 and q.sequence > initial_sequences[i]
                                assert q.gaps and all(g.ended_at is not None for g in q.gaps)
                                assert not stream.closed
                            assert runner.status == "paused", "Recovery silently resumed runner"
                            record("Stock/option identity, cursors and gaps survive recovery")
                            runner.resume(series)
                            recovered_count = len(signals)
                            record("Explicit runner resume after fresh recovered feeds")
                            phase = "next_signal"
                        elif phase == "next_signal" and len(signals) > recovered_count:
                            record("New completed-bar signal after recovery")
                            runner.stop()
                            count = len(signals)
                            runner.step(series, stock.latest())
                            assert runner.status == "stopped"
                            assert len([
                                e for e in broker.journal.events(broker.account)
                                if e["kind"] == "signal"
                                and e["payload"].get("run_id") == runner.run_id
                            ]) == count
                            record("Stop suppresses subsequent decisions")
                            phase = "complete"
                            break
                        elif runner.status == "paused" and phase not in {"paused", "recovering"}:
                            raise AssertionError(f"Unexpected runner pause: {runner.reason}")
                        sleep(.1)
                    assert phase == "complete", f"Bounded check ended in phase {phase}"
                    for i, stream in enumerate(streams):
                        (args.output / f"quote-{i}.json").write_text(
                            json.dumps(stream.latest().to_dict(), indent=2), encoding="utf-8"
                        )
                recovery = broker.reconcile()
                assert recovery.clear and recovery.snapshot.complete
                broker.report(args.output / "account.html")
                broker.export_strategy(runner.run_id, args.output / "strategy.json")
                for name in names:
                    getattr(adapter, name).assert_not_called()
                record("Clear final reconciliation; zero broker submissions or cancellations")
                result["passed"] = True
            finally:
                if runner is not None:
                    runner.stop()
                for name in names:
                    getattr(adapter, name).assert_not_called()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        (args.output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
