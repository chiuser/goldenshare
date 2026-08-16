# 申万 SW2021 行业分类 `index_classify` Prod 数据集 LLD v1

> 状态：LLD 已按当前代码完成纠偏，等待评审；尚未编码、迁移、同步或创建生产排程。
> 初版：2026-08-16；本次代码对账：2026-08-17。
> 上游产品依据：[板块雷达产品设计方案 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-product-design-v1.md)。
> 数据依据：[板块雷达数据覆盖审计 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-data-coverage-audit-v1.md)。
> 源站依据：Tushare `index_classify`，本地文档 `docs/sources/tushare/指数专题/0181_申万行业分类.md`（doc_id=181）。

---

## 1. 结论与边界

本数据集负责把 Tushare 当前 SW2021 一级、二级、三级行业分类直接发布到 Prod `core_serving.sw_industry_classification`，为后续申万行业成员、行情和板块雷达提供唯一的分类身份与父子层级事实。

已冻结口径：

1. 数据集 key 固定为 `index_classify`，源 API 固定为 `index_classify`。
2. 只请求 `src=SW2021`；不请求、不落库、不兼容 `SW2014`。
3. 使用 `source -> core_serving` direct-serving；`raw_dao_name/raw_table/std_table` 均为 `None`。
4. 源端 `index_code` 必须先保存为 `source_index_code`，再生成业务 `index_code`。
5. `industry_code=230501` 的源值 `850401.SI` 统一映射为业务码 `850412.SI`。
6. `840401` 是笔误，禁止进入规则表、模型、测试样本和生产数据。
7. 分类接口是无日期快照；目标表只表达最近一次成功发布的完整 SW2021 分类，不伪装成历史分类版本序列。
8. 本期不建设 Raw、Lake、工作流、板块雷达 API 或前端页面。

### 1.1 架构归属

```text
Tushare index_classify
  -> DatasetDefinition(index_classify)
  -> DatasetActionResolver(mode=none)
  -> 1 个 snapshot_refresh unit
  -> offset/limit 分页
  -> SW2021 代码标准化
  -> core_serving.sw_industry_classification
  -> Ops TaskRun / snapshot_run_trace
```

- Foundation domain：`board_theme`。
- Ops 展示分组：`board_theme / 板块 / 题材`。
- 依赖方向不变：实现只落 `foundation` 与 `ops` 既有扩展点，不产生 `foundation -> ops|biz|app` 反向依赖。

---

## 2. 真实源接口证据

### 2.1 请求矩阵

2026-08-16 通过项目现有 `TushareHttpClient` 只读实测：

| 请求形态 | 参数 | 行数/分页 | 结论 |
|---|---|---:|---|
| 不传业务参数 | `{}` | 359 行，全部为 `SW2014` | 禁止作为主维护请求；不显式传 `src` 会取错版本 |
| 固定版本全集 | `src=SW2021` | 511 行 | 正式全集基线 |
| 分页全集 | `src=SW2021, limit=200, offset=0/200/400` | `200/200/111` | short page 正常终止，合并 511 行 |
| 对象过滤 | `index_code=850401.SI, src=SW2021` | 1 行 | 只用于错码核验，不暴露为运营维护路径 |
| 单对象异常值 | `index_code=850401.SI, src=SW2021` | 1 行 | 源端确实返回 `230501 / 特钢Ⅲ` |
| 单对象业务码 | `index_code=850412.SI, src=SW2021` | 0 行 | 业务码不能反向作为分类接口源值 |
| 时间点/区间 | 不适用 | 不适用 | 源接口没有时间参数，平台不得暴露日期控件 |
| 默认字段 | `src=SW2021`，不传 `fields` | 已实测 | 默认返回不能替代正式字段白名单，尤其不能据此省略 `src` |
| 显式完整字段 | `src=SW2021`，显式 7 字段 | 已实测返回全部 7 字段 | 正式 connector payload 必须逐页携带同一字段白名单 |

分页合并后 `(src, industry_code)` 唯一键摘要与单次 511 行请求一致；不存在重复身份行。

差异记录：本地源文档的 SW2021 表格把 `industry_code=230501` 列为 `850412`，但 2026-08-16 当前 API 实测返回 `850401.SI`；成员与行情接口均使用 `850412.SI`。因此保留源值并做显式、可版本化映射，不能改写本地 source 文档去掩盖当前接口差异。

### 2.2 全量质量基线

