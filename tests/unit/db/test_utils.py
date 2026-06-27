from tr_shared.db import LIKE_ESCAPE_CHAR, escape_like


def test_escape_percent():
    assert escape_like("50%") == "50\\%"


def test_escape_underscore():
    assert escape_like("a_b") == "a\\_b"


def test_escape_backslash_first():
    # Backslash must be doubled BEFORE wildcards, else the wildcard escapes
    # would themselves be re-escaped.
    assert escape_like("a\\b") == "a\\\\b"


def test_escape_mixed():
    assert escape_like("\\%_") == "\\\\\\%\\_"


def test_escape_no_wildcards_unchanged():
    assert escape_like("plain text") == "plain text"


def test_escape_empty():
    assert escape_like("") == ""


def test_escape_char_constant():
    assert LIKE_ESCAPE_CHAR == "\\"
