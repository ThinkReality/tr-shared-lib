"""Bayut / Dubizzle webhook verifier.

Bayut and Dubizzle sign push webhooks with the ``X-Bayut-Signature`` header,
which is a plain MD5 hash of ``secret_key`` concatenated with the raw request
body — NOT HMAC. Returned as lowercase hex.

Reference: ``tr-listing-service/Bayut_Dubizzle_Profolio_API/leads_openapi.json``
(Push tag description, line 21).
"""

from __future__ import annotations

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


class BayutMD5Verifier:
    """Bayut/Dubizzle webhook verifier — md5(secret_key + raw_body) lowercase hex.

    - Header: ``X-Bayut-Signature`` (lowercased to ``x-bayut-signature``
      because the framework lowercases header keys before verification).
    - Algorithm: ``hashlib.md5(secret.encode() + raw_body).hexdigest()``.
    - Comparison: ``hmac.compare_digest`` (timing-safe).

    If *secret* is empty the verifier returns ``True`` to match the
    skip-when-unconfigured behaviour of :class:`HMACVerifier`.
    """

    signature_header: str = "x-bayut-signature"

    def verify(self, raw_body: bytes, headers: dict[str, str], secret: str) -> bool:
        if not secret:
            logger.debug("Bayut webhook secret not configured — skipping verification")
            return True

        received = headers.get(self.signature_header)
        if not received:
            logger.warning("Missing signature header: %s", self.signature_header)
            return False

        expected = hashlib.md5(secret.encode("utf-8") + raw_body).hexdigest()
        return hmac.compare_digest(expected, received.lower())


DubizzleVerifier = BayutMD5Verifier
"""Alias — Dubizzle uses the identical signing scheme as Bayut."""
