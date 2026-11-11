"""Explicit factor-change repair inputs and stable upstream identity."""

import re
from datetime import date, datetime
from typing import ClassVar, Literal
from zoneinfo import ZoneInfo

import dagster as dg
from pydantic import Field

from orchestrator.defs.run_contracts.run_keys import build_batch_id
from orchestrator.defs.run_contracts.stock_period import digest, source_period
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
    intent: Literal["factor_changed", "specified_history", "identity_maintenance"] = (
        "factor_changed"
    )
    business_date: str
    stock_codes: list[str]
    codes_hash: str
    frequencies: list[str]
    upstream_completions: list[dict[str, str]] = Field(default_factory=list)
    remove_keys: list[dict[str, str]] = Field(default_factory=list)

    @property
    def remove_keys_hash(self):
        return digest(self.remove_keys)

    def validate_intent(self):
        iso_business_date(self.business_date)
        if (
            self.business_date
            > datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        ):
            raise ValueError("period_repair_future_business_date")
        codes = sorted({code.strip().upper() for code in self.stock_codes})
        if (
            codes != self.stock_codes
            or any(re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", c) is None for c in codes)
            or gold_stock_daily_qfq_factor_repair_codes_hash(codes) != self.codes_hash
        ):
            raise ValueError("period_repair_codes_hash_mismatch")
        if self.intent == "factor_changed":
            if (
                self.frequencies != FREQUENCIES
                or len(self.upstream_completions) != 2
                or self.remove_keys
            ):
                raise ValueError("period_repair_frequencies_invalid")
            for freq, reference in zip(
                FREQUENCIES, self.upstream_completions, strict=True
            ):
                validate_delivery_ref(reference, freq)
        else:
            if (
                not self.frequencies
                or self.frequencies != [f for f in FREQUENCIES if f in self.frequencies]
                or self.upstream_completions
            ):
                raise ValueError("period_maintenance_frequencies_or_upstreams_invalid")
            if self.intent == "specified_history" and (not codes or self.remove_keys):
                raise ValueError("period_maintenance_history_scope_invalid")
            if self.intent == "identity_maintenance" and not self.remove_keys:
                raise ValueError("period_maintenance_remove_keys_required")
        if self.remove_keys != normalize_remove_keys(self.remove_keys):
            raise ValueError("period_maintenance_remove_keys_not_canonical")
        if any(key["freq"] not in self.frequencies for key in self.remove_keys):
            raise ValueError("period_maintenance_remove_key_frequency_invalid")


def normalize_remove_keys(keys):
    normalized = set()
    for key in keys:
        if set(key) != {"ts_code", "trade_date", "freq"} or not all(
            isinstance(v, str) for v in key.values()
        ):
            raise ValueError("period_maintenance_remove_key_invalid")
        code, day, freq = key["ts_code"].strip().upper(), key["trade_date"], key["freq"]
        if len(day) != 8 or not day.isdigit():
            raise ValueError("period_maintenance_remove_key_date_invalid")
        if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code):
            raise ValueError("period_maintenance_remove_key_code_invalid")
        date.fromisoformat(f"{day[:4]}-{day[4:6]}-{day[6:]}")
        source_period(day, freq)
        normalized.add((code, day, freq))
    return [
        {"ts_code": c, "trade_date": d, "freq": f}
        for c, d, f in sorted(
            normalized, key=lambda k: (FREQUENCIES.index(k[2]), k[1], k[0])
        )
    ]


def repair_upstream_batch_id(config):
    config.validate_intent()
    if config.intent != "factor_changed":
        raise ValueError("period_repair_automatic_intent_required")
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
