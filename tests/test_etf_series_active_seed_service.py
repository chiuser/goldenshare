from __future__ import annotations

import csv
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.ops.models.ops.etf_series_active import EtfSeriesActive
from src.ops.services.etf_series_active_seed_service import (
    ETF_SERIES_ACTIVE_SEED_EXPECTED_ROWS,
    EtfSeriesActiveSeedService,
)


SEED_PATH = Path("reports/etf_series_active_seed_1395_20260617.csv")


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


def _row_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(EtfSeriesActive)) or 0


def _write_seed_csv(tmp_path: Path, *, override: dict[int, dict[str, str]] | None = None) -> Path:
    output = tmp_path / "etf_seed.csv"
    overrides = override or {}
    fieldnames = ["ts_code", "selection_group", "latest_matched_trade_date"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index in range(ETF_SERIES_ACTIVE_SEED_EXPECTED_ROWS):
            row = {
                "ts_code": f"51{index:04d}.SH",
                "selection_group": "complete_1364",
                "latest_matched_trade_date": "2026-06-17",
            }
            row.update(overrides.get(index, {}))
            writer.writerow(row)
    return output


def test_etf_series_active_seed_dry_run_does_not_write() -> None:
    session = _session()

    report = EtfSeriesActiveSeedService().run(
        session,
        resource="fund_daily",
        seed_csv_path=SEED_PATH,
        dry_run=True,
    )

    assert report.dry_run is True
    assert report.resource == "fund_daily"
    assert report.candidate_count == 1395
    assert report.created_count == 1395
    assert report.skipped_count == 0
    assert _row_count(session) == 0


def test_etf_series_active_seed_apply_creates_single_resource() -> None:
    session = _session()

    report = EtfSeriesActiveSeedService().run(
        session,
        resource="fund_daily",
        seed_csv_path=SEED_PATH,
        dry_run=False,
    )

    assert report.created_count == 1395
    assert report.skipped_count == 0
    assert _row_count(session) == 1395
    sample = session.get(EtfSeriesActive, ("fund_daily", "510050.SH"))
    assert sample is not None
    assert sample.first_seen_date.isoformat() == "2026-06-17"
    assert sample.last_seen_date.isoformat() == "2026-06-17"


def test_etf_series_active_seed_can_create_two_resources_independently() -> None:
    session = _session()
    service = EtfSeriesActiveSeedService()

    service.run(session, resource="fund_daily", seed_csv_path=SEED_PATH, dry_run=False)
    service.run(session, resource="etf_rt_daily", seed_csv_path=SEED_PATH, dry_run=False)

    assert _row_count(session) == 2790


def test_etf_series_active_seed_repeated_apply_skips_existing_rows() -> None:
    session = _session()
    service = EtfSeriesActiveSeedService()

    service.run(session, resource="fund_daily", seed_csv_path=SEED_PATH, dry_run=False)
    report = service.run(session, resource="fund_daily", seed_csv_path=SEED_PATH, dry_run=False)

    assert report.created_count == 0
    assert report.skipped_count == 1395
    assert _row_count(session) == 1395


def test_etf_series_active_seed_rejects_unsupported_resource() -> None:
    session = _session()

    with pytest.raises(ValueError, match="unsupported ETF active resource"):
        EtfSeriesActiveSeedService().run(
            session,
            resource="bad_resource",
            seed_csv_path=SEED_PATH,
            dry_run=True,
        )


def test_etf_series_active_seed_rejects_of_code(tmp_path: Path) -> None:
    session = _session()
    seed_path = _write_seed_csv(tmp_path, override={0: {"ts_code": "510300.OF"}})

    with pytest.raises(ValueError, match=".OF code is not allowed"):
        EtfSeriesActiveSeedService().run(session, resource="fund_daily", seed_csv_path=seed_path)


def test_etf_series_active_seed_rejects_non_exchange_suffix(tmp_path: Path) -> None:
    session = _session()
    seed_path = _write_seed_csv(tmp_path, override={0: {"ts_code": "510300.BJ"}})

    with pytest.raises(ValueError, match="unsupported ts_code suffix"):
        EtfSeriesActiveSeedService().run(session, resource="fund_daily", seed_csv_path=seed_path)


def test_etf_series_active_seed_rejects_missing_latest_matched_trade_date(tmp_path: Path) -> None:
    session = _session()
    seed_path = _write_seed_csv(tmp_path, override={0: {"latest_matched_trade_date": ""}})

    with pytest.raises(ValueError, match="latest_matched_trade_date is required"):
        EtfSeriesActiveSeedService().run(session, resource="fund_daily", seed_csv_path=seed_path)
