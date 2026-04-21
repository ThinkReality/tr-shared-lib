"""Shared HTTP client with circuit breaker for service-to-service calls."""

from tr_shared.http.circuit_breaker import CircuitBreaker, CircuitState
from tr_shared.http.client import ServiceHTTPClient
from tr_shared.http.internal_client import InternalServiceClient

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "InternalServiceClient",
    "ServiceHTTPClient",
]
