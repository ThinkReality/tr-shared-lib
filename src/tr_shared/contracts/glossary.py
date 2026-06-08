"""Structured glossary for cross-domain terms.

One concept -> its canonical name, the authoritative type, and retired aliases.
The drift-guard test (tests/test_glossary.py) asserts no retired alias is still a
live enum member, so re-introducing `urgent`/`mobile_push`/`comment` fails CI.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    canonical: str  # human-facing canonical name
    type: str  # import path of the authoritative enum
    retired_aliases: tuple[str, ...] = ()


GLOSSARY: dict[str, Term] = {
    "feature": Term(
        canonical="Feature",
        type="tr_shared.contracts.taxonomy.Feature",
    ),
    "entity_type": Term(
        canonical="EntityType",
        type="tr_shared.contracts.entity_types.EntityType",
        retired_aliases=("comment",),  # migrated to activity.comment
    ),
    "priority": Term(
        canonical="Priority",
        type="tr_shared.contracts.enums.Priority",
        retired_aliases=("urgent",),  # migrated to critical
    ),
    "channel": Term(
        canonical="Channel",
        type="tr_shared.contracts.enums.Channel",
        retired_aliases=("mobile_push",),  # migrated to push
    ),
}
