from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from psycopg2.extras import RealDictCursor


ASSET_CHECK_RETENTION_KEEP_TRADE_DAY_COUNT = 20
ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES = (
    "gold_stk_mins_qfq_factor_repair_plan_evaluated",
    "gold_stk_mins_qfq_macd_kdj_repair_completed_check",
)
RUNNING_OR_QUEUED_STATUSES = (
    "QUEUED",
    "STARTING",
    "STARTED",
    "CANCELING",
)

_STOCK_TRADE_DAYS = "cn_a_stock_trade_days"
_STOCK_CURRENT_TRADE_DAYS = "cn_a_stock_current_trade_days"
_INDEX_TRADE_DAYS = "cn_a_index_trade_days"
_STOCK_MINS_SILVER_TRADE_DAYS = "cn_a_stock_mins_silver_trade_days"


def _asset_key(name: str) -> str:
    return json.dumps([name], separators=(",", ":"))


_ASSET_FAMILY_BY_NAME = {
    "raw_tushare_trade_calendar": "calendar",
    "silver_trade_calendar": "calendar",
    "raw_tushare_stock_basic": "stock_basic",
    "silver_stock_basic": "stock_basic",
    "silver_stock_lifecycle": "stock_basic",
    "raw_tushare_namechange": "namechange",
    "silver_namechange": "namechange",
    "silver_stock_identity_map": "identity_map",
    "raw_tushare_suspend_d": "suspend",
    "silver_stock_suspend_daily": "suspend",
    "raw_tushare_stock_daily": "stock_daily",
    "silver_stock_daily": "stock_daily",
    "raw_tushare_adj_factor": "adj_factor",
    "silver_adj_factor": "adj_factor",
    "raw_tushare_index_basic": "index_basic",
    "silver_index_basic": "index_basic",
    "raw_index_daily": "index_daily",
    "silver_index_daily": "index_daily",
    "gold_market_major_indices_daily": "major_indices",
    "gold_market_breadth_daily": "market_breadth",
    "gold_stock_return_distribution": "return_distribution",
    "gold_wealth_market_turnover": "wealth_market_turnover",
    "ch_share_fact_market_breadth_daily": "clickhouse_serving",
    "prod_ch_share_fact_market_breadth_daily": "prod_clickhouse_serving",
    "lake_root_health": "platform_health",
}

_KEEP_PARTITION_SET_BY_NAME = {
    "raw_tushare_suspend_d": _STOCK_TRADE_DAYS,
    "silver_stock_suspend_daily": _STOCK_TRADE_DAYS,
    "raw_tushare_stock_daily": _STOCK_TRADE_DAYS,
    "silver_stock_daily": _STOCK_TRADE_DAYS,
    "raw_tushare_adj_factor": _STOCK_CURRENT_TRADE_DAYS,
    "silver_adj_factor": _STOCK_CURRENT_TRADE_DAYS,
    "raw_index_daily": _INDEX_TRADE_DAYS,
    "silver_index_daily": _INDEX_TRADE_DAYS,
    "gold_market_major_indices_daily": _INDEX_TRADE_DAYS,
    "gold_market_breadth_daily": _STOCK_TRADE_DAYS,
    "gold_stock_return_distribution": _STOCK_TRADE_DAYS,
    "gold_wealth_market_turnover": _STOCK_MINS_SILVER_TRADE_DAYS,
    "ch_share_fact_market_breadth_daily": _STOCK_TRADE_DAYS,
    "prod_ch_share_fact_market_breadth_daily": _STOCK_TRADE_DAYS,
}

_EXCLUDED_ASSET_REASONS_BY_NAME = {
    "prod_ch_share_fact_market_breadth_daily": (
        "known latest check attribution gap; keep out of retention candidates "
        "until a separate recovery plan proves latest state safety"
    ),
    "lake_root_health": (
        "platform health asset, not an ordinary historical quality-check stream"
    ),
}

_RETENTION_ASSET_NAMES = tuple(
    sorted(
        name
        for name in _ASSET_FAMILY_BY_NAME
        if name not in _EXCLUDED_ASSET_REASONS_BY_NAME
    )
)

