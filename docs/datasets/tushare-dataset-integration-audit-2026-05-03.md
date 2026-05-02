# Tushare 数据集接入盘点（2026-05-03）

## 审计范围

- Tushare 文档基线：`docs/sources/tushare/docs_index.csv`，共 207 篇文档。
- 接入口径：`src/foundation/datasets/**` 中已进入 `list_dataset_definitions()` 的 `DatasetDefinition`，且 `source.source_keys` 包含 `tushare`。
- 本文统计的是“文档对应的 Tushare 数据集是否已进入当前数据集注册表”，不额外推断业务是否已经开放到页面或运营流程。

## 映射规则

- 默认按 `DatasetDefinition.source.api_name == docs_index.csv.api_name` 建立文档与内部数据集映射。
- 对 3 组同名 `api_name` 做了代码级人工收敛：
  - `trade_cal` 计入 `0026 交易日历` 和 `0137 交易日历` 两篇文档，因为当前内部定义是泛交易所日历能力。
  - `index_daily` 只计入 `0095 指数日线行情`，不计 `0155 南华期货指数日线行情`。
  - `stk_mins` 只计入 `0370 股票历史分钟行情`，不计 `0387 ETF历史分钟行情`。
- `0315 / 0316 / 0317` 由用户确认线上文档已不存在；本文仍按当前本地文档基线保留在“未接入”清单。

## 总览统计

| 指标 | 数值 |
| --- | ---: |
| Tushare 文档总数 | 207 |
| 已接入文档数 | 56 |
| 未接入文档数 | 151 |
| Tushare DatasetDefinition 数 | 57 |
| 一文多内部数据集 | 2（0336、0365） |
| 一内部数据集多文档入口 | 1（trade_cal -> 0026、0137） |

## 分类统计

| 分类 | 文档数 | 已接入 | 未接入 |
| --- | ---: | ---: | ---: |
| 公募基金 | 8 | 0 | 8 |
| 股票数据 / 基础数据 | 13 | 3 | 10 |
| 股票数据 / 行情数据 | 23 | 8 | 15 |
| 股票数据 / 财务数据 | 10 | 1 | 9 |
| 股票数据 / 资金流向数据 | 8 | 7 | 1 |
| 股票数据 / 两融及转融通 | 7 | 1 | 6 |
| 股票数据 / 参考数据 | 14 | 2 | 12 |
| 指数专题 | 19 | 6 | 13 |
| 股票数据 / 打板专题数据 | 24 | 15 | 9 |
| ETF专题 | 9 | 4 | 5 |
| 期货数据 | 14 | 1 | 13 |
| 大模型语料专题数据 | 8 | 2 | 6 |
| 债券专题 | 17 | 0 | 17 |
| 股票数据 / 特色数据 | 13 | 4 | 9 |
| 港股数据 | 11 | 1 | 10 |
| 美股数据 | 9 | 1 | 8 |

## 已接入清单

### 股票数据 / 基础数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 25 | 股票基础信息 | `stock_basic` | `stock_basic` 股票主数据 | `core_serving.security_serving` |  |
| 26 | 交易日历 | `trade_cal` | `trade_cal` 交易日历 | `core_serving.trade_calendar` | 与 0137 共用同一个 `trade_cal` DatasetDefinition。 |
| 397 | ST股票列表 | `stock_st` | `stock_st` ST股票列表 | `core_serving.equity_stock_st` |  |

