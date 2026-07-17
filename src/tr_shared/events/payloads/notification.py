"""Typed payloads for notification.* events (tr-crm-core notification module).

Field sets mirror the dicts emitted by
app/modules/notification/services/notifications/{notification_service,expiry_actions}.py.
All ids are str.
"""

from tr_shared.events.payloads._base import EventPayload


class NotificationSentV1(EventPayload):
    notification_id: str
    recipient_id: str
    module: str
    event: str
    channels: list[str]
    priority: str


class NotificationLeadOverdueRequestedV1(EventPayload):
    notification_id: str | None = None
    lead_id: str
    entity_type: str
