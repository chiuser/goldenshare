import math
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import dagster as dg

from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_stk_mins_path,
    silver_stock_basic_path,
)
from orchestrator.defs.prod_db.stk_mins import (
    assert_prod_stk_mins_source_columns,
    fetch_prod_stk_mins_rows,
    validate_prod_stk_mins_select_contract,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_STK_MINS_SCHEMA
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.configs import (
    STOCK_MINS_RAW_CONFIG_SCHEMA,
    StockMinsMergeRepairConfig,
    parse_stock_mins_raw_config,
)
from orchestrator.defs.run_contracts.stk_mins import (
    derive_stk_mins_exchange_from_ts_code,
    normalize_stk_mins_freq,
)


STK_MINS_RAW_COLUMNS = tuple(column.name for column in RAW_STK_MINS_SCHEMA)
STK_MINS_RAW_COLUMN_TYPES = {column.name: column.type for column in RAW_STK_MINS_SCHEMA}
STK_MINS_TUSHARE_PAGE_LIMIT = 8000
STK_MINS_REQUESTS_PER_MINUTE = 450
STK_MINS_REQUEST_INTERVAL_SECONDS = 60 / STK_MINS_REQUESTS_PER_MINUTE

_STK_MINS_FREQ_LABELS = {
    1: "1min",
    5: "5min",
    15: "15min",
    30: "30min",
    60: "60min",
}


@dataclass(frozen=True)
class StkMinsRawWriteResult:
    raw_file_path: Path
    row_count: int
    observed_columns: tuple[str, ...]
    stock_code_count: int
    returned_stock_code_count: int
    empty_stock_code_count: int
    page_count: int
    source_method: str
    query_count: int = 0
    write_mode: str = "reuse_existing"
    repair_stock_code_count: int = 0
    repair_start_time: str | None = None
    repair_end_time: str | None = None
    repair_returned_row_count: int = 0
    repair_replaced_row_count: int = 0
    repair_appended_row_count: int = 0

    def materialization_extra_metadata(
        self,
        *,
        partition_key: str,
        freq: int,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "partition_key": partition_key,
            "freq": freq,
            "source_method": self.source_method,
            "write_mode": self.write_mode,
            "stock_code_count": self.stock_code_count,
            "returned_stock_code_count": self.returned_stock_code_count,
            "empty_stock_code_count": self.empty_stock_code_count,
            "page_count": self.page_count,
            "query_count": self.query_count,
            "limit": STK_MINS_TUSHARE_PAGE_LIMIT,
        }
        if self.write_mode == "merge_repair":
            metadata.update(
                {
                    "repair_stock_code_count": self.repair_stock_code_count,
                    "repair_start_time": self.repair_start_time,
                    "repair_end_time": self.repair_end_time,
                    "repair_returned_row_count": self.repair_returned_row_count,
                    "repair_replaced_row_count": self.repair_replaced_row_count,
                    "repair_appended_row_count": self.repair_appended_row_count,
                }
            )
        return metadata


def _freq_label(freq: int | str) -> str:
    return _STK_MINS_FREQ_LABELS[normalize_stk_mins_freq(freq)]


def _partition_window(
    partition_key: str,
    *,
    start_time: str = "09:00:00",
    end_time: str = "19:00:00",
) -> tuple[str, str]:
    datetime.strptime(partition_key, "%Y-%m-%d")
    return f"{partition_key} {start_time}", f"{partition_key} {end_time}"


def load_current_listed_stock_codes_for_stk_mins(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_key: str,
) -> tuple[str, ...]:
    stock_basic_path = silver_stock_basic_path(lake_root)
    if not stock_basic_path.exists():
        raise FileNotFoundError(f"Missing silver stock basic file: {stock_basic_path}")

    with duckdb.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT ts_code
            FROM {read_parquet(stock_basic_path, hive_partitioning=False)}
            WHERE list_status = 'L'
              AND list_date <= CAST({duckdb_string(partition_key)} AS DATE)
            ORDER BY ts_code
            """
        ).fetchall()

    return tuple(str(row[0]) for row in rows)


def write_raw_stk_mins_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    freq: int | str,
    partition_key: str,
    stock_codes: Sequence[str],
    request_interval_seconds: float = STK_MINS_REQUEST_INTERVAL_SECONDS,
) -> StkMinsRawWriteResult:
    normalized_freq = normalize_stk_mins_freq(freq)
    target_path = raw_stk_mins_path(lake_root, normalized_freq, partition_key)
    if target_path.exists():
        return _reuse_existing_raw_stk_mins_partition(
            duckdb=duckdb,
            raw_path=target_path,
            freq=normalized_freq,
            partition_key=partition_key,
            stock_code_count=len(stock_codes),
        )

    rows, stats = _fetch_raw_stk_mins_rows(
        tushare=tushare,
        freq=normalized_freq,
        partition_key=partition_key,
        stock_codes=stock_codes,
        request_interval_seconds=request_interval_seconds,
    )
    if not rows:
        raise RuntimeError(
            "Tushare stk_mins returned 0 rows for "
            f"freq={_freq_label(normalized_freq)}, partition={partition_key}."
        )

    _write_raw_stk_mins_rows(
        duckdb=duckdb,
        rows=rows,
        target_path=target_path,
    )
    columns, row_count = _raw_file_columns_and_count(duckdb, target_path)
    return StkMinsRawWriteResult(
        raw_file_path=target_path,
        row_count=row_count,
        observed_columns=columns,
        stock_code_count=len(stock_codes),
        returned_stock_code_count=stats["returned_stock_code_count"],
        empty_stock_code_count=stats["empty_stock_code_count"],
        page_count=stats["page_count"],
        source_method="tushare_api",
    )


def write_raw_stk_mins_partition_from_prod_db(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    freq: int | str,
    partition_key: str,
    stock_codes: Sequence[str],
) -> StkMinsRawWriteResult:
    normalized_freq = normalize_stk_mins_freq(freq)
    target_path = raw_stk_mins_path(lake_root, normalized_freq, partition_key)
    if target_path.exists():
        return _reuse_existing_raw_stk_mins_partition(
            duckdb=duckdb,
            raw_path=target_path,
            freq=normalized_freq,
            partition_key=partition_key,
            stock_code_count=len(stock_codes),
        )

    validate_prod_stk_mins_select_contract()
    rows, stats = _fetch_raw_stk_mins_rows_from_prod_db(
        prod_postgres=prod_postgres,
        freq=normalized_freq,
        partition_key=partition_key,
        stock_codes=stock_codes,
    )
    if not rows:
        raise RuntimeError(
            "Prod DB stk_mins returned 0 rows for "
            f"freq={normalized_freq}, partition={partition_key}."
        )

    _write_raw_stk_mins_rows(
        duckdb=duckdb,
        rows=rows,
        target_path=target_path,
    )
    columns, row_count = _raw_file_columns_and_count(duckdb, target_path)
    return StkMinsRawWriteResult(
        raw_file_path=target_path,
        row_count=row_count,
        observed_columns=columns,
        stock_code_count=len(stock_codes),
        returned_stock_code_count=stats["returned_stock_code_count"],
        empty_stock_code_count=stats["empty_stock_code_count"],
        page_count=0,
        query_count=stats["query_count"],
        source_method="prod_db_raw_tushare",
    )


def merge_repair_raw_stk_mins_partition_from_tushare(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    freq: int | str,
    partition_key: str,
    repair_config: StockMinsMergeRepairConfig,
    request_interval_seconds: float = STK_MINS_REQUEST_INTERVAL_SECONDS,
) -> StkMinsRawWriteResult:
    normalized_freq = normalize_stk_mins_freq(freq)
    target_path = raw_stk_mins_path(lake_root, normalized_freq, partition_key)
    if not target_path.exists():
        raise FileNotFoundError(f"Cannot repair missing stk_mins raw file: {target_path}")

    validation_errors = _validate_existing_raw_stk_mins_partition(
        duckdb=duckdb,
        raw_path=target_path,
        freq=normalized_freq,
        partition_key=partition_key,
        include_value_sanity=False,
    )
    if validation_errors:
        raise RuntimeError(
            "Existing stk_mins raw partition is not repairable: "
            f"path={target_path}, errors={validation_errors}."
        )

    rows, stats = _fetch_raw_stk_mins_rows(
        tushare=tushare,
        freq=normalized_freq,
        partition_key=partition_key,
        stock_codes=repair_config.stock_codes,
        request_interval_seconds=request_interval_seconds,
        start_time=repair_config.start_time,
        end_time=repair_config.end_time,
    )
    empty_stock_codes = tuple(stats.get("empty_stock_codes", ()))
    if empty_stock_codes:
        raise RuntimeError(
            "Tushare stk_mins returned 0 rows for repair stock codes: "
            f"{list(empty_stock_codes)}."
        )
    if not rows:
        raise RuntimeError(
            "Tushare stk_mins returned 0 rows for merge_repair: "
            f"freq={_freq_label(normalized_freq)}, partition={partition_key}."
        )

    merge_stats = _merge_repair_raw_stk_mins_rows(
        duckdb=duckdb,
        rows=rows,
        target_path=target_path,
    )
    columns, row_count = _raw_file_columns_and_count(duckdb, target_path)
    return StkMinsRawWriteResult(
        raw_file_path=target_path,
        row_count=row_count,
        observed_columns=columns,
        stock_code_count=len(repair_config.stock_codes),
        returned_stock_code_count=int(stats["returned_stock_code_count"]),
        empty_stock_code_count=int(stats["empty_stock_code_count"]),
        page_count=int(stats["page_count"]),
        source_method="tushare_merge_repair",
        write_mode="merge_repair",
        repair_stock_code_count=len(repair_config.stock_codes),
        repair_start_time=repair_config.start_time,
        repair_end_time=repair_config.end_time,
        repair_returned_row_count=merge_stats["repair_returned_row_count"],
        repair_replaced_row_count=merge_stats["repair_replaced_row_count"],
        repair_appended_row_count=merge_stats["repair_appended_row_count"],
    )


def _reuse_existing_raw_stk_mins_partition(
    *,
    duckdb: DuckDBResource,
    raw_path: Path,
    freq: int,
    partition_key: str,
    stock_code_count: int,
) -> StkMinsRawWriteResult:
    validation_errors = _validate_existing_raw_stk_mins_partition(
        duckdb=duckdb,
        raw_path=raw_path,
        freq=freq,
        partition_key=partition_key,
    )
    if validation_errors:
        raise RuntimeError(
            "Existing stk_mins raw partition is not reusable: "
            f"path={raw_path}, errors={validation_errors}."
        )

    columns, row_count = _raw_file_columns_and_count(duckdb, raw_path)
    return StkMinsRawWriteResult(
        raw_file_path=raw_path,
        row_count=row_count,
        observed_columns=columns,
        stock_code_count=stock_code_count,
        returned_stock_code_count=0,
        empty_stock_code_count=0,
        page_count=0,
        source_method="existing_raw_partition_reused",
    )


def _fetch_raw_stk_mins_rows(
    *,
    tushare: TushareResource,
    freq: int,
    partition_key: str,
    stock_codes: Sequence[str],
    request_interval_seconds: float,
    start_time: str = "09:00:00",
    end_time: str = "19:00:00",
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if not stock_codes:
        raise RuntimeError("No current listed stock codes available for stk_mins raw.")

    start_datetime, end_datetime = _partition_window(
        partition_key,
        start_time=start_time,
        end_time=end_time,
    )
    fetched_rows: list[dict[str, object]] = []
    returned_stock_codes: set[str] = set()
    page_count = 0
    request_count = 0

    for stock_code in stock_codes:
        offset = 0
        stock_had_rows = False
        while True:
            if request_count and request_interval_seconds > 0:
                time.sleep(request_interval_seconds)
            request_count += 1
            page_params = {
                "ts_code": stock_code,
                "freq": _freq_label(freq),
                "start_date": start_datetime,
                "end_date": end_datetime,
                "limit": STK_MINS_TUSHARE_PAGE_LIMIT,
                "offset": offset,
            }
            result = tushare.call("stk_mins", page_params, STK_MINS_RAW_COLUMNS)
            page_rows = result.rows
            if result.columns != STK_MINS_RAW_COLUMNS and (result.columns or page_rows):
                raise RuntimeError(
                    "Tushare stk_mins returned columns "
                    f"{list(result.columns)}, expected {list(STK_MINS_RAW_COLUMNS)}."
                )

            page_count += 1
            for row in page_rows:
                fetched_rows.append(
                    _normalize_tushare_stk_mins_row(
                        row,
                        requested_ts_code=stock_code,
                        requested_freq=freq,
                        partition_key=partition_key,
                        start_datetime=start_datetime,
                        end_datetime=end_datetime,
                    )
                )
            if page_rows:
                stock_had_rows = True
                returned_stock_codes.add(stock_code)
            if len(page_rows) < STK_MINS_TUSHARE_PAGE_LIMIT:
                break
            offset += STK_MINS_TUSHARE_PAGE_LIMIT

        if stock_had_rows:
            returned_stock_codes.add(stock_code)

    empty_stock_codes = tuple(
        stock_code for stock_code in stock_codes if stock_code not in returned_stock_codes
    )
    return fetched_rows, {
        "page_count": page_count,
        "returned_stock_code_count": len(returned_stock_codes),
        "empty_stock_code_count": len(empty_stock_codes),
        "empty_stock_codes": empty_stock_codes,
    }


def _fetch_raw_stk_mins_rows_from_prod_db(
    *,
    prod_postgres: ProdPostgresResource,
    freq: int,
    partition_key: str,
    stock_codes: Sequence[str],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    if not stock_codes:
        raise RuntimeError("No current listed stock codes available for stk_mins raw.")

    start_datetime, end_datetime = _partition_window(partition_key)
    fetched_rows: list[dict[str, object]] = []
    returned_stock_codes: set[str] = set()
    query_count = 0

    with prod_postgres.connect() as connection:
        for stock_code in stock_codes:
            source_rows = fetch_prod_stk_mins_rows(
                connection,
                ts_code=stock_code,
                freq=freq,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
            )
            query_count += 1
            if source_rows:
                returned_stock_codes.add(stock_code)
            for row in source_rows:
                fetched_rows.append(
                    _normalize_prod_db_stk_mins_row(
                        row,
                        requested_ts_code=stock_code,
                        requested_freq=freq,
                        partition_key=partition_key,
                    )
                )

    return fetched_rows, {
        "query_count": query_count,
        "returned_stock_code_count": len(returned_stock_codes),
        "empty_stock_code_count": len(stock_codes) - len(returned_stock_codes),
    }


def _normalize_tushare_stk_mins_row(
    row: Mapping[str, Any],
    *,
    requested_ts_code: str,
    requested_freq: int,
    partition_key: str,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
) -> dict[str, object]:
    ts_code = str(row.get("ts_code") or "").strip()
    if ts_code != requested_ts_code:
        raise RuntimeError(
            "Tushare stk_mins returned a row outside the requested stock code: "
            f"requested={requested_ts_code}, actual={ts_code}."
        )

    trade_time = row.get("trade_time")
    if not trade_time or str(trade_time)[:10] != partition_key:
        raise RuntimeError(
            "Tushare stk_mins returned a row outside the requested trade date: "
            f"partition={partition_key}, trade_time={trade_time!r}."
        )
    if start_datetime and end_datetime:
        parsed_trade_time = _parse_stk_mins_trade_time(trade_time)
        parsed_start_datetime = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M:%S")
        parsed_end_datetime = datetime.strptime(end_datetime, "%Y-%m-%d %H:%M:%S")
        if not parsed_start_datetime <= parsed_trade_time <= parsed_end_datetime:
            raise RuntimeError(
                "Tushare stk_mins returned a row outside the requested repair window: "
                f"window={start_datetime}..{end_datetime}, trade_time={trade_time!r}."
            )

    raw_freq = str(row.get("freq") or "").strip().lower()
    expected_freq = _freq_label(requested_freq)
    if raw_freq not in {expected_freq, str(requested_freq)}:
        raise RuntimeError(
            "Tushare stk_mins returned a row outside the requested frequency: "
            f"requested={expected_freq}, actual={raw_freq!r}."
        )

    return {
        "ts_code": ts_code,
        "freq": requested_freq,
        "trade_time": trade_time,
        "open": _clean_numeric_value(row.get("open")),
        "close": _clean_numeric_value(row.get("close")),
        "high": _clean_numeric_value(row.get("high")),
        "low": _clean_numeric_value(row.get("low")),
        "vol": _clean_integer_value(row.get("vol")),
        "amount": _clean_numeric_value(row.get("amount")),
        "exchange": _clean_string_value(row.get("exchange")),
        "vwap": _clean_numeric_value(row.get("vwap")),
    }


def _parse_stk_mins_trade_time(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError as error:
        raise RuntimeError(f"Invalid stk_mins trade_time: {value!r}.") from error


def _normalize_prod_db_stk_mins_row(
    row: Mapping[str, Any],
    *,
    requested_ts_code: str,
    requested_freq: int,
    partition_key: str,
) -> dict[str, object]:
    assert_prod_stk_mins_source_columns(row)
    ts_code = str(row.get("ts_code") or "").strip()
    if ts_code != requested_ts_code:
        raise RuntimeError(
            "Prod DB stk_mins returned a row outside the requested stock code: "
            f"requested={requested_ts_code}, actual={ts_code}."
        )

    raw_freq = normalize_stk_mins_freq(row.get("freq", ""))
    if raw_freq != requested_freq:
        raise RuntimeError(
            "Prod DB stk_mins returned a row outside the requested frequency: "
            f"requested={requested_freq}, actual={raw_freq}."
        )

    trade_time = row.get("trade_time")
    if not trade_time or str(trade_time)[:10] != partition_key:
        raise RuntimeError(
            "Prod DB stk_mins returned a row outside the requested trade date: "
            f"partition={partition_key}, trade_time={trade_time!r}."
        )

    vol = _clean_integer_value(row.get("vol"))
    amount = _clean_numeric_value(row.get("amount"))
    return {
        "ts_code": ts_code,
        "freq": requested_freq,
        "trade_time": trade_time,
        "open": _clean_numeric_value(row.get("open")),
        "close": _clean_numeric_value(row.get("close")),
        "high": _clean_numeric_value(row.get("high")),
        "low": _clean_numeric_value(row.get("low")),
        "vol": vol,
        "amount": amount,
        "exchange": derive_stk_mins_exchange_from_ts_code(ts_code),
        "vwap": _derive_stk_mins_vwap(amount=amount, vol=vol),
    }


def _clean_numeric_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _clean_string_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_integer_value(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    number = float(value)
    if not number.is_integer():
        raise RuntimeError(f"stk_mins vol must be integer-like, got {value!r}.")
    return int(number)


def _derive_stk_mins_vwap(*, amount: object, vol: int | None) -> float:
    if amount is None or vol is None or vol == 0:
        return 0.0
    return float(amount) / vol


def _write_raw_stk_mins_rows(
    *,
    duckdb: DuckDBResource,
    rows: Sequence[Mapping[str, object]],
    target_path: Path,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    with duckdb.connect() as connection:
        column_defs = ", ".join(
            f'"{column}" {STK_MINS_RAW_COLUMN_TYPES[column]}'
            for column in STK_MINS_RAW_COLUMNS
        )
        connection.execute(f"CREATE TEMP TABLE api_rows ({column_defs})")
        placeholders = ", ".join("?" for _column in STK_MINS_RAW_COLUMNS)
        values = [[row.get(column) for column in STK_MINS_RAW_COLUMNS] for row in rows]
        connection.executemany(f"INSERT INTO api_rows VALUES ({placeholders})", values)
        select_sql = ", ".join(
            f'CAST("{column}" AS {STK_MINS_RAW_COLUMN_TYPES[column]}) AS "{column}"'
            for column in STK_MINS_RAW_COLUMNS
        )
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT {select_sql}
                FROM api_rows
                ORDER BY ts_code, trade_time
                """,
                temporary_path,
            )
        )

    os.replace(temporary_path, target_path)


