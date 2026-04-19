# AGENTS.md — src/app/api 聚合入口规则

## 适用范围

本文件适用于 `src/app/api/` 目录及其所有子目录。

若更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前目录的规则为准。

---

## 目录定位（硬约束）

`src/app/api` 是 **app 壳下的聚合入口目录**，不是业务实现目录。

它的职责是：
- 聚合已经分别落位到 `src/app/auth`、`src/biz`、`src/ops` 的子路由
- 提供新的 app 级路由入口
- 为最终替代 `src/platform/api/router.py` 与 `src/platform/api/v1/router.py` 做准备

它不是：
- biz API 主实现目录
- ops API 主实现目录
- auth/admin 业务规则实现目录

---

## 这里负责什么

`src/app/api` 负责：

1. app 级路由聚合
2. `/api` 与 `/api/v1` 入口编排
3. `include_router(...)` 组合
4. 健康检查与入口级轻量路由组织
5. 最终承接 platform 聚合入口的主实现
6. final cutover 期间的入口切换编排（仅入口，不改业务实现）

---

## 这里不负责什么

`src/app/api` 不负责：

1. biz 业务查询与业务 API 主逻辑
2. ops 运维治理 API 主逻辑
3. auth/admin service 业务逻辑
4. foundation 底层同步逻辑

若出现以上逻辑，应分别归位到：
- `src/biz/**`
- `src/ops/**`
- `src/app/auth/**`
- `src/foundation/**`

---

## 聚合入口迁移硬约束

处理聚合入口时，必须满足：

1. 先完成子路由落位，再处理入口切换
2. 新入口只负责聚合，不承载业务实现
3. 旧入口应保留 deprecated 兼容壳，避免一次性切全量调用方
4. 保持 `/api/health`、`/api/v1/*` 路由兼容
5. 不允许顺手改动业务 API 路径、标签、返回契约
6. 本轮若任务被定义为“准备阶段”，只允许修改文档与 AGENTS，不允许迁移实现代码

---

## 本目录允许做什么

### 允许

1. app 级 router 聚合
2. 入口级轻量健康检查组织
3. 旧路径 shim / compat 转发
4. 不改变外部行为的最小入口收敛

### 不允许

1. 在 `src/app/api` 中直接实现 biz/ops/auth 业务规则
2. 顺手改动大量路由路径或返回结构
3. 未经计划直接重做整套路由体系
4. 把 `src/app/api` 变成新的“大杂烩 API 目录”

---

## 完成任务时说明要求

每次修改 `src/app/api` 后，需说明：

1. 本次是否只是聚合/入口收敛，而非业务逻辑迁移
2. 聚合了哪些子路由
3. 是否保持了旧入口兼容壳
4. 是否影响 `/api` 与 `/api/v1` 的外部行为
