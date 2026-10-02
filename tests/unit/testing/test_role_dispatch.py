from pathlib import Path

import pytest

from tr_shared.config import BaseServiceSettings
from tr_shared.contracts.db_pool import StatementTimeoutProfile
from tr_shared.testing.role_dispatch import (
    _PROFILE_VARIABLE,
    assert_background_roles_set_statement_profile,
)

_EXPORT = f"export {_PROFILE_VARIABLE}={StatementTimeoutProfile.BACKGROUND.value}"
_PREAMBLE = '#!/bin/sh\nset -e\nROLE="${1:-api}"\n\n'


def _dispatcher(indent: str = "  ", subject: str = '"$ROLE"') -> str:
    arms = [
        "worker|beat)",
        f"  {_EXPORT}",
        "  exec celery -A app.celery_app worker -Q tasks",
        "  ;;",
        "consumer)",
        f"  {_EXPORT}",
        "  exec python -m app.workers.consumer",
        "  ;;",
        "api) ;;",
        '*) echo "unknown role: $ROLE (expected api|worker|beat|consumer)"; exit 64;;',
    ]
    body = "\n".join(indent + line for line in arms)
    return f"{_PREAMBLE}case {subject} in\n{body}\nesac\n\nexec uvicorn app.main:app\n"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "deploy.sh"
    path.write_text(text)
    return path


@pytest.mark.parametrize("indent", ["", "  ", "    "])
@pytest.mark.parametrize("subject", ['"$ROLE"', '"$1"'])
def test_real_dispatcher_shapes_pass(tmp_path, indent, subject):
    assert_background_roles_set_statement_profile(_write(tmp_path, _dispatcher(indent, subject)))


def test_a_background_arm_without_the_export_fails(tmp_path):
    text = _dispatcher().replace(f"consumer)\n    {_EXPORT}\n", "consumer)\n")
    with pytest.raises(AssertionError, match="consumer"):
        assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_an_export_after_exec_fails(tmp_path):
    text = _dispatcher().replace(
        f"consumer)\n    {_EXPORT}\n    exec python -m app.workers.consumer\n",
        f"consumer)\n    exec python -m app.workers.consumer\n    {_EXPORT}\n",
    )
    with pytest.raises(AssertionError, match="consumer"):
        assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_an_export_inside_a_conditional_fails(tmp_path):
    text = _dispatcher().replace(
        f"consumer)\n    {_EXPORT}\n",
        f'consumer)\n    if [ -n "$SLOW" ]; then\n      {_EXPORT}\n    fi\n',
    )
    with pytest.raises(AssertionError, match="consumer"):
        assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_a_comment_before_the_export_is_allowed(tmp_path):
    text = _dispatcher().replace(
        f"consumer)\n    {_EXPORT}\n", f"consumer)\n    # long statement cap\n    {_EXPORT}\n"
    )
    assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_a_commented_out_export_does_not_count(tmp_path):
    text = _dispatcher().replace(f"consumer)\n    {_EXPORT}", f"consumer)\n    # {_EXPORT}")
    with pytest.raises(AssertionError, match="consumer"):
        assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_an_export_of_the_wrong_profile_fails(tmp_path):
    wrong = f"export {_PROFILE_VARIABLE}={StatementTimeoutProfile.REQUEST.value}"
    text = _dispatcher().replace(_EXPORT, wrong, 1)
    with pytest.raises(AssertionError, match="worker"):
        assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_a_request_arm_setting_the_profile_fails(tmp_path):
    text = _dispatcher().replace("api) ;;", f"api) {_EXPORT} ;;")
    with pytest.raises(AssertionError, match="api"):
        assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_an_export_outside_the_dispatch_fails(tmp_path):
    text = _dispatcher().replace(_PREAMBLE, f"{_PREAMBLE}{_EXPORT}\n")
    with pytest.raises(AssertionError, match="outside"):
        assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_an_arm_mixing_request_and_background_roles_fails(tmp_path):
    text = _dispatcher().replace("worker|beat)", "api|worker|beat)")
    with pytest.raises(AssertionError, match="mixes"):
        assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_a_script_without_a_role_dispatch_fails(tmp_path):
    with pytest.raises(AssertionError, match="role dispatch"):
        assert_background_roles_set_statement_profile(
            _write(tmp_path, "#!/bin/sh\nexec uvicorn app.main:app\n")
        )


def test_two_role_dispatches_fail(tmp_path):
    text = _dispatcher() + _dispatcher().removeprefix(_PREAMBLE)
    with pytest.raises(AssertionError, match="role dispatch"):
        assert_background_roles_set_statement_profile(_write(tmp_path, text))


def test_a_request_role_without_an_arm_fails(tmp_path):
    with pytest.raises(AssertionError, match="web"):
        assert_background_roles_set_statement_profile(
            _write(tmp_path, _dispatcher()), request_roles=frozenset({"api", "web"})
        )


def test_custom_request_roles(tmp_path):
    text = _dispatcher().replace("api) ;;", "api|web) ;;")
    assert_background_roles_set_statement_profile(
        _write(tmp_path, text), request_roles=frozenset({"api", "web"})
    )


def test_the_guarded_variable_is_the_settings_field():
    assert _PROFILE_VARIABLE in BaseServiceSettings.model_fields
