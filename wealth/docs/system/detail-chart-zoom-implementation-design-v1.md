# 详情页共享图表与 K 线缩放技术实施方案 v1

> 状态：已完成。M1 共享收敛已提交为 `b38ac20e`，M2 缩放实现已提交为 `61a5adea`；M3 已完成专项文档与原始页面文档对账。
> 正式设计稿：[Goldenshare Web / 10 Detail Chart Zoom - Web Handoff](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=581-516&m=dev)
> 对应需求：[详情页 K 线缩放标杆需求 v1](./detail-chart-zoom-benchmark-requirement-v1.md)
> 对应 LLD：[详情页共享图表与 K 线缩放 LLD v1](./detail-chart-zoom-low-level-design-v1.md)
> 对应门禁：[详情页共享图表与 K 线缩放 M2 编码前门禁 v1](./detail-chart-zoom-m2-coding-gate-v1.md)

---

## 1. 文档目的

本文把已冻结的 K 线缩放需求拆成两个可独立验收的编码阶段：

1. 先完成股票分钟线到 `DetailChartWorkspace` 的共享收敛，不增加缩放功能，不改变现有视觉和交互。
2. 共享收敛通过后，再在唯一图表引擎中实现按钮缩放、自适应默认根数和纵轴自动适配。

本文不修改 API/DTO、后端查询、Lake Reader 或业务数据口径。正式 Figma 已在方案阶段完成升级；实施阶段只按其开发，不得自行改稿或用代码补偿偏差。

## 1.1 设计稿、方案与 LLD 的职责映射

| 正式设计范围 | 节点 | 技术落点 |
|---|---|---|
| 单按钮 10 个方向/状态变体 | `583:534` | `DetailChartZoomControls`、按钮状态与 a11y |
| 组合控件 4 个边界状态 | `585:550` | `canZoomIn/canZoomOut` 与 ShortData 状态 |
| 股票/指数、日线/分钟四场景 | `588:524`、`590:613`、`591:1711`、`592:918` | 四个 adapter 只传 shared 合同 |
| 45/120/180 根密度 | `593:1095` | `detailChartViewport.ts` 纯函数与边界测试 |
| 交互与状态 | `597:1107` | range 锚点、Loaded/Partial/异常态矩阵 |
| 几何与像素验收 | `597:1120` | 28×28、gap 4、组合宽 60、right/bottom 8px、偏差 <=2px |
| 正式开发映射 | `612:1132` | 编码、测试和截图证据对账入口 |

冲突处理：视觉和几何以正式 Figma 为准，组件职责、算法和生命周期以 LLD 为准；任何偏离必须先更新两者并重新评审。

## 1.2 跨模块抽象门禁原则适配

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一 | 可见范围只由 shared workspace 管理；页面和 adapter 不各自保存一份 | `DetailChartWorkspace` + viewport helper | 四消费者同一行为；删除股票分钟重复生命周期 |
| 契约先行 | 45/180/15、120、9.5px、75～150 和 data key 重置语义先冻结 | benchmark + shared props | helper 边界与组件交互测试 |
| 配置一致 | 本功能不新增 env、策略中心或页面常量配置 | shared 常量 | 全仓检索只存在一组缩放常量 |
| 默认显式 | 宽度无效回退 120；数据不足显示全部；新数据重置，图层切换不重置 | viewport reducer/helper | 0 宽、短数据、resize、dataKey、overlay 测试 |
| 排序与筛选确定 | 不改变数据顺序；range 基于已排序点数组 logical index | shared viewport | 首尾 clamp、历史中心锚定测试 |
| 性能预算前置 | 缩放不得重建 chart、重建 series 或发 API；单次只同步四个 range | runtime ref | createChart/fetch 调用次数断言 |
| 可观测与异常标准化 | 无新后端异常；按钮 disabled 是边界表达 | 原生 button/aria | disabled 与无数据状态测试 |
| 用户结果优先 | 以四类真实页面的根数、宽度、纵轴和无漂移为验收 | 浏览器/截图 | 1600×1200 四场景验收 |

## 2. 编码前代码审计与当前结论

### 2.1 M1 前已共享的实现

M1 开始前，`wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.tsx` 已经负责：

