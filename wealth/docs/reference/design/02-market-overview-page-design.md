# 财势乾坤｜市场总览页面设计文档 v0.1

> 建议路径：`/docs/wealth/pages/market-overview-page-design.md`  
> 负责人：`02_页面原型与 HTML Showcase`  
> 页面正式名称：`市场总览`  
> 页面归属：`乾坤行情`  
> 页面路径建议：`/market/overview` 或 `/quote/market-overview`  
> 当前版本：`v0.1`  
> 本轮产物：页面设计文档 + `market-overview-v1.html` HTML Showcase  
> 设计边界：桌面端优先；A 股优先；深色主题优先；不使用固定 SideNav。

---

## 0. 上游文档与依赖状态

本设计文档基于以下上游文档：

| 上游文档 | 本轮检索状态 | 本设计中的处理 |
|---|---|---|
| `财势乾坤行情软件项目总说明_v_0_2.md` | 已检索到 | 作为产品总控纲领，约束 P0 范围、首页事实边界、红涨绿跌、Codex 协作规则。 |
| `市场总览产品需求文档 v0.2.md` | 已检索到 | 作为市场总览页面 PRD，约束页面名称、归属、模块、非目标、导航方式。 |
| `03-design-tokens.md` | 已检索到，版本 `v0.2.3` | HTML Showcase 使用其中的深色主题、红涨绿跌、无固定 SideNav、TopMarketBar + Breadcrumb + PageHeader + ShortcutBar 规则。 |
| `04-component-guidelines.md` | 已检索到，状态 `Draft v0.3` | 组件拆分和状态模型按当前 v0.3 执行；若后续组件命名变化，需要同步更新 Showcase 注释与 Codex 提示词。 |
| `market-overview-api-v0.3.md` | 已检索到，状态 `Audit 修订稿` | Mock ViewModel 按 `GET /api/market/home-overview` 聚合接口组织；榜单部分存在 API/PRD 口径待确认，已在“待产品总控确认问题”标注。 |

> 说明：虽然 03、04、API v0.3 均已可作为当前落地依据，但 04 仍为 Draft、API 为 Audit 修订稿，因此本页面设计文档标记为 `v0.1`，HTML Showcase 标记为 `v1`，后续可随上游最终版做字段级校正。

---

## 1. 页面目标

“市场总览”是财势乾坤打开后的默认落地页候选，但**导航归属固定为乾坤行情**。它不是欢迎页、营销页，也不是主观分析页，而是：

> **A 股市场客观事实总览页。**

页面需要让用户在打开系统后，用最少切换快速看清以下事实：

1. 今日 A 股主要指数表现如何；
2. 全市场上涨、下跌、平盘家数如何；
3. 涨跌幅区间分布如何；
4. 市场风格偏大盘还是小盘；
5. 成交额相对上一交易日和近 20 日中位数是否放大；
6. 大盘资金净流入/净流出及分单结构如何；
7. 涨停、跌停、炸板、封板率、最高连板高度如何；
8. 连板梯队由哪些股票构成；
9. 哪些行业/概念板块涨跌靠前；
10. 哪些板块资金流入/流出靠前；
11. 哪些个股进入涨幅、跌幅、成交额、换手、量比异动榜；
12. 如何继续进入市场温度与情绪、机会雷达、自选、持仓、提醒、用户设置。

页面必须坚持：

- 只展示 A 股市场客观事实；
- 不展示市场温度、市场情绪指数、资金面分数、风险指数作为首页核心结论；
- 不输出买卖建议、仓位建议、明日预测；
- 中国市场红涨绿跌：上涨/净流入/涨停为红，下跌/净流出/跌停为绿，平盘为灰；
- 视觉专业、沉稳、高密度，有金融终端感。

---

## 2. 用户任务

