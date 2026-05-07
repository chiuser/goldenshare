# 财势乾坤｜P0 数据字典 v0.3

建议路径：`/docs/wealth/api/p0-data-dictionary.md`  
负责人：`04_API 契约与数据字典`  
版本：`v0.3`  
日期：`2026-05-06`  
状态：Audit 修订稿

---

## 0. 本轮审计结论

本版围绕“市场总览”开发落地重新收敛 P0 数据字典：

1. 市场总览归属 **乾坤行情**，不是独立一级菜单；桌面端 API 需要支持 `TopMarketBar`、`Breadcrumb`、`ShortcutBar`。
2. 市场总览只展示 A 股市场客观事实，不返回市场温度、市场情绪、资金面分数、风险指数作为核心结论。
3. Tushare 只作为已落库数据基座和字段口径参考；财势乾坤 API 使用业务对象和业务字段组织。
4. 字段单位、数值尺度默认保持 Tushare / PostgreSQL 落库口径；已确认特例：`trade_cal.is_open` 已落库为 boolean。
5. 行业、概念、地域板块使用东方财富板块体系：`dc_index`、`dc_member`、`dc_daily`；板块资金流补充使用 `moneyflow_ind_dc`。
6. 首页榜单使用东方财富热榜 `dc_hot`；传统涨跌幅榜、成交额榜、换手榜可后续作为扩展接口，不作为本轮 P0 默认榜单口径。
7. 所有行情对象必须提供或可派生 `direction`，前端按中国 A 股规则：`UP=红色`、`DOWN=绿色`、`FLAT=灰色`。

---

## 1. 设计边界

### 1.1 页面边界

市场总览是 **A 股市场客观事实总览页**。它回答“市场发生了什么”，不回答“该买还是该卖”。

禁止作为市场总览核心展示字段返回：

```text
marketTemperatureScore
marketSentimentScore
capitalScore
riskIndexScore
buySuggestion
sellSuggestion
positionSuggestion
tomorrowPrediction
subjectiveMarketConclusion
```

快捷入口可以返回入口名称、入口描述、路由、可用状态、待处理数量、是否有更新，但不得返回市场温度、情绪指数、资金面分数、风险指数的具体数值。

### 1.2 字段命名与单位口径

| 项目 | 规则 |
|---|---|
| API 字段命名 | `lowerCamelCase`，使用财势乾坤业务命名。 |
| 源字段名 | 在数据字典和附录中记录 Tushare / 落库字段名。 |
| 日期 | API 返回 `YYYY-MM-DD`，落库源可能为 `YYYYMMDD`。 |
| 时间 | API 返回 ISO 8601 或源字段时间字符串，具体字段说明中标注。 |
| 金额单位 | 默认保持 Tushare / 落库口径，不隐式换算。 |
| 成交量单位 | 默认保持 Tushare / 落库口径，不隐式换算。 |
| 涨跌幅 | 百分数数值，例如 `1.23` 表示 `1.23%`。 |
| 比率 | `rate` 默认 0-1 小数；`Pct` 默认百分数数值。 |
| 涨跌方向 | `UP` / `DOWN` / `FLAT` / `UNKNOWN`。 |
| 涨跌颜色 | `UP=红色`、`DOWN=绿色`、`FLAT=灰色`。 |

### 1.3 数据源使用清单

| 业务域 | 主数据集 / 落库表 | 主要字段 | 说明 |
|---|---|---|---|
| 交易日 | `trade_cal` / `raw_tushare.trade_cal` | `cal_date`、`is_open`、`pretrade_date` | `is_open` 已在落库时改为 boolean，这是当前唯一确认的类型特例。 |
| 股票基础 | `stock_basic` / `raw_tushare.stock_basic` | `ts_code`、`name`、`industry`、`market`、`exchange`、`list_status` | 用于个股名称、交易所、市场层级、行业初始归属。 |
| 个股日线 | `daily` / `raw_tushare.daily` | `open`、`high`、`low`、`close`、`pre_close`、`change`、`pct_chg`、`vol`、`amount` | API 字段业务化命名，但单位默认保持 Tushare / 落库口径。 |
| 每日指标 | `daily_basic` / `raw_tushare.daily_basic` | `turnover_rate`、`volume_ratio`、`pe_ttm`、`pb`、`total_mv`、`circ_mv` | 用于换手率、量比、市值、估值字段。 |
| 指数日线 | `index_daily` / `raw_tushare.index_daily` | `open`、`high`、`low`、`close`、`pre_close`、`change`、`pct_chg`、`vol`、`amount` | 用于 TopMarketBar 和指数卡片。 |
| 涨跌停价格 | `stk_limit` / `raw_tushare.stk_limit` | `up_limit`、`down_limit`、`pre_close` | 用于涨停 / 跌停状态辅助校验。 |
| 涨跌停 / 炸板 | `limit_list_d` / `raw_tushare.limit_list_d` | `limit`、`open_times`、`up_stat`、`limit_times`、`first_time`、`last_time`、`fd_amount` | 用于涨停、跌停、炸板、封板率、连板天梯。 |
| 大盘资金流 | `moneyflow_mkt_dc` / `raw_tushare.moneyflow_mkt_dc` | `net_amount`、`net_amount_rate`、`buy_elg_amount`、`buy_lg_amount`、`buy_md_amount`、`buy_sm_amount` | 用于首页大盘资金流事实，不输出资金面分数。 |
| 东方财富板块列表 | `dc_index` / `raw_tushare.dc_index` | `ts_code`、`name`、`leading`、`leading_code`、`pct_change`、`leading_pct`、`total_mv`、`turnover_rate`、`up_num`、`down_num`、`idx_type`、`level` | P0 行业 / 概念 / 地域板块主口径。 |
| 东方财富板块成分 | `dc_member` / `raw_tushare.dc_member` | `trade_date`、`ts_code`、`con_code`、`name` | 用于板块下钻和板块红盘率精算。 |
| 东方财富板块日线 | `dc_daily` / `raw_tushare.dc_daily` | `open`、`high`、`low`、`close`、`change`、`pct_change`、`vol`、`amount`、`swing`、`turnover_rate` | 用于板块行情、热力图、板块榜。 |
| 东方财富板块资金流 | `moneyflow_ind_dc` / `raw_tushare.moneyflow_ind_dc` | `net_amount`、`net_amount_rate`、`buy_elg_amount`、`buy_lg_amount`、`buy_md_amount`、`buy_sm_amount`、`rank` | 用于板块资金流补充，不替代板块主行情。 |
| 东方财富热榜 | `dc_hot` / `raw_tushare.dc_hot` | `data_type`、`ts_code`、`ts_name`、`rank`、`pct_change`、`current_price`、`rank_time` | P0 首页榜单 / 热榜主口径，默认 `market=A股市场`。 |

### 1.4 推荐数据基座视图

