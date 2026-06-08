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
    import tr_shared  # noqa: F401
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
    assert tr_shared.__version__ == "0.15.0"
