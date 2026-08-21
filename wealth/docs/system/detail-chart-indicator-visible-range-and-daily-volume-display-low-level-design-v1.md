# 详情页指标动态纵轴与日线成交量展示 LLD v1

> 状态：已闭环。代码开发、自动化验证、用户部署与人工交互验收均已完成。
> 日期：2026-08-20。
> 技术方案：[详情页指标动态纵轴与日线成交量展示技术方案 v1](./detail-chart-indicator-visible-range-and-daily-volume-display-implementation-design-v1.md)。
> 共享图表基线：[详情页共享图表与 K 线缩放 LLD v1](./detail-chart-zoom-low-level-design-v1.md)。
> 可见窗口基线：[详情页 K 线可见区间最高/最低价标注 LLD v1](./detail-chart-visible-extrema-annotation-low-level-design-v1.md)。
> 正式设计稿：[Indicator Range + Daily Volume 交互合同](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=728-723&m=dev)。

---

## 1. 目标与硬边界

### 1.1 开发目标

本专项一次完成两项共享能力：

1. 股票/指数日线详情由后端生成固定“万”单位、保留 2 位小数的成交量展示文本。
2. 股票/指数、日线/分钟线共用的 MACD/KDJ 面板，按当前完整可见 K 线实时确定纵轴范围。

实现后必须满足：

```text
daily raw volume (手)
  -> backend vol 保持原值
  -> backend volDisplay="58.63万"
  -> frontend volume histogram 使用 vol
  -> frontend 日线文字入口原样使用 volDisplay

canonical logical range
  -> 完整可见索引
  -> MACD 扫描 macd/dif/dea
  -> KDJ 扫描 k/d/j
  -> 确定共享 min/max
  -> 更新现有右侧纵轴，不重建 chart
```

### 1.2 已冻结口径

1. 成交量展示固定为 `vol / 10_000`，单位固定“万”，保留 2 位小数。
2. 四舍五入使用 `ROUND_HALF_UP`；`586339` 显示为 `58.63万`。
3. 原始 `vol` 数值和单位不变，继续用于成交量柱体。
4. 极值标签只显示在现有右侧纵轴，不新增左侧价格轴。
5. MACD 取当前可见 `macd/dif/dea` 的共同最大值和共同最小值。
6. KDJ 取当前可见 `k/d/j` 的共同最大值和共同最小值。
7. 全正或全负 MACD 不强制包含 0；只有 `min < 0 < max` 时显示 0 轴。
8. KDJ 不固定 0～100，不裁剪 J，不补齐 0 或 100。
9. 当 `min == max == value` 时：
   `padding=max(abs(value)*0.01, 0.01)`，有效域为
   `[value-padding,value+padding]`。
10. 动态范围只统计 logical range 内完整可见 K 线，忽略两侧半根 K 线。
11. 指标右轴标签使用统一固定字符宽度，数值右对齐；MACD 的 max/zero/min 与 KDJ 的
    max/min 不得因正负号或整数位数不同形成参差宽度。
12. max 标签使用上涨色背景，min 标签使用下跌色背景，MACD zero 标签使用中性色背景；
    Figma 与正式实现必须保持一致。
13. max/min 所在水平线就是指标绘图区的动态上边界和下边界；不得在相同位置再叠加指标
    绘图区外框线或固定分隔线。
14. MACD/KDJ 指标面板关闭 Lightweight Charts 自动水平网格线和自动中间刻度文本：
    MACD 只允许显示 max、跨零时的 zero、min，KDJ 只允许显示 max、min。K 线和成交量
    面板的自动网格保持不变。

### 1.3 明确不做

1. 不修改 MACD/KDJ 公式、参数、数据源或后端指标值。
2. 不改变 K 线和成交量面板的纵轴规则。
3. 不修改分钟成交量 API 或分钟成交量单位。
4. 不增加用户配置、环境变量、数据库迁移或新 API 路径。
5. 不新建第二套详情图表，不在四个页面分别订阅可见范围。
6. 不进入 Figma 共享详情图表组件 TODO 的组件化工作。

---

