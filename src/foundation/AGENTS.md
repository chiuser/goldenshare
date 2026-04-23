# AGENTS.md — `src/foundation/` 子系统规则

## 适用范围

本文件适用于 `src/foundation/` 目录及其子目录。  
若子目录存在更近的 `AGENTS.md`，以更近规则为准。

---

## 1. 子系统定位

`foundation` 是数据基座子系统，负责：

1. 数据源接入、同步、落库、基础模型与 DAO。
2. 底层契约（kernel/contracts）与通用基础能力。
3. 与上层解耦的可复用组件（不承载 ops/biz/app 业务语义）。

`foundation` 不负责：

1. 运维治理 API/运行编排（属于 `src/ops/**`）。
2. 对上业务 API/查询语义（属于 `src/biz/**`）。
3. 应用入口装配（属于 `src/app/**`）。

---

## 2. 硬约束

1. 禁止引入 `foundation -> ops|operations|biz|app|platform` 反向依赖。
2. 禁止把主实现写回 `src/platform/**` 或 `src/operations/**`。
3. 禁止恢复或新建 `src.foundation.services.sync.*`（Sync V1 已退场）。
4. 同步主链统一走 `src/foundation/services/sync_v2/**`。
5. 不允许“补丁叠补丁”；发现结构失真时优先提出重构方案。

---

## 3. 目录职责速记

1. `kernel/`：内核级契约与基础抽象。
2. `models/`：raw/core/core_serving/core_serving_light 等数据模型。
3. `dao/`：数据访问层。
4. `services/sync_v2/`：同步 V2 主链（contract/engine/planner/writer）。
5. `services/transform/`：离线转换与规范化工具。
6. `services/migration/`：迁移辅助（仅迁移用途，不承接日常主链）。
7. `connectors/`、`clients/`：外部源接入与 SDK/HTTP 客户端封装。

---

## 4. 常见误改点（禁止）

1. 在 engine/planner 中硬编码某个数据集特例。
2. 在 DAO 里加入业务编排逻辑（调度、重试、跨表策略）。
3. 在 models 改字段后不评估迁移与上下游兼容。
4. 在 foundation 中直接依赖 ops 执行表语义。

---

## 5. 动手前必读

1. `/Users/congming/github/goldenshare/AGENTS.md`
2. `/Users/congming/github/goldenshare/src/AGENTS.md`
3. `/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md`
4. `/Users/congming/github/goldenshare/docs/architecture/dependency-matrix.md`

---

## 6. 最小门禁

涉及 foundation 边界或同步主链改动时，至少执行：

1. `pytest -q tests/architecture/test_subsystem_dependency_matrix.py`
2. `pytest -q tests/architecture/test_sync_v2_registry_guardrails.py`
3. `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts`

