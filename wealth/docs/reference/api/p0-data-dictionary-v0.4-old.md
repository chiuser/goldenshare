# 财势乾坤｜P0 数据字典 v0.4

建议保存路径：`/docs/wealth/api/p0-data-dictionary.md`  
公共区建议保存路径：`财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4.md`  
负责人：`04_API 契约与数据字典`  
版本：`v0.4`  
状态：`HTML Review v1 补字段修订稿`  
更新时间：`2026-05-07`

---

## 本轮实际读取的公共区文件

| 序号 | 文件名 | 读取到的版本 / 状态 |
|---:|---|---|
| 1 | `财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2`，Review 草案 v0.2 |
| 2 | `市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2`，Review 草案 |
| 3 | `02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1`，本轮产物为 `market-overview-v1.html` |
| 4 | `04-component-guidelines.md` | `P0 组件库与交互组件方案 v0.3`，Draft v0.3 |
| 5 | `p0-data-dictionary-v0.3.md` | `P0 数据字典 v0.3`，Audit 修订稿 |
| 6 | `market-overview-api-v0.3.md` | `市场总览 API 草案 v0.3`，Audit 修订稿 |
| 7 | `市场总览html_review_v_1_总控解读与变更单.md` | `市场总览 HTML Review v1｜总控解读与变更单`，目标输出 `market-overview-v1.1.html` |
| 8 | `tushare接口文档/README.md` | Tushare 接口说明目录（本地镜像） |
| 9 | `tushare接口文档/docs_index.csv` | Tushare 文档总索引，包含 `doc_id/title/api_name/local_path` |


---

## 0. 本轮审计结论

本版基于 `market-overview-v1.1` 的总控变更单修订，目标是让市场总览 API 能直接支撑新增图表、历史趋势、日内成交额曲线、资金流历史曲线、涨跌停历史柱图和横向连板天梯。

本版保持以下产品边界：

1. 市场总览是 **A 股市场客观事实总览页**。
2. 市场总览属于 **乾坤行情**，不是独立一级菜单。
3. 桌面端不使用固定 SideNav；API 继续支持 `TopMarketBar`、`Breadcrumb`、`ShortcutBar`。
4. 市场总览不返回市场温度、市场情绪指数、资金面分数、风险指数作为核心结论。
5. 禁止返回：`marketTemperatureScore`、`marketSentimentScore`、`capitalScore`、`riskIndexScore`、`buySuggestion`、`sellSuggestion`、`positionSuggestion`、`tomorrowPrediction`、`subjectiveMarketConclusion`。
6. API 使用财势乾坤业务对象和业务字段组织，不复刻 Tushare API。
7. 行情显示必须支持中国 A 股 **红涨绿跌**。

---

## 1. 字段命名、单位与红涨绿跌规则

### 1.1 字段命名

| 项目 | 规则 |
| --- | --- |
| API 字段 | `lowerCamelCase`，使用财势乾坤业务命名 |
| 源字段 | 在数据字典和附录中记录 Tushare / PostgreSQL 落库字段名 |
| 日期 | API 返回 `YYYY-MM-DD`；落库源可能为 `YYYYMMDD` |
| 时间 | API 返回 `HH:mm` 或 ISO 8601，按字段说明标注 |
| 金额单位 | 默认保持 Tushare / PostgreSQL 落库口径；字段表必须写明单位 |
| 成交量单位 | 默认保持 Tushare / PostgreSQL 落库口径；字段表必须写明单位 |
| 涨跌幅 | 百分数数值，例如 `1.23` 表示 `1.23%` |
| rangeType | `1m` / `3m` |
| direction | `UP` / `DOWN` / `FLAT` / `UNKNOWN` |

### 1.2 红涨绿跌

| 数据含义 | 方向字段 | 显示颜色 |
| --- | --- | --- |
| 上涨、涨幅、涨停、净流入正值 | `UP` 或 value > 0 | 红色 |
| 下跌、跌幅、跌停、净流出负值 | `DOWN` 或 value < 0 | 绿色 |
| 平盘、零值、无变化 | `FLAT` 或 value = 0 | 灰色 |
| 不适用 / 未知 | `UNKNOWN` | 中性灰 |

### 1.3 Tushare / 落库数据集参考

| 业务域 | 主数据集 / 落库表 | 关键字段 | 说明 |
| --- | --- | --- | --- |
| 交易日 | `trade_cal` / `raw_tushare.trade_cal` | `cal_date`、`is_open`、`pretrade_date` | `is_open` 已落库为 boolean |
| 个股日线 | `daily` / `raw_tushare.daily` | `pct_chg`、`vol`、`amount` | 市场广度、历史成交额、涨跌分布 |
| 每日指标 | `daily_basic` / `raw_tushare.daily_basic` | `turnover_rate`、`volume_ratio` | 榜单扩展、换手/量比 |
| 指数日线 | `index_daily` / `raw_tushare.index_daily` | `close`、`pct_chg`、`amount` | TopMarketBar、主要指数、市场风格 |
| 分钟行情 | `stk_mins` / `raw_tushare.stk_mins` 或实时分钟基座 | `trade_time`、`amount` | 日内累计成交额趋势；若无全市场分钟聚合需数据基座补充 |
| 大盘资金流 | `moneyflow_mkt_dc` / `raw_tushare.moneyflow_mkt_dc` | `net_amount`、`buy_elg_amount`、`buy_lg_amount`、`buy_md_amount`、`buy_sm_amount` | 大盘资金流与历史资金流 |
| 涨跌停 / 炸板 | `limit_list_d` / `raw_tushare.limit_list_d` | `limit`、`open_times`、`limit_times`、`first_time`、`fd_amount` | 涨跌停统计、分布、连板天梯 |
| 涨跌停价格 | `stk_limit` / `raw_tushare.stk_limit` | `up_limit`、`down_limit` | 涨跌停状态辅助校验 |
| 东方财富板块列表 | `dc_index` / `raw_tushare.dc_index` | `ts_code`、`name`、`pct_change`、`up_num`、`down_num`、`idx_type`、`level` | 行业/概念/地域板块 |
| 东方财富板块成分 | `dc_member` / `raw_tushare.dc_member` | `ts_code`、`con_code`、`name` | 板块下钻、精算板块红盘率 |
| 东方财富板块日线 | `dc_daily` / `raw_tushare.dc_daily` | `open`、`high`、`low`、`close`、`change`、`pct_change`、`vol`、`amount`、`swing`、`turnover_rate` | 板块行情、热力图、板块榜 |
| 东方财富板块资金流 | `moneyflow_ind_dc` / `raw_tushare.moneyflow_ind_dc` | `net_amount`、`rank` | 板块资金流补充 |
| 东方财富热榜 | `dc_hot` / `raw_tushare.dc_hot` | `rank`、`pct_change`、`current_price`、`rank_time` | 榜单速览 / 热榜 |

---

## 2. 对象总览

