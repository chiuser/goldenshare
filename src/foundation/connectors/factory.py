from __future__ import annotations

from src.foundation.connectors.base import SourceConnector
from src.foundation.connectors.biying_connector import BiyingSourceConnector
from src.foundation.connectors.tushare_connector import TushareSourceConnector


CONNECTOR_TYPES: dict[str, type[SourceConnector]] = {
    TushareSourceConnector.source_key: TushareSourceConnector,
    BiyingSourceConnector.source_key: BiyingSourceConnector,
}


def create_source_connector(source_key: str) -> SourceConnector:
    connector_type = CONNECTOR_TYPES.get(source_key)
    if connector_type is None:
        supported = ", ".join(sorted(CONNECTOR_TYPES.keys()))
        raise ValueError(f"不支持的数据源：{source_key}。当前支持：{supported}")
    return connector_type()
