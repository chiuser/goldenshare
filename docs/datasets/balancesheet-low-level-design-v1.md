# A 股资产负债表（`balancesheet`）数据集接入 LLD v1

状态：**共享 `end_type` 规范化 LLD 已按 Prod 现状对齐；`20260830_000166` 已部署，代码与 migration `20260830_000167` 待实现**
编写日期：2026-08-30
上位方案：[A 股资产负债表接入技术方案 v1](/Users/congming/github/goldenshare/docs/datasets/balancesheet-dataset-development.md)

## 1. 目标与边界

本 LLD 只实现 `balancesheet_vip -> raw_tushare.balancesheet -> core_serving.equity_balancesheet`。raw 在 HDD 保留 158 个源字段、12 种报表类型和全部源站版本；serving 普通 view 提供每家公司、每个报告期唯一最新合并报表。

```text
DatasetActionRequest(balancesheet.maintain)
  -> 公告自然日 x report_type units
  -> balancesheet_vip 全部分页
  -> normalize / source identity gate
  -> raw_tushare.balancesheet              # gs_raw_cold_hdd
  -> core_serving.equity_balancesheet      # 普通 view
```

边界固定：不建 serving 表、不双写、不加工作流、不加 probe、不暴露 `comp_type/period`、不限制总输入跨度、不执行生产部署或同步。

## 2. 代码审计与复用结论

### 2.1 复用主链

1. Definition 落在 `definitions/low_frequency.py`，不新建第二套 registry。
2. 日期逐日算法复用 `_expand_natural_dates()`；报表类型使用 `resolve_enum_combinations()`。
3. source client 已支持 `offset_limit`，单 unit 全部分页合并后才进入 normalize/write。
4. `source_multiplicity_policy="deduplicate_identical"` 会先去掉分页重叠的完全相同行。
5. `batch_unique_key_fields` 会在 DML 前拒绝“同身份、不同内容”；无需专用 DAO 或新写入路径。
6. `raw_only_upsert` 与 `GenericDAO.bulk_upsert` 支持跨任务同身份内容修订覆盖。
7. HDD fail-closed migration 与普通 view 模式可复用 `fina_indicator` 实现方式。

### 2.2 必须新增的能力

1. 当前 `build_natural_day_point_units` 不处理 enum fanout，必须使用三表共享的 `build_financial_statement_units`。
2. 当前 `DatasetInputField -> ActionParameterResponse -> frontend` 缺少 option 中文标签和虚拟全选元数据。
3. 缺失 filter 的默认值需要统一读取 `enum_fanout_defaults`；显式空数组仍必须拒绝。

共享契约只实现一次。若 `income` 已先落地，本数据集只消费 [income LLD 第 5 节](/Users/congming/github/goldenshare/docs/datasets/income-low-level-design-v1.md) 的通用能力，不复制代码；若 `balancesheet` 先开发，则必须按该共享设计完整落地后再注册本数据集。

## 3. 字段与身份 contract

新增：

```text
src/foundation/datasets/balancesheet_contracts.py
```

复用：

```text
src/foundation/datasets/financial_statement_contracts.py
```

`balancesheet_contracts.py` 必须定义：

```python
BALANCESHEET_SOURCE_FIELDS       # 0036 源文档固定顺序的 158 字段
BALANCESHEET_DECIMAL_FIELDS      # 150 个 float 字段
BALANCESHEET_DATE_FIELDS = ("ann_date", "f_ann_date", "end_date")
```

静态门禁：

1. `len(BALANCESHEET_SOURCE_FIELDS) == 158`。
2. 前七字段必须是 `ts_code, ann_date, f_ann_date, end_date, report_type, comp_type, end_type`。
3. 最后一字段必须是 `update_flag`。
4. `len(BALANCESHEET_DECIMAL_FIELDS) == 150`。
5. 七字段身份必须直接复用 `FINANCIAL_STATEMENT_IDENTITY_FIELDS`，不得单独抄一份后漂移；`end_type` 由 `end_date` 唯一推导、落库后非空，但不重复进入身份。

完整字段只以 [0036 源文档](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0036_资产负债表.md) 和该 contract tuple 为代码事实。默认响应只有 152 字段，因此 source fields 不能由样本动态生成。

