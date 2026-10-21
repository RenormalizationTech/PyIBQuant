# Development handoff

Documentation reviewed: 2026-10-21. Implementation/release baseline: 2026-10-16,
Git checkpoint `f0f79a6`. The primary workflow is on-demand IBKR historical data →
Python research → backtesting. Selected-option historical acquisition is implemented;
a first single-contract historical-bar option backtest is also implemented.
The basic strategy-driven bar simulator is now implemented (see checkpoint below).
Named scientific datasets, quality reports and lightweight study starters are delivered.
The current local development snapshot is 0.1.0.dev1; see docs/API.md and CHANGELOG.md.
Do not require live recording, a large local archive or external historical-data
providers. The research/backtest foundation now includes the validated bounded equity
paper-trading and account-performance workflow described below.

Scope update — 2026-10-19: the standalone charting backlog has been removed,
including saved workspaces, watchlist UI, drawings, general indicator panes,
chart alerts and chart-specific expansion/performance projects. Maintain the
existing optional viewer; scope new plots around concrete research/backtest results
and account/order performance tracking.

## Where to resume


### Paper execution acceptance — 2026-10-21

The owner explicitly requested agent-run bounded paper testing in this chat.
Validation after the quote-refresh fix: 850 tests, Ruff, mypy (43 source files),
source archive/wheel and isolated SDK-free smoke/CLI all pass.
The new execution paths now have TWS paper evidence:

- Cross-session equity recovery: restored `77d386816acd417e94d29b1545d9b339`
  from October 20 with two orders consumed, explicitly rolled its daily baseline,
  and automatically filled one BUY and one SELL on October 21. The original
  four-order lifetime cap is consumed, ownership reconciles flat and fees are
  complete. Today's two fills net -2.207100 USD; the whole run nets -5.434111 USD.
- Selected-option automation: `5ea6f20b6bb647918879d36711dbbfbc`, one AAPL
  2026-11-20 365 C, multiplier 100, two-order cap and six-minute bound. The
  above-SMA runner automatically filled BUY 3.25 and SELL 3.05. Gross -20 USD,
  fees 1.536883, net -21.536883; complete ledger and flat. These are paper results.
- Quiet unchanged option BBOs exposed a caller usability issue. The option example
  now makes one bounded data-subscription refresh at a new decision candle when
  otherwise valid live BBO receipts are stale. It obtains new broker callbacks;
  it never re-dates cached fields or relaxes the 15-second guard. Delayed, crossed,
  missing and disconnected inputs are not retried by this helper. The bounded run
  recorded six live completed-bar signals and six quote refreshes.
- Unknown-send reservation: check `c3eda727ed824cc28fc9e14b8e568b05`, client 297
  order 3, one send attempt. Deliberate own-socket disconnect produced UnknownSend.
  The local 339.02 USD reservation survived restart and the cancellation request.
  Exact-ID recovery canceled that same order unfilled, with no replacement;
  the reservation released to zero and reconciliation is clear.
- Both actual run checkpoints were restored from a consistent journal backup:
  paused, correct option/equity identity, consumed caps preserved, no old balances
  reused as current funds. A fresh read-only TWS preflight passed every check.
  Final account flat, zero pending reservation and no unresolved/foreign orders.

Evidence: ignored `charts/paper/acceptance-2026-10-21/summary.json` and its component
reports; original check artifacts remain under `charts/paper/cancel-checks/` and
run audits under `charts/paper/runs/`. Keep the journal and all recovery identities.
The two exhausted runs are reporting-only for normal strategy execution; do not
increase/reset their budgets to obtain more fills. Explicit owned exits remain
separate from strategy entry/resume.

Both recorded sales are held locally until October 22 under the saved conservative
policy, capped by fresh broker balances. Actual next-date release cannot be observed
on October 21. It and natural partial fills remain pending live observations;
deterministic tests cover both. Automatic broker reconnect, execution corrections
and full historical coverage remain separate backlog. No real-money account was used.


Cleanup after acceptance: removed session scratch scripts, redundant temporary logs,
temporary build directories, synthetic funding-report outputs and Python/tool caches.
Preserved reusable modules/examples/tests, private journals and recovery files,
acceptance reports, the virtual environment and existing distribution artifacts.
Source and documentation changes remain uncommitted.


### Earlier implementation checkpoint — 2026-10-21

Historical checkpoint, superseded by the paper acceptance above.

Implemented and offline-tested: durable USD funding baseline and versioned local
settlement policy; immediate buy/fee debits, partial-fill commitments and retained
cancellation/unknown-send reservations; dated sale release capped by fresh broker
funds; replay and local transmission locking. Explicit session rollover preserves
run ownership/configuration/order budgets while recording a fresh daily P&L
baseline. The selected long-option above/below-SMA runner shares those controls,
including checkpoint restore and owned flatten. Observation remains the default.

Validation: 844 tests, Ruff, mypy (43 source files), source archive/wheel, isolated
SDK-free smoke/CLI and the synthetic offline Chrome account-report check pass.

These are code/offline-test results, not additional TWS execution acceptance.
Read-only TWS preflight passed against the existing journal on October 21:
account, order reconciliation, funding, flat starting holdings and P&L checks all
passed with transmission disabled. Evidence: ignored
`charts/paper/funding-preflight-2026-10-21.json`. A read-only selected-option
runner check resolved the contract and started, then paused on a live-quote
validity/freshness check before a completed signal; zero order intents. Summary:
`charts/paper/option-observation-2026-10-21.json`. This is a verified refusal, not
successful automated execution. At that checkpoint, bounded execution acceptance was pending; it subsequently
passed as recorded above. No order was sent during the initial offline validation. Automatic broker reconnect, full historical coverage,
execution-correction normalization and verified external cash flows remain open.
The local cash ceiling does not automatically credit external deposits/interest;
the default conservative closure calendar covers 2026–2027. See docs/API.md.


