# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Core scanner (`src/env_drift/scanner.py`) comparing every `.env*` environment
  against every other, with six drift types: `missing_key_in_env`,
  `orphaned_key`, `divergent_secret`, `format_mismatch`, `empty_value`,
  `pending_removal`
- Dotenv parser handling `export` prefixes, comments, inline comments, quoted
  values, blank lines, and commented-out assignments
- `${VAR}` / `$VAR` expansion (recursive, unknown references left verbatim)
- Symmetric `env-drift diff A B` with `added` / `removed` / `changed` /
  `pending_removal` actions
- Configuration from `.env-drift.toml` (`[env-drift]`) or `pyproject.toml`
  (`[tool.env-drift]`): `shared-keys`, `required-keys`, `required-in-prod`,
  `prod-env`, `exclude-files`, `ignore-keys`
- `.env-driftignore` with glob and `!` negation support
- Secret masking, on by default in text, JSON and SARIF output
  (`--show-secrets` to disable)
- Output formats: text, JSON, SARIF 2.1.0
- `env-drift list` to show discovered environments
- CI workflow running the suite plus a CLI smoke test on Python 3.11-3.13

### Changed

- README now documents only behaviour that exists, including the real install
  path (`pip install git+https://github.com/yunaremaia/env-drift.git`); the
  project is not published on PyPI

### Fixed

- Masking keys off the variable name rather than the environment name, which
  leaked `SECRET_KEY` values in text and JSON output

## [Initial Release]

- Initial project release
