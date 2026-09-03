"""Run the built Wealth UI against real routes in a fresh, disposable PG cluster.

Usage: APP_ENV=test JWT_SECRET=<test-only-secret> python -m tests.wealth_watchlist_browser_fixture
No existing database address is accepted. Stop with Ctrl-C; PG is stopped too.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import socket
import tempfile

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import insert
import uvicorn

from src.biz.api.wealth.market import (
    context,
    major_indices,
    stock_detail,
    stock_detail_news,
    stock_detail_nine_turn,
)
from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core_serving.equity_qfq_nineturn_daily import (
    EquityQfqNineTurnDaily,
)
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.news_stock_link import NewsStockLink
from src.foundation.models.core_serving_light.news import NewsLight
from tests.wealth_watchlist_postgres_support import (
    DAY,
    ROOT,
    fixture_app,
    isolated_postgres,
    seed_watchlist_fixture,
    test_headers,
)


def seed_browser_context(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA core_serving_light")
        for model in (
            EquityFactorPro,
            EquityQfqNineTurnDaily,
            IndexBasic,
            IndexDailyServing,
            NewsStockLink,
            NewsLight,
        ):
            model.__table__.create(connection)
        connection.execute(
            insert(EquityFactorPro),
            [
                dict(
                    ts_code=f"{i:06d}.SZ",
                    trade_date=DAY,
                    open=12,
                    close=12.34,
                    high=13,
                    low=11.5,
                    open_qfq=12,
                    close_qfq=12.34,
                    high_qfq=13,
                    low_qfq=11.5,
                    pre_close=12,
                    change=0.34,
                    pct_chg=2.83,
                    vol=1234567,
                    amount=123456,
                    turnover_rate=0.92,
                    volume_ratio=1.08,
                )
                for i in range(1, 205)
            ],
        )
        connection.execute(
            insert(EquityQfqNineTurnDaily),
            [
                dict(
                    ts_code=f"{i:06d}.SZ",
                    trade_date=DAY,
                    up_count=0,
                    down_count=0,
                    formula_version=1,
                    published_at=datetime.now(timezone.utc),
                )
                for i in range(1, 205)
            ],
        )
        indices = [
            ("000001.SH", "上证指数"),
            ("399001.SZ", "深证成指"),
            ("399006.SZ", "创业板指"),
            ("000688.SH", "科创50"),
            ("000300.SH", "沪深300"),
            ("000905.SH", "中证500"),
            ("000852.SH", "中证1000"),
            ("899050.BJ", "北证50"),
            ("000510.SH", "中证A500"),
            ("000016.SH", "上证50"),
        ]
        connection.execute(
            insert(IndexBasic),
            [dict(ts_code=code, name=name) for code, name in indices],
        )
        connection.execute(
            insert(IndexDailyServing),
            [
                dict(
                    ts_code=code,
                    trade_date=DAY,
                    close=4000,
                    change_amount=20,
                    pct_chg=0.5,
                    amount=10000,
                )
                for code, _ in indices
            ],
        )


def browser_app(engine):
    app = fixture_app(engine)
    for router in (
        context.router,
        major_indices.router,
        stock_detail.router,
        stock_detail_news.router,
        stock_detail_nine_turn.router,
    ):
        app.include_router(router, prefix="/api/v1")

    @app.get("/test-session")
    def session_for_browser(user_id: int = 4):
        if user_id not in (1, 2, 3, 4):
            raise ValueError("Unknown fixture owner")
        return {"token": test_headers(user_id)["Authorization"].removeprefix("Bearer ")}

    assets = ROOT / "wealth" / "dist" / "assets"
    app.mount(
        "/wealth/assets", StaticFiles(directory=assets), name="watchlist-test-assets"
    )

    @app.get("/wealth/{path:path}")
    def wealth_page(path: str):
        return FileResponse(ROOT / "wealth" / "dist" / "index.html")

    return app


if __name__ == "__main__":
    # Only a new, private /tmp cluster is used, regardless of normal app settings.
    directory = Path(tempfile.mkdtemp(prefix="watchlist-browser-", dir="/private/tmp"))
    with isolated_postgres(directory) as engine:
        seed_watchlist_fixture(engine)
        seed_browser_context(engine)
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        print(f"WATCHLIST_SMOKE_URL=http://127.0.0.1:{port}", flush=True)
        uvicorn.run(
            browser_app(engine), host="127.0.0.1", port=port, log_level="warning"
        )