### Stop checkpoint — 2026-10-20

Owner chose to stop here and restart fresh later. Basic algorithmic AAPL stock
paper trading is implemented and live-validated: completed-bar decisions submit
orders automatically, with funding/risk limits, fill/fee tracking, ownership,
reconciliation and configured pending-order cleanup. Human launch does not mean
manual approval of each trade. The short durations and four-order budget are the
tested profile settings. Disconnect uncertainty currently pauses trading and can
require explicit recovery; unattended recovery across failures/sessions is unfinished.
Selected long-option BUY/SELL and cancellation are validated; an algorithmic option
strategy runner is not implemented. SPY stays blocked at the owner's request.

No matching strategy/option/cancellation/flatten process was active at this stop
check. Last read-only account preflight passed after the option cancellation:
flat AAPL, zero working/missing/foreign orders, valid funding/P&L. The cancellation
result also confirms the whole account flat and its reservation released to zero.
No broker actions are pending from this session.

For a fresh later session, read this checkpoint and TODO.md, open the intended
paper TWS session, activate `.venv`, and run:

```sh
python examples/paper_preflight.py --profile examples/paper_aapl.json --connect
```

Review fresh state before launching `examples/paper_strategy.py` with the profile
and `--execute` during the regular session. Omitting `--resume-run` creates a new
run with fresh validated state. Keep the existing journal and evidence; a fresh run
does not mean deleting history or resetting an exhausted run's limits. Check for
holdings/unresolved orders rather than assuming the last flat state still applies.
The shipped profile remains one share, $500/order, four orders, $25 session-loss
threshold and 600 seconds; stop can retain filled inventory.

Latest code validation: 795 tests, Ruff, mypy (41 source files), whitespace,
source archive/wheel and SDK-free smoke/CLI pass. Subsequent edits only record
acceptance/documentation. The recorded stop checkpoint preceded commit `986fc9b` (`paper trading finished`).
Consult current Git status for subsequent local changes and push state.
The detailed evidence and remaining broader roadmap follow below.

Cleanup at stop: removed project test/type/lint and Python bytecode caches, the
identified `/tmp/pyibquant` scratch scripts/build logs and two temporary wheel-test
environments (34 files/cache directories). Preserved `.venv`, `dist`, reusable
examples/tests, paper SQLite journals (including sidecars/lock files), run evidence
and saved research results. Generated evidence under ignored `charts/` is retained
intentionally for audit/recovery; it is not disposable scratch data.

### Market-session continuation — 2026-10-20

Owner requested live-market tasks 1–7 plus fresh quotes, quote/feed recovery, SPY
permissions and active-signal controls. Read-only socket access requires sandbox
escalation; the initial sandbox failures were not evidence of a broken TWS setup.

Passed: paper preflight (flat AAPL, clear reconciliation, funding/P&L available),
live AAPL equity and 2026-11-20 340 C quotes including Greeks, bar reconnect/backfill,
and the new live session-controls check. That check observed completed-bar signals
before and after recovery, explicit pause/resume, automatic pause on its own data
socket disconnect, no silent resume, stable stock/option identities and cursors,
visible closed gaps, stop behavior and clear final reconciliation. Broker order
methods were disabled. Evidence: `charts/paper/live-session-controls-2026-10-20/`.

The completed-order coverage probe returned five AAPL records and its completion
barrier; evidence: `charts/paper/completed-order-coverage-2026-10-20/`. Filled records
report totalQuantity=0 but filledQuantity=1. The probe does not merge records into
strategy state or certify historical completeness. Exact-identity completed-order
recovery has since been integrated into `PaperBroker.reconcile()`: nine TWS records
matched in read-only preflight. A separate reconstructed journal omitting the prior
unfilled order's terminal callbacks recovered Submitted to Cancelled and released
the reservation, with zero submissions/cancellations. Evidence:
`charts/paper/completed-recovery-validation-2026-10-20/`. This is a reconstructed
missing-callback test, not a claim of actual disconnect-during-order validation.
SPY live API quote retry failed with IBKR 10089 ARCA/TOP/ALL. Owner explicitly chose
to leave SPY blocked and continue with AAPL.

The owner completed the new 1800-second execution run
`d547a4da804c4e5891518952953d0e4c` from 12:38:41 to 13:08:41 New York time.
Thirty completed-bar signals and thirty loss checks, four one-share fills, no
runner pauses/feed failures. BUY 340.90, SELL 340.76, BUY 340.79, SELL 340.68.
Gross -0.25 USD, fees 4.014050, net -4.264050; flat, complete, issue-free ledger.
Baseline remained -4.854019000000006 (broker account daily P&L at launch).
Fresh read-only preflight confirmed flat holdings, clear orders and usable funding.
This run has used its four-order budget; do not increase its cap or resume it.

Completed owner check: `417b80ac0fcf47958f2c59a89f79f427`, client 297 order 2,
one-share BUY limit 333.59. One send attempt then UnknownSend after own socket loss;
explicit same-ID resume recovered acknowledgment, canceled unfilled and reconciled
flat with a complete zero-execution ledger and no pending reservation. No replacement
was submitted. Evidence: `charts/paper/cancel-checks/417b80ac0fcf47958f2c59a89f79f427/`.

