"""LLD7/32: real Parquet replacement, native Dagster checks and partial results.

Inputs use doc32/migration188 and the existing history producer. Old events use
the original runless API, including its real unique constraint. Only resources
and external connections are replaced; Dagster event/run storage is real SQLite.
"""

import fcntl
from contextlib import contextmanager, nullcontext
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg
import pytest
import yaml
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.asset_guards.daily_basic_readiness import (
    batch_daily_basic_readiness,
    current_daily_basic_check_records,
    delivery_metadata,
)
from orchestrator.defs.assets.daily_basic import raw_tushare_daily_basic
from orchestrator.defs.bootstrap import daily_basic_events as events
from orchestrator.defs.bootstrap import daily_basic_history as history
from orchestrator.defs.checks import daily_basic_checks as checks
from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_ASSET,
    DAILY_BASIC_CHECKS,
    DAILY_BASIC_FIELDS,
    DAILY_BASIC_JOB,
    DAILY_BASIC_PARTITIONS,
)
from orchestrator.defs.jobs.daily_basic_update import raw_tushare_daily_basic_update_job
from orchestrator.defs.paths import raw_daily_basic_path
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from tests.test_daily_basic_events import publication as initial_publication
from tests.test_daily_basic_history import Source, rows, source_evidence
from tests.test_daily_basic_limit_status import _seed_file
from tests.test_daily_basic_raw_io import DB

publication = initial_publication


@pytest.fixture
def replacement_events(request, tmp_path, monkeypatch):
    days = [
        (date(2024, 12, 2) + timedelta(days=n)).isoformat()
        for n in range(30)
        if (date(2024, 12, 2) + timedelta(days=n)).weekday() < 5
    ][-getattr(request, "param", 2) :]
    # Literal statuses: A=0; retained B and historical A=NULL. No lifecycle filter.
    values = sorted(
        (code, day.replace("-", ""), *rows()[0][2:-1], status)
        for day in days
        for code, status in [("000001.SZ", 0), ("201872.SZ", None), ("920964.BJ", None)]
    )
    lake = tmp_path / "lake"
    calendar = tmp_path / "calendar.parquet"
    calendar.write_bytes(b"frozen calendar identity; explicit SSE weekdays above")
    for day in days:
        _seed_file(
            raw_daily_basic_path(lake, day),
            [r[:-1] for r in values if r[1] == day.replace("-", "")],
            include_status=False,
        )
    plan = history.make_history_plan(
        start=days[0],
        end=days[-1],
        batch_id="replacement",
        lake_root=lake,
        staging_root=tmp_path / "staging",
        calendar_path=calendar,
        dates=days,
        source_evidence=source_evidence(),
        cost_evidence={},
        limits={
            "max_source_rows": 50000,
            "max_source_seconds": 60,
            "max_stage_seconds": 60,
            "max_spill_bytes": 100000000,
        },
        replace_existing=True,
    )
    assert not plan["stop_reasons"]
    source = Source(values)
    history.export_daily_basic_history(plan, source, apply=True)
    history.build_daily_basic_history(plan, apply=True)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(DAILY_BASIC_PARTITIONS, days)
        for day in days:
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=DAILY_BASIC_ASSET,
                    partition=day,
                    metadata=build_materialization_metadata(
                        uri=raw_daily_basic_path(lake, day),
                        row_count=3,
                        observed_columns=list(DAILY_BASIC_FIELDS[:-1]),
                        extra_metadata={
                            "file_sha256": events.file_sha256(
                                raw_daily_basic_path(lake, day)
                            ),
                            "delivery_method": "prod_history",
                            "source_system": "prod_raw_db",
                            "trade_date": day,
                            "source_row_count": 3,
                            "code_count": 3,
                            "history_plan_fingerprint": "a" * 64,
                            "history_export_fingerprint": "b" * 64,
                            "history_audit_fingerprint": "c" * 64,
                        },
                    ),
                )
            )
        original = events._latest_materializations(instance, days)
        # With 22 days: one checked historical date outside W, plus the last day.
        for day in sorted({days[1], days[-1]}):
            record = original[day]
            for name in DAILY_BASIC_CHECKS:
                instance.report_runless_asset_event(
                    dg.AssetCheckEvaluation(
                        asset_key=dg.AssetKey(DAILY_BASIC_ASSET),
                        check_name=name,
                        partition=day,
                        passed=True,
                        blocking=True,
                        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                            storage_id=record.storage_id,
                            run_id=record.event_log_entry.run_id,
                            timestamp=record.event_log_entry.timestamp,
                        ),
                    )
                )
        audit = history.audit_daily_basic_history(plan, instance=instance)
        definitions = dg.Definitions(
            assets=[
                dg.AssetSpec(
                    "raw_tushare_stock_daily",
                    partitions_def=dg.DynamicPartitionsDefinition(
                        name="cn_a_stock_trade_days"
                    ),
                ),
                raw_tushare_daily_basic,
            ],
            asset_checks=[
                checks.raw_tushare_daily_basic_file_contract_check,
                checks.raw_tushare_daily_basic_source_coverage_check,
            ],
            jobs=[raw_tushare_daily_basic_update_job],
            resources={
                "lake_root": LakeRootResource(root_path=str(lake)),
                "duckdb": DuckDBResource(),
                "tushare": TushareResource(token="unused"),
            },
        )
        monkeypatch.setattr("orchestrator.definitions.defs", lambda: definitions)
        monkeypatch.setattr(DuckDBResource, "connect", lambda self: DB().connect())

        def forbidden(*args, **kwargs):
            raise AssertionError(
                "checks must not download, write files or read Prod/upstream"
            )

        monkeypatch.setattr(TushareResource, "call", forbidden)
        monkeypatch.setattr(
            ProdPostgresResource, "connect_readonly_transaction", forbidden
        )
        monkeypatch.setattr(
            "orchestrator.defs.assets.daily_basic.write_daily_basic_partition",
            forbidden,
        )
        monkeypatch.setattr(checks, "load_daily_basic_input_codes", forbidden)
        yield SimpleNamespace(
            plan=plan,
            audit=audit,
            instance=instance,
            days=days,
            original=original,
            definitions=definitions,
            source=source,
        )


