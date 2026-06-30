# SSOT for the error envelope — all error paths converge here so the shape never diverges.

from typing import Any


def build_error_envelope(
    message: str,
    code: str | None = None,
    correlation_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    inner: dict[str, Any] = {"message": message}
    if code is not None:
        inner["code"] = code
    if correlation_id is not None:
        inner["correlation_id"] = correlation_id
    for key, value in extra.items():
        if value is not None:
            inner[key] = value
    return {"error": inner}
