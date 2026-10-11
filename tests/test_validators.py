"""Unit tests for tr_shared.schemas.validators."""

from enum import Enum

import pytest

from tr_shared.schemas import coerce_enum, reject_unstorable_text, unstorable_text_location


class Color(str, Enum):
    RED = "red"
    BLUE = "blue"


def test_valid_string_coerced_to_member():
    assert coerce_enum("red", Color) is Color.RED


def test_none_passes_through():
    assert coerce_enum(None, Color) is None


def test_existing_member_passes_through():
    assert coerce_enum(Color.BLUE, Color) is Color.BLUE


def test_invalid_string_raises_with_allowed_values():
    with pytest.raises(ValueError, match="Invalid Color. Must be one of: red, blue"):
        coerce_enum("green", Color)


def test_label_overrides_message_name():
    with pytest.raises(ValueError, match="Invalid device type. Must be one of"):
        coerce_enum("green", Color, "device type")


def test_non_string_non_enum_passes_through():
    # int is neither str nor a Color — pass through for downstream type error
    assert coerce_enum(42, Color) == 42


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("night\x00shift", id="nul"),
        pytest.param("a\ud800b", id="high-surrogate"),
        pytest.param("a\udfffb", id="low-surrogate"),
    ],
)
def test_text_postgres_cannot_store_is_found(value):
    assert unstorable_text_location(value) == ()


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("plain text", id="plain"),
        pytest.param("emoji \U0001f600 and arabic مرحبا", id="astral-and-rtl"),
        pytest.param("\\u0000", id="escaped-backslash-text"),
        pytest.param("", id="empty"),
        pytest.param(42, id="int"),
        pytest.param(None, id="none"),
        pytest.param(True, id="bool"),
        pytest.param({"k": ["v", 1, {"n": None}]}, id="clean-nested"),
    ],
)
def test_storable_values_pass(value):
    assert unstorable_text_location(value) is None


def test_a_nested_dict_value_reports_its_path():
    assert unstorable_text_location({"meta": {"note": "a\x00b"}}) == ("meta", "note")


def test_a_dict_key_reports_the_dict_holding_it_so_the_key_is_never_echoed():
    assert unstorable_text_location({"meta": {"no\ud800te": "ok"}}) == ("meta",)


def test_a_list_item_reports_its_index():
    assert unstorable_text_location({"tags": ["ok", "b\ud800"]}) == ("tags", 1)


def test_reject_returns_a_storable_value_unchanged():
    value = {"note": "fine"}

    assert reject_unstorable_text(value, "metadata") is value


def test_reject_names_the_field_and_never_echoes_the_value():
    with pytest.raises(ValueError) as caught:
        reject_unstorable_text({"note": "secret\x00value"}, "metadata")

    assert "metadata" in str(caught.value)
    assert "secret" not in str(caught.value)


def test_deeply_nested_text_is_walked_without_recursion():
    value: object = "a\x00b"
    for _ in range(5000):
        value = [value]

    assert unstorable_text_location(value) == (0,) * 5000
