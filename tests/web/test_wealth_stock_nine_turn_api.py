from __future__ import annotations

from datetime import date, datetime, timezone

from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_qfq_nineturn_daily import (
    EquityQfqNineTurnDaily,
)
from src.foundation.models.core_serving.security_serving import Security


def _ensure_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in (
        EquityFactorPro.__table__,
        EquityQfqNineTurnDaily.__table__,
    ):
        table.create(bind, checkfirst=True)


def _seed_stock(db_session, *, missing_dates: set[date] | None = None) -> None:
    _ensure_tables(db_session)
    missing_dates = missing_dates or set()
    trade_dates = (date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13))
    db_session.add(
        Security(
            ts_code="000001.SZ",
            symbol="000001",
            name="平安银行",
            exchange="SZSE",
            list_status="L",
            security_type="EQUITY",
            source="tushare",
        )
    )
    db_session.add_all(
        TradeCalendar(
            exchange="SSE",
            trade_date=trade_date,
            is_open=True,
            pretrade_date=(trade_dates[index - 1] if index else date(2026, 8, 10)),
        )
        for index, trade_date in enumerate(trade_dates)
    )
    counts = (1, 9, 10)
    for trade_date, count in zip(trade_dates, counts, strict=True):
        db_session.add(
            EquityFactorPro(
                ts_code="000001.SZ",
                trade_date=trade_date,
                close_qfq=10.0 + count,
                source="tushare",
            )
        )
        if trade_date not in missing_dates:
            db_session.add(
                EquityQfqNineTurnDaily(
                    ts_code="000001.SZ",
                    trade_date=trade_date,
                    up_count=count,
                    down_count=0,
                    nine_up_turn="+9" if count >= 9 else None,
                    nine_down_turn=None,
                    formula_version=1,
                    published_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
                )
            )
    db_session.commit()


