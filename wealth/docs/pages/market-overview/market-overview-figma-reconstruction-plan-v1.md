# 市场总览原生 Figma 设计稿还原计划 v1

> **状态：已废止的准备稿，不得继续执行。**
>
> 本文曾正确确定“线上实际 CSS 为第一视觉事实源”和“主页面必须由原生 Figma 节点构成”，但没有定义可重复的线上截图冻结、DOM 计算样式量测、`CSS selector -> Figma node` 映射、逐模块叠图和差异闭环。因此它只能作为历史背景，不能证明或交付像素级还原。
>
> 后续施工必须改按：
> - [市场总览 Figma 像素级还原审计 v1](./market-overview-figma-pixel-audit-v1.md)
> - [市场总览 Figma 像素级还原执行计划 v2](./market-overview-figma-pixel-reconstruction-plan-v2.md)
> - [市场总览 Figma 像素级验收账本 v1](./market-overview-figma-pixel-verification-ledger-v1.md)

## 1. 目标与边界

### 1.1 目标

将当前财势乾坤“乾坤行情 / 市场总览”页面还原为一份**原生、可编辑、可维护**的 Figma 设计稿，目标文件为 [Goldenshare Web](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=0-1)。

这不是把浏览器截图放进 Figma，也不是依据个人审美重新设计。交付物必须能让后续页面复用同一套 token、组件和布局规则，并能与当前 `wealth` 前端实现逐模块核对。

### 1.2 本轮范围

1. 建立 Figma 的基础变量、文本样式、效果样式、布局网格和行情语义。
2. 建立市场总览实际用到的共享组件与模块级组件。
3. 还原当前市场总览的桌面端 loaded 页面、关键组件状态和必要交互说明。
4. 建立“Figma 节点 -> 当前前端组件/样式来源”的交接映射。
5. 以固定画布宽度逐模块比对当前浏览器页面，记录差异并收敛。

### 1.3 明确不做

1. 不修改 `wealth` 前端代码、后端 API、真实数据 contract 或模块三件套。
2. 不把页面导出为单张图片后伪装成设计稿；除既有 Logo 位图外，正文、容器、图表、图标、分割线均须是 Figma 原生可编辑节点。
3. 不为 Figma 重做产品信息架构、模块顺序、色彩语义或内容密度。
4. 不在本轮建立股票详情页、运营后台或全站所有页面的 Figma 稿。
5. 不在本轮接入 Figma Code Connect；组件实现稳定后另行评审。
6. 不为了模拟真实运行而把实时 ticker、每秒时钟、10 分钟新闻刷新等行为硬编码进设计稿。

## 2. 已完成审计

### 2.1 Figma 文件现状

| 审计项 | 结果 | 结论 |
| --- | --- | --- |
| 文件访问 | 可访问 `RADlZzREU4lPVviYfkLy6x` | 链路可用，可以在同一文件内建立设计系统与页面稿。 |
| 顶层结构 | 仅有空白 `main` 画布（`0:1`） | 没有可复用的既有组件、变量或页面结构，本轮必须从原生基础搭建。 |
| 现有设计资产 | 未发现可继承的 Figma 组件库 | 不能假定已有 token、Auto Layout 规则或资产命名。 |

### 2.2 当前首页代码现状

市场总览不是一个巨型静态 HTML，而是由页面编排、共享外壳和模块组件组合而成。CodeGraph 已覆盖页面入口、共享组件、模块调用关系和前端消费者；结论如下。

