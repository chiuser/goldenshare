# 详情页 K 线可见区间最高/最低价标注技术方案 v1

> 状态：前端开发与自动化门禁已完成；部署和人工交互验收按用户安排另行执行。
> 适用范围：股票日线、股票分钟线、指数日线、指数分钟线的 K 线主图区。
> 共享基础：[详情页共享图表与 K 线缩放技术实施方案 v1](./detail-chart-zoom-implementation-design-v1.md)
> 对应 LLD：[详情页 K 线可见区间最高/最低价标注 LLD v1](./detail-chart-visible-extrema-annotation-low-level-design-v1.md)
> 正式设计文件：[Goldenshare Web](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=581-516&m=dev)

---

## 1. 目标

在详情页 K 线主图区内，始终标出当前可见 K 线中的最高价和最低价。标注跟随用户当前看到的横轴范围变化，不按接口返回的全部历史数据固定计算。

本功能只增强图表展示，不修改行情 API、DTO、Lake 数据、前复权口径、技术指标或九转数据。

## 2. 已冻结产品口径

1. 最高点取当前可见 K 线中最大的 `high`，最低点取当前可见 K 线中最小的 `low`。
2. 标注只显示格式化后的价格值，例如 `124.80`、`54.96`；禁止显示“最高价”“最低价”等说明文字。
3. 多根可见 K 线具有相同最高价时，选择时间最近的一根；相同最低价同样选择时间最近的一根。
4. 箭头必须准确锚定所选 K 线的上影线最高点或下影线最低点。
5. 用户点击放大/缩小、左右拖动、切换股票或指数、切换日线/分钟周期、容器宽度变化或同一序列追加数据后，都必须按新的实际可见范围重新计算。
6. 标注只出现在 K 线主图区，不进入 MACD、成交量、KDJ 等副图区。
7. 股票日线、股票分钟线、指数日线、指数分钟线使用同一个共享实现和同一套交互规则。

## 3. 当前代码事实与影响面

当前四类图表均由：

`wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.tsx`

创建 K 线、MACD、成交量、KDJ 四个 `lightweight-charts` 实例，并由 `commitViewportRange(...)` 和 `subscribeVisibleLogicalRangeChange(...)` 维护统一 logical range。

真实消费者为：

| 场景 | Adapter | `dataKey` 口径 |
|---|---|---|
| 股票日线 | `StockChartWorkspace` | `stock:{tsCode}:day` |
| 股票分钟 | `StockMinuteChartWorkspace` | `stock:{tsCode}:m{freq}` |
| 指数日线 | `IndexChartWorkspace` | `index:{tsCode}:day` |
| 指数分钟 | `IndexMinuteChartWorkspace` | `index:{tsCode}:m{freq}` |

本轮在开发前已用 CodeGraph 核对上述 shared engine、四个 adapter、viewport helper 和 primitive 接入点。实现应继续收敛在 shared 图表目录，禁止四个 adapter 分别计算或绘制标注。

## 4. 可见范围计算

### 4.1 可见 K 线集合

输入：

- 由 `buildCandlestickData(points)` 生成、已按时间升序排列的可绘制 candle 数组。
- `lightweight-charts` 当前 `LogicalRange { from, to }`。

必须使用可绘制 candle 数组而不是原始 points。当前 series builder 会丢弃 OHLC 不完整的点；
只有 candle 数组的索引才与 candlestick series 的 logical index 一一对应。

只把中心 logical index 落入当前视口的完整 K 线计入统计：

```ts
startIndex = clamp(Math.ceil(range.from), 0, points.length - 1)
endIndex = clamp(Math.floor(range.to), 0, points.length - 1)
```

若范围无效、数组为空或 `startIndex > endIndex`，不显示任何最高/最低标注。边缘仅露出空白或半个 bar spacing 不得被错误计入。

### 4.2 极值与同值选择

只比较有限数值：

- `Number.isFinite(point.high)` 才参与最高价。
- `Number.isFinite(point.low)` 才参与最低价。

点数组已经按时间升序排列。扫描可见集合时：

- `high >= currentHigh` 时替换当前最高点。
- `low <= currentLow` 时替换当前最低点。

使用包含等号的比较保证相同价格最终保留时间最晚、也就是距离当前最近的那根 K 线。禁止通过字符串时间比较或重新排序改变原有序列顺序。

### 4.3 更新触发

极值选择的唯一输入是 shared viewport 与当前 points：

1. `subscribeVisibleLogicalRangeChange(...)` 返回新范围。
2. 放大/缩小通过 `commitViewportRange(...)` 写入新范围。
3. `dataKey` 改变。
4. 同一 `dataKey` 的 `points` 数量或内容改变。
5. resize 使自适应范围发生变化。

Primitive 每次绘制时读取 K 线 chart 的真实 visible logical range，并按规范化后的
`startIndex/endIndex` 缓存极值结果。Crosshair 移动可能触发 Canvas 重绘，但范围未变化时
必须命中缓存，不得重新扫描 points。Tooltip 更新、MA/BOLL tab 切换也不得引入独立极值状态。

## 5. 代码设计

