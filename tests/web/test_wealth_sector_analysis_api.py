from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import event, select

from src.foundation.config.settings import get_settings
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy


TARGET_DATE = date(2026, 4, 30)
OPEN_DATES = tuple(TARGET_DATE - timedelta(days=offset) for offset in range(64, -1, -1))


def _ensure_tables(db_session) -> None:
    bind = db_session.get_bind()
    DcDaily.__table__.create(bind, checkfirst=True)
    WealthSectorHierarchy.__table__.create(bind, checkfirst=True)


def _hierarchy_rows() -> tuple[tuple[str, str, int, str | None, str, str], ...]:
    return (
        ("BK1001.DC", "一级甲", 1, None, "BK1001.DC", "一级甲"),
        ("BK1002.DC", "一级乙", 1, None, "BK1002.DC", "一级乙"),
        ("BK1101.DC", "二级甲一", 2, "BK1001.DC", "BK1001.DC", "一级甲/二级甲一"),
        ("BK1102.DC", "二级甲二", 2, "BK1001.DC", "BK1001.DC", "一级甲/二级甲二"),
        ("BK1103.DC", "二级乙一", 2, "BK1002.DC", "BK1002.DC", "一级乙/二级乙一"),
        (
            "BK1201.DC",
            "三级甲一一",
            3,
            "BK1101.DC",
            "BK1001.DC",
            "一级甲/二级甲一/三级甲一一",
        ),
        (
            "BK1202.DC",
            "三级甲一二",
            3,
            "BK1101.DC",
            "BK1001.DC",
            "一级甲/二级甲一/三级甲一二",
        ),
    )


def _seed_sector_analysis(db_session) -> None:
    _ensure_tables(db_session)
    rows = _hierarchy_rows()
    previous: date | None = None
    for item in OPEN_DATES:
        db_session.add(
            TradeCalendar(
                exchange="SSE",
                trade_date=item,
                is_open=True,
                pretrade_date=previous,
            )
        )
        previous = item
    for order, (code, name, level, parent, root, path) in enumerate(rows, start=1):
        parent_name = next((row[1] for row in rows if row[0] == parent), None)
        root_name = next(row[1] for row in rows if row[0] == root)
        db_session.add(
            WealthSectorHierarchy(
                sector_code=code,
                sector_name=name,
                industry_level=level,
                industry_level_name=f"{level}级行业",
                parent_sector_code=parent,
                parent_sector_name=parent_name,
                root_sector_code=root,
                root_sector_name=root_name,
                hierarchy_path=path,
                is_leaf=level == 3,
                display_order=order,
                baseline_version="2026-04-30-v1",
                source_received_date=TARGET_DATE,
                code_reference_trade_date=TARGET_DATE,
                published_at=datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc),
            )
        )
        for date_index, item in enumerate(OPEN_DATES):
            close = Decimal(100 + order * 10 + date_index)
            db_session.add(
                DcDaily(
                    ts_code=code,
                    trade_date=item,
                    category="行业板块",
                    close=close,
                    open=close,
                    high=close,
                    low=close,
                    change=Decimal(order),
                    pct_change=Decimal(10 - order),
                    vol=Decimal("100"),
                    amount=Decimal("1000"),
                    swing=Decimal("1"),
                    turnover_rate=Decimal("2"),
                )
            )
    db_session.commit()


def _count_request_sql(engine, callback) -> tuple[int, object]:
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = callback()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(statements), response


def test_meta_returns_hierarchy_and_complete_open_date_coverage_in_three_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get("/api/v1/wealth/market/sector-analysis/meta"),
    )

    assert response.status_code == 200
    assert sql_count == 3
    payload = response.json()
    assert payload["coverageStartDate"] == OPEN_DATES[0].isoformat()
    assert payload["coverageEndDate"] == TARGET_DATE.isoformat()
    assert len(payload["hierarchy"]["nodes"]) == 7
    assert len(payload["tradeDates"]) == 65
    assert {item["availability"] for item in payload["tradeDates"]} == {"COMPLETE"}
    assert payload["formula"] == {
        "formulaKey": "sector-cross-sectional-momentum",
        "formulaVersion": 1,
        "periods": [1, 5, 10, 20, 30],
        "historyRanges": [20, 30, 60],
        "scopes": [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ],
        "directions": ["GAINERS", "LOSERS"],
    }