| 指标 | 实测值 |
|---|---:|
| SW2021 总行数 | 511 |
| L1 / L2 / L3 | 31 / 134 / 346 |
| `is_pub=1 / 0` | 414 / 97 |
| `(src, industry_code)` 重复 | 0 |
| 标准化后 `index_code` 重复 | 0 |
| 父节点缺失 | 0 |

`tushare-data` 的接口家族结论：`index_classify` 只负责申万分类与层级，不提供成分有效期或行业日行情，不能替代 `index_member_all`、`sw_daily`。

### 2.3 字段验证

默认字段与显式字段均已验证。正式 `source_fields` 必须显式包含默认不保证返回的 `src`：

```text
index_code, industry_name, parent_code, level,
industry_code, is_pub, src
```

### 2.4 源输入参数与运营暴露

| 源参数 | 源端可选 | 正式用途 | 运营是否可填 |
|---|---|---|---|
| `src` | 是 | Definition 固定 `SW2021` | 否 |
| `index_code` | 是 | 仅只读核验/诊断 | 否 |
| `level` | 是 | 仅只读核验/诊断，正式请求拉完整三级 | 否 |
| `parent_code` | 是 | 仅只读核验/诊断 | 否 |
| `limit/offset` | 是 | 通用分页器内部生成 | 否 |

不传 `src` 会取到 SW2014，因此 `src` 虽是源端可选参数，在本数据集中属于不可覆盖的内部常量，不是运营输入。

---

## 3. 三层时间语义

| 语义层 | 固定设计 |
|---|---|
| 时间输入 | 无时间；Ops/TaskRun 只保存 `mode=none` 意图 |
| 执行/unit | resolver 生成 1 个 `snapshot_refresh` unit；unit 内完成全部分页 |
| freshness/audit | 不建立连续日期桶；只观察最近一次成功维护时间 |

`DatasetDateModel`：

```python
{
    "date_axis": "none",
    "bucket_rule": "not_applicable",
    "window_mode": "none",
    "input_shape": "none",
    "observed_field": None,
    "audit_applicable": False,
    "not_applicable_reason": "SW2021 分类为无业务日期的当前快照，只按成功运行轨迹观测。",
}
```

`not_applicable` 既表示不做日期完整性审计，也表示本数据集不支持任何时间输入。

### 3.1 当前代码消费者审计

| 消费方 | 本数据集固定结果 | 已核验代码位置 | 实施影响 |
|---|---|---|---|
| Manual Action | 只生成 `snapshot_refresh/none`，无时间和 filter | `src/ops/queries/manual_action_query_service.py` | 新增 Definition 后自动派生；补 API 正反例 |
| Catalog | 使用 Definition 日期选择规则与 Ops 显式目录 | `src/ops/catalog/dataset_catalog_view_resolver.py`、`src/ops/catalog/dataset_catalog_views.py` | 必须新增唯一 `item_order=80` |
| Workflow | 首版不进入 workflow | `src/ops/action_catalog.py` | 不修改 workflow |
| Resolver / planner | `none` 生成 1 个 generic unit | `src/foundation/ingestion/resolver.py`、`src/foundation/ingestion/unit_planner.py` | 使用专用 request builder；不得使用不存在的 `generic` builder |
| Request builder | 只校验 snapshot profile；`src` 来自 `base_params` | `src/foundation/ingestion/request_builders.py` | 新增 `_index_classify_sw2021_params` |
| Freshness | `SNAPSHOT_RUN_TRACE` | `src/foundation/datasets/freshness_policies.py`、`src/ops/queries/freshness_query_service.py` | 新增显式映射 |
| Dataset card | 无 Raw，回退展示 serving/target 表 | `src/ops/dataset_definition_projection.py`、`src/ops/queries/dataset_card_query_service.py` | 补 direct-serving 回归 |
| Snapshot rebuild | 读取 Definition 投影和成功运行轨迹 | `src/ops/services/operations_dataset_status_snapshot_service.py` | 补 snapshot rebuild 测试 |
| Date completeness | 明确不适用 | `src/ops/services/date_completeness_audit_service.py` | `completeness.scope=not_applicable` |
| 自动任务 | 首版不开放 | `src/ops/services/schedule_automation_capability_resolver.py` | `schedule_enabled=False`，无 schedule policy |
| Source release / Probe | 不建设 | `src/ops/services/operations_schedule_service.py` | 无 probe、无运行时绑定 |
| 前端时间控件 | 无时间、无筛选 | `frontend/src/pages/ops-v21-task-manual-tab.tsx` | 只验证通用无时间表单，不加 dataset-key 分支 |
| Ops 展示目录 | `board_theme` 第 80 位 | `src/ops/catalog/dataset_catalog_views.py` | 位于现有 KPL 数据集之后 |
| 数据源页 / 分层 | `raw_table=None`，展示 `core_serving.sw_industry_classification` | `src/ops/schemas/dataset_card.py`、`frontend/src/pages/ops-v21-source-page.tsx`、`frontend/src/pages/ops-v21-dataset-detail-page.tsx` | 验证服务表标签，不显示伪 Raw |
| Shared storage / writer | direct-serving、完整范围原子替换 | `src/foundation/ingestion/writer.py`、`src/foundation/datasets/definitions/_builder.py`、`src/foundation/ingestion/linter.py` | 新增通用 `serving_direct_scope_replace`，回归全部既有 write path |
| 测试与文档 | 新数据集尚不存在 | `tests/test_dataset_definition_registry.py` 等模板门禁 | 实施时补齐，不得以现有回归代替新数据集验收 |

