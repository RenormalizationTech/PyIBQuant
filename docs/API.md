# Python API guide

This describes implemented APIs in the `0.1.0.dev1` development snapshot.
`PROJECT_PLAN.md` also contains future concepts; those are not API promises.

## Choose the entry point

| Task | Import / API | Broker connection? |
|---|---|---|
| Acquire one instrument | `from pyibquant import Market`; `market.bars(...)` | Yes |
| Acquire named inputs | `market.datasets(...)`; optional `BarRequest` selectors | Yes |
| Freeze, save and reload bars | `BarDataset.from_series(series)`, `.save()`, `.load()` | No |
| Save/reload named inputs | `BarDatasetCollection`, `.save()`, `.load()` | No |
| Inspect quality | Dataset/collection `.describe()`, `.quality_report()` | No |
| Align observed starts | Collection `.align(join="outer" or "inner")` | No |
| Export aligned data | `.to_records()`; optional `.to_dataframe()` | No |
| Daily descriptive correlations | `from pyibquant.studies import daily_correlations` | No |
| Intraday increments/moments | `from pyibquant.studies import intraday_scaling` | No |
| Fixed-size daily equity backtest | `from pyibquant.backtest import backtest_equity` | No |
| Fixed-size intraday option backtest | `from pyibquant.option_backtest import backtest_option` | No |
| Strategy/portfolio simulation | `from pyibquant.simulation import Feed, TargetStrategy, NextOpen, simulate` | No |
| Stock/option snapshots or streams | `market.quote(...)`, `market.stream_quote(...)` | Yes |
| Paper account observation | `PaperBroker.ibkr()` (read-only by default) | Yes |
| Experimental paper execution | `broker.submit_limit(...)`, `.cancel(...)` | Yes |
| Selected long-option paper runner | `OptionRunner` in `pyibquant.trading.option_runner` | Yes |
| Completed-bar paper runner | `EquityRunner`, `RunnerConfig` in `pyibquant.trading.runner` | Yes |
| Optional chart | `series.plot(...)` offline; `market.serve(...)` for connected inspection | Depends |

Core offline workflows have no mandatory third-party dependencies. Broker access
requires the official manually installed IBKR SDK and logged-in TWS/Gateway.
`[pandas]` enables DataFrames, `[cache]` enables the Parquet query cache, `[dev]`
provides tests/lint/typing, and `[browser]` provides browser regression tools.

## Acquire once, inspect and reuse

```python
from pyibquant import BarDatasetCollection, Market
from pyibquant.studies import daily_correlations

with Market.ibkr() as market:
    inputs = market.datasets(
        {"apple": "AAPL", "microsoft": "MSFT", "benchmark": "SPY"},
        interval="1d", start="2025-01-01", end="2026-01-01",
    )
inputs.save("charts/research/inputs.collection.json")

# Independent of the connection, SDK and optional dependencies:
inputs = BarDatasetCollection.load("charts/research/inputs.collection.json")
quality = inputs.quality_report(join="outer")
rows = inputs.align(join="outer").to_records()
study = daily_correlations(inputs)
```

Bounds are start-inclusive/end-exclusive. Intraday timestamps normalize to UTC;
daily timestamps are calendar dates. Requests use fixed bounds, sequential
paging/pacing and optional exact-query caching. Collection labels are user names;
resolved contract identity remains in each dataset's metadata.

`Market.datasets()` returns only after every input is nonempty and its planned
download completed. `DatasetCollectionError.failed_key` names the first failed
input; `.completed` exposes earlier frozen inputs and `.__cause__` retains the
original error, including a `HistoricalRangeError`'s partial pages/bounds. Local
selector/mode errors raise `ValueError`. No files or retries are automatic.

For selected options, use `Option` or `BarRequest(option, data_type="MIDPOINT")`.
Only fixed intraday ranges are supported. No bulk chain history or expired-option
reconstruction is supplied. MIDPOINT/BID/ASK volume stays null and these bar sources
do not establish executable quote prices. Source, multiplier and exact identity
remain separate from user labels.

## Evidence and missing observations

`describe()` summarizes recorded identity, sampling, requested/observed coverage,
download progress and fingerprints. `quality_report()` adds observation flags,
provider warnings and optional caller calendar/finality assertions. Unknown
completeness stays unknown; completed request windows do not prove full market
coverage. Reports never repair prices or alter stored provenance.

`collection.quality_report(expected={label: expected_starts},
finalized_through={label: bound}, join="outer")` accepts assertions per input.
A dataset accepts the expected starts directly. Calendar checks compare exactly
those starts; no exchange calendar is inferred. Without a calendar, shared gaps
can remain invisible. Unknown assertion labels raise `ValueError`.

An outer join preserves all observed starts and represents absent values as
`None`; an inner join keeps the intersection. Both require compatible intervals,
timestamp kinds and session settings. Neither fills/resamples or harmonizes
currencies, adjustments or price sources. Reports expose differing semantics and
row losses. Incompatible or incomplete inputs still have quality reports, with an
unavailable-alignment reason when alignment is requested.

Daily study returns are formed on adjacent union dates before listwise selection;
missing inputs cannot silently create mismatched return periods. Pearson values
are descriptive; constants/insufficient samples produce null values.
Intraday study lags count bars and require uninterrupted grids within a stated
local date. Supply `session_timezone` when source metadata is unknown. These are
dependent overlapping increments and descriptive moments, without fitted scaling
exponents, Hurst estimates or multifractal conclusions.

## Simulation assertions and execution

The simple equity/option backtests consume frozen datasets and prior-close targets.
The general simulator consumes named `Feed` objects and a strategy callback:

