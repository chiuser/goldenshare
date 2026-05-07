# 市场总览 homepage 代码架构设计 v1

## 1. 本轮目标

本文件定义“财势乾坤 / 乾坤行情 / 市场总览”homepage 的编码前架构设计。

目标不是重新设计页面，而是在 `wealth` 独立前端工程内，按 React + TypeScript + Vite 的工程方式，高保真还原 Drive 原型：

```text
wealth/docs/reference/showcase/market-overview-v1.1.html
```

本文件只回答“代码怎么组织、组件怎么拆、数据怎么流、样式怎么落、测试怎么守住高保真”。不实现真实后端 API，不扩展新页面，不新增与市场总览无关的功能。

## 2. 依据资料

编码前必须按顺序读取：

1. `wealth/AGENTS.md`
2. `wealth/docs/README.md`
3. `wealth/docs/reference/README.md`
4. `wealth/docs/reference/showcase/market-overview-v1.1.html`
5. `wealth/docs/reference/design/03-design-tokens.md`
6. `wealth/docs/reference/design/04-component-guidelines.md`
7. `wealth/docs/reference/review/market-overview-html-review-v2.md`
8. `wealth/docs/reference/review/市场总览html_review_v_2_总控解读与变更单.md`
9. `wealth/docs/pages/market-overview/market-overview-baseline.md`
10. `wealth/docs/pages/market-overview/api-contract-baseline.md`
11. `wealth/docs/pages/market-overview/implementation-prompt-baseline.md`

优先级：

1. 用户最新指令。
2. V1.1 HTML Showcase。
3. design token、component guideline、review v2。
4. 本地工程化 baseline。

如果资料之间冲突，必须停下列出冲突点，不允许擅自按个人审美改版。

## 3. 高保真硬约束

实现必须遵守：

1. 页面必须是深色金融终端风。
2. 桌面端不使用固定 SideNav。
3. 顶部结构必须是 `TopMarketBar + Breadcrumb + PageHeader + ShortcutBar + full-width content`。
4. 首页只展示客观市场事实，不输出买卖建议、仓位建议、明日预测。
5. 首页不展示市场温度分数、情绪指数、资金面分数、风险指数作为核心结论。
6. A 股红涨绿跌，红色表示上涨、正值、净流入、涨停；绿色表示下跌、负值、净流出、跌停。
7. 模块顺序、模块标题、布局比例、表格列顺序、图表交互默认完全跟随 V1.1 Showcase。
8. 任何偏离 Showcase 的想法只能写入“待拍板项”，不得直接进入代码。

## 4. 页面模块顺序

React 页面必须按 V1.1 原型顺序组织：

1. `TopMarketBar`
2. `Breadcrumb`
3. `PageHeader`
4. `ShortcutBar`
5. 今日市场客观总结 + 主要指数，左右 50% / 50%
6. 涨跌分布
7. 市场风格
8. 成交额总览
9. 大盘资金流向
10. 榜单速览
11. 涨跌停统计与分布，2 × 2
12. 连板天梯
13. 板块速览，左 4 × 2 榜单矩阵 + 右 5 × 4 热力图
14. 状态样式基线，仅作为首期开发/验收辅助区，若产品验收认为不应出现在正式 homepage，可作为待拍板项单独确认后再处理

第 14 项来自 V1.1 HTML 原型底部的状态样式基线。它对工程实现有价值，但是否在正式页面中展示，需要在实现前由用户拍板。

## 5. 目标目录结构

首期实现只在 `wealth` 内部新增/修改文件。

