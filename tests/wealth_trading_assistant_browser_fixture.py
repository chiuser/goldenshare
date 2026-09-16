"""Real M2 routes and M3 lifecycle in a newly created local PostgreSQL only.

Run with APP_ENV=test and a test-only JWT_SECRET; no existing DB URL is accepted.
"""
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import socket
import signal
import tempfile
import logging
from uuid import UUID, uuid4
from typing import Literal

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import insert, text, select
from sqlalchemy.orm import Session
import uvicorn

from src.app.api.v1.trading_assistant import router, owner
from src.app.auth.api.auth import router as auth_router
from src.app.auth.jwt_service import JWTService
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.app.models.app_user import AppUser
from src.app.models.auth_user_role import AuthUserRole
from src.app.runtime.trading_assistant_lifespan import trading_assistant_lifespan
from src.biz.api.wealth.market import major_indices, stock_search
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountLedgerScope, RuleScope
from src.biz.services.wealth.market.trading_assistant.write_protocol import scope_key
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.equity_dividend import EquityDividend
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.dc_index import DcIndex
from src.foundation.models.core_serving.dc_member import DcMember
from src.biz.api.wealth.market.trading_assistant.errors import TradingAssistantRoute
from src.biz.schemas.wealth.market.trading_assistant.common import ReadContext
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay
from tests.wealth_trading_assistant_fixture_support import fixed_fixture_clock
from tests.wealth_watchlist_postgres_support import ROOT, isolated_postgres
from src.foundation.clients.local_lake.stock_rule_minute_reader import StockRuleMinuteReader
from src.biz.models.wealth.trading_assistant.rules import RobotIdentity
from types import SimpleNamespace
from unittest.mock import patch
import asyncio
from time import monotonic
from tests.test_wealth_trading_assistant_robot_storage import CIPHER
from src.biz.services.wealth.market.trading_assistant.feishu_protocol import SendOutcome
from src.app.runtime.trading_assistant_notifications import run_notifications
from src.biz.schemas.wealth.market.trading_assistant.robot import CandidateCommand, TestCandidateCommand, ConfirmCandidateCommand

NOW = datetime(2026, 9, 11, 8, tzinfo=timezone.utc)

def seed(engine):
    with engine.begin() as conn:
        for schema in ("app", "core", "core_serving"):
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        for model in (AppUser, AuthUserRole, Security, TradeCalendar, IndexBasic, IndexDailyServing,
                      EquityDailyBar, EquitySuspendD, EquityDividend, EquityAdjFactor, DcIndex, DcMember):
            model.__table__.create(conn)
        conn.execute(insert(AppUser), [dict(id=i, username=f"ta-browser-{i}", password_hash="unused-test-only") for i in (1, 2)])
        scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
        with Operations.context(MigrationContext.configure(conn)):
            previous_revision = "20260907_000170"
            for revision_id in (*[f"20260912_{number:06d}" for number in range(171, 177)], "20260915_000177", *[f"20260916_{number:06d}" for number in range(178, 181)]):
                revision = scripts.get_revision(revision_id)
                if revision.down_revision != previous_revision:
                    raise ValueError("Unexpected fixture migration chain")
                revision.module.upgrade()
                previous_revision = revision.revision
        conn.execute(insert(Security), [dict(ts_code=code, symbol=code[:6], name=name, cnspell=spelling, exchange="SZSE",
            security_type="EQUITY", curr_type="CNY", list_status="L", source="isolated-browser-fixture")
            for code, name, spelling in (("000001.SZ", "测试股票", "CSGP"), ("000002.SZ", "缺价股票", "QJGP"))])
        previous = date(2026, 8, 31)
        for offset in range(14):
            day = date(2026, 9, 1) + timedelta(days=offset)
            opened = day.day in (1, 2, 3, 4, 7, 8, 9, 10, 11, 14)  # Explicit synthetic September calendar.
            conn.execute(insert(TradeCalendar), dict(exchange="SSE", trade_date=day, is_open=opened, pretrade_date=previous))
            if opened:
                previous = day
                if day <= NOW.date():
                    conn.execute(insert(EquityDailyBar), dict(ts_code="000001.SZ", trade_date=day,
                        close="12.00", source="tushare"))
        # Market source facts only. Accounts and published results still come
        # exclusively from the actual command and M3 paths.
        for index in range(1, 12):
            code = f"{100 + index:06d}.SZ"
            conn.execute(insert(Security), dict(ts_code=code, symbol=code[:6], name=f"持仓样本{index:02d}",
                cnspell=f"CCYB{index}", exchange="SZSE", security_type="EQUITY", curr_type="CNY", list_status="L", source="isolated-browser-fixture"))
            conn.execute(insert(EquityDailyBar), [dict(ts_code=code, trade_date=date(2026, 9, day), close=str(10 + index), source="tushare") for day in (10, 11)])
        conn.execute(insert(DcIndex), dict(ts_code="BKTEST", trade_date=date(2026, 9, 11), name="测试三级行业", idx_type="行业板块", level="东财三级行业"))
        conn.execute(insert(DcMember), [dict(ts_code="BKTEST", trade_date=date(2026, 9, 11), con_code=f"{100 + i:06d}.SZ") for i in range(1, 12)])
        from tests.wealth_trading_assistant_analysis_fixture import seed_analysis_sources
        seed_analysis_sources(conn)

