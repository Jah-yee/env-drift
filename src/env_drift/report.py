"""Rendering of scan findings as text, JSON, or SARIF.

Every format passes through :func:`_safe_environments`, which masks credentials
before anything is serialised. Masking is applied *before* the format is
rendered, not inside each renderer, so a new output format cannot accidentally
skip it -- the leak path this project exists to close.

``root`` is the scanned directory; it anchors SARIF artifact locations so
GitHub code scanning can link a result back to a file.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .masking import mask_value
from .scanner import EnvDrift

__all__ = [
    "FORMATS",
    "build_payload",
    "render",
    "render_json",
    "render_sarif",
    "render_text",
    "summarize",
]

FORMATS = ("text", "json", "sarif")

_SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
)

_HELP: dict[str, str] = {
    "missing_key_in_env": "A key declared in some environments is absent from others.",
    "orphaned_key": "A key exists in exactly one environment.",
    "divergent_secret": "A shared key holds different values across environments.",
    "format_mismatch": "The same key holds values of different shapes across environments.",
    "empty_value": "A key resolves to an empty string where another environment has a value.",
    "pending_removal": "A key is commented out in one environment but still live in another.",
}


def _safe_environments(drifts: list[EnvDrift], mask: bool = True) -> list[dict[str, Any]]:
    """Serialise findings with values masked unless explicitly disabled."""
    payload = []
    for drift in drifts:
        environments = drift.environments
        if mask:
            # The mask key is the *variable* name. Keying this on the
            # environment name leaked SECRET_KEY values in a real run.
            environments = {
                name: None if value is None else mask_value(drift.key, value)
                for name, value in environments.items()
            }
        payload.append(
            {
                "key": drift.key,
                "drift_type": drift.drift_type,
                "severity": drift.severity,
                "message": drift.message,
                "environments": environments,
            }
        )
    return payload


def summarize(drifts: list[EnvDrift]) -> dict[str, object]:
    """Count findings by severity and by drift type."""
    return {
        "total": len(drifts),
        "errors": sum(1 for d in drifts if d.severity == "error"),
        "warnings": sum(1 for d in drifts if d.severity == "warning"),
        "by_type": dict(sorted(Counter(d.drift_type for d in drifts).items())),
    }


def build_payload(
    drifts: list[EnvDrift],
    environments: list[str] | None = None,
    root: str | Path = ".",
    mask: bool = True,
) -> dict[str, object]:
    """The canonical JSON payload; SARIF and text are derived from it."""
    return {
        "tool": {"name": "env-drift", "version": _version()},
        "root": str(root),
        "environments": list(environments or []),
        "summary": summarize(drifts),
        "results": _safe_environments(drifts, mask=mask),
    }


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("env-drift")
    except PackageNotFoundError:  # running from a source checkout
        return "0.1.0"


def render_text(
    drifts: list[EnvDrift],
    environments: list[str] | None = None,
    root: str | Path = ".",
    mask: bool = True,
) -> str:
    """Human-readable summary, one line per finding."""
    safe = _safe_environments(drifts, mask=mask)
    if not safe:
        compared = ", ".join(environments or []) or "none"
        return f"No drift detected across environments: {compared}\n"

    lines: list[str] = []
    if environments:
        lines.append(f"Comparing environments: {', '.join(environments)}")
    lines.append("")
    width = max(len(str(item["key"])) for item in safe)
    for item in safe:
        lines.append(f"  [{item['severity']:>7}] {item['key']:<{width}}  {item['drift_type']}")
        lines.append(f"            {item['message']}")
        for name, value in dict(item["environments"]).items():
            if value is None:
                continue
            lines.append(f"            {name}: {value}")
    summary = summarize(drifts)
    lines.append("")
    lines.append(
        f"{summary['total']} finding(s): {summary['errors']} error(s), "
        f"{summary['warnings']} warning(s)"
    )
    return "\n".join(lines) + "\n"


def render_json(
    drifts: list[EnvDrift],
    environments: list[str] | None = None,
    root: str | Path = ".",
    mask: bool = True,
) -> str:
    """Machine-readable payload for CI."""
    return json.dumps(build_payload(drifts, environments, root, mask), indent=2) + "\n"


def render_sarif(
    drifts: list[EnvDrift],
    environments: list[str] | None = None,
    root: str | Path = ".",
    mask: bool = True,
) -> str:
    """SARIF 2.1.0 for GitHub code scanning."""
    safe = _safe_environments(drifts, mask=mask)
    root_path = Path(root).resolve()

    rules: list[dict[str, Any]] = [
        {
            "id": drift_type,
            "name": drift_type,
            "shortDescription": {"text": _HELP.get(drift_type, drift_type)},
            "defaultConfiguration": {"level": "warning"},
        }
        for drift_type in sorted({str(item["drift_type"]) for item in safe})
    ]

    results: list[dict[str, Any]] = []
    for item in safe:
        results.append(
            {
                "ruleId": item["drift_type"],
                "level": item["severity"],
                "message": {"text": item["message"]},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": str(root_path),
                                "uriBaseId": "%SRCROOT%",
                            },
                            "region": {"startLine": 1},
                        }
                    }
                ],
                "properties": {"key": item["key"], "environments": item["environments"]},
            }
        )

    document = {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "env-drift",
                        "version": _version(),
                        "informationUri": "https://github.com/yunaremaia/env-drift",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(document, indent=2) + "\n"


def render(
    drifts: list[EnvDrift],
    fmt: str = "text",
    environments: list[str] | None = None,
    root: str | Path = ".",
    mask: bool = True,
) -> str:
    """Render ``drifts`` in ``fmt`` (text, json or sarif)."""
    renderers = {"text": render_text, "json": render_json, "sarif": render_sarif}
    try:
        renderer = renderers[fmt]
    except KeyError:
        raise ValueError(f"unknown format {fmt!r}; expected one of {', '.join(FORMATS)}") from None
    return renderer(drifts, environments, root, mask)
