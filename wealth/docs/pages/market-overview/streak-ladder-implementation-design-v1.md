# 市场总览｜连板天梯技术实施方案 v1（implementation-design）

> 用途：把连板天梯 benchmark 需求转成可执行技术方案。  
> 阶段：编码前。  
> 产物性质：实现基线（不在本文写业务代码）。

关联文档：

1. [连板天梯标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-benchmark-requirement-v1.md)
2. [连板天梯 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-m2-coding-gate-v1.md)

---

## 1. 目的与边界

1. 目标：按最新版 UI（v5）落地连板天梯数据链路，确保后端输出与前端展示一一对应。
2. 本文只处理：
   - v5 数据模型
   - 数据来源表与映射
   - 跨日组合算法
   - 状态与异常归并
3. 本文不处理：
   - 页面视觉改动
   - 个股详情页跳转
   - 策略中心接入
4. 模块边界硬约束：
   - 连板天梯实施方案只覆盖连板天梯字段真值表与实现链路；
   - 即使与其它模块共享数据表，也不引入跨模块耦合逻辑。

---

## 2. 现状代码审计（与旧设计不符点）

1. 前端当前展示模型是 `ladderV5`，位于：
   - `/Users/congming/github/goldenshare/wealth/src/features/market-overview/api/marketOverviewTypes.ts`
2. 连板 UI 组件是 v5 分层渲染，位于：
   - `/Users/congming/github/goldenshare/wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx`
3. 旧三件套中的“固定五桶静态结构”与当前组件不一致，已在本版统一到 v5 语义。

---

## 3. 目标数据模型（实现冻结）

## 3.1 根对象 `streakLadderV5`

```ts
interface StreakLadderV5 {
  tradeDate: string;
  prevTradeDate: string;
  highestStreakLevel: number;
  aboveFive: LadderV5Stock[];
  promotions: Record<number, LadderV5PromotionLayer>; // key: 2/3/4/5
  firstBoard: LadderV5Stock[];
}
```

## 3.2 晋级层对象

```ts
interface LadderV5PromotionLayer {
  previousLabel: string;   // 例如：昨日二板
  currentLabel: string;    // 例如：今日三板
  previousStocks: LadderV5Stock[]; // 昨日层全量
  currentStocks: LadderV5Stock[];  // 今日晋级子集
}
```

## 3.3 股票对象

```ts
interface LadderV5Stock {
  stockName: string | null;
  stockCode: string;
  latestPrice: number | null;
  changePct: number | null;
  sectorName: string | null;
  openTimes: number | null;
  currentStreakLevel: number; // 掉队可为 0
  advanced: boolean;
}
```

---

## 4. 数据来源与映射（重点）

> 口径声明：以下映射是“连板天梯模块字段真值表（实现版）”，不扩展到其它模块。

## 4.1 来源表

1. `core_serving.trade_calendar`
2. `core_serving.equity_limit_list`
3. `core_serving.equity_daily_bar`（仅补展示列）

## 4.2 字段映射

| 目标字段 | 主来源表 | 来源列 | 规则 |
|---|---|---|---|
| `tradeDate` | `trade_calendar` | `trade_date` | 请求日或系统期望交易日 |
| `prevTradeDate` | `trade_calendar` | `prev_trade_date` | 与 `tradeDate` 同口径 |
| `stockCode` | `equity_limit_list` | `ts_code` | 必填 |
| `stockName` | `equity_limit_list` | `name` | 可空 |
| `currentStreakLevel` | `equity_limit_list` | `limit_times` | 解析正整数 |
| `openTimes` | `equity_limit_list` | `open_times` | 可空 |
| `latestPrice` | `equity_limit_list` | `close` | 缺失回退 `equity_daily_bar.close` |
| `changePct` | `equity_limit_list` | `pct_chg` | 缺失回退 `equity_daily_bar.pct_chg` |
| `sectorName` | `equity_limit_list` | `industry` | 可空 |

约束：

1. `equity_limit_list` 必须过滤 `limit_type='U'`。
2. `equity_daily_bar` 不能参与板数/晋级判定。
3. 共享来源仅用于说明数据事实，不允许在本模块内耦合其它模块的业务规则。

---

## 5. 组合算法（如何把表数据组合成 v5）

## 5.1 输入上下文

1. `tradeDate`
2. `prevTradeDate`
3. `market=CN_A`

## 5.2 中间集合

