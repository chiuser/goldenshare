"""Single-writer source-unit CSV export, independent verification and recovery."""

import json
import os
import re
import shutil
import time
from pathlib import Path
from uuid import uuid4

from orchestrator.defs.bootstrap.moneyflow_history_csv import (
    audit_moneyflow_history_csv,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    validate_moneyflow_history_plan,
)
from orchestrator.defs.bootstrap.moneyflow_history_source import (
    MoneyflowHistoryCopyRequest,
)
from orchestrator.defs.io.moneyflow_candidates import (
    moneyflow_candidate_directory,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_DUCKDB_MEMORY_LIMIT,
    MONEYFLOW_DUCKDB_THREADS,
    MONEYFLOW_HISTORY_MAX_CSV_BYTES,
    MONEYFLOW_HISTORY_MAX_ELAPSED_SECONDS,
    MONEYFLOW_HISTORY_MAX_SOURCE_BYTES,
    MONEYFLOW_HISTORY_MIN_FREE_BYTES,
    MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
    MONEYFLOW_HISTORY_STREAM_BYTES,
    MONEYFLOW_MAX_RSS_BYTES,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
)


def _identity(plan):
    return {
        "revision": "moneyflow_history_csv_export_v1",
        "plan_hash": plan.plan_hash,
        "schema_hash": plan.schema_hash,
        "source_counts_hash": plan.source_counts_hash,
        "limits": {
            "csv_bytes": MONEYFLOW_HISTORY_MAX_CSV_BYTES,
            "source_bytes": MONEYFLOW_HISTORY_MAX_SOURCE_BYTES,
            "elapsed_seconds": MONEYFLOW_HISTORY_MAX_ELAPSED_SECONDS,
            "unit_seconds": MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
            "minimum_free_bytes": MONEYFLOW_HISTORY_MIN_FREE_BYTES,
            "stream_bytes": MONEYFLOW_HISTORY_STREAM_BYTES,
            "rss_bytes": MONEYFLOW_MAX_RSS_BYTES,
            "duckdb_memory": MONEYFLOW_DUCKDB_MEMORY_LIMIT,
            "duckdb_threads": MONEYFLOW_DUCKDB_THREADS,
            "spill_bytes": 0,
        },
    }


def _read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise MoneyflowContractError("history_checkpoint_file")
    try:
        result = json.loads(path.read_text())
    except (ValueError, UnicodeError) as error:
        raise MoneyflowContractError("history_checkpoint_invalid") from error
    if not isinstance(result, dict):
        raise MoneyflowContractError("history_checkpoint_invalid")
    return result


