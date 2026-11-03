import ast
from pathlib import Path

import tr_shared.testing
from tr_shared.config import BaseServiceSettings
from tr_shared.testing.config import PLUGIN_OWNED_ENV, passes_scrub

_TESTING = Path(tr_shared.testing.__file__).parent
_ACCESSORS = {"get", "setdefault", "pop"}


def _is_os_environ(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _literal(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _environ_keys() -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for path in sorted(_TESTING.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            key = None
            if isinstance(node, ast.Subscript) and _is_os_environ(node.value):
                key = _literal(node.slice)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                func = node.func
                is_accessor = func.attr in _ACCESSORS and _is_os_environ(func.value)
                is_getenv = (
                    func.attr == "getenv"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                )
                if (is_accessor or is_getenv) and node.args:
                    key = _literal(node.args[0])
            if key is not None:
                keys.setdefault(key, []).append(f"{path.name}:{node.lineno}")
    return keys


def test_every_literal_environ_key_is_owned_or_passed_through():
    keys = _environ_keys()
    assert keys, "the scan found no os.environ access at all"
    stray = {
        k: where for k, where in keys.items() if k not in PLUGIN_OWNED_ENV and not passes_scrub(k)
    }
    assert not stray


def test_environment_and_service_token_are_base_settings_fields():
    assert {"ENVIRONMENT", "SERVICE_TOKEN"} <= set(BaseServiceSettings.model_fields)
