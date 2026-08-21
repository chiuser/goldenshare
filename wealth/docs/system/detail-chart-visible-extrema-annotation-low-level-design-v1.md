# 详情页 K 线可见区间最高/最低价标注 LLD v1

> 状态：已闭环完成。M1～M4、部署和用户人工交互验收均已通过。
> 日期：2026-08-20。
> 技术方案：[详情页 K 线可见区间最高/最低价标注技术方案 v1](./detail-chart-visible-extrema-annotation-implementation-design-v1.md)
> 共享基础：[详情页共享图表与 K 线缩放 LLD v1](./detail-chart-zoom-low-level-design-v1.md)
> 正式设计稿：[Goldenshare Web / 10 Detail Chart Zoom - Web Handoff](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=581-516&m=dev)

---

## 1. 目标与边界

### 1.1 开发目标

在 `DetailChartWorkspace` 的 K 线主图区增加共享可见区间极值标注：

1. 对当前实际可见的完整 K 线计算最高 `high` 和最低 `low`。
2. 多个相同极值选择时间最近、即 logical index 最大的 K 线。
3. 用单端开放箭头线准确指向影线极值，另一端只显示格式化价格。
4. zoom、横向拖动、resize、自适应范围、标的/周期切换和数据追加后自动更新。
5. 股票日线、股票分钟线、指数日线、指数分钟线共用一份实现。

### 1.2 本轮明确不做

1. 不修改后端、API、DTO、Reader、查询根数、Lake 或 Dagster。
2. 不增加最高价/最低价接口字段，也不修改 OHLC、前复权或技术指标语义。
3. 不修改 `DetailChartPoint` 的字段合同。
4. 不修改四个 feature adapter 的 props、请求或数据转换。
5. 不为标注增加开关、配置项、Tooltip、hover、点击或键盘交互。
6. 不影响主图 autoscale，不向价格轴或时间轴增加 primitive view。
7. 不修改九转 marker、趋势通道、MA/BOLL、MACD、成交量或 KDJ 的绘制规则。
8. 不在四个页面分别维护 extrema state、range subscription 或 DOM overlay。

### 1.3 实施原则

```text
buildCandlestickData(points) -> drawable candles
    + Kline chart visible logical range
    -> normalize visible integer indexes
    -> O(V) high/low selection, V <= 180
    -> timeToCoordinate + priceToCoordinate
    -> pure marker geometry
    -> one built-in candlestick series primitive
```

极值是前端展示派生状态，不是业务事实字段。它必须在共享 Canvas 坐标系内计算和绘制，
不得写回 view model、API contract 或页面状态。

---

## 2. 依据与代码审计

### 2.1 事实优先级

冲突时按以下顺序处理：

1. 用户最新明确指令：当前可见 K 线、只显示价格、同值取最近、单端箭头线。
2. 正式 Figma page `581:516` 及其共享组件、四场景实例和交互合同。
3. 本 LLD 与技术方案。
4. 当前 `dev-interface` 的 React、CSS、测试和 `lightweight-charts@5.2.0` 类型合同。
5. 历史详情页文档和参考稿。

### 2.2 CodeGraph 与当前引用审计

本轮在仓库根使用 `codegraph_status`、`codegraph_explore` 和 `codegraph_impact` 核对：

1. `DetailChartWorkspace` 是四类详情图表唯一 chart 生命周期实现。
2. 真实消费者为 `StockChartWorkspace`、`StockMinuteChartWorkspace`、
   `IndexChartWorkspace`、`IndexMinuteChartWorkspace`。
3. 四个 adapter 都只提供 `dataKey`、points、标题、Tooltip 和业务 primitive；
   没有独立 viewport 或极值绘制入口。
4. `codegraph_impact` 对 TSX JSX 动态引用不能完整列出消费者，因此又通过当前 import、
   adapter render 和测试 mock 做了交叉核验。开发验收不能只依赖 impact 输出。

### 2.3 `DetailChartWorkspace` 当前事实

`wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.tsx` 当前负责：

1. 创建 K 线、MACD、成交量、KDJ 四个 chart。
2. 创建 candlestick、line、histogram series。
3. 将外部 `mainPrimitives` 附着到 candlestick series。
4. 用 `commitViewportRange(...)` 保存 canonical range，并同步四个 chart。
5. 订阅四个 chart 的 `visibleLogicalRange`，支持 zoom、drag、resize 和 append。
6. chart effect 依赖 points、series 数据、业务 primitive 和显示模式；依赖变化时重建四图，
   但通过 `viewportRef` 恢复 canonical range。
7. 卸载时取消订阅、detach 外部 primitive 并移除 chart。

