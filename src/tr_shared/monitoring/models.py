"""
SQLAlchemy models for the central monitoring database.

These models define the ``monitoring`` schema tables used by
Layer 2 persistence. They do NOT inherit from ``tr_shared.db.base.BaseModel``
because monitoring tables have different requirements:

- ``tenant_id`` is nullable (public/health requests have no tenant)
- No soft-delete or audit columns needed
- Partitioning on ``request_logs`` by date

The admin panel owns the Alembic migration for these tables.
Celery tasks write to them; the admin panel reads from them.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class MonitoringBase(DeclarativeBase):
    """Separate declarative base for monitoring tables."""
    pass


class MonitoringRequestLog(MonitoringBase):
    """
    Individual request log — Layer 2 raw data.

    Partitioned by ``date`` in PostgreSQL. Partitions are created
    daily by the ``monitoring.create_partition`` Celery task.
    """
    __tablename__ = "request_logs"
    __table_args__ = (
        {"schema": "monitoring"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    service_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)


class MonitoringMetricsHourly(MonitoringBase):
    """Hourly aggregation of request_logs."""
    __tablename__ = "metrics_hourly"
    __table_args__ = (
        UniqueConstraint(
            "service_name", "date", "hour", "endpoint", "tenant_id",
            name="uq_monitoring_metrics_hourly",
        ),
        {"schema": "monitoring"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    service_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rate_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    avg_response_time_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    min_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p95_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p99_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_request_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_response_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC),
    )


class MonitoringMetricsDaily(MonitoringBase):
    """Daily aggregation of metrics_hourly."""
    __tablename__ = "metrics_daily"
    __table_args__ = (
        UniqueConstraint(
            "service_name", "date", "endpoint", "tenant_id",
            name="uq_monitoring_metrics_daily",
        ),
        {"schema": "monitoring"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    service_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rate_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    avg_requests_per_hour: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    avg_response_time_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    p95_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p99_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC),
    )


class MonitoringTenantUsage(MonitoringBase):
    """Daily per-tenant usage summary."""
    __tablename__ = "tenant_usage"
    __table_args__ = (
        UniqueConstraint(
            "service_name", "tenant_id", "date",
            name="uq_monitoring_tenant_usage",
        ),
        {"schema": "monitoring"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    service_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rate_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    avg_response_time_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    total_request_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=0)
    total_response_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC),
    )
