# 指数详情页技术实施方案 v1

> 状态：草案，待评审；本轮不写业务代码。
> 对应需求：[指数详情页标杆需求 v1](./index-detail-benchmark-requirement-v1.md)
> 对应门禁：[指数详情页 M2 编码前门禁 v1](./index-detail-m2-coding-gate-v1.md)

---

## 1. 方案结论

指数详情页可以按现有交互设计实施，但不能直接复制股票详情页或直接调用旧 Quote 聚合链路。推荐落法是：

1. 在 Wealth 命名空间新增独立的 `index-detail` BFF 模块。
2. 复用市场上下文、主要指数策略配置、鉴权和通用图表能力。
3. 日线行情/因子、权重贡献、趋势通道分别由稳定模块 API 输出，前端只通过 adapter 组装 ViewModel。
4. 将股票详情图表中的通用多面板引擎提取到 `shared/charts`，股票与指数保留各自页面适配层；禁止复制 751 行图表实现。
5. 生产只发布日线；本地分钟作为独立后置里程碑，只有 Lake 合同与本地 capability 同时通过才挂路由。
6. 技术结论和九转不纳入本轮 API，不返回 mock 或前端推导值。

## 2. 跨模块抽象门禁原则

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一 | 名单、行情、因子、权重、贡献与通道各有唯一后端事实源 | query/service + DTO | 字段逐项源映射 |
| 契约先行 | 三件套评审后才冻结 DTO | schema/API types | schema extra forbid + TS typecheck |
| 配置一致 | 复用 `majorIndices` 和现有 local minute 配置，不新增页面常量 | config service/capability | 10 code 与 profile 矩阵 |
| 默认显式 | 默认日线、基本行情页签、300 根、权重完整批次 | schema defaults/adapter | 缺参、边界、负向测试 |
| 排序确定 | 权重降序、code 次序；K 线时间升序 | query | 同权重/乱序样本 |
| 性能前置 | 小查询、权重全量批次与虚拟化、趋势缓存、分钟限页 | query/cache/reader | P95 与 payload 门禁 |
| 状态标准化 | 页面状态与各模块状态分开 | response dataStatus | READY/DELAYED/EMPTY/PARTIAL/ERROR |
| 用户结果优先 | 真实 API + 浏览器可见结果为验收 | web tests + frontend tests | 无 mock 回退、10 路由、页签 |

## 3. 当前代码与设计审计

### 3.1 前端现状

1. `WealthRouter.tsx` 只解析股票详情路由，没有指数详情路由。
2. `routerState.ts` 只有 `buildStockDetailPath()`。
3. `MajorIndexPanel.tsx` 已使用按钮并提示“点击指数卡进入指数详情”，但当前点击只调用 `onAction("进入详情：code")` 弹 toast。
4. `StockDetailPage.tsx` 已形成 `page-init -> kline` 真实 API 加载、日线默认、本地分钟按 capability 解锁的参考链路。
5. `StockInfoRail.tsx` 只有“盘口 / 资料”两页签，不能直接改名复用为指数三页签。
6. `StockChartWorkspace.tsx` 为 751 行、类型与文案绑定 stock；直接复制会形成第二套图表引擎。
7. `stockDetailViewModelAdapter.ts` 会把技术因子 `null` 转为 0。指数详情不得复用此空值策略，否则会在指标图上制造零值尖峰。
8. `TopMarketBar` 已是 shared 组件，应原样复用。
9. `StockDetailPage.tsx` 当前页面级只实现 loading/error；`StockMinuteChartWorkspace.tsx` 实现模块级 loading/empty/delayed/error；401 由 `wealthFetch + AuthProvider` 跳登录。403、PARTIAL、权重局部重试不能声称“股票详情已现成”，必须在指数详情状态机中补齐。

### 3.2 后端现状

