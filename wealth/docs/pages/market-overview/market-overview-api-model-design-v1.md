# 市场总览：数据对象模型与 API 设计 v1（先模型，后接口）

## 1. 目标与范围

本设计只服务财势乾坤 `market overview` 页面。

本版目标：

1. 先定义数据对象模型（字段、来源表、映射规则）。
2. 再定义 API 契约（请求、响应、调试态规则）。
3. 消除歧义字段（如裸 `code`），保留可扩展对象边界。

本版不做：

1. 不写后端实现代码。
2. 不写缓存与任务调度细节。
3. 不改 UI 交互细节。

---

## 2. 数据源清单（仅本页当前使用）

| 数据域 | 表名 | 作用 |
|---|---|---|
| 交易日 | `core_serving.trade_calendar` | 当前交易日、上一交易日、开市标记 |
| 股票日线 | `core_serving.equity_daily_bar` | 涨幅/跌幅/成交额榜主排序入口 |
| 股票日线指标 | `core_serving.equity_daily_basic` | 换手率、量比 |
| 市场资金流（大盘） | `core_serving.market_moneyflow_dc` | 主力/超大/大/中/小净流入及占比 |
| 热榜 | `core_serving.dc_hot` | 人气榜、飙升榜 |
| 涨跌停 | `core_serving.equity_limit_list` | 涨停/跌停/炸板统计 |
| 连板 | `core_serving.limit_step` | 首板到高板分层（`nums`） |
| 板块总览 | `core_serving.dc_index` | 板块涨跌、上涨下跌家数、龙头信息 |
| 板块行情 | `core_serving.dc_daily` | 板块日线补充（涨跌幅/成交额等） |
| 板块资金流 | `core_serving.board_moneyflow_dc` | 行业/概念/地域资金流 |
| 名称映射（股票） | `core_serving.security_serving` | `ts_code -> name`（个股名称兜底） |
| 名称映射（指数） | `core_serving.index_basic` | `ts_code -> name`（指数名称兜底） |

---

## 3. 对象模型（单一事实源）

## 3.1 `TradingDay`（交易日对象）

```ts
interface TradingDay {
  tradeDate: string;
  prevTradeDate: string;
  market: "CN_A";
  isTradingDay: boolean;
  sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
  timezone: "Asia/Shanghai";
}
```

| 字段 | 来源表 | 来源列 | 映射/转换 |
|---|---|---|---|
| `tradeDate` | `trade_calendar` | `trade_date` | date -> `YYYY-MM-DD` |
| `prevTradeDate` | `trade_calendar` | `pretrade_date` | date -> `YYYY-MM-DD` |
| `market` | 常量 | - | 固定 `CN_A` |
| `isTradingDay` | `trade_calendar` | `is_open` | boolean 原样 |
| `sessionStatus` | 服务端派生 | - | 按当前时钟 + 交易时段规则派生 |
| `timezone` | 常量 | - | 固定 `Asia/Shanghai` |

---

## 3.2 `PageStatus`（页面级长期状态）

```ts
interface PageStatus {
  status: "READY" | "DELAYED" | "PARTIAL" | "EMPTY" | "ERROR";
  displayText: string;
  asOfTime?: string;
}
```

说明：

1. 页面级状态是长期产品态。
2. 不等于各模块的细粒度状态；模块状态只在 debug 输出。

| 字段 | 来源 | 映射/转换 |
|---|---|---|
| `status` | 聚合器规则 | 由模块状态聚合（如 `READY/PARTIAL/DELAYED`） |
| `displayText` | 聚合器规则 | 如“已收盘”“数据延迟 90s” |
| `asOfTime` | 聚合器规则 | 常用 `serverTime` 或核心模块观测时间 |

---

## 3.3 `SubjectRef`（主体标识对象，替代裸 code）

```ts
type SubjectType = "stock" | "index" | "sector";

interface SubjectRef {
  subjectType: SubjectType;
  subjectCode: string;
  subjectName: string;
  stockCode?: string;
  indexCode?: string;
  sectorCode?: string;
}
```

说明：

1. 所有榜单、天梯、板块项都必须使用 `SubjectRef`。
2. 不再以裸 `code` 作为主体标识。

---

## 3.4 `MajorIndicesPanel`

