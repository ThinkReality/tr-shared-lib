# tests/test_task_payloads.py
import pytest
from pydantic import ValidationError

from tr_shared.events.payloads.task import (
    TaskAssignedV1,
    TaskCoAssignedV1,
    TaskCreatedV1,
    TaskDueSoonV1,
    TaskStatusChangedV1,
    TaskWatcherAddedV1,
)

BASE = {
    "task_id": "t1",
    "title": "Call client",
    "status": "open",
    "priority": "high",
    "entity_type": "lead",
    "entity_id": "e1",
    "assigned_to": "u1",
}


def test_created_matches_emitted_shape():
    data = {**BASE, "action": "created"}
    assert TaskCreatedV1(**data).model_dump() == data


def test_assigned_and_due_soon_share_base_shape():
    assert TaskAssignedV1(**{**BASE, "action": "assigned"}).action == "assigned"
    assert TaskDueSoonV1(**{**BASE, "action": "due_soon"}).action == "due_soon"


def test_status_changed_adds_prev_and_new():
    data = {**BASE, "action": "status_changed", "prev_status": "open", "new_status": "done"}
    p = TaskStatusChangedV1(**data)
    assert (p.prev_status, p.new_status) == ("open", "done")


def test_watcher_added_and_co_assigned_extras():
    w = TaskWatcherAddedV1(**{**BASE, "action": "watcher_added", "watcher_user_id": "w1"})
    assert w.watcher_user_id == "w1"
    c = TaskCoAssignedV1(**{**BASE, "action": "co_assigned", "co_assignee_user_id": "c1"})
    assert c.co_assignee_user_id == "c1"


def test_nullable_entity_fields():
    data = {**BASE, "action": "created", "entity_type": None, "entity_id": None, "assigned_to": None}
    assert TaskCreatedV1(**data).entity_id is None


def test_unknown_key_is_forbidden():
    with pytest.raises(ValidationError):
        TaskCreatedV1(**{**BASE, "action": "created", "bogus": 1})