def test_daily_api_maps_only_counts_one_through_nine(app_client, db_session) -> None:
    _seed_stock(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/nine-turn",
        params={"tsCode": "000001.SZ", "endDate": "2026-08-13", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["period"] == "day"
    assert payload["dataStatus"]["status"] == "READY"
    assert [marker["sequenceNumber"] for marker in payload["markers"]] == [1, 9]
    assert payload["markers"][1]["completed"] is True
    assert payload["latestMarker"] is None
    assert payload["meta"]["sourceRowCount"] == 3
    assert payload["meta"]["matchedRowCount"] == 3
    assert payload["meta"]["markerCount"] == 2
    assert payload["meta"]["comparisonLag"] == 4
    assert payload["meta"]["signalThreshold"] == 9
    assert payload["meta"]["formulaVersion"] == 1


def test_daily_api_returns_partial_without_clearing_confirmed_markers(
    app_client,
    db_session,
) -> None:
    _seed_stock(db_session, missing_dates={date(2026, 8, 12)})

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/nine-turn",
        params={"tsCode": "000001.SZ", "endDate": "2026-08-13", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataStatus"]["status"] == "PARTIAL"
    assert payload["dataStatus"]["code"] == "NT_ALIGNMENT_PARTIAL"
    assert [marker["sequenceNumber"] for marker in payload["markers"]] == [1]
    assert payload["meta"]["missingRowCount"] == 1


def test_daily_api_returns_source_empty_when_serving_has_no_matching_rows(
    app_client,
    db_session,
) -> None:
    _seed_stock(
        db_session,
        missing_dates={date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13)},
    )

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/nine-turn",
        params={"tsCode": "000001.SZ", "endDate": "2026-08-13", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["markers"] == []
    assert payload["dataStatus"]["status"] == "EMPTY"
    assert payload["dataStatus"]["code"] == "NT_SOURCE_NOT_READY"


def test_daily_api_reports_delayed_when_observed_rows_trail_the_explicit_window(
    app_client,
    db_session,
) -> None:
    _seed_stock(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/nine-turn",
        params={"tsCode": "000001.SZ", "endDate": "2026-08-14", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataStatus"]["status"] == "DELAYED"
    assert payload["dataStatus"]["code"] == "NT_SOURCE_NOT_READY"
    assert payload["dataStatus"]["expectedEndDate"] == "2026-08-14"
    assert payload["dataStatus"]["observedEndDate"] == "2026-08-13"


def test_daily_api_uses_bar_window_for_pagination(app_client, db_session) -> None:
    _seed_stock(db_session)
    first = app_client.get(
        "/api/v1/wealth/market/stock-detail/nine-turn",
        params={"tsCode": "000001.SZ", "endDate": "2026-08-13", "limit": 2},
    )

    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["meta"]["hasMore"] is True
    assert first_payload["meta"]["sourceRowCount"] == 2
    second = app_client.get(
        "/api/v1/wealth/market/stock-detail/nine-turn",
        params={
            "tsCode": "000001.SZ",
            "endDate": "2026-08-13",
            "limit": 2,
            "cursor": first_payload["meta"]["nextCursor"],
        },
    )

    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["meta"]["sourceRowCount"] == 1
    assert second_payload["markers"][0]["tradeDate"] == "2026-08-11"


def test_daily_api_rejects_cursor_bound_to_another_window(app_client, db_session) -> None:
    _seed_stock(db_session)
    first = app_client.get(
        "/api/v1/wealth/market/stock-detail/nine-turn",
        params={"tsCode": "000001.SZ", "endDate": "2026-08-13", "limit": 1},
    )
    cursor = first.json()["meta"]["nextCursor"]

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/nine-turn",
        params={"tsCode": "000001.SZ", "endDate": "2026-08-12", "cursor": cursor},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "NT_REQUEST_INVALID"


def test_daily_api_rejects_unknown_repeated_and_period_parameters(
    app_client,
    db_session,
) -> None:
    _seed_stock(db_session)
    endpoint = "/api/v1/wealth/market/stock-detail/nine-turn"

    unknown = app_client.get(endpoint, params={"tsCode": "000001.SZ", "foo": "bar"})
    repeated = app_client.get(
        f"{endpoint}?tsCode=000001.SZ&limit=2&limit=3"
    )
    unsupported = app_client.get(
        endpoint,
        params={"tsCode": "000001.SZ", "period": "5"},
    )
    oversized = app_client.get(
        endpoint,
        params={"tsCode": "000001.SZ", "limit": 2001},
    )

    assert unknown.status_code == 400
    assert repeated.status_code == 400
    assert unsupported.status_code == 400
    assert oversized.status_code == 400
    assert unknown.json()["code"] == "NT_REQUEST_INVALID"
    assert repeated.json()["code"] == "NT_REQUEST_INVALID"
    assert unsupported.json()["code"] == "NT_REQUEST_INVALID"
    assert oversized.json()["code"] == "NT_REQUEST_INVALID"


def test_page_init_announces_daily_nine_turn_only_in_non_local_env(
    app_client,
    db_session,
) -> None:
    _seed_stock(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/page-init",
        params={"tsCode": "000001.SZ", "tradeDate": "2026-08-13"},
    )

    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert capabilities["supportsNineTurn"] is True
    assert capabilities["nineTurnPeriods"] == ["day"]


def test_non_local_app_does_not_mount_stock_minute_nine_turn_route(app_client) -> None:
    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/minute-nine-turn",
        params={"tsCode": "000001.SZ", "freq": 30},
    )

    assert response.status_code == 404


def test_daily_api_rejects_a_non_equity_security(app_client, db_session) -> None:
    db_session.add(
        Security(
            ts_code="000001.SH",
            symbol="000001",
            name="上证指数",
            exchange="SSE",
            list_status="L",
            security_type="INDEX",
            source="tushare",
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/nine-turn",
        params={"tsCode": "000001.SH", "endDate": "2026-08-13"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NT_NOT_FOUND"
