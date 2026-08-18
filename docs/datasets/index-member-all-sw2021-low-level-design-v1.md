# 申万 SW2021 行业成员 `index_member_all` Prod 数据集 LLD v1

> 状态：M0～M3 已完成；成员数据集已通过真实源端、Y/N 分页、标准化、三级分类闭包、本地全量事务重放、可执行源端行数门禁和 Ops API/浏览器契约验收。迁移未在 Prod 执行，日行情数据集 M4 尚未开始。
> 初版：2026-08-16；代码对账：2026-08-17；最终产品拍板：2026-08-18；M2/M3 纠偏验收：2026-08-19。
> 前置 LLD：[申万 SW2021 行业分类 `index_classify` Prod 数据集 LLD v1](./index-classify-sw2021-low-level-design-v1.md)。
> 上游产品依据：[板块雷达产品设计方案 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-product-design-v1.md)。
> 数据依据：[板块雷达数据覆盖审计 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-data-coverage-audit-v1.md)。
> 源站依据：Tushare `index_member_all`，本地文档 `docs/sources/tushare/指数专题/0335_申万行业成分构成(分级).md`（doc_id=335）。

---

## 0. 2026-08-18 最终拍板

以下两项由用户按推荐方案确认，已成为三份申万数据集 LLD 的共同硬约束，不再列为待拍板项：

1. `index_classify` 首版只保留最近一次成功发布的完整 SW2021 分类快照，不保存抓取时点历史，也不把观察时间伪装成官方分类生效时间。历史研究如使用分类表，必须标注“按当前 SW2021 分类重述历史”。
2. `sw_daily` 服务表保留源接口按交易日返回的全部申万指数事实；板块雷达只在查询时与 `index_classify` 内连接并过滤 `is_pub=true`。源端额外综合/风格指数不得在 Foundation 入库阶段丢弃，也不得进入正式行业榜。

成员数据口径不因此改变：本表仍完整保存 Y/N 当前与历史关系；`out_date` 边界必须由业务样本核验，不属于偏好选择。

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

### 2.5 M3 当前真实验收（2026-08-18）

M3 重新通过 Tushare MCP、项目正式 `DatasetSourceClient` 和内存测试库完成只读/本地验收，没有连接 Prod、没有执行迁移或生产同步：

| 验收项 | 当前结果 |
|---|---|
| MCP 默认请求 | 3,000 行，全部 `is_new=Y`，再次证明默认返回会截断 |
| MCP 显式 11 字段 | 字段完整；`is_new=N` 返回 2,004 行 |
| 项目正式分页 | Y=`2000/2000/1895`，N=`2000/4`，共 5 请求、7,899 行 |
| 标准化 | 7,899 行，拒绝 0、完全重复去重 0 |
| 状态分布 | Y=5,895，N=2,004；Y 的非空 `out_date`=0，N 的空 `out_date`=0 |
| 唯一性与日期 | 业务主键重复 0、空 `in_date` 0、`out_date<in_date` 0 |
| 分类闭包 | L1/L2/L3 孤儿均为 0；实际涉及 31/131/338 个 L1/L2/L3 代码 |
| 关键代码 | 源 `850401.SI`=0，业务 `850412.SI`=25，业务 `840401.SI`=0 |
| 业务主键摘要 | SHA-256 `89ed980b2147c35db729b399ce2b3bc7d209879f710446d6097781598a57ca31` |
| 本地全量事务 | 先发布 511 行分类，再写入 7,899 行成员；同批重放仍为 7,899，read-back 内容一致 |

M3 同时补齐通用 `source_variant_mismatch` 门禁：每个固定 request variant 返回的 `is_new` 必须与当前请求值一致。Y/N 任一空结果或错返另一状态，都会在标准化和目标 DML 前失败，不能用“两个请求都有数据”冒充完整全集。

### 2.6 2026-08-19 M3 纠偏验收

审计发现原 20,000 行停止条件只存在于 `write_volume_assessment` 文字中，`buffer_all` 主链没有执行；IM-009 也只有 API 测试。纠偏后：

