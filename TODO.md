# PyIBQuant visualization roadmap

Last reconciled: 2026-10-15. Checkboxes describe implemented behavior, not a release promise.
The full project direction remains in [PROJECT_PLAN.md](PROJECT_PLAN.md).
For machine setup and where to resume, see [HANDOFF.md](HANDOFF.md).

## Goal and scope

Build an independently designed charting workspace that can replace TradingView
for frequent use by IBKR US stock/ETF retail traders, while supporting Python
quantitative research. Own the renderer and interaction design; do not reintroduce
TradingView's chart libraries. Options visualization follows the equity foundation.

This extends the original v0.1 market-data/chart slice. The complete list is not
required before the next useful release. Broker execution remains on the separate
paper-trading roadmap; displaying trade context does not authorize order placement.

## Completed prototype

- [x] Official IBKR API adapter, configurable host/port/client ID, readiness and request timeouts
- [x] US stock/ETF contract resolution and historical OHLCV bars
- [x] UTC intraday timestamps and date-only daily bars
- [x] Live historical-bar updates; repeated timestamps replace the current candle
- [x] Independent Canvas candlesticks, synchronized volume, axes and crosshair OHLCV
- [x] Wheel zoom, horizontal drag, touch pinch, keyboard navigation and high-DPI resizing
- [x] Fit data and Latest controls; preserve a panned view during updates
- [x] Browser symbol, interval and history selection with Load chart/Enter
- [x] Loading/errors, retain prior chart on failure, cancel prior subscription on success
- [x] Self-contained offline HTML snapshots and localhost live chart server
- [x] Offline provider/session tests and separate browser/integration checks

## Next milestone: complete chart foundations

Start with the first three items as one small implementation slice.

- [ ] Drag the price axis to scale vertically
- [ ] Vertical pan with explicit manual/automatic price-scale modes
- [ ] Autoscale toggle and reset; preserve manual scaling through live updates
- [ ] Drag the time axis to adjust candle spacing
- [ ] Configurable space to the right of the latest candle
- [ ] Load older historical bars when panning left; deduplicate and preserve viewport
- [ ] Local historical cache to reduce repeat requests (optional Parquet; no database server)
- [ ] New York/UTC timezone selection with daylight-saving-aware labels
- [ ] Browser regular/extended-hours toggle, session shading and separators
- [ ] Improve date ticks across sessions; candle-close countdown
- [ ] Distinguish connected/subscribed, stale, delayed and live states without guessing entitlements
- [ ] Display last data-update time and actionable connection errors
- [ ] Reconnect, restore subscriptions and backfill gaps

Acceptance: scaling, panning, interval changes, history loads and live updates do
not unexpectedly move the trader's view. Price/time coordinates stay consistent
across both panes. Add browser regressions for those behaviors.

## Everyday workspace

- [ ] Symbol/company search with exchange, currency and instrument identification
- [ ] Saved watchlists with sorting and last/change/volume/bid/ask/spread
- [ ] Premarket/after-hours quote context
- [ ] Favorite intervals and quick date ranges
- [ ] Save/restore preferences and named workspaces across restarts
- [ ] Fullscreen, context menus and consistent keyboard shortcuts
- [ ] Appearance settings; line and OHLC bar styles
- [ ] PNG and CSV exports

## Analysis tools

- [ ] Horizontal/vertical lines, trend lines, rectangles, text and measurements
- [ ] Drawing handles, candle snapping, lock/hide/delete and undo/redo
- [ ] Persist drawings by symbol using timestamp/price anchors, with timeframe visibility
- [ ] Drawing templates and object management
- [ ] SMA, EMA, VWAP and Bollinger Bands overlays
- [ ] RSI and MACD in separate resizable panes
- [ ] Indicator parameters, styles, templates and custom Python calculations
- [ ] Multiple resizable charts with optional symbol/time-range/crosshair synchronization
- [ ] Comparison symbols, percentage/indexed and logarithmic scales

## Monitoring and research

- [ ] Price/indicator alerts with crossing and bar-close semantics
- [ ] Python-side alert evaluation, expiration, history, sound and notifications
- [ ] Earnings/dividend/split markers; explicit data-provider requirements
- [ ] Explicit corporate-action adjustment settings and consistent indicator inputs
- [ ] Historical replay with stepping and speed control
- [ ] Research annotations, signal markers and backtest entry/exit overlays
- [ ] Backtest performance views
- [ ] Positions, average entry, orders and fills displayed on charts
- [ ] Later: option chain tables, IV smiles/skew, term structure and surfaces

## Quality and release work

- [ ] CI with an explicit official-SDK installation/testing strategy
- [ ] Verify clean installation and wheel assets on another machine
- [ ] Expand renderer tests for large datasets and lengthy live sessions
- [ ] Test data gaps, market holidays, DST, corporate actions and indicator correctness
- [ ] Persistence recovery tests once saved workspaces exist
- [ ] Bound live in-memory history and avoid sorting/repainting all bars on every poll
- [ ] Decide release metadata, supported Python/OS matrix and dependency constraints

Daily-use acceptance: prepare a watchlist, analyze multiple timeframes, mark levels,
monitor a session, and reopen the next day with the work intact.