def promote(state, day=None):
    with patch.object(
        history,
        "audit_daily_basic_history",
        side_effect=AssertionError("no full re-audit"),
    ):
        return history.promote_daily_basic_history(
            state.plan, state.audit, apply=True, sample_date=day
        )


def event_plan(state, connection, published):
    return events.plan_daily_basic_events(
        state.instance, connection, state.plan, state.audit, published
    )


def apply_events(state, connection, published, approved=None, day=None):
    return events.apply_daily_basic_events(
        state.instance,
        connection,
        state.plan,
        state.audit,
        published,
        approved or event_plan(state, connection, published),
        stage="report-events",
        apply=True,
        sample_date=day,
    )


@pytest.mark.parametrize("replacement_events", [22], indirect=True)
def test_three_samples_then_remaining_keep_identity_and_one_run_per_date(
    replacement_events,
):
    s = replacement_events
    assert s.audit["replacement"]["check_dates"] == s.days[1:]
    parent = s.audit["fingerprint"]
    with DB().connect() as connection:
        for day, expected in [(s.days[0], 1), (s.days[1], 3), (s.days[-1], 3)]:
            published = promote(s, day)
            plan = event_plan(s, connection, published)
            assert [f["date"] for f in plan["files"]] == sorted(
                f["date"] for f in published["files"]
            )
            assert (
                apply_events(s, connection, published, plan, day)["event_count"]
                == expected
            )
            assert s.audit["fingerprint"] == parent
            for item in s.audit["files"]:
                if item["date"] not in {f["date"] for f in published["files"]}:
                    assert (
                        events.file_sha256(
                            raw_daily_basic_path(
                                Path(s.plan["lake_root"]), item["date"]
                            )
                        )
                        == item["old_sha256"]
                    )
        published = promote(s)
        assert (
            apply_events(s, connection, published)["event_count"] == 57
        )  # 64 total, seven in samples.
        complete = event_plan(s, connection, published)
        assert (
            not complete["pending_materializations"] and not complete["pending_checks"]
        )
        with patch(
            "dagster.JobDefinition.get_subset",
            side_effect=AssertionError("no pending checks"),
        ):
            assert apply_events(s, connection, published, complete)["event_count"] == 0
        latest = events._latest_materializations(s.instance, s.days)
        for day in s.days:
            assert latest[day].storage_id != s.original[day].storage_id
            assert delivery_metadata(latest[day])["observed_columns"] == list(
                DAILY_BASIC_FIELDS
            )
            current = current_daily_basic_check_records(s.instance, day)
            if day == s.days[0]:
                assert not any(current.values())
                continue
            assert all(events._check_identity(c, latest[day]) for c in current.values())
            assert {c.run_id for c in current.values()} == {
                next(iter(current.values())).run_id
            }
            assert all(
                events.asset_check_record_evaluation(c).partition == day
                for c in current.values()
            )
        runs = s.instance.get_runs()
        assert len(runs) == 21 and all(run.is_success for run in runs)
        assert (
            len(
                s.instance.fetch_materializations(
                    dg.AssetRecordsFilter(asset_key=dg.AssetKey(DAILY_BASIC_ASSET)),
                    limit=100,
                ).records
            )
            == 44
        )
        assert batch_daily_basic_readiness(
            s.instance, connection, Path(s.plan["lake_root"]), [s.days[-1]]
        )[s.days[-1]].ready
        assert s.source.calls == 2