1. `GET /api/v1/wealth/market/major-indices` 已由 `majorIndices` 策略配置驱动 10 个指数及顺序。
2. 股票详情已在 `src/biz/{api,queries,schemas,services}/wealth/market/stock_detail` 建立可参考的分层。
3. `QuoteQueryService` 能读取指数日/周/月线并临时计算指标，但它属于旧 Quote 大服务；本模块不继续扩写该服务。
4. `core_serving.index_factor_pro` 已有 ORM 与完整 bfq 指标字段，但 10 指数生产覆盖尚未成为本页已验收事实，必须在编码前审计。
5. `IndexWeightDAO.get_latest_weights()` 能选最近批次，但返回按 `con_code` 排序，不符合页面“按权重排序”；页面查询不能照搬排序语义。
6. 现有趋势通道路由 `/api/v1/quote/detail/trend-channel` 和 schema 只接受 `000001.SH + day`，公式版本也是 SSE 专项；不能声称已覆盖其余 9 个指数。
7. 当前 local minute capability 已统一管理 `APP_ENV`、`WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED`、`GOLDENSHARE_LAKE_ROOT` 和 DuckDB 依赖，无需新增第二套开关。
8. `major_index_mins` Silver 与 `major_index_mins_technical` Gold 路径/七频率合同已进入当前工作树，但数据集文档仍要求完成正式写湖与验收；页面分钟能力必须后置。

### 3.3 CodeGraph 影响面

本轮方案审计使用了 `codegraph status/files/search/impact`，索引处于 up-to-date。关键影响面：

1. `StockDetailPage` 当前只影响股票详情页面文件；图表共享提取需要额外通过 import 搜索和前端测试锁定消费者。
2. `MarketMajorIndicesQueryService` 影响主要指数 API 及其查询服务；详情页只消费同一策略配置，不修改卡片响应契约。
3. `IndexWeightDAO` 当前消费者为 DAO factory 与 DAO 测试；详情页建议建立业务查询，不改变 DAO 既有排序契约。
4. `QuoteTrendChannelQueryService` 影响旧 Quote API 与完整趋势通道测试集。新页面应复用计算器并参数化查询，不破坏旧 SSE 响应。

## 4. 目标架构

```text
MarketOverview / 10 cards
  -> /wealth/market/index/:tsCode
  -> IndexDetailPage
       -> page-init
       -> kline ----------------> index_factor_pro
       -> trend-channel --------> index_daily_serving + shared calculator
       -> weights (lazy) -------> index_weight + equity_daily_bar
       -> local minutes --------> Lake Silver/Gold (local only)
```

边界：

1. `foundation` 只提供模型、配置 capability 与本地 Lake reader，不依赖 `biz/app`。
2. `biz` 负责指数详情事实查询、贡献点计算、状态和 DTO。
3. `app` 只挂路由与鉴权依赖。
4. `wealth` 前端只消费 DTO，经 adapter 转为 ViewModel。
5. 不修改 `src/platform`、`src/operations`、Dagster 写链或生产数据表。

## 5. 目录与文件计划

### 5.1 后端

```text
src/biz/
  api/wealth/market/
    index_detail.py
    index_detail_minutes.py              # local 条件路由
  queries/wealth/market/index_detail/
    __init__.py
    index_detail_query.py
    index_detail_query_service.py
    index_detail_trend_channel_service.py
    index_detail_minutes_query_service.py
  schemas/wealth/market/
    index_detail.py
    index_detail_minutes.py
  services/wealth/market/index_detail/
    __init__.py
    index_detail_field_mapper.py
    index_weight_contribution_builder.py
    index_detail_status_resolver.py

src/foundation/clients/local_lake/
  major_index_mins_reader.py              # 只读 Silver/Gold
```

现有文件修改：

1. `src/app/api/v1/router.py`：挂正式 index-detail router；local capability true 时再延迟挂分钟 router。
2. `src/biz/queries/quote_trend_channel_query.py`：把查询实例参数化为 `ts_code`，默认值仍为 `000001.SH`。
3. `docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md` 及 LLD：记录共享计算器/参数化查询的复用边界，但旧接口仍只支持 SSE。
4. `wealth/docs/system/exception-code-registry.md`：编码前登记已评审的 `ID_*` / `IM_*` 异常码。

### 5.2 前端

