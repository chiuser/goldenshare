"""Raw index daily file readiness checks for silver sensor gates."""

from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import raw_index_daily_by_code_path
from orchestrator.defs.resources import DuckDBResource


@dataclass(frozen=True)
class IndexDailyRawFileReadiness:
    trade_date: str
    registered_code_count: int
    ready_code_count: int
    missing_file_codes: tuple[str, ...]
    missing_trade_date_codes: tuple[str, ...]
    scan_error_code: str | None = None
    scan_error: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.scan_error is None
            and self.registered_code_count > 0
            and self.ready_code_count == self.registered_code_count
        )

    @property
    def missing_file_count(self) -> int:
        return len(self.missing_file_codes)

    @property
    def missing_trade_date_count(self) -> int:
        return len(self.missing_trade_date_codes)


def _raw_file_has_trade_date(connection, raw_path: Path, compact_trade_date: str) -> bool:
    query = read_parquet(raw_path, hive_partitioning=False)
    row = connection.execute(
        f"""
        SELECT count(*) > 0 AS has_trade_date
        FROM {query}
        WHERE CAST(trade_date AS VARCHAR) = ?
        """,
        [compact_trade_date],
    ).fetchone()
    return bool(row and row[0])


def check_index_daily_raw_files_for_trade_date(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    registered_index_codes: tuple[str, ...],
    trade_date: str,
) -> IndexDailyRawFileReadiness:
    """Check raw by-code files directly instead of inferring readiness from run tags."""

    compact_trade_date = trade_date.replace("-", "")
    missing_file_codes = []
    missing_trade_date_codes = []
    ready_code_count = 0

    try:
        with duckdb.connect() as connection:
            for index_code in registered_index_codes:
                raw_path = raw_index_daily_by_code_path(lake_root_path, index_code)
                if not raw_path.exists():
                    missing_file_codes.append(index_code)
                    continue
                if _raw_file_has_trade_date(connection, raw_path, compact_trade_date):
                    ready_code_count += 1
                else:
                    missing_trade_date_codes.append(index_code)
    except Exception as exc:
        return IndexDailyRawFileReadiness(
            trade_date=trade_date,
            registered_code_count=len(registered_index_codes),
            ready_code_count=ready_code_count,
            missing_file_codes=tuple(missing_file_codes),
            missing_trade_date_codes=tuple(missing_trade_date_codes),
            scan_error_code=type(exc).__name__,
            scan_error=str(exc),
        )

    return IndexDailyRawFileReadiness(
        trade_date=trade_date,
        registered_code_count=len(registered_index_codes),
        ready_code_count=ready_code_count,
        missing_file_codes=tuple(missing_file_codes),
        missing_trade_date_codes=tuple(missing_trade_date_codes),
    )
