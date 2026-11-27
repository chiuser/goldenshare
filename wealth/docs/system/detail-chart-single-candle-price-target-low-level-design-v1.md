# 股票和指数详情页单阳测顶、单阴测底 LLD v1

> 2026-11-27。产品交互和 LLD 已确认。编码前先核对股票、指数的真实日线样本，实施后运行回归并完成真实页面验收。

依据为[实施方案](./detail-chart-single-candle-price-target-implementation-design-v1.md)和[已确认的 Figma R1](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2307-79)。本期交付两个详情页的日 K 测算入口、共享弹窗、股票底部占位标签清理。股票日线前复权、指数点位、接口鉴权、图表与指标图层沿用现行数据和实现。范围为 Wealth 前端及交付文档，不涉及后端契约、子系统依赖、行情源、数据库或 Lake 写入。

## 1. 已确认的设计与开发约束

| 编号 | 已确认要求 | 验证 |
| --- | --- | --- |
| R1 | 股票和指数只有可用的日 K 图表在底部显示「单阳测顶」，位置在日期轴下方的指标栏末尾。入口为未选中指标的透明底、无可见外框文字样式。 | T1、B1 |
| R2 | 点击打开当前标的的弹窗。初始选中「单阳测顶」，日期留空。按所选测算目标切换标题。标的名称在标题右侧的居中位置，代码在名称下方、字号更小。 | T2、B1 |
| R3 | 所有指数测顶 `0.90`、测底 `1.10`。所有个股测顶 `0.85`、测底 `1.15`。切换目标恢复对应默认值，同一目标换日保留手填系数。点击「计算」使用当前输入。 | T2、T3、T6 |
| R4 | 用户手选交易日和测算目标。行情读取只按选定日期触发，日线存在才使用。所选日的开、高、低、收、涨跌幅和上一根日 K 的日期、收盘价可见。股票两根 `close` 和图表都用现有前复权价格。 | T4、T5、A1、A2 |
| R5 | 计算按钮在左，结果在右单行。标签、数字、单位垂直居中，测顶数字红、测底数字绿。状态、日期或输入变化清理旧结果。 | T3、T6、B1 |
| R6 | 删除股票底部的 11 个现有占位标签，保留可用指标、现有周期能力及指数标签行为。弹窗操作保持日 K 时间轴、缩放、可见范围、副图和图层状态。 | T1、T7、B1、B2 |
| R7 | 换日、关闭、路由标的变化时取消旧请求，晚到回包不能改写现有弹窗。失败可手动重试当前日期。当前无业务写入和参数持久化。 | T4、T5、B2 |

## 2. 当前实现与代码落点

用 CodeGraph `codegraph_explore` 核对两页装配、日 K 和分钟工作台、底部指标栏、日线客户端及两条 API 入口。以当前源码复核 JSX 调用方、测试、鉴权重放、前复权字段和图表更新依赖。审计时指数日线组装有并行工作区改动，本文依赖既有普通路由、字段及消费者。实施前在届时基线上复核 §3 的请求和回包，不将本审计中的并行源码变更纳入本期。

