# 股票详情页 Figma 像素级还原执行计划 v1

**状态：M0-M7 已完成，M6/M7 于 2026-07-31 因 KDJ 时间轴构造缺陷重新核验后通过。** 默认 loaded 态、模块裁切、DOM/CSS 量测、K 线 hover 及 mouse leave 消失态均已完成有效取证；loaded 主稿已完成 shared Shell、顶部内容、四区图表工作台和右侧信息栏的原生 Figma 构造，交互状态单独记录在状态页。页面结构与视觉基线已验收；位图级别仍保留已登记的字体与抗锯齿平台差异。

**目标文件：** [Goldenshare Web](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=0-1)

**本轮范围：** 以当前已登录、本地运行的股票详情页为唯一视觉基线，使用可编辑的原生 Figma 图层高保真还原桌面 loaded 页面；先完成可复现量测、Figma 施工和验收账本，再进入逐模块施工。

> **2026-07-30 执行记录。** M0 已冻结 `300169.SZ` 的默认 loaded DOM、computed style、完整页面与九个模块裁图，并验证了 K 线 hover 的当前可见态。浏览器直接 `clip` 裁图仍忽略非零原点；本次模块图改由同一张已校验的全页源图经本地 CoreGraphics 裁切，且逐项核对来源与输出角点，故模块量测有效。用户以真实鼠标将指针移出图表区后，DOM 已确认 tooltip、十字线与日期标签均不存在，并保存了离开态截图和 JSON。该交互证据采自 `761 x 800` 的用户浏览器视口，仅用于验证消失行为；页面几何仍严格使用同一 capture run 的 `1600 x 1200` 量测。具体事实与保留产物见 [M0 验收台账](stock-detail-figma-pixel-verification-ledger-v1.md)。

---

## 1. 目标、范围与非目标

### 1.1 目标

1. 在现有 `Goldenshare Web` Figma 文件中建立股票详情页的桌面 loaded 主稿，默认样本为 `300169.SZ`。
2. 保持当前页面的交易终端布局、信息密度、红涨绿跌、图表四区比例、右侧信息栏和共享顶部栏，不重新设计。
3. 所有页面结构、图表、文本、表格、按钮和状态均使用原生可编辑 Figma 节点构造。
4. 建立可追溯的 capture manifest、量测结果和模块级验收账本，确保后续页面或样式变更有明确重建路径。

### 1.2 本期范围

| 区域 | 当前代码锚点 | Figma 还原范围 |
|---|---|---|
| 共享顶部栏 | `wealth/src/shared/ui/top-market-bar/TopMarketBar.tsx` | 品牌、一级导航、指数跑马灯、用户入口；必须复用市场总览已有的 shared component，不得制作第二套。 |
| 面包屑与行动条 | `wealth/src/features/stock-detail/layout/StockBreadcrumbActionBar.tsx` | 面包屑层级、当前股票标识和分隔关系。 |
| 图表工具栏 | `wealth/src/features/stock-detail/layout/StockChartToolbar.tsx` | 股票身份、周期按钮、操作按钮、active/disabled 外观。 |
| 图表工作台 | `wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx` | 主 K 线、MACD、成交量、KDJ、右轴、横轴、指标信息条、十字线和 tooltip。 |
| 右侧信息栏 | `wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx` 及其子组件 | 股票头部、盘口/资料 tabs、盘口摘要、关联板块、个股资金统计、产品边界说明。 |
| 交互与状态说明 | `StockDetailToast.tsx`、图表交互实现 | hover、tooltip、crosshair、MA/BOLL、tabs、toast、不可用周期等说明；不混入 loaded 主稿。 |

### 1.3 明确不做

1. 不改动 `wealth/**` 产品代码、后端 API、数据模型、图表逻辑或 CSS。
2. 不把旧 `stock-detail-v1.4.3.html` 当作当前页面尺寸、颜色或布局的事实源。
3. 不为 Figma 方便而补造产品能力，不增加新的周期、指标、盘口字段、用户动作或实时行情语义。
4. 不将浏览器截图、Canvas 截图、导出 PNG 作为 Figma 图层或 image fill；仅品牌 logo 可以使用原始位图资产。
5. 不将动态数据差异误判为 Figma 施工缺陷，更不能用伪造数据掩盖差异。

