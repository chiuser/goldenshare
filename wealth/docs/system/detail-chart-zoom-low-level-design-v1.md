# 详情页共享图表与 K 线缩放 LLD v1

> 状态：已完成。M1 提交为 `b38ac20e`，M2 提交为 `61a5adea`；152 项测试、构建、浏览器验收和 M3 文档对账均已通过。
> 正式设计稿：[Goldenshare Web / 10 Detail Chart Zoom - Web Handoff](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=581-516&m=dev)
> 需求：[详情页 K 线缩放标杆需求 v1](./detail-chart-zoom-benchmark-requirement-v1.md)
> 方案：[详情页共享图表与 K 线缩放技术实施方案 v1](./detail-chart-zoom-implementation-design-v1.md)
> 门禁：[详情页共享图表与 K 线缩放 M2 编码前门禁 v1](./detail-chart-zoom-m2-coding-gate-v1.md)
> 后续共享交互扩展：[详情页 K 线可见区间最高/最低价标注技术方案 v1](./detail-chart-visible-extrema-annotation-implementation-design-v1.md)及其[代码级 LLD](./detail-chart-visible-extrema-annotation-low-level-design-v1.md)。该扩展已完成前端开发、自动化门禁、部署和用户人工交互验收，并已独立闭环；本文既有 M1/M2 完成状态不用于替代该扩展自身的验收记录。

---

## 1. 目标、范围与结论

### 1.1 本文要解决的问题

本文把已确认的技术方案落实到当前 `dev-interface` 代码的文件、类型、状态、算法、生命周期和测试层，确保编码阶段不再临时决定以下问题：

1. 如何先删除股票分钟线的第二套图表生命周期，并保持现有分钟图的页面结构和动态展示。
2. 如何让股票日线、股票分钟、指数日线、指数分钟最终只使用一个 `DetailChartWorkspace`。
3. 如何在不重建 chart、不请求 API 的情况下实现 `45～180` 根、每次 `15` 根的按钮缩放。
4. 如何按 K 线真实绘图区宽度计算自适应默认值，并保证 1600px 页面精确为 120 根。
5. 如何在图层切换、容器 resize、拖动、追加最新 bar 和切换标的/周期时保持正确锚点。
6. 如何保持四 pane 横轴完全同步，并让各自纵轴按可见真实数据自动适配。

### 1.2 本轮边界

本 LLD 只设计 Wealth 前端详情图表：

1. 不修改后端、API、DTO、Reader、查询 limit、cursor、Lake 或 Dagster。
2. 不修改行情字段、技术指标公式、趋势通道 geometry、Tooltip 字段和量额单位。
3. 不增加滚轮缩放、触控缩放、重置按钮、缩放百分比或自动翻页。
4. 不修改页面、左右栏、工具栏和四 pane 的尺寸比例。
5. 不修改 Loading、Empty、Error、Forbidden 页面骨架；只有 Loaded/Partial 且存在 K 线时渲染缩放控件。

### 1.3 实施结论

开发必须拆成两个独立里程碑：

1. **M1 共享收敛**：股票分钟迁入 shared，仍显示 90 根，不出现缩放按钮。
2. **M2 缩放能力**：在唯一 shared 引擎中加入自适应默认、按钮缩放、viewport 生命周期和显式纵轴 autoscale。

M1 未完成代码、浏览器和无漂移门禁前，不允许进入 M2。两阶段不得合并成一个大改动。

---

## 2. 依据与审计方法

### 2.1 事实优先级

发生冲突时按以下顺序处理：

1. 用户最新确认的 45/180/15、1600px 默认 120、约 9.5px/根和纵轴自动适配口径。
2. 正式 Figma page `581:516` 的组件、场景、密度、状态、几何与开发映射；它负责视觉和几何事实。
3. 本 LLD 及配套需求、技术方案和编码门禁；它们负责代码结构、算法和生命周期事实。
4. 当前 `dev-interface` 的实际 React、CSS、测试和本地运行页面；它们负责迁移前基线事实。
5. 股票/指数原页面文档中的历史实现记录。

视觉与 LLD 若发生冲突，不允许开发者自行选择或做补偿坐标；必须先同步修改正式 Figma 与本文并重新评审。

### 2.2 CodeGraph 审计

本轮在仓库根使用 `codegraph_status`、`codegraph_explore` 和 `codegraph_impact`：

1. 索引包含 2295 个文件、39764 个节点和 90283 条边，未报告 stale/pending。
2. `StockDetailPage` 在日线和分钟线之间分别渲染 `StockChartWorkspace`、`StockMinuteChartWorkspace`。
3. `IndexDetailPage` 在日线和分钟线之间分别渲染 `IndexChartWorkspace`、`IndexMinuteChartWorkspace`。
4. `StockChartWorkspace`、`IndexChartWorkspace`、`IndexMinuteChartWorkspace` 已消费 `DetailChartWorkspace`。
5. `StockMinuteChartWorkspace` 仍直接创建四个 `lightweight-charts` 实例，是唯一未收敛消费者。
6. `codegraph_impact` 对 TSX JSX 动态引用只返回符号自身；真实消费者已用 explore、当前 import 和页面渲染代码补充核验。编码后必须再次用 import 检索和 typecheck 证明消费者清零，不能只依赖 impact 输出。

### 2.3 本地只读浏览器审计

2026-08-12 对当前本地股票 `000638.SZ` 的 5 分钟页面做了只读检查：

1. 当前分钟图四个 pane 都显示图表库原生时间轴。
2. hover 时四个 pane 都显示原生 crosshair 轴标签，同时存在跨 pane 同步竖线和底部日期标签。
3. 分钟状态块位于 K 线区右上角。
4. 图表根容器在当前 1280px 视口为约 `1091.36×562`，图表区约 `1089.36×526`。
5. 因 `max-width:1360px` 媒体规则，四 pane 实测高度约为 `257.40 / 89.53 / 89.53 / 89.54`。
6. 图表区之后保留约 35px 空轨道；它没有指标文案，也没有 shared 指标栏的上分隔线。

因此 M1 不能简单把 DTO 塞入现有 shared props，否则时间轴、crosshair 轴标签和底部轨道会发生可见变化。本文在 shared 中定义稳定的通用展示策略解决该差异，不使用股票页面补偿 CSS，也不保留旧 chart 实现。

### 2.4 正式 Figma 审计

