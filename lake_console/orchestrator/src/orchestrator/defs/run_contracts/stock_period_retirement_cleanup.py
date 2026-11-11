"""Single-frequency retirement cleanup inputs; no persisted progress."""

from typing import ClassVar, Literal

import dagster as dg

from orchestrator.defs.run_contracts.stock_period_delivery import (
    iso_business_date,
    validate_delivery_ref,
)
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash,
)

JOB_NAME = "raw_stock_period_retirement_cleanup_job"
OP_NAME = "raw_stock_period_retirement_cleanup_op"


class StockPeriodRetirementCleanupConfig(dg.Config):
    model_config: ClassVar[dict[str, str]] = {"extra": "forbid"}
    business_date: str
    freq: Literal["week", "month"]
    stock_codes: list[str]
    codes_hash: str
    source_completion: dict[str, str]

    def validate_intent(self):
        iso_business_date(self.business_date)
        codes = sorted({code.strip().upper() for code in self.stock_codes})
        if (
            codes != self.stock_codes
            or gold_stock_daily_qfq_factor_repair_codes_hash(codes) != self.codes_hash
        ):
            raise ValueError("period_retirement_codes_hash_mismatch")
        validate_delivery_ref(self.source_completion, self.freq)


def retirement_result_check_name(freq):
    from orchestrator.defs.run_contracts.stock_period import frequency

    return f"raw_tushare_stk_period_bar_adj_{frequency(freq)}_retirement_cleanup_result_check"


def build_retirement_run_config(config):
    config.validate_intent()
    return {"ops": {OP_NAME: {"config": config.model_dump()}}}
