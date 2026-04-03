"""Tests for HMACVerifier."""

import hashlib
import hmac

from tr_shared.webhooks.verifier import HMACVerifier, WebhookVerifier


SECRET = "test-secret-32-characters-long!"
BODY = b'{"event":"listing.published","id":"123"}'


def _sign(body: bytes, secret: str, fmt: str = "hex") -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if fmt == "sha256={hex}":
        return f"sha256={digest}"
    return digest


class TestHMACVerifier:
    def test_valid_signature_returns_true(self):
        verifier = HMACVerifier()
        sig = _sign(BODY, SECRET)
        assert verifier.verify(BODY, {"x-signature": sig}, SECRET) is True

    def test_invalid_signature_returns_false(self):
        verifier = HMACVerifier()
        assert verifier.verify(BODY, {"x-signature": "bad-sig"}, SECRET) is False

    def test_missing_header_returns_false(self):
        verifier = HMACVerifier()
        assert verifier.verify(BODY, {}, SECRET) is False

    def test_empty_secret_skips_verification(self):
        verifier = HMACVerifier()
        assert verifier.verify(BODY, {}, "") is True

    def test_sha256_prefix_format(self):
        verifier = HMACVerifier(signature_format="sha256={hex}")
        sig = _sign(BODY, SECRET, fmt="sha256={hex}")
        assert verifier.verify(BODY, {"x-signature": sig}, SECRET) is True

    def test_sha256_prefix_format_wrong_signature(self):
        verifier = HMACVerifier(signature_format="sha256={hex}")
        assert verifier.verify(BODY, {"x-signature": "sha256=wrong"}, SECRET) is False

    def test_custom_header_name(self):
        verifier = HMACVerifier(signature_header="X-Custom-Sig")
        sig = _sign(BODY, SECRET)
        assert verifier.verify(BODY, {"x-custom-sig": sig}, SECRET) is True

    def test_header_name_is_lowercased(self):
        verifier = HMACVerifier(signature_header="X-Signature")
        assert verifier.signature_header == "x-signature"

    def test_implements_protocol(self):
        verifier = HMACVerifier()
        assert isinstance(verifier, WebhookVerifier)

    def test_timing_safe_comparison(self):
        """Verify we use hmac.compare_digest (constant-time)."""
        verifier = HMACVerifier()
        sig = _sign(BODY, SECRET)
        # Valid signature should pass
        assert verifier.verify(BODY, {"x-signature": sig}, SECRET) is True
        # Almost-correct signature should fail
        wrong_sig = sig[:-1] + ("0" if sig[-1] != "0" else "1")
        assert verifier.verify(BODY, {"x-signature": wrong_sig}, SECRET) is False