## 2. 当前代码事实与影响面

### 2.1 审计方法

本轮以当前 `dev-interface` 代码为事实源，使用 CodeGraph 的
`codegraph_explore`、`codegraph_impact` 核对共享图表、后端 DTO/mapper 和四类消费者，
并用当前类型、测试和 import 做交叉确认。

CodeGraph 影响面显示 `DetailChartPoint` 会影响共享 workspace、四个 feature adapter、
图表测试和九转相关测试 fixture。TSX 动态 JSX 引用不保证完全被静态图列出，因此实施时仍需
以 TypeScript 全量 typecheck 清理所有对象字面量。

### 2.2 后端成交量链路

当前事实：

| 场景 | DTO | Mapper 源字段 | 当前展示字段 |
|---|---|---|---|
| 股票 page-init | `StockQuoteSnapshotDto` | `row["vol"]` | 无 |
| 股票日线 bar | `StockKlineBarDto` | `row["vol"]` | 无 |
| 指数 page-init | `IndexDetailQuoteDto` | `row["factor_vol"]` | 无 |
| 指数日线 bar | `IndexKlineBarDto` | `row["vol"]` | 无 |

四个 mapper 都已得到原始“手”数值，不需要修改 SQL、查询服务或数据源。新增展示文本必须在
field mapper 层统一生成，不能让 query service 或前端重复换算。

### 2.3 前端成交量链路

1. `stockDetailViewModelAdapter.ts` 用 `formatVolumeText()` 计算“手/万手”。
2. `indexDetailViewModelAdapter.ts` 用 `formatHands()` 计算“手/万手/亿手”。
3. `StockChartWorkspace.tsx` 和 `IndexChartWorkspace.tsx` 又分别格式化日线面板标题与 Tooltip。
4. 成交量柱体直接消费 numeric `volume`，该链路必须保留。
5. 股票/指数分钟 workspace 有各自的分钟量格式化，本轮不改。

### 2.4 指标空值差异

`indexDetailViewModelAdapter.ts`、股票分钟和指数分钟 adapter 会把缺失指标保留为 `null`；
`stockDetailViewModelAdapter.ts` 当前却对 `macd/dif/dea/k/d/j` 使用 `valueOrZero()`。

这会让新上市股票或指标预热期的缺失值进入纵轴范围并伪造 0。本轮必须把股票日线这六个字段
改成 `finiteOrNull()`，并把 `StockCandlePoint` 对应类型改为 `number | null`。这是动态纵轴正确性
的前置修复，不改变指标公式。

### 2.5 共享 viewport 与 chart 生命周期

`DetailChartWorkspace.tsx` 当前已经统一负责：

1. K 线、MACD、成交量、KDJ 四个 chart 的创建与销毁。
2. canonical logical range 的保存和四窗格同步。
3. 初始范围、zoom、drag、resize、`dataKey` 切换和数据追加后的范围提交。
4. `commitViewportRange(...)` 是所有范围变化的统一提交点。
5. `resolveVisibleIndexRange(...)` 已使用 `ceil(from)` 和 `floor(to)` 只选择完整 K 线。

因此动态纵轴必须接入 `commitViewportRange(...)` 和现有 runtime ref；禁止新增 React 范围 state、
页面订阅或 chart 创建 effect。

---

## 3. 目标文件清单

### 3.1 新增文件

```text
src/biz/services/wealth/market/detail_volume_display.py
  # 股票/指数日线共享成交量展示 formatter

tests/test_wealth_detail_volume_display.py
  # Decimal、ROUND_HALF_UP、缺失/非法值测试

wealth/src/shared/charts/detail-workspace/detailChartIndicatorRange.ts
  # MACD/KDJ 可见范围纯计算

wealth/src/shared/charts/detail-workspace/detailChartIndicatorRange.test.ts
  # 纯函数边界测试
```

### 3.2 修改文件

后端：

