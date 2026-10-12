"""Frozen candidate proofs and native isolated event storage, with write traps."""

import json
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.bootstrap.moneyflow_history_cohort import _large_json
from orchestrator.defs.bootstrap.moneyflow_ind_dc_event_preview import (
    board_moneyflow_dc_history_proof,
    preview_board_moneyflow_dc_history,
)
from orchestrator.defs.paths import raw_moneyflow_path
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

from .test_moneyflow_history_promote import (
    DAY,
    hashes,
    isolated_space,  # noqa: F401 - pytest fixture
    operation,
    run,
    setup,
)


def prepare(tmp_path):
    from .test_moneyflow_history_promote import DATASETS, Source

    rows = {d: [Source.row(d)] for d in DATASETS}
    rows["moneyflow_ind_dc"] = [
        {**r, "trade_date": DAY}
        for r in json.loads(
            Path("tests/fixtures/moneyflow_ind_dc_20260930.json").read_text()
        )
    ]
    staging, lake, source = setup(tmp_path, rows=rows)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    return staging, lake, source


def preview(staging, lake, instance):
    return preview_board_moneyflow_dc_history(
        instance=instance,
        staging_root=staging,
        lake_root=lake,
        operation_id="cohort",
        cutoff=DAY,
        expected_cohort_hash=_large_json(operation(staging) / "cohort.json")[
            "cohort_hash"
        ],
    )


class ReadOnly:
    def __init__(self, instance):
        self.instance = instance
        self.event_log_storage = SimpleNamespace(
            get_asset_check_execution_history=instance.event_log_storage.get_asset_check_execution_history
        )

    def get_dynamic_partitions(self, *args):
        return self.instance.get_dynamic_partitions(*args)

    def fetch_materializations(self, *args, **kwargs):
        return self.instance.fetch_materializations(*args, **kwargs)


def test_preview_hashes_frozen_physical_files_but_never_writes(tmp_path):
    staging, lake, source = prepare(tmp_path)
    before = hashes(staging), hashes(lake), source.calls
    instance_home = tmp_path / "instance"
    instance_home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(instance_home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        result = preview(staging, lake, ReadOnly(instance))
        assert result["history_dates"] == result["verified_units"] == 1
        assert result["history_rows"] == 1031 and result["dataset"] == "moneyflow_ind_dc"
        assert result["verified_files"] == 2
        assert result["partitions_to_add"] == 1
        assert result["metadata_queries"] == 5 and result["formal_writes"] == 0
        assert result["control_files_unchanged"] == 4
        assert all(
            value["materializations_to_add"] == value["recent_checks_to_add"] == 1
            for value in result["layers"].values()
        )
        assert preview(staging, lake, ReadOnly(instance)) == result
    assert before == (hashes(staging), hashes(lake), source.calls)


@pytest.mark.parametrize(
    "kind", ["changed_file", "missing_file", "checkpoint", "promotion"]
)
def test_preview_rejects_changed_proof_or_physical_file(tmp_path, kind):
    staging, lake, _ = prepare(tmp_path)
    path = raw_moneyflow_path(lake, "moneyflow_ind_dc", DAY)
    if kind == "changed_file":
        path.write_bytes(path.read_bytes() + b"changed")
    elif kind == "missing_file":
        path.unlink()  # only this test's isolated temporary file
    else:
        control = next((operation(staging) / "moneyflow_ind_dc").rglob(kind + ".json"))
        control.write_text("{}")
    with pytest.raises(MoneyflowContractError):
        preview(staging, lake, SimpleNamespace())


@pytest.mark.parametrize(
    "kind", ["valid", "wrong_hash", "wrong_upstream", "failed_check", "stale_check"]
)
def test_existing_native_events_reused_only_with_exact_file_and_target(tmp_path, kind):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    from orchestrator.defs.io.moneyflow_candidates import candidate_file_hash
    from orchestrator.defs.paths import silver_moneyflow_path
    from orchestrator.defs.run_contracts.moneyflow import (
        MONEYFLOW_IND_DC_RAW_CHECK,
        MONEYFLOW_IND_DC_SILVER_CHECK,
    )

    staging, lake, _ = prepare(tmp_path)
    raw_hash = candidate_file_hash(raw_moneyflow_path(lake, "moneyflow_ind_dc", DAY))
    instance_home = tmp_path / "instance"
    instance_home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(instance_home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        for layer, name in (
            ("raw", MONEYFLOW_IND_DC_RAW_CHECK),
            ("silver", MONEYFLOW_IND_DC_SILVER_CHECK),
        ):
            key = dg.AssetKey(
                "raw_tushare_moneyflow_ind_dc"
                if layer == "raw"
                else "silver_moneyflow_ind_dc"
            )
            digest = (
                raw_hash
                if layer == "raw"
                else candidate_file_hash(
                    silver_moneyflow_path(lake, "moneyflow_ind_dc", DAY)
                )
            )
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=key,
                    partition=DAY,
                    metadata={
                        "goldenshare/file_sha256": "0" * 64
                        if kind == "wrong_hash"
                        else digest,
                        "goldenshare/raw_sha256": "0" * 64
                        if kind == "wrong_upstream"
                        else raw_hash,
                    },
                )
            )
            mat = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=key, asset_partitions=[DAY]), limit=1
            ).records[0]
            instance.report_runless_asset_event(
                AssetCheckEvaluation(
                    asset_key=key,
                    check_name=name,
                    passed=kind != "failed_check",
                    partition=DAY,
                    blocking=True,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=mat.storage_id + (1 if kind == "stale_check" else 0),
                        run_id=mat.event_log_entry.run_id,
                        timestamp=mat.timestamp,
                    ),
                )
            )
        if kind == "valid":
            result = preview(staging, lake, ReadOnly(instance))
            assert all(
                v["materializations_to_add"] == v["recent_checks_to_add"] == 0
                and v["materializations_reusable"] == v["recent_checks_reusable"] == 1
                for v in result["layers"].values()
            )
        else:
            with pytest.raises(MoneyflowContractError):
                preview(staging, lake, ReadOnly(instance))


