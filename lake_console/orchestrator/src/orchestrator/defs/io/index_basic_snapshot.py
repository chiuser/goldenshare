"""Tushare index basic collection and candidate comparisons."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.duckdb_sql import (
    INDEX_BASIC_RAW_COLUMNS,
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
    silver_index_basic_select,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_INDEX_BASIC_SCHEMA,
    SILVER_INDEX_BASIC_SCHEMA,
)
from orchestrator.defs.tushare_api_io import (
    TUSHARE_API_PAGE_LIMIT,
    iter_tushare_pages,
    write_verified_tushare_raw_candidate,
)

KNOWN_MARKETS = ("BSE", "CI", "CNI", "CSI", "NH", "SSE", "SW", "SZSE")
_SAMPLE_LIMIT = 10


def duplicate_codes_sql(path: Path) -> str:
    return f"""
        SELECT ts_code, count(*) AS row_count
        FROM {read_parquet(path, hive_partitioning=False)}
        WHERE ts_code IS NOT NULL AND trim(ts_code) != ''
        GROUP BY ts_code HAVING count(*) > 1
    """


def invalid_raw_dates_sql(path: Path) -> str:
    source = read_parquet(path, hive_partitioning=False)
    queries = [
        f"""SELECT ts_code, '{field}' AS field_name, {field} AS field_value
        FROM {source} WHERE {field} IS NOT NULL
          AND trim(CAST({field} AS VARCHAR)) != ''
          AND try_strptime(trim(CAST({field} AS VARCHAR)), '%Y%m%d') IS NULL"""
        for field in ("base_date", "list_date", "exp_date")
    ]
    return " UNION ALL ".join(queries)


def terminated_index_predicate(ready_date: str) -> str:
    return f"exp_date IS NOT NULL AND exp_date <= DATE {duckdb_string(ready_date)}"


def _validate_candidate(connection, path: Path, *, raw: bool) -> int:
    schema = RAW_TUSHARE_INDEX_BASIC_SCHEMA if raw else SILVER_INDEX_BASIC_SCHEMA
    observed = connection.execute(describe_parquet_query(path, hive_partitioning=False))
    if [(row[0], row[1].upper()) for row in observed.fetchall()] != [
        (column.name, column.type.upper()) for column in schema
    ]:
        raise ValueError(
            f"Index basic candidate schema differs from its contract: {path}"
        )
    source = read_parquet(path, hive_partitioning=False)
    required = ("ts_code",) if raw else ("ts_code", "name", "market")
    invalid_key = " OR ".join(
        f"{name} IS NULL OR trim({name}) = ''" for name in required
    )
    count, missing, duplicates = connection.execute(
        f"""SELECT count(*), count(*) FILTER (WHERE {invalid_key}),
           (SELECT count(*) FROM ({duplicate_codes_sql(path)})) FROM {source}"""
    ).fetchone()
    if not count or missing or duplicates:
        raise ValueError(
            f"Invalid index basic candidate counts: {count=}, {missing=}, {duplicates=}"
        )
    if (
        raw
        and connection.execute(
            f"SELECT 1 FROM ({invalid_raw_dates_sql(path)}) LIMIT 1"
        ).fetchone()
    ):
        raise ValueError("Index basic Raw candidate contains invalid dates")
    return count


def _collect(tushare, market: str | None = None):
    rows = []
    seen = set()
    pages = []
    fields = INDEX_BASIC_RAW_COLUMNS if market is None else ("ts_code", "market")
    params = {} if market is None else {"market": market}
    for offset, page in iter_tushare_pages(
        tushare=tushare,
        api_name="index_basic",
        api_params=params,
        field_names=fields,
        limit=TUSHARE_API_PAGE_LIMIT,
    ):
        if len(page) > TUSHARE_API_PAGE_LIMIT:
            raise ValueError(
                f"Index basic source exceeded page limit at {market=}, {offset=}"
            )
        for row in page:
            code = row["ts_code"]
            if not isinstance(code, str) or not code.strip() or code in seen:
                raise ValueError(
                    f"Index basic source has missing or duplicate ts_code at {market=}, {offset=}: {code!r}"
                )
            if market is not None and row["market"] != market:
                raise ValueError(
                    f"Index basic source ignored market filter {market!r} for {code}"
                )
            seen.add(code)
        rows.extend(page)
        pages.append({"offset": offset, "rows": len(page)})
    return rows, pages


def write_index_basic_raw(tushare, duckdb, path: Path, *, verify_markets: bool) -> dict:
    started = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    rows, pages = _collect(tushare)
    if not rows:
        raise ValueError("Index basic source did not return any rows")
    markets: dict[str, set[str]] = {}
    unclassified = 0
    for row in rows:
        market = row["market"]
        if isinstance(market, str) and market.strip():
            markets.setdefault(market, set()).add(row["ts_code"])
        else:
            unclassified += 1

    evidence = {
        "passed": True,
        "fetched_at": started,
        "source_rows": len(rows),
        "page_limit": TUSHARE_API_PAGE_LIMIT,
        "pages": pages,
        "unclassified_rows": unclassified,
        "market_counts": {
            market: len(codes) for market, codes in sorted(markets.items())
        },
    }
    if verify_markets:
        market_pages = {}
        for market in sorted(set(KNOWN_MARKETS) | markets.keys()):
            source, filtered_pages = _collect(tushare, market)
            expected = {row["ts_code"] for row in source}
            actual = markets.get(market, set())
            if expected != actual:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                raise ValueError(
                    f"Index basic market coverage differs for {market}: "
                    f"missing={len(missing)} {missing[:_SAMPLE_LIMIT]}, "
                    f"extra={len(extra)} {extra[:_SAMPLE_LIMIT]}"
                )
            market_pages[market] = filtered_pages
        evidence["market_pages"] = market_pages

    write_verified_tushare_raw_candidate(
        duckdb=duckdb,
        rows=rows,
        fields=INDEX_BASIC_RAW_COLUMNS,
        column_types={
            column.name: column.type for column in RAW_TUSHARE_INDEX_BASIC_SCHEMA
        },
        target_path=path,
    )
    with duckdb.connect() as connection:
        evidence["candidate_rows"] = _validate_candidate(connection, path, raw=True)
    return evidence


def write_index_basic_silver(
    connection, raw_path: Path, path: Path, ready_date: str
) -> dict:
    expected = silver_index_basic_select(raw_path, ready_date)
    connection.execute(copy_query_to_parquet(expected, path))
    count = _validate_candidate(connection, path, raw=False)
    actual = read_parquet(path, hive_partitioning=False)
    groups = connection.execute(
        f"""WITH expected AS ({expected}), differences AS (
          SELECT coalesce(e.ts_code, s.ts_code) AS ts_code,
            CASE WHEN s.ts_code IS NULL THEN 'missing'
                 WHEN e.ts_code IS NULL THEN 'extra' ELSE 'termination_mismatch' END AS reason
          FROM expected e FULL OUTER JOIN {actual} s USING (ts_code)
          WHERE s.ts_code IS NULL OR e.ts_code IS NULL OR e.exp_date IS DISTINCT FROM s.exp_date
        ) SELECT reason, count(*), list_slice(list(ts_code ORDER BY ts_code), 1, {_SAMPLE_LIMIT})
          FROM differences GROUP BY reason ORDER BY reason"""
    ).fetchall()
    if groups:
        raise ValueError(
            f"Index basic Silver differs from the source projection: {groups}"
        )
    return {
        "passed": True,
        "expected_rows": count,
        "candidate_rows": count,
        "missing_codes": 0,
        "extra_codes": 0,
        "termination_mismatches": 0,
        "ready_for_trade_date": ready_date,
    }


def raw_index_basic_changes(connection, before: Path, after: Path) -> dict:
    if not before.is_file():
        codes = connection.execute(
            f"SELECT ts_code FROM {read_parquet(after, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall()
        return {"added": [code for (code,) in codes], "removed": [], "changed": []}
    old = read_parquet(before, hive_partitioning=False)
    new = read_parquet(after, hive_partitioning=False)
    fields = ", ".join(
        f'''CASE WHEN b."{field}" IS DISTINCT FROM a."{field}" THEN '{field}' END'''
        for field in INDEX_BASIC_RAW_COLUMNS[1:]
    )
    rows = connection.execute(
        f"""WITH compared AS (
          SELECT coalesce(b.ts_code, a.ts_code) AS code,
            CASE WHEN b.ts_code IS NULL THEN 'added'
                 WHEN a.ts_code IS NULL THEN 'removed' ELSE 'changed' END AS status,
            list_filter([{fields}], field -> field IS NOT NULL) AS changed_fields
          FROM {old} b FULL OUTER JOIN {new} a USING (ts_code)
        ) SELECT code, status, changed_fields FROM compared
          WHERE status <> 'changed' OR len(changed_fields) > 0 ORDER BY code"""
    ).fetchall()
    return {
        "added": [code for code, status, _ in rows if status == "added"],
        "removed": [code for code, status, _ in rows if status == "removed"],
        "changed": [
            {"ts_code": code, "fields": fields}
            for code, status, fields in rows
            if status == "changed"
        ],
    }
