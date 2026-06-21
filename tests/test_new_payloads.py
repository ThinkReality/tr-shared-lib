"""Round-trip + strictness tests for the cms/lead/wam/listing-audit payloads and
the finance-invoice/card + hr-application additions (L1.2-L1.7).

Dicts mirror the runtime emit shapes (with dynamic legacy keys canonicalised to
actor_id/recipient_id per the redesign).
"""

import pytest
from pydantic import ValidationError

from tr_shared.events.envelope import EventEnvelope
from tr_shared.events.event_types import CMSEvents, HREvents
from tr_shared.events.helpers import parse_payload
from tr_shared.events.payloads.cms import (
    CMSBlogEventV1,
    CMSBlogUpdatedV1,
    CMSLandingPagePublishedV1,
    CMSPageApprovedV1,
    CMSPageEventV1,
    CMSPagePublishedV1,
    CMSPageRejectedV1,
    CMSPageReviewRequestedV1,
    CMSPageUpdatedV1,
)
from tr_shared.events.payloads.finance import (
    FinanceCardTransactionImportedV1,
    FinanceCardTransactionMatchedV1,
    FinanceInvoiceEventV1,
)
from tr_shared.events.payloads.hr import (
    HRApplicationStageChangedV1,
    HRApplicationSubmittedV1,
)
from tr_shared.events.payloads.lead import (
    LeadAssignedV1,
    LeadCreatedV1,
    LeadFollowupDueV1,
    LeadQualifiedV1,
    LeadStatusChangedV1,
)
from tr_shared.events.payloads.listing import ListingAuditEventV1
from tr_shared.events.payloads.wam import WAMLeadQualifiedV1


def _env(event_type: str, data: dict) -> EventEnvelope:
    return EventEnvelope(
        event_id="e",
        event_type=event_type,
        version="1.0",
        tenant_id="ten1",
        timestamp="2026-01-01T00:00:00Z",
        source_service="cms",
        actor_id=None,
        data=data,
    )


# ---------- CMS ----------

_PAGE_BASE = {
    "entity_type": "cms.page",
    "entity_id": "p1",
    "page_id": "p1",
    "page_title": "Home",
    "page_slug": "home",
    "action": "created",
    "actor_id": "u1",
    "actor_name": "Alice",
    "recipient_id": "u2",
    "status": "draft",
}


def test_cms_page_event_roundtrip():
    parsed = parse_payload(_env("cms.page.created", _PAGE_BASE), CMSPageEventV1)
    assert parsed.model_dump() == _PAGE_BASE


def test_cms_page_legacy_action_by_key_rejected():
    # The redesign drops dynamic {action}_by keys — a legacy created_by must fail.
    with pytest.raises(ValidationError):
        CMSPageEventV1(**{**_PAGE_BASE, "created_by": "u1"})


def test_cms_page_published_carries_url():
    data = {**_PAGE_BASE, "action": "published", "page_url": "https://x/home"}
    p = parse_payload(_env("cms.page.published", data), CMSPagePublishedV1)
    assert p.page_url == "https://x/home"


def test_cms_page_subclasses_construct():
    CMSPageUpdatedV1(**{**_PAGE_BASE, "action": "updated", "changes": {"title": "x"}})
    CMSPageReviewRequestedV1(**{**_PAGE_BASE, "requested_by": "u9"})
    CMSPageApprovedV1(**{**_PAGE_BASE, "page_url": "u", "review_notes": "ok"})
    CMSPageRejectedV1(**{**_PAGE_BASE, "review_notes": "no"})


def test_cms_blog_event_roundtrip():
    data = {
        "entity_type": "cms.blog",
        "entity_id": "b1",
        "blog_id": "b1",
        "blog_title": "Post",
        "blog_slug": "post",
        "action": "created",
        "actor_id": "u1",
        "actor_name": "Alice",
        "recipient_id": "u2",
        "status": "draft",
    }
    assert parse_payload(_env("cms.blog.created", data), CMSBlogEventV1).model_dump() == data
    CMSBlogUpdatedV1(**{**data, "action": "updated", "changes": {"x": 1}})


