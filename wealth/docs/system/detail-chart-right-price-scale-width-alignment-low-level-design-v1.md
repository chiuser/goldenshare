# 详情页共享图表右侧价格轴宽度对齐 LLD v1

> 状态：开发完成，自动化验证通过，待用户部署与人工页面验收。
> 日期：2026-08-21
> 适用工程：`wealth`
> 适用组件：`DetailChartWorkspace` 及股票/指数、日线/分钟线四类消费者。
> 本文只定义前端共享图表布局修复，不修改行情数据、指标公式、API、DTO 或后端服务。

---

## 1. 问题与目标

当前详情页由四个独立的 `lightweight-charts` 实例组成：

1. K 线主图；
2. MACD；
3. 成交量；
4. KDJ。

四个实例已经同步同一份 logical range，但截图和代码审计均证明：K 线区的纵向网格线与
MACD、成交量、KDJ 的纵向网格线仍会逐渐错开，越靠右偏差越明显。

本轮目标固定为：

1. 四个 pane 的右侧价格轴使用同一个**实际像素宽度**；
2. 四个 pane 在相同 logical range 下拥有相同的实际绘图区宽度；
3. 同一时间点在四个 pane 中映射到同一 x 坐标；
4. 默认可视根数、拖动换算、缩放控件和右侧 Tooltip 使用同一轴宽事实；
5. 修复同时覆盖股票/指数、日线/分钟线，不增加页面私有分支；
6. 不改变任何行情值、指标值、时间键、请求数量或页面数据状态。

---

## 2. 依据与优先级

### 2.1 用户冻结口径

1. K 线区与三个指标区的纵向网格必须严格对齐。
2. 修复应解决根因，不能通过隐藏网格、手工偏移某个 pane 或扩大固定常量掩盖问题。
3. 修复不能引入明显副作用，尤其不能破坏缩放、拖动、Tooltip、十字线或四类详情页。

### 2.2 系统基线

`wealth/docs/system/design-system-baseline.md` 已明确：

1. 主图、MACD、成交量、KDJ 的 x 轴必须同步；
2. 右侧价格轴/指标轴预留宽度必须在四个 pane 一致；
3. 图表实际绘图区右边界必须一致。

`wealth/docs/system/component-guidelines-baseline.md` 已明确：

1. `DetailChartWorkspace` 是详情页唯一共享图表生命周期实现；
2. 四个 pane 的右侧轴宽度与绘图区右边界必须对齐；
3. 页面 adapter 不得重新实现图表生命周期。

### 2.3 当前代码事实

本 LLD 基于以下当前代码审计：

| 事实 | 当前实现 | 结论 |
|---|---|---|
| 图表实例 | `DetailChartWorkspace.tsx` 创建四个独立 chart | 每个实例独立计算 price scale |
| 横轴同步 | `setVisibleLogicalRange(range)` 同步四个 chart | 只同步 logical range，不同步实际 plot width |
| 右轴配置 | `minimumWidth: RIGHT_PRICE_SCALE_WIDTH` | 只提供最小值，不是固定宽度 |
| 固定常量 | `RIGHT_PRICE_SCALE_WIDTH = 56` | 当前被默认根数计算和 CSS 偏移复用 |
| 指标标签 | MACD/KDJ 使用等宽 8 字符 formatter | 仍可能比 56px 更宽 |
| K 线标签 | 使用价格轴默认格式 | 宽度由价格位数决定 |
| 成交量标签 | 使用 volume formatter | 宽度由 `500M` 等文本决定 |
| ResizeObserver | 观察 K 线和 KDJ host | 只处理容器宽度，不统一内部价格轴宽度 |
| 缩放控件 | CSS 固定 `right: 64px` | 隐含 `56px + 8px` 假设 |
| 右侧 Tooltip | CSS 固定 `right: 58px` | 隐含 `56px + 2px` 假设 |
| 拖动换算 | 使用完整 K 线 host width | 没有扣除实际右侧价格轴宽度 |

