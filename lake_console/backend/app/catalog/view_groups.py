from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeViewGroup


VIEW_GROUPS: tuple[LakeViewGroup, ...] = (
    LakeViewGroup(group_key="reference_data", group_label="A股基础数据", group_order=1),
    LakeViewGroup(group_key="equity_market", group_label="A股行情", group_order=2),
    LakeViewGroup(group_key="board_theme", group_label="板块 / 题材", group_order=3),
    LakeViewGroup(group_key="leader_board", group_label="榜单", group_order=4),
    LakeViewGroup(group_key="limit_board", group_label="涨跌停榜", group_order=5),
    LakeViewGroup(group_key="index_market_data", group_label="A股指数行情", group_order=6),
    LakeViewGroup(group_key="etf_fund", group_label="ETF基金", group_order=7),
    LakeViewGroup(group_key="moneyflow", group_label="资金流向", group_order=8),
    LakeViewGroup(group_key="broker_recommendation", group_label="券商推荐", group_order=9),
    LakeViewGroup(group_key="news", group_label="新闻资讯", group_order=10),
    LakeViewGroup(group_key="hk_reference_data", group_label="港股基础数据", group_order=11),
    LakeViewGroup(group_key="us_reference_data", group_label="美股基础数据", group_order=12),
    LakeViewGroup(group_key="technical_indicators", group_label="技术指标", group_order=13),
    LakeViewGroup(group_key="maintenance", group_label="维护命令", group_order=99),
)

_VIEW_GROUP_BY_KEY = {group.group_key: group for group in VIEW_GROUPS}


def get_view_group(group_key: str) -> LakeViewGroup:
    try:
        return _VIEW_GROUP_BY_KEY[group_key]
    except KeyError as exc:
        raise ValueError(f"Unknown Lake view group: {group_key}") from exc
