"""A broad catch is DB work when a call in its ``try`` reaches the database through code the project types."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from tr_shared.testing.guards import assert_no_swallowed_db_errors, find_swallowed_db_errors

STORE = """
    class UrlStore:
        def __init__(self, session):
            self._session = session

        def save(self, url):
            self._session.execute(url)
"""

PURE_STORE = """
    class UrlStore:
        def save(self, url):
            return url.strip()
"""


def _app(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "app"
    for name, source in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dedent(source).lstrip("\n"))
    return root


def _lines(root: Path) -> dict[str, list[int]]:
    return {
        path: [hit.line for hit in hits] for path, hits in find_swallowed_db_errors(root).items()
    }


def _handler(root: Path, name: str) -> int:
    lines = (root / name).read_text().splitlines()
    return next(n for n, line in enumerate(lines, 1) if "except Exception" in line)


def _caller(body: str, signature: str = "url_store") -> str:
    return f"""
        from app.store import UrlStore, url_store, make_store, store_class


        def handle({signature}, url):
            try:
                {body}
            except Exception:
                return None
    """


STORE_MODULE = (
    STORE
    + """

    url_store = UrlStore(None)


    def make_store() -> UrlStore:
        return UrlStore(None)


    def store_class() -> type[UrlStore]:
        return UrlStore
"""
)


class TestReceiverTypes:
    @pytest.mark.parametrize(
        ("signature", "body"),
        [
            ("store: UrlStore", "store.save(url)"),
            ("store: UrlStore | None", "store.save(url)"),
            ("store: Optional[UrlStore]", "store.save(url)"),
            ("store: 'UrlStore'", "store.save(url)"),
            ("unused", "UrlStore(None).save(url)"),
            ("unused", "make_store().save(url)"),
            ("unused", "url_store.save(url)"),
            ("unused", "store_class()(None).save(url)"),
        ],
    )
    def test_a_typed_receiver_is_followed_into_the_project(
        self, tmp_path: Path, signature: str, body: str
    ) -> None:
        root = _app(
            tmp_path,
            {
                "store.py": STORE_MODULE,
                "handler.py": "from typing import Optional\n" + dedent(_caller(body, signature)),
            },
        )
        assert _lines(root) == {"handler.py": [_handler(root, "handler.py")]}

    @pytest.mark.parametrize(
        ("signature", "body"),
        [
            ("store: UrlStore", "store.save(url)"),
            ("unused", "make_store().save(url)"),
        ],
    )
    def test_a_typed_receiver_whose_code_never_reaches_the_database_is_not_flagged(
        self, tmp_path: Path, signature: str, body: str
    ) -> None:
        pure_module = (
            PURE_STORE
            + """

    url_store = UrlStore()


    def make_store() -> UrlStore:
        return UrlStore()


    def store_class() -> type[UrlStore]:
        return UrlStore
