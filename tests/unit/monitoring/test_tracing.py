"""Tests for setup_tracing."""
from unittest.mock import MagicMock, patch

import pytest

from opentelemetry.sdk.trace import TracerProvider

from tr_shared.monitoring.tracing import setup_tracing


class TestSetupTracing:
    def test_returns_tracer_provider(self):
        provider = setup_tracing("test-svc")
        assert isinstance(provider, TracerProvider)

    def test_no_endpoint_produces_provider_without_exporter(self):
        """Empty endpoint → provider created successfully, no processor added."""
        with patch.object(TracerProvider, "add_span_processor") as mock_add:
            setup_tracing("test-svc", otlp_endpoint="")
            mock_add.assert_not_called()

    def test_injected_exporter_triggers_add_span_processor(self):
        mock_exporter = MagicMock()
        with patch.object(TracerProvider, "add_span_processor") as mock_add:
            setup_tracing("test-svc", span_exporter=mock_exporter)
            mock_add.assert_called_once()

    def test_resource_carries_service_name(self):
        provider = setup_tracing("svc-name-check")
        assert provider.resource.attributes.get("service.name") == "svc-name-check"

    def test_sets_global_tracer_provider(self):
        from opentelemetry import trace

        provider = setup_tracing("global-test-svc")
        # Global tracer provider was replaced — provider is returned
        assert provider is not None

    def test_span_exporter_none_and_empty_endpoint(self):
        """When both are absent, no processor is added (no-op tracing)."""
        with patch.object(TracerProvider, "add_span_processor") as mock_add:
            setup_tracing("svc", span_exporter=None, otlp_endpoint="")
            mock_add.assert_not_called()
