# 财势乾坤行情系统组件规范 v1

## 1. 定位

本文定义财势乾坤行情系统当前的组件边界、复用规则和交互约束，是[Design System v1](./design-system-baseline.md)的组件层补充。视觉 token、页面模式、图表视觉和状态语义以 Design System v1 为准。

当前工程事实优先级：用户最新指令 -> 当前页面 DOM/CSS/已验证交互 -> 本文与 Design System v1 -> 页面级文档 -> `reference/**` 历史资料。

`wealth/docs/reference/showcase/component-library-demo-v2.2.html` 是组件意图、状态和交互的历史样本库，不是当前 React 组件 API，不得照搬其中的旧命名、旧 token 或旧数据契约。

## 2. 组件分层与放置

| 位置 | 放置内容 | 不应放置 |
|---|---|---|
| `src/app/**` | 路由、Provider、全局错误边界、样式装配 | 页面业务逻辑、模块 UI |
| `src/pages/**` | 页面编排、页面级状态、模块间导航 | 模块数据转换、通用 UI 细节 |
| `src/features/<domain>/**` | 单一业务域的 API client、adapter、view model、专用组件 | 跨页面共享视觉组件 |
| `src/shared/ui/**` | 两个及以上页面复用且有稳定行为的 UI | 绑定某个模块数据结构的组件 |
| `src/shared/charts/**` | 跨详情页复用的图表生命周期、坐标交互、纯算法与通用展示组件 | stock/index DTO、请求状态和领域文案 |
| `src/shared/lib/**` | 格式化、方向判断、纯工具 | React 页面状态 |
| `src/styles/**` | token、reset、跨页面基础工具类 | 模块专属布局 |

组件首次只在一个模块使用时，先放 feature；确认至少两个页面需要相同行为、样式和测试后，再迁入 `shared/ui`。禁止为“看起来整齐”提前抽象，也禁止复制已有共享组件形成第二套实现。

## 3. 当前正式共享组件

| 组件 | 位置 | 职责 | 使用约束 |
|---|---|---|---|
| `TopMarketBar` | `src/shared/ui/top-market-bar/` | 品牌、一级导航、指数 ticker、用户入口 | 市场总览、股票详情和后续行情页必须直接复用；不得复制 Header |
| `Panel` | `src/shared/ui/Panel.tsx` | 一级模块容器 | 用于独立内容区，不用于替代页面根布局 |
| `MetricCard` | `src/shared/ui/MetricCard.tsx` | 标题 + 数值 + 副值的原子事实卡 | 数据格式化在 adapter/formatter 完成 |
| `RangeSwitch` | `src/shared/ui/RangeSwitch.tsx` | 紧凑互斥切换 | active 必须驱动真实内容切换 |
| `DataStatusBadge` | `src/shared/ui/DataStatusBadge.tsx` | 模块数据状态 | 不与行情涨跌色混用 |
| `MarketStatusPill` | `src/shared/ui/MarketStatusPill.tsx` | 行情/事实聚合状态 | 仅用于有明确状态来源的位置 |
| `SkeletonBlock` | `src/shared/ui/SkeletonBlock.tsx` | 局部 loading 占位 | 不用 mock 数据伪装 loaded |
| `DetailChartWorkspace` | `src/shared/charts/detail-workspace/` | 详情页 K 线、MACD、成交量、KDJ 四窗格生命周期、同步交互和 viewport | 股票/指数领域 adapter 只提供稳定 `dataKey`、字段、文案、图层和 Tooltip；缩放合同遵循[技术方案](./detail-chart-zoom-implementation-design-v1.md)与[LLD](./detail-chart-zoom-low-level-design-v1.md) |

新增 shared 组件必须同时满足：至少两个真实消费者、稳定的 props 语义、最小组件测试、在本文补充职责与禁止项。

## 4. 页面复合组件模式

### 4.1 市场总览

市场总览采用“页面编排 + 独立模块 feature”模式。模块只消费自身 API 与 view model，页面负责排列、页面级状态和路由。

当前主要模块包括：