| 视图 | 用途 |
|---|---|
| `wealth_trade_day_view` | 统一交易日和交易阶段状态。 |
| `wealth_index_snapshot_view` | 核心指数快照。 |
| `wealth_market_breadth_snapshot` | 市场广度和涨跌幅分布预聚合。 |
| `wealth_market_style_snapshot` | 市场风格对比。 |
| `wealth_turnover_summary_snapshot` | 全市场成交额与历史成交额。 |
| `wealth_moneyflow_market_snapshot` | 大盘资金流事实。 |
| `wealth_limitup_snapshot` | 涨停、跌停、炸板、封板率。 |
| `wealth_limitup_streak_snapshot` | 连板天梯。 |
| `wealth_sector_rank_snapshot` | 东方财富行业/概念/地域板块榜。 |
| `wealth_sector_heatmap_snapshot` | 板块热力图节点。 |
| `wealth_stock_hot_rank_snapshot` | 东方财富热榜。 |
| `wealth_data_source_status` | 数据源状态与质量校验。 |

---

## 2. 红涨绿跌与展示派生规则

```text
if changePct > 0 → direction = UP
if changePct < 0 → direction = DOWN
if changePct == 0 → direction = FLAT
if changePct is null → direction = UNKNOWN
```

前端必须统一映射：

| direction | A 股显示含义 | 颜色 |
|---|---|---|
| `UP` | 上涨 | 红色 |
| `DOWN` | 下跌 | 绿色 |
| `FLAT` | 平盘 | 灰色 |
| `UNKNOWN` | 未知 / 不适用 | 中性灰 |

---

## 3. 市场总览 P0 对象字典

## 3.1 TradingDay

**对象定义**：交易日与市场状态对象，用于确定当前或指定日期是否为 A 股交易日、当前展示数据属于哪个交易日。  
**所属系统**：乾坤行情 / 交易日历服务  
**使用页面和模块**：TopMarketBar、PageHeader、全部行情模块  
**数据来源**：`raw_tushare.trade_cal`，其中 `is_open` 已落库为 boolean  
**更新频率**：日历日更新；页面状态分钟级派生  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不直接参与涨跌色，但影响数据日期与交易状态展示。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `tradeDate` | string(date) | 交易日 | - | 是 | `2026-04-28` | trade_cal.cal_date | 日频/按源 | 是 |
| `market` | enum | 市场，P0 固定 A 股 | - | 是 | `CN_A` | 系统配置 | 日频/按源 | 是 |
| `exchangeCalendar` | string | 使用的交易所日历 | - | 是 | `SSE` | trade_cal.exchange | 日频/按源 | 是 |
| `isTradingDay` | boolean | 是否交易日；已确认落库为 boolean | - | 是 | `true` | trade_cal.is_open | 日频/按源 | 是 |
| `prevTradeDate` | string(date) | 上一交易日 | - | 是 | `2026-04-27` | trade_cal.pretrade_date | 日频/按源 | 是 |
| `sessionStatus` | enum | PRE_OPEN / OPEN / NOON_BREAK / CLOSED / HOLIDAY | - | 是 | `CLOSED` | 服务端时间派生 | 分钟 | 是 |
| `timezone` | string | 交易时区 | - | 是 | `Asia/Shanghai` | 系统配置 | 日频/按源 | 是 |

## 3.2 DataSourceStatus

**对象定义**：数据源与数据集状态对象，用于页面展示数据新鲜度、异常降级和数据源 Tooltip。  
**所属系统**：数据中心 / 数据源监控服务  
**使用页面和模块**：TopMarketBar、PageHeader、数据源状态提示  
**数据来源**：数据同步任务、质量校验任务、raw_tushare 各表 max(trade_date)  
**更新频率**：任务完成或分钟级  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不直接参与红涨绿跌；用于 warning/error 状态颜色。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `sourceId` | string | 数据源 ID | - | 是 | `tushare_daily` | 内部配置 | 日频/按源 | 是 |
| `dataset` | string | 数据集名称 | - | 是 | `daily` | Tushare api_name | 日频/按源 | 是 |
| `tableName` | string | 落库表名 | - | 是 | `raw_tushare.daily` | 数据基座配置 | 日频/按源 | 是 |
| `dataDomain` | enum | QUOTE / INDEX / SECTOR / MONEY_FLOW / LIMIT_UP / CALENDAR / HOT_RANK | - | 是 | `QUOTE` | 系统配置 | 日频/按源 | 是 |
| `status` | enum | READY / PARTIAL / DELAYED / UNAVAILABLE | - | 是 | `READY` | 同步状态 | 日频/按源 | 是 |
| `latestTradeDate` | string(date) | 最新交易日 | - | 否 | `2026-04-28` | max(trade_date) | 日频/按源 | 是 |
| `latestDataTime` | datetime | 最新同步时间 | - | 否 | `2026-04-28T17:10:00+08:00` | 同步任务 | 日频/按源 | 是 |
| `rowCount` | integer | 当前交易日记录数 | 行 | 否 | `5288` | 质量校验 | 日频/按源 | 是 |
| `completenessPct` | number | 完整度 | % | 否 | `99.6` | 质量校验 | 日频/按源 | 是 |
| `errorCode` | string | 错误码 | - | 否 | `null` | 同步任务 | 日频/按源 | 是 |

## 3.3 TopMarketBarData

**对象定义**：桌面端顶部全局栏数据，支持品牌、全局系统入口、主要指数条、市场状态、用户入口。  
**所属系统**：应用框架 / 乾坤行情  
**使用页面和模块**：TopMarketBar  
**数据来源**：系统配置 + TradingDay + IndexSnapshot + DataSourceStatus  
**更新频率**：指数日频/数据状态分钟级  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：指数 ticker 使用 `direction` 触发红涨绿跌。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `brandName` | string | 品牌名 | - | 是 | `财势乾坤` | 系统配置 | 日频/按源 | 是 |
| `activeSystemKey` | string | 当前一级系统 key | - | 是 | `quote` | 页面上下文 | 日频/按源 | 是 |
| `globalEntries` | GlobalSystemEntry[] | 全局系统入口 | - | 是 | `[...]` | 系统配置 | 日频/按源 | 是 |
| `indexTickers` | IndexSnapshot[] | 顶部指数条 | - | 是 | `[...]` | index_daily | 日频/按源 | 是 |
| `tradingDay` | TradingDay | 交易日状态 | - | 是 | `{...}` | TradingDay | 日频/按源 | 是 |
| `dataStatus` | DataSourceStatus[] | 关键数据状态 | - | 是 | `[...]` | 数据源监控 | 日频/按源 | 是 |
| `userShortcutStatus` | UserShortcutStatus | 用户快捷状态 | - | 否 | `{...}` | 用户服务 | 日频/按源 | 是 |

## 3.4 GlobalSystemEntry

