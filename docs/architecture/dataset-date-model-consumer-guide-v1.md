# 数据集日期模型消费指南 v1

- 版本：v1
- 状态：当前生效
- 更新时间：2026-04-26
- 面向对象：需要读取数据集日期语义的后端模块、运维模块、审计模块、前端/API 设计方、外部协作方
- 单一事实源：`DatasetDefinition.date_model`

---

## 1. 一句话结论

所有数据集的日期语义都只允许从 `DatasetDefinition.date_model` 读取。

不要再为同步、状态、审计、前端展示分别维护独立的日期规则表。

---

## 2. 适用场景

当你需要回答下面问题时，应读取 `date_model`：

1. 某个数据集是否按交易日、自然日、月份或自然月窗口组织数据？
2. 某个数据集的日期完整性应该按每天、每周最后交易日、每月最后交易日还是自然月来判断？
3. 某个数据集是否适合做日期完整性审计？
4. 某个数据集应该用哪个字段作为 freshness / 数据状态的观测日期？
5. 某个数据集是否是快照/主数据，无法按日期连续性审计？
6. 某个同步策略需要把结构化日期模型临时转换成运行时锚点值。

如果你只是调用数据同步命令或查看运营后台页面，通常不需要直接读 `date_model`。

---

## 3. 正确读取方式

### 3.1 Python 后端模块

```python
from src.foundation.datasets.registry import get_dataset_definition

definition = get_dataset_definition(dataset_key)
date_model = definition.date_model
```

### 3.2 读取执行计划投影

执行链路不要再读取旧 contract helper。正确做法是把用户请求解析成 `DatasetActionRequest`，再由 resolver 读取 `DatasetDefinition.date_model` 生成 `DatasetExecutionPlan`。

```python
from src.foundation.ingestion.execution_plan import DatasetActionRequest
from src.foundation.ingestion.resolver import DatasetActionResolver

plan = DatasetActionResolver(session).build_plan(request)
```

注意：

1. `DatasetExecutionPlan` 是运行时投影，不是第二份事实源。
2. 新模块应优先读取结构化字段：`date_axis/bucket_rule/window_mode/input_shape/observed_field/audit_applicable`。
3. 不要把 plan 中的派生结果再落成一份长期配置。

### 3.3 前端或外部系统

前端和仓库外系统不要直接复制本文件中的规则表。

正确方式是：

1. 后端 API 如需暴露日期模型，应从 `DatasetDefinition.date_model` 序列化返回。
2. 前端只消费 API 返回值，不手写数据集日期规则。
3. 外部系统如需引用规则，应以导出的 API/文档快照为准，并标注生成时间。

---

## 4. 字段含义

`DatasetDateModel` 当前结构如下：

```python
@dataclass(slots=True, frozen=True)
class DatasetDateModel:
    date_axis: str
    bucket_rule: str
    window_mode: str
    input_shape: str
    observed_field: str | None
    audit_applicable: bool
    not_applicable_reason: str | None = None
```

| 字段 | 含义 | 典型值 | 消费方 |
|---|---|---|---|
| `date_axis` | 数据集日期基轴，即日期集合从哪里来 | `trade_open_day` / `natural_day` / `month_key` / `month_window` / `none` | planner、审计、展示 |
| `bucket_rule` | 在日期基轴上，哪些日期桶必须有数据 | `every_open_day` / `week_last_open_day` / `month_last_open_day` / `every_natural_day` / `week_friday` / `month_last_calendar_day` / `every_natural_month` / `month_window_has_data` / `not_applicable` | 审计、planner |
| `window_mode` | 请求窗口语义 | `point` / `range` / `point_or_range` / `none` | validator、planner、手动任务参数设计 |
| `input_shape` | 对外输入形态 | `trade_date_or_start_end` / `month_or_range` / `start_end_month_window` / `ann_date_or_start_end` / `none` | API、CLI、手动任务表单 |
| `observed_field` | 目标表中用于 freshness / 状态观测的字段 | `trade_date` / `ann_date` / `month` / `None` | ops freshness、审计 |
| `audit_applicable` | 是否适合做日期完整性审计 | `True` / `False` | 审计任务、审查中心 |
| `not_applicable_reason` | 不适合日期审计的原因 | `snapshot/master dataset` | 审计任务、审查中心 |

---

## 5. 字段组合语义

### 5.1 每个交易日都应有数据

```text
date_axis=trade_open_day
bucket_rule=every_open_day
window_mode=point_or_range
input_shape=trade_date_or_start_end
observed_field=trade_date
audit_applicable=True
```

典型数据集：

