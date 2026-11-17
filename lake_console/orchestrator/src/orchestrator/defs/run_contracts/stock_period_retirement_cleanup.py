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

JOB_NAME = "silver_stock_period_retirement_cleanup_job"
OP_NAME = "silver_stock_period_retirement_cleanup_op"
WORK_KEY = "goldenshare/silver_retirement_work"
RESULT_KEY = "goldenshare/silver_retirement_result"
WORK_VERSION = "stock-period-silver-retirement-work@1"
RESULT_VERSION = "stock-period-silver-retirement-result@1"


class StockPeriodRetirementCleanupConfig(dg.Config):
    model_config: ClassVar[dict[str, str]] = {"extra": "forbid"}
    business_date: str
    freq: Literal["week", "month"]
    stock_codes: list[str]
    codes_hash: str
    source_completion: dict[str, str]
    source_silver_run_id: str

    def validate_intent(self):
        iso_business_date(self.business_date)
        codes = sorted({code.strip().upper() for code in self.stock_codes})
        if (
            codes != self.stock_codes
            or gold_stock_daily_qfq_factor_repair_codes_hash(codes) != self.codes_hash
        ):
            raise ValueError("period_retirement_codes_hash_mismatch")
        validate_delivery_ref(self.source_completion, self.freq)
        from orchestrator.defs.run_contracts.stock_period_silver import canonical_run_id

        canonical_run_id(self.source_silver_run_id)


def build_retirement_run_config(config):
    config.validate_intent()
    return {"ops": {OP_NAME: {"config": config.model_dump()}}}
