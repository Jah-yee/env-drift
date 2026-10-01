"""Tests for secret masking in output (credential-leak prevention)."""

from env_drift.masking import REDACTED, is_secret_key, mask_value, mask_values

SECRET_KEYS = [
    "SECRET_KEY",
    "API_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "DB_PASSWORD",
    "SERVICE_CREDENTIALS",
    "STRIPE_SECRET_KEY",
]


def test_secret_keys_are_recognised():
    for key in SECRET_KEYS:
        assert is_secret_key(key) is True, key


def test_non_secret_keys_are_not_recognised_as_secret():
    for key in ["PORT", "DEBUG", "LOG_LEVEL", "APP_NAME", "RETRY_COUNT", "HOSTNAME"]:
        assert is_secret_key(key) is False, key


def test_secret_value_is_replaced_entirely():
    assert mask_value("API_TOKEN", "abc123xyz") == REDACTED


def test_non_secret_value_is_untouched():
    assert mask_value("PORT", "3000") == "3000"


def test_masking_is_case_insensitive():
    assert mask_value("api_token", "abc") == REDACTED


def test_masking_never_leaks_a_fragment_of_the_secret():
    masked = mask_value("DATABASE_URL", "postgres://user:hunter2@host/db")
    assert masked == REDACTED
    assert "hunter2" not in masked


def test_mask_values_masks_only_the_secret_keys():
    values = {"PORT": "3000", "API_TOKEN": "abc", "DEBUG": "true"}
    assert mask_values(values) == {"PORT": "3000", "API_TOKEN": REDACTED, "DEBUG": "true"}


def test_url_with_inline_credentials_is_masked_by_value_shape():
    # A DATABASE_URL that embeds a password is a secret even under a bland key.
    values = {"DATABASE_URL": "postgres://user:hunter2@host/db"}
    assert "hunter2" not in mask_values(values)["DATABASE_URL"]


def test_masking_an_empty_value_is_a_no_op():
    assert mask_value("EMPTY", "") == ""
