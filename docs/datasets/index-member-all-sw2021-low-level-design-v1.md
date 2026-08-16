# 申万 SW2021 行业成员 `index_member_all` Prod 数据集 LLD v1

> 状态：LLD 已按当前代码完成纠偏，等待评审；尚未编码、迁移、同步或创建生产排程。
> 初版：2026-08-16；本次代码对账：2026-08-17。
> 前置 LLD：[申万 SW2021 行业分类 `index_classify` Prod 数据集 LLD v1](./index-classify-sw2021-low-level-design-v1.md)。
> 上游产品依据：[板块雷达产品设计方案 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-product-design-v1.md)。
> 数据依据：[板块雷达数据覆盖审计 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-data-coverage-audit-v1.md)。
> 源站依据：Tushare `index_member_all`，本地文档 `docs/sources/tushare/指数专题/0335_申万行业成分构成(分级).md`（doc_id=335）。

---

## 1. 结论与边界

本数据集负责把 Tushare SW2021 申万三级行业的当前和历史成员关系直接发布到 Prod `core_serving.sw_industry_member`。它保存来源给出的纳入日、剔除日和当前状态，不按交易日展开成员快照，也不在入库阶段推导目标日是否有效。

已冻结口径：

1. 数据集 key 和源 API 均固定为 `index_member_all`。
2. 首版行业体系只做 `SW2021`；成员事实必须与 `core_serving.sw_industry_classification.src='SW2021'` 对账。
3. 使用 `source -> core_serving` direct-serving；不建设 Raw、Lake 或双写。
4. 正式全集由一个逻辑 unit 组成；unit 内顺序执行两个固定请求变体 `is_new=Y`、`is_new=N` 并汇聚完整分页结果。`is_new` 不是运营筛选项，用户不得改变或遗漏其中一组。
5. 一级、二级、三级源代码均保存在 `source_l*_code`；业务关联只使用标准化后的 `l*_code`。
6. “特钢Ⅲ”的业务标准码固定为 `850412.SI`；`840401` 禁止进入任何字段、规则和测试样本。
7. 不用当前 `is_new=Y` 快照冒充历史成员；历史研究必须使用 `in_date/out_date` 并在回测前确认剔除日边界语义。
8. 本期不建设成员权重、每日成员展开表、板块雷达计算、API 或前端。

### 1.1 架构归属

```text
Tushare index_member_all
  -> DatasetDefinition(index_member_all)
  -> DatasetActionResolver(mode=none)
  -> 1 个 snapshot_refresh unit
  -> unit 内 fixed request fan-in: is_new=Y / is_new=N
  -> 每个 request variant 独立 offset/limit 分页
  -> SW2021 代码标准化与分类闭包校验
  -> core_serving.sw_industry_member
  -> Ops TaskRun / snapshot_run_trace
```

- Foundation domain：`board_theme`。
- Ops 展示分组：`board_theme / 板块 / 题材`。
- 前置数据集：`index_classify` 必须先成功发布并通过 read-back。
- 依赖方向保持 `foundation <- ops/biz/app`，不新增反向依赖。

---

## 2. 真实源接口证据

### 2.1 请求矩阵

2026-08-16 通过项目现有 `TushareHttpClient` 只读实测：

| 请求形态 | 参数 | 行数/分页 | 结论 |
|---|---|---:|---|
| 不传业务参数 | `{}` | 3,000 行，全部 `is_new=Y` | 返回被默认上限截断，禁止作为正式全集请求 |
| 当前成员全集 | `is_new=Y, limit=2000` | `2000/2000/1895`，合计 5,895 | 必须显式分页 |
| 历史成员全集 | `is_new=N, limit=2000` | `2000/4`，合计 2,004 | 必须与 Y 独立拉取 |
| 当前+历史合并 | Y + N | 7,899 | 首次同步基线 |
| 异常源代码 | `l3_code=850401.SI, is_new=Y/N` | `0/0` | 成员源没有该代码 |
| 业务标准码 | `l3_code=850412.SI, is_new=Y/N` | `13/12` | 成员接口使用 `850412.SI` |
| 时间点/区间 | 不适用 | 不适用 | 接口没有业务日期输入 |
| 默认字段 | `is_new=Y`，不传 `fields` | 已实测 | 不能替代显式 11 字段契约 |
| 显式完整字段 | Y/N 均显式 11 字段 | 已实测返回完整字段 | 正式 connector 每页、每个 variant 必须使用同一字段白名单 |

