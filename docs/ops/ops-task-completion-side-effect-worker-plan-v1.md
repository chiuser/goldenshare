# Ops 任务完成后处理 Worker 运行契约

- 校准日期：2026-09-09。
- 性质：当前代码、配置与部署入口说明；不是部署指令或生产验收报告。
- 历史状态：2026-05-30 原方案记录本地实现完成、待部署验收。本轮确认实现仍在，未据此断言服务当前已运行或仍未部署。
- 与 [TaskRun 主契约](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md) 分工：本文只描述任务终态后的后处理，不重复任务模型、API 或页面 ETA。

## 1. 为什么独立运行

主任务 Worker 负责业务执行与 TaskRun 终态提交，随后可以领取下一任务；完成 Worker 扫描已结束的 TaskRun，执行以下后处理：

1. 刷新关联数据集状态投影。
2. 符合条件时创建 index_daily 日期完整性审计。
3. 尝试发送飞书完成通知。

主任务当前已经不再同步刷新 snapshot；旧文中的“主 Worker 仍被同步刷新阻塞”是拆分前背景。后处理不改变原任务成败，不为通知失败写 TaskRun issue，不应回滚已经提交的业务数据。

入口与实现：`src/cli.py` → `src/cli_parts/ops_handlers.py` → `src/ops/runtime/task_completion_worker.py`；查询、摘要和触发策略在 `src/ops/services/task_run_completion_service.py`，消息在 `src/ops/services/feishu_task_notification_service.py`。

## 2. 扫描、游标与失败边界

- 扫描 TaskRun，而不是 node。终态范围 success/partial_success/failed/canceled，且 ended_at 非空；Workflow 按整个任务处理一次，不按步骤通知。
- 第一次 run_cycle 只把内存游标初始化到当前最新终态 `(ended_at, id)`，返回 0，不执行后处理。没有历史终态时用空游标。
- 后续按 `ended_at ASC, id ASC` 取游标后的有限批次；每个任务处理函数正常返回后推进游标。
- 不新增 outbox、通知表或持久化确认，不回放启动前历史，不提供自动失败重试或 exactly-once 保证；重启后重新定位最新终态，停机期间的后处理可能被跳过。
- 一个任务内三项操作串行，任务之间也串行。慢 snapshot 刷新不会占住主任务 Worker，但会延迟本 Worker 的审计创建、通知和后续任务；不能写成“只延迟 snapshot”。
- snapshot、审计创建、发送通知各有异常捕获并记日志；审计创建异常还回滚其 Session。正常返回后即使其中某项失败，也推进游标，不自动补发。
- **摘要构建位于上述 try/catch 之外**；批次查询、摘要构建等异常可能逃出 run_cycle，游标尚未推进。CLI 外层没有统一捕获，进程可能退出。不能承诺“任何异常都继续处理后续任务”；systemd 重启也不等于补做遗漏后处理。

因此“不补历史”的边界影响通知、状态投影刷新和审计创建三者。要求可靠重放或独立并发时需另立方案，本轮不改变已接受的轻量 Worker 设计。

## 3. 三项后处理的实际范围

### 3.1 状态投影

dataset_action 根据 resource_key/action 解析正式动作；workflow 根据 request_payload.target_key 解析目标；目标无效、缺失或其他任务类型不刷新。maintenance_action 不能直接当成可刷新目标。

刷新在独立 Session 中调用 `DatasetStatusSnapshotService.refresh_for_target(strict=False)`，不使用业务执行事务。投影本身的策略和页面回退限制见 [Freshness 现行契约](/Users/congming/github/goldenshare/docs/ops/ops-freshness-policy-explicit-mapping-plan-v1.md)。`ops.dataset_status_snapshot` 必须保留，不属于 Kopia 清退对象。

### 3.2 index_daily 完成审计

须同时满足以下条件才创建审计，并非所有任务结束都触发：

- task_type=dataset_action、resource_key=index_daily、action=maintain、status=success。
- request_payload.run_scope 不是 `index_daily_gap_repair`，避免修复任务再次触发同一链路。
- time_input.mode=point 且 trade_date 可解析；该日期等于**后处理时**上海时区的当天，不只是任务开始或完成的日期。
- 配置的 default_exchange 在本地交易日历对应日期明确 is_open=True。
- 同日不存在 queued/running 的 index_daily、date_subject_matrix 审计。

满足条件后调用 DateCompletenessRunCommandService.create_system_run 写入系统审计请求；这里只创建，不在完成 Worker 内执行完整审计。不覆盖历史区间、Workflow 或补缺修复任务，也不承诺并发进程间的严格去重。

### 3.3 飞书通知

