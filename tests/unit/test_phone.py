from tr_shared.phone import to_e164


def test_uae_mobile_with_plus_and_country_code():
    assert to_e164("+971501234567") == "+971501234567"


def test_uae_mobile_with_country_code_no_plus():
    assert to_e164("971501234567") == "+971501234567"


def test_uae_mobile_local_format_with_leading_zero():
    assert to_e164("0501234567") == "+971501234567"


def test_uae_mobile_retained_trunk_zero_after_country_code():
    # 13-digit shape from the parent spec's baseline table: "9710" + 9-digit local number.
    assert to_e164("9710501234567") == "+971501234567"


def test_garbage_digit_run_returns_none():
    # The exact defect being fixed: an ID or count with >=7 digits is not a phone number.
    assert to_e164("188104") is None
    assert to_e164("18810400") is None


def test_too_short_returns_none():
    assert to_e164("123") is None


def test_none_returns_none():
    assert to_e164(None) is None


def test_empty_string_returns_none():
    assert to_e164("") is None


def test_non_digit_garbage_returns_none():
    assert to_e164("N/A") is None


def test_landline_returns_none():
    # UAE landline (04 prefix, Dubai) — not WhatsApp-reachable, must not pass as a mobile.
    assert to_e164("+97142345678") is None
