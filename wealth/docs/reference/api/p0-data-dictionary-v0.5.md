# 财势乾坤｜P0 数据字典 v0.5

> 历史参考声明：本文是 Drive 原始数据字典快照，字段对象、聚合结构和模块接口映射可能与当前工程化三件套不一致。当前实现不得直接沿用本文旧接口映射；字段来源、字段命名、状态语义和测试门禁以 `wealth/docs/pages/market-overview/**` 模块三件套与 `api-contract-baseline.md` 为准。

建议保存路径：`/docs/wealth/api/p0-data-dictionary.md`  
负责人：`04_API 契约与数据字典`  
版本：`v0.5`  
状态：`历史参考，不作为实现契约`
更新时间：`2026-05-10`

---

## 0. 历史审计结论（已废弃）

本版基于《项目总说明 v0.2》《市场总览 PRD v0.2》以及既有 API/数据字典成果，重新收敛到“市场总览”开发落地所需范围。

### 0.1 产品边界

1. 首期先做 Web，先专注 A 股。
2. 市场总览属于 **乾坤行情**，不是独立一级菜单。
3. 市场总览是 **A 股市场客观事实总览页**。
4. 桌面端不使用固定 SideNav；API 需要支持 `TopMarketBar`、`Breadcrumb`、`ShortcutBar`。
5. 市场总览不展示市场温度、市场情绪指数、资金面分数、风险指数作为核心结论。
6. 市场温度、市场情绪、资金面分数、风险指数属于“市场温度与情绪分析页”。
7. 所有行情字段必须支持中国 A 股 **红涨绿跌**。
8. Tushare 只作为已落库数据基座和字段口径参考；财势乾坤 API 使用业务对象和业务字段组织，不复刻 Tushare API。

### 0.2 禁止作为市场总览核心字段返回

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

快捷入口可以返回入口名称、入口描述、route、是否可用、待处理数量、是否有更新，但不得返回市场温度、情绪指数、资金面分数、风险指数的具体数值。

---

## 1. 字段命名、单位与显示规则

| 项目 | 规则 |
|---|---|
| API 字段命名 | `lowerCamelCase`，使用财势乾坤业务命名 |
| 源字段名 | 在数据字典和附录中记录 Tushare / PostgreSQL 落库字段名 |
| 日期 | API 返回 `YYYY-MM-DD`；源字段可为 `YYYYMMDD` |
| 时间 | API 返回 `HH:mm` 或 ISO 8601，按字段说明标注 |
| 金额单位 | 默认保持 Tushare / PostgreSQL 落库口径；字段表必须写明单位 |
| 成交量单位 | 默认保持 Tushare / PostgreSQL 落库口径；字段表必须写明单位 |
| 涨跌幅 | 百分数数值，例如 `1.23` 表示 `1.23%` |
| 比率 | `rate` 默认 0-1 小数；`Pct` 默认百分数数值 |
| direction | `UP` / `DOWN` / `FLAT` / `UNKNOWN` |

### 1.1 红涨绿跌规则

| 数据含义 | 方向字段 | 显示颜色 |
|---|---|---|
| 上涨、涨幅、涨停、净流入正值 | `UP` 或 value > 0 | 红色 |
| 下跌、跌幅、跌停、净流出负值 | `DOWN` 或 value < 0 | 绿色 |
| 平盘、零值、无变化 | `FLAT` 或 value = 0 | 灰色 |
| 不适用 / 未知 | `UNKNOWN` | 中性灰 |

---

## 2. Tushare / PostgreSQL 落库数据集参考

| 业务域 | 主数据集 / 落库表 | 关键字段 | 用途 |
|---|---|---|---|
| 交易日 | `trade_cal` / `raw_tushare.trade_cal` | `cal_date`、`is_open`、`pretrade_date` | 交易日状态；`is_open` 已落库为 boolean |
| 股票基础 | `stock_basic` / `raw_tushare.stock_basic` | `ts_code`、`name`、`industry`、`market`、`exchange` | 股票名称、行业、交易所 |
| 个股日线 | `daily` / `raw_tushare.daily` | `close`、`pct_chg`、`vol`、`amount` | 市场广度、成交额、榜单扩展字段 |
| 每日指标 | `daily_basic` / `raw_tushare.daily_basic` | `turnover_rate`、`volume_ratio`、`total_mv`、`circ_mv` | 换手率、量比、市值 |
| 指数日线 | `index_daily` / `raw_tushare.index_daily` | `close`、`change`、`pct_chg`、`amount` | 主要指数、TopMarketBar |
| 大盘资金流 | `moneyflow_mkt_dc` / `raw_tushare.moneyflow_mkt_dc` | `net_amount`、`buy_elg_amount`、`buy_lg_amount`、`buy_md_amount`、`buy_sm_amount` | 大盘资金流事实 |
| 涨跌停 / 炸板 | `limit_list_d` / `raw_tushare.limit_list_d` | `limit`、`open_times`、`limit_times`、`first_time`、`fd_amount` | 涨停、跌停、炸板、连板天梯 |
| 涨跌停价格 | `stk_limit` / `raw_tushare.stk_limit` | `up_limit`、`down_limit` | 涨跌停状态辅助校验 |
| 东方财富板块列表 | `dc_index` / `raw_tushare.dc_index` | `ts_code`、`name`、`pct_change`、`up_num`、`down_num`、`idx_type`、`leading` | 行业/概念/地域板块 |
| 东方财富板块成分 | `dc_member` / `raw_tushare.dc_member` | `ts_code`、`con_code`、`name` | 板块下钻、板块涨跌分布 |
| 东方财富板块日线 | `dc_daily` / `raw_tushare.dc_daily` | `pct_change`、`amount`、`turnover_rate` | 板块行情、热力图 |
| 东方财富板块资金流 | `moneyflow_ind_dc` / `raw_tushare.moneyflow_ind_dc` | `net_amount`、`rank` | 板块资金流 |
| 东方财富热榜 | `dc_hot` / `raw_tushare.dc_hot` | `rank`、`ts_code`、`ts_name`、`pct_change`、`current_price`、`rank_time` | 榜单速览 |

---

## 3. 市场总览 P0 对象字典

## 3.1 TradingDay

