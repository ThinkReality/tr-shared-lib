"""Typed event payloads. EventPayload is the strict base; per-feature modules
hold the {Feature}{Event}{Vn} models. Additive within a Vn; breaking = new Vn."""

from tr_shared.events.payloads._base import EventPayload

__all__ = ["EventPayload"]