| 用户任务 | 页面支持方式 | 优先级 | 下钻方向 |
|---|---|---:|---|
| 快速确认今日市场强弱 | 今日市场客观总结、主要指数、涨跌分布 | P0 | 指数详情、板块与榜单行情 |
| 查看主要指数表现 | 主要指数卡片、顶部行情条 | P0 | 指数详情页 |
| 判断赚钱效应 | 上涨/下跌/平盘家数、涨跌幅区间、涨跌中位数 | P0 | 涨跌分布详情或榜单 |
| 判断市场风格 | 大盘/小盘平均涨跌幅、大小盘涨跌比、等权平均涨跌幅 | P0 | 板块与榜单行情 |
| 查看成交活跃度 | 当日成交总额、较上一交易日变化、5 日/20 日均值、近半年曲线 | P0 | 市场成交额详情 |
| 查看资金方向 | 大盘资金净流入、超大单/大单/中单/小单、近半年曲线 | P0 | 资金流向详情、板块资金榜 |
| 查看短线交易事实 | 涨停、跌停、炸板、封板率、连板高度、天地板/地天板 | P0 | 涨跌停详情、连板天梯 |
| 发现强弱板块 | 行业/概念涨跌前五、资金流入/流出板块前五 | P0 | 板块详情、板块热力图 |
| 查看个股榜单 | 涨幅、跌幅、成交额、换手、量比异动榜 | P0 | 个股详情页 |
| 进入分析页 | 快捷入口“市场温度与情绪” | P0 | 市场温度与情绪分析页 |
| 进入机会发现 | 快捷入口“机会雷达” | P0 | 机会雷达页 |
| 管理关注对象 | 快捷入口“我的自选、我的持仓、提醒中心” | P0 | 自选、持仓、提醒中心 |

---

## 3. 页面归属与导航说明

### 3.1 页面归属

市场总览属于：

```text
财势乾坤 / 乾坤行情 / 市场总览
```

它可以作为系统默认落地页，但不能作为独立一级菜单。一级系统入口仍然是：

```text
乾坤行情 / 财势探查 / 交易助手 / 交易训练 / 数据中心 / 系统设置
```

TopMarketBar 中“乾坤行情”为 active 状态；市场总览在面包屑和页面头部中表达层级。

### 3.2 不使用固定 SideNav

桌面端市场总览不使用固定 SideNav。原因：

1. 行情内容需要横向空间承载指数网格、分布图、榜单表格、连板天梯；
2. 固定 SideNav 会压缩数据密度，与金融终端场景冲突；
3. 当前页面层级可由 Breadcrumb 清晰表达；
4. 高频分流由 TopMarketBar、ShortcutBar、模块下钻完成。

### 3.3 面包屑表达层级

面包屑固定为：

```text
财势乾坤 / 乾坤行情 / 市场总览
```

交互规则：

- “财势乾坤”：点击返回默认落地页；
- “乾坤行情”：点击或 hover 可展开乾坤行情内页面列表；
- “市场总览”：当前页，默认不可跳转，可点击触发当前页刷新或无动作。

---

## 4. 页面整体布局

桌面端采用全宽行情内容区，不预留 SideNav 宽度。

```text
┌──────────────────────────────────────────────────────────────────────┐
│ TopMarketBar：品牌 / 一级系统入口 / 指数行情条 / 时间 / 状态 / 用户   │
├──────────────────────────────────────────────────────────────────────┤
│ Breadcrumb：财势乾坤 / 乾坤行情 / 市场总览                            │
│ PageHeader：市场总览 / A股 / 交易日 / 更新时间 / 手动刷新              │
├──────────────────────────────────────────────────────────────────────┤
│ ShortcutBar：市场温度与情绪｜机会雷达｜我的自选｜我的持仓｜提醒｜设置  │
├──────────────────────────────────────────────────────────────────────┤
│ 首屏：今日市场客观总结 + 主要指数网格 + 涨跌分布 + 市场风格            │
│      + 成交额总览 + 大盘资金流向                                      │
├──────────────────────────────────────────────────────────────────────┤
│ 涨跌停统计 + 涨跌停分布 + 连板天梯                                    │
├──────────────────────────────────────────────────────────────────────┤
│ 板块速览：行业涨跌前五 / 概念涨跌前五 / 资金流入流出 / 热力图入口      │
├──────────────────────────────────────────────────────────────────────┤
│ 榜单速览：涨幅榜 / 跌幅榜 / 成交额榜 / 换手榜 / 量比异动榜             │
├──────────────────────────────────────────────────────────────────────┤
│ 状态样式基线：hover / selected / loading / empty / error              │
└──────────────────────────────────────────────────────────────────────┘
```