```text
wealth/src/
  app/
    App.tsx
    router.tsx
  pages/
    market-overview/
      MarketOverviewPage.tsx
      MarketOverviewPage.test.tsx
      market-overview-page.css
  features/
    market-overview/
      api/
        marketOverviewMockAdapter.ts
        marketOverviewTypes.ts
        marketOverviewViewModel.ts
      layout/
        MarketTerminalLayout.tsx
        TopMarketBar.tsx
        Breadcrumb.tsx
        PageHeader.tsx
        ShortcutBar.tsx
      summary/
        MarketSummaryPanel.tsx
        FactCard.tsx
      indices/
        MajorIndexPanel.tsx
        IndexCard.tsx
        IndexTickerStrip.tsx
      breadth/
        MarketBreadthPanel.tsx
      style/
        MarketStylePanel.tsx
      turnover/
        TurnoverOverviewPanel.tsx
      money-flow/
        MarketMoneyFlowPanel.tsx
      leaderboards/
        LeaderboardPanel.tsx
        LeaderboardTable.tsx
      limit-up/
        LimitBoardPanel.tsx
        LimitStructureBlock.tsx
        StreakLadderPanel.tsx
      sectors/
        SectorOverviewPanel.tsx
        SectorRankMatrix.tsx
        SectorHeatmap.tsx
  shared/
    charts/
      MiniLineChart.tsx
      ComboBarChart.tsx
      ChartTooltip.tsx
    lib/
      marketDirection.ts
      formatters.ts
      classNames.ts
    model/
      market.ts
    ui/
      Panel.tsx
      MetricCard.tsx
      DataStatusBadge.tsx
      MarketStatusPill.tsx
      RangeSwitch.tsx
      HelpTooltip.tsx
      SkeletonBlock.tsx
      Toast.tsx
  styles/
    design-tokens.css
    global.css
```

## 6. 摆放规则

### 6.1 `src/app`

只做应用装配：

1. 引入全局样式。
2. 提供最小路由。
3. 将默认入口导向 `/market/overview`。

禁止：

1. 写市场总览模块布局。
2. 写 mock 数据。
3. 写图表、表格、行情格式化。

### 6.2 `src/pages/market-overview`

只放页面级编排：

1. 调用 mock adapter。
2. 处理 loading / empty / error / delayed / loaded。
3. 按 V1.1 顺序组合 feature 模块。
4. 控制页面级路由与页面级刷新状态。

禁止：

1. 在页面文件里堆所有模块 JSX。
2. 在页面内手写金额、百分比、涨跌色格式化。
3. 在页面内直接拼接 mock 数据。

`MarketOverviewPage.tsx` 超过 400 行前必须拆分。

### 6.3 `src/features/market-overview`

按 V1.1 模块拆分领域组件。每个模块只负责自己那一块视觉和交互。

模块目录规则：

1. `layout/`：TopMarketBar、Breadcrumb、PageHeader、ShortcutBar 与终端页壳。
2. `summary/`：今日市场客观总结。
3. `indices/`：主要指数和顶部指数条。
4. `breadth/`：涨跌分布。
5. `style/`：市场风格。
6. `turnover/`：成交额总览。
7. `money-flow/`：大盘资金流向。
8. `leaderboards/`：榜单速览。
9. `limit-up/`：涨跌停统计与分布、连板天梯。
10. `sectors/`：板块速览。
11. `api/`：市场总览 mock adapter、类型、ViewModel 映射。

feature 组件可以知道市场总览业务字段，但不能调用后端，也不能读取 ops 数据。

### 6.4 `src/shared`

只沉淀真正跨模块复用的能力。

允许：

1. `shared/ui`：Panel、MetricCard、RangeSwitch、HelpTooltip、DataStatusBadge 等通用展示组件。
2. `shared/charts`：轻量图表组件。
3. `shared/lib`：格式化、涨跌方向、className 工具。
4. `shared/model`：市场方向等基础类型。

禁止：

1. 把市场总览专属布局提前上升为通用组件。
2. 在 shared 中写市场总览模块顺序。
3. 为“以后可能复用”提前抽象复杂通用框架。

## 7. 组件映射