class _Store:
    def __init__(self, directory):
        self.directory = directory
        self.recount()

    def recount(self):
        self.used = 0
        for root, directories, files in os.walk(self.directory):
            for name in (*directories, *files):
                path = Path(root) / name
                if path.is_symlink():
                    raise MoneyflowContractError("history_checkpoint_symlink")
            for name in files:
                self.used += (Path(root) / name).stat().st_size
                self.reserve(0)

    def reserve(self, size):
        if self.used + size > MONEYFLOW_HISTORY_MAX_SOURCE_BYTES:
            raise MoneyflowContractError("history_source_bytes_budget")

    def json(self, path, value):
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        self.reserve(len(data))
        if path.is_symlink():
            raise MoneyflowContractError("history_checkpoint_symlink")
        old_size = path.stat().st_size if path.exists() else 0
        candidate = path.with_name(path.name + ".tmp-" + uuid4().hex)
        with candidate.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self.used += len(data)
        os.replace(candidate, path)
        self.used -= old_size
        # Preserve the rename across process or machine exit.
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class _Control:
    def __init__(self, store, identity, unit_id, total_units, clock, cancel):
        self.store, self.clock, self.cancel = store, clock, cancel
        self.path = store.directory / "progress.json"
        self.budget = (
            _read_json(self.path)
            if self.path.exists()
            else {**identity, "charged_seconds": 0}
        )
        if any(self.budget.get(key) != value for key, value in identity.items()):
            raise MoneyflowContractError("history_execution_contract_changed")
        charged = self.budget.get("charged_seconds")
        if (
            type(charged) not in (int, float)
            or not 0 <= charged <= MONEYFLOW_HISTORY_MAX_ELAPSED_SECONDS
        ):
            raise MoneyflowContractError("history_time_budget")
        self.budget["unit_id"] = unit_id
        self.budget.setdefault("completed_units", 0)
        self.budget.setdefault("copy_transactions", 0)
        if (
            type(self.budget["completed_units"]) is not int
            or not 0 <= self.budget["completed_units"] <= total_units
            or type(self.budget["copy_transactions"]) is not int
            or self.budget["copy_transactions"] < 0
        ):
            raise MoneyflowContractError("history_checkpoint_progress")
        self.budget["total_units"] = total_units
        self.started = None
        self.bytes = 0

    def check(self):
        if self.cancel():
            raise InterruptedError("history_cancelled")
        assert_moneyflow_memory_budget()
        if self.started is not None:
            elapsed = self.clock() - self.started
            if elapsed < 0 or elapsed > MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS:
                raise MoneyflowContractError("history_unit_timeout")
            if elapsed - self.last_update >= 1:
                self.budget.update(bytes=self.bytes, last_updated=time.time())
                self.store.json(self.path, self.budget)
                self.last_update = elapsed

    def start(self, stage):
        self.check()
        if (
            self.budget["charged_seconds"] + MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS
            > MONEYFLOW_HISTORY_MAX_ELAPSED_SECONDS
        ):
            raise MoneyflowContractError("history_time_budget")
        self.budget["charged_seconds"] += MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS
        self.budget.update(
            stage=stage,
            bytes=0,
            last_updated=time.time(),
            reservation_seconds=MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
        )
        self.store.json(self.path, self.budget)
        self.started, self.last_update, self.bytes = self.clock(), 0, 0

    def finish(self):
        if self.started is None:
            return
        spent = max(0, self.clock() - self.started)
        self.budget["charged_seconds"] += spent - MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS
        self.budget.update(
            reservation_seconds=0, last_updated=time.time(), bytes=self.bytes
        )
        self.started = None
        self.store.json(self.path, self.budget)


class _Sink:
    def __init__(self, handle, control):
        self.handle, self.control = handle, control

    def write(self, data):
        self.control.check()
        if not isinstance(data, bytes) or len(data) > MONEYFLOW_HISTORY_STREAM_BYTES:
            raise MoneyflowContractError("history_stream_chunk")
        if self.control.bytes + len(data) > MONEYFLOW_HISTORY_MAX_CSV_BYTES:
            raise MoneyflowContractError("history_csv_bytes_budget")
        self.control.store.reserve(len(data))
        self.handle.write(data)
        self.control.bytes += len(data)
        self.control.store.used += len(data)
        self.control.check()


