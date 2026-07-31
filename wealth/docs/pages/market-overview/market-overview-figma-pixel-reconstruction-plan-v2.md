# 市场总览 Figma 像素级还原执行计划 v2

**状态：执行中；用户已指定本地已登录 loaded 页面为本轮视觉事实源。`20260728-local-loaded-1600-1x` 已冻结 `1600 x 1200`、1x 全页截图、16 个模块裁图、模块 geometry、computed style 与 root custom properties。旧远端 M0 与其 `01 Foundations / 62:2` skeleton 已删除，均为 `SOURCE_CHANGED` 历史资产。新 Figma `04 Market Overview - Desktop Loaded / 106:52` 已完成 M1 壳层几何与 Panel 外观对账；M2 已完成 TopMarketBar、面包屑、快捷入口、新闻双列、市场客观总结与主要指数的原生 Auto Layout 构造和首屏截图复验；M3 已完成“涨跌分布”“市场风格”“成交额总览”的 primary loaded 默认态原生构造与模块截图复验。尚无模块获得最终 `PIXEL_VERIFIED`，M7 仍需逐模块叠图签核。**
**目标文件：[Goldenshare Web](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=0-1)**
**执行运行手册：** [市场总览 Figma 像素级执行运行手册 v1](./market-overview-figma-pixel-execution-runbook-v1.md)
**唯一视觉事实源：用户指定本地已登录 loaded 页面 `http://127.0.0.1:5173/wealth/login?redirect=%2Fwealth%2F` 的同一次浏览器 capture run。页面地址仍保留 login redirect，但 DOM 已存在 `main.page-shell` 且无登录表单。**

## 1. 目标、范围与非目标

### 1.1 目标

把当前已部署的市场总览 loaded 页面还原为一份原生、可编辑、可维护的 Figma 设计稿。这里的“像素级”不是“整体风格相似”，而是以下三层同时成立：

1. **几何一致**：由线上 DOM 的 `getBoundingClientRect()` 得出的每个验收锚点，其 `x/y/width/height`、父级 padding、gap、边框宽度、圆角必须逐项匹配 Figma 设计值。
2. **样式一致**：颜色、透明度、背景渐变、border、shadow、字号、字重、行高、字距、数值字族均必须来自同一次 capture run 的 computed style 或对应线上 CSS；不允许凭感觉使用相近值。
3. **视觉一致**：在同为 `1600px`、1x 输出的前提下，浏览器模块截图与 Figma 模块截图逐个叠图检查；像素差异必须被定位到字体渲染、运行时 canvas 抗锯齿或明确的尚未通过项，不能用整页缩放图替代。

### 1.2 范围

1. 仅 `财富乾坤 / 乾坤行情 / 市场总览` 的 desktop loaded 页面。
2. `TopMarketBar` 作为市场总览与股票详情共享 Shell 组件。
3. loaded 页面可见的所有模块：面包屑、快捷入口、新闻、市场客观总结、主要指数、涨跌分布、市场风格、成交额、大盘资金流向、榜单、涨跌停、连板天梯、板块速览、状态样式基线。
4. `loading / empty / error / delayed` 与现有关键交互的静态设计参照。
5. Figma 的源规则、组件结构、变量与验收账本。

### 1.3 明确不做

1. 不修改 `wealth/src/**`、后端 API、数据源、真实数据口径或模块三件套。
2. 不导入浏览器整页截图、模块截图或图表截图充当 UI；logo 是唯一可保留的位图资产。
3. 不重设计、不简化模块、不替换产品文案、不把页面改成后台管理风。
4. 不把运行时 ticker、系统时钟、新闻 10 分钟刷新做成伪可运行的 Figma 动画；只记录真实触发规则与静态状态。
5. 不使用历史 V1.1/V1.8 的视觉取值。

## 2. 施工硬规则

| 编号 | 规则 | 不通过时的处理 |
|---|---|---|
| R1 | 用户指定的本地 loaded DOM/CSS 是本轮唯一第一事实源；V4 仅补充 CSS 无法表达的交互语义。 | 停止该模块，先记录来源冲突。 |
| R2 | 每次施工必须从同一 capture run 读取截图、DOM 几何、computed style、网络数据和版本 hash。 | 证据不完整，模块不得开始。 |
| R3 | CSS Flex/Grid 对应 Figma Auto Layout/明确 grid 约束；绝对定位只允许 CSS 已绝对定位的元素，或图表 plot area 内的点、线、柱、tooltip。 | 不得以手工 `x/y` 代替页面布局。 |
| R4 | 每个 Figma 组件和 primary 页面节点都必须有代码来源：组件路径、CSS selector、capture node、Figma node ID。 | 未登记节点不得作为正式页面内容。 |
| R5 | 每次只返工一个模块；该模块通过账本和叠图门禁前，不进入下一个。 | 禁止“先把全页画出来再一起调”。 |
| R6 | 禁止把差异通过整体缩放、裁剪、隐藏内容或更换数据掩盖。 | 记录为未通过，不能标记完成。 |
| R7 | 字体未确认时，相关模块阻塞；不得静默用 Inter 代替系统中文或等宽数字字体。 | 先取得可用字体或经用户确认的明确 fallback。 |
| R8 | 任何线上 HTML/CSS hash 改变，都必须新建 capture run，旧 run 不得再用于验收。 | 作废受影响模块的通过标记，重新比对。 |

## 3. 可复现视觉证据协议

### 3.1 单次 capture run 的固定条件

每次都记录下列信息，缺一不可：

| 项目 | 固定值或记录方式 |
|---|---|
| URL | `http://127.0.0.1:5173/wealth/login?redirect=%2Fwealth%2F`，并额外断言 `main.page-shell` 存在、登录表单不存在 |
| 浏览器 | Chromium/Chrome 的完整版本号 |
| viewport | `1600 x 1200` CSS px |
| device scale factor | `1` |
| 浏览器缩放 | `100%` |
| 页面状态 | 已完成所有初始请求的 loaded；关闭 DEV debug；无 hover、无 tooltip、无 focus ring，除非采集互动状态。 |
| 时间与数据 | 记录 capture 开始/结束时间、页面 `tradeDate`、每个模块状态、响应 body SHA-256。 |
| 资源版本 | HTML SHA-256、CSS asset URL/SHA-256、JS asset URL；本地代码 revision 仅作辅助。 |
| 输出 | 全页 PNG、每模块 1x crop、DOM geometry JSON、computed style JSON、网络响应索引、capture manifest。 |

