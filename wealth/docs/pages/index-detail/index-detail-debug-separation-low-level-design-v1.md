# 指数详情页普通请求与核验请求拆分 LLD v1

2026-11-10，财势乾坤本机接入已完成，管理员确认本机验收通过。实现提交为 `260d18907`，验收见 §6.1。业务口径见[财势乾坤接入方案 §9](../../../../lake_console/docs/design/dagster-major-index-quantitative-structure-onboarding-plan-v1.md#9-财势乾坤接入技术方案)，入口拆分流程见已评审的 [HTML 拆分方案](/Users/congming/.codex/visualizations/2026/11/08/01a1ba5a-b8e7-7960-8ac1-78dbadf6b3c4/wealth-index-detail-debug-separation.html)。事件、曲线的读取范围、结果字段和缺数据处理见[量化结构数据集 LLD §8](../../../../lake_console/docs/design/dagster-major-index-quantitative-structure-onboarding-low-level-design-v1.md#8-财势乾坤接入详细设计)。

## 1. 范围和验收条件

- 本机开发版网页仅在指数详情网址带 `debug=1` 时打开核验页。核验页直接请求独立接口，保留原逐根识别、预判、波段和诊断计算。波段按日期标在当前日线图上。
- 普通页的历史量化结构事件读主要指数量化结构数据集。日线和分钟副图各自读取识别所用的 MACD（12、26、9），用它画曲线、读数和标记。普通 MACD 副图继续使用自己的数据。图上按 `displayOnChart` 画标记，悬停展示该根 K 线的时间和全部事件，按 Gold 顺序显示。同一根可以有多项事件。下一根预判继续计算。
- 两条链路各自选择页面入口、请求地址、回包解析和界面状态，缓存按入口区分。浏览器分别安排各自的请求，服务器沿用现有的同时处理数量。共用行情查询、算法和图表组件。普通页面及其请求不触发核验模块加载、核验接口请求或诊断组装。
- 本轮只改财势乾坤指数详情页及直接调用方。DG 文件、Job、Sensor、九指数范围、五个周期、r4.1 规则、股票详情、市场总览的核验入口、环境配置和服务部署方式沿用现有定义。

拆分前，`IndexDetailPage`、图表、请求客户端和后端投影都接收 `debug`。核验页面代码未就绪时，`effectiveDebug` 会取普通值。基础接口会先构造部分诊断再丢弃。权重缓存只按指数和业务日期查找，来回切换时会复用另一种响应。本轮从入口拆开了这三处依赖。

## 2. 冻结请求和响应合同

以下均为 GET，相对前缀为 `/api/v1/wealth/market/index-detail`。请求字段名称、大小写、必填项、默认值、日期解析、重复参数检查及业务错误沿用迁移前实现。

| 普通地址 | 核验地址 | 请求字段 | 回包 |
| --- | --- | --- | --- |
| `/page-init` | `/debug/page-init` | `tsCode, tradeDate` | 页面初始化业务字段相同。普通 `debugInfo: null`，核验返回页面、报价、基本指标及成分涨跌明细 |
| `/kline` | `/debug/kline` | `tsCode, period, startDate, endDate, limit` | K 线、指标、日期、分页及 `dataStatus` 相同。普通 `debugInfo: null`，核验返回日线检查明细 |
| `/weights` | `/debug/weights` | `tsCode, tradeDate` | 权重批次、贡献点、统计和 `dataStatus` 相同。普通 `debugInfo: null`，核验返回权重检查明细 |
| `/xxm-signals` | `/debug/xxm-signals` | `tsCode, period, startDate, endDate, limit` | 普通返回 Gold 事件、量化结构曲线点、标的、周期、版本、覆盖范围和状态，字段见数据集 LLD §8.3。核验返回原 `XxmDebugResponseDto` |
| `/minute-xxm-signals` | `/debug/minute-xxm-signals` | `tsCode, freq, startDate, endDate, limit` | 与日线识别分法相同。分钟 `freq` 仍为 30、60、90、120 |
| `/xxm-key-point-forecast` | `/debug/xxm-key-point-forecast` | `tsCode, period, asOf` | 同一输入的预判结论相同。普通 `ForecastResponseDto`，核验 `ForecastDebugResponseDto` |
| 无 | `/debug/daily-waves` | `tsCode`，仅 `000001.SH` | 有结果和空结果都沿用现有波段回包。主图 K 线由日线接口提供。旧 `/daily-waves` 迁移后返回路由未找到 |

- 网页 URL 的 `debug=1` 只由网页路由读取。上表注册的 API 地址一律拒绝 `debug` 参数。收到 `debug=0` 或 `debug=1` 时走各自原无效参数规则，基础接口为 400 `ID_REQUEST_INVALID`，识别为 400 `XXM_REQUEST_INVALID`，预判为 400 `XXMF_REQUEST_INVALID`，波段为 422 `DAILY_WAVE_INVALID_REQUEST`。删除 `_parse_debug`、`parse_debug` 及对应 FastAPI `Query` 参数。新核验地址本身即表示核验。
- 基础三项核验沿用相应普通 API 当前的 `require_quote_access` 和环境开放范围。识别、预判和波段核验沿用后端显式 `APP_ENV=local/dev` 的门禁。普通识别和预判也保留现有门禁。分钟识别两种地址都只在现有分钟能力可用时注册。分钟能力关闭时，日线预判仍可用，分钟预判沿用原不可用错误。前端仅在本机开发版选择核验页。
- 基础三项的 `debugInfo` 固定保留在 JSON。核验 `modules[]` 使用 `module/status/expectedTradeDate/observedTradeDate/rowCount/missingCount`，`exceptions[]` 使用 `module/code/severity/message`。字段、空值、条目顺序和错误文本沿用原核验响应。识别及预判普通响应没有 `debug` 字段，核验响应必带原 `debug` 对象。识别、预判、波段的 `Cache-Control: no-store` 照旧。
- 日线识别默认 300 根，分钟识别默认 500 根，两种识别的 `limit` 都是 1–2,000 根。日线预判 `asOf` 仍为日期，分钟预判使用现有带 `+08:00` 的完成时刻。九指数范围和分钟完成端点按现有合同核对。北证 50 `899050.BJ` 保持无量化结构和预判，基础三项请求仍可使用。

当前 [指数详情 API / DTO 合同](index-detail-api-contract-v1.md) 记载旧接口。实现交付时更新其中的请求表、回包例子、错误及版本记录，并同步相关研究 API 文档和下文列出的调用方。

## 3. 后端迁移

### 3.1 URL 决定处理函数

1. 在 `src/biz/api/wealth/market/index_detail_debug.py` 登记上表七条核验路由，沿用现有请求参数、鉴权、依赖注入、错误转换和响应头。基础三项在 `src/app/api/v1/router.py` 与普通路由一起装配。其余四项放入现有本机装配函数，分钟判断使用已解析的同一个能力结果。移走普通 App 装配对波段实现的顶层导入。
2. 核验入口通过鉴权和参数校验后再导入对应实现。轻量入口只持有请求参数、业务依赖及已有通用错误类型。普通路由继续声明普通 `response_model`。核验路由在处理函数内按专用 DTO 验证、序列化后返回 `Response`。接口说明保留新地址、参数及返回结构，波段仍列出有结果和空结果两种结构。接口说明生成与业务处理分开，普通应用启动及普通请求均不加载核验处理代码。
3. 将基础三项已有参数解析、`_raise_http_error` 和 K 线路径选择保留为可共享的普通代码。识别、预判现有参数校验也只维护一份，调用方直接选择查询服务。普通接口处理函数、共享查询、DTO 和 App 装配的静态导入图中均无核验实现。核验失败只返回该地址的错误。

上证核验日线由 App 注入运行函数，沿用现有 App 到 Biz 的依赖方向。核验参数校验使用现有上证代码与业务错误定义。轻量路由模块无需加载波段计算来判断 `tsCode`。

在 [App 路由](../../../../src/app/api/v1/router.py) 中同时移除波段 API 和 `daily_wave_session_factory` 的启动导入。由 App 给核验路由提供创建波段只读会话的函数。这个函数只在 `/debug/daily-waves` 通过权限和参数检查、开始处理请求后，才从 `src/app/dependencies/daily_wave.py` 导入并调用原工厂。波段查询仍使用原只读会话及原超时和关闭规则。

### 3.2 页面初始化、日线和权重

修改 `src/biz/queries/wealth/market/index_detail/` 下对应的三个查询服务。每个服务保留普通 `build_page_init`、`build_kline`、`build_weights` 并去掉 `debug` 参数。各自提取一个共享查询方法，返回业务字段及本次查询已经得到的事实。普通方法调用它后返回普通 DTO。核验组装直接调用同一个查询方法，并用其结果生成核验 DTO。将三项核验的 DTO 迁到 `src/biz/schemas/wealth/market/index_detail_debug.py`，异常条目构造和分项状态组装移到 `src/biz/queries/wealth/market/index_detail/debug_response.py`。

| 服务 | 共享查询和业务响应继续负责 | 仅核验入口负责 |
| --- | --- | --- |
| `index_detail_page_query_service.py` | 保留业务日期解析、最近可用指数日线、同日量额和基本指标、成分涨跌统计。保留总 `dataStatus` 和业务字段中的成分涨跌状态。用现有查询返回的期望/观测日期、缺失计数、是否有日线及权重批次组装响应 | 无日线时按原顺序生成四项空记录和源空说明。有日线时生成 `pageInit, quote, dailyBasic, breadth`，迁移原报价、基本指标及缺权重时的分项状态计算。按原顺序列量额缺失、基本指标缺失、无权重、日线滞后 |
| `index_detail_kline_query_service.py` | 保留查询上下界、交易日、行数、分页、指标对齐、当前业务状态。通用日线与上证日线分别保留各自的预期日期、空窗口和缺指标判断。上证路径的期望日期仍取 `expected_end or query_end`，观测日期取日历窗口的最后一天，空窗口为 `None` | 根据同一次结果生成 `kline` 记录。通用路径沿用源空、因子部分缺失和观测日落后条目。上证现有计算路径保留自己的因子缺失或源空条目及原顺序。行数和缺失数取该窗口的原统计值 |
| `index_detail_weights_query_service.py` | 保留两种空结果的业务字段、权重批次选择、顺序、昨收与贡献点计算。保留可算和缺失数，以及重复成分或无效权重时原来的报错 | 生成一项 `weights`。区分无指数日线与无权重批次。对有数据的结果保留昨收缺失、观测日期滞后原条目及顺序 |

响应实现顺序如下。

1. 从三个现有响应类型抽出相同业务字段，保留字段顺序、验证和序列化规则。普通 DTO 的 `debugInfo` 类型为 `None`，显式输出 `null`。核验 DTO 使用相同业务字段定义，`debugInfo` 类型为必填的 `IndexDetailDebugInfoDto`。共享查询从数据库取得的行及计数直接交给核验组装函数，省去第二次行情读取。
2. 删除三个共享服务中的 `IndexDetailExceptionBuilder`、`_module_debug` 和 `debugInfo=… if debug`。仅诊断用的状态解析留到核验组装。业务 `dataStatus` 与业务缺失数仍在共享查询内一次计算。沿用当前业务错误转换，诊断用的异常条目只用于核验回包。
3. `000001.SH` 的日线且 `limit <= 500` 继续使用 `src/app/dependencies/index_daily_technical_indicators.py` 的指标运行代码，其余沿用现有线程池查询路径。把上证路径中查询、指标计算和编码抽为同一个执行函数，由普通入口传普通组装函数，核验入口传核验组装函数。组装及 UTF-8 编码继续在原工作线程、截止时间和响应大小限制内完成。保留 DG／Prod 源选择、上一根读取、断连取消和失败转换。
4. 上证普通和核验日线都使用 App 已装配的 `technical_indicator_runtime`，分别传入自己的响应组装函数。沿用当前与股票日线共用的计算和排队设置，以及现有启动和关闭方式。

### 3.3 量化结构、下一根预判和波段

| 代码 | 编码要求 |
| --- | --- |
| `index_detail_xxm.py`、`index_detail_minute_xxm.py` API | 原地址调用独立的普通识别查询。按数据集 LLD §8.2–8.4 选交易日、读主要指数量化结构文件和覆盖区间的识别曲线数据，生成普通响应。普通历史识别不调用 `load_entry()`、r4.1 或任何核验投影 |
| `index_detail_xxm/query_service.py` | 保留 `SeriesEntry`、`XxmCache`、`load_entry()`、`calculator_at()` 及其行情读取、状态快照和校验。迁出原 `build(debug=…)` 的 HTTP 历史识别投影。核验入口继续使用原日线起点、分钟窗口、事件和参照。缓存写入前保留 `_validate_entry` 及 `_response` 原来做的内部结果校验，含事件、结构、快照关联 |
| `index_detail_xxm/forecast_query_service.py` | 提取两条入口共用的计算与响应编码过程。保留原完成端点、`asOf`、前缀恢复、预判算法、`_assemble`、缓存键和写入时点。普通入口只传普通投影，核验入口传核验投影。校验、投影、编码和截止时间检查全部成功后才允许写入原缓存候选。一次请求只计算一次 |
| `response_projection.py`、识别和预判 schema | 普通识别增加独立的响应类型，字段及曲线点按数据集 LLD §8.3。现有 `XxmDebugResponseDto` 基于原 `XxmResponseDto`，迁移时保留这套响应字段和点校验。将核验的 `XxmDebugResponseDto`、`ForecastDebugResponseDto`、核验专用验证和投影移到专用模块。供预判计算的内部模型仍由公共计算代码维护。核验识别保留现有曲线、事件 ID、状态、参照、结构、标记顺序及诊断字段 |
| `index_detail_daily_wave.py`、波段查询与前端 `daily-wave/apiClient.ts` | 波段接口迁入 `/debug/daily-waves`，沿用原查询、计算和返回字段。前端按 §3.4 把结果标到已有 K 线。[Web 错误处理](../../../../src/app/exceptions/web.py)中波段错误的 `Cache-Control: no-store` 路径同步改为新地址 |

普通 Gold 读取、普通预判、核验识别和核验预判都用现有 `_REQUEST_SLOTS` 控制同一时间可以读几笔。预判和核验继续在现有 `load_entry()` 的读取阶段获取和归还名额，Gold 读取按数据集 LLD §8.4 使用同一对象。复用现有 `XxmCache` 及容量。由入口给行情计算结果、预判结果和正在进行的同键查询加普通或核验标识，同一指数同一时间的结果也只在各自入口复用。清理时只清当前入口的记录，容量满时沿用现有淘汰规则。两种预判分别验证同一输入所得结论，Gold 固定起点与核验滚动窗口各按自己的样本验收。

在 [预判响应校验](../../../../src/biz/schemas/wealth/market/index_detail_xxm_forecast.py) 中，移除公共 `_validate_identity` 对 `ForecastDebugDto` 的判断。普通预判继续用计算结果中的 `price_at`、`dif_at` 校验编号。核验回包仍使用 `priceAt`、`difAt`。只在校验核验回包时，将校验用副本中的两个字段名改回计算结果的写法，再调用同一套编号校验。返回给网页的字段名、预判编号和条件编号沿用现有值。

### 3.4 波段只在已有 K 线上加标记

1. `DailyWaveQueryService.build()` 按原观察范围从 `core_serving.index_factor_pro` 读取指数代码、交易日、收盘价、DIF、DEA 和 MACD 柱。行情和 MACD 在同一个查询中取出。用于判断观察起点的前段行情和交易日历沿用原查询，计算规则照旧。新地址返回现有波段明细或空结果，`sourcePoints` 仍随波段明细返回。取消上一版设计中的 `bars`、扩充查询列和 K 线格式转换。 [原波段查询](../../../../src/biz/queries/wealth/market/index_detail_daily_wave/query.py)
2. `useDailyWaveReview.ts` 每次打开或手工重试只请求一次 `/debug/daily-waves`。拿到结果即保存波段明细。删除第二次日线请求、`matchDailyWaveKline()`、`mismatch` 及其提示，并从波段状态中删除专用 `candles` 和 `dataKey`。关闭、切换指数或周期、离开页面时沿用现有取消逻辑，旧响应不能恢复已关闭的标记。 [现有波段页面入口](../../../../wealth/src/features/index-detail/daily-wave/useDailyWaveReview.ts)
3. `IndexChartWorkspace` 的 `points`、`dataKey` 和 `onHistoryViewport` 始终由当前页面的日线首批数据与原翻页逻辑决定。删除 `chartOverride` 和波段触发的主图切换。核验页将波段标记组件交给日线图表，组件接收正在画图的 `points` 和 `useNineTurnChartLayer()` 返回的 `markers`，供现有 `DailyWavePrimitive.setData()` 按日期画三角。将波段图层追加到现有 `mainPrimitives`。同一次页面挂载中，波段开关只增减图层、图例和悬停说明，图表组件和 `dataKey` 保持同一个。波段原三角画法及避让规则照旧。 [主图数据入口](../../../../wealth/src/features/index-detail/chart/IndexChartWorkspace.tsx) · [按日期画三角](../../../../wealth/src/features/index-detail/daily-wave/DailyWavePrimitive.ts)
4. 画标记时按日期找当前图上已有的 K 线，尚未加载对应日期就跳过该标记。用户往左翻到该日后，将更新后的 `points` 交给同一个波段图层，用已返回的结果补画。核验页的首批日线和翻页由页面原有加载流程请求 `/debug/kline`，与波段开关分开。删除 `useDailyWaveCompanionLayers`，原先为换图额外取的九转和趋势随之取消。九转和趋势继续由当前页面的加载和翻页流程负责。

## 4. 前端迁移

### 4.1 页面入口和基础请求

1. 在 `wealth/src/app/routes/WealthRouter.tsx` 的指数详情分支，解析一次 `location.search`。仅 `import.meta.env.DEV` 且 `params.get("debug") === "1"` 时渲染核验入口。继续直接加载普通 `IndexDetailPage`。将 `useIndexDebugModule` 现有的按需加载、错误、手工重试和卸载保护移至路由选择后的小组件，动态导入整个 `IndexDetailDebugPage`。核验代码加载期间显示现有加载状态，失败后使用现有重试操作。两个入口切换时卸载旧页面，取消在途请求，首笔新请求直接使用新入口的地址。
2. 从 `IndexDetailPage.tsx` 提取现有行情、周期、页签和图表布局为 `IndexDetailPageView.tsx`。两个入口分别传入自己稳定的请求函数与展示组件。路由把解析出的 `tradeDate` 交给共享页面，保留显式日期和默认日期的区别。将「查看最近交易日」的导航移到入口，沿用只删除 `tradeDate` 的行为，核验页因此仍留在核验入口。从顶栏选另一指数照旧用目标指数的默认地址。共享页面、布局、图表和底层客户端均去掉 `debug` 模式参数。把 `indexRecognitionAvailability.ts` 收窄为识别能力判断，保留当前已验证指数、开发环境和北证 50 限制。
3. `indexDetailApiClient.ts` 中的 `fetchIndexDetailPageInit`、`fetchIndexDetailKline` 和 `fetchIndexDetailWeights` 只发各自的普通地址。在 `features/index-detail/debug/` 内建立核验客户端和核验回包解析。两边复用已存在的鉴权传输、URL 参数构造和业务字段处理。共享控制器消费共同的业务字段。普通响应类型保留 `debugInfo: null`，核验类型包含完整的 `debugInfo`。当前基础三项的诊断供 API 核验，本轮按原用途保留回包。
4. `useIndexDetailController` 接收当前入口的 `loadPageInit`、`loadDailyKline`，删掉从 `search` 读取 `debug` 的逻辑。初始化完成后仍用回包 `asOfTradeDate` 发日线请求。`useIndexDailyHistory` 接收同一个 `loadDailyKline`，从历史分页输入移除 `debug`，保留分页端点、重复页控制及旧响应丢弃规则。核验页往左拖仍使用 `/debug/kline`。趋势通道、分钟行情及指标、九转沿用原请求地址和启用条件。
5. `useIndexWeights` 由入口传入该接口地址及加载函数，沿用打开权重页签且业务日期就绪时才请求。缓存键固定为 `请求地址|大写指数代码|asOfTradeDate`。按当前键读、写、删除，已取消的请求不提交回包。普通页打开上证某日权重后，核验页第一次打开同一天的权重必须发一次 `/debug/weights`。回到普通页可复用自己的响应。重试核验权重只删核验键。

### 4.2 图表、预判和请求状态

- `IndexChartWorkspace` 和 `IndexMinuteChartWorkspace` 使用入口提供的量化结构组件。组件输入为 `tsCode, period, points, indicatorVersion, indicatorsPending, enabled`。组件内部调用各自的 Hook，以 `children(view)` 将曲线、图元、按时间取悬停内容的函数和状态提示交给原图表渲染位置。公共图表自身移除 `debugExtension`、`decodeDebug` 和 `renderXxmDetails`。核验页负责原九转对齐提示。波段标记按 §3.4 附加到现有日线主图。
- 普通 `xxm/apiClient.ts`、`adapter.ts`、`useIndexXxmLayer.ts` 移除核验类型、解析回调和查询参数。普通解析按数据集 LLD §8.3 接受曲线点的两个空状态字段，核验解析仍按原类型处理。沿用 `useXxmValuesAt` 从识别回包的 `points` 取 DIF、DEA、MACD 给量化结构副图及读数，按 `meta.responseStart`、`meta.responseEnd` 和完成时刻与已加载 K 线对齐，核对对应收盘价，标记高度用识别点的 DIF。普通 MACD 副图继续使用图表接口的值。普通悬停的量化结构明细只显示时间和全部当根事件，按 Gold 原顺序。图上标记只取 `displayOnChart=true` 的事件。例如同根先取消旧结构、再出现新钝化，图上画新钝化，悬停按顺序显示两件事。核验组件和客户端放在 `debug/`，沿用其原识别回包的曲线、结构详情、参照和重试。首批 K 线和所需技术指标就绪即请求，副图开关只控制显示，普通日线向左续页时复用首批识别响应。核验路径沿用原窗口触发条件。
- `IndexInfoRail`、`IndexTechnicalTab` 接收由入口组装好的预判卡片。普通预判 Hook 和卡片只使用公开 DTO。核验页使用自己的 API 解析及明细内容，共用预判结论的现有展示。保留技术面页签激活、分钟支持、显式历史日期与请求取消规则。原 `IndexRecognitionDebug` 负责的波段状态和所有权检查移入核验页。
- 普通客户端沿用现有 `indexDetailRequests`。核验页加载后创建自己的 `IndexDetailRequestScheduler`。核验使用的指标、九转、识别、预判等原来进入队列的请求，传入当前入口的调度器。保留图表、九转、识别、预判原优先级和各自取消方式。基础三项请求沿用直接发送方式。
- 每次请求以当前入口、指数、周期、业务日期和已有窗口键归属到当前页面。入口切换、指数或周期变更和卸载继续使用原 AbortController 和响应归属检查。迟到响应只能由原请求持有者提交。切回周期、页签或详情页时沿用现有重新请求方式。读 Gold 仍按现有默认业务日期，晚间数据产出后刷新页面发起新请求。DG 上海时间 18:00 起检查上游，财势乾坤上海时间 20:00 切换默认业务日期。当前请求统计起止点及重试方式沿用原代码。

## 5. 开发顺序和直接调用方

1. 后端先改路由、参数和 DTO，拆基础三项查询与组装，按 §3.4 迁移波段地址。用迁移前核验样本比对业务字段和全部核验明细。测试冷启动、普通请求、无权限核验、有效核验四个阶段的模块导入记录。
2. 完成普通识别读取和响应，合并当前窗口的 Gold 事件与识别原用的日线、分钟 MACD（12、26、9）。拆识别核验与预判投影。分别比对 Gold 事件、曲线源值、r4.1 样本和预判样本，验证缓存各自取用、服务端沿用原并发上限。保留真实输入的 r4.1 和共享包回归。
3. 前端接入两个入口，再移除混用的标记、类型和旧请求构造。迁移直接使用接口的页面测试、日线翻页、权重、两种识别与预判客户端、波段客户端，以及 [页面请求验收脚本](../../../../scripts/research/index_market/xxm_page_request_audit.py) 和同名 `.mjs`。脚本继续支持 `--mode normal|debug|both`。浏览器脚本按模式调用实际客户端，后端脚本用完整 URL 归类请求，测试 App 装配与正式 App 相同的路由和指标运行依赖。每组采样只清理本组缓存。普通识别的 `prefixRows/sourceInputId` 留空，按实际 Gold 响应验证。核验和预判按原规则记录来源和计算前缀。同步检查引用 `load_entry()` 或 `XxmQueryError` 的研究工具与测试，包括 `xxm/daily_window_precheck.py`。
4. 将网页、后端、脚本、接口合同作为同一版交付。合并前查找旧 `debug=0/1` HTTP 调用、旧波段 URL、普通导入核验模块和测试中旧响应类型，清理本次范围内的直接消费者。保留网页 `?debug=1`。如果发布后需要回退，按现有发布方式整版恢复财势乾坤，复查页面与接口。Gold 继续由 DG 发布。

审计使用 CodeGraph 的 `codegraph_explore` 追踪网页路由、图表、侧栏、预判及上证日线工作线程，并核对识别查询、DG 计算输入和副图取值。波段修订核对了开关请求、主图换图、历史翻页和标记绘制的调用。编码后复查构建产物、真实样本及并发请求的相互影响，检查项见 §6。

## 6. 验收用例和性能

| 验收项 | 必须观察到的结果 |
| --- | --- |
| 路由与权限 | 在本机有权限时按 §2 访问。覆盖未登录、非本机、分钟能力关闭和北证 50。显式 `debug` 被各自原规则拒绝，旧波段 URL 返回 404，核验波段的成功及错误响应均返回原 `no-store` 响应头。非本机基础三项的核验地址保持原权限范围 |
| 加载隔离 | 浏览器冷开普通网址，核验包下载数和核验 HTTP 请求数为零。延迟核验页面加载，页面初始化和识别首笔分别为 `/debug/page-init`、`/debug/xxm-signals` 或分钟地址。模拟核验代码加载失败及手工重试。新后端进程先跑普通请求、普通预判和无权限核验，核验回包代码、波段会话及波段查询均未导入，诊断组装调用数为零。获准核验后只加载相应实现。先跑核验预判，再跑相同输入的普通预判，确认普通预判未执行核验回包组装和核验字段转换，公开结论和编号与冷启动时一致 |
| 三项基础接口 | 比较相同指数日期的两种业务字段及顺序。覆盖无日线、量额缺失、基本指标缺失、无权重、权重滞后、昨收缺失、空分页、指数日线技术因子缺失和观测日滞后。普通均为 `debugInfo: null`。核验按迁移前样本比对每项状态、计数、错误码、严重程度和文字。每次请求只跑一遍原业务查询流程，核验说明复用本次已读的数据。核验日线首批和续页都走 `/debug/kline` |
| 切换、缓存和并发 | 同一指数同一日按普通 → 核验 → 普通 → 核验切换。两边第一次分别发一次权重请求，后续命中各自缓存。重试一个地址时另一个键保留。延迟旧响应后切换，旧结果不能覆盖当前页面。两笔读数据的请求占满原额度时，第三笔等其中一笔结束再开始。上证日线两种地址使用同一个指标运行对象。核验失败、超时或取消后可重试，按入口清缓存只删对应键 |
| 量化结构 | 九指数与五周期的范围按数据集 LLD。至少核对上证日线、其他指数日线和分钟各一个窗口。普通识别按 §2 返回事件和曲线点，核对实际读取的交易日历、主要指数量化结构文件及曲线数据范围，识别内核调用为零。用固定的同根取消和钝化样本验证图上一个标记、悬停依次显示两件事。覆盖完成端点对齐、当根无事件、尾部未产出、失败和窗口内部缺文件。用普通 MACD 与识别值不同的样本验证两副图各用各的值，核验继续按原窗口计算且不读 Gold。副图开关和日线续页不追加普通识别请求 |
| 波段 | 用原样本确认新地址仍返回同样的波段结果，接口说明仍列出有结果和空结果两种返回。先等核验页首批日线和已有图层加载完成，再记录打开或重试波段后的新增请求。每次只发一次 `/debug/daily-waves`，主图日期、滚动位置和 `dataKey` 保持原值。首批 K 线只有 5 日、6 日，波段结果含 4 日、6 日时，只在 6 日画标记。往左翻由 `/debug/kline` 加载 4 日后，已有结果补画 4 日标记。九转和趋势按原翻页流程加载，波段请求次数保持不变。关闭后清掉标记。覆盖空结果、失败、超时、取消和切换指数或周期 |
| 预判与更新 | 同输入对照两种预判的公开结论，核验继续比对参照、条件和取消顺序。使用 20:00 前后日期测试并刷新页面，核对晚间文件产出后的显示 |
| 真实请求和耗时 | 使用现有本机环境、真实 API 及有限交易日的正式 Lake 样本。记录页面首批请求、实际文件数、冷/热耗时、响应字节数、计算调用数和超时后再次请求。真实样本用量化结构数据集 LLD §8.4 已列出的事件与窗口。隔离测试和真实验收分别记录 |

识别沿用后端 4 秒、1 MiB 响应和前端 5 秒请求限制。普通识别的交易日历、主要指数量化结构文件及曲线数据读取共用同一次后端截止时间。预判沿用 `FORECAST_SPEC` 的 400 毫秒计算上限及 32,768 字节响应上限。日线行情接口的技术指标计算继续按现有配置执行。波段沿用 `DailyWaveReviewSpec` 的后端 8 秒、响应 2 MiB 和浏览器 10 秒，验收记录开启波段后的请求次数、响应字节数和耗时。取消或超时后重跑同一窗口，使用相同读取范围和限制。验收按现有计时方式分别记录正常、失败及重跑请求耗时。

每个后端进程沿用 `BUDGET` 的量化结构读取上限，普通和核验合计同时读 2 笔。共用现有 64 MiB／16 条缓存容量，按入口取用各自的结果。上证日线使用原指标运行对象的设置，沿用现有工作线程和数据库连接方式。

后端回归入口为 `tests/web/test_wealth_index_detail_api.py`、`test_wealth_index_detail_dg_kline.py`、`test_wealth_index_detail_xxm_api.py`、`test_wealth_index_detail_xxm_local_routes.py`、`test_wealth_index_detail_xxm_forecast_api.py`、`test_wealth_index_detail_xxm_forecast_validation.py`、`test_wealth_index_detail_daily_wave_api.py`、`test_xxm_shared_loads.py`，以及 `tests/test_index_detail_daily_wave_query.py`、`tests/app/technical_indicators/test_index_daily_kline_integration.py`、`test_stock_daily_integration.py` 和 `scripts/research/index_market/tests/test_xxm_p4_audit_tools.py`。前端回归覆盖 `IndexDetailPage.test.tsx`、`IndexDetailDailyWave.test.tsx`、`useIndexDetailController.test.tsx`、两个图表 workspace、`IndexTechnicalTab.test.tsx`、`xxm/`、`xxm-forecast/`、`daily-wave/` 和 `debug/`。将波段原有第二次取日线及逐日对比用例改为一次请求、在已有 K 线上按日期加标记的断言。补路由冷加载、权重缓存切换及原并发上限的回归。开发验收运行相关用例、`npm --prefix wealth run typecheck`、`npm --prefix wealth run test` 和 `npm --prefix wealth run build`，用浏览器网络记录确认构建后的模块加载及波段请求次数。

### 6.1 实施验收记录

2026-11-10。本机通过后端相关回归 1,473 项及前端 1,602 项，类型检查、构建和文档完整性检查通过。后端冷启动、普通历史识别及拒绝核验权限时，均未加载核验响应组装和波段查询。接口说明保留各核验地址的响应字段，以及波段有结果和空结果两种响应。模拟连续两笔读取超时后，原窗口可重新请求。

正式 Lake 只读验收使用本机 API 路由，替换鉴权和数据库会话依赖。普通识别的 r4.1 逐根计算调用为 0。表中为上证指数截至 2026-11-06 两次各取 500 根的实测，耗时包含本机 HTTP 处理，两次请求均访问同一份 SSE 日历两次。

| 周期 | 首次／再次耗时 | 响应字节数 | 每次读取的文件数，另计日历 |
| --- | --- | ---: | --- |
| 日线 | 253／144 毫秒 | 66,843 | 500 份主要指数量化结构文件，500 份指数日线技术因子文件 |
| 90 分钟 | 254／220 毫秒 | 93,177 | 主要指数量化结构、主要指数分钟线、主要指数分钟技术指标各 167 份 |

另核对上证 2024-09-24 日线识别的 MACD 柱值 20.645、中证500 2010-01-04 日线成功且无事件、2010-01-05 的 30 分钟 14:30 顶钝化，以及上证 60 和 120 分钟完成端点。

隔离浏览器使用真实普通识别回包，页面初始化、日线和波段等其他响应使用测试样本。普通页的核验代码下载及核验 API 请求均为 0。核验页的初始化、日线和识别均直接请求各自的 `/debug/` 地址。打开波段只新增一次 `/debug/daily-waves`。开发版 React StrictMode 在两种页面各取消了一次初始化请求，构建版普通页只发一次初始化请求，按原环境门禁使用普通页面。

2026-11-10，管理员确认本机真实页面验收通过。财势乾坤本机接入以此收尾。普通识别仍按本机开发环境开放，生产接入与上线验收另行处理。

## 7. 财势乾坤编码门禁

按[模块交付检查清单 §2](../../system/module-delivery-checklist-v1.md#2-硬检查)执行。

| 检查项 | 落点和验收 |
| --- | --- |
| §2.1 交付事实链 | §2–4 定义数据到页面，§6 用正式 Lake 样本读回 |
| §2.2 后端事实归一 | §3 定义 Gold 事件和识别曲线来源，§4 页面按时间把曲线和事件对齐到已加载的 K 线 |
| §2.3 状态与错误 | §4 定义各自加载、取消、失败、重试，§6 验证切换 |
| §2.4 显示语义 | 普通悬停为时间和当根事件，核验沿用原明细，§6 核对实际页面 |
| §2.5 行为过程 | §6 验证冷启动、延迟加载、权限失败、晚到响应和刷新 |
| §2.6 文档同步 | §5 同步接口合同、研究调用方、测试和验收记录 |
| §2.7 渐进替换 | §5 按后端、前端、真实 API 顺序验证，同版迁移接口消费者 |
| §2.8 契约和消费者 | §2 冻结 URL、参数和字段，§5 同轮迁移网页及脚本 |
| §2.9 图表与文案 | §4 复用图表渲染和坐标，§6 核对同一 K 线的曲线与事件 |
| §2.10 计算与传输 | §3 区分 Gold 读结果、预判计算、核验投影，前端直接展示后端事实 |
| §2.11 配置 | 复用现有开发环境和分钟能力门禁，无新增配置项 |
| §2.12 检查清单映射 | 本表与 §6 验收记录逐项对应 |
| §2.13 例外 | 沿用原权限、开放范围及错误合同，无新增例外 |
| §2.14 图表参数 | 沿用现有坐标、曲线及标记参数，回归事件落点 |
| §2.15 并排双图 | 本轮沿用上下副图，页面验收同屏读数 |
| §2.16 卡片文案 | 预判结论卡沿用原文案，回归核验明细和普通悬停 |
| §2.17 真实 API 和页面 | §6 核对实测请求、响应及展示 |
| §2.18 八项原则 | 事实源、合同、配置、默认行为、顺序、性能、观测和用户可见结果，分别按 §1–6 验证 |
