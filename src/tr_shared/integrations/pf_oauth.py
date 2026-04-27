"""PropertyFinder Atlas token-exchange helper.

PropertyFinder's Atlas API uses a non-standard token endpoint that does NOT
follow OAuth2 client-credentials. The actual contract:

  POST https://atlas.propertyfinder.com/v1/auth/token
  Content-Type: application/json
  Body: {"apiKey": "...", "apiSecret": "..."}
  Response: {"accessToken": "...", "expiresIn": <seconds>}

This helper is the single source of truth for token exchange across services.
Higher-level concerns (caching, refresh scheduling) stay in the calling code.
"""

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
    """Exchange PropertyFinder API credentials for an Atlas access token.

    Args:
        api_key: PF API key.
        api_secret: PF API secret.
        http_client: Caller-owned httpx.AsyncClient. The caller is responsible
            for timeouts, connection pooling, and lifecycle.
        auth_url: PF Atlas token endpoint; defaults to PF_AUTH_URL.

    Returns:
        (access_token, expires_in_seconds) — the caller is responsible for
        refreshing the token before `expires_in` elapses.

    Raises:
        IntegrationConfigError: on non-2xx response, network failure, or
            malformed response body.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"apiKey": api_key, "apiSecret": api_secret}

    try:
        response = await http_client.post(auth_url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise IntegrationConfigError(
            f"PF token exchange failed: {exc.__class__.__name__}: {exc}"
        ) from exc

    if response.status_code != 200:
        # Do NOT include response body in the error message — it may echo
        # the credentials back. Status code alone is enough for diagnosis.
        raise IntegrationConfigError(
            f"PF token exchange returned HTTP {response.status_code}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise IntegrationConfigError("PF token response was not valid JSON") from exc

    token = data.get("accessToken")
    expires_in = data.get("expiresIn")
    if not isinstance(token, str) or not token:
        raise IntegrationConfigError("PF token response missing accessToken")
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise IntegrationConfigError("PF token response missing/invalid expiresIn")

    return token, expires_in