### 股票数据 / 行情数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 27 | A股日线行情 | `daily` | `daily` 股票日线 | `core_serving.equity_daily_bar` |  |
| 28 | 复权因子 | `adj_factor` | `adj_factor` 复权因子 | `core.equity_adj_factor` |  |
| 32 | 每日指标 | `daily_basic` | `daily_basic` 每日指标 | `core_serving.equity_daily_basic` |  |
| 183 | 每日涨跌停价格 | `stk_limit` | `stk_limit` 每日涨跌停价格 | `core_serving.equity_stk_limit` |  |
| 214 | 每日停复牌信息 | `suspend_d` | `suspend_d` 每日停复牌信息 | `core_serving.equity_suspend_d` |  |
| 336 | 股票周/月线行情(每日更新) | `stk_weekly_monthly` | `stk_period_bar_month` 股票月线行情<br>`stk_period_bar_week` 股票周线行情 | `core_serving.stk_period_bar`<br>`core_serving.stk_period_bar` | 同一篇文档拆成两个内部数据集：周线 / 月线。 |
| 365 | 股票周/月线行情(复权--每日更新) | `stk_week_month_adj` | `stk_period_bar_adj_month` 股票月线行情（复权）<br>`stk_period_bar_adj_week` 股票周线行情（复权） | `core_serving.stk_period_bar_adj`<br>`core_serving.stk_period_bar_adj` | 同一篇文档拆成两个内部数据集：复权周线 / 复权月线。 |
| 370 | 股票历史分钟行情 | `stk_mins` | `stk_mins` 股票历史分钟行情 | `raw_tushare.stk_mins` |  |

### 股票数据 / 财务数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 103 | 分红送股 | `dividend` | `dividend` 分红送股 | `core_serving.equity_dividend` |  |

### 股票数据 / 资金流向数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 170 | 个股资金流向 | `moneyflow` | `moneyflow` 个股资金流向 | `core_serving.equity_moneyflow` |  |
| 343 | 同花顺行业资金流向（THS） | `moneyflow_ind_ths` | `moneyflow_ind_ths` 行业资金流向(THS) | `core_serving.industry_moneyflow_ths` |  |
| 344 | 东财概念及行业板块资金流向（DC） | `moneyflow_ind_dc` | `moneyflow_ind_dc` 板块资金流向(DC) | `core_serving.board_moneyflow_dc` |  |
| 345 | 大盘资金流向（DC） | `moneyflow_mkt_dc` | `moneyflow_mkt_dc` 市场资金流向(DC) | `core_serving.market_moneyflow_dc` |  |
| 348 | 个股资金流向（THS） | `moneyflow_ths` | `moneyflow_ths` 个股资金流向(THS) | `core_serving.equity_moneyflow_ths` |  |
| 349 | 个股资金流向（DC） | `moneyflow_dc` | `moneyflow_dc` 个股资金流向(DC) | `core_serving.equity_moneyflow_dc` |  |
| 371 | 同花顺概念板块资金流向（THS） | `moneyflow_cnt_ths` | `moneyflow_cnt_ths` 概念板块资金流向(THS) | `core_serving.concept_moneyflow_ths` |  |

### 股票数据 / 两融及转融通

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 58 | 融资融券交易汇总 | `margin` | `margin` 融资融券汇总 | `core_serving.equity_margin` |  |

### 股票数据 / 参考数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 161 | 大宗交易 | `block_trade` | `block_trade` 大宗交易 | `core_serving.equity_block_trade` |  |
| 166 | 股东人数 | `stk_holdernumber` | `stk_holdernumber` 股东户数 | `core_serving.equity_holder_number` |  |

### 指数专题

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 94 | 指数基本信息 | `index_basic` | `index_basic` 指数基础信息 | `core_serving.index_basic` |  |
| 95 | 指数日线行情 | `index_daily` | `index_daily` 指数日线行情 | `core_serving.index_daily_serving` |  |
| 96 | 指数成分和权重 | `index_weight` | `index_weight` 指数成分权重 | `core_serving.index_weight` |  |
| 128 | 大盘指数每日指标 | `index_dailybasic` | `index_daily_basic` 指数每日指标 | `core_serving.index_daily_basic` |  |
| 171 | 指数周线行情 | `index_weekly` | `index_weekly` 指数周线 | `core_serving.index_weekly_serving` |  |
| 172 | 指数月线行情 | `index_monthly` | `index_monthly` 指数月线 | `core_serving.index_monthly_serving` |  |

