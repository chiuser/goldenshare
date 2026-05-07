# Codex 实现提示词：市场总览 v1

建议保存路径：`财势乾坤/codex/market-overview-codex-prompt-v1.md`

> 文档角色：05_Codex 落地提示词  
> 所属项目：财势乾坤  
> 所属页面：市场总览  
> 所属系统：乾坤行情  
> 页面优先级：P0  
> 实现基线：`财势乾坤/showcase/market-overview-v1.1.html`  
> API 基线：`财势乾坤/数据字典与API文档/market-overview-api-v0.4.md`  
> 数据字典基线：`财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4.md`  
> 组件规范基线：`财势乾坤/设计/04-component-guidelines.md`  
> Design Token 基线：`财势乾坤/设计/03-design-tokens.md`

---

## 0. 给 Codex 的执行总原则

你现在要在现有前端项目中实现“财势乾坤 / 乾坤行情 / 市场总览”页面。

这不是视觉重设计任务，不是产品重构任务，也不是静态 HTML 复制任务。你的目标是：在现有前端框架内，将 `market-overview-v1.1.html` 候选冻结版 Showcase 工程化落地，尽量还原其视觉、布局、模块顺序、数据密度、核心交互与状态表达。

执行前必须先读取并确认本文指定的必读文件存在。若任一必读文件无法读取，先停止实现，并向用户汇报缺失文件清单，不要自行脑补旧版本内容。

---

## 1. 必读文件

执行前必须读取以下文件，并在你的执行计划中确认这些文件存在：

1. `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md`
2. `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md`
3. `财势乾坤/设计/02-market-overview-page-design.md`
4. `财势乾坤/设计/03-design-tokens.md`
5. `财势乾坤/设计/04-component-guidelines.md`
6. `财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4.md`
7. `财势乾坤/数据字典与API文档/market-overview-api-v0.4.md`
8. `财势乾坤/showcase/market-overview-v1.1.html`

### 1.1 版本基线

本轮统一采用以下版本作为实现基线：

| 类型 | 基线文件 |
|---|---|
| Showcase | `财势乾坤/showcase/market-overview-v1.1.html` |
| API | `财势乾坤/数据字典与API文档/market-overview-api-v0.4.md` |
| 数据字典 | `财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4.md` |
| 组件规范 | `财势乾坤/设计/04-component-guidelines.md` |
| Design Token | `财势乾坤/设计/03-design-tokens.md` |

### 1.2 旧版本处理

严格遵守：

1. 不要使用 `market-overview-v1.html` 作为实现基线。
2. 不要等待、引用或假设 `market-overview-v1.2.html`。
3. 如果其它文档中出现旧路径、旧版本、旧状态，以本提示词指定的路径和版本为准。
4. `market-overview-v1.1.html` 是本轮候选冻结版 Showcase。

---

## 2. 实现任务背景

当前项目是“财势乾坤”，目标是构建专业、沉稳、高信息密度、有金融终端感的行情决策支持系统。

当前页面是“市场总览”。

页面基础定义：

| 项目 | 结论 |
|---|---|
| 项目 | 财势乾坤 |
| 页面 | 市场总览 |
| 所属系统 | 乾坤行情 |
| 优先级 | P0 |
| 市场范围 | A 股优先 |
| 页面定位 | A 股市场客观事实总览页 |
| 是否可作为默认落地页 | 可以 |
| 是否独立一级菜单 | 不可以 |
| 桌面端是否使用固定 SideNav | 不使用 |
| 桌面端框架 | TopMarketBar + Breadcrumb + PageHeader + ShortcutBar + 全宽行情内容区 |

页面归属必须表达为：

```text
财势乾坤 / 乾坤行情 / 市场总览
```

TopMarketBar 中“乾坤行情”应处于 active 状态。市场总览可以是系统默认打开页面，但不得在导航中被实现成独立一级菜单。

---

## 3. 实现目标

请完成以下目标：

1. 在现有前端项目中实现“市场总览”页面。
2. 页面视觉、布局、模块顺序、数据密度，尽量还原：
   `财势乾坤/showcase/market-overview-v1.1.html`
