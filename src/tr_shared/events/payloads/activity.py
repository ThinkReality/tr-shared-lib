"""Typed payloads for activity.* events (tr-crm-core activity module).

Field sets mirror the dicts emitted by
app/modules/activity/services/comment_event_publisher.py and
app/modules/activity/services/activity_service.py (LOG_CREATED).
All ids are str (UUIDs stringified at emit).
"""

from tr_shared.events.payloads._base import EventPayload


class ActivityCommentAddedV1(EventPayload):
    entity_type: str
    entity_id: str
    action: str
    comment_id: str
    parent_entity_type: str
    parent_entity_id: str
    mentioned_user_ids: list[str]
    mentions: list[str]


class ActivityCommentEditedV1(ActivityCommentAddedV1):
    # Inherits all 8 added-comment keys (incl. mentioned_user_ids) + the diff.
    newly_mentioned_user_ids: list[str]


class ActivityCommentDeletedV1(EventPayload):
    entity_type: str
    entity_id: str
    action: str
    comment_id: str
    parent_entity_type: str
    parent_entity_id: str


class ActivityLogCreatedV1(EventPayload):
    recipient_id: str
    log_id: str
    entity_type: str
    entity_id: str
    event_type: str
    description: str
    actor_name: str | None = None