布局建议：

| 区域 | 布局方式 | 说明 |
|---|---|---|
| TopMarketBar | 100% 宽度，48–56px 高度 | 保持紧凑；不要做大 Hero。 |
| Header 区 | 全宽容器，Breadcrumb + PageHeader | PageHeader 高度约 56px。 |
| ShortcutBar | 6 个入口横向网格 | 展示入口名称、说明、待处理数量；不展示主观分数。 |
| 主内容区 | 12 栅格 / CSS Grid | 面板间距 10–16px；信息密度优先。 |
| 指数区 | 10 个指数，建议 2 行 × 5 列 | PRD 至少 7 个；Token 建议 10 个，本版 Showcase 采用 10 个。 |
| 面板 | Panel + Header + Body | 弱边框、低亮背景、数字等宽。 |
| 榜单区 | Tab + RankingTable | 每个 Tab 固定列，行 hover 可点击。 |

---

## 5. 首屏模块优先级

### 5.1 首屏必须出现

| 优先级 | 模块 | 理由 |
|---:|---|---|
| 1 | TopMarketBar | 用户确认当前系统、主要指数、数据状态。 |
| 2 | Breadcrumb + PageHeader | 明确页面归属、市场范围、交易日、更新时间。 |
| 3 | ShortcutBar | 无 SideNav 后承担 P0 闭环分流。 |
| 4 | 今日市场客观总结 | 用事实文案降低用户认知成本。 |
| 5 | 主要指数 | 最核心行情入口。 |
| 6 | 涨跌分布 | 判断赚钱效应。 |
| 7 | 市场风格 | 判断大盘/小盘、权重/题材结构。 |
| 8 | 成交额总览 | 判断市场活跃度。 |
| 9 | 大盘资金流向 | 判断资金流事实。 |

### 5.2 首屏以下

| 模块 | 展示策略 |
|---|---|
| 涨跌停统计 | 首屏下方紧接展示，支持短线用户快速查看。 |
| 涨跌停分布 | 与涨跌停统计相邻，显示板块分布和高度分布。 |
| 连板天梯 | 完整结构展示，模块内部可滚动。 |
| 板块速览 | 多列表格组合，支持下钻。 |
| 榜单速览 | Tab 化，避免一次性堆满。 |
| 状态样式基线 | Showcase 专用，用于指导 Codex 实现状态。 |

---

## 6. 核心模块说明

### 6.1 TopMarketBar

**目标**：承载全局入口和实时市场状态，但不能成为大型导航侧栏。

必须包含：产品标识、一级系统入口、主要指数行情条、当前时间、开闭市状态、数据状态、用户入口。

数据依赖：`topMarketBar.brandName`、`topMarketBar.activeSystemKey`、`topMarketBar.globalEntries[]`、`topMarketBar.indexTickers[]`、`tradingDay.sessionStatus`、`dataStatus[]`、`topMarketBar.userShortcutStatus`。

交互：系统入口 hover；当前系统 selected；指数点击进入指数详情；数据状态 hover 显示数据源；用户入口打开菜单。

### 6.2 Breadcrumb + PageHeader

**目标**：替代 SideNav 表达页面层级，同时承载交易日和刷新动作。