| 已核实位置 | 实施动作与边界 |
| --- | --- |
| [StockDetailPage](../../src/pages/stock-detail/StockDetailPage.tsx) 的 `activePeriod === "day"` 分支、周月分支和分钟分支 | 只向日 K 分支传入打开弹窗的操作。弹窗作为图表工作台的兄弟节点挂载，页面负责当前 `viewModel.stock` 与弹窗打开状态。周月分支共用 `StockChartWorkspace`，校验 `period` 为 `day` 且存在打开回调才渲染按钮。 |
| [IndexDetailPageView](../../src/pages/index-detail/IndexDetailPageView.tsx) 按实际 `chartPeriod` 装配 `IndexChartWorkspace`、`IndexPeriodChartWorkspace` 和分钟工作台 | 只给日 K 分支传入打开回调，从当前 `viewModel.identity` 带标的。`IndexIndicatorBar` 被日 K 与周月线共用，只在日 K 调用点传入该回调。普通和 debug 页面共用图表装配，测算读取普通日线接口，避免误用 debug 页注入的 `loadDailyKline`。 |
| [StockChartWorkspace](../../src/features/stock-detail/chart/StockChartWorkspace.tsx) 的 `StockIndicatorBar`、[股票标签常量](../../src/features/stock-detail/model/stockDetailConstants.ts)、[真实适配器](../../src/features/stock-detail/api/stockDetailViewModelAdapter.ts)及[模拟适配器](../../src/features/stock-detail/api/stockDetailMockAdapter.ts) | 在常量清除 10 个无功能条目，保留当前面板及叠加功能。股票日周月工作台移除 `KDJ` 后的「量化结构」占位，九转保留在原分支。删掉底栏仅用于占位的提示分支；工作台用于「指标设置」的 `onAction` 仍按原路径调用。相关两个适配器共用一份标签来源。 |
| [StockMinuteChartWorkspace](../../src/features/stock-detail/chart/StockMinuteChartWorkspace.tsx) 和[共享指标开关](../../src/shared/charts/detail-workspace/DetailChartIndicatorToggle.tsx) | 股票分钟底栏用既有单项开关渲染 `VOL`、`MACD`、`KDJ` 和原九转，移除股票的「量化结构」占位。指数端的量化结构可用、禁用及分钟显示逻辑仍由原代码处理。 |
| [DetailChartWorkspace](../../src/shared/charts/detail-workspace/DetailChartWorkspace.tsx) 的 `bottomBar` 和[指标栏 CSS](../../src/shared/charts/detail-workspace/detail-chart-workspace.css) | 使用 `bottomBar` 的既有位置和 `.detail-chart-indicator-tab` 基础类。入口是普通按钮，无 `active` 类与 `aria-pressed`。弹窗的数据、选日和计算结果不作为图表 `dataKey`、序列、可见范围或副图开关的输入。 |

股票删除清单为**成交额、大单净量、主力密码、融资融券、陆股通资金、陆股通持股、AI机构活跃度、资金抄底、资金仓位、更多、量化结构**。`VOL` 实际由 `STOCK_INDICATOR_PANELS` 渲染，原常量的 `supported: false` 不能作为删除依据。其他时段的已实现指标按钮、股票悬停行情里的成交额、指数指标栏和右栏均使用各自原入口。

在 `wealth/src/features/single-candle-price-target/` 内实现共用逻辑，文件落点如下。表中的新文件名属于本次实施位置。

| 文件 | 责任 |
| --- | --- |
| `singleCandlePriceTarget.ts` | 标的类别、测算目标、本期默认系数表、日线事实选择、系数判定、纯公式及本模块的数值格式化。两页和弹窗消费同一份定义。 |
| `singleCandlePriceTargetQuote.ts` | 复用两个日线 API 客户端，读当前标的和所选日，用同一组原始 DTO 值构造弹窗所需视图输入。消化 API 客户端差异，调用方只传标的、日期和 `AbortSignal`。 |
| `useSingleCandlePriceTarget.ts` | 弹窗内的选日、输入值、行情请求生命周期和结果变化，取消旧请求。页面只负责打开、关闭和标的归属。 |
| `SingleCandlePriceTargetDialog.tsx`、`single-candle-price-target.css` | 共享表单、行情区、结果行与视觉状态。沿用[现有对话框模式](../../src/features/trading-assistant/ui/TradingAssistantForm.tsx)的原生 `dialog`、Esc 和焦点处理，样式使用全局设计变量。 |

两页传 `{ kind: "stock" | "index", tsCode, name }` 与 `onClose`。日 K 工作台只接收可选的打开回调，点击时把按钮元素传给页面，供关闭后恢复焦点。日 K 已卸载时跳过焦点回传。页级打开状态按当前标的标识校验，周期离开日 K、换标的或离开页面就结束本次测算。弹窗渲染、请求及输入逻辑落在独立文件，页面编排遵守现有 400 行限制。

## 3. 日线请求和字段合同

| 类别 | 现有请求 | 使用的回包字段 |
| --- | --- | --- |
| 股票 | `fetchStockDetailKline({ tsCode, period: "day", adjustment: "forward", endDate, limit: 2 }, { signal })` | `stockRef.tsCode`、`period`、`adjustment`、`sourceAdjustment`、`bars[]`、`dataStatus`。`adjustment="forward"` 与 `sourceAdjustment="qfq"` 已由现行类型和服务定义。 |
| 指数 | `fetchIndexDetailKline({ tsCode, period: "day", endDate, limit: 2 }, { signal })` | `indexRef.tsCode`、`period`、`bars[]`、`dataStatus`。指数请求无复权参数。 |

