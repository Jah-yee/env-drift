"""Tests for the symmetric diff between two environments."""

from env_drift.diff import diff_snapshots
from env_drift.scanner import EnvSnapshot


def test_identical_environments_produce_no_entries():
    a = EnvSnapshot("dev", {"A": "1", "B": "2"}, ())
    b = EnvSnapshot("prod", {"A": "1", "B": "2"}, ())
    assert diff_snapshots(a, b) == []


def test_key_added_in_target_is_reported():
    a = EnvSnapshot("dev", {"A": "1"}, ())
    b = EnvSnapshot("prod", {"A": "1", "B": "2"}, ())
    entries = diff_snapshots(a, b)
    assert [(e.key, e.action) for e in entries] == [("B", "added")]
    assert entries[0].value_a is None
    assert entries[0].value_b == "2"


def test_key_removed_from_target_is_reported():
    a = EnvSnapshot("dev", {"A": "1", "B": "2"}, ())
    b = EnvSnapshot("prod", {"A": "1"}, ())
    entries = diff_snapshots(a, b)
    assert [(e.key, e.action) for e in entries] == [("B", "removed")]
    assert entries[0].value_a == "2"
    assert entries[0].value_b is None


def test_changed_value_reports_both_sides():
    a = EnvSnapshot("dev", {"DEBUG": "true"}, ())
    b = EnvSnapshot("prod", {"DEBUG": "false"}, ())
    entries = diff_snapshots(a, b)
    assert [(e.key, e.action) for e in entries] == [("DEBUG", "changed")]
    assert (entries[0].value_a, entries[0].value_b) == ("true", "false")


def test_diff_is_symmetric():
    a = EnvSnapshot("dev", {"A": "1", "B": "2"}, ())
    b = EnvSnapshot("prod", {"A": "9"}, ())
    forward = {(e.key, e.action) for e in diff_snapshots(a, b)}
    backward = {(e.key, e.action) for e in diff_snapshots(b, a)}
    assert forward == {("A", "changed"), ("B", "removed")}
    # Reversing the pair flips added/removed but never loses the key.
    assert backward == {("A", "changed"), ("B", "added")}


def test_entries_are_sorted_by_key():
    a = EnvSnapshot("dev", {"ZED": "1"}, ())
    b = EnvSnapshot("prod", {"ALPHA": "1", "MID": "1"}, ())
    assert [e.key for e in diff_snapshots(a, b)] == ["ALPHA", "MID", "ZED"]


def test_commented_out_key_in_target_is_pending_removal_not_removed():
    a = EnvSnapshot("dev", {"A": "1", "LEGACY": "x"}, ())
    b = EnvSnapshot("prod", {"A": "1"}, ("LEGACY",))
    entries = diff_snapshots(a, b)
    assert [(e.key, e.action) for e in entries] == [("LEGACY", "pending_removal")]
    assert entries[0].value_a == "x"


def test_re_enabling_a_commented_key_is_added():
    a = EnvSnapshot("dev", {"A": "1"}, ("FEATURE_FLAG",))
    b = EnvSnapshot("prod", {"A": "1", "FEATURE_FLAG": "on"}, ())
    assert [(e.key, e.action) for e in diff_snapshots(a, b)] == [("FEATURE_FLAG", "added")]


def test_entry_renders_as_a_diff_line():
    a = EnvSnapshot("dev", {"A": "1", "B": "2"}, ())
    b = EnvSnapshot("prod", {"A": "1", "C": "3"}, ())
    lines = [entry.render() for entry in diff_snapshots(a, b)]
    assert lines == ["- B=2", "+ C=3"]


def test_render_marks_changes_with_old_and_new():
    a = EnvSnapshot("dev", {"A": "1"}, ())
    b = EnvSnapshot("prod", {"A": "2"}, ())
    assert diff_snapshots(a, b)[0].render() == "~ A: 1 -> 2"


def test_diff_entry_serialises_for_json_output():
    import json

    a = EnvSnapshot("dev", {"A": "1"}, ())
    b = EnvSnapshot("prod", {"A": "2"}, ())
    payload = diff_snapshots(a, b)[0].as_dict()
    assert payload == {
        "key": "A",
        "action": "changed",
        "value_a": "1",
        "value_b": "2",
    }
    assert json.loads(json.dumps(payload))["action"] == "changed"
