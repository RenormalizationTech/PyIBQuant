# Project direction

PyIBQuant focuses on on-demand market-data acquisition, reproducible Python
research, backtesting and bounded paper execution. This is design context;
[the API documentation](docs/API.md) describes implemented behavior.

## Research workflow

Acquire only the instruments and ranges needed for an experiment. Freeze source
rows and provenance, inspect quality, compute user-owned signals and preserve the
settings/input fingerprints behind a result. Live recording and a large local
option archive should not be prerequisites for historical research.

IBKR is the primary implemented research provider. Yahoo is an optional daily
preview; its current provenance and adjustment conventions do not satisfy the
strict study/backtest contracts. A future broader provider interface must make
comparability and completeness explicit rather than silently rewriting metadata.

## Simulation and paper workflows

Offline simulation should support causal bar access, transparent execution costs
and reproducible order/fill logs. Strategy decisions must remain separate from
broker transport. Paper execution needs durable identities, conservative funding,
reconciliation, restart handling and explicit ownership-based exits.

Custom strategy callbacks are implemented in the offline simulator. The paper
runners currently support fixed SMA signals; a general paper strategy interface
is future work. Live-money execution is outside current scope.

## Documentation and release direction

Keep user guides task-oriented and generated from `docs/` with MkDocs/GitHub
Pages. Put build, development and publication instructions under `contributing/`.
Public examples use synthetic data or placeholders, not personal account history.

Priorities and implementation gaps are tracked in [TODO.md](TODO.md).
