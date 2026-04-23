# 子系统依赖矩阵（收敛后现行版）

## 文档目的

定义后端单仓当前生效的依赖方向与护栏口径，作为评审与重构收尾阶段的统一基线。

本矩阵对应目标结构：

```text
src/
  foundation/
  ops/
  biz/
  app/
```

其中：

1. `foundation` / `ops` / `biz` 是三个业务子系统。
2. `app` 是组合根（装配层），不是业务子系统。
3. `platform` / `operations` 是 legacy 目录，仅用于兼容与清理，不承接新主实现。

---

## 1. 目标依赖方向

### 1.1 允许依赖

1. `foundation -> foundation`
2. `ops -> foundation, ops`
3. `biz -> foundation, biz`
4. `app -> foundation, ops, biz, app`
5. `tests -> all`（仅用于测试，不得成为反向依赖借口）

### 1.2 禁止依赖

1. `foundation -> ops | operations | biz | platform | app`
2. `ops -> biz`
3. `operations -> biz`
4. `biz -> ops | operations`

---

## 2. 当前状态（2026-04-23）

1. 依赖矩阵白名单已清零（按文件粒度历史例外已收口）。
2. `tests/architecture/test_subsystem_dependency_matrix.py` 当前为“零白名单”防回退模式。
3. `platform` 与 `operations` 的回流由专门护栏阻断：
   - `tests/architecture/test_platform_legacy_guardrails.py`
   - `tests/architecture/test_operations_legacy_guardrails.py`

说明：

1. 旧文档中关于 `src/foundation/models/all_models.py`、`src/foundation/services/sync/base_sync_service.py` 的历史白名单描述已过时，不再适用当前代码状态。
2. 若未来出现例外，必须按“单文件 + 原因 + 允许模块”形式显式登记，并附清理计划。

---

## 3. 护栏测试清单（现行）

1. `tests/architecture/test_subsystem_dependency_matrix.py`
2. `tests/architecture/test_platform_legacy_guardrails.py`
3. `tests/architecture/test_operations_legacy_guardrails.py`

执行建议：

1. 涉及目录边界改动时，至少先跑以上 3 个测试。
2. 涉及同步 V2 路径收口时，再补跑 `tests/architecture/test_sync_v2_registry_guardrails.py`。

---

## 4. 变更流程（强约束）

1. 先做引用/导入审计，再动代码。
2. 每轮只做一个边界目标，不顺手扩范围。
3. 删除兼容层前必须确认引用清零并通过最小回归。
4. 若边界归属不清，先补架构文档判定，再编码实现。

---

## 5. 争议归属判定（简版）

1. `foundation`：底层同步、存储、契约、通用基础能力。
2. `ops`：运维治理、调度执行、探测、状态投影、运行时编排。
3. `biz`：对上业务 API/查询/聚合服务。
4. `app`：应用创建、路由聚合、依赖装配、认证壳、运行入口。

