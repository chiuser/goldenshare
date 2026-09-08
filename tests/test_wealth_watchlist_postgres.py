from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from statistics import quantiles
from threading import Barrier, Event
from time import perf_counter

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.models.app_user import AppUser
from src.biz.models.wealth.watchlist_group import WealthWatchlistGroup as Group
from src.biz.models.wealth.watchlist_membership import (
    WealthWatchlistMembership as Membership,
)
from src.biz.queries.wealth.market.watchlist.watchlist_group_query import (
    WatchlistGroupQuery,
)
from src.biz.queries.wealth.market.watchlist.watchlist_query_service import (
    WatchlistQueryService,
)
from src.biz.services.wealth.market.watchlist.watchlist_command_service import (
    WatchlistCommandService,
)
from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    MAX_API_ID,
    PALETTE,
    WatchlistError,
    normalize_group_name,
)
from src.foundation.config.settings import get_settings
from tests.wealth_watchlist_postgres_support import (
    DAY,
    PG_BIN,
    ROOT,
    fixture_app,
    isolated_postgres,
    seed_watchlist_fixture,
    test_headers as headers,
)

BASE = "/api/v1/wealth/market/watchlist"
REVISION = "20260907_000170"


@pytest.fixture(scope="module")
def postgres_fixture(tmp_path_factory):
    if not (PG_BIN / "initdb").is_file():
        pytest.fail("Real PostgreSQL is required for stage-one acceptance")
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


def default_id(engine, owner):
    with Session(engine) as session:
        return WatchlistGroupQuery().get_default_group(session, user_id=owner).id


def create(engine, owner, name):
    with Session(engine) as session:
        return (
            WatchlistCommandService()
            .create_group(session, user_id=owner, name=name, color=PALETTE[0])
            .group.id
        )


def members(engine, group):
    with Session(engine) as session:
        return [
            (m.id, m.ts_code, m.is_pinned, m.created_at, m.updated_at)
            for m in session.scalars(
                select(Membership)
                .where(Membership.group_id == group)
                .order_by(Membership.id)
            )
        ]


def test_migrated_schema_defaults_and_sequence(postgres_fixture):
    engine, _ = postgres_fixture
    assert not inspect(engine).has_table("wealth_watchlist_item", schema="app")
    assert {
        r["name"]
        for r in inspect(engine).get_unique_constraints(
            "wealth_watchlist_membership", schema="app"
        )
    } == {"uq_wealth_watchlist_membership_group_stock"}
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM app.app_user")
        ) == connection.scalar(
            text("SELECT count(*) FROM app.wealth_watchlist_group WHERE is_default")
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM app.wealth_watchlist_membership WHERE is_pinned"
                )
            )
            == 0
        )
        maximum = connection.scalar(
            text("SELECT max(id) FROM app.wealth_watchlist_membership")
        )
    with Session(engine) as session:
        d = default_id(engine, 1)
        result = WatchlistCommandService().add_item(
            session, user_id=1, group_id=d, ts_code="005000.SZ"
        )
        assert result.created
    assert members(engine, d)[0][0] > maximum


def test_eight_concurrent_real_api_adds_are_idempotent(postgres_fixture):
    engine, app = postgres_fixture
    d = default_id(engine, 5)
    gate = Barrier(8)

    def add():
        with TestClient(app) as client:
            gate.wait(timeout=10)
            result = client.put(
                f"{BASE}/groups/{d}/items/000001.SZ", headers=headers(5)
            )
            assert result.status_code == 200, result.text
            return result.json()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: add(), range(8)))
    assert sum(r["created"] for r in results) == 1
    assert all(r["memberCount"] == 1 for r in results)
    assert len(members(engine, d)) == 1


