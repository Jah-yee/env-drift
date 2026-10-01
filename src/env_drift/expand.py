"""Shell-style variable expansion for env-drift values.

Supports ``${VAR}`` and ``$VAR``. Unknown references are left verbatim so the
scanner can still report the raw drift, references are resolved recursively so
chained definitions (``C=${B}-c``) collapse to a comparable literal, ``\\$`` is
an escape for a literal dollar sign, and a self-reference terminates instead of
looping.
"""

from __future__ import annotations

import re

__all__ = ["expand", "expand_all", "looks_like_reference"]

_MAX_DEPTH = 10
_REFERENCE = re.compile(r"(?<!\\)\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def looks_like_reference(value: str) -> bool:
    """True when ``value`` still contains at least one ``$VAR``/``${VAR}``."""
    return _REFERENCE.search(value) is not None


def _substitute(match: re.Match[str], values: dict[str, str]) -> str:
    name = match.group(1) or match.group(2)
    if name not in values:
        # Unresolvable reference: keep it so drift is still visible.
        return match.group(0)
    return values[name]


def expand(value: str, values: dict[str, str]) -> str:
    """Expand references in ``value`` using ``values`` as the lookup scope.

    Expansion happens **once** per value. Running it twice is not idempotent
    and cannot be made so: ``\\$`` is the escape that turns into a literal
    dollar sign, so a second pass would see that bare ``$`` and resolve it,
    and two files that both literally spell ``\\$TEMPLATE`` would be reported
    as drift. Callers that may be handed already-expanded data have to say so
    rather than re-expand -- see ``EnvSnapshot.expanded``.
    """
    current = value
    for _ in range(_MAX_DEPTH):
        expanded = _REFERENCE.sub(lambda m: _substitute(m, values), current)
        if expanded == current:
            return _unescape(expanded)
        current = expanded
    # Depth limit reached: a cycle. Return the last literal state.
    return _unescape(current)


def _unescape(value: str) -> str:
    """Consume the ``\\`` of an escaped dollar sign: ``\\$X`` -> ``$X``."""
    return value.replace("\\$", "$")


def expand_all(values: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``values`` with every value fully expanded."""
    return {key: expand(value, values) for key, value in values.items()}