**对象定义**：A 股交易日与交易阶段对象，用于确定市场总览展示数据所属交易日、上一交易日和交易状态。  
**所属系统**：乾坤行情 / 交易日历服务  
**使用页面和模块**：TopMarketBar、PageHeader、全部市场总览模块  
**数据来源**：raw_tushare.trade_cal；其中 is_open 已在落库时改为 boolean  
**更新频率**：交易日历日频；sessionStatus 由服务端按当前时间分钟级派生  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不直接参与红涨绿跌，但影响数据日期、交易状态和延迟提示。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradeDate` | `string(date)` | 当前交易日 | - | 是 | 2026-04-28 | trade_cal.cal_date | 日频 | 是 | 无 |
| `prevTradeDate` | `string(date)` | 上一交易日 | - | 是 | 2026-04-27 | trade_cal.pretrade_date | 日频 | 是 | 无 |
| `market` | `enum` | 市场，P0 固定 CN_A | - | 是 | CN_A | 系统配置 | 固定 | 是 | 无 |
| `exchangeCalendar` | `string` | 使用的交易所日历 | - | 否 | SSE | trade_cal.exchange | 日频 | 是 | 无 |
| `isTradingDay` | `boolean` | 是否交易日；当前落库已从 0/1 改为 boolean | - | 是 | true | trade_cal.is_open | 日频 | 是 | 无 |
| `sessionStatus` | `enum` | PRE_OPEN / OPEN / NOON_BREAK / CLOSED / HOLIDAY | - | 是 | CLOSED | 服务端时间派生 | 分钟级 | 是 | 无 |
| `timezone` | `string` | 交易时区 | - | 是 | Asia/Shanghai | 系统配置 | 固定 | 是 | 无 |

## 3.2 DataSourceStatus

**对象定义**：数据源和数据集状态对象，用于市场总览显示数据新鲜度、延迟、缺失和降级信息。  
**所属系统**：数据中心 / 数据源监控服务  
**使用页面和模块**：TopMarketBar、PageHeader、DataStatusBadge、模块 Tooltip  
**数据来源**：数据同步任务、质量校验任务、raw_tushare 各表 max(trade_date)  
**更新频率**：任务完成或分钟级刷新  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：使用状态色，不使用行情红绿，避免与涨跌方向混淆。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `sourceId` | `string` | 数据源 ID | - | 是 | tushare_daily | 数据源配置 | 低频 | 是 | 无 |
| `sourceName` | `string` | 数据源名称 | - | 是 | Tushare A股日线 | 配置 | 低频 | 是 | 无 |
| `dataset` | `string` | 数据集/API 名称 | - | 是 | daily | 同步任务 | 任务级 | 是 | 无 |
| `tableName` | `string` | 落库表名 | - | 是 | raw_tushare.daily | 数据基座 | 低频 | 是 | 无 |
| `dataDomain` | `enum` | QUOTE / INDEX / BREADTH / TURNOVER / MONEY_FLOW / LIMIT_UP / SECTOR / LEADERBOARD / SETTINGS | - | 是 | QUOTE | 配置 | 低频 | 是 | 无 |
| `status` | `enum` | READY / DELAYED / PARTIAL / EMPTY / ERROR / NO_PERMISSION | - | 是 | READY | 监控服务 | 分钟/任务 | 是 | 状态色 |
| `latestTradeDate` | `string(date)` | 最新交易日 | - | 否 | 2026-04-28 | max(trade_date) | 任务级 | 是 | 无 |
| `latestDataTime` | `datetime` | 最新同步时间 | - | 否 | 2026-04-28T17:10:00+08:00 | 同步任务 | 任务级 | 是 | 无 |
| `completenessPct` | `number` | 数据完整度 | % | 否 | 99.6 | 质量校验 | 任务级 | 是 | 无 |
| `message` | `string` | 状态说明 | - | 否 | 资金流数据为盘后更新 | 监控服务 | 分钟级 | 是 | 无 |

## 3.3 TopMarketBarData

**对象定义**：顶部全局栏数据对象，包含品牌、一级系统入口、顶部指数条、交易状态、用户快捷状态。  
**所属系统**：全局框架 / 乾坤行情  
**使用页面和模块**：TopMarketBar、GlobalSystemMenu、IndexTickerStrip、UserStatusArea  
**数据来源**：系统配置、IndexSnapshot、TradingDay、DataSourceStatus、用户服务  
**更新频率**：入口配置低频；指数与数据状态按源刷新  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：indexTickers 中的指数按 direction 红涨绿跌；系统入口不使用行情红绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `brandName` | `string` | 产品名称 | - | 是 | 财势乾坤 | 系统配置 | 低频 | 是 | 无 |
| `activeSystemKey` | `string` | 当前一级系统 key | - | 是 | quote | 页面上下文 | 路由级 | 是 | 无 |
| `globalEntries` | `GlobalSystemEntry[]` | 一级系统入口 | - | 是 | [...] | 系统配置 | 低频 | 是 | 无 |
| `indexTickers` | `IndexSnapshot[]` | 顶部指数条 | - | 是 | [...] | index_daily / 指数快照 | 按源 | 是 | 必须 |
| `tradingDay` | `TradingDay` | 交易日状态 | - | 是 | {...} | trade_cal | 日频/分钟 | 是 | 无 |
| `dataStatus` | `DataSourceStatus[]` | 关键数据状态 | - | 是 | [...] | 监控服务 | 分钟/任务 | 是 | 状态色 |
| `userShortcutStatus` | `UserShortcutStatus` | 用户快捷状态 | - | 否 | {watchCount:18} | 用户服务 | 缓存/实时 | 是 | 无 |

## 3.4 GlobalSystemEntry

**对象定义**：顶部一级系统入口，用于表达乾坤行情、财势探查、交易助手等系统导航状态。  
**所属系统**：全局导航  
**使用页面和模块**：TopMarketBar / GlobalSystemMenu  
**数据来源**：路由配置、权限配置  
**更新频率**：低频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不参与红涨绿跌。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `key` | `string` | 入口 key | - | 是 | quote | 系统配置 | 低频 | 是 | 无 |
| `title` | `string` | 入口名称 | - | 是 | 乾坤行情 | 系统配置 | 低频 | 是 | 无 |
| `route` | `string` | 入口路由 | - | 是 | /market/overview | 路由配置 | 低频 | 是 | 无 |
| `active` | `boolean` | 是否当前激活 | - | 是 | true | 页面上下文 | 路由级 | 是 | 无 |
| `enabled` | `boolean` | 是否可用 | - | 是 | true | 权限/配置 | 低频 | 是 | 无 |
| `sortOrder` | `integer` | 排序 | - | 否 | 10 | 配置 | 低频 | 是 | 无 |

## 3.5 BreadcrumbItem

**对象定义**：面包屑项，用于表达“财势乾坤 / 乾坤行情 / 市场总览”的页面层级。  
**所属系统**：页面框架  
**使用页面和模块**：Breadcrumb  
**数据来源**：路由配置、页面上下文  
**更新频率**：路由级  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不参与红涨绿跌。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `label` | `string` | 显示名称 | - | 是 | 乾坤行情 | 路由配置 | 路由级 | 是 | 无 |
| `route` | `string` | 跳转路由 | - | 否 | /market | 路由配置 | 路由级 | 是 | 无 |
| `current` | `boolean` | 是否当前页 | - | 是 | false | 页面上下文 | 路由级 | 是 | 无 |
| `disabled` | `boolean` | 是否禁用点击 | - | 否 | false | 页面上下文 | 路由级 | 否 | 无 |

## 3.6 QuickEntry

**对象定义**：市场总览页面内快捷入口，用于进入市场温度与情绪、机会雷达、自选、持仓、提醒、设置等页面。  
**所属系统**：页面框架 / 快捷入口配置  
**使用页面和模块**：ShortcutBar / QuickEntryCard  
**数据来源**：系统配置、用户服务、权限服务  
**更新频率**：配置低频；状态缓存/实时  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不展示市场温度、情绪、资金面、风险分数，不使用行情红绿表达入口状态。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `key` | `string` | 入口 key | - | 是 | market-emotion | 配置 | 低频 | 是 | 无 |
| `title` | `string` | 入口名称 | - | 是 | 市场温度与情绪 | 配置 | 低频 | 是 | 无 |
| `description` | `string` | 入口描述 | - | 是 | 进入分析页查看温度、情绪、资金与风险 | 配置 | 低频 | 是 | 无 |
| `route` | `string` | 入口路由 | - | 是 | /market/emotion | 路由配置 | 低频 | 是 | 无 |
| `enabled` | `boolean` | 是否可用 | - | 是 | true | 权限/配置 | 低频 | 是 | 无 |
| `pendingCount` | `integer` | 待处理数量 | 个 | 否 | 2 | 用户服务 | 缓存/实时 | 是 | 无 |
| `hasUpdate` | `boolean` | 是否有更新 | - | 否 | true | 用户服务 | 缓存/实时 | 是 | 无 |
| `sortOrder` | `integer` | 排序 | - | 否 | 10 | 配置 | 低频 | 否 | 无 |

## 3.7 UserShortcutStatus

**对象定义**：用户快捷状态对象，用于展示自选、持仓、提醒等数量和更新状态。  
**所属系统**：用户服务 / 交易助手  
**使用页面和模块**：TopMarketBar、ShortcutBar  
**数据来源**：自选服务、持仓服务、提醒服务、用户偏好  
**更新频率**：缓存/实时  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不参与行情红绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `watchCount` | `integer` | 自选数量 | 只 | 否 | 18 | 自选服务 | 缓存/实时 | 是 | 无 |
| `positionCount` | `integer` | 手工持仓数量 | 只 | 否 | 5 | 持仓服务 | 缓存/实时 | 是 | 无 |
| `activeAlertCount` | `integer` | 启用提醒数量 | 条 | 否 | 12 | 提醒服务 | 缓存/实时 | 是 | 无 |
| `unreadAlertCount` | `integer` | 未读提醒数量 | 条 | 否 | 2 | 提醒服务 | 缓存/实时 | 是 | 无 |
| `hasPreference` | `boolean` | 是否已设置投资偏好 | - | 否 | true | 用户偏好 | 缓存 | 否 | 无 |

## 3.8 MarketOverview

**对象定义**：市场总览聚合根对象，承载首屏和主要模块所需客观市场事实。  
**所属系统**：乾坤行情 / 市场总览聚合服务  
**使用页面和模块**：市场总览整页  
**数据来源**：聚合 TradingDay、IndexSnapshot、MarketBreadth、TurnoverSummary、MoneyFlowSummary、LimitUpSummary、SectorRankItem、StockRankItem 等对象  
**更新频率**：聚合接口盘中 15-60 秒；盘后缓存 1 天  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：透传各行情对象 direction 和正负值，前端按红涨绿跌展示。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradingDay` | `TradingDay` | 交易日状态 | - | 是 | {...} | trade_cal | 日频/分钟 | 是 | 无 |
| `dataStatus` | `DataSourceStatus[]` | 数据源状态 | - | 是 | [...] | 监控服务 | 分钟/任务 | 是 | 状态色 |
| `topMarketBar` | `TopMarketBarData` | 顶部栏 | - | 是 | {...} | 聚合服务 | 混合 | 是 | 指数红绿 |
| `breadcrumb` | `BreadcrumbItem[]` | 面包屑 | - | 是 | [...] | 路由配置 | 路由级 | 是 | 无 |
| `quickEntries` | `QuickEntry[]` | 快捷入口 | - | 是 | [...] | 配置/用户服务 | 缓存/低频 | 是 | 无 |
| `marketSummary` | `MarketObjectiveSummary` | 今日市场客观总结 | - | 是 | {...} | 聚合服务 | 按源 | 是 | 按事实项 |
| `indices` | `IndexSnapshot[]` | 主要指数 | - | 是 | [...] | index_daily | 按源 | 是 | 必须 |
| `breadth` | `MarketBreadth` | 涨跌分布 | - | 是 | {...} | daily 聚合 | 按源 | 是 | 必须 |
| `style` | `MarketStyle` | 市场风格 | - | 是 | {...} | index_daily / 聚合 | 按源 | 是 | 必须 |
| `turnover` | `TurnoverSummary` | 成交额总览 | 按源 | 是 | {...} | daily / 聚合 | 按源 | 是 | 变化正负 |
| `moneyFlow` | `MoneyFlowSummary` | 大盘资金流 | 元 | 是 | {...} | moneyflow_mkt_dc | 按源 | 是 | 正红负绿 |
| `limitUp` | `LimitUpSummary` | 涨跌停统计 | - | 是 | {...} | limit_list_d | 按源 | 是 | 涨停红跌停绿 |
| `limitUpDistribution` | `LimitUpDistribution` | 涨跌停分布结构 | - | 是 | {...} | limit_list_d + 板块映射 | 按源 | 是 | 涨停红跌停绿 |
| `streakLadder` | `LimitUpStreakLadder` | 连板天梯 | - | 是 | {...} | limit_list_d | 按源 | 是 | 股票涨跌红绿 |
| `sectorOverview` | `object` | 板块速览分组 | - | 是 | {...} | dc_index/dc_daily/moneyflow_ind_dc | 按源 | 是 | 板块涨跌红绿 |
| `leaderboards` | `object` | 榜单速览 | - | 是 | {top10:[...]} | dc_hot/daily/daily_basic | 按源 | 是 | 股票涨跌红绿 |

