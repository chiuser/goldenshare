"""Seven-date repair in temporary Lake/SQLite. Network is replaced, files/events are real."""

import copy
import csv
import io
import json
import shutil
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import moneyflow_history_supplement as engine
from orchestrator.defs.bootstrap import (
    moneyflow_history_supplement_control as controller,
)
from orchestrator.defs.bootstrap import moneyflow_history_supplement_events as events
from orchestrator.defs.bootstrap.moneyflow_history_candidates import (
    build_moneyflow_history_unit_candidates,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    MoneyflowHistoryDateCount,
    build_moneyflow_history_plan,
    history_schema,
)
from orchestrator.defs.bootstrap.moneyflow_history_receive import (
    history_candidate_connection,
)
from orchestrator.defs.bootstrap.moneyflow_history_supplement_control import (
    CONTRACTS,
    LIMITS,
    SCOPE,
    Control,
    Source,
    digest,
    file_hash,
    read_json,
    root_directory,
    save_json,
    target,
)
from orchestrator.defs.bootstrap.moneyflow_history_supplement_sensors import (
    NAMES,
    START,
    STOP,
    snapshot_body,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError


def row(dataset, day, code="000001.SZ", amount="-2.1250"):
    # Layout comes from the current historical producer contract; critical money
    # values/expected results below are independent literals, not merge output.
    value = {
        c.name: None if c.type == "VARCHAR" else "0" for c in history_schema(dataset)
    }
    value.update(trade_date=day, net_amount=amount)
    if "ts_code" in value:
        value["ts_code"] = code
    if "name" in value:
        value["name"] = '金样本,"\n'
    return value


def wire(dataset, rows):
    fields = [c.name for c in history_schema(dataset)]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fields)
    for value in rows:
        writer.writerow([r"\N" if value[k] is None else value[k] for k in fields])
    return buffer.getvalue().encode()


class FakeSource:
    def __init__(self, rows):
        self.rows, self.copies, self.metadata_calls = rows, [], []

    def copy(self, request, sink, check):
        assert "BEGIN READ ONLY" in request.sql()
        assert len(request.plan.units[request.unit_id].dates) == 1
        day = request.plan.units[request.unit_id].dates[0]
        self.copies.append((request.plan.dataset, day))
        payload = wire(request.plan.dataset, self.rows[request.plan.dataset, day])
        for start in range(0, len(payload), 31):
            check()
            sink.write(payload[start : start + 31])

    def metadata(self, request, sink, check):
        assert "BEGIN READ ONLY" in request.sql() and request.selected_dates
        self.metadata_calls.append((request.dataset, request.selected_dates))
        columns = [
            [
                c.name,
                "date"
                if c.name == "trade_date"
                else "text"
                if c.type == "VARCHAR"
                else c.type.lower().replace("decimal", "numeric"),
            ]
            for c in history_schema(request.dataset)
        ]
        facts = [
            {
                "trade_date": day,
                "scope": "",
                "rows": len(self.rows[request.dataset, day]),
                "keys": len(self.rows[request.dataset, day]),
                "invalid_keys": 0,
            }
            for day in request.selected_dates
        ]
        value = {
            "dataset": request.dataset,
            "cutoff": request.cutoff,
            "relation_kind": "r",
            "columns": columns,
            "facts": facts,
            "selected_dates": list(request.selected_dates),
        }
        check()
        sink.write(json.dumps(value).encode().hex().encode() + b"\n")


