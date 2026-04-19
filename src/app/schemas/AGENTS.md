# AGENTS.md — `src/app/schemas` 通用 Schema 规则

## 适用范围

本文件适用于 `src/app/schemas/` 及其子目录。

---

## 目录定位

`src/app/schemas` 仅承接 app 壳层共用 schema（例如健康检查等入口级 schema）。

不承接：

1. Biz 业务返回模型（应在 `src/biz/schemas`）
2. Ops 运维返回模型（应在 `src/ops/schemas`）

---

## 硬约束

1. 不把 app/biz/ops schema 混在本目录。
2. 不顺手改字段命名与契约语义。
3. 兼容变更需先确认调用范围。

---

## 改动后说明

每次改动需说明：

1. 该 schema 为何属于 app 壳共用
2. 是否影响已有接口契约
3. 是否涉及跨子系统 schema 边界调整
