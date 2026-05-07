# 财势乾坤｜P0 数据字典 v0.2

建议路径：`/docs/wealth/api/p0-data-dictionary.md`  
建议 Drive 文件夹：`数据字典与API文档`  
负责人：`04_API 契约与数据字典`  
状态：Draft v0.2

---

## 0. v0.2 变更说明

## 0.1 v0.2.1 口径修正：字段单位默认保持 Tushare / 落库口径

根据产品总控确认，v0.2.1 起执行以下字段口径规则：

1. **业务字段可以使用财势乾坤命名，但单位、数值尺度、枚举含义默认保持 Tushare 原始字段或当前落库字段口径。**
2. 不再默认把金额统一转为“元”，也不再默认把成交量统一转为“股”。
3. 只有在业务字段明确声明“已换算”时，才允许改变单位。
4. 已确认特例：`trade_cal.is_open` 在数据基座落库时已经由 Tushare 的 `0/1` 口径改为 `boolean`，因此财势乾坤字段 `isTradingDay` 直接映射该 boolean 值。
5. 前端展示层负责格式化单位，例如“千元 → 亿元”“万元 → 亿元”“手 → 万手”；API 文档必须说明字段来源单位，避免服务层隐式换算造成排障复杂。
6. 若后续需要建设面向前端展示的派生字段，应使用显式字段名，例如 `amountDisplayYuan`、`amountInYuan` 或在 `unit` 元数据中声明，不覆盖原始业务字段。

本条修正规则优先级高于 v0.2 文档中关于“统一归一化为元/股”的旧描述。

---

相对 v0.1，本版根据新的数据源使用说明做了以下升级：

1. 明确 Tushare 是**已落库数据基座与字段口径参考**，不是财势乾坤前端 API 形态。
2. API 与数据字典使用财势乾坤业务字段名，不直接暴露 Tushare 字段名。
3. 明确单位归一化：金额统一返回 `元`，成交量统一返回 `股`，涨跌幅统一为百分数数值。
4. 增加 `sourceRefs`、`dataStatus`、`normalized` 等数据来源与质量字段。
5. 增加推荐数据基座归一化视图，便于 Codex/后端从 PostgreSQL 中的 Tushare 原始表组织业务对象。
6. 继续遵守首页边界：市场总览首页只展示客观事实，不混入市场温度分、市场情绪分、资金面分数、风险指数。

## 0.1 Tushare 数据源使用原则

本项目的数据基座已按 Tushare 接口维度将数据下载并保存在 PostgreSQL。04_API 契约与数据字典的职责是：

1. 基于 P0 页面和业务对象重新组织财势乾坤的数据对象。
2. 参考 Tushare 字段定义、单位、更新时间、数据口径。
3. 对外 API 使用财势乾坤业务命名和统一单位。
4. 仅引入符合《项目总说明 v0.2》P0 范围的数据对象和接口，不扩展到港股、美股、期货、宏观等非 P0 范围。

## 0.2 Tushare 到财势乾坤字段归一化规则

| Tushare 数据集 | 原字段 | Tushare 单位/口径 | 财势乾坤字段 | API 单位/口径 | 换算 |
|---|---|---|---|---|---|
| `trade_cal` | `cal_date` | `YYYYMMDD` | `tradeDate` | `YYYY-MM-DD` | 日期格式转换 |
| `trade_cal` | `is_open` | `0/1` | `isTradingDay` | boolean | `1=true` |
| `trade_cal` | `pretrade_date` | `YYYYMMDD` | `prevTradeDate` | `YYYY-MM-DD` | 日期格式转换 |
| `stock_basic` | `ts_code` | TS 股票代码 | `stockCode` | 股票代码 | 原值 |
| `stock_basic` | `name` | 股票名称 | `stockName` | 股票名称 | 原值 |
| `stock_basic` | `industry` | 行业 | `industry` / `sectorName` | 行业/板块名 | 原值或映射 |
| `daily` | `open/high/low/close` | 元 | `open/high/low/lastPrice` | 元 | 原值 |
| `daily` | `pre_close` | 元 | `prevClose` | 元 | 原值 |
| `daily` | `pct_chg` | % | `changePct` | % | 原值 |
| `daily` | `vol` | 手 | `volume` | 股 | `vol * 100` |
| `daily` | `amount` | 千元 | `amount` | 元 | `amount * 1000` |
| `daily_basic` | `turnover_rate` | % | `turnoverRate` | % | 原值 |
| `daily_basic` | `volume_ratio` | 倍 | `volumeRatio` | 倍 | 原值 |
| `daily_basic` | `pe_ttm` | 倍 | `peTtm` | 倍 | 原值 |
| `daily_basic` | `pb` | 倍 | `pb` | 倍 | 原值 |
| `daily_basic` | `total_mv` | 万元 | `marketCap` | 元 | `total_mv * 10000` |
| `daily_basic` | `circ_mv` | 万元 | `floatMarketCap` | 元 | `circ_mv * 10000` |
| `index_daily` | `close/open/high/low` | 点 | `last/open/high/low` | 点 | 原值 |
| `index_daily` | `pct_chg` | % | `changePct` | % | 原值 |
| `index_daily` | `amount` | 千元 | `amount` | 元 | `amount * 1000` |
| `stk_limit` | `up_limit/down_limit` | 元 | `limitUpPrice/limitDownPrice` | 元 | 原值 |
| `limit_list_d` | `limit` | `U/D/Z` | `limitType` | `UP_LIMIT/DOWN_LIMIT/FAILED_LIMIT_UP` | 枚举映射 |
| `limit_list_d` | `open_times` | 次 | `openTimes` | 次 | 原值 |
| `limit_list_d` | `limit_times` | 连板数 | `streak` | 板 | 原值 |
| `moneyflow_mkt_dc` | `net_amount` | 元 | `mainNetInflow` | 元 | 原值 |
| `moneyflow_mkt_dc` | `buy_elg_amount` | 元 | `superLargeNetInflow` | 元 | 原值 |
| `moneyflow_dc` | `net_amount` | 万元 | `mainNetInflow` | 元 | `net_amount * 10000` |
| `moneyflow_ind_dc` | `net_amount` | 元 | `mainNetInflow` | 元 | 原值 |
| `sw_daily` | `pct_change` | % | `changePct` | % | 原值 |
| `sw_daily` | `vol` | 万股 | `volume` | 股 | `vol * 10000` |
| `sw_daily` | `amount` | 万元 | `amount` | 元 | `amount * 10000` |
| `sw_daily` | `total_mv` | 万元 | `marketCap` | 元 | `total_mv * 10000` |

## 0.3 v0.2 使用的 Tushare 数据集

| doc_id | api_name | 中文名称 | 本版用途 |
|---:|---|---|---|
| 25 | `stock_basic` | 股票基础信息 | 股票代码、名称、行业、地域、市场、交易所、上市状态、上市日期 |
| 26 | `trade_cal` | 交易日历 | 交易日、是否开市、上一交易日 |
| 27 | `daily` | A 股日线行情 | 个股 OHLC、昨收、涨跌额、涨跌幅、成交量、成交额 |
| 32 | `daily_basic` | 每日指标 | 换手率、量比、PE/PB、股本、市值 |
| 95 | `index_daily` | 指数日线行情 | 核心指数 OHLC、昨收、涨跌点、涨跌幅、成交量、成交额 |
| 183 | `stk_limit` | 每日涨跌停价格 | 个股涨停价、跌停价 |
| 298 | `limit_list_d` | 涨跌停和炸板数据 | 涨停、跌停、炸板、封单金额、首次封板、炸板次数、连板数 |
| 327 | `sw_daily` | 申万行业日线行情 | 行业指数涨跌幅、成交额、市值、PE/PB |
| 344 | `moneyflow_ind_dc` | 板块资金流向 | 行业/概念/地域板块资金流 |
| 345 | `moneyflow_mkt_dc` | 大盘资金流向 | 全市场主力、超大单、大单、中单、小单资金流 |
| 349 | `moneyflow_dc` | 个股资金流向 | 个股主力、超大单、大单、中单、小单资金流 |
| 370 | `stk_mins` | 股票历史分钟行情 | 个股分钟 K 线，P0 个股详情后续使用 |

## 0.4 推荐数据基座归一化视图

| 视图 | 用途 | 主要来源 |
|---|---|---|
| `wealth_trade_day_view` | 交易日统一视图 | `trade_cal` |
| `wealth_stock_universe_view` | A 股有效样本池 | `stock_basic`、`daily` |
| `wealth_quote_snapshot_daily_view` | 个股行情快照 | `daily`、`daily_basic`、`stock_basic`、`stk_limit` |
| `wealth_index_snapshot_view` | 指数行情快照 | `index_daily` |
| `wealth_market_breadth_snapshot` | 涨跌家数、红盘率、中位涨跌幅 | `daily`、`stock_basic`、`limit_list_d` |
| `wealth_turnover_summary_snapshot` | 全市场成交额和 20 日中位量能 | `daily`、`stock_basic` |
| `wealth_limitup_snapshot` | 涨跌停、炸板、连板预聚合 | `limit_list_d`、`stk_limit` |
| `wealth_sector_rank_snapshot` | 行业/板块榜 | `sw_daily`、`moneyflow_ind_dc` |
| `wealth_stock_rank_snapshot` | 个股榜 | `daily`、`daily_basic`、`stock_basic`、`limit_list_d` |
| `wealth_moneyflow_market_snapshot` | 大盘资金流 | `moneyflow_mkt_dc` |
| `wealth_data_source_status` | 数据集同步状态与质量校验 | 同步任务 |

---


## 0. 设计边界

### 0.1 产品边界

