"""Client-side connection-pool and timeout policy, shared by the engine factory and the settings base.

Lives in ``contracts`` rather than ``db`` because ``tr_shared.config`` mirrors these
defaults and must stay importable without the ``[db]`` extra — importing anything under
``tr_shared.db`` loads SQLAlchemy.

A long-lived container keeps a few warm connections instead of paying TCP + TLS + SCRAM
plus asyncpg's type introspection on every request (~6 round trips before the first
statement).

pool_size is what a process holds at rest and is what the Supavisor client cap (200 on
the smallest compute) has to absorb fleet-wide: every uvicorn worker and every Celery
prefork child owns a pool, ~52 engines × 2 ≈ 104. max_overflow is burst room; overflow
connections are closed on return, so they cost a client slot only while a burst lasts.
8 gives one API process 10 concurrent checkouts — two workers absorb the board's 20
parallel page fetches without queueing; the 11th waits up to pool_timeout. A prefork
child runs one task at a time and never approaches the ceiling.

Every wait here is shorter than the caller waiting on it. A checkout waits at most
DEFAULT_POOL_TIMEOUT_SECONDS and a new connection gets DB_CONNECT_TIMEOUT_SECONDS, DNS
included; shared-auth-lib asserts that their sum stays under its auth-context budget.
DB_STATEMENT_TIMEOUT_SECONDS caps one statement, per process profile: request
processes get the short cap, background processes (workers, beat, consumers) the long
one. It bounds a statement, not a request; the gateway's route budget bounds requests.

Recycle at 300 s bounds a connection's age: measured alive after 310 s idle on the
pooler, and under the ~350 s idle timeout of cloud NATs. Idle death sooner than that —
the pooler, a NAT, a laptop network drop — is caught by validating a connection that
sat unused for DB_IDLE_PING_AFTER_SECONDS, so a busy pool never pays the pgbouncer-mode
ping (BEGIN + fetchrow(";") + ROLLBACK).
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

DEFAULT_POOL_SIZE = 2
DEFAULT_MAX_OVERFLOW = 8
DEFAULT_POOL_TIMEOUT_SECONDS = 2
DB_CONNECT_TIMEOUT_SECONDS = 3
DB_IDLE_PING_AFTER_SECONDS = 30


class StatementTimeoutProfile(StrEnum):
    REQUEST = "request"
    BACKGROUND = "background"


DB_STATEMENT_TIMEOUT_SECONDS: Mapping[StatementTimeoutProfile, int] = MappingProxyType(
    {
        StatementTimeoutProfile.REQUEST: 20,
        StatementTimeoutProfile.BACKGROUND: 60,
    }
)

DEFAULT_POOL_KWARGS: dict = {
    "pool_size": DEFAULT_POOL_SIZE,
    "max_overflow": DEFAULT_MAX_OVERFLOW,
    "pool_timeout": DEFAULT_POOL_TIMEOUT_SECONDS,
    "pool_recycle": 300,
}
