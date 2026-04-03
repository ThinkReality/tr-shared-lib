"""Tests for Prometheus metrics endpoint helpers."""
from unittest.mock import MagicMock, patch

import pytest

from tr_shared.monitoring.prometheus_endpoint import (
    create_metrics_router,
    start_prometheus_http_server,
)


class TestStartPrometheusHttpServer:
    def test_calls_start_http_server(self):
        with patch(
            "tr_shared.monitoring.prometheus_endpoint.start_http_server"
        ) as mock_start:
            mock_start.return_value = MagicMock()
            start_prometheus_http_server(port=9090)
            mock_start.assert_called_once()

    def test_passes_port_to_underlying_server(self):
        with patch(
            "tr_shared.monitoring.prometheus_endpoint.start_http_server"
        ) as mock_start:
            mock_start.return_value = MagicMock()
            start_prometheus_http_server(port=9091)
            kwargs = mock_start.call_args.kwargs
            assert kwargs.get("port") == 9091

    def test_returns_server_instance(self):
        fake_server = MagicMock()
        with patch(
            "tr_shared.monitoring.prometheus_endpoint.start_http_server",
            return_value=fake_server,
        ):
            result = start_prometheus_http_server(port=9090)
            assert result is fake_server

    def test_raises_on_failure(self):
        with patch(
            "tr_shared.monitoring.prometheus_endpoint.start_http_server",
            side_effect=OSError("port in use"),
        ):
            with pytest.raises(OSError):
                start_prometheus_http_server(port=9090)


class TestCreateMetricsRouter:
    def test_returns_api_router(self):
        from fastapi import APIRouter

        router = create_metrics_router()
        assert isinstance(router, APIRouter)

    def test_router_has_metrics_path(self):
        router = create_metrics_router()
        paths = [r.path for r in router.routes]
        assert "/metrics" in paths

    def test_metrics_endpoint_returns_200(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(create_metrics_router())
        client = TestClient(app)
        resp = client.get("/metrics")
        assert resp.status_code == 200
