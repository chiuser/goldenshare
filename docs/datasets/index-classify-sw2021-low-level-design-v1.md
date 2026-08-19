# 申万 SW2021 行业分类 `index_classify` Prod 数据集 LLD v1

> 状态：M0～M4 已完成；迁移 `20260818_000138` 已在 Prod 执行，分类 TaskRun `8714/8717` 与成员 TaskRun `8718/8719` 的生产发布及幂等重放已通过。M5 日行情已发布到 2026-08-18；单日空结果安全 no-op 已完成本地纠偏并等待部署。
> 初版：2026-08-16；代码对账：2026-08-17；最终产品拍板：2026-08-18；M2/M3 纠偏验收：2026-08-19。
> 上游产品依据：[板块雷达产品设计方案 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-product-design-v1.md)。
> 数据依据：[板块雷达数据覆盖审计 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-data-coverage-audit-v1.md)。
> 源站依据：Tushare `index_classify`，本地文档 `docs/sources/tushare/指数专题/0181_申万行业分类.md`（doc_id=181）。

---

## 0. 2026-08-18 最终拍板

以下两项由用户按推荐方案确认，已成为三份申万数据集 LLD 的共同硬约束，不再列为待拍板项：

1. `index_classify` 首版只保留最近一次成功发布的完整 SW2021 分类快照，不保存抓取时点历史，也不把观察时间伪装成官方分类生效时间。历史研究如使用本表，必须标注“按当前 SW2021 分类重述历史”。
2. `sw_daily` 服务表保留源接口按交易日返回的全部申万指数事实；板块雷达只在查询时与 `index_classify` 内连接并过滤 `is_pub=true`。源端额外综合/风格指数不得在 Foundation 入库阶段丢弃，也不得进入正式行业榜。

这两项不会改变 `index_member_all` 的存储口径：成员表仍完整保存 Y/N 当前与历史关系；`out_date` 边界必须由业务样本核验，不属于偏好选择。

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

### 2.3 2026-08-18 M2 实施验收

M2 使用当前 Tushare MCP 和项目正式 ingestion 链路重新完成只读源端核验，没有执行 Prod 迁移或生产写入：

| 验收项 | 当前结果 |
|---|---|
| MCP 默认字段 `src=SW2021` | 511 行，字段为 `index_code/industry_name/parent_code/level/industry_code/is_pub/src` |
| MCP 显式七字段 `src=SW2021` | 511 行；L1/L2/L3 为 31/134/346，`is_pub=1/0` 为 414/97 |
| 不传 `src` | 359 行且全部为 SW2014，再次证明正式请求必须固定 SW2021 |
| 错码单对象 | `850401.SI` 返回 `230501/特钢Ⅲ`；`850412.SI` 源查询仍为空 |
| 项目正式分页链路 | 3 次请求，offset 为 0/200/400，页行数为 200/200/111，short page 正常终止 |
| 分页与 MCP 全集对账 | 两边都是 511 个唯一源身份，ASCII 身份集合指纹均为 `ff54e2ceb6390b6b` |
| 真实行标准化 | 511 normalized、0 rejected、0 deduplicated；`850401.SI` 保存在 `source_index_code`，业务码为 `850412.SI` |
| 质量校验 | 两组唯一键重复均为 0，父节点孤儿为 0，`840401.SI` 为 0 |
| 本地事务验收 | 首次写入 511；相同集合重放仍为 511；删除一个合法叶节点后重放精确收敛到 510；其他 `src` 范围保持不变 |
| 失败回滚 | 空批次、部分 reject、跨 `src` 和孤儿父节点均在发布前失败；失败后目标范围保持 510 行 |
| Ops 契约 | 仅 `mode=none` 且无 filter；服务表可见、Raw 为空、freshness 为 snapshot trace、自动化能力为空 |

M2 没有新增业务实现分支；M1 已完成的声明式通用能力经本轮端到端正反例确认满足分类数据集契约。上述 511 等数字是 2026-08-18 验收基线，不是永久写死的业务常量。

### 2.3.1 2026-08-19 M2 纠偏验收

审计发现原 `write_volume_assessment` 只是说明文字，`buffer_all` 主链没有真正执行 2,000 行停止条件；IC-008 也只有 API 测试，没有浏览器路径。纠偏后：

