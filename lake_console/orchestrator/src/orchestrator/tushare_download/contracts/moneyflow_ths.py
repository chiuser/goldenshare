"""同花顺个股资金流向完整源合同；本次只启用单日下载模式。"""

from ..download_models import DownloadMode
from ..source_contract import (
    ModeRule,
    OrderingRule,
    PaginationRule,
    ParameterRule,
    SourceDatasetContract,
    SourceField,
    SourceKind,
    TimeRule,
)

SOURCE_FIELDS = (
    SourceField(
        "trade_date", SourceKind.STRING, format="YYYYMMDD",
        description="交易日期", nullable=False,
    ),
    SourceField("ts_code", SourceKind.STRING, description="股票代码", nullable=False),
    SourceField("name", SourceKind.STRING, description="股票名称", nullable=True),
    *(
        SourceField(
            name, SourceKind.NUMBER, description=description, nullable=True,
            precision_note="源文档未声明固定小数位；保留源数值，下载组件不舍入。",
        )
        for name, description in (
            ("pct_change", "涨跌幅"),
            ("latest", "最新价"),
            ("net_amount", "资金净流入(万元)"),
            ("net_d5_amount", "5日主力净额(万元)"),
            ("buy_lg_amount", "今日大单净流入额(万元)"),
            ("buy_lg_amount_rate", "今日大单净流入占比(%)"),
            ("buy_md_amount", "今日中单净流入额(万元)"),
            ("buy_md_amount_rate", "今日中单净流入占比(%)"),
            ("buy_sm_amount", "今日小单净流入额(万元)"),
            ("buy_sm_amount_rate", "今日小单净流入占比(%)"),
        )
    ),
)

MONEYFLOW_THS_CONTRACT = SourceDatasetContract(
    contract_name="moneyflow_ths",
    dataset_id="moneyflow_ths",
    version="1",
    source_api_name="moneyflow_ths",
    fields=SOURCE_FIELDS,
    parameters=tuple(
        ParameterRule(name, SourceKind.STRING)
        for name in ("ts_code", "trade_date", "start_date", "end_date")
    ),
    modes=(ModeRule(DownloadMode.BY_POINT, point_param="trade_date"),),
    pagination=PaginationRule(
        strategy=2, effective_limit=2000, offset_start=0, offset_step=2000,
        limit_param="limit", offset_param="offset",
        short_page_ends=True, empty_page_ends=True,
    ),
    time_rules=(TimeRule("day", "1", "YYYY-MM-DD", "YYYYMMDD", "trade_date"),),
    ordering=OrderingRule("trade_date", "day"),
    source_evidence=(
        "https://tushare.pro/document/2?doc_id=348",
        "2026-11-12：20261110三页2000/2000/1218个代码及单代码完整13字段。",
        "2026-11-13：000001.SZ/20261110显式13字段只读源样本。",
    ),
    local_evidence_paths=(
        "docs/sources/tushare/股票数据/资金流向数据/0348_个股资金流向（THS）.md",
        "lake_console/docs/design/dagster-moneyflow-tushare-low-level-design-v1.md",
    ),
)
