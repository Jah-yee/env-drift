"""Cross-environment drift scanner.

The unit of work is a *snapshot*: one environment's parsed key/value pairs. The
scanner compares every pair of snapshots and emits one :class:`EnvDrift` per
inconsistency, so a finding always carries the full cross-environment context
for the key that drifted.

A plain value difference is **not** drift -- ``DEBUG=true`` in development and
``DEBUG=false`` in production is the whole point of separate env files. Drift is
reported for these checks:

``missing_key_in_env``
    The key exists in some environments and is absent from others.
``orphaned_key``
    The key exists in exactly one environment (dead config elsewhere).
``divergent_secret``
    A key declared in ``shared-keys`` holds different values per environment.
``format_mismatch``
    The same key holds values of different shapes (bool vs string, number vs
    duration) -- usually a typo or an unquoted value.
``empty_value``
    The key resolves to an empty string where another environment has a value.
``pending_removal``
    The key is commented out in one environment but still live in another.

Each finding carries the env file it is anchored to (:attr:`EnvDrift.path`) so
that :func:`env_drift.report.render_sarif` can report a repo-relative location.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .expand import expand_all
from .parser import parse_file
from .shapes import shape_of

__all__ = ["SEVERITIES", "EnvDrift", "EnvSnapshot", "load_snapshots", "scan"]

SEVERITIES = ("warning", "error")


@dataclass(frozen=True)
class EnvSnapshot:
    """One environment's parsed configuration."""

    name: str
    values: dict[str, str] = field(default_factory=dict)
    commented_keys: tuple[str, ...] = ()
    path: Path | None = None
    #: True when ``values`` has already been through :func:`expand_all`.
    #: Snapshots built by hand (library use, tests) default to False so that
    #: comparison still resolves their references. Snapshots from
    #: :func:`load_snapshots` set it, so the same values are never expanded
    #: twice -- see the note on :func:`env_drift.expand.expand`.
    expanded: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", dict(self.values))
        object.__setattr__(self, "commented_keys", tuple(self.commented_keys))


@dataclass(frozen=True)
class EnvDrift:
    """A single cross-environment inconsistency."""

    key: str
    drift_type: str
    severity: str
    message: str
    environments: dict[str, str | None] = field(default_factory=dict)
    #: The env file this finding is anchored to, when the scan came from real
    #: files. :func:`env_drift.report.render_sarif` turns it into a
    #: repo-relative ``artifactLocation.uri`` so code scanning points at the
    #: file that drifted instead of at the scan root. ``None`` for a finding
    #: built by hand, which has no file behind it.
    path: Path | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "drift_type": self.drift_type,
            "severity": self.severity,
            "message": self.message,
            "environments": dict(self.environments),
        }


def load_snapshots(files, expand: bool = True) -> list[EnvSnapshot]:
    """Parse discovered :class:`~env_drift.discovery.EnvFile` objects."""
    snapshots = []
    for env_file in files:
        parsed = parse_file(env_file.path)
        values = expand_all(parsed.values) if expand else dict(parsed.values)
        snapshots.append(
            EnvSnapshot(
                name=env_file.name,
                values=values,
                commented_keys=parsed.commented_keys,
                path=Path(env_file.path),
                expanded=expand,
            )
        )
    return snapshots


def _severity_rank(severity: str) -> int:
    return SEVERITIES.index(severity)


def _resolved(values: dict[str, str], expanded: bool = False) -> dict[str, str]:
    """Resolve ``${VAR}`` references so comparisons see final values.

    Only when they have not been resolved already. Expansion is deliberately
    not idempotent -- ``\\$`` has to yield a literal dollar sign, and a second
    pass would resolve that dollar sign -- so a snapshot that came from
    :func:`load_snapshots` must not be expanded a second time.
    """
    if expanded:
        return dict(values)
    return expand_all(values)


def _casing_inconsistent(values_by_env, defined_in, key):
    """True when environments spell the same value with different casing.

    ``DEBUG=true`` vs ``DEBUG=True`` is the same *shape* but a different
    literal, and code that does ``if os.environ["DEBUG"] == "True"`` silently
    stops matching one environment. Casing is only compared for values whose
    shape is casing-sensitive (booleans), never for free text.
    """
    literals = [values_by_env[name][key] for name in defined_in]
    if len(set(literals)) <= 1:
        return False
    if len({literal.lower() for literal in literals}) != 1:
        return False
    return all(shape_of(literal) == "boolean" for literal in literals)


def _anchor_path(snapshots, defined_in):
    """The file a finding about this key should be reported against.

    The first environment that actually defines the key wins, so a SARIF
    alert lands on the env file carrying the live value rather than on the
    scan root. A required key that no environment declares has no defining
    file, so the first snapshot is used instead; a hand-built finding with no
    snapshots at all has no path to point at.
    """
    by_name = {s.name: s.path for s in snapshots}
    for name in defined_in:
        path = by_name.get(name)
        if path is not None:
            return Path(path)
    for snapshot in snapshots:
        if snapshot.path is not None:
            return Path(snapshot.path)
    return None