- 由开关控制；启用但 webhook URL 或 secret 缺失时记警告并跳过。
- 使用带签名的富文本 `post`，不是 interactive card。签名以 timestamp、换行、secret 组成的字节串作 HMAC-SHA256 key，对空消息求摘要后 Base64；实际实现及回归见通知 service/test。
- 摘要含任务 ID/名称、类型、状态、触发来源、时间范围、耗时、成功 unit 数/总数、读取/写入/拒绝数；失败原因只对 failed/partial_success 加入。摘要是服务对原始字段的展示映射，不等于 API 字段全集。
- 问题摘要优先 operator_message，其次 title/technical_message，上限 500 字符；整段文本上限 3,500 字符。配置 public base URL 后追加 `/app/ops/tasks/{id}` 链接，但当前是追加后整体截断，不能保证超长文本仍保留链接。
- 不发送完整技术 payload、token、请求头或敏感配置。HTTP/业务返回失败抛给 Worker 记录日志，不改变业务任务结果。

## 4. 配置、来源与生效

配置定义在 `src/foundation/config/settings.py`，使用既有 Settings/environment 机制；通知 service 缓存构造时的 Settings，不承诺热更新。正式服务通过 GOLDENSHARE_ENV_FILE 指向 `/etc/goldenshare/web.env`；配置管理入口为 `scripts/remote-web-env.sh`。变更配置、生效重启及密钥设置均需独立授权，本文不含真实密钥。

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| OPS_TASK_COMPLETION_WORKER_POLL_SECONDS | 5 | 每轮后休眠秒数 |
| OPS_TASK_COMPLETION_WORKER_BATCH_SIZE | 20 | 每轮扫描数量上限 |
| OPS_TASK_NOTIFY_FEISHU_ENABLED | false | 是否尝试通知 |
| GOLDENSHARE_FEISHU_WEBHOOK_URL | 空 | 飞书入口；启用通知时需要 |
| GOLDENSHARE_FEISHU_WEBHOOK_SECRET | 空 | 签名密钥；启用通知时需要 |
| OPS_TASK_NOTIFY_TIMEOUT_SECONDS | 5 | 通知 HTTP 超时秒数 |
| OPS_PUBLIC_BASE_URL | 空 | 任务详情链接前缀；为空不加链接 |

这些是配置默认值，不是本机或生产当前有效值。本轮未读取密钥文件，也未修改设置。

## 5. CLI 与部署入口

CLI：`goldenshare ops-task-completion-worker-serve`。

- `--batch-size`：默认 20，CLI 限制 1..1000。
- `--sleep-seconds`：默认 5，至少 1。
- `--max-cycles`：默认无限循环，指定时至少 1。**真实 Worker 的 --max-cycles 1 只验证游标初始化，不能验证刷新、审计或通知。**
- CLI 默认值来自 Settings；每轮开新 Session，但同一进程复用 Worker 的内存游标。
- 本地验证只能在明确的隔离测试环境中有限运行；连接正式数据库后该命令可能写状态投影、创建审计、发送通知，绝不是只读探测。使用现有环境，不借测试隐式安装依赖。

部署单元为 `scripts/goldenshare-ops-task-completion-worker.service`：

| 项目 | 仓库定义 |
| --- | --- |
| 工作目录 | /opt/goldenshare/goldenshare |
| 配置入口 | GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env |
| 进程 | /opt/goldenshare/goldenshare/.venv/bin/goldenshare ops-task-completion-worker-serve |
| 重启策略 | Restart=always；RestartSec=3 |
| 安装目标 | multi-user.target |

`scripts/deploy-layered-systemd.sh` 负责同步 unit；Foundation 或 Ops 发布分支会启用/重启该服务，仅 Platform 发布不会。因此不能把任意一次分层部署都当成此 Worker 已部署的证明，也不能把脚本中条件步骤写成无条件执行。本文不执行部署、重启或通知测试。

## 6. 回归与验收边界

既有测试入口：

- `tests/web/test_ops_task_completion_worker.py`：首次启动不补历史、终态顺序、刷新/通知异常隔离、index_daily 审计触发及修复任务排除。
- `tests/test_feishu_task_notification_service.py`：签名、消息构造、缺 secret 跳过及业务失败。
- `tests/test_cli_ops_runtime.py`：有限循环和参数传递；其中替身返回处理数量，不替代真实首次循环行为验证。
- `tests/web/test_ops_runtime.py`：主任务不再同步刷新 snapshot 的防回退。

正式运行验收仍需独立授权和证据：先确认服务/有效配置，再观察**初始化以后**新结束的任务，核对三项适用后处理、失败日志及主任务可继续执行；不得为验收回放历史、擅自触发真实通知或增加生产任务。历史“待部署”不自动关闭，也不作为今天必须重新部署的理由。

本轮仅核对源码、测试定义、CLI 和 unit 文件，未执行 Worker、数据库回归、部署或网络通知。已知局限保留在 §2–3；信息去向见 [本批治理记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-taskrun-consolidation-20260909)。
