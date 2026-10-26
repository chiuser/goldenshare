"""Stock technical-factor inputs and immutable local contracts; no execution or I/O."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timedelta
from enum import IntEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType, UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints

import dagster as dg

from orchestrator.tushare_download import DownloadSummary, UnitResult
from orchestrator.tushare_download.contract_registry import content_digest
from orchestrator.tushare_download.contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CONTRACT,
)

STK_FACTOR_PRO_RAW_ASSET_KEY = "raw_tushare_stk_factor_pro"
STK_FACTOR_PRO_SILVER_ASSET_KEY = "silver_stock_factor_pro"
STK_FACTOR_PRO_RAW_CHECK_NAME = "raw_tushare_stk_factor_pro_file_contract_check"
STK_FACTOR_PRO_SILVER_CHECK_NAME = "silver_stock_factor_pro_file_contract_check"
STK_FACTOR_PRO_UPDATE_JOB_NAME = "raw_tushare_stk_factor_pro_update_job"
STK_FACTOR_PRO_REPAIR_JOB_NAME = "raw_tushare_stk_factor_pro_repair_job"
STK_FACTOR_PRO_WRITE_JOB_NAMES = (
    STK_FACTOR_PRO_UPDATE_JOB_NAME,
    STK_FACTOR_PRO_REPAIR_JOB_NAME,
)
STK_FACTOR_PRO_PARTITIONS = "cn_a_stock_factor_pro_trade_days"
STK_FACTOR_PRO_UPDATE_SENSOR_NAME = "raw_tushare_stk_factor_pro_update_job_sensor"
STK_FACTOR_PRO_PARTITION_SENSOR_NAME = "stock_factor_pro_trade_day_sensor"
STK_FACTOR_PRO_PROCESSING_VERSION = "1"
STK_FACTOR_PRO_TIMEZONE = "Asia/Shanghai"
STK_FACTOR_PRO_FIRST_SLOT_HOUR = 19
STK_FACTOR_PRO_SLOT_MINUTES = 30
STK_FACTOR_PRO_SLOT_COUNT = 10
STK_FACTOR_PRO_UPDATE_SENSOR_INTERVAL_SECONDS = 60
STK_FACTOR_PRO_PARTITION_SENSOR_INTERVAL_SECONDS = 600
STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS = 20
STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS = 5000
STK_FACTOR_PRO_CANCEL_STATUS_POLL_SECONDS = 1
STK_FACTOR_PRO_SENSOR_TARGET_SECONDS = 5
STK_FACTOR_PRO_DAY_UPDATE_TARGET_SECONDS = 120
STK_FACTOR_PRO_HISTORY_REFERENCE_TARGET_SECONDS = 1200

STK_FACTOR_PRO_SOURCE_COLUMNS = STK_FACTOR_PRO_CONTRACT.field_names
STK_FACTOR_PRO_RAW_COLUMN_TYPES = MappingProxyType(
    {
        field.name: "VARCHAR" if field.name in ("ts_code", "trade_date") else "DOUBLE"
        for field in STK_FACTOR_PRO_CONTRACT.fields
    }
)
STK_FACTOR_PRO_SILVER_COLUMN_TYPES = MappingProxyType(
    {
        **STK_FACTOR_PRO_RAW_COLUMN_TYPES,
        "trade_date": "DATE",
    }
)

StkFactorProUpdatePurpose = Literal["today", "previous_day", "bootstrap_supplement"]
StkFactorProPurpose = Literal[
    "today", "previous_day", "bootstrap_supplement", "manual_repair"
]
StkFactorProPhase = Literal["day", "history"]
StkFactorProLayer = Literal["raw", "silver"]


class HistoryPlanReason(IntEnum):
    """The six reviewed reasons; these are not downloader error codes."""

    FACTOR_CHANGED = 1
    PRIOR_UNFINISHED = 2
    PREVIOUS_FACTOR_MISSING = 3
    TARGET_FACTOR_MISSING = 4
    BOTH_FACTORS_MISSING = 5
    NO_PRIOR_HISTORY = 6


def normalize_stk_factor_pro_trade_date(value: object) -> str:
    if (
        type(value) is not str
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None
    ):
        raise ValueError("stk_factor_pro 日期必须使用 YYYY-MM-DD")
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("stk_factor_pro 日期格式错误")
    return value


def validate_stk_factor_pro_identifier(value: object) -> str:
    """Reject coercion and traversal; retain native run/operation identifiers."""
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or value in (".", "..")
        or any(c in value for c in ("/", "\\", "\x00"))
    ):
        raise ValueError("stk_factor_pro 标识必须是安全的非空路径单元")
    return value


def _digest(value: object) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("stk_factor_pro 摘要必须是64位小写SHA-256")


def _count(value: object) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("stk_factor_pro 计数必须是非负整数，不能是bool")


def _day(value: object) -> None:
    if type(value) is not date:
        raise ValueError("stk_factor_pro 业务日期必须是date")


def _optional_digest(value: object) -> None:
    if value is not None:
        _digest(value)


def _optional_id(value: object) -> None:
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError("stk_factor_pro 事件/检查id必须是正整数")


def _sample(value: object, *, count: int | None = None) -> None:
    if (
        type(value) is not tuple
        or len(value) > 20
        or any(type(code) is not str or not code for code in value)
        or tuple(sorted(set(value))) != value
        or (count is not None and len(value) > count)
    ):
        raise ValueError("stk_factor_pro 样本必须去重升序、至多20项且不超过实际计数")


def _update_fields(purpose, slot, submission, operation, approval, result) -> None:
    if purpose not in ("today", "previous_day", "bootstrap_supplement"):
        raise ValueError("stk_factor_pro 更新用途错误")
    if purpose == "bootstrap_supplement":
        if slot is not None or submission is not None:
            raise ValueError("bootstrap补数不能占自动时点或提交序号")
        validate_stk_factor_pro_identifier(operation)
        _digest(approval)
        _digest(result)
        return
    if any(v is not None for v in (operation, approval, result)):
        raise ValueError("自动用途不得携带bootstrap授权字段")
    if type(slot) is not int or not 0 <= slot < STK_FACTOR_PRO_SLOT_COUNT:
        raise ValueError("stk_factor_pro scheduled_slot必须是0到9的整数")
    if purpose == "today" and submission is not None:
        raise ValueError("today不接受submission_no")
    if purpose == "previous_day" and (
        type(submission) is not int or not 1 <= submission <= STK_FACTOR_PRO_SLOT_COUNT
    ):
        raise ValueError("previous_day submission_no必须是1到10的整数")


STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA = {
    "execution_day": dg.Field(str),
    "target_trade_date": dg.Field(str),
    "purpose": dg.Field(str),
    "scheduled_slot": dg.Field(dg.Noneable(int), is_required=True),
    "submission_no": dg.Field(dg.Noneable(int), is_required=False, default_value=None),
    "bootstrap_operation_id": dg.Field(
        dg.Noneable(str), is_required=False, default_value=None
    ),
    "expected_bootstrap_approval_digest": dg.Field(
        dg.Noneable(str), is_required=False, default_value=None
    ),
    "expected_bootstrap_date_result_digest": dg.Field(
        dg.Noneable(str), is_required=False, default_value=None
    ),
}


@dataclass(frozen=True, slots=True)
class StkFactorProRunInput:
    execution_day: date
    target_trade_date: date
    purpose: StkFactorProUpdatePurpose
    scheduled_slot: int | None
    submission_no: int | None = None
    bootstrap_operation_id: str | None = None
    expected_bootstrap_approval_digest: str | None = None
    expected_bootstrap_date_result_digest: str | None = None

    def __post_init__(self) -> None:
        _day(self.execution_day)
        _day(self.target_trade_date)
        _update_fields(
            self.purpose,
            self.scheduled_slot,
            self.submission_no,
            self.bootstrap_operation_id,
            self.expected_bootstrap_approval_digest,
            self.expected_bootstrap_date_result_digest,
        )


def parse_stk_factor_pro_run_input(
    config: Mapping[str, object],
    partition_key: str,
    calendar: tuple[date, ...],
) -> StkFactorProRunInput:
    """Parse structure and supplied calendar only; never grant execution authority."""
    required = {"execution_day", "target_trade_date", "purpose", "scheduled_slot"}
    if (
        not isinstance(config, Mapping)
        or set(config) - STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA.keys()
        or not required <= config.keys()
    ):
        raise ValueError("stk_factor_pro配置缺字段或含未知字段")
    if (
        type(calendar) is not tuple
        or not calendar
        or any(type(day) is not date for day in calendar)
        or tuple(sorted(set(calendar))) != calendar
    ):
        raise ValueError("必须提供已校验且升序唯一的SSE开市日历")
    parsed = StkFactorProRunInput(
        date.fromisoformat(
            normalize_stk_factor_pro_trade_date(config["execution_day"])
        ),
        date.fromisoformat(
            normalize_stk_factor_pro_trade_date(config["target_trade_date"])
        ),
        config["purpose"],
        config["scheduled_slot"],
        config.get("submission_no"),
        config.get("bootstrap_operation_id"),
        config.get("expected_bootstrap_approval_digest"),
        config.get("expected_bootstrap_date_result_digest"),
    )
    if (
        normalize_stk_factor_pro_trade_date(partition_key)
        != parsed.target_trade_date.isoformat()
    ):
        raise ValueError("目标日期与分区不符")
    if (
        parsed.target_trade_date not in calendar
        or calendar.index(parsed.target_trade_date) == 0
    ):
        raise ValueError("日历必须覆盖目标T及严格前交易日P")
    if parsed.purpose != "bootstrap_supplement":
        if parsed.execution_day not in calendar:
            raise ValueError("自动执行日D必须是开市日")
        index = calendar.index(parsed.execution_day)
        expected = (
            parsed.execution_day
            if parsed.purpose == "today"
            else calendar[index - 1]
            if index
            else None
        )
        if parsed.target_trade_date != expected:
            raise ValueError("目标T不符合today或previous_day日期关系")
    return parsed


@dataclass(frozen=True, slots=True)
class ContractIdentity:
    contract_name: str
    contract_version: str
    contract_content_digest: str
    processing_version: str

    def __post_init__(self) -> None:
        if (self.contract_name, self.contract_version, self.processing_version) != (
            "stk_factor_pro",
            "1",
            STK_FACTOR_PRO_PROCESSING_VERSION,
        ):
            raise ValueError("stk_factor_pro合同身份或处理版本错误")
        _digest(self.contract_content_digest)


@dataclass(frozen=True, slots=True)
class RunIdentity:
    creator_run_id: str
    source_run_id: str | None
    execution_day: date
    target_trade_date: date
    previous_trade_date: date
    purpose: StkFactorProPurpose
    scheduled_slot: int | None
    submission_no: int | None
    business_attempt: int | None

    def __post_init__(self) -> None:
        validate_stk_factor_pro_identifier(self.creator_run_id)
        if self.source_run_id is not None:
            validate_stk_factor_pro_identifier(self.source_run_id)
        for value in (
            self.execution_day,
            self.target_trade_date,
            self.previous_trade_date,
        ):
            _day(value)
        if self.previous_trade_date >= self.target_trade_date:
            raise ValueError("P必须严格早于T")
        if self.purpose in ("bootstrap_supplement", "manual_repair"):
            if any(
                v is not None
                for v in (
                    self.scheduled_slot,
                    self.submission_no,
                    self.business_attempt,
                )
            ):
                raise ValueError("人工用途不能占自动时点或次数")
        else:
            _update_fields(
                self.purpose, self.scheduled_slot, self.submission_no, None, None, None
            )
            if self.purpose == "previous_day":
                if type(self.business_attempt) is not int or self.business_attempt != 1:
                    raise ValueError("前日业务尝试固定为1")
                if self.target_trade_date >= self.execution_day:
                    raise ValueError("前日T必须早于D")
            elif (
                self.business_attempt is not None
                or self.target_trade_date != self.execution_day
            ):
                raise ValueError("today日期或业务次数错误")


@dataclass(frozen=True, slots=True)
class RecordRef:
    creator_run_id: str
    relative_path: str
    file_sha256: str

    def __post_init__(self) -> None:
        validate_stk_factor_pro_identifier(self.creator_run_id)
        value = self.relative_path
        if (
            type(value) is not str
            or not value
            or "\\" in value
            or "\x00" in value
            or PurePosixPath(value).is_absolute()
            or ".." in PurePosixPath(value).parts
            or PurePosixPath(value).as_posix() != value
            or value == "."
        ):
            raise ValueError("记录引用必须是规范且无越界的相对路径")
        _digest(self.file_sha256)


@dataclass(frozen=True, slots=True)
class VerifiedDaySource:
    """Current-call carrier only; construction is not source/business verification."""

    identity: RunIdentity
    contract: ContractIdentity
    unit_result: UnitResult
    summary: DownloadSummary
    raw_relation: str
    scope_digest: str
    day_source_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, RunIdentity) or not isinstance(
            self.contract, ContractIdentity
        ):
            raise TypeError("日源身份类型错误")
        if not isinstance(self.unit_result, UnitResult) or not isinstance(
            self.summary, DownloadSummary
        ):
            raise TypeError("日源必须持有组件的当前结果和summary")
        if self.raw_relation != "stk_factor_pro_day_source":
            raise ValueError("日源关系名必须由组件内部固定")
        _digest(self.scope_digest)
        _digest(self.day_source_digest)


@dataclass(frozen=True, slots=True)
class StkFactorProComparison:
    expected_rows: int
    actual_rows: int
    missing_key_count: int
    unexpected_key_count: int
    changed_row_count: int
    changed_field_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        for value in (
            self.expected_rows,
            self.actual_rows,
            self.missing_key_count,
            self.unexpected_key_count,
            self.changed_row_count,
        ):
            _count(value)
        expected_matched = self.expected_rows - self.missing_key_count
        actual_matched = self.actual_rows - self.unexpected_key_count
        if (
            expected_matched < 0
            or actual_matched < 0
            or expected_matched != actual_matched
            or self.changed_row_count > expected_matched
        ):
            raise ValueError("对账缺失/额外/匹配及变化行数不一致")
        if type(self.changed_field_counts) is not tuple:
            raise ValueError("逐字段计数必须是tuple")
        names = []
        for name, count in self.changed_field_counts:
            if name not in STK_FACTOR_PRO_SOURCE_COLUMNS[2:]:
                raise ValueError("逐字段计数只能引用契约数值列")
            _count(count)
            if count > self.changed_row_count:
                raise ValueError("字段变化数不能超过变化行数")
            names.append(name)
        if names != sorted(set(names), key=STK_FACTOR_PRO_SOURCE_COLUMNS.index):
            raise ValueError("逐字段计数必须按契约顺序且无重复")
        if (
            sum(count for _, count in self.changed_field_counts)
            < self.changed_row_count
        ):
            raise ValueError("变化行必须至少有一个字段变化")


@dataclass(frozen=True, slots=True)
class StkFactorProFileAudit:
    trade_date: date
    layer: StkFactorProLayer
    path: Path
    file_sha256: str
    observed_schema: tuple[tuple[str, str], ...]
    row_count: int
    invalid_key_count: int
    duplicate_key_count: int
    invalid_date_count: int
    invalid_numeric_count: int
    comparison: StkFactorProComparison
    passed: bool
    diagnostics_path: Path | None

    def __post_init__(self) -> None:
        _day(self.trade_date)
        _digest(self.file_sha256)
        if self.layer not in ("raw", "silver") or not isinstance(self.path, Path):
            raise ValueError("文件检查层级或路径错误")
        if self.diagnostics_path is not None and not isinstance(
            self.diagnostics_path, Path
        ):
            raise ValueError("诊断路径类型错误")
        for value in (
            self.row_count,
            self.invalid_key_count,
            self.duplicate_key_count,
            self.invalid_date_count,
            self.invalid_numeric_count,
        ):
            _count(value)
        if (
            not isinstance(self.comparison, StkFactorProComparison)
            or type(self.passed) is not bool
        ):
            raise ValueError("文件检查结果类型错误")
        schema = (
            STK_FACTOR_PRO_RAW_COLUMN_TYPES
            if self.layer == "raw"
            else STK_FACTOR_PRO_SILVER_COLUMN_TYPES
        )
        calculated = (
            self.observed_schema == tuple(schema.items())
            and self.row_count == self.comparison.actual_rows
            and self.comparison.expected_rows == self.comparison.actual_rows
            and not any(
                (
                    self.invalid_key_count,
                    self.duplicate_key_count,
                    self.invalid_date_count,
                    self.invalid_numeric_count,
                    self.comparison.missing_key_count,
                    self.comparison.unexpected_key_count,
                    self.comparison.changed_row_count,
                )
            )
            and all(count == 0 for _, count in self.comparison.changed_field_counts)
        )
        if self.passed != calculated:
            raise ValueError("文件passed与实际检查计数/schema不符")


@dataclass(frozen=True, slots=True)
class StkFactorProRawCoverage:
    target_trade_date: date
    complete: bool | None
    raw_check_passed: bool
    raw_file_sha256: str | None
    lifecycle_file_sha256: str | None
    suspend_file_sha256: str | None
    identity_file_sha256: str | None
    expected_count: int | None
    actual_count: int | None
    missing_count: int | None
    missing_sample_codes: tuple[str, ...]
    reason: str
    raw_materialization_storage_id: int | None
    raw_check_storage_id: int | None
    missing_codes_ref: RecordRef | None

    def __post_init__(self) -> None:
        _day(self.target_trade_date)
        if self.complete is not None and type(self.complete) is not bool:
            raise ValueError("覆盖必须是bool或None")
        if type(self.raw_check_passed) is not bool or type(self.reason) is not str:
            raise ValueError("覆盖检查字段类型错误")
        digests = (
            self.raw_file_sha256,
            self.lifecycle_file_sha256,
            self.suspend_file_sha256,
            self.identity_file_sha256,
        )
        for value in digests:
            _optional_digest(value)
        for value in (self.expected_count, self.actual_count, self.missing_count):
            if value is not None:
                _count(value)
        for value in (self.raw_materialization_storage_id, self.raw_check_storage_id):
            _optional_id(value)
        _sample(self.missing_sample_codes, count=self.missing_count)
        if self.raw_check_passed and (
            self.raw_file_sha256 is None
            or self.raw_materialization_storage_id is None
            or self.raw_check_storage_id is None
        ):
            raise ValueError("Raw检查通过必须有实际文件和记录身份")
        if self.complete is True and (
            not self.raw_check_passed
            or any(value is None for value in digests)
            or self.missing_count != 0
            or self.expected_count is None
            or self.actual_count is None
            or self.actual_count < self.expected_count
        ):
            raise ValueError("不能将缺失/未知证据标为齐备")
        if self.missing_codes_ref is not None and not isinstance(
            self.missing_codes_ref, RecordRef
        ):
            raise ValueError("缺失清单引用类型错误")
        if self.missing_count in (None, 0) and (
            self.missing_codes_ref is not None or self.missing_sample_codes
        ):
            raise ValueError("零缺失或未知不得伪造缺失清单")


@dataclass(frozen=True, slots=True)
class StkFactorProCoverageCounts:
    expected_count: int | None
    actual_count: int | None
    matched_count: int | None
    missing_count: int | None
    extra_count: int | None
    identity_unmapped_count: int | None
    identity_ambiguous_count: int | None
    identity_unmapped_sample_codes: tuple[str, ...]
    identity_ambiguous_sample_codes: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        counts = (
            self.expected_count,
            self.actual_count,
            self.matched_count,
            self.missing_count,
            self.extra_count,
        )
        for value in (
            *counts,
            self.identity_unmapped_count,
            self.identity_ambiguous_count,
        ):
            if value is not None:
                _count(value)
        _sample(self.identity_unmapped_sample_codes, count=self.identity_unmapped_count)
        _sample(
            self.identity_ambiguous_sample_codes, count=self.identity_ambiguous_count
        )
        if type(self.reason) is not str:
            raise ValueError("覆盖原因必须是文本")
        if any(value is None for value in counts):
            if any(value is not None for value in counts):
                raise ValueError("不能将部分未知覆盖计数伪装成已知")
        elif (
            self.expected_count != self.matched_count + self.missing_count
            or self.actual_count != self.matched_count + self.extra_count
            or self.identity_unmapped_count != 0
            or self.identity_ambiguous_count != 0
        ):
            raise ValueError("覆盖集合计数或身份映射不一致")


@dataclass(frozen=True, slots=True)
class StkFactorProTargetSilver:
    target_trade_date: date
    ready: bool
    silver_file_sha256: str | None
    current_raw_file_sha256: str
    source_raw_file_sha256: str | None
    silver_materialization_storage_id: int | None
    silver_check_execution_id: int | None
    reason: str

    def __post_init__(self) -> None:
        _day(self.target_trade_date)
        _digest(self.current_raw_file_sha256)
        _optional_digest(self.silver_file_sha256)
        _optional_digest(self.source_raw_file_sha256)
        _optional_id(self.silver_materialization_storage_id)
        _optional_id(self.silver_check_execution_id)
        if type(self.ready) is not bool or type(self.reason) is not str:
            raise ValueError("Silver结果字段类型错误")
        if self.ready and (
            self.silver_file_sha256 is None
            or self.source_raw_file_sha256 != self.current_raw_file_sha256
            or self.silver_materialization_storage_id is None
            or self.silver_check_execution_id is None
        ):
            raise ValueError("Silver就绪必须对应当前Raw及有效检查身份")


def stk_factor_pro_schema_digest(layer: StkFactorProLayer) -> str:
    if layer not in ("raw", "silver"):
        raise ValueError("未知股票技术因子层级")
    columns = (
        STK_FACTOR_PRO_RAW_COLUMN_TYPES
        if layer == "raw"
        else STK_FACTOR_PRO_SILVER_COLUMN_TYPES
    )
    return content_digest(
        {
            "record_kind": "stk_factor_pro.local_schema",
            "record_version": 1,
            "value": [{"name": name, "type": kind} for name, kind in columns.items()],
        }
    )


@dataclass(frozen=True, slots=True)
class PublishedTarget:
    trade_date: date
    layer: StkFactorProLayer
    skip_no_file: bool
    file_sha256: str | None
    file_rows: int
    checkpoint_ref: RecordRef | None
    unrefreshed_count: int
    scope_rows: int | None = None
    scope_content_sha256: str | None = None
    scope_content_version: int | None = None

    def __post_init__(self) -> None:
        _day(self.trade_date)
        _count(self.file_rows)
        _count(self.unrefreshed_count)
        if self.layer not in ("raw", "silver") or type(self.skip_no_file) is not bool:
            raise ValueError("发布目标层或跳过标志错误")
        _optional_digest(self.file_sha256)
        if self.skip_no_file:
            if (
                self.file_sha256 is not None
                or self.checkpoint_ref is not None
                or self.file_rows != 0
                or self.unrefreshed_count != 0
            ):
                raise ValueError("无文件目标不得伪造文件或记录")
        elif self.file_sha256 is None or not isinstance(self.checkpoint_ref, RecordRef):
            raise ValueError("发布目标缺少实际文件或完成记录")
        values = (
            self.scope_rows,
            self.scope_content_sha256,
            self.scope_content_version,
        )
        if any(v is not None for v in values):
            if any(v is None for v in values):
                raise ValueError("历史范围摘要三项必须同时提供")
            _count(self.scope_rows)
            _digest(self.scope_content_sha256)
            if self.scope_rows > self.file_rows:
                raise ValueError("历史范围行数不能超过实际文件行数")
            if (
                self.scope_rows == 0
                and self.scope_content_sha256 != hashlib.sha256(b"").hexdigest()
            ):
                raise ValueError("空历史范围必须使用空内容SHA-256")
            if (
                type(self.scope_content_version) is not int
                or self.scope_content_version != 1
            ):
                raise ValueError("未知历史内容摘要版本")


@dataclass(frozen=True, slots=True)
class StkFactorProPublicationRecord:
    """Closed per-file publication record for the day and historical paths."""

    record_version: int
    identity: RunIdentity
    phase: StkFactorProPhase
    trade_date: date
    layer: StkFactorProLayer
    contract: ContractIdentity
    scope_digest: str
    history_input_digest: str | None
    day_source_digest: str | None
    source_manifest_digest: str | None
    target_path: str
    candidate_relative_path: str
    prior_sha256: str | None
    candidate_sha256: str
    candidate_rows: int
    expected_published_sha256: str
    mode: Literal["reuse", "replace"]
    stage: Literal["intent", "complete"]
    unrefreshed_keys_ref: RecordRef | None
    unrefreshed_count: int | None
    verified_at: datetime | None
    actual_sha256: str | None
    actual_rows: int | None

    def __post_init__(self) -> None:
        if (
            type(self.record_version) is not int
            or self.record_version != 1
            or self.phase not in ("day", "history")
        ):
            raise ValueError("发布记录仅支持版本1的day/history阶段")
        if not isinstance(self.identity, RunIdentity) or not isinstance(
            self.contract, ContractIdentity
        ):
            raise TypeError("发布记录身份类型错误")
        _day(self.trade_date)
        if (
            self.layer not in ("raw", "silver")
            or (
                self.phase == "day"
                and self.trade_date != self.identity.target_trade_date
            )
            or (
                self.phase == "history"
                and self.trade_date >= self.identity.target_trade_date
            )
        ):
            raise ValueError("日发布记录日期或层不符")
        for digest in (
            self.scope_digest,
            self.candidate_sha256,
            self.expected_published_sha256,
        ):
            _digest(digest)
        _optional_digest(self.prior_sha256)
        _count(self.candidate_rows)
        if self.phase == "day" and any(
            value is not None
            for value in (
                self.history_input_digest,
                self.source_manifest_digest,
                self.unrefreshed_keys_ref,
                self.unrefreshed_count,
            )
        ):
            raise ValueError("日发布不得混入历史来源或差集引用")
        if self.phase == "day":
            _digest(self.day_source_digest)
        else:
            _digest(self.history_input_digest)
            _digest(self.source_manifest_digest)
            _count(self.unrefreshed_count)
            if self.day_source_digest is not None:
                raise ValueError("历史发布不得混入日源摘要")
            if not isinstance(self.unrefreshed_keys_ref, RecordRef) or (
                self.unrefreshed_keys_ref.creator_run_id != self.identity.creator_run_id
                or self.unrefreshed_keys_ref.relative_path
                != f"publication/history/{self.trade_date.isoformat()}/{self.layer}/unrefreshed-keys.parquet"
            ):
                raise ValueError("历史缺原键引用必须属于当前日期/层/run")
        if (
            type(self.target_path) is not str
            or not Path(self.target_path).is_absolute()
            or ".." in Path(self.target_path).parts
        ):
            raise ValueError("发布目标不是受控绝对路径")
        RecordRef(
            self.identity.creator_run_id,
            self.candidate_relative_path,
            self.candidate_sha256,
        )
        expected_candidate = (
            f"candidates/day/{self.layer}/data.parquet"
            if self.phase == "day"
            else f"candidates/history/{self.trade_date.isoformat()}/{self.layer}/data.parquet"
        )
        if self.candidate_relative_path != expected_candidate:
            raise ValueError("日候选路径必须属于本层固定候选目录")
        suffix = (
            ("raw", "tushare", "stk_factor_pro")
            if self.layer == "raw"
            else ("silver", "stock_factor_pro")
        )
        expected_parts = (
            *suffix,
            f"trade_date={self.trade_date.isoformat()}",
            "data.parquet",
        )
        if Path(self.target_path).parts[-len(expected_parts) :] != expected_parts:
            raise ValueError("发布目标路径与日期或层不符")
        if self.mode not in ("reuse", "replace") or self.stage not in (
            "intent",
            "complete",
        ):
            raise ValueError("发布记录状态错误")
        expected = self.prior_sha256 if self.mode == "reuse" else self.candidate_sha256
        if expected != self.expected_published_sha256:
            raise ValueError("发布预期与模式不符")
        if self.stage == "intent":
            if any(
                v is not None
                for v in (self.verified_at, self.actual_sha256, self.actual_rows)
            ):
                raise ValueError("intent不能冒充已读回完成")
        else:
            if not isinstance(
                self.verified_at, datetime
            ) or self.verified_at.utcoffset() != timedelta(hours=8):
                raise ValueError("发布完成缺少带时区时刻")
            _digest(self.actual_sha256)
            _count(self.actual_rows)
            if (
                self.actual_sha256 != self.expected_published_sha256
                or self.actual_rows != self.candidate_rows
            ):
                raise ValueError("发布完成实际文件与预期不符")


def _version(value: object) -> None:
    if type(value) is not int or value != 1:
        raise ValueError("历史记录版本必须是精确整数1")


def _code(value: object) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", value) is None:
        raise ValueError("历史股票代码不合法")


def _instant(value: object) -> None:
    if type(value) is not datetime or value.utcoffset() != timedelta(hours=8):
        raise ValueError("历史记录时刻必须是带+08:00时区的datetime")


def _finite(value: object) -> None:
    if type(value) is not float or not math.isfinite(value):
        raise ValueError("历史因子值必须是有限DOUBLE")


def _same_run_ref(value: object, identity: RunIdentity, path: str) -> None:
    if not isinstance(value, RecordRef) or (
        value.creator_run_id != identity.creator_run_id or value.relative_path != path
    ):
        raise ValueError("历史记录引用不属于当前run的固定路径")


def _tuple(value: object, kind: type) -> None:
    if type(value) is not tuple or any(not isinstance(item, kind) for item in value):
        raise TypeError("历史集合必须为约定类型的不可变tuple")


@dataclass(frozen=True, slots=True)
class StkFactorProHistoryStart:
    ts_code: str
    start_date: date | None
    earliest_basis_kind: int | None
    earliest_basis_date: date | None

    def __post_init__(self) -> None:
        _code(self.ts_code)
        if self.start_date is None:
            if (
                self.earliest_basis_kind is not None
                or self.earliest_basis_date is not None
            ):
                raise ValueError("未知起点不得携带伪造依据")
        else:
            _day(self.start_date)
            _day(self.earliest_basis_date)
            if type(
                self.earliest_basis_kind
            ) is not int or self.earliest_basis_kind not in (1, 2):
                raise ValueError("起点依据种类只能是1或2")
            if self.start_date != self.earliest_basis_date:
                raise ValueError("历史起点必须等于可信最早日期")


@dataclass(frozen=True, slots=True)
class HistoryOriginRef:
    T: date
    run: str
    relative_path: str
    file_sha: str

    def __post_init__(self) -> None:
        _day(self.T)
        RecordRef(self.run, self.relative_path, self.file_sha)


@dataclass(frozen=True, slots=True)
class HistoryRange:
    ts_code: str
    t_present: bool
    p_present: bool
    t_value: float | None
    p_value: float | None
    start_date: date | None
    end_date: date | None
    plan_reasons: tuple[int, ...]
    origin_target_dates: tuple[date, ...]
    origin_record_refs: tuple[HistoryOriginRef, ...]
    earliest_basis_kind: int | None
    earliest_basis_date: date | None

    def __post_init__(self) -> None:
        _code(self.ts_code)
        for present, value in (
            (self.t_present, self.t_value),
            (self.p_present, self.p_value),
        ):
            if type(present) is not bool:
                raise ValueError("因子存在标记必须是bool")
            if present:
                _finite(value)
            elif value is not None:
                raise ValueError("不存在的因子值必须为NULL")
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("历史起止必须同时已知或同时NULL")
        if self.start_date is not None:
            _day(self.start_date)
            _day(self.end_date)
            if self.start_date > self.end_date:
                raise ValueError("历史起止倒置")
        StkFactorProHistoryStart(
            self.ts_code,
            self.start_date,
            self.earliest_basis_kind,
            self.earliest_basis_date,
        )
        if (
            type(self.plan_reasons) is not tuple
            or not self.plan_reasons
            or any(
                type(value) not in (int, HistoryPlanReason)
                or int(value) not in range(1, 7)
                for value in self.plan_reasons
            )
            or tuple(sorted(set(self.plan_reasons))) != self.plan_reasons
        ):
            raise ValueError("历史原因必须为六项有限值的去重升序tuple")
        _tuple(self.origin_target_dates, date)
        for value in self.origin_target_dates:
            _day(value)
        if tuple(sorted(set(self.origin_target_dates))) != self.origin_target_dates:
            raise ValueError("历史来源日期必须去重升序")
        _tuple(self.origin_record_refs, HistoryOriginRef)
        if len(set(self.origin_record_refs)) != len(self.origin_record_refs):
            raise ValueError("历史来源引用不得重复")
        if any(
            ref.T not in self.origin_target_dates for ref in self.origin_record_refs
        ):
            raise ValueError("历史来源引用日期不在来源日期中")


@dataclass(frozen=True, slots=True)
class FactorFileRef:
    trade_date: date
    asset_key: str
    file_sha256: str
    rows: int

    def __post_init__(self) -> None:
        _day(self.trade_date)
        if self.asset_key != "raw_tushare_adj_factor":
            raise ValueError("历史权威因子只能来自raw_tushare_adj_factor")
        _digest(self.file_sha256)
        _count(self.rows)


@dataclass(frozen=True, slots=True)
class HistoryPlanRecord:
    record_version: int
    identity: RunIdentity
    contract: ContractIdentity
    revision: int
    created_at: datetime
    history_plan_digest: str
    history_ranges_digest: str
    ranges_ref: RecordRef
    full_code_count: int
    factor_t_ref: FactorFileRef
    factor_p_ref: FactorFileRef
    revision_of: RecordRef | None
    origin_plan_ref: RecordRef | None
    origin_history_plan_digest: str | None
    origin_history_ranges_digest: str | None

    def __post_init__(self) -> None:
        _version(self.record_version)
        if not isinstance(self.identity, RunIdentity) or not isinstance(
            self.contract, ContractIdentity
        ):
            raise TypeError("历史计划身份类型错误")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("历史计划revision必须为正整数")
        _instant(self.created_at)
        _digest(self.history_plan_digest)
        _digest(self.history_ranges_digest)
        _same_run_ref(self.ranges_ref, self.identity, "history-ranges.parquet")
        _count(self.full_code_count)
        if not isinstance(self.factor_t_ref, FactorFileRef) or not isinstance(
            self.factor_p_ref, FactorFileRef
        ):
            raise TypeError("历史计划缺少权威T/P引用")
        if (self.factor_t_ref.trade_date, self.factor_p_ref.trade_date) != (
            self.identity.target_trade_date,
            self.identity.previous_trade_date,
        ):
            raise ValueError("历史计划因子日期不是原T/P")
        if self.revision_of is not None and not isinstance(self.revision_of, RecordRef):
            raise TypeError("历史计划修订引用类型错误")
        values = (
            self.origin_plan_ref,
            self.origin_history_plan_digest,
            self.origin_history_ranges_digest,
        )
        if any(value is not None for value in values):
            if not isinstance(self.origin_plan_ref, RecordRef):
                raise ValueError("历史原授权引用缺失")
            _digest(self.origin_history_plan_digest)
            _digest(self.origin_history_ranges_digest)
        elif self.identity.purpose == "manual_repair":
            raise ValueError("手动repair必须保留完整原授权")


@dataclass(frozen=True, slots=True)
class HistoryEligibilityRecord:
    record_version: int
    identity: RunIdentity
    history_plan_digest: str
    history_ranges_digest: str
    raw_coverage: StkFactorProRawCoverage
    target_silver: StkFactorProTargetSilver | None
    evaluated_at: datetime

    def __post_init__(self) -> None:
        _version(self.record_version)
        if not isinstance(self.identity, RunIdentity) or not isinstance(
            self.raw_coverage, StkFactorProRawCoverage
        ):
            raise TypeError("历史资格身份或覆盖类型错误")
        _digest(self.history_plan_digest)
        _digest(self.history_ranges_digest)
        _instant(self.evaluated_at)
        if self.raw_coverage.target_trade_date != self.identity.target_trade_date:
            raise ValueError("历史覆盖不是原T")
        if self.target_silver is not None:
            if not isinstance(self.target_silver, StkFactorProTargetSilver):
                raise TypeError("历史Silver资格类型错误")
            if (
                self.target_silver.target_trade_date != self.identity.target_trade_date
                or (
                    self.target_silver.current_raw_file_sha256
                    != self.raw_coverage.raw_file_sha256
                )
            ):
                raise ValueError("历史Silver不对应本次原T Raw")


@dataclass(frozen=True, slots=True)
class UnitProjection:
    mode: int
    object_code: str | None
    point: date | None
    start_date: date | None
    end_date: date | None

    def __post_init__(self) -> None:
        if type(self.mode) is not int or self.mode not in (2, 5):
            raise ValueError("技术因子unit只能是mode2或mode5")
        if self.mode == 2:
            _day(self.point)
            if any(
                v is not None
                for v in (self.object_code, self.start_date, self.end_date)
            ):
                raise ValueError("日unit不得带股票区间")
        else:
            _code(self.object_code)
            _day(self.start_date)
            _day(self.end_date)
            if self.point is not None or self.start_date > self.end_date:
                raise ValueError("历史unit范围不合法")


@dataclass(frozen=True, slots=True)
class SourceFileRecord:
    phase: Literal["history"]
    unit_key: str
    component_unit_id: str
    ordinal: int
    mode: int
    object_code: str | None
    point: date | None
    start_date: date | None
    end_date: date | None
    source_row_count: int
    saved_row_count: int
    file_relative_path: str
    file_sha256: str
    file_rows: int
    schema_content_digest: str
    contract_content_digest: str
    verified_at: datetime

    def __post_init__(self) -> None:
        unit = UnitProjection(
            self.mode, self.object_code, self.point, self.start_date, self.end_date
        )
        if self.phase != "history" or self.mode != 5:
            raise ValueError("历史manifest只允许history/mode5")
        _digest(self.unit_key)
        if self.unit_key != stk_factor_pro_unit_key(unit):
            raise ValueError("历史manifest unit_key不对应其业务范围")
        if type(self.component_unit_id) is not str or not self.component_unit_id:
            raise ValueError("历史manifest缺少组件unit身份")
        for value in (
            self.ordinal,
            self.source_row_count,
            self.saved_row_count,
            self.file_rows,
        ):
            _count(value)
        if (
            self.source_row_count != self.saved_row_count
            or self.saved_row_count != self.file_rows
        ):
            raise ValueError("历史源、保存及文件行数不符")
        if self.file_relative_path != f"source/history/units/{self.unit_key}.parquet":
            raise ValueError("历史unit文件名必须由业务unit_key生成")
        for value in (
            self.file_sha256,
            self.schema_content_digest,
            self.contract_content_digest,
        ):
            _digest(value)
        if self.schema_content_digest != stk_factor_pro_schema_digest("raw"):
            raise ValueError("历史源schema摘要与完整Raw合同不符")
        _instant(self.verified_at)


@dataclass(frozen=True, slots=True)
class SourceCompleteRecord:
    record_version: int
    identity: RunIdentity
    phase: Literal["history"]
    contract: ContractIdentity
    history_plan_ref: RecordRef
    history_plan_digest: str
    history_plan_revision: int
    origin_history_plan_digest: str | None
    origin_history_ranges_digest: str | None
    history_input_digest: str
    scope_digest: str
    expected_units: tuple[UnitProjection, ...]
    files_manifest_ref: RecordRef
    files_manifest_digest: str
    completed_unit_count: int
    verified_at: datetime

    def __post_init__(self) -> None:
        _version(self.record_version)
        if (
            not isinstance(self.identity, RunIdentity)
            or not isinstance(self.contract, ContractIdentity)
            or self.phase != "history"
        ):
            raise ValueError("历史完整源身份或阶段错误")
        _same_run_ref(self.history_plan_ref, self.identity, "history-plan.json")
        _same_run_ref(
            self.files_manifest_ref,
            self.identity,
            "source/history/source-files.parquet",
        )
        for value in (
            self.history_plan_digest,
            self.history_input_digest,
            self.scope_digest,
            self.files_manifest_digest,
        ):
            _digest(value)
        if (
            type(self.history_plan_revision) is not int
            or self.history_plan_revision < 1
        ):
            raise ValueError("历史源计划revision错误")
        if (self.origin_history_plan_digest is None) != (
            self.origin_history_ranges_digest is None
        ):
            raise ValueError("历史源原授权两摘要必须同时提供")
        if self.origin_history_plan_digest is not None:
            _digest(self.origin_history_plan_digest)
            _digest(self.origin_history_ranges_digest)
        elif self.identity.purpose == "manual_repair":
            raise ValueError("历史repair源缺少原授权摘要")
        _tuple(self.expected_units, UnitProjection)
        if not self.expected_units or any(
            unit.mode != 5 or unit.end_date != self.identity.target_trade_date
            for unit in self.expected_units
        ):
            raise ValueError("历史源必须包含截止原T的完整历史unit")
        keys = tuple(_unit_sort(unit) for unit in self.expected_units)
        if keys != tuple(sorted(set(keys))) or len(
            {u.object_code for u in self.expected_units}
        ) != len(keys):
            raise ValueError("历史expected_units必须按代码/起止去重升序")
        _count(self.completed_unit_count)
        if self.completed_unit_count != len(self.expected_units):
            raise ValueError("历史完成unit数与规划不符")
        if self.scope_digest != stk_factor_pro_scope_digest(
            "history", self.identity.target_trade_date, self.expected_units
        ):
            raise ValueError("历史完整源scope摘要不符")
        _instant(self.verified_at)


@dataclass(frozen=True, slots=True)
class VerifiedSource:
    """Reference carrier; the current-run verifier must inspect actual files."""

    identity: RunIdentity
    contract: ContractIdentity
    source_complete: SourceCompleteRecord
    source_complete_ref: RecordRef

    def __post_init__(self) -> None:
        if not isinstance(self.source_complete, SourceCompleteRecord) or (
            self.identity != self.source_complete.identity
            or self.contract != self.source_complete.contract
        ):
            raise ValueError("已核历史源身份不一致")
        _same_run_ref(
            self.source_complete_ref,
            self.identity,
            "source/history/source-complete.json",
        )


@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapCodesRef:
    relative_path: str
    file_sha256: str
    row_count: int

    def __post_init__(self) -> None:
        RecordRef("operation", self.relative_path, self.file_sha256)
        _count(self.row_count)


@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapContext:
    operation_id: str
    approval_digest: str
    target_trade_date: date
    authorized_date_result_digest: str
    authorized_gap_input_digest: str
    authorized_missing_count: int
    authorized_missing_codes_ref: StkFactorProBootstrapCodesRef
    authorization_run_id: str

    def __post_init__(self) -> None:
        validate_stk_factor_pro_identifier(self.operation_id)
        validate_stk_factor_pro_identifier(self.authorization_run_id)
        _day(self.target_trade_date)
        for value in (
            self.approval_digest,
            self.authorized_date_result_digest,
            self.authorized_gap_input_digest,
        ):
            _digest(value)
        _count(self.authorized_missing_count)
        if (
            self.authorized_missing_count == 0
            or not isinstance(
                self.authorized_missing_codes_ref, StkFactorProBootstrapCodesRef
            )
            or self.authorized_missing_codes_ref.row_count
            != self.authorized_missing_count
        ):
            raise ValueError("bootstrap原缺口授权必须为正数量及实际引用")


@dataclass(frozen=True, slots=True)
class StkFactorProResultRef:
    run_id: str
    storage_id: int

    def __post_init__(self) -> None:
        validate_stk_factor_pro_identifier(self.run_id)
        if type(self.storage_id) is not int or self.storage_id <= 0:
            raise ValueError("阶段结果storage_id必须为正精确int")


@dataclass(frozen=True, slots=True)
class StkFactorProRecordedResults:
    target_trade_date: date
    day_result_ref: StkFactorProResultRef | None
    history_result_ref: StkFactorProResultRef | None
    history_plan_ref: RecordRef | None
    history_ranges_ref: RecordRef | None
    raw_coverage: StkFactorProRawCoverage | None
    bootstrap_context: StkFactorProBootstrapContext | None
    pending_plan_refs: tuple[RecordRef, ...]
    successful_publication_refs: tuple[RecordRef, ...]
    unresolved_day_failure_run_id: str | None
    unresolved_history_failure_run_id: str | None

    def __post_init__(self) -> None:
        _day(self.target_trade_date)
        for value, kind in (
            (self.day_result_ref, StkFactorProResultRef),
            (self.history_result_ref, StkFactorProResultRef),
            (self.history_plan_ref, RecordRef),
            (self.history_ranges_ref, RecordRef),
            (self.raw_coverage, StkFactorProRawCoverage),
            (self.bootstrap_context, StkFactorProBootstrapContext),
        ):
            if value is not None and not isinstance(value, kind):
                raise TypeError("已记录结果嵌套类型错误")
        if (
            self.raw_coverage is not None
            and self.raw_coverage.target_trade_date != self.target_trade_date
        ):
            raise ValueError("已记录覆盖不是同T")
        if (
            self.bootstrap_context is not None
            and self.bootstrap_context.target_trade_date != self.target_trade_date
        ):
            raise ValueError("已记录bootstrap上下文不是同T")
        for refs in (self.pending_plan_refs, self.successful_publication_refs):
            _tuple(refs, RecordRef)
            if len(set(refs)) != len(refs):
                raise ValueError("已记录意图引用不得重复")
        for value in (
            self.unresolved_day_failure_run_id,
            self.unresolved_history_failure_run_id,
        ):
            if value is not None:
                validate_stk_factor_pro_identifier(value)


@dataclass(frozen=True, slots=True)
class PublicationCompleteRecord:
    record_version: int
    identity: RunIdentity
    phase: StkFactorProPhase
    contract: ContractIdentity
    history_plan_digest: str
    history_ranges_digest: str
    scope_digest: str
    history_input_digest: str | None
    source_complete_ref: RecordRef | None
    day_source_digest: str | None
    source_manifest_digest: str | None
    targets: tuple[PublishedTarget, ...]
    verified_at: datetime

    def __post_init__(self) -> None:
        _version(self.record_version)
        if (
            not isinstance(self.identity, RunIdentity)
            or not isinstance(self.contract, ContractIdentity)
            or self.phase not in ("day", "history")
        ):
            raise ValueError("完整发布记录身份或阶段错误")
        for value in (
            self.history_plan_digest,
            self.history_ranges_digest,
            self.scope_digest,
        ):
            _digest(value)
        if self.phase == "day":
            _digest(self.day_source_digest)
            if any(
                value is not None
                for value in (
                    self.history_input_digest,
                    self.source_complete_ref,
                    self.source_manifest_digest,
                )
            ):
                raise ValueError("日完整发布不得混入历史来源")
        else:
            if self.day_source_digest is not None:
                raise ValueError("历史完整发布不得混入日源")
            _digest(self.history_input_digest)
            _digest(self.source_manifest_digest)
            _same_run_ref(
                self.source_complete_ref,
                self.identity,
                "source/history/source-complete.json",
            )
        _tuple(self.targets, PublishedTarget)
        keys = tuple((target.trade_date, target.layer) for target in self.targets)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("完整发布日期/层必须去重升序")
        for target in self.targets:
            if target.unrefreshed_count:
                raise ValueError("历史存在未刷新旧键，不能记录完整发布")
            if self.phase == "day":
                if (
                    target.trade_date != self.identity.target_trade_date
                    or target.scope_rows is not None
                ):
                    raise ValueError("日完整发布范围错误")
            elif (
                target.trade_date >= self.identity.target_trade_date
                or target.scope_rows is None
            ):
                raise ValueError("历史完整发布范围或scope缺失")
            if target.checkpoint_ref is not None:
                _same_run_ref(
                    target.checkpoint_ref,
                    self.identity,
                    f"publication/{self.phase}/{target.trade_date.isoformat()}/{target.layer}/complete.json",
                )
        for day in {target.trade_date for target in self.targets}:
            if {
                target.layer for target in self.targets if target.trade_date == day
            } != {"raw", "silver"}:
                raise ValueError("完整发布必须有每日期两层事实")
        _instant(self.verified_at)


def _unit_sort(unit: UnitProjection):
    return (
        unit.object_code or "",
        unit.start_date or date.min,
        unit.end_date or date.min,
        unit.point or date.min,
    )


def _business_digest(kind: str, projection: object) -> str:
    return content_digest(
        {"record_kind": kind, "record_version": 1, "value": projection}
    )


def stk_factor_pro_unit_key(unit: UnitProjection) -> str:
    if not isinstance(unit, UnitProjection):
        raise TypeError("unit业务摘要必须接收UnitProjection")
    return _business_digest("stk_factor_pro.unit", stk_factor_pro_record_to_dict(unit))


def stk_factor_pro_scope_digest(
    phase: StkFactorProPhase, target: date, units: tuple[UnitProjection, ...]
) -> str:
    _day(target)
    _tuple(units, UnitProjection)
    if phase not in ("day", "history"):
        raise ValueError("scope阶段错误")
    if len(set(units)) != len(units):
        raise ValueError("scope不得包含重复unit")
    if phase == "day" and units != (UnitProjection(2, None, target, None, None),):
        raise ValueError("日scope必须唯一原T")
    if phase == "history" and any(
        unit.mode != 5 or unit.end_date != target for unit in units
    ):
        raise ValueError("历史scope必须截止原T")
    return _business_digest(
        "stk_factor_pro.scope",
        {
            "phase": phase,
            "T": target.isoformat(),
            "units": [
                stk_factor_pro_record_to_dict(unit)
                for unit in sorted(units, key=_unit_sort)
            ],
        },
    )


def _ranges(ranges: tuple[HistoryRange, ...]) -> tuple[HistoryRange, ...]:
    _tuple(ranges, HistoryRange)
    if len({row.ts_code for row in ranges}) != len(ranges):
        raise ValueError("历史范围代码重复")
    return tuple(sorted(ranges, key=lambda row: row.ts_code))


def stk_factor_pro_history_ranges_digest(ranges: tuple[HistoryRange, ...]) -> str:
    return _business_digest(
        "stk_factor_pro.history_ranges",
        [
            {
                "ts_code": row.ts_code,
                "start_date": row.start_date.isoformat() if row.start_date else None,
                "end_date": row.end_date.isoformat() if row.end_date else None,
            }
            for row in _ranges(ranges)
        ],
    )


def _hex(value: float | None) -> str | None:
    return None if value is None else (0.0 if value == 0 else value).hex()


def stk_factor_pro_history_plan_digest(
    identity: RunIdentity, contract: ContractIdentity, ranges: tuple[HistoryRange, ...]
) -> str:
    return _business_digest(
        "stk_factor_pro.history_plan",
        {
            "T": identity.target_trade_date.isoformat(),
            "P": identity.previous_trade_date.isoformat(),
            "contract": stk_factor_pro_record_to_dict(contract),
            "history_ranges_digest": stk_factor_pro_history_ranges_digest(ranges),
            "entries": [
                {
                    "ts_code": row.ts_code,
                    "t_present": row.t_present,
                    "p_present": row.p_present,
                    "t_value_hex": _hex(row.t_value),
                    "p_value_hex": _hex(row.p_value),
                    "plan_reasons": [int(reason) for reason in row.plan_reasons],
                    "origin_target_dates": [
                        day.isoformat() for day in row.origin_target_dates
                    ],
                    "earliest_basis": {
                        "kind": row.earliest_basis_kind,
                        "date": row.earliest_basis_date.isoformat()
                        if row.earliest_basis_date
                        else None,
                    },
                }
                for row in _ranges(ranges)
            ],
        },
    )


def stk_factor_pro_history_input_digest(
    identity: RunIdentity,
    contract: ContractIdentity,
    units: tuple[UnitProjection, ...],
    ranges: tuple[HistoryRange, ...],
) -> str:
    by_code = {row.ts_code: row for row in _ranges(ranges)}
    selected = []
    for unit in sorted(units, key=_unit_sort):
        row = by_code.get(unit.object_code)
        if (
            row is None
            or not row.t_present
            or not row.p_present
            or (row.start_date, row.end_date) != (unit.start_date, unit.end_date)
        ):
            raise ValueError("历史请求与完整范围/关键因子不符")
        selected.append(
            {
                "ts_code": row.ts_code,
                "t_value_hex": _hex(row.t_value),
                "p_value_hex": _hex(row.p_value),
            }
        )
    return _business_digest(
        "stk_factor_pro.history_input",
        {
            "T": identity.target_trade_date.isoformat(),
            "P": identity.previous_trade_date.isoformat(),
            "contract": stk_factor_pro_record_to_dict(contract),
            "scope_digest": stk_factor_pro_scope_digest(
                "history", identity.target_trade_date, units
            ),
            "factors": selected,
        },
    )


def stk_factor_pro_files_manifest_digest(
    scope_digest: str, files: tuple[SourceFileRecord, ...]
) -> str:
    _digest(scope_digest)
    _tuple(files, SourceFileRecord)
    if len({row.unit_key for row in files}) != len(files):
        raise ValueError("历史manifest重复unit")
    return _business_digest(
        "stk_factor_pro.source_files",
        {
            "scope_digest": scope_digest,
            "files": [
                {
                    "unit": stk_factor_pro_record_to_dict(
                        UnitProjection(
                            row.mode,
                            row.object_code,
                            row.point,
                            row.start_date,
                            row.end_date,
                        )
                    ),
                    "source_row_count": row.source_row_count,
                    "saved_row_count": row.saved_row_count,
                    "file_sha256": row.file_sha256,
                    "file_rows": row.file_rows,
                    "schema_content_digest": row.schema_content_digest,
                }
                for row in sorted(files, key=lambda item: item.unit_key)
            ],
        },
    )


def stk_factor_pro_record_to_dict(record: object):
    """Canonical JSON-ready closed records; I/O remains in the owning module."""
    if record is None or type(record) in (str, bool, int, float):
        if type(record) is float:
            _finite(record)
        return record
    if isinstance(record, IntEnum):
        return int(record)
    if type(record) is date:
        return record.isoformat()
    if type(record) is datetime:
        _instant(record)
        return record.isoformat(timespec="microseconds")
    if is_dataclass(record) and not isinstance(record, type):
        return {
            field.name: stk_factor_pro_record_to_dict(getattr(record, field.name))
            for field in fields(record)
        }
    if type(record) is tuple:
        return [stk_factor_pro_record_to_dict(item) for item in record]
    raise TypeError("不支持的历史记录序列化类型")


def _parse_record_value(annotation, value):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        for choice in args:
            try:
                return _parse_record_value(choice, value)
            except (TypeError, ValueError):
                continue
        raise ValueError("历史记录联合字段类型不符")
    if annotation is type(None):
        if value is not None:
            raise ValueError("历史记录应为NULL")
        return None
    if origin is Literal:
        if not any(type(value) is type(item) and value == item for item in args):
            raise ValueError("历史记录Literal字段不符")
        return value
    if origin is tuple:
        if type(value) is not list:
            raise ValueError("历史JSON集合必须是数组")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_parse_record_value(args[0], item) for item in value)
        if len(value) != len(args):
            raise ValueError("历史JSON定长数组长度不符")
        return tuple(
            _parse_record_value(kind, item)
            for kind, item in zip(args, value, strict=True)
        )
    if annotation is date:
        if (
            type(value) is not str
            or normalize_stk_factor_pro_trade_date(value) != value
        ):
            raise ValueError("历史JSON日期不是ISO格式")
        return date.fromisoformat(value)
    if annotation is datetime:
        if type(value) is not str:
            raise ValueError("历史JSON时刻不是文本")
        parsed = datetime.fromisoformat(value)
        _instant(parsed)
        if parsed.isoformat(timespec="microseconds") != value:
            raise ValueError("历史JSON时刻必须固定微秒和+08:00")
        return parsed
    if isinstance(annotation, type) and is_dataclass(annotation):
        return parse_stk_factor_pro_record(annotation, value)
    if annotation in (str, int, float, bool):
        if type(value) is not annotation:
            raise ValueError("历史记录精确字段类型不符")
        return value
    raise TypeError("不支持的历史记录字段类型")


def parse_stk_factor_pro_record(record_type: type, value: dict):
    """Strictly parse every field; absent nullable values still require a key."""
    if not is_dataclass(record_type) or type(value) is not dict:
        raise ValueError("历史记录必须是完整JSON对象")
    definitions = fields(record_type)
    if set(value) != {field.name for field in definitions}:
        raise ValueError("历史记录缺字段或含未知字段")
    hints = get_type_hints(record_type)
    return record_type(
        **{
            field.name: _parse_record_value(hints[field.name], value[field.name])
            for field in definitions
        }
    )