1. 创建 K 线、MACD、成交量、KDJ 四个 `lightweight-charts` 实例。
2. 统一设置四个 pane 的 visible logical range。
3. 四窗格 crosshair、悬浮 Y 轴标签、Tooltip 和横向拖动同步。
4. 日线/分钟时间轴模式。
5. MA/BOLL line series 和可选 pane primitive。
6. `handleScale=false`、`handleScroll=false`，避免图表库原生交互破坏四窗格同步。

当前真实消费者为：

| 消费者 | 模式 | 是否使用 shared |
|---|---|---|
| `StockChartWorkspace` | 股票日线 | 是 |
| `IndexChartWorkspace` | 指数日线 | 是 |
| `IndexMinuteChartWorkspace` | 指数分钟 | 是 |
| `StockMinuteChartWorkspace` | 股票分钟 | M1 前否；提交 `b38ac20e` 后是 |

M1 前 shared 常量为 `defaultVisibleBars=90`，`visibleBars` 是可选 props，消费者没有统一响应式策略。M2 提交 `61a5adea` 已删除该覆盖入口并以 `detailChartViewport.ts` 统一治理。

### 2.2 M1 前股票分钟线重复实现

M1 前 `StockMinuteChartWorkspace.tsx` 独立维护：

1. 四个 chart 的创建和销毁。
2. candle/line/histogram series 构造。
3. crosshair、Tooltip、visible range 和 pointer drag。
4. 独立 `defaultVisibleMinuteBars=90`、颜色和 chart options。
5. 独立 DOM/CSS class。

它与 shared 的职责重复，且存在机械重复，例如右边界 clamp 分支连续两次执行 `to = maxTo`。提交 `b38ac20e` 已删除这套独立生命周期；当前只保留分钟领域 adapter。

### 2.3 数据量与纵轴能力

当前页面请求量已经足够：

1. `StockDetailPage` 日线 `limit=300`，股票分钟 `limit=500`。
2. `useIndexDetailController` 指数日线 `limit=300`。
3. `useIndexMinuteSeries` 指数分钟 `limit=500`。
4. 上证趋势通道请求 `limit=300`，覆盖日线最多 180 根可视范围。

当前安装的 `lightweight-charts@5.2.0` 中，price scale 的 `autoScale` 默认值为 `true`，其语义就是按可见范围自动适配。目标实现仍在 `buildChartOptions()` 中显式写入 `rightPriceScale.autoScale=true`，避免依赖隐含默认值。`TrendChannelPanePrimitive.autoscaleInfo(start,end)` 也已只读取可见 logical range 内的通道端点。因此缩放只需改变横轴 logical range，不应新增人工纵轴倍率。

### 2.4 CodeGraph 影响面

本方案在编码前使用：

1. `codegraph_explore` 核验 shared engine、四类 adapter、请求 limit 和交互链。
2. `codegraph_impact` 核验 `DetailChartWorkspace` 与 `StockMinuteChartWorkspace` 的直接影响面。
3. JSX 动态消费者由 explore 与当前 import/渲染代码补充确认。

需要回归的真实影响面为：

1. `StockDetailPage -> StockChartWorkspace / StockMinuteChartWorkspace`。
2. `IndexDetailPage -> IndexChartWorkspace / IndexMinuteChartWorkspace`。
3. `TrendChannelPanePrimitive` 的 visible-range autoscale。
4. shared CSS、四窗格同步测试和两类页面浏览器视觉。

不影响 `src/foundation`、`src/biz`、`src/app` 或 API contract。

## 3. 目标结构

```text
wealth/src/shared/charts/detail-workspace/
  DetailChartWorkspace.tsx             # 唯一 chart 生命周期与 viewport 编排
  DetailChartPane.tsx                  # pane DOM
  DetailChartZoomControls.tsx          # 纯按钮组件
  detailChartViewport.ts               # 根数、range、锚点和 clamp 纯函数
  detailChartTypes.ts                  # dataKey 与 shared props
  detailChartSeries.ts                 # 既有 series 数据构造
  detailChartFormatters.ts             # 既有时间/轴格式化
  detail-chart-workspace.css           # shared 图表和缩放控件样式

wealth/src/features/stock-detail/chart/
  StockChartWorkspace.tsx              # 股票日线 adapter
  StockMinuteChartWorkspace.tsx        # 股票分钟状态 + adapter，不再创建 chart

wealth/src/features/index-detail/chart/
  IndexChartWorkspace.tsx              # 指数日线 adapter + trend primitive
  IndexMinuteChartWorkspace.tsx        # 指数分钟 adapter
```

