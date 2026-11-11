"""Explicit factor-change repair inputs and stable upstream identity."""

from typing import ClassVar, Literal

import dagster as dg

from orchestrator.defs.run_contracts.run_keys import build_batch_id
from orchestrator.defs.run_contracts.stock_period_delivery import (
    iso_business_date,
    validate_delivery_ref,
)
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash,
)

JOB_NAME = "raw_stock_period_history_repair_job"
OP_NAME = "raw_stock_period_history_repair_op"
FREQUENCIES = ["week", "month"]


class StockPeriodHistoryRepairConfig(dg.Config):
    model_config: ClassVar[dict[str, str]] = {"extra": "forbid"}
    intent: Literal["factor_changed"] = "factor_changed"
    business_date: str
    stock_codes: list[str]
    codes_hash: str
    frequencies: list[str]
    upstream_completions: list[dict[str, str]]

    def validate_intent(self):
        iso_business_date(self.business_date)
        codes = sorted({code.strip().upper() for code in self.stock_codes})
        if (
            codes != self.stock_codes
            or gold_stock_daily_qfq_factor_repair_codes_hash(codes) != self.codes_hash
        ):
            raise ValueError("period_repair_codes_hash_mismatch")
        if self.frequencies != FREQUENCIES or len(self.upstream_completions) != 2:
            raise ValueError("period_repair_frequencies_invalid")
        for freq, reference in zip(FREQUENCIES, self.upstream_completions, strict=True):
            validate_delivery_ref(reference, freq)


def repair_upstream_batch_id(config):
    config.validate_intent()
    return build_batch_id(
        producer="stock_period_factor_inputs",
        scope=config.business_date,
        payload={
            "producer_run_id": config.upstream_completions[0]["producer_run_id"],
            "upstream_completions": config.upstream_completions,
            "codes_hash": config.codes_hash,
        },
    )


def build_history_repair_run_config(config):
    config.validate_intent()
    return {"ops": {OP_NAME: {"config": config.model_dump()}}}
