from __future__ import annotations

from unittest.mock import patch

from src.foundation.config.settings import get_settings
from src.foundation.models.core_serving.security_serving import Security


def _security(
    ts_code: str,
    *,
    name: str,
    symbol: str | None = None,
    cnspell: str | None = None,
    exchange: str = "SSE",
    curr_type: str = "CNY",
    list_status: str = "L",
    security_type: str = "EQUITY",
) -> Security:
    return Security(
        ts_code=ts_code,
        symbol=symbol if symbol is not None else ts_code.split(".", 1)[0],
        name=name,
        cnspell=cnspell,
        exchange=exchange,
        curr_type=curr_type,
        list_status=list_status,
        security_type=security_type,
        source="tushare",
    )


def _seed(db_session, *rows: Security) -> None:
    db_session.add_all(rows)
    db_session.commit()


def _get(app_client, keyword: str, *, limit: int | None = None):
    params: dict[str, str | int] = {"keyword": keyword}
    if limit is not None:
        params["limit"] = limit
    return app_client.get("/api/v1/wealth/market/stock-search", params=params)


def test_b01_b02_code_prefix_and_exact_ts_code_are_normalized_and_ranked(
    app_client,
    db_session,
) -> None:
    _seed(
        db_session,
        _security("600009.SH", name="上海机场"),
        _security("600000.SH", name="浦发银行"),
    )

    prefix_response = _get(app_client, " 600 ")
    assert prefix_response.status_code == 200
    assert prefix_response.json() == {
        "keyword": "600",
        "items": [
            {"tsCode": "600000.SH", "name": "浦发银行"},
            {"tsCode": "600009.SH", "name": "上海机场"},
        ],
    }

    exact_response = _get(app_client, "600009.sh")
    assert exact_response.status_code == 200
    assert exact_response.json()["items"][0] == {
        "tsCode": "600009.SH",
        "name": "上海机场",
    }


def test_b03_b04_b05_only_approved_prefix_fields_match(app_client, db_session) -> None:
    _seed(
        db_session,
        _security("000001.SZ", name="平安银行", cnspell="PAYH", exchange="SZSE"),
        _security("600009.SH", name="上海机场", cnspell="SHJC"),
    )

    pinyin_response = _get(app_client, "payh")
    assert pinyin_response.status_code == 200
    assert pinyin_response.json()["items"] == [
        {"tsCode": "000001.SZ", "name": "平安银行"}
    ]
    assert _get(app_client, "平安").json()["items"] == []
    assert _get(app_client, "0009").json()["items"] == []


def test_b06_b07_b08_candidate_pool_excludes_b_shares_inactive_and_non_equity(
    app_client,
    db_session,
) -> None:
    _seed(
        db_session,
        _security("600100.SH", name="合格股票", cnspell="POOL"),
        _security("900901.SH", name="美元B股", cnspell="POOL", curr_type="USD"),
        _security("200001.SZ", name="港币B股", cnspell="POOL", exchange="SZSE", curr_type="HKD"),
        _security("600101.SH", name="退市股票", cnspell="POOL", list_status="D"),
        _security("600102.SH", name="暂停上市", cnspell="POOL", list_status="P"),
        _security("000300.SH", name="沪深300", cnspell="POOL", security_type="INDEX"),
        _security("510300.SH", name="沪深300ETF", cnspell="POOL", security_type="ETF"),
    )

    response = _get(app_client, "pool")
    assert response.status_code == 200
    assert response.json()["items"] == [
        {"tsCode": "600100.SH", "name": "合格股票"}
    ]


def test_b09_candidate_pool_allows_only_sse_szse_and_bse(app_client, db_session) -> None:
    _seed(
        db_session,
        _security("600200.SH", name="沪市", cnspell="EX", exchange="SSE"),
        _security("000200.SZ", name="深市", cnspell="EX", exchange="SZSE"),
        _security("920200.BJ", name="北交所", cnspell="EX", exchange="BSE"),
        _security("00005.HK", name="港股", cnspell="EX", exchange="HKEX"),
    )

    assert _get(app_client, "ex").json()["items"] == [
        {"tsCode": "000200.SZ", "name": "深市"},
        {"tsCode": "600200.SH", "name": "沪市"},
        {"tsCode": "920200.BJ", "name": "北交所"},
    ]


def test_b10_results_have_stable_ts_code_order_within_the_same_rank(
    app_client,
    db_session,
) -> None:
    _seed(
        db_session,
        _security("600302.SH", name="三", cnspell="SAME"),
        _security("000301.SZ", name="一", cnspell="SAME", exchange="SZSE"),
        _security("920303.BJ", name="二", cnspell="SAME", exchange="BSE"),
    )

    assert [item["tsCode"] for item in _get(app_client, "same").json()["items"]] == [
        "000301.SZ",
        "600302.SH",
        "920303.BJ",
    ]


def test_b11_like_metacharacters_are_treated_as_literals(app_client, db_session) -> None:
    _seed(
        db_session,
        _security("600401.SH", name="普通股票", cnspell="NORMAL"),
        _security("600402.SH", name="另一股票", cnspell="ANOTHER"),
    )

    for keyword in ("%", "_", "\\"):
        response = _get(app_client, keyword)
        assert response.status_code == 200
        assert response.json()["items"] == []


def test_b12_default_and_explicit_limits_are_bounded(app_client, db_session) -> None:
    _seed(
        db_session,
        *[
            _security(
                f"{600500 + index:06d}.SH",
                name=f"候选{index:02d}",
                cnspell="LIMIT",
            )
            for index in range(21)
        ],
    )

    assert len(_get(app_client, "limit").json()["items"]) == 8
    assert len(_get(app_client, "limit", limit=1).json()["items"]) == 1
    assert len(_get(app_client, "limit", limit=20).json()["items"]) == 20
    rejected = _get(app_client, "limit", limit=21)
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "SS_REQUEST_INVALID"


def test_b13_blank_and_overlong_keywords_are_rejected(app_client) -> None:
    for keyword in ("   ", "A" * 33):
        response = _get(app_client, keyword)
        assert response.status_code == 400
        assert response.json()["code"] == "SS_REQUEST_INVALID"


def test_b14_quote_access_policy_is_reused(app_client, monkeypatch) -> None:
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        response = _get(app_client, "600")
        assert response.status_code == 401
        assert response.json()["code"] == "auth_required"
    finally:
        monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
        get_settings.cache_clear()


def test_b15_query_failures_use_safe_registered_error(app_client) -> None:
    with patch(
        "src.biz.queries.wealth.market.stock_search.stock_search_query.StockSearchQuery.search",
        side_effect=RuntimeError("core_serving.security_serving secret failure"),
    ):
        response = _get(app_client, "600")

    assert response.status_code == 500
    assert response.json()["code"] == "SS_QUERY_FAILED"
    assert response.json()["message"] == "股票搜索暂不可用"
    assert "security_serving" not in response.text
    assert "secret failure" not in response.text


def test_b16_fastapi_shape_errors_use_validation_error(app_client) -> None:
    missing_keyword = app_client.get("/api/v1/wealth/market/stock-search")
    invalid_limit = app_client.get(
        "/api/v1/wealth/market/stock-search",
        params={"keyword": "600", "limit": "not-an-integer"},
    )

    assert missing_keyword.status_code == 422
    assert missing_keyword.json()["code"] == "validation_error"
    assert invalid_limit.status_code == 422
    assert invalid_limit.json()["code"] == "validation_error"