## 3.9 MarketObjectiveSummary

**对象定义**：今日市场客观总结对象，只陈列事实，不输出主观判断。  
**所属系统**：乾坤行情 / 聚合服务  
**使用页面和模块**：今日市场客观总结  
**数据来源**：MarketBreadth、TurnoverSummary、MoneyFlowSummary、LimitUpSummary 聚合  
**更新频率**：随聚合接口刷新  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：事实项可按 direction 或正负值显示红绿；说明文本中性色。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `title` | `string` | 模块标题 | - | 是 | A股市场事实概览 | 配置 | 低频 | 是 | 无 |
| `facts` | `object[]` | 事实项列表 | - | 是 | [...] | 聚合服务 | 按源 | 是 | 按事实项 |
| `cards` | `object[]` | 事实卡片，可与 facts 等价 | - | 否 | [...] | 聚合服务 | 按源 | 是 | 按事实项 |
| `textCard` | `object` | 说明性文字卡片，不给投资结论 | - | 否 | {...} | 配置/聚合 | 低频 | 是 | 中性 |
| `asOf` | `datetime` | 数据时间 | - | 是 | 2026-04-28T15:10:00+08:00 | 聚合服务 | 按源 | 是 | 无 |
| `forbiddenConclusion` | `boolean` | 是否禁止主观结论 | - | 是 | true | 固定 | 固定 | 是 | 无 |

