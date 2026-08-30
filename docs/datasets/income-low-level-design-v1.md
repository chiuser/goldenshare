# A 股利润表（`income`）数据集接入 LLD v1

状态：**代码已实现；`end_type` 可空修正待运营部署 migration `20260830_000166` 后重跑验收**
编写日期：2026-08-30
上位方案：[A 股利润表接入技术方案 v1](/Users/congming/github/goldenshare/docs/datasets/income-dataset-development.md)

## 1. 目标与边界

本 LLD 将已确认口径落实为可直接编码的文件、契约、SQL、执行链和测试门禁。目标链路是：

```text
Ops 手动任务 / 普通自动任务
  -> DatasetActionRequest(income.maintain)
  -> DatasetActionResolver
  -> 公告自然日 x report_type unit
  -> income_vip limit/offset 分页
  -> normalize + 全批次身份冲突校验
  -> raw_tushare.income               # HDD 唯一物理表
  -> core_serving.equity_income       # 普通 view
```

本轮只实现 `income` 数据集及三张财务报表共用的最小输入契约。明确不做：

1. 不加入 workflow，不增加 probe，不新增专用 Ops API。
2. 不暴露 `comp_type/period/start_date/end_date/is_calc/limit/offset` 为维护筛选项。
3. 不建立 serving 物理表，不双写，不保存 `raw_payload`。
4. 不限制运营可配置的总日期跨度，不另造“历史补数”入口。
5. 不改 `fina_indicator`、`express` 或其他既有数据集行为。
6. 不执行部署、migration、生产同步或页面验收。

## 2. 当前代码审计结论

### 2.1 已有能力可直接复用

| 能力 | 当前实现 | 本轮用法 |
| --- | --- | --- |
| 数据集事实源 | `src/foundation/datasets/definitions/low_frequency.py` | 新增 `income` Definition |
| 自然日逐日 unit | `unit_planner._expand_natural_dates()` | 复用日期展开算法 |
| enum 扇出 | `plan_helpers.resolve_enum_combinations()` | 将真实 `report_type` 数组展开为 unit |
| 分页 | `DatasetSourceClient._iter_request_pages()` | `offset_limit + page_limit=5000`，短页结束 |
| 内容指纹 | `compute_source_content_hash()` | 对完整 94 个源字段计算 SHA-256 |
| 重复/冲突 | `deduplicate_identical + batch_unique_key_fields` | 同内容去重，同身份异内容整 unit 失败 |
| raw-only 写入 | `DatasetWriter._write_raw_only_upsert()` | 只调用 raw DAO |
| 自动日期游标 | `since_last_success_day_range` | 普通自动任务生成公告自然日区间 |
| HDD migration | `20260829_000160_add_fina_indicator_dataset.py` | 复用 fail-closed tablespace 模式 |

### 2.2 不能直接照搬的地方

1. `build_natural_day_point_units` 当前把 `enum_combinations` 固定为 `[{}]`，不能生成“公告日 × 报表类型”。不得只填写 Definition 后误以为已经扇出。
2. `DatasetInputField` 只有 `enum_values`，没有选项中文标签和“虚拟全选”元数据。
3. `ActionParameterResponse` 与前端类型只返回原始字符串 options，现有两个页面会直接显示 `1..12`。
4. `DatasetRequestValidator` 的缺省值只读 `field.default`，而现有 enum 扇出默认值事实位于 `planning.enum_fanout_defaults`；需要统一为同一事实源，不能复制两份默认值。
5. 手动任务当前会先丢弃显式空数组、再补默认值；这会把用户明确清空误解成“使用默认全部”，需要在默认填充前拒绝显式空的必填多选。

### 2.3 CodeGraph 影响面

开发前 CodeGraph 已覆盖：

- `DatasetInputField -> definitions/_builder.py`
- `ActionParameter -> manual_action_query_service.py`
- `dataset_field_default_value -> catalog_query_service.py / manual_action_query_service.py`
- `DatasetUnitPlanner -> build_plan_units / resolve_enum_combinations`
- `DatasetNormalizer -> source_multiplicity_policy / batch_unique_key_fields`
- `DatasetWriter -> raw_only_upsert -> GenericDAO.bulk_upsert`

跨语言消费者另行核对了 `frontend/src/shared/api/types.ts`、手动任务页和自动任务页。共享契约变更不得遗漏其中任何一处。

## 3. 源字段契约

### 3.1 新增 contract 文件

新增：

```text
src/foundation/datasets/financial_statement_contracts.py
src/foundation/datasets/income_contracts.py
```

