# 子系统边界基线（收敛后版本）

文档校准：2026-09-08。仅校准目录、现状与验证说明，不实施依赖迁移。

## 文档目的

本文件定义当前仓库的**稳定边界**，作为后续开发和评审的统一基线。  
本文维护目录与职责；目标依赖方向、现存差距和测试覆盖统一见[依赖矩阵](/Users/congming/github/goldenshare/docs/architecture/dependency-matrix.md)。目录结构已形成，不代表全部依赖目标已实现。

---

## 当前主体结构与辅助目录

```text
src/
  foundation/   # 数据基座 + contracts + 同步链路
  ops/          # 运行时编排 + 运维治理能力
  biz/          # 对上业务 API/Query/Service/Schema
  app/          # 组合根（web/api/auth/models/schemas 装配）
  platform/     # legacy 占位目录（冻结）
  operations/   # legacy 占位目录（冻结）
  cli.py        # CLI 入口
  cli_parts/    # CLI 实现拆分，由 cli.py 调用
  scripts/      # Python 工具入口，不是仓库根 scripts/
  shared/       # 仅包说明骨架，无共享能力主实现
qtf/            # 独立量化产品域，由 app 装配
scripts/        # 仓库工程脚本，包括部署、发版与自检入口
```

`foundation / ops / biz` 是三个业务子系统，`app` 是组合根；入口工具和占位目录不构成新的业务分层。QTF 位于仓库根，不属于 `src` 四层，只允许依赖自身与 `src.foundation`。

---

## 主 CLI / Web 入口

1. CLI：`goldenshare = src.cli:app`
2. Web：`goldenshare-web = src.app.web.run:main`
3. systemd 参考：`scripts/goldenshare-web.service` 使用 `python -m src.app.web.run`

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
2. 运维动作与工作流定义（`src/ops/action_catalog.py`），以及基于数据集事实的运行与 freshness 观测
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

## QTF 职责与依赖边界

QTF 承担量化研究、计算、验证与发布，由 `src/app` 装配；不得让 `foundation / ops / biz / platform / operations` 反向依赖 QTF。

完整允许/禁止方向和测试清单统一见[依赖矩阵](/Users/congming/github/goldenshare/docs/architecture/dependency-matrix.md)，不在本文维护第二份矩阵。App 不被下层反向依赖仍是架构目标，但当前 Ops/Biz API 对 App 认证和数据库依赖的导入尚存在，见矩阵 §2.1；文档校准不将其升级为允许模式，也不授权本轮改造。

---

## legacy 目录规则

### src/platform

1. 仅保留 legacy 占位与规则文档
2. 当前无 Python 源文件，包括 `__init__.py`；护栏禁止重新出现
3. 运行代码/测试代码不得导入 `src.platform.*`

### src/operations

1. 仅保留 legacy 占位与规则文档
2. 当前仅保留根目录及 `services/` 下的 AGENTS 说明，无 Python 源文件；护栏禁止恢复旧包
3. 运行代码/测试代码不得回流 `src.operations.*` 旧路径

---

## 变更流程（统一执行）

1. 先审计影响面（代码/测试/脚本/文档）
2. 每轮只做一个目标
3. 删除 compat 前先确认引用清零
4. 跑最小回归并记录结果
5. 同步更新架构文档与对应 AGENTS

---

## 维护边界

legacy Python 空包骨架已不存在，不再将“是否删除空包”列为待办。保留规则文档和防回退护栏；不据此删除目录、物理数据或本机 ignored 环境。历史材料按文档治理规则标注，不把旧执行步骤重新列为当前任务。

---

## 最小验证基线

按[Foundation 规范 §7](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md#7-按改动类型选择验收)区分文档、代码与获准部署验证；架构护栏范围见依赖矩阵 §3。

`bash scripts/deploy-systemd.sh --help` 当前只打印帮助，不进入实际部署；它只能证明帮助入口可用，不能证明构建、迁移、服务启动或发布成功。文档修改不要求运行该脚本或访问健康接口。
