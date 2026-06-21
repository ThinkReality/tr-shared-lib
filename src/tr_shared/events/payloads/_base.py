"""Strict base for all typed event payloads.

`extra="forbid"` means an unknown key (a producer-side rename or drift) fails
validation at the consumer edge instead of silently passing an empty value.

PII policy (SSOT): a payload field carrying personal data (email, phone, personal
name) is **hashed** (via ``tr_shared.events.pii.hash_pii``) when any consumer
correlates on it, or **omitted** when no consumer reads it. Never carry it raw.
"""

from pydantic import BaseModel, ConfigDict


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
