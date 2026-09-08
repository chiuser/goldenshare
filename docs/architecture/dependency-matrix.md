# 子系统依赖矩阵（收敛后现行版）

文档校准：2026-09-08。目标规则不放宽；当前实现与护栏覆盖单列说明。

## 文档目的

定义后端单仓的目标依赖方向、当前实现差距与护栏口径，作为评审基线；目标矩阵不能直接当作所有代码已遵守的证明。

本矩阵对应目标结构：

```text
src/
  foundation/
  ops/
  biz/
  app/
qtf/
```

其中：

1. `foundation` / `ops` / `biz` 是三个业务子系统。
2. `app` 是组合根（装配层），不是业务子系统。
3. `qtf` 是仓库根目录的独立量化产品域，由 `app` 组合装配。
4. `platform` / `operations` 是 legacy 说明目录，已无 Python 实现，不提供可复用兼容代码。

---

## 1. 目标依赖方向

### 1.1 允许依赖

1. `foundation -> foundation`
2. `ops -> foundation, ops`
3. `biz -> foundation, biz`
4. `qtf -> foundation, qtf`
5. `app -> foundation, ops, biz, qtf, app`
6. 测试可覆盖现行模块，但仍须遵守 legacy 导入禁令和各自隔离/执行规则；不能以测试为由恢复已退役包或形成运行时代码的反向依赖。

### 1.2 禁止依赖

1. `foundation -> ops | operations | biz | platform | app`
2. `ops -> biz`
3. `operations -> biz`
4. `biz -> ops | operations`
5. `foundation | ops | biz | platform | operations -> qtf`
6. `qtf -> ops | operations | biz | platform | app`，以及除 `src.foundation` 外的其他 `src` 根模块

---

## 2. 当前状态（2026-09-08 代码核对）

1. 依赖矩阵白名单已清零（按文件粒度历史例外已收口）。
2. `tests/architecture/test_subsystem_dependency_matrix.py` 当前为“零白名单”防回退模式。
3. `platform` 与 `operations` 的回流由专门护栏阻断：
   - `tests/architecture/test_platform_legacy_guardrails.py`
   - `tests/architecture/test_operations_legacy_guardrails.py`
4. 2026-08-22 起，顶层 `qtf` 产品域及其单向依赖由 `tests/architecture/test_subsystem_dependency_matrix.py` 的零白名单规则保护。

说明：

1. 旧文档中关于 `src/foundation/models/all_models.py`、`src/foundation/services/sync/base_sync_service.py` 的历史白名单描述已过时，不再适用当前代码状态。
2. 若未来出现例外，必须按“单文件 + 原因 + 允许模块”形式显式登记，并附清理计划。

### 2.1 目标尚未完全实现的边界

App 不被下层反向依赖仍是架构目标。当前 [Ops dataset cards API](/Users/congming/github/goldenshare/src/ops/api/dataset_cards.py) 和 [Biz market API](/Users/congming/github/goldenshare/src/biz/api/market.py) 等入口仍导入 `src.app.auth`、`src.app.dependencies` 等能力；这是现存依赖，不是本文新增的允许项。是否迁移、如何迁移需另行设计与批准，本轮不改代码。

“零白名单”只表示当前测试配置没有登记例外，不表示测试穷尽了目标矩阵。当前 [DependencyRule 配置](/Users/congming/github/goldenshare/tests/architecture/test_subsystem_dependency_matrix.py) 对 Ops 禁止 `biz/qtf`，对 Biz 禁止 `ops/operations/qtf`，并未禁止这两者导入 App。护栏通过不能据此证明 App 反向依赖已清零，也不能作为新增这类依赖的依据。

---

## 3. 护栏测试清单（现行）

1. `tests/architecture/test_subsystem_dependency_matrix.py`
2. `tests/architecture/test_platform_legacy_guardrails.py`
3. `tests/architecture/test_operations_legacy_guardrails.py`

执行建议：

1. 涉及目录边界代码改动时，至少跑以上 3 个测试；在仓库根使用现有 `.venv/bin/python3 -B -m pytest -q <测试文件>`，先确认测试无正式资源副作用，不自动安装依赖。
2. 涉及数据维护主链代码改动时，再补跑 `tests/architecture/test_dataset_runtime_registry_guardrails.py` 与 `tests/architecture/test_dataset_codebook_guardrails.py`。
3. 仅文档修改以文档完整性、差异和引用检查为默认验证；需要核实护栏现状时可定向运行上述本地测试。服务、数据库及部署验证按[Foundation 规范 §7](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md#7-按改动类型选择验收)另行区分，不与静态测试混用。

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
5. `qtf`：量化研究、计算、验证与发布合同；只依赖 Foundation，并由 App 装配。
