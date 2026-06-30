from tr_shared.schemas.error_envelope import build_error_envelope


def test_message_only():
    assert build_error_envelope("boom") == {"error": {"message": "boom"}}


def test_message_code_correlation():
    out = build_error_envelope("boom", code="X_1", correlation_id="cid-9")
    assert out == {"error": {"message": "boom", "code": "X_1", "correlation_id": "cid-9"}}


def test_none_fields_omitted():
    assert build_error_envelope("boom", code=None, correlation_id=None) == {"error": {"message": "boom"}}


def test_extra_fields_nested_inside_error_object():
    out = build_error_envelope("slow down", code="RL_1", retry_after=30, limit=100)
    assert out == {"error": {"message": "slow down", "code": "RL_1", "retry_after": 30, "limit": 100}}


def test_extra_none_values_omitted():
    assert build_error_envelope("boom", detail=None) == {"error": {"message": "boom"}}


def test_error_value_is_always_object():
    assert isinstance(build_error_envelope("boom")["error"], dict)


def test_exported_from_schemas_package():
    from tr_shared.schemas import build_error_envelope as exported
    assert exported("hi") == {"error": {"message": "hi"}}