`financial_statement_contracts.py` 只保存三表共享事实：

```python
FINANCIAL_STATEMENT_REPORT_TYPE_VALUES = (
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
)

FINANCIAL_STATEMENT_REPORT_TYPE_LABELS = {
    "1": "合并报表",
    "2": "单季合并",
    "3": "调整单季合并表",
    "4": "调整合并报表",
    "5": "调整前合并报表",
    "6": "母公司报表",
    "7": "母公司单季表",
    "8": "母公司调整单季表",
    "9": "母公司调整表",
    "10": "母公司调整前报表",
    "11": "母公司调整前合并报表",
    "12": "母公司调整前报表（源站代码 12）",
}

FINANCIAL_STATEMENT_IDENTITY_FIELDS = (
    "ts_code", "ann_date", "f_ann_date", "end_date",
    "report_type", "comp_type", "update_flag",
)
```

`end_type` 仍属于完整源字段，但不属于身份。生产任务 `10189` 证明源站会返回 `end_type=NULL`；raw 必须原样保留该空值，不能伪造成某个报告期类型。

`income_contracts.py` 定义：

```python
INCOME_SOURCE_FIELDS       # 按 0033 源文档顺序固定的 94 字段
INCOME_DECIMAL_FIELDS      # 除 7 个前置身份字段和末尾 update_flag 外的 86 个 float 字段
INCOME_DATE_FIELDS = ("ann_date", "f_ann_date", "end_date")
```

文件加载时必须 fail-fast：

```python
if len(INCOME_SOURCE_FIELDS) != 94: ...
if len(INCOME_DECIMAL_FIELDS) != 86: ...
if tuple(INCOME_SOURCE_FIELDS[:7]) != (...): ...
if INCOME_SOURCE_FIELDS[-1] != "update_flag": ...
```

禁止从默认响应动态推断字段；94 字段必须逐项来自 [0033 源文档](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0033_利润表.md)，并由测试固定顺序和数量。

## 4. DatasetDefinition 编码方案

在 `src/foundation/datasets/definitions/low_frequency.py` 引入上述常量并新增一条 Definition：

| 字段 | 代码值 |
| --- | --- |
| `dataset_key/display_name` | `income / 利润表` |
| source | `tushare / income_vip / tushare.income` |
| `source_fields` | `INCOME_SOURCE_FIELDS` |
| request builder | `_income_vip_params` |
| date model | `natural_day / not_applicable / point_or_range / ann_date_or_start_end` |
| observed field | `ann_date` |
| unit builder | `build_financial_statement_units` |
| pagination | `offset_limit / 5000` |
| universe | `no_pool` |
| storage | `raw_only_upsert / raw_with_serving_view` |
| raw/serving | `raw_tushare.income / core_serving.equity_income` |
| freshness | 由集中表映射为 `event_run_trace` |
| transaction | `commit_policy=unit` |

`report_type` filter 必须是：

```python
{
    "name": "report_type",
    "field_type": "list",
    "required": True,
    "multi_value": True,
    "enum_values": FINANCIAL_STATEMENT_REPORT_TYPE_VALUES,
    "option_labels": FINANCIAL_STATEMENT_REPORT_TYPE_LABELS,
    "select_all_enabled": True,
    "display_name": "报表类型",
    "description": "默认维护全部报表类型；可取消全部后选择具体类型。",
}
```

planner 配置：

```python
"enum_fanout_fields": ("report_type",),
"enum_fanout_defaults": {
    "report_type": FINANCIAL_STATEMENT_REPORT_TYPE_VALUES,
},
```

质量配置：

```python
"reject_policy": "fail_unit_on_any_rejection",
"required_fields": (*FINANCIAL_STATEMENT_IDENTITY_FIELDS, "source_content_hash"),
"unit_date_field": "ann_date",
"duplicate_key_policy": "allow",
"batch_unique_key_fields": FINANCIAL_STATEMENT_IDENTITY_FIELDS,
"source_multiplicity_policy": "deduplicate_identical",
"empty_result_policy": "allow",
```

自动任务继续使用 `since_last_success_day_range`，`initial_start_date` 为唯一策略参数。Definition 不声明 workflow/probe。

## 5. 共享输入契约编码方案

### 5.1 Foundation 模型

修改 `src/foundation/datasets/models.py`：

```python
class DatasetInputField:
    ...
    option_labels: dict[str, str] = field(default_factory=dict)
    select_all_enabled: bool = False
```

在 `__post_init__` 或 builder 的统一校验中 fail-closed：

