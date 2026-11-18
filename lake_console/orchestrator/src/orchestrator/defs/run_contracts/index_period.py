"""主要指数周线、月线的固定身份、时间输入及写入范围。"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import dagster as dg
from pydantic import ConfigDict, model_validator

from orchestrator.seeds.market.major_indices import load_major_indices_seed

INDEX_WEEK_PARTITIONS = "cn_a_index_week_ends"
INDEX_MONTH_PARTITIONS = "cn_a_index_months"
INDEX_PERIOD_TIMEZONE = "Asia/Shanghai"
INDEX_PERIOD_START_HOUR = 19
INDEX_PERIOD_TICK_SECONDS = 600
INDEX_PERIOD_EMPTY_SOURCE_CODE = "899050.BJ"
INDEX_PERIOD_PROBE_CODE = "000001.SH"
INDEX_PERIOD_BOOTSTRAP_JOB_NAME = "index_period_history_bootstrap_job"


@dataclass(frozen=True)
class IndexPeriod:
    dataset_id: str
    frequency: str
    partition_set: str
    source_doc: str

    @property
    def raw_asset(self) -> str:
        return f"raw_{self.dataset_id}"

    @property
    def raw_check(self) -> str:
        return f"{self.raw_asset}_file_contract_check"

    @property
    def raw_contract(self) -> str:
        return f"{self.dataset_id}_raw_v1"

    @property
    def silver_asset(self) -> str:
        return f"silver_{self.dataset_id}"

    @property
    def silver_check(self) -> str:
        return f"{self.silver_asset}_file_contract_check"

    @property
    def silver_contract(self) -> str:
        return f"{self.dataset_id}_silver_v1"


class IndexPeriodSilverConfig(dg.Config):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["daily", "period", "repair"]
    trade_date: str | None = None

    @model_validator(mode="after")
    def validate_time_input(self):
        if self.mode == "daily":
            if (
                self.trade_date is None
                or date.fromisoformat(self.trade_date).isoformat() != self.trade_date
            ):
                raise ValueError("日更必须指定 YYYY-MM-DD 的 trade_date")
        elif self.trade_date is not None:
            raise ValueError("period／repair 从所选分区确定期末，不允许额外 trade_date")
        return self


INDEX_WEEKLY = IndexPeriod(
    "index_weekly",
    "week",
    INDEX_WEEK_PARTITIONS,
    "https://tushare.pro/document/2?doc_id=171",
)
INDEX_MONTHLY = IndexPeriod(
    "index_monthly",
    "month",
    INDEX_MONTH_PARTITIONS,
    "https://tushare.pro/document/2?doc_id=172",
)


def index_period_codes() -> tuple[str, ...]:
    """只取既有名单的代码；日线 seed 起点不用于周期行情。"""
    return tuple(row.ts_code for row in load_major_indices_seed())


def build_index_period_silver_run_config(period, config: IndexPeriodSilverConfig):
    return {"ops": {period.silver_asset: {"config": config.model_dump(exclude_none=True)}}}


def index_period_bounds(period: IndexPeriod, partition_key: str) -> tuple[date, date]:
    if period == INDEX_WEEKLY:
        day = date.fromisoformat(partition_key)
        if day.isoformat() != partition_key:
            raise ValueError("周分区必须为 YYYY-MM-DD")
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    if period != INDEX_MONTHLY:
        raise ValueError("只支持指数周线、月线")
    start = date.fromisoformat(f"{partition_key}-01")
    if start.strftime("%Y-%m") != partition_key:
        raise ValueError("月分区必须为 YYYY-MM")
    following = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, following - timedelta(days=1)
