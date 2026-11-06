# 指数详情页低层设计（LLD）v1

> 2026-11-05 后续设计：[上证日线接入与普通日线500根请求见 §27](#sse-daily-kline-integration)。前文的旧请求量及验收记录保留为当时事实，普通日线后续实现以 §27 为准。

> 2026-11-04 成分行情缺失修订：用户验收通过，需求收尾。仅成分缺行情不再触发两处提示及 PARTIAL；完整月度 A 股名单、缺失计数与贡献 `--` 保留，其它异常照常展示。本次仅收尾提交，不执行推送或部署；生产发布及同拓扑复验独立进行。实现、技术验证和用户验收记录见[LLD §25](./index-detail-low-level-design-v1.md#index-constituent-missing-quote-20261020)。

> 状态：指数详情开发与生产验收已完成。M1～M5-B、P10、共享图表、九转 S7/M5/M6-A～M6-D 和日线最终数据/性能门禁均已按冻结合同实现；主要指数 bars/indicators 只读正式 Gold，无 Silver fallback 或 Mock。本地按 capability 开放七个分钟周期，生产只开放日线且分钟路由保持 404。
> 新增专项（2026-10-13）：上证日线及 60／90／120 分钟的徐小明 V0.1 已按批准 Figma 实现，技术验收完成，等用户验收；仅指数详情页的 1280／1440px 适配另获批准。当前证据及未确认边界见[专项实施方案与 LLD §13](./index-detail-xxm-implementation-and-low-level-design-v0.1.md#13-实施与技术验收2026-10-13)。本专项尚未部署，不改变本文既有验收记录或生产分钟门禁。
> 需求依据：[指数详情页标杆需求 v1](./index-detail-benchmark-requirement-v1.md)
> 技术方案：[指数详情页技术实施方案 v1](./index-detail-implementation-design-v1.md)
> 编码门禁：[指数详情页 M2 编码前门禁 v1](./index-detail-m2-coding-gate-v1.md)
> 正式 DTO：[指数详情页正式 API / DTO 合同 v1](./index-detail-api-contract-v1.md)
> M0 生产审计：[指数详情页 M0 生产因子审计 v1](./index-detail-m0-production-audit-v1.md)
> 趋势接口依据：[SSE 日线趋势通道实时计算方案 v1](../../../../docs/architecture/sse-daily-trend-channel-realtime-computation-low-level-design-v1.md#decisions-and-rationale)
> 分钟 DTO：[指数详情本地分钟 API / DTO 合同 v1](./index-detail-minutes-api-contract-v1.md)

---

## 1. 目标、范围与结论

### 1.1 本文要解决的问题

本文把已确认的产品与交互方案细化为可以逐文件实施和逐项验收的 LLD，重点冻结：

1. 指数详情独立 BFF 的目录、职责、DTO 和查询边界。
2. `page-init -> kline -> trend` 首屏请求编排，以及权重、分钟的懒加载边界。
3. 15 项基本行情、成分涨跌统计、完整权重批次和贡献点的唯一计算口径。
4. 股票/指数共享图表引擎的抽取范围，防止复制现有 751 行股票图表实现。
5. 上证指数趋势通道的逐日绘制与逐日着色算法。
6. Loaded、Loading、Empty、Error、Partial、Forbidden 共用页面骨架的状态机。
7. 本地指数分钟 reader 与生产环境隔离方式。
8. 代码、真实 API、浏览器和像素验收的退出条件。

### 1.2 本期包含

1. 10 个 `majorIndices` 配置指数的详情路由。
2. 正式环境日线页面、15 项基本行情、权重股、技术分析走势三 Tab。
3. 上证指数 `000001.SH` 的既有日线趋势通道消费与绘制。
4. 权重贡献点估算、完整列表、固定表头、10 行视窗和内部虚拟滚动。
5. 五个完整页面状态及 404、DELAYED、模块级错误变体。
6. 通用日线四面板图表能力抽取，并保持股票详情可见行为不变。
7. 本地分钟能力的独立 M5 结构设计。

### 1.3 本期不包含

1. 技术结论 API、结论文案或自动交易动作。
2. 九转 API 或前端推导。
3. 除上证指数外的趋势通道适配层。
4. 周线、月线、分时线或生产分钟接口。
5. 数据表迁移、生产写入、Lake 写入或 Dagster 主链修改。
6. `src/platform`、`src/operations` 新实现或兼容层。
7. 对旧 Quote 聚合 API、股票详情 DTO 或主要指数卡片 DTO 的字段扩展。

### 1.4 总体结论

M0 技术产物已完成，M1 后端已落地：

1. 10 指数 `core_serving.index_factor_pro` 的当前生产快照覆盖、同日一致性和旧候选 joined 查询 P95 已审计；M1 已复测最终 factor-only SQL、MA 历史基数条件查询和完整服务链。MA 历史不足采用基于实际历史根数的通用判断。
2. `ID_*` / `IM_*` 已登记到统一异常码注册表。
3. page-init/kline/weights 正式 DTO 已以 `1.3.1` 独立合同冻结；1.3.1 在不增删字段的前提下，将权重 rows 排序收敛为贡献点数值降序、null 置底和稳定决胜。
4. 生产审计发现深证成指、创业板指 factor 量额与正式日线分叉；外部数据源核对确认 factor 准确，基本行情与 Kline 的量额统一取 `index_factor_pro`，不做倍率修正或 daily fallback。
5. 已新增独立 `page-init/kline/weights` schema、query、mapper、service 与正式路由；未修改股票详情、主要指数卡片或 Quote trend DTO。
6. M1 生产只读复验显示 9 个指数当前有 630 根 factor（自 2024-01-02），A500 当前有 455 根（自 2024-09-23）；该结果只记录审计时点，不进入任何 code/date 特例。

M5-A 的 Silver K 线是历史阶段事实。P10 已在 Gold canonical bars 重建、技术指标重建和事件补录完成后，将正式业务读取切换为 Gold bars + Gold indicators；当前不再读取 Silver，也不保留 fallback。

---

## 2. 设计事实源与冲突优先级

实现发生冲突时按以下顺序判定：

1. 用户最新明确口径。
2. 本文引用的当前 Figma 节点与已批准交互。
3. 三件套文档与 M2 门禁。
4. 当前代码、真实 ORM、源接口本地文档和生产只读审计。
5. 股票详情只作为交互和代码模式参考，不作为指数业务合同。

Figma 事实源：

| 设计对象 | 节点 | 实现用途 |
|---|---|---|
| Basic Loaded | `417:2` | 默认完整页面基线 |
| Basic Rail 组件 | `414:446` | 15 项基本行情、两列八行、最后半行 |
| Weights Loaded | `423:2` | 权重 Tab 基线 |
| Weights Rail 组件 | `414:447` | 固定表头、10 行视窗、内部滚动 |
| Technical Loaded | `423:910` | 技术分析走势 Tab 基线 |
| Technical Rail 组件 | `414:448` | 四轨、技术结论占位与九转客观摘要 |
| Tab 组件集 | `473:275` | 三 Tab 稳定切换骨架 |
| 趋势通道组件集 | `413:25` | 四种逐日颜色状态的视觉参考 |
| Loading | `498:516` | 完整 Loading 页面 |
| Empty | `499:579` | 完整 Empty 页面 |
| Error | `501:761` | 完整 Error 页面 |
| Partial | `502:1625` | 完整 Partial 页面 |
| Forbidden | `504:1009` | 完整 Forbidden 页面 |
| States / Interaction Notes | `425:178` | 状态和交互说明 |

`425:190` 是过期的基本行情概述，仍含“振幅/较昨日”。实现和测试不得引用该节点。

---

## 3. 硬约束清单

| 编号 | 硬约束 | 代码落点 | 负向门禁 |
|---|---|---|---|
| C01 | 路由只接受 `majorIndices` 当前 10 code | universe service + page/kline/weights service | 任意第 11 个 code 返回 404 |
| C02 | 默认且正式环境只支持日线 | page-init capability + toolbar | prod 不挂分钟路由，分钟按钮 disabled |
| C03 | 不保留“前复权” | DTO、toolbar、页面文案 | 请求不接受 `adjustment`，DOM 无该文案 |
| C04 | 仅 `000001.SH + day` 请求趋势 API | capability + trend hook | 其余 9 code 的 fetch 次数为 0 |
| C05 | 通道颜色不使用 API `state` | trend adapter/primitive | state 与 close/lower 冲突样本仍按 close/lower |
| C06 | 每个有效交易日画短/长期各一根竖线 | trend primitive | 不允许抽样竖线或隔日连接 |
| C07 | 基本行情固定 15 项 | Basic adapter/grid | 不出现成交状态、较昨日、振幅 |
| C08 | 缺值显示 `--`，不补 0 | mapper + formatter | null 指标不产生零值折线 |
| C09 | 成分涨跌只统计权重批次中的 A 股；同日股票日线优先，确有停牌记录时按平盘解析 | page query | B 股不进入 total/missing；真实缺失不计入 flat |
| C10 | 权重 API 返回完整 A 股子集 | weights query/DTO | 不接受 limit，不静默截断，不归一化 A 股权重 |
| C11 | 权重不归一化，贡献不缩放 | contribution builder | 权重和不等于 100 仍保留源值 |
| C12 | 三 Tab 只替换右栏内容 | IndexInfoRail | 切 Tab 不销毁日线图表 |
| C13 | 权重/趋势/分钟错误是模块级错误 | controller state | 局部失败不覆盖页面 READY |
| C14 | 401/403/404/ERROR/EMPTY 有明确优先级 | controller reducer | 403 不伪装 EMPTY |
| C15 | 共享图表不得复制 stock 主实现 | shared chart engine | 禁止新增第二份 700+ 行同构实现 |
| C16 | 图表坐标内部保留绝对定位 | shared chart + primitive | 不用 Grid/Flex 排 K 线点、坐标轴、十字线 |
| C17 | 页面骨架/右栏/卡片/列表用流式布局 | page CSS/components | 不用补偿 x/y 模拟布局 |
| C18 | local minute 只读正式 Lake 根 | local capability/reader | 不读取旧 Lake 根或 staging |
| C19 | 本轮不写生产 DB/Lake | 全链路 | 无 migration、upsert、materialize |
| C20 | 股票、主要指数和 Quote 旧契约无字段漂移 | 回归测试 | 响应 key 集合快照保持不变 |

---

## 4. 当前代码审计与缺口

### 4.1 后端现状

| 当前文件/符号 | 已有能力 | 本页结论 |
|---|---|---|
| `src/biz/api/wealth/market/stock_detail.py` | `page-init`、`kline`、鉴权和参数别名模式 | 只参考分层，不复用股票 DTO |
| `StockDetailQueryService` | `MarketPageContextQuery`、日线/分钟 capability 编排 | 不能扩成 index/stock 联合大服务 |
| `stock_detail_field_mapper.py` | 股票 qfq、振幅和因子映射 | 指数 bfq 字段不同，新增 index mapper |
| `MarketPageContextQuery` | 默认最新已完成交易日、显式日期 | 原样复用，服务层不得再次减一天 |
| `StrategyConfigService` | 严格读取并缓存 `majorIndices` 配置 | 作为 10 code 唯一名单，不复制私有 fallback |
| `MarketMajorIndicesQueryService` | 10 卡顺序和快照 | 响应契约不修改；其 `_DEFAULT_INDEX_CODES` 不作为详情事实源 |
| `IndexBasic` | 指数名称、市场、发布方、分类 | 详情身份事实源 |
| `IndexDailyServing` | OHLC、昨收、涨跌与最新观测日 | page-init 日期/价格锚点；不提供量额 |
| `IndexDailyBasic` | PE、PE TTM、PB、换手率、流通/总市值 | 六个可空日度指标事实源 |
| `IndexFactorPro` | bfq OHLC、量额、MA、BOLL、MACD、KDJ | Kline 全字段及 page-init 同日量额事实源 |
| `IndexWeight` | 月度成分权重和复合索引 | 权重批次事实源 |
| `EquityDailyBar` | A 股成分同日 `pct_chg` | 涨跌统计与贡献的第一优先级输入 |
| `EquitySuspendD` | A 股成分同日 `suspend_type='S'` | 日线缺失时的停牌证据；解析为平盘和贡献 0 |
| `Security` | 成分股名称、证券类型、交易所和币种 | 用 `EQUITY + SSE/SZSE/BSE + CNY` 定义页面 A 股有效集合；不得按代码前缀猜测 |
| `QuoteTrendChannelQueryService` | `000001.SH + day` 的 25/90 通道与缓存 | 直接消费，绝不参数化为 10 指数 |
| `resolve_local_minute_capability` | local/dev 开关、Lake root、DuckDB 门禁 | M5 复用，不新增设置 |
| `StockMinsLakeReader` | 股票按年份 Gold 文件、游标和 schema 校验 | 指数是按交易日 Gold bars/indicators，不能继承或复制路径算法 |

### 4.2 前端现状

| 当前文件/符号 | 已有能力 | 本页结论 |
|---|---|---|
| `WealthRouter.tsx` | 解析股票详情，其余路由回市场总览 | 增加 index parser，顺序在默认回退前 |
| `routerState.ts` | `buildStockDetailPath` 和 history 通知 | 增加 `buildIndexDetailPath`；集中维护 `returnToWealthOverview()`，仅对带站内来源标记的 entry 调用 `history.back()`，直达/旧 entry 则 replace 到市场总览 |
| `MajorIndexPanel.tsx` | 卡片是 button，但点击只 toast | 改为上报 `onIndexSelect(code)` |
| `MarketOverviewPage.tsx` | 股票导航和 toast | 增加 `openIndexDetail`，不在卡片内拼 URL |
| `StockDetailPage.tsx` | page-init 后请求 kline、AbortController、本地分钟缓存 | 只参考请求生命周期；指数需更完整状态机 |
| `stockDetailViewModelAdapter.ts` | 把 null 转 0 | 指数禁止复用此策略 |
| `StockChartWorkspace.tsx` | M2 审计时为 4 面板、crosshair、tooltip、90 根窗口 | 已成为 shared adapter；当前使用统一自适应默认与按钮缩放 |
| `StockMinuteChartWorkspace.tsx` | 股票分钟 4 面板 | 已成为 shared adapter；只保留股票分钟字段、单位、状态与 Tooltip 语义 |
| `wealthFetch` | 401 刷新 token 和失效会话通知 | 原样复用；指数错误类型另保存 HTTP status |
| `TopMarketBar` | 共享顶部栏 | 所有指数状态原样复用 |

### 4.3 不能照搬的实现

1. `StockDetailPage` 的 loading/error 只有顶部栏和居中状态块，不符合指数完整状态稿。
2. `stockDetailViewModelAdapter` 的 `valueOrZero` 会制造假 K 线和技术指标尖峰。
3. `StockMinsLakeReader` 使用按年份组织的 Gold 文件；指数分钟 bars/indicators 均使用按 `trade_date=YYYY-MM-DD` 组织的正式 Gold 分区，不能继承股票路径算法。
4. 既有趋势接口使用 snake_case 查询参数与响应字段，不是 Wealth camelCase DTO。
5. `IndexWeightDAO.get_latest_weights()` 的排序不符合页面贡献点降序要求，不修改 DAO 旧语义；详情专用 query 只取完整事实，最终排序在贡献计算后的 service 完成。

---

## 5. CodeGraph 影响面记录

本轮在仓库根执行 `codegraph status/query/impact`，索引为 up to date。关键结果：

1. `WealthRouter` 当前直接影响自身；新增 index route 需要配套 router test。
2. `buildStockDetailPath` 的调用链到 `MarketOverviewPage.openStockDetail`；新增 index builder 不改 stock builder。
3. `MarketMajorIndicesQueryService` 影响主要指数 API/query 共 11 个符号；详情页只读同一策略配置，不修改该服务或响应。
4. `StockDetailPageInitResponseDto` 同时影响后端 schema、TS DTO、adapter 和页面；因此本页新增独立 DTO，禁止向股票响应加字段。
5. `QuoteTrendChannelQueryService` 的消费者为 Quote route 和两组测试；指数页面不改 service、cache、calculator 或 schema。
6. `StockChartWorkspace` 的真实页面消费者是 `StockDetailPage`；共享提取必须用 import 搜索和 stock 页面测试补足 CodeGraph 对 TSX 动态关系的不足。
7. 2026-08-12 对成分口径变更再次执行 CodeGraph：`IndexDetailQuery.load_breadth` 只由 `IndexDetailPageQueryService` 消费，`load_weight_rows/load_weight_batch_stats` 只由 `IndexDetailWeightsQueryService` 消费；前端只读取既有 breadth/coverage DTO，不需要新增字段。改动面因此收敛在专用 query、现有 service 不变量和 Web API 测试，未触及股票、主要指数卡片或旧 Quote 契约。

编码后若批量改图表文件或索引出现滞后，先 `codegraph sync` 再复核上述消费者。

---

## 6. 目标架构与依赖方向

```text
MarketOverviewPage
  -> buildIndexDetailPath(code)
  -> WealthRouter
  -> IndexDetailPage
       -> useIndexDetailController
            -> index page-init API
                 -> MarketPageContextQuery
                 -> StrategyConfigService(majorIndices)
                 -> IndexDetailQuery
            -> index kline API
                 -> IndexFactorPro
            -> quote trend-channel API (000001.SH only)
                 -> existing QuoteTrendChannelQueryService
            -> weights API (lazy)
                 -> IndexWeight + Security(A 股过滤) + EquityDailyBar + EquitySuspendD
            -> local minute APIs (M5 only)
                 -> MajorIndexMinsLakeReader
```

依赖规则：

1. `foundation` 只承载 ORM、Settings/capability 和本地文件 reader，不 import `biz/app/wealth`。
2. `biz/queries` 只读事实，`biz/services` 做纯映射/状态/公式，`biz/api` 做 HTTP 参数和错误映射。
3. `app` 只负责路由组合与认证依赖。
4. `wealth/features/index-detail` 消费 API 并生成 ViewModel；页面不直接理解数据库字段名。
5. `wealth/shared/charts` 不出现 stock/index 文案、API 类型或业务 capability。
6. Dagster 工程不反向依赖 Web reader，Web 也不 import `lake_console/orchestrator`。

---

## 7. 文件级结构

### 7.1 后端新增

```text
src/biz/api/wealth/market/
  index_detail.py
  index_detail_minutes.py                 # M5，local 条件 import

src/biz/schemas/wealth/market/
  index_detail.py
  index_detail_minutes.py                 # M5

src/biz/queries/wealth/market/index_detail/
  __init__.py
  index_detail_query.py                   # 纯 ORM 读取和内部 row dataclass
  index_detail_page_query_service.py      # page-init 编排
  index_detail_kline_query_service.py     # 日线/因子编排
  index_detail_weights_query_service.py   # 权重/贡献编排

src/biz/queries/wealth/market/index_detail_minutes/
  __init__.py
  index_detail_minutes_query_service.py   # M5

src/biz/services/wealth/market/index_detail/
  __init__.py
  index_detail_universe.py                # majorIndices 严格名单
  index_detail_field_mapper.py            # bfq/quote/identity 映射
  index_detail_status_resolver.py         # 页面与模块状态
  index_weight_contribution_builder.py    # Decimal 贡献公式
  index_detail_exception_builder.py       # debug exception 结构

src/foundation/clients/local_lake/
  major_index_mins_contract.py             # M5 路径/列/频率合同
  major_index_mins_reader.py               # M5 只读查询
```

早期草案中的单一 `index_detail_query_service.py` 已在 LLD 和实际代码中拆成 page/kline/weights 三个服务。原因是三条链的加载时机、错误范围、性能预算和数据源不同；合成一个大服务会让权重局部失败污染首屏。

### 7.2 后端修改

1. `src/app/api/v1/router.py`
   - 正常挂 `index_detail.router`。
   - 在现有 `_include_local_minute_router()` 内、同一 capability 为 true 时延迟 import 并挂 `index_detail_minutes.router`。
   - prod/staging 进程不得 import DuckDB reader。
2. `wealth/docs/system/exception-code-registry.md`
   - 编码前登记本文第 13 节异常码。
3. 不修改任何 ORM schema、Alembic migration、Quote trend schema、主要指数 DTO 或股票详情 DTO。

### 7.3 前端新增

```text
wealth/src/pages/index-detail/
  IndexDetailPage.tsx
  IndexDetailPage.test.tsx
  index-detail-page.css

wealth/src/features/index-detail/api/
  indexDetailApiClient.ts
  indexDetailApiTypes.ts
  indexDetailViewModelAdapter.ts
  trendChannelApiClient.ts
  trendChannelAdapter.ts
  indexDetailMinuteApiClient.ts             # M5

wealth/src/features/index-detail/model/
  indexDetailTypes.ts
  indexDetailConstants.ts
  indexDetailState.ts

wealth/src/features/index-detail/controller/
  useIndexDetailController.ts
  useIndexWeights.ts
  useIndexMinuteSeries.ts                    # M5

wealth/src/features/index-detail/chart/
  IndexChartWorkspace.tsx
  IndexMinuteChartWorkspace.tsx              # M5
  TrendChannelPanePrimitive.ts
  trendChannelGeometry.ts

wealth/src/features/index-detail/layout/
  IndexBreadcrumbActionBar.tsx
  IndexChartToolbar.tsx

wealth/src/features/index-detail/sidebar/
  IndexInfoRail.tsx
  IndexBasicTab.tsx
  IndexWeightsTab.tsx
  IndexTechnicalTab.tsx

wealth/src/features/index-detail/state/
  IndexDetailLoadingSkeleton.tsx
  IndexDetailPageState.tsx
  IndexDetailModuleState.tsx
  IndexDetailPartialNotice.tsx

wealth/src/shared/charts/detail-workspace/
  DetailChartWorkspace.tsx
  DetailChartPane.tsx
  detailChartTypes.ts
  detailChartSeries.ts
  detailChartFormatters.ts
  detail-chart-workspace.css
```

### 7.4 前端修改

1. `WealthRouter.tsx`：新增 `parseIndexDetailTsCode()`，位于股票解析后、市场总览 fallback 前。
2. `routerState.ts`：新增 `buildIndexDetailPath()`，行为为 trim、upper、encode。
3. `MajorIndexPanel.tsx`：`onAction` 改为 `onIndexSelect`；卡片只上报 code。
4. `MarketOverviewPage.tsx`：增加 `openIndexDetail()`，toast 仍服务其它操作。
5. `StockChartWorkspace.tsx`：保留为有业务职责的 stock adapter，不作为兼容层；通用图表实现移至 shared。
6. `stock-detail-page.css`：只移走真正属于通用图表的样式，页面和 stock 专属样式保留。

`IndexDetailPage.tsx` 目标不超过 400 行；请求生命周期放 controller hooks，DTO 映射放 adapter，图表对象创建放 shared engine。

---

## 8. 正式 API 契约

统一前缀：`/api/v1/wealth/market/index-detail`。

本节是代码结构摘要；字段 required/nullable、debug、错误响应和变更规则的唯一金标是 [指数详情页正式 API / DTO 合同 v1](./index-detail-api-contract-v1.md)。所有 Pydantic DTO 使用 `ConfigDict(extra="forbid")`。所有客户端 DTO 保持 camelCase；数据库字段映射只出现在后端 mapper/query。

### 8.1 通用状态 DTO

```python
IndexDetailStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY"]

class IndexDetailDataStatusDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: IndexDetailStatusValue
    expectedTradeDate: date
    observedTradeDate: date | None
```

成功状态优先级：`EMPTY > PARTIAL > DELAYED > READY`。Loading 是前端阶段，401/403/404/400/500 使用认证层或冻结错误响应，不伪装成 HTTP 200 `dataStatus=ERROR`。

### 8.2 `GET /page-init`

请求：

| 参数 | 类型 | 规则 |
|---|---|---|
| `tsCode` | string | 必填，trim+upper，必须属于 `majorIndices` |
| `tradeDate` | ISO date | 可选隐藏锚点，不在 UI 提供日期选择器 |
| `debug` | 0/1 | 默认 0 |

响应结构：

```ts
interface IndexDetailPageInitResponseDto {
  pageContext: MarketPageContextDto;
  asOfTradeDate: string | null;
  index: {
    tsCode: string;
    name: string;
    market: string | null;
    category: string | null;
    publisher: string | null;
    tags: string[];
  };
  quote: {
    tradeDate: string;
    point: number | null;
    change: number | null;
    changePct: number | null;
    direction: "UP" | "DOWN" | "FLAT" | "UNKNOWN";
    open: number | null;
    high: number | null;
    low: number | null;
    preClose: number | null;
    vol: number | null;
    amount: number | null;
  } | null;
  dailyBasic: {
    tradeDate: string;
    pe: number | null;
    peTtm: number | null;
    pb: number | null;
    turnoverRate: number | null;
    floatMv: number | null;
    totalMv: number | null;
  } | null;
  constituentBreadth: {
    tradeDate: string;
    weightTradeDate: string;
    upCount: number;
    flatCount: number;
    downCount: number;
    totalConstituentCount: number;
    matchedCount: number;
    missingCount: number;
    dataStatus: IndexDetailDataStatusDto;
  } | null;
  chartDefaults: {
    defaultPeriod: "day";
    availablePeriods: Array<"day" | "m1" | "m5" | "m15" | "m30" | "m60" | "m90" | "m120">;
    availableMainOverlays: Array<"MA" | "BOLL" | "TREND_CHANNEL">;
    availableIndicatorTabs: Array<"VOL" | "amount" | "MA" | "MACD" | "KDJ" | "BOLL">;
  };
  capabilities: {
    supportsTimeShare: false;
    supportsWeeklyMonthly: false;
    supportsMinute: boolean;
    minuteFrequencies: Array<1 | 5 | 15 | 30 | 60 | 90 | 120>;
    supportsTrendChannel: boolean;
    supportsNineTurn: true;
    nineTurnPeriods: Array<"day" | "5" | "15" | "30" | "60" | "90" | "120">;
    supportsTechnicalConclusion: false;
    supportsTradePlanEntry: true;
  };
  dataStatus: IndexDetailDataStatusDto;
  debugInfo: IndexDetailDebugInfoDto | null;
}
```

规则：

1. `pageContext.tradeDate` 是期望完成日；`asOfTradeDate` 是 `IndexDailyServing.trade_date <= expected` 的最新观测日。
2. quote 无行时 `asOfTradeDate=null`、`quote=null`、`dataStatus=EMPTY`。
3. quote 的日期/价格来自 daily；`vol/amount` 只取同 code、`trade_date=asOfTradeDate` 的 factor。factor 同日行或字段缺失时两项为 null，不回退 daily，并登记 `ID_FACTOR_PARTIAL`。
4. dailyBasic 只查 `trade_date = asOfTradeDate`，不向前找旧行冒充同日指标。
5. breadth 的三项统计在 `asOfTradeDate` 计算；先将权重批次与 `Security` 内连接，只保留 `security_type=EQUITY`、`exchange in (SSE,SZSE,BSE)`、`curr_type=CNY` 的 A 股。B 股及无法证明为 A 股的源行不进入 `totalConstituentCount/matchedCount/missingCount`，也不触发 PARTIAL。禁止按 `900xxx` 等代码前缀过滤。
6. 对每个 A 股成分，精确日 `EquityDailyBar.pct_chg` 非空时以该值为准；日线缺失或 `pct_chg` 为空但精确日存在 `EquitySuspendD.suspend_type='S'` 时按 `pct_chg=0`、FLAT 解析；两者同时存在时日线优先。只有两类证据都不存在才计入 `missingCount`。无权重批次时 breadth 为 `null`，不是三个 0。
7. `supportsTrendChannel` 只在 code 为 `000001.SH` 时为 true，且仅日线使用。
8. local capability disabled 时 `availablePeriods=["day"]`、分钟频率为空；enabled 时追加七个分钟 key。
9. `availableMainOverlays` 对上证指数包含 `TREND_CHANNEL`，其余 9 个只含 `MA/BOLL`。
10. Partial 提示不增加另一个自由文本合同。前端从 quote/dailyBasic 的真实 null 字段及其它仍适用的异常生成缺失项列表；不再将成分 `missingCount>0` 加入提示，也不能改成泛化的“部分基本行情”继续提示。Figma fixture 不写死。
11. page-init 状态解析固定为：quote 无行是 EMPTY；quote 存在但同日 factor 量额、dailyBasic 整行/字段缺失或 breadth 为空时是 PARTIAL；仅成分 `missingCount>0` 不再作为 partial 原因。有效批次的 breadth 即使有 missing 也为 READY，数值和 missingCount 均保留；没有其它 partial 原因且 observed 落后 expected 时 page-init 为 DELAYED，其余为 READY。
12. `supportsTradePlanEntry=true` 只表达顶部入口存在；技术结论、趋势状态和任何数据 effect 均不得触发交易动作。

### 8.3 `GET /kline`

请求：

| 参数 | 类型 | 默认/范围 |
|---|---|---|
| `tsCode` | string | 必填、10 code |
| `period` | `day` | 默认 day，拒绝其它值 |
| `startDate` | ISO date | 可选 |
| `endDate` | ISO date | 可选，页面传 `asOfTradeDate` |
| `limit` | integer | 默认 300，1..2000 |
| `debug` | 0/1 | 默认 0 |

明确不声明、不接受 `adjustment`。

```ts
interface IndexDetailKlineResponseDto {
  pageContext: MarketPageContextDto;
  indexRef: { tsCode: string; name: string | null };
  period: "day";
  bars: IndexKlineBarDto[];
  meta: {
    count: number;
    limit: number;
    startDate: string | null;
    endDate: string | null;
  };
  dataStatus: IndexDetailDataStatusDto;
  debugInfo: IndexDetailDebugInfoDto | null;
}

interface IndexKlineBarDto {
  tradeDate: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  preClose: number | null;
  change: number | null;
  changePct: number | null;
  amplitude: number | null;
  vol: number | null;
  amount: number | null;
  factors: {
    ma: { ma5: number | null; ma10: number | null; ma20: number | null; ma30: number | null; ma60: number | null; ma90: number | null; ma250: number | null };
    boll: { upper: number | null; middle: number | null; lower: number | null };
    macd: { dif: number | null; dea: number | null; macd: number | null };
    kdj: { k: number | null; d: number | null; j: number | null };
  };
}
```

字段映射：

| DTO | 唯一来源 |
|---|---|
| 日期、OHLC、昨收、涨跌、`changePct` | `IndexFactorPro`；`pct_change -> changePct` |
| `vol/amount` | `IndexFactorPro.vol/amount` |
| `ma5..ma250` | `IndexFactorPro.ma_bfq_5..ma_bfq_250` |
| `boll.upper/middle/lower` | `IndexFactorPro.boll_upper_bfq/boll_mid_bfq/boll_lower_bfq` |
| `macd.dif/dea/macd` | `IndexFactorPro.macd_dif_bfq/macd_dea_bfq/macd_bfq` |
| `kdj.k/d/j` | `IndexFactorPro.kdj_k_bfq/kdj_d_bfq/kdj_bfq` |

M0 生产审计确认 `399001.SZ`、`399006.SZ` 的 factor 量额自 2026-07-06 起与正式日线分叉，且两个源文档单位相同，不能用固定倍率解释。产品方完成外部数据源核对后确认 factor 准确，因此 `vol/amount` 必须进入 DTO；daily 量额禁止进入或 fallback。

`amplitude = (high - low) / preClose * 100`，任一输入为 null 或 `preClose=0` 时为 null。它只用于图表 tooltip，不进入 15 项基本行情。

MA 的历史不足 null 不因其本身把整页标成 PARTIAL，但必须按真实历史动态判断；以下情况标记 kline PARTIAL：

1. 同一范围的 `index_daily_serving` 有完成日行情，但 `index_factor_pro` 最新行落后。
2. 可绘制范围内整行、OHLC 或 factor `vol/amount` 缺失。
3. `maN` 为 null，且同一 code 截至该交易日已有至少 N 根有效历史 K 线。
4. BOLL/MACD/KDJ 等其它预期技术因子在可绘制范围内缺失。

禁止按 `000510.SH`、`2025-09-30`、当前表起点或首个非空值硬编码豁免。M0 记录的 A500 空值前缀只是 2026-08-11 的生产快照；2024 因子回填后，历史根数变化必须自动参与同一判断。

返回顺序永远为 `tradeDate ASC`；数据库查询先 DESC LIMIT，再在服务层反转。

### 8.4 `GET /weights`

请求：`tsCode`、可选 `tradeDate`、可选 `debug`。不接受 `limit/offset/sort/weightDate`。

```ts
interface IndexDetailWeightsResponseDto {
  indexRef: { tsCode: string; name: string | null };
  contributionTradeDate: string;
  weightTradeDate: string | null;
  isEstimated: true;
  rows: Array<{
    conCode: string;
    name: string | null;
    weight: number;
    changePct: number | null;
    contributionPoint: number | null;
    direction: "UP" | "DOWN" | "FLAT" | "UNKNOWN";
  }>;
  coverage: {
    totalCount: number;
    returnedCount: number;
    contributionAvailableCount: number;
    contributionMissingCount: number;
    isTruncated: false;
  };
  dataStatus: IndexDetailDataStatusDto;
  note: "基于最新月度权重估算，非指数公司官方归因";
  debugInfo: IndexDetailDebugInfoDto | null;
}
```

贡献口径：

```text
contributionPoint
  = indexPreClose
  * (weight / 100)
  * (constituentPctChg / 100)
```

精度冻结：

1. 内部全部转 `Decimal(str(value))` 计算。
2. 不对权重求和做归一化，不按实际指数涨跌点缩放。
3. 输出前用 `Decimal("0.0001")`、`ROUND_HALF_UP` 保留 4 位小数，再转 DTO number。
4. UI 显示 2 位并带正负号；最终 rows 按已输出的四位小数 `contributionPoint` 数值降序，`null` 置底，不按绝对值排序；同贡献点按 `weight DESC, conCode ASC`。
5. index preClose、weight 或最终解析后的 constituent pct 任一缺失时 contribution 为 null；停牌证据解析出的 pct 为 0，因此 contribution 合法为 0，不属于“缺值补 0”。

完整批次规则：

1. `weightTradeDate = max(index_weight.trade_date) <= contributionTradeDate`。
2. 该日期的官方源批次保持原样；页面在 `IndexWeight JOIN Security` 后只保留 `security_type=EQUITY`、`exchange in (SSE,SZSE,BSE)`、`curr_type=CNY` 的完整 A 股子集。B 股和无法证明为 A 股的行不进入 rows/coverage，禁止按代码前缀识别。
3. 对 A 股子集审计 `count(*)`、`count(weight)` 和重复 key；发现 null weight 或重复时整个 weights 模块 ERROR，禁止过滤后返回半批次。
4. 源查询不承担最终业务排序；service 完成贡献点四位小数舍入后，按 `contributionPoint DESC NULLS LAST, weight DESC, conCode ASC` 排列完整 rows。前端保持 API 原序，不得二次排序。
5. `rows.length = totalCount = returnedCount`，`isTruncated=false`；这里的 total 是页面 A 股子集总数，不是官方源批次含 B 股的行数。
6. A 股官方原始 weight 原样返回，不按 A 股权重合计重新归一化，也不按实际指数涨跌缩放。
7. 精确日 daily `pct_chg` 优先；仅在 daily 缺失/空值且存在 `suspend_type='S'` 时输出 `changePct=0`、`direction=FLAT`、`contributionPoint=0`，并计入 contributionAvailableCount；无两类证据才保持 null/UNKNOWN 并计入缺失数，但不单独触发 PARTIAL 或用户提示。
8. A 股名称缺失时保留行并显示 code；名称缺失不影响贡献 coverage。
9. 权重日期默认动态解析；`2026-07-31` 是当前生产验收基线，不硬编码在业务代码。
10. weights endpoint 先按 page-init 同口径解析最新指数日线。若完全没有指数日线，返回 `dataStatus=EMPTY`、`contributionTradeDate=pageContext.tradeDate`、`weightTradeDate=null`、空 rows；页面 EMPTY 不主动请求该接口。只要存在观测日，`contributionTradeDate` 就必须等于该观测日。

---

## 9. 查询设计

### 9.1 Universe 与身份

`IndexDetailUniverse` 每次 service 实例从 `StrategyConfigService.get_config(module_key="majorIndices", market="CN_A")` 取得 payload 和 version，并暴露：

```python
@dataclass(frozen=True, slots=True)
class IndexDetailUniverse:
    config_version: str
    ordered_codes: tuple[str, ...]

    def contains(self, ts_code: str) -> bool: ...
```

禁止 import `MarketMajorIndicesQueryService._DEFAULT_INDEX_CODES`。配置缺失/非法是服务配置错误，HTTP 映射为 `ID_QUERY_FAILED`，debug reason 记录 `config_missing/config_invalid`，不使用 fallback 名单继续展示。

身份查询：

```sql
SELECT ts_code, name, market, publisher, category
FROM core_serving.index_basic
WHERE ts_code = :ts_code;
```

名单包含但身份不存在时返回 `ID_NOT_FOUND`，不得用卡片名称拼临时身份。

### 9.2 Page-init 查询

查询顺序：

1. 解析 universe 和 identity。
2. `MarketPageContextQuery.build_context()` 得到 expected date。
3. 查询 latest quote：

```sql
WITH latest_daily AS (
  SELECT ts_code, trade_date, open, high, low, close, pre_close,
         change_amount, pct_chg
  FROM core_serving.index_daily_serving
  WHERE ts_code = :ts_code
    AND trade_date <= :expected_trade_date
  ORDER BY trade_date DESC
  LIMIT 1
)
SELECT q.ts_code, q.trade_date, q.open, q.high, q.low, q.close,
       q.pre_close, q.change_amount, q.pct_chg,
       f.vol, f.amount
FROM latest_daily AS q
LEFT JOIN core_serving.index_factor_pro AS f
  ON f.ts_code = q.ts_code
 AND f.trade_date = q.trade_date;
```

4. quote 存在时并列执行/顺序执行两个集合查询：exact dailyBasic、breadth 聚合。

```sql
SELECT trade_date, pe, pe_ttm, pb, turnover_rate, float_mv, total_mv
FROM core_serving.index_daily_basic
WHERE ts_code = :ts_code
  AND trade_date = :as_of_trade_date;
```

5. 先解析权重日期：

```sql
SELECT max(trade_date)
FROM core_serving.index_weight
WHERE index_code = :ts_code
  AND trade_date <= :as_of_trade_date;
```

6. 单条集合聚合 breadth，不能把全量成分拉到 Python 再计数。先由 `Security` 事实字段确定 A 股集合，再按“daily 优先、停牌补充”的顺序解析有效涨跌幅：

```sql
WITH eligible AS (
  SELECT
    w.con_code,
    e.pct_chg,
    EXISTS (
      SELECT 1
      FROM core_serving.equity_suspend_d sd
      WHERE sd.ts_code = w.con_code
        AND sd.trade_date = :as_of_trade_date
        AND sd.suspend_type = 'S'
    ) AS is_suspended
  FROM core_serving.index_weight w
  JOIN core_serving.security_serving s
    ON s.ts_code = w.con_code
   AND s.security_type = 'EQUITY'
   AND s.exchange IN ('SSE', 'SZSE', 'BSE')
   AND s.curr_type = 'CNY'
  LEFT JOIN core_serving.equity_daily_bar e
    ON e.ts_code = w.con_code
   AND e.trade_date = :as_of_trade_date
  WHERE w.index_code = :ts_code
    AND w.trade_date = :weight_trade_date
)
SELECT
  count(*) AS total_count,
  count(*) FILTER (WHERE pct_chg IS NOT NULL OR is_suspended) AS matched_count,
  count(*) FILTER (WHERE pct_chg > 0) AS up_count,
  count(*) FILTER (
    WHERE pct_chg = 0 OR (pct_chg IS NULL AND is_suspended)
  ) AS flat_count,
  count(*) FILTER (WHERE pct_chg < 0) AS down_count
FROM eligible;
```

`missingCount = totalCount - matchedCount`，并断言：

```text
up + flat + down = matched
matched + missing = total
```

A 股 `missing > 0` 时保留缺失数和三个已计算计数，不单独令 breadth 或 page-init 为 PARTIAL，不显示成分缺行情提示。缺失成分不进入 up/flat/down；B 股排除和有停牌证据的 A 股不进入 missing。没有权重批次时 breadth 仍为 null，page-init 仍为 PARTIAL，15 项中的三个计数显示 `--`。

### 9.3 Kline 查询

只投影页面需要的 27 个字段，禁止 `select *`：

```sql
SELECT f.ts_code, f.trade_date,
       f.open, f.high, f.low, f.close, f.pre_close, f.change, f.pct_change,
       f.vol, f.amount,
       f.ma_bfq_5, f.ma_bfq_10, f.ma_bfq_20, f.ma_bfq_30,
       f.ma_bfq_60, f.ma_bfq_90, f.ma_bfq_250,
       f.boll_upper_bfq, f.boll_mid_bfq, f.boll_lower_bfq,
       f.macd_dif_bfq, f.macd_dea_bfq, f.macd_bfq,
       f.kdj_k_bfq, f.kdj_d_bfq, f.kdj_bfq
FROM core_serving.index_factor_pro AS f
WHERE f.ts_code = :ts_code
  AND f.trade_date <= :end_date
  AND (:start_date IS NULL OR f.trade_date >= :start_date)
ORDER BY f.trade_date DESC
LIMIT :limit;
```

Kline 查询必须利用 factor `(ts_code, trade_date)` 主键，不再 JOIN daily。M0 的旧候选 joined 查询命中两侧主键，300 根数据库内 P95 为 1.636ms；`limit=2000` 当时每 code 实际只有 388 行，P95 2.127ms。该结果可作更复杂查询的保守参考，但不替代 factor-only 精确 SQL、真实 2000 行 payload 与 Web-host 端到端验收。

MA null 的历史足够性不能用响应数组长度判断。Kline service 在返回 bars 中出现任一 `maN=null` 时，使用同一 Session 追加一次历史基数查询：

```sql
SELECT count(*)
FROM core_serving.index_factor_pro
WHERE ts_code = :ts_code
  AND trade_date < :first_returned_trade_date
  AND close IS NOT NULL;
```

服务将结果作为首根返回 bar 之前的有效历史根数，再按 `tradeDate ASC` 扫描返回 bars；每遇到 `close IS NOT NULL` 加一。对每个 `maN=null`：累计根数小于 N 是合理历史不足；累计根数达到 N 则登记 `ID_FACTOR_PARTIAL`。该查询只判断历史是否足够，不计算或回填 MA，也不得加入 code/date 特例。M1 必须为这条条件查询补索引计划和 P95 验收，避免把 M0 仅含主查询的性能数据误称为最终完整链路。

### 9.4 Weights 查询

读取采用最多四条集合查询：

1. identity + contribution date/preClose。
2. max weight date + A 股子集 batch contract count。
3. 完整 A 股权重 JOIN Security 名称。
4. 在同一集合查询中 LEFT JOIN 当日 EquityDailyBar，并用 EquitySuspendD EXISTS 补充停牌证据。

推荐单条主查询：

```sql
SELECT
  w.con_code,
  w.weight,
  s.name,
  CASE
    WHEN e.pct_chg IS NOT NULL THEN e.pct_chg
    WHEN EXISTS (
      SELECT 1
      FROM core_serving.equity_suspend_d sd
      WHERE sd.ts_code = w.con_code
        AND sd.trade_date = :contribution_trade_date
        AND sd.suspend_type = 'S'
    ) THEN 0
    ELSE NULL
  END AS pct_chg
FROM core_serving.index_weight w
JOIN core_serving.security_serving s
  ON s.ts_code = w.con_code
 AND s.security_type = 'EQUITY'
 AND s.exchange IN ('SSE', 'SZSE', 'BSE')
 AND s.curr_type = 'CNY'
LEFT JOIN core_serving.equity_daily_bar e
  ON e.ts_code = w.con_code
 AND e.trade_date = :contribution_trade_date
WHERE w.index_code = :ts_code
  AND w.trade_date = :weight_trade_date;
```

SQL 只负责集合取数。贡献点使用上述 Decimal 公式计算并舍入后，由 service 执行最终稳定排序；禁止把公式复制进 SQL 或前端。

禁止：

1. 每行查名称或日线的 N+1。
2. 为凑 100% 修改 weight。
3. 用权重列表前 10 行计算 coverage。
4. 把没有精确日停牌证据的 `pct_chg IS NULL` 当 0 或 FLAT。
5. 按代码前缀识别 A/B 股，或把 B 股计入 total/missing 后再在前端隐藏。

### 9.5 一致性与事务

1. 每个 HTTP 请求只使用一个 SQLAlchemy Session。
2. page-init 先冻结 expected/asOf，再用同一日期查询 dailyBasic/breadth。
3. weights 先冻结 contribution/weight date，后续查询不得重新解析日期。
4. 查询为只读，不显式锁表，不提高到会阻塞 ingestion 的隔离级别。

---

## 10. 15 项基本行情 ViewModel

### 10.1 唯一字段顺序

| 顺序 | 标签 | DTO 来源 | formatter |
|---:|---|---|---|
| 1 | 昨收 | `quote.preClose` | point |
| 2 | 今开 | `quote.open` | point |
| 3 | 总量 | `quote.vol` | hands compact |
| 4 | 最高 | `quote.high` | point |
| 5 | 最低 | `quote.low` | point |
| 6 | 金额 | `quote.amount` | thousand-yuan compact |
| 7 | 市盈率 | `dailyBasic.pe` | ratio |
| 8 | TTM 市盈率 | `dailyBasic.peTtm` | ratio |
| 9 | 市净率 | `dailyBasic.pb` | ratio |
| 10 | 换手率 | `dailyBasic.turnoverRate` | percent |
| 11 | 流通市值 | `dailyBasic.floatMv` | yuan compact |
| 12 | 总市值 | `dailyBasic.totalMv` | yuan compact |
| 13 | 上涨数 | `constituentBreadth.upCount` | integer |
| 14 | 平盘数 | `constituentBreadth.flatCount` | integer |
| 15 | 下跌数 | `constituentBreadth.downCount` | integer |

### 10.2 格式化规则

1. point/ratio：两位小数；null/NaN/Infinity 为 `--`。
2. percent：两位小数加 `%`。
3. `vol` 源单位为“手”：`>=1e8` 显示亿，`>=1e4` 显示万，否则原值；最多两位小数。
4. `amount` 源单位为“千元”：先乘 1000 变为元，再按 `万/亿/万亿` 格式化。
5. `floatMv/totalMv` 源单位为元，直接按 `万/亿/万亿` 格式化。
6. count：非负整数；null 为 `--`。
7. 禁止把 null 经 `Number(null)`、`value || 0` 或 `valueOrZero` 转成 0。

### 10.3 颜色规则

1. 今开/最高/最低相对昨收决定 market up/down/flat；任一输入缺失为 neutral。
2. 上涨数使用 market-up，下跌数使用 market-down，平盘数 neutral。
3. 量额、估值、市值与昨收使用 neutral。
4. Error/Partial/Forbidden 只能用 system danger/warning/info，不得复用行情红绿。

### 10.4 布局规则

`IndexBasicTab` 用两列等宽 CSS Grid。每个指标是有背景的真实容器，内部 `display:flex; align-items:center; justify-content:space-between`，统一内边距、行高和 gap。

前 14 项按两列形成 7 行；第 15 项“下跌数”放第 8 行左半宽，右半宽保留空 Grid cell。不得让下跌数跨整行，也不得新增透明全宽补偿节点。

---

## 11. 趋势通道消费与绘制

### 11.1 HTTP 消费

既有接口：`GET /api/v1/quote/detail/trend-channel`。

实际查询参数是 snake_case：

```text
ts_code=000001.SH
period=day
end_date=<asOfTradeDate>
limit=<指数页面显式1000；后端省略参数仍默认300>
```

实际响应关键字段也是 snake_case：`data_status`、`trade_date`、`short_channel`、`long_channel`、`combined_state`。`trendChannelAdapter.ts` 只负责把该旧契约映射成指数图表内部类型，不向后端再包一层 Wealth endpoint。

当前 FastAPI/Pydantic 合同会把 OHLC 和通道 `Decimal` 序列化为四位小数字符串，例如 `"3940.0371"`。因此 raw TS DTO 必须把 `open/high/low/close/upper/lower` 声明为 `string`，adapter 再显式 `Number()` 并校验 finite；不得把未经核验的 raw response 直接断言成 number。

### 11.2 内部类型

```ts
interface TrendChannelPoint {
  time: string;
  close: number;
  shortUpper: number;
  shortLower: number;
  longUpper: number;
  longLower: number;
}

type ShortChannelTone = "shortAbove" | "shortBelow"; // 红 / 绿
type LongChannelTone = "longAbove" | "longBelow";    // 粉 / 蓝
```

adapter 必须验证所有数值有限、`upper >= lower`、日期唯一且升序；非法点丢弃并让趋势模块 PARTIAL，不能把错误坐标送入 renderer。

### 11.3 与 K 线对齐

1. 用 `tradeDate` 精确 inner join trend 与 kline。
2. 不向前填充、不用最近值补缺日、不使用未来日期。
3. 只有在 kline 序列中相邻且两个 trend 点都有效时才连接上下轨；任一日缺点则在该处断开。
4. 每个有效 trend 日仍分别绘制短期和长期的当日竖线。

### 11.4 逐日颜色算法

对交易日 `t`：

```ts
const shortColor = close < shortLower ? SHORT_GREEN : SHORT_RED;
const longColor = close < longLower ? LONG_BLUE : LONG_PINK;
```

等于下轨归入“下轨上方/触及”颜色：短期红、长期粉。页面不读取 API 的 `position/state/combined_state` 决定颜色。

颜色的归属：

1. `t` 日短期上下轨竖线使用 `t.shortColor`。
2. `t -> t+1` 的短期上轨和下轨连接段使用 `t.shortColor`。
3. 长期同理使用 `t.longColor`。
4. 到 `t+1` 日竖线和后续连接段重新判定，所以颜色在交易日边界切换。

### 11.5 Renderer 结构

不得为每个交易日创建 4~6 个 Lightweight Charts series。使用一个附着在主 K 线 series 的 `TrendChannelPanePrimitive`：

当前 lockfile 安装 `lightweight-charts 5.2.0`，其类型已提供 `ISeriesApi.attachPrimitive()`、`SeriesAttachedParameter` 和 `PrimitivePaneViewZOrder`。实现以这组当前 API 为准，pane view 返回 `zOrder() = "bottom"`，不使用未安装版本的示例接口。

1. primitive 接收已对齐点和颜色 token。
2. renderer 用 `timeScale.timeToCoordinate(time)` 和 candlestick series 的 `priceToCoordinate(price)` 取得像素坐标。
3. 单次 canvas pass 依次绘制短期、长期的上下轨连接和每日竖线。
4. 线宽、alpha、z-order 来自 Figma/Design Token；primitive 位于 K 线实体下层、网格上层。
5. resize、visible range、data 和 theme 变化时调用 `requestUpdate()`；只绘制当前可见逻辑范围加 1 个邻接点。
6. Tooltip/十字线仍由 shared chart engine 管理；primitive 不自己创建 DOM tooltip。

几何单测不依赖真实 canvas，`trendChannelGeometry.ts` 输出线段数组：

```ts
interface ChannelSegment {
  channel: "short" | "long";
  kind: "upper" | "lower" | "vertical";
  from: { time: string; price: number };
  to: { time: string; price: number };
  tone: ShortChannelTone | LongChannelTone;
}
```

N 个连续有效点应输出每个通道 `N` 根 vertical 和 `2*(N-1)` 根 horizontal-neighbor segments。

### 11.6 趋势状态

1. 非上证指数：不显示趋势入口、不初始化 hook、不请求。
2. 上证趋势 loading：日线可先显示，趋势层局部 loading。
3. EMPTY：隐藏趋势层，技术 Tab 四轨为 `--`。
4. ERROR：日线保留，页面/技术 Tab 标记 PARTIAL，提供局部重试。
5. READY：技术 Tab 展示最新对齐日的短期上下轨、长期上下轨。

---

## 12. 共享图表重构

### 12.1 Shared engine 职责

`DetailChartWorkspace` 只负责：

1. K 线、MACD、成交量、KDJ 四面板生命周期。
2. visible range、拖动、crosshair 和按钮缩放同步；按[详情页共享图表与 K 线缩放方案](../../system/detail-chart-zoom-implementation-design-v1.md)与[配套 LLD](../../system/detail-chart-zoom-low-level-design-v1.md)统一使用 45～180/15、自适应默认（1600px 为 120 根）与纵轴 autoscale。
3. 时间轴、浮动价格轴标签和 tooltip 定位。
4. MA/BOLL 可选主图层和 null-safe line/histogram 数据。
5. 接收可选 pane primitive，不理解趋势业务公式。

### 12.2 领域 adapter 职责

`StockChartWorkspace`：

1. 把 StockCandlePoint 映射到 shared candle。
2. 提供股票 tooltip 字段、单位、aria 文案和 toolbar action。
3. 提供 `stock:${tsCode}:day` 稳定 dataKey，保留股票 DOM 可见结果和颜色；不管理默认窗口。

`IndexChartWorkspace`：

1. 把 IndexCandlePoint 映射到 shared candle，保留 null。
2. 提供指数 tooltip（点位、涨跌幅、振幅、总量、金额）。
3. 仅上证传入 TrendChannelPanePrimitive。

这些 adapter 有真实领域职责，不是旧组件兼容壳。

### 12.3 Null-safe 数据规则

1. Candlestick 只有 OHLC 全部 finite 才进入 candle series。
2. 任一 line point 为 null/非 finite 时从该 series data 中省略，形成断点，不转 0。
3. Histogram point 为 null 时省略；颜色函数不接收 null。
4. Crosshair 查不到对应 domain point 时清除 tooltip，不回退数组最后一项冒充当前点。
5. shared 类型显式使用 `number | null`，不得用类型断言掩盖。

### 12.4 提取顺序

1. 先锁定股票基线截图和现有测试。
2. 纯搬迁 chart options、series helpers、sync 和 DOM 到 shared；股票 adapter 接入。
3. 股票 typecheck/test/build/浏览器对比通过后单独提交。
4. 再新增指数 adapter。
5. 最后接趋势 primitive。

不得在同一个未验证改动中同时“重写图表 + 接指数 API + 加趋势”。

---

## 13. 状态、错误与权限

### 13.1 前端错误类型

`IndexDetailApiError` 保存：

```ts
class IndexDetailApiError extends Error {
  code: string;
  status: number;
}
```

`wealthFetch` 继续处理 401 refresh/redirect；指数 client 不吞 403/404/500。

### 13.2 页面状态优先级

```text
401 auth redirect
  > 403 forbidden
  > 404/not-found/request-invalid
  > fatal error
  > empty
  > partial
  > delayed
  > ready
```

页面 controller reducer：

```ts
type IndexPagePhase =
  | "loading"
  | "ready"
  | "delayed"
  | "partial"
  | "empty"
  | "notFound"
  | "forbidden"
  | "error";
```

模块状态独立保存：

```ts
type ModulePhase = "idle" | "loading" | "ready" | "delayed" | "partial" | "empty" | "error";
```

`weights`、`trend`、`minute` 不能直接写 page phase；只有 page-init/kline 决定 fatal/empty 主状态。trend error 可以把 ready 页面提升为 partial，但不能清空日线。

### 13.3 已冻结异常码

以下 code 已登记到 [wealth 异常码注册表](../../system/exception-code-registry.md)，实现不得另造同义码：

| code | HTTP/状态 | 触发 | 前端动作 |
|---|---|---|---|
| `ID_REQUEST_INVALID` | 400 | code 格式、日期、period、limit 非法 | 请求错误壳，返回首页 |
| `ID_NOT_FOUND` | 404 | 非 10 code 或身份缺失 | notFound 全页壳 |
| `ID_SOURCE_EMPTY` | 200 EMPTY | 指数日线无行 | Empty 页面 |
| `ID_SOURCE_DELAYED` | 200 DELAYED | observed < expected | 保留数据，显示日期 |
| `ID_FACTOR_PARTIAL` | 200 PARTIAL | page-init 同日 factor 量额缺失、因子整体落后或异常断裂 | 基本行情量额 `--`；日线保留，缺线断点 |
| `ID_BASIC_DAILY_PARTIAL` | 200 PARTIAL | 同日 dailyBasic 缺行/缺字段 | 对应指标 `--`，其它数据保留 |
| `ID_BASIC_BREADTH_PARTIAL` | 原 1.3.1 为 200 PARTIAL | 原成分缺行情诊断；目标 1.3.2 不再产生 | 保留注册历史；工作区已停用，缺失数量保留，无成分缺失提示；未部署 |
| `ID_WEIGHT_EMPTY` | 200 EMPTY | 无权重批次 | 权重 Tab Empty |
| `ID_WEIGHT_CONTRIBUTION_PARTIAL` | 200 PARTIAL | 指数 preClose 缺失；不再由成分缺行情触发 | 行保留，贡献 `--`；仅成分缺行情时不显示此提示 |
| `ID_QUERY_FAILED` | 500/模块 ERROR | 配置或 SQL 未知失败 | 整页或模块重试 |
| `IM_SOURCE_NOT_READY` | 200 DELAYED | local 分区无覆盖 | 分钟局部 delayed |
| `IM_SOURCE_CONTRACT_INVALID` | 500 | Parquet/path/schema 不符 | 分钟局部 error |
| `IM_QUERY_FAILED` | 500 | DuckDB/IO 查询失败 | 分钟局部 error |
分钟参数或 cursor 非法仍使用 `ID_REQUEST_INVALID`；`IM_*` 只表达分钟数据源与查询执行状态，不另造同义请求错误码。

401/403 继续沿用认证层，不登记为业务 EMPTY。当前 shared capability 的 `SM_LOCAL_LAKE_NOT_CONFIGURED` 是启动级全局配置错误，不作为指数分钟 HTTP 响应复用；M5 若要把该错误暴露到模块合同，必须先单独评审通用化命名，不能在指数 service 内改写为另一语义。

### 13.4 页面骨架

所有状态保留：

```text
TopMarketBar(56)
Breadcrumb(42)
Toolbar(44)
MainContent(1058)
```

MainContent Loaded/Loading/Empty/Partial：左右 padding 10、gap 10、左 `1193.1953125×1038`、右 `376.796875×1038`。Error/Forbidden 的 MainContent 使用 `1580×1038` 全宽状态面板。

状态规则：

| 状态 | 页面结构 | 数据规则 | 动作 |
|---|---|---|---|
| Loading | 图表骨架 + 右栏骨架 | 清空上一标的详情缓存 | 无自动 toast |
| Empty | 左空态 + Basic Rail | 当前标的值全 `--` | 重载/移除 tradeDate 看最近日 |
| Error | 全宽系统错误面板 | 不显示旧标的详情 | 完整重试/返回首页 |
| Partial | Loaded 结构 + 局部 warning | 可用数据全部保留 | 对应模块重试 |
| Forbidden | 全宽权限面板 | 不发 kline/trend/weights | 返回首页 |
| 404 | 复用 Error 骨架换文案 | 停止后续请求 | 返回首页 |
| Delayed | Loaded 结构 | 展示 observed date | 可重载，不伪装最新 |

---

## 14. 前端请求编排与并发

### 14.1 首屏

`useIndexDetailController(tsCode, search)`：

1. 归一化 code，创建 page AbortController 和递增 `requestId`。
2. 立即清空上一个指数的 page/kline/trend/weights/minute ViewModel 和缓存，进入 loading。
3. 请求 page-init。
4. 403/404/fatal 立即落对应页面状态，不再发后续请求。
5. page-init EMPTY 时展示 Empty；不发 kline/trend。
6. page-init 成功后，以 `asOfTradeDate` 请求 kline。
7. 若 `supportsTrendChannel=true`，kline 与 trend 可以并行；否则只请求 kline。
8. kline 成功后组装基础 ViewModel；trend 可晚到并只更新 overlay/technical rail。
9. 每次 state commit 前校验 `requestId` 且 signal 未 aborted，避免快速切换指数串数据。

不使用 `Promise.all` 把 trend 失败升级成整页失败。推荐 `Promise.allSettled` 或两个独立 hook 状态。

### 14.2 权重 Tab

1. 默认 Basic，不预取全量 weights。
2. 首次激活 Weights 时请求一次，cache key：`tsCode + asOfTradeDate`。
3. Tab 切回再切入使用 cache，不重复请求。
4. code/asOf 改变时清空 cache 并 abort 旧请求。
5. retry 只清当前 key 的错误，不清日线。

### 14.3 技术 Tab

Technical 读取已经加载的 kline 最新指标和 trend 状态，不发“技术结论”请求；九转则通过共享 registry 按 capability 独立 ensure 固定 day/15/30/60/90/120 六周期，并消费各周期 API 的 `latestMarker`。技术结论固定显示 `--`；九转未开放、源空或无 marker 时显示 `--`，没有 mock 句子。

### 14.4 周期切换

1. prod/local flag false：日线 active；分时、1/5/15/30/60/90/120 分钟、周/月均 disabled，不触发 handler。
2. local enabled：七个分钟按钮 active；切入分钟只替换左图，右侧权重仍是日度权重与日度贡献，不重算盘中贡献。
3. 切回日线恢复日线 cache 和 trend overlay，不重新请求首屏。

### 14.5 交易计划边界

`+交易计划` 只在用户 click handler 中触发既有 toast/入口。controller effect、趋势状态、技术 Tab 和数据异常都不得调用交易 action。

---

## 15. 三 Tab 结构

### 15.1 `IndexInfoRail`

稳定 DOM：

```text
IndexInfoRail
  Header(identity + point + change)
  TabList(Basic / Weights / Technical)
  TabPanel(active only)
```

用 WAI-ARIA `tablist/tab/tabpanel`；ArrowLeft/ArrowRight 切换、Enter/Space 激活。切换只替换 TabPanel，不重建 Header 或左图。

### 15.2 Basic

使用第 10 节的固定 15 项数组。字段数组是已确认 UI 合同，可放 `indexDetailConstants.ts`；值和是否缺失全部来自 adapter。

### 15.3 Weights

1. 表头位于滚动容器外，position 不随 rows 滚动。
2. rows viewport 高度为“Figma 单行高度 × 10”；单行高度在实施开始时从 `414:447` 实际属性取值并锁为 CSS variable，不能目测。
3. 使用固定行高虚拟化；overscan 2~4 行。
4. API rows 保留全量，虚拟化只改变 DOM 渲染数量。
5. 最后一行可通过键盘和滚轮到达；虚拟列表提供正确 `aria-rowcount/rowindex`。
6. 估算说明固定展示，不把贡献点称为官方归因。

### 15.4 Technical

展示：

1. 最新日 MA/BOLL/MACD/KDJ 客观值。
2. 上证指数最新对齐日的短期上轨/下轨、长期上轨/下轨；其余指数显示 `--` 或按 Figma 隐藏趋势分组，不发请求。
3. 技术结论 `--`。
4. 九转按 capability 展示固定 day/15/30/60/90/120 六周期的最新“上序 N/下序 N”；未开放、源空或无 marker 显示 `--`。
5. 不出现买入、卖出、建议、机会、风险评级等主观结论。

---

## 16. 本地指数分钟 LLD（M5）

### 16.1 启用前提

1. `APP_ENV in {dev, local}`。
2. `WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=true`。
3. `GOLDENSHARE_LAKE_ROOT` 可读且指向正式 `/Volumes/datasource/data_lake` 语义根。
4. DuckDB 可 import。
5. Gold canonical bars 与 Gold technical 当前合同均已提交并通过正式物理验收。bars 决定 K 线可用性；indicators 在请求范围缺文件时独立返回 `IM_SOURCE_NOT_READY`，只使技术图层 PARTIAL，不清空 bars。

任一前提不满足都不挂 index minute router。prod/staging 请求路径为 404。

### 16.2 物理合同

Bars：

```text
gold/quote/major_index_mins/
  freq={1|5|15|30|60|90|120}/
  trade_date=YYYY-MM-DD/
  part-000.parquet
```

Gold canonical bars 文件列按当前合同为：

```text
ts_code, freq, trade_date, trade_time, open, high, low, close, vol, amount, exchange, vwap
```

Reader 同时验证目录分区日期、行内 `trade_date` 与 `CAST(trade_time AS DATE)` 三者一致；任一错配均按物理合同错误拒绝。

Indicators：

```text
gold/indicator/major_index_mins_technical/
  freq={1|5|15|30|60|90|120}/
  trade_date=YYYY-MM-DD/
  part-000.parquet
```

Gold 列：`ts_code, freq, trade_date, trade_time, ma_5..ma_250, boll_mid/upper/lower, macd_dif/dea/macd, kdj_k/d/j, observation_count, params_key, indicator_version`。

Web reader不读取 `major_index_mins_technical_state`，也不 import orchestrator 的 writer/asset/check。

Orchestrator 与 Web Reader 之间不建立运行时 import。仓库根静态合同门禁直接解析两侧源文件，并逐项比较七频率、23 个技术指标列名与类型、`params_key` 和 `indicator_version`；任何单边升级都会让测试失败，要求先完成显式合同评审。

### 16.3 Reader 结构

`major_index_mins_contract.py` 冻结 Web 只读端需要的：

1. 七个频率及 API int 频率合同。
2. Gold bars/Gold indicators 列名和类型。
3. 安全 code/date/freq regex。
4. 固定正式相对路径 builder。
5. `params_key` 与 `indicator_version` 期望值；若 Gold 合同升级，Web 合同必须显式评审同步。

`MajorIndexMinsLakeReader`：

1. 只从固定 dataset base 枚举 `trade_date=*/part-000.parquet`。
2. 对每个候选执行 resolve + `is_relative_to(lake_root)`，拒绝符号链接越界和非法分区名。
3. 按 start/end/cursor 过滤日期，倒序选取满足 limit 的最近分区，不用无界 OFFSET。
4. 每文件先 DESCRIBE 校验列顺序/类型，再 DuckDB 集合查询。
5. 结果按 `trade_date DESC, trade_time DESC LIMIT limit+1` 取页，返回前反转为升序。
6. cursor 使用版本化 base64 payload，绑定 dataset/code/freq/date/time/start/end；解析失败或与当前请求错配时返回 `ID_REQUEST_INVALID`。cursor 不含凭据或隐私数据；若后续要求防止客户端改写分页边界，再单独评审签名方案。
7. 空文件/无分区返回 DELAYED/EMPTY 合同，不返回假数据。

### 16.4 API

local router 提供：

1. `GET /index-detail/minutes`
2. `GET /index-detail/minute-indicators`

请求字段与股票分钟相似但 DTO 独立：`tsCode/freq/startDate/endDate/limit/cursor`。默认 limit 500，语法上限 10000；响应体 5MB 是更高优先级硬门禁，合法 limit 仍可能因 DTO 体积被 `ID_REQUEST_INVALID` 拒绝。

Bars 与 indicators 用相同 endDate/limit 窗口。前端不能用 `Promise.all` 让 indicators 缺失清空 bars；bars READY + indicators ERROR 应显示分钟 K 线并让技术图层 PARTIAL。

M5-B 前端同时发起同窗口 bars 与 indicators 请求，但使用 `Promise.allSettled` 或等价的独立结算，禁止 indicators rejection 让 bars promise 链失败。adapter 先验证根级 `tsCode/freq`，再把两侧按 `tradeTime` 排序并要求时间键一一对应；通过后将 Gold 字段映射到共享图表点，记录 `indicatorSource=gold`、真实 `paramsKey/indicatorVersion`。身份、重复键、数量或时间键不一致均按指标层失败处理：保留 bars，技术字段置 null，`indicatorSource=unavailable`，模块 PARTIAL。

M5-B 已删除 M5-A 的 `indexMinuteMockIndicatorProvider.ts`、`indicatorVersion=0`、`模拟指标` 标识和专属测试；当前禁止恢复开关、兼容分支或真实接口失败后的 Mock fallback。请求仍只在 Vite dev、page-init 宣布分钟能力且后端 local router 已挂载时发生；prod/staging 行为不变。

最大响应验收不得把 10000 根超过 5MB 的正确拒绝判成失败。固定算法是：先请求 10000 根；若成功，则必须小于等于 5MB且 cursor 正确；若返回响应体过大 `ID_REQUEST_INVALID`，该拒绝语义通过。随后固定请求 5000 根，必须 READY、低于 5MB、`hasMore/nextCursor` 合法、下一页时间严格早于本页首根且总耗时不超过 5s。

### 16.5 已知数据范围

当前 Gold bars 合同显式排除 `899050.BJ`。因此 local capability 表示“指数分钟功能已启用”，不保证每个 code/date 均有数据；北证50请求无有效 Gold 时返回明确 EMPTY/DELAYED，不 fallback 到 Silver、旧 Lake、日线或第三方接口。

---

## 17. 配置审计

本页不新增配置项。

| 配置 | 默认/来源 | 持久化 | 消费者 | 生效方式 | 本页用途 |
|---|---|---|---|---|---|
| `majorIndices/CN_A` | `major_indices.cn_a.v1.json` | repo JSON | 主要指数服务、详情 universe | 进程内 service cache | 10 code 唯一名单 |
| `APP_ENV` | Settings/env | env | local capability | 进程启动 | prod/local 隔离 |
| `WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED` | false | Settings/env | local capability | 进程启动 | M5 路由开关 |
| `GOLDENSHARE_LAKE_ROOT` | 空 | Settings/env | local capability/reader | 进程启动 | M5 只读根目录 |

不允许把趋势 code、25/90、权重日期、贡献公式或主要指数名单再做页面常量配置。趋势支持 code/period 属于已冻结接口能力；公式由既有 API 返回并由页面按固定视觉规则消费。

---

## 18. 性能与负载预算

### 18.1 正式 API

| API | 查询规模 | 目标 |
|---|---|---|
| page-init | identity 1 + quote 1 + dailyBasic 1 + breadth 聚合 1 | P95 <= 300ms |
| kline 300 | 300 行、27 字段、factor-only；有 MA null 时追加一次历史基数查询 | P95 <= 300ms |
| kline 2000 | 最多 2000 行、27 字段、factor-only；有 MA null 时追加一次历史基数查询 | P95 <= 800ms |
| weights | 上证当前最大 2184 个 A 股；Security INNER JOIN + daily LEFT JOIN + suspend EXISTS | P95 <= 800ms |
| trend | 既有缓存接口，默认 300 行 | 沿用既有门禁 |

所有 P95 必须在与生产拓扑等价的 Web-host -> PostgreSQL 路径复核；本地跨网络结果不冒充生产同机/同网性能。

M0 已完成数据库内基线：300 根 P95 1.636ms；2000-limit P95 2.127ms，但后者在 M0 快照只返回 388 行。它证明索引路径，不证明真实 2000 行 API payload。

### 18.2 M1 实现后生产只读历史基线

2026-08-11 使用当时 1.1.0 代码、同一 SQL 投影和显式只读事务复验 10 个指数。每个接口按 10 code × 5 轮，共 50 个样本；计时包含本机到生产 PostgreSQL、query/service、Pydantic DTO 组装和 JSON 序列化，不包含 HTTP Server 中间件。它是严格的跨网络历史基线，不冒充生产 Web-host 同拓扑 P95，也不证明 1.2.0 新增 A 股过滤与停牌 EXISTS 后的最终性能。

| 链路 | 实际行数 | P50 | P95 | max | payload max | 判定 |
|---|---:|---:|---:|---:|---:|---|
| page-init | 固定单标的 + breadth 聚合 | 161.812ms | 246.054ms | 247.276ms | 1,653 B | PASS |
| kline 300 | 300 | 126.671ms | 211.169ms | 226.565ms | 162,606 B | PASS |
| kline 2000 上限 | 455~630 | 143.777ms | 248.925ms | 263.420ms | 337,689 B | PASS（非真实 2000 行） |
| weights | 50~2224 | 184.854ms | 271.337ms | 290.305ms | 276,419 B | PASS |

精确生产 `EXPLAIN ANALYZE` 历史基线：factor-only 300 根 1.681ms，2000 上限实返 630 根 1.869ms；MA 历史基数查询 2.063ms；page-init latest daily + 同日 factor 0.071ms；1.1.0 上证 2224 成分 breadth 聚合 4.488ms，完整权重名称/行情 LEFT JOIN 12.927ms。Kline 查询均使用现有主键或日期索引；1.2.0 breadth/weights 必须在实现后以 2184 个 A 股、Security 过滤与 suspend EXISTS 的最终 SQL 重跑计划、P95 和 payload，不能沿用这两个旧查询数值宣称通过。

#### 18.2.1 DTO 1.2.0 最终查询复验

2026-08-12 以页面最新日 `2026-08-11`、权重日 `2026-07-31` 执行显式只读复验。上证最终 SQL 得到 total/matched 2184、up 648、flat 51、down 1485、missing 0；完整五计数 breadth 聚合 `EXPLAIN ANALYZE` 约 21.993ms，完整 A 股 weights 查询约 19.290ms。停牌子查询只在两条 daily 缺失 A 股上执行索引探测；breadth 的四个统计表达式共 8 次命中索引，未出现逐行全表扫描。

10 指数各 5 轮完整 query/service/Pydantic/JSON 链（跨网络，不含 HTTP 中间件）结果：

| 链路 | 样本 | P50 | P95 | max | payload max | 行数范围 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---|
| page-init 1.2.0 | 50 | 161.268ms | 245.589ms | 250.582ms | 1,653 B | 固定单标的 | PASS |
| weights 1.2.0 | 50 | 174.976ms | 267.319ms | 313.282ms | 275,543 B | 50~2184 | PASS |

以上结果证明新增 A 股过滤和停牌解析未造成性能回退；生产 Web-host 同拓扑验收仍按统一发布门禁执行。

### 18.3 Payload

1. page-init 目标 < 20 KiB。
2. kline 300 目标 < 250 KiB；2000 根需记录实际大小。
3. weights 完整批次目标 < 1 MiB；超过即停下评审 DTO，不截断数据掩盖。
4. trend 沿用既有 limit <= 2000。

### 18.4 前端

1. weights 全量数组只保存一份 API DTO/一份轻量 ViewModel，避免多次深拷贝。
2. 可视 DOM 只渲染 10 行 + overscan。
3. trend primitive 只绘当前可见范围，避免每次 crosshair move 重算全历史几何。
4. shared chart effect 的依赖使用稳定 memo，避免 Tab 切换重建四个 chart。

---

## 19. 测试设计

### 19.1 后端单元测试

新增：

```text
tests/test_index_detail_field_mapper.py
tests/test_index_weight_contribution_builder.py
tests/test_index_detail_status_resolver.py
tests/test_major_index_mins_reader.py            # M5
tests/test_major_index_mins_contract_alignment.py # M5-B contract gate
tests/test_index_minute_gold_audit.py             # M5-B read-only acceptance
```

覆盖：

1. `pct_change/kdj_bfq` 等精确字段映射。
2. amplitude 正常、null、preClose=0。
3. 贡献正/负/零、缺输入、4 位 ROUND_HALF_UP。
4. 权重不归一化、不缩放。
5. status 优先级和 reason。
6. breadth 等式；B 股不进入 total/missing；A 股 daily 优先；精确日停牌进入 matched/flat；真实 missing 不进 flat。
7. minute path 越界、非法 cursor、schema/type、partition/date 不一致。
8. Orchestrator/Web Reader 七频率、23 列、参数键和版本一致，且生产运行时无 Orchestrator import。
9. 正式 Gold 缺失输出 `SOURCE_NOT_READY`；fixture 已覆盖七频合同、重复键、版本错误和缺失隔离，正式验收已覆盖分区、唯一键、Gold bars/Gold indicators 时间键对齐和 Query Service 序列化性能。

### 19.2 后端真实 API fixture

新增 `tests/web/test_wealth_index_detail_api.py`，按现有 Web DB fixture 创建：

1. `TradeCalendar`
2. `IndexBasic`
3. `IndexDailyServing`
4. `IndexDailyBasic`
5. `IndexFactorPro`
6. `IndexWeight`
7. `EquityDailyBar`
8. `EquitySuspendD`
9. `Security`（测试数据必须显式提供 `security_type/exchange/curr_type`，证明 A 股过滤不依赖代码前缀）

至少覆盖：

1. 10 配置 code page-init 成功；第 11 code 404。
2. identity 缺失 404，配置错误 fail closed。
3. 默认/显式 tradeDate，latest <= expected，DELAYED。
4. quote EMPTY 后不返回 mock。
5. dailyBasic 同日缺行/单字段 null。
6. breadth up/flat/down/missing 和两条数量恒等式；B 股排除、停牌 A 股按 flat、daily 与停牌同时存在时 daily 优先、无两类证据只计 missing，不单独触发 PARTIAL。
7. kline 只允许 day、不接受 adjustment、升序、limit 边界。
8. 因子 null 保持 null，KDJ J 映射正确，不返回 MA15/MA120。
9. 权重日期、完整 A 股子集、贡献点正/零/负/null 降序、null 置底、同贡献 weight/code 决胜、B 股不进入 rows/coverage、名称缺失、停牌 pct/贡献为 0、真实 null pct、preClose 缺失。
10. 非 100% 权重和不归一化；贡献和实际指数涨跌不对账。
11. 401/403/400/404/500 映射。
12. debug=false 固定返回 `debugInfo=null`；debug=true 只列冻结的模块状态与异常，不回 SQL/Lake 绝对路径/环境变量/连接信息/凭据或 exception repr。

### 19.3 旧契约回归

1. `tests/web/test_wealth_stock_detail_api.py`：响应 key 和行为不变。
2. `tests/web/test_quote_trend_channel_api.py`、`tests/test_quote_trend_channel_query_service.py`：SSE-only 合同不变。
3. 主要指数 API 测试：10 卡顺序和响应无字段漂移。
4. `src/app/api/v1/router.py`：prod 不包含 index minute route，local 条件下同时包含 stock/index minute route。

### 19.4 前端单元/组件测试

新增：

```text
wealth/src/app/routes/routerState.test.ts
wealth/src/pages/index-detail/IndexDetailPage.test.tsx
wealth/src/features/index-detail/api/indexDetailViewModelAdapter.test.ts
wealth/src/features/index-detail/api/trendChannelAdapter.test.ts
wealth/src/features/index-detail/chart/trendChannelGeometry.test.ts
wealth/src/features/index-detail/api/indexMinuteViewModelAdapter.test.ts
wealth/src/features/index-detail/controller/useIndexMinuteSeries.test.tsx
wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.test.tsx
```

覆盖：

1. 10 卡导航、trim/upper/encode、前进后退。
2. Loading/Empty/Error/Partial/Forbidden/404/Delayed。
3. page-init 403/404 后 kline/trend fetch 次数为 0。
4. 上证请求 snake_case trend URL；其余 9 code 不请求。
5. 快速切 code 时旧响应不能覆盖新页面。
6. 15 项顺序、下跌数半宽、null 为 `--`、无旧字段。
7. 权重第一次激活才请求；cache、retry、完整 rowcount、末行可达。
8. Technical 的技术结论为 `--`；九转按固定 day/15/30/60/90/120 六周期 capability 展示 `latestMarker`，未开放/源空/无 marker 为 `--`，没有主观建议。
9. trend N 点 segment 数量、每日竖线、四种颜色、等于下轨边界、缺日断开。
10. trend error 不清空 kline/basic。
11. line/histogram null 不被送成 0。
12. StockChartWorkspace 的 shared 可视范围、crosshair、tooltip、MA/BOLL 回归；45/120/180 根、overlay/resize/append 不重置或错置范围均已由 shared 测试覆盖。
13. system 状态色不使用 market up/down token。
14. 本地七频率、按频率缓存、Abort/request id 防串标、真实 Gold 指标、无 Mock 标识、bars-only PARTIAL 与北证50局部空态。
15. shared chart 的 minute 时间轴、Asia/Shanghai crosshair、自适应首屏与日线模式回归；1600px 必须为 120 根。

### 19.5 真实 API 与像素验收

1. 本地启动真实 Web + Wealth，不使用 mock/scaffold fallback。
2. 逐一点击 10 卡；重点验收上证、深证、创业板、沪深300、北证50。
3. 1600×1200 对比 Basic、Weights、Technical 和五状态基线。
4. 普通 UI 元素偏差 <= 2px；字体、颜色、圆角、间距一致。
5. 图表、坐标轴、趋势、Tooltip、十字线不得因右栏或状态切换位移。
6. Weights 表头固定、视窗恰好 10 行、可滚到全量末行。
7. Partial 用至少两组不同缺失字段 fixture，证明提示非写死。
8. M4 当时的本机截图曾位于 `/private/tmp/goldenshare-index-detail-m4/`；这些 session-local 临时文件现已不存在，只保留为历史执行记录，不作为 2026-08-22 的可复核证据。
9. M5-A 当时的本机截图曾位于 `/private/tmp/`；这些 session-local 临时文件现已不存在，只保留为历史执行记录。北证50局部空态与切回日线仍由浏览器 DOM 和页面回归测试验收。
10. 日线与分钟量测完全一致：图表 `1193.203125×1038 @ (10,152)`，右栏 `376.796875×1038 @ (1213.203125,152)`，页面 `1600×1200` 无水平/垂直溢出。

验证命令：

```bash
pytest -q tests/web/test_wealth_index_detail_api.py \
  tests/test_index_detail_field_mapper.py \
  tests/test_index_weight_contribution_builder.py \
  tests/test_index_detail_status_resolver.py \
  tests/web/test_quote_trend_channel_api.py \
  tests/test_quote_trend_channel_query_service.py \
  tests/web/test_wealth_stock_detail_api.py

cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
```

M5 另加 reader、local route 和临时 Parquet 真实查询测试，不与 M1-M4 混为一个退出门。

---

## 20. 实施顺序与提交边界

| 里程碑 | 修改范围 | 退出条件 | 建议提交边界 |
|---|---|---|---|
| M0 | LLD、异常码、生产 factor 审计、DTO 签字 | 门禁清零 | docs/audit only |
| M1（已完成） | schema/query/mapper/page-init/kline/weights API | 后端真实 API + 旧契约回归 + 生产只读性能复验通过 | backend index detail |
| M2（已完成） | shared chart 提取 + stock adapter | 股票视觉/交互零回归 | shared chart refactor |
| M3（已完成） | route、10 卡导航、Loaded、三 Tab、trend primitive | Loaded 三画板、真实 API、2224 行滚动与 9 code 零趋势请求通过 | index detail loaded |
| M4（已完成） | 五态、404、Delayed、模块 retry | 状态测试、逐画板截图、真实 Partial 与 1600×1200 尺寸验收通过 | index detail states |
| M5-A（已完成） | local reader/router/minute chart | Silver 合同/性能、local/prod 矩阵、可见 Mock 指标 | index local minutes |
| M5-B 准备（已完成） | 70 checks 注册、跨边界合同门禁、七频率异常 fixture、只读正式验收入口 | 静态合同一致；正式 Gold 缺失时明确 `SOURCE_NOT_READY` | index minute indicators readiness |
| M5-B 正式数据验收（已完成） | Gold 覆盖、全量对齐、默认性能、最大响应 | 29,939 分区对零失败、630 样本 P95、10000/5MB 拒绝语义和 5000 cursor | index minute indicators readiness |
| M5-B 最终切换（已完成） | 真实 provider、删除 Mock | bars/indicators 独立结算、Mock 引用清零、前端/浏览器回归 | index minute indicators |
| M6（已完成） | 全回归与 prod smoke | prod 仅日线、无分钟 route | release verification |

每个里程碑只处理一个清晰目标。M2 必须在 M3 前独立验收，M5 不得成为 M1-M4 的隐含依赖。

---

## 21. 方案逐条对账

| 方案硬口径 | LLD 落点 | 测试落点 |
|---|---|---|
| 独立 index-detail BFF | 6、7、8、9 | 19.2 |
| 10 卡导航 | 7.4、14.1 | 19.4 |
| 默认日线、无前复权 | 8.3、14.4 | API 参数负例 + DOM |
| 三 Tab 稳定骨架 | 15 | Tab/ARIA/不重建图表 |
| 15 项基本行情 | 10 | 顺序/null/旧字段负例 |
| 成分涨跌统计 | 9.2 | 聚合与恒等式 |
| 权重完整批次/10 行滚动 | 8.4、9.4、15.3 | 长批次 + 虚拟滚动 |
| 贡献公式不归一化不对账 | 8.4 | Decimal 单测/真实 API |
| SSE-only 趋势 | 11 | 9 code 零请求回归 |
| 每日竖线与逐日四色 | 11.4/11.5 | geometry 线段计数 |
| 技术结论留空/九转独立接入 | 15.4 | 技术结论 `--`；九转按 capability/API 请求与局部状态回归 |
| 五个完整状态 | 13.4 | 页面测试 + 像素截图 |
| local minute/prod 404 | 16 | route 矩阵/临时 Parquet |
| 共享图表无复制 | 12 | stock 回归 + import 审计 |
| 交易计划仅用户点击 | 14.5 | effect 不触发 action |

---

## 22. 风险、阻断条件与后续评审

| 风险/阻断 | 当前事实 | 处理 |
|---|---|---|
| factor 实际历史仍少于 2000 根 | 2026-08-22 九个指数 881 根、A500 464 根，无法产生真实 2000 行 payload | 按 `N/A — accepted physical limitation` 关闭；2000 保留为参数上限，当前最大历史性能已通过，未来自然达到后进入常规回归 |
| 深市两源量额分叉 | 399001/399006 自 2026-07-06 起 factor 与 daily 不同 | 外部核对确认 factor 准确；指数详情统一取 factor，禁止 daily fallback 或倍率换算 |
| 历史回填改变 MA 可计算边界 | 若把某次 A500 前缀空值固化为 code/date 规则会产生错误 | 当前实现按实际有效历史根数动态判断；2024 回填后的复审证明达到周期后的异常 null 为 0，后续回填继续自动重分类 |
| 趋势旧契约命名不同 | snake_case，与 Wealth DTO 风格不同 | feature-local adapter，不改旧 API |
| 趋势 state 与视觉颜色不同 | 后端是迟滞状态，页面是 close/lower | 明确忽略 state 判色并做冲突样本测试 |
| 上证官方权重批次 2224 行、页面 A 股子集 2184 行 | API/DOM 可能膨胀；误把 B 股算缺失 | ORM 事实字段过滤 + 集合查询 + <1 MiB + 虚拟化；A 股权重不归一化 |
| dailyBasic 只覆盖部分指数 | 4 个指数当前无行 | null/`--` 是正式合同，不 fallback |
| 上证当前 40 个 B 股源行和 2 个停牌 A 股缺日线 | 旧实现误报 42 missing/PARTIAL | B 股不进入页面集合；停牌 A 股按 flat，当前验收为 total/matched 2184、648/51/1485、missing 0 |
| shared chart 改动股票 | M2 已拆为 477 行 shared engine、362 行 stock adapter，并补 null-safe series | 已通过独立组件测试、全量 Wealth 回归和 1600×1200 前后尺寸对账；M3 只新增 index adapter/primitive |
| Figma 旧节点冲突 | `425:190` 仍有旧字段 | 永久排除出金标 |
| Gold minute 数据与前端来源切换不同步 | 已完成正式 technical/state 全历史与性能验收，前端也已切真实 Gold | bars/indicators 独立结算；Gold 短暂落后时保留 bars 并显示 Partial，不回退 Mock |
| 北证50无 Gold canonical bars | 当前合同显式排除 | local 返回 Empty/Delayed，不 fallback |
| shared capability 错误码含 `SM_` | 历史股票命名 | 只作启动错误；不作为 index HTTP 语义复用 |

### 22.1 进入编码前必须确认的检查项

1. [x] 本 LLD 已完成产品、后端、前端评审，并按批准方案进入 M1-M4。
2. [x] 10 指数 factor 审计、最终 SQL、完整服务链和当前实返 payload P95 通过；真实 2000 行因物理历史不足按 `N/A — accepted physical limitation` 关闭。
3. [x] page-init/kline/weights DTO `1.3.1` 已冻结；字段集不变，成分集合、停牌解析与贡献排序语义已收紧。
4. [x] 贡献输出按 4 位舍入、UI 2 位的精度规则已冻结。
5. [x] 异常码已登记。
6. [x] shared chart M2 的股票测试、1600×1200 结构量测和当时截图验收已完成；历史 `/private/tmp` 文件现不可作为长期证据。
7. [x] Figma `414:447` 权重行高已从节点属性实测为 40px；实现使用 400px 十行视窗。
8. [x] M5-A 正式 Silver 合同与物理数据验收通过；Gold 不作为 bars 前置。
9. [x] M5-B 前 Gold 70 checks 已由 Definitions 正确发现；跨边界合同和 fixture 防漂移门禁已建立。
10. [x] M5-B 正式 Gold 物理文件、Silver 时间键全量对齐和默认 500 根性能通过；10000 为语法上限，5MB 正确拒绝与固定 5000 根正常分页共同构成最大响应门禁。
11. [x] M5-A 正式 Silver 七频率性能、10000 根响应、local/prod 路由、前端缓存/竞态与 1600×1200 浏览器验收通过。
12. [x] M5-B 前端真实 provider、bars-only PARTIAL、Mock 引用清零与 1600×1200 浏览器回归通过。

以下两条为 P10 切换前的 M5-B 日期化历史验收，保留用于解释 Gold technical 上线过程；它们不再代表当前业务 Reader 的 bars 数据源。

2026-08-12 M5-B 准备批次执行结果：分钟 Reader/合同/API/验收工具相关 42 项测试通过，子系统边界 14 项通过，Ruff、文档完整性和 diff 检查通过。正式只读预检观测到 Silver 七频率各 4,276 个分区、Gold technical 七频率均 0 个分区，因此状态保持 `SOURCE_NOT_READY / IM_SOURCE_NOT_READY`，性能矩阵尚未执行，也不得被标记为通过。

2026-08-13 最终批次结果：Definitions 为 14 assets/70 checks；Silver/Gold technical 七频率各 4,277 个分区，29,939 个频率-日期分区对完成全历史 schema、版本、有限值、唯一键和双向时间键检查且零失败；Technical/state 共 59,878 个文件、10,150,506 行。九个页面可用指数 × 七频率 × 10 次共 630 个默认 500 根样本全部 READY，频率级 P95 282.243–322.982ms。10000 根因超过 5MB 正确拒绝，5000 根返回 3,181,443 bytes、cursor 有效且耗时 334.441ms。前端 155 项全量测试、构建和 1/60/120 分钟真实浏览器回归通过；页面无 Mock 标识，日线/分钟图表区和右栏几何差值为 0px。

2026-08-15 发布边界验收确认生产环境仅挂载指数日线能力，指数分钟路由保持 404；2026-08-22 最终复验再次确认该边界。九转 M6-B～M6-D 已完成，不改变指数分钟 Reader/API、前端或图表的完成状态。

### 22.2 2026-08-22 最终生产验收

1. 生产 `dev-interface@57ece8a3` 工作区干净且与远端一致，并包含 `874f647b` 权重贡献排序、`673161cf` 固定六周期摘要和指数九转接入。
2. 十指数 factor 最新日均为 2026-08-21、重复键为 0；九个指数 881 根，A500 464 根。2024 可用历史与 daily 双向零缺口，达到对应周期后的异常 MA null 为 0。
3. 数据库 factor-only 300/当前最大窗口 P95 为 0.799/2.326ms，历史基数 P95 0.718ms；生产 Web 主机同拓扑 page-init/Kline 300/当前最大窗口 P95 为 26.649/17.373/78.741ms，均通过预算。
4. 真实 2000 行按 `N/A — accepted physical limitation` 关闭；2000 继续作为 API 参数上限并保留边界测试。
5. 十指数日线九转 50 次真实服务请求全部 200/READY、300 根完全对齐，P95 12.795ms；`000680.SH` 为 404，生产分钟 K 线、指标与九转路由均为 404。
6. 用户于 2026-08-22 完成当前生产页面视觉检查并批准收口。本轮没有新的持久截图；旧 `/private/tmp` 记录不再作为当前证据。

---

## 23. 边界与依赖矩阵影响

1. `foundation -> biz/ops/app`：无反向依赖。
2. `biz -> foundation`：新增只读模型消费，方向合法。
3. `app -> biz`：只新增路由挂载。
4. `wealth -> /api/v1`：新增独立 index contract，不扩股票或主要指数 contract。
5. `lake_console/orchestrator`：M1-M4 无修改；M5 Web reader只按稳定物理合同读取。
6. M2 将股票日线图表主实现收敛为 `StockChartWorkspace -> DetailChartWorkspace`，属于 Wealth 内部共享 UI 入口变化，不改变 API contract 或跨子系统依赖方向；已同步 `docs/architecture/codegraph-architecture-snapshot.md` 的 Wealth 关键入口。

---

## 24. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.22 | 2026-08-22 | 最终收口指数详情 LLD：同步当前生产 SHA、2024/动态 MA、数据库与 Web-host 同拓扑性能、真实 2000 行 N/A 边界、权重排序、九转 M6-D、固定六周期与用户视觉验收；历史临时截图不再冒充持久证据 | Codex |
| v1.21 | 2026-08-17 | 权重最终排序从源 weight 顺序改为 service 在贡献点四位舍入后按数值降序、null 置底、weight/code 决胜；SQL 与前端不复制排序公式 | Codex |
| v1.20 | 2026-08-16 | 收敛指数分钟完成状态：修正当前 Gold bars 路径、12 列物理合同、Gold-to-Gold 对齐与真实指标测试；M6 发布边界验收完成，并将九转后续运维阶段从指数分钟未完成项中剥离 | Codex |
| v1.19 | 2026-08-15 | 同步 M6-0 通过：生产路由与配置基线、platform-only 发布边界及 M5 定向回滚已冻结；板块测试竞态修复后 Wealth 全量回归通过，M6-A 仍待独立批准 | Codex |
| v1.18 | 2026-08-15 | 同步 S7/M5 当前实现：page-init capability 升级为 `supportsNineTurn=true + nineTurnPeriods`，Technical day/60/30 消费独立九转摘要并保持技术结论为空；M6 发布尚未开始 | Codex |
| v1.17 | 2026-08-14 | 完成 P10：正式 reader 与 capability 统一只读 Gold bars/indicators，无 Silver fallback；同步七频业务合同、时间键对齐和浏览器验收边界 | Codex |
| v1.16 | 2026-08-13 | 完成 M5-B 真实 provider、bars-only Partial、Mock 清零和 1600×1200 浏览器回归；更新最终 4,277×7 分区验收与性能证据 | Codex |
| v1.15 | 2026-08-13 | 回填 M5-B 正式 Gold 全历史、Definitions、Dagster 后审计与性能证据；冻结 10000/5MB + 5000 cursor 验收算法，以及真实 provider 独立结算、bars-only PARTIAL 和 Mock 清零的编码落点 | Codex |
| v1.14 | 2026-08-12 | M3 对账：四类详情图表已统一 shared 生命周期、稳定 dataKey、45～180/15 和 1600px 默认 120；API、趋势与状态合同不变 | Codex |
| v1.13 | 2026-08-12 | 同步详情图表后续方案：先收敛股票分钟独立生命周期，再统一实现 45～180 根、15 根步长和 1600px 默认 120 根；API/趋势合同不变 | Codex |
| v1.12 | 2026-08-12 | 完成 M5-B 准备：确认 Definitions 发现 14 个 Gold 资产与 70 个 checks，冻结 Orchestrator/Web Reader 静态合同门禁、七频率异常 fixture 和正式 Gold 只读验收入口；物理覆盖、对齐、性能及前端切换仍待正式文件 | Codex |
| v1.11 | 2026-08-12 | 完成 A 股过滤、daily 优先与停牌 fallback 查询实现；22 项指数 API、83 项后端相关、108 项 Wealth 回归通过；最终上证为 2184/648/51/1485/0，页面 READY，服务链与 payload 通过门禁 | Codex |
| v1.10 | 2026-08-12 | 收紧成分口径：权重与涨跌统计仅消费 Security 事实字段认定的 A 股；B 股不进入 rows/coverage/missing；A 股精确日 daily 优先，缺 daily 且有停牌证据时按 flat、贡献 0；补 SQL、异常和负向测试门禁 | Codex |
| v1.9 | 2026-08-11 | 完成 M5-A：按日分区正式 Silver Reader、独立分钟 DTO/API、统一 capability、七频率 controller/cache、Mock v0 provider、共享 minute 时间模式、Tooltip/局部空态；正式 P95、10000 根与浏览器尺寸证据回填 | Codex |
| v1.8 | 2026-08-11 | 冻结 M5-A/M5-B：正式 Silver 先提供本地分钟 K 线，前端使用可见且隔离的开发态 Mock 指标；Gold 脏工作流、70 checks、物理与对齐留待 M5-B | Codex |
| v1.7 | 2026-08-11 | 完成 M4：新增页面状态解析、Empty view model、五态组件与模块状态组件；page-init/kline/trend/weights 分层归并，支持请求中止、整页/局部重试和响应驱动 Partial 文案；完成五态、404、Delayed 浏览器截图与 1600×1200 尺寸验收，并通过 100 项 Wealth 与 82 项后端相关回归 | Codex |
| v1.6 | 2026-08-11 | 完成 M3：路由/10 卡、真实 API controller、15 项基本行情、三 Tab、权重懒加载缓存与 40px×10 虚拟滚动、逐日四色趋势 primitive 落地；通过 1600×1200 结构量测、2224 行末行、9 code 零趋势请求、83 项 Wealth 与 67 项后端回归 | Codex |
| v1.5 | 2026-08-11 | 完成 M2：提取 shared detail chart engine/pane/types/series/formatters/CSS，股票 adapter 保留领域文案、单位与交互；新增 null 断点/省略、四面板、90 根、crosshair、tooltip、MA/BOLL 测试，并记录 1600×1200 前后结构量测完全一致 | Codex |
| v1.4 | 2026-08-11 | 完成 M1 后端：独立三接口、严格参数/异常映射、factor-only Kline、动态 MA 历史判断、完整权重贡献；补 10 code 真实路由、源字段负例、旧契约回归及生产只读性能复验 | Codex |
| v1.3 | 2026-08-11 | 外部核对确认 factor 量额准确；page-init 同日量额与 Kline 全量额统一取 factor，删除 Kline daily JOIN，补 page-init 精确 JOIN、fallback 负向门禁与性能复验；DTO 提升为 1.1.0 | Codex |
| v1.2 | 2026-08-11 | 修正 MA null 低层口径：删除 A500/固定日期特例；增加按实际历史根数判断的条件查询、PARTIAL 规则和性能复验门禁；DTO 提升为 1.0.1 | Codex |
| v1.1 | 2026-08-11 | 完成 M0：落生产因子覆盖/性能审计、冻结独立 DTO 1.0.0、登记异常码；记录深市量额分叉、当时 A500 MA250 空值与真实 2000 行性能限制；量额最终来源已由 v1.3 修订 | Codex |
| v1 | 2026-08-11 | 基于最新 Figma、三件套、当前代码、CodeGraph、生产字段审计与分钟 Lake 合同形成首版 LLD；冻结文件结构、DTO、SQL、状态机、趋势 primitive、共享图表、测试和实施顺序 | Codex |


## 2026-10-20 右栏提示遮挡修订（编码前）

IndexInfoRail将原partial/delayed提示渲染在.index-right-tab-content首部；index-detail-page.css移除.index-data-notice绝对定位及补偿坐标，使用普通内容与--cs-space-10底部间隔。IndexDetailPartialNotice及状态/接口不变，修改范围限右栏布局。IndexDetailPage既有Partial/Delayed测试补当前tabpanel包含且先于正文、页签切换及Ready无提示；真实Partial浏览器检查文字与矩形无交叠。根因/预算/保存与验收详见XXM LLD§38.4，不将模拟状态声称真实源验收。


<a id="index-constituent-missing-quote-20261020"></a>
## 25. 成分行情缺失展示修订 LLD（2026-10-20 实施，2026-11-04 用户验收通过）

### 25.1 目标、范围与当前证据

对应[实施方案 §15](./index-detail-implementation-design-v1.md#index-constituent-missing-quote-plan-20261020)。管理员已确认取消仅成分缺行情产生的两处提示和对应 PARTIAL 判断；月度成分保留、缺失贡献显示 `--`，不新增价格列。管理员已在文档确认后授权本步开发；以下门禁从待执行开始逐项回填，部署不在本轮范围。

当前 `IndexDetailQuery.load_breadth/load_weight_rows` 已按同一 A 股范围读最新有效批次，日线优先、同日停牌补充；缺行情行已经保留，贡献计算返回 null，`IndexWeightsTab.formatContribution` 已显示 `--`。错误发生在状态及提示：page service 将 breadth missing 同时传给 breadth 和页面 PARTIAL；weights service 将总贡献缺失数作为 PARTIAL；前端又由 missingCount 生成页面提示，并在 weights phase=partial 时显示列表提示。不能只删一段文案而留下泛化提示或错误状态。

### 25.2 目标状态及数值

| 情况 | 目标行为 |
|---|---|
| 成分有效涨跌幅存在 | 依其正/零/负计入 up/flat/down，按原公式计算贡献 |
| 无涨跌幅但同日有 `suspend_type=S` | 按 0%/FLAT 与贡献 0 处理，不受本次修订影响 |
| 无有效涨跌幅且无停牌依据 | 保留成分；`changePct=null`、`direction=UNKNOWN`、`contributionPoint=null`；显示 `--`，不计入 up/flat/down |
| 只有上述成分缺行情，其它输入完整 | breadth READY；page-init/weights 按原观测日期返回 READY 或 DELAYED，不再仅因 missing 为 PARTIAL，不显示两处缺失提示 |
| 指数昨收为空 | weights 仍 PARTIAL，仍产生 `ID_WEIGHT_CONTRIBUTION_PARTIAL` 并显示原局部说明，不伪造贡献 |
| factor/dailyBasic 缺失、无权重批次、日期落后或接口异常 | 保留原 PARTIAL/EMPTY/DELAYED/HTTP 错误及提示，不批量关闭提示 |

`up+flat+down=matched`、`matched+missing=total`、`contributionAvailableCount+contributionMissingCount=totalCount` 不变。没有成分批次与已有批次但成分缺行情必须区分；不增加比例阈值或股票/日期特例。即使批次内所有成分都无行情，也保留名单与真实缺失数，不将它们伪计 flat；此情况同样不能仅因成分缺行情产生提示。

### 25.3 逐文件变更和消费者

| 位置 | 已实施内容 / 已核验消费者 |
|---|---|
| `src/biz/queries/wealth/market/index_detail/index_detail_page_query_service.py` / `build_page_init` | breadth 的 partial 不再由 missingCount 决定；页面 partial 条件去掉 breadth missing，保留 factor、dailyBasic、无批次判断；停止产生 breadth_partial 异常；debug breadth missingCount 仍为真实值 |
| `src/biz/queries/wealth/market/index_detail/index_detail_weights_query_service.py` / `build_weights` | coverage 仍按实际可计算贡献计数；PARTIAL 与异常触发改由指数昨收缺失决定，不能再用总 missing_count 代替；保留原排序、行和缺失值 |
| `src/biz/services/wealth/market/index_detail/index_detail_exception_builder.py` | 审计并清除停止产生的 breadth_partial 调用/方法；保留其它异常；统一注册表保留历史记录，不新增同义码 |
| `src/biz/schemas/wealth/market/index_detail.py`、`wealth/src/features/index-detail/api/indexDetailApiTypes.ts` | 字段、数值/null 类型不变；旧 breadth 异常码的类型声明只保留作已登记代码，不再允许服务实际产生；同步合同目标版本和测试，不保留旧状态行为 |
| `wealth/src/features/index-detail/model/indexDetailState.ts` / `collectIndexPartialReasons` | 去掉由 breadth missingCount 拼出的提示；不能以“部分基本行情”替代；其它实际缺字段和 K 线提示保留，页面 phase 继续消费后端状态 |
| `wealth/src/features/index-detail/controller/useIndexDetailController.ts`、`controller/useIndexWeights.ts` | 验证状态与缓存消费使用新响应；不加前端覆盖后端状态的判断，不改缓存键、请求或重试流程 |
| `wealth/src/features/index-detail/sidebar/IndexWeightsTab.tsx` | 无行情的行沿用现有 `--`；仅成分缺行情时由新 READY/DELAYED 状态自然不显示 PARTIAL 提示；保留指数昨收缺失时的 PARTIAL 提示和 error/empty/delayed，不新增列或 CSS 改版 |
| `IndexInfoRail`、`IndexDetailPartialNotice`、`indexDetailViewModelAdapter.buildBasicMetrics` | 作为消费者核验；保留其它提示位置、15 项指标和涨跌数展示；不因 missing 清空已计算计数 |

已使用仓库根 CodeGraph `codegraph_explore` 和 `codegraph_impact(collectIndexPartialReasons)`，并核对当前 query/service、exception builder、后端 schema、TS 类型、controller、sidebar、页面与 API 测试。图中出现的通用 `load` 同名候选不据此扩大修改范围；当前代码引用表明实际影响限于指数详情 `page-init/weights` 及本页消费者。无 Foundation、Ops、股票详情、主要指数首页 API 或 XXM 数学/接口变更。尚需人工确认的是改后真实页面视觉和验收结果，不是新增产品规则。

### 25.4 配置、读写、失败与性能边界

- 不新增、修改或安装配置/依赖；沿用现有 majorIndices 名单与页面请求。无业务表、状态表、Lake 或自动任务写入，后端仍为只读查询。
- 沿用现有集合 SQL，不新增查询，不把完整成分逐行补查；内存与单次完整成分响应相关，沿用固定 10 行视窗和虚拟滚动，不新增常驻缓存或后台任务。
- 沿用 §18 的 page-init P95 ≤300ms、weights P95 ≤800ms、payload ≤1 MiB 门禁；成分数量随最新批次变化，2184/2190 是历史样本，不作为截断上限。对同一有界样本复核，不进行全数据集扫描。
- 请求取消、失败、重新加载与局部重试沿用现有生命周期；中断无需数据恢复或数据库续跑。重试仍只重新读取原请求，page-init 和 weights 分别沿用首次读取的预算，不增加扫描范围；记录首次、重试及最后验收各自耗时，不把接口 P95 相加冒充整页性能。
- 最后验收限定一个正常指数和有缺失的上证样本，每个接口各 5 次只读请求，记录实际行数、缺失数及耗时，共不超过 20 次请求。验收调用单次最长等待 5 秒，仅作为验收的停止条件，不修改产品请求超时或新增配置；遇失败先记录并停止该样本，每个失败样本最多补查一次，不反复压测。包括补查在内该有界核验预算不超过 2 分钟；现有全量测试、typecheck/build 和浏览器人工检查的时间另记，不冒充接口性能。
- 本轮未执行真实 API 验收或部署，也不授权生产写入；后续核验遵守已授予的有界只读权限，不运行同步或修数。

### 25.5 测试输入的独立依据

字段以当前 `IndexWeight`、`Security`、`EquityDailyBar`、`EquitySuspendD` ORM 及现有 query 投影为准，不靠消费者反推。真实例子使用实施方案 §15.1 的 Prod 只读结果；该快照只证明数据接入边界，尚不能证明修改后的 API 或页面。

隔离 API fixture 使用可人工核算的四个 A 股成分：权重分别 10/20/30/40，涨跌幅分别 +1%/-2%/无日线但有同日 S/无日线且无 S，指数昨收 1000。字面预期为 up=1、flat=1、down=1、matched=3、missing=1，贡献分别 1/-4/0/null，排序为 1、0、-4、null；不得调用待测 helper 产生 expected。额外 B 股行必须被原 A 股条件排除；退市状态的 A 股行只要仍在所选批次就保留。真实缺失、确认停牌、零涨跌及指数昨收缺失分开造例。

### 25.6 编码与本地验收门禁（已完成，生产发布另验）

| 硬口径 | 测试/验收落点 | 当前状态 |
|---|---|---|
| 缺行情保留成分、null 和覆盖数，不删退市行、不补零、不加价格列 | `tests/web/test_wealth_index_detail_api.py` 的完整 rows/coverage/状态断言；页面三列表格及 `--` | 已实施，相关回归通过 |
| 仅成分缺行情不 PARTIAL，也不产生两处提示或泛化提示 | 同一 API 测试对 page-init/breadth/weights 状态、debug 缺失数和异常码断言；`wealth/src/pages/index-detail/IndexDetailPage.test.tsx` 对 ready 与 missing 组合断言 | 已实施，相关回归通过 |
| 日线优先、停牌 flat/0、真实 missing 不计平盘，排序不变 | 原 API/贡献 builder 测试及 §25.5 独立金样本；覆盖 daily 与 S 同时存在的反例 | 已实施，相关回归通过 |
| 只取消成分缺行情提示，不隐藏其它异常 | API 与页面分别覆盖 preClose null、factor/dailyBasic null、无批次、delayed、HTTP 500；混合缺失时只提示仍适用的问题 | 已实施，相关回归通过 |
| missingCount=0、正常变动的正/负/零行情与旧正常路径不受影响；全部成分无行情仍保留完整名单 | API/页面正常、部分缺失、全部缺失三组；覆盖 debug=0/1、页签切换和缓存后重新进入 | 已实施，相关回归通过 |
| 测试不只 mock 待验收边界 | 现有 Web 数据库 fixture 走真实路由、query/service/DTO；另以有界只读样本复核新 API，前端请求真实后端并确认两处不再提示、列表与其它有效提示正常 | 本机真实只读接口与页面通过；生产同拓扑待发布复验 |
| 新旧口径一次迁移 | 原测试中 missing 导致 PARTIAL/异常的断言逐项改到新口径，保留独立数值依据；注册表/合同/前端消费者同步，不能靠删断言或吞异常通过 | 已实施，相关回归通过 |
| 模块通用清单 | §25.1/25.3 覆盖交付事实与后端归一；§25.2/25.6 覆盖状态、显示、真实 API/页面；§25.4 覆盖查询/性能与读写；本轮无新增组件/视觉稿/配置，沿用当前表格和提示布局，无新增例外 | 本步代码与本地技术验收完成，无新增例外；未部署 |

执行顺序：先核验并更新后端 API 契约测试及两个 query service，再同步前端提示和页面测试；保留其它异常反例。用现有环境运行相关后端测试、Wealth typecheck/test/build，再进行上述有界真实 API 与页面验收。只有修复前会因原问题失败、修复后通过的回归和真实边界核验均完成，才回填完成状态。原 §19、M2 旧勾选和历史测试数量不能作为本修订通过证据。


### 25.7 开发与本地技术验收记录（2026-10-20，未部署）

**实现已完成，本地技术验收通过；未提交、未部署、未写 Prod。** 原常驻本地 8000 进程仍加载旧后端；本轮没有重启该进程。新状态的长期本地生效需要重新加载后端，生产生效需要另行发布。

1. 后端只改 `build_page_init` 的 breadth/page PARTIAL 与异常判断、`build_weights` 的 PARTIAL 触发条件及异常说明，清除无调用的 `breadth_partial` 方法。集合 SQL、成分名单、公式、四位舍入、排序、coverage 和 debug 缺失数均保留。
2. 前端删除 `collectIndexPartialReasons` 的成分缺失提示来源；权重列表已有的保留行和 `--` 渲染直接复用，没有删除其它 PARTIAL/DELAYED/error 提示，也没有覆盖后端状态或新增列。现有右栏提示正常占位布局改动和对应测试保留。
3. 按 §25.5 的四成分字面金样本验证贡献 1/0/-4/null、停牌、退市成分保留、B 股排除、debug=0/1；另覆盖全部有行情、全部无行情及 factor/dailyBasic/preClose 缺失和日期落后。前端缺失夹具同时保证 up+flat+down=matched，指数昨收缺失的 fixture 明确设 preClose=null，不用不一致输入证明提示保留。
4. 回归先在旧实现执行：后端新 READY 断言及字面样本因旧 PARTIAL 判断失败；前端混合缺失测试因旧文案仍存在而失败。修复后相关测试通过，未通过 skip 或删除数值断言掩盖失败。

| 检查 | 实际结果与范围 |
|---|---|
| `.venv/bin/python -m pytest tests/web/test_wealth_index_detail_api.py tests/test_index_weight_contribution_builder.py tests/test_index_detail_field_mapper.py tests/test_index_detail_status_resolver.py -q --disable-warnings` | 48 passed；Web fixture 为隔离内存 SQLite，走真实路由/query/service/DTO；不等于生产集成 |
| `npm --prefix wealth run test -- src/pages/index-detail/IndexDetailPage.test.tsx src/features/index-detail/state/IndexDetailState.test.tsx` | 35 passed；覆盖缺失提示消失、完整行/占位、缓存切换，以及其它错误与局部重试；最终两处夹具校准后再次通过 |
| `npm --prefix wealth run test` | 168 文件、1,193 项通过；随后只改上述两处夹具，定向 35 项再通过，不重复运行其它无关测试 |
| `npm --prefix wealth run typecheck` / `npm --prefix wealth run build` | 均通过；build 仍有现有 chunk 超过 500 kB 的非阻断提示，本轮未做无关拆包 |
| CodeGraph | 开发前 explore/impact 已记录于 §25.3；开发后 `codegraph sync/status` 完成，无分支或依赖方向变更 |

真实数据核验使用已有 App、原路由和工作区代码，在 `127.0.0.1:18001` 运行临时验收进程，关闭 lifespan、不启动后台任务、拒绝非 GET/HEAD/OPTIONS；数据库强制 `transaction_read_only=on`、statement_timeout=5s、lock_timeout=2s，并已用 SHOW 核对。只读目标为 Prod `core_serving.index_daily_serving/index_factor_pro/index_daily_basic/index_weight/security_serving/equity_daily_bar/equity_suspend_d` 及上下文日历；仅 `000001.SH/000016.SH`、行情日 2026-10-19 和各自不晚于当日的最新批次。每接口各 5 次，合计 20 次，未读取全数据集。单次在内存接收原 API 响应，只保存汇总与两只缺失成分；实际源数据没有更新。

| 指数 | 接口 | 样本数 | 本机 HTTP P95/ms | 最大响应/bytes | 状态 |
|---|---|---:|---:|---:|---|
| `000001.SH` | `page-init` | 5 | 211.312 | 2,359 | READY |
| `000001.SH` | `weights` | 5 | 454.441 | 274,962 | READY |
| `000016.SH` | `page-init` | 5 | 196.140 | 2,329 | READY |
| `000016.SH` | `weights` | 5 | 185.939 | 6,856 | READY |

这些样本达到本轮 300/800ms 和 1 MiB 预算；它们是**本机临时 App → Prod PostgreSQL 跨网络样本**，不是生产 Web 主机同拓扑 P95，也不替代发布阶段复验。正式 20 次采样未失败；前序连通性诊断有一次本机代理导致的 5 秒无响应，显式绕过本机代理后有界补查成功，不计入接口性能样本。浏览器工具曾阻塞、且验证被用户中断后续做；因此端到端人工操作超过原 2 分钟估算，这部分不伪装为接口延迟或重试进度。

Chrome 实际页面 `/wealth/market/index/000001.SH?tradeDate=2026-10-19&debug=1`：只将该页 `page-init/weights` 的实际 Fetch 请求临时送到上述新代码进程，没有替换 JSON 或使用 mock adapter；原登录和数据库读链保留。上证 breadth=984/64/1140、total=2190、matched=2188、missing=2，page-init/breadth/weights 均 READY；完整列表 data-total-rows=2190，滚动至末尾仍显示信达证券 601059.SH（权重 0.082）和东兴证券 601198.SH（权重 0.068），两行贡献均 `--`，没有缺行情提示或泛化“部分基本行情”提示；切回基本行情仍无提示。上证50的正常样本 total/matched=50、missing=0、READY。当前页控制台 error 为空；已在本次会话查看完整页面截图，未将它冒充生产截图。其它错误保留由上述隔离 API/页面反例验证，不声称在 Prod 制造了真实错误。

验收临时文件：`/private/tmp/index_missing_quote_api_acceptance_20261020.json`（20 次汇总）、`/private/tmp/index_missing_quote_wealth_tests_20261020.log`（全量前端日志）。临时文件不作为未来持续存在的前提，关键事实已记在本节。浏览器临时请求转发已清空，临时进程已停止，原 8000 服务未改动；未创建分支/worktree、安装依赖、提交或发布。无剩余产品拍板项；用户视觉复看和生产发布/同拓扑验收继续独立进行。


### 25.8 用户验收与需求收尾（2026-11-04）

管理员已明确“我验收通过了”，授权本需求收尾并提交。缺行情时继续展示当前有效月度批次中的完整 A 股名单，贡献缺失为 `null`、页面为 `--`，不新增价格列；取消仅由此引起的两处提示及 PARTIAL 判断。缺失不计平盘，停牌、贡献公式、排序、其它异常和延迟提示均保留。用户同时确认，即使后续再次出现类似缺失，也保留这套展示规则。无待拍板问题。

2026-11-04 00:07:48（上海时间）的 Prod 有界只读复核：raw_tushare.index_weight 与 core_serving.index_weight 中，上证、沪深300、中证500的最新批次均为 2026-10-30，分别为 2233、300、500 行，均不包含信达证券 `601059.SH` 和东兴证券 `601198.SH`；两码仍可见于 9 月 30 日历史批次。该更新不改变本次通用缺行情展示规则，也不删除历史成分。

收尾时在当前 `dev-interface` 再次复跑：`tests/web/test_wealth_index_detail_api.py`、贡献 builder、field mapper、status resolver 共 49 项通过；`IndexDetailPage.test.tsx` 与 `IndexDetailState.test.tsx` 共 40 项通过。后端使用隔离 SQLite fixture，前端使用响应替身，覆盖缺失/全缺失、名单保留、`--` 和其它异常不被隐藏；这次回归不代替 §25.7 的真实接口与浏览器证据。`python3 scripts/check_docs_integrity.py` 通过；它仅检查脚本声明的文档结构范围，不证明业务语义。未重复生产读写或部署。

本次提交范围为成分缺行情状态、提示、回归测试及对应文档；共享文件中的右栏提示布局和其它研究需求改动不并入。§25.7 是 10 月 20 日技术验收历史记录，其中本地服务、未提交和未部署描述仅对当时有效。本次不推送、不部署、不修改生产数据；生产发布及 Web 主机同拓扑性能复验仍独立进行。

### 26. 第四批波段核对与页面1000根（2026-10-26，开发完成，待管理员浏览器验收）

该批交付时，指数详情页普通日线与研究核对K线、趋势和指数日线九转统一显式请求1000根。研究按实际日期范围，普通右栏和预测沿用普通日期。股票当时传300，分钟传500。普通日线后续的500根改动以 [§27](#sse-daily-kline-integration) 为准。该批研究约定、依赖、失败处理、预算及验收见[定量结构下一阶段LLD §15.7](index-detail-xxm-next-implementation-low-level-design-v0.6.md#xxm-daily-wave-batch-four)及其15.4—15.6。此前各节300根实测属于历史证据。该批代码、自动测试及真实只读API核对已完成，当时尚未完成浏览器验收，实际结果见该文§15.7.1。

<a id="sse-daily-kline-integration"></a>
## 27. 上证日线接入与普通日线500根请求（设计）

依据[上证指数日线接入方案](index-detail-daily-kline-integration-implementation-design-v1.md)。本节覆盖上证 `000001.SH` 日线指标接入、上证普通日线分页与图层衔接，以及股票和指数普通日线图表请求量统一为500。股票本步只改普通日K、日线九转、日线趋势三处请求量。股票分页和空状态按[股票专项 LLD §16.5](../../../../docs/architecture/technical-indicator-kernel-stock-daily-api-integration-low-level-design-v1.html#stock-daily-frontend)另行推进。

### 27.1 后端分支和输入

| 文件 | 处理规则 |
|---|---|
| `src/biz/api/wealth/market/index_detail.py` | `build_router()` 接收 App 提供的上证日K执行函数。原 `/kline` 路由保留鉴权、参数、默认300和合法范围1～2000，按原规则解析并校验一次，再用标准化代码、周期和 `limit` 选分支。只有 `000001.SH/day` 且 `limit≤500` 走 App 执行函数。路由改为异步，旧分支用现有请求 Session 在线程中执行原 `build_kline()`。 |
| `src/app/api/v1/router.py`、新增 `src/app/dependencies/index_daily_technical_indicators.py` | 装配时把执行函数和既有 DG reader 传给指数路由。执行函数从 `request.app.state.technical_indicator_runtime` 取运行对象，调用 `execution._execute(runtime, arrived_at=arrived_at, validate_before_wait=..., work=..., receive=request.receive)`。`validate_before_wait` 直接交付路由已校验的参数，`work(parsed_request, control)` 执行同步查询并按 §27.2.1 返回最终 JSON 字节，路由直接发送这些字节。沿用现有名额、请求截止和断开后的停止处理。App 缺装配时按查询错误处理。 |
| `src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py`、`index_detail_query.py`、`src/foundation/clients/local_lake/index_daily_reader.py` | 在 `build_kline()` 增加可选的指标计算回调，本地新分支可传 `session=None`，PG 分支使用 App 传入的 Session。上证新分支沿用原行情来源，查询一次当页日期和现有行情字段，校验后把 `rows` 和同源补读函数交给回调。合法空页直接组包。旧指标列只在原分支和验收对照时读取。 |
| 新增 `src/foundation/technical_indicators/sources/index_daily.py` | 实现 `IndexDailyPriceSource`。App 回调在拿到当页 `rows` 后创建，每请求一个。来源接收当页交易日、高、低、收及同源补读函数。App 通过现有计算入口取得结果，指标对象及算法沿用原实现。 |
| `src/biz/services/wealth/market/index_detail/index_detail_field_mapper.py` | 继续使用 `build_kline_bar(row)`。业务组包只消费内核的16个指标值。开高低收、昨收、涨跌、成交量额仍按原行情行生成。内核已有 `price` 能力和输出合同保留。 |

工作函数与来源按以下顺序交接：

1. **读当页。** App 工作线程持有本次行情读取。DG 沿用现有 reader，在读取前后调用同一个 `ExecutionControl.check_active()`，已开始的读取退出后再清理。Prod 复用 `open_stock_daily_read_session(get_session_factory(), control)`，当页查询和补读共用该只读 Session，数据库查询沿用现有剩余时限，退出会话后再编码。内核计算 SQL 继续使用已有中断处理。
2. **建来源并调用一次内核。** 非空且通过校验后，App 回调创建 `IndexDailyPriceSource`，以 `security_type="index"`、`ts_code="000001.SH"`、`period="day"`、`adjustment="none"` 和本节的十项指标构造 `CalculationRequest`。内核 `start/end` 是当页实际首末日期，`limit` 是当页实际根数，`before=None`。用共享运行对象的注册表和配置、同一个 `ExecutionControl` 创建本次 `TechnicalIndicatorService`。App 回调调用一次 `service._prepare_calculation(request)`，再调用一次 `service._calculate_result(prepared, control=control)`，直接取计算结果供回填。中间结果无需执行面向独立库调用的 JSON 字节计量。
3. **按日期补读预热。** `CalculationEngine.resolve_history_requirement()` 的结果随 `ReadRequirement` 传给 `create_locator()`。使用 `requirement.history.warmup_rows`，大于0时调用一次 `read_previous(before, limit)`，`before` 为当页首日，`limit` 为预热根数。由该函数按同环境交易日历选取 `trade_date < before` 且不早于同源行情起点的最近至多 `limit` 个开市日。DG 以这些日期直接调用 `IndexDailyLakeReader.factor_rows()`，PG 按指数代码与这段实际首末日期查询。两边只取 `trade_date/high/low/close`，日期正序交回，预热范围为空时跳过行情读取。按应有日期核对缺行并校验输入值，确认到同源历史起点才允许预热不足。缺交易日、无效输入或读失败按 `ID_QUERY_FAILED` 返回。
4. **交付与回填。** 预热结果归本次 `IndexDailyPriceSource` 持有。`SourceLocator.describe()` 返回 `SourceDescription`，其中 `PriceReadSelection.target_start/target_end` 是当页首末日，`read_start` 是实际读到的最早日，`read_end=target_end`，`target_rows/preceding_rows` 分别用当页和预热的实得数量。来源用已核实的行情起点确定 `reached_source_origin`，`row_groups=()` 和 `price_paths=()`，因为行情读取已完成。定位器关闭后，`open()` 从来源已持有的数据按先预热、后当页的顺序交给 `SourceStream`，`next_batch(max_rows)` 交付合并后的 `SourceBatch`，除最后一批外每批交满。Arrow 列为 `trade_date/period_start/period_end/source_as_of` 四列 `DATE`，值均为本根交易日，以及 `high/low/close` 三列 `DOUBLE`。`standard_projection` 用对应 Arrow 列名作为 SQL 投影表达式。`SourceReadContext.record_price_rows()` 对当页和预热各计一次，交付批次时无需再计。`supported_adjustment_paths=(("none", "none"),)`，基准字段为空，按原流程跳过因子和复权计算。App 回调把 `CalculationResult` 和实际预热根数一并交回查询服务。

### 27.2 校验和回填

1. 上证新分支计算前，按同环境上交所交易日历、请求上下界及同源历史起点，取得本页最多 `limit` 个应有交易日，保留日期及 `pretrade_date`。返回的日期序列必须与预期序列相等，同时核开高低收四价为有限数值。少了应有的周三，即使读够500根仍按缺行情报错。以有界来源核验确定每个环境最早有该指数行情的日期，复用此依据区分历史起点和缺整根。仅日期范围内本来没有K线才返回成功空页，历史实际不足时按实际根数返回。通过原接口直接传休市日时，使用同一组日期的最晚交易日判断状态及调试信息，`meta.endDate` 保留请求截止日。
2. 一次请求固定七条MA、BOLL、MACD、KDJ。实例编号为 `ma5/ma10/ma20/ma30/ma60/ma90/ma250/boll/macd/kdj`。MA周期为5、10、20、30、60、90、250，BOLL沿内核20根、2倍定义，MACD为12/26/9，KDJ为9/3/3。算法与旧指标的实际一致性按§27.5验收。先核对 `result.times` 与当页交易日序列一致、结果根数等于当页根数，且这十项结果及下表字段齐全，再按位置写回原行。

   | 内核值 | 写回原字段 |
   |---|---|
   | 七条MA各自的 `value` | `ma_bfq_5/10/20/30/60/90/250` |
   | BOLL `upper/middle/lower` | `boll_upper_bfq/boll_mid_bfq/boll_lower_bfq` |
   | MACD `dif/dea/hist` | `macd_dif_bfq/macd_dea_bfq/macd_bfq` |
   | KDJ `k/d/j` | `kdj_k_bfq/kdj_d_bfq/kdj_bfq` |

3. 回填后用本次已经取得的数据检查，再按原方式组包。上证新分支直接使用第1步的交易日核对结果判断状态。原 `load_latest_daily_date()`、`has_daily_after()` 及原均线历史计数查询仅由旧分支调用。新分支检查 MA 和 BOLL 时，从 App 交回的实际预热根数开始，按当页正序每根加1。以 BOLL20 为例，实际预热12根时，当页第1根是第13根有效输入，BOLL 三项为空是合法的，到当页第8根才满20根。窗口已满仍为空按指标缺项处理，组包沿用既有 `PARTIAL` 状态。行情缺失、日期对不上、结果字段不齐或计算失败，整页按 `ID_QUERY_FAILED` 返回，用现有消息字段说明指数、适用的交易日及原因。失败或取消时按原流程释放读取和计算资源。
4. 上证分页字段为 `meta.nextEndDate`，类型为 `YYYY-MM-DD` 或 `null`。实际根数等于本次请求 `limit` 时，从本页最早K线已经取得的日历记录取 `pretrade_date`。短页、空页或请求下界内无可用的更早交易日时为 `null`。日期用于下一次 `endDate`，例如本页最早是周一且上周五开市，直接传周五。原 `pageContext.prevTradeDate` 仍对应本次请求截止日，`meta.endDate` 仍表示本次查询截止日。只为上证新分支交付分页日期。下一页是否有行情由该页实际返回决定，当前页计算分页日期只用日历。

#### 27.2.1 日K接口实现

正式字段和错误形状以[日K合同 §5.5](index-detail-api-contract-v1.md#sse-daily-kline-api)为准。实现按以下顺序：

1. **路由选择。** `index_detail.py` 进入处理函数时记录 `monotonic()`。复用 `_validate_query_shape()`、`_normalize_ts_code()`、`_parse_date()`、`_parse_limit()`、`_parse_debug()`，省略 `period` 时仍用 `day`。把解析后的参数传入选中的分支。上证且 `day`、`limit≤500` 时，在 App 排队和读取前拒绝显式起始日晚于显式截止日的请求，沿用 `ID_REQUEST_INVALID` 及消息「startDate 不能晚于 endDate」。其余请求进入原 `build_kline()`。新分支失败时使用现有错误映射。
2. **计算本页应有日期。** `build_kline()` 的新分支用 `query_end_date = end_date or context.trade_date` 保留原查询上界。若该日开市，`expected_end` 取查询上界，否则取同环境日历中的上一开市日。窗口下界取已核实的同源行情起点与显式 `start_date` 中较晚者，省略起始日时仅用同源起点。从 SSE 日历读取此窗口内最新至多 `limit` 个开市日及其 `pretrade_date`，按日期正序保留。该组日期同时用于当页读取边界、校验、状态与续页。日历读取失败进入查询错误。
   - DG 复用 `IndexDailyLakeReader.calendar_rows()`。显式截止日在窗口下界内时，传 `end=截止日`、`start=窗口下界`、`recent_open_days=limit`。显式截止日早于窗口下界时，仅按原上下文需要取得截止日的日历信息，直接得出空窗口。省略截止日用上海当天和 `recent_open_days=limit+1`，其中多一个开市日是为兼容原上下文在收盘数据切换前锚定上一交易日。把同一批日历记录交给 `MarketPageContextQuery.resolve_local_context(calendar_rows=...)`，再按已解析窗口筛出本页应有日期。附加的是日历日期，行情仍只读本页应有根数。
   - Prod 在 `market_page_context_query.py` 增加上证新分支使用的查询，复用 `resolve_context()` 的上界计算。用同一条 SQL 返回上下文和窗口日期：先得到唯一的 `resolved_anchor`，用锚点的 `is_open/pretrade_date` 得到有效上界，再对 `core_serving.trade_calendar` 取 `exchange='SSE'`、`is_open=true`、窗口下界至有效上界的 `trade_date/pretrade_date`，倒序取 `limit` 后按正序交回。窗口为空仍返回锚点上下文。旧分支继续直接调用 `resolve_context()`。
3. **一次读取当页并校验。** 应有日期为空时直接组包 EMPTY，跳过当页行情、预热和指标计算。非空时，PG 按代码和应有首末日期从 `core_serving.index_factor_pro` 读取当页，DG 把应有日期传给现有 `factor_rows()`。两条路径都按 `trade_date` 正序，只投影 `ts_code/trade_date/open/high/low/close/pre_close/change/pct_change/vol/amount`。按实际返回日期顺序与应有日期比较。缺失报告应有但未返回的交易日，重复、乱序或超出范围报告对应日期及原因。在这一步同时检查四价均为有限数值，字段检查顺序为开盘、最高、最低、收盘。空值报「收盘价缺失」等具体字段，非有限值报「收盘价无效」等。DG 行情读取失败时可用本次选定的文件路径定位缺文件的日期，正常路径无需逐文件再查一次。
4. **回填与状态。** 当页通过校验后执行 §27.1 的一次计算，按 §27.2 的日期、实例编号和字段表回填。可定位到交易日的失败使用 `IndexDetailQueryError`，消息格式为「指数代码 交易日 具体原因」，例如「000001.SH 2026-10-15 收盘价缺失」，由 `_raise_http_error()` 返回原 HTTP 500 / `ID_QUERY_FAILED`。读取或计算异常无法定位到单日时，消息给出指数代码及失败环节。新分支沿用既有 `PARTIAL` 缺项语义和成功状态组包，`expectedTradeDate = expected_end or query_end_date`，`observedTradeDate = rows[-1].trade_date`（空页为 `None`）。启用 debug 时，调试模块使用同一组日期与状态。
5. **构造分页字段。** 只有 `len(rows) == limit` 时，从本页最早交易日已读取的日历记录中取 `pretrade_date`。没有该值，或早于显式 `start_date` 时，传 `None`。短页和空页同样传 `None`。该字段和 `pageContext.prevTradeDate` 分别对应本页首根与请求上界，组包时各用各自的来源。

`src/biz/schemas/wealth/market/index_detail.py` 保留四字段的 `IndexDetailKlineMetaDto`，增加 `IndexDetailSseKlineMetaDto(IndexDetailKlineMetaDto)`，声明必填的 `nextEndDate: date | None`，字段没有默认值。将 `IndexDetailKlineResponseDto.meta` 声明为 `IndexDetailSseKlineMetaDto | IndexDetailKlineMetaDto`，两个类型沿用 `extra="forbid"`。新分支明确构造前者，旧分支仍构造后者并沿用原响应模型序列化。新分支保留 `"nextEndDate": null`，旧分支省略该键，两者都保留 `"debugInfo": null`。

**上证新分支只编码最终回包。** 工作函数取得已校验的 `IndexDetailKlineResponseDto` 后，用 `model_dump(mode="json", by_alias=True, exclude_none=False, exclude_unset=False)` 取得可编码内容。调用一次现有 `encode_response_utf8(payload, control=control, max_bytes=runtime.config.max_output_bytes)`。`_execute()` 使用返回结果模式（`send=None`），把工作函数返回的字节交给路由。路由保留原 `response_model` 声明，并用 `Response(content=body, media_type="application/json")` 发送现成字节。合法空页同样走这一条编码路径。超限或编码失败时按原查询错误返回，整份成功回包未发送。

### 27.3 前端请求、缓存和同页图层

| 文件 | 落点 |
|---|---|
| `wealth/src/shared/charts/dailyChartRequestLimits.ts` | 集中定义普通日线每页500和上证历史预取剩100根。股票只引用页大小，预取阈值只供上证普通日线使用。研究专用请求继续使用原有1000根常量，内核上限独立。 |
| `wealth/src/pages/stock-detail/StockDetailPage.tsx`、`wealth/src/features/stock-detail/trend-channel/controller/useStockTrendChannel.ts` | 股票首屏 `fetchStockDetailKline()` 的 `limit`、股票 `useNineTurnSeriesRegistry()` 的 `dailyLimit`、`fetchStockTrendChannel()` 的 `limit` 均显式传共用500。沿用原截止日、触发条件、请求时机、接口和缓存。 |
| `wealth/src/features/index-detail/controller/useIndexDetailController.ts` | 首屏趋势继续在 `page-init` 后由原控制器发出。首屏日K和趋势使用原截止日，显式传500。首屏趋势先回时保留在现有首屏状态，主图按首屏实际K线日期绘制，右栏沿用同一结果。上证历史日K使用最早已加载页回包的 `meta.nextEndDate` 发请求。 |
| `wealth/src/pages/index-detail/IndexDetailPage.tsx`、`wealth/src/features/nine-turn/controller/useNineTurnSeriesRegistry.ts`、`wealth/src/features/index-detail/api/indexNineTurnLoader.ts` | 首屏九转继续由主图和右栏的现有触发调用 `ensure(period)`，日线显式传500，沿用登记处的在途及已完成结果。历史日线复用九转 loader 和原接口，loader 转发历史页的 `startDate/endDate`。首屏最新九转摘要继续取首屏结果。 |
| `trendChannelApiClient.ts`、`src/biz/api/quote.py`、`quote_trend_channel_query_service.py` | 上证趋势新增可选 `start_date`。在原计算结果中以 `bisect_left(start_date)`、`bisect_right(end_date)` 确定包含式范围，再取该范围内最多 `limit` 个最新结果。仅在已指定起始日时，趋势自己的分页信息也以该范围为界。显式起始日晚于显式截止日返回 HTTP 400；省略起始日沿用原查询和分页含义。 |
| `IndexChartWorkspace.tsx`、共享 `DetailChartWorkspace.tsx` | 上证按可见交易日和原缩放向左加入旧数据，四张图继续同步并保留原实例。`IndexChartWorkspace.tsx` 将主图默认叠加项和用户主动选择分开处理。首屏可以按原规则提供默认项，用户选择 MA、BOLL 或趋势后，任何首屏迟到回包或历史回包都只补数据，保留选择。程序恢复视口只更新显示。到边界时仍识别向历史方向的新拖动，以触发重试。 |

- 上证日K缓存以标的、周期、首屏截止日和既有价格口径归属。用户向历史拖动时，从当前最左可见K线数到缓存最早一根，两端都计入，剩100根或更少才预取。已有500根时，第401根触发下一页。一个历史日K请求在途。下一页截止日随成功页保存，失败保留原截止日。回包时已拖回较新位置则只入缓存，再次往历史拖动先用缓存。已到左端仍在等待，显示「加载中」。
- 上证日K成功不足500根即到头。满页时仅在回包给出下一页截止交易日后继续加载。非空短页先并入缓存，历史0根保留原图。首屏0根沿用上证无数据状态。历史失败保留已有图，到左端显示「加载失败」。下一次试图越过左端的手势重试原页，一次手势一次请求。
- 上证历史日K成功且非空后，由控制器调用同页两路图层加载，每路传该页 `bars` 的实际首末交易日期及500。历史空页不触发两路请求。控制器按本次打开页面、历史页首末日期、图层类型登记，在发请求前写入在途状态。重复通知命中在途或已成功记录时直接使用该记录。某一路失败时保留原参数及失败状态，用户重试只重发该范围该图层。历史回包按日期写入缓存，用户已拖回较新位置时暂不更新图表。首屏右栏摘要始终取首屏状态。是否继续加载更早的历史由日K回包决定。
- 按标的、周期、首屏截止日、页面和请求编号核对归属，图层再核所属页。切换标的、日期或离开时取消旧请求，成功、失败和收尾均检查归属。分钟线相关请求当前已传500。

#### 27.3.1 趋势范围与前端接口实现

1. **趋势路由和查询。** 在 `src/biz/api/quote.py::get_quote_detail_trend_channel()` 增加 `start_date: date | None = Query(default=None)`。沿用鉴权及代码、周期校验，然后在调用查询服务前检查两个显式日期的顺序。倒序时抛 `WebAppError(status_code=400, code="INVALID_DATE_RANGE", message="起始日期不能晚于结束日期")`，非法日期沿用框架 422。给 `QuoteTrendChannelQueryService.build_response()` 增加默认 `None` 的同名关键字参数。
2. **仅裁剪完整结果。** 在 `src/biz/services/quote_trend_channel_query_service.py`，沿用原 `load_instrument()`、`load_series()` 和响应组装。使用 `bisect_left/bisect_right` 按 `trade_date` 在已排序的 `series.rows` 中查边界，直接用现有行，避免每页另建全量日期数组。边界及返回位置如下：

   ```python
   # rows 非空。key 按行取 trade_date。
   effective_end = end_date if end_date is not None else rows[-1].trade_date
   lo = bisect_left(rows, start_date, key=key) if start_date is not None else 0
   hi = bisect_right(rows, effective_end, key=key)
   first = max(lo, hi - limit)
   selected = rows[first:hi]
   has_more_history = bool(selected) and first > lo
   next_end_date = rows[first - 1].trade_date if has_more_history else None
   ```

   `hi≤lo` 或完整序列为空时均走空结果分支，返回空数组、计数0、首末日与下一截止日为空、`has_more_history=false`。有源但指定范围内没有数据时使用 `no_rows_in_requested_range`，省略起始日的空结果继续用原说明，无源继续用 `source_has_no_daily_rows`。有结果时实际首末日从 `selected` 取。水位日期、公式、缓存和 `TrendChannelResponse` 字段不变。正式约定见[趋势合同 §5.1](../../../../docs/architecture/sse-daily-trend-channel-realtime-computation-low-level-design-v1.md#trend-history-range-api)。
3. **日K客户端。** `indexDetailApiTypes.ts` 将 `meta` 声明为原四字段类型与包含必填 `nextEndDate: string | null` 的类型。沿用 `fetchIndexDetailKline()` 和现有错误消息读取。控制器在请求归属通过后，用 `"nextEndDate" in response.meta` 读取当前上证日K页的分页字段。字段缺失走现有接口错误处理，保留已有图与缓存。历史页按成功回包的截止日发起，入缓存成功后更新保存的下一截止日；失败保留旧值。旧分支消费者继续读取原字段。
4. **图层客户端。** `trendChannelApiClient.ts::fetchTrendChannel()` 的请求参数增加 `startDate?: string`。仅在参数存在时序列化成 `start_date`。首屏继续传原 `endDate` 与显式500，通用客户端既有默认值保留。历史页以当页 `bars[0].tradeDate`、`bars.at(-1).tradeDate` 为起止日。给 `useNineTurnSeriesRegistry.ts` 导出的 `NineTurnSeriesLoadRequest` 增加 `startDate?: string`，首屏 `ensure(period)` 的调用照旧，历史页直接通过 `loadIndexNineTurnSeries()` 将 `startDate/endDate` 转给现有 `fetchIndexNineTurnSeries()`。两路各发一次，重试复用记录的原参数与图层类型。现有请求取消和回包归属检查适用于两路。

#### 27.3.2 历史起点的指标绘制

1. `indexDetailViewModelAdapter.ts::toCandlePoint()` 继续逐字段保留 `number | null`，`IndexChartWorkspace.tsx` 按原交易日将 K 线和指标值传给 `DetailChartWorkspace.tsx`。所有有效 K 线保留原日期及位置。指标是否绘制按字段判断，沿用 `isFiniteChartNumber()`，不按页内第几根判断。
2. MA、BOLL、DIF 和 DEA 复用 `detailChartSeries.ts::buildLineData()`。缺值日只传 `{time}`，有效值日传 `{time, value}`。每条线从自己的首个有效日期开始，首个值之前留空。MACD 柱复用 `buildHistogramData()`，仅传有效值。`0` 通过同一判断，按正常的零值点或零高度柱交给图表。首次加载与历史左插更新沿用同样的构造函数。
3. `DetailChartWorkspace.tsx` 保留 MACD 面板、坐标和共用日期位置。当前可见区间中 `macd`、`dif`、`dea` 三项均没有有效值时，沿用 `resolveVisibleIndicatorRange()` 返回 `null` 的分支，`applyIndicatorAxisPriceLines()` 隐藏依赖数值的上下限、零轴线及标签。滚动到有值区间时沿用原范围更新。面板顶部的指标读数缺失时沿用 `--`。
4. 在 `wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.test.tsx` 用一个早期指标为 `null`、随后出现有效 `0` 和非零值的受控日线样本，检查 K 线和共用日期完整、各线仅从实际出值日开始、空值日没有 MACD 柱、有效 `0` 被保留，以及滚到全空区时 MACD 面板和坐标仍在。复用既定页面验收核对显示效果。

### 27.4 开发顺序和 Figma

1. **第1步，编码前准备。** Figma 已确认，[日K接口合同 §5.5](index-detail-api-contract-v1.md#sse-daily-kline-api)与[趋势范围合同 §5.1](../../../../docs/architecture/sse-daily-trend-channel-realtime-computation-low-level-design-v1.md#trend-history-range-api)已定稿。§27.5.1 已核实同源历史起点，起点指标和 §27.3.2 的绘制规则已确认。
2. **第2步，后端接入。** 上证日K和趋势日期边界已实现。DG 验收结果已获管理员确认，Prod 首屏通过。按管理员决定，Prod 续页和起点接口检查暂缓，第3步使用现有证据开工。各项实际结果见 [§27.5.3](#sse-daily-kline-step-2-result)。
3. **第3步，前端接入。** 按 §27.3 调整股票和指数普通日线请求量，并只在上证普通日线接入缓存、分页和图层。开工前核对 [§27.4.1](#sse-daily-kline-step-3-checklist)，编码后用既有测试文件验证。
4. **第4步，浏览器验收。** 按 §27.5.2 的现有预算，用 DG 真实日K接口验证上证两页及图表衔接，首屏辅助请求和图层使用既定受控回包。行情只读，记录实际请求和耗时。

[上证日线历史加载与图层状态总稿](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2170-639)已绘制、核图并经管理员确认，作为本次交互和视觉依据。核对了左端提示的位置、四图与时间轴的对齐、接入前后已有画面的对照，以及 1280 px 窄屏长错误提示的两行显示。

| 画稿 | 评审节点 |
|---|---|
| 左端提示与历史回包 | [加载中](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2170-646)、[加载失败与拖拽重试](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2170-649)、[接上历史页](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2170-653)、[拖回较新位置时只写缓存](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2170-656) |
| 行情校验与空结果 | [历史页窄屏错误](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2170-3108)、[首屏校验错误](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2170-3717)、[既有首屏空态](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=499-579)；历史空页和短页见总稿第05组说明。 |
| 图层局部失败 | [九转](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2170-3737)、[趋势通道](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2170-3740) |

<a id="sse-daily-kline-step-3-checklist"></a>
#### 27.4.1 第3步编码门禁矩阵

按 [Wealth 模块交付通用清单](../../system/module-delivery-checklist-v1.md#2-硬检查) 逐项核对。以下验证复用 §27.3、§27.5 和原定浏览器安排。

| 清单条目 | 适用性 | 代码位置和验证方式 |
|---|---|---|
| §2.1 交付事实链 | 适用 | 以上证已确认 Figma、接入方案 §7、已定稿接口和本节为准，开工前核对四步的范围和前置证据。 |
| §2.2 后端事实归一 | 适用 | §27.2 由后端校验交易日和四价，内核结果由后端回填。`useIndexDetailController.ts` 只使用回包日期、指标和 `meta.nextEndDate`，用原接口样本核对。 |
| §2.3 状态机 | 适用 | §27.3 区分首屏空、历史到头、等待和失败。续页等待随现有接口响应或页面切换取消结束，计算仍服从 §27.1 已有截止。用可控慢回包和失败回包核对左端文案及拖拽重试。 |
| §2.4 显示和数据 | 适用 | §27.3.2 沿用涨跌色和指标格式，缺值留空，有效 `0` 保留。用 `DetailChartWorkspace.test.tsx` 核对日期、线与柱。 |
| §2.5 行为过程 | 适用 | `useIndexDetailController.test.tsx`、`IndexDetailPage.test.tsx` 验证剩100根预取、返回较新位置后只写缓存、历史失败重试、短页和空页到头。按已确认 Figma 核对左端提示和窄屏错误。 |
| §2.6 文档与实现 | 适用 | 收尾时用实际请求和回包核对方案、§27.3 与接口示例，记录实测和暂缓范围。 |
| §2.7 渐进替换 | 适用范围为变更边界 | 沿用已有真实 API。股票只改三处数量，上证才启用续页，其他指数、分钟和研究继续使用各自路径。用六处请求断言和现有研究请求用例核对。此步无数据源切换。 |
| §2.8 接口与消费者 | 适用 | `indexDetailApiTypes.ts` 按新旧 `meta` 区分，趋势历史传 `start_date`，九转历史传 `startDate`。接口样本和控制器测试核对字段名及两路实际日期。 |
| §2.9 图表坐标 | 适用 | `DetailChartWorkspace.tsx` 按交易日保留四图共同范围。§27.3.2 保留 MACD 面板与坐标，用图表测试及浏览器核对。 |
| §2.10 统计与传输 | 适用范围为接口量和耗时 | 指标沿用后端，§27.5.2 约束 DG 浏览器两次日K请求。记录端到端耗时和请求结果，沿用已有时限。本步无新增统计或数据库函数。 |
| §2.11 策略配置 | 不适用 | 500及100是 §27.3 的页面常量，由前端构建生效，本步无策略中心配置。 |
| §2.12 清单映射 | 适用 | 开工前核对本表及下面的核心用例，逐项对应 §27.3、§27.5。 |
| §2.13 例外和语义断言 | 适用 | §27.3.2 的空值和坐标由图表测试断言。本步的验收范围决定是暂缓 Prod 续页和起点接口检查，详见 §27.5.3。无新增图表语义例外。 |
| §2.14 显式坐标参数 | 不适用 | 本步恢复已有时间轴视口和缩放，沿用既有纵轴取值，无新增 `yMin/yMax/yTickValues` 规则。 |
| §2.15 并排双图 | 不适用 | 日K、MACD、成交量、KDJ 上下排列，按 §2.9 核对时间轴同步。 |
| §2.16 指标卡片文案 | 不适用 | 本步交互文案是图表左端提示和错误信息，按 §2.5 核对。 |
| §2.17 真实接口和页面 | 适用 | 复用 §27.5.3 的后端实测，第4步按下述真实日K浏览器用例核对实际画面。受控回包用于验证图层和错误交互。 |
| §2.18 八项原则 | 适用 | 事实源对应 §2.2，接口对应 §2.8，配置一致对应 §27.3 共用常量，默认行为对应 §2.3，排序与筛选对应 §27.2 和上一交易日续页，性能对应 §2.10，错误和调试对应 §27.2.1 原错误合同，用户可见结果对应 §2.5、§2.17。方案对应第7节实施前检查。 |

**第3步的核心检查。** 用 `npm --prefix wealth run typecheck`、`npm --prefix wealth run test` 和 `npm --prefix wealth run build` 验证。定向开发检查复用 `useIndexDetailController.test.tsx`、`IndexDetailPage.test.tsx`、`IndexChartWorkspace.test.tsx`、`DetailChartWorkspace.test.tsx`、`useNineTurnSeriesRegistry.test.tsx`、`StockDetailPage.test.tsx` 和 `useStockTrendChannel.test.tsx`。覆盖普通日线六处显式500、上证按 `nextEndDate` 续页、历史左插保持当前日期和缩放、旧页回包先入缓存、两路图层按当页日期请求和独立重试。核对短页和空页到头，以及旧回包丢弃。

**第4步的真实日K用例。** 使用现有本地 DG 后端，通过 `npm --prefix wealth run dev -- --host 127.0.0.1` 启动页面。打开页面前准备 §27.5.2 规定的首屏辅助请求和图层受控回包，日K请求发往真实接口。打开 `/wealth/market/index/000001.SH?tradeDate=2026-10-20`，按 §27.5.1 的固定首屏和续页核对网络面板及画面。两次日K请求各返回500根，下一次用首屏给出的 `2024-09-20`，日期衔接无重叠。核对 `indexRef.tsCode`、`period`、`meta.count/limit/endDate/nextEndDate`、`dataStatus`、日期、四价、成交量及四组指标和图表对应，保留首屏摘要，接页前后当前可见日期及缩放一致。图层范围和失败提示复用 §27.5 受控回包检查，失败仍用原 `code/message/request_id` 语义。读数、请求和耗时按 §27.5.2 记录。

### 27.5 验收与停点

| 口径 | 必要证据 |
|---|---|
| 上证一次内核计算、原行回填 | 正常两页按 §27.5.1 对照本环境的原路径指标。16项逐日逐字段的原值绝对差不超过 `0.0005`，日期、字段、根数和空值位置一致。原行情字段照常校验。起点短页另按初始化规则验证。 |
| DG和Prod读取 | 分别核各环境的当页和预热，证明当页K线只读一次，预热独立按日期读取早于首根的数据，新分支沿用当页日期核对结果及实际预热根数。验证跨休市续页的上一交易日和数据状态、缺整根、缺四价、真实起点的合法短页以及其中 MA、BOLL 的合法空值。实际完成与暂缓项见 §27.5.3。 |
| 请求量与分支 | 用隔离测试核股票和指数普通日线六个请求点均显式500。上证501～2000及其它指数走原路径。分钟线已有500。 |
| 上证缓存与图层 | 核首屏、续页、短页和空页的实际日期及到头。用可控回包核首屏趋势仍先发、九转主图和右栏复用同一次请求、历史页每图层只发一次、失败只重试原图层及范围。核左端等待、用户选定 BOLL 后趋势回包仍显示 BOLL、回到较新位置只更新缓存和旧请求丢弃。 |

旧日K分支、趋势接口和趋势查询服务分别在现有 `tests/web/test_wealth_index_detail_api.py`、`tests/web/test_quote_trend_channel_api.py` 和趋势查询服务测试验证。验证上证旧日K行为的请求显式传大于500的合法值，包括已存因子、缺项、延迟和调试字段用例。省略 `limit` 仍取300的检查归入上证新分支。上证新分支在 `tests/app/technical_indicators/test_index_daily_kline_integration.py` 单独装配指数路由、运行对象和有界行情样本，覆盖页面读取、补读和回填。现有 Web 公共夹具会替换指标运行对象的生命周期，专门用例自行装配。前端验收落在现有股票、指数详情页测试及九转注册表测试。样本的预期日期、根数及旧指标值来自已核实的输入和原路径。

| 接口用例落点 | 用例与断言 |
|---|---|
| `tests/app/technical_indicators/test_index_daily_kline_integration.py` | 用周一、上周五和周四的交易日记录验证顺序。上证请求周一 `limit=1`，该页只返回周一、`nextEndDate` 为周五。续页传周五，只返回周五。直接传周日时，`meta.endDate` 仍是周日，预期、观测与调试模块用周五，状态沿用原逻辑。达到显式起始日时满页的 `nextEndDate` 为 `null`。省略 `limit` 走新分支，`meta.limit=300`。 |
| 同一上证日K测试文件 | 短页按实际数量返回且 `nextEndDate=null`。日历确认无应有日期时响应为 EMPTY，断言没有行情读取和内核调用。存在应有交易日但没有对应行情，以及该日收盘价为空，均断言 HTTP 500、`code/message/request_id` 和具体交易日，且没有执行内核。用既有正常回包样本同时核对原字段及 `debugInfo` 保留、最终编码函数只调用一次。 |
| `tests/web/test_wealth_index_detail_api.py` | 保留上证大于500和其它指数的旧路径用例。断言 `meta` 仅有原四字段，`debug=0` 时保留 `debugInfo:null`。 |
| `tests/web/test_wealth_index_detail_xxm_local_routes.py` | 现有两处用于核对旧日K行为的上证请求显式传 `limit=501`。新分支的日K和调试字段用专门的上证日K测试覆盖。 |
| `tests/web/test_quote_trend_channel_api.py` | 在既有切片样本上追加 `start_date`。验证起止日均包含、范围内超过 `limit` 时下一截止日仍在范围内、仅范围外有更早数据时分页为 `false/null`。有源但范围为空时检查 `no_rows_in_requested_range`，旧请求继续使用原空结果说明。显式日期倒序时断言 HTTP 400 和 `INVALID_DATE_RANGE`，查询服务未被调用。 |
| `useIndexDetailController.test.tsx`、`IndexDetailPage.test.tsx` | 核对首屏三路仍按原触发顺序，历史日K使用回包给出的周五截止日，两路历史图层分别发送其规定字段名并使用当页实际日期。核对历史空页、只重试失败的图层及原日期、过期回包丢弃、迟到的趋势回包保留已有 BOLL 选择。 |

<a id="sse-daily-kline-acceptance-samples"></a>
#### 27.5.1 各环境历史起点和固定验收日期

2026-11-05，只核 `000001.SH` 日线因子与同环境 SSE 交易日历。DG 的 6503 个分区目录仅枚举目录名以定位最早分区。现代范围只检查 1500 个指定路径是否有 `part-000.parquet`，因子行情和指标明细只读最早3天及下表所列6个边界日。Prod 使用 `scripts/psql-remote.sh`，会话核实 `transaction_read_only=on`，本次沿用既有审计的 5 秒查询和 2 秒锁等待限制。`EXPLAIN` 确认最早三行用 `(ts_code, trade_date)` 主键索引；指定窗口仅查上证代码及区间内的日期键，指标和价格明细也只取最早3天及6个边界日。

| 环境 | 当页和预热的正式来源 | 实际最早三根 | 起点前的开市日 |
|---|---|---|---|
| DG | `/Volumes/datasource/data_lake/silver/index/index_factor_pro/trade_date=YYYY-MM-DD/part-000.parquet` | `2000-01-04`、`2000-01-05`、`2000-01-06`。第一天收盘 `1406.371`，是目录最早分区，三份均有上证行。 | `1999-12-30` |
| Prod | PostgreSQL `core_serving.index_factor_pro` | `2010-01-04`、`2010-01-05`、`2010-01-06`。第一天收盘 `3243.76`，为索引按日期正序返回的首行。 | `2009-12-31` |

`2000-01-04` 也与 DG 的 [主要指数种子](../../../../lake_console/orchestrator/src/orchestrator/seeds/market/major_indices.cn_a.csv#L2) 对应。上证新分支由 App 按所用行情来源将本表相应的起点作为 `source_origin: date` 传入当页查询和补读函数，二者使用同一个值。调用期间不另查起点。新增更早历史时，在启用新范围前用上述有界方法核对并同步该来源的起点。原分支的缺项判断与数据入口沿用原实现。

正常样本固定为 `tsCode=000001.SH`、`period=day`、`limit=500`，首屏和续页均省略 `startDate`。预热500来自当前内核对默认指标组合的[既有验收](../../../../tests/foundation/technical_indicators/test_fourth_batch_fix.py#L388)。实现仍读 `requirement.history.warmup_rows`，实际算出的根数超出本验收安排时停止并记录，不能强行截成500。

| 样本 | 请求 `endDate` | 当页范围，正序 | 预热范围，正序 | 应返回的 `meta.nextEndDate` |
|---|---|---|---|---|
| 首屏 | `2026-10-20` | `2024-09-23`～`2026-10-20`，500根 | `2022-08-30`～`2024-09-20`，500根 | `2024-09-20` |
| 续页 | `2024-09-20` | `2022-08-30`～`2024-09-20`，500根 | `2020-08-10`～`2022-08-29`，500根 | `2022-08-29` |

两套日历均核到这些边界。DG 的 1500 个文件路径全部存在。Prod 对相同范围的因子日期和 SSE 开市日做双向比较，各1500个日期、缺失和额外日期均为0。两环境抽查 `2020-08-10`、`2022-08-29`、`2022-08-30`、`2024-09-20`、`2024-09-23`、`2026-10-20`，六日上证因子行均存在，收盘值一致，16个旧指标字段均非空。抽样结果用于选定范围。完整的新旧结果在接入后按以下顺序对照。

1. 分环境用旧路径的实际来源一次保存两页参考，每页一次读取。沿用 `IndexDetailQuery.load_kline_rows()` 的投影或 `IndexDailyLakeReader.factor_rows()` 的现行列清单，以本表的当页首末日限制读取，每页最多500根，按交易日正序。原行情字段走原 `build_kline_bar()` 取值。参考结果写本机 `/private/tmp`，后续阶段和续跑复用。不得为绕开新分支而扩大接口请求量。
2. 运行新日K首屏和续页，用新首屏回包的 `meta.nextEndDate` 发下一页。逐页先核对交易日期、字段集合、根数、原行情及空值位置，再对16个指标逐项比较。非空值按 `abs(Decimal(str(new)) - Decimal(str(old))) <= Decimal("0.0005")` 判定，恰等于上限也通过。`0.0005` 是小数点后第三位的半个单位，由管理员确认。每环境共1000个日期、16000个值，所有项均通过才算通过。失败记录环境、交易日、字段、原始新旧值及绝对差。该上限只用于验收，API 仍返回实际数值。
3. **起点短页按内核原初始化规则单独验收。** 两环境最早三根的旧 MA20、MA250 已有值，内核从各自实际首根开始。用上表第三根的日期作为 `endDate`，`limit=500` 且省略 `startDate`，应返回3根、前置输入0根、`nextEndDate=null`。三根上的7条MA和3条BOLL均应为 `null`，MACD首根按既有规则为有效的0。前端按 §27.3.2 判断每个字段何时可画。再用上表起点前的开市日作为 `endDate`，应返回成功空页，行情和预热读取均为0。旧因子的历史初始化差异记录在验收证据中，正常两页的对照门槛继续全部适用。

<a id="sse-daily-kline-acceptance-budget"></a>
#### 27.5.2 上证因子读取上限和失败处理

下表保留原定验收上限，累计的是每次实际选取的上证因子行。后续第4步只执行 DG 浏览器核对，Prod 暂缓项见 §27.5.3。在原定验收请求中核对取数调用次数和参数，确认当页只读一次、补读只覆盖当页首日之前，同时记录结果根数和耗时。DG 每日一个文件，从查询传入的日期数量直接得到选入的文件数，同一日期在不同请求重复选入时分别计入验收开销。PG 的每条因子查询绑定代码、日期范围和预期最大行数。取数范围核对属于开发验收，复用原定请求及其查询信息即可。

| 验收动作 | DG 因子上限（根） | Prod 因子上限（根） | 计算依据 |
|---|---:|---:|---|
| 旧指标参考 | 1000 | 1000 | 两页各500，只读取一次参考 |
| 后端接口对照 | 2000 | 2000 | 两次请求各500根当页加500根预热 |
| 历史起点 | 3 | 3 | 一个3根短页加一个0根空页 |
| 最终浏览器核对 | 2000 | 0 | 本地浏览器通过 DG 新日K接口走两页，仍各为500加500 |
| 正常安排合计 | 5003 | 3003 | 以上四项相加 |
| 一次获准的失败节点续跑预留 | 1000 | 1000 | 每环境至多续跑一个失败节点，最高费用是一整页新日K |
| **含续跑总上限** | **6003** | **4003** | 正常安排加各自预留 |

后端及最终浏览器的每个正常页分别定位当页、预热各一次，每次最多500个开市日。两个起点请求各读一次上下文日历，预热到起点直接交付空结果。按此计算，含续跑的日历查询上限为 DG `2×2+2+2×2+2=12` 次、Prod `2×2+2+2=8` 次。日历与行情分开计数，DG 同一个日历文件中的休市行不计入因子根数。首屏辅助请求和两路图层用受控回包核对触发时间、日期、空页及重试。该预算覆盖真实日K接口与浏览器衔接，趋势通道冷启动原有的完整历史读取不纳入本次真实验收。

查询失败、范围不符、读取超上限或对照有差异时，停止后续真实请求。失败尝试的实际读取量计入本节点，已通过节点及已取得的参考数据保留。修正后仅按原日期和原参数续跑获准的失败节点，额度不足时暂停。计划执行阶段记录实际请求、SQL 耗时和读到的根数，读取根数上限不折算为耗时承诺。

<a id="sse-daily-kline-step-2-result"></a>
#### 27.5.3 第二步开发与验收记录（2026-11-06）

后端接入已实现。61 项定向测试通过，覆盖上证新分支的当页与预热交接、跨休市续页、短页和空页、缺整根和缺收盘价、原字段与一次回包编码、旧日K分支及趋势起止日筛选。9 项依赖方向与内核边界检查通过。Prod 所用的日历查询另外以进程内临时表核对了周一、休市日、空窗口和前置日期。Prod 真实只读验收结果见本节末尾。

DG 已保存两页旧参考，共读取1000根。新接口首屏用 `endDate=2026-10-20&limit=500`，HTTP 200，返回 `2024-09-23` 至 `2026-10-20` 共500根，`nextEndDate=2024-09-20`。实际调用一次当页读取，另调用一次预热读取，预热范围为 `2022-08-30` 至 `2024-09-20`，也是500根。当页和预热日期无重叠。交易日期、原行情字段、指标字段和空值位置均与旧参考一致。本次首屏请求实测约0.212秒，当页和预热读数分别约0.044秒和0.038秒，仅记录本次执行。DG 本轮累计读取2000根。

首屏按当时的两位小数四舍五入规则比较，8000个值中135个有差异，其中 MACD 68个、BOLL 66个、MA250 1个。135个旧值都恰在两位小数的舍入分界，新值先四舍五入至三位则与各自旧值一致。例如 `2024-09-24` 的 MACD 柱值旧值为 `20.645`，新值为 `20.64484765453068`，直接取两位分别为 `20.65` 和 `20.64`。这项历史记录保留供追溯，现行规则见 §27.5.1。

管理员确认改用原始值绝对差 `≤ 0.0005` 后恢复第二步验收。复用已核对的 DG 首屏读数、回包和离线对照证据，8000个指标值均通过，原值最大绝对差恰为 `0.0005`。两页旧参考及首屏证据位于 `/private/tmp/sse-daily-step2.XHD3e7`。

DG 续页实际请求 `endDate=2024-09-20&limit=500`，HTTP 200，约0.300秒。返回 `2022-08-30` 至 `2024-09-20` 的500根，下一页截止日 `2022-08-29`。当页与 `2020-08-10` 至 `2022-08-29` 的500根预热各读一次。交易日期、原行情字段、指标字段及空值位置一致，8000个指标值中7999个通过。唯一超限项是 `2022-10-14` 的 BOLL 中轨，旧值 `3098.286`，新值 `3098.2854999999995`，原值绝对差 `0.0005000000005`，超限 `0.0000000000005`。复用已保存的 `2022-09-09` 至 `2022-10-14` 共20根收盘价，十进制求和为 `61965.7100`，均值 `3098.2855`，与旧值的差恰为 `0.0005`。超出的部分来自浮点运算尾数。

该次按原值规则记为超限，第二步验收当时暂停。DG 当时累计读取3000根，其中两页旧参考1000根，两次新接口各1000根。续页证据保存在同一临时目录的 `dg_acceptance_abs_diff.json`。

随后按单独批准的范围完成 DG 上证日线全历史对照。`2000-01-04` 至 `2026-11-05` 共6503个交易日，每日行情和日历一致，按14页、每页最多500根、最多500根预热对照104048项。各文件只读一次，预热重用已读行情。103091项在 `0.0005` 内。MA 和 BOLL 共515项在历史起点因窗口不足而为空。MACD 的306项超限全部落在最初128个交易日，KDJ 的78项全部落在最初28个交易日，12个具有完整500根预热的页上这两组指标均在阈值内。BOLL 中轨58项按原值比较超限，超出部分最大为 `0.000000000001`。管理员认可本次 DG 测试结果及历史起点的初始化差异。此次离线对照证据位于 `/private/tmp/sse-dg-all-dates.6TuyiL`。

DG 真实接口的剩余起点检查通过。请求截止 `2000-01-06` 返回3根，未读取预热，MA 和 BOLL 为 `null`，MACD 首根为0，`nextEndDate=null`。请求截止 `1999-12-30` 返回 EMPTY 和0根，行情读取为0。原定后端验收累计读取3003根，单独批准的全历史对照另计。

Prod 第一次核对旧参考时，使用只读事务及5秒语句上限，合并读取两页旧参考的语句超时。按页重试后，已取得并核对首屏500根旧参考，续页 `2022-08-30` 至 `2024-09-20` 的旧参考再次超时。`EXPLAIN` 显示续页按 `ts_code/trade_date` 的主键范围逆序扫描，具体超时原因尚未查明。失败语句的实际读取量无法从取消后的回包确认。保留首屏旧参考 `prod_reference_first_page.json`，当时按 §27.5.2 暂停，随后经管理员确认续跑。

管理员确认再次续跑后，将 Prod 续页旧参考拆为 `2022-08-30` 至 `2023-09-07`、`2023-09-08` 至 `2024-09-20` 两段，每段仍限5秒和250根，成功补齐续页500根。两页旧参考共1000根，日期无重复。随后经本地装配的实际日K路由连接 Prod，确认 `transaction_read_only=on`。首屏在0.897秒内返回500根，下一截止日为 `2024-09-20`，当页和预热各只读500根，8000项指标全部在 `0.0005` 以内，日期、原行情字段、指标字段和空值位置一致。

Prod 新接口续页读取当页500根耗时0.113秒。查询更早的500根预热行情时，`2020-08-10` 至 `2022-08-29` 的查询耗时5.809秒且没有返回，整次请求6.051秒后返回 HTTP 500（`ID_QUERY_FAILED`）。对该查询仅执行 `EXPLAIN`，显示使用同一主键按代码和日期范围逆序扫描。数据库具体耗时原因尚未查明。两次新接口请求实际返回1500根源行情，另一次预热查询的实际读取量无法由回包确认。接口验收证据保存在 `prod_acceptance_closeout.json`。

**当前决定（2026-11-06）。** 管理员确认 Prod 已有延迟问题，暂缓本次续页复验及起点短页、空页接口检查。Prod 的通过范围为首屏。凭已获认可的 DG 验收和 Prod 首屏结果推进第3步。第4步按原定 DG 浏览器范围验收。
