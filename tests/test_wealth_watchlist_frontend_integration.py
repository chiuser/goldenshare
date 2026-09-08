"""Real TypeScript client -> HTTP -> authenticated routes -> isolated PostgreSQL.

No browser, existing database URL, deployment, or production credentials.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from threading import Thread
from time import monotonic, sleep

import pytest
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import uvicorn

from src.biz.queries.wealth.market.watchlist.watchlist_query_service import WatchlistQueryService
from src.foundation.config.settings import get_settings
from tests.wealth_watchlist_postgres_support import (
    PG_BIN, ROOT, fixture_app, isolated_postgres, seed_watchlist_fixture,
    test_headers as headers,
)


class ClientConnection(dict):
    def __repr__(self):
        return f"ClientConnection(origin={self['origin']!r}, tokens=<synthetic/redacted>)"


@pytest.fixture(scope="module")
def live_watchlist(tmp_path_factory):
    assert (PG_BIN / "initdb").is_file(), "Existing PostgreSQL installation required"
    assert (ROOT / "wealth/node_modules/vite/dist/node/index.js").is_file()
    patch = pytest.MonkeyPatch()
    patch.setenv("APP_ENV", "test")
    patch.setenv("JWT_SECRET", "watchlist-http-test-only-not-production")
    get_settings.cache_clear()
    try:
        with isolated_postgres(tmp_path_factory.mktemp("watchlist-http-pg")) as engine:
            seed_watchlist_fixture(engine)
            app = fixture_app(engine)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(
                    app, log_level="error", access_log=False, lifespan="off",
                ))
                thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
                thread.start()
                try:
                    deadline = monotonic() + 10
                    while not server.started and thread.is_alive() and monotonic() < deadline:
                        sleep(0.01)
                    assert server.started, "Isolated HTTP test server failed to start"
                    yield ClientConnection({
                        "origin": f"http://127.0.0.1:{port}",
                        "tokens": {str(i): headers(i)["Authorization"][7:] for i in range(1, 55)},
                    })
                finally:
                    server.should_exit = True
                    thread.join(timeout=10)
                    assert not thread.is_alive(), "Test HTTP server did not stop"
    finally:
        patch.undo()
        get_settings.cache_clear()


def run_client(connection, mode):
    # Tokens are synthetic and passed through stdin, never command-line arguments/logs.
    result = subprocess.run(
        ["node", str(ROOT / "tests/wealth_watchlist_client_integration.mjs")],
        input=json.dumps({**connection, "mode": mode}), text=True,
        capture_output=True, cwd=ROOT, timeout=180,
        env={**os.environ, "NO_COLOR": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    print(json.dumps(report, ensure_ascii=False))
    return report


def test_real_frontend_client_all_contracts_and_performance(live_watchlist):
    report = run_client(live_watchlist, "contracts")
    assert report["contracts"] == 15
    assert report["sortTraversals"] == 16
    assert report["performanceSamples"] == 30


def test_watchlist_contracts_are_mounted_in_application_router():
    from src.app.api.router import router

    application = FastAPI()
    application.include_router(router)
    paths = {
        (method, route.path.removeprefix("/api/v1/wealth/market/watchlist"))
        for route in application.routes
        if route.path.startswith("/api/v1/wealth/market/watchlist")
        for method in route.methods
    }
    assert paths == {
        ("GET", "/groups"), ("POST", "/groups"),
        ("PATCH", "/groups/{group_id}/color"), ("DELETE", "/groups/{group_id}"),
        ("GET", "/groups/{group_id}/items"), ("GET", "/groups/{group_id}/search"),
        ("PUT", "/groups/{group_id}/items/{ts_code}"),
        *(("POST", f"/groups/{{group_id}}/actions/{action}") for action in
          ("move", "add-to-groups", "remove", "pin", "unpin")),
        ("GET", "/stocks/{ts_code}/groups"), ("PUT", "/stocks/{ts_code}/groups"),
        ("GET", "/summary"),
    }


@pytest.mark.parametrize("mode", ["unknown", "failed", "refresh-failed"])
def test_real_frontend_write_outcomes(live_watchlist, monkeypatch, mode):
    commit = Session.commit
    query = WatchlistQueryService.get_groups
    committed = False

    def fault_commit(session):
        nonlocal committed
        if mode == "failed":
            raise IntegrityError("COMMIT", {}, RuntimeError("test constraint rejection"))
        commit(session)
        committed = True
        if mode == "unknown":
            raise ConnectionError("test communication failure after actual commit")

    def fault_query(service, *args, **kwargs):
        nonlocal committed
        if mode == "refresh-failed" and committed:
            committed = False
            raise RuntimeError("test query failure after successful write")
        return query(service, *args, **kwargs)

    monkeypatch.setattr(Session, "commit", fault_commit)
    monkeypatch.setattr(WatchlistQueryService, "get_groups", fault_query)
    report = run_client(live_watchlist, mode)
    assert report["writes"] == 1
    assert report["persisted"] == (mode != "failed")