2026-08-12 已按节点树和实际属性完成正式开发稿对账：

1. page `581:516` 已命名为 `10 Detail Chart Zoom - Web Handoff`，状态节点 `612:1129` 标记 `APPROVED FOR WEB DEVELOPMENT`。
2. 单按钮组件集 `583:534` 包含 ZoomOut/ZoomIn × Default/Hover/Pressed/Focus/Disabled 共 10 个变体；组合组件集 `585:550` 包含 Available/Min45/Max180/ShortData。
3. 图标来自 Supericons 的 Phosphor `magnifying-glass-minus` 与 `magnifying-glass-plus`；图标容器为 16×16，矢量约 13×13，颜色继承当前状态 token。
4. 四个 1600×1200 场景节点为 `588:524`、`590:613`、`591:1711`、`592:918`；控件实例均为 60×28，并保持相同主图相对位置。
5. `593:1095` 冻结 45/120/180 根密度；`597:1107` 冻结交互和状态；`597:1120` 冻结 28/4/60px、价格轴与 8px 安全间距以及 <=2px 验收。
6. `612:1132` 将正式节点逐项映射到本文章节和目标 Web 组件。原股票 Loaded `345:3`、原指数 Loaded `417:2` 未被本轮正式稿升级修改。

---

## 3. 当前代码结构与缺口

### 3.1 Shared engine

`wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.tsx` 当前负责：

1. 创建和销毁 K 线、MACD、成交量、KDJ 四个 chart。
2. 构造 candlestick、line、histogram series，并挂载可选 primitive。
3. crosshair、Tooltip、Y 轴浮标、时间标签和四 pane visible range 同步。
4. 自定义 pointer/mouse 横向拖动。
5. 日线与分钟时间格式。

当前缺口：

| 项目 | 当前事实 | 目标 |
|---|---|---|
| 默认窗口 | `defaultVisibleBars=90` | M1 保持 90；M2 改为宽度自适应 |
| public override | `visibleBars?: number` | M2 删除，页面不能覆盖统一合同 |
| 数据身份 | 无 `dataKey` | M2 必填，用于新数据集重置 |
| viewport 保存 | 只存在 effect 内局部变量 | 提升为跨 chart 重建存活的 ref |
| effect 依赖 | `candleData/mainLines/points/primitives/timeMode/visibleBars` | zoom UI state 不进入依赖 |
| 图层切换 | 重建四 chart 并回到最新 90 根 | 同一 dataKey 重建后恢复当前 range |
| resize | 只更新日线时间 marker | 未交互时更新自适应默认；交互后保持 |
| 纵轴 | 依赖 `autoScale` 默认值 | 显式 `autoScale=true` |
| 控件槽位 | K 线 overlay 只有 Tooltip | Tooltip 与 zoom controls 并列 |
| 右上附加内容 | 无 | M1 增加领域无关 accessory 槽位 |
| 底部轨道 | 强制渲染指标栏 | 支持内容栏或透明结构轨道 |

`buildChartOptions()` 当前还有重复的 `timeScale.rightOffset` 声明；M1/M2 修改同一函数时应删除机械重复，但不得借机改变值 `1`。

### 3.2 股票分钟独立实现

`StockMinuteChartWorkspace.tsx` 当前 501 行并独立维护：

1. 四个 chart、八个 series（1 个 candlestick、2 个 histogram、5 个 line）和 chart options。
2. crosshair、visible range subscription、pointer/mouse drag。
3. 固定 90 根、状态块、四 pane DOM 和 Tooltip。
4. 一套与 shared 几乎同值的颜色和 CSS class。

右边界 clamp 中连续两次执行 `to = maxTo`，说明重复实现已开始产生机械噪声。M1 完成后该文件只能保留状态判断、ViewModel 映射和领域渲染；不得再 import：

```text
createChart
IChartApi
ISeriesApi
CandlestickSeries
HistogramSeries
LineSeries
ColorType
CrosshairMode
```

### 3.3 现有四个消费者

| 消费者 | 数据身份来源 | 当前图表实现 | M1 | M2 dataKey |
|---|---|---|---|---|
| `StockChartWorkspace` | 页面 `viewModel.stock.tsCode` | shared | 不改行为 | `stock:${tsCode}:day` |
| `StockMinuteChartWorkspace` | `data.tsCode + data.freq` | 独立 | 迁入 shared | `stock:${tsCode}:m${freq}` |
| `IndexChartWorkspace` | `viewModel.identity.tsCode` | shared | 不改行为 | `index:${tsCode}:day` |
| `IndexMinuteChartWorkspace` | `data.tsCode + data.freq` | shared | 不改行为 | `index:${tsCode}:m${freq}` |

`dataKey` 只表示可视序列身份，不包含 overlay，也不包含每次返回的最后时间。当前页面在切换显式 `tradeDate` 时会先卸载 Loaded 图表；同一序列追加数据由 viewport append 规则处理，因此无需把日期拼入 key。

### 3.4 数据量

当前请求已核验：

| 场景 | 请求量 | 最大可见根数 | 结论 |
|---|---:|---:|---|
| 股票日线 | 300 | 180 | 足够 |
| 指数日线 | 300 | 180 | 足够 |
| 股票分钟 | 500 | 180 | 足够 |
| 指数分钟 | 500 | 180 | 足够 |

本轮不改请求参数，不因缩小触发 cursor 或第二页请求。

### 3.5 当前测试缺口

1. `DetailChartWorkspace.test.tsx` 只有 90 根、null-safe、crosshair/Tooltip、分钟时间轴四类测试。
2. `StockMinuteChartWorkspace.test.tsx` 自带第二套 `lightweight-charts` mock，实际测试的是即将删除的独立生命周期。
3. `StockChartWorkspace.test.tsx` 证明 MA/BOLL 切换，但当前切换后只检查新 chart，没有证明 range 被保留。
4. 没有 viewport 纯函数测试。
5. 没有 45/120/180、宽度自适应、resize、dataKey、append bar、点击不重建 chart 的测试。
6. 没有 `TrendChannelPanePrimitive.autoscaleInfo()` 的独立可见范围回归。

---

## 4. 目标目录与文件职责

