# AGENTS.md — src/app 组合根规则

## 适用范围

本文件适用于 `src/app/` 目录及其所有子目录。

若更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前目录的规则为准。

---

## 目录定位（硬约束）

`src/app` 是 **app / composition-root** 目录，不是第四个业务子系统。

业务子系统仍只有三个：

- `foundation`
- `ops`
- `biz`

`app` 只做装配与入口，不承载业务核心规则。

---

## 这里负责什么

`src/app` 负责以下壳层职责：

1. web app 创建
2. router 聚合
3. auth wiring
4. dependency wiring
5. exception handler 装配
6. model registry
7. 启动入口

---

## 这里不负责什么

`src/app` 不负责以下职责：

1. biz 业务查询逻辑
2. ops 运维治理逻辑
3. foundation 底层同步逻辑

出现以上逻辑时，应分别归位到 `src/biz`、`src/ops`、`src/foundation`。

---

## platform 拆分阶段规则

当前仓库进入 platform 拆分准备阶段时，新增 app 壳逻辑优先进入 `src/app`：

- 来自 `platform/web` 的壳逻辑
- 来自 `platform/auth` 的装配逻辑
- 来自 `platform/dependencies` 的注入逻辑
- 来自 `platform/exceptions` 的 handler 装配逻辑
- 来自 `platform/api/router.py` / `platform/api/v1/router.py` 的聚合入口逻辑（最后迁移）

---

## 禁止事项

1. 不要把 `src/app` 做成业务逻辑堆积层。
2. 不要在 `src/app` 内实现 `biz` 或 `ops` 的核心 service/query 规则。
3. 不要让 `src/app` 反向成为下层依赖目标（下层不应依赖 app）。

---

## 完成任务时的输出要求

每次改动 `src/app` 后，需说明：

1. 本次改动属于哪类壳职责（web/router/auth/di/exception/model-registry/entrypoint）
2. 是否引入了任何业务规则（如有，应回滚并归位）
3. 是否影响 `platform` 到 `app` 的拆分路径
