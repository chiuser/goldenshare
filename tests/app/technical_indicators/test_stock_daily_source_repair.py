"""Exercise the stock route and kernel against isolated formal-layout Lake inputs."""

from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from src.app.auth.dependencies import require_quote_access
from src.app.dependencies.db import get_db_session
from src.app.dependencies import stock_daily_technical_indicators as wiring
from src.app.exceptions import install_exception_handlers
from src.app.runtime.reference_data import build_reference_data
from src.app.web.middleware.access_log import AccessLogMiddleware
from src.biz.api.wealth.market.stock_detail import build_router
from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.config.settings import Settings
from goldenshare_technical_indicators.errors import SourceContractError
from goldenshare_technical_indicators.service import TechnicalIndicatorService


PATH = "/api/v1/wealth/market/stock-detail/kline"
INIT_PATH = "/api/v1/wealth/market/stock-detail/page-init"
CODE = "600000.SH"
START = date(2026, 1, 5)
DAYS = tuple(START + timedelta(days=i) for i in range(29) if i % 7 < 5)
OTHER_DAY = date(2026, 2, 3)


def write_table(root, path, rows, schema=None):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), file)
    return file


@pytest.fixture
def source_client(tmp_path, monkeypatch):
    # DG physical schemas follow the stock daily, adjustment factor and stock
    # lifecycle contracts. Prices and adjustment expectations are independent literals.
    root = tmp_path
    for day in (*DAYS, OTHER_DAY):
        write_table(root, f"silver/quote/stock_daily/trade_date={day}/part-000.parquet", [{
            "ts_code": CODE if day in DAYS else "601398.SH", "trade_date": day,
            "open": 20.0, "high": 20.0, "low": 20.0, "close": 20.0, "pre_close": 10.0,
            "change_amount": 0.0, "pct_chg": 0.0, "vol": 100.0, "amount": 1000.0,
        }])
        write_table(root, f"silver/quote/adj_factor/trade_date={day}/part-000.parquet", [{
            "ts_code": CODE, "trade_date": day, "adj_factor": 1.0 if day in DAYS else 2.0,
        }])
    write_table(root, "silver/basic/stock_lifecycle/full/part-000.parquet",
                [{"ts_code": CODE, "list_date": START, "delist_date": None}],
                pa.schema([("ts_code", pa.string()), ("list_date", pa.date32()), ("delist_date", pa.date32())]))
    suspend = pa.schema([("ts_code", pa.string()), ("trade_date", pa.date32()),
                         ("suspend_type", pa.string()), ("suspend_timing", pa.string())])
    for day in DAYS:
        write_table(root, f"silver/quote/stock_suspend_daily/trade_date={day}/part-000.parquet", [], suspend)
    previous_open = None
    calendar = []
    for i in range((OTHER_DAY - START).days + 1):
        day = START + timedelta(days=i)
        is_open = i % 7 < 5
        calendar.append({"exchange": "SSE", "trade_date": day, "is_open": is_open,
                         "pretrade_date": previous_open})
        if is_open:
            previous_open = day
    write_table(root, "silver/calendar/trade_calendar/full/part-000.parquet", calendar)
    # Formal DG stock_basic Raw has VARCHAR fields, including YYYYMMDD dates.
    security = {
        "ts_code": CODE, "name": "浦发银行", "symbol": "600000", "exchange": "SSE",
        "list_status": "L", "list_date": "19991110", "market": "主板",
        "area": "上海", "industry": "银行", "curr_type": "CNY",
        **dict.fromkeys(("fullname", "enname", "cnspell", "delist_date",
                         "is_hs", "act_name", "act_ent_type")),
    }
    write_table(root, "raw/tushare/stock_basic/full/part-000.parquet", [security],
                pa.schema([(name, pa.string()) for name in security]))
    write_table(root, "raw/tushare/daily_basic/trade_date=2026-02-02/part-000.parquet", [{
        "ts_code": CODE, "trade_date": "20260202", "turnover_rate": "1.25", "volume_ratio": "0.80",
    }])

    def reject_pg(*args, **kwargs):
        pytest.fail("本地股票详情业务不应创建 PostgreSQL 会话")

    original_calculate = TechnicalIndicatorService.calculate_with_source
    calculations = []

    def calculate(service, request, **kwargs):
        calculated = original_calculate(service, request, **kwargs)
        if calculated.result is not None:
            calculations.append(calculated.result)
        return calculated

    monkeypatch.setattr(wiring, "open_stock_daily_read_session", reject_pg)
    monkeypatch.setattr(TechnicalIndicatorService, "calculate_with_source", calculate)

    @contextmanager
    def client_for(env="local", *, source_root=root, raise_server_exceptions=True):
        @asynccontextmanager
        async def lifespan(app):
            settings = Settings(_env_file=None, APP_ENV=env, GOLDENSHARE_LAKE_ROOT=str(source_root))
            app.state.reference_data = build_reference_data(settings)
            async with wiring.stock_daily_technical_indicators_lifespan(
                app, settings_provider=lambda: settings, session_factory_provider=reject_pg,
            ):
                yield

        app = FastAPI(lifespan=lifespan)
        app.include_router(build_router(local=True), prefix="/api/v1")
        install_exception_handlers(app)
        app.add_middleware(AccessLogMiddleware)
        app.dependency_overrides[require_quote_access] = lambda: None
        app.dependency_overrides[get_db_session] = reject_pg
        wiring.install_stock_daily_technical_indicators(app)
        with TestClient(app, raise_server_exceptions=raise_server_exceptions) as client:
            yield client

    return SimpleNamespace(client_for=client_for, calculations=calculations, root=root)


