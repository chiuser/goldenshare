# 财势乾坤｜P0 数据字典 v0.4

建议保存路径：`/docs/wealth/api/p0-data-dictionary.md`  
公共区建议保存路径：`财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4.md`  
负责人：`04_API 契约与数据字典`  
版本：`v0.4`  
状态：`HTML Review v2 全量修订稿`  
更新时间：`2026-05-07`

---

## 本轮实际读取的公共区文件

| 序号 | 文件名 | 实际读取到的版本 / 状态 |
|---:|---|---|
| 1 | `财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2`，Review 草案 v0.2 |
| 2 | `市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2`，Review 草案 |
| 3 | `02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1` |
| 4 | `04-component-guidelines.md` | `P0 组件库与交互组件方案 v0.3`，Draft v0.3 |
| 5 | `p0-data-dictionary-v0.4.md` | `P0 数据字典 v0.4`，HTML Review v1 补字段修订稿 |
| 6 | `market-overview-api-v0.4.md` | `市场总览 API 草案 v0.4`，HTML Review v1 补字段修订稿 |
| 7 | `market-overview-html-review-v2.md` | `市场总览页review-v2` |
| 8 | `市场总览html_review_v_2_总控解读与变更单.md` | `市场总览 HTML Review v2｜总控解读与变更单`，目标 `market-overview-v1.2.html` |
| 9 | `tushare接口文档/README.md` | Tushare 接口说明目录（本地镜像） |
| 10 | `tushare接口文档/docs_index.csv` | Tushare 文档总索引，含 `doc_id/title/api_name/local_path` |


---

## 0. 本轮 Review v2 修订范围

本版是在 `p0-data-dictionary-v0.4.md` 基础上，按 `market-overview-html-review-v2.md` 和总控变更单做**限定范围修订**。本轮只处理 Review v2 明确点名的四个区域：

1. 今日市场客观总结与主要指数左右结构所需字段；
2. 榜单速览 Top10 表格字段；
3. 涨跌停统计与分布 2×2 区域字段；
4. 板块速览 4列×2行榜单矩阵 + 右侧跨两行 5×4 热力图字段。

未被 Review v2 点名的模块，本轮不主动重构，包括：市场温度与情绪、大盘资金流、成交额总览、市场风格、连板天梯、路由、TopMarketBar、Breadcrumb、ShortcutBar。

### 0.1 产品边界

1. 市场总览是 A 股市场客观事实总览页。
2. 市场总览属于乾坤行情，不是独立一级菜单。
3. 市场总览不展示市场温度、市场情绪指数、资金面分数、风险指数作为核心结论。
4. 不返回 `marketTemperatureScore`、`marketSentimentScore`、`capitalScore`、`riskIndexScore`。
5. 不返回 `buySuggestion`、`sellSuggestion`、`positionSuggestion`、`tomorrowPrediction`、`subjectiveMarketConclusion`。
6. API 使用财势乾坤业务对象和业务字段组织，不复刻 Tushare API。
7. 所有行情字段必须支持红涨绿跌：上涨红、下跌绿、平盘灰。

---

## 1. 字段命名、单位与红涨绿跌规则

| 项目 | 规则 |
|---|---|
| API 字段命名 | `lowerCamelCase`，使用财势乾坤业务命名 |
| 源字段名 | 数据字典记录 Tushare / PostgreSQL 落库字段名 |
| 日期 | API 返回 `YYYY-MM-DD`；源字段可为 `YYYYMMDD` |
| 时间 | API 返回 `HH:mm` 或 ISO 8601，按字段说明标注 |
| 金额单位 | 默认保持 Tushare / PostgreSQL 落库口径；字段表必须写明单位 |
| 成交量单位 | 默认保持 Tushare / PostgreSQL 落库口径；字段表必须写明单位 |
| 涨跌幅 | 百分数数值，例如 `1.23` 表示 `1.23%` |
| `direction` | `UP` / `DOWN` / `FLAT` / `UNKNOWN` |
| 红涨绿跌 | `UP=红色`、`DOWN=绿色`、`FLAT=灰色` |

### 1.1 Review v2 点名模块的颜色规则

| 场景 | 颜色规则 |
|---|---|
| 榜单 `latestPrice` | 跟随 `direction`，上涨红、下跌绿、平盘灰 |
| 榜单 `changePct` | 正红、负绿、零灰 |
| 榜单 `turnoverRate`、`volumeRatio`、`volume`、`amount` | 中性色 |
| 涨停统计 | 涨停红、跌停绿、炸板使用中性/警示色 |
| 板块榜 `changePct` | 正红、负绿 |
| 热力图 | `changePct` 正红、负绿，深浅按绝对值或分位数 |

---

## 2. Tushare / 落库数据集参考

