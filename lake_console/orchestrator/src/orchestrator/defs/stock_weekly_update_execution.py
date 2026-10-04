"""Frozen automatic intents and receipt recovery for the existing point writer."""

import fcntl
import json
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    WeeklyCaptureStore,
    _atomic_json,
    capture_file_hash,
    check_capture_path,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyUnit,
    StockWeeklySource,
    WeeklyBudget,
    WeeklyPlanManifest,
    weekly_dataset_id,
)
from orchestrator.defs.source_readiness.stock_weekly import (
    assert_weekly_references_unchanged,
    load_weekly_reference,
    verify_weekly_source_completion,
)
from orchestrator.defs.stock_weekly_update import (
    WEEKLY_UPDATE_POLICY,
    weekly_update_intent,
)


@contextmanager
def weekly_execution_lock(staging_root, source, week):
    directory = (
        staging_root
        / "stock_weekly_raw"
        / "execution_locks"
        / weekly_dataset_id(source)
    )
    check_capture_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{week}.lock"
    check_capture_path(path)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WeeklyCaptureError("weekly_execution_active") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def read_weekly_control(path):
    check_capture_path(path)
    if path.stat().st_size > WEEKLY_UPDATE_POLICY.max_control_bytes:
        raise WeeklyCaptureError("weekly_control_budget_exceeded")
    return json.loads(path.read_text())


class WeeklyUpdateExecution:
    def __init__(self, source, week, intent_date, *, target_root, upstream_ready):
        self.intent = weekly_update_intent(source, week, intent_date)
        self.source = source
        self.target_root = target_root
        self.upstream_ready = upstream_ready
        self.reference = None
        self.next_request_at = 0.0

    def prepare(self, connection, assembly):
        path = assembly / "update_reference.json"
        if path.exists():
            self.reference = read_weekly_control(path)
            if self.reference["week"] != self.intent["week"]:
                raise WeeklyCaptureError("weekly_reference_identity_mismatch")
            assert_weekly_references_unchanged(self.reference["references"])
            if not self.upstream_ready(self.reference["open_dates"]):
                raise WeeklyCaptureError("weekly_upstream_not_ready")
        else:
            self.reference = load_weekly_reference(
                connection,
                self.target_root,
                self.intent["week"],
                upstream_ready=self.upstream_ready,
            )
            _atomic_json(path, self.reference)
        requests_path = assembly / "requests.json"
        if requests_path.exists():
            state = read_weekly_control(requests_path)
            budget = WeeklyBudget()
            self.next_request_at = (
                state.get(
                    "ended_at", state.get("started_at", 0) + budget.call_timeout_seconds
                )
                + budget.minimum_interval_seconds
            )
        return {"path": str(path), "sha256": capture_file_hash(path)}

    def reserve(self, assembly, index, params, request_cap, budget):
        path = assembly / "requests.json"
        state = (
            read_weekly_control(path)
            if path.exists()
            else {"calls": 0, "page_attempts": {}}
        )
        attempts = state["page_attempts"]
        key = str(index)
        if (
            state["calls"] >= request_cap
            or attempts.get(key, 0) >= budget.max_retries + 1
        ):
            raise WeeklyCaptureError("point_request_cap_exceeded")
        attempts[key] = attempts.get(key, 0) + 1
        state.update(
            calls=state["calls"] + 1,
            cap=request_cap,
            params=params,
            stage="requesting",
            started_at=time.time(),
        )
        state.pop("ended_at", None)
        _atomic_json(path, state)
        return state["calls"]

    def request_ended(self, assembly, budget):
        path = assembly / "requests.json"
        state = read_weekly_control(path)
        state["ended_at"] = time.time()
        _atomic_json(path, state)
        self.next_request_at = state["ended_at"] + budget.minimum_interval_seconds

    def record_page(self, assembly, index, unit, rows):
        _atomic_json(
            assembly / f"page-control-{index}.json",
            {**json.loads(json.dumps(asdict(unit), default=str)), "planned_rows": rows},
        )

    def resume_page(self, connection, assembly, index, intent, budget, plan_hash):
        path = assembly / f"page-control-{index}.json"
        if not path.exists():
            return None
        item = read_weekly_control(path)
        unit = ProdWeeklyUnit(
            item["unit_id"],
            StockWeeklySource(item["source"]),
            tuple(item["sorted_codes"]),
            date.fromisoformat(item["source_date_start"]),
            date.fromisoformat(item["source_date_end"]),
            item["schema_hash"],
            item["max_rows"],
        )
        if unit.source != self.source:
            raise WeeklyCaptureError("weekly_page_source_mismatch")
        manifest = WeeklyPlanManifest(
            plan_hash,
            self.source,
            str(assembly / "intent.json"),
            capture_file_hash(assembly / "intent.json"),
            (unit,),
            budget,
            0,
            item["planned_rows"],
            0,
            (),
        )
        store = WeeklyCaptureStore(assembly / f"page-{index}", manifest)
        with store.locked():
            try:
                receipt_path, receipt = store.validated_receipt(connection, unit)
            except WeeklyCaptureError as error:
                if str(error) == "capture_incomplete":
                    return None
                raise
        inputs, evidence = (
            [],
            [{"path": str(receipt_path), "sha256": capture_file_hash(receipt_path)}],
        )
        for chunk in receipt["chunks"]:
            reference = receipt_path.parent / chunk["path"]
            inputs.append(reference)
            evidence.append({"path": str(reference), "sha256": chunk["sha256"]})
        return {
            "rows": receipt["source_rows"],
            "inputs": inputs,
            "evidence": evidence,
            "index": {
                "unit": item,
                "receipt": str(receipt_path),
                "rows": receipt["source_rows"],
            },
        }

    def verify(self, connection):
        assert_weekly_references_unchanged(self.reference["references"])
        if not self.upstream_ready(self.reference["open_dates"]):
            raise WeeklyCaptureError("weekly_upstream_not_ready")
        rows = connection.execute(
            "SELECT ts_code,trade_date,end_date,freq FROM weekly_input"
        ).fetchall()
        return verify_weekly_source_completion(rows, self.reference)