3. 使用现有前端框架实现，不只是复制静态 HTML。
4. 优先复用项目现有组件；没有现成组件时，再按 `04-component-guidelines.md` 新增组件。
5. API 未完成时，建立本地 Mock adapter；Mock 结构必须贴近 `market-overview-api-v0.4.md`。
6. 页面路由归属“乾坤行情”，不得作为独立一级菜单。
7. 保留或实现 Showcase 中表达的核心 hover、active、Tooltip、图表定位线、RangeSwitch、loading、empty、error、data delayed 状态。
8. 完成后执行 Smoke Test，并按本文末尾模板汇报。

---

## 4. 必须实现或保留的模块

市场总览页面必须包含以下模块，不得遗漏：

1. `TopMarketBar`
2. `Breadcrumb`
3. `PageHeader`
4. `ShortcutBar`
5. 今日市场客观总结
6. 主要指数
7. 涨跌分布
8. 市场风格
9. 成交额总览
10. 大盘资金流向
11. 榜单速览
12. 涨跌停统计与分布
13. 连板天梯
14. 板块速览

模块顺序应以 `market-overview-v1.1.html` 为准，不要因为个人审美主动调整模块顺序。

---

## 5. Review v2 后的关键结构要求

以下结构是本轮必须保持的候选冻结版结构，不能回退到旧版布局。

### 5.1 今日市场客观总结 + 主要指数

保持左右结构，各占 50% 空间：

```text
┌──────────────────────────────┬──────────────────────────────┐
│ 今日市场客观总结              │ 主要指数                      │
│ 50%                           │ 50%                           │
└──────────────────────────────┴──────────────────────────────┘
```

今日市场客观总结：

```text
今日市场客观总结
├── 5 个事实卡片
└── 说明性文字卡片
```

主要指数：

```text
主要指数
├── 第一行：5 个指数
└── 第二行：5 个指数
```

禁止：

1. 不要把“今日市场客观总结”和“主要指数”拆成两个独占整行模块。
2. 不要减少主要指数数量。
3. 不要把主要指数改成单行横向滚动。

### 5.2 榜单速览

榜单速览展示 Top10。

表格列顺序固定为：

```text
排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额
```

字段表达要求：

| 列 | 展示要求 | 颜色规则 |
|---|---|---|
| 排名 | 当前榜单排名 | 中性色 |
| 股票 | 股票名称 + 股票代码 | 中性色 |
| 最新价 | 股票最新价 | 随涨跌方向，上涨红、下跌绿、平盘灰白 |
| 涨跌幅 | `+x.xx% / -x.xx%` | 正红、负绿、零灰白 |
| 换手率 | `x.xx%` | 中性色 |
| 量比 | `x.xx` | 中性色 |
| 成交量 | 支持万股、万手或 API displayText | 中性色 |
| 成交额 | 支持亿、万亿或 API displayText | 中性色 |

榜单行需要支持 hover；点击股票行进入个股详情页。

### 5.3 涨跌停统计与分布

整体为 2×2 结构：

```text
┌──────────────────────────────┬──────────────────────────────┐
│ 左上：8 个统计卡片            │ 右上：今日涨停板块分布         │
│                              │      + 跌停/炸板结构           │
├──────────────────────────────┼──────────────────────────────┤
│ 左下：历史涨跌停组合柱状图    │ 右下：昨天涨停板块分布         │
│                              │      + 跌停/炸板结构           │
└──────────────────────────────┴──────────────────────────────┘
```

要求：

1. 左上必须是 8 个统计卡片。
2. 右上必须展示“今日涨停板块分布 + 跌停/炸板结构”。
3. 左下必须展示历史涨跌停组合柱状图。
4. 右下必须展示“昨天涨停板块分布 + 跌停/炸板结构”。
5. 图表需要保留 Tooltip；若 Showcase 已表达 crosshair 或定位线，需要保留。

### 5.4 板块速览

