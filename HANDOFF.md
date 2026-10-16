# Development handoff

Checkpoint: 2026-10-16. The user clarified the primary product constraint:
options research/backtesting should use on-demand IBKR historical requests, without
mandatory live recording, large archives or external historical-data providers.
Historical option acquisition is the next implementation task. Existing recording,
rotation and reconnect tools remain optional support. The last code checkpoint
passed all 388 local tests, Ruff and mypy; this direction update changes docs only.

The current changes are saved as a local Git checkpoint; inspect `git log -1` and
`git status -sb` when resuming or transferring machines. No remote push is part of
this checkpoint. Generated market data/reports remain local under ignored
`charts/`. This is a development checkpoint, not a release.

## Where to resume

Read [README.md](README.md), [PROJECT_PLAN.md](PROJECT_PLAN.md), then
[TODO.md](TODO.md). Price-axis dragging, vertical panning, and autoscale toggle/reset
are implemented, along with time-axis dragging for candle spacing and configurable
right space. Older-history loading now supports automatic fetches when panning
left, a Load older button, retries, deduplication and stable viewports. Optional
Parquet caching, fixed New York display with DST-aware labels and a browser
regular/extended-hours selector are implemented. Provider schedule shading, date separators/ticks, a bar-boundary countdown,
receipt-time status and automatic reconnect/backfill have since been added.
Product direction now prioritizes convenient Python access to IBKR for research,
backtesting and algorithmic trading. Bar exports and optional session enrichment
are now implemented. Fixed historical ranges, basic dataset metadata, simple
returns/SMA and a research example have since been added with offline and live TWS
verification. Frozen dataset reload and explicit calendar/finality comparisons are
also implemented. The first daily equity backtest now works offline. Grouped
option discovery, independent quote streams and sampled recording/offline replay
are now implemented. Frozen AAPL integration checks pass. The user chose our
collected recordings for the first options backtest. Its intraday, SDK-free
long/flat simulator and offline JSON/CSV example are now implemented. Live-session
capture and offline simulation were verified on 2026-10-16. An explicit side-update
freshness policy now completes simulated round trips on both live recordings.
Opt-in quote reconnect and gap/generation recording have local test coverage.
Next: implement a small IBKR historical request for one explicitly selected option
and an intraday fixed range, then research and backtest the returned history.
Live reconnect verification and recording-scale work are optional and deferred;
an open market or live recorder must not gate the primary research workflow.
See the current-direction follow-up below. Earlier sections preserve implemented
experiments and validation history, rather than setting current priorities.
Charts are supporting inspection tools. Saved chart workspaces
and TradingView-style feature parity are secondary backlog items.

Audience priority: equities/ETFs are the general-user entry point; options
trading/backtesting is a major product use case and the owner's primary personal
interest. Preserve instrument identity and contract multiplier semantics when
extending datasets/accounting. After the shared equity research/backtest slice,
prioritize stock/option quotes and an options pilot without waiting for scanners
or chart parity. Plan historical option dataset imports and selected quote
recording separately from IBKR data acquisition; do not assume expired histories
can be recovered or sampled quotes are a full tick archive.

Keep manual `ibapi` installation and logged-in TWS/Gateway as prerequisites for
IBKR access. CI and automated SDK distribution are outside current scope. Keep
local unit, browser and explicit TWS integration checks.

## Current direction — on-demand IBKR option history

The user explicitly constrained scope after reviewing the recording-centric agenda:
"We should constrain ourselves to IBKR historical requests for options also, where
data can be requested on the fly from IBKR." This supersedes earlier recorded-quote
input priorities. Research and backtesting come before paper execution; existing
recorders remain optional diagnostics, not a prerequisite or collection service.
Do not expand vendors, whole-chain collection, persistent archives, recording
rotation or streaming recorded-quote simulation as the next default task.

Next implementation slice:

1. Resolve one explicit unexpired option using the existing Option selector and
   provider resolution. Request a short, completed intraday historical range from
   IBKR with explicit TRADES/MIDPOINT/BID/ASK semantics, starting with a small
   five-minute-bar example. Use fixed start-inclusive/end-exclusive bounds.
2. Reuse historical paging/pacing and optional query caching. Preserve the resolved
   contract's identity, selector, currency, multiplier, data type and requested
   range in metadata. Request only user-selected contracts/ranges; no automatic
   full-chain history download or mandatory database.
3. Verify returned historical bars against TWS, including outside trading hours
   when IBKR history services and permissions are available. Surface unavailable
   history and permission failures explicitly; never substitute live recording.
4. Add saved-input research and a separate historical-bar option backtest with
   explicit signal/fill/cost assumptions. Expand financial research analytics and
   result reporting before paper trading. Saved inputs are optional, bounded
   experiment snapshots, not a required growing collection.

Implementation findings: `Market.bars()` currently accepts stock symbols. The
provider's `bars()`/`bars_range()` resolve stock contracts, cache TRADES queries
and set equity identity/multiplier one in `_set_identity()`. The existing option
resolver and quote identity retain exact conId/multiplier and can inform the new
historical path. Preserve existing equity behavior and provider boundaries.
Option historical requests and bar-based option simulation are not implemented yet.

The current `backtest_option()` consumes recorded quote observations with local
receipt clocks, sizes and feed-type checks. Historical OHLC bars are different
inputs: do not manufacture live labels, quote receipt times, displayed sizes or
Greeks to force them into that engine. Do not assume a MIDPOINT series supplies
executable bid/ask fills. IBKR BID_ASK bars also use special aggregates, not
ordinary OHLC or an atomic bid/ask quote.

IBKR explicitly excludes expired options and option end-of-day data from its
historical offering. Scope initial work to available intraday history of a
currently resolvable option. Current chain discovery cannot reconstruct a past
chain universe, and historical contract Greeks are not promised. Keep these
constraints visible rather than automatically introducing another data vendor.
Primary references: [IBKR limitations](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction)
and [historical bar definitions](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars).

Validation for this checkpoint: documentation consistency and `git diff --check`.
No production code changed, no broker requests were made and the 388-test result
belongs to the preceding code checkpoint (`59da0e5`).

## After-hours recovery, rotation and disk replay — 2026-10-16

This checkpoint supersedes the earlier competing-session blocker. The user restored
market-data access after the close and authorized the work that does not require
an open market. All requests remained data-only; no settings, other sessions or
orders were changed.

Verified against TWS:

- `python tests/live_quote_recovery_check.py --market-data-type frozen --client-id 218`
  passed. The check disconnects only its own socket, preserves the owner/cursor,
  records a replacement generation and gap, receives new confirmed-frozen fields,
  cancels the restored subscription, reloads offline and verifies simulator refusal.
  Result: 120 samples, 108 frozen/12 unknown labels, 107 bid/ask pairs, 92 model
  IV/delta observations, one replacement generation and one recorded gap.
  Local artifacts: `charts/quote-recovery-check/20261016T213306389445Z/`.
- `examples/options_research.py` with the selected AAPL 2026-11-20 340 C, frozen
  mode, duration 6, interval .5, max samples/file 4 and client 219 passed.
  Result: 12 samples across three files, ten confirmed-frozen bid/ask and model
  IV/delta observations, two initial unknown samples, no crossed/delayed quotes.
  The stream/Market closed before set replay. Local artifacts:
  `charts/rotating-options-check/20261016T213804974068Z/recording/`.
- Both artifact directories retain `validation.json` with metadata, quality and
  input fingerprint. Data/reports stay under ignored `charts/`, outside Git.

