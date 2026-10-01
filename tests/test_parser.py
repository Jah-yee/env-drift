"""Tests for the dotenv parser."""

from env_drift.parser import parse_text


def test_parses_simple_key_value_pairs():
    text = "DEBUG=true\nPORT=3000\n"
    assert parse_text(text).values == {"DEBUG": "true", "PORT": "3000"}


def test_ignores_blank_lines_and_comments():
    text = "\n# a comment\nDEBUG=true\n\n  # indented comment\nPORT=3000\n"
    assert parse_text(text).values == {"DEBUG": "true", "PORT": "3000"}


def test_strips_export_prefix():
    text = "export DEBUG=true\n"
    assert parse_text(text).values == {"DEBUG": "true"}


def test_strips_matching_quotes():
    text = 'A="hello world"\nB=\'single\'\n'
    assert parse_text(text).values == {"A": "hello world", "B": "single"}


def test_keeps_inner_quotes_and_comment_hash_inside_value():
    text = 'A="say #hi"\nB=plain#not-a-comment\n'
    assert parse_text(text).values == {"A": "say #hi", "B": "plain#not-a-comment"}


def test_empty_value_is_preserved_as_empty_string():
    assert parse_text("EMPTY=\n").values == {"EMPTY": ""}


def test_commented_only_key_is_recorded_as_pending_removal():
    parsed = parse_text("# LEGACY_FLAG=false\nDEBUG=true\n")
    assert parsed.values == {"DEBUG": "true"}
    assert parsed.commented_keys == ("LEGACY_FLAG",)


def test_active_key_is_not_also_reported_as_commented():
    parsed = parse_text("# DEBUG=false\nDEBUG=true\n")
    assert parsed.values == {"DEBUG": "true"}
    assert parsed.commented_keys == ()


def test_ignores_lines_that_are_not_assignments():
    parsed = parse_text("just some text\nDEBUG=true\n")
    assert parsed.values == {"DEBUG": "true"}


def test_later_assignment_wins():
    assert parse_text("A=1\nA=2\n").values == {"A": "2"}