**对象定义**：顶部全局栏中的一级系统入口，如乾坤行情、财势探查、交易助手。  
**所属系统**：应用框架  
**使用页面和模块**：TopMarketBar  
**数据来源**：系统配置  
**更新频率**：低频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不参与红涨绿跌。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `key` | string | 入口 key | - | 是 | `quote` | 系统配置 | 日频/按源 | 是 |
| `title` | string | 入口名称 | - | 是 | `乾坤行情` | 系统配置 | 日频/按源 | 是 |
| `route` | string | 入口路由 | - | 是 | `/market/overview` | 系统配置 | 日频/按源 | 是 |
| `active` | boolean | 是否当前激活 | - | 是 | `true` | 页面上下文 | 日频/按源 | 是 |
| `enabled` | boolean | 是否可用 | - | 是 | `true` | 系统配置 | 日频/按源 | 是 |

## 3.5 BreadcrumbItem

**对象定义**：面包屑对象，用于表达市场总览归属为乾坤行情下的页面。  
**所属系统**：应用框架  
**使用页面和模块**：Breadcrumb  
**数据来源**：页面路由配置  
**更新频率**：低频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不参与红涨绿跌。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `label` | string | 显示名称 | - | 是 | `乾坤行情` | 路由配置 | 日频/按源 | 是 |
| `route` | string | 可跳转路由 | - | 否 | `/market` | 路由配置 | 日频/按源 | 是 |
| `current` | boolean | 是否当前页 | - | 是 | `false` | 页面上下文 | 日频/按源 | 是 |

## 3.6 QuickEntry

**对象定义**：页面内快捷入口对象，支持进入市场温度与情绪、机会雷达、自选、持仓、提醒中心等。  
**所属系统**：应用框架 / 业务分流  
**使用页面和模块**：ShortcutBar  
**数据来源**：配置中心 + 用户状态  
**更新频率**：低频/用户态实时  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：快捷入口不得返回温度/情绪/风险/资金分数；只可返回有无更新和待处理数。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `key` | string | 入口 key | - | 是 | `market-emotion` | 配置中心 | 日频/按源 | 是 |
| `title` | string | 入口标题 | - | 是 | `市场温度与情绪` | 配置中心 | 日频/按源 | 是 |
| `description` | string | 入口说明 | - | 否 | `查看温度、情绪、风险等分析页` | 配置中心 | 日频/按源 | 是 |
| `route` | string | 前端路由 | - | 是 | `/market/emotion` | 配置中心 | 日频/按源 | 是 |
| `enabled` | boolean | 是否可用 | - | 是 | `true` | 配置中心 | 日频/按源 | 是 |
| `pendingCount` | integer | 待处理数量 | 个 | 否 | `2` | 用户服务 | 日频/按源 | 是 |
| `hasUpdate` | boolean | 是否有更新 | - | 否 | `true` | 用户服务/配置中心 | 日频/按源 | 是 |

## 3.7 UserShortcutStatus

**对象定义**：用户相关快捷状态，用于 TopMarketBar 或 ShortcutBar 展示自选、持仓、提醒数量。  
**所属系统**：用户服务 / 交易助手  
**使用页面和模块**：TopMarketBar、ShortcutBar  
**数据来源**：watchlist/position/alert 用户表  
**更新频率**：实时/分钟  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不参与红涨绿跌；数量 badge 使用中性色或提醒色。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `watchCount` | integer | 自选数量 | 只 | 否 | `18` | 自选服务 | 日频/按源 | 是 |
| `positionCount` | integer | 手工持仓数量 | 只 | 否 | `5` | 持仓服务 | 日频/按源 | 是 |
| `activeAlertCount` | integer | 启用提醒数量 | 条 | 否 | `12` | 提醒服务 | 日频/按源 | 是 |
| `unreadAlertCount` | integer | 未读提醒数量 | 条 | 否 | `2` | 提醒服务 | 日频/按源 | 是 |
| `hasPreference` | boolean | 是否已设置投资偏好 | - | 否 | `true` | 用户偏好 | 日频/按源 | 是 |

## 3.8 MarketOverview

**对象定义**：市场总览聚合对象，承载页面首屏及主要模块所需客观事实。  
**所属系统**：乾坤行情 / 首页聚合服务  
**使用页面和模块**：市场总览页面  
**数据来源**：多个业务快照视图聚合  
**更新频率**：按模块  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：对象内行情子项都必须带 direction 或可派生 direction。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `tradingDay` | TradingDay | 交易日对象 | - | 是 | `{...}` | trade_cal | 日频/按源 | 是 |
| `dataStatus` | DataSourceStatus[] | 数据源状态 | - | 是 | `[...]` | 数据源监控 | 日频/按源 | 是 |
| `topMarketBar` | TopMarketBarData | 顶部全局栏数据 | - | 是 | `{...}` | 聚合服务 | 日频/按源 | 是 |
| `breadcrumb` | BreadcrumbItem[] | 面包屑 | - | 是 | `[...]` | 路由配置 | 日频/按源 | 是 |
| `quickEntries` | QuickEntry[] | 页面内快捷入口 | - | 是 | `[...]` | 配置中心 | 日频/按源 | 是 |
| `marketSummary` | MarketObjectiveSummary | 客观摘要 | - | 是 | `{...}` | 统计快照 | 日频/按源 | 是 |
| `indices` | IndexSnapshot[] | 核心指数 | - | 是 | `[...]` | index_daily | 日频/按源 | 是 |
| `breadth` | MarketBreadth | 市场广度 | - | 是 | `{...}` | daily/limit_list_d | 日频/按源 | 是 |
| `style` | MarketStyle | 市场风格 | - | 是 | `{...}` | index_daily | 日频/按源 | 是 |
| `turnover` | TurnoverSummary | 成交额 | 按源 | 是 | `{...}` | daily | 日频/按源 | 是 |
| `moneyFlow` | MoneyFlowSummary | 大盘资金流事实 | 按源 | 否 | `{...}` | moneyflow_mkt_dc | 日频/按源 | 是 |
| `limitUp` | LimitUpSummary | 涨跌停摘要 | - | 是 | `{...}` | limit_list_d | 日频/按源 | 是 |
| `limitUpDistribution` | LimitUpDistribution[] | 涨跌停分布 | - | 是 | `[...]` | limit_list_d/daily | 日频/按源 | 是 |
| `streakLadder` | LimitUpStreakLadder | 连板天梯 | - | 是 | `{...}` | limit_list_d | 日频/按源 | 是 |
| `sectorOverview` | object | 板块概览：强势/弱势/资金流/热力图 | - | 是 | `{...}` | dc_index/dc_daily | 日频/按源 | 是 |
| `leaderboards` | object | 东方财富热榜分组 | - | 是 | `{...}` | dc_hot | 日频/按源 | 是 |

## 3.9 MarketObjectiveSummary

**对象定义**：市场客观摘要对象，只用事实句和事实项，不输出主观结论。  
**所属系统**：乾坤行情  
**使用页面和模块**：PageHeader / 首屏概览  
**数据来源**：MarketBreadth + TurnoverSummary + LimitUpSummary + SectorRankItem  
**更新频率**：按模块  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：摘要事实中的涨跌字段按 direction 渲染。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `title` | string | 摘要标题 | - | 是 | `A股市场事实概览` | 服务端模板 | 日频/按源 | 是 |
| `facts` | object[] | 客观事实项列表 | - | 是 | `[{label:"上涨家数",value:3421}]` | 统计快照 | 日频/按源 | 是 |
| `updatedAt` | datetime | 摘要更新时间 | - | 是 | `2026-04-28T17:10:00+08:00` | 聚合服务 | 日频/按源 | 是 |
| `forbiddenConclusion` | boolean | 是否禁止主观结论，固定 true | - | 是 | `true` | 系统规则 | 日频/按源 | 是 |