### 2.4 图表库事实

当前依赖为 `lightweight-charts@5.2.0`。其类型合同明确：

1. `PriceScaleOptions.minimumWidth` 只是最小宽度；
2. 当标签内容需要更多空间时，实际宽度可以超过 `minimumWidth`；
3. `IPriceScaleApi.width()` 返回当前实际价格轴宽度；
4. `IPriceScaleApi.applyOptions()` 可以更新 `minimumWidth`。

因此，继续把四个 pane 都设置为 `minimumWidth=56`，不能证明四个实际宽度相等。

---

## 3. 根因结论

### 3.1 直接根因

四个 chart 的外层 host 宽度相同，logical range 也相同，但其右侧 price scale 的实际宽度不同。
实际绘图区宽度为：

```text
plot_width = host_width - actual_right_price_scale_width
```

同一 logical range 被分别映射到不同 `plot_width`，所以相同 logical index 的像素坐标不同。
这正是截图中“左侧偏差较小、越靠右偏差越大”的原因。

### 3.2 为什么旧修复没有覆盖

历史修复已完成：

1. 四个 pane 的 logical range 同步；
2. crosshair 和时间轴展示策略统一；
3. `minimumWidth=56` 作为价格轴基础下限。

这些修复没有读取并统一 `IPriceScaleApi.width()`，因此没有锁定四个 pane 的**实际**价格轴宽度。

### 3.3 禁止的错误修复

以下做法全部禁止：

1. 把 `56` 盲目改成更大的固定值；
2. 给某个 pane 单独增加 `padding-right`、`margin-right` 或 transform；
3. 隐藏纵向网格线来掩盖错位；
4. 为股票、指数、日线、分钟线分别写四套修复；
5. 修改 logical range、bar 数量或时间键使截图“看起来接近”；
6. 使用定时轮询持续测量 price scale；
7. 在每次 pointer move 中同步执行四次测量与写入；
8. 调用 `priceScale().setVisibleRange()` 人工修改纵轴数据范围。

---

## 4. 修复后共享合同

### 4.1 统一轴宽定义

每次共享 workspace 生命周期内维护：

```text
shared_right_price_scale_width
= max(
    RIGHT_PRICE_SCALE_WIDTH,
    kline.priceScale("right").width(),
    macd.priceScale("right").width(),
    volume.priceScale("right").width(),
    kdj.priceScale("right").width()
  )
```

计算时必须：

1. 忽略 `NaN`、`Infinity`、负数和 0；
2. 使用 `Math.ceil()` 归一为整数像素，避免亚像素抖动；
3. 下限始终为 `RIGHT_PRICE_SCALE_WIDTH`；
4. 同一 chart 生命周期内只允许保持或增大，不在交互中反复收缩；
5. `dataKey`、points 或 series 变化导致 chart 正常重建时，从基础下限重新测量。

同一生命周期内采用单调不减规则，是为了避免可见区变化时标签长短变化导致绘图区左右抖动。
图表重建后会重新计算，因此不会把某一标的的宽轴永久带到另一个标的或频率。

### 4.2 应用规则

若测得的新共享宽度大于当前共享宽度：

1. 对四个 `priceScale("right")` 调用：

```ts
priceScale.applyOptions({ minimumWidth: sharedWidth });
```

2. 将同一宽度写入 `.detail-chart-area` 的 CSS custom property：

```css
--detail-chart-right-price-scale-width: 88px;
```

3. 重新应用当前 canonical logical range；
4. 不改变 indicator autoscale provider；
5. 不重建 chart 或 series；
6. 不触发 API 请求。

这里调用 `priceScale().applyOptions()` 只修改布局下限，不写纵轴数据上下界，和缩放 LLD 中
“禁止动态写人工上下界”的规则不冲突。

### 4.3 绘图区宽度定义

