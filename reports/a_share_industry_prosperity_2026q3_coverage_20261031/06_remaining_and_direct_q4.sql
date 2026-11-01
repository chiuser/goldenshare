BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off; SET LOCAL enable_nestloop=off;
WITH q AS(SELECT trade_date,is_open FROM core_serving.trade_calendar WHERE exchange='SSE' AND trade_date IN(DATE '2019-10-31',DATE '2019-12-31',DATE '2020-10-30',DATE '2020-12-31',DATE '2021-10-29',DATE '2021-12-31',DATE '2022-10-31',DATE '2022-12-30',DATE '2023-10-31',DATE '2023-12-29',DATE '2024-10-31',DATE '2024-12-31',DATE '2025-10-31',DATE '2025-12-31',DATE '2026-10-30',DATE '2026-10-31'))
SELECT jsonb_build_object('section','calendar_dates','data',jsonb_agg(to_jsonb(q) ORDER BY trade_date)) FROM q;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off; SET LOCAL enable_nestloop=off;
WITH q AS(SELECT ts_code,end_date,count(*) versions,count(DISTINCT ann_date) announcement_dates FROM raw_tushare.income WHERE report_type='1' AND end_date IN(DATE '2024-09-30',DATE '2025-09-30',DATE '2026-09-30') GROUP BY ts_code,end_date),r AS(SELECT end_date,count(*) code_periods,count(*) FILTER(WHERE versions>1) multiple_version_keys,count(*) FILTER(WHERE announcement_dates>1) multiple_announcement_keys FROM q GROUP BY end_date)
SELECT jsonb_build_object('section','income_version_counts','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(r) ORDER BY end_date)) FROM r;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off; SET LOCAL enable_nestloop=off;
WITH members AS MATERIALIZED(SELECT DISTINCT m.con_code AS ts_code FROM core_serving.dc_member m JOIN core_serving.dc_index i ON i.trade_date=m.trade_date AND i.ts_code=m.ts_code WHERE m.trade_date=DATE '2026-09-30' AND i.idx_type='行业板块' AND i.level='东财一级行业'),base AS MATERIALIZED(SELECT s.ts_code FROM members m JOIN raw_tushare.stock_basic s ON s.ts_code=m.ts_code WHERE s.ts_code !~ '^(200|900)' AND s.list_date<=DATE '2026-09-30' AND (s.delist_date IS NULL OR s.delist_date>DATE '2026-09-30')),f AS MATERIALIZED(SELECT DISTINCT ON(ts_code,end_date) ts_code,end_date,profit_dedt,q_dtprofit FROM raw_tushare.fina_indicator WHERE end_date IN(DATE '2019-09-30',DATE '2019-12-31',DATE '2020-09-30',DATE '2020-12-31',DATE '2021-09-30',DATE '2021-12-31',DATE '2022-09-30',DATE '2022-12-31',DATE '2023-09-30',DATE '2023-12-31',DATE '2024-09-30',DATE '2024-12-31',DATE '2025-09-30',DATE '2025-12-31') ORDER BY ts_code,end_date,CASE update_flag WHEN '1' THEN 0 ELSE 1 END,ann_date DESC,fetched_at DESC,source_content_hash DESC),years AS(SELECT generate_series(2019,2025) y),t AS MATERIALIZED(SELECT a.ts_code,y.y,f9.profit_dedt d9,f12.profit_dedt d12,f12.q_dtprofit q4 FROM base a CROSS JOIN years y LEFT JOIN f f9 ON f9.ts_code=a.ts_code AND f9.end_date=make_date(y.y,9,30) LEFT JOIN f f12 ON f12.ts_code=a.ts_code AND f12.end_date=make_date(y.y,12,31)),q AS(SELECT y,count(*) FILTER(WHERE q4 IS NOT NULL) direct_q4_codes,count(*) FILTER(WHERE d9 IS NOT NULL AND d12 IS NOT NULL) cumulative_pair_codes,count(*) FILTER(WHERE q4 IS NOT NULL AND d9 IS NOT NULL AND d12 IS NOT NULL) overlap_codes,count(*) FILTER(WHERE q4 IS NOT NULL AND d9 IS NOT NULL AND d12 IS NOT NULL AND abs(q4-(d12-d9))<=1) overlap_equal_within_1yuan,count(*) FILTER(WHERE q4 IS NOT NULL OR (d9 IS NOT NULL AND d12 IS NOT NULL)) either_codes FROM t GROUP BY y),h AS(SELECT ts_code,count(*) FILTER(WHERE q4 IS NOT NULL OR(d9 IS NOT NULL AND d12 IS NOT NULL)) years FROM t GROUP BY ts_code),hist AS(SELECT years,count(*) codes FROM h GROUP BY years)
SELECT jsonb_build_object('section','deducted_direct_q4_availability','as_of',current_timestamp,'year_counts',(SELECT jsonb_agg(to_jsonb(q) ORDER BY y) FROM q),'history_counts',(SELECT jsonb_agg(to_jsonb(hist) ORDER BY years) FROM hist));
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off; SET LOCAL enable_nestloop=off;
WITH q AS(SELECT end_date,report_type,count(DISTINCT ts_code) codes FROM raw_tushare.income WHERE end_date IN(DATE '2019-09-30',DATE '2020-09-30',DATE '2021-09-30',DATE '2024-09-30',DATE '2026-09-30') GROUP BY end_date,report_type)
SELECT jsonb_build_object('section','income_raw_report_types','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q) ORDER BY end_date,report_type)) FROM q;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off; SET LOCAL enable_nestloop=off;
WITH q AS(SELECT end_date,report_type,count(DISTINCT ts_code) codes FROM raw_tushare.balancesheet WHERE end_date IN(DATE '2019-09-30',DATE '2020-09-30',DATE '2021-09-30',DATE '2024-09-30',DATE '2026-09-30') GROUP BY end_date,report_type)
SELECT jsonb_build_object('section','balancesheet_raw_report_types','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q) ORDER BY end_date,report_type)) FROM q;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off; SET LOCAL enable_nestloop=off;
WITH q AS(SELECT end_date,report_type,count(DISTINCT ts_code) codes FROM raw_tushare.cashflow WHERE end_date IN(DATE '2019-09-30',DATE '2020-09-30',DATE '2021-09-30',DATE '2024-09-30',DATE '2026-09-30') GROUP BY end_date,report_type)
SELECT jsonb_build_object('section','cashflow_raw_report_types','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q) ORDER BY end_date,report_type)) FROM q;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off; SET LOCAL enable_nestloop=off;
WITH q AS(SELECT ts_code,count(*) FILTER(WHERE trade_date=DATE '2026-10-30') raw_oct30_records,count(*) september_october_records,max(trade_date) last_observed_date FROM raw_tushare.daily_basic WHERE ts_code IN('002717.SZ','002827.SZ','601326.SH','605258.SH','688121.SH','688496.SH') AND trade_date BETWEEN DATE '2026-09-01' AND DATE '2026-10-30' GROUP BY ts_code)
SELECT jsonb_build_object('section','missing_valuation_raw_check','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q))) FROM q;
COMMIT;
