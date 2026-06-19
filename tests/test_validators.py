"""Unit tests for tr_shared.schemas.validators.coerce_enum."""

from enum import Enum

import pytest

from tr_shared.schemas import coerce_enum


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