两个客户端分别读取 `/api/v1/wealth/market/stock-detail/kline` 和 `/api/v1/wealth/market/index-detail/kline`。`endDate` 直接使用日期输入的 `YYYY-MM-DD`，无时区转换。股票这次请求不传 `tradeDate`、`startDate` 或 `debug`，不进入带 `tradeDate` 的本地分页／首屏 `quote` 路径。指数不传 `startDate`。两条日线请求不依赖图表缓存、历史翻页、技术指标是否齐全或页面右栏快照。

股票路由由 `get_stock_detail_kline` 构造 `StockDailyKlineRequest`，日线验证允许 1–500 根，`work` 在当前环境调用现有价格读取与回包装配。指数由 `get_index_detail_kline` 进入 `query_kline_response`，解析后复用现有日线分支，`limit=2` 属现行范围。两路仍调用 `require_quote_access`。不新增后端路由、参数、错误码或前端专用代理。 [股票路由](../../../src/biz/api/wealth/market/stock_detail.py) · [股票日线调用](../../../src/app/dependencies/stock_daily_technical_indicators.py) · [指数路由](../../../src/biz/api/wealth/market/index_detail.py) · [指数日线查询](../../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py)

| 可见字段 | 绑定规则 |
| --- | --- |
| 证券名称、代码 | 详情页已解析的当前标的。请求生命周期检查返回的 `stockRef.tsCode` 或 `indexRef.tsCode` 对应当前标的以及 `period=day`。 |
| 当日交易日、开盘价、最高价、最低价、收盘价、涨跌幅 | 从 `bars[]` 唯一取 `tradeDate === endDate` 的日线，依次展示 `tradeDate`、`open`、`high`、`low`、`close`、`changePct`。字段空时按现有格式 `--` 展示，`changePct=0` 正常显示。保留涨跌幅原值与其符号。 |
| 前一交易日与前一交易日收盘 | 同一 `bars[]` 中 `tradeDate < endDate` 的最近一根日 K，对应 `tradeDate` 和 `close`。两根按日期选择，取不到所选日时忽略回包中的旧行情。停牌无日 K 的日期和非交易日自然跳过。 |
| 股票行情卡标识、目标价、目标点位 | 股票行情区标「前复权」，取两根 `close` 计算前复权目标价，单位元。指数用两根指数点位计算目标点位，单位点。两种结果都仅由日线事实与本次用户系数生成。 |
| 状态和传输错误 | 回包 `dataStatus.status/expectedTradeDate/observedTradeDate` 用于核对回包，用户选日以 `bars[].tradeDate` 精确匹配。HTTP 或客户端失败使用行情读取失败状态。指数因辅助技术指标缺失标为 `PARTIAL` 但两根 `close` 完整时仍可计算。 |

`C1` 从上一根 `close` 取值。股票组装同时读前复权价格与已有行情的 `preClose`，这两个字段可能处在不同价格基准上。现有前复权使用 `latest_available_factor`，两根日线在同一个应答里完成，实际验收把测算请求和详情页同日期的前复权日线相互核对，覆盖除权日。 [股票回包装配](../../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py) · [股票字段映射](../../../src/biz/services/wealth/market/stock_detail/stock_detail_field_mapper.py) · [Prod 日线复权基准](../../../src/foundation/clients/technical_indicator_postgres.py) · [DG 日线复权基准](../../../src/foundation/clients/local_lake/technical_indicator_price_locator.py)

系数保留为用户输入字符串，默认值按产品已定的两位小数显示。使用可编辑数字输入框，允许小数，校验有限且大于零。输入合法且两个日线收盘价均可用于公式时，`calculatePriceTarget(C, C1, K)` 计算 `C * C / (C1 * K)`。两个收盘价需为有效正价格，结果应为有限正数。公式输入使用原精度，输出用本模块格式化为两位小数和必要的千位分组。行情涨跌幅复用 `formatSignedPercent` 和行情涨跌语义，底部结果颜色单独按用户选择的测算目标决定。当天涨跌方向、大小和兑现走势均不参与限制，正常小阳或小阴同样可算。 [股票前端 DTO](../../src/features/stock-detail/api/stockDetailApiTypes.ts) · [指数前端 DTO](../../src/features/index-detail/api/indexDetailApiTypes.ts) · [行情格式化与方向](../../src/shared/lib/formatters.ts)

## 4. 弹窗状态、事件与失效