1. `todayRows`：当日涨停池（解析后有效板数）
2. `prevRows`：昨日涨停池（解析后有效板数）
3. `todayByCode`：`todayRows` 按 `stockCode` 建索引
4. `prevByLevel[level]`：`prevRows` 按板数分层
5. `todayByLevel[level]`：`todayRows` 按板数分层

## 5.3 生成 `highestStreakLevel`

1. `highestStreakLevel = max(todayRows.currentStreakLevel)`。
2. 若当日无有效数据，走 `EMPTY` 状态链路。

## 5.4 生成 `aboveFive`

1. 过滤 `todayRows` 中 `currentStreakLevel >= 6`。
2. 映射为 `LadderV5Stock[]`，`advanced=true`。

## 5.5 生成晋级层（核心）

对 `level in [2,3,4,5]`，按 `highestStreakLevel` 动态裁剪：

1. `prevCandidates = prevByLevel[level-1]`（昨日该层全量）
2. `todayCandidates = todayByLevel[level]`（今日目标层）
3. `advancedCodes = prevCandidates.codes ∩ todayCandidates.codes`
4. `currentStocks`：
   - 仅 `advancedCodes`；
   - 字段使用当日记录；
   - `advanced=true`。
5. `previousStocks`：
   - 保留 `prevCandidates` 全量；
   - 对每只股票：
     - 若当日存在记录：展示列优先取当日（更接近页面“今日视角”）；
     - 若当日不存在记录：展示列回退昨日值；
   - `advanced = stockCode in advancedCodes`；
   - `currentStreakLevel`：
     - 当日存在记录：取当日板数；
     - 当日无记录：记为 `0`（掉队）。

## 5.6 生成 `firstBoard`

1. 过滤 `todayRows` 中 `currentStreakLevel = 1`。
2. 映射为 `LadderV5Stock[]`，`advanced=true`。

---

## 6. 排序与展示控制

1. `aboveFive` 排序：
   - `currentStreakLevel desc`
   - `changePct desc nulls last`
   - `latestPrice desc nulls last`
   - `stockCode asc`
2. `currentStocks` 排序：
   - `changePct desc nulls last`
   - `openTimes asc nulls last`
   - `stockCode asc`
3. `previousStocks` 排序：
   - `advanced desc`
   - `currentStreakLevel desc`
   - `changePct desc nulls last`
   - `stockCode asc`
4. 每层默认返回最多 12 条；展开逻辑由前端 UI 控制。

---

## 7. 状态与异常

## 7.1 模块状态

1. `READY`：结构完整可展示。
2. `DELAYED`：`observedTradeDate < expectedTradeDate`。
3. `PARTIAL`：存在无效板数行或补列缺失。
4. `EMPTY`：目标日无有效涨停结构数据。
5. `ERROR`：查询或组装异常。

## 7.2 异常码

1. `SL_SOURCE_DELAYED`
2. `SL_SOURCE_EMPTY`
3. `SL_INVALID_BOARD_COUNT`
4. `SL_JOIN_METRIC_MISSING`
5. `SL_QUERY_FAILED`

---

## 8. API 契约（实施口径）

1. 路径：`GET /api/v1/wealth/market/streak-ladder`
2. 参数：
   - `market?: "CN_A"`
   - `tradeDate?: string`
   - `debug?: 0 | 1`
3. 响应：
   - `tradingDay`
   - `pageStatus`
   - `streakLadderV5`
   - `debugInfo?`

---

## 9. 代码落位（计划）

```text
src/biz/
  api/wealth/market/streak_ladder.py
  queries/wealth/market/streak_ladder/
    streak_ladder_state_query.py
    streak_ladder_query.py
    streak_ladder_query_service.py
  schemas/wealth/market/streak_ladder.py
  services/wealth/market/streak_ladder/
    streak_ladder_builder.py
    streak_ladder_status_resolver.py
    streak_ladder_exception_builder.py
```

说明：

1. `query` 负责拉取与基础投影，不写 UI 语义。
2. `service` 负责 v5 组合语义（晋级层/掉队/advanced）。
3. `schema` 冻结响应契约，前端不可自行扩展事实字段。

---

## 10. 验证要点

1. `previousStocks` 必须包含昨日层全量，不得只保留晋级股。
2. `currentStocks` 必须是晋级交集子集。
3. `currentStreakLevel` 对掉队股票为 `0`。
4. `equity_daily_bar` 仅作为展示补列来源，不可影响层级判定。
5. 模块状态与异常码必须可追溯到具体数据缺口。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 按 v5 UI 重写实现方案：统一数据模型、来源映射、跨日组合算法 | Codex |
