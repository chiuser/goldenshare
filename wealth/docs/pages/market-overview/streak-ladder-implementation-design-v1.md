# 市场总览｜连板天梯技术实施方案 v1（implementation-design）

> 用途：把连板天梯 benchmark 需求转成可执行技术方案。  
> 阶段：编码前。  
> 产物性质：实现基线（不在本文写业务代码）。

关联文档：

1. [连板天梯标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-benchmark-requirement-v1.md)
2. [连板天梯 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-m2-coding-gate-v1.md)
3. [Review v7 Showcase](/Users/congming/github/goldenshare/wealth/docs/reference/showcase/market-overview-v7.html)

---

## 1. 目的与边界

1. 目标：按最新版 UI（v7 股票卡片）落地连板天梯数据链路，确保后端输出与前端展示一一对应。
2. 本文只处理：
   - 连板天梯层级模型；
   - v7 股票卡片数据模型；
   - 数据来源表与字段映射；
   - 跨日组合算法；
   - 状态与异常归并；
   - 前端 API/adapter/view model 消费链路。
3. 本文不处理：
   - 其它市场总览模块；
   - 个股详情页跳转；
   - 策略中心接入；
   - 涨跌停统计与分布模块的数据模型。
4. 模块边界硬约束：
   - 连板天梯实施方案只覆盖连板天梯字段真值表与实现链路；
   - 即使与其它模块共享数据表，也不引入跨模块耦合逻辑。

---

## 2. 现状代码审计

1. 后端接口路径已存在：
   - `/Users/congming/github/goldenshare/src/biz/api/wealth/market/streak_ladder.py`
2. 后端 schema 已存在：
   - `/Users/congming/github/goldenshare/src/biz/schemas/wealth/market/streak_ladder.py`
3. 后端查询已存在：
   - `/Users/congming/github/goldenshare/src/biz/queries/wealth/market/streak_ladder/streak_ladder_query.py`
4. 后端组装服务已存在：
   - `/Users/congming/github/goldenshare/src/biz/services/wealth/market/streak_ladder/streak_ladder_builder.py`
5. 前端 API 类型与 adapter 已存在：
   - `/Users/congming/github/goldenshare/wealth/src/features/market-overview/limit-up/api/marketStreakLadderApi.ts`
   - `/Users/congming/github/goldenshare/wealth/src/features/market-overview/limit-up/api/marketStreakLadderAdapter.ts`
6. 前端页面 ViewModel 类型已存在：
   - `/Users/congming/github/goldenshare/wealth/src/features/market-overview/api/marketOverviewTypes.ts`
7. 前端展示组件已存在：
   - `/Users/congming/github/goldenshare/wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx`

当前差距：

1. `LadderV5Stock` 缺少 v7 卡片所需金额字段和连板文本字段。
2. 查询层未选择 `fd_amount/limit_amount/limit_type`。
3. Builder 未生成 `limitAmountDisplayText/limitAmountLabel/streakText`。
4. 前端 adapter 仍会局部兜底旧字段，后续必须改为消费后端事实字段。

---

## 3. 目标数据模型（实现冻结）

### 3.1 根对象 `streakLadderV5`

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

### 3.2 晋级层对象

```ts
interface LadderV5PromotionLayer {
  previousLabel: string;          // 例如：昨日二板
  currentLabel: string;           // 例如：今日三板
  previousStocks: LadderV5Stock[]; // 昨日层全量
  currentStocks: LadderV5Stock[];  // 今日晋级子集
}
```

### 3.3 股票对象

```ts
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
  currentStreakLevel: number; // 掉队可为 0
  advanced: boolean;
  quoteStatus: "READY" | "SUSPENDED" | "MISSING";
}
```

说明：

1. `limitAmountDisplayText` 是卡片展示文本，前端不得自行选择来源列。
2. `limitAmountLabel` 是金额口径标签，当前连板天梯固定为“封单金额”。
3. `openTimes/firstLimitTime` 暂不进入 v7 卡片默认展示区，仅保留为扩展/调试事实字段。
4. `streakText` 是右侧标签区唯一连板文本，不拆成多个字段。
5. `quoteStatus` 由后端判定，前端不得自行用空价格猜测停牌或缺行情。

---

## 4. 数据来源与映射

> 口径声明：以下映射是“连板天梯模块字段真值表（实现版）”，不扩展到其它模块。

### 4.1 来源表

1. `core_serving.trade_calendar`
2. `core_serving.equity_limit_list`
3. `core_serving.equity_daily_bar`（仅补展示列）
4. `core_serving.equity_suspend_d`（仅解释当日无行情是否停牌）