## 4. DatasetDefinition

在 `low_frequency.py` 新增：

| 维度 | 代码值 |
| --- | --- |
| identity | `balancesheet / 资产负债表` |
| source | `balancesheet_vip`, `BALANCESHEET_SOURCE_FIELDS`, `tushare.balancesheet` |
| request builder | `_balancesheet_vip_params` |
| date model | `natural_day / not_applicable / point_or_range / ann_date_or_start_end` |
| input | 公告日期点/区间 + 必填多选 `report_type` |
| planning | `build_financial_statement_units`, `offset_limit`, `5000`, `no_pool` |
| storage | `raw_only_upsert`, `raw_with_serving_view` |
| target | `raw_tushare.balancesheet` |
| serving | `core_serving.equity_balancesheet` |
| freshness | `event_run_trace` |
| audit | `False` |
| capability | manual + regular schedule |

filter 与 planning 固定为：

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
}

"enum_fanout_fields": ("report_type",),
"enum_fanout_defaults": {"report_type": FINANCIAL_STATEMENT_REPORT_TYPE_VALUES},
```

质量与事务：

```python
"required_fields": (*FINANCIAL_STATEMENT_IDENTITY_FIELDS, "end_type", "source_content_hash"),
"unit_date_field": "ann_date",
"batch_unique_key_fields": FINANCIAL_STATEMENT_IDENTITY_FIELDS,
"source_multiplicity_policy": "deduplicate_identical",
"reject_policy": "fail_unit_on_any_rejection",
"empty_result_policy": "allow",
"commit_policy": "unit",
```

schedule time policy 为 `since_last_success_day_range`；不声明 probe/workflow。

## 5. Unit 与请求参数

### 5.1 Unit

共享 `build_financial_statement_units` 生成：

- point：1 个公告日 × 已选类型数。
- range：闭区间内每个自然日 × 已选类型数。
- 周末与节假日也生成 unit，不读 `trade_calendar`。
- 默认缺失 `report_type` 时从 `enum_fanout_defaults` 得到真实 `1..12`。
- 显式空数组、非法类型和 `ALL/__ALL__` 在 planning 前失败。

例如 `2026-08-29~2026-08-30` 默认生成 24 个 unit，而不是 2 个宽请求，也不是 2 个不带报表类型的请求。

### 5.2 Request builder

`_balancesheet_vip_params` 只返回：

```json
{"ann_date":"20260830","report_type":"1"}
```

实现必须验证 anchor 和 report type。不得向源端传 `comp_type/period/start_date/end_date`；`fields` 由 Definition 固定为 158 字段；`limit/offset` 由 source client 添加。

### 5.3 空结果

某个报表类型没有数据是源站合法事实。source 返回短空页后，该 unit 以 `fetched=0/normalized=0/written=0/rejected=0` 成功结束，不能触发 `raise_if_all_rejected` 或失败补丁。

## 6. Normalizer

在 `row_transforms.py` 新增 `_balancesheet_row_transform`，内部调用三表共享 helper：

1. 清除所有字符串中的 NUL。
2. `ts_code` trim + upper。
3. `ann_date/f_ann_date/end_date` 必须为 `date`。
4. `report_type` 只允许 `1..12`。
5. `update_flag` 只允许 `0/1`。
6. `comp_type` 要求非空但不建立封闭枚举；`comp_type=7` 必须通过。
7. 共享 helper 按 `end_date` 推导 `end_type=1..4`：缺失补齐，非法或与日期矛盾时拒绝。
8. 完成规范化后使用 158 个 `BALANCESHEET_SOURCE_FIELDS` 计算 `source_content_hash`；批次去重与冲突比较优先使用该规范化指纹。

数值列全部 nullable `Decimal`。不得把不适用银行/保险/证券的科目写成 0。

现有 normalizer 已提供所需批次语义：

```text
完全相同源行 -> deduplicate_identical -> 只保留一行
同身份不同内容 -> batch_unique_key_conflicting -> 整 unit 失败
跨任务同身份修订 -> raw upsert -> 覆盖旧业务字段与 hash/fetched_at
```

## 7. ORM、DAO 与 HDD Migration

### 7.1 ORM

新增 `src/foundation/models/raw/raw_balancesheet.py`：

- 七个身份字段与规范化后的 `end_type` 显式声明为 `nullable=False`。
- 150 个数值列由 `BALANCESHEET_DECIMAL_FIELDS` 动态生成 `Numeric(nullable=True)`。
- 元数据：`source_content_hash(64)`、`api_name='balancesheet_vip'`、`fetched_at timestamptz`。
- `__table_args__` 声明主键和两个逻辑索引，与 migration 名称完全一致。

在 `all_models.py`、`DAOFactory`、table model registry 中登记 `RawBalancesheet`。使用 `GenericDAO`，不新建数据集 DAO。

### 7.2 Migration

实现前重新读取真实 Alembic head。若三表同批开发，建议顺序固定为：

```text
income migration -> balancesheet migration -> cashflow migration
```

每个文件的 `down_revision` 只连接执行时真实上一 head。`balancesheet` migration：

1. 在任何 DDL 前确认 PostgreSQL 和 `gs_raw_cold_hdd`。
2. heap 使用 `postgresql_tablespace='gs_raw_cold_hdd'`。
3. 主键索引执行 `ALTER INDEX ... SET TABLESPACE gs_raw_cold_hdd`。
4. 二级索引直接使用 `TABLESPACE gs_raw_cold_hdd`。
5. 最后创建普通 view。
6. `downgrade()` 抛错，禁止自动删除业务事实。

主键 / 索引：

```text
PK (ts_code, ann_date, f_ann_date, end_date,
    report_type, comp_type, update_flag)
