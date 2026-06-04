"""Major indices input readiness checks for daily gold sensor gates."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import silver_index_basic_path, silver_index_daily_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.seeds.market.major_indices import (
    MajorIndexSeedRow,
    active_major_indices_seed_rows,
    load_major_indices_seed,
)


@dataclass(frozen=True)
class MarketMajorIndicesInputReadiness:
    trade_date: str
    seed_row_count: int
    active_seed_code_count: int
    registered_code_count: int
    missing_registered_seed_codes: tuple[str, ...]
    missing_index_basic_file: bool
    missing_index_basic_seed_codes: tuple[str, ...]
    missing_silver_daily_file: bool
    missing_silver_daily_seed_codes: tuple[str, ...]
    scan_error_code: str | None = None
    scan_error: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.scan_error is None
            and self.seed_row_count > 0
            and self.active_seed_code_count > 0
            and not self.missing_registered_seed_codes
            and not self.missing_index_basic_file
            and not self.missing_index_basic_seed_codes
            and not self.missing_silver_daily_file
            and not self.missing_silver_daily_seed_codes
        )

    @property
    def blocked_count(self) -> int:
        if self.scan_error:
            return max(1, self.registered_code_count)
        blocked = (
            len(self.missing_registered_seed_codes)
            + len(self.missing_index_basic_seed_codes)
            + len(self.missing_silver_daily_seed_codes)
        )
        if self.missing_index_basic_file:
            blocked += 1
        if self.missing_silver_daily_file:
            blocked += 1
        if self.active_seed_code_count == 0:
            blocked += 1
        return blocked


def _seed_values_sql(seed_rows: Sequence[MajorIndexSeedRow]) -> str:
    values_sql = ", ".join(
        f"({row.rank}, {duckdb_string(row.ts_code)})" for row in seed_rows
    )
    return f"(VALUES {values_sql}) AS seed(rank, ts_code)"


def _missing_seed_codes_in_index_basic(
    connection,
    *,
    index_basic_path: Path,
    seed_rows: Sequence[MajorIndexSeedRow],
) -> tuple[str, ...]:
    rows = connection.execute(
        f"""
        SELECT seed.ts_code
        FROM {_seed_values_sql(seed_rows)}
        LEFT JOIN {read_parquet(index_basic_path, hive_partitioning=False)} index_basic
          ON seed.ts_code = index_basic.ts_code
        WHERE index_basic.ts_code IS NULL
        ORDER BY seed.rank
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _missing_active_seed_codes_in_silver_daily(
    connection,
    *,
    silver_daily_path: Path,
    active_seed_rows: Sequence[MajorIndexSeedRow],
    trade_date: str,
) -> tuple[str, ...]:
    if not active_seed_rows:
        return ()
    rows = connection.execute(
        f"""
        SELECT seed.ts_code
        FROM {_seed_values_sql(active_seed_rows)}
        LEFT JOIN {read_parquet(silver_daily_path, hive_partitioning=False)} silver_daily
          ON seed.ts_code = silver_daily.ts_code
         AND CAST(silver_daily.trade_date AS DATE) = DATE {duckdb_string(trade_date)}
        WHERE silver_daily.ts_code IS NULL
        ORDER BY seed.rank
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def check_market_major_indices_inputs_for_trade_date(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    registered_index_codes: tuple[str, ...],
    trade_date: str,
) -> MarketMajorIndicesInputReadiness:
    """Check only the small seed-driven prerequisites for daily major indices."""

    seed_rows: tuple[MajorIndexSeedRow, ...] = ()
    active_seed_rows: tuple[MajorIndexSeedRow, ...] = ()
    missing_registered_seed_codes: tuple[str, ...] = ()
    missing_index_basic_file = False
    missing_index_basic_seed_codes: tuple[str, ...] = ()
    missing_silver_daily_file = False
    missing_silver_daily_seed_codes: tuple[str, ...] = ()

    try:
        seed_rows = load_major_indices_seed()
        active_seed_rows = active_major_indices_seed_rows(trade_date)
        registered_code_set = set(registered_index_codes)
        missing_registered_seed_codes = tuple(
            row.ts_code for row in seed_rows if row.ts_code not in registered_code_set
        )

        index_basic_path = silver_index_basic_path(lake_root_path)
        missing_index_basic_file = not index_basic_path.exists()
        silver_daily_path = silver_index_daily_path(lake_root_path, trade_date)
        missing_silver_daily_file = not silver_daily_path.exists()

        with connect_configured_duckdb() as connection:
            if not missing_index_basic_file:
                missing_index_basic_seed_codes = _missing_seed_codes_in_index_basic(
                    connection,
                    index_basic_path=index_basic_path,
                    seed_rows=seed_rows,
                )
            if not missing_silver_daily_file:
                missing_silver_daily_seed_codes = (
                    _missing_active_seed_codes_in_silver_daily(
                        connection,
                        silver_daily_path=silver_daily_path,
                        active_seed_rows=active_seed_rows,
                        trade_date=trade_date,
                    )
                )
    except Exception as exc:
        return MarketMajorIndicesInputReadiness(
            trade_date=trade_date,
            seed_row_count=len(seed_rows),
            active_seed_code_count=len(active_seed_rows),
            registered_code_count=len(registered_index_codes),
            missing_registered_seed_codes=missing_registered_seed_codes,
            missing_index_basic_file=missing_index_basic_file,
            missing_index_basic_seed_codes=missing_index_basic_seed_codes,
            missing_silver_daily_file=missing_silver_daily_file,
            missing_silver_daily_seed_codes=missing_silver_daily_seed_codes,
            scan_error_code=type(exc).__name__,
            scan_error=str(exc),
        )

    return MarketMajorIndicesInputReadiness(
        trade_date=trade_date,
        seed_row_count=len(seed_rows),
        active_seed_code_count=len(active_seed_rows),
        registered_code_count=len(registered_index_codes),
        missing_registered_seed_codes=missing_registered_seed_codes,
        missing_index_basic_file=missing_index_basic_file,
        missing_index_basic_seed_codes=missing_index_basic_seed_codes,
        missing_silver_daily_file=missing_silver_daily_file,
        missing_silver_daily_seed_codes=missing_silver_daily_seed_codes,
    )