```text
wealth/src/shared/charts/detail-workspace/
  DetailChartWorkspace.tsx
    # 唯一 chart/series/subscription/drag/viewport 生命周期
  DetailChartPane.tsx
    # 既有 pane 结构，不理解 zoom
  DetailChartZoomControls.tsx
    # 纯 button 组件，无 chart API
  detailChartViewport.ts
    # 常量、默认根数、range、锚点、clamp 纯函数
  detailChartViewport.test.ts
    # 算法边界
  detailChartTypes.ts
    # dataKey、展示策略和 shared props
  detailChartSeries.ts
    # 既有数据构造，不改事实值
  detailChartFormatters.ts
    # 既有时间格式，不改业务口径
  detail-chart-workspace.css
    # 空轨道、zoom controls 与既有 shared 样式

wealth/src/features/stock-detail/chart/
  StockChartWorkspace.tsx
    # 股票日线 adapter；M2 接收 tsCode
  StockMinuteChartWorkspace.tsx
    # 分钟状态 + adapter + 领域 Tooltip/标题，不创建 chart

wealth/src/features/index-detail/chart/
  IndexChartWorkspace.tsx
    # 指数日线 adapter + trend primitive
  IndexMinuteChartWorkspace.tsx
    # 指数分钟 Gold adapter + bars-only Partial
```

不新增第二个 `shared-minute-chart`、hook 版图表引擎或页面级 viewport store。

---

## 5. Shared 最终 Props 合同

### 5.1 类型

`detailChartTypes.ts` 最终增加：

```ts
export type DetailChartTimeAxisPlacement = "bottom-pane" | "each-pane";
export type DetailChartCrosshairPresentation =
  | "synchronized-overlay"
  | "native-axis-labels";

interface DetailChartWorkspaceBaseProps {
  dataKey: string;
  ariaLabel: string;
  crosshairPresentation?: DetailChartCrosshairPresentation;
  mainLines: DetailChartLineDefinition[];
  mainPrimitives?: ISeriesPrimitive<Time>[];
  panelAriaLabels: Record<DetailChartPanelKey, string>;
  points: DetailChartPoint[];
  renderMainHeader: (point: DetailChartPoint | null) => ReactNode;
  renderPanelHeader: (
    panel: Exclude<DetailChartPanelKey, "kline">,
    point: DetailChartPoint | null,
  ) => ReactNode;
  renderTooltip: (
    point: DetailChartPoint,
    side: DetailChartTooltipSide,
  ) => ReactNode;
  timeAxisAriaLabel: string;
  timeAxisPlacement?: DetailChartTimeAxisPlacement;
  timeMode: DetailChartTimeMode;
  topRightAccessory?: ReactNode;
}

type DetailChartBottomBarProps =
  | { bottomBar: ReactNode; bottomBarAriaLabel: string }
  | { bottomBar?: never; bottomBarAriaLabel?: never };

export type DetailChartWorkspaceProps =
  DetailChartWorkspaceBaseProps & DetailChartBottomBarProps;
```

最终 public props 不再包含 `visibleBars`。

### 5.2 默认值与职责

1. `timeAxisPlacement` 默认 `bottom-pane`，保持股票日线、指数日线、指数分钟当前 shared 行为。
2. `crosshairPresentation` 默认 `synchronized-overlay`，保持三个现有 shared 消费者行为。
3. 股票分钟明确传 `each-pane + native-axis-labels`，保持迁移前动态展示。
4. `topRightAccessory` 作为 `.detail-chart-area` 的直接子节点渲染；shared 不增加 wrapper、不覆盖 accessory 自身定位，也不读取状态值或改文案。
5. 有 `bottomBar` 时必须同时传 `bottomBarAriaLabel`；缺少 `bottomBar` 时渲染 `aria-hidden` 的透明 34px 结构轨道。
6. TypeScript 不能用空字符串或假 `span` 绕过底栏语义。

### 5.3 Chart options 映射

`buildChartOptions()` 接收 pane、`timeMode` 和两项展示策略：

1. `bottom-pane`：只有 KDJ pane 的 `timeScale.visible=true`。
2. `each-pane`：四个 pane 的 `timeScale.visible=true`。
3. `synchronized-overlay`：沿用 shared 当前隐藏原生 vertical label/line、隐藏 horizontal label，并渲染自定义同步竖线、日期标签和 Y 轴浮标。
4. `native-axis-labels`：crosshair 使用图表库 `CrosshairMode.Normal` 默认轴标签；仍保留跨 pane 同步竖线和底部日期标签，不渲染 shared 自定义 Y 轴浮标。
5. 两种模式都保持 `handleScale=false`、`handleScroll=false`。
6. 两种模式都显式设置 `rightPriceScale.autoScale=true`、`minimumWidth=56` 和既有 `scaleMargins`。

这两项展示策略只决定现有视觉，不参与 viewport 算法。

---

## 6. M1：股票分钟共享收敛

### 6.1 实施顺序

1. 保存四类图表的 1600×1200 静态和 hover 基线。
2. 先扩展 shared 的 accessory、可选底栏、时间轴和 crosshair 展示合同。
3. 给 shared 增加对应结构/展示测试，但保持默认 90 根。
4. 将股票分钟点映射为 `DetailChartPoint`。
5. 用 shared 替换股票分钟 loaded 分支。
6. 删除股票分钟的 chart/series/sync/drag/pane/options 代码。
7. 完成 M1 全量验证和前后截图；通过后独立提交。

### 6.2 股票分钟点映射

`StockMinuteChartWorkspace.tsx` 内保留纯映射函数：

```ts
function toDetailChartPoint(point: StockMinuteChartPoint): DetailChartPoint {
  return {
    time: point.timestamp as UTCTimestamp,
    fullDate: point.tradeTime,
    open: point.open,
    high: point.high,
    low: point.low,
    close: point.close,
    preClose: null,
    changePct: null,
    amplitude: null,
    volume: point.volume,
    amount: point.amount,
    turnoverRate: null,
    macd: point.macd,
    dif: point.macdDif,
    dea: point.macdDea,
    k: point.kdjK,
    d: point.kdjD,
    j: point.kdjJ,
    overlays: {},
  };
}
```

约束：

1. 不在这里计算 MA/BOLL，不把缺失指标转成 0。
2. `mainLines` 使用模块级只读空数组，避免每次 render 生成新引用。
3. `renderTooltip` 继续使用当前股票分钟字段顺序、股/元单位和相对本 bar 开盘价的颜色。
4. 领域 Tooltip 可继续使用现有 `.kline-tooltip/.tooltip-*` class；M1 不强制改名造成像素漂移。