- `MarketNewsPanelGroup`：新闻速览与个股新闻并列区域。
- `MarketSummaryPanel`：市场客观总结及事实卡。
- `MajorIndexPanel`：10 个主要指数卡。
- `MarketBreadthPanel`：涨跌家数/涨跌分布切换。
- `MarketStylePanel`、`TurnoverOverviewPanel`、`MarketMoneyFlowPanel`：市场风格、成交额、资金流向。
- `LeaderboardPanel`、`LimitBoardPanel`、`StreakLadderPanel`：榜单、涨跌停、连板天梯。
- `SectorOverviewPanel`：板块 Top5 矩阵与热力图。

模块不得自己决定页面路由。股票、指数等实体点击事件由模块上报业务标识（例如 `tsCode`），由 `MarketOverviewPage` 统一导航。这样模块可以复用，路由规则也不会散落在列表行里。

### 4.2 股票详情

股票详情页由下列复合区组成：

- `StockBreadcrumbActionBar`：路径与页面级操作。
- `StockChartToolbar`：周期、复权和受支持操作。
- `StockChartWorkspace`：K 线、MACD、成交量、KDJ 四区图表工作台。
- `StockInfoRail`：价格摘要、盘口、关联板块、个股资金等右侧固定信息栏。
- `Toast`：对首版未实现动作的轻量反馈。

详情页共享 `TopMarketBar`，但不共享市场总览的内容网格。右侧栏和四区图表是详情页的专用工作台，不应被抽象成普通 Card 拼装。

## 5. 基础视觉组件规则

### 5.1 Panel、Card 与 MetricCard

- Panel 负责模块边界、标题区与内容区，不承担列表行交互。
- Card 负责可比较的原子数据。相同组的 Card 必须有相同高度和数字基线。
- `MetricCard` 只显示经过 adapter 规范化的 `label/value/subText/direction` 等展示语义，不读取 API 原始字段。
- Panel 和 Card 的颜色、圆角、边框均来自系统 token；不在模块 CSS 中重建一套颜色。

### 5.2 Header、Breadcrumb、Shortcut

- 页面都从共享 `TopMarketBar` 开始。
- 面包屑使用次级文字，最后一级为当前页面的主强调，不承担重复的大标题。
- 页面操作区仅放当前页面必要动作。禁止重新在顶部添加已废弃的全局刷新时间、已收盘标记或重复的系统状态。
- 快捷入口仅用于市场总览约定的高频区域，不自动复制到详情页。

### 5.3 Tabs、RangeSwitch、按钮

- 互斥内容切换用 `RangeSwitch` 或 Tabs；同一组中只允许一个 active。
- active 的金色是选择状态，不是数据正向状态。
- 没有真实实现的动作可保留，但必须 disabled 或 toast 反馈，不能悄悄改变数据。
- 按钮点击区域必须与视觉边界一致；不可把整行无提示地扩大为跳转区域，除非页面级需求已确认整行可点击。

### 5.4 表格、榜单、热力图、梯队

- 排名行必须包含可识别主体（名称/代码）和排行指标；数列使用 `.num` 保持对齐。
- 板块热力图的色阶表达强弱，不能取代具体的涨跌数值。
- 连板天梯的金色仅表达“高板/关注层级”，不得让整个区块变为高饱和金色背景；层级容器仍保持 Panel 暗色材质。
- 股价或行情缺失时显示真实状态（如停牌、`--`），不沿用前一日行情假装当日数据。

## 6. 图表组件规则

### 6.1 市场总览图表

- 轻量趋势线、柱状图、热力图保持当前 SVG/CSS 实现；组件内部接收展示数据，不反向计算后端事实字段。
- `MiniLineChart` 等通用轻图表必须提供明确的轴语义、hover 信息和空数据处理。
- 涨跌分布柱形的顺序、颜色、数字位置遵循对应模块三件套与当前实现；数字固定在柱顶上方，而不是图表容器顶部。
- 同一模块中切换“内容类型”不能伪装成时间范围选择。

### 6.2 详情页图表

