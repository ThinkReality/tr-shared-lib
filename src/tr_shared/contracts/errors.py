"""The CATEGORY segment of an error code, {PREFIX}_{CATEGORY}_{NNN}; each value belongs to one shared exception."""

from enum import StrEnum


class ErrorCategory(StrEnum):
    VALIDATION = "VALIDATION"
    AUTH = "AUTH"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"
    RATE_LIMIT = "RATE_LIMIT"
    DATABASE = "DATABASE"
    INTERNAL = "INTERNAL"
    BAD_GATEWAY = "BAD_GATEWAY"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
