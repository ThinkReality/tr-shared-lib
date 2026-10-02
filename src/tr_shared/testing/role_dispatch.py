import re
from pathlib import Path

from tr_shared.contracts.db_pool import StatementTimeoutProfile

_PROFILE_VARIABLE = "DATABASE_STATEMENT_TIMEOUT_PROFILE"
_BACKGROUND = StatementTimeoutProfile.BACKGROUND.value
_CASE = re.compile(r'^[ \t]*case[ \t]+"\$(?:ROLE|1)"[ \t]+in[ \t]*$', re.MULTILINE)
_ESAC = re.compile(r"^[ \t]*esac[ \t]*$", re.MULTILINE)
_ARM = re.compile(r"\A\s*([^\s)]+)\)(.*)\Z", re.DOTALL)
_EXPORT = re.compile(rf"export[ \t]+{_PROFILE_VARIABLE}={_BACKGROUND}")


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
