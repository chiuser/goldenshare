from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isnan
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.index_mins_active_pool_sync_service import (
    INDEX_MINS_ACTIVE_POOL_MANIFEST,
    INDEX_MINS_ACTIVE_POOL_RESOURCE,
)
from lake_console.backend.app.services.parquet_writer import read_parquet_rows


INDEX_BASIC_MANIFEST_PATH = Path("manifest") / "index_universe" / "tushare_index_basic.parquet"


class IndexMinsUniverseError(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexMinsUniverseFilterResult:
    ts_codes: list[str]
    total_candidates: int
    selected_candidates: int
    skipped_listed_after_range: int
    skipped_expired_before_range: int
    effective_windows_by_code: dict[str, tuple[date, date]]

    def is_effective_on(self, *, ts_code: str, trade_date: date) -> bool:
        window = self.effective_windows_by_code.get(ts_code)
        if window is None:
            return False
        start_date, end_date = window
        return start_date <= trade_date <= end_date

    def effective_code_count_on(self, *, trade_date: date) -> int:
        return sum(1 for current_ts_code in self.ts_codes if self.is_effective_on(ts_code=current_ts_code, trade_date=trade_date))

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_candidates": self.total_candidates,
            "selected_candidates": self.selected_candidates,
            "skipped_listed_after_range": self.skipped_listed_after_range,
            "skipped_expired_before_range": self.skipped_expired_before_range,
        }


@dataclass(frozen=True)
class _IndexMinsActivePoolRow:
    resource: str
    ts_code: str


@dataclass(frozen=True)
class _IndexBasicRow:
    ts_code: str
    list_date: date
    exp_date: date | None


def load_index_mins_universe_for_range(
    *,
    lake_root: Path,
    start_date: date,
    end_date: date,
    ts_code: str | None = None,
) -> IndexMinsUniverseFilterResult:
    if end_date < start_date:
        raise ValueError("index_mins universe 过滤区间的 end_date 不能早于 start_date。")

    active_pool_rows = _load_active_pool_rows(lake_root=lake_root)
    active_codes = [row.ts_code for row in active_pool_rows]
    active_set = set(active_codes)
    explicit_ts_code = _normalize_ts_code(ts_code)
    if explicit_ts_code is not None and explicit_ts_code not in active_set:
        raise IndexMinsUniverseError(f"index_mins 调试 ts_code 不在本地 active pool 中：{explicit_ts_code}")

    candidate_codes = [explicit_ts_code] if explicit_ts_code is not None else active_codes
    index_basic_by_code = _load_index_basic_rows(
        lake_root=lake_root,
        required_codes=set(candidate_codes),
    )
    selected_codes: list[str] = []
    effective_windows_by_code: dict[str, tuple[date, date]] = {}
    skipped_listed_after_range = 0
    skipped_expired_before_range = 0

    for current_ts_code in candidate_codes:
        index_basic_row = index_basic_by_code.get(current_ts_code)
        if index_basic_row is None:
            raise IndexMinsUniverseError(f"index_mins active pool code 在本地 index_basic manifest 中不存在：{current_ts_code}")
        if index_basic_row.list_date > end_date:
            skipped_listed_after_range += 1
            continue
        if index_basic_row.exp_date is not None and index_basic_row.exp_date < start_date:
            skipped_expired_before_range += 1
            continue
        effective_start_date = max(start_date, index_basic_row.list_date)
        effective_end_date = min(end_date, index_basic_row.exp_date) if index_basic_row.exp_date is not None else end_date
        if effective_start_date > effective_end_date:
            raise IndexMinsUniverseError(
                f"index_mins 生命周期计算异常：ts_code={current_ts_code} "
                f"effective_start={effective_start_date.isoformat()} effective_end={effective_end_date.isoformat()}"
            )
        selected_codes.append(current_ts_code)
        effective_windows_by_code[current_ts_code] = (effective_start_date, effective_end_date)

    if not selected_codes:
        raise IndexMinsUniverseError(
            "index_mins active pool 按生命周期过滤后没有可同步的指数。"
            f" request_range={start_date.isoformat()}~{end_date.isoformat()}"
        )

    return IndexMinsUniverseFilterResult(
        ts_codes=selected_codes,
        total_candidates=len(candidate_codes),
        selected_candidates=len(selected_codes),
        skipped_listed_after_range=skipped_listed_after_range,
        skipped_expired_before_range=skipped_expired_before_range,
        effective_windows_by_code=effective_windows_by_code,
    )


