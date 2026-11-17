"""指数月线完整源合同，与周线共用相同源业务字段。"""

from dataclasses import replace

from .index_weekly import INDEX_WEEKLY_CONTRACT

INDEX_MONTHLY_CONTRACT = replace(
    INDEX_WEEKLY_CONTRACT,
    contract_name="index_monthly", dataset_id="index_monthly",
    source_api_name="index_monthly",
    source_evidence=(
        "https://tushare.pro/document/2?doc_id=172",
        "2026-11-17：完整11字段、单代码期末点查；北证50为空；量额为股、元，涨跌幅为比例。",
    ),
    local_evidence_paths=(
        "docs/sources/tushare/指数专题/0172_指数月线行情.md",
        "lake_console/docs/design/dagster-index-period-onboarding-plan-and-low-level-design-v1.md",
    ),
)
