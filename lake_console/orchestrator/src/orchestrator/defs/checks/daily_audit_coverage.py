"""Evidence produced by existing Checks for the daily audit."""

import json
import logging
from hashlib import sha256

import dagster as dg
import duckdb
from sqlalchemy.exc import SQLAlchemyError

from orchestrator.defs.duckdb_sql import read_parquet

logger = logging.getLogger(__name__)
TARGET_VERSION_TAG = "audit/target_file_version"
REGULAR_STOCK_MINUTE_ROWS = {1: 241, 5: 49, 15: 17, 30: 9, 60: 5}


def key_coverage(expected, actual, *, record_extras=True, confirm_changes=False):
    missing = expected - actual
    extra = actual - expected if record_extras else set()
    return {
        "status": ("pending" if confirm_changes else "gap")
        if missing or extra
        else "complete",
        "expected_count": len(expected),
        "actual_count": len(actual if record_extras else actual & expected),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "samples": [
            {"ts_code": code, "change": change}
            for change, keys in (("missing", missing), ("extra", extra))
            for code in sorted(keys)[:10]
        ],
    }


def stock_minute_coverage(expected_codes, actual_by_code, freq):
    coverage = key_coverage(expected_codes, actual_by_code.keys())
    expected = len(expected_codes) * REGULAR_STOCK_MINUTE_ROWS[freq]
    actual = sum(actual_by_code.values())
    if expected != actual:
        coverage["status"] = "gap"
    return {
        **coverage,
        "expected_count": expected,
        "actual_count": actual,
        "expected_code_count": len(expected_codes),
        "actual_code_count": len(actual_by_code),
        "rule_version": "stock_minute_regular_coverage_v1",
    }


def stat_version(path):
    if not path.is_file():
        return None
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def version_string(value):
    return json.dumps(value, separators=(",", ":"))


def is_requested_version(context, version):
    requested = context.run.tags.get(TARGET_VERSION_TAG)
    return not requested or requested == version_string(version)


def minute_file_batch_version(files):
    return sha256(
        version_string(
            sorted((str(path), identity) for path, identity in files)
        ).encode()
    ).hexdigest()


def select_codes(connection, query, parameters):
    try:
        return {code for (code,) in connection.execute(query, parameters).fetchall()}
    except duckdb.Error:
        logger.warning("暂无法读取日审计参照代码", exc_info=True)
        return None


def snapshot_comparison(connection, expected_sql, target, columns):
    projection = ", ".join(columns)
    actual = read_parquet(target, hive_partitioning=False)
    try:
        expected, observed, missing, extra = connection.execute(
            f"""
            WITH expected AS (SELECT {projection} FROM ({expected_sql})),
                 actual AS (SELECT {projection} FROM {actual})
            SELECT
              (SELECT count(*) FROM expected),
              (SELECT count(*) FROM actual),
              (SELECT count(*) FROM (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)),
              (SELECT count(*) FROM (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected))
            """
        ).fetchone()
    except duckdb.Error:
        logger.warning("暂无法对账快照 %s", target.name, exc_info=True)
        return None
    return {
        "status": "gap" if missing or extra else "complete",
        "expected_count": expected,
        "actual_count": observed,
        "missing_count": missing,
        "extra_count": extra,
        "samples": [],
        "rule_version": "stock_snapshot_projection_v1",
    }


def published_comparison_metadata(context, asset_key, path, *, partition=None):
    target = dg.AssetRecordsFilter(
        asset_key=dg.AssetKey(asset_key),
        asset_partitions=[partition] if partition else None,
    )
    try:
        records = context.instance.fetch_materializations(target, limit=1).records
    except SQLAlchemyError:
        logger.warning("暂无法读取 %s 快照版本", asset_key, exc_info=True)
        return {}
    if not records or not path.is_file():
        return {}
    value = records[0].asset_materialization.metadata.get(
        "goldenshare/audit_comparison"
    )
    comparison = value.value if value else None
    if not comparison or comparison["file_version"] != stat_version(path):
        return {}
    return {"audit_coverage": comparison}
