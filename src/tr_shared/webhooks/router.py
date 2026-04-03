"""Webhook handler registration and event dispatch."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from tr_shared.webhooks.schemas import WebhookEvent

logger = logging.getLogger(__name__)

WebhookHandler = Callable[[WebhookEvent], Awaitable[None]]


class WebhookRouter:
    """Routes webhook events to registered handlers.

    Supports both event-type-specific handlers and catch-all default handlers
    per provider. Lookup order:

    1. Exact match: ``(provider, event_type)``
    2. Default handler for the provider
    3. Log warning and skip
    """

    def __init__(self) -> None:
        self._handlers: dict[str, dict[str, WebhookHandler]] = {}
        self._default_handlers: dict[str, WebhookHandler] = {}

    def register(
        self,
        provider: str,
        event_type: str,
        handler: WebhookHandler,
    ) -> None:
        """Register a handler for a specific provider and event type.

        Args:
            provider: Provider identifier (e.g. ``"propertyfinder"``).
            event_type: Event type string (e.g. ``"listing.published"``).
            handler: Async callable that receives a ``WebhookEvent``.
        """
        self._handlers.setdefault(provider, {})[event_type] = handler

    def register_default(self, provider: str, handler: WebhookHandler) -> None:
        """Register a catch-all handler for a provider.

        Called when no event-type-specific handler matches.

        Args:
            provider: Provider identifier.
            handler: Async callable that receives a ``WebhookEvent``.
        """
        self._default_handlers[provider] = handler

    async def dispatch(self, event: WebhookEvent) -> None:
        """Dispatch a webhook event to the appropriate handler.

        Args:
            event: The parsed webhook event.
        """
        # Try exact match first
        provider_handlers = self._handlers.get(event.provider, {})
        handler = provider_handlers.get(event.event_type)

        if handler is None:
            handler = self._default_handlers.get(event.provider)

        if handler is None:
            logger.warning(
                "No handler registered for webhook: provider=%s, event_type=%s",
                event.provider,
                event.event_type,
            )
            return

        await handler(event)
