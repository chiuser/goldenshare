from __future__ import annotations

FreshnessPolicy = str

CONTINUOUS_OPEN_DAY = "continuous_open_day"
CONTINUOUS_NATURAL_DAY = "continuous_natural_day"
PERIOD_BUCKET = "period_bucket"
EVENT_RUN_TRACE = "event_run_trace"
SNAPSHOT_RUN_TRACE = "snapshot_run_trace"

FRESHNESS_POLICIES: frozenset[FreshnessPolicy] = frozenset(
    {
        CONTINUOUS_OPEN_DAY,
        CONTINUOUS_NATURAL_DAY,
        PERIOD_BUCKET,
        EVENT_RUN_TRACE,
        SNAPSHOT_RUN_TRACE,
    }
)

FRESHNESS_POLICY_BY_DATASET: dict[str, FreshnessPolicy] = {
    "adj_factor": CONTINUOUS_OPEN_DAY,
    "anns_d": EVENT_RUN_TRACE,
    "bak_basic": CONTINUOUS_OPEN_DAY,
    "balancesheet": EVENT_RUN_TRACE,
    "biying_equity_daily": CONTINUOUS_OPEN_DAY,
    "biying_moneyflow": CONTINUOUS_OPEN_DAY,
    "block_trade": EVENT_RUN_TRACE,
    "broker_recommend": PERIOD_BUCKET,
    "bse_mapping": SNAPSHOT_RUN_TRACE,
    "cctv_news": CONTINUOUS_NATURAL_DAY,
    "cashflow": EVENT_RUN_TRACE,
    "cyq_chips": CONTINUOUS_OPEN_DAY,
    "cyq_perf": CONTINUOUS_OPEN_DAY,
    "daily": CONTINUOUS_OPEN_DAY,
    "daily_basic": CONTINUOUS_OPEN_DAY,
    "dc_daily": CONTINUOUS_OPEN_DAY,
    "dc_hot": CONTINUOUS_OPEN_DAY,
    "dc_index": CONTINUOUS_OPEN_DAY,
    "dc_member": CONTINUOUS_OPEN_DAY,
    "dividend": EVENT_RUN_TRACE,
    "etf_basic": SNAPSHOT_RUN_TRACE,
    "etf_index": SNAPSHOT_RUN_TRACE,
    "etf_mins": CONTINUOUS_OPEN_DAY,
    "etf_sh_cons": CONTINUOUS_OPEN_DAY,
    "etf_share_size": CONTINUOUS_OPEN_DAY,
    "etf_sz_cons": CONTINUOUS_OPEN_DAY,
    "express": EVENT_RUN_TRACE,
    "fina_indicator": EVENT_RUN_TRACE,
    "fund_adj": CONTINUOUS_OPEN_DAY,
    "fund_basic": SNAPSHOT_RUN_TRACE,
    "fund_company": SNAPSHOT_RUN_TRACE,
    "fund_daily": CONTINUOUS_OPEN_DAY,
    "fund_div": EVENT_RUN_TRACE,
    "fund_manager": SNAPSHOT_RUN_TRACE,
    "fund_portfolio": EVENT_RUN_TRACE,
    "fund_share": EVENT_RUN_TRACE,
    "hk_basic": SNAPSHOT_RUN_TRACE,
    "index_basic": SNAPSHOT_RUN_TRACE,
    "index_classify": SNAPSHOT_RUN_TRACE,
    "index_daily": CONTINUOUS_OPEN_DAY,
    "index_daily_basic": CONTINUOUS_OPEN_DAY,
    "idx_factor_pro": CONTINUOUS_OPEN_DAY,
    "index_mins": CONTINUOUS_OPEN_DAY,
    "index_member_all": SNAPSHOT_RUN_TRACE,
    "index_monthly": PERIOD_BUCKET,
    "index_weekly": PERIOD_BUCKET,
    "index_weight": PERIOD_BUCKET,
    "income": EVENT_RUN_TRACE,
    "irm_qa_sh": EVENT_RUN_TRACE,
    "irm_qa_sz": EVENT_RUN_TRACE,
    "kpl_concept_cons": CONTINUOUS_OPEN_DAY,
    "kpl_list": CONTINUOUS_OPEN_DAY,
    "limit_cpt_list": CONTINUOUS_OPEN_DAY,
    "limit_list_d": CONTINUOUS_OPEN_DAY,
    "limit_list_ths": CONTINUOUS_OPEN_DAY,
    "limit_step": CONTINUOUS_OPEN_DAY,
    "major_news": EVENT_RUN_TRACE,
    "margin": CONTINUOUS_OPEN_DAY,
    "margin_detail": CONTINUOUS_OPEN_DAY,
    "moneyflow": CONTINUOUS_OPEN_DAY,
    "moneyflow_cnt_ths": CONTINUOUS_OPEN_DAY,
    "moneyflow_dc": CONTINUOUS_OPEN_DAY,
    "moneyflow_ind_dc": CONTINUOUS_OPEN_DAY,
    "moneyflow_ind_ths": CONTINUOUS_OPEN_DAY,
    "moneyflow_mkt_dc": CONTINUOUS_OPEN_DAY,
    "moneyflow_ths": CONTINUOUS_OPEN_DAY,
    "mkt_idx_bmk": SNAPSHOT_RUN_TRACE,
    "namechange": SNAPSHOT_RUN_TRACE,
    "news": EVENT_RUN_TRACE,
    "research_report": EVENT_RUN_TRACE,
    "st": SNAPSHOT_RUN_TRACE,
    "stk_auction_c": CONTINUOUS_OPEN_DAY,
    "stk_auction_o": CONTINUOUS_OPEN_DAY,
    "stk_factor_pro": CONTINUOUS_OPEN_DAY,
    "stk_holdernumber": EVENT_RUN_TRACE,
    "stk_limit": CONTINUOUS_OPEN_DAY,
    "stk_mins": CONTINUOUS_OPEN_DAY,
    "stk_nineturn": CONTINUOUS_OPEN_DAY,
    "stk_period_bar_adj_month": PERIOD_BUCKET,
    "stk_period_bar_adj_week": PERIOD_BUCKET,
    "stk_period_bar_month": PERIOD_BUCKET,
    "stk_period_bar_week": PERIOD_BUCKET,
    "stock_basic": SNAPSHOT_RUN_TRACE,
    "stock_company": SNAPSHOT_RUN_TRACE,
    "stock_st": CONTINUOUS_OPEN_DAY,
    "suspend_d": CONTINUOUS_OPEN_DAY,
    "sw_daily": CONTINUOUS_OPEN_DAY,
    "ths_daily": CONTINUOUS_OPEN_DAY,
    "ths_hot": CONTINUOUS_OPEN_DAY,
    "ths_index": SNAPSHOT_RUN_TRACE,
    "ths_member": SNAPSHOT_RUN_TRACE,
    "top_list": CONTINUOUS_OPEN_DAY,
    "trade_cal": CONTINUOUS_NATURAL_DAY,
    "us_basic": SNAPSHOT_RUN_TRACE,
}


def get_freshness_policy(dataset_key: str) -> FreshnessPolicy:
    try:
        return FRESHNESS_POLICY_BY_DATASET[dataset_key]
    except KeyError as exc:
        raise ValueError(f"数据集 {dataset_key} 缺少 freshness policy") from exc


def is_valid_freshness_policy(policy: str) -> bool:
    return policy in FRESHNESS_POLICIES
