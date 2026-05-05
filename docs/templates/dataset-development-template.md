# 数据集开发说明模板（DatasetDefinition 主线）

> 使用说明：
> - 写数据集开发文档之前，必须先阅读仓库根目录 `AGENTS.md`，确认当前硬约束和禁止项。
> - 每新增一个数据集，先复制本模板生成独立文档，放在 `docs/datasets/` 目录。
> - 文档命名建议：`<dataset-key>-dataset-development.md`。
> - 未完成本文档，不得进入编码、发版或远程同步。
> - 本模板以当前新架构为准：数据集事实源是 `DatasetDefinition`，执行主链是 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor`，任务观测主链是 Ops TaskRun。

---

## 0. 架构基线与禁止项

### 0.1 当前必须遵守的主线

1. 数据集身份、来源、输入、日期模型、落库、规划、清洗、能力、观测、质量、事务，全部收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition`。
2. 维护动作统一为 `action=maintain`，动作 key 由 `DatasetDefinition.action_key("maintain")` 派生，格式为 `<dataset_key>.maintain`。
3. 执行计划由 `DatasetActionResolver` 根据 `DatasetDefinition` 生成，执行器只消费 `DatasetExecutionPlan` 和 plan units。
4. Ops 手动任务、自动任务、任务详情、数据状态、数据源卡片均消费由 `DatasetDefinition` 派生的事实，不在前端或 Ops 查询层重新拼装数据集事实。
5. 任务运行与问题诊断只走 TaskRun 主链：`ops.task_run`、`ops.task_run_node`、`ops.task_run_issue`。
6. 必须遵守三层分离：Ops / TaskRun 只保存用户或调度意图，`DatasetActionResolver` 负责归一化为执行计划，request builder 只负责源接口字段映射和格式化。

### 0.2 禁止项

1. 不得新增或恢复旧三类同步命令作为用户可见或 API 主执行模型。
2. 不得新增旧同步服务包或旧 `operations/platform` 主实现。
3. 不得在 foundation 中依赖 ops、biz、app、platform、operations。
4. 不得使用 `__ALL__` / `__all__` 这类业务占位值污染请求参数、落库行或 source key。需要全量枚举时，必须在 `enum_fanout_defaults` 中显式列出真实枚举值。
5. 不得引入 checkpoint / acquire / 定点跳过语义；除非项目负责人明确提出该能力，并先完成专项方案评审。
6. 不得把状态写入失败设计成回滚业务数据；Ops/TaskRun/freshness/snapshot/schedule 等状态写入只能影响观测状态。
7. 不得写“临时方案”。如果事实或能力还没准备好，应标为“不支持 / 暂不接入”，不要把临时路径做进主链。
8. 不得在 Ops、前端、自动任务服务中提前展开日期模型，例如把自然月窗口提前转成源接口 `start_date/end_date`。这类展开必须由 resolver 根据 `DatasetDefinition.date_model` 完成。

---

## 1. 标准交付流程

1. 固定源站事实：官方文档、输入参数、输出字段、分页、限速、更新时间。
2. 新增或更新 `docs/sources/**` 源站文档；Tushare 文档必须同步 `docs/sources/tushare/docs_index.csv`。
3. 完成本文档，明确 `DatasetDefinition` 十段事实和执行/落库/观测方案。
4. 新增 SQLAlchemy ORM 模型、DAO、Alembic 迁移；确认 ORM 能被 `table_model_registry()` 自动发现。
5. 在正确的 `src/foundation/datasets/definitions/<domain>.py` 中新增 `DATASET_ROWS` 定义。
6. 补齐 ingestion 能力：request builder、unit builder、row transform、writer 路径、分页、reject reason、codebook。
7. 确认 Ops 派生能力：manual actions、catalog、freshness、dataset cards、TaskRun 详情。
8. 补测试：definition、resolver、unit planner、normalizer、writer、Ops API、架构门禁。
9. 本地执行门禁并记录命令。
10. 发版前在开发库跑最小真实同步，确认业务数据、TaskRun 详情、数据状态和数据源卡片一致。

---

## 2. 基本信息

