# 市场总览 Figma 像素级验收账本 v1

**用途：** 本文是 [像素级还原执行计划 v2](./market-overview-figma-pixel-reconstruction-plan-v2.md) 的唯一模块验收记录。它不替代 Figma，不替代截图，也不写产品需求；它只证明“当前 Figma 的哪个节点，依据哪一份线上证据，已经通过了哪些核对”。

**状态：当前本地 `20260728-local-loaded-1600-2x` 已捕获并取代历史 `1x` 施工基线；旧远端 M0 与基于它的 M1 skeleton 已删除并标记为 `SOURCE_CHANGED`。当前 primary root、shared TopMarketBar、Shell、模块外框和 Panel 外观已通过量测回读；连板天梯的当前 7 段结构已按活动 capture 重建，并完成一次有效的模块级 M7 源图/Figma 导出叠图。任何模块仍未取得 `PIXEL_VERIFIED`。**

## 1. Capture Run 信息

### 当前本地 loaded visual capture（本轮唯一施工基线）

| 字段 | 值 | 结论 |
|---|---|---|
| Capture ID | `20260728-local-loaded-1600-2x` | 本轮唯一允许用于 Figma M1-M7 施工的视觉基线；`2x` 是第二次 capture 编号，不是 DPR。 |
| 浏览器地址 / DOM 状态 | `http://127.0.0.1:5173/wealth/`；`main.page-shell` 存在、登录表单、DEV 调试面板和 error marker 均不存在 | 实际量测的是本地市场总览 loaded DOM。 |
| 捕获时间 | `2026-07-29T00:32:03.207Z` | 同一次本地连续 capture。 |
| viewport / DPR | `1600 x 1200 CSS px` / `1` | 符合本轮固定量测条件。 |
| 页面状态 | 16 个模块根均存在，无 error marker | `CAPTURED`；尚未表示 Figma 像素验收通过。 |
| 文档 / PNG 尺寸 | DOM `1600 x 4343 CSS px` / 全页 PNG `1600 x 4342 px` | Chromium 位图取整不用于布局判断；Figma 施工根使用 DOM border-box `4342.609375px`。 |
| 样式来源 | 6 个本地 Vite 运行时 style sheet | 不存在可冻结的单一 CSS asset hash。 |
| DOM geometry / computed style | `measurement.json`，SHA-256 `46556f523924106133cf433d402d3762452723aeaa9cf439ef3d3301545c33f8` | 已记录 root custom properties、模块 rect 与模块 computed style。 |
| 全页与模块截图 | `full-page.png` + `modules/*.png`（16 张），全页 SHA-256 `4d552b5dfed947efa6476f9a291adf04158390403a691569be5994c69c47544f` | 均由同一 `1600 x 1200 / DPR 1` local capture 生成。 |
| 网络/API hash | 未采集 | 本轮只冻结视觉 DOM/CSS/截图；不得把它表述为 API 数据快照审计。 |
| Figma 放行 | `M0_VISUAL_CAPTURED` | 可按当前视觉事实进入 M1，M1 需从零重建，旧 skeleton 不得复用。 |

### 产物版本化边界

版本库只保留当前施工与验收需要复查的三组证据：活动本地 capture `20260728-local-loaded-1600-2x`、M7 模块验收 `20260729-m7-module-verification`、板块速览动态内容刷新 `20260729-local-sector-overview-dynamic-1603`。更早的登录页、远端 1x、重放失败和中间截图均为本地调试产物，不纳入版本库；其结论在本文保留，但不再提供仓库内文件路径。

### 旧 Figma M1 skeleton 处理

`01 Foundations / 62:2` 基于旧远端 `4168/4169px` capture；当前本地活动施工根已为 `4342.609375px`，且中下段模块位置已经变化。因此该 skeleton 的所有几何结论均为 `SOURCE_CHANGED`；后续应删除或归档它，不允许在原节点上继续微调。

### 当前本地 M1 Layout Skeleton（壳层已通过，内部未施工）

| 字段 | 值 | 结论 |
|---|---|---|
| Figma page | `04 Market Overview - Desktop Loaded / 103:2` | 新 primary loaded 页面，独立于旧 `62:2`。 |
| M1 root | `Market Overview / Desktop / Loaded / Local1600 / M7 current source / 106:52` | `1600 x 4342.609375`；背景 `#070b12`。 |
| Shared Shell | `TopMarketBar / Shared / Loaded / Local1600 / M1 / 97:2`；instance `106:53` | instance 为 `1600 x 56`，保持可复用，未 detach。 |
| Page shell | `106:104` | `1600 x 4286.609375`；padding `14 / 18 / 34 / 18`，vertical gap `12`。 |
| Content grid | `106:107` | `1564 x 4106.21875`；七个真实行 gap 均为 `12`。 |
| 模块外框 | `106:106`、`106:109` 至 `106:124` | 14 个 panel shell 已回读：本地 CSS `#101827`、`rgba(148,163,184,.16)`、`12px` radius、`0 8px 24px rgba(0,0,0,.26)`。 |
| 几何回读 | root、topbar、shell、breadcrumb、shortcut、8 个 content-grid 行 | 所有 root-relative x/y/width/height 与 `measurement.json` 的本地基线 `delta = 0`。 |
| M1 放行 | `GEOMETRY_PASS` | 可按既定 M2 顺序施工第一屏内部模块；不是任何模块的 `PIXEL_VERIFIED`。 |

