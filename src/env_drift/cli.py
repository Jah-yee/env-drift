"""Command line interface for env-drift.

Commands
--------
``env-drift scan [PATH]``
    Compare every ``.env*`` file found under ``PATH``.
``env-drift diff ENV_A ENV_B``
    Symmetric diff between two named environments.
``env-drift list``
    Show which environments would be compared.

Exit codes (the contract CI depends on):
``0``
    no drift (or, for ``diff``, no differences)
``1``
    drift at or above the failure threshold
``2``
    configuration or usage error -- bad config, no env files, unknown
    environment, unsupported format

Values are masked unless ``--show-secrets`` is passed, in every output format.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config
from .diff import diff_snapshots
from .discovery import discover_env_files
from .masking import mask_value
from .report import FORMATS, build_payload, render
from .scanner import load_snapshots, scan

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2

FAIL_LEVELS = ("none", "warning", "error")


class UsageError(Exception):
    """Any condition that must exit with code 2."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="env-drift",
        description="Detect cross-environment configuration drift between .env files.",
    )
    parser.add_argument("--version", action="version", version=f"env-drift {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "path",
            nargs="?",
            default=None,
            help="directory to scan (default: current directory)",
        )
        sub.add_argument(
            "--dir",
            dest="dir_opt",
            metavar="PATH",
            help="directory to scan (same as the positional PATH)",
        )
        sub.add_argument("--config", metavar="FILE", help="path to a .env-drift.toml file")
        sub.add_argument(
            "--format",
            choices=FORMATS,
            default="text",
            help="output format (default: text)",
        )
        sub.add_argument(
            "--show-secrets",
            action="store_true",
            help="print values instead of masking them (debugging only)",
        )

    scan_parser = subparsers.add_parser("scan", help="scan for cross-environment drift")
    add_common(scan_parser)
    scan_parser.add_argument(
        "--env",
        action="append",
        metavar="NAME",
        help="restrict the scan to these environments (repeatable)",
    )
    scan_parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on warnings as well as errors",
    )
    scan_parser.add_argument(
        "--fail-on",
        choices=FAIL_LEVELS,
        default=None,
        help="minimum severity that fails the run (default: error)",
    )

    diff_parser = subparsers.add_parser("diff", help="diff two named environments")
    diff_parser.add_argument("env_a", metavar="ENV_A")
    diff_parser.add_argument("env_b", metavar="ENV_B")
    add_common(diff_parser)

    list_parser = subparsers.add_parser("list", help="list discovered environments")
    list_parser.add_argument("path", nargs="?", default=".")
    list_parser.add_argument("--config", metavar="FILE")

    return parser


def _threshold(args: argparse.Namespace) -> str:
    if getattr(args, "strict", False):
        return "warning"
    return getattr(args, "fail_on", None) or "error"


def _should_fail(drifts, threshold: str) -> bool:
    if threshold == "none":
        return False
    if not drifts:
        return False
    if threshold == "warning":
        return True
    return any(drift.severity == "error" for drift in drifts)


def _target_dir(args: argparse.Namespace) -> str:
    """The positional PATH and --dir are interchangeable; --dir wins."""
    return getattr(args, "dir_opt", None) or args.path or "."


def _load(args: argparse.Namespace):
    target = _target_dir(args)
    root = Path(target).resolve()
    if not root.is_dir():
        raise UsageError(f"not a directory: {target}")
    try:
        config = load_config(root, Path(args.config) if args.config else None)
    except ConfigError as exc:
        raise UsageError(str(exc)) from exc

    files = discover_env_files(root, exclude=config.exclude_files)
    if getattr(args, "env", None):
        wanted = set(args.env)
        files = [f for f in files if f.name in wanted]
    if not files:
        raise UsageError(f"no .env files found under {root}")
    return root, config, files