```ts
interface MajorIndicesPanel {
  tradeDate: string;
  rows: MajorIndexRow[];
}

interface MajorIndexRow {
  subject: SubjectRef; // subjectType=index
  point: number;
  change: number;
  changePct: number;
  amount?: number;
  direction: "UP" | "DOWN" | "FLAT" | "UNKNOWN";
}
```

| 字段 | 来源表 | 来源列 | 映射/转换 |
|---|---|---|---|
| `tradeDate` | `trade_calendar` | `trade_date` | 取请求日（或最近交易日） |
| `subject.subjectCode` | 指数行情主表（实现阶段确认） | `ts_code` | 原样 |
| `subject.subjectName` | `index_basic` | `name` | `ts_code` 关联，缺失可用配置兜底 |
| `point` | 指数行情主表 | `close` | 数值原样 |
| `change` | 指数行情主表 | `change_amount`/`change` | 统一为涨跌点 |
| `changePct` | 指数行情主表 | `pct_chg` | 数值原样（%值） |
| `amount` | 指数行情主表 | `amount` | 数值原样 |
| `direction` | 派生 | - | `changePct >0 => UP, <0 => DOWN, =0 => FLAT` |

> 注：指数行情当前仓库有 `index_daily_serving/index_daily_bar` 两个候选表。实现前以“线上最新、覆盖完整、性能更优”的单表口径拍板后固定。

---

## 3.5 `MarketSummary` + `MoneyFlowPanel`

```ts
interface MarketSummary {
  cards: MarketSummaryCard[];
  textCard: { title: string; content: string };
}

interface MarketSummaryCard {
  key: string;
  label: string;
  value: number | string;
  unit?: string;
  direction?: "UP" | "DOWN" | "FLAT" | "UNKNOWN";
}

interface MoneyFlowPanel {
  tradeDate: string;
  netAmount: number;
  netAmountRate: number;
  byOrderSize: {
    elg: { amount: number; rate: number };
    lg: { amount: number; rate: number };
    md: { amount: number; rate: number };
    sm: { amount: number; rate: number };
  };
}
```

| 字段 | 来源表 | 来源列 | 映射/转换 |
|---|---|---|---|
| `tradeDate` | `market_moneyflow_dc` | `trade_date` | 与请求日对齐 |
| `netAmount` | `market_moneyflow_dc` | `net_amount` | 原样（元） |
| `netAmountRate` | `market_moneyflow_dc` | `net_amount_rate` | 原样（%） |
| `byOrderSize.elg.amount` | `market_moneyflow_dc` | `buy_elg_amount` | 原样 |
| `byOrderSize.elg.rate` | `market_moneyflow_dc` | `buy_elg_amount_rate` | 原样 |
| `byOrderSize.lg.amount` | `market_moneyflow_dc` | `buy_lg_amount` | 原样 |
| `byOrderSize.lg.rate` | `market_moneyflow_dc` | `buy_lg_amount_rate` | 原样 |
| `byOrderSize.md.amount` | `market_moneyflow_dc` | `buy_md_amount` | 原样 |
| `byOrderSize.md.rate` | `market_moneyflow_dc` | `buy_md_amount_rate` | 原样 |
| `byOrderSize.sm.amount` | `market_moneyflow_dc` | `buy_sm_amount` | 原样 |
| `byOrderSize.sm.rate` | `market_moneyflow_dc` | `buy_sm_amount_rate` | 原样 |

---

## 3.6 `LeaderboardsPanel`（你已拍板的 7 个标签）

> 榜单作为标杆需求的前后端贯通规则（规则归属、股票池归属、模块异常语义）已单独收敛到：
> `wealth/docs/pages/market-overview/leaderboard-benchmark-requirement-v1.md`。
> 本节保留字段模型与来源映射，不再重复治理规则细节。

```ts
interface LeaderboardsPanel {
  tradeDate: string;
  tabs: LeaderboardTab[];
}

interface LeaderboardTab {
  tabKey: "gainers" | "losers" | "amount" | "turnover" | "volumeRatio" | "popularity" | "surge";
  tabLabel: string;
  rows: LeaderboardRow[];
}

interface LeaderboardRow {
  rank: number;
  subject: SubjectRef; // stock/index/sector 均可扩展
  latestPrice?: number;
  changePct?: number;
  turnoverRate?: number;
  volumeRatio?: number;
  volume?: number;
  amount?: number;
}
```

