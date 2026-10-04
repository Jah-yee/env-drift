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

- `scan --env` no longer drops an environment name that matched no file. A
  misspelling was filtered out silently, and because the check needs two
  environments, the survivors were scanned alone, `scan()` returned nothing and
  the CLI reported "No drift detected" with exit 0 -- a drift scanner reporting
  clean because of a typo in its own arguments, in text and in JSON alike. An
  unmatched name is now a usage error naming what was not found and what was
  available, matching what `diff` already did. When no `.env` files exist at
  all, the pre-existing "no .env files found" error is kept rather than
  reporting every requested name as unknown
- Masking keys off the variable name rather than the environment name, which
  leaked `SECRET_KEY` values in text and JSON output
- `pending_removal` is no longer skipped once a key is live in two or more
  environments. The check sat behind `len(defined_in) < 2`, so the
  three-environment case the README documents (a key live in development and
  staging, commented out in production) reported only the weaker
  `missing_key_in_env` and lost the actionable "the removal was started but
  never finished" finding
- A `.env-driftignore` that is not valid UTF-8 is now reported as a
  configuration error (exit 2) instead of escaping as a raw traceback. The
  decode error is not an `OSError`, and the resulting exit 1 is documented as
  "drift detected", so a corrupted ignore file failed CI for the wrong reason
- SARIF `artifactLocation.uri` is now relative to the scanned root and points
  at the env file that drifted. Every location used to carry the resolved root
  directory as an absolute path, which both landed every alert on the repo root
  and contradicted `uriBaseId: "%SRCROOT%"`. A finding with no file behind it
  is rendered without a location rather than with a fabricated one

## [Initial Release]

- Initial project release