## 3.10 IndexSnapshot

**对象定义**：核心指数行情快照。  
**所属系统**：指数行情服务  
**使用页面和模块**：TopMarketBar、指数卡片、市场风格  
**数据来源**：raw_tushare.index_daily + 指数配置  
**更新频率**：日频/后续实时  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：`changePct` 派生 `direction`，UP 红、DOWN 绿。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `indexCode` | string | 指数代码 | - | 是 | `000001.SH` | index_daily.ts_code | 日频/按源 | 是 |
| `indexName` | string | 指数名称 | - | 是 | `上证指数` | 指数配置 | 日频/按源 | 是 |
| `tradeDate` | string(date) | 交易日 | - | 是 | `2026-04-28` | index_daily.trade_date | 日频/按源 | 是 |
| `last` | number | 最新点位/收盘点位 | 点 | 是 | `3128.42` | index_daily.close | 日频/按源 | 是 |
| `prevClose` | number | 昨收点位 | 点 | 是 | `3099.76` | index_daily.pre_close | 日频/按源 | 是 |
| `change` | number | 涨跌点位 | 点 | 是 | `28.66` | index_daily.change | 日频/按源 | 是 |
| `changePct` | number | 涨跌幅 | % | 是 | `0.92` | index_daily.pct_chg | 日频/按源 | 是 |
| `amount` | number | 成交额，保持源口径 | 千元 | 否 | `482300000` | index_daily.amount | 日频/按源 | 是 |
| `direction` | enum | 涨跌方向 | - | 是 | `UP` | changePct 派生 | 日频/按源 | 是 |

## 3.11 MarketBreadth

**对象定义**：全市场涨跌家数、红盘率、中位涨跌幅及分布。  
**所属系统**：市场统计服务  
**使用页面和模块**：涨跌分布模块、历史涨跌曲线  
**数据来源**：raw_tushare.daily + stock_basic + limit_list_d  
**更新频率**：日频/后续实时  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：上涨数量/比例用红，下跌数量/比例用绿。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `samplePool` | string | 样本池 | - | 是 | `CN_A_COMMON` | 样本池规则 | 日频/按源 | 是 |
| `stockUniverseCount` | integer | 有效样本数 | 只 | 是 | `5128` | daily 有效记录 | 日频/按源 | 是 |
| `upCount` | integer | 上涨家数 | 只 | 是 | `3421` | daily.pct_chg > 0 | 日频/按源 | 是 |
| `downCount` | integer | 下跌家数 | 只 | 是 | `1488` | daily.pct_chg < 0 | 日频/按源 | 是 |
| `flatCount` | integer | 平盘家数 | 只 | 是 | `219` | daily.pct_chg = 0 | 日频/按源 | 是 |
| `redRate` | number | 红盘率 | ratio | 是 | `0.667` | upCount / stockUniverseCount | 日频/按源 | 是 |
| `medianChangePct` | number | 中位涨跌幅 | % | 是 | `0.48` | median(daily.pct_chg) | 日频/按源 | 是 |
| `distribution` | BreadthDistributionBucket[] | 涨跌幅分布桶 | - | 是 | `[...]` | daily.pct_chg 分桶 | 日频/按源 | 是 |
| `history` | object[] | 历史上涨/下跌点 | - | 否 | `[...]` | 历史市场广度快照 | 日频/按源 | 是 |

## 3.12 BreadthDistributionBucket

**对象定义**：涨跌幅分布桶对象。  
**所属系统**：市场统计服务  
**使用页面和模块**：涨跌幅分布图  
**数据来源**：raw_tushare.daily.pct_chg 分桶  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：正区间红色、负区间绿色、平盘灰色。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `bucketKey` | string | 分桶 key | - | 是 | `GT_5` | 系统分桶 | 日频/按源 | 是 |
| `bucketName` | string | 展示名称 | - | 是 | `涨超5%` | 系统分桶 | 日频/按源 | 是 |
| `minPct` | number | 区间下界 | % | 否 | `5` | 系统分桶 | 日频/按源 | 是 |
| `maxPct` | number | 区间上界 | % | 否 | `null` | 系统分桶 | 日频/按源 | 是 |
| `count` | integer | 股票数量 | 只 | 是 | `186` | daily.pct_chg 分桶 | 日频/按源 | 是 |
| `direction` | enum | 分桶方向 | - | 是 | `UP` | 区间派生 | 日频/按源 | 是 |

## 3.13 MarketStyle

**对象定义**：市场风格事实，比较大盘/小盘、权重/题材代表指数。  
**所属系统**：市场风格服务  
**使用页面和模块**：市场风格模块  
**数据来源**：raw_tushare.index_daily + 指数配置  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：比较项涨跌幅按 direction 渲染。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `largeCapIndexCode` | string | 大盘代表指数 | - | 是 | `000300.SH` | 指数配置 | 日频/按源 | 是 |
| `smallCapIndexCode` | string | 小盘代表指数 | - | 是 | `000852.SH` | 指数配置 | 日频/按源 | 是 |
| `largeCapChangePct` | number | 大盘代表指数涨跌幅 | % | 是 | `0.72` | index_daily.pct_chg | 日频/按源 | 是 |
| `smallCapChangePct` | number | 小盘代表指数涨跌幅 | % | 是 | `1.48` | index_daily.pct_chg | 日频/按源 | 是 |
| `smallVsLargeSpreadPct` | number | 小盘相对大盘强弱差 | pct point | 是 | `0.76` | 派生 | 日频/按源 | 是 |
| `styleLeader` | enum | 领先风格 | - | 是 | `SMALL_CAP` | 派生 | 日频/按源 | 是 |

## 3.14 TurnoverSummary

**对象定义**：市场成交额概览与历史成交额序列。  
**所属系统**：成交统计服务  
**使用页面和模块**：成交额模块、历史成交额曲线  
**数据来源**：raw_tushare.daily.amount 聚合  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：变化方向可按 amountChange 正负渲染。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `totalAmount` | number | 全市场成交额，保持 daily.amount 聚合口径 | 千元 | 是 | `1052300000` | sum(daily.amount) | 日频/按源 | 是 |
| `prevTotalAmount` | number | 上一交易日成交额 | 千元 | 是 | `982100000` | 历史聚合 | 日频/按源 | 是 |
| `amountChange` | number | 较上一交易日变化额 | 千元 | 是 | `70200000` | 派生 | 日频/按源 | 是 |
| `amountChangePct` | number | 较上一交易日变化幅度 | % | 是 | `7.15` | 派生 | 日频/按源 | 是 |
| `amount20dMedian` | number | 近20日成交额中位数 | 千元 | 否 | `936000000` | 历史聚合 | 日频/按源 | 是 |
| `amountRatio20dMedian` | number | 成交额/20日中位数 | 倍 | 否 | `1.12` | 派生 | 日频/按源 | 是 |
| `history` | HistoricalTurnoverPoint[] | 历史成交额曲线 | - | 是 | `[...]` | 历史聚合 | 日频/按源 | 是 |

