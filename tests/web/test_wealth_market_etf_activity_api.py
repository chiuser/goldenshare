"""ETF Activity HTTP tests against isolated Parquet with the DG Silver schema."""

from datetime import date, datetime, timedelta
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.foundation.config.settings import Settings, get_settings

_PATH = "/api/v1/wealth/market/etf-activity"
_TODAY = date(2026, 3, 30)
_FRIDAY = date(2026, 3, 27)
_CALENDAR_START = date(2025, 12, 1)
_HOLIDAY = date(2026, 2, 17)
_MISSING_DAY = date(2026, 1, 6)
_SNAPSHOT = "a" * 64


def _code(number: int) -> str:
    return f"{510000 + number}.SH"


def _daily_path(root: Path, day: date) -> Path:
    return root / "silver/quote/etf_daily" / f"trade_date={day}" / "part-000.parquet"


def _write(connection, path: Path, sql: str, params: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.sql(sql, params=params).write_parquet(str(path))


def _write_daily(connection, path: Path, day: date, rows: list) -> None:
    # Field names/types mirror FUND_DAILY_SILVER_COLUMN_TYPES and the formal DG file.
    _write(connection, path, """
        WITH quotes AS (SELECT unnest(?::STRUCT(ts_code VARCHAR, close DOUBLE, pct_chg DOUBLE, amount DOUBLE)[]) AS q),
        daily AS (SELECT q.*, q.close / (1.0 + q.pct_chg / 100.0) AS previous_close FROM quotes)
        SELECT ts_code, ?::DATE AS trade_date, previous_close AS pre_close,
               close AS open, close AS high, close AS low, close,
               close - previous_close AS change, pct_chg, 1.0::DOUBLE AS vol, amount
        FROM daily
    """, [[dict(zip(("ts_code", "close", "pct_chg", "amount"), row)) for row in rows], day])


@pytest.fixture
def lake(tmp_path):
    root = tmp_path / "lake"
    calendar = root / "silver/calendar/trade_calendar/full/part-000.parquet"
    basic = root / f"silver/basic/etf_basic/snapshot_id={_SNAPSHOT}/part-000.parquet"
    final_day = _TODAY + timedelta(days=1)
    # Date and name columns mirror the actual DG calendar / ETF Basic projections.
    with duckdb.connect(":memory:", config={"threads": "1"}) as connection:
        _write(connection, calendar, """
            WITH days AS (
                SELECT day::DATE AS trade_date,
                       dayofweek(day) BETWEEN 1 AND 5 AND day::DATE <> ?::DATE AS is_open
                FROM generate_series(?::DATE, ?::DATE, INTERVAL 1 DAY) AS days(day)
            )
            SELECT 'SSE'::VARCHAR AS exchange, trade_date, is_open,
                   max(trade_date) FILTER (WHERE is_open) OVER (
                     ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS pretrade_date
            FROM days
        """, [_HOLIDAY, _CALENDAR_START, final_day])
        _write(connection, basic, """
            SELECT ts_code, csname, extname, cname
            FROM (VALUES
                ('510001.SH', '华夏ETF', '替代名', '华夏基金全称'),
                ('510002.SH', '  ', '扩位简称', '扩位基金全称'),
                ('510003.SH', NULL, NULL, '基金中文全称')
            ) AS names(ts_code, csname, extname, cname)
        """, [])
        day_index = 0
        for offset in range((final_day - _CALENDAR_START).days + 1):
            day = _CALENDAR_START + timedelta(days=offset)
            if day.weekday() >= 5 or day == _HOLIDAY:
                continue
            day_index += 1
            if day == _MISSING_DAY:
                continue
            if day == _TODAY:
                rows = [
                    (_code(n), 0.975 if n == 1 else 1.0, -2.5 if n == 1 else 0.0, 100 if n <= 2 else 100 - n)
                    for n in range(1, 54)
                ]
            elif day == _FRIDAY:
                # Code 1 was 54th and code 2 first. Code 5 has two extra names ahead of it.
                overrides = {1: 0, 2: 200, 54: 95.5, 55: 95.25}
                rows = [(_code(n), 1.0, 0.0, overrides.get(n, 100 - n)) for n in range(1, 56) if n != 3]
            else:
                amount = 0 if day == date(2026, 2, 18) else day_index
                rows = [(_code(1), 1.0, 0.0, amount)]
            _write_daily(connection, _daily_path(root, day), day, rows)
        # Even a syntactically valid file cannot turn Sunday into an open day.
        sunday = date(2026, 3, 29)
        _write_daily(connection, _daily_path(root, sunday), sunday, [(_code(1), 1.0, 0.0, 99999.0)])
    return SimpleNamespace(root=root, calendar=calendar, basic=basic)


def _local_settings(**values):
    return Settings(_env_file=None, WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=False, **values)


@pytest.fixture
def request_api(monkeypatch, tmp_path, lake):
    # Do not read the repo's .env or start any App lifespan tasks.
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    wiring = importlib.import_module("src.app.api.v1.router")
    from src.biz.api.wealth.market import etf_activity as api_module
    from src.foundation.clients.local_lake import etf_daily_reader

    class FixtureClock:
        @staticmethod
        def now(tz):
            assert tz.key == "Asia/Shanghai"
            return datetime.combine(_TODAY, datetime.min.time(), tzinfo=tz)

    monkeypatch.setattr(api_module, "datetime", FixtureClock)
    monkeypatch.setattr(wiring, "FORMAL_LAKE_ROOT", lake.root)
    requests = []
    reference = {"available": True, "day": _TODAY.isoformat()}

    def respond(request):
        assert str(request.url) == "http://127.0.0.1:3000/graphql"
        payload = json.loads(request.content)
        assert payload["query"].lstrip().startswith("query EtfActivityBasic")
        assert 'assetKey: {path: ["silver_etf_daily"]}' in payload["query"]
        assert "partitions: [$day], limit: 1" in payload["query"]
        requests.append(payload["variables"])
        if not reference["available"]:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": {"assetNodeOrError": {
            "__typename": "AssetNode",
            "assetMaterializations": [{
                "partition": reference["day"],
                "metadataEntries": [
                    {"label": "dagster/uri", "path": str(_daily_path(lake.root, _TODAY))},
                    {"label": "goldenshare/basic_raw_snapshot_hash", "text": _SNAPSHOT},
                    {"label": "goldenshare/basic_silver_uri", "text": str(lake.basic)},
                ],
            }],
        }}})

    client_type = httpx.Client

    def dg_client(*, trust_env):
        assert trust_env is False
        return client_type(transport=httpx.MockTransport(respond), trust_env=False)

    monkeypatch.setattr(etf_daily_reader.httpx, "Client", dg_client)
    target = APIRouter(prefix="/api/v1")
    wiring._include_local_etf_activity(
        target, _local_settings(APP_ENV="local", GOLDENSHARE_LAKE_ROOT=str(lake.root)),
    )
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(target)
    # The actual quote-auth dependency runs. With no bearer token, its injected
    # session has no DB methods, so a data read through it would fail the test.
    app.dependency_overrides[get_db_session] = object
    return TestClient(app), requests, reference


