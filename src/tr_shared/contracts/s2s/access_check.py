"""Shared S2S access-check contract — used by the listing AND lead providers
and the activity-service caller. One model so allowed/reason can't drift."""

from uuid import UUID

from pydantic import BaseModel


class AccessCheckRequest(BaseModel):
    """Body for POST .../{entity_id}/access-check. Tenant rides the X-Tenant-Id header."""

    user_id: UUID


class AccessCheckResponse(BaseModel):
    allowed: bool
    reason: str
