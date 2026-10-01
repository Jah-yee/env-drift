"""Tests for the core cross-environment drift scanner."""

from env_drift.config import Config
from env_drift.scanner import EnvSnapshot, scan

DEV = EnvSnapshot(
    name="development",
    values={"DEBUG": "true", "DATABASE_URL": "postgres://dev/app", "APP_NAME": "app"},
    commented_keys=(),
)
PROD = EnvSnapshot(
    name="production",
    values={"DEBUG": "false", "DATABASE_URL": "postgres://prod/app", "APP_NAME": "app"},
    commented_keys=(),
)


def types(drifts):
    return sorted(drift.drift_type for drift in drifts)


def only(drifts, drift_type):
    return [d for d in drifts if d.drift_type == drift_type]


def test_no_drift_when_identical():
    a = EnvSnapshot("dev", {"A": "1"}, ())
    b = EnvSnapshot("prod", {"A": "1"}, ())
    assert scan([a, b], Config()) == []


def test_value_differing_across_envs_is_not_drift_by_itself():
    # DEBUG=true in dev and DEBUG=false in prod is intentional, not drift.
    assert only(scan([DEV, PROD], Config()), "value_mismatch") == []


def test_missing_key_in_env_is_reported():
    a = EnvSnapshot("dev", {"A": "1", "B": "2"}, ())
    b = EnvSnapshot("staging", {"A": "1", "B": "2"}, ())
    c = EnvSnapshot("prod", {"A": "1"}, ())
    found = only(scan([a, b, c], Config()), "missing_key_in_env")
    assert len(found) == 1
    assert found[0].key == "B"
    assert found[0].severity == "warning"


def test_missing_key_records_the_environment_it_is_absent_from():
    a = EnvSnapshot("dev", {"A": "1", "B": "2"}, ())
    b = EnvSnapshot("staging", {"A": "1", "B": "2"}, ())
    c = EnvSnapshot("prod", {"A": "1"}, ())
    found = only(scan([a, b, c], Config()), "missing_key_in_env")[0]
    assert found.environments == {"dev": "2", "staging": "2", "prod": None}
    assert "prod" in found.message


def test_missing_required_key_is_an_error():
    a = EnvSnapshot("dev", {"A": "1", "SECRET_KEY": "s"}, ())
    b = EnvSnapshot("staging", {"A": "1", "SECRET_KEY": "s"}, ())
    c = EnvSnapshot("prod", {"A": "1"}, ())
    found = only(scan([a, b, c], Config(required_keys=("SECRET_KEY",))), "missing_key_in_env")
    assert found[0].severity == "error"


def test_missing_in_prod_from_required_in_prod_is_an_error():
    a = EnvSnapshot("development", {"A": "1", "SECRET_KEY": "s"}, ())
    b = EnvSnapshot("staging", {"A": "1", "SECRET_KEY": "s"}, ())
    c = EnvSnapshot("production", {"A": "1"}, ())
    config = Config(required_in_prod=("SECRET_KEY",))
    found = only(scan([a, b, c], config), "missing_key_in_env")
    assert found[0].severity == "error"


def test_required_key_absent_from_every_environment_is_still_an_error():
    a = EnvSnapshot("development", {"A": "1"}, ())
    b = EnvSnapshot("production", {"A": "1"}, ())
    config = Config(required_keys=("SECRET_KEY",))
    found = only(scan([a, b], config), "missing_key_in_env")
    assert [f.key for f in found] == ["SECRET_KEY"]
    assert found[0].severity == "error"


def test_key_present_in_exactly_one_env_is_reported_as_orphaned_not_missing():
    a = EnvSnapshot("dev", {"A": "1", "ONLY_DEV": "x"}, ())
    b = EnvSnapshot("prod", {"A": "1"}, ())
    findings = scan([a, b], Config())
    assert [f.drift_type for f in findings] == ["orphaned_key"]
    assert findings[0].key == "ONLY_DEV"


def test_orphaned_key_present_in_only_one_env_is_reported():
    a = EnvSnapshot("dev", {"A": "1", "ONLY_DEV": "x"}, ())
    b = EnvSnapshot("prod", {"A": "1"}, ())
    found = only(scan([a, b], Config()), "orphaned_key")
    assert [f.key for f in found] == ["ONLY_DEV"]
    assert found[0].severity == "warning"


def test_key_only_in_production_is_called_out_as_prod_only():
    a = EnvSnapshot("dev", {"A": "1"}, ())
    b = EnvSnapshot("production", {"A": "1", "SECRET_KEY": "s"}, ())
    found = only(scan([a, b], Config()), "orphaned_key")[0]
    assert found.key == "SECRET_KEY"
    assert "production" in found.message


def test_orphaned_required_key_is_an_error():
    a = EnvSnapshot("dev", {"A": "1", "SECRET_KEY": "s"}, ())
    b = EnvSnapshot("prod", {"A": "1"}, ())
    found = only(scan([a, b], Config(required_keys=("SECRET_KEY",))), "orphaned_key")
    assert found[0].severity == "error"


def test_shared_key_with_divergent_value_is_an_error():
    config = Config(shared_keys=("DATABASE_URL",))
    found = only(scan([DEV, PROD], config), "divergent_secret")
    assert len(found) == 1
    assert found[0].key == "DATABASE_URL"
    assert found[0].severity == "error"


def test_shared_key_identical_across_envs_is_not_reported():
    same = [
        EnvSnapshot("dev", {"LOG_LEVEL": "info"}, ()),
        EnvSnapshot("prod", {"LOG_LEVEL": "info"}, ()),
    ]
    assert only(scan(same, Config(shared_keys=("LOG_LEVEL",))), "divergent_secret") == []


def test_ignored_key_is_never_reported():
    a = EnvSnapshot("dev", {"DEBUG": "true", "ONLY_DEV": "x"}, ())
    b = EnvSnapshot("prod", {"DEBUG": "true"}, ())
    found = scan([a, b], Config(ignored_keys=("DEBUG", "ONLY_*")))
    assert found == []


def test_ignored_shared_key_suppresses_divergence():
    config = Config(shared_keys=("DATABASE_URL",), ignored_keys=("DATABASE_URL",))
    assert only(scan([DEV, PROD], config), "divergent_secret") == []


def test_single_environment_never_reports_missing_or_orphan():
    findings = scan([EnvSnapshot("dev", {"A": "1", "B": "2"}, ())], Config())
    assert findings == []


def test_findings_are_sorted_by_key():
    a = EnvSnapshot("dev", {"A": "1", "ZED": "9"}, ())
    b = EnvSnapshot("staging", {"A": "1", "ZED": "9"}, ())
    c = EnvSnapshot("prod", {"A": "1"}, ())
    assert [d.key for d in scan([a, b, c], Config())] == ["ZED"]
