"""Single date-unit Raw/Silver candidates and independent source verification."""

import fcntl
import io
import json
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    history_business_key_fields,
    history_schema,
    validate_moneyflow_history_plan,
)
from orchestrator.defs.bootstrap.moneyflow_history_receive import (
    audit_history_day,
    history_candidate_connection,
    history_source_difference,
    receive_history_rows,
)
from orchestrator.defs.bootstrap.moneyflow_history_source import (
    MoneyflowHistoryCopyRequest,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_directory,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_DUCKDB_MEMORY_LIMIT,
    MONEYFLOW_DUCKDB_THREADS,
    MONEYFLOW_HISTORY_MAX_BUFFER_BYTES,
    MONEYFLOW_HISTORY_MAX_DISK_BYTES,
    MONEYFLOW_HISTORY_MAX_ELAPSED_SECONDS,
    MONEYFLOW_HISTORY_MIN_FREE_BYTES,
    MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
    MONEYFLOW_HISTORY_STREAM_BYTES,
    MONEYFLOW_MAX_RSS_BYTES,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
)


def _identity(plan):
    return {
        "revision": "moneyflow_history_dates_v2",
        "plan_hash": plan.plan_hash,
        "schema_hash": plan.schema_hash,
        "source_counts_hash": plan.source_counts_hash,
        "limits": {
            "buffer_bytes": MONEYFLOW_HISTORY_MAX_BUFFER_BYTES,
            "disk_bytes": MONEYFLOW_HISTORY_MAX_DISK_BYTES,
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
        self.lock = threading.RLock()
        self.recount()

    def recount(self):
        with self.lock:
            self._recount()

    def _recount(self):
        self.used = 0
        for root, directories, files in os.walk(self.directory):
            for name in (*directories, *files):
                path = Path(root) / name
                if path.is_symlink():
                    raise MoneyflowContractError("history_checkpoint_symlink")
            for name in files:
                self.used += (Path(root) / name).stat().st_size
                self.reserve(0)

    def add_file(self, path):
        with self.lock:
            size = path.stat().st_size
            self.reserve(size)
            self.used += size

    def reserve(self, size):
        if self.used + size > MONEYFLOW_HISTORY_MAX_DISK_BYTES:
            raise MoneyflowContractError("history_disk_bytes_budget")

    def json(self, path, value):
        with self.lock:
            self._json(path, value)

    def _json(self, path, value):
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
        self.lock = store.lock
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

    def record_source_copy(self):
        with self.lock:
            self.budget["copy_transactions"] += 1
            self.budget["sql_statements"] = 4 * self.budget["copy_transactions"]
            self.budget["connections"] = self.budget["copy_transactions"]
            self.store.json(self.path, self.budget)

    def progress(self, **fields):
        with self.lock:
            self.budget.update(fields)
            self.budget["last_updated"] = time.time()
            self.store.json(self.path, self.budget)

    def check(self):
        with self.lock:
            self._check()

    def _check(self):
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
        with self.lock:
            self._start(stage)

    def _start(self, stage):
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
        with self.lock:
            self._finish()

    def _finish(self):
        if self.started is None:
            return
        spent = max(0, self.clock() - self.started)
        self.budget["charged_seconds"] += spent - MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS
        self.budget.update(
            reservation_seconds=0, last_updated=time.time(), bytes=self.bytes
        )
        self.started = None
        self.store.json(self.path, self.budget)


class _MemorySink:
    def __init__(self, buffer, control):
        self.buffer, self.control = buffer, control

    def write(self, data):
        self.control.check()
        if not isinstance(data, bytes) or len(data) > MONEYFLOW_HISTORY_STREAM_BYTES:
            raise MoneyflowContractError("history_stream_chunk")
        if self.control.bytes + len(data) > MONEYFLOW_HISTORY_MAX_BUFFER_BYTES:
            raise MoneyflowContractError("history_buffer_bytes_budget")
        self.buffer.write(data)
        self.control.bytes += len(data)
        self.control.check()


@contextmanager
def _writer_lock(directory):
    descriptor = os.open(
        directory / "writer.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise MoneyflowContractError("history_writer_active") from error
        yield
    finally:
        os.close(descriptor)


def _attempt_path(unit_directory, attempt):
    if not isinstance(attempt, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise MoneyflowContractError("history_checkpoint_attempt")
    directory = unit_directory / attempt
    if directory.is_symlink():
        raise MoneyflowContractError("history_checkpoint_symlink")
    return directory


def _receipt_scope(plan, unit_id, identity):
    unit = plan.units[unit_id]
    return {
        **identity,
        "unit_id": unit_id,
        "dates": list(unit.dates),
        "expected_rows": unit.row_count,
    }


def _validate_receipt(receipt, scope):
    if (
        any(receipt.get(key) != value for key, value in scope.items())
        or type(receipt.get("unit_id")) is not int
        or receipt.get("stage")
        not in {
            "planned",
            "reading",
            "candidates_complete",
            "verifying",
            "verified",
            "blocked",
        }
        or {
            "after_key",
            "through_key",
            "last_key",
            "export",
            "verification",
            "export_attempt",
        }
        & receipt.keys()
    ):
        raise MoneyflowContractError("history_checkpoint_changed")


def _fsync(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_candidate(db, query, params, path, control, store):
    if path.exists() or path.is_symlink():
        raise MoneyflowContractError("history_candidate_conflict")
    temporary = path.with_suffix(".parquet.partial")
    if temporary.exists() or temporary.is_symlink():
        raise MoneyflowContractError("history_candidate_conflict")
    control.check()
    # Both layers derive from <=32MiB input; reserve conservative headroom.
    # Charge each new file by stat, avoiding a repeated walk of prior batches.
    # On failed output, the exception path recounts retained partial files.
    store.reserve(2 * MONEYFLOW_HISTORY_MAX_BUFFER_BYTES)
    db.execute(
        f"COPY ({query}) TO $target (FORMAT PARQUET)",
        {**params, "target": str(temporary)},
    )
    control.check()
    _fsync(temporary)
    store.add_file(temporary)
    os.replace(temporary, path)
    _fsync(path.parent)
    control.check()


def _create_days(db, plan, unit_id, attempt, receipt, checkpoint, control, store):
    fields = ",".join(f'"{column.name}"' for column in history_schema(plan.dataset))
    keys = ",".join(f'"{key}"' for key in history_business_key_fields(plan.dataset))
    expected = dict(receipt["source_proof"]["date_counts"])
    for day in plan.units[unit_id].dates:
        control.check()
        directory = attempt / day
        directory.mkdir()
        raw, silver = directory / "raw.parquet", directory / "silver.parquet"
        _copy_candidate(
            db,
            f"SELECT {fields} FROM history_rows WHERE trade_date=$day ORDER BY {keys}",
            {"day": day.replace("-", "")},
            raw,
            control,
            store,
        )
        projection = ",".join(
            'strptime("trade_date",\'%Y%m%d\')::DATE AS "trade_date"'
            if column.name == "trade_date"
            else f'"{column.name}"'
            for column in history_schema(plan.dataset)
        )
        _copy_candidate(
            db,
            f"SELECT {projection} FROM read_parquet($raw,hive_partitioning=false)",
            {"raw": str(raw)},
            silver,
            control,
            store,
        )
        if (
            audit_history_day(db, raw, silver, day, dataset=plan.dataset)
            != expected[day]
        ):
            raise MoneyflowContractError("history_candidate_row_count")
        receipt["files"].append(
            {
                "trade_date": day,
                "rows": expected[day],
                "raw_sha256": candidate_file_hash(raw),
                "silver_sha256": candidate_file_hash(silver),
            }
        )
        receipt["last_updated"] = time.time()
        store.json(checkpoint, receipt)
        control.progress(current_date=day, generated_dates=len(receipt["files"]))
        control.check()


def _audit_files(unit_directory, receipt, plan, unit_id, control):
    unit = plan.units[unit_id]
    files = receipt.get("files")
    expected = {
        fact.trade_date: fact.row_count
        for fact in plan.date_counts
        if fact.trade_date in unit.dates
    }
    if not isinstance(files, list) or len(files) != len(unit.dates):
        raise MoneyflowContractError("history_checkpoint_files")
    attempt = _attempt_path(unit_directory, receipt.get("attempt"))
    raw_files = []
    with history_candidate_connection(unit_directory, control.check) as db:
        for day, fact in zip(unit.dates, files, strict=True):
            control.check()
            if (
                not isinstance(fact, dict)
                or fact.get("trade_date") != day
                or type(fact.get("rows")) is not int
                or fact["rows"] != expected[day]
            ):
                raise MoneyflowContractError("history_checkpoint_files")
            directory = attempt / day
            raw, silver = directory / "raw.parquet", directory / "silver.parquet"
            if directory.is_symlink() or any(
                path.is_symlink() or not path.is_file() for path in (raw, silver)
            ):
                raise MoneyflowContractError("history_checkpoint_files")
            if any(
                not re.fullmatch(r"[0-9a-f]{64}", str(fact.get(layer + "_sha256", "")))
                or candidate_file_hash(path) != fact[layer + "_sha256"]
                for layer, path in (("raw", raw), ("silver", silver))
            ):
                raise MoneyflowContractError("history_candidate_changed")
            if (
                audit_history_day(db, raw, silver, day, dataset=plan.dataset)
                != expected[day]
            ):
                raise MoneyflowContractError("history_candidate_row_count")
            raw_files.append(raw)
    return raw_files


def build_moneyflow_history_unit_candidates(
    plan,
    unit_id: int,
    *,
    staging_root: Path,
    operation_id: str,
    source,
    cancel=lambda: False,
    clock=time.monotonic,
) -> dict:
    """Build/verify one date unit. No formal promotion, CLI, jobs or event writes.

    Complete candidates are re-audited and independently source-verified on resume;
    replay never rewrites them. Full cohort budget/activation remains a runner gate.
    """
    validate_moneyflow_history_plan(plan)
    if type(unit_id) is not int or not 0 <= unit_id < len(plan.units):
        raise MoneyflowContractError("history_date_unit")
    base = moneyflow_candidate_directory(
        staging_root, operation_id, plan.cutoff, dataset=plan.dataset
    )
    if (base / "history_export").exists() or (base / "history_export").is_symlink():
        raise MoneyflowContractError("history_legacy_operation")
    directory = base / "history_candidates"
    if directory.is_symlink():
        raise MoneyflowContractError("history_checkpoint_symlink")
    existing = staging_root
    while not existing.exists():
        existing = existing.parent
    minimum_free = (
        2 * MONEYFLOW_HISTORY_MAX_BUFFER_BYTES
        if (directory / "plan.json").exists()
        else MONEYFLOW_HISTORY_MIN_FREE_BYTES
    )
    if shutil.disk_usage(existing).free < minimum_free:
        raise MoneyflowContractError("history_free_space")
    if cancel():
        raise InterruptedError("history_cancelled")
    directory.mkdir(parents=True, exist_ok=True)
    with _writer_lock(directory):
        return _build_unit(directory, plan, unit_id, source, cancel, clock)


def _build_unit(directory, plan, unit_id, source, cancel, clock):
    store = _Store(directory)
    identity = _identity(plan)
    manifest = {
        **identity,
        "dataset": plan.dataset,
        "cutoff": plan.cutoff,
        "total_units": len(plan.units),
    }
    manifest_path = directory / "plan.json"
    if manifest_path.exists():
        if _read_json(manifest_path) != manifest:
            raise MoneyflowContractError("history_plan_changed")
    else:
        store.json(manifest_path, manifest)
    control = _Control(store, identity, unit_id, len(plan.units), clock, cancel)
    control.progress(
        dates=list(plan.units[unit_id].dates),
        expected_rows=plan.units[unit_id].row_count,
        eta="暂无法估算",
    )
    if unit_id:
        previous_directory = directory / f"unit-{unit_id - 1:06d}"
        previous = _read_json(previous_directory / "checkpoint.json")
        _validate_receipt(previous, _receipt_scope(plan, unit_id - 1, identity))
        if previous["stage"] != "verified":
            raise MoneyflowContractError("history_previous_unit_not_verified")
        control.start("previous_candidates_audit")
        try:
            _audit_files(previous_directory, previous, plan, unit_id - 1, control)
        finally:
            control.finish()
    unit_directory = directory / f"unit-{unit_id:06d}"
    if unit_directory.is_symlink():
        raise MoneyflowContractError("history_checkpoint_symlink")
    unit_directory.mkdir(exist_ok=True)
    checkpoint = unit_directory / "checkpoint.json"
    scope = _receipt_scope(plan, unit_id, identity)
    receipt = (
        _read_json(checkpoint)
        if checkpoint.exists()
        else {**scope, "stage": "planned", "files": []}
    )
    _validate_receipt(receipt, scope)
    if receipt["stage"] == "blocked":
        raise MoneyflowContractError("history_unit_blocked")
    try:
        # A full per-day manifest survives a crash before the unit stage update.
        complete = isinstance(receipt.get("files"), list) and len(
            receipt["files"]
        ) == len(plan.units[unit_id].dates)
        if complete:
            control.start("candidates_audit")
            try:
                _audit_files(unit_directory, receipt, plan, unit_id, control)
            finally:
                control.finish()
        elif receipt["stage"] in {"candidates_complete", "verifying", "verified"}:
            raise MoneyflowContractError("history_checkpoint_files")
        else:
            attempt = _attempt_path(unit_directory, uuid4().hex)
            attempt.mkdir()
            receipt.update(
                stage="reading",
                attempt=attempt.name,
                files=[],
                last_updated=time.time(),
            )
            receipt.pop("error_code", None)
            store.json(checkpoint, receipt)
            control.start("reading")
            try:
                with io.BytesIO() as buffer:
                    control.record_source_copy()
                    request = MoneyflowHistoryCopyRequest(
                        plan, unit_id, attempt / "source.sql"
                    )
                    source.copy(request, _MemorySink(buffer, control), control.check)
                    if request.sql_path.is_file():
                        store.add_file(request.sql_path)
                    with history_candidate_connection(attempt, control.check) as db:
                        receipt["source_proof"] = receive_history_rows(
                            db, buffer, plan, unit_id, control.check
                        )
                        # Release Python's wire buffer before writing the daily files.
                        buffer.seek(0)
                        buffer.truncate(0)
                        store.json(checkpoint, receipt)
                        _create_days(
                            db,
                            plan,
                            unit_id,
                            attempt,
                            receipt,
                            checkpoint,
                            control,
                            store,
                        )
            finally:
                control.finish()
        receipt.update(stage="candidates_complete", last_updated=time.time())
        store.json(checkpoint, receipt)
        verification = _attempt_path(unit_directory, uuid4().hex)
        verification.mkdir()
        receipt.update(stage="verifying", last_updated=time.time())
        store.json(checkpoint, receipt)
        control.start("verifying")
        try:
            with io.BytesIO() as buffer:
                control.record_source_copy()
                request = MoneyflowHistoryCopyRequest(
                    plan, unit_id, verification / "source.sql"
                )
                source.copy(request, _MemorySink(buffer, control), control.check)
                if request.sql_path.is_file():
                    store.add_file(request.sql_path)
                with history_candidate_connection(verification, control.check) as db:
                    proof = receive_history_rows(
                        db, buffer, plan, unit_id, control.check
                    )
                    buffer.seek(0)
                    buffer.truncate(0)
                    attempt = _attempt_path(unit_directory, receipt["attempt"])
                    raw_files = [
                        attempt / day / "raw.parquet"
                        for day in plan.units[unit_id].dates
                    ]
                    count, samples = history_source_difference(
                        db, raw_files, dataset=plan.dataset
                    )
                    receipt.update(
                        verification_proof=proof,
                        difference_count=count,
                        difference_samples=samples,
                    )
                    if count:
                        raise MoneyflowContractError("history_source_changed")
        finally:
            control.finish()
        receipt.update(stage="verified", last_updated=time.time())
        store.json(checkpoint, receipt)
        control.budget.update(
            stage="verified",
            completed_units=max(control.budget.get("completed_units", 0), unit_id + 1),
            total_units=len(plan.units),
            last_updated=time.time(),
        )
        store.json(control.path, control.budget)
        control.check()
        return receipt
    except (InterruptedError, MoneyflowContractError) as error:
        control.finish()
        receipt.update(last_updated=time.time(), error_code=str(error))
        if isinstance(error, MoneyflowContractError) and str(error) not in {
            "history_unit_timeout",
            "history_source_failed",
        }:
            receipt["stage"] = "blocked"
        store.recount()
        store.json(checkpoint, receipt)
        raise
