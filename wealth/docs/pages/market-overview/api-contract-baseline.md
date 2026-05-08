# 市场总览 API 契约基线（当前生效）

## 来源

本基线来自：

```text
wealth/docs/reference/api/market-overview-api-v0.4.md
wealth/docs/reference/api/p0-data-dictionary-v0.4.md
wealth/docs/pages/market-overview/market-overview-api-model-design-v1.md
wealth/docs/pages/market-overview/leaderboard-benchmark-requirement-v1.md
wealth/docs/pages/market-overview/leaderboard-implementation-design-v1.md

字段级“来源表/来源列/转换规则”以
`wealth/docs/pages/market-overview/market-overview-api-model-design-v1.md`
为唯一落地基线。

榜单模块的前后端贯通规则（规则归属、股票池归属、异常语义）以
`wealth/docs/pages/market-overview/leaderboard-benchmark-requirement-v1.md`
为专用基线。
```

## 当前阶段

首期只实现 mock adapter，不接真实后端 API。

真实后端 API 当前统一路径：

```http
GET /api/v1/wealth/market/overview
```

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

首期 mock adapter 也按该结构模拟。

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

## 真实 API 待后续实现（已拍板口径）

以下内容已确定口径，后续按该口径落地：

1. 榜单速览：
   - 涨幅/跌幅/成交额/换手/量比由 `equity_daily_bar` 主链路，换手与量比关联 `equity_daily_basic`。
   - 人气榜/飙升榜来自 `dc_hot`。
2. 连板天梯：基于 `limit_step`，分组固定“首板/二板/三板/四板/五板及以上”，并全量返回 `boardCount`。
3. 板块速览统一 DC 口径：`dc_index`/`dc_daily` + `board_moneyflow_dc`。
4. 模块级 delayed 仅用于 debug mode；正式产品默认展示页面级状态。

## 性能原则

后续真实 API 不允许从 raw 表实时大 join 拼首屏。

真实 API 落地前必须先设计：

- 聚合查询服务
- 预聚合快照
- 缓存策略
- 数据新鲜度口径
