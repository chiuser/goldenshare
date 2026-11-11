"""LLD6 native record boundaries; no formal definitions or external resources.

Metadata assertions are literal. The real producer and temporary consolidated
Dagster store exercise event/run identity, not file or network correctness.
"""

from dataclasses import replace
from datetime import date
from unittest.mock import patch

import dagster as dg
import pytest
from dagster._core.storage.tags import PARTITION_NAME_TAG

from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    read_stk_factor_pro_failure,
    read_stk_factor_pro_recorded_results,
    resolve_stk_factor_pro_source_run,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.test_stk_factor_pro_dagster_events import _isolated_instance

T, P = date(2026, 10, 21), date(2026, 10, 20)
CONFIG = {
    "execution_day": str(T),
    "target_trade_date": str(T),
    "purpose": "today",
    "scheduled_slot": 0,
}


def run_observations(instance, kinds, *, previous=None, fail=None, options=None):
    emitted = []
    state = previous or C.empty_stk_factor_pro_recorded_results(T)

    @dg.op(
        name="stk_factor_pro",
        config_schema=C.STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA,
        out={},
    )
    def operation(context):
        identity = C.RunIdentity(context.run_id, None, T, T, P, "today", 0)
        for kind in kinds:
            metadata = C.build_stk_factor_pro_observation_metadata(
                identity=identity,
                recorded_results=state,
                observation_kind=kind,
                result=(options or {}).get("result", "waiting")
                if kind in ("day", "history")
                else None,
                history_plan_ref=C.RecordRef(
                    context.run_id, "history-plan.json", "a" * 64
                )
                if kind != "precheck"
                else None,
                history_ranges_ref=C.RecordRef(
                    context.run_id, "history-ranges.json", "b" * 64
                )
                if kind != "precheck"
                else None,
                **{k: v for k, v in (options or {}).items() if k != "result"},
            )
            assert metadata["phase_result_version"] == 1
            assert metadata["target_trade_date"] == "2026-10-21"
            assert metadata["goldenshare/download_started"] is (kind == "start")
            yield dg.AssetObservation(
                asset_key=C.STK_FACTOR_PRO_RAW_ASSET_KEY,
                partition=str(T),
                metadata=metadata,
            )
            emitted.append(kind)
        if fail is not None:
            raise dg.Failure(
                "测试实际失败",
                metadata={
                    "goldenshare/retryable": fail[1],
                    "goldenshare/failure_phase": fail[0],
                    "goldenshare/target_trade_date": str(T),
                },
                allow_retries=False,
            )

    @dg.job(name=C.STK_FACTOR_PRO_UPDATE_JOB_NAME)
    def job():
        operation()

    result = job.execute_in_process(
        instance=instance,
        run_config={"ops": {"stk_factor_pro": {"config": CONFIG}}},
        tags={PARTITION_NAME_TAG: str(T)},
        raise_on_error=False,
    )
    return result, emitted


def latest_ref(instance, run_id):
    record = instance.get_records_for_run(
        run_id, of_type=dg.DagsterEventType.ASSET_OBSERVATION, ascending=False, limit=1
    ).records[0]
    return C.StkFactorProResultRef(run_id, record.storage_id)


