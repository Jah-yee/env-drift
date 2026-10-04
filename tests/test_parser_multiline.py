"""Multi-line quoted values, and the keys that must survive a stray quote.

``parse_text`` splits on ``splitlines()``, so a quoted value written across
physical lines used to be truncated at the first line and every later line
dropped as a stray non-assignment::

    KEY="first line
    second line"

reported ``KEY='"first line'`` and silently discarded ``second line``.

Closing that gap is easy to do destructively. The first attempt decided
"unclosed" by counting quote characters and then consumed following lines until
any matching quote appeared, never backtracking. On three ordinary lines that
heuristic reports an unclosed quote where there is none, and the accumulation
then ate every key after it::

    KEY="oops              -> KEY becomes '"oops\\nNEXT=keepme'; NEXT is gone
    KEY="v" # see "docs    -> the comment's quote reads as a false positive
    KEY="a \\" b"           -> the escaped quote reads as a false positive

That is the worse failure by far. env-drift's output is a comparison of key
sets, so a swallowed key does not look like a parse bug -- it is reported as
"exists only in production" for keys that are sitting in the file.

Each test below pins one behaviour, and the pair ``test_multiline_*`` /
``test_*_survives_a_stray_quote`` is what makes the set non-vacuous: the first
group fails on a tree without the fix, the second fails on a tree with a
naive one.
"""

from __future__ import annotations

import pytest

from env_drift.parser import parse_text

# --------------------------------------------------------------------------
# The behaviour being added: a quoted value spanning physical lines.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param('KEY="first line\nsecond line"\n', "first line\nsecond line", id="two_lines"),
        pytest.param('KEY="l1\nl2\nl3"\n', "l1\nl2\nl3", id="three_lines"),
        pytest.param("KEY='l1\nl2'\n", "l1\nl2", id="single_quotes"),
        pytest.param('KEY="a\n    b"\n', "a\n    b", id="indentation_preserved"),
    ],
)
def test_multiline_quoted_value_is_reassembled(text, expected):
    """The closing quote is on a later line; the value spans both.

    ``indentation_preserved`` pins that continuation lines are accumulated
    verbatim. Stripping each one as it is read rewrote ``"a\\n    b"`` to
    ``"a\\nb"`` -- a value the file never declared.
    """
    assert parse_text(text).values["KEY"] == expected


def test_keys_after_a_multiline_value_are_still_parsed():
    """The accumulation must resume at the line after the closing quote."""
    result = parse_text('KEY="first\nsecond"\nNEXT=keepme\n')

    assert result.values == {"KEY": "first\nsecond", "NEXT": "keepme"}


def test_unterminated_quote_at_eof_stays_literal():
    """A value still open when the file ends has no closing quote to find.

    EOF ends the accumulation, so the value falls through to the unterminated
    branch of ``_clean_value`` and keeps its opening quote -- the pre-existing
    fallback, unchanged.
    """
    result = parse_text('NEXT=keepme\nKEY="unterminated')

    assert result.values["NEXT"] == "keepme"
    assert result.values["KEY"] == '"unterminated'


# --------------------------------------------------------------------------
# The behaviour that must not regress: a stray quote must not eat the file.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_key"),
    [
        pytest.param('KEY="oops\nNEXT=keepme\n', '"oops', id="unbalanced_at_eol"),
        pytest.param('KEY="v" # see "docs\nNEXT=keepme\n', "v", id="quote_in_trailing_comment"),
        pytest.param('KEY="a \\" b"\nNEXT=keepme\n', "a \\", id="escaped_quote"),
    ],
)
def test_next_key_survives_a_stray_quote(text, expected_key):
    """One stray quote must cost at most its own key.

    All three lines have an odd number of quote characters, which is what a
    parity check calls an unclosed value. None of them is one: each has a
    closing quote that ``_clean_value`` already finds. When they were treated
    as continuations, ``NEXT`` vanished from the parse.
    """
    result = parse_text(text)

    assert result.values.get("NEXT") == "keepme", (
        "the key after a stray quote was absorbed into the previous value; "
        f"got {result.values!r}"
    )
    assert result.values["KEY"] == expected_key


def test_a_multi_line_value_does_not_swallow_a_whole_file():
    """End-to-end shape of the regression, on the tool's actual input.

    A single unbalanced quote at the top of one file turned two healthy files
    into a report claiming three keys were missing from development.
    """
    production = "SECRET=prod\nPORT=8080\nDEBUG=false\n"
    development = 'SECRET=dev\nPORT="8080\nDEBUG=false\n'

    prod = parse_text(production)
    dev = parse_text(development)

    assert set(prod.values) == set(dev.values) == {"SECRET", "PORT", "DEBUG"}
    assert prod.values["SECRET"] != dev.values["SECRET"], (
        "the fixture is meant to differ on exactly one key; if it does not, "
        "this test is no longer exercising the parse"
    )


def test_value_containing_a_hash_is_not_truncated():
    """``#`` inside quotes is content, not a comment opener."""
    result = parse_text('KEY="a # b"\nNEXT=keepme\n')

    assert result.values["KEY"] == "a # b"
    assert result.values["NEXT"] == "keepme"


def test_empty_quoted_value_does_not_consume_the_next_key():
    """``KEY=""`` has balanced quotes, so nothing should be accumulated."""
    result = parse_text('KEY=""\nNEXT=keepme\n')

    assert result.values["KEY"] == ""
    assert result.values["NEXT"] == "keepme"


def test_unquoted_value_is_never_treated_as_multiline():
    """Only a quote can open a multi-line value."""
    result = parse_text("KEY=plain\nNEXT=keepme\n")

    assert result.values == {"KEY": "plain", "NEXT": "keepme"}


def test_multiline_value_may_contain_a_trailing_comment_line():
    """A ``#`` line inside a quoted value is absorbed; it is not a key.

    The conservative continuation rule stops at blank lines, comment lines and
    assignments. Inside an open quote a comment line is content, so the
    accumulation has to take it -- otherwise the value would be truncated at
    the first ``#`` and the closing quote after it would be read as a key.
    """
    result = parse_text('KEY="l1\n# not a comment here\nl2"\nNEXT=keepme\n')

    assert result.values["KEY"] == "l1\n# not a comment here\nl2"
    assert result.values["NEXT"] == "keepme"


def test_commented_out_multiline_key_is_still_reported_as_commented():
    """The pending-removal signal depends on commented keys surviving.

    ``parse_text`` reports a key seen only in a commented-out assignment. A
    multi-line commented value must reach that list rather than being parsed as
    an active value.
    """
    result = parse_text('# KEY="first\n# second"\n')

    assert result.values == {}
    assert "KEY" in result.commented_keys


def test_multiline_value_replaces_a_previously_commented_key():
    """Re-assigning a commented-out key moves it back to active.

    ``parse_text`` removes a key from ``commented`` when it is assigned; this
    pins that the multi-line branch still reaches that bookkeeping rather than
    skipping it.
    """
    result = parse_text('# KEY="placeholder"\nKEY="first\nsecond"\n')

    assert result.values["KEY"] == "first\nsecond"
    assert "KEY" not in result.commented_keys