- 数据集 key：
- 中文显示名：
- 所属定义文件：`src/foundation/datasets/definitions/<domain>.py`
- 所属域：`reference_master` / `market_equity` / `market_fund` / `index_series` / `board_hotspot` / `moneyflow` / `low_frequency` / 其他（新增域需先评审）
  - 说明：这里是 `DatasetDefinition.domain` 的底层领域事实，不等于前端或 Ops 的用户可见展示分组。
- 数据源：`tushare` / `biying` / 其他
- 源站 API 名称：
- 源站文档链接：
- 本地源站文档路径：
- 文档抓取日期：
- 是否对外服务：是 / 否
- 是否多源融合：是 / 否
- 是否纳入自动任务：是 / 否
- 是否纳入日期完整性审计：是 / 否
- Ops 展示分组 key：
- Ops 展示分组名称：
- Ops 展示分组顺序：

---

## 3. 源站接口分析

### 3.1 输入参数

| 参数名 | 类型 | 必填 | 说明 | 类别（时间/枚举/代码/分页/其他） | 是否给运营用户填写 | 对应 `DatasetInputField` | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |

### 3.2 输出字段

| 字段名 | 类型 | 含义 | 是否落 raw | 是否进入 serving/core | 清洗规则 |
| --- | --- | --- | --- | --- | --- |

### 3.3 源端行为

- 是否分页：
- 分页参数与结束条件：
- 是否限速或有积分限制：
- 是否需要按代码池、日期、月份、枚举拆分请求：
- 是否有上游脏值或缺字段风险：
- 是否有级联依赖（例如先同步指数/板块主表，再同步成分）：

---

## 4. DatasetDefinition 事实设计

### 4.1 `identity`

```python
"identity": {
    "dataset_key": "",
    "display_name": "",
    "description": "",
    "aliases": (),
    "logical_key": None,
    "logical_priority": 100,
}
```

- `dataset_key`：
- `display_name`：
- `description`：
- `aliases`：
- `logical_key` / `logical_priority`（多源或同逻辑数据集时必填）：

### 4.2 `domain`

```python
"domain": {
    "domain_key": "",
    "domain_display_name": "",
    "cadence": "daily",
}
```

- `domain_key`：
- `domain_display_name`：
- `cadence`：`daily` / `weekly` / `monthly` / `intraday` / `low_frequency` / `snapshot` / `on_demand`

### 4.3 `source`

```python
"source": {
    "source_key_default": "",
    "source_keys": ("",),
    "adapter_key": "",
    "api_name": "",
    "source_fields": (),
    "source_doc_id": "",
    "request_builder_key": "generic",
    "base_params": {},
}
```

- `source_key_default` 必须属于 `source_keys`。
- `source_fields` 必须与源站文档和实际请求字段一致。
- 自定义请求参数构造器必须注册在 `src/foundation/ingestion/request_builders.py`。
- 不得从 `dataset_key` 前缀反推 source；source 事实只能来自这里。

### 4.4 `date_model`

```python
"date_model": {
    "date_axis": "",
    "bucket_rule": "",
    "window_mode": "",
    "input_shape": "",
    "observed_field": None,
    "audit_applicable": False,
    "not_applicable_reason": None,
    "bucket_window_rule": None,
    "bucket_applicability_rule": "always",
}
```

- `date_axis`：`trade_open_day` / `natural_day` / `month_key` / `month_window` / `none`
- `bucket_rule`：`every_open_day` / `week_last_open_day` / `month_last_open_day` / `every_natural_day` / `week_friday` / `month_last_calendar_day` / `every_natural_month` / `month_window_has_data` / `not_applicable`
- `window_mode`：`point` / `range` / `point_or_range` / `none`
- `input_shape`：按现有代码枚举选择，例如 `trade_date_or_start_end`、`month_or_range`、`start_end_month_window`、`ann_date_or_start_end`、`none`
- `observed_field`：用于 freshness 和日期审计观测的目标表字段；没有业务日期时填 `None`
- `audit_applicable`：
- `not_applicable_reason`：
- `bucket_window_rule`：候选锚点对应的业务窗口；默认 `None`，仅在候选桶需要按窗口判断是否可产出时填写，例如 `iso_week` / `natural_month`
- `bucket_applicability_rule`：候选桶是否应纳入 expected bucket；默认 `always`，股票周/月线长假排除使用 `requires_open_trade_day_in_bucket`