def test_period_route_uses_page_anchor_and_actual_coverage(source_client, monkeypatch):
    fields = ("open_qfq", "high_qfq", "low_qfq", "close_qfq")
    schema = pa.schema([
        ("ts_code", pa.string()), ("trade_date", pa.string()), ("end_date", pa.string()),
        *((name, pa.decimal128(18, 4)) for name in fields),
        ("vol", pa.decimal128(20, 4)), ("amount", pa.decimal128(20, 4)), ("pct_chg", pa.decimal128(10, 4)),
    ])
    bars = (
        ("stock_weekly/week_end=2026-01-23", "20260123", "20260123"),
        ("stock_weekly/week_end=2026-01-30", "20260130", "20260203"),
        ("stock_weekly/week_end=2026-02-06", "20260206", "20260202"),
        ("stock_monthly/month=2026-01", "20260131", "20260203"),
        ("stock_monthly/month=2026-02", "20260228", "20260202"),
    )
    for part, label, coverage in bars:
        write_table(source_client.root, f"silver/quote/{part}/part-000.parquet", [dict(
            ts_code=CODE, trade_date=label, end_date=coverage, **dict.fromkeys(fields, Decimal("20.00")),
            vol=Decimal("100.00"), amount=Decimal("1000.00"), pct_chg=Decimal("1.50"),
        )], schema)
    suspension = pa.schema([("ts_code", pa.string()), ("trade_date", pa.date32()),
                            ("suspend_type", pa.string()), ("suspend_timing", pa.string())])
    suspension_path = "silver/quote/stock_suspend_daily/trade_date=2026-02-03/part-000.parquet"
    write_table(source_client.root, suspension_path, [], suspension)
    zone = ZoneInfo("Asia/Shanghai")
    module = "src.biz.queries.wealth.market.context.market_page_context_query._now_cn"
    monkeypatch.setattr(module, lambda: datetime(2026, 2, 3, 19, 59, tzinfo=zone))

    with source_client.client_for() as client:
        init = client.get(INIT_PATH, params={"tsCode": CODE}).json()
        assert init["chartDefaults"]["availablePeriods"] == ["day", "week", "month"]
        assert init["pageContext"]["tradeDate"] == "2026-02-02"
        recent = client.get(PATH, params={"tsCode": CODE, "period": "week", "limit": 1}).json()
        assert recent["dataStatus"]["status"] == "READY"
        assert recent["bars"][0]["tradeDate"] == "2026-02-02"
        assert recent["bars"][0]["changePct"] == 1.5 and recent["bars"][0]["vol"] == 100.0
        assert recent["bars"][0]["amplitude"] is None and recent["bars"][0]["turnoverRate"] is None
        assert recent["meta"]["nextEndDate"] == "2026-01-30"
        earlier = client.get(PATH, params={"tsCode": CODE, "period": "week", "limit": 1,
                                          "tradeDate": "2026-02-02", "endDate": recent["meta"]["nextEndDate"]}).json()
        assert earlier["pageContext"]["tradeDate"] == "2026-02-02"
        assert earlier["bars"][0]["tradeDate"] == "2026-01-30"
        assert earlier["meta"]["nextEndDate"] == "2026-01-23"

        monkeypatch.setattr(module, lambda: datetime(2026, 2, 3, 20, tzinfo=zone))
        month = client.get(PATH, params={"tsCode": CODE, "period": "month"}).json()
        assert [bar["tradeDate"] for bar in month["bars"]] == ["2026-01-31", "2026-02-02"]
        assert month["dataStatus"]["status"] == "DELAYED"
        assert month["meta"]["nextEndDate"] is None
        write_table(source_client.root, suspension_path, [dict(ts_code=CODE, trade_date=OTHER_DAY,
                    suspend_type="S", suspend_timing=None)], suspension)
        month = client.get(PATH, params={"tsCode": CODE, "period": "month"}).json()
        assert month["dataStatus"]["status"] == "READY"
        assert month["dataStatus"]["expectedTradeDate"] == "2026-02-02"


