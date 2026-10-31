"""Versioned, bounded contracts for delivery of adjusted weekly source rows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

DATASET_KEY = "stk_period_bar_adj_week"
DELIVERY_TABLE = "core.stock_weekly_adj_delivery"
DELIVERY_DAO = "stock_weekly_adj_delivery"
WRITE_PATH = "raw_core_upsert_with_delivery"
UNIT_BUILDER = "stock_weekly_adj_refresh"
CONTRACT_VERSION = 1
# Internal working set, independent of source pages and the durable unit boundary.
SOURCE_ROW_BLOCK_SIZE = 128
SOURCE_FIELDS = (
    "ts_code",
    "trade_date",
    "end_date",
    "freq",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "open_qfq",
    "high_qfq",
    "low_qfq",
    "close_qfq",
    "open_hfq",
    "high_hfq",
    "low_hfq",
    "close_hfq",
    "vol",
    "amount",
    "change",
    "pct_chg",
)


class WeeklyAdjContractError(ValueError):
    def __init__(
        self, message: str, code: str = "weekly_adj.delivery_contract_mismatch"
    ):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class WeeklyAdjExecutionPolicy:
    contract_version: int = 1
    max_pages: int = 3
    max_rows_per_unit: int = 12_000
    max_units: int = 1000
    max_payload_bytes: int = 8 * 1024 * 1024
    max_plan_bytes: int = 1024 * 1024
    max_batch_payload_bytes: int = 256 * 1024 * 1024
    source_timeout_seconds: int = 20
    cancel_poll_seconds: int = 2
    progress_interval_seconds: int = 5
    db_statement_timeout_seconds: int = 20
    lock_timeout_seconds: int = 2
    observation_timeout_seconds: int = 2
    memory_target_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise WeeklyAdjContractError("未知周线交接版本")
        if any(type(value) is not int or value < 1 for value in asdict(self).values()):
            raise WeeklyAdjContractError("周线预算必须为正整数")
        if (
            self.max_payload_bytes > 8 * 1024 * 1024
            or self.max_plan_bytes > 1024 * 1024
            or self.max_units > 1000
        ):
            raise WeeklyAdjContractError("周线预算超过v1持久化合同上限")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    result = hashlib.sha256()
    for chunk in _canonical_chunks(value):
        result.update(chunk.encode())
    return result.hexdigest()


def _canonical_chunks(value: Any):
    return json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).iterencode(value)


def canonical_json_size(value: Any) -> int:
    """Count the exact canonical UTF-8 bytes without a complete string/bytes pair."""
    return sum(len(chunk.encode()) for chunk in _canonical_chunks(value))


def latest_completed_calendar_week(scheduled_at: datetime) -> date:
    """Latest Friday whose 19:30 Shanghai update window has begun."""
    if scheduled_at.tzinfo is None:
        raise WeeklyAdjContractError("计划触发时间必须含时区")
    local = scheduled_at.astimezone(ZoneInfo("Asia/Shanghai"))
    days_back = (local.weekday() - 4) % 7
    if days_back == 0 and (local.hour, local.minute) < (19, 30):
        days_back = 7
    return local.date() - timedelta(days=days_back)


def _source_date(value: date | str | None, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    if isinstance(value, datetime):
        raise WeeklyAdjContractError("行情日期不能包含时间")
    if type(value) is date:
        return value.strftime("%Y%m%d")
    if isinstance(value, str) and len(value) == 8:
        try:
            parsed = date(int(value[:4]), int(value[4:6]), int(value[6:]))
            if parsed.strftime("%Y%m%d") == value:
                return value
        except ValueError:
            pass
    raise WeeklyAdjContractError("行情日期必须为date或YYYYMMDD")


def canonical_source_rows(
    rows: list[dict[str, Any]], policy: WeeklyAdjExecutionPolicy
) -> list[dict[str, Any]]:
    if len(rows) > policy.max_rows_per_unit:
        raise WeeklyAdjContractError(
            "本单元行数超过预算", "weekly_adj.row_budget_exceeded"
        )
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict) or set(raw) != set(SOURCE_FIELDS):
            raise WeeklyAdjContractError("交付必须且只能包含21个源字段")
        code = raw["ts_code"]
        if (
            not isinstance(code, str)
            or not code.strip()
            or len(code) > 16
            or raw["freq"] != "week"
        ):
            raise WeeklyAdjContractError("代码或频率不符合Raw周线合同")
        row = {name: raw[name] for name in SOURCE_FIELDS}
        row["trade_date"] = _source_date(raw["trade_date"], nullable=False)
        row["end_date"] = _source_date(raw["end_date"], nullable=True)
        for name in SOURCE_FIELDS[4:]:
            value = raw[name]
            if value is None:
                continue
            if isinstance(value, (float, bool)) or not isinstance(
                value, (str, int, Decimal)
            ):
                raise WeeklyAdjContractError(
                    "交付数值必须来自数据库Decimal，不能经float转换"
                )
            try:
                number = Decimal(value)
                precision = (
                    10 if name == "pct_chg" else 20 if name in {"vol", "amount"} else 18
                )
                rounded = number.quantize(Decimal("0.0001"))
                if (
                    not number.is_finite()
                    or number != rounded
                    or abs(number) >= Decimal(10) ** (precision - 4)
                ):
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                raise WeeklyAdjContractError("数值非有限或超出数据库精度") from None
            row[name] = format(Decimal(0) if rounded == 0 else rounded, ".4f")
        key = (code, row["trade_date"], "week")
        if key in unique and unique[key] != row:
            raise WeeklyAdjContractError(
                "同单元同键源值冲突", "weekly_adj.source_key_conflict"
            )
        unique[key] = row
    result = [unique[key] for key in sorted(unique)]
    if canonical_json_size({"rows": result}) > policy.max_payload_bytes:
        raise WeeklyAdjContractError(
            "本单元载荷超过预算", "weekly_adj.row_budget_exceeded"
        )
    return result


def validate_weekly_response(
    envelope: dict[str, Any], fields: tuple[str, ...] = SOURCE_FIELDS
) -> list[dict[str, Any]]:
    """Validate the original envelope before converting it to rows, including empty pages."""
    if not isinstance(envelope, dict):
        raise WeeklyAdjContractError(
            "周线响应必须为对象", "weekly_adj.source_payload_invalid"
        )
    data = envelope.get("data")
    if (
        type(envelope.get("code")) is not int
        or envelope["code"] != 0
        or not isinstance(data, dict)
    ):
        raise WeeklyAdjContractError(
            "周线响应没有有效数据对象", "weekly_adj.source_payload_invalid"
        )
    returned = data.get("fields")
    items = data.get("items")
    if (
        not isinstance(returned, list)
        or any(not isinstance(f, str) for f in returned)
        or len(returned) != len(fields)
        or set(returned) != set(fields)
        or not isinstance(items, list)
    ):
        raise WeeklyAdjContractError(
            "周线响应字段不完整或重复", "weekly_adj.source_payload_invalid"
        )
    if any(not isinstance(row, list) or len(row) != len(returned) for row in items):
        raise WeeklyAdjContractError(
            "周线响应行结构错误", "weekly_adj.source_payload_invalid"
        )
    return [dict(zip(returned, row, strict=True)) for row in items]


def weekly_definition_issues(definition) -> list[tuple[str, str]]:
    """Validate the complete named binding; other datasets keep the None default."""
    policy = definition.planning.weekly_adj_policy
    storage = definition.storage
    if policy is None:
        if (
            storage.delivery_dao_name
            or storage.delivery_table
            or storage.write_path == WRITE_PATH
            or definition.planning.unit_builder_key == UNIT_BUILDER
        ):
            return [("weekly_adj_binding_invalid", "周线交接绑定必须同时声明具名预算")]
        return []
    valid = (
        definition.dataset_key == DATASET_KEY
        and definition.source.api_name == "stk_week_month_adj"
        and definition.source.adapter_key
        == definition.source.source_key_default
        == "tushare"
        and definition.source.source_keys == ("tushare",)
        and definition.source.request_builder_key == "_stk_period_bar_adj_week_params"
        and definition.source.base_params in ({}, {"freq": "week"})
        and definition.source.source_fields == SOURCE_FIELDS
        and storage.write_path == WRITE_PATH
        and storage.delivery_dao_name == DELIVERY_DAO
        and storage.delivery_table == DELIVERY_TABLE
        and storage.row_identity_filters == {"freq": "week"}
        and storage.raw_table == "raw_tushare.stk_period_bar_adj"
        and storage.raw_dao_name == "raw_stk_period_bar_adj"
        and storage.core_dao_name == "stk_period_bar_adj"
        and storage.delivery_mode == "single_source_serving"
        and storage.layer_plan == "raw->serving"
        and storage.std_table is None
        and all(
            value is None
            for value in (
                storage.observation_dao_name,
                storage.observation_table,
                storage.stage_dao_name,
                storage.stage_table,
            )
        )
        and storage.serving_table
        == storage.target_table
        == "core_serving.stk_period_bar_adj"
        and storage.raw_conflict_columns
        == storage.conflict_columns
        == ("ts_code", "trade_date", "freq")
        and definition.planning.unit_builder_key == UNIT_BUILDER
        and definition.planning.page_limit == 6000
        and definition.planning.pagination_policy == "offset_limit"
        and definition.planning.max_source_rows_per_unit == policy.max_rows_per_unit
        and definition.planning.max_units_per_execution == policy.max_units
        and definition.planning.fetch_concurrency == 1
        and definition.planning.page_processing_mode == "buffer_all"
        and definition.planning.announcement_policy is None
        and definition.transaction.commit_policy == "unit"
        and definition.transaction.idempotent_write_required is True
        and definition.quality.reject_policy == "fail_unit_on_any_rejection"
    )
    return (
        []
        if valid
        else [
            (
                "weekly_adj_binding_invalid",
                "复权周线供数、频率、写入、规划和预算必须一致",
            )
        ]
    )


def validate_correction_plan(plan, policy):
    """Pure format validation. Database binding is checked separately on every use."""
    fields = {
        "correction_version",
        "batch_id",
        "cutoff_week",
        "original_plan_revision",
        "original_plan_digest",
        "scope_digest",
        "contract_digest",
        "unit_ids_digest",
        "source_task_run_id",
        "units",
        "committed_units",
        "target_checks",
        "changes",
        "source_evidence",
    }
    try:
        if (
            not isinstance(plan, dict)
            or set(plan) != fields
            or type(plan["correction_version"]) is not int
            or plan["correction_version"] != 1
        ):
            raise ValueError
        UUID(plan["batch_id"])
        date.fromisoformat(plan["cutoff_week"])
        if any(
            type(plan[k]) is not int or plan[k] < 1
            for k in ("original_plan_revision", "source_task_run_id")
        ):
            raise ValueError
        for name in (
            "original_plan_digest",
            "scope_digest",
            "contract_digest",
            "unit_ids_digest",
        ):
            if (
                not isinstance(plan[name], str)
                or len(plan[name]) != 64
                or any(c not in "0123456789abcdef" for c in plan[name])
            ):
                raise ValueError
        units, headers, checks, changes = (
            plan[k] for k in ("units", "committed_units", "target_checks", "changes")
        )
        if (
            any(
                not isinstance(v, list) or len(v) > policy.max_units
                for v in (units, headers, checks)
            )
            or not isinstance(changes, list)
            or len(changes) != 1
        ):
            raise ValueError
        ids = [u["unit_id"] for u in units]
        if len(set(ids)) != len(ids) or plan["unit_ids_digest"] != digest(ids):
            raise ValueError
        for h in headers:
            if (
                set(h) != {"revision", "unit_id", "payload_digest", "rows_written"}
                or h["unit_id"] not in ids
                or type(h["revision"]) is not int
                or h["revision"] < 1
                or type(h["rows_written"]) is not int
                or h["rows_written"] < 0
                or len(h["payload_digest"]) != 64
            ):
                raise ValueError
        if len({h["unit_id"] for h in headers}) != len(headers):
            raise ValueError
        for c in checks:
            if (
                set(c)
                != {
                    "unit_id",
                    "ts_code",
                    "old_factor_target",
                    "new_factor_target",
                    "factor_target_date",
                }
                or c["unit_id"] not in ids
            ):
                raise ValueError
            if date.fromisoformat(c["factor_target_date"]) > date.fromisoformat(
                plan["cutoff_week"]
            ):
                raise ValueError
            for name in ("old_factor_target", "new_factor_target"):
                value = Decimal(c[name])
                if (
                    not value.is_finite()
                    or value <= 0
                    or format(value, ".8f") != c[name]
                ):
                    raise ValueError
        expected_targets = {
            u["unit_id"]: u
            for u in units
            if u["progress"].get("factor_target") is not None
        }
        if {c["unit_id"] for c in checks} != set(expected_targets):
            raise ValueError
        for c in checks:
            u = expected_targets[c["unit_id"]]
            if (
                c["ts_code"] != u["params"]["ts_code"]
                or c["old_factor_target"] != u["progress"]["factor_target"]
            ):
                raise ValueError
        if len({c["unit_id"] for c in checks}) != len(checks) or changes != [
            c for c in checks if c["old_factor_target"] != c["new_factor_target"]
        ]:
            raise ValueError
        if canonical_json_size(plan) + 2048 > policy.max_plan_bytes:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
        raise WeeklyAdjContractError("更正审核清单格式、单位或预算不符合合同") from None


def validate_correction_payload(payload, policy):
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "correction_version",
            "approved_plan",
            "approved_plan_digest",
            "approval_ref",
        }
        or type(payload["correction_version"]) is not int
        or payload["correction_version"] != 1
        or not isinstance(payload["approval_ref"], str)
        or not 1 <= len(payload["approval_ref"]) <= 200
    ):
        raise WeeklyAdjContractError("更正记录缺少有效批准内容")
    validate_correction_plan(payload["approved_plan"], policy)
    if (
        payload["approved_plan_digest"] != digest(payload["approved_plan"])
        or canonical_json_size(payload) > policy.max_plan_bytes
    ):
        raise WeeklyAdjContractError("更正批准摘要或大小不同")
