"""Isolated history publication, real ephemeral event identities and failures."""

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg
import pytest

from orchestrator.defs.asset_guards.daily_basic_readiness import (
    batch_daily_basic_readiness,
)
from orchestrator.defs.bootstrap import daily_basic_events as events
from orchestrator.defs.bootstrap import daily_basic_history as history
from orchestrator.defs.checks.daily_basic_checks import daily_basic_check_result
from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_ASSET,
    DAILY_BASIC_CHECKS,
    DAILY_BASIC_PARTITIONS,
)
from orchestrator.defs.daily_basic_raw_io import (
    audit_daily_basic_coverage,
    audit_daily_basic_file,
)
from orchestrator.defs.paths import raw_daily_basic_path
from tests import test_daily_basic_history as history_tests
from tests.test_daily_basic_history import Source, rows
from tests.test_daily_basic_raw_io import DB


@pytest.fixture
def publication(tmp_path):
    plan = history_tests.plan.__wrapped__(tmp_path)
    days = [(date(2025, 1, 2) + timedelta(days=n)).isoformat() for n in range(21)]
    plan = history.seal_history_report(
        {**plan, "dates": days, "start": days[0], "end": days[-1]}
    )
    values = [("000001.SZ", day.replace("-", ""), *rows()[0][2:]) for day in days]
    history.export_daily_basic_history(plan, Source(values), apply=True)
    history.build_daily_basic_history(plan, apply=True)
    audit = history.audit_daily_basic_history(plan)
    promote = history.promote_daily_basic_history(plan, audit, apply=True)
    return plan, audit, promote


def test_plan_register_sample_all_idempotence_and_history_readiness(publication):
    plan, _, _ = publication
    with dg.DagsterInstance.ephemeral() as instance, DB().connect() as connection:
        initial = events.plan_daily_basic_events(instance, connection, *publication)
        assert len(initial["pending_materializations"]) == 21
        assert len(initial["pending_checks"]) == 40
        assert len(initial["missing_registered_dates"]) == 21
        assert instance.get_dynamic_partitions(DAILY_BASIC_PARTITIONS) == []
        assert (
            instance.get_materialized_partitions(dg.AssetKey(DAILY_BASIC_ASSET))
            == set()
        )
        with pytest.raises(ValueError, match="apply_required"):
            events.apply_daily_basic_events(
                instance, connection, *publication, initial, stage="register"
            )
        events.apply_daily_basic_events(
            instance, connection, *publication, initial, stage="register", apply=True
        )
        current = events.plan_daily_basic_events(instance, connection, *publication)
        assert (
            events.apply_daily_basic_events(
                instance,
                connection,
                *publication,
                current,
                stage="register",
                apply=True,
            )["registered_count"]
            == 0
        )
        sample = events.apply_daily_basic_events(
            instance,
            connection,
            *publication,
            current,
            stage="report-events",
            apply=True,
            sample_date=plan["dates"][-1],
        )
        assert sample["event_count"] == 3
        current = events.plan_daily_basic_events(instance, connection, *publication)
        assert len(current["pending_checks"]) == 38
        result = events.apply_daily_basic_events(
            instance,
            connection,
            *publication,
            current,
            stage="report-events",
            apply=True,
        )
        assert result["event_count"] == 58
        current = events.plan_daily_basic_events(instance, connection, *publication)
        assert not current["pending_materializations"] and not current["pending_checks"]
        assert (
            events.apply_daily_basic_events(
                instance,
                connection,
                *publication,
                current,
                stage="report-events",
                apply=True,
            )["event_count"]
            == 0
        )
        with patch(
            "orchestrator.defs.asset_guards.daily_basic_readiness.load_daily_basic_input_codes",
            side_effect=AssertionError("historical stock raw must not be read"),
        ):
            result = batch_daily_basic_readiness(
                instance,
                connection,
                Path(plan["lake_root"]),
                [plan["dates"][0], plan["dates"][-1]],
            )
            assert not result[plan["dates"][0]].ready
            assert result[plan["dates"][-1]].ready
        context = SimpleNamespace(
            instance=instance,
            partition_key=plan["dates"][-1],
            run=SimpleNamespace(
                asset_selection=set(), run_id="check-only", step_keys_to_execute=None
            ),
        )
        with patch(
            "orchestrator.defs.checks.daily_basic_checks.load_daily_basic_input_codes",
            side_effect=AssertionError("no historical upstream"),
        ):
            assert daily_basic_check_result(
                context,
                SimpleNamespace(root=lambda: Path(plan["lake_root"])),
                DB(),
                coverage=True,
            ).passed