---

## 2. 视觉事实源与优先级

### 2.1 唯一视觉事实源

本轮唯一施工基线是同一次本地、已登录、loaded 页面 capture：

```text
http://127.0.0.1:5173/wealth/market/stock/300169.SZ
```

每次施工或验收都必须绑定 capture id。若本地 CSS、HTML、页面状态或股票数据改变，旧 capture 立即转为 `SOURCE_CHANGED`，不得继续用于通过判定。

### 2.2 冲突时的优先级

1. 用户本轮最新明确指令。
2. 同一次本地 loaded capture 的 DOM geometry、computed style 和可见页面结果。
3. 当前工程代码和 CSS：`StockDetailPage`、股票详情 feature、shared `TopMarketBar`、`stock-detail-page.css`。
4. 股票详情三件套，用于确认已实现功能范围、真实/模拟数据边界和交互语义。
5. `wealth/docs/update/stock-detail-v1.4.3.html`、设计 token、组件指南和 showcase，仅用于补齐当前页面未显式暴露的语义或状态，不得覆盖第 2、3 项。

这条顺序的含义是：先精确还原用户当前正在看的页面；历史原型只能解释意图，不能要求当前页面退回历史视觉。

### 2.3 已确认的工程事实

1. `WealthRouter` 对 `/wealth/market/stock/:tsCode` 解析后渲染 `StockDetailPage`。
2. 股票详情页和市场总览页已消费同一个 `TopMarketBar` 源组件；Figma 也必须使用一个 shared component instance，而不是复制页面顶栏。
3. 股票详情首期的核心行情由 `page-init -> kline` 两段真实 API 加载；右侧关联板块、个股资金和用户动作仍是独立 mock、disabled 或 toast 边界。视觉 capture 只冻结可见结果，不改变其真实来源。
4. 页面 `.stock-detail-app` 是 `height: 100vh`、`min-width: 1180px` 的固定桌面终端，不应被 Figma 还原为可自由纵向滚动的普通后台页面。
5. 图表工作台由 K 线主图、MACD、成交量、KDJ 四个纵向连续 plot 组成；十字线、浮动轴标和 tooltip 属于图表局部交互，不能只画主图而省略下方指标区。

---

## 3. 可复现取证协议

### 3.1 Capture 固定条件

| 项目 | 固定值或记录方式 |
|---|---|
| URL | `http://127.0.0.1:5173/wealth/market/stock/300169.SZ`；断言不是登录页、页面主根存在、无初始 loading/error。 |
| 浏览器 | 当前可用 in-app Chromium；记录版本。 |
| viewport | `1600 x 1200` CSS px。 |
| device scale factor | `1`。 |
| 浏览器缩放 | `100%`。 |
| 页面状态 | 首次请求均 settled；关闭 debug；默认日 K、默认主图指标；无 hover、无 tooltip、无 focus ring。 |
| 数据边界 | 记录 capture 开始/结束时间、`tsCode`、页面 `tradeDate`、股票名称和每个区域的可见状态。 |
| 交互状态 | tooltip/crosshair、MA/BOLL、tabs、toast、disabled 周期单独采集，不与默认 loaded 截图混用。 |
| 输出 | 全页 1x PNG、模块 1x crop、DOM geometry JSON、computed style JSON、量测摘要、manifest。 |

本轮的 Figma 页面根以 capture 实测的 `1600px` 宽度和实际 viewport 高度为准；不得用浏览器窗口截图的裁切尺寸、设备 DPR 或历史 `800px` 截图猜测页面尺寸。

mouse leave 属于交互可见性事实：若需要用户用真实鼠标完成该动作，可以在较小的已登录视口取证，但该截图只能证明元素已清除，不能替代本节 `1600 x 1200` 的几何施工基线。