def test_unit_symlink_rejected_before_checkpoint_reader(tmp_path, monkeypatch):
    import orchestrator.defs.bootstrap.moneyflow_history_event_preview as module

    staging, lake, _ = prepare(tmp_path)
    unit = next((operation(staging) / "moneyflow_ind_dc").rglob("unit-000000"))
    moved = tmp_path / "moved-unit"
    unit.rename(moved)
    unit.symlink_to(moved, target_is_directory=True)

    def forbidden(*args):
        raise AssertionError(
            "A symlinked unit must be rejected before reading its checkpoint."
        )

    monkeypatch.setattr(module, "_promotion_state", forbidden)
    with pytest.raises(MoneyflowContractError, match="history_promotion_path"):
        preview(staging, lake, SimpleNamespace())


def test_preview_rejects_foreign_cohort_without_metadata_access(tmp_path):
    staging, lake, _ = prepare(tmp_path)
    with pytest.raises(MoneyflowContractError, match="history_cohort_changed"):
        preview_board_moneyflow_dc_history(
            instance=SimpleNamespace(),
            staging_root=staging,
            lake_root=lake,
            operation_id="cohort",
            cutoff=DAY,
            expected_cohort_hash="0" * 64,
        )


@pytest.mark.parametrize("foreign_dataset", ["moneyflow_mkt_dc", "moneyflow_ind_ths", "moneyflow_cnt_ths"])
def test_board_preview_never_reuses_foreign_events(tmp_path, foreign_dataset):
    staging, lake, _ = prepare(tmp_path)
    home = tmp_path / "instance"
    home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key="raw_tushare_" + foreign_dataset, partition=DAY
            )
        )
        instance.add_dynamic_partitions("cn_a_" + foreign_dataset + "_trade_days", [DAY])
        result = preview(staging, lake, ReadOnly(instance))
        assert result["partitions_to_add"] == 1 and all(
            v["materializations_to_add"] == 1 for v in result["layers"].values()
        )


def test_concept_proof_preserves_daily_source_row_count(tmp_path):
    staging, lake, _ = prepare(tmp_path)
    proof = board_moneyflow_dc_history_proof(
        staging_root=staging,
        lake_root=lake,
        operation_id="cohort",
        cutoff=DAY,
        expected_cohort_hash=_large_json(operation(staging) / "cohort.json")[
            "cohort_hash"
        ],
    )
    assert proof["dataset"] == "moneyflow_ind_dc"
    assert proof["history_rows"] == 1031
    assert proof["entries"][0]["day"] == "2026-09-30"
    assert proof["entries"][0]["row_count"] == 1031
    assert proof["entries"][0]["scope_row_counts"] == {"行业": 496, "概念": 504, "地域": 31}


