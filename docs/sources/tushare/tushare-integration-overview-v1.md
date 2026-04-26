# Tushare 已接入数据集总说明（历史快照）

> 状态：历史归档（2026-04-20 生成）。  
> 说明：本文保留当时的盘点快照，包含已删除的 V1 路径与实现命名，仅用于追溯。  
> 当前现行口径请优先参考：
>
> 1. [Tushare 请求执行口径 v1](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)
> 2. `src/foundation/services/sync_v2/runtime_registry.py`
> 3. [docs_index.csv](/Users/congming/github/goldenshare/docs/sources/tushare/docs_index.csv)

- 历史统计口径：旧 sync registry + 旧 ops 规格注册表 + `docs/sources/tushare/docs_index.csv`
- 快照生成时间：2026-04-20
- 快照范围：仅统计 **Tushare** 已接入数据集（不含 Biying）。

## 1. 总体统计

| 指标 | 数值 | 说明 |
| --- | ---: | --- |
| 已接入数据集数 | 54 | 以 `SYNC_SERVICE_REGISTRY` 为准 |
| 已匹配源文档数 | 54 | `api_name` 能映射到 `docs_index.csv` |
| 源文档待补数 | 0 | 当前未在 `docs_index.csv` 命中 |

### 1.1 按文档主题统计

| 主题 | 数据集数 |
| --- | ---: |
| ETF专题 | 4 |
| 指数专题 | 6 |
| 港股数据 | 1 |
| 美股数据 | 1 |
| 股票数据 | 42 |

### 1.2 按同步方式统计（可重叠）

| 同步方式 | 覆盖数据集数 |
| --- | ---: |
| backfill_by_date_range | 4 |
| backfill_by_month | 1 |
| backfill_by_trade_date | 22 |
| backfill_equity_series | 6 |
| backfill_fund_series | 2 |
| backfill_index_series | 5 |
| backfill_low_frequency | 2 |
| backfill_trade_cal | 1 |
| sync_daily | 37 |
| sync_history | 54 |

### 1.3 源文档待补清单

| resource | 接口api | 建议补充文档 |
| --- | --- | --- |
| 无 | 无 | 当前已全部命中 |

## 2. 数据集模板说明（统一口径）

每个数据集按同一模板汇总：

1. **接入信息**：`resource`、展示名、Tushare 接口、源文档。
2. **实现方式（历史）**：服务类（`Sync*Service`）+ 落库链路（`raw -> core/core_serving`）。
3. **同步能力**：`sync_daily` / `sync_history` / `backfill_*`。
4. **同步维度**：按交易日、按证券池、按日期区间、按月等。
5. **输入参数对照**：按 `daily/history/backfill` 三段展示。
6. **输出参数对照（历史）**：接口字段数 + 字段示例（完整字段以当时服务实现为准）。

## 3. 已接入数据集清单（模板化汇总）

