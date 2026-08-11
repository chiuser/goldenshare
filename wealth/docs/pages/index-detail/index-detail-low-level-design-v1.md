# 指数详情页低层设计（LLD）v1

> 状态：M1 后端与 M2 共享图表已按冻结合同实现并通过验证；M3 及后续前端里程碑尚未开始。
> 需求依据：[指数详情页标杆需求 v1](./index-detail-benchmark-requirement-v1.md)
> 技术方案：[指数详情页技术实施方案 v1](./index-detail-implementation-design-v1.md)
> 编码门禁：[指数详情页 M2 编码前门禁 v1](./index-detail-m2-coding-gate-v1.md)
> 正式 DTO：[指数详情页正式 API / DTO 合同 v1](./index-detail-api-contract-v1.md)
> M0 生产审计：[指数详情页 M0 生产因子审计 v1](./index-detail-m0-production-audit-v1.md)
> 趋势接口依据：[SSE 日线趋势通道实时计算方案 v1](../../../../docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md)

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
3. page-init/kline/weights 正式 DTO 已以 `1.1.0` 独立合同冻结。
4. 生产审计发现深证成指、创业板指 factor 量额与正式日线分叉；外部数据源核对确认 factor 准确，基本行情与 Kline 的量额统一取 `index_factor_pro`，不做倍率修正或 daily fallback。
5. 已新增独立 `page-init/kline/weights` schema、query、mapper、service 与正式路由；未修改股票详情、主要指数卡片或 Quote trend DTO。
6. M1 生产只读复验显示 9 个指数当前有 630 根 factor（自 2024-01-02），A500 当前有 455 根（自 2024-09-23）；该结果只记录审计时点，不进入任何 code/date 特例。

M5 开始前，当前尚未提交的 `major_index_mins_technical` Gold 合同、writer 和验收仍必须先稳定；M1-M4 不依赖该脏工作树实现。

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
| Technical Rail 组件 | `414:448` | 四轨、技术结论与九转占位 |
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
| C09 | 成分涨跌使用最新有效权重批次和同日股票日线 | page query | missing 不计入 flat |
| C10 | 权重 API 返回完整批次 | weights query/DTO | 不接受 limit，不静默截断 |
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
| `EquityDailyBar` | 成分股同日 `pct_chg` | 涨跌统计与贡献输入 |
| `Security` | 成分股名称 | 权重行名称，缺失时只显示 code |
| `QuoteTrendChannelQueryService` | `000001.SH + day` 的 25/90 通道与缓存 | 直接消费，绝不参数化为 10 指数 |
| `resolve_local_minute_capability` | local/dev 开关、Lake root、DuckDB 门禁 | M5 复用，不新增设置 |
| `StockMinsLakeReader` | 股票按年份 Gold 文件、游标和 schema 校验 | 指数是按交易日 Silver/Gold，不能继承或复制路径算法 |

### 4.2 前端现状

| 当前文件/符号 | 已有能力 | 本页结论 |
|---|---|---|
| `WealthRouter.tsx` | 解析股票详情，其余路由回市场总览 | 增加 index parser，顺序在默认回退前 |
| `routerState.ts` | `buildStockDetailPath` 和 history 通知 | 增加 `buildIndexDetailPath` |
| `MajorIndexPanel.tsx` | 卡片是 button，但点击只 toast | 改为上报 `onIndexSelect(code)` |
| `MarketOverviewPage.tsx` | 股票导航和 toast | 增加 `openIndexDetail`，不在卡片内拼 URL |
| `StockDetailPage.tsx` | page-init 后请求 kline、AbortController、本地分钟缓存 | 只参考请求生命周期；指数需更完整状态机 |
| `stockDetailViewModelAdapter.ts` | 把 null 转 0 | 指数禁止复用此策略 |
| `StockChartWorkspace.tsx` | 4 面板、crosshair、tooltip、90 根窗口 | 抽取通用引擎，保留 stock 领域 adapter |
| `StockMinuteChartWorkspace.tsx` | 股票分钟 4 面板 | M5 不直接复用股票路径/DTO；可复用通用绘图能力 |
| `wealthFetch` | 401 刷新 token 和失效会话通知 | 原样复用；指数错误类型另保存 HTTP status |
| `TopMarketBar` | 共享顶部栏 | 所有指数状态原样复用 |

