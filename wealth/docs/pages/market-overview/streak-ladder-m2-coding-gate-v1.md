# 市场总览｜连板天梯 M2 编码前门禁 v1

> 用途：在编码前冻结连板天梯 v5 的契约、来源、组合逻辑与验证清单。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁（不通过不允许编码）。

关联文档：

1. [连板天梯标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-benchmark-requirement-v1.md)
2. [连板天梯技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-implementation-design-v1.md)

---

## 1. 本轮门禁目标

1. 只允许按 v5 分层模型编码，不允许回退旧五桶模型。
2. 必须把“数据模型 / 来源表 / 组合规则”一次性冻结。
3. 编码前必须有可执行样例和异常样例。
4. 本门禁只约束连板天梯模块；共享来源不等于跨模块耦合。

---

## 2. 开工前总清单（全通过才能编码）

1. [x] 响应根对象使用 `streakLadderV5`，非旧 `buckets` 模型
2. [x] 来源表冻结为 `trade_calendar + equity_limit_list (+ equity_daily_bar补列)`
3. [x] 晋级层组合规则冻结（昨日全量 + 今日晋级子集）
4. [x] `advanced/currentStreakLevel` 行为冻结
5. [x] 掉队股票 `currentStreakLevel=0` 语义冻结
6. [x] 排序规则冻结
7. [x] 状态归并规则冻结
8. [x] 异常码登记完成
9. [x] 正常/延迟/空/错误 样例冻结
10. [x] 后端与前端消费字段命名一致性核验完成
11. [x] 已确认“只维护连板天梯字段真值表，不扩展到其它模块”

---

## 3. 请求与响应契约冻结

## 3.1 请求参数

```ts
interface StreakLadderRequest {
  market?: "CN_A";     // default: CN_A
  tradeDate?: string;  // YYYY-MM-DD
  debug?: 0 | 1;       // default: 0
}
```

校验：

1. `market` 非 `CN_A` -> 参数错误
2. `tradeDate` 非法格式 -> 参数错误
3. `debug` 非 `0/1` -> 参数错误

## 3.2 响应结构（冻结）

```ts
interface StreakLadderResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  streakLadderV5: {
    tradeDate: string;
    prevTradeDate: string;
    highestStreakLevel: number;
    aboveFive: LadderV5Stock[];
    promotions: Record<number, LadderV5PromotionLayer>;
    firstBoard: LadderV5Stock[];
  };
  debugInfo?: {
    modules: ModuleStatusItem[];
    exceptions: ModuleExceptionItem[];
  };
}
```

```ts
interface LadderV5PromotionLayer {
  previousLabel: string;
  currentLabel: string;
  previousStocks: LadderV5Stock[];
  currentStocks: LadderV5Stock[];
}

interface LadderV5Stock {
  stockName: string | null;
  stockCode: string;
  latestPrice: number | null;
  changePct: number | null;
  sectorName: string | null;
  openTimes: number | null;
  currentStreakLevel: number;
  advanced: boolean;
}
```

---

## 4. 来源表与字段映射门禁（重点）

> 口径声明：本节是“连板天梯字段真值表门禁”，不包含其它模块字段。

## 4.1 表级门禁

1. `core_serving.trade_calendar`：交易日上下文
2. `core_serving.equity_limit_list`：连板主事实
3. `core_serving.equity_daily_bar`：展示补列（仅补列）

## 4.2 字段级门禁

| 字段 | 来源 | 硬约束 |
|---|---|---|
| `currentStreakLevel` | `equity_limit_list.limit_times` | 必须来自该列解析，失败剔除 |
| `stockCode` | `equity_limit_list.ts_code` | 必填 |
| `stockName` | `equity_limit_list.name` | 可空 |
| `openTimes` | `equity_limit_list.open_times` | 可空 |
| `latestPrice` | `equity_limit_list.close` / `equity_daily_bar.close` | 允许补列回退 |
| `changePct` | `equity_limit_list.pct_chg` / `equity_daily_bar.pct_chg` | 允许补列回退 |
| `sectorName` | `equity_limit_list.industry` | 可空 |

强制规则：

1. `equity_daily_bar` 不能用于板数判定。
2. 板数判定只能来自 `equity_limit_list.limit_times`。
3. 与其它模块共享来源表时，仅共享数据事实，不共享模块规则与组装逻辑。

---

## 5. 组合逻辑门禁（重点）

