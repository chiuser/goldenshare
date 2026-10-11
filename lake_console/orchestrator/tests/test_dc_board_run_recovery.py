"""Isolated recovery evidence: no formal instance, files, DB or network."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import dagster as dg
import pytest
from dagster._core.storage.tags import PARTITION_NAME_TAG, RUN_KEY_TAG, SENSOR_NAME_TAG

from orchestrator.defs.asset_guards.dc_board_run_recovery import (
    dc_recovery_decision,
    retryable_dc_failure,
    validate_dc_running_identity,
)
from orchestrator.defs.run_contracts.configs import (
    DcBoardRawRunConfig,
    DcBoardRecoveryIdentityConfig,
    build_raw_dc_board_update_job_run_config,
)
from orchestrator.defs.run_contracts.dc_board import DC_BOARD_RECOVERY_POLICY_VERSION
from orchestrator.defs.run_contracts.dc_board_failures import (
    DcBoardFailureFacts,
    DcBoardRequestFailure,
    request_failure_facts,
)
from orchestrator.defs.run_contracts.run_keys import (
    build_asset_update_run_key,
    build_repair_attempt_run_key,
)
from orchestrator.defs.tushare_errors import TushareResponseError
from orchestrator.defs.tushare_request_policy import (
    TushareCodeFailure,
    TushareRequestPolicy,
    execute_bounded_code_requests,
)
from tests.dc_board_quote_test_support import source_proof
from tests.test_dc_board_raw_io import _completion, _source_result

DAY = "2026-07-14"
ASSET = "raw_tushare_dc_member"
JOB = ASSET + "_update_job"
NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
FACTS = DcBoardFailureFacts(
    "source_response_unclassified",
    True,
    True,
    1,
    0,
    4,
    3,
    False,
    failure_samples=("BK1615.DC",),
)


def expected_dc_run_key(job_name, trade_date, attempt):
    # Test fixture construction only; production compares native keys inline via shared builders.
    if attempt == 1:
        return build_asset_update_run_key(subject=job_name.removesuffix("_job"), unit_id=trade_date)
    return build_repair_attempt_run_key(subject=job_name.removesuffix("_job"), repair_scope_id=trade_date, attempt=attempt)


def identity(attempt=1, source=None):
    return DcBoardRecoveryIdentityConfig(
        policy_version=DC_BOARD_RECOVERY_POLICY_VERSION,
        automatic_attempt=attempt,
        source_failure_run_id=source,
    )


def record(
    attempt=1,
    *,
    run_id=None,
    source=None,
    status=dg.DagsterRunStatus.FAILURE,
    legacy=False,
    manual=False,
    end=None,
    job=JOB,
    day=DAY,
):
    asset = job.removesuffix("_update_job")
    run_id = run_id or "run-" + str(attempt)
    tags = {PARTITION_NAME_TAG: day}
    config = {"source_proof": {}, "recovery_identity": None}
    if not manual:
        tags.update(
            {
                RUN_KEY_TAG: expected_dc_run_key(job, day, attempt),
                SENSOR_NAME_TAG: job + "_sensor",
            }
        )
        config = (
            {}
            if legacy
            else {
                "source_proof": {},
                "recovery_identity": identity(attempt, source).model_dump(),
            }
        )
    run = NS(
        run_id=run_id,
        job_name=job,
        status=status,
        tags=tags,
        run_config={"ops": {asset: {"config": config}}},
        parent_run_id=None,
        root_run_id=None,
        remote_job_origin=NS(job_name=job),
    )
    return NS(dagster_run=run, end_time=NOW.timestamp() - 600 if end is None else end)


def event(metadata=None, step=ASSET):
    values = FACTS.metadata() if metadata is None else metadata
    failure = NS(
        metadata={
            key: dg.MetadataValue.json(value)
            if isinstance(value, list)
            else dg.MetadataValue.bool(value)
            if type(value) is bool
            else dg.MetadataValue.int(value)
            if type(value) is int
            else dg.MetadataValue.null()
            if value is None
            else dg.MetadataValue.text(value)
            for key, value in values.items()
        }
    )
    return NS(
        event_log_entry=NS(
            dagster_event=NS(
                step_key=step, step_failure_data=NS(user_failure_data=failure)
            )
        )
    )


class Instance:
    def __init__(self, records=(), events=None, active=()):
        self.records = records
        self.active = active
        self.events = [event()] if events is None else events
        self.calls = []
        self.has_more = False

    def get_run_records(self, *, filters, limit):
        self.calls.append((filters, limit))
        if filters.statuses:
            assert filters.job_name.startswith(("raw_tushare_dc_", "silver_"))
            assert limit == 2
            return self.active
        assert filters.tags == {PARTITION_NAME_TAG: DAY} and limit == 21
        return self.records[:limit]

    def get_records_for_run(self, run_id, *, of_type, limit):
        assert of_type == dg.DagsterEventType.STEP_FAILURE and limit == 21
        return NS(records=self.events[:limit], has_more=self.has_more)


def decide(instance, **kwargs):
    return dc_recovery_decision(
        instance, job_name=JOB, trade_date=DAY, now=NOW, **kwargs
    )


@pytest.mark.parametrize("value", [True, False, "1", 1.0, 0, 4, -1, None])
def test_identity_rejects_coercion_and_out_of_range(value):
    with pytest.raises(ValueError):
        identity(value)


@pytest.mark.parametrize(
    "attempt,source", [(1, "failed"), (2, None), (3, ""), (2, " "), (3, " x ")]
)
def test_identity_rejects_wrong_failure_reference(attempt, source):
    with pytest.raises(ValueError):
        identity(attempt, source)


def test_policy_version_required_and_exact():
    with pytest.raises(ValueError):
        DcBoardRecoveryIdentityConfig(automatic_attempt=1)
    with pytest.raises(ValueError):
        DcBoardRecoveryIdentityConfig(policy_version="other", automatic_attempt=1)


@pytest.mark.parametrize(
    "asset", ["raw_tushare_dc_index", "raw_tushare_dc_member", "raw_tushare_dc_daily"]
)
def test_outer_config_only_and_manual_has_no_identity(asset):
    proof = source_proof(_completion(), _source_result()).model_copy(
        update={"target_asset": asset}
    )
    manual = build_raw_dc_board_update_job_run_config(
        asset_name=asset, partition_key=DAY, proof=proof
    )
    config = DcBoardRawRunConfig.model_validate(manual["ops"][asset]["config"])
    assert config.source_proof == proof and config.recovery_identity is None
    assert "automatic_attempt" not in proof.model_dump()
    with pytest.raises(ValueError):
        DcBoardRawRunConfig.model_validate(proof.model_dump())
    for attempt, source in ((1, None), (2, "run-1"), (3, "run-2")):
        automatic = build_raw_dc_board_update_job_run_config(
            asset_name=asset,
            partition_key=DAY,
            proof=proof,
            recovery_identity=identity(attempt, source),
        )
        assert (
            automatic["ops"][asset]["config"]["recovery_identity"]["automatic_attempt"]
            == attempt
        )


def test_first_request_and_retry_cooldown_boundaries_and_exhaustion():
    first = decide(Instance())
    assert first.identity == identity()
    for seconds in (599, 600):
        previous = record(end=NOW.timestamp() - seconds)
        decision = decide(Instance([previous]))
        assert decision.allowed == (seconds == 600)
        if decision.allowed:
            assert decision.identity == identity(2, previous.dagster_run.run_id)
    for seconds in (1799, 1800):
        records = [record(2, source="run-1", end=NOW.timestamp() - seconds), record(1)]
        decision = decide(Instance(records))
        assert decision.allowed == (seconds == 1800)
        if decision.allowed:
            assert decision.identity == identity(3, "run-2")
    records.insert(0, record(3, source="run-2"))
    assert decide(Instance(records)).reason_code == "automatic_attempts_exhausted"


@pytest.mark.parametrize(
    "status",
    [
        s
        for s in dg.DagsterRunStatus
        if s
        not in {
            dg.DagsterRunStatus.SUCCESS,
            dg.DagsterRunStatus.FAILURE,
            dg.DagsterRunStatus.CANCELED,
        }
    ],
)
def test_every_active_status_blocks_even_manual_other_partition(status):
    active = record(manual=True, status=status, day="2026-07-13")
    instance = Instance(active=[active])
    assert decide(instance).reason_code == "active_run"
    assert len(instance.calls) == 1


@pytest.mark.parametrize(
    "records,reason",
    [
        ([record(status=dg.DagsterRunStatus.SUCCESS)], "success_file_missing"),
        (
            [record(manual=True, run_id="manual"), record()],
            "manual_failure_requires_review",
        ),
        (
            [record(manual=True, status=dg.DagsterRunStatus.CANCELED), record()],
            "canceled_requires_review",
        ),
        ([record(2, source="not-real"), record()], "recovery_identity_invalid"),
        ([record(2, source="run-1")], "recovery_identity_invalid"),
        ([record(), record()], "recovery_identity_invalid"),
    ],
)
def test_bad_history_stops(records, reason):
    assert decide(Instance(records)).reason_code == reason


def test_overflow_no_read_past_21_and_unavailable_evidence_stops():
    instance = Instance([record(manual=True)] * 21)
    assert decide(instance).reason_code == "run_history_truncated"
    assert [limit for _, limit in instance.calls] == [2, 21]
    instance.get_run_records = lambda **_: (_ for _ in ()).throw(
        RuntimeError("DB unavailable")
    )
    assert decide(instance).reason_code == "run_evidence_unavailable"


@pytest.mark.parametrize(
    "end", [float("nan"), float("inf"), "time", NOW.timestamp() + 1]
)
def test_invalid_end_time_stops(end):
    assert decide(Instance([record(end=end)])).reason_code == "failure_end_time_invalid"


def test_missing_end_time_stops():
    old = record()
    old.end_time = None
    assert decide(Instance([old])).reason_code == "failure_end_time_invalid"


@pytest.mark.parametrize(
    "field,value",
    [
        ("failure_policy_version", "old"),
        ("reason_code", "unknown"),
        ("request_retryable", False),
        ("partition_retryable", False),
        ("partition_retryable", 1),
        ("failed_count", True),
        ("request_count", None),
        ("request_count", -1),
        ("unattempted_count", 1),
        ("budget_exceeded", True),
        ("budget_reason", "budget"),
        ("failure_samples", ["X"] * 21),
        ("failure_samples", []),
        ("retry_count", 5),
    ],
)
def test_failure_metadata_requires_complete_typed_consistent_facts(field, value):
    metadata = FACTS.metadata()
    metadata[field] = value
    assert not decide(Instance([record()], [event(metadata)])).allowed


def test_legacy_missing_metadata_other_failed_step_and_truncated_events_stop():
    for events in (
        [],
        [event({})],
        [event(), event(step="raw_tushare_dc_member_core_check")],
        [event()] * 21,
    ):
        assert not decide(Instance([record(legacy=True)], events)).allowed
    instance = Instance([record()])
    instance.has_more = True
    assert not decide(instance).allowed
    # Legacy evidence remains immutable; lack of config alone is not retry authority.
    assert (
        decide(Instance([record(legacy=True)], [event()])).reason_code
        == "legacy_requires_review"
    )


def test_repeated_decisions_cursor_loss_cross_day_never_reset_quota():
    instance = Instance([record()])
    assert (
        decide(instance).identity == decide(instance).identity == identity(2, "run-1")
    )
    later = dc_recovery_decision(
        instance, job_name=JOB, trade_date=DAY, now=NOW + timedelta(days=1)
    )
    assert later.identity == identity(2, "run-1")


def test_silver_failure_active_and_success_missing_never_retry():
    for status in (
        dg.DagsterRunStatus.FAILURE,
        dg.DagsterRunStatus.CANCELED,
        dg.DagsterRunStatus.SUCCESS,
    ):
        instance = Instance([record(manual=True, status=status)])
        assert not decide(instance, allow_recovery=False).allowed
    assert decide(Instance(), allow_recovery=False).allowed


@pytest.mark.parametrize(
    "changed",
    ["key", "sensor", "origin", "parent", "source", "attempt", "partition", "job"],
)
def test_asset_rechecks_native_provenance_before_source(changed):
    current = record(2, source="run-1", status=dg.DagsterRunStatus.STARTED)
    run = current.dagster_run
    if changed == "key":
        run.tags[RUN_KEY_TAG] = "copied-key"
    if changed == "sensor":
        run.tags[SENSOR_NAME_TAG] = "manual"
    if changed == "origin":
        run.remote_job_origin = None
    if changed == "parent":
        run.parent_run_id = "parent"
    if changed == "partition":
        run.tags[PARTITION_NAME_TAG] = "2026-07-15"
    if changed == "job":
        run.job_name = "other"
    if changed == "source":
        run.run_config["ops"][ASSET]["config"]["recovery_identity"][
            "source_failure_run_id"
        ] = "wrong"
    if changed == "attempt":
        run.run_config["ops"][ASSET]["config"]["recovery_identity"][
            "automatic_attempt"
        ] = 3
    context = NS(
        run=run,
        partition_key=DAY,
        instance=Instance([current, record()], active=[current]),
    )
    with pytest.raises(ValueError):
        validate_dc_running_identity(
            context, identity(2, "run-1"), asset_name=ASSET, now=NOW
        )


def test_asset_accepts_current_automatic_chain_and_manual_no_identity():
    current = record(2, source="run-1", status=dg.DagsterRunStatus.STARTED)
    context = NS(
        run=current.dagster_run,
        partition_key=DAY,
        instance=Instance([current, record()], active=[current]),
    )
    validate_dc_running_identity(
        context, identity(2, "run-1"), asset_name=ASSET, now=NOW
    )
    with pytest.raises(ValueError):
        validate_dc_running_identity(context, None, asset_name=ASSET, now=NOW)
    context.run = record(manual=True).dagster_run
    validate_dc_running_identity(context, None, asset_name=ASSET, now=NOW)


def test_full_failure_aggregation_does_not_trust_20_sample_rows():
    transient = TushareCodeFailure(
        "BK1615.DC", "source_response_unclassified", "secret", 4, True
    )
    deterministic = TushareCodeFailure(
        "BK9999.DC", "non_retryable", "permission", 1, False
    )
    result = NS(
        failed_codes=(transient,) * 20 + (deterministic,),
        unattempted_codes=(),
        budget_exceeded=False,
        budget_reason=None,
        request_count=81,
        retry_count=60,
    )
    facts = request_failure_facts(result)
    assert facts.failed_count == 21 and len(facts.failure_samples) == 20
    assert not facts.partition_retryable and not facts.request_retryable
    assert "secret" not in str(facts.metadata()) and "permission" not in str(
        facts.metadata()
    )
    result.failed_codes = (transient,)
    for budget, unattempted in ((True, ()), (False, ("BK0001.DC",))):
        result.budget_exceeded = budget
        result.unattempted_codes = unattempted
        assert not request_failure_facts(result).partition_retryable


def test_no_fields_retry_has_exact_4_call_bound_and_1_2_4_backoff():
    calls, waits = [], []

    def request(code):
        calls.append(code)
        raise TushareResponseError("no fields")

    result = execute_bounded_code_requests(
        codes=["BK1615.DC"],
        request=request,
        extract_rows=lambda response: response,
        policy=TushareRequestPolicy(minimum_interval_seconds=0),
        clock=lambda: 0,
        sleep_fn=waits.append,
    )
    assert len(calls) == 4 and waits == [1, 2, 4]
    facts = request_failure_facts(result)
    assert (
        facts.partition_retryable
        and facts.request_count == 4
        and facts.retry_count == 3
    )


def test_actual_raw_asset_failure_event_roundtrip_in_ephemeral_instance(
    monkeypatch, tmp_path
):
    from orchestrator.defs.assets import dc_board_raw
    from orchestrator.defs.resources import LakeRootResource

    # Hardcoded fakes and patched writer prevent resource initialization, source or file access.
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    seen = []

    def writer(**kwargs):
        seen.append(kwargs["source_snapshot_config"])
        raise DcBoardRequestFailure(FACTS)

    monkeypatch.setattr(dc_board_raw, "write_dc_member_partition", writer)
    monkeypatch.setattr(
        dc_board_raw, "plan_dc_member_candidate_codes", lambda **_: ("BK1615.DC",)
    )
    proof = source_proof(_completion(), _source_result()).model_copy(
        update={"target_asset": ASSET}
    )
    resources = {
        key: dg.ResourceDefinition.hardcoded_resource(object())
        for key in ("duckdb", "tushare", "prod_postgres")
    }
    resources["lake_root"] = LakeRootResource(root_path=str(tmp_path))
    job = dg.define_asset_job(
        JOB, selection=dg.AssetSelection.assets(dc_board_raw.raw_tushare_dc_member)
    )
    definitions = dg.Definitions(
        assets=[
            dc_board_raw.raw_tushare_dc_member,
            dg.AssetSpec("raw_tushare_dc_index"),
        ],
        jobs=[job],
        resources=resources,
    )
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions("cn_a_dc_member_trade_days", [DAY])
        result = definitions.resolve_job_def(JOB).execute_in_process(
            instance=instance,
            partition_key=DAY,
            run_config=build_raw_dc_board_update_job_run_config(
                asset_name=ASSET, partition_key=DAY, proof=proof
            ),
            raise_on_error=False,
        )
        assert not result.success and seen == [proof]
        stored = instance.get_run_records(
            dg.RunsFilter(run_ids=[result.run_id]), limit=1
        )[0]
        assert retryable_dc_failure(instance, stored, asset_name=ASSET)
        events = instance.get_records_for_run(
            result.run_id, of_type=dg.DagsterEventType.STEP_FAILURE, limit=21
        )
        failure = events.records[0].event_log_entry.dagster_event.step_failure_data
        assert {
            key: value.value
            for key, value in failure.user_failure_data.metadata.items()
        } == FACTS.metadata()
        assert failure.error.cause is not None
        assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("missing", list(FACTS.metadata()))
def test_any_missing_failure_field_requires_review(missing):
    metadata = FACTS.metadata()
    del metadata[missing]
    assert not decide(Instance([record()], [event(metadata)])).allowed


@pytest.mark.parametrize(
    "error",
    [
        ValueError("503 timeout"),
        TypeError("429"),
        PermissionError("timeout"),
        OSError("local disk timeout"),
        FileNotFoundError("503"),
        Exception("权限不足 429"),
        Exception("invalid parameter timeout"),
    ],
)
def test_deterministic_contract_permission_and_local_errors_never_request_retry(error):
    from orchestrator.defs.tushare_request_policy import classify_tushare_error

    # Category records whether the actual failure is contract, permission or unknown.
    category, retryable = classify_tushare_error(error)
    assert not retryable
    if isinstance(error, (ValueError, TypeError)):
        assert category == "source_or_data_contract"
    elif isinstance(error, (PermissionError, FileNotFoundError, OSError)):
        assert category == "non_retryable"
    else:
        assert category == "source_permission_or_parameter"


@pytest.mark.parametrize(
    "between", [record(manual=True, run_id="manual-between"), record(legacy=True)]
)
def test_forged_history_cannot_jump_manual_or_legacy_failure(between):
    records = [record(2, source="run-1"), between]
    if not between.dagster_run.tags.get(RUN_KEY_TAG):
        records.append(record())
    assert not decide(Instance(records)).allowed


def test_full_automatic_chain_with_real_stored_runs_failures_and_bounded_queries(
    monkeypatch, tmp_path
):
    import sys

    from dagster._core.definitions.job_base import InMemoryJob
    from dagster._core.execution.api import execute_run
    from dagster._core.remote_origin import (
        InProcessCodeLocationOrigin,
        RemoteRepositoryOrigin,
    )
    from dagster._core.types.loadable_target_origin import LoadableTargetOrigin

    from orchestrator.defs.assets import dc_board_raw
    from orchestrator.defs.resources import LakeRootResource

    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    executed = []

    def writer(**kwargs):
        executed.append(kwargs["source_snapshot_config"])
        raise DcBoardRequestFailure(FACTS)

    monkeypatch.setattr(dc_board_raw, "write_dc_member_partition", writer)
    monkeypatch.setattr(
        dc_board_raw, "plan_dc_member_candidate_codes", lambda **_: ("BK1615.DC",)
    )
    resources = {
        key: dg.ResourceDefinition.hardcoded_resource(object())
        for key in ("duckdb", "tushare", "prod_postgres")
    }
    resources["lake_root"] = LakeRootResource(root_path=str(tmp_path))
    job = dg.define_asset_job(
        JOB,
        selection=dg.AssetSelection.assets(dc_board_raw.raw_tushare_dc_member),
        executor_def=dg.in_process_executor,
    )
    definitions = dg.Definitions(
        assets=[
            dc_board_raw.raw_tushare_dc_member,
            dg.AssetSpec("raw_tushare_dc_index"),
        ],
        jobs=[job],
        resources=resources,
    )
    resolved = definitions.resolve_job_def(JOB)
    origin = RemoteRepositoryOrigin(
        InProcessCodeLocationOrigin(
            LoadableTargetOrigin(
                executable_path=sys.executable,
                module_name="tests.test_dc_board_run_recovery",
            )
        ),
        "isolated_dc_test",
    ).get_job_origin(JOB)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions("cn_a_dc_member_trade_days", [DAY])
        moment = datetime.now(UTC)
        decision = dc_recovery_decision(
            instance, job_name=JOB, trade_date=DAY, now=moment
        )
        for attempt in (1, 2, 3):
            assert decision.identity.automatic_attempt == attempt
            proof = source_proof(_completion(), _source_result(), ASSET)
            config = build_raw_dc_board_update_job_run_config(
                asset_name=ASSET,
                partition_key=DAY,
                proof=proof,
                recovery_identity=decision.identity,
            )
            run = instance.create_run_for_job(
                resolved,
                run_config=config,
                remote_job_origin=origin,
                tags={
                    PARTITION_NAME_TAG: DAY,
                    RUN_KEY_TAG: expected_dc_run_key(JOB, DAY, attempt),
                    SENSOR_NAME_TAG: JOB + "_sensor",
                },
            )
            # Advance only the injected recovery clock; never sleep or change stored facts.
            monkeypatch.setattr(
                dc_board_raw, "datetime", NS(now=lambda _, moment=moment: moment)
            )
            result = execute_run(InMemoryJob(resolved), run, instance)
            assert not result.success
            stored = instance.get_run_records(
                dg.RunsFilter(run_ids=[run.run_id]), limit=1
            )[0]
            assert retryable_dc_failure(instance, stored, asset_name=ASSET)
            before = datetime.fromtimestamp(stored.end_time, UTC)
            if attempt < 3:
                cooldown = (600, 1800)[attempt - 1]
                assert (
                    dc_recovery_decision(
                        instance,
                        job_name=JOB,
                        trade_date=DAY,
                        now=before + timedelta(seconds=cooldown - 1),
                    ).reason_code
                    == "recovery_cooldown"
                )
                moment = before + timedelta(seconds=cooldown)
                decision = dc_recovery_decision(
                    instance, job_name=JOB, trade_date=DAY, now=moment
                )
                assert decision.identity.source_failure_run_id == run.run_id
        assert (
            dc_recovery_decision(
                instance, job_name=JOB, trade_date=DAY, now=moment + timedelta(days=1)
            ).reason_code
            == "automatic_attempts_exhausted"
        )
        assert len(executed) == 3 and not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "asset", ["raw_tushare_dc_index", "raw_tushare_dc_member", "raw_tushare_dc_daily"]
)
def test_all_raw_boundaries_reject_copied_automatic_config_before_source(
    monkeypatch, asset
):
    from orchestrator.defs.assets import dc_board_raw

    proof = source_proof(_completion(), _source_result(), asset)
    config = DcBoardRawRunConfig(source_proof=proof, recovery_identity=identity())
    context = NS(
        run=record(manual=True).dagster_run, partition_key=DAY, instance=Instance()
    )
    accessed = []
    with pytest.raises(dg.Failure) as failure, dc_board_raw._raw_execution_boundary(context, config, asset_name=asset):
        accessed.append(True)
    assert not accessed and failure.value.metadata["partition_retryable"].value is False
    assert failure.value.__cause__ is not None


def test_member_failed_request_retains_actual_source_statistics_and_does_not_promote(
    monkeypatch, tmp_path
):
    from orchestrator.defs.assets import dc_board
    from orchestrator.defs.paths import raw_dc_member_path
    from tests.test_dc_board_raw_io import _MemoryDuckDB
    from tests.test_dc_board_source_freeze import observation

    observed = observation()
    monkeypatch.setattr(dc_board, "revalidate_dc_board_source", lambda **_: observed)

    class Source:
        def call(self, *args):
            raise TushareResponseError("no fields")

    target = raw_dc_member_path(tmp_path, DAY)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"untouched previous target")
    with pytest.raises(DcBoardRequestFailure) as failure:
        dc_board.write_dc_member_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            tushare=Source(),
            prod_postgres=object(),
            partition_key=DAY,
            candidate_codes=("BK1615.DC",),
            source_snapshot_config=source_proof(_completion(), _source_result(), ASSET),
            policy=TushareRequestPolicy(minimum_interval_seconds=0, max_retries=0),
        )
    facts = failure.value.facts
    assert facts.partition_retryable and facts.failed_count == 1
    assert facts.request_count == observed.source.request_count + 1
    assert facts.retry_count == observed.source.retry_count
    assert target.read_bytes() == b"untouched previous target"


def test_probe_to_freeze_preserves_typed_failure_without_parsing_messages(
    monkeypatch, tmp_path
):
    from orchestrator.defs.asset_guards import dc_board_source_freeze as freeze
    from orchestrator.defs.asset_guards.dc_board_source_probe import (
        load_tushare_dc_index_daily_source_snapshot,
    )
    from tests.dc_board_quote_test_support import prod_result

    class Source:
        def call(self, *args):
            raise TushareResponseError("no fields")

    source = load_tushare_dc_index_daily_source_snapshot(
        tushare=Source(),
        trade_date=DAY,
        prod_completion=_completion(),
        policy=TushareRequestPolicy(minimum_interval_seconds=0, max_retries=0),
    )
    assert not source.ready and source.failure_facts.partition_retryable
    assert source.failure_facts.failed_count == source.request_count == 3
    monkeypatch.setattr(
        freeze,
        "load_prod_dc_board_reference_snapshot",
        lambda **_: prod_result(_completion()),
    )
    monkeypatch.setattr(
        freeze, "load_tushare_dc_index_daily_source_snapshot", lambda **_: source
    )
    with pytest.raises(DcBoardRequestFailure) as failure:
        freeze.observe_dc_board_source(
            lake_root=tmp_path,
            duckdb_resource=object(),
            prod_postgres=object(),
            tushare=Source(),
            trade_date=DAY,
        )
    assert failure.value.facts == source.failure_facts


def test_known_requests_transport_types_remain_retryable_without_message_guessing():
    from requests import exceptions as request_errors

    from orchestrator.defs.tushare_request_policy import classify_tushare_error
    for error in (request_errors.ConnectionError("opaque"), request_errors.Timeout("opaque")):
        assert classify_tushare_error(error) == ("transient", True)
    assert classify_tushare_error(OSError("opaque")) == ("non_retryable", False)
