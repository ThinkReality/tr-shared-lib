"""The Feature taxonomy spine — the one canonical business-capability vocabulary.

A Feature is a frontend feature / domain / bounded context. It is the stable
spine that replaces the five overlapping taxonomies (SourceService, EntityType
prefix, code module, permission module, deployable). Event `source`, entity-type
prefixes, and permission scopes all draw from this vocabulary. Deployable names
(tr-crm-core, ...) are infra facts and never appear in contracts.
"""

from enum import StrEnum


class Feature(StrEnum):
    AUTH = "auth"
    LEAD = "lead"
    DEAL = "deal"
    CONTACT = "contact"
    PROPERTY = "property"
    LISTING = "listing"
    CMS = "cms"
    LMS = "lms"
    TASK = "task"
    ACTIVITY = "activity"
    NOTIFICATION = "notification"
    HR = "hr"
    FINANCE = "finance"
    ADMIN = "admin"  # campaign is a sub-concept of admin, not first-class
    MEDIA = "media"
    DLD = "dld"
    WAM = "wam"