def test_rankings_returns_full_gain_and_loss_lists_with_stable_strength_ranks_in_five_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, gainers = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            params={"tradeDate": TARGET_DATE.isoformat(), "scope": "LEVEL_1", "debug": 1},
        ),
    )
    losers = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={
            "tradeDate": TARGET_DATE.isoformat(),
            "scope": "LEVEL_1",
            "direction": "LOSERS",
        },
    )

    assert gainers.status_code == 200
    assert losers.status_code == 200
    assert sql_count == 5
    gain_payload = gainers.json()
    loss_payload = losers.json()
    assert gain_payload["status"] == "READY"
    assert gain_payload["ranking"]["totalCount"] == 2
    assert gain_payload["ranking"]["calculableCount"] == 2
    assert [row["sectorCode"] for row in gain_payload["ranking"]["rows"]] == [
        "BK1001.DC",
        "BK1002.DC",
    ]
    assert [row["sectorCode"] for row in loss_payload["ranking"]["rows"]] == [
        "BK1002.DC",
        "BK1001.DC",
    ]
    gain_ranks = {
        row["sectorCode"]: row["strengthRank"] for row in gain_payload["ranking"]["rows"]
    }
    loss_ranks = {
        row["sectorCode"]: row["strengthRank"] for row in loss_payload["ranking"]["rows"]
    }
    assert gain_ranks == loss_ranks == {"BK1001.DC": 1, "BK1002.DC": 2}
    assert gain_payload["debugInfo"]["sampleSectorCodes"] == ["BK1001.DC", "BK1002.DC"]


def test_history_returns_current_global_and_parent_ranks_and_sixty_slots_in_five_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/history",
            params={
                "tradeDate": TARGET_DATE.isoformat(),
                "scope": "LEVEL_1_CHILDREN",
                "level1Code": "BK1001.DC",
                "period": 1,
                "historyRange": 60,
                "sectorCode": "BK1101.DC",
            },
        ),
    )

    assert response.status_code == 200
    assert sql_count == 5
    payload = response.json()
    assert payload["status"] == "READY"
    assert len(payload["rollingReturns"]) == 60
    assert len(payload["historicalRanks"]) == 60
    assert [row["tradeDate"] for row in payload["rollingReturns"]] == [
        row["tradeDate"] for row in payload["historicalRanks"]
    ]
    assert payload["detail"]["currentScopeTotalCount"] == 2
    assert payload["detail"]["globalLevelTotalCount"] == 3
    assert payload["detail"]["parentTotalCount"] == 2
    assert payload["detail"]["scopeTitle"] == "一级甲内二级行业"


