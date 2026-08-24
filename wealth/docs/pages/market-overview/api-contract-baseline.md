# 市场总览 API 契约基线（当前生效）

> 新闻模块当前合同（2026-08-24）：左列 `/news/briefs` 展示 `core_serving_light.news` 全部可读快讯，右列 `/news/communications` 展示 `core_serving_light.major_news` 新闻通讯；详情必须使用 `contentSource + newsId`。旧 `/news/stocks` 和无来源详情路由已删除。

## 来源

本基线来自当前工程化文档，而不是 `reference/api/**` 旧草案：

```text
wealth/docs/pages/market-overview/market-overview-api-model-design-v1.md
wealth/docs/pages/market-overview/*-benchmark-requirement-v1.md
wealth/docs/pages/market-overview/*-implementation-design-v1.md
wealth/docs/pages/market-overview/*-m2-coding-gate-v1.md
wealth/docs/pages/market-overview/sector-overview-*-v2.md  # 板块速览当前 V2 后端契约
wealth/docs/system/module-delivery-checklist-v1.md
wealth/docs/system/engineering-architecture.md
```

`wealth/docs/reference/api/market-overview-api-v0.4/v0.5.md` 与
`wealth/docs/reference/api/p0-data-dictionary-v0.4/v0.5.md`
只作为历史输入材料，不再作为当前 API 实现契约。

字段级“来源表/来源列/转换规则”以
`wealth/docs/pages/market-overview/market-overview-api-model-design-v1.md`
为唯一落地基线。

榜单模块的前后端贯通规则（规则归属、股票池归属、异常语义）以
`wealth/docs/pages/market-overview/leaderboard-benchmark-requirement-v1.md`
为专用基线。

今日市场客观总结模块（卡片数量 5/6 配置化、文字卡后端配置驱动）以
`wealth/docs/pages/market-overview/market-summary-benchmark-requirement-v1.md`
为专用基线。

## 当前阶段

市场总览已进入“模块级真实 API 渐进替换”阶段。

真实后端 API 当前统一路径：

```http
GET /api/v1/wealth/market/{module}
```

整页聚合接口如需恢复，统一路径为：

```http
GET /api/v1/wealth/market/overview
```

但整页聚合接口必须单独设计，不允许复用早期 `/api/market/home-overview`。

已采用模块化接口的方向：

```http
GET /api/v1/wealth/market/summary
GET /api/v1/wealth/market/major-indices
GET /api/v1/wealth/market/breadth
GET /api/v1/wealth/market/style
GET /api/v1/wealth/market/turnover
GET /api/v1/wealth/market/leaderboards
GET /api/v1/wealth/market/limit-up/summary
GET /api/v1/wealth/market/streak-ladder
GET /api/v1/wealth/market/money-flow
GET /api/v1/wealth/market/sector-overview
GET /api/v1/wealth/market/news/briefs
GET /api/v1/wealth/market/news/communications
GET /api/v1/wealth/market/news/items/{contentSource}/{newsId}
```

模块接口只返回模块对象；整页聚合后续再由 overview 聚合接口统一编排。

## 旧口径替换表（禁止直接沿用）

| 历史口径 | 历史含义 | 当前方向 |
|---|---|---|
| `GET /api/market/home-overview` | 早期首屏大聚合接口 | 不作为当前实现依据；若恢复整页聚合，使用 `GET /api/v1/wealth/market/overview` 并单独设计 |
| `GET /api/index/summary` | 早期指数/顶部指数局部接口 | 主要指数模块统一走 `GET /api/v1/wealth/market/major-indices` |
| `GET /api/market/breadth` | 早期涨跌分布接口 | 统一走 `GET /api/v1/wealth/market/breadth` |
| `GET /api/market/style` | 早期市场风格接口 | 统一走 `GET /api/v1/wealth/market/style` |
| `GET /api/market/turnover` | 早期成交额总览接口 | 统一走 `GET /api/v1/wealth/market/turnover` |
| `GET /api/moneyflow/market` | 早期大盘资金流接口 | 统一走 `GET /api/v1/wealth/market/money-flow` |
| `marketNewsFlash` / `marketOverviewNewsBlocks` | 早期顶部统一快讯条或整页新闻聚合字段 | 不放入 PageHeader；当前合同为 briefs/communications |
| `GET /api/v1/wealth/market/news/stocks` | 旧首页右列个股新闻 | 已删除；首页右列固定使用 `/news/communications` |
| `GET /api/v1/wealth/market/news/items/{newsId}` | 旧无来源详情路由 | 已删除；详情固定使用 `contentSource + newsId` |
| `includeHistory` | 早期由前端决定是否返回历史序列 | 不再作为通用参数；历史窗口由模块契约定义 |
| 整页 mock 根对象 `data.moneyFlow/data.indices/...` | 早期从整页对象直接喂组件 | 已接真实 API 的模块必须通过模块 provider + view-model adapter |

## 请求参数