**重要：** Figma 宽度固定为 `1600px`。内容区应依 CSS 为 `1564px`（左右 `18px` gutter），顶栏为 `1600 x 56px`。这些数值是本轮第一个可检查锚点，不是经验值。

### 3.1.1 当前 M0 事实状态

当前唯一活动基线是 `20260728-local-loaded-1600-2x`：它在 `2026-07-29T00:32:03.207Z` 从本地已登录 `http://127.0.0.1:5173/wealth/` 采集，条件为 `1600 x 1200` CSS px、DPR `1`、DOM `body.scrollHeight=4343px`、Figma 施工根高 `4342.609375px`。该 ID 中的 `2x` 是第二次本地 capture 的编号，不是 DPR 或导出缩放。它包含 16 个可见模块根、全页 PNG、16 张模块裁图、根与模块 geometry、computed style、stylesheet 来源和 root custom properties；`measurement.json` SHA-256 为 `46556f523924106133cf433d402d3762452723aeaa9cf439ef3d3301545c33f8`，全页 PNG SHA-256 为 `4d552b5dfed947efa6476f9a291adf04158390403a691569be5994c69c47544f`。

`20260728-local-loaded-1600-1x` 仅保留为历史施工证据，不再是当前事实源；旧 `20260727-figma-m0-network-loaded-1600-1x` 是更早的远端证据。两者均不得用于本轮 M1-M7 的通过判断。本轮浏览器量测桥不读取或归档 Cookie、local storage、authorization header、token 或 API 响应正文；当前本地 Vite 样式通过 6 个运行时 style sheet 注入，因此没有稳定的单个 CSS asset hash。视觉数据只以同次 DOM 文本、截图、geometry 和 computed-style 组合冻结。

### 3.2 需要采集的 DOM 属性

对每个验收锚点采集以下字段：

```text
selector / DOM path / text digest / getBoundingClientRect
display / position / box-sizing / grid-template-columns / grid-template-rows
flex-direction / justify-content / align-items / gap
margin / padding / width / min-width / max-width / height / min-height
font-family / font-size / font-weight / line-height / letter-spacing
color / background / border / border-radius / box-shadow / opacity
overflow / transform / z-index
```

图表还必须采集：plot area 边界、axis 线、每个刻度标签、series 路径/bars、tooltip/crosshair 的默认与 hover 边界框。若 Canvas 没有可拆的 DOM 子节点，使用截图像素坐标建立图表子账本，但不得把截图导入 Figma。

### 3.3 文档与产物位置

本仓库只提交可读的 manifest、账本和差异说明；需要复查的 PNG/JSON 可按一次 capture run 归档，不混入产品源代码：

```text
wealth/docs/pages/market-overview/
  market-overview-figma-pixel-audit-v1.md
  market-overview-figma-pixel-reconstruction-plan-v2.md
  market-overview-figma-pixel-verification-ledger-v1.md
  figma-pixel-artifacts/
    <capture-id>/
      manifest.md
      dom-geometry.json
      computed-styles.json
      response-index.md
      full-page.png
      modules/<module-key>.png
      diffs/<module-key>.png
```

创建新 capture run 前，必须先检查线上 HTML/CSS hash；同一目录只对应一套 hash 和一份数据快照。

## 4. 组件与布局施工规范

### 4.1 Figma 构造规则

| 线上实现 | Figma 构造要求 |
|---|---|
| CSS Grid | 保留确定的列数、gap、列比例和 cell；用 Auto Layout wrapper + 明确子项 sizing，不能手画等距近似格子。 |
| Flex row/column | 必须用 Auto Layout，写清 padding、gap、对齐和 grow/fill/hug 行为。 |
| Panel/Card | 从基础组件实例化；颜色、border、radius、shadow 绑定 Foundations，不允许复制后手填。 |
| 文本 | 使用对应 text style；数字另用已核验的数值字族和 tabular width 规则。 |
| SVG/CSS 图表 | 原生 Vector/Line/Rectangle/Text；按 capture 的 geometry 建立 plot area 和点位。 |
| Canvas 图表 | 以截图量测出的 geometry 原生复刻，不能导入 canvas 截图。 |
| 绝对定位 | 只允许在 tooltip、chart plot 的折线/柱/标注、CSS 已绝对定位的 badge 等局部。 |

### 4.2 组件层级

```text
Foundations
  Color / typography / spacing / border-radius / shadow / chart primitive
Shell components
  TopMarketBar / Breadcrumb / ShortcutCard / Panel / SectionHeader
  RangeSwitch / Tab / MetricCard / StatusBlock / Tooltip
Market overview components
  MarketNewsPanel / MarketSummaryPanel / MajorIndexPanel
  MarketBreadthPanel / MarketStylePanel / TurnoverOverviewPanel
  MarketMoneyFlowPanel / LeaderboardPanel / LimitBoardPanel
  StreakLadderPanel / SectorOverviewPanel / StateBaselinePanel
Loaded page
  only component instances and documented composition wrappers
```

组件 component property 只暴露线上已经存在的内容/状态（例如 active tab、market direction、text/number、data state）；不得为方便画稿增加不存在的产品开关。

## 5. 返工顺序与模块门禁

### M0：建立 capture run 与证据清单

1. 打开线上 loaded 页面，按第 3 节固定浏览器条件完成一次 capture run。
2. 冻结 HTML/CSS/JS asset hash、页面请求响应索引、页面状态、`tradeDate` 和截图。
3. 采集全页 layout anchor 与所有模块 root 的 geometry/computed style。
4. 创建 `figma-pixel-artifacts/<capture-id>/manifest.md`，填入验收账本 Run 信息。
5. 如果线上页面未达到 loaded 或任一模块为 error/delayed，停止，不以 mock 或本地数据替代。

