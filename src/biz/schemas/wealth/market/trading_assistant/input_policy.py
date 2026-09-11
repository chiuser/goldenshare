"""PRD §5.5 immutable input policy, not an environment configuration."""

import regex

ACCOUNT_NAME_MAX_GRAPHEMES = 50
BROKER_NAME_MAX_GRAPHEMES = 50
NOTE_MAX_GRAPHEMES = 500
DECIMAL_INPUT_MAX_INTEGER_DIGITS = 18
MAX_SAFE_QUANTITY = 9007199254740991


def validate_graphemes(value: str, maximum: int, *, required: bool = False) -> str:
    if type(value) is not str:
        raise ValueError("Expected text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Invalid Unicode text") from exc
    if required and not value.strip():
        raise ValueError("Required text is empty")
    if len(regex.findall(r"\X", value)) > maximum:
        raise ValueError("Text exceeds visible character limit")
    return value
