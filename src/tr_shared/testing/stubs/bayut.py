"""Bayut/Dubizzle test fake — same `httpx.MockTransport`-backed shape as
`propertyfinder.py`, plus a correctly-signed fake webhook builder reusing the
real production MD5 verifier (Bayut signs push webhooks with
md5(secret + raw_body), not HMAC — see BayutMD5Verifier's own docstring).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tr_shared.testing.stubs.http_stub import MockTransportBuilder
from tr_shared.webhooks.providers.bayut import BayutMD5Verifier

if TYPE_CHECKING:
    import httpx

__all__ = ["BayutStub", "sign_bayut_webhook"]


class BayutStub:
    """
    stub = BayutStub()
    stub.listings([{"id": "L1", "status": "active"}])
    client = httpx.AsyncClient(transport=stub.build(), base_url="https://bayut.example")
    """

    def __init__(self) -> None:
        self._builder = MockTransportBuilder()

    def listings(self, items: list[dict[str, Any]]) -> "BayutStub":
        self._builder.route("GET", r"/listings$", json={"data": items, "total": len(items)})
        return self

    def leads(self, items: list[dict[str, Any]]) -> "BayutStub":
        self._builder.route("GET", r"/leads$", json={"data": items, "total": len(items)})
        return self

    def route(self, *args: Any, **kwargs: Any) -> "BayutStub":
        """Escape hatch for endpoints this stub doesn't wrap yet — same
        MockTransportBuilder.route() signature."""
        self._builder.route(*args, **kwargs)
        return self

    @property
    def requests(self) -> list[Any]:
        return self._builder.requests

    def build(self) -> "httpx.MockTransport":
        return self._builder.build()


def sign_bayut_webhook(payload: bytes, secret: str) -> dict[str, str]:
    """Headers for a fake Bayut/Dubizzle webhook delivery that a real
    BayutMD5Verifier.verify() call accepts."""
    import hashlib

    signature = hashlib.md5(secret.encode("utf-8") + payload).hexdigest()
    return {BayutMD5Verifier.signature_header: signature}
