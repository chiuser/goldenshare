BEGIN READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='3s';
SELECT json_build_object('section','as_of','data',json_build_object('time',current_timestamp,'read_only',current_setting('transaction_read_only')));
SELECT json_build_object('section','relations','data',json_agg(q ORDER BY schema_name,relation_name)) FROM (
 SELECT n.nspname schema_name,c.relname relation_name,c.relkind,c.reltuples::bigint estimated_rows
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE (n.nspname='raw_tushare' AND c.relname IN ('income','balancesheet','cashflow','fina_indicator','daily_basic','stock_basic'))
 OR (n.nspname='core_serving' AND c.relname IN ('equity_income','equity_balancesheet','equity_cashflow','equity_fina_indicator','equity_daily_basic','dc_index','dc_member'))
) q;
SELECT json_build_object('section','columns','data',json_agg(q ORDER BY table_schema,table_name)) FROM (
 SELECT table_schema,table_name,json_agg(json_build_object('name',column_name,'type',data_type) ORDER BY ordinal_position) columns
 FROM information_schema.columns
 WHERE (table_schema='raw_tushare' AND table_name IN ('income','balancesheet','cashflow','fina_indicator','daily_basic','stock_basic'))
 OR (table_schema='core_serving' AND table_name IN ('equity_income','equity_balancesheet','equity_cashflow','equity_fina_indicator','equity_daily_basic','dc_index','dc_member'))
 GROUP BY table_schema,table_name
) q;
SELECT json_build_object('section','indexes','data',json_agg(q ORDER BY schemaname,tablename,indexname)) FROM (
 SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes
 WHERE (schemaname='raw_tushare' AND tablename IN ('income','balancesheet','cashflow','fina_indicator','daily_basic','stock_basic'))
 OR (schemaname='core_serving' AND tablename IN ('equity_daily_basic','dc_index','dc_member'))
) q;
SELECT json_build_object('section','views','data',json_agg(q)) FROM (
 SELECT schemaname,viewname,definition FROM pg_views WHERE schemaname='core_serving'
 AND viewname IN ('equity_income','equity_balancesheet','equity_cashflow','equity_fina_indicator')
) q;
SELECT json_build_object('section','support_relation_names','data',json_agg(q ORDER BY table_schema,table_name)) FROM (
 SELECT table_schema,table_name FROM information_schema.tables
 WHERE table_schema IN ('raw_tushare','core','core_serving') AND
 (table_name ~ '(dividend|forecast|express|trade_cal|stock_company|stock_basic|namechange|gdp|ppi|pmi|cpi|money_supply|shibor|cn_m|hk_basic|hk_daily|fina_mainbz|fina_audit|fina_main)' )
) q;
COMMIT;