def _merge_repair_raw_stk_mins_rows(
    *,
    duckdb: DuckDBResource,
    rows: Sequence[Mapping[str, object]],
    target_path: Path,
) -> dict[str, int]:
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    with duckdb.connect() as connection:
        column_defs = ", ".join(
            f'"{column}" {STK_MINS_RAW_COLUMN_TYPES[column]}'
            for column in STK_MINS_RAW_COLUMNS
        )
        connection.execute(f"CREATE TEMP TABLE repair_rows ({column_defs})")
        placeholders = ", ".join("?" for _column in STK_MINS_RAW_COLUMNS)
        values = [[row.get(column) for column in STK_MINS_RAW_COLUMNS] for row in rows]
        connection.executemany(f"INSERT INTO repair_rows VALUES ({placeholders})", values)

        duplicate_key_count = int(
            connection.execute(
                """
                SELECT count(*)
                FROM (
                  SELECT ts_code, trade_time, count(*) AS row_count
                  FROM repair_rows
                  GROUP BY ts_code, trade_time
                  HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
        )
        if duplicate_key_count:
            raise RuntimeError(
                "Tushare merge_repair returned duplicate ts_code + trade_time keys."
            )

        existing_relation = read_parquet(target_path, hive_partitioning=False)
        replaced_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {existing_relation} AS existing_rows
                WHERE EXISTS (
                  SELECT 1
                  FROM repair_rows
                  WHERE repair_rows.ts_code = existing_rows.ts_code
                    AND repair_rows.trade_time = existing_rows.trade_time
                )
                """
            ).fetchone()[0]
        )
        repair_row_count = int(
            connection.execute("SELECT count(*) FROM repair_rows").fetchone()[0]
        )
        appended_count = repair_row_count - replaced_count

        select_existing_columns = ", ".join(
            f'existing_rows."{column}" AS "{column}"' for column in STK_MINS_RAW_COLUMNS
        )
        select_repair_columns = ", ".join(
            f'repair_rows."{column}" AS "{column}"' for column in STK_MINS_RAW_COLUMNS
        )
        cast_columns = ", ".join(
            f'CAST("{column}" AS {STK_MINS_RAW_COLUMN_TYPES[column]}) AS "{column}"'
            for column in STK_MINS_RAW_COLUMNS
        )
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT {cast_columns}
                FROM (
                  SELECT {select_existing_columns}
                  FROM {existing_relation} AS existing_rows
                  WHERE NOT EXISTS (
                    SELECT 1
                    FROM repair_rows
                    WHERE repair_rows.ts_code = existing_rows.ts_code
                      AND repair_rows.trade_time = existing_rows.trade_time
                  )
                  UNION ALL
                  SELECT {select_repair_columns}
                  FROM repair_rows
                ) AS merged_rows
                ORDER BY ts_code, trade_time
                """,
                temporary_path,
            )
        )

    os.replace(temporary_path, target_path)
    return {
        "repair_returned_row_count": repair_row_count,
        "repair_replaced_row_count": replaced_count,
        "repair_appended_row_count": appended_count,
    }


def _raw_file_columns_and_count(
    duckdb: DuckDBResource,
    raw_path: Path,
) -> tuple[tuple[str, ...], int]:
    with duckdb.connect() as connection:
        columns = tuple(
            row[0]
            for row in connection.execute(
                describe_parquet_query(raw_path, hive_partitioning=False)
            ).fetchall()
        )
        row_count = int(
            connection.execute(
                count_parquet_query(raw_path, hive_partitioning=False)
            ).fetchone()[0]
        )
    return columns, row_count


def _validate_existing_raw_stk_mins_partition(
    *,
    duckdb: DuckDBResource,
    raw_path: Path,
    freq: int,
    partition_key: str,
    include_value_sanity: bool = True,
) -> tuple[str, ...]:
    errors = []
    if not raw_path.exists():
        return ("missing_file",)

    with duckdb.connect() as connection:
        relation = read_parquet(raw_path, hive_partitioning=False)
        schema_rows = connection.execute(
            describe_parquet_query(raw_path, hive_partitioning=False)
        ).fetchall()
        observed_schema = {row[0]: row[1] for row in schema_rows}
        expected_schema = STK_MINS_RAW_COLUMN_TYPES
        row_count = int(
            connection.execute(
                count_parquet_query(raw_path, hive_partitioning=False)
            ).fetchone()[0]
        )
        if row_count <= 0:
            errors.append("row_count_not_positive")
        if observed_schema != expected_schema:
            errors.append("schema_mismatch")

        if row_count > 0:
            freq_mismatch_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM {relation}
                    WHERE CAST(freq AS INTEGER) != {freq}
                    """
                ).fetchone()[0]
            )
            if freq_mismatch_count:
                errors.append("freq_mismatch")

            date_mismatch_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM {relation}
                    WHERE CAST(trade_time AS DATE) != CAST({duckdb_string(partition_key)} AS DATE)
                    """
                ).fetchone()[0]
            )
            if date_mismatch_count:
                errors.append("partition_date_mismatch")

            duplicate_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM (
                      SELECT ts_code, trade_time, count(*) AS row_count
                      FROM {relation}
                      GROUP BY ts_code, trade_time
                      HAVING count(*) > 1
                    )
                    """
                ).fetchone()[0]
            )
            if duplicate_count:
                errors.append("duplicate_ts_code_trade_time")

            if include_value_sanity:
                invalid_value_count = int(
                    connection.execute(
                        f"""
                        SELECT count(*)
                        FROM {relation}
                        WHERE ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
                           OR open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
                           OR vol IS NULL OR amount IS NULL OR vwap IS NULL
                           OR open < 0 OR close < 0 OR high < 0 OR low < 0
                           OR vol < 0 OR amount < 0 OR vwap < 0
                        """
                    ).fetchone()[0]
                )
                if invalid_value_count:
                    errors.append("invalid_price_volume_values")

    return tuple(errors)


