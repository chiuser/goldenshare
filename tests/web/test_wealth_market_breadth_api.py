from __future__ import annotations

from datetime import date, timedelta

from src.biz.api.wealth.market.breadth import get_market_breadth_query_service
from src.biz.queries.wealth.market.breadth.breadth_fact_query import (
    BreadthDistributionBuckets,
    BreadthFactDuplicatedError,
    BreadthFactRow,
)
from src.biz.queries.wealth.market.breadth.breadth_query_service import MarketBreadthQueryService
from src.foundation.models.core.trade_calendar import TradeCalendar


def _ensure_breadth_tables(db_session) -> None:
    TradeCalendar.__table__.create(db_session.get_bind(), checkfirst=True)


def _seed_trade_calendar(db_session, *, end_date: date, days: int = 62) -> list[date]:
    trade_dates = [end_date - timedelta(days=days - 1 - idx) for idx in range(days)]
    for idx, trade_day in enumerate(trade_dates):
        prev_trade_day = trade_dates[idx - 1] if idx > 0 else None
        db_session.add(
            TradeCalendar(
                exchange="SSE",
                trade_date=trade_day,
                is_open=True,
                pretrade_date=prev_trade_day,
            )
        )
    db_session.commit()
    return trade_dates


def _fact(
    trade_day: date,
    *,
    up_count: int = 3421,
    down_count: int = 1488,
    flat_count: int = 219,
) -> BreadthFactRow:
    total_count = up_count + down_count + flat_count
    return BreadthFactRow(
        trade_date=trade_day,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        total_count=total_count,
        red_rate=round(up_count / total_count * 100, 2) if total_count else 0.0,
        distribution_buckets=BreadthDistributionBuckets(
            down_gt_10_count=4,
            down_7_10_count=8,
            down_5_7_count=36,
            down_3_5_count=184,
            down_0_3_count=1256,
            up_0_3_count=2860,
            up_3_5_count=446,
            up_5_7_count=86,
            up_7_10_count=21,
            up_gt_10_count=8,
        ),
    )


class FakeBreadthFactQuery:
    def __init__(
        self,
        *,
        facts_by_date: dict[date, BreadthFactRow] | None = None,
        observed_trade_date: date | None = None,
        duplicate_date: date | None = None,
        fail_on: str | None = None,
    ) -> None:
        self._facts_by_date = facts_by_date or {}
        self._observed_trade_date = observed_trade_date
        self._duplicate_date = duplicate_date
        self._fail_on = fail_on

    def load_observed_trade_date(self) -> date | None:
        if self._fail_on == "observed":
            raise RuntimeError("clickhouse observed query failed")
        return self._observed_trade_date

    def load_one(self, *, trade_date: date) -> BreadthFactRow | None:
        if self._fail_on == "one":
            raise RuntimeError("clickhouse fact query failed")
        if self._duplicate_date == trade_date:
            raise BreadthFactDuplicatedError(trade_date=trade_date, row_count=2)
        return self._facts_by_date.get(trade_date)

    def load_many(self, *, trade_dates: list[date]) -> list[BreadthFactRow]:
        if self._fail_on == "many":
            raise RuntimeError("clickhouse history query failed")
        if self._duplicate_date is not None and self._duplicate_date in trade_dates:
            raise BreadthFactDuplicatedError(trade_date=self._duplicate_date, row_count=2)
        return [self._facts_by_date[trade_day] for trade_day in trade_dates if trade_day in self._facts_by_date]


def _override_breadth_service(fake_query: FakeBreadthFactQuery) -> None:
    from src.app.web.app import app

    app.dependency_overrides[get_market_breadth_query_service] = lambda: MarketBreadthQueryService(
        fact_query=fake_query
    )


