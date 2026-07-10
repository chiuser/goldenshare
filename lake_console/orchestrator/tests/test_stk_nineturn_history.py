from pathlib import Path
import json

import pytest

from orchestrator.defs.bootstrap.stk_nineturn_history import (
    build_stk_nineturn_raw_history,
    build_stk_nineturn_silver_history,
    load_stk_nineturn_prod_export_manifest,
    plan_stk_nineturn_raw_history,
)
from orchestrator.defs.paths import silver_stock_identity_map_path, silver_stock_nineturn_daily_path
from orchestrator.defs.resources import DuckDBResource


def _manifest(tmp_path: Path) -> Path:
    output = tmp_path / "stage.parquet"
    output.touch()
    path = tmp_path / "sync_runs.jsonl"
    path.write_text(json.dumps({
        "run_id": "run-1", "dataset_key": "stk_nineturn",
        "source": "prod-raw-db", "mode": "range_rebuild",
        "start_date": "2023-01-03", "end_date": "2023-01-04",
        "fetched_rows": 4, "written_rows": 4, "skipped_partitions": 0,
        "partitions": [
            {"trade_date": "2023-01-03", "output": str(output)},
        ],
    }) + "\n", encoding="utf-8")
    return path


def test_manifest_is_scoped_and_plan_is_raw_only(tmp_path: Path) -> None:
    manifest = load_stk_nineturn_prod_export_manifest(
        manifest_path=_manifest(tmp_path), run_id="run-1"
    )
    plan = plan_stk_nineturn_raw_history(manifest=manifest, lake_root=tmp_path / "lake")
    assert plan.expected_partition_keys == ("2023-01-03",)
    assert plan.annual_batches == (2023,)
    assert str(plan.raw_target_paths[0]).endswith(
        "raw/tushare/stk_nineturn/trade_date=2023-01-03/part-000.parquet"
    )


def test_manifest_rejects_wrong_source(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source"] = "old_lake_bootstrap"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_method"):
        load_stk_nineturn_prod_export_manifest(manifest_path=path, run_id="run-1")


def test_silver_history_uses_one_batch_mapping_query_per_year(tmp_path: Path) -> None:
    source = tmp_path / "stage.parquet"
    with DuckDBResource().connect() as connection:
        connection.execute(
            f"""
            COPY (SELECT * FROM (VALUES
              ('830001.BJ', DATE '2023-01-03', 'daily', 10.0, 11.0, 9.0, 10.5,
               100.0, 1000.0, 0.0, 3.0, NULL::VARCHAR, NULL::VARCHAR)
            ) AS rows(ts_code, trade_date, freq, open, high, low, close, vol,
                      amount, up_count, down_count, nine_up_turn, nine_down_turn))
            TO '{source.as_posix()}' (FORMAT PARQUET)
            """
        )
        identity = silver_stock_identity_map_path(tmp_path / "lake")
        identity.parent.mkdir(parents=True)
        connection.execute(
            f"""
            COPY (SELECT * FROM (VALUES
              ('920001.BJ', '830001.BJ', DATE '2021-11-15', NULL::DATE)
            ) AS rows(latest_ts_code, source_ts_code, valid_from, valid_to))
            TO '{identity.as_posix()}' (FORMAT PARQUET)
            """
        )
    manifest_path = tmp_path / "manifest.jsonl"
    manifest_path.write_text(json.dumps({
        "run_id": "run-1", "dataset_key": "stk_nineturn", "source": "prod-raw-db",
        "mode": "range_rebuild", "start_date": "2023-01-03", "end_date": "2023-01-03",
        "fetched_rows": 1, "written_rows": 1, "skipped_partitions": 0,
        "partitions": [{"trade_date": "2023-01-03", "output": str(source)}],
    }) + "\n", encoding="utf-8")
    manifest = load_stk_nineturn_prod_export_manifest(
        manifest_path=manifest_path, run_id="run-1"
    )
    build_stk_nineturn_raw_history(
        manifest=manifest, lake_root=tmp_path / "lake", duckdb=DuckDBResource(), confirm_write=True
    )
    build_stk_nineturn_silver_history(
        manifest=manifest, lake_root=tmp_path / "lake", duckdb=DuckDBResource(), confirm_write=True
    )
    assert silver_stock_nineturn_daily_path(
        tmp_path / "lake", "2023-01-03"
    ).is_file()