def browser_app(database):
    clock = [NOW]
    class OfflineTransport:
        outcome = SendOutcome("SUCCEEDED", None, 0)
        calls = 0
        async def send(self, webhook, payload):
            # This object never constructs an HTTP client.
            self.calls += 1
            return self.outcome
    transport = OfflineTransport()
    async def offline_loop(dependencies, **kwargs):
        await run_notifications(dependencies, transport=transport, **{**kwargs, "public_base_url": "https://wealth.example"})
    @asynccontextmanager
    async def lifespan(app):
        from tests.test_stock_mins_reader import _write_bars
        from src.biz.services.wealth.market.trading_assistant.rule_calendar import session_minutes
        with tempfile.TemporaryDirectory(prefix="ta-rule-minutes-", dir="/private/tmp") as source_root, fixed_fixture_clock(database, clock):
            rows = [("000001.SZ", 1, day, minute.at.replace(tzinfo=None).isoformat(),
                9, 9, 9, 9, 100, 900, "SZSE") for day in (date(2026,9,11), date(2026,9,14)) for minute in session_minutes(day)]
            _write_bars(Path(source_root), code="000001.SZ", freq=1, rows=rows)
            with patch("src.app.runtime.trading_assistant_lifespan.load_credential_cipher", return_value=CIPHER), patch(
                    "src.app.runtime.trading_assistant_lifespan.run_notifications", offline_loop):
                async with trading_assistant_lifespan(app, database_url=database.url,
                        logger=logging.getLogger("ta-isolated-fixture"), minute_reader=StockRuleMinuteReader(Path(source_root))):
                    yield
    app = FastAPI(lifespan=lifespan)
    install_exception_handlers(app)
    def session():
        with Session(database) as db:
            yield db
    app.dependency_overrides[get_db_session] = session
    app.state.fixture_clock = clock
    for item in (router, auth_router, stock_search.router, major_indices.router):
        app.include_router(item, prefix="/api/v1")
    # Not a product API: exercises the actual injected read path and JWT owner.
    from fastapi import APIRouter
    probe = APIRouter(route_class=TradingAssistantRoute)
    @probe.get("/test-read-context", response_model=ReadContext)
    async def read_context(accountMode: Literal["ALL", "SINGLE"], accountId: UUID | None = None,
                           readContext: str | None = None, owner_id: int = Depends(owner)):
        def through(session, deadline):
            # A SELECT before capture proves isolation was set by the runner.
            return session.scalar(select(text("TIMESTAMPTZ '2026-09-11 07:00:00+00'")))
        return await app.state.trading_assistant.read_current(lambda s,d,b:b.context,
            owner_id=owner_id, account_mode=accountMode,
            account_id=accountId, context_token=readContext, resolve_target_through=through)
    @probe.get("/test-publication/{account_id}")
    async def publication(account_id: UUID, owner_id: int = Depends(owner)):
        def read(session, deadline, basis):
            reference = basis.context.accounts[0]
            if reference.publishedGenerationId is None:
                return None
            row = session.scalars(select(AccountSnapshot).join(PublicationDay,
                (PublicationDay.account_id == AccountSnapshot.account_id) &
                (PublicationDay.day_result_id == AccountSnapshot.day_result_id)).where(
                PublicationDay.account_id == account_id,
                PublicationDay.generation_id == UUID(reference.publishedGenerationId))
                .order_by(AccountSnapshot.trade_date.desc()).limit(1)).one()
            return dict(generationId=reference.publishedGenerationId,
                cash=str(row.cash_amount), marketValue=str(row.stock_market_value),
                holdingProfit=str(row.holding_profit_amount))
        return await app.state.trading_assistant.read_current(read, owner_id=owner_id,
            account_mode="SINGLE", account_id=account_id, resolve_target_through=lambda s,d:NOW)
    app.include_router(probe)
    @app.post("/test-rule-clock")
    def rule_clock(at: datetime):
        if at.tzinfo is None or at < clock[0] or at.date() > date(2026, 9, 14):
            raise ValueError("Only forward fixture time within seeded September facts")
        clock[0] = at
        return {"now": at.isoformat()}
    @app.post("/test-rule-robot")
    async def rule_robot():
        deps = app.state.trading_assistant
        current = await deps.read(lambda s,d: deps.robot_configuration.read(s, owner_id=1, deadline=d))
        if current.robot:
            return {"robotId": current.robot.robotId}
        def ids(): return dict(requestId=str(uuid4()), attemptId=str(uuid4()))
        candidate = (await deps.robot_commands.create(owner_id=1, command=CandidateCommand(**ids(),
            name="隔离资格机器人", expectedConfigVersionId=None, keywords=[], signingSecret=dict(action="CLEAR"),
            webhook=dict(action="REPLACE", value="https://open.feishu.cn/open-apis/bot/v2/hook/isolated-browser")))).result
        test = (await deps.robot_commands.test(owner_id=1, candidate_id=UUID(candidate.candidateId),
            command=TestCandidateCommand(**ids(), expectedCandidateVersion=candidate.candidateVersion))).result
        until = monotonic() + 15
        while monotonic() < until:
            result = await deps.read(lambda s,d: deps.robot_tests.read(s, owner_id=1,
                candidate_id=UUID(candidate.candidateId), test_id=UUID(test.testId), deadline=d))
            if result.state == "SUCCEEDED":
                saved = await deps.robot_commands.confirm(owner_id=1, candidate_id=UUID(candidate.candidateId),
                    command=ConfirmCandidateCommand(**ids(), expectedConfigVersionId=None, testId=test.testId, receivedConfirmed=True))
                return {"robotId": saved.result.robotId}
            await asyncio.sleep(.1)
        raise RuntimeError("Isolated robot test did not finish")
    @app.post("/test-notification-outcome")
    def notification_outcome(state: Literal["SUCCEEDED", "FAILED", "UNKNOWN"]):
        transport.outcome = SendOutcome(state, None if state == "SUCCEEDED" else "隔离发送验证", 0 if state == "SUCCEEDED" else None)
        clock[0] += timedelta(seconds=2)
        return {"calls": transport.calls}
    @app.get("/test-session")
    def test_session(user_id: int = 1):
        if user_id not in (1, 2):
            raise ValueError("Unknown fixture user")
        return {"fixture": "trading-assistant-isolated", "token": JWTService().encode(user_id=user_id, username=f"ta-browser-{user_id}", is_admin=False)}
    # Test-only stopped-worker scenario. These endpoints exist solely in this
    # module's fresh synthetic database app, never in the production router.
    @app.post("/test-pending-rule/{rule_id}")
    async def pending_rule(rule_id: UUID):
        deps = app.state.trading_assistant
        request_id, attempt_id = uuid4(), uuid4()
        deadline = Deadline.after_ms(5000)
        scope = RuleScope(scopeType="RULE", ruleType="PLAN", ruleId=str(rule_id))
        await deps.transactions.run(lambda s:deps.rules.protocol.register(s, owner_id=1, request_id=request_id,
            attempt_id=attempt_id, scope=scope, operation="RULE_CLOSE", payload=dict(expectedStateVersion="1"),
            now=clock[0], executor_id="stopped-rule-fixture", deadline=deadline), deadline=deadline, write=True)
        return {"requestId":str(request_id)}
    @app.post("/test-expire-rule/{rule_id}/{request_id}")
    async def expire_rule(rule_id: UUID, request_id: UUID):
        deps = app.state.trading_assistant
        clock[0] += timedelta(minutes=1)
        deadline = Deadline.after_ms(5000)
        scope = RuleScope(scopeType="RULE", ruleType="PLAN", ruleId=str(rule_id))
        await deps.transactions.run(lambda s:deps.rules.protocol.expire(s, owner_id=1, request_id=request_id,
            key=scope_key(scope), now=clock[0], deadline=deadline), deadline=deadline, write=True)
        return {"expired":True}
    @app.post("/test-pending-cash/{account_id}")
    async def pending_cash(account_id: UUID):
        deps = app.state.trading_assistant
        request_id, attempt_id = uuid4(), uuid4()
        deadline = Deadline.after_ms(5000)
        await deps.transactions.run(lambda s:deps.ledger.protocol.register(s, owner_id=1, request_id=request_id,
            attempt_id=attempt_id, scope=AccountLedgerScope(scopeType="ACCOUNT_LEDGER", accountId=str(account_id)),
            operation="CASH_FLOW_CREATE", payload=dict(direction="IN", occurredOn="2026-09-11", amount="25.00", note=None),
            now=clock[0], executor_id="stopped-browser-fixture", deadline=deadline), deadline=deadline, write=True)
        return {"requestId":str(request_id)}
    @app.post("/test-expire/{account_id}/{request_id}")
    async def expire(account_id: UUID, request_id: UUID):
        deps = app.state.trading_assistant
        clock[0] += timedelta(minutes=1)
        deadline = Deadline.after_ms(5000)
        await deps.transactions.run(lambda s:deps.ledger.protocol.expire(s, owner_id=1, request_id=request_id,
            key=f"ACCOUNT_LEDGER:{account_id}", now=clock[0], deadline=deadline), deadline=deadline, write=True)
        return {"expired":True}
    app.mount("/wealth/assets", StaticFiles(directory=ROOT / "wealth/dist/assets"))
    @app.get("/wealth/{path:path}")
    def frontend(path: str):
        return FileResponse(ROOT / "wealth/dist/index.html")
    return app

if __name__ == "__main__":
    def interrupted(signum, frame):
        # Uvicorn re-raises captured signals after shutdown. Unwind the PG
        # context instead of exiting before its fixture cleanup can run.
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    directory = Path(tempfile.mkdtemp(prefix="ta-browser-", dir="/private/tmp"))
    with isolated_postgres(directory) as database:
        seed(database)
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        print(f"TA_SMOKE_URL=http://127.0.0.1:{port}", flush=True)
        uvicorn.run(browser_app(database), host="127.0.0.1", port=port, log_level="warning")
