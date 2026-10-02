"""Configuration for env-drift.

Sources, in precedence order:

1. an explicit path (``--config``)
2. ``.env-drift.toml`` in the scanned directory (``[env-drift]`` table)
3. ``[tool.env-drift]`` in that directory's ``pyproject.toml``
4. built-in defaults

``.env-driftignore`` in the same directory contributes per-key ignores. Unknown
keys are ignored rather than fatal so a newer config file does not break an
older CLI, but a wrong *type* is a hard error -- silently ignoring
``shared-keys = "DATABASE_URL"`` would look like the tool ran clean.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Config", "ConfigError", "load_config"]

CONFIG_FILENAME = ".env-drift.toml"
IGNORE_FILENAME = ".env-driftignore"

_STRING_LIST_KEYS = ("shared-keys", "required-keys", "required-in-prod", "exclude-files", "ignore-keys")
_STRING_KEYS = ("prod-env",)


class ConfigError(Exception):
    """Raised for any unusable configuration input."""


@dataclass(frozen=True)
class Config:
    """Effective env-drift configuration."""

    shared_keys: tuple[str, ...] = ()
    required_keys: tuple[str, ...] = ()
    required_in_prod: tuple[str, ...] = ()
    exclude_files: tuple[str, ...] = ()
    ignored_keys: tuple[str, ...] = ()
    prod_env: str = "production"
    source: str | None = field(default=None, compare=False)
    paths: tuple[Path, ...] = field(default=(), compare=False)

    def is_ignored(self, key: str) -> bool:
        """True when ``key`` is excluded by ``.env-driftignore``.

        Supports shell-style globs (``LEGACY_*``) and ``!`` negations, where a
        later negated pattern re-includes a previously ignored key.
        """
        from fnmatch import fnmatch

        verdict = False
        for pattern in self.ignored_keys:
            if pattern.startswith("!"):
                if fnmatch(key, pattern[1:]):
                    verdict = False
            elif fnmatch(key, pattern):
                verdict = True
        return verdict


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _read_table(path: Path) -> dict[str, object]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc

    if path.name == "pyproject.toml":
        tool = data.get("tool")
        if not isinstance(tool, dict):
            return {}
        table = tool.get("env-drift") or tool.get("env_drift")
        return table if isinstance(table, dict) else {}

    # Standalone files use ``[env-drift]``, but ``[tool.env-drift]`` is accepted
    # too so a config table can be copied straight out of a pyproject.toml.
    table = data.get("env-drift") or data.get("env_drift")
    if isinstance(table, dict):
        return table
    tool = data.get("tool")
    if isinstance(tool, dict):
        nested = tool.get("env-drift") or tool.get("env_drift")
        if isinstance(nested, dict):
            return nested
    return {}


def _coerce(table: dict[str, object]) -> dict[str, object]:
    coerced: dict[str, object] = {}
    for key in _STRING_LIST_KEYS:
        if key not in table:
            continue
        raw = table[key]
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ConfigError(f"config key {key!r} must be a list of strings")
        coerced[key] = _dedupe(list(raw))
    for key in _STRING_KEYS:
        if key not in table:
            continue
        raw = table[key]
        if not isinstance(raw, str):
            raise ConfigError(f"config key {key!r} must be a string")
        coerced[key] = raw
    return coerced


def _read_ignore_file(path: Path) -> tuple[str, ...]:
    # UnicodeDecodeError is a ValueError, not an OSError, so listing only
    # OSError let a non-UTF-8 .env-driftignore escape as a raw traceback. The
    # process then exited 1 -- which the CLI documents as "drift detected" --
    # so a corrupted ignore file reddened CI as if config had drifted. The
    # decode is handled here exactly as _read_table already handles it.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read ignore file {path}: {exc}") from exc
    patterns = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return tuple(patterns)


def load_config(directory: Path, path: Path | None = None) -> Config:
    """Load configuration for a scan rooted at ``directory``."""
    directory = Path(directory)
    data: dict[str, object] = {}
    source: str | None = None
    loaded_paths: list[Path] = []

    if path is not None:
        path = Path(path)
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        data = _coerce(_read_table(path))
        source = str(path)
        loaded_paths.append(path)
    else:
        for candidate in (directory / CONFIG_FILENAME, directory / "pyproject.toml"):
            if candidate.is_file():
                coerced = _coerce(_read_table(candidate))
                if coerced or candidate.name == CONFIG_FILENAME:
                    data = coerced
                    source = str(candidate)
                loaded_paths.append(candidate)
                if source:
                    break

    ignore_path = directory / IGNORE_FILENAME
    if ignore_path.is_file():
        loaded_paths.append(ignore_path)
        data["ignore-keys"] = _dedupe(
            list(data.get("ignore-keys", ())) + list(_read_ignore_file(ignore_path))
        )

    return Config(
        shared_keys=tuple(data.get("shared-keys", ())),
        required_keys=tuple(data.get("required-keys", ())),
        required_in_prod=tuple(data.get("required-in-prod", ())),
        exclude_files=tuple(data.get("exclude-files", ())),
        ignored_keys=tuple(data.get("ignore-keys", ())),
        prod_env=str(data.get("prod-env", "production")),
        source=source,
        paths=tuple(loaded_paths),
    )
