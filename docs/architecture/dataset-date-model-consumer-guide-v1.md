# 数据集日期模型消费指南 v1

- 版本：v1
- 状态：当前生效
- 更新时间：2026-05-03
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

### 3.3 意图、执行计划、源接口参数三层分离

日期模型消费必须分清三层，不允许把某一层的职责提前或下放到另一层：

| 层级 | 负责什么 | 不负责什么 |
|---|---|---|
| Ops / TaskRun / API / UI | 保存用户或调度意图，例如处理哪个数据集、哪个月份、哪个日期范围、哪些筛选条件 | 不提前展开为某个源接口需要的参数 |
| `DatasetActionResolver` | 读取 `DatasetDefinition.date_model`，把意图归一化为 `DatasetExecutionPlan`、标准时间范围和 plan units | 不处理 TaskRun 持久化、页面展示或源接口字符串格式 |
| request builder | 把已经归一化的计划值格式化为源接口请求参数，例如 `date -> YYYYMMDD` | 不决定业务日期语义，不从 `dataset_key` 猜时间规则 |

例子：

`index_weight` 是 `start_end_month_window`。Ops 层应表达“维护 `202604` 自然月窗口”，resolver 再展开为 `2026-04-01 ~ 2026-04-30`，request builder 最后格式化为 Tushare 的 `start_date=20260401&end_date=20260430`。

错误做法：

1. Ops 自动任务看到源接口需要 `start_date/end_date`，就提前把 `start_month/end_month` 展开成源接口日期。
2. request builder 根据 `dataset_key=index_weight` 自行决定自然月首尾。
3. 前端把日期模型规则写成页面常量，再提交已经“加工过”的源接口参数。

正确做法：

1. 上层提交的是业务意图字段。
2. resolver 是日期模型归一化唯一入口。
3. request builder 只做字段映射和格式化。

### 3.4 前端或外部系统

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

### 4.1 相关存储事实：`storage.row_identity_filters`

`DatasetDateModel` 只表达日期语义，不表达目标表中的行归属。多个逻辑数据集共用同一张目标表、同一个观测日期字段时，行归属必须放在 `DatasetDefinition.storage.row_identity_filters`，不能让审计 SQL、freshness 查询或前端按 `dataset_key` 自行猜测。

当前已落地场景：

| 数据集 | 目标表 | 观测字段 | 行归属过滤 |
|---|---|---|---|
| `stk_period_bar_week` | `core_serving.stk_period_bar` | `trade_date` | `freq=week` |
| `stk_period_bar_month` | `core_serving.stk_period_bar` | `trade_date` | `freq=month` |
| `stk_period_bar_adj_week` | `core_serving.stk_period_bar_adj` | `trade_date` | `freq=week` |
| `stk_period_bar_adj_month` | `core_serving.stk_period_bar_adj` | `trade_date` | `freq=month` |

消费规则：

1. 读取实际 bucket 时必须同时消费 `date_model.observed_field` 与 `storage.row_identity_filters`。
2. `row_identity_filters` 是存储事实，不是审计特例。
3. 不允许在 Ops、SQL、前端或测试里写 `dataset_key -> freq` 这样的第二套映射。

### 4.2 日期桶可产出规则

当前 `date_axis + bucket_rule` 能表达“锚点是什么”，但还缺一层“这个锚点对应的业务窗口是否应该产出数据”。股票周/月线已经暴露出这个问题：`week_friday` 会生成春节、国庆整周休市期间的自然周五，但该周没有任何开市日，源数据本身不应产出周线数据，审计不应把它判为缺失。

当前结构化语义：

| 字段 | 含义 | 第一版取值 |
|---|---|---|
| `bucket_window_rule` | 锚点对应的业务窗口 | `iso_week` / `natural_month` |
| `bucket_applicability_rule` | 候选桶是否应纳入检查的规则 | `always` / `requires_open_trade_day_in_bucket` |

第一版只允许四个股票周/月线数据集显式启用：

| 数据集 | `bucket_rule` | `bucket_window_rule` | `bucket_applicability_rule` | 语义 |
|---|---|---|---|---|
| `stk_period_bar_week` | `week_friday` | `iso_week` | `requires_open_trade_day_in_bucket` | 自然周五仍是锚点，但该 ISO 周至少有 1 个开市日才应检查 |
| `stk_period_bar_adj_week` | `week_friday` | `iso_week` | `requires_open_trade_day_in_bucket` | 同上 |
| `stk_period_bar_month` | `month_last_calendar_day` | `natural_month` | `requires_open_trade_day_in_bucket` | 自然月末仍是锚点，但该自然月至少有 1 个开市日才应检查 |
| `stk_period_bar_adj_month` | `month_last_calendar_day` | `natural_month` | `requires_open_trade_day_in_bucket` | 同上 |

