
import duckdb

from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    build_weekly_partition_candidates,
    partition_path,
)
from orchestrator.defs.bootstrap.stock_weekly_promote import promote_weekly_candidates
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_column_specs,
)

from .stock_weekly_capture_test_support import (
    prod_frame,
)


def captured(tmp_path, frames=None, source=StockWeeklySource.PRIMARY_ADJUSTED):
    from .stock_weekly_capture_test_support import adjusted_captured
    return adjusted_captured(tmp_path, frames if frames is not None else [prod_frame()])


def test_adjusted_values(tmp_path):
    frame = prod_frame()
    source = StockWeeklySource.PRIMARY_ADJUSTED
    for name, _, _ in weekly_column_specs(source):
        if name.endswith(("_qfq", "_hfq")):
            frame[name] = "123.0001"
    frame = frame[[n for n, _, _ in weekly_column_specs(source)]]
    plan, root = captured(tmp_path, [frame], source)
    audit = build_weekly_partition_candidates(
        plan,
        capture_root=root,
        target_root=tmp_path / "formal",
        year=2020,
        partial_scope=True,
    )
    promote_weekly_candidates(audit, apply=True)
    with duckdb.connect() as con:
        path = partition_path(tmp_path / "formal", source, "2020-02-28")
        assert (
            str(
                con.execute(
                    "SELECT close_qfq FROM read_parquet(?,hive_partitioning=false)",
                    [str(path)],
                ).fetchone()[0]
            )
            == "123.0001"
        )