```text
src/biz/schemas/wealth/market/stock_detail.py
src/biz/schemas/wealth/market/index_detail.py
src/biz/services/wealth/market/stock_detail/stock_detail_field_mapper.py
src/biz/services/wealth/market/index_detail/index_detail_field_mapper.py
tests/test_index_detail_field_mapper.py
tests/web/test_wealth_stock_detail_api.py
tests/web/test_wealth_index_detail_api.py
```

前端合同和 adapter：

```text
wealth/src/features/stock-detail/api/stockDetailApiTypes.ts
wealth/src/features/stock-detail/api/stockDetailViewModelAdapter.ts
wealth/src/features/stock-detail/api/stockDetailViewModelAdapter.test.ts
wealth/src/features/stock-detail/model/stockDetailTypes.ts

wealth/src/features/index-detail/api/indexDetailApiTypes.ts
wealth/src/features/index-detail/api/indexDetailViewModelAdapter.ts
wealth/src/features/index-detail/api/indexDetailViewModelAdapter.test.ts
wealth/src/features/index-detail/model/indexDetailTypes.ts
wealth/src/features/index-detail/testing/indexDetailTestFixtures.ts
```

四类图表和共享 workspace：

```text
wealth/src/shared/charts/detail-workspace/detailChartTypes.ts
wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.tsx
wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.test.tsx

wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx
wealth/src/features/stock-detail/chart/StockChartWorkspace.test.tsx
wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.tsx
wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.test.tsx
wealth/src/features/index-detail/chart/IndexChartWorkspace.tsx
wealth/src/features/index-detail/chart/IndexChartWorkspace.test.tsx
wealth/src/features/index-detail/chart/IndexMinuteChartWorkspace.tsx
wealth/src/features/index-detail/chart/IndexMinuteChartWorkspace.test.tsx
```

若 TypeScript typecheck 发现其它 `DetailChartPoint` fixture，允许只补
`volumeDisplay: null`，不得顺带重构测试或业务代码。

### 3.3 明确不修改

1. 股票/指数 query service、DAO 和 SQL。
2. 股票/指数分钟 API DTO 和 reader。
3. 日线/分钟 MACD、KDJ 计算服务。
4. `detailChartViewport.ts` 的 45～180 根窗口合同。
5. Lake、Dagster、ClickHouse/PostgreSQL schema。

---

## 4. 后端日线成交量展示合同

### 4.1 共享 formatter

新增：

```python
def format_daily_volume_display(value: object | None) -> str | None:
    ...
```

实现顺序固定：

1. `None` 返回 `None`。
2. 使用 `Decimal(str(value))`，不得先转二进制 `float` 再四舍五入。
3. 非法值或非有限值返回 `None`。
4. `scaled = decimal_value / Decimal("10000")`。
5. `scaled.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`。
6. 返回固定两位字符串 `f"{scaled:.2f}万"`。

示例：

| 输入 | 输出 |
|---:|---|
| `586339` | `58.63万` |
| `5863` | `0.59万` |
| `0` | `0.00万` |
| `None` | `None` |
| `NaN/Infinity/非法字符串` | `None` |

formatter 只负责展示转换，不新增负数或业务域校验；源数据合法性仍由现有查询合同负责。

### 4.2 DTO 变更

以下四个 DTO 新增 required-nullable 字段，不保留旧字段缺失兼容路径：

```python
volDisplay: str | None
```

具体对象：

1. `StockQuoteSnapshotDto`
2. `StockKlineBarDto`
3. `IndexDetailQuoteDto`
4. `IndexKlineBarDto`

原始 `vol: float | None` 保持字段名、数值和单位不变。

### 4.3 Mapper 变更

每个 mapper 先只规范化一次原始成交量，再同时写入两个字段：

```python
vol = to_float(row.get("vol"))
return ...(
    vol=vol,
    volDisplay=format_daily_volume_display(vol),
)
```

指数 page-init 仍读取 `factor_vol`，只有输入键不同：

```python
vol = to_float(row.get("factor_vol"))
```

禁止：

1. 修改 SQL，把展示字符串在数据库中拼出来。
2. page-init 与 K 线使用两个 formatter。
3. 修改 raw `vol` 为“万”单位。
4. 在 schema validator 中重复计算展示值。

---

## 5. 前端日线成交量接入