| 层级 | 当前代码事实 | Figma 对应物 |
| --- | --- | --- |
| 页面编排 | `wealth/src/pages/market-overview/MarketOverviewPage.tsx` 按模块组合页面 | `Market Overview / Desktop - Loaded` 页面级 frame。 |
| 顶部外壳 | `wealth/src/shared/ui/top-market-bar/TopMarketBar.tsx` 同时被市场总览与股票详情页使用 | shared `TopMarketBar` 组件，不能为市场总览复制一套。 |
| 通用容器 | `wealth/src/shared/ui/Panel.tsx` 提供 section header、标题、帮助图标与内容区 | `Panel`、`PanelHeader`、`HelpTooltip` 基础组件。 |
| 页面结构 CSS | `wealth/src/pages/market-overview/market-overview-page.css` 定义两列、三列、模块间距与桌面宽度 | 页面 grid、Auto Layout、组件间距规则。 |
| 视觉 token | `wealth/src/styles/design-tokens.css`、`wealth/src/styles/global.css` | Figma variables / text styles / effect styles。 |
| 模块实现 | `wealth/src/features/market-overview/**` | 模块级 Figma 组件和实例。 |

当前主页面实际组合顺序为：

1. `TopMarketBar`
2. 面包屑与页面行动区
3. 快捷入口区
4. 新闻速览 + 今日市场客观总结 + 个股新闻 + 主要指数
5. 可选本地 debug 信息区
6. 涨跌分布 + 市场风格 + 成交额总览
7. 大盘资金流向 + 榜单速览
8. 涨跌停板
9. 连板天梯
10. 板块速览
11. 状态样式基线

其中第 11 项已被既有页面架构文档确认“先保留在正式 homepage 作为可见参考模块”；本轮 Figma 主页面应保留它，而不是擅自移到隐藏设计页。

### 2.3 布局与视觉事实

| 项目 | 当前事实 | Figma 还原要求 |
| --- | --- | --- |
| 页面宽度 | CSS 正常桌面范围为最小 `1460px`、最大 `1840px`；在较窄桌面断点会收敛至 `1420px` | 必须先确定一张标准 desktop frame；不能拿移动端或任意缩放截图作为基准。 |
| 顶栏 | 高度 `56px`，含品牌、六个导航项、行情 ticker 与用户入口 | 作为跨页面 shared component；不得只画市场总览专用版本。 |
| 页面底色 | 深色线性/径向渐变，非纯色后台 | 用可编辑 Figma fills 表达，而非平铺截图。 |
| Panel | 深色玻璃感 surface、细边框、约 `12px` 圆角、紧凑 padding | 所有模块容器从同一 Panel 组件派生。 |
| 行情颜色 | A 股红涨绿跌：上涨、正值、净流入、涨停为红；下跌、负值、净流出、跌停为绿 | 不得引用通用 success/error 语义替代行情语义。 |
| 文字与数字 | 中文 UI 使用系统中文字体栈；价格和指标使用等宽数字字体栈 | Figma 需先核验可用字体；若缺失，必须记录替代字体及视觉差异，不能静默替换。 |
| 图表 | 当前实现以 SVG/CSS 图表为主，存在折线、柱状、饼图、热力矩阵和状态图例 | 用 Figma vector、Auto Layout、文本和可复用 chart primitive 还原，不导入浏览器截图。 |

### 2.4 视觉来源冲突审计

当前资料存在“早期文档仍称 V1.1 为基准、当前工程规则已切换为 V4”的漂移。该问题不能被忽略，否则 Figma 会复制出与当前实现不一致的老版本。

| 来源 | 当前表述 | 与当前工程的关系 | 本计划建议处理 |
| --- | --- | --- | --- |
| `wealth/AGENTS.md` | 明确 `market-overview-v4.html` 是当前生效原型 | 当前工程强约束 | 作为视觉原型基线。 |
| `wealth/docs/README.md` | 明确 V4 Showcase、v0.2.7 token、v0.7 guideline 是当前生效资料 | 当前文档索引 | 作为当前文档基线。 |
| `MarketOverviewPage.tsx` 与 CSS | 已包含 V4 之后经评审落地的顶栏、新闻、模块和交互调整 | 当前运行事实 | 与 V4 不一致时优先。 |
| `implementation-architecture-v1.md` | 多处仍把 V1.1 写为优先视觉来源，且保留了早期 token/组件描述 | 历史工程化方案，局部过时 | 只能用于追溯“为何存在某组件”，不能覆盖当前代码/V4。 |
| `market-overview-baseline.md` 与部分 system baseline | 局部仍引用 V1.1/V1.8 | 历史摘要，存在漂移风险 | 不直接用于 Figma 像素取值；后续应单独做文档对齐。 |