IDX (ann_date, report_type, ts_code)
IDX (report_type, ts_code, end_date,
     update_flag DESC, f_ann_date DESC, ann_date DESC)
```

初始 migration `20260830_000164` 保留其部署时八字段主键历史。Prod 已执行 `20260830_000166`，当前三表主键均为七字段，`end_type` 均为 nullable；不改写该已部署 migration。新增 `20260830_000167`（`down_revision=20260830_000166`）：先检查表和七字段主键现状，再拒绝非季度末、非法非空值和与 `end_date` 矛盾的行，仅对空值执行确定性补齐，最后恢复 `end_type NOT NULL`。该 migration 不重建主键/索引，不移动 tablespace，不删除任何业务数据。

## 8. Serving View

`core_serving.equity_balancesheet` 逐列输出全部 158 个源字段和三个元数据字段。SQL 必须在数据库层完成唯一选择：

```sql
SELECT DISTINCT ON (ts_code, end_date) ...
FROM raw_tushare.balancesheet
WHERE report_type = '1'
ORDER BY
  ts_code, end_date,
  CASE update_flag WHEN '1' THEN 0 ELSE 1 END,
  f_ann_date DESC,
  ann_date DESC,
  fetched_at DESC,
  comp_type DESC,
  end_type DESC,
  source_content_hash DESC;