```python
from datetime import date
from pyibquant.simulation import Feed, NextOpen, TargetStrategy, simulate

result = simulate(
    {"apple": Feed(inputs["apple"], finalized_through=date(2025, 12, 31))},
    TargetStrategy("apple", lambda context: 1),
    initial_cash=10000, execution=NextOpen(commission_per_unit=0.01),
    strategy_settings={"name": "hold_one"},
)
metrics = result.metrics()
result.save("charts/research/simulation.json")
```

Feed histories publish only completed bars; orders fill at subsequent supplied
opens. The initial portfolio ledger is long-only, USD, whole quantities, with
shared cash, market orders, cancellation and full-fill-or-defer execution models.
Costs, logs, fingerprints and settings are preserved. Synthetic fills do not
reconstruct spread/liquidity. Daily and intraday feeds cannot mix, and option
expiry/lifecycle, shorting, margin, FX and broker order placement are unsupported.

**Finality conventions:** `audit()`, quality reports and legacy option backtests
use an inclusive bar-start assertion. The general simulator requires intraday
finality through `start + interval`; a bar's start alone is insufficient. Daily
assertions use dates. None of these assertions independently verify finality.

## Runnable workflows and checks

- `examples/research_collection.py fetch` acquires bounded equity/ETF collections;
  `inspect` exports quality JSON and optionally aligned CSV offline.
- `examples/research_studies.py correlations` / `scaling` consume saved collections.
- `examples/backtest_equity.py`, `backtest_option.py`, `backtest_strategy.py` consume
  saved individual datasets. See each script's `--help` and README examples.
- `.venv/bin/python -m pytest -q`, `.venv/bin/ruff check src examples tests`,
  `.venv/bin/mypy` run local automated checks.
- `tests/browser_chart_check.py`, `browser_history_check.py` and
  `browser_sessions_check.py` use synthetic data in installed Chrome.
- `tests/live_workflow_check.py --help` describes a small explicit TWS-to-offline
  workflow check. It uses a separate client and writes only ignored generated data.
- `.venv/bin/python tests/build_check.py` builds a wheel/source archive from a
  temporary source copy, installs the wheel in an isolated SDK-free environment,
  runs the wheel smoke check and writes checksums under ignored `dist/`.

Generated data and `.venv` are machine-local and excluded from Git and source
archives. Development builds are local; no publication, remote push or tag is
implied. Only Python 3.14 has been exercised in this local release check; the
package declares Python 3.11+, without claiming a tested multi-version matrix.


## Paper account observation and experimental execution

The broker connection is independent of `Market` and offline simulation. It uses
a dedicated positive client ID, discovers managed accounts, and requires a selected
`DU...` paper account. Discovery selects automatically only when exactly one account
is visible. A DU identifier or paper port is a consistency check, not independent
proof of the environment; order mode additionally requires the caller's explicit
`paper_confirmed=True` assertion. Real-money accounts are not supported by this API.

```python
from pyibquant import PaperBroker

with PaperBroker.ibkr(journal="charts/paper/account.sqlite3") as broker:
    snapshot = broker.snapshot()           # immutable, independently copied observations
    print(snapshot.to_dict())              # masks account IDs by default
    print(broker.funding())                # broker fields and conservative USD cash budget
    broker.report("charts/paper/account.html")  # self-contained HTML plus CSV history
```

Initial synchronization waits for account, account-summary, positions, open-orders
and executions completion callbacks. Missing callbacks cause an explicit failure.
`wait_for_update(sequence, timeout=...)` permits independent observers.
Refresh retains the existing account-summary subscription and its confirmed readiness,
then redownloads account values, positions, orders and executions. It clears old
financial values while retaining base-currency/account-structure metadata. Recreating
summary subscriptions on every refresh can exhaust TWS's active-request limit before
asynchronous cancellation finishes; the adapter avoids that churn. Timeouts name the
missing download stages and include recent broker errors.
 Data fields
retain source/currency/receipt time; callbacks are journaled by a separate worker,
not on the API network thread. A field's receipt time does not certify a current
exchange valuation. P&L remains missing when the broker does not provide it.

For a live, read-only localhost view of account value, cash, broker P&L, positions,
orders and executions:

```sh
.venv/bin/python examples/paper_account.py
.venv/bin/python examples/paper_account.py --snapshot
```

The terminal prints a localhost URL. Ctrl+C saves a final report and stops the
observer. The view has no order endpoints. Its cards distinguish total/settled cash,
buying power, available funds, estimated unsettled cash/pending buys and usable cash.
History begins at observation; gaps/session boundaries are explicit. Total account
P&L includes pre-existing/manual positions. No cash-flow-adjusted returns or strategy
P&L are inferred. SQLite journals and reports contain private financial data and
belong outside Git; the defaults are under the ignored `charts/paper/` directory.
Reopening the same journal retains history, but account balances must download again.
A disconnect blocks new orders; restart the connection and reconcile explicitly.

### Cash account versus margin account without borrowing

A cash account is subject to the broker's cash/settlement restrictions. A margin
account with a strategy that avoids borrowing is still a margin account: the broker
may permit reinvestment of unsettled proceeds. Choosing not to borrow does not
convert its funding rules into cash-account rules. `AccountType` may describe legal
structure (for example `INDIVIDUAL`), so it must not be treated as proof of cash or
margin financing. The target live-account policy must be configured independently
of the simulated paper account's capabilities.

`BuyingPower` alone is not an instrument-specific approval. USD spending is capped
by the minimum of fresh broker settled cash, total USD cash, available funds and
buying power, and a durable local cash ceiling. The configured order limit is
separate. Financial fields older than 60 seconds, unresolved orders, conflicting
executions and missing fees block new exposure. Submissions refresh the account
and recheck funding under the local journal's transmission lock before persisting
an intent. Only one PyIBQuant nonterminal order is allowed at a time.

