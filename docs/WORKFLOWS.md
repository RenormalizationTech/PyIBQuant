# Paper trading operating guide

[Documentation home](README.md) · [Paper API reference](PAPER_TRADING.md) ·
[Strategy validation checklist](STRATEGY_LAB.md)

Use this sequence to observe an account, run a bounded paper strategy and recover
its exact saved identity. The API reference documents arguments; this page
explains the operating decisions. Commands assume an activated environment and
a confirmed paper TWS/Gateway setup.

## Paper setup and operating sequence

Start with the [quick-start connection setup](QUICKSTART.md#4-connect-to-ibkr-for-a-small-historical-request).
`Market` and `PaperBroker` use separate client IDs. The shipped profile is an
example configuration, not an instruction to adopt a particular strategy or cap.
Keep your account-specific profile under ignored `charts/`.

```sh
python examples/paper_preflight.py --profile examples/paper_aapl.json
python examples/paper_preflight.py --profile examples/paper_aapl.json --connect
python examples/paper_account.py --snapshot
```

The first command checks local setup; the second adds read-only broker checks.
Both keep transmission disabled. The account snapshot records observations and
reports. Passing preflight does not establish that the next quote will be fresh
or that a particular order will be accepted or filled.

Observe the one-minute SMA runner:

```sh
python examples/paper_strategy.py --profile examples/paper_aapl.json --seconds 180
```

Historical candles warm the signal; only newly completed eligible live candles
can drive decisions. A regular-session run may still produce no entry. Inspect
status, reasons, warnings and data receipts before enabling execution.

To deliberately enable a bounded paper run after reviewing the profile, account,
funding and live data:

```sh
python examples/paper_strategy.py --profile examples/paper_aapl.json --execute
```

This command can send paper orders. Preserve the printed run ID and journal.
The profile's caps, lifetime order budget, duration and cleanup policy apply;
process restarts do not reset them. The provided strategy is above-SMA equity
long/flat, not a general live callback engine.

## Cash account versus margin account without borrowing

The broker combines fresh USD financial fields with a durable local cash ceiling.
Buying power alone is not an instrument-specific approval. Unknown fees retain a
reserve; buy fills debit actual premium/share cash, and unresolved orders retain
commitments until terminal evidence permits release.

A margin account with a no-borrowing strategy remains a margin account. Account
structure fields do not independently establish settlement behavior. Configure the
policy for the intended account rather than inferring it from one paper session.

The default `SettlementPolicy` uses a conservative local business-day release rule
for USD stocks/selected long options, with bounded 2026–2027 closure coverage.
It is a local spending constraint, not a statement that all products have identical
broker settlement rules. Fresh broker restrictions remain an independent cap;
deposits and other external credits do not automatically increase the local ceiling.
Inspect `broker.funding()` for usable cash, fee reserve, obligations and blockers.
See [the policy API](PAPER_TRADING.md#settlement-policy) for configuration.

## Recovery, ownership and audit APIs

An order ID is not a fill. A cancellation request is not confirmation. Missing,
conflicting or uncertain execution evidence blocks new exposure. Use the original
journal and exact run/check identity; do not delete the database or start a
replacement journal to bypass an unresolved outcome.

`broker.reconcile()` refreshes broker evidence. Review its snapshot, working,
missing and foreign orders plus the strategy ledger. Ledger quantity completeness
and fee completeness are separate. Account P&L can include manual holdings;
strategy attribution uses durable tags and actual executions.

## Restart recovery

Replace `RUN_ID` below with your saved run identity:

```sh
# Inspect/reconcile the saved run in paused, read-only mode.
python examples/paper_strategy.py --profile examples/paper_aapl.json --resume-run RUN_ID

# Explicitly resume paper execution under the original limits.
python examples/paper_strategy.py --profile examples/paper_aapl.json --resume-run RUN_ID --execute
```

The inspection path does not open a strategy feed or submit orders. Restore keeps
instrument identity, ownership, original caps and consumed order count. Resume
requires fresh reconciliation and risk evidence and skips paused candles.
A later trading date additionally requires `--new-session --execute`; review the
new daily baseline and retained lifetime order budget first. This is explicit
session recovery, not automatic broker reconnection or blind order replay.

## Pausing, stopping and explicit exits

Python runners expose `pause()`, `resume()` and `stop()`. The example command
stops when its duration ends or when interrupted with Ctrl+C. Pending-order
cleanup follows `cancel_on_stop`; filled holdings remain until an explicit exit.
Do not assume process termination made the account flat.

```sh
# Read-only plan for this exact run's reconciled holdings.
python examples/paper_flatten.py --profile examples/paper_aapl.json --run-id RUN_ID

# Deliberately submit the eligible owned-position exit.
python examples/paper_flatten.py --profile examples/paper_aapl.json --run-id RUN_ID --execute
```

Foreign/mixed holdings, stale prices or ownership mismatches block the exit.
Inspect terminal state, fills, fees and a fresh account snapshot afterward. An
exit attempt may remain unfilled; it does not guarantee liquidation.

## Paper cancellation check and recovery

The standalone cancellation harness defaults to read-only:

```sh
python examples/paper_cancel_check.py --profile examples/paper_aapl.json
```

With `--execute`, a new check deliberately submits a bounded resting limit BUY,
waits for acknowledgment and cancels that exact order. A fill can win the race;
no automatic sell/replacement is submitted. Read the script's `--help` and inspect
the plan before choosing this execution check.

Recover an **executed** check with its original ID, not by repeating entry:

```sh
python examples/paper_cancel_check.py --profile examples/paper_aapl.json --resume-check CHECK_ID
python examples/paper_cancel_check.py --profile examples/paper_aapl.json --resume-check CHECK_ID --execute
```

Read-only recovery only inspects/reconciles. Execution recovery cancels/waits on
the original eligible order. A deliberate `--disconnect-after-send` check can leave
a working/filled order and is an advanced recovery exercise, not a beginner task.
Unknown outcomes retain commitments and require reconciliation.

## Automated selected-option strategies

`OptionRunner` uses a live one-minute underlying signal and a separate exact-option
quote for premium execution. Select a valid unexpired contract yourself; there is
no automatic chain selection, rolling, exercise, assignment or expiry-day execution.
The five-cent default premium grid is still checked against actual broker rules.
A put does not automatically invert the selected above/below-SMA signal.

```sh
python examples/paper_option_strategy.py --help
python examples/paper_option_check.py --help
```

Supply `--expiry`, `--strike`, `--right` and, for the strategy example,
`--entry-when above_sma` or `below_sma`. Omitting `--execute` observes/inspects.
Explicit execution uses one long contract, its actual multiplier and the same
funding, ownership, session and restart controls. Option limits are premiums per
unit; full notional includes quantity and multiplier. Choose caps appropriate to
the selected contract; do not weaken checks merely to obtain a fill.

## Offline account and run reports

```sh
python examples/paper_report.py --output charts/paper/review.html
```

After stopping, rebuild reports from the saved journal without TWS. Compare actual
orders/fills with strategy decisions and investigate rejection/missing-data reasons.
Paper fills model a broker simulator and do not validate live execution quality.

## Stopping for the day and local data

Record the final run status, filled/working quantities, reconciliation and ledger
fee completeness. Retain the original journal/checkpoints and exact recovery
identities. Stop the owning process before moving journals; do not delete SQLite
WAL files while a process is using the database. Use consistent database backups.

Keep account-specific profiles, journals, reports and recovery IDs outside Git and
outside `docs/`, which is published as the website. Generated artifacts default
to ignored `charts/`. A later-date run needs an explicit session decision and
fresh observations; saved account balances are never current spendable funds.
