from tr_shared.contracts.headers import HttpHeader


def test_calling_headers_present_and_canonical():
    assert HttpHeader.CALLING_SERVICE.value == "X-Calling-Service"
    assert HttpHeader.CALLING_TENANT_ID.value == "X-Calling-Tenant-ID"
    # distinct wire name from SERVICE_NAME
    assert HttpHeader.CALLING_SERVICE.value != HttpHeader.SERVICE_NAME.value
