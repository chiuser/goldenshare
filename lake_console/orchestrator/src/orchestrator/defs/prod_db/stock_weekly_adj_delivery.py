"""Explicit, bounded READ ONLY queries through the approved Prod psql wrapper."""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from time import monotonic, sleep

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    check_capture_path,
    check_weekly_cancel,
)
from orchestrator.defs.prod_db.stock_weekly import PsqlWeeklyExporter
from orchestrator.defs.run_contracts.stock_weekly_adj_delivery import (
    ADJUSTED_DELIVERY_TABLE,
    DeliveryHeader,
    WeeklyAdjProdDeliveryBudget,
    delivery_batch_id,
    delivery_digest,
    delivery_revision,
)

HEADER_COLUMNS = tuple(DeliveryHeader.__dataclass_fields__)
RECORD_COLUMNS = (
    "revision",
    "contract_version",
    "batch_id",
    "unit_id",
    "record_kind",
    "intent",
    "outcome",
    "unit_kind",
    "cutoff_week",
    "start_date",
    "end_date",
    "ts_code",
    "payload",
    "rows_received",
    "rows_unique",
    "rows_written",
    "rows_preserved",
    "payload_digest",
    "scope_digest",
)


def _delivery_sql(projection, where, order, budget):
    # Identifiers and predicates originate solely from the builders below.
    return (
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
        f"SET LOCAL statement_timeout = '{budget.prod_statement_timeout_ms}ms';\n"
        "SET LOCAL work_mem = '32MB';\n"
        f"SELECT row_to_json(delivery) FROM (SELECT {projection} "
        f"FROM {ADJUSTED_DELIVERY_TABLE} WHERE {where} {order} LIMIT 1) AS delivery;\n"
        "ROLLBACK;\n"
    )


def build_next_closed_batch_sql(after_revision, budget):
    after_revision = delivery_revision(after_revision, allow_zero=True)
    projection = ",".join(
        "payload->'header' AS header" if n == "header" else f'"{n}"'
        for n in HEADER_COLUMNS
    )
    return _delivery_sql(
        projection,
        f"record_kind IN ('batch_closed','bootstrap_closed') AND revision>{after_revision}",
        "ORDER BY revision ASC",
        budget,
    )


def build_closed_batch_header_sql(batch_id, revision, budget):
    batch_id = delivery_batch_id(batch_id)
    revision = delivery_revision(revision)
    projection = ",".join(
        "payload->'header' AS header" if n == "header" else f'"{n}"'
        for n in HEADER_COLUMNS
    )
    return _delivery_sql(
        projection,
        f"batch_id='{batch_id}'::uuid AND revision={revision} "
        "AND record_kind IN ('batch_closed','bootstrap_closed')",
        "",
        budget,
    )


def build_delivery_record_sql(batch_id, kind, identity, budget):
    batch_id = delivery_batch_id(batch_id)
    if kind == "unit":
        identity = delivery_digest(identity)
        predicate = f"unit_id='{identity}'"
    elif kind == "plan" and identity == "plan":
        predicate = "unit_id='plan'"
    elif kind in ("batch_closed", "bootstrap_closed"):
        predicate = f"revision={delivery_revision(identity)}"
    else:
        raise ValueError("adjusted_delivery_query_kind_invalid")
    where = f"batch_id='{batch_id}'::uuid AND record_kind='{kind}' AND {predicate}"
    projection = ",".join(f'"{n}"' for n in RECORD_COLUMNS)
    return (
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
        f"SET LOCAL statement_timeout = '{budget.prod_statement_timeout_ms}ms';\n"
        "SET LOCAL work_mem = '32MB';\n"
        "SELECT row_to_json(control) FROM (SELECT count(*) AS record_count "
        f"FROM {ADJUSTED_DELIVERY_TABLE} WHERE {where}) AS control;\n"
        f"COPY (SELECT row_to_json(delivery) FROM (SELECT {projection} "
        f"FROM {ADJUSTED_DELIVERY_TABLE} WHERE {where} LIMIT 1) AS delivery) "
        "TO STDOUT WITH (FORMAT CSV);\nROLLBACK;\n"
    )