### 5.1 API 类型

`StockQuoteSnapshotDto`、`StockKlineBarDto`、指数 page-init quote 和
`IndexKlineBarDto` 均新增：

```ts
volDisplay: string | null;
```

该字段是后端正式合同，不声明为 optional。缺失字段应由真实 API/typecheck 测试暴露，
不得在 API client 中自行回算。

### 5.2 ViewModel 类型

新增：

```ts
interface StockCandlePoint {
  volume: number;
  volumeDisplay: string | null;
  macd: number | null;
  dif: number | null;
  dea: number | null;
  k: number | null;
  d: number | null;
  j: number | null;
}

interface IndexCandlePoint {
  volume: number | null;
  volumeDisplay: string | null;
}

interface DetailChartPoint {
  volume: number | null;
  volumeDisplay: string | null;
}
```

`volumeDisplay` 在 shared point 中为 required-nullable：日线 adapter 必须传 API 值，分钟 adapter
必须显式传 `null`。这样 minute 语义不会被误认为遗漏，也不需要兼容推断。

### 5.3 股票 adapter

`stockDetailViewModelAdapter.ts` 固定修改：

1. 删除 `formatVolumeText()`。
2. quote 的 `volumeText` 改为 `quote.volDisplay ?? "--"`。
3. 日线 candle 增加 `volumeDisplay: bar.volDisplay`。
4. `macd/dif/dea/k/d/j` 全部使用 `finiteOrNull()`。
5. 不改 amount、价格、MA/BOLL 或分钟 adapter。

### 5.4 指数 adapter

`indexDetailViewModelAdapter.ts` 固定修改：

1. 删除 `formatHands()`。
2. `buildBasicMetrics()` 的“总量”不再走 numeric `metric(...)`。
3. 增加只接收后端字符串的展示 metric helper；空值只输出 `--`。
4. 日线 candle 增加 `volumeDisplay: bar.volDisplay`。
5. 不改变 amount、估值、涨跌家数或分钟 adapter。

### 5.5 日线图表文字入口

`StockChartWorkspace.tsx` 与 `IndexChartWorkspace.tsx`：

1. `toDetailChartPoint()` 透传 `volumeDisplay`。
2. 成交量面板标题“总量”使用 `point.volumeDisplay ?? "--"`。
3. K 线 Tooltip“成交量”使用 `point.volumeDisplay ?? "--"`。
4. 删除日线成交量 `/10_000`、`/100_000_000` 和单位切换 formatter。
5. histogram 仍使用 `point.volume`。

股票/指数分钟 workspace 只补 `volumeDisplay: null`；现有分钟量标题、Tooltip 和柱体逻辑不变。

---

## 6. 指标可见范围纯计算

### 6.1 类型合同

新增 `detailChartIndicatorRange.ts`：

```ts
export type DetailChartIndicatorField =
  | "macd" | "dif" | "dea"
  | "k" | "d" | "j";

export interface DetailChartIndicatorRange {
  dataMax: number;
  dataMin: number;
  domainMax: number;
  domainMin: number;
  isDegenerate: boolean;
}

export const MACD_RANGE_FIELDS = ["macd", "dif", "dea"] as const;
export const KDJ_RANGE_FIELDS = ["k", "d", "j"] as const;

export function resolveVisibleIndicatorRange(
  points: readonly DetailChartPoint[],
  logicalRange: DetailChartLogicalRange | null,
  fields: readonly DetailChartIndicatorField[],
): DetailChartIndicatorRange | null;
```

`dataMin/dataMax` 是真实可见极值；`domainMin/domainMax` 是实际应用到图表的范围。
正常场景两者相同，退化场景只有 domain 使用安全跨度。

### 6.2 算法

实现顺序固定：

1. 调用 `resolveVisibleIndexRange(logicalRange, points.length)`。
2. 无有效索引返回 `null`。
3. 单次循环 `startIndex..endIndex`。
4. 对固定 fields 逐个读取值，只接受 `isFiniteChartNumber(value)`。
5. 不排序、不复制可见数组、不扫描完整历史。
6. 没有任何有限值时返回 `null`。
7. `dataMin !== dataMax` 时，domain 等于 data extrema。
8. 相等时应用冻结的 1%/0.01 安全跨度。