### 股票数据 / 打板专题数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 106 | 龙虎榜每日明细 | `top_list` | `top_list` 龙虎榜 | `core_serving.equity_top_list` |  |
| 259 | 同花顺概念和行业指数 | `ths_index` | `ths_index` 同花顺板块列表 | `core_serving.ths_index` |  |
| 260 | 同花顺板块指数行情 | `ths_daily` | `ths_daily` 同花顺板块日线行情 | `core_serving.ths_daily` |  |
| 261 | 同花顺概念板块成分 | `ths_member` | `ths_member` 同花顺板块成分 | `core_serving.ths_member` |  |
| 298 | 涨跌停列表（新） | `limit_list_d` | `limit_list_d` 每日涨跌停名单 | `core_serving.equity_limit_list` |  |
| 320 | 同花顺热榜 | `ths_hot` | `ths_hot` 同花顺热榜 | `core_serving.ths_hot` |  |
| 321 | 东方财富热榜 | `dc_hot` | `dc_hot` 东方财富热榜 | `core_serving.dc_hot` |  |
| 347 | 开盘啦榜单数据 | `kpl_list` | `kpl_list` 开盘啦榜单 | `core_serving.kpl_list` |  |
| 351 | 开盘啦题材成分 | `kpl_concept_cons` | `kpl_concept_cons` 开盘啦板块成分 | `core_serving.kpl_concept_cons` |  |
| 355 | 涨跌停榜单（同花顺） | `limit_list_ths` | `limit_list_ths` 同花顺涨停名单 | `core_serving.limit_list_ths` |  |
| 356 | 连板天梯 | `limit_step` | `limit_step` 连板梯队 | `core_serving.limit_step` |  |
| 357 | 最强板块统计 | `limit_cpt_list` | `limit_cpt_list` 涨停概念列表 | `core_serving.limit_cpt_list` |  |
| 362 | 东方财富概念板块 | `dc_index` | `dc_index` 东方财富板块列表 | `core_serving.dc_index` |  |
| 363 | 东方财富板块成分 | `dc_member` | `dc_member` 东方财富板块成分 | `core_serving.dc_member` |  |
| 382 | 东财概念板块行情 | `dc_daily` | `dc_daily` 东方财富板块日线行情 | `core_serving.dc_daily` |  |

### ETF专题

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 127 | ETF日线行情 | `fund_daily` | `fund_daily` 基金日线行情 | `core_serving.fund_daily_bar` |  |
| 199 | 基金复权因子 | `fund_adj` | `fund_adj` 基金复权因子 | `core.fund_adj_factor` |  |
| 385 | ETF基础信息 | `etf_basic` | `etf_basic` ETF 基础信息 | `core_serving.etf_basic` |  |
| 386 | ETF基准指数列表 | `etf_index` | `etf_index` ETF 跟踪指数 | `core_serving.etf_index` |  |

### 期货数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 137 | 交易日历 | `trade_cal` | `trade_cal` 交易日历 | `core_serving.trade_calendar` | 与 0026 共用同一个 `trade_cal` DatasetDefinition。 |

### 大模型语料专题数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 154 | 新闻联播 | `cctv_news` | `cctv_news` 新闻联播文字稿 | `core_serving_light.cctv_news` |  |
| 195 | 新闻通讯 | `major_news` | `major_news` 新闻通讯 | `core_serving_light.major_news` |  |

### 股票数据 / 特色数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 267 | 券商每月荐股 | `broker_recommend` | `broker_recommend` 券商月度金股推荐 | `core_serving.broker_recommend` |  |
| 293 | 每日筹码及胜率 | `cyq_perf` | `cyq_perf` 每日筹码及胜率 | `core_serving.equity_cyq_perf` |  |
| 328 | 股票技术面因子(专业版) | `stk_factor_pro` | `stk_factor_pro` 股票技术面因子(专业版) | `core_serving.equity_factor_pro` |  |
| 364 | 神奇九转指标 | `stk_nineturn` | `stk_nineturn` 神奇九转指标 | `core_serving.equity_nineturn` |  |