合并 7,899 行后：

- `(l3_code, ts_code, in_date)` 重复 0 行；
- `in_date` 空值 0 行；
- 5,895 行当前成员的 `out_date` 均为空；
- 所有三级代码均能在标准化后的 SW2021 分类中找到；
- `850412.SI` 有 25 条当前和历史成员事实，`850401.SI` 为 0。

`tushare-data` 接口家族结论：`index_member_all` 是申万分级行业与股票的关系事实，包含纳入/剔除日期，但不提供分类主表、行情或成员权重。

### 2.2 源文档与实测差异

本地来源文档写明“单次最大 2,000 行”，但当前项目连接器在不传 `limit` 时实际返回 3,000 行。该差异不能解释为接口允许完整返回，因为 Y 全集实际为 5,895 行。

正式契约固定为：

1. 每页显式发送 `limit=2000`。
2. offset 从 0 开始按实际 page size 推进。
3. 以 short page 结束，禁止把默认返回行数当作全集。
4. 验收记录每个 `is_new` unit 的页序列、页行数、合并行数和唯一键摘要。

### 2.3 字段验证

正式 `source_fields` 必须显式包含全部 11 个源字段：

```text
l1_code, l1_name, l2_code, l2_name, l3_code, l3_name,
ts_code, name, in_date, out_date, is_new
```

不能因样例表未展示 `out_date/is_new` 就省略；这两个字段直接决定历史成员语义和幂等更新。

### 2.4 源输入参数与运营暴露

| 源参数 | 源端可选 | 正式用途 | 运营是否可填 |
|---|---|---|---|
| `is_new` | 是，默认 Y | unit 内固定 request variant `Y/N` | 否 |
| `l1_code/l2_code/l3_code` | 是 | 仅只读核验/诊断 | 否 |
| `ts_code` | 是 | 仅只读核验/诊断 | 否 |
| `limit/offset` | 是 | 每个 request variant 的通用分页器生成 | 否 |

任何对象过滤都会把“成员全集”降成子集，所以不能进入 `DatasetInputModel`。不传 `is_new` 等价于默认 Y，会漏掉历史成员，也不能作为正式请求。

---

## 3. 三层时间语义

| 语义层 | 固定设计 |
|---|---|
| 时间输入 | 无时间；运营只发起“刷新 SW2021 成员全集” |
| 执行/unit | 固定生成 1 个 snapshot unit；source client 在该 unit 内按 Y、N 两个固定 request variant 顺序分页并合并 |
| freshness/audit | 不建立每日日期桶；只观察最近一次完整 TaskRun 成功时间 |

`DatasetDateModel`：

```python
{
    "date_axis": "none",
    "bucket_rule": "not_applicable",
    "window_mode": "none",
    "input_shape": "none",
    "observed_field": None,
    "audit_applicable": False,
    "not_applicable_reason": "成员接口返回带纳入/剔除日期的关系全集，本数据集自身不是按日同步的数据集。",
}
```

`not_applicable` 只描述维护输入和 freshness，不表示 `in_date/out_date` 没有业务时间语义。

### 3.1 目标日成员口径

服务表原样保存 `in_date/out_date/is_new`。板块雷达回测前必须用源端样本确认 `out_date` 是“最后有效日”还是“首个无效日”，再冻结目标日有效成员谓词。LLD 当前禁止猜测以下任一写法：