| 对象 | P0 用途 |
| --- | --- |
| TradingDay | 当前交易日与交易阶段对象。 |
| DataSourceStatus | 数据源和数据集状态对象。 |
| TopMarketBarData | 顶部全局栏数据。 |
| GlobalSystemEntry | 顶部一级系统入口。 |
| BreadcrumbItem | 面包屑项。 |
| QuickEntry | 页面内快捷入口。 |
| UserShortcutStatus | 用户自选、持仓、提醒等快捷状态。 |
| MarketOverview | 市场总览聚合根对象。 |
| MarketObjectiveSummary | 今日市场客观总结，只陈列事实，不给主观结论。 |
| IndexSnapshot | 指数行情快照。 |
| MarketBreadth | 当前涨跌分布、涨跌幅区间与历史趋势。 |
| HistoricalBreadthPoint | 涨跌分布历史趋势点。 |
| BreadthDistributionBucket | 涨跌幅区间分布桶。 |
| MarketStyle | 市场风格当前值与历史三线趋势。 |
| MarketStyleHistoryPoint | 市场风格历史趋势点。 |
| TurnoverSummary | 成交额总览、当日累计成交额曲线和历史成交额曲线。 |
| IntradayTurnoverPoint | 当日累计成交额趋势点。 |
| HistoricalTurnoverPoint | 历史成交额趋势点。 |
| MoneyFlowSummary | 大盘资金净流入、分单结构和历史资金流。 |
| HistoricalMoneyFlowPoint | 历史大盘资金净流入趋势点。 |
| LimitUpSummary | 涨跌停统计、分布和历史柱图聚合对象。 |
| HistoricalLimitUpDownPoint | 历史涨跌停组合柱图点。 |
| LimitUpDistribution | 当日涨跌停分布结构对象；v0.4 改造为图表数据结构，不再是普通列表。 |
| LimitUpDistributionItem | 涨跌停分布单项。 |
| LimitUpStreakLadder | 横向连板天梯根对象。 |
| LimitUpStreakLevel | 连板天梯层级。 |
| LimitUpStreakStock | 连板天梯股票卡片。 |
| SectorRankItem | 行业/概念/地域板块榜单项。 |
| HeatMapItem | 板块热力图节点。 |
| StockRankItem | 榜单股票项。P0 默认使用东方财富热榜，也可扩展为行情榜。 |

---

## 3. 对象字典

### 3.1 TradingDay

**对象定义**：当前交易日与交易阶段对象。  
**所属系统**：乾坤行情 / 交易日历服务  
**使用页面和模块**：TopMarketBar、PageHeader、全部行情模块  
**数据来源**：raw_tushare.trade_cal；`is_open` 已落库为 boolean  
**更新频率**：日频；交易阶段分钟级派生  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不直接参与红涨绿跌，但影响数据日期与刷新状态。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 当前交易日 | - | 是 | 2026-04-28 | trade_cal.cal_date | 日频 | 是 | 无 |
| prevTradeDate | string(date) | 上一交易日 | - | 是 | 2026-04-27 | trade_cal.pretrade_date | 日频 | 是 | 无 |
| market | enum | 市场，P0 固定 CN_A | - | 是 | CN_A | 系统配置 | 固定 | 是 | 无 |
| isTradingDay | boolean | 是否交易日；当前落库已由 0/1 改为 boolean | - | 是 | true | trade_cal.is_open | 日频 | 是 | 无 |
| sessionStatus | enum | PRE_OPEN / OPEN / NOON_BREAK / CLOSED / HOLIDAY | - | 是 | CLOSED | 服务端时间派生 | 分钟 | 是 | 无 |
| timezone | string | 交易时区 | - | 是 | Asia/Shanghai | 系统配置 | 固定 | 是 | 无 |

### 3.2 DataSourceStatus

**对象定义**：数据源和数据集状态对象。  
**所属系统**：数据中心 / 数据源监控服务  
**使用页面和模块**：TopMarketBar、PageHeader、模块 Tooltip、异常态  
**数据来源**：ETL 任务、数据质量校验、raw_tushare 表最新交易日  
**更新频率**：任务完成或分钟级  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：状态使用系统状态色，不使用行情红绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sourceId | string | 数据源 ID | - | 是 | tushare_daily | 数据源配置 | 低频 | 是 | 无 |
| dataset | string | 数据集/API 名称 | - | 是 | daily | 同步任务 | 任务级 | 是 | 无 |
| tableName | string | 落库表名 | - | 是 | raw_tushare.daily | 数据基座 | 低频 | 是 | 无 |
| dataDomain | enum | QUOTE / INDEX / BREADTH / TURNOVER / MONEY_FLOW / LIMIT_UP / SECTOR / LEADERBOARD | - | 是 | TURNOVER | 配置 | 低频 | 是 | 无 |
| status | enum | READY / DELAYED / PARTIAL / EMPTY / ERROR / NO_PERMISSION | - | 是 | READY | 监控服务 | 分钟/任务 | 是 | 状态色 |
| latestTradeDate | string(date) | 最新交易日 | - | 否 | 2026-04-28 | max(trade_date) | 任务级 | 是 | 无 |
| latestDataTime | datetime | 最新同步时间 | - | 否 | 2026-04-28T17:10:00+08:00 | 同步任务 | 任务级 | 是 | 无 |
| completenessPct | number | 完整度 | % | 否 | 99.6 | 校验任务 | 任务级 | 是 | 无 |
| message | string | 状态说明 | - | 否 | 资金流数据为盘后更新 | 监控服务 | 分钟 | 是 | 无 |

### 3.3 TopMarketBarData

**对象定义**：顶部全局栏数据。  
**所属系统**：全局框架 / 乾坤行情  
**使用页面和模块**：TopMarketBar  
**数据来源**：系统配置、IndexSnapshot[]、TradingDay、DataSourceStatus、用户服务  
**更新频率**：指数随行情；入口低频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：indexTickers 必须按 direction 红涨绿跌。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| brandName | string | 产品名称 | - | 是 | 财势乾坤 | 系统配置 | 低频 | 是 | 无 |
| activeSystemKey | string | 当前一级系统 key | - | 是 | quote | 页面上下文 | 路由级 | 是 | 无 |
| globalEntries | GlobalSystemEntry[] | 一级系统入口 | - | 是 | [...] | 系统配置 | 低频 | 是 | 无 |
| indexTickers | IndexSnapshot[] | 顶部指数条 | - | 是 | [...] | index_daily/指数快照 | 按源 | 是 | 必须 |
| tradingDay | TradingDay | 交易日状态 | - | 是 | {...} | trade_cal | 日频/分钟 | 是 | 无 |
| dataStatus | DataSourceStatus[] | 关键数据状态 | - | 是 | [...] | 数据源监控 | 分钟 | 是 | 状态色 |
| userShortcutStatus | UserShortcutStatus | 用户快捷状态 | - | 否 | {watchCount:18} | 用户服务 | 实时/缓存 | 是 | 无 |

### 3.4 GlobalSystemEntry

**对象定义**：顶部一级系统入口。  
**所属系统**：全局导航  
**使用页面和模块**：TopMarketBar / GlobalSystemMenu  
**数据来源**：系统配置  
**更新频率**：低频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：无。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| key | string | 入口 key | - | 是 | quote | 系统配置 | 低频 | 是 | 无 |
| title | string | 入口名称 | - | 是 | 乾坤行情 | 系统配置 | 低频 | 是 | 无 |
| route | string | 路由 | - | 是 | /market/overview | 路由配置 | 低频 | 是 | 无 |
| active | boolean | 是否当前激活 | - | 是 | true | 页面上下文 | 路由级 | 是 | 无 |
| enabled | boolean | 是否可用 | - | 是 | true | 权限/配置 | 低频 | 是 | 无 |
| sortOrder | integer | 排序 | - | 否 | 10 | 系统配置 | 低频 | 是 | 无 |

### 3.5 BreadcrumbItem

**对象定义**：面包屑项。  
**所属系统**：页面框架  
**使用页面和模块**：Breadcrumb  
**数据来源**：路由配置  
**更新频率**：路由级  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：无。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| label | string | 显示名称 | - | 是 | 乾坤行情 | 路由配置 | 路由级 | 是 | 无 |
| route | string | 路由 | - | 否 | /market | 路由配置 | 路由级 | 是 | 无 |
| current | boolean | 是否当前页 | - | 是 | false | 页面上下文 | 路由级 | 是 | 无 |
| disabled | boolean | 是否禁用点击 | - | 否 | false | 页面上下文 | 路由级 | 否 | 无 |