def _materialize_raw_stk_mins_partition(
    *,
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    freq: int,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    config = parse_stock_mins_raw_config(context.op_config)
    if config.write_mode == "merge_repair":
        if config.merge_repair is None:
            raise AssertionError("merge_repair config is required.")
        write_result = merge_repair_raw_stk_mins_partition_from_tushare(
            lake_root=lake_root.root(),
            duckdb=duckdb,
            tushare=tushare,
            freq=freq,
            partition_key=partition_key,
            repair_config=config.merge_repair,
        )
    elif config.source == "tushare":
        stock_codes = load_current_listed_stock_codes_for_stk_mins(
            lake_root=lake_root.root(),
            duckdb=duckdb,
            partition_key=partition_key,
        )
        write_result = write_raw_stk_mins_partition(
            lake_root=lake_root.root(),
            duckdb=duckdb,
            tushare=tushare,
            freq=freq,
            partition_key=partition_key,
            stock_codes=stock_codes,
        )
    elif config.source == "prod_db":
        stock_codes = load_current_listed_stock_codes_for_stk_mins(
            lake_root=lake_root.root(),
            duckdb=duckdb,
            partition_key=partition_key,
        )
        write_result = write_raw_stk_mins_partition_from_prod_db(
            lake_root=lake_root.root(),
            duckdb=duckdb,
            prod_postgres=prod_postgres,
            freq=freq,
            partition_key=partition_key,
            stock_codes=stock_codes,
        )
    else:
        raise AssertionError(f"Unhandled stk_mins raw config: {config}")
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=write_result.raw_file_path,
            row_count=write_result.row_count,
            observed_columns=write_result.observed_columns,
            extra_metadata=write_result.materialization_extra_metadata(
                partition_key=partition_key,
                freq=freq,
            ),
        )
    )