1. 首页定位为“市场客观事实驾驶舱”。
2. 首页 API 不返回 `MarketTemperature.score`、`MarketSentiment.score`、`RiskIndex.riskScore` 作为核心结论。
3. 市场温度、市场情绪、资金面分数、风险指数属于“市场温度与情绪分析页”的 P0 指标体系，可单独定义对象，但不混入首页核心结论。
4. 持仓功能不接真实券商账户，只依赖用户手工登记。
5. 所有行情类对象必须支持中国股票市场“红涨绿跌”：上涨为红色，下跌为绿色，平盘为灰色。

### 0.2 命名规范

| 项目 | 规范 |
|---|---|
| JSON 字段命名 | `lowerCamelCase` |
| 日期 | `YYYY-MM-DD`，如 `2026-04-28` |
| 时间 | ISO 8601，带时区，如 `2026-04-28T14:56:00+08:00` |
| 金额 | 默认单位为人民币元 |
| 涨跌幅 | `changePct` 使用百分数数值，例如 1.23% 返回 `1.23` |
| 比例 / 占比 | `rate` 使用 0 到 1 的小数，例如 62.8% 返回 `0.628` |
| 方向 | `direction` 统一取值：`UP` / `DOWN` / `FLAT` / `UNKNOWN` |
| 颜色语义 | `UP=red`，`DOWN=green`，`FLAT=gray` |
| 市场 | P0 默认 `CN_A` |
| 数据状态 | `READY` / `PARTIAL` / `DELAYED` / `UNAVAILABLE` |

### 0.3 通用字段建议

行情、榜单、统计对象建议尽量包含：


| 字段 | 类型 | 说明 |
| --- | --- | --- |
| tradeDate | string(date) | 交易日 |
| market | string(enum) | 市场，P0 默认 CN_A |
| asOf | string(datetime) | 数据截至时间 |
| dataStatus | string(enum) | READY / PARTIAL / DELAYED / UNAVAILABLE |
| source | string | 主数据来源 |
| calcVersion | string | 派生计算版本，便于回溯 |

---

## 1. 对象定义


### 1. TradingDay


**对象定义**：A 股交易日与当前交易阶段信息，用于首页顶部状态、接口默认交易日、缓存 key 和数据新鲜度判断。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 行情数据基座 / 交易日历服务 |
| 使用页面 | 首页、指数页、个股页、情绪分析页、持仓页 |
| 数据来源 | 交易所日历 / Tushare trade_cal / 内部交易日历表 |
| 更新频率 | 每日预生成；盘中按交易阶段刷新 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 当前交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| market | string(enum) | 市场，P0 默认 CN_A | - | 是 | CN_A | 系统配置 | 固定 | 是 |
| isTradingDay | boolean | 是否交易日 | - | 是 | true | 交易日历 | 日 | 是 |
| sessionStatus | string(enum) | PRE_OPEN / OPEN / NOON_BREAK / CLOSED / HOLIDAY | - | 是 | OPEN | 交易日历 + 当前时间 | 分钟 | 是 |
| timezone | string | 时区 | - | 是 | Asia/Shanghai | 系统配置 | 固定 | 是 |
| openTime | string(datetime) | 当日开盘时间 | - | 否 | 2026-04-28T09:30:00+08:00 | 交易日历 | 日 | 是 |
| closeTime | string(datetime) | 当日收盘时间 | - | 否 | 2026-04-28T15:00:00+08:00 | 交易日历 | 日 | 是 |
| prevTradeDate | string(date) | 上一交易日 | - | 是 | 2026-04-27 | 交易日历 | 日 | 是 |
| nextTradeDate | string(date) | 下一交易日 | - | 否 | 2026-04-29 | 交易日历 | 日 | 否 |
| isDelayed | boolean | 是否延迟行情 | - | 是 | true | 数据源状态 | 分钟 | 是 |
| dataStatus | string(enum) | 当日行情数据状态 | - | 是 | READY | 数据源状态 | 分钟 | 是 |



### 2. MarketOverview


**对象定义**：市场总览首页顶层聚合对象，只承载客观市场事实与模块入口数据，不承载市场温度、市场情绪、风险指数等主观评分结论。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 首页聚合服务 / 行情查询服务 |
| 使用页面 | 市场总览首页 |
| 数据来源 | 指数行情、股票行情、交易统计、涨跌停统计、板块榜单、个股榜单 |
| 更新频率 | 盘中 15-60 秒；盘后固定 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradingDay | TradingDay | 交易日信息 | - | 是 | {...} | 交易日历 | 分钟 | 是 |
| market | string(enum) | 市场 | - | 是 | CN_A | 系统配置 | 固定 | 是 |
| asOf | string(datetime) | 首页聚合数据截至时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 聚合服务 | 15-60 秒 | 是 |
| indices | IndexSnapshot[] | 核心指数快照 | - | 是 | [{indexCode:"000001.SH"}] | 指数行情 | 15-60 秒 | 是 |
| breadth | MarketBreadth | 涨跌家数与市场广度 | - | 是 | {upCount:3421} | 股票行情派生 | 15-60 秒 | 是 |
| style | MarketStyle | 市场风格表现 | - | 是 | {styleLeader:"SMALL_CAP"} | 指数行情派生 | 1-5 分钟 | 是 |
| turnover | TurnoverSummary | 成交额概览 | 元 | 是 | {totalAmount:1052300000000} | 股票行情聚合 | 15-60 秒 | 是 |
| moneyFlow | MoneyFlowSummary | 资金流事实摘要；可降级为空 | 元 | 否 | {mainNetInflow:-8120000000} | 资金流服务 | 1-5 分钟 | 否 |
| limitUp | LimitUpSummary | 涨跌停事实摘要 | - | 是 | {limitUpCount:59} | 股票行情派生 | 15-60 秒 | 是 |
| streakLadder | LimitUpStreakLadder[] | 连板天梯摘要 | - | 否 | [{streak:6,count:1}] | 涨停统计 | 1-5 分钟 | 是 |
| topSectors | SectorRankItem[] | 板块榜 | - | 是 | [{sectorName:"储能"}] | 板块计算 | 1-5 分钟 | 是 |
| stockLeaderboards | object | 个股榜单分组 | - | 是 | {topGainers:[...]} | 行情榜单 | 15-60 秒 | 是 |
| quickEntries | object[] | 首页快捷入口配置 | - | 是 | [{key:"emotion"}] | 配置中心 | 低频 | 是 |
| dataSources | DataSourceStatus[] | 数据源状态摘要 | - | 是 | [{sourceName:"Tushare"}] | 数据源监控 | 1 分钟 | 是 |



### 3. IndexSnapshot


**对象定义**：指数行情快照对象，用于首页核心指数卡片、指数列表、风格对比和 K 线入口。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 指数行情服务 |
| 使用页面 | 首页、指数详情、市场风格、情绪分析页 |
| 数据来源 | 指数行情源 / Tushare index_daily 或实时源 |
| 更新频率 | P0 可日频或分钟级；实时源接入后 3-15 秒 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| indexCode | string | 指数代码 | - | 是 | 000001.SH | 指数基础表 | 固定 | 是 |
| indexName | string | 指数名称 | - | 是 | 上证指数 | 指数基础表 | 低频 | 是 |
| market | string(enum) | 市场 | - | 是 | CN_A | 系统配置 | 固定 | 是 |
| last | number | 最新点位 / 收盘点位 | 点 | 是 | 3128.42 | 指数行情 | 15-60 秒/日 | 是 |
| prevClose | number | 昨收点位 | 点 | 是 | 3099.76 | 指数行情 | 日 | 是 |
| open | number | 开盘点位 | 点 | 否 | 3108.91 | 指数行情 | 日内 | 是 |
| high | number | 最高点位 | 点 | 否 | 3138.66 | 指数行情 | 日内 | 是 |
| low | number | 最低点位 | 点 | 否 | 3098.12 | 指数行情 | 日内 | 是 |
| change | number | 涨跌点数 | 点 | 是 | 28.66 | 派生 | 15-60 秒 | 是 |
| changePct | number | 涨跌幅，百分数数值 | % | 是 | 0.92 | 派生 | 15-60 秒 | 是 |
| amplitudePct | number | 振幅 | % | 否 | 1.31 | 派生 | 15-60 秒 | 否 |
| amount | number | 成交额 | 元 | 否 | 482300000000 | 指数行情 | 15-60 秒 | 是 |
| direction | string(enum) | UP / DOWN / FLAT / UNKNOWN；前端 UP=红、DOWN=绿 | - | 是 | UP | 派生 | 15-60 秒 | 是 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 行情源 | 15-60 秒 | 是 |



### 4. MarketBreadth


**对象定义**：A 股样本池内涨跌分布、红盘率、中位涨跌幅等市场广度事实，用于首页判断多数股票体感。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 市场统计服务 |
| 使用页面 | 首页、市场温度与情绪分析页 |
| 数据来源 | 股票行情快照 / 股票日线 / 交易参考表 |
| 更新频率 | 盘中 15-60 秒；盘后固定 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| samplePool | string(enum) | 样本池名称；建议 CN_A_COMMON | - | 是 | CN_A_COMMON | 样本池规则 | 日 | 是 |
| stockUniverseCount | integer | 样本池股票数 | 只 | 是 | 5128 | 股票基础表 | 日 | 是 |
| upCount | integer | 上涨家数 | 只 | 是 | 3421 | 行情派生 | 15-60 秒 | 是 |
| downCount | integer | 下跌家数 | 只 | 是 | 1488 | 行情派生 | 15-60 秒 | 是 |
| flatCount | integer | 平盘家数 | 只 | 是 | 219 | 行情派生 | 15-60 秒 | 是 |
| redRate | number | 红盘率 = upCount / stockUniverseCount | ratio | 是 | 0.667 | 派生 | 15-60 秒 | 是 |
| medianChangePct | number | 样本池中位涨跌幅 | % | 是 | 0.48 | 派生 | 15-60 秒 | 是 |
| upGt3Pct | number | 涨超 3% 占比 | ratio | 否 | 0.142 | 派生 | 15-60 秒 | 是 |
| downGt3Pct | number | 跌超 3% 占比 | ratio | 否 | 0.041 | 派生 | 15-60 秒 | 是 |
| limitUpCount | integer | 涨停家数 | 只 | 是 | 59 | 涨跌停派生 | 15-60 秒 | 是 |
| limitDownCount | integer | 跌停家数 | 只 | 是 | 8 | 涨跌停派生 | 15-60 秒 | 是 |
| advancersDeclinersRatio | number | 上涨 / 下跌家数比 | 倍 | 否 | 2.30 | 派生 | 15-60 秒 | 否 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 聚合服务 | 15-60 秒 | 是 |



