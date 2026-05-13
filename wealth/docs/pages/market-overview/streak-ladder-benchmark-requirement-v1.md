# 市场总览｜连板天梯标杆需求 v1（benchmark-requirement）

> 用途：冻结“连板天梯”模块在当前最新版 UI（v7 股票卡片）下的业务语义、数据模型、来源表与组合口径。  
> 阶段：需求冻结。  
> 产物性质：业务事实源（不是实现细节文档）。

关联文档：

1. [连板天梯技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-implementation-design-v1.md)
2. [连板天梯 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-m2-coding-gate-v1.md)
3. [Review v7 Showcase](/Users/congming/github/goldenshare/wealth/docs/reference/showcase/market-overview-v7.html)

---

## 1. 现状审计结论

1. 连板天梯层级结构仍沿用 v5 模型：五板以上层、晋级层、首板层。
2. 最新 UI 变化只发生在股票卡片内部，卡片升级为 v7 三分区结构：
   - 左上角代码胶囊；
   - 左侧识别区：股票名称、最新价；
   - 中间行情事实区：涨跌幅、金额；
   - 右侧标签区：所属板块、连板文本。
3. 旧三件套缺少 v7 卡片必需字段：
   - `limitAmount`
   - `limitAmountDisplayText`
   - `limitAmountLabel`
   - `streakText`
4. 旧三件套没有写清 `limit_list_d` 中涨停和跌停金额字段的方向型口径。

本版文档只修正连板天梯模块自身口径，不修改其它市场总览模块。

---

## 2. 目标与定位

1. 模块目标：按交易日展示“昨日层级 → 今日晋级层级”的连板接力结构。
2. 用户价值：在一屏内看清“高标高度、晋级宽度、掉队情况、首板补充”。
3. 业务定位：市场总览中的独立模块，只展示客观结构，不做交易建议。
4. 展示目标：股票卡片必须与 v7 Showcase 的字段结构一致。

---

## 3. 范围与边界

### 3.1 本期覆盖

1. 覆盖连板天梯层级结构：
   - 五板以上层（今日六板及以上）
   - 晋级层：昨日四板→今日五板、昨日三板→今日四板、昨日二板→今日三板、昨日首板→今日二板（按最高板动态截取）
   - 首板层（今日首板）
2. 每层支持展开/收起，展开行为仍由前端展示组件负责。
3. 股票卡片可见字段覆盖：
   - `stockCode`
   - `stockName`
   - `latestPrice`
   - `changePct`
   - `sectorName`
   - `limitAmountDisplayText`
   - `streakText`
4. 股票卡片事实字段覆盖：
   - `limitAmount`
   - `limitAmountLabel`
5. 股票卡片点击仅触发当前页面既有交互（当前阶段不新增详情页能力）。
6. 支持模块级 debug 状态（仅 debug 模式返回）。

### 3.2 本期不覆盖

1. 不做个股详情页真实跳转。
2. 不做连板预测、评分、交易建议。
3. 不做用户自定义分层或排序。
4. 不做策略中心接入（本模块规则固定在后端）。
5. 不修改涨跌停统计与分布、榜单速览、板块速览等其它模块。

### 3.3 与其他模块边界

1. `streakLadder` 是独立模块，只维护自己的连板层级数据对象。
2. 连板天梯三件套只维护“连板天梯字段真值表”，不维护其它模块字段。
3. 与其它模块即使共享同一来源表（例如 `equity_limit_list`），也仅做共享来源说明，不做模块耦合设计。
4. `limit-up`（涨跌停统计与分布）有自己的三件套和字段真值表，不与连板天梯混写。
5. `leaderboards` 等模块不复用连板天梯层级逻辑。

---

## 4. 核心原则（硬约束）

1. 规则后端化：层级划分、晋级判定、排序、金额来源、连板文案由后端定义，前端只展示。
2. 模型单一：以本三件套定义的 `streakLadderV5` 为唯一事实源。
3. 主源确定：连板主事实来自 `core_serving.equity_limit_list`。
4. 跨日确定：必须同时使用“目标交易日 + 前一交易日”两天数据，禁止单日拼接伪晋级。
5. UI 语义一致：左侧层级为“昨日全量”；右侧层级为“今日晋级子集”。
6. 金额口径明确：涨停显示封单金额，跌停显示板上成交金额；连板天梯当前只取涨停。
7. 状态可观测：源数据落后、无效板数、补列缺失都必须有状态/异常表达。

