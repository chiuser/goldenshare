"""Read-only single-file semantics shared by nodes and historical run events."""

from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_candidates import partition_path
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_weekly_raw import (
    WEEK_SQL,
    load_relation,
    validate_relation,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    WeeklyBudget,
    normalize_week_key,
)


def audit_weekly_file(source, week, root, *, kind="key_partition"):
    normalize_week_key(week)
    path = partition_path(root, source, week)
    budget = WeeklyBudget()
    # Checks are read-only, including spill: use existing temporary storage and no spill.
    import tempfile

    settings = DuckDBConnectionSettings(
        temp_directory=Path(tempfile.gettempdir()).resolve(),
        memory_limit=budget.duckdb_memory_limit,
        threads=budget.duckdb_threads,
        max_temp_directory_size=budget.duckdb_max_temp,
    )
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as con:
        load_relation(con, "weekly_checked", [path], source)
        if kind == "file_contract":
            return con.execute("SELECT count(*) FROM weekly_checked").fetchone()[0]
        count = validate_relation(con, "weekly_checked", source, budget, unique=True)
        if con.execute(
            f"SELECT count(*) FROM weekly_checked WHERE {WEEK_SQL}<>?", [week]
        ).fetchone()[0]:
            raise WeeklyCaptureError("formal_week_mismatch")
    return count
