from __future__ import annotations

import pytest

from src.foundation.connectors.biying_connector import BiyingSourceConnector


def test_biying_connector_fetches_stock_basic_rows(mocker) -> None:
    connector = BiyingSourceConnector(token="token_x", base_url="https://api.biyingapi.com")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        {"dm": "000001.SZ", "mc": "平安银行", "jys": "SZ"},
        {"dm": "000002.SZ", "mc": "万科A", "jys": "SZ"},
    ]
    get = mocker.patch.object(connector.session, "get", return_value=response)

    rows = connector.call("stock_basic")

    assert rows == response.json.return_value
    get.assert_called_once_with("https://api.biyingapi.com/hslt/list/token_x", timeout=(5, 30))


def test_biying_connector_requires_token() -> None:
    connector = BiyingSourceConnector(token="", base_url="https://api.biyingapi.com")
    with pytest.raises(ValueError, match="BIYING_TOKEN is empty"):
        connector.call("stock_basic")