### 3.6 QuickEntry

**对象定义**：页面内快捷入口。  
**所属系统**：页面框架 / 快捷入口配置  
**使用页面和模块**：ShortcutBar  
**数据来源**：系统配置、用户服务  
**更新频率**：配置低频；状态实时/缓存  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：不展示主观评分，不使用行情红绿表达入口状态。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| key | string | 入口 key | - | 是 | market-emotion | 配置 | 低频 | 是 | 无 |
| title | string | 入口名称 | - | 是 | 市场温度与情绪 | 配置 | 低频 | 是 | 无 |
| description | string | 入口描述 | - | 是 | 进入分析页查看温度、情绪、资金与风险 | 配置 | 低频 | 是 | 无 |
| route | string | 路由 | - | 是 | /market/emotion | 路由配置 | 低频 | 是 | 无 |
| enabled | boolean | 是否可用 | - | 是 | true | 权限/配置 | 低频 | 是 | 无 |
| pendingCount | integer | 待处理数量 | 个 | 否 | 2 | 用户服务 | 实时/缓存 | 是 | 无 |
| hasUpdate | boolean | 是否有更新 | - | 否 | true | 用户服务 | 实时/缓存 | 是 | 无 |

### 3.7 UserShortcutStatus

**对象定义**：用户自选、持仓、提醒等快捷状态。  
**所属系统**：用户服务 / 交易助手  
**使用页面和模块**：TopMarketBar、ShortcutBar  
**数据来源**：用户自选、持仓、提醒服务  
**更新频率**：实时/缓存  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：无。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| watchCount | integer | 自选数量 | 只 | 否 | 18 | 自选服务 | 实时/缓存 | 是 | 无 |
| positionCount | integer | 手工持仓数量 | 只 | 否 | 5 | 持仓服务 | 实时/缓存 | 是 | 无 |
| activeAlertCount | integer | 启用提醒数量 | 条 | 否 | 12 | 提醒服务 | 实时/缓存 | 是 | 无 |
| unreadAlertCount | integer | 未读提醒数量 | 条 | 否 | 2 | 提醒服务 | 实时/缓存 | 是 | 无 |
| hasPreference | boolean | 是否设置投资偏好 | - | 否 | true | 用户偏好 | 缓存 | 否 | 无 |

### 3.8 MarketOverview

**对象定义**：市场总览聚合根对象。  
**所属系统**：乾坤行情 / 首页聚合服务  
**使用页面和模块**：市场总览整页  
**数据来源**：全部市场总览业务对象聚合  
**更新频率**：按模块不同，聚合接口默认缓存 15-60 秒  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：透传各行情对象 direction 和正负值。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradingDay | TradingDay | 交易日 | - | 是 | {...} | trade_cal | 日频/分钟 | 是 | 无 |
| dataStatus | DataSourceStatus[] | 数据状态 | - | 是 | [...] | 监控服务 | 分钟 | 是 | 状态色 |
| topMarketBar | TopMarketBarData | 顶部栏 | - | 是 | {...} | 聚合 | 混合 | 是 | 指数红绿 |
| breadcrumb | BreadcrumbItem[] | 面包屑 | - | 是 | [...] | 路由 | 路由级 | 是 | 无 |
| quickEntries | QuickEntry[] | 快捷入口 | - | 是 | [...] | 配置/用户 | 缓存 | 是 | 无 |
| marketSummary | MarketObjectiveSummary | 今日市场客观总结 | - | 是 | {...} | 聚合 | 按源 | 是 | 数值正负 |
| indices | IndexSnapshot[] | 主要指数 | - | 是 | [...] | index_daily | 按源 | 是 | 必须 |
| breadth | MarketBreadth | 涨跌分布 | - | 是 | {...} | daily 聚合 | 按源 | 是 | 必须 |
| style | MarketStyle | 市场风格 | - | 是 | {...} | index_daily/daily 聚合 | 按源 | 是 | 必须 |
| turnover | TurnoverSummary | 成交额 | 源口径 | 是 | {...} | daily/分钟聚合 | 按源 | 是 | 正负变化 |
| moneyFlow | MoneyFlowSummary | 资金流 | 元 | 是 | {...} | moneyflow_mkt_dc | 盘后/按源 | 是 | 正红负绿 |
| limitUp | LimitUpSummary | 涨跌停统计与分布 | - | 是 | {...} | limit_list_d | 按源 | 是 | 涨停红跌停绿 |
| streakLadder | LimitUpStreakLadder | 横向连板天梯 | - | 是 | {...} | limit_list_d | 按源 | 是 | 股票涨跌红绿 |
| sectorOverview | object | 板块速览 | - | 是 | {...} | dc_index/dc_daily/moneyflow_ind_dc | 按源 | 是 | 板块涨跌红绿 |
| leaderboards | object | 榜单速览 | - | 是 | {...} | dc_hot/扩展榜单 | 按源 | 是 | 股票涨跌红绿 |

### 3.9 MarketObjectiveSummary

**对象定义**：今日市场客观总结，只陈列事实，不给主观结论。  
**所属系统**：乾坤行情 / 聚合服务  
**使用页面和模块**：今日市场客观总结  
**数据来源**：MarketBreadth、TurnoverSummary、MoneyFlowSummary、LimitUpSummary  
**更新频率**：随聚合接口  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：事实项按 direction 或 valueSign 显示红绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| title | string | 标题 | - | 是 | A股市场事实概览 | 配置 | 低频 | 是 | 无 |
| facts | object[] | 事实项 | - | 是 | [{label:'上涨家数',value:3421}] | 聚合 | 按源 | 是 | 可按方向 |
| forbiddenConclusion | boolean | 是否禁止主观结论 | - | 是 | true | 固定 | 固定 | 是 | 无 |
| asOf | datetime | 数据时间 | - | 是 | 2026-04-28T15:10:00+08:00 | 聚合 | 按源 | 是 | 无 |

### 3.10 IndexSnapshot

**对象定义**：指数行情快照。  
**所属系统**：指数行情服务  
**使用页面和模块**：TopMarketBar、主要指数  
**数据来源**：raw_tushare.index_daily  
**更新频率**：日频/按源，实时源接入后分钟级  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：点位、涨跌额、涨跌幅按 direction。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| indexCode | string | 指数代码 | - | 是 | 000001.SH | index_daily.ts_code | 按源 | 是 | 无 |
| indexName | string | 指数名称 | - | 是 | 上证指数 | 指数配置 | 低频 | 是 | 无 |
| last | number | 最新/收盘点位 | 点 | 是 | 3128.42 | index_daily.close | 按源 | 是 | 按 direction |
| prevClose | number | 昨收 | 点 | 是 | 3099.76 | index_daily.pre_close | 按源 | 是 | 无 |
| change | number | 涨跌点 | 点 | 是 | 28.66 | index_daily.change | 按源 | 是 | 正红负绿 |
| changePct | number | 涨跌幅 | % | 是 | 0.92 | index_daily.pct_chg | 按源 | 是 | 正红负绿 |
| amount | number | 成交额 | 源口径 | 否 | 482300000 | index_daily.amount | 按源 | 是 | 无 |
| direction | enum | 涨跌方向 | - | 是 | UP | changePct 派生 | 按源 | 是 | 必须 |
| asOf | datetime | 数据时间 | - | 是 | 2026-04-28T15:10:00+08:00 | 数据基座 | 按源 | 是 | 无 |

