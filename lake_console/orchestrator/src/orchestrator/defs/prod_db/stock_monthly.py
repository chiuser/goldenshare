"""Monthly Prod business fields through the sole approved rollback-only psql wrapper."""

from __future__ import annotations

import os
import re
import signal
import subprocess
from datetime import date
from pathlib import Path
from time import monotonic, sleep

from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_cancel,
    check_monthly_path,
    read_monthly_json,
    sync_monthly_directory,
)
from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_column_specs,
)


def prod_monthly_table(source) -> str:
    return "raw_tushare.stk_period_bar" + (
        "_adj"
        if StockMonthlySource(source) is StockMonthlySource.PRIMARY_ADJUSTED
        else ""
    )


def validate_prod_monthly_unit(unit, policy) -> None:
    StockMonthlySource(unit.source)
    if not isinstance(unit.unit_id, str) or not re.fullmatch(
        "[0-9a-f]{64}", unit.unit_id
    ):
        raise ValueError("monthly_unit_identity_invalid")
    if (
        not unit.sorted_codes
        or len(unit.sorted_codes) > policy.prod_code_batch
        or unit.sorted_codes != tuple(sorted(set(unit.sorted_codes)))
        or any(
            not isinstance(c, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", c)
            for c in unit.sorted_codes
        )
    ):
        raise ValueError("monthly_unit_codes_invalid")
    start, end = (
        date.fromisoformat(unit.source_date_start),
        date.fromisoformat(unit.source_date_end),
    )
    if (
        start.isoformat() != unit.source_date_start
        or end.isoformat() != unit.source_date_end
        or start.day != 1
        or end.day != 1
        or not start < end <= date(start.year + 1, 1, 1)
        or type(unit.max_rows) is not int
        or not 0 < unit.max_rows <= policy.max_prod_unit_rows
    ):
        raise ValueError("monthly_unit_scope_invalid")


def build_prod_monthly_query(unit, policy) -> str:
    validate_prod_monthly_unit(unit, policy)
    fields = []
    for name, kind in monthly_column_specs(unit.source):
        fields.append(
            f"to_char({name}, 'YYYYMMDD') AS {name}"
            if name in ("trade_date", "end_date")
            else f'"{name}"::text AS "{name}"'
            if kind.startswith("DECIMAL")
            else f'"{name}"'
        )
    codes = ",".join(f"'{code}'" for code in unit.sorted_codes)
    return f"SELECT {','.join(fields)} FROM {prod_monthly_table(unit.source)} WHERE ts_code = ANY(ARRAY[{codes}]) AND freq = 'month' AND trade_date >= DATE '{unit.source_date_start}' AND trade_date < DATE '{unit.source_date_end}' ORDER BY ts_code,trade_date,freq"


def build_prod_monthly_export_sql(
    unit, policy, io_policy, control_path, remaining_rows
) -> str:
    query = build_prod_monthly_query(unit, policy)
    check_monthly_path(control_path)
    if any(c in str(control_path) for c in "'\\\r\n`"):
        raise ValueError("monthly_control_path_invalid")
    if type(remaining_rows) is not int or remaining_rows < 0:
        raise ValueError("monthly_remaining_rows_invalid")
    count = (
        "SELECT count(*) AS source_rows, txid_current_snapshot()::text AS snapshot, transaction_timestamp()::text AS snapshot_at, current_setting('transaction_read_only') AS readonly, current_setting('transaction_isolation') AS isolation"
        + query[query.index(" FROM ") : query.index(" ORDER BY ")]
    )
    return rf"""\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '{io_policy.prod_statement_timeout_ms}ms';
SET LOCAL work_mem = '{io_policy.prod_work_mem_mb}MB';
{count}
\gset monthly_
SELECT json_build_object('source_rows', :monthly_source_rows, 'snapshot', :'monthly_snapshot', 'snapshot_at', :'monthly_snapshot_at', 'readonly', :'monthly_readonly', 'isolation', :'monthly_isolation')
\g '{control_path}'
SELECT 1 / ((:monthly_source_rows <= {unit.max_rows}) AND (:monthly_source_rows <= {remaining_rows}))::integer
\g /dev/null
COPY ({query}) TO STDOUT WITH (FORMAT CSV, HEADER true, NULL '\N', ENCODING 'UTF8');
ROLLBACK;
"""


def validate_monthly_export_evidence(evidence, unit, remaining_rows):
    rows = evidence.get("source_rows")
    if type(rows) is not int or rows < 0:
        raise ValueError("monthly_prod_control_invalid")
    if rows > min(unit.max_rows, remaining_rows):
        raise ValueError("monthly_prod_row_budget_exceeded")
    if (
        evidence.get("readonly") != "on"
        or evidence.get("isolation") != "repeatable read"
        or any(
            not isinstance(evidence.get(k), str) or not evidence[k]
            for k in ("snapshot", "snapshot_at")
        )
    ):
        raise ValueError("monthly_prod_control_invalid")


class PsqlMonthlyExporter:
    def __init__(self, *, process_factory=subprocess.Popen):
        self.process_factory = process_factory
        self.repo = Path(__file__).resolve().parents[6]

    @staticmethod
    def _stop(process, timeout):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=timeout)
        else:
            process.wait()

    def export(
        self, unit, policy, io_policy, attempt, cancel, progress, remaining_rows
    ):
        check_monthly_path(attempt)
        check_monthly_cancel(cancel)
        sql_path = attempt / "transport.sql"
        csv_pending, control_pending = (
            attempt / "transport.csv.pending",
            attempt / "control.json.pending",
        )
        sql = build_prod_monthly_export_sql(
            unit, policy, io_policy, control_pending, remaining_rows
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
                while True:
                    check_monthly_cancel(cancel)
                    if os.fstat(output.fileno()).st_size > io_policy.prod_csv_max_bytes:
                        raise ValueError("monthly_prod_csv_budget_exceeded")
                    if (
                        control_pending.exists()
                        and control_pending.stat().st_size > io_policy.control_max_bytes
                    ):
                        raise ValueError("monthly_control_budget_exceeded")
                    if process.poll() is not None:
                        break
                    if monotonic() - started >= io_policy.prod_unit_seconds:
                        raise ValueError("monthly_prod_unit_timeout")
                    progress(
                        {
                            "phase": "prod_export",
                            "unit": unit.unit_id,
                            "transport_bytes": os.fstat(output.fileno()).st_size,
                        }
                    )
                    sleep(0.1)
                if process.returncode != 0:
                    raise ValueError("monthly_prod_export_failed")
                evidence = read_monthly_json(
                    control_pending, io_policy.control_max_bytes
                )
                validate_monthly_export_evidence(evidence, unit, remaining_rows)
                output.flush()
                os.fsync(output.fileno())
            finally:
                self._stop(process, io_policy.process_shutdown_seconds)
        csv_path, control_path = attempt / "transport.csv", attempt / "control.json"
        with control_pending.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(csv_pending, csv_path)
        os.replace(control_pending, control_path)
        sync_monthly_directory(attempt)
        return csv_path, evidence