板块速览采用左侧 4 列 × 2 行榜单矩阵，右侧板块热力图跨两行。

```text
┌────────────┬────────────┬────────────┬────────────┬────────────────────┐
│ 行业涨幅前五 │ 概念涨幅前五 │ 地域涨幅前五 │ 资金流入前五 │                    │
├────────────┼────────────┼────────────┼────────────┤                    │
│ 行业跌幅前五 │ 概念跌幅前五 │ 地域跌幅前五 │ 资金流出前五 │ 板块热力图 5×4       │
└────────────┴────────────┴────────────┴────────────┴────────────────────┘
```

要求：

1. 左侧为 8 个榜单块。
2. 每个榜单块展示 Top5。
3. 右侧热力图跨两行。
4. 热力图内部为 5 行 × 4 列，共 20 个格子。
5. 板块项 hover 时需要有视觉反馈。
6. 点击板块项进入板块与榜单行情页。
7. 热力图 hover 需要展示 Tooltip。

---

## 6. 红涨绿跌硬规则

中国 A 股市场必须遵守红涨绿跌：

| 状态 | 颜色 |
|---|---|
| 上涨 / 正值 / 净流入 / 涨停 | 红色 |
| 下跌 / 负值 / 净流出 / 跌停 | 绿色 |
| 平盘 / 零值 / 无变化 | 白色、灰白色或中性灰 |

适用范围：

1. 指数点位；
2. 指数涨跌额；
3. 指数涨跌幅；
4. 股票最新价；
5. 股票涨跌幅；
6. K 线；
7. 榜单；
8. 热力图；
9. 涨跌停统计；
10. 资金流向；
11. Tooltip；
12. Mock 数据；
13. 图表正负柱；
14. hover / selected 状态中的行情色。

严禁：

1. 不要使用美股绿涨红跌规则。
2. 不要使用 UI 框架默认 `success=green` 表达上涨。
3. 不要出现同一个数据文字是红色、图形却是绿色的冲突。
4. 不要把行情红用于系统错误主色；系统错误应使用独立 danger/error token。

---

## 7. API / Mock 约束

### 7.1 首选接口

优先按以下聚合接口组织页面数据：

```http
GET /api/market/home-overview
```

该接口应作为市场总览首屏和主体模块的聚合数据来源。

### 7.2 请求参数参考

若项目已有 API 层，请按现有风格封装；参数语义参考：

```ts
interface MarketHomeOverviewParams {
  market?: 'CN_A';
  tradeDate?: string;       // YYYY-MM-DD
  dataMode?: 'latest' | 'eod' | 'replay';
  leaderboardLimit?: number; // 默认 10
  sectorTopLimit?: number;   // 默认 5
  heatMapRows?: number;      // 默认 5
  heatMapCols?: number;      // 默认 4
}
```

### 7.3 Mock adapter 要求

API 未完成时，建立本地 mock adapter，但必须满足：

1. Mock response 外层结构贴近 `market-overview-api-v0.4.md`。
2. 字段命名不得随意修改。
3. 优先使用 lowerCamelCase 业务字段。
4. 保留 `direction: 'UP' | 'DOWN' | 'FLAT' | 'UNKNOWN'` 或项目现有等价枚举。
5. 若字段暂缺，用 TODO 注释标记，不要自创主观字段顶替。
6. Mock 数据要有真实行情感：指数、股票、板块、涨跌停、成交额、资金、热力图等数值要相互合理。
7. Mock 数据也必须红涨绿跌。

### 7.4 禁止加入的首页核心字段

市场总览首页聚合接口、Mock 数据和页面 ViewModel 均不得加入以下首页核心字段：

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

市场温度、市场情绪、资金面分数、风险指数属于“市场温度与情绪分析页”的 P0 指标体系。市场总览只允许通过 ShortcutBar 提供入口，不允许展示这些分数或主观分析结论。

### 7.5 推荐数据对象映射

实现时可按以下对象拆分页面 ViewModel 或 TypeScript 类型，字段以 API v0.4 和数据字典 v0.4 为准：

