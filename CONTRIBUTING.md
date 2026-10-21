# Contributing to PyIBQuant

User installation and workflows are in the [documentation](docs/README.md).
This page covers source changes and documentation maintenance.

## Development setup and checks

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check src examples tests
mypy
```

Run checks appropriate to the change. The normal pytest suite does not connect to
a broker or send orders. Optional provider dependencies may enable more tests.
The official IBKR SDK is installed separately; the base package must remain
importable without it.

The `tests/live_*.py` and `tests/browser_*.py` programs are manually invoked
integration harnesses. Read their source and `--help` before running; some live
checks intentionally send bounded paper orders. Do not run them as part of a
generic CI job or documentation build. Keep observation, paper execution and
synthetic fills clearly separated.

## Source layout

- `src/pyibquant/`: public containers, market entry point and research APIs
- `src/pyibquant/data/`: historical requests, optional providers and cache
- `src/pyibquant/trading/`: paper adapters, funding, journals and runner lifecycle
- `src/pyibquant/visualization/`: optional read-only chart viewer
- `examples/`: standalone programs with CLI arguments
- `tests/`: offline unit/regression tests and explicit integration harnesses
- `docs/`: user-facing website source
- `contributing/`: documentation authoring and publishing instructions

See [HANDOFF.md](HANDOFF.md) for implementation boundaries,
[PROJECT_PLAN.md](PROJECT_PLAN.md) for design direction and [TODO.md](TODO.md) for
remaining work. These files describe the project, not a particular account/session.

## Documentation

Use the [authoring and GitHub Pages guide](contributing/DOCUMENTATION.md).
Keep developer infrastructure, private session notes and publication reviews out
of the user website. Examples should state prerequisites, units, saved artifacts
and expected behavior; use synthetic data for deterministic assertions.

```sh
python -m pip install -e '.[docs]'
python -m mkdocs serve
python -m mkdocs build --strict
```

## Packaging

```sh
python tests/build_check.py
```

This builds from a curated temporary copy, inspects the source archive/wheel,
installs the wheel in an isolated SDK-free environment and runs smoke checks.
Outputs go under ignored `dist/`. Build fresh artifacts for each release; do not
publish old local archives, which may contain superseded documentation.

## Public source hygiene

Do not commit credentials, real account numbers, account journals/reports,
personal session P&L, actual recovery IDs or machine-specific paths. Use
placeholders for public examples and keep account-specific profiles in `charts/`.
Local integration evidence is not a substitute for reproducible tests.

Before a public release, inspect the prospective tracked files, Git history,
commit metadata, release attachments and CI artifacts. `.gitignore` does not
remove content already committed or included in previously built archives.
