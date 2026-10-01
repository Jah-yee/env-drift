"""Tests for text, JSON and SARIF rendering, including masking in every format."""

import json

from env_drift.report import (
    build_payload,
    render,
    render_json,
    render_sarif,
    render_text,
)
from env_drift.scanner import EnvDrift

DRIFT = EnvDrift(
    key="DATABASE_URL",
    drift_type="divergent_secret",
    severity="error",
    message="'DATABASE_URL' is declared as a shared key but its value differs",
    environments={"dev": "postgres://user:hunter2@dev/app", "prod": "postgres://user:hunter2@prod/app"},
)
WARNING = EnvDrift(
    key="DEBUG",
    drift_type="orphaned_key",
    severity="warning",
    message="'DEBUG' exists only in dev and in no other environment (prod)",
    environments={"dev": "true", "prod": None},
)


def test_text_lists_drift_type_and_severity():
    text = render_text([DRIFT])
    assert "divergent_secret" in text
    assert "error" in text


def test_text_reports_when_there_is_no_drift():
    assert "No drift detected" in render_text([])


def test_text_masks_secret_values():
    assert "hunter2" not in render_text([DRIFT])


def test_text_shows_plain_values_when_masking_is_disabled():
    text = render_text([DRIFT], mask=False)
    assert "hunter2" in text


def test_json_is_valid_json_with_expected_schema():
    payload = json.loads(render_json([DRIFT], root=__file__))
    assert payload["tool"]["name"] == "env-drift"
    assert payload["summary"]["total"] == 1
    result = payload["results"][0]
    assert result["key"] == "DATABASE_URL"
    assert result["drift_type"] == "divergent_secret"
    assert result["severity"] == "error"


def test_json_masks_secret_values():
    assert "hunter2" not in render_json([DRIFT], root=__file__)


def test_json_summary_counts_by_type_and_severity():
    payload = json.loads(render_json([DRIFT, WARNING], root=__file__))
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["errors"] == 1
    assert payload["summary"]["warnings"] == 1
    assert payload["summary"]["by_type"]["divergent_secret"] == 1


def test_sarif_is_a_valid_2_1_0_document():
    payload = json.loads(render_sarif([DRIFT], root=__file__))
    assert payload["version"] == "2.1.0"
    assert payload["$schema"] == (
        "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
    )
    assert payload["runs"][0]["tool"]["driver"]["name"] == "env-drift"


def test_sarif_reports_one_result_per_drift_with_a_rule():
    payload = json.loads(render_sarif([DRIFT, WARNING], root=__file__))
    run = payload["runs"][0]
    assert len(run["results"]) == 2
    assert run["results"][0]["ruleId"] == "divergent_secret"
    rules = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assert rules == {"divergent_secret", "orphaned_key"}


def test_sarif_maps_severity_to_level():
    payload = json.loads(render_sarif([DRIFT, WARNING], root=__file__))
    levels = [r["level"] for r in payload["runs"][0]["results"]]
    assert levels == ["error", "warning"]


def test_sarif_masks_secret_values():
    assert "hunter2" not in render_sarif([DRIFT], root=__file__)


def test_sarif_with_no_drift_is_still_a_valid_document():
    payload = json.loads(render_sarif([], root=__file__))
    assert payload["runs"][0]["results"] == []


def test_render_dispatches_on_format():
    assert render([DRIFT], "json", root=__file__).strip().startswith("{")
    assert render([DRIFT], "sarif", root=__file__).strip().startswith("{")
    assert "divergent_secret" in render([DRIFT], "text", root=__file__)


def test_render_rejects_an_unknown_format():
    import pytest

    with pytest.raises(ValueError):
        render([DRIFT], "xml", root=__file__)


def test_payload_includes_the_environments_that_were_compared():
    payload = build_payload([DRIFT], environments=["dev", "prod"], root=__file__)
    assert payload["environments"] == ["dev", "prod"]