### 5.1 新增纯计算 helper

新增：

`wealth/src/shared/charts/detail-workspace/detailChartVisibleExtrema.ts`

```ts
interface DetailChartVisibleExtremum {
  index: number;
  time: Time;
  value: number;
}

interface DetailChartVisibleExtrema {
  high: DetailChartVisibleExtremum | null;
  low: DetailChartVisibleExtremum | null;
}

function resolveVisibleExtrema(
  candles: readonly DetailChartVisibleCandle[],
  range: DetailChartLogicalRange | null,
): DetailChartVisibleExtrema;
```

该 helper 只扫描当前可见集合。系统当前可见根数上限为 180，因此单次复杂度为 `O(V)`、`V <= 180`，不得扫描接口返回的全部历史，也不得引入排序。

### 5.2 新增 K 线 series primitive

新增：

`wealth/src/shared/charts/detail-workspace/VisibleExtremaPrimitive.ts`

使用一个附着在 candlestick series 上的 pane primitive 绘制两组标注：

- 横坐标通过 `chart.timeScale().timeToCoordinate(extremum.time)` 获取。
- 纵坐标通过 candlestick series 的 `priceToCoordinate(extremum.value)` 获取。
- 文案使用现有价格 formatter，保持页面当前价格精度，不直接拼接固定两位小数常量。

禁止使用页面 DOM 绝对定位猜测坐标。这样缩放、拖动、纵轴 autoscale、主图宽度变化时，标注仍与上/下影线同坐标系。

Primitive 在 `draw(...)` 中读取当前 visible logical range；workspace 不复制第二份 extrema
React state，也不新增 visible-range subscription。candle data 变化时，沿用现有 shared chart
生命周期重建 primitive；范围未变化的重复 draw 使用 primitive 内部缓存。

### 5.3 标注几何

1. 标注由“一端带箭头的水平线段 + 价格文本”组成，不使用气泡卡片，也不把箭头、线段拆成彼此分离的装饰。Figma 和前端实现都应使用一条连续的矢量描边形成线段与开放箭头，禁止使用独立三角形拼接模拟箭头。
2. 箭头端必须指向所选 K 线的上影线最高点或下影线最低点；价格文本位于线段另一端。视觉关系固定为 `箭头端（K 线锚点）— 线段 — 价格文本`，其中只有 K 线锚点一端带箭头。
3. 线段的 `y` 坐标必须精确等于极值价格的 `priceToCoordinate(...)` 结果，价格文本以该线段垂直居中；禁止把最高价整体上移或把最低价整体下移，否则箭头不再指向真实价格坐标。
4. 锚点位于 plot 左侧 65% 范围时，线段和价格向右展开；位于右侧 35% 时向左展开。左右变体只改变展开方向，不改变箭头始终指向 K 线的语义。
5. 文本和引导线必须留在 plot area 内，不进入右侧价格轴，不被顶部/底部裁切。
6. 线段、箭头和价格统一使用详情图表高对比中性前景色；设计基准线宽为 `1.5px`，禁止使用低透明度灰色，也不使用涨跌红绿表达“高/低”。
7. 标注图层保持透明，不在真实 K 线图中增加黑色文本底板；深色背景只用于 Figma 组件展示区，避免白色设计画布降低可读性。
8. 标注不拦截鼠标事件，不影响拖动、缩放、crosshair 或 Tooltip。

### 5.4 `DetailChartWorkspace` 集成

共享 workspace 负责：

1. 用当前 `candleData` 创建一个 `VisibleExtremaPrimitive` 实例并附着到 `klineSeries`。
2. 继续由既有 canonical viewport 统一驱动四个 chart；不新增 extrema 专用 range state 或 subscription。
3. 在 chart 销毁时先 detach 内建 primitive，再清理外部 `mainPrimitives` 和 chart。
4. 不把极值放进四个页面 adapter props；该能力默认应用于所有真实 K 线主图。

现有九转、趋势通道等 `mainPrimitives` 保持原合同。可见极值 primitive 属于 shared 内建图层，不加入页面传入的业务 primitive 列表。

## 6. 状态与冲突处理

| 状态 | 行为 |
|---|---|
| Loading / Empty / Error | 无 candle 数据，不显示标注 |
| Loaded | 显示当前可见范围最高/最低价 |
| Partial / Delayed | 只要当前 candle 数据可绘制，就按实际可见数据标注 |
| Crosshair / Tooltip | 标注常驻；Tooltip 浮层优先，不改变极值选择 |
| 九转 marker / 趋势通道 | 可共存；不得移动业务 marker 的时间或价格锚点 |
| 同一根同时为最高和最低且价格不同 | 分别锚定该根 K 线的真实 high/low 坐标，不做垂直补偿 |
| 最高价与最低价的索引和值都相同 | 只绘制一个价格标注，禁止重复线条或虚假垂直补偿 |

## 7. Figma 交互设计范围

正式 Figma 在 `10 Detail Chart Zoom - Web Handoff` 页面中补充：

