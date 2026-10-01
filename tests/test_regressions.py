"""Regression tests for defects found in review of the bootstrap implementation.

Each test here pins a bug that the original 140-test suite did not cover --
in four cases the suite asserted the *buggy* behaviour, so the CI matrix being
green proved nothing about them.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from env_drift.expand import expand_all
from env_drift.masking import REDACTED, mask_value
from env_drift.parser import parse_text

# --- parser: a quoted value followed by a trailing comment -----------------


def test_quoted_value_with_trailing_comment_drops_the_comment():
    # The closing quote, not the last character, is what marks a value as
    # quoted. Comparing first against last kept the quotes in the value.
    values = parse_text('A="hello" # released in v2\n').values
    assert values["A"] == "hello"


def test_single_quoted_value_with_trailing_comment():
    assert parse_text("A='x' # note\n").values["A"] == "x"


def test_quoted_value_without_comment_is_unchanged():
    assert parse_text('A="hello"\n').values["A"] == "hello"


def test_quoted_value_containing_a_hash_is_not_a_comment():
    assert parse_text('A="be#ef"\n').values["A"] == "be#ef"


# --- parser: a value may legitimately begin with '#' ----------------------


def test_value_starting_with_hash_is_not_truncated():
    # Hex colours, fragments and shell anchors all start with '#'.
    assert parse_text("COLOR=#ff0000\n").values["COLOR"] == "#ff0000"


def test_trailing_hash_only_comment_is_still_stripped():
    assert parse_text("A=value # note\n").values["A"] == "value"


def test_hash_without_preceding_whitespace_is_kept():
    assert parse_text("A=plain#not-a-comment\n").values["A"] == "plain#not-a-comment"


def test_url_fragment_is_not_truncated():
    assert parse_text("U=https://x/#anchor\n").values["U"] == "https://x/#anchor"


# --- masking: credentials with an empty username --------------------------


@pytest.mark.parametrize(
    "value",
    [
        "postgres://:s3cret@db.internal:5432/app",
        "postgres://user:@db/app",
        "amqp://:pw@host/vhost",
    ],
)
def test_url_credentials_are_masked_even_with_an_empty_username(value):
    # `postgres://:s3cret@db/app` is a common Docker form; the previous regex
    # required at least one character on each side of the colon, so the
    # password reached the output unmasked.
    assert mask_value("DATABASE_URL", value) == REDACTED


def test_url_without_credentials_is_not_masked():
    assert mask_value("API_HOST", "https://api.internal:8443/v1") != REDACTED


# --- expansion must not run twice -----------------------------------------


def test_escaped_dollar_resolves_to_a_literal_dollar_sign():
    # `\$` is the escape for a literal dollar sign, so exactly one pass turns it
    # into `$`. Note that `expand_all` is deliberately NOT idempotent -- a
    # second pass would resolve that literal `$` -- which is why
    # `EnvSnapshot` carries an `expanded` flag and the scanner never expands
    # the same values twice.
    assert expand_all({"LITERAL": r"\$HOME", "HOME": "/root"})["LITERAL"] == "$HOME"


def test_scanner_expands_hand_built_snapshots_exactly_once():
    """Snapshots built by hand still resolve references, and only once."""
    from env_drift.config import Config
    from env_drift.scanner import EnvSnapshot, scan

    snapshots = [
        EnvSnapshot(name="development", values={"LITERAL": r"\$HOME", "HOME": "/root"}),
        EnvSnapshot(name="production", values={"LITERAL": r"\$HOME", "HOME": "/other"}),
    ]
    drifts = scan(snapshots, Config())
    assert not [d for d in drifts if d.key == "LITERAL"]


def test_expansion_still_resolves_real_references():
    assert expand_all({"A": "$B", "B": "value"})["A"] == "value"


def test_expansion_is_not_run_twice_by_the_scanner(tmp_path):
    """The end-to-end symptom: two identical escaped values must not drift."""
    (tmp_path / ".env.development").write_text(
        "LITERAL=\\$TEMPLATE\nHOME=/root\n", encoding="utf-8"
    )
    (tmp_path / ".env.production").write_text(
        "LITERAL=\\$TEMPLATE\nHOME=/other\n", encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, "-m", "env_drift", "scan", "--format", "json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "LITERAL" not in result.stdout


# --- the `diff` exit code is part of the documented contract --------------


def test_diff_exits_one_when_there_are_differences(tmp_path):
    (tmp_path / ".env.dev").write_text("A=1\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("A=2\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "env_drift", "diff", "dev", "prod"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    # A `diff` that always exits 0 can never fail the CI gate that wants it.
    assert result.returncode == 1


def test_diff_exits_zero_when_there_are_no_differences(tmp_path):
    (tmp_path / ".env.dev").write_text("A=1\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("A=1\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "env_drift", "diff", "dev", "prod"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


# --- duplicate environment names must not silently drop a file -------------


def test_diff_rejects_an_ambiguous_environment_name(tmp_path):
    (tmp_path / "svc-a").mkdir()
    (tmp_path / "svc-b").mkdir()
    (tmp_path / ".env.dev").write_text("A=1\n", encoding="utf-8")
    (tmp_path / "svc-a" / ".env.prod").write_text("A=2\n", encoding="utf-8")
    (tmp_path / "svc-b" / ".env.prod").write_text("A=3\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "env_drift", "diff", "dev", "prod"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    # Previously the dict comprehension kept only the last match, so the
    # caller silently got a diff of a file they never named.
    assert result.returncode == 2
    assert "ambiguous" in (result.stderr + result.stdout).lower()