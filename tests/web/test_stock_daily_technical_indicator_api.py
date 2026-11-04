"""LLD §14.1 ordinary API checks. Real SQLite/route; controlled calculation.

P01/R01–R05 are deliberately not executed here. The temporary serving schema
is the current EquityFactorPro/Security/TradeCalendar producer definition.
"""
from datetime import date, timedelta

from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.core_serving.security_serving import Security
from tests.stock_daily_kline_helpers import backend_for_client
from tests.web.test_wealth_stock_detail_api import _ensure_stock_detail_tables, _seed_stock_detail_data


PATH = "/api/v1/wealth/market/stock-detail/kline"


def test_original_limits_and_openapi(app_client, db_session, monkeypatch, record_property):
    _ensure_stock_detail_tables(db_session)
    db_session.add(Security(ts_code="600000.SH", symbol="600000", name="浦发银行",
                            security_type="EQUITY", source="tushare"))
    days = tuple(date(2020, 1, 1) + timedelta(days=i) for i in range(500))
    db_session.add_all(EquityFactorPro(
        ts_code="600000.SH", trade_date=day, source="tushare", open_qfq=10,
        high_qfq=11, low_qfq=9, close_qfq=10, pre_close=10, change=0, pct_chg=0,
        vol=100, amount=1000, turnover_rate=None, volume_ratio=None,
    ) for day in days)
    db_session.commit()
    with backend_for_client(app_client, monkeypatch, db_session.get_bind(), record_property) as (_, calls, _):
        for limit in (None, 1, 500):
            params = {"tsCode": "600000.SH", "endDate": days[-1].isoformat()}
            if limit is not None:
                params["limit"] = limit
            expected_limit = 500 if limit is None else limit
            response = app_client.get(PATH, params=params)
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["meta"]["count"] == payload["meta"]["limit"] == len(payload["bars"]) == expected_limit
            assert [bar["tradeDate"] for bar in payload["bars"]] == [day.isoformat() for day in days[-expected_limit:]]
            assert payload["adjustment"] == "forward" and payload["sourceAdjustment"] == "qfq"
            assert set(payload) == {"pageContext", "stockRef", "period", "adjustment", "sourceAdjustment",
                                    "bars", "meta", "dataStatus", "debugInfo"}
            assert response.headers["content-type"] == "application/json"
        assert len(calls) == 3 and all(len(item.calculations) == 10 for item in calls)
    operation = app_client.app.openapi()["paths"][PATH]["get"]
    params = {item["name"]: item["schema"] for item in operation["parameters"] if item["in"] == "query"}
    assert set(params) == {"tsCode", "period", "adjustment", "tradeDate", "startDate", "endDate", "limit", "debug"}
    assert params["limit"]["default"] == 500 and params["period"]["default"] == "day"
    assert params["adjustment"]["default"] == "forward"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/StockDetailKlineResponseDto")


def test_prewait_errors_unknown_and_empty(app_client, db_session, monkeypatch, record_property):
    _seed_stock_detail_data(db_session)
    with backend_for_client(app_client, monkeypatch, db_session.get_bind(), record_property) as (backend, calls, controls):
        original = backend.runtime.admission.acquire
        admissions = []
        async def acquire(control):
            admissions.append(control)
            return await original(control)
        monkeypatch.setattr(backend.runtime.admission, "acquire", acquire)
        for changes in ({"period": "week"}, {"adjustment": "qfq"}, {"limit": 0}, {"limit": 501},
                        {"startDate": "2026-05-29", "endDate": "2026-05-28"}):
            response = app_client.get(PATH, params={"tsCode": "603806.SH", **changes})
            assert response.status_code == 400 and response.json()["code"] == "400001"
        assert not admissions and not calls and len(controls) == 5
        unknown = app_client.get(PATH, params={"tsCode": "UNKNOWN", "endDate": "2026-05-29"})
        assert unknown.status_code == 404 and unknown.json()["code"] == "404001"
        assert len(admissions) == 1 and not calls
        empty = app_client.get(PATH, params={"tsCode": "603806.SH", "endDate": "1900-01-01"})
        assert empty.status_code == 200 and empty.json()["bars"] == []
        assert empty.json()["dataStatus"]["status"] == "EMPTY" and not calls
        normal = app_client.get(PATH, params={"tsCode": " 603806.sh ", "endDate": "2026-05-29", "limit": 2, "sql": "ignored"})
        assert normal.status_code == 200 and len(normal.json()["bars"]) == 2
        assert len(admissions) == 3 and len(calls) == 1
        assert len(controls) == 8 and not backend.runtime.admission.active_leases
