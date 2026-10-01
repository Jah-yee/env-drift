"""Tests for shell-style variable expansion inside env values."""

from env_drift.expand import expand


def test_expands_braced_reference_from_same_file():
    values = {"API_HOST": "api.internal", "API_URL": "${API_HOST}/v1"}
    assert expand(values["API_URL"], values) == "api.internal/v1"


def test_expands_bare_reference():
    values = {"API_HOST": "api.internal", "API_URL": "$API_HOST/v1"}
    assert expand(values["API_URL"], values) == "api.internal/v1"


def test_expands_multiple_references_in_one_value():
    values = {"HOST": "h", "PORT": "8080", "URL": "${HOST}:${PORT}/api"}
    assert expand(values["URL"], values) == "h:8080/api"


def test_unknown_reference_is_left_untouched():
    values = {"URL": "${MISSING}/api"}
    assert expand(values["URL"], values) == "${MISSING}/api"


def test_recursive_expansion_resolves_chained_references():
    values = {"A": "root", "B": "${A}-b", "C": "${B}-c"}
    assert expand(values["C"], values) == "root-b-c"


def test_self_reference_does_not_loop_forever():
    values = {"A": "${A}"}
    assert expand(values["A"], values) == "${A}"


def test_escape_dollar_is_literal():
    values = {"URL": r"\${NOT_A_VAR}"}
    assert expand(values["URL"], values) == "${NOT_A_VAR}"


def test_expand_whole_mapping_returns_new_mapping():
    values = {"HOST": "h", "URL": "${HOST}/x"}
    assert expand_all(values) == {"HOST": "h", "URL": "h/x"}


from env_drift.expand import expand_all