### 3.2 采集内容

对每个模块根和内部锚点至少记录：

```text
selector / DOM path / text digest / getBoundingClientRect
display / position / box-sizing / grid-template-columns / grid-template-rows
flex-direction / justify-content / align-items / gap
margin / padding / width / min-width / max-width / height / min-height
font-family / font-size / font-weight / line-height / letter-spacing
color / background / border / border-radius / box-shadow / opacity
overflow / transform / z-index
```

图表额外记录：

```text
每个 panel root / header / plot area / right-axis / time-axis
网格线 / 轴刻度 / K线或柱线边界 / MA-BOLL-MACD-KDJ 线段
默认、hover 和离开后的 tooltip/crosshair 边界与可见性
四区同一时间锚点的纵向对齐关系
```

Canvas 无法提供可拆 DOM 时，可用同一 capture 的截图像素坐标建立子账本；这只用于量测，不能把截图导入 Figma。

### 3.3 产物位置

```text
wealth/docs/pages/stock-detail/
  stock-detail-figma-pixel-reconstruction-plan-v1.md
  stock-detail-figma-pixel-verification-ledger-v1.md       # M0 创建
  figma-pixel-artifacts/
    <capture-id>/
      manifest.md
      dom-geometry.json
      computed-styles.json
      measurement.md
      full-page.png
      modules/<module-key>.png
      interactions/<state-key>.png
      figma/<module-key>.png
      diffs/<module-key>.png
```

只提交可复查的 manifest、账本和差异说明；图像与 JSON 是否入库由后续 capture 体积决定，但目录结构和 hash 必须可追溯。

---

## 4. Figma 构造规范

### 4.1 页面与组件组织

| Figma 页面或资产 | 职责 |
|---|---|
| `06 Stock Detail - Desktop Loaded` | 唯一 loaded 主稿。只由 shared 与 stock-detail component instances 组成。 |
| `07 Stock Detail - States and Interaction Notes` | tooltip、crosshair、MA/BOLL、tab、toast、disabled 周期及加载/错误说明。不得与 loaded 主稿混排。 |
| `TopMarketBar / Shared / Loaded` | 复用市场总览已使用的共享顶部栏组件；如 source 变更，先更新 shared component，再由两个页面回读。 |
| `Stock Detail / Components` | 本页特有的 breadcrumb/action bar、toolbar、chart panel、info rail、summary grid、table row、toast。 |

页面编号为建议命名；执行前先读取当前 Figma 文件的实际 page 树，若已有同名页则复用而不是创建重复页面。

### 4.2 原生构造规则

| 线上结构 | Figma 构造 |
|---|---|
| Flex row/column | Auto Layout，显式记录 padding、gap、对齐、grow/fill/hug。 |
| 固定桌面 shell | 使用固定 frame；不把终端区域拆成会改变比例的响应式卡片流。 |
| Panel、chip、button、tab | 由 component/property 构造，颜色、border、radius、shadow 绑定 Foundations。 |
| 表格与摘要 grid | 按实际列宽、row height、分隔线与对齐还原；不得手工平均分列。 |
| 图表 | 以原生 Vector、Line、Rectangle、Text 重建；plot area 和 axis 先量测后绘制。 |
| 浮层 | tooltip、axis float label、toast 可用局部绝对定位；位置必须来自对应 hover capture。 |
| 文本 | 中文文本使用已量测的正文样式；数值使用已量测的数值字族和 tabular-width 规则。 |

浏览器数值字族若在 Figma 中不可用，按市场总览已确认口径使用 `Roboto Mono`，并在验收账本登记为 `FONT_RENDERING_GAP_OPEN`；不得以此放宽字号、行高、宽度或布局的量测要求。

---

## 5. 分阶段执行步骤与门禁

### M0：冻结股票详情页 capture run