ASSET_CHECK_RETENTION_ASSET_KEYS = tuple(
    _asset_key(name) for name in _RETENTION_ASSET_NAMES
)
ASSET_CHECK_RETENTION_ASSET_FAMILY_BY_KEY = {
    _asset_key(name): _ASSET_FAMILY_BY_NAME[name] for name in _RETENTION_ASSET_NAMES
}
ASSET_CHECK_RETENTION_KEEP_PARTITION_SET_BY_KEY = {
    _asset_key(name): _KEEP_PARTITION_SET_BY_NAME.get(name)
    for name in _RETENTION_ASSET_NAMES
}
ASSET_CHECK_RETENTION_EXCLUDED_ASSETS = tuple(
    {
        "asset_key": _asset_key(name),
        "asset_name": name,
        "asset_family": _ASSET_FAMILY_BY_NAME[name],
        "reason": reason,
    }
    for name, reason in sorted(_EXCLUDED_ASSET_REASONS_BY_NAME.items())
)


@dataclass(frozen=True)
class AssetCheckEventRetentionDryRunReport:
    keep_trade_day_count: int
    asset_keys: tuple[str, ...]
    protected_check_names: tuple[str, ...]
    keep_windows: tuple[dict[str, object], ...]
    table_counts: tuple[dict[str, object], ...]
    table_sizes: tuple[dict[str, object], ...]
    run_status_counts: tuple[dict[str, object], ...]
    running_or_queued_run_count: int
    candidate_totals: dict[str, object]
    candidate_event_count_by_asset: tuple[dict[str, object], ...]
    candidate_event_count_by_check: tuple[dict[str, object], ...]
    latest_state_summary_by_asset: tuple[dict[str, object], ...]
    protected_check_event_counts: tuple[dict[str, object], ...]
    excluded_asset_samples: tuple[dict[str, object], ...]
    candidate_check_samples: tuple[dict[str, object], ...]
    candidate_materialization_samples: tuple[dict[str, object], ...]
    safety_assertions: tuple[dict[str, object], ...]

    @property
    def should_stop(self) -> bool:
        return any(not bool(row["passed"]) for row in self.safety_assertions)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "asset_check_event_retention_dry_run_only",
            "should_stop": self.should_stop,
            "keep_trade_day_count": self.keep_trade_day_count,
            "asset_keys": list(self.asset_keys),
            "protected_check_names": list(self.protected_check_names),
            "keep_windows": list(self.keep_windows),
            "table_counts": list(self.table_counts),
            "table_sizes": list(self.table_sizes),
            "run_status_counts": list(self.run_status_counts),
            "running_or_queued_run_count": self.running_or_queued_run_count,
            "candidate_totals": self.candidate_totals,
            "candidate_event_count_by_asset": list(
                self.candidate_event_count_by_asset
            ),
            "candidate_event_count_by_check": list(
                self.candidate_event_count_by_check
            ),
            "latest_state_summary_by_asset": list(
                self.latest_state_summary_by_asset
            ),
            "protected_check_event_counts": list(self.protected_check_event_counts),
            "excluded_asset_samples": list(self.excluded_asset_samples),
            "candidate_check_samples": list(self.candidate_check_samples),
            "candidate_materialization_samples": list(
                self.candidate_materialization_samples
            ),
            "safety_assertions": list(self.safety_assertions),
        }


