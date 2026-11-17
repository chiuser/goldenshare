"""指数周线完整源合同；量额单位采用已核实的源值。"""

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
    SourceField("ts_code", SourceKind.STRING, description="指数代码", nullable=False),
    SourceField(
        "trade_date", SourceKind.STRING, format="YYYYMMDD",
        description="周期最后交易日", nullable=False,
    ),
    *(
        SourceField(
            name, SourceKind.NUMBER, description=description,
            precision_note="保留源数值，下载组件不舍入。",
        )
        for name, description in (
            ("close", "收盘点位"), ("open", "开盘点位"),
            ("high", "最高点位"), ("low", "最低点位"),
            ("pre_close", "前收盘点位"), ("change", "涨跌点位"),
            ("pct_chg", "涨跌幅比例，1%为0.0100"),
            ("vol", "成交量（股，采用已核实源值）"),
            ("amount", "成交额（元，采用已核实源值）"),
        )
    ),
)

INDEX_WEEKLY_CONTRACT = SourceDatasetContract(
    contract_name="index_weekly", dataset_id="index_weekly", version="1",
    source_api_name="index_weekly", fields=SOURCE_FIELDS,
    parameters=(
        *(ParameterRule(name, SourceKind.STRING) for name in (
            "ts_code", "trade_date", "start_date", "end_date",
        )),
    ),
    modes=(ModeRule(
        DownloadMode.BY_OBJECT_POINT, object_param="ts_code", point_param="trade_date",
    ),),
    pagination=PaginationRule(
        strategy=2, effective_limit=1000, offset_start=0, offset_step=1000,
        limit_param="limit", offset_param="offset",
        short_page_ends=True, empty_page_ends=True,
    ),
    time_rules=(TimeRule("day", "1", "YYYY-MM-DD", "YYYYMMDD", "trade_date"),),
    ordering=OrderingRule("trade_date", "day"),
    source_evidence=(
        "https://tushare.pro/document/2?doc_id=171",
        "2026-11-17：完整11字段、单代码期末点查；北证50为空；量额为股、元，涨跌幅为比例。",
    ),
    local_evidence_paths=(
        "docs/sources/tushare/指数专题/0171_指数周线行情.md",
        "lake_console/docs/design/dagster-index-period-onboarding-plan-and-low-level-design-v1.md",
    ),
)
