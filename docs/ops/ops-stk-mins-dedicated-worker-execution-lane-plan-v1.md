# 分钟线任务执行隔离与运维说明

更新时间：2026-09-09。状态：现行代码说明，已合并原 LLD；历史生产验收结果待核实。保留原文件路径，不作为新一轮开发或部署授权。

## 1. 解决什么问题

股票历史分钟线 `stk_mins` 和指数历史分钟线 `index_mins` 各有独立 worker，避免长任务占住通用消费者，也避免两类分钟任务相互排队。本机制不承诺分钟任务自身提速，不隔离数据库、磁盘 IO、主机资源或源端账号配额。

分钟任务仍走 `ops.task_run -> OperationsWorker -> TaskRunDispatcher -> DatasetActionResolver -> IngestionExecutor`，不另建任务表、队列表、lane 数据库字段或第二套执行器。车道由任务类型和资源标识决定，不是页面输入；手动提交、自动调度和源站探测仍创建普通 TaskRun，不需要为分流重建已有 schedule。

本文只维护分钟线隔离细节。通用任务状态、进度、重试和事务观测见 [TaskRun 执行与观测契约](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)，完成后刷新、审计和通知见 [后处理 Worker 契约](/Users/congming/github/goldenshare/docs/ops/ops-task-completion-side-effect-worker-plan-v1.md)。

## 2. 当前车道与领取规则

[worker_lane.py](/Users/congming/github/goldenshare/src/ops/runtime/worker_lane.py) 当前定义四种车道；原“三车道”是分钟隔离项目当时的范围，不是当前全系统清单。

| 车道 | 当前允许的任务 |
| --- | --- |
| `general` | 排除 `qtf_experiment`，并排除 `dataset_action` 类型的 `stk_mins/index_mins`；其余任务进入通用车道 |
| `stk_mins` | 仅 `task_type=dataset_action AND resource_key=stk_mins` |
| `index_mins` | 仅 `task_type=dataset_action AND resource_key=index_mins` |
| `qtf` | 仅 `task_type=qtf_experiment`；本文不展开其执行和发布规则 |

`TaskRun.task_type` 为非空字段；`resource_key` 可以为空。通用 SQL 显式保留空 resource 的 workflow/maintenance 等任务，不能将规则简写为忽略 NULL 的 `NOT IN`。

[OperationsWorker](/Users/congming/github/goldenshare/src/ops/runtime/worker.py) 的五处校验保持一致：

1. `run_next` 先处理本车道仍为 queued 且已标记取消的记录，再按 `requested_at, id` 升序选择本车道未标记取消的 queued 任务。
2. `_claim_task_run` 以 ID、queued、未请求取消和车道条件执行原子 update；仅更新一行才提交 running 并执行。未领取成功则 rollback，普通轮询继续查找；显式执行返回冲突。
3. `_cancel_next_queued_task_run` 的选择、`_cancel_queued_task_run` 的 update 都带车道条件。
4. `run_task_run` 在确认任务存在且 queued 后、处理取消前校验车道；错误车道返回 409 / `worker_lane_mismatch`。显式 ID 不能绕过分流。

条件更新防止同一 queued TaskRun 被重复领取，但不等于限制同车道进程数，也不能证明两个不同 TaskRun 不会处理重叠数据。

当前 [workflow definitions](/Users/congming/github/goldenshare/src/ops/action_catalog.py) 不含这两个分钟数据集。workflow 作为一个整体 TaskRun 在领取它的进程内执行，不会把内部步骤转交给分钟 worker；现有 [架构护栏](/Users/congming/github/goldenshare/tests/architecture/test_worker_lane_guardrails.py) 检查步骤的 dataset_key。不得借 workflow 绕过车道；若要引入分钟步骤，应先另行设计跨车道执行并获准，而不是删除护栏。

## 3. 取消、状态与故障边界

正常 API 取消通过 [TaskRunCommandService.request_cancel](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)：

- queued 任务直接转 canceled，写入取消/结束时间及 `canceled_before_start`，不需要分钟 worker 在线。
- 运行中的任务转 canceling；执行器在自身检查点响应，不承诺立即中断底层请求。终态取消请求返回冲突。
- worker 仍处理 `queued + cancel_requested_at` 的记录。这条补充路径受车道限制，不是正常排队取消必须等待的路径。

常驻命令中，全局 stale 收敛由通用 worker 每轮消费前调用；两个分钟 worker 不调用它。通用 worker 空闲时仍轮询，但其执行长任务期间不能承诺按固定短间隔收敛。独立人工收敛 CLI 仍存在，不能把“只有通用常驻循环自动调用”写成“没有其他入口”。状态修正不是停止底层进程或恢复业务执行。