## 3.10 IndexSnapshot

**对象定义**：指数行情快照，用于 TopMarketBar 指数条和主要指数区域。  
**所属系统**：指数行情服务  
**使用页面和模块**：TopMarketBar、主要指数  
**数据来源**：raw_tushare.index_daily；指数名称来自指数配置/index_basic  
**更新频率**：日频/按源；实时源接入后 15-60 秒  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：last、change、changePct 按 direction 红涨绿跌。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `indexCode` | `string` | 指数代码 | - | 是 | 000001.SH | index_daily.ts_code | 按源 | 是 | 无 |
| `indexName` | `string` | 指数名称 | - | 是 | 上证指数 | 指数配置 | 低频 | 是 | 无 |
| `last` | `number` | 最新/收盘点位 | 点 | 是 | 3128.42 | index_daily.close | 按源 | 是 | 按 direction |
| `prevClose` | `number` | 昨收点位 | 点 | 是 | 3099.76 | index_daily.pre_close | 按源 | 是 | 无 |
| `change` | `number` | 涨跌点 | 点 | 是 | 28.66 | index_daily.change | 按源 | 是 | 正红负绿 |
| `changePct` | `number` | 涨跌幅 | % | 是 | 0.92 | index_daily.pct_chg | 按源 | 是 | 正红负绿 |
| `amount` | `number` | 成交额 | index_daily.amount 源口径 | 否 | 482300000 | index_daily.amount | 按源 | 是 | 中性 |
| `direction` | `enum` | 涨跌方向 | - | 是 | UP | changePct 派生 | 按源 | 是 | 必须 |
| `asOf` | `datetime` | 数据时间 | - | 否 | 2026-04-28T15:10:00+08:00 | 数据基座 | 按源 | 是 | 无 |

## 3.11 MarketBreadth

**对象定义**：市场广度对象，表达当日上涨、下跌、平盘家数和涨跌幅分布。  
**所属系统**：市场广度统计服务  
**使用页面和模块**：涨跌分布  
**数据来源**：raw_tushare.daily 按有效样本池聚合；limit_list_d 辅助涨跌停  
**更新频率**：日频/按源；实时源接入后 15-60 秒  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：上涨家数红、下跌家数绿、平盘灰；涨跌幅桶按 direction。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `samplePool` | `string` | 样本池 | - | 是 | CN_A_COMMON | 样本池配置 | 日频 | 是 | 无 |
| `totalCount` | `integer` | 样本总数 | 只 | 是 | 5128 | daily 有效记录 | 按源 | 是 | 无 |
| `riseCount` | `integer` | 上涨家数 | 只 | 是 | 3421 | daily.pct_chg > 0 | 按源 | 是 | 红 |
| `fallCount` | `integer` | 下跌家数 | 只 | 是 | 1488 | daily.pct_chg < 0 | 按源 | 是 | 绿 |
| `flatCount` | `integer` | 平盘家数 | 只 | 是 | 219 | daily.pct_chg = 0 | 按源 | 是 | 灰 |
| `redRate` | `number` | 红盘率 | ratio | 否 | 0.667 | riseCount / totalCount | 按源 | 是 | 红 |
| `medianChangePct` | `number` | 中位涨跌幅 | % | 是 | 0.48 | median(daily.pct_chg) | 按源 | 是 | 正红负绿 |
| `distribution` | `BreadthDistributionBucket[]` | 涨跌幅分布桶 | - | 是 | [...] | daily.pct_chg 分桶 | 按源 | 是 | 按桶方向 |

## 3.12 BreadthDistributionBucket

**对象定义**：涨跌幅区间分布桶，用于展示当日涨跌幅结构。  
**所属系统**：市场广度统计服务  
**使用页面和模块**：涨跌分布 / DistributionChart  
**数据来源**：daily.pct_chg 分桶聚合  
**更新频率**：日频/按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨幅桶红、跌幅桶绿、平盘桶灰。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `bucketKey` | `string` | 桶 key | - | 是 | GT_5 | 服务端规则 | 低频 | 是 | 按 direction |
| `bucketName` | `string` | 桶名称 | - | 是 | 涨超5% | 服务端规则 | 低频 | 是 | 按 direction |
| `minPct` | `number` | 下限 | % | 否 | 5 | 服务端规则 | 低频 | 是 | 无 |
| `maxPct` | `number` | 上限 | % | 否 | null | 服务端规则 | 低频 | 是 | 无 |
| `count` | `integer` | 数量 | 只 | 是 | 186 | daily.pct_chg | 按源 | 是 | 按 direction |
| `direction` | `enum` | 桶方向 | - | 是 | UP | 服务端规则 | 低频 | 是 | 必须 |

## 3.13 MarketStyle

**对象定义**：市场风格对象，用于表达大盘、小盘、涨跌中位数等客观风格事实。  
**所属系统**：市场风格统计服务  
**使用页面和模块**：市场风格  
**数据来源**：index_daily 中大盘/小盘代表指数；medianChangePct 来自 MarketBreadth  
**更新频率**：日频/按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：各涨跌幅正红负绿；styleLeader 使用中性标签。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `largeCapIndexCode` | `string` | 大盘代表指数 | - | 是 | 000300.SH | 指数配置 | 低频 | 是 | 无 |
| `smallCapIndexCode` | `string` | 小盘代表指数 | - | 是 | 000852.SH | 指数配置 | 低频 | 是 | 无 |
| `largeCapChangePct` | `number` | 大盘涨跌幅 | % | 是 | 0.72 | index_daily.pct_chg | 按源 | 是 | 正红负绿 |
| `smallCapChangePct` | `number` | 小盘涨跌幅 | % | 是 | 1.48 | index_daily.pct_chg | 按源 | 是 | 正红负绿 |
| `medianChangePct` | `number` | 全市场中位涨跌幅 | % | 是 | 0.48 | MarketBreadth | 按源 | 是 | 正红负绿 |
| `smallVsLargeSpreadPct` | `number` | 小盘相对大盘强弱差 | pct point | 否 | 0.76 | 派生 | 按源 | 是 | 正红负绿 |
| `styleLeader` | `enum` | LARGE_CAP / SMALL_CAP / BALANCED | - | 是 | SMALL_CAP | 派生 | 按源 | 是 | 中性 |

