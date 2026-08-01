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
    present. Returns E.164 for a valid, plausibly-WhatsApp-reachable number; None otherwise.
    Never raises — every failure mode (unparseable, invalid, landline) returns None."""
    if not value:
        return None
    try:
        parsed = phonenumbers.parse(value, default_region)
    except NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    if phonenumbers.number_type(parsed) not in _CONTACTABLE_TYPES:
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