说明：
- 周线/月线不能按名称猜口径，必须以源接口文档为准。
- 如果源接口要求每周/每月最后一个交易日，使用 `week_last_open_day` / `month_last_open_day`。
- 如果源接口要求自然周周五或自然月最后一天，使用 `week_friday` / `month_last_calendar_day`；即使字段名叫 `trade_date`，也不能误建模成交易日。
- 如果自然锚点对应的业务窗口没有开市日就不应产出数据，必须显式填写 `bucket_window_rule` 与 `bucket_applicability_rule`，不得在审计 SQL 或前端用节假日白名单兜底。
- 快照/主数据通常使用 `date_axis="none"`、`bucket_rule="not_applicable"`，并给出 `not_applicable_reason`。
- 前端日期控件、审计能力、freshness 口径都从 `date_model` 派生，不允许另建第二套日期规则。

### 4.4.1 时间意图归一化设计

必须明确本数据集的时间输入在三层中的形态：

| 层级 | 本数据集应保存或生成什么 | 示例 |
| --- | --- | --- |
| Ops / TaskRun / Schedule | 用户或调度意图 | `trade_date`、`start_date/end_date`、`month`、`start_month/end_month` |
| `DatasetActionResolver` | 标准化执行计划时间范围和 units | 自然月窗口展开为月初/月末，公告日区间扇开为自然日 units |
| request builder | 源接口参数字段和值 | `date` 格式化为 `YYYYMMDD`，字段名映射为源端要求 |

填写项：

- Ops/TaskRun 保存的 `time_input` 形态：
- resolver 需要做的归一化：
- request builder 需要做的源接口格式化：
- 是否存在 `calendar_policy`：是 / 否；如有，只能生成调度意图，不能绕过 resolver 生成源接口参数。

常见口径：

- `month_or_range`：上层传 `month` 或 `start_month/end_month`，resolver 归一化月份键和日期范围。
- `start_end_month_window`：上层传 `start_month/end_month` 表达自然月窗口，resolver 展开为 `start_date/end_date`，request builder 再格式化为源接口日期。
- `ann_date_or_start_end`：上层传公告日或日期区间，resolver/planner 决定公告日锚点，request builder 映射为源端 `ann_date`。
- `trade_date_or_start_end`：上层传交易日或日期区间，resolver/planner 根据 `date_axis/bucket_rule` 生成执行锚点。

反例：

- 因为源接口最终需要 `start_date/end_date`，就在手动任务或自动任务服务中提前展开自然月窗口。
- 因为源接口字段叫 `trade_date`，就把自然周五或自然月末误当成交易日。
- 在前端根据 `dataset_key` 手写日期转换逻辑。

### 4.5 `input_model`

```python
"input_model": {
    "time_fields": (),
    "filters": (),
    "required_groups": (),
    "mutually_exclusive_groups": (),
    "dependencies": (),
}
```

| 字段 | 类型 | 是否必填 | 默认值 | 枚举值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |

约束：
- 时间字段必须与 `date_model.input_shape` 一致。
- 给用户看的 `display_name` 必须是中文业务名，不得暴露内部字段含义。
- 枚举多选如果要默认展开，必须同步配置 `planning.enum_fanout_defaults`。

### 4.6 `storage`

```python
"storage": {
    "raw_dao_name": "",
    "core_dao_name": "",
    "target_table": "",
    "delivery_mode": "",
    "layer_plan": "",
    "std_table": None,
    "serving_table": None,
    "raw_table": "",
    "conflict_columns": None,
    "write_path": "raw_core_upsert",
}
```

- `raw_table`：
- `target_table`：
- `delivery_mode`：
- `layer_plan`：例如 `raw-only`、`raw->core`、`raw->serving`、`raw->std->serving`
- `raw_dao_name`：
- `core_dao_name`：
- `conflict_columns`：
- `write_path`：

