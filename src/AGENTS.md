# AGENTS.md — `src/` 总规则（稳定期）

## 适用范围

本文件适用于 `src/` 目录及所有子目录。若存在更近目录规则，以更近 `AGENTS.md` 为准。

---

## 当前事实

1. 主体结构已收敛为 `foundation / ops / biz / app`。
2. `platform` 与 `operations` 已降级为 legacy 目录，只允许最小清理动作。
3. 新主实现必须直接落在 `foundation`、`ops`、`biz`、`app` 对应目录。

---

## 必守边界

1. `foundation` 不得依赖 `ops` / `operations` / `biz` / `platform` / `app`。
2. `ops` 不得依赖 `biz`。
3. `biz` 不得依赖 `ops` / `operations`。
4. 不得把主实现写回 `src/platform/**` 或 `src/operations/**`。

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

- 运维/运行时：`src/ops/**`
- 业务 API/查询：`src/biz/**`
- 应用壳装配：`src/app/**`
- 底层数据基座：`src/foundation/**`

---

## 任务输出要求

每次改动后需给出：

1. 本轮目标与选择原因
2. 审计结果
3. 改动文件
4. 验证结果
5. 剩余阻塞与下一步建议