| 字段 | 值 | 填写规则 |
|---|---|---|
| Capture ID | `20260726-191213-35daab6e-4db59061` | BLOCKED run；不是验收基线。 |
| 线上 URL | `https://wealthworld.com.cn/wealth/market/overview` | 只能使用线上 loaded 页面。 |
| 捕获时间 | `2026-07-26T11:21:03.595Z` | 隔离无头会话。 |
| 浏览器/版本 | `Google Chrome 150.0.7871.184` | 必须含 Chromium/Chrome 版本。 |
| viewport | `1600 x 1200 CSS px` | 不得改动。 |
| DPR / zoom | `1 / 100%` | 不得改动。 |
| 页面状态 | `BLOCKED`；重定向至 `/wealth/login?redirect=%2Fwealth%2Fmarket%2Foverview`，16 个目标模块均缺失。 | 此 run 不满足 loaded 门禁。 |
| tradeDate / 数据时点 | `不适用` | 登录页未请求市场数据。 |
| HTML SHA-256 | `0d0886806bf10e6b2b9dd13d691f1086a5f61c650f38527c3488e61508155ce7` | 登录页 HTML，不可作为 source baseline。 |
| CSS URL / SHA-256 | `index-C3nS_K6q.css / 4db5906178622f6a1852f39f253a36965586e7da99fbc53b27d27825160be875` | 仅记录资源，不作为 loaded 页面样式验收依据。 |
| JS URL | `index-BxzDHKj_.js / 95d21ea17d8db0d58533e4224e6c9b5bf780eb82390390ac3852a5d42803cc69` | 仅记录资源。 |
| 网络响应索引 | 未版本化的本地 BLOCKED capture 摘要 | 登录页未发生市场模块 API 请求。 |
| 全页截图 | 未版本化的本地 BLOCKED capture 截图 | 登录页证据，不能用于 Figma 还原。 |
| Figma file / root node | `RADlZzREU4lPVviYfkLy6x / 18:117` | 当前 primary loaded root；尚未修改。 |

### 已登录 loaded capture（进行中，非验收基线）

| 字段 | 值 | 结论 |
|---|---|---|
| Capture ID | `20260726-124421-c24dde9c` | 与上方 BLOCKED run 分离，不能覆盖旧记录。 |
| 最终 URL | `https://wealthworld.com.cn/wealth/market/overview` | 已停留在市场总览，未重定向到登录页。 |
| 浏览器条件 | Chrome，`1600 x 1200` CSS px，1x full-page PNG | 满足截图输出尺度。 |
| 页面状态 | 所有目标模块均在全页截图中可见，未见登录页或模块 fallback。 | 视觉 loaded 已确认。 |
| 文档尺寸 | `1600 x 4168` px | 与 `full-page.png` 实测一致。 |
| HTML / CSS / JS SHA-256 | `35daab6e...c6dda2b8` / `4db59061...160be875` / `95d21ea1...42803cc69` | 静态资源版本已冻结。 |
| DOM geometry / computed style | 浏览器桥接在大范围 DOM 读取时超时；本 run 已明确标记为待补。 | 未取得逐锚点量测前不得开始 Figma 施工。 |
| 全页截图 | 未版本化的本地历史截图 | 仅证明当时已登录 loaded，不是当前 DOM 完整量测或验收依据。 |

本次 capture 只证明“认证阻塞已解除、页面真实 loaded、静态资源版本一致”。它不证明任何模块已通过 `GEOMETRY_PASS`、`STYLE_PASS` 或 `PIXEL_VERIFIED`。

### 已登录 1x layout/style capture（历史 partial，不用于本轮 Figma 验收）

| 字段 | 值 | 结论 |
|---|---|---|
| Capture ID | `20260727-figma-m0-loaded-1600-1x` | 历史远端 loaded 1x layout/style 基线；已被本轮本地 capture 取代。 |
| 最终 URL / 页面状态 | `https://wealthworld.com.cn/wealth/market/overview` / `complete` | 未重定向到登录页。 |
| viewport / DPR | `1600 x 1200 CSS px` / `1` | 与 Figma 施工基线一致。 |
| 文档 / PNG 尺寸 | `1600 x 4168 CSS px` / `1600 x 4168 px` | 全页几何与 1x 输出一致。 |
| 数据时点 | `tradeDate=2026-07-24` | 从 13 条已加载市场 API resource URL 记录。 |
| DOM geometry / computed style | 300 anchors / 11 模块根 / 49 root custom properties | 量测文件已落 `dom-geometry.json` 与 `computed-styles.json`。 |
| 静态资源 | CSS `4db59061...160be875`；JS `95d21ea1...42803cc69` | 内容 hash 已冻结。 |
| HTML 响应 | `35daab6e...c6dda2b8` | 公开 SPA 文档响应 hash 已冻结。 |
| 全页与模块截图 | `full-page.png` + `modules/*.png`（11 张） | 均由同一 1x full-page capture 生成。 |
| 认证 API body hash | 未取得 | CDP 在初始加载后才附着；禁止读取 token/local storage 重放。 |
| Figma 放行 | `BLOCKED` | 已由下方 network capture 解决。 |

