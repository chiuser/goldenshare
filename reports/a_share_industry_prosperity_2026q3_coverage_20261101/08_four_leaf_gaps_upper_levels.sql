BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s';
WITH q AS(SELECT m.con_code,h.industry_level,count(DISTINCT h.sector_code) assignments FROM core_serving.dc_member m JOIN core_serving.wealth_sector_hierarchy h ON h.sector_code=m.ts_code WHERE m.trade_date=DATE '2026-10-30' AND m.con_code IN('002553.SZ','002843.SZ','688059.SH','920238.BJ') GROUP BY m.con_code,h.industry_level)
SELECT jsonb_build_object('section','four_leaf_gaps_upper_levels','as_of',current_timestamp,'data',jsonb_agg(to_jsonb(q) ORDER BY con_code,industry_level)) FROM q;
COMMIT;