New APIs and behavior:

- `QuoteRecording.open(path)` is a context-managed disk-backed alternative to
  immutable in-memory `load()`. It validates the entire file before returning,
  then rechecks integrity/fingerprint on every complete iteration. Its held file
  descriptor prevents path replacement from swapping inputs. Rows and metadata
  are independent copies; one iterator may be active per reader. Do not modify
  inputs in place; exhaust iterators to detect edits during replay.
- `record_quotes_rotating(stream, directory, duration=..., interval=...,
  max_samples=...)` writes exclusive numbered segments with independent footer
  checksums and predecessor hashes. A checksummed manifest is atomically published
  only after a graceful finish; terminal failures publish explicit partial status.
  IO errors/crashes leave diagnostic segments without a successful manifest.
  Existing directories are never overwritten. Rotation does not reset sampling,
  quote sequence, feed provenance or gap history. The caller owns the stream.
- `QuoteRecordingSet.open(manifest)` prevalidates all ordered segments and streams
  the complete logical session. It checks raw segment bytes, identity, counts,
  predecessor chain and cross-segment sequence/gap continuity. Missing/corrupt
  segments fail even with partial inspection enabled. Memory retains the largest
  sample/gap history plus the manifest descriptors, not every sample.
- `quality()` now counts distinct monotonic quote sequences without retaining a
  growing set. Replay memory tests use 2,000 samples in both single-file/set form
  and pass a peak allocation limit below 1 MB for inputs larger than 1 MB.
- The options simulator refuses individual rotation segments because a segment
  footer does not certify a complete session. The existing backtest CLI still
  consumes single-file inputs. Streaming simulation, exact multi-file input export,
  closed-file resume/restart recovery and automatic pruning remain future work.
- `examples/options_research.py --max-samples-per-file N` captures a set;
  `examples/replay_quotes.py PATH [--recording-set] [--allow-incomplete]` validates
  and summarizes inputs offline without SDK/optional dependencies.

Validation: all 388 local tests, Ruff, mypy and `git diff --check` pass. Tests cover
legacy inputs, corruption before exposure, consumer mutation, concurrent iterators,
path replacement, reader cleanup with unfinished iterators, missing/reordered/duplicated
segments, erased cross-segment gap
history with recomputed hashes, partial states, disk failures and bounded memory.
The common streaming validator also backs the existing immutable loader.

Remaining market-session check: run `python tests/live_quote_recovery_check.py`
when confirmed-live data is available. The explicit frozen run verifies lifecycle
only; it does not replace that live check or make frozen data a simulation input.

## Quote freshness and reconnect follow-up — 2026-10-16

