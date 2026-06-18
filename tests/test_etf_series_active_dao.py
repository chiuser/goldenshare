from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.dao.etf_series_active_dao import EtfSeriesActiveDAO
from src.foundation.dao.factory import DAOFactory
from src.ops.etf_series_active_store_adapter import OpsEtfSeriesActiveStore
from src.ops.models.ops.etf_series_active import EtfSeriesActive


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        EtfSeriesActive.__table__.create(connection)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_etf_series_active_dao_lists_codes_ordered() -> None:
    session = _session()
    dao = EtfSeriesActiveDAO(session)

    dao.upsert_seen_codes(
        "fund_daily",
        {"510300.SH": date(2026, 6, 17), "159915.SZ": date(2026, 6, 17)},
        checked_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
    )
    session.commit()

    assert dao.list_active_codes("fund_daily") == ["159915.SZ", "510300.SH"]


def test_etf_series_active_dao_upsert_preserves_resource_isolation_and_seen_bounds() -> None:
    session = _session()
    dao = EtfSeriesActiveDAO(session)

    dao.upsert_seen_codes(
        "fund_daily",
        {"510300.SH": date(2026, 6, 17)},
        checked_at=datetime(2026, 6, 18, 1, tzinfo=timezone.utc),
    )
    dao.upsert_seen_codes(
        "fund_daily",
        {"510300.SH": date(2026, 6, 16)},
        checked_at=datetime(2026, 6, 18, 2, tzinfo=timezone.utc),
    )
    dao.upsert_seen_codes(
        "etf_rt_daily",
        {"510300.SH": date(2026, 6, 17)},
        checked_at=datetime(2026, 6, 18, 3, tzinfo=timezone.utc),
    )
    session.commit()

    fund_daily = session.get(EtfSeriesActive, ("fund_daily", "510300.SH"))
    etf_rt_daily = session.get(EtfSeriesActive, ("etf_rt_daily", "510300.SH"))
    assert fund_daily is not None
    assert etf_rt_daily is not None
    assert fund_daily.first_seen_date == date(2026, 6, 16)
    assert fund_daily.last_seen_date == date(2026, 6, 17)
    assert dao.list_active_codes("fund_daily") == ["510300.SH"]
    assert dao.list_active_codes("etf_rt_daily") == ["510300.SH"]


def test_dao_factory_exposes_etf_series_active_dao() -> None:
    session = _session()

    factory = DAOFactory(session)

    assert isinstance(factory.etf_series_active, EtfSeriesActiveDAO)


def test_ops_adapter_lists_codes_ordered() -> None:
    session = _session()
    checked_at = datetime(2026, 6, 18, tzinfo=timezone.utc)
    session.add_all(
        [
            EtfSeriesActive(
                resource="fund_daily",
                ts_code="510300.SH",
                first_seen_date=date(2026, 6, 17),
                last_seen_date=date(2026, 6, 17),
                last_checked_at=checked_at,
            ),
            EtfSeriesActive(
                resource="fund_daily",
                ts_code="159915.SZ",
                first_seen_date=date(2026, 6, 17),
                last_seen_date=date(2026, 6, 17),
                last_checked_at=checked_at,
            ),
        ]
    )
    session.commit()

    assert OpsEtfSeriesActiveStore(session).list_active_codes("fund_daily") == ["159915.SZ", "510300.SH"]
