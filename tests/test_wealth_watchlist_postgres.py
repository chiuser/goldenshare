from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from statistics import quantiles
from threading import Barrier
from time import perf_counter

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.watchlist.watchlist_query import WatchlistQuery
from src.biz.services.wealth.market.watchlist.watchlist_command_service import (
    WatchlistCommandService,
)
from src.foundation.config.settings import get_settings
from tests.wealth_watchlist_postgres_support import (
    DAY,
    PG_BIN,
    fixture_app,
    isolated_postgres,
    seed_watchlist_fixture,
    test_headers as headers,
)

BASE = "/api/v1/wealth/market/watchlist"


@pytest.fixture(scope="module")
def postgres_fixture(tmp_path_factory):
    if not (PG_BIN / "initdb").is_file():
        pytest.skip("Local PostgreSQL initdb is required")
    patch = pytest.MonkeyPatch()
    patch.setenv("APP_ENV", "test")
    patch.setenv("JWT_SECRET", "watchlist-isolated-test-key-never-for-production")
    get_settings.cache_clear()
    try:
        with isolated_postgres(tmp_path_factory.mktemp("watchlist-pg")) as engine:
            seed_watchlist_fixture(engine)
            yield engine, fixture_app(engine)
    finally:
        patch.undo()
        get_settings.cache_clear()


def test_real_postgres_migration_and_eight_concurrent_api_adds(postgres_fixture):
    engine, app = postgres_fixture
    constraints = inspect(engine).get_unique_constraints(
        "wealth_watchlist_item", schema="app"
    )
    assert any(
        row["name"] == "uq_wealth_watchlist_item_user_stock" for row in constraints
    )
    assert any(
        row["column_names"] == ["user_id", "id"]
        for row in inspect(engine).get_indexes("wealth_watchlist_item", schema="app")
    )
    gate = Barrier(8)

    def add():
        with TestClient(app) as client:
            gate.wait(timeout=10)
            response = client.put(f"{BASE}/items/000001.SZ", headers=headers(5))
            assert response.status_code == 200, response.text
            return response.json()

    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(lambda _: add(), range(8)))
    assert sum(row["created"] for row in outcomes) == 1
    assert all(row["totalCount"] == 1 for row in outcomes)
    with Session(engine) as session:
        assert WatchlistQuery().count(session, user_id=5) == 1


def test_unrelated_fk_failure_is_not_misclassified_as_duplicate(postgres_fixture):
    engine, _ = postgres_fixture
    from sqlalchemy.exc import IntegrityError

    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            WatchlistCommandService().add(session, user_id=9999, ts_code="000001.SZ")
        assert WatchlistQuery().count(session, user_id=9999) == 0


def test_commit_failure_rolls_back_nested_insert(postgres_fixture, monkeypatch):
    engine, _ = postgres_fixture
    with Session(engine) as session:

        def fail_commit():
            raise RuntimeError("controlled commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="controlled commit failure"):
            WatchlistCommandService().add(session, user_id=1, ts_code="004998.SZ")
    with Session(engine) as independent:
        assert not WatchlistQuery().contains(
            independent, user_id=1, ts_code="004998.SZ"
        )


def test_real_api_payloads_timings_and_bounded_indexed_joins(postgres_fixture):
    engine, app = postgres_fixture
    sizes, timings = {}, {}
    with TestClient(app) as client:
        for owner, count in [(1, 0), (2, 20), (3, 100), (4, 200)]:
            response = client.get(
                BASE,
                params={"tradeDate": str(DAY), "limit": max(1, count)},
                headers=headers(owner),
            )
            assert response.status_code == 200
            assert len(response.json()["items"]) == count
            sizes[count] = len(response.content)
            assert sizes[count] <= 256 * 1024
        for name, method, path in [
            ("list", "GET", f"{BASE}?tradeDate={DAY}"),
            ("summary", "GET", BASE + "/summary"),
            ("membership", "GET", BASE + "/items/000001.SZ"),
            ("search", "GET", BASE + "/search?keyword=CSGP1"),
            ("PUT", "PUT", BASE + "/items/004999.SZ"),
            ("DELETE", "DELETE", BASE + "/items/004999.SZ"),
        ]:
            samples = []
            for _ in range(30):
                start = perf_counter()
                response = client.request(method, path, headers=headers())
                samples.append((perf_counter() - start) * 1000)
                assert response.status_code == 200, response.text
            timings[name] = round(quantiles(samples, n=100, method="inclusive")[94], 2)
            assert timings[name] <= (200 if name == "search" else 300)

    captured = []

    def capture(connection, _cursor, statement, parameters, _context, _many):
        if statement.startswith("SELECT") and "wealth_watchlist_item" in statement:
            captured.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as session:
            query = WatchlistQuery()
            members = query.list_memberships(
                session, user_id=4, limit=100, after_id=None
            )
            query.load_snapshot(
                session, user_id=4, memberships=members[:100], observed_trade_date=DAY
            )
            assert len(captured) == 2  # Membership page + one bounded fact join.
            query.count(session, user_id=4)
            query.contains(session, user_id=4, ts_code="000001.SZ")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(captured) == 4
    plans = []
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        for statement, parameters in captured:
            plan = "\n".join(
                row[0]
                for row in connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS) " + statement, parameters
                )
            )
            plans.append(plan)
    assert "idx_wealth_watchlist_item_user_id_id" in plans[0]
    assert (
        "LIMIT" not in plans[1]
    )  # Only the previously bounded ID set reaches the join.
    assert "Index" in plans[1]
    for primary_key in (
        "pk_equity_daily_bar",
        "pk_equity_daily_basic",
        "pk_equity_moneyflow",
    ):
        assert primary_key in plans[1]
    assert "Index" in plans[2]  # Summary uses an owner-scoped index scan.
    assert "uq_wealth_watchlist_item_user_stock" in plans[3]
    print(
        json.dumps(
            {"payloadBytes": sizes, "p95Ms": timings, "plans": plans},
            ensure_ascii=False,
            indent=2,
        )
    )
