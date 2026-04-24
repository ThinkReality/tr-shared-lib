"""Canonical event type registry for the ThinkRealty event bus.

All event types published to ``tr_event_bus`` MUST be defined here.
Services import constants rather than using raw string literals so typos
are caught at import time and grep/refactor works globally.

Naming convention
-----------------
``{domain}.{action}``                 — simple events  (lead.created)
``{domain}.{subdomain}.{action}``     — nested domains (cms.blog.published)
"""


class LeadEvents:
    """Events produced by tr-lead-management."""

    CREATED = "lead.created"
    UPDATED = "lead.updated"
    DELETED = "lead.deleted"
    ASSIGNED = "lead.assigned"
    REASSIGNED = "lead.reassigned"
    STATUS_CHANGED = "lead.status_changed"
    SOURCE_CHANGED = "lead.source_changed"
    PRIORITY_CHANGED = "lead.priority_changed"
    OWNER_CHANGED = "lead.owner_changed"
    CONTACT_ATTEMPTED = "lead.contact_attempted"
    CONTACTED = "lead.contacted"
    QUALIFIED = "lead.qualified"
    DISQUALIFIED = "lead.disqualified"
    CONVERTED = "lead.converted"
    LOST = "lead.lost"
    WON = "lead.won"
    ARCHIVED = "lead.archived"
    UNARCHIVED = "lead.unarchived"
    NOTE_ADDED = "lead.note_added"
    REMINDER_SET = "lead.reminder_set"
    REMINDER_DUE = "lead.reminder_due"
    ROLLBACK = "lead.rollback"
    FOLLOWUP_DUE = "lead.followup_due"


class DealEvents:
    """Events produced by tr-lead-management (deal pipeline)."""

    CREATED = "deal.created"
    WON = "deal.won"
    LOST = "deal.lost"
    STAGE_CHANGED = "deal.stage_changed"
    COMPLETED = "deal.completed"
    CANCELLED = "deal.cancelled"
    ROLLED_BACK = "deal.rolled_back"


class ListingEvents:
    """Events produced by tr-listing-service."""

    CREATED = "listing.created"
    UPDATED = "listing.updated"
    PUBLISHED = "listing.published"
    UNPUBLISHED = "listing.unpublished"
    ARCHIVED = "listing.archived"
    VERIFIED = "listing.verified"
    REJECTED = "listing.rejected"
    RESUBMITTED = "listing.resubmitted"
    DOCUMENT_SUBMITTED = "listing.document_submitted"
    PUBLISH_REQUESTED = "listing.publish_requested"
    PRICE_CHANGED = "listing.price_changed"
    OWNER_CHANGED = "listing.owner_changed"


class CMSEvents:
    """Events produced by tr-cms-service."""

    BLOG_CREATED = "cms.blog.created"
    BLOG_UPDATED = "cms.blog.updated"
    BLOG_PUBLISHED = "cms.blog.published"
    BLOG_UNPUBLISHED = "cms.blog.unpublished"
    BLOG_DELETED = "cms.blog.deleted"
    PAGE_CREATED = "cms.page.created"
    PAGE_UPDATED = "cms.page.updated"
    PAGE_PUBLISHED = "cms.page.published"
    PAGE_DELETED = "cms.page.deleted"


class ActivityEvents:
    """Events produced by tr-activity-service and consumed for activity logging."""

    COMMENT_ADDED = "activity.comment.added"
    MENTION_CREATED = "activity.mention.created"
    LOGGED = "activity.logged"


class AdminEvents:
    """Events produced by crm-backend and tr-be-admin-panel."""

    USER_CREATED = "admin.user.created"
    USER_UPDATED = "admin.user.updated"
    ROLE_ASSIGNED = "admin.role.assigned"
    INTEGRATION_PLATFORM_CREATED = "admin.integration.platform.created"
    INTEGRATION_PLATFORM_UPDATED = "admin.integration.platform.updated"
    INTEGRATION_PLATFORM_DELETED = "admin.integration.platform.deleted"
    MODULE_CONFIGURATION_UPDATED = "admin.module.configuration.updated"
    ASSIGNMENT_RULE_CREATED = "admin.assignment_rule.created"
    ASSIGNMENT_RULE_UPDATED = "admin.assignment_rule.updated"
    ASSIGNMENT_RULE_DELETED = "admin.assignment_rule.deleted"
    NURTURE_CAMPAIGN_CREATED = "admin.nurture_campaign.created"
    NURTURE_CAMPAIGN_UPDATED = "admin.nurture_campaign.updated"
    NURTURE_CAMPAIGN_DELETED = "admin.nurture_campaign.deleted"
    LEAD_SCORING_CREATED = "admin.lead_scoring.created"
    LEAD_SCORING_UPDATED = "admin.lead_scoring.updated"
    LEAD_SCORING_DELETED = "admin.lead_scoring.deleted"
    LEAD_SOURCE_CREATED = "admin.lead_source.created"
    LEAD_SOURCE_UPDATED = "admin.lead_source.updated"
    LEAD_SOURCE_DELETED = "admin.lead_source.deleted"


class MediaEvents:
    """Events produced by tr-media-service."""

    UPLOADED = "media.uploaded"
    OCR_COMPLETED = "media.ocr_completed"
    DELETED = "media.deleted"


class HREvents:
    """Events produced by TR-HR-System-be."""

    EMPLOYEE_CREATED = "hr.employee.created"
    EMPLOYEE_UPDATED = "hr.employee.updated"
    EMPLOYEE_SYNC_COMPLETED = "hr.employee.sync_completed"
    ATTENDANCE_SYNCED = "hr.attendance.synced"
    PAYROLL_CALCULATED = "hr.payroll.calculated"
    PAYROLL_APPROVED = "hr.payroll.approved"
    PAYROLL_REJECTED = "hr.payroll.rejected"
    JOB_POSTING_PUBLISHED = "hr.job_posting.published"
    JOB_POSTING_CLOSED = "hr.job_posting.closed"
    APPLICATION_SUBMITTED = "hr.application.submitted"
    APPLICATION_STAGE_CHANGED = "hr.application.stage_changed"
    APPLICATION_HIRED = "hr.application.hired"
    APPLICATION_REJECTED = "hr.application.rejected"
    OFFER_SENT = "hr.offer.sent"
    OFFER_ACCEPTED = "hr.offer.accepted"


class LMSEvents:
    """Events consumed by tr-notification-service (produced by tr-lms-service)."""

    COURSE_COMPLETED = "lms.course.completed"
    CERTIFICATE_ISSUED = "lms.certificate.issued"


class FinanceEvents:
    """Events consumed by tr-notification-service."""

    COMMISSION_PAID = "finance.commission.paid"
    INVOICE_PAID = "finance.invoice.paid"