```text
wealth/src/
  pages/index-detail/
    IndexDetailPage.tsx
    IndexDetailPage.test.tsx
    index-detail-page.css
  features/index-detail/
    api/
      indexDetailApiClient.ts
      indexDetailApiTypes.ts
      indexDetailViewModelAdapter.ts
      indexDetailMinuteApiClient.ts
    model/
      indexDetailTypes.ts
      indexDetailConstants.ts
    chart/
      IndexChartWorkspace.tsx
      IndexMinuteChartWorkspace.tsx
    layout/
      IndexBreadcrumbActionBar.tsx
      IndexChartToolbar.tsx
    sidebar/
      IndexInfoRail.tsx
      IndexBasicTab.tsx
      IndexWeightsTab.tsx
      IndexTechnicalTab.tsx
  shared/charts/detail-workspace/
    DetailChartWorkspace.tsx
    detailChartTypes.ts
    detailChartFormatters.ts
```

现有文件修改：

1. `WealthRouter.tsx`：解析指数详情路由。
2. `routerState.ts`：新增 `buildIndexDetailPath()`。
3. `MajorIndexPanel.tsx`：改为接受 `onIndexSelect(code)`。
4. `MarketOverviewPage.tsx`：调用 `navigateWealth(buildIndexDetailPath(code))`。
5. `StockChartWorkspace.tsx`：收敛为 stock adapter，消费 shared 图表引擎；股票页面视觉与行为不变。

页面文件仍只负责请求编排与状态，不得超过 400 行。

## 6. API 设计

### 6.1 `GET /index-detail/page-init`

请求：

```ts
interface IndexDetailPageInitRequest {
  tsCode: string;
  tradeDate?: string;
  debug?: 0 | 1;
}
```

响应核心：

```ts
interface IndexDetailPageInitResponse {
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
    amplitude: number | null;
    vol: number | null;
    amount: number | null;
    amountChangePct: number | null;
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
    supportsUserActions: false;
  };
  dataStatus: DataStatusDto;
  debugInfo?: unknown;
}
```

实现规则：

1. `tsCode` 必须属于当前 `majorIndices` 配置，否则 404。
2. 不在服务层根据 `sessionStatus` 再减一天；`MarketPageContextQuery.pageContext.tradeDate` 已是默认期望完成日。
3. quote 查询 `index_daily_serving.trade_date <= pageContext.tradeDate` 的最近两行；最新行日期是 `asOfTradeDate`，两行用于 `amountChangePct`。
4. 无 quote 时 `asOfTradeDate=null` 且状态 EMPTY。
5. 不在 page-init 加载 K 线、权重或趋势历史。

### 6.2 `GET /index-detail/kline`

请求：

```ts
interface IndexDetailKlineRequest {
  tsCode: string;
  period?: "day";       // default day
  startDate?: string;
  endDate?: string;
  limit?: number;        // default 300, 1..2000
  debug?: 0 | 1;
}
```

明确不接受 `adjustment`。响应 bars 从 `index_factor_pro` 读取 bfq OHLC、MA、BOLL、MACD、KDJ；时间升序，warm-up 空值保持 `null`。API 不返回 `MA15/MA120`，不在请求链计算源表没有的指标。

编码前必须用 10 个指数和至少 300 个交易日完成生产覆盖审计：代码覆盖、日期覆盖、关键字段非空率、OHLC 与 `index_daily_serving` 同日一致性。审计不通过则本里程碑停在门禁，不做 fallback。

### 6.3 `GET /index-detail/weights`

请求：

```ts
interface IndexDetailWeightsRequest {
  tsCode: string;
  tradeDate?: string;
  debug?: 0 | 1;
}
```

响应：

```ts
interface IndexDetailWeightsResponse {
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
  dataStatus: DataStatusDto;
  note: "基于最新月度权重估算，非指数公司官方归因";
  debugInfo?: unknown;
}
```

查询链：

1. 解析 page-init 同口径的 `asOfTradeDate`，作为 `contributionTradeDate`。
2. 查询指数该日 `pre_close`。
3. 查询 `MAX(index_weight.trade_date) <= contributionTradeDate`。
4. 取该批次全部权重，按 `weight DESC, con_code ASC` 排序，不截断。
5. 批量查询全部成分股名称和同日 `equity_daily_bar.pct_chg`，禁止 N+1；优先使用集合 JOIN/批量查询，不按行循环请求。
6. 后端按已冻结公式计算贡献点；不归一化、不缩放、不填 0。

当前生产审计证据：10 个指数 raw/serving 最新批次均为 `2026-07-31`，serving 共 5274 行，无 null weight、无重复成分；批次权重和约 `99.984%~100.006%`。这说明不得对源值强制归一化，也说明当前日期基线可以使用。