### 已登录 1x network capture（历史远端验收基线）

| 字段 | 值 | 结论 |
|---|---|---|
| Capture ID | `20260727-figma-m0-network-loaded-1600-1x` | 历史远端验收基线；本轮不得继续用于 Figma 施工或验收。 |
| 最终 URL / 页面状态 | `https://wealthworld.com.cn/wealth/market/overview` / `complete` | 未重定向到登录页。 |
| viewport / DPR | `1600 x 1200 CSS px` / `1` | 与 Figma 施工基线一致。 |
| 文档 / PNG 尺寸 | `1600 x 4168 CSS px` / `1600 x 4168 px` | 全页几何与 1x 输出一致。 |
| 数据时点 | `tradeDate=2026-07-24` | 来自同次 13 个市场 API 请求。 |
| DOM geometry / computed style | 300 anchors / 11 模块根 / 49 root custom properties | 量测文件已归档。 |
| 静态资源 | CSS `4db59061...160be875`；JS `95d21ea1...42803cc69` | 内容 hash 已冻结。 |
| 认证 API 响应 | 13 / 13 为 `200`，无缺失、无无效；仅记录字节数与 body SHA-256 | Network 在受控刷新前启用，未保存正文或认证信息。 |
| 全页与模块截图 | `full-page.png` + `modules/*.png`（11 张） | 均由同一 1x capture 生成。 |
| Figma 放行 | `SOURCE_CHANGED` | 保留历史审计证据；不得用于本轮 M1-M7。 |

### M0 历史阻塞与当前失效规则

原认证阻塞已解除：当前独立调试 Chrome 已通过用户手动登录进入市场总览。受控刷新中 Network 在页面加载前启用，13 个市场接口的 `200` 响应已完成 hash。整个过程未读取、复制或修改 local storage、Cookie、authorization header 或 token；裸 `fetch` 的 `401` 历史采样不作为任何基线。

若线上 CSS/JS 内容 hash、页面结构或市场 API 契约发生变化，当前 M0 立即标记为 `SOURCE_CHANGED`。恢复的唯一合规路径是：在当前已登录、开启远程调试端口的 Chrome 会话中，先由 CDP 启用 Network 监听，再经用户明确同意执行一次受控页面加载；只记录每个市场 API 的 URL、状态码、字节数和 body SHA-256，不落响应正文、不读取认证信息。必须新建 capture ID，不能覆盖当前基线。

### M1 Layout skeleton（历史施工记录，禁止复用）

| 字段 | 值 | 结论 |
|---|---|---|
| Figma page | `01 Foundations / 4:2` | 当前只在 Foundations 页施工，尚未创建 primary loaded 页面。 |
| M1 root | `Market Overview / Desktop / M1 Layout Skeleton / M0 20260727 / 62:2` | `1600 x 4169`，根背景绑定 `Background/Page`。 |
| Shared Shell | `62:3` TopMarketBar instance；`62:9` PageShell | `62:3 = 1600 x 56`；`62:9 = 1600 x 4113`；Shell padding 为 `14 / 18 / 34 / 18`，gap 为 `12`，均绑定 M0 Layout variables。 |
| 上方结构 | `63:7` BreadcrumbRow；`63:8` ShortcutBar | 相对 root 分别为 `(18,70,1564,28)` 与 `(18,110,1564,80)`；快捷入口为 6 个等分 Auto Layout 子格，gap `10`。 |
| Content grid | `64:7` | 相对 root `(18,202,1564,3933)`；子行和列均为 Auto Layout，不以页面内绝对坐标搭建。 |
| 首三行 | `64:8` SummaryIndex；`64:14` ThreeUp；`64:18` TwoUp | 相对 root 分别为 `(18,202,1564,532)`、`(18,746,1564,374)`、`(18,1132,1564,473)`；几何回读 delta 均为 `0`。 |
| 长页槽位 | `65:7` LimitBoard；`65:8` StreakLadder；`65:9` SectorOverview；`65:10` StateBaseline | 相对 root 分别为 `(18,1617,1564,567)`、`(18,2196,1564,1272)`、`(18,3480,1564,501)`、`(18,3993,1564,142)`；几何回读 delta 均为 `0`。 |
| Panel 外壳 | 所有 M1 Panel 槽位 | 绑定 `Component/Panel/ResolvedBackground`、`Border/Subtle`、`Radius/Panel`，并复制既有 `Panel / Default / M0` shadow；没有设置任何模块内部文字、图表或表格。 |
| 数值字体 | M0 `Font/Number/ResolvedChrome` 与 Figma fallback | Chrome resolved font 为 `DIN Alternate`；Figma 无此字体，按已确认口径使用 `Roboto Mono`。这是 `FONT_RENDERING_GAP_OPEN`，不构成任何模块 `STYLE_PASS`。 |
| 1px 网格差异 | `content-grid` 外框 | 浏览器外框记录为 `3932px`，但冻结子行高度加六个 CSS `12px` gap 为 `3933px`；Figma 保留后者以忠实表达真实子布局。该差异必须在 M7 叠图重新检查，当前不能标记 `PIXEL_VERIFIED`。 |
| M1 放行 | `SOURCE_CHANGED` | 旧 root 已失效；本轮已依据本地活动 `4342.609375px` capture 从零建立新的 M1 root。 |