### 4.2 `limit_list_d` 金额字段规则

`core_serving.equity_limit_list` 来自 Tushare `limit_list_d`。

| 场景 | `limit_type` | 展示金额来源 | 展示标签 | 说明 |
|---|---|---|---|---|
| 涨停 | `U` | `fd_amount` | `封单金额` | 连板天梯当前只取该场景 |
| 跌停 | `D` | `limit_amount` | `板上成交金额` | 仅作为未来复用规则，不进入当前连板天梯 |
| 炸板 | `Z` | 不进入连板天梯 | - | 当前模块不处理 |

禁止：

1. 涨停卡片禁止使用 `limit_amount`，因为该字段“涨停无此数据”。
2. 涨停卡片禁止使用 `amount`，因为该字段是全天成交额，不是卡片金额口径。
3. 前端禁止自行从 `fd_amount/limit_amount/amount` 中选择字段。

### 4.3 字段映射

| 目标字段 | 主来源表 | 来源列 | 规则 |
|---|---|---|---|
| `tradeDate` | `trade_calendar` | `trade_date` | 请求日或系统期望交易日 |
| `prevTradeDate` | `trade_calendar` | `prev_trade_date` | 与 `tradeDate` 同口径 |
| `stockCode` | `equity_limit_list` | `ts_code` | 必填 |
| `stockName` | `equity_limit_list` | `name` | 可空 |
| `currentStreakLevel` | `equity_limit_list` | `limit_times` | 解析正整数 |
| `openTimes` | `equity_limit_list` | `open_times` | 可空；非 v7 默认展示字段 |
| `firstLimitTime` | `equity_limit_list` | `first_time` | 可空；非 v7 默认展示字段 |
| `latestPrice` | `equity_limit_list` | `close` | 缺失回退 `equity_daily_bar.close` |
| `changePct` | `equity_limit_list` | `pct_chg` | 缺失回退 `equity_daily_bar.pct_chg` |
| `sectorName` | `equity_limit_list` | `industry` | 可空 |
| `limitAmount` | `equity_limit_list` | `fd_amount` | 当前过滤 `limit_type='U'`，固定取封单金额 |
| `limitAmountDisplayText` | 后端格式化 | `fd_amount` | 缺失返回 `--` |
| `limitAmountLabel` | 后端常量 | - | 当前固定返回 `封单金额` |
| `streakText` | 后端生成 | `limit_times` + 跨日层级 | 一个字段、一个标签 |
| `quoteStatus` | `equity_daily_bar` / `equity_suspend_d` | `close/pct_chg`、`suspend_type` | 后端判定：有当日行情为 `READY`，缺行情且停牌为 `SUSPENDED`，否则 `MISSING` |

约束：

1. `equity_limit_list` 必须过滤 `limit_type='U'`。
2. `equity_daily_bar` 不能参与板数/晋级/金额判定。
3. 共享来源仅用于说明数据事实，不允许在本模块内耦合其它模块的业务规则。
4. 昨日层股票当日未涨停时，不允许回退展示昨日价格；必须用当日 `equity_daily_bar`，无当日行情时再用 `equity_suspend_d` 解释状态。

---

## 5. 查询层改造方案

目标文件：

```text
src/biz/queries/wealth/market/streak_ladder/streak_ladder_query.py
```

### 5.1 查询字段

在现有查询基础上新增：

1. `EquityLimitList.limit_type`
2. `EquityLimitList.fd_amount`
3. `EquityLimitList.limit_amount`
4. 当前交易日 `EquityDailyBar.close/pct_chg`，用于昨日层掉队股票展示当日行情。
5. 当前交易日 `EquitySuspendD.suspend_type='S'`，用于昨日层股票无当日行情时标记停牌。

### 5.2 行对象

目标文件：

```text
src/biz/services/wealth/market/streak_ladder/streak_ladder_builder.py
```

`StreakLadderRow` 新增：

```py
limit_type: str | None
fd_amount: Decimal | None
limit_amount: Decimal | None
quote_status: str
```

### 5.3 有效性门禁

保留已有涨停有效性门禁：

1. `close > 0`
2. `pct_chg > 0`

涨停上下文金额缺失不剔除结构行，只把 `limitAmount=null`、`limitAmountDisplayText="--"`，并触发 `PARTIAL` 或 debug note。昨日层掉队股票的金额置空是非涨停场景的正常口径，不单独触发 `PARTIAL`。