后续所有依赖像素宽度的 viewport 计算统一使用：

```text
effective_plot_width = max(1, host_width - shared_right_price_scale_width)
```

禁止一部分逻辑使用 56，另一部分使用实际宽度。

---

## 5. 校准时序

### 5.1 首次创建

顺序固定为：

```text
创建四个 chart
  -> 创建 series / price lines
  -> setData
  -> 建立 runtime
  -> 应用 initial logical range 和 indicator ranges
  -> 立即执行一次 actual width 校准
  -> 下一 requestAnimationFrame 再验证一次
```

立即校准尽量消除首帧错位；下一帧验证用于等待浏览器和图表库完成文本布局。

### 5.2 logical range 变化

以下来源均经过现有 `commitViewportRange()`：

1. 点击放大/缩小；
2. 拖动历史区间；
3. 图表内部 visible-range callback；
4. untouched viewport 的 resize 自适应；
5. points 数量变化后的 range 恢复。

`commitViewportRange()` 在更新 indicator ranges 和四图 logical range 后，仅排队一次轴宽验证。
同一动画帧内的重复请求必须合并，不得重复执行。

### 5.3 容器 resize

现有 `ResizeObserver` 继续作为容器尺寸事实源。处理顺序修改为：

```text
收到 resize
  -> 下一帧读取最新 host width
  -> 验证/同步四个 actual price scale width
  -> 用 host width - shared scale width 计算 untouched 默认根数
  -> 必要时更新 canonical range
  -> 重新应用相同 range 到四个 chart
```

用户已经手工缩放或拖动时，resize 仍不得覆盖用户选择；只校准 price scale width 并重放当前
range。

### 5.4 不触发校准的事件

以下事件不执行轴宽测量：

1. 普通 React header render；
2. Tooltip 展示/隐藏；
3. synchronized-overlay 模式的鼠标移动；
4. hoverIndex 更新；
5. 九转 marker primitive 重绘；
6. 指标标题数值变化但没有引起 range/series 生命周期变化。

股票分钟 `native-axis-labels` 的动态标签宽度继续受 series price format 和当前共享宽度约束，
不在每个 pointer move 中测量。初始化和 range 变化后的共享最大值必须覆盖其正常标签宽度。

---

## 6. 代码级改动设计

### 6.1 `detailChartViewport.ts`

文件：

`wealth/src/shared/charts/detail-workspace/detailChartViewport.ts`

#### 6.1.1 新增共享宽度纯函数

新增：

```ts
export function resolveSharedRightPriceScaleWidth(
  measuredWidths: readonly number[],
  minimumWidth = RIGHT_PRICE_SCALE_WIDTH,
): number;
```

语义：

1. `minimumWidth` 非有限或小于 1 时回退 `RIGHT_PRICE_SCALE_WIDTH`；
2. 过滤非法测量值；
3. 对合法值 `Math.ceil()`；
4. 返回合法测量值和下限中的最大值。

正例：

```text
[56, 72, 88, 64] -> 88
[56, 56, 56, 56] -> 56
[72.1, 72, 64, 0] -> 73
```

负例：

```text
[] -> 56
[0, -1, NaN, Infinity] -> 56
```

#### 6.1.2 新增绘图区宽度纯函数

新增：

```ts
export function resolveDetailChartPlotWidth(
  hostWidth: number,
  rightPriceScaleWidth: number,
): number;
```

语义：

1. 两个输入均合法时返回 `max(1, hostWidth - rightPriceScaleWidth)`；
2. host 非法时返回 1；
3. 轴宽非法时使用基础下限 56。

#### 6.1.3 修改默认可视根数

签名调整为：

```ts
export function resolveAdaptiveVisibleCount(
  klineHostWidth: number,
  pointCount: number,
  rightPriceScaleWidth = RIGHT_PRICE_SCALE_WIDTH,
): number;
```

内部不再硬编码：