### 5. MarketStyle


**对象定义**：大盘 / 小盘、成长 / 价值、主要指数之间的风格强弱事实，用于首页展示今日市场偏稳还是偏进攻。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 市场风格计算服务 |
| 使用页面 | 首页、市场温度与情绪分析页、板块轮动页 |
| 数据来源 | 核心指数行情，如沪深300、中证1000、国证2000、上证50、创业板指、科创50 |
| 更新频率 | 1-5 分钟；P0 可日频 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| largeCapIndexCode | string | 大盘代表指数 | - | 是 | 000300.SH | 系统配置 | 低频 | 是 |
| smallCapIndexCode | string | 小盘代表指数 | - | 是 | 399303.SZ | 系统配置 | 低频 | 是 |
| largeCapChangePct | number | 大盘代表指数涨跌幅 | % | 是 | 0.72 | 指数行情 | 1-5 分钟 | 是 |
| smallCapChangePct | number | 小盘代表指数涨跌幅 | % | 是 | 1.48 | 指数行情 | 1-5 分钟 | 是 |
| smallVsLargeSpreadPct | number | 小盘相对大盘强弱差 | pct point | 是 | 0.76 | 派生 | 1-5 分钟 | 是 |
| growthIndexCode | string | 成长代表指数 | - | 否 | 399006.SZ | 系统配置 | 低频 | 否 |
| valueIndexCode | string | 价值代表指数 | - | 否 | 000016.SH | 系统配置 | 低频 | 否 |
| growthChangePct | number | 成长风格涨跌幅 | % | 否 | 1.21 | 指数行情 | 1-5 分钟 | 否 |
| valueChangePct | number | 价值风格涨跌幅 | % | 否 | 0.35 | 指数行情 | 1-5 分钟 | 否 |
| styleLeader | string(enum) | LARGE_CAP / SMALL_CAP / GROWTH / VALUE / BALANCED | - | 是 | SMALL_CAP | 派生 | 1-5 分钟 | 是 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 聚合服务 | 1-5 分钟 | 是 |



### 6. TurnoverSummary


**对象定义**：全市场成交额与相对量能摘要，用于首页成交额模块。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 成交统计服务 |
| 使用页面 | 首页、市场温度与情绪分析页 |
| 数据来源 | 股票行情快照 / 股票日线 amount 聚合 |
| 更新频率 | 15-60 秒；盘后固定 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| totalAmount | number | A 股全市场成交额 | 元 | 是 | 1052300000000 | 股票行情聚合 | 15-60 秒 | 是 |
| prevTotalAmount | number | 上一交易日成交额 | 元 | 否 | 982100000000 | 股票日线聚合 | 日 | 是 |
| amountChange | number | 较上一交易日变化额 | 元 | 否 | 70200000000 | 派生 | 15-60 秒 | 是 |
| amountChangePct | number | 较上一交易日变化幅度 | % | 否 | 7.15 | 派生 | 15-60 秒 | 是 |
| amount20dMedian | number | 近 20 日成交额中位数 | 元 | 否 | 936000000000 | 历史聚合 | 日 | 是 |
| amountRatio20dMedian | number | 今日成交额 / 20 日中位成交额 | 倍 | 否 | 1.12 | 派生 | 15-60 秒 | 是 |
| sseAmount | number | 沪市成交额 | 元 | 否 | 438200000000 | 股票行情聚合 | 15-60 秒 | 是 |
| szseAmount | number | 深市成交额 | 元 | 否 | 598400000000 | 股票行情聚合 | 15-60 秒 | 是 |
| bseAmount | number | 北交所成交额 | 元 | 否 | 15600000000 | 股票行情聚合 | 15-60 秒 | 否 |
| amountByBoard | object[] | 分市场层级成交额 | 元 | 否 | [{board:"STAR",amount:81200000000}] | 股票基础表 + 行情聚合 | 1-5 分钟 | 否 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 聚合服务 | 15-60 秒 | 是 |



### 7. MoneyFlowSummary


**对象定义**：资金流事实摘要。P0 首页可作为客观事实模块展示，但不输出资金面分数；若缺少分档资金源，允许 dataStatus=UNAVAILABLE 并降级。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 资金流服务 |
| 使用页面 | 首页、资金面分析页、市场温度与情绪分析页 |
| 数据来源 | 行情源资金流接口 / 大单分档统计 / 第三方数据 |
| 更新频率 | 1-5 分钟；取决于数据源 |
| 是否 P0 必需 | 首页非强必需；资金面页必需 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| netInflow | number | 全市场净流入 | 元 | 否 | -5280000000 | 资金流数据源 | 1-5 分钟 | 否 |
| mainNetInflow | number | 主力净流入 | 元 | 否 | -8120000000 | 资金流数据源 | 1-5 分钟 | 否 |
| superLargeNetInflow | number | 超大单净流入 | 元 | 否 | -3200000000 | 资金流数据源 | 1-5 分钟 | 否 |
| largeNetInflow | number | 大单净流入 | 元 | 否 | -4920000000 | 资金流数据源 | 1-5 分钟 | 否 |
| mediumNetInflow | number | 中单净流入 | 元 | 否 | 2100000000 | 资金流数据源 | 1-5 分钟 | 否 |
| smallNetInflow | number | 小单净流入 | 元 | 否 | 6020000000 | 资金流数据源 | 1-5 分钟 | 否 |
| northboundNetInflow | number|null | 北向资金净流入；P0 可为空 | 元 | 否 | null | 互联互通数据源 | 1-5 分钟 | 否 |
| topInflowSectors | SectorRankItem[] | 净流入靠前板块 | - | 否 | [...] | 板块资金流 | 1-5 分钟 | 否 |
| topOutflowSectors | SectorRankItem[] | 净流出靠前板块 | - | 否 | [...] | 板块资金流 | 1-5 分钟 | 否 |
| dataStatus | string(enum) | 数据状态 | - | 是 | PARTIAL | 数据源状态 | 1 分钟 | 是 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 资金流服务 | 1-5 分钟 | 是 |



### 8. LimitUpSummary


**对象定义**：涨跌停摘要对象，用于首页涨跌停模块和情绪分析页。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 涨跌停统计服务 |
| 使用页面 | 首页、情绪分析页、个股榜单 |
| 数据来源 | 股票行情快照 + 当日涨停价 / 跌停价 / 涨跌幅限制 |
| 更新频率 | 15-60 秒；盘后固定 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| limitUpCount | integer | 当前 / 收盘涨停数 | 只 | 是 | 59 | 行情派生 | 15-60 秒 | 是 |
| limitDownCount | integer | 当前 / 收盘跌停数 | 只 | 是 | 8 | 行情派生 | 15-60 秒 | 是 |
| touchedLimitUpCount | integer | 盘中触及涨停数 | 只 | 否 | 86 | high 与涨停价派生 | 15-60 秒 | 是 |
| failedLimitUpCount | integer | 炸板数：触板但未封住 | 只 | 否 | 27 | 派生 | 15-60 秒 | 是 |
| sealRate | number | 封板率 = 涨停数 / 触板数 | ratio | 否 | 0.686 | 派生 | 15-60 秒 | 是 |
| oneWordLimitUpCount | integer | 一字涨停数 | 只 | 否 | 7 | 行情派生 | 15-60 秒 | 否 |
| tradableLimitUpCount | integer | 可交易涨停数，剔除一字 | 只 | 否 | 52 | 派生 | 15-60 秒 | 否 |
| highestStreak | integer | 最高连板高度 | 板 | 否 | 6 | 连板计算 | 1-5 分钟 | 是 |
| firstBoardCount | integer | 首板数 | 只 | 否 | 42 | 连板计算 | 1-5 分钟 | 是 |
| secondBoardCount | integer | 二板数 | 只 | 否 | 8 | 连板计算 | 1-5 分钟 | 是 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 涨跌停统计服务 | 15-60 秒 | 是 |



### 9. LimitUpDistribution


**对象定义**：涨停 / 跌停 / 触板 / 炸板在市场层级、涨跌幅制度、行业主题或连板高度上的分布桶，用于图表展示。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 涨跌停统计服务 |
| 使用页面 | 首页、情绪分析页 |
| 数据来源 | 股票行情快照、涨跌停规则、股票基础表、板块映射 |
| 更新频率 | 1-5 分钟 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| distributionType | string(enum) | BOARD / LIMIT_PCT / SECTOR / STREAK | - | 是 | STREAK | 请求参数 / 计算服务 | 低频 | 是 |
| bucketKey | string | 分布桶 key | - | 是 | 3 | 计算服务 | 1-5 分钟 | 是 |
| bucketName | string | 分布桶名称 | - | 是 | 3连板 | 计算服务 | 1-5 分钟 | 是 |
| limitUpCount | integer | 桶内涨停数 | 只 | 是 | 5 | 行情派生 | 1-5 分钟 | 是 |
| limitDownCount | integer | 桶内跌停数 | 只 | 否 | 0 | 行情派生 | 1-5 分钟 | 否 |
| touchedLimitUpCount | integer | 桶内触板数 | 只 | 否 | 8 | 行情派生 | 1-5 分钟 | 否 |
| failedLimitUpCount | integer | 桶内炸板数 | 只 | 否 | 3 | 派生 | 1-5 分钟 | 否 |
| rate | number | 桶内占比 | ratio | 否 | 0.085 | 派生 | 1-5 分钟 | 否 |
| amount | number | 桶内成交额 | 元 | 否 | 24300000000 | 聚合 | 1-5 分钟 | 否 |
| topStocks | object[] | 桶内代表股票 | - | 否 | [{stockCode:"002xxx"}] | 涨停统计服务 | 1-5 分钟 | 否 |



