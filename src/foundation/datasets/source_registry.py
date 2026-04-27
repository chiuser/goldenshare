from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_key: str
    display_name: str


SOURCE_DEFINITIONS: tuple[SourceDefinition, ...] = (
    SourceDefinition(source_key="tushare", display_name="Tushare"),
    SourceDefinition(source_key="biying", display_name="Biying"),
)

_SOURCE_DISPLAY_NAMES = {item.source_key: item.display_name for item in SOURCE_DEFINITIONS}
_SPECIAL_SOURCE_DISPLAY_NAMES = {
    "all": "全部来源",
    "combined": "综合来源",
}


def list_source_definitions() -> tuple[SourceDefinition, ...]:
    return SOURCE_DEFINITIONS


def get_source_display_name(source_key: str | None) -> str | None:
    normalized = (source_key or "").strip().lower()
    if not normalized:
        return None
    return _SOURCE_DISPLAY_NAMES.get(normalized) or _SPECIAL_SOURCE_DISPLAY_NAMES.get(normalized)