### 4.3 不能照搬的实现

1. `StockDetailPage` 的 loading/error 只有顶部栏和居中状态块，不符合指数完整状态稿。
2. `stockDetailViewModelAdapter` 的 `valueOrZero` 会制造假 K 线和技术指标尖峰。
3. `StockMinsLakeReader` 使用 `gold/.../year=YYYY`，指数分钟使用 `silver/gold/.../trade_date=YYYY-MM-DD`。
4. 既有趋势接口使用 snake_case 查询参数与响应字段，不是 Wealth camelCase DTO。
5. `IndexWeightDAO.get_latest_weights()` 的排序不符合页面权重降序要求，不修改 DAO 旧语义，详情建立专用 query。

---

## 5. CodeGraph 影响面记录

本轮在仓库根执行 `codegraph status/query/impact`，索引为 up to date。关键结果：

1. `WealthRouter` 当前直接影响自身；新增 index route 需要配套 router test。
2. `buildStockDetailPath` 的调用链到 `MarketOverviewPage.openStockDetail`；新增 index builder 不改 stock builder。
3. `MarketMajorIndicesQueryService` 影响主要指数 API/query 共 11 个符号；详情页只读同一策略配置，不修改该服务或响应。
4. `StockDetailPageInitResponseDto` 同时影响后端 schema、TS DTO、adapter 和页面；因此本页新增独立 DTO，禁止向股票响应加字段。
5. `QuoteTrendChannelQueryService` 的消费者为 Quote route 和两组测试；指数页面不改 service、cache、calculator 或 schema。
6. `StockChartWorkspace` 的真实页面消费者是 `StockDetailPage`；共享提取必须用 import 搜索和 stock 页面测试补足 CodeGraph 对 TSX 动态关系的不足。

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
                 -> IndexWeight + Security + EquityDailyBar
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
  useIndexTrendChannel.ts
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
    supportsNineTurn: false;
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
5. breadth 的三项统计在 `asOfTradeDate` 计算；无权重批次时为 `null`，不是三个 0。
6. `supportsTrendChannel` 只在 code 为 `000001.SH` 时为 true，且仅日线使用。
7. local capability disabled 时 `availablePeriods=["day"]`、分钟频率为空；enabled 时追加七个分钟 key。
8. `availableMainOverlays` 对上证指数包含 `TREND_CHANNEL`，其余 9 个只含 `MA/BOLL`。
9. Partial 提示不增加另一个自由文本合同。前端从 quote/dailyBasic 的真实 null 字段和 breadth 的 `missingCount/dataStatus` 生成缺失项列表；Figma fixture 不写死。
10. page-init 状态解析固定为：quote 无行是 EMPTY；quote 存在但同日 factor 量额、dailyBasic 整行/字段缺失、breadth 为空或 `missingCount>0` 是 PARTIAL；没有 partial 原因且 observed 落后 expected 是 DELAYED；其余是 READY。
11. `supportsTradePlanEntry=true` 只表达顶部入口存在；技术结论、趋势状态和任何数据 effect 均不得触发交易动作。

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
4. UI 显示 2 位并带正负号；排序仍只按原始 weight，不按贡献点。
5. index preClose、weight 或 constituent pct 任一缺失时 contribution 为 null，不补 0。

完整批次规则：

1. `weightTradeDate = max(index_weight.trade_date) <= contributionTradeDate`。
2. 先审计该批次 `count(*)`、`count(weight)` 和重复 key；发现 null weight 或重复时整个 weights 模块 ERROR，禁止过滤后返回半批次。
3. 正常查询按 `weight DESC, con_code ASC`。
4. `rows.length = totalCount = returnedCount`，`isTruncated=false`。
5. 名称缺失不删除行，显示 code；名称缺失不影响贡献 coverage。
6. 权重日期默认动态解析；`2026-07-31` 是当前生产验收基线，不硬编码在业务代码。
7. weights endpoint 先按 page-init 同口径解析最新指数日线。若完全没有指数日线，返回 `dataStatus=EMPTY`、`contributionTradeDate=pageContext.tradeDate`、`weightTradeDate=null`、空 rows；页面 EMPTY 不主动请求该接口。只要存在观测日，`contributionTradeDate` 就必须等于该观测日。

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

