from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from typing import Any, Iterable, Mapping


ETF_BASIC_BUSINESS_FIELDS = (
    "ts_code",
    "csname",
    "extname",
    "cname",
    "index_code",
    "index_name",
    "setup_date",
    "list_date",
    "list_status",
    "exchange",
    "mgr_name",
    "custod_name",
    "mgt_fee",
    "etf_type",
)
ETF_BASIC_LIST_STATUSES = frozenset({"L", "P", "D"})
ETF_BASIC_CODE_SUFFIXES = frozenset({"SH", "SZ", "OF"})
ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT = 20


class EtfBasicSnapshotValidationError(ValueError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class EtfBasicSnapshotSummary:
    row_count: int
    snapshot_hash: str
    status_counts: dict[str, int]
    list_date_null_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class EtfBasicSnapshotDiff:
    added_codes: tuple[str, ...]
    removed_codes: tuple[str, ...]
    changed_codes: tuple[str, ...]
    status_changed_codes: tuple[str, ...]
    list_date_changed_codes: tuple[str, ...]

    def to_diagnostics(self, *, sample_limit: int = ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT) -> dict[str, Any]:
        limit = max(min(int(sample_limit), ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT), 0)
        sample_groups = {
            "added_codes": self.added_codes,
            "removed_codes": self.removed_codes,
            "changed_codes": self.changed_codes,
        }
        return {
            "added_count": len(self.added_codes),
            "removed_count": len(self.removed_codes),
            "changed_count": len(self.changed_codes),
            "status_changed_count": len(self.status_changed_codes),
            "list_date_changed_count": len(self.list_date_changed_codes),
            "added_samples": list(self.added_codes[:limit]),
            "removed_samples": list(self.removed_codes[:limit]),
            "changed_samples": list(self.changed_codes[:limit]),
            "samples_truncated": any(len(codes) > limit for codes in sample_groups.values()),
        }


def extract_etf_basic_business_row(row: Mapping[str, Any] | object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {field_name: row.get(field_name) for field_name in ETF_BASIC_BUSINESS_FIELDS}
    return {field_name: getattr(row, field_name) for field_name in ETF_BASIC_BUSINESS_FIELDS}


def validate_etf_basic_snapshot(
    rows: Iterable[Mapping[str, Any] | object],
    *,
    source_row_count: int,
    normalized_row_count: int,
) -> EtfBasicSnapshotSummary:
    business_rows = [extract_etf_basic_business_row(row) for row in rows]
    if source_row_count != normalized_row_count or normalized_row_count != len(business_rows):
        raise EtfBasicSnapshotValidationError(
            "ETF Basic 源端行数、归一化行数与快照行数不一致",
            details={
                "source_rows": source_row_count,
                "normalized_rows": normalized_row_count,
                "snapshot_rows": len(business_rows),
            },
        )
    if not business_rows:
        raise EtfBasicSnapshotValidationError("ETF Basic 完整快照不得为空")

    seen_codes: set[str] = set()
    status_counts = {status: 0 for status in sorted(ETF_BASIC_LIST_STATUSES)}
    list_date_null_counts = {status: 0 for status in sorted(ETF_BASIC_LIST_STATUSES)}
    for row in business_rows:
        ts_code = str(row.get("ts_code") or "")
        if not ts_code or ts_code in seen_codes:
            raise EtfBasicSnapshotValidationError(
                "ETF Basic 完整快照存在空代码或重复代码",
                details={"ts_code": ts_code or None},
            )
        seen_codes.add(ts_code)

        list_status = str(row.get("list_status") or "")
        if list_status not in ETF_BASIC_LIST_STATUSES:
            raise EtfBasicSnapshotValidationError(
                "ETF Basic 存在未知上市状态",
                details={"ts_code": ts_code, "list_status": list_status or None},
            )
        status_counts[list_status] += 1
        if row.get("list_date") is None:
            list_date_null_counts[list_status] += 1

        suffix = ts_code.rsplit(".", 1)[-1] if "." in ts_code else ""
        if suffix not in ETF_BASIC_CODE_SUFFIXES:
            raise EtfBasicSnapshotValidationError(
                "ETF Basic 存在未知代码后缀",
                details={"ts_code": ts_code, "suffix": suffix or None},
            )
        exchange = row.get("exchange")
        if suffix in {"SH", "SZ"} and exchange != suffix:
            raise EtfBasicSnapshotValidationError(
                "ETF Basic 交易所与代码后缀不一致",
                details={"ts_code": ts_code, "exchange": exchange, "expected_exchange": suffix},
            )

    return EtfBasicSnapshotSummary(
        row_count=len(business_rows),
        snapshot_hash=compute_etf_basic_snapshot_hash(business_rows),
        status_counts=status_counts,
        list_date_null_counts=list_date_null_counts,
    )


def compute_etf_basic_snapshot_hash(rows: Iterable[Mapping[str, Any] | object]) -> str:
    business_rows = [extract_etf_basic_business_row(row) for row in rows]
    canonical_rows = [
        [_canonical_value(row[field_name]) for field_name in ETF_BASIC_BUSINESS_FIELDS]
        for row in sorted(business_rows, key=lambda item: str(item.get("ts_code") or ""))
    ]
    payload = json.dumps(
        canonical_rows,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def diff_etf_basic_snapshots(
    before_rows: Iterable[Mapping[str, Any] | object],
    after_rows: Iterable[Mapping[str, Any] | object],
) -> EtfBasicSnapshotDiff:
    before_by_code = _canonical_rows_by_code(before_rows)
    after_by_code = _canonical_rows_by_code(after_rows)
    before_codes = set(before_by_code)
    after_codes = set(after_by_code)
    shared_codes = before_codes & after_codes
    changed_codes = tuple(
        sorted(code for code in shared_codes if before_by_code[code] != after_by_code[code])
    )
    status_index = ETF_BASIC_BUSINESS_FIELDS.index("list_status")
    list_date_index = ETF_BASIC_BUSINESS_FIELDS.index("list_date")
    return EtfBasicSnapshotDiff(
        added_codes=tuple(sorted(after_codes - before_codes)),
        removed_codes=tuple(sorted(before_codes - after_codes)),
        changed_codes=changed_codes,
        status_changed_codes=tuple(
            sorted(
                code
                for code in shared_codes
                if before_by_code[code][status_index] != after_by_code[code][status_index]
            )
        ),
        list_date_changed_codes=tuple(
            sorted(
                code
                for code in shared_codes
                if before_by_code[code][list_date_index] != after_by_code[code][list_date_index]
            )
        ),
    )


def _canonical_rows_by_code(
    rows: Iterable[Mapping[str, Any] | object],
) -> dict[str, tuple[Any, ...]]:
    result: dict[str, tuple[Any, ...]] = {}
    for source_row in rows:
        row = extract_etf_basic_business_row(source_row)
        ts_code = str(row.get("ts_code") or "")
        if not ts_code or ts_code in result:
            raise EtfBasicSnapshotValidationError(
                "ETF Basic 快照差异计算遇到空代码或重复代码",
                details={"ts_code": ts_code or None},
            )
        result[ts_code] = tuple(_canonical_value(row[field_name]) for field_name in ETF_BASIC_BUSINESS_FIELDS)
    return result


def _canonical_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        raise EtfBasicSnapshotValidationError("ETF Basic 业务字段不接受布尔数值")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (Decimal, float)):
        return _canonical_decimal(value)
    if isinstance(value, str):
        return value
    raise EtfBasicSnapshotValidationError(
        "ETF Basic 业务字段包含不可规范化类型",
        details={"value_type": type(value).__name__},
    )


def _canonical_decimal(value: Decimal | float) -> str:
    if isinstance(value, float) and not math.isfinite(value):
        raise EtfBasicSnapshotValidationError("ETF Basic 数值字段必须为有限数")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EtfBasicSnapshotValidationError("ETF Basic 数值字段无法规范化") from exc
    if not number.is_finite():
        raise EtfBasicSnapshotValidationError("ETF Basic 数值字段必须为有限数")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


__all__ = [
    "ETF_BASIC_BUSINESS_FIELDS",
    "ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT",
    "EtfBasicSnapshotDiff",
    "EtfBasicSnapshotSummary",
    "EtfBasicSnapshotValidationError",
    "compute_etf_basic_snapshot_hash",
    "diff_etf_basic_snapshots",
    "extract_etf_basic_business_row",
    "validate_etf_basic_snapshot",
]
