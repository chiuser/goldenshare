# 市场总览 Figma 像素级还原执行运行手册 v1

**状态：执行中；已按用户指令切换到本地已登录 loaded 页面进行量测。M0 本地视觉 capture 已完成，旧远端 capture 仅保留为历史证据。**
**上位方案：** [市场总览 Figma 像素级还原执行计划 v2](./market-overview-figma-pixel-reconstruction-plan-v2.md)
**验收记录：** [市场总览 Figma 像素级验收账本 v1](./market-overview-figma-pixel-verification-ledger-v1.md)

## 1. 用途与边界

本文把 v2 的 M0-M7 转成一次可重复执行的施工顺序。它不是新的视觉方案，也不改变市场总览的产品内容、模块顺序、真实 API 或前端实现。

本轮唯一视觉事实源是用户指定的本地已登录 `市场总览 loaded` DOM 与 CSS。浏览器地址栏保留 `http://127.0.0.1:5173/wealth/login?redirect=%2Fwealth%2F`，但实际 DOM 已渲染 `main.page-shell`，不存在登录表单；量测对象是该 loaded 页面，而不是登录表单。Figma、截图、账本必须围绕同一个本地 capture run 建立；不得混用旧远端 capture、历史 Showcase 或不同时间的数据。

## 2. 固定输入与禁止项

### 2.1 固定输入

| 项目 | 固定口径 |
|---|---|
| 页面 | 本地已登录 loaded 页面：`http://127.0.0.1:5173/wealth/login?redirect=%2Fwealth%2F`，以 `main.page-shell` 存在且无登录表单为准 |
| 画布 | `1600 x 4342.609375` Figma root；浏览器 viewport 为 `1600 x 1200` CSS px |
| 像素条件 | DPR `1`、浏览器缩放 `100%`、无 hover/focus/tooltip、DEV debug 关闭 |
| 页面状态 | 所有首页模块完成初始请求且为 loaded；任何关键模块 error/empty/delayed 时停止本次 run |
| Figma 页面 | `04 Market Overview - Desktop Loaded`，root `Market Overview / Desktop / Loaded` |
| 证据目录 | `wealth/docs/pages/market-overview/figma-pixel-artifacts/<capture-id>/` |

### 2.2 施工禁止项

1. 不使用整页或模块截图作为 Figma UI、image fill 或图表内容；Logo 是唯一允许的位图资产。
2. 不用缩放、裁剪、隐藏内容、替换数据或手工等距布局掩盖差异。
3. 不让 Figma 模块引用当前页面私有样式的猜测值；每个尺寸和颜色必须可回溯到 capture 中的 DOM/CSS。
4. 不在未完成的模块上写“高保真”“完成”或 `PIXEL_VERIFIED`。
5. 不修改 `wealth/src/**`、后端 API、真实数据、用户功能或 Figma 以外的页面。

## 3. Capture Run 执行细则

### 3.1 生成 capture ID

格式：`YYYYMMDD-HHMMSS-<html-sha8>-<css-sha8>`；本地 Vite 样式以内联 style 注入时，使用 `YYYYMMDD-local-loaded-<viewport>-<dpr>`，并在 manifest 记录 measurement SHA-256。

例如：`20260726-210500-35daab6e-4db59061`。一个 ID 只能对应一套 HTML/CSS/JS 资源、一个浏览器条件和一个数据快照。

### 3.2 采集顺序

1. 先访问页面并等待网络空闲与模块 loaded，记录开始时间。
2. 读取页面路由、HTML、已加载 CSS/JS asset URL 和 SHA-256。
3. 读取每个市场总览模块的 API 响应状态、`tradeDate` 和响应体 SHA-256；响应正文不在本文档重复保存，只在 `response-index.md` 记录 URL、状态码、时间和 hash。
4. 在同一浏览器会话中导出全页 PNG 与每个模块的 1x crop。
5. 导出所有模块 root 和指定子锚点的 DOM geometry、computed style 与文本摘要。
6. 再次检查 HTML/CSS hash。若与第 2 步不同，丢弃本次 run，重新开始。
7. 填写 manifest 与验收账本第 1 节；此时状态仅可为 `CAPTURED`，不能提前标记通过。

### 3.3 必采模块与 selector 映射