@pytest.mark.parametrize(
    "failure",
    ["file", "audit", "promote", "rows", "active", "check_only", "materialization"],
)
def test_plan_rejects_conflicts_without_writes(publication, failure):
    plan, audit, promote = publication
    with dg.DagsterInstance.ephemeral() as instance, DB().connect() as connection:
        day = plan["dates"][0]
        if failure == "file":
            raw_daily_basic_path(Path(plan["lake_root"]), day).write_bytes(b"broken")
        elif failure == "audit":
            audit = history.seal_history_report({**audit, "passed": False})
        elif failure == "promote":
            promote = history.seal_history_report(
                {**promote, "files": promote["files"][:-1]}
            )
        elif failure == "rows":
            audit = history.seal_history_report({**audit, "rows": 2})
        elif failure == "active":
            instance.create_run_for_job(
                dg.GraphDefinition(name="fixture").to_job(name=events.DAILY_BASIC_JOB)
            )
        elif failure == "check_only":
            instance.report_runless_asset_event(
                dg.AssetCheckEvaluation(
                    asset_key=dg.AssetKey(DAILY_BASIC_ASSET),
                    check_name=DAILY_BASIC_CHECKS[0],
                    partition=day,
                    passed=False,
                )
            )
        else:
            instance.report_runless_asset_event(
                dg.AssetMaterialization(asset_key=DAILY_BASIC_ASSET, partition=day)
            )
        with (
            patch.object(
                instance,
                "report_runless_asset_event",
                side_effect=AssertionError("plan must not write"),
            ),
            pytest.raises(ValueError),
        ):
            events.plan_daily_basic_events(instance, connection, plan, audit, promote)


def test_stale_expired_unregistered_and_outside_sample(publication):
    plan, _, _ = publication
    with dg.DagsterInstance.ephemeral() as instance, DB().connect() as connection:
        initial = events.plan_daily_basic_events(instance, connection, *publication)
        with pytest.raises(ValueError, match="missing_registered"):
            events.apply_daily_basic_events(
                instance,
                connection,
                *publication,
                initial,
                stage="report-events",
                apply=True,
            )
        with pytest.raises(ValueError, match="sample_outside"):
            events.apply_daily_basic_events(
                instance,
                connection,
                *publication,
                initial,
                stage="report-events",
                apply=True,
                sample_date=plan["dates"][0],
            )
        expired = history.seal_history_report(
            {**initial, "created_at": "2000-01-01T00:00:00+00:00"}
        )
        with pytest.raises(ValueError, match="expired"):
            events.apply_daily_basic_events(
                instance,
                connection,
                *publication,
                expired,
                stage="register",
                apply=True,
            )
        instance.add_dynamic_partitions(DAILY_BASIC_PARTITIONS, [plan["dates"][0]])
        with pytest.raises(ValueError, match="stale"):
            events.apply_daily_basic_events(
                instance,
                connection,
                *publication,
                initial,
                stage="register",
                apply=True,
            )


@pytest.mark.parametrize("fail_at", [3, 23])
def test_partial_api_failure_resumes_without_duplicate(publication, fail_at):
    with dg.DagsterInstance.ephemeral() as instance, DB().connect() as connection:
        instance.add_dynamic_partitions(DAILY_BASIC_PARTITIONS, publication[0]["dates"])
        initial = events.plan_daily_basic_events(instance, connection, *publication)
        original = instance.report_runless_asset_event
        calls = 0

        def fail(event):
            nonlocal calls
            calls += 1
            if calls == fail_at:
                raise RuntimeError("api failed")
            original(event)

        with (
            patch.object(instance, "report_runless_asset_event", side_effect=fail),
            pytest.raises(RuntimeError),
        ):
            events.apply_daily_basic_events(
                instance,
                connection,
                *publication,
                initial,
                stage="report-events",
                apply=True,
            )
        resumed = events.plan_daily_basic_events(instance, connection, *publication)
        assert len(resumed["pending_materializations"]) == max(0, 21 - (fail_at - 1))
        assert events.apply_daily_basic_events(
            instance,
            connection,
            *publication,
            resumed,
            stage="report-events",
            apply=True,
        )["event_count"] == 61 - (fail_at - 1)


