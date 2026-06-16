"""Cross-domain shared enums. Canonical values — retired aliases (`urgent`,
`mobile_push`) are recorded in the glossary and must never be re-introduced here.
"""

from enum import StrEnum


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"  # replaces the retired task value `urgent`


class Channel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"  # replaces the retired notification value `mobile_push`
    WHATSAPP = "whatsapp"


class CommentAction(StrEnum):
    """Action carried by activity.comment.* events."""

    CREATED = "created"
    EDITED = "edited"
    DELETED = "deleted"
