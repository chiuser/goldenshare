from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.dao.etf_basic_dao import EtfBasicDAO, EtfRequestTarget
from src.foundation.models.core.etf_basic import EtfBasic


AS_OF_DATE = date(2026, 8, 28)


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def register_sqlite_now(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        dbapi_connection.create_function(
            "now",
            0,
            lambda: datetime.now().isoformat(sep=" "),
        )

    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        EtfBasic.__table__.create(connection)

    session = Session(engine, future=True)
    session.add_all(
        [
            _row("510300.SH", exchange="SH", list_date=date(2012, 5, 28)),
            _row("159915.SZ", exchange="SZ", list_date=AS_OF_DATE),
            _row("510500.SH", exchange="SH", list_status="P"),
            _row("159901.SZ", exchange="SZ", list_status="D"),
            _row("510880.SH", exchange="SH", list_date=None),
            _row("159999.SZ", exchange="SZ", list_date=date(2026, 8, 29)),
            # 非交易所后缀优先于状态判断。
            _row("100000.OF", exchange="OF", list_status="D"),
            # 后缀与 exchange 不一致优先于状态判断。
            _row("510001.SH", exchange="SZ", list_status="P"),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _row(
    ts_code: str,
    *,
    exchange: str,
    list_status: str = "L",
    list_date: date | None = date(2020, 1, 1),
) -> EtfBasic:
    return EtfBasic(
        ts_code=ts_code,
        csname=f"{ts_code} 简称",
        extname=f"{ts_code} 扩位简称",
        cname=f"{ts_code} 全称",
        list_date=list_date,
        list_status=list_status,
        exchange=exchange,
        etf_type="境内",
    )


def test_snapshot_uses_one_serving_query_and_reconciles_exclusions(
    db_session: Session,
) -> None:
    select_count = 0

    def count_selects(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:  # type: ignore[no-untyped-def]
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(db_session.bind, "before_cursor_execute", count_selects)
    try:
        snapshot = EtfBasicDAO(db_session).load_requestability_snapshot(
            as_of_date=AS_OF_DATE
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_selects)

    assert select_count == 1
    assert snapshot.serving_row_count == 8
    assert snapshot.requestable_count == 2
    assert [target.ts_code for target in snapshot.targets] == [
        "159915.SZ",
        "510300.SH",
    ]
    assert dict(snapshot.excluded_reason_counts) == {
        "EXCHANGE_MISMATCH": 1,
        "LIST_DATE_AFTER_AS_OF": 1,
        "LIST_DATE_NULL": 1,
        "NON_EXCHANGE_SUFFIX": 1,
        "STATUS_NOT_LISTED": 2,
    }
    assert snapshot.serving_row_count == (
        snapshot.requestable_count + sum(snapshot.excluded_reason_counts.values())
    )


@pytest.mark.parametrize(
    ("exchange", "serving_count", "target_codes", "excluded_counts"),
    [
        (
            "SH",
            4,
            ["510300.SH"],
            {
                "EXCHANGE_MISMATCH": 1,
                "LIST_DATE_NULL": 1,
                "STATUS_NOT_LISTED": 1,
            },
        ),
        (
            "SZ",
            3,
            ["159915.SZ"],
            {"LIST_DATE_AFTER_AS_OF": 1, "STATUS_NOT_LISTED": 1},
        ),
    ],
)
def test_snapshot_exchange_scope_is_suffix_scoped(
    db_session: Session,
    exchange: str,
    serving_count: int,
    target_codes: list[str],
    excluded_counts: dict[str, int],
) -> None:
    snapshot = EtfBasicDAO(db_session).load_requestability_snapshot(
        as_of_date=AS_OF_DATE,
        exchange=exchange,  # type: ignore[arg-type]
    )

    assert snapshot.serving_row_count == serving_count
    assert [target.ts_code for target in snapshot.targets] == target_codes
    assert dict(snapshot.excluded_reason_counts) == excluded_counts
    assert snapshot.serving_row_count == (
        snapshot.requestable_count + sum(snapshot.excluded_reason_counts.values())
    )


def test_snapshot_contract_is_immutable(db_session: Session) -> None:
    snapshot = EtfBasicDAO(db_session).load_requestability_snapshot(
        as_of_date=AS_OF_DATE
    )

    with pytest.raises(FrozenInstanceError):
        snapshot.requestable_count = 0  # type: ignore[misc]
    with pytest.raises(TypeError):
        snapshot.excluded_reason_counts["OTHER"] = 1  # type: ignore[index]


def test_get_requestable_target_normalizes_code_and_exchange(
    db_session: Session,
) -> None:
    dao = EtfBasicDAO(db_session)

    target = dao.get_requestable_target(
        ts_code=" 510300.sh ",
        as_of_date=AS_OF_DATE,
        exchange=" sh ",  # type: ignore[arg-type]
    )

    assert target == EtfRequestTarget(
        ts_code="510300.SH",
        list_date=date(2012, 5, 28),
        exchange="SH",
    )
    assert (
        dao.get_requestable_target(
            ts_code="510300.SH",
            as_of_date=AS_OF_DATE,
            exchange="SZ",
        )
        is None
    )
    assert (
        dao.get_requestable_target(
            ts_code="100000.OF",
            as_of_date=AS_OF_DATE,
        )
        is None
    )
    assert dao.get_requestable_target(ts_code=" ", as_of_date=AS_OF_DATE) is None


@pytest.mark.parametrize(
    "ts_code",
    ["510500.SH", "159901.SZ", "510880.SH", "159999.SZ", "510001.SH"],
)
def test_get_requestable_target_rejects_ineligible_rows(
    db_session: Session,
    ts_code: str,
) -> None:
    assert (
        EtfBasicDAO(db_session).get_requestable_target(
            ts_code=ts_code,
            as_of_date=AS_OF_DATE,
        )
        is None
    )


@pytest.mark.parametrize(
    "method_name,kwargs",
    [
        ("load_requestability_snapshot", {}),
        ("get_requestable_target", {"ts_code": "510300.SH"}),
        ("requestable_targets_subquery", {}),
    ],
)
def test_public_selectors_reject_invalid_exchange(
    db_session: Session,
    method_name: str,
    kwargs: dict[str, str],
) -> None:
    method = getattr(EtfBasicDAO(db_session), method_name)

    with pytest.raises(ValueError, match="exchange 只支持 SH 或 SZ"):
        method(as_of_date=AS_OF_DATE, exchange="BJ", **kwargs)


def test_requestable_subquery_columns_and_rows_match_snapshot(
    db_session: Session,
) -> None:
    dao = EtfBasicDAO(db_session)
    snapshot = dao.load_requestability_snapshot(as_of_date=AS_OF_DATE)
    targets = dao.requestable_targets_subquery(as_of_date=AS_OF_DATE)

    assert list(targets.c.keys()) == [
        "ts_code",
        "list_date",
        "exchange",
        "csname",
        "extname",
        "cname",
        "etf_type",
        "list_status",
    ]
    rows = db_session.execute(select(targets).order_by(targets.c.ts_code)).mappings()
    assert [row["ts_code"] for row in rows] == [
        target.ts_code for target in snapshot.targets
    ]


def test_removed_ambiguous_selectors_are_not_exposed(db_session: Session) -> None:
    dao = EtfBasicDAO(db_session)

    assert not hasattr(dao, "get_active_etfs")
    assert not hasattr(dao, "get_fund_daily_candidates")
