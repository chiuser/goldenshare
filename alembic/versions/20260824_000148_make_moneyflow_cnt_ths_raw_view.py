"""make concept moneyflow ths a protected raw-backed serving view

Revision ID: 20260824_000148
Revises: 20260824_000147
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op


revision = "20260824_000148"
down_revision = "20260824_000147"
branch_labels = None
depends_on = None


_SET_BOUNDED_SESSION_LIMITS = (
    "SET LOCAL lock_timeout = '15s'",
    "SET LOCAL statement_timeout = '120s'",
    "SET LOCAL work_mem = '16MB'",
)


_PREFLIGHT_RELATIONS = """
DO $migration$
DECLARE
    raw_oid oid;
    serving_oid oid;
    raw_kind "char";
    serving_kind "char";
    raw_owner text;
    serving_owner text;
    raw_tablespace text;
    raw_is_partition boolean;
    serving_is_partition boolean;
BEGIN
    SELECT c.oid, c.relkind, owner_role.rolname, c.relispartition,
           COALESCE(object_ts.spcname, database_ts.spcname)
    INTO raw_oid, raw_kind, raw_owner, raw_is_partition, raw_tablespace
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_catalog.pg_roles owner_role ON owner_role.oid = c.relowner
    JOIN pg_catalog.pg_database current_db ON current_db.datname = current_database()
    JOIN pg_catalog.pg_tablespace database_ts ON database_ts.oid = current_db.dattablespace
    LEFT JOIN pg_catalog.pg_tablespace object_ts ON object_ts.oid = NULLIF(c.reltablespace, 0)
    WHERE n.nspname = 'raw_tushare'
      AND c.relname = 'moneyflow_cnt_ths';

    SELECT c.oid, c.relkind, owner_role.rolname, c.relispartition
    INTO serving_oid, serving_kind, serving_owner, serving_is_partition
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_catalog.pg_roles owner_role ON owner_role.oid = c.relowner
    WHERE n.nspname = 'core_serving'
      AND c.relname = 'concept_moneyflow_ths';

    IF raw_kind IS DISTINCT FROM 'r' THEN
        RAISE EXCEPTION
            'Expected raw_tushare.moneyflow_cnt_ths to be a physical table, found relation kind %',
            raw_kind;
    END IF;
    IF serving_kind IS DISTINCT FROM 'r' THEN
        RAISE EXCEPTION
            'Expected core_serving.concept_moneyflow_ths to be a physical table, found relation kind %',
            serving_kind;
    END IF;
    IF raw_is_partition OR serving_is_partition OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_inherits inheritance_row
        WHERE inheritance_row.inhrelid IN (raw_oid, serving_oid)
           OR inheritance_row.inhparent IN (raw_oid, serving_oid)
    ) THEN
        RAISE EXCEPTION 'Raw/serving inheritance or partition contract is not supported';
    END IF;
    IF raw_owner IS DISTINCT FROM current_user OR serving_owner IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION
            'Migration role must own both relations: current_user=%, raw_owner=%, serving_owner=%',
            current_user, raw_owner, serving_owner;
    END IF;
    IF raw_tablespace IS DISTINCT FROM 'pg_default' THEN
        RAISE EXCEPTION
            'raw_tushare.moneyflow_cnt_ths must remain on SSD pg_default, found %',
            raw_tablespace;
    END IF;
END
$migration$;
"""


_LOCK_SOURCE_RELATIONS = (
    "LOCK TABLE raw_tushare.moneyflow_cnt_ths IN SHARE MODE",
    "LOCK TABLE core_serving.concept_moneyflow_ths IN SHARE MODE",
)


_PREFLIGHT_CONTRACT = """
DO $migration$
DECLARE
    raw_oid oid := 'raw_tushare.moneyflow_cnt_ths'::regclass;
    serving_oid oid := 'core_serving.concept_moneyflow_ths'::regclass;
    raw_signature text[];
    serving_signature text[];
    raw_primary_key text[];
    serving_primary_key text[];
    raw_trade_date_index_columns text[];
    raw_trade_date_index_tablespace text;
    raw_entity_index_columns text[];
    raw_entity_index_tablespace text;
    serving_trade_date_index_columns text[];
    serving_entity_index_columns text[];
