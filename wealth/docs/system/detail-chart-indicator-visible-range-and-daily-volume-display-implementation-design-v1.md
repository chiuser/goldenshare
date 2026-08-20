# 详情页指标动态纵轴与日线成交量展示技术方案 v1

> 状态：技术方案、LLD 与代码开发已完成；待用户部署和人工交互验收。
> 日期：2026-08-20。
> 适用页面：股票详情、指数详情；日线、分钟线。
> 需求范围：股票/指数日线成交量展示单位后端化；共享 MACD/KDJ 按当前可见窗口动态确定纵轴范围。
> 代码级设计：[详情页指标动态纵轴与日线成交量展示 LLD v1](./detail-chart-indicator-visible-range-and-daily-volume-display-low-level-design-v1.md)。
> 关联基线：[指数详情页技术实施方案 v1](../pages/index-detail/index-detail-implementation-design-v1.md)、[详情图表缩放技术实施方案 v1](./detail-chart-zoom-implementation-design-v1.md)。

---

## 1. 文档目的

本专项解决两个用户可见问题：

1. 股票/指数详情日线中的成交量缺少统一的后端展示合同，当前前端分别执行“手 -> 万手/亿手”的领域换算。
2. MACD/KDJ 仍使用图表库通用自动缩放和固定上下留白，无法充分利用指标面板高度；KDJ 还容易给人“固定 0～100”的错误印象。

本文只冻结技术方案和交互口径，不修改业务代码，不部署，不验证页面。

## 1.1 已冻结产品口径

1. 股票/指数详情日线成交量以“万”为固定展示单位，换算在各自后端详情合同中完成。
2. 前端只展示后端返回的成交量文本，不做除法、单位判断或数量级切换。
3. MACD 的纵轴上下界来自当前完整可见 K 线中 `MACD`、`DIF`、`DEA` 三组有限值的共同最大值与共同最小值。
4. KDJ 的纵轴上下界来自当前完整可见 K 线中 `K`、`D`、`J` 三组有限值的共同最大值与共同最小值。
5. MACD 不强制围绕 0 对称；0 轴位置随可见数据上下移动。
6. KDJ 不固定为 0～100，不裁剪 J 值，也不强制包含 0 或 100。
7. 缩放、拖动、容器尺寸变化、数据集切换和增量数据进入后，必须按新的可见窗口重新计算。
8. 动态指标纵轴是详情页共享规则，同时作用于股票/指数、日线/分钟线。
9. 成交量展示固定保留 2 位小数。
10. 指标最大值与最小值标签只显示在现有右侧纵轴。
11. 当最大值等于最小值时，使用 `padding=max(abs(value)*1%, 0.01)` 生成安全范围。
12. MACD 全正或全负时不强制把 0 纳入纵轴范围。

## 1.2 明确不做

1. 不修改 MACD、KDJ 的指标计算公式或数据源。
2. 不改变 K 线、成交量面板的纵轴策略。
3. 不把股票/指数分钟成交量纳入本轮后端展示单位改造。
4. 不改变成交量柱体的源数值语义和相对高度。
5. 不增加用户可配置的纵轴模式。
6. 不新建第二套股票或指数图表实现。

## 2. 当前代码事实审计

### 2.1 股票/指数日线成交量

1. 指数日线从 `core_serving.index_factor_pro.vol` 读取成交量；股票日线详情合同同样返回数值 `vol`，两个源字段的业务单位均为“手”。
2. `IndexDetailQuoteDto/IndexKlineBarDto` 与 `StockQuoteSnapshotDto/StockKlineBarDto` 当前都只有原始 `vol`，没有后端展示文本字段。
3. `indexDetailViewModelAdapter.ts` 当前在前端执行指数基本行情“总量”的万手/亿手换算；`IndexChartWorkspace.tsx` 又独立计算 Tooltip 文本。
4. `stockDetailViewModelAdapter.ts` 当前在前端执行股票 `万手/手` 换算，`StockChartWorkspace.tsx` 仍有面板标题和 Tooltip 的独立格式化入口。
5. 因此同一单位事实散落在多个前端 adapter/workspace 中，既违反领域职责，也会形成股票与指数之间、标题与右栏之间的不一致。
6. 股票日线 adapter 还会把缺失的 `MACD/DIF/DEA/K/D/J` 转成数值 `0`；指数日线和两类分钟 adapter 均保留 `null`。动态纵轴若不先清除这项错误归零，会把“尚无指标值”误当成真实 0，因此本轮必须同步把股票日线这六个字段改为有限值或 `null`。

