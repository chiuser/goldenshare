# M7 模块验收取证清单（2026-07-29）

## 1. 本轮边界

- 页面：本地已登录 `http://127.0.0.1:5173/wealth/`
- CSS 视口：`1600 x 1200`
- Figma primary loaded root：`106:52`
- Figma page：`04 Market Overview - Desktop Loaded / 103:2`
- 本清单只记录 M7 的浏览器/Figma 取证与差异归因；不代表业务数据快照，也不修改产品代码。

## 2. 可信来源与裁图方法

浏览器正常截图的输出栅格为 `1600 x 1152`，但 DOM 的 CSS 视口与坐标系为 `1600 x 1200`。除页面末端的状态样式基线外，模块均位于这 `1152px` 可见范围内，因此本轮按 DOM `border-box` 坐标对 viewport 截图裁切，裁图不缩放。状态样式基线的最后 `14px` 被浏览器输出固定裁切，完整几何改由 DOM/Figma metadata 共同核验，且不据此授予样式或像素通过。

由于本地 in-app browser 的 `clip` 与 `fullPage` 截图实测不可靠，本轮可信裁图固定采用：

1. 用浏览器 CUA 滚动到已记录的 `scrollY`。
2. 截取普通 viewport 图。
3. 用 `/private/tmp/goldenshare_m7_crop.swift` 按 DOM x/y/width/height 无缩放裁切。
4. 以裁图、对应 Figma node、DOM rect 三者共同验收。

`sips` 的 `cropOffset` 在本机未按预期作用，早期由它生成的 v1/v2/v3 局部图均为无效证据；它们保留以说明错误来源，但不得再用于 overlay、几何或样式结论。

## 3. 有效输入

| 类别 | 文件/节点 | 尺寸或锚点 | SHA-256 / 备注 |
|---|---|---|---|
| 浏览器 viewport | `analysis/first-screen-viewport-scroll0.png` | `scrollY=0`，CSS `1600 x 1200`，输出 `1600 x 1152` | `5f173d57d15b2317ea16d12901a6bfaecbe2772ad147f40aaecdd24b8e056cbf` |
| 浏览器 viewport | `analysis/summary-major-viewport-scroll426.png` | `scrollY=426` | `c3c701cff931a343b9e157410eba7cd2595c8137d0579a4b0acfbc30d22b744f` |
| TopMarketBar source | `source/top-market-bar-current-v6.png` | `(0,0,1600,56)` | `7293e790fe316bcb8c111b11697c896ff83df7f585986bfc5ea722811160c847` |
| Breadcrumb source | `source/breadcrumb-current-v3.png` | `(18,70,1564,28)` | 有效首屏 viewport 裁切 |
| Shortcut source | `source/shortcut-current-v3.png` | `(18,110,1564,80)` | 有效首屏 viewport 裁切 |
| News source | `source/market-news-current-v3.png` | `(18,202,776,268)` | 有效首屏 viewport 裁切 |
| Stock news source | `source/stock-news-current-v3.png` | `(806,202,776,268)` | 有效首屏 viewport 裁切 |
| Summary source | `source/market-summary-current-v4.png` | `(18,56,776,252)` at `scrollY=426` | `99cd3410e577545999b1d85fe6a45a5eea42bf4584365c25e18edcef244a12a0` |
| Major indices source | `source/major-indices-current-v3.png` | `(806,56,776,252)` at `scrollY=426` | `17ab3245ef2dabef637633838d0e0a61508a2e718353bac59759af70251755fe` |
| Figma TopMarketBar | `106:53` | `1600 x 56` | export `figma/top-market-bar-106-53-v2.png`，`5e63d8527592b4b645fc4dd06129bf78b5acbf5701fc5cbb00c16d43cbb31991` |
| Figma Summary | `106:112` | root `776 x 252` | export `figma/market-summary-106-112.png`，`2fed5a08bec1496b3cc81331b9f75a3de63659b0d6feb871537b9ff67a291581` |
| Figma Major indices | `106:113` | root `776 x 252` | export `figma/major-indices-106-113.png`，`630f09d71a5b904e4f6ca0b8337915af1bbee3caa708d22c30784298fcd72703` |
| 浏览器 viewport | `analysis/grid-viewport-scroll426.png` | `scrollY=426` | 涨跌分布、市场风格、成交额总览的同一 viewport 来源图 |
| Breadth source | `source/breadth-current-v1.png` | `(18,320.391,513.328,374)` at `scrollY=426` | 有效 grid viewport 裁切 |
| Market style source | `source/market-style-current-v1.png` | `(543.328,320.391,513.336,374)` at `scrollY=426` | 有效 grid viewport 裁切 |
| Turnover source | `source/turnover-current-v1.png` | `(1068.664,320.391,513.328,374)` at `scrollY=426` | 有效 grid viewport 裁切 |
| Figma Breadth | `106:115` | root `513.328125 x 374` | export `figma/breadth-106-115.png` |
| Figma Market style | `106:116` | root `513.3359375 x 374` | export `figma/market-style-106-116.png` |
| Figma Turnover | `106:117` | root `513.328125 x 374` | export `figma/turnover-106-117.png` |
| 浏览器 viewport | `analysis/money-leaderboard-viewport-scroll1076.png` | `scrollY=1076` | 大盘资金流向与榜单速览的同一 viewport 来源图 |
| Money flow source | `source/money-flow-current-v1.png` | `(18,56.391,776,473.219)` at `scrollY=1076` | `988542d98468a1b055897bf2a2216a0808927d3a073c96ec268910b3c8db826c` |
| Leaderboard source | `source/leaderboard-current-v1.png` | `(806,56.391,776,473.219)` at `scrollY=1076` | `63d5078af442ae801976df55418ff4e62c8f64f24b8c421ea885060e0a41ebb4` |
| Figma Money flow | `106:119` | root `776 x 473.21875` | export `figma/money-flow-106-119.png`，`c35c65ad97b976543fe465e81f081deb12dcc7e44c7ed55754d2a71bf3b7655e` |
| Figma Leaderboard | `106:120` | root `776 x 473.21875` | export `figma/leaderboard-106-120.png`，`a48041549cc492a9b145d11cf96fb0f3e10f0b86df63a2409a83e12dea0aa0fe` |
| 浏览器 viewport | `analysis/limit-board-viewport-scroll1561.png` | `scrollY=1561` | 涨跌停统计与分布的同一 viewport 来源图 |
| Limit board source | `source/limit-board-current-v1.png` | `(18,56.609,1564,566.5)` at `scrollY=1561` | `3dbae447948c8b34ef3a0e4a4ccefda756170264c2046c49e6ff2adf925bd66c` |
| Figma Limit board | `106:121` | root `1564 x 566.5` | export `figma/limit-board-106-121.png`，`fd5f1149ba446e63071ea4f640c7ce337765f710ff9995204caf1e2623792054` |
| 浏览器 viewport | `analysis/sector-viewport-scroll3171.png` | `scrollY=3142.5` | 板块速览与状态样式基线的同一 viewport 来源图 |
| Sector overview source | `source/sector-overview-current-v1.png` | `(18,511.109,1564,501)` at `scrollY=3142.5` | `cd1db7f9a88842df30ce90501b36e679eff74ffe68a77c63059e8886b724a16e` |
| Figma Sector overview | `106:123` | root `1564 x 501` | export `figma/sector-overview-106-123.png`，`c29e322617201fe5111b39153ea8aff65ae56cb2a6807edbf94d4f255d76cf30` |
| Browser viewport | `analysis/state-baseline-viewport-current.png` | `scrollY=3142.5`，底部固定缺失 `14px` | in-app browser 的普通截图输出为 CSS viewport 高度减 `48px`；页面末端无法再向下滚动 |
| State baseline source | `source/state-baseline-current-v1.png` | `(18,1024.109,1564,128)` at `scrollY=3142.5` | 可见 `128px`；SHA-256 `6de4d10512a7fbe8e078d924a326fdea2d7de7ae9765b372e71956b70b973c8b` |
| Figma State baseline | `106:124` | root `1564 x 142` | export `figma/state-baseline-106-124.png`，视觉 effect 输出 `1564 x 158`；SHA-256 `c19520d5c72a606f46c7760206e1b52e25907777992bb2a4ea61d4b0aab84685` |

