from tr_shared.contracts.db_pool import (
    DB_IDLE_PING_AFTER_SECONDS,
    DB_STATEMENT_TIMEOUT_SECONDS,
    DEFAULT_POOL_KWARGS,
    DEFAULT_POOL_TIMEOUT_SECONDS,
    StatementTimeoutProfile,
)


def test_pool_kwargs_use_the_named_pool_timeout():
    assert DEFAULT_POOL_KWARGS["pool_timeout"] == DEFAULT_POOL_TIMEOUT_SECONDS


def test_every_profile_has_a_statement_cap():
    assert set(DB_STATEMENT_TIMEOUT_SECONDS) == set(StatementTimeoutProfile)


def test_request_cap_is_shorter_than_background_cap():
    assert (
        DB_STATEMENT_TIMEOUT_SECONDS[StatementTimeoutProfile.REQUEST]
        < DB_STATEMENT_TIMEOUT_SECONDS[StatementTimeoutProfile.BACKGROUND]
    )


def test_idle_validation_starts_before_recycle():
    assert DB_IDLE_PING_AFTER_SECONDS < DEFAULT_POOL_KWARGS["pool_recycle"]