### 港股数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 191 | 港股列表 | `hk_basic` | `hk_basic` 港股基础信息 | `core_serving.hk_security` |  |

### 美股数据

| doc_id | Tushare 文档 | api_name | 内部数据集 | 目标表 | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 252 | 美股列表 | `us_basic` | `us_basic` 美股基础信息 | `core_serving.us_security` |  |

## 未接入清单

### 公募基金

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 19 | 公募基金列表 | `fund_basic` |  |
| 118 | 公募基金公司 | `fund_company` |  |
| 119 | 公募基金净值 | `fund_nav` |  |
| 120 | 公募基金分红 | `fund_div` |  |
| 121 | 公募基金持仓数据 | `fund_portfolio` |  |
| 207 | 基金规模数据 | `fund_share` |  |
| 208 | 基金经理 | `fund_manager` |  |
| 359 | 场内基金技术因子(专业版) | `fund_factor_pro` |  |

### 股票数据 / 基础数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 100 | 股票曾用名 | `namechange` |  |
| 112 | 上市公司基本信息 | `stock_company` |  |
| 123 | IPO新股列表 | `new_share` |  |
| 193 | 上市公司管理层 | `stk_managers` |  |
| 194 | 管理层薪酬和持股 | `stk_rewards` |  |
| 262 | 股票历史列表（历史每天股票列表） | `bak_basic` |  |
| 329 | 股本情况（盘前） | `stk_premarket` |  |
| 375 | 北交所新旧代码对照表 | `bse_mapping` |  |
| 398 | 沪深港通股票列表 | `stock_hsgt` |  |
| 423 | ST风险警示板股票 | `st` |  |

### 股票数据 / 行情数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 48 | 沪深股通十大成交股 | `hsgt_top10` |  |
| 49 | 港股通十大成交股 | `ggt_top10` |  |
| 109 | 通用行情接口 | `pro_bar` |  |
| 144 | 周线行情 | `weekly` |  |
| 145 | 月线行情 | `monthly` |  |
| 146 | A股复权行情 | `pro_bar` |  |
| 196 | 港股通每日成交统计 | `ggt_daily` |  |
| 197 | 港股通每月成交统计 | `ggt_monthly` |  |
| 255 | 备用行情 | `bak_daily` |  |
| 315 | 实时盘口TICK快照(爬虫版) | `realtime_quote` | 用户已确认线上文档已不存在；本地旧文档保留，当前未接入。 |
| 316 | 实时成交数据(爬虫版) | `realtime_tick` | 用户已确认线上文档已不存在；本地旧文档保留，当前未接入。 |
| 317 | 实时涨跌幅排名(爬虫版) | `realtime_list` | 用户已确认线上文档已不存在；本地旧文档保留，当前未接入。 |
| 372 | A股实时日线 | `rt_k` |  |
| 374 | A股实时分钟 | `rt_min` |  |
| 457 | A股实时分钟-日累计 | `rt_min_daily` |  |

### 股票数据 / 财务数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 33 | 利润表 | `income` |  |
| 36 | 资产负债表 | `balancesheet` |  |
| 44 | 现金流量表 | `cashflow` |  |
| 45 | 业绩预告 | `forecast` |  |
| 46 | 业绩快报 | `express` |  |
| 79 | 财务指标数据 | `fina_indicator` |  |
| 80 | 财务审计意见 | `fina_audit` |  |
| 81 | 主营业务构成 | `fina_mainbz` |  |
| 162 | 财报披露计划 | `disclosure_date` |  |

### 股票数据 / 资金流向数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 47 | 沪深港通资金流向 | `moneyflow_hsgt` |  |

