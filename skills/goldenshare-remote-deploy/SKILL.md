---
name: "远程部署技能"
description: "Use when the user asks to deploy, restart, or verify Goldenshare services on the remote production server."
---

# 远程发布与验收

## 执行前

阅读仓库根 AGENTS、AGENTS.local.md、scripts/AGENTS.md，以及：
- [正式发版流程](/Users/congming/github/goldenshare/docs/release/release-process-v1.md)：模式、副作用、服务矩阵、验收与恢复。
- [统一入口](/Users/congming/github/goldenshare/scripts/deploy-systemd.sh)和[分层脚本](/Users/congming/github/goldenshare/scripts/deploy-layered-systemd.sh)：核对实际执行分支。

确认请求是发布、单独重启还是只读检查，不把后两者扩大为全量部署。默认 SSH alias 为 goldenshare-prod，仓库为 /opt/goldenshare/goldenshare；当次核实目标分支、预期 SHA、远程实际 SHA、权限和配置覆盖值，不输出凭据。

## 获准发布

发布使用 goldenshare 用户。只有全量发布及其安装、构建、迁移、seed、unit 同步和服务重启范围获准后，才使用：

```bash
ssh goldenshare-prod 'sudo -n -u goldenshare /bin/bash -lc "cd /opt/goldenshare/goldenshare && bash scripts/deploy-systemd.sh dev-interface"'
```

脚本省略分支仍默认 main，必须显式传批准分支。分层、QTF-only、维护迁移按正式流程选择，不自行拼装开关。普通 *-only 不代表只重启一个服务、也不代表跳过安装/迁移/seed。

发布前按获准测试范围完成预检；部署脚本不自动执行 release-preflight。unit 差异同步和 daemon-reload 仅在批准发布范围执行，不能因模板变更或提交代码就同步生产。

## 验收与只读模式

**不再把 Web、通用 worker、scheduler 三项当作全部服务。** 当前脚本管理九类服务：Web、通用 worker、scheduler、日期审计、完成后处理、股票分钟、指数分钟、QTF worker、realtime collector。精确名称与模式矩阵只在正式发版流程和 scripts/AGENTS 维护；这是脚本管理范围，不是已核实的生产运行清单。

按本次有效配置列清应检查的服务及排除理由，逐项记录 active/enabled、实际 unit/ExecStart 和必要日志；不要用短路命令让第一项失败掩盖后续服务状态。脚本状态打印失败仍可能返回成功，退出码不能替代独立验收。

- 普通发布核对 /api/health、/api/v1/health，并补受影响页面/API/任务链；健康响应不等于业务验收。
- QTF-only 和维护迁移不据脚本结束声称 Web 已验证；维护模式不自动恢复服务。
- “只检查/只验收”仅执行获准的远程只读状态、unit、日志和健康查询，不 pull/install/restart/enable/reload，不运行部署脚本。
- 单独重启只处理批准的服务，不调用全量发布替代重启。

## 失败与交付

权限不足先核对受控 sudo 白名单，不自动修改 sudoers；unit 不符先核对源模板与生效配置，不盲目重启。失败时记录实际 SHA、已完成动作及影响，按正式流程取得恢复授权；不得把切旧 SHA 后重跑部署当作可靠回滚。

报告目标/实际 SHA、模式与实际副作用、逐服务结果、unit 与健康/业务检查、失败和未验证项。保留 goldenshare 用户和非交互受控 sudo 边界，不修改无关服务。