禁止保留第二套 `createChart`、range sync、drag 或缩放实现。共享迁移完成后，`StockMinuteChartWorkspace.tsx` 不再直接 import `createChart`、series 构造器或 `IChartApi`。

## 4. 共享组件合同

### 4.1 Props 调整

`DetailChartWorkspaceProps` 增加必填 `dataKey`：

```ts
interface DetailChartWorkspaceProps {
  dataKey: string;
  // 其余现有领域渲染 props 保持
}
```

各 adapter 必须传稳定身份：

| 场景 | dataKey 组成 |
|---|---|
| 股票日线 | `stock:${tsCode}:day` |
| 股票分钟 | `stock:${tsCode}:m${freq}` |
| 指数日线 | `index:${tsCode}:day` |
| 指数分钟 | `index:${tsCode}:m${freq}` |

`visibleBars?: number` 从 public props 删除。缩放根数是系统统一交互合同，不能由各页面重新覆盖。

行为：

1. `dataKey` 改变：清除用户交互标记，按新容器宽度和新数据量重建默认范围。
2. 同一 `dataKey` 下仅 `mainLines/mainPrimitives` 改变：保留当前范围，不能跳回最新。
3. 同一 `dataKey` 下追加最新数据：若原视图贴近最新则继续跟随最新；若在历史区间则保留历史中心。

### 4.2 股票分钟 adapter

股票分钟点映射为 shared `DetailChartPoint`：

| shared 字段 | 股票分钟来源 |
|---|---|
| `time` | `timestamp` |
| `fullDate` | `tradeTime` |
| OHLC | 同名字段 |
| `volume/amount` | 同名字段 |
| `macd/dif/dea` | `macd/macdDif/macdDea` |
| `k/d/j` | `kdjK/kdjD/kdjJ` |
| `preClose/changePct/amplitude/turnoverRate` | `null` |
| `overlays` | 空对象；不得伪造分钟 MA/BOLL |

股票分钟 feature 继续负责：

1. loading/empty/error/ready 判断。
2. 状态文案与 `freq` 展示。
3. 分钟 Tooltip 的字段顺序、股/元单位和相对本 bar 开盘价的颜色。
4. MACD、成交量、KDJ 标题值。

为了迁移阶段无视觉漂移，shared workspace 提供一个通用 `topRightAccessory?: ReactNode` 槽位承载当前股票分钟状态块；shared 只把节点放入相对定位的图表区，不理解状态语义，也不覆盖 accessory 自身的定位样式。该状态块只有一个渲染入口，不再在 pane header 或其它 shared 层重复承载。

LLD 代码与浏览器审计进一步确认，旧股票分钟和当前 shared 存在两项真实展示差异：旧分钟线在四个 pane 都显示图表库原生时间轴，并保留原生 crosshair 轴标签；shared 默认只在底部 pane 显示时间轴，并使用自定义轴浮标。为了实现“共享生命周期”与“M1 无视觉漂移”两个已确认目标，shared 增加稳定、领域无关的展示策略：

1. `timeAxisPlacement: "bottom-pane" | "each-pane"`，默认 `bottom-pane`；股票分钟传 `each-pane`。
2. `crosshairPresentation: "synchronized-overlay" | "native-axis-labels"`，默认 `synchronized-overlay`；股票分钟传 `native-axis-labels`。
3. `bottomBar` 改为可选；未提供时渲染透明的 34px 结构轨道，不伪造指标栏或分隔线。股票分钟使用该空轨道。

这些是 shared 的正式展示合同，不是临时兼容分支；M1 完成后旧股票分钟 chart、pane 和同步实现仍必须全部删除。缩放逻辑不读取这些展示策略。

## 5. Viewport 状态设计

### 5.1 单一状态

shared 内部以 ref 保存 canonical viewport，以最小 React state 驱动按钮：

```ts
interface DetailChartViewportRefState {
  dataKey: string;
  lastMeasuredHostWidth: number | null;
  pointCount: number;
  range: { from: number; to: number } | null;
  userAdjusted: boolean;
}

interface DetailChartViewportUiState {
  dataKey: string;
  visibleCount: number;
}
```