## 2. 验收状态定义

| 状态 | 含义 |
|---|---|
| `NOT_STARTED` | 未建立证据、未开始 Figma 施工。 |
| `IN_PROGRESS` | 正在按对应 capture run 构建，不能作为后续模块事实。 |
| `BLOCKED` | 字体、线上状态、资源 hash 或来源冲突未解决。 |
| `GEOMETRY_PASS` | 外框、内部布局和尺寸已量测通过，但视觉仍未完成。 |
| `STYLE_PASS` | 字体、颜色、border、radius、shadow 通过；等待叠图。 |
| `PIXEL_VERIFIED` | 模块截图叠图、所有字段、Figma 可编辑性均通过。 |
| `SOURCE_CHANGED` | 线上 hash 已变，原验收不再可作为当前基线。 |

`PIXEL_VERIFIED` 是唯一允许标记为完成的状态。

## 3. 模块级验收表

除第 13 行“连板天梯”的当前活动 capture 重建记录外，本表内仍引用 `20260728-local-loaded-1600-1x` 的模块截图或静态文本，均只解释历史施工来源，不得作为当前几何、内容、颜色或 M7 放行证据。继续微调对应模块前，必须先从 `20260728-local-loaded-1600-2x` 重新量测并替换该行证据；在此之前，它们一律保持 `IN_PROGRESS`。