The earlier strict-clock results below are preserved as baseline evidence. IBKR's
[streaming-data documentation](https://www.interactivebrokers.com/docs/tws-api/doc/md/streaming-data)
explains that size changes can arrive without repeating an unchanged price.
`backtest_option(..., quote_age_basis="side_update")` now explicitly uses matching
live bid/ask size confirmations at/after the corresponding current prices. Both
side clocks must satisfy age/skew; the execution side needs a post-signal update.
A new price waits for its following size. Price receipts are never rewritten;
last/Greek/opposite-side activity cannot renew the execution side. The original
`price_receipt` policy remains the default with unchanged execution behavior.
Result schema version 2 records the policy and all three fill clocks
(`price_received_at`, `size_received_at`, `side_received_at`).

Both original live recordings were rerun offline with the explicit side-update
policy, retaining commission 1 per contract/fill, 5 bps slippage and default
age/skew/latency limits:

- November 340 C: one completed simulated round trip, net P&L -38.4125,
  final cash/equity 9961.5875, zero ending contracts, two unpriced observations.
- October 345 C: one completed simulated round trip, net P&L -32.42,
  final cash/equity 9967.58, zero ending contracts, ten unpriced observations.
- Both retain unknown full-path drawdown. These short runs validate simulation
  accounting, not profitability or executable liquidity. The strict policy still
  leaves both positions open and final equity unknown.
- Each original capture directory now also contains `hold-window-side-update/`
  with exact inputs, results, CSV logs and `validation.json`. Independent audits
  passed byte/fingerprint equality, identical replay, post-signal side confirmation,
  unchanged original price receipts, ask/bid costs, cash and round-trip accounting.

`Market.stream_quote(..., reconnect=True)` now opts into the existing Market
recovery supervisor (requires `Market.ibkr(reconnect=True)`). Recovery preserves
owner and cursor identity, reissues the exact conId and discards old prices, sizes,
Greeks and feed confirmation immediately. Every replacement increments `generation`.
Immutable `gaps` retain disconnect time/reason and replacement request time, even
when the outage falls between samples. Replacement time does not certify restored
quote availability or exchange continuity. Terminal data/permission failures are
not retried; owner cancellation prevents resurrection. Late callbacks from a
retired request cannot modify the replacement state.

New quote recordings use format version 2; version 1 still loads. Replay validates
gap history and generation progression, rejects carried pre-gap fields and preserves
outages missed by sampling. A duration ending disconnected is incomplete. All
reconnect-gap recordings are refused by the first simulator, even if recording
begins after recovery. File rotation, closed-file resume and large-file streaming
replay remain planned.

Run `python tests/live_quote_recovery_check.py` after restoring TWS market-data
access. It uses client 217, disconnects only its own socket during a short capture,
and checks new live fields, gap-preserving offline reload, selective cancellation
and simulator rejection. The 2026-10-16 attempt at about 13:37 New York time
resolved the contract but received **IBKR 10197: No market data during competing
live session**, before reaching the intentional socket disconnect. Thus live
recovery is not yet verified. The user confirmed access cannot be restored now
and requested that work stop here. Resume only after the user confirms this TWS
session is ready; no TWS settings or other sessions were altered.

Local checks cover default compatibility, side-update causality, missing/mismatched
size evidence, latency, costs, quote-only reconnect, retry failures, terminal 10197,
close during restore, retired callbacks waiting on locks, gap tampering and legacy
recordings. All 356 local tests, Ruff and mypy pass. Rerun
`python -m pytest -q` after subsequent edits. No orders were submitted.

## Live options validation baseline — 2026-10-16

Data-only TWS capture on port 7497 succeeded during the New York trading session
at approximately 13:24–13:27. Both runs discovered 41 chain groups and closed
their streams/connections before offline simulation. No broker orders were submitted.

- AAPL 2026-11-20 340 C: 60 seconds at 0.5-second intervals; 120 samples,
  118 confirmed-live bid/ask and model IV/delta observations, two initial unknown
  feed samples, 69 distinct observed versions. Local artifact directory:
  `charts/live-options-validation/20261016T172405542548Z/`.
- AAPL 2026-10-23 345 C: 120 seconds at 0.5-second intervals; 240 samples,
  239 confirmed-live bid/ask observations, 238 with model IV/delta, one initial
  unknown feed sample, 147 distinct observed versions. Local artifact directory:
  `charts/live-options-validation/20261016T172529876813Z/`.
- Both recordings completed with valid integrity checks, no crossed pairs and no
  frozen/delayed samples. Each directory retains `chain.json`, `quotes.jsonl`,
  `validation.json`, and `hold-window/` and `spread-filter/` result exports.
- Both strategies used one contract, 10,000 initial cash, commission 1 per
  contract per fill, 5 bps adverse slippage, and unchanged default receipt-age/skew
  limits. Hold-window used 30 seconds; spread-filter used a 5% relative spread.
- November hold-window entered at 14.30715 including slippage, leaving cash
  8568.285. October hold-window entered at 4.352175, leaving cash 9563.7825.
  Both remained long one contract; final equity, total return and drawdown were
  unknown. Exit attempts were blocked by stale price receipt times.
- Size/Greek callbacks continued while prices stayed unchanged or updated too
  infrequently for the two-second age and one-second skew checks. An active live
  feed does not imply every field has a recent receipt. Neither clock was reset
  from unrelated callbacks and no eligibility limit was loosened.
- November spread-filter produced no fills (new-price/age/skew gates); October
  spread-filter stayed flat because the spread exceeded its 5% threshold.
- Independent offline audits passed exact exported input bytes/fingerprints,
  identical rerun results, fill timing after signals/new price receipts, ask/bid
  slippage, cash/position accounting and realized-P&L consistency. Neither live
  recording produced a completed trade under the strict default. The subsequent
  explicit side-update policy completes both round trips, as recorded above.
- All 317 local tests passed, including 81 focused option discovery, recording,
  stream and backtest tests. No production code change was needed for this check.

This baseline led to the side-update policy and reconnect implementation described
above. Further valuation coverage, live reconnect verification, recording rotation
and large-file replay remain open. Exercise/assignment/settlement and broker
execution remain separate work. Generated data and reports stay local under
ignored `charts/`.

## Architecture to preserve and boundaries to improve

Keep normalized immutable bars, Python snapshots, the provider boundary and lazy
chart imports. They let research consume data without opening a browser. Existing
charts are useful inspection tools, not a required strategy runtime.

Session enrichment, bar exports and fixed-range metadata are implemented and
verified against TWS. Daily equity and intraday option replay have explicit
execution timing. Before adding broker-connected strategies, define completed-bar
events and separate chart/strategy bar-subscription ownership. Current chart
selection cancels the previous series; do not attach a strategy to that chart-owned
subscription. Quote handles already have independent ownership. Fixed-range
downloads release the Market operation lock so cancellation remains responsive.
Legacy lookback loads/reconnect still serialize operations; future broker controls
need an independent responsive path. Add order/fill/position reconciliation
separately from data-only reconnect. No order placement/control API exists yet.

The full rationale and the revised research → equity backtest → paper trading
order are recorded in PROJECT_PLAN.md. Later monitoring/options and chart-workspace
features follow concrete workflow needs. No wholesale rewrite is proposed.

## Session and recovery follow-up

`Market.bars(..., include_sessions=True)` additionally requests regular and extended
IBKR `SCHEDULE` data; the Python default is False. The chart CLI opts in, while
`Market.serve(..., include_sessions=True)` enables it by default for the initial
series and subsequent selections. `BarSeries.include_sessions` retains the choice
through history loads, recovery and periodic refreshes. Setting it False skips all
those schedule requests without disabling OHLCV recovery. `plot()` performs no
provider calls; request enrichment before exporting a shaded snapshot.
`BarSeries.sessions` contains normalized UTC start/end seconds, ISO reference date
and a `regular` boolean; snapshots embed this metadata. Intraday charts shade
non-regular windows and draw New York day separators across both panes. Schedules
include actual early closes; no local holiday calendar or standard-hours fallback
is invented. Schedule failures are separate from OHLCV errors. Older intraday
pages extend session metadata; daily/coarser charts request only a recent schedule.
For enriched live series, the recovery supervisor refreshes recent session metadata every five minutes,
including across New York midnight; it does not wait for the UTC date to change.

The browser shows receipt times and missing-callback context, while keeping
entitlements explicitly unverified. The countdown uses New York clock-aligned
intraday boundaries and session closes; daily/coarser charts have no countdown.
Real IBKR AAPL checks confirmed 1h starts 09:30/10:00/11:00, 2h starts
09:30/10:00/12:00, and 4h starts 09:30/12:00. Opening candles must not use a naive
start-plus-interval countdown.

`Market.ibkr()` starts a data-only recovery supervisor by default. It checks active
subscriptions, retries with a 1–30 second bounded backoff, reconnects the same
configured client and backfills from the last candle using fresh history. The
provider rebinds live callbacks to the original `BarSeries` under its history lock;
older downloaded candles and yearly source months survive. Series identity,
selection IDs and chart viewports stay intact. Public requests/cancellation and
recovery are serialized. `Market.cancel(series)` removes recovery eligibility;
closing stops the supervisor. `--no-reconnect` / `reconnect=False` opt out.
Initial connection failures still raise. IBKR 1102 (data maintained) restores
subscription status; 1101 (data lost) requires restoration. Unknown feed types
remain unverified; historical bars do not provide a reliable delayed/live type.

New checks: `tests/test_sessions.py`, `tests/test_reconnect.py`,
`tests/browser_sessions_check.py` and the explicit `tests/live_recovery_check.py`.
Provider-independent tests were moved into `tests/test_core.py` and
`tests/test_cache_core.py` so those local checks can run without importing the SDK. The full
suite still requires the official SDK and optional Parquet for all cache tests.
`tests/wheel_smoke.py` runs with `python -I` against a wheel installed into a fresh
SDK-free environment before installing optional dependencies.

The added GitHub Actions workflow was removed following the user's scope decision.
There is no pending SDK-source decision or CI work. Local clean-environment checks
remain useful for package integrity; they do not change the IBKR runtime setup or
make standalone visualization the product goal.

## Research exports follow-up

`BarSeries.to_records()` copies an ordered, deduplicated snapshot into native Python
OHLCV dictionaries. `to_csv(path)` writes the same schema with ISO UTC/date values,
creates parent directories and atomically replaces the destination. Neither needs
optional dependencies. `to_dataframe()` lazily imports optional pandas (`.[pandas]`)
and returns float64 OHLCV columns indexed by UTC datetimes or date-only identities.
No export calls the provider or requires an open Market; exported values are
independent of subsequent live updates. Partial latest bars remain partial.

Schema: timestamp, open, high, low, close, volume. `metadata()` now supplies a
separate JSON-compatible identity/query/download report to save alongside CSV.
Explicit ranges are implemented; dataset reload and gap/finality auditing remain
future work. Research usage is shown
in `examples/research_exports.py`; tests are in `tests/test_exports.py` and the
explicit data-only TWS `tests/live_exports_check.py`. Install pandas to run all
DataFrame checks; base package imports and CSV exports stay dependency-free.

## Fixed-range research follow-up

`Market.bars(start=..., end=...)` uses explicit start-inclusive/end-exclusive bar
identity bounds, mutually exclusive with duration/live. Intraday dates mean NY
midnight; aware whole-second datetimes normalize to UTC. Daily/coarser bounds are
dates; weekly/yearly eligibility uses Monday/January-1 anchors. Reject future ends.
The provider resolves the instrument once and walks fixed backward windows,
continuing across empty pages, trimming to each window and retaining source months
for annual candles. Exact page queries reuse the existing cache.

`HistoryPacer` wraps actual history/schedule requests: 0.25s soft spacing, plus 11s
small-bar spacing and 15.1s identical small-request spacing. Cache hits bypass it;
state survives reconnect; `close()` interrupts waits. It tracks this connection,
not unrelated clients. Large 30s downloads can be slow. `HistoricalRangeError`
contains completed partial pages and remaining bounds. Success means planned
requests completed, not proof of gap-free market coverage. `metadata()` explicitly
labels gaps/finality unverified, includes empty windows and cached-page counts,
and records instrument/session/adjustment identity without exposing IBKR objects.

Range download uses one captured provider generation without holding the Market
control lock throughout. Cancellation of other subscriptions remains responsive;
a disconnect raises with partial data rather than silently changing connections.
Fixed ranges cannot use `load_older`; the chart disables pagination for them.
Legacy lookback semantics remain intact. The Python research example
`examples/research_range.py` saves inputs/metadata and simple returns/SMA signals,
with no chart/pandas dependency and no simulated fills/profit claims.

New tests: `test_ranges.py`, `test_pacing.py`, `test_research.py`, plus explicit
`live_ranges_check.py`. After the user started TWS on 127.0.0.1:7497, the live
range check passed on 2026-10-16. It verified intraday/calendar/30s bounds, page
cache reuse, yearly OHLCV consistency and exported identity/query metadata.
The research example also exported 250 AAPL daily bars for 2025 and matching
signals/metadata. These checks do not prove gap-free coverage or bar finality.

## Frozen research datasets (2026-10-16)

`BarDataset.from_series(series)` captures bars plus copied metadata under the
series lock. `save(path)` atomically writes one versioned JSON document with a
SHA-256 integrity digest. `BarDataset.load(path)` requires no broker or optional
runtime dependencies. It validates integrity, timestamp kinds/order, coverage
counts and fixed-range bounds. It preserves original receipt time, instrument
identity, query/download status and session information; live updates cannot
change the frozen object. This is a research snapshot, separate from the provider
page cache. The checksum detects accidental edits, not authenticity.

`dataset.audit(expected_starts, finalized_through=...)` compares to a caller's
calendar for the exact query/hours. Missing/unexpected starts are explicit.
Without caller-confirmed finality all observed bars remain unconfirmed. Do not
infer weekdays/holidays or certify finality merely from a successful download.
The original metadata stays unverified; the audit is a separate result. There is
no bundled exchange-calendar generator yet.

`examples/research_range.py` now also writes bars.dataset.json.
`examples/research_saved.py` loads it offline and computes research values;
optional --calendar (one ISO timestamp per line) rejects mismatches before
analysis. Explicitly incomplete downloads are rejected. Calendar/finality inputs
are user assertions, not facts derived from the dataset.

## First daily equity backtest (2026-10-16)

`pyibquant.backtest.backtest_equity(dataset, signals, finalized_through=..., ...)`
accepts a frozen complete fixed-range daily regular-hours equity TRADES dataset,
with split-only adjustment and multiplier one. Boolean long/flat targets computed
after the close act at the next supplied open. Fixed whole-share sizing, adverse
slippage and flat per-fill commission are configurable; no borrowing/shorting.
Insufficient cash produces explicit rejections. Final positions stay marked to
the last close, with no forced exit or future execution of the last signal.
The caller must assert all bars are final; optional expected_dates must match
exactly. Without that calendar, gap coverage remains explicitly unchecked.

The result is frozen and includes fill/trade/rejection logs, daily equity/returns/
drawdown, realized/unrealized P&L, costs, optional expected calendar and the exact
input fingerprint. BarDataset.fingerprint() matches the on-disk SHA-256 digest.
Adjusted-price research units do not reconstruct historical nominal-share fills;
dividends, interest, settlement, taxes, liquidity and account rules are excluded.
There is no order placement or broker-connected strategy loop.

`research.above_sma` and `research.sma_crossover` provide trailing-only signals;
`examples/backtest_equity.py` runs either offline and saves inputs, strategy,
JSON results and CSV logs. Defaults are explicit simulation inputs, not IBKR fees.
The options pilot below now includes snapshots, discovery, quote streams,
recording/replay and the first intraday simulator. Live-session verification
remains the next integration step.
Optional result charts and paper execution controls remain planned.

## Level-one quote snapshots (2026-10-16)

`Market.quote(symbol_or_Option, market_data_type="live")` resolves one US stock or
explicit equity/ETF option contract and calls reqMktData with snapshot=True and
regulatorySnapshot=False. It waits for tickSnapshotEnd, returns a frozen Quote,
and never uses bar history, requests orders, or purchases regulatory snapshots.
Snapshot completion normally takes about 11 seconds; default timeout is 30.

Bid/ask/last, sizes, conId/local symbol/trading class/actual multiplier, requested
and reported feed type, delayed tick IDs and local callback receipt times are
preserved. Receipt timestamps do not establish exchange quote age. Missing or
nonpositive/unset prices are None, zero sizes stay zero. Crossed pairs remain
visible with no midpoint/spread. Delayed tick flags override any assumption of
live data. Available bid/ask/last/model IV/Greeks are separate; missing model
values are never manufactured. Partial permission messages are warnings; terminal
errors/timeouts fail and clean up the quote request. Snapshot lifetimes serialize
because reqMarketDataType is connection-wide, without holding Market's control
lock. Disconnects fail rather than silently reissue snapshots.

`Option(symbol, expiry_date, strike, "C"/"P", trading_class="", multiplier=None)`
resolves exactly one contract via SMART/USD. No multiplier is assumed. There is
no future/index-option coverage; grouped discovery is now implemented below. `examples/quote_snapshot.py`
prints or saves JSON after disconnecting; `tests/live_quotes_check.py` checks the
real data-only callback path. Stock verification passed. The user selected SPY,
2026-11-20, 770, C. Contract resolution passed: conId 882135148, trading class
SPY, local symbol SPY   261120C00770000, multiplier 100. The snapshot ended with
no bid/ask/Greeks and zero sizes; TWS returned 10091 naming SPY ARCA/TOP/ALL
(additional API market-data permissions). Feed type callback was live; that does
not establish field availability. The user instead chose AAPL 2026-11-20 340 C.
That contract resolved to conId 845042071, trading class AAPL, multiplier 100.
Its live request returned no prices during the overnight check (~01:11 EDT).
An explicitly requested frozen snapshot then passed: bid 12.65, ask 12.95,
sizes 891/125 and model IV/delta/gamma/vega/theta. Reported feed type was frozen.
In-session live option BBO/Greeks remain unverified; the SPY permission message
is not evidence that the AAPL snapshot needs a new subscription. Do not buy
subscriptions, change account settings or relabel frozen quotes as live.
Continuous subscriptions, grouped discovery and sampled recording/replay now work
as described below. Chart bid/ask display and historical option imports remain
planned. See README for exact limits and IBKR source links.

## Option discovery, streaming and sampled recordings (2026-10-16)

`Market.option_chain(symbol)` resolves a US stock/ETF and uses reqSecDefOptParams,
not a broad incomplete-option reqContractDetails query. Results retain exchange,
trading class and multiplier groups with sorted/deduplicated expiry/strike sets.
`chain.select(expiry, strike, right, trading_class=..., multiplier=...)` selects
one SMART candidate group; it does not certify the expiry/strike/right combination.
Quote APIs resolve that candidate exactly. Discovery never subscribes to all options.

`Market.stream_quote()` uses snapshot=False, regulatorySnapshot=False. The returned
QuoteStream owns one provider-generation request. `latest()` copies immutable
fields/status/feed provenance; wait_for_update(after_sequence, timeout=...) lets
independent consumers keep cursors without stealing updates. Intermediate
callbacks can coalesce; this is not a tick queue. Quote observations now include
streaming, sequence, observed_at, status and error. Active means callbacks arrived,
not that fields are complete/tradable. Closing cancels only that request; chart
bar cancellation does not own it. Market.close closes all of its subscriptions.

All active streams on a connection must request the same feed mode; mismatched
snapshot/stream modes fail before changing the global requested type. Separate
connections can use different modes. Terminal permissions/disconnects wake waiters
and retain their first terminal cause through later cleanup. There is no automatic
quote reconnect: old handles stay terminal while bar recovery can reconnect.

`record_quotes(stream, path, duration=..., interval=...)` samples on the calling
thread, including unchanged accumulated observations and their original receipt
times. Files are exclusive unless overwrite=True. JSONL header/samples/end footer
preserve contract identity, requested/reported mode, sampling cadence, status,
counts and SHA-256 integrity. complete means the recorder timer finished, not
market coverage, field availability, freshness or executable BBO. These are sampled
local observations, not an exchange tick archive. File IO/user code never runs on
the IBKR reader thread. The caller still owns and closes the stream.

`QuoteRecording.load()` requires no SDK/pandas/PyArrow. `.samples()` returns copied
JSON records. `.quality()` reports availability, crossed/delayed/frozen/unknown
samples, model IV/delta and distinct observed versions; exchange quote age and
execution suitability remain unverified. Missing footer, terminal streams and
truncated trailing data require allow_incomplete=True; checksum failures always
raise. Replay currently loads the recording in memory. Automatic resume, file
rotation and a bounded-memory large-file reader remain planned.

`examples/options_research.py` discovers alone or records one selected contract
into a new timestamped directory with chain.json and quotes.jsonl. Data is ignored
under charts/. The live check uses only the already selected AAPL 2026-11-20 340 C
in explicit frozen mode and cancels it after six seconds. The user chose newly
collected recordings for the first options backtest. Do not assume IBKR reconstructs
expired-option quote histories.

## First options simulation from collected recordings

The user chose our collected recordings rather than an external historical data
import. `pyibquant.option_backtest.backtest_option()` uses standard-library code;
no third-party backtesting package, SDK or chart runtime is involved.
`hold_window()` and `spread_targets()` provide causal demonstration targets.
Custom targets must contain one boolean per observation and avoid future data.

Scope: one resolved option, fixed whole-contract long/flat, one New York date
strictly before expiry. Input must be complete; frozen/delayed, terminal states,
nonincreasing timestamps, future receipt times and excessive sample gaps fail.
Initial unknown-feed rows are ineligible; confirmed live observations are required.
A signal acts after its observation, fills only at a later sample after latency
and a newer side-price receipt, and stays pending across unchanged targets.
Changed targets replace/cancel after the current observation is processed.
Buys use ask plus slippage and sells bid minus slippage. The recorded multiplier,
cash and displayed side size determine whole fills; fees are per contract per fill.
Both prices and both size receipt clocks must satisfy local age/skew limits.
Missing/stale/crossed/undersized quotes skip execution instead of manufacturing fills.

Open positions remain marked at a qualifying bid, without forced final sale or
estimated exit fees. Missing valuation stays None; period returns across it and
full-path drawdown are unknown. A recovered final mark can restore final return
without certifying the intervening path. No shorts, borrowing, partial fills,
queue priority, market impact, book reservation, exercise, assignment, expiry payoff,
overnight carry, settlement, interest or taxes. Local receipt age is not exchange
quote age, and displayed size is not proof of executable liquidity.

`QuoteRecording.fingerprint()` hashes canonical header/samples/footer, including
completion state. It identifies inputs, while the footer checksum verifies original
header/sample bytes; neither authenticates a source. Result JSON retains metadata,
exact targets, configuration, warnings, fills/trades/skips and equity/metrics.
`examples/backtest_option.py` reads the input bytes once, validates that snapshot,
then exports exact inputs, strategy settings, results and CSV logs. It rejects
invalid/frozen input before creating results. Default output is ignored
charts/option-backtest/; use a separate --output-dir to keep multiple runs.

Next: during the option's trading session, run the existing recorder with
--market-data-type live on the user-selected AAPL 2026-11-20 340 C, then the offline
example. See README commands. A real live-session recording is still needed to
validate the complete capture-to-simulation pipeline; the existing frozen sample
is deliberately refused. No permission/subscription/account changes are implied.

## What exists

| File | Responsibility |
|---|---|
| `src/pyibquant/market.py` | Public connection, bar query and chart-serving API |
| `src/pyibquant/data/providers/ibkr.py` | Official SDK callbacks, contracts, requests, normalization, cancellation |
| `src/pyibquant/data/cache.py` | Optional exact-query Parquet cache, expiry, inspection and clearing |
| `src/pyibquant/bars.py` | Immutable Bar values and mutable thread-protected BarSeries snapshots |
| `src/pyibquant/options.py` | Grouped option-chain metadata and explicit SMART candidate selection |
| `src/pyibquant/quote_stream.py` | Subscription ownership and independent consumer update cursors |
| `src/pyibquant/quote_recording.py` | Sampled JSONL recording, integrity/partial checks, quality reports and offline replay |
| `examples/options_research.py` | Discovery and selected-contract recording workflow |
| `src/pyibquant/option_backtest.py` | SDK-free intraday recorded-option simulation and results |
| `examples/backtest_option.py` | Offline simulation, exact input preservation and JSON/CSV exports |
| `tests/test_option_backtest.py` | Hand-calculated accounting, quote timing, quality limits and example exports |
| `tests/live_options_research_check.py` | Explicit TWS chain → stream → recording → offline replay integration check |
| `src/pyibquant/quotes.py` | SDK-free option selectors, quote/Greek values and callback normalization |
| `examples/quote_snapshot.py` | Stock/explicit-option snapshot inspection and JSON export |
| `tests/test_quotes.py` | Quote SDK callback, entitlement, cleanup and control responsiveness tests |
| `tests/test_quote_core.py` | SDK-free quote normalization, immutability and example checks |
| `tests/live_quotes_check.py` | Explicit standard quote snapshot integration check |
| `src/pyibquant/backtest.py` | Daily equity simulation, timing/cost assumptions and frozen results |
| `examples/backtest_equity.py` | Offline above-SMA/crossover runs with reproducible inputs and JSON/CSV results |
| `tests/test_backtest.py` | Hand-calculated accounting, cash rejection, finality/calendar checks and prefix causality |
| `src/pyibquant/dataset.py` | Frozen research datasets, atomic save/reload and explicit calendar/finality comparison |
| `examples/research_saved.py` | Offline analysis of a frozen dataset without IBKR/pandas/Parquet |
| `tests/test_dataset.py` | Roundtrip, corruption, immutability, calendar/finality and offline example regressions |
| `src/pyibquant/visualization/chart.py` | HTML export, localhost HTTP server, active chart session |
| `src/pyibquant/visualization/chart.html` | Page layout, form, styles and template placeholders |
| `src/pyibquant/visualization/chart.js` | Independent Canvas rendering, interactions and browser requests |
| `src/pyibquant/cli.py` | `pyibquant chart` command |
| `tests/test_market_data.py` | Offline SDK callbacks, contracts, normalization and intervals |
| `tests/test_core.py` | SDK-free bars, HTML export, chart sessions and CLI tests |
| `tests/test_exports.py` | Snapshot records/CSV/pandas exports and optional dependency behavior |
| `tests/live_exports_check.py` | Explicit TWS request/enrichment and export integration check |
| `examples/research_exports.py` | Headless IBKR-to-records/CSV research example |
| `tests/test_cache_core.py` | SDK-free Parquet cache and cache CLI tests |
| `tests/browser_chart_check.py` | Offline Chrome regression using generated synthetic data |
| `tests/browser_controls_check.py` | Explicit manual TWS/browser integration check |
| `tests/test_history.py` | Offline history merge, provider paging and session tests |
| `tests/browser_history_check.py` | Synthetic browser pagination, delayed responses and retry checks |
| `tests/browser_live_history_check.py` | Real TWS pagination and viewport integration check |
| `tests/test_cache.py` | Cache persistence, expiry, corruption, refresh, live bypass and concurrency |
| `tests/browser_cache_check.py` | Real TWS/browser daily/yearly cache reuse check |
| `tests/browser_hours_check.py` | Real TWS regular/extended-hours switching and older-history check |

No npm build or third-party chart library is required. JS is packaged with Python
and embedded into exported HTML. The sibling QuantIBKR repository supplied examples
but is not needed to install or run PyIBQuant.

HTTP API: `GET /` serves the page; `GET /data` returns the active series;
`POST /chart` accepts JSON `symbol`, `interval`, `duration`, and optional boolean
`regular_hours` (omitting it retains the active setting). Selection is serialized;
success replaces the series and cancels the old subscription, failure preserves
it. One server has one shared active chart, including across browser tabs.
`POST /older` accepts the current `selection_id` and earliest bar `before` time.
It shares the selection lock, rejects stale selections, reuses another tab's
already loaded boundary and throttles history requests to at most one per two
seconds. `/data` and the initial page carry the selection ID, so selecting the
same symbol/interval with another duration also resets clients correctly.

The browser polls every two seconds. Epoch seconds represent UTC intraday bars;
daily bars retain ISO session dates. Intraday labels use America/New_York
(EST/EDT automatically);
date-only labels remain unchanged. Canvas x coordinates use bar indices, omitting
closed-market gaps. Prices autoscale from visible candles by default. Manual
price ranges survive incoming bars, time navigation and resizing. Price and volume
are clipped separately; volume always keeps its own automatic scale.
The viewport count includes blank bar slots. Right space defaults to 10% of plot
width (selectable 0–40%). Fit includes all bars plus that space; Latest anchors
the data edge at the chosen margin. Fitted views expand on appends, following
views keep their zoom, and panned views keep their bar-index coordinates. A
time-axis drag zooms around the data edge when following, or around the right
viewport edge when panned. Double-clicking an axis resets only that axis.
Prepending anchors the old first timestamp at its new index, shifts `left` by
the inserted count and keeps candle spacing and tick-grid origin stable. Normal
append/follow behavior remains unchanged. History loading pauses polling, bumps
the browser generation counter to reject older in-flight polls, and leaves
Canvas navigation available. Errors require explicit retry; empty/no-progress
pages stop further loading for the current selection.

Supported intervals now include `2h`, `4h`, `1w` and `1y`. Yearly candles are
aggregated inside the IBKR provider from native monthly callbacks, grouped by
calendar year. A monthly replacement recomputes that year's OHLCV, so repeated
updates never add volume twice and corrected extrema can shrink. Annual date
anchors are January 1, with year-only axis labels. The chart warns that boundary
years can be partial. Weekly/yearly requests fetch enough extra source history
to cover the first requested calendar bucket and filter out unrequested earlier
periods. Weekly anchors are Mondays and source-month anchors are the first day
of each month, so clipped IBKR period-end dates cannot create duplicate periods.
Older pages use a fixed bounded duration per interval rather than the initial
query duration. Daily/coarser end boundaries use New York midnight converted to
UTC, including DST. The original live subscription is retained; overlapping
older downloads never replace live candles. Yearly source months are retained
in a provider-owned weak-key map and merged under a lock before recomputing the
affected years, including any previously partial earliest year.

Caching is off unless a cache directory is configured. Install `.[cache]` and
use `--cache` (default `~/.cache/pyibquant/`) or `--cache-dir`; `--no-cache` disables
it. The current preview uses ignored `charts/cache/`. Parquet is imported only
when a cache is instantiated; the base package still has no runtime dependencies.
The provider resolves contracts before looking up exact query keys, including
conId, native bar size, effective source window, hours, exchange, currency,
TRADES and normalization version. Calendar normalization version 2 prevents
reuse of entries made before period identities and aligned requests were fixed.
Fixed-end entries default to 24-hour expiry; relative snapshots are capped at
five minutes. Live subscriptions never read/write cached initialization or updates.
Older pages may hit cache, including normalized monthly inputs for yearly charts.
Cache hits are labeled; errors fall back to IBKR with warnings. Empty results
and errors are never persisted. Writes use temporary files and atomic replace.
`pyibquant cache inspect/clear` needs no IBKR connection and operates only on
namespaced cache entries. Per-request `refresh=True` or connection/CLI
`refresh_cache=True`/`--refresh-cache` bypasses reads and updates entries.

## Set up on the other machine

Clone/pull the committed work, enter the repository, and create a new environment.
Do not copy `.venv` from the original machine.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,browser,cache]'
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.
Python 3.11+ is declared. Original local checks used Python 3.11.6 on macOS;
the price/time-scaling follow-up used Python 3.14.5 on macOS. Other operating
systems have not yet been validated.