1. `option_labels` 的 key 必须属于 `enum_values`。
2. `select_all_enabled=True` 时必须同时满足 `multi_value=True` 且 `enum_values` 非空。
3. 不要求既有所有 enum 都配置中文标签；未配置时前端回退原值。

修改 `DatasetRequestValidator._normalize_input_params()`：只有字段完全缺失时，才从 `definition.planning.enum_fanout_defaults[field.name]` 补默认值；字段显式传 `[]` 时继续由 required 校验返回 `empty_not_allowed`。这样 planner、Ops 默认展示和直接 resolver 使用同一个默认值事实。

### 5.2 Ops 投影

修改：

```text
src/ops/action_catalog.py
src/ops/schemas/catalog.py
src/ops/queries/catalog_query_service.py
src/ops/queries/manual_action_query_service.py
src/ops/services/manual_action_service.py
src/ops/services/task_run_service.py
```

`ActionParameter` 与 `ActionParameterResponse` 增加：

```python
option_labels: dict[str, str]
select_all_enabled: bool
```

manual/catalog/automation 所有参数投影都从 `DatasetInputField` 原样传递，禁止只改其中一个 API。

默认与空值规则：

1. 字段缺失：从 `enum_fanout_defaults` 取得真实 `1..12`。
2. 字段显式为空：手动任务和 schedule 创建/更新均返回 422，不得补默认值。
3. 非法值或 `ALL/__ALL__`：由 options 和 sentinel guard 拒绝。
4. TaskRun `filters_json` 与 schedule `params_json.filters` 只保存真实值数组。

### 5.3 前端共享控件

新增一个通用共享控件，例如：

```text
frontend/src/shared/ui/ops-enum-multi-select.tsx
```

控件 props 只接收 `options/optionLabels/value/onChange/selectAllEnabled`，不得读取 dataset key。行为：

1. `value` 与完整 options 集合相等时，“全部”选中，真实选项全部选中且禁用。
2. 取消“全部”时 `onChange([])`；页面必填校验阻止提交。
3. 选择“全部”时 `onChange(options)`；payload 中没有虚拟值。
4. 标签使用 `optionLabels[option] ?? option`。

手动页和自动页都改为使用该控件；`frontend/src/shared/api/types.ts` 的所有 ActionParameter 结构同步增加两个字段。不得复制两套全选算法。

## 6. Planner 与请求参数

### 6.1 共享 unit builder

在 `src/foundation/ingestion/unit_planner.py` 新增并注册：

```python
build_financial_statement_units
```

伪代码：

```python
anchors = [trade_date] if point else _expand_natural_dates(start_date, end_date)
combinations = resolve_enum_combinations(
    request=request,
    fields=("report_type",),
    missing_field_defaults=definition.planning.enum_fanout_defaults,
)
combinations.sort(key=FINANCIAL_STATEMENT_REPORT_TYPE_VALUES.index)
return build_plan_units(
    anchors=anchors,
    enum_combinations=combinations,
    universe_values=[{}],
    ...,
)
```

该 builder 只负责三表共同的“自然日 × report_type”，不读取交易日历、不读取证券池、不请求源站。point 缺日期、range 缺边界或其他 run profile 必须返回现有结构化 planning error。

### 6.2 Request builder

在 `request_builders.py` 新增 `_income_vip_params`：

```python
if anchor_date is None:
    raise ValueError("利润表维护缺少公告日期锚点")
report_type = str(enum_values.get("report_type") or "").strip()
if report_type not in FINANCIAL_STATEMENT_REPORT_TYPE_VALUES:
    raise ValueError("利润表维护缺少或包含非法报表类型")
return {"ann_date": anchor_date.strftime("%Y%m%d"), "report_type": report_type}
```

不得把 request 原始区间透传给源端。`fields` 来自 Definition，`limit/offset` 由 source client 追加。

## 7. Normalizer 与修订覆盖

在 `row_transforms.py` 增加一个共享 helper 和 `_income_row_transform` 包装器：

1. 对字符串源字段清除 NUL；`ts_code` trim + upper。
2. 验证三个日期已被标准 normalizer 转成 `date`。
3. 验证 `report_type in 1..12`。
4. 验证 `update_flag in {"0", "1"}`。
5. `comp_type` 要求非空字符串；`end_type` 允许 `NULL` 或非空源值；允许 `comp_type="7"` 和未来合法值。
6. 按 `INCOME_SOURCE_FIELDS` 计算并写入 `source_content_hash`。

现有 normalizer 的执行顺序可直接满足修订语义：