class FakeUpdates:
    def __init__(self):
        self.values = {
            name: {
                "id": "id-" + name,
                "status": "RUNNING" if i % 2 else "STOPPED",
                "cursor": "do-not-reset",
            }
            for i, name in enumerate(NAMES)
        }
        self.actions = []

    def snapshot(self):
        return copy.deepcopy(self.values)

    def set_status(self, name, identity, status):
        assert name in NAMES and identity == self.values[name]["id"]
        self.actions.append((name, status))
        self.values[name]["status"] = status


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(
        shutil, "disk_usage", lambda p: SimpleNamespace(free=128 * 1024**3)
    )
    lake, staging, home = (tmp_path / n for n in ("lake", "staging", "instance"))
    for p in (lake, staging, home):
        p.mkdir()
    values = {(d, day): [row(d, day)] for d, day, _ in SCOPE}
    day = "2026-05-19"
    old = [
        row("moneyflow_dc", day, "000001.SZ", "1.2500"),
        row("moneyflow_dc", day, "000002.SZ", None),
    ]
    values["moneyflow_dc", day] = [
        row("moneyflow_dc", day, "000001.SZ", "999"),
        row("moneyflow_dc", day, "000002.SZ", "666"),
        row("moneyflow_dc", day, "000003.SZ", "-2.1250"),
    ]
    baseline_source = FakeSource({("moneyflow_dc", day): old})
    p = build_moneyflow_history_plan(
        "moneyflow_dc", [MoneyflowHistoryDateCount(day, 2, 2)], cutoff="2026-09-30"
    )
    receipt = build_moneyflow_history_unit_candidates(
        p, 0, staging_root=staging, operation_id="baseline", source=baseline_source
    )
    base = (
        staging
        / "moneyflow/baseline/moneyflow_dc/2026-09-30/history_candidates/unit-000000"
        / receipt["attempt"]
        / day
    )
    with dg.DagsterInstance.local_temp(
        str(home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        for layer in ("raw", "silver"):
            path = target(lake, "moneyflow_dc", day, layer)
            path.parent.mkdir(parents=True)
            (base / (layer + ".parquet")).replace(path)
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=("raw_tushare_" if layer == "raw" else "silver_")
                    + "moneyflow_dc",
                    partition=day,
                    metadata=build_materialization_metadata(
                        uri=path,
                        row_count=2,
                        extra_metadata={
                            "file_sha256": file_hash(path),
                            "raw_sha256": file_hash(
                                target(lake, "moneyflow_dc", day, "raw")
                            ),
                        },
                    ),
                )
            )
        instance.add_dynamic_partitions(CONTRACTS["moneyflow_dc"].partition_set, [day])
        source, updates = FakeSource(values), FakeUpdates()
        expected = {
            (d, t): sorted(v["ts_code"] for v in values[d, t])
            if d != "moneyflow_mkt_dc"
            else [t]
            for d, t, _ in SCOPE
        }
        plan = engine.prepare_moneyflow_history_supplement(
            instance=instance,
            source=source,
            updates=updates,
            lake_root=lake,
            staging_root=staging,
            operation_id="test-seven",
            expected_keys=expected,
            source_evidence="isolated literal keys; schema=current Prod producer",
            scratch_root=tmp_path / "prepare",
        )
        yield SimpleNamespace(
            plan=plan,
            source=source,
            updates=updates,
            instance=instance,
            root=root_directory(staging, "test-seven"),
            lake=lake,
            staging=staging,
        )


def run(case, **kwargs):
    # Simulate the two explicit operator stages; no production bypass or mock
    # replaces candidate approval, publication, SQL, or native event storage.
    if kwargs.get("apply"):
        if not (case.root / "candidates.json").exists():
            engine.apply_moneyflow_history_supplement(
                case.plan,
                digest(case.plan),
                instance=case.instance,
                source=case.source,
                updates=case.updates,
                **{**kwargs, "sample_only": False, "publish": False},
            )
        kwargs.update(
            publish=True,
            expected_candidates_sha=digest(read_json(case.root / "candidates.json")),
        )
    return engine.apply_moneyflow_history_supplement(
        case.plan,
        digest(case.plan),
        instance=case.instance,
        source=case.source,
        updates=case.updates,
        **kwargs,
    )


def source_review(case, current_code):
    return {
        "revision": "moneyflow_supplement_code_review_v1",
        "plan_sha256": digest(case.plan),
        "prior_code_sha256": digest(case.plan["code"]),
        "candidates_sha256": digest(read_json(case.root / "candidates.json")),
        "code": current_code,
    }