**门禁：** 没有完整 capture manifest 与本地可复查模块截图，不得修改 Figma 任何业务模块。

### M1：Layout skeleton 与 Foundations

1. 用 M0 的 CSS/DOM 数值重建 page background、topbar、page shell、`content-grid`、`summary-index-row`、`row-three` 和 `row-two`。
2. 逐项登记 token 的 CSS 变量/最终值，不允许只写语义名。
3. 验证实际 resolved 中文字体和 number 字体；不可用即阻塞。
4. 重建 Panel、Card、Button、Chip、RangeSwitch、Metric、Tooltip 状态。

**门禁：** `1600px` root、`56px` topbar、`18px` page gutter、`12px` module gap、Panel border/radius/shadow 均通过几何与样式账本。

**历史施工结果（2026-07-27）：** 曾在 `01 Foundations` 创建 `Market Overview / Desktop / M1 Layout Skeleton / M0 20260727`（Figma `62:2`）及其顶栏、页面槽位。该资产基于旧远端 `4168/4169px` capture，已由当前本地 `20260728-local-loaded-1600-2x` 的 `4342.609375px` Figma 施工根取代，状态为 `SOURCE_CHANGED`，且已删除；不得再继续微调或复用。

**当前 M1 施工结果（2026-07-29）：** `04 Market Overview - Desktop Loaded / 103:2` 的 primary root 是 `Market Overview / Desktop / Loaded / Local1600 / M7 current source / 106:52`，并使用共享 `TopMarketBar / Shared / Loaded / Local1600 / M1 / 97:2` 的 instance（`106:53`）。程序化回读确认 root `1600 x 4342.609375px`、Shell `1600 x 4286.609375px`、breadcrumb anchor、shortcut、content-grid `1564 x 4106.21875px`、四行组合和四个长页槽位均与 `20260728-local-loaded-1600-2x/measurement.json` 对齐；14 个 Panel 壳均使用本地 CSS 的 `#101827`、`rgba(148,163,184,.16)`、`12px` radius 与 `0 8px 24px rgba(0,0,0,.26)`。这是 `GEOMETRY_PASS` 与壳层 `STYLE_PASS`，不是模块内部或整页 `PIXEL_VERIFIED`。

**已知精度边界：** 当前活动 capture 的 `content-grid` 为 `4106.21875px`；冻结子行高度加七个真实 `12px` gap 后同为 `4106.21875px`。Figma 回读的 root-relative 各模块起点和尺寸均为 `delta = 0`。模块内部文字、图表和表格尚未完成正式叠图，不得因壳层通过而提前标记为 `PIXEL_VERIFIED`。

### M2：共享 Shell 与第一屏框架

施工顺序：`TopMarketBar -> Breadcrumb -> ShortcutBar -> 新闻/总结/主要指数组合`。

| 区域 | 线上代码/CSS锚点 | 必核对项 |
|---|---|---|
| 顶栏 | `TopMarketBar.tsx`、`top-market-bar.css` | brand `168px` grid 区、nav 宽度、ticker clipping、user entry、56px 高度、品牌文字上下两行。 |
| 面包屑 | `Breadcrumb.tsx`、`.breadcrumb-row` | `28px` 行高、左右对齐、meta 与状态 pill。 |
| 快捷入口 | `ShortcutBar.tsx`、`.shortcut-bar/.shortcut-card` | 6 列、`10px` gap、`72px` 最小高度、selected 底线。 |
| 新闻双列 | `MarketNewsPanelGroup.tsx`、`.market-news-*` | `220px` 滚动窗、标题点、时间列、单行密度与面板高度。 |
| 总结/指数双列 | `MarketSummaryPanel.tsx`、`MajorIndexPanel.tsx`、`.summary-index-row` | 5 卡默认、总结文案区、指数 2x5、卡片文本层级。 |

**门禁：** 每个区域单独截图叠图通过，才允许继续下一个区域。

**当前施工记录（2026-07-28）：**

1. `TopMarketBar / 106:53`、`Breadcrumb / 106:105`、`ShortcutBar / 106:106` 均已进入 primary loaded root；快捷入口使用 `02 Components - Shell` 中的 `Default / 118:2`、`Selected / 118:8`、`Alert / 120:2` 组件实例。
2. 新闻双列根分别为 `106:109`、`106:110`，两者均为原生纵向 Auto Layout：`10px 12px` padding、`8px` gap、`28px` header、`220px` viewport；正文行为以单行文本密度表达，不以截图或可滚动位图代替。
3. 市场客观总结根为 `106:112`，由 `28px` header、`5` 个 `SummaryFactCard / 132:2` 实例和 `66px` 事实文案区组成；主要指数根为 `106:113`，由 `2 x 5` `IndexCard` 实例组成，所用 component 为 `132:6`、`132:11`。
4. Figma 回读已确认上述容器与重复卡片均为 Auto Layout。首屏 Figma 输出已与同次 capture 的模块裁图进行视觉复验；差异只允许保留为已登记的字体栅格化边缘差异，不能以此掩盖尺寸、间距或文本换行。临时 QA Slice 已删除，不属于正式设计节点。

### M3：中段三列图表

施工顺序：`涨跌分布 -> 市场风格 -> 成交额总览`。

| 模块 | 线上锚点 | 必核对项 |
|---|---|---|
| 涨跌分布 | `MarketBreadthPanel.tsx`、`.breadth-distribution-*` | 默认 tab 是涨跌分布；11 桶次序、柱高、`10px` 标签、数值距柱顶、红涨绿跌、切换到涨跌家数的折线态。 |
| 市场风格 | `MarketStylePanel.tsx`、`.chart-box` | metric 卡、三线颜色、plot area、轴标签与零线。 |
| 成交额 | `TurnoverOverviewPanel.tsx`、`.turnover-charts` | 右/左图坐标格与 text 不重叠、从 0 起的纵轴、同一坐标网格宽度。 |