def _raw_stk_mins_extra_metadata(freq: int) -> dict[str, object]:
    return {
        "freq": freq,
        "freq_label": _freq_label(freq),
        "source_window": "09:00:00-19:00:00",
        "bootstrap_source": "backup_clean_next",
        "daily_source": "prod_db_raw_tushare",
        "fallback_source": "tushare_stk_mins",
        "raw_contract": (
            "Historical baseline comes from backup clean_next; daily partitions "
            "default to prod DB raw_tushare.stk_mins, with Tushare stk_mins kept "
            "as a manual fallback; all sources are normalized to the same raw schema."
        ),
    }


@dg.asset(
    name="raw_stk_mins_1m",
    deps=[silver_stock_basic],
    partitions_def=cn_a_stock_mins_trade_days,
    config_schema=STOCK_MINS_RAW_CONFIG_SCHEMA,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stk_mins",
        source_system=SourceSystem.TUSHARE,
        source_api="stk_mins",
        source_category_path="股票数据 / 行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md",
        data_contract="source_mirror",
        column_schema=RAW_STK_MINS_SCHEMA,
        path_template=lake_path_template(
            raw_stk_mins_path(PATH_TEMPLATE_LAKE_ROOT, 1, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata=_raw_stk_mins_extra_metadata(1),
    ),
    description="股票 1 分钟 raw 行情，历史基线来自 clean_next，默认日常来自 prod DB，Tushare 保留为备用。",
)
def raw_stk_mins_1m(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
) -> dg.MaterializeResult:
    return _materialize_raw_stk_mins_partition(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        tushare=tushare,
        prod_postgres=prod_postgres,
        freq=1,
    )


@dg.asset(
    name="raw_stk_mins_5m",
    deps=[silver_stock_basic],
    partitions_def=cn_a_stock_mins_trade_days,
    config_schema=STOCK_MINS_RAW_CONFIG_SCHEMA,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stk_mins",
        source_system=SourceSystem.TUSHARE,
        source_api="stk_mins",
        source_category_path="股票数据 / 行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md",
        data_contract="source_mirror",
        column_schema=RAW_STK_MINS_SCHEMA,
        path_template=lake_path_template(
            raw_stk_mins_path(PATH_TEMPLATE_LAKE_ROOT, 5, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata=_raw_stk_mins_extra_metadata(5),
    ),
    description="股票 5 分钟 raw 行情，历史基线来自 clean_next，默认日常来自 prod DB，Tushare 保留为备用。",
)
def raw_stk_mins_5m(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
) -> dg.MaterializeResult:
    return _materialize_raw_stk_mins_partition(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        tushare=tushare,
        prod_postgres=prod_postgres,
        freq=5,
    )


@dg.asset(
    name="raw_stk_mins_15m",
    deps=[silver_stock_basic],
    partitions_def=cn_a_stock_mins_trade_days,
    config_schema=STOCK_MINS_RAW_CONFIG_SCHEMA,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stk_mins",
        source_system=SourceSystem.TUSHARE,
        source_api="stk_mins",
        source_category_path="股票数据 / 行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md",
        data_contract="source_mirror",
        column_schema=RAW_STK_MINS_SCHEMA,
        path_template=lake_path_template(
            raw_stk_mins_path(PATH_TEMPLATE_LAKE_ROOT, 15, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata=_raw_stk_mins_extra_metadata(15),
    ),
    description="股票 15 分钟 raw 行情，历史基线来自 clean_next，默认日常来自 prod DB，Tushare 保留为备用。",
)
def raw_stk_mins_15m(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
) -> dg.MaterializeResult:
    return _materialize_raw_stk_mins_partition(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        tushare=tushare,
        prod_postgres=prod_postgres,
        freq=15,
    )


@dg.asset(
    name="raw_stk_mins_30m",
    deps=[silver_stock_basic],
    partitions_def=cn_a_stock_mins_trade_days,
    config_schema=STOCK_MINS_RAW_CONFIG_SCHEMA,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stk_mins",
        source_system=SourceSystem.TUSHARE,
        source_api="stk_mins",
        source_category_path="股票数据 / 行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md",
        data_contract="source_mirror",
        column_schema=RAW_STK_MINS_SCHEMA,
        path_template=lake_path_template(
            raw_stk_mins_path(PATH_TEMPLATE_LAKE_ROOT, 30, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata=_raw_stk_mins_extra_metadata(30),
    ),
    description="股票 30 分钟 raw 行情，历史基线来自 clean_next，默认日常来自 prod DB，Tushare 保留为备用。",
)
def raw_stk_mins_30m(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
) -> dg.MaterializeResult:
    return _materialize_raw_stk_mins_partition(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        tushare=tushare,
        prod_postgres=prod_postgres,
        freq=30,
    )


@dg.asset(
    name="raw_stk_mins_60m",
    deps=[silver_stock_basic],
    partitions_def=cn_a_stock_mins_trade_days,
    config_schema=STOCK_MINS_RAW_CONFIG_SCHEMA,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stk_mins",
        source_system=SourceSystem.TUSHARE,
        source_api="stk_mins",
        source_category_path="股票数据 / 行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md",
        data_contract="source_mirror",
        column_schema=RAW_STK_MINS_SCHEMA,
        path_template=lake_path_template(
            raw_stk_mins_path(PATH_TEMPLATE_LAKE_ROOT, 60, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata=_raw_stk_mins_extra_metadata(60),
    ),
    description="股票 60 分钟 raw 行情，历史基线来自 clean_next，默认日常来自 prod DB，Tushare 保留为备用。",
)
def raw_stk_mins_60m(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
) -> dg.MaterializeResult:
    return _materialize_raw_stk_mins_partition(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        tushare=tushare,
        prod_postgres=prod_postgres,
        freq=60,
    )


RAW_STK_MINS_ASSETS = (
    raw_stk_mins_1m,
    raw_stk_mins_5m,
    raw_stk_mins_15m,
    raw_stk_mins_30m,
    raw_stk_mins_60m,
)
