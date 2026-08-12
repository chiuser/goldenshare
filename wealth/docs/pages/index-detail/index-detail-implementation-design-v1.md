# 指数详情页技术实施方案 v1

> 状态：M1–M4 与 M5-A 已完成并通过验证；详情图表共享收敛与缩放已由 `b38ac20e`、`61a5adea` 完成；M5-A 使用真实 Silver K 线与开发态 Mock 指标，M5-B 保留真实 Gold 对接。
> 对应需求：[指数详情页标杆需求 v1](./index-detail-benchmark-requirement-v1.md)
> 对应门禁：[指数详情页 M2 编码前门禁 v1](./index-detail-m2-coding-gate-v1.md)
> 低层设计：[指数详情页低层设计 v1](./index-detail-low-level-design-v1.md)
> 正式 DTO：[指数详情页正式 API / DTO 合同 v1](./index-detail-api-contract-v1.md)
> M0 审计：[指数详情页 M0 生产因子审计 v1](./index-detail-m0-production-audit-v1.md)
> 分钟 DTO：[指数详情本地分钟 API / DTO 合同 v1](./index-detail-minutes-api-contract-v1.md)

---

## 1. 方案结论

指数详情页可以按现有交互设计实施，但不能直接复制股票详情页或直接调用旧 Quote 聚合链路。推荐落法是：

1. 在 Wealth 命名空间新增独立的 `index-detail` BFF 模块。
2. 复用市场上下文、主要指数策略配置、鉴权和通用图表能力。
3. 日线行情/因子、权重贡献由 Wealth 模块 API 输出；仅上证指数直接消费现有 Quote 趋势通道 API，前端统一组装 ViewModel。
4. 将股票详情图表中的通用多面板引擎提取到 `shared/charts`，股票与指数保留各自页面适配层；禁止复制 751 行图表实现。
5. 生产只发布日线；本地分钟作为独立后置里程碑，M5-A 以正式 Silver 合同与本地 capability 作为 K 线路由门禁，Gold 指标不阻塞 K 线。
6. 技术结论和九转不纳入本轮 API，不返回 mock 或前端推导值。

## 2. 跨模块抽象门禁原则

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一 | 名单、行情、因子、权重、贡献与通道各有唯一后端事实源 | query/service + DTO | 字段逐项源映射 |
| 契约先行 | 独立 DTO 已提升为 `1.2.0`，字段结构不变并冻结 A 股/停牌语义 | schema/API types | schema extra forbid + TS typecheck |
| 配置一致 | 复用 `majorIndices` 和现有 local minute 配置，不新增页面常量 | config service/capability | 10 code 与 profile 矩阵 |
| 默认显式 | 默认日线、基本行情页签、300 根、权重完整批次 | schema defaults/adapter | 缺参、边界、负向测试 |
| 排序确定 | 权重降序、code 次序；K 线时间升序 | query | 同权重/乱序样本 |
| 性能前置 | 小查询、权重全量批次与虚拟化、趋势缓存、分钟限页 | query/cache/reader | P95 与 payload 门禁 |
| 状态标准化 | 页面状态与各模块状态分开 | response dataStatus + HTTP error | 成功态 READY/DELAYED/EMPTY/PARTIAL；Error/Forbidden 走 HTTP |
| 用户结果优先 | 真实 API + 浏览器可见结果为验收 | web tests + frontend tests | 无 mock 回退、10 路由、页签 |

## 3. 当前代码与设计审计

### 3.1 前端现状

1. M3 已在 `WealthRouter.tsx` 增加 `/wealth/market/index/:tsCode` 解析，并由 `routerState.ts` 的 `buildIndexDetailPath()` 统一执行 trim、upper、encode。
2. `MajorIndexPanel.tsx` 只上报 `tsCode`，`MarketOverviewPage.tsx` 负责导航；10 张卡不再用 toast 模拟详情入口。
3. `IndexDetailPage.tsx` 只组合 TopMarketBar、页面骨架、controller、图表和右栏；真实请求生命周期位于 `features/index-detail/controller`。
4. `IndexChartWorkspace.tsx` 通过 M2 的 `DetailChartWorkspace` 适配指数数据，没有复制股票图表生命周期；股票仍由 `StockChartWorkspace.tsx` 独立适配。
5. 指数 adapter 对价格、因子和贡献严格 null-safe；MA250 等字段只根据接口实际返回决定是否为空，不按 code、日期或固定历史长度预设。
6. 上证趋势通道由 feature-local 旧合同 adapter 与 canvas primitive 绘制；其它 9 个指数既不展示入口，也不发请求。
7. `IndexInfoRail.tsx` 独立实现“基本行情 / 权重股贡献 / 技术面”三页签；权重完整批次在 400px 视窗中虚拟化，Tab 切换保留缓存和滚动位置。
8. M4 已在不重建 Loaded 页面的前提下补齐稳定四段骨架：Loading/Empty/Partial 保持双栏，Error/Forbidden/404 使用全宽 MainContent；页面级错误整页重试，趋势与权重错误局部重试，系统状态色不复用行情红绿。
9. M5-A 已新增独立指数分钟 Reader/API/controller/provider；`DetailChartWorkspace` 以显式 `daily|minute` 时间模式复用四窗格，不复制指数分钟图表生命周期。分钟切换只替换左侧图表，右栏、权重和趋势仍保持日线语义。

### 3.2 后端现状