### 3.6.1 涨幅/跌幅/成交额/换手/量比（主链路）

| 字段 | 来源表 | 来源列 | 映射/转换 |
|---|---|---|---|
| 行集合入口 | `equity_daily_bar` | `trade_date` | 以请求交易日筛选 |
| `subject.subjectCode` | `equity_daily_bar` | `ts_code` | 原样 |
| `subject.subjectName` | `security_serving` | `name` | `ts_code` 关联 |
| `latestPrice` | `equity_daily_bar` | `close` | 原样 |
| `changePct` | `equity_daily_bar` | `pct_chg` | 原样 |
| `amount` | `equity_daily_bar` | `amount` | 原样 |
| `volume` | `equity_daily_bar` | `vol` | 原样 |
| `turnoverRate` | `equity_daily_basic` | `turnover_rate` | `(ts_code, trade_date)` 左连接 |
| `volumeRatio` | `equity_daily_basic` | `volume_ratio` | `(ts_code, trade_date)` 左连接 |

排序规则：

1. `gainers`: `pct_chg desc`
2. `losers`: `pct_chg asc`
3. `amount`: `amount desc`
4. `turnover`: `turnover_rate desc`（基于 bar 主链路 + basic 指标）
5. `volumeRatio`: `volume_ratio desc`（同上）

### 3.6.2 人气榜/飙升榜（dc_hot）

| 字段 | 来源表 | 来源列 | 映射/转换 |
|---|---|---|---|
| 行集合入口 | `dc_hot` | `trade_date` | 请求日筛选 |
| 标签类型 | `dc_hot` | `query_hot_type` | `人气榜 => popularity`, `飙升榜 => surge` |
| `subject.subjectCode` | `dc_hot` | `ts_code` | 原样 |
| `subject.subjectName` | `dc_hot` | `ts_name` | 可回退 `security_serving.name` |
| `rank` | `dc_hot` | `rank` | 原样 |
| `changePct` | `dc_hot` | `pct_change` | 原样 |
| `latestPrice` | `dc_hot` | `current_price` | 原样 |

---

## 3.7 `LimitUpPanel`（涨跌停统计）

```ts
interface LimitUpPanel {
  tradeDate: string;
  limitUpCount: number;
  limitDownCount: number;
  brokenLimitCount: number;
  sealingRate?: number;
}
```

| 字段 | 来源表 | 来源列 | 映射/转换 |
|---|---|---|---|
| `limitUpCount` | `equity_limit_list` | `limit_type` | `count(*) where limit_type='U'` |
| `limitDownCount` | `equity_limit_list` | `limit_type` | `count(*) where limit_type='D'` |
| `brokenLimitCount` | `equity_limit_list` | `open_times` | 常见口径：`limit_type='U' and open_times>0` |
| `sealingRate` | 派生 | - | `limitUpCount / (limitUpCount + brokenLimitCount)` |

---

## 3.8 `StreakLadderPanel`（连板天梯）

```ts
interface StreakLadderPanel {
  tradeDate: string;
  buckets: StreakBucket[];
}

interface StreakBucket {
  ladderBucket: "first" | "second" | "third" | "fourth" | "fifthPlus";
  ladderLabel: "首板" | "二板" | "三板" | "四板" | "五板及以上";
  stockCount: number;
  stocks: LadderStockRow[];
}

interface LadderStockRow {
  subject: SubjectRef;  // stock
  boardCount: number;   // 1/2/3/4/5/6...
  latestPrice?: number;
  changePct?: number;
  openTimes?: number;
}
```

| 字段 | 来源表 | 来源列 | 映射/转换 |
|---|---|---|---|
| `subject.subjectCode` | `limit_step` | `ts_code` | 原样 |
| `subject.subjectName` | `limit_step` | `name` | 原样 |
| `boardCount` | `limit_step` | `nums` | `nums::int`，非数字丢弃并记录诊断 |
| `ladderBucket` | 派生 | - | `1/2/3/4` 各自；`>=5 => fifthPlus` |
| `latestPrice/changePct` | `equity_daily_bar` | `close/pct_chg` | `(ts_code, trade_date)` 左连接 |
| `openTimes` | `equity_limit_list` | `open_times` | `(ts_code, trade_date, limit_type='U')` |