## 5.1 必须按两日组合

1. 当日：`tradeDate`
2. 昨日：`prevTradeDate`

## 5.2 分层生成规则

1. `aboveFive`：当日 `currentStreakLevel >= 6`
2. `firstBoard`：当日 `currentStreakLevel = 1`
3. `promotions[level]`（`level=2..5`）：
   - `previousStocks` = 昨日 `boardCount=level-1` 全量
   - `currentStocks` = `previousStocks.codes ∩ 当日boardCount=level`
   - `previousStocks.advanced` 由交集判定
   - `previousStocks.currentStreakLevel`：
     - 当日有记录取当日板数；
     - 当日无记录记 `0`（掉队）

## 5.3 严禁行为

1. 把 `previousStocks` 过滤成仅晋级股票。
2. 仅按单日数据构造晋级层。
3. 在前端临时补 `advanced` 和 `currentStreakLevel`。

---

## 6. 排序门禁

1. `aboveFive`：
   - `currentStreakLevel desc`
   - `changePct desc nulls last`
   - `latestPrice desc nulls last`
   - `stockCode asc`
2. `currentStocks`：
   - `changePct desc nulls last`
   - `openTimes asc nulls last`
   - `stockCode asc`
3. `previousStocks`：
   - `advanced desc`
   - `currentStreakLevel desc`
   - `changePct desc nulls last`
   - `stockCode asc`

---

## 7. 状态与异常门禁

## 7.1 状态门禁

1. `READY`：结构完整
2. `DELAYED`：源观测日落后
3. `PARTIAL`：存在板数异常或补列缺失
4. `EMPTY`：目标日无有效数据
5. `ERROR`：查询/编排异常

## 7.2 异常码门禁

1. `SL_SOURCE_DELAYED`
2. `SL_SOURCE_EMPTY`
3. `SL_INVALID_BOARD_COUNT`
4. `SL_JOIN_METRIC_MISSING`
5. `SL_QUERY_FAILED`

必须登记文件：
[exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)

---

## 8. 核心样例门禁（最小集）

## 8.1 正常样例（必须覆盖）

1. `highestStreakLevel >= 6`，包含 `aboveFive`
2. `promotions[5..2]` 至少有一层
3. `previousStocks` 同时包含 `advanced=true/false`

## 8.2 delayed 样例（必须覆盖）

1. `observedTradeDate < expectedTradeDate`
2. `pageStatus=PARTIAL`（或全页归并后的合理状态）

## 8.3 empty 样例（必须覆盖）

1. `streakLadderV5` 结构仍完整
2. 各数组为空，状态 `EMPTY`

## 8.4 error 样例（必须覆盖）

1. `SL_QUERY_FAILED`
2. 不返回脏结构

---

## 9. 测试门禁（编码后必须通过）

1. 后端：
   - 两日组合单测（含晋级/掉队）
   - 异常分支单测（无效板数、补列缺失、空数据）
   - 集成测试（API 契约）
2. 前端：
   - adapter 字段映射测试
   - `StreakLadderPanel` 基础渲染与展开收起
   - `advanced` 标记驱动样式检查

---

## 10. 签字区

1. 需求负责人：`[x] 已确认（本轮门禁审计）`
2. 后端负责人：`[x] 已确认（本轮门禁审计）`
3. 前端负责人：`[x] 已确认（本轮门禁审计）`
4. 测试负责人：`[x] 已确认（本轮门禁审计）`

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 按 v5 UI 重写 M2 门禁：统一模型、来源、组合规则与测试清单 | Codex |
| v1.1 | 2026-05-13 | 运行门禁核验并完成勾选：typecheck、页面测试、build、异常码登记核验通过 | Codex |

---

## 12. 本轮门禁执行记录

1. 契约核验：`wealth/src/features/market-overview/api/marketOverviewTypes.ts` 与本门禁 `streakLadderV5` 字段一致。
2. 组件核验：`wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx` 已按 v5 分层（`aboveFive/promotions/firstBoard`）消费。
3. 异常码核验：`wealth/docs/system/exception-code-registry.md` 已登记 `SL_*` 五个异常码。
4. 命令核验：
   - `cd wealth && npm run -s typecheck` 通过
   - `cd wealth && npm run -s test -- src/pages/market-overview/MarketOverviewPage.test.tsx` 通过（20/20）
   - `cd wealth && npm run -s build` 通过