1. `daily`
2. `moneyflow`
3. `stk_limit`
4. `fund_daily`
5. `dc_daily`

语义：以交易日历中开市日期为基准，范围内每个开市交易日都可作为一个日期桶。

### 5.2 每周最后一个交易日应有数据

```text
date_axis=trade_open_day
bucket_rule=week_last_open_day
window_mode=point_or_range
input_shape=trade_date_or_start_end
observed_field=trade_date
audit_applicable=True
```

典型数据集：

1. `index_weekly`

语义：不是自然周五，而是该周最后一个开市交易日。

### 5.3 每月最后一个交易日应有数据

```text
date_axis=trade_open_day
bucket_rule=month_last_open_day
window_mode=point_or_range
input_shape=trade_date_or_start_end
observed_field=trade_date
audit_applicable=True
```

典型数据集：

1. `index_monthly`

语义：不是自然月最后一天，而是该月最后一个开市交易日。

### 5.4 股票周/月线源接口自然日期锚点

周线：

```text
date_axis=natural_day
bucket_rule=week_friday
window_mode=point_or_range
input_shape=trade_date_or_start_end
observed_field=trade_date
audit_applicable=True
```

典型数据集：

1. `stk_period_bar_week`
2. `stk_period_bar_adj_week`

语义：源接口字段名仍叫 `trade_date`，但含义是自然周周五，不是最后一个交易日。

月线：

```text
date_axis=natural_day
bucket_rule=month_last_calendar_day
window_mode=point_or_range
input_shape=trade_date_or_start_end
observed_field=trade_date
audit_applicable=True
```

典型数据集：

1. `stk_period_bar_month`
2. `stk_period_bar_adj_month`

语义：源接口字段名仍叫 `trade_date`，但含义是自然月最后一天，不是最后一个交易日。

### 5.5 按自然日公告日期组织数据

```text
date_axis=natural_day
bucket_rule=every_natural_day
window_mode=range
input_shape=ann_date_or_start_end
observed_field=ann_date
audit_applicable=True
```

典型数据集：

1. `dividend`
2. `stk_holdernumber`

语义：上层可传 `start_date/end_date`，执行策略按自然日扇开为源接口的 `ann_date` 请求。

### 5.5 按月份键组织数据

```text
date_axis=month_key
bucket_rule=every_natural_month
window_mode=point_or_range
input_shape=month_or_range
observed_field=month
audit_applicable=True
```

典型数据集：

1. `broker_recommend`

语义：月份以 `YYYYMM` 表示。用于 freshness 时，`YYYYMM` 会归一化为该月第一天。

### 5.6 按自然月窗口组织数据

```text
date_axis=month_window
bucket_rule=month_window_has_data
window_mode=range
input_shape=start_end_month_window
observed_field=trade_date
audit_applicable=True
```

典型数据集：

1. `index_weight`

语义：每个自然月作为一个窗口。窗口通常是该月第一天到最后一天，要求月窗口内存在数据，不要求固定到某个交易日。

### 5.7 快照或主数据

```text
date_axis=none
bucket_rule=not_applicable
window_mode=point / point_or_range / none
input_shape=none
observed_field=None
audit_applicable=False
not_applicable_reason=snapshot/master dataset
```

典型数据集：

1. `stock_basic`
2. `hk_basic`
3. `us_basic`
4. `index_basic`
5. `ths_member`

语义：这类数据集不按日期连续性组织，不适合日期完整性审计。

---

## 6. 常见消费方如何使用

### 6.1 Sync validator / planner

使用目标：

1. 校验 `run_profile` 与 `window_mode` 是否匹配。
2. 生成交易日、周末交易日、月末交易日、自然日、月份键等执行锚点。
3. 把结构化模型派生为执行计划中的时间桶和 unit。

正确做法：

```python
plan = DatasetActionResolver(session).build_plan(request)
units = plan.units
```

禁止做法：

1. 在 planner 里按 `dataset_key` 维护另一份日期类型表。
2. 在执行策略里覆盖 `date_axis/bucket_rule/window_mode`。
3. 在 helper 中加入只服务单个数据集的日期特例。

### 6.2 Ops freshness / 数据状态

使用目标：

1. 判断目标表中哪个字段代表最新业务日期。
2. 避免旧 freshness metadata 重复维护观测字段。

正确做法：

```python
observed_date_column = get_dataset_definition(resource_key).date_model.observed_field
```

补充规则：

1. `observed_field=None` 表示该数据集没有可用于日期 freshness 的观测字段。
2. `month` 字段若是 `YYYYMM`，展示/计算时可归一化为该月第一天。

### 6.3 日期完整性审计

使用目标：