常见 `write_path`：
- `raw_only_upsert`
- `raw_core_upsert`
- `raw_core_snapshot_insert_by_trade_date`
- `raw_std_publish_stock_basic`
- `raw_std_publish_moneyflow`
- `raw_std_publish_moneyflow_biying`
- `raw_index_period_serving_upsert`

如果需要新增 `write_path`，必须说明为什么现有路径不能承载，并补 writer 测试。

### 4.7 `planning`

```python
"planning": {
    "universe_policy": "no_pool",
    "enum_fanout_fields": (),
    "enum_fanout_defaults": {},
    "pagination_policy": "none",
    "page_limit": None,
    "chunk_size": None,
    "max_units_per_execution": None,
    "unit_builder_key": "generic",
}
```

- `universe_policy`：`no_pool` 表示明确不按对象池展开；`pool` 表示按 `planning.universe` 声明的对象池展开；`none` 只表示未定义，不得用于新数据集。
- `enum_fanout_fields`：哪些枚举字段参与 unit 扇出。
- `enum_fanout_defaults`：用户未填写枚举时默认展开的真实枚举值集合。
- `pagination_policy`：`none` / `offset_limit` / 其他现有策略。
- `page_limit`：
- `chunk_size`：
- `max_units_per_execution`：
- `unit_builder_key`：如需自定义，必须在 `src/foundation/ingestion/unit_planner.py` 有清晰实现和测试。

写入量评估：
- 必须估算单个 unit 的最大写入行数：
- 必须估算单个数据库事务的最大写入行数：
- 若单个 unit 可能形成超大事务，必须先调整 unit 拆分规则，不能靠分页掩盖事务风险。

### 4.8 `normalization`

```python
"normalization": {
    "date_fields": (),
    "decimal_fields": (),
    "required_fields": (),
    "row_transform_name": None,
}
```

- `date_fields`：
- `decimal_fields`：
- `required_fields`：
- `row_transform_name`：

约束：
- 行转换函数必须注册在 `src/foundation/ingestion/row_transforms.py`，不能放在 request builder 里。
- `required_fields` 缺失应进入 reject 统计，不得静默写入不完整业务行。
- 新增 row transform 必须补 normalizer 测试。

### 4.9 `capabilities`

```python
"capabilities": {
    "actions": (
        {
            "action": "maintain",
            "manual_enabled": True,
            "schedule_enabled": True,
            "retry_enabled": True,
            "supported_time_modes": (),
        },
    ),
}
```

- 是否允许手动维护：
- 是否允许自动调度：
- 是否允许重试：
- `supported_time_modes`：`point` / `range` / `none`

### 4.10 `observability`、`quality`、`transaction`

```python
"observability": {
    "progress_label": "",
    "observed_field": None,
    "audit_applicable": False,
},
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": (),
},
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": False,
    "write_volume_assessment": "",
}
```

- `observability.progress_label`：
- `observability.observed_field` 必须与 `date_model.observed_field` 保持一致。
- `quality.required_fields` 必须覆盖不能缺失的业务主键和日期字段。
- `transaction.commit_policy` 当前必须为 `unit`。
- `transaction.write_volume_assessment` 必须写人话，说明单事务写入量如何被控制。

---

## 5. 表结构、DAO 与迁移设计

### 5.1 表设计

#### A. `raw_<source>.<table>`

- ORM 模型路径：
- 主键：
- 字段清单：
- 审计字段：
- 索引：
- 是否分区：

#### B. `*_std.<table>`（如启用）

- ORM 模型路径：
- 标准字段映射：
- 清洗规则：
- 主键与索引：

#### C. `core` / `core_serving` / `core_serving_light`（如启用）

- ORM 模型路径：
- 对外字段口径：
- 主键：
- upsert 冲突列：
- 索引：
- 是否分区：

### 5.2 工程硬约束