**门禁：** 图表必须有 plot-area 子账本；不得只比 Panel 外框。

**当前施工记录（2026-07-28）：**

1. `MarketBreadth / 106:115` 已由 M1 空壳转为原生纵向 Auto Layout，外框仍严格保持 capture 的 `513.328125 x 374`；内部为 `12px` 四边 padding、`10px` 第一组间距。
2. 标题行 `SectionHeader / 涨跌分布 / M3 / 149:246` 为 `489.328125 x 30` 的横向 Auto Layout；右侧使用 `RangeSwitch / Two Choices / Loaded / Local1600 / M3 / 149:2` 实例，左侧默认激活“涨跌分布”，右侧保留“涨跌家数”。
3. 三张指标卡使用 `MetricCard / Loaded / Local1600 / M3 / 149:7` 的原生实例，固定三列 `157.776px`、`8px` gap、`82px` 高；数据来自同一 capture：`5195 / 286 / 42` 与 `94.1% / 5.2% / 0.8%`。
4. 默认图使用 `BreadthDistributionChart / Loaded / Local1600 / M3 / 149:11` 实例，严格为 `489.328125 x 210`，背景、border、radius、`14/16/12px` padding 与当前 CSS 对齐。11 个 bucket 均为 editable 的文本和矩形；只有柱、柱顶数值、基线位于 chart plot 内，未用截图或全局 absolute layout。
5. 分桶顺序、数据与语义冻结为：`>10 / 7~10 / 5~7 / 3~5 / 0~3 / 平盘 / 0~3 / 3~5 / 5~7 / 7~10 / >10`；对应值为 `6 / 9 / 11 / 20 / 240 / 42 / 2796 / 1570 / 503 / 210 / 116`。横轴不显示“涨/跌”字样，数值通过同一 bucket stack 保持在各自柱顶上方约 `10px`，而非固定在图表顶部。
6. `涨跌家数` 的折线状态按范围留给 M6 的状态/交互页构造；primary loaded 页只保留当前 capture 的默认“涨跌分布”态，避免把多态内容混入主稿。
7. `MarketStyle / 106:116` 已由 M1 空壳转为原生纵向 Auto Layout，外框仍严格保持 capture 的 `513.3359375 x 374`；内部为 `12px` 四边 padding、`10px` 第一组间距、`30px` 标题行、三张 `82px` 指标卡、`8px` 卡间距及 `178px` 趋势图。趋势图为 `MarketStyleTrendChart / 153:2` 实例，内部 plot area 为 `425.3359375 x 126`，按当前 `MiniLineChart` 的 `48/16/16/36px` canvas padding、五条轴线和三条原生 Vector 路径建立。
8. 三条趋势线不依据截图目测生成：使用本地同一次 capture 状态的 `GET /api/v1/wealth/market/style` 返回的 `oneMonth` 22 个点位，且已核对其 `tradeDate=2026-07-27`、三张 metric card 数值与 capture 一致。图表 y 轴按前端现有 `niceRange` 规则得到 `[-7.313364, 5.464464]`，并显示与 source 一致的 `5.5% / 2.3% / -0.9% / -4.1% / -7.3%` 标签；这只是主态截图复验，不替代 M7 的正式差异图签核。
9. `Turnover / 106:117` 已由 M1 空壳转为原生纵向 Auto Layout，外框严格保持 capture 的 `513.328125 x 374`；内部为 `12px` 四边 padding、`10px` item spacing、`30px` 标题行、四张 `82px` 指标卡与双列图表。专属 `RangeSwitch / Month Range / Loaded / Local1600 / M3 / 163:2` 为 `96 x 30`，不可错误复用涨跌分布的切换文案；四张卡使用 `MetricCard / Turnover / Loaded / Local1600 / M3 / 165:2`，每张由 `(489.328125 - 3 x 8) / 4 = 116.33203125px` 得出。
10. 四张卡的冻结数据来自同一次 `GET /api/v1/wealth/market/turnover?tradeDate=2026-07-27`：`今日成交总额 20887亿 / 截至 15:00`、`较上一交易日 +1442亿 / +7.42%`、`上一交易日成交 19445亿 / 2026-07-24`、`5日均值 23771亿 / 20日均值 28064亿`。这些值与模块裁图一一对应，不以目测近似数据替换。
11. 图表分别使用 `TurnoverChart / Intraday / Loaded / Local1600 / M3 / 166:2` 与 `TurnoverChart / History / Loaded / Local1600 / M3 / 170:2`；每张为 `239.6640625 x 178px`，plot area 为 `167.6640625 x 126px`，固定 padding 为左/右/上/下 `56/16/16/36px`。两图共用从 `0` 开始的 `0 / 10000 / 20000 / 30000 / 40000亿` 五条网格，避免右/左两图出现坐标格宽度或文字重叠差异。
12. 左图以接口返回的 `09:30 / 10:30 / 11:30 / 14:00 / 15:00` 五个累计成交额点建立黄色原生 Vector；右图以同一响应的 `oneMonth` 22 个交易日点建立蓝色原生 Vector。数值、轴、路径、卡片和标题均为 editable Figma 节点；没有导入截图。该记录只证明 primary loaded 主态与尺寸/数据口径，`1个月/3个月` 切换状态、hover/tooltip 和 M7 正式差异图仍未签核。

### M4：中下段双列与表格

施工顺序：`大盘资金流向 -> 榜单速览 -> 涨跌停板`。

| 模块 | 线上锚点 | 必核对项 |
|---|---|---|
| 大盘资金流向 | `MarketMoneyFlowPanel.tsx`、`.moneyflow-v3-*`、`.pie-*` | 分单饼图直径、中心孔、callout 折线与标签、趋势图比例。 |
| 榜单速览 | `LeaderboardPanel.tsx`、`.leaderboard*` | tabs、表头、8 列宽度、行高、股票主体、悬停/点击语义。 |
| 涨跌停板 | `LimitBoardPanel.tsx`、`.limit-*` | statistic cells、板块条、领涨股票行、图表 cell 和分隔线。 |

