# AGENTS.md — src/ops 目标承接目录规则

## 适用范围

本文件适用于 `src/ops/` 目录及其所有子目录。

---

## 当前阶段定义

`src/ops` 是未来运维与运行时子系统的主承接目录。

未来它将统一承接：

- runtime
- specs
- 运维 API
- 运维 Query
- 运维 Service
- 运维 Schema
- 运维相关模型

当前虽然 `src/operations` 仍存在，但方向已经明确：

- 新的长期 ops 逻辑优先进入 `src/ops`
- `src/operations` 只做维护与迁移，不再作为首选落点

---

## 本目录负责什么

### 负责

- scheduler / worker / dispatcher / runtime 编排
- job / workflow / freshness / pipeline mode 等 spec
- 运维 API
- 运维查询
- 运维服务
- 执行状态、探测、任务、审查中心等运维模型与 schema

### 不负责

- foundation 底层同步基础设施
- 对上业务 API / 业务查询语义
- 应用壳装配
- 认证 wiring

---

## 新代码放置规则

### 新 runtime 逻辑

优先进入：

- `src/ops/runtime/**`

### 新 spec 逻辑

优先进入：

- `src/ops/specs/**`

### 新运维 API / Query / Schema / Service

优先进入：

- `src/ops/api/**`
- `src/ops/queries/**`
- `src/ops/schemas/**`
- `src/ops/services/**`

不要再把新的长期 ops 逻辑放到 `src/operations/**`。

---

## 依赖规则

### 允许依赖

- `src.foundation`
- `src.ops`

### 禁止依赖

- `src.biz`
- 旧 `src.platform` 中的业务域能力

若确实需要某个业务语义，请先停在设计/计划阶段，判断该能力是否本就归属于 biz，或是否应该下沉为 foundation contract。

---

## 与 operations 的关系

当前处于过渡期，允许：

- 从 `src/operations` 渐进迁入 `src/ops`
- 为兼容旧路径提供少量薄转发

但不允许：

- 与 `src/operations` 长期双写
- 同时在 `operations` 和 `ops` 中新增同类长期实现
- 不经判断地复制 service 到两边

---

## 与 platform 的关系

`src/ops` 承接的是运维域能力，不是 app 壳。

因此：

- web / auth / dependencies / exceptions 不应放入 `src/ops`
- 若从 `platform` 迁移内容进来，必须先判定它属于运维域，而不是 app 壳或 biz 域

---

## 任务执行建议

处理本目录任务时，优先遵循：

1. 先判断是否已有 `operations` 对应旧实现
2. 有则优先考虑“收敛/兼容/归并”
3. 无则直接在 `ops` 新增
4. 保持目录命名与职责清晰
5. 不顺手扩大为大规模架构清扫

---

## 交付要求

每次完成涉及 `src/ops` 的任务后，必须说明：

1. 本次能力属于 runtime / specs / api / queries / schemas / services 中哪类
2. 是否替代或吸收了 `src/operations` 的旧逻辑
3. 是否新增了兼容导出
4. 是否影响 CLI 调用
5. 是否影响依赖矩阵

---

## 当前优先级

在本目录当前阶段，优先级排序如下：

1. 承接新的长期 ops 逻辑
2. 吸收 `operations` 的 runtime / specs
3. 再处理 services 重叠
4. 保持 ops 与 biz 边界清晰