## 3.14 TurnoverSummary

**对象定义**：成交额总览对象，表达今日成交额、上一交易日成交额、变化幅度和历史成交额。  
**所属系统**：成交统计服务  
**使用页面和模块**：成交额总览  
**数据来源**：daily.amount 全市场聚合；日内累计成交额需要分钟/实时聚合视图  
**更新频率**：日频/按源；日内数据 1-5 分钟  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：turnoverChangeAmount、turnoverChangePct 正红负绿；成交额本身中性。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `todayTurnoverAmount` | `number` | 今日成交总额 | daily.amount 源聚合口径 | 是 | 10523.0 | sum(daily.amount) | 按源 | 是 | 中性 |
| `previousTradeDate` | `string(date)` | 上一交易日 | - | 是 | 2026-04-27 | trade_cal | 日频 | 是 | 无 |
| `previousTurnoverAmount` | `number` | 上一交易日成交总额 | daily.amount 源聚合口径 | 是 | 9821.0 | 历史聚合 | 日频 | 是 | 中性 |
| `turnoverChangeAmount` | `number` | 较上一交易日变化额 | 源口径 | 是 | 702.0 | 派生 | 按源 | 是 | 正红负绿 |
| `turnoverChangePct` | `number` | 较上一交易日变化幅度 | % | 是 | 7.15 | 派生 | 按源 | 是 | 正红负绿 |
| `ma5TurnoverAmount` | `number` | 5日均成交额 | 源口径 | 否 | 10012.0 | 历史聚合 | 日频 | 是 | 中性 |
| `ma20TurnoverAmount` | `number` | 20日均成交额 | 源口径 | 否 | 9360.0 | 历史聚合 | 日频 | 是 | 中性 |
| `historyPoints` | `HistoricalTurnoverPoint[]` | 历史成交额趋势 | - | 否 | [...] | 历史聚合 | 日频 | 是 | 中性/变化可红绿 |

## 3.15 HistoricalTurnoverPoint

**对象定义**：历史成交额趋势点。  
**所属系统**：成交统计服务  
**使用页面和模块**：成交额历史趋势图  
**数据来源**：daily.amount 全市场日聚合  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：主图可中性色，Tooltip 可对较前日变化做红绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradeDate` | `string(date)` | 交易日 | - | 是 | 2026-04-28 | daily.trade_date | 日频 | 是 | 无 |
| `turnoverAmount` | `number` | 成交额 | daily.amount 源聚合口径 | 是 | 10523.0 | sum(daily.amount) | 日频 | 是 | 中性 |
| `prevTradeDate` | `string(date)` | 上一交易日 | - | 否 | 2026-04-27 | trade_cal | 日频 | 是 | 无 |
| `rangeType` | `enum` | 1m / 3m | - | 否 | 1m | 请求参数 | 请求级 | 是 | 无 |

## 3.16 MoneyFlowSummary

**对象定义**：大盘资金流对象，表达今日/昨日主力净流入和分单净流入事实。  
**所属系统**：资金流服务  
**使用页面和模块**：大盘资金流向  
**数据来源**：raw_tushare.moneyflow_mkt_dc  
**更新频率**：盘后/按源；实时资金源接入后 1-5 分钟  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：净流入正数红色，净流出负数绿色。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `todayNetInflowAmount` | `number` | 今日主力净流入 | 元 | 是 | 1211718400 | moneyflow_mkt_dc.net_amount | 盘后/按源 | 是 | 正红负绿 |
| `previousTradeDate` | `string(date)` | 上一交易日 | - | 是 | 2026-04-27 | trade_cal | 日频 | 是 | 无 |
| `previousNetInflowAmount` | `number` | 上一交易日主力净流入 | 元 | 是 | -3910650112 | 历史 net_amount | 盘后 | 是 | 正红负绿 |
| `superLargeOrderNetInflow` | `number` | 超大单净流入 | 元 | 是 | 22524846080 | buy_elg_amount | 盘后 | 是 | 正红负绿 |
| `largeOrderNetInflow` | `number` | 大单净流入 | 元 | 是 | 5433212928 | buy_lg_amount | 盘后 | 是 | 正红负绿 |
| `mediumOrderNetInflow` | `number` | 中单净流入 | 元 | 是 | -1203000000 | buy_md_amount | 盘后 | 是 | 正红负绿 |
| `smallOrderNetInflow` | `number` | 小单净流入 | 元 | 是 | -2203000000 | buy_sm_amount | 盘后 | 是 | 正红负绿 |
| `historyPoints` | `HistoricalMoneyFlowPoint[]` | 历史主力净流入 | - | 否 | [...] | moneyflow_mkt_dc | 日频 | 是 | 正红负绿 |

## 3.17 HistoricalMoneyFlowPoint

**对象定义**：历史大盘资金净流入趋势点。  
**所属系统**：资金流服务  
**使用页面和模块**：资金流历史趋势图  
**数据来源**：moneyflow_mkt_dc.net_amount  
**更新频率**：日频/盘后  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：正数净流入红色，负数净流出绿色。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradeDate` | `string(date)` | 交易日 | - | 是 | 2026-04-28 | moneyflow_mkt_dc.trade_date | 日频 | 是 | 无 |
| `netInflowAmount` | `number` | 主力净流入金额；正为净流入、负为净流出 | 元 | 是 | 1211718400 | moneyflow_mkt_dc.net_amount | 日频 | 是 | 正红负绿 |
| `rangeType` | `enum` | 1m / 3m | - | 否 | 1m | 请求参数 | 请求级 | 是 | 无 |

## 3.18 LimitUpSummary