```text
MarketHomeOverviewResponse
├── tradingDay
├── dataStatus
├── topMarketBar
├── breadcrumb
├── quickEntries
├── marketSummary
│   ├── cards[5]
│   └── textCard
├── indices[10]
├── marketBreadth
├── marketStyle
├── turnoverSummary
├── moneyFlowSummary
├── leaderboards
│   └── items[10]
├── limitUp
│   ├── summaryCards[8]
│   ├── todayDistribution
│   ├── historicalPoints
│   └── previousDistribution
├── limitUpStreakLadder
└── sectorOverview
    ├── rankGroups[8]
    └── heatMapItems[20]
```

---

## 8. 组件拆分建议

优先复用现有组件。没有现成组件时，再新增业务组件。新增组件必须贴合 `04-component-guidelines.md`，不要过度抽象。

### 8.1 页面级组件

建议页面级文件：

```text
MarketOverviewPage
```

职责：

1. 拉取 `GET /api/market/home-overview` 或 mock adapter；
2. 管理 loading / empty / error / delayed 状态；
3. 组织页面布局；
4. 将数据传给领域组件；
5. 不在页面文件中堆积大段表格、图表或热力图实现。

### 8.2 容器与导航组件

可复用或新增：

```text
TopMarketBar
Breadcrumb
PageHeader
ShortcutBar
Panel
DataStatusBadge
RefreshControl
RangeSwitch
```

要求：

1. TopMarketBar 展示品牌、一级系统入口、指数行情条、时间、数据状态、用户入口。
2. Breadcrumb 固定表达 `财势乾坤 / 乾坤行情 / 市场总览`。
3. PageHeader 展示页面标题“市场总览”、A 股范围、交易日、更新时间、刷新入口。
4. ShortcutBar 只展示入口和状态，不展示市场温度、情绪指数等主观分数。

### 8.3 市场总览领域组件

建议拆分：

```text
MarketObjectiveSummaryPanel
IndexGridPanel
MarketBreadthPanel
MarketStylePanel
TurnoverSummaryPanel
MoneyFlowSummaryPanel
StockLeaderboardPanel
LimitUpDistributionPanel
LimitUpStreakLadderPanel
SectorOverviewPanel
SectorHeatMap
```

### 8.4 基础行情展示组件

可复用或新增：

```text
NumericDisplay
ChangeText
PriceText
DirectionBadge
MetricCard
IndexCard
RankingTable
ChartTooltip
EmptyState
ErrorState
SkeletonBlock
DataDelayedState
```

要求：

1. 行情数字统一使用等宽数字。
2. 正数显示 `+`。
3. 百分比显示为 `+1.23% / -0.82%`。
4. 空值显示 `--`，不要显示为 `0`。
5. 如果 API 返回 `displayText`，优先展示 `displayText`，但保留原始值用于排序和 Tooltip。

---

## 9. 文件范围要求

由于前端项目结构可能不同，执行时先扫描项目结构，再选择符合现有约定的目录。不要直接大范围重构。

### 9.1 允许修改或新增的文件范围

可在现有结构下选择等价路径：

```text
src/pages/market/overview/**
src/views/market/overview/**
src/features/market-overview/**
src/components/market/**
src/components/quote/**
src/api/market/**
src/services/market/**
src/mocks/market-overview/**
src/types/market-overview/**
src/router/modules/market.*
src/routes/market.*
```

如果项目使用 Next.js、Vue、React Router、TanStack Router、Vite、Nuxt 或其它结构，请按项目现有约定落地，不要另起一套目录规范。

### 9.2 路由文件是否允许修改

允许修改路由文件，但仅限于：

1. 新增或注册“乾坤行情 / 市场总览”页面路由；
2. 将市场总览挂到“乾坤行情”下；
3. 配置默认落地页指向市场总览；
4. 设置 Breadcrumb / meta 信息。

禁止把市场总览配置成独立一级菜单。

推荐路由语义：

```text
/market/overview
```

或按项目已有命名：

```text
/quote/market-overview
```

二者择一，优先遵守现有路由命名风格。

