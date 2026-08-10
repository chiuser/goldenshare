from __future__ import annotations

from dataclasses import dataclass

from src.foundation.ingestion.codebook import INGESTION_ERROR_CODEBOOK
from src.foundation.ingestion.errors import StructuredError


@dataclass(frozen=True, slots=True)
class IngestionErrorPresentation:
    title: str
    operator_message: str
    suggested_action: str


def present_ingestion_error(error: StructuredError) -> IngestionErrorPresentation:
    entry = next((item for item in INGESTION_ERROR_CODEBOOK if item.code == error.error_code), None)
    if error.error_code == "units_exceeded":
        planned_units = _positive_int(error.details.get("planned_units"))
        max_units = _positive_int(error.details.get("max_units_per_execution"))
        if planned_units is not None and max_units is not None:
            message = f"本次范围会生成 {planned_units} 个处理单元，超过单次上限 {max_units} 个。请缩小时间范围后重试。"
        else:
            message = "本次范围生成的处理单元超过单次上限，请缩小时间范围后重试。"
        return IngestionErrorPresentation(
            title="任务范围超过单次上限",
            operator_message=message,
            suggested_action="缩小本次时间范围后重新提交。",
        )

    label = entry.label if entry is not None else "任务规划或参数校验未通过"
    suggested_action = entry.suggested_action if entry is not None and entry.suggested_action else "检查本次输入后重新提交。"
    title = "任务参数未通过校验" if error.error_type == "validation" else "任务规划未通过"
    return IngestionErrorPresentation(
        title=title,
        operator_message=f"{label}。",
        suggested_action=suggested_action,
    )


def structured_error_payload(error: StructuredError) -> dict[str, object]:
    return {
        "error_code": error.error_code,
        "error_type": error.error_type,
        "phase": error.phase,
        "retryable": error.retryable,
        "unit_id": error.unit_id,
        "details": dict(error.details),
    }


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value