Install TWS/IB Gateway and the official TWS API Python client 10.33+ separately,
following the SDK's installation/license instructions. The project's dependency
list deliberately does not install the old PyPI `ibapi` distribution.

```sh
python -m pip install "/path/to/TWS API/source/pythonclient"
python -c 'from ibapi import get_version_string; print(get_version_string())'
python -m pytest -q
ruff check src tests examples
mypy
```

Local validation used SDK 10.50.2. The original environment reused that existing
SDK using `--system-site-packages`; a fresh machine must install its own SDK.

For manual browser checks, install Google Chrome; Playwright launches the `chrome`
channel. The offline check needs neither an account nor a local market-data file:

```sh
python tests/browser_chart_check.py
python tests/browser_history_check.py
```

For live use, log into TWS, enable socket clients, allow localhost, keep Read-Only
API enabled, and use the matching port and a free client ID (defaults: paper TWS
7497, client ID 71). See README for the port table and subscription requirements.

```sh
pyibquant chart AAPL --live --web-port 8050
```

Open the printed URL (`http://127.0.0.1:8050/` for the command above), rather than a
saved HTML file, to change symbols/intervals. Keep the Python process running.
Browser controls select symbol, interval, history and trading hours. Regular hours
is the default; `--extended-hours` chooses the initial setting. Load chart applies
the selected hours through a fresh data subscription; older pages and cache keys
retain the active setting. Press Ctrl+C to stop.

