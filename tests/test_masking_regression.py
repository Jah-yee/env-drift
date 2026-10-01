"""Regression test: masking must key off the variable name, not the env name.

A real run printed ``SECRET_KEY=only-in-prod-abc`` in clear text because the
renderer masked with the environment name ("production") instead of the key
("SECRET_KEY"). ``DATABASE_URL`` escaped notice in the same run only because its
*value* looks like a URL with embedded credentials, which is a second,
independent trigger -- so a name-based secret is exactly the case that slips
through. This test pins the variable name as the mask key.
"""

from env_drift.masking import REDACTED, mask_values
from env_drift.report import build_payload, render_text
from env_drift.scanner import EnvDrift


def test_secret_is_masked_even_when_the_env_name_is_innocent():
    drift = EnvDrift(
        key="SECRET_KEY",
        drift_type="orphaned_key",
        severity="error",
        message="'SECRET_KEY' exists only in production",
        environments={"production": "only-in-prod-abc"},
    )
    for text in (
        render_text([drift]),
        str(build_payload([drift], ["development", "production"])),
    ):
        assert "only-in-prod-abc" not in text, text


def test_masking_by_name_covers_values_that_look_innocent():
    values = {"SECRET_KEY": "plain-words-no-url", "API_TOKEN": "abc", "PORT": "3000"}
    assert mask_values(values) == {
        "SECRET_KEY": REDACTED,
        "API_TOKEN": REDACTED,
        "PORT": "3000",
    }


def test_every_json_environment_value_goes_through_the_masker():
    drift = EnvDrift(
        key="AWS_ACCESS_KEY_ID",
        drift_type="divergent_secret",
        severity="error",
        message="differs",
        environments={"production": "AKIAIOSFODNN7EXAMPLE"},
    )
    payload = build_payload([drift], ["production"])
    assert payload["results"][0]["environments"]["production"] == REDACTED