def test_explicit_partial_keeps_full_pool_and_null_row_without_fallback(app_client, db_session) -> None:
    _seed_sector_analysis(db_session)
    db_session.delete(
        db_session.scalar(
            select(DcDaily).where(
                DcDaily.ts_code == "BK1002.DC",
                DcDaily.trade_date == TARGET_DATE,
                DcDaily.category == "行业板块",
            )
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"tradeDate": TARGET_DATE.isoformat(), "scope": "LEVEL_1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["tradingDay"]["expectedAvailability"] == "PARTIAL"
    assert payload["tradingDay"]["observedTradeDate"] == TARGET_DATE.isoformat()
    assert payload["ranking"]["totalCount"] == 2
    assert payload["ranking"]["calculableCount"] == 1
    assert payload["ranking"]["rows"][-1]["sectorCode"] == "BK1002.DC"
    assert payload["ranking"]["rows"][-1]["returnPct"] is None


def test_default_partial_falls_back_to_latest_complete_day_and_reports_delayed(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    db_session.delete(
        db_session.scalar(
            select(DcDaily).where(
                DcDaily.ts_code == "BK1202.DC",
                DcDaily.trade_date == TARGET_DATE,
                DcDaily.category == "行业板块",
            )
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"scope": "LEVEL_1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DELAYED"
    assert payload["exceptionCode"] == "SA_SOURCE_DELAYED"
    assert payload["tradingDay"]["expectedTradeDate"] == TARGET_DATE.isoformat()
    assert payload["tradingDay"]["observedTradeDate"] == OPEN_DATES[-2].isoformat()
    assert payload["tradingDay"]["expectedAvailability"] == "PARTIAL"
    assert payload["tradingDay"]["observedAvailability"] == "COMPLETE"


def test_explicit_missing_day_is_empty_and_never_falls_back(app_client, db_session) -> None:
    _seed_sector_analysis(db_session)
    for row in db_session.scalars(
        select(DcDaily).where(
            DcDaily.trade_date == TARGET_DATE,
            DcDaily.category == "行业板块",
        )
    ).all():
        db_session.delete(row)
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"tradeDate": TARGET_DATE.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "EMPTY"
    assert payload["exceptionCode"] == "SA_SOURCE_EMPTY"
    assert payload["tradingDay"]["expectedAvailability"] == "MISSING"
    assert payload["tradingDay"]["observedTradeDate"] == TARGET_DATE.isoformat()
    assert payload["ranking"] is None


def test_meta_keeps_partial_missing_days_and_ignores_codes_outside_current_hierarchy(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    partial_date = OPEN_DATES[-2]
    missing_date = OPEN_DATES[-3]
    db_session.delete(
        db_session.scalar(
            select(DcDaily).where(
                DcDaily.ts_code == "BK1202.DC",
                DcDaily.trade_date == partial_date,
                DcDaily.category == "行业板块",
            )
        )
    )
    for row in db_session.scalars(
        select(DcDaily).where(
            DcDaily.trade_date == missing_date,
            DcDaily.category == "行业板块",
        )
    ).all():
        db_session.delete(row)
    db_session.add(
        DcDaily(
            ts_code="BK9999.DC",
            trade_date=missing_date,
            category="行业板块",
            close=Decimal("100"),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            change=Decimal("1"),
            pct_change=Decimal("1"),
            vol=Decimal("1"),
            amount=Decimal("1"),
            swing=Decimal("1"),
            turnover_rate=Decimal("1"),
        )
    )
    db_session.commit()

    payload = app_client.get("/api/v1/wealth/market/sector-analysis/meta").json()
    by_date = {item["tradeDate"]: item for item in payload["tradeDates"]}
    assert by_date[partial_date.isoformat()] == {
        "tradeDate": partial_date.isoformat(),
        "availability": "PARTIAL",
        "expectedSectorCount": 7,
        "validSectorCount": 6,
    }
    assert by_date[missing_date.isoformat()] == {
        "tradeDate": missing_date.isoformat(),
        "availability": "MISSING",
        "expectedSectorCount": 7,
        "validSectorCount": 0,
    }


def test_history_retains_missing_date_slot_instead_of_filling_or_dropping_it(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    missing_date = OPEN_DATES[-10]
    db_session.delete(
        db_session.scalar(
            select(DcDaily).where(
                DcDaily.ts_code == "BK1101.DC",
                DcDaily.trade_date == missing_date,
                DcDaily.category == "行业板块",
            )
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/history",
        params={
            "scope": "LEVEL_1_CHILDREN",
            "level1Code": "BK1001.DC",
            "period": 1,
            "historyRange": 20,
            "sectorCode": "BK1101.DC",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    return_by_date = {item["tradeDate"]: item for item in payload["rollingReturns"]}
    rank_by_date = {item["tradeDate"]: item for item in payload["historicalRanks"]}
    assert return_by_date[missing_date.isoformat()]["returnPct"] is None
    assert rank_by_date[missing_date.isoformat()]["strengthRank"] is None
    assert rank_by_date[missing_date.isoformat()]["calculableCount"] == 1
    assert rank_by_date[missing_date.isoformat()]["totalCount"] == 2


def test_api_rejects_unknown_duplicate_direction_on_history_and_invalid_closure(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    cases = (
        "/api/v1/wealth/market/sector-analysis/meta?unknown=1",
        "/api/v1/wealth/market/sector-analysis/momentum/rankings?period=1&period=5",
        (
            "/api/v1/wealth/market/sector-analysis/momentum/history"
            "?sectorCode=BK1001.DC&direction=GAINERS"
        ),
        (
            "/api/v1/wealth/market/sector-analysis/momentum/rankings"
            "?scope=LEVEL_2_CHILDREN&level1Code=BK1002.DC&level2Code=BK1101.DC"
        ),
    )

    for path in cases:
        response = app_client.get(path)
        assert response.status_code == 400
        assert response.json()["code"] == "SA_SCOPE_INVALID"


def test_history_rejects_sector_outside_current_pool(app_client, db_session) -> None:
    _seed_sector_analysis(db_session)
    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/history",
        params={"scope": "LEVEL_1", "sectorCode": "BK1101.DC"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SA_SELECTION_INVALID"


def test_api_rejects_invalid_market_date_code_and_non_open_trade_date(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    closed_date = OPEN_DATES[-5]
    calendar = db_session.get(TradeCalendar, {"exchange": "SSE", "trade_date": closed_date})
    calendar.is_open = False
    db_session.commit()
    cases = (
        ("/api/v1/wealth/market/sector-analysis/meta", {"market": "US"}),
        (
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            {"tradeDate": "2026-02-30"},
        ),
        (
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            {"scope": "LEVEL_1_CHILDREN", "level1Code": "bk1001.dc"},
        ),
        (
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            {"tradeDate": closed_date.isoformat()},
        ),
    )
    for path, params in cases:
        response = app_client.get(path, params=params)
        assert response.status_code == 400
        assert response.json()["code"] == "SA_SCOPE_INVALID"


def test_meta_hierarchy_failure_is_safe_http_500(app_client, db_session) -> None:
    _ensure_tables(db_session)
    response = app_client.get("/api/v1/wealth/market/sector-analysis/meta")
    assert response.status_code == 500
    assert response.json()["code"] == "SA_HIERARCHY_UNAVAILABLE"
    assert "SELECT" not in response.text


def test_rankings_hierarchy_and_query_failures_use_safe_business_error_shells(
    app_client,
    db_session,
) -> None:
    _ensure_tables(db_session)
    hierarchy_payload = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"debug": 1},
    ).json()
    assert hierarchy_payload["status"] == "ERROR"
    assert hierarchy_payload["exceptionCode"] == "SA_HIERARCHY_UNAVAILABLE"
    assert "hierarchy" not in hierarchy_payload["message"].lower()

    _seed_sector_analysis(db_session)
    DcDaily.__table__.drop(db_session.get_bind())
    query_response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"debug": 1},
    )
    assert query_response.status_code == 200
    query_payload = query_response.json()
    assert query_payload["status"] == "ERROR"
    assert query_payload["exceptionCode"] == "SA_QUERY_FAILED"
    assert "SELECT" not in query_response.text
    assert "dc_daily" not in query_response.text


def test_debug_payload_is_hidden_outside_local_dev_and_test(app_client, db_session, monkeypatch) -> None:
    _seed_sector_analysis(db_session)
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv(
        "GOLDENSHARE_ENV_FILE",
        "/private/tmp/sector-analysis-missing.env",
    )
    get_settings.cache_clear()
    try:
        response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            params={"debug": 1},
        )
        assert response.status_code == 200
        assert response.json()["debugInfo"] is None
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        get_settings.cache_clear()


def test_quote_auth_requirement_is_reused(app_client, monkeypatch) -> None:
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        response = app_client.get("/api/v1/wealth/market/sector-analysis/meta")
        assert response.status_code == 401
        assert response.json()["code"] == "auth_required"
    finally:
        monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
        get_settings.cache_clear()