```ts
klineHostWidth - RIGHT_PRICE_SCALE_WIDTH
```

而是使用：

```ts
resolveDetailChartPlotWidth(klineHostWidth, rightPriceScaleWidth)
```

但必须先保留当前输入保护：`klineHostWidth` 非有限、非正数，或有效轴宽已经不小于 host width
时，继续以 `DEFAULT_VISIBLE_BARS=120` 作为自适应基准，再执行现有 point count 与上下限裁剪；不能
把 `resolveDetailChartPlotWidth()` 的安全值 `1` 直接带入根数密度计算。该 helper 返回 `1` 的语义只
是保证拖动等像素换算不除以 0，不代表异常容器应展示最少根数。

默认第三参数保持现有测试和外部调用兼容；正式 workspace 必须传当前共享实际宽度。

### 6.2 `DetailChartWorkspace.tsx`

文件：

`wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.tsx`

#### 6.2.1 Runtime 扩展

`DetailChartRuntime` 增加：

```ts
queuePriceScaleAlignment: () => void;
```

不把 `sharedRightPriceScaleWidth` 放入 React state，避免校准宽度触发整个 workspace render 或
chart effect 重建。

#### 6.2.2 Effect 内局部状态

四个 chart 创建后，在 effect 内维护：

```ts
const rightPriceScales = charts.map((chart) => chart.priceScale("right"));
let sharedRightPriceScaleWidth = RIGHT_PRICE_SCALE_WIDTH;
let priceScaleAlignmentFrame = 0;
```

禁止将 `IPriceScaleApi` 泄漏到领域 adapter 或页面。

#### 6.2.3 `alignRightPriceScales()`

新增 effect 内部函数：

```ts
const alignRightPriceScales = (): boolean => {
  const measuredWidth = resolveSharedRightPriceScaleWidth(
    rightPriceScales.map((scale) => scale.width()),
  );
  const nextWidth = Math.max(sharedRightPriceScaleWidth, measuredWidth);
  if (nextWidth === sharedRightPriceScaleWidth) return false;

  sharedRightPriceScaleWidth = nextWidth;
  rightPriceScales.forEach((scale) => {
    scale.applyOptions({ minimumWidth: nextWidth });
  });
  chartsAreaRef.current?.style.setProperty(
    "--detail-chart-right-price-scale-width",
    `${nextWidth}px`,
  );

  const currentRange = viewportRef.current.range;
  if (currentRange) applyVisibleRange(currentRange);
  return true;
};
```

实现时允许调整局部函数声明顺序以满足 TypeScript 闭包引用，但语义不得改变。

#### 6.2.4 `queuePriceScaleAlignment()`

新增帧合并器：

```ts
const queuePriceScaleAlignment = () => {
  window.cancelAnimationFrame(priceScaleAlignmentFrame);
  priceScaleAlignmentFrame = window.requestAnimationFrame(() => {
    alignRightPriceScales();
  });
};
```

约束：

1. 同一时刻最多有一个 pending frame；
2. cleanup 必须 cancel；
3. 不使用 interval、timeout 或 MutationObserver；
4. 不因宽度相同调用 `applyOptions()`；
5. 不因校准写 React state。

#### 6.2.5 首次对齐

在 runtime 已赋值、initial range 已应用后：

1. 直接调用 `alignRightPriceScales()`；
2. 再调用一次 `queuePriceScaleAlignment()`；
3. 不新增第三次无条件验证。

#### 6.2.6 `commitViewportRange()` 接入

现有流程保持：

```text
保存 canonical range
  -> 更新 visible count UI
  -> 更新 indicator range
  -> 同步四图 logical range
```

末尾增加：

```ts
runtimeRef.current?.queuePriceScaleAlignment();
```

该调用必须经过帧合并，不能同步读取 DOM。

#### 6.2.7 默认 range 计算

