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
    with pytest.raises(ValueError, match="Biying 数据源令牌未配置"):
        connector.call("stock_basic")


def test_biying_connector_fetches_equity_daily_rows(mocker) -> None:
    connector = BiyingSourceConnector(token="token_x", base_url="https://api.biyingapi.com")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        {"t": "2026-04-09 00:00:00", "o": 24.33, "h": 24.93, "l": 24.18, "c": 24.38, "v": 943525, "a": 2307474664, "pc": 25.05, "sf": 0},
    ]
    get = mocker.patch.object(connector.session, "get", return_value=response)

    rows = connector.call(
        "equity_daily_bar",
        params={
            "dm": "600602.SH",
            "freq": "d",
            "adj_type": "f",
            "st": "20260403",
            "et": "20260410",
            "lt": "2",
        },
    )

    assert rows == response.json.return_value
    get.assert_called_once_with(
        "https://api.biyingapi.com/hsstock/history/600602.SH/d/f/token_x?st=20260403&et=20260410&lt=2",
        timeout=(5, 30),
    )


def test_biying_connector_equity_daily_no_data_returns_empty_list(mocker) -> None:
    connector = BiyingSourceConnector(token="token_x", base_url="https://api.biyingapi.com")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"error": "数据不存在"}
    get = mocker.patch.object(connector.session, "get", return_value=response)

    rows = connector.call(
        "equity_daily_bar",
        params={
            "dm": "600602.SH",
            "freq": "d",
            "adj_type": "f",
            "st": "20260403",
            "et": "20260410",
            "lt": "2",
        },
    )

    assert rows == []
    get.assert_called_once_with(
        "https://api.biyingapi.com/hsstock/history/600602.SH/d/f/token_x?st=20260403&et=20260410&lt=2",
        timeout=(5, 30),
    )


def test_biying_connector_fetches_moneyflow_rows(mocker) -> None:
    connector = BiyingSourceConnector(token="token_x", base_url="https://api.biyingapi.com")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        {"t": "2026-04-10 00:00:00", "zmbzds": 1, "dddx": -5.3},
    ]
    get = mocker.patch.object(connector.session, "get", return_value=response)

    rows = connector.call(
        "moneyflow",
        params={
            "dm": "000001.SZ",
            "st": "20260401",
            "et": "20260410",
        },
    )

    assert rows == response.json.return_value
    get.assert_called_once_with(
        "https://api.biyingapi.com/hsstock/history/transaction/000001.SZ/token_x?st=20260401&et=20260410",
        timeout=(5, 30),
    )


def test_biying_connector_moneyflow_no_data_returns_empty_list(mocker) -> None:
    connector = BiyingSourceConnector(token="token_x", base_url="https://api.biyingapi.com")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"error": "数据不存在"}
    get = mocker.patch.object(connector.session, "get", return_value=response)

    rows = connector.call(
        "moneyflow",
        params={
            "dm": "000001.SZ",
            "st": "20260401",
            "et": "20260410",
        },
    )

    assert rows == []
    get.assert_called_once_with(
        "https://api.biyingapi.com/hsstock/history/transaction/000001.SZ/token_x?st=20260401&et=20260410",
        timeout=(5, 30),
    )


def test_biying_connector_applies_rate_limit_before_request(mocker) -> None:
    connector = BiyingSourceConnector(token="token_x", base_url="https://api.biyingapi.com")
    limiter = mocker.Mock()
    mocker.patch("src.foundation.connectors.biying_connector._get_rate_limiter", return_value=limiter)
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [{"dm": "000001.SZ", "mc": "平安银行", "jys": "SZ"}]
    get = mocker.patch.object(connector.session, "get", return_value=response)

    rows = connector.call("stock_basic")

    assert rows == response.json.return_value
    limiter.acquire.assert_called_once()
    get.assert_called_once_with("https://api.biyingapi.com/hslt/list/token_x", timeout=(5, 30))