```text
coerce -> hidden full-source hash -> row transform
       -> identical source row dedupe
       -> batch unique identity validation
```

因此：同身份同内容会在写入前去重；同身份不同内容会抛 `normalize.batch_unique_key_conflicting`，整 unit 不写；跨任务同身份内容变化则由 PostgreSQL upsert 覆盖旧字段。

## 8. ORM、DAO 与 Migration

### 8.1 ORM / DAO

新增：

```text
src/foundation/models/raw/raw_income.py
```

并更新：

```text
src/foundation/models/all_models.py
src/foundation/dao/factory.py
tests/test_foundation_table_model_registry.py
```

`RawIncome` 使用动态 mapped columns 生成 86 个 nullable `Numeric()` 字段；七个身份字段非空，`end_type` 作为 nullable 源字段显式声明，三个元数据字段显式声明。DAO 使用现有 `GenericDAO`，不新增专用 DAO，因为 normalizer 已在 DML 前完成批次冲突门禁。

### 8.2 Migration

实施时已重新执行 `alembic heads`；利润表初始建表 migration 为 `20260830_000163`。源站空值问题通过前向 migration `20260830_000166` 修正三张表，不改写已部署 migration 的历史语义。

upgrade 顺序：

1. `_assert_postgresql()`。
2. `_assert_hdd_tablespace()`；`gs_raw_cold_hdd` 不存在立即失败，且此时尚未创建 relation。
3. 创建 schema（幂等）。
4. 创建 `raw_tushare.income`，heap 指定 HDD。
5. 将主键索引显式迁到 HDD。
6. 创建两个二级索引并显式指定 HDD。
7. 创建 serving view。

主键和索引严格按技术方案：

```text
PK (ts_code, ann_date, f_ann_date, end_date,
    report_type, comp_type, update_flag)
IDX (ann_date, report_type, ts_code)
IDX (report_type, ts_code, end_date,
     update_flag DESC, f_ann_date DESC, ann_date DESC)
```

`20260830_000166` 在任何 DDL 前检查 PostgreSQL、`gs_raw_cold_hdd`、三张表存在且七字段身份无冲突；随后只重建三张表主键并执行 `end_type DROP NOT NULL`，不清表、不删业务行。

view SQL 核心：

```sql
SELECT DISTINCT ON (ts_code, end_date) <全部源字段>, source_content_hash, api_name, fetched_at
FROM raw_tushare.income
WHERE report_type = '1'
ORDER BY
  ts_code,
  end_date,
  CASE update_flag WHEN '1' THEN 0 ELSE 1 END,
  f_ann_date DESC,
  ann_date DESC,
  fetched_at DESC,
  comp_type DESC,
  end_type DESC,
  source_content_hash DESC;
```

`downgrade()` 必须 fail-closed 抛错，不自动删除业务事实。

## 9. Ops、目录与 freshness

1. `freshness_policies.py` 增加 `income: EVENT_RUN_TRACE`。
2. `dataset_catalog_views.py` 增加 `DatasetCatalogItem("income", "equity_financial", 30)`。
3. manual/catalog 由 Definition 自动投影，不增加页面私有数据集清单。
4. schedule capability 只返回普通 schedule；`probe_conditions=[]`。
5. workflow registry、probe registry、日期完整性审计 registry 中不得出现 `income`。

## 10. 文件级改动清单

### 新增

```text
docs/datasets/income-low-level-design-v1.md
src/foundation/datasets/financial_statement_contracts.py      # 三表共用，只新增一次
src/foundation/datasets/income_contracts.py
src/foundation/models/raw/raw_income.py
alembic/versions/<next>_add_income_dataset.py
frontend/src/shared/ui/ops-enum-multi-select.tsx               # 三表共用，只新增一次
frontend/src/shared/ui/ops-enum-multi-select.test.tsx
tests/test_financial_statement_datasets.py
```

### 修改