### 2.2 MACD/KDJ 纵轴

1. 四类详情图表已经统一消费 `DetailChartWorkspace`：股票日线、股票分钟、指数日线、指数分钟没有必要分别修改。
2. 四个 pane 共用 canonical logical range，缩放和拖动后会同步到 K 线、MACD、成交量、KDJ。
3. 当前 `buildChartOptions()` 对所有 pane 统一设置 `rightPriceScale.autoScale=true` 和 `scaleMargins={top:0.12,bottom:0.12}`。
4. 该通用配置没有把 MACD 的三组值或 KDJ 的三组值按可见窗口合并为一个确定域，也无法保证纵轴边界就是可见数据的真实 extrema。
5. 现有 `resolveVisibleIndexRange()` 已定义“只统计 logical range 内完整 K 线”的规则，可直接复用，避免边缘半根 K 线造成范围跳动。

### 2.3 CodeGraph 影响面

本专项已使用 CodeGraph 核验后端字段链路和共享图表消费者。影响面固定为：

1. 后端：股票/指数详情 schema、field mapper、日线 API 集成测试。
2. 详情前端：股票/指数 API types、ViewModel adapter、基本行情、日线成交量标题和 Tooltip。
3. 共享图表：可见索引解析、指标范围纯函数、MACD/KDJ price-scale 应用和共享组件测试。
4. 消费者：股票日线、股票分钟、指数日线、指数分钟四类图表均需回归；不存在第五套详情图表消费者。

## 3. 总体设计

```text
Stock/Index daily vol (手)
  -> 各自 backend 保留原始 vol
  -> backend 统一生成 volDisplay="58.63万"
  -> frontend histogram 使用 vol
  -> frontend 右栏/标题/Tooltip 原样展示 volDisplay

canonical visible logical range
  -> resolveVisibleIndexRange()
  -> MACD: scan macd/dif/dea
  -> KDJ: scan k/d/j
  -> resolve exact shared min/max
  -> apply pane-specific price range
  -> render extrema boundary labels and movable zero line
```

职责边界：成交量单位是后端业务展示语义；当前可见窗口是前端交互状态；指标源数据仍由后端提供，前端不重算指标。

## 4. 股票/指数日线成交量展示契约

### 4.1 正式契约

保留原数值字段，并新增展示字段：

```text
IndexDetailQuoteDto
  vol: number | null          # 原始“手”，用于事实与既有数值消费
  volDisplay: string | null   # 后端生成，例如 "58.63万"

IndexKlineBarDto
  vol: number | null          # 原始“手”，用于成交量柱体
  volDisplay: string | null   # 后端生成，供标题和 Tooltip 直接展示

StockQuoteSnapshotDto / StockKlineBarDto
  vol: number | null          # 原始“手”，用于事实与成交量柱体
  volDisplay: string | null   # 股票详情后端以同一规则生成
```

不把 `vol` 改成字符串，原因是成交量柱体需要连续数值；也不把 `vol` 的数值单位偷偷改成“万”，避免破坏已有合同和图表相对值。

### 4.2 格式规则

已冻结为：

1. `volDisplay = vol / 10_000`，固定使用“万”，不再切换“手/亿手”。
2. 保留 2 位小数，固定使用 `ROUND_HALF_UP`。
3. 例：`586339 -> "58.63万"`。
4. `null`、NaN 或无限值返回 `null`，前端只使用统一缺失占位 `--`。
5. 不附加“手”字，Figma 和页面统一显示 `58.63万`。

