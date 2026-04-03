"""Webhook signature verification.

Provides a ``Protocol``-based interface and a generic HMAC-SHA256 verifier
that covers PropertyFinder, Bayut, and Dubizzle signature formats.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class WebhookVerifier(Protocol):
    """Protocol for webhook signature verification."""

    def verify(self, raw_body: bytes, headers: dict[str, str], secret: str) -> bool:
        """Verify the webhook signature.

        Args:
            raw_body: Raw request body bytes.
            headers: Request headers with **lowercased** keys.
            secret: The shared secret for HMAC computation.

        Returns:
            ``True`` if the signature is valid (or verification is skipped).
        """
        ...  # pragma: no cover


class HMACVerifier:
    """Generic HMAC-SHA256 webhook verifier.

    Supports two signature formats:
    - ``"hex"``: raw hex digest (PropertyFinder listing webhooks)
    - ``"sha256={hex}"``: prefixed format (Bayut, Meta)

    If *secret* is empty, verification is skipped and ``True`` is returned.

    Args:
        signature_header: HTTP header name containing the signature (lowercased).
        signature_format: Expected format of the signature value.
    """

    def __init__(
        self,
        signature_header: str = "x-signature",
        signature_format: str = "hex",
    ) -> None:
        self.signature_header = signature_header.lower()
        self.signature_format = signature_format

    def verify(self, raw_body: bytes, headers: dict[str, str], secret: str) -> bool:
        if not secret:
            logger.debug("Webhook secret not configured — skipping verification")
            return True

        signature = headers.get(self.signature_header)
        if not signature:
            logger.warning(
                "Missing signature header: %s",
                self.signature_header,
            )
            return False

        expected = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if self.signature_format == "sha256={hex}":
            expected = f"sha256={expected}"

        return hmac.compare_digest(expected, signature)