**门禁：** 表格列宽必须由当前 CSS/table layout 和浏览器量测决定，禁止手工平均分配。

**当前施工记录（2026-07-28）：**

1. `MarketMoneyFlow / 106:119` 已按冻结页面的双列根框建立为原生纵向 Auto Layout，外框为 `776 x 473.21875px`，四边 `12px` padding、子项 `10px` gap；其标题行、双卡行和主体行依次为 `752 x 30px`、`752 x 100px`、`752 x 262px`，位置分别为 root 内 `y=12/52/162`。
2. 标题行 `SectionHeader / 大盘资金流向 / M4 / 188:336` 使用当前 loaded 文案和帮助图标，右侧为月份切换；双卡行 `Fund Top / 2 Cards / gap10 / 188:346` 复用 `FundCard / Money Flow / Loaded / Local1600 / M4 / 178:2`，冻结值为 `+908.3亿 / 2026-07-27` 与 `-774.6亿 / 2026-07-24`。
3. 主体严格为 `286 + 10 + 456px` 两列：左侧环图 panel 为 `188:356`，环图实例为 `188:358`（component `179:2`）；右侧趋势 panel 为 `188:377`，趋势图实例为 `188:379`（component `183:336`）。环图、callout、标题、坐标、网格、折线均是可编辑的原生 Figma 节点，未导入截图。
4. 单型资金数据来自同一次冻结响应：超大单 `+790.09112064亿`、大单 `+118.21195264亿`、中单 `-428.52483072亿`、小单 `-479.77828352亿`；趋势使用同一响应的 `oneMonth` 22 个交易日净流入点。趋势图 root 高 `230px`、plot padding 固定为左/右/上/下 `48/16/16/36px`，依据前端 `niceRange` 口径显示 `2051 / 1026 / 0 / -1026 / -2051亿` 五条水平网格。
5. 右侧标题与图表的相对位置不依赖 Figma 默认 gap：`Top Margin / source sub-chart-title / 193:390` 和 `Chart Gap / source chart-box margin-top / 195:390` 均为透明 `8px` spacer，使标题相对主体 `y=8`、图表相对主体 `y=32`，即图表绝对 `y=194`，与 `.sub-chart-title` 和 `.chart-box` 的源 CSS margin 逐项对应。
6. 当前记录只证明 primary loaded 主态的结构、数据与截图复验；月份切换、hover/tooltip 与 M7 正式叠图仍未签核，不能标为 `PIXEL_VERIFIED`。
7. 榜单速览进入 M4-2 施工前，先分离两类证据：冻结 capture 的 `modules/leaderboard.png` 负责 2026-07-28 primary loaded 的 7 个 tab、8 个表头和 10 行内容；当前本地 loaded DOM 仅用于补齐冻结 capture 未记录的浏览器最终 table layout。实测 content width 为 `750px`，8 列宽依次为 `48.1640625 / 151.375 / 87.1484375 / 87.1484375 / 87.1484375 / 87.1484375 / 100.9140625 / 100.953125px`，表头高 `28px`，10 行均为 `34.171875px`，tab 高 `30.5px`。Figma 必须照此建立原生可编辑表格，禁止用均分列宽、截图或新数据替换冻结行内容。
8. `Leaderboard / 106:120` 已按上述双证据口径完成 primary loaded 主态：root 保持 `776 x 473.21875px`，header `201:390`、tabs `201:399`、table shell `201:415` 依次为 `750 x 28.5px`、`750 x 30.5px`、`750 x 370.21875px`；header-to-tab 与 tab-to-table 间距为 `10px`、`8px`。原生 table header 为 `207:390`，10 行冻结内容分列保存在 `208:390..208:470` 和 `210:390..210:470`，每一行严格为 `34.171875px`，最后一行 bottom edge 为 `369.71875px`。股票名称/代码是独立的两行 editable 文本，所有数值、涨跌色、tab 与分隔线均是原生节点；未导入截图、未按 CSS 声明值均分列宽，也未以当前运行数据替换 capture 内容。该记录只证明 primary loaded 主态，hover/点击状态与 M7 正式叠图仍未签核。
9. 涨跌停板进入 M4-3 施工前，先分离两类证据：冻结 capture 的 `modules/limit-board.png` 负责 `今日 07-27`、`昨日 07-24` 的八项核心统计、两组板块/领涨股文本，以及 `06-26..07-27` 历史组合柱图的静态内容与形态；当前本地 loaded DOM 只用于量测最终几何，得到 panel `1564 x 566.5px`、header `1538 x 30.5px`、`763 + 12 + 763px` 双列、`244 + 12 + 244px` 双行、四个 cell 均为 `763 x 244px`。禁止以本地运行值替换冻结内容，禁止导入模块截图。
10. `LimitBoard / 106:121` 已按上述双证据口径完成 primary loaded 主态：root 使用原生纵向 Auto Layout，四边 `12px` padding、header-to-grid `10px`；header `218:390`、双行 grid `218:404`，四格分别为 `218:407/218:408/218:409/218:410`。左上为八张原生 editable statistic card（四列两行）；右上与右下均为 `219.296875 + 10 + 511.703125px` 的板块条/领涨股结构，领涨股三行固定 `43px`，首行高亮。左下为原生网格、轴、日期、红绿成对柱和标签，不使用图像填充。节点回读与 Figma 模块截图已完成；范围切换、行 hover/点击与 M7 正式叠图仍未签核，不能标为 `PIXEL_VERIFIED`。

### M5：长页模块与正式状态基线

施工顺序：`连板天梯 -> 板块速览 -> 状态样式基线`。

| 模块 | 线上锚点 | 必核对项 |
|---|---|---|
| 连板天梯 | `StreakLadderPanel.tsx`、`.limit-ladder-v5*` | 梯队行高、昨/今结构、箭头、5板以上强调、可进入详情的股票主体。 |
| 板块速览 | `SectorOverviewPanel.tsx` 及对应页面样式 | 热力格、文字截断、板块色语义、资金/涨跌信息密度。 |
| 状态样式基线 | `StateBaselinePanel()`、`.state-lab/.state-block` | 保持正式页面可见；与单独状态页的组件变体一致。 |

