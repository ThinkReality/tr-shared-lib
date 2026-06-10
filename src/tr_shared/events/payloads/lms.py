"""Typed payloads for lms.quiz.* events (tr-crm-core learning module).

Field sets mirror the dicts emitted by app/modules/learning/services/
{admin_notifier,agent_assignment_notifier,expiry_notifier}.py. All ids are str.
"""

from tr_shared.events.payloads._base import EventPayload


class LMSQuizGeneratedV1(EventPayload):
    recipient_id: str
    entity_type: str
    entity_id: str
    quiz_title: str
    questions_count: int
    review_url: str


class LMSQuizAssignedV1(EventPayload):
    recipient_id: str
    entity_type: str
    entity_id: str
    quiz_id: str
    quiz_title: str
    expires_at: str | None = None
    questions_count: int


class LMSQuizExpiredV1(EventPayload):
    recipient_id: str
    entity_type: str
    entity_id: str
    quiz_id: str
    quiz_title: str
    expired_at: str | None = None
    audit: bool
