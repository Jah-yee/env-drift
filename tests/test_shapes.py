"""Tests for value-shape classification."""

from env_drift.shapes import shape_of


def test_boolean_spellings():
    for value in ["true", "FALSE", "yes", "No", "on", "OFF"]:
        assert shape_of(value) == "boolean", value


def test_integers_and_floats():
    assert shape_of("3000") == "integer"
    assert shape_of("-42") == "integer"
    assert shape_of("0.5") == "float"
    assert shape_of("1e3") == "float"


def test_url():
    assert shape_of("postgres://host/db") == "url"
    assert shape_of("redis://cache:6379") == "url"


def test_paths():
    assert shape_of("/var/lib/app") == "path"
    assert shape_of("./config.yml") == "path"


def test_json_object():
    assert shape_of('{"a": 1}') == "json"


def test_plain_string():
    assert shape_of("production") == "string"
    assert shape_of("30s") == "string"


def test_empty_is_its_own_shape():
    assert shape_of("") == "empty"