内容：Breadcrumb、页面标题、市场范围、当前交易日、数据更新时间、手动刷新按钮、自动刷新状态。

数据依赖：`breadcrumb[]`、`tradingDay.tradeDate`、`tradingDay.market`、`tradingDay.sessionStatus`、`dataStatus[].latestTradeDate`、`serverTime`。

### 6.3 ShortcutBar / 页面内快捷入口

必须包含：市场温度与情绪、机会雷达、我的自选、我的持仓、提醒中心、用户设置。

允许显示入口名称、简短说明、待处理数量、是否有更新、是否可用。禁止显示市场温度分数、情绪指数、资金面分数、风险指数、买卖建议、预测性结论。

数据依赖：`quickEntries[]`。

### 6.4 今日市场客观总结

基于 `marketSummary`、`indices`、`breadth`、`turnover`、`moneyFlow`、`limitUp` 生成事实文案。仅允许描述指数涨跌、涨跌家数、成交额变化、涨停变化、资金净流入/流出等客观事实。

### 6.5 主要指数

至少展示上证指数、深证成指、创业板指、科创 50、沪深 300、中证 500、中证 1000。本版 Showcase 采用 10 个指数，额外包含上证 50、中证 A500、北证 50。

字段：`indexCode`、`indexName`、`last`、`prevClose`、`change`、`changePct`、`amount`、`direction`、`trend[]`。

### 6.6 涨跌分布

内容：上涨家数、下跌家数、平盘家数、红盘率、涨跌幅区间分布、近半年上涨/下跌/平盘家数曲线、涨跌中位数。

字段：`breadth.upCount`、`breadth.downCount`、`breadth.flatCount`、`breadth.redRate`、`breadth.medianChangePct`、`breadth.distribution[]`、`breadth.history[]`。

### 6.7 市场风格

内容：涨跌中位数、等权平均涨跌幅、大盘股平均涨跌幅、小盘股平均涨跌幅、大小盘涨跌比、风格领先方向。风格标签只能是事实表达，不作为交易建议。

字段：`style.largeCapChangePct`、`style.smallCapChangePct`、`style.equalWeightChangePct`、`style.medianChangePct`、`style.smallVsLargeSpreadPct`、`style.styleLeader`。

### 6.8 成交额总览

内容：当日市场成交总额、较上一交易日变化额、较上一交易日变化比例、近半年成交额曲线、5 日均值、20 日均值。

字段：`turnover.totalAmount`、`turnover.prevTotalAmount`、`turnover.amountChange`、`turnover.amountChangePct`、`turnover.amount5dAvg`、`turnover.amount20dMedian`、`turnover.history[]`、`turnover.unit`。

### 6.9 大盘资金流向

内容：大盘资金净流入、超大单净流入、大单净流入、中单净流入、小单净流入、近半年资金流向曲线。

字段：`moneyFlow.mainNetInflow`、`moneyFlow.superLargeNetInflow`、`moneyFlow.largeNetInflow`、`moneyFlow.mediumNetInflow`、`moneyFlow.smallNetInflow`、`moneyFlow.history[]`、`moneyFlow.unit`、`moneyFlow.dataStatus`。

资金正值/净流入为红，负值/净流出为绿。

### 6.10 涨跌停统计

内容：涨停家数、跌停家数、炸板家数、触板家数、封板率、连板家数、最高连板高度、天地板数量、地天板数量、数据口径说明。

字段：`limitUp.limitUpCount`、`limitUp.limitDownCount`、`limitUp.failedLimitUpCount`、`limitUp.touchedLimitUpCount`、`limitUp.sealRate`、`limitUp.streakStockCount`、`limitUp.highestStreak`、`limitUp.skyToFloorCount`、`limitUp.floorToSkyCount`、`limitUp.dataScopeNote`。

### 6.11 涨跌停分布

内容：涨停板块分布、跌停板块分布、连板高度分布、炸板板块分布。

