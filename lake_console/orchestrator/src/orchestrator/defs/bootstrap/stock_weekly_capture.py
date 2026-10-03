"""Durable, bounded source captures. No formal Lake or instance writes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyUnit,
    StockWeeklySource,
    WeeklyPlanManifest,
    WeeklySourceUnit,
    stable_weekly_hash,
    weekly_column_specs,
    weekly_key_columns,
    weekly_required_columns,
    weekly_schema_hash,
)

CancelProbe = Callable[[], bool]
SourceUnit = ProdWeeklyUnit | WeeklySourceUnit


class WeeklyCaptureError(RuntimeError):
    """A public reason code without credentials or source exception text."""


def check_weekly_cancel(cancel: CancelProbe) -> None:
    if cancel():
        raise WeeklyCaptureError("canceled")


def capture_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_capture_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise WeeklyCaptureError("capture_path_invalid")
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise WeeklyCaptureError("capture_symlink_forbidden")


def _atomic_json(path: Path, payload: dict) -> None:
    check_capture_path(path)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.pending")
    with temporary.open("x") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def weekly_unit_identity(unit: SourceUnit) -> str:
    return stable_weekly_hash(asdict(unit))


def validate_weekly_capture_relation(
    connection, relation: str, unit: SourceUnit
) -> int:
    """Transport identity/shape checks, preserving business NULL values."""
    source = StockWeeklySource(unit.source)
    required = weekly_required_columns(source)
    nulls = " OR ".join(f'"{name}" IS NULL' for name in required)
    if connection.execute(f"SELECT count(*) FROM {relation} WHERE {nulls}").fetchone()[
        0
    ]:
        raise WeeklyCaptureError("required_field_null")
    if connection.execute(
        f"""SELECT count(*) FROM {relation} WHERE
        NOT regexp_full_match(ts_code, '[0-9]{{6}}\\.(SH|SZ|BJ)') OR
        NOT regexp_full_match(trade_date, '[0-9]{{8}}') OR
        try_strptime(trade_date, '%Y%m%d') IS NULL"""
    ).fetchone()[0]:
        raise WeeklyCaptureError("source_key_invalid")
    keys = ",".join(f'"{key}"' for key in weekly_key_columns(source))
    count, distinct = connection.execute(
        f"SELECT count(*), count(DISTINCT ({keys})) FROM {relation}"
    ).fetchone()
    if count != distinct:
        raise WeeklyCaptureError("source_duplicate_key")
    if isinstance(unit, ProdWeeklyUnit):
        codes = list(unit.sorted_codes)
        bad = connection.execute(
            f"""SELECT count(*) FROM {relation} WHERE freq != 'week'
            OR ts_code NOT IN (SELECT unnest(?))
            OR trade_date < ? OR trade_date >= ?""",
            [
                codes,
                unit.source_date_start.strftime("%Y%m%d"),
                unit.source_date_end.strftime("%Y%m%d"),
            ],
        ).fetchone()[0]
    else:
        bad = connection.execute(
            f"""SELECT count(*) FROM {relation} WHERE ts_code != ?
            OR trade_date < ? OR trade_date > ?""",
            [
                unit.ts_code,
                unit.request_start.strftime("%Y%m%d"),
                unit.request_end.strftime("%Y%m%d"),
            ],
        ).fetchone()[0]
        # This source promises one observation per code/week. Do not silently merge.
        weeks = connection.execute(
            f"SELECT count(DISTINCT date_trunc('week', strptime(trade_date,'%Y%m%d'))) FROM {relation}"
        ).fetchone()[0]
        if weeks != count:
            raise WeeklyCaptureError("source_week_conflict")
    if bad:
        raise WeeklyCaptureError("source_range_mismatch")
    if count > unit.max_rows:
        raise WeeklyCaptureError("unit_row_budget_exceeded")
    return int(count)


def verify_weekly_plan_evidence(manifest: WeeklyPlanManifest) -> None:
    """Verify frozen external inputs before acquiring any source work."""
    repo = Path(__file__).resolve().parents[6]
    temporary = Path(tempfile.gettempdir()).resolve()
    allowed = (
        repo / "reports",
        Path(DEFAULT_LAKE_STAGING_ROOT),
        temporary,
        Path("/private/tmp"),
    )
    references = {(manifest.evidence_ref, manifest.evidence_hash)}
    for unit in manifest.units:
        if isinstance(unit, WeeklySourceUnit):
            if unit.expected_key_ref != manifest.evidence_ref:
                raise WeeklyCaptureError("expected_key_reference_mismatch")
            # unit.expected_key_hash hashes the sorted selected week keys, not file bytes.
            references.update(unit.source_evidence)
    for reference, expected_hash in sorted(references):
        path = Path(reference)
        if not path.is_absolute():
            path = repo / path
        check_capture_path(path)
        if not any(path.is_relative_to(root) for root in allowed):
            raise WeeklyCaptureError("source_evidence_root_forbidden")
        if not path.is_file() or capture_file_hash(path) != expected_hash:
            raise WeeklyCaptureError("source_evidence_hash_mismatch")


class WeeklyCaptureStore:
    """One frozen plan, OS writer lock, source chunks and per-unit receipts."""

    def __init__(self, root: Path, manifest: WeeklyPlanManifest):
        root = Path(root)
        check_capture_path(root)
        staging = Path(DEFAULT_LAKE_STAGING_ROOT)
        # Isolated test/sample outputs are allowed only in the OS temporary root.
        temporary = Path(tempfile.gettempdir()).resolve()
        if not (
            root.is_relative_to(staging)
            or root.is_relative_to(temporary)
            or root.is_relative_to(Path("/private/tmp"))
        ):
            raise WeeklyCaptureError("capture_root_forbidden")
        if not re.fullmatch("[a-f0-9]{64}", manifest.plan_hash):
            raise WeeklyCaptureError("plan_hash_invalid")
        if any(unit.source != manifest.source for unit in manifest.units):
            raise WeeklyCaptureError("manifest_source_mismatch")
        self.manifest = manifest
        self.root = root / "stock_weekly_raw" / manifest.plan_hash
        check_capture_path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locked = False
        self._unit_hashes = {
            unit.unit_id: weekly_unit_identity(unit) for unit in manifest.units
        }
        if len(self._unit_hashes) != len(manifest.units):
            raise WeeklyCaptureError("duplicate_unit_id")

    @contextmanager
    def locked(self) -> Iterator[WeeklyCaptureStore]:
        check_capture_path(self.root / "capture.lock")
        with (self.root / "capture.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WeeklyCaptureError("capture_writer_active") from None
            self._locked = True
            self._file_count = len(list(self.root.glob("units/*/attempt-*/*.parquet")))
            try:
                payload = {
                    "plan_hash": self.manifest.plan_hash,
                    "manifest_hash": stable_weekly_hash(asdict(self.manifest)),
                }
                plan_path = self.root / "plan.json"
                if plan_path.exists():
                    if self._read_json(plan_path) != payload:
                        raise WeeklyCaptureError("plan_changed")
                else:
                    _atomic_json(plan_path, payload)
                yield self
            finally:
                self._locked = False
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _require_lock(self) -> None:
        if not self._locked:
            raise WeeklyCaptureError("capture_lock_required")

    def unit_directory(self, unit: SourceUnit) -> Path:
        self._require_lock()
        if self._unit_hashes.get(unit.unit_id) != weekly_unit_identity(unit):
            raise WeeklyCaptureError("unit_not_in_frozen_plan")
        directory = self.root / "units" / self._unit_hashes[unit.unit_id]
        check_capture_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _read_json(self, path: Path) -> dict:
        check_capture_path(path)
        if path.stat().st_size > 1024 * 1024:
            raise WeeklyCaptureError("receipt_size_exceeded")
        with path.open() as stream:
            return json.load(stream)

    def begin_attempt(self, unit: SourceUnit) -> Path:
        directory = self.unit_directory(unit)
        checkpoint = directory / "checkpoint.json"
        state = self._read_json(checkpoint) if checkpoint.exists() else {}
        if state.get("unit_hash") not in (None, weekly_unit_identity(unit)):
            raise WeeklyCaptureError("checkpoint_identity_mismatch")
        existing = [
            int(path.name.split("-")[1])
            for path in directory.glob("attempt-*")
            if re.fullmatch("attempt-[0-9]{3}", path.name)
        ]
        attempts = max(int(state.get("attempts", 0)), max(existing, default=0)) + 1
        if attempts > self.manifest.budget.max_retries + 1:
            raise WeeklyCaptureError("unit_attempt_budget_exceeded")
        attempt = directory / f"attempt-{attempts:03d}"
        check_capture_path(attempt)
        # Existing interrupted evidence is never deleted or overwritten.
        attempt.mkdir(exist_ok=False)
        _atomic_json(
            checkpoint,
            {
                "attempts": attempts,
                "status": "fetching",
                "started_at": datetime.now(UTC).isoformat(),
                "unit_hash": weekly_unit_identity(unit),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        return attempt

    def mark_failed(self, unit: SourceUnit, reason: str) -> None:
        path = self.unit_directory(unit) / "checkpoint.json"
        state = self._read_json(path)
        state.update(
            status="canceled" if reason == "canceled" else "failed",
            reason_code=reason,
            updated_at=datetime.now(UTC).isoformat(),
        )
        _atomic_json(path, state)

    def reserve_request(self) -> None:
        self._require_lock()
        path = self.root / "requests.json"
        state = self._read_json(path) if path.exists() else {"attempts": 0}
        if state["attempts"] >= self.manifest.request_cap:
            raise WeeklyCaptureError("phase_request_budget_exceeded")
        state.update(
            attempts=state["attempts"] + 1,
            ended_at=None,
            started_at=datetime.now(UTC).timestamp(),
        )
        _atomic_json(path, state)

    def request_ended(self) -> None:
        path = self.root / "requests.json"
        state = self._read_json(path)
        state["ended_at"] = datetime.now(UTC).timestamp()
        _atomic_json(path, state)

    def next_request_at(self) -> float:
        path = self.root / "requests.json"
        if not path.exists():
            return 0.0
        state = self._read_json(path)
        ended = state["ended_at"]
        if ended is None:
            ended = state["started_at"] + self.manifest.budget.call_timeout_seconds
        return ended + self.manifest.budget.minimum_interval_seconds

    def write_chunk(
        self,
        connection,
        frame: pd.DataFrame,
        unit: SourceUnit,
        attempt: Path,
        index: int,
    ) -> dict:
        directory = self.unit_directory(unit)
        check_capture_path(attempt)
        if attempt.parent != directory or not re.fullmatch(
            "attempt-[0-9]{3}", attempt.name
        ):
            raise WeeklyCaptureError("attempt_path_invalid")
        specs = weekly_column_specs(unit.source)
        fields = tuple(name for name, _, _ in specs)
        if tuple(frame.columns) != fields:
            raise WeeklyCaptureError("source_schema_mismatch")
        if len(frame) > min(unit.max_rows, self.manifest.budget.fetch_batch_rows):
            raise WeeklyCaptureError("chunk_row_budget_exceeded")
        if self._file_count >= self.manifest.budget.max_phase_files:
            raise WeeklyCaptureError("phase_file_budget_exceeded")
        connection.register("weekly_capture_input", frame)
        try:
            # CAST may round decimals; reject nonzero digits beyond the declared scale first.
            for name, kind, _ in specs:
                if kind.startswith("DECIMAL"):
                    bad = connection.execute(
                        f'''SELECT count(*) FROM weekly_capture_input WHERE "{name}" IS NOT NULL
                        AND NOT regexp_full_match(CAST("{name}" AS VARCHAR),
                        '[+-]?[0-9]+(\\.[0-9]{{0,4}}0*)?')'''
                    ).fetchone()[0]
                    if bad:
                        raise WeeklyCaptureError("decimal_precision_loss")
                elif kind == "DOUBLE":
                    bad = connection.execute(
                        f'SELECT count(*) FROM weekly_capture_input WHERE "{name}" IS NOT NULL '
                        f'AND (try_cast("{name}" AS DOUBLE) IS NULL OR NOT isfinite(try_cast("{name}" AS DOUBLE)))'
                    ).fetchone()[0]
                    if bad:
                        raise WeeklyCaptureError("source_numeric_invalid")
            projection = ",".join(
                f'CAST("{name}" AS {kind}) AS "{name}"' for name, kind, _ in specs
            )
            connection.execute(
                f"CREATE OR REPLACE TEMP TABLE weekly_capture_chunk AS SELECT {projection} FROM weekly_capture_input"
            )
            count = validate_weekly_capture_relation(
                connection, "weekly_capture_chunk", unit
            )
            path = attempt / f"chunk-{index:04d}.parquet"
            if path.exists():
                raise WeeklyCaptureError("capture_chunk_exists")
            pending = path.with_suffix(".pending")
            connection.execute(
                "COPY weekly_capture_chunk TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(pending)],
            )
            with pending.open("rb") as stream:
                os.fsync(stream.fileno())
            readback = connection.execute(
                "SELECT count(*) FROM read_parquet(?, hive_partitioning=false)",
                [str(pending)],
            ).fetchone()[0]
            differences = connection.execute(
                """SELECT count(*) FROM (
                (SELECT * FROM weekly_capture_chunk EXCEPT ALL SELECT * FROM read_parquet(?, hive_partitioning=false))
                UNION ALL
                (SELECT * FROM read_parquet(?, hive_partitioning=false) EXCEPT ALL SELECT * FROM weekly_capture_chunk)
            )""",
                [str(pending), str(pending)],
            ).fetchone()[0]
            if differences:
                raise WeeklyCaptureError("capture_value_mismatch")
            if readback != count:
                raise WeeklyCaptureError("capture_readback_mismatch")
            os.replace(pending, path)
            self._file_count += 1
            _sync_directory(attempt)
            return {
                "path": str(path.relative_to(directory)),
                "rows": count,
                "sha256": capture_file_hash(path),
            }
        finally:
            connection.unregister("weekly_capture_input")

    def _validate_receipt(self, connection, unit: SourceUnit, receipt: dict) -> None:
        directory = self.unit_directory(unit)
        if (
            receipt.get("plan_hash") != self.manifest.plan_hash
            or receipt.get("unit_hash") != weekly_unit_identity(unit)
            or receipt.get("schema_hash") != weekly_schema_hash(unit.source)
        ):
            raise WeeklyCaptureError("receipt_identity_mismatch")
        chunks = receipt.get("chunks", [])
        if not chunks or len(chunks) > self.manifest.budget.max_phase_files:
            raise WeeklyCaptureError("capture_evidence_missing")
        paths = []
        for chunk in chunks:
            path = directory / chunk["path"]
            check_capture_path(path)
            if (
                not path.is_relative_to(directory)
                or capture_file_hash(path) != chunk["sha256"]
            ):
                raise WeeklyCaptureError("capture_hash_mismatch")
            paths.append(str(path))
        connection.execute(
            "CREATE OR REPLACE TEMP TABLE weekly_capture_unit AS SELECT * FROM read_parquet(?, hive_partitioning=false, union_by_name=false)",
            [paths],
        )
        observed = tuple(
            (row[0], row[1])
            for row in connection.execute("DESCRIBE weekly_capture_unit").fetchall()
        )
        expected = tuple(
            (name, kind) for name, kind, _ in weekly_column_specs(unit.source)
        )
        if observed != expected:
            raise WeeklyCaptureError("capture_schema_mismatch")
        count = validate_weekly_capture_relation(
            connection, "weekly_capture_unit", unit
        )
        if count != receipt["source_rows"] or count != sum(
            chunk["rows"] for chunk in chunks
        ):
            raise WeeklyCaptureError("capture_count_mismatch")
        if receipt["status"] != ("success_empty" if count == 0 else "captured"):
            raise WeeklyCaptureError("capture_status_mismatch")

    def seal(
        self,
        connection,
        unit: SourceUnit,
        chunks: list[dict],
        source_rows: int,
        evidence: dict,
    ) -> dict:
        directory = self.unit_directory(unit)
        receipt = {
            "plan_hash": self.manifest.plan_hash,
            "unit_hash": weekly_unit_identity(unit),
            "schema_hash": weekly_schema_hash(unit.source),
            "status": "success_empty" if source_rows == 0 else "captured",
            "source_rows": source_rows,
            "chunks": chunks,
            "source_evidence": evidence,
            "started_at": self._read_json(directory / "checkpoint.json")["started_at"],
            "captured_at": datetime.now(UTC).isoformat(),
        }
        self._validate_receipt(connection, unit, receipt)
        _atomic_json(directory / "receipt.json", receipt)
        self._complete_checkpoint(unit, receipt)
        return receipt

    def _complete_checkpoint(self, unit: SourceUnit, receipt: dict) -> None:
        path = self.unit_directory(unit) / "checkpoint.json"
        state = self._read_json(path) if path.exists() else {"attempts": 0}
        state.update(
            status=receipt["status"],
            unit_hash=weekly_unit_identity(unit),
            started_at=receipt["started_at"],
            receipt_hash=stable_weekly_hash(receipt),
            updated_at=datetime.now(UTC).isoformat(),
        )
        _atomic_json(path, state)

    def resume(self, connection, unit: SourceUnit) -> dict | None:
        path = self.unit_directory(unit) / "receipt.json"
        if not path.exists():
            return None
        receipt = self._read_json(path)
        self._validate_receipt(connection, unit, receipt)
        checkpoint = path.with_name("checkpoint.json")
        if checkpoint.exists():
            state = self._read_json(checkpoint)
            if state.get("receipt_hash") not in (None, stable_weekly_hash(receipt)):
                raise WeeklyCaptureError("receipt_hash_mismatch")
        self._complete_checkpoint(unit, receipt)
        return receipt