### 6.3 Loaded 分支

目标结构：

```tsx
<DetailChartWorkspace
  ariaLabel="分钟图表区"
  crosshairPresentation="native-axis-labels"
  mainLines={STOCK_MINUTE_MAIN_LINES}
  panelAriaLabels={...}
  points={points}
  renderMainHeader={...}
  renderPanelHeader={...}
  renderTooltip={...}
  timeAxisAriaLabel="股票分钟底部时间轴"
  timeAxisPlacement="each-pane"
  timeMode="minute"
  topRightAccessory={statusBlock}
/>
```

M1 尚未引入 `dataKey`；该必填合同与 viewport 在 M2 同轮加入，避免共享迁移阶段混入重置行为变化。

### 6.4 非 Loaded 分支

股票分钟当前 `idle/loading/error/empty` 使用 feature 自己的模块空态。本轮保持该状态判断和文案，不用无点的 shared chart 伪装 Loaded。

### 6.5 M1 删除清单

从 `StockMinuteChartWorkspace.tsx` 删除：

1. `MinuteChartRefs`、`MinuteChartSyncTarget`、`SharedCrosshairState`。
2. `chartColors`、`minuteChartHeight`、`defaultVisibleMinuteBars`。
3. 全部 `createChart/addSeries/setData` 代码。
4. crosshair/visible range subscription 和 drag listeners。
5. `buildMinuteChartOptions()`、`MinutePanel()`。
6. 重复右边界赋值和所有 chart cleanup。

不得把这些代码移动到另一个 stock 文件或 fallback 分支。

### 6.6 M1 视觉验收

必须对比：

1. 根容器、图表区、四 pane 和 34px 空轨道几何偏差不超过 2px。
2. 四 pane 时间轴、原生轴标签、状态块和 hover Tooltip 保持。
3. Tooltip 行顺序、位置避让、单位和颜色不变。
4. 允许 DOM class 从 stock pane/host 切为 shared pane/host，但不能靠页面补偿坐标维持外观。
5. 若 shared 内部 canvas 绘制出现超出上述合同的可见差异，M1 停止，不得添加临时 legacy chart 分支。

---

## 7. M2：Viewport 纯函数

### 7.1 唯一常量

新文件 `detailChartViewport.ts` 是唯一常量事实源：

```ts
export const MIN_VISIBLE_BARS = 45;
export const MAX_VISIBLE_BARS = 180;
export const ZOOM_STEP_BARS = 15;
export const DEFAULT_VISIBLE_BARS = 120;
export const MIN_ADAPTIVE_DEFAULT_BARS = 75;
export const MAX_ADAPTIVE_DEFAULT_BARS = 150;
export const TARGET_PIXELS_PER_BAR = 9.5;
export const RIGHT_PRICE_SCALE_WIDTH = 56;
export const LATEST_RANGE_TOLERANCE = 0.5;
```

CSS 只写控件像素，不复制 K 线根数或步长。测试从实现文件 import 常量，不另建同值 fixture。

### 7.2 类型

```ts
export interface DetailChartLogicalRange {
  from: number;
  to: number;
}

export interface DetailChartZoomAvailability {
  canZoomIn: boolean;
  canZoomOut: boolean;
}
```

### 7.3 自适应默认

```ts
resolveAdaptiveVisibleCount(
  klineHostWidth: number,
  pointCount: number,
): number
```

固定流程：

```text
if pointCount <= 0 => 0
if hostWidth 非有限或 hostWidth <= 56 => base = 120
else plotWidth = hostWidth - 56
raw = plotWidth / 9.5
stepped = round(raw / 15) * 15
base = clamp(stepped, 75, 150)
result = min(base, pointCount)
```

`round` 使用标准四舍五入，不用 floor 或 ceil。当前 1600px 已有 shared 根宽约 1193px，绘图区约 1137px，计算结果为 120。

### 7.4 初始范围

```ts
resolveInitialRange(
  pointCount: number,
  visibleCount: number,
): DetailChartLogicalRange | null
```

规则：

1. 任一输入小于等于 0 返回 `null`。
2. `count=min(pointCount, visibleCount)`。
3. `to=pointCount-1`。
4. `from=to-(count-1)`。
5. 不能调用 `fitContent()` 代替非空初始范围。

### 7.5 缩放可用性

```ts
resolveZoomAvailability(
  visibleCount: number,
  pointCount: number,
): DetailChartZoomAvailability
```

```text
effectiveMin = min(45, pointCount)
effectiveMax = min(180, pointCount)
canZoomIn = pointCount >= 45 && visibleCount > effectiveMin
canZoomOut = pointCount >= 45 && visibleCount < effectiveMax
```

点数少于 45 时两个按钮都 disabled。

### 7.6 点击目标根数

```ts
resolveZoomTargetCount(
  direction: "in" | "out",
  visibleCount: number,
  pointCount: number,
): number
```

1. `in`：`max(min(45, pointCount), visibleCount-15)`。
2. `out`：`min(180, pointCount, visibleCount+15)`。
3. 非 15 整数边界直接落到真实边界。

### 7.7 新 range

```ts
resolveZoomedRange(
  currentRange: DetailChartLogicalRange,
  targetCount: number,
  pointCount: number,
): DetailChartLogicalRange
```

算法：

1. `span=targetCount-1`。
2. 若 `abs(currentRange.to-(pointCount-1)) <= 0.5`，固定最新右边界。
3. 否则以 `(from+to)/2` 为中心生成目标范围。
4. 越过左边界时整体右移，越过右边界时整体左移。
5. `pointCount >= targetCount` 时最终 span 必须仍等于 `targetCount-1`。
6. 只有真实点数少于目标时才允许缩短 span。

### 7.8 同一序列追加数据

增加：

```ts
resolveRangeAfterPointCountChange(
  currentRange: DetailChartLogicalRange,
  previousPointCount: number,
  nextPointCount: number,
): DetailChartLogicalRange | null
```

1. 新点数为 0 返回 `null`。
2. 旧 range 贴近 `previousPointCount-1` 时，保留可见根数并右移到新最新点。
3. 旧 range 在历史区间时，保留中心和 span；只做新边界 clamp。
4. 点数缩短时不能返回负数或越过 `nextPointCount-1`。

---

## 8. Viewport 运行时状态

### 8.1 Canonical ref 与 UI state