BEGIN
    SELECT pg_catalog.array_agg(
        a.attname || '|' || pg_catalog.format_type(a.atttypid, a.atttypmod) || '|' ||
        CASE WHEN a.attnotnull THEN 'NOT NULL' ELSE 'NULL' END
        ORDER BY a.attnum
    )
    INTO raw_signature
    FROM pg_catalog.pg_attribute a
    WHERE a.attrelid = raw_oid
      AND a.attnum > 0
      AND NOT a.attisdropped;

    IF raw_signature IS DISTINCT FROM ARRAY[
        'trade_date|date|NOT NULL',
        'ts_code|character varying(16)|NOT NULL',
        'name|character varying(128)|NULL',
        'lead_stock|character varying(128)|NULL',
        'close_price|numeric(18,4)|NULL',
        'pct_change|numeric(10,4)|NULL',
        'industry_index|numeric(24,4)|NULL',
        'company_num|integer|NULL',
        'pct_change_stock|numeric(10,4)|NULL',
        'net_buy_amount|numeric(24,4)|NULL',
        'net_sell_amount|numeric(24,4)|NULL',
        'net_amount|numeric(24,4)|NULL',
        'api_name|character varying(32)|NOT NULL',
        'fetched_at|timestamp with time zone|NOT NULL',
        'raw_payload|text|NULL'
    ]::text[] THEN
        RAISE EXCEPTION 'Unexpected raw_tushare.moneyflow_cnt_ths column contract: %', raw_signature;
    END IF;

    SELECT pg_catalog.array_agg(
        a.attname || '|' || pg_catalog.format_type(a.atttypid, a.atttypmod) || '|' ||
        CASE WHEN a.attnotnull THEN 'NOT NULL' ELSE 'NULL' END
        ORDER BY a.attnum
    )
    INTO serving_signature
    FROM pg_catalog.pg_attribute a
    WHERE a.attrelid = serving_oid
      AND a.attnum > 0
      AND NOT a.attisdropped;

    IF serving_signature IS DISTINCT FROM ARRAY[
        'trade_date|date|NOT NULL',
        'ts_code|character varying(16)|NOT NULL',
        'name|character varying(128)|NULL',
        'lead_stock|character varying(128)|NULL',
        'close_price|numeric(18,4)|NULL',
        'pct_change|numeric(10,4)|NULL',
        'industry_index|numeric(24,4)|NULL',
        'company_num|integer|NULL',
        'pct_change_stock|numeric(10,4)|NULL',
        'net_buy_amount|numeric(24,4)|NULL',
        'net_sell_amount|numeric(24,4)|NULL',
        'net_amount|numeric(24,4)|NULL',
        'created_at|timestamp with time zone|NOT NULL',
        'updated_at|timestamp with time zone|NOT NULL'
    ]::text[] THEN
        RAISE EXCEPTION 'Unexpected core_serving.concept_moneyflow_ths column contract: %', serving_signature;
    END IF;

    SELECT pg_catalog.array_agg(a.attname ORDER BY key_column.ordinality)
    INTO raw_primary_key
    FROM pg_catalog.pg_constraint constraint_row
    CROSS JOIN LATERAL pg_catalog.unnest(constraint_row.conkey)
        WITH ORDINALITY AS key_column(attnum, ordinality)
    JOIN pg_catalog.pg_attribute a
      ON a.attrelid = constraint_row.conrelid
     AND a.attnum = key_column.attnum
    WHERE constraint_row.conrelid = raw_oid
      AND constraint_row.contype = 'p';

    SELECT pg_catalog.array_agg(a.attname ORDER BY key_column.ordinality)
    INTO serving_primary_key
    FROM pg_catalog.pg_constraint constraint_row
    CROSS JOIN LATERAL pg_catalog.unnest(constraint_row.conkey)
        WITH ORDINALITY AS key_column(attnum, ordinality)
    JOIN pg_catalog.pg_attribute a
      ON a.attrelid = constraint_row.conrelid
     AND a.attnum = key_column.attnum
    WHERE constraint_row.conrelid = serving_oid
      AND constraint_row.contype = 'p';

    IF raw_primary_key IS DISTINCT FROM ARRAY['trade_date', 'ts_code']::text[] THEN
        RAISE EXCEPTION 'Unexpected raw primary key: %', raw_primary_key;
    END IF;
    IF serving_primary_key IS DISTINCT FROM ARRAY['trade_date', 'ts_code']::text[] THEN
        RAISE EXCEPTION 'Unexpected serving primary key: %', serving_primary_key;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_row
        WHERE constraint_row.conrelid = serving_oid
          -- PostgreSQL 18 records NOT NULL constraints as contype = 'n'.
          -- The exact nullable contract is already verified above through
          -- pg_attribute.attnotnull, so only semantic constraints beyond the
          -- primary key and those catalog-backed NOT NULL rows are forbidden.
          AND constraint_row.contype NOT IN ('p', 'n')
    ) THEN
        RAISE EXCEPTION 'Unexpected non-primary-key constraint on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_row
        JOIN pg_catalog.pg_index index_row ON index_row.indexrelid = constraint_row.conindid
        WHERE constraint_row.conrelid IN (raw_oid, serving_oid)
          AND constraint_row.contype = 'p'
          AND (NOT index_row.indisvalid OR NOT index_row.indisready)
    ) THEN
        RAISE EXCEPTION 'Raw or serving primary-key index is invalid or not ready';
    END IF;

    SELECT pg_catalog.array_agg(a.attname ORDER BY key_column.ordinality),
           COALESCE(object_ts.spcname, database_ts.spcname)
    INTO raw_trade_date_index_columns, raw_trade_date_index_tablespace
    FROM pg_catalog.pg_index index_row
    JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_row.indexrelid
    JOIN pg_catalog.pg_database current_db ON current_db.datname = current_database()
    JOIN pg_catalog.pg_tablespace database_ts ON database_ts.oid = current_db.dattablespace
    LEFT JOIN pg_catalog.pg_tablespace object_ts ON object_ts.oid = NULLIF(index_relation.reltablespace, 0)
    CROSS JOIN LATERAL pg_catalog.unnest(index_row.indkey)
        WITH ORDINALITY AS key_column(attnum, ordinality)
    JOIN pg_catalog.pg_attribute a
      ON a.attrelid = index_row.indrelid
     AND a.attnum = key_column.attnum
    WHERE index_row.indrelid = raw_oid
      AND index_relation.relname = 'idx_raw_tushare_moneyflow_cnt_ths_trade_date'
      AND index_row.indisvalid
      AND index_row.indisready
      AND index_row.indpred IS NULL
    GROUP BY object_ts.spcname, database_ts.spcname;

    IF raw_trade_date_index_columns IS DISTINCT FROM ARRAY['trade_date']::text[] THEN
        RAISE EXCEPTION 'Required raw trade-date index is missing or invalid: %', raw_trade_date_index_columns;
    END IF;
    IF raw_trade_date_index_tablespace IS DISTINCT FROM 'pg_default' THEN
        RAISE EXCEPTION 'Required raw trade-date index must remain on SSD pg_default, found %', raw_trade_date_index_tablespace;
    END IF;

    SELECT pg_catalog.array_agg(a.attname ORDER BY key_column.ordinality),
           COALESCE(object_ts.spcname, database_ts.spcname)
    INTO raw_entity_index_columns, raw_entity_index_tablespace
    FROM pg_catalog.pg_index index_row
    JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_row.indexrelid
    JOIN pg_catalog.pg_database current_db ON current_db.datname = current_database()
    JOIN pg_catalog.pg_tablespace database_ts ON database_ts.oid = current_db.dattablespace
    LEFT JOIN pg_catalog.pg_tablespace object_ts ON object_ts.oid = NULLIF(index_relation.reltablespace, 0)
    CROSS JOIN LATERAL pg_catalog.unnest(index_row.indkey)
        WITH ORDINALITY AS key_column(attnum, ordinality)
    JOIN pg_catalog.pg_attribute a
      ON a.attrelid = index_row.indrelid
     AND a.attnum = key_column.attnum
    WHERE index_row.indrelid = raw_oid
      AND index_relation.relname = 'idx_raw_tushare_moneyflow_cnt_ths_ts_code_trade_date'
      AND index_row.indisvalid
      AND index_row.indisready
      AND index_row.indpred IS NULL
    GROUP BY object_ts.spcname, database_ts.spcname;

    IF raw_entity_index_columns IS DISTINCT FROM ARRAY['ts_code', 'trade_date']::text[] THEN
        RAISE EXCEPTION 'Required raw entity-date index is missing or invalid: %', raw_entity_index_columns;
    END IF;
    IF raw_entity_index_tablespace IS DISTINCT FROM 'pg_default' THEN
        RAISE EXCEPTION 'Required raw entity-date index must remain on SSD pg_default, found %', raw_entity_index_tablespace;
    END IF;

    SELECT pg_catalog.array_agg(a.attname ORDER BY key_column.ordinality)
    INTO serving_trade_date_index_columns
    FROM pg_catalog.pg_index index_row
    JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_row.indexrelid
    CROSS JOIN LATERAL pg_catalog.unnest(index_row.indkey)
        WITH ORDINALITY AS key_column(attnum, ordinality)
    JOIN pg_catalog.pg_attribute a
      ON a.attrelid = index_row.indrelid
     AND a.attnum = key_column.attnum
    WHERE index_row.indrelid = serving_oid
      AND index_relation.relname = 'idx_concept_moneyflow_ths_trade_date'
      AND index_row.indisvalid
      AND index_row.indisready
      AND index_row.indpred IS NULL;

    IF serving_trade_date_index_columns IS DISTINCT FROM ARRAY['trade_date']::text[] THEN
        RAISE EXCEPTION 'Unexpected serving trade-date index contract: %', serving_trade_date_index_columns;
    END IF;

    SELECT pg_catalog.array_agg(a.attname ORDER BY key_column.ordinality)
    INTO serving_entity_index_columns
    FROM pg_catalog.pg_index index_row
    JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_row.indexrelid
    CROSS JOIN LATERAL pg_catalog.unnest(index_row.indkey)
        WITH ORDINALITY AS key_column(attnum, ordinality)
    JOIN pg_catalog.pg_attribute a
      ON a.attrelid = index_row.indrelid
     AND a.attnum = key_column.attnum
    WHERE index_row.indrelid = serving_oid
      AND index_relation.relname = 'idx_concept_moneyflow_ths_ts_code_trade_date'
      AND index_row.indisvalid
      AND index_row.indisready
      AND index_row.indpred IS NULL;

    IF serving_entity_index_columns IS DISTINCT FROM ARRAY['ts_code', 'trade_date']::text[] THEN
        RAISE EXCEPTION 'Unexpected serving entity-date index contract: %', serving_entity_index_columns;
    END IF;
    IF (
        SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_index index_row
        WHERE index_row.indrelid = serving_oid
          AND NOT index_row.indisprimary
    ) <> 2 THEN
        RAISE EXCEPTION 'Unexpected secondary-index count on core_serving.concept_moneyflow_ths';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_row
        WHERE constraint_row.contype = 'f'
          AND (constraint_row.conrelid = serving_oid OR constraint_row.confrelid = serving_oid)
    ) THEN
        RAISE EXCEPTION 'Unexpected foreign-key dependency on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_trigger trigger_row
        WHERE trigger_row.tgrelid = serving_oid
          AND NOT trigger_row.tgisinternal
    ) THEN
        RAISE EXCEPTION 'Unexpected user trigger on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute attribute_row
        WHERE attribute_row.attrelid = serving_oid
          AND attribute_row.attnum > 0
          AND NOT attribute_row.attisdropped
          AND attribute_row.attacl IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Unexpected column-level ACL on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class relation_row
        WHERE relation_row.oid = serving_oid
          AND (relation_row.relrowsecurity OR relation_row.relforcerowsecurity)
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy policy_row
        WHERE policy_row.polrelid = serving_oid
    ) THEN
        RAISE EXCEPTION 'Unexpected RLS contract on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_depend dependency_row
        JOIN pg_catalog.pg_rewrite rewrite_row
          ON dependency_row.classid = 'pg_rewrite'::regclass
         AND dependency_row.objid = rewrite_row.oid
        JOIN pg_catalog.pg_class dependent_relation
          ON dependent_relation.oid = rewrite_row.ev_class
        WHERE dependency_row.refclassid = 'pg_class'::regclass
          AND dependency_row.refobjid = serving_oid
          AND dependent_relation.oid <> serving_oid
          AND dependent_relation.relkind IN ('v', 'm')
    ) THEN
        RAISE EXCEPTION 'Unexpected view dependency on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_depend dependency_row
        JOIN pg_catalog.pg_proc function_row
          ON dependency_row.classid = 'pg_proc'::regclass
         AND dependency_row.objid = function_row.oid
        WHERE dependency_row.refclassid = 'pg_class'::regclass
          AND dependency_row.refobjid = serving_oid
    ) THEN
        RAISE EXCEPTION 'Unexpected function dependency on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_rewrite rewrite_row
        WHERE rewrite_row.ev_class = serving_oid
    ) THEN
        RAISE EXCEPTION 'Unexpected rewrite rule on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_statistic_ext statistics_row
        WHERE statistics_row.stxrelid = serving_oid
    ) THEN
        RAISE EXCEPTION 'Unexpected extended statistics on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_seclabel label_row
        WHERE label_row.classoid = 'pg_class'::regclass
          AND label_row.objoid = serving_oid
    ) THEN
        RAISE EXCEPTION 'Unexpected security label on core_serving.concept_moneyflow_ths';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_publication_rel publication_row
        WHERE publication_row.prrelid = serving_oid
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_publication_namespace publication_namespace_row
        JOIN pg_catalog.pg_class relation_row
          ON relation_row.relnamespace = publication_namespace_row.pnnspid
        WHERE relation_row.oid = serving_oid
    ) THEN
        RAISE EXCEPTION 'Unexpected logical-publication contract on core_serving.concept_moneyflow_ths';
    END IF;