**对象定义**：涨跌停统计根对象，表达涨停、跌停、炸板、封板率、最高连板等事实。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：涨跌停统计与分布  
**数据来源**：raw_tushare.limit_list_d；必要时 daily + stk_limit 辅助  
**更新频率**：按源；实时源接入后 15-60 秒  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨停红、跌停绿、炸板中性/警示。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradeDate` | `string(date)` | 交易日 | - | 是 | 2026-04-28 | limit_list_d.trade_date | 按源 | 是 | 无 |
| `limitUpCount` | `integer` | 涨停家数 | 只 | 是 | 59 | limit='U' | 按源 | 是 | 红 |
| `limitDownCount` | `integer` | 跌停家数 | 只 | 是 | 8 | limit='D' | 按源 | 是 | 绿 |
| `brokenLimitCount` | `integer` | 炸板家数 | 只 | 是 | 27 | limit='Z' 或业务规则 | 按源 | 是 | 警示/中性 |
| `touchedLimitUpCount` | `integer` | 触及涨停家数 | 只 | 否 | 86 | limitUpCount + brokenLimitCount | 按源 | 是 | 红/中性 |
| `sealRate` | `number` | 封板率 | ratio | 是 | 0.686 | limitUpCount/touchedLimitUpCount | 按源 | 是 | 中性 |
| `maxStreakLevel` | `integer` | 最高连板高度 | 板 | 是 | 6 | max(limit_times) | 按源 | 是 | 红强调 |
| `streakStockCount` | `integer` | 连板股数量 | 只 | 否 | 16 | count(limit_times>=2) | 按源 | 是 | 红强调 |
| `skyToFloorCount` | `integer` | 天地板数量 | 只 | 否 | 1 | 待规则派生 | 按源 | 否 | 绿/警示 |
| `floorToSkyCount` | `integer` | 地天板数量 | 只 | 否 | 2 | 待规则派生 | 按源 | 否 | 红/强调 |
| `distribution` | `LimitUpDistribution` | 分布结构 | - | 是 | {...} | limit_list_d 聚合 | 按源 | 是 | 红/绿 |
| `streakLadder` | `LimitUpStreakLadder` | 连板天梯 | - | 否 | {...} | limit_list_d | 按源 | 是 | 红/绿 |

## 3.19 LimitUpDistribution

**对象定义**：涨跌停分布结构对象，用于表达涨停板块分布、跌停结构、炸板结构、连板层级分布。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：涨跌停统计与分布  
**数据来源**：limit_list_d + dc_member/dc_index/stock_basic 行业映射  
**更新频率**：按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨停红、跌停绿、炸板中性/警示。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `bySector` | `object[]` | 按板块分布 | - | 是 | [...] | limit_list_d + dc_member/dc_index | 按源 | 是 | 红/绿 |
| `byLimitType` | `object[]` | 按涨跌停类型分布 | - | 是 | [...] | limit_list_d.limit | 按源 | 是 | 红/绿 |
| `byStreakLevel` | `object[]` | 按连板层级分布 | - | 否 | [...] | limit_times | 按源 | 是 | 红 |
| `byBrokenLimit` | `object[]` | 炸板分布 | - | 否 | [...] | open_times / limit='Z' | 按源 | 是 | 中性/警示 |
| `distributionItems` | `object[]` | 默认合并展示项 | - | 否 | [...] | 聚合服务 | 按源 | 是 | 红/绿 |

## 3.20 LimitUpStreakLadder

**对象定义**：连板天梯根对象，按连板层级组织股票列表。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：连板天梯  
**数据来源**：limit_list_d.limit_times  
**更新频率**：按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：层级强调红色，股票涨跌按 direction。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradeDate` | `string(date)` | 交易日 | - | 是 | 2026-04-28 | limit_list_d.trade_date | 按源 | 是 | 无 |
| `highestLevel` | `integer` | 最高连板层级 | 板 | 是 | 6 | max(limit_times) | 按源 | 是 | 红强调 |
| `items` | `LimitUpStreakItem[]` | 连板项列表 | - | 是 | [...] | limit_list_d | 按源 | 是 | 股票红绿 |
| `levels` | `object[]` | 层级分组，可选 | - | 否 | [...] | limit_list_d 聚合 | 按源 | 是 | 股票红绿 |
| `asOf` | `datetime` | 数据时间 | - | 否 | 2026-04-28T15:10:00+08:00 | 数据基座 | 按源 | 是 | 无 |

## 3.21 LimitUpStreakItem

**对象定义**：连板天梯中的股票项。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：连板天梯 / StreakStockCard  
**数据来源**：limit_list_d，行情字段可关联 daily  
**更新频率**：按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：changePct 按 direction 正红负绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `stockCode` | `string` | 股票代码 | - | 是 | 002888.SZ | limit_list_d.ts_code | 按源 | 是 | 无 |
| `stockName` | `string` | 股票名称 | - | 是 | 示例股份 | limit_list_d.name | 按源 | 是 | 无 |
| `streakLevel` | `integer` | 连板层级 | 板 | 是 | 3 | limit_times | 按源 | 是 | 红强调 |
| `sectorName` | `string` | 所属板块/行业 | - | 否 | 机器人 | limit_list_d.industry / 板块映射 | 按源 | 是 | 无 |
| `latestPrice` | `number` | 最新价/收盘价 | 元 | 否 | 18.36 | daily.close / limit_list_d.close | 按源 | 是 | 中性 |
| `changePct` | `number` | 涨跌幅 | % | 是 | 10.01 | daily.pct_chg / limit_list_d.pct_chg | 按源 | 是 | 正红负绿 |
| `direction` | `enum` | 涨跌方向 | - | 是 | UP | changePct 派生 | 按源 | 是 | 必须 |
| `openTimes` | `integer` | 开板次数 | 次 | 否 | 1 | limit_list_d.open_times | 按源 | 是 | 中性 |
| `sealedAmount` | `number` | 封单金额 | 源口径 | 否 | 328000000 | limit_list_d.fd_amount | 按源 | 是 | 中性 |
| `firstLimitTime` | `string` | 首次封板时间 | - | 否 | 09:42:15 | limit_list_d.first_time | 按源 | 是 | 无 |

## 3.22 SectorRankItem

**对象定义**：行业、概念、地域板块榜单项。  
**所属系统**：板块行情服务  
**使用页面和模块**：板块速览、板块 Top5、热力图 Tooltip  
**数据来源**：dc_index、dc_daily、moneyflow_ind_dc  
**更新频率**：日频/按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：changePct 和 netInflowAmount 正红负绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `rank` | `integer` | 排名 | - | 是 | 1 | 排序派生 | 按源 | 是 | 中性 |
| `sectorCode` | `string` | 板块代码 | - | 是 | BK1184.DC | dc_index.ts_code | 按源 | 是 | 中性 |
| `sectorName` | `string` | 板块名称 | - | 是 | 人形机器人 | dc_index.name | 按源 | 是 | 中性 |
| `sectorType` | `enum` | INDUSTRY / CONCEPT / REGION | - | 是 | CONCEPT | dc_index.idx_type | 按源 | 是 | 中性 |
| `changePct` | `number` | 板块涨跌幅 | % | 是 | 4.37 | dc_daily.pct_change / dc_index.pct_change | 按源 | 是 | 正红负绿 |
| `turnoverAmount` | `number` | 成交额 | dc_daily.amount 源口径：元 | 否 | 12860000000 | dc_daily.amount | 按源 | 是 | 中性 |
| `netInflowAmount` | `number` | 主力净流入 | 元 | 否 | 2630000000 | moneyflow_ind_dc.net_amount | 盘后/按源 | 是 | 正红负绿 |
| `leadingStockCode` | `string` | 领涨股票代码 | - | 否 | 002117.SZ | dc_index.leading_code | 按源 | 是 | 中性 |
| `leadingStockName` | `string` | 领涨股票名称 | - | 否 | 东港股份 | dc_index.leading | 按源 | 是 | 中性 |
| `leadingStockChangePct` | `number` | 领涨股票涨跌幅 | % | 否 | 10.02 | dc_index.leading_pct | 按源 | 是 | 正红负绿 |