chart API 引用和 `applyVisibleRange()` 存放在 runtime ref 中。`range/userAdjusted` 的唯一事实源是 viewport ref；React state 只驱动按钮 disabled/aria，不得把 `visibleCount` 放回 chart 创建 effect 的依赖并导致每次点击销毁重建四个 chart。精确 commit 顺序以配套 LLD 为准。

### 5.2 纯函数

`detailChartViewport.ts` 至少提供：

```ts
resolveAdaptiveVisibleCount(klineHostWidth, pointCount): number
resolveInitialRange(pointCount, visibleCount): LogicalRange | null
resolveZoomedRange(currentRange, targetCount, pointCount): LogicalRange
resolveZoomAvailability(visibleCount, pointCount): { canZoomIn; canZoomOut }
```

冻结常量集中在该文件：

```ts
MIN_VISIBLE_BARS = 45
MAX_VISIBLE_BARS = 180
ZOOM_STEP_BARS = 15
DEFAULT_VISIBLE_BARS = 120
MIN_ADAPTIVE_DEFAULT_BARS = 75
MAX_ADAPTIVE_DEFAULT_BARS = 150
TARGET_PIXELS_PER_BAR = 9.5
RIGHT_PRICE_SCALE_WIDTH = 56
```

其它页面、adapter、测试 fixture 和 CSS 不得复制这些业务常量。

### 5.3 Logical range 口径

`visibleCount` 表示数据点数量，logical span 为 `visibleCount - 1`：

```text
latest-anchored: to = pointCount - 1
latest-anchored: from = to - (visibleCount - 1)
```

历史中心锚定：

1. `center=(from+to)/2`。
2. 新范围为 `center ± (targetCount-1)/2`。
3. 若越过左边界，整体右移；若越过右边界，整体左移。
4. clamp 后仍保持目标 span，除非 `pointCount < targetCount`。

“贴近最新”使用不超过 0.5 logical index 的容差，避免浮点拖动导致锚点误判。

### 5.4 Resize 与重建

1. `ResizeObserver` 观察 K 线 host，而不是浏览器 window。
2. `userAdjusted=false` 时，宽度变化重新计算自适应默认并同步四 pane。
3. `userAdjusted=true` 时，resize 保持当前可见根数和锚点，只让 chart 自身 auto-size。
4. chart 因图层变化需要重建时，优先恢复 `rangeRef`；只有 `dataKey` 改变才使用初始范围。
5. 组件卸载时清除 observer、range subscription、crosshair subscription 和 pointer listener。

## 6. 缩放控件实现

`DetailChartZoomControls` 由 shared workspace 渲染到 K 线 `DetailChartPane.overlay` 中，与领域 Tooltip 并列：

```tsx
<>
  {tooltip}
  <DetailChartZoomControls ... />
</>
```

定位：

1. `.kline-panel` 继续作为 `position: relative` 容器。
2. 控件 `position:absolute; right:64px; bottom:8px; z-index:9`，其中 64px = 56px 价格轴 + 8px 安全间距。
3. 两个按钮 28×28px、间距 4px；颜色、边框、圆角和 focus-visible 使用现有 Design Token。
4. 缩小/放大分别使用正式组件中的 Supericons Phosphor `magnifying-glass-minus` / `magnifying-glass-plus`；16×16 图标容器、约 13×13 居中矢量、`currentColor`。仓库没有相应运行时包，因此从正式 Figma 节点导出同源矢量并在组件内以内联 SVG 固化，不新增依赖。
5. 禁止使用纯文本 `−`/`＋`、Tabler 或其它近似图标替代；SVG 设 `aria-hidden`，语义只由 button 的 `aria-label` 提供。
6. Tooltip 位于主图上部，现有 Y 轴浮标位于价格轴内；新控件不得改动两者的位置。
7. pointer drag 的 `startDrag()` 已忽略 `button,select`，必须用组件测试确认点击不会进入 drag state。

事件：

1. `onZoomIn`：`target=max(45, visibleCount-15)`。
2. `onZoomOut`：`target=min(180, pointCount, visibleCount+15)`。
3. 调用 shared `applyVisibleRange()` 一次，由它同步四个 chart。
4. 更新 `visibleCount/range/userAdjusted`，不调用 `fitContent()`。

