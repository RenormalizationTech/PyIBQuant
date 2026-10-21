# Developer handoff

User workflows: [docs/README.md](docs/README.md).
Development checks and packaging: [CONTRIBUTING.md](CONTRIBUTING.md).

## Architecture and contracts

`Market.ibkr()` owns a data-only provider connection. Optional SDK imports stay
lazy. `BarSeries` is mutable and supports live updates; `BarDataset` and
`BarDatasetCollection` freeze rows with provenance and integrity digests for
offline use. Fixed historical ranges use inclusive start/exclusive end bounds,
sequential paging and explicit partial-download failures.

Research functions and simulators consume frozen inputs without broker calls.
The general simulator supplies completed-bar histories to `Strategy.on_bar()` and
executes market orders at eligible supplied opens. USD cash, whole quantities,
long-only positions and explicit cost models define its current scope.

`PaperBroker` owns a separate paper-only connection and durable SQLite journal.
The broker defaults to read-only. Unknown sends, missing execution evidence and
funding/ownership conflicts require explicit reconciliation. The funding ledger
uses versioned bounded settlement policies; existing journals retain their policy.

`EquityRunner` and `OptionRunner` drive bounded above/below-SMA strategies from
live one-minute underlying bars. Process restore is paused and retains identity,
order budgets and limits. Later-date resume requires explicit session handling.
They do not currently accept arbitrary user strategy callbacks.

## Preserve these boundaries

- Never turn unavailable prices, balances, fees or P&L into confirmed zeroes.
- Keep observed receipt times distinct from exchange times and bar finality.
- Do not treat completed request windows as a verified exchange calendar.
- Preserve exact contract identity, option multiplier and price source.
- Keep order submission, terminal evidence, cancellation and attribution separate.
- Never reuse a failed/uncertain send as a reason to create a replacement order.
- Keep private integration journals and recovery evidence outside source archives.

## Validation and outstanding work

Use the offline tests, lint/type checks, strict docs build and isolated wheel
smoke checks described in CONTRIBUTING.md. Integration results depend on the
operator's account, entitlements, SDK and broker session; no personal session log
is part of the public handoff. See [TODO.md](TODO.md) for remaining work.