Completed owner-run strategy with the shipped profile and
`--seconds 600 --check-controls --execute`. The offline-tested control harness waits
for a signal and resolved orders, pauses across a candle for at least 65 seconds,
checks unchanged cursor/signals/baseline/configuration/order budget, resumes with
normal reconciliation/risk checks, then requires a subsequent live signal. Expected
progress: `Execution control check: paused`, `resumed`, `passed`, then normal bounded
completion. Existing one-share/four-order/$500/$25 caps and stop policy apply;
filled holdings may remain. New module: `trading/control_check.py`; eight focused
tests in `tests/test_control_check.py`. Actual execution-enabled control acceptance
passed in run `77d386816acd417e94d29b1545d9b339`, 13:23:53–13:33:53 New York
time. Nine signals; pause at 13:24:08, resume at 13:25:13, passed at 13:26:06.
Baseline -9.118068999999982 and caps were preserved. One BUY fill at 341.25,
fee 1.000003 USD; one owned AAPL share retained at stop. Ledger complete and
issue-free, with open-position P&L dependent on last observed marks.

Completed owner exit: `examples/paper_flatten.py --profile examples/paper_aapl.json --run-id
77d386816acd417e94d29b1545d9b339 --execute`. Default invocation was verified read-only
against TWS and plans one owned SELL under the persisted $500 cap. Execution
reconciles afresh, submits at most one limit SELL, waits for terminal evidence and
reports actual strategy/account flatness. It applies the profile's pending-order
cleanup and never buys, adopts external holdings, resumes signals or blindly replaces
an order. Run artifacts remain under the same run directory. Restored flatten now
checks the original checkpoint before writing its own pause checkpoint; a regression
test covers the former self-conflict. Owner execution filled SELL order 13 at 340.03;
two total fills, gross -1.22 USD, fees 2.007011, net -3.227011. Strategy and account
flat, complete/issue-free ledger and no pending reservation. Fresh read-only preflight
is clear (`charts/paper/post-owned-flatten-preflight.json`). Earlier exhausted runs
remain reporting-only.

Owner-run option round trip passed: `e7c2452026e5459d845a3214ff0bfc8a`, client 311,
2026-10-20 14:03:55–14:03:57 New York. BUY one at 2.32, SELL one at 2.17;
gross -15 USD, fees 1.535070, net -16.535070. Complete issue-free ledger,
strategy/account flat, no pending owned order. Saved evidence:
`charts/paper/option-checks/e7c2452026e5459d845a3214ff0bfc8a/`.
Fresh read-only `charts/paper/post-option-roundtrip-preflight.json` is clear.

Owner-run option cancellation passed: `c7a050a5fbad4f7f807738fc3ef9383e`, client 311
order 3, 2026-10-20 14:19:44 New York plan. BUY one at 1.95 was acknowledged and
canceled unfilled. The 197 USD reservation (195 premium plus 2 fee allowance)
released to zero; ledger complete with zero executions/fees, account flat,
reconciliation clear and no pending owned order. Saved evidence:
`charts/paper/option-checks/c7a050a5fbad4f7f807738fc3ef9383e/`.
Fresh read-only `charts/paper/post-option-cancellation-preflight.json` passes:
zero working/missing/foreign orders, flat AAPL, valid funding and account P&L.

The bounded AAPL live-session checks are complete; no further owner command is
pending. Keep SPY blocked as requested. Broader settlement calendars/next-day cash
release, natural partial fills/corrections, full historical recovery, automatic
broker reconnect during execution, multi-session baselines, cash-flow-adjusted
returns and automated option strategies remain unverified or unimplemented.
Do not repeat completed orders or reset exhausted runs to generate more fills.
For future option cancellation uncertainty, ordinary `--resume-check ID --execute`
never submits a replacement BUY. A retained fill requires review before explicit
`--resume-check ID --execute --exit-owned`.

Read-only cancellation preflight passed at 14:09:22 New York: resting BUY limit
1.95, premium 195 USD, quoted spread/fee screen 24 USD; no orders transmitted.
Evidence: `charts/paper/option-checks/c8b971cea7f347e3b5e070e17ffc64a2/`.
Execution refreshes this plan. Current validation: **795 tests**, Ruff, mypy
(41 source files), whitespace check, source archive/wheel and isolated SDK-free
smoke/CLI all pass. Cancellation regressions cover multiplier reservation release,
missing-order recovery without replacement and a fill race retaining inventory.

Initial option API and multiplier-aware accounting are offline tested; read-only
TWS contract/rule/quote/funding preflight passes. Exact contract 845042384,
multiplier 100, SMART market rule
26 reports .01 increments. Harness limits use a coarser .05 grid for the paper
simulator's documented penny-fill limitation, still checked against the actual rule.
At 13:59 New York, plan BUY 2.30 / exit reference 2.15, entry premium 230 USD,
quoted spread plus estimated fees 19 USD. The 360 C candidate failed the spread
budget; no order was sent. Limits re-evaluate at execution and must still fit caps.

The option harness permits one BUY and one SELL attempt, each one contract under
the existing $500 premium cap. Its $25 check is a pre-entry spread/fee estimate,
not a guaranteed realized-loss stop. It records the validated account baseline.
Expiry-day/expired, stale/mismatched quote, missing tick rules/multiplier, external
inventory and uncertain state block orders. Unknown outcomes require the exact
printed `--resume-check CHECK_ID --execute`, which never buys or repeats a sell
attempt. A failed exit may retain an owned contract and requires explicit review.
Earlier read-only evidence:
`charts/paper/option-checks/38366e61883144d48fdbf4b6fba5a7ac/`.
Keep other execution workflows stopped. Full option strategy automation, lifecycle
events, settlement calendars and corrections remain separate backlog.

