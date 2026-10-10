"""Versioned, bounded contracts for delivery of adjusted weekly source rows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo

DATASET_KEY = "stk_period_bar_adj_week"
DELIVERY_TABLE = "core.stock_weekly_adj_delivery"
DELIVERY_DAO = "stock_weekly_adj_delivery"
WRITE_PATH = "raw_core_upsert_with_delivery"
UNIT_BUILDER = "stock_weekly_adj_refresh"
CONTRACT_VERSION = 1
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
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


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
    if len(canonical_json({"rows": result}).encode()) > policy.max_payload_bytes:
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
    """Validate a proposed binding; P1 does not activate the live Definition."""
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
