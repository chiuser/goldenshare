# AGENTS.md — `src/foundation/kernel/contracts/` 规则

## 适用范围

本文件适用于 `src/foundation/kernel/contracts/`。

---

## 1. 目录定位

该目录只定义 contract/protocol/interface（能力声明），用于：

1. foundation 与实现层之间解耦；
2. 防止 foundation 直接知道 ops/biz 具体实现细节。

---

## 2. 硬约束

1. contract 文件只能声明能力接口，不写具体存储实现。
2. 禁止引用 `src.ops.*`、`src.biz.*`、`src.app.*`。
3. 禁止把 ops 表结构语义写入 contract 类型命名中。
4. 任何默认实现必须是 NoOp/Null，且保持无副作用。

---

## 3. 演进规则

1. 修改 contract 前先审计全部实现方与调用方。
2. 字段/方法演进遵守[根 AGENTS 的硬约束](/Users/congming/github/goldenshare/AGENTS.md#硬约束)：未获明确批准保持现行调用契约，不以此新增旧接口兼容层。
3. 获准变更契约时，先补迁移文档，再同步修改全部实现方与调用方，清零旧口径，不保留双轨接口。
