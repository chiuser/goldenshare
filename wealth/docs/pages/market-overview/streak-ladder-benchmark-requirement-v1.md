# 市场总览｜连板天梯标杆需求 v1（benchmark-requirement）

> 用途：冻结“连板天梯”模块在当前最新版 UI（v5）下的业务语义、数据模型、来源表与组合口径。  
> 阶段：需求冻结前。  
> 产物性质：业务事实源（不是实现细节文档）。

关联文档：

1. [连板天梯技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-implementation-design-v1.md)
2. [连板天梯 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-m2-coding-gate-v1.md)

---

## 1. 现状审计结论（与旧三件套不符点）

1. 旧文档仍以“固定五桶（首板/二板/三板/四板/五板+）”为主模型。  
   现状 UI 已是 v5 分层模型：五板以上层 + 晋级层（昨日N板→今日N+1板）+ 首板层。
2. 旧文档把“连板天梯”定义成静态单日分桶。  
   现状 UI 明确展示“昨日层级全量 + 今日晋级子集”的跨日联动语义。
3. 旧文档未完整写清“非晋级股票为何仍展示在左侧”。  
   现状 UI 左侧就是昨日层级全量，右侧才是晋级成功子集。

本版文档已按以上差异统一修正。

---

## 2. 目标与定位

1. 模块目标：按交易日展示“昨日层级 → 今日晋级层级”的连板接力结构。
2. 用户价值：在一屏内看清“高标高度、晋级宽度、掉队情况、首板补充”。
3. 业务定位：市场总览中的独立模块，只展示客观结构，不做交易建议。

---

## 3. 范围与边界

### 3.1 本期覆盖

1. 覆盖 v5 连板天梯全部结构：
   - 五板以上层（今日六板及以上）
   - 晋级层：昨日四板→今日五板、昨日三板→今日四板、昨日二板→今日三板、昨日首板→今日二板（按最高板动态截取）
   - 首板层（今日首板）
2. 每层默认最多展示 12 只，支持展开/收起。
3. 股票卡片字段覆盖：
   - `stockName`
   - `stockCode`
   - `latestPrice`
   - `changePct`
   - `sectorName`
   - `openTimes`
   - `currentStreakLevel`
   - `advanced`
4. 股票卡片点击仅触发 toast（当前阶段不跳转详情）。
5. 支持模块级 debug 状态（仅 debug 模式返回）。

### 3.2 本期不覆盖

1. 不做个股详情页真实跳转。
2. 不做连板预测、评分、交易建议。
3. 不做用户自定义分层或排序。
4. 不做策略中心接入（本模块规则固定在后端）。

### 3.3 与其他模块边界

1. `streakLadder` 是独立模块，只维护自己的 v5 连板层级数据对象。
2. 连板天梯三件套只维护“连板天梯字段真值表”，不维护其它模块字段。
3. 与其它模块即使共享同一来源表（例如 `equity_limit_list`），也仅做共享来源说明，不做模块耦合设计。
4. `leaderboards` 等模块不复用连板天梯层级逻辑。

---

## 4. 核心原则（硬约束）

1. 规则后端化：层级划分、晋级判定、排序、降级由后端定义，前端只展示。
2. 模型单一：以本三件套定义的 `streakLadderV5` 为唯一事实源。
3. 主源确定：连板主事实来自 `core_serving.equity_limit_list`。
4. 跨日确定：必须同时使用“目标交易日 + 前一交易日”两天数据，禁止单日拼接伪晋级。
5. UI语义一致：左侧层级为“昨日全量”；右侧层级为“今日晋级子集”。
6. 状态可观测：源数据落后、无效板数、补列缺失都必须有状态/异常表达。

禁止事项：

1. 前端自行根据 `limit_times` 分层或做晋级判定。
2. 前端把昨日层级过滤成“仅晋级股”。
3. 直接把旧“五桶模型”透传给 v5 UI。
4. 为补字段引入与本模块无关的临时接口。

---

## 5. 业务对象模型（需求层语义）

## 5.1 `StreakLadderV5`

| 字段 | 含义 | 可空 | 说明 |
|---|---|---|---|
| `tradeDate` | 当前观测交易日 | 否 | 例如 `2026-04-28` |
| `prevTradeDate` | 前一交易日 | 否 | 例如 `2026-04-27` |
| `highestStreakLevel` | 当日最高连板板数 | 否 | 正整数 |
| `aboveFive` | 今日六板及以上股票 | 否 | 数组，可空数组 |
| `promotions` | 晋级层映射 | 否 | key 为 `2/3/4/5` |
| `firstBoard` | 今日首板股票 | 否 | 数组，可空数组 |

