"""Canonical record-kind taxonomy. Every entity type is Feature-prefixed so that
event `source` and entity prefix always agree, and the frontend can filter by
feature. Format: `{feature}` (single-record-kind features) or `{feature}.{entity}`.
"""

from enum import StrEnum

from tr_shared.contracts.taxonomy import Feature


class EntityType(StrEnum):
    LEAD = "lead"
    DEAL = "deal"
    CONTACT = "contact"
    PROPERTY = "property"
    LISTING = "listing"
    CMS_BLOG = "cms.blog"
    CMS_PAGE = "cms.page"
    LMS_COURSE = "lms.course"
    LMS_CERTIFICATE = "lms.certificate"
    TASK = "task"
    ACTIVITY_COMMENT = "activity.comment"
    HR_EMPLOYEE = "hr.employee"
    HR_APPLICATION = "hr.application"
    HR_OFFER = "hr.offer"
    HR_ATTENDANCE_RECORD = "hr.attendance_record"
    HR_ATTENDANCE_EXCEPTION = "hr.attendance_exception"
    HR_ATTENDANCE_MANUAL_ENTRY = "hr.attendance_manual_entry"
    HR_ATTENDANCE_SYNC_JOB = "hr.attendance_sync_job"
    FINANCE_COMMISSION = "finance.commission"
    FINANCE_INVOICE = "finance.invoice"
    FINANCE_EXPENSE = "finance.expense"
    ADMIN_USER = "admin.user"
    MEDIA = "media"

    def feature(self) -> Feature:
        """Return the owning Feature (prefix before the first dot, else whole value)."""
        return Feature(self.value.split(".", 1)[0])