所有 effect 内 `resolveAdaptiveVisibleCount(hostWidth, points.length)` 调用改为：

```ts
resolveAdaptiveVisibleCount(
  hostWidth,
  points.length,
  sharedRightPriceScaleWidth,
)
```

初次计算允许使用基础 56；首次实际宽度校准后，若 viewport 尚未被用户调整，重新比较真实 plot
width 对应的默认根数。只有根数实际变化时才更新 range。

#### 6.2.8 拖动换算

当前：

```ts
deltaLogical = -(deltaX * rangeWidth) / hostWidth;
```

目标：

```ts
const plotWidth = resolveDetailChartPlotWidth(
  hostWidth,
  sharedRightPriceScaleWidth,
);
deltaLogical = -(deltaX * rangeWidth) / plotWidth;
```

这样拖动只按真正可绘制 K 线的区域换算，不把右侧价格轴当成数据区域。

#### 6.2.9 ResizeObserver

保留当前 observer 和 `userAdjusted` 门禁，修改点为：

1. resize frame 中先排队轴宽校准；
2. untouched range 的 `resolveAdaptiveVisibleCount()` 传共享实际轴宽；
3. user-adjusted range 不重算默认根数；
4. 无论是否 user-adjusted，轴宽变化后都重放 canonical range；
5. cleanup 同时取消 `priceScaleAlignmentFrame`。

#### 6.2.10 CSS 变量清理

effect 建立时先写基础值：

```text
--detail-chart-right-price-scale-width: 56px
```

cleanup 时仅在当前 runtime 仍属于该 effect 时移除该变量，避免旧 effect 清理覆盖新 effect 的值。
CSS 必须保留 56px fallback，因此短暂缺失变量也不会让控件贴到最右边。

### 6.3 `detail-chart-workspace.css`

文件：

`wealth/src/shared/charts/detail-workspace/detail-chart-workspace.css`

#### 6.3.1 统一变量

在 `.detail-chart-area` 提供 fallback：

```css
--detail-chart-right-price-scale-width: 56px;
```

运行时会在同一元素上写入实际值。

#### 6.3.2 缩放控件

当前：

```css
right: 64px;
```

目标：

```css
right: calc(var(--detail-chart-right-price-scale-width, 56px) + 8px);
```

#### 6.3.3 右侧 Tooltip

当前：

```css
right: 58px;
```

目标：

```css
right: calc(var(--detail-chart-right-price-scale-width, 56px) + 2px);
```

这不是新增 Tooltip 行为，只是维持其原本“位于数据区、不压住右轴”的布局语义。

#### 6.3.4 不修改项

1. `.detail-chart-axis-float-label { right: 8px; }` 保持不变，它本来就绘制在价格轴区域；
2. pane 高度、header 高度、四区比例不变；
3. grid 颜色、线宽、显示规则不变；
4. 指标边界线、zero 线和价格标签不变；
5. K 线极值标注 primitive 不变。

### 6.4 四个领域 adapter

以下文件不应产生实现改动：

1. `StockChartWorkspace.tsx`；
2. `StockMinuteChartWorkspace.tsx`；
3. `IndexChartWorkspace.tsx`；
4. `IndexMinuteChartWorkspace.tsx`。

它们继续只负责 DTO/ViewModel 到 `DetailChartPoint`、主图 lines/primitives、header 和 Tooltip 的
领域映射。轴宽对齐必须由 shared workspace 一次修复后自动生效。

---

## 7. 状态与时序矩阵

