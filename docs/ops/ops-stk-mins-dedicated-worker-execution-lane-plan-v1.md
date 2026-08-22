# 分钟线数据集独立执行车道方案 v1

状态：三车道方案已实现，待生产验收
更新时间：2026-08-20  
适用范围：生产 Ops TaskRun 消费、`stk_mins`/`index_mins` 长任务隔离、现有 ingestion 主链

实现级设计：[分钟线数据集独立执行车道 LLD v1](/Users/congming/github/goldenshare/docs/ops/ops-minute-datasets-dedicated-worker-execution-lane-lld-v1.md)

> 本文沿用既有文件路径，但方案范围已经从单一 `stk_mins` 扩展为“通用车道 + 股票分钟线车道 + 指数分钟线车道”三车道。代码落地时不新增第三套任务事实源，也不改变数据集的同步语义。

## 1. 背景与审计结论

当前生产只有一个通用任务执行进程：

```text
goldenshare-ops-worker.service
  -> OperationsWorker
  -> TaskRunDispatcher
  -> DatasetActionResolver
  -> IngestionExecutor
```

因此 `stk_mins` 和 `index_mins` 的直接数据集任务都会进入同一个队列消费者。`stk_mins` 已经具备单进程内 2 路源端 fetch 并发，但这只改变一个任务内部的请求方式，不能避免它长时间占用唯一通用 worker。

当前代码核验结果：

| 项目 | 当前事实 |
| --- | --- |
| 通用 worker | 只有 `goldenshare-ops-worker.service` 负责领取普通 TaskRun |
| `stk_mins` | `fetch_concurrency=2`，只并发 fetch；normalize、write、commit、progress 仍在主线程串行执行 |
| `index_mins` | 使用同一套 TaskRun/Dispatcher/Resolver/Executor，当前 `fetch_concurrency=1` |
| 任务分流 | 当前 `OperationsWorker` 没有按 `resource_key` 分车道 |
| 业务表与事务 | 两个数据集均保持现有 writer、DAO、unit 事务边界 |
| 工作流 | 当前工作流定义未包含 `stk_mins` 或 `index_mins` 步骤 |
| 独立服务 | 当前尚未存在股票分钟线或指数分钟线专用 systemd worker |

远程 prod 只读审计还确认：最近一次 `stk_mins` 大任务 TaskRun `8752` 处理 `29,430` 个 unit，耗时约 `298` 分钟，期间其他 TaskRun 会继续排队。这个事实证明本专项首先要解决的是队列隔离，不应把它误写成再次提升源端并发。

## 2. 目标

建立三个独立的消费车道：

```text
ops.task_run
  ├─ 通用 worker：消费除 stk_mins/index_mins 外的任务
  ├─ stk_mins worker：只消费股票历史分钟线任务
  └─ index_mins worker：只消费指数历史分钟线任务
```

目标是：

1. `stk_mins` 长任务不再阻塞其他数据集。
2. `index_mins` 长任务不再阻塞其他数据集。
3. `stk_mins` 与 `index_mins` 彼此也不共享同一个长任务执行进程。
4. 三条车道仍使用同一套 TaskRun 主链和 ingestion 执行语义。

本专项不承诺两个分钟线任务自身耗时固定下降；它解决的是任务队列被长任务占用的问题。

## 3. 核心设计

### 3.1 三个进程，一个 TaskRun 主链

三个 worker 都从同一张 `ops.task_run` 表领取任务，使用同一套：

- `TaskRun` 状态流转；
- 原子 claim 逻辑；
- `TaskRunDispatcher`；
- `DatasetActionResolver`；
- `DatasetExecutionPlan`；
- `IngestionExecutor`；
- writer、业务事务和进度观测。

不新增任务表、队列表、worker lane 数据库字段或第二套执行器。

车道是运行时消费策略，不是用户任务意图。现有 `TaskRun.task_type/resource_key` 已能表达本期分流事实。

### 3.2 车道判定

| 车道 | 匹配条件 | 允许领取 |
| --- | --- | --- |
| `general` | `NOT (task_type="dataset_action" AND resource_key IN {"stk_mins", "index_mins"})` | 除两个分钟线数据集外的任务 |
| `stk_mins` | `task_type="dataset_action" AND resource_key="stk_mins"` | 仅股票历史分钟线 |
| `index_mins` | `task_type="dataset_action" AND resource_key="index_mins"` | 仅指数历史分钟线 |

