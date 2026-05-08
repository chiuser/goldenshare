# 市场总览｜榜单 M2 编码前门禁 v1

## 1. 目的

1. 本门禁对应模块：`leaderboards`。
2. 本门禁对应需求文档：  
   [leaderboard-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/leaderboard-benchmark-requirement-v1.md)。
3. 本门禁对应实施方案：  
   [leaderboard-implementation-design-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/leaderboard-implementation-design-v1.md)。

目标：在写任何业务代码前，把“输入、输出、查询、状态、异常、性能”全部锁定，避免编码期口径漂移。  
适用范围：仅 `leaderboards` 模块（本期），不扩散到其他模块。

---

## 2. 编码前硬门禁（全部通过才能开工）

1. 榜单定义（7 个 `boardKey`）冻结完成。
2. 请求参数与默认值冻结完成。
3. 响应对象字段冻结完成（含 debug 结构）。
4. 7 榜单样例响应通过评审。
5. 每榜 SQL 草案通过评审。
6. 状态归并样例（READY/PARTIAL/DELAYED/EMPTY/ERROR）通过评审。
7. `dc_hot` 严格/回退模式样例通过评审。
8. 异常码全部来自异常码注册表，无新增游离异常码。
9. 性能预算与降级策略明确。

---

## 3. 请求与响应冻结（M2 基线）

## 3.1 请求参数冻结

```ts
interface LeaderboardsRequest {
  market?: "CN_A";    // default: CN_A
  tradeDate?: string; // YYYY-MM-DD
  limit?: number;     // default: 10, range: [1, 50]
  boardKeys?: (
    "gainers" | "losers" | "amount" | "turnover" | "volumeRatio" | "popularity" | "surge"
  )[];
  debug?: 0 | 1;      // default: 0
}
```

参数校验：

1. `market` 非 `CN_A` -> `400001`
2. `tradeDate` 非法格式 -> `400001`
3. `limit` 越界 -> `400001`
4. `boardKeys` 含非法 key -> `400001`

## 3.2 响应对象冻结（摘要）

```ts
interface LeaderboardsResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  definitions: LeaderboardDefinition[];
  boards: LeaderboardBoard[];
  debugInfo?: {
    modules: ModuleStatusItem[];
    exceptions: ModuleExceptionItem[];
  };
}
```

---

## 4. 7 榜单样例响应（每榜最小样本）

> 说明：以下是门禁样本，用于锁定字段与语义，不代表真实值。

## 4.1 `gainers`

```json
{
  "boardKey": "gainers",
  "boardLabel": "涨幅榜",
  "status": "READY",
  "expectedTradeDate": "2026-05-08",
  "observedTradeDate": "2026-05-08",
  "rows": [
    {
      "rank": 1,
      "subject": { "subjectType": "stock", "subjectCode": "300750.SZ", "subjectName": "宁德时代" },
      "metrics": {
        "latestPrice": 212.36,
        "changePct": 9.87,
        "turnoverRate": 4.31,
        "volumeRatio": 1.85,
        "volume": 2241365,
        "amount": 4748392012.0
      }
    }
  ]
}
```

## 4.2 `losers`

```json
{
  "boardKey": "losers",
  "boardLabel": "跌幅榜",
  "status": "READY",
  "rows": [
    {
      "rank": 1,
      "subject": { "subjectType": "stock", "subjectCode": "000001.SZ", "subjectName": "平安银行" },
      "metrics": { "latestPrice": 10.32, "changePct": -9.12, "turnoverRate": 5.03, "volumeRatio": 2.14, "volume": 5312390, "amount": 552103993.0 }
    }
  ]
}
```

## 4.3 `amount`

```json
{
  "boardKey": "amount",
  "boardLabel": "成交额榜",
  "status": "READY",
  "rows": [
    {
      "rank": 1,
      "subject": { "subjectType": "stock", "subjectCode": "600519.SH", "subjectName": "贵州茅台" },
      "metrics": { "latestPrice": 1688.8, "changePct": 0.32, "turnoverRate": 1.73, "volumeRatio": 0.96, "volume": 812345, "amount": 13722100000.0 }
    }
  ]
}
```

## 4.4 `turnover`

```json
{
  "boardKey": "turnover",
  "boardLabel": "换手榜",
  "status": "READY",
  "rows": [
    {
      "rank": 1,
      "subject": { "subjectType": "stock", "subjectCode": "002594.SZ", "subjectName": "比亚迪" },
      "metrics": { "latestPrice": 251.19, "changePct": 2.01, "turnoverRate": 19.32, "volumeRatio": 3.22, "volume": 9921341, "amount": 2499012330.0 }
    }
  ]
}
```

## 4.5 `volumeRatio`

```json
{
  "boardKey": "volumeRatio",
  "boardLabel": "量比榜",
  "status": "READY",
  "rows": [
    {
      "rank": 1,
      "subject": { "subjectType": "stock", "subjectCode": "300059.SZ", "subjectName": "东方财富" },
      "metrics": { "latestPrice": 13.18, "changePct": 1.45, "turnoverRate": 8.11, "volumeRatio": 6.83, "volume": 12031566, "amount": 1536220000.0 }
    }
  ]
}
```

## 4.6 `popularity`

```json
{
  "boardKey": "popularity",
  "boardLabel": "人气榜",
  "status": "DELAYED",
  "expectedTradeDate": "2026-05-08",
  "observedTradeDate": "2026-05-07",
  "rows": [
    {
      "rank": 1,
      "subject": { "subjectType": "stock", "subjectCode": "601127.SH", "subjectName": "赛力斯" },
      "metrics": { "latestPrice": 88.33, "changePct": 4.21 }
    }
  ]
}
```

