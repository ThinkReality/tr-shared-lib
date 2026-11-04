from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import NoDecode


def split_csv(value: object) -> object:
    """Split a comma-separated environment value; refuse JSON so it fails at startup."""
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("[", "{")):
        raise ValueError("JSON is not accepted in an environment value; use a comma-separated list")
    return [item.strip() for item in value.split(",") if item.strip()]


CsvList = Annotated[list[str], NoDecode, BeforeValidator(split_csv)]