同一个过滤规则必须同时用于：

1. 普通 queued TaskRun 领取；
2. queued 且已请求取消的 TaskRun 收敛；
3. 显式 TaskRun ID 执行校验。

这样可以避免通用 worker 越权领取分钟线任务，也避免任一专用 worker误执行其他数据集。

### 3.3 工作流边界

当前工作流定义没有包含 `stk_mins` 或 `index_mins` 步骤，因此本期可以按直接 `dataset_action` 任务分流。

本期禁止把任一分钟线数据集加入工作流后，再期待工作流内部把步骤转交给专用 worker。工作流是一个整体 TaskRun，由领取它的 worker 在同一进程内执行全部步骤。

后续若要把分钟线加入工作流，必须另立“工作流跨车道拆分”方案；在此之前应增加架构测试，禁止工作流新增这两个数据集步骤，避免绕过分流规则。

## 4. 两个分钟线数据集的执行语义保持不变

新增进程不等于修改数据集的请求、计划或写入逻辑。

### 4.1 `stk_mins`

- 保持 `fetch_concurrency=2`。
- 只在专用 `stk_mins` 进程内并发 `DatasetSourceClient.fetch()`。
- normalize、writer、数据库事务提交、rollback、progress 仍由主线程串行执行。
- 保持现有 unit、请求参数、`page_limit=8000`、Tushare `500/min` 限速、writer、DAO 和 unit 事务边界。

### 4.2 `index_mins`

- 保持当前 `fetch_concurrency=1` 和现有串行行为。
- 不因为独立进程而新增指数分钟线内部并发。
- 保持现有指数池、频率扇出、时间窗口、分页、writer、DAO 和 unit 事务边界。

两个数据集都继续遵守：已提交 unit 不因后续 unit 失败而回滚，任务取消、失败、重试和进度语义不变。

## 5. 限速与资源边界

Tushare limiter 是进程内共享的，所以每条专用车道必须满足：

1. 生产最多运行一个 `stk_mins` 专用 worker。
2. 生产最多运行一个 `index_mins` 专用 worker。
3. 不通过启动多个同一车道进程扩大请求并发。
4. `stk_mins` 的两路 fetch 只存在于它自己的专用进程内。
5. `index_mins` 不新增进程内并发。

三进程仍共享 PostgreSQL CPU、磁盘 IO、连接数、主机 CPU/内存/网络和 Tushare 账号总配额。拆分车道不能隔离这些资源，因此必须观察数据库写入压力和源端限速。

## 6. 进程、命令与工厂

| 车道 | CLI 常驻命令 | CLI 单轮命令 | systemd unit | 工厂 |
| --- | --- | --- | --- | --- |
| 通用 | `goldenshare ops-worker-serve` | `goldenshare ops-worker-run` | `goldenshare-ops-worker.service` | `build_operations_worker()` |
| 股票分钟线 | `goldenshare ops-stk-mins-worker-serve` | `goldenshare ops-stk-mins-worker-run` | `goldenshare-ops-stk-mins-worker.service` | `build_stk_mins_worker()` |
| 指数分钟线 | `goldenshare ops-index-mins-worker-serve` | `goldenshare ops-index-mins-worker-run` | `goldenshare-ops-index-mins-worker.service` | `build_index_mins_worker()` |

单轮命令用于本地测试、发布验收和故障排查；生产使用 systemd 常驻命令。三个命令只增加消费车道选择，不新增运营侧配置项，不在前端展示。

## 7. 调度、自动任务与前端影响

本期不修改 scheduler。调度器仍然只负责：

```text
自动任务到期 -> 创建 queued TaskRun
```

之后由三个 worker 根据 TaskRun 事实分流。以下调用方不需要修改：

- 手动任务创建；
- 自动任务创建；
- 源站探测触发；
- 任务列表和详情；
- 取消任务；
- 失败重试；
- TaskRun 完成副作用 worker。

已有自动任务不需要重新创建。部署完成后，已有 queued 的两个分钟线任务会由对应专用 worker 领取。

## 8. 状态收敛策略