字段：`limitUpDistribution.limitUpSectors[]`、`limitUpDistribution.limitDownSectors[]`、`limitUpDistribution.streakHeight[]`、`limitUpDistribution.failedLimitUpSectors[]`。

### 6.12 连板天梯

内容：首板、二板、三板、四板、五板及以上，以及股票名、代码、板块、最新价、涨跌幅、开板次数。

字段：`streakLadder.highestStreak`、`streakLadder.items[].streak`、`streakLadder.items[].stocks[]`。

### 6.13 板块速览

内容：行业涨幅前五、行业跌幅前五、概念涨幅前五、概念跌幅前五、资金流入板块前五、资金流出板块前五、板块热力图入口。

字段：`sectorOverview.industryTopGainers[]`、`sectorOverview.industryTopLosers[]`、`sectorOverview.conceptTopGainers[]`、`sectorOverview.conceptTopLosers[]`、`sectorOverview.fundInflowTop[]`、`sectorOverview.fundOutflowTop[]`、`sectorOverview.heatmapEntry`。

数据源建议：`dc_index`、`dc_daily`、`moneyflow_ind_dc`。

### 6.14 榜单速览

内容：个股涨幅榜、个股跌幅榜、个股成交额榜、个股换手榜、个股异动榜（量比口径）。

字段：`leaderboards.gainers[]`、`leaderboards.losers[]`、`leaderboards.amount[]`、`leaderboards.turnover[]`、`leaderboards.surge[]`。

API v0.3 当前提示首页榜单使用 `dc_hot`，并准备 `leaderboards.popular` 与 `leaderboards.surge`。由于 PRD 与本轮任务明确要求 5 类榜单，本设计保留 5 个 Tab，并在“待产品总控确认问题”中标注 API 需补齐或明确降级策略。

---

## 7. 交互行为

| 交互对象 | 行为 | 结果 |
|---|---|---|
| 一级系统入口 | hover / click | hover 提亮；点击进入对应系统默认页。 |
| 指数行情条 | click | 进入指数详情页。 |
| 指数卡 | hover / click / selected | hover 提亮；click 选中；二次操作可进入指数详情。 |
| Breadcrumb | hover / click | 可点击项显示可点击态；当前项不跳转。 |
| 手动刷新 | click | 当前页进入局部 loading；更新数据状态；失败时模块级 error。 |
| 快捷入口 | hover / click | 点击进入对应 P0 页面；disabled 入口展示原因。 |
| 面板行 | hover / click | hover 高亮；点击进入板块或个股详情。 |
| 榜单 Tab | click | 切换榜单；当前 Tab selected。 |
| 图表区间 | hover | Tooltip 显示日期、数量、占比或金额。 |
| 错误态重试 | click | 只重试当前模块，不阻塞整页。 |

---

## 8. 数据依赖

| 数据对象 | 用途 | 必要性 | 更新频率建议 |
|---|---|---:|---|
| `TradingDay` | 交易日、开闭市状态、最近交易日 | 必需 | 交易日历 / 打开页时 |
| `DataSourceStatus` | 数据源状态、最新交易日、完整率 | 必需 | 同步任务更新 |
| `TopMarketBarData` | 品牌、系统入口、顶部指数行情、用户状态 | 必需 | 10s / 1min |
| `BreadcrumbItem[]` | 页面层级表达 | 必需 | 静态配置或聚合接口校验 |
| `QuickEntry[]` | 页面内快捷入口 | 必需 | 打开页时 / 用户状态变更 |
| `MarketObjectiveSummary` | 今日客观事实文案和指标 | 必需 | 聚合派生 |
| `IndexSnapshot[]` | 指数卡和顶部行情条 | 必需 | 10s / 1min / 收盘固定 |
| `MarketBreadth` | 涨跌家数、红盘率、区间分布、历史曲线 | 必需 | 1–5min / 收盘固定 |
| `MarketStyle` | 大小盘对比、涨跌中位数、等权平均 | 必需 | 1–5min / 收盘固定 |
| `TurnoverSummary` | 成交额和历史曲线 | 必需 | 1–5min / 收盘固定 |
| `MoneyFlowSummary` | 大盘资金流和分单结构 | 必需，可降级 | 1–5min / 源数据可用时 |
| `LimitUpSummary` | 涨跌停、炸板、封板率、最高连板 | 必需 | 1–5min / 收盘固定 |
| `LimitUpDistribution[]` | 涨跌停板块分布、连板高度 | 必需 | 1–5min / 收盘固定 |
| `LimitUpStreakLadder` | 连板天梯 | 必需 | 1–5min / 收盘固定 |
| `SectorOverview` | 行业/概念/资金流板块速览 | 必需 | 1–5min / 收盘固定 |
| `Leaderboards` | 涨幅/跌幅/成交额/换手/量比异动榜 | 必需，但 API 口径待确认 | 1–5min / 收盘固定 |

