"""
Standard response schemas for ThinkRealty microservices.

All services should use these schemas for API responses to ensure
consistent response envelopes across the platform.

Usage:
    from tr_shared.schemas import (
        SuccessResponse, ErrorResponse,
        PaginatedResponse, PaginationData,
    )
"""

import logging
import math
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, model_validator

_logger = logging.getLogger(__name__)

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success response envelope.

    Example::

        {
            "status": "success",
            "message": "Operation completed",
            "data": { ... }
        }
    """

    status: str = "success"
    message: str = "Operation completed successfully"
    data: T | None = None


class ErrorResponse(BaseModel):
    """Standard error response envelope.

    Example::

        {
            "status": "error",
            "error": "Validation failed",
            "detail": "Price must be greater than 0",
            "code": "LISTING_VALIDATION_001"
        }
    """

    status: str = "error"
    error: str
    detail: str | None = None
    code: str | None = None
    fields: dict[str, list[str]] | None = None


class PaginationData(BaseModel, Generic[T]):
    """Pagination data container with items and metadata."""

    items: list[T]
    total: int = Field(description="Total number of items across all pages")
    page: int = Field(ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(ge=1, description="Number of items per page")
    total_pages: int = Field(ge=0, description="Total number of pages")

    @model_validator(mode="after")
    def _validate_total_pages(self) -> "PaginationData[T]":
        expected = math.ceil(self.total / self.page_size) if self.page_size else 0
        if self.total_pages != expected:
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
    """Paginated response envelope wrapping PaginationData.

    Example::

        {
            "status": "success",
            "message": "Items retrieved",
            "data": {
                "items": [...],
                "total": 100,
                "page": 1,
                "page_size": 20,
                "total_pages": 5
            }
        }
    """

    status: str = "success"
    message: str = "Items retrieved successfully"
    data: PaginationData[T]
