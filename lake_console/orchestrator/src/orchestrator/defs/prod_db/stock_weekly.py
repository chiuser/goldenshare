"""Whitelisted weekly Prod source: one bounded, rollback-only snapshot per unit."""

from __future__ import annotations

import csv
import json
import os
import signal
import subprocess
from dataclasses import asdict
from pathlib import Path
from time import monotonic, sleep

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    capture_file_hash,
    check_capture_path,
    check_weekly_cancel,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyUnit,
    StockWeeklySource,
    WeeklyBudget,
    normalize_weekly_code,
    stable_weekly_hash,
    weekly_column_specs,
    weekly_schema_hash,
)


def prod_weekly_table(source: StockWeeklySource) -> str:
    source = StockWeeklySource(source)
    if source is StockWeeklySource.PRIMARY_UNADJUSTED:
        return "raw_tushare.stk_period_bar"
    if source is StockWeeklySource.PRIMARY_ADJUSTED:
        return "raw_tushare.stk_period_bar_adj"
    raise WeeklyCaptureError("alternate_has_no_prod_bootstrap")


def build_prod_weekly_query(
    unit: ProdWeeklyUnit, budget: WeeklyBudget
) -> tuple[str, dict]:
    table = prod_weekly_table(unit.source)
    if (
        not unit.sorted_codes
        or len(unit.sorted_codes) > budget.prod_code_batch
        or unit.sorted_codes != tuple(sorted(set(unit.sorted_codes)))
        or unit.schema_hash != weekly_schema_hash(unit.source)
        or not 0 < unit.max_rows <= budget.max_source_rows_per_prod_unit
        or unit.source_date_start >= unit.source_date_end
    ):
        raise WeeklyCaptureError("prod_unit_invalid")
    for code in unit.sorted_codes:
        normalize_weekly_code(code)
    columns = []
    for name, kind, _ in weekly_column_specs(unit.source):
        if name in ("trade_date", "end_date"):
            columns.append(f"to_char({name}, 'YYYYMMDD') AS {name}")
        elif kind.startswith("DECIMAL"):
            columns.append(f'"{name}"::text AS "{name}"')
        else:
            columns.append(f'"{name}"')
    where = "ts_code = ANY(%(codes)s) AND freq = 'week' AND trade_date >= %(start)s AND trade_date < %(end)s"
    return (
        f"SELECT {','.join(columns)} FROM {table} WHERE {where} ORDER BY ts_code,trade_date,freq",
        {
            "codes": list(unit.sorted_codes),
            "start": unit.source_date_start,
            "end": unit.source_date_end,
        },
    )


def build_prod_weekly_export_sql(unit, budget, control_path, remaining_rows):
    query, params = build_prod_weekly_query(unit, budget)
    check_capture_path(control_path)
    if any(char in str(control_path) for char in "'\\\r\n`"):
        raise WeeklyCaptureError("prod_control_path_invalid")
    query = query.replace(
        "%(codes)s", "ARRAY[" + ",".join(f"'{code}'" for code in params["codes"]) + "]"
    )
    query = query.replace("%(start)s", f"DATE '{params['start'].isoformat()}'")
    query = query.replace("%(end)s", f"DATE '{params['end'].isoformat()}'")
    if (
        isinstance(remaining_rows, bool)
        or not isinstance(remaining_rows, int)
        or remaining_rows < 0
    ):
        raise WeeklyCaptureError("phase_row_budget_exceeded")
    count = (
        "SELECT count(*) AS source_rows, txid_current_snapshot()::text AS snapshot, transaction_timestamp()::text AS snapshot_at, current_setting('transaction_read_only') AS readonly, current_setting('transaction_isolation') AS isolation"
        + query[query.index(" FROM ") : query.index(" ORDER BY ")]
    )
    return rf"""\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '{budget.prod_statement_timeout_ms}ms';
SET LOCAL work_mem = '{budget.prod_work_mem}';
{count}
\gset weekly_
SELECT json_build_object('source_rows', :weekly_source_rows, 'snapshot', :'weekly_snapshot', 'snapshot_at', :'weekly_snapshot_at', 'readonly', :'weekly_readonly', 'isolation', :'weekly_isolation')
\g '{control_path}'
SELECT 1 / ((:weekly_source_rows <= {unit.max_rows}) AND (:weekly_source_rows <= {remaining_rows}))::integer
\g /dev/null
COPY ({query}) TO STDOUT WITH (FORMAT CSV, HEADER true, NULL '\N', ENCODING 'UTF8');
ROLLBACK;
"""


