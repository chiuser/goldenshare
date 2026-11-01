BEGIN READ ONLY;
SET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s';
SELECT jsonb_build_object('section','as_of','time',current_timestamp,'read_only',current_setting('transaction_read_only'));
WITH q AS(SELECT n.nspname schema_name,c.relname relation_name,c.relkind,c.reltuples::bigint estimated_rows FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE (n.nspname='raw_tushare' AND c.relname IN('fina_indicator','stock_basic')) OR(n.nspname='core_serving' AND c.relname IN('equity_income','equity_balancesheet','equity_cashflow','equity_daily_basic','wealth_sector_hierarchy','dc_member')))
SELECT jsonb_build_object('section','relations','data',jsonb_agg(to_jsonb(q) ORDER BY schema_name,relation_name)) FROM q;
WITH q AS(SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes WHERE(schemaname='raw_tushare' AND tablename='fina_indicator') OR(schemaname='core_serving' AND tablename IN('wealth_sector_hierarchy','dc_member','equity_daily_basic')))
SELECT jsonb_build_object('section','indexes','data',jsonb_agg(to_jsonb(q) ORDER BY tablename,indexname)) FROM q;
WITH q AS(SELECT viewname,definition FROM pg_views WHERE schemaname='core_serving' AND viewname IN('equity_income','equity_balancesheet','equity_cashflow','equity_fina_indicator'))
SELECT jsonb_build_object('section','serving_views','data',jsonb_agg(to_jsonb(q))) FROM q;
COMMIT;
