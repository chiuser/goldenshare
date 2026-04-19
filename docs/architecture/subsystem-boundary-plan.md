# 子系统边界基线（收敛后版本）

## 文档目的

本文件定义当前仓库的**稳定边界**，作为后续开发和评审的统一基线。  
本版本已去除历史迁移步骤描述，避免与现状不一致。

---

## 当前目标结构（已达成）

```text
src/
  foundation/   # 数据基座 + contracts + 同步链路
  ops/          # 运行时编排 + 运维治理能力
  biz/          # 对上业务 API/Query/Service/Schema
  app/          # 组合根（web/api/auth/models/schemas 装配）
  platform/     # legacy 占位目录（冻结）
  operations/   # legacy 占位目录（冻结）
```

---

## 四层职责

### foundation

负责：

1. 数据源接入、同步、落库、基础 DAO/模型
2. kernel/contracts/shared primitives
3. 与上层无关的基础能力

不负责：

1. 运维 API
2. 业务 API
3. 应用入口装配

### ops

负责：

1. runtime（scheduler/worker/dispatcher）
2. specs（job/workflow/freshness）
3. 运维 API/Query/Schema/Service/Model

不负责：

1. 对上业务语义
2. 应用壳装配

### biz

负责：

1. 对上业务 API
2. 业务查询与聚合服务
3. 业务域 schema

不负责：

1. 调度/执行治理
2. 应用壳装配

### app

负责：

1. Web 应用创建与运行入口
2. Router 聚合
3. Auth wiring / DI wiring / 异常处理装配
4. App 层模型与通用 schema 接线

不负责：

1. Biz 核心业务规则
2. Ops 治理规则
3. Foundation 底层同步规则

---

## 依赖方向（硬约束）

1. `foundation` 不得依赖 `ops` / `operations` / `biz` / `platform` / `app`
2. `ops` 不得依赖 `biz`
3. `biz` 不得依赖 `ops` / `operations`
4. `app` 可装配 `biz` / `ops` / `foundation`，但不反向被下层依赖
5. 不得把主实现回流到 `platform` 或 `operations`

对应测试护栏：

1. `tests/architecture/test_subsystem_dependency_matrix.py`
2. `tests/architecture/test_platform_legacy_guardrails.py`
3. `tests/architecture/test_operations_legacy_guardrails.py`

---

## legacy 目录规则

### src/platform

1. 仅保留 legacy 占位与规则文档
2. 不承接任何 Python 主实现
3. 运行代码/测试代码不得导入 `src.platform.*`

### src/operations

1. 仅保留 legacy 占位与规则文档
2. `operations/services` 不得新增 Python 文件
3. 运行代码/测试代码不得回流 `src.operations.*` 旧路径

---

## 变更流程（统一执行）

1. 先审计影响面（代码/测试/脚本/文档）
2. 每轮只做一个目标
3. 删除 compat 前先确认引用清零
4. 跑最小回归并记录结果
5. 同步更新架构文档与对应 AGENTS

---

## 当前剩余工作（可选收尾）

1. 文档历史章节继续精简（保持“只写现状”）
2. 是否删除 legacy 目录空包骨架（需先做外部入口影响审计）

> 注：该清单是治理类收尾，不影响当前功能可用性。
