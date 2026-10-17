"""Source-preserving period Silver contracts; no source requests or file writes."""

from datetime import date, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import dagster as dg

from orchestrator.defs.paths import (
    raw_stk_period_bar_adj_week_path,
    raw_stock_monthly_path,
    silver_stock_monthly_path,
    silver_stock_weekly_path,
)
from orchestrator.defs.run_contracts.stock_monthly import StockMonthlySource
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_column_specs,
)

VERSION = "stock-period-silver@1"
SPECS = tuple(
    (n, t) for n, t, _ in weekly_column_specs(StockWeeklySource.PRIMARY_ADJUSTED)
)
FIELDS = tuple(n for n, _ in SPECS)
COLUMNS = ",".join(f'"{n}"' for n in FIELDS)
CHECK_KINDS = ("file_contract", "key_partition", "source_projection")


class StockPeriodSilverConfig(dg.Config):
    execution_id: str
    intent: Literal["bootstrap", "update"] = "bootstrap"
    audit_report: str | None = None
    source_completion: dict[str, str] | None = None
    resume_from_execution_id: str | None = None

    def validate_intent(self, freq):
        from orchestrator.defs.run_contracts.stock_period import (
            validate_completion_reference,
        )

        canonical_run_id(self.execution_id)
        if self.resume_from_execution_id is not None:
            canonical_run_id(self.resume_from_execution_id)
            if self.resume_from_execution_id == self.execution_id:
                raise ValueError("silver_recovery_self_reference")
        if self.intent == "bootstrap":
            if (
                not self.audit_report
                or self.source_completion is not None
                or self.resume_from_execution_id is not None
            ):
                raise ValueError("silver_bootstrap_config_invalid")
        elif self.audit_report is not None or self.source_completion is None:
            raise ValueError("silver_update_config_invalid")
        else:
            validate_completion_reference(self.source_completion, freq)


def update_run_id(freq, reference):
    from orchestrator.defs.run_contracts.stock_period import (
        validate_completion_reference,
    )

    ref = validate_completion_reference(reference, freq)
    return str(
        uuid5(
            NAMESPACE_URL,
            f"goldenshare/stock-period-silver/{freq}/{ref['upstream_batch_id']}",
        )
    )


def canonical_run_id(value):
    if str(UUID(value)) != value:
        raise ValueError("silver_run_id_not_canonical")
    return value


def recovery_run_id(parent_id, input_fingerprint):
    canonical_run_id(parent_id)
    return str(
        uuid5(
            NAMESPACE_URL,
            f"goldenshare/stock-period-silver/recovery/{parent_id}/{input_fingerprint}",
        )
    )


def frequency(value):
    if value not in ("week", "month"):
        raise ValueError("silver_frequency_invalid")
    return value


def period_key(value, freq):
    frequency(freq)
    if freq == "week":
        day = date.fromisoformat(value)
        if day.isoformat() != value or day.weekday() != 4:
            raise ValueError("silver_week_invalid")
    else:
        day = date.fromisoformat(value + "-01")
        if day.strftime("%Y-%m") != value:
            raise ValueError("silver_month_invalid")
    return value


def period_start(value, freq):
    period_key(value, freq)
    return (
        (date.fromisoformat(value) - timedelta(days=4)).isoformat()
        if freq == "week"
        else value + "-01"
    )


def asset_name(freq):
    return (
        "silver_stock_weekly" if frequency(freq) == "week" else "silver_stock_monthly"
    )


def check_names(freq):
    return tuple(f"{asset_name(freq)}_{kind}_check" for kind in CHECK_KINDS)


def raw_path(root, freq, period):
    period_key(period, freq)
    return (
        raw_stk_period_bar_adj_week_path(root, period)
        if freq == "week"
        else raw_stock_monthly_path(root, StockMonthlySource.PRIMARY_ADJUSTED, period)
    )


def target_path(root, freq, period):
    period_key(period, freq)
    return (
        silver_stock_weekly_path(root, period)
        if freq == "week"
        else silver_stock_monthly_path(root, period)
    )