## 3.15 HistoricalTurnoverPoint

**对象定义**：历史成交额曲线点。  
**所属系统**：成交统计服务  
**使用页面和模块**：历史成交额曲线  
**数据来源**：raw_tushare.daily 聚合  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：变化方向可按 amountChangePct 渲染。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `tradeDate` | string(date) | 交易日 | - | 是 | `2026-04-28` | daily.trade_date | 日频/按源 | 是 |
| `totalAmount` | number | 全市场成交额 | 千元 | 是 | `1052300000` | sum(daily.amount) | 日频/按源 | 是 |
| `amountChangePct` | number | 较前日变化 | % | 否 | `7.15` | 派生 | 日频/按源 | 是 |

## 3.16 MoneyFlowSummary

**对象定义**：大盘资金流事实摘要与历史资金流曲线，不输出资金面分数。  
**所属系统**：资金流服务  
**使用页面和模块**：资金流向模块  
**数据来源**：raw_tushare.moneyflow_mkt_dc  
**更新频率**：日频/源更新  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：净流入为正可红色，净流出为负可绿色；不得输出 capitalScore。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `mainNetInflow` | number | 主力净流入 | 元 | 否 | `-8120000000` | moneyflow_mkt_dc.net_amount | 日频/按源 | 是 |
| `mainNetInflowRate` | number | 主力净流入占比 | % | 否 | `-1.12` | moneyflow_mkt_dc.net_amount_rate | 日频/按源 | 是 |
| `superLargeAmount` | number | 超大单流入金额 | 元 | 否 | `-3200000000` | moneyflow_mkt_dc.buy_elg_amount | 日频/按源 | 是 |
| `largeAmount` | number | 大单流入金额 | 元 | 否 | `-4920000000` | moneyflow_mkt_dc.buy_lg_amount | 日频/按源 | 是 |
| `mediumAmount` | number | 中单流入金额 | 元 | 否 | `2100000000` | moneyflow_mkt_dc.buy_md_amount | 日频/按源 | 是 |
| `smallAmount` | number | 小单流入金额 | 元 | 否 | `6020000000` | moneyflow_mkt_dc.buy_sm_amount | 日频/按源 | 是 |
| `history` | HistoricalMoneyFlowPoint[] | 历史资金流曲线 | - | 否 | `[...]` | moneyflow_mkt_dc | 日频/按源 | 是 |

## 3.17 HistoricalMoneyFlowPoint

**对象定义**：历史资金流曲线点。  
**所属系统**：资金流服务  
**使用页面和模块**：资金流历史曲线  
**数据来源**：raw_tushare.moneyflow_mkt_dc  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：净流入正红、负绿。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `tradeDate` | string(date) | 交易日 | - | 是 | `2026-04-28` | moneyflow_mkt_dc.trade_date | 日频/按源 | 是 |
| `mainNetInflow` | number | 主力净流入 | 元 | 是 | `-8120000000` | moneyflow_mkt_dc.net_amount | 日频/按源 | 是 |
| `mainNetInflowRate` | number | 主力净流入占比 | % | 否 | `-1.12` | moneyflow_mkt_dc.net_amount_rate | 日频/按源 | 是 |

## 3.18 LimitUpSummary

**对象定义**：涨停、跌停、炸板、封板率、最高连板等客观事实。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：涨跌停统计模块  
**数据来源**：raw_tushare.limit_list_d + stk_limit  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨停红、跌停绿、炸板使用警示色。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `limitUpCount` | integer | 涨停数 | 只 | 是 | `59` | count(limit="U") | 日频/按源 | 是 |
| `limitDownCount` | integer | 跌停数 | 只 | 是 | `8` | count(limit="D") | 日频/按源 | 是 |
| `failedLimitUpCount` | integer | 炸板数 | 只 | 是 | `27` | count(limit="Z") | 日频/按源 | 是 |
| `touchedLimitUpCount` | integer | 触板数 | 只 | 是 | `86` | 涨停数 + 炸板数 | 日频/按源 | 是 |
| `sealRate` | number | 封板率 | ratio | 是 | `0.686` | limitUpCount/touchedLimitUpCount | 日频/按源 | 是 |
| `highestStreak` | integer | 最高连板高度 | 板 | 是 | `6` | max(limit_times) | 日频/按源 | 是 |
| `dataScopeNote` | string | 口径说明 | - | 否 | `limit_list_d 不含 ST 股票统计` | 源口径 | 日频/按源 | 是 |

## 3.19 LimitUpDistribution

**对象定义**：涨跌停分布，用于结构图。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：涨跌停分布模块  
**数据来源**：limit_list_d + daily 分桶  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨停/上涨桶红色，跌停/下跌桶绿色。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `distributionType` | enum | STREAK / LIMIT_TYPE / CHANGE_RANGE / SECTOR | - | 是 | `CHANGE_RANGE` | 请求参数/服务端 | 日频/按源 | 是 |
| `bucketKey` | string | 分布桶 key | - | 是 | `LIMIT_UP` | 系统分桶 | 日频/按源 | 是 |
| `bucketName` | string | 分布桶名称 | - | 是 | `涨停` | 系统分桶 | 日频/按源 | 是 |
| `count` | integer | 数量 | 只 | 是 | `59` | 聚合 | 日频/按源 | 是 |
| `direction` | enum | 方向 | - | 是 | `UP` | 分桶派生 | 日频/按源 | 是 |
| `rate` | number | 占比 | ratio | 否 | `0.0115` | 派生 | 日频/按源 | 是 |

## 3.20 LimitUpStreakLadder

**对象定义**：连板天梯对象，按连板高度聚合。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：连板天梯模块  
**数据来源**：raw_tushare.limit_list_d  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：所有涨停股涨跌方向为 UP，红色展示。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `tradeDate` | string(date) | 交易日 | - | 是 | `2026-04-28` | limit_list_d.trade_date | 日频/按源 | 是 |
| `highestStreak` | integer | 最高连板高度 | 板 | 是 | `6` | max(limit_times) | 日频/按源 | 是 |
| `levels` | object[] | 按高度聚合的天梯层级 | - | 是 | `[...]` | limit_list_d 聚合 | 日频/按源 | 是 |
| `items` | LimitUpStreakItem[] | 连板股票明细 | - | 是 | `[...]` | limit_list_d | 日频/按源 | 是 |

## 3.21 LimitUpStreakItem

