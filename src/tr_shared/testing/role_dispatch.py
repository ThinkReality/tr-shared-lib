import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from tr_shared.contracts.db_pool import StatementTimeoutProfile
from tr_shared.testing.env_contract import settings_class_names

_PROFILE_VARIABLE = "DATABASE_STATEMENT_TIMEOUT_PROFILE"
_BACKGROUND = StatementTimeoutProfile.BACKGROUND.value
_CASE = re.compile(r'^[ \t]*case[ \t]+"\$(?:ROLE|1)"[ \t]+in[ \t]*$', re.MULTILINE)
_ESAC = re.compile(r"^[ \t]*esac[ \t]*$", re.MULTILINE)
_ARM = re.compile(r"\A\s*([^\s)]+)\)(.*)\Z", re.DOTALL)
_EXPORT = re.compile(rf"export[ \t]+{_PROFILE_VARIABLE}={_BACKGROUND}")
_APP_REFERENCE = re.compile(r"([A-Za-z_][\w.]*):[A-Za-z_]\w*")
_PYTHON = re.compile(r"python[\d.]*")
_START_SCRIPTS = ("deploy.sh", "docker-entrypoint.sh")
_VALIDATION_ERROR = re.compile(r"validation errors? for (\w+)")
STARTUP_TIMEOUT_SECONDS = 10


def _without_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _first_command(body: str) -> str:
    return next((line.strip() for line in body.splitlines() if line.strip()), "")


def assert_background_roles_set_statement_profile(
    script: Path, request_roles: frozenset[str] = frozenset({"api"})
) -> None:
    code = _without_comments(script.read_text())
    cases = list(_CASE.finditer(code))
    assert len(cases) == 1, f"{script.name}: expected one role dispatch, found {len(cases)}"
    esac = _ESAC.search(code, cases[0].end())
    assert esac, f"{script.name}: the role dispatch has no esac"
    problems: list[str] = []
    if _PROFILE_VARIABLE in code[: cases[0].start()] + code[esac.end() :]:
        problems.append(f"{_PROFILE_VARIABLE} is set outside the role dispatch")
    named: set[str] = set()
    for chunk in code[cases[0].end() : esac.start()].split(";;"):
        if not chunk.strip():
            continue
        arm = _ARM.match(chunk)
        assert arm, f"{script.name}: cannot parse case arm {chunk.strip()!r}"
        label, body = arm.groups()
        roles = frozenset(label.split("|"))
        named |= roles
        if roles == {"*"}:
            continue
        if roles <= request_roles:
            if _PROFILE_VARIABLE in body:
                problems.append(f"{label}: a request role must not set {_PROFILE_VARIABLE}")
        elif roles & request_roles:
            problems.append(f"{label}: the arm mixes request and background roles")
        elif not _EXPORT.fullmatch(_first_command(body)):
            problems.append(
                f"{label}: the first command must be `export {_PROFILE_VARIABLE}={_BACKGROUND}`"
            )
    for role in sorted(request_roles - named):
        problems.append(f"{role}: request role has no case arm")
    assert not problems, f"{script.name}:\n" + "\n".join(problems)


def _option_value(tokens: list[str], start: int, *names: str) -> str | None:
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token in names and index + 1 < len(tokens):
            return tokens[index + 1]
        for name in names:
            if name.startswith("--") and token.startswith(f"{name}="):
                return token.split("=", 1)[1]
    return None


def _line_modules(line: str) -> dict[str, bool]:
    try:
        tokens = shlex.split(line.rstrip().removesuffix("\\"), comments=True)
    except ValueError:
        tokens = line.split()
    modules: dict[str, bool] = {}
    for index, token in enumerate(tokens):
        command = token.rsplit("/", 1)[-1]
        if command == "uvicorn":
            reference = next(
                (m for t in tokens[index + 1 :] if (m := _APP_REFERENCE.fullmatch(t))), None
            )
            if reference:
                modules.setdefault(reference.group(1), False)
        elif command == "celery":
            app = _option_value(tokens, index + 1, "-A", "--app")
            if app:
                modules.setdefault(app.split(":", 1)[0], False)
        elif _PYTHON.fullmatch(command):
            module = _option_value(tokens, index + 1, "-m")
            if module:
                modules[module] = True
    return modules


def _launches(*scripts: Path) -> dict[str, bool]:
    modules: dict[str, bool] = {}
    for script in scripts:
        for line in script.read_text().splitlines():
            if not line.lstrip().startswith("#"):
                for module, run_as_main in _line_modules(line).items():
                    modules[module] = modules.get(module, False) or run_as_main
    names = ", ".join(s.name for s in scripts)
    if not modules:
        raise ValueError(f"{names}: no start command (uvicorn, celery -A or python -m) found")
    if "app.main" not in modules:
        raise ValueError(f"{names}: no start command launches app.main (found {sorted(modules)})")
    return modules


def entry_modules(*scripts: Path) -> set[str]:
    """Modules the start scripts launch: ``uvicorn X:app``, ``celery -A X`` and ``python -m X``.

    Raises when the scripts start nothing, or nothing that imports ``app.main``.
    """
    return set(_launches(*scripts))


def assert_entry_points_require_database_url(repo_root: Path) -> None:
    """Every start-script module and every tracked ``alembic.ini`` refuses ``DATABASE_URL=""``.

    The modules come from ``deploy.sh`` and ``docker-entrypoint.sh`` (``entry_modules``).
    One a script starts with ``python -m`` runs that way; any other is imported. Each
    case runs with the test's environment plus ``DATABASE_URL=""`` and must exit
    non-zero with a validation error for a settings class under ``app/`` that names
    ``DATABASE_URL``. A case still running after ``STARTUP_TIMEOUT_SECONDS`` started
    without it.
    """
    scripts = [repo_root / name for name in _START_SCRIPTS if (repo_root / name).is_file()]
    assert scripts, f"{repo_root}: no {' or '.join(_START_SCRIPTS)}"
    inis = subprocess.run(
        ["git", "ls-files", "--", "*alembic.ini"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    cases = [
        ["-m", module] if run_as_main else ["-c", f"import {module}"]
        for module, run_as_main in sorted(_launches(*scripts).items())
    ]
    cases += [["-m", "alembic", "-c", ini, "current"] for ini in inis]
    classes = sorted(settings_class_names(repo_root / "app"))
    env = {**os.environ, "DATABASE_URL": ""}
    problems: list[str] = []
    for args in cases:
        label = "python " + " ".join(args)
        try:
            result = subprocess.run(
                [sys.executable, *args],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=STARTUP_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            problems.append(
                f"{label}: still running after {STARTUP_TIMEOUT_SECONDS} s, "
                "so it started without DATABASE_URL"
            )
            continue
        named = _VALIDATION_ERROR.search(result.stderr)
        if (
            result.returncode == 0
            or not named
            or named.group(1) not in classes
            or "DATABASE_URL" not in result.stderr
        ):
            problems.append(
                f"{label}: exit {result.returncode}, expected a validation error for one of "
                f"{classes} naming DATABASE_URL\n{result.stderr[-2000:]}"
            )
    assert not problems, "\n".join(problems)
