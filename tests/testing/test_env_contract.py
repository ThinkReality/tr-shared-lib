"""The .env.example contract guard, and its shell-consumed exemption.

Some env keys are consumed by shell, not Python — tr-api-gateway's
RUN_MIGRATIONS_ON_STARTUP is read by deploy.sh. Those must not be reported.
The exemption is derived by GREPPING compose/Dockerfile/*.sh for the key name,
never from a prose allowlist: a written exemption cannot be checked, and one
that names instances instead of the rule rots the moment the repo changes.
"""

import sys
import textwrap
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from tr_shared.testing import env_contract
from tr_shared.testing.env_contract import assert_no_orphan_env_keys


class _Svc(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    SERVICE_NAME: str = "x"


class _CaseSensitiveExample(BaseSettings):
    """A distinctively-named field so this test can't accidentally be
    satisfied by some other reachable BaseSettings subclass in the process."""

    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, extra="ignore")

    ENV_CONTRACT_CASE_PIN: str = "unset"


_APP_SETTINGS = """
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    SERVICE_NAME: str = "x"
    APP_OWNED_KEY: str = ""
"""


def _purge_app_modules() -> None:
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]


@pytest.fixture
def make_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Path]]:
    def _make(example: str, *, deploy_sh: str = "", toml: str = "", under: str = "") -> Path:
        root = tmp_path / under / "svc" if under else tmp_path / "svc"
        (root / "app").mkdir(parents=True)
        (root / "app" / "__init__.py").write_text("")
        (root / "app" / "config.py").write_text(_APP_SETTINGS)
        (root / ".env.example").write_text(example, encoding="utf-8")
        if deploy_sh:
            (root / "deploy.sh").write_text(deploy_sh, encoding="utf-8")
        if toml:
            (root / "pyproject.toml").write_text(toml, encoding="utf-8")
        monkeypatch.syspath_prepend(str(root))
        return root

    _purge_app_modules()
    yield _make
    _purge_app_modules()


def test_declared_keys_pass(make_repo) -> None:
    assert_no_orphan_env_keys(make_repo("SERVICE_NAME=x\n"), extra_classes=(_Svc,))


