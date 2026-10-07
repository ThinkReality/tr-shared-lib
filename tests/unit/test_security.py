import pytest

from tr_shared.security import constant_time_equals


@pytest.mark.parametrize(
    ("a", "b"),
    [("abc", "abc"), (b"abc", b"abc"), ("abc", b"abc"), ("é", "é"), ("é", "é".encode())],
)
def test_equal_values_compare_equal(a, b):
    assert constant_time_equals(a, b) is True


@pytest.mark.parametrize(
    ("a", "b"),
    [("abc", "abd"), ("abc", "ab"), ("", "a"), (b"abc", "abd")],
)
def test_different_values_compare_unequal(a, b):
    assert constant_time_equals(a, b) is False


@pytest.mark.parametrize(("a", "b"), [("é", "a"), ("a", "é"), ("abc", "abé"), ("\x80", "a")])
def test_non_ascii_text_is_unequal_instead_of_raising(a, b):
    assert constant_time_equals(a, b) is False
