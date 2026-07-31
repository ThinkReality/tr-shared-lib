"""PropertyFinder test fake — one `httpx.MockTransport`-backed stub for the
OAuth token endpoint + listing/lead endpoints the fleet's three PF clients call,
plus a correctly-signed fake webhook builder reusing the real production verifier
(never hand-build an unsigned payload a real webhook would never look like).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tr_shared.integrations.constants import PF_API_BASE_URL
from tr_shared.testing.stubs.http_stub import MockTransportBuilder
from tr_shared.webhooks.providers.propertyfinder import PropertyFinderVerifier

if TYPE_CHECKING:
    import httpx

__all__ = ["PF_API_BASE_URL", "PropertyFinderStub", "sign_propertyfinder_webhook"]


class PropertyFinderStub:
    """
    stub = PropertyFinderStub()
    stub.token(access_token="fake-token")
    stub.listings([{"id": "L1", "status": "active"}])
    client = httpx.AsyncClient(transport=stub.build(), base_url=PF_API_BASE_URL)
    """

    def __init__(self) -> None:
        self._builder = MockTransportBuilder()

    def token(
        self, *, access_token: str = "test-pf-access-token", expires_in: int = 3600
    ) -> "PropertyFinderStub":
        self._builder.route(
            "POST",
            r"/oauth/token$",
            json={
                "access_token": access_token,
                "expires_in": expires_in,
                "token_type": "Bearer",
            },
        )
        return self

    def listings(self, items: list[dict[str, Any]]) -> "PropertyFinderStub":
        self._builder.route("GET", r"/listings$", json={"data": items, "total": len(items)})
        return self

    def leads(self, items: list[dict[str, Any]]) -> "PropertyFinderStub":
        self._builder.route("GET", r"/leads$", json={"data": items, "total": len(items)})
        return self

    def route(self, *args: Any, **kwargs: Any) -> "PropertyFinderStub":
        """Escape hatch for endpoints this stub doesn't wrap yet — same
        MockTransportBuilder.route() signature, so a service isn't blocked
        waiting for this module to grow every endpoint it calls."""
        self._builder.route(*args, **kwargs)
        return self

    @property
    def requests(self) -> list[Any]:
        return self._builder.requests

    def build(self) -> "httpx.MockTransport":
        return self._builder.build()


def sign_propertyfinder_webhook(payload: bytes, secret: str) -> dict[str, str]:
    """Headers for a fake PF webhook delivery that a real
    PropertyFinderVerifier.verify() call accepts — computed with the same
    verifier production code uses, never hand-rolled."""
    import hashlib
    import hmac as _hmac

    verifier = PropertyFinderVerifier()
    signature = _hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return {verifier.signature_header: signature}