1. 按第 3.1 节打开 `300169.SZ` 的 loaded 页面，确认真实 API 已完成且没有 loading/error 覆盖层。
2. 采集页面根、顶部栏、面包屑、工具栏、左侧四区图表、右侧信息栏和底部指标栏的 geometry/computed style。
3. 单独采集默认态、主图 hover、指标区 hover、鼠标离开、MA/BOLL 选择、盘口/资料 tab、toast 和不可用周期状态。
4. 建立 `capture-id`、manifest 与股票详情页验收账本，记录 source 的 HTML/CSS 版本或本地运行时样式来源。
5. 对截图、量测与 Figma 输出使用同一 DOM 根和同一数据时点；若数据或 CSS 已变，废弃当前 capture。

**放行门禁：** 已取得完整 manifest、模块裁图、几何与样式数据，以及 hover 和离开后的元素可见性证据；允许进入 M1。

### M1：共享 Shell 与页面纵横骨架

施工顺序：`页面根 -> shared TopMarketBar instance -> 面包屑行动条 -> 图表工具栏 -> main 左右分栏`。

1. 以 M0 量测值建立固定桌面 page root、背景层、TopMarketBar 高度、面包屑高度、工具栏高度和主内容可用高度。
2. 左侧图表工作台和右侧信息栏按当前 CSS 的实际 `min/max width`、gap、border 和 overflow 约束构建，不能依据视觉猜测比例。
3. 建立共用 Panel、button、chip、tab、text style、direction color 等 Foundations；只收录当前页面已出现的 token。
4. 在 Figma 中插入 shared `TopMarketBar` instance，禁止 detach 或复制后修改。

**放行门禁：** page root、三个顶部层、左右主列、主内容高度、Panel 外框、数值字形和涨跌色均完成逐项核对，取得 `GEOMETRY_PASS` 与 shell `STYLE_PASS`。

### M2：股票身份、导航与操作层

施工顺序：`breadcrumb -> 股票身份区 -> 周期分段按钮 -> 操作按钮`。

1. 精确还原面包屑的文本层级、间隔、当前股票高亮和前缀位置。
2. 精确还原股票名称、代码、行业/区域 tags、周期标题、每个周期 chip、当前日 K active 状态，以及复权/资料/诊股/设置按钮。
3. 只在交互说明页表达不可用周期和 toast；loaded 主稿只保持当前默认可见状态。
4. 不因首期只有日 K 真实数据而删除当前工具栏上已存在的周期控件。

**放行门禁：** 所有文本的 family、size、weight、line-height、letter-spacing，全部 chip 的 height/padding/radius/border 和 active/disabled 色均有量测记录。

**2026-07-31 执行结论：通过。** 面包屑、股票身份、全部 11 个周期按钮和 4 个操作按钮已完成 Figma 原生构造；其实际页面字体为 macOS system stack，Figma 使用可用的 `SF Pro`（Regular/Bold）对齐。工具栏的几何不使用等宽猜测：股票身份最小宽度 `210px`，周期组从 `x=234px` 起，首个周期按钮从 `x=265px` 起，周期组总宽 `580.977px`，右侧操作组在 `1600px` 基线上的起点为 `x=1352px`、总宽 `238px`。实测按钮宽度、chip 高度与 token 绑定记录在验收台账第 6 节。

### M3：左侧图表工作台

施工顺序：`K线主图 -> MACD -> 成交量 -> KDJ -> 统一右轴与底部指标栏 -> hover 状态`。

1. 先按 M0 的 panel/header/plot/right-axis/time-axis 量测建立四区完整高度和相邻边界，确保四区的图表右边界与刻度列对齐。
2. 主图按当前默认主图指标还原 K 线、网格、均线或 BOLL、右轴刻度、当日轴标签和指标信息；指标线颜色必须来自当前 CSS/Canvas 实测。
3. 分别还原 MACD 柱与两线、成交量柱、KDJ 三线及各自 header metric，不能把四区压成一个示意图。
4. 量测并原生构造底部时间轴：日线在当前 K 线密度下的年份和月份标记，以当前实现为准，不套用历史示意图规则。
5. 量测并构造 `crosshair + KlineTooltip + AxisFloatLabel`：同一时间位置跨四区对齐；鼠标离开各图表区后 tooltip 消失；tooltip 位置、右/左切换与数值行均以实际交互 capture 为准。
6. 指标栏保留当前文字、active 外观和当前选择信息；不在主稿中绘制不存在的技术指标结果。

