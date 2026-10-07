import hmac


def constant_time_equals(a: str | bytes, b: str | bytes) -> bool:
    return hmac.compare_digest(_as_bytes(a), _as_bytes(b))


def _as_bytes(value: str | bytes) -> bytes:
    return value.encode("utf-8") if isinstance(value, str) else value
