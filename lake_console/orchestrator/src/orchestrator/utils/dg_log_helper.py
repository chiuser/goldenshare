from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class DgStdoutLogger:
    def __init__(self, component: str) -> None:
        if not component.strip():
            raise ValueError("DgStdoutLogger component must not be empty.")
        self._component = component.strip()

    def stdout(self, event: str, **fields: Any) -> None:
        if not event.strip():
            raise ValueError("DgStdoutLogger event must not be empty.")

        field_parts = [
            f"{_format_key(key)}={_format_value(value)}"
            for key, value in fields.items()
        ]
        message = " ".join([f"[{self._component}]", f"event={event.strip()}", *field_parts])
        print(message, flush=True)


def _format_key(value: str) -> str:
    return value.strip().replace(" ", "_")


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return f"<{type(value).__name__}>"
    if isinstance(value, Sequence) and not isinstance(value, str):
        return f"<{type(value).__name__}>"

    text = str(value).strip()
    if not text:
        return "-"
    return " ".join(text.split())
