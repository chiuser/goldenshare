# AGENTS.md — `src/` 总规则（稳定期）

## 适用范围

本文件适用于 `src/` 目录及所有子目录。若存在更近目录规则，以更近 `AGENTS.md` 为准。

---

## 当前事实

1. 主体结构已收敛为 `foundation / ops / biz / app`。
2. `platform` 与 `operations` 已降级为 legacy 目录，只允许最小清理动作。
3. 新主实现必须直接落在 `foundation`、`ops`、`biz`、`app` 对应目录。
4. `src/foundation/services/sync`（Sync V1）已移除，不得再新增或回流相关实现。
5. 数据集事实源收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition`。
6. 数据维护请求到执行计划的长期模型收敛到 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan`。
7. 运维任务运行、任务详情与问题诊断收敛到 `src/ops` TaskRun 主链。

---

## 必守边界

1. `foundation` 不得依赖 `ops` / `operations` / `biz` / `platform` / `app`。
2. `ops` 不得依赖 `biz`。
3. `biz` 不得依赖 `ops` / `operations`。
4. 不得把主实现写回 `src/platform/**` 或 `src/operations/**`。
5. 不得新增 `src.foundation.services.sync.*` 导入路径；数据维护执行主链只允许落在 `src/foundation/ingestion/**`。
6. 不得把 `sync_daily / backfill_* / sync_history` 重新作为用户可见或 API 主执行模型。
7. 不得恢复 `JobExecution*`、`sync_run_log` 或 `/api/v1/ops/executions*` 作为任务详情事实源。

边界违规由以下测试守护：

- `tests/architecture/test_subsystem_dependency_matrix.py`
- `tests/architecture/test_platform_legacy_guardrails.py`
- `tests/architecture/test_operations_legacy_guardrails.py`

---

## 工作方式

1. 先审计影响面，再改代码。
2. 每轮只做一个目标，不顺手扩范围。
3. 删除 compat 前必须先确认引用清零。
4. 高歧义项先补文档判定，再实施。

---

## 目录流向

- 运维/运行时：`src/ops/**`（TaskRun、scheduler/worker、ops API/query/service）
- 业务 API/查询：`src/biz/**`
- 应用壳装配：`src/app/**`
- 底层数据基座：`src/foundation/**`（DatasetDefinition、DatasetExecutionPlan、IngestionExecutor 与数据模型）

---

## 任务输出要求

每次改动后需给出：

1. 本轮目标与选择原因
2. 审计结果
3. 改动文件
4. 验证结果
5. 剩余阻塞与下一步建议