1. `GET /api/v1/wealth/market/major-indices` 已由 `majorIndices` 策略配置驱动 10 个指数及顺序。
2. 股票详情已在 `src/biz/{api,queries,schemas,services}/wealth/market/stock_detail` 建立可参考的分层。
3. `QuoteQueryService` 能读取指数日/周/月线并临时计算指标，但它属于旧 Quote 大服务；本模块不继续扩写该服务。
4. `core_serving.index_factor_pro` 已有 ORM 与完整 bfq 指标字段；M0 已完成 10 指数当前快照覆盖、同日一致性和最终查询性能审计，MA 历史不足必须运行时按实际有效历史判断。
5. `IndexWeightDAO.get_latest_weights()` 能选最近批次，但返回按 `con_code` 排序，不符合页面“按权重排序”；页面查询不能照搬排序语义。
6. 现有趋势通道路由 `/api/v1/quote/detail/trend-channel` 和 schema 只接受 `000001.SH + day`，公式版本也是 SSE 专项；不能声称已覆盖其余 9 个指数。
7. 当前 local minute capability 已统一管理 `APP_ENV`、`WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED`、`GOLDENSHARE_LAKE_ROOT` 和 DuckDB 依赖，无需新增第二套开关。
8. `major_index_mins` Silver 七频率正式物理文件已通过只读审计；`major_index_mins_technical` Gold 仍在独立工作流实现，M5-A 不读取其未提交代码作为事实，也不修改对应资产/writer/check。

### 3.3 CodeGraph 影响面

本轮方案审计使用了 `codegraph status/files/search/impact`，索引处于 up-to-date。关键影响面：

1. `StockDetailPage` 当前只影响股票详情页面文件；图表共享提取需要额外通过 import 搜索和前端测试锁定消费者。
2. `MarketMajorIndicesQueryService` 影响主要指数 API 及其查询服务；详情页只消费同一策略配置，不修改卡片响应契约。
3. `IndexWeightDAO` 当前消费者为 DAO factory 与 DAO 测试；详情页建议建立业务查询，不改变 DAO 既有排序契约。
4. `QuoteTrendChannelQueryService` 只服务 `000001.SH + day`。本页直接消费既有响应，不修改查询、计算器、缓存和旧 SSE 契约；其余 9 个指数不发起请求。

### 3.4 指数日线基础展示字段审计

2026-08-11 对生产 `core_serving.index_daily_serving`、`core_serving.index_daily_basic`、`core_serving.index_factor_pro` 做了只读、限定 10 个 code 的字段投影审计：

1. 10 个指数最新日均为 `2026-08-10`；自 `2026-07-01` 起各有 29 行日线，`pre_close/open/high/low/vol/amount` 均为 29/29 非空。
2. `index_daily_basic` 只覆盖 `000001.SH`、`399001.SZ`、`399006.SZ`、`000300.SH`、`000905.SH`、`000016.SH`；其余 4 个指数无行。
3. 已确认基本行情固定展示：昨收、今开、总量、最高、最低、金额、市盈率、TTM 市盈率、市净率、换手率、流通市值、总市值、上涨数、平盘数、下跌数。
4. `pe/pe_ttm/pb/turnover_rate/float_mv/total_mv` 进入可空契约；没有行或字段为空时前端显示 `--`，不得把 4 个未覆盖指数伪装成 0。
5. 删除“成交状态”和“较昨日”；page-init 不再查询前一交易日成交额，也不返回 `amountChangePct`。
6. 上涨/平盘/下跌使用 `weightTradeDate <= asOfTradeDate` 的最新源权重批次，但先通过 `Security` 的证券类型、交易所和币种限定 A 股；B 股不进入页面成分范围。A 股同日 `equity_daily_bar.pct_chg` 优先，日线为空且 `equity_suspend_d.suspend_type=S` 时按 0%/FLAT，二者都不存在时才计 missing。
7. 2026-08-12 生产只读复核：10 个指数均解析到 `2026-07-31` 权重批次；上证 2224 个源权重成员中有 2184 个 A 股、40 个 B 股。页面最新日 `2026-08-11` 的 2184 个 A 股中，648 上涨、49 有效行情平盘、1485 下跌，另有 2 个确认停牌；最终 flat=51、matched=2184、missing=0。该证据证明 B 股排除和正常停牌不应触发 PARTIAL。

### 3.5 M0 指数因子审计结论

1. 10 个 code 各有 388 行 factor，日期范围均为 2025-01-02 ~ 2026-08-10；最新日与 daily 对齐，无重复主键。
2. 最近 300 根的 OHLC、昨收、涨跌、涨跌幅完全一致；MA/BOLL/MACD/KDJ 除 `000510.SH` 的 MA250 当前有 94 个空值外均 300/300 非空。
3. 审计时 `000510.SH` 全表 MA250 在 2025-09-30 首次可用，此前 182 行连续为空、此后 206 行无断裂；这是 2026-08-11 生产快照，不是代码中的指数/日期特例。2024 技术因子同步后应复审。
4. `399001.SZ`、`399006.SZ` 的 factor 量额自 2026-07-06 起连续 26 日与 daily 分叉。两个源文档单位相同，禁止倍率修正；产品方完成外部数据源核对后确认 factor 准确，基本行情与 Kline 的 `vol/amount` 均唯一取 factor。
5. M0 的 factor 驱动、daily 同日 LEFT JOIN 旧候选查询命中两侧主键，数据库内 P95 为 300 根 1.636ms、2000-limit 2.127ms。M1 已按最终 factor-only SQL 复测：300 根 1.681ms、2000 上限实返 630 根 1.869ms，MA 历史基数查询 2.063ms。
6. M1 复验时 9 个指数已同步到 630 根，A500 为 455 根；当时完整服务链 50 样本 P95 为 page-init 246.054ms、kline 300 211.169ms、kline 2000 上限 248.925ms、weights 271.337ms。1.2.0 于 2026-08-12 使用最终 Security A 股过滤和停牌 EXISTS 对 10 指数各复跑 5 轮：page-init P95 245.589ms、weights P95 267.319ms，最大 weights 为 2184 行/275,543B；上证最终 breadth/weights SQL 分别约 21.993ms/19.290ms，均通过既定门禁。当前仍没有真实 2000 行物理样本，因此该门禁继续保留。

### 3.6 最新 Figma 结构与状态审计

当前设计结构已按节点树重新核验：

