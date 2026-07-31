from __future__ import annotations

import httpx
import pytest

from tr_shared.testing.stubs.propertyfinder import (
    PropertyFinderStub,
    sign_propertyfinder_webhook,
)
from tr_shared.webhooks.providers.propertyfinder import PropertyFinderVerifier


@pytest.mark.asyncio
async def test_token_and_listings_routes() -> None:
    stub = (
        PropertyFinderStub()
        .token(access_token="tok-1")
        .listings([{"id": "L1", "status": "active"}])
    )

    async with httpx.AsyncClient(transport=stub.build(), base_url="https://example.test") as client:
        token_resp = await client.post("/oauth/token", json={})
        listings_resp = await client.get("/listings")

    assert token_resp.json()["access_token"] == "tok-1"
    assert listings_resp.json()["data"] == [{"id": "L1", "status": "active"}]
    assert len(stub.requests) == 2


def test_signed_webhook_passes_the_real_verifier() -> None:
    payload = b'{"listing_id": "L1", "status": "sold"}'
    secret = "pf-secret"

    headers = sign_propertyfinder_webhook(payload, secret)

    assert PropertyFinderVerifier().verify(payload, headers, secret) is True


def test_signed_webhook_rejects_wrong_secret() -> None:
    payload = b'{"listing_id": "L1"}'
    headers = sign_propertyfinder_webhook(payload, "right-secret")

    assert PropertyFinderVerifier().verify(payload, headers, "wrong-secret") is False