### 3.11 MarketBreadth

**对象定义**：当前涨跌分布、涨跌幅区间与历史趋势。  
**所属系统**：市场广度统计服务  
**使用页面和模块**：涨跌分布  
**数据来源**：daily、样本池规则、limit_list_d 辅助  
**更新频率**：日频/按源；实时源接入后分钟级  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：上涨相关红、下跌相关绿、平盘灰。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| samplePool | string | 样本池 | - | 是 | CN_A_COMMON | 样本池配置 | 日频 | 是 | 无 |
| totalCount | integer | 样本总数 | 只 | 是 | 5128 | daily 有效记录 | 按源 | 是 | 无 |
| riseCount | integer | 上涨家数 | 只 | 是 | 3421 | daily.pct_chg > 0 | 按源 | 是 | 红 |
| fallCount | integer | 下跌家数 | 只 | 是 | 1488 | daily.pct_chg < 0 | 按源 | 是 | 绿 |
| flatCount | integer | 平盘家数 | 只 | 是 | 219 | daily.pct_chg = 0 | 按源 | 是 | 灰 |
| medianChangePct | number | 中位涨跌幅 | % | 是 | 0.48 | median(daily.pct_chg) | 按源 | 是 | 正红负绿 |
| distribution | BreadthDistributionBucket[] | 涨跌幅区间 | - | 是 | [...] | daily.pct_chg 分桶 | 按源 | 是 | 按 bucket direction |
| historyPoints | HistoricalBreadthPoint[] | 历史趋势，默认 1m | - | 是 | [...] | 预聚合 | 日频 | 是 | 上涨线红、下跌线绿 |
| rangeType | enum | 当前历史区间 | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.12 HistoricalBreadthPoint

**对象定义**：涨跌分布历史趋势点。  
**所属系统**：市场广度统计服务  
**使用页面和模块**：涨跌分布历史趋势图  
**数据来源**：daily 每日聚合  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：上涨线红、下跌线绿；平盘默认不展示。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | daily.trade_date | 日频 | 是 | 无 |
| riseCount | integer | 上涨家数 | 只 | 是 | 3421 | pct_chg > 0 | 日频 | 是 | 红线 |
| fallCount | integer | 下跌家数 | 只 | 是 | 1488 | pct_chg < 0 | 日频 | 是 | 绿线 |
| flatCount | integer | 平盘家数，前端历史图默认不展示 | 只 | 否 | 219 | pct_chg = 0 | 日频 | 是 | 灰，可隐藏 |
| totalCount | integer | 样本总数 | 只 | 是 | 5128 | 聚合 | 日频 | 是 | 无 |
| rangeType | enum | 1m / 3m | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.13 BreadthDistributionBucket

**对象定义**：涨跌幅区间分布桶。  
**所属系统**：市场广度统计服务  
**使用页面和模块**：涨跌分布当日区间图  
**数据来源**：daily.pct_chg 分桶  
**更新频率**：按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨幅桶红、跌幅桶绿、平盘灰。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bucketKey | string | 桶 key | - | 是 | GT_5 | 服务端规则 | 低频 | 是 | 按 direction |
| bucketName | string | 桶名称 | - | 是 | 涨超5% | 服务端规则 | 低频 | 是 | 按 direction |
| minPct | number | 下限 | % | 否 | 5 | 服务端规则 | 低频 | 是 | 无 |
| maxPct | number | 上限 | % | 否 | null | 服务端规则 | 低频 | 是 | 无 |
| count | integer | 数量 | 只 | 是 | 186 | daily.pct_chg | 按源 | 是 | 按 direction |
| direction | enum | 桶方向 | - | 是 | UP | 规则派生 | 低频 | 是 | 必须 |

### 3.14 MarketStyle

**对象定义**：市场风格当前值与历史三线趋势。  
**所属系统**：市场风格统计服务  
**使用页面和模块**：市场风格  
**数据来源**：大盘/小盘代表指数 index_daily，中位涨跌幅来自 MarketBreadth  
**更新频率**：日频/按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨跌幅正红负绿；历史三线按组件约定显示。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| largeCapIndexCode | string | 大盘代表指数 | - | 是 | 000300.SH | 配置 | 低频 | 是 | 无 |
| smallCapIndexCode | string | 小盘代表指数 | - | 是 | 000852.SH | 配置 | 低频 | 是 | 无 |
| largeCapChangePct | number | 大盘涨跌幅 | % | 是 | 0.72 | index_daily.pct_chg | 按源 | 是 | 正红负绿 |
| smallCapChangePct | number | 小盘涨跌幅 | % | 是 | 1.48 | index_daily.pct_chg | 按源 | 是 | 正红负绿 |
| medianChangePct | number | 全市场中位涨跌幅 | % | 是 | 0.48 | MarketBreadth | 按源 | 是 | 正红负绿 |
| styleLeader | enum | LARGE_CAP / SMALL_CAP / BALANCED | - | 是 | SMALL_CAP | 派生 | 按源 | 是 | 无 |
| historyPoints | MarketStyleHistoryPoint[] | 历史趋势点 | - | 是 | [...] | 预聚合 | 日频 | 是 | 正负 Tooltip |
| rangeType | enum | 当前历史区间 | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.15 MarketStyleHistoryPoint

**对象定义**：市场风格历史趋势点。  
**所属系统**：市场风格统计服务  
**使用页面和模块**：市场风格三线历史趋势图  
**数据来源**：index_daily + MarketBreadth 历史聚合  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：Tooltip 正负值按红绿；线色由组件固定。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日频 | 是 | 无 |
| largeCapChangePct | number | 大盘代表指数涨跌幅 | % | 是 | 0.72 | index_daily | 日频 | 是 | 正红负绿 |
| smallCapChangePct | number | 小盘代表指数涨跌幅 | % | 是 | 1.48 | index_daily | 日频 | 是 | 正红负绿 |
| medianChangePct | number | 全市场中位涨跌幅 | % | 是 | 0.48 | daily 聚合 | 日频 | 是 | 正红负绿 |
| rangeType | enum | 1m / 3m | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.16 TurnoverSummary

**对象定义**：成交额总览、当日累计成交额曲线和历史成交额曲线。  
**所属系统**：成交统计服务  
**使用页面和模块**：成交额总览  
**数据来源**：daily.amount 全市场聚合；日内累计需分钟/实时成交聚合  
**更新频率**：日频/盘中分钟级  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：较上一交易日变化正红负绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| todayTurnoverAmount | number | 今日成交总额 | 源口径 | 是 | 10523.0 | sum(daily.amount) 或实时累计 | 按源 | 是 | 无 |
| previousTradeDate | string(date) | 上一交易日 | - | 是 | 2026-04-27 | trade_cal | 日频 | 是 | 无 |
| previousTurnoverAmount | number | 上一交易日成交总额 | 源口径 | 是 | 9821.0 | 历史聚合 | 日频 | 是 | 无 |
| turnoverChangeAmount | number | 成交额变化 | 源口径 | 是 | 702.0 | 派生 | 按源 | 是 | 正红负绿 |
| turnoverChangePct | number | 成交额变化幅度 | % | 是 | 7.15 | 派生 | 按源 | 是 | 正红负绿 |
| ma5TurnoverAmount | number | 5 日均成交额 | 源口径 | 否 | 10012.0 | 历史聚合 | 日频 | 是 | 无 |
| ma20TurnoverAmount | number | 20 日均成交额 | 源口径 | 否 | 9360.0 | 历史聚合 | 日频 | 是 | 无 |
| intradayPoints | IntradayTurnoverPoint[] | 当日累计成交额点 | - | 是 | [...] | 分钟/实时聚合 | 1-5 分钟 | 是 | 无 |
| historyPoints | HistoricalTurnoverPoint[] | 历史成交额 | - | 是 | [...] | 日频聚合 | 日频 | 是 | 无 |
| rangeType | enum | 历史区间 | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.17 IntradayTurnoverPoint