**放行门禁：** 每个 panel 都有独立 plot-area 子账本；四区的 x 对齐、右轴对齐、header 与 plot 不重叠、默认和 hover 的 tooltip/crosshair 均完成复核。图表不得以截图代替。

**2026-07-31 执行结论：通过。** loaded 主稿的四区工作台全部采用原生 `FRAME`、`RECTANGLE`、`LINE`、`VECTOR` 和 `TEXT` 构造；没有引入图表截图或 image fill。K 线使用冻结 capture 同一股票、同一默认日 K 的 90 根真实 bar；MA、MACD、成交量和 KDJ 均按当前页面默认显示的字段和颜色绘制。KDJ 底部时间轴保持实际页面的 `24px` 绝对定位与叠层顺序，但填充必须是 `rgba(10,16,29,.14) -> rgba(10,16,29,.90)` 的纵向渐变，不能以实心深色遮蔽 KDJ 底部曲线。实际 Figma 节点、几何与可见差异归类记录在验收台账第 7 节。

### M4：右侧股票信息栏

施工顺序：`股票头部 -> 用户动作区 -> 盘口/资料 tabs -> 盘口摘要 -> 关联板块 -> 个股资金 -> 产品边界说明`。

1. 量测股票名称、代码、标签、价格、涨跌额/幅、三类操作按钮和 tab bar 的细节。
2. 量测盘口摘要的两列信息格、每一行的固定高度、label/value 对齐和涨跌颜色。
3. 量测关联板块表格的列宽、行高、分割线、文字截断和状态色；不将其变成普通卡片列表。
4. 量测个股资金统计的图形、进度条、数值和单位位置；仅冻结当前可见 fixture，不能宣称它来自已接入的真实数据。
5. 保留产品边界说明的当前可见内容与层级，避免 Figma 误导为真实实时盘口。

**放行门禁：** 右侧 rail 的根尺寸与四个内部区域的分割线、内边距、table/grid 对齐和文字裁切均已验证；当前 mock/disabled 内容在验收账本中标明来源边界。

**2026-07-31 执行结论：通过。** 右栏原生构造了股票头部、三项操作、盘口/资料 tabs、盘口摘要、关联板块、个股资金统计与产品边界说明。真实行情身份和盘口摘要与冻结 capture 对齐；关联板块、资金统计和产品边界继续按当前页面既有 mock/disabled 边界标识，未在 Figma 中伪装为新接入的真实能力。

### M5：状态与交互说明

1. 在状态页逐一表达：TopMarketBar ticker marquee、MA/BOLL 切换、图表 hover/crosshair/tooltip、tab 切换、toast、不可用周期与操作按钮。
2. loaded 主稿不呈现 debug、loading、error、hover 光标或 toast；状态页面不伪造产品中不存在的实时或交易能力。
3. 如当前真实 API 的 loading/error 页面有独立 layout，量测后只作为状态说明，不替换 loaded 主稿。

**放行门禁：** loaded 主稿和状态说明页严格分离；每个状态都能找到代码事件和 M0 interaction capture 证据。

**2026-07-31 执行结论：通过。** 新建 `07 Stock Detail - States and Interaction Notes`，默认 Loaded 主稿保持“鼠标已移出”的无 tooltip、无十字线、无浮动日期标签状态。状态页明确记录了 hover 跨四区十字线、tooltip 与日期标签、MA/BOLL、盘口/资料、toast 和不可用操作。鼠标离开后的消失态由用户在本地页实际操作并确认。

### M6：模块级验收与差异归因