def test_market_breadth_endpoint_returns_clickhouse_metrics_and_history(app_client, db_session) -> None:
    _ensure_breadth_tables(db_session)
    target_date = date(2026, 4, 28)
    trade_dates = _seed_trade_calendar(db_session, end_date=target_date)
    facts_by_date = {
        trade_day: _fact(trade_day, up_count=3000 + idx, down_count=1500 - idx, flat_count=200)
        for idx, trade_day in enumerate(trade_dates)
    }
    facts_by_date[target_date] = _fact(target_date, up_count=3421, down_count=1488, flat_count=219)
    _override_breadth_service(
        FakeBreadthFactQuery(facts_by_date=facts_by_date, observed_trade_date=target_date)
    )

    response = app_client.get("/api/v1/wealth/market/breadth", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["tradingDay"]["tradeDate"] == "2026-04-28"
    assert payload["breadth"]["tradeDate"] == "2026-04-28"
    assert payload["breadth"]["metrics"]["upCount"] == 3421
    assert payload["breadth"]["metrics"]["downCount"] == 1488
    assert payload["breadth"]["metrics"]["flatCount"] == 219
    assert payload["breadth"]["metrics"]["totalCount"] == 5128
    assert payload["breadth"]["metrics"]["redRate"] == 66.71
    metrics_buckets = payload["breadth"]["metrics"]["distributionBuckets"]
    assert metrics_buckets["up7To10Count"] == 21
    assert metrics_buckets["upGt10Count"] == 8
    assert metrics_buckets["down7To10Count"] == 8
    assert metrics_buckets["downGt10Count"] == 4
    old_up_bucket_key = "up" + "Gt7Count"
    old_down_bucket_key = "down" + "Gt7Count"
    assert old_up_bucket_key not in metrics_buckets
    assert old_down_bucket_key not in metrics_buckets
    assert len(payload["breadth"]["historyByRange"]["1m"]) == 22
    assert len(payload["breadth"]["historyByRange"]["3m"]) == 62
    first_one_month_point = payload["breadth"]["historyByRange"]["1m"][0]
    assert set(first_one_month_point.keys()) == {
        "tradeDate",
        "upCount",
        "downCount",
        "flatCount",
        "totalCount",
        "redRate",
        "distributionBuckets",
    }
    history_buckets = first_one_month_point["distributionBuckets"]
    assert history_buckets["down7To10Count"] == 8
    assert history_buckets["downGt10Count"] == 4
    assert old_up_bucket_key not in history_buckets
    assert old_down_bucket_key not in history_buckets
    assert payload["pageStatus"]["status"] == "READY"
    assert payload["debugInfo"]["modules"][0]["moduleKey"] == "breadth"

    no_debug_response = app_client.get("/api/v1/wealth/market/breadth", params={"tradeDate": "2026-04-28"})
    assert no_debug_response.status_code == 200
    no_debug_payload = no_debug_response.json()
    assert "debugInfo" not in no_debug_payload or no_debug_payload["debugInfo"] is None


def test_market_breadth_marks_delayed_without_postgres_fallback(app_client, db_session) -> None:
    _ensure_breadth_tables(db_session)
    target_date = date(2026, 4, 28)
    trade_dates = _seed_trade_calendar(db_session, end_date=target_date)
    observed_trade_date = target_date - timedelta(days=1)
    facts_by_date = {trade_day: _fact(trade_day) for trade_day in trade_dates if trade_day <= observed_trade_date}
    _override_breadth_service(
        FakeBreadthFactQuery(facts_by_date=facts_by_date, observed_trade_date=observed_trade_date)
    )

    response = app_client.get("/api/v1/wealth/market/breadth", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["pageStatus"]["status"] == "PARTIAL"
    assert payload["breadth"]["metrics"]["totalCount"] == 0
    assert payload["debugInfo"]["modules"][0]["status"] == "DELAYED"
    assert payload["debugInfo"]["exceptions"][0]["code"] == "BR_SOURCE_DELAYED"


def test_market_breadth_marks_empty_when_fact_table_has_no_observed_date(app_client, db_session) -> None:
    _ensure_breadth_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_trade_calendar(db_session, end_date=target_date)
    _override_breadth_service(FakeBreadthFactQuery(observed_trade_date=None))

    response = app_client.get("/api/v1/wealth/market/breadth", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["pageStatus"]["status"] == "EMPTY"
    assert payload["breadth"]["metrics"]["totalCount"] == 0
    assert payload["debugInfo"]["modules"][0]["status"] == "EMPTY"
    assert payload["debugInfo"]["exceptions"][0]["code"] == "BR_SOURCE_EMPTY"


def test_market_breadth_reports_history_incomplete(app_client, db_session) -> None:
    _ensure_breadth_tables(db_session)
    target_date = date(2026, 4, 28)
    trade_dates = _seed_trade_calendar(db_session, end_date=target_date)
    facts_by_date = {trade_day: _fact(trade_day) for trade_day in trade_dates[-10:]}
    _override_breadth_service(
        FakeBreadthFactQuery(facts_by_date=facts_by_date, observed_trade_date=target_date)
    )

    response = app_client.get("/api/v1/wealth/market/breadth", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["pageStatus"]["status"] == "PARTIAL"
    assert payload["debugInfo"]["modules"][0]["status"] == "PARTIAL"
    assert payload["debugInfo"]["exceptions"][0]["code"] == "BR_HISTORY_INCOMPLETE"


def test_market_breadth_reports_duplicated_fact_rows(app_client, db_session) -> None:
    _ensure_breadth_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_trade_calendar(db_session, end_date=target_date)
    _override_breadth_service(
        FakeBreadthFactQuery(observed_trade_date=target_date, duplicate_date=target_date)
    )

    response = app_client.get("/api/v1/wealth/market/breadth", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["pageStatus"]["status"] == "ERROR"
    assert payload["debugInfo"]["exceptions"][0]["code"] == "BR_FACT_DUPLICATED"
    assert payload["debugInfo"]["exceptions"][0]["details"]["rowCount"] == 2


def test_market_breadth_reports_clickhouse_query_failure(app_client, db_session) -> None:
    _ensure_breadth_tables(db_session)
    target_date = date(2026, 4, 28)
    _seed_trade_calendar(db_session, end_date=target_date)
    _override_breadth_service(FakeBreadthFactQuery(observed_trade_date=target_date, fail_on="one"))

    response = app_client.get("/api/v1/wealth/market/breadth", params={"tradeDate": "2026-04-28", "debug": 1})
    assert response.status_code == 200
    payload = response.json()

    assert payload["pageStatus"]["status"] == "ERROR"
    assert payload["debugInfo"]["exceptions"][0]["code"] == "BR_QUERY_FAILED"


def test_market_breadth_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/breadth", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
