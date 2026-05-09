# 市场总览｜成交额总览标杆需求 v1（benchmark-requirement）

> 用途：定义“成交额总览”模块的业务边界、统计口径与配置边界。  
> 阶段：需求冻结前。  
> 产物性质：业务规则事实源（不是实现细节文档）。

关联文档：

1. [成交额总览技术实施方案 v1（仅方案）](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-implementation-design-v1.md)
2. [成交额总览 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：输出“今日成交总额 + 对比 + 历史趋势”的客观事实。
2. 用户价值：用户快速判断市场活跃度是否放大或收缩。
3. 业务定位：市场总览首屏核心模块之一，只给事实，不给主观判断。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 四个统计卡：
   - 今日成交总额
   - 较上一交易日变化额/变化率
   - 上一交易日成交额
   - 5日均值（附 20 日指标）
2. 两张图：
   - 当日累计成交额（盘中时段）
   - 历史成交额趋势（`1个月` / `3个月`）
3. 模块级 debug 状态（仅调试模式）。

### 2.2 本期不覆盖

1. 不做成交额预测。
2. 不做成交额异动预警策略。
3. 不做前端样式和交互改造。

### 2.3 与其他模块边界

1. 上游依赖：`core_serving.equity_daily_bar`、`core_serving.trade_calendar`、`raw_tushare.stk_mins`（用于日内曲线）。
2. 下游消费者：`TurnoverPanel`。
3. 职责分割：
   - 本模块只负责成交额事实；
   - 不负责资金流、涨跌分布、市场风格、榜单逻辑。

---

## 3. 核心原则（硬约束）

1. 四卡固定：卡片数量固定 4，顺序固定，不做动态增减。
2. 时间范围固定：历史图只支持 `1个月`、`3个月`。
3. UI 不变：保持现有页面样式、布局、交互不变。
4. 盘后语义：当前系统无实时流，展示的是已落库事实；若当日未落库则按 delayed/empty 处理。
5. 真实源优先：模块切 real API 后，数据未返回前显示 `loading`，不得展示 mock 数据冒充 ready。
6. 超时显式失败：请求超过 5 秒必须进入 `error`，不得静默回退 mock。
7. 模块级渐进替换：本轮只允许 `turnover` 模块 source 从 `mock` 切到 `real`，其他模块 source 不变。
8. 说明文案约束：图下“横轴/纵轴解释”等说明文案默认不常驻，仅在需求明确要求时展示。

禁止事项：

1. 前端自行聚合成交额；
2. 用主观文案替代事实数值；
3. 额外增加计划外时间维度。

---

## 4. 业务对象模型（非代码，先语义）

1. `TurnoverPanel`：模块返回根对象。
2. `TurnoverMetrics`：4 卡统计对象。
3. `TurnoverIntradayPoint`：日内累计曲线点。
4. `TurnoverHistoryPoint`：历史趋势点。

字段语义要求：

| 对象 | 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|---|
| `TurnoverPanel` | `tradeDate` | 模块观测交易日 | - | 否 | 后端 | 缺失即异常 |
| `TurnoverMetrics` | `todayAmount` | 今日总成交额 | 元 | 是 | 后端 | 缺失显示 `--` |
| `TurnoverMetrics` | `prevAmount` | 上一交易日总成交额 | 元 | 是 | 后端 | 缺失显示 `--` |
| `TurnoverMetrics` | `amountDelta` | 与上一交易日差额 | 元 | 是 | 后端 | 缺失显示 `--` |
| `TurnoverMetrics` | `amountDeltaPct` | 与上一交易日差额比例 | % | 是 | 后端 | 缺失显示 `--` |
| `TurnoverMetrics` | `avg5dAmount` | 5 日均值 | 元 | 是 | 后端 | 缺失显示 `--` |
| `TurnoverMetrics` | `avg20dAmount` | 20 日均值（或口径项） | 元 | 是 | 后端 | 缺失显示 `--` |
| `TurnoverIntradayPoint` | `time` | 时点（HH:mm） | - | 否 | 后端 | 异常点丢弃 |
| `TurnoverIntradayPoint` | `cumAmount` | 累计成交额 | 元 | 是 | 后端 | 可空点位 |
| `TurnoverHistoryPoint` | `tradeDate` | 历史交易日 | - | 否 | 后端 | 异常点丢弃 |
| `TurnoverHistoryPoint` | `amount` | 当日总成交额 | 元 | 是 | 后端 | 可空点位 |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| 今日成交总额 | `core_serving.equity_daily_bar` | `amount` | 当日全市场 `sum(amount)` | 源口径聚合 |
| 上一交易日成交总额 | `core_serving.equity_daily_bar` | `amount` | 上一交易日全市场 `sum(amount)` | 源口径聚合 |
| 5日均值/20日指标 | `core_serving.equity_daily_bar` | `amount` | 最近 5/20 交易日均值聚合 | 固定为均值 |
| 历史趋势 | `core_serving.equity_daily_bar` | `amount` | 最近 22/62 交易日逐日 `sum(amount)` | 1个月/3个月 |
| 当日累计成交额曲线 | `raw_tushare.stk_mins` | `amount,trade_time,freq` | 当日按 `freq=30`、`trade_time` 聚合后做累计（5点） | 固定启用 |

补充：

1. 来源优先级：`equity_daily_bar` 为主源；`stk_mins` 仅用于日内曲线。
2. 回退策略：不跨日补值；若日内曲线缺失，模块状态可 `PARTIAL`。
3. 数据时效语义：盘后快照语义（非实时流）。

---

## 6. 状态语义

1. 页面级状态：`READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. 模块级状态（debug）：返回 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. delayed 判定：`observedTradeDate < expectedTradeDate`。
4. partial 判定：核心四卡有值但日内曲线缺失，或历史部分缺失。

---

## 7. 异常语义

1. 异常对象结构：`module/code/severity/message/details`。
2. 用户可见策略：正式态不展示异常码。
3. debug 可见策略：`debug=1` 返回模块异常明细（生产禁用）。

异常码要求：

1. 必须登记到 [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)。
2. 未登记异常码禁止进入代码与 API 契约。

---

## 8. API 契约（需求层）

1. 接口路径：`GET /api/v1/wealth/market/turnover`。
2. 请求参数：`market/tradeDate/debug`。
3. 响应结构：`tradingDay + pageStatus + turnover + debugInfo?`。
4. 字段命名规则：lowerCamelCase + 语义化字段。
5. 向后兼容策略：只增不改，不改既有字段语义。

---

## 9. 验收标准

1. 功能验收：返回 4 卡统计 + 30min 日内累计 5 点曲线 + 历史趋势（1个月/3个月）。
2. 语义验收：所有指标均为客观事实，不包含预测与建议。
3. 状态验收：debug 可追因 delayed/partial/empty/error。
4. 异常验收：仅使用注册表异常码。
5. 行为验收：真实源请求 pending 时显示 loading（不展示 mock turnover）。
6. 行为验收：真实源请求超过 5 秒显示 error（不回填 mock turnover）。
7. 范围验收：本轮仅 `turnover` 模块 source 变化，其余模块 source 保持不变。
8. 展示验收：不新增常驻图下注释（除非后续需求文档明确新增）。

---

## 10. 已确认清零项

1. `avg20dAmount` 口径固定为 20 日均值。
2. 日内累计曲线固定启用 `raw_tushare.stk_mins`。
3. 日内累计曲线固定使用 `freq=30`，输出 5 个坐标点。
4. UI 样式与交互保持现状，不做任何变化。
5. 本轮无未决拍板项。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结成交额总览模块边界（4卡 + 两图 + 固定范围） | Codex |
| v1.1 | 2026-05-08 | 拍板落定：20日均值 + 30min 5点日内累计曲线 | Codex |