---

## 4. 字段端到端设计

| 源字段 | 源文档 | 真实样本 | `source_fields` | Raw ORM/迁移 | Serving ORM/迁移 | Lake | 必填 | 目标与规则 |
|---|---|---|---|---|---|---|---|---|
| `index_code` | 是 | 是 | 是 | 不适用 | `source_index_code`、`index_code` | 不适用 | 是 | 源码保真后按规则生成业务码 |
| `industry_name` | 是 | 是 | 是 | 不适用 | `industry_name varchar(64)` | 不适用 | 是 | 行业名称 |
| `parent_code` | 是 | 是 | 是 | 不适用 | `source_parent_code`、`parent_code` | 不适用 | 是 | 源码保真；L1 业务父码为 `NULL` |
| `level` | 是 | 是 | 是 | 不适用 | `level varchar(2)` | 不适用 | 是 | 仅 `L1/L2/L3` |
| `industry_code` | 是 | 是 | 是 | 不适用 | `industry_code varchar(16)` | 不适用 | 是 | 分类身份，主键组成 |
| `is_pub` | 是 | 是 | 是 | 不适用 | `is_pub boolean` | 不适用 | 是 | `1/0 -> true/false` |
| `src` | 是，默认显示 N | 显式请求已返回 | 是 | 不适用 | `src varchar(16)` | 不适用 | 是 | 只能为 `SW2021`，主键组成 |

系统字段不进入 `source_fields`：`source='tushare'`、`normalization_rule_version='sw2021-index-code-v1'`、`created_at/updated_at`。Raw ORM、Raw 迁移和 Lake 白名单均为“不适用（有意无 Raw/Lake 层）”。这不是遗漏，也不得为通过门禁新增空 Raw 表。

### 4.1 标准化规则

唯一初始别名规则：

```python
SW2021_INDEX_CODE_ALIASES_V1 = {"850401.SI": "850412.SI"}
```

处理顺序：

1. 保存 `source_index_code`、`source_parent_code`。
2. 用 `source_index_code` 查显式别名表；分类接口命中该规则时必须同时满足 `industry_code=230501`，否则视为新冲突。
3. 未命中时 `index_code = source_index_code`。
4. L1 的业务 `parent_code` 转为 `None`；L2/L3 父级必须在本批 `industry_code` 集合中。
5. 标准化后 `(src, index_code)` 必须唯一；新冲突必须使 unit 失败，不能最后一行覆盖。

规则必须集中在 `src/foundation/datasets/sw_industry_contracts.py`，三个数据集共同引用；禁止把 `850401 -> 850412` 散落在 DAO、查询、SQL 或前端。

---

## 5. DatasetDefinition 设计

