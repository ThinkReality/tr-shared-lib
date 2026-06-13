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
from tr_shared.events.payloads.cms import (
    CMSBlogEventV1,
    CMSBlogUpdatedV1,
    CMSLandingPageContextV1,
    CMSLandingPageMediaV1,
    CMSLandingPagePublishedV1,
    CMSPageApprovedV1,
    CMSPageEventV1,
    CMSPagePublishedV1,
    CMSPageRejectedV1,
    CMSPageReviewRequestedV1,
    CMSPageUpdatedV1,
)
from tr_shared.events.payloads.finance import (
    FinanceCardTransactionImportedV1,
    FinanceCardTransactionMatchedV1,
    FinanceExpenseEventV1,
    FinanceExpenseRejectedV1,
    FinanceInvoiceEventV1,
)
from tr_shared.events.payloads.hr import (
    HRApplicationStageChangedV1,
    HRApplicationSubmittedV1,
    HRAttendanceCorrectionV1,
    HREventV1,
    HRJobPostingClosedV1,
    HRJobPostingPublishedV1,
    HRManualEntryCreatedV1,
    HRSyncFailedV1,
)
from tr_shared.events.payloads.lead import (
    LeadAssignedV1,
    LeadCreatedV1,
    LeadEventV1,
    LeadFollowupDueV1,
    LeadQualifiedV1,
    LeadStatusChangedV1,
)
from tr_shared.events.payloads.listing import (
    ListingAuditEventV1,
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
from tr_shared.events.payloads.wam import (
    WAMLeadQualifiedV1,
    WAMQualificationResultV1,
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
    # cms (page + blog lifecycle, landing page)
    "CMSBlogEventV1",
    "CMSBlogUpdatedV1",
    "CMSLandingPageContextV1",
    "CMSLandingPageMediaV1",
    "CMSLandingPagePublishedV1",
    "CMSPageApprovedV1",
    "CMSPageEventV1",
    "CMSPagePublishedV1",
    "CMSPageRejectedV1",
    "CMSPageReviewRequestedV1",
    "CMSPageUpdatedV1",
    # finance (expense lifecycle + invoice + card)
    "FinanceCardTransactionImportedV1",
    "FinanceCardTransactionMatchedV1",
    "FinanceExpenseEventV1",
    "FinanceExpenseRejectedV1",
    "FinanceInvoiceEventV1",
    # hr (attendance + recruitment)
    "HRApplicationStageChangedV1",
    "HRApplicationSubmittedV1",
    "HRAttendanceCorrectionV1",
    "HREventV1",
    "HRJobPostingClosedV1",
    "HRJobPostingPublishedV1",
    "HRManualEntryCreatedV1",
    "HRSyncFailedV1",
    # lead
    "LeadAssignedV1",
    "LeadCreatedV1",
    "LeadEventV1",
    "LeadFollowupDueV1",
    "LeadQualifiedV1",
    "LeadStatusChangedV1",
    # listing (PF-keyed lifecycle + audit)
    "ListingAuditEventV1",
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
    # wam
    "WAMLeadQualifiedV1",
    "WAMQualificationResultV1",
]
