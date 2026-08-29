\set ON_ERROR_STOP on
\pset pager off

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '180s';
SET LOCAL lock_timeout = '5s';

SELECT
    current_setting('transaction_read_only') AS transaction_read_only,
    current_setting('transaction_isolation') AS transaction_isolation,
    statement_timestamp() AS audit_started_at;

WITH fact_identity AS (
    SELECT
        'raw_tushare.etf_minute_bar'::text AS dataset,
        ts_code,
        MIN(trade_time::date) AS first_fact_date,
        COUNT(*)::bigint AS row_count,
        'ANY'::text AS expected_exchange
    FROM raw_tushare.etf_minute_bar
    GROUP BY ts_code
    UNION ALL
    SELECT
        'raw_tushare.etf_sh_cons',
        ts_code,
        MIN(trade_date),
        COUNT(*)::bigint,
        'SH'
    FROM raw_tushare.etf_sh_cons
    GROUP BY ts_code
    UNION ALL
    SELECT
        'raw_tushare.etf_sz_cons',
        ts_code,
        MIN(trade_date),
        COUNT(*)::bigint,
        'SZ'
    FROM raw_tushare.etf_sz_cons
    GROUP BY ts_code
    UNION ALL
    SELECT
        'core_serving.fund_daily_bar',
        ts_code,
        MIN(trade_date),
        COUNT(*)::bigint,
        'ANY'
    FROM core_serving.fund_daily_bar
    GROUP BY ts_code
), classified AS (
    SELECT
        facts.dataset,
        facts.ts_code,
        facts.first_fact_date,
        facts.row_count,
        facts.expected_exchange,
        basic.list_status,
        basic.list_date,
        basic.exchange,
        CASE
            WHEN facts.ts_code LIKE '%.SH' THEN 'SH'
            WHEN facts.ts_code LIKE '%.SZ' THEN 'SZ'
            ELSE NULL
        END AS suffix_exchange
    FROM fact_identity AS facts
    LEFT JOIN raw_tushare.etf_basic AS basic
        ON basic.ts_code = facts.ts_code
)
SELECT
    dataset,
    'TOTAL'::text AS reason_code,
    COUNT(*)::bigint AS affected_code_count,
    COALESCE(SUM(row_count), 0)::bigint AS affected_row_count
FROM classified
GROUP BY dataset
UNION ALL
SELECT
    dataset,
    'NON_EXCHANGE_ETF_SUFFIX',
    COUNT(*)::bigint,
    COALESCE(SUM(row_count), 0)::bigint
FROM classified
WHERE suffix_exchange IS NULL
GROUP BY dataset
UNION ALL
SELECT
    dataset,
    'CODE_NOT_IN_ETF_MASTER',
    COUNT(*)::bigint,
    COALESCE(SUM(row_count), 0)::bigint
FROM classified
WHERE list_status IS NULL
GROUP BY dataset
UNION ALL
SELECT
    dataset,
    'EXCHANGE_MISMATCH',
    COUNT(*)::bigint,
    COALESCE(SUM(row_count), 0)::bigint
FROM classified
WHERE suffix_exchange IS NOT NULL
  AND (
      exchange IS DISTINCT FROM suffix_exchange
      OR (expected_exchange <> 'ANY' AND expected_exchange <> suffix_exchange)
  )
GROUP BY dataset
UNION ALL
SELECT
    dataset,
    'PENDING_ETF_HAS_FACT',
    COUNT(*)::bigint,
    COALESCE(SUM(row_count), 0)::bigint
FROM classified
WHERE list_status = 'P'
GROUP BY dataset
UNION ALL
SELECT
    dataset,
    'LISTED_WITHOUT_LIST_DATE_HAS_FACT',
    COUNT(*)::bigint,
    COALESCE(SUM(row_count), 0)::bigint
FROM classified
WHERE list_status = 'L' AND list_date IS NULL
GROUP BY dataset
ORDER BY dataset, reason_code;

