"""Real M2 routes with synthetic facts in a newly created local PostgreSQL only.

Run with APP_ENV=test and a test-only JWT_SECRET; no existing DB URL is accepted.
"""
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import socket
import signal
import tempfile
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session
import uvicorn

from src.app.api.v1.trading_assistant import router
from src.app.auth.api.auth import router as auth_router
from src.app.auth.jwt_service import JWTService
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.app.models.app_user import AppUser
from src.app.models.auth_user_role import AuthUserRole
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.api.wealth.market import major_indices, stock_search
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountLedgerScope
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.security_serving import Security
from tests.wealth_watchlist_postgres_support import ROOT, isolated_postgres

NOW = datetime(2026, 9, 11, 8, tzinfo=timezone.utc)

def seed(engine):
    with engine.begin() as conn:
        for schema in ("app", "core", "core_serving"):
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        for model in (AppUser, AuthUserRole, Security, TradeCalendar, IndexBasic, IndexDailyServing):
            model.__table__.create(conn)
        conn.execute(insert(AppUser), [dict(id=i, username=f"ta-browser-{i}", password_hash="unused-test-only") for i in (1, 2)])
        migration = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_revision("20260912_000171").module
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        conn.execute(insert(Security), [dict(ts_code="000001.SZ", symbol="000001", name="测试股票", cnspell="CSGP", exchange="SZSE",
            security_type="EQUITY", curr_type="CNY", list_status="L", source="isolated-browser-fixture")])
        previous = date(2026, 8, 31)
        for offset in range(14):
            day = date(2026, 9, 1) + timedelta(days=offset)
            opened = day.weekday() < 5  # Explicit synthetic fixture, not a production calendar fallback.
            conn.execute(insert(TradeCalendar), dict(exchange="SSE", trade_date=day, is_open=opened, pretrade_date=previous))
            if opened:
                previous = day

def browser_app(database):
    engine = create_async_engine(database.url)
    clock = [NOW]
    @asynccontextmanager
    async def lifespan(app):
        yield
        await engine.dispose()
    app = FastAPI(lifespan=lifespan)
    install_exception_handlers(app)
    def session():
        with Session(database) as db:
            yield db
    app.dependency_overrides[get_db_session] = session
    app.state.trading_assistant = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
        now=lambda: clock[0], executor_id="isolated-browser")
    for item in (router, auth_router, stock_search.router, major_indices.router):
        app.include_router(item, prefix="/api/v1")
    @app.get("/test-session")
    def test_session(user_id: int = 1):
        if user_id not in (1, 2):
            raise ValueError("Unknown fixture user")
        return {"fixture": "trading-assistant-isolated", "token": JWTService().encode(user_id=user_id, username=f"ta-browser-{user_id}", is_admin=False)}
    # Test-only stopped-worker scenario. These endpoints exist solely in this
    # module's fresh synthetic database app, never in the production router.
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