1. `planning.max_source_rows_per_unit=20000` 经 Definition、`PlanPlanning`、唯一 `PlanUnitSnapshot` 冻结到执行端，Y/N 合并后共享同一个总量预算。
2. 20,000 行必须在两个 variant 均观察到终止 short page 后才成功；任何一页使合并行数达到 20,001 时，SourceClient 立即以 `source_rows_exceeded` 失败，标准化和目标 DML 均不会开始。
3. 自动化正反例已证明 Y=10,000、N=10,000 可完成；Y=10,001、N=10,000 在 N 的最后满页达到 20,001 时失败。持续满页同样会有界退出。
4. Playwright 使用真实 Chromium 分别打开分类和成员 Manual Action，确认两个动作都不展示日期、时间范围和任何筛选控件，提交体严格为 `{"time_input":{"mode":"none"},"filters":{}}`；控制台错误和失败 API 响应均为 0。

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

| 消费方 | 本数据集固定结果 | 已核验代码位置 | M3 验收结果 |
|---|---|---|---|
| Manual Action | 只生成 `snapshot_refresh/none`，无时间和 filter | `src/ops/queries/manual_action_query_service.py` | 已由 Definition 派生；API 正反例证明不暴露 `is_new` |
| Catalog | 使用 Ops 显式目录 | `src/ops/catalog/dataset_catalog_view_resolver.py`、`src/ops/catalog/dataset_catalog_views.py` | 已登记唯一 `item_order=90` |
| Workflow | 首版不进入 workflow | `src/ops/action_catalog.py` | 不修改 workflow |
| Resolver / planner | 不用 enum fanout；固定 1 unit 内 Y/N request fan-in | `src/foundation/ingestion/resolver.py`、`src/foundation/ingestion/unit_planner.py` | 已验收 1 unit 与不可由用户覆盖的 Y/N 顺序 |
| Request builder | 成员专用 builder 只接受 snapshot profile | `src/foundation/ingestion/request_builders.py` | `_index_member_all_sw2021_params` 已实现并通过 none-only 反例 |
| Source client | 同一 unit 逐 variant 分页、校验返回状态并合并 | `src/foundation/ingestion/source_client.py` | 已验收 5 页、空/错返 variant、20,000/20,001 行边界和持续满页有界失败 |
| Freshness | `SNAPSHOT_RUN_TRACE` | `src/foundation/datasets/freshness_policies.py`、`src/ops/queries/freshness_query_service.py` | 显式映射已生效 |
| Dataset card | 无 Raw，回退展示 serving/target 表 | `src/ops/dataset_definition_projection.py`、`src/ops/queries/dataset_card_query_service.py` | API 已验收 direct-serving 展示 |
| Snapshot rebuild | 读取 Definition 与完整 TaskRun 成功轨迹 | `src/ops/services/operations_dataset_status_snapshot_service.py` | 沿用已通过的 snapshot-run-trace 主链；本期不新增专用分支 |
| Date completeness | 明确不适用 | `src/ops/services/date_completeness_audit_service.py` | `completeness.scope=not_applicable` |
| 自动任务 | 首版不开放 | `src/ops/services/schedule_automation_capability_resolver.py` | `schedule_enabled=False` |
| Source release / Probe | 不建设 | `src/ops/services/operations_schedule_service.py` | 无 probe、无绑定 |
| 前端时间控件 | 无时间、无筛选 | `frontend/src/pages/ops-v21-task-manual-tab.tsx` | 通用无时间表单契约保持不变，API 与 Playwright 浏览器输入反例已通过 |
| Ops 展示目录 | `board_theme` 第 90 位 | `src/ops/catalog/dataset_catalog_views.py` | 位于分类之后、日行情之前 |
| 数据源页 / 分层 | `raw_table=None`，展示成员服务表 | `src/ops/schemas/dataset_card.py`、`frontend/src/pages/ops-v21-source-page.tsx`、`frontend/src/pages/ops-v21-dataset-detail-page.tsx` | 不显示伪 Raw |
| Shared storage / writer | 全部 Y/N 合并后替换 SW2021 成员范围 | `src/foundation/ingestion/writer.py`、`src/foundation/datasets/definitions/_builder.py`、`src/foundation/ingestion/linter.py` | 通用 scope replace 与成员三级闭包已通过 7,899 行本地事务重放 |
| 测试与文档 | 成员数据集专项正反例已建立 | `tests/test_sw2021_index_member_all_dataset_m3.py`、`tests/web/test_ops_sw2021_index_member_all_m3.py`、`frontend/e2e/smoke-visual.spec.ts` | 后端、API 与浏览器均独立验收，不以其他数据集回归代替 |

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
| planning | `universe_policy=no_pool`，无 enum unit fanout；`request_variant_fields=(is_new,)`、`request_variant_defaults={"is_new":("Y","N")}`；`pagination_policy=offset_limit`，`page_limit=2000`，`max_source_rows_per_unit=20000`，`unit_builder_key=generic`，`max_units_per_execution=1`，`fetch_concurrency=1`，`page_processing_mode=buffer_all` |
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

