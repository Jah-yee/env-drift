"""Tests for discovery of environment files in a project tree."""

from env_drift.discovery import discover_env_files


def make(tmp_path, name, content=""):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_discovers_dotenv_files_and_derives_env_names(tmp_path):
    make(tmp_path, ".env.development")
    make(tmp_path, ".env.production")
    found = discover_env_files(tmp_path)
    assert [f.name for f in found] == ["development", "production"]


def test_bare_dotenv_is_named_default(tmp_path):
    make(tmp_path, ".env")
    assert [f.name for f in discover_env_files(tmp_path)] == ["default"]


def test_discovers_local_suffix_pattern(tmp_path):
    make(tmp_path, ".env.production.local")
    assert [f.name for f in discover_env_files(tmp_path)] == ["production.local"]


def test_example_and_template_files_are_excluded(tmp_path):
    make(tmp_path, ".env.development")
    make(tmp_path, ".env.example")
    make(tmp_path, ".env.template")
    found = discover_env_files(tmp_path)
    assert [f.name for f in found] == ["development"]


def test_extra_excludes_are_honoured(tmp_path):
    make(tmp_path, ".env.development")
    make(tmp_path, ".env.staging")
    found = discover_env_files(tmp_path, exclude=(".env.staging",))
    assert [f.name for f in found] == ["development"]


def test_non_dotenv_files_are_ignored(tmp_path):
    make(tmp_path, "README.md")
    make(tmp_path, "docker-compose.yml")
    make(tmp_path, ".env.development")
    assert [f.name for f in discover_env_files(tmp_path)] == ["development"]


def test_result_is_sorted_for_stable_output(tmp_path):
    for name in [".env.production", ".env.development", ".env.staging"]:
        make(tmp_path, name)
    assert [f.name for f in discover_env_files(tmp_path)] == [
        "development",
        "production",
        "staging",
    ]


def test_no_files_returns_empty_list(tmp_path):
    assert discover_env_files(tmp_path) == []


def test_hidden_directory_env_files_are_not_scanned(tmp_path):
    nested = tmp_path / ".venv"
    nested.mkdir()
    make(nested, ".env.production")
    make(tmp_path, ".env.development")
    assert [f.name for f in discover_env_files(tmp_path)] == ["development"]
