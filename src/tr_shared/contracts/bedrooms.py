"""The bedroom-count vocabulary — one spelling for the whole fleet.

Owned by tr-content-platform, which uses it in two modules that must agree:
``listing`` filters an integer ``bedrooms`` column with it, and ``cms`` keys a
landing page's ``room_types`` JSONB and its ``property_types[].unit_types`` with
it. The two modules do not import each other, so a vocabulary both need cannot
live in either — the same reasoning that put ``Emirate`` here.

The frontend mirrors it by hand in ``lib/constants/listing-vocabulary.ts`` and
``lib/constants/cms-vocabulary.ts``; both mirrors are guarded against the
snapshots the owning module publishes.

**Only the vocabulary lives here.** Each consumer owns its own encoding:
``listing`` stores studio as an integer (``STUDIO_BEDROOMS``, in that module's
``core.enums``) and reads ``7+`` as ``>= 7``; ``cms`` stores the value verbatim
as a JSONB key. ``contracts/`` is declarations only.
"""

from enum import StrEnum


class BedroomCount(StrEnum):
    """``studio`` through ``7+`` — a filter vocabulary, not a storage one.

    ``studio`` and ``7+`` are why ``int(value)`` cannot be the parser: the first
    is not a number and the second is a bound, not a count.

    The union of what the two frontends offered. The CRM sent ``5+`` and had no
    6 or 7; tr-website sent ``6`` and ``7+`` and had no studio. Typing the field
    without changing both option lists would have 422'd tr-website's 6 and 7+ on
    the live public site.
    """

    STUDIO = "studio"
    ONE = "1"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN_PLUS = "7+"