| 顺序 | 模块键 | 浏览器 root 选择器 | Figma 目标节点 |
|---|---|---|---|
| 1 | top-market-bar | `header` | `TopMarketBar / Shared instance` |
| 2 | breadcrumb | `[aria-label="Breadcrumb"]` | `Breadcrumb` |
| 3 | shortcut-bar | `[aria-label="ShortcutBar / 页面内快捷入口"]` | `ShortcutBar` |
| 4 | market-news | `[aria-label="新闻速览"]` | `新闻速览` |
| 5 | stock-news | `[aria-label="个股新闻"]` | `个股新闻` |
| 6 | market-summary | `[aria-label="今日市场客观总结"]` | `MarketSummaryPanel / Loaded / 5 facts` |
| 7 | major-indices | `[aria-label="主要指数"]` | `MajorIndexPanel` |
| 8 | breadth | `[aria-label="涨跌分布"]` | `MarketBreadthPanel` |
| 9 | market-style | `[aria-label="市场风格"]` | `MarketStylePanel` |
| 10 | turnover | `[aria-label="成交额总览"]` | `TurnoverOverviewPanel` |
| 11 | money-flow | `[aria-label="大盘资金流向"]` | `MarketMoneyFlowPanel` |
| 12 | leaderboards | `[aria-label="榜单速览"]` | `LeaderboardPanel` |
| 13 | limit-board | `[aria-label="涨跌停统计与分布"]` | `LimitBoardPanel` |
| 14 | streak-ladder | `[aria-label="连板天梯"]` | `StreakLadderPanel` |
| 15 | sector-overview | `[aria-label="板块速览"]` | `SectorOverviewPanel` |
| 16 | state-baseline | `[aria-label="状态样式基线"]` | `StateBaselinePanel` |

若线上 selector 与该表不一致，先以实际 DOM 更新本文和验收账本，不能靠近似 selector 继续采集。

### 3.4 每个模块的子锚点

每个模块除 root 外，至少采集：`header`、`title`、`actions/tabs`、`first card/row`、`chart/table body`、`footer`。图表额外采集 plot area、轴、刻度标签、数据序列、tooltip/crosshair 默认及 hover 边界。

### 3.5 M0 停止条件

出现任意一项立即停止本次 run：

1. 页面跳转登录页、网络请求未完成、关键模块无数据或发生 error/delayed。
2. viewport、DPR、缩放、浏览器版本、登录态无法记录。
3. HTML/CSS hash 在 run 内变化。
4. 无法获得某个模块 root 的截图或 DOM geometry。
5. 发现原计划 selector 与真实 DOM 不一致且尚未回写文档。

## 4. M1 Foundations 与 Layout Skeleton

### 4.1 先后顺序

1. 建立或校验 Figma 色彩、字体、间距、圆角、边框和阴影样式，其最终值逐项来自 `computed-styles.json`。
2. 重建 `TopMarketBar` shared component 的 outer grid，再建 page background 和 page shell。
3. 建立 `content-grid`、两列 `summary-index-row`、三列 `row-three`、两列 `row-two` 的 Auto Layout/Grid wrappers。
4. 仅在 chart plot 内允许绝对定位；任何模块容器、卡片排列和文字堆叠均改用 Auto Layout。
5. 将 DOM/Figma 根框、padding、gap、border/radius/shadow 写入账本。

### 4.2 M1 放行条件

- `1600px` root、`56px` topbar、左右 `18px` gutter、`12px` module gap 均通过量测。
- Shell 不含 detached copy，`TopMarketBar` 仍为 shared component instance。
- 所有 foundation 值可反查 CSS selector/property，不存在无来源手填值。

## 5. M2-M5 模块施工顺序

每个模块严格重复以下八步，不能批量“先画全页再调”：

1. 读取本模块 root 与子锚点截图、geometry、computed style。
2. 在 Figma 以已验收 Shell/Panel component instance 创建模块 wrapper。
3. 用 Auto Layout 完成非图表容器；为文字设置真实 font family、size、weight、line-height 与 letter-spacing。
4. 用原生 Vector/Line/Rectangle/Text 重建图表、表格、tag、分割线；不能放截图。
5. 导出 Figma 模块截图并和同一 capture 的浏览器 crop 叠图。
6. 把每项偏差登记到验收账本，附 source CSS property 和 Figma node ID。
7. 仅修当前模块有来源的偏差；没有来源的差异标 `BLOCKED` 并停止本模块。
8. 全部锚点通过后标为 `PIXEL_VERIFIED`，再进入下一模块。

