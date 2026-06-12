"""Round-trip + strictness tests for hr.* and finance.* payloads (P5).

The dicts below mirror exactly what the people-finance HR and finance event
publishers emit for each event.
"""

import pytest
from pydantic import ValidationError

from tr_shared.events.envelope import EventEnvelope
from tr_shared.events.helpers import parse_payload
from tr_shared.events.payloads.finance import (
    FinanceExpenseEventV1,
    FinanceExpenseRejectedV1,
)
from tr_shared.events.payloads.hr import (
    HRAttendanceCorrectionV1,
    HRJobPostingClosedV1,
    HRJobPostingPublishedV1,
    HRManualEntryCreatedV1,
    HRSyncFailedV1,
)


def _env(event_type: str, data: dict) -> EventEnvelope:
    return EventEnvelope(
        event_id="e",
        event_type=event_type,
        version="1.0",
        tenant_id="ten1",
        timestamp="2026-01-01T00:00:00Z",
        source_service="people-finance",
        actor_id=None,
        data=data,
    )


_EXPENSE = {
    "entity_type": "expense",
    "entity_id": "ex1",
    "expense_id": "ex1",
    "title": "Team lunch",
    "amount": "100.00",
    "currency": "AED",
    "base_amount": "100.00",
    "status": "submitted",
    "payment_type": "personal",
    "category_id": "cat1",
    "description": "lunch",
    "expense_date": "2026-01-01",
    "submitted_by": "u1",
    "submitted_at": "2026-01-01T00:00:00Z",
    "notification_recipient_id": "u2",
}
_EXPENSE_REJECTED = {**_EXPENSE, "status": "rejected", "rejection_comment": "over budget"}

_MANUAL = {
    "entity_id": "m1",
    "entity_type": "attendance_manual_entry",
    "action": "created",
    "notification_event": "hr_attendance_manual_entry_created",
    "manual_entry_id": "m1",
    "employee_id": "emp1",
    "attendance_id": "a1",
}
_CORRECTION = {
    "entity_id": "m1",
    "entity_type": "attendance_manual_entry",
    "action": "correction_created",
    "notification_event": "hr_attendance_correction_created",
    "manual_entry_id": "m1",
    "attendance_id": "a1",
    "employee_id": "emp1",
}
_SYNC = {
    "entity_id": "t1",
    "entity_type": "hr_sync_task",
    "action": "failed",
    "notification_event": "hr_sync_failed",
    "sync_type": "attendance_full",
    "error": "boom",
    "task_id": "t1",
}
_JOB_PUB = {
    "entity_id": "j1",
    "entity_type": "job_posting",
    "action": "published",
    "notification_event": "hr_job_posting_published",
    "job_id": "j1",
    "title": "Engineer",
    "slug": "engineer",
    "share_url": "https://careers/engineer",
}
_JOB_CLOSE = {
    "entity_id": "j1",
    "entity_type": "job_posting",
    "action": "closed",
    "notification_event": "hr_job_posting_closed",
    "job_id": "j1",
    "title": "Engineer",
}


@pytest.mark.parametrize(
    ("event_type", "data", "model"),
    [
        ("finance.expense.submitted", _EXPENSE, FinanceExpenseEventV1),
        ("finance.expense.approved", _EXPENSE, FinanceExpenseEventV1),
        ("finance.expense.paid", _EXPENSE, FinanceExpenseEventV1),
        ("finance.expense.reimbursed", _EXPENSE, FinanceExpenseEventV1),
        ("finance.expense.rejected", _EXPENSE_REJECTED, FinanceExpenseRejectedV1),
        ("hr.attendance.manual_entry.created", _MANUAL, HRManualEntryCreatedV1),
        ("hr.attendance.record.corrected", _CORRECTION, HRAttendanceCorrectionV1),
        ("hr.sync.failed", _SYNC, HRSyncFailedV1),
        ("hr.job_posting.published", _JOB_PUB, HRJobPostingPublishedV1),
        ("hr.job_posting.closed", _JOB_CLOSE, HRJobPostingClosedV1),
    ],
)
def test_roundtrip_matches_emitted_dict(event_type, data, model):
    parsed = parse_payload(_env(event_type, data), model)
    assert parsed.model_dump() == data


def test_extra_key_rejected():
    with pytest.raises(ValidationError):
        FinanceExpenseEventV1(**{**_EXPENSE, "bogus": "x"})


def test_required_keys_enforced():
    incomplete = {k: v for k, v in _EXPENSE.items() if k != "expense_id"}
    with pytest.raises(ValidationError):
        FinanceExpenseEventV1(**incomplete)


def test_optionals_default_to_none():
    p = HRJobPostingPublishedV1(
        entity_id="j1",
        entity_type="job_posting",
        action="published",
        notification_event="hr_job_posting_published",
        job_id="j1",
        title="Engineer",
        slug="engineer",
    )
    assert p.share_url is None
