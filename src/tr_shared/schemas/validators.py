"""Reusable Pydantic field-validator helpers.

SSOT for cross-service validation logic so individual schemas stop
re-implementing the same coercion + error-message patterns.
"""

from enum import Enum
from typing import TypeVar

E = TypeVar("E", bound=Enum)


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
