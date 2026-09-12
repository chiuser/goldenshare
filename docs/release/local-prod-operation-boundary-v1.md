# 本地与生产操作边界

更新时间：2026-09-12。本文区分执行地点、数据目标和授权；描述能力不等于允许代理自行启动、安装、迁移或写数据。适用于 Web/运营前端与 Prod 任务；DG/Lake 按自身目录规则，不套用这里的 Prod 部署流程。

## 1. 本地进程不等于本地数据

本地 Web 可以连接远程数据库。页面打开与只读查询不能作为点击同步、修改配置、提交任务或其他生产写入的授权；操作前确认环境文件与请求目标，不输出密码、Token 或完整连接串。

本地开发默认不启动连接 Prod 的长驻 worker/scheduler，不执行大范围数据维护、回补、结构性重建或未经计划的 DDL/清理。需要隔离测试环境时另行确认，不能把它与生产连接混用。

## 2. 本地启动与安装前提

[local-build-and-run.sh](/Users/congming/github/goldenshare/scripts/local-build-and-run.sh)默认编译后端、构建运营 frontend、启动 Web 和前端 dev；不是 Wealth 启动工具，也不会默认运行完整发版预检。

默认环境文件 .env.web.local，Web 127.0.0.1:8000，frontend 127.0.0.1:5173。调用当前 PATH 中的 python3/npm；执行前确认使用既有正确环境、端口及配置，避免覆盖其他进程。

**安装风险：即使不传安装选项，只要需要构建或启动 frontend 且 frontend/node_modules 不存在，脚本仍会自动 npm install。** 根 AGENTS 禁止未经批准安装；缺依赖时先停止并说明用途/范围，不能先运行再看结果。本轮未修脚本。

确认依赖已存在且获准启动后，才可执行 `bash scripts/local-build-and-run.sh`。其选项边界：

| 选项 | 作用 |
| --- | --- |
| --web-only | 不启动/构建 frontend，保留后端编译与 Web 启动 |
| --frontend-only | 不启动 Web、不编译后端，仍构建/启动 frontend |
| --skip-frontend-build | 仅跳过构建；frontend 仍默认启动，缺 node_modules 仍可能安装 |
| --with-preflight | 额外执行 release-preflight；测试与环境隔离需先确认 |
| --install-python-deps / --install-frontend-deps | 显式安装，必须事先获得管理员允许 |

INSTALL_PY_DEPS/INSTALL_FE_DEPS 环境变量也可触发安装；不能只检查命令行没有安装参数。进程由脚本持有 PID，退出时停止本次启动的进程；这不是 systemd 托管的生产部署。

如需手工启动，复用已核实的环境执行 `GOLDENSHARE_ENV_FILE=.env.web.local python3 -m src.app.web.run` 和 `npm --prefix frontend run dev`；同样先取得启动授权，不借手工命令绕过安装或写库限制。

## 3. 远程生产

生产服务由 systemd 托管。批准发布后使用 goldenshare 用户和受控权限，具体部署模式、九项服务范围、migration/seed/unit 副作用及验收统一见[正式发版流程](/Users/congming/github/goldenshare/docs/release/release-process-v1.md)，本文件不再复制命令链。

同步、回补、修复、状态重建和配置写入均按任务范围批准；“运行在生产服务器”不是无限写入许可。维护迁移模式不负责暂停或恢复服务；生产写入不能因本地 UI 验证而自动获准。

## 4. 最小工作顺序

明确目标环境与获准动作 → 核对依赖、配置和现有进程 → 执行必要开发/只读验证 → 按改动选择预检 → 获准后发布 → 核实实际 SHA、服务、接口与数据链。发布前预检与发布后验收不同，历史 HTML 中的运行状态也不能替代当次检查。
