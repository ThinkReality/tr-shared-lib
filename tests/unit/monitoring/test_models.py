"""Tests for monitoring SQLAlchemy models — column definitions and instantiation."""

import uuid
from datetime import UTC, date, datetime

import pytest

from tr_shared.monitoring.models import (
    MonitoringBase,
    MonitoringMetricsDaily,
    MonitoringMetricsHourly,
    MonitoringRequestLog,
    MonitoringTenantUsage,
)


# ---------------------------------------------------------------------------
# MonitoringBase
# ---------------------------------------------------------------------------

class TestMonitoringBase:
    def test_is_declarative_base(self):
        from sqlalchemy.orm import DeclarativeBase
        assert issubclass(MonitoringBase, DeclarativeBase)


# ---------------------------------------------------------------------------
# MonitoringRequestLog
# ---------------------------------------------------------------------------

class TestMonitoringRequestLog:
    def test_tablename(self):
        assert MonitoringRequestLog.__tablename__ == "request_logs"

    def test_schema_is_monitoring(self):
        for arg in MonitoringRequestLog.__table_args__:
            if isinstance(arg, dict):
                assert arg.get("schema") == "monitoring"
                break

    def test_has_id_column(self):
        assert hasattr(MonitoringRequestLog, "id")

    def test_has_service_name_column(self):
        assert hasattr(MonitoringRequestLog, "service_name")

    def test_has_endpoint_column(self):
        assert hasattr(MonitoringRequestLog, "endpoint")

    def test_has_method_column(self):
        assert hasattr(MonitoringRequestLog, "method")

    def test_has_status_code_column(self):
        assert hasattr(MonitoringRequestLog, "status_code")

    def test_has_response_time_ms_column(self):
        assert hasattr(MonitoringRequestLog, "response_time_ms")

    def test_tenant_id_is_nullable(self):
        col = MonitoringRequestLog.__table__.c["tenant_id"]
        assert col.nullable is True

    def test_has_timestamp_column(self):
        assert hasattr(MonitoringRequestLog, "timestamp")

    def test_has_date_column(self):
        assert hasattr(MonitoringRequestLog, "date")

    def test_has_correlation_id_column(self):
        assert hasattr(MonitoringRequestLog, "correlation_id")

    def test_instantiation(self):
        """Model can be instantiated with basic fields."""
        log = MonitoringRequestLog(
            service_name="test-svc",
            endpoint="/api/v1/test",
            method="GET",
            status_code=200,
            response_time_ms=50,
            timestamp=datetime.now(UTC),
            date=date.today(),
            hour=12,
        )
        assert log.service_name == "test-svc"
        assert log.status_code == 200


# ---------------------------------------------------------------------------
# MonitoringMetricsHourly
# ---------------------------------------------------------------------------

class TestMonitoringMetricsHourly:
    def test_tablename(self):
        assert MonitoringMetricsHourly.__tablename__ == "metrics_hourly"

    def test_has_service_name(self):
        assert hasattr(MonitoringMetricsHourly, "service_name")

    def test_has_request_count(self):
        assert hasattr(MonitoringMetricsHourly, "request_count")

    def test_has_error_count(self):
        assert hasattr(MonitoringMetricsHourly, "error_count")

    def test_has_avg_response_time(self):
        assert hasattr(MonitoringMetricsHourly, "avg_response_time_ms")

    def test_has_unique_constraint(self):
        from sqlalchemy import UniqueConstraint
        constraints = [c for c in MonitoringMetricsHourly.__table__.constraints
                       if isinstance(c, UniqueConstraint)]
        assert len(constraints) >= 1

    def test_instantiation(self):
        m = MonitoringMetricsHourly(
            service_name="svc",
            date=date.today(),
            hour=10,
            request_count=100,
            error_count=5,
        )
        assert m.request_count == 100


# ---------------------------------------------------------------------------
# MonitoringMetricsDaily
# ---------------------------------------------------------------------------

class TestMonitoringMetricsDaily:
    def test_tablename(self):
        assert MonitoringMetricsDaily.__tablename__ == "metrics_daily"

    def test_has_service_name(self):
        assert hasattr(MonitoringMetricsDaily, "service_name")

    def test_has_date_column(self):
        assert hasattr(MonitoringMetricsDaily, "date")

    def test_has_request_count(self):
        assert hasattr(MonitoringMetricsDaily, "request_count")

    def test_instantiation(self):
        m = MonitoringMetricsDaily(
            service_name="svc",
            date=date.today(),
            request_count=500,
            error_count=10,
        )
        assert m.service_name == "svc"


# ---------------------------------------------------------------------------
# MonitoringTenantUsage
# ---------------------------------------------------------------------------

class TestMonitoringTenantUsage:
    def test_tablename(self):
        assert MonitoringTenantUsage.__tablename__ == "tenant_usage"

    def test_tenant_id_not_nullable(self):
        col = MonitoringTenantUsage.__table__.c["tenant_id"]
        assert col.nullable is False

    def test_has_total_requests(self):
        assert hasattr(MonitoringTenantUsage, "total_requests")

    def test_has_total_errors(self):
        assert hasattr(MonitoringTenantUsage, "total_errors")

    def test_has_created_at(self):
        assert hasattr(MonitoringTenantUsage, "created_at")

    def test_has_updated_at(self):
        assert hasattr(MonitoringTenantUsage, "updated_at")

    def test_instantiation(self):
        tid = uuid.uuid4()
        m = MonitoringTenantUsage(
            service_name="svc",
            tenant_id=tid,
            date=date.today(),
            total_requests=1000,
            total_errors=20,
        )
        assert m.tenant_id == tid
