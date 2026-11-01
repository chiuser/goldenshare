BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off;
WITH r AS MATERIALIZED(SELECT ts_code,end_date,ann_date,update_flag,fetched_at,source_content_hash,profit_dedt,q_dtprofit,roe FROM raw_tushare.fina_indicator WHERE end_date IN(DATE '2024-03-31',DATE '2024-06-30',DATE '2024-09-30',DATE '2024-12-31',DATE '2025-03-31',DATE '2025-06-30',DATE '2025-09-30',DATE '2025-12-31',DATE '2026-03-31',DATE '2026-06-30',DATE '2026-09-30')),
latest AS MATERIALIZED(SELECT DISTINCT ON(ts_code,end_date) ts_code,end_date,ann_date,update_flag,fetched_at,profit_dedt,q_dtprofit,roe FROM r ORDER BY ts_code,end_date,CASE update_flag WHEN '1' THEN 0 ELSE 1 END,ann_date DESC,fetched_at DESC,source_content_hash DESC),
a AS(SELECT end_date,count(*) raw_rows,count(DISTINCT ts_code) raw_codes,max(fetched_at) last_fetched_at FROM r GROUP BY end_date),
v AS(SELECT ts_code,end_date,count(*) versions,bool_or(profit_dedt IS NOT NULL) any_dedt_nonnull FROM r GROUP BY ts_code,end_date),
b AS(SELECT l.end_date,count(*) selected_codes,count(l.profit_dedt) profit_dedt_nonnull,count(l.q_dtprofit) q_dtprofit_nonnull,count(l.roe) roe_nonnull,count(*) FILTER(WHERE v.versions>1) multiple_version_codes,count(*) FILTER(WHERE l.profit_dedt IS NULL AND v.any_dedt_nonnull) selected_null_but_other_version_valid,count(*) FILTER(WHERE l.ann_date>DATE '2026-11-01') future_announcement_codes FROM latest l JOIN v ON v.ts_code=l.ts_code AND v.end_date=l.end_date GROUP BY l.end_date),
q AS(SELECT a.end_date,a.raw_rows,a.raw_codes,a.last_fetched_at,b.selected_codes,b.profit_dedt_nonnull,b.q_dtprofit_nonnull,b.roe_nonnull,b.multiple_version_codes,b.selected_null_but_other_version_valid,b.future_announcement_codes FROM a JOIN b USING(end_date))
SELECT jsonb_build_object('section','fina_indicator_periods','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q) ORDER BY end_date)) FROM q;
COMMIT;
