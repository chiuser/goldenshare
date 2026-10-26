"""Stock technical-factor inputs and immutable local contracts; no execution or I/O."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import IntEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal

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
            if (
                type(self.scope_content_version) is not int
                or self.scope_content_version != 1
            ):
                raise ValueError("未知历史内容摘要版本")


@dataclass(frozen=True, slots=True)
class StkFactorProPublicationRecord:
    """The reviewed per-file wire record. Batch two implements day only."""

    record_version: int
    identity: RunIdentity
    phase: Literal["day"]
    trade_date: date
    layer: StkFactorProLayer
    contract: ContractIdentity
    scope_digest: str
    history_input_digest: None
    day_source_digest: str
    source_manifest_digest: None
    target_path: str
    candidate_relative_path: str
    prior_sha256: str | None
    candidate_sha256: str
    candidate_rows: int
    expected_published_sha256: str
    mode: Literal["reuse", "replace"]
    stage: Literal["intent", "complete"]
    unrefreshed_keys_ref: None
    unrefreshed_count: None
    verified_at: datetime | None
    actual_sha256: str | None
    actual_rows: int | None

    def __post_init__(self) -> None:
        if (
            type(self.record_version) is not int
            or self.record_version != 1
            or self.phase != "day"
        ):
            raise ValueError("本批发布记录仅支持版本1的日阶段")
        if not isinstance(self.identity, RunIdentity) or not isinstance(
            self.contract, ContractIdentity
        ):
            raise TypeError("发布记录身份类型错误")
        _day(self.trade_date)
        if self.trade_date != self.identity.target_trade_date or self.layer not in (
            "raw",
            "silver",
        ):
            raise ValueError("日发布记录日期或层不符")
        for digest in (
            self.scope_digest,
            self.day_source_digest,
            self.candidate_sha256,
            self.expected_published_sha256,
        ):
            _digest(digest)
        _optional_digest(self.prior_sha256)
        _count(self.candidate_rows)
        if any(
            value is not None
            for value in (
                self.history_input_digest,
                self.source_manifest_digest,
                self.unrefreshed_keys_ref,
                self.unrefreshed_count,
            )
        ):
            raise ValueError("日发布不得混入历史来源或差集引用")
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
        if self.candidate_relative_path != f"candidates/day/{self.layer}/data.parquet":
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
