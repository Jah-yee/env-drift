"""Symmetric diff between two environments.

Answers "what changed from A to B", not just "is there drift":

``added``
    present in the target, absent from the source
``removed``
    present in the source, absent (and not merely commented) from the target
``changed``
    present in both with different values
``pending_removal``
    present in the source, commented out in the target -- disabled, not deleted

A commented-out key in the target is deliberately *not* a removal: reporting it
as removed loses the distinction between "delete this" and "stop setting this",
which is the thing a reviewer needs to see.
"""

from __future__ import annotations

from dataclasses import dataclass

from .expand import expand_all
from .scanner import EnvSnapshot

__all__ = ["ACTIONS", "DiffEntry", "diff_snapshots"]

ACTIONS = ("added", "removed", "changed", "pending_removal")

_SYMBOLS = {"added": "+", "removed": "-", "changed": "~", "pending_removal": "-"}


@dataclass(frozen=True)
class DiffEntry:
    """One key's difference between two environments."""

    key: str
    action: str
    value_a: str | None
    value_b: str | None

    def render(self) -> str:
        """Render as a single ``diff -u``-like line."""
        symbol = _SYMBOLS[self.action]
        if self.action == "changed":
            return f"{symbol} {self.key}: {self.value_a} -> {self.value_b}"
        value = self.value_b if self.action == "added" else self.value_a
        return f"{symbol} {self.key}={value}"

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "action": self.action,
            "value_a": self.value_a,
            "value_b": self.value_b,
        }


def diff_snapshots(source: EnvSnapshot, target: EnvSnapshot) -> list[DiffEntry]:
    """Return the symmetric difference from ``source`` to ``target``."""
    left = expand_all(source.values)
    right = expand_all(target.values)

    entries: list[DiffEntry] = []
    for key in sorted(set(left) | set(right)):
        in_left, in_right = key in left, key in right
        if in_left and in_right:
            if left[key] != right[key]:
                entries.append(DiffEntry(key, "changed", left[key], right[key]))
            continue
        if in_right:
            entries.append(DiffEntry(key, "added", None, right[key]))
            continue
        if key in target.commented_keys:
            entries.append(DiffEntry(key, "pending_removal", left[key], None))
        else:
            entries.append(DiffEntry(key, "removed", left[key], None))
    return entries
