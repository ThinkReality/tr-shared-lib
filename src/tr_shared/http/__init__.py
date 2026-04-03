"""Shared HTTP client with circuit breaker for service-to-service calls."""

from tr_shared.http.circuit_breaker import CircuitBreaker, CircuitState
from tr_shared.http.client import ServiceHTTPClient

__all__ = ["CircuitBreaker", "CircuitState", "ServiceHTTPClient"]