### 股票数据 / 两融及转融通

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 59 | 融资融券交易明细 | `margin_detail` |  |
| 326 | 融资融券标的（盘前更新） | `margin_secs` |  |
| 331 | 转融资交易汇总 | `slb_len` |  |
| 332 | 转融券交易汇总 | `slb_sec` |  |
| 333 | 转融券交易明细 | `slb_sec_detail` |  |
| 334 | 做市借券交易汇总 | `slb_len_mm` |  |

### 股票数据 / 参考数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 61 | 前十大股东 | `top10_holders` |  |
| 62 | 前十大流通股东 | `top10_floatholders` |  |
| 110 | 股权质押统计数据 | `pledge_stat` |  |
| 111 | 股权质押明细 | `pledge_detail` |  |
| 124 | 股票回购 | `repurchase` |  |
| 160 | 限售股解禁 | `share_float` |  |
| 164 | 股票账户开户数据 | `stk_account` |  |
| 165 | 股票账户开户数据（旧） | `stk_account_old` |  |
| 175 | 股东增减持 | `stk_holdertrade` |  |
| 451 | 个股异常波动 | `stk_shock` |  |
| 452 | 个股严重异常波动 | `stk_high_shock` |  |
| 453 | 交易所重点提示证券 | `stk_alert` |  |

### 指数专题

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 181 | 申万行业分类 | `index_classify` |  |
| 211 | 国际指数 | `index_global` |  |
| 215 | 市场交易统计 | `daily_info` |  |
| 268 | 深圳市场每日交易概况 | `sz_daily_info` |  |
| 308 | 中信行业指数行情 | `ci_daily` |  |
| 327 | 申万行业日线行情 | `sw_daily` |  |
| 335 | 申万行业成分构成(分级) | `index_member_all` |  |
| 358 | 指数技术因子(专业版) | `idx_factor_pro` |  |
| 373 | 中信行业成分 | `ci_index_member` |  |
| 403 | 交易所指数实时日线 | `rt_idx_k` |  |
| 417 | 申万实时行情 | `rt_sw_k` |  |
| 419 | 股票历史分钟行情 | `idx_mins` |  |
| 420 | A股实时分钟 | `rt_idx_min` |  |

### 股票数据 / 打板专题数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 107 | 龙虎榜机构明细 | `top_inst` |  |
| 311 | 游资名录 | `hm_list` |  |
| 312 | 游资每日明细 | `hm_detail` |  |
| 369 | 当日集合竞价 | `stk_auction` |  |
| 376 | 通达信板块信息 | `tdx_index` |  |
| 377 | 通达信板块成分 | `tdx_member` |  |
| 378 | 通达信板块行情 | `tdx_daily` |  |
| 421 | 东方财富题材库 | `dc_concept` |  |
| 422 | 东方财富题材成分 | `dc_concept_cons` |  |

### ETF专题

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 387 | ETF历史分钟行情 | `stk_mins` | 与 `stk_mins` 同名，但当前内部定义只覆盖股票历史分钟行情 0370，不覆盖 ETF 历史分钟行情。 |
| 400 | ETF实时日线 | `rt_etf_k` |  |
| 408 | ETF份额规模 | `etf_share_size` |  |
| 416 | ETF实时分钟 | `rt_min` |  |
| 454 | ETF实时参考 | `rt_etf_sz_iopv` |  |

### 期货数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 135 | 期货合约信息表 | `fut_basic` |  |
| 138 | 期货日线行情 | `fut_daily` |  |
| 139 | 每日成交持仓排名 | `fut_holding` |  |
| 140 | 仓单日报 | `fut_wsr` |  |
| 141 | 结算参数 | `fut_settle` |  |
| 155 | 南华期货指数日线行情 | `index_daily` | 与 `index_daily` 同名，但当前内部定义只覆盖指数专题的 0095，不覆盖南华期货指数。 |
| 189 | 期货主力与连续合约 | `fut_mapping` |  |
| 216 | 期货主要品种交易周报 | `fut_weekly_detail` |  |
| 313 | 期货历史分钟行情 | `ft_mins` |  |
| 314 | 期货Tick行情数据 | `` |  |
| 337 | 期货周/月线行情(每日更新) | `fut_weekly_monthly` |  |
| 340 | 期货实时分钟行情 | `rt_fut_min` |  |
| 368 | 期货合约涨跌停价格（盘前） | `ft_limit` |  |

