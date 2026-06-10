# tests/test_new_event_registries.py
from tr_shared.events.event_types import NotificationEvents, TaskEvents, WAMEvents


def test_task_events():
    assert TaskEvents.CREATED == "task.created"
    assert TaskEvents.ASSIGNED == "task.assigned"
    assert TaskEvents.CO_ASSIGNED == "task.co_assigned"
    assert TaskEvents.STATUS_CHANGED == "task.status_changed"
    assert TaskEvents.DUE_SOON == "task.due_soon"
    assert TaskEvents.WATCHER_ADDED == "task.watcher_added"


def test_notification_events():
    assert NotificationEvents.LEAD_REASSIGN_REQUESTED == "notification.lead.reassign_requested"
    assert NotificationEvents.LEAD_OVERDUE_REQUESTED == "notification.lead.overdue_requested"
    assert NotificationEvents.SENT == "notification.sent"


def test_finance_events_expense_invoice_card():
    from tr_shared.events.event_types import FinanceEvents

    assert FinanceEvents.EXPENSE_CREATED == "finance.expense.created"
    assert FinanceEvents.EXPENSE_SUBMITTED == "finance.expense.submitted"
    assert FinanceEvents.EXPENSE_APPROVED == "finance.expense.approved"
    assert FinanceEvents.EXPENSE_REJECTED == "finance.expense.rejected"
    assert FinanceEvents.EXPENSE_PAID == "finance.expense.paid"
    assert FinanceEvents.EXPENSE_REIMBURSED == "finance.expense.reimbursed"
    assert FinanceEvents.INVOICE_CREATED == "finance.invoice.created"
    assert FinanceEvents.INVOICE_SENT == "finance.invoice.sent"
    assert FinanceEvents.INVOICE_PAYMENT_RECORDED == "finance.invoice.payment_recorded"
    assert FinanceEvents.CARD_TRANSACTION_IMPORTED == "finance.card_transaction.imported"
    assert FinanceEvents.CARD_TRANSACTION_MATCHED == "finance.card_transaction.matched"


def test_deal_and_hr_offer_events():
    from tr_shared.events.event_types import DealEvents, HREvents

    assert DealEvents.AMOUNT_CHANGED == "deal.amount_changed"
    assert HREvents.OFFER_SENT == "hr.offer.sent"
    assert HREvents.OFFER_ACCEPTED == "hr.offer.accepted"


def test_wam_events():
    assert WAMEvents.LEAD_QUALIFIED == "wam.lead.qualified"


def test_new_registries_exported_from_events_package():
    from tr_shared.events import NotificationEvents as NE
    from tr_shared.events import TaskEvents as TE
    from tr_shared.events import WAMEvents as WE

    assert TE.CREATED == "task.created"
    assert NE.LEAD_OVERDUE_REQUESTED == "notification.lead.overdue_requested"
    assert WE.LEAD_QUALIFIED == "wam.lead.qualified"


def test_cms_page_review_events():
    from tr_shared.events.event_types import CMSEvents

    assert CMSEvents.PAGE_UNPUBLISHED == "cms.page.unpublished"
    assert CMSEvents.PAGE_REVIEW_REQUESTED == "cms.page.review_requested"
    assert CMSEvents.PAGE_APPROVED == "cms.page.approved"
    assert CMSEvents.PAGE_REJECTED == "cms.page.rejected"


def test_contracts_and_registries_all_importable():
    from tr_shared.contracts import (  # noqa: F401
        GLOSSARY,
        Channel,
        EntityType,
        Feature,
        Priority,
        Term,
    )
    from tr_shared.events import (  # noqa: F401
        NotificationEvents,
        TaskEvents,
        WAMEvents,
    )

    assert Feature.LEAD == "lead"