`buildCandlestickData(points)` 会丢弃 OHLC 不完整的点，因此 raw points index 不保证与
candlestick series logical index 一致。extrema 的正式输入必须是同一个 `candleData`；禁止
直接用原始 points 做 logical index 查找。

因此 extrema 不需要新建 React state 或第二个 range subscription。`lightweight-charts`
会在 visible range 或坐标变化时重绘 primitive；primitive 在 draw 时读取 K 线 chart 的真实范围即可。

### 2.4 当前 viewport 合同

`detailChartViewport.ts` 已冻结：

| 项目 | 当前值 |
|---|---:|
| 最少可见根数 | 45 |
| 最多可见根数 | 180 |
| zoom 步长 | 15 |
| 默认根数 | 120 |
| 自适应默认范围 | 75～150 |
| 右侧价格轴最小宽度 | 56px |

因此每次极值扫描最多处理 180 个 logical index，能够在 primitive 内执行；禁止为了这个
功能扫描接口返回的 300/500 根全量 points，也禁止排序。

### 2.5 当前 Primitive 合同

`NineTurnMarkerPrimitive` 和 `TrendChannelPanePrimitive` 已证明当前项目的接入方式：

1. 实现 `ISeriesPrimitive<Time>`。
2. 在 `attached(...)` 保存 `SeriesAttachedParameter`。
3. `paneViews()` 返回稳定的 view 引用。
4. renderer 使用 `target.useMediaCoordinateSpace(...)` 绘制。
5. 横坐标由 `timeToCoordinate(...)` 获取，纵坐标由 `priceToCoordinate(...)` 获取。
6. `autoscaleInfo()` 可返回 `null`，从而不改变价格范围。
7. `detached()` 清空 chart/series 引用。

`lightweight-charts@5.2.0` 的 `PrimitivePaneViewZOrder` 支持 `bottom | normal | top`。
extrema 必须使用 `top`，使开放箭头和数字位于 K 线、均线、九转和趋势线之上；现有 DOM
Tooltip 和 zoom controls 仍通过 CSS z-index 位于 Canvas 之上。

### 2.6 当前 formatter 与视觉 token

1. 价格统一使用 `formatPriceAxisValue(value)`，当前输出两位小数。
2. 主文字 token 为 `--cs-color-text-primary`，当前值 `#e5eef9`。
3. 数字字体 token 为 `--cs-font-family-number`。
4. primitive 运行在 Canvas，CSS custom property 需通过 `getComputedStyle` 读取，并提供 SSR/
   测试 fallback；不能把 `var(...)` 直接当成 Canvas 颜色。
5. K 线价格轴已设置 `scaleMargins: { top: 0.12, bottom: 0.12 }`，标注不再通过改 autoscale
   制造额外空间。

### 2.7 当前测试缺口

`DetailChartWorkspace.test.tsx` 已覆盖 viewport、zoom、drag、resize、append、Tooltip 和 cleanup，
但 chart mock 当前缺少：

1. series `priceToCoordinate(...)`。
2. primitive attached parameter 和 `requestUpdate()`。
3. 已附着 primitive 的可检查列表。
4. primitive renderer 的 media-space Canvas 测试能力。

新开发必须扩展既有 mock，不另建一套与真实 workspace 无关的页面 mock。

---

## 3. 方案与最终设计对账

### 3.1 已纠正的口径

技术方案旧表述曾写“最高价标注在锚点上方、最低价标注在锚点下方”。这与用户最终
参考图和 Figma 矢量组件不一致，现已纠正为：

1. 开放箭头尖端就是影线极值坐标。
2. 水平线段 `y` 与 `priceToCoordinate(value)` 完全一致。
3. 价格文字 `textBaseline = middle`，沿线垂直居中。
4. 不对 high 向上补偿，不对 low 向下补偿。

### 3.2 Figma 开发映射

| Figma | Web 实现 |
|---|---|
| component set `703:631` | `VisibleExtremaPrimitive` + pure geometry |
| High/Low | extrema kind，只影响数据来源，不改变颜色 |
| ExtendRight/ExtendLeft | `VisibleExtremaDirection` |
| `Value` property | `formatPriceAxisValue(extremum.value)` |
| vector `719:639..642` | Canvas `moveTo/lineTo` 的连续开放箭头路径 |
| 四个场景实例 | shared workspace 内建 primitive 自动覆盖四类 adapter |
| interaction contract `705:641` | visible range helper、同值取最近与范围变更测试 |

Figma 中的示例价格只用于视觉展示，不进入 fixture 金标。

---

## 4. 目标文件与职责

