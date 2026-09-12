"""Actual App router and JWT/UserRepository against a newly created PostgreSQL."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import insert, text, select, func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from src.app.api.v1.trading_assistant import router
from src.app.auth.jwt_service import JWTService
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.app.models.app_user import AppUser
from src.app.models.auth_user_role import AuthUserRole
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_real_jwt_owner_isolation_and_rejected_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr("src.app.auth.jwt_service.get_web_settings", lambda: SimpleNamespace(
        jwt_secret="isolated-ta-test-secret-not-a-production-credential", jwt_expire_minutes=5))
    with isolated_postgres(tmp_path) as database:
        with database.begin() as connection:
            connection.execute(text("CREATE SCHEMA app"))
            AppUser.__table__.create(connection)
            AuthUserRole.__table__.create(connection)
            connection.execute(insert(AppUser), [dict(id=i, username=f"ta-jwt-{i}",
                password_hash="unused-test-password", is_active=i != 3) for i in (1, 2, 3)])
            migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000171").module
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()

        def session():
            with Session(database) as db:
                yield db

        async def exercise():
            engine = create_async_engine(database.url)
            app = FastAPI()
            install_exception_handlers(app)
            app.dependency_overrides[get_db_session] = session
            app.state.trading_assistant = build_trading_assistant_dependencies(engine,
                policy=TradingAssistantExecutionPolicyV1(), now=lambda: datetime(2026, 9, 12, 8, tzinfo=timezone.utc),
                executor_id="real-jwt-api")
            app.include_router(router, prefix="/api/v1")
            root = "/api/v1/wealth/market/trading-assistant"
            tokens = {i: JWTService().encode(user_id=i, username=f"ta-jwt-{i}", is_admin=False) for i in (1, 2, 3, 4)}
            headers = lambda i: {"Authorization": "Bearer " + tokens[i]}
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
                    command = dict(requestId=str(uuid4()), attemptId=str(uuid4()), name="真实认证测试", brokerName="券商",
                        initialCash="1000.00", initialPositions=[], commissionRateWan="3.00", minimumCommission="5.00", stampTaxRatePct="0.05")
                    for invalid in ({}, {"Authorization": "Bearer invalid"}, headers(3), headers(4)):
                        assert (await client.post(root + "/accounts", headers=invalid, json=command)).status_code == 401
                    with database.connect() as connection:
                        assert connection.scalar(select(func.count()).select_from(Account)) == 0
                    saved = await client.post(root + "/accounts", headers=headers(1), json=command)
                    assert saved.status_code == 201, saved.text
                    assert saved.headers["cache-control"] == "no-store"
                    account = saved.json()["result"]["account"]["accountId"]
                    assert (await client.get(root + "/accounts", headers=headers(2))).json() == {"items": []}
                    assert (await client.get(root + f"/accounts/{account}/initialization", headers=headers(2))).status_code == 404
                    assert (await client.get(root + "/write-requests/" + command["requestId"], headers=headers(2))).status_code == 404
                    replay = await client.post(root + "/accounts", headers=headers(1), json=command)
                    assert replay.status_code == 200 and replay.json() == saved.json()
                    tampered = await client.post(root + "/accounts", headers=headers(1), json={**command, "ownerId": 2})
                    assert tampered.status_code == 400
                    with database.connect() as connection:
                        assert connection.scalar(select(func.count()).select_from(Account)) == 1
            finally:
                await engine.dispose()
        asyncio.run(exercise())
