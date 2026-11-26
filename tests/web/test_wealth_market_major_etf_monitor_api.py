"""Exercise the registered monitor route with DG-shaped Parquet and isolated auth/metadata."""

from datetime import date, datetime
import importlib
import json
from types import SimpleNamespace

import duckdb
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.app.web.middleware import RequestIdMiddleware
from src.foundation.clients.local_lake import etf_daily_reader
from src.foundation.clients.local_lake.reference_data_reader import LakeTradeCalendarReader
from src.foundation.config.settings import Settings, get_settings

_PATH = "/api/v1/wealth/market/major-etf-monitor"
_TODAY = date(2026, 3, 31)
_START = date(2025, 12, 31)
_CODES = (
    "510300.SH", "510310.SH", "510330.SH", "159919.SZ", "510050.SH", "510500.SH", "512500.SH",
    "512100.SH", "159845.SZ", "560010.SH", "159629.SZ", "159915.SZ", "159977.SZ", "588000.SH",
)
_OUTSIDER = "511360.SH"
_SNAPSHOT = "a" * 64
_EMPTY = {"status": "empty", "tradeDate": None, "oneMonthStartDate": None, "trend": [], "quotes": []}
_UNAVAILABLE = "MAJOR_ETF_MONITOR_SOURCE_UNAVAILABLE"


def _daily_path(root, day):
    return root / "silver" / "quote" / "etf_daily" / f"trade_date={day}" / "part-000.parquet"


def _write_parquet(db, path, table):
    path.parent.mkdir(parents=True, exist_ok=True)
    db.execute(f"COPY {table} TO ? (FORMAT PARQUET)", [str(path)])


def _write_daily(path, day, rows, *, amount_type="DOUBLE"):
    # FUND_DAILY_SILVER_COLUMN_TYPES defines trade_date: DATE, ts_code: VARCHAR and the three DOUBLEs.
    with duckdb.connect(":memory:") as db:
        db.execute(f"""CREATE TABLE daily (
            ts_code VARCHAR, trade_date DATE, close DOUBLE, pct_chg DOUBLE, amount {amount_type}
        )""")
        if rows:
            db.executemany("INSERT INTO daily VALUES (?, ?, ?, ?, ?)", [
                (code, day, close, pct, amount) for code, close, pct, amount in rows
            ])
        _write_parquet(db, path, "daily")


def _write_names(path, rows):
    # DG silver_etf_basic projects all three ETF name fields as VARCHAR.
    with duckdb.connect(":memory:") as db:
        db.execute("CREATE TABLE basic (ts_code VARCHAR, csname VARCHAR, extname VARCHAR, cname VARCHAR)")
        db.executemany("INSERT INTO basic VALUES (?, ?, ?, ?)", rows)
        _write_parquet(db, path, "basic")


def _rows(codes, *, amount=100):
    return [(code, 4.0, 0.0, amount) for code in codes]


def _latest_rows():
    return [(_CODES[0], 4.125, -0.28, 234.5), (_CODES[1], 4.0, 0.0, 0), *_rows(_CODES[2:])]


@pytest.fixture
def lake(tmp_path):
    root = tmp_path / "formal"
    current = _daily_path(root, _TODAY)
    basic = root / "silver" / "basic" / "etf_basic" / f"snapshot_id={_SNAPSHOT}" / "part-000.parquet"
    _write_names(basic, [
        (_CODES[0], " 沪深300ETF ", "后备名", "另一个名称"),
        (_CODES[1], "  ", " 扩位简称 ", "后备名"),
        (_CODES[2], None, " ", " 基金全称 "),
        (_CODES[3], " ", None, ""),
        (_OUTSIDER, "名单外", None, None),
    ])
    _write_daily(_daily_path(root, _START), _START, [*_rows(reversed(_CODES)), *_rows([_OUTSIDER], amount=10**9)])
    partial_day = date(2026, 1, 5)
    _write_daily(_daily_path(root, partial_day), partial_day, _rows(_CODES[:-1]))
    outside_only_day = date(2026, 2, 27)
    _write_daily(_daily_path(root, outside_only_day), outside_only_day, _rows([_OUTSIDER]))
    zero_day = date(2026, 3, 2)
    _write_daily(_daily_path(root, zero_day), zero_day, _rows(_CODES, amount=0))
    _write_daily(current, _TODAY, [*_rows([_OUTSIDER], amount=10**9), *reversed(_latest_rows())])
    for day in [date(2025, 12, 30), date(2026, 4, 1)]:
        # These files would fail even schema inspection if they entered the query.
        path = _daily_path(root, day)
        path.parent.mkdir(parents=True)
        path.write_text("out of range")
    (current.parent.parent / "trade_date=20260330").mkdir()
    return SimpleNamespace(root=root, current=current, basic=basic, daily_dir=current.parent.parent)