def collect_asset_check_event_retention_dry_run(
    connection,
    *,
    sample_limit: int = 20,
    keep_trade_day_count: int = ASSET_CHECK_RETENTION_KEEP_TRADE_DAY_COUNT,
    asset_keys: Sequence[str] = ASSET_CHECK_RETENTION_ASSET_KEYS,
    protected_check_names: Sequence[str] = (
        ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES
    ),
) -> AssetCheckEventRetentionDryRunReport:
    if sample_limit <= 0:
        raise ValueError("sample_limit must be positive")
    if keep_trade_day_count <= 0:
        raise ValueError("keep_trade_day_count must be positive")
    normalized_asset_keys = _normalize_asset_keys(asset_keys)
    if not normalized_asset_keys:
        raise ValueError("asset_keys must not be empty")
    if not protected_check_names:
        raise ValueError("protected_check_names must not be empty")

    params = _query_params(
        normalized_asset_keys,
        protected_check_names=protected_check_names,
        keep_trade_day_count=keep_trade_day_count,
        sample_limit=sample_limit,
    )

    _set_read_only_session(connection)
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        table_counts = _fetch_all(cursor, _TABLE_COUNTS_SQL)
        table_sizes = _fetch_all(cursor, _TABLE_SIZES_SQL)
        run_status_counts = _fetch_all(cursor, _RUN_STATUS_COUNTS_SQL)
        running_or_queued_run_count = _fetch_scalar(
            cursor,
            _RUNNING_OR_QUEUED_RUN_COUNT_SQL,
        )
        keep_windows = _fetch_all(cursor, _KEEP_WINDOWS_SQL, params)
        candidate_event_count_by_asset = _fetch_all(
            cursor,
            _CANDIDATE_EVENT_COUNT_BY_ASSET_SQL,
            params,
        )
        candidate_event_count_by_check = _fetch_all(
            cursor,
            _CANDIDATE_EVENT_COUNT_BY_CHECK_SQL,
            params,
        )
        latest_state_summary_by_asset = _fetch_all(
            cursor,
            _LATEST_STATE_SUMMARY_BY_ASSET_SQL,
            params,
        )
        protected_check_event_counts = _fetch_all(
            cursor,
            _PROTECTED_CHECK_EVENT_COUNTS_SQL,
            params,
        )
        candidate_check_samples = _fetch_all(
            cursor,
            _CANDIDATE_CHECK_SAMPLES_SQL,
            params,
        )
        candidate_materialization_samples = _fetch_all(
            cursor,
            _CANDIDATE_MATERIALIZATION_SAMPLES_SQL,
            params,
        )
        safety_counts = _fetch_one(cursor, _SAFETY_COUNTS_SQL, params)

    candidate_totals = _candidate_totals(candidate_event_count_by_asset)
    safety_assertions = _build_safety_assertions(
        running_or_queued_run_count=running_or_queued_run_count,
        keep_trade_day_count=keep_trade_day_count,
        keep_windows=keep_windows,
        safety_counts=safety_counts,
    )
    return AssetCheckEventRetentionDryRunReport(
        keep_trade_day_count=keep_trade_day_count,
        asset_keys=normalized_asset_keys,
        protected_check_names=tuple(protected_check_names),
        keep_windows=tuple(keep_windows),
        table_counts=tuple(table_counts),
        table_sizes=tuple(table_sizes),
        run_status_counts=tuple(run_status_counts),
        running_or_queued_run_count=running_or_queued_run_count,
        candidate_totals=candidate_totals,
        candidate_event_count_by_asset=tuple(candidate_event_count_by_asset),
        candidate_event_count_by_check=tuple(candidate_event_count_by_check),
        latest_state_summary_by_asset=tuple(latest_state_summary_by_asset),
        protected_check_event_counts=tuple(protected_check_event_counts),
        excluded_asset_samples=ASSET_CHECK_RETENTION_EXCLUDED_ASSETS,
        candidate_check_samples=tuple(candidate_check_samples),
        candidate_materialization_samples=tuple(candidate_materialization_samples),
        safety_assertions=tuple(safety_assertions),
    )