**对象定义**：连板天梯中的股票项。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：连板天梯模块  
**数据来源**：raw_tushare.limit_list_d  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨停股红色展示，开板次数/炸板警示色。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `stockCode` | string | 股票代码 | - | 是 | `002888.SZ` | limit_list_d.ts_code | 日频/按源 | 是 |
| `stockName` | string | 股票名称 | - | 是 | `示例股份` | limit_list_d.name | 日频/按源 | 是 |
| `sectorName` | string | 所属行业/板块 | - | 否 | `机器人` | limit_list_d.industry 或 dc_member | 日频/按源 | 是 |
| `streak` | integer | 连板数 | 板 | 是 | `3` | limit_list_d.limit_times | 日频/按源 | 是 |
| `firstSealTime` | string | 首次封板时间 | - | 否 | `09:42:15` | limit_list_d.first_time | 日频/按源 | 是 |
| `lastSealTime` | string | 最后封板时间 | - | 否 | `14:21:10` | limit_list_d.last_time | 日频/按源 | 是 |
| `openTimes` | integer | 开板次数 | 次 | 否 | `1` | limit_list_d.open_times | 日频/按源 | 是 |
| `sealAmount` | number | 封单金额 | 按源 | 否 | `920000000` | limit_list_d.fd_amount | 日频/按源 | 是 |

## 3.22 SectorRankItem

**对象定义**：行业/概念/地域板块榜单项。  
**所属系统**：板块行情服务  
**使用页面和模块**：板块速览、热力图、板块榜  
**数据来源**：raw_tushare.dc_index + dc_daily + dc_member；资金补充 moneyflow_ind_dc  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：板块涨跌幅和领涨股涨跌幅按 direction 渲染。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `rank` | integer | 排名 | - | 是 | `1` | 排序派生 | 日频/按源 | 是 |
| `sectorId` | string | 东方财富板块代码 | - | 是 | `BK1184.DC` | dc_index.ts_code/dc_daily.ts_code | 日频/按源 | 是 |
| `sectorName` | string | 板块名称 | - | 是 | `人形机器人` | dc_index.name | 日频/按源 | 是 |
| `sectorType` | enum | INDUSTRY / CONCEPT / REGION | - | 是 | `CONCEPT` | dc_index.idx_type | 日频/按源 | 是 |
| `level` | string | 行业层级 | - | 否 | `二级` | dc_index.level | 日频/按源 | 是 |
| `close` | number | 板块收盘点位 | 点 | 否 | `792.52` | dc_daily.close | 日频/按源 | 是 |
| `changePct` | number | 板块涨跌幅 | % | 是 | `0.87` | dc_daily.pct_change 或 dc_index.pct_change | 日频/按源 | 是 |
| `direction` | enum | 涨跌方向 | - | 是 | `UP` | changePct 派生 | 日频/按源 | 是 |
| `volume` | number | 板块成交量 | 股 | 否 | `123456789` | dc_daily.vol | 日频/按源 | 是 |
| `amount` | number | 板块成交额 | 元 | 否 | `987654321` | dc_daily.amount | 日频/按源 | 是 |
| `swing` | number | 振幅 | % | 否 | `2.31` | dc_daily.swing | 日频/按源 | 是 |
| `turnoverRate` | number | 换手率 | % | 否 | `4.08` | dc_daily.turnover_rate/dc_index.turnover_rate | 日频/按源 | 是 |
| `marketCap` | number | 总市值 | 万元 | 否 | `12345678.9` | dc_index.total_mv | 日频/按源 | 是 |
| `upCount` | integer | 上涨家数 | 只 | 否 | `32` | dc_index.up_num | 日频/按源 | 是 |
| `downCount` | integer | 下跌家数 | 只 | 否 | `62` | dc_index.down_num | 日频/按源 | 是 |
| `leadingStockCode` | string | 领涨股代码 | - | 否 | `002117.SZ` | dc_index.leading_code | 日频/按源 | 是 |
| `leadingStockName` | string | 领涨股名称 | - | 否 | `东港股份` | dc_index.leading | 日频/按源 | 是 |
| `leadingStockChangePct` | number | 领涨股涨跌幅 | % | 否 | `10.02` | dc_index.leading_pct | 日频/按源 | 是 |
| `mainNetInflow` | number | 板块主力净流入 | 元 | 否 | `3056382208` | moneyflow_ind_dc.net_amount | 日频/按源 | 是 |

## 3.23 HeatMapItem

**对象定义**：板块热力图节点对象。  
**所属系统**：板块行情服务  
**使用页面和模块**：板块热力图  
**数据来源**：raw_tushare.dc_index + dc_daily + moneyflow_ind_dc  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：颜色基于 changePct：涨红跌绿；面积基于 amount 或 marketCap。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `id` | string | 节点 ID | - | 是 | `BK1184.DC` | dc_index.ts_code | 日频/按源 | 是 |
| `parentId` | string | 父节点 ID | - | 否 | `CONCEPT` | 板块类型 | 日频/按源 | 是 |
| `name` | string | 节点名称 | - | 是 | `人形机器人` | dc_index.name | 日频/按源 | 是 |
| `type` | enum | INDUSTRY / CONCEPT / REGION | - | 是 | `CONCEPT` | dc_index.idx_type | 日频/按源 | 是 |
| `changePct` | number | 涨跌幅 | % | 是 | `0.87` | dc_daily.pct_change | 日频/按源 | 是 |
| `direction` | enum | 涨跌方向 | - | 是 | `UP` | changePct 派生 | 日频/按源 | 是 |
| `sizeValue` | number | 面积值 | 按 sizeMetric | 是 | `987654321` | dc_daily.amount 或 dc_index.total_mv | 日频/按源 | 是 |
| `sizeMetric` | enum | AMOUNT / MARKET_CAP / STOCK_COUNT | - | 是 | `AMOUNT` | 请求参数 | 日频/按源 | 是 |
| `colorMetric` | enum | CHANGE_PCT / MONEY_FLOW | - | 是 | `CHANGE_PCT` | 请求参数 | 日频/按源 | 是 |

## 3.24 StockRankItem

**对象定义**：首页榜单股票项。P0 默认使用东方财富热榜，不等同于荐股。  
**所属系统**：榜单服务  
**使用页面和模块**：榜单速览、热榜模块  
**数据来源**：raw_tushare.dc_hot  
**更新频率**：日内多次/按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：热榜项的 changePct 按 direction 渲染；rank 本身中性。

| 字段 | 类型 | 字段说明 | 单位 | 是否必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 |
|---|---|---|---|---|---|---|---|---|
| `rank` | integer | 排名/热度 | - | 是 | `1` | dc_hot.rank | 日频/按源 | 是 |
| `rankType` | enum | POPULAR / SURGE | - | 是 | `POPULAR` | hot_type 映射 | 日频/按源 | 是 |
| `market` | string | 市场类型 | - | 是 | `A股市场` | dc_hot 查询参数/data_type | 日频/按源 | 是 |
| `stockCode` | string | 股票代码 | - | 是 | `601099.SH` | dc_hot.ts_code | 日频/按源 | 是 |
| `stockName` | string | 股票名称 | - | 是 | `太平洋` | dc_hot.ts_name | 日频/按源 | 是 |
| `price` | number | 当前价 | 元 | 否 | `4.82` | dc_hot.current_price | 日频/按源 | 是 |
| `changePct` | number | 涨跌幅 | % | 否 | `3.21` | dc_hot.pct_change | 日频/按源 | 是 |
| `direction` | enum | 涨跌方向 | - | 否 | `UP` | changePct 派生 | 日频/按源 | 是 |
| `rankTime` | string | 榜单获取时间 | - | 是 | `22:30:00` | dc_hot.rank_time | 日频/按源 | 是 |
| `isLatest` | boolean | 是否最新榜单 | - | 是 | `true` | is_new 映射 | 日频/按源 | 是 |