shared 内部维护：

```ts
interface DetailChartViewportRefState {
  dataKey: string;
  lastMeasuredHostWidth: number | null;
  pointCount: number;
  range: DetailChartLogicalRange | null;
  userAdjusted: boolean;
}

interface DetailChartViewportUiState {
  dataKey: string;
  visibleCount: number;
}
```

规则：

1. `range` 与 `userAdjusted` 的唯一事实源是 ref，使其在 chart effect 清理/重建之间存活。
2. React state 只驱动按钮 disabled；state 中带 `dataKey`，避免新标的首帧短暂显示旧 disabled 状态。
3. `visibleCount` 不进入 chart 创建 effect 依赖。
4. 不写 URL、localStorage、sessionStorage 或全局 store。

### 8.2 Runtime ref

```ts
interface DetailChartRuntime {
  applyRange: (range: DetailChartLogicalRange) => void;
  getRange: () => DetailChartLogicalRange | null;
}
```

`runtimeRef` 由当前四 chart effect 设置和清空。缩放按钮只调用 `runtimeRef.current.applyRange()`，不得触发 props 变化或 chart 重建。

### 8.3 统一 commit

所有入口必须经过一个内部 `commitViewportRange()`：

```text
输入：range、userAdjusted 是否升级、是否写入四 chart
1. 更新 viewportRef.range
2. 需要时把 userAdjusted 从 false 升为 true；不得自动降回 false
3. 计算 visibleCount = round(to-from)+1，并 clamp 到真实点数
4. 仅 count/dataKey 改变时更新 React UI state
5. 调用 runtime.applyRange 同步四 chart
6. queue 时间轴 marker 更新
```

只有 `dataKey` 改变时，`userAdjusted` 才重置为 false。

---

## 9. Chart 生命周期与 effect 设计

### 9.1 M2 effect 依赖

chart 创建 effect 允许依赖：

```text
candleData
crosshairPresentation
dataKey
mainLines
points
primitives
timeAxisPlacement
timeMode
```

不得依赖：

```text
visibleCount
zoom availability
hoverIndex
tooltipSide
userAdjusted
```

当前图层切换仍可按现有窄范围重建 chart/series；本轮不扩大为 series diff 引擎。但重建前后的 viewport 必须恢复，不能重新初始化。

### 9.2 创建后的范围决策

创建四 chart 后按固定优先级决定 range：

1. `dataKey` 改变：清空旧 ref，读取 K 线 host 宽度，计算自适应默认，以最新点为右边界。
2. 同一 `dataKey` 且已有 range、点数不变：恢复已有 range，用于 MA/BOLL/趋势通道切换。
3. 同一 `dataKey` 且点数改变：调用 `resolveRangeAfterPointCountChange()`。
4. 无 range 但有点：计算自适应初始 range。
5. 无点：清空 viewport；不展示 controls。

### 9.3 visible range subscription

1. 保留 `isSyncingVisibleRange` 防递归。
2. 任一 source chart range 变化时，把同一 range 写入其它三个 chart。
3. subscription 回调更新 canonical range，但不能把 `userAdjusted` 自动改为 true；图表库内部重排不等于用户操作。
4. 点击和拖动入口自己明确传 `userAdjusted=true`。

### 9.4 拖动

沿用当前像素到 logical delta 算法，但调整：

1. pointerdown 只记录起点，不立即标记用户已调整。
2. 第一次产生非零并成功 clamp 的移动才设置 `userAdjusted=true`。
3. `button,select` 继续被 `target.closest()` 排除；zoom 按钮不得进入 drag state。
4. range span 在拖动中不变。

### 9.5 ResizeObserver

使用一个 observer 观察 K 线 host 与 KDJ host：

1. KDJ 尺寸变化：更新日线时间 markers。
2. K 线宽度变化且 `userAdjusted=false`：重新计算自适应默认，并继续贴近最新。
3. K 线宽度变化且 `userAdjusted=true`：不改 range，只让 `autoSize` 生效。
4. observer 回调合并到下一动画帧；若计算出的 visibleCount 未变，不调用 `setVisibleLogicalRange()`。
5. cleanup 取消动画帧并 disconnect observer。

---

## 10. 缩放控件

### 10.1 组件合同

新增纯组件：

```ts
interface DetailChartZoomControlsProps {
  canZoomIn: boolean;
  canZoomOut: boolean;
  onZoomIn: () => void;
  onZoomOut: () => void;
}
```

组件不 import `lightweight-charts`，不读取 pointCount，不计算 targetCount。

### 10.2 DOM

```tsx
<div className="detail-chart-zoom-controls" aria-label="K线缩放">
  <button
    aria-label="缩小K线，增加可见根数"
    disabled={!canZoomOut}
    type="button"
  >
    <DetailChartZoomIcon direction="out" aria-hidden="true" />
  </button>
  <button
    aria-label="放大K线，减少可见根数"
    disabled={!canZoomIn}
    type="button"
  >
    <DetailChartZoomIcon direction="in" aria-hidden="true" />
  </button>
</div>
```

顺序固定为缩小后放大。`DetailChartZoomIcon` 与 controls 放在同一文件，合同如下：

1. `out` 使用正式 Figma 组件内的 Supericons Phosphor `magnifying-glass-minus` 矢量；`in` 使用 `magnifying-glass-plus`。
2. 从节点 `583:534` 导出完整同源 SVG，以 `viewBox="0 0 16 16"` 内联；必须保留导出结果中约 `1.493px` 左右的 x/y 居中位移，不能只复制局部 path 后把它贴到左上角。不得手工重画，也不得使用纯文本 `−`/`＋`、Tabler 或其它近似图标。
3. SVG 固定 16×16，内部路径保持正式稿约 13.014×13.014 的居中留白，`fill="currentColor"`，`focusable="false"`，`aria-hidden="true"`。
4. 仓库当前没有 Phosphor/Supericons 运行时依赖，本轮不得为两个静态图标新增依赖；a11y 语义只由两个真实 button 的 `aria-label` 提供。
5. 45 根时 `canZoomIn=false`；达到 `min(180, pointCount)` 时 `canZoomOut=false`；数据少于 45 根时二者都为 false。

### 10.3 K 线 overlay

`DetailChartPane.overlay` 接收：

```tsx
<>
  {latest && isChartHovering ? renderTooltip(latest, tooltipSide) : null}
  {points.length > 0 ? <DetailChartZoomControls ... /> : null}
</>
```