### 9.3 不允许修改的文件范围

未经用户确认，不要修改：

1. 全局主题系统；
2. 全局 Layout 结构；
3. 全局菜单体系中与市场总览无关的页面；
4. 无关页面；
5. 无关 API adapter；
6. 构建配置；
7. 包管理文件；
8. lint / tsconfig / vite / webpack 等基础配置；
9. 认证、权限、用户系统；
10. 数据中心、交易助手、财势探查、交易训练等无关页面实现。

若确实需要改全局文件来注册路由或复用 token，必须将改动限制到最小，并在结果中说明原因。

### 9.4 不确定文件范围时的处理

如果无法确定应该改哪些文件，必须先扫描项目结构并汇报计划：

```text
我识别到当前前端结构为：xxx
计划新增/修改文件：
1. xxx：原因
2. xxx：原因
不会修改：
1. xxx
2. xxx
```

获得用户确认前，不要大范围改动。

---

## 10. 交互要求

必须实现或保留以下交互：

1. TopMarketBar 系统入口 hover / active。
2. Breadcrumb hover。
3. ShortcutBar hover / active。
4. 指数卡 hover。
5. 指数卡点击进入指数详情页。
6. 榜单行 hover。
7. 榜单行点击进入个股详情页。
8. 板块项 hover。
9. 板块项点击进入板块与榜单行情页。
10. 热力图 hover Tooltip。
11. RangeSwitch：`1个月 / 3个月` 切换。
12. 图表 Tooltip。
13. 图表 crosshair 或定位线，如 Showcase 已表达。
14. RefreshControl 手动刷新。
15. loading / empty / error / data delayed 基础状态。

如果目标详情页尚未实现，点击可先跳转到预留路由或调用项目现有 navigation helper，并在 TODO 中标记。

不要因为详情页未完成而删除点击态、hover 态或交互入口。

---

## 11. 状态要求

页面和模块必须具备基础状态：

| 状态 | 要求 |
|---|---|
| loading | 使用骨架屏或占位，保留布局，不整页闪烁 |
| empty | 展示无数据原因，可提供刷新入口 |
| error | 单模块失败不拖垮整页，展示错误态和重试入口 |
| data delayed | 展示数据延迟提示，不伪装成实时数据 |
| partial | 部分模块可用时，其余模块降级显示 |
| no permission | 若出现权限限制，展示无权限提示，不白屏 |

数据状态建议贴合：

```text
READY / DELAYED / PARTIAL / EMPTY / ERROR / NO_PERMISSION
```

---

## 12. 严禁主动改动的内容

严禁执行以下行为：

1. 不要把市场总览做成独立一级菜单。
2. 不要实现固定 SideNav。
3. 不要把市场总览做成主观分析页。
4. 不要展示市场温度、市场情绪指数、资金面分数、风险指数作为首页核心结论。
5. 不要输出买卖建议。
6. 不要输出仓位建议。
7. 不要输出明日预测。
8. 不要使用美股绿涨红跌规则。
9. 不要改变红涨绿跌规则。
10. 不要大范围重构无关页面。
11. 不要替换全局主题系统。
12. 不要引入不必要的重型依赖。
13. 不要读取旧版 `market-overview-v1.html` 作为实现基线。
14. 不要等待或引用 `market-overview-v1.2.html`。
15. 不要擅自修复用户未确认的小瑕疵。
16. 不要擅自改动 Showcase 中未要求实现的模块结构。
17. 不要因为个人审美主动重设计页面。
18. 不要主动调整模块顺序。
19. 不要主动增删模块。
20. 不要把 ShortcutBar 做成主观指标展示区。

---

## 13. 关于“小瑕疵”的处理规则

用户认为 `market-overview-v1.1.html` 已经“差不多了，虽然还有点小瑕疵”。

因此，你只能做工程实现层面的必要修正，例如：