```text
in_date <= target_date <= out_date
in_date <= target_date <  out_date
```

在该边界未验收前，只允许用 `is_new=true` 查询当前成员，不能宣称历史回测已无前视。

### 3.2 当前代码消费者审计

| 消费方 | 本数据集固定结果 | 已核验代码位置 | 实施影响 |
|---|---|---|---|
| Manual Action | 只生成 `snapshot_refresh/none`，无时间和 filter | `src/ops/queries/manual_action_query_service.py` | 新增 Definition 后自动派生；不暴露 `is_new` |
| Catalog | 使用 Ops 显式目录 | `src/ops/catalog/dataset_catalog_view_resolver.py`、`src/ops/catalog/dataset_catalog_views.py` | 新增唯一 `item_order=90` |
| Workflow | 首版不进入 workflow | `src/ops/action_catalog.py` | 不修改 workflow |
| Resolver / planner | 当前 enum fanout 会生成两个 unit，不满足原子全集 | `src/foundation/ingestion/resolver.py`、`src/foundation/ingestion/unit_planner.py` | 不使用 enum fanout；新增固定 request fan-in 计划字段，仍只生成 1 unit |
| Request builder | 当前不存在成员专用 builder | `src/foundation/ingestion/request_builders.py` | 新增 `_index_member_all_sw2021_params`，只校验 snapshot profile |
| Source client | 当前每 unit 只有一组 request params | `src/foundation/ingestion/source_client.py` | 新增声明式 fixed request fan-in；逐 variant 分页、最后合并 |
| Freshness | `SNAPSHOT_RUN_TRACE` | `src/foundation/datasets/freshness_policies.py`、`src/ops/queries/freshness_query_service.py` | 新增显式映射 |
| Dataset card | 无 Raw，回退展示 serving/target 表 | `src/ops/dataset_definition_projection.py`、`src/ops/queries/dataset_card_query_service.py` | 补 direct-serving 回归 |
| Snapshot rebuild | 读取 Definition 与完整 TaskRun 成功轨迹 | `src/ops/services/operations_dataset_status_snapshot_service.py` | 只有单 unit 全集发布成功才更新 |
| Date completeness | 明确不适用 | `src/ops/services/date_completeness_audit_service.py` | `completeness.scope=not_applicable` |
| 自动任务 | 首版不开放 | `src/ops/services/schedule_automation_capability_resolver.py` | `schedule_enabled=False` |
| Source release / Probe | 不建设 | `src/ops/services/operations_schedule_service.py` | 无 probe、无绑定 |
| 前端时间控件 | 无时间、无筛选 | `frontend/src/pages/ops-v21-task-manual-tab.tsx` | 只验证通用无时间表单 |
| Ops 展示目录 | `board_theme` 第 90 位 | `src/ops/catalog/dataset_catalog_views.py` | 位于分类之后、日行情之前 |
| 数据源页 / 分层 | `raw_table=None`，展示成员服务表 | `src/ops/schemas/dataset_card.py`、`frontend/src/pages/ops-v21-source-page.tsx`、`frontend/src/pages/ops-v21-dataset-detail-page.tsx` | 不显示伪 Raw |
| Shared storage / writer | 全部 Y/N 合并后替换 SW2021 成员范围 | `src/foundation/ingestion/writer.py`、`src/foundation/datasets/definitions/_builder.py`、`src/foundation/ingestion/linter.py` | 复用分类 LLD 新增的通用 scope replace；补跨表预写校验 |
| 测试与文档 | 新数据集尚不存在 | registry/planner/source/writer/Ops 测试 | 不能以现有数据集回归代替本数据集验收 |

---

## 4. 字段端到端设计