def test_partial_materializations_replan_and_progress_do_not_restart(
    replacement_events, capsys
):
    s = replacement_events
    published = promote(s)
    original = s.instance.report_runless_asset_event
    writes = 0

    def interrupt(event):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError("interrupted after one materialization")
        return original(event)

    with DB().connect() as connection:
        approved = event_plan(s, connection, published)
        with (
            patch.object(s.instance, "report_runless_asset_event", interrupt),
            pytest.raises(RuntimeError),
        ):
            apply_events(s, connection, published, approved)
        resumed = event_plan(s, connection, published)
        assert resumed["pending_materializations"] == [s.days[1]]
        with pytest.raises(ValueError, match="event_plan_stale"):
            apply_events(s, connection, published, approved)
        assert apply_events(s, connection, published, resumed)["event_count"] == 5
        assert "confirmed=1 total=6" in capsys.readouterr().out
        assert not event_plan(s, connection, published)["pending_checks"]


@pytest.mark.parametrize("interruption", ["failure", "cancel"])
def test_one_successful_check_then_interruption_only_runs_remaining(
    replacement_events, interruption
):
    s = replacement_events
    published = promote(s)
    original = checks.daily_basic_check_result

    def interrupt(context, lake_root, duckdb, *, coverage):
        if coverage:
            if interruption == "cancel":
                raise KeyboardInterrupt()
            raise dg.Failure("interruption before a coverage result")
        return original(context, lake_root, duckdb, coverage=coverage)

    with DB().connect() as connection:
        with (
            patch.object(checks, "daily_basic_check_result", interrupt),
            pytest.raises(
                (ValueError, KeyboardInterrupt, dg.DagsterExecutionInterruptedError)
            ),
        ):
            apply_events(s, connection, published)
        run = s.instance.get_runs()[0]
        assert run.is_finished
        before = current_daily_basic_check_records(s.instance, s.days[0])
        completed = before[
            dg.AssetCheckKey(dg.AssetKey(DAILY_BASIC_ASSET), DAILY_BASIC_CHECKS[0])
        ]
        unfinished = before[
            dg.AssetCheckKey(dg.AssetKey(DAILY_BASIC_ASSET), DAILY_BASIC_CHECKS[1])
        ]
        assert completed.status.value == "SUCCEEDED"
        assert unfinished.status.value == "PLANNED"
        pending = event_plan(s, connection, published)
        assert [s.days[0], DAILY_BASIC_CHECKS[0]] not in pending["pending_checks"]
        assert [s.days[0], DAILY_BASIC_CHECKS[1]] in pending["pending_checks"]
        assert not pending["pending_materializations"]
        assert apply_events(s, connection, published, pending)["event_count"] == 3
        after = current_daily_basic_check_records(s.instance, s.days[0])
        assert after[completed.key].id == completed.id
        assert after[unfinished.key].run_id != completed.run_id
        assert not event_plan(s, connection, published)["pending_checks"]