### 10. LimitUpStreakLadder


**对象定义**：连板天梯对象，按连板高度展示股票分布。首页只展示摘要，情绪分析页展示完整天梯。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 涨跌停统计服务 |
| 使用页面 | 首页、情绪分析页 |
| 数据来源 | 历史涨停记录、当日涨停记录、股票行情 |
| 更新频率 | 1-5 分钟；盘后固定 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| streak | integer | 连板高度 | 板 | 是 | 3 | 连板计算 | 1-5 分钟 | 是 |
| count | integer | 该高度股票数量 | 只 | 是 | 5 | 连板计算 | 1-5 分钟 | 是 |
| stocks | object[] | 该高度股票列表 | - | 是 | [{stockCode:"002123"}] | 连板计算 | 1-5 分钟 | 是 |
| highestStreak | integer | 当日最高连板高度 | 板 | 否 | 6 | 连板计算 | 1-5 分钟 | 是 |
| breakCount | integer | 断板数量 | 只 | 否 | 14 | 需昨日连板池 | 1-5 分钟 | 否 |
| promotionRate | number | 晋级率 | ratio | 否 | 0.42 | 派生 | 1-5 分钟 | 否 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 统计服务 | 1-5 分钟 | 是 |



### 11. SectorRankItem


**对象定义**：板块榜单项，可用于涨幅榜、跌幅榜、成交额榜、资金净流入榜和热力图。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 板块计算服务 |
| 使用页面 | 首页、板块轮动页、市场温度与情绪分析页 |
| 数据来源 | 板块成分映射 + 股票行情聚合 |
| 更新频率 | 1-5 分钟；P0 可日频 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rank | integer | 排名 | - | 是 | 1 | 计算服务 | 1-5 分钟 | 是 |
| sectorId | string | 板块 ID | - | 是 | BK0421 | 板块基础表 | 低频 | 是 |
| sectorName | string | 板块名称 | - | 是 | 储能 | 板块基础表 | 低频 | 是 |
| sectorType | string(enum) | INDUSTRY / CONCEPT / REGION / STYLE / BOARD | - | 是 | CONCEPT | 板块基础表 | 低频 | 是 |
| changePct | number | 板块涨跌幅 | % | 是 | 3.86 | 成分股派生 | 1-5 分钟 | 是 |
| direction | string(enum) | 涨跌方向，UP=红，DOWN=绿 | - | 是 | UP | 派生 | 1-5 分钟 | 是 |
| redRate | number | 板块内红盘率 | ratio | 否 | 0.82 | 成分股派生 | 1-5 分钟 | 是 |
| riseCount | integer | 板块内上涨家数 | 只 | 否 | 63 | 成分股派生 | 1-5 分钟 | 是 |
| fallCount | integer | 板块内下跌家数 | 只 | 否 | 12 | 成分股派生 | 1-5 分钟 | 是 |
| amount | number | 板块成交额 | 元 | 否 | 128600000000 | 成分股聚合 | 1-5 分钟 | 是 |
| amountRatio20dMedian | number | 板块成交额相对 20 日中位 | 倍 | 否 | 1.45 | 历史聚合 | 1-5 分钟 | 否 |
| mainNetInflow | number | 主力净流入 | 元 | 否 | 2630000000 | 资金流服务 | 1-5 分钟 | 否 |
| leadingStockCode | string | 领涨股票代码 | - | 否 | 300750.SZ | 成分股排序 | 1-5 分钟 | 是 |
| leadingStockName | string | 领涨股票名称 | - | 否 | 宁德时代 | 股票基础表 | 低频 | 是 |
| leadingStockChangePct | number | 领涨股票涨跌幅 | % | 否 | 5.82 | 股票行情 | 1-5 分钟 | 是 |



### 12. StockRankItem


**对象定义**：个股榜单项。用于首页涨幅榜、跌幅榜、成交额榜、换手榜、涨速榜等。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 个股榜单服务 |
| 使用页面 | 首页、个股列表页、机会发现页 |
| 数据来源 | 股票行情快照 / 股票日线 / 股票基础表 |
| 更新频率 | 15-60 秒；榜单可 1 分钟刷新 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rank | integer | 排名 | - | 是 | 1 | 排序服务 | 15-60 秒 | 是 |
| rankType | string(enum) | GAINER / LOSER / AMOUNT / TURNOVER / VOLUME_RATIO / LIMIT_UP | - | 是 | GAINER | 请求参数 | 固定 | 是 |
| stockCode | string | 股票代码 | - | 是 | 300123.SZ | 股票基础表 | 固定 | 是 |
| stockName | string | 股票名称 | - | 是 | 某科技 | 股票基础表 | 低频 | 是 |
| price | number | 最新价 / 收盘价 | 元 | 是 | 18.36 | 行情源 | 15-60 秒 | 是 |
| changePct | number | 涨跌幅 | % | 是 | 20.01 | 派生 | 15-60 秒 | 是 |
| direction | string(enum) | UP=红，DOWN=绿，FLAT=灰 | - | 是 | UP | 派生 | 15-60 秒 | 是 |
| amount | number | 成交额 | 元 | 否 | 3280000000 | 行情源 | 15-60 秒 | 是 |
| volume | number | 成交量 | 股 | 否 | 182000000 | 行情源 | 15-60 秒 | 是 |
| turnoverRate | number | 换手率 | % | 否 | 18.4 | 行情源 / 派生 | 15-60 秒 | 否 |
| volumeRatio | number | 量比 | 倍 | 否 | 2.8 | 行情源 / 派生 | 15-60 秒 | 否 |
| marketCap | number | 总市值 | 元 | 否 | 38200000000 | 基础表 + 行情 | 分钟 / 日 | 否 |
| sectorName | string | 所属主行业 / 主题 | - | 否 | 半导体 | 板块映射 | 日 | 是 |
| isLimitUp | boolean | 是否涨停 | - | 否 | true | 涨停规则 | 15-60 秒 | 是 |
| isLimitDown | boolean | 是否跌停 | - | 否 | false | 涨停规则 | 15-60 秒 | 是 |



### 13. HeatMapItem


**对象定义**：热力图节点对象。可表示行业、概念或板块层级，颜色映射涨跌幅，面积映射成交额 / 市值 / 成分数量。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 板块热力图服务 |
| 使用页面 | 首页、板块轮动页 |
| 数据来源 | 板块映射、股票行情聚合 |
| 更新频率 | 1-5 分钟 |
| 是否 P0 必需 | 首页可选；板块页必需 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | string | 节点 ID | - | 是 | SW801730 | 板块基础表 | 低频 | 是 |
| parentId | string | 父节点 ID | - | 否 | SW801000 | 板块基础表 | 低频 | 否 |
| name | string | 节点名称 | - | 是 | 电力设备 | 板块基础表 | 低频 | 是 |
| type | string(enum) | INDUSTRY / CONCEPT / STYLE / BOARD | - | 是 | INDUSTRY | 板块基础表 | 低频 | 是 |
| changePct | number | 涨跌幅 | % | 是 | 2.61 | 聚合派生 | 1-5 分钟 | 是 |
| direction | string(enum) | 涨跌方向 | - | 是 | UP | 派生 | 1-5 分钟 | 是 |
| amount | number | 成交额，默认面积指标 | 元 | 否 | 95800000000 | 聚合 | 1-5 分钟 | 是 |
| marketCap | number | 市值，可作为面积指标 | 元 | 否 | 2840000000000 | 股票基础 + 行情 | 日 / 分钟 | 否 |
| stockCount | integer | 成分股数量 | 只 | 否 | 226 | 板块映射 | 日 | 是 |
| redRate | number | 红盘率 | ratio | 否 | 0.74 | 派生 | 1-5 分钟 | 否 |
| sizeMetric | string(enum) | 面积指标 | - | 是 | AMOUNT | 请求参数 | 固定 | 是 |
| colorMetric | string(enum) | 颜色指标 | - | 是 | CHANGE_PCT | 请求参数 | 固定 | 是 |



### 14. QuoteSnapshot


