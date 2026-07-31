# 市场总览 Figma 像素级还原审计 v1

**状态：已完成审计，等待按 v2 计划返工。**
**审计日期：2026-07-26**
**范围：仅财势乾坤 `市场总览` 的 Figma 还原流程与现有 Figma 草稿；不修改产品前端、后端、数据或 API。**

## 1. 审计结论

现有 Figma 稿不是截图拼图：加载态首页由原生 `FRAME`、`TEXT`、`LINE`、`VECTOR` 和组件实例组成，`TopMarketBar` 也已做成 shared component instance。这部分可以保留为**可编辑草稿资产**。

但它不满足“像素级还原”的交付条件，不能继续作为正式设计稿使用。根因不是某几个颜色或间距微调，而是施工链路缺少以下四条不可替代的事实约束：

1. 没有冻结可重复取得的线上浏览器视觉基线：缺少统一的 viewport、DPR、浏览器、页面状态、数据快照、全页/模块截图与资源版本记录。
2. 没有逐节点量测线上 DOM：当前稿没有 `CSS selector -> DOM computed style -> Figma node` 映射，无法证明任何一个 Figma 元素来自哪条真实 CSS。
3. 没有逐模块差异闭环：没有叠图、几何 delta、字体与图表的核对记录；“看起来接近”被误当成“已还原”。
4. 主要页面容器仍以手工绝对定位为主：它可以摆出近似布局，却不能从 CSS Grid/Flex 的真实约束推导出可维护的响应关系，也无法定位像素偏差源头。

因此，本轮结论是：**现有 Figma 草稿必须按 v2 从证据冻结开始逐模块返工；不得在现有近似画面上继续局部打补丁。**

## 2. 审计依据

### 2.1 线上部署证据

| 项目 | 已核验事实 | 作用 |
|---|---|---|
| 线上 URL | `https://wealthworld.com.cn/wealth/market/overview` | 唯一第一视觉事实源。 |
| 线上 HTML | SHA-256 `35daab6e63a2dbda803397ae54680226c2e56102117fe80b14827c42c6dda2b8` | 证明本次审计读取的 deployed shell 版本。 |
| 线上 CSS asset | `/wealth/assets/index-C3nS_K6q.css` | 线上最终计算样式的资源来源。 |
| 线上 CSS | SHA-256 `4db5906178622f6a1852f39f253a36965586e7da99fbc53b27d27825160be875` | 后续截图与 DOM 采样必须记录对应 hash，防止页面发版后误比旧图。 |
| 已核验 CSS 特征 | 顶栏 `56px`、`168px` brand grid、`18px` page gutter、`12px` 主模块 gap、11 桶分布图、红涨绿跌 token | 说明线上 CSS 与本地当前主线共享关键布局口径；仍不得据此跳过浏览器计算样式采样。 |

### 2.2 本地实现证据

| 文件 | 已核验职责 | 本轮用法 |
|---|---|---|
| `wealth/src/pages/market-overview/MarketOverviewPage.tsx` | 当前首页的实际模块装配顺序、debug 条件与模块交互入口 | 建立模块清单与 Figma 页面装配顺序。 |
| `wealth/src/pages/market-overview/market-overview-page.css` | shell、Grid、Panel、新闻、图表、榜单、连板、板块的页面级 CSS | 每个模块量测的源码索引，不直接代替线上 computed style。 |
| `wealth/src/shared/ui/top-market-bar/TopMarketBar.tsx` | 市场总览和股票详情复用的顶栏组件 | Figma 必须保持 shared，而不是复制市场总览私有顶栏。 |
| `wealth/src/shared/ui/top-market-bar/top-market-bar.css` | 顶栏 grid、ticker、品牌与用户入口细节 | 顶栏量测与组件拆分依据。 |
| `wealth/src/styles/design-tokens.css` | 颜色、字体、圆角、阴影、页面尺度 token | Figma variable/text/effect 的命名和数值依据。 |
| `wealth/src/styles/global.css` | 页面背景、基础字族、行情红涨绿跌 | 还原行情色语义与底色。 |

CodeGraph 已覆盖 `MarketOverviewPage`、`TopMarketBar`、模块消费者和页面入口。当前组合顺序为：顶栏、面包屑、快捷入口、新闻/总结/主要指数、三列指标模块、资金流向/榜单、涨跌停、连板天梯、板块速览、状态样式基线。`OverviewDebugPanel` 仅在本地 DEV 且 `debug=1` 时出现，不属于 primary loaded 页面。

### 2.3 Figma 草稿证据

目标文件：[Goldenshare Web](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=0-1)。