| 顺序 | 模块 | DOM root selector/锚点 | 主要 CSS 来源 | Figma component/root node | 证据截图 | 几何 | 样式 | 图表/密度 | 可编辑性 | 叠图 | 状态 | 差异/处理结论 |
|---:|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | TopMarketBar | `header.top-market-bar` | `wealth/src/shared/ui/top-market-bar/top-market-bar.css` | `TopMarketBar / Shared / Loaded / Local1600 / M1 / 97:2`；instance `106:53` | `20260729-m7-module-verification/source/top-market-bar-current-v6.png`；`figma/top-market-bar-106-53-v2.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `不适用` | 原生 Auto Layout + editable text/image layers | 第一批可信裁图已完成；逐像素差异图待完成 | `IN_PROGRESS` | DOM/Figma root 都是 `1600 x 56`。M7 发现 Figma 导航字重误为 `700`，已把 `97:10/12/14/16/18/20` 改为 Regular，对齐浏览器 `400`。ticker 内容为 `SOURCE_CHANGED`；数值 `DIN Alternate -> Roboto Mono` 是已确认 `FONT_RENDERING_GAP_OPEN`。 |
| 2 | Breadcrumb + ShortcutBar | `[aria-label="Breadcrumb"]`；`[aria-label="ShortcutBar / 页面内快捷入口"]` | `market-overview-page.css` 的 `.breadcrumb-row/.shortcut-*` | `106:105`；`106:106`；`118:2/118:8/120:2` | `20260729-m7-module-verification/source/breadcrumb-current-v3.png`；`shortcut-current-v3.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `不适用` | 原生 Auto Layout + editable text | 第一批可信裁图已完成；逐像素差异图待完成 | `IN_PROGRESS` | DOM/Figma 为 `1564 x 28`、`1564 x 80.391px`。时间/状态与 Figma 冻结内容不同，归类 `SOURCE_CHANGED`；不得以动态内容差异判为布局缺陷。 |
| 3 | 新闻速览 | `[aria-label="新闻速览"]` | `market-overview-page.css` 的 `.market-news-*` | `106:109` | `20260729-m7-module-verification/source/market-news-current-v3.png`；`figma/market-news-106-109.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `28px` header；`220px` viewport；单行 row 密度 | 原生纵向/横向 Auto Layout + editable text | 第一批可信裁图已完成；逐像素差异图待完成 | `IN_PROGRESS` | DOM/Figma root 都是 `776 x 268`。新闻列表与时间实时变化，归类 `SOURCE_CHANGED`。 |
| 4 | 个股新闻 | `[aria-label="个股新闻"]` | `market-overview-page.css` 的 `.market-news-*` | `106:110` | `20260729-m7-module-verification/source/stock-news-current-v3.png`；`figma/stock-news-106-110.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `28px` header；`220px` viewport；单行 row 密度 | 原生纵向/横向 Auto Layout + editable text | 第一批可信裁图已完成；逐像素差异图待完成 | `IN_PROGRESS` | DOM/Figma root 都是 `776 x 268`。新闻列表与时间实时变化，归类 `SOURCE_CHANGED`。 |
| 5 | 今日市场客观总结 | `[aria-label="今日市场客观总结"]` | `.summary-* / .fact-*` | `106:112`；`SummaryFactCard / 132:2` | `20260729-m7-module-verification/source/market-summary-current-v4.png`；`figma/market-summary-106-112.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `28px` header、5 卡 `76px`、`66px` 事实文案区 | 原生 Auto Layout + component instances + editable text | 第一批可信裁图已完成；逐像素差异图待完成 | `IN_PROGRESS` | DOM/Figma root 都是 `776 x 252`。结构卡片/边距一致；五卡数值、状态与文案因数据时点不同归类 `SOURCE_CHANGED`。 |
| 6 | 主要指数 | `[aria-label="主要指数"]` | `.index-*` | `106:113`；`IndexCard / 132:6`、`132:11` | `20260729-m7-module-verification/source/major-indices-current-v3.png`；`figma/major-indices-106-113.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `2 x 5`、card `78px`、两行 gap `8px` | 原生 Auto Layout + component instances + editable text | 第一批可信裁图已完成；逐像素差异图待完成 | `IN_PROGRESS` | DOM/Figma root 都是 `776 x 252`。指数值和涨跌语义为 `SOURCE_CHANGED`；ticker transform 不参与静态几何。 |
| 7 | 涨跌分布 | `[aria-label="涨跌分布"]` | `MarketBreadthPanel.tsx`；`.panel/.section-header/.mini-metrics/.range-switch/.breadth-distribution-*` | root `106:115`；header `149:246`；RangeSwitch `149:251`；DistributionChart `149:270` | `figma-pixel-artifacts/20260729-m7-module-verification/source/breadth-current-v1.png`；`figma/breadth-106-115.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `11` 桶、三张 `82px` metric card、默认 distribution；counts 交互态已由 M6 说明 | 原生 Auto Layout + component instances + editable text/rectangles | 当前 source 与 Figma exports 已复核；正式同数据时点叠图待做 | `IN_PROGRESS` | root `513.328125 x 374`，`12px` padding；header `30px`，metrics `82px`/`8px` gap，chart `489.328125 x 210`。当前分桶计数、metric 值和柱高来自 2026-07-29 source，与 Figma 冻结内容不同，已登记为 `SOURCE_CHANGED`，不标 `STYLE_PASS`。 |
| 8 | 市场风格 | `[aria-label="市场风格"]` | `MarketStylePanel.tsx`；`.panel/.section-header/.mini-metrics/.range-switch/.chart-box` | root `106:116`；header `153:268`；RangeSwitch `153:273`；MarketStyleTrendChart `153:292` | `figma-pixel-artifacts/20260729-m7-module-verification/source/market-style-current-v1.png`；`figma/market-style-106-116.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `3` 张 `82px` metric card；`178px` 三线 chart；默认 `1个月` | 原生 Auto Layout + editable text/vector/rectangles | 当前 source 与 Figma exports 已复核；正式同数据时点叠图待做 | `IN_PROGRESS` | root `513.3359375 x 374`，`12px` padding；plot `425.3359375 x 126`，轴 padding `48/16/16/36px`。三条线、卡片涨跌值与 Figma 冻结时点不同，登记为 `SOURCE_CHANGED`；不以实时曲线差异归类为构造缺陷。 |
| 9 | 成交额总览 | `[aria-label="成交额总览"]` | `TurnoverOverviewPanel.tsx`；`.panel/.section-header/.mini-metrics/.range-switch/.turnover-charts/.chart-box` | root `106:117`；header `174:280`；RangeSwitch `174:286`；IntradayChart `174:315`；HistoryChart `174:345` | `figma-pixel-artifacts/20260729-m7-module-verification/source/turnover-current-v1.png`；`figma/turnover-106-117.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `4` 张 `82px` card；双列 `239.6640625 x 178px` chart；两图共用 `0..40000亿` 纵轴 | 原生 Auto Layout + component instances + editable text/vector/rectangles | 当前 source 与 Figma exports 已复核；正式同数据时点叠图待做 | `IN_PROGRESS` | root `513.328125 x 374`，`12px` padding；header `30px`、metrics `82px`/`8px` gap；每张 plot `167.6640625 x 126px`，padding `56/16/16/36px`。成交额、日期与两图序列来自不同数据时点，登记为 `SOURCE_CHANGED`，不标 `STYLE_PASS`。 |
| 10 | 大盘资金流向 | `[aria-label="大盘资金流向"]` | `MarketMoneyFlowPanel.tsx`；`.moneyflow-v3-*`；`.pie-*`；`.sub-chart-title/.chart-box` | root `106:119`；Header `188:336`；FundTop `188:346`；OrderPie `188:358`；Trend `188:379` | `figma-pixel-artifacts/20260729-m7-module-verification/source/money-flow-current-v1.png`；`figma/money-flow-106-119.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `286 + 10 + 456px` body；`230px` trend；环图/callout/5-level axis | 原生 Auto Layout + editable text/rectangles/vectors + component instances | 当前 source 与 Figma exports 已复核；正式同数据时点叠图待做 | `IN_PROGRESS` | root `776 x 473.21875`，`12px` padding；Header/FundTop/Body 为 `752 x 30/100/262px`。右趋势 chart plot 使用 `48/16/16/36px` padding；透明 `8px` spacers固定标题 `y=8`、chart `y=32`。当前净流入、日期、饼图和趋势序列不同，登记为 `SOURCE_CHANGED`，不标 `STYLE_PASS`。 |
| 11 | 榜单速览 | `[aria-label="榜单速览"]` | `LeaderboardPanel.tsx`；`.leaderboard/.tabs/.tab-btn/.stock-cell` | root `106:120`；header `201:390`；tabs `201:399`；table `201:415`；table header `207:390` | `figma-pixel-artifacts/20260729-m7-module-verification/source/leaderboard-current-v1.png`；`figma/leaderboard-106-120.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | `7` tab、`8` 列、`10` 行、股票主体两行 | 原生 Auto Layout + editable text/rectangles；不得导入截图 | 当前 source 与 Figma exports 已复核；正式同数据时点叠图待做 | `IN_PROGRESS` | root `776 x 473.21875`；header `750 x 28.5px`、tab `750 x 30.5px`、table `750 x 370.21875px`。列宽、表头/行高均已由 node 回读；当前榜单股票与行情值不同，登记为 `SOURCE_CHANGED`，不标 `STYLE_PASS`。 |
| 12 | 涨跌停板 | `[aria-label="涨跌停统计与分布"]` | `LimitBoardPanel.tsx`；`.limit-*` | root `106:121`；header `218:390`；grid `218:404`；stats/today/history/yesterday `218:407/218:408/218:409/218:410` | `figma-pixel-artifacts/20260729-m7-module-verification/source/limit-board-current-v1.png`；`figma/limit-board-106-121.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | 八张 `179.25 x 87px` statistic card；`763 x 244px` 2x2 cell；板块条、三行领涨股、5 级轴组合柱图 | 原生 Auto Layout + editable text/rectangles/lines；未导入截图 | 当前 source 与 Figma exports 已复核；正式同数据时点叠图待做 | `IN_PROGRESS` | root `1564 x 566.5px`，`763 + 12 + 763px` 和 `244 + 12 + 244px` 的实际几何已由 metadata 回读。当前统计、板块条、领涨股和组合柱与 Figma 冻结内容不同，登记为 `SOURCE_CHANGED`，不标 `STYLE_PASS`。 |
| 13 | 连板天梯 | `[aria-label="连板天梯"]` | `StreakLadderPanel.tsx`；`.limit-ladder-v5*` | root `106:122`；header `229:390`；list `229:396`；五板以上 `296:390`；其余层 `229:399..229:403` | `modules/streak-ladder-m7-source.png`；`figma/streak-ladder-106-122-m7.png`；`figma/streak-ladder-106-122-overlay-m7.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | 当前 7 层、昨/今双侧卡片、箭头、五板以上强调与首板六列 | 原生 Auto Layout + editable text/frames；不使用模块截图或 image fill | `M7_PARTIAL_REVIEWED` | `IN_PROGRESS` | 活动 root 为 `1564 x 1445.5px`，header/list 为 `1538 x 21px / 1538 x 1388.5px`；seven layers 为 `34.5/138/188/188/188/315/265px`，间距均 `12px`。`296:390`、`229:399`、`229:400`、`229:401`、`229:402`、`229:403` 已按当前 DOM 逐层回填；其中 `229:399` 的右侧已回读为 `229 x 72px` 空态，`229:402` 已回读为两侧各 6 张 `229 x 80px` 的双行折叠态及 `103/13` 计数，`229:403` 已回读为 `45只`、两行六列 12 张 `246 x 80px` 首板卡及“展开全部”。原 `modules/streak-ladder.png` 因粘性顶栏的全页拼接污染而作废；新源/Figma/overlay 均为 `1564 x 1446`。首次叠图发现 Figma summary 日期仍为 `2026-07-27`，已改为源页面的 `2026-07-28`。梯度位移审计的最佳 Figma export 裁切为顶端 `15px`（低层渲染登记最佳水平偏移为 `-3px`）；DOM/Figma root 的 x、宽高仍一致，因此该微小图像偏移不被擅自归类为布局差异。字体光栅和图像效果差异尚未完成阈值归因，故不得记为 `STYLE_PASS` 或 `PIXEL_VERIFIED`。 |
| 14 | 板块速览 | `[aria-label="板块速览"]` | `SectorOverviewPanel.tsx`；`.sector-v2-layout/.sector-matrix/.sector-col/.rank-item/.heatmap-panel/.heatmap-preview/.heat-cell` | root `106:123`；header `246:390`；layout `246:397`；matrix `246:398/246:400/246:405`；8 cards `246:401..246:409`；heatmap `246:399`；preview `254:391` | `figma-pixel-artifacts/20260729-m7-module-verification/source/sector-overview-current-v1.png`；`figma/sector-overview-106-123.png`；`figma-pixel-artifacts/20260729-local-sector-overview-dynamic-1603/manifest.md` | `GEOMETRY_PASS` | `IN_PROGRESS` | 当前 local 可见数据已同步 | 原生 Auto Layout + editable text/frames；不使用模块截图或 image fill | 当前模块 source/Figma 同尺寸来源已复核；正式差异图待做 | `IN_PROGRESS` | 当前页面的 8 张 Top5 卡片（40 条排行）与 20 个热力格已逐项更新到 Figma。上涨数值色为 `#ff4d5a`，下跌文本和值为 `#15c784`；当前热力格均为下跌状态，使用 `#15c784 / 42%` 填充。root、layout、preview 的尺寸及布局属性均回读无漂移。本轮 source 与 Figma 的可见动态内容一致，但动态更新不替代 M7 像素叠图，故不得标记 `STYLE_PASS` 或 `PIXEL_VERIFIED`。 |
| 15 | 状态样式基线 | `[aria-label="状态样式基线"]` | `StateBaselinePanel()`；`.state-lab/.state-block/.skeleton/.empty-box/.error-box/.delayed-box` | root `106:124`；header/title/secondary `261:390/261:391/261:392`；states `261:393..261:397`；editable copy `262:390..262:402` | `figma-pixel-artifacts/20260729-m7-module-verification/source/state-baseline-current-v1.png`；`figma/state-baseline-106-124.png` | `GEOMETRY_PASS` | `IN_PROGRESS` | 4 个 `377 x 85px` 状态块：loading、empty、error、data delayed | 原生 Auto Layout + editable text/gradient rectangles；不使用截图或 image fill | 可见 `128px` 状态源图与 Figma export 已回看；页面末端截图裁切限制已登记 | `IN_PROGRESS` | root `1564 x 142px`，header/lab 为 `1538 x 21px / 1538 x 85px`；四块 gap `10px`，内容 inset `11px`。Figma 使用 `Noto Sans SC` 替代浏览器系统字体；`loading` 的自然宽度为 `49px`（source 为 `47.7734375px`），已使用自然宽度避免错误换行，其余几何锚点一致。浏览器在页面末端固定缺最后 `14px`，因此只核验可见 `128px`，不得标记 `STYLE_PASS` 或 `PIXEL_VERIFIED`。 |