1. 适配现有组件结构；
2. 修复明显运行错误；
3. 保证数据渲染稳定；
4. 保证响应式基础可用；
5. 保证 TypeScript / lint / build 通过；
6. 将静态 Showcase 中的 mock 表达转为稳定组件和数据驱动渲染；
7. 将无法落地的临时 CSS 写法转为项目可维护写法。

不得因为个人审美主动重设计页面。

如果发现 Showcase 中存在小视觉瑕疵，应在实现结果中列为：

```text
待产品总控确认项 / TODO
```

不要擅自改版。

---

## 14. 实现步骤建议

请按以下步骤执行：

### 14.1 扫描项目

1. 识别前端框架和路由方式。
2. 识别现有 Layout、菜单、路由模块。
3. 识别现有 API adapter / service 层。
4. 识别现有组件库和 token 使用方式。
5. 识别现有 mock 数据机制。

### 14.2 制定文件计划

输出计划，至少包含：

1. 准备新增/修改的页面文件；
2. 准备新增/复用的组件文件；
3. 准备新增/复用的 API adapter 文件；
4. 准备新增/复用的 mock 数据文件；
5. 准备修改的路由文件；
6. 明确不会修改的全局文件和无关页面。

### 14.3 建立数据结构

1. 根据 `market-overview-api-v0.4.md` 建立或补充 TypeScript 类型 / schema。
2. 建立 `GET /api/market/home-overview` adapter。
3. API 未完成时建立 mock adapter。
4. 保证 mock 数据覆盖所有模块。
5. 确保不存在禁止字段。

### 14.4 页面工程化实现

1. 搭建页面框架：TopMarketBar + Breadcrumb + PageHeader + ShortcutBar + 全宽内容。
2. 实现首屏左右结构：今日市场客观总结 50% + 主要指数 50%。
3. 实现涨跌分布、市场风格、成交额总览、大盘资金流向。
4. 实现榜单速览 Top10 表格。
5. 实现涨跌停统计与分布 2×2。
6. 实现连板天梯。
7. 实现板块速览 4×2 榜单矩阵 + 右侧 5×4 热力图。
8. 补齐 hover / active / Tooltip / RangeSwitch / crosshair / loading / empty / error / delayed 状态。

### 14.5 自测和收尾

1. 启动项目。
2. 打开市场总览路由。
3. 检查页面无白屏。
4. 检查控制台无明显错误。
5. 检查布局、颜色、模块、数据、交互。
6. 执行 lint / typecheck / build / test，按项目实际命令执行。
7. 输出最终实现报告和 Smoke Test 结果。

---

## 15. 验收标准

完成后必须自查以下 20 项：

1. 页面能正常打开。
2. 页面无白屏。
3. 控制台无明显错误。
4. 页面标题是“市场总览”。
5. 页面归属显示为“财势乾坤 / 乾坤行情 / 市场总览”。
6. 桌面端没有固定 SideNav。
7. TopMarketBar 渲染正确。
8. Breadcrumb 渲染正确。
9. ShortcutBar 渲染正确。
10. 今日市场客观总结与主要指数左右结构正确。
11. 今日市场客观总结先展示 5 个事实卡片，下方展示说明性文字卡片。
12. 主要指数两行，每行 5 个。
13. 榜单 Top10 渲染正确。
14. 榜单列顺序为：排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额。
15. 涨跌停统计与分布 2×2 正确。
16. 板块速览左侧 4×2 榜单矩阵正确。
17. 板块热力图在右侧跨两行，内部 5×4。
18. 红涨绿跌正确。
19. 未展示市场温度、情绪指数、资金面分数、风险指数作为首页核心结论。
20. 没有买卖建议，Mock/API 数据稳定。

---

## 16. Smoke Test 清单

完成后必须执行并汇报：

1. 启动项目命令。
2. 打开市场总览路由。
3. 页面无白屏。
4. 控制台无明显错误。
5. 核心模块渲染检查。
6. 红涨绿跌检查。
7. 榜单 Top10 检查。
8. 榜单列顺序检查。
9. 涨跌停统计与分布 2×2 检查。
10. 板块热力图 5×4 检查。
11. 关键点击交互检查。
12. Tooltip / RangeSwitch / chart hover 检查。
13. loading / empty / error / data delayed 基础状态检查。
14. lint / typecheck / build / test 执行结果。

