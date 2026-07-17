"""Each legacy dict mirrors the exact keys the live crm-core producer emits.
Round-trip equality + extra="forbid" turns producer-side field drift into a
ValidationError at the consumer edge instead of a silent mismatch."""

import pytest
from pydantic import ValidationError

from tr_shared.events.payloads import (
    ActivityCommentAddedV1,
    ActivityCommentEditedV1,
    AdminLeadScoringDeletedV1,
    AdminUserCreatedV1,
    IntegrationPlatformEventV1,
    LMSQuizAssignedV1,
    NotificationSentV1,
)

_CASES = [
    (
        ActivityCommentAddedV1,
        {
            "entity_type": "comment", "entity_id": "e1", "action": "created",
            "comment_id": "c1", "parent_entity_type": "lead", "parent_entity_id": "p1",
            "mentioned_user_ids": ["u1"], "mentions": ["@a"],
        },
    ),
    (
        ActivityCommentEditedV1,
        {
            "entity_type": "comment", "entity_id": "e1", "action": "edited",
            "comment_id": "c1", "parent_entity_type": "lead", "parent_entity_id": "p1",
            "mentioned_user_ids": ["u1", "u2"], "newly_mentioned_user_ids": ["u2"],
            "mentions": ["@a", "@b"],
        },
    ),
    (
        NotificationSentV1,
        {
            "notification_id": "n1", "recipient_id": "r1", "module": "listing",
            "event": "listing.created", "channels": ["in_app"], "priority": "medium",
        },
    ),
    (
        AdminUserCreatedV1,
        {
            "user_id": "u1", "user_name": "Jo",
            "role_names": ["AGENT"], "recipient_id": "r1",
        },
    ),
    (
        LMSQuizAssignedV1,
        {
            "recipient_id": "r1", "entity_type": "quiz", "entity_id": "q1",
            "quiz_id": "q1", "quiz_title": "Quiz", "expires_at": None, "questions_count": 25,
        },
    ),
    (
        IntegrationPlatformEventV1,
        {
            "schema_version": "1.0", "platform_id": "p1", "platform_name": "PF",
            "tenant_id": "t1", "webhook_token": None,
        },
    ),
]


@pytest.mark.parametrize("model,legacy", _CASES)
def test_roundtrip_matches_legacy_dict(model, legacy):
    assert model(**legacy).model_dump(mode="json") == legacy


@pytest.mark.parametrize("model,legacy", _CASES)
def test_extra_key_rejected(model, legacy):
    with pytest.raises(ValidationError):
        model(**{**legacy, "unexpected": "x"})


def test_missing_required_key_rejected():
    with pytest.raises(ValidationError):
        NotificationSentV1(notification_id="n1")


def test_lead_scoring_deleted_count_is_int_only():
    assert AdminLeadScoringDeletedV1(config_id="c1", deleted_count=1).deleted_count == 1
    assert AdminLeadScoringDeletedV1(config_id=None, deleted_count=5).deleted_count == 5
    with pytest.raises(ValidationError):
        AdminLeadScoringDeletedV1(config_id=None, deleted_count="all")