def request(client, **params):
    return client.get(PATH, params={"tsCode": CODE, "endDate": "2026-02-02", "debug": 1, **params})


def check_values(payload, days):
    assert [bar["tradeDate"] for bar in payload["bars"]] == [d.isoformat() for d in days]
    assert payload["meta"]["count"] == len(days)
    for bar in payload["bars"]:
        assert (bar["open"], bar["high"], bar["low"], bar["close"], bar["vol"], bar["amount"]) == (10, 10, 10, 10, 100, 1000)
        assert bar["factors"]["macd"] == {"dif": 0, "dea": 0, "macd": 0}
        assert bar["factors"]["kdj"] == {"k": 50, "d": 50, "j": 50}
        # The fixture producer writes constant 20, rebased by 1/2 at the page anchor.
        assert bar["factors"]["trendChannel"] == pytest.approx({
            "shortUpper": 10, "shortLower": 10, "longUpper": 10, "longLower": 10,
        }, abs=0.01, rel=0)


def test_local_first_screen_shares_dg_result_and_never_opens_business_pg(source_client):
    with source_client.client_for() as client:
        init = client.get(INIT_PATH, params={"tsCode": CODE, "tradeDate": OTHER_DAY.isoformat(), "debug": 1})
        assert init.status_code == 200, init.text
        page = init.json()
        assert set(page) == {"pageContext", "stock", "chartDefaults", "capabilities", "debugInfo"}
        assert page["stock"]["name"] == "浦发银行"
        assert page["debugInfo"]["sourceTables"] == ["raw/tushare/stock_basic", "silver/calendar/trade_calendar"]
        day = page["pageContext"]["tradeDate"]
        assert day == "2026-02-03"
        assert not source_client.calculations
        response = request(client, tradeDate=day, endDate=day, limit=2)
        assert response.status_code == 200, response.text
        openapi = client.get("/openapi.json").json()
        schema = openapi["paths"][PATH]["get"]
    assert {item["name"] for item in schema["parameters"] if item["in"] == "query"} == {
        "tsCode", "period", "adjustment", "tradeDate", "startDate", "endDate", "limit", "debug",
    }
    assert {item["$ref"].rsplit("/", 1)[-1] for item in
            schema["responses"]["200"]["content"]["application/json"]["schema"]["anyOf"]} == {
        "LocalStockDetailFirstKlineResponseDto", "LocalStockDetailPagedKlineResponseDto", "StockDetailKlineResponseDto",
        "StockDetailPeriodKlineResponseDto",
    }
    for name in ("LocalStockDetailFirstKlineResponseDto", "LocalStockDetailPagedKlineResponseDto",
                 "StockDetailKlineResponseDto", "StockDetailPeriodKlineResponseDto"):
        assert "nineTurnMarkers" in openapi["components"]["schemas"][name]["required"]
    payload = response.json()
    check_values(payload, DAYS[-2:])
    assert payload["pageContext"]["tradeDate"] == day
    assert payload["dataStatus"]["expectedTradeDate"] == day
    assert payload["dataStatus"]["observedTradeDate"] == "2026-02-02"
    assert payload["dataStatus"]["status"] == "DELAYED"
    latest = payload["bars"][-1]
    assert payload["quote"] == {
        "tradeDate": "2026-02-02", "price": 10, "close": 10, "open": 10, "high": 10, "low": 10,
        "preClose": 10, "change": 0, "changePct": 0, "direction": "FLAT",
        "vol": 100, "volDisplay": latest["volDisplay"], "amount": 1000,
        "turnoverRate": 1.25, "volumeRatio": 0.80,
    }
    for field in ("tradeDate", "open", "high", "low", "close", "preClose", "change",
                  "changePct", "vol", "volDisplay", "amount", "turnoverRate", "volumeRatio"):
        assert payload["quote"][field] == latest[field]
    assert payload["meta"]["nextEndDate"] == "2026-01-29"
    assert payload["nineTurnMarkers"] == []
    assert len(source_client.calculations) == 1


