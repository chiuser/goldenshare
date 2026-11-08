# 股票和指数详情页副图显示与隐藏 LLD v1

> 2026-11-08。Figma 交互已审阅通过，四类当前页面的全开尺寸和底轴高度已量测复核。范围与验收口径见[实施方案 R1～R6](./detail-chart-indicator-panel-visibility-implementation-design-v1.md#1-交付范围)。本设计补充[现有共享图表 LLD](./detail-chart-zoom-low-level-design-v1.md)的显隐布局和底轴位置。

## 1. 代码落点与参数

下表中的源码路径均相对 `wealth/src/`。

| 文件 | 符号与职责 |
|---|---|
| `shared/charts/detail-workspace/detailChartTypes.ts` | 从 `DetailChartPanelKey` 排除 `kline` 得到 `DetailChartIndicatorPanelKey`，定义 `DetailChartIndicatorControls`。`DetailChartWorkspaceBaseProps` 新增可选 `hiddenIndicatorPanels`，未传等同全开。`renderPanelHeader` 的副图参数复用同一个键类型。 |
| `shared/charts/detail-workspace/useDetailChartIndicatorControls.ts`（新增） | `useDetailChartIndicatorControls(tsCode)` 只持有当前标的和隐藏集合，返回集合及点击函数。 |
| `pages/stock-detail/StockDetailPage.tsx`、`pages/index-detail/IndexDetailPage.tsx` | 在日线与分钟分支外调用上面的 hook，股票沿用页面 `tsCode`，指数使用页面现有的 `normalizedTsCode`。把同一 `indicatorControls` 传给两个分支。 |
| `shared/charts/detail-workspace/DetailChartIndicatorToggle.tsx`（新增） | `DetailChartIndicatorToggle` 渲染一个按钮。`DetailChartIndicatorToggles` 按 `volume`、`macd`、`kdj` 返回三个同款按钮，供两个分钟适配组件使用。容器由调用方提供，保持现有 flex 布局。 |
| `features/stock-detail/chart/StockChartWorkspace.tsx`、`features/index-detail/chart/IndexChartWorkspace.tsx` | `StockIndicatorBar`、`IndexIndicatorBar` 接上副图按钮，保留原有主图与其他标签。把隐藏集合传给共享图表。 |
| `features/stock-detail/chart/StockMinuteChartWorkspace.tsx`、`features/index-detail/chart/IndexMinuteChartWorkspace.tsx` | 在 Loaded 图表接入按钮和隐藏集合。`LoadedIndexMinuteChart` 接收上层传来的同一份状态。 |
| `shared/charts/detail-workspace/DetailChartWorkspace.tsx`、`DetailChartPane.tsx`、`detail-chart-workspace.css` | `DetailChartWorkspace` 传入显示状态和时间模式。`DetailChartPane` 保留标题、宿主及覆盖层的同一根元素。CSS 收起副图占用的空间，固定底轴位置。 |

四个适配组件都接收必传的 `indicatorControls`。直接渲染适配组件的测试同步补参数，包括 `features/index-detail/debug/IndexRecognitionDebug.test.tsx`。共享图表接受的显隐值与回调如下。共享图表只接收集合，不接收点击回调。

```ts
export type DetailChartIndicatorPanelKey = Exclude<DetailChartPanelKey, "kline">;

export interface DetailChartIndicatorControls {
  hiddenIndicatorPanels: ReadonlySet<DetailChartIndicatorPanelKey>;
  onToggleIndicatorPanel: (panel: DetailChartIndicatorPanelKey) => void;
}
```

## 2. 页面状态与标签

1. `useDetailChartIndicatorControls` 用一份 `useState` 保存 `{ tsCode, hiddenIndicatorPanels }`。初始隐藏集合为空。事件使用函数式更新，复制集合后对传入键做一次 `delete` 或 `add`，再返回新状态。只要标的未变，周期、日期、请求状态和研究模式变化都沿用同一个集合。
2. 发现当前 `tsCode` 与状态中的标的不同，在当前组件的渲染中有条件地把这份状态替换为新标的的空集合。这样切换标的时，子图第一次显示就是全亮，A → B → A 也恢复全亮。刷新时由 `useState` 初始化。采用同组件内局部重置，不给整个详情页或图表追加 `key`，不引入跨标的缓存、存储、周期同步 effect 或点击去抖。[React `useState` 说明](https://react.dev/reference/react/useState#storing-information-from-previous-renders)
3. 按钮只用 `hiddenIndicatorPanels.has(panel)` 得到是否点亮，沿用 `detail-chart-indicator-tab` 和 `active`，设置 `type="button"`、`aria-pressed={visible}`，鼠标和键盘都触发同一函数。面板键与显示文字固定为 `volume` → `VOL`、`macd` → `MACD`、`kdj` → `KDJ`。按钮切换时保持 DOM 和键盘焦点。
4. 股票日线在 `StockIndicatorBar` 遍历中，先按 `tab.key` 将 `VOL`、`MACD`、`KDJ` 三个确定的键分流到共享按钮。此分支的可见性来自页面选择，原 `tab.active`、`tab.supported` 仍只供其余分支使用。当前 `StockDetailChartDefaultsDto.availableIndicatorTabs` 已含这三项，现有面板本身也始终存在。无需加能力字段或把 `VOL` 走到通用暂未支持提示。其余标签维持 `onOverlayChange` / `onAction` 原路径。
5. 指数日线保留 `VOL`、`成交额`、`MACD`、`KDJ`、`均线`、`BOLL`、符合原条件时的 `趋势通道` 顺序。成交额仍为禁用按钮。保留 `daily-wave-bottom-bar` 外层与附加研究控件。股票分钟在已有 `bottomBar` 轨道传入含三个按钮的标签容器及 `bottomBarAriaLabel="股票分钟指标栏"`。指数分钟在 `IndexMinuteIndicatorBar` 将三个按钮放在均线、BOLL 前，原有状态消息仍位于标签之后。空、失败和无数据等待状态继续由各适配组件现有分支渲染。

## 3. 图表布局与实例

`DetailChartWorkspace` 保留 `macd → volume → kdj` 的副图顺序和稳定的 `key`，继续渲染四个图表宿主。它在 `.detail-chart-area` 上标记 `data-time-mode={timeMode}`，在副图上逐项传 `hidden={hiddenIndicatorPanels.has(panel)}`。`DetailChartPane` 的根元素用 `data-hidden={hidden || undefined}` 供 CSS 识别，并设 `inert={hidden || undefined}`，使隐藏副图及其控件退出交互和可访问性树。原共享 Tooltip 与右侧信息栏继续由各自的逻辑处理。

`.detail-chart-area` 沿用 Grid。第一行给主图，其余三行分别对应 MACD、成交量和 KDJ 所占区域。MACD 和成交量行收起时归零。KDJ 行在全开时包含 KDJ 可见内容和原有底轴，收起时只剩底轴。KDJ 宿主始终用绝对定位贴绘图区底边，由第四行单独占位，保留原宿主尺寸。日线与分钟线的裁切规则见第 4 节。外层 `.detail-chart-workspace` 的 `34px` 标签条行沿用现有规则。

```css
.detail-chart-area {
  --detail-chart-pane-height: calc(100% * 17 / 95);
  --detail-chart-time-axis-height: 24px;
  grid-template-rows:
    minmax(0, 1fr)
    var(--detail-chart-macd-row, var(--detail-chart-pane-height))
    var(--detail-chart-volume-row, var(--detail-chart-pane-height))
    var(--detail-chart-kdj-row, var(--detail-chart-pane-height));
}

.detail-chart-area[data-time-mode="minute"] {
  --detail-chart-time-axis-height: 28px;
}

.detail-chart-area:has(> .macd-panel[data-hidden]) {
  --detail-chart-macd-row: 0px;
}

.detail-chart-area:has(> .volume-panel[data-hidden]) {
  --detail-chart-volume-row: 0px;
}

.detail-chart-area:has(> .kdj-panel[data-hidden]) {
  --detail-chart-kdj-row: var(--detail-chart-time-axis-height);
}

@media (max-width: 1360px) {
  .detail-chart-area {
    --detail-chart-pane-height: calc(100% * 16 / 94);
  }
}
```

`.kline-panel`、显示中的 `.macd-panel` 和 `.volume-panel` 分别放在第 1、2、3 行。隐藏的 MACD 和成交量用 `position: absolute; inset-inline: 0; top: 0; height: var(--detail-chart-pane-height); visibility: hidden`，使它们退出布局且宿主宽高仍可用于同步。`.kdj-panel` 用相同的宽高规则，固定 `bottom: 0`，第 4 行由网格留出。

`17 / 95` 与 `16 / 94` 分别来自当前全开轨道 `44fr 17fr 17fr 17fr` 和 `46fr 16fr 16fr 16fr`，基数是底部标签条上方的 `.detail-chart-area` 高度。主图获得的高度是被隐藏副图的可见内容高度。关闭 KDJ 时，第四行由原高减到时间轴高度，因而 MACD 和成交量下移的距离等于 KDJ 的标题加可见绘图区，底轴空间只计一次。每个断点以当前真实页面量测确认这组尺寸关系。

## 4. 独立底轴与浏览范围

1. **日线。** 沿用 `DailyTimeAxis`、`buildDailyTimeAxisMarkers` 和 KDJ 的现有横坐标。日期轴继续 `bottom: 0`，高度引用 `--detail-chart-time-axis-height`。KDJ 可见时用 `clip-path: inset(0 0 var(--detail-chart-time-axis-height) 0)` 露出时间轴上方的部分。KDJ 隐藏时用 `visibility: hidden`，共享日期轴继续显示。原 `24px` 来自 `.detail-chart-time-axis` 的现行 CSS。
2. **分钟线。** `createPaneChart`、`buildChartOptions` 及 `formatShanghaiMinuteAxisLabel` 保持原样，默认底轴继续由 KDJ 图实例绘制。KDJ 可见时保留原图，原生时间轴自然位于其绘图区下方。KDJ 隐藏时，用 `clip-path: inset(calc(100% - var(--detail-chart-time-axis-height)) 0 0 0)` 只露出原生时间轴。独立底轴指页面上的固定一条空间，原生刻度继续由原实例绘制，避免增设图表、重新计算时间刻度或把轴移到其他副图。`28px` 已在两类 5 分钟图的刻度画布实测验证，和锁定的 Lightweight Charts 5.2.0 默认高度一致。外层表格行高 `34px`，布局取实际绘制的 `28px`。已有 `each-pane` 初始化行为继续由原条件处理，四个页面入口沿用 `bottom-pane`。
3. **范围和缩放。** 开关只改变布局。四图创建 effect、`dataKey`、`syncVisibleRange`、`alignRightPriceScales`、`ResizeObserver`、`applyIndicatorRanges` 和 `syncCrosshairMove` 沿用现有逻辑。全部关闭时主图自然填到轴的上缘，缩放按钮继续用主图内的现有偏移。宽度、首尾时间与根数只作验收断言。当前没有证据证明隐藏 KDJ 会改变横向宽度，禁止为此增加锁宽、拦截尺寸或图表回调、手动写回范围、重试或延时。
4. 底轴和标签条位置固定。验证轴上方紧贴的图依次为全开时 `KDJ`、关 KDJ 后 `成交量`、再关 VOL 后 `MACD`、再关 MACD 后 `K线`。恢复任意副图后沿用同一顺序。

## 5. 验收用例

| 需求 | 自动化证据 | 本地浏览器证据 |
|---|---|---|
| R1 独立开关 | 四个适配组件的 `*ChartWorkspace.test.tsx` 检查标签可用、点亮/点灭、传给共享图表的隐藏键和开关回调。`DetailChartWorkspace.test.tsx` 用同一个组件 `rerender` 隐藏、恢复，断言整个目标根元素具有隐藏标记，其他副图和主图没有标记。隐藏时保留原 host 引用。 | 四类图表逐项关闭再开启，检查标题、读数、图形、坐标、标注一起显隐。用 Tab 检查焦点跳过隐藏控件。真实页面对照第 6 节的显示字段。 |
| R2 空间分配 | 共享组件断言面板顺序、隐藏标记及 `inert`。真实几何和原生刻度的可见性由浏览器断言。 | 固定同一视口记录全开时各块外框和可见绘图区。关 KDJ 后，MACD/成交量下移原 KDJ 的可见内容高度，保留各自高度，成交量底部贴时间轴上缘。关中间成交量时，KDJ 留在底部，MACD 与 KDJ 紧贴。全关后主图占满底轴上方区域，再全开回到原布局。比较图表外框、底轴和标签条位置，按同一浏览器的亚像素取整核对。 |
| R3 轴与范围 | 日线断言共享 `DailyTimeAxis` 仍渲染，分钟断言 KDJ 初始化为唯一原生底轴。切换副图后同一批图表宿主、四图 logical range、`createChart`、`remove` 和各序列 `setData` 计数保持原样。 | 首屏全亮，数据就绪后直接关 KDJ 再恢复，比较右侧价格区宽度、横向首尾时间及根数。再缩放并拖到非最新区间后切换，核对原范围、主图指标与十字线同步。日线日期轴和分钟上海时间轴各只显示一条，位置固定。关 KDJ 后分钟轴仍可见，其他副图绘图区完整。 |
| R4 状态 | `StockDetailPage.test.tsx`、`IndexDetailPage.test.tsx` 在现有周期缓存用例上覆盖默认全亮、日线关闭 KDJ → 5 分钟 → 另一分钟周期 → 回日线、换标的后全亮。含 A → B → A。若工作区适配组件被 mock，mock 要渲染传入的真实控制状态或将事件回调接回页面。 | 同一标的周期切换保持当前三个按钮状态，换标的、刷新恢复全亮。等待正常加载再检查，错误态复用现有提示和重试。 |
| R5 标签共存 | 股票日线三副图按钮不会触发 `onAction`，原成交额行为、均线/BOLL 和趋势可用条件原样覆盖。指数保留成交额禁用、均线/BOLL 与趋势原条件。分钟保留状态提示、空态和错误。 | 全开时复核原主图指标、标签栏顺序、侧栏位置与原基线一致。股票分钟底部由原空轨道显示为标签条。检查指数分钟及日线研究扩展场景的状态文字和原控件可用。 |
| R6 网络边界 | 页面测试等待首屏或周期请求结束，记录调用次数。连续切换副图不会发出新请求，切换周期仍走现有有界请求及缓存。 | DevTools 网络记录中，点击前后行情、指标、趋势、九转和历史请求计数不变。正常拖动到历史边界和切换周期仍可走原请求。控制台无新增错误。 |

受影响测试优先跑 `npm --prefix wealth run test -- detail-workspace stock-detail index-detail`。后续交付门禁执行 `npm --prefix wealth run typecheck`、`npm --prefix wealth run test` 和 `npm --prefix wealth run build`。测试替身只用于按钮、布局属性、状态和图表调用的断言，真实几何和 API 展示用本地浏览器单独验收。

## 6. 真实 API 展示与性能证据

通过现有本地 Wealth 前端入口验收。如需启动前端，沿用本机已配置的开发环境和 `npm --prefix wealth run dev`。用 `/wealth/market/stock/<tsCode>` 和 `/wealth/market/index/<tsCode>` 各选一个已验证日线及分钟数据可用的标的。使用真实路由和本地已启用的分钟能力。每页先等日线 Loaded，再选择现行支持且有数据的分钟周期。周期联动用 5 分钟和另一个已支持的频率。图表全开时记录现有几何基线，使用缩放文档曾量测的 `1600 × 1200` 视口，再用 `1360 × 1200` 覆盖共享 CSS 的窄侧规则，宽度依据现行断点。

| 数据 | 需比对的真实响应字段和页面 |
|---|---|
| 股票、指数日线 `kline` | 在同一个 `tradeDate` 对比 K 线 `open/high/low/close`、成交量 `vol/volDisplay`、`factors.macd.{dif,dea,macd}` 与 `factors.kdj.{k,d,j}`。用各页面现有格式读数。缺值继续显示原占位。 |
| 股票、指数分钟 `minutes`、`minute-indicators` | 在同一 `tradeTime` 对比 `open/high/low/close`、`vol`、`macdDif/macdDea/macd`、`kdjK/kdjD/kdjJ`。在收起、恢复副图后核对同一时间的现有值。 |
| 状态 | 记录实际请求状态和页面提示。若真实返回 Partial 或 Delayed，核对原提示仍在且有数据的图仍可切换。用已有页面测试补足无数据和失败场景，单独标记替身覆盖的边界。 |

一次点击允许原尺寸观察、布局和绘图更新，增量上限是零次请求、零次实例创建和序列重装。布局记录与网络计数前后对照，保留实际测量证据。只读取页面既有请求窗口。若验证中断，在同样本和视口刷新恢复默认，从未记录的步骤继续，额外读数最多为重开该页面的原请求，不做全量拉取或生产数据操作。

### 6.1 编码前量测记录

2026-11-08，使用已登录的本机 Chrome，前端为 `127.0.0.1:5174/wealth`，后端为 `127.0.0.1:8000`。样本为股票 `601878.SH` 和指数 `000001.SH` 的日线与 5 分钟线。两页的 `page-init`、`kline`、`minutes`、`minute-indicators` 均返回 HTTP `200`。日线与分钟行情请求均沿用页面的 `endDate=2026-11-06`、`limit=500`，分钟请求为 `freq=5`。四类全开图表的每块均已渲染画布。

下表单位为 CSS px。高度取页面元素边界，展示到小数点后三位。日线和 5 分钟线的图表区及四块面板高度相同，底轴之外的 KDJ 内容高度分别取原日期轴上缘和原生绘图区实测。

| 视口 | 标的 | 图表区高 | K 线 / MACD / 成交量 / KDJ 面板高 | MACD / 成交量绘图区宿主高 | KDJ 日线底轴上方绘图区高 | KDJ 5 分钟绘图行高 |
|---|---|---:|---|---|---:|---:|
| `1600 × 1200` | 股票、指数 | 1002 | 464.078 / 179.305 / 179.305 / 179.305 | 151.305 / 150.305 | 127.313 | 122.500 |
| `1360 × 1200` | 股票 | 1006 | 492.297 / 171.234 / 171.234 / 171.227 | 143.234 / 142.234 | 119.234 | 114.500 |
| `1360 × 1200` | 指数 | 1002 | 490.336 / 170.555 / 170.555 / 170.555 | 142.555 / 141.555 | 118.555 | 114.500 |

四类图表的面板标题高 `28px`、标签条高 `34px`。日线 `DailyTimeAxis` 实测高 `24px`。分钟图的原生刻度画布实测高 `28px`，外层表格行实测高 `34px`，固定底轴按画布绘制高度取值。画布边缘与标签条上缘的差异在本次量测中为亚像素，继续用现有图表取整。已核对现行 CSS 在宽、窄两档的四块分配比例，确认第 3、4 节使用的尺寸依据。

上证日线量测时仍显示现有「顶底识别加载失败」提示，基础行情与三块副图均正常绘制。本记录只确认当前全开布局、底轴及基础行情接口，显隐、恢复、浏览范围和新增请求的验证安排在实现后执行。

## 7. 编码门禁矩阵

对照[模块交付通用清单](./module-delivery-checklist-v1.md)。通过条件均指后续开发验收。例外白名单为空。

| 条款 | 适用性与落点 | 验证 |
|---|---|---|
| §2.1 交付事实链 | 适用。Figma 交互审阅已通过，按该稿修订方案和 LLD。 | 第 6.1 节已复核真实页面的全开几何及底轴高度。 |
| §2.2 后端事实归一 | 适用。第 6 节字段走现有 API 与映射。 | 真实响应和页面同时间读数一致。 |
| §2.3 模块状态机 | 适用。第 2 节复用现有状态机和超时。 | R4/R5，现有状态用例。 |
| §2.4 显示与数据绑定 | 适用。副图仅切显示，保留真实单位、缺值、颜色。 | R1 与第 6 节。 |
| §2.5 行为过程 | 适用。第 5 节逐项覆盖切换和恢复。 | 组件、页面与浏览器证据。 |
| §2.6 文档同步 | 适用。原共享方案和 LLD 链接本次设计。 | 开发完成后按 R1～R6 回填对账。 |
| §2.7 渐进替换 | 数据源切换不适用。复用现有真实源，失败处理见方案第 4 节。 | R6 验证现行请求和回退路径。 |
| §2.8 契约与消费者 | 适用。冻结第 1 节前端参数，四个消费者一并接入。API DTO 原样消费。 | 类型检查与四个适配测试。 |
| §2.9 图表坐标 | 适用。第 4 节保留横轴同步和时间语义。 | R2/R3 的几何和轴验证。 |
| §2.10 统计与传输 | 新增统计不适用，适用现有传输边界。 | R6 证明无点击增量请求。 |
| §2.11 配置 | 不适用。无策略配置改动。 | 文件与环境差异检查。 |
| §2.12 映射矩阵 | 适用。以本表为门禁。 | 评审及最终逐项对账。 |
| §2.13 例外与语义断言 | 适用。无例外，语义见 R1～R6。 | 第 5 节测试。 |
| §2.14 图表参数语义 | 适用。保留既有范围、指标轴和格式规则。 | R3 及共享图表既有回归。 |
| §2.15 并排双图 | 不适用。现有图表上下排列。 | 用 §2.9 检查同步与对齐。 |
| §2.16 指标卡片文案 | 不适用。无卡片改造，标签复用原尺寸。 | R5 浏览器检查标签和状态提示。 |
| §2.17 真实 API 与展示 | 适用。第 6 节真实响应及显示检查。 | 现有真实路由驱动四类浏览器图表，并对照响应字段。 |
| §2.18 跨模块抽象 | 适用。见方案第 6 节逐条对照。 | 验证同一套布局和状态逻辑覆盖四个入口。 |

CodeGraph 使用 `codegraph_explore` 核对指数页面、共享图表、面板和范围相关符号。`codegraph_callers` 没有返回 JSX 调用方，已通过实际源码引用确认四个图表适配组件是运行时消费者，并核对其上层页面、测试、标签和响应字段。真实浏览器需要复核原始绘图区与底轴的尺寸，以及副图显隐前后的横向范围和位置。
