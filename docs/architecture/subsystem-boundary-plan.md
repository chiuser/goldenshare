# 子系统边界与渐进式迁移计划

## 文档目的

本文档用于冻结后端单仓的目标结构、子系统边界、目录归属与渐进式迁移顺序。

当前仓库已经在逻辑上形成了三类能力，但在物理目录与依赖方向上仍存在明显混杂：

- `foundation`：数据基座核心
- `operations + ops`：运行时编排与运维治理能力分散在两处
- `biz + platform`：对上业务 API 与应用壳能力混放

本计划的目标不是一次性大搬家，而是：

1. 先统一目标结构
2. 先冻结过渡期规则
3. 先阻止新增错误依赖
4. 再逐步做职责回收、依赖解耦与物理迁移

---

## 目标结构

目标结构为：

```text
src/
  foundation/   # 数据基座 + kernel/contracts/shared primitives
  ops/          # 运行时编排 + 运维 API/Query/Service/Schema
  biz/          # 对上业务 API/Query/Service/Schema
  app/          # 很薄的应用壳：web/bootstrap/di/auth wiring/error handlers/model registry
```

说明：

- `foundation` / `ops` / `biz` 是三个业务子系统
- `app` 不是第四个业务子系统，而是组合根（composition root）
- `app` 只负责组装，不承载核心业务规则
- `app` 不应以 big bang 方式一次性创建并整体替换 `platform`
- 迁移策略应是：先拆清 `platform` 中的 app 壳职责与业务职责，再逐步抽出 `app`

---

## 子系统职责定义

### foundation

负责：

- 外部数据源连接器
- DAO / repository / 落库模型
- 同步链路
- serving 构建
- resolution 策略
- db/session/settings/contracts/types/errors 等基础设施
- 与上层无关的共享基础能力

不负责：

- 运维 API
- 对上业务 API
- 应用启动装配
- 鉴权接线
- 全局 router 聚合

---

### ops

负责：

- scheduler / worker / dispatcher 等运行时编排
- job / workflow / dataset freshness 等 spec
- 运维域 API / Query / Service / Schema
- 任务、执行、探测、状态、审查中心等运维治理能力

不负责：

- 对上业务 API
- 业务查询语义
- foundation 的底层建模与通用基础设施
- 应用壳装配

---

### biz

负责：

- 对上业务 API
- 业务查询服务
- 面向上层消费的 schema
- 业务域的聚合查询、接口封装与展示友好输出

不负责：

- 运维执行治理
- scheduler / worker / runtime 编排
- foundation 底层同步基础设施
- 应用壳装配

---

### app

负责：

- FastAPI app 创建
- router 聚合与挂载
- middleware / exception handler 注册
- auth wiring
- dependency wiring / composition root
- model registry / metadata 装载
- 启动入口与 web 运行

不负责：

- 核心业务逻辑
- 核心同步逻辑
- 运维业务规则
- 对上业务查询规则

---

## 当前目录到未来归属映射

### 现有目录映射

- `src/foundation` -> `foundation`
- `src/operations/runtime` -> `ops/runtime`
- `src/operations/services` -> `ops/services`
- `src/operations/specs` -> `ops/specs`
- `src/operations/dataset_status_projection.py` -> `ops`，需专项判断最终归属（更可能属于运行时/运维投影层，而不是继续留在旧目录根）
- `src/ops/api` -> `ops/api`
- `src/ops/queries` -> `ops/queries`
- `src/ops/schemas` -> `ops/schemas`
- `src/ops/services` -> `ops/services`
- `src/ops/models/ops` -> `ops/models`
- `src/biz` -> `biz`
- `src/platform/web` -> `app/web`
- `src/platform/auth` -> `app/auth`
- `src/platform/dependencies` -> `app/dependencies` 或 `app/di`
- `src/platform/exceptions` -> `app/exceptions`
- `src/platform/api` -> `biz/api` 或 `ops/api` 或少量聚合逻辑进 `app`
- `src/platform/api/router.py` -> `app` 聚合层，属于当前 HTTP 入口聚合链路的一部分，应作为“最后迁移”的对象，不应和普通业务 API 一起提前搬动
- `src/platform/api/v1/router.py` -> `app` 聚合层，负责聚合 platform / ops / biz 路由，应作为“最后迁移”的对象
- `src/platform/queries` -> `biz/queries` 或 `ops/queries`
- `src/platform/schemas` -> `biz/schemas` 或 `ops/schemas`
- `src/platform/services` -> `biz/services` 或 `ops/services`
- `src/platform/models` -> `app/models` / `biz/models` / `ops/models`，需细分
- `src/shared` -> `foundation/kernel/contracts` / `foundation/kernel/types` / `foundation/kernel/primitives`
- `src/db.py` -> `foundation/kernel/db/*`
- `src/utils.py` -> `foundation/kernel/utils/*`
- `src/cli.py` -> 暂留在 `src/cli.py`，内部调用逐步收敛

---

## 当前已知问题

