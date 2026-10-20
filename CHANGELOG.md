# Development changes

## 0.1.0.dev1

Local development snapshot; no published release is implied.

- Record October 20 owner-run validation of bounded AAPL strategy execution,
  same-day restart, execution controls, owned flattening, disconnect-after-send
  exact-ID recovery, and selected-option buy/sell and unfilled cancellation.
  Exact-identity completed-order recovery is integrated. Settlement calendars,
  execution corrections, automatic broker reconnect, multi-session recovery and
  automated option strategies remain open.

- Reconcile the end-of-day paper validation checkpoint and private-data index.
  Replace the superseded combined integration order check with read-only account
  acquisition; keep human execution in the separate strategy/cancellation examples.
- Add a read-only-by-default AAPL cancellation check: one bounded resting limit,
  broker acknowledgment, exact-tag cancellation and terminal reconciliation.
  Persist check identity/artifacts; recover the original order without replacement.
  Treat partial/full fills, rejection, missing acknowledgment and uncertain sends
  separately from a confirmed unfilled cancel; never automatically unwind a fill.
- Fix live-bar freshness races during account/risk reads: capture feed receipt
  before the real clock, including resume and post-refresh checks. Keep the
  15-second limit and explicit-clock future rejection; journal exact ages on failure.
- Fix startup skipping P&L validation when its first callback is absent. Persist
  same-day flat-account validation evidence across preflight/strategy connections;
  require fresh matching account downloads and retain explicit confirmation
  timestamps. Anchor evidence to callback-time account state and block reuse on
  any changed or unknown funds, exposure, orders, fills, fees or conflicting P&L.
- Confirm stale flat-account risk through fresh unchanged USD account downloads,
  preserving the P&L receipt time and session-loss baseline. Changed funds,
  exposure, orders, executions or fees still require fresh P&L. Validate the active
  subscription at startup without renewal; diagnose missing initial callbacks.
- Add a saved AAPL paper profile, read-only local/API preflight and documented
  launch/recovery/report sequence. Profiles cannot enable execution. Validate
  bounded settings, dedicated client IDs, account/funding/contract/P&L readiness
  and retain explicit runtime live-data/session checks and human order handoff.
- Add versioned runner checkpoints and explicit paused restore, preserving run
  identity/configuration, daily loss baseline, candle cursor, order counts and caps.
  Reconcile holdings and unresolved intents before resume; a local process lease
  prevents concurrent execution of the same run/journal. Legacy runs are report-only.
- Add offline journal report generation and per-run FIFO realized/unrealized P&L,
  fees, observed dollar drawdown, exposure curves, scoped orders/fills and CSV
  exports. Keep timestamped marks and unknown fees visible; retain per-run artifacts.
- Fix a false session-loss stop caused by IBKR's transient zero P&L on subscription
  renewal. Collect the initial update burst, require confirmation of all-zero
  resets, validate execution-start baselines and keep unconfirmed samples out of
  resume. Journal risk comparison numbers and show them in loss-stop messages.
- Fix a false stale-P&L pause after closing the starting share: renew the read-only
  P&L subscription before a stale risk check, require a valid new-generation sample,
  preserve the loss baseline and recheck market-data age after waiting.
- Add an explicit one-share starting-position close/preflight to the bounded
  strategy example. Confirm a full fill and flat holdings before starting; keep
  the manual close separate from strategy ownership and support cleanup on stop.
- Add explicit reconciliation reports, immutable terminal order waits with partial
  evidence on uncertainty, and exact-tag cancellation with confirmation waits.
- Add persistent fill-based strategy ownership/cash-flow/fee audits and masked JSON
  export. Missing executions block ownership-based actions; open P&L is not inferred.
- Add in-memory runner resume preserving limits/baselines and explicit owned-only
  flattening. Every trading decision checks holdings against its recorded fills.

- Fix multi-date settled-cash parsing after sales: select today's balance without
  releasing tomorrow's proceeds. Repair order average-price reporting from actual
  executions and preserve it against late zero-valued status callbacks. Add a
  flat-account-only `--buy-only` resume to the owner-run paper check.
- Fix repeated paper-account refreshes exhausting TWS account-summary subscriptions
  (IBKR 322). Retain one summary subscription, redownload current balances/positions,
  preserve currency metadata and report missing download stages on timeout.
- Add a dedicated read-only-by-default `PaperBroker`, immutable account snapshots,
  transactional local history and cash/value/P&L reports with a localhost viewer.
- Add an explicit holding-only market-sell command and a read-only-by-default
  liquidation/one-share-AAPL check. Market buys/shorting remain disabled. Actual
  broker execution requires human handoff; the agent's approved preflight sent no orders.
- Add experimental paper equity DAY limit orders, owned cancellation, durable intent
  keys, partial-fill/fee callbacks and conservative broker-based USD funding checks.
- Add a bounded completed-bar above-SMA runner with observation-only default,
  explicit controls, fresh-data checks, loss/position/order limits and no blind retries.
  Broker account monitoring, live-data observation and bounded order integration
  are verified; broader recovery/accounting remains unfinished. Real-money execution
  is disabled.
- Add an optional daily US stock/ETF Yahoo chart preview (`.[yahoo]`,
  `--provider yahoo --interval 1d`) with explicit source/adjustment warnings.
  IBKR remains the default; connection/SDK failures suggest switching explicitly.
- Add strategy-driven daily/intraday portfolio simulation: multiple explicit feeds,
  completed-bar callbacks, shared USD cash, whole long quantities, scaling/partial
  exits, cancellable market orders and replaceable execution models.
- Add named frozen dataset collections with atomic persistence, integrity checks,
  explicit inner/outer timestamp alignment and records/optional pandas exports.
- Add dataset descriptions and quality reports with source semantics, observation
  flags, optional caller calendar/finality assertions and alignment diagnostics.
- Add `Market.datasets()`, per-input `BarRequest` selectors and first-failure
  diagnostics retaining completed inputs and the original cause.
- Add standard-library daily log-return/correlation and intraday increment/moment
  study starters, with offline examples and preserved provenance.
- Retain existing bounded equity/selected-option IBKR history, quotes, charts and
  fixed-size equity/option backtests. Advanced science methods remain user-owned;
  no new mandatory dependencies. Paper execution is a separate experimental API.
- Document supported APIs, differing finality conventions and local build checks.
  Source distributions include examples, guides and validation scripts, excluding
  generated datasets and virtual environments.

Initial scope remains USD/US equity and selected-option research. Simulation uses
explicit synthetic execution assumptions; no shorting, margin, multi-leg/lifecycle
accounting or daily/intraday clock mixing. Scientific helpers do not certify data,
infer missing prices or establish multifractality. See README and docs/API.md.