Post-recovery preflight exposed and fixed a replay bug: legacy `send_unknown`
events omitted client ID and replayed under the observer's current client, creating
a false foreign order (288:2) alongside the canceled real order (297:2). New events
persist client ID; legacy replay uses original session metadata in both broker and
offline replay. Source records are unchanged. Focused cross-client and offline
regressions pass; fresh preflight reports zero working/missing/foreign orders and
flat AAPL. Evidence: `charts/paper/post-disconnect-recovery-fixed-preflight.json`.

Historical launch instructions: `examples/paper_cancel_check.py --profile examples/paper_aapl.json
--execute --disconnect-after-send`. This attempts one one-share AAPL DAY limit BUY
2% below the fresh bid (capped at $500), intentionally disconnects its own broker
socket, and leaves any possibly working order for explicit recovery. Expected
outcome is disconnected_after_send (exit 2); preserve the exact Check ID and then
run `--resume-check CHECK_ID --execute`. The resume command never submits a new
order. Missing outcomes block cancellation/replacement; any unexpected fill is
reported and retained, never auto-sold. Do not repeat the initial submission.
Focused tests cover send uncertainty, one intent, no automatic cancellation,
fresh recovered acknowledgment and exact-order cancellation.
Validation after these changes: 761 offline tests, Ruff, mypy, whitespace check,
source archive/wheel and isolated SDK-free smoke/CLI passed. The read-only fresh
cancellation plan also passed; its price must be refreshed by the execution command.
Broader broker recovery, settlement calendars, corrections, cash-flow-adjusted returns
and automated option strategies remain.
The established broker workflow uses human terminal handoff. The earlier handoff
records an automatic-review rejection, but the original rationale is not available
in this continuation; do not present it as a newly verified blanket paper-trading
prohibition. No permission settings have been changed. The earlier close-of-day
checkpoint below is historical.

### Earlier bounded-equity checkpoint

Recorded checkpoint: **2026-10-20, before this continuation**. The bounded AAPL paper
workflow is validated. The last owner-run reconciliation was flat, with no pending
owned order or reservation. Cleanup did not contact IBKR; this is recorded state,
not a new account observation. All source changes are saved locally and remain
uncommitted; no release or push is implied.

### Validated workflow and evidence

- Saved profile: `examples/paper_aapl.json`; AAPL, one-minute above-SMA(20), one
  share, $500 per-order cap, four orders, $25 account session-loss cap, ten minutes.
  Profiles cannot enable transmission; `--execute` is explicit. The profile cancels
  pending run orders on stop and leaves filled holdings for an explicit exit.
- Run `f88dfa3eef444074aa6c5b4b6cba7396`: ten-minute completion with fills, followed
  by an owner-run process restart/resume. Ownership, baseline 0.0 and the original
  order budget survived. Four fills: BUY 340.61, SELL 340.12, BUY 340.36, SELL 340.01.
  Gross realized -0.84 USD, fees 4.014022, net **-4.854022 USD**. Ledger is complete,
  flat and issue-free. The next entry was blocked by the four-order cap.
  This run is exhausted; do not increase its budget or resume it on another date.
  Evidence: `charts/paper/runs/f88dfa3eef444074aa6c5b4b6cba7396/`.
- Cancellation check `c97af579ef034829b3afd3d383c928a9`: broker client 297 order 1,
  one AAPL BUY limit 333.82, acknowledged and canceled with zero fills. Fresh
  reconciliation was clear, holdings flat, ledger complete with no executions,
  and pending_owned_order=false. Evidence:
  `charts/paper/cancel-checks/c97af579ef034829b3afd3d383c928a9/`.
- Verification: **740 tests**, Ruff, mypy (39 source files), whitespace check,
  source archive/wheel and isolated SDK-free smoke checks pass. Python 3.14 with
  official SDK 10.50.2 is installed locally. Python 3.11–3.13 and separate older-SDK
  environments remain unverified before public release.

### Important implementation decisions

- `PaperBroker` is read-only by default and accepts selected DU paper accounts
  only. Keep `strategy.sqlite3`: it holds order identities, fill ownership, risk
  evidence and recovery checkpoints. Missing or uncertain orders block resubmission.
- Funding requires conservative broker-reported settled USD cash, cash balance,
  available funds and buying power, plus a fee reserve. `SettledCashByDate` uses
  only today's New York balance. `AccountType=INDIVIDUAL` is account structure,
  not evidence of cash versus margin funding. Never infer settlement from buying
  power alone or release tomorrow's sale proceeds locally.
- TWS account P&L requires "Prepare portfolio PnL data when downloading positions".
  Startup waits for validation, including a two-second settling window. A first
  zero reset after trusted nonzero P&L needs another valid callback. Quiet flat
  accounts can use same-day validated journal evidence only after fresh matching
  account/funds/execution/fee downloads. Old receipt times and loss baselines stay
  unchanged. A new date, exposure, changed/unknown evidence or conflicting sample
  blocks reuse. Never fabricate an initial zero baseline.
- Feed receipt is captured before the actual comparison clock to avoid callbacks
  arriving during account/risk work appearing spuriously future-dated. The strict
  15-second limit remains; failed checks journal exact timestamps and ages.
- Account-summary subscriptions are persistent across refreshes. Only readiness
  and currency metadata carry over; balances/positions require fresh downloads.
- `EquityRunner.restore` returns paused. Explicit same-day resume reconciles fills,
  holdings, order budget and risk. A POSIX process lease prevents concurrent local
  execution of one run. Stop, cancel and strategy-owned flatten are separate.
- Broker execution in this chat used human terminal handoff after automatic review
  rejected agent-initiated broker orders/cancellations, including paper transactions.
  Do not bypass that rejection through another tool.