def test_direct_old_day_survives_many_history_observations(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        first, _ = run_observations(instance, ["day"])
        day_ref = latest_ref(instance, first.run_id)
        state = replace(
            C.empty_stk_factor_pro_recorded_results(T), day_result_ref=day_ref
        )
        later, emitted = run_observations(instance, ["history"] * 21, previous=state)
        assert len(emitted) == 21 and later.success
        with patch.object(
            instance, "fetch_observations", wraps=instance.fetch_observations
        ) as read:
            known = {}
            result = read_stk_factor_pro_recorded_results(
                instance, target_trade_date=T, known_pg=known
            )
            assert result.day_result_ref == day_ref
            assert result.history_result_ref.run_id == later.run_id
            assert read.call_count == 2
            assert all(c.kwargs["limit"] == 1 for c in read.call_args_list)
            assert read.call_args_list[1].args[0].storage_ids == [day_ref.storage_id]
            assert (
                read_stk_factor_pro_recorded_results(
                    instance, target_trade_date=T, known_pg=known
                )
                is result
            )
            assert read.call_count == 2


def test_start_keeps_old_results_and_new_pending_plan(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        old, _ = run_observations(instance, ["day"])
        prior = replace(
            C.empty_stk_factor_pro_recorded_results(T),
            day_result_ref=latest_ref(instance, old.run_id),
        )
        first_failure, _ = run_observations(
            instance, ["history"], previous=prior, fail=("history", False)
        )
        prior = replace(
            prior,
            history_result_ref=latest_ref(instance, first_failure.run_id),
            unresolved_history_failure_run_id=first_failure.run_id,
        )
        new, _ = run_observations(
            instance, ["start"], previous=prior, fail=("history", True)
        )
        result = read_stk_factor_pro_recorded_results(
            instance, target_trade_date=T, known_pg={}
        )
        assert result.day_result_ref == prior.day_result_ref
        assert result.history_result_ref == prior.history_result_ref
        assert any(p.creator_run_id == new.run_id for p in result.pending_plan_refs)
        assert result.unresolved_history_failure_run_id == new.run_id
        assert result.successful_publication_refs == ()


def test_exit_before_first_observation_not_hidden_by_old_success(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        run_observations(instance, ["day"])
        failed, _ = run_observations(instance, [], fail=("day", False))
        known = {}
        result = read_stk_factor_pro_recorded_results(
            instance, target_trade_date=T, known_pg=known
        )
        assert result.unresolved_day_failure_run_id == failed.run_id
        with patch.object(
            instance.event_log_storage,
            "get_records_for_run",
            wraps=instance.event_log_storage.get_records_for_run,
        ) as read:
            assert read_stk_factor_pro_failure(
                instance, failed.run_id, known_pg=known
            ) == {"retryable": False, "failure_phase": "day"}
            assert read.call_count == 0


def test_empty_and_bad_reference_do_not_expand_scan(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        assert (
            read_stk_factor_pro_recorded_results(
                instance, target_trade_date=T, known_pg={}
            ).day_result_ref
            is None
        )
        prior = replace(
            C.empty_stk_factor_pro_recorded_results(T),
            day_result_ref=C.StkFactorProResultRef("missing-run", 999999),
        )
        run_observations(instance, ["start"], previous=prior)
        with patch.object(
            instance, "fetch_observations", wraps=instance.fetch_observations
        ) as read:
            with pytest.raises(ValueError, match="明确引用"):
                read_stk_factor_pro_recorded_results(
                    instance, target_trade_date=T, known_pg={}
                )
            assert read.call_count == 2


def test_closed_metadata_and_ordinary_context(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        result, _ = run_observations(instance, ["precheck"])
        record = instance.get_records_for_run(
            result.run_id, of_type=dg.DagsterEventType.ASSET_OBSERVATION, limit=1
        ).records[0]
        metadata = record.event_log_entry.dagster_event.asset_observation_data.asset_observation.metadata
        parsed = C.parse_stk_factor_pro_observation_metadata(metadata)
        assert parsed["bootstrap_context"] is None
        assert parsed["result"] is None and parsed["phase"] is None
        assert parsed["goldenshare/download_started"] is False
        with pytest.raises(ValueError, match="缺字段"):
            C.parse_stk_factor_pro_observation_metadata(
                {k: v for k, v in metadata.items() if k != "pending_plan_refs"}
            )
        with pytest.raises(ValueError, match="未知字段"):
            C.parse_stk_factor_pro_observation_metadata(
                {**metadata, "unexpected": dg.MetadataValue.int(1)}
            )


def test_no_parent_has_no_reexecution_authority(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        result, _ = run_observations(instance, ["precheck"])
        run = instance.get_run_by_id(result.run_id)
        value = C.parse_stk_factor_pro_run_input(CONFIG, str(T), {P: None, T: P})
        assert (
            resolve_stk_factor_pro_source_run(
                instance, run, value, known_pg={}, known_records={}
            )
            is None
        )


def test_history_completion_requires_final_success_and_keeps_day_failure(tmp_path):
    # These literal file IDs describe the metadata boundary only; file readiness
    # and publication are verified by the later actual writer/check tests.
    coverage = C.StkFactorProRawCoverage(
        T,
        True,
        True,
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        1,
        1,
        0,
        0,
        "1",
        (),
        "完整",
        1,
        2,
        None,
    )
    silver = C.StkFactorProTargetSilver(
        T, True, "e" * 64, "a" * 64, "a" * 64, 3, 4, "通过"
    )
    with _isolated_instance(tmp_path) as instance:
        failed, _ = run_observations(
            instance,
            ["history"],
            fail=("history", False),
            options={
                "result": "completed",
                "raw_coverage": coverage,
                "target_silver": silver,
                "publication_complete_digest": "f" * 64,
            },
        )
        state = read_stk_factor_pro_recorded_results(
            instance, target_trade_date=T, known_pg={}
        )
        assert state.successful_publication_refs == ()
        assert any(p.creator_run_id == failed.run_id for p in state.pending_plan_refs)
        assert state.unresolved_history_failure_run_id == failed.run_id
        repaired, _ = run_observations(
            instance,
            ["history"],
            previous=state,
            options={
                "result": "completed",
                "raw_coverage": coverage,
                "target_silver": silver,
                "publication_complete_digest": "e" * 64,
                "recovery_of_run_id": failed.run_id,
            },
        )
        result = read_stk_factor_pro_recorded_results(
            instance, target_trade_date=T, known_pg={}
        )
        assert result.successful_publication_refs == (
            C.RecordRef(
                repaired.run_id,
                "publication/history/publication-complete.json",
                "e" * 64,
            ),
        )
        assert result.unresolved_history_failure_run_id is None


def test_no_action_does_not_clear_failed_day(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        old, _ = run_observations(instance, [], fail=("day", False))
        prior = read_stk_factor_pro_recorded_results(
            instance, target_trade_date=T, known_pg={}
        )
        run_observations(
            instance,
            ["day"],
            previous=prior,
            options={
                "result": "no_action",
                "recovery_of_run_id": old.run_id,
            },
        )
        result = read_stk_factor_pro_recorded_results(
            instance, target_trade_date=T, known_pg={}
        )
        assert result.unresolved_day_failure_run_id == old.run_id


def test_actual_reexecution_parent_is_checked_once_and_config_must_match(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        parent, _ = run_observations(instance, ["start"], fail=("day", False))

        @dg.op(
            name="stk_factor_pro", config_schema=C.STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA
        )
        def operation():
            pass

        @dg.job(name=C.STK_FACTOR_PRO_UPDATE_JOB_NAME)
        def job():
            operation()

        child = instance.create_run_for_job(
            job,
            run_config={"ops": {"stk_factor_pro": {"config": CONFIG}}},
            tags={PARTITION_NAME_TAG: str(T)},
            parent_run_id=parent.run_id,
            root_run_id=parent.run_id,
        )
        value = C.parse_stk_factor_pro_run_input(CONFIG, str(T), {P: None, T: P})
        known = {}
        with patch.object(
            instance, "get_run_by_id", wraps=instance.get_run_by_id
        ) as read:
            source = resolve_stk_factor_pro_source_run(
                instance, child, value, known_pg=known, known_records={}
            )
            assert source.parent_run_id == parent.run_id
            assert source.root_run_id == parent.run_id
            assert source.original_status == "FAILURE"
            assert source.history_plan_ref.creator_run_id == parent.run_id
            assert read.call_count == 1
        with pytest.raises(ValueError, match="七字段"):
            resolve_stk_factor_pro_source_run(
                instance,
                child,
                replace(value, scheduled_slot=1),
                known_pg=known,
                known_records={},
            )


def test_reference_wrong_run_and_wrong_phase_are_rejected(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        first, _ = run_observations(instance, ["day"])
        real = latest_ref(instance, first.run_id)
        prior = replace(
            C.empty_stk_factor_pro_recorded_results(T),
            day_result_ref=C.StkFactorProResultRef("other-run", real.storage_id),
        )
        run_observations(instance, ["start"], previous=prior)
        with pytest.raises(ValueError, match="run不符"):
            read_stk_factor_pro_recorded_results(
                instance, target_trade_date=T, known_pg={}
            )
        prior = replace(
            C.empty_stk_factor_pro_recorded_results(T), history_result_ref=real
        )
        run_observations(instance, ["start"], previous=prior)
        with pytest.raises(ValueError, match="阶段"):
            read_stk_factor_pro_recorded_results(
                instance, target_trade_date=T, known_pg={}
            )


def test_reopened_store_uses_persisted_complete_reference(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        old, _ = run_observations(instance, ["day"])
        ref = latest_ref(instance, old.run_id)
        prior = replace(C.empty_stk_factor_pro_recorded_results(T), day_result_ref=ref)
        run_observations(instance, ["precheck"], previous=prior)
    with _isolated_instance(tmp_path) as reopened:
        result = read_stk_factor_pro_recorded_results(
            reopened, target_trade_date=T, known_pg={}
        )
        assert result.day_result_ref == ref
        assert result.history_result_ref is None
