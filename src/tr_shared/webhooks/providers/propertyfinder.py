"""PropertyFinder webhook verifier.

PropertyFinder sends listing-status webhooks with an ``X-Signature`` header
containing a raw hex HMAC-SHA256 digest of the request body.
"""

from tr_shared.webhooks.verifier import HMACVerifier


class PropertyFinderVerifier(HMACVerifier):
    """PropertyFinder-specific HMAC verifier.

    - Header: ``X-Signature``
    - Format: raw hex digest (no prefix)
    """

    def __init__(self) -> None:
        super().__init__(signature_header="x-signature", signature_format="hex")
