from tr_shared.exceptions import NotFoundError, ValidationError


def test_to_dict_is_nested_error_object():
    exc = ValidationError(detail="Price must be > 0", code="LISTING_VALIDATION_001")
    assert exc.to_dict() == {
        "error": {"message": "Validation failed", "code": "LISTING_VALIDATION_001", "detail": "Price must be > 0"}
    }


def test_to_dict_omits_absent_detail():
    body = NotFoundError(resource="Lead", code="LEAD_NOT_FOUND_001").to_dict()
    assert body["error"]["message"] == "Lead not found"
    assert body["error"]["code"] == "LEAD_NOT_FOUND_001"


def test_to_dict_error_is_object_not_string():
    assert isinstance(ValidationError(detail="bad").to_dict()["error"], dict)
