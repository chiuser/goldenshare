from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.assets.index_mins_silver_repair import (
    IndexMinsSilverFallbackRequest,
    compute_index_mins_fallback_source_revision,
    repair_silver_index_mins_source_empty,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import raw_index_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.index_mins import (
    fallback_source_times_for_index_mins,
)


TRADE_DATE = "2026-07-27"


def test_fallback_530_code_set_stays_within_bounded_repair_budget() -> None:
    codes = [f"{100000 + index:06d}.SH" for index in range(530)]
    times = list(fallback_source_times_for_index_mins())
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source_path = raw_index_mins_path(root, "5min", TRADE_DATE)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with DuckDBResource().connect() as connection:
            connection.execute(
                """
                CREATE TABLE source_rows AS
                SELECT
                  codes.ts_code::VARCHAR AS ts_code,
                  '5min'::VARCHAR AS freq,
                  CAST(? || ' ' || times.trade_time AS TIMESTAMP) AS trade_time,
                  10.0::DOUBLE AS open,
                  10.5::DOUBLE AS close,
                  11.0::DOUBLE AS high,
                  9.5::DOUBLE AS low,
                  100.0::DOUBLE AS vol,
                  1000.0::DOUBLE AS amount,
                  'XSHG'::VARCHAR AS exchange,
                  10.25::DOUBLE AS vwap
                FROM unnest(?) AS codes(ts_code)
                CROSS JOIN unnest(?) AS times(trade_time)
                """,
                [TRADE_DATE, codes, times],
            )
            connection.execute(
                copy_query_to_parquet("SELECT * FROM source_rows", source_path)
            )
            source_revision = compute_index_mins_fallback_source_revision(
                connection=connection,
                lake_root=root,
                partition_key=TRADE_DATE,
            )

        result = repair_silver_index_mins_source_empty(
            lake_root=root,
            duckdb=DuckDBResource(),
            request=IndexMinsSilverFallbackRequest(
                partition_key=TRADE_DATE,
                target_frequencies=(15, 30, 60),
                source_empty_frequencies=(15, 30, 60),
                effective_codes=tuple(codes),
                source_revision=source_revision,
                source_empty_reason="source_probe_target_frequencies_empty",
            ),
        )

        assert [item.written_row_count for item in result] == [
            530 * 17,
            530 * 9,
            530 * 5,
        ]
        assert max(item.elapsed_ms for item in result) < 60_000
