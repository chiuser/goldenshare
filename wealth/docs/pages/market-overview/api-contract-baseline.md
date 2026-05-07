# 市场总览 API 契约基线

## 来源

本基线来自 Drive：

```text
财势乾坤/数据字典与API文档/market-overview-api-v0.4.md
财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4.md
```

## 当前阶段

首期只实现 mock adapter，不接真实后端 API。

真实后端 API 规划路径：

```http
GET /api/v1/wealth/market/overview
```

Drive 原 API 草案中的路径是：

```http
GET /api/market/home-overview
```

本工程采用 `/api/v1/wealth/market/overview` 作为本地规划路径，避免与既有运营后台 API 混淆。

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

## 聚合数据结构

市场总览聚合数据至少包含：

```ts
interface MarketOverview {
  tradingDay: TradingDay;
  dataStatus: MarketDataStatus;
  topMarketBar: TopMarketBarData;
  breadcrumb: BreadcrumbItem[];
  quickEntries: QuickEntry[];
  marketSummary: MarketSummary;
  indices: MajorIndex[];
  breadth: MarketBreadth;
  style: MarketStyle;
  turnover: TurnoverOverview;
  moneyFlow: MarketMoneyFlow;
  leaderboards: MarketLeaderboards;
  limitUp: LimitUpOverview;
  streakLadder: StreakLadder;
  sectorOverview: SectorOverview;
}
```

## 字段命名规则

1. TypeScript 与 API 字段统一 lowerCamelCase。
2. 不新增旧字段别名。
3. 不使用 `price` / `sectorId` 这类待淘汰命名。
4. 推荐使用 `latestPrice` / `sectorCode`。

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

## 真实 API 待后续拍板

以下内容首期不实现真实逻辑，只允许在 mock 中使用明确的静态样例：

1. 榜单来源：`dc_hot` 还是传统涨跌幅/成交额/换手率/量比榜。
2. 板块热力图排序：涨跌幅、成交额、资金流，还是综合排序。
3. 天地板 / 地天板规则。
4. 涨停板块分布优先使用行业、概念还是混合口径。
5. 后端是否返回 `displayText`，还是只返回结构化数值。

## 性能原则

后续真实 API 不允许从 raw 表实时大 join 拼首屏。

真实 API 落地前必须先设计：

- 聚合查询服务
- 预聚合快照
- 缓存策略
- 数据新鲜度口径