| 业务域 | 主数据集 / 落库表 | 关键字段 | 本轮用途 |
|---|---|---|---|
| 股票基础 | `stock_basic` / `raw_tushare.stock_basic` | `ts_code`、`name`、`industry`、`market`、`exchange` | 股票代码、名称、行业兜底 |
| 个股日线 | `daily` / `raw_tushare.daily` | `close`、`pct_chg`、`vol`、`amount` | 榜单扩展字段：最新价、涨跌幅、成交量、成交额 |
| 每日指标 | `daily_basic` / `raw_tushare.daily_basic` | `turnover_rate`、`volume_ratio` | 榜单 Top10 的换手率、量比 |
| 指数日线 | `index_daily` / `raw_tushare.index_daily` | `close`、`pct_chg`、`amount` | 主要指数 2 行 × 5 个 |
| 涨跌停 / 炸板 | `limit_list_d` / `raw_tushare.limit_list_d` | `limit`、`open_times`、`limit_times`、`first_time`、`fd_amount` | 涨跌停 8 卡、今日/昨日结构 |
| 涨跌停价格 | `stk_limit` / `raw_tushare.stk_limit` | `up_limit`、`down_limit` | 涨跌停辅助校验 |
| 东方财富板块列表 | `dc_index` / `raw_tushare.dc_index` | `ts_code`、`name`、`pct_change`、`up_num`、`down_num`、`idx_type`、`leading`、`leading_code`、`leading_pct` | 板块 Top5、热力图 |
| 东方财富板块成分 | `dc_member` / `raw_tushare.dc_member` | `ts_code`、`con_code`、`name` | 板块分布、热力图扩展 |
| 东方财富板块日线 | `dc_daily` / `raw_tushare.dc_daily` | `pct_change`、`amount`、`turnover_rate` | 板块涨跌幅、成交额 |
| 东方财富板块资金流 | `moneyflow_ind_dc` / `raw_tushare.moneyflow_ind_dc` | `net_amount`、`rank` | 资金流入/流出 Top5、热力图净流入 |
| 东方财富热榜 | `dc_hot` / `raw_tushare.dc_hot` | `rank`、`ts_code`、`ts_name`、`pct_change`、`current_price`、`rank_time` | 榜单速览基础排名 |
| 交易日 | `trade_cal` / `raw_tushare.trade_cal` | `cal_date`、`is_open`、`pretrade_date` | 当前/上一交易日；`is_open` 已落库为 boolean |

---

## 3. 对象总览

| 对象 | P0 用途 | 本轮是否修改 |
|---|---|---|
| TradingDay | 当前交易日和上一交易日 | 否 |
| DataSourceStatus | 数据状态 | 否 |
| TopMarketBarData | 顶部栏 | 否 |
| GlobalSystemEntry | 顶部一级系统入口 | 否 |
| BreadcrumbItem | 面包屑 | 否 |
| QuickEntry | 页面快捷入口 | 否 |
| UserShortcutStatus | 用户快捷状态 | 否 |
| MarketOverview | 聚合根对象 | 是，仅更新 `marketSummary`、`indices`、`leaderboards`、`limitUp`、`sectorOverview` |
| MarketObjectiveSummary | 今日市场客观总结 | 是，确认 5 个事实卡 + 说明卡 |
| MarketSummaryCard | 今日市场事实卡 | 新增 |
| MarketSummaryTextCard | 今日市场说明卡 | 新增 |
| IndexSnapshot | 主要指数 | 是，确认 `gridRow/gridCol` 可选支持 2×5 |
| MarketBreadth | 涨跌分布 | 否 |
| MarketStyle | 市场风格 | 否 |
| TurnoverSummary | 成交额总览 | 否 |
| MoneyFlowSummary | 大盘资金流 | 否 |
| LimitUpSummary | 涨跌停统计根对象 | 是，补 2×2 结构 |
| LimitUpSummaryCard | 涨跌停统计卡 | 新增 |
| LimitUpDayDistribution | 今日/昨日涨跌停结构 | 新增 |
| LimitUpSectorDistributionItem | 涨停板块分布项 | 新增 |
| LimitDownBrokenStructureItem | 跌停/炸板结构项 | 新增 |
| HistoricalLimitUpDownPoint | 历史涨跌停柱图点 | 是，确认 Review v2 要求字段 |
| LimitUpStreakLadder | 连板天梯 | 否 |
| SectorOverview | 板块速览根对象 | 新增 |
| SectorRankItem | Top5 板块项 | 是，字段补齐 |
| HeatMapItem | 5×4 热力图项 | 是，字段补齐 |
| StockRankItem | 榜单 Top10 股票项 | 是，补换手率、量比、成交量、成交额 |

---

## 4. 基础对象字典

