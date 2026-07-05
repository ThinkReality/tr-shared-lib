"""Typed payload for wam.* events (tr-whatsApp-marketing-agent).

The canonical builder is app/schemas/events.py. The lead-management consumer
reads only user_number/lead_score/tier; the remaining fields are advisory
qualification context. ``qualification_result`` carries a whitelisted key set.
"""

from typing import Literal

from pydantic import Field, field_validator

from tr_shared.events.payloads._base import EventPayload


class WAMQualificationResultV1(EventPayload):
    """Whitelisted qualification signals (all optional)."""

    buyer_type: str | None = None
    individual_or_corp: str | None = None
    funds_location: str | None = None
    bank_account_status: str | None = None
    financing_method: str | None = None
    pre_approval_status: str | None = None
    financial_readiness: str | None = None
    purpose: str | None = None
    comparing_markets: str | None = None
    timeline: str | None = None
    legal_readiness: str | None = None
    property_type_pref: str | None = None
    budget: str | None = None
    location: str | None = None
    qualification_status: str | None = None
    next_step: str | None = None


class WAMLeadQualifiedV1(EventPayload):
    """wam.lead.qualified — a WhatsApp-qualified lead handed to the CRM."""

    user_number: str
    lead_score: int = Field(ge=0)
    tier: Literal["hot", "warm", "cold", "low_priority"]
    buyer_type: str | None = None
    budget: str | None = None
    location: str | None = None
    booking_uid: str | None = None
    persona: str | None = None
    crm_agent_id: str | None = None
    qualification_result: WAMQualificationResultV1 | None = None

    @field_validator("user_number")
    @classmethod
    def _digits_only(cls, v: str) -> str:
        if not v or not v.isdigit():
            raise ValueError("user_number must be digits-only (no +, spaces, or symbols)")
        return v
