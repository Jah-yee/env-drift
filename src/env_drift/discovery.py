"""Discovery of environment files in a project tree.

Recognised names are ``.env`` (env name ``default``) and ``.env.<name>``
including the ``.env.<name>.local`` convention. Templates (``.env.example``,
``.env.template``, and friends) are skipped by default because they are not
environments -- comparing against a template produces noise, not drift. Hidden
directories such as ``.venv`` and ``.git`` are never descended into.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["DEFAULT_EXCLUDES", "EnvFile", "discover_env_files", "env_name_for"]

#: Template files that are documentation, not deployable environments.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
    ".env.defaults",
)

_HIDDEN_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}


@dataclass(frozen=True)
class EnvFile:
    """A discovered environment file and the environment name it represents."""

    name: str
    path: Path

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.name} ({self.path.name})"


def env_name_for(path: Path) -> str:
    """Map ``.env`` / ``.env.production.local`` to an environment name."""
    filename = path.name
    if filename == ".env":
        return "default"
    if filename.startswith(".env."):
        return filename[len(".env.") :]
    return filename


def _is_hidden_dir(path: Path) -> bool:
    return path.name in _HIDDEN_DIRS or path.name.startswith(".")


def discover_env_files(root: Path, exclude: tuple[str, ...] = ()) -> list[EnvFile]:
    """Return every environment file under ``root``, sorted by env name."""
    root = Path(root)
    excluded = set(DEFAULT_EXCLUDES) | set(exclude)
    found: list[EnvFile] = []

    for path in sorted(root.rglob(".env*")):
        if not path.is_file():
            continue
        if any(part == ".git" or _is_hidden_dir(Path(part)) for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name in excluded:
            continue
        if not (path.name == ".env" or path.name.startswith(".env.")):
            continue
        found.append(EnvFile(name=env_name_for(path), path=path))

    return sorted(found, key=lambda f: f.name)