def materializations_only(s, connection, published):
    with (
        patch(
            "dagster.JobDefinition.execute_in_process",
            side_effect=RuntimeError("before check run"),
        ),
        pytest.raises(RuntimeError),
    ):
        apply_events(s, connection, published)
    assert not event_plan(s, connection, published)["pending_materializations"]


def test_active_planned_check_blocks_then_terminal_run_can_resume(replacement_events):
    s = replacement_events
    published = promote(s)
    with DB().connect() as connection:
        materializations_only(s, connection, published)
        chosen = {
            dg.AssetCheckKey(dg.AssetKey(DAILY_BASIC_ASSET), DAILY_BASIC_CHECKS[1])
        }
        job = s.definitions.resolve_job_def(DAILY_BASIC_JOB).get_subset(
            asset_selection=set(), asset_check_selection=chosen
        )
        run = s.instance.create_run_for_job(
            job,
            tags={"dagster/partition": s.days[0]},
            status=dg.DagsterRunStatus.STARTED,
        )
        with pytest.raises(ValueError, match="history_active_run"):
            event_plan(s, connection, published)
        # Existing administrator action; the bootstrap must not auto-terminate it.
        s.instance.report_run_canceled(run)
        assert apply_events(s, connection, published)["event_count"] == 4


def test_failed_evaluation_remains_failed_and_stops_following_dates(replacement_events):
    s = replacement_events
    published = promote(s)
    original = checks.daily_basic_check_result

    def invalid(context, lake_root, duckdb, *, coverage):
        if coverage:
            return dg.AssetCheckResult(
                passed=False,
                severity=dg.AssetCheckSeverity.ERROR,
                metadata={"failed_rule_names": ["injected_check_failure"]},
            )
        return original(context, lake_root, duckdb, coverage=coverage)

    with DB().connect() as connection:
        with (
            patch.object(checks, "daily_basic_check_result", invalid),
            pytest.raises(ValueError, match="history_check_run_failed"),
        ):
            apply_events(s, connection, published)
        assert len(s.instance.get_runs()) == 1
        failed = current_daily_basic_check_records(s.instance, s.days[0])[
            dg.AssetCheckKey(dg.AssetKey(DAILY_BASIC_ASSET), DAILY_BASIC_CHECKS[1])
        ]
        assert failed.status.value == "FAILED"
        with pytest.raises(ValueError, match="history_check_conflict"):
            event_plan(s, connection, published)
        assert (
            current_daily_basic_check_records(s.instance, s.days[0])[failed.key].id
            == failed.id
        )


def test_native_checks_hold_the_existing_date_lock_without_nested_locking(
    replacement_events,
):
    s = replacement_events
    published = promote(s)
    original = checks.daily_basic_check_result
    calls = []

    def inspect(context, lake_root, duckdb, *, coverage):
        path = (
            Path(s.plan["staging_root"])
            / "daily_basic"
            / "locks"
            / f"{context.partition_key}.lock"
        )
        with path.open("a") as stream, pytest.raises(BlockingIOError):
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        calls.append((context.partition_key, coverage))
        return original(context, lake_root, duckdb, coverage=coverage)

    with (
        DB().connect() as connection,
        patch.object(checks, "daily_basic_check_result", inspect),
    ):
        assert apply_events(s, connection, published)["event_count"] == 6
    assert calls == [(day, coverage) for day in s.days for coverage in [False, True]]
    assert len(s.instance.get_runs()) == 2


def test_readonly_plan_and_busy_lock_preserve_all_old_events(replacement_events):
    s = replacement_events
    published = promote(s)
    with DB().connect() as connection:
        approved = event_plan(s, connection, published)
        assert approved["pending_materializations"] == s.days
        assert events._latest_materializations(s.instance, s.days) == s.original
        assert not s.instance.get_runs()
        with (
            events._daily_basic_partition_lock(s.plan, s.days[0]),
            pytest.raises(ValueError, match="partition_locked"),
        ):
            apply_events(s, connection, published, approved)
        assert events._latest_materializations(s.instance, s.days) == s.original
        assert apply_events(s, connection, published, approved)["event_count"] == 6


