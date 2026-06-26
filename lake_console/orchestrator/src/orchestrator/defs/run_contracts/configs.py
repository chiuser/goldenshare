"""Typed config helpers for Dagster run configuration."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from datetime import time as datetime_time
from typing import Literal

import dagster as dg
from pydantic import Field


class IndexDailyRawConfig(dg.Config):
    write_mode: Literal["replace"] = Field(
        default="replace",
        description="指数日线 raw-by-date 写入模式；当前只允许替换写入。",
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


StockMinsRawSource = Literal["tushare", "prod_db"]
StockMinsRawWriteMode = Literal["reuse_existing", "merge_repair"]
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

    def validate(self) -> "ParsedStockMinsRawConfig":
        if self.merge_repair is None:
            return self
        start_time = _parse_hms_time(self.merge_repair.start_time)
        end_time = _parse_hms_time(self.merge_repair.end_time)
        if start_time > end_time:
            raise ValueError("merge_repair.start_time must not be later than end_time.")
        return self


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
            default_value="tushare",
            is_required=False,
            description=(
                "股票分钟线 raw 写入来源；默认日常 sensor 使用 prod DB job，"
                "Tushare source 保留为人工备用入口和 merge_repair 修复入口。"
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
    }
)


STOCK_MINS_RAW_ASSET_OP_NAMES = (
    "raw_stk_mins_1m",
    "raw_stk_mins_5m",
    "raw_stk_mins_15m",
    "raw_stk_mins_30m",
    "raw_stk_mins_60m",
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


def build_stock_mins_raw_update_job_run_config(
    *,
    source: StockMinsRawSource,
) -> dict[str, object]:
    normalized_source = _normalize_stock_mins_raw_source(source)
    return {
        "ops": {
            op_name: {
                "config": {
                    "source": normalized_source,
                    "write_mode": {
                        "reuse_existing": {},
                    },
                }
            }
            for op_name in STOCK_MINS_RAW_ASSET_OP_NAMES
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
    source = _normalize_stock_mins_raw_source(config.get("source", "tushare"))
    write_mode_config = config.get("write_mode", {"reuse_existing": {}})
    if not isinstance(write_mode_config, Mapping):
        raise ValueError("write_mode must be a selector mapping.")

    selected_modes = [
        mode
        for mode in ("reuse_existing", "merge_repair")
        if mode in write_mode_config
    ]
    if len(selected_modes) != 1:
        raise ValueError("write_mode must select exactly one branch.")

    write_mode = selected_modes[0]
    if write_mode == "reuse_existing":
        return ParsedStockMinsRawConfig(
            source=source,
            write_mode="reuse_existing",
        )

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
    ).validate()


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
            "merge_repair.stock_codes must not contain duplicates: "
            f"{duplicate_codes}."
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
