# 股票周/月线自然锚点日期模型修正方案 v1

- 状态：已实施
- 创建日期：2026-05-02
- 最近更新：2026-05-03
- 适用范围：`stk_period_bar_week`、`stk_period_bar_month`、`stk_period_bar_adj_week`、`stk_period_bar_adj_month`
- 源站事实：
  - `docs/sources/tushare/股票数据/行情数据/0336_股票周_月线行情(每日更新).md`
  - `docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md`
- 当前相关代码：
  - `src/foundation/datasets/definitions/market_equity.py`
  - `src/foundation/datasets/models.py`
  - `src/foundation/ingestion/unit_planner.py`
  - `src/foundation/ingestion/validator.py`
  - `src/foundation/ingestion/request_builders.py`
  - `src/ops/queries/manual_action_query_service.py`
  - `src/ops/services/date_completeness_audit_service.py`
  - `src/ops/queries/freshness_query_service.py`
  - `frontend/src/pages/ops-v21-task-manual-tab.tsx`
  - `frontend/src/shared/ui/date-field.tsx`
  - `frontend/src/shared/ui/trade-date-field.tsx`

---

## 1. 背景

当前四个股票周/月线数据集使用的 Tushare 源接口是：

| 数据集 | 源接口 | 当前频率 |
| --- | --- | --- |
| `stk_period_bar_week` | `stk_weekly_monthly` | `week` |
| `stk_period_bar_month` | `stk_weekly_monthly` | `month` |
| `stk_period_bar_adj_week` | `stk_week_month_adj` | `week` |
| `stk_period_bar_adj_month` | `stk_week_month_adj` | `month` |

源文档对 `trade_date` 的口径不是“最后一个交易日”：

| 源接口 | 文档字段说明 | 样例 |
| --- | --- | --- |
| `stk_weekly_monthly` | `交易日期(格式：YYYYMMDD，每周或每月最后一天的日期）` | 周线 `20251024`；月线 `20251031` |
| `stk_week_month_adj` | 输入：`每周或每月最后一天的日期`；输出：`每周五或者月末日期` | 周线 `20250117`、`20250110` |

当前代码把这四个数据集建模为：

| 数据集 | 当前 `date_axis` | 当前 `bucket_rule` | 当前实际生成的请求锚点 |
| --- | --- | --- | --- |
| `stk_period_bar_week` | `trade_open_day` | `week_last_open_day` | 每周最后一个开市交易日 |
| `stk_period_bar_month` | `trade_open_day` | `month_last_open_day` | 每月最后一个开市交易日 |
| `stk_period_bar_adj_week` | `trade_open_day` | `week_last_open_day` | 每周最后一个开市交易日 |
| `stk_period_bar_adj_month` | `trade_open_day` | `month_last_open_day` | 每月最后一个开市交易日 |

这会在周五休市、月末非交易日等场景下传错源接口 `trade_date`，导致同步取不到数据或取数不完整。

---

## 2. 已核验的现有日期规则

当前 `DatasetDefinition.date_model` 已实际使用的组合如下：

| `date_axis` | `bucket_rule` | 语义 | 是否能表达本需求 |
| --- | --- | --- | --- |
| `trade_open_day` | `every_open_day` | 每个开市交易日 | 不能，只能表达交易日 |
| `trade_open_day` | `week_last_open_day` | 每周最后一个开市交易日 | 不能，源接口要自然周五 |
| `trade_open_day` | `month_last_open_day` | 每月最后一个开市交易日 | 不能，源接口要自然月最后一天 |
| `natural_day` | `every_natural_day` | 每个自然日 | 不能，粒度过宽，不是只取周五/月末 |
| `month_key` | `every_natural_month` | `YYYYMM` 月份键 | 不能，源接口要 `YYYYMMDD` 日期 |
| `month_window` | `month_window_has_data` | 自然月窗口内有数据即可 | 不能，源接口要固定月末日期锚点 |
| `none` | `not_applicable` | 无日期维度 | 不能 |

结论：

1. 现有规则里没有可以准确表达“自然周五”的 `bucket_rule`。
2. 现有规则里没有可以准确表达“自然月最后一天”的 `bucket_rule`。
3. 不能继续复用 `week_last_open_day` / `month_last_open_day`，否则会继续把源接口锚点错误缩窄到交易日历。
4. 不能复用 `every_natural_day`，否则区间任务会按每天扇出，远大于源接口真实周期。
5. 不能复用 `month_key` 或 `month_window`，因为源接口参数字段仍叫 `trade_date`，且格式是 `YYYYMMDD`。

---

## 3. 目标口径

