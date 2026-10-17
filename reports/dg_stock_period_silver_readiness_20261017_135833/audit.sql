-- lifecycle_once
CREATE TEMP TABLE life AS SELECT ts_code,name,exchange,list_status,list_date,delist_date,is_cny_stock FROM read_parquet(?);

-- listed_scope
CREATE TEMP TABLE listed AS SELECT * FROM life WHERE list_status='L' AND is_cny_stock;

-- identity_once
CREATE TEMP TABLE identities AS SELECT source_ts_code,latest_ts_code,confidence FROM read_parquet(?);

-- calendar_once
CREATE TEMP TABLE cal AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)::INTEGER ord FROM read_parquet(?) WHERE exchange='SSE' AND is_open AND trade_date BETWEEN ? AND ?;

-- lifecycle_bounds
CREATE TEMP TABLE bounds AS SELECT l.*,n.ord first_ord,p.ord last_ord
        FROM listed l ASOF LEFT JOIN cal n ON greatest(l.list_date,?::DATE)<=n.trade_date
        ASOF LEFT JOIN cal p ON least(coalesce(l.delist_date-1,?::DATE),?::DATE)>=p.trade_date;

-- periods
CREATE TEMP TABLE periods AS
        WITH p AS (SELECT f.freq,date_trunc(f.freq,c.trade_date)::DATE period_start,min(c.ord) first_ord,max(c.ord) last_ord
            FROM cal c CROSS JOIN (VALUES ('week'),('month')) f(freq) GROUP BY 1,2)
        SELECT *,CASE WHEN freq='week' THEN period_start+4 ELSE last_day(period_start) END period_label,
        row_number() OVER(PARTITION BY freq ORDER BY period_start)::INTEGER period_seq FROM p;

-- suspension_once
CREATE TEMP TABLE susp_all AS
        SELECT s.ts_code source_code,i.latest_ts_code ts_code,s.trade_date,s.suspend_type,s.suspend_timing
        FROM read_parquet(?,hive_partitioning=false) s LEFT JOIN identities i ON s.ts_code=i.source_ts_code;

-- full_day_suspensions
CREATE TEMP TABLE full_susp AS SELECT DISTINCT ts_code,trade_date FROM susp_all WHERE suspend_type='S' AND suspend_timing IS NULL;

-- suspension_periods
CREATE TEMP TABLE susp_period AS
        SELECT f.freq,s.ts_code,date_trunc(f.freq,s.trade_date)::DATE period_start,count(DISTINCT s.trade_date)::INTEGER suspended_days
        FROM full_susp s JOIN bounds b USING(ts_code) JOIN cal c ON c.trade_date=s.trade_date AND c.ord BETWEEN b.first_ord AND b.last_ord
        CROSS JOIN (VALUES ('week'),('month')) f(freq) GROUP BY 1,2,3;

-- expected_stock_periods
CREATE TEMP TABLE expected AS
        SELECT p.freq,b.ts_code,p.period_start,p.period_label,p.period_seq,
        (least(b.last_ord,p.last_ord)-greatest(b.first_ord,p.first_ord)+1)::INTEGER eligible_days,
        coalesce(s.suspended_days,0)::INTEGER suspended_days
        FROM bounds b JOIN periods p ON b.first_ord<=p.last_ord AND b.last_ord>=p.first_ord
        LEFT JOIN susp_period s ON s.freq=p.freq AND s.ts_code=b.ts_code AND s.period_start=p.period_start;

-- week_raw_once
CREATE TEMP TABLE raw AS SELECT r."ts_code",r."trade_date",r."end_date",r."freq",r."open",r."high",r."low",r."close",r."pre_close",r."open_qfq",r."high_qfq",r."low_qfq",r."close_qfq",r."open_hfq",r."high_hfq",r."low_hfq",r."close_hfq",r."vol",r."amount",r."change",r."pct_chg",r.filename,
            i.latest_ts_code canonical_code,i.confidence,
            try_strptime(r.trade_date,'%Y%m%d')::DATE bar_date,try_strptime(r.end_date,'%Y%m%d')::DATE source_asof,
            date_trunc('week',try_strptime(r.trade_date,'%Y%m%d'))::DATE period_start
            FROM read_parquet(?,hive_partitioning=false,filename=true) r LEFT JOIN identities i ON r.ts_code=i.source_ts_code;

