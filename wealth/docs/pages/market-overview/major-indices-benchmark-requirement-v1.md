# 市场总览｜主要指数标杆需求 v1（benchmark-requirement）

> 用途：定义“主要指数”模块的业务边界、配置边界与展示边界。  
> 阶段：需求冻结前。  
> 产物性质：业务规则事实源（不是实现细节文档）。

关联文档：

1. [主要指数技术实施方案 v1（仅方案）](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/major-indices-implementation-design-v1.md)
2. [主要指数 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/major-indices-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：稳定输出市场总览右侧“主要指数 2x5 卡片”数据，保证数量固定与可配置名单并存。
2. 用户价值：用户持续看到同一形态的 10 指数快照，且指数组成可由后端配置调整。
3. 业务定位：市场总览首屏核心行情模块之一，提供指数客观事实，不提供策略建议。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 主要指数模块数据对象与接口契约。
2. 指数卡片数量固定为 10（2 行 × 5 列）。
3. 指数名单（具体 10 个 code）后端可配置。
4. 模块级状态（debug）与页面状态联动规则。
5. 主要指数使用真实 API 时，前端必须遵循：返回前 `loading`、成功 `ready`、失败/超时 `error`，且不得回填 mock 数据冒充 ready。

### 2.2 本期不覆盖

1. 指数详情页及跳转后页面实现。
2. 顶部 ticker 条实时刷新策略优化。
3. 指数数量动态扩缩容（本期禁止）。
4. 任何 UI 样式与交互改造。

### 2.3 与其他模块边界

1. 上游依赖：`core_serving.index_daily_serving`、`core_serving.index_basic`、`core_serving.trade_calendar`。
2. 下游消费者：市场总览前端 `MajorIndexPanel`。
3. 与相邻模块职责分割：
   - 本模块只负责指数卡片事实输出；
   - 不负责 market summary 文案拼装；
   - 不负责榜单、板块、资金流模块事实。

---

## 3. 核心原则（硬约束）

1. 数量固定：永远返回 10 张卡片（缺数据时允许空位但数量不变）。
2. 名单可配：10 个指数 code 由后端配置定义与排序，前端不硬编码指数列表。
3. UI 不变：保持现有样式、间距、字号、交互，不做任何视觉变更。
4. 状态可观测：真实源加载态可见、超时可见，默认超时阈值 5 秒。

禁止事项：

1. 前端按本地常量生成指数名单；
2. 后端返回非 10 条导致布局漂移；
3. 擅自改 `2x5` 布局语义。
4. 真实源未返回时展示 mock 指数数据。

---

## 4. 业务对象模型（非代码，先语义）

1. `MajorIndicesDefinition`：指数名单定义（固定 10 条 code，含排序）。
2. `MajorIndexRow`：单指数卡片事实。
3. `MajorIndicesPanel`：模块返回对象（含 tradeDate 与 rows）。

字段语义要求：

| 对象 | 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|---|
| `MajorIndicesDefinition` | `definitionKey` | 指数名单定义主键 | - | 否 | 后端 | 缺失即异常 |
| `MajorIndicesDefinition` | `indexCodes` | 指数代码列表，长度固定 10 | - | 否 | 后端 | 非 10 条即异常 |
| `MajorIndexRow` | `subject` | 主体标识（index） | - | 否 | 后端 | 名称缺失则仅显示 code |
| `MajorIndexRow` | `point` | 最新点位 | 点 | 是 | 后端 | 缺失展示 `--` |
| `MajorIndexRow` | `change` | 涨跌点 | 点 | 是 | 后端 | 缺失展示 `--` |
| `MajorIndexRow` | `changePct` | 涨跌幅 | % | 是 | 后端 | 缺失展示 `--` |
| `MajorIndexRow` | `direction` | 涨跌方向 | - | 否 | 后端 | `UNKNOWN` 中性展示 |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| 指数代码 | `core_serving.index_daily_serving` | `ts_code` | 原样 | 必须命中配置名单 |
| 指数名称 | `core_serving.index_basic` | `name` | 按 `ts_code` 关联 | 缺失可空 |
| 最新点位 | `core_serving.index_daily_serving` | `close` | 数值原样 | - |
| 涨跌点 | `core_serving.index_daily_serving` | `change_amount`/`change` | 统一为 `change` | 字段差异在查询层统一 |
| 涨跌幅 | `core_serving.index_daily_serving` | `pct_chg` | 数值原样 | % 值 |
| 成交额 | `core_serving.index_daily_serving` | `amount` | 数值原样 | 可选显示 |
| 交易日 | `core_serving.trade_calendar` | `trade_date` | date -> `YYYY-MM-DD` | 模块观测日期 |

补充：

1. 来源优先级：单源 `index_daily_serving`，不做多源竞态。
2. 回退策略：不做跨日强回补；数据滞后时标记 delayed。
3. 时效语义：盘后快照语义（非实时流）。

---

## 6. 状态语义

1. 页面级状态：`READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. 模块级状态（debug）：返回 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. delayed 判定：`observedTradeDate < expectedTradeDate`。
4. partial 判定：模块有缺失但其余模块可用时页面 `PARTIAL`。
5. 模块加载态（前端渲染态）：
   - `loading`：真实 API 请求未返回，展示 loading 样式；
   - `ready`：真实 API 返回并完成 10 卡渲染；
   - `error`：请求失败或超过 5 秒未返回，展示 error 样式。

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

1. 接口路径：`GET /api/v1/wealth/market/major-indices`。
2. 请求参数：`market/tradeDate/debug`。
3. 响应结构：`tradingDay + pageStatus + majorIndices + debugInfo?`。
4. 字段命名规则：lowerCamelCase + `SubjectRef`。
5. 向后兼容策略：新增字段只做可选扩展，不改既有语义。

---

## 9. 验收标准

1. 功能验收：任意请求均返回固定 10 卡结构（允许单卡空值）。
2. 语义验收：指数名单由后端配置驱动，前端零配置。
3. 状态验收：模块级 delayed/empty 可在 debug 追因。
4. 异常验收：仅使用注册表异常码。
5. 行为验收：真实 API 未返回前不展示 mock；5 秒超时进入 error。

---

## 10. 已确认清零项

1. 指数卡片数量固定为 10，不做可配置数量。
2. 指数 code 名单后端可配置，前端不做名单逻辑。
3. UI 交互与样式保持当前实现，不做任何变化。
4. 本轮无未决拍板项。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结主要指数模块边界（10 固定、名单可配、UI 不变） | Codex |
