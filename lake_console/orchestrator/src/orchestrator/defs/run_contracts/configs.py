"""Typed config helpers for Dagster run configuration."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from datetime import time as datetime_time
from typing import Literal

import dagster as dg
from pydantic import Field


class IndexDailyRawByCodeConfig(dg.Config):
    trade_date: str = Field(description="指数日线 raw-by-code 本次更新的目标交易日，格式 YYYY-MM-DD。")
    write_mode: Literal["replace"] = Field(
        default="replace",
        description="指数日线 raw-by-code 写入模式；当前只允许替换写入。",
    )


StockMinsRawSource = Literal["tushare", "prod_db"]
StockMinsRawWriteMode = Literal["reuse_existing", "merge_repair"]


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


def build_index_daily_raw_op_config(config: IndexDailyRawByCodeConfig) -> dict[str, object]:
    normalized_trade_date = normalize_iso_trade_date(config.trade_date)
    return {
        "ops": {
            "raw_tushare_index_daily_by_code": {
                "config": {
                    "trade_date": normalized_trade_date,
                    "write_mode": config.write_mode,
                }
            }
        }
    }


def build_index_daily_update_job_run_config(
    *,
    trade_date: str,
    write_mode: Literal["replace"] = "replace",
) -> dict[str, object]:
    return build_index_daily_raw_op_config(
        IndexDailyRawByCodeConfig(
            trade_date=trade_date,
            write_mode=write_mode,
        )
    )


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


def _normalize_hms_time(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M:%S").time()
    except ValueError as error:
        raise ValueError(f"{field_name} must use HH:MM:SS format.") from error
    return parsed.isoformat()


def _parse_hms_time(value: str) -> datetime_time:
    return datetime.strptime(value, "%H:%M:%S").time()
