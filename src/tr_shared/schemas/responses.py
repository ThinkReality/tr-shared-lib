"""
Standard response schemas for ThinkRealty microservices.

All services should use these schemas for API responses to ensure
consistent response envelopes across the platform.

Usage:
    from tr_shared.schemas import (
        SuccessResponse, ErrorEnvelope,
        PaginatedResponse, PaginationData,
    )
"""

import logging
import math
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

_logger = logging.getLogger(__name__)

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success response envelope."""

    status: str = "success"
    message: str = "Operation completed successfully"
    data: T | None = None


class ErrorDetail(BaseModel):
    """Inner object of the canonical error envelope.

    Mirrors ``build_error_envelope`` output: ``message`` is always present;
    ``code`` / ``correlation_id`` are set on nearly every path; category-specific
    extras (``detail``, ``fields`` for 422, ``retry_after`` for 429, ...) arrive
    via ``**extra`` — hence ``extra="allow"`` so the schema documents the stable
    core without lying about the dynamic keys.
    """

    model_config = ConfigDict(extra="allow")

    message: str
    code: str | None = None
    correlation_id: str | None = None


class ErrorEnvelope(BaseModel):
    """Canonical error response — SSOT for the wire shape produced by
    ``build_error_envelope`` and all handlers registered by
    ``register_exception_handlers``. ``error`` is ALWAYS an object.
    """

    error: ErrorDetail


class PaginationData(BaseModel, Generic[T]):
    """Pagination data container with items and metadata."""

    items: list[T]
    total: int = Field(description="Total number of items across all pages")
    page: int = Field(ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(ge=1, description="Number of items per page")
    total_pages: int | None = Field(
        default=None,
        ge=0,
        description="Total number of pages; computed from total/page_size when omitted",
    )

    @model_validator(mode="after")
    def _validate_total_pages(self) -> "PaginationData[T]":
        expected = math.ceil(self.total / self.page_size) if self.page_size else 0
        if self.total_pages is None:
            self.total_pages = expected
        elif self.total_pages != expected:
            _logger.warning(
                "PaginationData total_pages auto-corrected",
                extra={
                    "given": self.total_pages,
                    "expected": expected,
                    "total": self.total,
                    "page_size": self.page_size,
                },
            )
            self.total_pages = expected
        return self


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response envelope wrapping PaginationData."""

    status: str = "success"
    message: str = "Items retrieved successfully"
    data: PaginationData[T]
