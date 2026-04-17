# 架构设计问题清单 V1（2026-04-18）

## 1. 背景与目标

本清单用于沉淀本轮“运行时稳定性 + 数据状态一致性”梳理结果，形成可执行的修复闭环：

1. 将问题按优先级分层（P0/P1）。
2. 明确每个问题的根因、影响面、验收标准。
3. 把修复方案拆分到独立文档，方便并行推进与复盘。

## 2. 问题分级定义

1. `P0`：会直接导致运行错误、状态错误、数据一致性风险或严重误导，需优先修复。
2. `P1`：不会立即造成全链路中断，但会持续增加维护成本、回归风险或可观测性盲区，需在本轮一起收敛。

## 3. 问题清单

## P0

1. `P0-1`：Worker 抢占任务非原子，存在并发重复领取窗口。  
影响：多 worker 并发下可能出现同一 `queued` 任务被竞争处理，产生冲突/异常状态。

2. `P0-2`：Sync 过程进度写入与业务数据共用同一事务，进度更新中的 `commit` 会提前提交主事务。  
影响：处理中间态被提前落库，失败回滚语义被破坏，导致“失败但部分业务数据已提交”。

## P1

1. `P1-1`：observed-date 模型注册表重复维护（freshness 与 reconciliation 各一份）。  
影响：新增/迁移数据集时容易只改一处，出现业务日计算不一致。

2. `P1-2`：数据状态快照刷新失败在关键路径可见性不足。  
影响：执行完成后 UI 可能仍看到旧状态，但系统未显式告警，排障成本高。

3. `P1-3`：freshness 元数据对新增 sync 资源缺少强校验。  
影响：新增数据集后容易出现“显示名称未配置”等问题，直到运行阶段才暴露。

## P2

1. `P2-1`：Execution finalize 后的状态快照刷新与主 execution 会话耦合过高。  
影响：快照子流程异常可能干扰主会话，排障边界不清晰。

2. `P2-2`：快照行到 freshness item 的投影逻辑分散在多个类中。  
影响：字段扩展时容易漏改，形成“同一快照两套口径”。

## P3

1. `P3-1`：P0/P1 修复点缺少针对性回归测试。  
影响：后续重构时容易回归，且问题会在运行阶段才暴露。

2. `P3-2`：新增数据集模板缺少“启动期守门校验”的显式勾选项。  
影响：研发交付仍可能只做功能验证，遗漏架构守门验证。

## 4. 修复方案文档

1. P0 修复方案：  
[architecture-design-issues-p0-remediation-v1.md](/Users/congming/github/goldenshare/docs/architecture/architecture-design-issues-p0-remediation-v1.md)
2. P1 修复方案：  
[architecture-design-issues-p1-remediation-v1.md](/Users/congming/github/goldenshare/docs/architecture/architecture-design-issues-p1-remediation-v1.md)
3. P2 修复方案：  
[architecture-design-issues-p2-remediation-v1.md](/Users/congming/github/goldenshare/docs/architecture/architecture-design-issues-p2-remediation-v1.md)
4. P3 修复方案：  
[architecture-design-issues-p3-remediation-v1.md](/Users/congming/github/goldenshare/docs/architecture/architecture-design-issues-p3-remediation-v1.md)

## 5. 统一验收口径

1. 并发 worker 场景下，不得再出现同一 execution 被重复启动。
2. sync 任务失败时，业务数据必须遵守单事务回滚语义；进度更新不应破坏主事务边界。
3. 新增数据集若遗漏 freshness 元数据，必须在启动/导入阶段直接失败，不能静默跳过。
4. 状态快照刷新异常必须在 execution 事件中可见，支持前端与运维定位。
5. 快照字段口径在所有读路径保持一致，避免同数据多口径。
6. P0/P1 架构守门项必须有自动化回归测试覆盖。