**已拍板的 Figma 取证优先级**：

1. 当前线上实际生效的市场总览页面代码、DOM 与 CSS。这是唯一第一事实源，Figma 必须还原其已部署的视觉结果。
2. 当前线上 CSS 未能单独表达、但页面结构仍需要补全的细节，才读取 `market-overview-v4.html`。
3. `03-design-tokens-v0.2.7.md`、`04-component-guidelines-v0.7.md` 与 review v2 仅用于解释 token 语义、组件职责和交互原则，不能覆盖线上 CSS 的具体取值。
4. V1.1/V1.8、旧 implementation architecture 只作历史解释，不得作为视觉取值或布局依据。

用户最新指令用于限定本次工作范围；只有用户明确要求 Figma 表达一个尚未上线的新版视觉时，才允许偏离当前线上 CSS，并必须在 `00 Cover and Source Rules` 单独标注该偏离。

## 3. Figma 成品结构

目标文件保持简洁，但要把“基础规则、可复用组件、正式页面、状态说明”分开，避免把所有内容堆进一张长画布。

```text
Goldenshare Web
  00 Cover and Source Rules
  01 Foundations
  02 Components - Shell
  03 Components - Market Overview
  04 Market Overview - Desktop Loaded
  05 Market Overview - States and Interaction Notes
```

### 3.1 `00 Cover and Source Rules`

内容：本计划的取证优先级、标准 desktop frame、Figma 构建日期、代码/原型引用、版本说明。

目的：后续设计或开发人员能分辨“当前正式基线”和“历史参考”，不再拿 V1.1 误覆盖当前页面。

### 3.2 `01 Foundations`

建立可被所有后续财势乾坤页面复用的最小设计基础，不扩张成抽象过度的设计系统。

| 类别 | 建立内容 | 来源 |
| --- | --- | --- |
| Color variables | `page`、`topbar`、`panel`、`surface`、边框、主文字、次文字、muted、brand、行情 up/down/flat | `design-tokens.css` 与 v0.2.7 token。 |
| Spacing variables | `8/10/12/16/20/24` 等当前页面实际间距 | `design-tokens.css`、页面 CSS。 |
| Radius and border | Panel、Card、Chip、Button 的圆角、边框颜色与强调边框 | 当前 CSS 与 V4。 |
| Typography styles | 页面标题、Panel 标题、正文、辅助文字、数值、图表轴标签、按钮 | 当前 CSS 字号/字重/行高。 |
| Effects | Panel 阴影、玻璃感、背景渐变 | `global.css` 和当前页面样式。 |
| Layout grid | 标准 desktop 内容宽度、页面 gutter、12 列/模块比例说明 | `market-overview-page.css` 实际 grid。 |

原则：Variable 名称采用语义名，不在 Figma 里复制早期 `--csq-*` / `--cs-*` CSS 命名争议；文档中保留其 CSS source reference 即可。

### 3.3 `02 Components - Shell`

| Figma 组件 | 必须包含的状态/结构 | 对应当前实现 |
| --- | --- | --- |
| `TopMarketBar` | 品牌区、激活/非激活导航、ticker 单元、用户入口；ticker 只展示静态可视窗口 | `shared/ui/top-market-bar/TopMarketBar.tsx`、`top-market-bar.css`。 |
| `BreadcrumbTimeStatus` | 路径、日期/时间、交易状态的静态样式 | `market-overview/Breadcrumb.tsx`。 |
| `ShortcutCard` | 标题、说明、徽标、选中态 | `market-overview/ShortcutBar.tsx`。 |
| `Panel` | 标题、帮助图标、右侧 meta/action、内容 slot | `shared/ui/Panel.tsx`。 |
| `RangeSwitch` | default/active/hover/disabled | 当前市场模块的 range/模式切换样式。 |
| `MetricCard` | 标题、主值、secondary、red/green/flat 数值 | 市场总结、风格、成交额等卡片。 |
| `DataStateBlock` | loading、empty、error、delayed、loaded 的容器语义 | 当前模块状态和状态样式基线。 |
| `HelpTooltip` / `Toast` | 常规提示、无真实功能动作反馈 | component guideline 与当前页面交互。 |

