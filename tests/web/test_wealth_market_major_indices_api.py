from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing


_INDEX_CODES = [
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "899050.BJ",
    "000510.SH",
    "000016.SH",
]


def _ensure_major_indices_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        IndexDailyServing.__table__,
        IndexBasic.__table__,
    ]:
        table.create(bind, checkfirst=True)


def test_major_indices_endpoint_returns_fixed_10_rows(app_client, db_session) -> None:
    _ensure_major_indices_tables(db_session)

    db_session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 4, 27),
                is_open=True,
                pretrade_date=date(2026, 4, 24),
            ),
            TradeCalendar(
                exchange="SSE",
                trade_date=date(2026, 4, 28),
                is_open=True,
                pretrade_date=date(2026, 4, 27),
            ),
        ]
    )

    for index, ts_code in enumerate(_INDEX_CODES):
        db_session.add(
            IndexBasic(
                ts_code=ts_code,
                name=f"指数{index + 1}",
                market="SSE",
            )
        )
        db_session.add(
            IndexDailyServing(
                ts_code=ts_code,
                trade_date=date(2026, 4, 28),
                open=Decimal("1000.0000"),
                high=Decimal("1010.0000"),
                low=Decimal("990.0000"),
                close=Decimal(f"{1000 + index * 10:.4f}"),
                pre_close=Decimal("1000.0000"),
                change_amount=Decimal("5.0000"),
                pct_chg=Decimal("0.5000"),
                vol=Decimal("1000.0000"),
                amount=Decimal("5000000.0000"),
                source="tushare",
            )
        )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/major-indices", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tradingDay"]["tradeDate"] == "2026-04-28"
    assert payload["majorIndices"]["definition"]["fixedCount"] == 10
    assert len(payload["majorIndices"]["rows"]) == 10
    assert [row["subject"]["subjectCode"] for row in payload["majorIndices"]["rows"]] == _INDEX_CODES
    assert payload["majorIndices"]["rows"][0]["subject"]["subjectName"] == "指数1"
    assert payload["majorIndices"]["rows"][0]["direction"] == "UP"
    assert payload["pageStatus"]["status"] == "READY"
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "majorIndices"


def test_major_indices_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/major-indices", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"