**门禁：** 长页面不得通过压缩高度或缩小字号来“塞下内容”。

#### M5-1 已执行：连板天梯 primary loaded 主态

`StreakLadderPanel` 当前按活动 `20260728-local-loaded-1600-2x` 建立：Figma root 为 `106:122`，采用原生纵向 Auto Layout，而非截图或 image fill。root 为 `1564 x 1445.5px`；内部 header/list 为 `1538 x 21px` 与 `1538 x 1388.5px`。当前 DOM 的七个 list child 依次为 summary `34.5px`、五板以上 `138px`、昨日四板→今日五板 `188px`、昨日三板→今日四板 `188px`、昨日二板→今日三板 `188px`、昨日首板→今日二板 `315px`、首板 `265px`，六个 `12px` gap 后严格合计 `1388.5px`。双侧层级卡片仍为 `229px`，首板为六列 `246px` 卡片；文本、价格、涨跌、行业、封单额和连板标签必须保持可编辑。

当前七个真实层均已逐层回读：独立的“五板以上” gold emphasis 层为 `296:390`，只保留 `603221.SH / 爱丽家居 / 16.94 / +10.00% / 3.54亿 / 家居用品 / 6板`；`229:401` 已由历史双行结构改为当前 `188px` 单行的“昨日二板→今日三板”晋级层；`229:400` 已按“昨日三板→今日四板”回填顺钠股份、长城军工和晋级的顺钠股份；`229:399` 已按“昨日四板→今日五板”回填唯一未晋级的五洲医疗及 `229 x 72px` 的今日五板空态；`229:402` 已按“昨日首板→今日二板”回填 `315px` 双行晋级层，左右两侧均为 source 折叠态可见的前 6 张卡，并保留 `103/13` 计数和“展开全部”按钮；`229:403` 已按 `265px` 首板层回填 `45只`、说明文字、12 张 `246 x 80px` 可编辑卡和“展开全部”按钮，回读确认 header/body、两行六列 grid 与所有卡片内容。M7 导出叠图尚未签核，故本模块仍为 `IN_PROGRESS`，不得以历史 `1x` 截图或“5 个梯队”结论标为通过。

#### M5-2 已执行：板块速览 primary loaded 主态

`SectorOverviewPanel` 已按同一本地 frozen loaded 基线建立在 Figma `106:123`。root 采用原生纵向 Auto Layout，固定为 `1564 x 501px`，四边 `12px` padding；header/body 分别为 `1538 x 34.5px` 与 `1538 x 430.5px`。body 的左侧 Top5 矩阵和右侧热力图严格使用浏览器量测的 `1186.788940 + 10 + 341.210999px` 结构，而不是手工均分。

左侧 8 张卡为两行四列，每张 `289.195/289.203 x 210.25px`，包含 `13px` 栏目标题、对应涨/跌或净流入/净流出栏目色，以及五条 `28px` 排行。右侧 `Heatmap Panel / 246:399` 使用原生 `5 x 4` frame/text 网格，preview 为 `319.210999 x 382px`，行/列 gap 均按 source 的 `6px` 建立。所有文字、排行、颜色与热力格都是 editable 原生节点；没有导入模块截图或 image fill。

节点回读已确认尺寸、列数、每卡五行与 20 个热力格。经用户确认，M7 已以当前 local loaded 页面更新 Figma 的动态可见数据：8 张 Top5 卡片共 40 条排行与 20 个热力格均逐项回填；上涨值为 `#ff4d5a`，下跌值为 `#15c784`，当前热力格均为下跌状态、使用 `#15c784 / 42%` 填充。该过程没有更改 `106:123` 的 root、layout、preview 几何或任何结构样式。动态证据与回读结果记录在 `figma-pixel-artifacts/20260729-local-sector-overview-dynamic-1603/manifest.md`。本次不是模块级 overlay 签核，状态仍为 `GEOMETRY_PASS / IN_PROGRESS`，不得标记 `STYLE_PASS` 或 `PIXEL_VERIFIED`。

#### M5-3 已执行：状态样式基线 primary loaded 主态

`StateBaselinePanel()` 已按同一本地 frozen loaded 基线建立在 Figma `106:124`。它保持为正式市场总览可见的静态参照模块，不被误做成独立业务页面或运行时 fallback。root 使用原生纵向 Auto Layout，固定为 `1564 x 142px`；header/lab 严格为 `1538 x 21px`、`1538 x 85px`。为了忠实映射浏览器的 `1px border + 12px padding` 内容框，Figma root 使用 `13px` content inset，实际子内容宽度为 source 的 `1538px`。

四个状态块 `261:394..261:397` 均为可编辑的 `377 x 85px` 原生 Frame，以 `10px` gap 排列。loading 由可编辑标题和两根带 source 渐变色标的 Rectangle 组成；empty、error、data delayed 分别保留 source 的虚线色、文本色、单/双行排版与 `11px` 内部锚点。所有文字、边框、阴影和骨架条均是原生 Figma 节点，没有截图、image fill 或被隐藏的栅格化替身。

节点回读已确认每个块的 `x=0/387/774/1161px`、正文锚点与浏览器量测一致。Figma 可用字体中没有浏览器的系统字体，故使用 `Noto Sans SC`；只有 `loading` 的自然字宽由 source 的 `47.7734375px` 变为 `49px`，为防止错误换行已显式保留自然宽并登记为字体渲染差异。该差异不放宽容器或文本坐标要求；M6 状态说明已完成，但本模块仍等待 M7 正式叠图，状态只能是 `IN_PROGRESS`。

### M6：状态、交互和页面装配