相等场景只显示一条真实值标签，避免两个相同标签重叠；安全 domain 端点不冒充业务极值。

### 6.3 复杂度

当前 viewport 最多 180 根：

```text
MACD: 180 * 3
KDJ : 180 * 3
合计 : 最多 1080 次标量检查
```

每次 viewport commit 只计算 MACD 一次、KDJ 一次，时间 O(V)，额外空间 O(1)。

---

## 7. `DetailChartWorkspace` 接入设计

### 7.1 Runtime 扩展

当前 runtime：

```ts
interface DetailChartRuntime {
  applyRange(range): void;
  getRange(): DetailChartLogicalRange | null;
}
```

扩展为：

```ts
interface DetailChartRuntime {
  applyRange(range): void;
  applyIndicatorRanges(range): void;
  getRange(): DetailChartLogicalRange | null;
}
```

`commitViewportRange(...)` 固定执行：

1. 更新 canonical viewport ref 和 UI count。
2. 只要 range 非空，总是调用 `applyIndicatorRanges(range)`。
3. 只有 `applyToCharts !== false` 时才调用 `applyRange(range)`。

这一顺序保证源 chart 的拖动回调虽然不重复 set logical range，仍会更新指标纵轴。

### 7.2 Series 引用

创建 chart 时必须保留六个指标 series：

```text
MACD: macdBars, difSeries, deaSeries
KDJ : kSeries, dSeries, jSeries
```

不得只保留 `macdBars` 和 `kdjReferenceLine`，否则无法把同一个 autoscale contract 显式应用到
同一 pane 的全部 series。

### 7.3 Autoscale provider

为每个 indicator pane 维护一个闭包缓存：

```ts
let macdRange: DetailChartIndicatorRange | null = null;
let kdjRange: DetailChartIndicatorRange | null = null;
```

同一 pane 的三个 series 使用同一个 provider 语义：

```ts
const provider = () => range
  ? { priceRange: { minValue: range.domainMin, maxValue: range.domainMax } }
  : null;
```

范围更新后，对对应三个 series 调用 `applyOptions({ autoscaleInfoProvider })`，强制图表库重新执行
autoscale；不得销毁或重建 chart/series。

`buildChartOptions(...)` 增加 `panel` 参数：

1. `macd/kdj` 的 `rightPriceScale.scaleMargins` 固定为 `{top:0,bottom:0}`。
2. `kline/volume` 保持当前 `{top:0.12,bottom:0.12}`。
3. left price scale 保持隐藏。
4. MACD/KDJ series 的价格格式固定 2 位小数，`minMove=0.01`。

### 7.4 右侧纵轴标签

每个 indicator pane 在 reference series 上创建三条可复用 price line：

1. max boundary：`lineVisible=true`，`axisLabelVisible=true`。
2. min boundary：非退化范围时 `lineVisible=true`，`axisLabelVisible=true`。
3. zero line：中性虚线；只有 MACD `dataMin < 0 < dataMax` 时显示。

标签规则：

1. max/min 只出现在右侧纵轴，不渲染左侧 DOM/Canvas 标签。
2. max 标签使用现有上涨色背景，min 标签使用现有下跌色背景，zero 标签使用中性色背景；
   标签文字统一使用高对比度浅色。
3. 正常范围分别标记 `dataMax/dataMin`。
4. 退化范围只显示一条 `dataMin == dataMax` 的真实值标签，隐藏重复标签。
5. 无有限值时隐藏 max/min/zero，provider 返回 `null`。
6. 全正/全负 MACD 隐藏 zero line，不扩大 domain。
7. KDJ 不创建 0/20/50/80/100 固定参考线。
8. 指标价格格式固定为 2 位小数，并以统一固定字符宽度输出；不足位使用数字等宽空格在
   左侧补齐，使右轴标签数值右对齐。

边界线规则：

