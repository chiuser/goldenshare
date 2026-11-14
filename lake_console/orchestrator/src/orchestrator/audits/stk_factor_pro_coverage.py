"""Historical stock technical factor coverage against actual ordinary daily bars."""

from orchestrator.defs.checks.stk_factor_pro import relation_identifier

STK_FACTOR_PRO_HISTORICAL_COVERAGE_RULE_VERSION = "stock_daily.v1"

_PREFIX = "stk_factor_pro_missing_audit_"
_TABLES = tuple(
    _PREFIX + suffix
    for suffix in (
        "quote_sources",
        "code_map",
        "expected",
        "present",
        "matched",
        "missing",
        "daily",
        "reused",
        "needs_check",
        "reuse_counts",
    )
)


def prepare_stk_factor_pro_missing_coverage(
    connection,
    *,
    dates_relation,
    quote_relation,
    lifecycle_relation,
    identity_relation,
    actual_relation,
):
    """Compare held monthly DATE/code inputs; confirmed IPO first days are optional.

    Ordinary daily bars define required stocks. Missing lifecycle rows do not
    discard those bars. Producers own schemas and identity uniqueness. This
    helper does no file/runtime I/O and does not change daily source admission.
    """
    dates, quotes, lifecycle, identity = (
        relation_identifier(name)
        for name in (
            dates_relation,
            quote_relation,
            lifecycle_relation,
            identity_relation,
        )
    )
    quote_sources, code_map, expected = _TABLES[:3]
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {quote_sources} AS "
        "SELECT DISTINCT q.trade_date,q.ts_code source_ts_code,"
        "coalesce(i.latest_ts_code,q.ts_code) ts_code "
        f"FROM {quotes} q JOIN {dates} d USING(trade_date) "
        f"LEFT JOIN {lifecycle} l ON l.ts_code=q.ts_code "
        f"LEFT JOIN {identity} i ON i.source_ts_code=q.ts_code "
        "AND i.valid_from<=q.trade_date "
        "AND (i.valid_to IS NULL OR q.trade_date<i.valid_to) "
        "WHERE l.list_date IS NULL OR l.list_date<>q.trade_date"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {expected} AS "
        f"SELECT DISTINCT trade_date,ts_code FROM {quote_sources}"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {code_map} AS "
        f"SELECT trade_date,ts_code source_ts_code,ts_code FROM {expected} UNION "
        f"SELECT trade_date,source_ts_code,ts_code FROM {quote_sources} UNION "
        f"SELECT l.trade_date,i.source_ts_code,l.ts_code FROM {expected} l "
        f"JOIN {identity} i ON i.latest_ts_code=l.ts_code "
        "AND i.valid_from<=l.trade_date "
        "AND (i.valid_to IS NULL OR l.trade_date<i.valid_to)"
    )
    return compare_stk_factor_pro_missing_coverage(
        connection, dates_relation=dates_relation, actual_relation=actual_relation
    )


def compare_stk_factor_pro_missing_coverage(
    connection, *, dates_relation, actual_relation
):
    """Reuse prepared ordinary daily codes; compare without rebuilding inputs."""
    dates, actual = (
        relation_identifier(name) for name in (dates_relation, actual_relation)
    )
    _, code_map, expected, present, matched, missing, daily, *_ = _TABLES
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {present} AS "
        f"SELECT DISTINCT m.trade_date,m.ts_code FROM {actual} a JOIN {code_map} m "
        "ON a.trade_date=m.trade_date AND a.ts_code=m.source_ts_code"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {matched} AS "
        f"SELECT * FROM {expected} INTERSECT SELECT * FROM {present}"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {missing} AS "
        f"SELECT * FROM {expected} EXCEPT SELECT * FROM {present}"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {daily} AS "
        "SELECT d.trade_date,coalesce(e.n,0) expected_count,"
        "coalesce(m.n,0) matched_count,coalesce(x.n,0) missing_count "
        f"FROM {dates} d LEFT JOIN "
        f"(SELECT trade_date,count(*) n FROM {expected} GROUP BY trade_date) e USING(trade_date) "
        f"LEFT JOIN (SELECT trade_date,count(*) n FROM {matched} GROUP BY trade_date) m USING(trade_date) "
        f"LEFT JOIN (SELECT trade_date,count(*) n FROM {missing} GROUP BY trade_date) x USING(trade_date)"
    )
    return {
        "daily_relation": daily,
        "expected_relation": expected,
        "matched_relation": matched,
        "missing_relation": missing,
        "code_map_relation": code_map,
    }


def reuse_stk_factor_pro_missing_coverage(
    connection, *, dates_relation, previous_expected_relation, previous_missing_relation
):
    """Reuse verified E-F=M; only Q-E needs a new technical factor lookup."""
    dates, previous_expected, previous_missing = (
        relation_identifier(name)
        for name in (
            dates_relation,
            previous_expected_relation,
            previous_missing_relation,
        )
    )
    expected, reused, needs_check, counts = (_TABLES[index] for index in (2, 7, 8, 9))
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {reused} AS "
        f"(SELECT * FROM {expected} INTERSECT SELECT * FROM {previous_expected}) "
        f"EXCEPT SELECT * FROM {previous_missing}"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {needs_check} AS "
        f"SELECT * FROM {expected} EXCEPT SELECT * FROM {previous_expected}"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {counts} AS "
        "SELECT d.trade_date,coalesce(r.n,0) reused_matched_count,"
        "coalesce(c.n,0) needs_check_count "
        f"FROM {dates} d LEFT JOIN "
        f"(SELECT trade_date,count(*) n FROM {reused} GROUP BY trade_date) r USING(trade_date) "
        f"LEFT JOIN (SELECT trade_date,count(*) n FROM {needs_check} GROUP BY trade_date) c USING(trade_date)"
    )
    return {
        "reused_relation": reused,
        "needs_check_relation": needs_check,
        "counts_relation": counts,
    }


def release_stk_factor_pro_missing_coverage(connection):
    for table in reversed(_TABLES):
        connection.execute(f"DROP TABLE IF EXISTS {table}")