**对象定义**：当日累计成交额趋势点。  
**所属系统**：成交统计服务  
**使用页面和模块**：成交额总览日内累计成交曲线  
**数据来源**：全市场分钟成交额聚合；若没有全市场分钟聚合表，需数据基座补充  
**更新频率**：盘中 1-5 分钟  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：曲线中性，不按红绿表达涨跌。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | 交易日历 | 日频 | 是 | 无 |
| time | string(HH:mm) | 时间点；至少支持 09:30/11:30/15:00 | - | 是 | 09:30 | 分钟聚合 | 1-5 分钟 | 是 | 无 |
| cumulativeTurnoverAmount | number | 截至该时间累计成交额 | 源口径 | 是 | 128.5 | 分钟/实时聚合 | 1-5 分钟 | 是 | 无 |
| market | enum | 市场 | - | 是 | CN_A | 系统配置 | 固定 | 是 | 无 |
| dataStatus | enum | 数据状态 | - | 是 | READY | 监控 | 分钟 | 是 | 状态色 |

### 3.18 HistoricalTurnoverPoint

**对象定义**：历史成交额趋势点。  
**所属系统**：成交统计服务  
**使用页面和模块**：成交额历史趋势图  
**数据来源**：daily.amount 全市场日聚合  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：主图中性，Tooltip 可显示较前日变化红绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | daily.trade_date | 日频 | 是 | 无 |
| turnoverAmount | number | 成交额 | 源口径 | 是 | 10523.0 | sum(daily.amount) | 日频 | 是 | 无 |
| prevTradeDate | string(date) | 上一交易日 | - | 是 | 2026-04-27 | trade_cal | 日频 | 是 | 无 |
| rangeType | enum | 1m / 3m | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.19 MoneyFlowSummary

**对象定义**：大盘资金净流入、分单结构和历史资金流。  
**所属系统**：资金流服务  
**使用页面和模块**：大盘资金流向  
**数据来源**：raw_tushare.moneyflow_mkt_dc  
**更新频率**：盘后/按源；实时源接入后可盘中刷新  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：正数净流入红色，负数净流出绿色；主趋势线白色，Tooltip 正负红绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| todayNetInflowAmount | number | 今日主力净流入 | 元 | 是 | 1211718400 | moneyflow_mkt_dc.net_amount | 盘后/按源 | 是 | 正红负绿 |
| previousTradeDate | string(date) | 上一交易日 | - | 是 | 2026-04-27 | trade_cal | 日频 | 是 | 无 |
| previousNetInflowAmount | number | 上一交易日主力净流入 | 元 | 是 | -3910650112 | 历史 net_amount | 盘后 | 是 | 正红负绿 |
| superLargeOrderNetInflow | number | 超大单净流入 | 元 | 是 | 22524846080 | buy_elg_amount | 盘后 | 是 | 正红负绿 |
| largeOrderNetInflow | number | 大单净流入 | 元 | 是 | 5433212928 | buy_lg_amount | 盘后 | 是 | 正红负绿 |
| mediumOrderNetInflow | number | 中单净流入 | 元 | 是 | -1203000000 | buy_md_amount | 盘后 | 是 | 正红负绿 |
| smallOrderNetInflow | number | 小单净流入 | 元 | 是 | -2203000000 | buy_sm_amount | 盘后 | 是 | 正红负绿 |
| historyPoints | HistoricalMoneyFlowPoint[] | 历史资金净流入 | - | 是 | [...] | moneyflow_mkt_dc | 日频 | 是 | Tooltip 红绿 |
| rangeType | enum | 历史区间 | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.20 HistoricalMoneyFlowPoint

**对象定义**：历史大盘资金净流入趋势点。  
**所属系统**：资金流服务  
**使用页面和模块**：大盘资金流历史趋势图  
**数据来源**：moneyflow_mkt_dc.net_amount  
**更新频率**：日频/盘后  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：正数净流入红色、负数净流出绿色；前端主趋势线白色，Tooltip 正负红绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | moneyflow_mkt_dc.trade_date | 日频 | 是 | 无 |
| netInflowAmount | number | 主力净流入金额；正为净流入，负为净流出 | 元 | 是 | 1211718400 | moneyflow_mkt_dc.net_amount | 日频 | 是 | 正红负绿 |
| rangeType | enum | 1m / 3m | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.21 LimitUpSummary

**对象定义**：涨跌停统计、分布和历史柱图聚合对象。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：涨跌停统计与分布  
**数据来源**：limit_list_d，必要时 daily + stk_limit 辅助  
**更新频率**：按源；盘后固定  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨停红、跌停绿、炸板中性/警示色。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | limit_list_d.trade_date | 日频 | 是 | 无 |
| limitUpCount | integer | 涨停家数 | 只 | 是 | 59 | limit='U' | 按源 | 是 | 红 |
| limitDownCount | integer | 跌停家数 | 只 | 是 | 8 | limit='D' | 按源 | 是 | 绿 |
| brokenLimitCount | integer | 炸板家数 | 只 | 是 | 27 | limit='Z' 或业务规则 | 按源 | 是 | 警示/中性 |
| touchedLimitUpCount | integer | 触及涨停家数 | 只 | 是 | 86 | limitUpCount + brokenLimitCount | 按源 | 是 | 红/中性 |
| sealRate | number | 封板率 | ratio | 是 | 0.686 | 派生 | 按源 | 是 | 无 |
| highestStreakLevel | integer | 最高连板层级 | 板 | 是 | 6 | max(limit_times) | 按源 | 是 | 红强调 |
| distribution | LimitUpDistribution | 当日分布结构 | - | 是 | {...} | 聚合 | 按源 | 是 | 涨停红跌停绿 |
| historyPoints | HistoricalLimitUpDownPoint[] | 历史组合柱图 | - | 是 | [...] | 历史聚合 | 日频 | 是 | 涨停红跌停绿 |
| rangeType | enum | 历史区间 | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.22 HistoricalLimitUpDownPoint

**对象定义**：历史涨跌停组合柱图点。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：涨跌停历史组合柱图  
**数据来源**：limit_list_d 历史聚合  
**更新频率**：日频  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：涨停柱红、跌停柱绿、炸板柱中性/警示。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | limit_list_d.trade_date | 日频 | 是 | 无 |
| limitUpCount | integer | 涨停家数 | 只 | 是 | 59 | limit='U' | 日频 | 是 | 红柱 |
| limitDownCount | integer | 跌停家数 | 只 | 是 | 8 | limit='D' | 日频 | 是 | 绿柱 |
| brokenLimitCount | integer | 炸板家数 | 只 | 是 | 27 | limit='Z' 或业务规则 | 日频 | 是 | 中性/警示 |
| rangeType | enum | 1m / 3m | - | 是 | 1m | 请求参数 | 请求级 | 是 | 无 |

### 3.23 LimitUpDistribution