```text
src/foundation/datasets/models.py                              # 共享契约，只改一次
src/foundation/datasets/definitions/low_frequency.py
src/foundation/datasets/freshness_policies.py
src/foundation/ingestion/validator.py                          # enum fanout 默认事实
src/foundation/ingestion/unit_planner.py
src/foundation/ingestion/request_builders.py
src/foundation/ingestion/row_transforms.py
src/foundation/models/all_models.py
src/foundation/dao/factory.py
src/ops/action_catalog.py                                      # 共享投影，只改一次
src/ops/schemas/catalog.py
src/ops/queries/catalog_query_service.py
src/ops/queries/manual_action_query_service.py
src/ops/services/manual_action_service.py
src/ops/services/task_run_service.py
src/ops/catalog/dataset_catalog_views.py
frontend/src/shared/api/types.ts
frontend/src/pages/ops-v21-task-manual-tab.tsx
frontend/src/pages/ops-v21-task-auto-tab.tsx
tests/test_dataset_action_resolver.py
tests/test_dataset_definition_registry.py
tests/test_foundation_table_model_registry.py
tests/architecture/test_dataset_runtime_registry_guardrails.py
tests/web/test_ops_catalog_api.py
tests/web/test_ops_manual_actions_api.py
tests/web/test_ops_schedule_api.py
frontend/src/pages/ops-v21-task-manual-tab.test.tsx
frontend/src/pages/ops-v21-task-auto-tab.test.tsx
```

## 11. 测试矩阵

| 层 | 正向 | 负向 |
| --- | --- | --- |
| contract | 94/86 数量、顺序、中文标签齐全 | 字段漂移、标签 key 越界 fail-fast |
| Definition | raw/view、HDD、event freshness、默认 12 类型 | workflow/probe/audit 不得出现 |
| validator | 缺失 `report_type` 使用默认 12 类型 | 显式空、非法值、sentinel 拒绝 |
| planner | point=12 units；2 天 range=24 units；包含周末 | 不读交易日历；缺日期失败 |
| request | 仅 `ann_date + report_type` | 不泄漏 `period/comp_type/range/pagination` |
| source | 5000 满页继续，短页结束，所有页合并 | 中间页错误不能发布半套数据 |
| normalizer | `comp_type=7`、nullable 科目、同内容去重 | 缺身份、非法 flag/type、同身份异内容失败 |
| writer | 同身份跨任务修订覆盖；只写 raw | 不调用 serving DAO；任一 reject 阻断 unit |
| migration | heap/PK/两索引均 HDD；view 唯一选择正确 | 无 tablespace 在建表前失败；downgrade 拒绝 |
| Ops/API | 中文标签、默认全选、手动/自动可见 | 空选择/非法值 422，无 probe/workflow |
| frontend | 全选、取消全选、子集选择、payload 真实数组 | payload 不出现虚拟 all，两个页面行为一致 |

## 12. 开发顺序与停止条件

建议里程碑：

1. `I0`：冻结 94 字段 contract 与 migration head。
2. `I1`：落共享 enum contract、validator、unit builder 及测试。
3. `I2`：落 ORM/DAO/migration/view。
4. `I3`：落 Definition/request/normalizer/writer 注册。
5. `I4`：落 Ops 与前端共享全选控件。
6. `I5`：完整回归与文档收口。

出现以下任一情况必须停止，不能用临时分支绕过：

1. 实际 connector 显式 94 字段与源文档不一致。
2. 一个 `ann_date + report_type` 分页出现同身份不同内容。
3. migration 无法证明所有物理 relation 在 HDD。
4. serving 选择规则无法在 SQL 中确定性复现。
5. 页面或 API 仍需按 `dataset_key=income` 私自拼接标签/全选状态。

## 13. 验证命令

```bash
uv run ruff check src/foundation/datasets src/foundation/ingestion src/foundation/models/raw/raw_income.py src/foundation/dao/factory.py src/ops tests/test_financial_statement_datasets.py
uv run pytest -q tests/test_financial_statement_datasets.py tests/test_dataset_definition_registry.py tests/test_foundation_table_model_registry.py
uv run pytest -q tests/web/test_ops_catalog_api.py tests/web/test_ops_manual_actions_api.py tests/web/test_ops_schedule_api.py
uv run pytest -q tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_dataset_runtime_registry_guardrails.py
uv run goldenshare ingestion-lint-definitions
cd frontend && npm run test -- ops-enum-multi-select ops-v21-task-manual-tab ops-v21-task-auto-tab
cd /Users/congming/github/goldenshare && python3 scripts/check_docs_integrity.py
```

## 14. 验收口径

代码完成只能说明“可交付运营部署”，不能直接把数据集标为生产验收完成。开发验收必须证明：

1. Definition、计划、请求、字段、身份、HDD 和 view 口径全部与上位方案一致。
2. 默认 12 类型与任意子集均能生成准确 unit 数和源参数。
3. 空类型是成功空 unit，源端冲突或 reject 是整 unit 失败。
4. raw 只存一份物理事实，serving view 每公司每报告期唯一。
5. 手动与自动页面只消费后端参数契约，不自行推断事实。

初始历史维护范围仍由运营后续决定，不阻塞开发。