### 6.4 `GET /index-detail/trend-channel`

请求固定 `tsCode + period=day + endDate + limit`。

实现策略：

1. 复用 `TrendChannelCalculator`，不复制 EMA/状态机代码。
2. 把 `QuoteTrendChannelQuery` 参数化为实例 `tsCode`；旧 Quote API 仍在入口层限制 `000001.SH`，旧 response 与公式版本不变。
3. 新 `IndexDetailTrendChannelService` 只允许 `majorIndices` 配置中的 code，使用独立 generic DTO 与缓存容量（至少 10 个 code）。
4. 新响应公式版本使用 `major-index-daily-trend-channel-v1`，明确与旧 SSE 接口的标的范围不同，但数值公式相同。
5. 前端按 `tradeDate` 与 kline 对齐；缺日不向前填充。
6. 技术页签的中轴只在服务端 adapter 中由最新短期上下轨算术平均得到，前端不计算。

### 6.5 本地分钟接口

保持股票分钟接口的环境隔离：

1. 复用 `resolve_local_minute_capability()` 与现有两项 Settings，不新增配置。
2. prod/staging 不 import reader、不 import DuckDB、不挂路由。
3. local enabled 后：
   - bars 只读 `silver/quote/major_index_mins/freq={freq}/trade_date={date}/part-000.parquet`；
   - indicators 只读 `gold/indicator/major_index_mins_technical/freq={freq}/trade_date={date}/part-000.parquet`；
   - 不读 state 文件，不触发 Dagster，不写 Lake。
4. 默认 500 根，cursor 时间键翻页；指标 null 保持 null。
5. `899050.BJ` 等历史覆盖边界按 Lake 合同返回 EMPTY/DELAYED，不从日线或其他指数补造。

## 7. 前端交互与状态机

### 7.1 首次加载

```text
route tsCode
  -> page-init
  -> Promise.all(kline, trend-channel)
  -> build view model
  -> render Basic tab (default)
```

权重接口在首次点击“权重股”时加载完整批次；成功后按 `tsCode + contributionTradeDate + weightTradeDate` 缓存在页面生命周期内。技术页签复用已加载趋势数据，不请求不存在的“技术结论 API”。

### 7.2 周期切换

1. 初始 `day`。
2. 生产：分时、周/月、所有分钟按钮都带 disabled/unsupported 状态；点击不改变 active period。
3. 本地：只解锁 `minuteFrequencies` 中存在的分钟按钮。
4. 从分钟切回日线直接使用日线缓存。
5. 权重页签始终显示日频贡献，不随分钟切换刷新。

### 7.3 右侧页签

1. 默认 `basic`。
2. `weights` 独立 loading/ready/partial/empty/error。
3. `technical` 在趋势可用时展示客观通道；技术结论和九转位置展示 `--`。
4. tab 切换只改本地 UI state，不改路由、不触发交易动作。
5. `weights` 表头固定；滚动视窗高度等于 10 行，使用虚拟化列表渲染完整 `rows`，不得把“只渲染可视行”误写为“只请求前 10 行”。
6. tab 切换后保留权重数据与滚动位置；重新进入同一 `tsCode + contributionTradeDate + weightTradeDate` 不重复请求。

### 7.4 交易计划边界

1. `+自选/+提醒/+交易计划` 延续股票详情当前占位行为：用户主动点击后显示“暂未开通”。
2. 技术结论、趋势通道、九转、页签切换、周期切换均不得调用这些 action handler。
3. 本轮不新增用户状态表、写 API 或交易流程。

## 8. 图表共享重构

### 8.1 拆分原则

`DetailChartWorkspace` 只负责：

1. 4 个同步面板（K 线、MACD、成交量、KDJ）。
2. crosshair、tooltip、时间轴、缩放窗口。
3. 可选 MA/BOLL 与可选趋势通道 line series。
4. null-safe line data：缺失指标跳过该点，不转换为 0。

页面/领域 adapter 负责：

1. stock/index 文案、单位和 toolbar。
2. DTO 到通用 candle 的映射。
3. period capability 和业务状态。

### 8.2 回归边界

