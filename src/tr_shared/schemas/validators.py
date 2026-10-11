"""Reusable Pydantic field-validator helpers.

SSOT for cross-service validation logic so individual schemas stop
re-implementing the same coercion + error-message patterns.
"""

import re
from enum import Enum
from typing import TypeVar

E = TypeVar("E", bound=Enum)
T = TypeVar("T")

_UNSTORABLE_TEXT = re.compile("[\x00\ud800-\udfff]")


def coerce_enum(value: object, enum_cls: type[E], label: str | None = None) -> object:
    """Coerce a raw string into ``enum_cls`` with a uniform error message.

    Use inside a Pydantic ``mode="before"`` field validator::

        @field_validator("device_type", mode="before")
        @classmethod
        def _coerce(cls, v: object) -> object:
            return coerce_enum(v, DeviceType, "device type")

    ``None`` and existing ``enum_cls`` instances pass through unchanged. A
    string that is not a valid member raises ``ValueError`` listing the allowed
    values. Non-string, non-enum values pass through so downstream Pydantic
    validation reports the type error in its own voice.
    """
    if value is None or isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError:
            valid = ", ".join(str(member.value) for member in enum_cls)
            name = label or enum_cls.__name__
            raise ValueError(f"Invalid {name}. Must be one of: {valid}") from None
    return value


def unstorable_text_location(value: object) -> tuple[str | int, ...] | None:
    pending: list[tuple[tuple[str | int, ...], object]] = [((), value)]
    while pending:
        path, item = pending.pop()
        if isinstance(item, str):
            if _UNSTORABLE_TEXT.search(item):
                return path
        elif isinstance(item, dict):
            for key, inner in item.items():
                if isinstance(key, str) and _UNSTORABLE_TEXT.search(key):
                    return path
                pending.append(((*path, key), inner))
        elif isinstance(item, list):
            pending.extend(((*path, index), inner) for index, inner in enumerate(item))
    return None


def reject_unstorable_text(value: T, label: str) -> T:
    if unstorable_text_location(value) is not None:
        raise ValueError(f"{label} contains a NUL or unpaired surrogate character")
    return value
