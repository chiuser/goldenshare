# 架构问题 P2 修复方案 V1（2026-04-18）

关联总览：  
[architecture-design-issues-v1.md](/Users/congming/github/goldenshare/docs/architecture/architecture-design-issues-v1.md)

## 1. P2-1 快照刷新会话解耦

## 问题现状

execution finalize 之后会触发数据状态快照刷新。若仍与主 execution 事务/会话耦合，边界不清晰，异常处理容易产生连带影响。

## 修复方案

1. 将“execution 状态收敛提交”和“快照刷新”分为两个会话边界。  
2. 快照刷新失败只记录 warning 事件，不回滚已完成的 execution 状态。  
3. warning 事件结构化携带错误摘要，便于页面与运维定位。

## 验收标准

1. execution 成功/失败状态提交后，不因快照刷新异常被覆写。  
2. 快照刷新异常可在 execution 事件流直接观察到。  

## 2. P2-2 快照投影口径统一

## 问题现状

`DatasetStatusSnapshot` 到 `DatasetFreshnessItem` 的字段投影在多个类重复实现，字段演进时容易出现“写了快照但某条读路径没更新”的问题。

## 修复方案

1. 抽取统一投影函数（snapshot row -> freshness item）。  
2. `freshness_query_service` 与 `dataset_status_snapshot_service` 共用该函数。  
3. 后续字段新增仅维护一处映射。

## 验收标准

1. 项目中不存在两套独立的快照投影实现。  
2. 快照字段新增时，所有读取路径口径一致。  

## 3. 风险与回滚

1. 会话解耦后若新增异常，优先保主执行状态正确，其次再处理快照更新。  
2. 投影函数集中后若映射错误，影响面更集中，但也更易单点修复。  