END
$migration$;
"""


_VERIFY_DATA_EQUIVALENCE = """
DO $migration$
DECLARE
    raw_count bigint;
    serving_count bigint;
    raw_min_date date;
    raw_max_date date;
    serving_min_date date;
    serving_max_date date;
    window_start date;
    window_end date;
    raw_window_count bigint;
    serving_window_count bigint;
    raw_window_identity_count bigint;
    serving_window_identity_count bigint;
    raw_only_count bigint;
    serving_only_count bigint;
    max_rows_per_month constant bigint := 20000;
BEGIN
    SELECT pg_catalog.count(*), min(trade_date), max(trade_date)
    INTO raw_count, raw_min_date, raw_max_date
    FROM raw_tushare.moneyflow_cnt_ths;

    SELECT pg_catalog.count(*), min(trade_date), max(trade_date)
    INTO serving_count, serving_min_date, serving_max_date
    FROM core_serving.concept_moneyflow_ths;

    IF raw_count IS DISTINCT FROM serving_count
       OR raw_min_date IS DISTINCT FROM serving_min_date
       OR raw_max_date IS DISTINCT FROM serving_max_date THEN
        RAISE EXCEPTION
            'moneyflow_cnt_ths raw/serving range mismatch: raw_count=%, serving_count=%, raw_range=%..%, serving_range=%..%',
            raw_count, serving_count, raw_min_date, raw_max_date, serving_min_date, serving_max_date;
    END IF;

    IF raw_count = 0 THEN
        RETURN;
    END IF;

    window_start := pg_catalog.date_trunc('month', raw_min_date)::date;
    WHILE window_start <= raw_max_date LOOP
        window_end := (window_start + interval '1 month')::date;

        SELECT pg_catalog.count(*), pg_catalog.count(DISTINCT (trade_date, ts_code))
        INTO raw_window_count, raw_window_identity_count
        FROM raw_tushare.moneyflow_cnt_ths
        WHERE trade_date >= window_start
          AND trade_date < window_end;

        SELECT pg_catalog.count(*), pg_catalog.count(DISTINCT (trade_date, ts_code))
        INTO serving_window_count, serving_window_identity_count
        FROM core_serving.concept_moneyflow_ths
        WHERE trade_date >= window_start
          AND trade_date < window_end;

        IF raw_window_count > max_rows_per_month OR serving_window_count > max_rows_per_month THEN
            RAISE EXCEPTION
                'moneyflow_cnt_ths monthly reconciliation exceeds safety cap: window=%..%, raw=%, serving=%, cap=%',
                window_start, window_end, raw_window_count, serving_window_count, max_rows_per_month;
        END IF;

        WITH raw_only AS (
            SELECT trade_date, ts_code, name, lead_stock, close_price, pct_change,
                   industry_index, company_num, pct_change_stock, net_buy_amount,
                   net_sell_amount, net_amount
            FROM raw_tushare.moneyflow_cnt_ths
            WHERE trade_date >= window_start
              AND trade_date < window_end
            EXCEPT ALL
            SELECT trade_date, ts_code, name, lead_stock, close_price, pct_change,
                   industry_index, company_num, pct_change_stock, net_buy_amount,
                   net_sell_amount, net_amount
            FROM core_serving.concept_moneyflow_ths
            WHERE trade_date >= window_start
              AND trade_date < window_end
        )
        SELECT pg_catalog.count(*) INTO raw_only_count FROM raw_only;

        WITH serving_only AS (
            SELECT trade_date, ts_code, name, lead_stock, close_price, pct_change,
                   industry_index, company_num, pct_change_stock, net_buy_amount,
                   net_sell_amount, net_amount
            FROM core_serving.concept_moneyflow_ths
            WHERE trade_date >= window_start
              AND trade_date < window_end
            EXCEPT ALL
            SELECT trade_date, ts_code, name, lead_stock, close_price, pct_change,
                   industry_index, company_num, pct_change_stock, net_buy_amount,
                   net_sell_amount, net_amount
            FROM raw_tushare.moneyflow_cnt_ths
            WHERE trade_date >= window_start
              AND trade_date < window_end
        )
        SELECT pg_catalog.count(*) INTO serving_only_count FROM serving_only;

        IF raw_window_count IS DISTINCT FROM serving_window_count
           OR raw_window_identity_count IS DISTINCT FROM raw_window_count
           OR serving_window_identity_count IS DISTINCT FROM serving_window_count
           OR raw_only_count <> 0
           OR serving_only_count <> 0 THEN
            RAISE EXCEPTION
                'moneyflow_cnt_ths monthly mismatch: window=%..%, raw_count=%, serving_count=%, raw_identity_count=%, serving_identity_count=%, raw_only=%, serving_only=%',
                window_start, window_end, raw_window_count, serving_window_count,
                raw_window_identity_count, serving_window_identity_count,
                raw_only_count, serving_only_count;
        END IF;

        window_start := window_end;
    END LOOP;