1. 只在 `05 Market Overview - States and Interaction Notes` 表达 hover、tooltip、loading、empty、error、delayed、ticker marquee 暂停、新闻局部刷新、股票入口跳转。
2. primary loaded 页面不显示 `OverviewDebugPanel`。
3. 用 M2-M5 已验收的 component instances 重装 `04 Market Overview - Desktop Loaded`；不得 detach 后局部修改。
4. 在 Cover 记录 capture id、asset hash、data snapshot 边界和 Figma root node id。

**门禁：** loaded 页面与状态/交互页的内容不能混淆；交互说明不伪造不存在的产品页面或实时能力。

#### M6 已执行：状态与交互参考、主稿装配核验、Cover 登记

`05 Market Overview - States and Interaction Notes / 11:2` 已存在可编辑的原生状态与交互参考页。本轮只校正其文字事实，未创建伪产品页面：`11:27` 记录 ticker 为 `36s linear` 的右向左无缝滚动及 hover 暂停；`11:29` 记录新闻首次请求 `5s` 超时、每 `10` 分钟局部刷新及刷新失败保留旧内容；`11:31` 记录默认“涨跌分布”与图表切换；`11:33` 记录榜单、涨跌停领涨股、连板股票卡仅上报 `tsCode`，由页面统一导航至 `/wealth/market/stock/:tsCode`；`11:35` 记录真实的 `?` tooltip 规则。`11:43` 明确 `OverviewDebugPanel` 只会在 `DEV + debug=1` 出现，当前本地 loaded DOM 不渲染该节点。

primary loaded root `106:52` 已回读：它保留 shared `TopMarketBar` 实例并含 `44` 个 Figma component instance，未采用 detach 后的私有 Shell 重装。M6 只确认装配事实；不因此授予任一模块 `PIXEL_VERIFIED`。

Cover `00 Cover and Source Rules / 4:24` 的原生登记卡 `274:2` 仍保留历史 capture 的可追溯记录；当前活动事实应以本文第 2 节的 `20260728-local-loaded-1600-2x` 为准（`2026-07-29T00:32:03.207Z / 1600 x 1200 / DPR 1`，量测 SHA-256 `46556f523924106133cf433d402d3762452723aeaa9cf439ef3d3301545c33f8`，primary root `106:52`）。两个 capture 都未采集 API 数据时点、响应正文或网络 hash，因此只能作为已登录页面的 DOM/CSS/截图视觉事实，不能表述为数据快照审计。

### M7：视觉验收与交接

1. 输出 Figma 的 1x 全页和每模块 frame。
2. 与 M0 的浏览器对应截图叠图；在验收账本记录几何、文字、颜色、图表、动态边界和未通过项。
3. 对每项差异分类为：`source changed`、`font rendering`、`Figma construction defect`。只有第三类允许直接改稿；前两类先重新冻结或解决字体。
4. 全模块通过后，才把 Figma 从 `Draft` 标记为 `Pixel-verified`。

#### M7-1 已执行：连板天梯模块级叠图复核

`106:122` 是首个按当前 `20260728-local-loaded-1600-2x` 完成有效模块级叠图的长页节点。历史 `full-page.png` 裁出的 `modules/streak-ladder.png` 发现重复粘性 `TopMarketBar`，因此被明确作废；本轮只使用同一已登录页面两段 viewport 的无顶栏区域，按 DOM 模块边界拼接为 `1564 x 1446px` source。Figma 导出同样归一到 `1564 x 1446px`，并通过梯度位移测算确定其根节点视觉范围的顶部裁切为 `15px`。

#### M7-2 已执行：板块速览动态数据刷新

当前 local loaded DOM 的 `[aria-label="板块速览"]` 保持既有 `1564 x 501px` 几何；用户已确认以它为动态事实源。Figma `106:123` 因此只更新可见数据：8 张 Top5 卡片的 40 条排行与 5 x 4 热力图的 20 个格子全部逐条替换；上涨数值色为 `#ff4d5a`，下跌文本和值为 `#15c784`，当前 20 格都采用 `#15c784 / 42%` 填充。更新前后，root、header/body、左侧 `4 x 2` 矩阵、右侧 heatmap、Auto Layout、间距、Panel 外观和字体均未修改。

动态截图和 Figma 回读结果已归档至 `figma-pixel-artifacts/20260729-local-sector-overview-dynamic-1603/manifest.md`。其中整页截图只证明当前动态内容，不作为新的模块裁图或透明 overlay 源；故该模块从 `SOURCE_CHANGED` 收敛为 `IN_PROGRESS`，并继续保持 `GEOMETRY_PASS`，但不得标记 `STYLE_PASS` 或 `PIXEL_VERIFIED`。

叠图前发现唯一确定的内容差异：Figma summary 仍是 `2026-07-27 连板天梯`，已改为源页面的 `2026-07-28 连板天梯`。完成后，root 外框、七层顺序/层高、层间距、P1 双侧 6 张可见卡、首板 12 张可见卡、空态和展开按钮均与源图一致。当前仅完成几何和内容的模块级签核；因字体 rasterization 与效果像素差异尚未逐项归因或设定阈值，`106:122` 仍为 `IN_PROGRESS`，不能标记 `STYLE_PASS` 或 `PIXEL_VERIFIED`。

#### M7-3 已执行：五板以上透明渐变渲染修正

线上部署提交 `d30c7e1` 已只读核验：`above-five` body 的 CSS 仅为 `8%` 金色到深色的纵向渐变，header 仅为 `14%` 金色到深色的横向渐变。Figma 直接保存半透明渐变 stop 时，导出出现了不符合线上结果的高饱和金色大面积填充；这是 Figma 的构造差异，不是产品样式。为保持可编辑性且忠实于最终像素，Figma `296:390` 和 `296:391` 改为相对于 Panel `#101827` 的预合成不透明色：body `#22262C -> #0E1523`，header `#403D35 -> #131C2C`，边框和 header 分隔线也使用对应预合成色。该修正不改变层级尺寸、文本、卡片或任何产品代码；模块仍保持 `IN_PROGRESS`，等待字体与其余效果差异的完整 M7 归因。