def test_real_route_uses_latest_open_day_and_orders_full_market_rankings(request_api):
    client, requests, _ = request_api
    response = client.get(_PATH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["tradeDate"] == "2026-03-30"
    assert result["previousTradeDate"] == "2026-03-27"
    assert result["oneMonthStartDate"] == "2026-02-28"
    ranking = result["ranking"]
    assert ranking["status"] == "ready" and ranking["error"] is None
    rows = ranking["rows"]
    assert len(rows) == 50
    assert [r["rank"] for r in rows] == list(range(1, 51))
    assert rows[0] == {
        "rank": 1, "tsCode": "510001.SH", "name": "华夏ETF", "closePrice": 0.975,
        "priceChangePct": -2.5, "amountYuan": 100_000, "rankChange": 53,
    }
    assert rows[1]["tsCode"] == "510002.SH"  # Same turnover as rank 1.
    assert rows[1]["name"] == "扩位简称" and rows[1]["rankChange"] == -1
    assert rows[2]["name"] == "基金中文全称" and rows[2]["rankChange"] is None
    assert rows[3]["name"] is None and rows[4]["rankChange"] == 0
    assert rows[-1]["tsCode"] == "510050.SH"
    assert requests == [{"day": "2026-03-30"}]


def test_trend_warms_up_then_keeps_open_day_gaps_and_zero_turnover(request_api):
    client, _, _ = request_api
    result = client.get(_PATH).json()
    trend = result["trend"]
    # Dec 30 is open day 22 in the fixture. The previous 19 values are 3..21.
    assert trend[0] == {
        "tradeDate": "2025-12-30", "amountYuan": 22_000, "ma5Yuan": 20_000, "ma20Yuan": 12_500,
    }
    by_day = {point["tradeDate"]: point for point in trend}
    assert by_day["2026-01-06"] == {
        "tradeDate": "2026-01-06", "amountYuan": None, "ma5Yuan": None, "ma20Yuan": None,
    }
    assert by_day["2026-01-12"]["ma5Yuan"] is None
    assert by_day["2026-01-13"]["ma5Yuan"] == 30_000
    assert by_day["2026-01-13"]["ma20Yuan"] is None
    assert by_day["2026-02-18"]["amountYuan"] == 0
    assert "2026-02-17" not in by_day and "2026-03-29" not in by_day
    assert trend[-1]["tradeDate"] == "2026-03-30"


def test_missing_prior_file_keeps_prices_and_does_not_compare_to_earlier_day(lake, request_api):
    client, _, _ = request_api
    _daily_path(lake.root, _FRIDAY).unlink()
    response = client.get(_PATH)
    assert response.status_code == 200
    result = response.json()
    assert result["previousTradeDate"] == "2026-03-27"
    assert result["ranking"]["status"] == "partial"
    assert len(result["ranking"]["rows"]) == 50
    assert all(row["rankChange"] is None for row in result["ranking"]["rows"])
    assert result["ranking"]["rows"][0]["priceChangePct"] == -2.5
    assert result["trend"][-2]["amountYuan"] is None


def test_missing_or_mismatched_dg_reference_only_fails_ranking_and_retry_recovers(request_api):
    client, requests, reference = request_api
    reference["day"] = _FRIDAY.isoformat()
    wrong_day = client.get(_PATH)
    assert wrong_day.status_code == 200 and wrong_day.json()["ranking"] == {
        "status": "error", "rows": [],
        "error": {"code": "ETF_ACTIVITY_RANKING_UNAVAILABLE", "message": "ETF 排行榜暂不可读取，请重试"},
    }
    reference.update(day=_TODAY.isoformat(), available=False)
    no_service = client.get(_PATH).json()
    assert no_service["ranking"] == wrong_day.json()["ranking"]
    assert no_service["trend"] == wrong_day.json()["trend"]
    reference["available"] = True
    retry = client.get(_PATH).json()
    assert retry["ranking"]["status"] == "ready" and retry["trend"] == no_service["trend"]
    assert len(requests) == 3


def test_missing_basic_file_and_invalid_price_only_fail_the_ranking(lake, request_api):
    client, _, _ = request_api
    basic_bytes = lake.basic.read_bytes()
    lake.basic.unlink()
    response = client.get(_PATH)
    assert response.status_code == 200 and response.json()["ranking"]["status"] == "error"
    lake.basic.write_bytes(basic_bytes)
    path = _daily_path(lake.root, _TODAY)
    with duckdb.connect(":memory:") as connection:
        _write_daily(connection, path, _TODAY, [(_code(1), -1.0, 0.0, 12.0)])
    response = client.get(_PATH)
    assert response.status_code == 200 and response.json()["ranking"]["status"] == "error"
    assert response.json()["trend"][-1]["amountYuan"] == 12_000


@pytest.mark.parametrize("invalid", ["schema", "duplicate", "date", "calendar", "timeout"])
def test_invalid_trend_input_is_unavailable_not_empty(lake, request_api, monkeypatch, invalid):
    client, requests, _ = request_api
    if invalid == "timeout":
        module = importlib.import_module("src.biz.queries.wealth.market.etf_activity.etf_activity_query")
        monkeypatch.setattr(module, "_REQUEST_SECONDS", 0)
    else:
        # This partition is inside the bounded window but is not part of the ranking.
        day = date(2026, 1, 7)
        part = _daily_path(lake.root, day)
        with duckdb.connect(":memory:") as connection:
            if invalid == "schema":
                _write(connection, part, "SELECT '510001.SH' AS ts_code, ?::DATE AS trade_date, 1::BIGINT AS amount", [day])
            elif invalid == "duplicate":
                _write_daily(connection, part, day, [(_code(1), 1.0, 0.0, 1)] * 2)
            elif invalid == "date":
                _write_daily(connection, part, day + timedelta(days=1), [(_code(1), 1.0, 0.0, 1)])
            else:
                shortened = lake.calendar.with_name("valid_except_one_date.parquet")
                _write(connection, shortened, "SELECT * FROM read_parquet(?) WHERE trade_date <> ?", [str(lake.calendar), day])
                shortened.replace(lake.calendar)
    response = client.get(_PATH)
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "ETF_ACTIVITY_SOURCE_UNAVAILABLE"
    assert requests == []


def test_empty_lake_and_unavailable_calendar_are_distinct(lake, request_api):
    client, requests, _ = request_api
    _daily_path(lake.root, _TODAY).parent.parent.rename(lake.root / "isolated_daily_files")
    result = client.get(_PATH)
    assert result.status_code == 200
    assert result.json() == {
        "tradeDate": None, "previousTradeDate": None, "oneMonthStartDate": None, "trend": [],
        "ranking": {"status": "empty", "rows": [], "error": None},
    }
    lake.calendar.unlink()
    assert client.get(_PATH).status_code == 503
    assert requests == []


def test_quote_auth_rejects_before_reading_dg(request_api, monkeypatch):
    client, requests, _ = request_api
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    response = client.get(_PATH)
    assert response.status_code == 401 and response.json()["code"] == "auth_required"
    assert not requests


@pytest.mark.parametrize(("environment", "root_matches", "status"), [
    (None, True, 404), ("prod", True, 404), ("test", True, 404), ("dev", False, 503), ("local", False, 503),
])
def test_requires_explicit_local_environment_and_formal_root(monkeypatch, tmp_path, environment, root_matches, status):
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
    monkeypatch.delenv("APP_ENV", raising=False)
    get_settings.cache_clear()
    wiring = importlib.import_module("src.app.api.v1.router")
    formal = tmp_path / "formal"
    monkeypatch.setattr(wiring, "FORMAL_LAKE_ROOT", formal)
    configured = formal if root_matches else tmp_path / "other"
    env = {} if environment is None else {"APP_ENV": environment}
    target = APIRouter(prefix="/api/v1")
    wiring._include_local_etf_activity(target, _local_settings(GOLDENSHARE_LAKE_ROOT=str(configured), **env))
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(target)
    app.dependency_overrides[get_db_session] = object
    response = TestClient(app).get(_PATH)
    assert response.status_code == status
