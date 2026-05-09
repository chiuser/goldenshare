# 市场总览｜今日市场客观总结标杆需求 v1（benchmark-requirement）

> 用途：定义“今日市场客观总结”模块的业务边界与事实口径。  
> 阶段：需求冻结前。  
> 产物性质：业务规则事实源（不是实现细节文档）。

关联文档：

1. [今日市场客观总结技术实施方案 v1（仅方案）](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-summary-implementation-design-v1.md)
2. [今日市场客观总结 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-summary-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：把“今日市场客观总结”做成后端配置驱动、前端纯展示的标杆模块。
2. 用户价值：用户在首屏快速看到“客观事实摘要”，不依赖主观解读。
3. 业务定位：市场总览首页左上核心事实模块；不承载交易建议与预测。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 今日市场客观总结模块数据对象定义。
2. 事实卡片数量后端可配置（仅允许 `5` 或 `6`）。
3. 下方文字卡位置固定，但文字内容由后端配置与渲染输出。
4. 模块级状态（debug）与页面级状态联动口径。
5. 当 summary 使用真实 API 时，前端必须遵循：响应返回前显示 loading；超过 5 秒未返回显示 error；不得展示 mock summary 回填。

### 2.2 本期不覆盖

1. 排行榜、板块、连板等其他模块实现细节。
2. 审计中心与任务调度能力开发。
3. 主观观点、仓位建议、明日预测文案。
4. 大模型文案生成或自由生成文本能力。

### 2.3 与其他模块边界

1. 上游依赖：`trade_calendar`、`equity_daily_bar`、`market_moneyflow_dc`、`limit_list_ths`、指数行情模块（用于“主要指数上涨数量”事实）。
2. 下游消费者：市场总览前端 `MarketSummaryPanel`。
3. 与相邻模块职责分割：
   - 本模块只输出“客观总结卡片与文字卡”。
   - 主要指数模块只输出指数卡，不拼装总结文案。
   - 前端不参与事实计算与文案拼接。

---

## 3. 核心原则（硬约束）

1. 规则归属：卡片定义、卡片顺序、卡片数量（5/6）、文案模板均由后端定义。
2. 契约归属：本文件为需求事实源；实现落地见 implementation-design；编码前锁定见 coding-gate。
3. 禁止事项：
   - 前端硬编码“固定 5 卡”或硬编码文案；
   - 前端依据本地规则自行生成客观总结；
   - 真实 API 未返回时用 mock summary 顶替；
   - 后端返回超过 6 卡或少于 5 卡；
   - 文案中出现主观交易建议。

---

## 4. 业务对象模型（非代码，先语义）

1. `MarketSummaryDefinition`：后端配置定义对象。
2. `MarketSummaryCard`：事实卡对象。
3. `MarketSummaryTextCard`：说明文字卡对象（位置固定在卡片区下方，按盘中/盘后模板分版本）。

字段语义（核心）：

| 对象 | 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|---|
| `MarketSummaryDefinition` | `definitionKey` | 配置主键（如 `CN_A_SUMMARY_V1`） | - | 否 | 后端 | 不允许缺失；缺失即异常 |
| `MarketSummaryDefinition` | `cardCount` | 卡片数量，仅 `5/6` | - | 否 | 后端 | 非法值直接异常 |
| `MarketSummaryCard` | `cardKey` | 卡片业务键（唯一） | - | 否 | 后端 | 不允许重复 |
| `MarketSummaryCard` | `label` | 卡片标题 | - | 否 | 后端 | 缺失用 `--` 并记异常 |
| `MarketSummaryCard` | `value` | 主值（数字或复合值） | 视卡片而定 | 是 | 后端 | `null` 时显示 `--` |
| `MarketSummaryCard` | `subText` | 次级描述（如“较昨日：+702亿”） | - | 是 | 后端 | 可空 |
| `MarketSummaryCard` | `direction` | 行情语义方向 | - | 是 | 后端 | 空则中性展示 |
| `MarketSummaryTextCard` | `title` | 文字卡标题/强调前缀 | - | 否 | 后端 | 缺失视为异常 |
| `MarketSummaryTextCard` | `content` | 文字卡正文（客观） | - | 否 | 后端 | 缺失视为空态并标记异常 |

---

## 5. 数据来源与映射（事实层）

> 默认 5 卡来自固定 `cardKey` 集；第 6 卡默认关闭，仅在后端配置显式启用时返回。  
> 前端不关心来源表，只按返回契约渲染。

| `cardKey` | 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|---|
| `majorIndexUpCount` | 主要指数涨跌比 | 指数行情模块聚合结果 | `upCount/totalCount` | 组合为 `upCount:downCount`（如 `2:8`） | 默认卡 |
| `riseFallCount` | 上涨/下跌家数 | `core_serving.equity_daily_bar` | `pct_chg` | `pct_chg>0` 计上涨，`<0` 计下跌，`=0` 计平盘 | 默认卡 |
| `turnoverTotal` | 成交总额 | `core_serving.equity_daily_bar` | `amount` | 按交易日汇总，格式化为“亿” | 默认卡 |
| `marketNetFlow` | 大盘资金净流入/流出 | `core_serving.market_moneyflow_dc` | `net_amount` | 正负决定 `direction` 与“净流入/净流出”文案 | 默认卡 |
| `limitUpDown` | 涨停/跌停及炸板 | `core_serving.limit_list_ths` | `limit_type` | 统计涨停池、跌停池、炸板池（按 `ts_code` 去重） | 默认卡 |
| `flatCount` | 平盘家数 | `core_serving.equity_daily_bar` | `pct_chg` | `pct_chg=0` 计数 | 可选第 6 卡 |

补充：

1. 来源优先级：单一主源，不做多源竞态。
2. 回退策略：任一关键源缺失时，模块可 `PARTIAL/DELAYED`，但不允许前端补算。
3. 时效语义：盘后快照语义（非实时流）。
4. 指数上涨数量口径：本模块独立查询与计算，不复用“主要指数模块内部产物”。

### 5.1 文案模板注册表（冻结）

> 文案由后端模板渲染，不做自由生成。  
> 本表是 `textCard` 的唯一语义源，编码时不得新增“隐式模板”。

| templateKey | 触发条件 | title 模板 | content 模板 |
|---|---|---|---|
| `objective_intraday_v1` | `sessionStatus in {PRE_OPEN,TRADING,BREAK}` | `截至当前时点，A 股主要指数{majorIndexTone}。` | `当前上涨家数{upDownTone}下跌家数，成交活跃度较上一交易日同时段{turnoverTone}；涨停{limitUpDownTone}跌停。大盘资金当前为{fundFlowTone}。以下为客观事实快照，不构成交易建议。` |
| `objective_close_v1` | `sessionStatus == CLOSED` | `截至收盘，A 股主要指数{majorIndexTone}。` | `全市场上涨家数{upDownTone}下跌家数，成交额较上一交易日{turnoverTone}；涨停{limitUpDownTone}跌停。大盘资金今日为{fundFlowTone}，资金分布呈现{flowPatternTone}。本卡片仅描述客观事实，不构成交易建议。` |

### 5.2 模板变量定义（冻结）

| 变量 | 含义 | 来源 | 取值规则 |
|---|---|---|---|
| `majorIndexTone` | 指数整体强弱短语 | 指数上涨数/总数 | `upCount > total/2 => 多数上涨`; `upCount == total/2 => 涨跌分化`; `upCount < total/2 => 多数下跌` |
| `upDownTone` | 上涨家数 vs 下跌家数关系 | `equity_daily_bar` 聚合 | `up > down => 多于`; `up == down => 持平于`; `up < down => 少于` |
| `turnoverTone` | 成交活跃度变化 | `equity_daily_bar.amount` 与前一交易日对比 | `deltaPct >= +1% => 放大`; `-1% < deltaPct < +1% => 基本持平`; `<= -1% => 缩量` |
| `limitUpDownTone` | 涨跌停关系 | `limit_list_ths` 聚合 | `limitUp > limitDown => 家数高于`; `== => 家数接近`; `< => 家数低于` |
| `fundFlowTone` | 主力净流入/流出描述 | `market_moneyflow_dc.net_amount` | `>0 => 净流入`; `=0 => 基本平衡`; `<0 => 净流出` |
| `flowPatternTone` | 资金分布态势 | `market_moneyflow_dc` 分项结构 | 首版固定 `分化`；后续版本再细化，不在 v1 扩散 |

### 5.3 模板渲染硬约束

1. 未识别 `sessionStatus` 时，强制回退 `objective_intraday_v1`。
2. 任一变量缺失时，不抛原始异常给前端：  
   - `title` 回退固定中性文本：`今日市场客观总结`；  
   - `content` 回退固定中性文本：`当前可用数据不足，暂仅展示已确认的客观事实。`
3. 文案禁止词（大小写不敏感）：
   - `买入`、`卖出`、`加仓`、`减仓`、`抄底`、`止盈`、`止损`、`明日`、`预测`
4. 文案长度上限（渲染前）：
   - `title <= 36` 字符
   - `content <= 220` 字符
5. 前端不允许拼接或改写文案，只展示后端返回文本。

---

## 6. 状态语义

1. 页面级状态：`READY/PARTIAL/DELAYED/EMPTY/ERROR`（正式产品态）。
2. 模块级状态（debug）：`moduleStatus` 显示 `expectedTradeDate/observedTradeDate/lagDays/status`。
3. delayed 判定：任一核心来源 `observedTradeDate < expectedTradeDate`。
4. partial 判定：模块非 `READY` 且页面仍有其他模块可用时页面为 `PARTIAL`。
5. 模块加载态（前端渲染态）：
   - `loading`：真实 API 未返回，展示 loading 样式（状态基线第一格）。
   - `error`：真实 API 请求超过 5 秒或请求失败，展示 error 样式（状态基线第三格）。
   - `ready`：真实 API 返回并完成渲染。

---

## 7. 异常语义

1. 异常对象结构：`module/code/severity/message/details`。
2. 用户可见策略：正式态不直接展示异常码。
3. debug 可见策略：`debug=1` 返回模块异常明细。

异常码要求：

1. 必须登记到 [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)。
2. 未登记异常码禁止进入代码与 API 契约。

---

## 8. API 契约（需求层）

1. 模块接口路径：`GET /api/v1/wealth/market/summary`。
2. 请求参数：`market/tradeDate/debug`。
3. 响应结构：`tradingDay + pageStatus + marketSummary + debugInfo?`。
4. 字段命名规则：统一 lowerCamelCase。
5. 向后兼容策略：新增字段仅做可选扩展，不改既有字段语义。

---

## 9. 验收标准

1. 功能验收：后端可配置返回 5 卡或 6 卡；前端均可正确展示。
2. 语义验收：文案来自后端，不含主观建议。
3. 状态验收：debug 可见模块级 delayed/partial 原因。
4. 异常验收：异常码均登记且可回溯。
5. 加载验收：真实 API 未返回前不展示 mock summary，5 秒超时后进入 error 样式。

---

## 10. 已确认清零项

1. 第 6 卡默认关闭（默认 5 卡）。
2. 文案分版本：盘中模板、盘后模板。
3. 指数上涨数量按本模块独立逻辑计算，不做内部复用耦合。
4. 本轮无未决拍板项。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结“后端配置驱动 + 前端纯展示”需求边界 | Codex |
