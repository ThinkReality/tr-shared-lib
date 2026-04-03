"""Tests for MetricsMiddleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from tr_shared.monitoring.instruments import InstrumentSet
from tr_shared.monitoring.middleware import DEFAULT_EXCLUDED_PATHS, MetricsMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_instruments() -> InstrumentSet:
    return InstrumentSet(
        request_counter=MagicMock(),
        request_duration=MagicMock(),
        error_counter=MagicMock(),
        active_requests=MagicMock(),
    )


def _build_app(instruments=None, excluded_paths=None, business_domain_classifier=None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        MetricsMiddleware,
        service_name="test-svc",
        instrument_set=instruments,
        excluded_paths=excluded_paths,
        business_domain_classifier=business_domain_classifier,
    )

    @app.get("/api/test")
    def endpoint():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/error")
    def error_endpoint():
        from fastapi import Response
        return Response(status_code=400)

    return app


# ---------------------------------------------------------------------------
# DEFAULT_EXCLUDED_PATHS
# ---------------------------------------------------------------------------

class TestDefaultExcludedPaths:
    def test_health_excluded(self):
        assert "/health" in DEFAULT_EXCLUDED_PATHS

    def test_docs_excluded(self):
        assert "/docs" in DEFAULT_EXCLUDED_PATHS

    def test_metrics_excluded(self):
        assert "/metrics" in DEFAULT_EXCLUDED_PATHS


# ---------------------------------------------------------------------------
# Passthrough when no instruments
# ---------------------------------------------------------------------------

class TestNoInstruments:
    def test_request_succeeds_without_instruments(self):
        app = _build_app(instruments=None)
        client = TestClient(app)
        response = client.get("/api/test")
        assert response.status_code == 200

    def test_no_metrics_recorded_without_instruments(self):
        """When instrument_set is None, all calls pass through unchanged."""
        app = _build_app(instruments=None)
        client = TestClient(app)
        client.get("/api/test")  # Should not raise


# ---------------------------------------------------------------------------
# Excluded paths
# ---------------------------------------------------------------------------

class TestExcludedPaths:
    def test_health_path_skips_metrics(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/health")
        instruments.request_counter.add.assert_not_called()

    def test_non_excluded_path_records_metrics(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/test")
        instruments.request_counter.add.assert_called_once()

    def test_custom_excluded_path_skips_metrics(self):
        instruments = _mock_instruments()
        app = _build_app(
            instruments=instruments,
            excluded_paths=frozenset({"/api/test"}),
        )
        client = TestClient(app)
        client.get("/api/test")
        instruments.request_counter.add.assert_not_called()


# ---------------------------------------------------------------------------
# Metric recording
# ---------------------------------------------------------------------------

class TestMetricRecording:
    def test_request_counter_incremented(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/test")
        instruments.request_counter.add.assert_called_once()

    def test_request_duration_recorded(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/test")
        instruments.request_duration.record.assert_called_once()

    def test_active_requests_incremented_then_decremented(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/test")
        calls = instruments.active_requests.add.call_args_list
        values = [c[0][0] for c in calls]
        assert 1 in values    # +1 at start
        assert -1 in values   # -1 at end (finally block)

    def test_error_counter_incremented_on_4xx(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/error")
        instruments.error_counter.add.assert_called()

    def test_error_counter_not_called_on_2xx(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/test")
        instruments.error_counter.add.assert_not_called()

    def test_labels_include_service_name(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/test")
        call_args = instruments.request_counter.add.call_args
        labels = call_args[0][1]
        assert labels["service"] == "test-svc"

    def test_labels_include_http_method(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/test")
        call_args = instruments.request_counter.add.call_args
        labels = call_args[0][1]
        assert labels["http.method"] == "GET"

    def test_labels_include_normalized_route(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/test")
        call_args = instruments.request_counter.add.call_args
        labels = call_args[0][1]
        assert "http.route" in labels

    def test_duration_is_positive(self):
        instruments = _mock_instruments()
        app = _build_app(instruments=instruments)
        client = TestClient(app)
        client.get("/api/test")
        call_args = instruments.request_duration.record.call_args
        duration = call_args[0][0]
        assert duration >= 0


# ---------------------------------------------------------------------------
# Business domain classifier
# ---------------------------------------------------------------------------

class TestBusinessDomainClassifier:
    def test_classifier_called_with_path(self):
        instruments = _mock_instruments()
        classifier = MagicMock(return_value="listings")
        app = _build_app(instruments=instruments, business_domain_classifier=classifier)
        client = TestClient(app)
        client.get("/api/test")
        classifier.assert_called_once()

    def test_classifier_none_result_skips_extra_metrics(self):
        instruments = _mock_instruments()
        classifier = MagicMock(return_value=None)
        app = _build_app(instruments=instruments, business_domain_classifier=classifier)
        client = TestClient(app)
        client.get("/api/test")
        # request_counter called once (base) not twice (no domain)
        assert instruments.request_counter.add.call_count == 1