### 3.4 `03 Components - Market Overview`

模块组件保留业务可读的名称；不把整个页面做成一个无法编辑的超级组件。

| 模块组件 | 关键子结构 | 当前组件来源 |
| --- | --- | --- |
| `MarketNewsPanel` | 标题、可见条数、时间、单行新闻、滚动窗口静态态 | `features/market-overview/news/*`。 |
| `MarketSummaryPanel` | 5 卡默认布局、可选第 6 卡、事实文案、状态 badge | `summary/MarketSummaryPanel.tsx`。 |
| `MajorIndicesPanel` | 2 x 5 指数卡、涨跌颜色与代码/名称层级 | `indices/MajorIndexPanel.tsx`。 |
| `MarketBreadthPanel` | 上涨/下跌/平盘卡、涨跌分布柱图、涨跌家数折线图、模式切换 | `breadth/MarketBreadthPanel.tsx`。 |
| `MarketStylePanel` | 风格卡和三线趋势图 | `style/MarketStylePanel.tsx`。 |
| `TurnoverOverviewPanel` | 累计成交额、历史趋势、刻度/坐标语义 | `turnover/TurnoverOverviewPanel.tsx`。 |
| `MarketMoneyFlowPanel` | 净流入摘要、分单饼图、趋势图 | `money-flow/MarketMoneyFlowPanel.tsx`。 |
| `LeaderboardPanel` | tab、榜单行、股票主体、数值列、缺失态 | `leaderboards/LeaderboardPanel.tsx`。 |
| `LimitBoardPanel` | 涨停/跌停核心统计与领涨股票行 | `limit-up/LimitBoardPanel.tsx`。 |
| `StreakLadderPanel` | 连板梯队、代表股票、查看全部动作 | `limit-up/StreakLadderPanel.tsx`。 |
| `SectorOverviewPanel` | 热力矩阵、板块单元、资金/涨跌信息 | `sectors/SectorOverviewPanel.tsx`。 |
| `StateBaselinePanel` | 已确认保留的状态样式参考区 | `pages/market-overview/StateBaselinePanel.tsx`。 |

### 3.5 `04 Market Overview - Desktop Loaded`

这是唯一的正式 loaded 页面 frame。它必须由上述组件实例组成，而不是把组件复制后手改。

构建规则：

1. 页面 frame 使用固定标准宽度，内容高度随模块自然增长。
2. 顶栏和页面主体分层；顶栏不随页面内容纵向拉伸。
3. 首页第一屏先完成“顶部栏 -> 面包屑/行动区 -> 快捷入口 -> 新闻/总结/指数”组合，再继续后续模块。
4. `row-three`、`row-two`、新闻/总结/指数组合严格沿用当前 CSS 比例；不因 Figma 画布方便而改成均分或自由 masonry。
5. 采用冻结的数据快照填充展示，但数据数值不承担 API 契约含义。
6. 市场总览默认 loaded frame 不展示本地开发专用 `OverviewDebugPanel`。

### 3.6 `05 Market Overview - States and Interaction Notes`

本页只保存正式页面所需的状态和交互说明，不重做第二个产品页面。