控件存在不依赖指标是否完整；Partial 只要有 K 线就显示。

### 10.4 CSS

新增：

```css
.detail-chart-zoom-controls {
  bottom: 8px;
  display: flex;
  gap: 4px;
  position: absolute;
  right: 64px;
  z-index: 9;
}

.detail-chart-zoom-controls button {
  align-items: center;
  display: inline-flex;
  height: 28px;
  justify-content: center;
  width: 28px;
}

.detail-chart-zoom-controls svg {
  display: block;
  fill: currentColor;
  height: 16px;
  width: 16px;
}
```

其余背景、边框、圆角、hover、pressed、focus-visible 必须使用现有 Design Token；disabled 使用原生属性并按正式稿 45% 弱化。禁止：

1. 修改 Tooltip 的 `top/right/left`。
2. 修改 Y 轴浮标 `right:8px`。
3. 修改四 pane grid 比例或底栏高度。
4. 用 transform 缩放图表。

---

## 11. 四个 Adapter 的 M2 改动

### 11.1 股票日线

`StockChartWorkspaceProps` 增加必填 `tsCode`，`StockDetailPage` 传 `viewModel.stock.tsCode`：

```tsx
<DetailChartWorkspace dataKey={`stock:${tsCode}:day`} ... />
```

不得从 candle 内容猜 tsCode。

### 11.2 股票分钟

```tsx
<DetailChartWorkspace
  dataKey={`stock:${data.tsCode}:m${data.freq}`}
  ...
/>
```

频率切换即新 key，按新 host 和点数计算默认范围；分钟缓存仍由页面 controller 管理，viewport 不进入缓存。

### 11.3 指数日线

```tsx
<DetailChartWorkspace
  dataKey={`index:${viewModel.identity.tsCode}:day`}
  ...
/>
```

MA/BOLL/趋势通道只改变 `mainLines/mainPrimitives`，不改变 key。

### 11.4 指数分钟

```tsx
<DetailChartWorkspace
  dataKey={`index:${data.tsCode}:m${data.freq}`}
  ...
/>
```

`indicatorSource` 不参与 key；Gold 指标就绪或降级为 bars-only Partial 时，不能把用户观察区间重置回最新。M5-B 已删除 M5-A Mock 标识与来源分支。

---

## 12. 纵轴与趋势通道

1. `buildChartOptions().rightPriceScale.autoScale` 显式为 `true`。
2. zoom 只调用四 pane 的 `timeScale().setVisibleLogicalRange()`。
3. 不调用 `priceScale().applyOptions()` 动态写人工上下界。
4. 不改 OHLC、指标或趋势值，不使用 CSS scale。
5. `TrendChannelPanePrimitive.autoscaleInfo(start,end)` 继续只返回与可见 logical range 相交线段的端点极值。
6. 新增 primitive 单测，证明视窗外的极端通道值不会撑大当前纵轴。
7. 分钟模式仍不请求、不绘制趋势通道。

---

## 13. 状态矩阵

| 页面/模块状态 | points | 控件 | 行为 |
|---|---:|---|---|
| Loaded | `>=45` | 显示 | 按 range 决定 disabled |
| Loaded | `1..44` | 显示 | 两个按钮 disabled |
| Partial | `>0` | 显示 | 指标缺失不阻塞 K 线 |
| Loading/Idle | 0 | 不显示 | 保持现有骨架/模块态 |
| Empty | 0 | 不显示 | 保持空态 |
| Error | 0 | 不显示 | 保持错误与重试 |
| Forbidden | 0 | 不显示 | 保持权限态 |

本功能不增加异常码。按钮边界不是错误状态。

---

## 14. 测试设计

### 14.1 `detailChartViewport.test.ts`

至少覆盖：

1. host 约 1193px 得到 120 根。
2. 窄屏得到 75，宽屏得到 150。
3. `0/NaN/Infinity/<=56` 宽度回退 120。
4. pointCount 为 `0/30/44/45/60/100/180/300/500`。
5. 初始 range 始终以最新点结尾。
6. 连续 zoom in 最终 45，zoom out 最终 `min(180, pointCount)`。
7. 非 15 整数点数直接落到真实上限。
8. latest 锚点的右边界不动。
9. 历史中心缩放保持中心。
10. 左右越界整体平移，目标 span 不缩短。
11. append bar 的 latest 跟随与历史不跳转。
12. 点数缩短时 range 合法。

### 14.2 `DetailChartWorkspace.test.tsx`

测试 mock 必须记录 `createChart` options、当前 visible range、subscriptions 和 remove：

1. M1 阶段保留 90 根；M2 将断言替换为宽度计算后的 120 根。
2. 四 chart 每次得到完全相同 range。
3. 点击一次只产生四次 `setVisibleLogicalRange()`；`createChart` 总数不增加。
4. 连续点击到 45/180 后按钮 disabled。
5. 点击 button 不触发 drag listener。
6. dataKey 改变重置；overlay/primitive 引用改变恢复 range。
7. 用户 zoom/drag 后 resize 不重置；未交互时 resize 可更新默认。
8. append bar 的 latest/历史两种行为。
9. `autoScale=true` 写入四 chart options。
10. `bottom-pane/each-pane` 与两种 crosshair presentation options 正确。
11. accessory 与透明 34px spacer 的 DOM/ARIA 正确。
12. crosshair、Tooltip、axis label、时间 marker 和 cleanup 回归。

测试环境提供可控 `ResizeObserver`，测试主动发出宽度变化；不能用修改 window.innerWidth 代替 K 线 host 宽度。

### 14.3 股票分钟 adapter 测试

M1 后删除该测试文件内第二套 chart mock。改为 mock/capture `DetailChartWorkspace` props，验证：

1. OHLCV/amount、MACD/KDJ 和 null 字段映射。
2. `overlays={}`，不制造 MA/BOLL。
3. M1 的时间轴/crosshair/空轨道/accessory 策略。
4. M2 的 `stock:${tsCode}:m${freq}` key。
5. 状态文案、freq、Tooltip 行顺序、股/元单位和颜色。
6. loading/error/empty 不渲染 shared loaded chart。

### 14.4 其它 adapter 与页面测试