### Next session

No more setup commands are needed today. On a later trading date, inspect the
account and use a **new** bounded run; the validated old run is exhausted and
cross-date resume is intentionally refused. Follow `docs/API.md` for preflight,
observation, execution, recovery, cancellation and offline reports.

Remaining work: longer/multi-session observation, cross-date baseline policy,
settlement edge cases, full completed-order history and corrections, automatic
broker reconnect, then selected options. Live-money enablement is outside this
checkpoint. The full roadmap is in `TODO.md` and `PROJECT_PLAN.md` section 24.
General chart-workspace expansion remains removed from scope.

### Local data and cleanup

`charts/paper/README.md` indexes private data. Primary journals, completed/failed
run evidence, cancellation artifacts and the historical rebalance evidence are
retained. Read-only diagnostic journals and old visual/report checks are archived
under `charts/paper/archive/2026-10-20/`; the archive manifest records original
paths, sizes and hashes. Archives are evidence, not journals to launch a new run
against. `tests/live_paper_check.py` is now read-only; use the separate documented
strategy and cancellation examples for human-run execution.

Generated private data remains Git-ignored. No credentials or account identifiers
belong in source control. The `.venv`, research datasets and historical caches are
preserved. Current package artifacts can be rebuilt with `tests/build_check.py`.

## Historical cleanup checkpoint — 2026-10-16

Removed the superseded recording-based options experiment:

- Sampled quote recording, rotating capture and disk-backed recording replay modules.
- Receipt-based option simulator and its dedicated examples/tests.
- Recording-dependent TWS integration scripts and public package exports.
- Known generated experimental recordings/results under `charts/live-options-validation/`,
  `charts/quote-recovery-check/`, `charts/rotating-options-check/` and
  `charts/options-research-check/` (approximately 4.7 MB of file contents).
- Stale wheel/build output, tool caches and project bytecode.

The removed source is recoverable from Git commit `59da0e5`. Recorded market-data
files were ignored, not committed; those generated experiment files were deleted.
Existing equity research datasets, backtest results, chart assets/caches and the
working `.venv` remain. No broker requests or settings changes were part of cleanup.

Validation: all 261 remaining tests, Ruff, mypy and `git diff --check` pass. A wheel
was built from a clean build directory, checked for absence of removed modules,
installed into a temporary SDK-free environment and passed `tests/wheel_smoke.py`.
The test count decreased because 127 recording/simulation tests were removed with
the obsolete features. Existing retained tests were not weakened; the wheel check
now directly verifies quote streams rather than using a recording round trip.

Inspect `git log -1` and `git status -sb` when resuming or transferring machines.
Changes are saved as local checkpoints; no remote push or release is implied.

## What remains implemented

- Official manually installed IBKR SDK market-data adapter and a separate guarded
  DU-paper-only account/order API; real-money account execution remains disabled.
- US equity/ETF historical bars, fixed start/end ranges, paging/pacing and optional
  exact-query Parquet cache. History is TRADES with split-only adjustment semantics.
- Selected unexpired option intraday history with fixed bounds, exact resolved
  identity/multiplier and TRADES/MIDPOINT/BID/ASK sources. Shared paging/pacing
  and optional query cache; BID/ASK/MIDPOINT volume remains None.
- Immutable bars, CSV/records and optional pandas exports, frozen BarDataset save/
  reload with integrity/fingerprint checks, caller-supplied calendar/finality audits.
- Simple returns, SMA, above-SMA and SMA-crossover research signals.
- Daily single-instrument equity long/flat backtest: prior-close signals execute
  next open, fixed whole shares, configurable commissions/slippage, logs and metrics.
- Explicit option selectors, exact contract resolution/multiplier, grouped option
  discovery, stock/option quote snapshots and available IV/Greeks.
- Independent quote-stream handles/cursors and opt-in reconnect. Recovery clears
  fields/feed confirmation, restores exact resolved contracts and preserves gap
  history. These remain useful for inspection and future strategy feeds.
- Optional native Canvas charts, sessions, history loading, live bar recovery and
  browser controls. Charts remain supporting inspection tools.

Historical option acquisition and a first intraday option backtest are implemented.
Do not describe the removed recorded-quote prototype as implemented functionality.
No recording/rotation/replay API is exported. Do not reintroduce that stack as a
prerequisite for research or automatically download whole option chains.

## Option history checkpoint — 2026-10-16

- `Market.bars(Option(...), interval="5min", start=..., end=..., data_type=...)`
  accepts fixed intraday bounds and TRADES/MIDPOINT/BID/ASK. No lookback/live/session
  mode for options. Stock defaults and current equity backtesting remain intact.
- Exact selector matching, resolved conId, currency, actual multiplier, expiry,
  strike/right, trading class and local symbol are retained with query metadata.
  Adjustment/finality/gap completeness remain unverified. Never assume multiplier 100.
- BID/ASK/MIDPOINT bars preserve missing volume through Python, CSV, pandas,
  frozen datasets, Parquet cache and charts. Served option charts omit stock
  reload/session controls. Fixed-range history cannot load older bars implicitly.
- `examples/research_option_history.py` requests one selected contract, saves CSV,
  metadata, dataset and descriptive returns/SMA signals. Empty/incomplete downloads
  produce no research outputs. `examples/research_saved.py` reuses the dataset
  without IBKR, SDK, pandas or a chart.
- After-hours TWS check: AAPL 2026-11-20 340 C, trading class AAPL, conId 845042071,
  multiplier 100. Completed 2026-10-16 regular session [09:30,16:00) New York,
  five-minute bars: 78 each for TRADES, MIDPOINT, BID and ASK. Verified a MIDPOINT
  cache hit, preserved identity/volume/source and broker-free research reload.
  No live quote subscription, order or settings change was needed.
