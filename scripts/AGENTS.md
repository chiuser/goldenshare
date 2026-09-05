# AGENTS.md — `scripts/` 部署脚本规则

## 适用范围

本文件适用于 `scripts/` 目录及其子目录。

---

## 核心原则

1. 部署脚本变更必须保持“可回滚、可观察、最小权限”。
2. 任何会影响生产启动链路的改动，必须先做只读审计再执行。
3. 不允许在脚本里引入不必要的破坏性动作（如清空目录、重置仓库）。

---

## Unit 文件同步（强提醒）

以下文件属于 systemd unit 模板：

1. `scripts/goldenshare-web.service`
2. `scripts/goldenshare-ops-worker.service`
3. `scripts/goldenshare-ops-scheduler.service`
4. `scripts/goldenshare-date-completeness-worker.service`
5. `scripts/goldenshare-ops-task-completion-worker.service`
6. `scripts/goldenshare-ops-stk-mins-worker.service`
7. `scripts/goldenshare-ops-index-mins-worker.service`
8. `scripts/goldenshare-realtime-collector.service`

当以上任一文件改动时，**必须**同步到服务器 `/etc/systemd/system` 并执行 `systemctl daemon-reload`，否则部署可能成功但服务启动失败（常见于 `ExecStart` 漂移）。

---

## 推荐流程

1. 先运行部署脚本 `--help` 与 shell 语法检查。
2. 审计当前服务器生效 unit（`systemctl cat ...`）。
3. 执行部署（含按需 unit 同步）。
4. 检查健康接口与服务状态。

分层部署约束：

1. `--platform-only` / `--ops-only` / `--foundation-only` 默认不处理 `goldenshare-realtime-collector.service`。
2. `goldenshare-date-completeness-worker.service` 只要 `DEPLOY_OPS=1` 就必须 enable + restart。
3. `goldenshare-ops-task-completion-worker.service` 只要 `DEPLOY_FOUNDATION=1` 或 `DEPLOY_OPS=1` 就必须 enable + restart。
4. `goldenshare-ops-stk-mins-worker.service` 和 `goldenshare-ops-index-mins-worker.service` 只要 `DEPLOY_FOUNDATION=1` 或 `DEPLOY_OPS=1` 就必须 enable + restart。
5. 需要在非全量部署中同时处理实时采集服务时，必须显式传 `--with-realtime`。
6. 全量部署默认处理实时采集服务；如需跳过，显式传 `--skip-realtime`。

---

## 权限最小化

若使用 `goldenshare` 用户部署，应在 sudoers 中仅放行：

1. `systemctl daemon-reload/restart/status`（受部署脚本管理的服务）
2. `systemctl enable goldenshare-date-completeness-worker.service`（日期完整性审计 worker 是常驻服务，必须开机自启动）
3. `systemctl enable goldenshare-ops-task-completion-worker.service`（TaskRun 完成副作用 worker 是常驻服务，必须开机自启动）
4. `systemctl enable goldenshare-ops-stk-mins-worker.service` 和 `systemctl enable goldenshare-ops-index-mins-worker.service`（分钟线专用 worker 是常驻服务，必须开机自启动）
5. `systemctl enable goldenshare-realtime-collector.service`（实时 collector 是常驻服务，必须开机自启动）
6. 受部署脚本管理的 unit 模板到 `/etc/systemd/system` 的 `install -m 644`

不要给无边界的 root 命令白名单。

---

## 数据湖工具边界

旧 Console 联合启动脚本已在 M6 删除，不得恢复或用新入口包装旧后台。
正式维护入口位于 `lake_console/orchestrator`；Lake 根以其 paths.py 为准，不使用旧 Console 配置。
保留 `lake_console/bin/lake-clickhouse-start` 和 `lake_console/bin/lake-prod-clickhouse-tunnel`；
两者执行会改变服务或连接状态，静态审计只能做语法检查，不能把启动脚本当只读探针。