昨日层掉队股票额外门禁：

1. 当日 `equity_daily_bar` 存在且 `close>0`、`pct_chg` 非空：`quoteStatus=READY`，展示当日价格和涨跌幅，金额置空。
2. 当日 `equity_daily_bar` 缺失，且 `equity_suspend_d.suspend_type='S'`：`quoteStatus=SUSPENDED`。
3. 当日 `equity_daily_bar` 缺失，且无停牌记录：`quoteStatus=MISSING`。
4. `SUSPENDED/MISSING` 不允许回退昨日价格。

---

## 6. 组合算法

### 6.1 输入上下文

1. `tradeDate`
2. `prevTradeDate`
3. `market=CN_A`

### 6.2 中间集合

1. `todayRows`：当日涨停池（解析后有效板数）
2. `prevRows`：昨日涨停池（解析后有效板数）
3. `todayByCode`：`todayRows` 按 `stockCode` 建索引
4. `prevByLevel[level]`：`prevRows` 按板数分层
5. `todayByLevel[level]`：`todayRows` 按板数分层

### 6.3 生成 `highestStreakLevel`

1. `highestStreakLevel = max(todayRows.currentStreakLevel)`。
2. 若当日无有效数据，走 `EMPTY` 状态链路。

### 6.4 生成 `aboveFive`

1. 过滤 `todayRows` 中 `currentStreakLevel >= 6`。
2. 映射为 `LadderV5Stock[]`，`advanced=true`。
3. `streakText` 使用 `N板`。

### 6.5 生成晋级层

对 `level in [2,3,4,5]`，按 `highestStreakLevel` 动态裁剪：

1. `prevCandidates = prevByLevel[level-1]`（昨日该层全量）
2. `todayCandidates = todayByLevel[level]`（今日目标层）
3. `advancedCodes = prevCandidates.codes ∩ todayCandidates.codes`
4. `currentStocks`：
   - 仅 `advancedCodes`；
   - 字段使用当日记录；
   - `advanced=true`；
   - `streakText=N连板`。
5. `previousStocks`：
   - 保留 `prevCandidates` 全量；
   - 对每只股票：
     - 若当日存在记录：展示列优先取当日；
     - 若当日不存在记录但有当日 `equity_daily_bar`：展示当日价格/涨跌幅，金额置空；
     - 若当日不存在记录且无当日 `equity_daily_bar`：查 `equity_suspend_d`，停牌返回 `quoteStatus=SUSPENDED`，否则 `quoteStatus=MISSING`；
   - `advanced = stockCode in advancedCodes`；
   - `currentStreakLevel`：
     - 当日存在记录：取当日板数；
     - 当日无记录：记为 `0`（掉队）；
   - `streakText`：
     - 晋级成功：按当日板数生成；
     - 掉队：使用 `昨日N板`。

### 6.6 生成 `firstBoard`

1. 过滤 `todayRows` 中 `currentStreakLevel = 1`。
2. 映射为 `LadderV5Stock[]`，`advanced=true`。
3. `streakText=首板`。

---

## 7. 金额与文本生成

### 7.1 `limitAmount`

实现函数建议：

```py
def resolve_limit_amount(row: StreakLadderRow) -> tuple[Decimal | None, str]:
    if row.limit_type == "U":
        return row.fd_amount, "封单金额"
    if row.limit_type == "D":
        return row.limit_amount, "板上成交金额"
    return None, "封单金额"
```

当前连板天梯过滤 `limit_type='U'`，因此实际返回固定为：

1. `limitAmount = fd_amount`
2. `limitAmountLabel = "封单金额"`

### 7.2 `limitAmountDisplayText`

后端统一格式化，前端只展示。

建议规则：

1. `None` -> `--`
2. `>= 100000000` -> 保留 2 位小数，单位 `亿`，例如 `1.27亿`
3. `>= 10000` -> 取整或保留 1 位，单位 `万`，例如 `8200万`
4. `< 10000` -> 原数值整数展示

### 7.3 `streakText`

建议规则：

1. 当日 `1` 板 -> `首板`
2. 当日 `2..5` 板 -> `N连板`
3. 当日 `>=6` 板 -> `N板`
4. 昨日层掉队股票 -> `昨日N板`

`streakText` 由后端生成，前端不得根据 `currentStreakLevel/advanced` 重新拼文案。

---

## 8. 排序与展示控制

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
4. 展开/收起数量由前端组件按 Showcase 规则处理；后端不按 UI 折叠数量截断。

