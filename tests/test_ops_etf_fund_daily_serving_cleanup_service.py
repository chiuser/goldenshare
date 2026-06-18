from __future__ import annotations

import csv
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.ops.services.etf_fund_daily_serving_cleanup_service import EtfFundDailyServingCleanupService


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS raw_tushare")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        connection.exec_driver_sql(
            """
            CREATE TABLE core_serving.fund_daily_bar (
                ts_code TEXT NOT NULL,
                trade_date DATE NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE raw_tushare.fund_daily (
                ts_code TEXT NOT NULL,
                trade_date DATE NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE ops.etf_series_active (
                resource TEXT NOT NULL,
                ts_code TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE ops.task_run (
                resource_key TEXT,
                status TEXT
            )
            """
        )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _seed_common_rows(session: Session) -> None:
    session.execute(
        text("INSERT INTO ops.etf_series_active (resource, ts_code) VALUES (:resource, :ts_code)"),
        [{"resource": "fund_daily", "ts_code": "510300.SH"}],
    )
    session.execute(
        text("INSERT INTO raw_tushare.fund_daily (ts_code, trade_date) VALUES (:ts_code, :trade_date)"),
        [
            {"ts_code": "510300.SH", "trade_date": "2026-06-17"},
            {"ts_code": "999999.SH", "trade_date": "2026-06-17"},
            {"ts_code": "888888.SH", "trade_date": "2026-06-16"},
        ],
    )
    session.execute(
        text("INSERT INTO core_serving.fund_daily_bar (ts_code, trade_date) VALUES (:ts_code, :trade_date)"),
        [
            {"ts_code": "510300.SH", "trade_date": "2026-06-17"},
            {"ts_code": "999999.SH", "trade_date": "2026-06-16"},
            {"ts_code": "999999.SH", "trade_date": "2026-06-17"},
            {"ts_code": "888888.SH", "trade_date": "2026-06-16"},
        ],
    )
    session.commit()


def _write_confirm_report(path: Path, codes: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ts_code", "min_trade_date", "max_trade_date", "row_count"])
        writer.writeheader()
        for code in codes:
            writer.writerow(
                {
                    "ts_code": code,
                    "min_trade_date": "2026-06-16",
                    "max_trade_date": "2026-06-17",
                    "row_count": 1,
                }
            )


def _serving_codes(session: Session) -> list[str]:
    rows = session.execute(
        text("SELECT ts_code FROM core_serving.fund_daily_bar ORDER BY ts_code, trade_date")
    ).all()
    return [str(row[0]) for row in rows]


def _raw_row_count(session: Session) -> int:
    return int(session.scalar(text("SELECT COUNT(*) FROM raw_tushare.fund_daily")) or 0)


def test_cleanup_service_dry_run_reports_serving_rows_outside_active_pool(tmp_path: Path) -> None:
    session = _session()
    _seed_common_rows(session)
    output = tmp_path / "outside.csv"

    report = EtfFundDailyServingCleanupService().run(session, dry_run=True, output_path=output)

    assert report.dry_run is True
    assert report.outside_code_count == 2
    assert report.outside_row_count == 3
    assert report.deleted_count == 0
    assert report.raw_row_count_before == 3
    with output.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["ts_code"] for row in rows] == ["888888.SH", "999999.SH"]
    assert {row["ts_code"]: row["row_count"] for row in rows} == {"888888.SH": "1", "999999.SH": "2"}


def test_cleanup_service_apply_requires_confirm_report() -> None:
    session = _session()

    with pytest.raises(ValueError, match="--confirm-report is required"):
        EtfFundDailyServingCleanupService().run(session, dry_run=False, confirm_report_path=None)


def test_cleanup_service_apply_refuses_when_fund_daily_task_run_is_open(tmp_path: Path) -> None:
    session = _session()
    _seed_common_rows(session)
    confirm_report = tmp_path / "confirm.csv"
    _write_confirm_report(confirm_report, ["888888.SH", "999999.SH"])
    session.execute(
        text("INSERT INTO ops.task_run (resource_key, status) VALUES (:resource_key, :status)"),
        {"resource_key": "fund_daily", "status": "running"},
    )
    session.commit()

    with pytest.raises(RuntimeError, match="fund_daily task runs are still open"):
        EtfFundDailyServingCleanupService().run(session, dry_run=False, confirm_report_path=confirm_report)

    assert _serving_codes(session) == ["510300.SH", "888888.SH", "999999.SH", "999999.SH"]


def test_cleanup_service_apply_deletes_only_confirmed_rows_still_outside_active_pool(tmp_path: Path) -> None:
    session = _session()
    _seed_common_rows(session)
    confirm_report = tmp_path / "confirm.csv"
    _write_confirm_report(confirm_report, ["510300.SH", "888888.SH", "999999.SH"])
    raw_before = _raw_row_count(session)

    report = EtfFundDailyServingCleanupService().run(
        session,
        dry_run=False,
        confirm_report_path=confirm_report,
    )

    assert report.dry_run is False
    assert report.outside_code_count == 2
    assert report.outside_row_count == 3
    assert report.deleted_count == 3
    assert report.post_outside_row_count == 0
    assert report.raw_row_count_before == raw_before
    assert report.raw_row_count_after == raw_before
    assert _serving_codes(session) == ["510300.SH"]
    assert _raw_row_count(session) == raw_before