def _normalize_asset_keys(asset_keys: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for asset_key in asset_keys:
        value = asset_key.strip()
        if not value:
            continue
        if value.startswith("["):
            parsed = json.loads(value)
            if not isinstance(parsed, list) or not all(
                isinstance(part, str) for part in parsed
            ):
                raise ValueError(f"Invalid Dagster asset key JSON: {asset_key}")
            normalized.append(json.dumps(parsed, separators=(",", ":")))
        else:
            normalized.append(_asset_key(value))
    return tuple(dict.fromkeys(normalized))


def _query_params(
    asset_keys: Sequence[str],
    *,
    protected_check_names: Sequence[str],
    keep_trade_day_count: int,
    sample_limit: int,
) -> dict[str, object]:
    unknown = sorted(
        asset_key
        for asset_key in asset_keys
        if asset_key not in ASSET_CHECK_RETENTION_ASSET_FAMILY_BY_KEY
    )
    if unknown:
        raise ValueError(f"Unexpected asset keys for retention dry-run: {unknown}")
    return {
        "asset_keys": list(asset_keys),
        "asset_families": [
            ASSET_CHECK_RETENTION_ASSET_FAMILY_BY_KEY[asset_key]
            for asset_key in asset_keys
        ],
        "keep_partition_set_names": [
            ASSET_CHECK_RETENTION_KEEP_PARTITION_SET_BY_KEY[asset_key]
            for asset_key in asset_keys
        ],
        "protected_check_names": list(protected_check_names),
        "keep_trade_day_count": keep_trade_day_count,
        "sample_limit": sample_limit,
    }


def _set_read_only_session(connection) -> None:
    set_session = getattr(connection, "set_session", None)
    if callable(set_session):
        set_session(readonly=True, autocommit=False)


def _fetch_all(
    cursor,
    sql: str,
    params: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    _assert_select_only_sql(sql)
    cursor.execute(sql, params or {})
    return [_normalize_row(row) for row in cursor.fetchall()]


def _fetch_one(
    cursor,
    sql: str,
    params: Mapping[str, object] | None = None,
) -> dict[str, object]:
    rows = _fetch_all(cursor, sql, params)
    if len(rows) != 1:
        raise RuntimeError(f"Expected one row, got {len(rows)}")
    return rows[0]


def _fetch_scalar(
    cursor,
    sql: str,
    params: Mapping[str, object] | None = None,
) -> int:
    row = _fetch_one(cursor, sql, params)
    value = next(iter(row.values()))
    return int(value or 0)


def _normalize_row(row: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_safe(value) for key, value in dict(row).items()}


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _candidate_totals(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "check_candidate_count": sum(
            _int(row, "check_candidate_count") for row in rows
        ),
        "check_event_candidate_count": sum(
            _int(row, "check_event_candidate_count") for row in rows
        ),
        "check_event_tag_candidate_count": sum(
            _int(row, "check_event_tag_candidate_count") for row in rows
        ),
        "materialization_candidate_count": sum(
            _int(row, "materialization_candidate_count") for row in rows
        ),
        "materialization_event_tag_candidate_count": sum(
            _int(row, "materialization_event_tag_candidate_count") for row in rows
        ),
    }


def _build_safety_assertions(
    *,
    running_or_queued_run_count: int,
    keep_trade_day_count: int,
    keep_windows: Sequence[Mapping[str, object]],
    safety_counts: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    short_keep_windows = [
        row
        for row in keep_windows
        if _int(row, "keep_partition_count") < keep_trade_day_count
    ]
    return (
        _safety_assertion(
            "no_running_or_queued_runs",
            running_or_queued_run_count == 0,
            running_or_queued_run_count,
        ),
        _safety_assertion(
            "all_keep_windows_have_expected_trade_day_count",
            not short_keep_windows,
            len(short_keep_windows),
        ),
        _safety_assertion(
            "candidate_checks_exclude_keep_window_partitions",
            _int(safety_counts, "check_keep_partition_collision_count") == 0,
            _int(safety_counts, "check_keep_partition_collision_count"),
        ),
        _safety_assertion(
            "candidate_materializations_exclude_keep_window_partitions",
            _int(safety_counts, "materialization_keep_partition_collision_count")
            == 0,
            _int(safety_counts, "materialization_keep_partition_collision_count"),
        ),
        _safety_assertion(
            "candidate_checks_exclude_latest_materialization_bound_checks",
            _int(safety_counts, "check_latest_state_collision_count") == 0,
            _int(safety_counts, "check_latest_state_collision_count"),
        ),
        _safety_assertion(
            "candidate_materializations_exclude_latest_materializations",
            _int(safety_counts, "materialization_latest_state_collision_count")
            == 0,
            _int(safety_counts, "materialization_latest_state_collision_count"),
        ),
        _safety_assertion(
            "candidate_checks_exclude_protected_status_checks",
            _int(safety_counts, "protected_check_candidate_count") == 0,
            _int(safety_counts, "protected_check_candidate_count"),
        ),
        _safety_assertion(
            "candidate_checks_have_partition_keys",
            _int(safety_counts, "check_null_partition_candidate_count") == 0,
            _int(safety_counts, "check_null_partition_candidate_count"),
        ),
        _safety_assertion(
            "candidate_materializations_have_partition_keys",
            _int(safety_counts, "materialization_null_partition_candidate_count")
            == 0,
            _int(safety_counts, "materialization_null_partition_candidate_count"),
        ),
        _safety_assertion(
            "candidate_check_events_exist_and_match_check_event_type",
            _int(safety_counts, "check_event_type_mismatch_count") == 0,
            _int(safety_counts, "check_event_type_mismatch_count"),
        ),
    )


def _safety_assertion(name: str, passed: bool, observed_count: int) -> dict[str, object]:
    return {
        "name": name,
        "passed": passed,
        "observed_count": observed_count,
    }


def _int(row: Mapping[str, object], key: str) -> int:
    return int(row.get(key) or 0)


def _assert_select_only_sql(sql: str) -> None:
    upper = " ".join(sql.upper().split())
    forbidden_tokens = (
        " DELETE ",
        " UPDATE ",
        " INSERT ",
        " UPSERT ",
        " MERGE ",
        " DROP ",
        " ALTER ",
        " TRUNCATE ",
        " VACUUM ",
        " ANALYZE ",
        " CREATE ",
        " GRANT ",
        " REVOKE ",
    )
    padded = f" {upper} "
    for token in forbidden_tokens:
        if token in padded:
            raise ValueError(f"Dry-run SQL must be read-only; found {token.strip()}")


_TABLE_COUNTS_SQL = """
-- query: table_counts
SELECT 'event_logs' AS table_name, count(*)::bigint AS row_count FROM event_logs
UNION ALL
SELECT 'asset_check_executions', count(*)::bigint FROM asset_check_executions
UNION ALL
SELECT 'asset_event_tags', count(*)::bigint FROM asset_event_tags
UNION ALL
SELECT 'runs', count(*)::bigint FROM runs
UNION ALL
SELECT 'run_tags', count(*)::bigint FROM run_tags
UNION ALL
SELECT 'dynamic_partitions', count(*)::bigint FROM dynamic_partitions
UNION ALL
SELECT 'instigators', count(*)::bigint FROM instigators
ORDER BY table_name
"""

_TABLE_SIZES_SQL = """
-- query: table_sizes
SELECT
  relname AS table_name,
  pg_total_relation_size(relid)::bigint AS total_bytes,
  pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
WHERE relname IN (
  'event_logs',
  'asset_check_executions',
  'asset_event_tags',
  'runs',
  'run_tags',
  'dynamic_partitions',
  'instigators'
)
ORDER BY pg_total_relation_size(relid) DESC
"""

_RUN_STATUS_COUNTS_SQL = """
-- query: run_status_counts
SELECT status, count(*)::bigint AS run_count
FROM runs
GROUP BY status
ORDER BY status
"""

_RUNNING_OR_QUEUED_RUN_COUNT_SQL = """
-- query: running_or_queued_run_count
SELECT count(*)::bigint AS running_or_queued_run_count
FROM runs
WHERE status IN ('QUEUED', 'STARTING', 'STARTED', 'CANCELING')
"""

_ASSET_SCOPE_CTE = """
asset_scope AS (
  SELECT
    scope.asset_key,
    scope.asset_family,
    scope.keep_partition_set_name
  FROM unnest(
    %(asset_keys)s::text[],
    %(asset_families)s::text[],
    %(keep_partition_set_names)s::text[]
  ) AS scope(asset_key, asset_family, keep_partition_set_name)
)
"""

_KEEP_WINDOWS_CTE = f"""
{_ASSET_SCOPE_CTE},
keep_scope AS (
  SELECT DISTINCT keep_partition_set_name
  FROM asset_scope
  WHERE keep_partition_set_name IS NOT NULL
),
ranked_keep_partitions AS (
  SELECT
    dp.partitions_def_name AS keep_partition_set_name,
    dp.partition,
    row_number() OVER (
      PARTITION BY dp.partitions_def_name
      ORDER BY dp.partition DESC
    ) AS partition_rank
  FROM dynamic_partitions dp
  JOIN keep_scope ks
    ON ks.keep_partition_set_name = dp.partitions_def_name
),
keep_partitions AS (
  SELECT keep_partition_set_name, partition
  FROM ranked_keep_partitions
  WHERE partition_rank <= %(keep_trade_day_count)s
)
"""

_KEEP_WINDOWS_SQL = f"""
-- query: keep_windows
WITH {_KEEP_WINDOWS_CTE}
SELECT
  keep_partition_set_name,
  min(partition) AS keep_start_partition,
  max(partition) AS keep_end_partition,
  count(*)::bigint AS keep_partition_count
FROM keep_partitions
GROUP BY keep_partition_set_name
ORDER BY keep_partition_set_name
"""

_COMMON_CANDIDATE_CTES = f"""
{_KEEP_WINDOWS_CTE},
latest_materializations AS (
  SELECT
    el.asset_key::text AS asset_key,
    max(el.id) AS latest_materialization_id
  FROM event_logs el
  JOIN asset_scope s
    ON s.asset_key = el.asset_key::text
  WHERE el.dagster_event_type = 'ASSET_MATERIALIZATION'
  GROUP BY el.asset_key::text
),
candidate_checks AS (
  SELECT
    ace.id,
    ace.asset_key::text AS asset_key,
    s.asset_family,
    s.keep_partition_set_name,
    ace.check_name,
    ace.partition,
    ace.run_id,
    ace.execution_status,
    ace.evaluation_event_storage_id,
    ace.materialization_event_storage_id,
    ace.evaluation_event_timestamp
  FROM asset_check_executions ace
  JOIN asset_scope s
    ON s.asset_key = ace.asset_key::text
  LEFT JOIN keep_partitions k
    ON k.keep_partition_set_name = s.keep_partition_set_name
   AND k.partition = ace.partition
  LEFT JOIN latest_materializations lm
    ON lm.latest_materialization_id = ace.materialization_event_storage_id
  WHERE s.keep_partition_set_name IS NOT NULL
    AND ace.partition IS NOT NULL
    AND k.partition IS NULL
    AND lm.latest_materialization_id IS NULL
    AND ace.check_name <> ALL(%(protected_check_names)s)
),
candidate_materializations AS (
  SELECT
    el.id,
    el.asset_key::text AS asset_key,
    s.asset_family,
    s.keep_partition_set_name,
    el.partition,
    el.run_id,
    el.timestamp
  FROM event_logs el
  JOIN asset_scope s
    ON s.asset_key = el.asset_key::text
  LEFT JOIN keep_partitions k
    ON k.keep_partition_set_name = s.keep_partition_set_name
   AND k.partition = el.partition
  LEFT JOIN latest_materializations lm
    ON lm.latest_materialization_id = el.id
  WHERE s.keep_partition_set_name IS NOT NULL
    AND el.dagster_event_type = 'ASSET_MATERIALIZATION'
    AND el.partition IS NOT NULL
    AND k.partition IS NULL
    AND lm.latest_materialization_id IS NULL
)
"""

_CANDIDATE_EVENT_COUNT_BY_ASSET_SQL = f"""
-- query: candidate_event_count_by_asset
WITH {_COMMON_CANDIDATE_CTES},
check_counts AS (
  SELECT
    c.asset_key,
    c.asset_family,
    count(*)::bigint AS check_candidate_count,
    count(e.id)::bigint AS check_event_candidate_count,
    count(t.id)::bigint AS check_event_tag_candidate_count
  FROM candidate_checks c
  LEFT JOIN event_logs e
    ON e.id = c.evaluation_event_storage_id
  LEFT JOIN asset_event_tags t
    ON t.event_id = c.evaluation_event_storage_id
  GROUP BY c.asset_key, c.asset_family
),
materialization_counts AS (
  SELECT
    m.asset_key,
    m.asset_family,
    count(*)::bigint AS materialization_candidate_count,
    count(t.id)::bigint AS materialization_event_tag_candidate_count
  FROM candidate_materializations m
  LEFT JOIN asset_event_tags t
    ON t.event_id = m.id
  GROUP BY m.asset_key, m.asset_family
)
SELECT
  s.asset_key,
  s.asset_family,
  COALESCE(c.check_candidate_count, 0)::bigint AS check_candidate_count,
  COALESCE(c.check_event_candidate_count, 0)::bigint
    AS check_event_candidate_count,
  COALESCE(c.check_event_tag_candidate_count, 0)::bigint
    AS check_event_tag_candidate_count,
  COALESCE(m.materialization_candidate_count, 0)::bigint
    AS materialization_candidate_count,
  COALESCE(m.materialization_event_tag_candidate_count, 0)::bigint
    AS materialization_event_tag_candidate_count
FROM asset_scope s
LEFT JOIN check_counts c
  ON c.asset_key = s.asset_key
LEFT JOIN materialization_counts m
  ON m.asset_key = s.asset_key
ORDER BY (
  COALESCE(c.check_candidate_count, 0)
  + COALESCE(m.materialization_candidate_count, 0)
) DESC, s.asset_key
"""

_CANDIDATE_EVENT_COUNT_BY_CHECK_SQL = f"""
-- query: candidate_event_count_by_check
WITH {_COMMON_CANDIDATE_CTES}
SELECT
  c.asset_key,
  c.asset_family,
  c.check_name,
  count(*)::bigint AS check_candidate_count
FROM candidate_checks c
GROUP BY c.asset_key, c.asset_family, c.check_name
ORDER BY check_candidate_count DESC, c.asset_key, c.check_name
"""

_LATEST_STATE_SUMMARY_BY_ASSET_SQL = """
-- query: latest_state_summary_by_asset
WITH
asset_scope AS (
  SELECT
    scope.asset_key,
    scope.asset_family,
    scope.keep_partition_set_name
  FROM unnest(
    %(asset_keys)s::text[],
    %(asset_families)s::text[],
    %(keep_partition_set_names)s::text[]
  ) AS scope(asset_key, asset_family, keep_partition_set_name)
),
latest_materializations AS (
  SELECT DISTINCT ON (el.asset_key::text)
    el.asset_key::text AS asset_key,
    el.id AS latest_materialization_id,
    el.partition AS latest_partition,
    el.run_id AS latest_run_id,
    el.timestamp AS latest_timestamp
  FROM event_logs el
  JOIN asset_scope s
    ON s.asset_key = el.asset_key::text
  WHERE el.dagster_event_type = 'ASSET_MATERIALIZATION'
  ORDER BY el.asset_key::text, el.id DESC
),
latest_checks AS (
  SELECT
    ace.asset_key::text AS asset_key,
    ace.materialization_event_storage_id,
    count(*)::bigint AS latest_check_count,
    count(*) FILTER (WHERE ace.execution_status = 'SUCCEEDED')::bigint
      AS latest_succeeded_check_count,
    count(*) FILTER (WHERE ace.execution_status <> 'SUCCEEDED')::bigint
      AS latest_non_succeeded_check_count
  FROM asset_check_executions ace
  JOIN latest_materializations lm
    ON lm.latest_materialization_id = ace.materialization_event_storage_id
  GROUP BY ace.asset_key::text, ace.materialization_event_storage_id
)
SELECT
  s.asset_key,
  s.asset_family,
  s.keep_partition_set_name,
  lm.latest_materialization_id,
  lm.latest_partition,
  lm.latest_run_id,
  lm.latest_timestamp,
  COALESCE(lc.latest_check_count, 0)::bigint AS latest_check_count,
  COALESCE(lc.latest_succeeded_check_count, 0)::bigint
    AS latest_succeeded_check_count,
  COALESCE(lc.latest_non_succeeded_check_count, 0)::bigint
    AS latest_non_succeeded_check_count
FROM asset_scope s
LEFT JOIN latest_materializations lm
  ON lm.asset_key = s.asset_key
LEFT JOIN latest_checks lc
  ON lc.asset_key = s.asset_key
 AND lc.materialization_event_storage_id = lm.latest_materialization_id
ORDER BY s.asset_key
"""

_PROTECTED_CHECK_EVENT_COUNTS_SQL = """
-- query: protected_check_event_counts
WITH
asset_scope AS (
  SELECT unnest(%(asset_keys)s::text[]) AS asset_key
)
SELECT
  ace.asset_key::text AS asset_key,
  ace.check_name,
  count(*)::bigint AS check_event_count
FROM asset_check_executions ace
JOIN asset_scope s
  ON s.asset_key = ace.asset_key::text
WHERE ace.check_name = ANY(%(protected_check_names)s)
GROUP BY ace.asset_key::text, ace.check_name
ORDER BY check_event_count DESC, ace.asset_key::text, ace.check_name
"""

_CANDIDATE_CHECK_SAMPLES_SQL = f"""
-- query: candidate_check_samples
WITH {_COMMON_CANDIDATE_CTES}
SELECT
  c.asset_key,
  c.asset_family,
  c.check_name,
  c.partition,
  c.run_id,
  c.execution_status,
  c.evaluation_event_storage_id,
  c.materialization_event_storage_id
FROM candidate_checks c
ORDER BY c.evaluation_event_storage_id DESC NULLS LAST, c.asset_key, c.check_name
LIMIT %(sample_limit)s
"""

_CANDIDATE_MATERIALIZATION_SAMPLES_SQL = f"""
-- query: candidate_materialization_samples
WITH {_COMMON_CANDIDATE_CTES}
SELECT
  m.asset_key,
  m.asset_family,
  m.partition,
  m.run_id,
  m.id AS event_storage_id,
  m.timestamp
FROM candidate_materializations m
ORDER BY m.id DESC, m.asset_key
LIMIT %(sample_limit)s
"""

_SAFETY_COUNTS_SQL = f"""
-- query: safety_counts
WITH {_COMMON_CANDIDATE_CTES},
keep_collision_checks AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  JOIN keep_partitions k
    ON k.keep_partition_set_name = c.keep_partition_set_name
   AND k.partition = c.partition
),
keep_collision_materializations AS (
  SELECT count(*)::bigint AS count
  FROM candidate_materializations m
  JOIN keep_partitions k
    ON k.keep_partition_set_name = m.keep_partition_set_name
   AND k.partition = m.partition
),
latest_collision_checks AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  JOIN latest_materializations lm
    ON lm.latest_materialization_id = c.materialization_event_storage_id
),
latest_collision_materializations AS (
  SELECT count(*)::bigint AS count
  FROM candidate_materializations m
  JOIN latest_materializations lm
    ON lm.latest_materialization_id = m.id
),
protected_check_candidates AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  WHERE c.check_name = ANY(%(protected_check_names)s)
),
null_partition_check_candidates AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  WHERE c.partition IS NULL
),
null_partition_materialization_candidates AS (
  SELECT count(*)::bigint AS count
  FROM candidate_materializations m
  WHERE m.partition IS NULL
),
check_event_type_mismatches AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  LEFT JOIN event_logs e
    ON e.id = c.evaluation_event_storage_id
  WHERE e.id IS NULL
     OR e.dagster_event_type <> 'ASSET_CHECK_EVALUATION'
)
SELECT
  (SELECT count FROM keep_collision_checks)
    AS check_keep_partition_collision_count,
  (SELECT count FROM keep_collision_materializations)
    AS materialization_keep_partition_collision_count,
  (SELECT count FROM latest_collision_checks)
    AS check_latest_state_collision_count,
  (SELECT count FROM latest_collision_materializations)
    AS materialization_latest_state_collision_count,
  (SELECT count FROM protected_check_candidates)
    AS protected_check_candidate_count,
  (SELECT count FROM null_partition_check_candidates)
    AS check_null_partition_candidate_count,
  (SELECT count FROM null_partition_materialization_candidates)
    AS materialization_null_partition_candidate_count,
  (SELECT count FROM check_event_type_mismatches)
    AS check_event_type_mismatch_count
"""


def asset_check_event_retention_sql_statements() -> tuple[str, ...]:
    return (
        _TABLE_COUNTS_SQL,
        _TABLE_SIZES_SQL,
        _RUN_STATUS_COUNTS_SQL,
        _RUNNING_OR_QUEUED_RUN_COUNT_SQL,
        _KEEP_WINDOWS_SQL,
        _CANDIDATE_EVENT_COUNT_BY_ASSET_SQL,
        _CANDIDATE_EVENT_COUNT_BY_CHECK_SQL,
        _LATEST_STATE_SUMMARY_BY_ASSET_SQL,
        _PROTECTED_CHECK_EVENT_COUNTS_SQL,
        _CANDIDATE_CHECK_SAMPLES_SQL,
        _CANDIDATE_MATERIALIZATION_SAMPLES_SQL,
        _SAFETY_COUNTS_SQL,
    )
