from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BizTableCatalogItem:
    table_key: str
    display_name: str
    table_name: str
    group_key: str
    group_label: str
    group_order: int
    item_order: int
    observed_date_column: str
    observed_at_column: str | None
    status_policy_key: str


BIZ_TABLE_SOURCE_KEY = "biz_tableset"
BIZ_TABLE_SOURCE_DISPLAY_NAME = "Biz数据集"


BIZ_TABLE_CATALOG: tuple[BizTableCatalogItem, ...] = (
    BizTableCatalogItem(
        table_key="wealth_market_turnover_snapshot",
        display_name="成交额分钟快照",
        table_name="core_serving.wealth_market_turnover_snapshot",
        group_key="wealth_market",
        group_label="财势乾坤",
        group_order=90,
        item_order=10,
        observed_date_column="trade_date",
        observed_at_column="built_at",
        status_policy_key="wealth_turnover_snapshot",
    ),
)


def list_biz_table_catalog_items() -> tuple[BizTableCatalogItem, ...]:
    return BIZ_TABLE_CATALOG