def _cmd_scan(args: argparse.Namespace) -> int:
    root, config, files = _load(args)
    snapshots = load_snapshots(files)
    drifts = scan(snapshots, config)
    mask = not args.show_secrets

    print(
        render(
            drifts,
            args.format,
            environments=[snapshot.name for snapshot in snapshots],
            root=root,
            mask=mask,
        ),
        end="",
    )
    return EXIT_DRIFT if _should_fail(drifts, _threshold(args)) else EXIT_OK


def _cmd_diff(args: argparse.Namespace) -> int:
    root, _config, files = _load(args)
    by_name: dict[str, list] = {}
    for found in files:
        by_name.setdefault(found.name, []).append(found)

    for name in (args.env_a, args.env_b):
        if name not in by_name:
            available = ", ".join(sorted(by_name)) or "none"
            raise UsageError(f"unknown environment {name!r}; discovered: {available}")

    def resolve(name: str):
        matches = by_name[name]
        if len(matches) > 1:
            # Selecting by bare name is ambiguous in a monorepo, where every
            # service has its own `.env.production`. Silently taking the last
            # match would diff a file the caller never asked for.
            paths = ", ".join(str(m.path) for m in matches)
            raise UsageError(
                f"environment {name!r} is ambiguous, found {len(matches)} files: {paths}"
            )
        return matches[0]

    source = load_snapshots([resolve(args.env_a)])[0]
    target = load_snapshots([resolve(args.env_b)])[0]
    entries = diff_snapshots(source, target)
    mask = not args.show_secrets

    if args.format == "json":
        payload = build_payload([], environments=[source.name, target.name], root=root, mask=mask)
        payload["diff"] = [_safe_entry(entry, mask) for entry in entries]
        payload["summary"] = {"total": len(entries), "by_action": _count_actions(entries)}
        print(json.dumps(payload, indent=2))
        # Documented contract: 0 = no differences, 1 = differences found. A
        # `diff` that always exits 0 can never fail a CI gate that wants it to.
        return EXIT_DRIFT if entries else EXIT_OK

    if args.format == "sarif":
        raise UsageError("sarif output is only available for `scan`")

    lines = [f"Comparing {source.name} -> {target.name}", ""]
    if not entries:
        lines.append("No differences.")
    for entry in entries:
        line = entry.render()
        if mask:
            line = _mask_rendered(line, entry)
        lines.append(line)
    print("\n".join(lines))
    return EXIT_DRIFT if entries else EXIT_OK


def _count_actions(entries) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.action] = counts.get(entry.action, 0) + 1
    return dict(sorted(counts.items()))


def _safe_entry(entry, mask: bool) -> dict[str, object]:
    payload = entry.as_dict()
    if not mask:
        return payload
    payload["value_a"] = None if payload["value_a"] is None else mask_value(entry.key, payload["value_a"])
    payload["value_b"] = None if payload["value_b"] is None else mask_value(entry.key, payload["value_b"])
    return payload


def _mask_rendered(line: str, entry) -> str:
    """Replace the rendered value with the mask, for text diff lines."""
    if entry.action == "changed":
        safe_a = mask_value(entry.key, entry.value_a or "")
        safe_b = mask_value(entry.key, entry.value_b or "")
        return f"~ {entry.key}: {safe_a} -> {safe_b}"
    value = entry.value_b if entry.action == "added" else entry.value_a
    safe = mask_value(entry.key, value or "")
    symbol = line[0]
    return f"{symbol} {entry.key}={safe}"


def _cmd_list(args: argparse.Namespace) -> int:
    target = _target_dir(args)
    root = Path(target).resolve()
    if not root.is_dir():
        raise UsageError(f"not a directory: {target}")
    try:
        config = load_config(root, Path(args.config) if args.config else None)
    except ConfigError as exc:
        raise UsageError(str(exc)) from exc

    files = discover_env_files(root, exclude=config.exclude_files)
    if not files:
        raise UsageError(f"no .env files found under {root}")
    for env_file in files:
        print(f"{env_file.name}\t{env_file.path.relative_to(root)}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {"scan": _cmd_scan, "diff": _cmd_diff, "list": _cmd_list}
    try:
        return handlers[args.command](args)
    except UsageError as exc:
        print(f"env-drift: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