## 4.7 `surge`

```json
{
  "boardKey": "surge",
  "boardLabel": "飙升榜",
  "status": "READY",
  "rows": [
    {
      "rank": 1,
      "subject": { "subjectType": "stock", "subjectCode": "002415.SZ", "subjectName": "海康威视" },
      "metrics": { "latestPrice": 29.61, "changePct": 6.88 }
    }
  ]
}
```

---

## 5. 查询草案（每榜一条，可直接转实现）

> 约定：以下 SQL 为草案，真实实现可按 SQLAlchemy/CTE 组织，但字段语义必须一致。

## 5.1 `gainers`

```sql
WITH stock_pool AS (
  SELECT DISTINCT b.ts_code
  FROM core_serving.equity_daily_bar b
  JOIN core_serving.security_serving s ON s.ts_code = b.ts_code
  WHERE b.trade_date = :trade_date
    AND s.security_type = 'stock'
)
SELECT
  b.ts_code,
  s.name,
  b.close AS latest_price,
  b.pct_chg AS change_pct,
  db.turnover_rate,
  db.volume_ratio,
  b.vol AS volume,
  b.amount
FROM core_serving.equity_daily_bar b
JOIN stock_pool p ON p.ts_code = b.ts_code
LEFT JOIN core_serving.security_serving s ON s.ts_code = b.ts_code
LEFT JOIN core_serving.equity_daily_basic db
  ON db.ts_code = b.ts_code AND db.trade_date = b.trade_date
WHERE b.trade_date = :trade_date
ORDER BY b.pct_chg DESC
LIMIT :limit;
```

## 5.2 `losers`

`ORDER BY b.pct_chg ASC`，其余同 `gainers`。

## 5.3 `amount`

`ORDER BY b.amount DESC`，其余同 `gainers`。

## 5.4 `turnover`

`ORDER BY db.turnover_rate DESC NULLS LAST`，其余同 `gainers`。

## 5.5 `volumeRatio`

`ORDER BY db.volume_ratio DESC NULLS LAST`，其余同 `gainers`。

## 5.6 `popularity`

```sql
SELECT
  h.ts_code,
  COALESCE(h.ts_name, s.name, '') AS subject_name,
  h.rank,
  h.current_price AS latest_price,
  h.pct_change AS change_pct,
  h.trade_date
FROM core_serving.dc_hot h
LEFT JOIN core_serving.security_serving s ON s.ts_code = h.ts_code
WHERE h.trade_date = :resolved_trade_date
  AND h.query_hot_type = '人气榜'
ORDER BY h.rank ASC
LIMIT :limit;
```

## 5.7 `surge`

`WHERE h.query_hot_type='飙升榜'`，其余同 `popularity`。

---

## 6. `dc_hot` 严格/回退样例门禁

| 模式 | 目标日有数据 | 行为 | board.status |
|---|---|---|---|
| strict=true | 是 | 取目标日 | READY |
| strict=true | 否 | 返回空 rows | DELAYED |
| strict=false | 是 | 取目标日 | READY |
| strict=false | 否 | 回退最近有数据日 | DELAYED |

附加要求：

1. 回退时必须返回 `observedTradeDate`。
2. strict 空榜单场景必须产出 `LB_SOURCE_EMPTY` 或 `LB_SOURCE_DELAYED`。

---

## 7. 状态归并样例门禁

| 各 board 状态分布 | pageStatus.status |
|---|---|
| 全 READY | READY |
| READY + DELAYED 混合 | PARTIAL |
| READY + EMPTY 混合 | PARTIAL |
| READY + ERROR 混合 | PARTIAL |
| 全 DELAYED | DELAYED |
| 全 EMPTY | EMPTY |
| 全 ERROR | ERROR |

---

## 8. 异常码覆盖矩阵（本期）

| code | 最少覆盖用例 |
|---|---|
| `LB_SOURCE_EMPTY` | strict=true 且目标日无 `dc_hot` 数据 |
| `LB_SOURCE_DELAYED` | strict=false 回退到历史日 |
| `LB_JOIN_METRIC_MISSING` | 某条 `daily_basic` 缺失 |
| `LB_SUBJECT_NAME_MISSING` | `dc_hot.ts_name` 和 `security.name` 都缺失 |
| `LB_QUERY_FAILED` | 人工注入查询异常 |

> 异常码定义与语义以  
> [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md) 为准。

---

## 9. 性能门禁（编码前确认）

1. 单次请求默认 `limit=10`，7 榜同时返回。
2. 目标 P95 `< 400ms`（同机房 DB，非冷启动）。
3. 返回体 `< 120KB`。
4. 若超过预算，优先做查询优化；Redis 缓存放到二期，不在本门禁强制启用。

---

## 10. M2 开工签字清单（评审记录）

### 10.1 后端负责人确认

1. [ ] 7 榜定义冻结
2. [ ] SQL 草案冻结
3. [ ] strict/fallback 行为冻结
4. [ ] 状态归并规则冻结
5. [ ] 异常码全部来自注册表

### 10.2 前端负责人确认

1. [ ] definitions 驱动 tab
2. [ ] columnSchema 驱动列
3. [ ] debug 模式开关与展示策略明确
4. [ ] 名称缺失降级策略明确

### 10.3 产品/架构确认

1. [ ] 本期只交付榜单，不扩散其他模块
2. [ ] 页面级状态与模块级 debug 状态边界清晰
3. [ ] 后续模块沿用同一模式，另开分期文档

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 建立榜单 M2 编码前门禁清单 | Codex |