| 场景 | 是否重建四图 | 是否重新测量 | range 行为 | 轴宽行为 |
|---|---:|---:|---|---|
| 首次 Loaded | 是 | 立即 + 下一帧 | 初始化 latest range | 取四图最大值 |
| 切换股票/指数 | 是 | 立即 + 下一帧 | 新 `dataKey` 重置 | 从 56 重新测量 |
| 切换日线/分钟频率 | 是 | 立即 + 下一帧 | 新 `dataKey` 重置 | 从 56 重新测量 |
| 切换 MA/BOLL/趋势通道 | 现状可能重建 | 立即 + 下一帧 | 保留 canonical range | 从 56 重新测量 |
| 点击 zoom | 否 | 下一帧合并 | 四图同步新 range | 仅可增大 |
| 拖动历史区间 | 否 | 下一帧合并 | 四图同步新 range | 仅可增大 |
| 容器 resize | 否 | resize frame | untouched 自适应；手工范围保持 | 仅可增大 |
| append 新 bar | 现状重建 | 立即 + 下一帧 | latest 跟随，历史保持 | 从 56 重新测量 |
| Tooltip/crosshair move | 否 | 否 | 不变 | 不变 |
| 空数据 | 按现状 | 无有效内容则保持 56 | `fitContent()` | CSS fallback 56 |

---

## 8. 测试设计

### 8.1 `detailChartViewport.test.ts`

扩展：

1. `[56,72,88,64] -> 88`；
2. 所有值相同不扩大；
3. 小数向上取整；
4. 空数组和非法值回退 56；
5. 自定义合法 minimum 可用；
6. host/axis 正常时返回差值；
7. host 非法或 `host <= axis` 时 plot width 安全返回 1；
8. `resolveAdaptiveVisibleCount()` 第三参数影响阈值计算；
9. 不传第三参数时保持现有 1600px/120 根合同。

### 8.2 Lightweight Charts mock

扩展 `DetailChartWorkspace.test.tsx` 中的 chart mock：

```ts
chart.priceScale("right") -> {
  width: vi.fn(),
  applyOptions: vi.fn(),
}
```

mock 必须区分：

1. intrinsic width：该 chart 的内容自然需要的宽度；
2. applied minimum width：shared 写入的下限；
3. actual width：`max(intrinsic, applied minimum)`。

测试入口提供每次创建四图时的 intrinsic widths，例如：

```text
kline=72, macd=88, volume=60, kdj=80
```

### 8.3 Workspace 正向测试

必须新增：

1. 四个不同 actual width 最终都收到 `minimumWidth=88`；
2. `.detail-chart-area` 的 CSS 变量最终为 `88px`；
3. 校准后四图重新应用同一 logical range；
4. `createChart` 仍只调用 4 次；
5. 不调用 `fitContent()`；
6. 不调用 fetch；
7. 宽度已经一致时不调用 `priceScale.applyOptions()`；
8. 非法/0 测量值不覆盖基础 56；
9. 下一帧出现更大 intrinsic width 时只再统一一次；
10. 同一生命周期后续较小宽度不触发收缩和抖动；
11. `dataKey` 切换后从新一组 intrinsic widths 重新计算；
12. cleanup 取消 pending frame，卸载后不再 apply options。

### 8.4 viewport 与交互回归

必须证明：

1. 1600px 基线仍得到 120 根；
2. 实际轴宽参与窄/宽容器默认根数；
3. 用户 zoom 后 resize 不覆盖用户范围；
4. 拖动使用 plot width，span 不变且方向正确；
5. zoom 仍为 45～180、步长 15；
6. append latest 和历史观察区间规则不变；
7. visible extrema、MACD/KDJ 动态 range 随同一 canonical range 更新；
8. shared crosshair x、DailyTimeAxis marker 与四图 range 不回退。

### 8.5 CSS 合同测试

静态检查 `detail-chart-workspace.css`：

1. zoom controls 使用 shared CSS variable + 8px；
2. right Tooltip 使用 shared CSS variable + 2px；
3. 不再出现这两个位置的裸 `64px/58px`；
4. axis float label 仍为 `right: 8px`；
5. 不新增 pane-specific 右边距补丁。

### 8.6 四消费者回归

至少运行：