def test_an_undeclared_key_fails_and_names_itself(make_repo) -> None:
    root = make_repo("SERVICE_NAME=x\nSTALE_RENAMED_KEY=1\n")

    with pytest.raises(AssertionError, match="STALE_RENAMED_KEY"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_shell_consumed_key_is_exempt(make_repo) -> None:
    root = make_repo(
        "SERVICE_NAME=x\nRUN_MIGRATIONS_ON_STARTUP=true\n",
        deploy_sh='if [ "$RUN_MIGRATIONS_ON_STARTUP" = "true" ]; then alembic upgrade head; fi\n',
    )

    assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_substring_match_does_not_grant_exemption(make_repo) -> None:
    """RUN_MIGRATIONS must not be exempted by a file mentioning RUN_MIGRATIONS_ON_STARTUP."""
    root = make_repo(
        "SERVICE_NAME=x\nRUN_MIGRATIONS=true\n",
        deploy_sh="echo $RUN_MIGRATIONS_ON_STARTUP\n",
    )

    with pytest.raises(AssertionError, match="RUN_MIGRATIONS"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_case_sensitive_classs_wrong_case_key_still_fails_through_this_entry_point(
    make_repo,
) -> None:
    """Pins the Finding-3 fix through this entry point too: a lowercase
    .env.example key must not be accepted just because its upper-cased form
    coincidentally matches a case-sensitive class's declared name — this
    guard must delegate to unclaimed_env_keys, not re-implement the
    comparison without case handling."""
    root = make_repo("SERVICE_NAME=x\nenv_contract_case_pin=1\n")

    with pytest.raises(AssertionError, match="env_contract_case_pin"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc, _CaseSensitiveExample))


def test_a_key_read_by_go_source_is_exempt(make_repo) -> None:
    """M6: WAM's Go bot reads WHATSMEOW_DB_PATH and CREWAI_BASE_URL via os.Getenv.

    Reported as orphans, the guard's own message tells the developer to delete two
    keys the bot needs to boot - the guard causing the outage it exists to prevent.
    Python is not the only runtime in this monorepo, so it cannot be the only
    thing that counts as a consumer.
    """
    root = make_repo("WHATSMEOW_DB_PATH=/data/whatsmeow.db\n")
    (root / "go-whatsapp-bot").mkdir()
    (root / "go-whatsapp-bot" / "main.go").write_text(
        'func main() { dbPath := os.Getenv("WHATSMEOW_DB_PATH") }\n', encoding="utf-8"
    )

    assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_key_no_consumer_of_any_language_reads_still_fails(make_repo) -> None:
    """The widening must not become a blanket pass. A key mentioned nowhere is
    still an orphan even once .go files are scanned."""
    root = make_repo("SERVICE_NAME=x\nSTALE_RENAMED_KEY=1\n")
    (root / "go-whatsapp-bot").mkdir()
    (root / "go-whatsapp-bot" / "main.go").write_text(
        'func main() { _ = os.Getenv("SOMETHING_ELSE") }\n', encoding="utf-8"
    )

    with pytest.raises(AssertionError, match="STALE_RENAMED_KEY"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_worktree_copy_of_this_repo_cannot_exempt_a_key(make_repo) -> None:
    """A worktree holds a copy of this same repo at another revision. Scanning it
    lets a key that only some other branch consumes look claimed here — a false
    negative that depends on what a colleague is mid-way through. iter_shell_files
    has skipped .worktrees for this reason since it was written; this scan must
    skip the same four directories.
    """
    root = make_repo("SERVICE_NAME=x\nSTALE_RENAMED_KEY=1\n")
    other_branch = root / ".worktrees" / "some-branch"
    other_branch.mkdir(parents=True)
    (other_branch / "deploy.sh").write_text("echo $STALE_RENAMED_KEY\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="STALE_RENAMED_KEY"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_repo_under_worktrees_still_sees_its_own_consumers(make_repo) -> None:
    root = make_repo(
        "SERVICE_NAME=x\nRUN_MIGRATIONS_ON_STARTUP=true\n",
        deploy_sh='echo "$RUN_MIGRATIONS_ON_STARTUP"\n',
        under=".worktrees/branch",
    )
    assert_no_orphan_env_keys(root)


def test_owners_come_from_the_app_settings_classes(make_repo) -> None:
    assert_no_orphan_env_keys(make_repo("SERVICE_NAME=x\nAPP_OWNED_KEY=1\n"))


def test_zero_settings_classes_fail(make_repo) -> None:
    root = make_repo("SERVICE_NAME=x\n")
    (root / "app" / "config.py").write_text("X = 1\n")
    with pytest.raises(AssertionError, match="zero settings classes"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


_TOML = '[tool.tr_testing]\nservice = "svc"\n\n[tool.tr_testing.env]\n'


class _AuthLibFixture(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_LIB_", extra="ignore")

    TABLE_PIN: str = ""


class TestG15Table:
    def test_an_owned_table_key_passes(self, make_repo) -> None:
        assert_no_orphan_env_keys(
            make_repo("SERVICE_NAME=x\n", toml=_TOML + 'APP_OWNED_KEY = "1"\n')
        )

    def test_an_unowned_table_key_fails(self, make_repo) -> None:
        root = make_repo("SERVICE_NAME=x\n", toml=_TOML + 'TABLE_ORPHAN = "1"\n')
        with pytest.raises(AssertionError, match="TABLE_ORPHAN"):
            assert_no_orphan_env_keys(root)

    def test_external_consumers_do_not_own_a_table_key(self, make_repo) -> None:
        root = make_repo(
            "SERVICE_NAME=x\n",
            toml=_TOML + 'TABLE_ORPHAN = "1"\n',
            deploy_sh='echo "$TABLE_ORPHAN"\n',
        )
        with pytest.raises(AssertionError, match="TABLE_ORPHAN"):
            assert_no_orphan_env_keys(root)

    def test_an_auth_lib_key_passes_only_through_extra_classes(self, make_repo) -> None:
        root = make_repo("SERVICE_NAME=x\n", toml=_TOML + 'AUTH_LIB_TABLE_PIN = "1"\n')
        with pytest.raises(AssertionError, match="AUTH_LIB_TABLE_PIN"):
            assert_no_orphan_env_keys(root)
        assert_no_orphan_env_keys(root, extra_classes=(_AuthLibFixture,))


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, str]], Path]:
    def _make(modules: dict[str, str]) -> Path:
        root = tmp_path / f"pkg_{uuid.uuid4().hex[:12]}"
        root.mkdir()
        (root / "__init__.py").write_text("")
        for name, source in modules.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.parent != root and not (path.parent / "__init__.py").exists():
                (path.parent / "__init__.py").write_text("")
            path.write_text(textwrap.dedent(source))
        monkeypatch.syspath_prepend(str(tmp_path))
        return root

    return _make


class TestSettingsClasses:
    def test_finds_direct_indirect_and_lib_based_classes(self, package) -> None:
        root = package(
            {
                "a.py": """
                    from pydantic_settings import BaseSettings
                    from tr_shared.config import BaseServiceSettings

                    class Direct(BaseSettings):
                        A: str = ""

                    class FromBase(BaseServiceSettings):
                        B: str = ""
                """,
                "sub/b.py": f"""
                    from {"{pkg}"}.a import Direct

                    class Indirect(Direct):
                        C: str = ""
                """,
            }
        )
        (root / "sub" / "b.py").write_text(
            (root / "sub" / "b.py").read_text().replace("{pkg}", root.name)
        )
        found = env_contract.settings_classes(root)
        assert sorted(c.__name__ for c in found) == ["Direct", "FromBase", "Indirect"]
        from_base = next(c for c in found if c.__name__ == "FromBase")
        assert "SERVICE_NAME" in from_base.model_fields

    def test_imports_no_module_without_a_settings_class(self, package) -> None:
        root = package(
            {
                "config.py": "from pydantic_settings import BaseSettings\nclass S(BaseSettings):\n    A: str = ''\n",
                "boom.py": "raise RuntimeError('imported a module with no settings class')\n",
            }
        )
        assert [c.__name__ for c in env_contract.settings_classes(root)] == ["S"]
        assert f"{root.name}.boom" not in sys.modules

    def test_a_lookalike_base_is_not_a_settings_class(self, package) -> None:
        root = package(
            {
                "real.py": "from pydantic_settings import BaseSettings\nclass Real(BaseSettings):\n    A: str = ''\n",
                "fake.py": "class BaseSettings:\n    pass\n\nclass Fake(BaseSettings):\n    pass\n",
            }
        )
        assert [c.__name__ for c in env_contract.settings_classes(root)] == ["Real"]

    def test_zero_classes_fail(self, package) -> None:
        root = package({"plain.py": "X = 1\n"})
        with pytest.raises(AssertionError, match="zero settings classes"):
            env_contract.settings_classes(root)


def _check_portable(tmp_path: Path, text: str) -> None:
    (tmp_path / ".env.example").write_text(text, encoding="utf-8")
    env_contract.assert_env_example_is_portable(tmp_path)


class TestG19Portable:
    @pytest.mark.parametrize(
        "line",
        [
            "A=a b",
            'A=["x"]',
            "A='[\"x\"]'",
            'A={"k": 1}',
            "A=$HOME",
            "A=pa$$word",
            'A="x$y"',
        ],
    )
    def test_each_non_portable_value_fails(self, tmp_path: Path, line: str) -> None:
        with pytest.raises(AssertionError, match="A"):
            _check_portable(tmp_path, f"B=ok\n{line}\n")

    def test_a_duplicate_key_fails(self, tmp_path: Path) -> None:
        with pytest.raises(AssertionError, match="SERVICE_TOKEN"):
            _check_portable(tmp_path, "SERVICE_TOKEN=a\nOTHER=b\nSERVICE_TOKEN=c\n")

    def test_portable_forms_pass(self, tmp_path: Path) -> None:
        _check_portable(
            tmp_path,
            "# comment\n\nA=x\nB=\nC=\"a b\"\nD='a b'\nE='pa$$word'\nexport F=x\n"
            "G=http://a.example,https://b.example\nH=postgresql+asyncpg://u:p@localhost:5432/db\n",
        )

    def test_an_inline_comment_after_whitespace_passes(self, tmp_path: Path) -> None:
        _check_portable(
            tmp_path,
            "ENVIRONMENT=development          # development | test | staging | production\n"
            "PORT=8008   # costs $0, a b\nQ='a b'  # quoted\n",
        )

    @pytest.mark.parametrize("line", ["A=VAL # comment", "A=VAL # $x", "A=VAL#x"])
    def test_a_hash_starts_a_comment_only_after_a_space(self, tmp_path: Path, line: str) -> None:
        _check_portable(tmp_path, f"{line}\n")

    @pytest.mark.parametrize("line", ["A=VAL\t# note", 'A="VAL"\t# note', "A=VAL \t# note"])
    def test_a_tab_before_a_hash_asks_for_a_space(self, tmp_path: Path, line: str) -> None:
        with pytest.raises(AssertionError, match="use a space before #"):
            _check_portable(tmp_path, f"{line}\n")

    @pytest.mark.parametrize("line", ["A=VAL#$x", "A=VAL\t# comment", 'A="VAL"\t# comment'])
    def test_a_hash_without_a_space_before_it_is_part_of_the_value(
        self, tmp_path: Path, line: str
    ) -> None:
        with pytest.raises(AssertionError, match="A"):
            _check_portable(tmp_path, f"{line}\n")

    def test_a_missing_file_fails(self, tmp_path: Path) -> None:
        with pytest.raises(AssertionError, match="missing"):
            env_contract.assert_env_example_is_portable(tmp_path)


_FIELD_MODULE = """
import collections
import dataclasses
import typing
from typing import Annotated, Optional

from pydantic import BaseModel, Json, RootModel, SecretStr
from pydantic_settings import BaseSettings, NoDecode

Csv = Annotated[list[str], NoDecode]


class Nested(BaseModel):
    a: str = ""


class NestedSettings(BaseSettings):
    a: str = ""


class Root(RootModel[list[str]]):
    pass


@dataclasses.dataclass
class Data:
    a: str = ""


class Probe(BaseSettings):
    FIELD: {annotation}
"""


class TestG21EnvSafe:
    @pytest.mark.parametrize(
        "annotation",
        [
            "list[str]",
            "typing.List[str]",
            "set[str]",
            "frozenset[str]",
            "tuple[str, ...]",
            "collections.deque[str]",
            "dict[str, str]",
            "typing.Mapping[str, str]",
            "Nested",
            "NestedSettings",
            "Root",
            "Data",
            "Json[list[str]]",
            "Optional[list[str]]",
            "Optional[Csv]",
            "str | dict[str, str]",
        ],
    )
    def test_a_json_decoded_field_fails(self, package, annotation: str) -> None:
        root = package({"config.py": _FIELD_MODULE.replace("{annotation}", annotation)})
        with pytest.raises(AssertionError, match="FIELD"):
            env_contract.assert_settings_are_env_safe(root.parent, package=root.name)

    @pytest.mark.parametrize("annotation", ["Csv", "str", "int", "bool", "SecretStr"])
    def test_a_scalar_or_csv_field_passes(self, package, annotation: str) -> None:
        root = package({"config.py": _FIELD_MODULE.replace("{annotation}", annotation)})
        env_contract.assert_settings_are_env_safe(root.parent, package=root.name)

    @pytest.mark.parametrize(
        "body",
        [
            "PYTHON_X: str = ''",
            "TMP: str = ''",
            "tmp: str = ''",
            "model_config = SettingsConfigDict(env_prefix='TMP')\n    DIR: str = ''",
            "X: str = Field('', validation_alias='TZ')",
            "X: str = Field('', validation_alias='pytest_addopts')",
        ],
    )
    def test_a_field_the_passthrough_shadows_fails(self, package, body: str) -> None:
        source = (
            "from pydantic import Field\n"
            "from pydantic_settings import BaseSettings, SettingsConfigDict\n\n"
            f"class Shadowed(BaseSettings):\n    {body}\n"
        )
        root = package({"config.py": source})
        with pytest.raises(AssertionError, match="Shadowed"):
            env_contract.assert_settings_are_env_safe(root.parent, package=root.name)

    def test_zero_classes_fail(self, package) -> None:
        root = package({"plain.py": "X = 1\n"})
        with pytest.raises(AssertionError, match="zero settings classes"):
            env_contract.assert_settings_are_env_safe(root.parent, package=root.name)

    def test_a_service_repo_is_checked_through_its_app_folder(self, make_repo) -> None:
        root = make_repo("SERVICE_NAME=x\n")
        (root / "app" / "config.py").write_text(
            "from pydantic_settings import BaseSettings\n\n"
            "class AppSettings(BaseSettings):\n    FIELD: list[str] = []\n"
        )
        with pytest.raises(AssertionError, match="FIELD"):
            env_contract.assert_settings_are_env_safe(root)
