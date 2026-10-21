# Development roadmap

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for direction and
[CONTRIBUTING.md](CONTRIBUTING.md) for development checks. This list is not a
promise of future API compatibility or delivery dates.

## Research and backtesting

- [ ] Add worked strategy comparisons with explicit training/holdout periods.
- [ ] Improve performance summaries and experiment comparison tools.
- [ ] Design a general provider contract before broadening Yahoo preview scope.
- [ ] Add supported Python-version CI coverage beyond local verification.

## Paper execution

- [ ] Design custom paper strategy callbacks; current runners expose SMA signals.
- [ ] Extend evidence for natural partial fills and later-date cash release.
- [ ] Expand execution-correction normalization and completed-order coverage.
- [ ] Evaluate automatic broker reconnect with explicit uncertainty handling.
- [ ] Review settlement-calendar coverage before using dates outside its bounds.

## Documentation and release

- [ ] Review public Git history, author identity metadata and GitHub-hosted artifacts.
- [ ] Enable GitHub Pages and manually publish when the public source is approved.
- [ ] Build fresh release artifacts and verify their contents before distribution.
- [ ] Keep examples, parameter definitions and manual checks aligned with the API.
