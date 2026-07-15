from pathlib import Path

from orchestrator.defs.jobs.dc_daily_technical_repair import (
    GOLD_DC_DAILY_TECHNICAL_REPAIR_JOB_NAME,
    gold_dc_daily_technical_repair_job,
)
from orchestrator.defs.ops.dc_daily_technical_repair import (
    GOLD_DC_DAILY_TECHNICAL_REPAIR_CONFIG_SCHEMA,
)


def test_repair_job_is_op_based_and_has_complete_batch_config() -> None:
    assert gold_dc_daily_technical_repair_job.name == GOLD_DC_DAILY_TECHNICAL_REPAIR_JOB_NAME
    assert gold_dc_daily_technical_repair_job.name == "gold_dc_daily_technical_repair_job"
    assert len(gold_dc_daily_technical_repair_job.graph.node_defs) == 1
    assert "upstream_batch_id" in GOLD_DC_DAILY_TECHNICAL_REPAIR_CONFIG_SCHEMA
    assert "source_revision" in GOLD_DC_DAILY_TECHNICAL_REPAIR_CONFIG_SCHEMA
    assert "selected_partition_count" in GOLD_DC_DAILY_TECHNICAL_REPAIR_CONFIG_SCHEMA


def test_repair_job_does_not_select_assets_or_define_a_second_check() -> None:
    source = Path("src/orchestrator/defs/jobs/dc_daily_technical_repair.py").read_text()
    assert "define_asset_job" not in source
    assert "AssetSelection" not in source
    assert "gold_dc_daily_technical_core_check" not in source


def test_repair_op_event_source_is_partitioned_and_not_history_scanning() -> None:
    source = Path("src/orchestrator/defs/ops/dc_daily_technical_repair.py").read_text()
    assert "AssetMaterialization" in source
    assert "AssetCheckEvaluation" in source
    assert "partition=partition_result.trade_date" in source
    assert "get_event_records" not in source
    assert "report_runless_asset_event" not in source
