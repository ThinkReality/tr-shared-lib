from starlette.requests import HTTPConnection

from tr_shared.contracts.headers import HttpHeader

GATEWAY_VERIFIED = "gateway_verified"
RESOLVED_CLIENT_IP = "resolved_client_ip"


def client_ip(connection: HTTPConnection) -> str:
    resolved: str | None = getattr(connection.state, RESOLVED_CLIENT_IP, None)
    if resolved:
        return resolved
    if getattr(connection.state, GATEWAY_VERIFIED, False):
        original = connection.headers.get(HttpHeader.ORIGINAL_IP.value)
        if original:
            return original.strip()
    edge_set = connection.headers.get(HttpHeader.REAL_IP.value)
    if edge_set:
        return edge_set.strip()
    return connection.client.host if connection.client else "unknown"
