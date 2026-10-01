# env-drift

Detect cross-environment configuration drift — when `.env.development`, `.env.staging`, and `.env.production` diverge in unexpected ways.

## Problem

Modern applications maintain multiple environment files (`.env.development`, `.env.staging`, `.env.production`). Common failure modes:

- **Missing keys** in production that exist in development (causes `undefined` values in prod)
- **Divergent secrets** where staging and production should share the same keys (database URLs, API endpoints)
- **Inconsistent values** where the same key has different formats across environments
- **Orphaned keys** that exist in prod but no longer in any other environment (dead config, security risk)

Existing tools validate *individual* files (`dotenv-linter`, `dotenv-validator`) but do **not** compare across environments. This leaves drift undetected until a deploy breaks.

## Solution

`env-drift` scans a project for `.env` / `.env.*` files, resolves variable references, and compares every environment against every other:

| Check | Drift type | Severity | What it catches |
|-------|-----------|----------|-----------------|
| Missing keys | `missing_key_in_env` | warning (error if required) | Key in `.env.development` and `.env.staging` but not in `.env.production` |
| Divergent secrets | `divergent_secret` | error | Key declared as "shared" in config but values differ across envs |
| Orphaned keys | `orphaned_key` | warning (error if required) | Key in `.env.production` missing from all other envs |
| Format mismatch | `format_mismatch` | error | Same key with inconsistent value formats (e.g., `true` vs `True`, `30` vs `30s`) |
| Empty values | `empty_value` | warning (error if required) | Required key present but empty in one environment |
| Pending removal | `pending_removal` | warning | Key commented out in one env but still set in another |

A plain value difference is **not** drift — `DEBUG=true` in development and `DEBUG=false` in production is the whole point of separate env files. Values are only compared for a reason: a key you declared as shared, or two environments that spell the same value incompatibly.

### Install

env-drift is not on PyPI yet. Install it from the repository:

```bash
pip install git+https://github.com/yunaremaia/env-drift.git
```

Or, for development:

```bash
git clone https://github.com/yunaremaia/env-drift.git
cd env-drift
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

### Usage

```bash
# Scan current directory for .env.* drift
env-drift scan

# Scan a specific directory (also accepted as a positional argument)
env-drift scan --dir services/api

# Scan only some environments (repeatable)
env-drift scan --env development --env production

# Diff two named environments: what was added, removed, changed
env-drift diff development production
env-drift diff development production --format json

# Show which environments would be compared
env-drift list

# Define which keys must be consistent across environments
# (in pyproject.toml as [tool.env-drift] or .env-drift.toml as [env-drift])
[env-drift]
shared-keys = ["DATABASE_URL", "REDIS_URL", "LOG_LEVEL"]
required-in-prod = ["SECRET_KEY", "DATABASE_URL"]

# Run with config
env-drift scan --config .env-drift.toml

# Output formats
env-drift scan --format json   # CI-friendly
env-drift scan --format sarif  # GitHub Code Scanning integration
```

### Configuration

| Key | Meaning |
|-----|---------|
| `shared-keys` | Keys that must hold the same value in every environment. Divergence is an `error`. |
| `required-keys` | Keys that must exist in every environment. Absence is an `error`. |
| `required-in-prod` | Keys that must exist in the production environment. Absence is an `error`. |
| `prod-env` | Which environment name counts as production (default: `production`). |
| `exclude-files` | Extra `.env*` filenames to skip, e.g. `[".env.staging"]`. |
| `ignore-keys` | Keys to skip, same syntax as `.env-driftignore`. |

`.env-driftignore` holds per-key ignores, one pattern per line, with `#` comments, globs (`LEGACY_*`) and `!` negation:

```text
# env values that are intentionally per-environment
DEBUG
PORT
LEGACY_*
!LEGACY_KEEP
```

### Secret masking

Values are masked by default in **every** output format (text, JSON, SARIF), because CI logs are public. A value is redacted when its key contains `SECRET`, `TOKEN`, `KEY`, `PASSWORD`, `PASSWD`, `CREDENTIAL` or `AUTH`, when it is a URL with embedded credentials, or when it starts with a well-known token prefix (`ghp_`, `xoxb-`, `AKIA`, …). `PORT=3000` and `LOG_LEVEL=info` are printed as-is.

Use `--show-secrets` to disable masking while debugging. The default is on because a leaked credential cannot be un-leaked.

### Exit Codes

- `0` — no drift detected
- `1` — drift detected at or above the failure threshold (CI fail)
- `2` — config or usage error

By default only `error`-severity findings fail the run. Use `--strict` (or `--fail-on warning`) to fail on warnings too, or `--fail-on none` to always exit `0`.

### Diff actions

`env-drift diff A B` reports a symmetric difference rather than a verdict:

| Action | Symbol | Meaning |
|--------|--------|---------|
| `added` | `+ KEY=value` | Present in B, absent from A |
| `removed` | `- KEY=value` | Present in A, absent from B |
| `changed` | `~ KEY: old -> new` | Present in both with different values |
| `pending_removal` | `- KEY=value` | Present in A, commented out in B |

JSON output carries the same information with an `action` field (`added`/`removed`/`changed`/`pending_removal`) plus `value_a` and `value_b`.

### Parsing rules

Pure stdlib, no `dotenv` dependency. Supported: `KEY=value`, an optional `export` prefix, `#` comments and inline comments after unquoted values, single/double quoted values, blank lines, and commented-out assignments (tracked for `pending_removal`). `${VAR}` and `$VAR` references are expanded recursively before comparison, so two environments that spell the same URL differently are not reported as drift. A reference that cannot be resolved is left verbatim rather than guessed.

## Stack

- **Language:** Python 3.11+
- **Parser:** Pure stdlib (`os.environ` compatible, no `dotenv` runtime dependency)
- **Config:** `pyproject.toml` (PEP 621) or standalone `.env-drift.toml`
- **Output:** Terminal, JSON, SARIF 2.1.0
- **Tests:** `pytest`

## Roadmap

- [x] Core scanner: missing/divergent/orphan/format checks
- [x] Config-driven shared-key enforcement
- [x] SARIF output for GitHub Advanced Security
- [x] Secret masking in output (default on, every format)
- [x] Diff mode: compare two specific envs
- [ ] Auto-fix: synchronize missing keys from reference env
- [ ] Git pre-commit hook integration
- [ ] Multi-environment matrix diff (`compare A B C`)
- [ ] Multi-language support (`.envrc`, `config.yaml` profiles)

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

CI runs the suite plus a CLI smoke test on Python 3.11, 3.12 and 3.13.

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

Please follow the existing test-first pattern and run `pytest` before submitting.

## License

MIT

## Project Links

- Repository: https://github.com/yunaremaia/env-drift
- Issues: https://github.com/yunaremaia/env-drift/issues