---

## 9. API 依赖

### 9.1 首屏聚合接口

```http
GET /api/market/home-overview
```

推荐用于市场总览首屏和主要模块一次性加载。

请求参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `market` | string | `CN_A` | P0 固定 A 股。 |
| `tradeDate` | string(date) | 最近交易日 | 指定交易日。 |
| `dataMode` | enum | `latest` | `latest` / `eod` / `replay`。 |
| `sectorType` | enum | `ALL` | `INDUSTRY` / `CONCEPT` / `REGION` / `ALL`。 |
| `sectorLimit` | integer | `8` | 每组板块榜数量。 |
| `leaderboardLimit` | integer | `10` | 每组榜单返回数量。 |
| `includeHistory` | boolean | `true` | 是否返回历史曲线。 |

响应必须覆盖：

```text
tradingDay
dataStatus
topMarketBar
breadcrumb
quickEntries
marketSummary
indices
breadth
style
turnover
moneyFlow
limitUp
limitUpDistribution
streakLadder
sectorOverview
leaderboards
```

### 9.2 模块接口

| 模块 | 聚合字段 | 推荐模块接口 | 用途 |
|---|---|---|---|
| TopMarketBar | `topMarketBar`、`dataStatus` | `/api/index/summary` | 顶部指数局部刷新。 |
| Breadcrumb | `breadcrumb` | 聚合接口内返回 | 校验固定文案。 |
| ShortcutBar | `quickEntries` | `/api/settings/quick-entry` | 用户状态与入口状态刷新。 |
| 主要指数 | `indices` | `/api/index/summary` | 指数卡局部刷新。 |
| 涨跌分布 | `breadth` | `/api/market/breadth` | 涨跌家数和分布刷新。 |
| 市场风格 | `style` | `/api/market/style` | 风格统计刷新。 |
| 成交额总览 | `turnover` | `/api/market/turnover` | 成交额曲线刷新。 |
| 大盘资金流 | `moneyFlow` | `/api/moneyflow/market` | 资金流模块刷新。 |
| 涨跌停统计 | `limitUp` | `/api/limitup/summary` | 涨跌停统计刷新。 |
| 涨跌停分布 | `limitUpDistribution` | `/api/limitup/distribution` | 分布刷新。 |
| 连板天梯 | `streakLadder` | `/api/limitup/streak-ladder` | 连板天梯刷新。 |
| 板块速览 | `sectorOverview` | `/api/sector/overview` | 板块速览刷新。 |
| 榜单速览 | `leaderboards` | `/api/market/leaderboards` | 榜单刷新，字段口径待确认。 |

### 9.3 禁止字段

市场总览聚合接口不得作为首页核心展示字段返回：

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

快捷入口可以有 `title`、`description`、`route`、`pendingCount`、`hasUpdate`，但不能附带上述分数或结论。

---

## 10. 组件拆分

### 10.1 页面级容器