## 7. 分阶段实施

### M0：文档与基线

1. 冻结三件套、影响面和常量。
2. 正式 Figma page `581:516`、组件、四场景、密度、状态与几何节点完成 `APPROVED FOR WEB DEVELOPMENT` 标记和开发映射。
3. 保存 1600×1200 股票日线、股票分钟、指数日线、指数分钟浏览器基线截图。
4. 记录四窗格、右轴、Tooltip、状态块和底部指标栏几何。

退出条件：本文已经用户确认；LLD 和 coding gate 完成实现级审计并等待最终评审；没有代码改动。

### M1：共享组件收敛

1. 为 shared 补齐股票分钟需要的通用槽位和 adapter 测试。
2. 将股票分钟 DTO ViewModel 映射为 `DetailChartPoint`。
3. 用 `DetailChartWorkspace timeMode="minute"` 替换股票分钟独立 chart 生命周期。
4. 删除股票分钟重复的 chart options、series、range sync、drag、crosshair 和 pane 组件代码。
5. 此阶段仍保持旧的 90 根默认值，确保结构迁移与产品行为变更可独立定位。
6. 完成 typecheck/test/build 和四页面浏览器回归；与基线的普通 UI 偏差不得超过 2px。

退出条件：四类图表全部走 shared；全仓不存在第二套详情页 chart 生命周期；缩放功能尚未加入。

实施结果（2026-08-12）：上述退出条件已满足。股票分钟 loaded 分支已成为 `DetailChartWorkspace` adapter；旧 chart options、series、range/crosshair/drag 同步和 pane 实现已删除，页面私有重复图表 CSS 同步清理。共享组件以 `each-pane + native-axis-labels + topRightAccessory + 34px transparent spacer` 保持迁移前动态表现，默认窗口仍为 90 根，页面无缩放按钮。

### M2：缩放与自适应默认

1. 新增 viewport 纯函数和 zoom controls。
2. 删除 public `visibleBars` 覆盖入口，启用统一常量。
3. 默认值从固定 90 改为自适应；1600px 精确为 120。
4. 接入 latest/历史中心锚点、边界 clamp、resize 与 dataKey 重置。
5. 验证纵轴 autoscale、趋势 primitive 和四 pane 同步。

退出条件：功能、组件、页面与视觉门禁全部通过。

实施结果（2026-08-12）：退出条件已满足。`detailChartViewport.ts` 成为 45/180/15、120、75～150、9.5px 和 56px 的唯一事实源；shared 以 canonical viewport ref 与 runtime ref 统一处理 latest/历史中心、resize、overlay 重建和 append bar。四个 adapter 均传稳定 `dataKey`；正式 Figma `583:534` 的 Phosphor 矢量以内联 SVG 固化，没有新增运行时依赖。单次点击只向四个 chart 写 logical range，不重建 chart，也不触发页面请求。

### M3：文档对账与提交

1. 把实施结果、截图路径和测试结果回填三件套及原股票/指数详情文档。
2. 独立提交 M1 共享收敛，再独立提交 M2 缩放功能。
3. 不暂存其它线程的 Lake、Dagster、市场总览或文档改动。

实施结果（2026-08-12）：M1 已以 `b38ac20e` 独立提交，M2 已以 `61a5adea` 独立提交；专项三件套、编码门禁、共享组件规范、股票分钟 API 文档和指数详情文档已同步当前实现。其它线程的 Lake、Dagster 和非本任务文档改动未纳入本轮暂存范围。

## 8. 测试与验证计划

### 8.1 纯函数

至少覆盖：

1. 1137px 绘图区得到 120 根。
2. 窄宽度 clamp 到 75，宽屏 clamp 到 150，无效宽度回退 120。
3. pointCount 为 0、30、60、100、300、500。
4. 45/180/实际点数边界和非 15 整数边界。
5. latest 锚点与历史中心锚点。
6. 左右边界 clamp 后目标 span 不缩短。

### 8.2 Shared 组件

1. 初始四 pane 接收相同 120 根范围。
2. 放大镜加号/减号每次改变 15 根，45 根时放大 disabled，最大可见根数时缩小 disabled。
3. 点击按钮不触发 drag、不调用 `fitContent()`、不重新 `createChart()`。
4. 用户缩放后 resize 不重置；未交互时 resize 更新自适应默认。
5. overlay/primitive 切换保留范围；dataKey 改变重置。
6. 纵轴保持 `autoScale=true`，不出现 CSS scale 或值变换。