## 3.23 HeatMapItem

**对象定义**：板块热力图节点项。  
**所属系统**：板块热力图服务  
**使用页面和模块**：板块速览 / SectorHeatMapGrid  
**数据来源**：dc_index、dc_daily、moneyflow_ind_dc  
**更新频率**：日频/按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：热力图颜色按 changePct 正红负绿，深浅按分位或绝对值。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `sectorCode` | `string` | 板块代码 | - | 是 | BK1184.DC | dc_index.ts_code | 按源 | 是 | 中性 |
| `sectorName` | `string` | 板块名称 | - | 是 | 人形机器人 | dc_index.name | 按源 | 是 | 中性 |
| `sectorType` | `enum` | INDUSTRY / CONCEPT / REGION | - | 是 | CONCEPT | dc_index.idx_type | 按源 | 是 | 中性 |
| `changePct` | `number` | 涨跌幅 | % | 是 | 4.37 | dc_daily.pct_change | 按源 | 是 | 正红负绿 |
| `direction` | `enum` | 涨跌方向 | - | 是 | UP | changePct 派生 | 按源 | 是 | 必须 |
| `turnoverAmount` | `number` | 成交额 | dc_daily.amount 源口径：元 | 否 | 12860000000 | dc_daily.amount | 按源 | 是 | 中性 |
| `netInflowAmount` | `number` | 主力净流入 | 元 | 否 | 2630000000 | moneyflow_ind_dc.net_amount | 盘后/按源 | 是 | Tooltip 正红负绿 |
| `riseStockCount` | `integer` | 板块上涨家数 | 只 | 否 | 32 | dc_index.up_num | 按源 | 是 | 红 |
| `fallStockCount` | `integer` | 板块下跌家数 | 只 | 否 | 62 | dc_index.down_num | 按源 | 是 | 绿 |
| `rowIndex` | `integer` | 热力图行号，0-based | - | 否 | 0 | 服务端布局/前端派生 | 请求级 | 否 | 无 |
| `colIndex` | `integer` | 热力图列号，0-based | - | 否 | 3 | 服务端布局/前端派生 | 请求级 | 否 | 无 |

## 3.24 StockRankItem

**对象定义**：榜单速览股票项，支持 Top10 表格展示。  
**所属系统**：榜单服务  
**使用页面和模块**：榜单速览 / LeaderboardTop10Table  
**数据来源**：dc_hot 提供基础热榜，daily/daily_basic 补最新价、涨跌幅、换手率、量比、成交量、成交额  
**更新频率**：dc_hot 日内多次；daily/daily_basic 按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：latestPrice、changePct 按 direction；turnoverRate、volumeRatio、volume、amount 中性色。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `rank` | `integer` | 排名 | - | 是 | 1 | dc_hot.rank / 排序派生 | 按源 | 是 | 中性 |
| `stockCode` | `string` | 股票代码 | - | 是 | 601099.SH | dc_hot.ts_code / daily.ts_code | 按源 | 是 | 中性 |
| `stockName` | `string` | 股票名称 | - | 是 | 太平洋 | dc_hot.ts_name / stock_basic.name | 按源 | 是 | 中性 |
| `latestPrice` | `number` | 最新价/收盘价 | 元 | 是 | 4.82 | dc_hot.current_price 或 daily.close | 按源 | 是 | 按 direction |
| `changePct` | `number` | 涨跌幅 | % | 是 | 3.21 | dc_hot.pct_change 或 daily.pct_chg | 按源 | 是 | 正红负绿 |
| `direction` | `enum` | 涨跌方向 | - | 是 | UP | changePct 派生 | 按源 | 是 | 必须 |
| `turnoverRate` | `number` | 换手率 | % | 是 | 5.34 | daily_basic.turnover_rate | 按源 | 是 | 中性 |
| `volumeRatio` | `number` | 量比 | 倍 | 是 | 2.18 | daily_basic.volume_ratio | 按源 | 是 | 中性 |
| `volume` | `number` | 成交量 | daily.vol 源口径：手 | 是 | 356200 | daily.vol | 按源 | 是 | 中性 |
| `amount` | `number` | 成交额 | daily.amount 源口径：千元；前端可格式化万元/亿元 | 是 | 1865000 | daily.amount | 按源 | 是 | 中性 |
| `rankTime` | `string` | 榜单时间 | - | 否 | 22:30:00 | dc_hot.rank_time | 按源 | 否 | 无 |
| `rankType` | `enum` | POPULAR / SURGE / GAINER / LOSER / AMOUNT / TURNOVER / VOLUME_RATIO | - | 是 | POPULAR | 请求参数/派生 | 按源 | 是 | 无 |


---

## 4. 附录 A：字段名词表

| 字段名 | 统一中文名 | 单位/口径 | 常见来源 |
|---|---|---|---|
| `turnover_rate` | 换手率 | % | `daily_basic`、`dc_index`、`dc_daily` |
| `volume_ratio` | 量比 | 倍 | `daily_basic` |
| `pct_chg` | 涨跌幅 | % | `daily`、`index_daily` |
| `pct_change` | 涨跌幅 | % | `dc_index`、`dc_daily`、`dc_hot` |
| `current_price` | 当前价 | 元 | `dc_hot` |
| `close` | 收盘价/最新点位 | 元/点，按源 | `daily`、`index_daily`、`dc_daily` |
| `vol` | 成交量 | `daily.vol` 为手；`dc_daily.vol` 为股 | `daily`、`dc_daily` |
| `amount` | 成交额 | `daily.amount` 为千元；`dc_daily.amount` 为元 | `daily`、`dc_daily` |
| `net_amount` | 主力净流入 | 元，个别个股资金源可能为万元 | `moneyflow_mkt_dc`、`moneyflow_ind_dc` |
| `rank` | 排名 | - | `dc_hot`、排序派生 |
| `limit` | 涨跌停状态 | U/D/Z 等按源 | `limit_list_d` |
| `open_times` | 开板次数 | 次 | `limit_list_d` |
| `limit_times` | 连板数 | 板 | `limit_list_d` |
| `fd_amount` | 封单金额 | 按源口径 | `limit_list_d` |
| `first_time` | 首次封板时间 | 源时间字符串 | `limit_list_d` |
| `idx_type` | 板块类型 | 行业板块/概念板块/地域板块 | `dc_index` |
| `leading` | 领涨股票名称 | - | `dc_index` |
| `leading_code` | 领涨股票代码 | - | `dc_index` |
| `leading_pct` | 领涨股票涨跌幅 | % | `dc_index` |
| `up_num` | 上涨家数 | 只 | `dc_index` |
| `down_num` | 下跌家数 | 只 | `dc_index` |

---

## 5. 文档末尾清单

### 5.1 聚合接口和模块接口推荐使用方式