| 组件 | 说明 |
|---|---|
| `MarketOverviewPage` | 页面总容器，负责数据加载、状态管理、模块组合。 |
| `TopMarketBar` | 顶部市场状态栏。 |
| `GlobalSystemMenu` | 一级系统入口；桌面端横向展示，窄屏可折叠。 |
| `IndexTickerStrip` | 顶部主要指数行情条。 |
| `Breadcrumb` | 页面层级。 |
| `PageHeader` | 标题、市场范围、交易日、更新时间、刷新。 |
| `ShortcutBar` | 页面内快捷入口容器。 |
| `MarketOverviewContent` | 全宽行情内容区，无 SideNav。 |

### 10.2 行情事实组件

| 组件 | 映射字段 |
|---|---|
| `MarketObjectiveSummary` | `marketSummary`、`indices`、`breadth`、`turnover`、`moneyFlow`、`limitUp` |
| `IndexGrid` | `indices[]` |
| `IndexCard` | `IndexSnapshot` |
| `MetricCard` | 各模块指标 |
| `MarketBreadthPanel` | `breadth` |
| `DistributionChart` | `breadth.distribution[]`、`limitUpDistribution` |
| `MarketStylePanel` | `style` |
| `TurnoverPanel` | `turnover` |
| `MiniTrendChart` | `history[]`、`trend[]` |
| `FundFlowPanel` | `moneyFlow` |
| `FundFlowBar` | `moneyFlow` 分单结构 |
| `LimitUpSummaryPanel` | `limitUp` |
| `LimitUpDistributionPanel` | `limitUpDistribution` |
| `LimitUpStreakLadder` | `streakLadder` |
| `SectorOverviewPanel` | `sectorOverview` |
| `SectorRankList` | 板块榜单项 |
| `LeaderboardTabs` | `leaderboards` |
| `RankingTable` | 个股榜单 |
| `DataStatusBadge` | `dataStatus` |
| `StateBlock` | loading / empty / error |

---

## 11. 空状态 / 加载态 / 异常态

### 11.1 空状态

| 场景 | 文案 | 操作 |
|---|---|---|
| 非交易日无当日数据 | 当前日期不是 A 股交易日，已切换到最近交易日。 | 查看最近交易日 / 手动选择日期 |
| 板块榜为空 | 当前口径下暂无板块榜数据。 | 刷新 / 查看最近交易日 |
| 榜单为空 | 当前榜单暂无数据，可能是数据源暂未更新。 | 刷新 / 查看热门榜 |
| 历史曲线为空 | 暂无近半年历史数据。 | 保留指标卡，隐藏曲线或显示占位 |

### 11.2 加载态

要求：整页首次加载显示骨架屏；手动刷新时保持原数据，模块角标显示 refreshing；表格显示骨架行；图表显示网格占位；不允许整页白屏；TopMarketBar 和 PageHeader 优先渲染。

### 11.3 异常态

| 异常 | 表现 | 处理 |
|---|---|---|
| `400001` 参数错误 | PageHeader 下方提示条件错误 | 恢复默认条件 |
| `401001` 未登录 | 基础行情游客态展示；用户入口提示登录 | 登录 |
| `404001` 数据不存在 | 模块空状态 | 切换最近交易日 |
| `500001` 服务异常 | 模块 error block | 重试 |
| `503001` 数据源不可用 | DataStatusBadge 警告；相关模块降级 | 使用缓存 / 重试 |
| 资金流数据缺失 | MoneyFlowPanel 显示降级说明 | 用成交额和板块成交额替代展示 |

---

## 12. HTML Showcase 要求

文件路径：

```text
/docs/wealth/showcase/market-overview-v1.html
```

必须满足：单文件 HTML/CSS/JS；不依赖复杂构建工具；不依赖外部 CDN；使用真实感 A 股 Mock 数据；上涨红色、下跌绿色、平盘灰色；桌面端不得出现固定 SideNav；全宽展示行情内容；体现 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar；体现 hover、active、selected、loading、empty、error；图表可用 CSS/SVG/Canvas 模拟；模块间距、层级、信息密度接近高保真原型；不做廉价大屏风；HTML 中保留清晰注释；页面标题必须是“市场总览”。