---

## 9. 状态与异常

### 9.1 模块状态

1. `READY`：结构完整可展示。
2. `DELAYED`：`observedTradeDate < expectedTradeDate`。
3. `PARTIAL`：存在无效板数行、当日行情缺失且无停牌依据，或涨停上下文金额缺失。
4. `EMPTY`：目标日无有效涨停结构数据。
5. `ERROR`：查询或组装异常。

### 9.2 异常码

1. `SL_SOURCE_DELAYED`
2. `SL_SOURCE_EMPTY`
3. `SL_INVALID_BOARD_COUNT`
4. `SL_JOIN_METRIC_MISSING`
5. `SL_QUERY_FAILED`

涨停上下文金额缺失可以进入 `SL_JOIN_METRIC_MISSING`，details 中标记 `field=fd_amount`。昨日层掉队股票若有当日行情但无封单金额，不属于金额缺失。

---

## 10. API 契约（实施口径）

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

`LadderV5StockDto` 必须包含：

```py
stockName: str | None
stockCode: str
latestPrice: float | None
changePct: float | None
sectorName: str | None
limitAmount: float | None
limitAmountDisplayText: str
limitAmountLabel: Literal["封单金额", "板上成交金额"]
streakText: str
openTimes: int | None
firstLimitTime: str | None
currentStreakLevel: int
advanced: bool
```

---

## 11. 前端消费链路改造方案

### 11.1 API 类型

目标文件：

```text
wealth/src/features/market-overview/limit-up/api/marketStreakLadderApi.ts
```

要求：

1. 所有 `LadderV5Stock` 响应对象补齐：
   - `limitAmount`
   - `limitAmountDisplayText`
   - `limitAmountLabel`
   - `streakText`
2. 字段名必须与后端 lowerCamelCase 一致。

### 11.2 Adapter

目标文件：

```text
wealth/src/features/market-overview/limit-up/api/marketStreakLadderAdapter.ts
```

要求：

1. Adapter 只做字段清洗和空值兜底。
2. Adapter 不允许：
   - 根据 `openTimes` 拼“一字板/开板N次”；
   - 根据 `currentStreakLevel` 拼 `streakText`；
   - 自行选择金额来源；
   - 自行格式化金额。
3. 对后端缺失的展示文本，只能降级为 `--`，并保留错误暴露给测试。

### 11.3 ViewModel 类型

目标文件：

```text
wealth/src/features/market-overview/api/marketOverviewTypes.ts
```

要求：

1. `LadderV5Stock` 与 API 契约保持字段一致。
2. 不新增旧字段别名。
3. 不把 `limitAmountDisplayText` 改名为 `boardTradeAmountText`。

### 11.4 展示组件

目标文件：

```text
wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx
```

要求：

1. 只展示 API/ViewModel 字段。
2. v7 卡片字段位置：
   - 左上角胶囊：`stockCode`
   - 左侧：`stockName/latestPrice`
   - 中间：`changePct/limitAmountDisplayText`
   - 右侧：`sectorName/streakText`
3. 不再默认展示 `openTimes`。
4. 不再由组件拼接 `streakText`。

---

## 12. 代码落位

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

wealth/src/features/market-overview/
  limit-up/api/
    marketStreakLadderApi.ts
    marketStreakLadderAdapter.ts
  limit-up/StreakLadderPanel.tsx
  api/marketOverviewTypes.ts
```

说明：

1. `query` 负责拉取与基础投影，不写 UI 语义。
2. `service` 负责连板组合语义、金额口径、文案生成。
3. `schema` 冻结响应契约，前端不可自行扩展事实字段。
4. 前端只负责展示和交互，不负责事实拼装。

---

## 13. 验证要点

1. `previousStocks` 必须包含昨日层全量，不得只保留晋级股。
2. `currentStocks` 必须是晋级交集子集。
3. `currentStreakLevel` 对掉队股票为 `0`。
4. `equity_daily_bar` 仅作为展示补列来源，不可影响层级判定。
5. 涨停金额必须来自 `fd_amount`。
6. `amount` 和 `limit_amount` 不得进入涨停卡片金额。
7. 前端不得自行拼接 `streakText` 或格式化金额。
8. 模块状态与异常码必须可追溯到具体数据缺口。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 按 v5 UI 重写实现方案：统一数据模型、来源映射、跨日组合算法 | Codex |
| v1.2 | 2026-05-13 | 同步 v7 股票卡片字段、金额来源规则、前后端消费链路与实现门禁 | Codex |