With that server running, an optional integration check requests SPY 5-minute and
AAPL daily data and leaves the shared chart on AAPL daily:

```sh
python tests/browser_controls_check.py
```

## Validation recorded at this checkpoint

Documentation cleanup (2026-10-16): reconciled README scope/setup, architecture
readiness, roadmap and handoff with the implemented datasets and both simulators.
All 317 local tests, Ruff, mypy and whitespace checks pass. The documented expanded
SDK-free subset passes 187 tests with six pandas checks skipped against the
installed wheel. Local Markdown links resolve, and no generated charts, datasets,
environments or build outputs are tracked. Live-session verification remains pending.

Collected-option simulator follow-up (2026-10-16): 317 local tests, Ruff and mypy
(22 source files) pass. Its 41 tests cover hand-calculated ask/bid accounting,
nonstandard multipliers, costs, pending intents/latency, new receipt timing,
skipped fills, missing/recovered valuation, causality, invalid input and both
offline example strategies with exact inputs and reproducible JSON/CSV exports.
The rebuilt base wheel passes its isolated smoke check without ibapi/pandas/PyArrow;
the installed-wheel SDK-free research/quote/backtest subset passes 167 tests and
skips six pandas checks. The actual saved frozen AAPL recording loads correctly
but is rejected for simulation as intended. No new live prices or performance
claims were verified; the market was closed during this implementation.