1. max/min 水平线使用同一中性网格线色和实线样式，避免整条边界线被误读为涨跌状态；
   涨跌色只承载右轴标签背景语义。
2. max/min 水平线直接位于 `domainMax/domainMin` 对应的绘图区上下边界，并随可见窗口变化。
3. 指标 panel 不得再绘制与 min boundary 重合的 `border-bottom`；KDJ 作为末端 panel 也保持
   无额外底部外框。共享 workspace 外框和不同 panel header 不属于本条禁止范围。
4. 退化范围只显示真实值对应的一条 max boundary；安全 domain 两端不生成伪极值边界线。
5. `buildChartOptions(...)` 对 `macd/kdj` 设置 `grid.horzLines.visible=false`，避免图表库
   在动态边界之间继续生成自动水平网格线。
6. 指标自定义 `priceFormat.tickmarksFormatter` 对自动 tick 返回空文本，只保留 price line
   自己的 max/min/zero 轴标签；不得出现 KDJ `50.00` 一类未冻结的中间标签。

price line 负责右轴标签、max/min 动态边界和 MACD 0 线；确定 domain 的唯一事实仍是
autoscale provider，price line 不得反向扩大范围。

### 7.5 刷新触发矩阵

| 触发 | 当前入口 | 指标范围动作 |
|---|---|---|
| 首次加载 | initial range commit | 计算并应用 |
| 放大/缩小 | `zoom()` -> commit | 计算并应用 |
| 横向拖动 | visible range callback -> commit | 计算并应用 |
| 未交互 resize | adaptive range commit | 计算并应用 |
| `dataKey` 切换 | chart effect + initial range | 计算并应用 |
| 数据追加 | point count change + restored range | 计算并应用 |

不新增 request、不新增第二套 range subscription、不把范围写入 React state。

---

## 8. 四类消费者对账

| 消费者 | 日线成交量 display | 动态 MACD/KDJ | 其它修改 |
|---|---|---|---|
| `StockChartWorkspace` | API display | shared 自动生效 | 透传字段；指标 null 修正 |
| `IndexChartWorkspace` | API display | shared 自动生效 | 透传字段 |
| `StockMinuteChartWorkspace` | 不改，传 `null` | shared 自动生效 | 无分钟 API 变更 |
| `IndexMinuteChartWorkspace` | 不改，传 `null` | shared 自动生效 | 无分钟 API 变更 |

四个消费者不得增加 autoscale、price line 或 visible-range 私有代码。

---

## 9. 测试设计

### 9.1 后端 formatter

`tests/test_wealth_detail_volume_display.py`：

1. `586339 -> 58.63万`。
2. `5863 -> 0.59万`。
3. 进位边界验证 `ROUND_HALF_UP`，禁止依赖 Python bankers rounding。
4. `0 -> 0.00万`。
5. `None/NaN/Infinity/非法值 -> None`。

### 9.2 Backend mapper/API

1. 股票/指数 quote 的 raw `vol` 未改变，`volDisplay` 正确。
2. 股票/指数 K 线 bar 的 raw `vol` 未改变，`volDisplay` 正确。
3. page-init 和 K 线使用同一 formatter。
4. 真实 Web API JSON 明确包含 nullable `volDisplay`。
5. 不新增 SQL 字段或额外数据库查询。

### 9.3 Frontend adapter

1. 股票 quote/index basic metric 原样展示 `volDisplay`。
2. 日线 candle 透传 `volumeDisplay`。
3. 股票日线缺失 `macd/dif/dea/k/d/j` 保留 `null`，不再变成 0。
4. raw `volume` 数值保持不变。
5. 删除旧 formatter 后，股票/指数日线 adapter 不再出现 `/10000` 或 `/100000000`。

### 9.4 Range 纯函数

覆盖：

1. fractional range 只统计完整索引。
2. MACD 三字段共同决定 min/max。
3. KDJ 三字段共同决定 min/max，J 可超出 0～100。
4. null/NaN/Infinity 被忽略。
5. 全部无效返回 `null`。
6. 全正、全负、跨 0。
7. `min == max == 0` 得到 `[-0.01,0.01]`。
8. `min == max == 100` 得到 `[99,101]`。