1. 股票详情 DOM/CSS 与图表可见行为不得变化。
2. stock 当前 90 根可视窗口、crosshair 同步和 tooltip 定位必须保留。
3. 共享重构单独提交/里程碑验证后，再接指数趋势 overlay，避免把复用重构与业务故障混在一起定位。

## 9. 状态、异常与权限

建议在评审后登记以下异常码；未登记前不得编码：

| code | 场景 | 页面行为 |
|---|---|---|
| `ID_REQUEST_INVALID` | 非法代码/日期/limit | 400，显示请求错误 |
| `ID_NOT_FOUND` | 不属于 10 指数或基础信息不存在 | 404 页面 |
| `ID_SOURCE_EMPTY` | 日线主源无数据 | 页面 EMPTY |
| `ID_SOURCE_DELAYED` | observed 早于完成交易日 | DELAYED，显示日期 |
| `ID_FACTOR_PARTIAL` | 技术因子缺行/缺列 | 主图 PARTIAL，缺线不补 0 |
| `ID_WEIGHT_EMPTY` | 无可用权重批次 | 权重页签 EMPTY |
| `ID_WEIGHT_CONTRIBUTION_PARTIAL` | 成分日线/指数昨收缺失 | 行显示 `--`，页签 PARTIAL |
| `ID_TREND_UNAVAILABLE` | 通道源无效/更新中/计算失败 | 主图与技术页签 PARTIAL/ERROR |
| `ID_QUERY_FAILED` | 其它查询失败 | 对应模块 ERROR |
| `IM_SOURCE_NOT_READY` | 本地分钟文件未覆盖 | 分钟模块 DELAYED |
| `IM_SOURCE_CONTRACT_INVALID` | 本地 Parquet 合同错误 | 分钟模块 ERROR |
| `IM_QUERY_FAILED` | DuckDB/文件查询失败 | 分钟模块 ERROR |

鉴权统一使用 `require_quote_access`。未登录沿用 `AuthProvider` 登录跳转；已登录但无权限显示 FORBIDDEN，不将 403 伪装为空数据。

前端恢复动作固定如下：

| 失败范围 | 可见结果 | 恢复动作 |
|---|---|---|
| page-init 404 / 非法指数 | 页面未找到，停止后续请求 | 返回市场总览 |
| page-init/query fatal error | 保留 TopMarketBar 与页面错误壳 | 整页重试 page-init -> kline/trend |
| 401 | 清理失效会话 | 跳登录并携带 redirect |
| 403 | 整页 FORBIDDEN | 不自动重试，不转换为 EMPTY |
| 日线 EMPTY | 保留指数身份、工具栏和三 tab 壳 | 显示暂无数据；显式重试 |
| weights loading/error/empty | 只替换权重 tab，主图保持 | 局部重试 weights |
| weights PARTIAL | 保留完整行；缺失贡献显示 `--` 与说明 | 不自动补 0；允许局部重试 |
| trend/指标 error | 隐藏对应层或断点，基本行情保持 | 局部重试 trend/kline |
| local minute empty/delayed/error | 只替换分钟图，日线缓存保持 | 局部重试或切回日线 |

## 10. 测试与验证计划

### 10.1 后端真实 API

新增 `tests/web/test_wealth_index_detail_api.py`，至少覆盖：

1. 10 个配置 code 均可 page-init，非名单 code 为 404。
2. `MarketPageContextQuery` 默认日期、显式日期和 source delayed 三类锚点覆盖。
3. kline 只接受 day、不接受 adjustment、升序、null 不变 0。
4. page-init 与 kline 核心字段对照真实表。
5. 权重解析到 2026-07-31，完整批次、排序、覆盖计数、不截断和不归一化正确。
6. 贡献点正常、负值、零涨跌、成分日线缺失、指数昨收缺失均按公式断言。
7. 权重和实际指数涨跌点不相等时不缩放。
8. 趋势通道覆盖 10 个 code；旧 SSE Quote API 契约回归不变。
9. 权限、空、延迟、查询错误、部分缺失。
10. prod profile 分钟路由 404；local profile 真实临时 Lake 文件可查。

### 10.2 前端

新增/更新测试：