def test_sample_code_review_resume_preserves_original_plan_candidates_and_budget(
    case, monkeypatch
):
    from orchestrator.defs.bootstrap.moneyflow_history_supplement_sensors import (
        transition,
    )

    for value in case.updates.values.values():
        value["status"] = "RUNNING"
    case.plan["sensors"] = case.updates.snapshot()
    assert run(case, apply=True, sample_only=True)["accepted"] == 1
    before_plan = file_hash(case.root / "plan.json")
    before_candidates = file_hash(case.root / "candidates.json")
    control = Control(case.plan, digest(case.plan), case.root)
    transition(case.updates, control, restore=True)
    control.state["stage"] = "waiting_for_shared_source_review_updates_restored"
    control.save()
    copies = list(case.source.copies)
    current = {**case.plan["code"], "reviewed-controller.py": "a" * 64}
    monkeypatch.setattr(controller, "code_identity", lambda: current)
    with pytest.raises(MoneyflowContractError, match="code_changed"):
        run(case, apply=True)
    review = source_review(case, current)
    args = {"source_review": review, "expected_source_review_sha": digest(review)}
    assert run(case, **args)["accepted"] == 1
    assert not (case.root / "source-review.json").exists()
    # A process may exit between saving the review and binding its state digest.
    save_json(case.root / "source-review.json", review)
    result = run(case, apply=True, **args)
    assert result["accepted"] == 7 and result["counts"]["reads"] < 340
    assert case.source.copies == copies and len(copies) == 14
    assert result["counts"]["materializations"] == result["counts"]["checks"] == 14
    assert file_hash(case.root / "plan.json") == before_plan
    assert file_hash(case.root / "candidates.json") == before_candidates
    assert read_json(case.root / "source-review.json") == review
    assert case.updates.snapshot() == case.plan["sensors"]
    state_hash = file_hash(case.root / "state.json")
    assert run(case, **args) == {
        "stage": "complete",
        "accepted": 7,
        "replay": True,
        "writes": 0,
    }
    assert file_hash(case.root / "state.json") == state_hash
    monkeypatch.setattr(controller, "code_identity", lambda: case.plan["code"])
    with pytest.raises(MoneyflowContractError, match="source_review_missing"):
        run(case)
    changed_review = {**review, "code": {**current, "new-code.py": "c" * 64}}
    monkeypatch.setattr(controller, "code_identity", lambda: changed_review["code"])
    with pytest.raises(MoneyflowContractError, match="saved_source_review_changed"):
        run(
            case,
            source_review=changed_review,
            expected_source_review_sha=digest(changed_review),
        )
    monkeypatch.setattr(controller, "code_identity", lambda: current)
    (case.root / "source-review.json").unlink()
    with pytest.raises(MoneyflowContractError, match="saved_source_review_missing"):
        run(case, **args)


@pytest.mark.parametrize(
    "fault", ["digest", "parent", "prior", "candidate", "code", "extra", "no_digest"]
)
def test_source_review_errors_refuse_before_writes(case, monkeypatch, fault):
    assert run(case, apply=True, sample_only=True)["accepted"] == 1
    current = {**case.plan["code"], "reviewed-controller.py": "b" * 64}
    monkeypatch.setattr(controller, "code_identity", lambda: current)
    review = source_review(case, current)
    if fault in {"parent", "prior", "candidate"}:
        review[
            {
                "parent": "plan_sha256",
                "prior": "prior_code_sha256",
                "candidate": "candidates_sha256",
            }[fault]
        ] = "0" * 64
    elif fault == "code":
        review["code"] = {}
    elif fault == "extra":
        review["force"] = True
    sha = (
        "0" * 64
        if fault == "digest"
        else None
        if fault == "no_digest"
        else digest(review)
    )
    before = file_hash(case.root / "state.json")
    actions = list(case.updates.actions)
    with pytest.raises(MoneyflowContractError):
        run(case, apply=True, source_review=review, expected_source_review_sha=sha)
    assert file_hash(case.root / "state.json") == before
    assert case.updates.actions == actions and len(case.source.copies) == 14


def test_readonly_then_full_sql_native_acceptance_and_zero_copy_replay(case):
    assert run(case)["writes"] == 0 and not case.root.exists()
    assert (
        len(case.source.metadata_calls) == 5
        and not case.source.copies
        and not case.updates.actions
    )
    result = run(case, apply=True)
    assert result["accepted"] == 7 and result["stage"] == "complete"
    assert result["counts"]["copies"] == 14 and result["counts"]["metadata"] == 10
    assert result["counts"]["connections"] == 24 and result["counts"]["partitions"] == 6
    assert result["counts"]["materializations"] == result["counts"]["checks"] == 14
    assert case.updates.snapshot() == case.plan["sensors"]
    assert (
        len(case.updates.actions) == 28
    )  # Seven initially running; no originally stopped item touched.
    with history_candidate_connection(case.staging, lambda: None) as db:
        for layer in ("raw", "silver"):
            values = db.execute(
                "SELECT ts_code,net_amount FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                [str(target(case.lake, "moneyflow_dc", "2026-05-19", layer))],
            ).fetchall()
            assert values == [
                ("000001.SZ", Decimal("1.2500")),
                ("000002.SZ", None),
                ("000003.SZ", Decimal("-2.1250")),
            ]
    before = {str(p): file_hash(p) for p in case.root.rglob("*") if p.is_file()}
    actions = list(case.updates.actions)
    assert run(case, apply=True) == {
        "stage": "complete",
        "accepted": 7,
        "replay": True,
        "writes": 0,
    }
    assert case.updates.actions == actions and len(case.source.copies) == 14
    assert {str(p): file_hash(p) for p in case.root.rglob("*") if p.is_file()} == before
    assert read_json(case.root / "state.json")["counts"]["reads"] < LIMITS["reads"]