1. 从 Figma 导出 1x 全页和模块 frame，与同一 capture run 的 source crop 对照。
2. 逐模块登记 geometry、文字、颜色、边框、阴影、图表、动态数据和交互差异。
3. 差异仅允许归类为：
   - `FIGMA_CONSTRUCTION_DEFECT`：Figma 构造或值错误，可直接修稿；
   - `SOURCE_CHANGED`：本地页面 CSS/数据已变，重新执行 M0 后再施工；
   - `FONT_RENDERING_GAP_OPEN`：已确认字体不可用或栅格化差异，记录证据，不借此放松几何要求；
   - `CAPTURE_TOOL_DEFECT`：截图或浏览器桥接不可信，先修取证链路，禁止放行。
4. 每一个模块取得可复查的 Figma node、source crop、差异说明和验收状态。

**放行门禁：** 未分类差异不得标记通过；任何模块不得仅凭肉眼“看起来像”获得 `PIXEL_VERIFIED`。

**2026-07-31 复核结论：通过，但记录一项已修复缺陷。** source capture 与 Figma 导出均为 `1600 x 1200`。布局和构造差异的关键坐标通过程序化 Figma 读取逐项对账；在人工视觉复核中发现 `FIGMA_CONSTRUCTION_DEFECT`：节点 `379:347`（KDJ 时间轴）错误使用了 `92%` 不透明实心填充，导致其虽与实际页面同样叠在 KDJ 底部 `24px` 区域，却错误遮蔽了曲线。该节点已改为与线上 CSS 相同的 `.14 -> .90` 纵向渐变，并保留顶部 `1px` 半透明分隔线；不再将这类实质视觉差异归为正常叠层。已登记的开放项只有 `FONT_RENDERING_GAP_OPEN`：浏览器数值 token 首选 `DIN Alternate`，而 Figma 使用可用的 `Roboto Mono`，以及浏览器 Canvas 与 Figma 原生 vector 的抗锯齿差异；该项不改变尺寸、字重、颜色和间距的验收口径。

### M7：页面级复核与交接

**2026-07-31 执行结论：通过。** 最终扫描确认 `06 Stock Detail - Desktop Loaded` 的根 `345:3` 只由 shared 顶栏 instance、面包屑、工具栏和主内容组成；主内容只包含按实测坐标定位的工作台与右栏。`345:4` 仍是 shared component `97:2` 的 instance，未 detach。loaded 主稿无 tooltip/crosshair/date-label 残留，唯一 image fill 是 shared 顶栏中已有的官方 Brand Logo；图表和右栏全部为原生可编辑节点。状态页 `385:2` 仅包含独立的 M5 状态根，不含 image fill，也不污染 loaded 主稿。

**最终状态：`STRUCTURE_AND_VISUAL_BASELINE_VERIFIED`。** 因 `DIN Alternate` 在 Figma 不可用、Canvas 与 Figma vector 栅格化不同，不能诚实宣称两个 PNG 位图逐像素相同；这两个 `FONT_RENDERING_GAP_OPEN` 已明确保留。除此之外没有未分类的构造、几何、状态或资产问题。

### M7：页面级复核与交接

1. 重新读取 Figma 根和所有模块 node 的尺寸，确认未出现 detached shared TopMarketBar、未记录的绝对定位或 image fill。
2. 核对页面固定终端高度、首屏可见密度、所有模块顺序、左右列比例和图表四区比例。
3. 在验收账本写明 capture id、Figma page/node、模块状态、已知字体差异和未通过项。
4. 只有全部模块均满足第 6 节标准，才允许把页面标记为 `PIXEL_VERIFIED`；否则保持 `IN_PROGRESS`，不做完成声明。

---

## 6. 验收标准

### 6.1 模块级放行条件