全局 stale TaskRun 收敛只由通用 worker 执行：

1. `stk_mins` 和 `index_mins` 专用 worker 不重复扫描全局运行中任务。
2. 通用 worker 即使暂时没有普通任务，也继续执行 stale reconciliation。
3. 任务完成通知和异步 snapshot 刷新仍由现有 completion worker 处理。
4. 任一专用 worker 只负责自己的 queued 任务，不改变其他任务的状态。

这样可以避免多个进程重复修改同一 TaskRun、重复创建 stale issue 或重复写入观测状态。

## 9. 代码与部署改动范围

计划修改：

| 文件/目录 | 内容 |
| --- | --- |
| `src/ops/runtime/worker.py` | 增加可配置消费车道过滤，覆盖领取、取消、显式执行 |
| `src/app/runtime/ops_worker_factory.py` | 明确通用车道并复用 dispatcher 装配 |
| `src/app/runtime/` | 新增两个分钟线 worker 工厂，复用同一 dispatcher 装配逻辑 |
| `src/app/runtime/__init__.py` | 导出两个专用工厂 |
| `src/cli.py` | 增加两个专用 worker 的 run/serve 命令 |
| `src/cli_parts/ops_handlers.py` | 增加两个专用 worker handler，复用现有消费循环 |
| `scripts/goldenshare-ops-stk-mins-worker.service` | 新增股票分钟线 unit |
| `scripts/goldenshare-ops-index-mins-worker.service` | 新增指数分钟线 unit |
| `scripts/deploy-layered-systemd.sh` | 同步两个 unit、enable/restart、状态输出 |
| `scripts/deploy-systemd.sh` | 更新帮助文案或服务说明 |
| `scripts/goldenshare-deploy.sudoers` | 增加两个 unit 的安装、enable、restart、status 权限 |
| `scripts/AGENTS.md` | 增加两个 unit 清单 |
| `tests/` | 增加三车道分流、CLI、部署脚本和工作流边界测试 |

明确不改：

- `DatasetDefinition`、`DatasetExecutionPlan`、planner、request builder；
- `stk_mins`/`index_mins` writer、DAO、raw 表和业务事务；
- scheduler 的任务创建逻辑；
- Ops API、前端页面和数据库迁移；
- Tushare 请求参数、限速值和数据集内部并发策略。

## 10. 开发里程碑

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| M0 | 复核 worker、dispatcher、TaskRun、部署链路和两个数据集边界 | CodeGraph 影响面与当前代码一致 |
| M1 | 实现三车道消费过滤 | 通用跳过两个分钟线，两个专用 worker 互不越权 |
| M2 | 接入两个专用工厂和 CLI | 两个单轮命令可测试，两个常驻命令可启动退出 |
| M3 | 接入 systemd 与部署链路 | 两个 unit 可同步、enable、restart、status |
| M4 | 补齐测试护栏 | 领取、取消、按 ID 执行、并发 claim、workflow 边界全部覆盖 |
| M5 | 本地和远程只读验收 | 三个服务状态正常，TaskRun 分流正确，无重复领取 |
| M6 | 生产观察 | 观察队列等待、分钟线耗时、Tushare 限速、DB 资源和其他任务启动延迟 |

当前进度：M0 复核、M1 车道过滤、M2 工厂与 CLI、M3 systemd/部署链路、M4 测试护栏及本地验证已完成；M5 远程只读验收与 M6 生产观察待部署窗口执行。

部署补充约束：若仅执行 `DEPLOY_OPS=1`，部署脚本也会重启通用 worker，使分钟线排除规则在当前进程中生效；否则旧通用 worker 可能继续领取分钟线任务。

## 11. 测试计划

必须覆盖：