def test_cli_report_failure_keeps_committed_checks_and_resumes_without_run(
    replacement_events, tmp_path, monkeypatch
):
    from orchestrator.defs.bootstrap import daily_basic_event_instance as adapter
    from orchestrator.defs.bootstrap import daily_basic_history_cli as cli

    s = replacement_events
    published = promote(s)
    with DB().connect() as connection:
        approved = event_plan(s, connection, published)
    inputs = {}
    for name, value in [
        ("plan", s.plan),
        ("audit", s.audit),
        ("promote", published),
        ("events", approved),
    ]:
        inputs[name] = tmp_path / f"saved-{name}.json"
        history.save_history_report(inputs[name], value)

    @contextmanager
    def instance(*, writable=False, for_execution=False):
        assert writable and for_execution
        yield s.instance

    monkeypatch.setattr(adapter, "daily_basic_event_instance", instance)
    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", s.plan["lake_root"])
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", s.plan["staging_root"])
    monkeypatch.setattr(cli, "_event_apply_lock", nullcontext)
    monkeypatch.setattr(
        cli, "connect_configured_duckdb", lambda *a, **k: DB().connect()
    )
    args = cli.history_parser().parse_args(
        [
            "report-events",
            "--apply",
            "--plan",
            str(inputs["plan"]),
            "--audit-report",
            str(inputs["audit"]),
            "--promote-report",
            str(inputs["promote"]),
            "--event-plan",
            str(inputs["events"]),
            "--fingerprint",
            approved["fingerprint"],
            "--report",
            str(tmp_path / "result.json"),
        ]
    )
    with (
        patch.object(
            cli, "save_history_report", side_effect=OSError("report write failed")
        ),
        pytest.raises(OSError),
    ):
        cli.run_history_cli(args)
    assert len(s.instance.get_runs()) == 2
    with DB().connect() as connection:
        resumed = event_plan(s, connection, published)
        assert not resumed["pending_checks"] and not resumed["pending_materializations"]
    history.save_history_report(inputs["events"], resumed)
    args.fingerprint = resumed["fingerprint"]
    assert cli.run_history_cli(args)["event_count"] == 0
    assert len(s.instance.get_runs()) == 2


def test_execution_adapter_constructs_a_persistent_instance_for_native_checks(
    replacement_events, tmp_path, monkeypatch
):
    from dagster._core.storage.event_log.sqlite.sqlite_event_log import (
        SqliteEventLogStorage,
    )
    from dagster._core.storage.runs.sqlite.sqlite_run_storage import SqliteRunStorage

    from orchestrator.defs.bootstrap import daily_basic_event_instance as adapter

    s = replacement_events
    promote(s)
    home = tmp_path / "instance-home"
    home.mkdir()
    (home / "dagster.yaml").write_text(
        yaml.safe_dump(
            {
                "storage": {
                    "postgres": {
                        "postgres_db": {
                            "hostname": "localhost",
                            "username": "fixture",
                            "password": "fixture",
                            "db_name": "goldenshare_dagster",
                            "port": 5432,
                        }
                    }
                },
                "local_artifact_storage": {
                    "module": "dagster._core.storage.root",
                    "class": "LocalArtifactStorage",
                    "config": {"base_dir": str(home)},
                },
                "run_coordinator": {
                    "module": "dagster._core.run_coordinator",
                    "class": "QueuedRunCoordinator",
                    "config": {},
                },
                "telemetry": {"enabled": False},
            }
        )
    )
    # Only PG storage construction is substituted; the adapter/InstanceRef are real.
    event_store = SqliteEventLogStorage(str(tmp_path / "event-storage"))
    run_store = SqliteRunStorage.from_local(str(tmp_path / "run-storage"))
    monkeypatch.setattr(adapter, "INSTANCE_HOME", home)
    monkeypatch.setattr(adapter, "PostgresEventLogStorage", lambda *a, **k: event_store)
    monkeypatch.setattr(adapter, "PostgresRunStorage", lambda *a, **k: run_store)
    day = s.days[-1]
    item = next(item for item in s.audit["files"] if item["date"] == day)
    with adapter.daily_basic_event_instance(
        writable=True, for_execution=True
    ) as instance:
        assert instance.is_persistent
        assert type(instance.run_coordinator).__name__ == "QueuedRunCoordinator"
        instance.add_dynamic_partitions(DAILY_BASIC_PARTITIONS, [day])
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=DAILY_BASIC_ASSET,
                partition=day,
                metadata=build_materialization_metadata(
                    extra_metadata=events._history_evidence(s.plan, s.audit, item)
                ),
            )
        )
        selected = {
            dg.AssetCheckKey(dg.AssetKey(DAILY_BASIC_ASSET), name)
            for name in DAILY_BASIC_CHECKS
        }
        result = (
            s.definitions.resolve_job_def(DAILY_BASIC_JOB)
            .get_subset(asset_selection=set(), asset_check_selection=selected)
            .execute_in_process(instance=instance, partition_key=day)
        )
        assert result.success and len(result.get_asset_check_evaluations()) == 2
        target = events._latest_materializations(instance, [day])[day]
        assert all(
            events._check_identity(check, target)
            for check in current_daily_basic_check_records(instance, day).values()
        )
        assert len(instance.get_runs()) == 1