| 里程碑 | 模块顺序 | 额外核对点 |
|---|---|---|
| M2 | TopMarketBar、Breadcrumb、ShortcutBar、新闻速览、个股新闻、市场客观总结、主要指数 | ticker 裁剪、品牌双行文字、6 列快捷入口、新闻时间列、5 卡和 2x5 指数格 |
| M3 | 涨跌分布、市场风格、成交额总览 | plot area、刻度、卡片密度、tab active、柱/线位置、tooltip 边界 |
| M4 | 大盘资金流向、榜单速览、涨跌停板 | 饼图标注、榜单列宽、行高、空/延迟展示、涨跌停统计格 |
| M5 | 连板天梯、板块速览、状态样式基线 | 长页高度、层级列宽、热图格、状态对照不占 primary loaded 页面逻辑 |

### M5-1 连板天梯施工记录

- [x] 当前活动事实源为 `20260728-local-loaded-1600-2x` 的 `[aria-label="连板天梯"]`，不是历史 `1x` capture。它的 root 是 `x=18 / y=2196.109375 / w=1564 / h=1445.5px`，内部 header/list 为 `1538 x 21px`、`1538 x 1388.5px`；Figma 根 `106:122` 使用同一高度与原生纵向 Auto Layout。
- [x] 当前 DOM 有 7 个 list child，按 `12px` gap 依次为：summary `34.5px`、五板以上 `138px`、昨日四板→今日五板 `188px`、昨日三板→今日四板 `188px`、昨日二板→今日三板 `188px`、昨日首板→今日二板 `315px`、首板 `265px`。其合计严格为 `1388.5px`；Figma `229:396` 已回读为相同的 child count、顺序、层高、gap 和总高。
- [x] “五板以上”是当前 DOM 的独立 gold emphasis 层，不得被 P5 晋级层替代。Figma `296:390` 用首板的原生 Auto Layout 模板建立，保留 6 列 `246px` grid 的真实结构，只保留当前唯一可见卡片 `603221.SH / 爱丽家居 / 16.94 / +10.00% / 3.54亿 / 家居用品 / 6板`，并以 source CSS 的 gold panel/header/card gradients 与 border 构造；未导入截图或 image fill。
- [x] Figma `229:401` 已从过期的 `315px` 双行层重建为当前 `188px` 单行 `721 + 54 + 721px` promotion grid：昨日二板 3 只、今日三板 1 只。可编辑卡片与当前 DOM 一致：新亚制程、至纯科技、国新能源及晋级的新亚制程；过期的第二行、第二张今日卡片和“展开全部”按钮已删除。
- [x] Figma `229:400` 已按当前 `188px` 单行 promotion grid 回填“昨日三板→今日四板”：昨日 2 只、晋级 1 只；三张可编辑卡片为顺钠股份、长城军工和晋级的顺钠股份。该层保持 `721 + 54 + 721px`、`10px` grid gap、`229 x 80px` card，掉队的长城军工价格和涨跌幅按 source 的绿色保留。
- [x] Figma `229:399` 已按当前 `188px` 单行 promotion grid 回填“昨日四板→今日五板”：昨日 1 只、晋级 0 只；左侧只保留未晋级的五洲医疗 `301234.SZ / 77.75 / +10.28% / -- / 医疗器械 / 昨日四板`，右侧是 source 同口径的 `229 x 72px` 虚线“暂无股票”空态。Figma 回读确认 root 为 `1538 x 188px`、左侧仅一张 card、右侧 grid 为 `703 x 72px`。
- [x] Figma `229:402` 已按当前 `315px` 双行 promotion grid 回填“昨日首板→今日二板”：昨日 103 只、晋级 13 只；折叠态左右两侧各保留当前 DOM 可见的前 6 张 `229 x 80px` 晋级卡（中利集团、嘉美包装、明新旭腾、华达科技、亚振家居、海南海药），保持 `721 + 54 + 721px`、`10px` grid gap、`703 x 168px` 双行 grid 和底部 `1516 x 30px`“展开全部”按钮。Figma 回读确认左右各 2 行 3 列，所有卡片内容、计数和尺寸与 source 一致。
- [x] Figma `229:403` 已按当前 `265px` 首板层回填：header/body 为 `1536 x 36px`、`1536 x 227px`，`45只` 计数与“只展示今日首板股票”说明均和 source 一致；内容为 `1516 x 168px` 的两行六列 grid，12 张可编辑 `246 x 80px` 卡为捷众科技、安诺其、波长光电、科蓝软件、曙光股份、荣安地产、天融信、深纺织Ａ、国风新材、东晶电子、兴业股份、格尔软件，保留 `1516 x 30px`“展开全部”按钮。Figma 回读已确认标题、计数、两行六列、所有卡片内容与尺寸。
- [x] 当前活动 capture 的 7 个连板天梯可见层均已逐层量测并回填为可编辑 Figma 节点；M7 已完成一次模块级源图/Figma 导出/透明叠图复核。历史 `modules/streak-ladder.png` 因全页拼接重复粘性顶栏而作废，替换为 `modules/streak-ladder-m7-source.png`、`figma/streak-ladder-106-122-m7.png` 与 overlay。Figma 导出按实测顶端 `15px` 视觉范围裁切；summary 的过期 `2026-07-27` 已校正为 `2026-07-28`。字体与效果的像素差异仍未逐项归因，本模块保持 `IN_PROGRESS`，禁止标为 `STYLE_PASS` 或 `PIXEL_VERIFIED`。

