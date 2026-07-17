"""Bounded readiness for the local ClickHouse board technical serving copy."""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_TECHNICAL_INDICATOR_VERSION,
    DC_DAILY_TECHNICAL_PARAMS_KEY,
)
from orchestrator.defs.run_contracts.dc_daily_technical_serving import (
    CH_DC_DAILY_TECHNICAL_CHECKS,
    DC_DAILY_TECHNICAL_SERVING_TABLE,
    DC_DAILY_TECHNICAL_SERVING_WINDOW_LIMIT,
    PROD_CH_DC_DAILY_TECHNICAL_CHECKS,
)


CHECK_NAME = "ch_dc_daily_technical_core_check"
PROD_CHECK_NAME = PROD_CH_DC_DAILY_TECHNICAL_CHECKS[0]


def _is_missing_table(error: Exception) -> bool:
    text = str(error).upper()
    return (
        "UNKNOWN TABLE" in text
        or "UNKNOWN_TABLE" in text
        or "TABLE DOESN'T EXIST" in text
    )


def _filter_sql(expected_trade_dates: Sequence[str]) -> tuple[str, dict[str, object]]:
    if not expected_trade_dates:
        raise ValueError("expected_trade_dates must not be empty")
    params: dict[str, object] = {}
    placeholders: list[str] = []
    for index, trade_date in enumerate(expected_trade_dates):
        name = f"trade_date_{index}"
        placeholders.append(f"%({name})s")
        params[name] = trade_date
    return f"trade_date IN ({', '.join(placeholders)})", params


def _query_partition_metrics(client, expected_trade_dates: Sequence[str]):
    where_sql, params = _filter_sql(expected_trade_dates)
    return client.execute(
        f"""
        SELECT
          trade_date,
          count() AS row_count,
          uniqExact(tuple(ts_code, trade_date, category)) AS unique_key_count,
          countIf(ts_code IS NULL OR trim(ts_code) = '') AS invalid_code_count,
          countIf(category IS NULL OR trim(category) = '') AS invalid_category_count,
          countIf(params_key != %(params_key)s) AS params_mismatch_count,
          countIf(indicator_version != %(indicator_version)s) AS version_mismatch_count
        FROM {DC_DAILY_TECHNICAL_SERVING_TABLE}
        WHERE {where_sql}
        GROUP BY trade_date
        ORDER BY trade_date
        """,
        {
            **params,
            "params_key": DC_DAILY_TECHNICAL_PARAMS_KEY,
            "indicator_version": DC_DAILY_TECHNICAL_INDICATOR_VERSION,
        },
    )


def batch_ch_dc_daily_technical_lake_readiness(
    *,
    client,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
) -> ContinuityBatchReadiness:
    """Read at most the recent window with one bounded ClickHouse query."""

    started = perf_counter()
    expected = tuple(str(value) for value in expected_trade_dates)
    if len(expected) > DC_DAILY_TECHNICAL_SERVING_WINDOW_LIMIT:
        raise ValueError(
            "ClickHouse technical readiness window exceeds "
            f"{DC_DAILY_TECHNICAL_SERVING_WINDOW_LIMIT} trade dates."
        )
    registered = set(str(value) for value in registered_trade_days)
    statuses: dict[str, ContinuityDateReadiness] = {}
    try:
        rows = _query_partition_metrics(client, expected)
    except Exception as error:
        reason = "missing_clickhouse_table" if _is_missing_table(error) else "scan_error"
        for trade_date in expected:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=reason != "missing_clickhouse_table",
                checks_passed=False,
                reason=reason,
                failed_check_names=(CHECK_NAME,) if reason == "scan_error" else (),
                missing_check_names=(CHECK_NAME,) if reason == "missing_clickhouse_table" else (),
                summary={
                    "dataset": "ch_dc_daily_technical",
                    "target_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
                    "scan_error": str(error)[:500],
                    "registered": trade_date in registered,
                },
            )
        return ContinuityBatchReadiness(
            expected_trade_dates=expected,
            statuses_by_trade_date=statuses,
            elapsed_ms=max(0, int((perf_counter() - started) * 1000)),
            scanned_file_count=0,
        )

    metrics_by_date = {str(row[0]): tuple(row[1:]) for row in rows}
    for trade_date in expected:
        metrics = metrics_by_date.get(trade_date)
        if metrics is None or int(metrics[0]) == 0:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="missing_clickhouse_partition",
                missing_check_names=(CHECK_NAME,),
                summary={
                    "dataset": "ch_dc_daily_technical",
                    "target_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
                    "row_count": 0,
                    "registered": trade_date in registered,
                },
            )
            continue

        (
            row_count,
            unique_key_count,
            invalid_code_count,
            invalid_category_count,
            params_mismatch_count,
            version_mismatch_count,
        ) = (int(value or 0) for value in metrics)
        failed_rules: list[str] = []
        if unique_key_count != row_count:
            failed_rules.append("business_key_unique")
        if invalid_code_count or invalid_category_count:
            failed_rules.append("business_key_non_null")
        if params_mismatch_count or version_mismatch_count:
            failed_rules.append("indicator_metadata_matches_contract")
        passed = not failed_rules
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=passed,
            materialized=True,
            checks_passed=passed,
            reason="ready" if passed else "core_check_failed",
            failed_check_names=() if passed else (CHECK_NAME,),
            summary={
                "dataset": "ch_dc_daily_technical",
                "target_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
                "row_count": row_count,
                "unique_key_count": unique_key_count,
                "invalid_code_count": invalid_code_count,
                "invalid_category_count": invalid_category_count,
                "params_mismatch_count": params_mismatch_count,
                "version_mismatch_count": version_mismatch_count,
                "failed_rules": failed_rules,
                "registered": trade_date in registered,
            },
        )

    return ContinuityBatchReadiness(
        expected_trade_dates=expected,
        statuses_by_trade_date=statuses,
        elapsed_ms=max(0, int((perf_counter() - started) * 1000)),
        scanned_file_count=0,
    )