### 4.1 TradingDay

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradeDate` | string(date) | 当前交易日 | - | 是 | `2026-04-28` | `trade_cal.cal_date` | 日频 | 是 | 无 |
| `prevTradeDate` | string(date) | 上一交易日 | - | 是 | `2026-04-27` | `trade_cal.pretrade_date` | 日频 | 是 | 无 |
| `market` | enum | 市场，P0 固定 `CN_A` | - | 是 | `CN_A` | 系统配置 | 固定 | 是 | 无 |
| `isTradingDay` | boolean | 是否交易日 | - | 是 | `true` | `trade_cal.is_open`，已落库 boolean | 日频 | 是 | 无 |
| `sessionStatus` | enum | 交易阶段 | - | 是 | `CLOSED` | 服务端派生 | 分钟 | 是 | 无 |
| `timezone` | string | 时区 | - | 是 | `Asia/Shanghai` | 系统配置 | 固定 | 是 | 无 |

### 4.2 DataSourceStatus

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `sourceId` | string | 数据源 ID | - | 是 | `tushare_daily` | 配置 | 低频 | 是 | 无 |
| `dataset` | string | 数据集 | - | 是 | `daily` | 同步任务 | 任务级 | 是 | 无 |
| `tableName` | string | 落库表 | - | 是 | `raw_tushare.daily` | 数据基座 | 低频 | 是 | 无 |
| `dataDomain` | enum | 数据域 | - | 是 | `LEADERBOARD` | 配置 | 低频 | 是 | 无 |
| `status` | enum | 数据状态 | - | 是 | `READY` | 监控服务 | 分钟/任务 | 是 | 状态色 |
| `latestTradeDate` | string(date) | 最新交易日 | - | 否 | `2026-04-28` | `max(trade_date)` | 任务级 | 是 | 无 |
| `latestDataTime` | datetime | 最新同步时间 | - | 否 | `2026-04-28T17:10:00+08:00` | 同步任务 | 任务级 | 是 | 无 |
| `completenessPct` | number | 完整度 | % | 否 | `99.6` | 校验任务 | 任务级 | 是 | 无 |
| `message` | string | 状态说明 | - | 否 | `热榜为最新采集` | 监控服务 | 分钟 | 是 | 无 |

### 4.3 TopMarketBarData / GlobalSystemEntry / BreadcrumbItem / QuickEntry / UserShortcutStatus

本轮 Review v2 未点名这些对象，沿用 v0.4。为保持全量文档完整性，关键字段如下：

| 对象 | 字段 |
|---|---|
| `TopMarketBarData` | `brandName`、`activeSystemKey`、`globalEntries`、`indexTickers`、`tradingDay`、`dataStatus`、`userShortcutStatus` |
| `GlobalSystemEntry` | `key`、`title`、`route`、`active`、`enabled`、`sortOrder` |
| `BreadcrumbItem` | `label`、`route`、`current`、`disabled` |
| `QuickEntry` | `key`、`title`、`description`、`route`、`enabled`、`pendingCount`、`hasUpdate` |
| `UserShortcutStatus` | `watchCount`、`positionCount`、`activeAlertCount`、`unreadAlertCount` |

> `QuickEntry` 不得包含任何市场温度/情绪/资金面/风险分数。

---

## 5. Review v2 点名对象字典

### 5.1 MarketOverview

| 字段 | 类型 | 说明 | 必填 | 本轮是否修改 |
|---|---|---|---|---|
| `tradingDay` | TradingDay | 交易日 | 是 | 否 |
| `dataStatus` | DataSourceStatus[] | 数据状态 | 是 | 否 |
| `topMarketBar` | TopMarketBarData | 顶部栏 | 是 | 否 |
| `breadcrumb` | BreadcrumbItem[] | 面包屑 | 是 | 否 |
| `quickEntries` | QuickEntry[] | 快捷入口 | 是 | 否 |
| `marketSummary` | MarketObjectiveSummary | 今日市场客观总结 | 是 | 是 |
| `indices` | IndexSnapshot[] | 主要指数，支持 2×5 | 是 | 是 |
| `breadth` | MarketBreadth | 涨跌分布 | 是 | 否 |
| `style` | MarketStyle | 市场风格 | 是 | 否 |
| `turnover` | TurnoverSummary | 成交额 | 是 | 否 |
| `moneyFlow` | MoneyFlowSummary | 大盘资金流 | 是 | 否 |
| `limitUp` | LimitUpSummary | 涨跌停 2×2 | 是 | 是 |
| `streakLadder` | LimitUpStreakLadder | 连板天梯 | 是 | 否 |
| `sectorOverview` | SectorOverview | 板块矩阵 + 热力图 | 是 | 是 |
| `leaderboards` | object | 榜单 Top10 | 是 | 是 |

### 5.2 MarketObjectiveSummary

**对象定义**：今日市场客观总结。Review v2 要求与主要指数保持左右结构，左侧先展示 5 个事实卡片，再展示说明性文字卡片。  
**所属系统**：乾坤行情 / 聚合服务。  
**使用页面和模块**：今日市场客观总结。  
**数据来源**：聚合 `MarketBreadth`、`TurnoverSummary`、`MoneyFlowSummary`、`LimitUpSummary`。  
**P0 必需**：是。  
**红涨绿跌关系**：事实卡按 `direction` 或正负值显示。

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `layout` | enum | 布局，Review v2 固定左侧模块 | - | 是 | `LEFT_HALF` | 页面约束 | 低频 | 是 | 无 |
| `cards` | MarketSummaryCard[] | 5 个事实卡片 | - | 是 | `[...]` | 聚合 | 按源 | 是 | 按卡片 |
| `textCard` | MarketSummaryTextCard | 说明性文字卡片 | - | 是 | `Ellipsis` | 聚合/配置 | 按源 | 是 | 中性 |
| `asOf` | datetime | 数据时间 | - | 是 | `2026-04-28T15:10:00+08:00` | 聚合 | 按源 | 是 | 无 |
| `forbiddenConclusion` | boolean | 禁止主观结论 | - | 是 | `true` | 固定 | 固定 | 是 | 无 |

### 5.3 MarketSummaryCard

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `key` | string | 卡片 key | - | 是 | `riseCount` | 聚合配置 | 低频 | 是 | 无 |
| `label` | string | 展示名称 | - | 是 | `上涨家数` | 配置 | 低频 | 是 | 无 |
| `value` | number/string | 数值 | 按字段 | 是 | `3421` | 聚合 | 按源 | 是 | 按 direction |
| `unit` | string | 单位 | - | 否 | `只` | 配置 | 低频 | 是 | 无 |
| `direction` | enum | 显示方向 | - | 否 | `UP` | 派生 | 按源 | 是 | 必须 |
| `displayText` | string | 前端可直接展示文本 | - | 否 | `3421只` | 服务端可选 | 按源 | 否 | 按 direction |

### 5.4 MarketSummaryTextCard

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `title` | string | 说明卡标题 | - | 是 | `客观事实说明` | 配置 | 低频 | 是 | 无 |
| `content` | string | 说明文字，只描述事实口径，不给结论 | - | 是 | `本页仅展示A股市场客观运行事实，不构成投资建议。` | 配置 | 低频 | 是 | 无 |
| `tooltip` | string | hover 说明 | - | 否 | `指标口径说明` | 配置 | 低频 | 否 | 无 |

### 5.5 IndexSnapshot

Review v2 要求主要指数仍为两行，每行 5 个，不横向滚动。本轮仅确认可选布局字段，不改变指数行情基本字段。

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `indexCode` | string | 指数代码 | - | 是 | `000001.SH` | `index_daily.ts_code` | 按源 | 是 | 无 |
| `indexName` | string | 指数名称 | - | 是 | `上证指数` | 指数配置 | 低频 | 是 | 无 |
| `last` | number | 最新/收盘点位 | 点 | 是 | `3128.42` | `index_daily.close` | 按源 | 是 | 按 direction |
| `change` | number | 涨跌点 | 点 | 是 | `28.66` | `index_daily.change` | 按源 | 是 | 正红负绿 |
| `changePct` | number | 涨跌幅 | % | 是 | `0.92` | `index_daily.pct_chg` | 按源 | 是 | 正红负绿 |
| `direction` | enum | 涨跌方向 | - | 是 | `UP` | 派生 | 按源 | 是 | 必须 |
| `amount` | number | 成交额 | 源口径 | 否 | `482300000` | `index_daily.amount` | 按源 | 是 | 中性 |
| `gridRow` | integer | 2×5 布局行号 | - | 否 | `1` | 服务端配置/前端派生 | 低频 | 否 | 无 |
| `gridCol` | integer | 2×5 布局列号 | - | 否 | `3` | 服务端配置/前端派生 | 低频 | 否 | 无 |

### 5.6 StockRankItem

**对象定义**：榜单速览股票项。Review v2 要求 Top10，列为：排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额。  
**所属系统**：榜单服务。  
**使用页面和模块**：榜单速览 Top10 表格。  
**数据来源**：基础排名可来自 `dc_hot`，新增列需关联 `daily`、`daily_basic`。传统涨跌幅/成交额/换手/量比榜可直接由 `daily/daily_basic` 派生。  
**更新频率**：热榜按 `dc_hot`，行情指标按源。  
**P0 必需**：是。  
**红涨绿跌关系**：`latestPrice`、`changePct` 按 `direction`；换手率、量比、成交量、成交额中性色。

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `rank` | integer | 排名 | - | 是 | `1` | `dc_hot.rank` / 排序派生 | 按源 | 是 | 中性 |
| `stockCode` | string | 股票代码 | - | 是 | `601099.SH` | `dc_hot.ts_code` / `daily.ts_code` | 按源 | 是 | 中性 |
| `stockName` | string | 股票名称 | - | 是 | `太平洋` | `dc_hot.ts_name` / `stock_basic.name` | 按源 | 是 | 中性 |
| `latestPrice` | number | 最新价/收盘价 | 元 | 是 | `4.82` | `dc_hot.current_price` 或 `daily.close` | 按源 | 是 | 按 direction |
| `changePct` | number | 涨跌幅 | % | 是 | `3.21` | `dc_hot.pct_change` 或 `daily.pct_chg` | 按源 | 是 | 正红负绿 |
| `direction` | enum | 涨跌方向 | - | 是 | `UP` | `changePct` 派生 | 按源 | 是 | 必须 |
| `turnoverRate` | number | 换手率 | % | 是 | `5.34` | `daily_basic.turnover_rate` | 日频/按源 | 是 | 中性 |
| `volumeRatio` | number | 量比 | 倍 | 是 | `2.18` | `daily_basic.volume_ratio` | 日频/按源 | 是 | 中性 |
| `volume` | number | 成交量 | `daily.vol` 源口径：手 | 是 | `356200` | `daily.vol` | 日频/按源 | 是 | 中性 |
| `amount` | number | 成交额 | `daily.amount` 源口径：千元 | 是 | `1865000` | `daily.amount` | 日频/按源 | 是 | 中性 |
| `rankTime` | string | 榜单时间 | - | 否 | `22:30:00` | `dc_hot.rank_time` | 按源 | 否 | 无 |
| `rankType` | enum | 榜单类型 | - | 是 | `POPULAR` | 请求参数/派生 | 按源 | 是 | 无 |

展示列顺序固定：`rank`、股票组合列（`stockName + stockCode`）、`latestPrice`、`changePct`、`turnoverRate`、`volumeRatio`、`volume`、`amount`。

### 5.7 LimitUpSummary

**对象定义**：涨跌停统计与分布模块根对象。Review v2 要求 2×2 区域：左上 8 卡，右上今日分布结构，左下历史柱状图，右下昨日分布结构。  
**所属系统**：涨跌停统计服务。  
**使用页面和模块**：涨跌停统计与分布。  
**数据来源**：`limit_list_d`，必要时 `daily + stk_limit` 辅助。  
**更新频率**：按源；实时源接入后 15-60 秒。  
**P0 必需**：是。  
**红涨绿跌关系**：涨停红、跌停绿、炸板中性/警示。

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradeDate` | string(date) | 当前交易日 | - | 是 | `2026-04-28` | `limit_list_d.trade_date` | 日频/按源 | 是 | 无 |
| `summaryCards` | LimitUpSummaryCard[] | 左上 8 个统计卡 | - | 是 | `[...]` | 聚合 | 按源 | 是 | 按卡片 |
| `limitUpCount` | integer | 涨停家数 | 只 | 是 | `59` | `limit='U'` | 按源 | 是 | 红 |
| `limitDownCount` | integer | 跌停家数 | 只 | 是 | `8` | `limit='D'` | 按源 | 是 | 绿 |
| `brokenLimitCount` | integer | 炸板家数 | 只 | 是 | `27` | `limit='Z'` 或业务规则 | 按源 | 是 | 警示/中性 |
| `sealRate` | number | 封板率 | ratio | 是 | `0.686` | 派生 | 按源 | 是 | 中性 |
| `maxStreakLevel` | integer | 最高连板高度 | 板 | 是 | `6` | `max(limit_times)` | 按源 | 是 | 红强调 |
| `streakStockCount` | integer | 连板股数量 | 只 | 是 | `16` | `count(limit_times >= 2)` | 按源 | 是 | 红强调 |
| `skyToFloorCount` | integer | 天地板数量 | 只 | 否 | `1` | 需规则派生 | 按源 | 是 | 绿/警示 |
| `floorToSkyCount` | integer | 地天板数量 | 只 | 否 | `2` | 需规则派生 | 按源 | 是 | 红/强调 |
| `todayDistribution` | LimitUpDayDistribution | 右上：今日分布结构 | - | 是 | `Ellipsis` | `limit_list_d` 聚合 | 按源 | 是 | 红/绿 |
| `previousTradeDayDistribution` | LimitUpDayDistribution | 右下：昨日分布结构 | - | 是 | `Ellipsis` | 上一交易日 `limit_list_d` 聚合 | 日频 | 是 | 红/绿 |
| `historyPoints` | HistoricalLimitUpDownPoint[] | 左下：历史组合柱图 | - | 是 | `[...]` | 历史聚合 | 日频 | 是 | 红/绿 |