1. `planning.max_source_rows_per_unit=2000` 作为通用声明式字段进入 Definition、`PlanPlanning` 和每个 `PlanUnitSnapshot`；不按 `dataset_key` 特判。
2. `DatasetSourceClient` 在合并每页前计算 unit 累计源端行数；2,000 行必须继续观察到终止 short page才成功，下一页只要使总量达到 2,001 行就以 `source_rows_exceeded` 失败，标准化和目标 DML 均不会开始。
3. Definition builder 拒绝非正整数上限、非 `buffer_all` 使用方式及 `page_limit > max_source_rows_per_unit` 的自相矛盾配置。
4. 自动化正反例已证明 2,000 行可完成、2,001 行失败；持续返回满页也会在越过 2,000 行时有界退出，不再无限请求。
5. Playwright 使用真实 Chromium 打开 Manual Action 页面，分别选择分类和成员动作，确认无日期、时间范围和筛选控件，提交体严格为 `{"time_input":{"mode":"none"},"filters":{}}`；控制台错误和失败 API 响应均为 0。

### 2.4 字段验证

默认字段与显式字段均已验证。正式 `source_fields` 必须显式包含默认不保证返回的 `src`：

```text
index_code, industry_name, parent_code, level,
industry_code, is_pub, src
```

### 2.5 源输入参数与运营暴露

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
| Manual Action | 只生成 `snapshot_refresh/none`，无时间和 filter | `src/ops/queries/manual_action_query_service.py` | 已由 Definition 自动派生，并通过 API 与 Playwright 浏览器正反例 |
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
| 前端时间控件 | 无时间、无筛选 | `frontend/src/pages/ops-v21-task-manual-tab.tsx` | 已验证通用无时间表单，不加 dataset-key 分支 |
| Ops 展示目录 | `board_theme` 第 80 位 | `src/ops/catalog/dataset_catalog_views.py` | 位于现有 KPL 数据集之后 |
| 数据源页 / 分层 | `raw_table=None`，展示 `core_serving.sw_industry_classification` | `src/ops/schemas/dataset_card.py`、`frontend/src/pages/ops-v21-source-page.tsx`、`frontend/src/pages/ops-v21-dataset-detail-page.tsx` | 验证服务表标签，不显示伪 Raw |
| Shared storage / writer | direct-serving、完整范围原子替换 | `src/foundation/ingestion/writer.py`、`src/foundation/datasets/definitions/_builder.py`、`src/foundation/ingestion/linter.py` | 新增通用 `serving_direct_scope_replace`，回归全部既有 write path |
| 测试与文档 | 分类数据集专项正反例已建立 | `tests/test_sw2021_index_classify_dataset_m2.py`、`tests/web/test_ops_sw2021_index_classify_m2.py`、`frontend/e2e/smoke-visual.spec.ts` | M2 已完成独立后端、API 与浏览器验收，不以其他数据集回归替代 |

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
| planning | `universe_policy=no_pool`，无 enum fanout，`pagination_policy=offset_limit`，`page_limit=200`，`max_source_rows_per_unit=2000`，`unit_builder_key=generic`，`max_units_per_execution=1`，`fetch_concurrency=1`，`page_processing_mode=buffer_all` |
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

M1 已将 `empty_result_policy/pre_write_validator_key`、`replacement_scope_fields` 和 `serving_direct_scope_replace` 落为通用、声明式契约，没有在 executor/writer 中按 `dataset_key` 写分支。通用 preflight 先处理空结果和任意 reject，再由预写校验器检查第二唯一键 `(src,index_code)`、层级闭包、父子对应和错码规则，全部通过后才允许 DML。

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

M1 开工时重新确认仓库唯一 head 为 `20260816_000137`，已生成线性迁移 `20260818_000138`，其 `down_revision` 为该真实 head。M1 只生成和测试迁移，未连接 Prod、未执行 DDL；M5 实施前仍须重新核验仓库与 Prod 唯一 head。

---

## 7. Ingestion、Ops 与消费者

### 7.1 请求、分页与事务