**对象定义**：个股行情快照对象，用于搜索结果、个股详情页头部、自选 / 持仓卡片。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 个股行情服务 |
| 使用页面 | 个股详情页、自选、持仓、首页榜单 |
| 数据来源 | 股票行情源 / 股票日线 |
| 更新频率 | 15-60 秒；P0 可日频 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| stockCode | string | 股票代码 | - | 是 | 300750.SZ | 股票基础表 | 固定 | 是 |
| stockName | string | 股票名称 | - | 是 | 宁德时代 | 股票基础表 | 低频 | 是 |
| exchange | string(enum) | SSE / SZSE / BSE | - | 是 | SZSE | 股票基础表 | 固定 | 是 |
| lastPrice | number | 最新价 / 收盘价 | 元 | 是 | 188.42 | 行情源 | 15-60 秒 | 是 |
| prevClose | number | 昨收价 | 元 | 是 | 183.60 | 行情源 | 日 | 是 |
| open | number | 开盘价 | 元 | 否 | 184.30 | 行情源 | 日内 | 是 |
| high | number | 最高价 | 元 | 否 | 190.88 | 行情源 | 日内 | 是 |
| low | number | 最低价 | 元 | 否 | 183.80 | 行情源 | 日内 | 是 |
| change | number | 涨跌额 | 元 | 是 | 4.82 | 派生 | 15-60 秒 | 是 |
| changePct | number | 涨跌幅 | % | 是 | 2.63 | 派生 | 15-60 秒 | 是 |
| direction | string(enum) | UP=红，DOWN=绿，FLAT=灰 | - | 是 | UP | 派生 | 15-60 秒 | 是 |
| volume | number | 成交量 | 股 | 否 | 46820000 | 行情源 | 15-60 秒 | 是 |
| amount | number | 成交额 | 元 | 否 | 8812000000 | 行情源 | 15-60 秒 | 是 |
| turnoverRate | number | 换手率 | % | 否 | 1.12 | 行情源 / 派生 | 15-60 秒 | 否 |
| amplitudePct | number | 振幅 | % | 否 | 3.86 | 派生 | 15-60 秒 | 否 |
| peTtm | number | 市盈率 TTM | 倍 | 否 | 21.4 | 财务 / 行情源 | 日 | 否 |
| pb | number | 市净率 | 倍 | 否 | 4.8 | 财务 / 行情源 | 日 | 否 |
| limitUpPrice | number | 当日涨停价 | 元 | 否 | 220.32 | 交易参考表 | 日 | 是 |
| limitDownPrice | number | 当日跌停价 | 元 | 否 | 146.88 | 交易参考表 | 日 | 是 |
| isSuspended | boolean | 是否停牌 | - | 是 | false | 交易参考表 | 日 | 是 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 行情源 | 15-60 秒 | 是 |



### 15. KlineCandle


**对象定义**：K 线蜡烛图基础对象，支持日 K、周 K、月 K、分钟 K 的统一表达。P0 首页不直接使用。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | K 线服务 |
| 使用页面 | 个股详情页、指数详情页 |
| 数据来源 | 股票日线 / 指数日线 / 分钟行情 |
| 更新频率 | 日 K 日更；分钟 K 分钟级；P0 可先日 K |
| 是否 P0 必需 | 个股页必需；首页非必需 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| symbol | string | 股票或指数代码 | - | 是 | 300750.SZ | 请求参数 | 固定 | 是 |
| symbolType | string(enum) | STOCK / INDEX / SECTOR | - | 是 | STOCK | 请求参数 | 固定 | 是 |
| period | string(enum) | 1m / 5m / 15m / 30m / 60m / D / W / M | - | 是 | D | 请求参数 | 固定 | 是 |
| tradeDate | string(date) | 交易日期 | - | 是 | 2026-04-28 | 行情源 | 日 / 分钟 | 是 |
| tradeTime | string(datetime) | K 线时间点，日 K 可为空 | - | 否 | 2026-04-28T14:55:00+08:00 | 分钟行情 | 分钟 | 否 |
| open | number | 开盘价 | 元 / 点 | 是 | 184.30 | 行情源 | 依 period | 是 |
| high | number | 最高价 | 元 / 点 | 是 | 190.88 | 行情源 | 依 period | 是 |
| low | number | 最低价 | 元 / 点 | 是 | 183.80 | 行情源 | 依 period | 是 |
| close | number | 收盘价 | 元 / 点 | 是 | 188.42 | 行情源 | 依 period | 是 |
| prevClose | number | 前收盘价 | 元 / 点 | 否 | 183.60 | 行情源 | 日 | 是 |
| volume | number | 成交量 | 股 | 否 | 46820000 | 行情源 | 依 period | 是 |
| amount | number | 成交额 | 元 | 否 | 8812000000 | 行情源 | 依 period | 是 |
| changePct | number | 本周期涨跌幅 | % | 否 | 2.63 | 派生 | 依 period | 是 |
| turnoverRate | number | 换手率 | % | 否 | 1.12 | 行情源 / 派生 | 依 period | 否 |
| adjustType | string(enum) | NONE / QFQ / HFQ | - | 否 | QFQ | 请求参数 | 固定 | 否 |



### 16. TechnicalIndicators


**对象定义**：技术指标对象。用于 K 线页主图均线、MACD、成交量均线、KDJ 等。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 技术指标计算服务 |
| 使用页面 | 个股详情页、指数详情页、机会验证页 |
| 数据来源 | KlineCandle 序列派生 |
| 更新频率 | 与 K 线 period 一致 |
| 是否 P0 必需 | 个股页 P0 必需；首页非必需 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| symbol | string | 标的代码 | - | 是 | 300750.SZ | 请求参数 | 固定 | 是 |
| period | string(enum) | 周期 | - | 是 | D | 请求参数 | 固定 | 是 |
| tradeDate | string(date) | 交易日期 | - | 是 | 2026-04-28 | K 线数据 | 依 period | 是 |
| ma5 | number | 5 周期均线 | 元 / 点 | 否 | 181.24 | 派生 | 依 period | 是 |
| ma10 | number | 10 周期均线 | 元 / 点 | 否 | 178.90 | 派生 | 依 period | 是 |
| ma20 | number | 20 周期均线 | 元 / 点 | 否 | 174.22 | 派生 | 依 period | 是 |
| ma60 | number | 60 周期均线 | 元 / 点 | 否 | 166.18 | 派生 | 依 period | 否 |
| volumeMa5 | number | 5 周期成交量均线 | 股 | 否 | 35800000 | 派生 | 依 period | 是 |
| volumeMa10 | number | 10 周期成交量均线 | 股 | 否 | 33200000 | 派生 | 依 period | 是 |
| macdDif | number | MACD DIF | - | 否 | 2.14 | 派生 | 依 period | 是 |
| macdDea | number | MACD DEA | - | 否 | 1.62 | 派生 | 依 period | 是 |
| macdHist | number | MACD 柱 | - | 否 | 1.04 | 派生 | 依 period | 是 |
| kdjK | number | KDJ K 值 | - | 否 | 72.6 | 派生 | 依 period | 是 |
| kdjD | number | KDJ D 值 | - | 否 | 66.1 | 派生 | 依 period | 是 |
| kdjJ | number | KDJ J 值 | - | 否 | 85.5 | 派生 | 依 period | 是 |
| rsi6 | number | 6 周期 RSI | - | 否 | 61.2 | 派生 | 依 period | 否 |



### 17. MarketTemperature


**对象定义**：市场温度对象，用于“市场温度与情绪分析页”。它可以包含评分、等级和构成事实，但首页不应把该对象作为核心结论展示。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 市场温度计算服务 |
| 使用页面 | 市场温度与情绪分析页；首页只提供入口，不返回核心评分 |
| 数据来源 | MarketBreadth、TurnoverSummary、MarketStyle、LimitUpSummary、SectorRankItem |
| 更新频率 | 1-5 分钟；盘后固定 |
| 是否 P0 必需 | 情绪分析页必需；首页不混入 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| score | number | 市场温度分 | 分 | 是 | 68.5 | 计算模型 | 1-5 分钟 | 是 |
| level | string(enum) | COLD / NEUTRAL / WARM / HOT | - | 是 | WARM | 计算模型 | 1-5 分钟 | 是 |
| redRate | number | 红盘率 | ratio | 是 | 0.667 | MarketBreadth | 1-5 分钟 | 是 |
| medianChangePct | number | 中位涨跌幅 | % | 是 | 0.48 | MarketBreadth | 1-5 分钟 | 是 |
| amountRatio20dMedian | number | 成交额相对 20 日中位 | 倍 | 是 | 1.12 | TurnoverSummary | 1-5 分钟 | 是 |
| smallVsLargeSpreadPct | number | 小盘相对大盘强弱 | pct point | 否 | 0.76 | MarketStyle | 1-5 分钟 | 是 |
| mainlineSectors | SectorRankItem[] | 主线方向 Top N | - | 否 | [...] | 板块计算服务 | 1-5 分钟 | 是 |
| mainlineConcentrationRate | number | 主线成交集中度 | ratio | 否 | 0.31 | 板块聚合 | 1-5 分钟 | 否 |
| calcVersion | string | 计算模型版本 | - | 是 | mt_v0.2 | 计算服务 | 低频 | 是 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 计算服务 | 1-5 分钟 | 是 |



### 18. MarketSentiment


**对象定义**：短线情绪对象，用于衡量封板生态、连板高度、炸板率、晋级率等博弈事实。首页不应输出情绪评分作为核心结论。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 市场情绪计算服务 |
| 使用页面 | 市场温度与情绪分析页 |
| 数据来源 | LimitUpSummary、LimitUpStreakLadder、股票行情、涨跌停规则 |
| 更新频率 | 1-5 分钟；盘后固定 |
| 是否 P0 必需 | 情绪分析页必需；首页不混入 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| score | number | 情绪分 | 分 | 是 | 62.0 | 计算模型 | 1-5 分钟 | 是 |
| level | string(enum) | WEAK / NEUTRAL / ACTIVE / EUPHORIC | - | 是 | ACTIVE | 计算模型 | 1-5 分钟 | 是 |
| limitUpCount | integer | 涨停数 | 只 | 是 | 59 | LimitUpSummary | 1-5 分钟 | 是 |
| failedLimitUpCount | integer | 炸板数 | 只 | 是 | 27 | LimitUpSummary | 1-5 分钟 | 是 |
| sealRate | number | 封板率 | ratio | 是 | 0.686 | LimitUpSummary | 1-5 分钟 | 是 |
| highestStreak | integer | 最高连板高度 | 板 | 是 | 6 | LimitUpStreakLadder | 1-5 分钟 | 是 |
| promotionRate | number | 晋级率 | ratio | 否 | 0.42 | 连板计算 | 1-5 分钟 | 否 |
| breakCount | integer | 断板数量 | 只 | 否 | 14 | 连板计算 | 1-5 分钟 | 否 |
| openingPremiumPct | number | 昨日涨停今日开盘溢价 | % | 否 | 2.8 | 涨停池 + 今日开盘 | 日内 | 否 |
| calcVersion | string | 计算模型版本 | - | 是 | ms_v0.2 | 计算服务 | 低频 | 是 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 计算服务 | 1-5 分钟 | 是 |