def _pending_removal(key, snapshots, values_by_env, defined_in, present, path=None):
    commented_in = [
        s.name for s in snapshots if key in s.commented_keys and key not in values_by_env[s.name]
    ]
    if not (defined_in and commented_in):
        return None
    return EnvDrift(
        key=key,
        drift_type="pending_removal",
        severity="warning",
        message=(
            f"{key!r} is commented out in {', '.join(commented_in)} but still set in "
            f"{', '.join(defined_in)}"
        ),
        environments=present,
        path=path,
    )


def _presence_check(key, defined_in, absent_in, present, required, path=None):
    """Report absence of a key: orphaned (one env) or missing (some envs)."""
    if absent_in and not defined_in:
        return EnvDrift(
            key=key,
            drift_type="missing_key_in_env",
            severity="error",
            message=(
                f"{key!r} is required but is not declared in any environment "
                f"({', '.join(absent_in)})"
            ),
            environments=present,
            path=path,
        )
    if absent_in and len(defined_in) == 1:
        # Present in exactly one environment: both "missing elsewhere" and
        # "orphaned". Report the single, more actionable fact.
        return EnvDrift(
            key=key,
            drift_type="orphaned_key",
            severity="error" if required else "warning",
            message=(
                f"{key!r} exists only in {defined_in[0]} and in no other environment "
                f"({', '.join(absent_in)})"
            ),
            environments=present,
            path=path,
        )
    if absent_in:
        return EnvDrift(
            key=key,
            drift_type="missing_key_in_env",
            severity="error" if required else "warning",
            message=(
                f"{key!r} is set in {', '.join(defined_in)} but missing in "
                f"{', '.join(absent_in)}"
            ),
            environments=present,
            path=path,
        )
    return None


def _value_check(key, values_by_env, defined_in, present, config, path=None):
    """Compare values across environments for shared keys, shapes and empties."""
    findings = []
    distinct = {values_by_env[name][key] for name in defined_in}

    if key in config.shared_keys and len(distinct) > 1:
        return [
            EnvDrift(
                key=key,
                drift_type="divergent_secret",
                severity="error",
                message=(
                    f"{key!r} is declared as a shared key but its value differs across "
                    f"environments ({', '.join(defined_in)})"
                ),
                environments=present,
                path=path,
            )
        ]

    shapes = {name: shape_of(values_by_env[name][key]) for name in defined_in}
    reason = None
    if len(set(shapes.values())) > 1:
        reason = ", ".join(f"{name}={shapes[name]}" for name in defined_in)
    elif _casing_inconsistent(values_by_env, defined_in, key):
        reason = ", ".join(f"{name}={values_by_env[name][key]!r}" for name in defined_in)
    if reason:
        findings.append(
            EnvDrift(
                key=key,
                drift_type="format_mismatch",
                severity="error",
                message=f"{key!r} has inconsistent value formats across environments: {reason}",
                environments=present,
                path=path,
            )
        )

    empty_in = [name for name in defined_in if values_by_env[name][key] == ""]
    if empty_in and len(distinct) > 1:
        findings.append(
            EnvDrift(
                key=key,
                drift_type="empty_value",
                severity="error" if key in config.required_keys else "warning",
                message=f"{key!r} is empty in {', '.join(empty_in)}",
                environments=present,
                path=path,
            )
        )
    return findings


def scan(snapshots: list[EnvSnapshot], config: Config) -> list[EnvDrift]:
    """Compare every environment against every other and report drift."""
    if len(snapshots) < 2:
        return []

    names = [s.name for s in snapshots]
    values_by_env = {s.name: _resolved(s.values, s.expanded) for s in snapshots}
    found_keys = {key for values in values_by_env.values() for key in values}
    # A required key that no environment declares is drift in its own right,
    # so it has to enter the loop even though it appears in no file.
    all_keys = sorted(found_keys | set(config.required_keys) | set(config.required_in_prod))

    drifts: list[EnvDrift] = []
    for key in all_keys:
        if config.is_ignored(key):
            continue

        present = {name: values.get(key) for name, values in values_by_env.items()}
        defined_in = [name for name in names if key in values_by_env[name]]
        absent_in = [name for name in names if key not in values_by_env[name]]
        required = key in config.required_keys or (
            key in config.required_in_prod and config.prod_env in names
        )
        path = _anchor_path(snapshots, defined_in)

        presence = _presence_check(key, defined_in, absent_in, present, required, path=path)
        if presence is not None:
            drifts.append(presence)

        # A key commented out in one environment but still live in another is
        # drift regardless of how many environments define it. This check used
        # to sit behind `len(defined_in) < 2`, which skipped it for exactly the
        # 3-environment case the README documents: `defined_in` had 2 entries,
        # the guard fell through to `_value_check`, and `pending_removal` was
        # never emitted even though the finding was true.
        pending = _pending_removal(key, snapshots, values_by_env, defined_in, present, path=path)
        if pending is not None:
            drifts.append(pending)

        if len(defined_in) < 2:
            continue

        drifts.extend(_value_check(key, values_by_env, defined_in, present, config, path=path))

    return drifts