| 段 | 固定值 |
|---|---|
| identity | `dataset_key=index_classify`，显示名“申万 SW2021 行业分类” |
| domain | `board_theme / 板块 / 题材` |
| source | `source_key_default=tushare`，`source_keys=(tushare,)`，`adapter=tushare`，`api_name=index_classify`，`source_doc_id=tushare.index_classify`，`request_builder_key=_index_classify_sw2021_params`，`base_params={"src":"SW2021"}`，`release_policy=same_day` |
| input_model | 无时间字段、无 filter；`src/level/index_code/parent_code` 均不向运营暴露 |
| storage | `delivery_mode=core_direct`，`layer_plan=source->serving`，`raw_dao_name/raw_table/std_table=None`，`core_dao_name=sw_industry_classification`，`target_table=serving_table=core_serving.sw_industry_classification`，`write_path=serving_direct_scope_replace`，`raw_conflict_columns=None`，`conflict_columns=(src,industry_code)`，`replacement_scope_fields=(src,)`，`row_identity_filters={}` |
| planning | `universe_policy=no_pool`，无 enum fanout，`pagination_policy=offset_limit`，`page_limit=200`，`unit_builder_key=generic`，`max_units_per_execution=1`，`fetch_concurrency=1`，`page_processing_mode=buffer_all` |
| normalization | `date_fields=()`、`decimal_fields=()`；`row_transform_name=normalize_sw2021_classification_row`；必填业务身份与层级字段 |
| capabilities | `maintain` 允许手动和重试、`schedule_enabled=False`，只支持 `none` |
| observability | `snapshot_run_trace`，无 observed field，无日期审计 |
| completeness | `scope=not_applicable`，无 subject/universe；原因同 date model |
| transaction | `commit_policy=unit`，`idempotent_write_required=True`；唯一 unit 缓冲约 511 行、3 页，若超过 2,000 行则停止复核分页和事务预算 |

Definition 落点：`src/foundation/datasets/definitions/board_hotspot.py`。Freshness 显式登记：

```python
FRESHNESS_POLICY_BY_DATASET["index_classify"] = SNAPSHOT_RUN_TRACE
```

### 5.1 质量策略

```python
"quality": {
    "reject_policy": "fail_unit_on_any_rejection",
    "empty_result_policy": "fail_unit",
    "required_fields": (
        "source_index_code", "index_code", "industry_name",
        "level", "industry_code", "is_pub", "src",
        "source", "normalization_rule_version",
    ),
    "duplicate_key_policy": "allow",
    "source_multiplicity_policy": "deduplicate_identical",
    "batch_unique_key_fields": ("src", "industry_code"),
    "required_distinct_values": {"level": ("L1", "L2", "L3")},
    "pre_write_validator_key": "sw2021_classification_snapshot",
}
```

当前 `DatasetQualityPolicy` 尚无 `empty_result_policy/pre_write_validator_key`，`DatasetStorageDefinition` 尚无 `replacement_scope_fields`，writer 也尚无 `serving_direct_scope_replace`。实施时必须把它们作为通用、声明式契约新增：禁止按 `dataset_key` 在 executor/writer 中写分支。通用 preflight 先处理空结果和任意 reject，再由预写校验器检查第二唯一键 `(src,index_code)`、层级闭包、父子对应和错码规则，全部通过后才允许 DML。

`replacement_scope_fields` 与现有 `row_identity_filters` 职责不同：前者定义 writer 的事务替换范围，后者只服务日期完整性身份过滤。本数据集不做日期完整性审计，因此 `row_identity_filters={}`。writer 必须从已校验的 normalized batch 提取唯一 scope tuple；本数据集只能得到 `src='SW2021'`。零个或多个 scope tuple 都必须在 DML 前失败。

实现验收以 511、31/134/346、414/97 为 M0 基线，但不得把这些数字写成永久业务常量；源站合法分类调整允许变化，变化必须进入验收报告并重新核验父子闭包和跨接口代码覆盖。

---

## 6. 表、DAO 与迁移

### 6.1 ORM

- 文件：`src/foundation/models/core_serving/sw_industry_classification.py`
- 类：`SwIndustryClassification`
- 表：`core_serving.sw_industry_classification`
- 主键：`(src, industry_code)`
- 唯一约束：`(src, index_code)`
- 索引：`(src, level, is_pub)`、`(src, parent_code)`
- 不分区：当前仅 511 行，分区没有收益。

### 6.2 DAO

复用 `GenericDAO`，在 `DAOFactory` 增加 `sw_industry_classification` 属性；不新增专用事务或查询编排到 DAO。

### 6.3 Alembic

三张申万服务表可由同一个线性迁移创建，迁移只建表、约束和索引，不 seed、不回填、不创建账号或模块专属 GRANT。

2026-08-17 只读审计时，仓库和 Prod `public.alembic_version` 均为唯一 head `20260816_000137`。本文仍不预分配新 revision；实施日必须重新执行 `uv run alembic heads --verbose` 和 Prod 只读核验，新迁移的 `down_revision` 只能连接实施时真实唯一 head。

---

## 7. Ingestion、Ops 与消费者

### 7.1 请求、分页与事务

