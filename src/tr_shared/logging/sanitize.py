import re
import traceback
from typing import Any

MAX_STRING_LENGTH = 20
MIN_TOKEN_LENGTH = 50
MIN_TOKEN_DOTS = 2

SENSITIVE_FIELDS = {
    "email",
    "password",
    "token",
    "secret",
    "api_key",
    "authorization",
    "credit_card",
    "ssn",
    "phone",
    "phone_number",
    "mobile",
    "address",
    "context",
    "data",
    "user_metadata",
    "headers",
    "bearer",
    "jwt",
}


def sanitize_for_logging(
    data: Any,
    max_depth: int = 3,
) -> Any:
    """
    Recursively sanitize sensitive data for logging.
    Replaces sensitive values with '[REDACTED]' or '[REDACTED:type]'
    """
    if max_depth <= 0:
        return "[MAX_DEPTH_REACHED]"

    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            is_sensitive = any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS)

            if is_sensitive:
                if isinstance(value, (dict, list)):
                    sanitized[key] = f"[REDACTED:{type(value).__name__}]"
                elif isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
                    sanitized[key] = "[REDACTED:long_string]"
                else:
                    sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_for_logging(value, max_depth - 1)
        return sanitized

    if isinstance(data, list):
        return [sanitize_for_logging(item, max_depth - 1) for item in data[:10]]

    if isinstance(data, str):
        if re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", data):
            return "[REDACTED:email]"
        if len(data) > MIN_TOKEN_LENGTH and data.count(".") >= MIN_TOKEN_DOTS:
            return "[REDACTED:token]"
        return data

    return data


def sanitize_traceback(traceback_str: str) -> str:
    """Sanitize a traceback / error string before logging.

    Redacts, in order: email addresses, URL-embedded credentials, SQL bound-parameter
    blocks (asyncpg/psycopg echo row values — e.g. device tokens — verbatim there),
    key/value secrets (authorization/token/secret/api_key/password/bearer), and long
    opaque tokens (JWTs, API keys). UUIDs are intentionally preserved — they are
    correlation identifiers, not secrets.
    """
    if not traceback_str:
        return traceback_str

    traceback_str = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "[REDACTED:email]",
        traceback_str,
        flags=re.IGNORECASE,
    )
    # URL-embedded credentials: scheme://user:password@host → redact the password
    traceback_str = re.sub(
        r"(://[^:/\s@]+:)[^@/\s]+(@)",
        r"\1[REDACTED:credential]\2",
        traceback_str,
    )
    # SQL bound-parameter blocks: "[parameters: (...)]" / "[parameters: {...}]"
    traceback_str = re.sub(
        r"(\[parameters:\s*).*?(\])",
        r"\1[REDACTED]\2",
        traceback_str,
        flags=re.IGNORECASE | re.DOTALL,
    )
    traceback_str = re.sub(
        r"(?i)\bbearer\s+[A-Za-z0-9._\-]+",
        "Bearer [REDACTED:token]",
        traceback_str,
    )
    # key=value / key: value secrets (covers short secrets the length heuristic misses)
    traceback_str = re.sub(
        r"(?i)\b(authorization|api[_-]?key|secret|token|password|passwd|pwd)\b"
        r"(['\"]?\s*[:=]\s*['\"]?)([^\s'\",;]+)",
        r"\1\2[REDACTED]",
        traceback_str,
    )
    # Long opaque tokens (JWTs, API keys), keep UUIDs which are shorter / hyphen-split
    token_pattern = rf"\b[a-zA-Z0-9_-]{{{MIN_TOKEN_LENGTH},}}\b"
    return re.sub(token_pattern, "[REDACTED:token]", traceback_str)


def safe_log_context(error: BaseException) -> dict[str, str]:
    """Sanitized error + traceback for structured logging.

    Use this instead of ``exc_info=True`` or ``logger.exception(...)``: those
    attach the RAW traceback (SQL bound parameters, device tokens, emails,
    payloads) to the log record, bypassing redaction. Spread the result into
    the log call's ``extra``:

        logger.error("delivery_failed", extra={**ctx, **safe_log_context(e)})
    """
    return {
        "error": sanitize_traceback(str(error)),
        "traceback": sanitize_traceback(traceback.format_exc()),
    }


def sanitize_context(context: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize notification context data.
    Returns only keys and types, not values.
    """
    if not context:
        return {}

    sanitized = {}
    for key, value in context.items():
        key_lower = str(key).lower()
        is_sensitive = any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS)

        if is_sensitive:
            sanitized[key] = f"[REDACTED:{type(value).__name__}]"
        elif isinstance(value, (dict, list)):
            sanitized[key] = f"[{type(value).__name__}]"
        else:
            sanitized[key] = type(value).__name__

    return sanitized