def _attempt_path(unit_directory, attempt):
    if not isinstance(attempt, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise MoneyflowContractError("history_checkpoint_attempt")
    directory = unit_directory / attempt
    if directory.is_symlink():
        raise MoneyflowContractError("history_checkpoint_symlink")
    return directory


def _physical_proof(unit_directory, receipt, phase, plan, unit_id, control):
    proof = receipt.get(phase)
    if not isinstance(proof, dict):
        raise MoneyflowContractError("history_checkpoint_proof")
    path = _attempt_path(unit_directory, receipt.get(phase + "_attempt")) / "source.csv"
    control.check()
    if (
        path.is_symlink()
        or not path.is_file()
        or not isinstance(proof.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", proof["sha256"])
    ):
        raise MoneyflowContractError("history_checkpoint_proof")
    if (
        type(proof.get("rows")) is not int
        or type(proof.get("bytes")) is not int
        or proof.get("rows") != plan.source_units[unit_id].row_count
        or proof.get("bytes") != path.stat().st_size
        or path.stat().st_size > MONEYFLOW_HISTORY_MAX_CSV_BYTES
    ):
        raise MoneyflowContractError("history_checkpoint_csv_changed")
    control.check()
    # Prove boundary facts from the file, rather than trusting edited JSON keys.
    control.start("resume_audit")
    request = MoneyflowHistoryCopyRequest(
        plan,
        unit_id,
        path.parent / "source.sql",
        tuple(receipt["after_key"]) if receipt.get("after_key") else None,
        tuple(receipt["export"]["last_key"])
        if phase == "verification" and plan.dataset == "moneyflow"
        else None,
    )
    try:
        if _audit(path, request, control) != proof:
            raise MoneyflowContractError("history_checkpoint_csv_changed")
    finally:
        control.finish()
    control.check()
    return proof


def export_moneyflow_history_unit(
    plan,
    unit_id: int,
    *,
    staging_root: Path,
    operation_id: str,
    source,
    cancel=lambda: False,
    clock=time.monotonic,
) -> dict:
    """Export/verify one unit. A caller must own the operation's exclusive writer.

    There is deliberately no full-history APPLY, job, parallel runner or event API.
    Recovery trusts no arbitrary paths from JSON; both successful CSVs are retained.
    """
    validate_moneyflow_history_plan(plan)
    if type(unit_id) is not int or not 0 <= unit_id < len(plan.source_units):
        raise MoneyflowContractError("history_source_unit")
    base = moneyflow_candidate_directory(
        staging_root, operation_id, plan.cutoff, dataset=plan.dataset
    )
    directory = base / "history_export"
    # Existing helper checks ancestors through base; check all export children too.
    if directory.is_symlink():
        raise MoneyflowContractError("history_checkpoint_symlink")
    existing = staging_root
    while not existing.exists():
        existing = existing.parent
    admission_file = directory / "plan.json"
    minimum_free = (
        2 * MONEYFLOW_HISTORY_MAX_CSV_BYTES
        if admission_file.exists()
        else MONEYFLOW_HISTORY_MIN_FREE_BYTES
    )
    if shutil.disk_usage(existing).free < minimum_free:
        raise MoneyflowContractError("history_free_space")
    if cancel():
        raise InterruptedError("history_cancelled")
    directory.mkdir(parents=True, exist_ok=True)
    store = _Store(directory)
    identity = _identity(plan)
    control = _Control(store, identity, unit_id, len(plan.source_units), clock, cancel)
    manifest_path = directory / "plan.json"
    if manifest_path.exists():
        if _read_json(manifest_path) != {
            **identity,
            "dataset": plan.dataset,
            "cutoff": plan.cutoff,
            "total_units": len(plan.source_units),
        }:
            raise MoneyflowContractError("history_plan_changed")
    else:
        store.json(
            manifest_path,
            {
                **identity,
                "dataset": plan.dataset,
                "cutoff": plan.cutoff,
                "total_units": len(plan.source_units),
            },
        )
    after_key = None
    if unit_id:
        previous_directory = directory / f"unit-{unit_id - 1:06d}"
        previous = _read_json(previous_directory / "checkpoint.json")
        _validate_receipt(previous, identity, unit_id - 1)
        if previous["stage"] != "verified":
            raise MoneyflowContractError("history_previous_unit_not_verified")
        proof = _physical_proof(
            previous_directory, previous, "export", plan, unit_id - 1, control
        )
        _physical_proof(
            previous_directory,
            previous,
            "verification",
            plan,
            unit_id - 1,
            control,
        )
        if previous["export"] != previous["verification"]:
            raise MoneyflowContractError("history_source_changed")
        if plan.dataset == "moneyflow":
            after_key = tuple(proof["last_key"])
    unit_directory = directory / f"unit-{unit_id:06d}"
    if unit_directory.is_symlink():
        raise MoneyflowContractError("history_checkpoint_symlink")
    unit_directory.mkdir(exist_ok=True)
    checkpoint = unit_directory / "checkpoint.json"
    receipt = (
        _read_json(checkpoint)
        if checkpoint.exists()
        else {
            **identity,
            "unit_id": unit_id,
            "stage": "planned",
            "after_key": list(after_key) if after_key else None,
            "dates": list(plan.source_units[unit_id].dates),
            "expected_rows": plan.source_units[unit_id].row_count,
        }
    )
    _validate_receipt(receipt, identity, unit_id)
    if (
        receipt.get("after_key") != (list(after_key) if after_key else None)
        or receipt.get("dates") != list(plan.source_units[unit_id].dates)
        or receipt.get("expected_rows") != plan.source_units[unit_id].row_count
    ):
        raise MoneyflowContractError("history_checkpoint_scope_changed")
    if receipt["stage"] == "blocked":
        raise MoneyflowContractError("history_unit_blocked")
    if receipt["stage"] == "verified":
        original = _physical_proof(
            unit_directory, receipt, "export", plan, unit_id, control
        )
        verified = _physical_proof(
            unit_directory, receipt, "verification", plan, unit_id, control
        )
        if original != verified:
            raise MoneyflowContractError("history_source_changed")
        control.budget.update(
            stage="verified",
            completed_units=max(control.budget.get("completed_units", 0), unit_id + 1),
            total_units=len(plan.source_units),
            last_updated=time.time(),
        )
        store.json(control.path, control.budget)
        return receipt
    try:
        for phase, started, completed in (
            ("export", "exporting", "exported"),
            ("verification", "verifying", "verified"),
        ):
            control.check()
            if phase == "export" and receipt["stage"] in ("exported", "verifying"):
                _physical_proof(unit_directory, receipt, phase, plan, unit_id, control)
                continue
            attempt = receipt.get(phase + "_attempt")
            current = _attempt_path(unit_directory, attempt) if attempt else None
            through_key = (
                tuple(receipt["export"]["last_key"])
                if phase == "verification" and plan.dataset == "moneyflow"
                else None
            )
            # A complete rename with an interrupted checkpoint is safely re-audited.
            if current is None or not (current / "source.csv").exists():
                attempt = uuid4().hex
                current = _attempt_path(unit_directory, attempt)
                current.mkdir()
                receipt.update(
                    stage=started,
                    **{phase + "_attempt": attempt},
                    last_updated=time.time(),
                )
                store.json(checkpoint, receipt)
                control.start(started)
                request = MoneyflowHistoryCopyRequest(
                    plan, unit_id, current / "source.sql", after_key, through_key
                )
                with (current / "source.partial").open("xb") as handle:
                    control.budget["copy_transactions"] += 1
                    store.json(control.path, control.budget)
                    source.copy(request, _Sink(handle, control), control.check)
                    handle.flush()
                    os.fsync(handle.fileno())
                store.recount()
                control.check()
                proof = _audit(current / "source.partial", request, control)
                control.check()
                os.replace(current / "source.partial", current / "source.csv")
                descriptor = os.open(current, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            else:
                control.start(started)
                request = MoneyflowHistoryCopyRequest(
                    plan, unit_id, current / "source.sql", after_key, through_key
                )
                proof = _audit(current / "source.csv", request, control)
            control.finish()
            if phase == "verification" and proof != receipt["export"]:
                receipt.update(
                    stage="blocked",
                    error_code="history_source_changed",
                    verification=proof,
                    last_updated=time.time(),
                )
                store.json(checkpoint, receipt)
                raise MoneyflowContractError("history_source_changed")
            receipt.update(stage=completed, **{phase: proof}, last_updated=time.time())
            store.json(checkpoint, receipt)
            control.budget.update(
                stage=completed,
                completed_units=unit_id + (phase == "verification"),
                total_units=len(plan.source_units),
                last_updated=time.time(),
            )
            store.json(control.path, control.budget)
            control.check()
    except (InterruptedError, MoneyflowContractError) as error:
        control.finish()
        receipt.update(last_updated=time.time(), error_code=str(error))
        if isinstance(error, MoneyflowContractError) and str(error) not in (
            "history_unit_timeout",
            "history_source_failed",
        ):
            receipt["stage"] = "blocked"
        store.json(checkpoint, receipt)
        raise
    return receipt


def _validate_receipt(receipt, identity, unit_id):
    if (
        any(receipt.get(key) != value for key, value in identity.items())
        or type(receipt.get("unit_id")) is not int
        or receipt["unit_id"] != unit_id
        or receipt.get("stage")
        not in {"planned", "exporting", "exported", "verifying", "verified", "blocked"}
    ):
        raise MoneyflowContractError("history_checkpoint_changed")


def _audit(path, request, control):
    return audit_moneyflow_history_csv(
        path,
        request,
        control.check,
        timeout_seconds=MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS
        - (control.clock() - control.started),
    )