@pytest.fixture
def wiring(monkeypatch, tmp_path):
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    yield importlib.import_module("src.app.api.v1.router")
    get_settings.cache_clear()


def _client(wiring, **settings):
    target = APIRouter(prefix="/api/v1")
    wiring._include_local_etf_activity(
        target, Settings(_env_file=None, WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=False, **settings),
    )
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    install_exception_handlers(app)
    app.include_router(target)
    # Run actual quote auth. The stand-in session has no DB methods.
    app.dependency_overrides[get_db_session] = object
    return TestClient(app)


@pytest.fixture
def request_api(wiring, lake, monkeypatch):
    api = importlib.import_module("src.biz.api.wealth.market.major_etf_monitor")

    class FixtureClock:
        @staticmethod
        def now(tz):
            assert tz.key == "Asia/Shanghai"
            return datetime.combine(_TODAY, datetime.min.time(), tzinfo=tz)

    monkeypatch.setattr(api, "datetime", FixtureClock)
    monkeypatch.setattr(wiring, "FORMAL_LAKE_ROOT", lake.root)

    def forbidden(*_args, **_kwargs):
        pytest.fail("The monitor route may not read the trade calendar")

    for method in ("latest_open_among", "recent_open_rows", "range_rows"):
        monkeypatch.setattr(LakeTradeCalendarReader, method, forbidden)

    requests = []
    reference = {"day": _TODAY.isoformat(), "daily": str(lake.current), "basic": str(lake.basic), "available": True}

    def respond(request):
        assert request.method == "POST" and str(request.url) == "http://127.0.0.1:3000/graphql"
        body = json.loads(request.content)
        assert 'assetKey: {path: ["silver_etf_daily"]}' in body["query"]
        assert "partitions: [$day], limit: 1" in body["query"]
        requests.append(body["variables"])
        if not reference["available"]:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": {"assetNodeOrError": {
            "__typename": "AssetNode",
            "assetMaterializations": [{
                "partition": reference["day"],
                "metadataEntries": [
                    {"label": "dagster/uri", "path": reference["daily"]},
                    {"label": "goldenshare/basic_raw_snapshot_hash", "text": _SNAPSHOT},
                    {"label": "goldenshare/basic_silver_uri", "text": reference["basic"]},
                ],
            }],
        }}})

    client_type = httpx.Client

    def dg_client(*, trust_env):
        assert trust_env is False
        return client_type(transport=httpx.MockTransport(respond), trust_env=False)

    monkeypatch.setattr(etf_daily_reader.httpx, "Client", dg_client)
    reads = []
    query_parquet = etf_daily_reader.EtfDailyLakeReader.query_parquet

    def read(self, sql, parameters, *, columns_by_file, deadline):
        reads.append(tuple(columns_by_file))
        return query_parquet(self, sql, parameters, columns_by_file=columns_by_file, deadline=deadline)

    monkeypatch.setattr(etf_daily_reader.EtfDailyLakeReader, "query_parquet", read)
    return SimpleNamespace(
        client=_client(wiring, APP_ENV="local", GOLDENSHARE_LAKE_ROOT=str(lake.root)),
        requests=requests, reference=reference, reads=reads,
    )


def _assert_unavailable(response):
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body == {
        "code": _UNAVAILABLE,
        "message": "主要ETF（国家队）监测暂不可读取，请重试",
        "request_id": response.headers["x-request-id"],
    }


