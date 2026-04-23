# AGENTS.md — `src/foundation/services/` 规则

## 适用范围

本文件适用于 `src/foundation/services/` 及其子目录。  
若子目录存在更近的 `AGENTS.md`，以更近规则为准。

---

## 1. 目录定位

该目录承接 foundation 的服务层能力，当前主分层：

1. `sync_v2/`：同步主链（唯一生效链路）。
2. `transform/`：转换/规范化工具能力。
3. `migration/`：迁移辅助能力（一次性或低频运维动作）。

---

## 2. 硬约束

1. 禁止新增 `sync/`（V1）实现或导入路径回流。
2. 禁止把 ops/biz 语义塞入 foundation service。
3. 禁止在 service 层写入跨子系统编排逻辑。
4. 禁止在迁移脚本中沉淀长期主流程逻辑。

---

## 3. 变更边界

1. 日常同步能力改动：只在 `sync_v2/**` 完成。
2. 数据转换逻辑改动：优先在 `transform/**` 完成。
3. 迁移工具改动：只影响迁移场景，不影响主链默认路径。

---

## 4. 动手前必读

1. `/Users/congming/github/goldenshare/src/foundation/AGENTS.md`
2. `/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md`
3. `/Users/congming/github/goldenshare/docs/architecture/sync-v2-dataset-strategy-simplification-plan-v1.md`