1. `StockChartWorkspace.test.tsx` 增加 tsCode/dataKey，并证明 MA/BOLL 切换保留 range。
2. 新增或补齐 `IndexChartWorkspace` 测试：dataKey、趋势 primitive、MA/BOLL/趋势切换不重置。
3. 补齐 `IndexMinuteChartWorkspace` 测试：dataKey、minute 时间、真实 Gold 指标、无 Mock 标识、Partial 有 K 线仍显示 controls。
4. `StockDetailPage.test.tsx` 证明日线 adapter 收到 tsCode，周期切换不增加请求。
5. `IndexDetailPage.test.tsx` 证明切标的/周期不会复用旧 key；右栏和权重请求不因 zoom 发生。

### 14.5 网络负向门禁

组件点击测试在调用前后记录 `fetch` mock 次数：缩放点击、drag 和 resize 的请求增量必须为 0。不能只凭代码审查宣称无请求。

---

## 15. 浏览器与像素验收

### 15.1 证据目录

实施阶段在本机使用：

```text
/private/tmp/goldenshare-detail-chart-zoom/
  m1-before/
  m1-after/
  m2-after/
  measurements.md
```

每张截图记录 URL、标的、周期、viewport、状态、hover 坐标和时间。M1/M2 完成后把最终路径和关键量测回填本文及门禁。

### 15.2 M1 基线

1600×1200 保存：

1. 股票日线静态与 hover。
2. 股票 5 分钟静态与 hover。
3. 上证指数日线趋势通道静态与 hover。
4. 上证指数 5 分钟静态与 hover。

M1 允许变化只有内部 DOM/class 和实现归属；普通 UI 几何偏差不超过 2px，字段、单位、时间轴、十字线、状态块和底轨不变。

实施证据（2026-08-12）：

1. 迁移前：`/private/tmp/goldenshare-detail-chart-zoom/m1-before/`；迁移后：`/private/tmp/goldenshare-detail-chart-zoom/m1-after/`。
2. 股票日线、股票 5 分钟、上证指数日线、上证指数 5 分钟均保存 1600×1200 静态基线；股票 5 分钟另保存迁移前后 hover 基线。
3. 股票 5 分钟 workbench、charts area、状态块的 `x/y/width/height` 前后差值均为 0px；28 个 Lightweight Charts canvas 的 `x/y/width/height` 前后差值均为 0px。
4. 迁移后 hover 仍显示 `20260410 15:00`、原七字段 Tooltip、四 pane 原生 crosshair 轴标签、同步竖线和底部日期标签；shared 自定义 Y 轴浮标未重复渲染。
5. 1600×1200 页面 body 为 1600×1200，无横向或纵向新增溢出；四场景均无放大/缩小按钮。

### 15.3 M2 场景

1. 股票日线 120/45/180，对照正式节点 `588:524` 与密度节点 `593:1095`。
2. 股票分钟 120、历史中心 zoom、Tooltip，对照 `591:1711`。
3. 上证指数日线 120、趋势通道、Tooltip，对照 `590:613`。
4. 指数分钟 1/60/120 分钟、真实 Gold 指标与 bars-only Partial，对照 `592:918`；M5-B 不再保留模拟指标标识。
5. 数据少于 45、介于 45 与默认、少于 180。
6. 宽度变化触发 75/150 clamp。
7. 切换 MA/BOLL/趋势通道后 range 不变。
8. 切换标的/周期后按新数据重置。
9. Available/Min45/Max180/ShortData 对照组件集 `585:550`；按钮交互态对照 `583:534`。

允许视觉变化仅限缩放按钮、K 线横向密度和可见数据导致的纵轴范围；其它布局按 `597:1120` 的 2px 门禁，图表、趋势通道、坐标轴、Tooltip 和十字线不得位移。

实施证据（2026-08-12）：

1. 截图目录：`/private/tmp/goldenshare-detail-chart-zoom/m2-after/`；已保存股票日线默认 120、最小 45、最大 180、股票 5 分钟和上证指数日线 1600×1200 截图。
2. 1600×1200 股票页面实测图表根宽 `1193.20px`、图表区宽 `1191.20px`；控件 `60×28px`，两个按钮均为 `28×28px`、间距 `4px`，几何与正式稿一致。
3. 股票日线连续放大到 45 后放大按钮原生 disabled；连续缩小到 180 后缩小按钮原生 disabled；图表区、workspace 与右栏几何保持不动。
4. 本条记录的是 2026-08-12 M5-A 历史验收：上证指数日线保留趋势通道与缩放控件；指数 1/60/120 分钟显示真实 K 线、当时的模拟指标标识和缩放控件；切回日 K 后趋势通道和控件恢复。M5-B 当前合同已改为真实 Gold 指标并删除该标识，当前验收见指数详情 LLD。
5. 股票 5 分钟保留分钟工作台和缩放控件；指数/股票分钟缩放前后右栏文本完全一致；干净页面会话无 console error。
6. 1050/1900 viewport smoke 未出现控件尺寸漂移或新增页面横向溢出；自适应 75/150 的精确 logical range 由可控 ResizeObserver 组件测试锁定。

---

## 16. 文件级改动清单

### 16.1 M1

| 文件 | 改动 |
|---|---|
| `detailChartTypes.ts` | 增加 accessory、可选底栏和两项展示策略；暂留 `visibleBars` |
| `DetailChartWorkspace.tsx` | 接入展示策略、accessory、透明底轨；仍固定 90 |
| `detail-chart-workspace.css` | 增加透明底轨结构样式，不加 zoom 样式 |
| `StockMinuteChartWorkspace.tsx` | 改为状态 + shared adapter；删除独立生命周期 |
| `DetailChartWorkspace.test.tsx` | 展示策略、accessory、spacer 回归 |
| `StockMinuteChartWorkspace.test.tsx` | 改为 adapter/state 测试，删除独立 chart mock |

### 16.2 M2

| 文件 | 改动 |
|---|---|
| `detailChartViewport.ts` | 新增唯一常量和 range 纯函数 |
| `detailChartViewport.test.ts` | 新增算法测试 |
| `DetailChartZoomControls.tsx` | 新增纯按钮组件与 Figma 同源 Phosphor 放大镜内联 SVG，不新增依赖 |
| `detailChartTypes.ts` | 增加必填 dataKey，删除 public visibleBars |
| `DetailChartWorkspace.tsx` | viewport ref/runtime、按钮、resize、恢复/重置/append、autoScale |
| `detail-chart-workspace.css` | controls 的位置、按钮状态和 focus-visible |
| `StockChartWorkspace.tsx` | 增加 tsCode、传股票日线 dataKey |
| `StockDetailPage.tsx` | 传 `viewModel.stock.tsCode` |
| `StockMinuteChartWorkspace.tsx` | 传股票分钟 dataKey |
| `IndexChartWorkspace.tsx` | 传指数日线 dataKey |
| `IndexMinuteChartWorkspace.tsx` | 传指数分钟 dataKey |
| 相关测试 | helper/shared/adapter/page/primitive 回归 |