def test_sample_then_resume_has_no_source_reread(case):
    assert run(case, apply=True, sample_only=True)["accepted"] == 1
    assert all(v["status"] == "STOPPED" for v in case.updates.snapshot().values())
    assert len(list(case.lake.rglob("*.parquet"))) == 4  # Existing DC + one new date.
    assert run(case, apply=True)["accepted"] == 7
    assert len(case.source.copies) == 14 and len(case.source.metadata_calls) == 10


def test_candidate_stage_does_not_publish_and_rejects_missing_or_wrong_approval(case):
    common = {
        "instance": case.instance,
        "source": case.source,
        "updates": case.updates,
        "apply": True,
    }
    with pytest.raises(MoneyflowContractError, match="candidate_approval_missing"):
        engine.apply_moneyflow_history_supplement(
            case.plan, digest(case.plan), publish=True, **common
        )
    assert (
        not case.root.exists() and not case.updates.actions and not case.source.copies
    )
    prepared = engine.apply_moneyflow_history_supplement(
        case.plan, digest(case.plan), **common
    )
    assert (
        prepared["stage"] == "candidates_ready_for_review" and prepared["accepted"] == 0
    )
    assert len(list(case.lake.rglob("*.parquet"))) == 2
    assert prepared["counts"]["materializations"] == prepared["counts"]["checks"] == 0
    assert case.updates.snapshot() == case.plan["sensors"]
    before = len(case.updates.actions)
    with pytest.raises(MoneyflowContractError, match="candidate_approval_changed"):
        engine.apply_moneyflow_history_supplement(
            case.plan,
            digest(case.plan),
            publish=True,
            expected_candidates_sha="0" * 64,
            **common,
        )
    assert len(case.updates.actions) == before and len(case.source.copies) == 14


@pytest.mark.parametrize(
    "mutation",
    ["scope", "digest", "keys", "code", "limit", "target", "sensor", "native"],
)
def test_plan_and_baseline_changes_refuse_without_copy_or_switch(case, mutation):
    sha = digest(case.plan)
    if mutation == "scope":
        case.plan["entries"][0]["day"] = "2026-07-10"
    elif mutation == "digest":
        sha = "0" * 64
    elif mutation == "keys":
        case.plan["entries"][0]["keys"] = []
    elif mutation == "code":
        case.plan["code"] = {}
    elif mutation == "limit":
        case.plan["limits"] = {**LIMITS, "copies": 99}
    elif mutation == "target":
        target(case.lake, "moneyflow_dc", "2026-05-19", "raw").write_bytes(b"changed")
    elif mutation == "sensor":
        case.updates.values[NAMES[0]]["cursor"] = "changed"
    else:
        case.instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key="raw_tushare_moneyflow_dc", partition="2026-05-19"
            )
        )
    if mutation not in {"digest", "target", "sensor", "native"}:
        sha = digest(case.plan)
    with pytest.raises(MoneyflowContractError):
        engine.apply_moneyflow_history_supplement(
            case.plan,
            sha,
            instance=case.instance,
            source=case.source,
            updates=case.updates,
            apply=True,
        )
    assert (
        not case.source.copies and not case.updates.actions and not case.root.exists()
    )


@pytest.mark.parametrize(
    "fault",
    ["wrong_date", "duplicate", "missing_key", "bad_decimal", "metadata_change"],
)
def test_bad_source_never_publishes_and_restores_switches(case, fault):
    dataset, day, _ = SCOPE[-1]
    if fault == "wrong_date":
        case.source.rows[dataset, day][0]["trade_date"] = "2026-05-20"
    elif fault == "duplicate":
        case.source.rows[dataset, day][1]["ts_code"] = "000001.SZ"
    elif fault == "missing_key":
        case.source.rows[dataset, day][2]["ts_code"] = "600999.SH"
    elif fault == "bad_decimal":
        case.source.rows[dataset, day][0]["net_amount"] = "not-money"
    else:
        case.source.rows[dataset, day].append(row(dataset, day, "600999.SH"))
    with pytest.raises(MoneyflowContractError):
        run(case, apply=True)
    assert len(list(case.lake.rglob("*.parquet"))) == 2
    assert case.updates.snapshot() == case.plan["sensors"]