### 8.3 Adapter 与页面

1. 股票分钟字段、单位、颜色、状态、Tooltip 与迁移前一致。
2. 股票日线 MA/BOLL、指数日线趋势通道、指数分钟模拟指标标识回归。
3. 真实页面周期/标的快速切换不串缩放状态。
4. 无数据/少数据/partial 状态按钮显示与 disabled 正确。

### 8.4 浏览器与截图

在 1600×1200 验收：

1. 股票日线默认 120、45、180。
2. 股票分钟默认 120、Tooltip、历史区间缩放。
3. 上证指数日线默认 120、趋势通道、Tooltip。
4. 指数分钟 1m/60m/120m 默认 120 与 Mock 标识。
5. 页面宽度变化后的 75～150 自适应边界。

截图按正式 Figma 节点 `588:524`、`590:613`、`591:1711`、`592:918` 对照场景；控件和密度分别对照 `585:550` 与 `593:1095`，普通 UI 几何继续执行 `597:1120` 的 <=2px 门禁。

M1 截图应与基线只允许 <=2px 普通 UI 偏差；M2 允许的视觉变化仅包括新增按钮、可见 K 线根数和由可见数据触发的纵轴范围。

验证命令：

```bash
npm --prefix wealth run typecheck
npm --prefix wealth run test
npm --prefix wealth run build
git diff --check
```

## 9. 性能与安全

1. 缩放只执行四次 `setVisibleLogicalRange()`，不得销毁/重建 chart 或 series。
2. 缩放按钮点击不得请求 API，网络请求数保持 0。
3. 不新增依赖；Supericons Phosphor 同源矢量以内联 SVG 固化，不开放任意 chart options 或脚本输入。
4. 不改变有限请求量，不扫描更多数据库或 Lake 文件。
5. ResizeObserver 回调必须去重到动画帧或同等轻量机制，避免 resize 风暴。

## 10. 风险与缓解

| 风险 | 触发条件 | 缓解动作 |
|---|---|---|
| 股票分钟迁移视觉漂移 | 独立 CSS 与 shared CSS 细节不同 | M1 独立提交；迁移前后截图和 DOM 几何逐项对账 |
| 每次缩放重建图表 | 把 visibleCount 放入 chart effect 依赖 | runtime ref 直接应用 range；测试锁定 createChart 次数 |
| 图层切换重置窗口 | chart effect 重新执行初始 range | `dataKey` 与 `rangeRef` 分离；overlay 回归测试 |
| 历史观察点跳回最新 | 所有缩放都固定右边界 | latest 容差判断；历史区间保持中心 |
| 趋势通道撑大纵轴 | primitive 使用全量端点 | 保留现有 visible-range autoscaleInfo 并测试 |
| 小数据边界显示过大 | 不顾 pointCount 强制 45 根 | 小于 45 显示全部且双按钮 disabled |
| resize 覆盖用户选择 | 每次宽度变化重算默认 | `userAdjusted` 门禁；仅未交互态自适应 |

## 11. 例外白名单

无。本文不偏离通用组件、图表坐标、真实 API 或视觉验收规则。

## 12. 待拍板项

无。正式设计稿、技术方案、LLD、编码门禁、实现与原始文档已经完成一致性对账。

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.4 | 2026-08-12 | 完成 M3：登记 `b38ac20e`/`61a5adea`，同步专项与原始文档并清除实施前现状表述 | Codex |
| v1.3 | 2026-08-12 | 回填 M2 实施结果、唯一常量/viewport 生命周期、四 adapter dataKey、27 test files / 152 tests 全量回归和浏览器验收 | Codex |
| v1.2 | 2026-08-12 | 对齐正式 Figma page `581:516`，补齐节点到代码/验收映射，并冻结同源 Phosphor 放大镜内联 SVG 实现 | Codex |
| v1.1 | 2026-08-12 | 记录方案已确认，链接实现级 LLD，并按当前代码修正股票分钟机械重复的审计描述 | Codex |
| v1 | 2026-08-12 | 初版：先收敛股票分钟共享图表，再统一实现 45～180 根按钮缩放与 120 根自适应默认 | Codex |
