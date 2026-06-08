"""Strict base for all typed event payloads.

`extra="forbid"` means an unknown key (a producer-side rename or drift) fails
validation at the consumer edge instead of silently passing an empty value.
"""

from pydantic import BaseModel, ConfigDict


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