1. Basic Loaded 根画板为 `417:2`，固定 `1600×1200`、纵向 Auto Layout；TopMarketBar `417:3` 复用主组件 `97:2`。
2. 根画板分为 56px TopMarketBar、42px 面包屑、44px 工具栏和 1058px 主内容区。主内容区为横向 Auto Layout，内边距 10px、栏间距 10px；左图表 `417:42` 为 `1193.1953125×1038`，右栏实例 `484:281` 为 `376.796875×1038`。
3. 图表绘图区 `417:42` 继续使用绝对坐标承载 K 线、趋势通道、九转位置、指标、坐标轴、十字线和 Tooltip；不得将这些点线改成普通流式布局。
4. 右栏实例 `484:281` 来自 Basic 组件 `414:446`；Weights/Technical 组件为 `414:447` / `414:448`。Tab 组件集为 `473:275`，三个 Tab 切换只替换右栏内容。
5. 趋势通道组件集 `413:25` 保留绝对坐标，包含四个位置示例；实际页面实例 `417:842` 只作为绘制与配色验收基线，业务颜色仍按每日收盘相对各自下轨计算。
6. 五个完整状态根画板已生成：Loading `498:516`、Empty `499:579`、Error `501:761`、Partial `502:1625`、Forbidden `504:1009`，全部为 `1600×1200` 并复用 TopMarketBar 主组件 `97:2`。
7. 交互说明根画板 `425:178` 已扩展为 `1600×1438`；验收、页面错误和模块错误卡片已下移，当前无背景叠放。
8. `425:190` 仍是旧的基本行情概述，含“振幅/较昨日”；它已被 Basic 组件 `414:446`、详细口径 `425:219` 和本文 15 项合同覆盖，禁止进入实现或测试金标。

## 4. 目标架构

```text
MarketOverview / 10 cards
  -> /wealth/market/index/:tsCode
  -> IndexDetailPage
       -> page-init
            -> index_daily_serving + index_daily_basic
            -> index_weight + security_serving + equity_daily_bar + equity_suspend_d
               (仅聚合 A 股成分涨跌三项与覆盖数)
       -> kline ----------------> index_factor_pro
       -> trend-channel (仅 000001.SH) -> 既有 Quote API
       -> weights (lazy) -------> index_weight + security_serving + equity_daily_bar + equity_suspend_d
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
    index_detail_page_query_service.py
    index_detail_kline_query_service.py
    index_detail_weights_query_service.py
  schemas/wealth/market/
    index_detail.py
    index_detail_minutes.py
  services/wealth/market/index_detail/
    __init__.py
    index_detail_universe.py
    index_detail_field_mapper.py
    index_weight_contribution_builder.py
    index_detail_status_resolver.py
    index_detail_exception_builder.py

src/foundation/clients/local_lake/
  major_index_mins_reader.py              # 只读 Silver/Gold
```

现有文件修改：

1. `src/app/api/v1/router.py`：挂正式 index-detail router；local capability true 时再延迟挂分钟 router。
2. `docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md`：同步页面绘制颜色和上下轨连线规则，不修改后端计算契约。
3. `wealth/docs/system/exception-code-registry.md`：编码前登记已评审的 `ID_*` / `IM_*` 异常码；趋势通道沿用既有 Quote 接口异常，不新增十指数异常码。

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
      trendChannelApiClient.ts
      trendChannelAdapter.ts
      indexDetailMinuteApiClient.ts             # M5
    controller/
      useIndexDetailController.ts
      useIndexWeights.ts
    model/
      indexDetailTypes.ts
      indexDetailConstants.ts
    chart/
      IndexChartWorkspace.tsx
      TrendChannelPanePrimitive.ts
      trendChannelGeometry.ts
      IndexMinuteChartWorkspace.tsx             # M5
    layout/
      IndexBreadcrumbActionBar.tsx
      IndexChartToolbar.tsx
    sidebar/
      IndexInfoRail.tsx
      IndexBasicTab.tsx
      IndexWeightsTab.tsx
      IndexTechnicalTab.tsx
    state/
      IndexDetailLoadingSkeleton.tsx
      IndexDetailPageState.tsx
      IndexDetailModuleState.tsx
      IndexDetailPartialNotice.tsx
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

状态组件边界：

