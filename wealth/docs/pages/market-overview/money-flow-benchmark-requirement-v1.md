# 市场总览｜大盘资金流向标杆需求 v1（benchmark-requirement）

> 用途：定义“大盘资金流向”模块的业务边界与固定规则。  
> 阶段：需求冻结前。  
> 产物性质：业务规则事实源（不是实现细节文档）。

关联文档：

1. [大盘资金流向技术实施方案 v1（仅方案）](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-implementation-design-v1.md)
2. [大盘资金流向 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：输出“今日/昨日大盘资金净流入 + 历史净流入趋势”的客观事实。
2. 用户价值：用户快速判断市场资金方向是否在改善或转弱。
3. 业务定位：市场总览首屏核心模块，提供客观统计，不输出主观建议。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 双卡指标：今日大盘资金净流入、昨日大盘资金净流入。
2. 历史趋势：净流入折线，时间范围固定 `1个月`、`3个月`。
3. 结构化分单数据：超大单/大单/中单/小单净流入额与占比（后端返回，首期前端不展示）。
4. 模块级 debug 状态（仅调试模式）。

### 2.2 本期不覆盖

1. 不做主观资金强弱评分。
2. 不做可配置时间范围。
3. 不做前端样式/交互改造。

### 2.3 与其他模块边界

1. 上游依赖：`core_serving.market_moneyflow_dc`、`core_serving.trade_calendar`。
2. 下游消费者：`MarketMoneyFlowPanel`。
3. 职责分割：
   - 本模块只负责市场级资金流事实；
   - 不负责榜单排序、板块资金流、市场风格或成交额逻辑。

---

## 3. 核心原则（硬约束）

1. 规则归属：净流入口径、分单结构、历史取样、状态判定全部由后端定义，前端只展示。
2. 契约归属：模块契约以本三件套为唯一事实源，字段名/可空策略/状态语义本期冻结。
3. 无配置能力：本模块不接入策略配置中心，不读取模块策略文件。
4. 固定时间范围：仅支持 `1个月` 与 `3个月`。
5. UI 不变：保持当前页面结构和交互（双卡 + 单折线 + RangeSwitch）不变。
6. 统计口径冻结：统一使用 `market_moneyflow_dc`。

禁止事项：

1. 临时增加 `6个月`、`12个月` 等范围；
2. 前端自行拼接净流入计算；
3. 用其他表兜底混算当前日净流入。

### 3.1 跨模块抽象门禁原则（需求层冻结）

1. 事实源单一：资金流事实字段统一由后端定义并产出，唯一事实源为 `core_serving.market_moneyflow_dc`。
2. 契约冻结：`moneyFlow.metrics/byOrderSize/historyByRange` 字段名、可空语义、单位语义在本期冻结，不允许中途漂移。
3. 配置一致性：本模块首期不接策略中心，不引入可配置分支；范围固定 `1个月/3个月`。
4. 默认行为显式：未传 `tradeDate` 使用交易日历期望日；缺数时按 `DELAYED/PARTIAL/EMPTY` 显式落状态。
5. 排序筛选确定性：历史点统一按 `tradeDate` 升序输出；不做跨源拼接或跨口径混排。
6. 性能预算前置：模块接口 P95 预算 `< 260ms`，超预算先查 SQL/序列化，不先引缓存。
7. 可观测标准化：异常对象统一 `module/code/severity/message/details`，异常码必须先登记再使用。
8. 用户可见结果优先：验收以“双卡 + 历史曲线 + 状态文案”可见一致性为主，不以中间查询结果替代。

---

## 4. 业务对象模型（非代码，先语义）

1. `MoneyFlowPanel`：资金流向模块返回根对象。
2. `MoneyFlowMetrics`：双卡指标对象。
3. `OrderSizeFlow`：分单结构对象。
4. `MoneyFlowHistoryPoint`：历史趋势点。

字段语义要求：

| 对象 | 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|---|
| `MoneyFlowPanel` | `tradeDate` | 模块观测交易日 | - | 否 | 后端 | 缺失即异常 |
| `MoneyFlowMetrics` | `todayNetAmount` | 今日大盘净流入 | 元 | 是 | 后端 | 缺失显示 `--` |
| `MoneyFlowMetrics` | `prevNetAmount` | 昨日大盘净流入 | 元 | 是 | 后端 | 缺失显示 `--` |
| `MoneyFlowMetrics` | `unit` | 金额原始单位 | - | 否 | 后端 | 固定 `yuan` |
| `OrderSizeFlow` | `elg.amount` | 超大单净流入额 | 元 | 是 | 后端 | 缺失显示 `--` |
| `OrderSizeFlow` | `elg.rate` | 超大单净流入占比 | % | 是 | 后端 | 缺失显示 `--` |
| `OrderSizeFlow` | `lg.amount` | 大单净流入额 | 元 | 是 | 后端 | 缺失显示 `--` |
| `OrderSizeFlow` | `lg.rate` | 大单净流入占比 | % | 是 | 后端 | 缺失显示 `--` |
| `OrderSizeFlow` | `md.amount` | 中单净流入额 | 元 | 是 | 后端 | 缺失显示 `--` |
| `OrderSizeFlow` | `md.rate` | 中单净流入占比 | % | 是 | 后端 | 缺失显示 `--` |
| `OrderSizeFlow` | `sm.amount` | 小单净流入额 | 元 | 是 | 后端 | 缺失显示 `--` |
| `OrderSizeFlow` | `sm.rate` | 小单净流入占比 | % | 是 | 后端 | 缺失显示 `--` |
| `MoneyFlowPanel` | `historyByRange` | 各时间范围趋势点 | - | 否 | 后端 | 空数组 + 模块 empty |
| `MoneyFlowHistoryPoint` | `tradeDate` | 历史交易日 | - | 否 | 后端 | 异常点丢弃 |
| `MoneyFlowHistoryPoint` | `netAmount` | 当日净流入 | 元 | 是 | 后端 | 可空点位 |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| `tradeDate` | `core_serving.trade_calendar` | `trade_date` | date -> `YYYY-MM-DD` | 取目标交易日 |
| `todayNetAmount` | `core_serving.market_moneyflow_dc` | `net_amount` | 目标交易日取值 | 单源 |
| `prevNetAmount` | `core_serving.market_moneyflow_dc` | `net_amount` | 前一交易日取值 | 单源 |
| `elg.amount` | `core_serving.market_moneyflow_dc` | `buy_elg_amount` | 原样 | 单源 |
| `elg.rate` | `core_serving.market_moneyflow_dc` | `buy_elg_amount_rate` | 原样 | 单源 |
| `lg.amount` | `core_serving.market_moneyflow_dc` | `buy_lg_amount` | 原样 | 单源 |
| `lg.rate` | `core_serving.market_moneyflow_dc` | `buy_lg_amount_rate` | 原样 | 单源 |
| `md.amount` | `core_serving.market_moneyflow_dc` | `buy_md_amount` | 原样 | 单源 |
| `md.rate` | `core_serving.market_moneyflow_dc` | `buy_md_amount_rate` | 原样 | 单源 |
| `sm.amount` | `core_serving.market_moneyflow_dc` | `buy_sm_amount` | 原样 | 单源 |
| `sm.rate` | `core_serving.market_moneyflow_dc` | `buy_sm_amount_rate` | 原样 | 单源 |
| `historyByRange[*].netAmount` | `core_serving.market_moneyflow_dc` | `net_amount` | 按交易日序列取历史值 | 22/62 交易日 |

补充：

1. 来源优先级：单源 `market_moneyflow_dc`。
2. 回退策略：不跨源补值，不用其他表估算资金流。
3. 时效语义：盘后快照语义（非实时流）。

---

## 6. 状态语义

1. 页面级状态：`READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. 模块级状态（debug）：返回 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. delayed 判定：`observedTradeDate < expectedTradeDate`。
4. partial 判定：双卡可用但历史范围缺口，或分单结构缺失。

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

1. 接口路径：`GET /api/v1/wealth/market/money-flow`。
2. 请求参数：`market/tradeDate/debug`。
3. 响应结构：`tradingDay + pageStatus + moneyFlow + debugInfo?`。
4. 字段命名规则：lowerCamelCase + 语义化字段。
5. 向后兼容策略：只增不改；不改现有字段语义。

---

## 9. 验收标准

1. 功能验收：返回双卡指标 + `1个月/3个月` 历史净流入趋势。
2. 语义验收：净流入正负语义稳定（正=净流入，负=净流出）。
3. 状态验收：debug 可见模块 delayed/empty/error 追因。
4. 异常验收：仅使用注册表异常码。

### 9.1 参考 case（可复用）

1. “接口成功但模块全空”：验证是否是目标交易日无数据而非查询失败。
2. “今日有值但昨日缺失”：验证状态应为 `PARTIAL`，且昨日卡片显示 `--`。
3. “历史样本不足”：验证 `threeMonth` 点位不足时状态归并为 `PARTIAL`，但 `oneMonth` 正常可展示。
4. “源日期落后”：验证 `observedTradeDate < expectedTradeDate` 时模块标记 `DELAYED`。

---

## 10. 待拍板项（当前已清零）

1. 资金流模块数据源固定为 `market_moneyflow_dc`。
2. 时间范围固定 `1个月/3个月`。
3. 保持当前页面样式与交互不变。
4. 分单结构（超大/大/中/小净流入额与占比）作为模块标准返回对象保留。
5. 本轮无未决拍板项。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结大盘资金流向模块边界（双卡 + 历史趋势 + 分单结构） | Codex |
| v1.1 | 2026-05-12 | 对齐三件套模板：补齐跨模块门禁原则与验收参考 case，统一“待拍板项”章节语义 | Codex |
| v1.2 | 2026-05-12 | 强化模板对齐：补齐“规则归属/契约归属”硬约束，统一需求层冻结表达 | Codex |