| 类型 | Figma 表达方式 | 说明 |
| --- | --- | --- |
| ticker 跑马灯 | 静态可视窗口 + 动画说明 | Figma 不模拟无限复制的 CSS marquee。 |
| 日期/交易状态 | 静态实例 + “运行时每秒刷新”说明 | 不把系统时钟写成固定产品事实。 |
| 新闻自动刷新 | 静态列表 + “10 分钟局部刷新、无整页闪烁”说明 | 不做真实定时原型。 |
| 图表 hover/crosshair | tooltip 与 crosshair 组件变体 | 至少有默认态和 hover 参考态。 |
| 模块状态 | loading / empty / error / delayed / loaded 组件变体 | 保持局部失败不拖垮整页的视觉边界。 |
| 点击动作 | 原型连接或行动说明 | 仅表达现有交互目的，不伪造未实现页面。 |

## 4. 详细执行步骤

### M0：冻结视觉证据与施工口径

**目的**：防止在 Figma 中混用旧 V1.1、V4 与当前代码的不同版本。

步骤：

1. 以当前线上市场总览页面的 DOM、CSS 和标准 viewport 截图冻结视觉基线；不从本地分支、V4 或历史 HTML 推导第一版外观。
2. 确认标准 desktop frame 的宽度和用于像素核对的浏览器 viewport。
3. 在当前本地页面取得一个 loaded 状态的完整参考截图；记录日期、缩放倍率、浏览器 viewport、页面是否开启 debug。
4. 对比截图、`market-overview-v4.html`、`MarketOverviewPage.tsx` 和 CSS：逐项标记“完全一致”“当前代码更新”“原型独有且未采用”。
5. 生成 Figma `00 Cover and Source Rules` 的来源说明，不开始绘制业务模块。

输出：一份不会随意漂移的视觉证据清单。

门禁：没有明确优先级和固定 frame，不进入 M1。

### M1：建立 Foundations

**目的**：使所有组件使用相同颜色、间距、字体和效果，避免同一页面出现手填的相近色/相近间距。

步骤：

1. 从 `design-tokens.css` 提取当前实际使用的页面、surface、border、文字、brand、up/down/flat 值。
2. 在 Figma 建立颜色 variable collection；行情红绿与普通成功/错误语义分开命名。
3. 从当前 CSS 提取 `8/10/12/16/20/24` 间距、圆角、边框、阴影，建立 number/effect styles。
4. 建立中文正文、标题、数字、图表轴、标签、按钮的 text styles；先核验中文和数字字体在 Figma 是否可用。
5. 建立 desktop content grid、topbar 高度、gutter 与 panel gap 的 layout 参考。
6. 在 Foundations 页面放置“token -> CSS source”小型对照表，便于开发回查。

输出：可被组件直接绑定的变量和文本样式。

门禁：不得在 M2 以后新增未登记的色值、字号、圆角或模块私有阴影；发现例外须先记录来源。

### M2：建立共享 Shell 组件

**目的**：先解决跨页面复用和全页共同结构，避免市场总览与未来股票详情各画一套顶栏。

步骤：

1. 建立 `TopMarketBar`，按当前 shared React 组件拆成 brand、nav、ticker、user entry 四个可编辑区域。
2. 导入既有 `logo_new.png` 作为唯一允许保留的位图品牌资产；不将文字 Logo 栅格化。
3. 用 component variants 表达导航 default/active、ticker up/down/flat、用户入口 default/hover，不复制多份组件。
4. 建立 `BreadcrumbTimeStatus`、`ShortcutCard`、`Panel`、`RangeSwitch`、`MetricCard`、`DataStateBlock` 与 `HelpTooltip`。
5. 用 Auto Layout 和 component properties 暴露必要文字、数值、色彩语义和右侧 action；不暴露会破坏布局的任意尺寸开关。
6. 将 `TopMarketBar` 实例同时放到一个“跨页面复用示例” frame，证明它不是市场总览私有组件。

输出：Shell 与通用组件库。

门禁：市场总览正式页面只能使用 component instance；禁止 detach 后为页面做私有修改。

### M3：建立图表原语与状态原语

