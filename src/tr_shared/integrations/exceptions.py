"""Exceptions raised by the integrations package."""


class IntegrationConfigError(Exception):
    """Base exception for integration config client failures.

    Raised on HTTP errors, circuit-open conditions, malformed responses,
    and Vault decrypt failures surfaced via the admin-panel endpoint.
    """


class IntegrationConfigNotFound(IntegrationConfigError):
    """Raised when a requested (tenant_id, platform_name) has no active row.

    This is a logical 404 — the integration either was never created,
    was soft-deleted, or is disabled. Callers that expect an integration
    to exist should surface this as a user-visible error ("This tenant
    has not connected PropertyFinder"). Callers that use the client for
    opportunistic warming (e.g., startup warm_all) should swallow it.
    """
