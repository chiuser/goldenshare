# AGENTS.md — src/app/web 应用壳运行入口规则

## 适用范围

本文件适用于 `src/app/web/` 目录及其所有子目录。

若更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前目录的规则为准。

---

## 目录定位（硬约束）

`src/app/web` 是 **应用壳运行入口目录**。

它的职责是：
- 创建 Web 应用
- 注册 middleware / lifespan / exception handlers
- 挂载静态资源
- 接入 `src/app/api` 聚合入口
- 最终承接 `src/platform/web/app.py` 的主实现

它不是：
- biz 实现目录
- ops 实现目录
- auth 业务实现目录

---

## 这里负责什么

`src/app/web` 负责：

1. FastAPI app 创建
2. middleware 注册
3. lifespan 注册
4. exception handler 装配
5. 静态资源挂载
6. 运行入口组织
7. app 级设置接线

---

## 这里不负责什么

`src/app/web` 不负责：

1. biz 查询与业务 API 主逻辑
2. ops 运维治理逻辑
3. auth/admin 服务业务规则
4. foundation 同步与存储逻辑

---

## 运行入口迁移硬约束

处理 `platform/web/app.py` -> `src/app/web/*` 迁移时，必须满足：

1. 先完成子路由与聚合入口落位，再切运行入口
2. 保持 middleware、lifespan、异常处理与静态资源行为等价
3. 不允许顺手改启动逻辑、配置读取逻辑、健康检查路径
4. 旧路径应保留 deprecated 兼容壳，避免一次性切全量调用方
5. 任何入口迁移都必须以行为兼容优先，而不是代码风格优先

---

## 本目录允许做什么

### 允许

1. app 创建与运行入口收敛
2. middleware / lifespan / exception handler 装配
3. 旧路径 shim / compat 转发
4. 不改变外部行为的最小入口迁移

### 不允许

1. 在 `src/app/web` 中实现 biz/ops/auth 业务规则
2. 顺手改配置模型、返回契约、路由路径
3. 未经计划直接重构整个 web 启动体系

---

## 完成任务时说明要求

每次修改 `src/app/web` 后，需说明：

1. 本次是否只是运行入口/壳层收敛
2. 是否保持了 middleware / lifespan / exception handler 行为兼容
3. 是否保持了静态资源与健康检查行为兼容
4. 是否保留了旧路径兼容壳