| 源字段 | 源文档 | 真实样本 | `source_fields` | Raw ORM/迁移 | Serving ORM/迁移 | Lake | 必填 | 目标与规则 |
|---|---|---|---|---|---|---|---|---|
| `l1_code` | 是 | 是 | 是 | 不适用 | `source_l1_code`、`l1_code` | 不适用 | 是 | 源码保真并生成业务码 |
| `l1_name` | 是 | 是 | 是 | 不适用 | `l1_name varchar(64)` | 不适用 | 是 | 必须与分类 L1 名称一致 |
| `l2_code` | 是 | 是 | 是 | 不适用 | `source_l2_code`、`l2_code` | 不适用 | 是 | 源码保真并生成业务码 |
| `l2_name` | 是 | 是 | 是 | 不适用 | `l2_name varchar(64)` | 不适用 | 是 | 必须与分类 L2 名称一致 |
| `l3_code` | 是 | 是 | 是 | 不适用 | `source_l3_code`、`l3_code` | 不适用 | 是 | 业务主键组成，必须命中分类 L3 |
| `l3_name` | 是 | 是 | 是 | 不适用 | `l3_name varchar(64)` | 不适用 | 是 | 必须与分类 L3 名称一致 |
| `ts_code` | 是 | 是 | 是 | 不适用 | `ts_code varchar(16)` | 不适用 | 是 | 成分股票代码，主键组成 |
| `name` | 是 | 是 | 是 | 不适用 | `stock_name varchar(64)` | 不适用 | 是 | 成分股票名称 |
| `in_date` | 是 | 是 | 是 | 不适用 | `in_date date` | 不适用 | 是 | 纳入日期，主键组成 |
| `out_date` | 是 | Y/N 显式样本已返回 | 是 | 不适用 | `out_date date NULL` | 不适用 | 否 | 当前成员为空，历史成员允许值 |
| `is_new` | 是 | Y/N 显式样本已返回 | 是 | 不适用 | `is_new boolean` | 不适用 | 是 | `Y/N -> true/false` |

系统字段不进入 `source_fields`：`classification_version='SW2021'`、`source='tushare'`、`normalization_rule_version='sw2021-index-code-v1'`、`created_at/updated_at`。Raw ORM、Raw 迁移、Lake 白名单和每日成员展开表均为“不适用”。

### 4.1 标准化与跨表闭包

三个层级代码统一调用 `src/foundation/datasets/sw_industry_contracts.py` 的同一标准化函数：

1. 先保存 `source_l*_code`。
2. 将源代码 `850401.SI` 规范为业务码 `850412.SI`；分类接口额外要求其 `industry_code=230501`。
3. 当前成员源本身已返回 `850412.SI`，因此首次正常化不应改变这 25 条事实。
4. `840401` 无论是否带 `.SI` 都必须作为非法代码拒绝。
5. 每条 `l1/l2/l3_code` 必须分别命中分类表对应的 L1/L2/L3；三级代码与 `classification_version` 形成数据库外键。
6. 标准化后若两个不同源记录落到同一业务主键且非完全相同，必须拒绝冲突并使 unit 失败。

---

## 5. DatasetDefinition 设计

