"""Publish THS stock Silver from the actual same-date Raw without event gates."""

from functools import partial

from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_file,
    audit_daily_moneyflow_standardization,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
    moneyflow_writer_lock,
)
from orchestrator.defs.io.moneyflow_daily_silver_update_candidate import (
    build_daily_moneyflow_silver_update_candidate,
)
from orchestrator.defs.io.moneyflow_update_publication import (
    assert_moneyflow_update_path,
    assert_moneyflow_update_roots,
    publish_moneyflow_update_file,
)
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.defs.run_contracts.moneyflow import assert_moneyflow_memory_budget


def update_moneyflow_ths_silver(
    *, lake_root, staging_root, operation_id, trade_date, check_cancel=lambda: None
):
    dataset = "moneyflow_ths"
    directory = moneyflow_candidate_directory(
        staging_root, operation_id, trade_date, dataset=dataset
    )
    assert_moneyflow_update_roots(lake_root, staging_root)
    namespace = staging_root / "moneyflow"
    namespace.mkdir(exist_ok=True)
    with moneyflow_writer_lock(namespace):
        check_cancel()
        raw = raw_moneyflow_path(lake_root, dataset, trade_date)
        assert_moneyflow_update_path(raw)
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / "silver.parquet"
        target = silver_moneyflow_path(lake_root, dataset, trade_date)
        assert_moneyflow_update_path(candidate)
        assert_moneyflow_update_path(target)
        checkpoint = directory / "promotion-silver.json"
        with moneyflow_candidate_connection(directory) as connection:
            count = build_daily_moneyflow_silver_update_candidate(
                connection, raw=raw, candidate=candidate, trade_date=trade_date,
                dataset=dataset, checkpoint=checkpoint,
            )
            raw_hash = candidate_file_hash(raw)
            assert_moneyflow_memory_budget()
            state = publish_moneyflow_update_file(
                connection, candidate, target, dataset=dataset,
                audit_file=partial(audit_daily_moneyflow_file, dataset=dataset),
                day=trade_date, layer="silver", raw_hash=raw_hash,
                checkpoint=checkpoint, check_cancel=check_cancel,
            )
            audit_daily_moneyflow_standardization(
                connection, raw, target, trade_date, dataset=dataset
            )
        return {
            "target": str(target), "row_count": count, "raw_sha256": raw_hash,
            "file_sha256": state["published_sha256"], "promotion_mode": state["mode"],
        }