### M5-2 板块速览施工记录

- [x] 板块速览现有施工内容来自历史 `20260728-local-loaded-1600-1x` 的静态证据；它只解释既有 Figma 层的来源，不再作为当前几何或动态内容的唯一依据。若继续微调本模块，必须先按当前 `20260728-local-loaded-1600-2x` 重新量测，再更新本段。
- [x] 在 `04 Market Overview - Desktop Loaded` 的 `106:123` 建立原生纵向 Auto Layout：root 为 `1564 x 501px`、四边 `12px` padding、`10px` item spacing；header/body 分别为 `1538 x 34.5px`、`1538 x 430.5px`。
- [x] body 严格按实测的 `1186.788940 + 10 + 341.210999px` 两列建立；左侧矩阵为两行四列，8 张卡为 `289.195/289.203 x 210.25px`，每卡包含 `18.5px` 标题行和 5 条 `28px` Top5 排行。Figma 结构容器按浏览器 CSS 的 `10px padding + 1px border` 收口为 `11px` 内容 inset，使文本可用宽度与 source 的 `267.195/267.203px` 一致。
- [x] 右侧 `Heatmap Panel / 246:399` 采用原生 `5 x 4` 网格：preview 为 `319.210999 x 382px`，行高严格为 `71.59375/71.6015625/71.6015625/71.6015625/71.59375px`，行/列 gap 为 `6px`。热力格和 Top5 文本均为可编辑的 Figma text/frame；未导入截图或使用 image fill。
- [x] 标题、栏目指标、排名、名称与数值分别按 source 的视觉层级建立；第一行栏目使用上涨/流入红色，第二行使用下跌/流出绿色，即使冻结数值本身带正号也不擅自重判栏目色。热力格的红色透明度按当前 source 的正向 alpha 规则冻结。
- [x] 节点回读已确认结构几何；M6 的按钮行为已登记。当前活动 capture 的源图为 `modules/sector-overview-m7-source.png`（`1564 x 501`，SHA-256 `91470e3ae641c4a440884e0b90c3d155a72b17fd9a464896b340bdf2ae2001b9`）。
- [x] M7 复核发现 Figma `106:123` 仍是此前冻结的可见数据样本：当前源图的 Top5 排行、资金流向和热力图均已更替，且热力图从旧样本的全上涨红色语义变为当前的全下跌绿色语义。Figma 导出已归档为 `figma/sector-overview-106-123-m7-source-changed.png`（`1564 x 549`，SHA-256 `0161e488def49ae835d116aca58876bb2ccb697e367d75c999b898f460a533c8`）。这不是 CSS/布局偏差，故不得以透明叠图把旧内容伪装为通过。
- [ ] 本模块状态改为 `SOURCE_CHANGED`：几何证据仍为 `GEOMETRY_PASS`，但可见内容、颜色语义与图表密度不能对当前源图授予 `STYLE_PASS` 或 `PIXEL_VERIFIED`。必须由用户确认“以当前本地页面数据更新 Figma 可见文本/颜色，同时保持已量测结构不变”，或明确冻结旧样本并接受其无法对当前页面做像素验收，之后才能继续。

