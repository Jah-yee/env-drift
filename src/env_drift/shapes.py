"""Value-shape classification for format-mismatch detection.

Two environments holding the same key with different *shapes* is usually a
mistake: ``DEBUG=true`` in one file and ``DEBUG=True`` (a string, or a NameError
waiting to happen) in another, or ``TIMEOUT=30`` against ``TIMEOUT=30s``. The
classification is intentionally coarse -- the point is to catch a value that
cannot possibly be the same thing, not to police style.
"""

from __future__ import annotations

import re

__all__ = ["SHAPES", "shape_of"]

SHAPES = ("boolean", "integer", "float", "url", "json", "path", "string")

_BOOLEANS = {"true", "false", "yes", "no", "on", "off"}
_INTEGER = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?((\d+\.\d*|\.\d+)([eE][+-]?\d+)?|\d+[eE][+-]?\d+)$")
_URL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_PATH = re.compile(r"^(/|~/|\./|\.\./)")


def shape_of(value: str) -> str:
    """Classify a raw env value into one of :data:`SHAPES`."""
    if value == "":
        return "empty"
    lowered = value.strip().lower()
    if lowered in _BOOLEANS:
        return "boolean"
    if _INTEGER.match(value.strip()):
        return "integer"
    if _FLOAT.match(value.strip()):
        return "float"
    if _URL.match(value.strip()):
        return "url"
    if value.strip()[:1] in "[{" and value.strip()[-1:] in "]}":
        return "json"
    if _PATH.match(value.strip()):
        return "path"
    return "string"
