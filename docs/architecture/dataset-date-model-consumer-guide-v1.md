# 数据集日期模型消费指南

更新时间：2026-09-10。状态：现行日期语义专题。已合并日期枚举、Workflow 时间形状/制度和股票周期维护说明的有效内容；本次补齐来源与测试入口、区分指数周/月线实现，不改日期模型或消费者行为，不重新认证源接口行为。

## 1. 先区分三个问题

| 问题 | 依据 | 不能推导什么 |
| --- | --- | --- |
| 用户能传什么时间？ | `input_shape/window_mode`、input_model、动作 `supported_time_modes` | 能按日期过滤，不代表每天都应有数据 |
| 一次执行如何拆分？ | Resolver、planner、request builder 与日期模型 | 按代码请求，不代表没有业务日期 |
| 如何判断新鲜度和缺失？ | `observed_field/audit_applicable/bucket_rule`、freshness policy、行归属与 completeness | 最近同步成功，不代表业务日期最新或对象完整 |

唯一日期事实源为 [DatasetDateModel](/Users/congming/github/goldenshare/src/foundation/datasets/models.py)。其他模块通过 [registry](/Users/congming/github/goldenshare/src/foundation/datasets/registry.py)读取，不在 Ops、前端、SQL 或 helper 中维护另一份数据集日期映射。

```python
from src.foundation.datasets.registry import get_dataset_definition

definition = get_dataset_definition(dataset_key)
date_model = definition.date_model
```

## 2. 字段语义

| 字段 | 负责什么 |
| --- | --- |
| `date_axis` | 日期轴：`trade_open_day/natural_day/month_key/month_window/none` |
| `bucket_rule` | 日期锚点/桶规则；须与审计适用性一起判断，不能单独推出所有桶都必须有数据 |
| `window_mode` | `point/range/point_or_range/none`；动作能力还可进一步限制 |
| `input_shape` | 输入字段结构，不由字段名猜交易日或自然日 |
| `observed_field` | 目标表真实业务日期字段，可为 `None`，不以同步时间兜底 |
| `audit_applicable` | 是否适用日期完整性审计；不适用时记录 `not_applicable_reason` |
| `bucket_window_rule` | 锚点对应的业务窗口，如 `iso_week/natural_month`；默认未声明 |
| `bucket_applicability_rule` | 默认 `always`；显式启用 `requires_open_trade_day_in_bucket` 才按窗口内开市日排除桶 |

日期选择规则由模型的 `selection_rule()` 派生，不能再复制一张 `dataset_key -> selection_rule` 表。新增取值必须核验所有消费者，模型接受字符串不证明 planner、审计和 UI 均已支持。

### 日期桶规则

| `bucket_rule` | 含义 |
| --- | --- |
| `every_open_day` | 每个开市日 |
| `week_last_open_day/month_last_open_day` | 每周/每月最后开市日 |
| `every_natural_day` | 每个自然日 |
| `week_friday/month_last_calendar_day` | 自然周五/自然月最后一天 |
| `calendar_quarter_end` | 自然季度末；当前 `fund_portfolio` 使用，但其 `audit_applicable=False`，不能据此要求连续季度一定有记录 |
| `every_natural_month` | `YYYYMM` 月份键 |
| `month_window_has_data` | 自然月窗口内存在数据，不要求固定某一天 |
| `not_applicable` | 不以连续日期桶判断缺失；不等于没有时间输入 |

`not_applicable` 与 `input_shape` 必须分开读。例如当前 `fund_div` 可以按公告日期维护，但不要求每个自然日都有分红；`ths_member` 则无日期输入。不能把事件型一概改成 no-time，也不能把所有主数据强制按日审计。[定义证据](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/public_fund.py)

### 输入与交互

| `input_shape` | 意图字段与交互 |
| --- | --- |
| `trade_date_or_start_end` | 单日期 `trade_date` 或 `start_date/end_date`；能选哪些日期须结合日期轴和桶规则 |
| `ann_date_or_start_end` | 公告日期单点或自然日期区间，以动作支持的模式为准 |
| `month_or_range` | `month` 或 `start_month/end_month` |
| `start_end_month_window` | `start_month/end_month`，表示自然月窗口 |
| `none` | 无日期输入 |

API/前端消费后端派生的字段与选择规则，不能看到 `trade_date` 就使用交易日控件，也不能无视动作能力自动开放所有时间模式。

