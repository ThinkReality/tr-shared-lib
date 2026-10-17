from pathlib import Path

import tr_shared
from tr_shared.testing.guards import detect_unpooled_redis_client, find_violations

SRC = Path(tr_shared.__file__).parent


def test_every_redis_client_is_built_by_the_pool_builder():
    bypasses = find_violations(
        SRC,
        detect_unpooled_redis_client,
        skip=("testing",),
        exclude=(SRC / "redis" / "pool.py",),
    )

    assert bypasses == {}
