# AGENTS.md — 仓库根入口规则（第一版）

## 适用范围
本文件适用于当前仓库根目录及其所有子目录。

若更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前工作目录的 `AGENTS.md` 为准。

---

## 当前仓库所处阶段
本仓库正在进行“后端单仓子系统收敛”的渐进式重构。

当前目标结构为：

```text
src/
  foundation/
  ops/
  biz/
  app/
```

其中：
- `foundation` / `ops` / `biz` 是三个业务子系统
- `app` 是很薄的应用壳（composition root），不是第四个业务子系统

当前重构策略不是一次性大搬家，而是：
1. 先冻结边界与依赖方向
2. 先阻止新增错误依赖
3. 再逐步迁移主实现
4. 最后收兼容壳与旧路径

---

## 开始任何任务前必须先读
在动代码之前，先阅读并理解以下文件：

1. `docs/architecture/subsystem-boundary-plan.md`
2. `docs/architecture/dependency-matrix.md`
3. `docs/architecture/ops-consolidation-plan.md`（若任务与 operations / ops 收敛有关）
4. `src/AGENTS.md`
5. 当前目标目录及其上级目录中更具体的 `AGENTS.md`

如果任务发生在：
- `src/platform/**` 下，必须先读 `src/platform/AGENTS.md`
- `src/operations/**` 下，必须先读 `src/operations/AGENTS.md`
- `src/ops/**` 下，必须先读 `src/ops/AGENTS.md`

不要跳过这些规则文件后直接开始改代码。

---

## 当前硬约束
### 1. 不要重新引入 foundation 的反向依赖
禁止让 `src/foundation/**` 重新直接依赖：
- `src/ops`
- `src/operations`
- `src/platform`
- `src/biz`
- `src/app`

当前 foundation 第一阶段边界收敛已完成。不要为了图省事重新把上层语义塞回 foundation。

### 2. 当前优先级高于 platform 重构的是 operations -> ops 收敛
当前主线优先处理：
- `operations/runtime` -> `ops/runtime`
- `operations/specs` -> `ops/specs`
- `operations/services` -> `ops/services`

除非任务明确要求，否则不要跳去大规模拆 `platform`。

### 3. 不做 big bang 式重构
禁止在一次任务中同时做：
- 大规模目录迁移
- 业务逻辑重写
- API / schema / query 全量改造
- platform 大拆分
- CLI 体系重做

每次只完成一个明确阶段目标，并保留兼容性。

### 4. 兼容壳可以保留，但必须很薄
旧路径兼容壳允许存在，但必须：
- 只做转发
- 标注 deprecated
- 不再承接新逻辑

不要把兼容壳继续发展成新的主实现。

### 5. No source, no code
以下内容如果没有明确依据，禁止直接猜测并编码：
- 子系统归属
- 依赖方向
- 接口字段
- 数据库字段
- 业务状态机
- 迁移顺序
- 哪个文件应作为主实现、哪个应作为 façade/兼容层

若信息不足，先输出：
- 已确认信息
- 缺失信息
- 风险点
- 建议方案

---

## 目录级导航
### 后端
- `src/foundation/**`：数据基座与共享基础能力
- `src/ops/**`：运维治理、runtime、specs、ops services 的主承接目录
- `src/biz/**`：对上业务 API / query / service / schema
- `src/app/**`：很薄的 app 组合根（当前只允许小步增长）
- `src/operations/**`：历史过渡目录，优先迁出，不再作为新长期逻辑首选落点
- `src/platform/**`：历史过渡目录，优先收缩，不再新增长期业务逻辑

### 前端
- `frontend/**` 当前结构相对稳定
- 若任务仅涉及前端页面/交互，不要顺手触碰后端重构主线
- 若后续新增 `frontend/AGENTS.md`，进入前端目录工作前必须先读

---

## 当前阶段的推荐工作方式
### 小任务
可以直接做，但必须：
- 说明依据
- 控制范围
- 给出最小验证结果

### 中任务
先给出：
- 目标理解
- 影响文件
- 依赖方向是否变化
- 验证方案
再动代码。

### 大任务 / 迁移任务
先更新或新增计划文档，再实施。尤其是：
- operations -> ops 收敛
- platform 拆分
- foundation contract / adapter 抽取
- app 壳扩展

---

## 提交与推送规则
- 可以创建本地 checkpoint / commit
- 只有在用户明确要求时，才允许执行 push
- 若用户明确要求推送，目标分支为：`dev-interface`

在进行较大改动前，优先建议先做 Git checkpoint。

---

## 完成任务后的输出要求
每次完成任务后，至少说明：
1. 本次目标
2. 依据来源
3. 改动文件
4. 是否影响子系统边界
5. 是否影响依赖矩阵
6. 验证结果
7. 风险与待确认项

如果是迁移任务，还要额外说明：
- 谁是新主实现
- 哪些旧路径保留为兼容壳
- 哪些部分明确暂缓处理

---

## 当前最重要的行为原则
1. 先读规则，再改代码
2. 先收敛主实现，再清兼容壳
3. 先处理低歧义项，再处理高歧义项
4. 先稳住 ops 收敛主线，再考虑 platform 大拆分
5. 不要重新污染 foundation
