"""Formal daily return route backed by real commands and M3 publication."""
import asyncio
from decimal import Decimal
from time import monotonic
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from tests.test_wealth_trading_assistant_m41_fixture import ROOT, wait_stage
from tests.wealth_trading_assistant_browser_fixture import browser_app, seed
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_daily_returns_actual_profit_fees_coverage_and_permissions(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        app = browser_app(database)

        async def run():
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    endpoint = ROOT + "/returns/days/2026-09-11"
                    login = await client.get("/test-session")
                    assert login.status_code == 200, login.text
                    client.headers["Authorization"] = "Bearer " + login.json()["token"]

                    async def create(code=None):
                        response = await client.post(ROOT + "/accounts", json=dict(
                            requestId=str(uuid4()), attemptId=str(uuid4()), name=code or "现金", brokerName="券商",
                            commissionRateWan="3.00", minimumCommission="5.00", stampTaxRatePct="0.05",
                            initialCash="1000.00", initialPositions=[] if code is None else [dict(
                                clientRowId="one", tsCode=code, openedOn="2026-09-10", quantity=1000,
                                availableQuantity=1000, costPrice="10.00")]))
                        assert response.status_code == 201, response.text
                        account = response.json()["result"]["account"]["accountId"]
                        await wait_stage(client, account, "WAITING_DATA" if code == "000002.SZ" else "PUBLISHED")
                        return account

                    account = await create("000001.SZ")
                    params = dict(accountMode="SINGLE", accountId=account)
                    previous = await client.get(ROOT + "/returns/days/2026-09-10", params=params)
                    assert previous.status_code == 200, previous.text
                    assert previous.json()["profitAmount"] == "1989.00"
                    assert previous.json()["coverage"]["accounts"][0]["initializedOn"] == "2026-09-11"
                    token = previous.json()["readContext"]["contextToken"]
                    sold = await client.post(ROOT + f"/accounts/{account}/trades", json=dict(
                        requestId=str(uuid4()), attemptId=str(uuid4()), direction="SELL", tsCode="000001.SZ",
                        tradeDate="2026-09-11", quantity=400, price="12.00"))
                    assert sold.status_code == 201, sold.text
                    await wait_stage(client, account, "PUBLISHED")
                    assert (await client.get(endpoint, params={**params, "readContext": token})).status_code == 409
                    cash = await create()
                    statements = []
                    def observe(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)
                    engine = app.state.trading_assistant.transactions.engine.sync_engine
                    event.listen(engine, "before_cursor_execute", observe)
                    began = monotonic()
                    try:
                        response = await client.get(endpoint, params={"accountMode": "ALL"})
                    finally:
                        elapsed = monotonic() - began
                        event.remove(engine, "before_cursor_execute", observe)
                    assert response.status_code == 200, response.text
                    value = response.json()
                    assert value["coverage"]["dataStatus"] == "Ready"
                    assert (value["profitAmount"], value["capitalAmount"], value["returnPct"]) == ("-5.00", "10000.00", "-0.05")
                    assert (value["closedTradeCount"], value["closedProfitAmount"]) == (1, "792.60")
                    assert (value["commissionAmount"], value["stampTaxAmount"], value["feeDataStatus"]) == ("5.00", "2.40", "Ready")
                    assert value["recordsScope"]["requestedStartDate"] == "2026-09-11"
                    contribution_url = endpoint + "/contributions"
                    contribution_statements = []
                    def observe_contributions(conn, cursor, statement, parameters, context, executemany):
                        contribution_statements.append(statement)
                    started_contributions = monotonic()
                    event.listen(engine, "before_cursor_execute", observe_contributions)
                    try:
                        contributions = await client.get(contribution_url, params=dict(accountMode="ALL", limit=1,
                            readContext=value["readContext"]["contextToken"]))
                    finally:
                        event.remove(engine, "before_cursor_execute", observe_contributions)
                    contribution_elapsed = monotonic() - started_contributions
                    assert contribution_elapsed < 5
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in contribution_statements)
                    print(f"M5 contributions: SQL={len(contribution_statements)}, bytes={len(contributions.content)}, seconds={contribution_elapsed:.5f}")
                    assert contributions.status_code == 200, contributions.text
                    parts = contributions.json()
                    assert (parts["totalCount"], parts["totalProfitAmount"], parts["nextCursor"]) == (1, "-5.00", None)
                    assert (parts["items"][0]["profitAmount"], parts["items"][0]["capitalAmount"],
                        parts["items"][0]["returnPct"]) == ("-5.00", "10000.00", "-0.05")
                    assert parts["items"][0]["accountRounds"][0]["accountId"] == account
                    assert parts["items"][0]["accountRounds"][0]["roundNumber"] == 1
                    for bad in ({"limit":"0"}, {"cursor":"bad"}, {"extra":"1"}):
                        assert (await client.get(contribution_url, params={"accountMode":"ALL", **bad})).status_code == 400
                    assert (await client.get(contribution_url, params={**params, "readContext":token})).status_code == 409
                    day_sql_count = len(statements)
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    curve_params = dict(accountMode="ALL", stockMode="ALL", requestedStartDate="2026-09-11",
                                        requestedEndDate="2026-09-11", granularity="MONTH")
                    curve_url = ROOT + "/returns/curve"
                    began_curve = monotonic()
                    statements.clear()
                    event.listen(engine, "before_cursor_execute", observe)
                    try:
                        curve = await client.get(curve_url, params=curve_params)
                    finally:
                        curve_elapsed = monotonic() - began_curve
                        event.remove(engine, "before_cursor_execute", observe)
                    assert curve.status_code == 200, curve.text
                    curve_value = curve.json()
                    assert curve_value["historyStartDate"] == "2026-09-10"
                    point = curve_value["points"][0]
                    assert (point["periodStartDate"], point["periodEndDate"], point["isPeriodEnded"]) == (
                        "2026-09-01", "2026-09-30", False)
                    assert (point["profitAmount"], point["capitalAmount"], point["returnPct"]) == ("1984.00", "10000.00", "19.84")
                    assert curve_value["requestedStartDate"] == "2026-09-11"
                    assert point["accounts"][0]["effectiveStartDate"] in ("2026-09-10", "2026-09-11")
                    assert curve_value["coverage"]["dataStatus"] == "Ready"
                    assert curve_elapsed < 5
                    print(f"M5 curve API: SQL={len(statements)}, bytes={len(curve.content)}, elapsed={curve_elapsed:.5f}s")
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    for grain, expected_dates in (("DAY", ("2026-09-11", "2026-09-11")),
                                                   ("WEEK", ("2026-09-07", "2026-09-13"))):
                        response_curve = await client.get(curve_url, params={**curve_params, "granularity":grain})
                        assert response_curve.status_code == 200, response_curve.text
                        p = response_curve.json()["points"][0]
                        assert (p["periodStartDate"], p["periodEndDate"]) == expected_dates
                        assert p["profitAmount"] == ("-5.00" if grain == "DAY" else "1984.00")
                    single_curve = await client.get(curve_url, params={**curve_params, "stockMode":"SINGLE", "tsCode":"000001.SZ"})
                    assert single_curve.status_code == 200, single_curve.text
                    assert single_curve.json()["historyStartDate"] == "2026-09-10"
                    assert single_curve.json()["points"][0]["profitAmount"] == "1984.00"
                    empty_curve = await client.get(curve_url, params={**curve_params, "requestedStartDate":"2026-10-01", "requestedEndDate":"2026-10-31"})
                    assert empty_curve.status_code == 200, empty_curve.text
                    assert empty_curve.json()["points"] == []
                    assert empty_curve.json()["historyStartDate"] == "2026-09-10"
                    cash_curve = await client.get(curve_url, params={**curve_params, "accountMode":"SINGLE", "accountId":cash})
                    assert cash_curve.status_code == 200, cash_curve.text
                    assert cash_curve.json()["historyStartDate"] == "2026-09-11"
                    absent_stock = await client.get(curve_url, params={**curve_params, "accountMode":"SINGLE", "accountId":cash,
                        "stockMode":"SINGLE", "tsCode":"000001.SZ"})
                    assert absent_stock.status_code == 200, absent_stock.text
                    assert absent_stock.json()["historyStartDate"] is None
                    assert all(p["profitAmount"] is None for p in absent_stock.json()["points"])
                    for bad in ({"granularity":"YEAR"}, {"extra":"1"}, {"requestedEndDate":"2026-09-01"}):
                        assert (await client.get(curve_url, params={**curve_params, **bad})).status_code == 400
                    assert (await client.get(curve_url, params={**curve_params, **params, "readContext":token})).status_code == 409
                    monthly_days = await client.get(curve_url, params={**curve_params, "requestedStartDate":"2026-09-01", "granularity":"DAY"})
                    assert monthly_days.status_code == 200, monthly_days.text
                    assert len(monthly_days.json()["points"]) == 11
                    assert sum(Decimal(p["profitAmount"]) for p in monthly_days.json()["points"] if p["profitAmount"] is not None) == 1984
                    assert all(p["profitAmount"] is None for p in monthly_days.json()["points"][:9])
                    assert (await client.get(curve_url, params=list(curve_params.items()) + [("granularity", "DAY")])).status_code == 400
                    assert (await client.get(curve_url, params={**curve_params, "stockMode":"SINGLE", "tsCode":"999999.SZ"})).status_code == 404
                    calendar_url = ROOT + "/returns/calendar"
                    started_calendar = monotonic()
                    calendar = await client.get(calendar_url, params=dict(accountMode="ALL", month="2026-09"))
                    assert calendar.status_code == 200, calendar.text
                    cal = calendar.json()
                    assert len(cal["days"]) == 25
                    assert (cal["days"][0]["date"], cal["days"][-1]["date"]) == ("2026-08-31", "2026-10-02")
                    assert cal["monthSummary"]["periodProfitAmount"] == "1984.00"
                    assert cal["monthSummary"]["computedDayCount"] == 2
                    assert cal["monthSummary"]["positiveDayCount"] == cal["monthSummary"]["negativeDayCount"] == 1
                    assert cal["monthSummary"]["minDailyReturnPct"] == "-0.05"
                    assert cal["monthSummary"]["minDailyReturnDates"] == ["2026-09-11"]
                    assert cal["monthSummary"]["closedProfitAmount"] == "792.60"
                    assert all(d["profitAmount"] is None and d["calculationState"] is None and d["readContext"] is None
                        for d in cal["days"] if d["temporalState"] == "FUTURE")
                    assert cal["days"][0]["calculationState"] == "Empty" and cal["days"][0]["reason"]
                    for month in ("2026-08", "2026-10"):
                        empty_month = await client.get(calendar_url, params=dict(accountMode="ALL", month=month))
                        assert empty_month.status_code == 200, empty_month.text
                        assert empty_month.json()["monthSummary"]["periodProfitAmount"] is None
                        assert empty_month.json()["monthSummary"]["computedDayCount"] == 0
                    for bad in ({"month":"2026-13"}, {"extra":"1"}, {"stockMode":"ALL"}):
                        assert (await client.get(calendar_url, params={"accountMode":"ALL", "month":"2026-09", **bad})).status_code == 400
                    print(f"M5 calendar API: bytes={len(calendar.content)}, elapsed={monotonic()-started_calendar:.5f}s")
                    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
                    assert elapsed < 5
                    print(f"M5 day API: accounts=2, SQL={day_sql_count}, bytes={len(response.content)}, elapsed={elapsed:.5f}s")
                    cash_value = (await client.get(endpoint, params=dict(accountMode="SINGLE", accountId=cash))).json()
                    assert cash_value["coverage"]["dataStatus"] == "Empty" and cash_value["profitAmount"] is None
                    for day in ("2026-09-09", "2026-09-12"):
                        empty = await client.get(ROOT + "/returns/days/" + day, params=params)
                        assert empty.status_code == 200, empty.text
                        assert empty.json()["coverage"]["dataStatus"] == "Empty"
                    await create("000002.SZ")
                    incomplete_curve = await client.get(curve_url, params=curve_params)
                    assert incomplete_curve.status_code == 200, incomplete_curve.text
                    assert incomplete_curve.json()["points"][0]["profitAmount"] is None
                    assert incomplete_curve.json()["coverage"]["dataStatus"] == "Partial"
                    missing_calendar = await client.get(calendar_url, params=dict(accountMode="ALL", month="2026-09"))
                    assert missing_calendar.status_code == 200, missing_calendar.text
                    assert missing_calendar.json()["monthSummary"]["periodProfitAmount"] is None
                    partial = await client.get(endpoint, params={"accountMode": "ALL"})
                    assert partial.status_code == 200, partial.text
                    assert partial.json()["coverage"]["dataStatus"] == "Partial"
                    assert partial.json()["profitAmount"] is None
                    assert partial.json()["commissionAmount"] == "5.00"
                    missing_parts = await client.get(contribution_url, params={"accountMode":"ALL"})
                    assert missing_parts.status_code == 200, missing_parts.text
                    assert missing_parts.json()["totalCount"] == 2
                    assert missing_parts.json()["totalProfitAmount"] is None
                    assert missing_parts.json()["items"][1]["stockRef"]["tsCode"] == "000002.SZ"
                    assert missing_parts.json()["items"][1]["profitAmount"] is None
                    assert missing_parts.json()["items"][1]["accountRounds"] == []
                    for invalid in ("accountMode=ALL&extra=1", "accountMode=ALL&accountMode=ALL", "accountMode=SINGLE"):
                        assert (await client.get(endpoint + "?" + invalid)).status_code == 400
                    assert (await client.get(ROOT + "/returns/days/2026-02-30", params=params)).status_code == 400
                    assert (await client.get(endpoint, params=dict(accountMode="SINGLE", accountId=str(uuid4())))).status_code == 404
                    other = await client.get("/test-session", params={"user_id": 2})
                    client.headers["Authorization"] = "Bearer " + other.json()["token"]
                    assert (await client.get(calendar_url, params={**params, "month":"2026-09"})).status_code == 404
                    assert (await client.get(curve_url, params={**curve_params, **params})).status_code == 404
                    assert (await client.get(endpoint, params=params)).status_code == 404
                    assert (await client.get(endpoint, params={**params, "readContext": token})).status_code == 404
                    del client.headers["Authorization"]
                    assert (await client.get(calendar_url, params=dict(accountMode="ALL", month="2026-09"))).status_code == 401
                    assert (await client.get(curve_url, params=curve_params)).status_code == 401
                    assert (await client.get(endpoint, params={"accountMode": "ALL"})).status_code == 401
        asyncio.run(run())