### 4.3 前端消费范围

股票/指数日线以下位置统一改为展示后端文本：

1. 基本行情或盘口右栏的成交量/总量。
2. 成交量面板标题“总量”。
3. K 线 Tooltip“成交量”。

成交量柱体继续使用 `vol` 数值。前端删除上述位置的 `/10_000`、`/100_000_000` 和单位分支，不保留兼容 formatter。

## 5. MACD 动态纵轴

### 5.1 数据范围

1. 输入点只取当前 pane canonical logical range 中的完整 K 线索引。
2. 每个点检查 `macd`、`dif`、`dea`。
3. 只统计有限数值；`null`、NaN、正负无限值忽略。
4. `min = min(visible macd/dif/dea)`，`max = max(visible macd/dif/dea)`。

### 5.2 坐标规则

1. 纵轴上界等于 `max`，下界等于 `min`。
2. 不执行 `max(abs(min), abs(max))` 对称化。
3. 当 `min < 0 < max` 时显示 0 轴，位置按 `zeroYRatio=max/(max-min)` 计算。
4. 全正或全负时不强制把 0 纳入范围。
5. 顶部和底部边界标签显示真实 `max/min`；中间刻度不得反向扩大数据域。

示例：可见窗口 `max=7.79`、`min=-9.55` 时，0 轴位于面板高度约 44.93% 处，不在垂直中心。

## 6. KDJ 动态纵轴

### 6.1 数据范围

1. 输入点仍来自同一 canonical logical range。
2. 每个点检查 `k`、`d`、`j`，只统计有限数值。
3. `min = min(visible k/d/j)`，`max = max(visible k/d/j)`。

### 6.2 坐标规则

1. 纵轴上界等于 `max`，下界等于 `min`。
2. 不固定 0～100。
3. J 大于 100 或小于 0 时完整进入范围，不裁剪、不压回边界。
4. KDJ 全部在 0～100 内时，仍以当前可见真实 extrema 为边界，不人为补 0 和 100。
5. 顶部和底部边界标签显示真实 `max/min`。

## 7. 共享可见范围刷新机制

动态范围必须接入现有 canonical viewport 提交流程，不新增四套订阅：

1. 首次加载完成并应用初始可见范围。
2. 用户点击放大/缩小按钮。
3. 用户拖动历史区间。
4. 未交互态容器 resize 导致默认可见根数变化。
5. `dataKey` 切换，包括股票/指数和日线/分钟频率切换。
6. 增量数据进入并保持 latest anchor。

每次 commit 只执行一次 O(V) 范围计算，`V <= 180`；MACD/KDJ 合计最多检查 `180 * 6 = 1080` 个标量，不发请求、不重建 chart、不遍历全量历史。

## 8. 前端实现边界

新增共享纯函数：

```ts
resolveVisibleIndicatorRange(points, logicalRange, fields):
  { min: number; max: number } | null
```

规则：

1. 内部复用 `resolveVisibleIndexRange()`。
2. MACD 字段固定为 `macd/dif/dea`，KDJ 固定为 `k/d/j`。
3. 不接受页面自定义字段或范围模式。
4. 计算结果只应用到对应 indicator pane；K 线和 volume 不变。
5. chart 生命周期仍由 `DetailChartWorkspace` 唯一管理。
6. React state 不保存完整范围明细，避免 visible-range 回调触发图表重建；使用 runtime ref/series option 更新。

## 9. Figma 交互设计落点

本轮设计稿需同步表达：