- Validation: 289 pytest tests, Ruff, mypy, offline Chrome chart regression and
  diff whitespace check. New tests cover all sources, identity mismatch, unsupported
  modes, expiry/future bounds, permissions, empty data, partial/disconnected paging,
  cache separation, missing-volume exports and example behavior.
- Small generated validation inputs/results remain ignored under
  `charts/option-history-check/{TRADES,MIDPOINT,BID,ASK,cache}/`. They are optional
  experiment inputs, not a required market-data archive.

## Option backtest checkpoint — 2026-10-16

- `src/pyibquant/option_backtest.py`: `backtest_option()` and immutable result/logs.
  Single contract long/flat, fixed whole contracts, USD TRADES/MIDPOINT intraday
  inputs. Requires `fill_model="next_bar_open"` and timezone-aware finality assertion.
- Prior-close targets execute at the next supplied open. Overlapping bars are
  rejected. Cash flows and marks use the resolved multiplier; commission is per
  contract per side, slippage adverse in basis points. Insufficient cash rejects
  fills; last-bar signals cannot execute and final positions remain marked.
- Synthetic prices do not establish historical executable fills. BID/ASK-only
  inputs, expiry-day/later bars, shorting, exercise/assignment/settlement and
  adjusted-deliverable modeling are outside this first model. Saved pre-expiry
  data remains usable after expiry. No wall-clock restriction on offline analysis.
- Result retains input fingerprint/metadata, targets, assumptions, optional
  calendar, fills/trades/rejections and cash/position/equity/return/drawdown curve.
  Metrics reconcile realized plus unrealized net P&L with total equity change.
- `examples/backtest_option.py` runs above-SMA or SMA-cross, saving exact frozen
  inputs, strategy settings, JSON results and CSV logs. Both strategies passed on
  the saved 78-bar AAPL MIDPOINT and TRADES inputs with costs; no TWS calls needed.
  Outputs are ignored under `charts/option-backtest-check/{MIDPOINT,TRADES}/`.
- Fixed an existing dataset loader issue: integer OHLCV values used to become
  floats, changing the fingerprint after reload. Numeric representation is now
  preserved; integrity verification still applies and missing volume remains null.
- Validation: 336 tests plus style/typing checks. Tests cover hand-calculated
  nonstandard multiplier/cost accounting, losses/open positions, cash rejection,
  next-bar timing/lookahead isolation, overlapping bars, expiry, invalid inputs,
  source restrictions, calendar/finality, overflow, atomic save and runnable examples.
  A clean SDK-free wheel also passed offline equity/option simulation and dataset
  reload checks without optional dependencies. No chart code changes in this slice;
  previous browser regression remains applicable.

## Strategy-driven backtesting checkpoint — 2026-10-16

- `src/pyibquant/simulation.py`: `Feed`, `Context`/`Strategy`, `Order`, `ExecutionModel`,
  `NextOpen`, `Portfolio`, `SimulationResult`, `TargetStrategy` and `simulate()`.
- Complete frozen daily/intraday inputs, USD only. Existing equity and option
  fixed-size APIs remain compatible; new strategies use the general simulator.
- Explicit close/open clock: publish all completed bars, invoke one strategy
  callback, then execute eligible market orders at actual supplied opens. Strategy
  histories exclude uncompleted bars; execution inputs exclude future OHLCV.
- Different intraday intervals/gaps, empty/stale histories, data ages and mark times.
  Daily feeds use synthetic UTC days and cannot mix with intraday feeds. Intraday
  finality must cover start + interval, unlike the legacy option start assertion.
- Shared cash, submission-order execution, whole long quantities, cash/holding
  rejection, cancellation and end-of-data cancellation. No cash reservation or
  implicit sell-first ordering. `TargetStrategy(..., decision_feed=...)` lets an
  underlying signal trade an option and replaces its outstanding target orders.
- Scaling/partial exits, multiplier-aware weighted-average cost basis including
  allocated entry fees, realized/unrealized P&L. Equity records separate close/open
  phases at adjacent boundaries so drawdown includes both marks and execution costs.
- Model protocol returns a full fill or defers. `NextOpen` supports a flat fee,
  per-unit fee and adverse bps slippage. Settings and strategy parameters are
  serialized with fingerprints, metadata, finality/calendar assertions and logs.
- `examples/backtest_strategy.py` runs equity or underlying-driven option targets
  from saved inputs, saving exact datasets alongside atomic JSON results. Missing
  or stale signals target zero; tolerated signal age is an explicit argument.
- No broker changes/requests are needed. No shorting/margin, FX, limit/stops,
  partial fills or expiry lifecycle. Option simulation horizons crossing expiry
  are rejected even if that option's own data ends earlier. User code/external
  inputs remain responsible for their own lookahead and reproducibility.
- Tests cover accounting with nonstandard multipliers and partial sales, shared
  cash/order priority, cancellation, asynchronous clocks/stale data, future-bar
  isolation, invalid model outputs, SMA parity, atomic results and runnable examples.
- Validation: 389 tests (53 new), Ruff, mypy and whitespace checks pass. A clean
  wheel built from a temporary source copy passed SDK/pandas/PyArrow-free equity
  and option strategy simulation. The example also ran offline on saved AAPL
  2025 daily inputs and the 78-bar option MIDPOINT input, with costs. Outputs are
  ignored under `charts/strategy-backtest-check/{equity,option}/`. Underlying-driven
  option behavior is verified with controlled multi-feed test fixtures, not a new
  live download. No chart changes; prior browser regression remains applicable.