- [ ] 绑定同一 capture run 的 source 图、DOM root selector、文本状态和 Figma node。
- [ ] 外框、内部 grid/flex、gap、padding、border、radius、shadow 与 computed style 一致。
- [ ] 所有可见文字的字体、字号、字重、行高、字距已核对；任何 fallback 已登记。
- [ ] 涨跌、平盘、次级信息和禁用态颜色符合当前页面 CSS 语义。
- [ ] 图表有独立的 plot-area、axis、series、tooltip/crosshair 子账本。
- [ ] Figma 只使用原生可编辑节点；无截图、无图表 image fill、无 detached shared TopMarketBar。
- [ ] 模块截图叠图或同等可信视觉对照完成，所有剩余差异均有分类。

### 6.2 页面级放行条件

- [ ] 固定桌面 root 的宽高、三个顶部层和主内容可用高度与 source 一致。
- [ ] 左图表区与右 rail 的列宽、间距、边界和 overflow 行为一致。
- [ ] K 线、MACD、成交量、KDJ 四区的 panel 比例、右轴和共享时间锚点一致。
- [ ] 只有品牌 logo 使用位图；图表与页面内容全部可编辑。
- [ ] capture manifest、验收账本、Figma page/component/node 映射完整。
- [ ] 没有将旧 `stock-detail-v1.4.3.html`、默认 mock 或历史 screenshot 覆盖当前本地 CSS/DOM。

---

## 7. 风险与停止条件

| 风险或冲突 | 处理方式 |
|---|---|
| 本地页面数据或 Vite CSS 在施工期变化 | 停止继续对照旧图；新建 capture run，并把旧验收标记为 `SOURCE_CHANGED`。 |
| 图表 Canvas 无可拆 DOM | 用同次截图像素建立图表子账本，再用原生 Figma vector/text 构造；禁止导入截图。 |
| in-app browser 截图裁切或桥接量测不稳定 | 先验证裁图链路与 DOM border-box 一致；工具不可信时标记 `CAPTURE_TOOL_DEFECT`，不继续施工。 |
| Figma 缺少浏览器数值字体 | 仅数值可使用已确认的 `Roboto Mono`，登记字体差异；不得调整布局来掩盖字形差异。 |
| 当前页面实现与三件套或历史原型冲突 | 以当前代码/DOM 为视觉事实；若冲突影响产品语义或范围，停止并单独提出，不在 Figma 中自行裁决。 |
| shared TopMarketBar 被单页私有修改 | 先回到 shared component 校准并复查市场总览，禁止在股票详情页 detach 后修图。 |

---

## 8. 执行前与完成后对账

### 8.1 开工硬约束

1. 只做 Figma 还原、量测、验收账本和关联证据，不改产品代码。
2. 当前 CSS/DOM 是视觉第一优先级，历史文档不能反向覆盖它。
3. Figma 宽度固定为 `1600px`，高度取 M0 capture 的真实 viewport，不凭截图估算。
4. 顶部栏必须复用现有 shared Figma component，禁止第二套或 detached copy。
5. 每个图表区域必须独立量测和验收，不得只还原最上方 K 线主图。
6. 任何 source 变化、字体缺失、量测不完整或图表交互不明确，都必须停在对应门禁，不得“看着差不多”继续。

### 8.2 计划与现有工程的对应关系

| 已确认事实 | 本计划落点 |
|---|---|
| 当前股票详情入口为 `/wealth/market/stock/:tsCode` | 第 2.3 节和 M0 的固定 URL。 |
| TopMarketBar 是跨页面 shared 组件 | 第 1.2、4.1、M1、M7。 |
| 日 K 是当前首期真实数据，右侧部分仍是 mock/disabled | 第 2.3、M0、M4。 |
| 首期只支持 day/forward，其他按钮仍存在 | M2 和 M5。 |
| 现有图表包含四个连续区域和 hover 交互 | M3。 |
| 当前本地 CSS 是视觉第一优先级 | 第 2.2、M0、M6、风险表。 |

### 8.3 本计划完成后的下一步

先执行 M0，建立股票详情页 capture 与验收账本；M0 通过后才开始 Figma M1。任何页面代码、API 或数据源的变化都不是本计划的一部分，必须另开需求处理。
