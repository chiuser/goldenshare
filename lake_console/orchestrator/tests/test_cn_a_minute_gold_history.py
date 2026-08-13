from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap.cn_a_minute_gold_history import (
    CnAMinuteGoldHistoryError,
    audit_cn_a_minute_gold_history_candidates,
    audit_cn_a_minute_gold_history_formal,
    audit_major_index_gold_silver_equivalence,
    build_cn_a_minute_gold_history_candidates,
    build_cn_a_minute_gold_history_plan,
    promote_cn_a_minute_gold_history,
)
from orchestrator.defs.bootstrap.cn_a_minute_gold_history_cli import main
from orchestrator.defs.paths import (
    gold_index_mins_path,
    gold_major_index_mins_path,
    silver_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins import (
    effective_silver_codes_for_date,
)

TRADE_DATE = "2025-01-02"
TS_CODE = "000001.SH"


def _clock_range(start: str, end: str, minutes: int) -> tuple[str, ...]:
    current = datetime.fromisoformat(f"{TRADE_DATE} {start}")
    final = datetime.fromisoformat(f"{TRADE_DATE} {end}")
    values: list[str] = []
    while current <= final:
        values.append(current.strftime("%H:%M:%S"))
        current += timedelta(minutes=minutes)
    return tuple(values)


def _source_times(freq: int) -> tuple[str, ...]:
    if freq == 1:
        return (
            "09:30:00",
            *_clock_range("09:31:00", "11:30:00", 1),
            *_clock_range("13:01:00", "15:00:00", 1),
        )
    if freq == 5:
        return (
            "09:30:00",
            *_clock_range("09:35:00", "11:30:00", 5),
            *_clock_range("13:05:00", "15:00:00", 5),
        )
    if freq == 30:
        return (
            "09:30:00",
            "10:00:00",
            "10:30:00",
            "11:00:00",
            "11:30:00",
            "13:30:00",
            "14:00:00",
            "14:30:00",
            "15:00:00",
        )
    if freq == 60:
        return ("09:30:00", "10:30:00", "11:30:00", "14:00:00", "15:00:00")
    raise AssertionError(freq)


def _write_silver_sources(root: Path) -> None:
    connection = duckdb.connect(":memory:")
    try:
        for freq in (1, 5, 30, 60):
            path = silver_index_mins_path(root, f"{freq}min", TRADE_DATE)
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                (
                    TS_CODE,
                    f"{freq}min",
                    datetime.fromisoformat(f"{TRADE_DATE} {clock}"),
                    10.0 + index,
                    10.1 + index,
                    10.2 + index,
                    9.9 + index,
                    100.0 + index,
                    1000.0 + index,
                    "XSHG",
                    10.05 + index,
                    datetime.fromisoformat(TRADE_DATE).date(),
                )
                for index, clock in enumerate(_source_times(freq))
            ]
            connection.execute(
                """
                CREATE OR REPLACE TABLE source (
                  ts_code VARCHAR,
                  freq VARCHAR,
                  trade_time TIMESTAMP,
                  open DOUBLE,
                  close DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  vol DOUBLE,
                  amount DOUBLE,
                  exchange VARCHAR,
                  vwap DOUBLE,
                  trade_date DATE
                )
                """
            )
            connection.executemany(
                "INSERT INTO source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def _write_major_silver_sources(root: Path) -> None:
    connection = duckdb.connect(":memory:")
    try:
        for freq in (1, 5, 30, 60):
            path = silver_major_index_mins_path(
                root, f"{freq}min", TRADE_DATE
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = []
            for code_index, code in enumerate(
                effective_silver_codes_for_date(TRADE_DATE)
            ):
                rows.extend(
                    (
                        code,
                        f"{freq}min",
                        datetime.fromisoformat(f"{TRADE_DATE} {clock}"),
                        10.0 + code_index + index,
                        10.1 + code_index + index,
                        10.2 + code_index + index,
                        9.9 + code_index + index,
                        100.0 + index,
                        1000.0 + index,
                        "XSHG",
                        10.05 + code_index + index,
                    )
                    for index, clock in enumerate(_source_times(freq))
                )
            connection.execute(
                """
                CREATE OR REPLACE TABLE source (
                  ts_code VARCHAR,
                  freq VARCHAR,
                  trade_time TIMESTAMP,
                  open DOUBLE,
                  close DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  vol DOUBLE,
                  amount DOUBLE,
                  exchange VARCHAR,
                  vwap DOUBLE
                )
                """
            )
            connection.executemany(
                "INSERT INTO source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def _payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_candidate_first_bootstrap_promotes_one_complete_dataset_directory() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        lake_root = root / "lake"
        staging_root = root / "missing-staging-root"
        report_root = root / "reports"
        lake_root.mkdir()
        _write_silver_sources(lake_root)

        plan_path = build_cn_a_minute_gold_history_plan(
            dataset="index_mins",
            formal_lake_root=lake_root,
            staging_root=staging_root,
            report_root=report_root,
        )
        plan = _payload(plan_path)
        assert staging_root.is_dir()
        candidate_path = build_cn_a_minute_gold_history_candidates(
            plan_report_path=plan_path,
            expected_plan_hash=str(plan["plan_hash"]),
            duckdb_resource=DuckDBResource(),
            apply=True,
        )
        assert not gold_index_mins_path(lake_root, 1, TRADE_DATE).exists()

        audit_path = audit_cn_a_minute_gold_history_candidates(
            plan_report_path=plan_path,
            candidate_report_path=candidate_path,
            expected_plan_hash=str(plan["plan_hash"]),
            duckdb_resource=DuckDBResource(),
        )
        assert _payload(audit_path)["ready"] is True

        promote_path = promote_cn_a_minute_gold_history(
            plan_report_path=plan_path,
            candidate_report_path=candidate_path,
            audit_report_path=audit_path,
            expected_plan_hash=str(plan["plan_hash"]),
            duckdb_resource=DuckDBResource(),
            apply=True,
        )
        assert _payload(promote_path)["promoted_file_count"] == 7
        formal_audit_path = audit_cn_a_minute_gold_history_formal(
            plan_report_path=plan_path,
            candidate_report_path=candidate_path,
            audit_report_path=audit_path,
            expected_plan_hash=str(plan["plan_hash"]),
            duckdb_resource=DuckDBResource(),
        )
        assert _payload(formal_audit_path)["ready"] is True
        assert all(
            gold_index_mins_path(lake_root, freq, TRADE_DATE).is_file()
            for freq in (1, 5, 15, 30, 60, 90, 120)
        )
        connection = duckdb.connect(":memory:")
        try:
            first_times = {
                freq: connection.execute(
                    "SELECT min(strftime(trade_time, '%H:%M:%S')) FROM read_parquet(?)",
                    [str(gold_index_mins_path(lake_root, freq, TRADE_DATE))],
                ).fetchone()[0]
                for freq in (1, 5, 15, 30, 60, 90, 120)
            }
        finally:
            connection.close()
        assert first_times == {
            1: "09:30:00",
            5: "09:35:00",
            15: "09:45:00",
            30: "10:00:00",
            60: "10:30:00",
            90: "11:00:00",
            120: "11:30:00",
        }


def test_plan_refuses_an_existing_formal_gold_dataset() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        lake_root = root / "lake"
        staging_root = root / "staging"
        report_root = root / "reports"
        lake_root.mkdir()
        staging_root.mkdir()
        _write_silver_sources(lake_root)
        target = gold_index_mins_path(lake_root, 1, TRADE_DATE)
        target.parent.mkdir(parents=True)
        target.touch()

        with pytest.raises(CnAMinuteGoldHistoryError, match="already exists"):
            build_cn_a_minute_gold_history_plan(
                dataset="index_mins",
                formal_lake_root=lake_root,
                staging_root=staging_root,
                report_root=report_root,
            )


def test_major_unchanged_frequencies_are_compared_in_bounded_year_groups() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        lake_root = root / "lake"
        staging_root = root / "staging"
        report_root = root / "reports"
        lake_root.mkdir()
        _write_major_silver_sources(lake_root)
        plan_path = build_cn_a_minute_gold_history_plan(
            dataset="major_index_mins",
            formal_lake_root=lake_root,
            staging_root=staging_root,
            report_root=report_root,
        )
        plan = _payload(plan_path)
        candidate_path = build_cn_a_minute_gold_history_candidates(
            plan_report_path=plan_path,
            expected_plan_hash=str(plan["plan_hash"]),
            apply=True,
        )
        audit_path = audit_cn_a_minute_gold_history_candidates(
            plan_report_path=plan_path,
            candidate_report_path=candidate_path,
            expected_plan_hash=str(plan["plan_hash"]),
        )
        promote_cn_a_minute_gold_history(
            plan_report_path=plan_path,
            candidate_report_path=candidate_path,
            audit_report_path=audit_path,
            expected_plan_hash=str(plan["plan_hash"]),
            apply=True,
        )
        for freq in (90, 120):
            silver = silver_major_index_mins_path(
                lake_root, f"{freq}min", TRADE_DATE
            )
            silver.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(
                gold_major_index_mins_path(lake_root, freq, TRADE_DATE),
                silver,
            )

        equivalence = audit_major_index_gold_silver_equivalence(
            plan_report_path=plan_path,
            expected_plan_hash=str(plan["plan_hash"]),
        )
        payload = _payload(equivalence)
        assert payload["ready"] is True
        assert payload["frequencies"] == [1, 90, 120]
        assert len(payload["audits"]) == 3


def test_cli_requires_explicit_write_confirmations() -> None:
    assert (
        main(
            [
                "build-candidates",
                "--plan-report",
                "/tmp/missing.json",
                "--expected-plan-hash",
                "hash",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "promote",
                "--plan-report",
                "/tmp/missing.json",
                "--candidate-report",
                "/tmp/missing-candidate.json",
                "--audit-report",
                "/tmp/missing-audit.json",
                "--expected-plan-hash",
                "hash",
            ]
        )
        == 2
    )
