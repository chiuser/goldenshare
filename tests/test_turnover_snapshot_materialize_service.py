from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.services.wealth.market.turnover.turnover_snapshot_materialize_service import TurnoverSnapshotMaterializeService
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import WealthMarketTurnoverSnapshot
from src.foundation.models.raw.raw_stk_mins import RawStkMins


def _build_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS raw_tushare")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        RawStkMins.__table__.create(connection, checkfirst=True)
        WealthMarketTurnoverSnapshot.__table__.create(connection, checkfirst=True)
    return Session(engine, future=True)


def test_materialize_trade_date_builds_ready_snapshot() -> None:
    session = _build_session()
    try:
        trade_date = date(2026, 5, 8)
        for ts_code, amount_base in (("000001.SZ", 1000.0), ("000002.SZ", 1200.0)):
            for minute in ("09:30:00", "10:00:00", "10:30:00", "15:00:00"):
                session.add(
                    RawStkMins(
                        ts_code=ts_code,
                        freq=30,
                        trade_time=datetime.fromisoformat(f"{trade_date.isoformat()} {minute}"),
                        open=10.0,
                        close=10.0,
                        high=10.0,
                        low=10.0,
                        vol=100,
                        amount=amount_base,
                    )
                )
        session.commit()

        results = TurnoverSnapshotMaterializeService().materialize_trade_date(
            session,
            trade_date=trade_date,
            freqs=[30],
        )
        session.commit()

        assert len(results) == 1
        assert results[0].build_status == "READY"
        snapshot = session.scalar(
            select(WealthMarketTurnoverSnapshot).where(
                WealthMarketTurnoverSnapshot.type == "stock",
                WealthMarketTurnoverSnapshot.market == "CN_A",
                WealthMarketTurnoverSnapshot.trade_date == trade_date,
                WealthMarketTurnoverSnapshot.freq == 30,
            )
        )
        assert snapshot is not None
        assert snapshot.security_count == 2
        assert snapshot.source_row_count == 8
        # Raw minute amount is yuan; wealth turnover snapshot stores thousand-yuan.
        assert snapshot.total_amount == Decimal("8.80")
        assert snapshot.total_vol == 800
        assert isinstance(snapshot.points_json, list)
        assert len(snapshot.points_json) == 4
        assert snapshot.points_json[0]["amount"] == 2.2
        assert snapshot.points_json[0]["vol"] == 200
    finally:
        session.close()


def test_materialize_trade_date_is_idempotent_for_same_slice() -> None:
    session = _build_session()
    try:
        trade_date = date(2026, 5, 8)
        session.add(
            RawStkMins(
                ts_code="000001.SZ",
                freq=30,
                trade_time=datetime.fromisoformat(f"{trade_date.isoformat()} 09:30:00"),
                open=10.0,
                close=10.0,
                high=10.0,
                low=10.0,
                vol=100,
                amount=1000.0,
            )
        )
        session.commit()

        service = TurnoverSnapshotMaterializeService()
        service.materialize_trade_date(session, trade_date=trade_date, freqs=[30])
        session.commit()
        service.materialize_trade_date(session, trade_date=trade_date, freqs=[30])
        session.commit()

        rows = session.execute(
            select(WealthMarketTurnoverSnapshot).where(
                WealthMarketTurnoverSnapshot.type == "stock",
                WealthMarketTurnoverSnapshot.market == "CN_A",
                WealthMarketTurnoverSnapshot.trade_date == trade_date,
                WealthMarketTurnoverSnapshot.freq == 30,
            )
        ).scalars().all()
        assert len(rows) == 1
    finally:
        session.close()
