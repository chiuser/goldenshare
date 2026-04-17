# 架构问题 P0 修复方案 V1（2026-04-18）

关联总览：  
[architecture-design-issues-v1.md](/Users/congming/github/goldenshare/docs/architecture/architecture-design-issues-v1.md)

## 1. P0-1 Worker 原子领取任务

## 问题现状

`run_next` 采用“先 select queued，再调用 run_execution”模式，两个并发 worker 可能读到同一行 `queued` execution，随后竞争更新，产生冲突或重复启动尝试。

## 修复方案

1. 将 `run_next` 改为“原子领取”：
- 先只查询候选 `execution_id`（最早 queued）。
- 通过条件更新 `WHERE id=:id AND status='queued'` 抢占。
- `rowcount == 1` 才算领取成功，否则重试下一轮。
2. 领取成功后直接进入“已启动执行”路径，避免再次走 `queued` 检查。
3. 对 `queued + cancel_requested_at is not null` 的任务优先收敛为 canceled，防止队列头阻塞。

## 验收标准

1. 并发 worker 运行时，同一 execution 最多被一个 worker 成功领取。
2. 不再出现“Only queued executions can start immediately”类并发冲突噪音。

## 2. P0-2 进度写入事务隔离

## 问题现状

多个 sync 服务在 `_update_progress` 中直接 `self.session.commit()`，会把当前业务事务一并提交，破坏“execute 整体成功/失败”语义。

## 修复方案

1. 在 `BaseSyncService` 提供统一进度写入方法，使用独立 session/事务写 `ops.job_execution` 进度字段。
2. 各 sync 服务的 `_update_progress` 统一改为调用基类方法，不再操作主业务 session 的提交。
3. 进度写入失败仅记录日志，不影响主同步流程提交/回滚。

## 验收标准

1. sync 执行期间不再出现由 `_update_progress` 触发的主事务提前提交。
2. 任务失败时，业务数据可整体回滚；进度字段可独立更新。
3. 所有存在 `_update_progress` 的服务实现统一收敛到基类方法。

## 3. 风险与回滚

1. 若独立进度会话在极端环境不可用，主流程仍可继续，只损失实时进度可见性，不影响数据正确性。
2. 若发现 worker 抢占逻辑异常，可临时退回单 worker 运行并快速回滚 `run_next` 改动。