**对象定义**：当日涨跌停分布结构对象；v0.4 改造为图表数据结构，不再是普通列表。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：涨跌停统计与分布  
**数据来源**：limit_list_d + dc_index/dc_member 或股票行业映射  
**更新频率**：按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：分布项中涨停红、跌停绿、炸板中性/警示。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bySector | LimitUpDistributionItem[] | 按板块分布 | - | 是 | [...] | limit_list_d + dc_member | 按源 | 是 | 红/绿 |
| byLimitType | LimitUpDistributionItem[] | 按涨跌停类型分布 | - | 是 | [...] | limit_list_d.limit | 按源 | 是 | 红/绿 |
| byStreakLevel | LimitUpDistributionItem[] | 按连板层级分布 | - | 是 | [...] | limit_times | 按源 | 是 | 红 |
| byBrokenLimit | LimitUpDistributionItem[] | 炸板分布 | - | 是 | [...] | open_times / limit='Z' | 按源 | 是 | 中性/警示 |
| distributionItems | LimitUpDistributionItem[] | 默认合并展示项 | - | 是 | [...] | 聚合 | 按源 | 是 | 红/绿 |

### 3.24 LimitUpDistributionItem

**对象定义**：涨跌停分布单项。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：涨跌停分布图、Tooltip  
**数据来源**：limit_list_d 聚合  
**更新频率**：按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：数量字段按涨停/跌停/炸板映射。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| categoryCode | string | 分类代码 | - | 是 | BK1184.DC | 板块/类型/层级 | 按源 | 是 | 无 |
| categoryName | string | 分类名称 | - | 是 | 人形机器人 | 聚合 | 按源 | 是 | 无 |
| categoryType | enum | SECTOR / LIMIT_TYPE / STREAK_LEVEL / BROKEN_LIMIT | - | 是 | SECTOR | 聚合 | 按源 | 是 | 无 |
| limitUpCount | integer | 涨停数量 | 只 | 是 | 6 | 聚合 | 按源 | 是 | 红 |
| limitDownCount | integer | 跌停数量 | 只 | 是 | 1 | 聚合 | 按源 | 是 | 绿 |
| brokenLimitCount | integer | 炸板数量 | 只 | 是 | 2 | 聚合 | 按源 | 是 | 中性/警示 |
| relatedStocks | LimitUpStreakStock[] | 相关股票 | - | 否 | [...] | limit_list_d | 按源 | 是 | 股票涨跌红绿 |

### 3.25 LimitUpStreakLadder

**对象定义**：横向连板天梯根对象。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：连板天梯，独占一行横向布局  
**数据来源**：limit_list_d.limit_times  
**更新频率**：按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：层级强调红色，股票涨跌按 direction。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | limit_list_d | 日频 | 是 | 无 |
| highestLevel | integer | 最高连板层级 | 板 | 是 | 6 | max(limit_times) | 按源 | 是 | 红强调 |
| levels | LimitUpStreakLevel[] | 连板层级 | - | 是 | [...] | 聚合 | 按源 | 是 | 层级红强调 |
| asOf | datetime | 数据时间 | - | 是 | 2026-04-28T15:10:00+08:00 | 数据基座 | 按源 | 是 | 无 |

### 3.26 LimitUpStreakLevel

**对象定义**：连板天梯层级。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：横向连板天梯每列  
**数据来源**：limit_list_d.limit_times  
**更新频率**：按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：层级标签可用涨停红强调。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| level | integer | 连板层级 | 板 | 是 | 3 | limit_times | 按源 | 是 | 红强调 |
| levelLabel | string | 层级名称 | - | 是 | 三板 | 派生 | 按源 | 是 | 红强调 |
| stockCount | integer | 该层级股票数量 | 只 | 是 | 5 | 聚合计数 | 按源 | 是 | 无 |
| stocks | LimitUpStreakStock[] | 股票列表 | - | 是 | [...] | limit_list_d | 按源 | 是 | 股票涨跌红绿 |

### 3.27 LimitUpStreakStock

**对象定义**：连板天梯股票卡片。  
**所属系统**：涨跌停统计服务  
**使用页面和模块**：连板天梯  
**数据来源**：limit_list_d，行情字段可关联 daily  
**更新频率**：按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：changePct 正红负绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| stockCode | string | 股票代码 | - | 是 | 002888.SZ | limit_list_d.ts_code | 按源 | 是 | 无 |
| stockName | string | 股票名称 | - | 是 | 示例股份 | limit_list_d.name | 按源 | 是 | 无 |
| sectorName | string | 所属板块/行业 | - | 否 | 机器人 | limit_list_d.industry / 板块映射 | 按源 | 是 | 无 |
| latestPrice | number | 最新价/收盘价 | 元 | 否 | 18.36 | daily.close 或 limit_list_d.close | 按源 | 是 | 无 |
| changePct | number | 涨跌幅 | % | 是 | 10.01 | daily.pct_chg / limit_list_d.pct_chg | 按源 | 是 | 正红负绿 |
| direction | enum | 涨跌方向 | - | 是 | UP | changePct 派生 | 按源 | 是 | 必须 |
| openTimes | integer | 开板次数 | 次 | 否 | 1 | limit_list_d.open_times | 按源 | 是 | 无 |
| sealedAmount | number | 封单金额 | 源口径 | 否 | 328000000 | limit_list_d.fd_amount | 按源 | 是 | 无 |
| firstLimitTime | string | 首次封板时间 | - | 否 | 09:42:15 | limit_list_d.first_time | 按源 | 是 | 无 |

### 3.28 SectorRankItem

**对象定义**：行业/概念/地域板块榜单项。  
**所属系统**：板块行情服务  
**使用页面和模块**：板块速览、热力图、板块榜  
**数据来源**：dc_index、dc_daily、moneyflow_ind_dc  
**更新频率**：日频/按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：changePct 正红负绿；资金正红负绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rank | integer | 排名 | - | 是 | 1 | 排序派生 | 按源 | 是 | 无 |
| sectorId | string | 板块代码 | - | 是 | BK1184.DC | dc_index.ts_code | 按源 | 是 | 无 |
| sectorName | string | 板块名称 | - | 是 | 人形机器人 | dc_index.name | 按源 | 是 | 无 |
| sectorType | enum | INDUSTRY / CONCEPT / REGION | - | 是 | CONCEPT | dc_index.idx_type | 按源 | 是 | 无 |
| changePct | number | 涨跌幅 | % | 是 | 4.37 | dc_daily.pct_change | 按源 | 是 | 正红负绿 |
| amount | number | 成交额 | 元 | 否 | 987654321 | dc_daily.amount | 按源 | 是 | 无 |
| turnoverRate | number | 换手率 | % | 否 | 4.08 | dc_daily.turnover_rate | 按源 | 是 | 无 |
| upCount | integer | 上涨家数 | 只 | 否 | 32 | dc_index.up_num | 按源 | 是 | 红 |
| downCount | integer | 下跌家数 | 只 | 否 | 62 | dc_index.down_num | 按源 | 是 | 绿 |
| mainNetInflow | number | 主力净流入 | 元 | 否 | 3056382208 | moneyflow_ind_dc.net_amount | 盘后 | 是 | 正红负绿 |
| leadingStockCode | string | 领涨股代码 | - | 否 | 002117.SZ | dc_index.leading_code | 按源 | 是 | 无 |
| leadingStockName | string | 领涨股名称 | - | 否 | 东港股份 | dc_index.leading | 按源 | 是 | 无 |
| leadingStockChangePct | number | 领涨股涨跌幅 | % | 否 | 10.02 | dc_index.leading_pct | 按源 | 是 | 正红负绿 |

### 3.29 HeatMapItem