Discovery/stream/recording follow-up (2026-10-16): 276 local tests, Ruff and
mypy (21 source files) pass. The bare installed wheel passes its expanded smoke
check without ibapi/pandas/PyArrow, including chain selection, streaming-model
recording and offline replay. The installed-wheel subset without ibapi/pandas
passes 126 tests and skips six pandas checks. TWS check passed with 41 AAPL
chain groups. One selected AAPL 2026-11-20 340 C frozen stream recorded six seconds
at half-second sampling: 12 samples, 10 with bid/ask and confirmed frozen mode,
9 with model IV/delta, 2 initial unknown-feed samples, no crossed pairs. Only one
quote subscription was created, no history requests were sent, cancellation
released its request and the file reloaded after broker disconnect. The quality
report preserves unknown exchange quote age and unverified execution suitability.
Generated artifacts stay under ignored charts/options-research-check/.

Tests cover chain grouping/ambiguity/candidate identity, malformed chain callbacks,
stream cursors/ownership/mode isolation, snapshot coexistence, terminal wakeups and
first-cause retention, initial send cleanup, sampled unchanged receipts, exclusive
files, partial/truncated inputs, integrity/identity/count checks and both discovery/
recording example paths. Quote reconnect, disk rotation and live-session options
verification remain unverified/unimplemented as noted above.

