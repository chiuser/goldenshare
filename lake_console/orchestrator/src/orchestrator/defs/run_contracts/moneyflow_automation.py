"""Fixed moneyflow automation identities; no configurable dataset selection."""

from dataclasses import dataclass

from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_CNT_THS_RAW_CHECK,
    MONEYFLOW_CNT_THS_SILVER_CHECK,
    MONEYFLOW_IND_DC_RAW_CHECK,
    MONEYFLOW_IND_DC_SILVER_CHECK,
    MONEYFLOW_IND_THS_RAW_CHECK,
    MONEYFLOW_IND_THS_SILVER_CHECK,
    MONEYFLOW_MKT_DC_RAW_CHECK,
    MONEYFLOW_MKT_DC_SILVER_CHECK,
    MONEYFLOW_MKT_HISTORY_START,
    MoneyflowContractError,
)


@dataclass(frozen=True)
class MoneyflowAutomationContract:
    dataset: str
    raw_check: str
    silver_check: str
    partition_set: str
    history_start: str
    label: str

    @property
    def raw_asset(self):
        return "raw_tushare_" + self.dataset

    @property
    def silver_asset(self):
        return "silver_" + self.dataset

    @property
    def raw_job(self):
        return self.raw_asset + "_update_job"

    @property
    def silver_job(self):
        return self.silver_asset + "_update_job"

    @property
    def event_revision(self):
        require_moneyflow_automation_contract(self)
        return {
            "moneyflow_mkt_dc": "market_moneyflow_history_events_v1",
            "moneyflow_ind_ths": "industry_moneyflow_ths_history_events_v1",
            "moneyflow_cnt_ths": "concept_moneyflow_ths_history_events_v1",
            "moneyflow_ind_dc": "board_moneyflow_dc_history_events_v1",
        }[self.dataset]


MARKET_MONEYFLOW_AUTOMATION = MoneyflowAutomationContract(
    "moneyflow_mkt_dc",
    MONEYFLOW_MKT_DC_RAW_CHECK,
    MONEYFLOW_MKT_DC_SILVER_CHECK,
    "cn_a_moneyflow_mkt_dc_trade_days",
    MONEYFLOW_MKT_HISTORY_START,
    "东方财富大盘资金流向",
)
INDUSTRY_THS_MONEYFLOW_AUTOMATION = MoneyflowAutomationContract(
    "moneyflow_ind_ths",
    MONEYFLOW_IND_THS_RAW_CHECK,
    MONEYFLOW_IND_THS_SILVER_CHECK,
    "cn_a_moneyflow_ind_ths_trade_days",
    "2024-09-10",
    "同花顺行业资金流向",
)
CONCEPT_THS_MONEYFLOW_AUTOMATION = MoneyflowAutomationContract(
    "moneyflow_cnt_ths",
    MONEYFLOW_CNT_THS_RAW_CHECK,
    MONEYFLOW_CNT_THS_SILVER_CHECK,
    "cn_a_moneyflow_cnt_ths_trade_days",
    "2024-09-10",
    "同花顺概念资金流向",
)


BOARD_DC_MONEYFLOW_AUTOMATION = MoneyflowAutomationContract(
    "moneyflow_ind_dc",
    MONEYFLOW_IND_DC_RAW_CHECK,
    MONEYFLOW_IND_DC_SILVER_CHECK,
    "cn_a_moneyflow_ind_dc_trade_days",
    "2023-09-12",
    "东方财富板块资金流向",
)


def require_moneyflow_automation_contract(contract):
    if contract not in (
        MARKET_MONEYFLOW_AUTOMATION,
        INDUSTRY_THS_MONEYFLOW_AUTOMATION,
        CONCEPT_THS_MONEYFLOW_AUTOMATION,
        BOARD_DC_MONEYFLOW_AUTOMATION,
    ):
        raise MoneyflowContractError("automation_dataset")