1. 股票日线 `StockChartWorkspace.test.tsx`；
2. 股票分钟 `StockMinuteChartWorkspace.test.tsx`；
3. 指数日线 `IndexChartWorkspace.test.tsx`；
4. 指数分钟 `IndexMinuteChartWorkspace.test.tsx`。

断言四者继续只创建 shared workspace，不出现各自 `priceScale` 对齐逻辑。

---

## 9. 性能门禁

| 项目 | 门禁 |
|---|---|
| 初始化测量 | 4 次 `width()`，立即一次 + 下一帧一次 |
| 单次对齐写入 | 最多 4 次 `applyOptions()`，仅共享宽度增大时 |
| range 高频变化 | 同一动画帧合并为一次测量 |
| pointer move | 0 次 width 测量、0 次轴宽写入 |
| React state | 不保存轴宽，不因轴宽触发 render |
| chart/series 重建 | 对齐动作增量 0 |
| API 请求 | 增量 0 |
| 后端/数据湖 | 增量 0 |
| 定时轮询 | 禁止 |

复杂度固定为 O(4)，与 K 线根数、指标数量和历史长度无关。

---

## 10. 副作用控制

### 10.1 绘图区略微变窄

四个 pane 会统一预留最宽的右轴。较窄 pane 的绘图区可能比当前少几到几十像素，这是实现严格
对齐的必要成本。默认可视根数使用真实 plot width 重新计算，避免密度口径漂移。

### 10.2 首帧轻微调整

浏览器若在 chart 创建后下一帧才给出最终文字宽度，可能发生一次宽度调整。通过“同步立即测量 +
单次 RAF 验证”限制为最多一次可见调整，不采用长期轮询。

### 10.3 交互控件位置

缩放控件和右侧 Tooltip 必须跟随 shared CSS variable；否则轴变宽后会压住价格标签。这两个改动是
轴宽修复的必要伴随项，不改变其交互和视觉尺寸。

### 10.4 不受影响的行为

1. 行情 K 线和指标数值；
2. MACD/KDJ 可见范围计算；
3. 指标 max/min/zero 边界线；
4. K 线最高/最低标注；
5. 日线和分钟时间格式；
6. API 请求、缓存、错误态和重试；
7. 九转、MA、BOLL、趋势通道图层；
8. 后端、数据库和数据湖。

---

## 11. 实施步骤

### M1 纯函数和 mock

1. 新增共享轴宽和 plot width 纯函数；
2. 修改 adaptive count 签名；
3. 扩展 viewport tests；
4. 扩展 chart mock 的 price scale API。

停止条件：无法在不引入页面分支的情况下得到稳定共享宽度。

### M2 Workspace 对齐

1. 增加 effect 内 width state 和两个校准函数；
2. 接入初始化、range 和 resize 生命周期；
3. 改造默认根数和拖动换算；
4. 完成 cleanup 和循环保护；
5. 增加 workspace 正负测试。

停止条件：对齐会重建 chart、触发无限 visible-range 回调或覆盖用户 range。

### M3 CSS 与四消费者回归

1. 写入 CSS variable fallback；
2. 修改 zoom controls 和 Tooltip 偏移；
3. 增加 CSS 静态门禁；
4. 跑四消费者定向回归。

停止条件：任一 adapter 需要页面私有 price scale 代码。

### M4 自动验证与人工验收交接

1. 运行共享 target tests；
2. 运行四消费者 tests；
3. 运行 `typecheck`、完整前端 test 和 build；
4. 运行 `git diff --check`；
5. 交由用户部署并人工检查股票/指数、日线/分钟线。

本 LLD 不包含部署动作。

---

## 12. 验证命令

