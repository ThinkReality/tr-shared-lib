"""``Emirate`` is a mirrored vocabulary — three places have to agree on it.

tr-content-platform CHECK-constrains a column to these values, tr-crm-core
stores one on the tenant profile, and the frontend hand-mirrors them in
``lib/constants/emirates.ts``. This file pins the values on the owning side so
a member added or renamed here is loud, not silent on all three.
"""

import pytest

from tr_shared.contracts import Emirate as ExportedEmirate
from tr_shared.contracts.emirates import Emirate


def test_exactly_the_seven_emirates():
    assert {e.value for e in Emirate} == {
        "Dubai",
        "Abu Dhabi",
        "Sharjah",
        "Ajman",
        "Ras Al Khaimah",
        "Fujairah",
        "Umm Al Quwain",
    }


def test_exported_from_the_package_root():
    """Consumers import from ``tr_shared.contracts``, not the submodule."""
    assert ExportedEmirate is Emirate


def test_values_are_title_case():
    """Portal trees emit Title Case, so the value is display-ready as stored."""
    assert all(e.value == e.value.title() for e in Emirate)


def test_al_ain_is_not_a_member():
    """It is a region of Abu Dhabi. Bayut puts it at emirate depth; the alias
    table in tr-content-platform absorbs that, not this vocabulary."""
    assert "Al Ain" not in {e.value for e in Emirate}


@pytest.mark.parametrize("raw", ["dubai", "abu_dhabi", "DUBAI", "RAK"])
def test_lookup_is_exact_not_forgiving(raw):
    """Spelling tolerance belongs to tr-content-platform's ``normalize_emirate``.

    If this enum accepted loose spellings, two spellings of one emirate would
    both look correct to a caller — which is the bug the enum replaced.
    """
    with pytest.raises(ValueError):
        Emirate(raw)


def test_is_a_str_subclass():
    """StrEnum, so it serializes as its value and compares to plain strings."""
    assert isinstance(Emirate.DUBAI, str)
    assert Emirate.DUBAI == "Dubai"