1. request builder 固定为新增的 `_index_classify_sw2021_params`：只接受 `snapshot_refresh`，返回空业务参数；`src=SW2021` 只能由 Definition `base_params` 合并，用户输入无法覆盖。
2. Source client 每页都显式发送七个 `source_fields`。
3. offset 序列固定由通用 `offset_limit` 产生，short page 终止。
4. `max_source_rows_per_unit=2000` 在 plan 中冻结；累计行数越过上限时以 `source_rows_exceeded` 在标准化和 DML 前失败。
5. 全分页结果先进入同一个 `NormalizedBatch`；任何 reject、空结果、缺任一层级、父子不闭合或标准化冲突均在 DML 前失败。
6. 通用 `serving_direct_scope_replace` 从 normalized batch 的唯一 scope tuple 得到 `src='SW2021'`，再只锁定并替换该范围：同一事务内参数化删除旧范围、插入本批完整集合、按两组唯一键和内容摘要 read-back；失败整体回滚。禁止 `TRUNCATE`、无条件 `DELETE`、复用 `row_identity_filters` 猜写入范围或触碰其他 `src`。
7. 该范围替换是“当前完整快照”语义的必要组成，不属于隐式清表；编码评审必须验证 SQL where 条件，生产迁移和首次同步仍需用户另行授权。

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
| 分页 | `200/200/111` 合并唯一键等于不截断基准；2,000 行边界可在终止短页后完成 | 丢页、重复冲突页、2,001 行或持续满页时以 `source_rows_exceeded` 失败 |
| 父子闭包 | 31/134/346 且所有 L2/L3 父级存在 | 孤儿节点、非法 level、重复 `(src,industry_code)` 时失败 |
| 无时间 | `mode=none` 生成 1 unit | point/range 或任何 filter 被拒绝 |
| Ops 卡片 | 显示 target/serving 表和 snapshot trace | 显示伪 Raw 表或日期滞后状态时失败 |

### 8.2 文件级实施范围

M1～M3 实际新增/修改：

- `src/foundation/datasets/sw_industry_contracts.py`
- `src/foundation/datasets/definitions/board_hotspot.py`
- `src/foundation/datasets/freshness_policies.py`
- `src/foundation/datasets/models.py`
- `src/foundation/datasets/definitions/_builder.py`
- `src/foundation/models/core_serving/sw_industry_classification.py`
- `src/foundation/dao/factory.py`
- `src/foundation/ingestion/request_builders.py`
- `src/foundation/ingestion/source_client.py`
- `src/foundation/ingestion/linter.py`
- `src/foundation/ingestion/row_transforms.py`
- `src/foundation/ingestion/writer.py`
- `src/ops/catalog/dataset_catalog_views.py`
- `frontend/e2e/support/smoke-fixtures.ts`
- `frontend/e2e/smoke-visual.spec.ts`
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
| IC-001 | 仅 SW2021 | planner/source | 固定 base param + strict input | 无版本筛选 | Definition、builder | 每页含 SW2021 | SW2014/用户覆盖拒绝 | 511 行请求矩阵 | M2/M5 | M2 已通过；待 M5 生产发布验收 |
| IC-002 | 无 Raw/Lake/双写 | storage/card | direct-serving linter | 卡片展示服务表 | builder、linter、writer | 只解析 serving DAO | Raw DAO/表出现即失败 | source/target 对账 | M1/M2/M5 | M2 已通过；待 M5 生产发布验收 |
| IC-003 | 只保留最新分类快照并精确替换 | writer/DAO/业务查询 | 限定 `src` 原子 scope replace + read-back；无历史快照键 | 无专用交互；历史标注当前分类重述 | models、writer、DAO | 源集合收缩后目标精确一致 | 空结果、无 where、跨 src 删除、伪历史版本字段失败 | 两次不同 key set 演练 | M1/M2/M5 | M2 已通过 511→511→510 重放；待 M5 生产发布验收 |
| IC-004 | 保留源码并产出业务码 | normalization/下游 | 共享 contracts + transform | 不展示源码为业务码 | contracts、transform、ORM | 850401→850412 | 840401/新冲突失败 | 关键码 read-back | M1/M2/M5 | M2 已通过；待 M5 生产发布验收 |
| IC-005 | 全量分页不截断且有界 | source client/TaskRun | offset-limit 200、short page、unit 上限 2,000 | 展示分页进度 | source client | 200/200/111；2,000 行边界完成 | 丢页/重复冲突/2,001 行或持续满页失败 | 511 键摘要 | M2/M5 | M2 纠偏已通过，分页、全集指纹与 2,000/2,001 边界一致；待 M5 |
| IC-006 | 层级闭包与双唯一性 | pre-write validator/DB | L1/L2/L3、父子闭包、两组唯一约束 | 不适用 | validator、ORM、迁移 | 31/134/346 闭合 | 孤儿/错层/双键冲突失败 | 闭包 SQL | M2/M5 | M2 已通过；待 M5 生产表约束验收 |
| IC-007 | 空结果或任意 reject 不发布 | normalizer/writer | quality preflight | TaskRun 展示结构化失败 | models、writer、codebook | 511 行零拒绝提交 | 空/部分 reject 回滚 | fetched/normalized/rejected 对账 | M1/M2/M5 | M2 已通过；待 M5 生产发布验收 |
| IC-008 | 无时间且首版无排程 | Manual Action/schedule | none-only、schedule false | 只显示手动无时间表单 | Definition、Ops projection | none 可提交 | point/range/schedule 不可选 | API/Playwright 浏览器路径 | M2 | M2 纠偏已通过，浏览器提交体固定为 none + 空 filters |
| IC-009 | 服务表可观测且不伪造 Raw | freshness/card/snapshot | SNAPSHOT_RUN_TRACE | target fallback | freshness、Ops query | 显示最近成功和服务表 | 日期滞后/伪 Raw 失败 | rebuild snapshot | M2/M5 | M2 已通过；待 M5 生产状态快照验收 |

