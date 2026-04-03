# tr-shared-lib

Shared Python toolkit for all 16 ThinkRealty microservices. Provides cross-cutting
infrastructure so each service doesn't reinvent caching, event handling, circuit
breaking, rate limiting, logging, and observability.

## Modules

| Module | What it does | Install extra |
|---|---|---|
| `cache` | JSON cache with key building, pattern invalidation, miss/hit/error distinction | `cache` |
| `db` | Multi-tenant SQLAlchemy base models and generic `BaseRepository[T]` | `db` |
| `http` | `ServiceHTTPClient` + `CircuitBreaker` (optional Redis-backed shared state) | `http` |
| `events` | Redis Streams producer/consumer with DLQ, retry, idempotency | `redis` |
| `middleware` | `CorrelationIDMiddleware`, `GlobalErrorHandlerMiddleware`, `LoggingMiddleware` | `middleware` |
| `rate_limiter` | Token bucket + sliding window; in-memory fallback when Redis is down | `rate-limiter` |
| `monitoring` | OpenTelemetry adapters (Prometheus, Loki, OTLP), Celery aggregation tasks | `monitoring` |
| `logging` | structlog setup (JSON in prod, colored in dev) | `logging` |
| `celery` | Celery app factory | `celery` |
| `config` | Pydantic Settings v2 base class | *(no extra)* |
| `redis` | Thin Redis client wrapper | `redis` |

---

## Installation

This library is installed directly from the private GitHub repo. Include only the
extras your service needs:

```bash
# Minimal — cache + events only
pip install "tr-shared-lib[cache,redis] @ git+https://github.com/ThinkRealty/tr-shared-lib.git"

# Full stack
pip install "tr-shared-lib[all] @ git+https://github.com/ThinkRealty/tr-shared-lib.git"
```

### Available extras

| Extra | Packages installed |
|---|---|
| `redis` | redis-py ≥5 |
| `cache` | redis-py ≥5 |
| `upstash` | upstash-redis (for Upstash serverless Redis) |
| `db` | SQLAlchemy 2.0 + asyncpg |
| `http` | httpx |
| `middleware` | fastapi, httpx |
| `celery` | Celery ≥5 |
| `logging` | json-logging |
| `monitoring` | OpenTelemetry full stack |
| `monitoring-prometheus` | Prometheus exporter only (lighter) |
| `monitoring-otlp` | OTLP exporter only (lighter) |
| `rate-limiter` | redis-py + fastapi |
| `all` | Everything above |

---

## Quick-start examples

### Cache (cache-aside pattern)

```python
from tr_shared.cache import CacheProviderFactory, CacheService

cache = await CacheProviderFactory.create_and_initialize(
    provider="standard", redis_url="redis://localhost:6379/0"
)
svc = CacheService(cache=cache, key_prefix="prod:listings")

# Simple get/set
await svc.set("listings:123", {"name": "Burj View"}, ttl=3600)
data = await svc.get("listings:123")

# Distinguish miss from Redis error
result = await svc.get_result("listings:123")
if result.error:
    # Redis is down — fall back to DB, don't cache
elif result.hit:
    return result.value
else:
    # Genuine miss — fetch from DB and cache

# Cache-aside with fetch function
data = await svc.get_or_set(
    svc.build_key("listings", "123"),
    fetch_func=fetch_from_db,
    ttl=3600,
)
```

### Events (Redis Streams)

```python
from tr_shared.events import EventProducer, EventConsumer, EventEnvelope

# Producer
producer = EventProducer(redis_url="redis://localhost:6379")
await producer.publish("user.created", payload={"name": "Alice"}, tenant_id="t-1")

# Consumer
consumer = EventConsumer(
    redis_url="redis://localhost:6379",
    stream_name="user_events",
    consumer_group="my_service",
)

@consumer.handler("user.created")
async def handle_user_created(envelope: EventEnvelope) -> None:
    print(envelope.data)

await consumer.start()
```

### Circuit Breaker

```python
from tr_shared.http.circuit_breaker import CircuitBreaker

breaker = CircuitBreaker(
    name="crm-backend",
    failure_threshold=5,
    recovery_timeout=30,
    # Optional: share state across instances/restarts
    redis_client=redis_client,
)

if await breaker.is_open():
    raise ServiceUnavailableError("crm-backend")

try:
    result = await call_crm_backend()
    await breaker.record_success()
except Exception:
    await breaker.record_failure()
    raise
```

### Rate Limiter (FastAPI dependency)

```python
from tr_shared.rate_limiter import RateLimiter, RateLimitMiddleware

# Add middleware (applies globally)
app.add_middleware(
    RateLimitMiddleware,
    redis_url="redis://localhost:6379",
    default_limit=100,      # requests
    default_window=60,      # seconds
)

# Or per-route dependency
from tr_shared.rate_limiter.dependency import rate_limit

@router.post("/listings")
async def create_listing(
    _: None = Depends(rate_limit(limit=10, window=60)),
):
    ...
```

---

## Architecture decisions

**Why `CacheInterface` and a factory?**
Each service can use standard Redis locally and Upstash in production without
changing any service code. The factory reads `CACHE_PROVIDER=standard|upstash`
from the environment.

**Why optional dependencies?**
A service that only needs caching should not have to install the full
OpenTelemetry stack. Extras let each service install exactly what it needs.

**Why `OrderedDict` in `InMemoryIdempotencyChecker`?**
A plain `set` has no insertion order, so evicting "the oldest 5000 entries"
would remove random entries. `OrderedDict` preserves insertion order so
`popitem(last=False)` always removes the truly oldest entry (FIFO).

**Why `BaseRedisAdapter`?**
`StandardRedisAdapter` and `UpstashAdapter` share 91% identical code. The base
class holds all shared logic; subclasses only override the 2–3 methods where the
provider APIs genuinely differ (`set()` atomicity, `xadd()` approximation flag).

---

## For contributors

```bash
# Install all deps including dev tools
uv sync --all-extras

# Run tests with coverage
uv run pytest tests/ -v --cov=src/tr_shared --cov-report=term-missing

# Lint + format
uv run ruff check --fix src/
uv run ruff format src/
```

**Requirements:**
- Python ≥ 3.11
- Test coverage must stay ≥ 80% (enforced by pytest config)
- Every new module needs tests under `tests/unit/<module>/`
