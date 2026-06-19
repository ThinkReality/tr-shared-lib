"""Unit tests for tr_shared.web.dependencies.get_public_tenant_id."""

from uuid import UUID, uuid4

import pytest

from tr_shared.exceptions import ValidationError
from tr_shared.web import get_public_tenant_id


async def test_valid_uuid_returned():
    tid = uuid4()
    result = await get_public_tenant_id(x_tenant_id=str(tid))
    assert result == tid
    assert isinstance(result, UUID)


async def test_malformed_uuid_raises_validation_error():
    with pytest.raises(ValidationError):
        await get_public_tenant_id(x_tenant_id="not-a-uuid")