1. request builder 固定为新增的 `_index_classify_sw2021_params`：只接受 `snapshot_refresh`，返回空业务参数；`src=SW2021` 只能由 Definition `base_params` 合并，用户输入无法覆盖。
2. Source client 每页都显式发送七个 `source_fields`。
3. offset 序列固定由通用 `offset_limit` 产生，short page 终止。
4. 全分页结果先进入同一个 `NormalizedBatch`；任何 reject、空结果、缺任一层级、父子不闭合或标准化冲突均在 DML 前失败。
5. 新通用 `serving_direct_scope_replace` 从 normalized batch 的唯一 scope tuple 得到 `src='SW2021'`，再只锁定并替换该范围：同一事务内参数化删除旧范围、插入本批完整集合、按两组唯一键和内容摘要 read-back；失败整体回滚。禁止 `TRUNCATE`、无条件 `DELETE`、复用 `row_identity_filters` 猜写入范围或触碰其他 `src`。
6. 该范围替换是“当前完整快照”语义的必要组成，不属于隐式清表；编码评审必须验证 SQL where 条件，生产迁移和首次同步仍需用户另行授权。

### 7.2 Ops 派生

| 消费方 | 设计结果 |
|---|---|
| Manual Action | 展示无时间维护动作；无日期、版本、层级或代码 filter |
| Catalog | `board_theme` 组，固定 `item_order=80` |
| TaskRun | 对象类型为“分类快照”，进度记录页号、offset、page rows、总行数 |
| Freshness | 只显示最近成功运行，不显示“缺少某交易日” |
| Date completeness | 不适用 |
| Dataset card | `raw_table=null`，明确显示服务表 `core_serving.sw_industry_classification` |
| Schedule | 首版 `schedule_enabled=False`；不创建 schedule，也不展示自动任务能力 |
| Workflow | 首版不新增；依赖顺序由实施 runbook 管理 |

数据源页面和前端只消费通用 Definition/API 契约，不增加 `index_classify` 页面特例。

### 7.3 后续业务消费者契约

板块雷达只能使用：

- `index_code` 做跨表关联；
- `industry_code` 做分类身份；
- `parent_code` 做层级关系；
- `is_pub=true` 形成可发布行业指数池。

禁止业务查询直接使用 `source_index_code`。若按当前分类回看历史，产品必须标注“按当前 SW2021 分类重述历史”，不能宣称是目标日期当时的分类版本。

---

## 8. 测试与验收

### 8.1 正反例

| 约束 | 正向测试 | 反向测试 |
|---|---|---|
| 只做 SW2021 | plan 的每页参数都含 `src=SW2021` | 无参数不能生成 SW2014 请求；传 `src=SW2014` 被 strict validator 拒绝 |
| direct-serving | 只解析 serving DAO 并 upsert 511 行 | 解析 Raw DAO、出现 Raw 表或双写时 linter 失败 |
| 代码标准化 | `230501/850401 -> source=850401, business=850412` | `840401`、未知冲突或两源码归一为同一业务键时失败 |
| 分页 | `200/200/111` 合并唯一键等于不截断基准 | 丢页、重复冲突页、未 short-page 终止时失败 |
| 父子闭包 | 31/134/346 且所有 L2/L3 父级存在 | 孤儿节点、非法 level、重复 `(src,industry_code)` 时失败 |
| 无时间 | `mode=none` 生成 1 unit | point/range 或任何 filter 被拒绝 |
| Ops 卡片 | 显示 target/serving 表和 snapshot trace | 显示伪 Raw 表或日期滞后状态时失败 |

### 8.2 文件级实施范围

计划新增/修改：

- `src/foundation/datasets/sw_industry_contracts.py`
- `src/foundation/datasets/definitions/board_hotspot.py`
- `src/foundation/datasets/freshness_policies.py`
- `src/foundation/datasets/models.py`
- `src/foundation/datasets/definitions/_builder.py`
- `src/foundation/models/core_serving/sw_industry_classification.py`
- `src/foundation/dao/factory.py`
- `src/foundation/ingestion/request_builders.py`
- `src/foundation/ingestion/linter.py`
- `src/foundation/ingestion/row_transforms.py`
- `src/foundation/ingestion/writer.py`
- `src/ops/catalog/dataset_catalog_views.py`
- 一条实施日确定 revision 的 Alembic 迁移
- Definition、resolver、source client、normalizer、writer、Ops API、数据源卡片和迁移测试

不修改 `src/platform/**`、`src/operations/**`、Lake/Dagster 或 Wealth 页面。

### 8.3 真实验收

