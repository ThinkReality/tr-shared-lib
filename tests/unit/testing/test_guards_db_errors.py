"""Database errors reach the boundary: no swallow, no flattening into a generic 500.

Each detector returns the line of the offending ``except`` handler, so every
fixture asserts the exact line rather than "something was found".
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from tr_shared.testing.guards import (
    Exemption,
    assert_no_flattened_errors,
    assert_no_swallowed_db_errors,
    detect_flattened_errors,
    detect_swallowed_db_errors,
)


def _source(text: str) -> str:
    return dedent(text).lstrip("\n")


def _handler_line(source: str, marker: str) -> int:
    return next(n for n, line in enumerate(source.splitlines(), 1) if marker in line)


def _tree(tmp_path: Path, name: str, source: str) -> Path:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)
    return tmp_path


GENERIC_NAMES = (
    "SQLAlchemyError",
    "DBAPIError",
    "OperationalError",
    "InterfaceError",
    "DatabaseError",
    "TimeoutError",
)


class TestGenericSqlalchemyCatch:
    @pytest.mark.parametrize("name", GENERIC_NAMES)
    def test_flags_each_generic_class_without_a_reraise(self, name: str) -> None:
        source = _source(
            f"""
            from sqlalchemy.exc import {name}

            def load(db):
                try:
                    return db.get(1)
                except {name}:
                    return None
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]

    @pytest.mark.parametrize(
        ("imports", "caught"),
        [
            ("from sqlalchemy.exc import OperationalError as OpError", "OpError"),
            ("from sqlalchemy import exc", "exc.OperationalError"),
            ("import sqlalchemy", "sqlalchemy.exc.OperationalError"),
            ("import sqlalchemy.exc", "sqlalchemy.exc.SQLAlchemyError"),
            ("import sqlalchemy.exc as sa_exc", "sa_exc.DBAPIError"),
            ("import sqlalchemy as sa", "sa.exc.InterfaceError"),
            ("from sqlalchemy.exc import SQLAlchemyError", "(ValueError, SQLAlchemyError)"),
        ],
    )
    def test_resolves_every_import_form(self, imports: str, caught: str) -> None:
        source = _source(
            f"""
            {imports}

            def load():
                try:
                    return compute()
                except {caught}:
                    return None
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]

    def test_resolves_an_import_made_inside_the_function(self) -> None:
        source = _source(
            """
            def load():
                from sqlalchemy.exc import SQLAlchemyError

                try:
                    return compute()
                except SQLAlchemyError:
                    return None
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]

    @pytest.mark.parametrize(
        ("imports", "caught"),
        [
            ("import psycopg2", "psycopg2.OperationalError"),
            ("from psycopg2 import OperationalError", "OperationalError"),
            ("from psycopg2 import errors", "errors.InterfaceError"),
            ("import redis", "redis.exceptions.TimeoutError"),
            ("from redis.exceptions import TimeoutError", "TimeoutError"),
            ("from kombu.exceptions import OperationalError", "OperationalError"),
            ("import asyncio", "asyncio.TimeoutError"),
            ("", "TimeoutError"),
            ("from tr_shared.exceptions import DatabaseError", "DatabaseError"),
            ("", "OperationalError"),
        ],
    )
    def test_same_names_from_other_libraries_do_not_match(self, imports: str, caught: str) -> None:
        source = _source(
            f"""
            {imports}

            def load():
                try:
                    return compute()
                except {caught}:
                    return None
            """
        )
        assert detect_swallowed_db_errors(source) == []

    @pytest.mark.parametrize(
        ("imports", "caught"),
        [
            ("from sqlalchemy.exc import IntegrityError", "IntegrityError"),
            ("from sqlalchemy.exc import DataError", "DataError"),
            ("from sqlalchemy.exc import NoResultFound", "NoResultFound"),
            ("from sqlalchemy.exc import MultipleResultsFound", "MultipleResultsFound"),
            ("from sqlalchemy.orm.exc import NoResultFound", "NoResultFound"),
            ("from sqlalchemy import exc", "(exc.IntegrityError, exc.DataError)"),
        ],
    )
    def test_narrow_semantic_catches_are_allowed(self, imports: str, caught: str) -> None:
        source = _source(
            f"""
            {imports}

            async def claim(db, row):
                try:
                    db.add(row)
                    await db.flush()
                except {caught}:
                    return False
                return True
            """
        )
        assert detect_swallowed_db_errors(source) == []

    @pytest.mark.parametrize("body", ["raise", "raise ConflictError() from exc"])
    def test_a_reraising_handler_is_allowed(self, body: str) -> None:
        source = _source(
            f"""
            from sqlalchemy.exc import SQLAlchemyError

            def load(db):
                try:
                    return db.get(1)
                except SQLAlchemyError as exc:
                    logger.error("load_failed")
                    {body}
            """
        )
        assert detect_swallowed_db_errors(source) == []

    def test_an_outage_sibling_does_not_excuse_a_generic_catch(self) -> None:
        source = _source(
            """
            from sqlalchemy.exc import SQLAlchemyError

            def load(db):
                try:
                    return db.get(1)
                except DatabaseUnavailableError:
                    raise
                except SQLAlchemyError:
                    return None
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except SQLAlchemy")]


class TestBroadCatchInRepository:
    @pytest.mark.parametrize(
        ("class_name", "caught"),
        [
            ("TaskTrackingRepository", "except Exception:"),
            ("ListedUrlRepo", "except BaseException:"),
            ("UserRepository", "except:"),
            ("UserRepository", "except (ValueError, Exception):"),
        ],
    )
    def test_flags_a_broad_swallow_anywhere_in_the_class(
        self, class_name: str, caught: str
    ) -> None:
        source = _source(
            f"""
            class {class_name}:
                def count(self):
                    try:
                        return compute()
                    {caught}
                        return 0
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]

    def test_flags_a_handler_in_a_function_nested_in_a_repository_method(self) -> None:
        source = _source(
            """
            class TaskTrackingRepository:
                def run(self):
                    def inner():
                        try:
                            return compute()
                        except Exception:
                            return None
                    return inner()
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]

    def test_a_reraising_repository_handler_is_allowed(self) -> None:
        source = _source(
            """
            class TaskTrackingRepository:
                def count(self):
                    try:
                        return compute()
                    except Exception:
                        logger.exception("count_failed")
                        raise
            """
        )
        assert detect_swallowed_db_errors(source) == []

    def test_the_same_handler_outside_a_repository_without_db_work_is_allowed(self) -> None:
        source = _source(
            """
            class ReportService:
                def count(self):
                    try:
                        return compute()
                    except Exception:
                        return 0
            """
        )
        assert detect_swallowed_db_errors(source) == []


class TestBroadCatchAroundDbWork:
    @pytest.mark.parametrize(
        "call",
        [
            "await session.execute(stmt)",
            "await self.db.flush()",
            "self._db.begin_nested()",
            "await self.user_repo.get_by_id_in_tenant(user_id)",
            "await self.auth_repository.get_agents_batch(ids)",
            "AsyncSessionLocal()",
            "next(get_sync_db())",
            "await execute_sql(sql)",
            "await AuditLogRepository(db).create(row)",
            "conn.execute(stmt)",
            "result.scalar_one()",
            "await service.get_by_id(1)",
            "await self._bridge_get_task_urls_from_db(task_id)",
        ],
    )
    def test_flags_a_broad_swallow_around_a_db_looking_call(self, call: str) -> None:
        source = _source(
            f"""
            async def handle(self, session, db, conn, result, service, stmt, sql, row, ids):
                try:
                    {call}
                except Exception:
                    logger.warning("best_effort_failed")
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]

    @pytest.mark.parametrize(
        "call",
        [
            "await self.redis.get(key)",
            "pipe.execute()",
            "await self._session_cache.cache_session(session)",
            "cache_keys.websocket_session(user_id)",
            "driver_session.get(url)",
            "await httpx.AsyncClient().get(url)",
            "publish(event)",
        ],
    )
    def test_calls_that_only_look_like_db_work_are_not_flagged(self, call: str) -> None:
        source = _source(
            f"""
            async def handle(self, key, pipe, session, user_id, url, event):
                try:
                    {call}
                except Exception:
                    logger.warning("best_effort_failed")
            """
        )
        assert detect_swallowed_db_errors(source) == []

    def test_a_reraising_handler_around_db_work_is_allowed(self) -> None:
        source = _source(
            """
            async def handle(db):
                try:
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            """
        )
        assert detect_swallowed_db_errors(source) == []

    def test_try_star_is_scanned(self) -> None:
        source = _source(
            """
            async def handle(db):
                try:
                    await db.commit()
                except* Exception:
                    logger.warning("commit_failed")
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except*")]


class TestNestedScopes:
    @pytest.mark.parametrize(
        "body",
        [
            "def later():\n        return db.execute(stmt)\n    register(later)",
            "register(lambda: db.execute(stmt))",
            "class Later:\n        def run(self):\n            return db.execute(stmt)\n    register(Later)",
        ],
    )
    def test_db_work_only_inside_a_nested_scope_is_not_flagged(self, body: str) -> None:
        source = (
            f"def handle(db, stmt):\n  try:\n    {body}\n  except Exception:\n    return None\n"
        )
        assert detect_swallowed_db_errors(source) == []

    def test_a_raise_inside_a_nested_def_is_not_a_reraise(self) -> None:
        source = _source(
            """
            async def handle(db):
                try:
                    await db.commit()
                except Exception:
                    def explain():
                        raise RuntimeError("never called")
                    logger.warning("commit_failed")
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]