---

## 4. 市场总览对象关系

```text
MarketOverview
├── TradingDay
├── DataSourceStatus[]
├── TopMarketBarData
│   ├── GlobalSystemEntry[]
│   ├── IndexSnapshot[]
│   └── UserShortcutStatus
├── BreadcrumbItem[]
├── QuickEntry[]
├── MarketObjectiveSummary
├── IndexSnapshot[]
├── MarketBreadth
│   └── BreadthDistributionBucket[]
├── MarketStyle
├── TurnoverSummary
│   └── HistoricalTurnoverPoint[]
├── MoneyFlowSummary
│   └── HistoricalMoneyFlowPoint[]
├── LimitUpSummary
├── LimitUpDistribution[]
├── LimitUpStreakLadder
│   └── LimitUpStreakItem[]
├── SectorRankItem[] / HeatMapItem[]
└── StockRankItem[]
```

---

## 5. P0 已具备字段

| 模块 | 已具备字段 |
|---|---|
| 交易日 | `trade_cal.cal_date`、`is_open`、`pretrade_date` |
| 指数 | `index_daily.close`、`pre_close`、`change`、`pct_chg`、`amount` |
| 市场广度 | `daily.pct_chg` 可派生上涨/下跌/平盘、中位涨跌幅、涨跌幅分布 |
| 成交额 | `daily.amount` 可聚合全市场成交额和历史成交额 |
| 大盘资金流 | `moneyflow_mkt_dc.net_amount`、`net_amount_rate`、各单型金额 |
| 涨跌停 | `limit_list_d.limit`、`open_times`、`limit_times`、`first_time`、`last_time`、`fd_amount` |
| 板块 | `dc_index`、`dc_member`、`dc_daily` 可支撑板块榜、成分、热力图 |
| 板块资金 | `moneyflow_ind_dc` 可补充资金流入榜 |
| 热榜 | `dc_hot` 可支撑首页人气榜、飙升榜 |
| UI 框架 | TopMarketBar、Breadcrumb、ShortcutBar 可由系统配置 + 用户状态支持 |

## 6. P0 暂缺字段

1. 盘中实时全市场行情快照；当前 Tushare 口径更适合日频/延迟展示。
2. 市场广度的平盘细分、停牌、新股无涨跌幅限制的完整统一样本池口径。
3. 传统涨幅榜、跌幅榜、成交额榜、换手榜的独立业务接口；本轮 P0 首页默认使用 `dc_hot`。
4. 近半年历史曲线若要求高性能，需要预聚合快照表。
5. 涨跌停“天地板/地天板”等特殊短线结构字段。
6. 板块热力图层级树和板块父子关系稳定表。

## 7. 需要数据基座补充的字段

| 能力 | 建议补充 |
|---|---|
| 样本池 | `wealth_stock_universe_snapshot`，明确 ST、停牌、新股、退市整理等过滤口径。 |
| 历史曲线 | `wealth_market_breadth_history`、`wealth_turnover_history`、`wealth_moneyflow_history`。 |
| 板块体系 | `wealth_sector_dimension`，统一 `dc_index.idx_type` 到 `INDUSTRY/CONCEPT/REGION`。 |
| 热力图 | `wealth_sector_heatmap_snapshot`，预先计算 sizeMetric 和 colorMetric。 |
| 数据状态 | `wealth_data_source_status`，记录各 raw_tushare 表最新交易日、行数、完整度。 |
| 快捷入口 | `wealth_quick_entry_config` 和用户侧状态表。 |

## 8. 待产品总控确认问题

1. 市场总览是否只展示 `dc_hot` 热榜，还是同时补传统涨跌幅榜/成交额榜作为二级 Tab？
2. 市场广度样本池是否排除 ST？建议 P0 明确一个 `CN_A_COMMON` 口径。
3. 板块红盘率是否允许用 `dc_index.up_num/down_num` 近似，还是必须通过 `dc_member + daily` 精算？
4. 近半年历史曲线是否 P0 首屏必须展示，还是模块展开后展示？
5. TopMarketBar 是否需要返回用户头像/账号信息，还是仅返回 userShortcutStatus？

---

# 附录 A：字段名词表

> 本附录用于前端表头、指标名称、Tooltip 和字段解释。字段名默认保持 Tushare / 当前 PostgreSQL 落库口径；中文展示名由财势乾坤统一定义。

## A.1 通用行情字段

| 字段名 | 统一中文名 | 字段说明 | 单位/类型 | 常见来源 |
|---|---|---|---|---|
| `ts_code` | 证券代码 | Tushare 统一证券代码，通常带交易所后缀 | string | 多数 Tushare 数据集 |
| `symbol` | 股票代码 | 不带交易所后缀的股票代码 | string | `stock_basic` |
| `name` | 名称 | 股票、指数或板块名称 | string | `stock_basic`、`dc_index`、`limit_list_d` |
| `trade_date` | 交易日期 | 数据所属交易日 | `YYYYMMDD` | 多数日频数据集 |
| `open` | 开盘价 | 当前交易日或周期的开盘价 | 元/点 | `daily`、`index_daily`、`dc_daily` |
| `high` | 最高价 | 当前交易日或周期最高价 | 元/点 | `daily`、`index_daily`、`dc_daily` |
| `low` | 最低价 | 当前交易日或周期最低价 | 元/点 | `daily`、`index_daily`、`dc_daily` |
| `close` | 收盘价 | 当前交易日或周期收盘价 | 元/点 | `daily`、`index_daily`、`dc_daily` |
| `pre_close` | 昨收价 | 上一交易日收盘价 | 元/点 | `daily`、`index_daily`、`stk_limit` |
| `change` | 涨跌额 / 涨跌点位 | 当前价格相对昨收的变化 | 元/点 | `daily`、`index_daily`、`dc_daily` |
| `pct_chg` | 涨跌幅 | 个股或指数涨跌幅 | % | `daily`、`index_daily` |
| `pct_change` | 涨跌幅 | 板块、资金流或热榜中的涨跌幅字段 | % | `dc_index`、`dc_daily`、`moneyflow_ind_dc`、`dc_hot` |
| `vol` | 成交量 | 成交量，单位按来源保持 | 手/股等 | `daily`、`index_daily`、`dc_daily` |
| `amount` | 成交额 | 成交金额，单位按来源保持 | 千元/元等 | `daily`、`index_daily`、`dc_daily` |

