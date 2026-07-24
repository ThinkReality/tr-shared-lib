from tr_shared.logging import (
    safe_log_context,
    sanitize_context,
    sanitize_for_logging,
    sanitize_traceback,
)


def test_safe_log_context_redacts_email_and_long_tokens():
    try:
        raise ValueError("failed for user@example.com with token abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ")
    except ValueError as e:
        ctx = safe_log_context(e)
        assert "user@example.com" not in ctx["error"]
        assert "[REDACTED:email]" in ctx["error"]


def test_sanitize_traceback_redacts_email():
    tb = "Error for user user@example.com at line 42"
    result = sanitize_traceback(tb)
    assert "user@example.com" not in result
    assert "[REDACTED:email]" in result


def test_sanitize_for_logging_redacts_sensitive_keys():
    data = {"email": "alice@example.com", "name": "Alice"}
    result = sanitize_for_logging(data)
    assert result["email"] == "[REDACTED]"
    assert result["name"] == "Alice"


def test_sanitize_context_redacts_sensitive_keys_by_type():
    ctx = {"token": "secret-value", "count": 5}
    result = sanitize_context(ctx)
    assert result["token"] == "[REDACTED:str]"
    assert result["count"] == "int"
