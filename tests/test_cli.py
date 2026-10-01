"""End-to-end tests for the env-drift CLI, run as real subprocesses.

These deliberately invoke the installed console script instead of calling
``main()`` in-process: the exit code is the tool's contract in CI, and an
in-process test cannot see it.
"""

import json
import subprocess
import sys

import pytest

DEV = """\
# development
DEBUG=true
PORT=3000
DATABASE_URL=postgres://app:s3cr3t-dev@dev-db.internal:5432/app
API_HOST=api.internal
"""

# Same value as DEV except:
#   * DEBUG=True instead of DEBUG=true  -> format_mismatch (casing)
#   * a different DATABASE_URL         -> divergent_secret (declared shared)
PROD = """\
DEBUG=True
PORT=3000
DATABASE_URL=postgres://app:s3cr3t-prod@prod-db.internal:5432/app
API_HOST=api.internal
"""

# Identical to PROD except every value agrees with DEV.
CLEAN_PROD = """\
DEBUG=false
PORT=3000
DATABASE_URL=postgres://app:s3cr3t-dev@dev-db.internal:5432/app
API_HOST=api.internal
"""

CONFIG = '[env-drift]\nshared-keys = ["DATABASE_URL"]\n'


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".env.development").write_text(DEV, encoding="utf-8")
    (tmp_path / ".env.production").write_text(PROD, encoding="utf-8")
    (tmp_path / ".env-drift.toml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


def run(*args, cwd, expect=None):
    result = subprocess.run(
        [sys.executable, "-m", "env_drift", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if expect is not None:
        assert result.returncode == expect, (
            f"expected exit {expect}, got {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def test_help_exits_zero(project):
    result = run("--help", cwd=project, expect=0)
    assert "scan" in result.stdout


def test_clean_project_exits_zero(tmp_path):
    (tmp_path / ".env.development").write_text(DEV, encoding="utf-8")
    (tmp_path / ".env.production").write_text(CLEAN_PROD, encoding="utf-8")
    result = run("scan", cwd=tmp_path, expect=0)
    assert "No drift detected" in result.stdout


def test_value_difference_without_a_shared_key_is_not_drift(tmp_path):
    # DEBUG true -> false is the entire point of separate env files.
    (tmp_path / ".env.development").write_text("DEBUG=true\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("DEBUG=false\n", encoding="utf-8")
    run("scan", cwd=tmp_path, expect=0)


def test_drift_exits_one_and_names_the_key(project):
    result = run("scan", cwd=project, expect=1)
    assert "divergent_secret" in result.stdout
    assert "DATABASE_URL" in result.stdout


def test_casing_difference_is_reported_as_format_mismatch(project):
    result = run("scan", cwd=project, expect=1)
    assert "format_mismatch" in result.stdout


def test_json_output_is_parseable(project):
    result = run("scan", "--format", "json", cwd=project, expect=1)
    payload = json.loads(result.stdout)
    assert payload["tool"]["name"] == "env-drift"
    assert payload["environments"] == ["development", "production"]
    assert any(r["key"] == "DATABASE_URL" for r in payload["results"])


def test_sarif_output_is_parseable(project):
    result = run("scan", "--format", "sarif", cwd=project, expect=1)
    payload = json.loads(result.stdout)
    assert payload["version"] == "2.1.0"
    assert payload["runs"][0]["results"]


def test_secrets_are_masked_by_default(project):
    result = run("scan", "--format", "json", cwd=project, expect=1)
    assert "s3cr3t" not in result.stdout


def test_secrets_appear_only_with_show_secrets(project):
    result = run("scan", "--format", "json", "--show-secrets", cwd=project, expect=1)
    assert "s3cr3t-prod" in result.stdout


def test_no_env_files_exits_two(tmp_path):
    result = run("scan", cwd=tmp_path, expect=2)
    assert "no .env files" in (result.stderr + result.stdout).lower()


def test_bad_config_exits_two(tmp_path):
    (tmp_path / ".env.development").write_text(DEV, encoding="utf-8")
    (tmp_path / ".env.production").write_text(PROD, encoding="utf-8")
    (tmp_path / ".env-drift.toml").write_text("[env-drift\nbroken", encoding="utf-8")
    result = run("scan", cwd=tmp_path, expect=2)
    assert "config" in (result.stderr + result.stdout).lower()


def test_invalid_format_is_rejected(project):
    result = run("scan", "--format", "xml", cwd=project)
    assert result.returncode == 2


def test_missing_config_path_exits_two(project):
    result = run("scan", "--config", "nope.toml", cwd=project, expect=2)
    assert "config file not found" in (result.stderr + result.stdout).lower()


def test_diff_shows_added_removed_and_changed(tmp_path):
    (tmp_path / ".env.dev").write_text("A=1\nB=2\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("A=1\nC=3\n", encoding="utf-8")
    result = run("diff", "dev", "prod", cwd=tmp_path, expect=1)
    assert "- B=2" in result.stdout
    assert "+ C=3" in result.stdout


def test_diff_marks_changed_values(tmp_path):
    (tmp_path / ".env.dev").write_text("A=1\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("A=2\n", encoding="utf-8")
    result = run("diff", "dev", "prod", cwd=tmp_path, expect=1)
    assert "~ A: 1 -> 2" in result.stdout


def test_diff_json_has_action_field(tmp_path):
    (tmp_path / ".env.dev").write_text("A=1\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("A=2\n", encoding="utf-8")
    result = run("diff", "dev", "prod", "--format", "json", cwd=tmp_path, expect=1)
    payload = json.loads(result.stdout)
    assert payload["diff"][0]["action"] == "changed"


def test_diff_of_identical_envs_exits_zero_and_says_no_changes(tmp_path):
    (tmp_path / ".env.dev").write_text("A=1\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("A=1\n", encoding="utf-8")
    result = run("diff", "dev", "prod", cwd=tmp_path, expect=0)
    assert "No differences" in result.stdout


def test_diff_with_unknown_environment_exits_two(tmp_path):
    (tmp_path / ".env.dev").write_text("A=1\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("A=2\n", encoding="utf-8")
    result = run("diff", "dev", "nope", cwd=tmp_path, expect=2)
    assert "unknown environment" in (result.stderr + result.stdout).lower()


def test_diff_masks_secrets(tmp_path):
    (tmp_path / ".env.dev").write_text("API_TOKEN=abc123\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("API_TOKEN=def456\n", encoding="utf-8")
    result = run("diff", "dev", "prod", cwd=tmp_path, expect=1)
    assert "abc123" not in result.stdout
    assert "def456" not in result.stdout
    assert "***REDACTED***" in result.stdout


def test_list_shows_discovered_environments(project):
    result = run("list", cwd=project, expect=0)
    assert "development" in result.stdout
    assert "production" in result.stdout


def test_config_declaring_shared_keys_silences_the_finding(tmp_path):
    (tmp_path / ".env.development").write_text("LOG_LEVEL=info\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("LOG_LEVEL=debug\n", encoding="utf-8")
    assert run("scan", cwd=tmp_path).returncode == 0
    (tmp_path / ".env-drift.toml").write_text(
        '[env-drift]\nshared-keys = ["LOG_LEVEL"]\n', encoding="utf-8"
    )
    result = run("scan", cwd=tmp_path, expect=1)
    assert "divergent_secret" in result.stdout


def test_driftignore_suppresses_a_key(tmp_path):
    (tmp_path / ".env.development").write_text("DEBUG=true\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("DEBUG=True\n", encoding="utf-8")
    assert run("scan", cwd=tmp_path).returncode == 1
    (tmp_path / ".env-driftignore").write_text("DEBUG\n", encoding="utf-8")
    assert run("scan", cwd=tmp_path, expect=0).returncode == 0


def test_strict_turns_warnings_into_a_failure(tmp_path):
    (tmp_path / ".env.development").write_text("A=1\nONLY_DEV=x\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("A=1\n", encoding="utf-8")
    assert run("scan", cwd=tmp_path, expect=0).returncode == 0
    assert run("scan", "--strict", cwd=tmp_path, expect=1).returncode == 1


def test_required_in_prod_turns_missing_into_an_error(tmp_path):
    (tmp_path / ".env.development").write_text("A=1\nB=1\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("A=1\n", encoding="utf-8")
    (tmp_path / ".env.staging").write_text("A=1\nB=1\n", encoding="utf-8")
    (tmp_path / ".env-drift.toml").write_text(
        '[env-drift]\nrequired-in-prod = ["B"]\n', encoding="utf-8"
    )
    result = run("scan", "--format", "json", cwd=tmp_path, expect=1)
    payload = json.loads(result.stdout)
    missing = next(r for r in payload["results"] if r["key"] == "B")
    assert missing["severity"] == "error"


def test_scan_can_target_a_single_environment_directory(tmp_path):
    services = tmp_path / "services" / "api"
    services.mkdir(parents=True)
    (services / ".env.development").write_text(DEV, encoding="utf-8")
    (services / ".env.production").write_text(PROD, encoding="utf-8")
    # No .env-drift.toml in that subtree, so only the casing drift is found --
    # the point here is that --dir scopes the scan to the given directory.
    result = run("scan", "--dir", str(services), cwd=tmp_path, expect=1)
    assert "Comparing environments: development, production" in result.stdout
    assert "format_mismatch" in result.stdout
