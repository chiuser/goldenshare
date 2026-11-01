BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off;
WITH q AS(SELECT trade_date,count(*) records,count(DISTINCT ts_code) codes,count(close) close_nonnull,count(*) FILTER(WHERE close>0) close_positive,count(total_mv) total_mv_nonnull,count(*) FILTER(WHERE total_mv>0) total_mv_positive,count(total_share) total_share_nonnull,count(*) FILTER(WHERE total_share>0) total_share_positive,count(pe_ttm) pe_ttm_nonnull,count(*) FILTER(WHERE pe_ttm>0) pe_ttm_positive,count(pb) pb_nonnull,count(*) FILTER(WHERE pb>0) pb_positive,count(ps_ttm) ps_ttm_nonnull,count(dv_ttm) dv_ttm_nonnull FROM core_serving.equity_daily_basic WHERE trade_date IN (DATE '2019-10-31',DATE '2019-12-31',DATE '2020-10-30',DATE '2020-12-31',DATE '2021-10-29',DATE '2021-12-31',DATE '2022-10-31',DATE '2022-12-30',DATE '2023-10-31',DATE '2023-12-29',DATE '2024-10-31',DATE '2024-12-31',DATE '2025-10-31',DATE '2025-12-31',DATE '2026-09-30',DATE '2026-10-29',DATE '2026-10-30') GROUP BY trade_date)
SELECT jsonb_build_object('section','valuation_dates','as_of',current_timestamp,'data',coalesce(jsonb_agg(to_jsonb(q) ORDER BY trade_date),'[]'::jsonb)) FROM q;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off;
WITH q AS(SELECT trade_date,count(*) records,count(DISTINCT ts_code) codes FROM core_serving.equity_daily_basic WHERE trade_date BETWEEN DATE '2026-10-23' AND DATE '2026-10-31' GROUP BY trade_date)
SELECT jsonb_build_object('section','recent_valuation_days','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q) ORDER BY trade_date)) FROM q;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off;
WITH q AS(SELECT trade_date,count(*) records,count(total_mv) market_value_nonnull FROM raw_tushare.daily_basic WHERE ts_code IN ('600519.SH','000001.SZ','601398.SH') AND trade_date IN (DATE '2019-10-31',DATE '2019-12-31',DATE '2020-10-30',DATE '2020-12-31',DATE '2021-10-29',DATE '2021-12-31',DATE '2022-10-31',DATE '2022-12-30',DATE '2023-10-31',DATE '2023-12-29',DATE '2024-10-31',DATE '2024-12-31',DATE '2025-10-31',DATE '2025-12-31',DATE '2026-09-30',DATE '2026-10-29',DATE '2026-10-30') GROUP BY trade_date)
SELECT jsonb_build_object('section','raw_valuation_three_code_control','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q) ORDER BY trade_date)) FROM q;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off;
WITH i AS MATERIALIZED(SELECT trade_date,ts_code,level FROM core_serving.dc_index WHERE trade_date IN (DATE '2019-10-31',DATE '2019-12-31',DATE '2020-10-30',DATE '2020-12-31',DATE '2021-10-29',DATE '2021-12-31',DATE '2022-10-31',DATE '2022-12-30',DATE '2023-10-31',DATE '2023-12-29',DATE '2024-10-31',DATE '2024-12-31',DATE '2025-10-31',DATE '2025-12-31',DATE '2026-09-30',DATE '2026-10-29',DATE '2026-10-30') AND idx_type='行业板块' AND level IN ('东财一级行业','东财二级行业')),
q AS(SELECT i.trade_date,i.level,count(DISTINCT i.ts_code) industries,count(m.con_code) relations,count(DISTINCT m.con_code) member_codes FROM i LEFT JOIN core_serving.dc_member m ON m.trade_date=i.trade_date AND m.ts_code=i.ts_code GROUP BY i.trade_date,i.level)
SELECT jsonb_build_object('section','industry_history_dates','as_of',current_timestamp,'data',coalesce(jsonb_agg(to_jsonb(q) ORDER BY trade_date,level),'[]'::jsonb)) FROM q;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s';
WITH q AS(SELECT table_schema,table_name,jsonb_agg(jsonb_build_object('name',column_name,'type',data_type) ORDER BY ordinal_position) columns FROM information_schema.columns WHERE (table_schema='raw_tushare' AND table_name IN ('trade_cal','dividend','hk_basic','bse_mapping','namechange')) OR (table_schema='core_serving' AND table_name IN ('trade_calendar','equity_dividend','equity_express')) GROUP BY table_schema,table_name)
SELECT jsonb_build_object('section','support_columns','data',jsonb_agg(to_jsonb(q))) FROM q;
COMMIT;
