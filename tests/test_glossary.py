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
    assert "urgent" in GLOSSARY["priority"].retired_aliases
    assert "mobile_push" in GLOSSARY["channel"].retired_aliases
    assert "comment" in GLOSSARY["entity_type"].retired_aliases
