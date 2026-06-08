# tests/test_contract_enums.py
import pytest

from tr_shared.contracts.enums import Channel, Priority


def test_priority_members():
    assert {p.value for p in Priority} == {"low", "medium", "high", "critical"}


def test_priority_rejects_retired_urgent():
    with pytest.raises(ValueError):
        Priority("urgent")


def test_channel_members():
    assert {c.value for c in Channel} == {"in_app", "email", "sms", "push", "whatsapp"}


def test_channel_rejects_retired_mobile_push():
    with pytest.raises(ValueError):
        Channel("mobile_push")