Figma module export 可能包含阴影等视觉 effect 边界，因此 PNG 的输出宽高不能代替 node 几何；几何只以 Figma node metadata 与 browser DOM rect 对照。

## 4. 第一批量测与结论

| 模块 | DOM rect | Figma node | Figma 几何 | 结论 |
|---|---|---|---|---|
| TopMarketBar | `(0,0,1600,56)` | `106:53` | `1600 x 56` | `GEOMETRY_PASS` |
| Breadcrumb | `(18,70,1564,28)` | `106:105` | `1564 x 28` | `GEOMETRY_PASS` |
| ShortcutBar | `(18,110,1564,80.391)` | `106:106` | `1564 x 80.391` | `GEOMETRY_PASS` |
| 新闻速览 | `(18,202.391,776,268)` | `106:109` | `776 x 268` | `GEOMETRY_PASS` |
| 个股新闻 | `(806,202.391,776,268)` | `106:110` | `776 x 268` | `GEOMETRY_PASS` |
| 今日市场客观总结 | `(18,482.391,776,252)` | `106:112` | `776 x 252` | `GEOMETRY_PASS` |
| 主要指数 | `(806,482.391,776,252)` | `106:113` | `776 x 252` | `GEOMETRY_PASS` |
| 涨跌分布 | `(18,320.391,513.328,374)` at `scrollY=426` | `106:115` | `513.328125 x 374` | `GEOMETRY_PASS` |
| 市场风格 | `(543.328,320.391,513.336,374)` at `scrollY=426` | `106:116` | `513.3359375 x 374` | `GEOMETRY_PASS` |
| 成交额总览 | `(1068.664,320.391,513.328,374)` at `scrollY=426` | `106:117` | `513.328125 x 374` | `GEOMETRY_PASS` |
| 大盘资金流向 | `(18,56.391,776,473.219)` at `scrollY=1076` | `106:119` | `776 x 473.21875` | `GEOMETRY_PASS` |
| 榜单速览 | `(806,56.391,776,473.219)` at `scrollY=1076` | `106:120` | `776 x 473.21875` | `GEOMETRY_PASS` |
| 涨跌停统计与分布 | `(18,56.609,1564,566.5)` at `scrollY=1561` | `106:121` | `1564 x 566.5` | `GEOMETRY_PASS` |
| 板块速览 | `(18,511.109,1564,501)` at `scrollY=3142.5` | `106:123` | `1564 x 501` | `GEOMETRY_PASS` |
| 状态样式基线 | `(18,1024.109,1564,142)` at `scrollY=3142.5` | `106:124` | `1564 x 142` | `GEOMETRY_PASS` |

