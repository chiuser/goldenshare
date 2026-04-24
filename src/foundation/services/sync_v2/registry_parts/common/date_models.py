from __future__ import annotations

from src.foundation.services.sync_v2.contracts import DatasetDateModel


def _trade_day(
    *,
    bucket_rule: str = "every_open_day",
    window_mode: str = "point_or_range",
) -> DatasetDateModel:
    return DatasetDateModel(
        date_axis="trade_open_day",
        bucket_rule=bucket_rule,
        window_mode=window_mode,
        input_shape="trade_date_or_start_end",
        observed_field="trade_date",
        audit_applicable=True,
    )


def _master(*, window_mode: str = "point") -> DatasetDateModel:
    return DatasetDateModel(
        date_axis="none",
        bucket_rule="not_applicable",
        window_mode=window_mode,
        input_shape="none",
        observed_field=None,
        audit_applicable=False,
        not_applicable_reason="snapshot/master dataset",
    )


DATASET_DATE_MODELS: dict[str, DatasetDateModel] = {
    "adj_factor": _trade_day(),
    "biying_equity_daily": _trade_day(),
    "biying_moneyflow": _trade_day(),
    "block_trade": _trade_day(),
    "broker_recommend": DatasetDateModel(
        date_axis="month_key",
        bucket_rule="every_natural_month",
        window_mode="point_or_range",
        input_shape="month_or_range",
        observed_field="month",
        audit_applicable=True,
    ),
    "cyq_perf": _trade_day(),
    "daily": _trade_day(),
    "daily_basic": _trade_day(),
    "dc_daily": _trade_day(),
    "dc_hot": _trade_day(),
    "dc_index": _trade_day(),
    "dc_member": _trade_day(),
    "dividend": DatasetDateModel(
        date_axis="natural_day",
        bucket_rule="every_natural_day",
        window_mode="range",
        input_shape="ann_date_or_start_end",
        observed_field="ann_date",
        audit_applicable=True,
    ),
    "etf_basic": _master(),
    "etf_index": _master(),
    "fund_adj": _trade_day(),
    "fund_daily": _trade_day(),
    "hk_basic": _master(),
    "index_basic": _master(),
    "index_daily": _trade_day(),
    "index_daily_basic": _trade_day(),
    "index_monthly": _trade_day(bucket_rule="month_last_open_day"),
    "index_weekly": _trade_day(bucket_rule="week_last_open_day"),
    "index_weight": DatasetDateModel(
        date_axis="month_window",
        bucket_rule="month_window_has_data",
        window_mode="range",
        input_shape="start_end_month_window",
        observed_field="trade_date",
        audit_applicable=True,
    ),
    "kpl_concept_cons": _trade_day(),
    "kpl_list": _trade_day(),
    "limit_cpt_list": _trade_day(),
    "limit_list_d": _trade_day(),
    "limit_list_ths": _trade_day(),
    "limit_step": _trade_day(),
    "margin": _trade_day(),
    "moneyflow": _trade_day(),
    "moneyflow_cnt_ths": _trade_day(),
    "moneyflow_dc": _trade_day(),
    "moneyflow_ind_dc": _trade_day(),
    "moneyflow_ind_ths": _trade_day(),
    "moneyflow_mkt_dc": _trade_day(),
    "moneyflow_ths": _trade_day(),
    "stk_factor_pro": _trade_day(),
    "stk_holdernumber": DatasetDateModel(
        date_axis="natural_day",
        bucket_rule="every_natural_day",
        window_mode="range",
        input_shape="ann_date_or_start_end",
        observed_field="ann_date",
        audit_applicable=True,
    ),
    "stk_limit": _trade_day(),
    "stk_nineturn": _trade_day(),
    "stk_period_bar_adj_month": _trade_day(bucket_rule="month_last_open_day"),
    "stk_period_bar_adj_week": _trade_day(bucket_rule="week_last_open_day"),
    "stk_period_bar_month": _trade_day(bucket_rule="month_last_open_day"),
    "stk_period_bar_week": _trade_day(bucket_rule="week_last_open_day"),
    "stock_basic": _master(window_mode="none"),
    "stock_st": _trade_day(),
    "suspend_d": _trade_day(),
    "ths_daily": _trade_day(),
    "ths_hot": _trade_day(),
    "ths_index": _master(),
    "ths_member": _master(window_mode="point_or_range"),
    "top_list": _trade_day(),
    "trade_cal": DatasetDateModel(
        date_axis="natural_day",
        bucket_rule="every_natural_day",
        window_mode="point_or_range",
        input_shape="trade_date_or_start_end",
        observed_field="trade_date",
        audit_applicable=True,
    ),
    "us_basic": _master(),
}


def get_dataset_date_model(dataset_key: str) -> DatasetDateModel:
    try:
        return DATASET_DATE_MODELS[dataset_key]
    except KeyError as exc:
        raise KeyError(f"missing date_model for dataset={dataset_key}") from exc