| 段 | 固定值 |
|---|---|
| identity | `dataset_key=index_member_all`，显示名“申万 SW2021 行业成员” |
| domain | `board_theme / 板块 / 题材` |
| source | `source_key_default=tushare`，`source_keys=(tushare,)`，`adapter=tushare`，`api_name=index_member_all`，`source_doc_id=tushare.index_member_all`，`request_builder_key=_index_member_all_sw2021_params`，`base_params={}`，`release_policy=same_day` |
| input_model | 无时间字段、无 filter；`is_new/l1_code/l2_code/l3_code/ts_code` 均不向运营暴露 |
| storage | `delivery_mode=core_direct`，`layer_plan=source->serving`，无 Raw/Std；`core_dao_name=sw_industry_member`，`target_table=serving_table=core_serving.sw_industry_member`，`write_path=serving_direct_scope_replace`，`raw_conflict_columns=None`，`conflict_columns=(l3_code,ts_code,in_date)`，`replacement_scope_fields=(classification_version,)`，`row_identity_filters={}` |
| planning | `universe_policy=no_pool`，无 enum unit fanout；新增 `request_variant_fields=(is_new,)`、`request_variant_defaults={"is_new":("Y","N")}`；`pagination_policy=offset_limit`，`page_limit=2000`，`unit_builder_key=generic`，`max_units_per_execution=1`，`fetch_concurrency=1`，`page_processing_mode=buffer_all` |
| normalization | `date_fields=(in_date,out_date)`，无 decimal；`row_transform_name=normalize_sw2021_member_row`；三级代码标准化，分类闭包由预写校验完成 |
| capabilities | `maintain` 允许手动和重试、`schedule_enabled=False`，只支持 `none` |
| observability | `snapshot_run_trace`，无日期完整性审计 |
| completeness | `scope=not_applicable`，无 subject/universe；原因同 date model |
| transaction | `commit_policy=unit`、`idempotent_write_required=True`；唯一 unit 缓冲约 7,899 行、5 页，总量超过 20,000 行时停止复核内存、配额与事务预算 |

Definition 落点：`src/foundation/datasets/definitions/board_hotspot.py`。Freshness 显式登记：

```python
FRESHNESS_POLICY_BY_DATASET["index_member_all"] = SNAPSHOT_RUN_TRACE
```

### 5.1 固定 request fan-in 的最小共享契约调整

当前 enum fanout 会把 Y/N 拆成两个独立事务，无法保证成员全集原子发布；当前 SourceClient 又只执行一组 request params。因此实施时新增声明式 `request_variant_fields/request_variant_defaults`，语义固定为：

1. planner 仍只生成一个 unit，不把内部变体变成用户 filter 或独立 unit；
2. SourceClient 在同一 unit 内按声明顺序生成 Y、N 两组请求，各自从 offset 0 分页至 short page，再合并为一个 fetch result；
3. 每页必须携带同一 11 字段白名单；分页诊断分别记录 Y/N 页序列，再记录合并唯一键摘要；
4. strict validator 拒绝用户传入 `is_new`；request builder 不接受覆盖；
5. linter 要求 variant 字段不在 input_model、默认集合非空且无重复、总组合数受限，本数据集固定为 2；
6. 任一 variant 空结果、分页失败或键冲突都会使唯一 unit 失败，目标表保持不变。

这是通用 source-fetch 契约，不得在 executor/source client 中按 `dataset_key` 写成员特例。模型、resolver plan snapshot、source client、linter、TaskRun 分页诊断和既有单请求路径都要有回归。

### 5.2 质量策略

```python
"quality": {
    "reject_policy": "fail_unit_on_any_rejection",
    "empty_result_policy": "fail_unit_per_request_variant",
    "required_fields": (
        "source_l1_code", "l1_code", "l1_name",
        "source_l2_code", "l2_code", "l2_name",
        "source_l3_code", "l3_code", "l3_name",
        "ts_code", "stock_name", "in_date", "is_new",
        "classification_version", "source",
        "normalization_rule_version",
    ),
    "duplicate_key_policy": "allow",
    "source_multiplicity_policy": "deduplicate_identical",
    "batch_unique_key_fields": ("l3_code", "ts_code", "in_date"),
    "pre_write_validator_key": "sw2021_member_snapshot",
}
```

预写校验器使用 writer 的同一业务 session，只读分类服务表并一次性建立 SW2021 L1/L2/L3 映射，逐行核验代码、名称和父子关系；数据库外键继续只约束 L3，不能用该外键冒充完整三级闭包。任何 reject、空 Y、空 N、分类缺失或闭包冲突都在目标 DML 前失败。