1. 通用 worker 不领取 `stk_mins` 和 `index_mins`。
2. `stk_mins` worker 不领取 `index_mins` 或其他任务。
3. `index_mins` worker 不领取 `stk_mins` 或其他任务。
4. 三个 worker 同时竞争时，一个 TaskRun 只能被一个 worker claim。
5. 两个分钟线任务的 queued 取消请求由对应车道收敛。
6. 专用 worker 显式执行错误车道 TaskRun 时拒绝。
7. 通用 worker 显式执行两个分钟线 TaskRun 时拒绝。
8. 当前 workflow 不包含两个分钟线数据集，并增加防止后续误加入的测试。
9. 两个专用 worker 的 `--max-cycles 1` 命令能启动并退出。
10. 部署脚本会同步、enable、restart、展示两个新 service。
11. `DEPLOY_FOUNDATION=1` 或 `DEPLOY_OPS=1` 时两个专用 worker 都会重启；仅 `DEPLOY_PLATFORM=1` 时不会重启。
12. 既有 `stk_mins` fetch-only 并发测试继续通过；不在本专项把 `index_mins` 改成并发。

## 12. 部署与切换顺序

首次上线前必须只读确认：

1. 没有正在运行的 `stk_mins` 或 `index_mins` TaskRun，或当前任务已经自然完成。
2. 没有需要立即停止的长事务。
3. 通用 worker 当前服务状态正常。
4. 新 unit、CLI 和部署脚本已随同一版本发布。

推荐切换顺序：

```text
发布代码
  -> 同步两个新 systemd unit
  -> daemon-reload
  -> 确认两个分钟线任务没有运行中任务
  -> 启动/enable 两个专用 worker
  -> 重启通用 worker，使其加载排除规则
  -> 检查三个 worker 状态
  -> 检查 queued/running TaskRun 分流
```

如果部署时已有分钟线任务正在通用 worker 中执行，不应直接强制重启中断。应等待完成，或由运营明确允许中断后再切换。

## 13. 生产验收标准

| 验收项 | 标准 |
| --- | --- |
| 服务 | 通用、股票分钟线、指数分钟线三个 worker 均 active/running |
| 分流 | 两个分钟线数据集只能由各自专用 worker 领取 |
| 其他任务 | 通用 worker 可以在两个分钟线长任务期间继续领取其他任务 |
| 数据 | 两个数据集的 unit 数、请求参数、写入行数、reject 语义与改造前一致 |
| 并发 | `stk_mins` 仍为 2 路 fetch；`index_mins` 仍为串行 fetch |
| 限速 | 不出现因同一数据集多进程消费导致的新增 Tushare 限速错误 |
| 事务 | 不出现跨任务事务、重复提交或业务数据回滚 |
| 恢复 | 任一服务重启后，对应 queued 任务能继续被正确领取 |
| 其他任务延迟 | 不再因任一分钟线任务排队而等待数小时 |

## 14. 回滚方案

如果任一专用 worker 出现异常：

1. 停止对应专用 worker。
2. 暂停提交新的对应分钟线任务，或保持 queued 等待。
3. 将通用 worker 的消费范围恢复为全量。
4. 确认同一数据集只存在一个消费进程。
5. 已提交业务数据不回滚、不清表、不重建。

回滚不需要数据库迁移，也不需要修改已有 TaskRun 数据。

## 15. 已确认决策

### D1：部署触发范围（已确认）

只要满足以下任一条件：

```text
DEPLOY_FOUNDATION=1 或 DEPLOY_OPS=1
    -> enable + restart 两个分钟线专用 worker
```

### D2：首次切换窗口（已确认）

首次部署前等待当前 `stk_mins`/`index_mins` 任务自然完成，不在长任务中途重启通用 worker。若必须提前切换，需要运营另行明确允许中断当前任务。

当前没有其他待拍板的架构事项。

## 16. 审计记录

本次方案更新前已完成：

- CodeGraph 对 `OperationsWorker`、`run_next`、`build_operations_worker`、`TaskRunDispatcher`、CLI handler 和调用方的影响面分析；
- 本地 `stk_mins`/`index_mins` DatasetDefinition、unit planner、request builder、Executor 和 Tushare limiter 核验；
- `src/ops` 当前工作流定义检索，确认没有两个分钟线数据集步骤；
- 远程 prod worker 服务、TaskRun 和 `stk_mins` 长任务执行记录的只读核验。

已确认：

1. 现有 `stk_mins` 独立 worker 仍未实现，原方案已扩展为三车道一次性落地方案。
2. `index_mins` 当前与 `stk_mins` 共用通用 worker，独立进程可以只改消费分流，不改 ingestion 主链。
3. 三车道共用同一 TaskRun 主链，不引入新的任务事实源。
