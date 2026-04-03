"""Meta (Facebook) webhook verifier with handshake support.

Meta signs webhook payloads with ``X-Hub-Signature-256`` using HMAC-SHA256
and the App Secret. Meta also requires a verification handshake via GET
with ``hub.mode``, ``hub.verify_token``, and ``hub.challenge`` query params.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


class MetaWebhookVerifier:
    """Meta (Facebook) webhook verifier.

    - Signature header: ``X-Hub-Signature-256``
    - Format: ``sha256={hex_digest}``
    - Handshake: GET with ``hub.mode=subscribe`` + ``hub.verify_token`` + ``hub.challenge``

    Args:
        verify_token: The token configured in the Meta App Dashboard for
            the verification handshake.
    """

    def __init__(self, verify_token: str = "") -> None:
        self.verify_token = verify_token

    def verify(self, raw_body: bytes, headers: dict[str, str], secret: str) -> bool:
        """Verify Meta webhook signature.

        Args:
            raw_body: Raw request body bytes.
            headers: Request headers with lowercased keys.
            secret: Meta App Secret.

        Returns:
            ``True`` if signature is valid.
        """
        if not secret:
            logger.debug("Meta App Secret not configured — skipping verification")
            return True

        signature = headers.get("x-hub-signature-256")
        if not signature:
            logger.warning("Missing X-Hub-Signature-256 header")
            return False

        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    def handle_handshake(self, query_params: dict[str, str]) -> int | None:
        """Handle Meta's verification handshake (GET request).

        Args:
            query_params: Query parameters from the GET request.

        Returns:
            The ``hub.challenge`` value as int if the handshake is valid,
            ``None`` otherwise.
        """
        mode = query_params.get("hub.mode")
        if mode != "subscribe":
            return None

        token = query_params.get("hub.verify_token")
        if not self.verify_token or token != self.verify_token:
            return None

        challenge = query_params.get("hub.challenge")
        if not challenge:
            return None

        try:
            return int(challenge)
        except (ValueError, TypeError):
            logger.warning("Invalid hub.challenge value: %s", challenge)
            return None