### 9.5 Workspace 测试

扩展现有 lightweight-charts mock，支持：

1. series `applyOptions()`。
2. `createPriceLine()` 返回可记录 `applyOptions()` 的对象。
3. chart options 可检查 pane-specific scale margins。

必须验证：

1. 初始范围对 MACD/KDJ 分别应用正确 provider。
2. zoom、drag、resize、`dataKey` 和 append 后更新范围。
3. 全正/全负 MACD 不显示 0 线，跨 0 时显示。
4. max/min 只生成右侧 axis labels，没有左轴实现。
5. KDJ 不固定 0～100。
6. 退化范围采用安全 domain 且只显示一个真实值标签。
7. indicator pane margin 为 0，K 线/volume 仍为 0.12。
8. `createChart` 数量在范围变化前后保持 4，不因 autoscale 更新重建。
9. 不触发 API request。
10. max/min boundary 可见，使用中性实线；MACD zero 仍为中性虚线。
11. 指标右轴格式化文本长度一致、保留 2 位小数并从右侧对齐。
12. MACD/KDJ panel 带专属 class，样式门禁证明没有与 min boundary 重合的底部边框。
13. MACD/KDJ 自动水平网格关闭，K 线/成交量自动水平网格保持开启。
14. 指标自动 tick 文本为空，price line 的 max/min/zero formatter 仍输出等宽两位小数。

### 9.6 四消费者回归

1. 股票/指数日线标题和 Tooltip 使用 `volumeDisplay`。
2. 股票/指数分钟原格式化不变。
3. 四个 `toDetailChartPoint()` 都显式设置 `volumeDisplay`。
4. 四场景均继续共享同一个 workspace。

---

## 10. 性能与稳定性门禁

| 项目 | 硬门禁 |
|---|---|
| 后端 DB 查询 | 增量 0 |
| 后端 formatter | 每个 quote/bar O(1) |
| range 扫描 | 每次两次 O(V)，`V <= 180` |
| 标量检查 | 每次最多 1080 |
| 额外 API 请求 | 0 |
| chart/series 重建 | 范围变化时 0 |
| React 范围 state | 0 |
| 页面私有订阅 | 0 |
| 全历史扫描/排序 | 0 |

范围更新中的闭包缓存只保存两个小对象，不保存可见 points 副本。price line 实例只在 chart 创建时
创建，后续仅 `applyOptions()`；chart cleanup 继续由现有 effect 统一负责。

---

## 11. 实施顺序与停止条件

### M1 后端展示合同

1. 新增 formatter 和单测。
2. 修改四个 DTO、两个 mapper。
3. 更新 mapper/API 测试。

停止条件：raw `vol` 被改单位、API 缺字段、page-init/K 线输出不一致。

### M2 前端合同与展示

1. 修改 API types、ViewModel types 和 adapter。
2. 清除日线成交量前端换算。
3. 修复股票日线 MACD/KDJ null 语义。
4. 修改两类日线标题/Tooltip；分钟只补 nullable 字段。

停止条件：分钟成交量语义被改变、柱体改用字符串、旧换算仍有日线消费者。

### M3 共享指标纵轴

1. 先实现纯函数和测试。
2. 再扩展 workspace runtime、series 引用、provider 和 price lines。
3. 更新 chart mock 和共享测试。
4. 回归四消费者。

停止条件：需要页面私有实现、chart 被范围变化重建、全正/全负仍被强制纳入 0。

### M4 验证与文档收口（已完成）

1. 后端目标测试。
2. 前端 target tests、typecheck、build。
3. 用户在实际部署环境验证 raw/display 展示合同与动态纵轴交互结果。
4. 用户确认动态纵轴和日线成交量展示无问题。
5. 技术方案与 LLD 更新为闭环状态。

---

## 12. 验证命令

后端：

```bash
cd /Users/congming/github/goldenshare
uv run --project . python -m pytest \
  tests/test_wealth_detail_volume_display.py \
  tests/test_index_detail_field_mapper.py \
  tests/web/test_wealth_stock_detail_api.py \
  tests/web/test_wealth_index_detail_api.py
```

