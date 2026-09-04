"""Structured glossary for cross-domain terms.

One concept -> its canonical name, the authoritative type, and retired aliases.
The drift-guard test (tests/test_glossary.py) asserts no retired alias is still a
live enum member, so re-introducing `urgent`/`mobile_push`/`comment` fails CI.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Term:
    canonical: str
    type: str  # import path of the authoritative enum
    migrations: dict[str, str] = field(default_factory=dict)  # retired alias -> replacement value

    @property
    def retired_aliases(self) -> tuple[str, ...]:
        return tuple(self.migrations)


# The cross-domain canonical enums. Each retired alias maps to the live member
# that replaced it, so the bijection test can assert both directions: no retired
# alias is still live, and every replacement IS a live member.
GLOSSARY: dict[str, Term] = {
    "feature": Term(
        canonical="Feature",
        type="tr_shared.contracts.taxonomy.Feature",
    ),
    "entity_type": Term(
        canonical="EntityType",
        type="tr_shared.contracts.entity_types.EntityType",
        migrations={"comment": "activity.comment"},
    ),
    "priority": Term(
        canonical="Priority",
        type="tr_shared.contracts.enums.Priority",
        migrations={"urgent": "critical"},
    ),
    "channel": Term(
        canonical="Channel",
        type="tr_shared.contracts.enums.Channel",
        migrations={"mobile_push": "push"},
    ),
    # One bedroom spelling for listing, cms and both frontends. The retired
    # aliases are the two encodings cms landing pages used: `room_types` keys
    # were `bed1`..`bed7plus` and `property_types[].unit_types` were the display
    # labels `1 Bedroom`..`7+ Bedroom`. One representative of each retired shape
    # is recorded; re-introducing either spelling as a member fails the guard.
    "bedroom_count": Term(
        canonical="BedroomCount",
        type="tr_shared.contracts.bedrooms.BedroomCount",
        migrations={"bed1": "1", "1 Bedroom": "1", "bed7plus": "7+"},
    ),
}