### M5-3 状态样式基线施工记录

- [x] 状态样式基线现有施工内容来自历史 `20260728-local-loaded-1600-1x` 的静态证据；它只解释既有 Figma 层的来源，不再作为当前几何、文本或动态状态的唯一依据。若继续微调本模块，必须先按当前 `20260728-local-loaded-1600-2x` 重新量测，再更新本段。
- [x] 在 `04 Market Overview - Desktop Loaded` 的 `106:124` 建立原生纵向 Auto Layout。root 为 `1564 x 142px`，header/lab 为 `1538 x 21px`、`1538 x 85px`，对应浏览器 `.panel` 的 `12px padding + 1px border`，Figma 采用 `13px` content inset 以收口到同一 `1538px` 内容宽。
- [x] `StateBaseline / Four States / 261:393` 按浏览器实际 `377 + 10 + 377 + 10 + 377 + 10 + 377px` 建立四列；`261:394..261:397` 固定为 `377 x 85px`，内 inset 为 `11px`，使用对应的 base/empty/error/delayed 虚线 border、`10px` radius 与 source RGBA 文本色。
- [x] loading 使用 `262:394..262:396` 的可编辑标题和两根 `12px` 原生渐变 Rectangle，位置为 `y=11/34/54px`；empty、error、data delayed 的文本行分别按浏览器回读位置 `y=35/33.25px` 与 `y=11/27.5px` 建立。未导入模块截图或 image fill。
- [x] Figma 回读确认 root、header、lab、四列、gap、所有文本与骨架条的坐标一致；模块截图回看发现 Figma `Noto Sans SC` 的 `loading` 自然宽为 `49px`，高于 source 系统字体的 `47.7734375px`，已改用自然宽避免换行并登记为 `FONT_RENDERING_GAP_OPEN`，不是布局偏差。
- [x] M6 已在状态与交互参考页记录状态基线 help tooltip、loading 动画边界等静态说明；M7 仍须以同一 capture 做正式透明叠图后，才允许改为 `PIXEL_VERIFIED`。

## 6. M6-M7 装配与验收

### 6.1 M6 页面装配

1. 只使用 M2-M5 已验收组件实例装配 `Market Overview / Desktop / Loaded`。
2. 校验容器顺序、列比例、页面总高度、scroll 内容密度与 capture 一致。
3. 不把 DEV `OverviewDebugPanel` 放入 primary loaded root；它只作为状态说明，不属于线上主页面。
4. 对有 active tab 的模块，首期只保留 capture 当时的默认 active 状态；交互 state 另建 state frame，不让页面主稿混杂 hover/focus。

#### 6.1.1 已执行记录（2026-07-28）

1. `05 Market Overview - States and Interaction Notes / 11:2` 是原有的可编辑原生参考页。本轮已将 `11:27/11:29/11:31/11:33/11:35/11:43` 对齐到本地实现：ticker hover 暂停、新闻局部刷新、涨跌分布默认态与切换、`tsCode` 页面级跳转、`?` tooltip 和 DEV-only debug 边界。
2. `04 Market Overview - Desktop Loaded / 106:52` 已回读为 shared `TopMarketBar` + `44` 个 component instance 的装配结果；未发现 detached Shell。当前本地 loaded DOM 中 `OverviewDebugPanel` 不存在。
3. `00 Cover and Source Rules / 4:24` 的原生登记卡 `274:2` 已保存 capture ID、capture 时间/viewport/DPR、视觉量测 hash 和 primary root `106:52`。它同时明确未采集 API 数据时点、响应正文或网络 hash，因此只作为视觉证据登记。
4. M6 完成不改变任何模块的 `IN_PROGRESS` 状态；所有模块仍必须经过 M7 的当前活动 capture 导出、对应截图差异归因和账本签核。

### 6.2 M7 复核

