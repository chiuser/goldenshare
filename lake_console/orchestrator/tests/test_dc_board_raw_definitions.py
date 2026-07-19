from pathlib import Path

from orchestrator.defs.assets.dc_board_raw import (
    plan_dc_member_candidate_codes,
    raw_tushare_dc_daily,
    raw_tushare_dc_index,
    raw_tushare_dc_member,
)
from orchestrator.defs.checks.dc_board_checks import (
    raw_tushare_dc_daily_core_check,
    raw_tushare_dc_index_core_check,
    raw_tushare_dc_member_core_check,
)
from orchestrator.defs.jobs.dc_board import (
    raw_tushare_dc_daily_update_job,
    raw_tushare_dc_index_update_job,
    raw_tushare_dc_member_update_job,
)
from orchestrator.defs.partitions import (
    cn_a_dc_daily_trade_days,
    cn_a_dc_index_trade_days,
    cn_a_dc_member_trade_days,
)
from orchestrator.defs.sensors.dc_board_sensor import (
    raw_tushare_dc_daily_update_job_sensor,
    raw_tushare_dc_index_update_job_sensor,
    raw_tushare_dc_member_update_job_sensor,
)


def test_m4_definitions_are_partitioned_and_stopped() -> None:
    assert raw_tushare_dc_index.partitions_def is cn_a_dc_index_trade_days
    assert raw_tushare_dc_member.partitions_def is cn_a_dc_member_trade_days
    assert raw_tushare_dc_daily.partitions_def is cn_a_dc_daily_trade_days
    assert {check.name for check in raw_tushare_dc_index_core_check.check_specs} == {
        "raw_tushare_dc_index_core_check"
    }
    assert {check.name for check in raw_tushare_dc_member_core_check.check_specs} == {
        "raw_tushare_dc_member_core_check"
    }
    assert {check.name for check in raw_tushare_dc_daily_core_check.check_specs} == {
        "raw_tushare_dc_daily_core_check"
    }
    assert raw_tushare_dc_index_update_job.name == "raw_tushare_dc_index_update_job"
    assert raw_tushare_dc_member_update_job.name == "raw_tushare_dc_member_update_job"
    assert raw_tushare_dc_daily_update_job.name == "raw_tushare_dc_daily_update_job"
    for sensor in (
        raw_tushare_dc_index_update_job_sensor,
        raw_tushare_dc_member_update_job_sensor,
        raw_tushare_dc_daily_update_job_sensor,
    ):
        assert sensor.default_status.value == "STOPPED"


def test_m4_jobs_select_only_their_raw_asset_and_check() -> None:
    source_by_job = {
        "raw_tushare_dc_index_update_job": Path(
            "src/orchestrator/defs/jobs/dc_board.py"
        ).read_text(),
        "raw_tushare_dc_member_update_job": Path(
            "src/orchestrator/defs/jobs/dc_board.py"
        ).read_text(),
        "raw_tushare_dc_daily_update_job": Path(
            "src/orchestrator/defs/jobs/dc_board.py"
        ).read_text(),
    }
    for source in source_by_job.values():
        assert "AssetSelection.assets" in source
        assert "AssetSelection.checks_for_assets" in source
        assert "AssetSelection.assets(silver_" not in source


def test_member_candidate_planner_uses_index_and_nearest_member_baseline(tmp_path) -> None:
    import duckdb

    root = Path(tmp_path)
    calendar = root / "silver/calendar/trade_calendar/full/part-000.parquet"
    calendar.parent.mkdir(parents=True)
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('SSE', DATE '2024-12-20', true),
                ('SSE', DATE '2024-12-23', true)
            ) AS t(exchange, trade_date, is_open)
        ) TO '{calendar}' (FORMAT PARQUET)
        """,
    )
    index_path = root / "raw/board/dc_index/trade_date=2024-12-23/part-000.parquet"
    index_path.parent.mkdir(parents=True)
    connection.execute(
        f"COPY (SELECT * FROM (VALUES ('BK0002.DC')) AS t(ts_code)) TO '{index_path}' (FORMAT PARQUET)",
    )
    member_path = root / "raw/board/dc_member/trade_date=2024-12-20/part-000.parquet"
    member_path.parent.mkdir(parents=True)
    connection.execute(
        f"COPY (SELECT * FROM (VALUES ('BK0001.DC')) AS t(ts_code)) TO '{member_path}' (FORMAT PARQUET)",
    )
    connection.close()

    class _MemoryDuckDB:
        def connect(self):
            outer = self
            class _Context:
                def __enter__(self):
                    self.connection = duckdb.connect()
                    return self.connection
                def __exit__(self, exc_type, exc, tb):
                    self.connection.close()
                    return False
            return _Context()

    candidates = plan_dc_member_candidate_codes(
        lake_root_path=root,
        duckdb_resource=_MemoryDuckDB(),
        partition_key="2024-12-23",
    )
    assert candidates == ("BK0001.DC", "BK0002.DC")


def test_member_candidate_planner_fails_without_non_first_baseline(tmp_path) -> None:
    import duckdb
    import pytest

    from orchestrator.defs.assets.dc_board import DcBoardRawValidationError

    root = Path(tmp_path)
    calendar = root / "silver/calendar/trade_calendar/full/part-000.parquet"
    calendar.parent.mkdir(parents=True)
    connection = duckdb.connect()
    connection.execute(
        f"COPY (SELECT * FROM (VALUES ('SSE', DATE '2024-12-20', true), ('SSE', DATE '2024-12-23', true)) AS t(exchange, trade_date, is_open)) TO '{calendar}' (FORMAT PARQUET)",
    )
    index_path = root / "raw/board/dc_index/trade_date=2024-12-23/part-000.parquet"
    index_path.parent.mkdir(parents=True)
    connection.execute(
        f"COPY (SELECT * FROM (VALUES ('BK0002.DC')) AS t(ts_code)) TO '{index_path}' (FORMAT PARQUET)",
    )
    connection.close()

    class _MemoryDuckDB:
        def connect(self):
            class _Context:
                def __enter__(self):
                    self.connection = duckdb.connect()
                    return self.connection
                def __exit__(self, exc_type, exc, tb):
                    self.connection.close()
                    return False
            return _Context()

    with pytest.raises(DcBoardRawValidationError, match="historical member baseline"):
        plan_dc_member_candidate_codes(
            lake_root_path=root,
            duckdb_resource=_MemoryDuckDB(),
            partition_key="2024-12-23",
        )