禁止事项：

1. 前端自行根据 `limit_times` 分层或做晋级判定。
2. 前端自行从 `fd_amount/limit_amount/amount` 选择金额字段。
3. 前端自行格式化金额作为事实口径。
4. 前端把昨日层级过滤成“仅晋级股”。
5. 直接把旧“五桶模型”透传给 v7 UI。
6. 为补字段引入与本模块无关的临时接口。

---

## 5. 业务对象模型（需求层语义）

### 5.1 `StreakLadderV5`

| 字段 | 含义 | 可空 | 说明 |
|---|---|---|---|
| `tradeDate` | 当前观测交易日 | 否 | 例如 `2026-04-28` |
| `prevTradeDate` | 前一交易日 | 否 | 例如 `2026-04-27` |
| `highestStreakLevel` | 当日最高连板板数 | 否 | 非负整数 |
| `aboveFive` | 今日六板及以上股票 | 否 | 数组，可空数组 |
| `promotions` | 晋级层映射 | 否 | key 为 `2/3/4/5` |
| `firstBoard` | 今日首板股票 | 否 | 数组，可空数组 |

### 5.2 `LadderV5PromotionLayer`

| 字段 | 含义 | 可空 | 说明 |
|---|---|---|---|
| `previousLabel` | 昨日层标签 | 否 | 如“昨日二板” |
| `currentLabel` | 今日层标签 | 否 | 如“今日三板” |
| `previousStocks` | 昨日层全量股票 | 否 | 包含晋级与未晋级 |
| `currentStocks` | 今日晋级成功股票 | 否 | `previousStocks` 的晋级子集 |

### 5.3 `LadderV5Stock`

| 字段 | 含义 | 可空 | 缺失降级 |
|---|---|---|---|
| `stockName` | 股票名称 | 是 | 缺失时前端只展示代码 |
| `stockCode` | 股票代码 | 否 | 缺失则丢弃该行 |
| `latestPrice` | 最新价（盘后口径） | 是 | 缺失显示 `--` |
| `changePct` | 涨跌幅 | 是 | 缺失显示 `--` |
| `sectorName` | 行业/题材名 | 是 | 缺失显示 `--` |
| `limitAmount` | 卡片金额原始值 | 是 | 缺失显示 `--` |
| `limitAmountDisplayText` | 卡片金额展示文本 | 否 | 缺失值统一返回 `--` |
| `limitAmountLabel` | 卡片金额语义标签 | 否 | 当前连板天梯固定为“封单金额” |
| `streakText` | 连板/板型展示文本 | 否 | 如“首板”“3连板”“6板”“昨日二板” |
| `openTimes` | 开板次数 | 是 | 不进入 v7 卡片可见区域，仅作为扩展/调试事实字段 |
| `firstLimitTime` | 首次封板时间 | 是 | 不进入 v7 卡片可见区域，仅作为扩展/调试事实字段 |
| `currentStreakLevel` | 当前板数 | 否 | 可为 `0`（已掉队） |
| `advanced` | 是否晋级成功 | 否 | `true/false` |
| `quoteStatus` | 当日行情状态 | 否 | `READY` 有当日行情；`SUSPENDED` 当日停牌；`MISSING` 当日行情缺失且无停牌依据 |

---

## 6. 数据来源与字段映射

> 口径声明：本章是“连板天梯模块字段真值表”，只约束连板天梯自身字段；不承担其它模块字段定义。

### 6.1 来源表

1. `core_serving.trade_calendar`
2. `core_serving.equity_limit_list`
3. `core_serving.equity_daily_bar`（仅用于补齐当日行情展示列，不参与板数判定）
4. `core_serving.equity_suspend_d`（仅用于解释“昨日层股票当日无行情”的停牌状态）

### 6.2 来源接口事实

`core_serving.equity_limit_list` 对应 Tushare `limit_list_d`。

接口字段口径：