1. 首屏加载优先使用 `GET /api/market/home-overview`。
2. 模块局部刷新使用模块接口：
   - 指数：`GET /api/index/summary`
   - 涨跌分布：`GET /api/market/breadth`
   - 市场风格：`GET /api/market/style`
   - 成交额：`GET /api/market/turnover`
   - 大盘资金流：`GET /api/moneyflow/market`
   - 涨跌停：`GET /api/limitup/summary`
   - 连板天梯：`GET /api/limitup/streak-ladder`
   - 板块：`GET /api/sector/top`
   - 榜单：`GET /api/leaderboard/stock`
   - 快捷入口：`GET /api/settings/quick-entry`
3. 历史或重计算模块按需局部刷新，避免整页重载。
4. 非核心模块失败时返回 `PARTIAL`，不拖垮整页。

### 5.2 市场总览页面模块与 API 字段映射表

| 页面模块 | 聚合字段 | 模块接口 | 关键对象 |
|---|---|---|---|
| TopMarketBar | `topMarketBar`、`dataStatus` | `/api/index/summary` | TopMarketBarData |
| Breadcrumb | `breadcrumb` | 聚合返回 | BreadcrumbItem |
| ShortcutBar | `quickEntries` | `/api/settings/quick-entry` | QuickEntry |
| 今日市场客观总结 | `marketSummary` | 聚合返回 | MarketObjectiveSummary |
| 主要指数 | `indices` | `/api/index/summary` | IndexSnapshot |
| 涨跌分布 | `breadth` | `/api/market/breadth` | MarketBreadth |
| 市场风格 | `style` | `/api/market/style` | MarketStyle |
| 成交额总览 | `turnover` | `/api/market/turnover` | TurnoverSummary |
| 大盘资金流向 | `moneyFlow` | `/api/moneyflow/market` | MoneyFlowSummary |
| 涨跌停统计与分布 | `limitUp`、`limitUpDistribution` | `/api/limitup/summary` | LimitUpSummary |
| 连板天梯 | `streakLadder` | `/api/limitup/streak-ladder` | LimitUpStreakLadder |
| 板块速览 | `sectorOverview` | `/api/sector/top` | SectorRankItem / HeatMapItem |
| 榜单速览 | `leaderboards` | `/api/leaderboard/stock` | StockRankItem |

### 5.3 给 02 HTML Showcase 的 Mock 数据建议

1. 使用 `GET /api/market/home-overview` 的 response 作为根 mock。
2. 主要指数至少 10 个，建议 2 行 × 5 列。
3. 榜单 Top10 每组至少 10 条，并包含换手率、量比、成交量、成交额。
4. 板块 8 个 Top5 各至少 5 条。
5. 热力图至少 20 条，对应 5 行 × 4 列。
6. 快捷入口不得出现任何市场温度/情绪/资金面/风险分数。
7. 所有涨跌相关字段都提供 `direction`。

### 5.4 给 03 组件库的 Props 映射建议

| 组件 | Props |
|---|---|
| `TopMarketBar` | `topMarketBar: TopMarketBarData` |
| `Breadcrumb` | `items: BreadcrumbItem[]` |
| `ShortcutBar` | `items: QuickEntry[]` |
| `MarketObjectiveSummaryPanel` | `summary: MarketObjectiveSummary` |
| `IndexGrid` | `items: IndexSnapshot[]` |
| `MarketBreadthPanel` | `breadth: MarketBreadth` |
| `MarketStylePanel` | `style: MarketStyle` |
| `TurnoverPanel` | `turnover: TurnoverSummary` |
| `MoneyFlowPanel` | `moneyFlow: MoneyFlowSummary` |
| `LimitUpPanel` | `limitUp: LimitUpSummary`、`distribution: LimitUpDistribution` |
| `StreakLadder` | `streakLadder: LimitUpStreakLadder` |
| `SectorOverviewMatrix` | `sectorOverview` |
| `LeaderboardTop10Table` | `items: StockRankItem[]` |

### 5.5 给 05 Codex 提示词的 API 约束

1. 只接入 `GET /api/market/home-overview` 的 mock 根对象。
2. 不得新增主观分数字段或交易建议字段。
3. 严格按 `direction` 做红涨绿跌。
4. 金额、成交量单位按 API 字段说明展示，不擅自改口径。
5. 空值显示 `--`，不要显示误导性 `0`。
6. 模块异常使用局部异常态，不整页白屏。
7. 榜单列顺序：排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额。

### 5.6 P0 已具备字段

| 能力 | 来源 |
|---|---|
| 交易日、上一交易日 | `trade_cal` |
| 指数行情 | `index_daily` |
| 个股行情、市场广度、成交额 | `daily` |
| 换手率、量比、市值 | `daily_basic` |
| 大盘资金流 | `moneyflow_mkt_dc` |
| 涨跌停、炸板、连板 | `limit_list_d` |
| 涨跌停价格 | `stk_limit` |
| 行业/概念/地域板块 | `dc_index`、`dc_member`、`dc_daily` |
| 板块资金流 | `moneyflow_ind_dc` |
| 热榜 | `dc_hot` |

### 5.7 P0 暂缺字段

| 字段/能力 | 原因 |
|---|---|
| 实时全市场分钟级成交额 | 需建设分钟聚合视图或接入实时源 |
| 实时资金流 | 当前 `moneyflow_mkt_dc` 更偏盘后/按源 |
| 实时封单变化 | 需实时涨跌停源 |
| 天地板/地天板 | 需稳定规则确认 |
| 板块平盘家数 | `dc_index` 仅有 `up_num/down_num`，需 `dc_member + daily` 精算 |
| 热力图排序算法 | 需产品确认按涨跌幅、成交额、资金流还是综合 |

### 5.8 需要数据基座补充的字段/视图

1. `wealth_market_home_overview_snapshot`
2. `wealth_market_breadth_snapshot`
3. `wealth_turnover_summary_snapshot`
4. `wealth_moneyflow_market_snapshot`
5. `wealth_limitup_snapshot`
6. `wealth_limitup_distribution_snapshot`
7. `wealth_limitup_streak_ladder_snapshot`
8. `wealth_sector_overview_matrix_snapshot`
9. `wealth_sector_heatmap_snapshot`
10. `wealth_stock_leaderboard_snapshot`
11. `wealth_data_source_status`

### 5.9 待产品总控确认问题

1. 榜单速览默认采用 `dc_hot` 热榜，还是传统涨幅/成交额/换手/量比榜？
2. 市场广度样本池是否排除 ST、新股、停牌、无涨跌幅限制股票？
3. 热力图排序依据：涨跌幅、成交额、资金净流入，还是综合排序？
4. 天地板/地天板是否进入市场总览 P0 首屏？
5. 资金流数据盘中缺失时是否允许显示最近盘后数据并标记 `DELAYED`？
