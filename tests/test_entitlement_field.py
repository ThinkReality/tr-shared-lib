import pytest
from pydantic import BaseModel, ValidationError

from tr_shared.contracts.taxonomy import (
    EntitlementModuleField,
    Feature,
    ensure_entitlement_module,
)


class _Model(BaseModel):
    module: EntitlementModuleField


def test_accepts_an_entitlement_module():
    assert _Model(module="listing").module is Feature.LISTING


def test_rejects_a_feature_that_is_not_toggleable():
    with pytest.raises(ValidationError, match="not a tenant-toggleable module"):
        _Model(module="media")


def test_rejects_a_non_feature_string():
    """A string that is not a Feature at all fails at enum coercion, BEFORE the
    validator runs — so the message is pydantic's enum message, not ours. Do not
    assert the toggleable wording here; it is a different failure."""
    with pytest.raises(ValidationError):
        _Model(module="listing_management")


def test_the_validator_is_public_and_is_the_one_the_field_uses():
    """One rule, one message. `require_module` (shared-auth-lib) and
    `set_tenant_modules` (crm-core) both call THIS function rather than restating
    the sentence — three hand-written copies of it is what this replaces."""
    assert ensure_entitlement_module(Feature.LISTING) is Feature.LISTING
    with pytest.raises(ValueError, match="not a tenant-toggleable module"):
        ensure_entitlement_module(Feature.MEDIA)