END
$migration$;
"""


_VERIFY_EXISTING_REJECT_FUNCTION = """
DO $migration$
DECLARE
    reject_function_oid oid;
BEGIN
    SELECT function_row.oid
    INTO reject_function_oid
    FROM pg_catalog.pg_proc function_row
    JOIN pg_catalog.pg_namespace namespace_row ON namespace_row.oid = function_row.pronamespace
    JOIN pg_catalog.pg_roles owner_role ON owner_role.oid = function_row.proowner
    JOIN pg_catalog.pg_language language_row ON language_row.oid = function_row.prolang
    WHERE namespace_row.nspname = 'core_serving'
      AND function_row.proname = 'reject_raw_direct_serving_view_dml'
      AND function_row.pronargs = 0
      AND owner_role.rolname = current_user
      AND language_row.lanname = 'plpgsql'
      AND NOT function_row.prosecdef
      AND function_row.prorettype = 'trigger'::regtype
      AND function_row.proconfig = ARRAY['search_path=pg_catalog']::text[];

    IF reject_function_oid IS NULL THEN
        RAISE EXCEPTION 'Required DML rejection function contract is missing or invalid';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.aclexplode(
            COALESCE(
                (SELECT function_row.proacl FROM pg_catalog.pg_proc function_row WHERE function_row.oid = reject_function_oid),
                pg_catalog.acldefault('f', current_user::regrole)
            )
        ) acl_row
        WHERE acl_row.grantee = 0
    ) THEN
        RAISE EXCEPTION 'DML rejection function must not grant EXECUTE to PUBLIC';
    END IF;