1. `IndexDetailLoadingSkeleton` 只负责 Figma `498:516` 的图表与右栏骨架，不携带 mock 行情。
2. `IndexDetailPageState` 承载 EMPTY 主图、ERROR、FORBIDDEN 和 404 的页面级壳；文案与动作由受限状态枚举提供，不接受任意 JSX 拼装。
3. `IndexDetailModuleState` 只替换权重 Tab、趋势图层或分钟图模块，不得覆盖不受影响区域。
4. `IndexDetailPartialNotice` 根据接口返回的真实缺失字段生成说明；Figma 的三个缺失字段只是视觉 fixture，不得写成常量。

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
    dataStatus: DataStatusDto;
  } | null;
  chartDefaults: {
    defaultPeriod: "day";
    availablePeriods: Array<"day" | "m1" | "m5" | "m15" | "m30" | "m60" | "m90" | "m120">;
    availableMainOverlays: Array<"MA" | "BOLL" | "TREND_CHANNEL">; // TREND_CHANNEL 仅 000001.SH
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
  dataStatus: DataStatusDto;
  debugInfo: IndexDetailDebugInfoDto | null;
}
```

实现规则：

1. `tsCode` 必须属于当前 `majorIndices` 配置，否则 404。
2. 不在服务层根据 `sessionStatus` 再减一天；`MarketPageContextQuery.pageContext.tradeDate` 已是默认期望完成日。
3. quote 先查询 `index_daily_serving.trade_date <= pageContext.tradeDate` 的最近一行作为 `asOfTradeDate` 和价格来源，再精确读取同 code、同日 `index_factor_pro.vol/amount`；不读取 daily 量额，也不为“较昨日”读取前一日成交额。
4. 无 quote 时 `asOfTradeDate=null` 且状态 EMPTY。
5. `dailyBasic` 只读 `trade_date = asOfTradeDate` 的一行；整行或单字段缺失都保持 `null`，由前端逐字段显示 `--`。
6. `constituentBreadth` 只做最新有效源权重批次中的 A 股集合聚合，不返回成分明细。A 股由 `Security.security_type=EQUITY`、`exchange in (SSE,SZSE,BSE)`、`curr_type=CNY` 定义；B 股不进入总数和缺失数。A 股日线优先，确认停牌按 0%/FLAT；只有无日线且无停牌依据的 A 股才令模块 `dataStatus=PARTIAL`。
7. 不在 page-init 加载 K 线、权重明细或趋势历史。
8. `supportsTrendChannel` 仅对 `000001.SH + day` 返回 true；其余指数的 `availableMainOverlays` 不包含 `TREND_CHANNEL`。
9. `supportsTradePlanEntry=true` 只表达顶部入口存在；技术结论与任何数据状态不触发交易动作。

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

明确不接受 `adjustment`。响应 bars 的日期、价格、涨跌、`vol/amount` 与 MA/BOLL/MACD/KDJ 全部从 `index_factor_pro` 同一行读取；时间升序，源空值保持 `null`。API 不返回 `MA15/MA120`，不在请求链计算源表没有的指标，不用 daily 量额 fallback 或倍率换算。

10 指数至少 300 根的当前生产快照覆盖审计已在 M0 完成；实施必须保持审计报告冻结的源选择和通用 MA 历史判断。禁止硬编码 `000510.SH`、`2025-09-30` 或任何固定 warm-up 起止日。

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
  debugInfo: IndexDetailDebugInfoDto | null;
}
```

查询链：

1. 解析 page-init 同口径的 `asOfTradeDate`，作为 `contributionTradeDate`。
2. 查询指数该日 `pre_close`。
3. 查询 `MAX(index_weight.trade_date) <= contributionTradeDate`。
4. 以内连接 Security 取该批次完整 A 股子集，按 `weight DESC, con_code ASC` 排序，不截断；B 股不返回、不进入 coverage。
5. 集合查询同日 `equity_daily_bar.pct_chg` 与 `equity_suspend_d`，禁止 N+1。日线值优先；无日线且确认停牌时使用 0%，否则保留 null。
6. 后端按已冻结公式计算贡献点；不归一化、不缩放。确认停牌的 0% 是有明确事实依据的业务值，不是对未知缺失补 0。

当前生产审计证据：10 个指数 raw/serving 最新批次均为 `2026-07-31`，serving 共 5274 行，无 null weight、无重复成分；批次权重和约 `99.984%~100.006%`。这说明不得对源值强制归一化，也说明当前日期基线可以使用。

### 6.4 既有 `GET /api/v1/quote/detail/trend-channel`

本页不新增 `/index-detail/trend-channel`，不参数化 `QuoteTrendChannelQuery`，不开发十指数 service/DTO/cache 适配层。

消费规则：

1. 仅当 `tsCode=000001.SH`、`period=day` 且 `supportsTrendChannel=true` 时请求既有接口；其余 9 个指数不展示入口、不请求接口。
2. 继续使用既有 `sse-daily-trend-channel-v1` 响应；后端 25/90 公式、严格突破状态机、缓存与错误契约全部不变。
3. 前端按 `tradeDate` 与 kline 对齐；缺日不向前填充。
4. 每个交易日都绘制短期/长期上轨、下轨与同日竖向连接，不能抽样省略；不绘制中轴或辅助分区。
5. 页面逐交易日比较收盘与各自下轨：短期 `close < shortLower` 为绿、否则为红；长期 `close < longLower` 为蓝、否则为粉。交易日 `t` 的竖线和从 `t` 连到 `t+1` 的两段轨线使用 `t` 日颜色，到 `t+1` 重新判定。不得用趋势 `state` 选择颜色。
6. 右侧技术页签展示短期上轨、短期下轨、长期上轨、长期下轨四项；接口失败仅使上证指数趋势模块局部 ERROR/PARTIAL。

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
6. M5-A 前端使用隔离的开发态 Mock indicator provider，输入真实 Silver bars，显示“模拟指标”；后端不返回 Mock，真实 indicator endpoint 缺文件时仍返回 `IM_SOURCE_NOT_READY`。
7. Mock 不是异常 fallback：provider 在 M5-A 明确选用 Mock，不先调用真实 Gold；M5-B 验收后删除 Mock 并一次性切换真实 provider。

## 7. 前端交互与状态机

### 7.1 首次加载

```text
route tsCode
  -> page-init
  -> kline
  -> if supportsTrendChannel: existing Quote trend-channel
  -> build view model
  -> render Basic tab (default)
```

权重接口在首次点击“权重股”时加载完整批次；成功后按 `tsCode + asOfTradeDate` 缓存。技术页签仅在上证指数复用已加载趋势数据；其余指数显示不支持。所有指数都不请求不存在的“技术结论 API”。

### 7.2 周期切换

1. 初始 `day`。
2. 生产：分时、周/月、所有分钟按钮都带 disabled/unsupported 状态；点击不改变 active period。
3. 本地：只解锁 `minuteFrequencies` 中存在的分钟按钮。
4. 从分钟切回日线直接使用日线缓存。
5. 权重页签始终显示日频贡献，不随分钟切换刷新。

### 7.3 右侧页签

1. 默认 `basic`。
2. `weights` 独立 loading/ready/partial/empty/error。
3. `technical` 仅在上证指数趋势可用时展示四个客观轨道值；其余指数显示不支持；技术结论和九转位置展示 `--`。
4. tab 切换只改本地 UI state，不改路由、不触发交易动作。
5. `weights` 表头固定；滚动视窗高度等于 10 行，使用虚拟化列表渲染完整 `rows`，不得把“只渲染可视行”误写为“只请求前 10 行”。
6. tab 切换后保留权重数据与滚动位置；重新进入同一 `tsCode + contributionTradeDate + weightTradeDate` 不重复请求。

