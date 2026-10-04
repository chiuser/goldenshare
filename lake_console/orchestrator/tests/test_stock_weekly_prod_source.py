import json
import subprocess
import sys
from dataclasses import replace
from datetime import date
from threading import Event, Timer

import pytest

from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.prod_db.stock_weekly import (
    PsqlWeeklyExporter,
    build_prod_weekly_export_sql,
    build_prod_weekly_query,
)
from orchestrator.defs.run_contracts.stock_weekly import StockWeeklySource, WeeklyBudget

from .stock_weekly_capture_test_support import (
    prod_plan,
)


def test_sql_preserves_business_columns_and_half_open_source_year():
    plan = prod_plan()
    sql, params = build_prod_weekly_query(plan.units[0], plan.budget)
    assert '"open"::text' in sql and "to_char(trade_date, 'YYYYMMDD')" in sql
    assert "freq = 'week'" in sql and "trade_date < %(end)s" in sql
    assert params["start"] == date(2020, 1, 1) and params["end"] == date(2021, 1, 1)
    for forbidden in (
        "SELECT *",
        "api_name",
        "fetched_at",
        "raw_payload",
        "is_listed",
        "IS NOT NULL",
    ):
        assert forbidden not in sql
    with pytest.raises(WeeklyCaptureError):
        build_prod_weekly_query(
            replace(plan.units[0], source=StockWeeklySource.ALTERNATE_WEEKLY),
            plan.budget,
        )
    with pytest.raises(WeeklyCaptureError):
        build_prod_weekly_query(replace(plan.units[0], schema_hash="bad"), plan.budget)


def offline_process_factory(control, *, rows=1, mode="success", observed=None):
    def launch(argv, **kwargs):
        if observed is not None:
            observed.update(argv=argv, kwargs=kwargs)
        data = {
            "source_rows": rows,
            "snapshot": "100:200:",
            "snapshot_at": "2026-10-03",
            "readonly": "on",
            "isolation": "repeatable read",
        }
        if mode == "invalid":
            data["readonly"] = "off"
        script = (
            "import pathlib,time,json,sys; "
            + f"pathlib.Path({str(control)!r}).write_text({json.dumps(data)!r}); "
        )
        if mode == "blocked":
            script += "time.sleep(30)"
        elif mode == "oversized":
            script += "sys.stdout.write('x'*10000)"
        elif mode == "failed":
            script += "sys.exit(3)"
        else:
            script += "sys.stdout.write('header\\n')"
        return subprocess.Popen([sys.executable, "-c", script], **kwargs)

    return launch


def test_snapshot_sql_and_sole_script_entry(tmp_path):
    plan = prod_plan()
    unit = plan.units[0]
    sql = build_prod_weekly_export_sql(
        unit, plan.budget, tmp_path / "control.json.pending", 30_000
    )
    assert (
        sql.index("REPEATABLE READ READ ONLY")
        < sql.index("SELECT count")
        < sql.index("COPY (")
        < sql.index("ROLLBACK")
    )
    assert "\\gset weekly_" in sql and "NULL '\\N'" in sql
    assert "ARRAY['000005.SZ']" in sql
    assert "DATE '2021-01-01'" in sql
    observed = {}
    exporter = PsqlWeeklyExporter(
        process_factory=offline_process_factory(
            tmp_path / "control.json.pending", observed=observed
        )
    )
    path, evidence = exporter.export(
        unit, plan.budget, tmp_path, lambda: False, lambda _: None, 30_000
    )
    assert path.exists() and evidence["source_rows"] == 1
    argv = observed["argv"]
    assert argv[0] == "bash" and argv[1].endswith("/scripts/psql-remote.sh")
    assert argv[-3:] == ["--", "-qAt", "-w"]
    assert observed["kwargs"]["env"]["ENV_FILE"].endswith("/goldenshare/.env.web.local")
    assert len(evidence["capture_artifacts"]) == 3


@pytest.mark.parametrize(
    "mode,rows,remaining,reason",
    [
        ("success", 30001, 30000, "unit_row_budget"),
        ("success", 2, 1, "phase_row_budget"),
        ("invalid", 1, 30000, "prod_control_invalid"),
        ("failed", 1, 30000, "prod_export_failed"),
        ("oversized", 1, 30000, "prod_csv_budget"),
    ],
)
def test_export_rejects_budget_failure_and_bad_control(
    tmp_path, mode, rows, remaining, reason
):
    plan = prod_plan(budget=WeeklyBudget(prod_csv_max_bytes=1000))
    exporter = PsqlWeeklyExporter(
        process_factory=offline_process_factory(
            tmp_path / "control.json.pending", rows=rows, mode=mode
        )
    )
    with pytest.raises(WeeklyCaptureError, match=reason):
        exporter.export(
            plan.units[0],
            plan.budget,
            tmp_path,
            lambda: False,
            lambda _: None,
            remaining,
        )
    assert not (tmp_path / "transport.csv").exists()
    assert (tmp_path / "transport.csv.pending").exists()


def test_actual_blocked_process_cancel_and_timeout(tmp_path):
    from time import monotonic

    plan = prod_plan(
        budget=WeeklyBudget(prod_unit_seconds=1, prod_statement_timeout_ms=500)
    )
    for mode in ("cancel", "timeout"):
        attempt = tmp_path / mode
        attempt.mkdir()
        exporter = PsqlWeeklyExporter(
            process_factory=offline_process_factory(
                attempt / "control.json.pending", mode="blocked"
            )
        )
        canceled = Event()
        timer = Timer(0.2, canceled.set)
        if mode == "cancel":
            timer.start()
        started = monotonic()
        try:
            with pytest.raises(
                WeeklyCaptureError,
                match="canceled" if mode == "cancel" else "prod_unit_timeout",
            ):
                exporter.export(
                    plan.units[0],
                    plan.budget,
                    attempt,
                    canceled.is_set,
                    lambda _: None,
                    30000,
                )
        finally:
            if mode == "cancel":
                timer.join()
        assert monotonic() - started < 3
        assert not (attempt / "transport.csv").exists()


def test_control_file_budget_is_consistent_after_fast_process_exit(tmp_path):
    plan = prod_plan(budget=WeeklyBudget(prod_control_max_bytes=10))
    exporter = PsqlWeeklyExporter(
        process_factory=offline_process_factory(tmp_path / "control.json.pending")
    )
    with pytest.raises(WeeklyCaptureError, match="prod_control_budget_exceeded"):
        exporter.export(
            plan.units[0], plan.budget, tmp_path, lambda: False, lambda _: None, 30000
        )
    assert not (tmp_path / "control.json").exists()


@pytest.mark.parametrize(
    "name",
    ["prod_csv_max_bytes", "prod_control_max_bytes", "prod_process_shutdown_seconds"],
)
def test_new_transport_budgets_reject_zero(name):
    with pytest.raises(ValueError, match="invalid_integer_budget"):
        WeeklyBudget(**{name: 0})


def test_precanceled_export_never_starts_process(tmp_path):
    plan = prod_plan()
    exporter = PsqlWeeklyExporter(
        process_factory=lambda *args, **kwargs: pytest.fail("must not spawn")
    )
    with pytest.raises(WeeklyCaptureError, match="canceled"):
        exporter.export(
            plan.units[0], plan.budget, tmp_path, lambda: True, lambda _: None, 30000
        )
    assert not list(tmp_path.iterdir())