@pytest.mark.parametrize(
    "field",
    [
        "delivery_method",
        "file_sha256",
        "source_row_count",
        "code_count",
        "trade_date",
        "history_export_fingerprint",
        "history_audit_fingerprint",
        "history_plan_fingerprint",
        "source_system",
    ],
)
def test_history_coverage_rejects_invalid_evidence(publication, field):
    plan, audit, _ = publication
    item = audit["files"][-1]
    evidence = events._history_evidence(plan, audit, item)
    path = raw_daily_basic_path(Path(plan["lake_root"]), item["date"])
    with DB().connect() as connection:
        checked = audit_daily_basic_file(connection, path, item["date"])
        assert not audit_daily_basic_coverage(path, checked, (), evidence)
        evidence[field] = "bad"
        assert audit_daily_basic_coverage(path, checked, (), evidence)


def test_no_full_history_checks_or_source_scan(publication):
    with (
        dg.DagsterInstance.ephemeral() as instance,
        DB().connect() as connection,
        patch.object(
            events, "audit_daily_basic_file", wraps=events.audit_daily_basic_file
        ) as audit,
    ):
        result = events.plan_daily_basic_events(instance, connection, *publication)
        assert audit.call_count == 20
        assert all(day in result["recent_dates"] for day, _ in result["pending_checks"])


def test_materialization_page_budget_and_cursor_fail_closed():
    instance = SimpleNamespace(
        fetch_materializations=lambda *a, **k: SimpleNamespace(
            records=[SimpleNamespace(partition_key="2025-01-02")],
            has_more=True,
            cursor=None,
        )
    )
    with pytest.raises(ValueError, match="event_cursor"):
        events._latest_materializations(instance, ["2025-01-02", "2025-01-03"])
    with (
        patch.object(events, "EVENT_RECORD_LIMIT", 0),
        pytest.raises(ValueError, match="event_read_budget"),
    ):
        events._latest_materializations(instance, ["2025-01-02"])


def test_cli_requires_explicit_write_before_instance_access():
    from orchestrator.defs.bootstrap import daily_basic_event_instance as adapter
    from orchestrator.defs.bootstrap.daily_basic_history_cli import (
        history_parser,
        run_history_cli,
    )

    for stage, extra in (
        ("register", []),
        ("report-events", []),
        ("plan-events", ["--apply"]),
        ("audit-events", ["--apply"]),
    ):
        args = history_parser().parse_args(
            [
                stage,
                "--plan",
                "/private/tmp/unused-plan.json",
                "--audit-report",
                "/private/tmp/unused-audit.json",
                "--promote-report",
                "/private/tmp/unused-promote.json",
                "--report",
                "/private/tmp/unused-output.json",
                *extra,
            ]
        )
        with (
            patch.object(
                adapter,
                "daily_basic_event_instance",
                side_effect=AssertionError("must not open instance"),
            ),
            pytest.raises(ValueError),
        ):
            run_history_cli(args)


def test_failed_existing_check_blocks(publication):
    with dg.DagsterInstance.ephemeral() as instance, DB().connect() as connection:
        plan = events.plan_daily_basic_events(instance, connection, *publication)
        events.apply_daily_basic_events(
            instance, connection, *publication, plan, stage="register", apply=True
        )
        plan = events.plan_daily_basic_events(instance, connection, *publication)
        day = plan["recent_dates"][-1]
        item = plan["files"][-1]
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=DAILY_BASIC_ASSET,
                partition=day,
                metadata=events.build_materialization_metadata(
                    extra_metadata=item["evidence"]
                ),
            )
        )
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(DAILY_BASIC_ASSET),
                check_name=DAILY_BASIC_CHECKS[0],
                partition=day,
                passed=False,
            )
        )
        with pytest.raises(ValueError, match="check_conflict"):
            events.plan_daily_basic_events(instance, connection, *publication)


def test_historical_file_change_invalidates_active_readiness(publication):
    with dg.DagsterInstance.ephemeral() as instance, DB().connect() as connection:
        instance.add_dynamic_partitions(DAILY_BASIC_PARTITIONS, publication[0]["dates"])
        plan = events.plan_daily_basic_events(instance, connection, *publication)
        day = plan["recent_dates"][-1]
        events.apply_daily_basic_events(
            instance,
            connection,
            *publication,
            plan,
            stage="report-events",
            apply=True,
            sample_date=day,
        )
        raw_daily_basic_path(Path(publication[0]["lake_root"]), day).write_bytes(
            b"broken"
        )
        assert not batch_daily_basic_readiness(
            instance, connection, Path(publication[0]["lake_root"]), [day]
        )[day].ready
