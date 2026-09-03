"""Isolated watchlist development fixture; never accepts an existing DB URL."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path
import shutil
import socket
import subprocess

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from src.app.auth.jwt_service import JWTService
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.app.models.app_user import AppUser
from src.app.models.auth_role import AuthRole
from src.app.models.auth_role_permission import AuthRolePermission
from src.app.models.auth_permission import AuthPermission
from src.app.models.auth_user_role import AuthUserRole
from src.biz.api.wealth.market import watchlist
from src.biz.models.wealth.watchlist_item import WealthWatchlistItem
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 9, 2)
PG_BIN = Path(
    shutil.which("postgres") or "/opt/homebrew/opt/postgresql@18/bin/postgres"
).parent


@contextmanager
def isolated_postgres(directory: Path):
    """Start a new local cluster under the supplied *empty temporary* directory."""
    if not directory.is_dir() or any(directory.iterdir()):
        raise ValueError("A newly created, empty test directory is required")
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    data = directory / "pgdata"
    subprocess.run(
        [
            str(PG_BIN / "initdb"),
            "-D",
            str(data),
            "-A",
            "trust",
            "-U",
            "watchlist_test",
            "--no-locale",
            "--encoding=UTF8",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            str(PG_BIN / "pg_ctl"),
            "-D",
            str(data),
            "-l",
            str(directory / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {port} -k ''",
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    engine = create_engine(
        f"postgresql+psycopg://watchlist_test@127.0.0.1:{port}/postgres", pool_size=12
    )
    try:
        yield engine
    finally:
        engine.dispose()
        subprocess.run(
            [str(PG_BIN / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
            check=True,
            capture_output=True,
        )


def seed_watchlist_fixture(engine):
    """Synthetic, bounded data in the freshly created cluster only."""
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA app")
        connection.exec_driver_sql("CREATE SCHEMA core_serving")
        connection.exec_driver_sql("CREATE SCHEMA core")
        for model in (
            AppUser,
            AuthRole,
            AuthPermission,
            AuthUserRole,
            AuthRolePermission,
            Security,
            TradeCalendar,
            EquityDailyBar,
            EquityDailyBasic,
            EquityMoneyflow,
        ):
            model.__table__.create(connection)
        migration = (
            ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
            .get_revision("20260903_000169")
            .module
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.execute(
            insert(AppUser),
            [
                dict(
                    id=i,
                    username=f"watchlist-test-{i}",
                    password_hash="not-a-login-password",
                )
                for i in range(1, 55)
            ],
        )
        connection.execute(
            insert(Security),
            [
                dict(
                    ts_code=f"{i:06d}.SZ",
                    symbol=f"{i:06d}",
                    name=f"测试股票{i}",
                    cnspell=f"CSGP{i}",
                    industry="银行",
                    list_status="L",
                    security_type="EQUITY",
                    exchange="SZSE",
                    curr_type="CNY",
                    source="watchlist_test",
                )
                for i in range(1, 5001)
            ],
        )
        connection.execute(
            insert(TradeCalendar),
            [
                dict(
                    exchange="SSE",
                    trade_date=DAY,
                    is_open=True,
                    pretrade_date=date(2026, 9, 1),
                )
            ],
        )
        connection.execute(
            insert(EquityDailyBar),
            [
                dict(
                    ts_code=f"{i:06d}.SZ",
                    trade_date=DAY,
                    close=12.34,
                    pct_chg=[1.73, -1.5, 0][i % 3],
                    vol=1234567,
                )
                for i in range(1, 5001)
            ],
        )
        connection.execute(
            insert(EquityDailyBasic),
            [
                dict(
                    ts_code=f"{i:06d}.SZ",
                    trade_date=DAY,
                    pe_ttm=None if i % 5 == 0 else 5.62,
                    pb=0.71,
                    volume_ratio=1.08,
                    turnover_rate=0.92,
                )
                for i in range(1, 5001)
                if i % 7
            ],
        )
        connection.execute(
            insert(EquityMoneyflow),
            [
                dict(
                    ts_code=f"{i:06d}.SZ",
                    trade_date=DAY,
                    net_mf_amount=[2189.4, -2189.4, 0][i % 3],
                )
                for i in range(1, 5001)
                if i % 7
            ],
        )
        # Owners 1..4 are the 0/20/100/200 fixtures. Owner 5 is for concurrency.
        counts = {1: 0, 2: 20, 3: 100, 4: 200, 5: 0}
        for owner in range(1, 55):
            rows = [
                dict(user_id=owner, ts_code=f"{i:06d}.SZ")
                for i in range(1, counts.get(owner, 200) + 1)
            ]
            if rows:
                connection.execute(insert(WealthWatchlistItem), rows)
        connection.exec_driver_sql("ANALYZE")


def test_headers(user_id=4):
    return {
        "Authorization": "Bearer "
        + JWTService().encode(
            user_id=user_id, username=f"watchlist-test-{user_id}", is_admin=False
        )
    }


def fixture_app(engine):
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(watchlist.router, prefix="/api/v1")

    def session_dependency():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = session_dependency
    return app