当前模型尚无 `request_variant_*`、`replacement_scope_fields`、`empty_result_policy` 和 `pre_write_validator_key`。这些字段及其 plan snapshot、builder/linter 校验和运行时消费者必须在同一实现阶段落齐；只改 Definition 或只改 SourceClient 都不算完成。

本数据集同样不复用 `row_identity_filters` 作为写入条件。writer 必须在 Y/N 合并、标准化和预写校验之后，从 normalized batch 提取唯一 `classification_version='SW2021'` scope tuple；零个或多个版本都必须在目标 DML 前失败。

7,899、5,895/2,004 和 `850412.SI=25` 是 M0 实测基线，不是永久硬编码常量。源站合法修订允许行数变化，但必须重新通过分页、唯一键和分类闭包验收。

---

## 6. 表、DAO 与迁移

### 6.1 ORM

- 文件：`src/foundation/models/core_serving/sw_industry_member.py`
- 类：`SwIndustryMember`
- 表：`core_serving.sw_industry_member`
- 主键/冲突键：`(l3_code, ts_code, in_date)`
- 外键：`(classification_version, l3_code)` 引用分类表唯一键 `(src, index_code)`
- 检查约束：`out_date IS NULL OR out_date >= in_date`
- 索引：
  - `(l3_code, is_new, ts_code)`：当前成员查询；
  - `(l3_code, in_date, out_date)`：目标日成员查询；
  - `(ts_code, in_date, out_date)`：股票历史行业归属查询。
- 不分区：首版不足一万行，分区没有收益。

主键不含 `is_new`，因为同一纳入事件从当前变成历史时应更新原行的 `is_new/out_date`，不能产生两条业务事实。

### 6.2 DAO

复用 `GenericDAO`，在 `DAOFactory` 增加 `sw_industry_member` 属性；不在 DAO 推导目标日成员，也不新增专用事务层。

### 6.3 Alembic

三张申万服务表可在同一个线性迁移中创建，顺序必须是分类表、成员表、日行情表。迁移只建表、约束和索引，不 seed、不回填、不删除旧数据、不创建账号或模块专属 GRANT。

2026-08-17 只读审计时，仓库和 Prod `public.alembic_version` 均为唯一 head `20260816_000137`。实施日必须重新对账，不能在本文预写 revision 或猜测 `down_revision`。

---

## 7. Ingestion、Ops 与消费者

### 7.1 请求、分页与事务

1. resolver 固定只产生 1 个 unit，不接受 `is_new` 输入覆盖。
2. SourceClient 固定按 Y 后 N 执行；每个 variant 每页显式带 11 个 `source_fields`、`limit=2000` 和当前 offset。
3. Y/N 全部分页在唯一 unit 内合并、标准化、去重和跨表校验，再进入 writer。
4. `serving_direct_scope_replace` 从 normalized batch 的唯一 scope tuple 得到 `classification_version='SW2021'`，只参数化替换该范围：同一事务内删除旧范围、插入本次完整集合、按主键和内容摘要 read-back；任一环节失败整体回滚。
5. 禁止 `TRUNCATE`、无条件 DELETE、按单个 Y/N 范围提前发布或触碰其他分类版本。
6. 同一完整请求重放应得到相同键集和内容摘要；源集合合法收缩会通过范围替换准确反映，不保留幽灵成员。

### 7.2 Ops 派生

| 消费方 | 设计结果 |
|---|---|
| Manual Action | 一个“刷新成员全集”动作；无日期、状态、层级、代码 filter |
| Catalog | `board_theme` 组，固定 `item_order=90` |
| TaskRun | 一个全集 unit，分别展示 Y/N 页数、offset、页行数和最终合并行数 |
| Freshness | 最近一次完整 TaskRun 成功时间；不显示每日缺口 |
| Date completeness | 不适用 |
| Dataset card | `raw_table=null`，服务表为 `core_serving.sw_industry_member` |
| Schedule | 首版 `schedule_enabled=False`；不创建或展示自动任务能力 |
| Workflow | 首版不新增；runbook 显式保证分类先于成员 |

