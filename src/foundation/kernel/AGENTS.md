# AGENTS.md — `src/foundation/kernel/` 规则

## 适用范围

本文件适用于 `src/foundation/kernel/` 及其子目录。

---

## 1. 目录定位

`kernel` 是 foundation 的内核抽象层，目标是：

1. 定义稳定契约（contracts/protocols）。
2. 提供跨模块复用的基础语义。

不是业务逻辑目录，不承接具体数据集实现。

---

## 2. 硬约束

1. 禁止在 kernel 写具体 ORM/SQL 实现细节。
2. 禁止在 kernel 引入 ops/biz/app 语义依赖。
3. 禁止把临时过渡逻辑长期放在 kernel。

---

## 3. 设计原则

1. 先抽象能力，再接具体实现。
2. 合同必须稳定、命名清晰、边界明确。
3. 默认实现仅允许 NoOp/Null 风格，不得耦合具体外部存储语义。

