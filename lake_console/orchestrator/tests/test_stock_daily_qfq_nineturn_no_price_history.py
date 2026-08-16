from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_history import (
    DUCKDB_MEMORY_LIMIT,
    DUCKDB_THREADS,
    MAX_BATCH_SECONDS,
    MAX_RSS_BYTES,
    StockDailyQfqNineTurnNoPriceError,
    audit_stock_daily_qfq_nineturn_no_price_candidates,
    audit_stock_daily_qfq_nineturn_no_price_formal,
    build_stock_daily_qfq_nineturn_no_price_candidates,
    plan_stock_daily_qfq_nineturn_no_price_history,
    promote_stock_daily_qfq_nineturn_no_price_candidates,
)
from orchestrator.defs.resources import DuckDBResource


def test_plan_freezes_only_legacy_daily_files_without_qfq_price_identity(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    _write_legacy_partition(lake_root, "2026-08-11", close_qfq=10.0)
    _write_legacy_partition(lake_root, "2026-08-12", close_qfq=99.0)

    plan = plan_stock_daily_qfq_nineturn_no_price_history(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        writer_stopped=True,
        output_dir=tmp_path / "reports",
    )

    assert plan.should_stop is False
    assert [item.partition_key for item in plan.partitions] == [
        "2026-08-11",
        "2026-08-12",
    ]
    assert plan.report["row_count"] == 4
    assert plan.report["write_counters"] == {
        "candidate_files": 0,
        "formal_lake": 0,
        "dagster_events": 0,
        "prod_rows": 0,
    }
    serialized = json.dumps(plan.report, ensure_ascii=False)
    assert "gold_stock_daily_qfq" not in serialized
    assert "qfq_relative_path" not in serialized


def test_plan_fails_closed_when_writer_runs_or_scope_has_extra_parquet(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    target = _write_legacy_partition(lake_root, "2026-08-12", close_qfq=10.0)
    target.with_name("unexpected.parquet").write_bytes(target.read_bytes())

    plan = plan_stock_daily_qfq_nineturn_no_price_history(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        writer_stopped=False,
        output_dir=tmp_path / "reports",
    )

    assert plan.should_stop is True
    assert "writer_not_stopped" in plan.stop_reasons
    assert "unexpected_formal_file" in plan.stop_reasons


def test_plan_rejects_mixed_legacy_and_new_schema_files(tmp_path: Path) -> None:
    lake_root, staging_root = _roots(tmp_path)
    _write_legacy_partition(lake_root, "2026-08-11", close_qfq=10.0)
    _write_six_column_partition(lake_root, "2026-08-12")

    plan = plan_stock_daily_qfq_nineturn_no_price_history(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        writer_stopped=True,
        output_dir=tmp_path / "reports",
    )

    assert plan.should_stop is True
    assert "year=2026:legacy_contract_failed" in plan.stop_reasons
    assert plan.report["annual_audits"][0]["schema_mismatch_file_count"] == 1


def test_sample_projection_removes_price_and_preserves_business_fields(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    source = _write_legacy_partition(lake_root, "2026-08-12", close_qfq=12.5)
    source_preimage = source.read_bytes()
    plan = _plan(lake_root, staging_root, tmp_path)

    build = build_stock_daily_qfq_nineturn_no_price_candidates(
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        mode="sample",
        sample_partition_keys=("2026-08-12",),
        confirm_build=True,
    )
    audit = audit_stock_daily_qfq_nineturn_no_price_candidates(
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        mode="sample",
        sample_partition_keys=("2026-08-12",),
    )

    candidate = (
        plan.candidate_lake_root
        / "gold/indicator/stock_daily_qfq_nineturn"
        / "trade_date=2026-08-12/part-000.parquet"
    )
    with duckdb.connect() as connection:
        schema = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{candidate.as_posix()}', "
            "hive_partitioning=false)"
        ).fetchall()
        rows = connection.execute(
            f"SELECT * FROM read_parquet('{candidate.as_posix()}', "
            "hive_partitioning=false) ORDER BY ts_code"
        ).fetchall()
    assert [row[0] for row in schema] == [
        "ts_code",
        "trade_date",
        "up_count",
        "down_count",
        "nine_up_turn",
        "nine_down_turn",
    ]
    assert rows[0][2:] == (10, 0, "+9", None)
    assert build["formal_lake_write_count"] == 0
    assert audit["should_stop"] is False
    assert source.read_bytes() == source_preimage


def test_candidate_audit_rejects_business_value_drift(tmp_path: Path) -> None:
    lake_root, staging_root = _roots(tmp_path)
    _write_legacy_partition(lake_root, "2026-08-12", close_qfq=12.5)
    plan = _plan(lake_root, staging_root, tmp_path)
    build_stock_daily_qfq_nineturn_no_price_candidates(
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        mode="full",
        confirm_build=True,
    )
    candidate = (
        plan.candidate_lake_root
        / "gold/indicator/stock_daily_qfq_nineturn"
        / "trade_date=2026-08-12/part-000.parquet"
    )
    replacement = candidate.with_name("replacement.parquet")
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT ts_code, trade_date, up_count + 1 AS up_count, down_count,
                     nine_up_turn, nine_down_turn
              FROM read_parquet('{candidate.as_posix()}', hive_partitioning=false)
            ) TO '{replacement.as_posix()}' (FORMAT PARQUET)
            """
        )
    replacement.replace(candidate)

    report = audit_stock_daily_qfq_nineturn_no_price_candidates(
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        mode="full",
    )

    assert report["should_stop"] is True
    assert report["annual_audits"][0]["source_minus_candidate_count"] == 2
    assert report["annual_audits"][0]["candidate_minus_source_count"] == 2


def test_full_projection_promotes_atomically_and_passes_formal_audit(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    formal = _write_legacy_partition(lake_root, "2026-08-12", close_qfq=12.5)
    plan = _plan(lake_root, staging_root, tmp_path)
    build_stock_daily_qfq_nineturn_no_price_candidates(
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        mode="full",
        confirm_build=True,
    )
    candidate_audit = audit_stock_daily_qfq_nineturn_no_price_candidates(
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        mode="full",
    )

    promotion = promote_stock_daily_qfq_nineturn_no_price_candidates(
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        audit_report_path=Path(str(candidate_audit["report_path"])),
        writer_stopped=True,
        reader_stopped=True,
        confirm_promote=True,
    )
    formal_audit = audit_stock_daily_qfq_nineturn_no_price_formal(
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        candidate_audit_report_path=Path(str(candidate_audit["report_path"])),
        duckdb_resource=DuckDBResource(),
    )

    with duckdb.connect() as connection:
        columns = [
            row[0]
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{formal.as_posix()}', "
                "hive_partitioning=false)"
            ).fetchall()
        ]
    assert promotion["promoted_file_count"] == 1
    assert columns == [
        "ts_code",
        "trade_date",
        "up_count",
        "down_count",
        "nine_up_turn",
        "nine_down_turn",
    ]
    assert formal_audit["should_stop"] is False
    assert formal_audit["candidate_residual_count"] == 0


def test_projection_requires_reviewed_hash_and_explicit_confirmation(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    _write_legacy_partition(lake_root, "2026-08-12", close_qfq=12.5)
    plan = _plan(lake_root, staging_root, tmp_path)

    with pytest.raises(StockDailyQfqNineTurnNoPriceError, match="confirmation"):
        build_stock_daily_qfq_nineturn_no_price_candidates(
            plan=plan,
            expected_plan_hash=plan.plan_hash,
            duckdb_resource=DuckDBResource(),
            mode="full",
            confirm_build=False,
        )
    with pytest.raises(StockDailyQfqNineTurnNoPriceError, match="hash mismatch"):
        build_stock_daily_qfq_nineturn_no_price_candidates(
            plan=plan,
            expected_plan_hash="not-reviewed",
            duckdb_resource=DuckDBResource(),
            mode="full",
            confirm_build=True,
        )


def test_projection_resource_gates_are_frozen() -> None:
    assert DUCKDB_MEMORY_LIMIT == "2GB"
    assert DUCKDB_THREADS == 1
    assert MAX_BATCH_SECONDS == 300.0
    assert MAX_RSS_BYTES == 16 * 1024**3


def test_projection_tool_does_not_import_formula_or_qfq_price_source() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/orchestrator/defs/bootstrap/stock_daily_qfq_nineturn_no_price_history.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "build_nineturn_formula_select_sql",
        "build_gold_stock_daily_qfq_nineturn_select_sql",
        "gold_stock_daily_qfq_path",
        "qfq_source_path",
        "close_value",
    ):
        assert forbidden not in source


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    return lake_root, staging_root


def _plan(
    lake_root: Path,
    staging_root: Path,
    tmp_path: Path,
):
    plan = plan_stock_daily_qfq_nineturn_no_price_history(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        writer_stopped=True,
        output_dir=tmp_path / "reports",
    )
    assert plan.should_stop is False
    return plan


def _write_legacy_partition(
    lake_root: Path,
    partition_key: str,
    *,
    close_qfq: float,
) -> Path:
    path = (
        lake_root
        / "gold/indicator/stock_daily_qfq_nineturn"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES
                ('000001.SZ', DATE '{partition_key}', {close_qfq}::DOUBLE,
                 10::INTEGER, 0::INTEGER, '+9'::VARCHAR, NULL::VARCHAR),
                ('600000.SH', DATE '{partition_key}', 8.2::DOUBLE,
                 0::INTEGER, 4::INTEGER, NULL::VARCHAR, NULL::VARCHAR)
              ) AS rows(ts_code, trade_date, close_qfq, up_count, down_count,
                        nine_up_turn, nine_down_turn)
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )
    return path


def _write_six_column_partition(lake_root: Path, partition_key: str) -> Path:
    path = (
        lake_root
        / "gold/indicator/stock_daily_qfq_nineturn"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT '000001.SZ'::VARCHAR AS ts_code,
                DATE '{partition_key}' AS trade_date,
                1::INTEGER AS up_count,
                0::INTEGER AS down_count,
                NULL::VARCHAR AS nine_up_turn,
                NULL::VARCHAR AS nine_down_turn
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )
    return path