## 3. 意图、执行和源参数

1. Ops/TaskRun/API/UI 保存用户或调度意图。
2. [DatasetActionResolver](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)归一化时间并调用 planner 生成计划。
3. [request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)映射、格式化已归一化值，不重新决定业务日期制度。

`index_weight` 示例：上层表达维护 `202604` 自然月窗口；Resolver 展开为 4 月 1 日至 30 日；builder 再格式化源参数。不要让 Ops 或页面提前计算源端的 `start_date/end_date`。

`broker_recommend` 使用月份键；Resolver 的 point 执行归一化与 freshness 中把 `YYYYMM` 表示为该月第一天，是不同用途，不能互相替换。

`index_daily` 按请求池 `index_daily_raw` 的代码及日期窗口取数，Serving 再按 `index_daily` active 池筛选；这不改变其交易日观测模型。不要把执行扇出方式写回日期轴。

<a id="period-anchors"></a>

## 4. 股票与指数周期线必须区分

| 数据集 | Definition 声明的日期轴与锚点 | 观测字段 |
| --- | --- | --- |
| `stk_period_bar_week`、`stk_period_bar_adj_week` | `natural_day + week_friday` | `trade_date` |
| `stk_period_bar_month`、`stk_period_bar_adj_month` | `natural_day + month_last_calendar_day` | `trade_date` |
| `index_weekly` | `trade_open_day + week_last_open_day` | `trade_date` |
| `index_monthly` | `trade_open_day + month_last_open_day` | `trade_date` |

完整定义见 [market_equity.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)、[index_series.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)。

- 股票周五休市但周内有开市日时，自然周五仍是锚点；不能回退为周四。
- 股票自然月末不是开市日时，仍保留自然月末；不能统一改成月末交易日。
- 指数月线按完整月历校验真实月末；指数周线虽声明 `week_last_open_day`，区间 planner 实际只取输入范围内每周最后开市日，仍可产生截断周单元。不能从声明推导出周线已有完整周期校验，也不能把月线派生保护推广给周线；差异见[指数机制 §3–4](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)。本次只说明现状，不授权修改指数。
- 自然锚点应贯穿输入选择、planner、目标观测、审计和展示；不能只改 UI 文案。
- 范围内无可执行锚点、计划为空与“预期数据缺失”不是同一结果；保留现行处理与反例测试，不为统一措辞强制报错。

旧“所有周/月线都以最后交易日为准”的确认已经被推翻。股票周/月线的独立维护说明已并入本节，不再另维护重复规则。

### 股票周期接口与执行入口

| 数据集 | 源接口 | builder 固定频率 |
| --- | --- | --- |
| `stk_period_bar_week` / `stk_period_bar_month` | `stk_weekly_monthly` | 分别为 `week` / `month` |
| `stk_period_bar_adj_week` / `stk_period_bar_adj_month` | `stk_week_month_adj` | 分别为 `week` / `month` |

源资料：[doc 336 股票周/月线行情](</Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0336_股票周_月线行情(每日更新).md>)、[doc 365 股票周/月线复权行情](</Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md>)。本地资料中 `trade_date` 是周期锚点，返回字段 `end_date` 是计算截至日期；doc 336 样例中前者为 `20251024`、后者为 `20251023`，不能因为锚点已存在就认定完整周期计算已经结束。这里引用既有资料，不作为本次源端实测结论。

手动与自动入口保持 `action=maintain`，point 输入日期，range 输入 `start_date/end_date`，通过 §3 的标准 Resolver/Plan 执行，不恢复历史独立回补服务或旧执行任务名称。[validator](/Users/congming/github/goldenshare/src/foundation/ingestion/validator.py)拒绝非自然周五/自然月末的股票 point；[planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)按范围展开锚点；[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)固定 `freq` 并格式化日期，不将源接口可选参数自动开放为运营字段。

已有 [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)覆盖自然周五（含 5 月 1 日）、自然月末范围展开、实际请求的 `trade_date/freq` 和非法周线 point；动作暴露见 [action catalog 测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)。不再把这些现有覆盖写成“后续待补”。

### 日期桶是否应产出

四个股票周期数据集显式使用 `requires_open_trade_day_in_bucket`：

