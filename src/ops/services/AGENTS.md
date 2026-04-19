# AGENTS.md — `src/ops/services` 服务层规则

## 适用范围

本文件适用于 `src/ops/services/` 及其子目录。

---

## 目录定位

`src/ops/services` 是 ops 服务层主承接目录。

---

## 文件角色

1. **主实现文件**：承接完整治理能力。
2. **入口/facade 文件**：只做薄编排与稳定导出。
3. **适配器文件**：仅做 contract/adapter 注入连接。

---

## 约束

1. 新主实现只能放在本目录，不回流 `src/operations/services`。
2. facade 不得承载重业务逻辑。
3. 不在本目录实现 biz 业务语义。
4. 变更需保持 CLI、runtime、API 调用链行为稳定。

---

## 改动后说明

每次改动需说明：

1. 本次变更属于主实现/facade/适配器哪一类
2. 是否影响调度执行链路或 CLI 命令行为
3. 是否影响 ops API/query/schema 对应契约