6. 单条集合聚合 breadth，不能把全量成分拉到 Python 再计数：

```sql
SELECT
  count(*) AS total_count,
  count(e.pct_chg) AS matched_count,
  count(*) FILTER (WHERE e.pct_chg > 0) AS up_count,
  count(*) FILTER (WHERE e.pct_chg = 0) AS flat_count,
  count(*) FILTER (WHERE e.pct_chg < 0) AS down_count
FROM core_serving.index_weight w
LEFT JOIN core_serving.equity_daily_bar e
  ON e.ts_code = w.con_code
 AND e.trade_date = :as_of_trade_date
WHERE w.index_code = :ts_code
  AND w.trade_date = :weight_trade_date;
```

`missingCount = totalCount - matchedCount`，并断言：

```text
up + flat + down = matched
matched + missing = total
```

`missing > 0` 时 breadth 和 page-init 为 PARTIAL，但三个已计算计数保留。没有权重批次时 breadth 为 null，15 项中的三个计数显示 `--`。

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
2. max weight date + batch contract count。
3. 全量权重 LEFT JOIN Security 名称。
4. 一次 `IN (:codes)` 查询当日 EquityDailyBar pct_chg，或在第 3 条中直接 LEFT JOIN。

推荐单条主查询：

```sql
SELECT w.con_code, w.weight, s.name, e.pct_chg
FROM core_serving.index_weight w
LEFT JOIN core_serving.security_serving s
  ON s.ts_code = w.con_code
LEFT JOIN core_serving.equity_daily_bar e
  ON e.ts_code = w.con_code
 AND e.trade_date = :contribution_trade_date
WHERE w.index_code = :ts_code
  AND w.trade_date = :weight_trade_date
ORDER BY w.weight DESC, w.con_code ASC;
```

禁止：

1. 每行查名称或日线的 N+1。
2. 为凑 100% 修改 weight。
3. 用权重列表前 10 行计算 coverage。
4. 把 `pct_chg IS NULL` 当 0 或 FLAT。

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
limit=<与日线 kline 一致，默认 300>
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
2. visible range、90 根默认窗口、缩放/拖动、crosshair 同步。
3. 时间轴、浮动价格轴标签和 tooltip 定位。
4. MA/BOLL 可选主图层和 null-safe line/histogram 数据。
5. 接收可选 pane primitive，不理解趋势业务公式。

### 12.2 领域 adapter 职责

`StockChartWorkspace`：

1. 把 StockCandlePoint 映射到 shared candle。
2. 提供股票 tooltip 字段、单位、aria 文案和 toolbar action。
3. 保留股票当前默认窗口、DOM 可见结果和颜色。

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
| `ID_BASIC_BREADTH_PARTIAL` | 200 PARTIAL | 成分同日行情缺失 | 三计数保留并提示 coverage |
| `ID_WEIGHT_EMPTY` | 200 EMPTY | 无权重批次 | 权重 Tab Empty |
| `ID_WEIGHT_CONTRIBUTION_PARTIAL` | 200 PARTIAL | preClose/pct 缺失 | 行保留，贡献 `--` |
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

Technical 读取已经加载的 kline 最新指标和 trend 状态，不另发“技术结论”或“九转”请求。技术结论、九转固定显示 `--`，没有 mock 句子。

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
4. 九转 `--`。
5. 不出现买入、卖出、建议、机会、风险评级等主观结论。

---

## 16. 本地指数分钟 LLD（M5）

### 16.1 启用前提

1. `APP_ENV in {dev, local}`。
2. `WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=true`。
3. `GOLDENSHARE_LAKE_ROOT` 可读且指向正式 `/Volumes/datasource/data_lake` 语义根。
4. DuckDB 可 import。
5. Silver/Gold 当前合同已提交、正式物理验收通过。