@pytest.mark.parametrize("layer", ["raw", "silver"])
@pytest.mark.parametrize("dataset", ["moneyflow_mkt_dc", "moneyflow_dc"])
def test_publication_exit_resumes_from_intent_without_source_copy(
    case, monkeypatch, layer, dataset
):
    from orchestrator.defs.io import moneyflow_update_publication as publication

    original = publication._checkpoint
    fired = False

    def fail(path, value):
        nonlocal fired
        if (
            value["stage"] == "complete"
            and value["layer"] == layer
            and value["revision"] == dataset + "_daily_v1"
            and not fired
        ):
            fired = True
            raise OSError("exit after replace before checkpoint")
        original(path, value)

    monkeypatch.setattr(publication, "_checkpoint", fail)
    with pytest.raises(OSError, match="after replace"):
        run(case, apply=True)
    assert all(v["status"] == "STOPPED" for v in case.updates.snapshot().values())
    monkeypatch.setattr(publication, "_checkpoint", original)
    assert run(case, apply=True)["accepted"] == 7
    assert len(case.source.copies) == 14
    assert run(case, apply=True)["writes"] == 0


@pytest.mark.parametrize("after_commit", [True, False])
@pytest.mark.parametrize("event_kind", ["materialization", "check"])
def test_native_response_loss_reconciles_or_stops_uncertain(
    case, monkeypatch, after_commit, event_kind
):
    original = case.instance.report_runless_asset_event
    fired = False

    def fail(event):
        nonlocal fired
        relevant = isinstance(event, dg.AssetMaterialization) == (
            event_kind == "materialization"
        )
        if relevant and not fired:
            fired = True
            if after_commit:
                original(event)
            raise OSError("response lost")
        return original(event)

    monkeypatch.setattr(case.instance, "report_runless_asset_event", fail)
    with pytest.raises(OSError, match="response lost"):
        run(case, apply=True)
    monkeypatch.setattr(case.instance, "report_runless_asset_event", original)
    if after_commit:
        result = run(case, apply=True)
        assert (
            result["counts"]["materializations"] == 14
            and result["counts"]["checks"] == 14
        )
        assert run(case, apply=True)["writes"] == 0
    else:
        with pytest.raises(MoneyflowContractError, match="uncertain_action"):
            run(case, apply=True)
    assert len(case.source.copies) == 14


def test_cancel_before_any_write(case):
    with pytest.raises(InterruptedError, match="cancelled"):
        run(case, apply=True, cancel=lambda: True)
    assert not case.root.exists() and not case.updates.actions


@pytest.mark.parametrize(
    "kind", ["copies", "metadata", "connections", "reads", "seconds", "bytes", "files"]
)
def test_persistent_global_budget(case, kind):
    case.root.mkdir(parents=True)
    c = Control(case.plan, digest(case.plan), case.root)
    c.save()
    if kind == "seconds":
        c.state["seconds"] = LIMITS[kind] + 1
        c.save()
        with pytest.raises(MoneyflowContractError, match="seconds"):
            Control(case.plan, digest(case.plan), case.root)
    elif kind in {"bytes", "files"}:
        if kind == "bytes":
            with (case.root / "oversized").open("wb") as handle:
                handle.truncate(LIMITS[kind] + 1)
        else:
            for i in range(LIMITS[kind]):
                (case.root / f"f{i}").touch()
        with pytest.raises(MoneyflowContractError, match="disk_budget"):
            c.disk()
    else:
        c.state["counts"][kind] = LIMITS[kind]
        c.save()
        restored = Control(case.plan, digest(case.plan), case.root)
        with pytest.raises(MoneyflowContractError, match="budget"):
            restored.charge("copies" if kind == "connections" else kind)


def test_current_graphql_schema_accepts_exact_update_requests():
    from dagster_graphql.schema import create_schema
    from graphql import get_variable_values, parse, validate

    schema = create_schema().graphql_schema
    for body in (
        snapshot_body(),
        {"query": START, "variables": {"selector": snapshot_body()["variables"]["s0"]}},
        {"query": STOP, "variables": {"id": "native-sensor-id"}},
    ):
        document = parse(body["query"])
        assert validate(schema, document) == []
        assert isinstance(
            get_variable_values(
                schema, document.definitions[0].variable_definitions, body["variables"]
            ),
            dict,
        )
    assert len(NAMES) == 14 and all("register" not in n for n in NAMES)


def test_source_request_reservation_survives_failure(case):
    case.root.mkdir(parents=True)
    c = Control(case.plan, digest(case.plan), case.root)

    def fail(*args):
        raise OSError("interrupted source")

    s = Source(SimpleNamespace(copy=fail), c)
    with pytest.raises(OSError):
        s.copy(None, None, lambda: None)
    restored = Control(case.plan, digest(case.plan), case.root)
    assert restored.state["seconds"] >= 120 and restored.state["counts"]["copies"] == 1


