"""Typed config helpers for Dagster run configuration."""

from datetime import datetime
from typing import Literal

import dagster as dg
from pydantic import Field


class IndexDailyRawByCodeConfig(dg.Config):
    trade_date: str = Field(description="指数日线 raw-by-code 本次更新的目标交易日，格式 YYYY-MM-DD。")
    write_mode: Literal["replace"] = Field(
        default="replace",
        description="指数日线 raw-by-code 写入模式；当前只允许替换写入。",
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