1. 共享 `Visible Extrema Annotation` 视觉组件，覆盖最高/最低、向左/向右四种几何状态。
2. 股票日线、指数日线、股票分钟、指数分钟四个 Web Handoff 主图区各增加一组价格标注。
3. 新增交互说明，明确标注随 zoom、横向拖动、周期/标的切换和数据追加重新计算。
4. 新增同值规则说明：相同极值选择时间最近的一根。
5. 标注示例只显示价格值，不出现“最高价”“最低价”。
6. 组件展示区使用独立深色背景提高对比度；四个真实主图区中的组件实例仍保持透明，不遮挡 K 线。

Figma 数值仅为视觉 fixture，不作为接口或测试金标。

### 7.1 正式节点台账

| 内容 | Figma 节点 | 验收结论 |
|---|---|---|
| 高对比组件展示框 | `716:639` | 深色展示背景只服务设计稿阅读；正式图表实例透明 |
| 共享标注组件集 | `703:631` | `Kind=High/Low` × `Direction=ExtendRight/ExtendLeft` 四变体；共享 `Value` 文本属性；使用单一矢量描边的开放箭头线 |
| 股票日线主图 | plot `588:581`，实例 `704:615` / `704:619` | 最高价向右展开、最低价向左展开 |
| 指数日线主图 | plot `590:672`，实例 `704:623` / `704:627` | 与股票日线使用同一组件 |
| 股票分钟主图 | plot `591:1768`，实例 `704:631` / `704:635` | 与日线使用同一视觉合同 |
| 指数分钟主图 | plot `592:977`，实例 `704:639` / `704:643` | 与股票分钟使用同一视觉合同 |
| 交互合同 | `705:641` | 明确当前可见范围、同值取最近、只显示价格、双坐标锚定 |

正式稿示例使用 `6.79` / `4.12`。四个场景均已回读实例属性与几何：箭头端与线段连续并指向影线极值，价格位于线段另一端；高点锚定左侧最高影线并向右展开，低点锚定右侧最低影线并向左展开。日线和分钟线代表场景已截图复核，标注对比度清晰，且未侵入右侧价格轴和缩放控件。

## 8. 测试与验收计划

### 8.1 纯函数测试

- 空数组、空范围和范围越界不返回标注。
- fractional logical range 只统计 `ceil(from)..floor(to)`。
- null、NaN、Infinity 不参与比较。
- 多个相同最高价选择最后一根。
- 多个相同最低价选择最后一根。
- 缩放或拖动改变范围后返回新的极值。

### 8.2 Primitive 与 workspace 测试

- 横坐标来自极值点 time，纵坐标来自 high/low price。
- 左右方向按可用空间切换。
- 标注文案只有价格值。
- range change 更新 primitive，不重建四个 chart。
- Crosshair 移动不触发极值重算。
- 股票/指数、日线/分钟四个 adapter 无私有极值实现。

### 8.3 浏览器验收

分别验证股票日线、股票分钟、指数日线、指数分钟：

1. 默认视口标注正确。
2. 放大、缩小后按新可见集合变化。
3. 左右拖动后按新可见集合变化。
4. 箭头与上/下影线准确对齐。
5. 不遮挡右轴、缩放按钮、Tooltip 和关键九转 marker。
6. 四个 pane 的横轴同步不回退，console/network 无新增错误。

## 9. 明确不做

- 不修改后端或行情数据。
- 不为最高/最低增加 API 字段。
- 不标注全量历史最高/最低。
- 不在副图区绘制极值。
- 不显示“最高价”“最低价”文字。
- 不提供关闭开关或配置项。
- 不在四个页面分别实现一套逻辑。

## 10. 后续推进

1. 按 LLD 依次完成 shared helper、geometry、primitive 和 workspace 接入。
2. 执行纯算法、primitive、workspace 与四 adapter 回归门禁。
3. 完成四场景浏览器验收后收口。

## 11. 变更记录

| 版本 | 日期 | 说明 | 作者 |
|---|---|---|---|
| v1.7 | 2026-08-20 | 完成 shared extrema helper、geometry、Primitive、workspace 接入及自动化回归；人工交互验收待用户执行 | Codex |
| v1.6 | 2026-08-20 | 按当前 series builder 事实将 logical index 输入收敛为可绘制 candle data，避免 OHLC 空值造成索引错位 | Codex |
| v1.5 | 2026-08-20 | 冻结完全平价窗口只绘制一个价格标注的去重口径，清除最后待定项 | Codex |
| v1.4 | 2026-08-20 | 完成代码级 LLD 审计；按最终参考稿纠正价格线垂直坐标、Primitive range 读取与缓存口径 | Codex |
| v1.3 | 2026-08-20 | 按参考图将标注重画为单一矢量描边的单端开放箭头线，修正左右变体箭头方向 | Codex |
| v1.2 | 2026-08-20 | 提升 Figma 展示对比度，冻结单端箭头线段、箭头指向影线与价格位于另一端的几何合同 | Codex |
| v1.1 | 2026-08-20 | 完成正式 Figma 共享组件、四场景实例和交互合同，并登记节点台账 | Codex |
| v1 | 2026-08-20 | 冻结可见区间、高低价、同值取最近、纯价格标注与四场景共享实现口径 | Codex |
