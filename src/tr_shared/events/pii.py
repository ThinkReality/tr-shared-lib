"""PII hashing for event-bus payloads.

Raw phone/email must never go on the event bus (privacy). Producers hash PII
through this single helper so consumers receive a stable opaque token, not the
raw value. Lives in tr_shared so every service hashes identically — a token
produced by one service matches the same input hashed by another.
"""

import hashlib


def hash_pii(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest()[:16] if value else None
