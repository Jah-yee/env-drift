"""Secret masking for env-drift output.

Default-on, because CI logs are public and a leaked credential cannot be
un-leaked. A value is treated as secret when its *key* matches a credential-ish
pattern (``SECRET``, ``TOKEN``, ``KEY``, ``PASSWORD``, ``CREDENTIAL``,
``PASSWD``, ``AUTH``) or when its *value* has the shape of an embedded
credential (a URL carrying a password, or a well-known token prefix).

Masking replaces the whole value with :data:`REDACTED` -- never a prefix or
suffix -- so no fragment of a secret reaches the output.
"""

from __future__ import annotations

import re

__all__ = [
    "REDACTED",
    "is_secret_key",
    "mask_value",
    "mask_values",
]

REDACTED = "***REDACTED***"

_KEY_PATTERN = re.compile(r"(SECRET|TOKEN|KEY|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.IGNORECASE)

# userinfo@host, e.g. postgres://app:s3cret@db.internal:5432/app
#
# The userinfo half is matched loosely and only its *presence* matters: any
# userinfo containing a colon carries a password, even when the user side is
# empty (``postgres://:s3cret@db/app`` is a common Docker/Postgres form) and
# even when the password contains characters that a stricter class would
# reject. Anchoring on the colon inside the authority -- before the first
# ``/`` or ``@`` -- keeps a colon inside a path or query from counting.
_URL_CREDENTIALS = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s@]*:[^/\s@]*@")

# Well-known literal token shapes that leak even under an innocuous key name.
_VALUE_PREFIXES = (
    "ghp_",
    "gho_",
    "github_pat_",
    "ghs_",
    "ghr_",
    "glpat-",
    "xoxb-",
    "xoxp-",
    "AKIA",
    "ASIA",
    "sk-",
    "sk_live_",
    "sk_test_",
    "eyJhbGciOi",  # JWT
    "-----BEGIN",
)


def is_secret_key(key: str) -> bool:
    """True when the *key name* suggests the value is a credential."""
    return _KEY_PATTERN.search(key) is not None


def _is_secret_value(value: str) -> bool:
    if not value:
        return False
    if _URL_CREDENTIALS.match(value):
        return True
    return value.startswith(_VALUE_PREFIXES)


def mask_value(key: str, value: str) -> str:
    """Return ``REDACTED`` for credentials, otherwise ``value`` unchanged."""
    if is_secret_key(key) or _is_secret_value(value):
        return REDACTED
    return value


def mask_values(values: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``values`` with every credential redacted."""
    return {key: mask_value(key, value) for key, value in values.items()}