首次发布必须记录：

```text
source_fetched_rows = 511
normalized_rows = 511
rejected_rows = 0
written_rows = 511
target_unique_rows(src=SW2021) = 511
level_counts = 31 / 134 / 346
is_pub_counts = 414 / 97
duplicate_identity_rows = 0
parent_orphan_rows = 0
source_850401_rows = 1
business_850412_rows(industry_code=230501) = 1
business_840401_rows = 0
```

若源站在实施日合法变更，不能机械要求仍为 511；必须把变化明细、父子闭包、唯一键和成员/行情覆盖重新审计后再批准发布。

---

## 9. 硬需求追溯账本

| ID | 硬需求与依据 | 影响层/消费者 | 后端权威约束 | 前端表现 | 实现文件 | 正向测试 | 反向测试 | 真实验证 | 阶段 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|
| IC-001 | 仅 SW2021 | planner/source | 固定 base param + strict input | 无版本筛选 | Definition、builder | 每页含 SW2021 | SW2014/用户覆盖拒绝 | 511 行请求矩阵 | M1/M2 | 待实施 |
| IC-002 | 无 Raw/Lake/双写 | storage/card | direct-serving linter | 卡片展示服务表 | builder、linter、writer | 只解析 serving DAO | Raw DAO/表出现即失败 | source/target 对账 | M1/M2 | 待实施 |
| IC-003 | 当前快照必须精确替换 | writer/DAO/业务查询 | 限定 `src` 原子 scope replace + read-back | 无专用交互 | models、writer、DAO | 源集合收缩后目标精确一致 | 空结果、无 where、跨 src 删除失败 | 两次不同 key set 演练 | M2/M3 | 待实施 |
| IC-004 | 保留源码并产出业务码 | normalization/下游 | 共享 contracts + transform | 不展示源码为业务码 | contracts、transform、ORM | 850401→850412 | 840401/新冲突失败 | 关键码 read-back | M2/M3 | 待实施 |
| IC-005 | 全量分页不截断 | source client/TaskRun | offset-limit 200、short page | 展示分页进度 | source client | 200/200/111 | 丢页/重复冲突/无 short page 失败 | 511 键摘要 | M2/M3 | 待实施 |
| IC-006 | 层级闭包与双唯一性 | pre-write validator/DB | L1/L2/L3、父子闭包、两组唯一约束 | 不适用 | validator、ORM、迁移 | 31/134/346 闭合 | 孤儿/错层/双键冲突失败 | 闭包 SQL | M2/M3 | 待实施 |
| IC-007 | 空结果或任意 reject 不发布 | normalizer/writer | quality preflight | TaskRun 展示结构化失败 | models、writer、codebook | 511 行零拒绝提交 | 空/部分 reject 回滚 | fetched/normalized/rejected 对账 | M2/M3 | 待实施 |
| IC-008 | 无时间且首版无排程 | Manual Action/schedule | none-only、schedule false | 只显示手动无时间表单 | Definition、Ops projection | none 可提交 | point/range/schedule 不可选 | API/浏览器路径 | M2 | 待实施 |
| IC-009 | 服务表可观测且不伪造 Raw | freshness/card/snapshot | SNAPSHOT_RUN_TRACE | target fallback | freshness、Ops query | 显示最近成功和服务表 | 日期滞后/伪 Raw 失败 | rebuild snapshot | M2/M3 | 待实施 |

---

## 10. 实施顺序与停止条件

1. M0：评审三份纠偏后的 LLD；确认新增共享质量字段、预写校验注册表和范围替换 writer 契约，再重新确认 CodeGraph 与 Alembic/Prod 基线。
2. M1：先实现共享 SW2021 代码契约、三个 ORM/DAO/Definition 与线性迁移，但不运行生产迁移。
3. M2：实现分类 row transform、分页/事务/质量测试及 Ops 派生测试。
4. M3：部署后先只执行 `index_classify` 最小真实同步与 read-back。
5. M4：分类验收通过后，才允许进入 `index_member_all` 实际同步。

立即停止条件：

- 实施日仓库与 Prod Alembic 基线未对齐；
- `src=SW2021` 不再返回闭合的 L1/L2/L3；
- 出现除已批准规则外的新跨接口错码；
- 分页 key 集与不截断基准不一致；
- 需要新增 Raw、Lake、生产账号、连接、无条件删除或超出 `src='SW2021'` 的写入范围。

本 LLD 不授权编码、迁移、生产同步、历史回补或排程启用。
