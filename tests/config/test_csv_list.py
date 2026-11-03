import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

import tr_shared.config


def _settings(**kwargs: object) -> BaseSettings:
    class Settings(BaseSettings):
        ITEMS: tr_shared.config.CsvList = ["default"]

    return Settings(**kwargs)


def test_a_comma_separated_value_is_split_and_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ITEMS", "a, b,,c")
    assert _settings().ITEMS == ["a", "b", "c"]


def test_an_empty_value_is_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ITEMS", "")
    assert _settings().ITEMS == []


def test_a_list_passes_unchanged() -> None:
    assert _settings(ITEMS=["a", "b"]).ITEMS == ["a", "b"]


def test_a_list_default_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ITEMS", raising=False)
    assert _settings().ITEMS == ["default"]


@pytest.mark.parametrize("value", ['["a", "b"]', '{"a": 1}', ' ["a"]'])
def test_json_raises_and_names_the_field(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ITEMS", value)
    with pytest.raises(ValidationError, match="ITEMS"):
        _settings()
