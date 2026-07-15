"""Uses atomic ``SET NX EX`` for race-condition-safe duplicate detection.
Follows fail-open semantics: if Redis is unavailable, requests proceed normally.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from tr_shared.contracts.headers import HttpHeader
from tr_shared.redis.client import get_redis_client

logger = logging.getLogger(__name__)

_PROCESSING_SENTINEL = json.dumps({"s": "processing"})


class APIIdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        redis_url: str = "",
        service_name: str = "",
        ttl: int = 86400,
        max_response_size: int = 1_048_576,
    ) -> None:
        super().__init__(app)
        self._redis_url = redis_url
        self._service_name = service_name
        self._ttl = ttl
        self._max_response_size = max_response_size
        self._redis: Any | None = None

    async def _get_redis(self) -> Any | None:
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        try:
            self._redis = await get_redis_client(self._redis_url)
            return self._redis
        except Exception:
            logger.warning("Idempotency: failed to connect to Redis", exc_info=True)
            return None

    def _build_key(self, tenant_id: str, idempotency_key: str) -> str:
        parts = [
            p
            for p in (self._service_name, "idempotency", tenant_id, idempotency_key)
            if p
        ]
        return ":".join(parts)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method != "POST":
            return await call_next(request)

        idempotency_key = request.headers.get(HttpHeader.IDEMPOTENCY_KEY.value)
        if not idempotency_key:
            return await call_next(request)

        tenant_id = (
            getattr(getattr(request, "state", None), "tenant_id", None)
            or request.headers.get(HttpHeader.TENANT_ID.value, "global")
        )

        redis = await self._get_redis()
        if redis is None:
            return await call_next(request)

        cache_key = self._build_key(str(tenant_id), idempotency_key)

        try:
            was_set = await redis.set(
                cache_key, _PROCESSING_SENTINEL, nx=True, ex=self._ttl
            )
        except Exception:
            logger.warning(
                "Idempotency SET NX failed — processing normally", exc_info=True
            )
            return await call_next(request)

        # SET NX returns True if newly set, None if key already existed
        if was_set is None:
            return await self._handle_duplicate(redis, cache_key)

        return await self._process_and_cache(request, call_next, redis, cache_key)

    async def _handle_duplicate(self, redis: Any, cache_key: str) -> Response:
        try:
            cached = await redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                if data.get("s") == "completed":
                    return Response(
                        content=data["b"],
                        status_code=data["sc"],
                        media_type=data.get("ct", "application/json"),
                        headers={HttpHeader.IDEMPOTENCY_REPLAYED.value: "true"},
                    )
            # Key exists but status is "processing" — concurrent duplicate
            return Response(
                content=json.dumps(
                    {
                        "error": {
                            "code": "IDEMPOTENCY_CONFLICT",
                            "message": "A request with this idempotency key is currently being processed",
                        }
                    }
                ),
                status_code=409,
                media_type="application/json",
            )
        except Exception:
            logger.warning(
                "Idempotency GET failed — returning conflict", exc_info=True
            )
            return Response(
                content=json.dumps(
                    {
                        "error": {
                            "code": "IDEMPOTENCY_CONFLICT",
                            "message": "Unable to verify idempotency status",
                        }
                    }
                ),
                status_code=409,
                media_type="application/json",
            )

    async def _process_and_cache(
        self,
        request: Request,
        call_next: Callable,
        redis: Any,
        cache_key: str,
    ) -> Response:
        response = await call_next(request)

        body_bytes = b""
        async for chunk in response.body_iterator:
            body_bytes += chunk

        status_code = response.status_code
        content_type = response.headers.get("content-type", "application/json")

        # Cache 2xx and 4xx; skip 5xx (allow retry)
        if status_code < 500 and len(body_bytes) <= self._max_response_size:
            try:
                cache_value = json.dumps(
                    {
                        "s": "completed",
                        "sc": status_code,
                        "b": body_bytes.decode("utf-8", errors="replace"),
                        "ct": content_type,
                    }
                )
                await redis.set(cache_key, cache_value, ex=self._ttl)
            except Exception:
                logger.warning(
                    "Idempotency: failed to cache response", exc_info=True
                )
        elif status_code >= 500:
            try:
                await redis.delete(cache_key)
            except Exception:
                pass

        response_headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in ("content-length", "content-type")
        }
        return Response(
            content=body_bytes,
            status_code=status_code,
            media_type=content_type,
            headers=response_headers,
        )
