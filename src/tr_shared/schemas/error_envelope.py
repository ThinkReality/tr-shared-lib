# SSOT for the error envelope — all error paths converge here so the shape never diverges.

import re
from typing import Any

from starlette.applications import Starlette

VALIDATION_CODE = "VALIDATION_000"
INTERNAL_CODE = "INTERNAL_000"
CONFLICT_CODE = "CONFLICT_000"

_CODE_PREFIX = re.compile(r"[A-Z]+")


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


def set_error_code_prefix(app: Starlette, code_prefix: str) -> None:
    if not _CODE_PREFIX.fullmatch(code_prefix):
        raise ValueError(f"code_prefix must be upper-case letters only, got {code_prefix!r}")
    app.state.error_code_prefix = code_prefix


def framework_error_code(app: Starlette, suffix: str) -> str:
    code_prefix = getattr(app.state, "error_code_prefix", None)
    if code_prefix is None:
        raise RuntimeError(
            "This app has no error code prefix: call "
            "register_exception_handlers(app, code_prefix=...) at startup."
        )
    return f"{code_prefix}_{suffix}"