1. 数值类型默认使用 `DOUBLE PRECISION`；若使用 `NUMERIC`，必须逐字段说明理由。
2. 对于源站中语义明确、格式稳定的日期字符串（例如 `YYYYMMDD`），raw 层允许直接落 PostgreSQL `date`；字段名保持不变，不额外保留第二份字符串镜像。
3. 有 `trade_date` 且数据量较大的表，必须评估分区；默认年分区，超大表可月分区。
4. 有 `ts_code + trade_date` 语义时，默认主键为 `(ts_code, trade_date)`，并评估 `trade_date` 方向索引。
5. 新 ORM 模型必须能被 `src.foundation.models.table_model_registry.table_model_registry()` 发现；freshness 观测依赖该 registry。
6. 新表必须有 Alembic 迁移，迁移和 ORM 模型字段必须一致。

### 5.3 DAO

- Raw DAO：
- Core/Serving DAO：
- 是否需要新增 DAOFactory 属性：
- `bulk_upsert` / `insert` / 特殊写入策略：
- 幂等策略：

---

## 6. Ingestion 实现设计

### 6.1 请求构造

- `request_builder_key`：
- 函数位置：`src/foundation/ingestion/request_builders.py`
- 输入来自 `DatasetActionRequest.time_input` / `filters` / `base_params`：
- 是否需要源端字段名转换：
- 是否需要默认参数：
- 是否只做源接口格式化，不承担业务日期语义判断：
- 如果需要日期、月份或窗口转换，请说明为何不应放在 resolver：

### 6.2 Unit 规划

- `unit_builder_key`：
- unit 维度：日期 / 月份 / 股票 / 指数 / 板块 / 枚举 / 组合
- unit_id 组成：
- `progress_context` 字段：
- 单 unit 最大数据量评估：
- 单次执行最大 unit 数评估：

### 6.3 Source Client 与分页

- adapter：`tushare` / `biying` / 其他
- `pagination_policy`：
- 单页参数：
- 结束条件：
- 限速策略：
- 源端错误映射：

### 6.4 Normalizer

- 字段类型转换：
- 日期转换：
- decimal/float 转换：
- required 字段拒绝策略：
- row transform：
- reject reason code：

### 6.5 Writer

- `write_path`：
- raw 写入：
- serving/core 写入：
- 是否先删后写：
- 幂等写入策略：
- 冲突列：
- 事务边界：每个 unit 一个业务数据事务

### 6.6 结构化错误与 codebook

- 新增 `error_code`：
- 中文语义：
- 建议动作：
- 是否需要加入 `src/foundation/ingestion/codebook.py`：
- 前端是否能通过 codebook 展示，不硬编码语义：

---

## 7. Ops、TaskRun 与页面派生

### 7.1 手动任务

- `GET /api/v1/ops/manual-actions` 是否能看到该数据集：
- 分组是否来自 `DatasetDefinition.domain`：
- 名称是否来自 `DatasetDefinition.display_name`：
- 时间控件是否由 `date_model` 正确派生：
- filter 控件是否由 `input_model.filters` 正确派生：
- 提交的 `time_input` 是否仍是用户意图，而不是源接口参数：
- 提交接口：`POST /api/v1/ops/manual-actions/<dataset_key>.maintain/task-runs`

### 7.2 自动任务

- 是否允许 `schedule_enabled=True`：
- 自动任务是否只选择数据集动作，不暴露底层执行路径：
- 如果有 `calendar_policy`，它生成的是哪种调度意图：
- 是否确认自动任务没有提前展开日期模型或生成源接口参数：
- 是否需要放入 workflow：如需要，使用 `docs/templates/workflow-development-template.md` 另写方案。

### 7.3 TaskRun 观测

参考：[Ops TaskRun 执行观测模型重设计方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)

必须填写：

- 当前对象类型：股票 / 指数 / 板块 / 日期 / 月份 / 枚举 / 其他
- 当前对象标识字段：
- 当前窗口字段：
- `progress_context` 示例：
- 失败时 `TaskRunIssue.object_json` 示例：
- 是否有 `rows_rejected`：
- 是否有 `rejected_reason_counts` / `rejected_reason_samples`：

展示原则：
- 页面主指标只展示最终已提交结果，不把中间尝试写入量当成已入库结果。
- 后端输出结构化 token，Ops 层负责转换为用户可读展示。
- 不得在前端按 dataset_key 写专用文案分支。