-- week_scope
CREATE TEMP VIEW scoped AS SELECT r.*,l.list_status,l.list_date,l.delist_date,
            CASE WHEN r.canonical_code IS NULL OR r.confidence IS DISTINCT FROM 'confirmed' THEN 'identity_unresolved'
              WHEN l.ts_code IS NULL THEN 'lifecycle_unresolved'
              WHEN l.list_status<>'L' OR NOT l.is_cny_stock THEN 'outside_listed_scope'
              WHEN r.bar_date IS NULL OR r.source_asof IS NULL OR r.freq<>'week' THEN 'invalid_date_or_frequency'
              WHEN r.period_start<date_trunc('week',DATE '2014-01-01') THEN 'before_2014_period'
              WHEN r.period_start<date_trunc('week',l.list_date) THEN 'before_listing_period'
              WHEN l.delist_date IS NOT NULL AND r.period_start>date_trunc('week',l.delist_date-1) THEN 'after_delisting_period'
              WHEN r.period_start>date_trunc('week',DATE '2026-10-16') THEN 'future_period'
              ELSE 'eligible' END classification
            FROM raw r LEFT JOIN life l ON l.ts_code=r.canonical_code;

-- week_scope_issues
COPY (SELECT 'week' frequency,ts_code source_code,canonical_code,trade_date,end_date,classification,filename FROM scoped WHERE classification NOT IN ('eligible','before_2014_period','before_listing_period','outside_listed_scope')) TO ? (FORMAT CSV, HEADER TRUE);

-- week_latest_keys
CREATE TEMP TABLE latest_keys AS SELECT canonical_code ts_code,period_start,max(source_asof) source_asof,count(*) raw_rows
            FROM scoped WHERE classification='eligible' GROUP BY 1,2;

-- week_latest_counts
CREATE TEMP TABLE latest_counts AS SELECT k.ts_code,k.period_start,k.source_asof,k.raw_rows,count(*) latest_rows,
            min(r.bar_date) first_latest_label,max(r.bar_date) last_latest_label
            FROM latest_keys k JOIN scoped r ON r.canonical_code=k.ts_code AND r.period_start=k.period_start AND r.source_asof=k.source_asof
            WHERE r.classification='eligible' GROUP BY 1,2,3,4;

-- week_only_tied_latest_values
CREATE TEMP TABLE tie_variants AS
            SELECT c.ts_code,c.period_start,count(DISTINCT (r."open",r."high",r."low",r."close",r."pre_close",r."open_qfq",r."high_qfq",r."low_qfq",r."close_qfq",r."open_hfq",r."high_hfq",r."low_hfq",r."close_hfq",r."vol",r."amount",r."change",r."pct_chg")) variants
            FROM latest_counts c JOIN scoped r ON r.canonical_code=c.ts_code AND r.period_start=c.period_start AND r.source_asof=c.source_asof
            WHERE c.latest_rows>1 AND r.classification='eligible' GROUP BY 1,2;

-- week_actual_valid_periods
CREATE TEMP TABLE actual AS SELECT c.* FROM latest_counts c LEFT JOIN tie_variants t USING(ts_code,period_start) WHERE coalesce(t.variants,1)=1;

-- week_latest_conflicts
COPY (SELECT 'week' frequency,r.canonical_code ts_code,l.name stock_name,r.period_start,r.trade_date,r.end_date,
            to_json(struct_pack(open := r."open",high := r."high",low := r."low",close := r."close",pre_close := r."pre_close",open_qfq := r."open_qfq",high_qfq := r."high_qfq",low_qfq := r."low_qfq",close_qfq := r."close_qfq",open_hfq := r."open_hfq",high_hfq := r."high_hfq",low_hfq := r."low_hfq",close_hfq := r."close_hfq",vol := r."vol",amount := r."amount",change := r."change",pct_chg := r."pct_chg")) business_values,r.filename source_file
            FROM scoped r JOIN tie_variants t ON r.canonical_code=t.ts_code AND r.period_start=t.period_start
            JOIN latest_keys k ON k.ts_code=t.ts_code AND k.period_start=t.period_start AND k.source_asof=r.source_asof
            JOIN listed l ON l.ts_code=r.canonical_code WHERE t.variants>1 AND r.classification='eligible'
            ORDER BY ts_code,period_start,r.trade_date) TO ? (FORMAT CSV, HEADER TRUE);

-- week_missing
CREATE TEMP TABLE missing AS SELECT e.*,
            CASE WHEN k.ts_code IS NOT NULL THEN 'latest_version_conflict' ELSE 'missing_required_period' END reason
            FROM expected e ANTI JOIN actual a USING(ts_code,period_start)
            LEFT JOIN latest_keys k USING(ts_code,period_start)
            WHERE e.freq='week' AND e.eligible_days>e.suspended_days;