本轮不修改 `src/**` 后端文件、`lake_console/**` 或其它线程的市场总览文档。

---

## 17. 实施与提交顺序

### 17.1 M0 文档退出

1. 用户确认本文。
2. 门禁中的“LLD 经用户确认”勾选。
3. 保存 M1 前截图基线。
4. 以正式 Figma page `581:516` 和节点映射作为 M2 视觉验收基线；不得用其代替 M1 的真实浏览器迁移前截图。

### 17.2 M1 提交

建议提交：

```text
refactor(wealth): migrate stock minutes to shared detail chart
```

退出条件：

1. 股票分钟不再 import/create chart。
2. 四类图表都消费 shared。
3. 仍为 90 根，无 zoom controls。
4. typecheck/test/build 和 1600×1200 无漂移通过。

当前状态：1～4 已通过；M1 已由提交 `b38ac20e` 独立提交。

### 17.3 M2 提交

建议提交：

```text
feat(wealth): add adaptive detail chart zoom controls
```

退出条件：

1. 45/180/15、120、9.5px、75～150 全部通过。
2. 四 pane 同 range、纵轴 autoscale、dataKey/resize/overlay/append 通过。
3. 点击不重建 chart、不请求 API。
4. 四类页面浏览器和视觉验收通过。

当前状态：1～4 已通过；M2 已由提交 `61a5adea` 独立提交。

### 17.4 文档对账

实施结果同步回：

1. 本文。
2. benchmark、implementation design、coding gate。
3. `component-guidelines-baseline.md`。
4. 股票分钟 API 文档和指数详情原 LLD 中的历史/目标说明。

只暂存本任务文件；不得暂存当前工作区的 Lake、Dagster、市场总览或其它线程改动。

M3 已逐文件审计 `component-guidelines-baseline.md`、股票分钟 API 文档和指数详情原文档的既有未提交差异，仅在图表共享与缩放相关段落增量同步当前事实；其它线程内容未覆盖、未删除，提交时仍需按文件和补丁范围复核。

---

## 18. 验证命令

M1 和 M2 分别执行：

```bash
npm --prefix wealth run typecheck
npm --prefix wealth run test
npm --prefix wealth run build
git diff --check
```

实施前后另做：

```bash
rg -n "createChart|IChartApi|CandlestickSeries|HistogramSeries|LineSeries" \
  wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.tsx

rg -n "MIN_VISIBLE_BARS|MAX_VISIBLE_BARS|ZOOM_STEP_BARS|TARGET_PIXELS_PER_BAR" \
  wealth/src --glob '*.ts' --glob '*.tsx'
```

第一条 M1 后必须无匹配；第二条除 `detailChartViewport.ts` 和直接 import/测试引用外，不得出现重复字面常量定义。

---

## 19. 风险与控制

| 风险 | 当前根因 | 控制 |
|---|---|---|
| 股票分钟迁移漂移 | 时间轴、axis label、底轨与 shared 默认不同 | 稳定展示策略 + 前后 hover 截图 |
| overlay 后跳回最新 | chart effect 重建且当前范围只在局部变量 | canonical range ref + dataKey |
| 点击重建四 chart | visibleCount 进入 effect 依赖 | runtime ref + createChart 次数测试 |
| resize 覆盖用户选择 | 每次宽度变化重算默认 | `userAdjusted` 单向门禁 |
| 追加 bar 时历史视图跳转 | 只按新 pointCount 初始化 | previous/next pointCount 纯函数 |
| 趋势通道撑大价格轴 | primitive 使用全量端点 | visible autoscaleInfo 独立测试 |
| 小数据制造空白 | 强制最少 45 | 少于 45 显示全部且双 disabled |
| 配置漂移 | 页面自行传 visibleBars | 删除 public override，常量唯一 |
| 两套实现复活 | 旧股票分钟代码保留 fallback | import 检索 + 禁止兼容分支 |

---

## 20. 边界与依赖矩阵结论

1. 本轮只修改 `wealth/src/shared`、`wealth/src/features`、`wealth/src/pages` 和对应文档/测试。
2. 不影响 `foundation/ops/biz/app` 子系统依赖矩阵。
3. shared 不 import stock/index DTO；领域 adapter 负责映射。
4. 页面继续负责请求、缓存、Abort 和周期切换；shared 不发网络请求。
5. 本轮无需更新 `docs/architecture/codegraph-architecture-snapshot.md`，因为后端子系统边界和主要 API contract 不变；前端共享组件消费者变化在本文记录。

---

## 21. 待拍板项

无新的产品参数。正式 Figma、技术方案和本文已完成一致性对账；代码审计发现的股票分钟展示差异已收敛为 shared 的正式通用展示合同，不改变已确认的业务交互。

M1 与 M2 均已按本文完成实现、验收和独立提交；M3 文档对账已完成。本专项没有未完成的功能里程碑。

---

## 22. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.4 | 2026-08-16 | 收敛指数分钟当前结构注释：真实 Gold adapter、bars-only Partial、无 Mock 标识；不改变共享图表合同 | Codex |
| v1.3 | 2026-08-12 | 完成 M3 文档对账，登记 M1 `b38ac20e`、M2 `61a5adea`，清除待提交和原文档待同步口径 | Codex |
| v1.2 | 2026-08-12 | 回填 M2 实现文件、45/120/180 与 resize/append/dataKey 测试、Figma 同源控件、27 test files / 152 tests 全量回归和浏览器截图证据 | Codex |
| v1.1 | 2026-08-12 | 对齐正式 Figma page `581:516`；补齐节点映射、同源 Phosphor 放大镜 SVG 合同、边界 disabled 方向及像素验收依据 | Codex |
| v1 | 2026-08-12 | 基于当前四消费者、shared 生命周期、股票分钟独立实现、CSS、测试和本地运行页面完成实现级 LLD | Codex |