## Scientific research data checkpoint — 2026-10-16

User direction: scientific research means enabling users to study market structure
(e.g. correlations, scaling/multifractality and random matrices). Keep built-in
analysis small; prioritize solid, useful datasets requested/loaded from IBKR.
Backtest comparisons and out-of-sample reports remain backtesting features.

- `BarDatasetCollection` stores named frozen inputs in one atomic integrity-checked
  JSON document; every input retains its full bars, fingerprint and provenance.
- Explicit inner/outer exact bar-start alignment requires matching interval,
  timestamp kind and session settings. Known incomplete downloads are rejected.
  No filling/resampling or inferred calendar; dropped/absent/null counts and source
  metadata accompany records and optional pandas output. Unknown quality stays unknown.
- `examples/research_collection.py fetch` uses bounded sequential equity/ETF queries
  and existing pacing/cache; no collection is written on empty/incomplete/failing
  inputs. `inspect` loads and aligns offline. Selected-option datasets can also be
  put into collections via Python; no bulk option-chain download is introduced.
- Validation: 423 tests (34 new), Ruff, mypy, whitespace checks and a clean
  SDK/pandas/PyArrow-free wheel smoke pass. Previously saved AAPL option inputs
  for TRADES/MIDPOINT/BID/ASK round-tripped with unchanged source fingerprints;
  both joins retained 78 UTC starts, nullable volume remained absent and offline
  inspection exported 78 rows. Outputs remain ignored under
  `charts/scientific-data-check/`. This is reuse of saved data, not fresh acquisition.
- Fresh TWS AAPL/MSFT/SPY acquisition for [2026-10-12,2026-10-16) passed:
  four daily bars per instrument, both joins retained four dates with no absent
  observations among inputs, and offline inspection/CSV export passed. The initial
  connection failure was sandbox network denial (direct socket errno 1), not a
  disconnected TWS. Retrying with approved network access succeeded. Inputs and
  exports remain ignored under `charts/scientific-data-check/`. No orders or
  account/settings changes were made. Next: follow concrete scientific data needs. Do not build advanced estimators or
  prioritize performance reports as the scientific research milestone.

## Dataset quality and named acquisition checkpoint — 2026-10-16

- `BarDataset.describe()` and collection `describe()` summarize recorded identity,
  sampling/source/adjustment/session semantics, queries, coverage, download progress
  and fingerprints. `quality_report()` adds JSON-compatible observation flags,
  warnings/errors and optional caller calendar/finality checks. No source mutation,
  inferred expected calendar, automatic repairs or overall quality score.
- Finality in reports uses `audit()`'s inclusive BAR-START convention, explicitly
  distinct from the general simulator's intraday end-coverage requirement.
- Collection reports accept calendars/finality keyed by input label. They expose
  source differences and optional alignment losses; incompatible/partial inputs
  still receive individual reports with an unavailable-alignment reason.
- `Market.datasets(mapping, start=..., end=..., interval=...)` requests and freezes
  named inputs sequentially through existing `bars()` paging/pacing/cache. Strings
  and Options default to TRADES; `BarRequest` supports per-input option sources
  and equity primary exchanges. Common hours, refresh and equity-only sessions.
- First error/empty/incomplete input raises `DatasetCollectionError`: `failed_key`,
  read-only `completed` mapping, original `__cause__` (including partial-page
  HistoricalRangeError). No automatic retries, later requests or filesystem writes.
  The example now uses this public API and can export `--quality-report` JSON.
- Fresh TWS checks passed: AAPL/MSFT/SPY, four daily bars each for
  [2026-10-12,2026-10-16); mixed AAPL equity plus 2026-11-20 340 C MIDPOINT,
  six five-minute bars each on 2026-10-16 [09:30,10:00) New York. Option identity
  conId 845042071/multiplier 100 and nullable volume preserved. Explicit calendar/
  finality checks and broker-free reload, reports and CSV export passed.
  Artifacts remain ignored under `charts/scientific-quality-check/`.
- Use approved network access for live checks: the default execution sandbox denies
  local sockets (errno 1) even while TWS is listening. No TWS/account/order changes.
- Validation: 475 tests (52 new), Ruff, mypy and whitespace checks pass. A clean
  wheel passed existing smoke checks plus named request coordination and quality
  reports without SDK/pandas/PyArrow installed. New tests cover anomalies, unknown/partial/empty
  inputs, mismatched calendars, reports on incompatible collections, source
  differences, acquisition ordering/preflight/failures and offline example outputs.
- The agreed scientific-data foundation is delivered. Further transformations,
  sampling/calendar integration or acquisition scope should follow a concrete study;
  advanced statistical estimators remain user-owned. Backtest reports stay separate.

## Lightweight study starters checkpoint — 2026-10-16

- User requested both daily correlations and intraday scaling preparation, provided
  they require no extra packages or complicated construction. `pyibquant.studies`
  uses only the standard library; no dependency/configuration changes.
- `daily_correlations(collection)` constructs log returns on adjacent union dates
  before listwise selection, preserving endpoints/missing values and reporting
  common sample/exclusion counts plus Pearson matrix. Constants/insufficient data
  yield null correlations. No filling or source/currency harmonization.
- `intraday_scaling(dataset, lags=..., session_timezone=...)` exports log-price
  increments and first absolute/second moments. Exact uninterrupted grids and
  same local date required; missing intermediate bars and date changes break
  sequences. Explicit timezone needed if source metadata is unknown. Overlapping
  increments remain dependent; no fitted exponents/Hurst/multifractal claims.
