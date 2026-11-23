"""Single-code, single-day Tushare projections for manual DC concept review."""

from ...defs.run_contracts.dc_board import DC_INDEX_PAGE_LIMIT, DC_MEMBER_PAGE_LIMIT
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

DC_INDEX_REVIEW_FIELDS = ("trade_date", "ts_code", "name", "idx_type")
DC_MEMBER_REVIEW_FIELDS = ("trade_date", "ts_code", "con_code", "name")
# A real “历史新高” may share the placeholder's name. Reuse the complete production predicate.
DC_INDEX_PLACEHOLDER_FIELDS = (
    "leading",
    "leading_code",
    "pct_change",
    "leading_pct",
    "total_mv",
    "turnover_rate",
    "up_num",
    "down_num",
)


def _contract(name, fields, page_size, doc_id, local_doc, extra_parameters=()):
    return SourceDatasetContract(
        contract_name=name,
        dataset_id=name,
        version="1",
        source_api_name=name,
        fields=tuple(
            SourceField(
                field,
                SourceKind.NUMBER
                if field in DC_INDEX_PLACEHOLDER_FIELDS[2:]
                else SourceKind.STRING,
                nullable=field in DC_INDEX_PLACEHOLDER_FIELDS,
                format="YYYYMMDD" if field == "trade_date" else "",
            )
            for field in fields
        ),
        parameters=(
            ParameterRule("ts_code", SourceKind.STRING),
            ParameterRule("trade_date", SourceKind.STRING),
            *extra_parameters,
        ),
        modes=(
            ModeRule(
                DownloadMode.BY_OBJECT_POINT,
                object_param="ts_code",
                point_param="trade_date",
                allowed_filters=tuple(parameter.name for parameter in extra_parameters),
            ),
        ),
        pagination=PaginationRule(
            strategy=2,
            effective_limit=page_size,
            offset_start=0,
            offset_step=page_size,
            limit_param="limit",
            offset_param="offset",
            short_page_ends=True,
            empty_page_ends=True,
        ),
        time_rules=(TimeRule("day", "1", "YYYY-MM-DD", "YYYYMMDD", "trade_date"),),
        ordering=OrderingRule("trade_date", "day"),
        source_evidence=(f"https://tushare.pro/document/2?doc_id={doc_id}",),
        local_evidence_paths=(
            f"docs/sources/tushare/股票数据/打板专题数据/{local_doc}",
        ),
    )


DC_INDEX_REVIEW_CONTRACT = _contract(
    "dc_index",
    (*DC_INDEX_REVIEW_FIELDS, *DC_INDEX_PLACEHOLDER_FIELDS),
    DC_INDEX_PAGE_LIMIT,
    362,
    "0362_东方财富概念板块.md",
    (
        ParameterRule(
            "idx_type", SourceKind.STRING, required=True, choices=("概念板块",)
        ),
    ),
)
DC_MEMBER_REVIEW_CONTRACT = _contract(
    "dc_member",
    DC_MEMBER_REVIEW_FIELDS,
    DC_MEMBER_PAGE_LIMIT,
    363,
    "0363_东方财富板块成分.md",
)