---

## 10. 三数据集统一开发里程碑与停止条件

三份 LLD 统一使用以下 M0～M7 编号。任何单份文档不得另建一套阶段含义，也不得在前置阶段未通过时提前执行后续生产动作。

| 里程碑 | 目标与交付 | 完成门禁 | 当前状态 |
|---|---|---|---|
| M0 产品与开发门禁 | 两项最终拍板写入三份 LLD；硬需求账本、影响面和实施边界一致 | 文档校验通过；用户明确允许进入 M1 | 已完成 |
| M1 共享基座与迁移准备 | 实现共享代码标准化、质量/预写校验声明、fixed request fan-in、原子 scope replace；新增三表 ORM/DAO/Definition、Ops 目录/freshness 和一条线性迁移 | CodeGraph 列出的消费者均有对应实现与回归；所有既有 writer/source/Definition 路径通过；迁移仅生成和测试，不对 Prod 执行 | 已完成；迁移 `20260818_000138` 已于 2026-08-19 在 Prod 执行并与仓库 head 对齐 |
| M2 分类数据集 | 完成 `index_classify` request、分页、transform、双唯一性、层级闭包、Ops 派生及正反例 | 511 与 31/134/346 等基线可解释；空/错码/孤儿/跨范围替换均阻断；本地或测试库幂等 | 已完成；Prod TaskRun `8714/8717` 发布与幂等重放通过，511 行内容摘要一致 |
| M3 成员数据集 | 完成单 unit 的 Y/N fan-in、分页、标准化、分类三级闭包、原子替换及 Ops 正反例 | Y/N 任一失败目标零变化；7,899 基线、唯一键、日期和闭包可解释；本地或测试库幂等 | 已完成；Prod TaskRun `8718/8719` 发布与幂等重放通过，7,899 行内容摘要一致 |
| M4 日行情数据集 | 完成交易日 point/range unit、15 字段、全源行保留、同日原子替换、freshness/completeness 及 Ops 正反例 | 非交易日、宽区间直传、日期越界、过滤 25 行、跨日删除均阻断；单日本地幂等 | 已完成（2026-08-19）；最终 OHLC 取整口径已完成本地代码与正反例纠偏 |
| M5 生产最小发布 | 经单独授权后重新核验仓库/Prod Alembic head，部署并执行迁移；按分类→成员→一个交易日日行情同步 | 三段 fetched/normalized/rejected/written/target 对账、read-back 和幂等重放全部通过；不包含历史回补 | 进行中；迁移、分类和成员已通过，日行情已发布 2026-07-01～2026-08-18；单日空结果 no-op 已完成本地纠偏并等待部署验收 |
| M6 历史事实与回补 | 核验成员 `out_date` 边界，审计 `sw_daily` 全代码历史覆盖、配额、耗时与事务预算，提交明确窗口 | 用户批准具体日期范围后才能 PLAN/APPLY；全窗口 read-back 与幂等重放通过 | 未开始 |
| M7 自动化 | 审计三个源接口到达/变化节奏，设计独立 readiness、重试和最终失败规则 | 用户另行批准生产 schedule 的创建与启用；不得把当前 `schedule_enabled=False` 静默改为 true | 未开始 |

板块雷达的申万回测不属于本轮数据集开发；只有 M6 形成可回测日期集合并确认无前视成员谓词后，才进入后续研究阶段。

立即停止条件：

- 实施日仓库与 Prod Alembic 基线未对齐；
- `src=SW2021` 不再返回闭合的 L1/L2/L3；
- 出现除已批准规则外的新跨接口错码；
- 分页 key 集与不截断基准不一致；
- 需要新增 Raw、Lake、生产账号、连接、无条件删除或超出 `src='SW2021'` 的写入范围。

M5 已按用户授权进入生产发布；分类和成员生产验收已完成，日行情已发布到 2026-08-18，单日空结果 no-op 已完成本地纠偏并等待部署。当前仍不授权新增迁移、历史回补、研究物化或排程启用。
