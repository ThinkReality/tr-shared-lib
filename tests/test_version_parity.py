"""Guard: __version__ and pyproject [project].version must never drift."""

import tomllib
from pathlib import Path

import tr_shared


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    assert tr_shared.__version__ == data["project"]["version"]


def test_new_surface_imports():
    from tr_shared.events.payloads import (  # noqa: F401
        CMSLandingPagePublishedV1,
        CMSPageEventV1,
        FinanceCardTransactionMatchedV1,
        FinanceInvoiceEventV1,
        HRApplicationStageChangedV1,
        HRApplicationSubmittedV1,
        LeadCreatedV1,
        ListingAuditEventV1,
        WAMLeadQualifiedV1,
    )
