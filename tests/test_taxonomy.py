# tests/test_taxonomy.py
import pytest

from tr_shared.contracts.taxonomy import Feature

EXPECTED = {
    "auth", "lead", "deal", "contact", "property", "listing", "cms", "lms",
    "task", "activity", "notification", "hr", "finance", "admin", "media",
    "dld", "wam",
}


def test_feature_has_exactly_the_17_locked_members():
    assert {f.value for f in Feature} == EXPECTED
    assert len(list(Feature)) == 17


def test_feature_is_a_str_enum():
    assert Feature.LEAD == "lead"
    assert isinstance(Feature.LEAD, str)


def test_campaign_is_not_a_feature():
    with pytest.raises(ValueError):
        Feature("campaign")
