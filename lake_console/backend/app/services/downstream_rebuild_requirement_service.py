from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DOWNSTREAM_REBUILD_REQUIREMENT_SCHEMA_VERSION = 1
DOWNSTREAM_REBUILD_REQUIREMENT_RELATIVE_PATH = Path("manifest") / "downstream_rebuild_requirements" / "stk_mins.parquet"
DOWNSTREAM_REBUILD_REQUIREMENT_FIELDS = (
    "requirement_schema_version",
    "requirement_id",
    "source_layer",
    "source_publish_id",
    "target_layer",
    "target_task",
    "scope_type",
    "freqs",
    "start_date",
    "end_date",
    "status",
    "reason_code",
    "human_message",
    "created_at",
    "updated_at",
    "finished_at",
    "error_message",
)


class DownstreamRebuildRequirementService:
    """Build downstream rebuild requirement rows.

    M3-C-A only plans these rows. Formal publishing will be responsible for
    writing them before the final clean_next gate is marked passed.
    """

    def __init__(self, *, lake_root: Path) -> None:
        self.lake_root = lake_root

    @property
    def requirement_file(self) -> Path:
        return self.lake_root / DOWNSTREAM_REBUILD_REQUIREMENT_RELATIVE_PATH

    def build_stk_mins_qfq_requirements(
        self,
        *,
        source_publish_id: str,
        publish_partitions: list[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        scope = _scope_from_publish_partitions(publish_partitions)
        raw_freqs = scope["freqs"]
        derived_freqs = _derived_target_freqs(raw_freqs)
        affected_freqs = sorted(set(raw_freqs) | set(derived_freqs))

        requirements: list[dict[str, Any]] = []
        if derived_freqs:
            requirements.append(
                self._requirement(
                    source_publish_id=source_publish_id,
                    target_layer="derived/stk_mins_by_date",
                    target_task="rebuild_90_120_from_clean_next",
                    freqs=derived_freqs,
                    start_date=scope["start_date"],
                    end_date=scope["end_date"],
                    reason_code="qfq_clean_next_published",
                    human_message=(
                        "clean_next 前复权基准发布后，30/60 分钟源数据对应的 90/120 分钟派生层需要重建。"
                    ),
                )
            )
        requirements.append(
            self._requirement(
                source_publish_id=source_publish_id,
                target_layer="research/stk_mins_by_symbol_month",
                target_task="rebuild_by_month_from_clean_next_and_derived",
                freqs=affected_freqs,
                start_date=scope["start_date"],
                end_date=scope["end_date"],
                reason_code="qfq_clean_next_published",
                human_message="clean_next 前复权基准发布后，按股票月份重排的 research 层需要按受影响频率重建。",
            )
        )
        requirements.append(
            self._requirement(
                source_publish_id=source_publish_id,
                target_layer="indicator/*",
                target_task="review_and_recompute_after_qfq",
                freqs=affected_freqs,
                start_date=scope["start_date"],
                end_date=scope["end_date"],
                reason_code="qfq_clean_next_published",
                human_message="clean_next 前复权基准发布后，分钟级技术指标需要重新评估并按受影响频率重算。",
            )
        )
        return requirements

    def _requirement(
        self,
        *,
        source_publish_id: str,
        target_layer: str,
        target_task: str,
        freqs: list[int],
        start_date: date,
        end_date: date,
        reason_code: str,
        human_message: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        source_layer = "research/stk_mins_by_date_clean_next"
        scope_type = "date_range"
        freqs_text = ",".join(str(freq) for freq in sorted(freqs))
        requirement_id = _requirement_id(
            source_layer=source_layer,
            source_publish_id=source_publish_id,
            target_layer=target_layer,
            target_task=target_task,
            scope_type=scope_type,
            freqs=freqs_text,
            start_date=start_date,
            end_date=end_date,
        )
        return {
            "requirement_schema_version": DOWNSTREAM_REBUILD_REQUIREMENT_SCHEMA_VERSION,
            "requirement_id": requirement_id,
            "source_layer": source_layer,
            "source_publish_id": source_publish_id,
            "target_layer": target_layer,
            "target_task": target_task,
            "scope_type": scope_type,
            "freqs": freqs_text,
            "start_date": start_date,
            "end_date": end_date,
            "status": "pending",
            "reason_code": reason_code,
            "human_message": human_message,
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "error_message": None,
        }


def _scope_from_publish_partitions(publish_partitions: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not publish_partitions:
        raise ValueError("publish_partitions 为空，不能生成 downstream rebuild requirement。")
    parsed = [_parse_partition_key(str(row.get("partition_key") or "")) for row in publish_partitions]
    return {
        "freqs": sorted({item["freq"] for item in parsed}),
        "start_date": min(item["trade_date"] for item in parsed),
        "end_date": max(item["trade_date"] for item in parsed),
    }


def _parse_partition_key(partition_key: str) -> dict[str, Any]:
    parts = {}
    for item in partition_key.split("/"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts[key] = value
    try:
        freq = int(parts["freq"])
        trade_date = date.fromisoformat(parts["trade_date"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"publish partition_key 格式非法：{partition_key}") from exc
    return {"freq": freq, "trade_date": trade_date}


def _derived_target_freqs(raw_freqs: list[int]) -> list[int]:
    result: list[int] = []
    if 30 in raw_freqs:
        result.append(90)
    if 60 in raw_freqs:
        result.append(120)
    return result


def _requirement_id(
    *,
    source_layer: str,
    source_publish_id: str,
    target_layer: str,
    target_task: str,
    scope_type: str,
    freqs: str,
    start_date: date,
    end_date: date,
) -> str:
    payload = {
        "source_layer": source_layer,
        "source_publish_id": source_publish_id,
        "target_layer": target_layer,
        "target_task": target_task,
        "scope_type": scope_type,
        "freqs": freqs,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"dsr_{digest[:24]}"
