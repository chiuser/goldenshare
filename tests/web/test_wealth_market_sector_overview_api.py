from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.models.core.board_moneyflow_dc import BoardMoneyflowDc
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.trade_calendar import TradeCalendar


def _ensure_sector_overview_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [TradeCalendar.__table__, DcDaily.__table__, DcIndex.__table__, BoardMoneyflowDc.__table__]:
        table.create(bind, checkfirst=True)


def _seed_sector_overview_facts(db_session, *, trade_date: date) -> None:
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=trade_date,
            is_open=True,
            pretrade_date=date(2026, 4, 27),
        )
    )
    category_specs = [
        ("行业板块", "IND", 7, Decimal("4.50")),
        ("概念板块", "CON", 7, Decimal("3.80")),
        ("地域板块", "REG", 6, Decimal("3.20")),
    ]
    for category, prefix, count, base_pct in category_specs:
        for idx in range(count):
            ts_code = f"{prefix}{idx + 1:03d}.BK"
            pct_change = base_pct - Decimal(idx) * Decimal("1.10")
            db_session.add(
                DcDaily(
                    ts_code=ts_code,
                    trade_date=trade_date,
                    category=category,
                    close=Decimal("100.0000"),
                    open=Decimal("99.0000"),
                    high=Decimal("101.0000"),
                    low=Decimal("98.0000"),
                    change=Decimal("1.0000"),
                    pct_change=pct_change,
                    vol=Decimal("100000.0000"),
                    amount=Decimal("250000000.0000"),
                    swing=Decimal("2.0000"),
                    turnover_rate=Decimal("3.0000"),
                )
            )
            db_session.add(
                DcIndex(
                    ts_code=ts_code,
                    trade_date=trade_date,
                    name=f"{category}{idx + 1}",
                    idx_type=category,
                    leading=f"领涨股{idx + 1}",
                    leading_code=f"000{idx + 1:03d}.SZ",
                    pct_change=pct_change,
                    leading_pct=Decimal("10.0000"),
                    total_mv=Decimal("10000000000.0000"),
                    turnover_rate=Decimal("2.5000"),
                    up_num=20 + idx,
                    down_num=5,
                    level="一级",
                )
            )
    content_specs = [("行业", "IND"), ("概念", "CON"), ("地域", "REG")]
    for content_type, prefix in content_specs:
        for idx in range(5):
            db_session.add(
                BoardMoneyflowDc(
                    trade_date=trade_date,
                    content_type=content_type,
                    name=f"{content_type}资金{idx + 1}",
                    ts_code=f"{prefix}{idx + 1:03d}.BK",
                    pct_change=Decimal("1.0000"),
                    close=Decimal("100.0000"),
                    net_amount=Decimal("1000000000.0000") - Decimal(idx) * Decimal("500000000.0000"),
                    net_amount_rate=Decimal("0.3000"),
                    buy_elg_amount=Decimal("100000000.0000"),
                    buy_elg_amount_rate=Decimal("0.0300"),
                    buy_lg_amount=Decimal("200000000.0000"),
                    buy_lg_amount_rate=Decimal("0.0600"),
                    buy_md_amount=Decimal("300000000.0000"),
                    buy_md_amount_rate=Decimal("0.0900"),
                    buy_sm_amount=Decimal("400000000.0000"),
                    buy_sm_amount_rate=Decimal("0.1200"),
                    buy_sm_amount_stock="样本股",
                    rank=idx + 1,
                )
            )
    db_session.commit()


def test_market_sector_overview_endpoint_returns_columns_heatmap_and_debug(app_client, db_session) -> None:
    _ensure_sector_overview_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_sector_overview_facts(db_session, trade_date=target_date)

    response = app_client.get("/api/v1/wealth/market/sector-overview", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["tradingDay"]["tradeDate"] == "2026-04-28"
    assert payload["sectorOverview"]["tradeDate"] == "2026-04-28"
    assert payload["pageStatus"]["status"] == "READY"
    assert payload["sectorOverview"]["status"] == "READY"
    assert [column["columnKey"] for column in payload["sectorOverview"]["columns"]] == [
        "industryTopGainers",
        "conceptTopGainers",
        "regionTopGainers",
        "fundIn",
        "industryTopLosers",
        "conceptTopLosers",
        "regionTopLosers",
        "fundOut",
    ]
    assert all(len(column["rows"]) == 5 for column in payload["sectorOverview"]["columns"])
    assert payload["sectorOverview"]["columns"][0]["rows"][0]["subject"]["subjectName"] == "行业板块1"
    assert payload["sectorOverview"]["columns"][0]["rows"][0]["metric"]["displayText"] == "+4.50%"
    assert payload["sectorOverview"]["columns"][3]["rows"][0]["metric"]["displayText"] == "+10.0亿"
    assert len(payload["sectorOverview"]["heatMapItems"]) == 20
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "sectorOverview"
    assert payload["debugInfo"]["exceptions"] == []

    no_debug_response = app_client.get("/api/v1/wealth/market/sector-overview", params={"tradeDate": "2026-04-28"})
    assert no_debug_response.status_code == 200
    no_debug_payload = no_debug_response.json()
    assert "debugInfo" not in no_debug_payload or no_debug_payload["debugInfo"] is None


def test_market_sector_overview_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/sector-overview", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
