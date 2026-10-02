"""Regression tests for defects found in review of the bootstrap implementation.

Each test here pins a bug that the original 140-test suite did not cover --
in four cases the suite asserted the *buggy* behaviour, so the CI matrix being
green proved nothing about them.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from env_drift.config import Config, ConfigError, load_config
from env_drift.discovery import discover_env_files
from env_drift.expand import expand_all
from env_drift.masking import REDACTED, mask_value
from env_drift.parser import parse_text
from env_drift.report import render_sarif
from env_drift.scanner import EnvSnapshot, load_snapshots, scan

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


# --- pending_removal must survive a third environment ----------------------


def test_pending_removal_is_reported_with_three_environments():
    """The 3-environment case the README documents.

    ``LEGACY`` is live in development and staging and commented out in
    production. The pending-removal check was gated behind
    ``len(defined_in) < 2``, so as soon as a key was live in *two* environments
    the check was skipped and only the weaker ``missing_key_in_env`` finding
    survived -- the actionable fact, that the removal was started but never
    finished, was lost exactly when there were more environments to compare.
    """
    development = EnvSnapshot("development", {"A": "1", "LEGACY": "1"}, ())
    staging = EnvSnapshot("staging", {"A": "1", "LEGACY": "1"}, ())
    production = EnvSnapshot("production", {"A": "1"}, ("LEGACY",))

    found = [
        d for d in scan([development, staging, production], Config())
        if d.drift_type == "pending_removal"
    ]
    assert [d.key for d in found] == ["LEGACY"]
    assert found[0].severity == "warning"
    assert "production" in found[0].message
    assert "development" in found[0].message


def test_pending_removal_still_absent_when_the_key_is_live_in_every_env():
    """The other side of the guard: a key that is live everywhere is not
    pending removal, however many environments there are."""
    snapshots = [
        EnvSnapshot("development", {"A": "1"}, ()),
        EnvSnapshot("staging", {"A": "1"}, ()),
        EnvSnapshot("production", {"A": "1"}, ()),
    ]
    assert [d for d in scan(snapshots, Config()) if d.drift_type == "pending_removal"] == []


def test_pending_removal_survives_the_cli_with_three_environments(tmp_path):
    """End-to-end, so the finding cannot be lost between scanner and report."""
    (tmp_path / ".env.development").write_text("A=1\nLEGACY=1\n", encoding="utf-8")
    (tmp_path / ".env.staging").write_text("A=1\nLEGACY=1\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("A=1\n#LEGACY=1\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "env_drift", "scan", "--format", "json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    assert "pending_removal" in payload["summary"]["by_type"]


# --- a corrupted ignore file is a config error, not drift -------------------


def test_undecodable_ignore_file_is_a_config_error_not_drift(tmp_path):
    """`.env-driftignore` that is not valid UTF-8 must exit 2.

    A traceback here exits 1, which the CLI documents as "drift detected": CI
    would go red over a broken ignore file and red for the wrong reason, and
    the drift it never reported would be invisible.
    """
    (tmp_path / ".env.development").write_text("A=1\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("A=1\n", encoding="utf-8")
    (tmp_path / ".env-driftignore").write_bytes(b"LEGACY_\xff\xfe\n")
    result = subprocess.run(
        [sys.executable, "-m", "env_drift", "scan"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    assert "UnicodeDecodeError" not in result.stderr
    assert "Traceback" not in result.stderr


def test_load_config_rejects_an_undecodable_ignore_file(tmp_path):
    (tmp_path / ".env-driftignore").write_bytes(b"LEGACY_\xff\xfe\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


# --- SARIF locations must point at the file that drifted -------------------


def test_sarif_uri_is_repo_relative_and_names_the_drifting_file(tmp_path):
    """Code scanning resolves ``uri`` against ``uriBaseId`` (``%SRCROOT%``).

    Every location used to carry the resolved root directory as an absolute
    path, so every alert landed on the repo root instead of the env file that
    actually drifted, and the absolute prefix defeated the base id entirely.
    """
    (tmp_path / ".env.development").write_text("A=1\nONLY_DEV=x\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("A=1\n", encoding="utf-8")
    files = discover_env_files(tmp_path)
    drifts = scan(load_snapshots(files), Config())

    document = json.loads(render_sarif(drifts, environments=[f.name for f in files], root=tmp_path))
    results = document["runs"][0]["results"]
    assert results
    for result in results:
        location = result["locations"][0]["physicalLocation"]["artifactLocation"]
        uri = location["uri"]
        assert not uri.startswith("/"), f"SARIF uri must be repo-relative, got {uri!r}"
        assert uri == ".env.development", f"expected the drifting file, got {uri!r}"


def test_sarif_uri_of_a_nested_env_file_is_relative_to_the_root(tmp_path):
    """A file in a subdirectory keeps its directory prefix, minus the root."""
    (tmp_path / "services" / "api").mkdir(parents=True)
    (tmp_path / "services" / "api" / ".env.development").write_text("A=1\nONLY=x\n", encoding="utf-8")
    (tmp_path / "services" / "api" / ".env.production").write_text("A=1\n", encoding="utf-8")
    files = discover_env_files(tmp_path)
    drifts = scan(load_snapshots(files), Config())

    document = json.loads(render_sarif(drifts, environments=[f.name for f in files], root=tmp_path))
    uris = {
        r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        for r in document["runs"][0]["results"]
    }
    assert uris == {"services/api/.env.development"}
    for uri in uris:
        assert not uri.startswith("/")
        assert str(tmp_path) not in uri