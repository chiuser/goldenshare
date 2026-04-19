# AGENTS.md — src 目录过渡期总规则

## 适用范围

本文件适用于 `src/` 目录及其所有子目录。

若更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前工作目录的 `AGENTS.md` 为准。

---

## 当前阶段说明

当前仓库正处于“单仓三子系统收敛”的过渡期。

目标结构为：

```text
src/
  foundation/
  ops/
  biz/
  app/
```

其中：

- `foundation` / `ops` / `biz` 是三个业务子系统
- `app` 是很薄的应用壳，不是第四个业务子系统
- `app` 不应通过一次性整体搬迁 `platform` 的方式出现，而应逐步从 `platform` 中抽离壳职责形成

当前历史目录：

- `src/operations`
- `src/platform`

仍然存在，但它们都是过渡目录，不应继续无约束增长。

当前基线补充（必须守住）：

1. `src/platform` 已进入 compat-only 阶段，不得新增主实现。
2. 运行代码与测试代码禁止重新依赖 `src.platform.*`。
3. 对上述基线的自动化护栏由以下测试负责：
   - `tests/architecture/test_platform_legacy_guardrails.py`
   - `tests/architecture/test_subsystem_dependency_matrix.py`

---

## 总规则

### 1. 先遵守边界，再写代码

收到任务后，先阅读：

1. `docs/architecture/subsystem-boundary-plan.md`
2. `docs/architecture/dependency-matrix.md`
3. 当前目录及上级目录中更具体的 `AGENTS.md`

不要在未确认目录归属和依赖方向前直接编码。

---

### 2. No source, no code

以下内容没有明确来源时，禁止直接猜测并编码：

- 子系统归属
- 模块依赖方向
- 接口字段
- 数据库字段
- 业务状态值
- 运维状态语义
- app 装配方式

信息不足时，先输出：

- 已确认信息
- 缺失信息
- 风险点
- 建议方案

不要把推测包装成“已经完成”。

---

### 3. 过渡期禁止事项

- 不要继续把新业务逻辑放进 `src/platform`
- 不要继续把新长期逻辑放进 `src/operations`
- 不要让 `foundation` 依赖 `ops` / `biz` / `platform`
- 不要让 `ops` 直接依赖 `biz`
- 不要让 `biz` 直接依赖 `ops`
- 不要继续把共享能力堆进 `src/db.py` 与 `src/utils.py`
- 不要一上来就创建大而全的 `src/app` 并整体搬迁 `platform`

---

### 4. 每次只做一个阶段目标

不要在同一轮任务中同时做：

- 大规模目录迁移
- 业务逻辑重写
- 架构重设计
- CLI 重做
- API 契约大改

每次只完成一个明确阶段目标，并保留兼容性。

---

### 5. 复杂迁移先计划

符合以下情况时，先输出计划，不要直接改代码：

- 跨多个目录迁移
- 涉及 foundation 依赖方向修复
- 涉及 operations -> ops 归并
- 涉及 platform 拆分
- 涉及 app 壳引入
- 涉及 CLI 归属重整

---

## 当前推荐目录流向

### 新 foundation 相关代码

优先进入：

- `src/foundation/**`

### 新运维/运行时相关代码

优先进入：

- `src/ops/runtime/**`
- `src/ops/services/**`
- `src/ops/specs/**`
- `src/ops/api/**`
- `src/ops/queries/**`
- `src/ops/schemas/**`

### 新业务 API / 业务查询 / 业务服务

优先进入：

- `src/biz/**`

### 新 app 装配逻辑

优先朝未来目标收敛：

- 优先识别并抽离 `platform/web`、`platform/auth`、`platform/dependencies`、`platform/exceptions`
- `platform/api/router.py` 与 `platform/api/v1/router.py` 属于当前 app 聚合入口，默认最后迁移
- 若尚未创建 `src/app`，应采用最小过渡方式，不要因为“目标结构”而立即大搬迁

---

## 交付要求

每次任务完成后，必须说明：

1. 本次目标
2. 依据来源
3. 改动文件
4. 是否影响子系统边界
5. 是否影响依赖矩阵
6. 验证结果
7. 风险与待确认项

---

## 当前优先级

在本仓库当前阶段，优先级排序如下：

1. 阻止新增错误依赖
2. 固化迁移计划与目录规则
3. 拆 foundation 的反向依赖
4. 合并 operations 到 ops
5. 拆 platform
6. 再处理 db.py / utils.py 的共享归位
