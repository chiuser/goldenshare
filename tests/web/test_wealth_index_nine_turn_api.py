from __future__ import annotations

from datetime import date, datetime, timezone

from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_nineturn_daily import IndexNineTurnDaily


def _ensure_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in (
        IndexFactorPro.__table__,
        IndexNineTurnDaily.__table__,
    ):
        table.create(bind, checkfirst=True)


def _seed_index(
    db_session,
    *,
    ts_code: str = "000001.SH",
    missing_dates: set[date] | None = None,
) -> None:
    _ensure_tables(db_session)
    missing_dates = missing_dates or set()
    trade_dates = (date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13))
    db_session.add_all(
        TradeCalendar(
            exchange="SSE",
            trade_date=trade_date,
            is_open=True,
            pretrade_date=(trade_dates[index - 1] if index else date(2026, 8, 10)),
        )
        for index, trade_date in enumerate(trade_dates)
    )
    for trade_date, count in zip(trade_dates, (1, 9, 10), strict=True):
        factor = IndexFactorPro(
            ts_code=ts_code,
            trade_date=trade_date,
            source="tushare",
        )
        factor.close = 3000.0 + count
        db_session.add(factor)
        if trade_date not in missing_dates:
            db_session.add(
                IndexNineTurnDaily(
                    ts_code=ts_code,
                    trade_date=trade_date,
                    close=3000.0 + count,
                    up_count=count,
                    down_count=0,
                    nine_up_turn="+9" if count >= 9 else None,
                    nine_down_turn=None,
                    formula_version=1,
                    published_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
                )
            )
    db_session.commit()


def test_daily_index_api_maps_only_one_through_nine(app_client, db_session) -> None:
    _seed_index(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/nine-turn",
        params={"tsCode": "000001.SH", "endDate": "2026-08-13", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["subjectType"] == "index"
    assert payload["period"] == "day"
    assert payload["dataStatus"]["status"] == "READY"
    assert [marker["sequenceNumber"] for marker in payload["markers"]] == [1, 9]
    assert payload["latestMarker"] is None


def test_daily_index_api_keeps_partial_markers(app_client, db_session) -> None:
    _seed_index(db_session, missing_dates={date(2026, 8, 12)})

    response = app_client.get(
        "/api/v1/wealth/market/index-detail/nine-turn",
        params={"tsCode": "000001.SH", "endDate": "2026-08-13", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataStatus"]["status"] == "PARTIAL"
    assert payload["dataStatus"]["code"] == "NT_ALIGNMENT_PARTIAL"
    assert [marker["sequenceNumber"] for marker in payload["markers"]] == [1]


def test_daily_index_api_supports_bj_and_rejects_physical_only_code(
    app_client,
    db_session,
) -> None:
    _seed_index(db_session, ts_code="899050.BJ")

    supported = app_client.get(
        "/api/v1/wealth/market/index-detail/nine-turn",
        params={"tsCode": "899050.BJ", "endDate": "2026-08-13"},
    )
    physical_only = app_client.get(
        "/api/v1/wealth/market/index-detail/nine-turn",
        params={"tsCode": "000680.SH", "endDate": "2026-08-13"},
    )

    assert supported.status_code == 200
    assert supported.json()["tsCode"] == "899050.BJ"
    assert physical_only.status_code == 404
    assert physical_only.json()["code"] == "NT_NOT_FOUND"


def test_daily_index_api_rejects_strict_parameter_violations(
    app_client,
    db_session,
) -> None:
    _seed_index(db_session)
    endpoint = "/api/v1/wealth/market/index-detail/nine-turn"

    unknown = app_client.get(endpoint, params={"tsCode": "000001.SH", "foo": "x"})
    repeated = app_client.get(f"{endpoint}?tsCode=000001.SH&limit=2&limit=3")
    unsupported = app_client.get(
        endpoint,
        params={"tsCode": "000001.SH", "period": "1"},
    )

    assert unknown.status_code == 400
    assert repeated.status_code == 400
    assert unsupported.status_code == 400
    assert unknown.json()["code"] == "NT_REQUEST_INVALID"
