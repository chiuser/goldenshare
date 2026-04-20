# 数据同步 V2 详细技术方案总索引（分期评审版）

- 版本：v1.0
- 日期：2026-04-21
- 状态：待评审
- 主方案基线：[数据同步 V2 重设计方案](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
- 表改造配套：[Ops 数据表改造清单](/Users/congming/github/goldenshare/docs/architecture/ops-schema-migration-checklist-v2.md)
- 编码执行版：[V2 分期可执行编码任务包](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-implementation-work-packages.md)

---

## 1. 分期策略（为什么这样拆）

本次 V2 采用“先控制面可观测，再数据面可替换，最后收口兼容层”的顺序。原因：

1. 执行态模型是所有能力的基础，不先定 execution/step/unit，后续进度和错误语义无法稳定。  
2. 引擎与契约是数据集迁移的核心，不先固化 contract/plan/unit/error，迁移会重复返工。  
3. 工作流、probe、状态投影属于跨模块协同，必须在执行模型稳定后落地。  
4. 最终切换（双写、读切、停写旧表）需要前面三期都通过门禁。  

---

## 2. 分期清单（评审入口）

### 第 1 期：执行域模型与事件基线（P0）

文档：
- [Phase 1 - 执行域与事件模型](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-1-execution-domain.md)

目标：
- 定义并落地 `execution/step/unit/event` 的统一模型。  
- 补齐运行语义、失败语义、事件 envelope。  

### 第 2 期：引擎与数据集契约（P0）

文档：
- [Phase 2 - 引擎与契约层](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-2-engine-contracts.md)

目标：
- 建立 `DatasetSyncContract`、`Planner/Worker/Normalizer/Writer` 的标准接口与字段语义。  
- 引入 ACL 反腐层模型，隔离数据源协议。  

### 第 3 期：工作流/Probe/状态投影（P1）

文档：
- [Phase 3 - 工作流、Probe 与状态投影](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-3-workflow-probe-projection.md)

目标：
- 统一工作流参数语义、失败策略、恢复策略。  
- 完成 Probe 拆分触发与双层进度展示模型。  
- 打通状态投影一致性规则。  

### 第 4 期：迁移切换与兼容收口（P1/P2）

文档：
- [Phase 4 - 迁移切换与收口](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-4-cutover-migration.md)

目标：
- 完成双写、读切、停写、兼容退场。  
- 给出可回滚窗口与最终验收基线。  

---

## 3. 统一评审模板（每期必须回答）

1. 模块职责是否单一、边界是否清晰？  
2. 字段字典是否完整（类型、默认、必填、语义、约束）？  
3. 不变量和状态机是否可执行（不是口头规则）？  
4. 与现有代码/表是否有冲突？冲突如何迁移？  
5. 回滚策略是否可操作、可验证？  
6. 本期完成后，下期是否具备进入条件？  

---

## 4. 里程碑门禁（跨期）

1. 第 1 期通过前，不进入第 2 期编码。  
2. 第 2 期通过前，不启动数据集批量迁移。  
3. 第 3 期通过前，不切换 ops 主页面读链。  
4. 第 4 期执行前，必须完成全量引用审计与回滚演练。  
