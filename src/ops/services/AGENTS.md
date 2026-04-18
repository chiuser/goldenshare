# AGENTS.md — src/ops/services 主承接目录规则

## 适用范围

本文件适用于 `src/ops/services/` 目录及其所有子目录。

若更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前工作目录的 `AGENTS.md` 为准。

---

## 当前阶段定义

`src/ops/services` 现在是运维治理与运行编排 service 的**主承接目录**。

当前仓库处于 `operations/services -> ops/services` 渐进收敛阶段：
- 新的长期 ops service 逻辑，优先进入本目录
- 从 `src/operations/services` 迁来的历史实现，也应逐步收敛到本目录
- `src/operations/services` 只应继续承担兼容壳与少量尚未迁移的遗留实现，不再是首选落点

---

## 本目录负责什么

### 负责

- 运维治理域 service
- 运行编排相关 service
- execution / schedule / reconciliation / snapshot / probe / report / seed 等明显属于 ops 域的服务实现
- 为 `src/ops/api`、`src/ops/queries`、`src/ops/runtime` 提供服务层承接

### 不负责

- foundation 底层数据同步基础设施
- biz 域业务查询与对上 API 语义
- platform / app 壳职责（web、auth、dependencies、exceptions）
- 跨域分析类、高歧义 service 在未完成归属判定前的兜底承接

---

## 当前命名与角色规则

本目录当前存在三类文件，必须分清角色：

### 1. 主实现（core implementation）

这类文件是真正的迁入承接位，负责历史 `operations/services/*` 的主实现逻辑。

当前典型命名包括：
- `operations_execution_service.py`
- `operations_schedule_service.py`
- `operations_execution_reconciliation_service.py`
- `operations_sync_job_state_reconciliation_service.py`
- `operations_dataset_status_snapshot_service.py`
- `operations_probe_runtime_service.py`
- `operations_daily_health_report_service.py`
- `operations_dataset_pipeline_mode_seed_service.py`

规则：
- 历史从 `operations/services` 迁来的主实现，优先采用 `operations_<name>_service.py` 命名，直到后续统一命名收口
- 这类文件可以承载真实实现

### 2. façade / 命令层薄封装

当前典型包括：
- `execution_service.py`
- `schedule_service.py`
- `runtime_service.py`
- `probe_service.py`
- `std_rule_service.py`
- `resolution_release_service.py`

规则：
- façade 文件应保持薄
- 不要把新的复杂业务逻辑继续堆入 façade
- façade 主要做编排、入口适配、对外稳定接口维持

### 3. 辅助适配

例如：
- `job_execution_sync_context.py`

规则：
- 仅承接 contract / adapter / 注入侧的适配职责
- 不要把高层业务逻辑混入 adapter

---

## 新代码放置规则

### 可以直接放入本目录的新内容

仅当一个 service 明显满足以下条件时，才可直接新增到本目录：
- 明显属于 ops 治理域
- 不依赖 biz 域查询/业务语义
- 不应归属 foundation 底层同步基础设施
- 已在 `docs/architecture/ops-consolidation-plan.md` 中被判定为应并入 ops

### 新 service 前必须先做的检查

在新增或迁移 service 前，先检查：
1. `docs/architecture/ops-consolidation-plan.md`
2. 当前是否已有同名/近义 service
3. 该能力是否其实更适合留在 foundation / biz / app
4. 是否应该先更新归并计划，而不是直接写代码

---

## 当前阶段禁止事项

- 不要把 platform / app 壳逻辑写进本目录
- 不要把 foundation contract / kernel / db / utils 逻辑写进本目录
- 不要把明显属于 biz 的 service 塞进本目录
- 不要在本目录中继续制造“双命名中心”并长期共存而不说明角色
- 不要在没有归并计划更新的情况下，随意把高歧义 legacy service 搬进来

---

## 与 src/operations/services 的关系

当前规则：
- `src/ops/services` 是主承接位
- `src/operations/services` 是 legacy 兼容与遗留区

因此：
- 新的长期实现不要再优先写到 `src/operations/services`
- 从 `src/operations/services` 迁入后，可保留 deprecated shim
- shim 必须保持薄，不得继续生长业务逻辑

---

## 完成任务时的输出要求

每次涉及 `src/ops/services` 的任务完成后，必须说明：

1. 本次改动属于哪一类：主实现 / façade / 辅助适配
2. 是否替代或吸收了 `src/operations/services` 的旧实现
3. 是否新增了 deprecated 兼容壳
4. 是否影响 runtime / api / query 的调用链
5. 当前命名中谁是主实现、谁是 façade
6. 本次是否更新了 `docs/architecture/ops-consolidation-plan.md`

---

## 当前优先级

在当前阶段，本目录优先级排序如下：

1. 继续承接已明确归属为 ops 的 legacy services
2. 保持 façade 薄、主实现清晰
3. 逐步减少 `src/operations/services` 的真实实现数量
4. 避免在本目录引入新的高歧义跨域逻辑