| 场景 | 影响与处理边界 |
| --- | --- |
| 某分钟 worker 停止 | 对应未执行任务等待，通用 worker 不接管；排队任务仍可经正常 API 取消。核实故障和运行状态后，按授权恢复对应服务 |
| 通用 worker 停止 | 通用任务消费和该常驻循环的 stale 收敛停止；不会因此禁止分钟 worker 领取任务 |
| 同车道重复进程 | 可能领取不同任务并扩大请求量，仍属部署错误；核实正在执行的任务后处理多余实例，不以原子 claim 作为多实例许可 |
| 执行进程中断 | 不自动把 running 重新入队；先核验业务提交、TaskRun 与节点状态，再决定后续处理，不能靠重启宣称已续跑 |

原“停止专用 worker，然后恢复通用 worker 全量领取”的回滚清单不再作为操作指南：当前没有这一 CLI/配置开关，回退代码还可能改变 QTF 和其他现行装配。确需版本回退须另行审核目标版本、全部车道、服务与数据库兼容边界；本说明不授权回退或恢复旧实现。保留已提交业务数据和已完成任务，不清表、不重建、不因消费进程故障回滚业务数据。

## 4. 数据执行与资源边界

| 数据集 | 当前执行边界与依据 |
| --- | --- |
| `stk_mins` | [定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)为 `fetch_concurrency=2`、`page_limit=8000`、unit 提交；两路仅用于源端 fetch。只有一个 unit 时走串行分支 |
| `index_mins` | [定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)沿用 [planning 默认值](/Users/congming/github/goldenshare/src/foundation/datasets/models.py) `fetch_concurrency=1`，保持串行 fetch、现有对象池/频率/窗口、分页和 unit 提交 |

[IngestionExecutor](/Users/congming/github/goldenshare/src/foundation/ingestion/executor.py) 的并发分支只把 `source_client.fetch` 交给线程池；归一化、写入、提交及进度处理仍在消费结果的主线程中执行。车道不修改请求参数、writer、DAO 或业务事务边界；已提交 unit 不因后续 unit 失败而回滚，观测写入不得回滚业务提交。

生产每种分钟车道最多一个 worker 实例；不要在常驻服务旁手动再运行同车道消费命令。这个限制是部署要求，不是代码实现了进程级单例锁。[Tushare limiter](/Users/congming/github/goldenshare/src/foundation/clients/tushare_client.py) 在进程内按 API 共享；当前代码限制 `stk_mins=500/min`、`idx_mins=100/min`，不是跨进程或账号全局配额保护，也不是本轮源站实测结论。

## 5. 工厂、CLI 与服务

工厂集中在 [ops_worker_factory.py](/Users/congming/github/goldenshare/src/app/runtime/ops_worker_factory.py)，通过 `_build_worker` 装配 dispatcher，再注入不同 lane。不复制旧工厂示例；现行装配还包含新闻、板块分析及按车道注册的外部执行器，不能照旧示例覆盖。

下表 CLI 均以 `goldenshare` 执行，服务模板均在 `scripts/`：

| 车道 | 单轮 / 常驻命令 | 服务 | 工厂 |
| --- | --- | --- | --- |
| 通用 | `ops-worker-run / ops-worker-serve` | `goldenshare-ops-worker.service` | `build_operations_worker` |
| 股票分钟 | `ops-stk-mins-worker-run / ops-stk-mins-worker-serve` | `goldenshare-ops-stk-mins-worker.service` | `build_stk_mins_worker` |
| 指数分钟 | `ops-index-mins-worker-run / ops-index-mins-worker-serve` | `goldenshare-ops-index-mins-worker.service` | `build_index_mins_worker` |

[CLI 定义](/Users/congming/github/goldenshare/src/cli.py)中，分钟 `*-run --limit` 默认 1、范围 1–1000；`*-serve` 的 limit 默认 10、同范围，sleep-seconds 默认 5 秒且至少 1 秒，max-cycles 默认不限制、指定时至少 1。分钟命令没有通用命令的 `--auto-reconcile-limit`。

**这些是实际消费命令，不是只读探针。** limit 是每轮处理的任务数，不是并发数；`--max-cycles 1` 也可能执行一个完整长任务，不能限制耗时或保证无写入。[handler](/Users/congming/github/goldenshare/src/cli_parts/ops_handlers.py) 每轮创建 Session 和对应 worker，依次消费至 limit 或无候选，输出 lane、任务 ID/终态及行数，关闭 Session；达到 max-cycles 后退出，否则 sleep。Session 不跨轮询周期，不能据此声称“每个任务独占一个 Session”。分钟摘要只输出本轮处理数，不把全局 queued/running 数冒充车道队列统计。

两个专用 unit 使用 `/opt/goldenshare/goldenshare` 为 WorkingDirectory，读取 `GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env`，由该目录的 `.venv/bin/goldenshare` 启动对应 serve，`Restart=always / RestartSec=3`。不在 unit 中另配数据库 URL、token 或数据集并发参数。

## 6. 部署与人工安全检查

**以下仅说明获准发布时的边界，不构成部署授权。** 默认服务名及同步权限见 [scripts 规则](/Users/congming/github/goldenshare/scripts/AGENTS.md)、[部署脚本](/Users/congming/github/goldenshare/scripts/deploy-layered-systemd.sh)和 [sudoers 模板](/Users/congming/github/goldenshare/scripts/goldenshare-deploy.sudoers)。分钟服务使用精确的 install、enable、restart、status 权限，不放开任意 root 命令；脚本缺权限时不得自动扩大授权。