---

## 13. Codex 实现注意事项

### 13.1 必须阅读的文档

1. `/docs/wealth/00-project-overview.md`
2. `/docs/wealth/prd/market-overview-prd.md`
3. `/docs/wealth/03-design-tokens.md`
4. `/docs/wealth/04-component-guidelines.md`
5. `/docs/wealth/api/market-overview-api.md`
6. `/docs/wealth/pages/market-overview-page-design.md`
7. `/docs/wealth/showcase/market-overview-v1.html`

### 13.2 实现范围

实现市场总览页面；路由建议 `/market/overview`；页面归属乾坤行情；不新增固定 SideNav；使用 TopMarketBar + Breadcrumb + PageHeader + ShortcutBar + 全宽行情内容区；使用 mock 数据或 API adapter，字段结构对齐 `GET /api/market/home-overview`；红涨绿跌必须正确；所有表格行 hover、卡片 hover/selected、Tab active 必须实现；至少实现 loading、empty、error 三类基础状态；不要引入大屏风、过度发光、低幼插画。

### 13.3 文件边界建议

可新增：

```text
src/pages/market/overview/
src/components/market-overview/
src/mocks/marketOverviewMock.ts
src/styles/market-overview.css
```

不得随意修改全局路由结构中非本页面相关配置、Design Token 中已确认的红涨绿跌规则、已有公共组件的破坏性 API。

### 13.4 Smoke Test

```text
1. 启动项目成功。
2. 打开 /market/overview 成功。
3. 页面无白屏。
4. 桌面端没有固定 SideNav。
5. TopMarketBar、Breadcrumb、PageHeader、ShortcutBar 正常渲染。
6. 主要指数、涨跌分布、成交额、资金流、涨跌停、连板、板块、榜单全部出现。
7. 红涨绿跌正确。
8. hover、selected、active、loading、empty、error 状态可见。
9. 控制台无明显错误。
10. mock 数据能映射到 API v0.3 字段。
```

---

## 14. 待产品总控确认问题

1. **主要指数数量**：PRD 要求至少 7 个，Design Token v0.2.3 建议 10 个 2 行 × 5 列。本版 Showcase 采用 10 个，是否作为最终固定口径？
2. **ShortcutBar 待处理数量**：本轮任务允许展示待处理数量；Design Token 中提到 ShortcutBar 状态主要展示未读提醒数量。本版展示待处理数量但不展示主观分数，是否保留？
3. **榜单 API 口径**：PRD 要求涨幅榜、跌幅榜、成交额榜、换手榜、量比异动榜；API v0.3 当前提示首页榜单使用 `dc_hot`，并准备 `leaderboards.popular` 与 `leaderboards.surge`。是否需要 API v0.3 补齐五类榜单字段？
4. **板块热力图**：Design Token 决策倾向只提供入口；本版遵循“入口优先”，不铺开完整热力图。是否允许后续展示小型预览？
5. **金额单位**：API v0.3 保持 Tushare/PostgreSQL 落库口径，前端展示依赖 `unit` 或 `displayText`。是否要求后端统一返回展示文本以减少前端误格式化？
6. **涨跌停口径**：API v0.3 样例提示 `limit_list_d 不含 ST 股票统计`。页面是否需要显性展示该口径说明？
7. **资金流缺失降级**：若 `moneyFlow.dataStatus=UNAVAILABLE`，首页是隐藏资金面板、显示异常态，还是用成交额/板块成交额替代？
8. **页面文件名**：本轮按用户要求使用 `market-overview-page-design.md` 和 `market-overview-v1.html`，后续是否废弃旧 `home-overview.md` / `home-overview-v1.html` 命名？
