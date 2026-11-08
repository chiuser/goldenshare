# 股票和指数详情页副图显示与隐藏 LLD v1

> 2026-11-09。第 1–7 节保留原三项副图显隐的 Figma、实测和实现基线。[第 8 节](#quantitative-structure-lld)的量化结构与切周期首屏修复已通过管理员本机页面验收。原显隐规则见[实施方案 R1～R6](./detail-chart-indicator-panel-visibility-implementation-design-v1.md#1-交付范围)，底轴和浏览范围沿用[共享图表 LLD](./detail-chart-zoom-low-level-design-v1.md)。

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

<a id="quantitative-structure-lld"></a>

## 8. 量化结构详细设计

依据[量化结构需求](detail-chart-quantitative-structure-requirements-v1.md)和[实施方案第 7 节](detail-chart-indicator-panel-visibility-implementation-design-v1.md#quantitative-structure-plan)。本节只涉及股票、指数详情页和共享图表的前端展示。识别、下一根预判、普通行情、权限及持久化均使用现有接口和来源。

### 8.1 代码落点与调用

| 落点 | 本轮职责 |
| --- | --- |
| `IndexDetailPage.tsx`、`useDetailChartIndicatorControls.ts`、`DetailChartIndicatorToggle.tsx` | 步骤 1。页面给出可用状态和提示回调。共享开关管理三栏，复用标签样式。股票页继续用同一个开关，采用默认不可用状态。 |
| `StockChartWorkspace.tsx`、`StockMinuteChartWorkspace.tsx` | 步骤 1。在 KDJ 标签后插入占位按钮，股票接口的指标标签清单继续按现有方式消费。 |
| `detailChartTypes.ts`、`DetailChartWorkspace.tsx`、`detail-chart-workspace.css`、`detailChartIndicatorRange.ts` | 步骤 1 定义副图键。步骤 2 接入可选副图输入，复用 MACD 的两线一柱和轴样式，并参加现有横向联动。 |
| `IndexChartWorkspace.tsx`、`IndexMinuteChartWorkspace.tsx`、`XxmLayerUi.tsx` | 步骤 3。在 KDJ 后接标签，按时间读取现有识别结果，把读数、状态和标记接入新副图。悬停摘要跟随该副图显隐。 |
| `useIndexXxmLayer.ts`、`xxm/types.ts` | 页面与识别 hook 共用现有五个周期的判断。hook 的就绪条件、请求、重试和数据返回继续按现行方式工作。 |
| `xxm/adapter.ts`、`xxm/adapter.test.tsx` | 数值比较移除已完成，见 §8.3。后续副图使用现有 `byTime`，无需修改这两个文件。 |

现行 `macdPrimitives` 的两个生产调用方都是指数图表，本轮迁移到量化结构的图层输入。更新直接使用共享参数的页面、图表及 debug 测试。采用 `codegraph_explore` 核对四类图表入口、共享开关、识别 hook 和适配器，再从源码核对 JSX 调用方和测试。识别适配器保留现有参数签名。真实浏览器需复核现有绘图区、底轴及新增标签在两档既有视口下的布局。

### 8.2 标签、名额和切换

1. 在 `detailChartTypes.ts` 新增副图键 `quantitativeStructure`。`useDetailChartIndicatorControls(tsCode, quantitativeStructureAvailable = false, onLimitReached?)` 返回原有 `hiddenIndicatorPanels`、`onToggleIndicatorPanel` 和 `quantitativeStructureAvailable`。指数在 `IndexDetailPage` 获取当前图表周期和原识别能力后调用。股票沿用现有单参数调用。
2. 指数可用条件为现有 `recognitionEnabled` 为真，且当前周期为 `day/m30/m60/m90/m120`。分钟还要求原 `supportsMinute` 为真，并以当前已加载分钟图的标的和频率为准。`xxm/types.ts` 将 `useIndexXxmLayer` 当前五个周期提成一处判断，页面和 hook 共用。识别请求的加载失败和滞后只影响副图内的显示状态。
3. `DetailChartIndicatorToggle` 增加可选的 `mode`，默认 `available`，走原 `aria-pressed`、高亮和点击处理。量化结构在指数未开通时传 `disabled`，显示置灰的原生禁用按钮。股票传 `placeholder`，显示未点亮的可聚焦按钮并省略点击动作。指数日线直接插到 KDJ 后。股票日线在 `StockIndicatorBar` 遍历到 KDJ 时紧接插入，两个分钟入口通过 `DetailChartIndicatorToggles` 在三项之后追加。现有成交额、主图指标及研究控件的顺序照旧。

共享开关在原页面生命周期内管理选中的副图键。默认选择 `volume`、`macd`、`kdj`。用当前有效选择派生标签高亮、隐藏集合和计数，禁止从 DOM 或请求状态反推。点击时在同一次状态更新中按以下顺序判断。

| 当前状态及点击 | 处理 |
| --- | --- |
| 禁用或占位 | 不进入开关处理。 |
| 当前已展示该项 | 关闭该项。 |
| 当前未展示该项且已有三栏 | 保留当前选择，记录一次拒绝。状态提交后用现有页面 Toast 提示「最多展示3个技术指标，请取消一个后再打开」。 |
| 当前未展示该项且少于三栏 | 打开该项。 |

用原 `useState` 的函数式更新完成计数和显隐。每次点击在更新前生成一个标记，仅在满栏拒绝时写入状态。由提交后的效果用标记判重并调用 `onLimitReached`，状态更新函数内不弹提示。`IndexDetailPage` 复用 `showToast` 和 `IndexDetailToast`。沿用当前提示时长，新的手动提示替换前一次手动提示计时，页面退出时清理计时。测试断言连续点击第四项时，新提示不会被旧计时器清掉。 [现有提示代码](../../src/pages/index-detail/IndexDetailPage.tsx)

同一标的在支持周期之间沿用选择。暂时切到不支持的周期时，量化结构不显示也不计入名额，返回支持周期时恢复之前的选择。如果期间用户开启了第三个普通副图，则同时清除待恢复的量化结构选择，避免返回时挤掉一个普通副图。标的变化及刷新回到默认。已有行情加载和失败页面继续由各图表入口管理。

### 8.3 首批识别结果的使用

1. 指数日线从 `IndexChartWorkspace.initialPoints` 取首次窗口。普通日线向左追加的 `points` 只用于图表横轴，不能进入识别请求。既有日线波段核对使用当前核对图的初始窗口，其独立图层、控件和悬停继续走原入口。
2. 指数分钟线沿用当前普通 K 线及指标加载顺序。继续由 `IndexMinuteChartWorkspace` 把现有图表点和分钟指标版本传给 `useIndexXxmLayer`，由现有就绪条件发起识别。副图显隐只改变显示。
3. 日线继续请求 `xxm-signals`，分钟继续请求 `minute-xxm-signals`。沿用首尾日期、实际根数、周期、标的及 debug 参数，以及当前请求身份、调度、取消、缓存、超时和重试处理。 [现有识别请求](../../src/features/index-detail/xxm/useIndexXxmLayer.ts)
4. `decodeXxmResponse` 沿用现有检查。`buildXxmViewModel` 保留现有参数、时间、收盘、标的、周期和版本核对。按管理员确认删除普通 DIF、DEA 和柱值与识别值的数值比较，适用于日线及原支持的四个分钟周期。本步只改适配器中的这一项检查和相应测试，复用原输入、请求时机及错误处理。额外请求和数据写入均为零。复验继续使用相同的回归样本和现有上证日线页面。 [已核实的上证日线差异](../pages/index-detail/index-detail-low-level-design-v1.md#sse-daily-kline-step-2-result)
5. 沿用适配器的 `byTime` 取同一识别点的 `dif/dea/hist`、摘要及 debug 详情。仅按 `displayOnChart` 选取公开标记，仍用识别 DIF 作为纵向位置。 [识别回包](../../../src/biz/schemas/wealth/market/index_detail_xxm.py)

数值比较已移除。日线及四个分钟周期回归通过。本机上证日线的两条现有接口各返回 500 根，前端用实际回包生成识别结果及悬停内容。2024-09-24 普通 MACD 柱值 `20.64484765453068` 与识别柱值 `20.645` 均保留。浏览器连接超时，本次实际回包验证覆盖前端适配和组件渲染。

### 8.4 共享图表与悬停

#### 8.4.1 共享输入

`detailChartTypes.ts` 中的共享组件输入如下。共享层只认识三个绘图值及按时间读取的函数。现有 `points`、`panelAriaLabels` 和 `renderPanelHeader` 继续服务主图与原三栏。

```ts
type DetailChartMacdValues = Pick<DetailChartPoint, "macd" | "dif" | "dea">;

interface DetailChartQuantitativeStructure {
  ariaLabel: string;
  valuesAt: (time: DetailChartPoint["time"]) => DetailChartMacdValues | null;
  primitives: readonly ISeriesPrimitive<Time>[];
  renderHeader: (values: DetailChartMacdValues | null) => ReactNode;
}

// DetailChartWorkspaceProps 的可选输入
quantitativeStructure?: DetailChartQuantitativeStructure;
```

内部图表键和 `hiddenIndicatorPanels` 增加 `quantitativeStructure`，原三栏标题回调仍只接受 `macd/volume/kdj`。新栏标题调用自己的 `renderHeader`。接线完成时删除共享组件旧的 `macdPrimitives` 输入及普通 DIF 上的识别图层接线，两个指数调用方一并迁移。

#### 8.4.2 建图、更新与布局

| 现有代码位置 | 接入方式 |
| --- | --- |
| `DetailChartWorkspace` 的图表宿主及 `createPaneChart` | 可选输入存在时，在普通 MACD 宿主之后放一个 `quantitative-structure-panel`。进入工作区时创建一次，使用 MACD 的建图选项，不显示额外底轴。创建依赖只读可选输入是否存在，显隐和识别回包不作为重建条件。 |
| `setMacdData`、DIF、DEA 序列 | 复用普通 MACD 的柱色、线色和价格格式。新栏三条序列的值都从 `valuesAt(point.time)` 取。DIF、DEA 使用现有 `buildLineData`，在无识别值的 K 线上保留空时间点。柱值继续用 `buildHistogramData`，有效的 `0` 正常绘制。原三栏仍用原行情点。 |
| `applyIndicatorRanges`、`detailChartIndicatorRange.ts` | 给现有范围计算增加可选的字段取值回调，省略时仍读普通行情点。新栏传 `MACD_RANGE_FIELDS` 和自己的取值回调，使用自己的三组值算纵轴和刻度，复用原有空值、退化范围和轴线样式。 |
| 识别回包及清理 | 在现有图表运行对象上提供新栏更新入口。`valuesAt` 更新时仅重装新栏序列及纵轴，沿用当前可见范围。设置新栏数据时使用现有范围同步保护，避免它把范围变化传给主图。识别图层沿用旧的挂接、变更和清理方式，改挂新栏 DIF。退出工作区时由现有清理流程退订并释放新栏。 |
| `updateHistory` | 普通日线左插 K 线时，用合并后的 `plottedPoints` 同步新栏时间点，历史部分按 `valuesAt` 返回空。时间偏移和可见范围仍由原 `updateHistory` 统一提交，识别请求继续绑定 `initialPoints`。 |
| `charts`、`syncTargets` | 新栏接收共享横向范围，参加十字线和右侧轴宽同步。新栏的时间轴回调不参与写入其它栏。纵向读数从新栏自己的柱值取，无值按现有方式清除该栏的数值提示。日线仍由 KDJ 的横坐标生成日期轴，分钟仍使用 KDJ 原生底轴。 |
| `detail-chart-workspace.css` | 网格依次为主图、普通 MACD、量化结构、成交量、KDJ 与底轴共用的最后一行。新栏可见时用原 MACD 行高，缺席或收起时行高归零。收起时沿用原隐藏宿主和 `inert` 行为。底轴空间仍只留一次。 |

#### 8.4.3 指数页接线

1. `IndexChartWorkspace` 和 `IndexMinuteChartWorkspace` 沿用现有 `useIndexXxmLayer` 调用。可用时传入 `quantitativeStructure`，从 `xxm.data?.byTime.get(String(time))?.point` 取值，将回包 `hist` 传为绘图字段 `macd`。取值函数随识别结果更新，开关变化时复用同一个函数。没有识别点时返回 `null`。这份输入从可用图表初始化起存在，点灭只通过 `hiddenIndicatorPanels` 控制。
2. 新栏标题用「量化结构(12,26,9)」，复用对应日线或分钟的普通 MACD 标题读数渲染方式，依次显示 MACD、DIF、DEA。无值显示 `--`。将 `xxm.macdPrimitives` 交给新栏，将 `XxmLayerStatus` 及原重试动作移入新栏标题。普通 MACD 标题及三组指标值仍来自原行情。
3. 主图悬停在量化结构有效点亮、当前时间有识别点时渲染 `XxmSignalDetails` 和该识别点的 debug 详情。普通行情和独立波段核对悬停仍由原区域渲染。右侧 `useXxmForecast` 继续使用原技术面页签、环境和日期条件。

### 8.5 状态、预算与中断

识别副图继续复用 `XxmLayerStatus`。加载中显示现有加载文案。正常回包绘制当前有效窗口。空数据留空并显示现有暂无数据文案。滞后时绘制已有数据并显示来源截至时间。失败或超时留空并提供原重试入口。后端请求时限为现有 `4` 秒，前端识别调用时限为现有 `5000` 毫秒，超时继续使用「顶底识别加载超时，请重试」。未开通场景只有禁用标签。 [后端预算](../../../src/biz/services/wealth/market/index_detail_xxm/runtime.py) · [前端时限](../../src/features/index-detail/xxm/apiClient.ts)

| 动作 | 本轮增量边界及依据 |
| --- | --- |
| 首次加载可用的指数工作区 | 相比原工作区增加一个图表、两条线和一组柱。沿用原首批识别请求，普通上证日线和现有分钟页面的行情批次上限均为 500 根，`limit` 取实返根数。debug 继续使用其现有窗口。 |
| 标签开关、上限提示、禁用和占位 | 新增网络请求、图表创建和序列重装均为零。布局和尺寸观察沿用原工作区。 |
| 普通日线历史插入 | 每次由原行情分页加载实际历史根数。新副图三组序列按合并后的时间轴同步，识别请求增量为零，识别数值仍限于原首批。 |
| 失败重试、退出和中断后续验 | 手动重试一次只重发一次原首批识别请求。离开当前窗口取消待处理请求，下一次按已有缓存和窗口身份加载。验收中断后重开同样本和视口，只重复该页面一次原有首批请求流程。历史用例只复核现有普通续页。 |

本轮无后台写入、配置新增或迁移。撤回以整项前端改动为单位。以上为按现有流程和新副图数量推导的限制，浏览器验收登记实际请求及图表更新结果。

### 8.6 回归及真实页面验收

| 需求 | 自动化及真实页面用例 |
| --- | --- |
| 默认、名额、禁用与占位 | `IndexDetailPage.test.tsx` 覆盖默认三栏、关闭 KDJ → 打开量化结构 → 重开 KDJ 提示，连续点第四项时提示正常。指数日线、分钟组件测试核对 KDJ 后的标签和禁用状态。股票日线、分钟组件测试在满栏和未满时点击占位，确认无状态、提示及网络变化。 |
| 同一标的切周期 | `IndexDetailPage.test.tsx` 从打开量化结构的支持周期切到不支持周期再返回，验证原选择恢复。重复该过程，在不支持周期先开启第三个普通副图，再返回时保留普通三栏。换标的或刷新恢复默认。 |
| 独立取值及防止错绑 | `xxm/adapter.test.tsx` 覆盖日线和分钟线时间、收盘一致而普通 DIF、DEA、MACD 不同，识别点和标记仍取识别回包的回归。继续用已有反例验证标的、周期、版本、时间及收盘检查。 |
| 纵轴、标记及读数 | `DetailChartWorkspace.test.tsx` 和指数图表测试断言两图分别收到各自的线、柱和纵轴范围，合法零值绘制，缺值留空，标记只挂到量化结构的 DIF。普通行情的指标、主图图层及读数由原测试覆盖。 |
| 位置与悬停 | 测试四个入口的 KDJ 后置标签和指数新副图顺序。在同一有识别结果的时间开关量化结构，识别摘要及其 debug 详情随之显隐，行情和独立波段悬停可继续查看。右侧预判请求和内容仍由原技术面页签控制。 |
| 首批、续页及底轴 | 上证日线翻历史，断言普通历史可绘制且识别请求次数不增加，新副图历史部分只保留空时间点，首批标签不移位。两档原量测视口验证同时显示两组 MACD、隐藏 KDJ、收起新副图和全关时的底轴位置、缩放和十字线，记录显隐前后可见日期与根数。 |

真实验收直接使用本机页面及其实际接口回包。用上证指数 `tradeDate=2026-10-20` 的现有首屏，关闭 KDJ，再同时查看普通 MACD 和量化结构。对照 `kline` 回包的 `factors.macd.{dif,dea,macd}` 与识别回包的 `points.{time,dif,dea,hist}`。2024-09-24 的两组柱值按当前两位精度都显示 `20.64`，原始值由真实回包和序列输入断言核对，页面再核显示样式。用首批中 `displayOnChart=true` 的事件核对标记和悬停，左拖续页检查新增历史只有普通数据。分钟用上证 90 分钟的现有 r4.1 案例核对图层，切到 5 分钟验证指数标签置灰。股票使用 §6.1 的现有样本验收两个入口的占位。每个用例记录页面实际请求、对应时间和可见结果。 [日线已验收窗口](../pages/index-detail/index-detail-low-level-design-v1.md#sse-daily-kline-step-2-result) · [90 分钟案例](../../../docs/product/xxm-research-and-implementation-v0.6.md#xxm-current-handoff)

优先执行 `npm --prefix wealth run test -- detail-workspace stock-detail index-detail`。交付执行 `npm --prefix wealth run typecheck`、`npm --prefix wealth run test`、`npm --prefix wealth run build`。验收使用上面的实际页面流程，旧研究工具仅用于原研究目的。浏览器连接失败时如实记录，自动化用例和真实回包的组件渲染结果分别登记。

### 8.7 编码门禁矩阵

| 通用清单 | 适用性与落点 | 验证 |
| --- | --- | --- |
| §2.1 交付事实链 | 适用。原 Figma 和量测提供布局基线，新增行为来自已确认需求。管理员已确认按实施方案和本节开发。 | 核对三项拍板和三个文档的对应要求。 |
| §2.2 后端事实归一 | 适用。§8.3 直接消费识别及行情回包。 | 两组指标同时间对照。 |
| §2.3 状态机 | 适用。§8.2、§8.5 定义禁用、占位和识别状态。 | 正常、空、滞后、错误、超时与重试。 |
| §2.4 显示与数据绑定 | 适用。§8.4 分开读数、纵轴和标记。 | 对照真实回包与图形。 |
| §2.5 行为过程 | 适用。§8.6 定义开关、历史、悬停和切换。 | 页面测试及真实浏览器。 |
| §2.6 同轮同步 | 适用。需求、方案、LLD 和验收结果按同一范围对账。 | 实施后核对变更与证据。 |
| §2.7 渐进替换 | 数据源迁移不适用。前端切换范围及撤回见 §8.5。 | 核对改动边界和真实接口复用。 |
| §2.8 契约和消费者 | 适用。§8.1、§8.3 定义新增副图输入及前端校验范围，HTTP 合同沿用。 | 类型检查、四个页面入口和日线、分钟识别回归。 |
| §2.9 图表坐标 | 适用。§8.4 明确日期、分钟端点、独立纵轴和缺值。 | 日期索引、纵轴、底轴及同步断言。 |
| §2.10 计算与传输 | 适用。§8.5 按首批、续页和重试分别限定增量。 | 真实网络次数及既有时限。 |
| §2.11 配置 | 不适用。沿用环境和分钟能力。 | 检查相关配置与环境门禁。 |
| §2.12 清单映射 | 适用。本表逐条对应。 | 方案与 LLD 评审。 |
| §2.13 例外和语义断言 | 适用。例外白名单为空。 | §8.6 的正反用例。 |
| §2.14 图表参数 | 适用。§8.4 复用原 MACD 显示参数和轴样式。 | 样式及读数对照，缺值与零值断言。 |
| §2.15 并排双图 | 不适用。两图上下排列，各自使用本图数据的纵轴。 | 核对共享横轴及右侧轴宽对齐。 |
| §2.16 指标卡片文案 | 不适用。新增标签和副图标题。 | 浏览器核对窄侧标签条、标题与状态提示。 |
| §2.17 真实 API 与展示 | 适用。§8.6 给出字段清单和样本。 | 真实路由回包及页面读数、标记核对。 |
| §2.18 跨模块原则 | 适用。八条分别见下表。 | 评审与对应验收记录。 |

| §2.18 原则 | 设计及验证 |
| --- | --- |
| 单一事实源 | §8.3、§8.4。按实际回包核对普通 MACD 和量化结构。 |
| 契约先行 | §8.1、§8.3。确认四入口、现有 DTO 和日线、分钟识别校验。 |
| 配置一致 | §8.2。使用现有能力与页面内选择，核对开发和生产门禁。 |
| 默认明确 | §8.2。验证三项默认、指数禁用和股票占位。 |
| 顺序确定 | §8.2、§8.4。核对标签、副图及时间顺序。 |
| 性能预算 | §8.5。核对请求、实例、序列更新与续验边界。 |
| 状态与异常 | §8.3、§8.5。核对错误隔离、重试、过期响应和现有文案。 |
| 用户可见结果 | §8.6。核对位置、显隐、读数、标记、底轴和悬停。 |

### 8.8 编码顺序与复验

1. **接标签和名额。** 按 §8.2 实现共享开关、指数提示和股票占位。先通过页面选择测试。指数可用标签在步骤 3 随副图接通。
2. **增加可选副图。** 按 §8.4.1–§8.4.2 修改共享类型、图表和布局。先在 `DetailChartWorkspace.test.tsx` 用可控绘图值验证两栏序列、纵轴、宿主顺序、开关与历史时间点。
3. **接上现有识别结果。** 按 §8.3 和 §8.4.3 同步修改指数日线和分钟入口，迁移旧的图层接线。更新两个图表适配测试及引用相同参数的页面和 debug 测试。四个入口全部接通后，逐项回归原副图、预判和独立波段核对。
4. **自检与交接。** 开发侧按 §8.6 执行自动化检查并登记结果。管理员按该节在真实页面验收。中断时从未通过的用例继续，复验使用同一页面及原请求窗口。需要撤回时撤回本轮副图和标签改动，已完成的数值比较移除作为独立修改保留。

### 8.9 开发自检结果

2026-11-08 在仓库外的临时测试目录复用已有依赖，完成以下检查。

| 检查 | 结果及覆盖 |
| --- | --- |
| `npm --prefix wealth run test -- detail-workspace stock-detail index-detail` | 55 个文件、673 项通过。包含三栏上限、周期切换、股票占位、独立序列与纵轴、标记与悬停、首批识别请求和普通历史续页。 |
| `npm --prefix wealth run typecheck` | 通过。覆盖四个图表入口和共享副图输入。 |
| `npm --prefix wealth run test` | 187 个文件、1636 项通过。 |
| `npm --prefix wealth run build` | 通过，仍有构建的包体积提示。 |

测试用识别回包样本驱动识别适配器及图表接线，断言普通 MACD 和量化结构的取值、标记及首批请求边界。真实接口回包与浏览器画布的展示核对按 §8.6 由管理员验收。

### 8.10 切周期后的首屏位置修复

本机上证详情切到 90 分钟后右端显示 2026-05-18 15:00，切回日线后显示 2025-05-28。向近期拖动日线可到 2026-11-06，5 分钟首次显示也到 2026-11-06 15:00。量化结构在等待识别结果时已有 K 线时间点，图表库以最后一个有值的点为基准计算显示范围。序列还没有值时，它发出的范围偏早，被共享图表同步给了主图。标签收起时图表实例仍在，因此同样受影响。

在 `DetailChartWorkspace` 中保留量化结构接收横向范围的逻辑，跳过该栏向其它图表发布范围的订阅。共享拖动、缩放、日线续页和识别回包后的新栏定位继续沿用原实现。修改只涉及前端范围同步，新增请求、实例和数据写入均为零。失败或中断后沿用原页面重开复验，无额外数据读取步骤。

自动化回归模拟新栏发出的偏早范围，检查日线及分钟主图仍在最新一根，并验证用户缩放仍同步到新栏。两项用例修复前失败，修复后通过。共享图表 113 项、Wealth 全量 1638 项、类型检查和构建均通过。

本机真实页面复测，首次日线右端为 2026-11-06，切到 90 分钟为 2026-11-06 15:00。打开量化结构后 90 分钟右端仍为 2026-11-06 15:00，保持开启并切回日线，右端仍为 2026-11-06。

2026-11-09，管理员确认本轮本机页面验收通过，并授权提交。