-- week_missing_ranges
CREATE TEMP TABLE missing_ranges AS
            WITH n AS (SELECT *,period_seq-row_number() OVER(PARTITION BY ts_code,reason ORDER BY period_seq) island FROM missing),
            g AS (SELECT ts_code,reason,island,min(period_label) missing_from,max(period_label) missing_to,count(*) missing_period_count,
                sum(eligible_days) eligible_trading_days,sum(suspended_days) full_day_suspension_days FROM n GROUP BY 1,2,3)
            SELECT g.*,l.name stock_name,l.exchange,l.list_status,l.list_date,l.delist_date FROM g JOIN listed l USING(ts_code);

-- week_missing_range_csv
COPY (SELECT 'week' frequency,ts_code,stock_name,exchange,list_status,list_date,delist_date,missing_from,missing_to,missing_period_count,eligible_trading_days,full_day_suspension_days,reason FROM missing_ranges ORDER BY ts_code,missing_from) TO ? (FORMAT CSV, HEADER TRUE);

-- week_missing_period_csv
COPY (SELECT 'week' frequency,m.ts_code,l.name stock_name,l.exchange,l.list_date,l.delist_date,m.period_label,m.eligible_days,m.suspended_days,m.reason FROM missing m JOIN listed l USING(ts_code) ORDER BY m.ts_code,m.period_label) TO ? (FORMAT CSV, HEADER TRUE);

-- week_suspension_contradictions
COPY (SELECT 'week' frequency,e.ts_code,l.name stock_name,e.period_label,e.eligible_days,e.suspended_days,
            a.first_latest_label,a.last_latest_label FROM expected e JOIN actual a USING(ts_code,period_start) JOIN listed l USING(ts_code)
            WHERE e.freq='week' AND e.eligible_days=e.suspended_days AND e.period_start>=greatest(l.list_date,DATE '2014-01-01') ORDER BY e.ts_code,e.period_label) TO ? (FORMAT CSV, HEADER TRUE);

-- month_raw_once
CREATE TEMP TABLE raw AS SELECT r."ts_code",r."trade_date",r."end_date",r."freq",r."open",r."high",r."low",r."close",r."pre_close",r."open_qfq",r."high_qfq",r."low_qfq",r."close_qfq",r."open_hfq",r."high_hfq",r."low_hfq",r."close_hfq",r."vol",r."amount",r."change",r."pct_chg",r.filename,
            i.latest_ts_code canonical_code,i.confidence,
            try_strptime(r.trade_date,'%Y%m%d')::DATE bar_date,try_strptime(r.end_date,'%Y%m%d')::DATE source_asof,
            date_trunc('month',try_strptime(r.trade_date,'%Y%m%d'))::DATE period_start
            FROM read_parquet(?,hive_partitioning=false,filename=true) r LEFT JOIN identities i ON r.ts_code=i.source_ts_code;

-- month_scope
CREATE TEMP VIEW scoped AS SELECT r.*,l.list_status,l.list_date,l.delist_date,
            CASE WHEN r.canonical_code IS NULL OR r.confidence IS DISTINCT FROM 'confirmed' THEN 'identity_unresolved'
              WHEN l.ts_code IS NULL THEN 'lifecycle_unresolved'
              WHEN l.list_status<>'L' OR NOT l.is_cny_stock THEN 'outside_listed_scope'
              WHEN r.bar_date IS NULL OR r.source_asof IS NULL OR r.freq<>'month' THEN 'invalid_date_or_frequency'
              WHEN r.period_start<date_trunc('month',DATE '2014-01-01') THEN 'before_2014_period'
              WHEN r.period_start<date_trunc('month',l.list_date) THEN 'before_listing_period'
              WHEN l.delist_date IS NOT NULL AND r.period_start>date_trunc('month',l.delist_date-1) THEN 'after_delisting_period'
              WHEN r.period_start>date_trunc('month',DATE '2026-10-16') THEN 'future_period'
              ELSE 'eligible' END classification
            FROM raw r LEFT JOIN life l ON l.ts_code=r.canonical_code;

-- month_scope_issues
COPY (SELECT 'month' frequency,ts_code source_code,canonical_code,trade_date,end_date,classification,filename FROM scoped WHERE classification NOT IN ('eligible','before_2014_period','before_listing_period','outside_listed_scope')) TO ? (FORMAT CSV, HEADER TRUE);

-- month_latest_keys
CREATE TEMP TABLE latest_keys AS SELECT canonical_code ts_code,period_start,max(source_asof) source_asof,count(*) raw_rows
            FROM scoped WHERE classification='eligible' GROUP BY 1,2;

-- month_latest_counts
CREATE TEMP TABLE latest_counts AS SELECT k.ts_code,k.period_start,k.source_asof,k.raw_rows,count(*) latest_rows,
            min(r.bar_date) first_latest_label,max(r.bar_date) last_latest_label
            FROM latest_keys k JOIN scoped r ON r.canonical_code=k.ts_code AND r.period_start=k.period_start AND r.source_asof=k.source_asof
            WHERE r.classification='eligible' GROUP BY 1,2,3,4;