1. 使用 M0 同一 capture 对 primary loaded Figma page 导出全页和模块截图。
2. 逐模块审查叠图：先 geometry，再 typography，再 colors/effects，最后图表与内容密度。
3. 把可证明的字体 rasterization 差异单独标记；不得将它归类为布局通过的理由。
4. 填写账本页面级放行项。存在一个 `BLOCKED`、`SOURCE_CHANGED` 或未归因差异时，禁止页面级 `PIXEL_VERIFIED`。

#### M7-1 连板天梯已执行的模块级复核

1. 浏览器 `fullPage` 导出若重复粘性顶部栏，必须判为无效源图；不得从这种导出继续裁取长页面模块。
2. 改用同一页面状态的 viewport 片段时，每段先按真实顶部栏高度裁掉覆盖区域，再按 DOM module border-box 拼接。该方法只用于视觉取证，禁止修改页面 DOM/CSS 来截屏。
3. Figma 节点导出可能包含 frame 以外的视觉 effect extent；必须用可复核的位移测算确定裁切，而不是按阴影经验猜。当前 `106:122` 的最佳顶端裁切为 `15px`。
4. 已归档的连板天梯 source、Figma export 和 `50%` overlay 证明 7 层结构、可见内容和外框几何相符；字体栅格化与效果差异尚未有允许阈值，故只记 `M7_PARTIAL_REVIEWED`。

## 7. 文档更新纪律

1. 实施事实更新到本运行手册和验收账本；方案口径变更才更新 v2，不倒写既有产品文档。
2. 线上 HTML/CSS hash 变化时，新建 capture 目录和新账本 run，不覆盖旧证据。
3. 发现 selector、模块顺序、CSS 来源或 Figma node 映射不对时，先更新文档再继续 Figma 修改。
4. 每轮交付报告必须列出：capture ID、Figma 修改节点、已验收模块、未通过模块、证据路径和下一阶段。
5. 当前本地活动 capture 的浏览器 `body.scrollHeight` 为 `4343px`，Figma 施工根取同次 DOM border-box 高度 `1600 x 4342.609375px`；其中 Shell 为 `4286.609375px`，包含 `56px` 顶栏。历史 `1x` 的 `4319px / 4263.609375px` 和旧远端的 `4168/4169px` 都不得用于当前施工判断。

## 8. 本轮执行清单