现行实现不使用会把 Y/N 拆成两个独立事务的 enum fanout。M1 已通过声明式 `request_variant_fields/request_variant_defaults` 建立以下通用契约，M3 已完成成员数据集实测：

1. planner 仍只生成一个 unit，不把内部变体变成用户 filter 或独立 unit；
2. SourceClient 在同一 unit 内按声明顺序生成 Y、N 两组请求，各自从 offset 0 分页至 short page，再合并为一个 fetch result；
3. 每页必须携带同一 11 字段白名单；分页诊断分别记录 Y/N 页序列，再记录合并唯一键摘要；
4. strict validator 拒绝用户传入 `is_new`；request builder 不接受覆盖；
5. linter 要求 variant 字段不在 input_model、默认集合非空且无重复、总组合数受限，本数据集固定为 2；
6. `max_source_rows_per_unit=20000` 作为同一 unit 的 Y/N 合并总预算；20,001 行或持续满页会以 `source_rows_exceeded` 在标准化和 DML 前失败；
7. 任一 variant 空结果、返回状态与请求变体不一致、分页失败或键冲突都会使唯一 unit 失败，目标表保持不变。

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

`request_variant_*`、`replacement_scope_fields`、`empty_result_policy` 和 `pre_write_validator_key` 已在 M1 同步落到 Definition、plan snapshot、builder/linter 与运行时消费者；M3 已通过真实源端和专项回归证明不是仅修改 Definition 或 SourceClient 的半套实现。

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

M1 开工时重新确认仓库唯一 head 为 `20260816_000137`，已生成线性迁移 `20260818_000138`，其 `down_revision` 为该真实 head。M1 只生成和测试迁移，未连接 Prod、未执行 DDL；M5 实施前仍须重新核验仓库与 Prod 唯一 head。

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
| 固定 Y/N 全集 | 无输入生成 1 unit，unit 内请求 Y/N 两组 | 用户传 `is_new`、缺 N、重复 Y、额外值或源端错返状态时拒绝 |
| 显式分页 | Y=`2000/2000/1895`，N=`2000/4`；Y/N 合计 20,000 行边界可完成 | 使用默认 3000、漏页、页间冲突、20,001 行或持续满页时失败 |
| direct-serving | 只解析 serving DAO | Raw DAO、Raw 表、双写或 Lake 路径出现时 linter 失败 |
| 标准代码 | 850412 保持 850412，源码列保真 | 850401 未标准化、840401 或新冲突时失败 |
| 分类闭包 | 全部 L1/L2/L3 命中对应分类层级 | 未知代码、层级错配、分类未先发布时失败 |
| 成员身份 | 同纳入事件 Y->N 幂等更新 | 同主键不同非状态事实、空 in_date、out<in 时失败 |
| 无时间 | `mode=none` 执行 | point/range、目标日 filter 或成员每日展开被拒绝 |
| 原子发布 | Y/N 均齐备后一次替换完整范围 | 任一 variant 失败时目标表零变化 |

### 8.2 文件级实施范围

M1～M3 实际新增/修改：