```text
wealth/src/shared/charts/detail-workspace/
  detailChartVisibleExtrema.ts
    # drawable candle 可见整数索引归一化、极值选择、范围缓存 key
  detailChartVisibleExtrema.test.ts
    # 纯算法边界和同值规则

  visibleExtremaGeometry.ts
    # 文本测量后的左右展开、边界回退和开放箭头几何
  visibleExtremaGeometry.test.ts
    # 锚点、方向、窄空间、裁切和去重分支

  VisibleExtremaPrimitive.ts
    # lightweight-charts lifecycle、缓存、坐标转换和 Canvas 绘制
  VisibleExtremaPrimitive.test.ts
    # primitive 生命周期、绘制和 autoscale 门禁

  DetailChartWorkspace.tsx
    # 创建/attach/detach 内建 primitive
  DetailChartWorkspace.test.tsx
    # shared 接入、range 变化、不重建、cleanup 回归
```

不修改：

```text
wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx
wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.tsx
wealth/src/features/index-detail/chart/IndexChartWorkspace.tsx
wealth/src/features/index-detail/chart/IndexMinuteChartWorkspace.tsx
wealth/src/shared/charts/detail-workspace/detailChartTypes.ts
wealth/src/shared/charts/detail-workspace/detail-chart-workspace.css
```

如果开发中发现必须修改上述冻结文件，先回到本文说明原因和影响，不允许临时加 props 或 CSS。

---

## 5. 纯计算合同

### 5.1 类型

`detailChartVisibleExtrema.ts` 定义并导出：

```ts
import type { Time } from "lightweight-charts";

import type { DetailChartLogicalRange } from "./detailChartViewport";

export interface DetailChartVisibleCandle {
  high: number | null;
  low: number | null;
  time: Time;
}

export interface DetailChartVisibleExtremum {
  index: number;
  time: Time;
  value: number;
}

export interface DetailChartVisibleExtrema {
  high: DetailChartVisibleExtremum | null;
  low: DetailChartVisibleExtremum | null;
}

export interface DetailChartVisibleIndexRange {
  endIndex: number;
  startIndex: number;
}

export function resolveVisibleIndexRange(
  range: DetailChartLogicalRange | null,
  pointCount: number,
): DetailChartVisibleIndexRange | null;

export function resolveVisibleExtrema(
  candles: readonly DetailChartVisibleCandle[],
  range: DetailChartLogicalRange | null,
): DetailChartVisibleExtrema;
```

### 5.2 可见索引归一化

算法固定为：

```ts
if (!range || points.length === 0) return null;
if (!Number.isFinite(range.from) || !Number.isFinite(range.to)) return null;

const startIndex = Math.max(0, Math.ceil(range.from));
const endIndex = Math.min(points.length - 1, Math.floor(range.to));
if (startIndex > endIndex) return null;
```

语义：只有 bar center 的 logical index 完整进入范围才参加计算。左右边缘只露出一部分的 K 线
不计入；这与技术方案的“用户当前能看到的完整 K 线”口径一致。

### 5.3 单次扫描

```ts
let high: DetailChartVisibleExtremum | null = null;
let low: DetailChartVisibleExtremum | null = null;

for (let index = startIndex; index <= endIndex; index += 1) {
  const candle = candles[index];
  if (!candle) continue;

  if (isFiniteChartNumber(candle.high) && (!high || candle.high >= high.value)) {
    high = { index, time: candle.time, value: candle.high };
  }
  if (isFiniteChartNumber(candle.low) && (!low || candle.low <= low.value)) {
    low = { index, time: candle.time, value: candle.low };
  }
}
```

硬约束：

1. 复用 `isFiniteChartNumber`，不复制数值合法性规则。
2. `>=` / `<=` 保证同值选择最后一个 logical index。
3. 不比较 `fullDate` 字符串，不排序，不创建 visible candle 副本。
4. high 与 low 独立选择；某一侧没有合法值时只隐藏该侧。
5. helper 不格式化价格、不读取 chart API、不写缓存。
6. workspace 必须传入 `buildCandlestickData(points)` 的结果，保证 logical index 与 series 对齐。

### 5.4 缓存 key

Primitive 持有固定 candle data 引用，缓存只需记录：

```ts
interface VisibleExtremaCache {
  endIndex: number;
  extrema: DetailChartVisibleExtrema;
  startIndex: number;
}
```

每次 draw 先归一化 range：

1. `startIndex/endIndex` 与 cache 相同：直接复用 extrema。
2. 任一不同：调用一次 `resolveVisibleExtrema(...)` 并覆盖 cache。
3. candle data 变化时现有 workspace effect 会销毁旧 primitive 并创建新实例，禁止增加 version。

这样 crosshair 导致的重复 Canvas draw 不会重复扫描 180 根数据。

---

## 6. 几何合同

### 6.1 类型与常量