### 大模型语料专题数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 143 | 新闻快讯 | `news` |  |
| 176 | 上市公司全量公告 | `anns_d` |  |
| 366 | 上证E互动 | `irm_qa_sh` |  |
| 367 | 深证互动易 | `irm_qa_sz` |  |
| 406 | 国家政策法规库 | `npr` |  |
| 415 | 券商研究报告 | `research_report` |  |

### 债券专题

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 185 | 可转债基本信息 | `cb_basic` |  |
| 186 | 可转债发行 | `cb_issue` |  |
| 187 | 可转债行情 | `cb_daily` |  |
| 201 | 国债收益率曲线 | `yc_cb` |  |
| 233 | 财经日历 | `eco_cal` |  |
| 246 | 可转债转股价变动 | `cb_price_chg` |  |
| 247 | 可转债转股结果 | `cb_share` |  |
| 256 | 债券回购日行情 | `repo_daily` |  |
| 269 | 可转债赎回信息 | `cb_call` |  |
| 271 | 债券大宗交易 | `bond_blk` |  |
| 272 | 大宗交易明细 | `bond_blk_detail` |  |
| 305 | 可转债票面利率 | `cb_rate` |  |
| 322 | 柜台流通式债券报价 | `bc_otcqt` |  |
| 323 | 柜台流通式债券最优报价 | `bc_bestotcqt` |  |
| 392 | 可转债技术因子(专业版) | `cb_factor_pro` |  |
| 458 | 获取可转债评级历史记录 | `cb_rating` |  |
| 459 | 可转债十大持有人 | `top10_cb_holders` |  |

### 股票数据 / 特色数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 188 | 沪深港股通持股明细 | `hk_hold` |  |
| 274 | 中央结算系统持股明细 | `ccass_hold_detail` |  |
| 275 | 机构调研表 | `stk_surv` |  |
| 292 | 卖方盈利预测数据 | `report_rc` |  |
| 294 | 每日筹码分布 | `cyq_chips` |  |
| 295 | 中央结算系统持股汇总 | `ccass_hold` |  |
| 353 | 股票开盘集合竞价数据 | `stk_auction_o` |  |
| 354 | 股票收盘集合竞价数据 | `stk_auction_c` |  |
| 399 | AH股比价 | `stk_ah_comparison` |  |

### 港股数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 192 | 港股行情 | `hk_daily` |  |
| 250 | 港股交易日历 | `hk_tradecal` |  |
| 304 | 港股分钟行情 | `hk_mins` |  |
| 339 | 港股复权行情 | `hk_daily_adj` |  |
| 383 | 港股实时日线 | `rt_hk_k` |  |
| 388 | 港股财务指标数据 | `hk_fina_indicator` |  |
| 389 | 港股利润表 | `hk_income` |  |
| 390 | 港股资产负债表 | `hk_balancesheet` |  |
| 391 | 港股现金流量表 | `hk_cashflow` |  |
| 401 | 港股复权因子 | `hk_adjfactor` |  |

### 美股数据

| doc_id | Tushare 文档 | api_name | 备注 |
| ---: | --- | --- | --- |
| 253 | 美股交易日历 | `us_tradecal` |  |
| 254 | 美股行情 | `us_daily` |  |
| 338 | 美股复权行情 | `us_daily_adj` |  |
| 393 | 美股财务指标数据 | `us_fina_indicator` |  |
| 394 | 美股利润表 | `us_income` |  |
| 395 | 美股资产负债表 | `us_balancesheet` |  |
| 396 | 美股现金流量表 | `us_cashflow` |  |
| 402 | 美股复权因子 | `us_adjfactor` |  |
