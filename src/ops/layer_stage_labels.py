from __future__ import annotations


_STAGE_DISPLAY_NAMES = {
    "raw": "原始层",
    "std": "标准层",
    "resolution": "融合层",
    "serving": "服务层",
    "light": "轻量服务层",
}


def get_layer_stage_display_name(stage: str | None) -> str | None:
    normalized = (stage or "").strip().lower()
    if not normalized:
        return None
    return _STAGE_DISPLAY_NAMES.get(normalized)