def test_no_same_day_old_check_is_allowed_but_failed_check_is_not(case):
    assert case.plan["entries"][-1]["baseline"]["raw"]["check_id"] is None
    entry = case.plan["entries"][-1]
    c = Control(case.plan, digest(case.plan))
    mat, _ = events.facts(case.instance, entry, "raw", c)
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    case.instance.report_runless_asset_event(
        AssetCheckEvaluation(
            asset_key=mat.asset_key,
            check_name=CONTRACTS["moneyflow_dc"].raw_check,
            passed=False,
            blocking=True,
            partition=entry["day"],
            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                storage_id=mat.storage_id,
                run_id=mat.event_log_entry.run_id,
                timestamp=mat.timestamp,
            ),
        )
    )
    with pytest.raises(MoneyflowContractError, match="old_check_failed_or_stale"):
        events.baseline(
            case.instance, entry, "raw", entry["baseline"]["raw"]["hash"], c
        )


def test_post_metadata_failure_keeps_completed_tables_and_shared_budget(
    case, monkeypatch
):
    original = case.source.metadata
    failed = False

    def fail(request, sink, check):
        nonlocal failed
        if request.dataset == "moneyflow_ind_ths" and not failed:
            failed = True
            raise OSError("post metadata connection lost")
        original(request, sink, check)

    monkeypatch.setattr(case.source, "metadata", fail)
    with pytest.raises(OSError, match="metadata connection"):
        run(case, apply=True)
    state = read_json(case.root / "state.json")
    assert state["verified_metadata"] == {
        "moneyflow_mkt_dc": digest(case.plan["metadata"]["moneyflow_mkt_dc"])
    }
    assert state["counts"]["connections"] == 21 and len(case.source.copies) == 14
    monkeypatch.setattr(case.source, "metadata", original)
    result = run(case, apply=True)
    assert result["accepted"] == 7 and result["counts"]["connections"] == 25
    assert result["counts"]["metadata"] == 11 and len(case.source.copies) == 14


def test_partial_pause_lost_response_restores_only_originally_running(
    case, monkeypatch
):
    original = case.updates.set_status

    def fail(name, identity, status):
        original(name, identity, status)
        if len(case.updates.actions) == 2:
            raise OSError("pause response lost")

    monkeypatch.setattr(case.updates, "set_status", fail)
    with pytest.raises(OSError, match="pause response"):
        run(case, apply=True)
    assert case.updates.snapshot() == case.plan["sensors"]
    assert not case.source.copies and len(case.updates.actions) == 4


def test_dc_merge_exit_before_proof_rebuilds_only_sql(case, monkeypatch):
    from orchestrator.defs.bootstrap import moneyflow_history_supplement_files as files

    original = files.save_json
    failed = False

    def fail(path, value):
        nonlocal failed
        if value.get("old_hashes") and not failed:
            failed = True
            raise OSError("merge proof exit")
        original(path, value)

    monkeypatch.setattr(files, "save_json", fail)
    with pytest.raises(OSError, match="merge proof exit"):
        run(case, apply=True)
    assert len(case.source.copies) == 14
    monkeypatch.setattr(files, "save_json", original)
    assert run(case, apply=True)["accepted"] == 7
    assert (
        len(case.source.copies) == 14
        and len(list((case.root / "item-6").glob("merged-*"))) == 2
    )


@pytest.mark.parametrize("fault", ["target", "candidate", "proof", "check"])
def test_partial_operation_tampering_stops_without_new_copy(case, monkeypatch, fault):
    run(case, apply=True, sample_only=True)
    state = read_json(case.root / "state.json")
    if fault == "target":
        target(case.lake, "moneyflow_mkt_dc", "2026-07-09", "raw").write_bytes(
            b"changed"
        )
    elif fault == "candidate":
        Path(state["items"]["1"]["source"]["paths"]["raw"]).write_bytes(b"changed")
    elif fault == "proof":
        path = case.root / "item-0/final-proof.json"
        value = read_json(path)
        value["hashes"]["raw"] = "0" * 64
        save_json(path, value)
        # Missing local acceptance must not allow the altered proof to publish.
        state["items"]["0"]["accepted"] = False
        save_json(case.root / "state.json", state)
    else:
        entry = case.plan["entries"][0]
        c = Control(case.plan, digest(case.plan))
        mat, _ = events.facts(case.instance, entry, "raw", c)
        case.instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=mat.asset_key,
                partition=entry["day"],
                metadata=mat.asset_materialization.metadata,
            )
        )  # Real new storage_id; the previous check still targets the old one.
    with pytest.raises(MoneyflowContractError):
        run(case, apply=True)
    assert len(case.source.copies) == 14
    assert all(v["status"] == "STOPPED" for v in case.updates.snapshot().values())