原已确认的 D1 保留：有效 `DEPLOY_FOUNDATION=1` 或 `DEPLOY_OPS=1` 时，两种分钟 worker 都 enable + restart。下表只列本文涉及的相对顺序，其他服务仍按发布范围处理：

| 有效发布范围 | 当前脚本中相关 worker 的顺序 |
| --- | --- |
| 包含 Foundation | 通用 worker 先重启，之后股票分钟、指数分钟 worker 依次 enable/restart |
| Ops-only | 股票分钟、指数分钟 worker 依次 enable/restart，再重启通用 worker加载排除规则 |
| 仅 Platform | 不启用/重启这两个分钟 worker；不能据此推断不更新 unit，普通 unit 同步是独立步骤 |
| QTF-only / 维护迁移模式 | wrapper 将 Foundation/Ops 置零，不重启分钟 worker；各模式的其余边界见 scripts 规则 |

普通 unit 同步启用时，两个分钟模板变化会触发 daemon-reload；主发布流程非维护迁移模式还会 reload。不能声称任一发布只 reload 一次。同步代码或 unit 本身，不证明运行进程已加载新版本。

原已确认的 D2 保留：首次切换前等待两个分钟数据集正在运行的任务自然结束，不在长任务中途重启；必须中断时另获明确批准。当前脚本没有查询 TaskRun 并自动等待的机制，人工检查与后续重启之间也不是原子门禁。执行前必须结合当时任务、进程和提交状态确认窗口，不能仅凭下列查询一次为空就声称全程安全：

```sql
BEGIN READ ONLY;
SELECT id, task_type, resource_key, status, started_at, requested_at
FROM ops.task_run
WHERE task_type = 'dataset_action'
  AND resource_key IN ('stk_mins', 'index_mins')
  AND status IN ('running', 'canceling')
ORDER BY started_at, id;
COMMIT;
```

还需确认没有待处理的长事务、通用服务状态正常、代码与两个 unit 来自同一发布版本。发布后检查各服务实际状态、任务领取归属、是否出现重复消费者，以及普通任务是否仍被共享资源拖慢。后续常规发布也不能把自动 restart 当成已获准中断当前任务；本文不新增自动等待、停服、锁或重启功能。

## 7. 验证范围与历史记录

| 证据入口 | 能证明什么 / 不能证明什么 |
| --- | --- |
| [车道测试](/Users/congming/github/goldenshare/tests/test_worker_lane.py) | Python 匹配和 SQL 条件，包括 QTF 排除、空 resource；不是生产竞争验收 |
| [workflow 护栏](/Users/congming/github/goldenshare/tests/architecture/test_worker_lane_guardrails.py) | 当前定义中显式 dataset_key 不含两个分钟数据集；不是跨车道执行实现 |
| [模拟 CLI 测试](/Users/congming/github/goldenshare/tests/test_cli_ops_runtime.py) | 注册、工厂选择、输出和单轮退出，专用循环不调用全局收敛；没有启动真实 worker |
| [worker 集成测试](/Users/congming/github/goldenshare/tests/web/test_ops_runtime.py) | 领取、取消和显式执行的车道限制；现有双 worker claim 测试是在同一 Session 中顺序调用，不是多进程真实并发验证 |
| [部署测试](/Users/congming/github/goldenshare/tests/test_deploy_layered_systemd_script.py) | 分钟服务相关用例主要检查脚本文本、模板与权限条目；不能替代实际部署或进程状态验收 |

仅做文档治理时，使用现有环境进行无数据库的定向回归，不自动同步/安装依赖：

```bash
.venv/bin/python3 -B -m pytest -q -p no:cacheprovider tests/test_worker_lane.py tests/architecture/test_worker_lane_guardrails.py tests/test_cli_ops_runtime.py -k 'lane or minute_datasets'
bash -n scripts/deploy-layered-systemd.sh scripts/deploy-systemd.sh
.venv/bin/python3 -B scripts/check_docs_integrity.py
```

2026-09-09 本次审计的定向测试为 11 项通过、12 项未选中；文档完整性三个检查组和 Shell 语法检查通过。未运行数据库集成测试、真实并发竞争、Tushare 请求、部署或生产验收，不据此宣布线上已验收。未来若验收，应保留服务/分流/重复领取证据、两类分钟数据的 unit/请求/写入/reject 对账、源端限流和数据库资源观察，不能只看服务 active。

历史证据：2026-08-20 旧方案记录 TaskRun `8752` 处理 `29,430` 个 unit、耗时约 `298` 分钟，作为隔离动机，不是当前性能基线；当时 M0–M4 记录为代码与本地验证完成，M5 远程验收、M6 生产观察尚待执行。本次未核实之后是否完成，不重开旧里程碑，也不自动结案。旧方案和 LLD 全文可从合并前提交 `0a2fa759` 追溯，合并去向见 [治理记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-minute-lane-consolidation-20260909)。
