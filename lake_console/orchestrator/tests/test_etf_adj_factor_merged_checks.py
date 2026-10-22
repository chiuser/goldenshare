"""Merged checks use actual ETF producer fixtures and independent rule expectations.

Raw/Silver fixtures come from the existing writers in etf_daily_test_support and
test_etf_daily_silver_checks. Synthetic rule failures below isolate Dagster's
six-result/blocking boundary; missing-file cases exercise the real audit.
"""

from dataclasses import replace
from pathlib import Path

import dagster as dg
import pytest

from orchestrator.defs.assets import etf_daily as assets
from orchestrator.defs.checks import etf_daily_checks as checks
from orchestrator.defs.io.etf_daily_silver_writer import FUND_ADJ_SILVER_SPEC
from orchestrator.defs.jobs.etf_daily import silver_etf_adj_factor_update_job
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_FACTOR_COMPLETION_METADATA_KEY,
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
)
from tests.test_etf_daily_silver_checks import (
    PARTITION,
    _report_materialization,
    _write_adj,
)

ASSET = dg.AssetKey("silver_etf_adj_factor")
KINDS = (
    "contract",
    "source_filter",
    "source_parity",
    "key_integrity",
    "domain",
    "coverage",
)


@pytest.fixture
def merged_partition(tmp_path, monkeypatch):
    lake, written = _write_adj(tmp_path)
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    with dg.DagsterInstance.ephemeral(
        tempdir=str(instance_dir), settings={"telemetry": {"enabled": False}}
    ) as instance:
        _report_materialization(instance, written)
        instance.add_dynamic_partitions(cn_a_etf_mins_trade_days.name, [PARTITION])
        definitions = dg.Definitions(
            assets=[assets.silver_etf_adj_factor],
            asset_checks=[checks.silver_etf_adj_factor_checks],
            jobs=[silver_etf_adj_factor_update_job],
            resources={
                "lake_root": LakeRootResource(root_path=str(lake)),
                "duckdb": DuckDBResource(),
            },
        )
        full_job = definitions.resolve_job_def("silver_etf_adj_factor_update_job")

        def forbidden_writer(**kwargs):
            pytest.fail("checks-only execution called the factor writer")

        monkeypatch.setattr(
            assets, "write_etf_adj_factor_silver_partition", forbidden_writer
        )

        def execute(
            names=SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS, *, tags=None, resources=None
        ):
            selected = {dg.AssetCheckKey(ASSET, name) for name in names}
            job = full_job.get_subset(
                asset_selection=set(), asset_check_selection=selected
            )
            assert not job.asset_layer.executable_asset_keys
            return job.execute_in_process(
                instance=instance,
                partition_key=PARTITION,
                tags=tags,
                raise_on_error=False,
                resources=resources,
            )

        yield lake, written, instance, execute


def evaluations_by_kind(result):
    by_name = {
        evaluation.check_name: evaluation
        for evaluation in result.get_asset_check_evaluations()
    }
    assert set(by_name) == set(SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS)
    assert all(
        ev.asset_key == ASSET and ev.partition == PARTITION for ev in by_name.values()
    )
    assert all(
        ev.blocking and ev.severity is dg.AssetCheckSeverity.ERROR
        for ev in by_name.values()
    )
    return tuple(by_name[name].passed for name in SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS)


def test_merged_definition_keeps_exact_original_check_keys_and_partitions():
    definition = checks.silver_etf_adj_factor_checks
    assert definition.node_def.name == "silver_etf_adj_factor_checks"
    assert definition.can_subset
    specs = tuple(definition.check_specs)
    assert {spec.key for spec in specs} == {
        dg.AssetCheckKey(ASSET, name) for name in SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS
    }
    assert len(specs) == 6
    assert all(
        spec.blocking and spec.partitions_def is cn_a_etf_mins_trade_days
        for spec in specs
    )
    assert not any(
        hasattr(checks, name) for name in SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS
    )


def test_one_real_checks_only_run_audits_once_and_keeps_original_target(
    merged_partition,
    monkeypatch,
):
    _, written, instance, execute = merged_partition
    before = (written.raw_path.read_bytes(), written.target_path.read_bytes())
    target = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=ASSET, asset_partitions=[PARTITION]), limit=1
    ).records[0]
    original_audit = checks.audit_etf_daily_silver_partition
    original_basic = checks.validate_etf_daily_basic_reference
    audit_calls, basic_calls = [], []

    def monitored_audit(**kwargs):
        audit_calls.append(kwargs)
        return original_audit(**kwargs)

    def monitored_basic(**kwargs):
        basic_calls.append(kwargs)
        return original_basic(**kwargs)

    monkeypatch.setattr(checks, "audit_etf_daily_silver_partition", monitored_audit)
    monkeypatch.setattr(checks, "validate_etf_daily_basic_reference", monitored_basic)
    result = execute()
    assert result.success
    assert evaluations_by_kind(result) == (True, True, True, True, True, True)
    assert all(
        "goldenshare/historical_added_row_count" not in evaluation.metadata
        for evaluation in result.get_asset_check_evaluations()
    )
    assert len(audit_calls) == len(basic_calls) == 1
    assert audit_calls[0]["check_kinds"] == frozenset(KINDS)
    assert not result.get_asset_materialization_events()
    assert all(
        ev.target_materialization_data.storage_id == target.storage_id
        for ev in result.get_asset_check_evaluations()
    )
    assert (written.raw_path.read_bytes(), written.target_path.read_bytes()) == before


