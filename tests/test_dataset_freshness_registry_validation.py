from __future__ import annotations

from src.ops.dataset_definition_projection import (
    DatasetFreshnessProjection,
    validate_dataset_freshness_projections,
)


class _ModelWithTradeDate:
    trade_date = object()


class _ModelWithoutTradeDate:
    updated_at = object()


def _build_projection(
    *,
    resource_key: str,
    target_table: str,
    observed_date_column: str | None = "trade_date",
) -> DatasetFreshnessProjection:
    return DatasetFreshnessProjection(
        dataset_key=resource_key,
        resource_key=resource_key,
        display_name=resource_key,
        domain_key="equity",
        domain_display_name="股票",
        target_table=target_table,
        cadence="daily",
        raw_table="raw_tushare.daily",
        observed_date_column=observed_date_column,
    )


def test_validate_dataset_freshness_projections_passes_when_mapping_and_column_exist() -> None:
    projections = {
        "daily": _build_projection(resource_key="daily", target_table="core_serving.equity_daily_bar"),
    }
    errors = validate_dataset_freshness_projections(
        projections,
        observed_model_registry={"core_serving.equity_daily_bar": _ModelWithTradeDate},
    )
    assert errors == []


def test_validate_dataset_freshness_projections_reports_missing_model_mapping() -> None:
    projections = {
        "daily": _build_projection(resource_key="daily", target_table="core_serving.equity_daily_bar"),
    }
    errors = validate_dataset_freshness_projections(projections, observed_model_registry={})
    assert errors
    assert "Missing observed model mapping: daily" in errors[0]


def test_validate_dataset_freshness_projections_reports_missing_observed_column() -> None:
    projections = {
        "daily": _build_projection(resource_key="daily", target_table="core_serving.equity_daily_bar"),
    }
    errors = validate_dataset_freshness_projections(
        projections,
        observed_model_registry={"core_serving.equity_daily_bar": _ModelWithoutTradeDate},
    )
    assert errors
    assert "Missing observed date column on mapped model: daily(core_serving.equity_daily_bar.trade_date)" in errors[0]