### 7.4 交易计划边界

1. `+自选/+提醒/+交易计划` 延续股票详情当前占位行为：用户主动点击后显示“暂未开通”。
2. 技术结论、趋势通道、九转、页签切换、周期切换均不得调用这些 action handler。
3. 本轮不新增用户状态表、写 API 或交易流程。

### 7.5 五个状态的页面结构合同

所有页面级状态都保留 `TopMarketBar -> Breadcrumb -> Toolbar -> MainContent` 四段骨架。TopMarketBar 继续展示全局主要指数 ticker，它不是当前详情请求的旧数据，不参与清空；MainContent 内的指数专属数据必须按状态处理。

| 状态 | 根节点 | MainContent 结构 | 文案与动作 | 数据保留规则 |
|---|---|---|---|---|
| LOADING | `498:516` | 1193.195px 图表骨架 + 376.797px 右栏骨架 | “正在加载指数行情”；上证指数可显示“正在读取日线、技术指标与趋势通道”，其余指数不得声称正在读取不支持的趋势通道 | 清空上一标的 page-init/kline/weights/trend ViewModel，只保留全局 ticker |
| EMPTY | `499:579` | 左侧空态图表面板 + 右侧 Basic 信息栏实例 | “暂无指数日线数据”；“重新加载 / 查看最近交易日” | 保留指数身份、工具栏、Tab；主价格、涨跌和 15 个指标值为 `--` |
| ERROR | `501:761` | 单个 `1580×1038` 全宽系统错误面板 | “指数详情加载失败 / 行情服务暂时不可用，请稍后重试。 / ERROR · 请求未完成”；“重新加载 / 返回指数首页” | 不显示旧详情数据；重新加载执行完整 page-init -> kline -> capability trend 链 |
| PARTIAL | `502:1625` | Loaded 图表和右栏不变，右栏增加局部告警 | “部分数据缺失”；说明实际缺失字段 | 保留所有可用数据；仅真实 null/缺失项为 `--`，图层缺失绘制断点或隐藏对应层 |
| FORBIDDEN | `504:1009` | 单个 `1580×1038` 全宽权限面板 | “暂无访问权限 / 403 · FORBIDDEN”；“返回指数首页” | 不发起后续 kline/weights/trend 请求，不转换为 EMPTY，不自动重试 |

布局规则：

1. Loading、Empty、Partial 保持 Loaded 的左右栏尺寸；Error、Forbidden 使用全宽主面板，但外层四段骨架尺寸不变。
2. 页面骨架、状态内容、按钮组、右栏卡片和列表使用 Auto Layout/CSS Grid/Flex；图表绘图区内部保留坐标定位。
3. PARTIAL 提示内部采用流式布局；其相对右栏的位置可作为状态覆盖层实现，但不得用多组补偿坐标重排原右栏实例。
4. ERROR 使用 `--cs-color-danger-system`，PARTIAL 使用 `--cs-color-warning`，FORBIDDEN 使用 `--cs-color-info`；不得使用 `--cs-color-market-up/down` 表达系统状态。
5. 404 没有独立完整 Figma 画板，复用 ERROR 的全宽页面壳并替换为“指数不存在 / 返回指数首页”；DELAYED 没有独立完整像素稿，保留 Loaded 数据并显示实际观测日期。
6. EMPTY 的“重新加载”保留当前 URL 参数并重跑完整加载链；“查看最近交易日”移除隐藏的 `tradeDate` 查询参数后 replace 到同一指数路由，让 `MarketPageContextQuery` 重新解析最新已完成交易日。若默认查询仍为空，继续停留 EMPTY，不回填 mock 或任意旧日期。

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
2. 指数详情 M2 完成时的 stock 历史基线为 90 根；当前 shared 已按[详情页 K 线缩放标杆需求](../../system/detail-chart-zoom-benchmark-requirement-v1.md)升级为 1600px 默认 120 根和 45～180 根缩放。crosshair 同步和 tooltip 定位继续保持。
3. 共享重构单独提交/里程碑验证后，再接指数趋势 overlay，避免把复用重构与业务故障混在一起定位。

### 8.3 M2 实施结果

1. 通用生命周期已收敛到 `wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.tsx`，pane、types、series、formatters 与 CSS 分文件承载。
2. `StockChartWorkspace.tsx` 已成为股票领域 adapter，只负责股票 candle 映射、MA/BOLL 选择、中文文案、单位、tooltip 与底部指标 action。
3. shared series 对缺失 OHLC 过滤 candle；line 缺失点写为 whitespace 断点；histogram 缺失点省略，任何缺失值都不转换为 0。
4. shared engine 预留可选 `ISeriesPrimitive<Time>[]`，但 M2 未实现指数 adapter、趋势 geometry 或趋势请求；这些仍属于 M3。
5. 1600×1200 浏览器前后量测完全一致：图表根容器 `1193.1953125×1038`，四面板高度 `464.078125 / 179.3046875 / 179.3046875 / 179.3046875`，底部指标栏 34px；MA/BOLL、crosshair 与 tooltip 浏览器交互通过。

### 8.4 共享收敛与缩放实施结果

2026-08-12 已按[共享图表与 K 线缩放技术实施方案](../../system/detail-chart-zoom-implementation-design-v1.md)和[配套 LLD](../../system/detail-chart-zoom-low-level-design-v1.md)完成实施：