AAPL option follow-up (2026-10-16): 234 tests, Ruff and mypy pass. The real SDK
normalizes unavailable option computations to None, which initially exposed an
unguarded delta comparison. The handler now accepts optional fields and preserves
available Greeks without killing the connection. Its Decimal unset-size sentinel
(2**127-1) is also normalized to None rather than reported as an enormous size.
Regression tests cover both Decimal and float forms, all-missing computations,
mixed available/unavailable model fields and legitimate zero Greek values.
The installed-wheel subset without ibapi/pandas passes 100 tests and skips six
pandas checks. The diagnostic script retains separate files for requested modes.

The user-selected AAPL 2026-11-20 340 C resolved with multiplier 100. Overnight
live mode returned no BBO; frozen mode passed with bid/ask 12.65/12.95, sizes
891/125 and nonmissing model IV, delta, gamma, vega and theta. Feed type callback
confirmed frozen, with no permission warning in that snapshot. Data is last
available, not a verified current or executable quote. No in-session live option
claim is made. Raw diagnostic outputs remain Git-ignored.

Level-one snapshot follow-up (2026-10-16): 231 unit tests, Ruff and mypy
(18 source files) pass. The bare installed wheel passes SDK-free smoke checks;
the installed-wheel subset without ibapi/pandas passes 98 tests, with six pandas
checks skipped. Offline tests cover stock/option resolution, actual multiplier, feed-type transitions and delayed tick IDs,
missing/unset/crossed quotes, separate Greek sources and unavailable sentinels,
timeouts/permissions/disconnect cleanup, Market control responsiveness, immutable
JSON export and standalone examples. The actual AAPL standard snapshot passed on
port 7497/client 193: bid/ask/sizes arrived and IBKR reported live feed type.
The selected SPY option resolved but returned no bid/ask/Greeks with 10091;
that specific empty snapshot/partial-permission combination has a regression test.
Generated quote records are ignored under charts/quote-check/. The later AAPL
frozen check above verifies option BBO/model Greeks; in-session live verification
remains pending.

Daily equity backtest follow-up (2026-10-16): 199 unit tests, Ruff and mypy pass.
Hand-calculated tests cover delayed signal execution, adverse slippage, per-fill
fees, realized/unrealized P&L, equity returns/drawdown, ending positions, rejected
buys/exits and cash preservation. Prefix tests verify trailing-only SMA signals
and that changing future prices/signals cannot change earlier results. Invalid
inputs, incomplete downloads, unconfirmed finality, calendar mismatches and
arithmetic overflow are rejected. Both example strategies are exercised offline.