### 3.1 数据集分流

本轮只修正股票周/月线新接口口径：

| 数据集 | 目标口径 |
| --- | --- |
| `stk_period_bar_week` | 自然周周五作为源接口 `trade_date` |
| `stk_period_bar_adj_week` | 自然周周五作为源接口 `trade_date` |
| `stk_period_bar_month` | 自然月最后一天作为源接口 `trade_date` |
| `stk_period_bar_adj_month` | 自然月最后一天作为源接口 `trade_date` |

不改动指数周/月线：

| 数据集 | 保持现状原因 |
| --- | --- |
| `index_weekly` | 当前源接口文档与实现按交易日最后一天维护，未在本轮发现源站冲突 |
| `index_monthly` | 当前源接口文档与实现按交易日最后一天维护，未在本轮发现源站冲突 |

### 3.2 新增日期模型枚举值

在现有 `DatasetDateModel.bucket_rule` 内补齐两个规则值：

| 新 `bucket_rule` | 建议 `date_axis` | 语义 | 典型数据集 |
| --- | --- | --- | --- |
| `week_friday` | `natural_day` | 范围内每个自然周的周五日期 | `stk_period_bar_week`、`stk_period_bar_adj_week` |
| `month_last_calendar_day` | `natural_day` | 范围内每个自然月最后一天 | `stk_period_bar_month`、`stk_period_bar_adj_month` |

这里不是新建第二套日期系统，而是在当前唯一事实源 `DatasetDefinition.date_model` 中补齐缺失语义。

### 3.3 日期桶可产出规则

自然锚点修正解决了“源接口 trade_date 应传自然周五/自然月末”的问题，但日期完整性审计又暴露出另一个边界：春节、国庆等长假可能导致某个 ISO 自然周内没有任何开市日。这样的自然周五虽然是候选锚点，但业务上不应产出周线数据，不能被审计判为缺失。

目标口径：

| 数据集 | 锚点 | 可产出条件 | 不满足时 |
|---|---|---|---|
| `stk_period_bar_week` | 自然周五 | 该 ISO 周内至少有 1 个开市交易日 | 规则排除，不算缺失 |
| `stk_period_bar_adj_week` | 自然周五 | 该 ISO 周内至少有 1 个开市交易日 | 规则排除，不算缺失 |
| `stk_period_bar_month` | 自然月最后一天 | 该自然月内至少有 1 个开市交易日 | 规则排除，不算缺失 |
| `stk_period_bar_adj_month` | 自然月最后一天 | 该自然月内至少有 1 个开市交易日 | 规则排除，不算缺失 |

已新增到 `DatasetDefinition.date_model` 的结构化字段：

| 字段 | 周线取值 | 月线取值 |
|---|---|---|
| `bucket_window_rule` | `iso_week` | `natural_month` |
| `bucket_applicability_rule` | `requires_open_trade_day_in_bucket` | `requires_open_trade_day_in_bucket` |

约束：

1. 该规则只作用于本方案覆盖的四个股票周/月线数据集。
2. 不允许用春节、国庆日期白名单替代。
3. 不允许在审计 SQL、freshness 查询或前端用 `dataset_key` 特判。
4. 交易日历是判断“窗口内是否有开市日”的唯一事实来源。
5. 审计详情应把这类日期展示为“规则排除”，不是“缺失”。

---

## 4. 修改点清单

### M1：DatasetDefinition 事实修正

修改文件：

1. `src/foundation/datasets/definitions/market_equity.py`

修改内容：

| 数据集 | 当前 | 目标 |
| --- | --- | --- |
| `stk_period_bar_week` | `date_axis=trade_open_day`、`bucket_rule=week_last_open_day` | `date_axis=natural_day`、`bucket_rule=week_friday` |
| `stk_period_bar_adj_week` | `date_axis=trade_open_day`、`bucket_rule=week_last_open_day` | `date_axis=natural_day`、`bucket_rule=week_friday` |
| `stk_period_bar_month` | `date_axis=trade_open_day`、`bucket_rule=month_last_open_day` | `date_axis=natural_day`、`bucket_rule=month_last_calendar_day` |
| `stk_period_bar_adj_month` | `date_axis=trade_open_day`、`bucket_rule=month_last_open_day` | `date_axis=natural_day`、`bucket_rule=month_last_calendar_day` |

保持不变：

1. `window_mode=point_or_range`
2. `input_shape=trade_date_or_start_end`
3. `observed_field=trade_date`
4. `audit_applicable=True`
5. `source.api_name`
6. `source.request_builder_key`
7. 表结构、DAO、writer、row transform

原因：