消费规则：

1. planner 仍按 `bucket_rule` 生成候选锚点。
2. 日期完整性审计在判断 expected bucket 前，必须按 `bucket_applicability_rule` 过滤不可产出的候选桶；其他需要判断 expected bucket 的消费方后续接入时也必须复用同一规则。
3. 被过滤掉的桶不是缺失，应展示为“规则排除”，原因是对应业务窗口内无开市日。
4. 这不是节假日白名单，也不是审计 SQL 特判；交易日历是判断业务窗口是否可产出的事实来源。
5. 其他数据集第一版不得默认套用该规则，必须由 `DatasetDefinition` 显式声明。

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

语义：源接口字段名仍叫 `trade_date`，但含义是自然周周五，不是最后一个交易日。日期完整性审计必须叠加 `bucket_applicability_rule=requires_open_trade_day_in_bucket`：如果自然周内没有任何开市日，该周五候选桶应被规则排除，不算缺失。

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

语义：源接口字段名仍叫 `trade_date`，但含义是自然月最后一天，不是最后一个交易日。日期完整性审计必须叠加 `bucket_applicability_rule=requires_open_trade_day_in_bucket`：如果自然月内没有任何开市日，该月末候选桶应被规则排除，不算缺失。

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
window_mode=none
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
6. `etf_basic`
7. `etf_index`
8. `ths_index`

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
6. `storage.row_identity_filters`
7. `bucket_window_rule`
8. `bucket_applicability_rule`

禁止做法：

1. 新增独立的 `calendar_type/anchor_rule` 规则表。
2. 前端硬编码每个数据集的审计规则。
3. 将审计规则写入 ops 本地常量后长期维护。
4. 用节假日日期白名单隐藏审计缺口。
5. 在审计 SQL 中按 `dataset_key` 写股票周/月线特例。

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

参数提交原则：

1. 手动任务和自动任务只提交用户或调度意图，不提交源接口参数。
2. `month_or_range` 应提交 `month` 或 `start_month/end_month`。
3. `start_end_month_window` 应提交 `start_month/end_month` 表达自然月窗口；自然月首尾日期由 `DatasetActionResolver` 统一展开。
4. `calendar_policy` 只能生成调度意图，例如某次计划触发时间对应的月份键，不能直接生成源接口参数。
5. 如果某个 UI/API 需要展示最终请求参数，必须读取执行计划或调试视图，不得在页面自行计算。

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

### 7.3 `index_weight`

`index_weight` 使用自然月窗口：

```text
date_axis=month_window
bucket_rule=month_window_has_data
input_shape=start_end_month_window
```

正确职责划分：

1. Ops / TaskRun 保存自然月窗口意图：`start_month/end_month`。
2. resolver 根据 `start_end_month_window` 展开自然月首尾：`start_date/end_date`。
3. request builder 把日期格式化为 Tushare 源接口参数：`YYYYMMDD`。

不要在手动任务服务、自动任务服务或前端提前展开自然月首尾。否则同一个日期语义会散落在多个入口，后续会出现 TaskRun、resolver、request builder 口径不一致。

### 7.4 `ths_member`

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
5. 如果变更 `time_input`、`input_shape`、`calendar_policy` 或自动任务日期策略，必须覆盖完整链路：API/UI payload -> TaskRun.time_input_json -> `DatasetActionResolver.build_plan()` -> `PlanUnit.request_params`。
6. 只验证 TaskRun 创建成功不算完成；必须证明 resolver 生成的执行计划和源接口参数正确。

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
8. 禁止在 Ops、前端、自动任务服务中提前展开日期模型；展开必须发生在 resolver。
9. 禁止在 request builder 中决定业务日期语义；request builder 只能格式化已经归一化的计划值。
10. 禁止用节假日白名单、数据集 key 特判或 SQL 特例替代 `bucket_applicability_rule`。

---

## 10. 相关文档

1. [DatasetDefinition 单一事实源重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
2. [股票周/月线自然锚点日期模型修正方案 v1](/Users/congming/github/goldenshare/docs/architecture/stk-period-calendar-anchor-date-model-fix-plan-v1.md)
3. [DatasetDefinition 枚举语义参考 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-enum-reference-v1.md)
4. [数据集日期完整性审计设计 v2](/Users/congming/github/goldenshare/docs/ops/dataset-date-completeness-audit-design-v2.md)
5. [数据集日期完整性审计设计 v1（审查中心，历史草案）](/Users/congming/github/goldenshare/docs/ops/dataset-date-completeness-audit-design-v1.md)
