from __future__ import annotations

from collections.abc import Iterable

from src.foundation.services.sync_v2.contracts import InputField, InputSchema

def build_input_schema(*, fields: Iterable[InputField]) -> InputSchema:
    return InputSchema(fields=tuple(fields))