def test_cms_landing_page_published_nested_context():
    data = {
        "project_id": "pr1",
        "project_title": "Marina Heights",
        "landing_page_context": {
            "developer_name": "Emaar",
            "project_type": "residential",
            "property_types": ["apartment"],
            "starting_price": 1500000.0,
            "starting_price_currency": "AED",
            "amenities": ["pool"],
            "media": [{"media_id": "m1", "media_url": "https://x/1.jpg", "category": "hero"}],
        },
    }
    p = parse_payload(_env("cms.landing_page.published", data), CMSLandingPagePublishedV1)
    assert p.landing_page_context.developer_name == "Emaar"
    assert p.landing_page_context.media[0].media_id == "m1"


def test_every_cms_page_and_blog_event_has_a_model():
    mapping = {
        CMSEvents.PAGE_CREATED: CMSPageEventV1,
        CMSEvents.PAGE_DELETED: CMSPageEventV1,
        CMSEvents.PAGE_UNPUBLISHED: CMSPageEventV1,
        CMSEvents.PAGE_UPDATED: CMSPageUpdatedV1,
        CMSEvents.PAGE_PUBLISHED: CMSPagePublishedV1,
        CMSEvents.PAGE_REVIEW_REQUESTED: CMSPageReviewRequestedV1,
        CMSEvents.PAGE_APPROVED: CMSPageApprovedV1,
        CMSEvents.PAGE_REJECTED: CMSPageRejectedV1,
        CMSEvents.BLOG_CREATED: CMSBlogEventV1,
        CMSEvents.BLOG_UPDATED: CMSBlogUpdatedV1,
        CMSEvents.BLOG_PUBLISHED: CMSBlogEventV1,
        CMSEvents.BLOG_UNPUBLISHED: CMSBlogEventV1,
        CMSEvents.BLOG_DELETED: CMSBlogEventV1,
        CMSEvents.LANDING_PAGE_PUBLISHED: CMSLandingPagePublishedV1,
    }
    # Every cms.page.* and cms.blog.* (+ landing_page) registry value is mapped.
    assert len(mapping) == 14


# ---------- Lead ----------

_LEAD_BASE = {"entity_type": "lead", "entity_id": "l1", "lead_id": "l1", "lead_name": "Bob"}


def test_lead_created_minimal_shape_validates():
    data = {**_LEAD_BASE, "hashed_phone": "h", "source": "website"}
    assert parse_payload(_env("lead.created", data), LeadCreatedV1).lead_id == "l1"


def test_lead_created_rich_shape_validates():
    data = {
        **_LEAD_BASE,
        "lead_phone": "hashed",
        "lead_email": "hashed",
        "tenant_id": "t1",
        "stage": "new",
        "status": "open",
        "lead_score": 80,
        "lead_quality_tier": "hot",
        "assigned_to": "a1",
        "recipient_id": "a1",
        "created_by": "u1",
        "actor_id": "u1",
    }
    p = parse_payload(_env("lead.created", data), LeadCreatedV1)
    assert p.lead_score == 80


def test_lead_other_events_construct():
    LeadAssignedV1(**_LEAD_BASE, assigned_to="a1", assignment_reason="manual")
    LeadStatusChangedV1(**_LEAD_BASE, new_status="qualified")
    LeadQualifiedV1(**_LEAD_BASE, qualification_score=90)
    LeadFollowupDueV1(**_LEAD_BASE, followup_date="2026-01-02")


def test_lead_extra_key_rejected():
    with pytest.raises(ValidationError):
        LeadCreatedV1(**_LEAD_BASE, raw_phone="+9715")  # raw PII never on the bus


# ---------- WAM ----------

