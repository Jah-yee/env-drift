"""Dotenv parsing for env-drift.

Pure stdlib. Supports the subset of the dotenv format that shows up in real
environment files: ``KEY=value``, an optional ``export`` prefix, ``#`` comments,
single/double quoted values, inline comments after unquoted values, and blank
lines. Values are never expanded or interpolated here -- expansion is a separate
concern in :mod:`env_drift.expand`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["ParsedEnv", "parse_file", "parse_text"]

_EXPORT_PREFIXES = ("export ", "export\t")
_QUOTES = ("'", '"')


@dataclass(frozen=True)
class ParsedEnv:
    """Result of parsing a single environment file.

    ``values`` maps key -> value for active assignments. ``commented_keys``
    holds keys that appear only in commented-out assignments, which matters for
    the "pending removal" signal (a key disabled in one environment but still
    live in another).
    """

    values: dict[str, field] = field(default_factory=dict)  # type: ignore[assignment]
    commented_keys: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.values)


def _strip_inline_comment(raw: str) -> str:
    """Drop a trailing ``# comment`` from an *unquoted* value.

    A ``#`` only opens a comment when whitespace precedes it, so
    ``B=plain#not-a-comment`` keeps its value. A ``#`` at index 0 is *not* a
    comment either: the line-level comment has already been handled by the
    caller, so a value starting with ``#`` is real content (a hex colour like
    ``COLOR=#ff0000``, or a URL fragment). Truncating it to an empty string
    would report an empty value that does not exist.
    """
    for index, char in enumerate(raw):
        if char != "#":
            continue
        if index > 0 and raw[index - 1] in " \t":
            return raw[:index].rstrip()
    return raw


def _clean_value(raw: str) -> str:
    """Normalize a raw right-hand side: unquote, or strip a trailing comment.

    The closing quote is what tells a quoted value apart from an unquoted one,
    and a trailing comment after a quoted value is legal and common::

        A="hello" # released in v2

    So a value whose first character is a quote has to be searched for its
    *closing* quote and everything past it treated as a comment. Deciding
    "unquoted vs quoted" by comparing the first and last character instead
    leaves the quotes in the value whenever a comment follows them.
    """
    value = raw.strip()
    if value[:1] in _QUOTES:
        closing = value.find(value[0], 1)
        if closing != -1:
            return value[1:closing]
        # Unterminated quote: fall through and treat the whole thing as literal.
    return _strip_inline_comment(value)


def _split_assignment(line: str) -> tuple[str, str] | None:
    """Return ``(key, raw_value)`` for an assignment line, else ``None``."""
    if "=" not in line:
        return None
    key, _, raw_value = line.partition("=")
    key = key.strip()
    if not key:
        return None
    return key, raw_value


def parse_text(text: str) -> ParsedEnv:
    """Parse dotenv ``text`` into active values plus commented-out keys."""
    values: dict[str, str] = {}
    commented: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#"):
            body = line.lstrip("#").strip()
            assignment = _split_assignment(body)
            if assignment is None:
                continue
            key = assignment[0]
            if key not in values and key not in commented:
                commented.append(key)
            continue

        for prefix in _EXPORT_PREFIXES:
            if line.startswith(prefix):
                line = line[len(prefix) :].lstrip()
                break

        assignment = _split_assignment(line)
        if assignment is None:
            # Not an assignment (e.g. a stray "echo" line); ignore it.
            continue

        key, raw_value = assignment
        values[key] = _clean_value(raw_value)
        # A key that is commented out and then re-enabled below is active, so
        # it must not linger in the pending-removal list.
        if key in commented:
            commented.remove(key)

    return ParsedEnv(values=values, commented_keys=tuple(commented))


def parse_file(path: str | Path) -> ParsedEnv:
    """Parse the dotenv file at ``path`` using UTF-8, replacing bad bytes."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_text(text)
