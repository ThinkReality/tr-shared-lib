"""PropertyFinder OAuth2 client-credentials helper.

Extracted from tr-listing-service/app/clients/propertyfinder/token_manager.py
so admin-panel and listing-service share one implementation. Higher-level
concerns (token caching, refresh scheduling) stay in the calling code —
this helper is only the raw HTTP exchange.

PF's contract (non-obvious):
  - Credentials go in an HTTP Basic header, NOT in the request body.
  - Body is JSON with scope=openid + grant_type=client_credentials,
    NOT application/x-www-form-urlencoded.
"""

import base64

import httpx

from tr_shared.integrations.constants import PF_AUTH_URL
from tr_shared.integrations.exceptions import IntegrationConfigError


async def fetch_pf_access_token(
    api_key: str,
    api_secret: str,
    *,
    http_client: httpx.AsyncClient,
    auth_url: str = PF_AUTH_URL,
) -> tuple[str, int]:
    """Exchange PropertyFinder API credentials for an OAuth access token.

    Args:
        api_key: PF API key (client_id equivalent).
        api_secret: PF API secret (client_secret equivalent).
        http_client: Caller-owned httpx.AsyncClient. The caller is responsible
            for timeouts, connection pooling, and lifecycle.
        auth_url: OAuth2 token endpoint; defaults to PF_AUTH_URL.

    Returns:
        (access_token, expires_in_seconds) — the caller is responsible for
        refreshing the token before `expires_in` elapses.

    Raises:
        IntegrationConfigError: on non-2xx response, network failure, or
            malformed response body.
    """
    encoded = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
    }
    payload = {"scope": "openid", "grant_type": "client_credentials"}

    try:
        response = await http_client.post(auth_url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise IntegrationConfigError(
            f"PF OAuth exchange failed: {exc.__class__.__name__}: {exc}"
        ) from exc

    if response.status_code != 200:
        # Do NOT include response body in the error message — it may contain
        # the credentials echoed back. Status code + reason is enough.
        raise IntegrationConfigError(
            f"PF OAuth exchange returned HTTP {response.status_code}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise IntegrationConfigError("PF OAuth response was not valid JSON") from exc

    token = data.get("access_token")
    expires_in = data.get("expires_in")
    if not isinstance(token, str) or not token:
        raise IntegrationConfigError("PF OAuth response missing access_token")
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise IntegrationConfigError("PF OAuth response missing/invalid expires_in")

    return token, expires_in