@pytest.mark.parametrize("params", [{}, {"tradeDate": "2026-01-30"},
                                     {"tradeDate": "2026-02-02", "startDate": "2026-02-02"}])
def test_local_ordinary_daily_requests_include_nine_turn_without_pagination(source_client, params):
    with source_client.client_for() as client:
        response = request(client, **params)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "quote" not in payload and "nextEndDate" not in payload["meta"]
    assert payload["nineTurnMarkers"] == []
    assert len(source_client.calculations) == 1
    assert [item.calculation_id for item in source_client.calculations[0].calculations].count("nineturn") == 1
    check_values(payload, DAYS[-1:] if "startDate" in params else DAYS)


@pytest.mark.parametrize("limit", [7, 10])
def test_stock_daily_pages_use_previous_actual_date_and_stop_at_oldest(source_client, limit):
    anchor = OTHER_DAY.isoformat()
    with source_client.client_for() as client:
        end = anchor
        for page_number in range(3):
            stop = len(DAYS) - page_number * limit
            start = max(0, stop - limit)
            response = request(client, tradeDate=anchor, endDate=end, limit=limit)
            assert response.status_code == 200, response.text
            payload = response.json()
            check_values(payload, DAYS[start:stop])
            assert payload["meta"]["startDate"] is None
            assert payload["meta"]["endDate"] == end
            assert ("quote" in payload) == (page_number == 0)
            expected_next = DAYS[start - 1].isoformat() if start else None
            assert payload["meta"]["nextEndDate"] == expected_next
            end = expected_next
    assert len(source_client.calculations) == 3


@pytest.mark.parametrize("paginated", [False, True])
def test_local_daily_requests_get_markers_from_the_same_calculation(source_client, paginated):
    for index, day in enumerate(DAYS):
        partition = f"silver/quote/stock_daily/trade_date={day}/part-000.parquet"
        original = pq.ParquetFile(source_client.root / partition).read().to_pylist()[0]
        write_table(source_client.root, partition, [original | dict.fromkeys(("open", "high", "low", "close"), 20.0 + index)])
    anchor = DAYS[12].isoformat()
    with source_client.client_for() as client:
        first = request(client, endDate=anchor, limit=5, **({"tradeDate": anchor} if paginated else {}))
        assert first.status_code == 200, first.text
        first = first.json()
        older = request(client, endDate=first["meta"]["nextEndDate"] if paginated else DAYS[7].isoformat(),
                        limit=5, **({"tradeDate": anchor} if paginated else {}))
        assert older.status_code == 200, older.text
        older = older.json()
    assert len(source_client.calculations) == 2
    for payload, calculation, indices, counts in (
        (first, source_client.calculations[0], range(8, 13), range(5, 10)),
        (older, source_client.calculations[1], range(4, 8), range(1, 5)),
    ):
        assert len(calculation.calculations) == 13 and calculation.calculations[-2].calculation_id == "nineturn"
        assert calculation.calculations[-1].calculation_id == "trend_channel"
        assert calculation.statistics.price_conversion_batches == 1
        assert payload["nineTurnMarkers"] == [
            {"tradeDate": DAYS[index].isoformat(), "tradeTime": None, "direction": "UP",
             "sequenceNumber": count, "completed": count == 9}
            for index, count in zip(indices, counts, strict=True)
        ]
    if paginated:
        assert first["quote"]["tradeDate"] == anchor
        assert older["pageContext"]["tradeDate"] == first["meta"]["nextEndDate"]
    else:
        assert "quote" not in first and "nextEndDate" not in first["meta"]
        assert "nextEndDate" not in older["meta"]
    assert "quote" not in older