弹窗挂载时初始化为 `target=top`、日期为空、类别对应默认系数、行情空闲、结果为空。行情状态和表单结果分开。一个日期请求只负责填入行情和读取状态，计算只由用户按按钮触发。

| 事件／状态 | 状态变化和用户可见结果 |
| --- | --- |
| 打开／未选日 | 标题「单阳测顶」，行情卡提示「选择交易日后查看行情」，结果「—」，计算禁用。打开时聚焦交易日输入框，等待用户选日。 |
| 选定新日期 | 立即清理旧行情及结果，取消上一日期的请求。进入读取状态，提示「正在读取日线行情…」。同一目标下保留系数。清空日期回到未选日，取消现有请求。 |
| 成功且命中所选日 | 展示对应行情。`C`、`C1` 都有效时可按有效系数计算，未计算前显示「—」。上一根缺失提示「缺少前一交易日收盘价」，所选日 `close` 不可用提示「缺少所选交易日收盘价」。其他已返回行情正常显示。 |
| 成功但未命中所选日 | 文案「所选交易日暂无日线行情」，日期仍是用户的选择，保持计算禁用。旧日 K、快照和相邻交易日均不替换所选日。 |
| 读取失败 | 文案「日线行情读取失败」，显示「重试」。重试同一日期，清理失败和旧结果，返回读取状态。取消请求仅结束其生命周期，不展示失败。 |
| 切换测算目标 | 同步切换标题、选择控件和该目标默认系数，清空已计算结果。所选日、已读行情和在途的同日请求保持。重复点当前目标不视为切换。 |
| 修改系数或点击计算 | 系数变动后清空结果。无效输入提示「请输入大于 0 的有效系数」。有效时点击计算显示结果，异常不可表示的计算结果提示「测算结果超出可显示范围」，不显示旧结果。无输入变化时允许同值重复计算。 |
| 关闭、换标的、离开日 K 或页面卸载 | 终止当前请求与弹窗状态，入口仍存在时恢复焦点。重开重新初始化，不复原旧系数、日期或结果。 |

每次实际选日／手动重试创建新的请求实例及自己的 `AbortController`，在取消时同时使旧实例失效。只有当前有效实例、当前标的及同一所选日期的响应可提交行情状态。即使 `fetch` 或鉴权重放在取消之后返回，旧响应也不能更新弹窗。目标切换、系数调整和点击计算不重发请求。关闭按钮、Esc、路由切换、工作台不再显示日 K 都走同一个清理路径。

## 5. Figma 细节和图表行为

| 区域 | 已确认口径及实现 |
| --- | --- |
| 底部入口 | Figma 的[股票](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2307-1660)和[指数](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2307-1662)入口均为 `58 × 24 px`，和同栏未选中标签相同。实现复用现有 `24px` 高度、`11px` 字号和左右 `7px` 内边距，不额外固定按钮宽度。是打开弹窗的按钮，具备键盘焦点及对话框语义，点击不会占用副图数量。 |
| 弹窗标题区 | 桌面画板宽 `552px`。标题 `16px` 靠左；名称 `13px`、代码 `11px` 叠放在标题右边的居中位置；关闭按钮靠右。标题、标的块与关闭按钮在垂直方向居中，居中区域两侧布局对称。关闭与标题动态更新沿用同一语义标题。 |
| 表单和行情 | 「测算目标」、交易日、测算系数和「日线行情」的顺序、暗色表面及激活色按现有设计变量。未选日、加载、无行情、失败与重试分别对照 Figma `2308:451`、`2308:1159`、`2308:1216`、`2308:1273`。可编辑系数和真实日期由产品表单承接。 |
| 结果行 | 左「计算」，右结果。结果标签 `12px`、数字 `20px` 等宽加粗、单位 `13px`，三段同一行、按垂直中心对齐。测顶数字取 `--cs-color-market-up`、测底数字取 `--cs-color-market-down`；标签和单位取中性色。无结果显示「—」并省略单位。 [股票测顶画板](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2308-568) · [指数测底画板](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2308-1098) |

桌面弹窗宽度、字号和入口高度来自已确认画板或现有 CSS。窄视口按可用宽度限制弹窗并允许内容滚动。结果容器可收缩，内侧保持单行和字号，长结果可在结果区横向查看，计算按钮固定在左。沿用 Wealth 字体和[设计变量](../../src/styles/design-tokens.css)，维护明显的键盘焦点。弹窗操作后原图表实例、可见范围及选中指标应保持。用同一个非默认缩放和图层组合做打开前、计算后、关闭后的几何和行为对照。