- 周线窗口是 `iso_week`，月线窗口是 `natural_month`。
- 日期审计先生成候选锚点，再依据交易日历排除整个窗口没有开市日的桶。
- 被排除桶应标为“规则排除”，不是缺失，也不应改造成节假日白名单。
- 单日休市不等于整个周期无交易。不能只查锚点当天是否开市。
- 这是 expected bucket 的适用性判断；不宣称所有 planner 都已应用同样过滤，也不默认为其他数据集启用。

实现依据：[date_completeness_audit_service.py](/Users/congming/github/goldenshare/src/ops/services/date_completeness_audit_service.py)、[date_completeness_run_service.py](/Users/congming/github/goldenshare/src/ops/services/date_completeness_run_service.py)。

### 共表行归属

股票周/月线分别共用 `core_serving.stk_period_bar`、`core_serving.stk_period_bar_adj`。读取实际日期桶时，须同时使用 `observed_field` 和 `storage.row_identity_filters` 的 `freq=week/month`，否则月线可能“补上”周线缺口。

行归属是 storage 事实，不是在 Ops、SQL 或前端按 dataset key 写特例。它与完整性对象范围、冲突键仍是不同概念。

<a id="workflow-time"></a>

## 5. Workflow 的时间形状与默认制度

原 Workflow 分析的核心结论保留：`point/range/none` 回答“输入什么形状”；`trade_open_day/natural_day/none` 回答“默认日期属于什么制度”。单点不等于交易日，range 也不等于交易日区间。

当前 [WorkflowDefinition](/Users/congming/github/goldenshare/src/ops/action_catalog.py)有 `time_regime`；[TaskRunCommandService._default_workflow_time_input()](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)的行为是：

- 无参数 workflow 返回 `mode=none`。
- point profile 且有 `trade_date` 参数：natural-day workflow 有调度时间时，按排程时区得到本地自然日；其他情形先返回 point 意图，由后续链路处理默认日期。
- 需要范围的流程不能凭空补成“今天”；缺少明确范围时拒绝自动任务配置。

手动任务的日期控件/标签应消费 workflow 的制度投影，不能把 natural-day workflow 按交易日呈现。workflow 默认日期、dataset 日期模型和源参数分别归属不同层；workflow 的 `time_regime` 不覆盖子数据集的 Definition。

原文夹带的五个新数据集接入、workflow 本体和对接进度不是日期模型合同，不随合并宣称已完成或重新开工。专项进度继续由 [参考数据任务组索引](/Users/congming/github/goldenshare/docs/governance/reference-data-workstreams-rollout-index-v1.md)和 [Workflow 目录](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md)维护。Schedule 日期策略另见 [当前 resolver](/Users/congming/github/goldenshare/src/ops/services/dataset_schedule_time_policy_resolver.py)，不能用旧 Workflow 草案覆盖后续动作级策略。

## 6. 消费者核验与测试

| 消费方 | 必须核验 |
| --- | --- |
| validator/planner | 输入组合、锚点、空计划、unit/request params；不能另建日期分类 |
| freshness/cards/snapshot | 真实业务日期、freshness policy、无日期时的同步迹象与未确认状态 |
| 日期完整性 | audit 适用性、expected buckets、窗口排除、actual 行归属；日期齐全不等于对象齐全 |
| 手动/自动/Workflow | 意图到 TaskRun，再到 Resolver 和 unit 的完整链路 |
| API/前端 | 后端派生字段、时间控件、标签与禁止输入；不复制数据集映射 |

日期模型变更需按 [根 AGENTS](/Users/congming/github/goldenshare/AGENTS.md)完成全量消费者审计，并同步 [数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。只证明 TaskRun 创建成功不够，必须验证计划与实际请求范围。

关键测试入口：[registry](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[resolver](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[日期审计](/Users/congming/github/goldenshare/tests/test_date_completeness_audit_service.py)、[日期审计 API](/Users/congming/github/goldenshare/tests/web/test_ops_date_completeness_api.py)、[freshness](/Users/congming/github/goldenshare/tests/test_dataset_freshness_registry_validation.py)、[Ops action catalog](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)。

至少保留自然周五休市、自然月末非交易日、整周期无交易、股票/指数差异、共表 freq 隔离、月份窗口及 no-time/事件输入的正反例。真实请求与生产验收按独立授权执行；本文合并不修改数据，也不恢复旧补湖或迁移步骤。
