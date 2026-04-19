# AGENTS.md — src/app/schemas 通用 Schema 承接规则

## 适用范围

本文件适用于 `src/app/schemas/` 目录及其所有子目录。

若更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前目录的规则为准。

---

## 目录定位（硬约束）

`src/app/schemas` 是 app 壳下的通用 schema 承接目录。

这里只承接 **app-auth / app-api 层真正共用** 的 schema，不是业务模型容器。

---

## 这里负责什么

`src/app/schemas` 负责：

1. app 壳层公共响应 schema（如健康检查、通用 OK/错误响应）
2. app-auth 与 app-api 共同依赖的轻量通用 schema
3. platform -> app 迁移过程中的 schema 路径收敛与兼容组织

---

## 这里不负责什么

`src/app/schemas` 不负责：

1. biz 业务返回模型
2. ops 运维返回模型
3. foundation 底层数据结构契约

若出现以上 schema，应分别归位到：

- `src/biz/schemas/**`
- `src/ops/schemas/**`
- `src/foundation/**`

---

## 迁移 `platform/schemas/common.py` 的硬约束

迁移前必须先确认：

1. 共享范围是否仅限 app 壳层
2. 不会引入 biz/ops schema 交叉回流
3. 旧路径是否保留 deprecated shim

迁移时必须满足：

1. 保持响应字段与语义兼容
2. 不允许顺手扩大 schema 责任边界
3. 不允许把 app/biz/ops 混合 schema 继续堆在本目录

---

## 完成任务时说明要求

每次修改 `src/app/schemas` 后，需说明：

1. 本次 schema 是否属于 app 壳层共用
2. 是否影响 biz/ops schema 边界
3. 是否保留了旧路径兼容策略（如适用）