- `src/foundation/datasets/sw_industry_contracts.py`
- `src/foundation/datasets/definitions/board_hotspot.py`
- `src/foundation/datasets/freshness_policies.py`
- `src/foundation/datasets/models.py`
- `src/foundation/datasets/definitions/_builder.py`
- `src/foundation/models/core_serving/sw_industry_member.py`
- `src/foundation/dao/factory.py`
- `src/foundation/ingestion/linter.py`
- `src/foundation/ingestion/codebook.py`
- `src/foundation/ingestion/request_builders.py`
- `src/foundation/ingestion/source_client.py`
- `src/foundation/ingestion/row_transforms.py`
- `src/foundation/ingestion/writer.py`
- `src/ops/catalog/dataset_catalog_views.py`
- 一条实施日确定 revision 的 Alembic 迁移
- `tests/test_sw2021_industry_datasets_m1.py`
- `tests/test_sw2021_index_member_all_dataset_m3.py`
- `tests/web/test_ops_sw2021_index_member_all_m3.py`
- `frontend/e2e/support/smoke-fixtures.ts`
- `frontend/e2e/smoke-visual.spec.ts`
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
| IM-001 | 只做 SW2021 | Definition/分类 FK | 固定 classification_version + 分类表校验 | 无版本筛选 | Definition、validator、ORM | 全部命中 SW2021 | 非 SW2021 拒绝 | 分类闭包 SQL | M3/M5 | M3 已通过；待 M5 生产发布验收 |
| IM-002 | Y/N 必须是一个原子全集 | planner/source/writer | 单 unit fixed request fan-in | 无 `is_new` 控件 | models、planner、source、writer | Y/N 齐备后发布 | 用户覆盖/缺一组/单组提前发布失败 | 5895+2004 对账 | M1/M3/M5 | M3 已通过；待 M5 生产发布验收 |
| IM-003 | 显式 2000 分页且合并有界 | source/TaskRun | 每 variant offset-limit、unit 上限 20,000 | 展示两组分页诊断 | source client | Y 3 页、N 2 页；20,000 行边界完成 | 默认 3000/漏页/错返状态/20,001 行或持续满页失败 | 页摘要与 7899 键 | M3/M5 | M3 纠偏已通过，5 页、主键摘要与 20,000/20,001 边界已记录；待 M5 |
| IM-004 | 无 Raw/Lake/双写 | storage/card | direct-serving scope replace | 卡片展示服务表 | linter、writer、Ops query | 只解析 serving DAO | Raw/双写出现失败 | source/target 对账 | M1/M3/M5 | M3 已通过本地全量事务；待 M5 |
| IM-005 | 源码保真与业务标准码 | normalization/下游 | 共享 code contracts | 不以源码关联 | contracts、transform、ORM | 850412 保持 | 850401 未归一/840401 失败 | 关键码 read-back | M1/M3/M5 | M3 已通过；待 M5 生产 read-back |
| IM-006 | 历史有效期事实保真 | ORM/normalizer | 日期解析、out>=in | 不适用 | transform、ORM、迁移 | Y/N 日期合法 | 空 in/out<in 失败 | 空值和区间 SQL | M3/M5 | M3 已通过；待 M5 生产表约束验收 |
| IM-007 | 分类三级闭包 | pre-write validator/DB | L1/L2/L3 代码、名称、父子全核验 | 不适用 | validator、ORM | 0 orphan | 未知/错层/错名失败 | 全量闭包 SQL | M3/M5 | M3 已通过；待 M5 生产闭包验收 |
| IM-008 | 空结果或任意 reject 不发布 | source/normalizer/writer | variant empty/mismatch + quality preflight | TaskRun 结构化失败 | models、source、writer、codebook | 7899 零拒绝 | 空/错返 Y/N、部分 reject 回滚 | 四段行数对账 | M1/M3/M5 | M3 已通过；待 M5 生产发布验收 |
| IM-009 | 无时间且首版无排程 | Manual Action/schedule | none-only、schedule false | 手动无时间表单 | Definition、Ops | none 可提交 | 日期/schedule 不可选 | API/Playwright 浏览器路径 | M3 | M3 纠偏已通过，浏览器提交体固定为 none + 空 filters |
| IM-010 | 不冒充每日快照/历史无前视 | 下游研究契约 | 保留 in/out/is_new；边界未验收不开放历史谓词 | 产品后续标注 | 后续 Biz 方案 | 当前成员查询 | 未确认 out_date 时历史计算阻断 | 边界样本审计 | M6 | 待实施 |