### 19. RiskIndex


**对象定义**：风险指数对象，用于衡量跌停率、高位崩塌率、亏钱效应和波动风险。首页不直接展示风险分数。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 风险计算服务 |
| 使用页面 | 市场温度与情绪分析页、持仓深度分析、交易计划 |
| 数据来源 | 股票行情、涨跌停统计、历史涨幅、波动率 |
| 更新频率 | 1-5 分钟；盘后固定 |
| 是否 P0 必需 | 情绪分析页 / 持仓分析 P0 可选 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| riskScore | number | 风险分，越高风险越大 | 分 | 是 | 38.5 | 计算模型 | 1-5 分钟 | 是 |
| riskLevel | string(enum) | LOW / MEDIUM / HIGH / EXTREME | - | 是 | MEDIUM | 计算模型 | 1-5 分钟 | 是 |
| limitDownRate | number | 跌停率 | ratio | 是 | 0.0016 | LimitUpSummary + 样本池 | 1-5 分钟 | 是 |
| downGt3Pct | number | 跌超 3% 占比 | ratio | 是 | 0.041 | MarketBreadth | 1-5 分钟 | 是 |
| highLevelCollapseRate | number | 高位崩塌率 | ratio | 否 | 0.083 | 高位池计算 | 1-5 分钟 | 否 |
| failedLimitUpRate | number | 炸板率 | ratio | 否 | 0.314 | LimitUpSummary | 1-5 分钟 | 是 |
| indexVolatility20d | number | 指数 20 日波动率 | % | 否 | 17.2 | 指数历史行情 | 日 | 否 |
| riskFlags | string[] | 风险标签 | - | 否 | ["HIGH_FAIL_RATE"] | 计算服务 | 1-5 分钟 | 否 |
| calcVersion | string | 计算模型版本 | - | 是 | risk_v0.2 | 计算服务 | 低频 | 是 |
| asOf | string(datetime) | 数据时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 计算服务 | 1-5 分钟 | 是 |



### 20. OpportunitySignal


**对象定义**：机会信号对象，承接“发现机会”闭环，表示某只股票、某个板块或某类条件触发了可跟踪信号。P0 不直接形成买卖建议。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 机会探查服务 |
| 使用页面 | 机会发现页、自选页、持仓页、首页快捷入口 |
| 数据来源 | 行情、板块、技术指标、用户偏好、规则引擎 |
| 更新频率 | 1-5 分钟 / 日频 |
| 是否 P0 必需 | P0 闭环可选，后续重点扩展 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| signalId | string | 信号 ID | - | 是 | sig_20260428_0001 | 信号服务 | 实时生成 | 是 |
| tradeDate | string(date) | 触发交易日 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| signalType | string(enum) | SECTOR_STRENGTH / BREAKOUT / VOLUME_EXPANSION / LIMIT_UP / PREFERENCE_MATCH | - | 是 | SECTOR_STRENGTH | 规则引擎 | 1-5 分钟 | 是 |
| targetType | string(enum) | STOCK / SECTOR / INDEX | - | 是 | SECTOR | 规则引擎 | 1-5 分钟 | 是 |
| targetCode | string | 标的代码 | - | 是 | BK0421 | 板块 / 股票基础表 | 低频 | 是 |
| targetName | string | 标的名称 | - | 是 | 储能 | 基础表 | 低频 | 是 |
| title | string | 信号标题 | - | 是 | 储能板块放量领涨 | 信号服务 | 1-5 分钟 | 是 |
| strengthScore | number | 信号强度分，不等同买卖建议 | 分 | 否 | 76 | 规则引擎 | 1-5 分钟 | 否 |
| facts | object[] | 触发事实列表 | - | 是 | [{field:"changePct",value:3.86}] | 规则引擎 | 1-5 分钟 | 是 |
| triggerFields | string[] | 触发字段 | - | 否 | ["changePct","amountRatio20dMedian"] | 规则引擎 | 1-5 分钟 | 是 |
| status | string(enum) | NEW / WATCHING / DISMISSED / EXPIRED | - | 是 | NEW | 用户行为 / 规则 | 实时 | 是 |
| createdAt | string(datetime) | 创建时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 信号服务 | 实时 | 是 |



### 21. WatchStock


**对象定义**：用户自选股对象。P0 以用户手工添加为主。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 用户自选服务 |
| 使用页面 | 自选页、首页自选模块、个股详情页 |
| 数据来源 | 用户手工维护 + QuoteSnapshot |
| 更新频率 | 用户行为实时；行情字段随行情刷新 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| watchId | string | 自选记录 ID | - | 是 | watch_001 | 自选服务 | 创建时 | 是 |
| userId | string | 用户 ID | - | 是 | u_1001 | 用户系统 | 固定 | 是 |
| stockCode | string | 股票代码 | - | 是 | 300750.SZ | 用户输入 / 搜索 | 固定 | 是 |
| stockName | string | 股票名称 | - | 是 | 宁德时代 | 股票基础表 | 低频 | 是 |
| groupName | string | 自选分组 | - | 否 | 新能源 | 用户输入 | 实时 | 是 |
| tags | string[] | 用户标签 | - | 否 | ["储能","观察"] | 用户输入 | 实时 | 否 |
| note | string | 备注 | - | 否 | 观察二季度订单 | 用户输入 | 实时 | 否 |
| sortOrder | integer | 排序 | - | 是 | 10 | 用户行为 | 实时 | 是 |
| quote | QuoteSnapshot | 行情快照 | - | 否 | {lastPrice:188.42} | 行情服务 | 15-60 秒 | 是 |
| createdAt | string(datetime) | 添加时间 | - | 是 | 2026-04-22T11:20:00+08:00 | 自选服务 | 创建时 | 是 |
| updatedAt | string(datetime) | 更新时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 自选服务 | 实时 | 是 |



### 22. PositionStock


**对象定义**：用户手工登记的持仓对象。不接真实券商账户，不包含真实交易权限，不代表券商持仓。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 手工持仓服务 |
| 使用页面 | 持仓页、个股详情页、交易计划页 |
| 数据来源 | 用户手工登记 + QuoteSnapshot |
| 更新频率 | 用户行为实时；盈亏随行情刷新 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| positionId | string | 持仓 ID | - | 是 | pos_001 | 持仓服务 | 创建时 | 是 |
| userId | string | 用户 ID | - | 是 | u_1001 | 用户系统 | 固定 | 是 |
| stockCode | string | 股票代码 | - | 是 | 300750.SZ | 用户输入 | 固定 | 是 |
| stockName | string | 股票名称 | - | 是 | 宁德时代 | 股票基础表 | 低频 | 是 |
| quantity | number | 持仓数量 | 股 | 是 | 1000 | 用户输入 | 实时 | 是 |
| costPrice | number | 成本价 | 元 | 是 | 176.50 | 用户输入 | 实时 | 是 |
| lastPrice | number | 最新价 | 元 | 否 | 188.42 | 行情服务 | 15-60 秒 | 是 |
| marketValue | number | 当前市值 | 元 | 否 | 188420 | 派生 | 15-60 秒 | 是 |
| costAmount | number | 成本金额 | 元 | 是 | 176500 | 派生 | 实时 | 是 |
| unrealizedPnl | number | 浮动盈亏 | 元 | 否 | 11920 | 派生 | 15-60 秒 | 是 |
| unrealizedPnlPct | number | 浮动盈亏率 | % | 否 | 6.75 | 派生 | 15-60 秒 | 是 |
| holdingDays | integer | 持仓天数 | 天 | 否 | 18 | 派生 | 日 | 否 |
| sourceType | string(enum) | 来源，P0 固定 MANUAL | - | 是 | MANUAL | 系统 | 固定 | 是 |
| note | string | 持仓备注 | - | 否 | 观察 20 日线支撑 | 用户输入 | 实时 | 否 |
| createdAt | string(datetime) | 创建时间 | - | 是 | 2026-04-10T10:15:00+08:00 | 持仓服务 | 创建时 | 是 |
| updatedAt | string(datetime) | 更新时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 持仓服务 | 实时 | 是 |



### 23. PositionDeepAnalysis