1. 源接口字段名仍是 `trade_date`，所以不改 `input_shape`。
2. 目标表观测字段仍是 `trade_date`，所以 freshness 和审计继续读取该字段。
3. 错误只在“锚点日期生成”层，不在表结构或落库层。

### M2：DatasetDateModel selection rule 映射

修改文件：

1. `src/foundation/datasets/models.py`

修改内容：

| `bucket_rule` | `selection_rule` |
| --- | --- |
| `week_friday` | `week_friday` |
| `month_last_calendar_day` | `month_end` |

影响：

1. Ops 手动任务 API 会从 `DatasetDefinition.date_model` 自动返回新 `selection_rule`。
2. 前端不应自己判断数据集 key，而应继续消费后端返回的 selection rule。

### M3：Planner 范围扇出

修改文件：

1. `src/foundation/ingestion/unit_planner.py`

修改内容：

1. 在 `_resolve_anchors()` 中支持 `natural_day + week_friday`：
   - 输入 `start_date/end_date`
   - 生成范围内所有自然周周五
   - 只生成落在输入区间内的日期
2. 支持 `natural_day + month_last_calendar_day`：
   - 输入 `start_date/end_date`
   - 生成范围内所有自然月最后一天
   - 只生成落在输入区间内的日期

示例：

| 输入区间 | 规则 | 输出 anchors |
| --- | --- | --- |
| `2026-04-20 ~ 2026-04-24` | `week_friday` | `2026-04-24` |
| `2026-04-20 ~ 2026-04-30` | `week_friday` | `2026-04-24` |
| `2026-04-20 ~ 2026-05-08` | `week_friday` | `2026-04-24`、`2026-05-01`、`2026-05-08` |
| `2026-04-01 ~ 2026-04-29` | `month_last_calendar_day` | 空 |
| `2026-04-01 ~ 2026-04-30` | `month_last_calendar_day` | `2026-04-30` |
| `2026-04-20 ~ 2026-05-31` | `month_last_calendar_day` | `2026-04-30`、`2026-05-31` |

边界：

1. 如果范围内没有有效锚点，planner 应返回空 unit 并由现有流程按空计划处理，或明确抛出可读错误。实现前需核对当前空 unit 行为，再决定是否补错误提示。
2. 不允许 fallback 成 `start_date/end_date` 直接传源接口，因为本接口文档明确建议按交易日期循环提取，且单次有 6000 限制。

### M4：Validator 单点日期校验

修改文件：

1. `src/foundation/ingestion/validator.py`

修改内容：

1. 当 `date_model.bucket_rule=week_friday` 且请求是 `point` 时，`trade_date` 必须是周五。
2. 当 `date_model.bucket_rule=month_last_calendar_day` 且请求是 `point` 时，`trade_date` 必须是自然月最后一天。
3. 校验失败时返回可读错误：
   - 周线：`当前数据集要求选择自然周周五`
   - 月线：`当前数据集要求选择自然月最后一天`

原因：

1. 不应把错误日期传给源接口后再失败。
2. 校验必须从 `date_model` 派生，不写数据集 key 特判。

### M5：Request Builder 保持源接口参数语义

涉及文件：

1. `src/foundation/ingestion/request_builders.py`

预期改动：

1. `_stk_period_bar_week_params()` 继续接收 planner 给出的 `anchor_date`。
2. `anchor_date` 已经是自然周五或自然月末，因此 builder 只负责格式化为 `YYYYMMDD`。
3. 不在 builder 内重新计算周五/月末。

原因：

1. 锚点生成属于 planner，不属于 request builder。
2. 避免在多个层重复实现日期规则。

### M6：Ops 手动任务 API 与前端日期选择

后端修改文件：

1. `src/ops/queries/manual_action_query_service.py`

前端修改文件：

1. `frontend/src/shared/api/types.ts`
2. `frontend/src/shared/ui/date-field.tsx`
3. `frontend/src/pages/ops-v21-task-manual-tab.tsx`
4. `frontend/src/pages/ops-v21-task-auto-tab.tsx`
5. 相关测试文件

目标：

| selection rule | 前端行为 |
| --- | --- |
| `week_friday` | 使用自然日日期选择，单点只能选周五 |
| `month_end` | 使用自然日日期选择，单点只能选自然月最后一天 |

注意：

1. 不能继续使用 `TradeDateField` 来承载这两个规则，因为 `TradeDateField` 会先排除非交易日。
2. 范围模式仍可选普通自然日期范围，由 planner 在后端按周五/月末扇出。
3. 前端校验只是体验优化；后端 validator 仍是最终门禁。

### M7：Ops Freshness

