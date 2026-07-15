"""Tests for tr_shared.events.pii.hash_pii."""

import hashlib

from tr_shared.events import hash_pii


def test_none_returns_none():
    assert hash_pii(None) is None


def test_empty_string_returns_none():
    assert hash_pii("") is None


def test_hashes_to_16_hex_chars():
    out = hash_pii("+971501234567")
    assert out is not None
    assert len(out) == 16
    assert all(c in "0123456789abcdef" for c in out)


def test_is_sha256_truncated_and_stable():
    value = "user@example.com"
    expected = hashlib.sha256(value.encode()).hexdigest()[:16]
    assert hash_pii(value) == expected
    assert hash_pii(value) == hash_pii(value)
