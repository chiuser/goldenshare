BEGIN READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='3s';
WITH q AS(SELECT baseline_version,industry_level,count(*) nodes FROM core_serving.wealth_sector_hierarchy GROUP BY baseline_version,industry_level)
SELECT jsonb_build_object('section','published_fixed_hierarchy','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q) ORDER BY industry_level)) FROM q;
COMMIT;
BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off;
WITH base AS MATERIALIZED(SELECT ts_code FROM raw_tushare.stock_basic WHERE ts_code !~ '^(200|900)' AND list_status IN('L','P') AND list_date<=DATE '2026-10-30' AND(delist_date IS NULL OR delist_date>DATE '2026-10-30')),
fixed_members AS MATERIALIZED(SELECT m.trade_date,h.industry_level,m.con_code FROM core_serving.dc_member m JOIN core_serving.wealth_sector_hierarchy h ON h.sector_code=m.ts_code WHERE m.trade_date IN(DATE '2026-10-29',DATE '2026-10-30')),
ds AS(SELECT DISTINCT trade_date,industry_level FROM fixed_members),
q AS(SELECT ds.trade_date,ds.industry_level,count(DISTINCT b.ts_code) eligible_codes,count(DISTINCT m.con_code) mapped_codes FROM ds CROSS JOIN base b LEFT JOIN fixed_members m ON m.trade_date=ds.trade_date AND m.industry_level=ds.industry_level AND m.con_code=b.ts_code GROUP BY ds.trade_date,ds.industry_level)
SELECT jsonb_build_object('section','fixed_hierarchy_member_coverage','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q) ORDER BY trade_date,industry_level)) FROM q;
COMMIT;