**目的**：用最小可复用原语承接各模块图表，不把每张图的坐标、tooltip、刻度逻辑手工复制。

步骤：

1. 建立 Chart Grid、Axis Label、Line Series、Bar Series、Donut Slice、Heat Cell、Tooltip、Crosshair 的基础可编辑结构。
2. 用当前页面实际网格线、轴文字、行情红绿和数值字体制作样式；不把旧 showcase 的白底配色或字体带入。
3. 为折线图建立至少 default / hover 参考态；tooltip 值来自冻结快照，仅表达视觉结构。
4. 为涨跌分布建立“分布柱图”和“涨跌家数折线图”两种成品组合，以反映当前按钮切换后的页面事实。
5. 为大盘资金流向建立饼图标签与连线规则，确保 label 不因组件缩放脱离图形。
6. 对每种原语标记“可复用”或“仅市场总览专用”，避免抽象出无消费者的组件库。

输出：图表和状态原语库。

门禁：每个图表的轴语义必须与当前页面一致，例如计数图从 0 起；不得为了画面好看引入负值轴或不存在的指标。

### M4：逐模块原生重建

**目的**：逐个完成页面内容，缩小视觉偏差的定位范围。

执行顺序和每步核对项如下：

| 顺序 | 模块 | 施工与核对重点 |
| ---: | --- | --- |
| 1 | 头部、面包屑、快捷入口 | 顶栏 `56px`、品牌/导航/ticker 比例、面包屑层级、页面 gutter。 |
| 2 | 新闻、市场客观总结、主要指数 | 新闻可见密度、总结默认 5 卡、总结文案区域、主要指数 2 x 5 卡。 |
| 3 | 涨跌分布 | 三张计数卡、默认“涨跌分布”、11 个分桶柱图，以及“涨跌家数”切换态。 |
| 4 | 市场风格、成交额总览 | 同行三列比例、图表刻度、卡片与 chart 的垂直间距。 |
| 5 | 大盘资金流向、榜单速览 | 两列比例、饼图标签不越界、榜单行密度和各类榜单 tab。 |
| 6 | 涨跌停板、连板天梯 | 统计块、股票主体行、梯队结构、无预测/买卖建议。 |
| 7 | 板块速览 | 热力矩阵密度、单元格信息层级、行情颜色。 |
| 8 | 状态样式基线 | 保留为正式页面可见的参考模块，并与 `DataStateBlock` 变体相同。 |

每个模块完成后都要在同一标准宽度下和浏览器截图并排核对：容器尺寸、内外边距、文字层级、数字字重、颜色、边框、图表比例、模块高度和相邻模块间距。

输出：各模块 Figma 组件与逐模块核对记录。

门禁：一个模块没有通过核对，不提前用整体页面缩放掩盖偏差，也不继续堆叠后续模块。

### M5：组装正式 Desktop Loaded 页面

**目的**：将已验证的组件实例装配为可维护的主页，而不是拼接若干已经漂移的副本。

步骤：

1. 创建 `04 Market Overview - Desktop Loaded` frame，使用 M0 确认的标准宽度。
2. 以 M4 验收后的 component instance 组装完整模块顺序。
3. 锁定容器 grid 和模块比例，检查三列/两列区域在同一 page gutter 下对齐。
4. 填入同一冻结数据快照，避免一个页面同时出现不同时点、不同 API 状态的数字。
5. 确认默认页面不包含本地 `OverviewDebugPanel`，但正式状态样式基线仍可见。
6. 标记视觉稿版本、数据快照日期与代码 revision，便于以后查明差异来源。

输出：一份完整的、可编辑的市场总览 desktop loaded 设计稿。

### M6：状态、交互与原型说明

**目的**：把设计能表达的动态能力定义清楚，不让 Figma 静态稿被误读为运行时实现。

步骤：

