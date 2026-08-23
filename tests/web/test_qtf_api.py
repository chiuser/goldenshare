from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from qtf.adapters.persistence.models.runtime import ExperimentRun
from qtf.contracts.runtime import DatasetEvidence
from qtf.engine.canonical_hash import canonical_json_hash
from qtf.modules.sector.factor_kernel import SectorObservation
from qtf.modules.sector.input_contract import (
    SECTOR_L2_SOURCE_CONTRACT,
    SectorHierarchyNode,
    SectorInputSnapshot,
)
from src.app.api.v1.qtf import get_qtf_input_source
from src.app.runtime.qtf_task_intent_stager import QtfTaskRunIntentStager
from src.app.models.app_user import AppUser
from src.ops.models.ops.task_run import TaskRun
from src.ops.contracts.external_task import ExternalTaskExecutionOutcome
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.runtime.worker import OperationsWorker
from src.ops.runtime.worker_lane import WorkerLane


class StubSectorInputSource:
    def __init__(self, snapshot: SectorInputSnapshot) -> None:
        self.snapshot = snapshot
        self.read_count = 0

    def read(self, _request):  # type: ignore[no-untyped-def]
        self.read_count += 1
        return self.snapshot


def test_qtf_api_requires_admin(app_client: TestClient, user_factory) -> None:  # type: ignore[no-untyped-def]
    assert app_client.get("/api/v1/qtf/templates").status_code == 401

    user_factory(username="viewer", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "viewer", "password": "secret"})
    response = app_client.get(
        "/api/v1/qtf/templates",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert response.status_code == 403


def test_qtf_draft_preflight_freeze_run_and_cancel_flow(
    app_client: TestClient,
    auth_token: str,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.web.app import app

    headers = {"Authorization": f"Bearer {auth_token}"}
    source = StubSectorInputSource(_snapshot())
    app.dependency_overrides[get_qtf_input_source] = lambda: source

    templates = app_client.get("/api/v1/qtf/templates", headers=headers)
    assert templates.status_code == 200
    assert [item["templateKey"] for item in templates.json()["templates"]] == ["sector_l2_turn_hot_v1"]

    created = app_client.post(
        "/api/v1/qtf/researches",
        headers=headers,
        json={"requestKey": "create-1", "templateKey": "sector_l2_turn_hot_v1", "title": "二级行业转热"},
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["revisionStatus"] == "DRAFT"
    assert created_body["canPreflight"] is False
    research_key = created_body["researchKey"]
    revision_key = created_body["revisionKey"]

    incomplete = app_client.post(
        f"/api/v1/qtf/researches/{research_key}/input-preflights",
        headers=headers,
        json={
            "requestKey": "preflight-before-draft",
            "draftVersion": 1,
            "requestedStartDate": "2026-08-03",
            "requestedEndDate": "2026-08-04",
        },
    )
    assert incomplete.status_code == 422
    assert source.read_count == 0

    saved = app_client.put(
        f"/api/v1/qtf/researches/{research_key}/draft",
        headers=headers,
        json={
            "draftVersion": 1,
            "problemStatement": "能否发现未来继续热的二级行业",
            "successDefinitionKeys": ["FUTURE_SIBLING_RANK_CONTINUATION"],
            "nonGoalKeys": ["PER_SECTOR_TUNING", "PRODUCTION_RELEASE"],
            "parameterSelections": _parameter_selections(),
        },
    )
    assert saved.status_code == 200
    assert saved.json()["draftVersion"] == 2
    assert saved.json()["canPreflight"] is True

    extra = app_client.put(
        f"/api/v1/qtf/researches/{research_key}/draft",
        headers=headers,
        json={
            "draftVersion": 2,
            "problemStatement": "x",
            "successDefinitionKeys": [],
            "nonGoalKeys": [],
            "parameterSelections": None,
            "pythonSource": "print('forbidden')",
        },
    )
    assert extra.status_code == 422

    preview = app_client.post(
        f"/api/v1/qtf/researches/{research_key}/input-preflights",
        headers=headers,
        json={
            "requestKey": "preflight-1",
            "draftVersion": 2,
            "requestedStartDate": "2026-08-03",
            "requestedEndDate": "2026-08-04",
        },
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert source.read_count == 1
    assert preview_body["preflight"]["preflightStatus"] == "PASS"
    assert preview_body["plan"]["sampleSplit"] == {
        "kind": "ORDERED_TRADING_DAYS",
        "inSamplePct": 50,
        "calibrationPct": 25,
        "outOfSamplePct": 25,
    }
    assert preview_body["plan"]["futureHorizons"] == [1, 3, 5]
    assert len(preview_body["plan"]["parameterMatrix"]) == 4

    wrong_freeze = app_client.post(
        f"/api/v1/qtf/researches/{research_key}/freeze",
        headers=headers,
        json={
            "requestKey": "freeze-1",
            "draftVersion": 2,
            "inputPreflightKey": preview_body["preflight"]["preflightKey"],
            "approvedPlanHash": "0" * 64,
            "acknowledgedExclusions": True,
        },
    )
    assert wrong_freeze.status_code == 409

    frozen = app_client.post(
        f"/api/v1/qtf/researches/{research_key}/freeze",
        headers=headers,
        json={
            "requestKey": "freeze-1",
            "draftVersion": 2,
            "inputPreflightKey": preview_body["preflight"]["preflightKey"],
            "approvedPlanHash": preview_body["plan"]["planHash"],
            "acknowledgedExclusions": True,
        },
    )
    assert frozen.status_code == 200
    assert frozen.json()["revisionStatus"] == "FROZEN"
    revision_hash = frozen.json()["revisionHash"]

    freeze_replay = app_client.post(
        f"/api/v1/qtf/researches/{research_key}/freeze",
        headers=headers,
        json={
            "requestKey": "freeze-1",
            "draftVersion": 2,
            "inputPreflightKey": preview_body["preflight"]["preflightKey"],
            "approvedPlanHash": preview_body["plan"]["planHash"],
            "acknowledgedExclusions": True,
        },
    )
    assert freeze_replay.status_code == 200
    assert freeze_replay.json()["revisionHash"] == revision_hash

    run_count_before = len(list(db_session.scalars(select(ExperimentRun))))
    task_count_before = len(list(db_session.scalars(select(TaskRun))))
    original_stage = QtfTaskRunIntentStager.stage

    def _stage_then_fail(self, intent):  # type: ignore[no-untyped-def]
        original_stage(self, intent)
        raise RuntimeError("simulated staging failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(QtfTaskRunIntentStager, "stage", _stage_then_fail)
        with pytest.raises(RuntimeError, match="simulated staging failure"):
            app_client.post(
                f"/api/v1/qtf/revisions/{revision_key}/runs",
                headers=headers,
                json={"requestKey": "run-rollback", "revisionHash": revision_hash},
            )
    db_session.expire_all()
    assert len(list(db_session.scalars(select(ExperimentRun)))) == run_count_before
    assert len(list(db_session.scalars(select(TaskRun)))) == task_count_before

    started = app_client.post(
        f"/api/v1/qtf/revisions/{revision_key}/runs",
        headers=headers,
        json={"requestKey": "run-1", "revisionHash": revision_hash},
    )
    assert started.status_code == 200
    run_body = started.json()
    assert run_body["runStatus"] == "QUEUED"
    run = db_session.scalar(select(ExperimentRun).where(ExperimentRun.run_key == run_body["runKey"]))
    task_run = db_session.get(TaskRun, run_body["taskRunId"])
    assert run is not None and task_run is not None
    assert run.task_run_id == task_run.id
    assert task_run.task_type == "qtf_experiment"

    replay = app_client.post(
        f"/api/v1/qtf/revisions/{revision_key}/runs",
        headers=headers,
        json={"requestKey": "run-1", "revisionHash": revision_hash},
    )
    assert replay.status_code == 200
    assert replay.json()["runKey"] == run_body["runKey"]
    assert len(list(db_session.scalars(select(ExperimentRun)))) == 1

    detail = app_client.get(f"/api/v1/qtf/runs/{run_body['runKey']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["frozenPlanSummary"]["candidateCount"] == 4
    assert "runtimeFingerprint" not in detail.json()
    assert "requestPayload" not in detail.json()

    canceled = app_client.post(
        f"/api/v1/qtf/runs/{run_body['runKey']}/cancel",
        headers=headers,
        json={"requestKey": "cancel-1", "currentVersion": "QUEUED"},
    )
    assert canceled.status_code == 200
    assert canceled.json()["runStatus"] == "CANCELED"

    cancel_replay = app_client.post(
        f"/api/v1/qtf/runs/{run_body['runKey']}/cancel",
        headers=headers,
        json={"requestKey": "cancel-1", "currentVersion": "QUEUED"},
    )
    assert cancel_replay.status_code == 200
    assert cancel_replay.json()["runStatus"] == "CANCELED"

    stale_cancel = app_client.post(
        f"/api/v1/qtf/runs/{run_body['runKey']}/cancel",
        headers=headers,
        json={"requestKey": "cancel-stale", "currentVersion": "EXECUTING"},
    )
    assert stale_cancel.status_code == 409
    assert stale_cancel.json()["code"] == "QTF_STATE_CONFLICT"


def test_default_ops_task_run_api_rejects_qtf(
    app_client: TestClient,
    auth_token: str,
) -> None:
    response = app_client.post(
        "/api/v1/ops/task-runs",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "task_type": "qtf_experiment",
            "resource_key": "sector_heat_research",
            "action": "execute_backtest",
            "time_input": {"mode": "none"},
            "filters": {},
            "request_payload": {"runKey": "forged"},
        },
    )
    assert response.status_code == 422


def test_qtf_worker_lane_claims_only_qtf_and_general_leaves_it_queued(
    db_session: Session,
    task_run_factory,
) -> None:  # type: ignore[no-untyped-def]
    qtf_task = task_run_factory(
        task_type="qtf_experiment",
        resource_key="sector_heat_research",
        action="execute_backtest",
        request_payload_json={"runKey": "run-1", "revisionKey": "revision-1", "revisionHash": "a" * 64},
    )
    minute_task = task_run_factory(task_type="dataset_action", resource_key="stk_mins")

    assert OperationsWorker(lane=WorkerLane.GENERAL).run_next(db_session) is None
    db_session.refresh(qtf_task)
    db_session.refresh(minute_task)
    assert qtf_task.status == "queued"
    assert minute_task.status == "queued"

    executor = _StubExternalExecutor()
    worker = OperationsWorker(
        dispatcher=TaskRunDispatcher(external_executors={"qtf_experiment": executor}),
        lane=WorkerLane.QTF,
    )
    completed = worker.run_next(db_session)

    assert completed is not None and completed.id == qtf_task.id
    assert completed.status == "success"
    assert executor.task_run_ids == [qtf_task.id]
    db_session.refresh(minute_task)
    assert minute_task.status == "queued"


class _StubExternalExecutor:
    def __init__(self) -> None:
        self.task_run_ids: list[int] = []

    def execute(self, *, task_run_id: int, request_payload):  # type: ignore[no-untyped-def]
        self.task_run_ids.append(task_run_id)
        assert request_payload["runKey"] == "run-1"
        return ExternalTaskExecutionOutcome(status="success", summary_message="done")


def _parameter_selections() -> dict[str, object]:
    return {
        "baselineDays": [60, 120],
        "trendDays": [5, 10],
        "amountLookbackDays": 20,
        "ewmaLambda": 0.3,
        "priceWeight": 0.5,
        "amountWeight": 0.5,
        "zClip": 3.0,
        "signalThreshold": 70.0,
        "resetThreshold": 60.0,
        "upMoveShareMin": 0.6,
        "futureHorizons": [1, 3, 5],
        "comparisonScope": "SIBLINGS",
        "minimumGroupSize": 2,
        "rankingRule": {"kind": "PERCENTILE_GTE", "threshold": 80.0},
        "eventClusterRule": "RESET_ONLY",
    }


def _snapshot() -> SectorInputSnapshot:
    now = datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc)
    trade_dates = (date(2026, 8, 3), date(2026, 8, 4))
    hierarchy = (
        SectorHierarchyNode("P", "父行业", 1, None, "P", 1, "v1", now),
        SectorHierarchyNode("A", "子行业A", 2, "P", "P", 1, "v1", now),
        SectorHierarchyNode("B", "子行业B", 2, "P", "P", 2, "v1", now),
    )
    observations = tuple(
        SectorObservation(day, sector, "", pct_change, amount)
        for day, rows in (
            (trade_dates[0], (("A", 1.0, 100.0), ("B", -1.0, 120.0))),
            (trade_dates[1], (("A", 2.0, 130.0), ("B", 0.5, 140.0))),
        )
        for sector, pct_change, amount in rows
    )
    evidence = tuple(
        DatasetEvidence(
            dataset_key=key,
            fields=("field",),
            start_date=trade_dates[0] if key != "core_serving.wealth_sector_hierarchy" else None,
            end_date=trade_dates[-1] if key != "core_serving.wealth_sector_hierarchy" else None,
            row_count=count,
            unique_key_status="PASS",
            missing_count=0,
            duplicate_count=0,
            content_hash=canonical_json_hash({"key": key, "count": count}),
        )
        for key, count in (
            ("core_serving.trade_calendar", 2),
            ("core_serving.wealth_sector_hierarchy", 3),
            ("core_serving.dc_daily", 4),
        )
    )
    source_hash = canonical_json_hash(SECTOR_L2_SOURCE_CONTRACT)
    return SectorInputSnapshot(
        as_of=now,
        trade_dates=trade_dates,
        hierarchy=hierarchy,
        observations=observations,
        dataset_evidence=evidence,
        content_hash=canonical_json_hash({"source": source_hash, "rows": 9}),
        source_contract_hash=source_hash,
    )