1. `b38ac20e` 将股票分钟四窗格迁入 `DetailChartWorkspace`，迁移阶段保持 90 根与现有视觉并独立验证无漂移。
2. `61a5adea` 让股票日线、股票分钟、指数日线、指数分钟统一启用 45～180 根、每次 15 根、1600px 默认 120 根和 75～150 根自适应默认。
3. 四类 adapter 使用 `stock|index + tsCode + day|m{freq}` 的稳定 `dataKey`；切标的/周期重置，切 MA/BOLL/趋势不重置。
4. 缩放只改变四 pane 共享 logical range，纵轴按可见真实数据自动适配；不修改指数日线/分钟 API、趋势 primitive 或页面状态，也不发请求或重建 chart。

## 9. 状态、异常与权限

以下异常码已登记到 [wealth 异常码注册表](../../system/exception-code-registry.md)，实现不得另造同义码：

| code | 场景 | 页面行为 |
|---|---|---|
| `ID_REQUEST_INVALID` | 非法代码/日期/limit | 400，显示请求错误 |
| `ID_NOT_FOUND` | 不属于 10 指数或基础信息不存在 | 404 页面 |
| `ID_SOURCE_EMPTY` | 日线主源无数据 | 页面 EMPTY |
| `ID_SOURCE_DELAYED` | observed 早于完成交易日 | DELAYED，显示日期 |
| `ID_FACTOR_PARTIAL` | page-init 同日 factor 量额缺失，或 Kline 因子缺行/缺列 | 基本行情量额 `--`、主图 PARTIAL，缺线不补 0 |
| `ID_BASIC_DAILY_PARTIAL` | 同日 dailyBasic 缺行/缺字段 | 对应指标 `--`，页面 PARTIAL |
| `ID_BASIC_BREADTH_PARTIAL` | A 股成分无同日行情且无停牌依据 | 三计数保留并提示 coverage；B 股/确认停牌不触发 |
| `ID_WEIGHT_EMPTY` | 无可用权重批次 | 权重页签 EMPTY |
| `ID_WEIGHT_CONTRIBUTION_PARTIAL` | A 股成分既无日线也无停牌依据，或指数昨收缺失 | 行显示 `--`，页签 PARTIAL |
| `ID_QUERY_FAILED` | 其它查询失败 | 对应模块 ERROR |
| `IM_SOURCE_NOT_READY` | 本地分钟文件未覆盖 | 分钟模块 DELAYED |
| `IM_SOURCE_CONTRACT_INVALID` | 本地 Parquet 合同错误 | 分钟模块 ERROR |
| `IM_QUERY_FAILED` | DuckDB/文件查询失败 | 分钟模块 ERROR |

鉴权统一使用 `require_quote_access`。未登录沿用 `AuthProvider` 登录跳转；已登录但无权限显示 FORBIDDEN，不将 403 伪装为空数据。

前端恢复动作固定如下：

| 失败范围 | 可见结果 | 恢复动作 |
|---|---|---|
| page-init 404 / 非法指数 | 页面未找到，停止后续请求 | 返回市场总览 |
| page-init/query fatal error | 保留 TopMarketBar 与页面错误壳 | 整页重试 page-init -> kline；上证指数再按 capability 重试 trend |
| 401 | 清理失效会话 | 跳登录并携带 redirect |
| 403 | 保留页面外壳，主内容使用 Figma `504:1009` 的整页 FORBIDDEN 面板 | 不自动重试，不转换为 EMPTY；返回指数首页 |
| 日线 EMPTY | 使用 Figma `499:579`：保留指数身份、工具栏和三 tab 壳，右栏指数专属值为 `--` | 重新加载或查看最近交易日 |
| weights loading/error/empty | 只替换权重 tab，主图保持 | 局部重试 weights |
| weights PARTIAL | 保留完整 A 股行；真实缺失贡献显示 `--`；确认停牌显示 0 | 不把未知缺失补 0；允许局部重试 |
| basic daily fields missing | 仅对应字段显示 `--`；其余基本行情保留 | 不回填、不补 0 |
| constituent breadth PARTIAL | 保留已分类 A 股的上涨/平盘/下跌；确认停牌计平盘，真实缺失不计入三类 | 显示部分缺失状态；允许整页重试 |
| trend/指标 error | 隐藏对应层或断点，基本行情保持 | 局部重试 trend/kline |
| local minute empty/delayed/error | 只替换分钟图，日线缓存保持 | 局部重试或切回日线 |

## 10. 测试与验证计划

### 10.1 后端真实 API

新增 `tests/web/test_wealth_index_detail_api.py`，至少覆盖：

1. 10 个配置 code 均可 page-init，非名单 code 为 404。
2. `MarketPageContextQuery` 默认日期、显式日期和 source delayed 三类锚点覆盖。
3. kline 只接受 day、不接受 adjustment、升序、null 不变 0。
4. page-init 与 kline 核心字段对照真实表。
5. 权重解析到 2026-07-31，完整 A 股子集、B 股排除、排序、覆盖计数、不截断和不归一化正确。
6. 贡献点正常、负值、零涨跌、确认停牌、真实 A 股行情缺失、指数昨收缺失均按公式断言。
7. 权重和实际指数涨跌点不相等时不缩放。
8. page-init 的 15 个基本行情字段映射正确；日度指标缺失保持 null；成分涨跌只取 A 股，日线优先、确认停牌进入 flat、B 股不进入 coverage，真实 missing 不进入 flat。
9. 上证指数调用既有趋势 API 并逐交易日按相对下轨规则着色；每个交易日都有竖线，颜色切换点连续；其余 9 个指数断言无入口、无请求；旧 SSE Quote API 契约回归不变。
10. 权限、空、延迟、查询错误、部分缺失。
11. prod profile 分钟路由 404；local profile 真实临时 Lake 文件可查。

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
9. 基本行情严格展示 15 项；任一缺失值显示 `--`，不存在“成交状态”和“较昨日”。
10. 技术 tab 或趋势失败不清空日线/基本行情。
11. 股票详情共享图表回归。
12. 趋势通道每天具备上下轨竖线、相邻交易日上下轨连线；颜色逐交易日判定且切换点连续；短期红/绿与长期粉/蓝四种组合都有组件测试。
13. Loading 不残留上一标的详情值；Empty 恰好将主价格、涨跌与 15 个基本行情值显示为 `--`；Error/FORBIDDEN 使用全宽主面板并保留外层页面壳。
14. Partial fixture 验证金额、TTM 市盈率、平盘数为 `--` 且其它 Loaded 数据不变；另以不同缺失字段证明提示文案由响应生成、没有写死 Figma 示例。
15. 系统 ERROR/PARTIAL/FORBIDDEN 分别使用 danger-system/warning/info token，断言未使用行情涨跌色。