1. `limit_type='U'`：涨停。
2. `limit_type='D'`：跌停。
3. `fd_amount`：封单金额，涨停时用于展示。
4. `limit_amount`：板上成交金额，跌停时用于展示；涨停无此数据。
5. `amount`：全天成交额，不是本卡片金额字段来源。

连板天梯当前只取 `limit_type='U'`，因此卡片金额固定取 `fd_amount`。

### 6.3 字段映射总表

| 目标字段 | 主来源 | 列 | 规则 |
|---|---|---|---|
| `tradeDate` | `trade_calendar` | `trade_date` | 由请求日或系统期望交易日确定 |
| `prevTradeDate` | `trade_calendar` | `prev_trade_date` | 与 `tradeDate` 同市场口径 |
| `stockCode` | `equity_limit_list` | `ts_code` | 原样 |
| `stockName` | `equity_limit_list` | `name` | 原样 |
| `currentStreakLevel` | `equity_limit_list` | `limit_times` | 解析为正整数；失败剔除 |
| `openTimes` | `equity_limit_list` | `open_times` | 原样；不作为 v7 卡片默认展示字段 |
| `firstLimitTime` | `equity_limit_list` | `first_time` | 原样；不作为 v7 卡片默认展示字段 |
| `latestPrice` | `equity_limit_list` | `close` | 缺失可回退 `equity_daily_bar.close` |
| `changePct` | `equity_limit_list` | `pct_chg` | 缺失可回退 `equity_daily_bar.pct_chg` |
| `sectorName` | `equity_limit_list` | `industry` | 原样，缺失可空 |
| `limitAmount` | `equity_limit_list` | `fd_amount` | 连板天梯只取涨停，固定用封单金额 |
| `limitAmountDisplayText` | 后端格式化 | `fd_amount` | 例如 `1.27亿`、`8200万`、`--` |
| `limitAmountLabel` | 后端常量 | - | 当前固定为 `封单金额` |
| `streakText` | 后端生成 | `limit_times` + 跨日层级 | 一个字段、一个标签 |
| `quoteStatus` | `equity_daily_bar` / `equity_suspend_d` | `close/pct_chg`、`suspend_type` | 有当日行情为 `READY`；缺当日行情且 `suspend_type='S'` 为 `SUSPENDED`；否则为 `MISSING` |

补充：

1. `equity_limit_list` 只取 `limit_type='U'`（涨停池）。
2. `equity_daily_bar` 仅做展示补列，不可用于推导板数、晋级或金额。
3. `amount` 禁止作为 v7 股票卡片金额来源。
4. 若未来跌停模块复用相同卡片，跌停金额应取 `limit_amount`，标签为“板上成交金额”；这不改变连板天梯当前涨停口径。
5. 若其它模块也使用 `equity_limit_list`，那属于“共享来源”关系，不构成与连板天梯的数据耦合。
6. 昨日层股票若当日不在涨停池，必须优先取当日 `equity_daily_bar` 行情展示；若缺当日行情，再查 `equity_suspend_d` 判断是否停牌。

---

## 7. 组合规则

1. 先取 `tradeDate` 当日涨停池，解析 `currentStreakLevel`。
2. 再取 `prevTradeDate` 前一日涨停池，解析前一日板数。
3. 计算 `highestStreakLevel = max(tradeDate.currentStreakLevel)`。
4. 构建 `aboveFive`：
   - 过滤当日 `currentStreakLevel>=6`。
5. 构建晋级层 `level=2..5`（按最高板动态裁剪）：
   - `previousStocks`：前一日 `boardCount=level-1` 的全量股票。
   - `currentStocks`：`previousStocks.stockCode ∩ 当日boardCount=level` 的交集股票。
   - `previousStocks.advanced`：在交集内为 `true`，否则 `false`。
   - `previousStocks.currentStreakLevel`：
     - 若当日仍在涨停池，取当日板数；
     - 若当日不在涨停池，取 `0`（掉队）。
   - `previousStocks` 展示字段：
     - 当日仍在涨停池：使用当日涨停行；
     - 当日不在涨停池但有当日 `equity_daily_bar`：使用当日 `close/pct_chg`，金额置空；
     - 缺当日 `equity_daily_bar` 且 `equity_suspend_d.suspend_type='S'`：`quoteStatus=SUSPENDED`；
     - 缺当日 `equity_daily_bar` 且无停牌记录：`quoteStatus=MISSING`。