Smoke Test 汇报格式：

```text
Smoke Test 结果：
1. 启动命令：xxx
2. 市场总览路由：xxx
3. 页面是否无白屏：是/否
4. 控制台错误：无/有，详情 xxx
5. 核心模块渲染：通过/未通过
6. 红涨绿跌：通过/未通过
7. 榜单 Top10：通过/未通过
8. 榜单列顺序：通过/未通过
9. 涨跌停 2×2：通过/未通过
10. 板块热力图 5×4：通过/未通过
11. 关键点击交互：通过/部分通过/未通过
12. 基础状态：通过/部分通过/未通过
13. lint/typecheck/build/test：xxx
遗留问题：
- xxx
```

---

## 17. 最终实现报告模板

完成后请按以下格式汇报：

```text
本轮实现完成：市场总览

一、读取文件确认
- 已读取：xxx
- 未读取：无 / xxx

二、实际修改文件
- xxx：说明
- xxx：说明

三、实际新增文件
- xxx：说明
- xxx：说明

四、页面路由
- 路由：xxx
- 归属：财势乾坤 / 乾坤行情 / 市场总览
- 是否独立一级菜单：否
- 是否存在固定 SideNav：否

五、模块完成情况
- TopMarketBar：完成/部分完成
- Breadcrumb：完成/部分完成
- PageHeader：完成/部分完成
- ShortcutBar：完成/部分完成
- 今日市场客观总结：完成/部分完成
- 主要指数：完成/部分完成
- 涨跌分布：完成/部分完成
- 市场风格：完成/部分完成
- 成交额总览：完成/部分完成
- 大盘资金流向：完成/部分完成
- 榜单速览：完成/部分完成
- 涨跌停统计与分布：完成/部分完成
- 连板天梯：完成/部分完成
- 板块速览：完成/部分完成

六、API / Mock
- 是否接入真实 API：是/否
- 是否使用 mock adapter：是/否
- Mock 文件：xxx
- 是否包含禁止字段：否

七、红涨绿跌检查
- 指数：通过/未通过
- 榜单：通过/未通过
- 热力图：通过/未通过
- 涨跌停：通过/未通过
- Tooltip：通过/未通过

八、Smoke Test
- 按 Smoke Test 清单逐项填写

九、待产品总控确认项
- xxx

十、未完成 / TODO
- xxx
```

---

## 18. 本轮读取文件列表

本提示词基于以下公共区文件生成：

1. `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md`
   - 读取版本：`财势乾坤项目总说明 v0.2`
   - 状态：Review 草案 v0.2

2. `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md`
   - 读取版本：`市场总览产品需求文档 v0.2`
   - 状态：Review 草案

3. `财势乾坤/设计/02-market-overview-page-design.md`
   - 读取版本：`财势乾坤｜市场总览页面设计文档 v0.1`
   - 当前版本：v0.1

4. `财势乾坤/设计/03-design-tokens.md`
   - 读取版本：`财势乾坤｜Design Token 与视觉规范 v0.2.5`
   - 状态：v0.2.5，基于市场总览 HTML Review v2 局部修订

5. `财势乾坤/设计/04-component-guidelines.md`
   - 读取版本：`财势乾坤｜P0 组件库与交互组件方案 v0.5 完整合并版`
   - 状态：Draft v0.5 merged-full / HTML Review v2 局部修订版

6. `财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4.md`
   - 读取版本：`财势乾坤｜P0 数据字典 v0.4`
   - 状态：HTML Review v2 全量修订稿

7. `财势乾坤/数据字典与API文档/market-overview-api-v0.4.md`
   - 读取版本：`财势乾坤｜市场总览 API 草案 v0.4`
   - 状态：HTML Review v2 全量修订稿

8. `财势乾坤/showcase/market-overview-v1.1.html`
   - 读取版本：`财势乾坤｜市场总览 HTML Showcase v1.1`
   - 页面标题：`财势乾坤｜市场总览 v1.1`