任一前提不满足都不挂 index minute router。prod/staging 请求路径为 404。

### 16.2 物理合同

Bars：

```text
silver/quote/major_index_mins/
  freq={1min|5min|15min|30min|60min|90min|120min}/
  trade_date=YYYY-MM-DD/
  part-000.parquet
```

Silver 文件列按当前合同为：

```text
ts_code, freq, trade_time, open, close, high, low, vol, amount, exchange, vwap
```

文件本身没有 `trade_date` 列；reader 从已验证的 partition path 取得日期，并校验 `CAST(trade_time AS DATE)` 与 partition 一致。

Indicators：

```text
gold/indicator/major_index_mins_technical/
  freq={1|5|15|30|60|90|120}/
  trade_date=YYYY-MM-DD/
  part-000.parquet
```

Gold 列：`ts_code, freq, trade_date, trade_time, ma_5..ma_250, boll_mid/upper/lower, macd_dif/dea/macd, kdj_k/d/j, observation_count, params_key, indicator_version`。

Web reader不读取 `major_index_mins_technical_state`，也不 import orchestrator 的 writer/asset/check。

### 16.3 Reader 结构

`major_index_mins_contract.py` 冻结 Web 只读端需要的：

1. 七个频率及 API int -> Silver string 的映射。
2. Silver/Gold 列名和类型。
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

请求字段与股票分钟相似但 DTO 独立：`tsCode/freq/startDate/endDate/limit/cursor`。默认 limit 500，最大 10000。

Bars 与 indicators 用相同 endDate/limit 窗口。前端不能用 `Promise.all` 让 indicators 缺失清空 bars；bars READY + indicators ERROR 应显示分钟 K 线并让技术图层 PARTIAL。

### 16.5 已知数据范围

当前 Silver 合同显式排除 `899050.BJ`。因此 local capability 表示“指数分钟功能已启用”，不保证每个 code/date 均有数据；北证50请求无有效 Silver 时返回明确 EMPTY/DELAYED，不 fallback 到旧 Lake、日线或第三方接口。

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
| weights | 最大约 2224 行、两次 LEFT JOIN | P95 <= 800ms |
| trend | 既有缓存接口，默认 300 行 | 沿用既有门禁 |

所有 P95 必须在与生产拓扑等价的 Web-host -> PostgreSQL 路径复核；本地跨网络结果不冒充生产同机/同网性能。

M0 已完成数据库内基线：300 根 P95 1.636ms；2000-limit P95 2.127ms，但后者在 M0 快照只返回 388 行。它证明索引路径，不证明真实 2000 行 API payload。

### 18.2 M1 实现后生产只读复验

2026-08-11 使用最终代码、同一 SQL 投影和显式只读事务复验 10 个指数。每个接口按 10 code × 5 轮，共 50 个样本；计时包含本机到生产 PostgreSQL、query/service、Pydantic DTO 组装和 JSON 序列化，不包含 HTTP Server 中间件。它是严格的跨网络实现链复验，不冒充生产 Web-host 同拓扑 P95。

| 链路 | 实际行数 | P50 | P95 | max | payload max | 判定 |
|---|---:|---:|---:|---:|---:|---|
| page-init | 固定单标的 + breadth 聚合 | 161.812ms | 246.054ms | 247.276ms | 1,653 B | PASS |
| kline 300 | 300 | 126.671ms | 211.169ms | 226.565ms | 162,606 B | PASS |
| kline 2000 上限 | 455~630 | 143.777ms | 248.925ms | 263.420ms | 337,689 B | PASS（非真实 2000 行） |
| weights | 50~2224 | 184.854ms | 271.337ms | 290.305ms | 276,419 B | PASS |