"""
        )
        root = _app(tmp_path, {"store.py": pure_module, "handler.py": _caller(body, signature)})
        assert _lines(root) == {}

    def test_a_local_assigned_from_a_constructor_is_followed(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "store.py": STORE,
                "handler.py": """
                    from app.store import UrlStore


                    def handle(url):
                        store = UrlStore(None)
                        try:
                            store.save(url)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {"handler.py": [_handler(root, "handler.py")]}

    @pytest.mark.parametrize(
        "assignment",
        ["self._store = UrlStore(None)", "self._store = store or UrlStore(None)"],
    )
    def test_an_attribute_set_in_the_constructor_is_followed(
        self, tmp_path: Path, assignment: str
    ) -> None:
        root = _app(
            tmp_path,
            {
                "store.py": STORE,
                "runner.py": f"""
                    from app.store import UrlStore


                    class Runner:
                        def __init__(self, store=None):
                            {assignment}

                        def run(self, url):
                            try:
                                self._store.save(url)
                            except Exception:
                                return None
                """,
            },
        )
        assert _lines(root) == {"runner.py": [_handler(root, "runner.py")]}

    def test_an_attribute_annotated_on_the_class_is_followed(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "store.py": STORE,
                "runner.py": """
                    from app.store import UrlStore


                    class Runner:
                        store: UrlStore

                        def run(self, url):
                            try:
                                self.store.save(url)
                            except Exception:
                                return None
                """,
            },
        )
        assert _lines(root) == {"runner.py": [_handler(root, "runner.py")]}

    def test_an_attribute_of_a_typed_object_is_followed(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "store.py": STORE,
                "scraper.py": """
                    from app.store import UrlStore


                    class Scraper:
                        def __init__(self):
                            self.persistence = UrlStore(None)
                """,
                "handler.py": """
                    from app.scraper import Scraper


                    def handle(scraper: Scraper, url):
                        try:
                            scraper.persistence.save(url)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {"handler.py": [_handler(root, "handler.py")]}

    def test_an_untyped_receiver_is_not_followed_by_its_method_name(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "owners.py": """
                    class OwnerStore:
                        def __init__(self, session):
                            self._session = session

                        def search(self, term):
                            return self._session.execute(term)
                """,
                "parser.py": """
                    import re

                    PATTERN = re.compile("x")


                    def parse(text):
                        try:
                            return PATTERN.search(text)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {}


class TestImports:
    @pytest.mark.parametrize(
        "import_line",
        [
            "from .store import UrlStore",
            "from app.store import UrlStore",
            "from app.pkg import UrlStore",
            "import app.store as stores",
        ],
    )
    def test_every_import_form_resolves(self, tmp_path: Path, import_line: str) -> None:
        annotation = "stores.UrlStore" if "as stores" in import_line else "UrlStore"
        root = _app(
            tmp_path,
            {
                "store.py": STORE,
                "pkg/__init__.py": "from app.store import UrlStore\n",
                "handler.py": f"""
                    {import_line}


                    def handle(store: {annotation}, url):
                        try:
                            store.save(url)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {"handler.py": [_handler(root, "handler.py")]}

    def test_an_import_inside_the_function_resolves(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "store.py": STORE,
                "handler.py": """
                    def handle(url):
                        from app.store import UrlStore

                        store = UrlStore(None)
                        try:
                            store.save(url)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {"handler.py": [_handler(root, "handler.py")]}

    def test_a_module_function_is_followed(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "status.py": """
                    def update_status(session, url):
                        session.execute(url)
                """,
                "handler.py": """
                    from app import status


                    def handle(url):
                        try:
                            status.update_status(None, url)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {"handler.py": [_handler(root, "handler.py")]}


class TestDispatch:
    def test_a_protocol_method_dispatches_to_every_implementation(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "ports.py": """
                    from typing import Protocol


                    class UrlPort(Protocol):
                        def save(self, url) -> None: ...
                """,
                "adapters.py": STORE,
                "handler.py": """
                    from app.ports import UrlPort


                    def handle(port: UrlPort, url):
                        try:
                            port.save(url)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {"handler.py": [_handler(root, "handler.py")]}

    def test_a_protocol_method_skips_a_same_named_method_of_another_shape(
        self, tmp_path: Path
    ) -> None:
        root = _app(
            tmp_path,
            {
                "runner.py": """
                    from typing import Protocol


                    class AgentRunner(Protocol):
                        def run(self, name, inputs): ...


                    class GraphRunner:
                        def run(self, name, inputs):
                            return {"name": name, **inputs}


                    def get_agent_runner() -> AgentRunner:
                        return GraphRunner()
                """,
                "orchestrator.py": """
                    class Orchestrator:
                        def __init__(self, session):
                            self._session = session

                        def run(self, phone):
                            self._session.execute(phone)
                """,
                "graph.py": """
                    from app.runner import get_agent_runner


                    def invoke(inputs):
                        try:
                            return get_agent_runner().run("outreach", inputs)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {}

    def test_an_abstract_method_dispatches_to_its_overrides(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "base.py": """
                    from abc import ABC, abstractmethod


                    class Store(ABC):
                        @abstractmethod
                        def save(self, url):
                            raise NotImplementedError
                """,
                "sql.py": """
                    from app.base import Store


                    class SqlStore(Store):
                        def __init__(self, session):
                            self._session = session

                        def save(self, url):
                            self._session.execute(url)
                """,
                "handler.py": """
                    from app.base import Store


                    def handle(store: Store, url):
                        try:
                            store.save(url)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {"handler.py": [_handler(root, "handler.py")]}

    def test_a_stub_alone_reaches_nothing(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "ports.py": """
                    from typing import Protocol


                    class UrlPort(Protocol):
                        def save(self, url) -> None: ...


                    class MemoryPort:
                        def save(self, url) -> None:
                            self.urls = [url]
                """,
                "handler.py": """
                    from app.ports import UrlPort


                    def handle(port: UrlPort, url):
                        try:
                            port.save(url)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {}

    def test_a_self_call_reaches_a_sibling_mixin(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "create.py": """
                    class CreateMixin:
                        def create(self, user):
                            try:
                                self.delete(user)
                            except Exception:
                                return None
                """,
                "delete.py": """
                    class DeleteMixin:
                        def delete(self, user):
                            self.db.flush()
                """,
                "service.py": """
                    from app.create import CreateMixin
                    from app.delete import DeleteMixin


                    class UserService(CreateMixin, DeleteMixin):
                        pass
                """,
            },
        )
        assert _lines(root) == {"create.py": [_handler(root, "create.py")]}

    def test_a_self_call_is_not_matched_to_an_unrelated_class(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "create.py": """
                    class CreateMixin:
                        def create(self, user):
                            try:
                                self.delete(user)
                            except Exception:
                                return None
                """,
                "other.py": """
                    class Unrelated:
                        def delete(self, user):
                            self.db.flush()
                """,
            },
        )
        assert _lines(root) == {}


class TestReach:
    def test_reach_is_transitive_and_the_failure_names_the_chain(self, tmp_path: Path) -> None:
        root = _app(
            tmp_path,
            {
                "store.py": STORE,
                "runner.py": """
                    from app.store import UrlStore


                    def mark_failed(url):
                        UrlStore(None).save(url)


                    def finish(url):
                        mark_failed(url)


                    def run(url):
                        try:
                            finish(url)
                        except Exception:
                            return None
                """,
            },
        )
        with pytest.raises(AssertionError, match="swallow") as failure:
            assert_no_swallowed_db_errors(root)
        assert "finish -> mark_failed -> UrlStore.save" in str(failure.value)

    @pytest.mark.parametrize(("reaches", "expected"), [(True, 1), (False, 0)])
    def test_a_call_cycle_terminates(self, tmp_path: Path, reaches: bool, expected: int) -> None:
        leaf = "    session.execute(url)\n" if reaches else ""
        root = _app(
            tmp_path,
            {
                "loop.py": (
                    "def ping(session, url):\n"
                    "    pong(session, url)\n"
                    f"{leaf}"
                    "\n\n"
                    "def pong(session, url):\n"
                    "    ping(session, url)\n"
                    "\n\n"
                    "def run(url):\n"
                    "    try:\n"
                    "        pong(None, url)\n"
                    "    except Exception:\n"
                    "        return None\n"
                ),
            },
        )
        assert len(_lines(root).get("loop.py", [])) == expected

    def test_a_call_resolved_to_project_code_is_not_judged_by_its_name(
        self, tmp_path: Path
    ) -> None:
        root = _app(
            tmp_path,
            {
                "bulkhead.py": """
                    class Bulkhead:
                        @classmethod
                        def from_db_model(cls, row):
                            return cls()
                """,
                "manager.py": """
                    from app.bulkhead import Bulkhead


                    def build(row):
                        try:
                            return Bulkhead.from_db_model(row)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {}

    def test_a_resolved_call_with_a_db_looking_name_is_not_a_leaf_one_level_down(
        self, tmp_path: Path
    ) -> None:
        root = _app(
            tmp_path,
            {
                "bulkhead.py": """
                    class Bulkhead:
                        @classmethod
                        def from_db_model(cls, row):
                            return cls()


                    def build(row):
                        return Bulkhead.from_db_model(row)
                """,
                "manager.py": """
                    from app.bulkhead import build


                    def load(row):
                        try:
                            return build(row)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {}

    def test_a_repository_method_reaches_the_database_whatever_its_body_calls(
        self, tmp_path: Path
    ) -> None:
        root = _app(
            tmp_path,
            {
                "owners.py": """
                    from tr_shared.db import BaseRepository


                    class OwnerRepository(BaseRepository):
                        async def find(self, term):
                            return await self.lookup(term)
                """,
                "handler.py": """
                    from app.owners import OwnerRepository


                    async def handle(owners: OwnerRepository, term):
                        try:
                            return await owners.find(term)
                        except Exception:
                            return None
                """,
            },
        )
        assert _lines(root) == {"handler.py": [_handler(root, "handler.py")]}

    def test_a_db_call_found_only_by_name_inside_project_code_still_counts(
        self, tmp_path: Path
    ) -> None:
        root = _app(
            tmp_path,
            {
                "jobs.py": """
                    def count(db):
                        return db.execute("select 1")


                    def report(db):
                        try:
                            return count(db)
                        except Exception:
                            return 0
                """,
            },
        )
        assert _lines(root) == {"jobs.py": [_handler(root, "jobs.py")]}