9. `财势乾坤/review/market-overview-html-review-v2.md`
   - 读取版本：`市场总览页review-v2`
   - 内容：Review v2 四项局部修改要求

10. `财势乾坤/review/market-overview-html-review-v2-总控解读与变更单.md`
    - 实际读取到的文件名：`市场总览html_review_v_2_总控解读与变更单.md`
    - 读取版本：`市场总览 HTML Review v2｜总控解读与变更单`
    - 说明：该文件内曾写目标输出 `market-overview-v1.2.html` 与 `05 暂缓最终 Codex 提示词`，但本轮用户已明确指定以 `market-overview-v1.1.html` 作为候选冻结版实现基线，不等待 v1.2。

---

## 19. 最终采用的 Showcase 基线

```text
财势乾坤/showcase/market-overview-v1.1.html
```

不要使用：

```text
财势乾坤/showcase/market-overview-v1.html
```

不要等待或引用：

```text
财势乾坤/showcase/market-overview-v1.2.html
```

---

## 20. Codex 实现边界

Codex 应做：

1. 工程化实现市场总览页面。
2. 尽量高保真还原 `market-overview-v1.1.html`。
3. 按 API v0.4 建立 adapter / mock。
4. 按组件规范拆分可维护组件。
5. 按 Design Token 使用颜色、字体、间距、边框、图表 token。
6. 保证红涨绿跌。
7. 保证页面状态和基础交互。
8. 保证构建、类型、lint 或项目既有校验通过。

Codex 不应做：

1. 不做产品重设计。
2. 不改模块顺序。
3. 不新增主观结论。
4. 不新增交易建议。
5. 不重构无关页面。
6. 不替换全局主题系统。
7. 不引入重型依赖。
8. 不把 Showcase 的小瑕疵擅自改成另一版视觉方案。

---

## 21. 禁止事项汇总

1. 禁止独立一级菜单。
2. 禁止固定 SideNav。
3. 禁止主观分析首页。
4. 禁止市场温度分数。
5. 禁止市场情绪指数。
6. 禁止资金面分数。
7. 禁止风险指数。
8. 禁止买卖建议。
9. 禁止仓位建议。
10. 禁止明日预测。
11. 禁止绿涨红跌。
12. 禁止旧版 `market-overview-v1.html`。
13. 禁止等待 `market-overview-v1.2.html`。
14. 禁止无关大重构。
15. 禁止替换全局主题系统。
16. 禁止不必要重型依赖。
17. 禁止擅自重排模块。
18. 禁止擅自增删模块。
19. 禁止用个人审美重设计。
20. 禁止将未确认小瑕疵自行改版。

---

## 22. Smoke Test 清单

完成后必须检查：

1. 启动项目命令。
2. 打开市场总览路由。
3. 页面无白屏。
4. 控制台无明显错误。
5. 核心模块渲染检查。
6. 红涨绿跌检查。
7. 榜单 Top10 检查。
8. 榜单列顺序检查。
9. 涨跌停统计与分布 2×2 检查。
10. 板块热力图 5×4 检查。
11. 关键点击交互检查。
12. loading / empty / error / data delayed 基础状态检查。
13. lint / typecheck / build / test 检查。

---

## 23. 待产品总控确认问题

本轮实现阶段如遇以下问题，不要擅自改版，列入待产品总控确认项：

1. `market-overview-v1.1.html` 中任何用户未明确要求修改的小视觉瑕疵。
2. 现有前端组件能力不足导致无法完全还原的细节。
3. 真实 API 与 `market-overview-api-v0.4.md` 字段不一致的地方。
4. 现有路由体系中“乾坤行情”命名与文档不一致的地方。
5. 图表库不支持 crosshair / Tooltip 细节时的替代表达方案。
6. 响应式断点与 Showcase 最小宽度之间的冲突。
7. Mock 数据口径与后端实际落库口径不一致的地方。
8. 任何可能影响全局主题、全局 Layout、全局菜单的必要改动。
