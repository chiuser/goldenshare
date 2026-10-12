"""Frozen candidate proofs and native isolated event storage, with write traps."""

import json
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.bootstrap.moneyflow_event_preview import (
    preview_stock_moneyflow_history,
    stock_moneyflow_history_proof,
)
from orchestrator.defs.bootstrap.moneyflow_history_cohort import _large_json
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
    rows["moneyflow"] = [
        {**r, "trade_date": DAY}
        for r in json.loads(
            Path("tests/fixtures/moneyflow_20260930.json").read_text()
        )
    ]
    staging, lake, source = setup(tmp_path, rows=rows)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    return staging, lake, source


def preview(staging, lake, instance):
    return preview_stock_moneyflow_history(
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
        assert result["history_rows"] == 5572 and result["dataset"] == "moneyflow"
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
    path = raw_moneyflow_path(lake, "moneyflow", DAY)
    if kind == "changed_file":
        path.write_bytes(path.read_bytes() + b"changed")
    elif kind == "missing_file":
        path.unlink()  # only this test's isolated temporary file
    else:
        control = next((operation(staging) / "moneyflow").rglob(kind + ".json"))
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
        MONEYFLOW_RAW_CHECK,
        MONEYFLOW_SILVER_CHECK,
    )

    staging, lake, _ = prepare(tmp_path)
    raw_hash = candidate_file_hash(raw_moneyflow_path(lake, "moneyflow", DAY))
    instance_home = tmp_path / "instance"
    instance_home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(instance_home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        for layer, name in (
            ("raw", MONEYFLOW_RAW_CHECK),
            ("silver", MONEYFLOW_SILVER_CHECK),
        ):
            key = dg.AssetKey(
                "raw_tushare_moneyflow"
                if layer == "raw"
                else "silver_moneyflow"
            )
            digest = (
                raw_hash
                if layer == "raw"
                else candidate_file_hash(
                    silver_moneyflow_path(lake, "moneyflow", DAY)
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
    unit = next((operation(staging) / "moneyflow").rglob("unit-000000"))
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
        preview_stock_moneyflow_history(
            instance=SimpleNamespace(),
            staging_root=staging,
            lake_root=lake,
            operation_id="cohort",
            cutoff=DAY,
            expected_cohort_hash="0" * 64,
        )


@pytest.mark.parametrize(
    "foreign_dataset", ["moneyflow_mkt_dc", "moneyflow_ind_ths", "moneyflow_dc"]
)
def test_stock_preview_never_reuses_foreign_events(tmp_path, foreign_dataset):
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
        instance.add_dynamic_partitions(
            "cn_a_" + foreign_dataset + "_trade_days", [DAY]
        )
        result = preview(staging, lake, ReadOnly(instance))
        assert result["partitions_to_add"] == 1 and all(
            v["materializations_to_add"] == 1 for v in result["layers"].values()
        )


def test_stock_proof_preserves_daily_source_row_count(tmp_path):
    staging, lake, _ = prepare(tmp_path)
    proof = stock_moneyflow_history_proof(
        staging_root=staging,
        lake_root=lake,
        operation_id="cohort",
        cutoff=DAY,
        expected_cohort_hash=_large_json(operation(staging) / "cohort.json")[
            "cohort_hash"
        ],
    )
    assert proof["dataset"] == "moneyflow"
    assert proof["history_rows"] == 5572
    assert proof["entries"][0]["day"] == "2026-09-30"
    assert proof["entries"][0]["row_count"] == 5572


def test_recent_schema_count_must_match_frozen_count(tmp_path, monkeypatch):
    import orchestrator.defs.bootstrap.moneyflow_history_event_preview as module

    staging, lake, _ = prepare(tmp_path)
    original = module.audit_moneyflow_automation_standardization

    def changed(*args, **kwargs):
        return original(*args, **kwargs) + 1

    monkeypatch.setattr(module, "audit_moneyflow_automation_standardization", changed)
    with pytest.raises(MoneyflowContractError, match="history_event_rows_changed"):
        preview(staging, lake, SimpleNamespace())


def test_4067_source_dates_use_85_bounded_native_reads():
    from datetime import date, timedelta

    from orchestrator.defs.bootstrap.moneyflow_event_preview import (
        read_stock_moneyflow_event_state,
    )

    dates = [(date(2010, 1, 4) + timedelta(days=i)).isoformat() for i in range(4067)]
    calls = {"partitions": 0, "materializations": 0, "checks": 0}

    class Reader:
        event_log_storage = property(lambda self: self)

        def get_dynamic_partitions(self, name):
            assert name == "cn_a_moneyflow_trade_days"
            calls["partitions"] += 1
            return []

        def fetch_materializations(self, records_filter, *, limit):
            assert records_filter.asset_key.to_user_string() in (
                "raw_tushare_moneyflow",
                "silver_moneyflow",
            )
            assert 1 <= len(records_filter.asset_partitions) <= 100 and limit == 100
            calls["materializations"] += 1
            return SimpleNamespace(records=[])

        def get_asset_check_execution_history(self, key, *, limit):
            assert (
                key.asset_key.to_user_string()
                in ("raw_tushare_moneyflow", "silver_moneyflow")
                and limit == 100
            )
            calls["checks"] += 1
            return []

    state = read_stock_moneyflow_event_state(
        Reader(),
        [{"day": d, "raw_sha256": "a" * 64, "silver_sha256": "b" * 64} for d in dates],
        dates[-20:],
    )
    assert state["metadata_queries"] == 85
    assert calls == {"partitions": 1, "materializations": 82, "checks": 2}
    assert state["mats"] == state["checks"] == {} and state["registered"] == set()


def test_proof_uses_actual_source_dates_without_filling_gap(tmp_path):
    from orchestrator.defs.bootstrap.moneyflow_event_preview import (
        stock_moneyflow_history_proof,
    )

    from .test_moneyflow_history_promote import DATASETS, Source

    rows = {d: [Source.row(d)] for d in DATASETS}
    rows["moneyflow"] = [
        {**Source.row("moneyflow"), "trade_date": d}
        for d in ("2010-01-04", "2010-01-06")
    ]
    staging, lake, _ = setup(tmp_path, rows=rows)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    proof = stock_moneyflow_history_proof(
        staging_root=staging,
        lake_root=lake,
        operation_id="cohort",
        cutoff=DAY,
        expected_cohort_hash=_large_json(operation(staging) / "cohort.json")[
            "cohort_hash"
        ],
    )
    assert [e["day"] for e in proof["entries"]] == [
        "2010-01-04",
        "2010-01-06",
    ]
    assert proof["history_rows"] == 2 and proof["verified_files"] == 4
    assert all(
        e["row_count"] == 1 and "scope_row_counts" not in e for e in proof["entries"]
    )



def test_native_capacity_truncation_cannot_be_accepted():
    from orchestrator.defs.bootstrap.moneyflow_event_preview import (
        read_stock_moneyflow_event_state,
    )

    class Reader:
        def get_dynamic_partitions(self, name):
            return []

        def fetch_materializations(self, records_filter, *, limit):
            return SimpleNamespace(records=[SimpleNamespace(partition_key="2010-01-04")] * 100)

    with pytest.raises(MoneyflowContractError, match="history_event_record_limit"):
        read_stock_moneyflow_event_state(
            Reader(), [{"day": d, "raw_sha256": "a" * 64, "silver_sha256": "b" * 64}
                       for d in ("2010-01-04", "2010-01-06")], [])