### 7.3 后续业务消费者契约

板块雷达使用标准业务 `l1/l2/l3_code`，不得使用 `source_l*_code` 关联。当前分析可使用 `is_new=true`；历史分析必须在剔除日语义验收后按 `in_date/out_date` 选取目标日成员。

本表不提供权重。等权或目标日流通市值权重由研究层结合目标日股票事实计算，不能把成员行序、`is_new` 或名称当作权重。

---

## 8. 测试与验收

### 8.1 正反例

| 约束 | 正向测试 | 反向测试 |
|---|---|---|
| 固定 Y/N 全集 | 无输入生成 1 unit，unit 内请求 Y/N 两组 | 用户传 `is_new`、缺 N、重复 Y 或额外值时拒绝 |
| 显式分页 | Y=`2000/2000/1895`，N=`2000/4` | 使用默认 3000、漏页、页间冲突或不以 short page 结束时失败 |
| direct-serving | 只解析 serving DAO | Raw DAO、Raw 表、双写或 Lake 路径出现时 linter 失败 |
| 标准代码 | 850412 保持 850412，源码列保真 | 850401 未标准化、840401 或新冲突时失败 |
| 分类闭包 | 全部 L1/L2/L3 命中对应分类层级 | 未知代码、层级错配、分类未先发布时失败 |
| 成员身份 | 同纳入事件 Y->N 幂等更新 | 同主键不同非状态事实、空 in_date、out<in 时失败 |
| 无时间 | `mode=none` 执行 | point/range、目标日 filter 或成员每日展开被拒绝 |
| 原子发布 | Y/N 均齐备后一次替换完整范围 | 任一 variant 失败时目标表零变化 |

### 8.2 文件级实施范围

计划新增/修改：

- `src/foundation/datasets/sw_industry_contracts.py`
- `src/foundation/datasets/definitions/board_hotspot.py`
- `src/foundation/datasets/freshness_policies.py`
- `src/foundation/datasets/models.py`
- `src/foundation/datasets/definitions/_builder.py`
- `src/foundation/models/core_serving/sw_industry_member.py`
- `src/foundation/dao/factory.py`
- `src/foundation/ingestion/linter.py`
- `src/foundation/ingestion/request_builders.py`
- `src/foundation/ingestion/source_client.py`
- `src/foundation/ingestion/row_transforms.py`
- `src/foundation/ingestion/writer.py`
- `src/ops/catalog/dataset_catalog_views.py`
- 一条实施日确定 revision 的 Alembic 迁移
- Definition、linter、resolver、source client、normalizer、writer、Ops API、数据源卡片和迁移测试

不修改 `src/platform/**`、`src/operations/**`、Lake/Dagster 或 Wealth 页面。

### 8.3 真实验收

首次发布必须记录：

```text
source_y_rows = 5895
source_n_rows = 2004
source_total_rows = 7899
normalized_rows = 7899
rejected_rows = 0
target_unique_rows = 7899
duplicate_business_keys = 0
null_in_date_rows = 0
out_before_in_rows = 0
classification_orphan_rows = 0
source_850401_rows = 0
business_850412_rows = 25
business_840401_rows = 0
```

数字变化不自动等于失败；必须解释为源站修订，并重新核验唯一键、分类闭包、Y/N 分布和关键代码。

---

## 9. 硬需求追溯账本

