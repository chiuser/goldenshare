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

当以上任一文件改动时，**必须**同步到服务器 `/etc/systemd/system` 并执行 `systemctl daemon-reload`，否则部署可能成功但服务启动失败（常见于 `ExecStart` 漂移）。

---

## 推荐流程

1. 先运行部署脚本 `--help` 与 shell 语法检查。
2. 审计当前服务器生效 unit（`systemctl cat ...`）。
3. 执行部署（含按需 unit 同步）。
4. 检查健康接口与服务状态。

---

## 权限最小化

若使用 `goldenshare` 用户部署，应在 sudoers 中仅放行：

1. `systemctl daemon-reload/restart/status`（三服务）
2. 三个 unit 模板到 `/etc/systemd/system` 的 `install -m 644`

不要给无边界的 root 命令白名单。

---

## 本地 Lake Console 脚本

`scripts/local-lake-console.sh` 只用于本地移动盘 Lake Console。

约束：

1. 不参与生产部署。
2. 不启动生产 web/worker/scheduler。
3. 不读取或写入远程 `goldenshare-db`。
4. 必须通过 `GOLDENSHARE_LAKE_ROOT` 指定本地移动盘 Lake 根目录。