## 6. 性能、失败与续跑

| 操作 | 新增行情调用与返回预算 |
| --- | --- |
| 首屏、打开、清空日期、切换目标、修改系数、计算、关闭 | 0 次日线客户端调用。弹窗关闭时取消已有请求。 |
| 每次选定日期／手动重试 | 1 次对应日线客户端调用。正常会话 1 次 HTTP 行情 GET，成功返回最多 2 根日 K。 |
| 会话过期 | 复用 `wealthFetch` 的现有 401 刷新语义。单个逻辑请求最多多 1 次行情 GET 重放，鉴权刷新由既有机制按会话共享，单独记录。没有新增行情自动重试。 |
| 取消后继续、最终验收 | 可重新打开并选择同一日期，按一次新的逻辑请求计。设验收实际选了 `N` 次日期、手动重试 `R` 次，正常鉴权新增行情调用 `N+R`，成功回包合计最多 `2 × (N+R)` 根。既有页面首屏、正常换周期请求及鉴权流按网络记录分开。 |

`limit=2` 约束回包，不代表后端只读取两行。技术指标预热按现有日线路径。走算子执行控制的分支以当前运行配置为准，仓库默认总目标 `8,000 ms`，其中清理预留 `2,000 ms`，默认工作期限在到达请求后 `6,000 ms`。该配置适用于当前技术指标执行控制，不作为其余指数查询路径或前端的实测承诺。弹窗复用当前行情客户端与取消机制，暂不设额外前端超时。浏览器验收分别记下 HTTP 状态、耗时、响应体大小、鉴权重放与错误文案。发现已有日线接口不满足第 3 节时先定位环境与调用差异。 [鉴权客户端](../../src/shared/api/wealthApiClient.ts) · [算子默认配置](../../../src/foundation/config/settings.py) · [请求期限计算](../../../packages/technical_indicators/src/goldenshare_technical_indicators/execution_control.py)

中断只丢失当前弹窗状态，可重新选同一日；不存在持久化进度或业务写入。运行失败时重试只读当前标的和所选日，图表继续按原数据工作。发布后若入口、图表或正反用例出现回归，撤回本功能对应前端改动并重跑 §7 既有浏览器用例。

## 7. 测试和验收

夹具使用第 3 节的现行回包类型。历史行情示例为独立字面值；不调用待测公式来生成预期。下面的测试均待实施。`A` 为接口用例，`B` 为真实 API 驱动的页面验收，`T` 为单元或组件／页面测试。