1. 决定某数据集是否可审计。
2. 生成期望日期桶。
3. 查询目标表实际日期桶并计算缺口。

应读取字段：

1. `audit_applicable`
2. `not_applicable_reason`
3. `date_axis`
4. `bucket_rule`
5. `observed_field`

禁止做法：

1. 新增独立的 `calendar_type/anchor_rule` 规则表。
2. 前端硬编码每个数据集的审计规则。
3. 将审计规则写入 ops 本地常量后长期维护。

### 6.4 手动任务 / 自动任务参数设计

使用目标：

1. 判断页面应展示单日、区间、月份、自然月窗口还是无日期输入。
2. 判断某数据集的 `maintain` 动作应该接收哪种时间输入。

建议读取字段：

1. `window_mode`
2. `input_shape`
3. `date_axis`
4. `bucket_rule`

示例：

| `input_shape` | 推荐交互 |
|---|---|
| `trade_date_or_start_end` | 单交易日或交易日区间 |
| `month_or_range` | 单月份或月份区间 |
| `start_end_month_window` | 自然月窗口 |
| `ann_date_or_start_end` | 公告自然日或自然日区间 |
| `none` | 不展示日期输入 |

### 6.5 前端展示

前端不应自己维护日期模型。若页面需要展示“按交易日更新”“按月更新”“不可审计”等信息，应由后端 API 返回由 `date_model` 派生后的展示字段。

建议后端返回示例：

```json
{
  "dataset_key": "broker_recommend",
  "date_model": {
    "date_axis": "month_key",
    "bucket_rule": "every_natural_month",
    "window_mode": "point_or_range",
    "input_shape": "month_or_range",
    "observed_field": "month",
    "audit_applicable": true,
    "not_applicable_reason": null
  }
}
```

---

## 7. 特殊口径

### 7.1 `index_daily`

`index_daily` 的数据本身按交易日观测，所以：

```text
date_axis=trade_open_day
bucket_rule=every_open_day
observed_field=trade_date
```

但它的源接口请求策略会按活跃指数池 `ts_code` 扇开，并传 `start_date/end_date` 窗口，避免 `日期 * 指数池` 的请求爆炸。

结论：

1. 日期模型仍是交易日模型。
2. 请求策略是数据集内部实现细节。
3. 不要因为请求策略特殊而改写 `date_model`。

### 7.2 `broker_recommend`

`broker_recommend` 使用月份键：

```text
observed_field=month
```

其中 `month` 是 `YYYYMM` 字符串。用于 freshness 归一化时，应按该月第一天解释。

### 7.3 `ths_member`

`ths_member` 当前没有日期输入参数，按快照/主数据处理：

```text
date_axis=none
audit_applicable=False
not_applicable_reason=snapshot/master dataset
```

如果来源接口或业务口径发生变化，必须先修改 `DatasetDefinition.date_model`，再改审计/展示/任务逻辑。

---

## 8. 新增或修改数据集时的规则

新增或修改数据集时，必须同步完成：

1. 在 `src/foundation/datasets/definitions/**` 中定义或更新 `date_model`。
2. 确认 `DatasetDefinition.input_model`、`planning`、`transaction` 与日期模型一致。
3. 运行 ingestion definition lint。
4. 补充或更新必要测试。

最小门禁：

```bash
pytest -q tests/test_dataset_definition_registry.py tests/test_dataset_action_resolver.py
pytest -q tests/architecture/test_dataset_maintenance_refactor_guardrails.py
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare ingestion-lint-definitions
```

如果变更影响 ops freshness，还应运行：

```bash
pytest -q tests/test_ops_action_catalog.py tests/test_ops_freshness_snapshot_query_service.py tests/test_dataset_freshness_registry_validation.py
```

---

## 9. 禁止事项

1. 禁止新增第二套日期规则表。
2. 禁止在 ops/frontend/biz 中复制 `DATASET_DATE_MODELS`。
3. 禁止在策略层覆盖 DatasetDefinition 日期模型。
4. 禁止把执行计划投影结果当作新的事实源。
5. 禁止把快照/主数据强行纳入日期连续性审计。
6. 禁止把 `week_last_open_day` 简化成自然周五；源接口确实要求自然周五时，必须显式使用 `week_friday`。
7. 禁止把 `month_last_open_day` 简化成自然月末；源接口确实要求自然月末时，必须显式使用 `month_last_calendar_day`。

---

## 10. 相关文档

1. [DatasetDefinition 单一事实源重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
2. [数据集日期完整性审计设计 v1（审查中心，历史草案）](/Users/congming/github/goldenshare/docs/ops/dataset-date-completeness-audit-design-v1.md)
