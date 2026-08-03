"""The Feature taxonomy spine — the one canonical business-capability vocabulary.

A Feature is a frontend feature / domain / bounded context. It is the stable
spine that replaces the five overlapping taxonomies (SourceService, EntityType
prefix, code module, permission module, deployable). Event `source`, entity-type
prefixes, and permission scopes all draw from this vocabulary. Deployable names
(tr-crm-core, ...) are infra facts and never appear in contracts.
"""

from enum import StrEnum
from typing import Annotated, Final

from pydantic import AfterValidator


class Feature(StrEnum):
    AUTH = "auth"
    LEAD = "lead"
    DEAL = "deal"
    CONTACT = "contact"
    PROPERTY = "property"
    LISTING = "listing"
    CMS = "cms"
    LMS = "lms"
    TASK = "task"
    ACTIVITY = "activity"
    NOTIFICATION = "notification"
    HR = "hr"
    FINANCE = "finance"
    ADMIN = "admin"  # campaign is a sub-concept of admin, not first-class
    MEDIA = "media"
    DLD = "dld"
    WAM = "wam"
    RECRUITMENT = "recruitment"
    SCRAPING = "scraping"


ENTITLEMENT_MODULES: Final[frozenset[Feature]] = frozenset(
    {
        Feature.LISTING,
        Feature.CMS,
        Feature.LEAD,  # deals and commissions ride along; DEAL is not a unit
        Feature.LMS,
        Feature.HR,
        Feature.FINANCE,
        Feature.DLD,
        Feature.SCRAPING,
    }
)
"""The subset of Features a tenant can be granted or denied at onboarding.

A frozenset OF ``Feature`` members, not of strings and not a parallel enum.
Members, because ``Feature.SCRPING`` is an AttributeError at import while
``"scrping"`` is a silently wrong string. Not a subset enum, because
``isinstance(SubsetEnum.X, Feature)`` is False and ``events/helpers.py``
raises TypeError on exactly that check.

This is a hand-written literal rather than a set derived from a per-Feature
flag, because ``Feature`` is a bare StrEnum with no registry of per-member
facts — deriving would mean inventing one to carry a single boolean. There is
only one list, so there is nothing for it to drift from. Widening and narrowing
are held deliberate by ``tests/test_taxonomy.py`` instead: the Feature
count-lock and the eight-member assertion both have to be amended by hand.

``auth_schema.auth_tenant.enabled_modules`` is the single store of what a tenant
holds. ``admin.admin_panel_modules`` is a per-module CONFIG sidecar keyed by the
same vocabulary, and its DB CHECK constraint MUST be generated from this set."""


def ensure_entitlement_module(value: Feature) -> Feature:
    """The ONE check that a Feature is tenant-toggleable, and the ONE message.

    Public on purpose. ``EntitlementModuleField`` wraps it,
    ``shared_auth_lib.authz.entitlement.require_module`` calls it at router-import
    time, and ``AsyncTenantService.set_tenant_modules`` reaches it by coercing
    through the field. Three hand-written copies of this sentence is what that
    arrangement replaces — two of them had tests ``match=``ing the literal, so a
    reworded message would have failed in three repos at once.
    """
    if value not in ENTITLEMENT_MODULES:
        raise ValueError(
            f"{value.value} is not a tenant-toggleable module; "
            f"valid: {sorted(m.value for m in ENTITLEMENT_MODULES)}"
        )
    return value


EntitlementModuleField = Annotated[Feature, AfterValidator(ensure_entitlement_module)]
"""Pydantic field type for a tenant-toggleable module name.

Emits the full ``Feature`` enum in OpenAPI and 422s on the non-toggleable
members. That gap is real and does not cash out today: no frontend has OpenAPI
codegen and none calls the admin modules endpoint. If a consumer lands, derive a
``WithJsonSchema`` from ``ENTITLEMENT_MODULES`` — do not duplicate the names."""