`visibleExtremaGeometry.ts` 定义：

```ts
export type VisibleExtremaDirection = "extend-left" | "extend-right";

export interface VisibleExtremaMarkerLayout {
  arrowTipX: number;
  direction: VisibleExtremaDirection;
  lineEndX: number;
  lineStartX: number;
  textAlign: CanvasTextAlign;
  textX: number;
  y: number;
}
```

几何常量固定为：

| 常量 | 值 | 含义 |
|---|---:|---|
| `EXTREMA_LINE_LENGTH` | 28px | 箭头尖端到线段文字端 |
| `EXTREMA_MIN_LINE_LENGTH` | 12px | 窄边界时可缩短的最小线长 |
| `EXTREMA_ARROW_WING_LENGTH` | 6px | 开放箭头两翼水平长度 |
| `EXTREMA_ARROW_HALF_HEIGHT` | 4px | 开放箭头相对水平线的上下高度 |
| `EXTREMA_TEXT_GAP` | 8px | 线段末端到数字文本 |
| `EXTREMA_EDGE_PADDING` | 4px | plot 左右安全边距 |
| `EXTREMA_DIRECTION_SPLIT` | 0.65 | plot 左 65% 优先向右，右 35% 优先向左 |
| `EXTREMA_LINE_WIDTH` | 1.5px | 线段和开放箭头统一线宽 |
| `EXTREMA_FONT` | `600 12px number-font` | 数字样式 |

这些值来自正式 Figma 和当前高密度图表基线；不新增 CSS token。若实现期发现 1.5px 在
高 DPI Canvas 上模糊，只允许通过 media coordinate space 的像素对齐调整坐标，不改变视觉尺寸。

### 6.2 方向选择

先测量价格文本宽度：

```ts
const requiredWidth = lineLength + EXTREMA_TEXT_GAP + textWidth;
const leftAvailable = anchorX - EXTREMA_EDGE_PADDING;
const rightAvailable = mediaWidth - EXTREMA_EDGE_PADDING - anchorX;
const preferred = anchorX <= mediaWidth * 0.65 ? "extend-right" : "extend-left";
```

决策顺序：

1. preferred side 可容纳完整标注：使用 preferred。
2. preferred 不可容纳而 opposite 可容纳：翻转方向。
3. 两侧都不能容纳 28px 线：选择可用空间较大一侧，并将线缩短到 12～28px。
4. 若该侧连 `12px + gap + textWidth` 都无法容纳：本帧不画该标注，禁止裁切文本、侵入价格轴
   或覆盖成省略号。

正常详情页 plot 宽度不会触发第 4 条；它仅是窄容器和测试环境的 fail-safe。

### 6.3 开放箭头路径

向右展开时，箭头尖端在左侧 K 线锚点：

```text
anchorX,y  ←────────  text
```

Canvas 路径：

```ts
moveTo(anchorX + wingLength, y - halfHeight);
lineTo(anchorX, y);
lineTo(anchorX + wingLength, y + halfHeight);
moveTo(anchorX, y);
lineTo(lineEndX, y);
```

向左展开时水平镜像，箭头尖端仍是 K 线锚点：

```text
text  ────────→  anchorX,y
```

禁止：

1. 使用填充三角形。
2. 箭头和线段之间出现间隙。
3. 把价格放在箭头尖端一侧。
4. 把 line `y` 偏离价格坐标。
5. 增加黑色气泡或半透明背景。

### 6.4 文本布局

1. `textBaseline = "middle"`。
2. 向右展开时 `textAlign = "left"`，`textX = lineEndX + gap`。
3. 向左展开时 `textAlign = "right"`，`textX = lineEndX - gap`。
4. 文案只允许 `formatPriceAxisValue(value)` 的返回值。
5. 颜色使用 `--cs-color-text-primary`，fallback `#e5eef9`。
6. 数字字体使用计算后的 `--cs-font-family-number`，fallback 为
   `"DIN Alternate", "Roboto Mono", "SF Mono", monospace`。

### 6.5 垂直边界

文本和水平线都以真实 price coordinate 为中心。现有 12% price scale margin 是正常场景的
垂直安全区；primitive 不改 autoscale。若 y 在 media plot 外或文字高度会被顶部/底部裁切，
该侧标注本帧不画，禁止移动箭头离开真实价格点。

### 6.6 高低重叠

1. high 与 low 在同一根 K 线但值不同：分别画在真实 high/low y 坐标。
2. high 与 low 的 index 和 value 都相同：只绘制一个价格标注，禁止重复绘制或为了避让而
   修改真实价格坐标。

---

## 7. `VisibleExtremaPrimitive` 设计

### 7.1 类结构

