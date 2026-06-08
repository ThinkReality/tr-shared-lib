"""Typed payloads for task.* events (tr-crm-core task module).

Field set mirrors the dict emitted by app/modules/task/events.py:_task_payload
plus each event's extra keys. All ids are str (UUIDs are stringified at emit).
"""

from tr_shared.events.payloads._base import EventPayload


class TaskEventV1(EventPayload):
    task_id: str
    title: str
    status: str
    priority: str
    entity_type: str | None = None
    entity_id: str | None = None
    assigned_to: str | None = None
    action: str


class TaskCreatedV1(TaskEventV1):
    pass


class TaskAssignedV1(TaskEventV1):
    pass


class TaskDueSoonV1(TaskEventV1):
    pass


class TaskStatusChangedV1(TaskEventV1):
    prev_status: str
    new_status: str


class TaskWatcherAddedV1(TaskEventV1):
    watcher_user_id: str


class TaskCoAssignedV1(TaskEventV1):
    co_assignee_user_id: str