精确生产 `EXPLAIN ANALYZE`：factor-only 300 根 1.681ms，2000 上限实返 630 根 1.869ms；MA 历史基数查询 2.063ms；page-init latest daily + 同日 factor 0.071ms；上证 2224 成分 breadth 聚合 4.488ms，完整权重名称/行情 LEFT JOIN 12.927ms。查询均使用现有主键或日期索引；2000 上限查询只对单 code 的 630 行做内存排序，不存在跨标的无界扫描。

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
```

覆盖：

1. `pct_change/kdj_bfq` 等精确字段映射。
2. amplitude 正常、null、preClose=0。
3. 贡献正/负/零、缺输入、4 位 ROUND_HALF_UP。
4. 权重不归一化、不缩放。
5. status 优先级和 reason。
6. breadth 等式与 missing 不进 flat。
7. minute path 越界、非法 cursor、schema/type、partition/date 不一致。

### 19.2 后端真实 API fixture

新增 `tests/web/test_wealth_index_detail_api.py`，按现有 Web DB fixture 创建：

1. `TradeCalendar`
2. `IndexBasic`
3. `IndexDailyServing`
4. `IndexDailyBasic`
5. `IndexFactorPro`
6. `IndexWeight`
7. `EquityDailyBar`
8. `Security`

至少覆盖：

1. 10 配置 code page-init 成功；第 11 code 404。
2. identity 缺失 404，配置错误 fail closed。
3. 默认/显式 tradeDate，latest <= expected，DELAYED。
4. quote EMPTY 后不返回 mock。
5. dailyBasic 同日缺行/单字段 null。
6. breadth up/flat/down/missing 和两条数量恒等式。
7. kline 只允许 day、不接受 adjustment、升序、limit 边界。
8. 因子 null 保持 null，KDJ J 映射正确，不返回 MA15/MA120。
9. 权重日期、全量长度、稳定排序、名称缺失、null pct、preClose 缺失。
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
8. Technical 的结论/九转为 `--`，没有主观建议。
9. trend N 点 segment 数量、每日竖线、四种颜色、等于下轨边界、缺日断开。
10. trend error 不清空 kline/basic。
11. line/histogram null 不被送成 0。
12. StockChartWorkspace 90 根、crosshair、tooltip、MA/BOLL 回归。
13. system 状态色不使用 market up/down token。

### 19.5 真实 API 与像素验收

1. 本地启动真实 Web + Wealth，不使用 mock/scaffold fallback。
2. 逐一点击 10 卡；重点验收上证、深证、创业板、沪深300、北证50。
3. 1600×1200 对比 Basic、Weights、Technical 和五状态基线。
4. 普通 UI 元素偏差 <= 2px；字体、颜色、圆角、间距一致。
5. 图表、坐标轴、趋势、Tooltip、十字线不得因右栏或状态切换位移。
6. Weights 表头固定、视窗恰好 10 行、可滚到全量末行。
7. Partial 用至少两组不同缺失字段 fixture，证明提示非写死。

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
| M3 | route、10 卡导航、Loaded、三 Tab、trend primitive | Loaded 三画板通过 | index detail loaded |
| M4 | 五态、404、Delayed、模块 retry | 状态测试 + 五画板截图 | index detail states |
| M5 | local reader/router/minute chart | Lake 合同、性能、local/prod 矩阵 | index local minutes |
| M6 | 全回归与 prod smoke | prod 仅日线、无分钟 route | release verification |

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
| 技术结论/九转留空 | 15.4 | `--` 与无 API 请求 |
| 五个完整状态 | 13.4 | 页面测试 + 像素截图 |
| local minute/prod 404 | 16 | route 矩阵/临时 Parquet |
| 共享图表无复制 | 12 | stock 回归 + import 审计 |
| 交易计划仅用户点击 | 14.5 | effect 不触发 action |

---

## 22. 风险、阻断条件与后续评审

| 风险/阻断 | 当前事实 | 处理 |
|---|---|---|
| factor 实际历史仍少于 2000 根 | 当前 9 个指数 630 根、A500 455 根，不能证明真实 2000 行 payload | M1 的 2000 上限请求已验收当前实返行数；真实 2000 行仍保留为发布前门禁 |
| 深市两源量额分叉 | 399001/399006 自 2026-07-06 起 factor 与 daily 不同 | 外部核对确认 factor 准确；指数详情统一取 factor，禁止 daily fallback 或倍率换算 |
| 历史回填改变 MA 可计算边界 | 当前 A500 空值前缀被固化为 code/date 规则 | 按实际有效历史根数判断；回填后自动重分类并复审覆盖 |
| 趋势旧契约命名不同 | snake_case，与 Wealth DTO 风格不同 | feature-local adapter，不改旧 API |
| 趋势 state 与视觉颜色不同 | 后端是迟滞状态，页面是 close/lower | 明确忽略 state 判色并做冲突样本测试 |
| 权重全量最大 2224 行 | API/DOM 可能膨胀 | 集合查询 + <1 MiB + 虚拟化 |
| dailyBasic 只覆盖部分指数 | 4 个指数当前无行 | null/`--` 是正式合同，不 fallback |
| 上证 breadth 有 40 missing 样本 | 三项统计不是全覆盖 | 保留计数 + coverage + PARTIAL |
| shared chart 改动股票 | M2 已拆为 477 行 shared engine、362 行 stock adapter，并补 null-safe series | 已通过独立组件测试、全量 Wealth 回归和 1600×1200 前后尺寸对账；M3 只新增 index adapter/primitive |
| Figma 旧节点冲突 | `425:190` 仍有旧字段 | 永久排除出金标 |
| Gold minute 实现尚在脏工作树 | 合同/writer 未形成稳定基线 | M5 前单独提交、验收，不引用未提交实现作为事实 |
| 北证50无 Silver | 当前合同显式排除 | local 返回 Empty/Delayed，不 fallback |
| shared capability 错误码含 `SM_` | 历史股票命名 | 只作启动错误；不作为 index HTTP 语义复用 |

### 22.1 进入编码前必须确认的检查项

1. [ ] 本 LLD 完成产品、后端、前端评审。
2. [x] 10 指数 factor 审计、最终 SQL、完整服务链和当前实返 payload P95 通过；真实 2000 行仍保留为后续门禁。
3. [x] page-init/kline/weights DTO `1.1.0` 已冻结。
4. [x] 贡献输出按 4 位舍入、UI 2 位的精度规则已冻结。
5. [x] 异常码已登记。
6. [x] shared chart M2 的股票截图/测试基线已保存；1600×1200 前后截图及结构量测位于本机验证目录 `/private/tmp/goldenshare-index-detail-m2/`。
7. [ ] Figma `414:447` 权重行高在实施前从节点属性实测并记录。
8. [ ] M5 开始前分钟 Gold 合同与物理数据验收通过。

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
| v1.5 | 2026-08-11 | 完成 M2：提取 shared detail chart engine/pane/types/series/formatters/CSS，股票 adapter 保留领域文案、单位与交互；新增 null 断点/省略、四面板、90 根、crosshair、tooltip、MA/BOLL 测试，并记录 1600×1200 前后结构量测完全一致 | Codex |
| v1.4 | 2026-08-11 | 完成 M1 后端：独立三接口、严格参数/异常映射、factor-only Kline、动态 MA 历史判断、完整权重贡献；补 10 code 真实路由、源字段负例、旧契约回归及生产只读性能复验 | Codex |
| v1.3 | 2026-08-11 | 外部核对确认 factor 量额准确；page-init 同日量额与 Kline 全量额统一取 factor，删除 Kline daily JOIN，补 page-init 精确 JOIN、fallback 负向门禁与性能复验；DTO 提升为 1.1.0 | Codex |
| v1.2 | 2026-08-11 | 修正 MA null 低层口径：删除 A500/固定日期特例；增加按实际历史根数判断的条件查询、PARTIAL 规则和性能复验门禁；DTO 提升为 1.0.1 | Codex |
| v1.1 | 2026-08-11 | 完成 M0：落生产因子覆盖/性能审计、冻结独立 DTO 1.0.0、登记异常码；记录深市量额分叉、当时 A500 MA250 空值与真实 2000 行性能限制；量额最终来源已由 v1.3 修订 | Codex |
| v1 | 2026-08-11 | 基于最新 Figma、三件套、当前代码、CodeGraph、生产字段审计与分钟 Lake 合同形成首版 LLD；冻结文件结构、DTO、SQL、状态机、趋势 primitive、共享图表、测试和实施顺序 | Codex |