| V1.1 原型区域 | React 组件 | 目录 |
|---|---|---|
| TopMarketBar | `TopMarketBar` | `features/market-overview/layout/` |
| 主要指数行情条 | `IndexTickerStrip` | `features/market-overview/indices/` |
| Breadcrumb | `Breadcrumb` | `features/market-overview/layout/` |
| PageHeader | `PageHeader` | `features/market-overview/layout/` |
| ShortcutBar | `ShortcutBar` | `features/market-overview/layout/` |
| 今日市场客观总结 | `MarketSummaryPanel` + `FactCard` | `features/market-overview/summary/` |
| 主要指数 | `MajorIndexPanel` + `IndexCard` | `features/market-overview/indices/` |
| 涨跌分布 | `MarketBreadthPanel` | `features/market-overview/breadth/` |
| 市场风格 | `MarketStylePanel` | `features/market-overview/style/` |
| 成交额总览 | `TurnoverOverviewPanel` | `features/market-overview/turnover/` |
| 大盘资金流向 | `MarketMoneyFlowPanel` | `features/market-overview/money-flow/` |
| 榜单速览 | `LeaderboardPanel` + `LeaderboardTable` | `features/market-overview/leaderboards/` |
| 涨跌停统计与分布 | `LimitBoardPanel` + `LimitStructureBlock` | `features/market-overview/limit-up/` |
| 连板天梯 | `StreakLadderPanel` | `features/market-overview/limit-up/` |
| 板块速览 | `SectorOverviewPanel` + `SectorRankMatrix` + `SectorHeatmap` | `features/market-overview/sectors/` |
| 通用 Panel | `Panel` | `shared/ui/` |
| 指标卡 | `MetricCard` | `shared/ui/` |
| 区间切换 | `RangeSwitch` | `shared/ui/` |
| 帮助提示 | `HelpTooltip` | `shared/ui/` |
| 图表 Tooltip | `ChartTooltip` | `shared/charts/` |
| 折线图 | `MiniLineChart` | `shared/charts/` |
| 组合柱状图 | `ComboBarChart` | `shared/charts/` |

## 8. 样式架构

### 8.1 Token 使用

实现以 `wealth/docs/reference/design/03-design-tokens.md` 和 V1.1 HTML 中的 `--cs-*` token 为准。

`wealth` 代码统一使用 `--cs-*` 命名，不新增 `--csq-*` 别名。`04-component-guidelines.md` 中出现的 `--csq-*` 视为历史命名参考，落代码时必须映射回 `--cs-*`。

必须补齐的 token 类别：

1. 背景：`--cs-color-bg-page`、`--cs-color-bg-topbar`、`--cs-color-bg-panel`、`--cs-color-bg-panel-soft`。
2. 边框：`--cs-color-border-subtle`、`--cs-color-border-strong`。
3. 文本：`--cs-color-text-primary`、`--cs-color-text-secondary`、`--cs-color-text-muted`。
4. 行情：`--cs-color-market-up`、`--cs-color-market-down`、`--cs-color-market-flat`。
5. 品牌：`--cs-color-brand`、`--cs-color-brand-weak`。
6. 图表：axis、grid、zero line、crosshair、tooltip。
7. 布局：topbar 高度、page header 高度、content min/max width。
8. 字体：base 与 number。

### 8.2 CSS 文件组织

首期采用“全局 token + 页面样式 + 组件局部 className”的方式，不引入 CSS-in-JS。

```text
styles/design-tokens.css       # token 与全局主题
styles/global.css              # reset、body、基础字体
pages/market-overview/market-overview-page.css
```

页面样式文件只承载市场总览布局和模块间 grid。可复用组件的基础样式放在组件同名 CSS 或页面样式中，第一期不引入复杂样式系统。

### 8.3 高保真样式来源

下列 CSS 值必须优先从 V1.1 HTML 搬入或等价还原：