```ts
export class VisibleExtremaPrimitive implements ISeriesPrimitive<Time> {
  private attachedParameters: SeriesAttachedParameter<Time> | null = null;
  private cache: VisibleExtremaCache | null = null;
  private readonly candles: readonly DetailChartVisibleCandle[];
  private readonly view = new VisibleExtremaPaneView(this);

  constructor(candles: readonly DetailChartVisibleCandle[]) {
    this.candles = candles;
  }

  attached(parameters: SeriesAttachedParameter<Time>): void;
  detached(): void;
  paneViews(): readonly IPrimitivePaneView[];
  autoscaleInfo(): null;
  draw(target: CanvasRenderingTarget2D): void;
}
```

构造参数只接收与 candlestick series 完全相同的 drawable candle data。不接收原始 points、
adapter 类型、日线/分钟模式、stock/index 类型或页面配置。

### 7.2 生命周期

1. `attached(parameters)`：保存 chart/series/requestUpdate 引用，清空 cache。
2. `paneViews()`：始终返回同一 `[view]` 引用，避免图表库缓存失效。
3. `VisibleExtremaPaneView.zOrder()`：返回 `top`。
4. `autoscaleInfo()`：固定返回 `null`。
5. `detached()`：清空 attached parameters 和 cache，不保留 chart 引用。
6. 不实现 `hitTest()`，标注不接管鼠标、光标或点击。
7. 不实现 price/time axis views。

### 7.3 draw 顺序

```text
attached/points/range guard
    -> normalize visible integer range
    -> cache hit or resolve extrema
    -> media coordinate space
    -> resolve Canvas token/font
    -> high coordinate + geometry + draw
    -> low coordinate + geometry + draw
    -> restore context
```

具体门禁：

1. 未 attached、points 为空或 visible range 为 null：直接 return。
2. high/low 的 `timeToCoordinate` 或 `priceToCoordinate` 返回 null：只跳过对应侧。
3. 先 `context.save()`，结束时必须 `context.restore()`。
4. 每侧最多调用一次 `measureText()`。
5. 每侧使用一次 `beginPath()`；箭头两翼与主线在同一次 `stroke()` 中完成。
6. 不调用 React setState，不调用 `requestUpdate()`，不主动改变 visible range。
7. 不在 draw 内 map/filter/sort/slice points。

### 7.4 重绘与缓存语义

`lightweight-charts` 在 visible range、price scale、size 和 series 坐标变化时调用 primitive view。
Primitive 每次读取当前 chart range，因此：

| 事件 | 行为 |
|---|---|
| zoom | range index 变化，重新扫描最多 180 根 |
| drag | range index 跨入新 bar 时重算；同一整数范围内复用缓存 |
| crosshair | range 不变，复用缓存，只重画几何 |
| resize 且默认根数变化 | range 变化后重算 |
| resize 但 range 不变 | 复用 extrema，重算左右几何 |
| points append / overlay chart rebuild | 新 primitive + 新 candle data；现有 viewport range 恢复后计算 |
| dataKey 变化 | shared chart 重建并使用新 points，无旧 extrema 泄漏 |

---

## 8. `DetailChartWorkspace` 接入

### 8.1 创建顺序

在 candlestick `setData(candleData)` 后、外部 `mainPrimitives` 前创建：

```ts
const visibleExtremaPrimitive = new VisibleExtremaPrimitive(candleData);
klineSeries.attachPrimitive(visibleExtremaPrimitive);
primitives.forEach((primitive) => klineSeries.attachPrimitive(primitive));
```

内建 primitive 与外部业务 primitive 分开保存，禁止把它 push 进 `mainPrimitives`，原因：

1. extrema 是所有真实 K 线默认能力，不是 adapter 可选业务图层。
2. 避免改变 `DetailChartWorkspaceProps` 和四个消费者。
3. 保持九转、趋势通道的 memo/useEffect 依赖语义不变。

### 8.2 cleanup 顺序

```ts
klineSeries.detachPrimitive(visibleExtremaPrimitive);
primitives.forEach((primitive) => klineSeries.detachPrimitive(primitive));
charts.forEach((chart) => chart.remove());
```

不依赖 `chart.remove()` 隐式清理 primitive，测试必须显式证明 detach。

### 8.3 effect 与 state 门禁

1. 不新增 React state、ref 或 callback 保存 extrema。
2. 不修改 chart effect 依赖数组；`points` 已在依赖中。
3. 不修改 `commitViewportRange`、`syncVisibleRange`、zoom、drag 或 resize 算法。
4. 不新增 visible-range subscription。
5. 不修改 `DetailChartWorkspaceProps`。
6. 不触发 fetch，不改变 `dataKey`。

### 8.4 图层优先级

从低到高：