## 5.2 `LadderV5PromotionLayer`

| 字段 | 含义 | 可空 | 说明 |
|---|---|---|---|
| `previousLabel` | 昨日层标签 | 否 | 如“昨日二板” |
| `currentLabel` | 今日层标签 | 否 | 如“今日三板” |
| `previousStocks` | 昨日层全量股票 | 否 | 包含晋级与未晋级 |
| `currentStocks` | 今日晋级成功股票 | 否 | `previousStocks` 的晋级子集 |

## 5.3 `LadderV5Stock`

| 字段 | 含义 | 可空 | 缺失降级 |
|---|---|---|---|
| `stockName` | 股票名称 | 是 | 缺失时前端只展示代码 |
| `stockCode` | 股票代码 | 否 | 缺失则丢弃该行 |
| `latestPrice` | 最新价（盘后口径） | 是 | 缺失显示 `--` |
| `changePct` | 涨跌幅 | 是 | 缺失显示 `--` |
| `sectorName` | 行业/题材名 | 是 | 缺失显示 `--` |
| `openTimes` | 开板次数 | 是 | 缺失显示 `--` |
| `currentStreakLevel` | 当前板数 | 否 | 可为 `0`（已掉队） |
| `advanced` | 是否晋级成功 | 否 | `true/false` |

---

## 6. 数据来源与字段映射（你关心的重点）

> 口径声明：本章是“连板天梯模块字段真值表”，只约束连板天梯自身字段；不承担其它模块字段定义。

## 6.1 来源表

1. `core_serving.trade_calendar`
2. `core_serving.equity_limit_list`
3. `core_serving.equity_daily_bar`（仅用于补齐当日行情展示列，不参与板数判定）

## 6.2 字段映射总表

| 目标字段 | 主来源 | 列 | 规则 |
|---|---|---|---|
| `tradeDate` | `trade_calendar` | `trade_date` | 由请求日或系统期望交易日确定 |
| `prevTradeDate` | `trade_calendar` | `prev_trade_date` | 与 `tradeDate` 同市场口径 |
| `stockCode` | `equity_limit_list` | `ts_code` | 原样 |
| `stockName` | `equity_limit_list` | `name` | 原样 |
| `currentStreakLevel` | `equity_limit_list` | `limit_times` | 解析为正整数；失败剔除 |
| `openTimes` | `equity_limit_list` | `open_times` | 原样 |
| `latestPrice` | `equity_limit_list` | `close` | 缺失可回退 `equity_daily_bar.close` |
| `changePct` | `equity_limit_list` | `pct_chg` | 缺失可回退 `equity_daily_bar.pct_chg` |
| `sectorName` | `equity_limit_list` | `industry` | 原样，缺失可空 |

补充：

1. `equity_limit_list` 只取 `limit_type='U'`（涨停池）。
2. `equity_daily_bar` 仅做展示补列，不可用于推导板数或晋级。
3. 若其它模块也使用 `equity_limit_list`，那属于“共享来源”关系，不构成与连板天梯的数据耦合。

## 6.3 组合规则（如何组合）

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
6. 构建 `firstBoard`：
   - 当日 `currentStreakLevel=1` 全量股票。

---

## 7. 状态语义

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
   - 展示补列存在缺失但主结构可展示。

---

## 8. 异常语义

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

## 9. API 契约（需求层）

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

## 10. 验收标准

1. 必须能渲染 v5 三类层级：五板以上、晋级层、首板。
2. 晋级层必须满足“左侧昨日全量、右侧今日晋级子集”。
3. `advanced` 标记与交集判定一致。
4. `currentStreakLevel` 对掉队股票可为 `0`。
5. 状态与异常必须能解释源落后、无数据、无效板数三类关键场景。

---

## 11. 已确认项

1. 采用 v5 分层模型，不回退旧五桶静态模型。
2. 连板板数判定只认 `equity_limit_list.limit_times`。
3. `equity_daily_bar` 只用于补行情显示列，不参与层级判定。
4. 本期无待拍板项。

---

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 按最新版 UI（v5）重写：统一分层模型、来源表映射、跨日组合规则 | Codex |