END
$migration$;
"""


_LOCK_SERVING_FOR_SWITCH = """
LOCK TABLE core_serving.concept_moneyflow_ths IN ACCESS EXCLUSIVE MODE;
"""


_SWITCH_RELATION = """
DO $migration$
DECLARE
    serving_oid oid := 'core_serving.concept_moneyflow_ths'::regclass;
    serving_owner text;
    relation_comment text;
    column_comments jsonb;
    select_grants jsonb;
    grant_entry jsonb;
    comment_entry record;
    grantee_name text;
    grant_sql text;
    restored_relation_comment text;
    restored_column_comments jsonb;
    restored_select_grants jsonb;
BEGIN
    SELECT owner_role.rolname, pg_catalog.obj_description(relation_row.oid, 'pg_class')
    INTO serving_owner, relation_comment
    FROM pg_catalog.pg_class relation_row
    JOIN pg_catalog.pg_roles owner_role ON owner_role.oid = relation_row.relowner
    WHERE relation_row.oid = serving_oid;

    SELECT COALESCE(
        pg_catalog.jsonb_object_agg(
            attribute_row.attname,
            pg_catalog.col_description(attribute_row.attrelid, attribute_row.attnum)
        ) FILTER (
            WHERE pg_catalog.col_description(attribute_row.attrelid, attribute_row.attnum) IS NOT NULL
        ),
        '{}'::jsonb
    )
    INTO column_comments
    FROM pg_catalog.pg_attribute attribute_row
    WHERE attribute_row.attrelid = serving_oid
      AND attribute_row.attnum > 0
      AND NOT attribute_row.attisdropped;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class relation_row
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(relation_row.relacl, pg_catalog.acldefault('r', relation_row.relowner))
        ) acl_row
        WHERE relation_row.oid = serving_oid
          AND acl_row.grantee <> relation_row.relowner
          AND acl_row.privilege_type <> 'SELECT'
    ) THEN
        RAISE EXCEPTION 'Unexpected non-owner DML grant on core_serving.concept_moneyflow_ths';
    END IF;

    SELECT COALESCE(
        pg_catalog.jsonb_agg(
            pg_catalog.jsonb_build_object(
                'grantee', CASE
                    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
                    ELSE grantee_role.rolname
                END,
                'is_grantable', acl_row.is_grantable
            )
            ORDER BY acl_row.grantee
        ) FILTER (
            WHERE acl_row.grantee <> relation_row.relowner
              AND acl_row.privilege_type = 'SELECT'
        ),
        '[]'::jsonb
    )
    INTO select_grants
    FROM pg_catalog.pg_class relation_row
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(relation_row.relacl, pg_catalog.acldefault('r', relation_row.relowner))
    ) acl_row
    LEFT JOIN pg_catalog.pg_roles grantee_role ON grantee_role.oid = acl_row.grantee
    WHERE relation_row.oid = serving_oid;

    EXECUTE 'DROP TABLE core_serving.concept_moneyflow_ths';
    EXECUTE $view$
        CREATE VIEW core_serving.concept_moneyflow_ths AS
        SELECT
            trade_date,
            ts_code,
            name,
            lead_stock,
            close_price,
            pct_change,
            industry_index,
            company_num,
            pct_change_stock,
            net_buy_amount,
            net_sell_amount,
            net_amount,
            fetched_at AS created_at,
            fetched_at AS updated_at
        FROM raw_tushare.moneyflow_cnt_ths
    $view$;

    EXECUTE pg_catalog.format(
        'ALTER VIEW core_serving.concept_moneyflow_ths OWNER TO %I',
        serving_owner
    );
    EXECUTE 'REVOKE ALL ON core_serving.concept_moneyflow_ths FROM PUBLIC';

    FOR grant_entry IN SELECT value FROM pg_catalog.jsonb_array_elements(select_grants)
    LOOP
        grantee_name := grant_entry ->> 'grantee';
        IF grantee_name = 'PUBLIC' THEN
            grant_sql := 'GRANT SELECT ON core_serving.concept_moneyflow_ths TO PUBLIC';
        ELSE
            grant_sql := pg_catalog.format(
                'GRANT SELECT ON core_serving.concept_moneyflow_ths TO %I',
                grantee_name
            );
        END IF;
        IF (grant_entry ->> 'is_grantable')::boolean THEN
            grant_sql := grant_sql || ' WITH GRANT OPTION';
        END IF;
        EXECUTE grant_sql;
    END LOOP;

    IF relation_comment IS NOT NULL THEN
        EXECUTE pg_catalog.format(
            'COMMENT ON VIEW core_serving.concept_moneyflow_ths IS %L',
            relation_comment
        );
    END IF;
    FOR comment_entry IN SELECT key, value FROM pg_catalog.jsonb_each_text(column_comments)
    LOOP
        EXECUTE pg_catalog.format(
            'COMMENT ON COLUMN core_serving.concept_moneyflow_ths.%I IS %L',
            comment_entry.key,
            comment_entry.value
        );
    END LOOP;

    SELECT pg_catalog.obj_description(relation_row.oid, 'pg_class')
    INTO restored_relation_comment
    FROM pg_catalog.pg_class relation_row
    WHERE relation_row.oid = 'core_serving.concept_moneyflow_ths'::regclass;

    SELECT COALESCE(
        pg_catalog.jsonb_object_agg(
            attribute_row.attname,
            pg_catalog.col_description(attribute_row.attrelid, attribute_row.attnum)
        ) FILTER (
            WHERE pg_catalog.col_description(attribute_row.attrelid, attribute_row.attnum) IS NOT NULL
        ),
        '{}'::jsonb
    )
    INTO restored_column_comments
    FROM pg_catalog.pg_attribute attribute_row
    WHERE attribute_row.attrelid = 'core_serving.concept_moneyflow_ths'::regclass
      AND attribute_row.attnum > 0
      AND NOT attribute_row.attisdropped;

    SELECT COALESCE(
        pg_catalog.jsonb_agg(
            pg_catalog.jsonb_build_object(
                'grantee', CASE
                    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
                    ELSE grantee_role.rolname
                END,
                'is_grantable', acl_row.is_grantable
            )
            ORDER BY acl_row.grantee
        ) FILTER (
            WHERE acl_row.grantee <> relation_row.relowner
              AND acl_row.privilege_type = 'SELECT'
        ),
        '[]'::jsonb
    )
    INTO restored_select_grants
    FROM pg_catalog.pg_class relation_row
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(relation_row.relacl, pg_catalog.acldefault('r', relation_row.relowner))
    ) acl_row
    LEFT JOIN pg_catalog.pg_roles grantee_role ON grantee_role.oid = acl_row.grantee
    WHERE relation_row.oid = 'core_serving.concept_moneyflow_ths'::regclass;

    IF restored_relation_comment IS DISTINCT FROM relation_comment
       OR restored_column_comments IS DISTINCT FROM column_comments
       OR restored_select_grants IS DISTINCT FROM select_grants THEN
        RAISE EXCEPTION
            'Failed to restore serving metadata: relation_comment=%, column_comments=%, select_grants=%',
            restored_relation_comment, restored_column_comments, restored_select_grants;
    END IF;

    EXECUTE $trigger$
        CREATE TRIGGER trg_concept_moneyflow_ths_reject_dml
        INSTEAD OF INSERT OR UPDATE OR DELETE
        ON core_serving.concept_moneyflow_ths
        FOR EACH ROW
        EXECUTE FUNCTION core_serving.reject_raw_direct_serving_view_dml()
    $trigger$;
