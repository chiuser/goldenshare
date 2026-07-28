from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap import index_global_bootstrap_cli
from orchestrator.defs.bootstrap.index_global_bootstrap_plan import (
    IndexGlobalBootstrapPlanError,
    build_date_plan,
    run_dry_run,
)
from orchestrator.defs.paths import raw_index_global_path, silver_index_global_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
)


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


def _write_empty(path: Path, schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ", ".join(
        f'CAST(NULL AS {column.type}) AS "{column.name}"' for column in schema
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT {columns} WHERE false) TO ? (FORMAT PARQUET)",
            [str(path)],
        )


def _write_broken(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT 1 AS wrong_column) TO ? (FORMAT PARQUET)",
            [str(path)],
        )


def test_date_plan_uses_every_natural_date_and_fingerprint() -> None:
    plan = build_date_plan(start_date="2022-01-01", end_date="2022-01-04")
    assert plan.expected_natural_dates == (
        "2022-01-01",
        "2022-01-02",
        "2022-01-03",
        "2022-01-04",
    )
    assert len(plan.fingerprint) == 64


def test_date_plan_rejects_before_start_and_future() -> None:
    with pytest.raises(IndexGlobalBootstrapPlanError, match="cannot precede"):
        build_date_plan(start_date="2021-12-31", end_date="2022-01-04")
    with pytest.raises(IndexGlobalBootstrapPlanError, match="future"):
        build_date_plan(start_date="2022-01-01", end_date="2999-01-01")


def test_dry_run_allows_missing_and_valid_empty_targets(tmp_path: Path) -> None:
    _write_empty(raw_index_global_path(tmp_path, "2022-01-01"), RAW_INDEX_GLOBAL_SCHEMA)
    _write_empty(silver_index_global_path(tmp_path, "2022-01-01"), SILVER_INDEX_GLOBAL_SCHEMA)

    report = run_dry_run(
        lake_root=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        start_date="2022-01-01",
        end_date="2022-01-02",
    )

    assert report.should_stop is False
    assert report.estimated_source_request_count == 10
    assert report.target_audits[0].valid_existing_count == 1
    assert report.target_audits[0].missing_count == 1
    assert report.target_audits[1].valid_existing_count == 1
    assert report.source_probe == "not_requested"


def test_dry_run_stops_on_invalid_existing_target(tmp_path: Path) -> None:
    _write_broken(raw_index_global_path(tmp_path, "2022-01-01"))
    _write_empty(silver_index_global_path(tmp_path, "2022-01-01"), SILVER_INDEX_GLOBAL_SCHEMA)

    report = run_dry_run(
        lake_root=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        start_date="2022-01-01",
        end_date="2022-01-01",
    )

    assert report.should_stop is True
    assert report.stop_reason_codes == ("raw_invalid_existing_target",)
    assert report.target_audits[0].invalid_existing_count == 1
    assert report.target_files[0].reason_code == "schema_mismatch"


def test_cli_has_dry_run_only_and_planner_has_no_event_or_apply_path() -> None:
    with pytest.raises(SystemExit):
        index_global_bootstrap_cli._parser().parse_args(["apply"])
    source = Path(index_global_bootstrap_cli.__file__).with_name(
        "index_global_bootstrap_plan.py"
    ).read_text(encoding="utf-8")
    assert "report_runless_asset_event" not in source
    assert "os.replace" not in source
    assert "get_event_records" not in source