```ts
interface MarketOverviewParams {
  market?: "CN_A";
  tradeDate?: string; // YYYY-MM-DD
  dataMode?: "latest" | "eod" | "replay";
  leaderboardLimit?: number; // default: 10
  sectorTopLimit?: number; // default: 5
  heatMapRows?: number; // default: 5
  heatMapCols?: number; // default: 4
  debug?: 0 | 1; // default: 0; 1=返回模块级调试状态
}
```

其中 `sectorTopLimit/heatMapRows/heatMapCols` 只解释历史聚合草案；当前板块速览 V2 模块接口不接受这些参数，返回数量由 V2 契约固定。

## 响应包裹

后续真实 API 建议：

```ts
interface WealthApiResponse<T> {
  code: number;
  message: string;
  data: T;
  traceId: string;
  serverTime: string;
}
```

未接真实 API 的模块 mock adapter 也必须按该结构模拟；已接真实 API 的模块不得继续使用整页 mock 或旧 reference response 替代。

## 聚合数据结构（对象化，不拍扁）

市场总览聚合数据至少包含：

```ts
interface MarketOverview {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  topMarketBar: TopMarketBarData;
  breadcrumb: BreadcrumbItem[];
  quickEntries: QuickEntry[];
  marketSummary: MarketSummary;
  majorIndices: MajorIndicesPanel;
  moneyFlow: MoneyFlowPanel;
  marketNews: MarketNewsPanelGroup;
  leaderboards: LeaderboardsPanel;
  limitUp: LimitUpPanel;
  streakLadder: StreakLadderPanel;
  sectorOverview: SectorOverviewPanel;
  debugInfo?: DebugModuleStatus; // 仅 debug=1 返回
}
```

## 字段命名规则

1. TypeScript 与 API 字段统一 lowerCamelCase。
2. 不新增旧字段别名。
3. 领域主体禁止使用歧义 `code`；使用 `subjectType + subjectCode + subjectName`。
4. 对象保持对象化边界，不把 `tradingDay` 等对象拍扁。
5. 异常码统一引用 `wealth/docs/system/exception-code-registry.md`，不得在模块文档和代码中重复发明。

## 方向枚举

```ts
type MarketDirection = "UP" | "DOWN" | "FLAT" | "UNKNOWN";
```

映射规则：

- `UP`：红色
- `DOWN`：绿色
- `FLAT`：中性灰白
- `UNKNOWN`：中性弱提示

## 禁止字段

市场总览首页、mock 数据和 ViewModel 都不得加入：

```text
marketTemperatureScore
marketSentimentScore
capitalScore
riskIndexScore
buySuggestion
sellSuggestion
positionSuggestion
tomorrowPrediction
subjectiveMarketConclusion
```

## 真实 API 与已拍板口径

以下内容已确定口径，后续按该口径落地：

1. 榜单速览：
   - 涨幅/跌幅/成交额/换手/量比由 `equity_daily_bar` 主链路，换手与量比关联 `equity_daily_basic`。
   - 人气榜/飙升榜来自 `dc_hot`。
2. 连板天梯：独立模块接口 `GET /api/v1/wealth/market/streak-ladder`，基于 `equity_limit_list / limit_list_d`，分组固定“首板/二板/三板/四板/五板及以上”，并全量返回 `boardCount`。
3. 板块速览前后端均已在本地切换为 V2 判别式契约，旧 `columns + heatMapItems` 及前端旧 adapter/fixture 已删除；部署时仍必须作为同一发布单元上线，禁止只部署其中一侧。行业层级来自 `core_serving.wealth_sector_hierarchy`，行业/概念/地域盘后行情、资金与成员来自 `dc_daily + dc_index + board_moneyflow_dc + dc_member`，成员盘后行情来自 `equity_daily_bar`，证券资格与停牌解释来自 `security_serving + equity_suspend_d`，概念热度来自 `core_serving.wealth_sector_heat_daily`。V2 提供 `INDUSTRY/CONCEPT/REGION` 三个独立视图，使用 `heatDelta1d` 和有效 A 股成分池，不引入实时行情、分钟热度或 Redis 事实源。
4. 模块级 delayed 仅用于 debug mode；正式产品默认展示页面级状态。
5. 新闻模块已使用 `/briefs` 与 `/communications`，item 可点击打开共享阅读器。`/briefs` 展示全部可读 `news` 快讯，不按 `channels` 过滤；`/communications` 展示 `major_news` 新闻通讯。详情身份固定为 `contentSource + newsId`，两张表不跨源去重或 fallback；`major_news` 正文只按 HTML > TEXT 展示，`url` 仅作为 `originalUrl` 溯源事实，不写入 DOM、不导航。两列仍不接收 `tradeDate`，继续使用“昨日 00:00 到当前服务器时间”的 `newsWindow`。

## 性能原则

后续真实 API 不允许从 raw 表实时大 join 拼首屏。

真实 API 落地前必须先设计：

- 聚合查询服务
- 预聚合快照
- 缓存策略
- 数据新鲜度口径
