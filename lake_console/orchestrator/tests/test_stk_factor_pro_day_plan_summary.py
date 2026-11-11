"""Real day observation/plan producers; only forbidden file reads are trapped."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.assets import stk_factor_pro as asset
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from tests.test_stk_factor_pro_history_repair import setup_failed_history
from tests.test_stk_factor_pro_jobs import DAY, PREVIOUS, isolated_update_environment


@pytest.fixture
def published(tmp_path, monkeypatch):
    with isolated_update_environment(tmp_path, monkeypatch) as env:
        instance, _, _, lake, staging, _ = env
        _, source_id, plan, _ = setup_failed_history(tmp_path, monkeypatch, env)
        known_pg = {}
        facts = asset.readiness.read_stk_factor_pro_recorded_results(
            instance, target_trade_date=DAY, known_pg=known_pg
        )
        # This is the existing job boundary, including native bindings and actual
        # Raw/Silver file verification. Lower-level summary receives its results.
        baseline = asset.readiness.read_stk_factor_pro_day_factor_shas(
            instance,
            prior=facts,
            previous_trade_date=PREVIOUS,
            lake_root=lake,
            staging_root=staging,
            contract=plan.contract,
            known_pg=known_pg,
            known_records={},
        )
        assert plan.factor_t_ref.file_sha256 != plan.factor_p_ref.file_sha256
        assert baseline == (
            plan.factor_t_ref.file_sha256,
            plan.factor_p_ref.file_sha256,
        )
        values = known_pg[("phase_result", facts.day_result_ref.storage_id)]
        checks = known_pg[("day_publication_checks", source_id)]
        yield env, facts, plan, values, checks


def summary(published, *, values=None, checks=None, previous=PREVIOUS, known=None):
    env, _, plan, original_values, original_checks = published
    return asset.readiness.read_stk_factor_pro_day_plan_factor_shas(
        day_observation=original_values if values is None else values,
        publication_checks=original_checks if checks is None else checks,
        previous_trade_date=previous,
        staging_root=env[4],
        contract=plan.contract,
        known_records={} if known is None else known,
    )


def test_verified_day_summary_reads_one_plan_and_no_technical_factor_files(
    published, monkeypatch
):
    env, _, plan, _, _ = published
    lake = env[3]
    technical = {
        raw_stk_factor_pro_path(lake, str(DAY)),
        silver_stock_factor_pro_path(lake, str(DAY)),
    }
    opened = []
    original = Path.open

    def opened_path(path, *args, **kwargs):
        assert path not in technical, "summary read technical-factor Parquet"
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened_path)
    monkeypatch.setattr(
        asset.readiness,
        "factor_known_file_sha",
        lambda *a, **k: pytest.fail("summary hashes technical-factor files"),
    )
    known = {}
    expected = (plan.factor_t_ref.file_sha256, plan.factor_p_ref.file_sha256)
    assert summary(published, known=known) == expected
    assert summary(published, known=known) == expected
    assert len(opened) == 1 and opened[0].name == "history-plan.json"


@pytest.mark.parametrize(
    "bad", ["missing", "other_producer", "other_date", "P", "digest"]
)
def test_plan_reference_errors_do_not_fall_back_to_latest_history(published, bad):
    _, _, _, values, _ = published
    changed = dict(values)
    if bad == "missing":
        changed["history_plan_ref"] = None
    elif bad == "other_producer":
        changed["history_plan_ref"] = replace(
            values["history_plan_ref"], creator_run_id="repair-producer"
        )
    elif bad == "other_date":
        changed["target_trade_date"] = PREVIOUS
    elif bad == "digest":
        changed["history_plan_ref"] = replace(
            values["history_plan_ref"], file_sha256="0" * 64
        )
    with pytest.raises((ValueError, FileNotFoundError)):
        summary(published, values=changed, previous=DAY if bad == "P" else PREVIOUS)


def test_repair_observation_cannot_replace_the_verified_daily_plan(published):
    _, _, _, values, _ = published
    with pytest.raises(ValueError, match="本次日更的历史计划引用"):
        summary(published, values={**values, "producer_run_id": "repair-run"})


@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_plan_must_match_both_verified_publication_producers(published, layer):
    checks = dict(published[4])
    name = (
        asset.C.STK_FACTOR_PRO_RAW_ASSET_KEY
        if layer == "raw"
        else asset.C.STK_FACTOR_PRO_SILVER_ASSET_KEY
    )
    original = checks[name]
    target = original.target_materialization_data
    checks[name] = AssetCheckEvaluation(
        asset_key=original.asset_key,
        check_name=original.check_name,
        passed=True,
        blocking=True,
        partition=original.partition,
        metadata=original.metadata,
        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
            storage_id=target.storage_id,
            run_id="repair-producer",
            timestamp=target.timestamp,
        ),
    )
    with pytest.raises(ValueError, match="本次日更的历史计划引用"):
        summary(published, checks=checks)


@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_job_entry_still_checks_physical_raw_and_silver_before_summary(
    published, layer
):
    env, facts, plan, _, _ = published
    instance, _, _, lake, staging, _ = env
    target = (
        raw_stk_factor_pro_path(lake, str(DAY))
        if layer == "raw"
        else silver_stock_factor_pro_path(lake, str(DAY))
    )
    sha = asset.readiness.factor_known_file_sha

    def changed_file(path, **kwargs):
        return "0" * 64 if path == target else sha(path, **kwargs)

    with (
        patch.object(
            asset.readiness, "factor_known_file_sha", side_effect=changed_file
        ) as physical,
        patch.object(
            asset.readiness, "read_stk_factor_pro_day_plan_factor_shas"
        ) as light,
    ):
        assert (
            asset.readiness.read_stk_factor_pro_day_factor_shas(
                instance,
                prior=facts,
                previous_trade_date=PREVIOUS,
                lake_root=lake,
                staging_root=staging,
                contract=plan.contract,
                known_pg={},
                known_records={},
            )
            is None
        )
        assert physical.call_count == (1 if layer == "raw" else 2)
        light.assert_not_called()