- Both helpers reject empty, nonpositive-close and incomplete/unknown-download
  inputs. Reports retain source fingerprints, quality evidence and assumptions;
  provenance/finality remains unchanged. Calendar completeness is not inferred.
- `examples/research_studies.py` runs either workflow entirely offline against a
  saved collection, writing JSON values/results/provenance. It prevents overwriting
  source inputs. See README for acquisition and analysis commands.
- Fresh TWS validation: AAPL/MSFT/SPY 2025 daily inputs (250 rows each, 249 common
  log-return observations), AAPL five-minute [2026-10-12,2026-10-16) (312 bars;
  308/304/296/280 valid increments at lags 1/2/4/8). Offline examples passed.
  Generated artifacts ignored under `charts/scientific-studies-check/`.
- Validation: 497 tests (22 new), Ruff, mypy and whitespace checks pass. A clean
  wheel ran both helpers without SDK/pandas/PyArrow/NumPy/SciPy dependencies.
  New tests check known inverse correlations, missing-period
  isolation, constants, hand-calculated moments, gaps, timezone/date boundaries,
  input restrictions, empty lags and offline CLI safety.

## Development snapshot checkpoint — 0.1.0.dev1

- Reviewed supported API entry points and added `docs/API.md`, with acquisition,
  quality/alignment, scientific helpers and simulation in one workflow. Updated
  overview/roadmap statements that still described delivered features as next work.
- Added `CHANGELOG.md`, explicit source manifest and version `0.1.0.dev1`.
  Source distributions include docs, examples and validation scripts; generated
  datasets, virtual environments and credentials are excluded by curated copying.
- Fresh `tests/live_workflow_check.py` passed through TWS: AAPL/MSFT/SPY daily
  2025 inputs and AAPL/selected 2026-11-20 340 C MIDPOINT for the completed
  2026-10-16 regular session. All post-download work runs after broker close:
  persistence, quality, correlations, scaling, equity/option/general strategy
  simulation and HTML generation. No account/orders/settings changes.
- Chrome offline regressions passed for native chart interactions, history
  pagination and session/freshness/reconnect rendering. No shared live-chart
  session or TWS settings were changed by these tests.
- Release acceptance: 497 pytest tests, Ruff, mypy, whitespace checks; build source
  archive, then wheel from that archive, inspect contents and run SDK/optional-
  dependency-free wheel smoke and CLI checks. `tests/build_check.py` performs the
  artifact checks using existing tools, without downloads. Artifacts/checksums go
  under ignored `dist/`. Re-run it after changing source or docs.
- Locally tested with Python 3.14 only; Python 3.11+ remains declared compatibility,
  not a validated multi-version matrix. No CI/automatic SDK install introduced.
- This is a local development checkpoint. No remote push, tag or publication is
  implied. Further scope should follow concrete research needs or a separate
  explicit execution/backtesting request.

Implementation entry points:

- `src/pyibquant/dataset.py`, `collection.py`, `requests.py`, `Market.datasets()` and
  `tests/test_dataset_quality.py`/`tests/test_dataset_requests.py`: descriptions,
  quality assertions and named acquisition/error handling.
- `src/pyibquant/collection.py`, `examples/research_collection.py` and
  `tests/test_collection.py`: scientific data collections and alignment.

- `src/pyibquant/simulation.py`, `examples/backtest_strategy.py` and
  `tests/test_simulation.py`: general strategy, execution and portfolio tools.
- `src/pyibquant/option_backtest.py`, `examples/backtest_option.py` and
  `tests/test_option_backtest.py`: new option simulation, reports and regressions.
- `src/pyibquant/research.py` / `backtest.py`: shared research and equity simulator.
- `src/pyibquant/bars.py` / `dataset.py`: provenance, nullable volume and audits.
- `src/pyibquant/market.py` / `data/providers/ibkr.py`: bounded option acquisition.

IBKR excludes expired options and option end-of-day data from historical access.
Scope initial work to available intraday history for a resolvable option. Current
chain discovery cannot reconstruct historical option universes. Do not fabricate
historical Greeks, sizes, quote receipts or live feed confirmation from OHLC bars.
MIDPOINT bars do not imply executable bid/ask fills; BID_ASK bars have special
aggregate semantics. See [IBKR limitations](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction)
and [bar definitions](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars).

## Setup and local checks

Use Python 3.11+ and the existing `.venv`, or create a new environment and install
`.[dev]` plus optional `.[cache]`/`.[pandas]` only as needed. Install the official
TWS Python SDK 10.33+ manually into that environment; do not use the old PyPI ibapi.
See README for SDK installation and the complete API examples.

TWS/Gateway must be logged in for acquisition, with API socket access and appropriate
market-data permissions. Keep Read-Only API enabled. Defaults: localhost:7497,
client ID 71; choose a unique ID for concurrent clients. Saved-data research and
equity backtests require no broker or SDK. CI/automatic SDK installation remain
outside scope. No broker-connected paper trading is implemented.

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check src examples tests
.venv/bin/mypy
```

Explicit TWS checks are separate from pytest: `tests/live_ranges_check.py`,
`tests/live_exports_check.py`, `tests/live_quotes_check.py` and
`tests/live_recovery_check.py`. The last reconnect script disconnects only its
own client socket for bar recovery. Do not run these just to work on saved data.

Preserved local equity inputs/results include `charts/research-live-check/`
(AAPL 2025 daily bars, signals and calendar) and `charts/backtest/` (above-SMA and
SMA-cross results). The ignored `charts/` directory is not carried by Git; save
specific research inputs separately when transferring machines. `.venv` is also
machine-local. No credentials, account IDs, SDK downloads or generated datasets
should be committed.