```bash
cd /Users/congming/github/goldenshare

npm --prefix wealth run test -- \
  src/shared/charts/detail-workspace/detailChartViewport.test.ts \
  src/shared/charts/detail-workspace/DetailChartWorkspace.test.tsx \
  src/features/stock-detail/chart/StockChartWorkspace.test.tsx \
  src/features/stock-detail/chart/StockMinuteChartWorkspace.test.tsx \
  src/features/index-detail/chart/IndexChartWorkspace.test.tsx \
  src/features/index-detail/chart/IndexMinuteChartWorkspace.test.tsx

npm --prefix wealth run typecheck
npm --prefix wealth run test
npm --prefix wealth run build
git diff --check
```

---

## 13. 人工验收矩阵

部署后由用户人工验收，至少覆盖：

| 页面 | 周期 | 检查点 |
|---|---|---|
| 股票详情 | 日线 | 四 pane 纵向网格全宽对齐 |
| 股票详情 | 1m/60m/120m | native/共享时间轴均对齐 |
| 指数详情 | 日线 | K 线与 MACD/成交量/KDJ 网格对齐 |
| 指数详情 | 1m/60m/120m | 分钟时间轴和四 pane 对齐 |
| 任一详情 | zoom 45/120/180 | 缩放后仍对齐，控件不压轴 |
| 任一详情 | 拖到历史区间 | 拖动后仍对齐，速度无突变 |
| 任一详情 | 极端长价格/指标标签 | 四轴仍同宽，无文本裁切 |
| 任一详情 | resize | untouched 自适应；手工 range 保持 |

硬验收：从任意一条 K 线区纵向网格向下观察，必须与 MACD、成交量、KDJ 的对应竖线处于同一
像素列；不能再出现向右逐步累积的偏差。

---

## 14. 边界与依赖结论

1. 改动只位于 `wealth/src/shared/charts/detail-workspace/**` 和对应测试/文档；
2. 不修改 stock/index feature 的业务合同；
3. 不修改仓库后端 `foundation/ops/biz/app` 依赖矩阵；
4. 不新增依赖；
5. 不修改 Figma 视觉元素，本轮是现有四 pane 对齐合同的实现修复；
6. 不更新 `docs/architecture/codegraph-architecture-snapshot.md`，因为系统边界和 API 调用链不变。

CodeGraph 影响面审计确认四个消费者均通过同一个 `DetailChartWorkspace` 接入：

1. `StockChartWorkspace`；
2. `StockMinuteChartWorkspace`；
3. `IndexChartWorkspace`；
4. `IndexMinuteChartWorkspace`。

---

## 15. 待拍板项

无新增产品参数或视觉决策。共享最大实际轴宽、同生命周期单调不减、基础下限 56px、立即校准加
一次 RAF 验证，均是修复现有错位合同所需的实现规则。

进入开发后如发现 `lightweight-charts@5.2.0` 在 `minimumWidth` 更新后仍返回不同实际宽度，必须
停止并报告真实测量结果；禁止继续增加固定宽度、CSS 补丁或无界校准次数。

---

## 16. 实施结果

本轮已严格按本文档落地：

1. `detailChartViewport.ts` 已增加共享实际轴宽与绘图区宽度纯函数；
2. `DetailChartWorkspace.tsx` 已完成四图实际轴宽测量、最大值同步、帧合并、生命周期重置与 cleanup；
3. 默认根数、拖动换算、缩放控件和右侧 Tooltip 已统一消费共享实际轴宽；
4. 股票/指数、日线/分钟线继续复用同一个 workspace，业务 adapter 未新增轴宽分支；
5. 定向 6 个测试文件共 67 个测试通过；
6. `wealth` 完整 39 个测试文件共 279 个测试通过；
7. TypeScript 类型检查和生产构建通过；
8. 未启动服务、未部署，本文第 13 节的人工页面验收由用户执行。

---

## 17. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1.1 | 2026-08-21 | 按 LLD 完成共享实际轴宽对齐、绘图区换算、CSS 偏移与自动化回归 |
| v1 | 2026-08-21 | 基于当前四 chart 生命周期、实际 price scale API、viewport、CSS 和四类消费者完成代码级修复设计 |