### 7.4 数据状态、数据源卡片与 freshness

- `target_table` 是否能在 `table_model_registry()` 找到 ORM 模型：
- `date_model.observed_field` 是否存在于目标 ORM 模型：
- 无日期数据集是否明确展示最近同步迹象而非新鲜/滞后：
- 数据源卡片是否显示正确 source：
- `ops-rebuild-dataset-status` 后是否能生成正确快照：

### 7.5 日期完整性审计

- `audit_applicable`：
- 审计日期桶：
- 期望桶生成规则：
- 实际桶读取字段：
- 不适用原因：

---

## 8. 测试与门禁

### 8.1 必补测试

- DatasetDefinition registry：
  - 新 dataset key 在正确 domain 文件中
  - `tests/architecture/test_dataset_runtime_registry_guardrails.py` 的 domain key 矩阵已更新
- Resolver / planner：
  - point / range / none / month 视数据集能力覆盖
  - unit_count、unit_id、request_params、progress_context 正确
- Request builder：
  - 时间参数映射
  - filter / enum 参数映射
  - 不产生非法 ALL sentinel
- Normalizer：
  - date / decimal / required fields
  - row transform 可注册并可执行
  - reject reason 统计
- Writer：
  - 幂等 upsert
  - conflict_columns
  - 单 unit 事务边界
- Ops API：
  - manual-actions
  - catalog
  - task-runs
  - freshness / dataset-cards
- Frontend（如显示或交互变化）：
  - 页面能看到动作
  - 表单控件正确
  - 任务详情和数据状态展示正确

### 8.2 必跑命令

```bash
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
pytest -q tests/test_dataset_definition_registry.py tests/test_dataset_action_resolver.py tests/test_dataset_unit_planner.py
pytest -q tests/architecture/test_dataset_runtime_registry_guardrails.py tests/architecture/test_dataset_maintenance_refactor_guardrails.py tests/architecture/test_arch_no_all_sentinel.py
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare ingestion-lint-definitions
python3 scripts/check_docs_integrity.py
```

按改动范围追加：

```bash
pytest -q tests/test_dataset_normalizer.py
pytest -q tests/test_dataset_writer_<dataset>.py
pytest -q tests/web/test_ops_manual_actions_api.py tests/web/test_ops_catalog_api.py tests/web/test_ops_freshness_api.py
cd frontend && npm run typecheck
```

### 8.3 验收勾选

- [ ] 源站文档与 docs index 已更新
- [ ] DatasetDefinition 十段事实完整
- [ ] 新数据集没有旧执行术语或旧路由
- [ ] 没有新增 `__ALL__` / `__all__` 业务占位值
- [ ] 没有新增 checkpoint / acquire 语义
- [ ] ORM、DAO、迁移一致
- [ ] `target_table` 能被 table model registry 发现
- [ ] 日期模型能驱动手动任务、freshness 和审计
- [ ] Ops 展示目录配置已确认，数据源页 / 手动任务 / 自动任务的展示分组一致
- [ ] Ops/TaskRun 保存的是用户或调度意图，没有提前展开为源接口参数
- [ ] `DatasetActionResolver` 测试覆盖该数据集的时间输入归一化
- [ ] 测试覆盖 `TaskRun.time_input_json -> DatasetActionResolver.build_plan() -> PlanUnit.request_params`
- [ ] 单事务写入量已真实评估并写入 `transaction.write_volume_assessment`
- [ ] request builder、unit planner、normalizer、writer 均有测试
- [ ] TaskRun 详情展示可读，无重复错误信息
- [ ] 数据源卡片和数据状态页展示正确
- [ ] 门禁命令已通过并记录输出

---

## 9. 发布与回滚

- Alembic 迁移：
- 发布顺序：
- 是否需要重建数据状态：`goldenshare ops-rebuild-dataset-status`
- 最小真实同步命令：
- 验收查询 SQL：
- 回滚方式：
- 风险点与处理：

---

## 10. 本次交付快照

- 当前已支持：
- 当前不支持：
- 已知风险：
- 后续计划：
