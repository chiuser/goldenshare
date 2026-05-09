# 市场总览｜涨跌分布标杆需求 v1（benchmark-requirement）

> 用途：定义“涨跌分布”模块的业务边界与固定规则。  
> 阶段：需求冻结前。  
> 产物性质：业务规则事实源（不是实现细节文档）。

关联文档：

1. [涨跌分布技术实施方案 v1（仅方案）](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-implementation-design-v1.md)
2. [涨跌分布 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：输出“上涨/下跌/平盘家数 + 近 1 月/3 月上涨下跌趋势线”的客观事实。
2. 用户价值：用户快速判断当日市场广度与近阶段赚钱效应变化。
3. 业务定位：市场总览首屏核心模块，提供客观统计，不输出主观建议。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 指标卡：上涨家数、下跌家数、平盘家数（分别展示红盘率/绿盘率/平盘率）。
2. 历史趋势：仅两条线（上涨家数、下跌家数），时间范围固定 `1个月`、`3个月`。
3. 模块级 debug 状态（仅调试模式）。

### 2.2 本期不覆盖

1. 不做涨跌幅区间柱状分布图。
2. 不做可配置时间范围。
3. 不做前端样式/交互改造。

### 2.3 与其他模块边界

1. 上游依赖：`core_serving.equity_daily_bar`、`core_serving.trade_calendar`。
2. 下游消费者：`MarketBreadthPanel`。
3. 职责分割：
   - 本模块只负责涨跌广度事实；
   - 不负责市场风格、成交额、资金流或榜单逻辑。

---

## 3. 核心原则（硬约束）

1. 无配置能力：本模块不接入策略配置中心，不读取任何模块策略配置文件。
2. 固定时间范围：仅支持 `1个月` 与 `3个月`。
3. UI 不变：保持当前页面结构和交互（RangeSwitch + 双折线 + 3 卡片）不变。
4. 图表纵轴冻结：纵轴从 `0` 开始，固定刻度值为 `0/1500/3000/4500/6000`。
4. 统计口径冻结：基于 `core_serving.equity_daily_bar` 当日全量样本直接计数；不额外过滤 ST/停牌特例；`pct_chg` 为空不计入上/下/平计数。

禁止事项：

1. 临时增加 `6个月`、`12个月` 等范围；
2. 变更为多图表组合；
3. 前端自行计算涨跌家数。

---

## 4. 业务对象模型（非代码，先语义）

1. `MarketBreadthPanel`：涨跌分布模块返回根对象。
2. `BreadthMetrics`：当日核心指标。
3. `BreadthHistoryPoint`：历史趋势点（仅上/下家数）。

字段语义要求：

| 对象 | 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|---|
| `MarketBreadthPanel` | `tradeDate` | 模块观测交易日 | - | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `upCount` | 当日上涨家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `downCount` | 当日下跌家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `flatCount` | 当日平盘家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `redRate` | 红盘率 = up / (up+down+flat) | % | 否 | 后端 | 缺失即异常 |
| `MarketBreadthPanel` | `historyByRange` | 各时间范围趋势点 | - | 否 | 后端 | 空数组 + 模块 empty |
| `BreadthHistoryPoint` | `tradeDate` | 历史交易日 | - | 否 | 后端 | 丢弃异常点 |
| `BreadthHistoryPoint` | `upCount` | 当日上涨家数 | 家 | 否 | 后端 | 丢弃异常点 |
| `BreadthHistoryPoint` | `downCount` | 当日下跌家数 | 家 | 否 | 后端 | 丢弃异常点 |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| `tradeDate` | `core_serving.trade_calendar` | `trade_date` | date -> `YYYY-MM-DD` | 取目标交易日 |
| `upCount` | `core_serving.equity_daily_bar` | `pct_chg` | `pct_chg > 0` 计数 | 按目标交易日 |
| `downCount` | `core_serving.equity_daily_bar` | `pct_chg` | `pct_chg < 0` 计数 | 按目标交易日 |
| `flatCount` | `core_serving.equity_daily_bar` | `pct_chg` | `pct_chg = 0` 计数 | 按目标交易日 |
| `historyByRange[*].upCount` | `core_serving.equity_daily_bar` | `pct_chg` | 按交易日聚合 `pct_chg>0` | 22/62 交易日 |
| `historyByRange[*].downCount` | `core_serving.equity_daily_bar` | `pct_chg` | 按交易日聚合 `pct_chg<0` | 22/62 交易日 |

补充：

1. 来源优先级：单源 `equity_daily_bar`。
2. 回退策略：不跨日补值；数据落后时标记 delayed。
3. 时效语义：盘后快照语义（非实时流）。
4. 计数细则：仅对 `pct_chg is not null` 的样本参与计数，`pct_chg is null` 直接排除。

---

## 6. 状态语义

1. 页面级状态：`READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. 模块级状态（debug）：返回 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. delayed 判定：`observedTradeDate < expectedTradeDate`。
4. partial 判定：本模块 delayed/empty 且其他模块可用。

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

1. 接口路径：`GET /api/v1/wealth/market/breadth`。
2. 请求参数：`market/tradeDate/debug`。
3. 响应结构：`tradingDay + pageStatus + breadth + debugInfo?`。
4. 字段命名规则：lowerCamelCase + 语义化字段。
5. 向后兼容策略：只增不改；不改现有字段语义。

---

## 9. 验收标准

1. 功能验收：返回当日 3 指标 + `1个月/3个月` 双范围趋势数据。
2. 语义验收：历史趋势只展示上涨家数、下跌家数，不返回平盘趋势线。
3. 状态验收：debug 可见模块 delayed/empty/error 追因。
4. 异常验收：仅使用注册表异常码。
5. 展示验收：平盘家数卡片副文案必须展示 `平盘率 x%`，不得展示“当前日统计”。
6. 图表验收：纵轴刻度必须为 `0/1500/3000/4500/6000`，不得出现负值刻度。

---

## 10. 已确认清零项

1. 本模块不做配置化能力。
2. 时间范围固定 `1个月/3个月`。
3. 保持当前页面样式与交互不变。
4. 统计口径已拍板：`equity_daily_bar` 全量样本口径，`pct_chg` 为空不计入。
5. 本模块接入真实 API 时，必须遵守 `loading -> ready`、`timeout(5s) -> error`，且 timeout/error 不允许回填 mock 数据。
6. 本轮仅允许 `breadth` 模块 source 从 `mock` 切到 `real`，其余模块 source 必须保持原值不变。
7. 本轮无未决拍板项。
8. 平盘家数卡片副文案统一为 `平盘率 x%`。
9. 纵轴刻度固定为 `0/1500/3000/4500/6000`。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结涨跌分布模块边界（无配置、固定范围、UI 不变） | Codex |
| v1.1 | 2026-05-09 | 对齐模块交付清单：补充真实源 loading/error 门禁与模块 source 单模块切换约束 | Codex |
| v1.2 | 2026-05-09 | 对齐实现修复：平盘卡副文案改为平盘率；纵轴刻度固定为 0/1500/3000/4500/6000 | Codex |