| ID | 硬需求与依据 | 影响层/消费者 | 后端权威约束 | 前端表现 | 实现文件 | 正向测试 | 反向测试 | 真实验证 | 阶段 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|
| IM-001 | 只做 SW2021 | Definition/分类 FK | 固定 classification_version + 分类表校验 | 无版本筛选 | Definition、validator、ORM | 全部命中 SW2021 | 非 SW2021 拒绝 | 分类闭包 SQL | M1/M2/M3 | 待实施 |
| IM-002 | Y/N 必须是一个原子全集 | planner/source/writer | 单 unit fixed request fan-in | 无 `is_new` 控件 | models、planner、source、writer | Y/N 齐备后发布 | 用户覆盖/缺一组/单组提前发布失败 | 5895+2004 对账 | M2/M3 | 待实施 |
| IM-003 | 显式 2000 分页 | source/TaskRun | 每 variant offset-limit | 展示两组分页诊断 | source client | Y 3 页、N 2 页 | 默认 3000/漏页/无 short page 失败 | 页摘要与 7899 键 | M2/M3 | 待实施 |
| IM-004 | 无 Raw/Lake/双写 | storage/card | direct-serving scope replace | 卡片展示服务表 | linter、writer、Ops query | 只解析 serving DAO | Raw/双写出现失败 | source/target 对账 | M1/M2/M3 | 待实施 |
| IM-005 | 源码保真与业务标准码 | normalization/下游 | 共享 code contracts | 不以源码关联 | contracts、transform、ORM | 850412 保持 | 850401 未归一/840401 失败 | 关键码 read-back | M2/M3 | 待实施 |
| IM-006 | 历史有效期事实保真 | ORM/normalizer | 日期解析、out>=in | 不适用 | transform、ORM、迁移 | Y/N 日期合法 | 空 in/out<in 失败 | 空值和区间 SQL | M2/M3 | 待实施 |
| IM-007 | 分类三级闭包 | pre-write validator/DB | L1/L2/L3 代码、名称、父子全核验 | 不适用 | validator、ORM | 0 orphan | 未知/错层/错名失败 | 全量闭包 SQL | M2/M3 | 待实施 |
| IM-008 | 空结果或任意 reject 不发布 | source/normalizer/writer | variant empty + quality preflight | TaskRun 结构化失败 | models、source、writer、codebook | 7899 零拒绝 | 空 Y/N、部分 reject 回滚 | 四段行数对账 | M2/M3 | 待实施 |
| IM-009 | 无时间且首版无排程 | Manual Action/schedule | none-only、schedule false | 手动无时间表单 | Definition、Ops | none 可提交 | 日期/schedule 不可选 | API/浏览器路径 | M2 | 待实施 |
| IM-010 | 不冒充每日快照/历史无前视 | 下游研究契约 | 保留 in/out/is_new；边界未验收不开放历史谓词 | 产品后续标注 | 后续 Biz 方案 | 当前成员查询 | 未确认 out_date 时历史计算阻断 | 边界样本审计 | M4 | 待实施 |

---

## 10. 实施顺序与停止条件

1. M0：评审三份纠偏后的 LLD；确认新增共享质量字段、固定 request fan-in、预写校验注册表和范围替换 writer 契约，再重新确认 CodeGraph 与 Alembic/Prod 基线。
2. M1：随分类表一起实现共享契约、ORM/DAO/Definition/迁移，不运行生产迁移。
3. M2：实现 fixed request fan-in、成员标准化、跨表预写校验、范围替换、分页诊断和 Ops 正反例。
4. M3：分类生产 read-back 通过后，执行成员最小真实同步和 read-back。
5. M4：成员有效期边界样本验收后，才允许用于无前视历史回测。

立即停止条件：

- 分类数据集未发布或成员代码无法闭合；
- Y/N 任何一组未完整分页或无法在同一 unit 原子发布；
- 出现新的跨接口错码或标准化键冲突；
- 需要把 `is_new` 暴露给运营才能完成执行；
- 需要 Raw/Lake、每日展开表、生产账号/连接、无条件删除或超出 `classification_version='SW2021'` 的写入范围；
- 在未确认 `out_date` 边界前要求出具无前视回测结论。

本 LLD 不授权编码、迁移、生产同步、历史回补、研究物化或排程启用。
