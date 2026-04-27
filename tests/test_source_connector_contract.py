from __future__ import annotations

import pytest

from src.foundation.connectors.base import SourceConnector
from src.foundation.connectors.biying_connector import BiyingSourceConnector
from src.foundation.connectors.tushare_connector import TushareSourceConnector


class _DummyConnector(SourceConnector):
    source_key = "dummy"

    def call(self, api_name: str, params=None, fields=None):
        return [{"api_name": api_name, "params": params or {}, "fields": list(fields or [])}]


def test_source_connector_contract_shape() -> None:
    connector = _DummyConnector()
    rows = connector.call("daily", params={"ts_code": "000001.SZ"}, fields=["trade_date", "close"])
    assert rows == [
        {
            "api_name": "daily",
            "params": {"ts_code": "000001.SZ"},
            "fields": ["trade_date", "close"],
        }
    ]


def test_connectors_expose_source_key() -> None:
    assert TushareSourceConnector.source_key == "tushare"
    assert BiyingSourceConnector.source_key == "biying"


def test_biying_connector_rejects_unsupported_api() -> None:
    connector = BiyingSourceConnector(token="x", base_url="https://api.biyingapi.com")
    with pytest.raises(ValueError, match="不支持该接口"):
        connector.call("equity_daily")