def test_concurrent_creates_respect_nine_custom_limit(postgres_fixture):
    engine, _ = postgres_fixture
    for i in range(8):
        create(engine, 6, f"已建{i}")
    gate = Barrier(4)

    def attempt(i):
        with Session(engine) as session:
            gate.wait(timeout=10)
            try:
                return (
                    WatchlistCommandService()
                    .create_group(session, user_id=6, name=f"竞争{i}", color=PALETTE[0])
                    .group.id
                )
            except WatchlistError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert sum(type(r) is int for r in results) == 1
    assert results.count("WL_GROUP_LIMIT_REACHED") == 3
    with Session(engine) as session:
        assert len(WatchlistGroupQuery().list_groups(session, user_id=6)) == 10


def test_concurrent_name_conflict_is_specific(postgres_fixture):
    engine, _ = postgres_fixture
    gate = Barrier(2)

    def attempt(_):
        with Session(engine) as session:
            gate.wait(timeout=10)
            try:
                return (
                    WatchlistCommandService()
                    .create_group(session, user_id=7, name="同名", color=PALETTE[0])
                    .group.id
                )
            except WatchlistError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert (
        sum(type(r) is int for r in results) == 1
        and results.count("WL_GROUP_NAME_CONFLICT") == 1
    )


def test_delete_reads_group_list_after_waiting_for_default_lock(postgres_fixture):
    engine, _ = postgres_fixture
    owner = 8
    last = create(engine, owner, "原末组")
    started = Event()
    with Session(engine) as creating:
        default = WatchlistGroupQuery().get_default_group(
            creating, user_id=owner, for_update=True
        )
        default_group_id = default.id
        new = Group(user_id=owner, name="新右邻", color=PALETTE[0])
        creating.add(new)
        creating.flush()
        new_id = new.id

        def remove():
            with Session(engine) as deleting:
                started.set()
                return WatchlistCommandService().delete_group(
                    deleting, user_id=owner, group_id=last
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(remove)
            assert started.wait(5)
            creating.commit()
            result = future.result(timeout=10)
    assert result.nextGroupId == new_id and result.nextGroupId != default_group_id


def test_maximum_batch_real_counts_order_and_atomic_stale(postgres_fixture):
    engine, _ = postgres_fixture
    owner = 9
    d = default_id(engine, owner)
    ids = [r[0] for r in members(engine, d)]
    targets = [create(engine, owner, f"目标{i}") for i in range(9)]
    with Session(engine) as session:
        service = WatchlistCommandService()
        start = perf_counter()
        result = service.batch(
            session,
            user_id=owner,
            group_id=d,
            action="ADD_TO_GROUPS",
            membership_ids=list(reversed(ids)),
            target_group_ids=list(reversed(targets)),
        )
        elapsed = (perf_counter() - start) * 1000
        assert result.createdCount == 1800 and result.requestedCount == 200
        assert [g.groupId for g in result.groupCounts] == [d, *targets]
        assert all(g.memberCount == 200 for g in result.groupCounts)
        assert (
            service.batch(
                session,
                user_id=owner,
                group_id=d,
                action="ADD_TO_GROUPS",
                membership_ids=ids,
                target_group_ids=targets,
            ).createdCount
            == 0
        )
        with pytest.raises(WatchlistError) as error:
            service.batch(
                session,
                user_id=owner,
                group_id=d,
                action="MOVE",
                membership_ids=[ids[0], MAX_API_ID],
                target_group_ids=[targets[0]],
            )
        assert error.value.code == "WL_SELECTION_STALE"
    expected_codes = [r[1] for r in members(engine, d)]
    for target in targets:
        assert [r[1] for r in members(engine, target)] == expected_codes
    assert len(members(engine, d)) == 200
    assert elapsed <= 800
    print(
        json.dumps(
            {"maxBatchCreated": result.createdCount, "elapsedMs": round(elapsed, 2)}
        )
    )


def test_only_designated_duplicate_is_ignored_by_insert_helper(postgres_fixture):
    engine, _ = postgres_fixture
    d = default_id(engine, 10)
    service = WatchlistCommandService()
    with Session(engine) as session:
        WatchlistGroupQuery().get_owned_group(
            session, user_id=10, group_id=d, for_update=True
        )
        assert service._insert_missing_memberships(session, [(d, "000001.SZ")]) == 0
        with pytest.raises(IntegrityError):
            service._insert_missing_memberships(session, [(MAX_API_ID, "000001.SZ")])
        session.rollback()
        with pytest.raises(IntegrityError):
            service._insert_missing_memberships(session, [(d, None)])
        session.rollback()


def test_mid_move_failure_and_dto_failure_rollback_real_database(
    postgres_fixture, monkeypatch
):
    engine, _ = postgres_fixture
    d = default_id(engine, 11)
    target = create(engine, 11, "目标")
    before = members(engine, d)

    def fail_count(*_args, **_kwargs):
        raise RuntimeError("count failed before DTO")

    with Session(engine) as session:
        service = WatchlistCommandService()
        monkeypatch.setattr(service._groups, "count_memberships", fail_count)
        with pytest.raises(WatchlistError) as error:
            service.batch(
                session,
                user_id=11,
                group_id=d,
                action="MOVE",
                membership_ids=[before[0][0]],
                target_group_ids=[target],
            )
        assert error.value.code == "WL_WRITE_FAILED"
    assert members(engine, d) == before and members(engine, target) == []
    with Session(engine) as session:
        with monkeypatch.context() as patch:
            patch.setattr(
                "src.biz.services.wealth.market.watchlist.watchlist_command_service.WatchlistBatchActionResponseDto",
                lambda **_: (_ for _ in ()).throw(ValueError("DTO failure")),
            )
            with pytest.raises(WatchlistError):
                WatchlistCommandService().batch(
                    session,
                    user_id=11,
                    group_id=d,
                    action="PIN",
                    membership_ids=[before[0][0]],
                )
    assert members(engine, d) == before


def test_postcommit_sql_is_zero_for_every_write(postgres_fixture):
    engine, _ = postgres_fixture
    owner = 12
    d = default_id(engine, owner)
    with Session(engine) as session:
        state = {"committed": False}

        def committed(_session):
            state["committed"] = True

        def sql(_conn, _cursor, _statement, *_rest):
            assert not state["committed"], "SQL executed after mutation commit"

        event.listen(session, "after_commit", committed)
        event.listen(engine, "before_cursor_execute", sql)
        try:
            service = WatchlistCommandService()

            def run(operation):
                state["committed"] = False
                result = operation()
                assert state["committed"]
                result.model_dump(mode="json")
                return result

            a = run(
                lambda: service.create_group(
                    session, user_id=owner, name="新分组", color=PALETTE[0]
                )
            ).group.id
            run(
                lambda: service.change_color(
                    session, user_id=owner, group_id=a, color=PALETTE[1]
                )
            )
            run(
                lambda: service.add_item(
                    session, user_id=owner, group_id=a, ts_code="000001.SZ"
                )
            )
            state["committed"] = False
            mid = session.scalar(select(Membership.id).where(Membership.group_id == a))
            run(
                lambda: service.batch(
                    session,
                    user_id=owner,
                    group_id=a,
                    action="PIN",
                    membership_ids=[mid],
                )
            )
            run(
                lambda: service.batch(
                    session,
                    user_id=owner,
                    group_id=a,
                    action="UNPIN",
                    membership_ids=[mid],
                )
            )
            run(
                lambda: service.batch(
                    session,
                    user_id=owner,
                    group_id=a,
                    action="ADD_TO_GROUPS",
                    membership_ids=[mid],
                    target_group_ids=[d],
                )
            )
            run(
                lambda: service.batch(
                    session,
                    user_id=owner,
                    group_id=a,
                    action="MOVE",
                    membership_ids=[mid],
                    target_group_ids=[d],
                )
            )
            run(
                lambda: service.replace_stock_groups(
                    session, user_id=owner, ts_code="000001.SZ", group_ids=[a]
                )
            )
            state["committed"] = False
            mid = session.scalar(select(Membership.id).where(Membership.group_id == a))
            run(
                lambda: service.batch(
                    session,
                    user_id=owner,
                    group_id=a,
                    action="REMOVE",
                    membership_ids=[mid],
                )
            )
            run(lambda: service.delete_group(session, user_id=owner, group_id=a))
        finally:
            event.remove(engine, "before_cursor_execute", sql)
            event.remove(session, "after_commit", committed)


def test_committed_but_response_lost_returns_unknown_without_replay(
    postgres_fixture, monkeypatch
):
    engine, _ = postgres_fixture
    d = default_id(engine, 13)
    with Session(engine) as session:
        commit = session.commit

        def lost():
            commit()
            raise ConnectionError("response lost after actual commit")

        monkeypatch.setattr(session, "commit", lost)
        with pytest.raises(WatchlistError) as error:
            WatchlistCommandService().add_item(
                session, user_id=13, group_id=d, ts_code="005000.SZ"
            )
        assert error.value.code == "WL_WRITE_OUTCOME_UNKNOWN"
    assert sum(row[1] == "005000.SZ" for row in members(engine, d)) == 1


def test_real_api_payload_timings_and_no_n_plus_one(postgres_fixture):
    engine, app = postgres_fixture
    captured = []

    def capture(_connection, _cursor, statement, parameters, *_args):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            captured.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        d = default_id(engine, 4)
        lengths = []
        for limit in (1, 200):
            captured.clear()
            with Session(engine) as session:
                result = WatchlistQueryService().get_page(
                    session,
                    user_id=4,
                    group_id=d,
                    requested_trade_date=DAY,
                    limit=limit,
                    sort_by="peTtm",
                    direction="desc",
                )
                assert len(result.items) == limit
            lengths.append(len(captured))
        assert lengths[0] == lengths[1]
        statements = list(captured)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    plans = []
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        for statement, parameters in statements:
            plans.append(
                "\n".join(
                    r[0]
                    for r in connection.exec_driver_sql(
                        "EXPLAIN (ANALYZE, BUFFERS) " + statement, parameters
                    )
                )
            )
    timings, sizes = {}, {}
    with TestClient(app) as client:
        for limit in (100, 200):
            samples = []
            for _ in range(30):
                start = perf_counter()
                result = client.get(
                    f"{BASE}/groups/{d}/items",
                    headers=headers(4),
                    params={"tradeDate": str(DAY), "limit": limit},
                )
                samples.append((perf_counter() - start) * 1000)
                assert result.status_code == 200, result.text
            timings[limit] = round(quantiles(samples, n=100, method="inclusive")[94], 2)
            sizes[limit] = len(result.content)
            assert timings[limit] <= (300 if limit == 100 else 500)
            assert sizes[limit] <= (256 if limit == 100 else 512) * 1024
        for suffix in (
            "/groups",
            "/summary",
            "/stocks/000001.SZ/groups",
            f"/groups/{d}/search?keyword=CSGP1",
        ):
            assert client.get(BASE + suffix, headers=headers(4)).status_code == 200
    assert any("Index" in plan for plan in plans)
    print(
        json.dumps(
            {
                "sqlCounts": lengths,
                "p95Ms": timings,
                "payloadBytes": sizes,
                "plans": plans,
            },
            ensure_ascii=False,
        )
    )


def migration():
    return (
        ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
        .get_revision(REVISION)
        .module
    )


@pytest.mark.parametrize("scenario", ["empty", "history", "unsafe_id"])
def test_isolated_migration_roundtrip_and_abort(tmp_path, scenario):
    with isolated_postgres(tmp_path) as engine:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA app")
            AppUser.__table__.create(connection)
            old = (
                ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
                .get_revision("20260903_000169")
                .module
            )
            with Operations.context(MigrationContext.configure(connection)):
                old.upgrade()
            if scenario != "empty":
                connection.execute(
                    text(
                        "INSERT INTO app.app_user(id,username,password_hash) VALUES (1,'one','unused'),(2,'empty','unused')"
                    )
                )
                for mid, day, code in [
                    (2, 8, "000001.SZ"),
                    (17, 1, "000002.SZ"),
                    (30, 1, "000003.SZ"),
                ]:
                    if scenario == "unsafe_id" and mid == 30:
                        mid = MAX_API_ID + 1
                    connection.execute(
                        text("""INSERT INTO app.wealth_watchlist_item(id,user_id,ts_code,created_at,updated_at)
                        VALUES (:id,1,:code,:time,:time)"""),
                        dict(
                            id=mid,
                            code=code,
                            time=datetime(2026, 9, day, tzinfo=timezone.utc),
                        ),
                    )
        with engine.connect() as connection:
            original = connection.execute(
                text(
                    "SELECT user_id,id,ts_code,created_at,updated_at FROM app.wealth_watchlist_item ORDER BY user_id,id"
                )
            ).all()
        if scenario == "unsafe_id":
            with pytest.raises(RuntimeError, match="ID exceeds"):
                with (
                    engine.begin() as connection,
                    Operations.context(MigrationContext.configure(connection)),
                ):
                    migration().upgrade()
            assert inspect(engine).has_table("wealth_watchlist_item", schema="app")
            assert not inspect(engine).has_table("wealth_watchlist_group", schema="app")
            return
        with (
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            migration().upgrade()
        assert not inspect(engine).has_table("wealth_watchlist_item", schema="app")
        if scenario == "history":
            d = default_id(engine, 1)
            assert [(1, *row[:2], *row[3:]) for row in members(engine, d)] == original
            with Session(engine) as session:
                service = WatchlistCommandService()
                service.batch(
                    session, user_id=1, group_id=d, action="PIN", membership_ids=[2, 30]
                )
                service.batch(
                    session,
                    user_id=1,
                    group_id=d,
                    action="UNPIN",
                    membership_ids=[2, 30],
                )
            assert [r[0] for r in members(engine, d)] == [2, 17, 30]
            # Pin/unpin legitimately changes updated_at. Downgrade must preserve
            # that new fact, not restore or fabricate the historical timestamp.
            original = [(1, *row[:2], *row[3:]) for row in members(engine, d)]
        with (
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            migration().downgrade()
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT user_id,id,ts_code,created_at,updated_at FROM app.wealth_watchlist_item ORDER BY user_id,id"
                    )
                ).all()
                == original
            )
        assert not inspect(engine).has_table(
            "wealth_watchlist_membership", schema="app"
        )


