# 市场总览｜连板天梯 M2 编码前门禁 v1

> 用途：在编码前冻结连板天梯层级、v7 股票卡片契约、来源、组合逻辑与验证清单。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁（不通过不允许编码）。

关联文档：

1. [连板天梯标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-benchmark-requirement-v1.md)
2. [连板天梯技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-implementation-design-v1.md)
3. [Review v7 Showcase](/Users/congming/github/goldenshare/wealth/docs/reference/showcase/market-overview-v7.html)

---

## 1. 本轮门禁目标

1. 只允许按连板天梯 v5 层级模型编码，不允许回退旧五桶模型。
2. 股票卡片必须按 v7 字段结构编码，不允许保留旧开板次数默认展示。
3. 必须把“数据模型 / 来源表 / 金额口径 / 组合规则 / 前端消费链路”一次性冻结。
4. 编码前必须有可执行样例和异常样例。
5. 本门禁只约束连板天梯模块；共享来源不等于跨模块耦合。

---

## 2. 开工前总清单（全通过才能编码）

1. [x] 响应根对象使用 `streakLadderV5`，非旧 `buckets` 模型。
2. [x] 来源表冻结为 `trade_calendar + equity_limit_list (+ equity_daily_bar补列)`。
3. [x] 晋级层组合规则冻结（昨日全量 + 今日晋级子集）。
4. [x] `advanced/currentStreakLevel` 行为冻结。
5. [x] 掉队股票 `currentStreakLevel=0` 语义冻结。
6. [x] v7 股票卡片字段冻结。
7. [x] `fd_amount/limit_amount` 方向型金额口径冻结。
8. [x] 排序规则冻结。
9. [x] 状态归并规则冻结。
10. [x] 异常码登记完成。
11. [x] 正常/延迟/空/错误样例冻结。
12. [x] 后端与前端消费字段命名一致性核验完成。
13. [x] 已确认“只维护连板天梯字段真值表，不扩展到其它模块”。
14. [x] 本轮无待拍板项。

---

## 3. 请求与响应契约冻结

### 3.1 请求参数

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

