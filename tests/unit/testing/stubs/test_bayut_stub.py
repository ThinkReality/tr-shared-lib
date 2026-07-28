from __future__ import annotations

import httpx
import pytest

from tr_shared.testing.stubs.bayut import BayutStub, sign_bayut_webhook
from tr_shared.webhooks.providers.bayut import BayutMD5Verifier


@pytest.mark.asyncio
async def test_listings_and_leads_routes() -> None:
    stub = BayutStub().listings([{"id": "L1"}]).leads([{"id": "LD1"}])

    async with httpx.AsyncClient(
        transport=stub.build(), base_url="https://example.test"
    ) as client:
        listings_resp = await client.get("/listings")
        leads_resp = await client.get("/leads")

    assert listings_resp.json()["data"] == [{"id": "L1"}]
    assert leads_resp.json()["data"] == [{"id": "LD1"}]


def test_signed_webhook_passes_the_real_verifier() -> None:
    payload = b'{"lead_id": "LD1"}'
    secret = "bayut-secret"

    headers = sign_bayut_webhook(payload, secret)

    assert BayutMD5Verifier().verify(payload, headers, secret) is True


def test_signed_webhook_rejects_wrong_secret() -> None:
    payload = b'{"lead_id": "LD1"}'
    headers = sign_bayut_webhook(payload, "right-secret")

    assert BayutMD5Verifier().verify(payload, headers, "wrong-secret") is False