## 3.1 M6 状态、交互与基线登记

1. 原生状态与交互参考 root 为 `05 Market Overview - States and Interaction Notes / 11:2`。本轮已回写并回读本地实现的 tooltip、ticker hover 暂停、新闻局部刷新、涨跌分布切换、`tsCode` 页面级跳转和 DEV-only debug 边界；事实文本节点为 `11:27/11:29/11:31/11:33/11:35/11:43`。
2. primary loaded root `106:52` 已回读为 shared `TopMarketBar` 实例加 `44` 个 component instance 的原生装配；当前本地 loaded DOM 中不存在 `OverviewDebugPanel`。该项证明 M6 装配边界，不替代 M7 视觉差异签核。

## 3.2 M7 连板天梯模块级复核

1. 历史 `full-page.png` 的 `streak-ladder.png` 因浏览器全页拼接重复粘性 `TopMarketBar` 而失效；它不能再被用作该模块的源图。M7 改用同一登录会话的两个 viewport 片段，严格按 DOM 的模块边界裁掉每段 `56px` 顶栏后拼接，不改变 DOM、CSS、页面状态或 Figma 内容。
2. 有效源图、Figma `106:122` 导出与 `50%` alpha overlay 已归档至当前 capture 目录。Figma 导出高度多于模块 root 的视觉范围经梯度位移测算，最佳上边裁切为 `15px`；这替代了此前无证据的 `24px` 估计。
3. 模块 root、7 层高度/顺序、12px 层间距、P1 双侧六卡折叠态、首板两行六列、卡片值和 summary 日期均已通过 DOM/Figma 回读。源图与 Figma 图的外框和内容密度一致。
4. `2026-07-29` 远程部署提交 `d30c7e1` 的当前 CSS 已只读核验：五板以上 body 为 `linear-gradient(180deg, rgba(247, 199, 107, 0.08), rgba(13, 20, 34, 0.78))`，header 为 `linear-gradient(90deg, rgba(247, 199, 107, 0.14), rgba(18, 27, 44, 0.92))`。Figma 若直接使用带 alpha 的渐变 stop，会渲染成高饱和整块金色，属于 `Figma construction defect`，不是线上样式。
5. 已在 Figma `296:390/296:391` 改为以线上 Panel 基底 `#101827` 预合成后的不透明渐变：body `#22262C -> #0E1523`、header `#403D35 -> #131C2C`；外框/分隔线同样改为预合成色。复验导出 SHA-256 为 `7b285689e317b0093c395f8f845d137c3fc23bc92d6586202dea11bd6c9e451b`，确认仅保留轻量金色强调。
6. 当前叠图仍可见字体栅格化和图像效果的低层差异，且尚未定义允许阈值或逐项完成 `FONT_RENDERING_GAP_OPEN` 归因。因此本条只放行 `GEOMETRY_PASS` 和 `M7_PARTIAL_REVIEWED`，不放行 `STYLE_PASS`、`PIXEL_VERIFIED` 或整页验收。