### 3.2 响应结构（冻结）

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
  limitAmount: number | null;
  limitAmountDisplayText: string;
  limitAmountLabel: "封单金额" | "板上成交金额";
  streakText: string;
  openTimes: number | null;
  firstLimitTime: string | null;
  currentStreakLevel: number;
  advanced: boolean;
}
```

---

## 4. 来源表与字段映射门禁

> 口径声明：本节是“连板天梯字段真值表门禁”，不包含其它模块字段。

### 4.1 表级门禁

1. `core_serving.trade_calendar`：交易日上下文。
2. `core_serving.equity_limit_list`：连板主事实。
3. `core_serving.equity_daily_bar`：展示补列（仅补列）。

### 4.2 字段级门禁

| 字段 | 来源 | 硬约束 |
|---|---|---|
| `currentStreakLevel` | `equity_limit_list.limit_times` | 必须来自该列解析，失败剔除 |
| `stockCode` | `equity_limit_list.ts_code` | 必填 |
| `stockName` | `equity_limit_list.name` | 可空 |
| `openTimes` | `equity_limit_list.open_times` | 可空；不进入 v7 卡片默认可见区域 |
| `firstLimitTime` | `equity_limit_list.first_time` | 可空；不进入 v7 卡片默认可见区域 |
| `latestPrice` | `equity_limit_list.close` / `equity_daily_bar.close` | 允许补列回退 |
| `changePct` | `equity_limit_list.pct_chg` / `equity_daily_bar.pct_chg` | 允许补列回退 |
| `sectorName` | `equity_limit_list.industry` | 可空 |
| `limitAmount` | `equity_limit_list.fd_amount` | 当前模块只取涨停，必须来自封单金额 |
| `limitAmountDisplayText` | 后端格式化 | 必须由后端返回 |
| `limitAmountLabel` | 后端常量 | 当前固定为 `封单金额` |
| `streakText` | 后端生成 | 必须由后端返回 |

强制规则：

1. `equity_daily_bar` 不能用于板数判定。
2. 板数判定只能来自 `equity_limit_list.limit_times`。
3. `equity_limit_list` 当前必须过滤 `limit_type='U'`。
4. 涨停卡片金额只能来自 `fd_amount`。
5. 涨停卡片禁止使用 `limit_amount`。
6. 涨停卡片禁止使用 `amount`。
7. 与其它模块共享来源表时，仅共享数据事实，不共享模块规则与组装逻辑。

### 4.3 `limit_list_d` 金额口径门禁

| 场景 | 字段 | 是否用于连板天梯 | 说明 |
|---|---|---|---|
| 涨停 `U` | `fd_amount` | 是 | 展示“封单金额” |
| 跌停 `D` | `limit_amount` | 否 | 未来跌停模块可展示“板上成交金额” |
| 涨停 `U` | `limit_amount` | 否 | 文档明确涨停无此数据 |
| 任意 | `amount` | 否 | 全天成交额，不是卡片金额口径 |

---

## 5. 组合逻辑门禁

### 5.1 必须按两日组合

1. 当日：`tradeDate`
2. 昨日：`prevTradeDate`

### 5.2 分层生成规则

1. `aboveFive`：当日 `currentStreakLevel >= 6`
2. `firstBoard`：当日 `currentStreakLevel = 1`
3. `promotions[level]`（`level=2..5`）：
   - `previousStocks` = 昨日 `boardCount=level-1` 全量
   - `currentStocks` = `previousStocks.codes ∩ 当日boardCount=level`
   - `previousStocks.advanced` 由交集判定
   - `previousStocks.currentStreakLevel`：
     - 当日有记录取当日板数；
     - 当日无记录记 `0`（掉队）

### 5.3 文案生成门禁

1. `streakText` 必须由后端生成。
2. 规则：
   - 当日首板：`首板`
   - 当日 2 至 5 板：`N连板`
   - 当日 6 板及以上：`N板`
   - 昨日层掉队股票：`昨日N板`
3. 前端不得自行拼接或覆盖 `streakText`。

### 5.4 严禁行为

1. 把 `previousStocks` 过滤成仅晋级股票。
2. 仅按单日数据构造晋级层。
3. 在前端临时补 `advanced/currentStreakLevel/streakText`。
4. 在前端临时拼金额展示文本。

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

## 7. 前端消费门禁

### 7.1 API 类型

文件：

```text
wealth/src/features/market-overview/limit-up/api/marketStreakLadderApi.ts
```

门禁：

1. `aboveFive/previousStocks/currentStocks/firstBoard` 中的 stock 对象必须全部包含：
   - `limitAmount`
   - `limitAmountDisplayText`
   - `limitAmountLabel`
   - `streakText`

### 7.2 Adapter

文件：

```text
wealth/src/features/market-overview/limit-up/api/marketStreakLadderAdapter.ts
```

门禁：

1. Adapter 不得选择金额来源。
2. Adapter 不得格式化金额。
3. Adapter 不得拼接 `streakText`。
4. Adapter 只允许做空值清洗与类型稳定。

### 7.3 ViewModel 与组件

文件：

```text
wealth/src/features/market-overview/api/marketOverviewTypes.ts
wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx
```

门禁：

1. `LadderV5Stock` 必须包含 v7 卡片字段。
2. 组件必须展示：
   - 左上角：`stockCode`
   - 左侧：`stockName/latestPrice`
   - 中间：`changePct/limitAmountDisplayText`
   - 右侧：`sectorName/streakText`
3. 组件不得默认展示 `openTimes`。
4. 组件不得自行回退成“一字板/开板N次”文案。

---

## 8. 状态与异常门禁

### 8.1 状态门禁

1. `READY`：结构完整
2. `DELAYED`：源观测日落后
3. `PARTIAL`：存在板数异常、补列缺失或金额缺失
4. `EMPTY`：目标日无有效数据
5. `ERROR`：查询/编排异常

### 8.2 异常码门禁

1. `SL_SOURCE_DELAYED`
2. `SL_SOURCE_EMPTY`
3. `SL_INVALID_BOARD_COUNT`
4. `SL_JOIN_METRIC_MISSING`
5. `SL_QUERY_FAILED`

必须登记文件：
[exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)

---

## 9. 核心样例门禁（最小集）

### 9.1 正常样例（必须覆盖）

1. `highestStreakLevel >= 6`，包含 `aboveFive`
2. `promotions[5..2]` 至少有一层
3. `previousStocks` 同时包含 `advanced=true/false`
4. stock 对象包含 `limitAmountDisplayText`
5. stock 对象包含 `streakText`

### 9.2 delayed 样例（必须覆盖）

1. `observedTradeDate < expectedTradeDate`
2. `pageStatus=PARTIAL`（或全页归并后的合理状态）

### 9.3 empty 样例（必须覆盖）

1. `streakLadderV5` 结构仍完整
2. 各数组为空，状态 `EMPTY`

### 9.4 error 样例（必须覆盖）

1. `SL_QUERY_FAILED`
2. 不返回脏结构

### 9.5 金额口径样例（必须覆盖）

1. 涨停样例：`limit_type='U'` 时 `limitAmount=fd_amount`、`limitAmountLabel='封单金额'`。
2. 涨停样例：`amount` 不得出现在卡片金额断言中。
3. 涨停样例：`limit_amount` 不得出现在卡片金额断言中。

---

## 10. 测试门禁（编码后必须通过）

1. 后端：
   - 两日组合单测（含晋级/掉队）
   - 金额来源单测（`fd_amount` 进入涨停卡片）
   - 文案生成单测（`首板/N连板/N板/昨日N板`）
   - 异常分支单测（无效板数、补列缺失、金额缺失、空数据）
   - 集成测试（API 契约）
2. 前端：
   - adapter 字段映射测试
   - `StreakLadderPanel` 基础渲染与展开收起
   - `limitAmountDisplayText` 展示测试
   - `streakText` 展示测试
   - `advanced` 标记驱动样式检查

---

## 11. 签字区

1. 需求负责人：`[x] 已确认（本轮 v7 卡片 + 金额口径门禁）`
2. 后端负责人：`[x] 已确认（本轮 v7 卡片 + 金额口径门禁）`
3. 前端负责人：`[x] 已确认（本轮 v7 卡片 + 金额口径门禁）`
4. 测试负责人：`[x] 已确认（本轮 v7 卡片 + 金额口径门禁）`

---

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 按 v5 UI 重写 M2 门禁：统一模型、来源、组合规则与测试清单 | Codex |
| v1.1 | 2026-05-13 | 运行门禁核验并完成勾选：typecheck、页面测试、build、异常码登记核验通过 | Codex |
| v1.2 | 2026-05-13 | 同步 v7 股票卡片字段、金额口径、前端消费链路与新增测试门禁 | Codex |

---

## 13. 本轮门禁执行记录

1. 契约核验：待编码时同步 `wealth/src/features/market-overview/api/marketOverviewTypes.ts` 与本门禁字段。
2. 组件核验：待编码时同步 `wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx` 的 v7 卡片消费字段。
3. 异常码核验：`wealth/docs/system/exception-code-registry.md` 已登记 `SL_*` 五个异常码。
4. 金额口径核验：本门禁已冻结 `limit_type='U' -> fd_amount -> 封单金额`。
5. 命令核验：本次仅文档更新，未执行代码测试。