```text
grid / series
    -> bottom primitives: nine-turn, current trend primitive
    -> top primitive: visible extrema
    -> DOM mainLayerAccessory / crosshair overlays
    -> DOM Tooltip (z-index 8)
    -> DOM zoom controls (z-index 9)
```

Tooltip 覆盖 extrema 是允许的；用户当前 hover 信息优先。extrema 不做 Tooltip 避让，也不改变
九转时间/价格位置。

---

## 9. 四场景消费者边界

| 场景 | 当前 adapter | 本轮代码改动 |
|---|---|---|
| 股票日线 | `StockChartWorkspace` | 0 |
| 股票分钟 | `StockMinuteChartWorkspace` | 0 |
| 指数日线 | `IndexChartWorkspace` | 0 |
| 指数分钟 | `IndexMinuteChartWorkspace` | 0 |

四场景只通过 shared engine 自动获得能力。编码后必须检索确认：

1. `visibleExtrema` 只存在于 `shared/charts/detail-workspace`。
2. 四个 adapter 没有 extrema import、state、prop、DOM overlay 或 range subscription。
3. stock/index、daily/minute 的 `dataKey` 口径不变。
4. `mainPrimitives` 长度和顺序仍只反映九转/趋势业务 primitive。

---

## 10. 状态与异常行为

| 状态 | 行为 |
|---|---|
| points 为空 | 不显示 extrema；不创建页面占位 |
| high/low 非有限值 | 对应值不参与；不转为 0 |
| 只有 high 合法 | 只画最高价 |
| 只有 low 合法 | 只画最低价 |
| visible range 无完整 bar | 两侧都不画 |
| coordinate 返回 null | 只跳过对应 marker |
| plot 太窄 | 尝试翻转/缩线；仍放不下则隐藏对应 marker |
| Loading/Empty/Error | 没有真实 points，不显示 |
| Partial/Delayed 且有 points | 按当前实际 points 显示 |
| Tooltip 打开 | Tooltip 可覆盖 marker；marker 不改变选择 |

禁止在 console 持续打印 draw 错误。可预期的 null/range/窄空间均是静默 guard；开发错误由单测
和浏览器 console 验收发现。

---

## 11. 测试设计

### 11.1 `detailChartVisibleExtrema.test.ts`

至少覆盖：

1. 空 points、null range、NaN/Infinity range。
2. range 完全在 points 左侧、右侧和反向范围。
3. fractional range 使用 `ceil(from)..floor(to)`。
4. from/to 被 points 边界正确 clamp。
5. null/NaN/Infinity high/low 不参与。
6. 高低分别来自不同 K 线。
7. 相同最高价取 index 最大者。
8. 相同最低价取 index 最大者。
9. 不排序、不改变输入 points。

### 11.2 `visibleExtremaGeometry.test.ts`

至少覆盖：

1. anchor 在左 65% 内优先 extend-right。
2. anchor 在右 35% 内优先 extend-left。
3. preferred side 放不下时翻转。
4. 两侧都紧张时选空间更大一侧并缩线。
5. 连最小线和文本都放不下时返回 null。
6. extend-right 的 arrow tip 等于 anchor，价格在右侧。
7. extend-left 的 arrow tip 等于 anchor，价格在左侧。
8. line/text `y` 精确等于 price coordinate，不存在 high/low 垂直偏移。
9. 文本与 plot edge 保持 4px 安全距离。

### 11.3 `VisibleExtremaPrimitive.test.ts`

使用 fake attached parameters 和 fake media context 覆盖：

1. attached/detached 生命周期。
2. `paneViews()` 返回稳定引用，zOrder 为 top。
3. `autoscaleInfo()` 固定为 null。
4. 无 range、无 points、无坐标时不 draw。
5. time 坐标来自 `timeToCoordinate(extremum.time)`。
6. high/low 的 y 分别来自 `priceToCoordinate(value)`。
7. Canvas path 是开放箭头，不调用 fill/closePath 形成三角形。
8. 文案只有 `formatPriceAxisValue` 输出，不含中文标签。
9. token 不可用时使用固定 fallback。
10. range 整数边界不变的重复 draw 命中 cache；变化后只重算一次。
11. 完全重合 high/low 只绘制一个价格标注。

### 11.4 `DetailChartWorkspace.test.tsx`

扩展当前 `lightweight-charts` mock：

1. series 增加 `priceToCoordinate`。
2. `attachPrimitive` 调用 primitive 的 `attached(...)`，提供 chart、series、requestUpdate。
3. 保存每个 series 的 attached primitive 列表。
4. `detachPrimitive` 调用 primitive 的 `detached()` 并从列表移除。

新增断言：