END
$migration$;
"""


_VERIFY_VIEW_CONTRACT = """
DO $migration$
DECLARE
    view_oid oid;
    view_kind "char";
    view_owner text;
    view_columns text[];
    reject_function_oid oid;
BEGIN
    SELECT relation_row.oid, relation_row.relkind, owner_role.rolname
    INTO view_oid, view_kind, view_owner
    FROM pg_catalog.pg_class relation_row
    JOIN pg_catalog.pg_namespace namespace_row ON namespace_row.oid = relation_row.relnamespace
    JOIN pg_catalog.pg_roles owner_role ON owner_role.oid = relation_row.relowner
    WHERE namespace_row.nspname = 'core_serving'
      AND relation_row.relname = 'concept_moneyflow_ths';

    IF view_kind IS DISTINCT FROM 'v' THEN
        RAISE EXCEPTION 'Expected core_serving.concept_moneyflow_ths to be a view, found %', view_kind;
    END IF;
    IF view_owner IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION 'Unexpected view owner: %', view_owner;
    END IF;

    SELECT pg_catalog.array_agg(attribute_row.attname ORDER BY attribute_row.attnum)
    INTO view_columns
    FROM pg_catalog.pg_attribute attribute_row
    WHERE attribute_row.attrelid = view_oid
      AND attribute_row.attnum > 0
      AND NOT attribute_row.attisdropped;

    IF view_columns IS DISTINCT FROM ARRAY[
        'trade_date',
        'ts_code',
        'name',
        'lead_stock',
        'close_price',
        'pct_change',
        'industry_index',
        'company_num',
        'pct_change_stock',
        'net_buy_amount',
        'net_sell_amount',
        'net_amount',
        'created_at',
        'updated_at'
    ]::text[] THEN
        RAISE EXCEPTION 'Unexpected serving view columns: %', view_columns;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_trigger trigger_row
        WHERE trigger_row.tgrelid = view_oid
          AND trigger_row.tgname = 'trg_concept_moneyflow_ths_reject_dml'
          AND NOT trigger_row.tgisinternal
          AND trigger_row.tgenabled = 'O'
    ) THEN
        RAISE EXCEPTION 'Missing enabled DML rejection trigger on core_serving.concept_moneyflow_ths';
    END IF;

    SELECT function_row.oid
    INTO reject_function_oid
    FROM pg_catalog.pg_proc function_row
    JOIN pg_catalog.pg_namespace namespace_row ON namespace_row.oid = function_row.pronamespace
    JOIN pg_catalog.pg_roles owner_role ON owner_role.oid = function_row.proowner
    JOIN pg_catalog.pg_language language_row ON language_row.oid = function_row.prolang
    WHERE namespace_row.nspname = 'core_serving'
      AND function_row.proname = 'reject_raw_direct_serving_view_dml'
      AND function_row.pronargs = 0
      AND owner_role.rolname = current_user
      AND language_row.lanname = 'plpgsql'
      AND NOT function_row.prosecdef
      AND function_row.prorettype = 'trigger'::regtype
      AND function_row.proconfig = ARRAY['search_path=pg_catalog']::text[];

    IF reject_function_oid IS NULL THEN
        RAISE EXCEPTION 'Unexpected DML rejection function contract';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.aclexplode(
            COALESCE(
                (SELECT function_row.proacl FROM pg_catalog.pg_proc function_row WHERE function_row.oid = reject_function_oid),
                pg_catalog.acldefault('f', current_user::regrole)
            )
        ) acl_row
        WHERE acl_row.grantee = 0
    ) THEN
        RAISE EXCEPTION 'DML rejection function must not grant EXECUTE to PUBLIC';
    END IF;
END
$migration$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for statement in _SET_BOUNDED_SESSION_LIMITS:
        op.execute(statement)
    op.execute(_PREFLIGHT_RELATIONS)
    for statement in _LOCK_SOURCE_RELATIONS:
        op.execute(statement)
    op.execute(_PREFLIGHT_CONTRACT)
    op.execute(_VERIFY_DATA_EQUIVALENCE)
    op.execute(_VERIFY_EXISTING_REJECT_FUNCTION)
    op.execute(_LOCK_SERVING_FOR_SWITCH)
    op.execute(_SWITCH_RELATION)
    op.execute(_VERIFY_VIEW_CONTRACT)


def downgrade() -> None:
    raise RuntimeError(
        "Recreating a physical core_serving.concept_moneyflow_ths table requires an explicit approved "
        "forward migration; automatic downgrade is forbidden."
    )