The base wheel without ibapi/pandas/PyArrow passes the expanded smoke check and
runs both strategies on 250 saved AAPL 2025 daily bars, with 1 share, initial cash
10000, commission 1 per fill and 5 bps adverse slippage. Above-SMA(20) completed
12 trades; SMA crossover(10,20) completed 7. Exact input fingerprints match the
saved dataset. These are integration checks, not strategy recommendations.
The independently supplied 2025 dates match all 250 rows; its explicit holiday
list follows the [NYSE 2025 calendar](https://www.nyse.com/publicdocs/ICE_NYSE_2025_Yearly_Trading_Calendar.pdf)
plus the [Nasdaq January 9 closure notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2025-1).
The generated calendar and outputs remain ignored under charts/. This does not
add or certify an automatic exchange-calendar provider.

Frozen dataset follow-up (2026-10-16): 161 unit tests, Ruff and mypy pass.
Tests cover date/UTC/DST roundtrips, live-update isolation, nested metadata copies,
atomic write failures, altered/malformed documents, unsupported versions,
duplicate timestamps, range/coverage consistency, partial status, caller calendar
mismatches and unconfirmed finality. The real research example saved 250 AAPL
2025 daily bars via local TWS. A freshly installed wheel in an environment without
ibapi/pandas/PyArrow passed the SDK-free smoke test and reloaded those same bars
with matching last return/SMA values through examples/research_saved.py.
Generated datasets remain under ignored charts/research-live-check/.

Fixed-range/research follow-up: 141 local unit tests, Ruff and mypy pass. All three
offline Chrome scripts pass, including fixed-range pagination being disabled and
restored after chart selection changes. Tests cover DST/UTC and date boundaries,
strict/exclusive range filtering, empty-window continuation, partial failures,
page cache reuse without provider/pacing requests, yearly source-month merging,
interruptible pacing and responsive cancellation during a waiting range download.
The installed-wheel subset without SDK/pandas passes 50 tests and skips six pandas
checks; a bare base environment passes package/HTML/CSV/metadata/research/error
imports with no optional runtime dependencies. The synthetic research example
writes correct input/metadata/signal outputs and refuses to analyze a failed
partial download. Live validation initially lacked a TWS listener; the user then
started TWS on port 7497 and the range script passed on 2026-10-16. Results:
502 daily bars / 3 pages, 105 weekly bars / 1 page, 11 yearly bars / 2 pages,
plus 5-minute and 30-second bounds, cache reuse, yearly OHLCV comparison and
exported identity/query metadata. The actual research example exported 250 AAPL
daily bars for 2025; CSV/signals row counts, complete-download metadata and
SMA warmup were checked. Outputs are under ignored charts/research-live-check/.

Research exports/optional-enrichment follow-up: 100 unit tests, Ruff and mypy pass
on Python 3.14.5 with pandas 3.0.6 and the installed official SDK. All three offline
Chrome regressions pass. The separate TWS export check confirms plain queries send
only TRADES historical requests, opt-in enrichment adds regular/extended SCHEDULE
requests, and records/CSV/pandas exports work after disconnect with preserved UTC
and date-only identities. The live recovery integration also passes for enriched
intraday and unenriched yearly series. A base wheel installed without SDK, Parquet
or pandas passes import, HTML/records/CSV export and missing-dependency checks.
The installed-wheel local subset without pandas passes 36 checks and explicitly
skips six DataFrame checks; with pandas installed all export tests run. No remote
CI or account/order requests were added.

Session/recovery follow-up: 75 unit tests, Ruff and mypy pass on Python 3.14.5
with the installed official SDK 10.50.2. All three offline Chrome regressions pass;
synthetic session checks inspect actual canvas shading in both panes, early close
and DST behavior, missing schedules, countdown expiry, stale callbacks and stable
viewports through recovery states. Desktop/mobile screenshots were reviewed.
An isolated environment with no SDK or Parquet installed passes wheel import,
packaged-asset and offline-export checks; after adding pytest/Parquet, all 27
SDK-free tests pass against the installed wheel with source-path injection off.
The real TWS recovery check passes with a separate client: actual regular/extended
schedules, automatic socket recovery, intraday backfill, retained older yearly
source history, and cancellation. No orders/account requests or disruption of the
existing chart server were needed. Other operating systems remain unverified.
CI and automatic SDK installation were removed from the current scope.

Hours/timezone follow-up: 60 offline tests, Ruff, mypy and the offline browser
regression passed. The real IBKR browser hours check returned 156 regular-hours
versus 384 extended-hours AAPL 5-minute bars over the same 2 D window, confirmed
outside-session bars and older-history retention, rejected invalid hours, and
restored the shared preview to regular-hours AAPL daily 6 M. New York labels were
checked across EST/EDT, the spring transition and overnight calendar rollover.

Cache follow-up: 58 offline tests, Ruff and mypy passed on Python 3.14.5 with
PyArrow 26.0.0. Coverage includes date/datetime Parquet roundtrips, exact keys,
expiry/future clocks, corruption/schema failures, atomic/concurrent writes,
scoped clearing, optional imports, refresh, live bypass and monthly source
restoration. Real IBKR checks proved snapshot hits avoid historical requests,
refresh/live initialization still request IBKR, and a fresh connection reuses
older pages. Browser cache checks passed for daily/yearly charts while retaining
manual views and live subscriptions. Cache metadata inspection exposed varying
IBKR month-end labels: calendar normalization/aligned source requests now keep
current YTD values equal for short/long lookbacks and closed-year OHLCV unchanged
through pagination. Weekly buckets likewise keep stable Monday identities.

History-loading follow-up: 26 offline tests, Ruff and mypy passed. The existing
renderer regression and synthetic pagination regression passed, including slow
responses, navigation during downloads, stable price/time coordinates, stale
poll suppression, explicit retry, exhaustion and same-symbol selection resets.
Real TWS/browser history tests passed for AAPL: 1-minute 390 to 2,340 bars, daily
22 to 273, weekly 105 to 366 and yearly 2 to 12. Live subscriptions and manual
time/price views survived each prepend. The existing live symbol/interval/error
integration checks also passed. Counts are local observations, not fixtures.
Run the two live integration scripts sequentially because they share one chart.

Interval follow-up: 15 offline tests, Ruff, mypy, Chrome offline regression and
live browser integration passed. Real AAPL subscriptions returned 2-hour,
4-hour, weekly and aggregated yearly candles. Unit tests cover calendar-year
boundaries, chronological open/close with out-of-order monthly callbacks,
volume replacement, corrected highs/lows and subscription cancellation. Browser
checks cover date/year labels and all four interval selections.

Price/time-scaling follow-up: validated on macOS with Python 3.14.5 and the locally
installed official SDK 10.50.2. All 11 offline tests, Ruff, mypy and the expanded
Chrome regression passed. Browser checks cover dragging both axes, vertical
panning, right-space settings, blank-area crosshairs, native touch axes/pinch,
manual bounds through updates/resizing/navigation, autoscale and selection resets,
pane clipping and empty/flat data. Desktop/mobile screenshots were reviewed.
Live TWS integration also passed: AAPL 1-minute data, subscribed browser polling
with stable manual/time views, SPY 5-minute selection, invalid-history recovery,
and AAPL daily/6-month selection. The integration check leaves the shared chart
on AAPL daily; it verifies subscriptions/polling, not real-time entitlements or
that prices changed during the test.

Original implementation checks:

- 11 offline tests passed; Ruff and mypy passed.
- Wheel build and isolated import/render smoke check passed; HTML/JS assets and
  typing marker are included, with no source-tree or SDK dependency for chart export.
- Chrome offline renderer check passed with no external requests or JS errors:
  zoom, drag, crosshair, keyboard, DPR, resizing, viewport updates, empty/flat bars.
- Real TWS historical requests and live bar subscriptions succeeded.
- Browser selection succeeded for SPY 5-minute and AAPL daily/6-month history.
- Invalid history retained the active chart; the next valid selection recovered.
- Desktop/mobile layouts and touch pinch were checked in Chrome.

The local chart server only runs while its Python process remains active. Launch
it again on a new machine; a localhost URL is not a hosted service.

These are development checks, not proof of production reliability. Recorded bar
counts and chart screenshots are local artifacts, not fixtures or release data.

## Known limits

- Single active series per server; no saved layouts, drawings, indicators or watchlists.
- Delayed/live feed-type confirmation remains unavailable for historical-bar subscriptions.
- Reconnect needs TWS login/API settings and the configured port to remain valid;
  provider history limits can prevent recovery of very long gaps.
- Exact-query cache only; no coverage merging, automatic pruning or disk-size limit.
- Historical bars are US stock/ETF TRADES only, with no delayed-history fallback.
- US stock/ETF quote snapshots, selected streams and grouped option discovery are implemented.
- Default quote handles end on disconnect; opt-in recovery clears fields and records gaps.
- Frozen quote recovery passed against TWS; confirmed-live recovery still needs an open session.
- Sample-count rotation/disk-backed replay are implemented; closed-file resume is not.
- Sampled recordings are not tick archives; `load()` holds rows in memory, while
  `open()` and recording-set replay scan from disk.
- The option simulator is intraday, long/flat and pre-expiry only; exercise/assignment/settlement modeling remains pending. Live capture/replay
  passed, with receipt-age/skew rules restricting fills and valuations.
- Depth, chart bid/ask display and historical option quote imports are not implemented.
- IBKR limits/entitlements apply; fixed ranges page automatically, legacy lookbacks remain single requests.
- Live bars remain in memory without a retention limit; full snapshots are polled/redrawn.
- A selection temporarily creates the replacement subscription before releasing the old one.
- No order execution, account credentials or account identifiers are needed by this slice.
- No cross-platform validation results yet; checks run locally and CI is outside current scope.

## Git transfer

Source, tests, docs and package configuration should travel through Git.
`.venv/`, generated `charts/` HTML/screenshots, caches and build outputs are ignored.
Nothing in `/tmp` is needed. No credentials or downloaded SDK should be added.

The chart-foundations checkpoint includes source, regression checks and progress
documentation. Generated market-data artifacts remain ignored. The local preview
uses client ID 173 and `charts/cache/`, with regular-hours AAPL daily bars over 6 M.
To restart it after closing the current process:

```sh
python -m pyibquant chart AAPL --interval 1d --duration '6 M' --live --web-port 8050 --client-id 173 --cache-dir charts/cache --no-browser
```

The HTTP server and TWS connection are local processes, not part of the commit.
Before moving machines, inspect `git status -sb`, `git log -1` and the configured
remote. Fetch origin and compare `git log origin/main..HEAD` to identify any local
commits that still need pushing. Generated data stays local even after source is pushed.