修改文件：

1. `src/ops/queries/freshness_query_service.py`

修改内容：

1. 支持 `natural_day + week_friday` 的 expected business date：
   - 当前日期到达本周周五前，expected 是上一个周五。
   - 当前日期到达或超过本周周五，expected 是本周周五。
2. 支持 `natural_day + month_last_calendar_day` 的 expected business date：
   - 当前日期到达自然月末前，expected 是上个月自然月末。
   - 当前日期到达或超过自然月末，expected 是本月自然月末。
3. actual bucket 过滤应按自然周五 / 自然月末过滤，不再按交易日历的最后开市日过滤。
4. 默认宽限天数建议：
   - `week_friday`：沿用周线宽限，建议 14 天。
   - `month_last_calendar_day`：沿用月线宽限，建议 31 天。

### M8：日期完整性审计

修改文件：

1. `src/ops/services/date_completeness_audit_service.py`
2. `src/ops/queries/date_completeness_query_service.py`
3. `tests/test_date_completeness_audit_service.py`

修改内容：

1. `ExpectedBucketPlanner` 支持：
   - `natural_day + week_friday`
   - `natural_day + month_last_calendar_day`
2. rule label 更新：
   - `natural_day + week_friday`：`每个自然周周五`
   - `natural_day + month_last_calendar_day`：`每个自然月最后一天`
3. actual bucket 继续从 `observed_field=trade_date` 读取。

### M9：文档同步

需要同步更新：

1. `docs/architecture/dataset-date-model-consumer-guide-v1.md`
2. `docs/templates/dataset-development-template.md`
3. `docs/datasets/equity-weekly-monthly-sync-logic.md`
4. `docs/ops/dataset-date-completeness-audit-design-v2.md`
5. `docs/ops/ops-date-model-freshness-alignment-plan-v1.md`
6. `docs/architecture/dataset-definition-fact-audit-matrix-v1.md`

同步原则：

1. 旧“周线/月线必须最后交易日”的描述要拆开：
   - 指数周/月线：最后交易日。
   - 股票 `stk_weekly_monthly/stk_week_month_adj`：自然周五 / 自然月末。
2. 不得再写“全局统一最后交易日”。
3. 文档必须说明：源接口字段名仍叫 `trade_date`，但该字段的业务含义由数据集 `bucket_rule` 决定。

---

## 5. 测试方案

### 5.1 Foundation 测试

建议新增或更新：

1. `tests/test_dataset_definition_registry.py`
   - 四个股票周/月线数据集的 `date_axis/bucket_rule` 符合新口径。
   - `index_weekly/index_monthly` 保持旧口径。
2. `tests/test_dataset_action_resolver.py`
   - `stk_period_bar_week` 区间生成自然周五 anchors。
   - `stk_period_bar_month` 区间生成自然月末 anchors。
   - 复权周/月线同样覆盖。
3. `tests/test_dataset_action_validator.py` 或现有 validator 测试文件
   - 周线 point 非周五拒绝。
   - 月线 point 非自然月末拒绝。
   - 合法周五/月末通过。

### 5.2 Ops 测试

建议新增或更新：

1. `tests/web/test_ops_manual_actions_api.py`
   - 四个股票周/月线 action 返回新的 selection rule。
   - 指数周/月线 action 仍返回最后交易日 selection rule。
2. `tests/web/test_ops_runtime.py`
   - `trade_open_day` 数据集在非交易日单点任务中允许跳过。
   - `natural_day + week_friday/month_last_calendar_day` 数据集即使锚点是非交易日，也必须继续进入源接口请求链路，不能被交易日历提前跳过。
3. `tests/test_date_completeness_audit_service.py`
   - `natural_day + week_friday` 生成正确 buckets。
   - `natural_day + month_last_calendar_day` 生成正确 buckets。
4. `tests/web/test_ops_freshness_api.py`
   - 周五前 expected 是上一周五。
   - 周五当天 expected 是本周五。
   - 月末前 expected 是上月月末。
   - 月末当天 expected 是本月月末。

### 5.3 前端测试

建议新增或更新：

1. `frontend/src/shared/ui/date-field.test.tsx`
   - `week_friday` 只允许周五。
   - `month_end` 允许自然月最后一天，即使不是交易日。
2. `frontend/src/pages/ops-v21-task-manual-tab.test.tsx`
   - 股票周/月线单点不再走交易日限定控件。
   - 范围模式仍可提交自然日期范围。

### 5.4 最小命令

后续实施完成后至少执行：