1. 10 卡点击导航到正确 index path。
2. router 解析和浏览器前进/后退。
3. initial loading、fatal error、empty、partial、forbidden。
4. 右侧三 tab 切换；权重只在首次点击加载一次，固定 10 行视窗、内部滚动、虚拟化且可到达末行。
5. 技术结论和九转显示 `--`，不存在 mock 文案。
6. prod 周期 disabled；local minute capability 解锁。
7. 页面不存在“前复权”。
8. 缺失因子不会渲染为 0。
9. 技术 tab 或趋势失败不清空日线/基本行情。
10. 股票详情共享图表回归。

### 10.3 浏览器与像素验收

1. 本地真实 API 启动后验证 `/wealth/market/index/000001.SH`。
2. 逐一点击 10 卡，至少抽检 000001/399001/399006/000300/899050。
3. 1600×1200 对比 Figma `423:2`、`423:910` 与三种 Info Rail variant。
4. 验证 tab、tooltip、周期 disabled、loading/error/partial/permission。
5. 像素误差和设计漂移记录到后续独立 verification ledger，不在业务代码中硬编码补偿。

执行命令：

```bash
pytest -q tests/web/test_wealth_index_detail_api.py tests/test_quote_trend_channel_query_service.py
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
```

## 11. 分期里程碑

| 里程碑 | 内容 | 退出条件 |
|---|---|---|
| M0 方案冻结 | 三件套评审、异常码、Figma 节点台账 | 门禁签字 |
| M1 数据与契约 | 10 指数 factor 覆盖审计、DTO、page-init/kline/weights/trend API | 真实 API 测试通过 |
| M2 图表共享 | 提取 shared 图表引擎，股票行为零回归 | stock tests + 浏览器对比通过 |
| M3 页面 Loaded | 路由、10 卡导航、日线、三 tab、贡献点、趋势 overlay | Figma Loaded 验收 |
| M4 异常状态 | loading/error/empty/partial/permission | 状态测试与截图通过 |
| M5 本地分钟 | reader、条件路由、分钟页面 | Lake 数据与性能门禁通过 |
| M6 发布验收 | prod 日线能力、分钟路由不存在、全回归 | 构建/测试/生产 smoke 通过 |

技术结论 API 与九转 API 不属于 M0-M6，分别立项后再扩展 DTO 与 UI。

## 12. 风险与缓解

| 风险 | 触发条件 | 缓解 |
|---|---|---|
| 趋势接口只支持 SSE | 直接拿旧接口服务 10 指数 | 保留旧契约，新增 Wealth 十指数适配层 |
| factor 生产覆盖不足 | 新 view 没有 10 指数/历史不够 | 编码前真实审计，失败即停，不 fallback |
| Figma 与数据语义冲突 | 示例贡献点不可复算、全市场成交说明不成立 | 以冻结公式和真实源语义覆盖示例文案 |
| 图表复用导致股票回归 | 直接改 751 行组件 | 先共享重构、单独验证、再加指数 overlay |
| 分钟 Lake 尚未正式 ready | 页面先暴露 capability | capability + Lake 门禁，prod 永不挂路由 |
| 贡献缺失被当 0 | adapter 使用 valueOrZero | index adapter null-safe，API coverage 明示 |
| 全量权重导致 DOM/响应膨胀 | 直接渲染完整数组或查询逐行补名 | 单次完整批次 API + 集合查询；前端虚拟化；P95 与 1 MiB payload 门禁 |
| 技术内容诱发交易含义 | 用通道自动生成建议/动作 | 客观事实与用户 action 严格分离 |

## 13. 需评审的五个技术口径

1. 同意旧 SSE 趋势接口保持不变、Wealth 新增十指数适配层。
2. 同意右侧通道三位置使用短期 `upper / midpoint / lower`。
3. **已按本轮产品决定更新**：权重 API 返回完整批次；前端固定 10 行视窗、表头固定、内部滚动并虚拟化，不提供任意 limit。
4. 同意“成交状态”首期显示 `--`，不做临时阈值分类。
5. 同意“较昨日”固定为成交额相对上一完成交易日的变化率。

## 14. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.1 | 2026-08-11 | 权重改为完整批次与 10 行虚拟滚动；补齐页面/模块异常恢复矩阵和当前股票详情实现差距 | Codex |
| v1 | 2026-08-10 | 基于现有代码、CodeGraph、Figma 与生产权重审计形成首版实施草案 | Codex |
