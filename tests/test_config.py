"""Tests for configuration loading and validation."""

import pytest

from env_drift.config import Config, ConfigError, load_config

MINIMAL = """\
[tool.env-drift]
shared-keys = ["DATABASE_URL"]
required-in-prod = ["SECRET_KEY"]
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_no_config_exists(tmp_path):
    config = load_config(tmp_path)
    assert config == Config()


def test_loads_from_standalone_toml(tmp_path):
    write(tmp_path, ".env-drift.toml", MINIMAL)
    config = load_config(tmp_path)
    assert config.shared_keys == ("DATABASE_URL",)
    assert config.required_in_prod == ("SECRET_KEY",)


def test_loads_from_pyproject_tool_table(tmp_path):
    write(tmp_path, "pyproject.toml", MINIMAL)
    assert load_config(tmp_path).shared_keys == ("DATABASE_URL",)


def test_explicit_path_wins_over_autodiscovery(tmp_path):
    write(tmp_path, "other.toml", '[env-drift]\nshared-keys = ["X"]\n')
    path = write(tmp_path, ".env-drift.toml", MINIMAL)
    assert load_config(tmp_path, path=path).shared_keys == ("DATABASE_URL",)


def test_exclude_files_is_read(tmp_path):
    write(tmp_path, ".env-drift.toml", '[env-drift]\nexclude-files = [".env.staging"]\n')
    assert load_config(tmp_path).exclude_files == (".env.staging",)


def test_prod_env_is_configurable(tmp_path):
    write(tmp_path, ".env-drift.toml", '[env-drift]\nprod-env = "live"\n')
    assert load_config(tmp_path).prod_env == "live"


def test_default_prod_env_is_production(tmp_path):
    assert load_config(tmp_path).prod_env == "production"


def test_missing_explicit_config_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path, path=tmp_path / "nope.toml")


def test_non_string_entry_is_rejected(tmp_path):
    write(tmp_path, ".env-drift.toml", '[env-drift]\nshared-keys = [1]\n')
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_malformed_toml_is_rejected(tmp_path):
    write(tmp_path, ".env-drift.toml", "[env-drift\nbroken")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_unknown_keys_are_ignored_not_fatal(tmp_path):
    write(tmp_path, ".env-drift.toml", '[env-drift]\nfuture-option = true\n')
    assert load_config(tmp_path) == Config()


def test_keys_are_deduplicated_and_order_preserved(tmp_path):
    write(tmp_path, ".env-drift.toml", '[env-drift]\nshared-keys = ["A", "B", "A"]\n')
    assert load_config(tmp_path).shared_keys == ("A", "B")


def test_ignored_keys_are_read(tmp_path):
    write(tmp_path, ".env-driftignore", "# comment\nDEBUG\nPORT\n\n")
    config = load_config(tmp_path)
    assert "DEBUG" in config.ignored_keys
    assert "PORT" in config.ignored_keys


def test_ignore_file_supports_glob_and_ignore_prefix(tmp_path):
    write(tmp_path, ".env-driftignore", "LEGACY_*\n!LEGACY_KEEP\n")
    config = load_config(tmp_path)
    assert "LEGACY_*" in config.ignored_keys
    assert "!LEGACY_KEEP" in config.ignored_keys