def test_stock_daily_cursor_crosses_days_without_stock_data(source_client):
    for day in DAYS[-4:-2]:
        path = f"silver/quote/stock_daily/trade_date={day}/part-000.parquet"
        original = pq.ParquetFile(source_client.root / path).read().to_pylist()[0]
        write_table(source_client.root, path, [{**original, "ts_code": "601398.SH"}])
        suspend = f"silver/quote/stock_suspend_daily/trade_date={day}/part-000.parquet"
        write_table(source_client.root, suspend, [
            {"ts_code": CODE, "trade_date": day, "suspend_type": "S", "suspend_timing": None},
        ], pq.read_schema(source_client.root / suspend))
    anchor = OTHER_DAY.isoformat()
    with source_client.client_for() as client:
        first = request(client, tradeDate=anchor, endDate=anchor, limit=2)
        assert first.status_code == 200, first.text
        assert first.json()["meta"]["nextEndDate"] == DAYS[-5].isoformat()
        second = request(client, tradeDate=anchor, endDate=DAYS[-5].isoformat(), limit=2)
        assert second.status_code == 200, second.text
        check_values(second.json(), DAYS[-6:-4])


def test_stock_uses_latest_basis_even_on_an_older_page(source_client):
    with source_client.client_for() as client:
        response = request(client, limit=2, startDate="2026-01-30")
        assert response.status_code == 200, response.text
        older = request(client, limit=1, endDate="2026-01-29")
        assert older.status_code == 200, older.text
    payload = response.json()
    check_values(payload, DAYS[-2:])
    check_values(older.json(), (DAYS[-3],))
    assert all(bar["factors"]["boll"] == {"upper": 10, "middle": 10, "lower": 10} for bar in payload["bars"])
    first, previous = source_client.calculations
    assert first.statistics.source_rows == 21
    assert first.source.id == previous.source.id == "stock_daily"
    assert first.price_adjustment.basis_date == previous.price_adjustment.basis_date == OTHER_DAY
    assert payload["debugInfo"]["sourceTables"] == [
        "raw/tushare/stock_basic", "silver/calendar/trade_calendar",
        "silver/quote/stock_daily", "silver/quote/adj_factor", "raw/tushare/daily_basic",
    ]


def test_full_short_history_preserves_nulls(source_client):
    with source_client.client_for("dev") as client:
        response = request(client)
        assert response.status_code == 200, response.text
    payload = response.json()
    check_values(payload, DAYS)
    for bar in payload["bars"][:19]:
        assert bar["factors"]["ma"]["ma20"] is None
        assert bar["factors"]["boll"] == {"upper": None, "middle": None, "lower": None}
    assert [bar["factors"]["ma"]["ma20"] for bar in payload["bars"][19:]] == [10, 10]


def test_dg_skips_unrelated_file(source_client):
    with source_client.client_for("dev") as client:
        response = request(client, endDate="2026-02-03", limit=1)
        assert response.status_code == 200, response.text
    check_values(response.json(), DAYS[-1:])
    assert source_client.calculations[0].statistics.source_rows == 21


def test_stock_daily_reads_each_quote_partition_once_and_uses_only_actual_dates(source_client, monkeypatch):
    recent_batch = LakePriceLocator._read_recent_daily_batch
    fact_rows = LakeTechnicalIndicatorPriceSource._fact_rows
    queries, basic_dates = [], []

    def record_batch(locator, paths, columns):
        queries.append((locator.requirement.latest_rows, paths))
        return recent_batch(locator, paths, columns)

    def record_facts(source, root, dataset, *args, **kwargs):
        assert dataset == "stock_daily_basic"
        basic_dates.append(kwargs["day"])
        return fact_rows(source, root, dataset, *args, **kwargs)

    monkeypatch.setattr(LakePriceLocator, "_read_recent_daily_batch", record_batch)
    monkeypatch.setattr(LakeTechnicalIndicatorPriceSource, "_fact_rows", record_facts)
    with source_client.client_for() as client:
        response = request(client, tradeDate=OTHER_DAY.isoformat(), endDate=OTHER_DAY.isoformat())
    assert response.status_code == 200, response.text
    payload = response.json()
    check_values(payload, DAYS)
    assert payload["meta"]["nextEndDate"] is None
    assert basic_dates == [DAYS[-1]]
    [(limit, paths)] = queries
    assert limit == 500
    assert tuple(path.parent.name for path in paths) == tuple(f"trade_date={day}" for day in (*DAYS, OTHER_DAY))


