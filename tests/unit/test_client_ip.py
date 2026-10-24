from starlette.requests import Request

from tr_shared.client_ip import GATEWAY_VERIFIED, RESOLVED_CLIENT_IP, client_ip


def _request(headers: dict[str, str], *, verified: bool = False) -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("203.0.113.9", 4321),
        "state": {GATEWAY_VERIFIED: True} if verified else {},
    }
    return Request(scope)


def test_a_gateway_verified_request_is_the_original_ip():
    request = _request(
        {
            "X-Original-IP": "198.51.100.7",
            "X-Real-IP": "100.64.0.2",
            "X-Forwarded-For": "100.64.0.3",
        },
        verified=True,
    )

    assert client_ip(request) == "198.51.100.7"


def test_an_unverified_original_ip_is_ignored():
    request = _request({"X-Original-IP": "198.51.100.7", "X-Real-IP": "100.64.0.2"})

    assert client_ip(request) == "100.64.0.2"


def test_forwarded_for_is_never_read():
    request = _request({"X-Forwarded-For": "198.51.100.7"})

    assert client_ip(request) == "203.0.113.9"


def test_an_ip_resolved_upstream_in_the_same_process_wins_over_every_header():
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-real-ip", b"100.64.0.2"), (b"x-original-ip", b"198.51.100.7")],
            "client": ("203.0.113.9", 4321),
            "state": {GATEWAY_VERIFIED: True, RESOLVED_CLIENT_IP: "192.0.2.44"},
        }
    )

    assert client_ip(request) == "192.0.2.44"


def test_no_peer_is_unknown():
    request = Request({"type": "http", "headers": [], "client": None, "state": {}})

    assert client_ip(request) == "unknown"