1. 在 `05 Market Overview - States and Interaction Notes` 摆放 shared 与模块状态变体。
2. 标注 ticker、时钟、新闻刷新、图表 hover、范围/模式切换、新闻 hover 暂停、榜单/股票跳转等行为的触发条件。
3. 如需可点击原型，仅连接当前已存在的页面内状态，或已存在的股票详情路由；不伪造未开发目标页面。
4. 对 loading/error/delayed 状态注明“局部模块状态”，不能画成整页覆盖层。
5. 将开发专用 debug 信息作为非产品态单独标注，不放进 primary loaded frame。

输出：状态与交互参照页。

门禁：Figma 动画/原型不得与当前产品事实冲突；无法高保真模拟的运行时行为必须写明边界。

### M7：视觉验收与交接

**目的**：确认 Figma 不只是“风格接近”，而是能作为后续开发和评审的事实来源。

步骤：

1. 用 M0 同一 viewport 重新截取浏览器 loaded 页面，并导出 Figma 对应 frame 作并排对照。
2. 按模块逐项核对：位置、宽高、gap、padding、字体/字重/行高、颜色、border、radius、shadow、图表轴、数值颜色。
3. 对每项差异记录“代码更新优先”“原型差异”“Figma 构建偏差”之一；只有第三类可以直接修稿。
4. 检查所有 primary UI 节点是否可编辑，确认没有整屏截图、被 detach 的共享组件或手填的无来源样式。
5. 产出组件目录、变量目录、代码映射和剩余差异清单。

验收标准：

1. 标准宽度下，模块顺序、布局比例、颜色语义和内容密度与当前正式首页一致。
2. TopMarketBar 是共享组件，可被后续页面直接实例化。
3. 主页面所有重要模块都由原生 Figma 组件/图层构成。
4. 状态与互动说明覆盖现有关键行为，但不伪造产品能力。
5. 没有将 V1.1 的旧视觉口径未经说明地混入当前 V4/当前代码口径。

## 5. 当前文件与 Figma 的映射

| 代码/资料 | 本计划中使用方式 |
| --- | --- |
| 当前线上已部署的市场总览 DOM/CSS | Figma 的唯一第一视觉事实源；页面截图必须从同一线上标准 viewport 取得。 |
| `wealth/src/pages/market-overview/MarketOverviewPage.tsx` | 用于追溯当前页面模块组合、默认页面状态与页面级动作；若与线上部署不一致，以线上为准并记录版本差异。 |
| `wealth/src/pages/market-overview/market-overview-page.css` | 用于定位线上布局、列比例、gap、panel/page 关系的代码来源；不以本地未部署改动覆盖线上。 |
| `wealth/src/shared/ui/top-market-bar/TopMarketBar.tsx` | 用于追溯 shared 顶栏的内容和可复用边界。 |
| `wealth/src/shared/ui/top-market-bar/top-market-bar.css` | 用于追溯顶栏尺寸、各区比例与 ticker 可视区域。 |
| `wealth/src/shared/ui/Panel.tsx` | 通用 Panel 结构。 |
| `wealth/src/styles/design-tokens.css` | 核心颜色、间距、圆角、字体与 effect 的第一手 CSS 值。 |
| `wealth/src/styles/global.css` | 页面背景、基础文本和行情语义 class。 |
| `wealth/src/features/market-overview/**` | 每个模块的可见字段、组件结构、状态与局部交互。 |
| `wealth/docs/reference/showcase/market-overview-v4.html` | 仅在当前线上 CSS 未表达某一细节时，作为补充参考。 |
| `wealth/docs/reference/design/03-design-tokens-v0.2.7.md` | 仅用于设计 token 的语义解释。 |
| `wealth/docs/reference/design/04-component-guidelines-v0.7.md` | 仅用于通用组件职责和交互原则。 |
| `wealth/docs/reference/review/market-overview-html-review-v2.md` | 已确认模块布局修订的历史依据。 |

## 6. 风险与控制