---

## 3.9 `SectorOverviewPanel`（统一 DC 口径）

```ts
interface SectorOverviewPanel {
  tradeDate: string;
  columns: SectorColumn[];
  heatMapItems: SectorHeatItem[];
}

interface SectorColumn {
  columnKey: string;
  title: string;
  tone: "up" | "down";
  rows: SectorRankRow[];
}

interface SectorRankRow {
  rank: number;
  subject: SubjectRef; // sector
  metricText: string;
  metricValue: number;
}
```

| 数据列 | 来源表 | 来源列 | 映射/转换 |
|---|---|---|---|
| 板块代码/名称 | `dc_index` | `ts_code`, `name` | 作为 `subjectCode/subjectName` |
| 板块涨跌幅 | `dc_index`/`dc_daily` | `pct_change` | 具体实现选一张主表固定 |
| 上涨下跌家数 | `dc_index` | `up_num`, `down_num` | 原样 |
| 板块成交额 | `dc_daily` | `amount` | 原样 |
| 板块资金流 | `board_moneyflow_dc` | `net_amount` 等 | `trade_date + content_type` 筛选 |
| 内容分类 | `board_moneyflow_dc` | `content_type` | 仅 `行业/概念/地域` |

---

## 3.10 `DebugModuleStatus`（仅 debug mode）

```ts
interface DebugModuleStatus {
  enabled: true;
  modules: ModuleStatusItem[];
}

interface ModuleStatusItem {
  moduleKey: string;
  status: "READY" | "DELAYED" | "PARTIAL" | "EMPTY" | "ERROR";
  source: string;
  observedTradeDate?: string;
  expectedTradeDate?: string;
  lagDays?: number;
  note?: string;
}
```

| 字段 | 来源 | 规则 |
|---|---|---|
| `moduleKey` | 固定枚举 | `marketSummary/majorIndices/leaderboards/limitUp/streakLadder/sectorOverview/moneyFlow` |
| `source` | 固定映射 | 如 `dc_hot`、`equity_daily_bar`、`limit_step` |
| `observedTradeDate` | 对应源表 | `max(trade_date)`（按模块口径） |
| `expectedTradeDate` | 请求参数/交易日解析 | 当前应展示交易日 |
| `status` | 派生 | `observed==expected => READY`；落后 => `DELAYED`；无数据=>`EMPTY`；部分缺失=>`PARTIAL` |

---

## 4. API 设计（在对象模型之后）

## 4.1 命名空间

统一使用：

`/api/v1/wealth/market/*`

---

## 4.2 首屏聚合接口

`GET /api/v1/wealth/market/overview`

请求参数：

```ts
interface MarketOverviewRequest {
  market?: "CN_A";
  tradeDate?: string; // YYYY-MM-DD
  dataMode?: "latest" | "eod" | "replay";
  leaderboardLimit?: number; // default 10
  sectorTopLimit?: number;   // default 5
  heatMapRows?: number;      // default 5
  heatMapCols?: number;      // default 4
  debug?: 0 | 1;             // default 0
}
```

响应包裹：

```ts
interface WealthApiResponse<T> {
  code: number;
  message: string;
  data: T;
  traceId: string;
  serverTime: string;
}
```

主数据对象：

```ts
interface MarketOverviewData {
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
  debugInfo?: DebugModuleStatus; // debug=1 时返回
}
```

---

## 4.3 可拆分子接口（可选）

以下是后续按性能需要再拆分，不是首期必做：

1. `GET /api/v1/wealth/market/leaderboards`
2. `GET /api/v1/wealth/market/limit-up/summary`
3. `GET /api/v1/wealth/market/limit-up/streak-ladder`
4. `GET /api/v1/wealth/market/sector-overview`

---

## 5. 兼容与扩展规则

1. 不允许再新增歧义裸字段 `code` 作为主体标识。
2. 对象优先，不把对象字段拍扁到根层。
3. 新增能力优先“新增可选字段/子对象”，不改旧字段语义。
4. 模块级状态仅存在于 `debugInfo`；正式态只看 `pageStatus`。
5. 旧 `/api/market/*` 路径不再作为实现口径。