```bash
pytest -q tests/test_dataset_definition_registry.py tests/test_dataset_action_resolver.py
pytest -q tests/web/test_ops_manual_actions_api.py tests/test_date_completeness_audit_service.py
pytest -q tests/architecture/test_dataset_runtime_registry_guardrails.py
python3 -m src.cli ingestion-lint-definitions
cd frontend && npm run test -- ops-v21-task-manual-tab
python3 scripts/check_docs_integrity.py
```

---

## 6. 验收场景

### 6.1 周线

输入：

```json
{
  "dataset_key": "stk_period_bar_week",
  "time_input": {
    "mode": "range",
    "start_date": "2026-04-20",
    "end_date": "2026-05-08"
  }
}
```

期望计划：

```text
trade_date=20260424, freq=week
trade_date=20260501, freq=week
trade_date=20260508, freq=week
```

不应生成：

```text
trade_date=20260424  # 如果刚好周五可相同
trade_date=20260430  # 这类最后交易日不能作为周线锚点
```

### 6.2 月线

输入：

```json
{
  "dataset_key": "stk_period_bar_month",
  "time_input": {
    "mode": "range",
    "start_date": "2026-04-01",
    "end_date": "2026-05-31"
  }
}
```

期望计划：

```text
trade_date=20260430, freq=month
trade_date=20260531, freq=month
```

不应生成：

```text
trade_date=20260424  # 交易月末，但不是源接口月末日期
trade_date=20260529  # 如果 2026-05-31 非交易日，也不能提前到最后交易日
```

### 6.3 单点校验

| 数据集 | 输入日期 | 期望 |
| --- | --- | --- |
| `stk_period_bar_week` | `2026-04-24` 周五 | 通过 |
| `stk_period_bar_week` | `2026-04-23` 周四 | 拒绝 |
| `stk_period_bar_month` | `2026-04-30` 月末 | 通过 |
| `stk_period_bar_month` | `2026-04-29` 非月末 | 拒绝 |

### 6.4 TaskRun 单点执行门禁

TaskRun dispatcher 只能对 `date_model.date_axis=trade_open_day` 的数据集应用“非交易日跳过维护”。

股票周/月线已明确为 `date_axis=natural_day`：

1. `stk_period_bar_week` 在 `2026-05-01` 这类自然周五、但交易日历休市的日期上，必须继续调用源接口。
2. `stk_period_bar_month` 在自然月最后一天休市时，同样必须继续调用源接口。
3. 禁止按数据集 key 特判；判断依据只能来自 `DatasetDefinition.date_model`。

---

## 7. 非目标

1. 不改表结构，不新增 Alembic 迁移。
2. 不改 raw/core/serving 的主键与存储字段。
3. 不改 `index_weekly/index_monthly`。
4. 不把周五/月末规则写成前端或 Ops 的数据集 key 特判。
5. 不恢复旧三类同步入口，不引入旧历史维护语义。

---

## 8. 风险与处理

| 风险 | 说明 | 处理 |
| --- | --- | --- |
| 历史文档仍写“周/月最后交易日” | 会误导后续开发 | M9 统一同步文档 |
| 前端继续使用 `TradeDateField` | 会排除非交易日月末 | M6 改为自然日规则控件 |
| freshness 仍按交易日 bucket 判断 | 页面会错误显示滞后或正常 | M7 增加自然周五/月末逻辑 |
| 审计仍按交易日最后一天 | 审计缺口会误判 | M8 增加新 bucket |
| 范围内无锚点 | 可能生成空任务或用户困惑 | 实施时明确空计划处理与错误提示 |
| 长假整周无开市日 | 自然周五被审计误判为缺失 | `bucket_applicability_rule=requires_open_trade_day_in_bucket`，作为规则排除桶展示 |

实施说明：

1. 本轮保持现有空计划行为不额外改造，避免把日期口径修正扩大成任务提交流程改造。
2. 如果后续运营上需要“范围内没有周五/月末时直接给用户明确错误”，应单独立题处理。

---

## 9. 完成定义

本需求完成必须同时满足：

1. 四个股票周/月线数据集的 `DatasetDefinition.date_model` 表达自然周五 / 自然月末。
2. 区间维护生成的 plan unit 使用自然周五 / 自然月末作为 `trade_date`。
3. 单点维护拒绝非周五 / 非月末日期。
4. 手动任务页面不再把股票周/月线限制为最后交易日。
5. freshness 与日期完整性审计使用同一套新 date model 事实。
6. 旧文档中“股票周/月线最后交易日”的误导性描述已全部修正或标记历史。
7. 所有最小测试与文档完整性检查通过。
8. 长假整周/月无开市日的候选桶，不进入缺失桶，进入规则排除桶。