The first funded order journals a baseline and a complete copy of its settlement
policy before sending. Known buy fills debit the local ceiling immediately at
actual price and contract multiplier. Known positive USD fees debit it immediately;
unknown fees retain the order's allowance (default $2) and block new exposure until
confirmed. Partial fills consume actual cash and leave the unfilled limit-price
commitment reserved. Cancellation requests and unknown sends keep that commitment;
only terminal broker evidence releases the unfilled portion. Explicit holding-only
exits remain possible when funding blocks new exposure.

Sale proceeds produce dated, USD settlement obligations. The default versioned
`SettlementPolicy` uses a conservative local T+1 rule for both US stocks and
selected long options, skipping weekends and a union of market/banking closures
with bounded 2026–2027 coverage. This is deliberately stricter than IBKR's documented
US option T+0 cash availability; it is not a claim that every product uses stock
settlement. Outside calendar coverage, new buys are refused. Supply an explicit
bounded policy using `settlement_policy=SettlementPolicy(...)` when opening a new
journal/baseline; the journal retains its exact policy across restarts and rejects
an incompatible replacement. Import from `pyibquant.trading.funding`.

At the local release date the sale can increase the local ceiling, but fresh broker
funds must independently permit spending. Local commitments are not subtracted a
second time from broker balances: usable cash is the minimum of two independently
computed ceilings. `funding()` exposes `cash_ceiling`, `fee_reserve`,
`pending_buy_estimate`, `local_unsettled`, `settlement_obligations`, policy version,
coverage and blocking reasons. The account viewer includes settlement details.

Restart replays the baseline, intents, executions and late fees; it never reuses
old account balances as current funds. Local POSIX journal locks serialize sends;
a broker with unreplayed financial events must reopen/reconcile. This coordinates
one shared local journal, not copied journals or different machines. Legacy journals
without a baseline can establish one only after recorded fills/fees reconcile and
recorded sales have passed their local settlement dates. Missing or corrected
execution evidence blocks new exposure instead of being discarded.

The local ceiling covers recorded PyIBQuant fills after its baseline; it is not an
account statement or verified external-cash-flow ledger. Deposits, interest and
other external credits do not automatically raise it. Broker caps can always lower
spending. Advanced margin, FX and execution-correction normalization remain outside
this implementation.

On the tested TWS session, `SettledCashByDate` supplies USD
`YYYYMMDD:amount` entries when `SettledCash` is absent. The parser selects today's
New York balance, never tomorrow's larger balance; malformed, duplicate or nonfinite
entries block funds. The report's total-minus-settled estimate is distinct from
recorded local sale obligations.

