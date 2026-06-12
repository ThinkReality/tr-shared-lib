"""Typed event payloads. EventPayload is the strict base; per-feature modules
hold the {Feature}{Event}{Vn} models. Additive within a Vn; breaking = new Vn."""

from tr_shared.events.payloads._base import EventPayload
from tr_shared.events.payloads.activity import (
    ActivityCommentAddedV1,
    ActivityCommentDeletedV1,
    ActivityCommentEditedV1,
    ActivityLogCreatedV1,
)
from tr_shared.events.payloads.admin import (
    AdminAssignmentRuleCreatedV1,
    AdminLeadScoringCreatedV1,
    AdminLeadScoringDeletedV1,
    AdminLeadScoringUpdatedV1,
    AdminLeadSourceCreatedV1,
    AdminLeadSourceDeletedV1,
    AdminLeadSourceUpdatedV1,
    AdminModuleConfigurationUpdatedV1,
    AdminNurtureCampaignCreatedV1,
    AdminNurtureCampaignUpdatedV1,
    IntegrationPlatformEventV1,
)
from tr_shared.events.payloads.auth import (
    AdminRoleAssignedV1,
    AdminUserCreatedV1,
    AdminUserUpdatedV1,
)
from tr_shared.events.payloads.listing import (
    ListingDeletedV1,
    ListingExpiredV1,
    ListingPfEventV1,
    ListingRepublishedV1,
    ListingSaleV1,
)
from tr_shared.events.payloads.lms import (
    LMSQuizAssignedV1,
    LMSQuizExpiredV1,
    LMSQuizGeneratedV1,
)
from tr_shared.events.payloads.notification import (
    NotificationLeadOverdueRequestedV1,
    NotificationLeadReassignRequestedV1,
    NotificationSentV1,
)
from tr_shared.events.payloads.task import (
    TaskAssignedV1,
    TaskCoAssignedV1,
    TaskCreatedV1,
    TaskDueSoonV1,
    TaskEventV1,
    TaskStatusChangedV1,
    TaskWatcherAddedV1,
)

__all__ = [
    "EventPayload",
    # activity
    "ActivityCommentAddedV1",
    "ActivityCommentDeletedV1",
    "ActivityCommentEditedV1",
    "ActivityLogCreatedV1",
    # admin
    "AdminAssignmentRuleCreatedV1",
    "AdminLeadScoringCreatedV1",
    "AdminLeadScoringDeletedV1",
    "AdminLeadScoringUpdatedV1",
    "AdminLeadSourceCreatedV1",
    "AdminLeadSourceDeletedV1",
    "AdminLeadSourceUpdatedV1",
    "AdminModuleConfigurationUpdatedV1",
    "AdminNurtureCampaignCreatedV1",
    "AdminNurtureCampaignUpdatedV1",
    "IntegrationPlatformEventV1",
    # auth (admin.user.* / admin.role.*)
    "AdminRoleAssignedV1",
    "AdminUserCreatedV1",
    "AdminUserUpdatedV1",
    # listing (PF-keyed lifecycle)
    "ListingDeletedV1",
    "ListingExpiredV1",
    "ListingPfEventV1",
    "ListingRepublishedV1",
    "ListingSaleV1",
    # lms
    "LMSQuizAssignedV1",
    "LMSQuizExpiredV1",
    "LMSQuizGeneratedV1",
    # notification
    "NotificationLeadOverdueRequestedV1",
    "NotificationLeadReassignRequestedV1",
    "NotificationSentV1",
    # task
    "TaskAssignedV1",
    "TaskCoAssignedV1",
    "TaskCreatedV1",
    "TaskDueSoonV1",
    "TaskEventV1",
    "TaskStatusChangedV1",
    "TaskWatcherAddedV1",
]