前端：

```bash
cd /Users/congming/github/goldenshare
npm --prefix wealth run test -- \
  src/shared/charts/detail-workspace/detailChartIndicatorRange.test.ts \
  src/shared/charts/detail-workspace/DetailChartWorkspace.test.tsx \
  src/features/stock-detail/api/stockDetailViewModelAdapter.test.ts \
  src/features/index-detail/api/indexDetailViewModelAdapter.test.ts \
  src/features/stock-detail/chart/StockChartWorkspace.test.tsx \
  src/features/stock-detail/chart/StockMinuteChartWorkspace.test.tsx \
  src/features/index-detail/chart/IndexChartWorkspace.test.tsx \
  src/features/index-detail/chart/IndexMinuteChartWorkspace.test.tsx

npm --prefix wealth run typecheck
npm --prefix wealth run build
```

收口：

```bash
git diff --check
git status --short
```

---

## 13. 计划对账

| 技术方案硬口径 | LLD 落点 | 测试门禁 |
|---|---|---|
| 后端生成固定“万”文本 | 第 4 章 | formatter + 两类 API |
| 2 位、HALF_UP | 4.1 | 舍入边界测试 |
| raw vol 不变 | 4.2～4.3、5.5 | mapper/API/adapter |
| 前端不计算日线量单位 | 5.3～5.5 | 删除旧 formatter + 展示测试 |
| MACD 三值共同 extrema | 6、7 | 纯函数 + workspace |
| KDJ 三值共同 extrema | 6、7 | 纯函数 + workspace |
| 只统计完整 K 线 | 6.2 | fractional range |
| 标签只在右轴 | 7.4 | price-line mock |
| 标签等宽右对齐 | 7.4 | custom price formatter |
| 标签背景与 Figma 一致 | 7.4 | price-line color + Figma contract |
| 极值线即动态上下边界 | 7.4 | price-line mock + panel class/CSS |
| 指标无额外自动横线/刻度 | 7.4 | pane grid options + tickmarks formatter |
| 相等值安全范围 | 6.2、7.4 | 0/100 退化测试 |
| 单边 MACD 不含 0 | 7.4 | 全正/全负测试 |
| 四场景共享 | 第 8 章 | 四消费者回归 |
| 不重建 chart、不发请求 | 7、10 | createChart/API call count |

当前无待拍板项。开发必须按 M1～M4 顺序推进；发现合同冲突时先更新技术方案与本 LLD，
不得用前端回算、兼容字段或页面私有 autoscale 绕过。

### 13.1 实施结果

1. M1～M3 已按本 LLD 完成，没有修改分钟成交量 API、指标公式或图表窗口合同。
2. 后端目标测试 `51 passed`；前端目标测试 `48 passed`。
3. 前端 TypeScript typecheck 与 production build 均通过。
4. 用户已完成部署和人工交互验收，确认动态纵轴和日线成交量展示无问题。
5. v1.2 边界线与标签对齐修正完成后，目标测试 `24 passed`、前端完整测试 `270 passed`，
   TypeScript typecheck 与 production build 再次通过。

## 14. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1.4 | 2026-08-21 | 记录用户部署与人工交互验收通过；专项闭环 |
| v1.3 | 2026-08-20 | 修正图层遗漏：MACD/KDJ 关闭自动水平网格和自动中间刻度，只保留显式极值边界与可选 zero 线 |
| v1.2 | 2026-08-20 | 冻结右轴标签等宽右对齐与红/灰/绿背景；max/min 水平线改为动态上下边界，并禁止叠加指标 panel 外框线 |
| v1.1 | 2026-08-20 | 按 M1～M4 完成代码开发与自动化验证，记录测试结果；状态保持待部署和人工验收 |
| v1 | 2026-08-20 | 基于当前后端 DTO/mapper、四类详情图表 adapter 和共享 workspace 完成代码级设计；冻结成交量展示合同、MACD/KDJ 动态纵轴、右轴标签、退化范围和单边 MACD 规则 |