**对象定义**：持仓深度分析对象，围绕用户手工持仓进行行情、技术、板块、风险与计划联动分析。P0 可先结构预留和 Mock。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 持仓分析服务 |
| 使用页面 | 持仓深度分析页、个股详情页、交易计划页 |
| 数据来源 | PositionStock、QuoteSnapshot、KlineCandle、TechnicalIndicators、SectorRankItem、RiskIndex |
| 更新频率 | 用户打开时计算；盘中 1-5 分钟刷新 |
| 是否 P0 必需 | P0 可选，闭环扩展必需 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| analysisId | string | 分析 ID | - | 是 | ana_001 | 分析服务 | 创建时 | 是 |
| positionId | string | 持仓 ID | - | 是 | pos_001 | 持仓服务 | 固定 | 是 |
| stockCode | string | 股票代码 | - | 是 | 300750.SZ | PositionStock | 固定 | 是 |
| analysisDate | string(date) | 分析日期 | - | 是 | 2026-04-28 | 交易日历 | 日 | 是 |
| quote | QuoteSnapshot | 当前行情 | - | 是 | {...} | 行情服务 | 15-60 秒 | 是 |
| technicalSummary | object | 技术摘要 | - | 否 | {trend:"ABOVE_MA20"} | 技术指标服务 | 1-5 分钟 | 是 |
| sectorExposure | SectorRankItem[] | 相关板块表现 | - | 否 | [...] | 板块服务 | 1-5 分钟 | 是 |
| riskFlags | string[] | 风险标签 | - | 否 | ["BREAK_MA20"] | 风险服务 | 1-5 分钟 | 否 |
| supportLevels | number[] | 支撑位 | 元 | 否 | [176.5,168.2] | 技术计算 | 日 / 分钟 | 否 |
| resistanceLevels | number[] | 压力位 | 元 | 否 | [192.8,205.0] | 技术计算 | 日 / 分钟 | 否 |
| relatedTradePlans | TradePlan[] | 关联交易计划 | - | 否 | [...] | 交易计划服务 | 实时 | 否 |
| summaryText | string | 机器摘要文本，需标识非投资建议 | - | 否 | 当前价格站上20日均线... | 分析服务 | 打开时 | 否 |
| updatedAt | string(datetime) | 更新时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 分析服务 | 1-5 分钟 | 是 |



### 24. TradePlan


**对象定义**：用户交易计划对象，承接观察和验证后的执行纪律。不代表真实委托，不接交易账户。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 交易计划服务 |
| 使用页面 | 交易计划页、持仓页、个股详情页、提醒页 |
| 数据来源 | 用户手工输入 + 行情字段辅助 |
| 更新频率 | 用户行为实时 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| planId | string | 计划 ID | - | 是 | plan_001 | 交易计划服务 | 创建时 | 是 |
| userId | string | 用户 ID | - | 是 | u_1001 | 用户系统 | 固定 | 是 |
| stockCode | string | 股票代码 | - | 是 | 300750.SZ | 用户输入 / 搜索 | 固定 | 是 |
| stockName | string | 股票名称 | - | 是 | 宁德时代 | 股票基础表 | 低频 | 是 |
| planType | string(enum) | BUY_WATCH / ADD / REDUCE / SELL / HOLD | - | 是 | BUY_WATCH | 用户输入 | 实时 | 是 |
| entryPrice | number | 计划买入价 / 观察触发价 | 元 | 否 | 184.00 | 用户输入 | 实时 | 是 |
| stopLossPrice | number | 止损价 | 元 | 否 | 171.50 | 用户输入 | 实时 | 是 |
| takeProfitPrice | number | 止盈价 | 元 | 否 | 205.00 | 用户输入 | 实时 | 是 |
| positionSizePct | number | 计划仓位 | % | 否 | 15 | 用户输入 | 实时 | 否 |
| rationale | string | 计划理由 | - | 否 | 储能主线放量，回踩20日线观察 | 用户输入 | 实时 | 是 |
| status | string(enum) | DRAFT / ACTIVE / TRIGGERED / DONE / CANCELLED | - | 是 | ACTIVE | 用户行为 | 实时 | 是 |
| alertRules | AlertRule[] | 关联提醒 | - | 否 | [...] | 提醒服务 | 实时 | 否 |
| createdAt | string(datetime) | 创建时间 | - | 是 | 2026-04-28T10:20:00+08:00 | 交易计划服务 | 创建时 | 是 |
| updatedAt | string(datetime) | 更新时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 交易计划服务 | 实时 | 是 |



### 25. AlertRule


**对象定义**：提醒规则对象，用于价格、涨跌幅、技术条件、计划触发等提醒。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 提醒服务 |
| 使用页面 | 提醒页、个股详情页、持仓页、交易计划页 |
| 数据来源 | 用户规则 + 行情订阅 / 扫描任务 |
| 更新频率 | 用户行为实时；规则扫描 15-60 秒或分钟级 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ruleId | string | 提醒规则 ID | - | 是 | alert_001 | 提醒服务 | 创建时 | 是 |
| userId | string | 用户 ID | - | 是 | u_1001 | 用户系统 | 固定 | 是 |
| scopeType | string(enum) | STOCK / SECTOR / INDEX / PLAN | - | 是 | STOCK | 用户输入 | 创建时 | 是 |
| targetCode | string | 目标代码 | - | 是 | 300750.SZ | 用户输入 / 计划 | 创建时 | 是 |
| targetName | string | 目标名称 | - | 是 | 宁德时代 | 基础表 | 低频 | 是 |
| conditionType | string(enum) | PRICE / CHANGE_PCT / BREAK_MA / AMOUNT / PLAN_PRICE | - | 是 | PRICE | 用户输入 | 创建时 | 是 |
| operator | string(enum) | GT / GTE / LT / LTE / CROSS_UP / CROSS_DOWN | - | 是 | GTE | 用户输入 | 创建时 | 是 |
| threshold | number | 阈值 | 依条件 | 是 | 190 | 用户输入 | 创建时 | 是 |
| frequency | string(enum) | ONCE / ONCE_PER_DAY / EVERY_TIME | - | 是 | ONCE | 用户输入 | 创建时 | 是 |
| channels | string[] | 提醒渠道 | - | 是 | ["IN_APP"] | 用户配置 | 创建时 | 是 |
| enabled | boolean | 是否启用 | - | 是 | true | 用户行为 | 实时 | 是 |
| lastTriggeredAt | string(datetime) | 上次触发时间 | - | 否 | null | 提醒服务 | 实时 | 是 |
| createdAt | string(datetime) | 创建时间 | - | 是 | 2026-04-28T10:25:00+08:00 | 提醒服务 | 创建时 | 是 |
| updatedAt | string(datetime) | 更新时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 提醒服务 | 实时 | 是 |



### 26. InvestmentPreference


**对象定义**：用户投资偏好对象，用于机会筛选、提醒默认值、首页快捷入口个性化。P0 可先做基础设置，不做复杂画像。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 用户偏好服务 |
| 使用页面 | 设置页、机会发现页、自选页、首页快捷入口 |
| 数据来源 | 用户手工设置 |
| 更新频率 | 用户行为实时 |
| 是否 P0 必需 | 可选；建议 P0 预留 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| userId | string | 用户 ID | - | 是 | u_1001 | 用户系统 | 固定 | 是 |
| marketScope | string[] | 关注市场范围 | - | 是 | ["CN_A"] | 用户设置 | 实时 | 是 |
| riskPreference | string(enum) | LOW / MEDIUM / HIGH | - | 是 | MEDIUM | 用户设置 | 实时 | 是 |
| stylePreference | string[] | 偏好风格 | - | 否 | ["GROWTH","SMALL_CAP"] | 用户设置 | 实时 | 否 |
| sectorPreferences | string[] | 偏好板块 ID | - | 否 | ["BK0421"] | 用户设置 | 实时 | 否 |
| avoidSt | boolean | 是否规避 ST | - | 是 | true | 用户设置 | 实时 | 是 |
| maxPositionCount | integer | 最大持仓数偏好 | 只 | 否 | 8 | 用户设置 | 实时 | 否 |
| defaultHoldingPeriod | string(enum) | 默认持有周期 | - | 否 | SWING | 用户设置 | 实时 | 否 |
| alertQuietStart | string | 提醒免打扰开始 | - | 否 | 22:00 | 用户设置 | 实时 | 否 |
| alertQuietEnd | string | 提醒免打扰结束 | - | 否 | 08:00 | 用户设置 | 实时 | 否 |
| updatedAt | string(datetime) | 更新时间 | - | 是 | 2026-04-28T14:56:00+08:00 | 用户偏好服务 | 实时 | 是 |



### 27. DataSourceStatus


**对象定义**：数据源状态对象，用于首页显示数据新鲜度、异常降级提示和后端监控。


| 项目 | 内容 |
| --- | --- |
| 所属系统 | 数据源监控服务 |
| 使用页面 | 首页、系统状态页、后台监控 |
| 数据来源 | ETL / 同步任务 / 数据源探针 |
| 更新频率 | 1 分钟或按同步任务 |
| 是否 P0 必需 | 是 |


**字段列表**


| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sourceId | string | 数据源 ID | - | 是 | tushare | 系统配置 | 低频 | 是 |
| sourceName | string | 数据源名称 | - | 是 | Tushare | 系统配置 | 低频 | 是 |
| dataDomain | string(enum) | QUOTE / INDEX / KLINE / MONEY_FLOW / CALENDAR / SECTOR | - | 是 | QUOTE | 系统配置 | 低频 | 是 |
| status | string(enum) | READY / PARTIAL / DELAYED / UNAVAILABLE | - | 是 | READY | 监控服务 | 1 分钟 | 是 |
| latestDataTime | string(datetime) | 最新数据时间 | - | 否 | 2026-04-28T14:56:00+08:00 | 同步任务 | 1 分钟 | 是 |
| latencyMs | integer | 访问延迟 | 毫秒 | 否 | 186 | 探针 | 1 分钟 | 否 |
| completenessPct | number | 完整度 | % | 否 | 99.6 | 校验任务 | 1 分钟 / 日 | 是 |
| errorCode | string|null | 源错误码 | - | 否 | null | 同步任务 | 实时 | 是 |
| errorMessage | string|null | 错误信息 | - | 否 | null | 同步任务 | 实时 | 是 |
| fallbackSourceId | string|null | 降级数据源 | - | 否 | local_daily_cache | 配置中心 | 低频 | 否 |
| updatedAt | string(datetime) | 状态更新时间 | - | 是 | 2026-04-28T14:56:30+08:00 | 监控服务 | 1 分钟 | 是 |



---

## 2. P0 字段分层