def _load_active_pool_rows(*, lake_root: Path) -> list[_IndexMinsActivePoolRow]:
    active_pool_file = lake_root / INDEX_MINS_ACTIVE_POOL_MANIFEST
    if not active_pool_file.exists():
        raise IndexMinsUniverseError(
            "缺少本地 active pool manifest/index_universe/index_mins_active_pool.parquet。"
            "请先执行 sync-index-mins-active-pool。"
        )
    raw_rows = read_parquet_rows(active_pool_file)
    if not raw_rows:
        raise IndexMinsUniverseError("本地 index_mins active pool 为空，请先重新执行 sync-index-mins-active-pool。")

    rows: list[_IndexMinsActivePoolRow] = []
    seen_codes: set[str] = set()
    for index, raw_row in enumerate(raw_rows, start=1):
        resource = _required_text(raw_row.get("resource"), field="resource", row_index=index)
        if resource != INDEX_MINS_ACTIVE_POOL_RESOURCE:
            raise IndexMinsUniverseError(
                f"index_mins active pool resource 非法：row={index} resource={resource!r}"
            )
        ts_code = _required_text(raw_row.get("ts_code"), field="ts_code", row_index=index).upper()
        if ts_code in seen_codes:
            raise IndexMinsUniverseError(f"index_mins active pool ts_code 重复：{ts_code}")
        seen_codes.add(ts_code)
        rows.append(_IndexMinsActivePoolRow(resource=resource, ts_code=ts_code))
    return rows


def _load_index_basic_rows(*, lake_root: Path, required_codes: set[str]) -> dict[str, _IndexBasicRow]:
    index_basic_file = lake_root / INDEX_BASIC_MANIFEST_PATH
    if not index_basic_file.exists():
        raise IndexMinsUniverseError(
            "缺少本地 index_basic manifest/index_universe/tushare_index_basic.parquet。"
            "请先执行 sync-dataset index_basic。"
        )
    raw_rows = read_parquet_rows(index_basic_file)
    if not raw_rows:
        raise IndexMinsUniverseError("本地 index_basic manifest 为空，请先重新执行 sync-dataset index_basic。")

    rows_by_code: dict[str, _IndexBasicRow] = {}
    for index, raw_row in enumerate(raw_rows, start=1):
        ts_code = _required_text(raw_row.get("ts_code"), field="ts_code", row_index=index).upper()
        if ts_code not in required_codes:
            continue
        if ts_code in rows_by_code:
            raise IndexMinsUniverseError(f"本地 index_basic manifest ts_code 重复：{ts_code}")
        list_date = _required_date(raw_row.get("list_date"), field="list_date", ts_code=ts_code)
        exp_date = _optional_date(raw_row.get("exp_date"), field="exp_date", ts_code=ts_code)
        if exp_date is not None and exp_date < list_date:
            raise IndexMinsUniverseError(
                f"本地 index_basic manifest exp_date 早于 list_date：ts_code={ts_code} "
                f"list_date={list_date.isoformat()} exp_date={exp_date.isoformat()}"
        )
        rows_by_code[ts_code] = _IndexBasicRow(ts_code=ts_code, list_date=list_date, exp_date=exp_date)
    missing_codes = sorted(required_codes - set(rows_by_code))
    if missing_codes:
        missing_preview = ",".join(missing_codes[:5])
        suffix = "..." if len(missing_codes) > 5 else ""
        raise IndexMinsUniverseError(
            "index_mins active pool code 在本地 index_basic manifest 中不存在："
            f"{missing_preview}{suffix}"
        )
    return rows_by_code


def _normalize_ts_code(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().upper()
    return text or None


def _required_text(value: Any, *, field: str, row_index: int) -> str:
    text = _text_or_none(value)
    if text is None:
        raise IndexMinsUniverseError(f"index_mins manifest {field} 为空：row={row_index}")
    return text


def _required_date(value: Any, *, field: str, ts_code: str) -> date:
    parsed = _parse_date_or_none(value)
    if parsed is None:
        raise IndexMinsUniverseError(f"index_mins manifest {field} 为空或不可解析：ts_code={ts_code} value={value!r}")
    return parsed


def _optional_date(value: Any, *, field: str, ts_code: str) -> date | None:
    try:
        return _parse_date_or_none(value)
    except ValueError as exc:
        raise IndexMinsUniverseError(f"index_mins manifest {field} 不可解析：ts_code={ts_code} value={value!r}") from exc


def _parse_date_or_none(value: Any) -> date | None:
    if _is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return date.fromisoformat(text)
    raise ValueError(f"unsupported date format: {text}")


def _text_or_none(value: Any) -> str | None:
    if _is_blank(value):
        return None
    text = str(value).strip()
    return text or None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and isnan(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "nat", "none", "null"}
