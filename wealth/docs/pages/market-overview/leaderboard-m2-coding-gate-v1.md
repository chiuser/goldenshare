# 市场总览｜榜单 M2 编码前门禁 v1

> 用途：在编码前冻结榜单模块的参数、响应、查询、状态、异常与性能门禁。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [榜单标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/leaderboard-benchmark-requirement-v1.md)
2. [榜单技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/leaderboard-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`leaderboards`
2. 本门禁对应需求文档：`leaderboard-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`leaderboard-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 榜单定义（7 个 `boardKey`）冻结完成
2. [ ] 请求参数与默认值冻结完成
3. [ ] 响应对象字段冻结完成（含 debug 结构）
4. [ ] 7 榜单样例响应通过评审
5. [ ] 每榜 SQL 草案通过评审
6. [ ] 状态归并样例（READY/PARTIAL/DELAYED/EMPTY/ERROR）通过评审
7. [ ] `dc_hot` 严格/回退模式样例通过评审
8. [ ] 异常码全部来自异常码注册表，无游离异常码
9. [ ] 性能预算与降级策略明确
10. [ ] 前端真实源加载态门禁冻结（loading/ready/error）
11. [ ] 5 秒超时进入 error 且不展示 mock 回填的行为门禁冻结
12. [ ] 本轮仅 leaderboards 切换到 real、其余模块 source 不变
13. [ ] 配置生效语义冻结（本模块读取策略配置中心，规则由 `leaderboard.cn_a.v1.json` 提供）
14. [ ] 通用清单映射矩阵冻结并评审通过
15. [ ] 模块例外白名单冻结并评审通过
16. [ ] 签字完成

---

## 3. 请求与响应冻结（M2 基线）

### 3.1 请求参数冻结

```ts
interface LeaderboardsRequest {
  market?: "CN_A";    // default: CN_A
  tradeDate?: string; // YYYY-MM-DD
  limit?: number;     // default: payload.defaultLimit, range: [1, 50]
  debug?: 0 | 1;      // default: 0
}
```

参数校验：

1. `market` 非 `CN_A` -> `400001`
2. `tradeDate` 非法格式 -> `400001`
3. `limit` 越界 -> `400001`
4. `debug` 非 `0/1` -> `400001`
5. 若请求携带 `boardKeys`，直接拒绝（`400001`），防止用户侧覆盖运营配置。

### 3.2 响应对象冻结（摘要）

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

### 4.1 `gainers`

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

### 4.2 `losers`

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

### 4.3 `amount`

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

### 4.4 `turnover`

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

### 4.5 `volumeRatio`

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

### 4.6 `popularity`

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

### 4.7 `surge`

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

## 5. 配置门禁（策略配置中心）

配置文件：`src/biz/services/wealth/config/definitions/leaderboard.cn_a.v1.json`

必检项（不通过不得开工）：

1. `moduleKey=leaderboards`、`market=CN_A` 与 registry 注册一致。
2. `version` 必须符合语义版本格式 `x.y.z`，测试不得把具体版本号写死。
3. `updatedAt` 必须带时区偏移；`updatedBy` 必填。
4. `payload.boardKeys` 必须与 7 榜单 key 冻结集合一致：
   - `gainers/losers/amount/turnover/volumeRatio/popularity/surge`
5. `payload.defaultLimit` 在允许范围内（建议默认 10）。
6. `payload.strictHotDate` 默认 `true`，且仅可通过配置中心改。

---

## 6. 查询草案（每榜一条，可直接转实现）

> 约定：以下 SQL 为草案，真实实现可按 SQLAlchemy/CTE 组织，但字段语义必须一致。

### 6.1 `gainers`

```sql
WITH stock_pool AS (
  SELECT DISTINCT b.ts_code
  FROM core_serving.equity_daily_bar b
  JOIN core_serving.security_serving s ON s.ts_code = b.ts_code
  WHERE b.trade_date = :trade_date
    AND s.security_type = 'stock'
    AND s.list_status = 'L'
    AND s.list_date <= :trade_date
    AND (s.delist_date IS NULL OR s.delist_date > :trade_date)
    AND s.name NOT ILIKE 'ST%'
    AND s.name NOT ILIKE '*ST%'
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

### 6.2 `losers`

`ORDER BY b.pct_chg ASC`，其余同 `gainers`。

### 6.3 `amount`

`ORDER BY b.amount DESC`，其余同 `gainers`。

### 6.4 `turnover`

`ORDER BY db.turnover_rate DESC NULLS LAST`，其余同 `gainers`。

### 6.5 `volumeRatio`

`ORDER BY db.volume_ratio DESC NULLS LAST`，其余同 `gainers`。

### 6.6 `popularity`

```sql
SELECT
  h.ts_code,
  COALESCE(h.ts_name, s.name, '') AS subject_name,
  h.rank,
  h.rank_time,
  h.current_price AS latest_price,
  h.pct_change AS change_pct,
  h.trade_date
FROM core_serving.dc_hot h
LEFT JOIN core_serving.security_serving s ON s.ts_code = h.ts_code
WHERE h.trade_date = :resolved_trade_date
  AND h.query_hot_type = '人气榜'
  AND h.query_market = 'A股'
  AND h.data_type = 'stock'
  AND NOT (h.rank IS NULL AND h.rank_time IS NULL)
ORDER BY
  CASE WHEN h.rank IS NULL THEN 1 ELSE 0 END,
  h.rank ASC NULLS LAST,
  CASE WHEN h.rank_time IS NULL THEN 1 ELSE 0 END,
  h.rank_time DESC NULLS LAST,
  h.ts_code ASC
LIMIT :limit;
```

### 6.7 `surge`

`WHERE h.query_hot_type='飙升榜'`，其余过滤/剔除/排序规则同 `popularity`。

---

## 7. `dc_hot` 严格/回退样例门禁

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

## 8. 状态归并样例门禁

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

## 9. 异常码覆盖矩阵（本期）

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

## 10. 性能门禁（编码前确认）

1. 单次请求默认 `limit=10`，7 榜同时返回。
2. 目标 P95 `< 400ms`（同机房 DB，非冷启动）。
3. 返回体 `< 120KB`。
4. 若超过预算，优先做查询优化；Redis 缓存放到二期，不在本门禁强制启用。

---

## 11. 测试门禁

1. 单元测试：
   - 定义注册表一致性；
   - 状态归并规则；
   - 异常组装规则；
   - strict/fallback 分支。
2. 集成测试：
   - 正常/延迟/空/错误四态；
   - 7 榜单输出完整；
   - `dc_hot` 非 A 股样本不入榜；
   - `dc_hot` rank 并列按 rank_time 新到旧；
   - `dc_hot` rank 为空按 rank_time 新到旧；
   - `dc_hot` rank/rank_time 同时无效样本被剔除。
3. 冒烟测试：
   - 真实源请求 pending 时显示 loading（不展示 mock 榜单）；
   - 真实源请求超过 5 秒显示 error（不回填 mock 榜单）；
   - `debug=1` 返回模块级状态与异常，`debug=0` 不返回 `debugInfo`。
4. 渐进替换约束验证：
   - 仅 `leaderboards` source 发生变化；
   - 非目标模块 source 与行为不变。

---

## 12. 通用清单映射矩阵

| 通用清单条目 | 适用性 | 本模块落地位置 | 当前状态 |
|---|---|---|---|
| 2.1 三件套先行 | 适用 | 本文 + benchmark + implementation | 已落地 |
| 2.2 后端事实归一 | 适用 | `definitions/boards` 后端产出，前端仅渲染 | 已落地 |
| 2.3 模块状态机清晰 | 适用 | `loading/ready/error` + `pageStatus` 归并 | 已落地 |
| 2.4 显示语义绑定 | 适用 | `metrics` 与 `subject` 字段语义冻结 | 已落地 |
| 2.5 测试覆盖行为过程 | 适用 | 第 10 节测试门禁 | 已落地 |
| 2.6 文档与实现同轮同步 | 适用 | 三件套同轮修订 | 已落地 |
| 2.7 模块级渐进替换纪律 | 适用 | 仅 leaderboards 切 real | 已落地 |
| 2.8 契约先行与消费者对齐 | 适用 | 第 3 节请求/响应冻结 | 已落地 |
| 2.9 图表坐标与说明文案约束 | 不适用 | 本模块无图表渲染，只有榜单列表 | 已登记例外 |
| 2.10 统计计算与数据传输边界 | 适用 | SQL 排序与 limit 截断，不做前端二次统计 | 已落地 |
| 2.11 配置生效语义 | 适用 | 读取策略配置中心 `leaderboard.cn_a.v1.json`，重启生效，严格校验 envelope+payload | 已落地 |
| 2.12 通用清单映射矩阵 | 适用 | 本节 | 已落地 |
| 2.13 模块例外白名单与语义断言 | 适用 | 第 12 节 | 已落地 |
| 2.14 图表参数优先级 | 不适用 | 本模块无图表组件参数（无 yMin/yMax/ticks） | 已登记例外 |
| 2.15 双图并排坐标对齐 | 不适用 | 本模块无双图布局 | 已登记例外 |
| 2.16 指标卡片单行约束 | 不适用 | 本模块无“指标卡片副文案单行”需求 | 已登记例外 |

---

## 13. 模块例外白名单（leaderboards）

| 例外规则 | 生效范围 | 业务语义依据 | 处理方式 |
|---|---|---|---|
| 2.9 图表坐标约束不适用 | leaderboards 全模块 | 榜单模块无图表，仅列表与数值列 | 标记 N/A，不补图表门禁 |
| 2.14 显式坐标参数门禁不适用 | leaderboards 全模块 | 无图表引擎参数（`yMin/yMax/yTickValues`） | 标记 N/A |
| 2.15 双图对齐门禁不适用 | leaderboards 全模块 | 页面无双图并排区域 | 标记 N/A |
| 2.16 单行卡片门禁不适用 | leaderboards 全模块 | 模块不包含“指标卡片副文案” | 标记 N/A |

---

## 14. M2 开工签字清单（评审记录）

### 14.1 后端负责人确认

1. [ ] 7 榜定义冻结
2. [ ] SQL 草案冻结
3. [ ] strict/fallback 行为冻结
4. [ ] 状态归并规则冻结
5. [ ] 异常码全部来自注册表

### 14.2 前端负责人确认

1. [ ] definitions 驱动 tab
2. [ ] columnSchema 驱动列
3. [ ] debug 模式开关与展示策略明确
4. [ ] 名称缺失降级策略明确

### 14.3 产品/架构确认

1. [ ] 本期只交付榜单，不扩散其他模块
2. [ ] 页面级状态与模块级 debug 状态边界清晰
3. [ ] 后续模块沿用同一模式，另开分期文档

---

## 15. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 建立榜单 M2 编码前门禁清单 | Codex |
| v1.1 | 2026-05-10 | 对齐最新通用清单：补齐映射矩阵、模块例外白名单、loading/error 行为门禁与配置边界 | Codex |
| v1.2 | 2026-05-10 | 对齐拍板口径：切策略配置中心、收口 boardKeys 非对外、补配置版本门禁与股票池过滤规则 | Codex |
| v1.3 | 2026-05-10 | 同步热榜门禁：`dc_hot` 增加 A股+stock 过滤、rank/rank_time 排序、异常值剔除与对应测试项 | Codex |