-- month_only_tied_latest_values
CREATE TEMP TABLE tie_variants AS
            SELECT c.ts_code,c.period_start,count(DISTINCT (r."open",r."high",r."low",r."close",r."pre_close",r."open_qfq",r."high_qfq",r."low_qfq",r."close_qfq",r."open_hfq",r."high_hfq",r."low_hfq",r."close_hfq",r."vol",r."amount",r."change",r."pct_chg")) variants
            FROM latest_counts c JOIN scoped r ON r.canonical_code=c.ts_code AND r.period_start=c.period_start AND r.source_asof=c.source_asof
            WHERE c.latest_rows>1 AND r.classification='eligible' GROUP BY 1,2;

-- month_actual_valid_periods
CREATE TEMP TABLE actual AS SELECT c.* FROM latest_counts c LEFT JOIN tie_variants t USING(ts_code,period_start) WHERE coalesce(t.variants,1)=1;

-- month_latest_conflicts
COPY (SELECT 'month' frequency,r.canonical_code ts_code,l.name stock_name,r.period_start,r.trade_date,r.end_date,
            to_json(struct_pack(open := r."open",high := r."high",low := r."low",close := r."close",pre_close := r."pre_close",open_qfq := r."open_qfq",high_qfq := r."high_qfq",low_qfq := r."low_qfq",close_qfq := r."close_qfq",open_hfq := r."open_hfq",high_hfq := r."high_hfq",low_hfq := r."low_hfq",close_hfq := r."close_hfq",vol := r."vol",amount := r."amount",change := r."change",pct_chg := r."pct_chg")) business_values,r.filename source_file
            FROM scoped r JOIN tie_variants t ON r.canonical_code=t.ts_code AND r.period_start=t.period_start
            JOIN latest_keys k ON k.ts_code=t.ts_code AND k.period_start=t.period_start AND k.source_asof=r.source_asof
            JOIN listed l ON l.ts_code=r.canonical_code WHERE t.variants>1 AND r.classification='eligible'
            ORDER BY ts_code,period_start,r.trade_date) TO ? (FORMAT CSV, HEADER TRUE);

-- month_missing
CREATE TEMP TABLE missing AS SELECT e.*,
            CASE WHEN k.ts_code IS NOT NULL THEN 'latest_version_conflict' ELSE 'missing_required_period' END reason
            FROM expected e ANTI JOIN actual a USING(ts_code,period_start)
            LEFT JOIN latest_keys k USING(ts_code,period_start)
            WHERE e.freq='month' AND e.eligible_days>e.suspended_days;

-- month_missing_ranges
CREATE TEMP TABLE missing_ranges AS
            WITH n AS (SELECT *,period_seq-row_number() OVER(PARTITION BY ts_code,reason ORDER BY period_seq) island FROM missing),
            g AS (SELECT ts_code,reason,island,min(period_label) missing_from,max(period_label) missing_to,count(*) missing_period_count,
                sum(eligible_days) eligible_trading_days,sum(suspended_days) full_day_suspension_days FROM n GROUP BY 1,2,3)
            SELECT g.*,l.name stock_name,l.exchange,l.list_status,l.list_date,l.delist_date FROM g JOIN listed l USING(ts_code);

-- month_missing_range_csv
COPY (SELECT 'month' frequency,ts_code,stock_name,exchange,list_status,list_date,delist_date,missing_from,missing_to,missing_period_count,eligible_trading_days,full_day_suspension_days,reason FROM missing_ranges ORDER BY ts_code,missing_from) TO ? (FORMAT CSV, HEADER TRUE);

-- month_missing_period_csv
COPY (SELECT 'month' frequency,m.ts_code,l.name stock_name,l.exchange,l.list_date,l.delist_date,m.period_label,m.eligible_days,m.suspended_days,m.reason FROM missing m JOIN listed l USING(ts_code) ORDER BY m.ts_code,m.period_label) TO ? (FORMAT CSV, HEADER TRUE);

-- month_suspension_contradictions
COPY (SELECT 'month' frequency,e.ts_code,l.name stock_name,e.period_label,e.eligible_days,e.suspended_days,
            a.first_latest_label,a.last_latest_label FROM expected e JOIN actual a USING(ts_code,period_start) JOIN listed l USING(ts_code)
            WHERE e.freq='month' AND e.eligible_days=e.suspended_days AND e.period_start>=greatest(l.list_date,DATE '2014-01-01') ORDER BY e.ts_code,e.period_label) TO ? (FORMAT CSV, HEADER TRUE);