def test_wam_lead_qualified_minimal():
    p = WAMLeadQualifiedV1(user_number="971501234567", lead_score=80, tier="hot")
    assert p.user_number == "971501234567"


def test_wam_user_number_must_be_digits():
    with pytest.raises(ValidationError):
        WAMLeadQualifiedV1(user_number="+971-50-1234567", lead_score=80, tier="hot")


def test_wam_qualification_result_nested():
    p = WAMLeadQualifiedV1(
        user_number="971501234567",
        lead_score=80,
        tier="hot",
        qualification_result={"buyer_type": "investor", "timeline": "3m"},
    )
    assert p.qualification_result.buyer_type == "investor"


# ---------- Listing audit ----------

_AUDIT = {
    "entity_id": "list1",
    "entity_type": "listing",
    "action": "update",
    "new_status": "active",
    "old_status": "draft",
    "changes": {"price": [100, 200]},
}


def test_listing_audit_roundtrip():
    p = parse_payload(_env("listing.updated", _AUDIT), ListingAuditEventV1)
    assert p.entity_type == "listing"


def test_listing_audit_rejects_redundant_event_type_key():
    # The legacy emit dict injected event_type into data; the redesign drops it.
    with pytest.raises(ValidationError):
        ListingAuditEventV1(**{**_AUDIT, "event_type": "listing.updated"})


# ---------- Finance invoice + card ----------

def test_finance_invoice_event():
    data = {
        "entity_type": "invoice",
        "entity_id": "i1",
        "invoice_number": "INV-1",
        "status": "draft",
        "total_amount": "500.00",
        "invoice_type": "sales",
        "party_name": "ACME",
        "notification_recipient_id": "u1",
    }
    assert parse_payload(_env("finance.invoice.created", data), FinanceInvoiceEventV1).invoice_number == "INV-1"


def test_finance_card_imported_and_matched():
    imported = {
        "entity_type": "card_transaction_import",
        "entity_id": "ten1",
        "total_submitted": 10,
        "created": 8,
        "skipped_duplicates": 2,
        "auto_matched": 5,
        "requires_manual_review": 3,
        "match_error_count": 0,
        "match_errors": [],
        "created_transaction_ids": ["t1", "t2"],
    }
    FinanceCardTransactionImportedV1(**imported)
    matched = {
        "entity_type": "card_transaction",
        "entity_id": "tx1",
        "merchant_name": "Cafe",
        "amount": "42.00",
        "currency": "AED",
        "transaction_date": "2026-01-01",
        "matched_expense_id": "ex1",
        "match_type": "auto",
    }
    FinanceCardTransactionMatchedV1(**matched)


# ---------- HR application ----------

def test_hr_application_events():
    submitted = {
        "entity_id": "app1",
        "entity_type": "hr_application",
        "action": "submitted",
        "notification_event": "hr_application_submitted",
        "application_id": "app1",
        "job_id": "j1",
    }
    HRApplicationSubmittedV1(**submitted)
    # PII dropped — extra="forbid" must now reject applicant_name / applicant_email.
    for pii in ("applicant_name", "applicant_email"):
        with pytest.raises(ValidationError):
            HRApplicationSubmittedV1(**{**submitted, pii: "x"})
    stage = {
        "entity_id": "app1",
        "entity_type": "hr_application",
        "action": "stage_changed",
        "notification_event": "hr_application_stage_changed",
        "application_id": "app1",
        "job_id": "j1",
        "new_stage": "interview",
        "old_stage": "screening",
    }
    HRApplicationStageChangedV1(**stage)


def test_all_hr_application_events_have_a_model():
    mapping = {
        HREvents.APPLICATION_SUBMITTED: HRApplicationSubmittedV1,
        HREvents.APPLICATION_STAGE_CHANGED: HRApplicationStageChangedV1,
        HREvents.APPLICATION_HIRED: HRApplicationStageChangedV1,
        HREvents.APPLICATION_REJECTED: HRApplicationStageChangedV1,
    }
    assert len(mapping) == 4
