from __future__ import annotations

import pytest

from src.foundation.connectors.base import SourceConnector
from src.foundation.connectors.biying_connector import BiyingSourceConnector
from src.foundation.connectors.factory import CONNECTOR_TYPES, create_source_connector
from src.foundation.connectors.tushare_connector import TushareSourceConnector


def test_factory_contains_expected_connectors() -> None:
    assert "tushare" in CONNECTOR_TYPES
    assert "biying" in CONNECTOR_TYPES


def test_factory_creates_tushare_connector() -> None:
    connector = create_source_connector("tushare")
    assert isinstance(connector, TushareSourceConnector)
    assert isinstance(connector, SourceConnector)


def test_factory_creates_biying_connector() -> None:
    connector = create_source_connector("biying")
    assert isinstance(connector, BiyingSourceConnector)
    assert isinstance(connector, SourceConnector)


def test_factory_rejects_unknown_source_key() -> None:
    with pytest.raises(ValueError, match="Unsupported source_key: unknown"):
        create_source_connector("unknown")
