# Foundation 当前强约束（统一基线）

更新时间：2026-09-01

## 1. 文档定位

本文件是 Foundation 研发规则的**统一基线**，用于替代分散在多份文档中的重复约束。

当以下文档出现描述冲突时，以本文件为准：

1. `dataset-publish-governance-spec-v1.md`
2. `foundation-onboarding-and-legacy-checklist-v1.md`

---

## 2. 强约束总览（必须遵守）

1. 子系统边界以 [subsystem-boundary-plan.md](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md) 为准。
2. 依赖方向以 [dependency-matrix.md](/Users/congming/github/goldenshare/docs/architecture/dependency-matrix.md) 为准。
3. Ops 状态语义以 [ops-contract-current.md](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md) 为准。
4. 数据集事实以 `src/foundation/datasets/**` 的 `DatasetDefinition` 为准。
5. 数据维护执行计划以 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan` 为准。

---

## 3. Foundation 分层与数据路径

### 3.1 默认分层

1. `core_serving`：对上业务契约层（当前主读口径）。
2. `raw_<source>`：需要保留源站原始事实、审计或重放时使用；不是所有数据集的强制前置层。
3. `core_serving_light`：高频查询性能层（可选，不替代 `core_serving`）。
4. 经正式设计批准的 direct-serving 数据集可以从源端直接写入 `core_serving`；不得为了形式完整伪造空 raw 表、影子 DAO 或双写兼容层。

### 3.2 模式语义

1. `single_source_direct`：单源对上服务，可采用 `raw -> serving`，也可采用经正式批准的 source -> serving direct-serving。
2. `multi_source_pipeline`：`raw -> std -> resolution -> serving`（多源完整链路）。
3. `raw_only`：只采集 raw，不对外服务。
4. `legacy_core_direct`：历史兼容口径，禁止新增。

### 3.3 新增能力约束

1. 新增“对外服务”数据集，默认落 `core_serving.*`。
2. 不允许新增 `core.*` 直写主路径（除已明确保留项）。
3. 仅当存在高频性能瓶颈时才引入 `core_serving_light.*`。

---

## 4. 同步链路约束

1. 同步主流程必须可观测、可重放、可恢复。
2. 时间输入能力必须由 `DatasetDefinition.date_model` 与源接口真实行为决定；允许 point、range、month、no-time snapshot 等不同模型，不要求所有数据集同时支持单时间点和时间区间。
3. 分页接口必须内部自动循环，不把分页细节暴露为运营常规参数。
4. 同步任务必须纳入 Ops 可观测对象（TaskRun + pipeline mode + freshness）。
5. 旧执行路由不再作为当前用户任务、API 或长期领域模型。
6. 预计或实测超过 60 秒，或规模会随日期、对象、分页、分区增长的任务，必须遵守仓库根 `AGENTS.md` 的长任务门禁，并完整填写 [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md) 0.3.5。

---

## 5. 数据集交付门禁（DoD）

新增/改造数据集必须同时满足：

1. 有按 [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md) 完整填写的独立数据集开发文档（`docs/datasets/*`）。
2. DatasetDefinition 中的身份、中文名、来源、日期模型、输入能力与表映射明确。
3. 落库路径与目标表明确（raw/serving/light）。
4. 幂等写入与去重策略明确。
5. Ops 交互与状态观测已接入。
6. DatasetExecutionPlan 能覆盖对应维护动作。
7. 测试清单完整（单元/集成/回归）。
8. 长任务已完成内存、持久化、续跑、进度、取消、终态一致和 worker lane 的设计与真实最小验收；非长任务已记录不适用依据。

模板入口：

1. [dataset-development-template.md](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
2. [workflow-development-template.md](/Users/congming/github/goldenshare/docs/templates/workflow-development-template.md)

---

## 6. 数值类型与表结构约束

1. 数值类型默认优先 `DOUBLE PRECISION`。
2. 使用 `NUMERIC` 需逐字段说明原因（监管口径/财务精确记账）。
3. 存在 `trade_date` 的大表默认按时间分区（年或月，需说明理由）。
4. 主键、唯一键和冲突键必须从源端真实身份与业务语义推导；`(ts_code, trade_date)` 只能作为候选，不能作为默认答案。`freq/category/type/market/hot_type/is_new` 等身份字段必须通过真实样本决定是否入键。
5. 只有存在日期驱动读写路径时才要求对应日期索引；索引字段和顺序必须由真实查询、同步范围与表规模决定。

---

## 7. 验收最小基线

1. 架构护栏：
   - `pytest -q tests/architecture/test_subsystem_dependency_matrix.py`
2. Web 健康：
   - `GET /api/health`
   - `GET /api/v1/health`
3. Ops 可见性：
   - `/api/v1/ops/dataset-cards`
   - `/api/v1/ops/freshness`

---

## 8. 文档协作规则

1. 本文件维护“当前强约束”；专题文档维护“领域细节”。
2. 任何变更先改文档，再改代码。
3. 若专题文档与本文件不一致，先修正文档再继续开发。
