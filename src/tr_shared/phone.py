"""E.164 phone normalization — SSOT for parsing raw phone strings into a strict, dialable
format. Owned by whichever service ingests the raw data (never by a downstream consumer)."""

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberType

_CONTACTABLE_TYPES = frozenset(
    {
        PhoneNumberType.MOBILE,
        PhoneNumberType.FIXED_LINE_OR_MOBILE,
    }
)


def to_e164(value: str | None, default_region: str = "AE") -> str | None:
    """Parse `value` as a phone number, defaulting to `default_region` when no country code is
    present. Returns E.164 for any valid, parseable number — landline included. Never raises;
    unparseable or invalid input returns None. Says nothing about WhatsApp reachability — see
    `is_whatsapp_reachable`."""
    if not value:
        return None
    try:
        parsed = phonenumbers.parse(value, default_region)
    except NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def is_whatsapp_reachable(e164: str) -> bool:
    """Whether an E.164 number is plausibly reachable on WhatsApp — mobile or
    fixed-line-or-mobile only, never a pure landline. Takes the output of `to_e164`, not raw
    input."""
    parsed = phonenumbers.parse(e164, None)
    return phonenumbers.number_type(parsed) in _CONTACTABLE_TYPES