1. `body` 背景径向渐变与深色线性渐变。
2. `.top-market-bar` 四列 grid：`156px 540px minmax(320px, 1fr) 340px`。
3. 页面 `min-width: 1460px` 和 `max-width: 1840px`。
4. 今日总结 + 主要指数 `50% / 50%`。
5. 主要指数 `2 × 5`。
6. `row-three` 三列布局。
7. `row-two` 两列布局。
8. 榜单 Top10 表格固定列宽。
9. 涨跌停 `2 × 2`。
10. 板块速览左 `4 × 2` + 右 `5 × 4`。

## 9. 数据与 ViewModel 架构

首期只使用 mock adapter，但 mock 必须模拟真实 contract。

```text
MarketOverviewPage
  -> loadMarketOverview(params)
  -> WealthApiResponse<MarketOverview>
  -> toMarketOverviewViewModel(response.data)
  -> feature components
```

### 9.1 类型文件

`features/market-overview/api/marketOverviewTypes.ts` 定义：

1. `WealthApiResponse<T>`
2. `MarketOverviewParams`
3. `MarketOverview`
4. `MarketDirection`
5. 各模块数据类型

字段命名统一 lowerCamelCase。

### 9.2 Mock Adapter

`marketOverviewMockAdapter.ts` 只负责返回静态 mock 响应和模拟四态。

建议函数：

```ts
export async function fetchMarketOverviewMock(
  params: MarketOverviewParams,
  options?: { state?: "loaded" | "loading" | "empty" | "error" | "delayed" },
): Promise<WealthApiResponse<MarketOverview>>;
```

mock 数据必须覆盖：

1. V1.1 默认 loaded 数据。
2. loading 骨架。
3. empty 局部状态。
4. error 局部状态。
5. delayed 数据状态。

### 9.3 ViewModel

`marketOverviewViewModel.ts` 只做 API contract 到组件 props 的映射。

允许：

1. 计算 `direction` className。
2. 生成图表 points。
3. 将榜单数据整理成 tabs。
4. 将 sector 数据整理成矩阵。

禁止：

1. 在 ViewModel 中创造 API 没有的业务事实。
2. 生成买卖建议、仓位建议、明日预测。
3. 为旧字段做兼容别名。

## 10. 交互设计落代码规则

### 10.1 RangeSwitch

V1.1 支持：

1. 涨跌分布：`1个月 / 3个月`
2. 市场风格：`1个月 / 3个月`
3. 成交额历史：`1个月 / 3个月`
4. 大盘资金流向：`1个月 / 3个月`
5. 涨跌停历史：`1个月 / 3个月`

实现方式：

1. 每个模块内部维护自己的 `activeRange`。
2. 不做全局联动。
3. 切换后只更新该模块图表。

### 10.2 Tooltip / HelpTooltip

必须覆盖：

1. 模块标题旁 `?` 帮助提示。
2. 图表 hover tooltip。
3. 表格行 hover。
4. 热力图 hover。
5. 数据状态说明。

Tooltip 不接入第三方库。首期使用轻量 React 状态 + CSS 定位实现。

### 10.3 图表

不引入重型图表库。

可选方案：

1. 折线图用 SVG 实现。
2. 涨跌停组合柱状图用 SVG 实现。
3. Tooltip 用鼠标位置或最近点定位。

V1.1 HTML 使用 canvas。React 实现可使用 SVG，只要视觉、坐标轴、grid、crosshair、tooltip 行为高保真等价。

### 10.4 点击与跳转

首期不接真实路由详情页。点击行为只做轻量 toast 或 console-safe 的预留反馈。

必须保留的点击点：

1. 系统导航按钮。
2. ShortcutCard。
3. 指数卡。
4. 榜单行。
5. 连板股票卡。
6. 板块榜单项。
7. 热力图块。
8. 手动刷新按钮。

不得新增真实后端调用。

## 11. 状态设计

页面必须覆盖五类状态：

1. `loading`
2. `empty`
3. `error`
4. `dataDelayed`
5. `loaded`

状态归属：