---

## 10. 三数据集统一开发里程碑与停止条件

三份 LLD 统一使用以下 M0～M7 编号。任何单份文档不得另建一套阶段含义，也不得在前置阶段未通过时提前执行后续生产动作。

| 里程碑 | 目标与交付 | 完成门禁 | 当前状态 |
|---|---|---|---|
| M0 产品与开发门禁 | 两项最终拍板写入三份 LLD；硬需求账本、影响面和实施边界一致 | 文档校验通过；用户明确允许进入 M1 | 已完成 |
| M1 共享基座与迁移准备 | 实现共享代码标准化、质量/预写校验声明、fixed request fan-in、原子 scope replace；新增三表 ORM/DAO/Definition、Ops 目录/freshness 和一条线性迁移 | CodeGraph 列出的消费者均有对应实现与回归；所有既有 writer/source/Definition 路径通过；迁移仅生成和测试，不对 Prod 执行 | 已完成（2026-08-18）；迁移 `20260818_000138` 未在 Prod 执行 |
| M2 分类数据集 | 完成 `index_classify` request、分页、transform、双唯一性、层级闭包、Ops 派生及正反例 | 511 与 31/134/346 等基线可解释；空/错码/孤儿/跨范围替换均阻断；本地或测试库幂等 | 已完成；2026-08-19 补齐 2,000/2,001 行门禁和浏览器验收，未执行 Prod 写入 |
| M3 成员数据集 | 完成单 unit 的 Y/N fan-in、分页、标准化、分类三级闭包、原子替换及 Ops 正反例 | Y/N 任一失败目标零变化；7,899 基线、唯一键、日期和闭包可解释；本地或测试库幂等 | 已完成；2026-08-19 补齐 20,000/20,001 行门禁和浏览器验收，未执行 Prod 写入 |
| M4 日行情数据集 | 完成交易日 point/range unit、15 字段、全源行保留、同日原子替换、freshness/completeness 及 Ops 正反例 | 非交易日、宽区间直传、日期越界、过滤 25 行、跨日删除均阻断；单日本地幂等 | 未开始 |
| M5 生产最小发布 | 经单独授权后重新核验仓库/Prod Alembic head，部署并执行迁移；按分类→成员→一个交易日日行情同步 | 三段 fetched/normalized/rejected/written/target 对账、read-back 和幂等重放全部通过；不包含历史回补 | 未开始 |
| M6 历史事实与回补 | 核验成员 `out_date` 边界，审计 `sw_daily` 全代码历史覆盖、配额、耗时与事务预算，提交明确窗口 | 用户批准具体日期范围后才能 PLAN/APPLY；全窗口 read-back 与幂等重放通过 | 未开始 |
| M7 自动化 | 审计三个源接口到达/变化节奏，设计独立 readiness、重试和最终失败规则 | 用户另行批准生产 schedule 的创建与启用；不得把当前 `schedule_enabled=False` 静默改为 true | 未开始 |

板块雷达的申万回测不属于本轮数据集开发；只有 M6 形成可回测日期集合并确认无前视成员谓词后，才进入后续研究阶段。

立即停止条件：

- 分类数据集未发布或成员代码无法闭合；
- Y/N 任何一组未完整分页或无法在同一 unit 原子发布；
- 出现新的跨接口错码或标准化键冲突；
- 需要把 `is_new` 暴露给运营才能完成执行；
- 需要 Raw/Lake、每日展开表、生产账号/连接、无条件删除或超出 `classification_version='SW2021'` 的写入范围；
- 在未确认 `out_date` 边界前要求出具无前视回测结论。

M3 已按用户授权完成成员数据集端到端验收。本 LLD 当前不授权 M4 日行情开发、Prod 迁移执行、生产同步、历史回补、研究物化或排程启用。