## 3.3 M7 板块速览动态数据刷新

1. 同一已登录本地会话中，`[aria-label="板块速览"]` 的 DOM border-box 是 `x=18 / y=3653.609375 / 1564 x 501px`。Figma `106:123` 的 root、header/body、`4 x 2` 排行矩阵和 `5 x 4` 热力图几何均保持不变，因此保留 `GEOMETRY_PASS`。
2. 经用户确认，当前页面的 8 组 Top5、资金流向和 20 个热力格已逐条更新至 Figma。上涨值使用 `#ff4d5a`，下跌值使用 `#15c784`；当前 20 个热力格均为下跌状态，填充使用 `#15c784 / 42%`。这次更新只处理动态事实，不改变结构、尺寸、Auto Layout、Panel 外观或字体。
3. 动态取证、Figma 回读结果和完整边界登记在 `figma-pixel-artifacts/20260729-local-sector-overview-dynamic-1603/manifest.md`。其中 `full-page.png` 是当前页面的整页证据，不是新的模块像素 overlay 源。
4. 当前状态从 `SOURCE_CHANGED` 收敛为 `IN_PROGRESS`。尚未以同尺寸模块裁图进行透明叠图，因此不授予 `STYLE_PASS` 或 `PIXEL_VERIFIED`。
3. Cover `00 Cover and Source Rules / 4:24` 的原生登记卡为 `274:2`，其内容节点 `274:3..274:21` 已保存 capture ID、capture 时间/viewport/DPR、视觉量测 SHA-256 和 primary root `106:52`。登记卡明确未采集 API 数据时点、响应正文或网络 hash，因此本 capture 只能作为 DOM/CSS/截图视觉事实，不能用于 API 数据快照结论。
4. M6 已完成；所有模块保持 `IN_PROGRESS`，直到 M7 输出 Figma 1x 全页/模块、与对应浏览器截图逐项归因并写入本账本。

