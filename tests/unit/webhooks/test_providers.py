"""Tests for provider-specific verifiers."""

import hashlib
import hmac

from tr_shared.webhooks.providers.bayut import BayutMD5Verifier, DubizzleVerifier
from tr_shared.webhooks.providers.meta import MetaWebhookVerifier
from tr_shared.webhooks.providers.propertyfinder import PropertyFinderVerifier
from tr_shared.webhooks.verifier import WebhookVerifier

SECRET = "test-secret-32-characters-long!"
BODY = b'{"lead_id":"abc123"}'


class TestPropertyFinderVerifier:
    def test_uses_x_signature_header(self):
        v = PropertyFinderVerifier()
        assert v.signature_header == "x-signature"

    def test_uses_hex_format(self):
        v = PropertyFinderVerifier()
        assert v.signature_format == "hex"

    def test_valid_signature(self):
        v = PropertyFinderVerifier()
        sig = hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        assert v.verify(BODY, {"x-signature": sig}, SECRET) is True

    def test_implements_protocol(self):
        assert isinstance(PropertyFinderVerifier(), WebhookVerifier)


class TestBayutMD5Verifier:
    def test_uses_x_bayut_signature_header(self):
        v = BayutMD5Verifier()
        assert v.signature_header == "x-bayut-signature"

    def test_valid_md5_concat_signature(self):
        v = BayutMD5Verifier()
        sig = hashlib.md5(SECRET.encode() + BODY).hexdigest()
        assert v.verify(BODY, {"x-bayut-signature": sig}, SECRET) is True

    def test_valid_signature_uppercase_normalised(self):
        v = BayutMD5Verifier()
        sig = hashlib.md5(SECRET.encode() + BODY).hexdigest().upper()
        assert v.verify(BODY, {"x-bayut-signature": sig}, SECRET) is True

    def test_hmac_sha256_signature_fails(self):
        v = BayutMD5Verifier()
        sig = hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        assert v.verify(BODY, {"x-bayut-signature": sig}, SECRET) is False

    def test_missing_header_fails(self):
        v = BayutMD5Verifier()
        assert v.verify(BODY, {}, SECRET) is False

    def test_empty_secret_skips_verification(self):
        v = BayutMD5Verifier()
        assert v.verify(BODY, {}, "") is True

    def test_implements_protocol(self):
        assert isinstance(BayutMD5Verifier(), WebhookVerifier)


class TestDubizzleVerifierAlias:
    def test_alias_is_bayut_verifier(self):
        assert DubizzleVerifier is BayutMD5Verifier

    def test_valid_signature(self):
        v = DubizzleVerifier()
        sig = hashlib.md5(SECRET.encode() + BODY).hexdigest()
        assert v.verify(BODY, {"x-bayut-signature": sig}, SECRET) is True


class TestMetaWebhookVerifier:
    def test_valid_signature(self):
        v = MetaWebhookVerifier()
        digest = hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        sig = f"sha256={digest}"
        assert v.verify(BODY, {"x-hub-signature-256": sig}, SECRET) is True

    def test_invalid_signature(self):
        v = MetaWebhookVerifier()
        assert v.verify(BODY, {"x-hub-signature-256": "sha256=bad"}, SECRET) is False

    def test_missing_header(self):
        v = MetaWebhookVerifier()
        assert v.verify(BODY, {}, SECRET) is False

    def test_empty_secret_skips_verification(self):
        v = MetaWebhookVerifier()
        assert v.verify(BODY, {}, "") is True

    def test_handshake_valid_token(self):
        v = MetaWebhookVerifier(verify_token="my-token")
        result = v.handle_handshake({
            "hub.mode": "subscribe",
            "hub.verify_token": "my-token",
            "hub.challenge": "12345",
        })
        assert result == 12345

    def test_handshake_wrong_token(self):
        v = MetaWebhookVerifier(verify_token="my-token")
        result = v.handle_handshake({
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "12345",
        })
        assert result is None

    def test_handshake_wrong_mode(self):
        v = MetaWebhookVerifier(verify_token="my-token")
        result = v.handle_handshake({
            "hub.mode": "unsubscribe",
            "hub.verify_token": "my-token",
            "hub.challenge": "12345",
        })
        assert result is None

    def test_handshake_missing_challenge(self):
        v = MetaWebhookVerifier(verify_token="my-token")
        result = v.handle_handshake({
            "hub.mode": "subscribe",
            "hub.verify_token": "my-token",
        })
        assert result is None

    def test_handshake_no_params(self):
        v = MetaWebhookVerifier(verify_token="my-token")
        result = v.handle_handshake({})
        assert result is None

    def test_handshake_invalid_challenge_value(self):
        v = MetaWebhookVerifier(verify_token="my-token")
        result = v.handle_handshake({
            "hub.mode": "subscribe",
            "hub.verify_token": "my-token",
            "hub.challenge": "not-a-number",
        })
        assert result is None

    def test_handshake_empty_verify_token(self):
        v = MetaWebhookVerifier(verify_token="")
        result = v.handle_handshake({
            "hub.mode": "subscribe",
            "hub.verify_token": "",
            "hub.challenge": "12345",
        })
        assert result is None