- [x] 创建 v2 执行计划、审计报告和验收账本。
- [x] 创建本次 M0 capture run 的目录与 manifest：`20260726-191213-35daab6e-4db59061`。
- [x] 使用隔离无头 Chrome 验证认证前置条件：页面重定向至 `/wealth/login`，不能取得市场总览模块截图或 DOM 量测。
- [x] 将 BLOCKED 原因、资源 hash 和恢复条件写入验收账本；该 run 不是有效 source baseline。
- [x] 在本地已登录 loaded 会话完成活动 capture：`20260728-local-loaded-1600-2x`；历史 `1x` 仅保留为早期施工证据。
- [x] 按本地 capture 重建 M1 Foundations 与 Layout Skeleton：`04 Market Overview - Desktop Loaded / 103:2`、root `106:52`、shared TopMarketBar `97:2` / instance `106:53`；旧 `62:2` skeleton 已删除，标记为 `SOURCE_CHANGED`，不得继续增量修补。
- [x] 完成 M2 的 shared Shell 与第一屏构造：Breadcrumb `106:105`、ShortcutBar `106:106`、新闻双列 `106:109/106:110`、市场客观总结 `106:112`、主要指数 `106:113`；所有非图表布局已回读为原生 Auto Layout，临时 QA Slice 已删除。
- [ ] 在进入 M3 前，按验收账本对 M2 六个区域完成最终模块差异图签核；当前首屏截图复验与几何/样式基线已完成，但尚未授予 `PIXEL_VERIFIED`。
- [x] M3-1 涨跌分布 primary loaded 默认态：`MarketBreadth / 106:115` 已完成原生 Auto Layout 构造；可复用构件为 RangeSwitch `149:2`、MetricCard `149:7`、DistributionChart `149:11`。回读通过 root、header、三列卡与 chart plot 的固定尺寸；11 个分桶均为 editable 文本/矩形，不使用截图。
- [ ] M3-1 涨跌分布：在 `05 Market Overview - States and Interaction Notes` 创建“涨跌家数”双线状态、hover/tooltip 边界说明，并做 M7 正式模块差异图签核。
- [x] M3-2 市场风格 primary loaded 默认态：`MarketStyle / 106:116` 已完成原生 Auto Layout 构造；复用 RangeSwitch `149:2`、MetricCard `149:7`，趋势图 component 为 `153:2`。回读通过 root、header、三列卡、`178px` chart 与 `425.3359375 x 126` plot 的固定尺寸；三条线按同一 capture 的真实 oneMonth 22 点数据与前端 `niceRange` 公式建立，不使用截图或估算点位。
- [ ] M3-2 市场风格：在 `05 Market Overview - States and Interaction Notes` 创建 `3个月` 切换状态、hover/tooltip 边界说明，并做 M7 正式模块差异图签核。
- [x] M3-3 成交额总览 primary loaded 默认态：`Turnover / 106:117` 已完成原生 Auto Layout 构造；专属月份切换 component 为 `163:2`，四列 metric component 为 `165:2`，日内累计与历史趋势 component 分别为 `166:2`、`170:2`。回读通过 `513.328125 x 374` root、`12px` padding、`30px` header、四张 `82px` card、两张 `239.6640625 x 178px` chart 与共享 `0/10000/20000/30000/40000亿` 纵轴。五个日内点和 `oneMonth` 22 个历史点均来自同一次 frozen API response，不使用截图。
- [ ] M3-3 成交额总览：在 `05 Market Overview - States and Interaction Notes` 创建 `3个月` 切换状态、hover/tooltip 边界说明，并做 M7 正式模块差异图签核。
- [x] M4-1 大盘资金流向 primary loaded 默认态：`MarketMoneyFlow / 106:119` 已完成原生纵向 Auto Layout 构造，回读为 `776 x 473.21875` root、`12px` padding、`10px` item spacing；header/fund cards/body 为 `752 x 30/100/262px`。基金卡组件为 `178:2`，单型资金环图为 `179:2`，历史趋势为 `183:336`；所有图表元素均为可编辑原生节点，不使用截图。右侧趋势以两个透明 `8px` spacer（`193:390`、`195:390`）精确表达源 CSS 的标题和 chart margin，图表绝对起点为 `y=194`。
- [ ] M4-1 大盘资金流向：在 `05 Market Overview - States and Interaction Notes` 创建 `3个月` 切换状态、hover/tooltip 边界说明，并做 M7 正式模块差异图签核。
- [x] M4-2 榜单速览 primary loaded 默认态：`106:120` 已以 `12px` content inset、`28.5px` header、`10px` header-to-tab gap、`30.5px` tab 行与 `8px` tab-to-table gap 建立。原生 table shell `201:415` 固定 `750 x 370.21875px`，header `207:390` 为 `28px`，10 行分别为 `34.171875px`，8 列严格使用浏览器最终宽度 `48.1640625 / 151.375 / 87.1484375 x4 / 100.9140625 / 100.953125px`；冻结截图 `modules/leaderboard.png` 是唯一文本来源，当前 local DOM 只用于最终 geometry，不替换行数据。截图与节点回读均通过，未导入截图。
- [ ] M4-2 榜单速览：在 `05 Market Overview - States and Interaction Notes` 补 active tab、row hover 与整行进入股票详情的交互说明，并做 M7 正式模块差异图签核。
- [x] M4-3 涨跌停统计与分布 primary loaded 默认态：`LimitBoard / 106:121` 已完成原生纵向 Auto Layout 构造；回读为 `1564 x 566.5px` root、`12px` padding、`10px` header-to-grid gap、`1538 x 30.5px` header 与 `1538 x 500px` grid。grid 固定为 `763 + 12 + 763px` 双列、`244 + 12 + 244px` 双行；八张统计卡、两套板块条/三行领涨股和左下历史组合柱图都由 editable text/rectangle/line 节点构成。冻结截图 `modules/limit-board.png` 是静态内容唯一来源，本地 loaded DOM 只用于量测，不使用截图填充。
- [ ] M4-3 涨跌停统计与分布：在 `05 Market Overview - States and Interaction Notes` 补月份切换、领涨股行 hover/整行进入股票详情及图表 hover/tooltip 说明，并做 M7 正式模块差异图签核。