6. 构建 `firstBoard`：
   - 当日 `currentStreakLevel=1` 全量股票。
7. 构建 `streakText`：
   - 当日首板：`首板`
   - 当日 2 至 5 板：`N连板`
   - 当日 6 板及以上：`N板`
   - 昨日层掉队股票：`昨日N板`

---

## 8. 状态语义

1. 页面级状态：`READY / PARTIAL / DELAYED / EMPTY / ERROR`。
2. 模块级状态（debug）：
   - `moduleKey=streakLadder`
   - `expectedTradeDate`
   - `observedTradeDate`
   - `lagDays`
   - `status`
   - `note`
3. delayed 判定：`observedTradeDate < expectedTradeDate`。
4. partial 判定：
   - 存在 `limit_times` 解析失败；
   - 展示补列存在缺失但主结构可展示；
   - `fd_amount` 缺失但主结构可展示。

---

## 9. 异常语义

1. 异常结构：`module/code/severity/message/details`。
2. 异常码（本模块）：
   - `SL_SOURCE_DELAYED`
   - `SL_SOURCE_EMPTY`
   - `SL_INVALID_BOARD_COUNT`
   - `SL_JOIN_METRIC_MISSING`
   - `SL_QUERY_FAILED`
3. 所有异常码必须登记到
   [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)。

---

## 10. API 契约（需求层）

1. 接口路径：`GET /api/v1/wealth/market/streak-ladder`
2. 请求参数：
   - `market?: "CN_A"`（默认 `CN_A`）
   - `tradeDate?: string`（`YYYY-MM-DD`）
   - `debug?: 0 | 1`（默认 `0`）
3. 响应字段：
   - `tradingDay`
   - `pageStatus`
   - `streakLadderV5`
   - `debugInfo?`

---

## 11. 前端消费链路

1. API 类型必须在 `wealth/src/features/market-overview/limit-up/api/marketStreakLadderApi.ts` 中声明新字段。
2. Adapter 必须在 `wealth/src/features/market-overview/limit-up/api/marketStreakLadderAdapter.ts` 中原样映射：
   - `limitAmount`
   - `limitAmountDisplayText`
   - `limitAmountLabel`
   - `streakText`
3. 页面 ViewModel 必须在 `wealth/src/features/market-overview/api/marketOverviewTypes.ts` 中保留上述字段。
4. `StreakLadderPanel` 只能展示后端返回的金额文本和连板文本，不得自行选择来源列。

---

## 12. 验收标准

1. 必须能渲染三类层级：五板以上、晋级层、首板。
2. 晋级层必须满足“左侧昨日全量、右侧今日晋级子集”。
3. `advanced` 标记与交集判定一致。
4. `currentStreakLevel` 对掉队股票可为 `0`。
5. 股票卡片必须展示 v7 字段结构：
   - 左侧：`stockName/latestPrice`
   - 中间：`changePct/limitAmountDisplayText`
   - 右侧：`sectorName/streakText`
   - 左上角：`stockCode`
6. 涨停卡片金额必须来自 `fd_amount`，不得来自 `amount` 或 `limit_amount`。
7. 状态与异常必须能解释源落后、无数据、无效板数、当日行情缺失且无停牌依据、涨停上下文金额缺失等关键场景。

---

## 13. 已确认项

1. 采用 v5 连板层级模型，不回退旧五桶静态模型。
2. 股票卡片采用 v7 展示结构。
3. 连板板数判定只认 `equity_limit_list.limit_times`。
4. `equity_daily_bar` 只用于补行情显示列，不参与层级判定。
5. 连板天梯当前只取 `limit_type='U'`。
6. 涨停金额显示 `fd_amount`，语义为“封单金额”。
7. 跌停金额若未来使用，显示 `limit_amount`，语义为“板上成交金额”。
8. 本期无待拍板项。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 按最新版 UI（v5）重写：统一分层模型、来源表映射、跨日组合规则 | Codex |
| v1.2 | 2026-05-13 | 同步 v7 股票卡片字段、`fd_amount/limit_amount` 金额口径、前端消费链路与验收规则 | Codex |