References checked 2026-10-21: [IBKR account balances](https://www.ibkrguides.com/traderworkstation/account-balances.htm),
[OCC 2026 holidays and US banking closures](https://infomemo.theocc.com/infomemos?number=57897),
[Federal Reserve holiday schedules](https://www.frbservices.org/about/holiday-schedules/).
The default calendar is a conservative local policy, not a complete certification
of any clearing service's operating calendar.

### Order API and runner status

Order mode uses `PaperBroker.ibkr(readonly=False, paper_confirmed=True, ...)`.
`submit_limit(symbol, "BUY" or "SELL", quantity, limit_price, tag=..., key=...)`
submits a USD equity DAY limit order during regular hours (`outsideRth=False`).
Defaults cap each order at one share and $500 notional. The optional key prevents
repeated local intents across restarts. The broker journals intent before sending,
allocates IDs separately from data requests, preserves partial fills/late fees,
and never automatically resends an ambiguous submission. `cancel(order_id)` controls
only this client’s PyIBQuant orders. Closing an observer does not cancel orders.

`close_position_market(symbol, quantity, tag=..., key=...)` is a separate, explicit
owner-directed liquidation command. It only sells existing long whole-share USD
equities, enforces the configured quantity cap and reconfirmed holdings, and cannot
place market buys or open short positions. Market orders have no price/notional
cap and do not assume a fill price. The strategy runner continues to require fresh
live quotes and uses limit orders; a missing subscription does not loosen its rules.

`examples/paper_rebalance_check.py` defaults to a read-only preflight of current
holdings and quotes. Its explicit `--execute` mode sells existing supported holdings,
verifies a flat account, and buys one AAPL share capped at $500 order notional. A
holding with IBKR error 10168 uses the explicit market-close command instead of
inventing a current quote. Other missing/stale quotes stop the workflow. Every
fill and resulting position is checked before continuing; unresolved working
orders are canceled and checked on exit. `--execute --buy-only` resumes just the
one-share AAPL purchase and refuses to proceed if any positions already exist.
The owner reports successful liquidation and the follow-up one-share AAPL purchase.

Order submission and fills have owner-run paper evidence, including an algorithmic
AAPL buy/sell round trip. The owner also validated ten-minute bounded completion,
same-day process restart/resume with preserved limits, and acknowledged unfilled
cancellation on 2026-10-20. Recovery across market sessions still needs validation.
Open-order visibility is a snapshot, not full control or continuous observation of
other clients' orders. Historical executions are limited by what TWS returns.
Reconciliation also downloads completed orders with an explicit completion barrier.
It updates only existing journal orders with matching positive permanent ID,
client/order ID, contract, reference and side. It preserves submitted quantity
when TWS reports zero total quantity for a filled record, and requires consistent
filled quantity. Completed orders do not create executions, prices or fees.
Conflicts raise, unmatched records do not adopt orders, and absence never proves
cancellation. An incomplete completed-order request requires a new broker session;
it cannot be retried on the same untagged callback stream. The result exposes
`completed_orders_checked`; full historical coverage is not promised.
Read-only TWS verification matched nine records; a reconstructed missing-callback
journal recovered a known unfilled cancellation without submitting/canceling orders.
Execution-correction attribution, automatic reconnect
and robust multi-session strategy accounting remain subsequent work. Unknown
persisted orders continue to block, rather than being assumed canceled or filled.
Unknown-send events persist the originating API client ID. Older events without
that field replay using their original session's client metadata, including offline
report replay; changing observer clients never creates a duplicate order identity.

`EquityRunner` runs the existing above-SMA signal on one-minute completed candles,
witnessed by the next live candle. It requires a provider-confirmed regular session,
matching live bid/ask and bar identities, contiguous warmup, and fresh data. It does
not process historical candles as orders or retry missed/stale decisions. Order mode
also requires a flat selected symbol at start and fresh broker P&L for its account
session-loss limit. It caps the selected position and number of orders per run.
Live feed receipts are read before the real-clock freshness comparison so callbacks
arriving during account/risk reads cannot appear spuriously future-dated. Explicit
test/replay clocks still reject future receipts. A failed live-bar check records
the receipt timestamp, check timestamp, exact age and configured limit; pause
messages distinguish missing callbacks from measured stale/future values. The
15-second order-data freshness guard remains unchanged.
If the P&L sample is older than 15 seconds, `broker.refresh_risk(timeout=5)` first
checks whether fresh account downloads can confirm an unchanged, fully flat USD
account. This requires a validated same-day P&L reference, zero unrealized P&L,
no holdings or working orders, and unchanged cash/funding, net liquidation,
executions and fees. Foreign cash, missing values or any change require a fresh
P&L callback. The confirmation has its own timestamp and journal event: the old
P&L receipt time and loss baseline remain unchanged. It cannot infer a missing
baseline or cover an exposed account. This avoids repeated subscription
renewals when a quiet flat account stops emitting unchanged P&L.
Otherwise, `broker.refresh_pnl(timeout=5)` renews with a new request ID and ignores
late prior-generation callbacks. Missing/invalid values, timeout or disconnect
still block orders. The runner rechecks quote/bar age after waiting. Both methods
only download account data; neither sends broker orders.
IBKR can return an initial zero-valued P&L callback followed by the current value.
Renewal therefore collects a two-second initial update window; an all-zero first
sample replacing nonzero P&L requires a subsequent valid callback. Unconfirmed
resets time out and cannot be reused by resume as valid risk data. True zero P&L
is supported when confirmed. Execution startup validates the initial active
subscription with `refresh_pnl(renew=False)` before setting the baseline, avoiding
an unnecessary cancel/resubscribe. Startup waits even when P&L is initially absent.
A validated same-day preflight reference can carry across connections through the
same account journal, provided a fresh download confirms identical flat-account
evidence. The reference is anchored to account state at the original callback and
must still match after validation. Legacy same-day validated samples can be
reconstructed from their recorded account session, with the same fresh comparison
required. No old funds or P&L are replayed as current broker observations. Changed
or unknown evidence, conflicting callbacks or a new trading date block reuse.
If neither a callback nor matching reference is available, verify the TWS setting
**Prepare portfolio PnL data when downloading positions**, which
[IBKR requires for account P&L](https://interactivebrokers.github.io/tws-api/pnl.html).
If already enabled, restart the paper TWS/Gateway session and repeat read-only
preflight before execution. The API cannot inspect this setting. A missing initial
baseline still blocks trading. The journal records validated samples, the baseline
and each loss comparison; loss stops include the numeric change and limit.
`start`, `pause`, `resume`, `stop`, `cancel_owned_orders` and `flatten` are distinct.
Stop does not cancel or flatten. Resume applies to a paused or restored run: it
reconciles first, preserves the loss baseline/order count, requires matching
strategy-owned holdings and skips candles missed during the pause. It cannot
reconnect a failed broker. A second `start` cannot
reset an existing run's limits. Each execution decision also checks that account
holdings match this run's actual recorded executions.

### Recovery, ownership and audit APIs

```python
recovery = broker.reconcile()  # read-only fresh account/open-order/execution download
print(recovery.clear, recovery.missing_orders, recovery.foreign_orders)
ledger = broker.strategy_ledger("my-strategy-tag")
broker.export_strategy("my-strategy-tag", "charts/paper/strategy-audit.json")
```

`Reconciliation.snapshot` is immutable. `working_orders` includes unresolved
PyIBQuant references across clients; `missing_orders` contains those not observed
in the latest open-order/execution download. Absence never implies cancellation.
`foreign_orders` includes working orders this client cannot control, including
manual orders. `clear` requires a complete account snapshot and no tracked or
foreign working orders; it is not proof of complete historical coverage. Completed
orders outside the execution lookback still require manual investigation. Tags
and fills survive journal reopening; a different API client does not gain control.

`broker.wait_order(order_id, timeout=35)` waits for a known order of this client,
returning an immutable order in Filled/Cancelled/ApiCancelled/Inactive state.
Check `filled` and `remaining`: terminal does not imply a full fill. Timeout or
uncertain connection state raises `OrderWaitError` with immutable `last_order`
evidence. Waiting never sends, cancels or retries an order. A known terminal
result remains readable after a disconnect.

`broker.cancel_owned_orders(tag=..., timeout=35)` requests cancellation only for
this client's exact strategy tag, then waits within one shared timeout. Results
can be fills that won the race. An unresolved result raises `OrderWaitError`;
identities remain journaled. This is an explicit write command and requires an
enabled paper broker. `runner.cancel_owned_orders()` uses its own run tag.

`runner.flatten(series, quote)` pauses the run, reconciles, checks that its fill
ledger exactly matches account holdings and submits a bounded DAY limit sell for
only its own whole shares. It requires fresh live quotes and a provider-confirmed
regular session, refuses pending/mixed/external holdings and cannot trade from an
observation run. It returns an order ID; use `wait_order` and refresh positions to
confirm liquidation. It does not reset loss or order limits. A missing execution
or conflicting fill blocks ownership-based actions.

`strategy_ledger(tag)` reports signed positions, execution count, USD trade cash
flow, commissions and reconciliation issues. Cash flow is not open-position P&L.
Missing/non-USD fees remain unknown. The JSON export includes masked account
identity, orders and executions; net realized trading P&L is reported only when
positions are flat, fills reconcile and commissions are known. It excludes income,
corporate actions, external holdings and account-wide returns. Execution-correction
normalization and full historical coverage remain unfinished; exact-identity
completed-order recovery for existing journal orders is implemented. Keep private exports
under ignored `charts/`.

### Restart recovery

New runs journal versioned checkpoints with their complete configuration, contract,
trading date, daily-P&L baseline, order caps, processed candle and order count. The
candle checkpoint is written before any decision can create an intent. Restore
also counts durable intents after the checkpoint, including unknown send outcomes.
Balances and positions are never restored as current account state.

```python
from pyibquant.trading.runner import EquityRunner

runner = EquityRunner.restore(broker, run_id)
assert runner.status == "paused"  # no API requests or orders during restore
runner.resume(series)  # explicit reconciliation and fresh risk/feed checks
```

Same-day resume requires matching contracts and run-owned
fills/holdings, fresh live bars, a provider-confirmed regular session, fresh validated
P&L, and no unresolved or foreign working orders. It preserves the original loss
baseline and order budget, retains the original order caps even if the replacement
broker permits larger orders, and skips missed candles. A feed older than the
persisted candle is refused. Unknown orders are never guessed canceled or resent.
If another process changes the checkpoint or adds intents after restoration,
resume refuses the stale state; reopen/reload from the journal before trying again.

Restore can be inspected using a read-only broker, but execution cannot resume
until the broker is explicitly enabled. A local POSIX file lock beside the journal
allows one executing process per run/journal. Pause retains ownership; stop releases
it. Process exit releases the lock automatically. This does not coordinate copied
journals, multiple machines or network filesystems. Windows execution recovery is
not yet supported. New-date rebaselining is not automatic.

To continue a checkpointed run on a later New York trading date, call
`runner.resume(series, new_session=True)`. This requires current-day live bars,
provider session evidence, fresh validated P&L, known recorded fees, matched
ownership and clear orders. It records the previous and new daily P&L baselines
as an explicit session rollover. The daily loss threshold measures change since
that new baseline; it does not include overnight changes or provide a lifetime
loss cap. Run identity, original order/notional/quantity caps and total consumed
order budget remain unchanged. An exhausted run cannot regain orders by rolling
its session. Failed checks preserve the old baseline. No missed bars are traded.
The equity example exposes this as `--resume-run RUN_ID --new-session --execute`.
A disconnected transport still requires opening a new broker; automatic broker
reconnect/resubmission is not implemented.

Legacy runs without a complete checkpoint remain reporting-only. Their missing
configuration or risk state is not inferred. For a new checkpointed run, the example
supports `--resume-run RUN_ID`; the symbol must match and `--window` cannot override
stored settings. This option cannot be combined with `--close-existing-share`.
Without `--execute`, it prints the paused recovered state and writes a report,
without opening market-data subscriptions. Human-run `--execute` attempts explicit
resume under the checks above; it does not create another run identity.

### Offline account and run reports

```sh
.venv/bin/python examples/paper_report.py --journal charts/paper/strategy.sqlite3 --output charts/paper/strategy-review.html
```

This reads the source SQLite journal in read-only mode and uses the broker reducer
in a disposable local replay. It does not connect to TWS or modify the source.
The snapshot is explicitly offline/incomplete; cached values are historical
observations. Multiple-account journals require `--account`.

The account report now includes a run selector, configuration/mode, order and fill
tables, FIFO realized P&L, unrealized P&L, commissions, gross exposure and a run P&L
curve. Open positions use timestamped last-observed portfolio marks; missing marks
or fees stay unknown. Manual orders, existing positions and starting-share closes
are excluded from run attribution. Drawdown is in dollars over recorded net-P&L
observations, not a claim of complete intraday coverage. No percentage return is
computed without an allocated capital/cash-flow definition. Late fees affect the
curve when received; duplicate executions do not create additional fills.

Alongside HTML and account CSV, reports write `-runs.csv`, `-run-points.csv` and
`-fills.csv`. Strategy JSON audits include the run performance summary. The strategy
example retains per-run HTML/JSON/CSV under `charts/paper/runs/RUN_ID/` as well as
the latest report. Data and historical pause reasons remain intact; old false-stop
events are not rewritten. All generated artifacts contain private trading history
and belong under ignored `charts/`.

### Paper setup and operating sequence

`examples/paper_aapl.json` saves the selected AAPL/20-bar SMA configuration:
one-share long/flat target, $500 order cap, four orders per run, $25 account
session-loss limit, 15-second market-data age limit and a bounded ten-minute run.
Pending run orders are canceled on exit; filled shares remain until an explicit
strategy exit/flatten. Broker, market data and preflight use separate client IDs.
The account is auto-selected only when exactly one account is visible, and must
be a DU paper account. The port does not establish paper-account identity.

Run preflight before starting the runner:

```sh
.venv/bin/python examples/paper_preflight.py --profile examples/paper_aapl.json
.venv/bin/python examples/paper_preflight.py --profile examples/paper_aapl.json --connect
```

The first command validates local configuration, SDK and journal location without
a connection. The second also checks account downloads, order reconciliation,
settled-cash funding, flat starting holdings, the selected contract and validated
P&L using a read-only connection. Results are saved to `charts/paper/preflight.json`.
Neither command places or cancels orders. Preflight always reports
`ready_to_trade=false`: fresh live quotes/bars, regular-session evidence and actual
order acceptance are evaluated at runtime. A successful after-hours preflight
does not prove current market-data permissions or an executable price.

The launch commands are:

```sh
# Observe without orders (also the default when using a profile).
.venv/bin/python examples/paper_strategy.py --profile examples/paper_aapl.json

# Human-run bounded paper execution during the regular session.
.venv/bin/python examples/paper_strategy.py --profile examples/paper_aapl.json --execute

# Human-run execution control check (new run; normal limits and stop policy).
.venv/bin/python examples/paper_strategy.py --profile examples/paper_aapl.json \
  --seconds 600 --check-controls --execute

# Inspect a checkpoint, paused and read-only; does not open a market feed.
.venv/bin/python examples/paper_strategy.py --profile examples/paper_aapl.json --resume-run RUN_ID

# Human-run explicit resume of that same run and its existing limits.
.venv/bin/python examples/paper_strategy.py --profile examples/paper_aapl.json --resume-run RUN_ID --execute

# Rebuild account/run reports offline after stopping.
.venv/bin/python examples/paper_report.py --output charts/paper/strategy-review.html
```

Profile files cannot contain `execute`, `readonly` or `paper_confirmed` switches;
unknown fields are rejected. Trading still requires the command-line `--execute`.
Profile paths resolve relative to the profile file. Optional command-line symbol,
window, duration and journal overrides apply to new runs; persisted configuration
wins on restore and an explicit conflicting `--window` is rejected. Client IDs,
account selection and broker caps come from the profile. The legacy command
without a profile retains its explicit cancellation opt-in. Keep account-specific
custom profiles under ignored `charts/`; the shipped profile contains no identifier
or credentials. Resets, cash transfers and cross-date baseline changes require a
separate reconciliation/new-session decision.

`--check-controls` requires a new execution run of at least 240 seconds. After its
first completed-bar signal and resolved orders, it deliberately pauses for at least
65 seconds and one new candle. Signals, candle cursor, run identity, configuration,
baseline and order budget must stay unchanged during the pause. Resume uses the
normal fresh-data, ownership, funding/reconciliation and risk checks; it skips the
paused candles. The check prints `paused`, `resumed` and `passed` after a new signal,
then continues the bounded run under its existing limits. Failure or timeout still
stops the runner and performs configured pending-order cleanup; filled holdings
can remain. Owner-run live acceptance passed on 2026-10-20: nine signals, deliberate
pause/resume with unchanged risk baseline/caps, a subsequent signal and ten-minute
completion. One filled AAPL share remained for a separate explicit exit.

To inspect or close only one exact run's reconciled holdings:

```sh
.venv/bin/python examples/paper_flatten.py --profile examples/paper_aapl.json --run-id RUN_ID
.venv/bin/python examples/paper_flatten.py --profile examples/paper_aapl.json \
  --run-id RUN_ID --execute
```

The first command is a read-only fresh exit plan; `EquityRunner.flatten_plan()` does
not modify the runner checkpoint or submit/cancel orders. The second checks the
restored checkpoint under its run lease, pauses and submits at most one bounded
limit SELL for actual run-owned holdings. It waits for terminal evidence, reconciles
both ledger and account holdings and applies the profile's pending-order cleanup.
It never starts new strategy decisions, adopts manual holdings or replaces an
uncertain order. Prices refresh at execution; stale quotes or mismatched holdings
block the exit. Fees/realized P&L remain unknown until actual callbacks supply them.

Local setup is complete for this bounded USD-equity workflow. The owner completed
a ten-minute session with actual fills, then restarted/resumed it with reconciled
ownership and unchanged loss/order limits. Its fourth order sold the retained
share; a fifth order was blocked by the original cap. The separate resting-order
cancellation check also passed on 2026-10-20: broker acknowledgment, Cancelled with
zero fills, flat holdings, clear reconciliation and no pending owned reservation.
These checks validate the initial bounded-equity operating sequence.
The owner subsequently completed a 30-minute run with 30 completed-bar decisions,
four fills and a flat, fully attributed result (-0.25 USD gross, 4.014050 USD fees,
-4.264050 USD net). Fresh read-only reconciliation confirmed flat holdings and
no unresolved orders. Its four-order budget is exhausted.
Completed-order history beyond TWS coverage, correction normalization, cross-date
rebaselining, options/margin strategies and live-money enablement remain outside
this initial setup. Unknown outcomes continue to block trading.

### Paper cancellation check and recovery

For a separate human-run disconnect-after-send acceptance check:

```sh
.venv/bin/python examples/paper_cancel_check.py --profile examples/paper_aapl.json \
  --execute --disconnect-after-send
# Preserve the exact printed Check ID; expected outcome: disconnected_after_send, exit 2.
.venv/bin/python examples/paper_cancel_check.py --profile examples/paper_aapl.json \
  --resume-check CHECK_ID --execute
```

The first command attempts one one-share AAPL DAY limit BUY 2% below the fresh bid,
with the existing $500 cap and funding checks. It disconnects only its own broker
socket immediately after the send returns, marks the send uncertain and performs
no automatic cancellation/reconnect. The order may remain working or fill.
The second command first reconciles the exact persisted order with fresh broker
downloads, then cancels/waits only that order. It never submits a replacement or
reverses a fill. A missing original order blocks recovery. Never repeat the first
command to recover an uncertain outcome. This harness is offline tested; actual
disconnect-after-send acceptance still requires the owner-run paper check.

Keep the strategy stopped and the account flat. During a provider-confirmed regular
session, inspect a fresh plan, then have the human operator execute the bounded check:

```sh
.venv/bin/python examples/paper_cancel_check.py --profile examples/paper_aapl.json
.venv/bin/python examples/paper_cancel_check.py --profile examples/paper_aapl.json --execute
```

The check uses dedicated broker/market clients 297/298, the selected DU paper
account and the profile journal. It requires matching live AAPL USD equity quotes,
positive settled-cash funding including a fee reserve, and no holdings or visible/
unresolved working orders. It submits one share with a DAY limit 2% below the bid,
capped at the lesser of $500 and the profile cap. It waits for Submitted/PreSubmitted
acknowledgment and approximately two seconds of resting time before canceling its
exact durable tag. The check does not send an additional round trip or increase
the previous strategy run's order budget.

`passed: true` requires acknowledged cancellation with zero fills, flat holdings,
a complete fill ledger and clear fresh reconciliation. Repeating terminal cleanup
is a no-op. A rejection, missing acknowledgment or unconfirmed cancellation cannot
pass. A fill can win the cancellation race; any partial/full fill is reported and
retained for an explicit owner decision. No replacement order or automatic sell
is submitted. Cleanup also runs on an interrupted wait or uncertain send, but a
request alone is not proof of cancellation.

The command prints the check ID before submitting, and saves masked plan/result,
before/after snapshots, audit JSON and account HTML under
`charts/paper/cancel-checks/CHECK_ID/`. The read-only preflight's ID describes only
an unsubmitted plan; execution creates a new ID with fresh prices. Recover an
**executed** check using its original ID, rather than repeating a fresh execution:

```sh
# Inspect/reconcile only; never cancels or submits.
.venv/bin/python examples/paper_cancel_check.py --profile examples/paper_aapl.json --resume-check CHECK_ID

# Cancel only the original working order and confirm; never submits a replacement.
.venv/bin/python examples/paper_cancel_check.py --profile examples/paper_aapl.json --resume-check CHECK_ID --execute
```

Recovery refuses an unknown ID, multiple matching orders or an order owned by a
different client. A local process lease prevents concurrent cancellation checks.
Exit 0 means a read-only preflight/inspection completed or an executed cancellation
passed. Exit 1 reports uncertainty or a failed check; exit 2 reports a confirmed
outcome that did not meet the unfilled-cancellation criteria, including a fill.
Inspect the result and holdings before taking any further action.

### Selected long-option paper lifecycle (experimental)

`PaperBroker.submit_option_limit(option, side, 1, limit_price, quote=quote, tag=tag,
key=key)` uses the shared durable intent, broker transport, order waits, cancellation
and reconciliation. It resolves exactly one USD option and downloads its SMART
price-increment ladder via `reqMarketRule`; `minTick` alone is not assumed sufficient.
Limits must match that ladder and the quote's exact contract identity/multiplier.
Bid/ask must be live, non-crossed, positive and received within 15 seconds after
blocking broker downloads. Expiry-day/expired orders are refused.

Initial scope is one long contract. Entry requires a flat selected contract, clear
orders and broker settled-cash funding for `limit × quantity × actual multiplier`
plus a $2 fee reserve. The order's premium must fit the configured notional cap.
A SELL can only close the exact tag's one reconciled owned contract; external
holdings, shorting, scaling, multi-leg orders, exercise/assignment and automatic
option strategies are unsupported. `EquityRunner` remains equity-only.
Ledger cash flow, FIFO P&L, exposure and pending-buy estimates now apply actual
option multipliers. Missing/conflicting execution multipliers make results incomplete;
equity calculations retain per-share behavior. Fees remain broker-reported values.

The separate bounded human-run integration harness defaults to read-only:

```sh
.venv/bin/python examples/paper_option_check.py --profile examples/paper_aapl.json \
  --expiry 2026-11-20 --strike 365 --right C
.venv/bin/python examples/paper_option_check.py --profile examples/paper_aapl.json \
  --expiry 2026-11-20 --strike 365 --right C --execute
# Recovery uses the exact printed Check ID and persisted contract; never repeat entry.
.venv/bin/python examples/paper_option_check.py --profile examples/paper_aapl.json \
  --resume-check CHECK_ID --execute
```

It requires a flat starting account, clear orders, a provider-confirmed underlying
regular session and fresh option quotes. It uses five-cent-grid limits rounded
against the actual market rule to accommodate the documented paper-option penny-fill
limitation; see [IBKR paper simulator limitations](https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/).
Preflight requires entry premium below $500 and quoted spread plus $4 estimated
round-trip fees within the profile loss budget. This cost estimate does not guarantee
a realized-loss limit or execution quality. Execution records a validated account
P&L baseline, attempts one BUY then one owned SELL, waits for broker terminal states
and reconciles positions/fees. No filled round trip is claimed by read-only preflight.

Recovery never buys, never blindly replaces an attempted sell and refuses missing
or foreign orders. Pending tagged orders are canceled and verified on exit; filled
holdings are retained if a close fails. Reports/audits live under the exact Check ID
in ignored `charts/paper/option-checks/`. Keep other execution workflows stopped.
Owner-run acceptance passed on 2026-10-20, check
`e7c2452026e5459d845a3214ff0bfc8a`: BUY one AAPL November 20 365 C at 2.32,
SELL at 2.17; gross -15 USD, fees 1.535070, net -16.535070. Ledger complete,
account/strategy flat and no pending reservation; fresh read-only preflight clear.

For a separate acknowledgment/cancellation check, add `--cancel-only` to a new
check. It submits one BUY at a nickel-rounded limit 10% below the fresh bid,
waits for acknowledgment, rests two seconds, cancels that exact order, and reports
the multiplier-based reservation before/after. Success requires zero fills, confirmed
cancellation, clear reconciliation and a flat account. A fill race is reported and
retained without an automatic SELL. Resume cancellation with the exact Check ID;
only explicit `--resume-check CHECK_ID --execute --exit-owned` requests an owned
exit after review. Recovery never submits a new BUY. Read-only mode supports
`--cancel-only` without `--execute`. Quotes and eligibility are rechecked at execution.

Owner-run cancellation acceptance passed on 2026-10-20, check
`c7a050a5fbad4f7f807738fc3ef9383e`: one 1.95 BUY acknowledged then Cancelled,
zero fills/fees, complete ledger, account flat and clear reconciliation. The
197 USD pending-buy estimate (195 premium plus 2 fee allowance) released to zero.
Fresh read-only account preflight confirmed zero working/missing/foreign orders.

### Automated selected-option strategies

`OptionRunner` uses the same lifecycle, risk, session recovery, journal and
strategy-owned flattening as `EquityRunner`. The signal feed is an independently
owned live one-minute underlying feed. The traded instrument is one explicit,
resolved long option; a separate exact-contract quote drives tick-valid premium
limits. The default `premium_grid=Decimal(".05")` avoids penny-fill limitations
of the TWS paper simulator; it is still validated against the actual broker tick
ladder. The grid is persisted and may be configured explicitly in Python.
Order/notional checks include the actual multiplier. Call/put selection
and above/below-SMA entry are explicit; put selection does not silently invert a
signal. This initial runner has these two stateless signals, not arbitrary strategy
callbacks. There is no automatic contract selection, rolling, exercise, assignment,
expiry-day execution or multi-leg support.

```python
from datetime import date
from pyibquant import Option
from pyibquant.trading.option_runner import OptionRunner
from pyibquant.trading.runner import RunnerConfig

# Supply a contract you chose and a separately owned underlying series/option quote.
selector = Option("AAPL", date(2026, 11, 20), 365, "C")
runner = OptionRunner(broker, RunnerConfig("AAPL", window=20), selector,
                      entry_when="above_sma")  # observation by default
runner.start(underlying_series)
runner.step(underlying_series, option_quote)  # invoke as data arrives
runner.pause()
runner.resume(underlying_series)
runner.stop()  # retains filled inventory
```

`flatten_plan(underlying_series, option_quote)` previews an exact owned exit;
`flatten(...)` is an explicit execution action. Foreign/mixed holdings are refused.
`EquityRunner.restore(broker, run_id)` dispatches an option checkpoint back to
`OptionRunner`, preserving selector, signal, underlying/option identities,
multiplier and original caps. Resume re-resolves the contract and rejects identity
changes. It also supports explicit `new_session=True` under the shared checks.

The example refreshes a quiet but otherwise valid live quote subscription once
at a new decision candle when its receipts have aged out. It waits up to five
seconds for new callbacks and then applies the same freshness/validity checks.
Cached receipt times are never rewritten. `examples/paper_flatten.py` dispatches
restored stock/option runs to the matching quote and owned-only exit API.

The standalone example defaults to observation:

```sh
python examples/paper_option_strategy.py --profile examples/paper_aapl.json \
  --expiry 2026-11-20 --strike 365 --right C --entry-when above_sma
```

This dated selection is an API example, not a recommended contract. Choose a valid
unexpired contract with your own liquidity/strategy criteria. `--execute` enables
bounded paper orders. `--resume-run RUN_ID` uses the saved selector and rejects
selection overrides; add `--new-session --execute` only for an explicit later-day
resume. Omitting `--execute` on restore only inspects the paused run and saves its
audit. The profile's duration and cancel-on-stop setting apply; stopping never
liquidates a filled option. Account reports and audits are saved under ignored
`charts/paper/`. These new funding/rollover/option-runner paths are offline-tested.
Bounded TWS acceptance now includes equity rollover, automatic option buy/sell,
exact-ID disconnect recovery and reservation release. Actual next-date cash release
and natural partial fills remain unobserved live.

### Stopping for the day and local data

Let the bounded runner exit, or interrupt it with Ctrl-C. The shipped profile
cancels pending run orders on exit; filled holdings remain until an explicit exit.
Check the saved result and reconciliation rather than assuming process exit made
the account flat. On 2026-10-20 the final cancellation result confirmed flat
holdings and no pending owned order.

Retain `charts/paper/strategy.sqlite3`, its recovery identities/checkpoints, per-run
audits and cancellation results. Never delete a SQLite WAL while a process has
the database open. Stop the owning process before moving a journal. Diagnostic
journals can be retained as verified standalone SQLite backups; tool caches and
bytecode can be regenerated. The private `charts/paper/README.md` indexes retained
data and the dated archive manifest. These files stay out of Git.

Reports can be rebuilt offline with `examples/paper_report.py`; no TWS connection
is needed for documentation, cleanup or report generation. A later trading date
requires an explicit new-session baseline or a new run; same-day evidence cannot
cross the date boundary implicitly.
The completed four-order run's budget must not be reset or increased to continue.

The runnable example defaults to observation only:

```sh
.venv/bin/python examples/paper_strategy.py AAPL --seconds 180
```

The owner selected AAPL/above-SMA (20 one-minute bars), one-share target, $500
per-order cap and $25 account session-loss limit. To prepare a flat starting
symbol, `--close-existing-share` previews a close of exactly one manual share.
It refuses other quantities, requires fresh live quotes and a regular session,
and never assigns the manual position to the strategy. With `--execute`, it
waits for the close to fill and reconfirms flat holdings before starting. Other
symbols are untouched. If already flat, it proceeds without a starting close.

Owner-run command for a bounded ten-minute paper test:

```sh
.venv/bin/python examples/paper_strategy.py AAPL --window 20 --seconds 600 --close-existing-share --execute --cancel-on-stop
```

This command can send paper orders and requires explicit owner authorization. `--cancel-on-stop` cancels and waits
for this run's pending orders and any pending starting-share close. It does not
liquidate filled strategy holdings. Reports and the strategy audit are written
under `charts/paper/` even when start/cancellation fails. The run can end without
an entry if no eligible signal occurs. Omit `--execute --cancel-on-stop` for the
read-only preflight/observation path.

`--execute` enables paper orders and requires explicit authorization for integration
use; `--cancel-on-stop` explicitly cancels that run's outstanding orders. Live-money
execution, margin strategies and option orders are not implemented. Paper fills
cannot validate live execution quality. Offline simulation remains a separate API.