### 10.3 浏览器与像素验收

1. 本地真实 API 启动后验证 `/wealth/market/index/000001.SH`。
2. 逐一点击 10 卡，至少抽检 000001/399001/399006/000300/899050。
3. 1600×1200 对比 Basic `417:2`、Weights `423:2`、Technical `423:910` 与三种 Info Rail variant。
4. 分别对比 Loading `498:516`、Empty `499:579`、Error `501:761`、Partial `502:1625`、Forbidden `504:1009`；验证文案、动作、颜色、数据保留和状态恢复。
5. 像素误差和设计漂移记录到后续独立 verification ledger，不在业务代码中硬编码补偿。
6. 普通 UI 元素相对基线偏差不超过 2px；图表、趋势通道、坐标轴、Tooltip 和十字线不得因状态组件发生位移。

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
| M0 方案冻结（已完成） | 三件套/LLD、异常码、正式 DTO、生产 factor 审计、Loaded/Components/五态 Figma 节点台账 | 审计与合同已落档 |
| M1 数据与契约（已完成） | 按冻结 DTO 实现 page-init/kline/weights；趋势仍由前端后续直接接既有 SSE API | 真实 API、旧契约无漂移与实现后性能测试通过 |
| M2 图表共享（已完成） | 提取 shared 图表引擎，股票行为零回归 | stock tests + 浏览器对比通过 |
| M3 页面 Loaded（已完成） | 路由、10 卡导航、日线、三 tab、贡献点、趋势 overlay | Figma Loaded 验收、真实 API 浏览器验收、全量回归通过 |
| M4 异常状态（已完成） | 按五个 Figma 根画板实现 loading/empty/error/partial/forbidden，并补 404/delayed/module 状态变体 | 状态测试、真实浏览器逐状态截图与尺寸验收通过 |
| M5-A 本地分钟（已完成） | reader、条件路由、真实 Silver K 线、可见开发态 Mock 指标 | Silver 数据/性能、local/prod 与视觉门禁通过 |
| M5-B 准备（已完成） | 70 checks 注册、跨边界合同门禁、七频率异常 fixture、只读正式验收入口 | Definitions 发现 14 个资产/70 个 checks；合同一致；缺正式 Gold 时明确 `SOURCE_NOT_READY` |
| M5-B 最终切换 | 真实 indicators、删除 Mock | Gold 物理覆盖/全量对齐/性能与 10000 根门禁通过 |
| M6 发布验收 | prod 日线能力、分钟路由不存在、全回归 | 构建/测试/生产 smoke 通过 |

M5-B 准备批次已于 2026-08-12 验收：42 项分钟相关测试、14 项依赖边界测试及静态检查通过；正式只读预检确认 Silver 七频率各 4,276 个分区、Gold technical 七频率 0 个分区，因此只记录 `SOURCE_NOT_READY / IM_SOURCE_NOT_READY`，不形成 Gold 性能通过结论。

技术结论 API 与九转 API 不属于 M0-M6，分别立项后再扩展 DTO 与 UI。

## 12. 风险与缓解

| 风险 | 触发条件 | 缓解 |
|---|---|---|
| 趋势接口只支持 SSE | 误把通道入口暴露给其余 9 个指数 | capability 仅对 `000001.SH` 开启；其余指数不展示、不请求，不开发适配层 |
| factor 实际历史仍少于 2000 根 | 当前 9 个指数 630 根、A500 455 根，仍不足以证明真实 2000 行 API payload | M1 已验收 2000 上限请求的当前实返 455~630 行；真实 2000 行保留为发布前门禁 |
| 深市两源量额分叉 | 399001/399006 自 2026-07-06 起 factor 与 daily 不同 | 外部核对确认 factor 准确；指数详情统一取 factor，禁止 daily fallback 或倍率换算 |
| 历史回填会改变 MA 可计算边界 | 把当前 A500 空值前缀固化为 code/date 规则 | 按实际有效历史根数动态判断；2024 同步完成后复审，不改代码特例 |
| Figma 与数据语义冲突 | 示例贡献点不可复算、全市场成交说明不成立 | 以冻结公式和真实源语义覆盖示例文案 |
| 图表复用导致股票回归 | 直接改 751 行组件 | 先共享重构、单独验证、再加指数 overlay |
| 分钟 Lake 尚未正式 ready | 页面先暴露 capability | capability + Lake 门禁，prod 永不挂路由 |
| 贡献缺失被当 0 | adapter 使用 valueOrZero | index adapter null-safe，API coverage 明示 |
| 全量 A 股权重导致 DOM/响应膨胀 | 直接渲染完整数组或查询逐行补名 | 单次完整 A 股子集 API + 集合查询；前端虚拟化；P95 与 1 MiB payload 门禁 |
| B 股被误报缺失 | 直接以源权重总数减日线匹配数 | 先按 Security 事实字段限定 A 股；B 股不进入 coverage，不用代码前缀判断 |
| 停牌被误报缺失或无依据补 0 | 仅 LEFT JOIN 日线，或把全部 null 当平盘 | 只在同日 `suspend_type=S` 命中时使用 0%/FLAT；无停牌依据继续 PARTIAL |
| 技术内容诱发交易含义 | 用通道自动生成建议/动作 | 客观事实与用户 action 严格分离 |
| 状态稿被当成静态样例 | 把 Partial 三个缺失字段或上证 Loading 文案写死 | 状态组件由 capability/缺失字段驱动，Figma 只冻结结构、文案模板和视觉语义 |
| Figma 旧说明误导字段实现 | 继续读取 `425:190` 的振幅/较昨日 | 以 Basic 组件 `414:446`、详细口径 `425:219` 和三件套 15 项清单为唯一合同 |

