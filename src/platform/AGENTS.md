# AGENTS.md — src/platform 过渡期规则

## 适用范围

本文件适用于 `src/platform/` 目录及其所有子目录。

---

## 当前阶段定义

`src/platform` 是历史过渡目录，不是未来目标中的长期业务子系统。

未来目标是将 `platform` 消解为两类内容：

1. app 壳职责
   - `web`
   - `auth`
   - `dependencies`
   - `exceptions`
   - 少量组合根 glue code
   - router 聚合入口

2. 应迁出的业务职责
   - `api`
   - `queries`
   - `schemas`
   - `services`
   - `models` 中与业务/运维有关的部分

最终目标是：

- app 壳相关内容进入 `src/app/**`
- 业务 API / Query / Schema / Service 进入 `src/biz/**`
- 运维 API / Query / Schema / Service 进入 `src/ops/**`

注意：
- `platform` 不应被直接整体 rename 为 `app`
- 应先拆职责，再抽壳

---

## 本目录当前允许做什么

### 允许

- 修复本目录已有代码中的 bug
- 为迁移做最小过渡封装
- 增加 deprecated 注释
- 将旧实现改为薄转发层
- 梳理 router / web / auth / dependencies 的 app 壳职责
- 做不改变外部行为的最小路径调整

### 不允许

- 在 `platform/api` 中新增长期业务 API
- 在 `platform/queries` 中新增长期业务查询服务
- 在 `platform/services` 中新增长期业务逻辑
- 在 `platform/schemas` 中新增长期业务 schema
- 把本应进入 `biz` 或 `ops` 的新能力继续写进 `platform`
- 把 `platform` 继续做成“第四个子系统”
- 一次性整体搬走全部 `platform` 内容

---

## 目录归属指导

### `platform/web`

未来归属：`app/web`

说明：

- 这里是应用壳的核心候选目录
- 可作为未来 `src/app/web` 的迁移来源

---

### `platform/auth`

未来归属：`app/auth`

说明：

- 认证接线、当前用户依赖、权限依赖等属于 app 壳，不属于 foundation / ops / biz

---

### `platform/dependencies`

未来归属：`app/dependencies` 或 `app/di`

说明：

- 这里只应保留 app 级依赖装配
- 不应长期承载业务查询逻辑

---

### `platform/exceptions`

未来归属：`app/exceptions`

---

### `platform/api`

未来归属：

- 业务 API -> `biz/api`
- 运维 API -> `ops/api`
- 少量 router 聚合 -> `app`

规则：

- 不再新增新的长期 endpoint 到本目录
- 新能力应直接写到未来归属目录
- 本目录后续只允许保留过渡路由或薄转发

特别说明：

- `platform/api/router.py` 是当前 `/api` 根聚合路由入口的一部分
- `platform/api/v1/router.py` 是当前 v1 路由聚合入口的一部分
- 这两个文件不应与普通业务 API 一起提前迁移，默认属于最后迁移对象

---

### `platform/queries`

未来归属：

- 业务查询 -> `biz/queries`
- 运维查询 -> `ops/queries`

---

### `platform/services`

未来归属：

- 业务服务 -> `biz/services`
- 运维服务 -> `ops/services`

---

### `platform/schemas`

未来归属：

- 业务 schema -> `biz/schemas`
- 运维 schema -> `ops/schemas`

---

### `platform/models`

未来归属需细分：

- app 用户/认证相关 -> `app/models` 或 `app/auth/models`
- 运维 ORM 模型 -> `ops/models`
- 业务 ORM / DTO / query model -> `biz/models`

注意：

- 在未判定归属前，不要继续加厚本目录
- 先说明归属，再做迁移

---

## 依赖规则

### 本目录中的代码不应成为基础层依赖源

禁止形成：

- `foundation -> platform`

若发现 foundation 直接依赖 platform，优先作为重构对象处理。

---

### 本目录不应继续承接新的共享基础设施

不要把以下能力继续新增到 `platform`：

- db/session 基础能力
- contracts / ports
- shared primitives
- 通用 utils

这些应归入 foundation 或未来的 app 壳。

---

## 迁移任务执行规则

当任务涉及 `platform` 时，优先判断：

1. 这个能力其实属于 app 壳？
2. 这个能力其实属于 biz？
3. 这个能力其实属于 ops？

若答案明确，就不要继续留在 `platform` 新增逻辑。

若任务命中 `platform/api/router.py` 或 `platform/api/v1/router.py`，默认应按“应用聚合层”对待，而不是按普通业务 API 对待。

---

## 完成任务时的输出要求

每次涉及 `platform` 的任务完成后，必须说明：

1. 本次改动属于 app / biz / ops 中的哪类职责
2. 为什么暂时还保留在 `platform`，还是已经迁出
3. 是否新增了过渡层
4. 是否影响 router 挂载
5. 是否影响 auth / dependencies / exceptions
6. 后续下一步适合继续迁出什么

---

## 当前优先迁出对象

第一批优先迁出：

- 明显属于业务域的 API / Query / Schema / Service
- 如 share 相关能力

优先保留但收敛：

- `web`
- `auth`
- `dependencies`
- `exceptions`
- router 聚合链路

---

## 禁止顺手扩大范围

处理 `platform` 任务时：

- 不要顺手改整个认证体系
- 不要顺手重做全部 router
- 不要顺手重写所有 schema
- 不要顺手把 app 壳全部一次性搬完

每次只做一个明确迁移目标，并保持外部行为稳定。