def test_default_import_stays_runless_and_sample_limit_unchanged(publication):
    with dg.DagsterInstance.ephemeral() as instance, DB().connect() as connection:
        approved = events.plan_daily_basic_events(instance, connection, *publication)
        events.apply_daily_basic_events(
            instance, connection, *publication, approved, stage="register", apply=True
        )
        approved = events.plan_daily_basic_events(instance, connection, *publication)
        with pytest.raises(ValueError, match="sample_outside_recent"):
            events.apply_daily_basic_events(
                instance,
                connection,
                *publication,
                approved,
                stage="report-events",
                apply=True,
                sample_date=publication[0]["dates"][0],
            )
        with patch(
            "dagster.JobDefinition.execute_in_process",
            side_effect=AssertionError("default stays runless"),
        ):
            assert (
                events.apply_daily_basic_events(
                    instance,
                    connection,
                    *publication,
                    approved,
                    stage="report-events",
                    apply=True,
                )["event_count"]
                == 61
            )
        assert instance.get_runs() == []


@pytest.mark.parametrize(
    "stage,replacing,expected",
    [
        ("plan-events", True, False),
        ("audit-events", True, False),
        ("register", True, False),
        ("report-events", True, True),
        ("report-events", False, False),
    ],
)
def test_cli_execution_mode_is_only_for_replacement_publication(
    replacement_events, tmp_path, monkeypatch, stage, replacing, expected
):
    from orchestrator.defs.bootstrap import daily_basic_event_instance as adapter
    from orchestrator.defs.bootstrap import daily_basic_history_cli as cli

    s = replacement_events
    published = promote(s)
    plan = history.seal_history_report({**s.plan, "replace_existing": replacing})
    inputs = {}
    for name, value in [
        ("plan", plan),
        ("audit", s.audit),
        ("promote", published),
        ("events", history.seal_history_report({"stage": "plan-events"})),
    ]:
        path = tmp_path / f"cli-{name}.json"
        history.save_history_report(path, value)
        inputs[name] = path
    modes = []

    @contextmanager
    def instance(*, writable=False, for_execution=False):
        modes.append((writable, for_execution))
        yield s.instance

    monkeypatch.setattr(adapter, "daily_basic_event_instance", instance)
    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", s.plan["lake_root"])
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", s.plan["staging_root"])
    monkeypatch.setattr(cli, "_event_apply_lock", nullcontext)
    monkeypatch.setattr(
        cli, "connect_configured_duckdb", lambda *a, **k: DB().connect()
    )
    # Only routing is isolated here; the tests above execute real native checks.
    monkeypatch.setattr(events, "apply_daily_basic_events", lambda *a, **k: {})
    monkeypatch.setattr(events, "plan_daily_basic_events", lambda *a, **k: {})
    args = cli.history_parser().parse_args(
        [
            stage,
            "--plan",
            str(inputs["plan"]),
            "--audit-report",
            str(inputs["audit"]),
            "--promote-report",
            str(inputs["promote"]),
            "--report",
            str(tmp_path / "cli-output.json"),
            *(
                [
                    "--apply",
                    "--event-plan",
                    str(inputs["events"]),
                    "--fingerprint",
                    history.load_history_report(inputs["events"])["fingerprint"],
                ]
                if stage in ("register", "report-events")
                else []
            ),
        ]
    )
    cli.run_history_cli(args)
    assert modes == [(stage in ("register", "report-events"), expected)]
    assert not s.instance.get_runs()
