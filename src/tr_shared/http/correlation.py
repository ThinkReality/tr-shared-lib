from tr_shared.contracts.headers import HttpHeader
from tr_shared.logging import get_correlation_id


def correlation_headers() -> dict[str, str]:
    correlation_id = get_correlation_id()
    return {HttpHeader.CORRELATION_ID.value: correlation_id} if correlation_id else {}
