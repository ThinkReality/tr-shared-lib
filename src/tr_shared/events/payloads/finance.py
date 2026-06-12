"""Typed payloads for finance.* events (tr-people-finance finance module).

Scoped to the EXPENSE lifecycle, which is the one unambiguous shape: every
expense event (submitted/approved/paid/reimbursed) serialises through the single
``lifecycle_service._serialize_expense_for_event`` path; rejected reuses it and
appends ``rejection_comment``. The wire dict additionally carries ``entity_type``
+ ``entity_id`` (injected by ``FinanceEventPublisher.publish``) and an optional
``notification_recipient_id``.

The invoice events (created/sent/payment_recorded/paid), card_transaction.matched
and card_transaction.imported are emitted from caller-supplied dict literals built
inline at divergent call sites (no shared serialiser) and are intentionally NOT
modelled here yet — they need emitter canonicalisation first (mirrors the listing
status-change deferral). approval_reminder bypasses the publisher envelope entirely.

Field set mirrors the dict at
app/modules/finance/services/expenses/lifecycle_service.py:_serialize_expense_for_event.
All ids are str (UUIDs stringified at emit); money fields are str (Decimal
stringified); dates are ISO str.
"""

from tr_shared.events.payloads._base import EventPayload


class FinanceExpenseEventV1(EventPayload):
    """finance.expense.submitted / .approved / .paid / .reimbursed.

    Identical shape — one serialiser, one emit path per event.
    """

    entity_type: str
    entity_id: str
    expense_id: str
    title: str
    amount: str
    currency: str
    base_amount: str
    status: str
    payment_type: str
    category_id: str | None = None
    description: str | None = None
    expense_date: str | None = None
    submitted_by: str | None = None
    submitted_at: str | None = None
    notification_recipient_id: str | None = None


class FinanceExpenseRejectedV1(FinanceExpenseEventV1):
    """finance.expense.rejected — adds the approver's rejection comment."""

    rejection_comment: str
