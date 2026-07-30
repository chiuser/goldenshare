from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.asset_guards.index_mins_lake_readiness import (
    batch_silver_index_mins_fallback_lake_readiness,
)
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
CODE = "000001.SH"


def _write_5min_source(root: Path) -> None:
    path = raw_index_mins_path(root, "5min", TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            CREATE TABLE source_rows AS
            SELECT
              '000001.SH'::VARCHAR AS ts_code,
              '5min'::VARCHAR AS freq,
              CAST(? || ' ' || trade_time AS TIMESTAMP) AS trade_time,
              (row_number() OVER () + 1)::DOUBLE AS open,
              (row_number() OVER () + 1.5)::DOUBLE AS close,
              (row_number() OVER () + 2)::DOUBLE AS high,
              (row_number() OVER () + 0.5)::DOUBLE AS low,
              10.0::DOUBLE AS vol,
              100.0::DOUBLE AS amount,
              'XSHG'::VARCHAR AS exchange,
              1.25::DOUBLE AS vwap
            FROM unnest(?) AS values_table(trade_time)
            """,
            [TRADE_DATE, list(fallback_source_times_for_index_mins())],
        )
        connection.execute(copy_query_to_parquet("SELECT * FROM source_rows", path))


def _request(
    root: Path, frequencies: tuple[int, ...]
) -> IndexMinsSilverFallbackRequest:
    with DuckDBResource().connect() as connection:
        revision = compute_index_mins_fallback_source_revision(
            connection=connection,
            lake_root=root,
            partition_key=TRADE_DATE,
        )
    return IndexMinsSilverFallbackRequest(
        partition_key=TRADE_DATE,
        target_frequencies=frequencies,
        source_empty_frequencies=(15, 30, 60),
        effective_codes=(CODE,),
        source_revision=revision,
        source_empty_reason="source_probe_target_frequencies_empty",
    )


def test_fallback_readiness_distinguishes_missing_partial_and_ready() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_5min_source(root)
        request = _request(root, (15, 30, 60))

        with DuckDBResource().connect() as connection:
            missing = batch_silver_index_mins_fallback_lake_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(TRADE_DATE,),
                fallback_requests_by_trade_date={TRADE_DATE: request},
            )
        missing_status = missing.status_for_trade_date(TRADE_DATE)
        assert missing_status.materialized is False
        assert missing_status.checks_passed is False
        assert missing_status.summary["reason_code"] == "file_missing"
        assert missing_status.summary["source_mode"] == "derived_fallback"

        repair_silver_index_mins_source_empty(
            lake_root=root,
            duckdb=DuckDBResource(),
            request=_request(root, (15,)),
        )
        with DuckDBResource().connect() as connection:
            partial = batch_silver_index_mins_fallback_lake_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(TRADE_DATE,),
                fallback_requests_by_trade_date={TRADE_DATE: request},
            )
        partial_status = partial.status_for_trade_date(TRADE_DATE)
        assert partial_status.materialized is True
        assert partial_status.checks_passed is False
        assert partial_status.summary["reason_code"] == "fallback_target_partial"

        repair_silver_index_mins_source_empty(
            lake_root=root,
            duckdb=DuckDBResource(),
            request=request,
        )
        with DuckDBResource().connect() as connection:
            ready = batch_silver_index_mins_fallback_lake_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(TRADE_DATE,),
                fallback_requests_by_trade_date={TRADE_DATE: request},
            )
        ready_status = ready.status_for_trade_date(TRADE_DATE)
        assert ready_status.ready is True
        assert (
            ready_status.summary["reason_code"] == "ready_after_source_empty_fallback"
        )
        assert ready.scanned_file_count == 4


def test_fallback_readiness_fails_closed_for_unregistered_or_missing_request() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with DuckDBResource().connect() as connection:
            unregistered = batch_silver_index_mins_fallback_lake_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(),
                fallback_requests_by_trade_date={},
            )
        assert unregistered.status_for_trade_date(TRADE_DATE).summary[
            "reason_code"
        ] == ("registered_partition_missing")

        with DuckDBResource().connect() as connection:
            missing_request = batch_silver_index_mins_fallback_lake_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(TRADE_DATE,),
                fallback_requests_by_trade_date={},
            )
        assert missing_request.status_for_trade_date(TRADE_DATE).summary[
            "reason_code"
        ] == ("fallback_request_missing")
