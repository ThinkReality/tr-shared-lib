from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, Depends, FastAPI

from tr_shared.testing import assert_session_dependencies_are_function_scoped


async def get_session() -> AsyncIterator[str]:
    yield "session"


def _app(scope: str | None) -> FastAPI:
    app = FastAPI()
    router = APIRouter()

    @router.get("/items")
    async def items(session: str = Depends(get_session, scope=scope)) -> str:
        return session

    @router.get("/health")
    async def health() -> str:
        return "ok"

    app.include_router(router)
    return app


def test_function_scoped_session_passes() -> None:
    assert_session_dependencies_are_function_scoped(_app("function"), {get_session})


@pytest.mark.parametrize("scope", [None, "request"])
def test_any_other_scope_names_the_route(scope: str | None) -> None:
    with pytest.raises(AssertionError, match=r"\['GET'\] /items"):
        assert_session_dependencies_are_function_scoped(_app(scope), {get_session})


def test_a_scan_that_finds_no_session_dependency_fails() -> None:
    async def other() -> AsyncIterator[str]:
        yield "other"

    with pytest.raises(AssertionError, match="no route depends on a session"):
        assert_session_dependencies_are_function_scoped(_app("function"), {other})
