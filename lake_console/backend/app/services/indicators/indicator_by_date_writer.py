from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_directory_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


INDICATOR_BY_DATE_ROOT = "stk_mins_indicators_by_date"
REQUIRED_INDICATOR_FIELDS = (
    "ts_code",
    "freq",
    "trade_time",
    "params_key",
    "indicator_version",
)


class IndicatorByDateWriter:
    def __init__(self, *, lake_root: Path) -> None:
        self.lake_root = lake_root

    def write_rows(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        indicator: str,
        params_key: str,
        freq: int,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        indicator_key = _validate_path_token(indicator, field_name="indicator")
        params_key_value = _validate_path_token(params_key, field_name="params_key")
        if freq <= 0:
            raise ValueError("freq 必须大于 0。")

        normalized_rows = [_normalize_indicator_row(row, expected_freq=freq, expected_params_key=params_key_value) for row in rows]
        if not normalized_rows:
            raise ValueError("没有可写入的指标行。")

        session = self.start_session(
            indicator=indicator_key,
            params_key=params_key_value,
            freq=freq,
            run_id=run_id,
        )
        session.stage_rows(normalized_rows, part_label="000")
        return session.commit()

    def start_session(
        self,
        *,
        indicator: str,
        params_key: str,
        freq: int,
        run_id: str | None = None,
    ) -> IndicatorByDateWriteSession:
        indicator_key = _validate_path_token(indicator, field_name="indicator")
        params_key_value = _validate_path_token(params_key, field_name="params_key")
        if freq <= 0:
            raise ValueError("freq 必须大于 0。")
        LakeRootService(self.lake_root).require_ready_for_write()
        return IndicatorByDateWriteSession(
            lake_root=self.lake_root,
            indicator=indicator_key,
            params_key=params_key_value,
            freq=freq,
            run_id=run_id or _run_id("indicator-by-date"),
        )


class IndicatorByDateWriteSession:
    def __init__(self, *, lake_root: Path, indicator: str, params_key: str, freq: int, run_id: str) -> None:
        self.lake_root = lake_root
        self.indicator = indicator
        self.params_key = params_key
        self.freq = freq
        self.run_id = run_id
        self.input_rows = 0
        self.written_rows = 0
        self.partition_rows: dict[str, int] = defaultdict(int)

    def stage_rows(self, rows: Iterable[Mapping[str, Any]], *, part_label: str) -> int:
        part_label_value = _validate_path_token(part_label, field_name="part_label")
        normalized_rows = [_normalize_indicator_row(row, expected_freq=self.freq, expected_params_key=self.params_key) for row in rows]
        if not normalized_rows:
            return 0
        rows_by_date = _group_by_trade_date(normalized_rows)
        staged_total = 0
        for trade_date, partition_rows in sorted(rows_by_date.items()):
            tmp_partition = _tmp_indicator_partition(
                lake_root=self.lake_root,
                run_id=self.run_id,
                indicator=self.indicator,
                params_key=self.params_key,
                freq=self.freq,
                trade_date=trade_date,
            )
            tmp_file = tmp_partition / f"part-{part_label_value}.parquet"
            if tmp_file.exists():
                raise RuntimeError(f"指标临时 part 已存在：{tmp_file}")
            sorted_rows = sorted(partition_rows, key=lambda item: (str(item["ts_code"]), item["trade_time"]))
            written = write_rows_to_parquet(sorted_rows, tmp_file)
            validated = read_parquet_row_count(tmp_file)
            if validated != written:
                raise RuntimeError(f"指标分区校验失败：written={written} validated={validated} file={tmp_file}")
            self.partition_rows[trade_date] += written
            self.input_rows += len(partition_rows)
            self.written_rows += written
            staged_total += written
        return staged_total

    def commit(self) -> dict[str, Any]:
        if not self.partition_rows:
            raise ValueError("没有已 stage 的指标分区。")
        partitions: list[dict[str, Any]] = []
        for trade_date, rows in sorted(self.partition_rows.items()):
            tmp_partition = _tmp_indicator_partition(
                lake_root=self.lake_root,
                run_id=self.run_id,
                indicator=self.indicator,
                params_key=self.params_key,
                freq=self.freq,
                trade_date=trade_date,
            )
            final_partition = _indicator_partition(
                lake_root=self.lake_root,
                indicator=self.indicator,
                params_key=self.params_key,
                freq=self.freq,
                trade_date=trade_date,
            )
            replace_directory_atomically(
                tmp_dir=tmp_partition,
                final_dir=final_partition,
                backup_root=self.lake_root / "_tmp" / self.run_id / "_backup",
            )
            partitions.append({"trade_date": trade_date, "rows": rows, "path": str(final_partition)})
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(self.run_id)
        return {
            "operation": "write_indicator_by_date",
            "indicator": self.indicator,
            "params_key": self.params_key,
            "freq": self.freq,
            "run_id": self.run_id,
            "input_rows": self.input_rows,
            "written_rows": self.written_rows,
            "partition_count": len(partitions),
            "partitions": partitions,
        }


def _group_by_trade_date(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        trade_time = row["trade_time"]
        grouped[trade_time.date().isoformat()].append(row)
    return grouped


def _indicator_partition(*, lake_root: Path, indicator: str, params_key: str, freq: int, trade_date: str) -> Path:
    return (
        lake_root
        / "derived"
        / INDICATOR_BY_DATE_ROOT
        / f"indicator={indicator}"
        / f"params_key={params_key}"
        / f"freq={freq}"
        / f"trade_date={trade_date}"
    )


def _tmp_indicator_partition(*, lake_root: Path, run_id: str, indicator: str, params_key: str, freq: int, trade_date: str) -> Path:
    return (
        lake_root
        / "_tmp"
        / run_id
        / "derived"
        / INDICATOR_BY_DATE_ROOT
        / f"indicator={indicator}"
        / f"params_key={params_key}"
        / f"freq={freq}"
        / f"trade_date={trade_date}"
    )


def _normalize_indicator_row(row: Mapping[str, Any], *, expected_freq: int, expected_params_key: str) -> dict[str, Any]:
    normalized = dict(row)
    for field in REQUIRED_INDICATOR_FIELDS:
        if field not in normalized:
            raise ValueError(f"指标行缺少字段：{field}")

    freq = int(normalized["freq"])
    if freq != expected_freq:
        raise ValueError(f"指标行 freq={freq} 与写入目标 freq={expected_freq} 不一致。")
    normalized["freq"] = freq

    params_key = str(normalized["params_key"] or "").strip()
    if params_key != expected_params_key:
        raise ValueError(f"指标行 params_key={params_key} 与写入目标 params_key={expected_params_key} 不一致。")
    normalized["params_key"] = params_key

    ts_code = str(normalized["ts_code"] or "").strip()
    if not ts_code:
        raise ValueError("指标行 ts_code 不能为空。")
    normalized["ts_code"] = ts_code
    normalized["trade_time"] = _parse_trade_time(normalized["trade_time"])
    normalized["indicator_version"] = int(normalized["indicator_version"])
    return normalized


def _parse_trade_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().replace(tzinfo=None)
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("指标行 trade_time 不能为空。")
    try:
        return datetime.fromisoformat(raw_value.replace("T", " "))
    except ValueError as exc:
        raise ValueError(f"指标行 trade_time 格式无效：{raw_value}") from exc


def _validate_path_token(value: str, *, field_name: str) -> str:
    token = str(value or "").strip()
    if not token:
        raise ValueError(f"{field_name} 不能为空。")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if any(char not in allowed for char in token):
        raise ValueError(f"{field_name} 只能包含字母、数字、下划线和短横线。")
    return token


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
