"""The seven emirates — one closed vocabulary for the whole fleet.

Owned by tr-content-platform: it is the CHECK-constrained vocabulary of
``listing_schema.listing_listings.uae_emirate``
(``ck_listing_listings_uae_emirate``), and is re-exported by that module's
``core.enums``. Declared here because tr-crm-core stores an emirate on the
tenant's company profile too, and the frontend mirrors it by hand in
``tr-crm-frontend/lib/constants/emirates.ts``.

Same reasoning as ``PortalSyncStatus`` in ``contracts.s2s.listing_internal``:
being owned by one service is not a reason to declare it there when a second
service has to agree on the values. The alternative was a third spelling of a
vocabulary the fleet already enumerates, guards and mirrors.

**Only the vocabulary lives here.** The permit rule
(``PERMIT_REQUIRED_EMIRATES``) is a listing business rule, and the accepted-
spelling tables (``normalize_emirate``, ``split_emirate_region``) exist to
absorb what specific portals emit — Bayut puts Al Ain at breadcrumb depth 1,
PropertyFinder writes ``abu_dhabi``. Both stay in tr-content-platform with the
reasons that produced them. ``contracts/`` is declarations only.

Adding or removing a member requires a forward migration in tr-content-platform
that regenerates the CHECK constraint, plus an update to the frontend mirror —
``vocabulary_contract.py`` and ``emirates.test.ts`` are what make that loud.
"""

from enum import StrEnum


class Emirate(StrEnum):
    """Canonical value for an emirate anywhere in the fleet.

    Title Case because both inbound portal trees already emit it, so nothing has
    to be rewritten on import and the value is display-ready.
    """

    DUBAI = "Dubai"
    ABU_DHABI = "Abu Dhabi"
    SHARJAH = "Sharjah"
    AJMAN = "Ajman"
    RAS_AL_KHAIMAH = "Ras Al Khaimah"
    FUJAIRAH = "Fujairah"
    UMM_AL_QUWAIN = "Umm Al Quwain"