1. `08 Index Detail - Desktop Loaded` 三个 Loaded 根画板和 `06 Stock Detail - Desktop Loaded` 股票根画板中的成交量统一显示 `总量:58.63万`。
2. 股票与指数 Loaded 根画板中的 MACD 纵轴改成非对称动态示例：顶部 `7.79`、底部 `-9.55`，0 轴不居中。
3. 股票与指数 Loaded 根画板中的 KDJ 纵轴改成动态 extrema 示例，不再展示固定 0/40/80/120 语义。
4. 增加交互交付说明：缩放、拖动、resize、dataKey 切换后重新计算；规则共享到股票/指数和日线/分钟。
5. 设计稿只表达交互和视觉结果，不把 `vol / 10_000` 写成前端行为。

本轮已完成以下 Figma 设计修改：

1. `08 Index Detail - Desktop Loaded` 三张 Loaded 根画板：Basic `417:2`、Weights `423:2`、Technical `423:910`。
2. `06 Stock Detail - Desktop Loaded` 股票根画板：`345:3`。
3. 四张画板的成交量标题均为 `总量:58.63万`；股票盘口与指数 Basic 右栏同步为 `58.63万`。
4. 四张画板的 MACD 纵轴示例均为顶部 `7.79`、动态 0 轴、底部 `-9.55`。
5. 四张画板的 KDJ 纵轴示例均为 `104.95 / 67.16 / 29.37 / -8.42`，明确表达非固定 0～100。
6. 共享交互合同节点为 `728:723`，位于 `10 Detail Chart Zoom - Web Handoff` 页面，覆盖后端日线成交量文本、MACD 范围、KDJ 范围和四场景刷新规则。

评审入口：

- [指数详情 Basic Loaded](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=417-2&m=dev)
- [股票详情 Loaded](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=345-3&m=dev)
- [Indicator Range + Daily Volume 交互合同](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=728-723&m=dev)

### 9.1 TODO：共享详情图表 Figma 交互组件

Figma 节点：`733:631`，状态明确为“未开工”。

目标：将股票/指数 × 日线/分钟共用的 K 线、MACD、成交量、KDJ 四窗格设计为通用 Figma 交互组件；页面只通过组件属性或插槽提供领域 Header、Tooltip、主图 Overlay、九转层和状态附件。

当前评估：

1. 当前真正组件化的只有缩放按钮、趋势通道、右栏和九转等局部；四种图表仍是四张完整交付画板，不能直接一键转成同一个 component。
2. Figma 工作量为中等偏大，完整收敛预计 `2～3` 人日：
   - 四场景差异矩阵与组件属性设计：`0.5` 人日；
   - 四窗格 shell、pane、轴、Tooltip/Overlay 插槽和 variants：`1` 人日；
   - 四场景实例替换、页面引用整理和视觉回归：`0.5～1.5` 人日。
3. 若只建立组件骨架、不替换现有画板，约 `1～1.5` 人日，但会留下两套设计事实源，不建议采用。
4. 本轮只登记 TODO 和工作量，不创建组件、不替换画板、不改变代码。

评审入口：[Shared Detail Chart Interaction Component TODO](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=733-631&m=dev)。

## 10. 测试与验收计划

### 10.1 后端

1. `vol=586339` 返回 `volDisplay="58.63万"`。
2. 小于 1 万仍按万显示，例如 `5863 -> "0.59万"`。
3. null 返回 null。
4. page-init quote 与 Kline bar 使用同一 formatter。
5. 股票/指数真实详情 API 测试分别断言 `vol` 数值未改变、`volDisplay` 正确。

### 10.2 共享纯函数

1. fractional logical range 只统计完整索引。
2. MACD 三组值共同决定 extrema。
3. KDJ 三组值共同决定 extrema，J 超出 0～100 时不裁剪。
4. null/NaN/Infinity 被忽略。
5. 全部无有效值时返回 null。
6. 全正、全负、跨 0、min=max 均有明确测试。

### 10.3 共享图表

1. 初始加载、缩放、拖动、resize、dataKey 切换后更新 MACD/KDJ 范围。
2. MACD 非对称范围不强制中心 0 轴。
3. KDJ 不固定 0～100。
4. 四类消费者都走同一 helper，没有页面私有实现。
5. 一次 viewport commit 不重建四个 chart、不触发 API 请求。
6. 股票/指数日线成交量文字入口都使用各自后端 display 字段，前端不存在换算除法。