| 用例 | 放置与通过条件 |
| --- | --- |
| T1 入口与股票清理 | `StockDetailPage.test.tsx`、`IndexDetailPage.test.tsx`，以及股票日周月、股票分钟、指数日线图表组件测试。日 K 可打开「单阳测顶」；切周、月、分钟、分时无入口；切回日 K 恢复。股票按已列 11 项断言不在底部 DOM，`VOL` 等真指标仍可切换，悬停成交额仍存在。指数的成交额、量化结构、九转与图层沿用原断言。 |
| T2 初始化和输入 | 共享弹窗测试。四个系数分别断言，并用两个不同股票、两个不同指数证明同类别一致。未选日按钮禁用且无行情读取。切换方向同步改变标题和系数；同方向换日保留手填；关闭重开清空。用手填 `1` 触发计算，确认使用现值。 |
| T3 计算和颜色 | 模型及弹窗测试。`C1=100, C=105` 指数测顶 `122.50`、个股测顶 `129.71`；`C1=100, C=95` 指数测底 `82.05`、个股测底 `78.48`；首组 `K=1` 为 `110.25`。用对象不同涨跌方向和小阳／小阴确认可计算，结果色只由测算目标控制。检验两位小数、千位分组、元／点和切换后清空。 |
| T4 日期及字段边界 | API 适配与弹窗测试。请求断言代码、所选 `endDate`、`period=day`、`limit=2` 及股票前复权参数。两根各用不同 `tradeDate` 和值，断言五个当日行情字段、前收日期与收盘逐项对应。`preClose` 刻意与上一根 `close` 不同，确认不被使用。周末／停牌选中日期无匹配、仅一条日 K、缺 `close`、`changePct=0`、技术因子 `PARTIAL` 但价格有效各有断言。 |
| T5 请求、晚到和失败 | 弹窗用可控请求覆盖 A 日后连选 B 日，A 迟到、取消、关闭、换标的及离开日 K。失败时「重试」使用原日期。点开／改目标／输入系数／计算无新增日线调用。现有鉴权重放由客户端原测试覆盖，测算请求继续传 `signal`。 |
| T6 非法系数和结果清理 | 验证空、零、负、非有限系数及结果不可表示。可用的正小数正常计算。修改日期、目标、系数后清除旧结果，单位同步留空。 |
| T7 图表与键盘回归 | 检查键盘可打开、Esc 或关闭按钮使焦点回到来源，点测算前后副图数量、选中项和图表加载调用一致。已有挂载计数或浏览范围测试如需扩充，仅增加本次入口的行为断言。 |
| A1 股票真实路由 | 在普通股票详情日线 HTTP 路由发 `{tsCode, period=day, adjustment=forward, endDate, limit=2}`，核对 §3 的身份、周期、价格口径、日期、OHLC、涨跌幅、前一根 `close` 与状态。选一个有界历史除权样本，核对同接口两根及详情页同日期前复权价格。用可核实停牌的复牌日验证前一根实际交易日。 |
| A2 指数真实路由 | 在普通指数详情日线 HTTP 路由发 `{tsCode, period=day, endDate, limit=2}`，各核对一个上证指数和另一个产品支持的指数，按 §3 核对同一组字段、恰当日期与单位。尝试一个已核实的休市日，无精确当日日线时按为空处理，允许服务返回此前日线。 |
| B1 两页真实展示 | 用真实行情响应驱动浏览器，按 A1/A2 的当日和前一根逐项对照 Figma 标题区、行情及结果。用户手选日期并改系数后，目标数字与独立手算一致。截图核对底栏样式、标的块布局以及结果单行、垂直中心、红绿颜色。验证现有桌面窗口与项目现有窄视口。 |
| B2 真接口网络与图表 | 开 DevTools 保留网络与控制台记录。逐项记录打开、选日、换目标、改系数、计算、关闭、切周期的请求和图表位置。只看真实接口有界请求，单独记录鉴权重放、耗时和响应大小；正常可用周期和经过选择的原指标继续工作。 |

### 7.1 执行命令与证据记录

1. 使用仓库已有依赖执行 `npm --prefix wealth run test -- single-candle-price-target stock-detail index-detail detail-workspace`，再执行 `npm --prefix wealth run typecheck`、`npm --prefix wealth run test`、`npm --prefix wealth run build`。前端测试、构建临时目录依仓库规则放在 `/private/tmp`，复用现有依赖。
2. 既有路由与日线回归入口为 `.venv/bin/python -m pytest tests/web/test_wealth_stock_detail_api.py tests/web/test_wealth_index_detail_api.py tests/web/test_wealth_index_detail_dg_kline.py`。其中股票部分用 `backend_for_client` 替代算子后端，DG 指数文件测试直接调用服务；通过这些用例只能说明相应隔离范围。A1/A2 另在获准的现有运行环境，以普通 HTTP 路由和实际配置的数据源执行，不注入 mock service/query。使用已登录浏览器网络面板或已有授权的本地请求方式，保留请求路径、参数、HTTP 状态、`dataStatus`、两根 `tradeDate/close` 和当日核心字段。
3. B1/B2 打开普通股票和指数详情，同一环境复用 A1/A2 的标的和历史日期。DevTools 验收不注入行情 URL 拦截或 mock adapter。对每个实际用例登记环境、日期、标的、有效请求数、回包根数、耗时、字段比对和浏览器截图，明示未覆盖环境。读取范围只限上述单标的选日及已有图表，不全量读取。

## 8. 编码门禁矩阵

