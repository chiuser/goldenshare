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
        raise ValueError(f"Unsupported source_key: {source_key}. Supported source keys: {supported}")
    return connector_type()
