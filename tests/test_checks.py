"""Tests for format mismatch, empty values, and pending removal checks."""

from env_drift.config import Config
from env_drift.discovery import discover_env_files
from env_drift.scanner import EnvSnapshot, load_snapshots, scan


def only(drifts, drift_type):
    return [d for d in drifts if d.drift_type == drift_type]


def test_same_key_different_value_format_is_reported():
    a = EnvSnapshot("dev", {"DEBUG": "true"}, ())
    b = EnvSnapshot("prod", {"DEBUG": "True"}, ())
    found = only(scan([a, b], Config()), "format_mismatch")
    assert len(found) == 1
    assert found[0].severity == "error"


def test_format_mismatch_message_names_both_shapes():
    a = EnvSnapshot("dev", {"TIMEOUT": "30"}, ())
    b = EnvSnapshot("prod", {"TIMEOUT": "30s"}, ())
    message = only(scan([a, b], Config()), "format_mismatch")[0].message
    assert "dev=integer" in message
    assert "prod=string" in message


def test_same_shape_different_value_is_not_a_format_mismatch():
    a = EnvSnapshot("dev", {"DEBUG": "true"}, ())
    b = EnvSnapshot("prod", {"DEBUG": "false"}, ())
    assert only(scan([a, b], Config()), "format_mismatch") == []


def test_number_versus_url_is_a_format_mismatch():
    a = EnvSnapshot("dev", {"TIMEOUT": "30"}, ())
    b = EnvSnapshot("prod", {"TIMEOUT": "https://x/30"}, ())
    assert len(only(scan([a, b], Config()), "format_mismatch")) == 1


def test_empty_value_where_another_env_has_one_is_reported():
    a = EnvSnapshot("dev", {"LOG_LEVEL": "debug"}, ())
    b = EnvSnapshot("prod", {"LOG_LEVEL": ""}, ())
    found = only(scan([a, b], Config()), "empty_value")
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].environments["prod"] == ""


def test_empty_required_value_is_an_error():
    a = EnvSnapshot("dev", {"LOG_LEVEL": "debug"}, ())
    b = EnvSnapshot("prod", {"LOG_LEVEL": ""}, ())
    found = only(scan([a, b], Config(required_keys=("LOG_LEVEL",))), "empty_value")
    assert found[0].severity == "error"


def test_key_empty_in_every_environment_is_not_reported_as_empty_drift():
    a = EnvSnapshot("dev", {"LOG_LEVEL": ""}, ())
    b = EnvSnapshot("prod", {"LOG_LEVEL": ""}, ())
    assert only(scan([a, b], Config()), "empty_value") == []


def test_commented_key_live_elsewhere_is_pending_removal():
    a = EnvSnapshot("dev", {"LEGACY": "1", "A": "1"}, ())
    b = EnvSnapshot("prod", {"A": "1"}, ("LEGACY",))
    found = only(scan([a, b], Config()), "pending_removal")
    assert len(found) == 1
    assert found[0].key == "LEGACY"
    assert found[0].severity == "warning"
    assert "prod" in found[0].message


def test_key_active_in_all_envs_is_not_pending_removal():
    a = EnvSnapshot("dev", {"A": "1"}, ())
    b = EnvSnapshot("prod", {"A": "1"}, ("A",))
    assert only(scan([a, b], Config()), "pending_removal") == []


def test_a_single_key_can_produce_several_independent_findings():
    a = EnvSnapshot("dev", {"A": "1", "X": "1"}, ())
    b = EnvSnapshot("prod", {"A": "1"}, ("X",))
    findings = scan([a, b], Config())
    assert sorted(d.drift_type for d in findings) == ["orphaned_key", "pending_removal"]
    assert {d.key for d in findings} == {"X"}


def test_expanded_values_are_compared_not_their_references(tmp_path):
    # End-to-end through the real parse -> discover -> load -> scan chain:
    # the reported values must be resolved, not the raw "${HOST}/v1" text.
    (tmp_path / ".env.dev").write_text(
        "HOST=shared.example\nAPI=${HOST}/v1\n", encoding="utf-8"
    )
    (tmp_path / ".env.prod").write_text(
        "HOST=shared.example\nAPI=${HOST}/v2\n", encoding="utf-8"
    )
    files = discover_env_files(tmp_path)
    drifts = scan(load_snapshots(files), Config(shared_keys=("API",)))
    found = only(drifts, "divergent_secret")
    assert found[0].environments == {"dev": "shared.example/v1", "prod": "shared.example/v2"}


def test_shape_mismatch_ignores_value_expansion_differences():
    # A=${BASE}/x where BASE is a url in both envs stays the same shape.
    a = EnvSnapshot("dev", {"BASE": "https://a", "API": "${BASE}/x"}, ())
    b = EnvSnapshot("prod", {"BASE": "https://b", "API": "${BASE}/x"}, ())
    assert only(scan([a, b], Config()), "format_mismatch") == []