1. candlestick series 固定附着一个内建 `VisibleExtremaPrimitive`。
2. 外部九转/趋势 primitive 仍按原顺序附着。
3. zoom/drag 不重建 chart，range 变化后 primitive 使用新范围。
4. crosshair 不改变 range，也不重新扫描 extrema。
5. overlay/mainLines 导致 chart 重建时 canonical range 保留，新 primitive 使用恢复后的范围。
6. unmount 显式 detach 内建和外部 primitive。
7. empty points 不产生 marker draw，但不破坏四 pane 骨架。

### 11.5 Adapter 回归

运行并保留四个 adapter 现有测试，证明：

1. `dataKey` 不变。
2. `mainPrimitives` 仍只有原业务 primitive。
3. 日线/分钟状态和 Tooltip 不变。
4. adapter 不新增 extrema props。

建议最小测试集合：

```bash
npm --prefix wealth run test -- \
  src/shared/charts/detail-workspace/detailChartVisibleExtrema.test.ts \
  src/shared/charts/detail-workspace/visibleExtremaGeometry.test.ts \
  src/shared/charts/detail-workspace/VisibleExtremaPrimitive.test.ts \
  src/shared/charts/detail-workspace/DetailChartWorkspace.test.tsx \
  src/features/stock-detail/chart/StockChartWorkspace.test.tsx \
  src/features/stock-detail/chart/StockMinuteChartWorkspace.test.tsx \
  src/features/index-detail/chart/IndexChartWorkspace.test.tsx \
  src/features/index-detail/chart/IndexMinuteChartWorkspace.test.tsx

npm --prefix wealth run typecheck
npm --prefix wealth run build
```

---

## 12. 浏览器与视觉验收

### 12.1 场景矩阵

每个场景验证默认、zoom in、zoom out、向左拖动、向右拖动：

1. 股票日线。
2. 股票分钟线，至少 1m 和 60m。
3. 指数日线。
4. 指数分钟线，至少 5m 和 60m。

至少额外准备一组同值最高/最低 fixture，验证“最近一根”选择。

### 12.2 几何验收

1. 箭头尖端与目标 wick 极值坐标误差不超过 1 CSS px。
2. 线段 y 与价格坐标误差不超过 1 CSS px。
3. 只显示价格，不出现“最高价/最低价”。
4. 左右展开方向合理，右侧不进入 56px price scale。
5. 文本、线段和箭头不被 plot 边界裁切。
6. 标注颜色达到主文字对比度，不使用低透明度灰。
7. Tooltip、zoom controls 可覆盖标注，交互仍正常。
8. 九转、趋势通道、MA/BOLL 与 extrema 同时开启时无坐标漂移。
9. 四个 pane 的时间轴和 crosshair 同步不回退。

### 12.3 性能观测

1. 反复 zoom/drag 时无明显掉帧。
2. crosshair 连续移动时 extrema scan 次数不随 mousemove 增长。
3. chart 创建次数与开发前一致；zoom/drag 期间为 0 次新增。
4. network 请求次数与开发前一致。
5. console 无新增 error/warning。

截图统一保存到：

```text
/private/tmp/goldenshare-detail-chart-visible-extrema/
```

---

## 13. 性能、边界与回滚门禁

### 13.1 性能门禁

| 项目 | 门禁 |
|---|---|
| 极值扫描 | `O(V)`，`V <= 180`，单循环 |
| crosshair 重绘 | 整数范围不变时必须命中 cache |
| 排序/复制 | 0 |
| React state | 0 个 extrema state |
| range subscription | 0 个新增 subscription |
| chart rebuild | zoom/drag/crosshair 为 0 |
| API/network | 0 个新增请求 |
| autoscale 扩张 | 0；`autoscaleInfo() === null` |
| adapter 私有实现 | 0 |

### 13.2 依赖与架构边界

1. 只改 `wealth/src/shared/charts/detail-workspace/**` 和对应 system docs。
2. 不影响根目录 `foundation / ops / biz / app` 依赖矩阵。
3. 不新增 npm dependency。
4. 不修改 API contract、异常码或配置项。
5. 不引入 legacy `platform/operations` 依赖。

### 13.3 回滚

功能完全位于 shared 内建 primitive。若验收失败，回滚顺序为：

1. 删除 `DetailChartWorkspace` 中 attach/detach 内建 primitive 的两处接入。
2. 删除三个新增模块及测试。
3. 保留既有四图、viewport、九转和趋势通道代码不变。

不需要后端、数据或配置回滚。

---

## 14. 已拍板边界

### D1：最高价与最低价完全相同的可见区间只显示一个标注

触发条件：

```text
high.index === low.index && high.value === low.value
```