class TestOutageSiblingCredit:
    @pytest.mark.parametrize(
        "sibling",
        [
            "except DatabaseUnavailableError:",
            "except DATABASE_OUTAGE_ERRORS:",
            "except db_errors.DatabaseUnavailableError:",
            "except tr_db.DATABASE_OUTAGE_ERRORS:",
            "except (DatabaseUnavailableError, DatabaseTimeoutError):",
        ],
    )
    def test_an_earlier_bare_reraise_sibling_credits_a_broad_catch_around_db_work(
        self, sibling: str
    ) -> None:
        source = _source(
            f"""
            async def handle(db):
                try:
                    await db.commit()
                {sibling}
                    raise
                except Exception:
                    logger.warning("best_effort_failed")
            """
        )
        assert detect_swallowed_db_errors(source) == []

    def test_an_earlier_bare_reraise_sibling_credits_a_repository_catch(self) -> None:
        source = _source(
            """
            class ServiceTokenRepository:
                async def record_token_usage(self):
                    try:
                        await self.db.flush()
                    except DATABASE_OUTAGE_ERRORS:
                        raise
                    except Exception:
                        return False
            """
        )
        assert detect_swallowed_db_errors(source) == []

    @pytest.mark.parametrize(
        "sibling_body",
        [
            'logger.error("outage")\n    raise',
            "raise ServiceUnavailableError()",
            "pass",
        ],
    )
    def test_a_sibling_whose_body_is_not_a_bare_raise_does_not_credit(
        self, sibling_body: str
    ) -> None:
        source = (
            "async def handle(db):\n"
            "  try:\n"
            "    await db.commit()\n"
            "  except DatabaseUnavailableError:\n"
            f"    {sibling_body}\n"
            "  except Exception:\n"
            "    logger.warning('best_effort_failed')\n"
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except Exception")]

    def test_a_later_sibling_does_not_credit(self) -> None:
        source = _source(
            """
            async def handle(db):
                try:
                    await db.commit()
                except Exception:
                    logger.warning("best_effort_failed")
                except DatabaseUnavailableError:
                    raise
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except Exception")]

    def test_a_sibling_catching_something_else_does_not_credit(self) -> None:
        source = _source(
            """
            async def handle(db):
                try:
                    await db.commit()
                except ValueError:
                    raise
                except Exception:
                    logger.warning("best_effort_failed")
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except Exception")]


class TestFlattenedErrors:
    @pytest.mark.parametrize(
        ("caught", "raised"),
        [
            ("except Exception as e:", 'raise InternalServerError("Failed to get role")'),
            ("except Exception as e:", 'raise DatabaseError("Failed to trigger quiz")'),
            ("except Exception as e:", "raise AuthInternalServerError() from e"),
            ("except Exception as e:", "raise InternalServerError"),
            ("except Exception as e:", 'raise HTTPException(500, "Failed")'),
            ("except Exception as e:", 'raise HTTPException(status_code=500, detail="Failed")'),
            (
                "except Exception as e:",
                "raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))",
            ),
            ("except BaseException:", 'raise InternalServerError("x")'),
            ("except:", 'raise InternalServerError("x")'),
            ("except (ValueError, Exception):", 'raise InternalServerError("x")'),
        ],
    )
    def test_flags_a_broad_handler_that_raises_a_generic_500(
        self, caught: str, raised: str
    ) -> None:
        source = f"async def route():\n  try:\n    return await work()\n  {caught}\n    {raised}\n"
        assert detect_flattened_errors(source) == [_handler_line(source, "except")]

    @pytest.mark.parametrize(
        ("caught", "raised"),
        [
            (
                "except SQLAlchemyError as e:",
                'raise DatabaseError(f"Failed to create role: {e!s}") from e',
            ),
            (
                "except SQLAlchemyError as exc:",
                'raise DatabaseError("Database operation failed") from exc',
            ),
            ("except OperationalError:", 'raise InternalServerError("x")'),
            ("except (ValueError, DBAPIError):", 'raise HTTPException(500, "Failed")'),
        ],
    )
    def test_flags_a_generic_sqlalchemy_handler_that_raises_a_generic_500(
        self, caught: str, raised: str
    ) -> None:
        source = (
            "from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError\n"
            f"async def route():\n  try:\n    return await work()\n  {caught}\n    {raised}\n"
        )
        assert detect_flattened_errors(source) == [_handler_line(source, "except")]

    @pytest.mark.parametrize(
        ("caught", "raised"),
        [
            ("except IntegrityError as e:", 'raise DatabaseError("integrity") from e'),
            ("except SQLAlchemyError:", "raise"),
        ],
    )
    def test_allows_a_narrow_sqlalchemy_conversion_and_a_generic_reraise(
        self, caught: str, raised: str
    ) -> None:
        source = (
            "from sqlalchemy.exc import IntegrityError, SQLAlchemyError\n"
            f"async def route():\n  try:\n    return await work()\n  {caught}\n    {raised}\n"
        )
        assert detect_flattened_errors(source) == []

    def test_flags_a_conditional_conversion(self) -> None:
        source = _source(
            """
            def save(self, attempt):
                try:
                    return self.write()
                except Exception as e:
                    if attempt >= 3:
                        raise DatabaseError("gave up") from e
                    return None
            """
        )
        assert detect_flattened_errors(source) == [_handler_line(source, "except")]

    @pytest.mark.parametrize(
        ("caught", "raised"),
        [
            ("except ValueError as e:", "raise ValidationError(str(e))"),
            ("except ValueError as e:", 'raise InternalServerError("narrow")'),
            ("except Exception as e:", 'raise ServiceUnavailableError("pf down")'),
            ("except Exception as e:", 'raise HTTPException(status_code=404, detail="gone")'),
            (
                "except Exception as e:",
                "raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)",
            ),
            ("except Exception as e:", "raise"),
            ("except Exception as e:", "raise e"),
        ],
    )
    def test_allows_specific_conversions_and_passthrough(self, caught: str, raised: str) -> None:
        source = f"async def route():\n  try:\n    return await work()\n  {caught}\n    {raised}\n"
        assert detect_flattened_errors(source) == []

    def test_a_flattener_inside_a_nested_def_is_not_the_handlers_own(self) -> None:
        source = _source(
            """
            async def route():
                try:
                    return await work()
                except Exception:
                    def convert():
                        raise InternalServerError("x")
                    return fallback(convert)
            """
        )
        assert detect_flattened_errors(source) == []

    def test_try_star_is_scanned(self) -> None:
        source = _source(
            """
            async def route():
                try:
                    return await work()
                except* Exception:
                    raise InternalServerError("x")
            """
        )
        assert detect_flattened_errors(source) == [_handler_line(source, "except*")]


class TestModuleLevelTupleAliases:
    @pytest.mark.parametrize(
        "alias",
        [
            "_DB_ERRORS = (SQLAlchemyError, OperationalError)",
            "_DB_ERRORS: tuple[type[Exception], ...] = (SQLAlchemyError, OperationalError)",
            "_BASE = (SQLAlchemyError,)\n_DB_ERRORS = (ValueError, _BASE)",
        ],
    )
    def test_an_aliased_generic_sqlalchemy_catch_is_flagged(self, alias: str) -> None:
        source = (
            "from sqlalchemy.exc import OperationalError, SQLAlchemyError\n"
            f"{alias}\n"
            "def load():\n"
            "    try:\n"
            "        return compute()\n"
            "    except _DB_ERRORS:\n"
            "        return None\n"
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]

    def test_an_aliased_broad_catch_in_a_repository_is_flagged(self) -> None:
        source = _source(
            """
            _ANY = (ValueError, Exception)

            class TaskTrackingRepository:
                def count(self):
                    try:
                        return compute()
                    except _ANY:
                        return 0
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]

    def test_an_aliased_broad_catch_around_db_work_is_flagged(self) -> None:
        source = _source(
            """
            BEST_EFFORT_ERRORS = (Exception,)

            async def handle(db):
                try:
                    await db.commit()
                except BEST_EFFORT_ERRORS:
                    logger.warning("commit_failed")
            """
        )
        assert detect_swallowed_db_errors(source) == [_handler_line(source, "except")]

    def test_an_aliased_outage_sibling_credits(self) -> None:
        source = _source(
            """
            _OUTAGE = (DatabaseUnavailableError,)

            async def handle(db):
                try:
                    await db.commit()
                except _OUTAGE:
                    raise
                except Exception:
                    logger.warning("best_effort_failed")
            """
        )
        assert detect_swallowed_db_errors(source) == []

    def test_an_aliased_narrow_catch_is_allowed(self) -> None:
        source = _source(
            """
            from sqlalchemy.exc import IntegrityError

            _DUPLICATE = (IntegrityError,)

            async def claim(db, row):
                try:
                    db.add(row)
                    await db.flush()
                except _DUPLICATE:
                    return False
                return True
            """
        )
        assert detect_swallowed_db_errors(source) == []

    def test_an_aliased_broad_flattener_is_flagged(self) -> None:
        source = _source(
            """
            _ANY = (Exception,)

            async def route():
                try:
                    return await work()
                except _ANY:
                    raise InternalServerError("failed")
            """
        )
        assert detect_flattened_errors(source) == [_handler_line(source, "except")]


SWALLOW = _source(
    """
    from sqlalchemy.exc import SQLAlchemyError

    def load(db):
        try:
            return db.get(1)
        except SQLAlchemyError:
            return None
    """
)

FLATTEN = _source(
    """
    async def route():
        try:
            return await work()
        except Exception:
            raise InternalServerError("failed")
    """
)

PROBE = Exemption(reason="a probe reports DB state " + "x" * 60, requires_symbols=("def load",))
CONVERTER = Exemption(reason="converts on purpose " + "x" * 60, requires_symbols=("def route",))


@pytest.mark.parametrize(
    ("assert_guard", "violation", "exemption", "message"),
    [
        (assert_no_swallowed_db_errors, SWALLOW, PROBE, "swallow"),
        (assert_no_flattened_errors, FLATTEN, CONVERTER, "500"),
    ],
)
class TestAssertions:
    def test_fails_on_a_violation(
        self, tmp_path: Path, assert_guard, violation: str, exemption: Exemption, message: str
    ) -> None:
        root = _tree(tmp_path, "services/loader.py", violation)
        with pytest.raises(AssertionError, match=message) as failure:
            assert_guard(root)
        assert "services/loader.py" in str(failure.value)

    def test_passes_with_an_exemption_for_that_file(
        self, tmp_path: Path, assert_guard, violation: str, exemption: Exemption, message: str
    ) -> None:
        root = _tree(tmp_path, "services/loader.py", violation)
        assert_guard(root, {"services/loader.py": exemption})

    def test_fails_on_a_stale_exemption(
        self, tmp_path: Path, assert_guard, violation: str, exemption: Exemption, message: str
    ) -> None:
        root = _tree(tmp_path, "services/loader.py", "def load():\n    return 1\n")
        with pytest.raises(AssertionError, match="no longer violate"):
            assert_guard(root, {"services/loader.py": exemption})

    def test_skips_alembic_trees(
        self, tmp_path: Path, assert_guard, violation: str, exemption: Exemption, message: str
    ) -> None:
        root = _tree(tmp_path, "modules/auth/alembic/versions/0001_init.py", violation)
        assert_guard(root)