def test_route_aggregates_only_monitored_codes_and_returns_quotes_in_fixed_order(request_api, lake):
    response = request_api.client.get(_PATH, params={"tsCode": _OUTSIDER, "tradeDate": "2025-12-30", "range": "1m"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data == {
        "status": "ready", "tradeDate": "2026-03-31", "oneMonthStartDate": "2026-02-28",
        "trend": [
            {"tradeDate": "2025-12-31", "amountYuan": 1_400_000.0},
            {"tradeDate": "2026-01-05", "amountYuan": None},
            {"tradeDate": "2026-02-27", "amountYuan": None},
            {"tradeDate": "2026-03-02", "amountYuan": 0.0},
            {"tradeDate": "2026-03-31", "amountYuan": 1_434_500.0},
        ],
        "quotes": [
            {"tsCode": _CODES[0], "name": "沪深300ETF", "closePrice": 4.125, "priceChangePct": -0.28,
             "amountYuan": 234_500.0},
            {"tsCode": _CODES[1], "name": "扩位简称", "closePrice": 4.0, "priceChangePct": 0.0,
             "amountYuan": 0.0},
            *[
                {"tsCode": code, "name": "基金全称" if code == _CODES[2] else None,
                 "closePrice": 4.0, "priceChangePct": 0.0, "amountYuan": 100_000.0}
                for code in _CODES[2:]
            ],
        ],
    }
    assert request_api.requests == [{"day": "2026-03-31"}]
    days = [date(2025, 12, 31), date(2026, 1, 5), date(2026, 2, 27), date(2026, 3, 2), _TODAY]
    assert request_api.reads == [(*(_daily_path(lake.root, day) for day in days), lake.basic)]


def test_partial_latest_keeps_all_14_rows_and_does_not_report_a_partial_sum(request_api, lake):
    _write_daily(lake.current, _TODAY, _latest_rows()[1:])
    data = request_api.client.get(_PATH).json()
    assert data["status"] == "ready" and data["tradeDate"] == "2026-03-31"
    assert data["trend"][-1] == {"tradeDate": "2026-03-31", "amountYuan": None}
    assert [quote["tsCode"] for quote in data["quotes"]] == list(_CODES)
    assert data["quotes"][0] == {
        "tsCode": _CODES[0], "name": "沪深300ETF", "closePrice": None, "priceChangePct": None, "amountYuan": None,
    }
    assert data["quotes"][1]["amountYuan"] == 0.0


def test_latest_with_no_matches_preserves_history_without_backdating_quotes(request_api, lake):
    _write_daily(lake.current, _TODAY, _rows([_OUTSIDER]))
    data = request_api.client.get(_PATH).json()
    assert data["status"] == "ready" and data["tradeDate"] == "2026-03-31" and data["quotes"] == []
    assert data["trend"][0] == {"tradeDate": "2025-12-31", "amountYuan": 1_400_000.0}
    assert data["trend"][-1] == {"tradeDate": "2026-03-31", "amountYuan": None}
    for day in (_START, date(2026, 3, 2)):
        _daily_path(lake.root, day).unlink()
    assert request_api.client.get(_PATH).json() == _EMPTY


def test_empty_directory_and_absent_directory_have_distinct_responses(request_api, lake):
    lake.daily_dir.rename(lake.daily_dir.with_name("isolated"))
    _assert_unavailable(request_api.client.get(_PATH))
    lake.daily_dir.mkdir()
    response = request_api.client.get(_PATH)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == _EMPTY and request_api.requests == [] and request_api.reads == []


@pytest.mark.parametrize("fault", ["duplicate", "date", "schema", "null_amount", "negative_amount", "inf_amount"])
def test_malformed_history_is_a_source_error(request_api, lake, fault):
    path = _daily_path(lake.root, _START)
    day = date(2025, 12, 30) if fault == "date" else _START
    amount = {"null_amount": None, "negative_amount": -1, "inf_amount": float("inf")}.get(fault, 100)
    codes = [_CODES[0]] * 2 if fault == "duplicate" else _CODES
    _write_daily(path, day, _rows(codes, amount=amount), amount_type="BIGINT" if fault == "schema" else "DOUBLE")
    _assert_unavailable(request_api.client.get(_PATH))


@pytest.mark.parametrize(("close", "pct"), [(None, 0), (-1, 0), (float("inf"), 0), (4, None), (4, float("nan"))])
def test_bad_latest_quote_is_a_source_error(request_api, lake, close, pct):
    _write_daily(lake.current, _TODAY, [(_CODES[0], close, pct, 1)])
    _assert_unavailable(request_api.client.get(_PATH))


def test_bad_quote_columns_of_other_etfs_and_historical_prices_do_not_block(request_api, lake):
    _write_daily(_daily_path(lake.root, _START), _START, [(code, None, None, 100) for code in _CODES])
    _write_daily(lake.current, _TODAY, [*_latest_rows(), (_OUTSIDER, None, None, -1)])
    result = request_api.client.get(_PATH)
    assert result.status_code == 200 and result.json()["trend"][0]["amountYuan"] == 1_400_000.0


def test_duplicate_target_name_and_dg_reference_errors_are_reported_and_retry_recovers(request_api, lake, caplog):
    for key, bad in [("day", "2026-03-30"), ("daily", "/not-the-daily-file"), ("basic", "/not-a-dg-snapshot"),
                     ("available", False)]:
        good = request_api.reference[key]
        request_api.reference[key] = bad
        _assert_unavailable(request_api.client.get(_PATH))
        request_api.reference[key] = good
    assert request_api.reads == []
    basic_bytes = lake.basic.read_bytes()
    lake.basic.unlink()
    _assert_unavailable(request_api.client.get(_PATH))
    _write_names(lake.basic, [(_CODES[0], "先", None, None), (_CODES[0], "后", None, None)])
    _assert_unavailable(request_api.client.get(_PATH))
    lake.basic.write_bytes(basic_bytes)
    assert request_api.client.get(_PATH).status_code == 200
    assert request_api.requests == [{"day": _TODAY.isoformat()}] * 7
    assert "阶段=同日 ETF 基础信息引用" in caplog.text
    assert "阶段=DG Parquet 核对与计算" in caplog.text


def test_read_deadline_and_auth_stop_before_query(request_api, lake, monkeypatch):
    query = importlib.import_module("src.biz.queries.wealth.market.major_etf_monitor.major_etf_monitor_query")
    monkeypatch.setattr(query, "_REQUEST_SECONDS", 0)
    _assert_unavailable(request_api.client.get(_PATH))
    lake.daily_dir.rename(lake.daily_dir.with_name("isolated"))
    lake.daily_dir.mkdir()
    _assert_unavailable(request_api.client.get(_PATH))
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    failure = request_api.client.get(_PATH)
    assert failure.status_code == 401 and failure.json()["code"] == "auth_required"
    assert failure.headers["cache-control"] == "no-store"
    assert request_api.requests == [] and request_api.reads == []


@pytest.mark.parametrize("environment", [None, "prod", "test"])
def test_nonlocal_modes_never_initialize_the_reader(wiring, tmp_path, monkeypatch, environment):
    monkeypatch.delenv("APP_ENV", raising=False)

    def forbidden(*_args, **_kwargs):
        pytest.fail("The nonlocal API must not instantiate the DG reader")

    monkeypatch.setattr(etf_daily_reader, "EtfDailyLakeReader", forbidden)
    values = {} if environment is None else {"APP_ENV": environment}
    client = _client(wiring, GOLDENSHARE_LAKE_ROOT=str(tmp_path / "formal"), **values)
    assert client.get(_PATH).status_code == 404


def test_local_mode_rejects_nonformal_root_before_any_metadata_read(wiring, tmp_path, monkeypatch):
    wiring_root = tmp_path / "formal"
    monkeypatch.setattr(wiring, "FORMAL_LAKE_ROOT", wiring_root)

    def forbidden(*_args, **_kwargs):
        pytest.fail("An incorrect DG root must stop before the metadata request")

    monkeypatch.setattr(etf_daily_reader.EtfDailyLakeReader, "basic_file", forbidden)
    client = _client(wiring, APP_ENV="dev", GOLDENSHARE_LAKE_ROOT=str(tmp_path / "other"))
    _assert_unavailable(client.get(_PATH))