## 5. 差异归因

| ID | 分类 | 模块 | 现象 | 结论 / 动作 |
|---|---|---|---|---|
| M7-20260729-01 | `FIGMA_CONSTRUCTION_DEFECT` | TopMarketBar | 六个主导航在 Figma 是 `700`，当前页面计算值为 `400`。 | 已将 shared component `97:10/12/14/16/18/20` 调整为 Noto Sans SC Regular；实例 `106:53` 随组件更新。 |
| M7-20260729-02 | `SOURCE_CHANGED` | TopMarketBar | 当前 ticker 已为 2026-07-29 的指数、涨跌值；Figma 仍为前一冻结时点。 | 不按实时值改动 Figma；动态内容不参与静态结构结论。 |
| M7-20260729-03 | `SOURCE_CHANGED` | 新闻、Summary、Major indices | 新闻内容、时间、指数、市场总结五卡及事实文案均来自当前实时数据，与 Figma 冻结时点不同。 | 不把数据变化记为布局或颜色缺陷；待下一次统一动态数据冻结时再集中刷新。 |
| M7-20260729-04 | `FONT_RENDERING_GAP_OPEN` | 数字/行情展示 | 浏览器实际数值字体为 `DIN Alternate`；Figma 无同字体。 | 按已确认口径使用 `Roboto Mono`，不以该差异放宽 x/y、字号、字重或容器尺寸。 |
| M7-20260729-05 | `CAPTURE_TOOL_DEFECT` | 取证链路 | `clip/fullPage` 与 `sips cropOffset` 均产生错误局部图。 | 不计入 Figma/产品差异；保留无效文件，后续一律使用本清单第 2 节裁图流程。 |
| M7-20260729-06 | `SOURCE_CHANGED` | 涨跌分布、市场风格、成交额总览 | 当前本地 source 的指标卡、分桶计数和趋势线点位与 Figma 冻结时点不同；三个模块的根几何、三卡/四卡网格、切换控件与图表槽位均与 Figma node metadata 对齐。 | 不以实时业务值替换 Figma；不把柱高或折线路径差异归因为构造缺陷。 |
| M7-20260729-07 | `SOURCE_CHANGED` | 大盘资金流向、榜单速览 | 当前本地 source 的净流入、饼图占比、趋势序列、榜单股票和行情值与 Figma 冻结时点不同；两模块的根、卡片网格、左右列比、七个 tab、八列 table 与 Figma node metadata 对齐。 | 不更新 Figma 动态业务内容；不把饼图扇区、折线路径或榜单行内容差异归为构造缺陷。 |
| M7-20260729-08 | `SOURCE_CHANGED` | 涨跌停统计与分布 | 当前本地 source 的今日/昨日日期、八项统计、板块条、领涨股及组合柱数据与 Figma 冻结时点不同；根、双行双列布局、八张统计卡和两个 `763px` 图表/结构槽位与 Figma node metadata 对齐。 | 不以实时统计替换 Figma；不把柱高、条宽或领涨股文本差异归为构造缺陷。 |

板块速览在本轮开始前已按用户确认的当前 local loaded 动态内容逐项更新 Figma；本轮有效 source 与 `106:123` 的可见排行、数值、涨跌色和热力格状态一致。因此它没有新增差异记录。状态样式基线是静态参考模块，当前可见的 `128px` 源图与 Figma 的标题、四块顺序、虚线框、骨架条和文本结构一致；受浏览器页面末端截图裁切限制，仍不赋予 `STYLE_PASS` 或 `PIXEL_VERIFIED`。

## 6. 当前放行状态

本轮 15 个模块均已完成可信源图或已归档同一会话源图、DOM/Figma root 几何回读和动态差异归因；除 shared TopMarketBar 导航字重外，没有发现可证明的 Figma 构造缺陷。尚未逐项完成字体、边框、圆角、阴影、文本基线和图表的同尺寸差异图验收，任何模块均不得标记为 `STYLE_PASS` 或 `PIXEL_VERIFIED`。

下一阶段要取得页面级像素放行，必须先提供可重复的同数据时点静态 source：例如为市场总览增加仅用于验收的 versioned fixture/offline mode，或在同一数据时点冻结浏览器与 Figma 的模块源图。该前提未满足前，本清单只能证明结构、构造缺陷和动态差异的归因，不能证明全页像素一致。
