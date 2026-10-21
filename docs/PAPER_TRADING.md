# Paper account and runner API

[Documentation home](README.md) · [Core API](API.md) ·
[Advanced operating procedures](WORKFLOWS.md)

Start with account observation. `PaperBroker` is a separate connection from
`Market`, uses its own client ID, and defaults to read-only. Experimental
execution supports selected USD equities and one long option; real-money trading
is outside this API. A returned order ID is not a fill, a cancellation request
is not confirmation, and stopping a runner does not liquidate holdings.

- [Connect and inspect an account](#connect-and-inspect-an-account)
- [Experimental order methods](#experimental-order-methods)
- [Runner configuration and lifecycle](#runner-configuration-and-lifecycle)
- [Profiles and preflight](#profiles-and-preflight)
- [Settlement policy](#settlement-policy)

## Connect and inspect an account

Import: `from pyibquant import PaperBroker`.

```text
PaperBroker.ibkr(*, journal="charts/paper/account.sqlite3", account=None,
                 host="127.0.0.1", port=7497, client_id=272, timeout=20,
                 readonly=True, paper_confirmed=False, max_order_value=500,
                 max_quantity=1, settlement_policy=None)
```

| Argument | Meaning |
|---|---|
| `journal: str \| Path` | Durable SQLite history, intents and recovery identities. Reuse the original journal for recovery; do not delete it to bypass uncertainty. |
| `account: str \| None` | Explicit managed `DU...` paper account. None selects automatically only when exactly one account is visible. |
| `host`, `port` | API socket address; default localhost paper TWS 7497. |
| `client_id: int` | Positive dedicated broker client ID; distinct from Market and other connections. |
| `timeout: float` | Connection/synchronization timeout in seconds. |
| `readonly: bool` | Default True blocks order submission/cancellation. |
| `paper_confirmed: bool` | Explicit caller assertion of paper environment, required with `readonly=False`. Port/DU prefix alone do not prove the environment. |
| `max_order_value: float` | Positive USD per-order notional cap for bounded limit orders. Option notional includes the actual multiplier. |
| `max_quantity: int` | Positive whole quantity cap, shares or contracts. |
| `settlement_policy: SettlementPolicy \| None` | Bounded local cash-release policy; None uses the versioned default. An existing journal retains its policy and rejects incompatible replacements. |

Returns a synchronized broker, waiting for account, summary, positions, open-order
and execution callbacks. Missing download stages fail explicitly. Use a context
manager to release the worker, journal and socket. Closing does not flatten.

```python
from pyibquant import PaperBroker

with PaperBroker.ibkr() as broker:  # Paper observation; no orders.
    snapshot = broker.snapshot()
    print(snapshot.to_dict())
    print(broker.funding())
    print(broker.report("charts/paper/account.html"))
```

### Account observation methods

Examples in the table run inside that open broker context. Timeouts are seconds.

| Method | Arguments and result | Example |
|---|---|---|
| `snapshot() -> AccountSnapshot` | Independently copied current observations; no new broker download. | `snapshot = broker.snapshot()` |
| `wait_ready(timeout=20) -> AccountSnapshot` | Wait for synchronization barriers or raise BrokerError. Factory already calls this initially. | `broker.wait_ready(timeout=30)` |
| `wait_for_update(after, timeout=5) -> AccountSnapshot` | `after` is the last snapshot sequence; wait for a newer one or closure. Timeout returns current snapshot. | `new = broker.wait_for_update(snapshot.sequence, timeout=5)` |
| `refresh() -> AccountSnapshot` | Fresh account/position/order/execution downloads; retained summary subscription avoids subscription churn. | `fresh = broker.refresh()` |
| `refresh_pnl(*, timeout=5, renew=True) -> AccountSnapshot` | Wait for a valid P&L sample; renew requests a new subscription generation. Old sample is not relabelled as fresh. May confirm a same-day flat reference explicitly. | `fresh = broker.refresh_pnl(timeout=10)` |
| `refresh_risk(*, timeout=5) -> AccountSnapshot` | Refresh risk evidence including supported flat-account confirmation; does not place orders. | `fresh = broker.refresh_risk(timeout=10)` |
| `funding(*, at=None) -> dict` | Fresh broker caps combined with durable local USD cash ceiling, fee reserves, unsettled obligations and blockers. `at` is an aware datetime override; omit for current time. | `print(broker.funding())` |
| `base_currency() -> str \| None` | Recorded base currency if known; no FX conversion. | `print(broker.base_currency())` |
| `reconcile() -> Reconciliation` | Fresh downloads compared with durable order identities. Does not replace missing orders. | `recovery = broker.reconcile()` |
| `strategy_ledger(tag) -> StrategyLedger` | Exact nonempty durable tag, at most 100 characters; attribute recorded executions to it. | `ledger = broker.strategy_ledger("my-study")` |
| `export_strategy(tag, path) -> Path` | Save a tag's masked orders, executions, ledger and performance summary as JSON. | `broker.export_strategy("my-study", "charts/paper/my-study.json")` |
| `report(path) -> Path` | Write account HTML and companion CSV history; creates parents. | `broker.report("charts/paper/account.html")` |
| `close() -> None` | Close worker/journal/connection; context exit calls it. | `broker.close()` |

Receipt times describe callbacks, not independently current exchange valuations.
Unavailable P&L/fees stay missing. Account P&L includes manual/pre-existing holdings;
it is distinct from strategy attribution. Reports/journals contain financial data;
keep them outside Git (the default `charts/` location is ignored).

### Snapshot, values, reconciliation and ledger fields

`AccountSnapshot`: `account`, `session`, `sequence`, `status`, `complete`, `values`,
`positions`, `orders`, `executions`, `pnl`, `errors`.
`complete` indicates synchronization readiness, not complete historical coverage.

`snapshot.value(tag, currency="") -> AccountValue | None` matches an exact broker
tag/currency. Empty currency is an exact match, not a wildcard.
`snapshot.to_dict(*, mask_account=True) -> dict` exports copied observations and
masks account identifiers by default. `AccountValue` fields are `tag`, `currency`,
raw string `value`, `received_at`, `source`; its `.number` property returns a
`Decimal` or None if absent/invalid.

```python
# Within an open broker context:
snapshot = broker.snapshot()
value = snapshot.value("TotalCashValue", "USD")
print(value.number if value is not None else None)
print(snapshot.complete, snapshot.errors)
```

`Reconciliation` contains `snapshot`, `working_orders`, `missing_orders`,
`foreign_orders`, `completed_orders_checked`. Its `.clear` property checks that
snapshot is complete and working/foreign orders are absent; inspect missing-order
and ledger evidence too before treating recovery as resolved.

`StrategyLedger` contains `tag`, `(contract ID, Decimal quantity)` pairs in
`positions`, `execution_count`, signed premium/share `cash_flow`, `commissions`
(or None), `issues`; `.complete` means fill quantities reconcile, separately from
fee completeness. `.to_dict()` exports strings for Decimal amounts. Realized P&L
is reported only for a complete flat ledger with known fees; it does not mark
open holdings to market. Example: `print(broker.strategy_ledger("my-study").to_dict())`.

## Experimental order methods

These calls require a broker opened with `readonly=False, paper_confirmed=True`
and a verified paper environment. They can send/cancel paper orders. They are
reference examples with explicit prerequisites, not part of the offline quick start.

### `broker.submit_limit(symbol, side, quantity, limit_price, *, tag="manual", key=None) -> int`

- `symbol`: one USD equity ticker; `side`: `BUY` or `SELL`.
- `quantity`: positive whole shares within broker limits; sells cannot short.
- `limit_price`: positive finite per-share limit; DAY order, within notional cap.
- `tag`: exact nonempty user attribution label, at most 100 characters.
- `key`: optional unique 1–40 ASCII-character durable idempotency identity;
  duplicates are rejected, not resubmitted. Omission generates an identity.

Returns broker order ID after intent/send handling. Fresh account funding and
reconciliation are checked before exposure. Illustrative call inside an already
verified execution-enabled paper broker:

```python
# PAPER EXECUTION. Substitute a deliberately chosen current price and unique key.
# order_id = broker.submit_limit("AAPL", "BUY", 1, chosen_price,
#                                tag="manual-check", key="unique-entry-001")
# order = broker.wait_order(order_id, timeout=35)
# print(order["status"], order.get("filled"))
```

### `broker.close_position_market(symbol, quantity, *, tag="manual-close", key=None) -> int`

Owner-directed market SELL of existing long whole-share USD equity holdings.
`symbol`, `quantity`, `tag` and `key` have the meanings above. Quantity cap applies;
a market notional/execution price cannot be capped. No market buys or shorts.
Example, only after checking holdings in an execution-enabled paper broker:
`broker.close_position_market("AAPL", 1, tag="chosen-exit", key="unique-exit-001")`.

### `broker.submit_option_limit(selector, side, quantity, limit_price, *, quote, tag, key=None) -> int`

`selector` is an explicit `Option`; `side` is BUY/SELL; initial scope is one long
contract (`quantity=1`). `limit_price` is premium per unit, not full contract value.
`quote` must be a fresh live exact-contract `Quote` with positive non-crossed
bid/ask; actual multiplier and SMART price-increment ladder are validated.
Required `tag` owns the entry/exit; optional `key` is as above. SELL closes only
the exact tag's reconciled owned contract. Expiry-day/expired orders are refused.

Illustrative call with your chosen selector, quote and validated price:
`broker.submit_option_limit(selector, "BUY", 1, chosen_premium, quote=quote,
tag="option-check", key="unique-option-entry")`.

### Waiting and cancellation

| Method | Arguments and behavior | Example (known owned order only) |
|---|---|---|
| `wait_order(order_id, *, timeout=35) -> Mapping` | Nonnegative ID for this client, finite nonnegative timeout. Wait for Filled, Cancelled, ApiCancelled or Inactive. No cancellation/retry. Terminal does not mean filled. | `order = broker.wait_order(order_id, timeout=35)` |
| `cancel(order_id) -> None` | Request cancellation of this client's known owned order; terminal orders are a no-op. Must wait/reconcile afterward. | `broker.cancel(order_id)` |
| `cancel_owned_orders(*, tag, timeout=35) -> tuple[Mapping, ...]` | Exact tag, total nonnegative finite wait budget. Cancel only this client's matching working orders, then wait for terminal evidence. | `orders = broker.cancel_owned_orders(tag="my-study")` |

A fill can win the cancellation race. `OrderWaitError` carries `.last_order`
(including known partial fills) on timeout/disconnection; do not submit a replacement
just because waiting failed. `BrokerError` reports funding, ownership, lifecycle or
reconciliation blocks. Recover with the original journal and identities using the
[operational procedures](WORKFLOWS.md#paper-cancellation-check-and-recovery).

## Runner configuration and lifecycle

Imports:

```python
from pyibquant.trading.runner import EquityRunner, RunnerConfig
from pyibquant.trading.option_runner import OptionRunner
```

### `RunnerConfig(symbol, window=20, quantity=1, dry_run=True, max_orders=4, max_session_loss=25, max_data_age=15)`

| Field | Meaning |
|---|---|
| `symbol` | Uppercase alphanumeric underlying equity symbol. |
| `window` | Positive integer SMA length in completed one-minute candles. |
| `quantity` | Positive whole target shares; exactly one contract for OptionRunner. |
| `dry_run` | Default True observes signals without sending orders. |
| `max_orders` | Positive total order-intent budget for the run, retained on restore. |
| `max_session_loss` | Positive USD account session-loss limit relative to validated baseline; not a guaranteed maximum realized loss. |
| `max_data_age` | Positive maximum age in seconds for data freshness checks. |

`EquityRunner(broker, config)` uses above-SMA targets on a separately owned live
one-minute series. Warmup history never itself triggers an order; subsequent live
candles witness completion. Quote identity/freshness, sessions, risk, funding and
ownership are checked. Public state includes `run_id`, `status`, `reason`,
`config`, and property `trade_instrument_id` (None until resolved).

| Method | Arguments, result and behavior |
|---|---|
| `start(series, *, at=None) -> None` | Begin on live one-minute BarSeries matching config. Optional `at` is aware clock override; normally omit. |
| `step(series, quote, *, at=None) -> int \| None` | Process available data; quote is matching underlying equity Quote (or selected option Quote for OptionRunner). Returns order ID only if submitted. Caller drives updates; runner does not own a feed/event loop. |
| `pause(reason="Paused by user") -> None` | Pause decisions and retain run identity/caps. Does not flatten holdings. |
| `resume(series, *, at=None, new_session=False) -> None` | Resume after fresh reconciliation; skip paused bars. A later trading date requires explicit new_session=True with validated new baseline. Does not reconnect a socket. Execution authorization is required by the implementation. |
| `stop() -> None` | Stop decisions and release run lease; retains inventory. Pending-order cancellation is separate. |
| `cancel_owned_orders(*, timeout=35) -> tuple[Mapping, ...]` | Cancel/wait only this run's pending owned orders. Does not sell fills. |
| `flatten_plan(series, quote, *, at=None) -> dict` | Read-only preview for a previously started execution run of an exact run-owned exit. Does not change checkpoint or send/cancel. |
| `flatten(series, quote, *, at=None) -> int \| None` | Explicit execution action: pause and submit a bounded owned-position SELL, if eligible. Wait/reconcile separately. |
| `EquityRunner.restore(broker, run_id) -> EquityRunner` | Load exact durable checkpoint in paused state; dispatch option checkpoints to OptionRunner. Retain original ownership, limits, order count and baseline. Does not start feed or execute. |

**Paper observation example**, needing fresh live data permissions and a ready
paper account. The bounded wait only demonstrates driving `step`; it may produce
no signal during those seconds. It submits no orders with default config/broker.

```python
from pyibquant import Market, PaperBroker
from pyibquant.trading.runner import EquityRunner, RunnerConfig

with PaperBroker.ibkr() as broker, Market.ibkr(client_id=71) as market:
    series = market.bars("AAPL", interval="1min", duration="1 D", live=True,
                         include_sessions=True)
    runner = EquityRunner(broker, RunnerConfig("AAPL", window=20))
    try:
        runner.start(series)
        with market.stream_quote("AAPL") as stream:
            quote = stream.latest()
            quote = stream.wait_for_update(quote.sequence, timeout=5)
            runner.step(series, quote)
            print(runner.run_id, runner.status, runner.reason)
            runner.pause("Finished observation")
    finally:
        runner.stop()
```

### `OptionRunner(broker, config, selector, *, entry_when="above_sma", premium_grid=Decimal(".05"))`

`broker`/`config` as above; `selector` must be one Option on config's underlying.
`entry_when` is `above_sma` or `below_sma`; choosing a put does not invert it.
`premium_grid` is a positive finite Decimal price grid, default five cents for
paper-fill behavior; actual broker tick rules still apply. Multiplier-based order
caps apply. Lifecycle methods are inherited, but `series` remains the live
underlying and `quote` must be the **selected option's** quote. No automatic expiry
selection, rolling, exercise, assignment or arbitrary signal callback.

```python
from datetime import date
from decimal import Decimal
from pyibquant import Option
from pyibquant.trading.option_runner import OptionRunner
from pyibquant.trading.runner import RunnerConfig

# Within an open PaperBroker context; creates an observing runner, not an order.
# selector = Option("AAPL", date(2026, 11, 20), 365, "C")
# runner = OptionRunner(broker, RunnerConfig("AAPL"), selector,
#                       entry_when="above_sma", premium_grid=Decimal(".05"))
```

Use `EquityRunner.restore()` for persisted runs; the lower-level option execution
checkpoint constructor is restoration plumbing rather than a manual entry point.

## Profiles and preflight

`from pyibquant.trading.profile import PaperProfile`.
A profile saves connection, signal, cap and duration settings. It cannot enable
execution from a file. See [the shipped profile](https://github.com/RenormalizationTech/PyIBQuant/blob/main/examples/paper_aapl.json).

| Fields (defaults) | Meaning |
|---|---|
| `version=1`, `symbol="AAPL"`, `host="127.0.0.1"`, `port=7497`, `account=None` | Schema, underlying and paper connection selection. |
| `broker_client_id=276`, `market_client_id=277`, `preflight_client_id=288` | Three distinct positive connection identities. |
| `journal=Path("charts/paper/strategy.sqlite3")` | Durable SQLite location. Python constructor requires Path. JSON loader resolves relative paths against the profile file. |
| `window=20`, `quantity=1`, `max_order_value=500`, `max_orders=4`, `max_session_loss=25`, `max_data_age=15` | Same units/meaning as runner and broker settings above. |
| `seconds=600`, `cancel_on_stop=True` | Example-run duration, greater than zero and at most 3600 seconds; pending-order cleanup policy. Not automatic liquidation. |

| Method/function | Arguments and return | Example |
|---|---|---|
| `PaperProfile.load(path) -> PaperProfile` | Validate JSON; reject unknown/transmission fields; resolve journal relative to profile. | `profile = PaperProfile.load("examples/paper_aapl.json")` |
| `profile.to_dict() -> dict` | JSON-compatible settings; explicit account identifiers are retained. | `print(profile.to_dict())` |
| `profile.runner_config(*, execute=False) -> RunnerConfig` | Explicit execute True turns off dry_run in the returned config. Does not connect. | `config = profile.runner_config()` |
| `profile.broker_options(*, execute=False, preflight=False) -> dict` | Keyword arguments for PaperBroker.ibkr. Preflight selects its own client and cannot combine with execution. | `options = profile.broker_options(preflight=True)` |
| `check_profile(profile, *, connect=False) -> dict` | Import from trading.preflight. Validate SDK/config/path; optionally perform read-only account checks. Never authorizes order transmission. | `report = check_profile(profile, connect=False)` |

```python
from pyibquant.trading.preflight import check_profile
from pyibquant.trading.profile import PaperProfile

profile = PaperProfile.load("examples/paper_aapl.json")
print(check_profile(profile)["checks"])  # No socket opened; missing SDK is reported.
```

## Settlement policy

`from pyibquant.trading.funding import SettlementPolicy`.

`SettlementPolicy(version=..., start=date(2026,1,1), end=date(2027,12,31),
holidays=..., equity_days=1, option_days=1, fee_allowance=Decimal(2))` is a
versioned **local conservative policy**, not an exchange-calendar service.
`start/end` bound coverage; `holidays` is a tuple of unique closed dates;
`equity_days/option_days` are positive business-day delays; `fee_allowance` is a
positive Decimal USD reserve per order until fees are known. Default dates and
closures cover 2026–2027 and deliberately hold option proceeds conservatively.

`policy.settlement_date(trade_date, asset_type, currency) -> date` accepts date,
`STK`/`OPT`, and `USD`; skips weekends/closures and refuses out-of-coverage dates.
`policy.to_dict()` serializes dates/Decimals;
`SettlementPolicy.from_dict(value)` reloads that mapping.

```python
from datetime import date
from pyibquant.trading.funding import SettlementPolicy

policy = SettlementPolicy()
print(policy.settlement_date(date(2026, 10, 19), "STK", "USD"))  # 2026-10-20
assert SettlementPolicy.from_dict(policy.to_dict()) == policy
```

Fresh broker limits still cap spending independently of this local ceiling.
See [operational workflows](WORKFLOWS.md) for funding baselines, unknown fees,
settlement obligations, journal locks, recovery and cross-date limits.