**对象定义**：板块热力图节点。  
**所属系统**：板块热力图服务  
**使用页面和模块**：板块速览 / 热力图入口或展开  
**数据来源**：dc_index、dc_daily、moneyflow_ind_dc  
**更新频率**：日频/按源  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：颜色按 changePct / direction。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | string | 节点 ID | - | 是 | BK1184.DC | dc_index.ts_code | 按源 | 是 | 无 |
| name | string | 节点名称 | - | 是 | 人形机器人 | dc_index.name | 按源 | 是 | 无 |
| type | enum | INDUSTRY / CONCEPT / REGION | - | 是 | CONCEPT | dc_index.idx_type | 按源 | 是 | 无 |
| changePct | number | 涨跌幅 | % | 是 | 4.37 | dc_daily.pct_change | 按源 | 是 | 正红负绿 |
| direction | enum | 涨跌方向 | - | 是 | UP | 派生 | 按源 | 是 | 必须 |
| amount | number | 成交额 | 元 | 否 | 987654321 | dc_daily.amount | 按源 | 是 | 无 |
| mainNetInflow | number | 主力净流入 | 元 | 否 | 3056382208 | moneyflow_ind_dc.net_amount | 盘后 | 否 | 正红负绿 |
| sizeMetric | enum | 面积指标 | - | 是 | AMOUNT | 请求参数/默认 | 请求级 | 是 | 无 |
| colorMetric | enum | 颜色指标 | - | 是 | CHANGE_PCT | 请求参数/默认 | 请求级 | 是 | 无 |

### 3.30 StockRankItem

**对象定义**：榜单股票项。P0 默认使用东方财富热榜，也可扩展为行情榜。  
**所属系统**：榜单服务  
**使用页面和模块**：榜单速览  
**数据来源**：dc_hot；如做涨幅/成交额/换手榜，可由 daily/daily_basic 派生  
**更新频率**：dc_hot 日内多次  
**是否 P0 必需**：是  
**与红涨绿跌显示的关系**：changePct 正红负绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tradeDate | string(date) | 交易日 | - | 是 | 2026-04-28 | dc_hot.trade_date | 日内 | 是 | 无 |
| rankType | enum | POPULAR / SURGE / GAINER / LOSER / AMOUNT / TURNOVER / VOLUME_RATIO | - | 是 | POPULAR | 请求参数/派生 | 日内 | 是 | 无 |
| stockCode | string | 股票代码 | - | 是 | 601099.SH | dc_hot.ts_code | 日内 | 是 | 无 |
| stockName | string | 股票名称 | - | 是 | 太平洋 | dc_hot.ts_name | 日内 | 是 | 无 |
| rank | integer | 排名/热度 | - | 是 | 1 | dc_hot.rank | 日内 | 是 | 无 |
| price | number | 当前价 | 元 | 否 | 4.82 | dc_hot.current_price | 日内 | 是 | 无 |
| changePct | number | 涨跌幅 | % | 否 | 3.21 | dc_hot.pct_change | 日内 | 是 | 正红负绿 |
| direction | enum | 涨跌方向 | - | 是 | UP | 派生 | 日内 | 是 | 必须 |
| rankTime | string | 榜单时间 | - | 是 | 22:30:00 | dc_hot.rank_time | 日内 | 是 | 无 |
| dataType | string | 数据类型 | - | 否 | A股市场 | dc_hot.data_type | 日内 | 是 | 无 |


---

## 4. 附录 A：字段名词表

| 字段名 | 统一中文名 | 单位/口径 | 常见来源 |
| --- | --- | --- | --- |
| turnover_rate | 换手率 | % | daily_basic、dc_index、dc_daily |
| volume_ratio | 量比 | 倍 | daily_basic |
| pct_chg | 涨跌幅 | % | daily、index_daily |
| pct_change | 涨跌幅 | % | dc_index、dc_daily、moneyflow_mkt_dc |
| amount | 成交额 | 按源口径；daily 为千元，dc_daily/stk_mins 为元 | daily、dc_daily、stk_mins |
| vol | 成交量 | 按源口径；daily 为手，stk_mins/dc_daily 为股 | daily、stk_mins、dc_daily |
| net_amount | 主力净流入 | 元，moneyflow_dc 个股为万元 | moneyflow_mkt_dc、moneyflow_ind_dc、moneyflow_dc |
| buy_elg_amount | 超大单净流入 | 元/万元按源 | 资金流数据 |
| buy_lg_amount | 大单净流入 | 元/万元按源 | 资金流数据 |
| buy_md_amount | 中单净流入 | 元/万元按源 | 资金流数据 |
| buy_sm_amount | 小单净流入 | 元/万元按源 | 资金流数据 |
| up_limit | 涨停价 | 元 | stk_limit |
| down_limit | 跌停价 | 元 | stk_limit |
| limit | 涨跌停状态 | U/D/Z 等，按源口径 | limit_list_d |
| open_times | 开板次数 | 次 | limit_list_d |
| limit_times | 连板数 | 板 | limit_list_d |
| first_time | 首次封板时间 | 源时间字符串 | limit_list_d |
| fd_amount | 封单金额 | 按源口径 | limit_list_d |
| idx_type | 板块类型 | 行业/概念/地域 | dc_index、dc_daily |
| leading | 领涨股票名称 | - | dc_index |
| leading_code | 领涨股票代码 | - | dc_index |
| leading_pct | 领涨股票涨跌幅 | % | dc_index |
| up_num | 上涨家数 | 只 | dc_index |
| down_num | 下跌家数 | 只 | dc_index |
| rank_time | 榜单时间 | 源时间字符串 | dc_hot |
| current_price | 当前价 | 元 | dc_hot |

---

## 5. 本轮新增字段清单

| 对象 | 新增字段 |
| --- | --- |
| MarketBreadth | historyPoints、rangeType |
| HistoricalBreadthPoint | 新增对象 |
| MarketStyle | medianChangePct、historyPoints、rangeType |
| MarketStyleHistoryPoint | 新增对象 |
| TurnoverSummary | todayTurnoverAmount、previousTradeDate、previousTurnoverAmount、turnoverChangeAmount、turnoverChangePct、ma5TurnoverAmount、ma20TurnoverAmount、intradayPoints、historyPoints |
| IntradayTurnoverPoint | 新增对象 |
| HistoricalTurnoverPoint | 明确 prevTradeDate、rangeType |
| MoneyFlowSummary | todayNetInflowAmount、previousTradeDate、previousNetInflowAmount、superLargeOrderNetInflow、largeOrderNetInflow、mediumOrderNetInflow、smallOrderNetInflow、historyPoints |
| HistoricalMoneyFlowPoint | 新增对象 |
| LimitUpSummary | brokenLimitCount、distribution、historyPoints |
| HistoricalLimitUpDownPoint | 新增对象 |
| LimitUpDistribution | bySector、byLimitType、byStreakLevel、byBrokenLimit、distributionItems |
| LimitUpStreakLadder | levels[].stockCount |
| LimitUpStreakLevel | 新增对象 |
| LimitUpStreakStock | 新增对象 |

## 6. 本轮修改字段清单

| 原字段/对象 | 修改后 | 说明 |
| --- | --- | --- |
| totalAmount | todayTurnoverAmount | 成交额字段更明确 |
| prevTotalAmount | previousTurnoverAmount | 与上一交易日字段统一 |
| amountChange | turnoverChangeAmount | 避免金额泛化 |
| amountChangePct | turnoverChangePct | 与成交额对象一致 |
| mainNetInflow | todayNetInflowAmount | 首页资金模块聚焦今日净流入 |
| failedLimitUpCount | brokenLimitCount | 与“炸板”展示更一致，可保留 alias |
| LimitUpDistribution 列表 | 图表结构对象 | 支持 sector/type/streak/broken 多维分布 |
| LimitUpStreakLadder[] | LimitUpStreakLadder.levels[] | 支持横向天梯每层 stockCount |