```

必须用样本覆盖已实测场景：同一源身份主体存在 `f_ann_date=20260820` 和 `20260827` 时 raw 两行都保留，serving 选择后者；若较旧 `f_ann_date` 的 `update_flag=1` 与较新 `f_ann_date` 的 `update_flag=0` 同时存在，先选 `update_flag=1`，再比较日期。

## 9. Ops 与前端

### 9.1 后端

1. `freshness_policies.py` 登记 `balancesheet: EVENT_RUN_TRACE`。
2. `dataset_catalog_views.py` 增加 `DatasetCatalogItem("balancesheet", "equity_financial", 40)`。
3. catalog/manual/automation 参数都必须返回 `option_labels` 与 `select_all_enabled`。
4. schedule 缺少 report type 使用 Definition 默认全部；显式空数组在创建/更新时 422。
5. `params_json.filters.report_type` 只存真实值数组。

### 9.2 前端

手动和自动页面复用共享 `OpsEnumMultiSelect`：默认全部；取消全部后清空并允许子选；全部选中时禁用 12 个真实选项。页面只消费 API 元数据，不出现 `balancesheet` 条件分支。

## 10. 文件改动

### 10.1 本次 `end_type` 规范化收口

本表不建立独立规范化实现，直接复用 [利润表 LLD 第 10.1 节](/Users/congming/github/goldenshare/docs/datasets/income-low-level-design-v1.md)的共享 contract、row transform、normalizer、codebook 和 `000167`。本表专属改动只有 `RawBalancesheet.end_type nullable=False`、Definition 必填字段断言与共享测试 fixture。

### 10.2 初次数据集接入的历史清单

#### 新增

```text
docs/datasets/balancesheet-low-level-design-v1.md
src/foundation/datasets/balancesheet_contracts.py
src/foundation/models/raw/raw_balancesheet.py
alembic/versions/<next>_add_balancesheet_dataset.py
tests/test_financial_statement_datasets.py
```

#### 修改

```text
src/foundation/datasets/definitions/low_frequency.py
src/foundation/datasets/freshness_policies.py
src/foundation/ingestion/request_builders.py
src/foundation/ingestion/row_transforms.py
src/foundation/models/all_models.py
src/foundation/dao/factory.py
src/ops/catalog/dataset_catalog_views.py
tests/test_dataset_action_resolver.py
tests/test_dataset_definition_registry.py
tests/test_foundation_table_model_registry.py
tests/architecture/test_dataset_runtime_registry_guardrails.py
tests/web/test_ops_catalog_api.py
tests/web/test_ops_manual_actions_api.py
tests/web/test_ops_schedule_api.py
```

若共享 report-type contract 尚未落地，还必须包含 income LLD 第 5 节列出的 foundation/ops/frontend 文件；已落地时不得重复实现。

## 11. 测试矩阵

| 层 | 必须证明 |
| --- | --- |
| contract | 158 源字段、150 数值字段、顺序固定；默认响应 152 不可作为 contract |
| Definition | no-pool、自然日、raw-only/view、HDD、event freshness |
| planner | 1 日默认 12 units；2 日 24 units；周末不被过滤；子集数量准确 |
| request | 只有 `ann_date/report_type`；158 fields；pagination 不在 builder |
| source | `5000 + 5000 + 980` 类满页链可闭合；短页结束 |
| normalizer | nullable 科目、`comp_type=7`、`end_type` 推导/校验、规范化指纹去重、同身份冲突失败 |
| writer | raw-only；跨任务同身份修订覆盖；空 unit 成功 |
| serving | report_type、update_flag、f_ann_date 与稳定 tie-break 顺序 |
| migration | `000167` 仅校验/补齐 `end_type` 并恢复 `NOT NULL`；不改主键、索引或 tablespace |
| Ops/UI | 中文标签、虚拟全选、真实数组、显式空拒绝 |
| 边界 | 无 workflow/probe/date completeness/Biz API 新增 |

## 12. 开发步骤

1. 复用利润表 LLD 的 `N0-N5` 共享收口顺序，不另建 balancesheet 分支。
2. 证明空值、正确值、非法值、矛盾值、非季度末和批次规范化去重在 balancesheet Definition 上行为一致。
3. 证明 `000167` 对空 balancesheet 表仍可完成约束恢复，且不生成任何删除或主键 DDL。
4. 运行定向、codebook、架构、Definition lint 和 docs 检查。

停止条件：Prod 不是 `000166`/七字段主键现状、存量值非法或矛盾、共享 normalizer 回归、或 `000167` 需要扩大到主键/tablespace/删除操作。

## 13. 验证命令

```bash
uv run ruff check src/foundation/datasets src/foundation/ingestion src/foundation/models/raw/raw_balancesheet.py src/foundation/dao/factory.py src/ops tests/test_financial_statement_datasets.py
uv run pytest -q tests/test_financial_statement_datasets.py tests/test_dataset_definition_registry.py tests/test_foundation_table_model_registry.py
uv run pytest -q tests/web/test_ops_catalog_api.py tests/web/test_ops_manual_actions_api.py tests/web/test_ops_schedule_api.py
uv run pytest -q tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_dataset_runtime_registry_guardrails.py
uv run goldenshare ingestion-lint-definitions
cd frontend && npm run test -- ops-enum-multi-select ops-v21-task-manual-tab ops-v21-task-auto-tab
cd /Users/congming/github/goldenshare && python3 scripts/check_docs_integrity.py
```

## 14. 交付状态定义

开发完成后文档只能更新为“代码已实现，待运营部署与验收”。初始历史范围、生产 migration、数据同步和页面验收由运营后续执行；不得在开发阶段自行运行生产写操作。