## 13. 已确认的技术口径

1. 趋势通道仅支持上证指数，直接消费既有 SSE API，不开发十指数适配层。
2. 通道按短期25、长期90各自上下轨绘制；每个交易日都有竖线，颜色按当日收盘点相对各自下轨逐日决定并允许在交易日边界切换；右侧展示四个轨道值，不展示中轴。
3. 权重 API 返回完整 A 股子集；B 股不返回、不占 coverage；前端固定 10 行视窗、表头固定、内部滚动并虚拟化，不提供任意 limit。
4. 基本行情固定 15 项；日度指标无值显示 `--`，删除“成交状态”和“较昨日”。
5. 上涨/平盘/下跌只按最新有效源批次中的 A 股聚合；日线优先，确认停牌计入平盘，只有无日线且无停牌依据的 A 股进入 missing/PARTIAL。
6. 基本行情与 Kline 的成交量、成交额统一取 `index_factor_pro`；`index_daily_serving` 只保留日期/价格锚点职责，不提供量额 fallback。

## 14. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.17 | 2026-08-12 | M3 对账：共享收敛与缩放已由 `b38ac20e`/`61a5adea` 完成，四类图表统一 dataKey、45～180/15 与自适应 120；后端合同不变 | Codex |
| v1.16 | 2026-08-12 | 冻结后续图表演进：先将股票分钟迁入 shared，再统一启用 45～180 根缩放与 1600px 默认 120 根；后端合同不变 | Codex |
| v1.15 | 2026-08-12 | 完成 M5-B 准备：确认 70 checks 已注册，增加 Orchestrator/Web Reader 合同防漂移、七频率错误 fixture 与正式 Gold 只读验收入口；正式文件验收和前端切换继续待办 | Codex |
| v1.14 | 2026-08-12 | 完成 A 股成分范围与停牌解析实现；回填 10 指数最终服务链 P95、上证最终 SQL 计划、2184 行 payload 及真实页面 READY 验收 | Codex |
| v1.13 | 2026-08-12 | 统一 page-init/weights 的 A 股成分范围；B 股排除在 rows/coverage/missing 外；确认停牌按 0%/FLAT 参与 breadth 与贡献，真实 A 股缺失才触发 PARTIAL；DTO 提升为 1.2.0 | Codex |
| v1.12 | 2026-08-11 | 完成 M5-A：新增正式 Silver Reader、独立双接口与错误映射、统一 capability 路由、本地七频率 controller/cache/竞态隔离、Mock v0 provider、共享分钟图表与局部状态；正式只读 P95、10000 根、浏览器和回归通过 | Codex |
| v1.11 | 2026-08-11 | 完成 M4：controller 落地页面/模块状态优先级、请求中止防串标、Empty/404/403/500 映射、Delayed/Partial 动态提示与趋势/权重局部重试；五个 Figma 状态和 404/Delayed 通过 1600×1200 浏览器验收，100 项 Wealth 与 82 项后端相关回归通过 | Codex |
| v1.10 | 2026-08-11 | 完成 M3 Loaded：独立路由与 10 卡导航、真实 API controller、null-safe adapter、三 Tab、15 项基本行情、完整权重虚拟滚动、SSE-only 趋势 primitive；通过 1600×1200 三画板、2224 行末行、9 code 零趋势请求和全量回归验收 | Codex |
| v1.9 | 2026-08-11 | 完成 M2 shared chart 与 stock adapter；落 null-safe series、四面板同步、90 根窗口、crosshair/tooltip、可选 primitive 接口及独立回归测试，并通过全量 Wealth 测试、构建和浏览器尺寸对账 | Codex |
| v1.8 | 2026-08-11 | 完成 M1 后端三接口与严格错误映射；补 factor/daily 源负例、动态 MA 回填测试、10 code/权重/旧契约回归及生产只读 P95；同步实际目录拆分 | Codex |
| v1.7 | 2026-08-11 | 外部核对确认 factor 量额准确；基本行情与 Kline 的量额统一改取 factor，删除 Kline daily JOIN 和 fallback；DTO 提升为 1.1.0 | Codex |
| v1.6 | 2026-08-11 | 修正 MA null 口径：删除 A500/固定日期 warm-up 特例；按实际有效历史根数判断，并将 DTO 合同提升为 1.0.1 | Codex |
| v1.5 | 2026-08-11 | 完成 M0：链接正式 DTO/审计并登记异常码；记录深市量额分叉、当时 A500 MA250 空值与真实 2000 行性能待验项；量额最终来源已由 v1.7 修订 | Codex |
| v1.4 | 2026-08-11 | 按最新 Figma 节点树补齐五态完整页面合同、状态组件拆分、系统颜色与逐画板测试；登记 1600×1200 骨架尺寸和旧概述文案冲突 | Codex |
| v1.3 | 2026-08-11 | 冻结逐交易日趋势判色和每日竖线；基本行情改为 15 项并删除成交状态/较昨日；补成分涨跌聚合 DTO、缺失规则与生产复核证据 | Codex |
| v1.2 | 2026-08-11 | 趋势通道收敛为仅上证指数直接调用既有 API；删除十指数适配层与中轴设计；补双通道绘制/颜色规则、成交状态和生产字段审计 | Codex |
| v1.1 | 2026-08-11 | 权重改为完整批次与 10 行虚拟滚动；补齐页面/模块异常恢复矩阵和当前股票详情实现差距 | Codex |
| v1 | 2026-08-10 | 基于现有代码、CodeGraph、Figma 与生产权重审计形成首版实施草案 | Codex |