### 10.4 人工交互验收

1. 股票/指数日线右栏、成交量标题、Tooltip 的单位和数值一致。
2. 缩放显示更少或更多 K 线时，MACD/KDJ 纵轴边界随可见数据变化。
3. 拖动到不同历史区间时，范围随区间变化，四 pane 时间坐标仍对齐。
4. 股票/指数、日线/分钟四种场景视觉行为一致。

## 11. 性能预算

| 项目 | 门禁 |
|---|---|
| 后端成交量格式化 | 每个返回 bar O(1)，不增加数据库查询 |
| 可见范围扫描 | 每次 O(V)，`V <= 180` |
| 额外 API 请求 | 0 |
| chart 重建 | 0 |
| 全历史扫描 | 0 |
| 页面私有订阅 | 0；复用 shared canonical viewport |

## 12. 风险与缓解

| 风险 | 原因 | 缓解 |
|---|---|---|
| 把 `vol` 改成字符串导致柱体无法绘制 | 展示合同与数值事实混用 | 保留 `vol`，新增 `volDisplay` |
| 基本行情、标题、Tooltip 单位不一致 | 多个前端 formatter | 后端单一 formatter，前端只展示文本 |
| MACD/KDJ 仍显得扁平 | 通用 12% margin 或自动域扩大 | indicator pane 使用确定 extrema，不复用 K 线 margin |
| 边界半根 K 线导致范围跳动 | fractional logical range | 复用完整可见索引规则 |
| 缩放时频繁重建图表 | 把范围写入 chart 创建 effect | runtime ref 更新 scale，不改 chart lifecycle |
| 极值相同导致零高度域 | 全部值相同 | `padding=max(abs(value)*1%, 0.01)`，范围为 `[value-padding,value+padding]` |
| 缺失指标被误算为 0 | 股票日线 adapter 使用 `valueOrZero` | 六个 MACD/KDJ 字段统一保留有限值或 `null` |

## 13. 分期

1. D0：本文与 Figma 评审，冻结产品口径。已完成。
2. D1：编写代码级 LLD，补 API contract 和共享图表 contract。已完成。
3. D2：后端 formatter、schema、mapper 和真实 API 测试。已完成。
4. D3：前端成交量 display 字段接入与旧 formatter 清零。已完成。
5. D4：共享 MACD/KDJ 动态范围实现与四消费者回归。已完成。
6. D5：typecheck/test/build 已完成；真实 API smoke、部署和人工交互验收待用户执行。

## 14. 已拍板项

1. **成交量小数位**：固定 2 位，例如 `58.63万`。
2. **指标 extrema 标签位置**：只显示在现有右侧纵轴，不新增左轴标签。
3. **`min == max` 的安全跨度**：`padding=max(abs(value)*1%, 0.01)`，最终域为 `[value-padding,value+padding]`。
4. **全正/全负 MACD 的 0 轴**：不强制把 0 纳入范围；只有 `min < 0 < max` 时才显示 0 轴。

本专项已无待拍板项。若开发中发现当前代码或 `lightweight-charts@5.2.0` 类型合同与本文冲突，必须先回写本文和 LLD，不得自行改变上述口径。

## 15. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1.2 | 2026-08-20 | 按冻结方案完成后端成交量展示合同、前端日线展示接入、共享 MACD/KDJ 可见窗口纵轴及自动化验证；待部署和人工验收 |
| v1.1 | 2026-08-20 | 冻结成交量精度、右轴标签、退化范围和单边 MACD 规则；补充股票日线缺失指标错误归零的代码审计结论；进入 LLD 完成态 |
| v1 | 2026-08-20 | 初版并扩展：冻结股票/指数日线后端成交量展示合同、共享 MACD/KDJ 可见窗口动态纵轴方案和通用 Figma 组件 TODO |
