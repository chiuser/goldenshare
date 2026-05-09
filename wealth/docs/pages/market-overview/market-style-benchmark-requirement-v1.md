# 市场总览｜市场风格标杆需求 v1（benchmark-requirement）

> 用途：定义“市场风格”模块的业务边界、配置边界与统计口径。  
> 阶段：需求冻结前。  
> 产物性质：业务规则事实源（不是实现细节文档）。

关联文档：

1. [市场风格技术实施方案 v1（仅方案）](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-style-implementation-design-v1.md)
2. [市场风格 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-style-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：输出“市场风格”3 张事实卡片与 3 条历史趋势线（大盘、小盘、涨跌中位数）。
2. 用户价值：用户快速判断当前日“权重风格 vs 小盘风格”的客观强弱。
3. 业务定位：市场总览首屏核心模块之一，只给事实，不给主观判断。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 三张卡片：大盘股平均涨跌幅 / 小盘股平均涨跌幅 / 涨跌中位数。
2. 历史趋势：固定 `1个月`、`3个月` 两档，三线同图（大盘、小盘、中位数）。
3. 三张卡片的数据源配置化（通过策略配置中心统一读取）。
4. 模块级 debug 状态（仅调试模式）。

### 2.2 本期不覆盖

1. 不做“等权平均涨跌幅”卡片。
2. 不输出“风格领先方向”主观标签。
3. 不做前端样式和交互改造。

### 2.3 与其他模块边界

1. 上游依赖：`core_serving.index_daily_serving`、`core_serving.equity_daily_bar`、`core_serving.trade_calendar`。
2. 下游消费者：`MarketStylePanel`。
3. 职责分割：
   - 本模块只负责风格事实统计；
   - 不负责涨跌家数、成交额、资金流、榜单逻辑。

---

## 3. 核心原则（硬约束）

1. 三卡固定：卡片数量固定 3，顺序固定（大盘 -> 小盘 -> 涨跌中位数）。
2. 数据源可配：三卡数据源从后端策略配置读取，前端不硬编码来源。
3. 中位数定义固定：  
   把“全市场 A 股样本”的 `pct_chg` 按升序排序，取**中间那只股票**的涨跌幅作为“涨跌中位数”，不使用插值中位数。
4. UI 不变：保持当前页面样式、间距、交互不变（含 `1个月/3个月` 切换）。

禁止事项：

1. 前端自行计算风格数据；
2. 使用 `percentile_cont`（插值）替代离散中位；
3. 在模块里输出买卖建议或风格预测。

---

## 4. 业务对象模型（非代码，先语义）

1. `MarketStyleDefinition`：市场风格模块配置定义（含 3 卡数据源策略）。
2. `MarketStylePanel`：模块返回根对象。
3. `MarketStyleCard`：单卡对象（3 张固定）。
4. `MarketStyleHistoryPoint`：历史趋势点（每个交易日 3 个值）。

字段语义要求：

| 对象 | 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|---|
| `MarketStyleDefinition` | `definitionKey` | 模块配置主键 | - | 否 | 后端 | 缺失即异常 |
| `MarketStyleDefinition` | `cardSources` | 3 卡数据源定义 | - | 否 | 后端 | 非法即异常 |
| `MarketStyleCard` | `cardKey` | 卡片主键（large/small/median） | - | 否 | 后端 | 缺失即异常 |
| `MarketStyleCard` | `label` | 卡片标题 | - | 否 | 后端 | 缺失即异常 |
| `MarketStyleCard` | `valuePct` | 当前日值 | % | 是 | 后端 | 缺失显示 `--` |
| `MarketStyleCard` | `sourceText` | 来源说明（如沪深300口径） | - | 否 | 后端 | 缺失即异常 |
| `MarketStyleHistoryPoint` | `tradeDate` | 历史交易日 | - | 否 | 后端 | 异常点丢弃 |
| `MarketStyleHistoryPoint` | `largePct` | 大盘值 | % | 是 | 后端 | 缺失则点位可空 |
| `MarketStyleHistoryPoint` | `smallPct` | 小盘值 | % | 是 | 后端 | 缺失则点位可空 |
| `MarketStyleHistoryPoint` | `medianPct` | 中位数值 | % | 是 | 后端 | 缺失则点位可空 |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| 大盘股平均涨跌幅 | `core_serving.index_daily_serving` | `pct_chg` | 按配置 `indexCode`（默认 `000300.SH`）取值 | 来源可配置 |
| 小盘股平均涨跌幅 | `core_serving.index_daily_serving` | `pct_chg` | 按配置 `indexCode`（默认 `000852.SH`）取值 | 来源可配置 |
| 涨跌中位数 | `core_serving.equity_daily_bar` | `pct_chg` | `percentile_disc(0.5) within group (order by pct_chg)` | 全市场 A 股样本 |
| 历史交易日 | `core_serving.trade_calendar` | `trade_date` | 按 range 取最近 22/62 个交易日 | 1个月/3个月 |

补充：

1. 来源优先级：单源（指数来自 `index_daily_serving`，中位数来自 `equity_daily_bar`）。
2. 回退策略：不做跨日补值；数据滞后时标记 delayed。
3. 数据时效语义：盘后快照语义（非实时流）。

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

1. 接口路径：`GET /api/v1/wealth/market/style`。
2. 请求参数：`market/tradeDate/debug`。
3. 响应结构：`tradingDay + pageStatus + style + debugInfo?`。
4. 字段命名规则：lowerCamelCase + 语义化字段。
5. 向后兼容策略：只增不改，不改既有字段语义。

---

## 9. 验收标准

1. 功能验收：返回 3 张固定卡片 + `1个月/3个月` 历史三线数据。
2. 语义验收：中位数必须来自“中间那只股票”的离散中位，不是均值中位。
3. 配置验收：三卡来源由后端策略配置驱动，前端不持有来源逻辑。
4. 状态验收：debug 可追因 delayed/empty/error。

---

## 10. 已确认清零项

1. 三卡数据源配置化能力必须支持。
2. 大盘默认 `沪深300`，小盘默认 `中证1000`，但都可在配置中调整。
3. 涨跌中位数定义固定为“全市场 A 股排序后中间那只股票的涨跌幅”。
4. UI 样式与交互保持现状，不做任何变化。
5. 本轮无未决拍板项。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结市场风格模块边界（三卡来源可配 + 离散中位数） | Codex |
