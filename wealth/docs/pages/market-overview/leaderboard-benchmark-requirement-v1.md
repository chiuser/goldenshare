# 市场总览｜榜单标杆需求 v1（benchmark-requirement）

> 用途：定义榜单模块业务事实源与边界。  
> 阶段：需求冻结前。  
> 产物性质：业务规则事实源（不是实现细节文档）。

关联文档：

1. [榜单标杆技术实施方案 v1（仅方案）](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/leaderboard-implementation-design-v1.md)
2. [榜单 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/leaderboard-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：把“榜单速览”做成前后端贯通标杆，确保规则后端统一定义，前端只渲染。
2. 用户价值：用户看到稳定、可解释、可追踪的榜单数据，不再出现口径漂移和“前端二次加工”。
3. 业务定位：市场总览首页的核心事实模块之一，不提供主观推荐，不承担选股策略功能。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 市场总览页榜单速览模块。
2. 7 个榜单：`gainers/losers/amount/turnover/volumeRatio/popularity/surge`。
3. 模块级状态（debug）与页面级状态（正式态）联动规则。
4. 模块异常语义（仅榜单试点）。

### 2.2 本期不覆盖

1. 审计中心功能开发与页面交互。
2. 非市场总览页面的榜单系统。
3. 主观推荐、仓位建议、明日预测。
4. 其他模块（连板天梯、板块速览等）的异常码落地。

### 2.3 与其他模块边界

1. 上游依赖：`trade_calendar`、`equity_daily_bar`、`equity_daily_basic`、`dc_hot`、`security_serving`。
2. 下游消费者：市场总览前端榜单区域（以及后续 overview 聚合接口）。
3. 与相邻模块分割：榜单只负责榜单行数据与榜单状态，不负责整页聚合、不负责指数区与板块区事实拼装。

---

## 3. 核心原则（硬约束）

1. 规则归属：榜单规则（股票池、排序、回退）由后端定义，前端不决策。
2. 契约归属：本文件是榜单需求事实源；实现细节在 implementation-design；编码门禁在 coding-gate。
3. 禁止事项：
   - 前端手工重排榜单或重建股票池；
   - 裸 `code` 作为主体标识；
   - 未登记异常码进入接口。
4. 行为门禁：
   - 真实 API 未返回前，模块必须显示 `loading`；
   - 禁止用 mock 榜单冒充 ready；
   - 请求超过 5 秒必须进入 `error`。
5. 渐进替换门禁：本轮只允许 `leaderboards` 模块 source 从 `mock -> real`，其他模块 source 必须保持不变。
6. 配置语义：本期榜单规则由后端策略配置中心读取（`leaderboard.cn_a.v1.json`），前端不暴露 `boardKeys` 自定义能力。

---

## 4. 业务对象模型（非代码，先语义）

1. `LeaderboardDefinition`：榜单定义对象（榜单 key、展示名、排序策略、列定义）。
2. `LeaderboardBoard`：单个榜单运行结果（状态、观测日期、榜单行）。
3. `LeaderboardRow`：榜单行对象（主体 + 指标列）。

字段语义要求（适用于核心字段）：

1. 含义：字段必须有业务定义，不允许“仅为了前端展示临时拼字段”。
2. 单位：金额、成交量、百分比必须明确单位和精度。
3. 可空：明确可空策略（例如 `subjectName` 可空）。
4. 产出责任：后端负责数据事实，前端负责显示格式化。
5. 缺失降级：缺名称时前端显示代码；缺指标时按契约返回空值并标注状态/异常。

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| 榜单主体代码 | `core_serving.equity_daily_bar` / `core_serving.dc_hot` | `ts_code` | 原样 | 主体键 |
| 榜单主体名称 | `core_serving.dc_hot` / `core_serving.security_serving` | `ts_name` / `name` | `COALESCE` | 缺失允许空名 |
| 最新价 | `equity_daily_bar` / `dc_hot` | `close` / `current_price` | 数值原样 | 按数据族 |
| 涨跌幅 | `equity_daily_bar` / `dc_hot` | `pct_chg` / `pct_change` | 数值原样 | 百分比 |
| 换手率 | `equity_daily_basic` | `turnover_rate` | 左连接补列 | `turnover` 榜核心 |
| 量比 | `equity_daily_basic` | `volume_ratio` | 左连接补列 | `volumeRatio` 榜核心 |
| 成交量 | `equity_daily_bar` | `vol` | 数值原样 | `amount/turnover` 补充列 |
| 成交额 | `equity_daily_bar` | `amount` | 数值原样 | `amount` 榜核心 |
| 热榜名次 | `dc_hot` | `rank` | 数值原样 | `popularity/surge` |
| 热榜更新时间 | `dc_hot` | `rank_time` | 时间原样 | rank 并列/空值时排序兜底 |

补充：

1. 来源优先级：行情榜主源 `equity_daily_bar`，热榜主源 `dc_hot`。
2. 回退策略：仅 `dc_hot` 有 strict/fallback 双模式。
3. 数据时效语义：盘后快照语义（非实时流）。
4. 股票池边界（CN_A）：
   - 必须满足 `security_type='stock'`；
   - 必须满足 `list_status='L'`；
   - 必须满足 `list_date <= trade_date` 且 `(delist_date IS NULL OR delist_date > trade_date)`；
   - 必须过滤 ST（名称含 `ST` 或 `*ST`）；
   - 停牌标的不应入榜（当日无有效成交行情数据时自然排除）。
5. `dc_hot` 过滤与排序边界（人气榜/飙升榜）：
   - 过滤：`query_market='A股市场'`；
   - 说明：`data_type` 在线上当前是市场标签（如 `A股市场/ETF基金/港股市场`），不是 `stock/index` 语义字段，本期不作为独立业务过滤条件；
   - 排序：`rank` 非空优先、`rank` 升序、`rank_time` 非空优先、`rank_time` 新到旧、`ts_code` 兜底；
   - 异常剔除：`rank` 与 `rank_time` 同时无效（空值）直接剔除，不进入榜单 rows。
6. `dc_hot` 参数口径门禁（防止本地通过线上空榜）：
   - 开发前必须先做源表枚举审计（`trade_date/query_hot_type/query_market/data_type`）；
   - 测试 fixture 必须复用线上实值口径（`A股市场`），禁止写概念化别名（如 `A股`、`stock`）冒充真实值；
   - 若源端枚举发生变化，先更新三件套，再改代码。

---

## 6. 状态语义

1. 页面级状态（正式态）：`READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. 模块级状态（debug）：每榜单提供 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. delayed 判定：`observedTradeDate < expectedTradeDate`。
4. partial 判定：存在模块 `DELAYED/EMPTY/ERROR` 但非全量同态。
5. loading/error 行为：
   - 真实源 pending -> `loading`
   - 真实源超时（5 秒）或失败 -> `error`

---

## 7. 异常语义

1. 异常对象结构：`moduleKey/code/severity/message/details`。
2. 用户可见策略：正式页面不直接展示异常码。
3. debug 可见策略：`debug=1` 返回模块异常明细用于排障。

异常码要求：

1. 必须登记到 [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)。
2. 未登记异常码禁止进入 API 契约和代码实现。

---

## 8. API 契约（需求层）

1. 接口路径：`GET /api/v1/wealth/market/leaderboards`。
2. 请求参数：`market/tradeDate/limit/debug`。
3. 榜单集合来源：`boardKeys` 仅来自策略配置中心（`payload.boardKeys`），不作为用户可控请求参数。
4. 响应结构：`tradingDay + pageStatus + definitions + boards + debugInfo?`。
5. 字段命名规则：lowerCamelCase；主体使用 `subjectType/subjectCode/subjectName`。
6. 向后兼容策略：新增字段只加可选；不改既有字段语义。
7. debug 语义：`debug=0`（默认）不返回 `debugInfo`；`debug=1` 才返回模块状态与异常明细。

---

## 9. 验收标准

1. 功能验收：7 榜单全部可返回，定义与数据一致。
2. 语义验收：规则由后端定义，前端仅渲染。
3. 状态验收：页面级与模块级状态规则一致可复现。
4. 异常验收：仅使用已登记异常码，debug 下可追因。
5. 行为验收：真实源 pending 显示 `loading`，且不展示 mock 榜单。
6. 行为验收：真实源请求超过 5 秒显示 `error`，不允许静默回退 mock。
7. 范围验收：本轮仅 `leaderboards` source 变化，其他模块 source 保持不变。
8. 配置验收：
   - 榜单定义必须从策略配置中心读取；
   - `strictHotDate` 默认 `true` 且可通过配置中心修改；
   - `boardKeys` 不允许通过用户请求参数覆盖。

---

## 10. 已确认清零项

1. 本轮无待确认项，已全部拍板完成。
2. 后续若新增榜单类型（如振幅榜），再新增需求文档条目并进入新一轮评审，不在本轮范围。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 按模板重构文档结构，冻结榜单需求边界 | Codex |
| v1.1 | 2026-05-10 | 对齐最新门禁：补充 loading/error/5秒超时行为、单模块切换纪律、debug 默认语义与配置边界 | Codex |
| v1.2 | 2026-05-10 | 对齐拍板口径：启用策略配置中心、冻结 CN_A 股票池过滤规则、移除 boardKeys 对外参数 | Codex |
| v1.3 | 2026-05-10 | 补齐热榜硬约束：补充 `dc_hot` 过滤、rank/rank_time 排序链路与异常值剔除规则 | Codex |
| v1.4 | 2026-05-10 | 修正 `dc_hot` 真实口径：过滤改为 `query_market='A股市场'`，并新增“源表枚举审计 + fixture 实值对齐”硬门禁 | Codex |
