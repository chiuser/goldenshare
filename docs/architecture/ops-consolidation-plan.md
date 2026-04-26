# ops 收敛基线（收敛后版本）

## 文档目的

记录 `operations -> ops` 收敛后的当前真实状态，作为后续稳定化与防回退基线。

> 2026-04-26 更新：运维动作与工作流目录已从旧规格目录继续收口到 `src/ops/action_catalog.py`。当前文档中的 `ops` 收敛结论仍成立，但不再把旧规格目录作为主实现位置。

---

## 收敛结论（已完成）

1. runtime 主实现已收敛到 `src/ops/runtime/*`
2. 运维动作目录与工作流定义主实现已收敛到 `src/ops/action_catalog.py`
3. 常规 services 主实现已收敛到 `src/ops/services/*`
4. `history_backfill` 已收敛到 `src/ops/services/operations_history_backfill_service.py`
5. `market_mood_walkforward_validation_service` 已收敛到 `src/biz/services/market_mood_walkforward_validation_service.py`

---

## 当前目录状态

### 主目录

`src/ops` 为唯一 ops 主实现目录，承接：

1. runtime
2. action catalog / workflow definition
3. ops api/query/schema/service/model

### legacy 目录

`src/operations` 已冻结，仅保留：

1. `src/operations/AGENTS.md`
2. `src/operations/services/AGENTS.md`

不再保留 `operations/services/*.py`、`operations/runtime/*.py`、`operations/specs/*.py` 主实现。

---

## 护栏

1. `tests/architecture/test_operations_legacy_guardrails.py`
2. `tests/architecture/test_subsystem_dependency_matrix.py`

护栏目标：

1. 阻止 `src.operations.*` 旧路径回流
2. 阻止 `operations/services` 重新长出 Python 实现
3. 阻止子系统依赖方向回退

---

## 稳定期规则

1. 新运维能力只能进入 `src/ops/**`
2. 不得将主实现写回 `src/operations/**`
3. facade 允许保留，但必须薄、可审计、无隐藏业务逻辑
4. 大范围重命名或结构调整需先审计影响面再执行

---

## 剩余收尾项（可选）

1. 文档层历史路径引用继续精简
2. 若确认无外部依赖，可进一步评估 `src/operations` 空包骨架是否删除

> 以上为可选治理项，不影响当前运行链路。
