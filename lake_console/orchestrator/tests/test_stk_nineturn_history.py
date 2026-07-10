from pathlib import Path
import json

import pytest

from orchestrator.defs.bootstrap.stk_nineturn_history import (
    load_stk_nineturn_prod_export_manifest,
    plan_stk_nineturn_raw_history,
)


def _manifest(tmp_path: Path) -> Path:
    output = tmp_path / "stage.parquet"
    output.touch()
    path = tmp_path / "sync_runs.jsonl"
    path.write_text(json.dumps({
        "run_id": "run-1", "dataset_key": "stk_nineturn",
        "source": "prod_db_readonly", "mode": "range_rebuild",
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
