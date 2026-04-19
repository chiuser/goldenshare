# AGENTS.md — `src/app/web` 运行入口规则

## 适用范围

本文件适用于 `src/app/web/` 及其子目录。

---

## 目录定位

`src/app/web` 负责运行入口装配：

1. FastAPI app 创建
2. middleware/lifespan/异常处理装配
3. 静态资源挂载
4. 启动入口组织

不负责业务规则实现。

---

## 硬约束

1. 不在本目录新增 biz/ops/foundation 业务逻辑。
2. 变更时优先保持路由、middleware 顺序和入口行为兼容。
3. 非必要不改变启动参数语义。

---

## 改动后说明

每次改动需说明：

1. 是否仅入口/装配层变化
2. 是否影响 `/api`、`/app`、`/ops`、`/api/docs` 行为
3. 是否影响静态资源挂载
