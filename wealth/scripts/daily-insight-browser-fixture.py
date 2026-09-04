"""Bounded browser acceptance: real Daily Insight routes/query/schema, synthetic SQLite.

Never accepts a database URL. Starts a random loopback port only for the subprocess;
the server thread and in-memory database are closed in finally. No Prod access.
Usage: PYTHONPATH=. uv run python wealth/scripts/daily-insight-browser-fixture.py
       /private/tmp/<evidence-dir> /absolute/path/to/playwright/index.mjs
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Lock, Thread
import time
from unittest.mock import patch

os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "daily-insight-browser-fixture-only-not-production"

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import uvicorn

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.biz.api.wealth.market import context, sector_analysis
from src.biz.services.wealth.market.sector_analysis.daily_facts.template_renderer import SectorDailyInsightTemplateRenderer
from tests.test_wealth_sector_daily_insight_query_service import Item, NOW, Summary, seed_insight

ROOT = Path(__file__).resolve().parents[2]


def seed_rows(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
    with Session(engine) as session:
        seed_insight(session)
        originals = session.scalars(select(Item)).all()
        for row in originals:
            for i in range(1, 80):
                values = {column.name: getattr(row, column.name) for column in Item.__table__.columns}
                values.update(sector_code=f"BK{row.industry_level}{(i * 2 + (1 if row.return_pct_1d > 0 else 2)):03d}.DC", stable_order=i + 1, sector_name=f"行业长名称测试{i}")
                # These fields remain real template inputs; API/schema are not mocked.
                values["rendered_text"] = SectorDailyInsightTemplateRenderer().render(
                    category=values["category"], sector_name=values["sector_name"], industry_level=values["industry_level"], values=values,
                    evidence_types=("PRICE_VOLUME",), previous_evidence_types=("PRICE_VOLUME",),
                )[2]
                session.add(Item(**values))
        for summary in session.scalars(select(Summary)):
            summary.sector_count = 337
            summary.calculable_count = 337
            summary.up_count = 80
            summary.down_count = 80
            summary.flat_count = 177
            for column in Summary.__table__.columns:
                if column.name.startswith("missing_"):
                    setattr(summary, column.name, 0)
        session.commit()


def main():
    output = Path(sys.argv[1]).resolve()
    if not str(output).startswith("/private/tmp/"):
        raise ValueError("Evidence output must be in /private/tmp")
    output.mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    seed_rows(engine)
    # FastAPI may enter/exit a sync dependency on different thread-pool threads.
    # A non-owner-bound mutex serializes the one SQLite connection across requests.
    lock = Lock()
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(context.router, prefix="/api/v1")
    app.include_router(sector_analysis.router, prefix="/api/v1")

    def session_dependency():
        with lock, Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = session_dependency
    # Authentication alone is stubbed; 401 is covered by the real backend tests.
    app.dependency_overrides[require_quote_access] = lambda: None

    @app.get("/test-fixture")
    def identify():
        return {"kind": "daily-insight-isolated-sqlite"}

    @app.get("/api/v1/wealth/market/major-indices")
    def empty_ticker():
        return {"majorIndices": {"rows": []}, "pageStatus": {"status": "READY", "displayText": "测试环境"}}

    app.mount("/wealth/assets", StaticFiles(directory=ROOT / "wealth/dist/assets"))

    @app.get("/wealth/{path:path}")
    def page(path: str):
        return FileResponse(ROOT / "wealth/dist/index.html")

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=5))
    thread = Thread(target=server.run, daemon=True)
    try:
        with patch("src.biz.queries.wealth.market.context.market_page_context_query._now_cn", return_value=NOW):
            thread.start()
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.05)
            if not server.started:
                raise RuntimeError("Isolated HTTP fixture did not start")
            subprocess.run(["node", str(ROOT / "wealth/scripts/daily-insight-browser-smoke.mjs"), f"http://127.0.0.1:{port}", str(output), sys.argv[2]], check=True, timeout=180)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()
        if thread.is_alive():
            raise RuntimeError("Fixture server failed to stop")
        print(f"Fixture closed: 127.0.0.1:{port}", flush=True)


if __name__ == "__main__":
    main()
