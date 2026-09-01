"""Typed config helpers for Dagster run configuration."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from datetime import time as datetime_time
from typing import Literal

import dagster as dg
from pydantic import Field

from orchestrator.defs.run_contracts.stk_mins import ProdStkMinsCompletionReference


class IndexDailyRawConfig(dg.Config):
    write_mode: Literal["replace"] = Field(
        default="replace",
        description="指数日线 raw-by-date 写入模式；当前只允许替换写入。",
    )


class DcBoardIndexSourceSnapshotConfig(dg.Config):
    trade_date: str = Field(
        description="本次 DC Tushare 源快照对应的交易日，格式 YYYY-MM-DD。",
    )
    prod_completion_observed_at: str = Field(
        description="第二次稳定 prod 完成快照的带时区 ISO-8601 观测时间。",
    )
    prod_completion_fingerprint: str = Field(
        description="稳定 prod 完成快照的 lowercase SHA-256。",
    )
    tushare_source_observed_at: str = Field(
        description="本次已确认 Tushare 业务源快照的带时区 ISO-8601 观测时间。",
    )
    tushare_source_fingerprint: str = Field(
        description="完整 Tushare index/daily 业务行的 lowercase SHA-256。",
    )


class DcIndustryHierarchyConfig(dg.Config):
    reference_trade_date: str = Field(
        description="补齐行业 BK 代码所用 silver_dc_index 交易日，格式 YYYY-MM-DD。",
    )


class GoldStockDailyQfqFactorRepairConfig(dg.Config):
    qfq_factor_trade_date: str = Field(
        description="股票日线前复权 repair 的复权因子交易日，格式 YYYY-MM-DD。",
    )
    repair_required_codes_hash: str = Field(
        description="由相邻 expected trade date 的 silver_adj_factor diff 得到的 affected code 集合 SHA-256。",
    )
    upstream_batch_id: str = Field(
        description="触发本次 repair 的上游 daily qfq run batch id。",
    )


class GoldStockDailyTrendChannelRepairConfig(dg.Config):
    qfq_factor_repair_trade_date: str = Field(
        description="触发趋势通道 repair 的 qfq 因子交易日，格式 YYYY-MM-DD。",
    )
    repair_start_trade_date: str = Field(
        description="趋势通道从该交易日开始重算，格式 YYYY-MM-DD。",
    )
    repair_end_trade_date: str = Field(
        description="趋势通道重算到该交易日，格式 YYYY-MM-DD。",
    )
    stock_codes: list[str] = Field(
        description="来自 qfq repair completion metadata 的完整受影响股票代码。",
    )
    repair_required_codes_hash: str = Field(
        description="完整受影响股票代码集合的 SHA-256。",
    )
    source_upstream_batch_id: str = Field(
        description="触发本次趋势修复的 qfq repair exact upstream batch id。",
    )


StockMinsRawSource = Literal["tushare", "prod_db"]
StockMinsRawWriteMode = Literal["reuse_existing", "merge_repair"]
StockMinsSilverWriteMode = Literal["write_new", "reuse_existing"]
StockDailyRawWriteMode = Literal["full_day", "missing_code_repair"]
MAX_STOCK_DAILY_MISSING_CODE_REPAIR_COUNT = 100


@dataclass(frozen=True)
class StockMinsMergeRepairConfig:
    stock_codes: tuple[str, ...]
    start_time: str
    end_time: str


@dataclass(frozen=True)
class ParsedStockMinsRawConfig:
    source: StockMinsRawSource
    write_mode: StockMinsRawWriteMode
    merge_repair: StockMinsMergeRepairConfig | None = None
    prod_completion_reference: ProdStkMinsCompletionReference | None = None

    def validate(self) -> "ParsedStockMinsRawConfig":
        if self.write_mode == "merge_repair":
            if self.source != "tushare" or self.merge_repair is None:
                raise ValueError("merge_repair write_mode only supports source=tushare.")
            if self.prod_completion_reference is not None:
                raise ValueError(
                    "merge_repair must not carry prod_completion_reference."
                )
            start_time = _parse_hms_time(self.merge_repair.start_time)
            end_time = _parse_hms_time(self.merge_repair.end_time)
            if start_time > end_time:
                raise ValueError(
                    "merge_repair.start_time must not be later than end_time."
                )
            return self
        if self.source == "prod_db" and self.prod_completion_reference is None:
            raise ValueError(
                "source=prod_db reuse_existing requires prod_completion_reference."
            )
        if self.source != "prod_db" and self.prod_completion_reference is not None:
            raise ValueError(
                "prod_completion_reference is only valid for source=prod_db."
            )
        return self


@dataclass(frozen=True)
class ParsedStockMinsSilverConfig:
    write_mode: StockMinsSilverWriteMode


@dataclass(frozen=True)
class StockDailyMissingCodeRepairConfig:
    ts_codes: tuple[str, ...]
    missing_codes_hash: str
    repair_attempt: int


@dataclass(frozen=True)
class ParsedStockDailyRawConfig:
    write_mode: StockDailyRawWriteMode
    missing_code_repair: StockDailyMissingCodeRepairConfig | None = None


STOCK_DAILY_RAW_CONFIG_SCHEMA = dg.Shape(
    {
        "write_mode": dg.Field(
            dg.Selector(
                {
                    "full_day": dg.Field(
                        dg.Shape({}),
                        default_value={},
                        is_required=False,
                        description="日常全交易日 raw 更新模式。",
                    ),
                    "missing_code_repair": dg.Field(
                        dg.Shape(
                            {
                                "ts_codes": dg.Field(
                                    [str],
                                    description=(
                                        "本次补拉的股票代码列表，不能为空，最多 100 个。"
                                    ),
                                ),
                                "missing_codes_hash": dg.Field(
                                    str,
                                    description="sensor 对完整 missing code 集合计算出的稳定 hash。",
                                ),
                                "repair_attempt": dg.Field(
                                    int,
                                    description="同一 trade_date + missing hash 的 repair 尝试次数。",
                                ),
                            }
                        ),
                        description="股票日线 raw missing-code 受控修复模式。",
                    ),
                }
            ),
            default_value={"full_day": {}},
            is_required=False,
            description="股票日线 raw 写入模式；full_day 与 missing_code_repair 互斥。",
        ),
    }
)


STOCK_MINS_RAW_CONFIG_SCHEMA = dg.Shape(
    {
        "source": dg.Field(
            dg.Enum(
                "StockMinsRawSource",
                [
                    dg.EnumValue("tushare"),
                    dg.EnumValue("prod_db"),
                ],
            ),
            default_value="prod_db",
            is_required=False,
            description=(
                "股票分钟线 raw 写入来源；默认使用 prod DB，Tushare source "
                "保留为显式人工备用入口和 merge_repair 修复入口。"
            ),
        ),
        "write_mode": dg.Field(
            dg.Selector(
                {
                    "reuse_existing": dg.Field(
                        dg.Shape({}),
                        default_value={},
                        is_required=False,
                        description="日常安全模式：已有合格 raw 文件直接复用。",
                    ),
                    "merge_repair": dg.Field(
                        dg.Shape(
                            {
                                "stock_codes": dg.Field(
                                    [str],
                                    description="需要人工修复的股票代码列表，不能为空。",
                                ),
                                "start_time": dg.Field(
                                    str,
                                    description="修复窗口开始时间，格式 HH:MM:SS。",
                                ),
                                "end_time": dg.Field(
                                    str,
                                    description="修复窗口结束时间，格式 HH:MM:SS。",
                                ),
                            }
                        ),
                        description="Tushare 受控修复模式，只替换或追加返回的分钟键。",
                    ),
                }
            ),
            default_value={"reuse_existing": {}},
            is_required=False,
            description="股票分钟线 raw 写入模式；reuse_existing 与 merge_repair 互斥。",
        ),
        "prod_completion_reference": dg.Field(
            dg.Shape(
                {
                    "task_run_id": dg.Field(int),
                    "trade_date": dg.Field(str),
                    "ended_at": dg.Field(str),
                    "full_market": dg.Field(bool),
                    "frequency_set_hash": dg.Field(str),
                    "expected_code_count": dg.Field(int),
                    "expected_code_hash": dg.Field(str),
                    "frequency_code_counts": dg.Field(
                        dg.Shape(
                            {
                                "1": dg.Field(int),
                                "5": dg.Field(int),
                                "15": dg.Field(int),
                                "30": dg.Field(int),
                                "60": dg.Field(int),
                            }
                        )
                    ),
                    "coverage_observed_at": dg.Field(str),
                    "reference_fingerprint": dg.Field(str),
                }
            ),
            is_required=False,
            description=(
                "仅 prod_db 全日更新使用的最小完成依据；必须由 raw sensor 构造，"
                "不包含代码列表或 TaskRun JSON。"
            ),
        ),
    }
)


STOCK_MINS_SILVER_CONFIG_SCHEMA = dg.Shape(
    {
        "write_mode": dg.Field(
            dg.Selector(
                {
                    "write_new": dg.Field(
                        dg.Shape({}),
                        default_value={},
                        is_required=False,
                        description="默认安全模式：目标文件已存在时拒绝覆盖。",
                    ),
                    "reuse_existing": dg.Field(
                        dg.Shape({}),
                        default_value={},
                        is_required=False,
                        description=(
                            "仅用于受控恢复后的 Dagster 状态复核：只读取既有 Silver 文件，"
                            "不改写 Parquet。"
                        ),
                    ),
                }
            ),
            default_value={"write_new": {}},
            is_required=False,
            description="股票分钟线 Silver 写入模式；两个分支互斥。",
        )
    }
)


STOCK_MINS_RAW_ASSET_OP_NAMES = (
    "raw_stk_mins_1m",
    "raw_stk_mins_5m",
    "raw_stk_mins_15m",
    "raw_stk_mins_30m",
    "raw_stk_mins_60m",
)

STOCK_MINS_SILVER_ASSET_OP_NAMES = (
    "silver_stk_mins_1m",
    "silver_stk_mins_5m",
    "silver_stk_mins_15m",
    "silver_stk_mins_30m",
    "silver_stk_mins_60m",
)


def normalize_iso_trade_date(value: str, *, field_name: str = "trade_date") -> str:
    stripped = value.strip()
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from error
    if parsed < datetime.strptime("2000-01-01", "%Y-%m-%d").date():
        raise ValueError(f"{field_name} must not be earlier than 2000-01-01.")
    return parsed.isoformat()


def build_raw_index_daily_update_job_run_config(
    *,
    partition_key: str,
    write_mode: Literal["replace"] = "replace",
) -> dict[str, object]:
    normalize_iso_trade_date(partition_key, field_name="partition_key")
    return {
        "ops": {
            "raw_index_daily": {
                "config": {
                    "write_mode": write_mode,
                }
            }
        }
    }


def build_silver_dc_industry_hierarchy_update_job_run_config(
    *,
    reference_trade_date: str,
) -> dict[str, object]:
    normalized_reference_trade_date = normalize_iso_trade_date(
        reference_trade_date,
        field_name="reference_trade_date",
    )
    return {
        "ops": {
            "silver_dc_industry_hierarchy": {
                "config": {
                    "reference_trade_date": normalized_reference_trade_date,
                }
            }
        }
    }


def build_raw_dc_index_update_job_run_config(
    *,
    partition_key: str,
    trade_date: str,
    prod_completion_observed_at: str,
    prod_completion_fingerprint: str,
    tushare_source_observed_at: str,
    tushare_source_fingerprint: str,
) -> dict[str, object]:
    normalized_partition_key = normalize_iso_trade_date(
        partition_key,
        field_name="partition_key",
    )
    normalized_trade_date = normalize_iso_trade_date(
        trade_date,
        field_name="trade_date",
    )
    if normalized_trade_date != normalized_partition_key:
        raise ValueError("trade_date must equal partition_key.")
    normalized_prod_completion_observed_at = _normalize_reference_observed_at(
        prod_completion_observed_at,
    )
    normalized_prod_completion_fingerprint = _normalize_sha256_hex(
        prod_completion_fingerprint,
        field_name="prod_completion_fingerprint",
    )
    normalized_tushare_source_observed_at = _normalize_reference_observed_at(
        tushare_source_observed_at,
    )
    normalized_tushare_source_fingerprint = _normalize_sha256_hex(
        tushare_source_fingerprint,
        field_name="tushare_source_fingerprint",
    )
    return {
        "ops": {
            "raw_tushare_dc_index": {
                "config": {
                    "trade_date": normalized_trade_date,
                    "prod_completion_observed_at": normalized_prod_completion_observed_at,
                    "prod_completion_fingerprint": normalized_prod_completion_fingerprint,
                    "tushare_source_observed_at": normalized_tushare_source_observed_at,
                    "tushare_source_fingerprint": normalized_tushare_source_fingerprint,
                }
            }
        }
    }


def validate_dc_board_index_source_snapshot_config(
    config: DcBoardIndexSourceSnapshotConfig,
    *,
    partition_key: str,
) -> DcBoardIndexSourceSnapshotConfig:
    build_raw_dc_index_update_job_run_config(
        partition_key=partition_key,
        trade_date=config.trade_date,
        prod_completion_observed_at=config.prod_completion_observed_at,
        prod_completion_fingerprint=config.prod_completion_fingerprint,
        tushare_source_observed_at=config.tushare_source_observed_at,
        tushare_source_fingerprint=config.tushare_source_fingerprint,
    )
    return config


def build_stock_daily_raw_repair_run_config(
    *,
    ts_codes: Sequence[str],
    missing_codes_hash: str,
    repair_attempt: int,
) -> dict[str, object]:
    repair_config = StockDailyMissingCodeRepairConfig(
        ts_codes=_normalize_stock_daily_repair_ts_codes(ts_codes),
        missing_codes_hash=_normalize_missing_codes_hash(missing_codes_hash),
        repair_attempt=_normalize_repair_attempt(repair_attempt),
    )
    return {
        "ops": {
            "raw_tushare_stock_daily": {
                "config": {
                    "write_mode": {
                        "missing_code_repair": {
                            "ts_codes": list(repair_config.ts_codes),
                            "missing_codes_hash": repair_config.missing_codes_hash,
                            "repair_attempt": repair_config.repair_attempt,
                        }
                    }
                }
            }
        }
    }


def build_gold_stock_daily_qfq_factor_repair_run_config(
    *,
    qfq_factor_trade_date: str,
    repair_required_codes_hash: str,
    upstream_batch_id: str,
) -> dict[str, object]:
    repair_config = GoldStockDailyQfqFactorRepairConfig(
        qfq_factor_trade_date=normalize_iso_trade_date(
            qfq_factor_trade_date,
            field_name="qfq_factor_trade_date",
        ),
        repair_required_codes_hash=_normalize_sha256_hex(
            repair_required_codes_hash,
            field_name="repair_required_codes_hash",
        ),
        upstream_batch_id=_normalize_required_text(
            upstream_batch_id,
            field_name="upstream_batch_id",
        ),
    )
    return {
        "ops": {
            "gold_stock_daily_qfq_factor_repair_op": {
                "config": {
                    "qfq_factor_trade_date": repair_config.qfq_factor_trade_date,
                    "repair_required_codes_hash": (
                        repair_config.repair_required_codes_hash
                    ),
                    "upstream_batch_id": repair_config.upstream_batch_id,
                }
            }
        }
    }


def build_gold_stock_daily_trend_channel_repair_run_config(
    *,
    qfq_factor_repair_trade_date: str,
    repair_start_trade_date: str,
    repair_end_trade_date: str,
    stock_codes: Sequence[str],
    repair_required_codes_hash: str,
    source_upstream_batch_id: str,
) -> dict[str, object]:
    normalized_codes = tuple(str(item).strip().upper() for item in stock_codes)
    if (
        not normalized_codes
        or any(not item for item in normalized_codes)
        or normalized_codes != tuple(sorted(set(normalized_codes)))
    ):
        raise ValueError(
            "stock_codes must be a non-empty, sorted and unique code list."
        )
    repair_config = GoldStockDailyTrendChannelRepairConfig(
        qfq_factor_repair_trade_date=normalize_iso_trade_date(
            qfq_factor_repair_trade_date,
            field_name="qfq_factor_repair_trade_date",
        ),
        repair_start_trade_date=normalize_iso_trade_date(
            repair_start_trade_date,
            field_name="repair_start_trade_date",
        ),
        repair_end_trade_date=normalize_iso_trade_date(
            repair_end_trade_date,
            field_name="repair_end_trade_date",
        ),
        stock_codes=list(normalized_codes),
        repair_required_codes_hash=_normalize_sha256_hex(
            repair_required_codes_hash,
            field_name="repair_required_codes_hash",
        ),
        source_upstream_batch_id=_normalize_required_text(
            source_upstream_batch_id,
            field_name="source_upstream_batch_id",
        ),
    )
    return {
        "ops": {
            "gold_stock_daily_trend_channel_repair_op": {
                "config": {
                    "qfq_factor_repair_trade_date": (
                        repair_config.qfq_factor_repair_trade_date
                    ),
                    "repair_start_trade_date": repair_config.repair_start_trade_date,
                    "repair_end_trade_date": repair_config.repair_end_trade_date,
                    "stock_codes": repair_config.stock_codes,
                    "repair_required_codes_hash": (
                        repair_config.repair_required_codes_hash
                    ),
                    "source_upstream_batch_id": (
                        repair_config.source_upstream_batch_id
                    ),
                }
            }
        }
    }


def build_stock_mins_raw_update_job_run_config(
    *,
    source: StockMinsRawSource,
    prod_completion_reference: ProdStkMinsCompletionReference | None = None,
) -> dict[str, object]:
    normalized_source = _normalize_stock_mins_raw_source(source)
    reference_config = (
        prod_completion_reference.to_config_dict()
        if prod_completion_reference is not None
        else None
    )
    return {
        "ops": {
            op_name: {
                "config": {
                    "source": normalized_source,
                    "write_mode": {
                        "reuse_existing": {},
                    },
                    **(
                        {"prod_completion_reference": reference_config}
                        if reference_config is not None
                        else {}
                    ),
                }
            }
            for op_name in STOCK_MINS_RAW_ASSET_OP_NAMES
        }
    }


def build_stock_mins_silver_reuse_existing_run_config() -> dict[str, object]:
    """Build the explicit no-write config used after offline Silver recovery."""

    return {
        "ops": {
            op_name: {"config": {"write_mode": {"reuse_existing": {}}}}
            for op_name in STOCK_MINS_SILVER_ASSET_OP_NAMES
        }
    }


def parse_stock_daily_raw_config(
    raw_config: Mapping[str, object] | None,
) -> ParsedStockDailyRawConfig:
    config = dict(raw_config or {})
    write_mode_config = config.get("write_mode", {"full_day": {}})
    if not isinstance(write_mode_config, Mapping):
        raise ValueError("write_mode must be a selector mapping.")

    selected_modes = [
        mode
        for mode in ("full_day", "missing_code_repair")
        if mode in write_mode_config
    ]
    if len(selected_modes) != 1:
        raise ValueError("write_mode must select exactly one branch.")

    write_mode = selected_modes[0]
    if write_mode == "full_day":
        return ParsedStockDailyRawConfig(write_mode="full_day")

    repair_config = write_mode_config["missing_code_repair"]
    if not isinstance(repair_config, Mapping):
        raise ValueError("missing_code_repair config must be a mapping.")

    return ParsedStockDailyRawConfig(
        write_mode="missing_code_repair",
        missing_code_repair=StockDailyMissingCodeRepairConfig(
            ts_codes=_normalize_stock_daily_repair_ts_codes(
                repair_config.get("ts_codes")
            ),
            missing_codes_hash=_normalize_missing_codes_hash(
                repair_config.get("missing_codes_hash")
            ),
            repair_attempt=_normalize_repair_attempt(
                repair_config.get("repair_attempt")
            ),
        ),
    )


def parse_stock_mins_raw_config(
    raw_config: Mapping[str, object] | None,
) -> ParsedStockMinsRawConfig:
    config = dict(raw_config or {})
    source = _normalize_stock_mins_raw_source(config.get("source", "prod_db"))
    prod_completion_reference = (
        ProdStkMinsCompletionReference.from_config_mapping(
            config.get("prod_completion_reference")
        )
        if "prod_completion_reference" in config
        else None
    )
    write_mode_config = config.get("write_mode", {"reuse_existing": {}})
    if not isinstance(write_mode_config, Mapping):
        raise ValueError("write_mode must be a selector mapping.")

    selected_modes = [
        mode for mode in ("reuse_existing", "merge_repair") if mode in write_mode_config
    ]
    if len(selected_modes) != 1:
        raise ValueError("write_mode must select exactly one branch.")

    write_mode = selected_modes[0]
    if write_mode == "reuse_existing":
        return ParsedStockMinsRawConfig(
            source=source,
            write_mode="reuse_existing",
            prod_completion_reference=prod_completion_reference,
        ).validate()

    repair_config = write_mode_config["merge_repair"]
    if source != "tushare":
        raise ValueError("merge_repair write_mode only supports source=tushare.")
    if not isinstance(repair_config, Mapping):
        raise ValueError("merge_repair config must be a mapping.")

    return ParsedStockMinsRawConfig(
        source=source,
        write_mode="merge_repair",
        merge_repair=StockMinsMergeRepairConfig(
            stock_codes=_normalize_repair_stock_codes(repair_config.get("stock_codes")),
            start_time=_normalize_hms_time(
                repair_config.get("start_time"),
                field_name="start_time",
            ),
            end_time=_normalize_hms_time(
                repair_config.get("end_time"),
                field_name="end_time",
            ),
        ),
        prod_completion_reference=prod_completion_reference,
    ).validate()


def parse_stock_mins_silver_config(
    raw_config: Mapping[str, object] | None,
) -> ParsedStockMinsSilverConfig:
    config = dict(raw_config or {})
    write_mode_config = config.get("write_mode", {"write_new": {}})
    if not isinstance(write_mode_config, Mapping):
        raise ValueError("write_mode must be a selector mapping.")

    selected_modes = [
        mode for mode in ("write_new", "reuse_existing") if mode in write_mode_config
    ]
    if len(selected_modes) != 1:
        raise ValueError("write_mode must select exactly one branch.")
    return ParsedStockMinsSilverConfig(write_mode=selected_modes[0])


def _normalize_stock_mins_raw_source(value: object) -> StockMinsRawSource:
    source = str(value or "").strip().lower()
    if source not in {"tushare", "prod_db"}:
        raise ValueError("source must be one of: tushare, prod_db.")
    return source  # type: ignore[return-value]


def _normalize_repair_stock_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("merge_repair.stock_codes must be a non-empty list.")
    stock_codes = tuple(str(item).strip().upper() for item in value)
    if not stock_codes or any(not item for item in stock_codes):
        raise ValueError("merge_repair.stock_codes must be a non-empty list.")
    duplicate_codes = sorted(
        {stock_code for stock_code in stock_codes if stock_codes.count(stock_code) > 1}
    )
    if duplicate_codes:
        raise ValueError(
            f"merge_repair.stock_codes must not contain duplicates: {duplicate_codes}."
        )
    return stock_codes


def _normalize_stock_daily_repair_ts_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("missing_code_repair.ts_codes must be a non-empty list.")
    ts_codes = tuple(str(item).strip().upper() for item in value)
    if not ts_codes or any(not item for item in ts_codes):
        raise ValueError("missing_code_repair.ts_codes must be a non-empty list.")
    duplicate_codes = sorted(
        {ts_code for ts_code in ts_codes if ts_codes.count(ts_code) > 1}
    )
    if duplicate_codes:
        raise ValueError(
            "missing_code_repair.ts_codes must not contain duplicates: "
            f"{duplicate_codes}."
        )
    if len(ts_codes) > MAX_STOCK_DAILY_MISSING_CODE_REPAIR_COUNT:
        raise ValueError(
            "missing_code_repair.ts_codes must not contain more than "
            f"{MAX_STOCK_DAILY_MISSING_CODE_REPAIR_COUNT} codes."
        )
    return ts_codes


def _normalize_missing_codes_hash(value: object) -> str:
    return _normalize_sha256_hex(
        value,
        field_name="missing_code_repair.missing_codes_hash",
    )


def _normalize_reference_observed_at(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(
            "reference_observed_at must be a non-empty ISO-8601 timestamp."
        )
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "reference_observed_at must be an ISO-8601 timestamp."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("reference_observed_at must include a timezone offset.")
    return parsed.isoformat()


def _normalize_sha256_hex(value: object, *, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError(f"{field_name} is required.")
    if len(text) != 64:
        raise ValueError(f"{field_name} must be a SHA-256 hex string.")
    if any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field_name} must be a lowercase hex string.")
    return text


def _normalize_required_text(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _normalize_repair_attempt(value: object) -> int:
    try:
        attempt = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "missing_code_repair.repair_attempt must be an integer."
        ) from error
    if attempt <= 0:
        raise ValueError("missing_code_repair.repair_attempt must be positive.")
    return attempt


def _normalize_hms_time(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M:%S").time()
    except ValueError as error:
        raise ValueError(f"{field_name} must use HH:MM:SS format.") from error
    return parsed.isoformat()


def _parse_hms_time(value: str) -> datetime_time:
    return datetime.strptime(value, "%H:%M:%S").time()