例如可见区间内所有 K 线完全平价，或测试/停牌数据只有同一个有效价格。因为最终设计要求
标注必须位于真实价格 y 坐标，high/low 两条标注会完全重叠，不能再用“一个向上、一个向下”
的虚假垂直偏移解决。

**冻结结论：只绘制一个价格标注。**

原因：

1. 最高价和最低价在此时是同一个业务事实，重复两个相同数字没有新增信息。
2. 能保持箭头精确锚定真实价格，不引入补偿坐标。
3. 不会出现两条线重影、文字加粗或方向相互冲突。
4. 对正常 45～180 根行情没有行为影响，只处理极端平价窗口。

禁止同时画两个相反箭头，也禁止通过上下偏移制造两个并不对应真实价格的锚点。

---

## 15. 开发步骤与完成定义

### M1：纯算法与几何（已完成）

1. 实现 visible index 和 extrema helper。
2. 实现左右展开及开放箭头 geometry。
3. 完成纯函数正反测试。

验收：不修改 React、chart 或页面代码；算法测试全绿。

### M2：Primitive（已完成）

1. 实现生命周期、缓存、坐标转换和 Canvas draw。
2. 冻结 top zOrder、null autoscale、token fallback。
3. 实现 D1 的单标注去重分支。
4. 完成 primitive 测试。

验收：fake chart/media context 下几何和缓存全绿。

### M3：Shared workspace 接入（已完成）

1. 在 candlestick series 上 attach 内建 primitive。
2. cleanup 显式 detach。
3. 扩展 workspace chart mock 和回归测试。
4. 确认四个 adapter 零改动。

验收：zoom/drag 不重建，四场景 adapter 测试全绿。

### M4：浏览器验收与文档收口（已完成）

1. 用户已将实现部署到实际页面并完成人工交互验证。
2. 用户确认本需求功能符合预期，验收结论为合格。
3. 技术方案、LLD 和共享缩放文档的交叉引用已统一更新为闭环状态。

本次收口以用户在实际部署环境中的人工验收结论为准；未额外补写用户未提供的截图路径、
逐像素误差或独立性能量测数据。

### Definition of Done

1. 当前可见完整 K 线高低价选择正确，同值选择最近一根。
2. 开放箭头尖端准确指向 wick，价格在另一端且只显示数值。
3. zoom、drag、resize、append、dataKey/周期切换后更新正确。
4. 四个 adapter 没有私有实现或新 props。
5. 不修改 API、DTO、Lake、Dagster、请求量或业务指标。
6. 纯算法、primitive、workspace、四 adapter 测试通过。
7. `typecheck`、build 和浏览器矩阵通过。
8. D1 单标注去重分支已实现并有测试，不保留待定口径。

## 16. 实施记录

2026-08-20 已按本文完成：

1. 新增 drawable candle 可见极值纯算法及测试。
2. 新增左右展开、开放箭头与窄边界回退几何及测试。
3. 新增 `VisibleExtremaPrimitive`，实现 top z-order、null autoscale、整数范围缓存、
   token fallback 和完全平价单标注去重。
4. 在 `DetailChartWorkspace` candlestick series 内建 attach/detach；四个 adapter 零改动。
5. 开发中发现 raw points 与 candlestick logical index 在 OHLC 空值时可能错位，已按当前
   `buildCandlestickData` 事实改为传入同一 drawable `candleData`，并同步修正方案和本文。
6. 专项 8 个测试文件、50 项测试通过；Wealth 全量 38 个测试文件、257 项测试通过。
7. `npm run typecheck` 与 `npm run build` 通过。build 仅保留仓库既有的大 chunk 提示。
8. 用户已完成部署和实际页面人工交互验收，确认需求没有问题、验收合格；M4 已闭环。
9. 本专项没有待开发、待部署、待验收或待拍板事项。

## 17. 变更记录

| 版本 | 日期 | 说明 | 作者 |
|---|---|---|---|
| v1.4 | 2026-08-21 | 用户完成部署和实际页面人工交互验收，验收合格；关闭 M4 并完成专项文档收口 | Codex |
| v1.3 | 2026-08-20 | 完成 M1～M3 实现和自动化门禁，记录 drawable candle 索引修正与当时的 M4 验收边界；后续已由 v1.4 闭环 | Codex |
| v1.2 | 2026-08-20 | 按 `buildCandlestickData` 的过滤事实改用 drawable candle data，保证 logical index 与真实 series 对齐 | Codex |
| v1.1 | 2026-08-20 | 冻结完全平价窗口只绘制一个价格标注，清除开发前最后待定项 | Codex |
| v1 | 2026-08-20 | 完成当前代码、CodeGraph、Primitive、viewport、测试与 Figma 对账，形成代码级开发合同 | Codex |