### 1. foundation 存在反向依赖

已知样例：

- `src/foundation/models/all_models.py` 直接导入了 platform / ops 的大量模型
- `src/foundation/services/sync/base_sync_service.py` 直接依赖了 ops 的进度写回能力

这类依赖会破坏 foundation 作为最低层的稳定性，必须优先拆除。

---

### 2. operations 与 ops 语义重叠

当前已经形成“双中心”：

- `operations`：runtime / services / specs，且还存在目录根级的 `dataset_status_projection.py`
- `ops`：api / queries / schemas / services / models，且已有 `runtime` / `specs` skeleton

这意味着新逻辑若继续同时进入两处，后续迁移成本会持续上升。

---

### 3. platform 混装

`platform` 当前同时承载：

- web app 创建
- auth / dependencies / exception handling
- API / Query / Service / Schema
- 部分模型
- router 聚合链路

这导致 `platform` 既像应用壳，又像业务域，又像运维域入口，必须被消解，而不是简单重命名保留。

---

### 4. shared 未真正承接共享契约

当前共享能力仍大量挂在：

- `src/db.py`
- `src/utils.py`

`src/shared` 没有真正成为“共享契约层”，导致公共能力既难约束，又难归类。

---

## 过渡期规则

从本计划生效开始，执行以下规则：

### 目录级规则

1. `src/platform` 不再新增业务 API / Query / Service / Schema
2. `src/operations` 不再新增新的长期归属逻辑
   - 新 runtime / spec 优先进入 `src/ops/runtime` 与 `src/ops/specs`
   - 新运维 service 优先进入 `src/ops/services`
3. `src/db.py` 不再继续变厚
4. `src/utils.py` 不再新增新的“通用杂项方法”
5. 新的共享契约优先进入 `foundation/kernel/contracts`
6. 新的 web / auth / di / exception 装配优先朝未来 `app/` 目标收敛，但不得 big bang 搬迁
7. `platform/api/router.py` 与 `platform/api/v1/router.py` 属于当前应用聚合入口，默认最后迁移

---

### 实现级规则

1. 不做 big bang 式一次性大迁移
2. 每次任务只处理一个阶段目标
3. 不允许把“目录迁移 + 业务重写 + 架构优化”混在一个任务中
4. 复杂迁移先产出计划文档，再动代码
5. 对旧路径允许短期兼容壳，但必须明确标注 deprecated

---

## 渐进式迁移顺序

### 第 0 步：冻结目标与规则

产出：

- `docs/architecture/subsystem-boundary-plan.md`
- `docs/architecture/dependency-matrix.md`

本步不改业务逻辑。

---

### 第 1 步：放置过渡期 AGENTS

建议至少覆盖：

- `src/AGENTS.md`
- `src/platform/AGENTS.md`
- `src/operations/AGENTS.md`
- `src/ops/AGENTS.md`

目标是先约束新代码流向。

---

### 第 2 步：建立依赖矩阵测试

新增真正的子系统依赖测试，先阻止新增错误依赖，不要求一次性清零历史技术债。

---

### 第 3 步：优先拆 foundation 的反向依赖

优先级最高的两个点：

1. 将 `all_models.py` 的“全量模型装载”职责迁移到 `app/model_registry.py`
2. 将 `base_sync_service.py` 对 ops 的直接依赖改为 foundation contract + ops 实现

---

### 第 4 步：operations 并入 ops

采用“两段式”：

1. 先做归并清单，不做大迁移
2. 再先迁 runtime / specs，再迁 services
3. 将 `dataset_status_projection.py` 单独列入归属判断，不要在迁移时遗漏

---

### 第 5 步：拆 platform

第一批优先迁出明显属于 biz 的能力，例如 share 相关 API / query / schema / service。

platform 最终只保留 app 壳相关职责；其中 router 聚合链路属于最后迁移对象。

---

### 第 6 步：拆 db.py 与 utils.py

将共享基础设施正式收敛进 `foundation/kernel`。

---

### 第 7 步：收口

包括：

- 删兼容壳
- 收紧依赖矩阵测试
- 缩减 platform
- 缩减 operations
- 更新 CLI 内部归属
- 更新 README / docs / runbook

---

## 完成定义

当以下条件成立时，认为后端单仓完成第一阶段重构收敛：

1. foundation 不再依赖 ops / biz / app
2. operations 的新增逻辑已停止，并逐步并入 ops
3. platform 不再承载业务 API / query / service / schema
4. web / auth / di / exception / model registry 已形成薄 app 壳
5. db 与 utils 已从仓库级万能模块拆散
6. 有真正运行中的依赖矩阵测试
7. Codex 在仓库中已有明确 AGENTS 约束可遵守

---

## 非目标

本计划当前不追求：

- 一次性拆仓
- 一次性更换全部 import 路径
- 一次性重做 CLI 体系
- 一次性重做所有模型目录
- 一次性引入新的工程框架或额外基础设施

当前优先级是：先把方向锁住，先把错误增长停住，再逐步收敛。