def test_proof_counts_actual_categories_without_requiring_future_daily_scope(tmp_path):
    from .test_moneyflow_history_promote import setup

    staging, lake, _ = setup(tmp_path)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    proof = board_moneyflow_dc_history_proof(
        staging_root=staging, lake_root=lake, operation_id="cohort", cutoff=DAY,
        expected_cohort_hash=_large_json(operation(staging) / "cohort.json")["cohort_hash"],
    )
    assert proof["history_rows"] == proof["entries"][0]["row_count"] == 1
    assert proof["entries"][0]["scope_row_counts"] == {"行业": 1}
    # The very same history file must not pass the future three-scope daily check.
    from orchestrator.defs.checks.moneyflow_daily import audit_daily_moneyflow_file
    from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_connection
    with (
        moneyflow_candidate_connection(staging) as connection,
        pytest.raises(MoneyflowContractError, match="file_scope_coverage"),
    ):
        audit_daily_moneyflow_file(
            connection, raw_moneyflow_path(lake, "moneyflow_ind_dc", DAY), DAY,
            dataset="moneyflow_ind_dc",
        )


def test_recent_frozen_scope_and_row_count_are_verified(tmp_path, monkeypatch):
    import orchestrator.defs.bootstrap.moneyflow_history_event_preview as module

    staging, lake, _ = prepare(tmp_path)
    original = module.audit_moneyflow_automation_standardization
    def wrong_count(*args):
        return original(*args) - 1
    monkeypatch.setattr(module, "audit_moneyflow_automation_standardization", wrong_count)
    with pytest.raises(MoneyflowContractError, match="history_event_scope_or_rows_changed"):
        preview(staging, lake, SimpleNamespace())


def test_739_dates_read_native_state_in_batches_without_write_methods():
    from datetime import date, timedelta

    from orchestrator.defs.bootstrap.moneyflow_ind_dc_event_preview import (
        read_board_moneyflow_dc_event_state,
    )
    days = [(date(2023, 9, 12) + timedelta(days=i)).isoformat() for i in range(739)]
    entries = [{"day": d, "raw_sha256": "a" * 64, "silver_sha256": "b" * 64} for d in days]
    calls = {"parts": 0, "mats": 0, "checks": 0}
    class ReadOnlyBatches:
        @property
        def event_log_storage(self):
            return self
        def get_dynamic_partitions(self, name):
            assert name == "cn_a_moneyflow_ind_dc_trade_days"
            calls["parts"] += 1
            return []
        def fetch_materializations(self, records_filter, *, limit):
            assert records_filter.asset_key.to_user_string() in {
                "raw_tushare_moneyflow_ind_dc", "silver_moneyflow_ind_dc"
            }
            assert 0 < len(records_filter.asset_partitions) <= 100 and limit == 100
            calls["mats"] += 1
            return SimpleNamespace(records=[])
        def get_asset_check_execution_history(self, key, *, limit):
            assert key.asset_key.to_user_string() in {
                "raw_tushare_moneyflow_ind_dc", "silver_moneyflow_ind_dc"
            } and limit == 100
            calls["checks"] += 1
            return []
    state = read_board_moneyflow_dc_event_state(ReadOnlyBatches(), entries, days[-20:])
    assert state["metadata_queries"] == 19
    assert calls == {"parts": 1, "mats": 16, "checks": 2}
    assert not state["registered"] and not state["mats"] and not state["checks"]


def test_actual_category_counts_cannot_be_replaced_by_other_frozen_categories(tmp_path, monkeypatch):
    import orchestrator.defs.bootstrap.moneyflow_history_event_preview as module

    staging, lake, _ = prepare(tmp_path)
    original = module.expected_history_scopes
    def wrong_scopes(snapshot, days):
        # Same total, wrong category distribution: a total-count-only check would pass.
        scopes = original(snapshot, days)
        return [[day, scope, count + (1 if scope == "行业" else -1 if scope == "概念" else 0)]
                for day, scope, count in scopes]
    monkeypatch.setattr(module, "expected_history_scopes", wrong_scopes)
    with pytest.raises(MoneyflowContractError, match="history_event_scope_or_rows_changed"):
        preview(staging, lake, SimpleNamespace())