## 4. 单锚点量测模板

每个模块至少填写 root、header、主要内容区、一个代表性卡片/行、一个图表或表格锚点。复杂图表按 plot area、axis、series、label、tooltip 分开填。

| 模块 | 锚点名称 | DOM selector / path | 浏览器 rect `(x,y,w,h)` | 关键 computed style | Figma node ID | Figma `(x,y,w,h)` | 几何差异 | 结果 |
|---|---|---|---|---|---|---|---|---|
| `待填写` | `待填写` | `待填写` | `待填写` | `待填写` | `待填写` | `待填写` | `待填写` | `待填写` |

## 5. 字体与颜色核对模板

| 模块/元素 | 浏览器 resolved font | Figma font | size / weight / line-height / spacing | 浏览器色值 | Figma 色值 | 结果 | 备注 |
|---|---|---|---|---|---|---|---|
| `待填写` | `待填写` | `待填写` | `待填写` | `待填写` | `待填写` | `待填写` | `待填写` |

## 6. 差异记录模板

| ID | 模块 | 分类 | 现象 | 证据 | 结论 | 修正动作 | 复验结果 |
|---|---|---|---|---|---|---|---|
| `待填写` | `待填写` | `source changed / font rendering / Figma construction defect` | `待填写` | `待填写` | `待填写` | `待填写` | `待填写` |

## 7. 页面级放行签字

- [ ] 所有 15 个模块为 `PIXEL_VERIFIED`。
- [ ] 同一 capture run 的 HTML/CSS/response/screenshot 均可定位。
- [ ] primary loaded page 没有截图、无来源颜色、私有 detached Shell 或未记录的 absolute layout。
- [ ] TopMarketBar 保持 shared component，可供股票详情页面复用。
- [ ] `OverviewDebugPanel` 不在 primary loaded page，状态样式基线仍在正式页面。
- [ ] 全页 1x 输出、逐模块 1x 输出、差异图和 Figma node 映射已归档。
- [ ] 审核人：`待填写`。
