import pytest
from pydantic import ValidationError

from tr_shared.events.payloads import EventPayload


class _Sample(EventPayload):
    a: str


def test_forbids_unknown_keys():
    with pytest.raises(ValidationError):
        _Sample(a="x", b="surprise")


def test_accepts_declared_keys():
    assert _Sample(a="x").a == "x"


def test_model_dump_roundtrip_is_lossless():
    s = _Sample(a="x")
    assert _Sample(**s.model_dump()) == s
