# tests/test_glossary.py
import importlib
from enum import Enum

from tr_shared.contracts.glossary import GLOSSARY, Term


def _resolve(type_path: str) -> type[Enum]:
    module_path, name = type_path.rsplit(".", 1)
    return getattr(importlib.import_module(module_path), name)


def test_glossary_holds_term_objects():
    assert GLOSSARY
    assert all(isinstance(t, Term) for t in GLOSSARY.values())


def test_every_term_type_resolves_to_an_enum():
    for term in GLOSSARY.values():
        enum_cls = _resolve(term.type)
        assert issubclass(enum_cls, Enum)


def test_retired_aliases_are_not_live_members():
    for key, term in GLOSSARY.items():
        live = {m.value for m in _resolve(term.type)}
        for alias in term.retired_aliases:
            assert alias not in live, (
                f"glossary[{key!r}] lists retired alias {alias!r} that is STILL a "
                f"live member of {term.canonical} — drift"
            )


def test_known_migrations_are_recorded():
    assert GLOSSARY["priority"].migrations["urgent"] == "critical"
    assert GLOSSARY["channel"].migrations["mobile_push"] == "push"
    assert GLOSSARY["entity_type"].migrations["comment"] == "activity.comment"


def test_glossary_covers_exactly_the_canonical_enums():
    """Type-level bijection: the glossary registers exactly the four cross-domain
    canonical enums — adding/removing one without updating the glossary fails here."""
    assert set(GLOSSARY) == {"feature", "entity_type", "priority", "channel"}


def test_every_migration_replacement_is_a_live_member():
    """Reverse direction: every retired alias maps to a replacement that IS a live
    member of its enum (and the retired alias itself is gone). Catches a migration
    whose replacement was later renamed/removed."""
    for key, term in GLOSSARY.items():
        live = {m.value for m in _resolve(term.type)}
        for retired, replacement in term.migrations.items():
            assert replacement in live, (
                f"glossary[{key!r}] migrates {retired!r} -> {replacement!r}, but "
                f"{replacement!r} is NOT a live member of {term.canonical} — drift"
            )
            assert retired not in live, (
                f"glossary[{key!r}] retired alias {retired!r} is STILL live in "
                f"{term.canonical} — drift"
            )
