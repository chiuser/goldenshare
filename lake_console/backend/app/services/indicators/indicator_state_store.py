from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.indicators.macd_spec import DEFAULT_MACD_PARAMS
from lake_console.backend.app.services.indicators.models import MacdParams, MacdState
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    read_parquet_rows,
    replace_file_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


STATE_VERSION = 1
STATE_REQUIRED_FIELDS = (
    "indicator_key",
    "params_key",
    "source_dataset_key",
    "freq",
    "ts_code",
    "last_trade_time",
    "ema_fast",
    "ema_slow",
    "dea",
    "source_node_key",
    "source_watermark",
    "state_version",
    "updated_at",
)


class MacdStateStore:
    def __init__(self, *, lake_root: Path) -> None:
        self.lake_root = lake_root

    def state_file(self, *, params: MacdParams = DEFAULT_MACD_PARAMS) -> Path:
        return self.lake_root / "manifest" / "indicator_state" / "stk_mins_macd" / f"params_key={params.params_key}" / "state.parquet"

    def load_states(self, *, params: MacdParams = DEFAULT_MACD_PARAMS) -> dict[tuple[str, int], MacdState]:
        state_file = self.state_file(params=params)
        if not state_file.exists():
            return {}
        rows = read_parquet_rows(state_file)
        states: dict[tuple[str, int], MacdState] = {}
        for row in rows:
            state = _state_from_row(row, params=params)
            key = (state.ts_code, state.freq)
            if key in states:
                raise ValueError(f"MACD state 存在重复 key：ts_code={state.ts_code} freq={state.freq}")
            states[key] = state
        return states

    def get_state(self, *, ts_code: str, freq: int, params: MacdParams = DEFAULT_MACD_PARAMS) -> MacdState | None:
        return self.load_states(params=params).get((ts_code, int(freq)))

    def needs_bootstrap(self, *, ts_code: str, freq: int, params: MacdParams = DEFAULT_MACD_PARAMS) -> bool:
        return self.get_state(ts_code=ts_code, freq=freq, params=params) is None

    def replace_states_after_result_write(
        self,
        states: Iterable[MacdState],
        *,
        result_summary: Mapping[str, Any],
        params: MacdParams = DEFAULT_MACD_PARAMS,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        _validate_result_summary(result_summary)
        normalized_states = _normalize_states(states)
        if not normalized_states:
            raise ValueError("没有可写入的 MACD state。")

        LakeRootService(self.lake_root).require_ready_for_write()
        run_id_value = run_id or _run_id("indicator-state")
        state_file = self.state_file(params=params)
        tmp_file = self.lake_root / "_tmp" / run_id_value / "manifest" / "indicator_state" / "stk_mins_macd" / f"params_key={params.params_key}" / "state.parquet"
        rows = [_state_to_row(state, params=params) for state in normalized_states]
        written = write_rows_to_parquet(rows, tmp_file)
        validated = read_parquet_row_count(tmp_file)
        if validated != written:
            raise RuntimeError(f"MACD state 校验失败：written={written} validated={validated} file={tmp_file}")
        replace_file_atomically(
            tmp_file=tmp_file,
            final_file=state_file,
            backup_root=self.lake_root / "_tmp" / run_id_value / "_backup",
        )
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id_value)
        return {
            "operation": "replace_macd_state",
            "indicator": "macd",
            "params_key": params.params_key,
            "run_id": run_id_value,
            "state_count": written,
            "state_file": str(state_file),
            "result_run_id": result_summary.get("run_id"),
        }


def _normalize_states(states: Iterable[MacdState]) -> list[MacdState]:
    normalized = list(states)
    seen: set[tuple[str, int]] = set()
    for state in normalized:
        if not state.ts_code.strip():
            raise ValueError("MACD state ts_code 不能为空。")
        if state.freq <= 0:
            raise ValueError("MACD state freq 必须大于 0。")
        key = (state.ts_code, state.freq)
        if key in seen:
            raise ValueError(f"MACD state 存在重复 key：ts_code={state.ts_code} freq={state.freq}")
        seen.add(key)
    return sorted(normalized, key=lambda item: (item.freq, item.ts_code))


def _state_to_row(state: MacdState, *, params: MacdParams) -> dict[str, Any]:
    source_node_key = "clean_next_by_date" if state.freq in {1, 5, 15, 30, 60} else "derived_by_date"
    return {
        "indicator_key": "macd",
        "params_key": params.params_key,
        "source_dataset_key": "stk_mins",
        "freq": int(state.freq),
        "ts_code": state.ts_code,
        "last_trade_time": state.last_trade_time.replace(tzinfo=None),
        "ema_fast": float(state.ema_fast),
        "ema_slow": float(state.ema_slow),
        "dea": float(state.dea),
        "source_node_key": source_node_key,
        "source_watermark": state.last_trade_time.replace(tzinfo=None),
        "state_version": STATE_VERSION,
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }


def _state_from_row(row: Mapping[str, Any], *, params: MacdParams) -> MacdState:
    for field in STATE_REQUIRED_FIELDS:
        if field not in row:
            raise ValueError(f"MACD state 缺少字段：{field}")
    indicator_key = str(row["indicator_key"] or "").strip()
    params_key = str(row["params_key"] or "").strip()
    source_dataset_key = str(row["source_dataset_key"] or "").strip()
    if indicator_key != "macd":
        raise ValueError(f"MACD state indicator_key 无效：{indicator_key}")
    if params_key != params.params_key:
        raise ValueError(f"MACD state params_key 无效：{params_key}")
    if source_dataset_key != "stk_mins":
        raise ValueError(f"MACD state source_dataset_key 无效：{source_dataset_key}")
    if int(row["state_version"]) != STATE_VERSION:
        raise ValueError(f"MACD state_version 无效：{row['state_version']}")
    return MacdState(
        ts_code=str(row["ts_code"] or "").strip(),
        freq=int(row["freq"]),
        last_trade_time=_parse_datetime(row["last_trade_time"], field_name="last_trade_time"),
        ema_fast=float(row["ema_fast"]),
        ema_slow=float(row["ema_slow"]),
        dea=float(row["dea"]),
    )


def _validate_result_summary(summary: Mapping[str, Any]) -> None:
    if summary.get("operation") != "write_indicator_by_date":
        raise ValueError("MACD state 只能在指标 by_date 写入成功后前进。")
    if summary.get("indicator") != "macd":
        raise ValueError("MACD state 只能跟随 macd 指标结果前进。")
    if int(summary.get("written_rows") or 0) <= 0:
        raise ValueError("MACD state 不能跟随空写入结果前进。")
    if int(summary.get("partition_count") or 0) <= 0:
        raise ValueError("MACD state 不能跟随空分区结果前进。")


def _parse_datetime(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().replace(tzinfo=None)
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError(f"MACD state {field_name} 不能为空。")
    try:
        return datetime.fromisoformat(raw_value.replace("T", " "))
    except ValueError as exc:
        raise ValueError(f"MACD state {field_name} 格式无效：{raw_value}") from exc


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