| resource | 数据集 | Tushare接口 | 源文档 | 实现方式 | 落库链路 | 同步方式 | 同步维度 | 输入参数对照 | 输出参数对照 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `adj_factor` | 复权因子 | `adj_factor` | doc_id 28 / 股票数据/行情数据/0028_复权因子.md | `SyncAdjFactorService` | `raw_tushare.adj_factor -> core.equity_adj_factor` | `backfill_equity_series/sync_daily/sync_history` | 日增量/历史/全量/按证券池 | daily:trade_date；history:ts_code,start_date,end_date；backfill:backfill_equity_series:start_date,end_date,offset,limit | 3字段；示例:ts_code,trade_date,adj_factor |
| `block_trade` | 大宗交易 | `block_trade` | doc_id 161 / 股票数据/参考数据/0161_大宗交易.md | `SyncBlockTradeService` | `raw_tushare.block_trade -> core_serving.equity_block_trade` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date；history:start_date,end_date；backfill:backfill_by_trade_date:start_date,end_date,exchange,offset,limit | 7字段；示例:ts_code,trade_date,price,vol,amount,buyer |
| `broker_recommend` | 券商每月荐股 | `broker_recommend` | doc_id 267 / 股票数据/特色数据/0267_券商每月荐股.md | `SyncBrokerRecommendService` | `raw_tushare.broker_recommend -> core_serving.broker_recommend` | `backfill_by_month/sync_daily/sync_history` | 日增量/历史/全量/按月 | daily:month；history:-；backfill:backfill_by_month:start_month,end_month,offset,limit | 14字段；示例:month,currency,name,ts_code,trade_date,close |
| `cyq_perf` | 每日筹码及胜率 | `cyq_perf` | doc_id 293 / 股票数据/特色数据/0293_每日筹码及胜率.md | `SyncCyqPerfService` | `raw_tushare.cyq_perf -> core_serving.equity_cyq_perf` | `sync_daily/sync_history` | 日增量/历史/全量 | daily:trade_date,ts_code；history:trade_date,start_date,end_date,ts_code；backfill:- | 11字段；示例:ts_code,trade_date,his_low,his_high,cost_5pct,cost_15pct |
| `daily` | 股票日线 | `daily` | doc_id 27 / 股票数据/行情数据/0027_A股日线行情.md | `SyncEquityDailyService` | `raw_tushare.daily -> core_serving.equity_daily_bar` | `backfill_equity_series/sync_daily/sync_history` | 日增量/历史/全量/按证券池 | daily:trade_date；history:ts_code,start_date,end_date；backfill:backfill_equity_series:start_date,end_date,offset,limit | 11字段；示例:ts_code,trade_date,open,high,low,close |
| `daily_basic` | 股票日指标 | `daily_basic` | doc_id 32 / 股票数据/行情数据/0032_每日指标.md | `SyncDailyBasicService` | `raw_tushare.daily_basic -> core_serving.equity_daily_basic` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date；history:start_date,end_date；backfill:backfill_by_trade_date:start_date,end_date,exchange,offset,limit | 18字段；示例:ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio |
| `dc_daily` | 东方财富板块行情 | `dc_daily` | doc_id 382 / 股票数据/打板专题数据/0382_东财概念板块行情.md | `SyncDcDailyService` | `raw_tushare.dc_daily -> core_serving.dc_daily` | `backfill_by_date_range/sync_daily/sync_history` | 日增量/历史/全量/按日期区间 | daily:trade_date,ts_code,idx_type；history:ts_code,start_date,end_date,idx_type；backfill:backfill_by_date_range:start_date,end_date,ts_code,idx_type | 12字段；示例:ts_code,trade_date,close,open,high,low |
| `dc_hot` | 东方财富热榜 | `dc_hot` | doc_id 321 / 股票数据/打板专题数据/0321_东方财富热榜.md | `SyncDcHotService` | `raw_tushare.dc_hot -> core_serving.dc_hot` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code,market,hot_type,is_new；history:trade_date,start_date,end_date,ts_code,market,hot_type,is_new；backfill:backfill_by_trade_date:start_date,end_date,ts_code,market,hot_type,is_new,offset,limit | 8字段；示例:trade_date,data_type,ts_code,ts_name,rank,pct_change |
| `dc_index` | 东方财富概念板块 | `dc_index` | doc_id 362 / 股票数据/打板专题数据/0362_东方财富概念板块.md | `SyncDcIndexService` | `raw_tushare.dc_index -> core_serving.dc_index` | `backfill_by_date_range/sync_daily/sync_history` | 日增量/历史/全量/按日期区间 | daily:trade_date,ts_code,idx_type；history:ts_code,start_date,end_date,idx_type；backfill:backfill_by_date_range:start_date,end_date,ts_code,idx_type | 13字段；示例:ts_code,trade_date,name,leading,leading_code,pct_change |
| `dc_member` | 东方财富板块成分 | `dc_member` | doc_id 363 / 股票数据/打板专题数据/0363_东方财富板块成分.md | `SyncDcMemberService` | `raw_tushare.dc_member -> core_serving.dc_member` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code,con_code；history:trade_date,ts_code,con_code；backfill:backfill_by_trade_date:start_date,end_date,ts_code,con_code | 4字段；示例:trade_date,ts_code,con_code,name |
| `dividend` | 分红送转 | `dividend` | doc_id 103 / 股票数据/财务数据/0103_分红送股.md | `SyncDividendService` | `raw_tushare.dividend -> core_serving.equity_dividend` | `backfill_low_frequency/sync_history` | 历史/全量/低频按股票池 | daily:-；history:ts_code；backfill:backfill_low_frequency:offset,limit | 16字段；示例:ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate |
| `etf_basic` | ETF 基本信息 | `etf_basic` | doc_id 385 / ETF专题/0385_ETF基础信息.md | `SyncEtfBasicService` | `raw_tushare.etf_basic -> core_serving.etf_basic` | `sync_history` | 历史/全量 | daily:-；history:list_status,exchange；backfill:- | 14字段；示例:ts_code,csname,extname,cname,index_code,index_name |
| `etf_index` | ETF 基准指数列表 | `etf_index` | doc_id 386 / ETF专题/0386_ETF基准指数列表.md | `SyncEtfIndexService` | `raw_tushare.etf_index -> core_serving.etf_index` | `sync_history` | 历史/全量 | daily:-；history:-；backfill:- | 8字段；示例:ts_code,indx_name,indx_csname,pub_party_name,pub_date,base_date |
| `fund_adj` | 基金复权因子 | `fund_adj` | doc_id 199 / ETF专题/0199_基金复权因子.md | `SyncFundAdjService` | `raw_tushare.fund_adj -> core.fund_adj_factor` | `backfill_fund_series/sync_daily/sync_history` | 日增量/历史/全量/按基金池 | daily:trade_date；history:start_date,end_date；backfill:backfill_fund_series:start_date,end_date,offset,limit | 3字段；示例:ts_code,trade_date,adj_factor |
| `fund_daily` | 基金日线 | `fund_daily` | doc_id 127 / ETF专题/0127_ETF日线行情.md | `SyncFundDailyService` | `raw_tushare.fund_daily -> core_serving.fund_daily_bar` | `backfill_fund_series/sync_daily/sync_history` | 日增量/历史/全量/按基金池 | daily:trade_date；history:start_date,end_date；backfill:backfill_fund_series:start_date,end_date,offset,limit | 11字段；示例:ts_code,trade_date,open,high,low,close |
| `hk_basic` | 港股列表 | `hk_basic` | doc_id 191 / 港股数据/0191_港股列表.md | `SyncHkBasicService` | `raw_tushare.hk_basic -> core_serving.hk_security` | `sync_history` | 历史/全量 | daily:-；history:list_status；backfill:- | 12字段；示例:ts_code,name,fullname,enname,cn_spell,market |
| `index_basic` | 指数主数据 | `index_basic` | doc_id 94 / 指数专题/0094_指数基本信息.md | `SyncIndexBasicService` | `raw_tushare.index_basic -> core_serving.index_basic` | `sync_history` | 历史/全量 | daily:-；history:-；backfill:- | 13字段；示例:ts_code,name,fullname,market,publisher,index_type |
| `index_daily` | 指数日线 | `index_daily` | doc_id 95 / 指数专题/0095_指数日线行情.md | `SyncIndexDailyService` | `raw_tushare.index_daily -> core_serving.index_daily_serving` | `backfill_index_series/sync_daily/sync_history` | 日增量/历史/全量/按指数池 | daily:trade_date；history:ts_code,start_date,end_date；backfill:backfill_index_series:start_date,end_date,offset,limit | 11字段；示例:ts_code,trade_date,open,high,low,close |
| `index_daily_basic` | 指数日指标 | `index_dailybasic` | doc_id 128 / 指数专题/0128_大盘指数每日指标.md | `SyncIndexDailyBasicService` | `raw_tushare.index_daily_basic -> core_serving.index_daily_basic` | `backfill_index_series/sync_history` | 历史/全量/按指数池 | daily:-；history:ts_code,start_date,end_date；backfill:backfill_index_series:start_date,end_date,offset,limit | 12字段；示例:ts_code,trade_date,total_mv,float_mv,total_share,float_share |
| `index_monthly` | 指数月线 | `index_monthly` | doc_id 172 / 指数专题/0172_指数月线行情.md | `SyncIndexMonthlyService` | `raw_tushare.index_monthly_bar -> core_serving.index_monthly_serving` | `backfill_index_series/sync_history` | 历史/全量/按指数池 | daily:-；history:ts_code,start_date,end_date；backfill:backfill_index_series:start_date,end_date,offset,limit | 11字段；示例:ts_code,trade_date,close,open,high,low |
| `index_weekly` | 指数周线 | `index_weekly` | doc_id 171 / 指数专题/0171_指数周线行情.md | `SyncIndexWeeklyService` | `raw_tushare.index_weekly_bar -> core_serving.index_weekly_serving` | `backfill_index_series/sync_history` | 历史/全量/按指数池 | daily:-；history:ts_code,start_date,end_date；backfill:backfill_index_series:start_date,end_date,offset,limit | 11字段；示例:ts_code,trade_date,close,open,high,low |
| `index_weight` | 指数成分权重 | `index_weight` | doc_id 96 / 指数专题/0096_指数成分和权重.md | `SyncIndexWeightService` | `raw_tushare.index_weight -> core_serving.index_weight` | `backfill_index_series/sync_history` | 历史/全量/按指数池 | daily:-；history:index_code,start_date,end_date；backfill:backfill_index_series:start_date,end_date,offset,limit | 4字段；示例:index_code,con_code,trade_date,weight |
| `kpl_concept_cons` | 开盘啦题材成分 | `kpl_concept_cons` | doc_id 351 / 股票数据/打板专题数据/0351_开盘啦题材成分.md | `SyncKplConceptConsService` | `raw_tushare.kpl_concept_cons -> core_serving.kpl_concept_cons` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code,con_code；history:trade_date,ts_code,con_code；backfill:backfill_by_trade_date:start_date,end_date,exchange,ts_code,con_code,offset,limit | 8字段；示例:ts_code,name,con_name,con_code,trade_date,desc |
| `kpl_list` | 开盘啦榜单 | `kpl_list` | doc_id 347 / 股票数据/打板专题数据/0347_开盘啦榜单数据.md | `SyncKplListService` | `raw_tushare.kpl_list -> core_serving.kpl_list` | `backfill_by_date_range/sync_daily/sync_history` | 日增量/历史/全量/按日期区间 | daily:trade_date,tag；history:trade_date,start_date,end_date,tag；backfill:backfill_by_date_range:start_date,end_date,tag,trade_date | 24字段；示例:ts_code,name,trade_date,lu_time,ld_time,open_time |
| `limit_cpt_list` | 最强板块统计 | `limit_cpt_list` | doc_id 357 / 股票数据/打板专题数据/0357_最强板块统计.md | `SyncLimitCptListService` | `raw_tushare.limit_cpt_list -> core_serving.limit_cpt_list` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date；history:trade_date,start_date,end_date；backfill:backfill_by_trade_date:start_date,end_date,offset,limit | 9字段；示例:ts_code,name,trade_date,days,up_stat,cons_nums |
| `limit_list_d` | 涨跌停榜 | `limit_list_d` | doc_id 298 / 股票数据/打板专题数据/0298_涨跌停列表（新）.md | `SyncLimitListService` | `raw_tushare.limit_list -> core_serving.equity_limit_list` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,limit_type,exchange；history:trade_date,start_date,end_date,limit_type,exchange；backfill:backfill_by_trade_date:start_date,end_date,limit_type,exchange,offset,limit | 18字段；示例:trade_date,ts_code,industry,name,close,pct_chg |
| `limit_list_ths` | 同花顺涨跌停榜单 | `limit_list_ths` | doc_id 355 / 股票数据/打板专题数据/0355_涨跌停榜单（同花顺）.md | `SyncLimitListThsService` | `raw_tushare.limit_list_ths -> core_serving.limit_list_ths` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,limit_type,market；history:trade_date,start_date,end_date,limit_type,market；backfill:backfill_by_trade_date:start_date,end_date,limit_type,market,offset,limit | 24字段；示例:trade_date,ts_code,name,price,pct_chg,open_num |
| `limit_step` | 涨停天梯 | `limit_step` | doc_id 356 / 股票数据/打板专题数据/0356_连板天梯.md | `SyncLimitStepService` | `raw_tushare.limit_step -> core_serving.limit_step` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date；history:trade_date,start_date,end_date；backfill:backfill_by_trade_date:start_date,end_date,offset,limit | 4字段；示例:ts_code,name,trade_date,nums |
| `margin` | 融资融券交易汇总 | `margin` | doc_id 58 / 股票数据/两融及转融通/0058_融资融券交易汇总.md | `SyncMarginService` | `raw_tushare.margin -> core_serving.equity_margin` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,exchange_id；history:trade_date,start_date,end_date,exchange_id；backfill:backfill_by_trade_date:start_date,end_date,exchange_id,offset,limit | 9字段；示例:trade_date,exchange_id,rzye,rzmre,rzche,rqye |
| `moneyflow` | 资金流向（基础） | `moneyflow` | doc_id 170 / 股票数据/资金流向数据/0170_个股资金流向.md | `SyncMoneyflowService` | `raw_tushare.moneyflow -> core_serving.equity_moneyflow` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date；history:start_date,end_date；backfill:backfill_by_trade_date:start_date,end_date,exchange,offset,limit | 20字段；示例:ts_code,trade_date,buy_sm_vol,buy_sm_amount,sell_sm_vol,sell_sm_amount |
| `moneyflow_cnt_ths` | 概念板块资金流向（同花顺） | `moneyflow_cnt_ths` | doc_id 371 / 股票数据/资金流向数据/0371_同花顺概念板块资金流向（THS）.md | `SyncMoneyflowCntThsService` | `raw_tushare.moneyflow_cnt_ths -> core_serving.concept_moneyflow_ths` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code；history:trade_date,start_date,end_date,ts_code；backfill:backfill_by_trade_date:start_date,end_date,ts_code,offset,limit | 12字段；示例:trade_date,ts_code,name,lead_stock,close_price,pct_change |
| `moneyflow_dc` | 个股资金流向（东方财富） | `moneyflow_dc` | doc_id 349 / 股票数据/资金流向数据/0349_个股资金流向（DC）.md | `SyncMoneyflowDcService` | `raw_tushare.moneyflow_dc -> core_serving.equity_moneyflow_dc` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code；history:trade_date,start_date,end_date,ts_code；backfill:backfill_by_trade_date:start_date,end_date,ts_code,offset,limit | 15字段；示例:trade_date,ts_code,name,pct_change,close,net_amount |
| `moneyflow_ind_dc` | 板块资金流向（东方财富） | `moneyflow_ind_dc` | doc_id 344 / 股票数据/资金流向数据/0344_东财概念及行业板块资金流向（DC）.md | `SyncMoneyflowIndDcService` | `raw_tushare.moneyflow_ind_dc -> core_serving.board_moneyflow_dc` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code,content_type；history:trade_date,start_date,end_date,ts_code,content_type；backfill:backfill_by_trade_date:start_date,end_date,ts_code,content_type,offset,limit | 18字段；示例:trade_date,content_type,ts_code,name,pct_change,close |
| `moneyflow_ind_ths` | 行业资金流向（同花顺） | `moneyflow_ind_ths` | doc_id 343 / 股票数据/资金流向数据/0343_同花顺行业资金流向（THS）.md | `SyncMoneyflowIndThsService` | `raw_tushare.moneyflow_ind_ths -> core_serving.industry_moneyflow_ths` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code；history:trade_date,start_date,end_date,ts_code；backfill:backfill_by_trade_date:start_date,end_date,ts_code,offset,limit | 12字段；示例:trade_date,ts_code,industry,lead_stock,close,pct_change |
| `moneyflow_mkt_dc` | 市场资金流向（东方财富） | `moneyflow_mkt_dc` | doc_id 345 / 股票数据/资金流向数据/0345_大盘资金流向（DC）.md | `SyncMoneyflowMktDcService` | `raw_tushare.moneyflow_mkt_dc -> core_serving.market_moneyflow_dc` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date；history:trade_date,start_date,end_date；backfill:backfill_by_trade_date:start_date,end_date,offset,limit | 15字段；示例:trade_date,close_sh,pct_change_sh,close_sz,pct_change_sz,net_amount |
| `moneyflow_ths` | 个股资金流向（同花顺） | `moneyflow_ths` | doc_id 348 / 股票数据/资金流向数据/0348_个股资金流向（THS）.md | `SyncMoneyflowThsService` | `raw_tushare.moneyflow_ths -> core_serving.equity_moneyflow_ths` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code；history:trade_date,start_date,end_date,ts_code；backfill:backfill_by_trade_date:start_date,end_date,ts_code,offset,limit | 13字段；示例:trade_date,ts_code,name,pct_change,latest,net_amount |
| `stk_factor_pro` | 股票技术面因子(专业版) | `stk_factor_pro` | doc_id 328 / 股票数据/特色数据/0328_股票技术面因子(专业版).md | `SyncStkFactorProService` | `raw_tushare.stk_factor_pro -> core_serving.equity_factor_pro` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code；history:trade_date,start_date,end_date,ts_code；backfill:backfill_by_trade_date:start_date,end_date,ts_code,offset,limit | 227字段；示例:ts_code,trade_date,close_bfq,open_bfq,high_bfq,low_bfq |
| `stk_holdernumber` | 股东户数 | `stk_holdernumber` | doc_id 166 / 股票数据/参考数据/0166_股东人数.md | `SyncHolderNumberService` | `raw_tushare.holdernumber -> core_serving.equity_holder_number` | `backfill_low_frequency/sync_history` | 历史/全量/低频按股票池 | daily:-；history:ts_code；backfill:backfill_low_frequency:offset,limit | 4字段；示例:ts_code,ann_date,end_date,holder_num |
| `stk_limit` | 每日涨跌停价格 | `stk_limit` | doc_id 183 / 股票数据/行情数据/0183_每日涨跌停价格.md | `SyncStkLimitService` | `raw_tushare.stk_limit -> core_serving.equity_stk_limit` | `sync_daily/sync_history` | 日增量/历史/全量 | daily:trade_date,ts_code；history:trade_date,start_date,end_date,ts_code；backfill:- | 5字段；示例:trade_date,ts_code,pre_close,up_limit,down_limit |
| `stk_nineturn` | 神奇九转指标 | `stk_nineturn` | doc_id 364 / 股票数据/特色数据/0364_神奇九转指标.md | `SyncStkNineTurnService` | `raw_tushare.stk_nineturn -> core_serving.equity_nineturn` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code；history:trade_date,start_date,end_date,ts_code；backfill:backfill_by_trade_date:start_date,end_date,offset,limit | 13字段；示例:ts_code,trade_date,freq,open,high,low |
| `stk_period_bar_adj_month` | 股票复权月线 | `stk_week_month_adj` | doc_id 365 / 股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md | `SyncStkPeriodBarAdjMonthService` | `raw_tushare.stk_period_bar_adj -> core_serving.stk_period_bar_adj` | `backfill_equity_series/sync_daily/sync_history` | 日增量/历史/全量/按证券池 | daily:trade_date；history:ts_code,start_date,end_date；backfill:backfill_equity_series:start_date,end_date,offset,limit | 21字段；示例:ts_code,trade_date,end_date,freq,open,high |
| `stk_period_bar_adj_week` | 股票复权周线 | `stk_week_month_adj` | doc_id 365 / 股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md | `SyncStkPeriodBarAdjWeekService` | `raw_tushare.stk_period_bar_adj -> core_serving.stk_period_bar_adj` | `backfill_equity_series/sync_history` | 历史/全量/按证券池 | daily:-；history:ts_code,start_date,end_date；backfill:backfill_equity_series:start_date,end_date,offset,limit | 21字段；示例:ts_code,trade_date,end_date,freq,open,high |
| `stk_period_bar_month` | 股票月线 | `stk_weekly_monthly` | doc_id 336 / 股票数据/行情数据/0336_股票周_月线行情(每日更新).md | `SyncStkPeriodBarMonthService` | `raw_tushare.stk_period_bar -> core_serving.stk_period_bar` | `backfill_equity_series/sync_daily/sync_history` | 日增量/历史/全量/按证券池 | daily:trade_date；history:ts_code,start_date,end_date；backfill:backfill_equity_series:start_date,end_date,offset,limit | 13字段；示例:ts_code,trade_date,end_date,freq,open,high |
| `stk_period_bar_week` | 股票周线 | `stk_weekly_monthly` | doc_id 336 / 股票数据/行情数据/0336_股票周_月线行情(每日更新).md | `SyncStkPeriodBarWeekService` | `raw_tushare.stk_period_bar -> core_serving.stk_period_bar` | `backfill_equity_series/sync_history` | 历史/全量/按证券池 | daily:-；history:ts_code,start_date,end_date；backfill:backfill_equity_series:start_date,end_date,offset,limit | 13字段；示例:ts_code,trade_date,end_date,freq,open,high |
| `stock_basic` | 股票主数据 | `stock_basic` | doc_id 25 / 股票数据/基础数据/0025_基础信息.md | `SyncStockBasicService` | `raw_tushare.stock_basic -> core_serving.security_serving` | `sync_history` | 历史/全量 | daily:-；history:source_key；backfill:- | 17字段；示例:ts_code,symbol,name,area,industry,fullname |
| `stock_st` | ST股票列表 | `stock_st` | doc_id 397 / 股票数据/基础数据/0397_ST股票列表.md | `SyncStockStService` | `raw_tushare.stock_st -> core_serving.equity_stock_st` | `sync_daily/sync_history` | 日增量/历史/全量 | daily:trade_date,ts_code；history:trade_date,start_date,end_date,ts_code；backfill:- | 5字段；示例:ts_code,name,trade_date,type,type_name |
| `suspend_d` | 每日停复牌信息 | `suspend_d` | doc_id 214 / 股票数据/行情数据/0214_每日停复牌信息.md | `SyncSuspendDService` | `raw_tushare.suspend_d -> core_serving.equity_suspend_d` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code,suspend_type；history:trade_date,start_date,end_date,ts_code,suspend_type；backfill:backfill_by_trade_date:start_date,end_date,ts_code,suspend_type,offset,limit | 4字段；示例:ts_code,trade_date,suspend_timing,suspend_type |
| `ths_daily` | 同花顺板块行情 | `ths_daily` | doc_id 260 / 股票数据/打板专题数据/0260_同花顺板块指数行情.md | `SyncThsDailyService` | `raw_tushare.ths_daily -> core_serving.ths_daily` | `backfill_by_date_range/sync_daily/sync_history` | 日增量/历史/全量/按日期区间 | daily:trade_date,ts_code；history:-；backfill:backfill_by_date_range:start_date,end_date,ts_code | 14字段；示例:ts_code,trade_date,close,open,high,low |
| `ths_hot` | 同花顺热榜 | `ths_hot` | doc_id 320 / 股票数据/打板专题数据/0320_同花顺热榜.md | `SyncThsHotService` | `raw_tushare.ths_hot -> core_serving.ths_hot` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date,ts_code,market,is_new；history:trade_date,start_date,end_date,ts_code,market,is_new；backfill:backfill_by_trade_date:start_date,end_date,exchange,ts_code,market,is_new,offset,limit | 11字段；示例:trade_date,data_type,ts_code,ts_name,rank,pct_change |
| `ths_index` | 同花顺概念和行业指数 | `ths_index` | doc_id 259 / 股票数据/打板专题数据/0259_同花顺概念和行业指数.md | `SyncThsIndexService` | `raw_tushare.ths_index -> core_serving.ths_index` | `sync_history` | 历史/全量 | daily:-；history:ts_code,exchange,type；backfill:- | 6字段；示例:ts_code,name,count,exchange,list_date,type |
| `ths_member` | 同花顺板块成分 | `ths_member` | doc_id 261 / 股票数据/打板专题数据/0261_同花顺概念板块成分.md | `SyncThsMemberService` | `raw_tushare.ths_member -> core_serving.ths_member` | `sync_history` | 历史/全量 | daily:-；history:ts_code,con_code；backfill:- | 7字段；示例:ts_code,con_code,con_name,weight,in_date,out_date |
| `top_list` | 龙虎榜 | `top_list` | doc_id 106 / 股票数据/打板专题数据/0106_龙虎榜每日明细.md | `SyncTopListService` | `raw_tushare.top_list -> core_serving.equity_top_list` | `backfill_by_trade_date/sync_daily/sync_history` | 日增量/历史/全量/按交易日 | daily:trade_date；history:start_date,end_date；backfill:backfill_by_trade_date:start_date,end_date,exchange,offset,limit | 15字段；示例:trade_date,ts_code,name,close,pct_change,turnover_rate |
| `trade_cal` | 交易日历 | `trade_cal` | doc_id 26 / 股票数据/基础数据/0026_交易日历.md | `SyncTradeCalendarService` | `raw_tushare.trade_cal -> core_serving.trade_calendar` | `backfill_trade_cal/sync_history` | 历史/全量/交易日历回补 | daily:-；history:start_date,end_date,exchange；backfill:backfill_trade_cal:start_date,end_date,exchange | 4字段；示例:exchange,cal_date,is_open,pretrade_date |
| `us_basic` | 美股列表 | `us_basic` | doc_id 252 / 美股数据/0252_美股列表.md | `SyncUsBasicService` | `raw_tushare.us_basic -> core_serving.us_security` | `sync_history` | 历史/全量 | daily:-；history:classify；backfill:- | 6字段；示例:ts_code,name,enname,classify,list_date,delist_date |
