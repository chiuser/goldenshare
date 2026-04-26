# Foundation 当前强约束（统一基线）

更新时间：2026-04-26

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

1. `raw_<source>`：来源保真层（必须保留审计与重放能力）。
2. `core_serving`：对上业务契约层（当前主读口径）。
3. `core_serving_light`：高频查询性能层（可选，不替代 `core_serving`）。

### 3.2 模式语义

1. `single_source_direct`：`raw -> serving`（单源直出）。
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
2. 时间语义接口必须同时支持：
   - 单时间点同步
   - 时间区间回补
3. 分页接口必须内部自动循环，不把分页细节暴露为运营常规参数。
4. 同步任务必须纳入 Ops 可观测对象（TaskRun + pipeline mode + layer snapshot）。
5. 旧执行路由不再作为当前用户任务、API 或长期领域模型。

---

## 5. 数据集交付门禁（DoD）

新增/改造数据集必须同时满足：

1. 有独立数据集开发文档（`docs/datasets/*`）。
2. DatasetDefinition 中的身份、中文名、来源、日期模型、输入能力与表映射明确。
3. 落库路径与目标表明确（raw/serving/light）。
4. 幂等写入与去重策略明确。
5. Ops 交互与状态观测已接入。
6. DatasetExecutionPlan 能覆盖对应维护动作。
7. 测试清单完整（单元/集成/回归）。

模板入口：

1. [dataset-development-template.md](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
2. [workflow-development-template.md](/Users/congming/github/goldenshare/docs/templates/workflow-development-template.md)

---

## 6. 数值类型与表结构约束

1. 数值类型默认优先 `DOUBLE PRECISION`。
2. 使用 `NUMERIC` 需逐字段说明原因（监管口径/财务精确记账）。
3. 存在 `trade_date` 的大表默认按时间分区（年或月，需说明理由）。
4. 常规行情语义主键优先 `(ts_code, trade_date)`。
5. 至少提供 `trade_date` 方向索引用于按日同步与检索。

---

## 7. 验收最小基线

1. 架构护栏：
   - `pytest -q tests/architecture/test_subsystem_dependency_matrix.py`
2. Web 健康：
   - `GET /api/health`
   - `GET /api/v1/health`
3. Ops 可见性：
   - `/api/v1/ops/dataset-cards`
   - `/api/v1/ops/layer-snapshots/latest`
   - `/api/v1/ops/freshness`

---

## 8. 文档协作规则

1. 本文件维护“当前强约束”；专题文档维护“领域细节”。
2. 任何变更先改文档，再改代码。
3. 若专题文档与本文件不一致，先修正文档再继续开发。
