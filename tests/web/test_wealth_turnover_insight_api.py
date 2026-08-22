from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from src.foundation.config.settings import get_settings
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import (
    WealthMarketTurnoverSnapshot,
)


def _minute_grid() -> list[str]:
    labels: list[str] = []
    for minute in range(9 * 60 + 30, 11 * 60 + 31):
        labels.append(f"{minute // 60:02d}:{minute % 60:02d}")
    for minute in range(13 * 60 + 1, 15 * 60 + 1):
        labels.append(f"{minute // 60:02d}:{minute % 60:02d}")
    return labels


def _ensure_tables(db_session) -> None:
    TradeCalendar.__table__.create(db_session.connection(), checkfirst=True)
    WealthMarketTurnoverSnapshot.__table__.create(db_session.connection(), checkfirst=True)


def _seed_day(db_session, *, trade_date: date, previous_date: date | None, amount: Decimal) -> None:
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=trade_date,
            is_open=True,
            pretrade_date=previous_date,
        )
    )
    points = [{"tradeTime": label, "amount": str(amount)} for label in _minute_grid()]
    total = amount * Decimal(len(points))
    db_session.add(
        WealthMarketTurnoverSnapshot(
            type="stock",
            market="CN_A",
            trade_date=trade_date,
            freq=1,
            latest_trade_time=datetime.combine(trade_date, time(15, 0)),
            security_count=5000,
            source_row_count=len(points) * 5000,
            total_amount=total,
            total_vol=1,
            points_json=points,
            build_status="READY",
            build_version="v1",
            built_at=datetime(2026, 8, 22, 20, 0),
            build_note=None,
        )
    )


def test_turnover_insight_api_returns_complete_real_route_payload(app_client, db_session) -> None:
    _ensure_tables(db_session)
    previous = date(2026, 8, 20)
    current = date(2026, 8, 21)
    _seed_day(db_session, trade_date=previous, previous_date=date(2026, 8, 19), amount=Decimal("250000"))
    _seed_day(db_session, trade_date=current, previous_date=previous, amount=Decimal("200000"))
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/turnover-insight",
        params={"market": "CN_A", "tradeDate": current.isoformat(), "debug": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["tradingDay"]["expectedTradeDate"] == current.isoformat()
    assert payload["tradingDay"]["observedTradeDate"] == current.isoformat()
    assert payload["tradingDay"]["previousObservedTradeDate"] == previous.isoformat()
    assert payload["summary"]["current"]["displayText"] == "482亿"
    assert payload["summary"]["previous"]["displayText"] == "603亿"
    assert payload["summary"]["delta"]["displayText"] == "-121亿"
    assert len(payload["series"]) == 241
    assert sum(point["showAxisLabel"] for point in payload["series"]) == 17
    assert payload["debugInfo"]["candidateCount"] == 2
    assert len(response.content) < 64 * 1024


def test_turnover_insight_api_returns_partial_without_previous(app_client, db_session) -> None:
    _ensure_tables(db_session)
    current = date(2026, 8, 21)
    _seed_day(db_session, trade_date=current, previous_date=date(2026, 8, 20), amount=Decimal("200000"))
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/turnover-insight",
        params={"tradeDate": current.isoformat()},
    )

    payload = response.json()
    assert payload["status"] == "PARTIAL"
    assert payload["deltaAxis"] is None
    assert len(payload["series"]) == 241
    assert all(point["previousAmountYi"] is None for point in payload["series"])
    assert all(point["deltaAmountYi"] is None for point in payload["series"])


def test_turnover_insight_api_uses_strict_adjacent_delayed_pair(app_client, db_session) -> None:
    _ensure_tables(db_session)
    expected = date(2026, 8, 21)
    delayed_current = date(2026, 8, 20)
    delayed_previous = date(2026, 8, 19)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=expected,
            is_open=True,
            pretrade_date=delayed_current,
        )
    )
    _seed_day(
        db_session,
        trade_date=delayed_previous,
        previous_date=date(2026, 8, 18),
        amount=Decimal("250000"),
    )
    _seed_day(
        db_session,
        trade_date=delayed_current,
        previous_date=delayed_previous,
        amount=Decimal("200000"),
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/turnover-insight",
        params={"tradeDate": expected.isoformat(), "debug": 1},
    )

    payload = response.json()
    assert payload["status"] == "DELAYED"
    assert payload["tradingDay"]["expectedTradeDate"] == expected.isoformat()
    assert payload["tradingDay"]["observedTradeDate"] == delayed_current.isoformat()
    assert payload["exceptionCode"] == "TI_SOURCE_DELAYED"


def test_turnover_insight_api_returns_empty_when_no_current_snapshot_exists(
    app_client,
    db_session,
) -> None:
    _ensure_tables(db_session)
    current = date(2026, 8, 21)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=current,
            is_open=True,
            pretrade_date=date(2026, 8, 20),
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/turnover-insight",
        params={"tradeDate": current.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "EMPTY"
    assert payload["series"] == []
    assert payload["upperAxis"] is None
    assert payload["deltaAxis"] is None
    assert payload["exceptionCode"] == "TI_CURRENT_SNAPSHOT_MISSING"


def test_turnover_insight_api_returns_error_for_invalid_current_snapshot(
    app_client,
    db_session,
) -> None:
    _ensure_tables(db_session)
    current = date(2026, 8, 21)
    _seed_day(
        db_session,
        trade_date=current,
        previous_date=date(2026, 8, 20),
        amount=Decimal("200000"),
    )
    db_session.flush()
    snapshot = db_session.query(WealthMarketTurnoverSnapshot).filter_by(
        type="stock",
        market="CN_A",
        trade_date=current,
        freq=1,
    ).one()
    snapshot.points_json = [{"tradeTime": "09:30", "amount": "-1"}]
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/turnover-insight",
        params={"tradeDate": current.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ERROR"
    assert payload["series"] == []
    assert payload["exceptionCode"] == "TI_POINT_QUALITY_INVALID"
    assert "points_json" not in response.text


def test_turnover_insight_api_disables_debug_outside_allowed_environments(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    _ensure_tables(db_session)
    current = date(2026, 8, 21)
    _seed_day(db_session, trade_date=current, previous_date=date(2026, 8, 20), amount=Decimal("200000"))
    db_session.commit()
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", "/private/tmp/turnover-insight-missing.env")
    get_settings.cache_clear()

    response = app_client.get(
        "/api/v1/wealth/market/turnover-insight",
        params={"tradeDate": current.isoformat(), "debug": 1},
    )

    assert response.status_code == 200
    assert response.json()["debugInfo"] is None


def test_turnover_insight_api_rejects_invalid_contract_parameters(app_client) -> None:
    unsupported_market = app_client.get(
        "/api/v1/wealth/market/turnover-insight",
        params={"market": "US"},
    )
    invalid_debug = app_client.get(
        "/api/v1/wealth/market/turnover-insight",
        params={"debug": 2},
    )
    invalid_date = app_client.get(
        "/api/v1/wealth/market/turnover-insight",
        params={"tradeDate": "2026-99-99"},
    )

    assert unsupported_market.status_code == 400
    assert invalid_debug.status_code == 422
    assert invalid_date.status_code == 422