def test_active_run_blocks_before_pause_or_source(case):
    case.instance.run_storage.add_run(
        dg.DagsterRun(
            job_name=CONTRACTS["moneyflow_dc"].raw_job,
            run_id="active-source-job",
            status=dg.DagsterRunStatus.STARTED,
        )
    )
    with pytest.raises(MoneyflowContractError, match="active_update_runs"):
        run(case, apply=True)
    assert (
        not case.updates.actions and not case.source.copies and not case.root.exists()
    )


@pytest.mark.parametrize("job", [n.removesuffix("_sensor") for n in NAMES])
def test_native_active_query_covers_each_update_job_with_one_read(case, job):
    from dagster._core.remote_origin import (
        RegisteredCodeLocationOrigin,
        RemoteRepositoryOrigin,
    )

    from orchestrator.defs.bootstrap.moneyflow_history_supplement_sensors import idle

    # SDK DagsterRun.__new__ requires a real origin record for QUEUED;
    # this is metadata only, not a code-location connection or launched job.
    origin = RemoteRepositoryOrigin(
        RegisteredCodeLocationOrigin("isolated-moneyflow"), "test_repo"
    ).get_job_origin(job)
    case.instance.run_storage.add_run(
        dg.DagsterRun(
            job_name=job,
            run_id="queued-" + job,
            status=dg.DagsterRunStatus.QUEUED,
            remote_job_origin=origin,
        )
    )
    control = Control(case.plan, digest(case.plan))
    before = control.state["counts"]["reads"]
    with pytest.raises(MoneyflowContractError, match="active_update_runs"):
        idle(case.instance, control)
    assert control.state["counts"]["reads"] == before + 1


def test_native_active_query_ignores_unrelated_jobs(case):
    from orchestrator.defs.bootstrap.moneyflow_history_supplement_sensors import idle

    case.instance.run_storage.add_run(
        dg.DagsterRun(
            job_name="unrelated_job",
            run_id="unrelated-active",
            status=dg.DagsterRunStatus.STARTED,
        )
    )
    control = Control(case.plan, digest(case.plan))
    before = control.state["counts"]["reads"]
    idle(case.instance, control)
    assert control.state["counts"]["reads"] == before + 1


def test_all_fourteen_running_sample_complete_and_replay_fit_budget(case):
    for value in case.updates.values.values():
        value["status"] = "RUNNING"
    case.plan["sensors"] = case.updates.snapshot()
    assert run(case, apply=True, sample_only=True)["accepted"] == 1
    assert run(case, apply=True)["accepted"] == 7
    assert case.updates.snapshot() == case.plan["sensors"]
    assert run(case, apply=True)["writes"] == 0
    state = read_json(case.root / "state.json")
    assert state["counts"]["reads"] + 29 <= 400
    assert state["counts"]["copies"] == 14 and state["counts"]["connections"] == 24
    assert len(case.updates.actions) == 56


def observed_cursor(when="2026-10-18T02:00:00+08:00"):
    from orchestrator.defs.run_contracts.cursors import build_sensor_cursor

    # Current real producer build_sensor_cursor, with an independent literal
    # runtime progress sample from the observed before_window contract.
    return build_sensor_cursor(
        evaluated_at=datetime.fromisoformat(when),
        decision="skip",
        details={
            "summary": "尚未到22:00。",
            "next_action": "等待下次评估。",
            "reason_code": "before_window",
            "runtime_state": {"dates": {"2026-10-16": {"verified_on": "2026-10-17"}}},
        },
    )


