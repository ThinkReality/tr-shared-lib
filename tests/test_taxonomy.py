import pytest

from tr_shared.contracts.taxonomy import ENTITLEMENT_MODULES, Feature

EXPECTED = {
    "auth",
    "lead",
    "deal",
    "contact",
    "property",
    "listing",
    "cms",
    "lms",
    "task",
    "activity",
    "notification",
    "hr",
    "finance",
    "admin",
    "media",
    "dld",
    "wam",
    "recruitment",
    # `scraping` joined 2026-08-03. It is a tenant-toggleable entitlement unit,
    # and ENTITLEMENT_MODULES is a frozenset OF Features — so it had to be a real
    # spine member, not a parallel string. Amending this literal set and the count
    # below is the deliberate, documented act the lock exists to force.
    "scraping",
}


def test_feature_has_exactly_the_19_locked_members():
    assert {f.value for f in Feature} == EXPECTED
    assert len(list(Feature)) == 19


def test_feature_is_a_str_enum():
    assert Feature.LEAD == "lead"
    assert isinstance(Feature.LEAD, str)


def test_campaign_is_not_a_feature():
    with pytest.raises(ValueError):
        Feature("campaign")


def test_entitlement_modules_are_the_eight_toggleable_units():
    assert ENTITLEMENT_MODULES == frozenset(
        {
            Feature.LISTING,
            Feature.CMS,
            Feature.LEAD,
            Feature.LMS,
            Feature.HR,
            Feature.FINANCE,
            Feature.DLD,
            Feature.SCRAPING,
        }
    )


def test_every_entitlement_module_is_a_real_feature():
    """True by construction — the set holds Feature members, not strings. This
    asserts the construction, so a future edit to a bare string fails here."""
    assert all(isinstance(m, Feature) for m in ENTITLEMENT_MODULES)


def test_deal_is_not_an_entitlement_unit():
    """Deals ride along with `lead`. Widening later is additive and cheap;
    narrowing later breaks a tenant who already had it."""
    assert Feature.DEAL not in ENTITLEMENT_MODULES
