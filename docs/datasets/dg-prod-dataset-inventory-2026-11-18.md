# DG 与 Prod 数据集对照表

**盘点日期：2026-11-18（北京时间）。** 本表用于让业务沟通与工程代码指向同一个数据集。中文名是本次统一命名建议，英文标识沿用现有数据集键；同一业务数据集在 DG 的多个层、频率以及 Prod 的多个表放在一行。

共 **130 个业务数据集**，其中 **40 个两边登记、19 个 DG 登记、71 个 Prod 登记**。盘点覆盖当前 94 个 Prod 数据源定义、17 个 Prod 业务产出定义和 187 个 DG 资产定义。DG 健康检查资产、代码种子、发布控制表、任务和状态表、PostgreSQL 子分区不计为业务数据集。

## 1. 如何读这张表

- **周期**指业务粒度或日期锚点。分钟 K 线的粒度以分钟表示，批量维护按交易日。股票周/月线以自然周五/自然月末为锚，指数周/月线以该周期最后开市日为锚。[日期模型消费指南](../architecture/dataset-date-model-consumer-guide-v1.md#period-anchors)
- **DG 起点**按层、频率列最早核实的非空业务分区或全量文件页脚日期。按股票与年份存放的资产仅列抽取股票的日期。快照通常没有统一的历史起点。总表 Lake 路径相对 `/Volumes/datasource/data_lake`，文件名、资产键和频率取值见 DG 明细。
- **Prod 起点**是注明表和过滤条件下，业务日期索引返回的第一条非空值。原始、标准、服务层各有自己的覆盖范围；查询选了哪个表就只代表哪个表。无合适索引或连接未接通的项目标为“未核实”。
- **两边登记**表示两边可找到对应的存储登记。股票涨跌幅分布在 Prod 使用发布表中的分桶字段。覆盖范围、股票与指数池、复权规则、发布状态及更新完整性仍以具体合同和对应表为准。路径或配置中写着某个日期，单独标为历史目标或合同下限。

## 2. 业务数据集总表

### 基础主数据

| 统一中文名 | 英文标识 | 目录覆盖 | 来源 | DG 周期 | DG 位置 | DG 起点 | Prod 周期 | Prod 主表或视图 | Prod 起点和依据表 | 口径说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 股票历史基础列表 | `bak_basic` | Prod | Tushare | — | — | — | 交易日 | `core_serving_light.bak_basic` | 2016-08-09 `raw_tushare.bak_basic` | — |
| 北交所新旧代码对照 | `bse_mapping` | Prod | Tushare | — | — | — | 全量快照 | `core_serving_light.bse_mapping` | 快照 | — |
| ETF 基础信息 | `etf_basic` | DG + Prod | Tushare | 全量快照 | Raw `raw/tushare/etf_basic/snapshot_id={snapshot_id}/`<br>Silver `silver/basic/etf_basic/snapshot_id={snapshot_id}/` | 快照 | 全量快照 | `core_serving.etf_basic` | 快照 | — |
| 港股基础信息 | `hk_basic` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.hk_security` | 快照 | — |
| 股票曾用名 | `namechange` | DG + Prod | Tushare | 全量快照 | Raw `raw/tushare/namechange/full/`<br>Silver `silver/basic/namechange/full/` | 快照 | 全量快照 | `core_serving_light.namechange` | 快照 | 全量曾用名区间快照，单条记录的生效日与更新快照的动作时间不同。 |
| ST 风险警示事件 | `st` | Prod | Tushare | — | — | — | 全量快照 | `core_serving_light.st` | 快照 | — |
| 股票主数据 | `stock_basic` | DG + Prod | BIYING、Tushare | 全量快照 | Raw `raw/tushare/stock_basic/full/`<br>Silver `silver/basic/stock_basic/full/` | 快照 | 全量快照 | `core_serving.security_serving` | 快照 | Prod 含 Tushare、BIYING 两源及合并输出。DG 登记 Tushare 路径和标准化文件。股票生命周期和股票身份映射有独立对象口径。 |
| 上市公司基本信息 | `stock_company` | Prod | Tushare | — | — | — | 全量快照 | `core_serving_light.stock_company` | 快照 | — |
| 股票身份映射 | `stock_identity_map` | DG | 派生计算 | 全量快照 | Silver `silver/basic/stock_identity_map/` | 快照 | — | — | — | — |
| 股票生命周期 | `stock_lifecycle` | DG | 派生计算 | 全量快照 | Silver `silver/basic/stock_lifecycle/full/` | 快照 | — | — | — | — |
| 股票历史确认全日停牌事实 | `stock_suspend_confirmed` | DG | 参考数据 | 全量快照 | Silver `silver/quote/stock_suspend_confirmed/full/` | Silver 2014-01-02 | — | — | — | — |
| 交易日历 | `trade_cal` | DG + Prod | Tushare | 日历日（全量文件） | Raw `raw/tushare/trade_calendar/full/`<br>Silver `silver/calendar/trade_calendar/full/` | Raw 1990-12-19<br>Silver 1990-12-19 | 自然日 | `core_serving.trade_calendar` | 1990-12-19 `core_serving.trade_calendar` | 日历日期包含休市日和未来日历。DG Raw 日期字段 cal_date，Silver 与 Prod 业务表用 trade_date。 |
| 美股基础信息 | `us_basic` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.us_security` | 快照 | — |

### 股票行情

| 统一中文名 | 英文标识 | 目录覆盖 | 来源 | DG 周期 | DG 位置 | DG 起点 | Prod 周期 | Prod 主表或视图 | Prod 起点和依据表 | 口径说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 股票复权因子 | `adj_factor` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/adj_factor/trade_date={partition_key}/`<br>Silver `silver/quote/adj_factor/trade_date={partition_key}/` | Raw 2009-01-05<br>Silver 2009-01-05 | 交易日 | `core.equity_adj_factor` | 2009-01-05 `core.equity_adj_factor` | 供股票价格复权使用。与股票日线技术因子分开。 |
| BIYING 股票日线行情 | `biying_equity_daily` | Prod | BIYING | — | — | — | 交易日 | `raw_biying.equity_daily_bar` | 2025-01-02 `raw_biying.equity_daily_bar` | 当前存储目标为 `raw_biying.equity_daily_bar`。定义中的 `raw_biying.equity_daily` 未在 Prod 找到。 |
| 大宗交易 | `block_trade` | Prod | Tushare | — | — | — | 交易日 | `core_serving.equity_block_trade` | 2010-01-04 `core_serving.equity_block_trade` | — |
| 券商月度金股推荐 | `broker_recommend` | Prod | Tushare | — | — | — | 月（月份键） | `core_serving.broker_recommend` | 2024-01 `core_serving.broker_recommend` | — |
| 每日筹码分布 | `cyq_chips` | Prod | Tushare | — | — | — | 交易日 | `raw_tushare.cyq_chips` | 2018-01-02 `raw_tushare.cyq_chips` | — |
| 每日筹码及胜率 | `cyq_perf` | Prod | Tushare | — | — | — | 交易日 | `raw_tushare.cyq_perf` | 2018-01-02 `raw_tushare.cyq_perf` | — |
| 股票日线行情 | `daily` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/stock_daily/trade_date={partition_key}/`<br>Silver `silver/quote/stock_daily/trade_date={partition_key}/` | Raw 2014-01-02<br>Silver 2014-01-02 | 交易日 | `core_serving.equity_daily_bar` | 1990-12-19 `core_serving.equity_daily_bar` | DG 与 Tushare 链路对应。Prod 另有 BIYING 股票日线来源和独立存储，分别可查。前复权股票日线单列。 |
| 股票每日指标 | `daily_basic` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/daily_basic/trade_date={partition_key}/` | Raw 2010-01-04 | 交易日 | `core_serving.equity_daily_basic` | 2010-01-04 `core_serving.equity_daily_basic` | 源数据集为 daily_basic。与指数每日指标、股票日线技术因子、收盘涨跌停价格分别登记。 |
| 股票日线数据集市快照 | `equity_daily_snapshot` | Prod | 派生计算 | — | — | — | 当前快照 | `dm.equity_daily_snapshot` | 快照 | — |
| 涨停概念列表 | `limit_cpt_list` | Prod | Tushare | — | — | — | 交易日 | `core_serving.limit_cpt_list` | 2023-11-13 `core_serving.limit_cpt_list` | — |
| 每日涨跌停名单 | `limit_list_d` | Prod | Tushare | — | — | — | 交易日 | `core_serving.equity_limit_list` | 2020-01-02 `core_serving.equity_limit_list` | — |
| 同花顺涨停名单 | `limit_list_ths` | Prod | Tushare | — | — | — | 交易日 | `core_serving.limit_list_ths` | 2023-11-01 `core_serving.limit_list_ths` | — |
| 连板梯队 | `limit_step` | Prod | Tushare | — | — | — | 交易日 | `core_serving.limit_step` | 2023-11-13 `core_serving.limit_step` | — |
| 融资融券汇总 | `margin` | Prod | Tushare | — | — | — | 交易日 | `raw_tushare.margin` | 2025-01-02 `raw_tushare.margin` | — |
| 融资融券交易明细 | `margin_detail` | Prod | Tushare | — | — | — | 交易日 | `core_serving.equity_margin_detail` | 未核实 | — |
| 券商研究报告 | `research_report` | Prod | Tushare | — | — | — | 报告日期（按自然日维护） | `core_serving_light.research_report` | 2020-01-01 `raw_tushare.research_report` | — |
| 股票收盘集合竞价 | `stk_auction_c` | Prod | Tushare | — | — | — | 交易日 | `raw_tushare.stk_auction_c` | 2025-01-02 `raw_tushare.stk_auction_c` | — |
| 股票开盘集合竞价 | `stk_auction_o` | Prod | Tushare | — | — | — | 交易日 | `raw_tushare.stk_auction_o` | 2025-01-02 `raw_tushare.stk_auction_o` | — |
| 股票日线技术因子（专业版） | `stk_factor_pro` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/stk_factor_pro/trade_date={partition_key}/`<br>Silver `silver/stock_factor_pro/trade_date={partition_key}/` | Raw 2017-01-03<br>Silver 2017-01-03 | 交易日 | `core_serving.equity_factor_pro` | 2017-01-03 `raw_tushare.stk_factor_pro` | DG Silver 对应 stock_factor_pro。表列技术因子行情与股票复权因子是两套字段。 |
| 股票每日涨跌停价格 | `stk_limit` | Prod | Tushare | — | — | — | 交易日 | `raw_tushare.stk_limit` | 2024-01-02 `raw_tushare.stk_limit` | — |
| 股票分钟线行情（未复权） | `stk_mins` | DG + Prod | Tushare | 1/5/15/30/60 分钟 | Raw `raw/tushare/stk_mins/freq={频率}/trade_date={partition_key}/`<br>Silver `silver/quote/stk_mins/freq={频率}/trade_date={partition_key}/` | Raw 2009-01-05<br>Silver 2014-01-02 | 1/5/15/30/60 分钟 | `core_serving.equity_minute_bar`<br>`raw_tushare.stk_mins` | 未核实 | DG Raw 与 Silver 的历史起点分别登记为 2009-01-05、2014-01-01。Prod 按分钟记录 trade_time；分钟频率和按交易日维护是不同属性。 |
| 股票分钟线行情（前复权） | `stk_mins_qfq` | DG | 派生计算 | 1/5/15/30/60/90/120 分钟 | Gold `gold/quote/stk_mins_qfq/freq={频率}/ts_code={ts_code}/year={year}/` | Gold 2014-01-02（样本） | — | — | — | DG 历史下限为 2014-01-01。按股票与年份存储；表中日期只对应抽取的股票年度文件。 |
| 股票前复权分钟线 MACD/KDJ | `stk_mins_qfq_macd_kdj` | DG | 派生计算 | 1/5/15/30/60/90/120 分钟 | Gold `gold/indicator/stk_mins_qfq_macd_kdj/freq={频率}/ts_code={ts_code}/year={year}/` | Gold 2014-01-02（样本） | — | — | — | 按股票与年份存储；表中日期只对应抽取的股票年度文件。日切计算状态另有资产。 |
| 股票前复权分钟线 MACD/KDJ 计算状态 | `stk_mins_qfq_macd_kdj_state` | DG | 派生计算 | 1/5/15/30/60/90/120 分钟 | Gold `gold/indicator/stk_mins_qfq_macd_kdj_state/freq={频率}/trade_date={partition_key}/` | Gold 2014-01-02 | — | — | — | — |
| 股票前复权分钟线神奇九转（自算） | `stk_mins_qfq_nineturn` | DG | 派生计算 | 30/60/90/120 分钟 | Gold `gold/indicator/stk_mins_qfq_nineturn/freq={频率}/trade_date={partition_key}/` | Gold 2014-01-02 | — | — | — | — |
| 股票日线神奇九转（Tushare） | `stk_nineturn` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/stk_nineturn/trade_date={partition_key}/`<br>Silver `silver/quote/stock_nineturn_daily/trade_date={partition_key}/` | Raw 2023-01-03<br>Silver 2023-01-03 | 交易日 | `raw_tushare.stk_nineturn` | 2023-01-03 `raw_tushare.stk_nineturn` | DG Silver 对应 stock_nineturn_daily。自算前复权日线九转单列。 |
| 股票月线行情（含复权） | `stk_period_bar_adj_month` | DG + Prod | Tushare | 月（自然月末） | Raw `raw/tushare/stk_period_bar_adj_month/month={partition_key}/`<br>Silver `silver/quote/stock_monthly/month={partition_key}/` | Raw 1990-12<br>Silver 2014-01 | 月（自然月末） | `core_serving.stk_period_bar_adj`，`freq=month` | 1997-05-31（freq=month） `core_serving.stk_period_bar_adj` | DG Raw 与 Prod 对应 stk_week_month_adj；含未复权、前复权和后复权价格。Prod 用 freq=month，DG Silver 独立存储。 |
| 股票周线行情（含复权） | `stk_period_bar_adj_week` | DG + Prod | Tushare | 周（自然周五） | Raw `raw/tushare/stk_period_bar_adj_week/week_end={partition_key}/`<br>Silver `silver/quote/stock_weekly/week_end={partition_key}/` | Raw 1990-12-21<br>Silver 2014-01-03 | 周（自然周五） | `core_serving.stk_period_bar_adj`，`freq=week` | 1997-05-23（freq=week） `core_serving.stk_period_bar_adj` | DG Raw 与 Prod 对应 stk_week_month_adj；含未复权、前复权和后复权价格。Prod 用 freq=week，DG Silver 独立存储。 |
| 股票普通月线行情 | `stk_period_bar_month` | Prod | Tushare | — | — | — | 月（自然月末） | `core_serving.stk_period_bar`，`freq=month` | 2010-01-31（freq=month） `core_serving.stk_period_bar` | 对应 stk_weekly_monthly 的独立接口口径。DG 含复权月线已有未复权价格字段。 |
| 股票普通周线行情 | `stk_period_bar_week` | Prod | Tushare | — | — | — | 周（自然周五） | `core_serving.stk_period_bar`，`freq=week` | 2010-01-01（freq=week） `core_serving.stk_period_bar` | 对应 stk_weekly_monthly 的独立接口口径。DG 含复权周线已有未复权价格字段。 |
| 股票日线行情（前复权） | `stock_daily_qfq` | DG | 派生计算 | 交易日 | Gold `gold/quote/stock_daily_qfq/trade_date={partition_key}/` | Gold 2014-01-02 | — | — | — | — |
| 股票前复权日线神奇九转（自算） | `stock_daily_qfq_nineturn` | DG + Prod | 派生计算 | 交易日 | Gold `gold/indicator/stock_daily_qfq_nineturn/trade_date={partition_key}/` | Gold 2014-01-02 | 交易日 | `core_serving.equity_qfq_nineturn_daily` | 2014-01-02 `core_serving.equity_qfq_nineturn_daily` | DG 前复权日线自行计算并发布给 Prod，输入来自 DG 前复权日线。 |
| 股票日线趋势通道 | `stock_daily_trend_channel` | DG | 派生计算 | 交易日 | Gold `gold/indicator/stock_daily_trend_channel/trade_date={partition_key}/` | Gold 2014-01-02 | — | — | — | — |
| 股票日线趋势通道计算状态 | `stock_daily_trend_channel_state` | DG | 派生计算 | 交易日 | Gold `gold/indicator/stock_daily_trend_channel_state/trade_date={partition_key}/` | Gold 2014-01-02 | — | — | — | — |
| ST 股票列表 | `stock_st` | Prod | Tushare | — | — | — | 交易日 | `core_serving.equity_stock_st` | 2016-08-09 `core_serving.equity_stock_st` | — |
| 股票每日停复牌信息 | `suspend_d` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/suspend_d/trade_date={partition_key}/`<br>Silver `silver/quote/stock_suspend_daily/trade_date={partition_key}/` | Raw 2014-01-02<br>Silver 2014-01-02 | 交易日 | `raw_tushare.suspend_d` | 2000-01-04 `raw_tushare.suspend_d` | — |
| 龙虎榜 | `top_list` | Prod | Tushare | — | — | — | 交易日 | `core_serving.equity_top_list` | 2016-01-04 `core_serving.equity_top_list` | — |

### 指数 / ETF

| 统一中文名 | 英文标识 | 目录覆盖 | 来源 | DG 周期 | DG 位置 | DG 起点 | Prod 周期 | Prod 主表或视图 | Prod 起点和依据表 | 口径说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ETF 复权因子 | `etf_adj_factor` | DG | 从基金复权因子筛选 ETF | 交易日 | Silver `silver/quote/etf_adj_factor/trade_date={partition_key}/` | Silver 2025-01-02 | — | — | — | DG 从基金复权因子筛选 ETF。Prod 基金复权因子表范围更宽，Prod 目录未单独登记对应 ETF 专表。 |
| ETF 日线行情 | `etf_daily` | DG | 从基金日线筛选 ETF | 交易日 | Silver `silver/quote/etf_daily/trade_date={partition_key}/` | Silver 2025-01-02 | — | — | — | DG 从基金日线行情筛选 ETF。Prod 基金日线表范围更宽，Prod 目录未单独登记对应 ETF 专表。 |
| ETF 跟踪指数 | `etf_index` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.etf_index` | 快照 | — |
| ETF 分钟线行情 | `etf_mins` | DG + Prod | Tushare | 1/5/15/30/60 分钟 | Raw `raw/tushare/etf_mins/freq={频率}min/trade_date={partition_key}/`<br>Silver `silver/quote/etf_mins/freq={频率}min/trade_date={partition_key}/` | Raw 2025-01-02<br>Silver 2025-01-02 | 1/5/15/30/60 分钟 | `raw_tushare.etf_minute_bar` | 未核实 | — |
| ETF 申赎清单 | `etf_sh_cons` | Prod | Tushare | — | — | — | 交易日 | `raw_tushare.etf_sh_cons` | 2026-01-05 `raw_tushare.etf_sh_cons` | — |
| ETF 份额规模 | `etf_share_size` | Prod | Tushare | — | — | — | 交易日 | `raw_tushare.etf_share_size` | 2026-01-05 `raw_tushare.etf_share_size` | — |
| ETF 每日持仓组合（深市） | `etf_sz_cons` | Prod | Tushare | — | — | — | 交易日 | `raw_tushare.etf_sz_cons` | 2026-01-05 `raw_tushare.etf_sz_cons` | — |
| 基金复权因子 | `fund_adj` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/fund_adj/trade_date={partition_key}/` | Raw 2025-01-02 | 交易日 | `core.fund_adj_factor` | 2016-01-04 `core.fund_adj_factor` | DG 有基金复权因子 Raw，另从中产出 ETF 复权因子 Silver。 |
| 基金日线行情 | `fund_daily` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/fund_daily/trade_date={partition_key}/` | Raw 2025-01-02 | 交易日 | `core_serving.fund_daily_bar` | 2016-01-04 `core_serving.fund_daily_bar` | DG 有基金 Raw，另从中产出 ETF Silver。Prod 的基金日线主表保留基金数据集口径。 |
| 指数日线技术因子（专业版） | `idx_factor_pro` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/idx_factor_pro/trade_date={partition_key}/`<br>Silver `silver/index/index_factor_pro/trade_date={partition_key}/` | Raw 2000-01-04<br>Silver 2000-01-04 | 交易日 | `core_serving.index_factor_pro` | 2010-01-04 `raw_tushare.idx_factor_pro` | DG Silver 对应 index_factor_pro，当前可用历史依指数代码而异。此处起点来自物理分区。 |
| 指数基础信息 | `index_basic` | DG + Prod | Tushare | 全量快照 | Raw `raw/tushare/index_basic/full/`<br>Silver `silver/index_basic/full/` | 快照 | 全量快照 | `core_serving.index_basic` | 快照 | — |
| 指数日线行情 | `index_daily` | DG + Prod | Tushare、prod_core_db | 交易日 | Raw `raw/index_daily/trade_date={partition_key}/`<br>Silver `silver/index_daily/trade_date={partition_key}/` | Raw 2000-01-04<br>Silver 2000-01-04 | 交易日 | `core_serving.index_daily_serving` | 1991-07-15 `core_serving.index_daily_serving` | — |
| 指数每日指标 | `index_daily_basic` | Prod | Tushare | — | — | — | 交易日 | `core_serving.index_daily_basic` | 2020-01-02 `core_serving.index_daily_basic` | — |
| 国际指数日线行情 | `index_global` | DG | Tushare | 交易日 | Raw `raw/index_global/trade_date={partition_key}/`<br>Silver `silver/index_global/trade_date={partition_key}/` | Raw 2022-01-03<br>Silver 2022-01-03 | — | — | — | DG 合同历史下限 2022-01-01。 |
| 指数分钟线行情 | `index_mins` | DG + Prod | Tushare、prod_core_db | Raw 1/5/15/30/60 分钟<br>Silver 1/5/15/30/60/90/120 分钟<br>Gold 1/5/15/30/60/90/120 分钟 | Raw `raw/tushare/index_mins/freq={频率}min/trade_date={partition_key}/`<br>Silver `silver/quote/index_mins/freq={频率}min/trade_date={partition_key}/`<br>Gold `gold/quote/index_mins/freq={频率}/trade_date={partition_key}/` | Raw 2025-01-02<br>Silver 2025-01-02<br>Gold 2025-01-02 | 1/5/15/30/60 分钟 | `core_serving.index_minute_bar`<br>`raw_tushare.index_mins` | 2025-01-02（freq=1min） `raw_tushare.index_mins`<br>2025-01-02（freq=5min） `raw_tushare.index_mins`<br>2025-01-02（freq=15min） `raw_tushare.index_mins`<br>2025-01-02（freq=30min） `raw_tushare.index_mins`<br>2025-01-02（freq=60min） `raw_tushare.index_mins` | DG Gold 及 Silver 支持 90、120 分钟；Prod 当前源定义支持 1、5、15、30、60 分钟。DG 合同的历史起点为 2025-01-02。 |
| 指数月线行情 | `index_monthly` | DG + Prod | Tushare | 月（最后开市日） | Raw `raw/index_monthly/full/`<br>Silver `silver/index_monthly/full/` | Raw 1991-07-31<br>Silver 1991-07-31 | 月（最后开市日） | `core_serving.index_monthly_serving`<br>`raw_tushare.index_monthly_bar` | 1991-07-31 `core_serving.index_monthly_serving` | 月锚点为当月最后开市日。DG 为全量文件，按月登记分区；Prod 业务查询还有选定指数范围的 Serving 表。 |
| 指数周线行情 | `index_weekly` | DG + Prod | Tushare | 周（最后开市日） | Raw `raw/index_weekly/full/`<br>Silver `silver/index_weekly/full/` | Raw 1991-07-19<br>Silver 1991-07-19 | 周（最后开市日） | `core_serving.index_weekly_serving`<br>`raw_tushare.index_weekly_bar` | 1991-07-19 `core_serving.index_weekly_serving` | 周锚点为当周最后开市日。DG 为全量文件，按周登记分区；Prod 业务查询还有选定指数范围的 Serving 表。 |
| 指数成分权重 | `index_weight` | Prod | Tushare | — | — | — | 自然月窗口 | `core_serving.index_weight` | 未核实 | — |
| 主要指数日线神奇九转（自算） | `major_index_daily_nineturn` | DG + Prod | 派生计算 | 交易日 | Gold `gold/indicator/major_index_daily_nineturn/trade_date={partition_key}/` | Gold 2000-01-04 | 交易日 | `core_serving.index_nineturn_daily` | 2000-01-04 `core_serving.index_nineturn_daily` | — |
| 主要指数分钟线行情 | `major_index_mins` | DG | Tushare | Raw 1/5/15/30/60 分钟<br>Silver 1/5/15/30/60/90/120 分钟<br>Gold 1/5/15/30/60/90/120 分钟 | Raw `raw/tushare/major_index_mins/freq={频率}min/trade_date={partition_key}/`<br>Silver `silver/quote/major_index_mins/freq={频率}min/trade_date={partition_key}/`<br>Gold `gold/quote/major_index_mins/freq={频率}/trade_date={partition_key}/` | Raw 2009-01-05<br>Silver 2009-01-05<br>Gold 2009-01-05 | — | — | — | DG 独立对象范围，历史起点目标 2009-01-05。Prod 指数分钟线目录未单独登记主要指数池。 |
| 主要指数分钟线神奇九转（自算） | `major_index_mins_nineturn` | DG | 派生计算 | 5/15/30/60/90/120 分钟 | Gold `gold/indicator/major_index_mins_nineturn/freq={频率}/trade_date={partition_key}/` | Gold 2009-01-05 | — | — | — | — |
| 主要指数分钟线技术指标 | `major_index_mins_technical` | DG | 派生计算 | 1/5/15/30/60/90/120 分钟 | Gold `gold/indicator/major_index_mins_technical/freq={频率}/trade_date={partition_key}/` | Gold 2009-01-05 | — | — | — | — |
| 主要指数分钟线技术指标计算状态 | `major_index_mins_technical_state` | DG | 派生计算 | 1/5/15/30/60/90/120 分钟 | Gold `gold/indicator/major_index_mins_technical_state/freq={频率}/trade_date={partition_key}/` | Gold 2009-01-05 | — | — | — | — |
| 主要指数量化结构 | `major_index_quantitative_structure` | DG | 派生计算 | 交易日 | Gold `gold/indicator/major_index_quantitative_structure/trade_date={partition_key}/` | Gold 2010-01-04 | — | — | — | — |
| 主要指数日线 | `market_major_indices_daily` | DG | 派生计算 | 交易日 | Gold `gold/market/major_indices_daily/trade_date={partition_key}/` | Gold 2000-01-04 | — | — | — | — |

### 公募基金

| 统一中文名 | 英文标识 | 目录覆盖 | 来源 | DG 周期 | DG 位置 | DG 起点 | Prod 周期 | Prod 主表或视图 | Prod 起点和依据表 | 口径说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 公募基金列表 | `fund_basic` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.fund_basic_current` | 快照 | — |
| 基金管理人 | `fund_company` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.fund_company_current` | 快照 | — |
| 基金分红 | `fund_div` | Prod | Tushare | — | — | — | 公告日（按发布） | `core_serving.fund_div` | 2020-12-15 `core_serving.fund_div` | — |
| 基金经理 | `fund_manager` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.fund_manager_current` | 快照 | — |
| 基金持仓 | `fund_portfolio` | Prod | Tushare | — | — | — | 季（报告期末） | `core_serving.fund_portfolio` | 未核实 | 报告期末用 end_date，按季观测；有财报披露时才有记录。 |
| 公募基金规模 | `fund_share` | Prod | Tushare | — | — | — | 份额日期（按自然日维护） | `core_serving.fund_share_current` | 2014-01-02 `core_serving.fund_share_current` | 基金规模观察版本与当前表分开，日期取 trade_date。 |
| 基金业绩基准库 | `mkt_idx_bmk` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.mkt_idx_bmk_current` | 快照 | — |

### 资金流向

| 统一中文名 | 英文标识 | 目录覆盖 | 来源 | DG 周期 | DG 位置 | DG 起点 | Prod 周期 | Prod 主表或视图 | Prod 起点和依据表 | 口径说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 个股资金流向 | `moneyflow` | DG + Prod | BIYING、Tushare | 交易日 | Raw `raw/tushare/moneyflow/trade_date={partition_key}/`<br>Silver `silver/moneyflow/moneyflow/trade_date={partition_key}/` | Raw 2010-01-04<br>Silver 2010-01-04 | 交易日 | `core_serving.equity_moneyflow` | 2025-04-15 `raw_biying.moneyflow`<br>2010-01-04 `raw_tushare.moneyflow` | Prod 的 Tushare 与 BIYING 是同一逻辑数据集下的来源变体。DG 当前登记 Tushare 原始数据及其标准层。东方财富和同花顺自有口径单列。 |
| 同花顺概念板块资金流向 | `moneyflow_cnt_ths` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/moneyflow_cnt_ths/trade_date={partition_key}/`<br>Silver `silver/moneyflow/moneyflow_cnt_ths/trade_date={partition_key}/` | Raw 2024-09-10<br>Silver 2024-09-10 | 交易日 | `raw_tushare.moneyflow_cnt_ths` | 2024-09-10 `raw_tushare.moneyflow_cnt_ths` | — |
| 东方财富个股资金流向 | `moneyflow_dc` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/moneyflow_dc/trade_date={partition_key}/`<br>Silver `silver/moneyflow/moneyflow_dc/trade_date={partition_key}/` | Raw 2023-09-11<br>Silver 2023-09-11 | 交易日 | `raw_tushare.moneyflow_dc` | 2023-09-11 `raw_tushare.moneyflow_dc` | — |
| 东方财富板块资金流向 | `moneyflow_ind_dc` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/moneyflow_ind_dc/trade_date={partition_key}/`<br>Silver `silver/moneyflow/moneyflow_ind_dc/trade_date={partition_key}/` | Raw 2023-09-12<br>Silver 2023-09-12 | 交易日 | `raw_tushare.moneyflow_ind_dc` | 2023-09-12 `raw_tushare.moneyflow_ind_dc` | — |
| 同花顺行业资金流向 | `moneyflow_ind_ths` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/moneyflow_ind_ths/trade_date={partition_key}/`<br>Silver `silver/moneyflow/moneyflow_ind_ths/trade_date={partition_key}/` | Raw 2024-09-10<br>Silver 2024-09-10 | 交易日 | `raw_tushare.moneyflow_ind_ths` | 2024-09-10 `raw_tushare.moneyflow_ind_ths` | — |
| 东方财富大盘资金流向 | `moneyflow_mkt_dc` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/moneyflow_mkt_dc/trade_date={partition_key}/`<br>Silver `silver/moneyflow/moneyflow_mkt_dc/trade_date={partition_key}/` | Raw 2023-04-17<br>Silver 2023-04-17 | 交易日 | `raw_tushare.moneyflow_mkt_dc` | 2023-04-17 `raw_tushare.moneyflow_mkt_dc` | — |
| 同花顺个股资金流向 | `moneyflow_ths` | DG + Prod | Tushare | 交易日 | Raw `raw/tushare/moneyflow_ths/trade_date={partition_key}/`<br>Silver `silver/moneyflow/moneyflow_ths/trade_date={partition_key}/` | Raw 2024-12-19<br>Silver 2024-12-19 | 交易日 | `raw_tushare.moneyflow_ths` | 2024-12-19 `raw_tushare.moneyflow_ths` | — |

### 板块 / 题材

| 统一中文名 | 英文标识 | 目录覆盖 | 来源 | DG 周期 | DG 位置 | DG 起点 | Prod 周期 | Prod 主表或视图 | Prod 起点和依据表 | 口径说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 东方财富板块日线行情 | `dc_daily` | DG + Prod | Tushare | 交易日 | Raw `raw/board/dc_daily/trade_date={partition_key}/`<br>Silver `silver/board/dc_daily/trade_date={partition_key}/` | Raw 2024-01-02<br>Silver 2024-01-02 | 交易日 | `core_serving.dc_daily`<br>`raw_tushare.dc_daily` | 2024-01-02 `raw_tushare.dc_daily` | Prod 维护写入 Raw，同时登记业务服务表。板块日线技术指标是下游派生数据。 |
| 东方财富板块日线技术指标 | `dc_daily_technical` | DG + Prod | 派生计算 | 交易日 | Gold `gold/board/dc_daily_technical/trade_date={partition_key}/`<br>本机 ClickHouse `goldenshare_serving.board_fact_technical_daily` | Gold 2024-01-02 | 交易日 | `goldenshare_serving.board_fact_technical_daily`（ClickHouse，待核） | 未核实 | 技术指标计算结果由 DG Gold 产出，经本机 ClickHouse 发布到 Prod ClickHouse。历史目标下限 2024-01-02。 |
| 东方财富热榜 | `dc_hot` | Prod | Tushare | — | — | — | 交易日 | `core_serving.dc_hot` | 2024-03-20 `core_serving.dc_hot` | — |
| 东方财富板块列表 | `dc_index` | DG + Prod | Tushare | 交易日 | Raw `raw/board/dc_index/trade_date={partition_key}/`<br>Silver `silver/board/dc_index/trade_date={partition_key}/` | Raw 2024-12-20<br>Silver 2024-12-20 | 交易日 | `core_serving.dc_index` | 2024-12-20 `core_serving.dc_index` | — |
| 东方财富行业层级 | `dc_industry_hierarchy` | DG + Prod | 东方财富参考数据 | 全量快照 | Silver `silver/board/dc_industry_hierarchy/full/` | 快照 | 全量快照 | `core_serving.wealth_sector_hierarchy` | 快照 | DG Silver 快照，Prod 由显式发布写入。业务成分参考日和文件历史起点不同。 |
| 东方财富板块成分 | `dc_member` | DG + Prod | Tushare | 交易日 | Raw `raw/board/dc_member/trade_date={partition_key}/`<br>Silver `silver/board/dc_member/trade_date={partition_key}/` | Raw 2024-12-20<br>Silver 2024-12-20 | 交易日 | `core_serving.dc_member` | 2024-12-20 `core_serving.dc_member` | — |
| 申万 SW2021 行业分类 | `index_classify` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.sw_industry_classification` | 快照 | — |
| 申万 SW2021 行业成员 | `index_member_all` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.sw_industry_member` | 快照 | — |
| 开盘啦板块成分 | `kpl_concept_cons` | Prod | Tushare | — | — | — | 交易日 | `core_serving.kpl_concept_cons` | 2024-10-14 `core_serving.kpl_concept_cons` | — |
| 开盘啦榜单 | `kpl_list` | Prod | Tushare | — | — | — | 交易日 | `core_serving.kpl_list` | 2025-01-02 `core_serving.kpl_list` | — |
| 申万 SW2021 行业日行情 | `sw_daily` | Prod | Tushare | — | — | — | 交易日 | `core_serving.sw_industry_daily` | 2025-01-02 `core_serving.sw_industry_daily` | — |
| 同花顺板块日线行情 | `ths_daily` | Prod | Tushare | — | — | — | 交易日 | `core_serving.ths_daily` | 2020-01-02 `core_serving.ths_daily` | — |
| 同花顺热榜 | `ths_hot` | Prod | Tushare | — | — | — | 交易日 | `core_serving.ths_hot` | 2025-01-02 `core_serving.ths_hot` | — |
| 同花顺板块列表 | `ths_index` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.ths_index` | 快照 | — |
| 同花顺板块成分 | `ths_member` | Prod | Tushare | — | — | — | 全量快照 | `core_serving.ths_member` | 快照 | — |
| 板块每日洞察明细 | `wealth_sector_daily_insight_item` | Prod | 派生计算 | — | — | — | 交易日 | `core_serving.wealth_sector_daily_insight_item` | 未核实 | 归属板块每日分析。最早物理记录日期未按 PUBLISHED 批次过滤。 |
| 板块每日洞察汇总 | `wealth_sector_daily_insight_summary` | Prod | 派生计算 | — | — | — | 交易日 | `core_serving.wealth_sector_daily_insight_summary` | 未核实 | 归属板块每日分析。最早物理记录日期未按 PUBLISHED 批次过滤。 |
| 板块双动量 | `wealth_sector_dual_momentum_daily` | Prod | 派生计算 | — | — | — | 交易日 | `core_serving.wealth_sector_dual_momentum_daily` | 2025-08-22 `core_serving.wealth_sector_dual_momentum_daily` | 归属板块每日分析。最早物理记录日期未按 PUBLISHED 批次过滤。 |
| 每日板块热度 | `wealth_sector_heat_daily` | Prod | 派生计算 | — | — | — | 交易日 | `core_serving.wealth_sector_heat_daily` | 2026-05-20 `core_serving.wealth_sector_heat_daily` | — |
| 板块成员涨跌广度 | `wealth_sector_member_breadth_daily` | Prod | 派生计算 | — | — | — | 交易日 | `core_serving.wealth_sector_member_breadth_daily` | 2025-08-22 `core_serving.wealth_sector_member_breadth_daily` | 归属板块每日分析。最早物理记录日期未按 PUBLISHED 批次过滤。 |
| 板块成员均线广度 | `wealth_sector_member_ma_breadth_daily` | Prod | 派生计算 | — | — | — | 交易日 | `core_serving.wealth_sector_member_ma_breadth_daily` | 2025-08-22 `core_serving.wealth_sector_member_ma_breadth_daily` | 归属板块每日分析。最早物理记录日期未按 PUBLISHED 批次过滤。 |
| 板块动量 | `wealth_sector_momentum_daily` | Prod | 派生计算 | — | — | — | 交易日 | `core_serving.wealth_sector_momentum_daily` | 2025-08-22 `core_serving.wealth_sector_momentum_daily` | 归属板块每日分析。最早物理记录日期未按 PUBLISHED 批次过滤。 |
| 板块价量分析 | `wealth_sector_price_volume_daily` | Prod | 派生计算 | — | — | — | 交易日 | `core_serving.wealth_sector_price_volume_daily` | 2025-08-22 `core_serving.wealth_sector_price_volume_daily` | 归属板块每日分析。最早物理记录日期未按 PUBLISHED 批次过滤。 |
| 板块相对轮动 | `wealth_sector_relative_rotation_daily` | Prod | 派生计算 | — | — | — | 交易日 | `core_serving.wealth_sector_relative_rotation_daily` | 2025-08-22 `core_serving.wealth_sector_relative_rotation_daily` | 归属板块每日分析。最早物理记录日期未按 PUBLISHED 批次过滤。 |

### 市场统计

| 统一中文名 | 英文标识 | 目录覆盖 | 来源 | DG 周期 | DG 位置 | DG 起点 | Prod 周期 | Prod 主表或视图 | Prod 起点和依据表 | 口径说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 市场宽度 | `market_breadth` | DG + Prod | 派生计算 | 交易日 | Gold `gold/breadth/market_breadth_daily/trade_date={partition_key}/`<br>本机 ClickHouse `goldenshare_serving.share_fact_market_breadth_daily` | Gold 2014-01-02 | 交易日 | `goldenshare_serving.share_fact_market_breadth_daily`（ClickHouse，待核） | 未核实 | ClickHouse 发布表将市场宽度与股票涨跌幅分布分桶合在同一张表。湖内两个 Parquet 数据集保持各自定义。 |
| 股票涨跌幅分布 | `stock_return_distribution` | DG + Prod | 派生计算 | 交易日 | Gold `gold/breadth/stock_return_distribution/trade_date={partition_key}/` | Gold 2014-01-02 | 交易日 | `goldenshare_serving.share_fact_market_breadth_daily`（ClickHouse，待核） | 未核实 | DG Gold 独立存储。Prod ClickHouse 发布表共享其中的分桶字段，明细以发布合同为准。 |
| 市场成交额分钟快照 | `wealth_market_turnover` | DG + Prod | 派生计算 | 分钟快照（交易日） | Gold `gold/wealth/market_turnover/trade_date={partition_key}/` | Gold 2014-01-02 | 分钟快照（交易日） | `core_serving.wealth_market_turnover_snapshot` | 未核实 | 按交易日存分钟级累计成交额快照；Prod 保存 DG 发布结果。 |

### 低频数据

| 统一中文名 | 英文标识 | 目录覆盖 | 来源 | DG 周期 | DG 位置 | DG 起点 | Prod 周期 | Prod 主表或视图 | Prod 起点和依据表 | 口径说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 资产负债表 | `balancesheet` | Prod | Tushare | — | — | — | 公告日（按发布） | `raw_tushare.balancesheet` | 2022-01-01 `raw_tushare.balancesheet` | — |
| 现金流量表 | `cashflow` | Prod | Tushare | — | — | — | 公告日（按发布） | `raw_tushare.cashflow` | 2022-01-01 `raw_tushare.cashflow` | — |
| 分红送股 | `dividend` | Prod | Tushare | — | — | — | 公告日（按发布） | `core_serving.equity_dividend` | 1991-03-17 `core_serving.equity_dividend` | — |
| 业绩快报 | `express` | Prod | Tushare | — | — | — | 公告日（按发布） | `core_serving.equity_express` | 2010-01-05 `core_serving.equity_express` | — |
| 财务指标 | `fina_indicator` | Prod | Tushare | — | — | — | 公告日（按发布） | `raw_tushare.fina_indicator` | 2022-01-01 `raw_tushare.fina_indicator` | — |
| 利润表 | `income` | Prod | Tushare | — | — | — | 公告日（按发布） | `raw_tushare.income` | 2022-01-01 `raw_tushare.income` | — |
| 股东户数 | `stk_holdernumber` | Prod | Tushare | — | — | — | 公告日（按发布） | `core_serving.equity_holder_number` | 未核实 | — |

### 新闻资讯

| 统一中文名 | 英文标识 | 目录覆盖 | 来源 | DG 周期 | DG 位置 | DG 起点 | Prod 周期 | Prod 主表或视图 | Prod 起点和依据表 | 口径说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 上市公司公告 | `anns_d` | DG + Prod | Tushare | 公告日 | Raw `raw/tushare/anns_d/ann_date={partition_key}/` | Raw 2020-01-01 | 公告日（按发布） | `core_serving_light.anns_d` | 2020-01-01 `raw_tushare.anns_d` | 按公告日期。DG 登记 Raw，Prod 另登记业务表。公告日期可查询，具体日期是否有公告取决于实际发布。 |
| 新闻联播文字稿 | `cctv_news` | Prod | Tushare | — | — | — | 自然日 | `core_serving_light.cctv_news` | 2020-01-01 `raw_tushare.cctv_news` | — |
| 上证E互动问答 | `irm_qa_sh` | Prod | Tushare | — | — | — | 发布时间（按事件） | `core_serving_light.irm_qa_sh` | 2025-01-14 `raw_tushare.irm_qa_sh` | — |
| 深证互动易问答 | `irm_qa_sz` | Prod | Tushare | — | — | — | 发布时间（按事件） | `core_serving_light.irm_qa_sz` | 2020-12-31 `raw_tushare.irm_qa_sz` | — |
| 新闻通讯 | `major_news` | Prod | Tushare | — | — | — | 发布时间（按事件） | `core_serving_light.major_news` | 2026-01-01 `raw_tushare.major_news` | — |
| 新闻快讯 | `news` | Prod | Tushare | — | — | — | 发布时间（按事件） | `core_serving_light.news` | 2022-01-01 `raw_tushare.news` | — |
| 新闻个股关联 | `news_stock_link` | Prod | 派生计算 | — | — | — | 按新闻关联 | `core_serving.news_stock_link` | 未核实 | — |

## 3. 共享包建议

可以做一个 DG 和 Prod 都依赖的基础共享包。Prod 的数据源定义和业务产出有各自的目录，DG 则在资产目录中引用本地名称映射。建议把统一身份放进共享包，由各端登记自己的路径、表名和规则，发布时按共享标识生成一份只读目录随包提供。DG、Prod 和其他消费者都能用同一个标识查到两端的登记信息。[Prod 数据源目录](../../src/foundation/datasets/registry.py) · [Prod 业务产出目录](../../src/ops/catalog/biz_dataset_definitions.py) · [DG 资产目录](../../lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py) · [DG 名称映射](../../lake_console/orchestrator/src/orchestrator/defs/catalog/name_mapping.py)

| 维护位置 | 字段 | 使用方式 |
| --- | --- | --- |
| 共享包 | 稳定英文标识、唯一中文名、旧称、数据领域、业务对象、业务粒度、可明确跨端共享的语义 | 用标识查找数据集，用中文名沟通，用别名兼容历史叫法。名称维护一处。 |
| DG 登记 | 共享标识、资产键、层级、路径模板、对象范围、支持频率、分区锚点、已确认的历史下限 | 一个业务数据集可以关联多个资产。以路径函数和运行合同为依据。 |
| Prod 登记 | 共享标识、来源、源接口、表/视图、层级、共表过滤、支持频率、日期字段和日期规则 | 同一张表可对应多个业务数据集，例如按 freq 区分股票周线和月线。 |
| 核验结果 | 环境、存储位置、频率或来源、最早非空日期、取证方式、核验时间 | 回补和保留策略会改变实际起点，从各端只读查询结果生成。 |

依赖方向可参考仓库现有独立包。DG 和 Prod 同向引用共享包。共享包提供基础定义与查询，DG、Ops、Web 的运行逻辑和数据库连接由各自入口负责。首批可以用股票周线行情（含复权）、股票月线行情（含复权）、指数分钟线行情验证一对多与共表过滤。验收时按中文名、英文键、DG 资产键、Prod 全限定表名反查。一个表名有多个结果时，同时返回 `freq` 或来源条件。自动检查应逐项对照正式路径和表映射，并验证中文名、英文标识及别名的冲突规则。[现有独立包接入示例](../../packages/technical_indicators/pyproject.toml) · [子系统边界](../architecture/subsystem-boundary-plan.md)

平时可以说“股票周线行情（含复权）”，需要指定存储时追加“DG Silver”或“Prod Serving，freq=week”。如果输入只有“股票周线”或 `core_serving.stk_period_bar_adj`，查询结果应列出匹配的业务项和区分条件。

## 4. DG 存储明细

Parquet 列为完整的相对路径模板。频率目录中，股票 Raw/Silver 用数字，指数与 ETF 的部分层级用带 `min` 的目录名。表和资产中用同一个英文业务标识反查。

| 英文标识 | DG 数据集标识 | DG 资产键 | 层 | 周期 | 源接口 | 文件模板 / 本机表 | 起点与证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `etf_basic` | `etf_basic` | `raw_tushare_etf_basic` | Raw | 全量快照 | `etf_basic` | `raw/tushare/etf_basic/snapshot_id={snapshot_id}/part-000.parquet` | 版本快照，已见非空文件（`snapshot_id（SHA256）`） |
| `etf_basic` | `etf_basic` | `silver_etf_basic` | Silver | 全量快照 | — | `silver/basic/etf_basic/snapshot_id={snapshot_id}/part-000.parquet` | 版本快照，已见非空文件（`snapshot_id（SHA256）`） |
| `namechange` | `namechange` | `raw_tushare_namechange` | Raw | 全量快照 | `namechange` | `raw/tushare/namechange/full/part-000.parquet` | 快照，已见非空文件 |
| `namechange` | `namechange` | `silver_namechange` | Silver | 全量快照 | — | `silver/basic/namechange/full/part-000.parquet` | 快照，已见非空文件 |
| `stock_basic` | `stock_basic` | `raw_tushare_stock_basic` | Raw | 全量快照 | `stock_basic` | `raw/tushare/stock_basic/full/part-000.parquet` | 快照，已见非空文件 |
| `stock_basic` | `stock_basic` | `silver_stock_basic` | Silver | 全量快照 | — | `silver/basic/stock_basic/full/part-000.parquet` | 快照，已见非空文件 |
| `stock_identity_map` | `stock_identity_map` | `silver_stock_identity_map` | Silver | 全量快照 | — | `silver/basic/stock_identity_map/part-000.parquet` | 快照，已见非空文件 |
| `stock_lifecycle` | `stock_lifecycle` | `silver_stock_lifecycle` | Silver | 全量快照 | — | `silver/basic/stock_lifecycle/full/part-000.parquet` | 快照，已见非空文件 |
| `stock_suspend_confirmed` | `stock_suspend_confirmed` | `silver_stock_suspend_confirmed` | Silver | 全量快照 | — | `silver/quote/stock_suspend_confirmed/full/part-000.parquet` | 2014-01-02 · 文件页脚最早日期（`trade_date`） |
| `trade_cal` | `trade_cal` | `raw_tushare_trade_calendar` | Raw | 日历日（全量文件） | `trade_cal` | `raw/tushare/trade_calendar/full/part-000.parquet` | 1990-12-19 · 文件页脚最早日期（`cal_date`） |
| `trade_cal` | `trade_cal` | `silver_trade_calendar` | Silver | 日历日（全量文件） | — | `silver/calendar/trade_calendar/full/part-000.parquet` | 1990-12-19 · 文件页脚最早日期（`trade_date`） |
| `adj_factor` | `adj_factor` | `raw_tushare_adj_factor` | Raw | 交易日 | `adj_factor` | `raw/tushare/adj_factor/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `adj_factor` | `adj_factor` | `silver_adj_factor` | Silver | 交易日 | — | `silver/quote/adj_factor/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `daily` | `daily` | `raw_tushare_stock_daily` | Raw | 交易日 | `daily` | `raw/tushare/stock_daily/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `daily` | `daily` | `silver_stock_daily` | Silver | 交易日 | — | `silver/quote/stock_daily/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `daily_basic` | `daily_basic` | `raw_tushare_daily_basic` | Raw | 交易日 | `daily_basic` | `raw/tushare/daily_basic/trade_date={partition_key}/part-000.parquet` | 2010-01-04 · 首个非空分区（`trade_date`） |
| `stk_factor_pro` | `stk_factor_pro` | `raw_tushare_stk_factor_pro` | Raw | 交易日 | `stk_factor_pro` | `raw/tushare/stk_factor_pro/trade_date={partition_key}/data.parquet` | 2017-01-03 · 首个非空分区（`trade_date`） |
| `stk_factor_pro` | `stock_factor_pro` | `silver_stock_factor_pro` | Silver | 交易日 | — | `silver/stock_factor_pro/trade_date={partition_key}/data.parquet` | 2017-01-03 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `raw_stk_mins_1m` | Raw | 1 分钟 | `stk_mins` | `raw/tushare/stk_mins/freq=1/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `raw_stk_mins_5m` | Raw | 5 分钟 | `stk_mins` | `raw/tushare/stk_mins/freq=5/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `raw_stk_mins_15m` | Raw | 15 分钟 | `stk_mins` | `raw/tushare/stk_mins/freq=15/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `raw_stk_mins_30m` | Raw | 30 分钟 | `stk_mins` | `raw/tushare/stk_mins/freq=30/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `raw_stk_mins_60m` | Raw | 60 分钟 | `stk_mins` | `raw/tushare/stk_mins/freq=60/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `silver_stk_mins_1m` | Silver | 1 分钟 | — | `silver/quote/stk_mins/freq=1/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `silver_stk_mins_5m` | Silver | 5 分钟 | — | `silver/quote/stk_mins/freq=5/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `silver_stk_mins_15m` | Silver | 15 分钟 | — | `silver/quote/stk_mins/freq=15/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `silver_stk_mins_30m` | Silver | 30 分钟 | — | `silver/quote/stk_mins/freq=30/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins` | `stk_mins` | `silver_stk_mins_60m` | Silver | 60 分钟 | — | `silver/quote/stk_mins/freq=60/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq` | `stk_mins_qfq` | `gold_stk_mins_qfq_1m` | Gold | 1 分钟 | — | `gold/quote/stk_mins_qfq/freq=1/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq` | `stk_mins_qfq` | `gold_stk_mins_qfq_5m` | Gold | 5 分钟 | — | `gold/quote/stk_mins_qfq/freq=5/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq` | `stk_mins_qfq` | `gold_stk_mins_qfq_15m` | Gold | 15 分钟 | — | `gold/quote/stk_mins_qfq/freq=15/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq` | `stk_mins_qfq` | `gold_stk_mins_qfq_30m` | Gold | 30 分钟 | — | `gold/quote/stk_mins_qfq/freq=30/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq` | `stk_mins_qfq` | `gold_stk_mins_qfq_60m` | Gold | 60 分钟 | — | `gold/quote/stk_mins_qfq/freq=60/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq` | `stk_mins_qfq` | `gold_stk_mins_qfq_90m` | Gold | 90 分钟 | — | `gold/quote/stk_mins_qfq/freq=90/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq` | `stk_mins_qfq` | `gold_stk_mins_qfq_120m` | Gold | 120 分钟 | — | `gold/quote/stk_mins_qfq/freq=120/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq_macd_kdj` | `stk_mins_qfq_macd_kdj` | `gold_stk_mins_qfq_macd_kdj_1m` | Gold | 1 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj/freq=1/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq_macd_kdj` | `stk_mins_qfq_macd_kdj` | `gold_stk_mins_qfq_macd_kdj_5m` | Gold | 5 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj/freq=5/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq_macd_kdj` | `stk_mins_qfq_macd_kdj` | `gold_stk_mins_qfq_macd_kdj_15m` | Gold | 15 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj/freq=15/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq_macd_kdj` | `stk_mins_qfq_macd_kdj` | `gold_stk_mins_qfq_macd_kdj_30m` | Gold | 30 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj/freq=30/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq_macd_kdj` | `stk_mins_qfq_macd_kdj` | `gold_stk_mins_qfq_macd_kdj_60m` | Gold | 60 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj/freq=60/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq_macd_kdj` | `stk_mins_qfq_macd_kdj` | `gold_stk_mins_qfq_macd_kdj_90m` | Gold | 90 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj/freq=90/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq_macd_kdj` | `stk_mins_qfq_macd_kdj` | `gold_stk_mins_qfq_macd_kdj_120m` | Gold | 120 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj/freq=120/ts_code={ts_code}/year={year}/part-000.parquet` | 2014-01-02 · 单股票样本日期（`trade_date（000001.SZ）`） |
| `stk_mins_qfq_macd_kdj_state` | `stk_mins_qfq_macd_kdj_state` | `gold_stk_mins_qfq_macd_kdj_state_1m` | Gold | 1 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj_state/freq=1/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_macd_kdj_state` | `stk_mins_qfq_macd_kdj_state` | `gold_stk_mins_qfq_macd_kdj_state_5m` | Gold | 5 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj_state/freq=5/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_macd_kdj_state` | `stk_mins_qfq_macd_kdj_state` | `gold_stk_mins_qfq_macd_kdj_state_15m` | Gold | 15 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj_state/freq=15/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_macd_kdj_state` | `stk_mins_qfq_macd_kdj_state` | `gold_stk_mins_qfq_macd_kdj_state_30m` | Gold | 30 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj_state/freq=30/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_macd_kdj_state` | `stk_mins_qfq_macd_kdj_state` | `gold_stk_mins_qfq_macd_kdj_state_60m` | Gold | 60 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj_state/freq=60/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_macd_kdj_state` | `stk_mins_qfq_macd_kdj_state` | `gold_stk_mins_qfq_macd_kdj_state_90m` | Gold | 90 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj_state/freq=90/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_macd_kdj_state` | `stk_mins_qfq_macd_kdj_state` | `gold_stk_mins_qfq_macd_kdj_state_120m` | Gold | 120 分钟 | — | `gold/indicator/stk_mins_qfq_macd_kdj_state/freq=120/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_nineturn` | `stk_mins_qfq_nineturn` | `gold_stk_mins_qfq_nineturn_30m` | Gold | 30 分钟 | — | `gold/indicator/stk_mins_qfq_nineturn/freq=30/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_nineturn` | `stk_mins_qfq_nineturn` | `gold_stk_mins_qfq_nineturn_60m` | Gold | 60 分钟 | — | `gold/indicator/stk_mins_qfq_nineturn/freq=60/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_nineturn` | `stk_mins_qfq_nineturn` | `gold_stk_mins_qfq_nineturn_90m` | Gold | 90 分钟 | — | `gold/indicator/stk_mins_qfq_nineturn/freq=90/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_mins_qfq_nineturn` | `stk_mins_qfq_nineturn` | `gold_stk_mins_qfq_nineturn_120m` | Gold | 120 分钟 | — | `gold/indicator/stk_mins_qfq_nineturn/freq=120/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stk_nineturn` | `stk_nineturn` | `raw_tushare_stk_nineturn` | Raw | 交易日 | `stk_nineturn` | `raw/tushare/stk_nineturn/trade_date={partition_key}/part-000.parquet` | 2023-01-03 · 首个非空分区（`trade_date`） |
| `stk_nineturn` | `stock_nineturn_daily` | `silver_stock_nineturn_daily` | Silver | 交易日 | — | `silver/quote/stock_nineturn_daily/trade_date={partition_key}/part-000.parquet` | 2023-01-03 · 首个非空分区（`trade_date`） |
| `stk_period_bar_adj_month` | `stk_period_bar_adj_month` | `raw_tushare_stk_period_bar_adj_month` | Raw | 月（自然月末） | `stk_week_month_adj` | `raw/tushare/stk_period_bar_adj_month/month={partition_key}/data.parquet` | 1990-12 · 首个非空分区（`month`） |
| `stk_period_bar_adj_month` | `stock_monthly` | `silver_stock_monthly` | Silver | 月（自然月末） | — | `silver/quote/stock_monthly/month={partition_key}/part-000.parquet` | 2014-01 · 首个非空分区（`month`） |
| `stk_period_bar_adj_week` | `stk_period_bar_adj_week` | `raw_tushare_stk_period_bar_adj_week` | Raw | 周（自然周五） | `stk_week_month_adj` | `raw/tushare/stk_period_bar_adj_week/week_end={partition_key}/part-000.parquet` | 1990-12-21 · 首个非空分区（`week_end`） |
| `stk_period_bar_adj_week` | `stock_weekly` | `silver_stock_weekly` | Silver | 周（自然周五） | — | `silver/quote/stock_weekly/week_end={partition_key}/part-000.parquet` | 2014-01-03 · 首个非空分区（`week_end`） |
| `stock_daily_qfq` | `stock_daily_qfq` | `gold_stock_daily_qfq` | Gold | 交易日 | — | `gold/quote/stock_daily_qfq/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stock_daily_qfq_nineturn` | `stock_daily_qfq_nineturn` | `gold_stock_daily_qfq_nineturn` | Gold | 交易日 | — | `gold/indicator/stock_daily_qfq_nineturn/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stock_daily_trend_channel` | `stock_daily_trend_channel` | `gold_stock_daily_trend_channel` | Gold | 交易日 | — | `gold/indicator/stock_daily_trend_channel/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `stock_daily_trend_channel_state` | `stock_daily_trend_channel_state` | `gold_stock_daily_trend_channel_state` | Gold | 交易日 | — | `gold/indicator/stock_daily_trend_channel_state/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `suspend_d` | `suspend_d` | `raw_tushare_suspend_d` | Raw | 交易日 | `suspend_d` | `raw/tushare/suspend_d/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `suspend_d` | `suspend_d` | `silver_stock_suspend_daily` | Silver | 交易日 | — | `silver/quote/stock_suspend_daily/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `etf_adj_factor` | `etf_adj_factor` | `silver_etf_adj_factor` | Silver | 交易日 | — | `silver/quote/etf_adj_factor/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_daily` | `etf_daily` | `silver_etf_daily` | Silver | 交易日 | — | `silver/quote/etf_daily/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `raw_etf_mins_1m` | Raw | 1 分钟 | `etf_mins` | `raw/tushare/etf_mins/freq=1min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `raw_etf_mins_5m` | Raw | 5 分钟 | `etf_mins` | `raw/tushare/etf_mins/freq=5min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `raw_etf_mins_15m` | Raw | 15 分钟 | `etf_mins` | `raw/tushare/etf_mins/freq=15min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `raw_etf_mins_30m` | Raw | 30 分钟 | `etf_mins` | `raw/tushare/etf_mins/freq=30min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `raw_etf_mins_60m` | Raw | 60 分钟 | `etf_mins` | `raw/tushare/etf_mins/freq=60min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `silver_etf_mins_1m` | Silver | 1 分钟 | — | `silver/quote/etf_mins/freq=1min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `silver_etf_mins_5m` | Silver | 5 分钟 | — | `silver/quote/etf_mins/freq=5min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `silver_etf_mins_15m` | Silver | 15 分钟 | — | `silver/quote/etf_mins/freq=15min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `silver_etf_mins_30m` | Silver | 30 分钟 | — | `silver/quote/etf_mins/freq=30min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `etf_mins` | `etf_mins` | `silver_etf_mins_60m` | Silver | 60 分钟 | — | `silver/quote/etf_mins/freq=60min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `fund_adj` | `fund_adj` | `raw_tushare_fund_adj` | Raw | 交易日 | `fund_adj` | `raw/tushare/fund_adj/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `fund_daily` | `fund_daily` | `raw_tushare_fund_daily` | Raw | 交易日 | `fund_daily` | `raw/tushare/fund_daily/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `idx_factor_pro` | `idx_factor_pro` | `raw_tushare_idx_factor_pro` | Raw | 交易日 | `idx_factor_pro` | `raw/tushare/idx_factor_pro/trade_date={partition_key}/part-000.parquet` | 2000-01-04 · 首个非空分区（`trade_date`） |
| `idx_factor_pro` | `index_factor_pro` | `silver_index_factor_pro` | Silver | 交易日 | — | `silver/index/index_factor_pro/trade_date={partition_key}/part-000.parquet` | 2000-01-04 · 首个非空分区（`trade_date`） |
| `index_basic` | `index_basic` | `raw_tushare_index_basic` | Raw | 全量快照 | `index_basic` | `raw/tushare/index_basic/full/part-000.parquet` | 快照，已见非空文件 |
| `index_basic` | `index_basic` | `silver_index_basic` | Silver | 全量快照 | — | `silver/index_basic/full/part-000.parquet` | 快照，已见非空文件 |
| `index_daily` | `index_daily` | `raw_index_daily` | Raw | 交易日 | — | `raw/index_daily/trade_date={partition_key}/part-000.parquet` | 2000-01-04 · 首个非空分区（`trade_date`） |
| `index_daily` | `index_daily` | `silver_index_daily` | Silver | 交易日 | — | `silver/index_daily/trade_date={partition_key}/part-000.parquet` | 2000-01-04 · 首个非空分区（`trade_date`） |
| `index_global` | `index_global` | `raw_index_global` | Raw | 交易日 | `index_global` | `raw/index_global/trade_date={partition_key}/part-000.parquet` | 2022-01-03 · 首个非空分区（`trade_date`） |
| `index_global` | `index_global` | `silver_index_global` | Silver | 交易日 | — | `silver/index_global/trade_date={partition_key}/part-000.parquet` | 2022-01-03 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `raw_index_mins_1m` | Raw | 1 分钟 | — | `raw/tushare/index_mins/freq=1min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `raw_index_mins_5m` | Raw | 5 分钟 | — | `raw/tushare/index_mins/freq=5min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `raw_index_mins_15m` | Raw | 15 分钟 | — | `raw/tushare/index_mins/freq=15min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `raw_index_mins_30m` | Raw | 30 分钟 | — | `raw/tushare/index_mins/freq=30min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `raw_index_mins_60m` | Raw | 60 分钟 | — | `raw/tushare/index_mins/freq=60min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `silver_index_mins_1m` | Silver | 1 分钟 | — | `silver/quote/index_mins/freq=1min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `silver_index_mins_5m` | Silver | 5 分钟 | — | `silver/quote/index_mins/freq=5min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `silver_index_mins_15m` | Silver | 15 分钟 | — | `silver/quote/index_mins/freq=15min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `silver_index_mins_30m` | Silver | 30 分钟 | — | `silver/quote/index_mins/freq=30min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `silver_index_mins_60m` | Silver | 60 分钟 | — | `silver/quote/index_mins/freq=60min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `silver_index_mins_90m` | Silver | 90 分钟 | — | `silver/quote/index_mins/freq=90min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `silver_index_mins_120m` | Silver | 120 分钟 | — | `silver/quote/index_mins/freq=120min/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `gold_index_mins_1m` | Gold | 1 分钟 | — | `gold/quote/index_mins/freq=1/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `gold_index_mins_5m` | Gold | 5 分钟 | — | `gold/quote/index_mins/freq=5/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `gold_index_mins_15m` | Gold | 15 分钟 | — | `gold/quote/index_mins/freq=15/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `gold_index_mins_30m` | Gold | 30 分钟 | — | `gold/quote/index_mins/freq=30/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `gold_index_mins_60m` | Gold | 60 分钟 | — | `gold/quote/index_mins/freq=60/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `gold_index_mins_90m` | Gold | 90 分钟 | — | `gold/quote/index_mins/freq=90/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_mins` | `index_mins` | `gold_index_mins_120m` | Gold | 120 分钟 | — | `gold/quote/index_mins/freq=120/trade_date={partition_key}/part-000.parquet` | 2025-01-02 · 首个非空分区（`trade_date`） |
| `index_monthly` | `index_monthly` | `raw_index_monthly` | Raw | 月（最后开市日） | `index_monthly` | `raw/index_monthly/full/part-000.parquet` | 1991-07-31 · 文件页脚最早日期（`trade_date`） |
| `index_monthly` | `index_monthly` | `silver_index_monthly` | Silver | 月（最后开市日） | — | `silver/index_monthly/full/part-000.parquet` | 1991-07-31 · 文件页脚最早日期（`trade_date`） |
| `index_weekly` | `index_weekly` | `raw_index_weekly` | Raw | 周（最后开市日） | `index_weekly` | `raw/index_weekly/full/part-000.parquet` | 1991-07-19 · 文件页脚最早日期（`trade_date`） |
| `index_weekly` | `index_weekly` | `silver_index_weekly` | Silver | 周（最后开市日） | — | `silver/index_weekly/full/part-000.parquet` | 1991-07-19 · 文件页脚最早日期（`trade_date`） |
| `major_index_daily_nineturn` | `major_index_daily_nineturn` | `gold_major_index_daily_nineturn` | Gold | 交易日 | — | `gold/indicator/major_index_daily_nineturn/trade_date={partition_key}/part-000.parquet` | 2000-01-04 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `raw_major_index_mins_1m` | Raw | 1 分钟 | `idx_mins` | `raw/tushare/major_index_mins/freq=1min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `raw_major_index_mins_5m` | Raw | 5 分钟 | `idx_mins` | `raw/tushare/major_index_mins/freq=5min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `raw_major_index_mins_15m` | Raw | 15 分钟 | `idx_mins` | `raw/tushare/major_index_mins/freq=15min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `raw_major_index_mins_30m` | Raw | 30 分钟 | `idx_mins` | `raw/tushare/major_index_mins/freq=30min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `raw_major_index_mins_60m` | Raw | 60 分钟 | `idx_mins` | `raw/tushare/major_index_mins/freq=60min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `silver_major_index_mins_1m` | Silver | 1 分钟 | — | `silver/quote/major_index_mins/freq=1min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `silver_major_index_mins_5m` | Silver | 5 分钟 | — | `silver/quote/major_index_mins/freq=5min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `silver_major_index_mins_15m` | Silver | 15 分钟 | — | `silver/quote/major_index_mins/freq=15min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `silver_major_index_mins_30m` | Silver | 30 分钟 | — | `silver/quote/major_index_mins/freq=30min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `silver_major_index_mins_60m` | Silver | 60 分钟 | — | `silver/quote/major_index_mins/freq=60min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `silver_major_index_mins_90m` | Silver | 90 分钟 | — | `silver/quote/major_index_mins/freq=90min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `silver_major_index_mins_120m` | Silver | 120 分钟 | — | `silver/quote/major_index_mins/freq=120min/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `gold_major_index_mins_1m` | Gold | 1 分钟 | — | `gold/quote/major_index_mins/freq=1/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `gold_major_index_mins_5m` | Gold | 5 分钟 | — | `gold/quote/major_index_mins/freq=5/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `gold_major_index_mins_15m` | Gold | 15 分钟 | — | `gold/quote/major_index_mins/freq=15/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `gold_major_index_mins_30m` | Gold | 30 分钟 | — | `gold/quote/major_index_mins/freq=30/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `gold_major_index_mins_60m` | Gold | 60 分钟 | — | `gold/quote/major_index_mins/freq=60/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `gold_major_index_mins_90m` | Gold | 90 分钟 | — | `gold/quote/major_index_mins/freq=90/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins` | `major_index_mins` | `gold_major_index_mins_120m` | Gold | 120 分钟 | — | `gold/quote/major_index_mins/freq=120/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_nineturn` | `major_index_mins_nineturn` | `gold_major_index_mins_nineturn_5m` | Gold | 5 分钟 | — | `gold/indicator/major_index_mins_nineturn/freq=5/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_nineturn` | `major_index_mins_nineturn` | `gold_major_index_mins_nineturn_15m` | Gold | 15 分钟 | — | `gold/indicator/major_index_mins_nineturn/freq=15/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_nineturn` | `major_index_mins_nineturn` | `gold_major_index_mins_nineturn_30m` | Gold | 30 分钟 | — | `gold/indicator/major_index_mins_nineturn/freq=30/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_nineturn` | `major_index_mins_nineturn` | `gold_major_index_mins_nineturn_60m` | Gold | 60 分钟 | — | `gold/indicator/major_index_mins_nineturn/freq=60/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_nineturn` | `major_index_mins_nineturn` | `gold_major_index_mins_nineturn_90m` | Gold | 90 分钟 | — | `gold/indicator/major_index_mins_nineturn/freq=90/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_nineturn` | `major_index_mins_nineturn` | `gold_major_index_mins_nineturn_120m` | Gold | 120 分钟 | — | `gold/indicator/major_index_mins_nineturn/freq=120/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical` | `major_index_mins_technical` | `gold_major_index_mins_technical_1m` | Gold | 1 分钟 | — | `gold/indicator/major_index_mins_technical/freq=1/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical` | `major_index_mins_technical` | `gold_major_index_mins_technical_5m` | Gold | 5 分钟 | — | `gold/indicator/major_index_mins_technical/freq=5/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical` | `major_index_mins_technical` | `gold_major_index_mins_technical_15m` | Gold | 15 分钟 | — | `gold/indicator/major_index_mins_technical/freq=15/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical` | `major_index_mins_technical` | `gold_major_index_mins_technical_30m` | Gold | 30 分钟 | — | `gold/indicator/major_index_mins_technical/freq=30/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical` | `major_index_mins_technical` | `gold_major_index_mins_technical_60m` | Gold | 60 分钟 | — | `gold/indicator/major_index_mins_technical/freq=60/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical` | `major_index_mins_technical` | `gold_major_index_mins_technical_90m` | Gold | 90 分钟 | — | `gold/indicator/major_index_mins_technical/freq=90/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical` | `major_index_mins_technical` | `gold_major_index_mins_technical_120m` | Gold | 120 分钟 | — | `gold/indicator/major_index_mins_technical/freq=120/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical_state` | `major_index_mins_technical_state` | `gold_major_index_mins_technical_state_1m` | Gold | 1 分钟 | — | `gold/indicator/major_index_mins_technical_state/freq=1/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical_state` | `major_index_mins_technical_state` | `gold_major_index_mins_technical_state_5m` | Gold | 5 分钟 | — | `gold/indicator/major_index_mins_technical_state/freq=5/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical_state` | `major_index_mins_technical_state` | `gold_major_index_mins_technical_state_15m` | Gold | 15 分钟 | — | `gold/indicator/major_index_mins_technical_state/freq=15/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical_state` | `major_index_mins_technical_state` | `gold_major_index_mins_technical_state_30m` | Gold | 30 分钟 | — | `gold/indicator/major_index_mins_technical_state/freq=30/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical_state` | `major_index_mins_technical_state` | `gold_major_index_mins_technical_state_60m` | Gold | 60 分钟 | — | `gold/indicator/major_index_mins_technical_state/freq=60/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical_state` | `major_index_mins_technical_state` | `gold_major_index_mins_technical_state_90m` | Gold | 90 分钟 | — | `gold/indicator/major_index_mins_technical_state/freq=90/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_mins_technical_state` | `major_index_mins_technical_state` | `gold_major_index_mins_technical_state_120m` | Gold | 120 分钟 | — | `gold/indicator/major_index_mins_technical_state/freq=120/trade_date={partition_key}/part-000.parquet` | 2009-01-05 · 首个非空分区（`trade_date`） |
| `major_index_quantitative_structure` | `major_index_quantitative_structure` | `gold_major_index_quantitative_structure` | Gold | 交易日 | — | `gold/indicator/major_index_quantitative_structure/trade_date={partition_key}/part-000.parquet` | 2010-01-04 · 首个非空分区（`trade_date`） |
| `market_major_indices_daily` | `market_major_indices_daily` | `gold_market_major_indices_daily` | Gold | 交易日 | — | `gold/market/major_indices_daily/trade_date={partition_key}/part-000.parquet` | 2000-01-04 · 首个非空分区（`trade_date`） |
| `moneyflow` | `moneyflow` | `raw_tushare_moneyflow` | Raw | 交易日 | `moneyflow` | `raw/tushare/moneyflow/trade_date={partition_key}/part-000.parquet` | 2010-01-04 · 首个非空分区（`trade_date`） |
| `moneyflow` | `moneyflow` | `silver_moneyflow` | Silver | 交易日 | — | `silver/moneyflow/moneyflow/trade_date={partition_key}/part-000.parquet` | 2010-01-04 · 首个非空分区（`trade_date`） |
| `moneyflow_cnt_ths` | `moneyflow_cnt_ths` | `raw_tushare_moneyflow_cnt_ths` | Raw | 交易日 | `moneyflow_cnt_ths` | `raw/tushare/moneyflow_cnt_ths/trade_date={partition_key}/part-000.parquet` | 2024-09-10 · 首个非空分区（`trade_date`） |
| `moneyflow_cnt_ths` | `moneyflow_cnt_ths` | `silver_moneyflow_cnt_ths` | Silver | 交易日 | — | `silver/moneyflow/moneyflow_cnt_ths/trade_date={partition_key}/part-000.parquet` | 2024-09-10 · 首个非空分区（`trade_date`） |
| `moneyflow_dc` | `moneyflow_dc` | `raw_tushare_moneyflow_dc` | Raw | 交易日 | `moneyflow_dc` | `raw/tushare/moneyflow_dc/trade_date={partition_key}/part-000.parquet` | 2023-09-11 · 首个非空分区（`trade_date`） |
| `moneyflow_dc` | `moneyflow_dc` | `silver_moneyflow_dc` | Silver | 交易日 | — | `silver/moneyflow/moneyflow_dc/trade_date={partition_key}/part-000.parquet` | 2023-09-11 · 首个非空分区（`trade_date`） |
| `moneyflow_ind_dc` | `moneyflow_ind_dc` | `raw_tushare_moneyflow_ind_dc` | Raw | 交易日 | `moneyflow_ind_dc` | `raw/tushare/moneyflow_ind_dc/trade_date={partition_key}/part-000.parquet` | 2023-09-12 · 首个非空分区（`trade_date`） |
| `moneyflow_ind_dc` | `moneyflow_ind_dc` | `silver_moneyflow_ind_dc` | Silver | 交易日 | — | `silver/moneyflow/moneyflow_ind_dc/trade_date={partition_key}/part-000.parquet` | 2023-09-12 · 首个非空分区（`trade_date`） |
| `moneyflow_ind_ths` | `moneyflow_ind_ths` | `raw_tushare_moneyflow_ind_ths` | Raw | 交易日 | `moneyflow_ind_ths` | `raw/tushare/moneyflow_ind_ths/trade_date={partition_key}/part-000.parquet` | 2024-09-10 · 首个非空分区（`trade_date`） |
| `moneyflow_ind_ths` | `moneyflow_ind_ths` | `silver_moneyflow_ind_ths` | Silver | 交易日 | — | `silver/moneyflow/moneyflow_ind_ths/trade_date={partition_key}/part-000.parquet` | 2024-09-10 · 首个非空分区（`trade_date`） |
| `moneyflow_mkt_dc` | `moneyflow_mkt_dc` | `raw_tushare_moneyflow_mkt_dc` | Raw | 交易日 | `moneyflow_mkt_dc` | `raw/tushare/moneyflow_mkt_dc/trade_date={partition_key}/part-000.parquet` | 2023-04-17 · 首个非空分区（`trade_date`） |
| `moneyflow_mkt_dc` | `moneyflow_mkt_dc` | `silver_moneyflow_mkt_dc` | Silver | 交易日 | — | `silver/moneyflow/moneyflow_mkt_dc/trade_date={partition_key}/part-000.parquet` | 2023-04-17 · 首个非空分区（`trade_date`） |
| `moneyflow_ths` | `moneyflow_ths` | `raw_tushare_moneyflow_ths` | Raw | 交易日 | `moneyflow_ths` | `raw/tushare/moneyflow_ths/trade_date={partition_key}/part-000.parquet` | 2024-12-19 · 首个非空分区（`trade_date`） |
| `moneyflow_ths` | `moneyflow_ths` | `silver_moneyflow_ths` | Silver | 交易日 | — | `silver/moneyflow/moneyflow_ths/trade_date={partition_key}/part-000.parquet` | 2024-12-19 · 首个非空分区（`trade_date`） |
| `dc_daily` | `dc_daily` | `raw_tushare_dc_daily` | Raw | 交易日 | `dc_daily` | `raw/board/dc_daily/trade_date={partition_key}/part-000.parquet` | 2024-01-02 · 首个非空分区（`trade_date`） |
| `dc_daily` | `dc_daily` | `silver_dc_daily` | Silver | 交易日 | — | `silver/board/dc_daily/trade_date={partition_key}/part-000.parquet` | 2024-01-02 · 首个非空分区（`trade_date`） |
| `dc_daily_technical` | `dc_daily_technical` | `gold_dc_daily_technical` | Gold | 交易日 | — | `gold/board/dc_daily_technical/trade_date={partition_key}/part-000.parquet` | 2024-01-02 · 首个非空分区（`trade_date`） |
| `dc_daily_technical` | `ch_dc_daily_technical` | `ch_dc_daily_technical` | Serving | 交易日 | — | `goldenshare_serving.board_fact_technical_daily` | 本机 ClickHouse，已核实表存在 |
| `dc_index` | `dc_index` | `raw_tushare_dc_index` | Raw | 交易日 | `dc_index` | `raw/board/dc_index/trade_date={partition_key}/part-000.parquet` | 2024-12-20 · 首个非空分区（`trade_date`） |
| `dc_index` | `dc_index` | `silver_dc_index` | Silver | 交易日 | — | `silver/board/dc_index/trade_date={partition_key}/part-000.parquet` | 2024-12-20 · 首个非空分区（`trade_date`） |
| `dc_industry_hierarchy` | `dc_industry_hierarchy` | `silver_dc_industry_hierarchy` | Silver | 全量快照 | — | `silver/board/dc_industry_hierarchy/full/part-000.parquet` | 快照，已见非空文件 |
| `dc_member` | `dc_member` | `raw_tushare_dc_member` | Raw | 交易日 | `dc_member` | `raw/board/dc_member/trade_date={partition_key}/part-000.parquet` | 2024-12-20 · 首个非空分区（`trade_date`） |
| `dc_member` | `dc_member` | `silver_dc_member` | Silver | 交易日 | — | `silver/board/dc_member/trade_date={partition_key}/part-000.parquet` | 2024-12-20 · 首个非空分区（`trade_date`） |
| `market_breadth` | `market_breadth` | `gold_market_breadth_daily` | Gold | 交易日 | — | `gold/breadth/market_breadth_daily/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `market_breadth` | `ch_share_fact_market_breadth_daily` | `ch_share_fact_market_breadth_daily` | Serving | 交易日 | — | `goldenshare_serving.share_fact_market_breadth_daily` | 本机 ClickHouse，已核实表存在 |
| `stock_return_distribution` | `stock_return_distribution` | `gold_stock_return_distribution` | Gold | 交易日 | — | `gold/breadth/stock_return_distribution/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `wealth_market_turnover` | `wealth_market_turnover` | `gold_wealth_market_turnover` | Gold | 分钟快照（交易日） | — | `gold/wealth/market_turnover/trade_date={partition_key}/part-000.parquet` | 2014-01-02 · 首个非空分区（`trade_date`） |
| `anns_d` | `anns_d` | `raw_tushare_anns_d` | Raw | 公告日 | `anns_d` | `raw/tushare/anns_d/ann_date={partition_key}/part-000.parquet` | 2020-01-01 · 首个非空分区（`ann_date`） |

## 5. Prod 存储明细

同一个业务标识可有多个 Prod 维护键。同一登记键下的 Raw、标准层、目标表、业务表和观察版本按实际表名合并。下列日期只列本次成功取得的索引结果，空格以“—”表示。

| 英文标识 | Prod 登记键 / 发布资产 | 存储 | 用途 | 源接口 | 表或视图 | 行归属或范围 | 实查状态 | 核实的起点与日期字段 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bak_basic` | `bak_basic` | PostgreSQL | Raw | `bak_basic` | `raw_tushare.bak_basic` | — | 已核实表 | 2016-08-09 `trade_date` |
| `bak_basic` | `bak_basic` | PostgreSQL | Serving / 维护目标 | `bak_basic` | `core_serving_light.bak_basic` | — | 已核实视图 | — |
| `bse_mapping` | `bse_mapping` | PostgreSQL | Raw | `bse_mapping` | `raw_tushare.bse_mapping` | — | 已核实表 | — |
| `bse_mapping` | `bse_mapping` | PostgreSQL | Serving / 维护目标 | `bse_mapping` | `core_serving_light.bse_mapping` | — | 已核实视图 | — |
| `etf_basic` | `etf_basic` | PostgreSQL | Raw | `etf_basic` | `raw_tushare.etf_basic` | — | 已核实表 | — |
| `etf_basic` | `etf_basic` | PostgreSQL | Serving / 维护目标 | `etf_basic` | `core_serving.etf_basic` | — | 已核实表 | — |
| `hk_basic` | `hk_basic` | PostgreSQL | Raw | `hk_basic` | `raw_tushare.hk_basic` | — | 已核实表 | — |
| `hk_basic` | `hk_basic` | PostgreSQL | Serving / 维护目标 | `hk_basic` | `core_serving.hk_security` | — | 已核实表 | — |
| `namechange` | `namechange` | PostgreSQL | Raw | `namechange` | `raw_tushare.namechange` | — | 已核实表 | — |
| `namechange` | `namechange` | PostgreSQL | Serving / 维护目标 | `namechange` | `core_serving_light.namechange` | — | 已核实视图 | — |
| `st` | `st` | PostgreSQL | Raw | `st` | `raw_tushare.st` | — | 已核实表 | — |
| `st` | `st` | PostgreSQL | Serving / 维护目标 | `st` | `core_serving_light.st` | — | 已核实视图 | — |
| `stock_basic` | `stock_basic` | PostgreSQL | Raw | `stock_basic` | `raw_tushare.stock_basic` | — | 已核实表 | — |
| `stock_basic` | `stock_basic` | PostgreSQL | 标准层 | `stock_basic` | `core_multi.security_std` | 按 source_key 区分来源 | 已核实表 | — |
| `stock_basic` | `stock_basic` | PostgreSQL | Serving / 维护目标 | `stock_basic` | `core_serving.security_serving` | 多源合并结果 | 已核实表 | — |
| `stock_basic` | `stock_basic` | PostgreSQL | Raw | BIYING `stock_basic` | `raw_biying.stock_basic` | BIYING 来源 | 已核实表 | — |
| `stock_company` | `stock_company` | PostgreSQL | Raw | `stock_company` | `raw_tushare.stock_company` | — | 已核实表 | — |
| `stock_company` | `stock_company` | PostgreSQL | Serving / 维护目标 | `stock_company` | `core_serving_light.stock_company` | — | 已核实视图 | — |
| `trade_cal` | `trade_cal` | PostgreSQL | Raw | `trade_cal` | `raw_tushare.trade_cal` | — | 已核实表 | — |
| `trade_cal` | `trade_cal` | PostgreSQL | Serving / 维护目标 | `trade_cal` | `core_serving.trade_calendar` | — | 已核实表 | 1990-12-19 `trade_date` |
| `us_basic` | `us_basic` | PostgreSQL | Raw | `us_basic` | `raw_tushare.us_basic` | — | 已核实表 | — |
| `us_basic` | `us_basic` | PostgreSQL | Serving / 维护目标 | `us_basic` | `core_serving.us_security` | — | 已核实表 | — |
| `adj_factor` | `adj_factor` | PostgreSQL | Raw | `adj_factor` | `raw_tushare.adj_factor` | — | 已核实表 | — |
| `adj_factor` | `adj_factor` | PostgreSQL | 维护目标 | `adj_factor` | `core.equity_adj_factor` | — | 已核实表 | 2009-01-05 `trade_date` |
| `biying_equity_daily` | `biying_equity_daily` | PostgreSQL | Raw | `equity_daily_bar` | `raw_biying.equity_daily` | — | Prod 未找到此声明表 | — |
| `biying_equity_daily` | `biying_equity_daily` | PostgreSQL | 维护目标 | `equity_daily_bar` | `raw_biying.equity_daily_bar` | — | 已核实表 | 2025-01-02 `trade_date` |
| `block_trade` | `block_trade` | PostgreSQL | Raw | `block_trade` | `raw_tushare.block_trade` | — | 已核实表 | — |
| `block_trade` | `block_trade` | PostgreSQL | Serving / 维护目标 | `block_trade` | `core_serving.equity_block_trade` | — | 已核实表 | 2010-01-04 `trade_date` |
| `broker_recommend` | `broker_recommend` | PostgreSQL | Raw | `broker_recommend` | `raw_tushare.broker_recommend` | — | 已核实表 | — |
| `broker_recommend` | `broker_recommend` | PostgreSQL | Serving / 维护目标 | `broker_recommend` | `core_serving.broker_recommend` | — | 已核实表 | 2024-01 `month` |
| `cyq_chips` | `cyq_chips` | PostgreSQL | Raw / 维护目标 | `cyq_chips` | `raw_tushare.cyq_chips` | — | 已核实表 | 2018-01-02 `trade_date` |
| `cyq_chips` | `cyq_chips` | PostgreSQL | Serving | `cyq_chips` | `core_serving.equity_cyq_chips` | — | 已核实视图 | — |
| `cyq_perf` | `cyq_perf` | PostgreSQL | Raw / 维护目标 | `cyq_perf` | `raw_tushare.cyq_perf` | — | 已核实表 | 2018-01-02 `trade_date` |
| `cyq_perf` | `cyq_perf` | PostgreSQL | Serving | `cyq_perf` | `core_serving.equity_cyq_perf` | — | 已核实视图 | — |
| `daily` | `daily` | PostgreSQL | Raw | `daily` | `raw_tushare.daily` | — | 已核实表 | — |
| `daily` | `daily` | PostgreSQL | Serving / 维护目标 | `daily` | `core_serving.equity_daily_bar` | — | 已核实表 | 1990-12-19 `trade_date` |
| `daily` | `daily` | PostgreSQL | 轻量业务表 | `daily` | `core_serving_light.equity_daily_bar_light` | — | 已核实表 | — |
| `daily_basic` | `daily_basic` | PostgreSQL | Raw | `daily_basic` | `raw_tushare.daily_basic` | — | 已核实表 | — |
| `daily_basic` | `daily_basic` | PostgreSQL | Serving / 维护目标 | `daily_basic` | `core_serving.equity_daily_basic` | — | 已核实表 | 2010-01-04 `trade_date` |
| `equity_daily_snapshot` | `equity_daily_snapshot` | PostgreSQL | 业务产出 | — | `dm.equity_daily_snapshot` | — | 已核实表 | — |
| `limit_cpt_list` | `limit_cpt_list` | PostgreSQL | Raw | `limit_cpt_list` | `raw_tushare.limit_cpt_list` | — | 已核实表 | — |
| `limit_cpt_list` | `limit_cpt_list` | PostgreSQL | Serving / 维护目标 | `limit_cpt_list` | `core_serving.limit_cpt_list` | — | 已核实表 | 2023-11-13 `trade_date` |
| `limit_list_d` | `limit_list_d` | PostgreSQL | Raw | `limit_list_d` | `raw_tushare.limit_list` | — | 已核实表 | — |
| `limit_list_d` | `limit_list_d` | PostgreSQL | Serving / 维护目标 | `limit_list_d` | `core_serving.equity_limit_list` | — | 已核实表 | 2020-01-02 `trade_date` |
| `limit_list_ths` | `limit_list_ths` | PostgreSQL | Raw | `limit_list_ths` | `raw_tushare.limit_list_ths` | — | 已核实表 | — |
| `limit_list_ths` | `limit_list_ths` | PostgreSQL | Serving / 维护目标 | `limit_list_ths` | `core_serving.limit_list_ths` | — | 已核实表 | 2023-11-01 `trade_date` |
| `limit_step` | `limit_step` | PostgreSQL | Raw | `limit_step` | `raw_tushare.limit_step` | — | 已核实表 | — |
| `limit_step` | `limit_step` | PostgreSQL | Serving / 维护目标 | `limit_step` | `core_serving.limit_step` | — | 已核实表 | 2023-11-13 `trade_date` |
| `margin` | `margin` | PostgreSQL | Raw / 维护目标 | `margin` | `raw_tushare.margin` | — | 已核实表 | 2025-01-02 `trade_date` |
| `margin` | `margin` | PostgreSQL | Serving | `margin` | `core_serving.equity_margin` | — | 已核实视图 | — |
| `margin_detail` | `margin_detail` | PostgreSQL | Serving / 维护目标 | `margin_detail` | `core_serving.equity_margin_detail` | — | 已核实表 | — |
| `research_report` | `research_report` | PostgreSQL | Raw | `research_report` | `raw_tushare.research_report` | — | 已核实表 | 2020-01-01 `trade_date` |
| `research_report` | `research_report` | PostgreSQL | Serving / 维护目标 | `research_report` | `core_serving_light.research_report` | — | 已核实视图 | — |
| `stk_auction_c` | `stk_auction_c` | PostgreSQL | Raw / 维护目标 | `stk_auction_c` | `raw_tushare.stk_auction_c` | — | 已核实表 | 2025-01-02 `trade_date` |
| `stk_auction_c` | `stk_auction_c` | PostgreSQL | Serving | `stk_auction_c` | `core_serving.equity_auction_close` | — | 已核实视图 | — |
| `stk_auction_o` | `stk_auction_o` | PostgreSQL | Raw / 维护目标 | `stk_auction_o` | `raw_tushare.stk_auction_o` | — | 已核实表 | 2025-01-02 `trade_date` |
| `stk_auction_o` | `stk_auction_o` | PostgreSQL | Serving | `stk_auction_o` | `core_serving.equity_auction_open` | — | 已核实视图 | — |
| `stk_factor_pro` | `stk_factor_pro` | PostgreSQL | Raw | `stk_factor_pro` | `raw_tushare.stk_factor_pro` | — | 已核实表 | 2017-01-03 `trade_date` |
| `stk_factor_pro` | `stk_factor_pro` | PostgreSQL | Serving / 维护目标 | `stk_factor_pro` | `core_serving.equity_factor_pro` | — | 已核实视图 | — |
| `stk_limit` | `stk_limit` | PostgreSQL | Raw / 维护目标 | `stk_limit` | `raw_tushare.stk_limit` | — | 已核实表 | 2024-01-02 `trade_date` |
| `stk_limit` | `stk_limit` | PostgreSQL | Serving | `stk_limit` | `core_serving.equity_stk_limit` | — | 已核实视图 | — |
| `stk_mins` | `stk_mins` | PostgreSQL | Raw / 维护目标 | `stk_mins` | `raw_tushare.stk_mins` | — | 已核实表 | — |
| `stk_mins` | `stk_mins` | PostgreSQL | 业务查询视图 | `stk_mins` | `core_serving.equity_minute_bar` | — | 已核实视图 | — |
| `stk_nineturn` | `stk_nineturn` | PostgreSQL | Raw / 维护目标 | `stk_nineturn` | `raw_tushare.stk_nineturn` | — | 已核实表 | 2023-01-03 `trade_date` |
| `stk_nineturn` | `stk_nineturn` | PostgreSQL | Serving | `stk_nineturn` | `core_serving.equity_nineturn` | — | 已核实视图 | — |
| `stk_period_bar_adj_month` | `stk_period_bar_adj_month` | PostgreSQL | Raw | `stk_week_month_adj` | `raw_tushare.stk_period_bar_adj` | `freq=month` | 已核实表 | — |
| `stk_period_bar_adj_month` | `stk_period_bar_adj_month` | PostgreSQL | Serving / 维护目标 | `stk_week_month_adj` | `core_serving.stk_period_bar_adj` | `freq=month` | 已核实表 | 1997-05-31 `trade_date` `freq=month` |
| `stk_period_bar_adj_month` | `stk_period_bar_adj_month` | PostgreSQL | 交付记录 | `stk_week_month_adj` | `core.stock_period_adj_delivery` | `freq=month` | 已核实表 | — |
| `stk_period_bar_adj_week` | `stk_period_bar_adj_week` | PostgreSQL | Raw | `stk_week_month_adj` | `raw_tushare.stk_period_bar_adj` | `freq=week` | 已核实表 | — |
| `stk_period_bar_adj_week` | `stk_period_bar_adj_week` | PostgreSQL | Serving / 维护目标 | `stk_week_month_adj` | `core_serving.stk_period_bar_adj` | `freq=week` | 已核实表 | 1997-05-23 `trade_date` `freq=week` |
| `stk_period_bar_adj_week` | `stk_period_bar_adj_week` | PostgreSQL | 交付记录 | `stk_week_month_adj` | `core.stock_period_adj_delivery` | `freq=week` | 已核实表 | — |
| `stk_period_bar_month` | `stk_period_bar_month` | PostgreSQL | Raw | `stk_weekly_monthly` | `raw_tushare.stk_period_bar` | `freq=month` | 已核实表 | — |
| `stk_period_bar_month` | `stk_period_bar_month` | PostgreSQL | Serving / 维护目标 | `stk_weekly_monthly` | `core_serving.stk_period_bar` | `freq=month` | 已核实表 | 2010-01-31 `trade_date` `freq=month` |
| `stk_period_bar_week` | `stk_period_bar_week` | PostgreSQL | Raw | `stk_weekly_monthly` | `raw_tushare.stk_period_bar` | `freq=week` | 已核实表 | — |
| `stk_period_bar_week` | `stk_period_bar_week` | PostgreSQL | Serving / 维护目标 | `stk_weekly_monthly` | `core_serving.stk_period_bar` | `freq=week` | 已核实表 | 2010-01-01 `trade_date` `freq=week` |
| `stock_daily_qfq_nineturn` | `prod_core_stock_daily_qfq_nineturn` | PostgreSQL | Serving | — | `core_serving.equity_qfq_nineturn_daily` | DG 发布 | 已核实表 | 2014-01-02 `trade_date` |
| `stock_st` | `stock_st` | PostgreSQL | Raw | `stock_st` | `raw_tushare.stock_st` | — | 已核实表 | — |
| `stock_st` | `stock_st` | PostgreSQL | Serving / 维护目标 | `stock_st` | `core_serving.equity_stock_st` | — | 已核实表 | 2016-08-09 `trade_date` |
| `suspend_d` | `suspend_d` | PostgreSQL | Raw / 维护目标 | `suspend_d` | `raw_tushare.suspend_d` | — | 已核实表 | 2000-01-04 `trade_date` |
| `suspend_d` | `suspend_d` | PostgreSQL | Serving | `suspend_d` | `core_serving.equity_suspend_d` | — | 已核实视图 | — |
| `top_list` | `top_list` | PostgreSQL | Raw | `top_list` | `raw_tushare.top_list` | — | 已核实表 | — |
| `top_list` | `top_list` | PostgreSQL | Serving / 维护目标 | `top_list` | `core_serving.equity_top_list` | — | 已核实表 | 2016-01-04 `trade_date` |
| `etf_index` | `etf_index` | PostgreSQL | Raw | `etf_index` | `raw_tushare.etf_index` | — | 已核实表 | — |
| `etf_index` | `etf_index` | PostgreSQL | Serving / 维护目标 | `etf_index` | `core_serving.etf_index` | — | 已核实表 | — |
| `etf_mins` | `etf_mins` | PostgreSQL | Raw / 维护目标 | `etf_mins` | `raw_tushare.etf_minute_bar` | — | 已核实表 | — |
| `etf_sh_cons` | `etf_sh_cons` | PostgreSQL | Raw / 维护目标 | `etf_sh_cons` | `raw_tushare.etf_sh_cons` | — | 已核实表 | 2026-01-05 `trade_date` |
| `etf_sh_cons` | `etf_sh_cons` | PostgreSQL | Serving | `etf_sh_cons` | `core_serving.etf_sh_cons` | — | 已核实视图 | — |
| `etf_share_size` | `etf_share_size` | PostgreSQL | Raw / 维护目标 | `etf_share_size` | `raw_tushare.etf_share_size` | — | 已核实表 | 2026-01-05 `trade_date` |
| `etf_share_size` | `etf_share_size` | PostgreSQL | Serving | `etf_share_size` | `core_serving.etf_share_size` | — | 已核实视图 | — |
| `etf_sz_cons` | `etf_sz_cons` | PostgreSQL | Raw / 维护目标 | `etf_sz_cons` | `raw_tushare.etf_sz_cons` | — | 已核实表 | 2026-01-05 `trade_date` |
| `etf_sz_cons` | `etf_sz_cons` | PostgreSQL | Serving | `etf_sz_cons` | `core_serving.etf_sz_cons` | — | 已核实视图 | — |
| `fund_adj` | `fund_adj` | PostgreSQL | Raw | `fund_adj` | `raw_tushare.fund_adj` | — | 已核实表 | — |
| `fund_adj` | `fund_adj` | PostgreSQL | 维护目标 | `fund_adj` | `core.fund_adj_factor` | — | 已核实表 | 2016-01-04 `trade_date` |
| `fund_daily` | `fund_daily` | PostgreSQL | Raw | `fund_daily` | `raw_tushare.fund_daily` | — | 已核实表 | — |
| `fund_daily` | `fund_daily` | PostgreSQL | Serving / 维护目标 | `fund_daily` | `core_serving.fund_daily_bar` | — | 已核实表 | 2016-01-04 `trade_date` |
| `idx_factor_pro` | `idx_factor_pro` | PostgreSQL | Raw | `idx_factor_pro` | `raw_tushare.idx_factor_pro` | — | 已核实表 | 2010-01-04 `trade_date` |
| `idx_factor_pro` | `idx_factor_pro` | PostgreSQL | Serving / 维护目标 | `idx_factor_pro` | `core_serving.index_factor_pro` | — | 已核实视图 | — |
| `index_basic` | `index_basic` | PostgreSQL | Raw | `index_basic` | `raw_tushare.index_basic` | — | 已核实表 | — |
| `index_basic` | `index_basic` | PostgreSQL | Serving / 维护目标 | `index_basic` | `core_serving.index_basic` | — | 已核实表 | — |
| `index_daily` | `index_daily` | PostgreSQL | Raw | `index_daily` | `raw_tushare.index_daily` | — | 已核实表 | — |
| `index_daily` | `index_daily` | PostgreSQL | Serving / 维护目标 | `index_daily` | `core_serving.index_daily_serving` | — | 已核实表 | 1991-07-15 `trade_date` |
| `index_daily_basic` | `index_daily_basic` | PostgreSQL | Raw | `index_dailybasic` | `raw_tushare.index_daily_basic` | — | 已核实表 | — |
| `index_daily_basic` | `index_daily_basic` | PostgreSQL | Serving / 维护目标 | `index_dailybasic` | `core_serving.index_daily_basic` | — | 已核实表 | 2020-01-02 `trade_date` |
| `index_mins` | `index_mins` | PostgreSQL | Raw / 维护目标 | `idx_mins` | `raw_tushare.index_mins` | — | 已核实表 | 2025-01-02 `trade_time` `freq=1min`<br>2025-01-02 `trade_time` `freq=5min`<br>2025-01-02 `trade_time` `freq=15min`<br>2025-01-02 `trade_time` `freq=30min`<br>2025-01-02 `trade_time` `freq=60min` |
| `index_mins` | `index_mins` | PostgreSQL | 业务查询视图 | `idx_mins` | `core_serving.index_minute_bar` | — | 已核实视图 | — |
| `index_monthly` | `index_monthly` | PostgreSQL | Raw / 维护目标 | `index_monthly` | `raw_tushare.index_monthly_bar` | — | 已核实表 | — |
| `index_monthly` | `index_monthly_serving` | PostgreSQL | 业务产出 | — | `core_serving.index_monthly_serving` | — | 已核实表 | 1991-07-31 `trade_date` |
| `index_monthly` | `index_monthly` | PostgreSQL | 历史 Core 表（当前物理存在） | `index_monthly` | `core.index_monthly_bar` | 现行维护目标见主表 | 已核实表 | — |
| `index_weekly` | `index_weekly` | PostgreSQL | Raw / 维护目标 | `index_weekly` | `raw_tushare.index_weekly_bar` | — | 已核实表 | — |
| `index_weekly` | `index_weekly_serving` | PostgreSQL | 业务产出 | — | `core_serving.index_weekly_serving` | — | 已核实表 | 1991-07-19 `trade_date` |
| `index_weekly` | `index_weekly` | PostgreSQL | 历史 Core 表（当前物理存在） | `index_weekly` | `core.index_weekly_bar` | 现行维护目标见主表 | 已核实表 | — |
| `index_weight` | `index_weight` | PostgreSQL | Raw | `index_weight` | `raw_tushare.index_weight` | — | 已核实表 | — |
| `index_weight` | `index_weight` | PostgreSQL | Serving / 维护目标 | `index_weight` | `core_serving.index_weight` | — | 已核实表 | — |
| `major_index_daily_nineturn` | `prod_core_index_daily_nineturn` | PostgreSQL | Serving | — | `core_serving.index_nineturn_daily` | DG 发布 | 已核实表 | 2000-01-04 `trade_date` |
| `fund_basic` | `fund_basic` | PostgreSQL | Serving / 维护目标 | `fund_basic` | `core_serving.fund_basic_current` | — | 已核实表 | — |
| `fund_basic` | `fund_basic` | PostgreSQL | 观察版本 | `fund_basic` | `core_serving.fund_basic_observation` | — | 已核实表 | — |
| `fund_company` | `fund_company` | PostgreSQL | Serving / 维护目标 | `fund_company` | `core_serving.fund_company_current` | — | 已核实表 | — |
| `fund_company` | `fund_company` | PostgreSQL | 观察版本 | `fund_company` | `core_serving.fund_company_observation` | — | 已核实表 | — |
| `fund_div` | `fund_div` | PostgreSQL | Serving / 维护目标 | `fund_div` | `core_serving.fund_div` | — | 已核实表 | 2020-12-15 `ann_date` |
| `fund_manager` | `fund_manager` | PostgreSQL | Serving / 维护目标 | `fund_manager` | `core_serving.fund_manager_current` | — | 已核实表 | — |
| `fund_manager` | `fund_manager` | PostgreSQL | 观察版本 | `fund_manager` | `core_serving.fund_manager_observation` | — | 已核实表 | — |
| `fund_portfolio` | `fund_portfolio` | PostgreSQL | Serving / 维护目标 | `fund_portfolio` | `core_serving.fund_portfolio` | — | 已核实表 | — |
| `fund_portfolio` | `fund_portfolio` | PostgreSQL | 发布暂存 | `fund_portfolio` | `foundation.fund_portfolio_stage` | — | 已核实表 | — |
| `fund_share` | `fund_share` | PostgreSQL | Serving / 维护目标 | `fund_share` | `core_serving.fund_share_current` | — | 已核实表 | 2014-01-02 `trade_date` |
| `fund_share` | `fund_share` | PostgreSQL | 观察版本 | `fund_share` | `core_serving.fund_share_observation` | — | 已核实表 | — |
| `mkt_idx_bmk` | `mkt_idx_bmk` | PostgreSQL | Serving / 维护目标 | `mkt_idx_bmk` | `core_serving.mkt_idx_bmk_current` | — | 已核实表 | — |
| `mkt_idx_bmk` | `mkt_idx_bmk` | PostgreSQL | 观察版本 | `mkt_idx_bmk` | `core_serving.mkt_idx_bmk_observation` | — | 已核实表 | — |
| `moneyflow` | `biying_moneyflow` | PostgreSQL | Raw | `moneyflow` | `raw_biying.moneyflow` | — | 已核实表 | 2025-04-15 `trade_date` |
| `moneyflow` | `biying_moneyflow` | PostgreSQL | 标准层 | `moneyflow` | `core_multi.moneyflow_std` | `source_key=biying` | 已核实表 | — |
| `moneyflow` | `biying_moneyflow` | PostgreSQL | Serving / 维护目标 | `moneyflow` | `core_serving.equity_moneyflow` | 多源融合结果 | 已核实表 | — |
| `moneyflow` | `moneyflow` | PostgreSQL | Raw | `moneyflow` | `raw_tushare.moneyflow` | — | 已核实表 | 2010-01-04 `trade_date` |
| `moneyflow` | `moneyflow` | PostgreSQL | 标准层 | `moneyflow` | `core_multi.moneyflow_std` | `source_key=tushare` | 已核实表 | — |
| `moneyflow` | `moneyflow` | PostgreSQL | Serving / 维护目标 | `moneyflow` | `core_serving.equity_moneyflow` | 多源融合结果 | 已核实表 | — |
| `moneyflow_cnt_ths` | `moneyflow_cnt_ths` | PostgreSQL | Raw / 维护目标 | `moneyflow_cnt_ths` | `raw_tushare.moneyflow_cnt_ths` | — | 已核实表 | 2024-09-10 `trade_date` |
| `moneyflow_cnt_ths` | `moneyflow_cnt_ths` | PostgreSQL | Serving | `moneyflow_cnt_ths` | `core_serving.concept_moneyflow_ths` | — | 已核实视图 | — |
| `moneyflow_dc` | `moneyflow_dc` | PostgreSQL | Raw / 维护目标 | `moneyflow_dc` | `raw_tushare.moneyflow_dc` | — | 已核实表 | 2023-09-11 `trade_date` |
| `moneyflow_dc` | `moneyflow_dc` | PostgreSQL | Serving | `moneyflow_dc` | `core_serving.equity_moneyflow_dc` | — | 已核实视图 | — |
| `moneyflow_ind_dc` | `moneyflow_ind_dc` | PostgreSQL | Raw / 维护目标 | `moneyflow_ind_dc` | `raw_tushare.moneyflow_ind_dc` | — | 已核实表 | 2023-09-12 `trade_date` |
| `moneyflow_ind_dc` | `moneyflow_ind_dc` | PostgreSQL | Serving | `moneyflow_ind_dc` | `core_serving.board_moneyflow_dc` | — | 已核实视图 | — |
| `moneyflow_ind_ths` | `moneyflow_ind_ths` | PostgreSQL | Raw / 维护目标 | `moneyflow_ind_ths` | `raw_tushare.moneyflow_ind_ths` | — | 已核实表 | 2024-09-10 `trade_date` |
| `moneyflow_ind_ths` | `moneyflow_ind_ths` | PostgreSQL | Serving | `moneyflow_ind_ths` | `core_serving.industry_moneyflow_ths` | — | 已核实视图 | — |
| `moneyflow_mkt_dc` | `moneyflow_mkt_dc` | PostgreSQL | Raw / 维护目标 | `moneyflow_mkt_dc` | `raw_tushare.moneyflow_mkt_dc` | — | 已核实表 | 2023-04-17 `trade_date` |
| `moneyflow_mkt_dc` | `moneyflow_mkt_dc` | PostgreSQL | Serving | `moneyflow_mkt_dc` | `core_serving.market_moneyflow_dc` | — | 已核实视图 | — |
| `moneyflow_ths` | `moneyflow_ths` | PostgreSQL | Raw / 维护目标 | `moneyflow_ths` | `raw_tushare.moneyflow_ths` | — | 已核实表 | 2024-12-19 `trade_date` |
| `moneyflow_ths` | `moneyflow_ths` | PostgreSQL | Serving | `moneyflow_ths` | `core_serving.equity_moneyflow_ths` | — | 已核实视图 | — |
| `dc_daily` | `dc_daily` | PostgreSQL | Raw / 维护目标 | `dc_daily` | `raw_tushare.dc_daily` | — | 已核实表 | 2024-01-02 `trade_date` |
| `dc_daily` | `dc_daily` | PostgreSQL | Serving | `dc_daily` | `core_serving.dc_daily` | — | 已核实视图 | — |
| `dc_daily_technical` | `prod_ch_dc_daily_technical` | ClickHouse | Serving | — | `goldenshare_serving.board_fact_technical_daily` | DG 发布 | Prod 已登记，连接未接通 | — |
| `dc_hot` | `dc_hot` | PostgreSQL | Raw | `dc_hot` | `raw_tushare.dc_hot` | — | 已核实表 | — |
| `dc_hot` | `dc_hot` | PostgreSQL | Serving / 维护目标 | `dc_hot` | `core_serving.dc_hot` | — | 已核实表 | 2024-03-20 `trade_date` |
| `dc_index` | `dc_index` | PostgreSQL | Raw | `dc_index` | `raw_tushare.dc_index` | — | 已核实表 | — |
| `dc_index` | `dc_index` | PostgreSQL | Serving / 维护目标 | `dc_index` | `core_serving.dc_index` | — | 已核实表 | 2024-12-20 `trade_date` |
| `dc_industry_hierarchy` | `prod_core_wealth_sector_hierarchy` | PostgreSQL | Serving | — | `core_serving.wealth_sector_hierarchy` | DG 发布 | 已核实表 | — |
| `dc_member` | `dc_member` | PostgreSQL | Raw | `dc_member` | `raw_tushare.dc_member` | — | 已核实表 | — |
| `dc_member` | `dc_member` | PostgreSQL | Serving / 维护目标 | `dc_member` | `core_serving.dc_member` | — | 已核实表 | 2024-12-20 `trade_date` |
| `index_classify` | `index_classify` | PostgreSQL | Serving / 维护目标 | `index_classify` | `core_serving.sw_industry_classification` | — | 已核实表 | — |
| `index_member_all` | `index_member_all` | PostgreSQL | Serving / 维护目标 | `index_member_all` | `core_serving.sw_industry_member` | — | 已核实表 | — |
| `kpl_concept_cons` | `kpl_concept_cons` | PostgreSQL | Raw | `kpl_concept_cons` | `raw_tushare.kpl_concept_cons` | — | 已核实表 | — |
| `kpl_concept_cons` | `kpl_concept_cons` | PostgreSQL | Serving / 维护目标 | `kpl_concept_cons` | `core_serving.kpl_concept_cons` | — | 已核实表 | 2024-10-14 `trade_date` |
| `kpl_list` | `kpl_list` | PostgreSQL | Raw | `kpl_list` | `raw_tushare.kpl_list` | — | 已核实表 | — |
| `kpl_list` | `kpl_list` | PostgreSQL | Serving / 维护目标 | `kpl_list` | `core_serving.kpl_list` | — | 已核实表 | 2025-01-02 `trade_date` |
| `sw_daily` | `sw_daily` | PostgreSQL | Serving / 维护目标 | `sw_daily` | `core_serving.sw_industry_daily` | — | 已核实表 | 2025-01-02 `trade_date` |
| `ths_daily` | `ths_daily` | PostgreSQL | Raw | `ths_daily` | `raw_tushare.ths_daily` | — | 已核实表 | — |
| `ths_daily` | `ths_daily` | PostgreSQL | Serving / 维护目标 | `ths_daily` | `core_serving.ths_daily` | — | 已核实表 | 2020-01-02 `trade_date` |
| `ths_hot` | `ths_hot` | PostgreSQL | Raw | `ths_hot` | `raw_tushare.ths_hot` | — | 已核实表 | — |
| `ths_hot` | `ths_hot` | PostgreSQL | Serving / 维护目标 | `ths_hot` | `core_serving.ths_hot` | — | 已核实表 | 2025-01-02 `trade_date` |
| `ths_index` | `ths_index` | PostgreSQL | Raw | `ths_index` | `raw_tushare.ths_index` | — | 已核实表 | — |
| `ths_index` | `ths_index` | PostgreSQL | Serving / 维护目标 | `ths_index` | `core_serving.ths_index` | — | 已核实表 | — |
| `ths_member` | `ths_member` | PostgreSQL | Raw | `ths_member` | `raw_tushare.ths_member` | — | 已核实表 | — |
| `ths_member` | `ths_member` | PostgreSQL | Serving / 维护目标 | `ths_member` | `core_serving.ths_member` | — | 已核实表 | — |
| `wealth_sector_daily_insight_item` | `wealth_sector_daily_insight_item` | PostgreSQL | 业务产出 | — | `core_serving.wealth_sector_daily_insight_item` | — | 已核实表 | — |
| `wealth_sector_daily_insight_summary` | `wealth_sector_daily_insight_summary` | PostgreSQL | 业务产出 | — | `core_serving.wealth_sector_daily_insight_summary` | — | 已核实表 | — |
| `wealth_sector_dual_momentum_daily` | `wealth_sector_dual_momentum_daily` | PostgreSQL | 业务产出 | — | `core_serving.wealth_sector_dual_momentum_daily` | — | 已核实表 | 2025-08-22 `trade_date` |
| `wealth_sector_heat_daily` | `wealth_sector_heat_daily` | PostgreSQL | 业务产出 | — | `core_serving.wealth_sector_heat_daily` | — | 已核实表 | 2026-05-20 `trade_date` |
| `wealth_sector_member_breadth_daily` | `wealth_sector_member_breadth_daily` | PostgreSQL | 业务产出 | — | `core_serving.wealth_sector_member_breadth_daily` | — | 已核实表 | 2025-08-22 `trade_date` |
| `wealth_sector_member_ma_breadth_daily` | `wealth_sector_member_ma_breadth_daily` | PostgreSQL | 业务产出 | — | `core_serving.wealth_sector_member_ma_breadth_daily` | — | 已核实表 | 2025-08-22 `trade_date` |
| `wealth_sector_momentum_daily` | `wealth_sector_momentum_daily` | PostgreSQL | 业务产出 | — | `core_serving.wealth_sector_momentum_daily` | — | 已核实表 | 2025-08-22 `trade_date` |
| `wealth_sector_price_volume_daily` | `wealth_sector_price_volume_daily` | PostgreSQL | 业务产出 | — | `core_serving.wealth_sector_price_volume_daily` | — | 已核实表 | 2025-08-22 `trade_date` |
| `wealth_sector_relative_rotation_daily` | `wealth_sector_relative_rotation_daily` | PostgreSQL | 业务产出 | — | `core_serving.wealth_sector_relative_rotation_daily` | — | 已核实表 | 2025-08-22 `trade_date` |
| `market_breadth` | `prod_ch_share_fact_market_breadth_daily` | ClickHouse | Serving | — | `goldenshare_serving.share_fact_market_breadth_daily` | DG 发布 | Prod 已登记，连接未接通 | — |
| `stock_return_distribution` | `prod_ch_share_fact_market_breadth_daily` | ClickHouse | 发布表中的涨跌幅分布字段 | — | `goldenshare_serving.share_fact_market_breadth_daily` | 与市场宽度共表 | Prod 已登记，连接未接通 | — |
| `wealth_market_turnover` | `prod_core_wealth_market_turnover` | PostgreSQL | Serving | — | `core_serving.wealth_market_turnover_snapshot` | DG 发布 | 已核实表 | — |
| `balancesheet` | `balancesheet` | PostgreSQL | Raw / 维护目标 | `balancesheet_vip` | `raw_tushare.balancesheet` | — | 已核实表 | 2022-01-01 `ann_date` |
| `balancesheet` | `balancesheet` | PostgreSQL | Serving | `balancesheet_vip` | `core_serving.equity_balancesheet` | — | 已核实视图 | — |
| `cashflow` | `cashflow` | PostgreSQL | Raw / 维护目标 | `cashflow_vip` | `raw_tushare.cashflow` | — | 已核实表 | 2022-01-01 `ann_date` |
| `cashflow` | `cashflow` | PostgreSQL | Serving | `cashflow_vip` | `core_serving.equity_cashflow` | — | 已核实视图 | — |
| `dividend` | `dividend` | PostgreSQL | Raw | `dividend` | `raw_tushare.dividend` | — | 已核实表 | — |
| `dividend` | `dividend` | PostgreSQL | Serving / 维护目标 | `dividend` | `core_serving.equity_dividend` | — | 已核实表 | 1991-03-17 `ann_date` |
| `express` | `express` | PostgreSQL | Serving / 维护目标 | `express_vip` | `core_serving.equity_express` | — | 已核实表 | 2010-01-05 `ann_date` |
| `fina_indicator` | `fina_indicator` | PostgreSQL | Raw / 维护目标 | `fina_indicator_vip` | `raw_tushare.fina_indicator` | — | 已核实表 | 2022-01-01 `ann_date` |
| `fina_indicator` | `fina_indicator` | PostgreSQL | Serving | `fina_indicator_vip` | `core_serving.equity_fina_indicator` | — | 已核实视图 | — |
| `income` | `income` | PostgreSQL | Raw / 维护目标 | `income_vip` | `raw_tushare.income` | — | 已核实表 | 2022-01-01 `ann_date` |
| `income` | `income` | PostgreSQL | Serving | `income_vip` | `core_serving.equity_income` | — | 已核实视图 | — |
| `stk_holdernumber` | `stk_holdernumber` | PostgreSQL | Raw | `stk_holdernumber` | `raw_tushare.holdernumber` | — | 已核实表 | — |
| `stk_holdernumber` | `stk_holdernumber` | PostgreSQL | Serving / 维护目标 | `stk_holdernumber` | `core_serving.equity_holder_number` | — | 已核实表 | — |
| `anns_d` | `anns_d` | PostgreSQL | Raw | `anns_d` | `raw_tushare.anns_d` | — | 已核实表 | 2020-01-01 `ann_date` |
| `anns_d` | `anns_d` | PostgreSQL | Serving / 维护目标 | `anns_d` | `core_serving_light.anns_d` | — | 已核实视图 | — |
| `cctv_news` | `cctv_news` | PostgreSQL | Raw | `cctv_news` | `raw_tushare.cctv_news` | — | 已核实表 | 2020-01-01 `date` |
| `cctv_news` | `cctv_news` | PostgreSQL | Serving / 维护目标 | `cctv_news` | `core_serving_light.cctv_news` | — | 已核实视图 | — |
| `irm_qa_sh` | `irm_qa_sh` | PostgreSQL | Raw | `irm_qa_sh` | `raw_tushare.irm_qa_sh` | — | 已核实表 | 2025-01-14 `pub_time` |
| `irm_qa_sh` | `irm_qa_sh` | PostgreSQL | Serving / 维护目标 | `irm_qa_sh` | `core_serving_light.irm_qa_sh` | — | 已核实视图 | — |
| `irm_qa_sz` | `irm_qa_sz` | PostgreSQL | Raw | `irm_qa_sz` | `raw_tushare.irm_qa_sz` | — | 已核实表 | 2020-12-31 `pub_time` |
| `irm_qa_sz` | `irm_qa_sz` | PostgreSQL | Serving / 维护目标 | `irm_qa_sz` | `core_serving_light.irm_qa_sz` | — | 已核实视图 | — |
| `major_news` | `major_news` | PostgreSQL | Raw | `major_news` | `raw_tushare.major_news` | — | 已核实表 | 2026-01-01 `pub_time` |
| `major_news` | `major_news` | PostgreSQL | Serving / 维护目标 | `major_news` | `core_serving_light.major_news` | — | 已核实视图 | — |
| `news` | `news` | PostgreSQL | Raw | `news` | `raw_tushare.news` | — | 已核实表 | 2022-01-01 `news_time` |
| `news` | `news` | PostgreSQL | Serving / 维护目标 | `news` | `core_serving_light.news` | — | 已核实视图 | — |
| `news_stock_link` | `news_stock_link` | PostgreSQL | 业务产出 | — | `core_serving.news_stock_link` | — | 已核实表 | — |

## 6. 取证范围

- **DG。** 187 个资产键与隔离加载结果逐项一致。按登记路径读取了 182 份 Parquet 页脚，178 个路径均有非空文件。对日期分区按日期由早到晚读取候选页脚，对按股票与年份存放的文件只核对限定的股票及年度样本。没有读取 Parquet 数据页。[路径定义](../../lake_console/orchestrator/src/orchestrator/defs/paths.py)
- **Prod PostgreSQL。** 实查上表涉及的 197 张表或视图，另发现 1 个 Raw 声明名与物理表名不一致。对 77 张有合适索引的表共返回 83 个日期值，单查询只读日期并返回最多 1 行。月份值保留月精度，分钟时间戳在本表只显示日期。这些结果仅用于确认对应表的起点，覆盖、质量和最新日期需要另外核验。[Prod 日期字段与表映射定义](../../src/foundation/datasets/models.py)
- **ClickHouse。** 本机确认两张发布表存在；Prod 已登记同名目标表，本次配置的连接端口拒绝连接，表存在与起点仍待实查。[市场宽度迁移](../../lake_console/orchestrator/clickhouse_migrations/sql/V2__create_share_fact_market_breadth_daily.sql) · [板块日线技术指标迁移](../../lake_console/orchestrator/clickhouse_migrations/sql/V4__create_dc_daily_technical.sql)
- **台账范围。** 覆盖当前三个登记入口及核对过的直接存储，包含已登记的指标计算状态文件。板块每日分析发布控制表、公告迁移和同步台账、PostgreSQL 子分区不作为新业务数据集。表中的中文名与合并关系属于本次目录建议。