def test_natural_evaluation_time_updates_do_not_reset_progress(case, monkeypatch):
    from orchestrator.defs.bootstrap.moneyflow_history_supplement_sensors import (
        same_sensor_snapshot,
    )

    name = NAMES[1]
    case.updates.values[name]["cursor"] = observed_cursor()
    case.plan["sensors"] = case.updates.snapshot()
    original = case.updates.snapshot
    counter = 0

    def evaluated():
        nonlocal counter
        counter += 1
        if case.updates.values[name]["status"] == "RUNNING":
            value = json.loads(case.updates.values[name]["cursor"])
            value["evaluated_at"] = (
                datetime.fromisoformat("2026-10-18T02:00:00+08:00")
                + timedelta(seconds=counter)
            ).isoformat()
            case.updates.values[name]["cursor"] = json.dumps(value)
        return original()

    monkeypatch.setattr(case.updates, "snapshot", evaluated)
    assert run(case, apply=True, sample_only=True)["accepted"] == 1
    assert run(case, apply=True)["accepted"] == 7
    assert run(case, apply=True)["writes"] == 0
    current = case.updates.snapshot()
    assert current[name]["cursor"] != case.plan["sensors"][name]["cursor"]
    assert same_sensor_snapshot(current, case.plan["sensors"])
    assert json.loads(current[name]["cursor"])["details"]["runtime_state"] == {
        "dates": {"2026-10-16": {"verified_on": "2026-10-17"}}
    }


@pytest.mark.parametrize(
    "change",
    [
        "progress",
        "date",
        "count",
        "schema",
        "unknown",
        "invalid_time",
        "naive_time",
        "id",
        "status",
    ],
)
def test_cursor_progress_identity_and_contract_changes_still_refuse(change):
    from orchestrator.defs.bootstrap.moneyflow_history_supplement_sensors import (
        same_sensor_state,
    )

    old = {"id": "native-id", "status": "RUNNING", "cursor": observed_cursor()}
    new = copy.deepcopy(old)
    value = json.loads(observed_cursor("2026-10-18T02:10:00+08:00"))
    if change == "progress":
        value["details"]["runtime_state"]["dates"] = {}
    elif change == "date":
        value["target_date"] = "2026-10-16"
    elif change == "count":
        value["selected_count"] = 1
    elif change == "schema":
        value["schema_version"] = 2
    elif change == "unknown":
        value["extra_field"] = True
    elif change == "invalid_time":
        value["evaluated_at"] = "bad-time"
    elif change == "naive_time":
        value["evaluated_at"] = "2026-10-18T02:10:00"
    elif change == "id":
        new["id"] = "other-id"
    else:
        new["status"] = "STOPPED"
    new["cursor"] = json.dumps(value)
    assert not same_sensor_state(new, old)


def test_cancel_during_source_can_resume_without_poisoning_unit(case, monkeypatch):
    original = case.source.copy
    cancelled = False

    def interrupted(request, sink, check):
        nonlocal cancelled
        original(request, sink, check)
        cancelled = True

    monkeypatch.setattr(case.source, "copy", interrupted)
    with pytest.raises(InterruptedError, match="cancelled"):
        run(case, apply=True, cancel=lambda: cancelled)
    assert case.updates.snapshot() == case.plan["sensors"]
    assert len(list(case.lake.rglob("*.parquet"))) == 2
    monkeypatch.setattr(case.source, "copy", original)
    assert run(case, apply=True)["accepted"] == 7
    assert len(case.source.copies) == 15


def test_old_valid_runless_check_requires_new_design_before_publication(case):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    from orchestrator.defs.run_contracts.metadata import (
        CheckScope,
        build_check_metadata,
    )

    entry = case.plan["entries"][-1]
    c = Control(case.plan, digest(case.plan))
    mat, _ = events.facts(case.instance, entry, "raw", c)
    case.instance.report_runless_asset_event(
        AssetCheckEvaluation(
            asset_key=mat.asset_key,
            check_name=CONTRACTS["moneyflow_dc"].raw_check,
            passed=True,
            blocking=True,
            partition=entry["day"],
            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                storage_id=mat.storage_id,
                run_id=mat.event_log_entry.run_id,
                timestamp=mat.timestamp,
            ),
            metadata=build_check_metadata(
                check_scope=CheckScope.SCHEMA,
                extra_metadata={"file_sha256": entry["baseline"]["raw"]["hash"]},
            ),
        )
    )
    with pytest.raises(
        MoneyflowContractError, match="old_runless_check_revision_unsupported"
    ):
        events.baseline(
            case.instance, entry, "raw", entry["baseline"]["raw"]["hash"], c
        )


def test_readonly_review_of_partial_operation_checks_real_files(case):
    run(case, apply=True, sample_only=True)
    before = file_hash(case.root / "state.json")
    assert run(case)["accepted"] == 1
    assert file_hash(case.root / "state.json") == before
    target(case.lake, "moneyflow_mkt_dc", "2026-07-09", "raw").write_bytes(
        b"external change"
    )
    with pytest.raises(MoneyflowContractError, match="partial_target_changed"):
        run(case)
    assert (
        file_hash(case.root / "state.json") == before and len(case.source.copies) == 14
    )
