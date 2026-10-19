# Development changes

## 0.1.0.dev1

Local development snapshot; no published release is implied.

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
  no new mandatory dependencies or broker order-placement APIs.
- Document supported APIs, differing finality conventions and local build checks.
  Source distributions include examples, guides and validation scripts, excluding
  generated datasets and virtual environments.

Initial scope remains USD/US equity and selected-option research. Simulation uses
explicit synthetic execution assumptions; no shorting, margin, multi-leg/lifecycle
accounting or daily/intraday clock mixing. Scientific helpers do not certify data,
infer missing prices or establish multifractality. See README and docs/API.md.
