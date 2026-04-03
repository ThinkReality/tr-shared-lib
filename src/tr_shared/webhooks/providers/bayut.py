"""Bayut / Dubizzle webhook verifier.

Bayut and Dubizzle send lead webhooks with an ``X-Signature`` header
containing an HMAC-SHA256 digest prefixed with ``sha256=``.
"""

from tr_shared.webhooks.verifier import HMACVerifier


class BayutVerifier(HMACVerifier):
    """Bayut/Dubizzle-specific HMAC verifier.

    - Header: ``X-Signature``
    - Format: ``sha256={hex_digest}``
    """

    def __init__(self) -> None:
        super().__init__(signature_header="x-signature", signature_format="sha256={hex}")