详情页正式共享图表引擎是 `DetailChartWorkspace`，通过 `lightweight-charts` 加 React/CSS 覆盖层实现。`StockChartWorkspace`、`StockMinuteChartWorkspace`、`IndexChartWorkspace` 和 `IndexMinuteChartWorkspace` 均为领域 adapter；全仓只保留 shared 的一套四窗格生命周期、range sync、drag、crosshair 和缩放实现。共享收敛与缩放分别由 `b38ac20e`、`61a5adea` 完成，禁止重新引入页面私有图表生命周期或兼容分支。

强制行为：

1. K 线、MACD、成交量、KDJ 四个 pane 同步时间坐标与十字线。
2. 右侧轴宽度和绘图区右边界跨 pane 对齐。
3. tooltip 根据鼠标所在绘图区左右半区避让，且鼠标离开工作台后与十字线一起 dismiss。
4. 时间轴同时支持日线的年份/月度标记和十字线日期标签。
5. 指标标题栏在 chart pane 外占有固定高度，不得覆盖指标绘图区。
6. 轴、网格、crosshair、tooltip 使用系统图表 token；指标系列颜色按系统 Design System 规定。
7. 任何新增指标都必须确认来源字段、时间对齐、数值轴语义和 hover 展示，而非前端临时计算或模拟。
8. K 线缩放只改变四窗格共享 logical range；纵轴由可见真实数据自动适配，不得用 CSS scale 或修改行情值模拟放大。
9. 可视根数合同唯一落在 `detailChartViewport.ts`：最少 45、最多 180、步长 15、1600px 默认 120，自适应默认 clamp 为 75～150；页面和 adapter 不得覆盖或复制这些常量。
10. 四类 adapter 必须提供 `stock|index + tsCode + day|m{freq}` 的稳定 `dataKey`；切换标的或周期重置默认范围，切换 MA/BOLL/趋势图层不得重置用户视图。
11. 缩放按钮只在有真实 K 线点时出现；点击只同步四个 chart 的 logical range，不重建 chart、不调用 `fitContent()`、不发网络请求。

## 7. 数据、状态与交互边界

### 7.1 数据流

页面和组件只消费 view model：

```text
API DTO -> feature adapter -> view model -> component
```

- 组件中不得拼接 API 原始字段、格式化金额/百分比或推断行情方向。
- formatter 与方向判断集中在 `shared/lib` 或 feature adapter。
- 页面不可回填 mock 覆盖真实 API 的 loading/error；未接真实 API 的相邻模块可继续保持独立 mock。

### 7.2 状态组件

每个核心模块要有 loading、empty、error、loaded 和必要的 delayed/partial 表达。状态组件只反映该模块事实，不以全页状态掩盖局部异常。

- `loading`：展示 skeleton/占位。
- `empty`：说明无数据。
- `error`：展示简明错误，并保留不受影响模块。
- `delayed`：表达日期或时效落后；debug 详情不得默认出现在正式用户界面。

### 7.3 Tooltip、Popover、Drawer、Toast

- Tooltip 用于即时解释或图表点位，不承载长篇业务说明。
- Popover/Drawer 适合展开列表、筛选或辅助信息，必须有明确关闭路径。
- Toast 用于轻量、非阻断反馈；不承担数据加载错误的唯一展示。
- 浮层组件必须处理容器边缘避让、焦点和裁切问题。

## 8. 新组件准入与验证

新增或修改组件前，页面/模块方案至少回答：

1. 为什么已有 shared/feature 组件不能满足。
2. 它属于 shared 还是 feature，依据是什么。
3. 它接收什么 view model，不接收哪些 API 原始字段。
4. 默认、hover、active、disabled、loading、empty、error、delayed 如何表现。
5. 是否涉及图表、列表实体跳转、数字方向或动画；若涉及，如何遵循系统规则。

组件验收至少包含：

- 对应的组件或页面测试；
- 真实 API 接入模块的核心字段到 UI 展示断言；
- 宽桌面基线下的视觉检查；
- 未改变同一 shared 组件其他消费者的回归检查。

任何组件若需要偏离本规范，必须先更新 Design System/页面设计文档并取得确认；不允许以局部 CSS 覆盖形成第二套标准。