#### M7-4 已执行：可信裁图链路与首屏第一批复核

本地 in-app browser 的 CSS viewport 已固定为 `1600 x 1200`。实测发现其普通 screenshot 输出为 `1600 x 1152`，`clip` 与 `fullPage` 两种截图均不能可靠表达页面纵向坐标；同时，`sips --cropOffset` 在当前环境没有按给定偏移生效。上述工具异常不是产品或 Figma 差异，早期依赖它们的局部图均作废，不得用于 M7 放行。

本轮改为以 DOM `border-box` 为唯一几何锚点：CUA 定位 `scrollY`、普通 viewport 截图、用 `/private/tmp/goldenshare_m7_crop.swift` 按 DOM x/y/width/height 无缩放裁切。有效源图、Figma 导出、hash、无效图清单和每项差异归因均归档在 `figma-pixel-artifacts/20260729-m7-module-verification/manifest.md`。

第一批 TopMarketBar、Breadcrumb、ShortcutBar、新闻速览、个股新闻、今日市场客观总结和主要指数已重新量测。七个 root 的 DOM/Figma 宽高一一一致，均只放行 `GEOMETRY_PASS`。唯一可证明的 Figma 构造缺陷是 shared `TopMarketBar` 的六个导航标签为 `700` 字重，而浏览器实际 computed style 为 `400`；已把源组件 `97:10/12/14/16/18/20` 改为 `Noto Sans SC Regular`。新闻/市场事实/指数 ticker 的内容变化均为 `SOURCE_CHANGED`；浏览器 `DIN Alternate` 与 Figma `Roboto Mono` 的数值渲染差异为已确认的 `FONT_RENDERING_GAP_OPEN`。这些项目不允许被误记为布局缺陷或通过替换实时数据掩盖。

#### M7-5 已执行：全模块几何与差异归因收口

本轮已将涨跌分布、市场风格、成交额总览、大盘资金流向、榜单速览、涨跌停统计与分布、连板天梯、板块速览和状态样式基线纳入同一取证规则。15 个模块的 root 均以 browser DOM `border-box` 与 Figma node metadata 回读，宽高无漂移。除 `M7-20260729-01` 的 TopMarketBar 导航字重外，没有新增的 `Figma construction defect`；市场数据、新闻、榜单和图表差异均按 `SOURCE_CHANGED` 隔离，数字字体差异保持 `FONT_RENDERING_GAP_OPEN`。

板块速览已在本轮前按用户确认的当前 local loaded 动态内容同步，故只进行来源与几何复核，不再以历史数据重写。状态样式基线的 root 为 `1564 x 142px`；in-app browser 在页面底部固定裁掉最后 `14px` 的可见 DOM 范围，因此本轮只核验其可见 `128px` 和完整 DOM/Figma 几何，不能用截断图赋予样式或像素通过。

M7 当前完成的是“可信证据、全模块几何、构造缺陷与动态差异归因”阶段，而不是页面级 `PIXEL_VERIFIED`。要进入最终叠图签核，必须先取得同一数据时点的可重复静态源图，例如受控的 versioned fixture/offline mode，或将浏览器与 Figma 的动态数据在同一时点重新冻结。此前不得以实时内容变化、字体 fallback 或不可靠截图工具代替差异图验收。

## 6. 验收标准

### 6.1 模块级放行条件

每个模块必须同时满足：

- [ ] 绑定同一 capture run 的截图、DOM root selector 和 data state。
- [ ] 外框、内部 grid/flex、gap、padding、border、radius、shadow 的 Figma 值与 computed style 完全相同。
- [ ] 所有可见文本的 font family、font size、weight、line-height、letter spacing 已核对；字体无未说明 fallback。
- [ ] 数值颜色、上下涨跌和 flat 语义符合线上 CSS。
- [ ] 图表具有独立 plot-area 账本，标签/轴/柱/线/tooltip 已量测。
- [ ] Figma 使用原生 editable nodes；无截图、无 image fill 伪装图表、无 detatched shared shell。
- [ ] 模块截图叠图已审查，剩余差异都有明确分类和处理结论。

### 6.2 页面级放行条件

- [ ] 首屏与全页的模块顺序、分栏比例、页面高度、scroll 内容密度均与 source capture 一致。
- [ ] 只有 logo 是位图资产。
- [ ] source manifest、验证账本、Figma page/component/node 映射完整。
- [ ] 没有以历史 V1.1/V1.8、默认 mock 或本地未部署 CSS 覆盖线上视觉。
- [ ] 所有 Figma 页面、组件和节点遵循命名规范，便于后续页面消费 shared Shell。

## 7. 风险与决策边界

1. Figma 与浏览器的字体 rasterization 可能产生边缘像素差异，但这不能用来放宽布局或样式取值。几何和 computed-style 数值必须一致；字体差异必须有字体探测证据。
2. Canvas/SVG 图表不能导入截图。若某个 canvas 子元素无法通过 DOM 拆解，使用截图的像素坐标作为施工尺度，仍以 Figma vector/text 原生绘制。
3. 如果线上页面在 M0-M7 期间发版，旧 capture run 立即冻结为历史证据；需要继续施工时必须重新采集，禁止混用。
4. 本计划没有引入新的用户功能、API 或前端状态；发现产品逻辑与页面视觉不符时，停止 Figma 施工，单独提出产品/工程问题，不擅自重设计。

## 8. 计划对账

| 已拍板项 | v2 落点 |
|---|---|
| 当前线上 CSS/DOM 是第一优先级 | 第 2 节 R1、第 3 节 capture run、第 5 节 M0。 |
| Figma 画布为 1600px | 第 3.1 节、M1 门禁。 |
| 页面数据必须冻结 | 第 3.1 节 capture manifest、M0。 |
| 顶栏必须跨页面复用 | 第 1.2 节、M2。 |
| 不使用页面截图充当设计稿 | 第 1.3 节、4.1 节、6.1 节。 |
| 先文档和审计，再继续改稿 | 本文、审计 v1、验收账本 v1；本计划当前状态为待评审。 |
