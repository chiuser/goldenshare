# 本地/生产双环境操作边界 v1

更新时间：2026-04-20

## 1. 目标

在同一套代码下，同时保证：

1. 本地可高效查看 UI 改动（连接远程数据库）。
2. 远程生产环境可稳定执行数据运营任务与部署。

## 2. 边界定义

### 2.1 本地环境（开发/验证）

允许：

1. 启动 Web 与前端：
   - 推荐一键：`bash scripts/local-build-and-run.sh`
   - 或手工分别启动：
     - `GOLDENSHARE_ENV_FILE=.env.web.local python3 -m src.app.web.run`
     - `cd frontend && npm run dev`
2. 页面交互验证、接口展示检查（以只读为主）。
3. 前端构建、单测、文档校验。

禁止：

1. 长驻消费/调度命令：
   - `goldenshare ops-worker-serve`
   - `goldenshare ops-scheduler-serve`
2. 大规模写库任务：
   - `sync-history`、`backfill-*`、批量 `sync-daily`
3. 未经计划的结构性数据库操作（DDL/大规模清理等）。

### 2.2 远程生产（运营/执行）

允许：

1. 一键部署：`bash scripts/deploy-systemd.sh dev-interface`
2. 调度与执行：
   - `goldenshare ops-scheduler-serve`
   - `goldenshare ops-worker-serve`
3. 数据运营任务（同步、回补、修复、健康度任务）。

要求：

1. 使用 `goldenshare` 用户执行部署。
2. 变更后检查服务状态：
   - `goldenshare-web.service`
   - `goldenshare-ops-worker.service`
   - `goldenshare-ops-scheduler.service`
3. 仅当 `scripts/goldenshare-*.service` 发生改动时，才同步 unit 文件到 `/etc/systemd/system`。

## 3. 发布前预检脚本说明

`scripts/release-preflight.sh` 是“手工预检脚本”，默认不会被 `deploy-systemd.sh` 或 `deploy-layered-systemd.sh` 自动调用。

建议时机：

1. 本地准备发版前手工执行一次：
   - `bash scripts/release-preflight.sh`
2. 预检通过后再执行远程部署。

## 4. 推荐流程（最小版）

1. 本地执行 `bash scripts/local-build-and-run.sh`，完成编译并启动 UI 验证。
2. 本地执行 `bash scripts/release-preflight.sh`。
3. 远程执行 `bash scripts/deploy-systemd.sh dev-interface`。
4. 检查三项 systemd 服务状态。
