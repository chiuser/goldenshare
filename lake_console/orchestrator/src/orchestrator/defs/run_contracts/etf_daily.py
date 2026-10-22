"""Stable contracts for Tushare fund daily and adjustment-factor assets."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_REQUESTABILITY_EXCHANGE_MISMATCH,
    ETF_BASIC_REQUESTABILITY_LIST_DATE_AFTER_AS_OF,
    ETF_BASIC_REQUESTABILITY_LIST_DATE_NULL,
    ETF_BASIC_REQUESTABILITY_NON_EXCHANGE_SUFFIX,
    ETF_BASIC_REQUESTABILITY_STATUS_NOT_LISTED,
    classify_etf_basic_requestability,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

FUND_DAILY_API_NAME = "fund_daily"
FUND_ADJ_API_NAME = "fund_adj"
FUND_DAILY_PAGE_LIMIT = 5_000
FUND_ADJ_PAGE_LIMIT = 2_000

RAW_TUSHARE_FUND_DAILY_ASSET_KEY = "raw_tushare_fund_daily"
SILVER_ETF_DAILY_ASSET_KEY = "silver_etf_daily"
RAW_TUSHARE_FUND_ADJ_ASSET_KEY = "raw_tushare_fund_adj"
SILVER_ETF_ADJ_FACTOR_ASSET_KEY = "silver_etf_adj_factor"

FUND_DAILY_DATASET_ID = "fund_daily"
ETF_DAILY_DATASET_ID = "etf_daily"
FUND_ADJ_DATASET_ID = "fund_adj"
ETF_ADJ_FACTOR_DATASET_ID = "etf_adj_factor"

RAW_FUND_DAILY_JOB_NAME = "raw_fund_daily_update_job"
SILVER_ETF_DAILY_JOB_NAME = "silver_etf_daily_update_job"
RAW_FUND_ADJ_JOB_NAME = "raw_fund_adj_update_job"
SILVER_ETF_ADJ_FACTOR_JOB_NAME = "silver_etf_adj_factor_update_job"

RAW_FUND_DAILY_SENSOR_NAME = f"{RAW_FUND_DAILY_JOB_NAME}_sensor"
SILVER_ETF_DAILY_SENSOR_NAME = f"{SILVER_ETF_DAILY_JOB_NAME}_sensor"
RAW_FUND_ADJ_SENSOR_NAME = f"{RAW_FUND_ADJ_JOB_NAME}_sensor"
SILVER_ETF_ADJ_FACTOR_SENSOR_NAME = f"{SILVER_ETF_ADJ_FACTOR_JOB_NAME}_sensor"

ETF_DAILY_SENSOR_WINDOW_LIMIT = 10
ETF_DAILY_BOOTSTRAP_START_DATE = date(2025, 1, 1)
ETF_DAILY_BOOTSTRAP_BATCH_DAYS = 20
ETF_DAILY_BOOTSTRAP_CHECK_EVENT_TAIL_DAYS = 20
ETF_DAILY_DISK_SAFETY_FACTOR = Decimal("2.5")
ETF_DAILY_AUTOMATION_CONTRACT_REVISION = "v1"
ETF_DAILY_BOOTSTRAP_CONTRACT_REVISION = "v1"
ETF_DAILY_COVERAGE_POLICY_REVISION = "fund_daily_warn__fund_adj_blocking_v3"
ETF_DAILY_CHANGE_TOLERANCE = 1e-6
ETF_DAILY_PCT_CHG_TOLERANCE = 0.01
ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT = 20

FUND_DAILY_SOURCE_COLUMNS = (
    "ts_code",
    "trade_date",
    "pre_close",
    "open",
    "high",
    "low",
    "close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)

FUND_ADJ_SOURCE_COLUMNS = (
    "ts_code",
    "trade_date",
    "adj_factor",
    "discount_rate",
)

FUND_DAILY_RAW_COLUMN_TYPES = MappingProxyType(
    {
        column: "VARCHAR" if column in {"ts_code", "trade_date"} else "DOUBLE"
        for column in FUND_DAILY_SOURCE_COLUMNS
    }
)
FUND_DAILY_SILVER_COLUMN_TYPES = MappingProxyType(
    {
        column: "DATE"
        if column == "trade_date"
        else "VARCHAR"
        if column == "ts_code"
        else "DOUBLE"
        for column in FUND_DAILY_SOURCE_COLUMNS
    }
)
FUND_ADJ_RAW_COLUMN_TYPES = MappingProxyType(
    {
        column: "VARCHAR" if column in {"ts_code", "trade_date"} else "DOUBLE"
        for column in FUND_ADJ_SOURCE_COLUMNS
    }
)
FUND_ADJ_SILVER_COLUMN_TYPES = MappingProxyType(
    {
        column: "DATE"
        if column == "trade_date"
        else "VARCHAR"
        if column == "ts_code"
        else "DOUBLE"
        for column in FUND_ADJ_SOURCE_COLUMNS
    }
)

ETF_DAILY_REJECTION_REASON_CODES = (
    "NON_EXCHANGE_SUFFIX",
    "BASIC_CODE_ABSENT",
    "EXCHANGE_MISMATCH",
    "STATUS_NOT_LISTED",
    "LIST_DATE_NULL",
    "LIST_DATE_AFTER_TRADE_DATE",
)

RAW_FUND_DAILY_CHECKS = (
    "raw_tushare_fund_daily_source_contract_check",
    "raw_tushare_fund_daily_partition_scope_check",
    "raw_tushare_fund_daily_key_integrity_check",
)
RAW_FUND_ADJ_CHECKS = (
    "raw_tushare_fund_adj_source_contract_check",
    "raw_tushare_fund_adj_partition_scope_check",
    "raw_tushare_fund_adj_key_integrity_check",
)
SILVER_ETF_DAILY_BLOCKING_CHECKS = (
    "silver_etf_daily_contract_check",
    "silver_etf_daily_source_filter_check",
    "silver_etf_daily_source_parity_check",
    "silver_etf_daily_key_integrity_check",
    "silver_etf_daily_bar_domain_check",
)
SILVER_ETF_DAILY_COVERAGE_CHECK = "silver_etf_daily_basic_coverage_check"
SILVER_ETF_ADJ_FACTOR_COVERAGE_CHECK = "silver_etf_adj_factor_basic_coverage_check"
SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS = (
    "silver_etf_adj_factor_contract_check",
    "silver_etf_adj_factor_source_filter_check",
    "silver_etf_adj_factor_source_parity_check",
    "silver_etf_adj_factor_key_integrity_check",
    "silver_etf_adj_factor_domain_check",
    SILVER_ETF_ADJ_FACTOR_COVERAGE_CHECK,
)

FUND_DAILY_REQUEST_POLICY = TushareRequestPolicy(
    minimum_interval_seconds=0.13,
    max_retries=1,
    max_requests=2,
    max_elapsed_seconds=30.0,
)
FUND_ADJ_REQUEST_POLICY = TushareRequestPolicy(
    minimum_interval_seconds=0.13,
    max_retries=1,
    max_requests=4,
    max_elapsed_seconds=30.0,
)


class EtfDailyContractError(ValueError):
    """Raised when an ETF daily contract value is invalid."""


@dataclass(frozen=True, slots=True)
class EtfDailySourceRequest:
    api_name: str
    params: Mapping[str, object]
    fields: tuple[str, ...]


def normalize_etf_daily_trade_date(value: str | date) -> str:
    """Return one strict ISO trade date used by partitions and paths."""

    if isinstance(value, datetime):
        raise EtfDailyContractError("ETF daily trade date must not include a time")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise EtfDailyContractError(
            f"ETF daily trade date must use YYYY-MM-DD: {value!r}"
        ) from error
    if text != parsed.isoformat():
        raise EtfDailyContractError(
            f"ETF daily trade date must use YYYY-MM-DD: {value!r}"
        )
    return text


def classify_etf_daily_source_row(
    *,
    ts_code: object,
    trade_date: date,
    basic_row: Mapping[str, object] | None,
) -> str | None:
    """Classify one Raw row against the frozen Basic snapshot in fixed order."""

    if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
        raise EtfDailyContractError("ETF daily classification trade_date must be DATE")
    if not isinstance(ts_code, str) or not ts_code.endswith((".SH", ".SZ")):
        return "NON_EXCHANGE_SUFFIX"
    if basic_row is None or basic_row.get("ts_code") != ts_code:
        return "BASIC_CODE_ABSENT"
    reason = classify_etf_basic_requestability(
        basic_row,
        eligibility_as_of=trade_date,
    )
    return {
        None: None,
        ETF_BASIC_REQUESTABILITY_NON_EXCHANGE_SUFFIX: "NON_EXCHANGE_SUFFIX",
        ETF_BASIC_REQUESTABILITY_EXCHANGE_MISMATCH: "EXCHANGE_MISMATCH",
        ETF_BASIC_REQUESTABILITY_STATUS_NOT_LISTED: "STATUS_NOT_LISTED",
        ETF_BASIC_REQUESTABILITY_LIST_DATE_NULL: "LIST_DATE_NULL",
        ETF_BASIC_REQUESTABILITY_LIST_DATE_AFTER_AS_OF: ("LIST_DATE_AFTER_TRADE_DATE"),
    }[reason]


def _validated_offset(offset: int, *, page_limit: int) -> int:
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise EtfDailyContractError("ETF daily offset must be an integer")
    if offset < 0 or offset % page_limit != 0:
        raise EtfDailyContractError(
            "ETF daily offset must be a non-negative multiple of the page limit"
        )
    return offset


def _build_source_request(
    *,
    api_name: str,
    source_columns: tuple[str, ...],
    page_limit: int,
    partition_key: str | date,
    offset: int,
) -> EtfDailySourceRequest:
    trade_date = normalize_etf_daily_trade_date(partition_key)
    return EtfDailySourceRequest(
        api_name=api_name,
        params=MappingProxyType(
            {
                "trade_date": trade_date.replace("-", ""),
                "limit": page_limit,
                "offset": _validated_offset(offset, page_limit=page_limit),
            }
        ),
        fields=source_columns,
    )


def build_fund_daily_request(
    partition_key: str | date,
    offset: int,
) -> EtfDailySourceRequest:
    return _build_source_request(
        api_name=FUND_DAILY_API_NAME,
        source_columns=FUND_DAILY_SOURCE_COLUMNS,
        page_limit=FUND_DAILY_PAGE_LIMIT,
        partition_key=partition_key,
        offset=offset,
    )


def build_fund_adj_request(
    partition_key: str | date,
    offset: int,
) -> EtfDailySourceRequest:
    return _build_source_request(
        api_name=FUND_ADJ_API_NAME,
        source_columns=FUND_ADJ_SOURCE_COLUMNS,
        page_limit=FUND_ADJ_PAGE_LIMIT,
        partition_key=partition_key,
        offset=offset,
    )


# Only the reviewed business scope is fixed here; the actual keys live in the Plan.
ETF_FACTOR_COMPLETION_SCOPE_HASH = (
    "b42c991cbe1711316c48ad0782e9cb21d4b3944967013aa01c5288481400f76b"
)
ETF_FACTOR_COMPLETION_METADATA_KEY = "goldenshare/history_completion"


def etf_factor_completion_hash(payload: object) -> str:
    """Canonical business hash; callers explicitly choose fields, never event ids."""
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def validate_etf_factor_completion_scope(scope: Mapping[str, object]) -> None:
    """Reject every scope other than the 56-code/701-key table reviewed in LLD11.9."""
    if etf_factor_completion_hash(scope) != ETF_FACTOR_COMPLETION_SCOPE_HASH:
        raise EtfDailyContractError("etf_factor_completion_scope_not_approved")


@dataclass(frozen=True, slots=True)
class EtfFactorCompletionFile:
    trade_date: str
    original_storage_id: int
    original_run_id: str | None
    original_metadata: Mapping[str, object]
    original_check_ids: Mapping[str, int]
    raw_storage_id: int
    raw_metadata: Mapping[str, object]
    expected_row_count: int
    expected_content_hash: str

    def validate(self, added_count: int) -> None:
        import re

        normalize_etf_daily_trade_date(self.trade_date)
        if (
            type(self.original_storage_id) is not int
            or self.original_storage_id <= 0
            or type(self.raw_storage_id) is not int
            or self.raw_storage_id <= 0
            or set(self.original_check_ids)
            != set(SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS)
            or any(
                type(x) is not int or x <= 0 for x in self.original_check_ids.values()
            )
            or type(self.expected_row_count) is not int
            or type(self.original_metadata.get("dagster/row_count")) is not int
            or self.expected_row_count
            != self.original_metadata["dagster/row_count"] + added_count
            or self.expected_row_count > 5000
            or not re.fullmatch(r"[0-9a-f]{64}", self.expected_content_hash)
            or ETF_FACTOR_COMPLETION_METADATA_KEY in self.original_metadata
        ):
            raise EtfDailyContractError(
                "etf_factor_completion_original_or_output_invalid"
            )

    def to_dict(self) -> dict[str, object]:
        from dataclasses import asdict

        return asdict(self)


@dataclass(frozen=True, slots=True)
class EtfFactorCompletionPlan:
    scope: Mapping[str, object]
    basic_reference: Mapping[str, object]
    basic_evidence: Mapping[str, object]
    files: tuple[EtfFactorCompletionFile, ...]

    def validate(self) -> "EtfFactorCompletionPlan":
        from orchestrator.defs.run_contracts.etf_basic import (
            EtfBasicSilverSnapshotReference,
        )

        validate_etf_factor_completion_scope(self.scope)
        EtfBasicSilverSnapshotReference.model_validate(
            self.basic_reference
        ).validate_contract()
        if (
            set(self.basic_evidence) != {"storage_id", "metadata", "check_ids"}
            or type(self.basic_evidence["storage_id"]) is not int
            or self.basic_evidence["storage_id"] <= 0
            or len(self.basic_evidence["check_ids"]) != 3
            or self.basic_evidence["metadata"].get("goldenshare/raw_snapshot_hash")
            != self.basic_reference["raw_snapshot_hash"]
            or self.basic_evidence["metadata"].get("goldenshare/silver_content_hash")
            != self.basic_reference["silver_content_hash"]
        ):
            raise EtfDailyContractError("etf_factor_completion_basic_evidence_invalid")
        additions = self.scope["additions"]
        if not isinstance(additions, dict) or tuple(
            f.trade_date for f in self.files
        ) != tuple(sorted(additions)):
            raise EtfDailyContractError("etf_factor_completion_dates_invalid")
        for item in self.files:
            item.validate(len(additions[item.trade_date]))
        return self

    def file(self, trade_date: str) -> EtfFactorCompletionFile:
        return next(f for f in self.files if f.trade_date == trade_date)

    @property
    def plan_hash(self) -> str:
        # Record identity and observation times are traceability, not business identity.
        return etf_factor_completion_hash(
            {
                "scope": self.scope,
                "basic_content": {
                    key: self.basic_reference[key]
                    for key in ("raw_snapshot_hash", "silver_content_hash")
                },
                "files": [
                    {
                        "trade_date": f.trade_date,
                        "original_count": f.original_metadata["dagster/row_count"],
                        "original_hash": f.original_metadata[
                            "goldenshare/content_hash"
                        ],
                        "original_basic_raw_hash": f.original_metadata[
                            "goldenshare/basic_raw_snapshot_hash"
                        ],
                        "original_basic_silver_hash": f.original_metadata[
                            "goldenshare/basic_silver_content_hash"
                        ],
                        "raw_count": f.raw_metadata["dagster/row_count"],
                        "raw_hash": f.raw_metadata["goldenshare/content_hash"],
                        "expected_row_count": f.expected_row_count,
                        "expected_content_hash": f.expected_content_hash,
                    }
                    for f in self.files
                ],
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": dict(self.scope),
            "basic_reference": dict(self.basic_reference),
            "basic_evidence": dict(self.basic_evidence),
            "files": [f.to_dict() for f in self.files],
            "plan_hash": self.plan_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EtfFactorCompletionPlan":
        import json

        if (
            set(payload)
            != {"scope", "basic_reference", "basic_evidence", "files", "plan_hash"}
            or len(json.dumps(payload).encode()) > 256 * 1024
        ):
            raise EtfDailyContractError("etf_factor_completion_payload_invalid")
        result = cls(
            scope=payload["scope"],
            basic_reference=payload["basic_reference"],
            basic_evidence=payload["basic_evidence"],
            files=tuple(EtfFactorCompletionFile(**item) for item in payload["files"]),
        ).validate()
        if result.plan_hash != payload["plan_hash"]:
            raise EtfDailyContractError("etf_factor_completion_plan_hash_invalid")
        return result