| [Wealth 交付清单](./module-delivery-checklist-v1.md) | 适用性与具体落点 | 核验方式 |
| --- | --- | --- |
| §2.1 交付事实链 | 适用。已确认 Figma、修订方案、本文及门禁矩阵。 | 核对评审链和当前状态。 |
| §2.2 后端事实归一 | 适用。§3 只投影既有行情事实，计算是用户输入即时结果。 | T4、A1、A2、B1。 |
| §2.3 状态机 | 适用。§4 区分空闲、加载、数据、空和错误，新弹窗沿用现有请求期限。 | T4、T5、T6、B1。 |
| §2.4 语义绑定 | 适用。§3 涨跌幅和 §5 结果字号、颜色按其各自实际含义。 | T3、T4、B1。 |
| §2.5 行为过程 | 适用。§4 包括异步加载、取消、失败、重试、重新计算。 | T2、T5、T6、T7。 |
| §2.6 文档与实现同步 | 适用。方案、Figma、LLD 和断言随同一需求口径。 | 同轮对照 R1–R7 和结果记录。 |
| §2.7 渐进替换 | 按现有真实 API 新增消费，涉及真实数据、回滚和不回退 mock；source 切换开关不适用，本期无源切换或 mock 接入。 | §6、B2、核对请求和变更范围。 |
| §2.8 契约与消费者 | 适用。冻结 §2 前端入参及 §3 现有行情字段，两页共享。外部 DTO 增改不适用。 | 类型检查、T4、A1、A2。 |
| §2.9 坐标与文案 | 轴策略不适用，弹窗无图表且已有坐标沿用。显示文案按 §4–§5。 | T7、B2。 |
| §2.10 统计与传输 | 请求预算与实测适用。SQL 聚合、特定函数及兼容分支不适用，两根日线走既有接口。 | §6、A1、A2、B2。 |
| §2.11 策略配置 | 策略中心不适用。四个产品默认值固定在共享功能的模型，随前端版本生效，手改仅留在弹窗。 | §2–§3、T2。 |
| §2.12 门禁矩阵 | 适用。本节逐项标明适用范围、位置与验证。 | 评审本节和 §7 实际结果。 |
| §2.13 例外与语义 | 适用。期限差异登记在下表；累计图表语义不涉及。 | 期限与状态检查、T3、T4。 |
| §2.14 图表参数 | 不适用。本功能无显式坐标参数和优先级变化。 | T7、B2 回归原图表。 |
| §2.15 双图与轴标签 | 不适用。无并排图表、轴域或并排布局变化。 | B2 核对原图表。 |
| §2.16 单行约束 | 适用。§5 明确字号、居中、单行和可用宽度处理。 | B1 长数字、正常及窄窗口截图。 |
| §2.17 核心接口与展示 | 适用。§3 字段表与 §7.1 命令、接口和页面双验收。 | A1、A2、B1、B2。 |
| §2.18 跨模块约束 | 适用。下表逐项映射八条原则。 | 复核下表及对应证据。 |

| §2.18 原则 | 本期落点与验收 |
| --- | --- |
| 1 事实源单一 | §3 取同一日线回包、同一价格口径和精确日期，T4、A1、A2 对账。 |
| 2 契约先行 | §2–§3 冻结前端输入与既有字段，T4 断言请求和可空字段，A1、A2 走普通路由。 |
| 3 配置一致 | §2 只在共享模型维护四个固定值，T2 对不同标的验证默认。 |
| 4 默认显式 | §4 明确初始目标、日期、系数、缺值及切换，T2、T4、T6 验证。 |
| 5 日期选择明确 | §3 明确精确当天和最近前一根日 K，T4 和 A2 断言无精确日期不回退。 |
| 6 性能有预算 | §6 声明请求根数、重放和取消后重测费用，B2 记录实际。 |
| 7 异常与状态 | §4 使用现有鉴权和错误路径，本期没有新增 API 异常码，T5 验证状态。 |
| 8 用户可见结果 | §5、§7 对照浏览器真实字段、已知公式结果和视觉状态，B1、B2 记录证据。 |

| 例外记录 | 适用范围及理由 | 验证 |
| --- | --- | --- |
| 复用已有请求期限 | 仅本测算弹窗。沿用既有日线客户端和后端执行期限，不另套通用清单示例中的前端 5 秒值。不同日线分支的后端期限可不同。 | 按 §6 记录真实耗时、取消、路由错误及页面提示。 |

## 9. 实施顺序与验收交接

1. LLD 评审后，在当前代码版本核对两条普通日线接口的有界样本。价格、日期、身份或取数限制不符合 §3 时先查明差异，更新方案与 LLD 后再进入实现。
2. 实现共用弹窗和取数、计算路径，先用独立样例核对默认值、空状态、晚到请求与公式。接上两页日 K 按钮和股票标签清理，补齐周月、分钟与指数原入口相关回归。
3. 运行 §7.1 的命令、真实接口与浏览器验收，将 R1–R7 映射到实际代码、测试和读回证据。记录失败、续验及仍待验证的环境。验收结论以实际执行为准。