def batch_prod_ch_dc_daily_technical_lake_readiness(
    *,
    local_client,
    prod_client,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
) -> ContinuityBatchReadiness:
    """Compare local and Prod serving with two bounded ClickHouse scans."""

    started = perf_counter()
    local_batch = batch_ch_dc_daily_technical_lake_readiness(
        client=local_client,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
    )
    prod_batch = batch_ch_dc_daily_technical_lake_readiness(
        client=prod_client,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
    )
    statuses: dict[str, ContinuityDateReadiness] = {}
    for trade_date in tuple(str(value) for value in expected_trade_dates):
        local_status = local_batch.status_for_trade_date(trade_date)
        prod_status = prod_batch.status_for_trade_date(trade_date)
        summary = {
            "dataset": "prod_ch_dc_daily_technical",
            "target_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
            "local": local_status.to_cursor_details(),
            "prod": prod_status.to_cursor_details(),
        }
        if not local_status.ready:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=local_status.materialized,
                checks_passed=False,
                reason=(
                    "local_materialized_check_failed"
                    if local_status.materialized
                    else "local_not_ready"
                ),
                failed_check_names=(
                    local_status.failed_check_names
                    or CH_DC_DAILY_TECHNICAL_CHECKS
                )
                if local_status.materialized
                else (),
                missing_check_names=(
                    local_status.missing_check_names
                    or CH_DC_DAILY_TECHNICAL_CHECKS
                )
                if not local_status.materialized
                else (),
                summary=summary,
            )
            continue
        if not prod_status.ready:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=prod_status.materialized,
                checks_passed=False,
                reason=(
                    "prod_materialized_check_failed"
                    if prod_status.materialized
                    else "missing_prod_clickhouse_partition"
                ),
                failed_check_names=(
                    prod_status.failed_check_names
                    or (PROD_CHECK_NAME,)
                )
                if prod_status.materialized
                else (),
                missing_check_names=(
                    prod_status.missing_check_names
                    or (PROD_CHECK_NAME,)
                )
                if not prod_status.materialized
                else (),
                summary=summary,
            )
            continue
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=True,
            materialized=True,
            checks_passed=True,
            reason="ready",
            summary=summary,
        )

    return ContinuityBatchReadiness(
        expected_trade_dates=tuple(str(value) for value in expected_trade_dates),
        statuses_by_trade_date=statuses,
        elapsed_ms=max(0, int((perf_counter() - started) * 1000)),
        scanned_file_count=(
            local_batch.scanned_file_count + prod_batch.scanned_file_count
        ),
    )


__all__ = [
    "batch_ch_dc_daily_technical_lake_readiness",
    "batch_prod_ch_dc_daily_technical_lake_readiness",
]