1. 页面级 loading：首次加载时保留页面骨架。
2. 模块级 empty/error：单模块失败不拖垮整页。
3. dataDelayed：通过 `DataStatusBadge` 与模块角标表达。
4. loaded：V1.1 默认展示。

不要为了状态展示改变 V1.1 模块顺序和尺寸。

## 12. 测试与验收

### 12.1 单元测试

至少覆盖：

1. `MarketOverviewPage` 能渲染核心标题和模块。
2. `RangeSwitch` 切换 active range。
3. 红涨绿跌 class 映射正确。
4. `LeaderboardPanel` 渲染 Top10 和固定列标题。
5. `SectorOverviewPanel` 渲染 8 个 Top5 榜单块与 20 个热力图块。
6. error/empty/delayed 状态文案存在。

### 12.2 构建门禁

每次有效代码改动必须执行：

```bash
npm run typecheck
npm run test
npm run build
```

### 12.3 可视验收

实现后必须做浏览器人工检查或 smoke：

1. 页面深色金融终端风。
2. TopMarketBar 无固定 SideNav。
3. 今日总结 + 主要指数左右 50% / 50%。
4. 主要指数 2 × 5。
5. 榜单列顺序准确。
6. 涨跌停 2 × 2。
7. 板块速览左 4 × 2 + 右 5 × 4。
8. RangeSwitch 可切换。
9. Tooltip/hover 可见。
10. 红涨绿跌没有反。

## 13. 分阶段实施建议

### 13.1 Step 1：基础结构与 token

目标：

1. 补齐 `src/shared`、`src/pages`、`src/features` 目录。
2. 补齐 `design-tokens.css`。
3. 建立路由和 `MarketOverviewPage` 空壳。

不做：

1. 不写全部模块。
2. 不接真实 API。

### 13.2 Step 2：数据 contract 与 mock adapter

目标：

1. 定义市场总览类型。
2. 将 V1.1 HTML mock 数据迁入 typed mock。
3. 建立 ViewModel 映射。

不做：

1. 不创造 V1.1 没有的业务结论。
2. 不调用后端。

### 13.3 Step 3：布局壳与上半屏

目标：

1. TopMarketBar。
2. Breadcrumb。
3. PageHeader。
4. ShortcutBar。
5. 今日总结 + 主要指数。

### 13.4 Step 4：中部行情模块

目标：

1. 涨跌分布。
2. 市场风格。
3. 成交额总览。
4. 大盘资金流向。
5. 榜单速览。

### 13.5 Step 5：涨跌停、连板、板块

目标：

1. 涨跌停 2 × 2。
2. 连板天梯。
3. 板块速览 4 × 2 + 5 × 4。

### 13.6 Step 6：四态、交互与验收

目标：

1. loading / empty / error / delayed / loaded。
2. RangeSwitch。
3. Tooltip。
4. hover / click / toast。
5. 单测、构建、浏览器验收。

## 14. 待拍板项

以下事项已经由用户拍板，编码必须按本节执行：

1. V1.1 底部“状态样式基线”作为正式 homepage 的可见参考模块先保留。
2. 图表实现使用 SVG，不引入重型图表库，但视觉和交互必须高保真还原 V1.1。
3. 点击预留反馈使用 V1.1 同款轻量 toast。
4. Logo 使用 `wealth/docs/reference/brand/logo/logo_new.png` 对应的本地图片素材。

## 15. 禁止事项清单

1. 禁止把 V1.1 原型改成运营后台风格。
2. 禁止引入固定 SideNav。
3. 禁止重排模块。
4. 禁止删除模块。
5. 禁止新增未计划模块。
6. 禁止接真实后端 API。
7. 禁止调用既有 ops 后台 API。
8. 禁止把所有代码堆在一个大页面文件。
9. 禁止引入重型图表库。
10. 禁止绿涨红跌。
11. 禁止在页面组件里散落金额、百分比、涨跌色格式化逻辑。