def test_empty_and_missing_source(source_client):
    with source_client.client_for() as client:
        response = request(client, tradeDate="1900-01-01", endDate="1900-01-01")
        assert response.status_code == 200
        assert response.json()["bars"] == []
        assert response.json()["dataStatus"]["status"] == "EMPTY"
        assert "quote" in response.json() and response.json()["quote"] is None
        assert response.json()["meta"]["nextEndDate"] is None
        assert response.json()["nineTurnMarkers"] == []
        response = request(client, startDate=OTHER_DAY.isoformat(), endDate=OTHER_DAY.isoformat())
        assert response.status_code == 200, response.text
        assert response.json()["dataStatus"]["status"] == "EMPTY"
        assert response.json()["bars"] == []
        assert response.json()["nineTurnMarkers"] == []
        for path in (INIT_PATH, PATH):
            assert client.get(path, params={"tsCode": "T00018.SH"}).json()["code"] == "404001"
    with source_client.client_for(source_root=source_client.root / "absent") as client:
        for path in (INIT_PATH, PATH):
            response = client.get(path, params={"tsCode": CODE})
            assert response.status_code == 500
            assert response.json()["code"] == "internal_error"
            assert "读取数据失败" in response.json()["message"]
            assert "silver/calendar/trade_calendar" in response.json()["message"]
    assert not source_client.calculations


@pytest.mark.parametrize("factors", [(), (0.0,), (float("nan"),), (1.0, 1.0)])
def test_no_adjusted_result_is_returned_when_warmup_factor_is_invalid(source_client, factors):
    partition = f"silver/quote/adj_factor/trade_date={DAYS[0]}/part-000.parquet"
    if factors:
        write_table(source_client.root, partition,
                    [{"ts_code": CODE, "trade_date": DAYS[0], "adj_factor": value} for value in factors])
    else:
        (source_client.root / partition).unlink()
    with source_client.client_for() as client:
        with pytest.raises(SourceContractError, match="factor"):
            request(client, limit=1)
    assert not source_client.calculations


@pytest.mark.parametrize("factors", [(0.0,), (2.0, 2.0)])
def test_invalid_latest_basis_is_rejected_outside_page_window(source_client, factors):
    write_table(source_client.root, f"silver/quote/adj_factor/trade_date={OTHER_DAY}/part-000.parquet",
                [{"ts_code": CODE, "trade_date": OTHER_DAY, "adj_factor": value} for value in factors])
    with source_client.client_for() as client:
        with pytest.raises(SourceContractError, match="adjustment factor basis"):
            request(client, limit=1)
    assert not source_client.calculations


@pytest.mark.parametrize("paginated", [False, True])
@pytest.mark.parametrize("failure", ["missing rail", "nonfinite rail", "missing nine turn", "invalid nine turn"])
def test_daily_contract_failure_releases_request_and_retries(source_client, monkeypatch, failure, paginated):
    from dataclasses import replace
    calculate = TechnicalIndicatorService.calculate_with_source
    broken = True

    def result_with_invalid_output(service, request, **kwargs):
        calculated = calculate(service, request, **kwargs)
        if not broken or calculated.result is None:
            return calculated
        result = calculated.result
        if failure == "missing nine turn":
            return replace(calculated, result=replace(result, calculations=tuple(
                item for item in result.calculations if item.calculation_id != "nineturn"
            )))
        if failure == "invalid nine turn":
            return replace(calculated, result=replace(result, calculations=tuple(
                replace(item, fields=(("up_count", (14,) * len(result.times)), item.fields[1]))
                if item.calculation_id == "nineturn" else item for item in result.calculations
            )))
        channel = next(item for item in result.calculations if item.calculation_id == "trend_channel")
        fields = channel.fields[:-1] if failure == "missing rail" else (
            ("short_upper", (float("nan"),) * len(result.times)), *channel.fields[1:],
        )
        invalid = replace(channel, fields=fields)
        return replace(calculated, result=replace(result, calculations=tuple(
            invalid if item is channel else item for item in result.calculations
        )))

    monkeypatch.setattr(TechnicalIndicatorService, "calculate_with_source", result_with_invalid_output)
    with source_client.client_for(raise_server_exceptions=False) as client:
        args = {"tsCode": CODE, "endDate": str(OTHER_DAY), "limit": 2}
        if paginated:
            args["tradeDate"] = str(OTHER_DAY)
        failed = client.get(PATH, params=args)
        assert failed.status_code == 500, failed.text
        assert not client.app.state.technical_indicator_runtime.admission.active_leases
        broken = False
        success = client.get(PATH, params=args)
        assert success.status_code == 200, success.text
        check_values(success.json(), DAYS[-2:])
        assert success.json()["nineTurnMarkers"] == []
        assert not client.app.state.technical_indicator_runtime.admission.active_leases
