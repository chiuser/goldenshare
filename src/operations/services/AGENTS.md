# AGENTS.md — src/operations/services 过渡兼容目录规则

## 适用范围

本文件适用于 `src/operations/services/` 目录及其所有子目录。

---

## 当前阶段定义

`src/operations/services` 当前是**过渡兼容目录**，不是长期主承接目录。

当前仓库已经开始将低歧义、明显属于 ops 域的 service 逐步迁入 `src/ops/services`。因此：
- 本目录中的已迁移文件应只保留 deprecated shim
- 尚未迁移的遗留实现应等待归属判定后，再决定迁往 `ops`、保留在 `foundation`、或继续暂缓

本目录不应继续无约束增长。

---

## 本目录允许做什么

### 允许

- 为已迁移 service 保留 deprecated shim
- 修复 shim 的转发问题
- 为尚未迁移、仍在本目录中的 legacy service 做最小必要 bugfix
- 在迁移过程中加入明确的 deprecated 注释与迁移说明
- 在完成归并计划更新后，将明确归属的 legacy service 迁出本目录

### 不允许

- 在本目录新增新的长期 service 实现
- 把新的 ops 主实现继续写在本目录
- 把新的业务分析逻辑、platform 逻辑、foundation 逻辑写在本目录
- 在没有更新归并计划的情况下，自行决定把高歧义 service 硬迁到 `ops`

---

## 目录角色划分

### 1. 已迁移文件

例如当前已迁移并保留 shim 的 service：
- `execution_service.py`
- `schedule_service.py`
- `schedule_planner.py`
- `schedule_probe_binding_service.py`
- `execution_reconciliation_service.py`
- `sync_job_state_reconciliation_service.py`
- `dataset_status_snapshot_service.py`
- `probe_runtime_service.py`
- `daily_health_report_service.py`
- `dataset_pipeline_mode_seed_service.py`

规则：
- 这些文件应只保留最薄的 deprecated shim
- 不要在 shim 中继续加入新逻辑

### 2. 尚未迁移的 legacy 实现

当前仍在本目录作为主实现保留的文件，必须先完成归属判定，再决定是否迁移。

规则：
- 不要直接把这些文件当作“还可以继续开发的常规目录”
- 任何涉及这些文件的重构任务，先看 `docs/architecture/ops-consolidation-plan.md`

---

## 处理剩余 legacy service 的规则

对于仍未迁移的 service，必须先判断它属于哪一类：

- 明显属于 ops 治理域，可进入后续批次迁移
- 更偏 foundation 数据运行/同步编排，不适合直接迁到 ops
- 更偏 biz 业务分析或跨域语义，应继续暂缓
- 需要专项迁移，不适合在常规批次中处理

在未完成判定前，不要直接修改归属。

---

## 当前阶段禁止事项

- 不要继续让 `src/operations/services` 成为新逻辑首选落点
- 不要把 shim 改成厚实现
- 不要把高歧义 service 在没有计划文档更新的情况下迁到 `ops`
- 不要借“修一个 bug”顺手做大范围 service 重写
- 不要碰 platform

---

## 与 src/ops/services 的关系

规则固定如下：
- `src/ops/services` 是主承接目录
- `src/operations/services` 是 legacy 兼容目录

因此：
- 新的长期实现优先进入 `src/ops/services`
- 本目录中已迁移文件只保留兼容壳
- 若需要迁移新一批 service，先更新 `docs/architecture/ops-consolidation-plan.md`

---

## 完成任务时的输出要求

每次涉及 `src/operations/services` 的任务完成后，必须说明：

1. 本次改动针对的是 shim 还是 legacy 主实现
2. 若是 shim，是否仍保持薄转发
3. 若是 legacy 主实现，是否已经在文档中完成归属判定
4. 是否新增了迁移目标或更新了归并计划
5. 当前本目录还剩哪些真正未迁移的 service

---

## 当前优先级

在当前阶段，本目录优先级排序如下：

1. 保持已迁移文件的 shim 足够薄
2. 继续减少本目录中的真实实现数量
3. 对剩余高歧义 service 先做归属判定，再做迁移
4. 不允许本目录重新长成第二个主承接目录