| Figma 对象 | 审计结果 | 结论 |
|---|---|---|
| `04 Market Overview - Desktop Loaded` | 存在 `1600 x 4140` 的 `Market Overview / Desktop / Loaded` root。 | 1600px 画布约束已建立。 |
| `TopMarketBar / Shared instance` | `1600 x 56`，为 instance，使用 horizontal auto layout、`12px` spacing、左右 `18px` padding。 | 可以作为返工时的组件基础，但仍需截图量测验证文字与子区比例。 |
| `Page shell` | `1564px` 宽，`x=18`，与 1600px 内容 gutter 相符；但 `layoutMode=NONE`。 | 外层坐标接近 CSS，内部仍为手工定位。 |
| 新闻、主要指数、涨跌分布、风格、成交额、资金、榜单、涨跌停、天梯、板块、状态区 | 全部存在原生节点。 | 覆盖范围完整，但不等于视觉验收通过。 |
| 主要模块容器 | 大多数为 `layoutMode=NONE`；已见大面积绝对坐标。 | 不符合“CSS Grid/Flex 应使用可追溯约束”的施工要求。 |
| Cover 来源说明 | 已写明线上 DOM/CSS 为第一事实源、1600px frame。 | 缺少抓取时间、HTML/CSS hash、viewport/DPR、数据快照、截图路径和 revision。 |
| 验收资料 | 没有模块截图、DOM 几何导出、叠图或差异台账。 | 是本轮不能宣称像素级的直接原因。 |

## 3. 现有草稿的具体偏差类别

| 类别 | 当前问题 | 为什么不能靠“看着调一下”解决 | v2 处理方式 |
|---|---|---|---|
| 布局 | 多数模块用绝对 `x/y/width/height` 摆放。 | 容器高度、换行、列宽变化时无法从 CSS 规则推导，偏差会层层累积。 | Flex/Grid 对应 Auto Layout 或明确 grid cell；绝对定位只允许 SVG/canvas 内部图形。 |
| 尺寸 | 尚未记录每个容器的真实 `getBoundingClientRect()`。 | 图层宽高相近不能说明 gap、padding、border-box、行高正确。 | 每个模块建立 DOM/Figma 边界框账本，几何逐项为零差异。 |
| 字体 | Cover 仅记录 `Inter fallback`，没有证明 Figma 字体与线上实际 resolved font 一致。 | 中文字宽、数字宽度、字重与行高会造成持续性排版偏差。 | 捕获 `getComputedStyle(...).fontFamily/fontSize/fontWeight/lineHeight/letterSpacing`；字体不可用即阻塞并先解决。 |
| 图表 | 折线、柱、饼、热图以近似图形表达，未以真实截图坐标、刻度和点位量测。 | 图表的视觉密度、轴基线、标签位置最容易“风格像、细节错”。 | 每个图表建立 plot area、axis、series、label、tooltip 的坐标账本。 |
| 内容 | 冻结数据时点、新闻行数、指数/榜单值和状态没有统一证据。 | 同一页面在不同时点取数，列宽、换行、图形高度都会不同。 | 使用一份命名快照，记录页面请求、响应 hash 与截图。 |
| 验收 | 仅做过 Figma 整页缩略视觉检查。 | 缩略图无法发现 1-10px 的间距、字重、对齐与图表轴错误。 | 全页只用于完整性；逐模块 1x 截图叠图与差异清单才是放行依据。 |

## 4. 必须保留与必须返工的边界

### 4.1 可以保留

1. Figma 文件及其六个页面的目录结构。
2. `TopMarketBar` 的 shared component 身份与品牌 logo 图像资产。
3. “只允许 logo 使用位图；产品页面本体必须是原生可编辑节点”的边界。
4. 当前页面模块范围和模块顺序。
5. 线上 CSS 第一、V4 仅补交互、历史 V1.1/V1.8 不参与视觉取样的优先级。

### 4.2 必须返工

1. `04 Market Overview - Desktop Loaded` 的所有业务模块，不能以当前绝对定位草稿作为正式版本。
2. `01 Foundations` 的 token、字体、effect、layout grid，必须补可追溯的源码/计算样式清单。
3. Shell 和模块组件的 variants/Auto Layout，必须依据已采集的 DOM 结构复建。
4. `00 Cover and Source Rules`，必须补足版本、截图和数据快照的可复现证据。
5. 任何“已完成/高保真/像素级”标记，必须等验收账本全部通过后才允许出现。

## 5. 风险与控制

| 风险 | 控制 |
|---|---|
| 线上页面在施工期间发版 | 每次量测必须重记 HTML/CSS hash；hash 变化即作废当前 comparison run，重新冻结。 |
| Figma 默认字体与浏览器 resolved font 不同 | 先做字体探测；无同字体不得假装通过像素级验收。 |
| 数据在请求间变化 | 浏览器页面、网络响应、模块截图必须来自同一个 capture run。 |
| 用全页缩放掩盖差异 | 禁止用缩略图判定；逐模块 1x crop 是唯一视觉 gate。 |
| Figma 手工微调覆盖 CSS 事实 | 每次调节必须登记 selector、CSS 属性、Figma node 和原因；没有来源不允许改。 |
| 影响产品实现 | 本轮只操作 Figma 和文档，不改 `wealth/src/**`、API 或数据。 |

## 6. 后续文档关系

1. 本文记录“为什么旧稿不合格”和当前事实。
2. [像素级还原执行计划 v2](./market-overview-figma-pixel-reconstruction-plan-v2.md) 定义唯一允许的返工顺序与门禁。
3. [像素级验收账本 v1](./market-overview-figma-pixel-verification-ledger-v1.md) 是每个模块的唯一验收记录，不允许另起零散 checklist。
4. 原 `market-overview-figma-reconstruction-plan-v1.md` 只保留历史背景，禁止继续施工。