### 2.1 P0 已具备 / 可由基础行情直接推导字段

> 说明：本节按 P0 实现口径标记“已具备 / 易具备”，表示可由交易日历、股票基础表、指数 / 个股日线、行情快照、板块映射计算得到；仍需以后端实际库表核验为准。

| 类别 | 字段 |
|---|---|
| 交易日 | `tradeDate`、`prevTradeDate`、`isTradingDay`、`sessionStatus` |
| 指数快照 | `indexCode`、`indexName`、`last`、`prevClose`、`change`、`changePct`、`amount` |
| 个股快照 | `stockCode`、`stockName`、`open`、`high`、`low`、`lastPrice`、`prevClose`、`changePct`、`volume`、`amount` |
| 市场广度 | `upCount`、`downCount`、`flatCount`、`redRate`、`medianChangePct`、`upGt3Pct`、`downGt3Pct` |
| 成交额 | `totalAmount`、`prevTotalAmount`、`amountRatio20dMedian`、`sseAmount`、`szseAmount` |
| 涨跌停 | `limitUpCount`、`limitDownCount`、`touchedLimitUpCount`、`failedLimitUpCount`、`sealRate` |
| 板块榜单 | `sectorId`、`sectorName`、`changePct`、`amount`、`redRate`、`leadingStock*` |
| 用户闭环 | `WatchStock`、`PositionStock`、`TradePlan`、`AlertRule` 基础字段 |

### 2.2 P0 暂缺 / 高风险字段

| 字段 | 暂缺原因 | P0 降级方案 |
|---|---|---|
| `mainNetInflow`、`superLargeNetInflow`、`largeNetInflow` | 依赖资金流分档源，普通日线无法可靠推导 | 首页显示 `dataStatus=UNAVAILABLE`，用成交额和板块成交额替代 |
| `northboundNetInflow` | 依赖互联互通数据；且 P0 先专注 A 股 | 首页先隐藏；资金页后续补充 |
| `openingPremiumPct` | 依赖昨日涨停池与今日开盘数据稳定关联 | 情绪分析页 P0.1 补 |
| `promotionRate`、`breakCount` | 依赖连续涨停历史链路 | 先展示最高板和各高度数量 |
| `highLevelCollapseRate` | 依赖高位池定义与复权历史行情 | 先不在首页展示 |
| `turnoverRate`、`marketCap` | 依赖流通股本 / 总股本 | 个股详情可空；首页榜单不强依赖 |
| `volumeRatio` | 依赖分钟均量或历史成交量口径 | 个股榜单可空 |
| `supportLevels`、`resistanceLevels` | 技术计算口径待定 | 持仓深度分析页后续补 |

### 2.3 需要数据基座补充的字段

1. 当日交易参考表：`up_limit_price`、`down_limit_price`、`limit_pct`、`is_suspended`、`is_no_price_limit`。
2. 股票有效样本池：剔除 ST / 退市整理 / 停牌 / 无涨跌幅限制 / 上市不足 20 日。
3. 板块 / 主题映射表：`sector_id`、`stock_code`、`effective_start_date`、`effective_end_date`。
4. 历史全市场成交额序列：用于 `amount20dMedian`、`amountRatio20dMedian`。
5. 涨停历史链路：用于 `streak`、`promotionRate`、`breakCount`。
6. 资金流分档数据：用于 `MoneyFlowSummary`。
7. 流通股本 / 自由流通市值：用于换手率、市值热力图、风格增强计算。
8. 统一数据源状态表：用于 `DataSourceStatus` 和接口降级提示。

---

## 3. 给 02 HTML Showcase 的 Mock 数据建议

1. 首页 Mock 固定使用 `2026-04-28T14:56:00+08:00`，交易状态为 `OPEN`。
2. 首页展示指数建议：上证指数、深证成指、创业板指、沪深300、中证1000、科创50。
3. 首页不要展示市场温度分、情绪分、风险分，只展示快捷入口：“市场温度与情绪分析”。
4. 红涨绿跌示例：
   - 上证指数 `changePct: 0.92`，`direction: "UP"`，前端渲染红色。
   - 跌幅榜股票 `changePct: -8.41`，`direction: "DOWN"`，前端渲染绿色。
5. 首页模块建议使用：
   - 顶部：交易状态、更新时间、数据源状态。
   - 指数卡片：`IndexSnapshot[]`。
   - 市场广度：`MarketBreadth`。
   - 成交额：`TurnoverSummary`。
   - 涨跌停：`LimitUpSummary` + `LimitUpStreakLadder[]`。
   - 板块榜：`SectorRankItem[]`。
   - 个股榜：`StockRankItem[]`。
   - 快捷入口：`quickEntries[]`。

---

## 4. 给 03 组件库的字段映射建议

| 组件 | 主要对象 | 关键字段 | 颜色规则 |
|---|---|---|---|
| `TradingStatusChip` | TradingDay | `sessionStatus`、`asOf`、`isDelayed` | 交易中状态点；延迟黄色 |
| `IndexTickerCard` | IndexSnapshot | `indexName`、`last`、`change`、`changePct`、`direction` | `UP=red`、`DOWN=green`、`FLAT=gray` |
| `MarketBreadthBar` | MarketBreadth | `upCount`、`downCount`、`flatCount`、`redRate` | 上涨红、下跌绿、平盘灰 |
| `TurnoverMetricCard` | TurnoverSummary | `totalAmount`、`amountChangePct`、`amountRatio20dMedian` | 成交额中性；变化方向按正负 |
| `LimitUpStatsCard` | LimitUpSummary | `limitUpCount`、`limitDownCount`、`sealRate`、`highestStreak` | 涨停红、跌停绿 |
| `StreakLadderMini` | LimitUpStreakLadder | `streak`、`count`、`stocks` | 高度可强调，但避免霓虹大屏风 |
| `SectorRankTable` | SectorRankItem | `rank`、`sectorName`、`changePct`、`redRate`、`amount` | 涨跌幅按方向 |
| `StockRankTable` | StockRankItem | `rank`、`stockName`、`price`、`changePct`、`amount` | 涨跌幅按方向 |
| `DataSourceBadge` | DataSourceStatus | `status`、`latestDataTime`、`completenessPct` | 异常橙 / 红；正常中性 |

---

## 5. 待产品总控确认问题

1. 首页是否展示资金流摘要？建议：如果没有稳定资金流源，首页仅展示成交额与板块成交额，不硬放“主力净流入”。
2. 首页是否展示热力图？建议：P0 可放轻量热力图，若 HTML showcase 时间紧，可先用板块榜替代。
3. 板块体系优先用申万行业、概念板块，还是内部主题板块？建议 P0 先双轨：行业稳定，概念用于机会发现。
4. 个股榜单首期保留哪些榜？建议 P0 首页只保留涨幅榜、跌幅榜、成交额榜、涨停榜。
5. 市场温度 / 情绪分是否允许在首页以入口角标展示？建议 v0.2 继续不展示分数，只显示入口和事实摘要。
6. 手工持仓是否要求支持多账户分组？建议 P0 先不做账户，最多做组合 / 分组。
7. API 时间频率：P0 是先支持盘后日频，还是直接按盘中延迟行情设计？建议接口按盘中设计，数据源不足时返回 `dataStatus=DELAYED`。

---

## 32. v0.2 字段来源重点修订

### 32.1 首页核心对象的数据来源优先级

| 对象 | 优先来源 | 说明 |
|---|---|---|
| `TradingDay` | `trade_cal` | `cal_date/is_open/pretrade_date` 是交易日判断基础 |
| `IndexSnapshot` | `index_daily` | `amount` 从千元归一为元 |
| `QuoteSnapshot` | `daily + daily_basic + stock_basic + stk_limit` | 个股价格、换手、市值、涨跌停价合并为业务快照 |
| `MarketBreadth` | `daily + stock_basic + limit_list_d` | 用 `pct_chg` 计算涨跌家数、红盘率和中位涨跌幅 |
| `TurnoverSummary` | `daily` | 用 `amount * 1000` 聚合全市场成交额 |
| `LimitUpSummary` | `limit_list_d` 优先，`daily + stk_limit` 兜底 | `limit_list_d` 可直接支持涨停、跌停、炸板、连板 |
| `SectorRankItem` | `sw_daily` + `moneyflow_ind_dc` | 行业行情与板块资金流合并为板块榜 |
| `MoneyFlowSummary` | `moneyflow_mkt_dc` | 首页只展示资金流事实，不展示资金面分数 |

### 32.2 与首页边界相关的明确约束

1. `MarketTemperature.score`、`MarketSentiment.score`、`RiskIndex.riskScore` 不进入首页 `home-overview` 聚合核心 response。
2. 首页可返回 `quickEntries` 中的“市场温度与情绪”入口，但不得以角标形式展示温度分/情绪分。
3. 资金流属于客观事实，可以作为首页模块；如果 `moneyflow_mkt_dc` 不可用，返回 `dataStatus=UNAVAILABLE` 并模块级降级。
4. 涨跌停模块需展示数据口径提示：`limit_list_d 不含 ST 股票统计`。
5. `direction=UP` 必须渲染红色，`direction=DOWN` 必须渲染绿色，`direction=FLAT` 渲染灰色。

### 32.3 v0.2 待数据基座确认

1. Tushare 原始表是否已在 PostgreSQL 中完成单位归一化；若未完成，建议建立 `wealth_*_view` 统一处理。
2. `limit_list_d.amount/fd_amount/limit_amount` 的入库单位需由数据基座确认后固化。
3. `CN_A_COMMON` 样本池是否排除 ST、新股、停牌、无涨跌幅限制股票，需产品总控确认。
4. 申万行业、东财行业/概念/地域板块同时存在时，首页板块榜默认体系需产品确认。