| 风险 | 根因 | 控制措施 |
| --- | --- | --- |
| 复刻旧 V1.1 而非当前页面 | 多份旧文档仍含 V1.1 优先级 | M0 先冻结来源优先级；代码/V4 冲突时记录，不静默选旧稿。 |
| 用截图伪造完成 | 图表和密集页面手工搭建成本较高 | M7 检查 primary 节点可编辑性；仅 Logo 可保留为位图。 |
| Figma 与实际页面按不同宽度比较 | 现有桌面 CSS 有最小/最大宽度及断点 | M0 冻结 viewport 与 canvas 宽度；所有验收使用同一宽度。 |
| 字体替换造成看似细小但系统性偏差 | CSS 使用系统字体栈与数字字体栈 | M1 先做字体可用性核验；不可用时登记明确 fallback。 |
| 动态交互在静态稿中失真 | ticker、时钟、新闻刷新、真实 API 是运行时行为 | M6 用变体/说明表达；不造假动画或伪 API。 |
| Figma 库过度抽象 | 一次试图覆盖未来所有页面 | 本轮只做市场总览和 TopMarketBar 所需最小组件；其他页面按需求增量扩展。 |

## 7. 需要用户拍板的事项

以下决定会直接影响 Figma 的事实基线；在进入 M0 以后的 Figma 写入前需要明确。

### D1：视觉取证优先级（已拍板）

已确认：当前线上实际生效的市场总览 CSS 与视觉结果为第一优先级。V4、token/component guideline 只能补充线上 CSS 未表达的细节；V1.1/V1.8 不得参与视觉还原。

影响：Figma 表达的是线上正在运行的系统，而不是本地未部署代码或早期 HTML。

### D2：标准 desktop 画布宽度（已拍板）

已确认：以 `1600px` 宽作为正式 Figma desktop frame，页面高度自适应；视觉验收使用同宽浏览器 viewport。

依据：当前页面正常 desktop 内容范围是 `1460px` 至 `1840px`，`1600px` 位于常用中间区间，可避免把窄桌面断点误当成默认设计。

影响：不冻结宽度就无法判定一个 Panel 的宽度、三列比例、ticker 可视窗口和图表密度是否正确。

### D3：页面数据快照口径（已拍板）

已确认：Figma primary loaded frame 使用一次冻结的 loaded 页面数据快照，并在 Cover 中记录截图日期和数据时点；不使用会随 API 或时钟变化的 live 数据。

影响：Figma 的任务是可复核的视觉稿，不是行情实时看板。数据快照不会改变 API 或前端逻辑。

### D4：原型交互深度（已拍板）

已确认：本轮只做组件状态变体、必要点击连接和交互说明；不做 ticker 无限跑马灯、每秒时钟、10 分钟新闻请求等运行时动画。

影响：可以完整说明交互设计，同时避免出现“Figma 演示看似能运行、实际上与产品行为不一致”的伪实现。

### D5：开发专用 debug 信息的呈现位置（已拍板）

已确认：不放进 `04 Market Overview - Desktop Loaded`；如需保留，单独放在 `05 Market Overview - States and Interaction Notes` 标记为 `DEV only`。

依据：当前 `OverviewDebugPanel` 仅由本地 debug 条件渲染，不是用户态页面的一部分。

影响：不影响已确认保留的“状态样式基线”；二者性质不同，状态样式基线仍在正式主页。

### D6：字体不可用时的 fallback（已拍板）

已确认：先在 Figma 检查 `PingFang SC`、数字字体栈中的可用项；若缺失，使用最接近的可用中文系统字体和等宽数字字体，并在 Cover 标记替代关系后继续。

影响：该事项只有字体不可用时才需要实际选择，避免静默替换造成日后难以解释的字宽差异。

## 8. 下一步

视觉取证、标准 frame、数据快照、原型深度、debug 呈现和字体 fallback 均已拍板，可按 M0 到 M7 执行。执行期间任何发现的线上 CSS/原型冲突先登记到 `00 Cover and Source Rules`，不擅自通过改前端代码或自由重设计解决。