class PsqlWeeklyAdjDeliveryReader:
    """One connection at a time; sensor only reads the 4KiB header projection."""

    def __init__(self, *, budget=None, process_factory=subprocess.Popen):
        self.budget = budget or WeeklyAdjProdDeliveryBudget()
        self.process_factory = process_factory
        self.repo = Path(__file__).resolve().parents[6]

    def _query(self, sql, byte_limit, *, cancel, progress, record_csv=False):
        check_weekly_cancel(cancel)
        with tempfile.TemporaryDirectory(prefix="weekly-adj-control-") as directory:
            output_path = Path(directory).resolve() / "response.jsonl"
            check_capture_path(output_path)
            environment = os.environ.copy()
            environment["ENV_FILE"] = str(self.repo / ".env.web.local")
            command = [
                "bash",
                str(self.repo / "scripts/psql-remote.sh"),
                "-c",
                sql,
                "--",
                "-qAt",
                "-w",
            ]
            started = monotonic()
            with output_path.open("xb") as output:
                process = self.process_factory(
                    command,
                    cwd=self.repo,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                last_progress = started
                try:
                    while process.poll() is None:
                        check_weekly_cancel(cancel)
                        now = monotonic()
                        if now - started >= self.budget.prod_unit_seconds:
                            raise WeeklyCaptureError("adjusted_delivery_read_timeout")
                        if os.fstat(output.fileno()).st_size > byte_limit:
                            raise WeeklyCaptureError(
                                "adjusted_delivery_read_budget_exceeded"
                            )
                        if now - last_progress >= self.budget.progress_interval_seconds:
                            progress(
                                {
                                    "stage": "prod_delivery_read",
                                    "elapsed_seconds": now - started,
                                }
                            )
                            last_progress = now
                        sleep(0.1)
                    check_weekly_cancel(cancel)
                    if os.fstat(output.fileno()).st_size > byte_limit:
                        raise WeeklyCaptureError(
                            "adjusted_delivery_read_budget_exceeded"
                        )
                    if process.returncode != 0:
                        raise WeeklyCaptureError("adjusted_delivery_read_failed")
                    output.flush()
                finally:
                    PsqlWeeklyExporter._stop(process, 1)
            lines = output_path.read_text(encoding="utf-8").splitlines()
            if not lines:
                return None
            if record_csv:
                if len(lines) != 2 or lines[0] != '{"record_count":1}':
                    raise WeeklyCaptureError("adjusted_delivery_copy_count_mismatch")
                # COPY carries one explicitly projected immutable JSON record,
                # not a Python accumulation of the whole range. The file cap
                # is enforced before parsing, including CSV quote expansion.
                csv.field_size_limit(max(csv.field_size_limit(), byte_limit))
                fields = next(csv.reader(io.StringIO(lines[1])))
                if len(fields) != 1:
                    raise WeeklyCaptureError("adjusted_delivery_read_shape_invalid")
                lines = fields
            if len(lines) != 1:
                raise WeeklyCaptureError("adjusted_delivery_read_shape_invalid")
            try:
                value = json.loads(lines[0])
            except (ValueError, UnicodeError):
                raise WeeklyCaptureError(
                    "adjusted_delivery_read_shape_invalid"
                ) from None
            if not isinstance(value, dict):
                raise WeeklyCaptureError("adjusted_delivery_read_shape_invalid")
            return value

    def next_closed_batch(
        self, after_revision, *, cancel=lambda: False, progress=lambda _: None
    ):
        value = self._query(
            build_next_closed_batch_sql(after_revision, self.budget),
            self.budget.max_control_bytes,
            cancel=cancel,
            progress=progress,
        )
        if value is None:
            return None
        try:
            header = DeliveryHeader(**value)
            header.validate_budget(self.budget)
        except (TypeError, ValueError):
            raise WeeklyCaptureError("adjusted_delivery_header_invalid") from None
        return header

    def read_record(
        self, header, kind, identity, *, cancel=lambda: False, progress=lambda _: None
    ):
        header.validate_budget(self.budget)
        limit = (
            self.budget.max_plan_bytes + 16 * 1024
            if kind == "plan"
            else self.budget.max_unit_payload_bytes + 16 * 1024
            if kind == "unit"
            else self.budget.max_closure_bytes
        )
        record = self._query(
            build_delivery_record_sql(header.batch_id, kind, identity, self.budget),
            2 * limit + self.budget.max_control_bytes,
            cancel=cancel,
            progress=progress,
            record_csv=True,
        )
        if record is None:
            raise WeeklyCaptureError("adjusted_delivery_record_missing")
        if set(record) != set(RECORD_COLUMNS):
            raise WeeklyCaptureError("adjusted_delivery_record_shape_invalid")
        if (
            record["batch_id"] != header.batch_id
            or record["contract_version"] != header.contract_version
            or record["scope_digest"] != header.scope_digest
            or record["cutoff_week"] != header.cutoff_week
            or record["record_kind"] != kind
        ):
            raise WeeklyCaptureError("adjusted_delivery_record_identity_mismatch")
        return record

    def closed_batch_header(
        self, batch_id, revision, *, cancel=lambda: False, progress=lambda _: None
    ):
        value = self._query(
            build_closed_batch_header_sql(batch_id, revision, self.budget),
            self.budget.max_control_bytes,
            cancel=cancel,
            progress=progress,
        )
        if value is None:
            raise WeeklyCaptureError("adjusted_delivery_closed_batch_missing")
        try:
            header = DeliveryHeader(**value)
            header.validate_budget(self.budget)
        except (TypeError, ValueError):
            raise WeeklyCaptureError("adjusted_delivery_header_invalid") from None
        return header

    def verify_empty_batch(self, header):
        """One bounded aggregate control row; no market-data download or raw scan."""
        if (
            header.rows_written
            or header.anchor_partition is not None
            or header.header["bootstrap"]
        ):
            raise WeeklyCaptureError("adjusted_delivery_empty_batch_invalid")
        batch_id = delivery_batch_id(header.batch_id)
        sql = (
            "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
            f"SET LOCAL statement_timeout = '{self.budget.prod_statement_timeout_ms}ms';\n"
            "SELECT row_to_json(control) FROM (SELECT count(*) AS unit_count, "
            "coalesce(sum(rows_received),0) AS rows_received, "
            "coalesce(sum(rows_written),0) AS rows_written, "
            "coalesce(sum(rows_unique),0) AS rows_unique, "
            "coalesce(sum(rows_preserved),0) AS rows_preserved, "
            "coalesce(bool_and(payload='{"
            + '"rows":[]'
            + "}'::jsonb),true) AS empty_payloads "
            f"FROM {ADJUSTED_DELIVERY_TABLE} WHERE batch_id='{batch_id}'::uuid "
            f"AND record_kind='unit' AND revision<{header.revision}) AS control;\nROLLBACK;\n"
        )
        value = self._query(
            sql,
            self.budget.max_control_bytes,
            cancel=lambda: False,
            progress=lambda _: None,
        )
        expected = {
            "unit_count": header.header["unit_count"],
            "rows_received": header.rows_received,
            "rows_written": 0,
            "rows_unique": 0,
            "rows_preserved": header.rows_preserved,
            "empty_payloads": True,
        }
        if value != expected:
            raise WeeklyCaptureError("adjusted_delivery_empty_batch_invalid")


def header_record_matches(header, record):
    """Compare the closure to the sensor projection without adding payload to it."""
    actual = {n: record[n] for n in HEADER_COLUMNS if n != "header"}
    actual["header"] = record["payload"].get("header")
    return actual == asdict(header)
