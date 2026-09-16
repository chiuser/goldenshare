"""Real rule routes and retained-request protocol against isolated PostgreSQL."""
import asyncio
from time import perf_counter
from datetime import timedelta
from uuid import UUID

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select, func, event
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from tests.test_wealth_trading_assistant_rule_storage import rule_database
from tests.test_wealth_trading_assistant_rule_commands import command_database, NOW, plan, identity
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.models.wealth.trading_assistant.rules import Rule, RuleVersion, RuleExecution
from src.biz.models.wealth.trading_assistant.ledger import Ledger
from src.foundation.models.core.trade_calendar import TradeCalendar


def test_real_create_query_revise_close_recovery_and_no_read_side_effect(command_database):
    with command_database.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=NOW.date(),
            is_open=True, pretrade_date=NOW.date() - timedelta(days=1)))
    async def exercise():
        engine = create_async_engine(command_database.url)
        statements = []
        event.listen(engine.sync_engine, "before_cursor_execute", lambda conn, cursor, statement, parameters, context, executemany: statements.append(statement))
        clock, owner = [NOW], [1]
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda: clock[0], executor_id="rule-api")
        app = FastAPI()
        async def auth():
            return owner[0]
        app.include_router(create_trading_assistant_router(auth_dependency=auth, dependencies_dependency=lambda: deps))
        root = "/wealth/market/trading-assistant"
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                command = plan(account).model_dump(mode="json", exclude_unset=True)
                invalid = await client.post(root + "/plans", json=command | {"priceCondition": {"operator": "LTE", "upper": "-1"}})
                assert invalid.status_code == 400 and invalid.json()["fieldErrors"][0]["field"] == "priceCondition.upper"
                saved = await client.post(root + "/plans", json=command)
                assert saved.status_code == 201, saved.text
                rule_id = saved.json()["result"]["ruleId"]
                path = root + "/plans/" + rule_id
                assert (await client.post(root + "/plans", json=command)).json() == saved.json()
                detail = await client.get(path)
                assert detail.status_code == 200, detail.text
                assert detail.json()["maintenance"]["canEditConditions"] is True
                for params in ({"accountMode": "ALL", "limit": "1.0"}, {"accountMode": "ALL", "status": "ENDED"}, {"accountMode": "ALL", "extra": "x"}):
                    assert (await client.get(root + "/plans", params=params)).status_code == 400
                statements.clear()
                started = perf_counter()
                page = await client.get(root + "/plans", params={"accountMode": "SINGLE", "accountId": str(account), "keyword": "000001.sz"})
                assert page.status_code == 200 and len(page.json()["items"]) == 1, page.text
                elapsed_ms = (perf_counter() - started) * 1000
                print(dict(rule_list_sql=len(statements), response_bytes=len(page.content), elapsed_ms=round(elapsed_ms, 2)))
                assert elapsed_ms < 5000 and len(statements) < 40
                assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
                clock[0] += timedelta(minutes=1)
                revised = await client.post(path + "/condition-revisions", json=dict(**identity(), expectedStateVersion="1",
                    priceCondition=None, volumeCondition={"operator": "GTE", "thresholdLots": "100.00"}))
                assert revised.status_code == 200, revised.text
                versions = await client.get(path + "/condition-versions", params={"limit": 1})
                assert versions.status_code == 200 and versions.json()["nextCursor"], versions.text
                assert (await client.get(path + "/checks")).json() == dict(items=[], nextCursor=None)
                pending = await client.get(root + "/write-requests/pending", params=dict(scopeType="RULE", ruleType="PLAN", ruleId=rule_id))
                assert pending.status_code == 200, pending.text
                assert (await client.get(root + "/write-requests/pending", params=dict(scopeType="RULE_CREATE", ruleType="ALERT", tsCode="000001.SZ"))).status_code == 200
                for bad in (dict(scopeType="RULE", ruleType="PLAN", ruleId=rule_id, accountId=str(account)),
                            dict(scopeType="ACCOUNT_CREATE", ruleType="PLAN")):
                    assert (await client.get(root + "/write-requests/pending", params=bad)).status_code == 400
                # Past deadline still allows closing without any market read.
                clock[0] += timedelta(hours=8)
                closed = await client.post(path + "/close", json=dict(**identity(), expectedStateVersion="2"))
                assert closed.status_code == 200, closed.text
                recovery = await client.get(root + "/write-requests/" + closed.json()["requestId"])
                assert recovery.status_code == 200 and recovery.json()["scope"]["ruleId"] == rule_id
                after = (await client.get(path)).json()
                assert after["ruleStatus"] == "CLOSED" and after["finalResult"] is None
                assert after["maintenance"]["canClose"] is False
                owner[0] = 2
                for suffix in ("", "/checks", "/condition-versions"):
                    assert (await client.get(path + suffix)).status_code == 404
                assert (await client.get(root + "/alerts/" + rule_id)).status_code == 404
                assert (await client.get(root + "/plans", params=dict(accountMode="ALL"))).json()["items"] == []
                schema = app.openapi()
                assert "CreatePlanCommand" in schema["components"]["schemas"]
        finally:
            await engine.dispose()
    asyncio.run(exercise())
    with command_database.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Ledger).where(Ledger.account_id == account)) == 0
        assert conn.scalar(select(func.count()).select_from(RuleVersion).join(Rule,
            RuleVersion.rule_id == Rule.rule_id).where(Rule.account_id == account)) == 2
        assert conn.scalar(select(RuleExecution.fence).join(Rule,
            RuleExecution.rule_id == Rule.rule_id).where(Rule.account_id == account)) == 2