## A.2 交易日历字段

| 字段名 | 统一中文名 | 字段说明 | 单位/类型 | 常见来源 |
|---|---|---|---|---|
| `exchange` | 交易所 | 交易所代码 | string | `trade_cal`、`stock_basic` |
| `cal_date` | 日历日期 | 自然日期 | `YYYYMMDD` | `trade_cal` |
| `is_open` | 是否开市 | 当前落库已改为 boolean | boolean | `trade_cal` |
| `pretrade_date` | 上一交易日 | 当前日期对应的上一交易日 | `YYYYMMDD` | `trade_cal` |

## A.3 每日指标字段

| 字段名 | 统一中文名 | 字段说明 | 单位/类型 | 常见来源 |
|---|---|---|---|---|
| `turnover_rate` | 换手率 | 成交量相对流通股本的比例 | % | `daily_basic`、`dc_index`、`dc_daily` |
| `turnover_rate_f` | 自由流通换手率 | 成交量相对自由流通股本的比例 | % | `daily_basic` |
| `volume_ratio` | 量比 | 当前成交量相对近期平均成交量的比值 | 倍 | `daily_basic` |
| `pe` | 市盈率 | 静态市盈率 | 倍 | `daily_basic` |
| `pe_ttm` | 市盈率 TTM | 滚动市盈率 | 倍 | `daily_basic` |
| `pb` | 市净率 | 市值相对净资产的比值 | 倍 | `daily_basic` |
| `total_mv` | 总市值 | 总市值，单位按来源保持 | 万元 | `daily_basic`、`dc_index` |
| `circ_mv` | 流通市值 | 流通市值 | 万元 | `daily_basic` |
| `total_share` | 总股本 | 公司总股本 | 万股 | `daily_basic` |
| `float_share` | 流通股本 | 流通股本 | 万股 | `daily_basic` |
| `free_share` | 自由流通股本 | 自由流通股本 | 万股 | `daily_basic` |

## A.4 东方财富板块字段

| 字段名 | 统一中文名 | 字段说明 | 单位/类型 | 常见来源 |
|---|---|---|---|---|
| `idx_type` | 板块类型 | 行业板块、概念板块、地域板块 | string | `dc_index`、`dc_daily` 查询条件 |
| `level` | 行业层级 | 行业层级字段 | string | `dc_index` |
| `leading` | 领涨股票名称 | 板块当日领涨股票名称 | string | `dc_index` |
| `leading_code` | 领涨股票代码 | 板块当日领涨股票代码 | string | `dc_index` |
| `leading_pct` | 领涨股票涨跌幅 | 领涨股票当日涨跌幅 | % | `dc_index` |
| `up_num` | 上涨家数 | 板块内上涨股票数量 | 只 | `dc_index` |
| `down_num` | 下跌家数 | 板块内下跌股票数量 | 只 | `dc_index` |
| `con_code` | 成分股代码 | 东方财富板块成分股代码 | string | `dc_member` |
| `swing` | 振幅 | 板块日线振幅 | % | `dc_daily` |
| `current_price` | 当前价 | 热榜中的当前价格 | 元 | `dc_hot` |
| `rank_time` | 榜单时间 | 热榜采集或更新时间 | string | `dc_hot` |
| `data_type` | 数据类型 | 热榜所属市场或类型 | string | `dc_hot` |
| `rank` | 排名 | 热榜或资金榜排名 | integer | `dc_hot`、`moneyflow_ind_dc` |

## A.5 涨跌停与资金流字段

| 字段名 | 统一中文名 | 字段说明 | 单位/类型 | 常见来源 |
|---|---|---|---|---|
| `up_limit` | 涨停价 | 当日涨停价格 | 元 | `stk_limit` |
| `down_limit` | 跌停价 | 当日跌停价格 | 元 | `stk_limit` |
| `limit` | 涨跌停状态 | U 涨停、D 跌停、Z 炸板等，按源文档解释 | enum/string | `limit_list_d` |
| `fd_amount` | 封单金额 | 封板时封单金额 | 按源口径 | `limit_list_d` |
| `first_time` | 首次封板时间 | 当日首次封板时间 | string | `limit_list_d` |
| `last_time` | 最后封板时间 | 当日最后封板时间 | string | `limit_list_d` |
| `open_times` | 开板次数 | 当日开板次数 | 次 | `limit_list_d` |
| `up_stat` | 涨停统计 | 源接口提供的涨停统计字符串 | string | `limit_list_d` |
| `limit_times` | 连板数 | 当前连续涨停板数量 | 板 | `limit_list_d` |
| `net_amount` | 主力净流入 | 主力资金净流入金额，单位按来源保持 | 元/万元 | `moneyflow_mkt_dc`、`moneyflow_ind_dc`、`moneyflow_dc` |
| `net_amount_rate` | 主力净流入占比 | 主力净流入金额占比 | % | 资金流数据集 |
| `buy_elg_amount` | 超大单流入金额 | 超大单主动买入金额 | 按源口径 | 资金流数据集 |
| `buy_lg_amount` | 大单流入金额 | 大单主动买入金额 | 按源口径 | 资金流数据集 |
| `buy_md_amount` | 中单流入金额 | 中单主动买入金额 | 按源口径 | 资金流数据集 |
| `buy_sm_amount` | 小单流入金额 | 小单主动买入金额 | 按源口径 | 资金流数据集 |

## A.6 财势乾坤派生字段

| 字段名 | 统一中文名 | 字段说明 | 单位/类型 | 常见对象 |
|---|---|---|---|---|
| `direction` | 涨跌方向 | `UP` 上涨、`DOWN` 下跌、`FLAT` 平盘、`UNKNOWN` 未知 | enum | 所有行情对象 |
| `redRate` | 红盘率 | 上涨家数 / 有效样本数 | ratio | `MarketBreadth`、`SectorRankItem` |
| `medianChangePct` | 中位涨跌幅 | 有效样本涨跌幅中位数 | % | `MarketBreadth` |
| `sealRate` | 封板率 | 涨停数 / 触及涨停数 | ratio | `LimitUpSummary` |
| `failedLimitUpCount` | 炸板数 | 触及涨停但未封住的数量 | 只 | `LimitUpSummary` |
| `touchedLimitUpCount` | 触板数 | 涨停数 + 炸板数 | 只 | `LimitUpSummary` |
| `highestStreak` | 最高连板高度 | 当日最高连续涨停板数量 | 板 | `LimitUpSummary` |
| `amountRatio20dMedian` | 成交额相对 20 日中位倍数 | 当日成交额 / 近 20 日中位成交额 | 倍 | `TurnoverSummary` |
| `dataStatus` | 数据状态 | READY / PARTIAL / DELAYED / UNAVAILABLE | enum | 通用 |
| `asOf` | 数据时间 | 当前对象的数据更新时间或同步时间 | datetime | 通用 |
| `sourceRefs` | 数据来源引用 | 标识数据来自哪些数据集和表 | array | API 响应对象 |