WITH before_list_date AS (
    SELECT
        'raw_tushare.etf_minute_bar'::text AS dataset,
        bars.ts_code,
        COUNT(*)::bigint AS affected_row_count
    FROM raw_tushare.etf_minute_bar AS bars
    JOIN raw_tushare.etf_basic AS basic ON basic.ts_code = bars.ts_code
    WHERE basic.list_date IS NOT NULL
      AND bars.trade_time < basic.list_date::timestamp
    GROUP BY bars.ts_code
    UNION ALL
    SELECT
        'raw_tushare.etf_sh_cons',
        facts.ts_code,
        COUNT(*)::bigint
    FROM raw_tushare.etf_sh_cons AS facts
    JOIN raw_tushare.etf_basic AS basic ON basic.ts_code = facts.ts_code
    WHERE basic.list_date IS NOT NULL AND facts.trade_date < basic.list_date
    GROUP BY facts.ts_code
    UNION ALL
    SELECT
        'raw_tushare.etf_sz_cons',
        facts.ts_code,
        COUNT(*)::bigint
    FROM raw_tushare.etf_sz_cons AS facts
    JOIN raw_tushare.etf_basic AS basic ON basic.ts_code = facts.ts_code
    WHERE basic.list_date IS NOT NULL AND facts.trade_date < basic.list_date
    GROUP BY facts.ts_code
    UNION ALL
    SELECT
        'core_serving.fund_daily_bar',
        facts.ts_code,
        COUNT(*)::bigint
    FROM core_serving.fund_daily_bar AS facts
    JOIN raw_tushare.etf_basic AS basic ON basic.ts_code = facts.ts_code
    WHERE basic.list_date IS NOT NULL AND facts.trade_date < basic.list_date
    GROUP BY facts.ts_code
)
SELECT
    dataset,
    'BEFORE_CURRENT_LIST_DATE'::text AS reason_code,
    COUNT(*)::bigint AS affected_code_count,
    COALESCE(SUM(affected_row_count), 0)::bigint AS affected_row_count
FROM before_list_date
GROUP BY dataset
ORDER BY dataset;

WITH requestable AS (
    SELECT ts_code
    FROM core_serving.etf_basic
    WHERE list_status = 'L'
      AND list_date IS NOT NULL
      AND list_date <= (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date
      AND (
          (ts_code LIKE '%.SH' AND exchange = 'SH')
          OR (ts_code LIKE '%.SZ' AND exchange = 'SZ')
      )
), monitor_config AS (
    SELECT
        'ops.etf_realtime_monitor_pool'::text AS dataset,
        pool.ts_code
    FROM ops.etf_realtime_monitor_pool AS pool
    UNION ALL
    SELECT
        'ops.etf_realtime_monitor_rule',
        rule.scope_key
    FROM ops.etf_realtime_monitor_rule AS rule
    WHERE rule.scope_type = 'etf'
)
SELECT
    config.dataset,
    'MONITOR_CONFIG_NOT_REQUESTABLE'::text AS reason_code,
    COUNT(*)::bigint AS affected_code_count,
    COALESCE(md5(string_agg(config.ts_code, ',' ORDER BY config.ts_code)), md5('')) AS code_set_checksum
FROM monitor_config AS config
LEFT JOIN requestable ON requestable.ts_code = config.ts_code
WHERE requestable.ts_code IS NULL
GROUP BY config.dataset
ORDER BY config.dataset;

WITH protected_rows AS (
    SELECT 'raw_tushare.fund_daily'::text AS dataset, ts_code
    FROM raw_tushare.fund_daily
    WHERE ts_code LIKE '%.OF'
    UNION ALL
    SELECT 'raw_tushare.fund_adj', ts_code
    FROM raw_tushare.fund_adj
    WHERE ts_code LIKE '%.OF'
    UNION ALL
    SELECT 'core.fund_adj_factor', ts_code
    FROM core.fund_adj_factor
    WHERE ts_code LIKE '%.OF'
    UNION ALL
    SELECT 'raw_tushare.etf_share_size', ts_code
    FROM raw_tushare.etf_share_size
), protected_summary AS (
    SELECT
        dataset,
        COUNT(*)::bigint AS row_count,
        COUNT(DISTINCT ts_code)::bigint AS code_count
    FROM protected_rows
    GROUP BY dataset
), protected_codes AS (
    SELECT
        dataset,
        md5(string_agg(ts_code, ',' ORDER BY ts_code)) AS code_set_checksum
    FROM (
        SELECT DISTINCT dataset, ts_code
        FROM protected_rows
    ) AS identities
    GROUP BY dataset
)
SELECT
    summary.dataset,
    summary.row_count,
    summary.code_count,
    codes.code_set_checksum
FROM protected_summary AS summary
JOIN protected_codes AS codes USING (dataset)
ORDER BY summary.dataset;

SELECT
    'ops.etf_realtime_alert'::text AS dataset,
    COUNT(*)::bigint AS row_count,
    MIN(trade_date) AS first_trade_date,
    MAX(trade_date) AS last_trade_date
FROM ops.etf_realtime_alert
UNION ALL
SELECT
    'ops.etf_realtime_minute_stat',
    COUNT(*)::bigint,
    MIN(trade_date),
    MAX(trade_date)
FROM ops.etf_realtime_minute_stat
ORDER BY dataset;

ROLLBACK;