## 7. 本轮废弃或不再展示字段清单

| 字段 | 处理 |
| --- | --- |
| equalWeightedChangePct | 不再作为市场风格模块展示字段 |
| largeSmallRatioText / 大小盘解释性文字 | 不再作为正文展示，说明进入 HelpTooltip |
| marketTemperatureScore | 市场总览禁止 |
| marketSentimentScore | 市场总览禁止 |
| capitalScore | 市场总览禁止 |
| riskIndexScore | 市场总览禁止 |
| buySuggestion / sellSuggestion / tomorrowPrediction | 市场总览禁止 |

## 8. 市场总览页面模块与 API 字段映射表

| 页面模块 | 聚合字段 | 模块接口 | 关键对象 |
| --- | --- | --- | --- |
| TopMarketBar | topMarketBar、dataStatus | /api/index/summary | TopMarketBarData |
| Breadcrumb | breadcrumb | 聚合返回 | BreadcrumbItem |
| ShortcutBar | quickEntries | /api/settings/quick-entry | QuickEntry |
| 今日市场客观总结 | marketSummary | 聚合返回 | MarketObjectiveSummary |
| 主要指数 | indices | /api/index/summary | IndexSnapshot |
| 涨跌分布 | breadth、breadth.historyPoints | /api/market/breadth | MarketBreadth |
| 市场风格 | style、style.historyPoints | /api/market/style | MarketStyle |
| 成交额总览 | turnover、turnover.intradayPoints、turnover.historyPoints | /api/market/turnover | TurnoverSummary |
| 大盘资金流向 | moneyFlow、moneyFlow.historyPoints | /api/moneyflow/market | MoneyFlowSummary |
| 涨跌停统计与分布 | limitUp、limitUp.distribution、limitUp.historyPoints | /api/limitup/summary | LimitUpSummary |
| 连板天梯 | streakLadder.levels[] | /api/limitup/streak-ladder | LimitUpStreakLadder |
| 板块速览 | sectorOverview | /api/sector/top | SectorRankItem |
| 榜单速览 | leaderboards | /api/leaderboard/stock | StockRankItem |

## 9. 给 02 HTML Showcase 的 Mock 数据建议

1. 历史序列默认返回 `rangeType=1m`，每个序列准备 20-23 个交易日点。
2. `rangeType=3m` 作为模块局部刷新 mock，准备 60-66 个交易日点。
3. 日内成交额至少包含 `09:30`、`11:30`、`15:00` 三个坐标点，可额外增加 `10:30`、`13:30`、`14:30`。
4. 资金流历史点正负交错，体现 Tooltip 正红负绿。
5. 涨跌停历史柱图要同时包含涨停、跌停、炸板。
6. 连板天梯至少包含：首板、二板、三板、四板、五板及以上，每层必须有 `stockCount`。
7. 不得在快捷入口 mock 中放市场温度/情绪/风险分数。

## 10. 给 03 组件 Props 的字段映射建议

| 组件 | Props |
| --- | --- |
| HistoricalBreadthChart | points: HistoricalBreadthPoint[]、rangeType、onRangeChange |
| MarketStyleTrendChart | points: MarketStyleHistoryPoint[]、rangeType |
| IntradayTurnoverChart | points: IntradayTurnoverPoint[]、xTicks:['09:30','11:30','15:00'] |
| HistoricalTurnoverChart | points: HistoricalTurnoverPoint[]、rangeType |
| MoneyFlowTrendChart | points: HistoricalMoneyFlowPoint[]、zeroAxis:true |
| LimitUpDownBarChart | points: HistoricalLimitUpDownPoint[]、rangeType |
| LimitUpDistributionChart | distribution: LimitUpDistribution |
| HorizontalStreakLadder | levels: LimitUpStreakLevel[] |
| StreakStockCard | stock: LimitUpStreakStock |

## 11. 给 05 Codex 提示词的 API 约束

1. 以 `GET /api/market/home-overview` 的 mock 作为 `market-overview-v1.1.html` 数据根对象。
2. 不允许新增市场温度、情绪指数、资金面分数、风险指数展示字段。
3. 历史图表统一支持 `1m/3m` 切换。
4. 日内成交额图必须显示 `09:30`、`11:30`、`15:00`。
5. 资金流趋势主线白色；Tooltip 正数红色、负数绿色。
6. 涨跌停历史柱图：涨停红、跌停绿、炸板使用中性/警示色。
7. 连板天梯横向布局，每层必须显示 `stockCount`。
8. 所有涨跌数字使用 `direction` 或正负值按红涨绿跌渲染。

## 12. P0 已具备字段

| 能力 | 数据来源 |
| --- | --- |
| 交易日、上一交易日 | trade_cal |
| 指数行情 | index_daily |
| 个股日线、涨跌分布、历史涨跌家数 | daily |
| 每日指标、换手率、量比 | daily_basic |
| 历史成交额 | daily.amount 聚合 |
| 大盘资金流与历史资金流 | moneyflow_mkt_dc |
| 涨停、跌停、炸板、连板 | limit_list_d |
| 涨跌停价格辅助 | stk_limit |
| 东方财富板块 | dc_index、dc_member、dc_daily |
| 板块资金流 | moneyflow_ind_dc |
| 东方财富热榜 | dc_hot |

## 13. P0 暂缺字段

| 字段/能力 | 说明 |
| --- | --- |
| 全市场日内累计成交额 | 需要分钟级全市场聚合视图，不能逐次实时扫全量分钟表 |
| 实时资金流 | moneyflow_mkt_dc 为盘后/按源；盘中资金需另接实时源 |
| 涨跌停盘中实时变化 | limit_list_d 更适合盘后/按源；实时封板过程需实时源 |
| 天地板/地天板稳定口径 | 需结合 high/low/open/close 与涨跌停价规则 |
| 板块内平盘家数 | dc_index 只提供 up_num/down_num，如需精确需 dc_member + daily 聚合 |
| 3个月全量历史序列缓存 | 需要预计算或物化视图 |

## 14. 需要数据基座补充的字段/视图

| 视图 | 用途 |
| --- | --- |
| wealth_market_breadth_history_snapshot | 1m/3m 涨跌家数历史 |
| wealth_market_style_history_snapshot | 大盘/小盘/中位涨跌幅历史 |
| wealth_intraday_turnover_snapshot | 当日累计成交额时间序列 |
| wealth_turnover_history_snapshot | 历史成交额 1m/3m |
| wealth_moneyflow_market_history_snapshot | 历史大盘资金流 |
| wealth_limitup_history_snapshot | 历史涨跌停/炸板 |
| wealth_limitup_distribution_snapshot | 当日涨跌停分布 |
| wealth_limitup_streak_ladder_snapshot | 横向连板天梯 |
| wealth_sector_rank_snapshot | 东方财富板块榜 |
| wealth_stock_hot_rank_snapshot | 东方财富热榜 |

## 15. 待产品总控确认问题

1. `brokenLimitCount` 是否统一替换 `failedLimitUpCount`，还是保留双字段兼容一期实现？
2. 天地板/地天板是否进入 v1.1 展示，还是保留在后续涨跌停详情页？
3. 日内累计成交额在没有实时源时，是否允许用最近盘后数据生成占位曲线？
4. 市场风格代表指数：大盘是否固定沪深300，小盘是否固定中证1000？
5. 东方财富热榜是否替代传统涨跌幅榜作为首页默认榜单，还是两类榜单并存？