@pytest.mark.parametrize("fact", ["custom", "pin"])
def test_downgrade_refuses_v2_facts(tmp_path, fact):
    with isolated_postgres(tmp_path) as engine:
        seed_watchlist_fixture(engine)
        # Each branch starts without custom groups or pins; prove both gates independently.
        with engine.begin() as connection:
            if fact == "custom":
                connection.execute(
                    text(
                        "INSERT INTO app.wealth_watchlist_group(user_id,name,color,is_default) VALUES (20,'阻止','#5AA7FF',false)"
                    )
                )
            else:
                connection.execute(
                    text(
                        "UPDATE app.wealth_watchlist_membership SET is_pinned=true WHERE group_id=:g"
                    ),
                    {"g": default_id(engine, 20)},
                )
        with pytest.raises(RuntimeError, match="custom|losslessly"):
            with (
                engine.begin() as connection,
                Operations.context(MigrationContext.configure(connection)),
            ):
                migration().downgrade()
        assert not inspect(engine).has_table("wealth_watchlist_item", schema="app")


def test_opposing_moves_lock_groups_in_the_same_order(postgres_fixture):
    engine, _ = postgres_fixture
    owner = 21
    a, b = create(engine, owner, "左组"), create(engine, owner, "右组")
    with Session(engine) as session:
        service = WatchlistCommandService()
        service.add_item(session, user_id=owner, group_id=a, ts_code="000001.SZ")
        service.add_item(session, user_id=owner, group_id=b, ts_code="000002.SZ")
    mid_a, mid_b = members(engine, a)[0][0], members(engine, b)[0][0]
    gate = Barrier(2)

    def move(source, target, mid):
        with Session(engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            gate.wait(timeout=10)
            return WatchlistCommandService().batch(
                session,
                user_id=owner,
                group_id=source,
                action="MOVE",
                membership_ids=[mid],
                target_group_ids=[target],
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(move, a, b, mid_a), pool.submit(move, b, a, mid_b)]
        assert all(f.result(timeout=10).removedCount == 1 for f in futures)
    assert [row[1] for row in members(engine, a)] == ["000002.SZ"]
    assert [row[1] for row in members(engine, b)] == ["000001.SZ"]


def test_shared_name_vectors_are_stored_exactly_in_postgres(postgres_fixture):
    engine, _ = postgres_fixture
    vectors = json.loads(
        (ROOT / "tests/fixtures/wealth_watchlist_group_names.json").read_text()
    )
    vectors.append(
        dict(
            accepted=True,
            raw="q" + "\u0301" * 511 + " ",
            normalized="q" + "\u0301" * 511,
        )
    )
    for vector in vectors:
        if not vector["accepted"]:
            continue
        with Session(engine) as session:
            group = Group(
                user_id=22, name=normalize_group_name(vector["raw"]), color=PALETTE[0]
            )
            session.add(group)
            session.flush()
            group_id = group.id
            session.expire_all()
            assert session.get(Group, group_id).name == vector["normalized"]
            session.rollback()


def test_postgres_user_delete_cascades_groups_and_members(postgres_fixture):
    engine, _ = postgres_fixture
    owner = 23
    group = create(engine, owner, "级联组")
    with Session(engine) as session:
        WatchlistCommandService().add_item(
            session, user_id=owner, group_id=group, ts_code="000001.SZ"
        )
        group_ids = session.scalars(
            select(Group.id).where(Group.user_id == owner)
        ).all()
        session.execute(delete(AppUser).where(AppUser.id == owner))
        session.flush()
        assert session.scalar(select(Group.id).where(Group.user_id == owner)) is None
        assert (
            session.scalar(
                select(Membership.id).where(Membership.group_id.in_(group_ids))
            )
            is None
        )
        session.rollback()


@pytest.mark.parametrize("failure", ["sql", "commit"])
def test_move_sql_or_confirmed_commit_rejection_is_atomic(
    postgres_fixture, monkeypatch, failure
):
    engine, _ = postgres_fixture
    owner = 24
    source = default_id(engine, owner)
    target = create(engine, owner, failure)
    before = members(engine, source)
    with Session(engine) as session:
        if failure == "commit":

            def rejected():
                raise IntegrityError(
                    "COMMIT", {}, RuntimeError("confirmed constraint rejection")
                )

            monkeypatch.setattr(session, "commit", rejected)

        def break_insert(_connection, cursor, statement, _parameters, *_args):
            if statement.startswith("INSERT INTO app.wealth_watchlist_membership"):
                cursor.execute("SELECT 1 / 0")

        if failure == "sql":
            event.listen(engine, "before_cursor_execute", break_insert)
        try:
            with pytest.raises(WatchlistError) as error:
                WatchlistCommandService().batch(
                    session,
                    user_id=owner,
                    group_id=source,
                    action="MOVE",
                    membership_ids=[before[0][0]],
                    target_group_ids=[target],
                )
            assert error.value.code == "WL_WRITE_FAILED"
        finally:
            if failure == "sql":
                event.remove(engine, "before_cursor_execute", break_insert)
    assert members(engine, source) == before
    assert members(engine, target) == []
