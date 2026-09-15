"""Client-side connection-pool policy, shared by the engine factory and the settings base.

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

Recycle at 300 s bounds a connection's idle time from above (idle ≤ age): measured alive
after 310 s idle on the pooler, and under the ~350 s idle timeout of cloud NATs — that
is what stands in for pre-ping, which under asyncpg in pgbouncer mode is
BEGIN + fetchrow(";") + ROLLBACK on every checkout: four round trips, most of the gain.
"""

DEFAULT_POOL_SIZE = 2
DEFAULT_MAX_OVERFLOW = 8
DEFAULT_POOL_KWARGS: dict = {
    "pool_size": DEFAULT_POOL_SIZE,
    "max_overflow": DEFAULT_MAX_OVERFLOW,
    "pool_timeout": 10,
    "pool_recycle": 300,
}