### 5.8 LimitUpSummaryCard

推荐 8 个 `key` 固定为：`limitUpCount`、`limitDownCount`、`brokenLimitCount`、`sealRate`、`maxStreakLevel`、`streakStockCount`、`skyToFloorCount`、`floorToSkyCount`。

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `key` | string | 卡片 key | - | 是 | `limitUpCount` | 配置 | 低频 | 是 | 无 |
| `label` | string | 卡片名称 | - | 是 | `涨停家数` | 配置 | 低频 | 是 | 无 |
| `value` | number/string | 卡片数值 | 按字段 | 是 | `59` | 聚合 | 按源 | 是 | 按 direction |
| `unit` | string | 单位 | - | 否 | `只` | 配置 | 低频 | 是 | 无 |
| `direction` | enum | 显示方向 | - | 否 | `UP` | 配置/派生 | 按源 | 是 | 红/绿 |
| `tooltip` | string | 口径说明 | - | 否 | `涨停统计按源口径` | 配置 | 低频 | 否 | 无 |

### 5.9 LimitUpDayDistribution

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradeDate` | string(date) | 交易日 | - | 是 | `2026-04-28` | `trade_cal` | 日频 | 是 | 无 |
| `limitUpSectorDistribution` | LimitUpSectorDistributionItem[] | 涨停板块分布 | - | 是 | `[...]` | `limit_list_d + dc_member/dc_index` | 按源 | 是 | 红 |
| `limitDownStructure` | LimitDownBrokenStructureItem[] | 跌停结构 | - | 是 | `[...]` | `limit_list_d` 聚合 | 按源 | 是 | 绿 |
| `brokenLimitStructure` | LimitDownBrokenStructureItem[] | 炸板结构 | - | 是 | `[...]` | `limit_list_d` 聚合 | 按源 | 是 | 警示/中性 |

### 5.10 LimitUpSectorDistributionItem

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `sectorCode` | string | 板块代码 | - | 是 | `BK1184.DC` | `dc_index.ts_code` | 按源 | 是 | 无 |
| `sectorName` | string | 板块名称 | - | 是 | `人形机器人` | `dc_index.name` | 按源 | 是 | 无 |
| `sectorType` | enum | `INDUSTRY` / `CONCEPT` / `REGION` | - | 是 | `CONCEPT` | `dc_index.idx_type` | 按源 | 是 | 无 |
| `limitUpCount` | integer | 板块内涨停数 | 只 | 是 | `6` | `limit_list_d + dc_member` | 按源 | 是 | 红 |
| `relatedStocks` | object[] | 代表股票 | - | 否 | `[...]` | `limit_list_d` | 按源 | 否 | 股票涨跌红绿 |
| `ratio` | number | 占当日涨停比例 | ratio | 否 | `0.102` | 派生 | 按源 | 否 | 无 |

### 5.11 LimitDownBrokenStructureItem

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `categoryCode` | string | 分类代码 | - | 是 | `LIMIT_DOWN` | 服务端规则 | 低频 | 是 | 无 |
| `categoryName` | string | 分类名称 | - | 是 | `跌停` | 服务端规则 | 低频 | 是 | 无 |
| `count` | integer | 数量 | 只 | 是 | `8` | `limit_list_d` 聚合 | 按源 | 是 | 按 type |
| `type` | enum | `LIMIT_DOWN` / `BROKEN_LIMIT` | - | 是 | `LIMIT_DOWN` | 服务端规则 | 低频 | 是 | 跌停绿、炸板警示 |
| `relatedStocks` | object[] | 相关股票 | - | 否 | `[...]` | `limit_list_d` | 按源 | 否 | 股票涨跌红绿 |

### 5.12 HistoricalLimitUpDownPoint

Review v2 明确字段只要求 `tradeDate`、`limitUpCount`、`limitDownCount`、`rangeType`。v0.4 中已有 `brokenLimitCount` 可继续保留，但本轮不强制进入 v2 展示。

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `tradeDate` | string(date) | 交易日 | - | 是 | `2026-04-28` | `limit_list_d.trade_date` | 日频 | 是 | 无 |
| `limitUpCount` | integer | 涨停数量 | 只 | 是 | `59` | `limit='U'` | 日频 | 是 | 红柱 |
| `limitDownCount` | integer | 跌停数量 | 只 | 是 | `8` | `limit='D'` | 日频 | 是 | 绿柱 |
| `rangeType` | enum | `1m` / `3m` | - | 是 | `1m` | 请求参数 | 请求级 | 是 | 无 |

### 5.13 SectorOverview

**对象定义**：板块速览根对象。Review v2 要求左侧 4列×2行榜单矩阵，右侧跨两行 5×4 热力图。  
**所属系统**：板块行情服务。  
**使用页面和模块**：板块速览。  
**数据来源**：`dc_index`、`dc_daily`、`moneyflow_ind_dc`。  
**P0 必需**：是。  
**红涨绿跌关系**：涨幅榜红、跌幅榜绿、热力图红绿。

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 来源 | 频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `industryRiseTop5` | SectorRankItem[] | 行业涨幅前五 | - | 是 | `[...]` | `dc_index/dc_daily` | 日频/按源 | 是 | 正红 |
| `conceptRiseTop5` | SectorRankItem[] | 概念涨幅前五 | - | 是 | `[...]` | `dc_index/dc_daily` | 日频/按源 | 是 | 正红 |
| `regionRiseTop5` | SectorRankItem[] | 地域涨幅前五 | - | 是 | `[...]` | `dc_index/dc_daily` | 日频/按源 | 是 | 正红 |
| `moneyInflowTop5` | SectorRankItem[] | 资金流入前五 | - | 是 | `[...]` | `moneyflow_ind_dc` | 盘后/按源 | 是 | 正红 |
| `industryFallTop5` | SectorRankItem[] | 行业跌幅前五 | - | 是 | `[...]` | `dc_index/dc_daily` | 日频/按源 | 是 | 负绿 |
| `conceptFallTop5` | SectorRankItem[] | 概念跌幅前五 | - | 是 | `[...]` | `dc_index/dc_daily` | 日频/按源 | 是 | 负绿 |
| `regionFallTop5` | SectorRankItem[] | 地域跌幅前五 | - | 是 | `[...]` | `dc_index/dc_daily` | 日频/按源 | 是 | 负绿 |
| `moneyOutflowTop5` | SectorRankItem[] | 资金流出前五 | - | 是 | `[...]` | `moneyflow_ind_dc` | 盘后/按源 | 是 | 负绿 |
| `heatMapItems` | HeatMapItem[] | 右侧 5×4 热力图，至少 20 条 | - | 是 | `[...]` | `dc_index/dc_daily/moneyflow_ind_dc` | 日频/按源 | 是 | 正红负绿 |

### 5.14 SectorRankItem

**对象定义**：板块 Top5 榜单项。  
**使用页面和模块**：板块速览 8 个 Top5 榜单。  
**数据来源**：`dc_index`、`dc_daily`、`moneyflow_ind_dc`。

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `rank` | integer | 排名 | - | 是 | `1` | 排序派生 | 按源 | 是 | 中性 |
| `sectorCode` | string | 板块代码 | - | 是 | `BK1184.DC` | `dc_index.ts_code` | 按源 | 是 | 中性 |
| `sectorName` | string | 板块名称 | - | 是 | `人形机器人` | `dc_index.name` | 按源 | 是 | 中性 |
| `sectorType` | enum | `INDUSTRY` / `CONCEPT` / `REGION` | - | 是 | `CONCEPT` | `dc_index.idx_type` | 按源 | 是 | 中性 |
| `changePct` | number | 板块涨跌幅 | % | 是 | `4.37` | `dc_daily.pct_change` 或 `dc_index.pct_change` | 按源 | 是 | 正红负绿 |
| `turnoverAmount` | number | 成交额 | `dc_daily.amount` 源口径：元 | 是 | `9860000000` | `dc_daily.amount` | 按源 | 是 | 中性 |
| `netInflowAmount` | number | 主力净流入 | 元 | 是 | `3056382208` | `moneyflow_ind_dc.net_amount` | 盘后/按源 | 是 | 正红负绿 |
| `leadingStockCode` | string | 领涨股票代码 | - | 是 | `002117.SZ` | `dc_index.leading_code` | 按源 | 是 | 中性 |
| `leadingStockName` | string | 领涨股票名称 | - | 是 | `东港股份` | `dc_index.leading` | 按源 | 是 | 中性 |
| `leadingStockChangePct` | number | 领涨股票涨跌幅 | % | 是 | `10.02` | `dc_index.leading_pct` | 按源 | 是 | 正红负绿 |

### 5.15 HeatMapItem

**对象定义**：板块热力图格子项。Review v2 要求至少 20 条，对应 5 行 × 4 列。  
**数据来源**：`dc_index`、`dc_daily`、`moneyflow_ind_dc`。

| 字段 | 类型 | 说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `sectorCode` | string | 板块代码 | - | 是 | `BK1184.DC` | `dc_index.ts_code` | 按源 | 是 | 中性 |
| `sectorName` | string | 板块名称 | - | 是 | `人形机器人` | `dc_index.name` | 按源 | 是 | 中性 |
| `sectorType` | enum | `INDUSTRY` / `CONCEPT` / `REGION` | - | 是 | `CONCEPT` | `dc_index.idx_type` | 按源 | 是 | 中性 |
| `changePct` | number | 涨跌幅 | % | 是 | `4.37` | `dc_daily.pct_change` | 按源 | 是 | 正红负绿 |
| `direction` | enum | 涨跌方向 | - | 是 | `UP` | `changePct` 派生 | 按源 | 是 | 必须 |
| `turnoverAmount` | number | 成交额 | `dc_daily.amount` 源口径：元 | 是 | `9860000000` | `dc_daily.amount` | 按源 | 是 | 中性 |
| `netInflowAmount` | number | 主力净流入 | 元 | 是 | `3056382208` | `moneyflow_ind_dc.net_amount` | 盘后/按源 | 是 | Tooltip 正红负绿 |
| `riseStockCount` | integer | 板块上涨家数 | 只 | 是 | `32` | `dc_index.up_num` | 按源 | 是 | 红 |
| `fallStockCount` | integer | 板块下跌家数 | 只 | 是 | `62` | `dc_index.down_num` | 按源 | 是 | 绿 |
| `rowIndex` | integer | 热力图行号，0-based | - | 是 | `0` | 服务端布局/前端派生 | 请求级 | 是 | 无 |
| `colIndex` | integer | 热力图列号，0-based | - | 是 | `3` | 服务端布局/前端派生 | 请求级 | 是 | 无 |

---

## 6. 未被 Review v2 点名、保持 v0.4 的对象

以下对象在本轮不主动修改，仅沿用 `p0-data-dictionary-v0.4.md` 已确认定义：

1. `MarketBreadth`
2. `HistoricalBreadthPoint`
3. `BreadthDistributionBucket`
4. `MarketStyle`
5. `MarketStyleHistoryPoint`
6. `TurnoverSummary`
7. `IntradayTurnoverPoint`
8. `HistoricalTurnoverPoint`
9. `MoneyFlowSummary`
10. `HistoricalMoneyFlowPoint`
11. `LimitUpStreakLadder`
12. `LimitUpStreakLevel`
13. `LimitUpStreakStock`

---

## 7. 附录 A：字段名词表

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

## 8. 文档末尾清单

### 8.1 本轮 Review v2 修改摘要

1. `MarketObjectiveSummary` 补充左右结构所需的 `layout`、`cards`、`textCard`。
2. `IndexSnapshot` 确认可选 `gridRow/gridCol`，支持主要指数 2×5。
3. `StockRankItem` 补齐 Top10 表格列：最新价、涨跌幅、换手率、量比、成交量、成交额。
4. `LimitUpSummary` 补齐 2×2 展示结构：`summaryCards`、`todayDistribution`、`previousTradeDayDistribution`、`historyPoints`。
5. 新增 `LimitUpDayDistribution`、`LimitUpSectorDistributionItem`、`LimitDownBrokenStructureItem`。
6. 新增 `SectorOverview`，补齐 8 个 Top5 榜单和 `heatMapItems`。
7. `SectorRankItem` 补齐 Review v2 要求字段。
8. `HeatMapItem` 补齐 5×4 布局字段：`rowIndex`、`colIndex`。

### 8.2 本轮新增字段清单

| 对象 | 新增字段 |
|---|---|
| `MarketObjectiveSummary` | `layout`、`cards`、`textCard` |
| `IndexSnapshot` | `gridRow`、`gridCol` |
| `StockRankItem` | `latestPrice`、`turnoverRate`、`volumeRatio`、`volume`、`amount` |
| `LimitUpSummary` | `summaryCards`、`todayDistribution`、`previousTradeDayDistribution` |
| `LimitUpDayDistribution` | 新对象 |
| `LimitUpSectorDistributionItem` | 新对象 |
| `LimitDownBrokenStructureItem` | 新对象 |
| `SectorOverview` | 新对象 |
| `SectorRankItem` | `sectorCode`、`turnoverAmount`、`netInflowAmount` |
| `HeatMapItem` | `sectorCode`、`turnoverAmount`、`netInflowAmount`、`riseStockCount`、`fallStockCount`、`rowIndex`、`colIndex` |

### 8.3 本轮修改字段清单

| 对象/字段 | 修改 |
|---|---|
| `MarketOverview` | 仅明确 `marketSummary`、`indices`、`leaderboards`、`limitUp`、`sectorOverview` 的 v2 结构 |
| `StockRankItem.price` | 建议统一为 `latestPrice`，旧字段可短期兼容 |
| `SectorRankItem.sectorId` | 建议统一为 `sectorCode`，旧字段可短期兼容 |
| `LimitUpSummary.distribution` | 拆分为 `todayDistribution` 和 `previousTradeDayDistribution` |

### 8.4 本轮未修改 API 模块清单

1. `breadth`
2. `style`
3. `turnover`
4. `moneyFlow`
5. `streakLadder`
6. `topMarketBar`
7. `breadcrumb`
8. `quickEntries`
9. 路由结构

### 8.5 市场总览页面模块与 API 字段映射表

| 页面模块 | API 字段 |
|---|---|
| 今日市场客观总结 | `marketSummary.cards`、`marketSummary.textCard` |
| 主要指数 | `indices[]` |
| 榜单速览 | `leaderboards.top10[]` |
| 涨跌停统计卡 | `limitUp.summaryCards[]` |
| 今日涨停板块分布 | `limitUp.todayDistribution.limitUpSectorDistribution[]` |
| 今日跌停/炸板结构 | `limitUp.todayDistribution.limitDownStructure[]`、`brokenLimitStructure[]` |
| 昨日涨停板块分布 | `limitUp.previousTradeDayDistribution.limitUpSectorDistribution[]` |
| 昨日跌停/炸板结构 | `limitUp.previousTradeDayDistribution.limitDownStructure[]`、`brokenLimitStructure[]` |
| 历史涨跌停柱状图 | `limitUp.historyPoints[]` |
| 板块矩阵 | `sectorOverview.*Top5[]` |
| 5×4 热力图 | `sectorOverview.heatMapItems[]` |

### 8.6 给 02 HTML Showcase 的 Mock 数据建议

1. 榜单 Top10 必须真实填满 10 行。
2. 每条榜单必须有换手率、量比、成交量、成交额。
3. 涨跌停 8 个统计卡必须齐全。
4. 今日/昨日分布结构必须均有数据。
5. 行业/概念/地域/资金流入/资金流出 Top5 均需 5 条。
6. 热力图必须 20 条，5 行 × 4 列，`rowIndex/colIndex` 完整。

### 8.7 给 03 组件 Props 的字段映射建议

| 组件 | Props |
|---|---|
| `MarketSummaryIndexSplitPanel` | `summary`、`indices` |
| `MarketSummaryCards` | `cards: MarketSummaryCard[]` |
| `MarketSummaryTextCard` | `textCard: MarketSummaryTextCard` |
| `IndexGrid` | `items: IndexSnapshot[]`、`columns:5`、`rows:2` |
| `LeaderboardTop10Table` | `items: StockRankItem[]` |
| `LimitUpTwoByTwoPanel` | `summaryCards`、`todayDistribution`、`previousTradeDayDistribution`、`historyPoints` |
| `SectorOverviewMatrix` | 8 个 Top5 数组 |
| `SectorHeatMapGrid` | `items: HeatMapItem[]`、`rows:5`、`cols:4` |

### 8.8 P0 已具备字段

| 能力 | 来源 |
|---|---|
| 榜单基础排名 | `dc_hot` |
| 榜单最新价/涨跌幅 | `dc_hot.current_price/pct_change` 或 `daily.close/pct_chg` |
| 榜单换手率/量比 | `daily_basic.turnover_rate/volume_ratio` |
| 榜单成交量/成交额 | `daily.vol/amount` |
| 涨跌停统计 | `limit_list_d` |
| 涨停板块分布 | `limit_list_d + dc_member/dc_index` |
| 板块 Top5 | `dc_index/dc_daily` |
| 板块资金流 Top5 | `moneyflow_ind_dc` |
| 热力图基础字段 | `dc_index/dc_daily/moneyflow_ind_dc` |

### 8.9 P0 暂缺字段

| 字段 | 原因 |
|---|---|
| `skyToFloorCount` | 需要天地板规则确认 |
| `floorToSkyCount` | 需要地天板规则确认 |
| 精确板块平盘家数 | `dc_index` 仅给 `up_num/down_num`，需 `dc_member + daily` 精算 |
| 热力图 5×4 排布算法 | 需确认按涨跌幅、成交额还是资金净流入排序 |
| 榜单类型并存策略 | 需确认 `dc_hot` 与传统行情榜是否并存 |

### 8.10 需要数据基座补充的字段/视图

1. `wealth_stock_leaderboard_snapshot`：合并 `dc_hot + daily + daily_basic`，提供榜单 Top10 完整列。
2. `wealth_limitup_day_distribution_snapshot`：提供今日/昨日涨停板块分布、跌停结构、炸板结构。
3. `wealth_sector_overview_matrix_snapshot`：提供 8 个 Top5 榜单。
4. `wealth_sector_heatmap_5x4_snapshot`：提供 20 条热力图格子和 `rowIndex/colIndex`。
5. 天地板/地天板规则视图：用于 `skyToFloorCount/floorToSkyCount`。

### 8.11 待产品总控确认问题

1. 榜单速览是否以传统行情榜为主，还是 `dc_hot` 热榜 + 关联行情字段为主？
2. 热力图 20 个格子排序依据：涨跌幅、成交额、资金净流入，还是综合排序？
3. 天地板/地天板是否在 v1.2 必须真实展示，还是允许空值/占位？
4. 涨停板块分布优先按概念、行业，还是混合板块口径？
