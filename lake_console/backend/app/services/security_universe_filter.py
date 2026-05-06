from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isnan
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.parquet_writer import read_parquet_rows

SECURITY_UNIVERSE_PATH = Path("manifest") / "security_universe" / "tushare_stock_basic.parquet"
VALID_LIST_STATUSES = {"L", "D", "P"}


class SecurityUniverseError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecurityUniverseFilterResult:
    ts_codes: list[str]
    total_symbols: int
    selected_symbols: int
    skipped_listed_after_range: int
    skipped_delisted_before_range: int
    selected_listed_symbols: int
    selected_delisted_or_paused_symbols: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_symbols": self.total_symbols,
            "selected_symbols": self.selected_symbols,
            "skipped_listed_after_range": self.skipped_listed_after_range,
            "skipped_delisted_before_range": self.skipped_delisted_before_range,
            "selected_listed_symbols": self.selected_listed_symbols,
            "selected_delisted_or_paused_symbols": self.selected_delisted_or_paused_symbols,
        }


@dataclass(frozen=True)
class _SecurityUniverseRow:
    ts_code: str
    list_status: str
    list_date: date
    delist_date: date | None


def load_security_universe_for_range(
    *,
    lake_root: Path,
    start_date: date,
    end_date: date,
) -> SecurityUniverseFilterResult:
    if end_date < start_date:
        raise ValueError("股票池过滤区间的 end_date 不能早于 start_date。")

    rows = _load_security_universe_rows(lake_root=lake_root)
    selected: list[_SecurityUniverseRow] = []
    skipped_listed_after_range = 0
    skipped_delisted_before_range = 0
    for row in rows:
        if row.list_date > end_date:
            skipped_listed_after_range += 1
            continue
        if row.delist_date is not None and row.delist_date < start_date:
            skipped_delisted_before_range += 1
            continue
        selected.append(row)

    ts_codes = sorted(row.ts_code for row in selected)
    if not ts_codes:
        raise SecurityUniverseError(
            "本地股票池按生命周期过滤后没有可请求的 ts_code。"
            f" request_range={start_date.isoformat()}~{end_date.isoformat()}"
        )

    return SecurityUniverseFilterResult(
        ts_codes=ts_codes,
        total_symbols=len(rows),
        selected_symbols=len(selected),
        skipped_listed_after_range=skipped_listed_after_range,
        skipped_delisted_before_range=skipped_delisted_before_range,
        selected_listed_symbols=sum(1 for row in selected if row.list_status == "L"),
        selected_delisted_or_paused_symbols=sum(1 for row in selected if row.list_status in {"D", "P"}),
    )


def _load_security_universe_rows(*, lake_root: Path) -> list[_SecurityUniverseRow]:
    universe_file = lake_root / SECURITY_UNIVERSE_PATH
    if not universe_file.exists():
        raise SecurityUniverseError(
            "缺少本地股票池 manifest/security_universe/tushare_stock_basic.parquet。"
            "请先执行 sync-stock-basic。"
        )

    raw_rows = read_parquet_rows(universe_file)
    if not raw_rows:
        raise SecurityUniverseError("本地股票池为空，请先重新执行 sync-stock-basic。")

    seen_codes: set[str] = set()
    rows: list[_SecurityUniverseRow] = []
    for index, raw_row in enumerate(raw_rows, start=1):
        ts_code = _required_text(raw_row.get("ts_code"), field="ts_code", row_index=index)
        if ts_code in seen_codes:
            raise SecurityUniverseError(f"本地股票池 ts_code 重复：{ts_code}")
        seen_codes.add(ts_code)

        list_status = _required_text(raw_row.get("list_status"), field="list_status", row_index=index)
        if list_status not in VALID_LIST_STATUSES:
            allowed = ", ".join(sorted(VALID_LIST_STATUSES))
            raise SecurityUniverseError(f"本地股票池 list_status 非法：ts_code={ts_code} list_status={list_status} allowed={allowed}")

        list_date = _required_date(raw_row.get("list_date"), field="list_date", ts_code=ts_code)
        delist_date = _optional_date(raw_row.get("delist_date"), field="delist_date", ts_code=ts_code)

        if list_status == "L" and delist_date is not None:
            raise SecurityUniverseError(f"本地股票池 list_status=L 但 delist_date 非空：ts_code={ts_code}")
        if list_status in {"D", "P"} and delist_date is None:
            raise SecurityUniverseError(f"本地股票池 list_status={list_status} 但 delist_date 为空：ts_code={ts_code}")
        if delist_date is not None and list_date > delist_date:
            raise SecurityUniverseError(
                f"本地股票池 list_date 晚于 delist_date：ts_code={ts_code} "
                f"list_date={list_date.isoformat()} delist_date={delist_date.isoformat()}"
            )

        rows.append(
            _SecurityUniverseRow(
                ts_code=ts_code,
                list_status=list_status,
                list_date=list_date,
                delist_date=delist_date,
            )
        )
    return rows


def _required_text(value: Any, *, field: str, row_index: int) -> str:
    text = _text_or_none(value)
    if text is None:
        raise SecurityUniverseError(f"本地股票池 {field} 为空：row={row_index}")
    return text


def _required_date(value: Any, *, field: str, ts_code: str) -> date:
    parsed = _parse_date_or_none(value)
    if parsed is None:
        raise SecurityUniverseError(f"本地股票池 {field} 为空或不可解析：ts_code={ts_code} value={value!r}")
    return parsed


def _optional_date(value: Any, *, field: str, ts_code: str) -> date | None:
    try:
        return _parse_date_or_none(value)
    except ValueError as exc:
        raise SecurityUniverseError(f"本地股票池 {field} 不可解析：ts_code={ts_code} value={value!r}") from exc


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