@pytest.mark.parametrize(
    ("failed_kind", "expected"),
    [
        ("contract", (False, True, True, True, True, True)),
        ("source_filter", (True, False, True, True, True, True)),
        ("source_parity", (True, True, False, True, True, True)),
        ("key_integrity", (True, True, True, False, True, True)),
        ("domain", (True, True, True, True, False, True)),
        ("coverage", (True, True, True, True, True, False)),
    ],
)
def test_every_individual_failure_preserves_all_six_results_and_fails_run(
    merged_partition,
    monkeypatch,
    failed_kind,
    expected,
):
    _, _, _, execute = merged_partition
    actual_rules = checks._silver_failed_rules

    def one_literal_failure(audit, *, check_kind):
        if check_kind == failed_kind:
            return ("synthetic_independent_rule_failure",)
        return actual_rules(audit, check_kind=check_kind)

    monkeypatch.setattr(checks, "_silver_failed_rules", one_literal_failure)
    result = execute()
    assert not result.success
    assert evaluations_by_kind(result) == expected
    assert len(result.get_step_failure_events()) == 1


@pytest.mark.parametrize("unavailable_raw", ["missing", "unreadable"])
def test_raw_failure_leaves_four_independent_checks_true(
    merged_partition,
    unavailable_raw,
):
    _, written, _, execute = merged_partition
    if unavailable_raw == "missing":
        written.raw_path.rename(written.raw_path.with_suffix(".held"))
    else:
        written.raw_path.write_bytes(b"invalid synthetic parquet")
    result = execute()
    assert not result.success
    assert evaluations_by_kind(result) == (True, True, False, True, True, False)


def test_missing_basic_does_not_change_silver_only_results(merged_partition):
    _, written, _, execute = merged_partition
    basic_path = Path(written.basic_reference.silver_uri)
    basic_path.rename(basic_path.with_suffix(".held"))
    result = execute()
    assert not result.success
    assert evaluations_by_kind(result) == (True, False, False, True, True, False)


def test_silver_unreadable_cannot_pass_any_check(merged_partition):
    _, written, _, execute = merged_partition
    written.target_path.write_bytes(b"invalid synthetic silver parquet")
    result = execute()
    assert not result.success
    assert evaluations_by_kind(result) == (False, False, False, False, False, False)


def test_single_key_selection_does_not_prepare_raw_or_basic(
    merged_partition,
    monkeypatch,
):
    _, _, _, execute = merged_partition

    def forbidden_unrelated_input(*args, **kwargs):
        pytest.fail("key-only selection attempted Raw or Basic validation")

    monkeypatch.setattr(
        checks, "validate_etf_daily_basic_reference", forbidden_unrelated_input
    )
    monkeypatch.setattr(
        checks, "audit_etf_daily_raw_relation", forbidden_unrelated_input
    )
    result = execute([SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS[3]])
    assert result.success
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0].check_name == "silver_etf_adj_factor_key_integrity_check"
    assert evaluations[0].passed and evaluations[0].partition == PARTITION


def test_result_construction_is_pure(merged_partition, monkeypatch):
    lake, _, instance, _ = merged_partition
    audit = checks.audit_etf_daily_silver_partition(
        instance=instance,
        lake_root_path=lake,
        duckdb_resource=DuckDBResource(),
        spec=FUND_ADJ_SILVER_SPEC,
        partition_key=PARTITION,
    )
    # The saved missing-path facts, not filesystem probes, control metadata.
    audit = replace(audit, missing_file_paths=(audit.raw_file_path,))

    def forbidden_file_probe(*args, **kwargs):
        pytest.fail("pure result construction performed a file probe")

    with monkeypatch.context() as pure_scope:
        pure_scope.setattr(Path, "is_file", forbidden_file_probe)
        result = checks.build_etf_daily_silver_check_result(
            audit, check_kind="coverage"
        )
        assert result.passed
        assert result.metadata["goldenshare/missing_file_paths"].value == [
            str(audit.raw_file_path)
        ]
        history_audit = replace(
            audit,
            history=checks.FactorHistoryAudit(
                audit.relation, audit.basic_reference, ()
            ),
            source_filter=None,
        )
        accepted_history = checks.build_etf_daily_silver_check_result(
            history_audit, check_kind="source_filter"
        )
        assert accepted_history.passed
        assert accepted_history.metadata["goldenshare/failed_row_count"].value == 0
        assert "goldenshare/historical_added_row_count" not in accepted_history.metadata


@pytest.mark.parametrize("lost_value", [None, "wrong-type"])
def test_maintenance_missing_basic_is_rejected_before_audit(
    merged_partition,
    monkeypatch,
    lost_value,
):
    _, _, _, execute = merged_partition

    def forbidden_audit(**kwargs):
        pytest.fail("maintenance resource guard ran after audit")

    monkeypatch.setattr(checks, "audit_etf_daily_silver_partition", forbidden_audit)
    result = execute(
        tags={ETF_FACTOR_COMPLETION_METADATA_KEY: "synthetic-plan-hash"},
        resources={
            "prepared_basic": dg.ResourceDefinition.hardcoded_resource(lost_value)
        },
    )
    assert not result.success
    assert not result.get_asset_check_evaluations()
    assert "completion_prepared_basic_required" in str(
        result.get_step_failure_events()[0]
    )