class PsqlWeeklyExporter:
    """Only the approved wrapper opens the DB; Python supervises bounded files."""

    def __init__(self, *, process_factory=subprocess.Popen):
        self.process_factory = process_factory
        self.repo = Path(__file__).resolve().parents[6]

    @staticmethod
    def _stop(process, seconds):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=seconds)
        else:
            process.wait()

    def export(self, unit, budget, attempt, cancel, progress, remaining_rows):
        check_capture_path(attempt)
        check_weekly_cancel(cancel)
        sql_path = attempt / "transport.sql"
        csv_pending = attempt / "transport.csv.pending"
        control_pending = attempt / "control.json.pending"
        sql = build_prod_weekly_export_sql(
            unit, budget, control_pending, remaining_rows
        )
        with sql_path.open("x") as stream:
            stream.write(sql)
            stream.flush()
            os.fsync(stream.fileno())
        command = [
            "bash",
            str(self.repo / "scripts/psql-remote.sh"),
            "-f",
            str(sql_path),
            "--",
            "-qAt",
            "-w",
        ]
        environment = os.environ.copy()
        environment["ENV_FILE"] = str(self.repo / ".env.web.local")
        started = monotonic()
        with csv_pending.open("xb") as output:
            process = self.process_factory(
                command,
                cwd=self.repo,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                while process.poll() is None:
                    check_weekly_cancel(cancel)
                    if monotonic() - started >= budget.prod_unit_seconds:
                        raise WeeklyCaptureError("prod_unit_timeout")
                    if os.fstat(output.fileno()).st_size > budget.prod_csv_max_bytes:
                        raise WeeklyCaptureError("prod_csv_budget_exceeded")
                    if (
                        control_pending.exists()
                        and control_pending.stat().st_size
                        > budget.prod_control_max_bytes
                    ):
                        raise WeeklyCaptureError("prod_control_budget_exceeded")
                    progress(
                        {
                            "transport_bytes": os.fstat(output.fileno()).st_size,
                            "phase": "prod_export",
                        }
                    )
                    sleep(0.1)
                check_weekly_cancel(cancel)
                if os.fstat(output.fileno()).st_size > budget.prod_csv_max_bytes:
                    raise WeeklyCaptureError("prod_csv_budget_exceeded")
                if not control_pending.exists():
                    raise WeeklyCaptureError("prod_control_invalid")
                if control_pending.stat().st_size > budget.prod_control_max_bytes:
                    raise WeeklyCaptureError("prod_control_budget_exceeded")
                try:
                    evidence = json.loads(control_pending.read_text())
                except (ValueError, UnicodeError):
                    raise WeeklyCaptureError("prod_control_invalid") from None
                rows = (
                    evidence.get("source_rows") if isinstance(evidence, dict) else None
                )
                if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
                    raise WeeklyCaptureError("prod_control_invalid")
                if rows > unit.max_rows:
                    raise WeeklyCaptureError("unit_row_budget_exceeded")
                if rows > remaining_rows:
                    raise WeeklyCaptureError("phase_row_budget_exceeded")
                if process.returncode != 0:
                    raise WeeklyCaptureError("prod_export_failed")
                if (
                    evidence.get("readonly") != "on"
                    or evidence.get("isolation") != "repeatable read"
                    or any(
                        not isinstance(evidence.get(key), str) or not evidence[key]
                        for key in ("snapshot", "snapshot_at")
                    )
                ):
                    raise WeeklyCaptureError("prod_control_invalid")
                output.flush()
                os.fsync(output.fileno())
            finally:
                self._stop(process, budget.prod_process_shutdown_seconds)
        csv_path = attempt / "transport.csv"
        control_path = attempt / "control.json"
        with control_pending.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(csv_pending, csv_path)
        os.replace(control_pending, control_path)
        descriptor = os.open(attempt, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        evidence.update(
            source_table=prod_weekly_table(unit.source),
            unit_hash=stable_weekly_hash(asdict(unit)),
            transport="psql_copy_csv_v1",
            capture_artifacts=[
                {
                    "path": str(path.relative_to(attempt.parent)),
                    "sha256": capture_file_hash(path),
                }
                for path in (sql_path, csv_path, control_path)
            ],
        )
        return csv_path, evidence


def load_prod_weekly_csv(connection, path, unit, evidence):
    check_capture_path(path)
    fields = [name for name, _, _ in weekly_column_specs(unit.source)]
    with path.open(newline="", encoding="utf-8") as stream:
        if next(csv.reader(stream), None) != fields:
            raise WeeklyCaptureError("source_schema_mismatch")
    columns = "{" + ",".join(f"'{name}':'VARCHAR'" for name in fields) + "}"
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE weekly_prod_csv AS SELECT * FROM read_csv(?, columns={columns}, header=true, auto_detect=false, delim=',', quote='\"', escape='\"', nullstr='\\N', allow_quoted_nulls=false, strict_mode=true) LIMIT {unit.max_rows + 1}",
        [str(path)],
    )
    count = connection.execute("SELECT count(*) FROM weekly_prod_csv").fetchone()[0]
    if count > unit.max_rows:
        raise WeeklyCaptureError("unit_row_budget_exceeded")
    if count != evidence["source_rows"]:
        raise WeeklyCaptureError("source_count_changed")
    return count
