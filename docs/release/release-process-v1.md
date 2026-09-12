# Goldenshare 正式发版流程

更新时间：2026-09-12，依据当前部署与预检脚本静态校准；未执行生产部署或验收。本文描述行为与操作边界，不构成安装、迁移、seed、重启或数据写入授权。

## 1. 版本、角色与授权

适用于业务主系统、运维系统的 systemd 发布。开发负责人准备提交、测试和变更说明；发布执行人核实环境与获准动作；验收人核对实际接口、页面和任务链。

- 按根 AGENTS 在当前 dev-interface 工作区开发，不再要求自行建功能分支或强制合 main。推送和发布均须明确授权。
- 发布记录必须包含目标分支、预期 SHA、远程拉取后的实际 SHA；不发布未提交本地修改。
- 统一入口 [deploy-systemd.sh](/Users/congming/github/goldenshare/scripts/deploy-systemd.sh) 转发到 [deploy-layered-systemd.sh](/Users/congming/github/goldenshare/scripts/deploy-layered-systemd.sh)。两者省略分支时仍默认 main；按现行流程必须显式传入批准的 dev-interface，不能把文档更新误当作脚本默认值已改。
- 使用 goldenshare 用户、受控 sudo/systemd 权限；默认远程仓库为 /opt/goldenshare/goldenshare，运行环境文件为 /etc/goldenshare/web.env。实际覆盖值、远程 origin 和镜像提交需当次核实，不依赖历史同步时长。

## 2. 发版前预检

在既有依赖环境、获准的测试范围内手工执行 `bash scripts/release-preflight.sh`。部署脚本不会自动调用它；本地启动脚本仅在指定 --with-preflight 时调用。

[预检脚本](/Users/congming/github/goldenshare/scripts/release-preflight.sh)的七个环境开关默认均为 1：

| 开关 | 当前检查 |
| --- | --- |
| RUN_COMPILE_CHECK | compileall：foundation/ops/biz/app/shared/scripts |
| RUN_LEGACY_COMPILE | 在编译开启时追加 platform/operations；不意味着旧实现恢复维护 |
| RUN_ENTRYPOINT_SMOKE | Web 运行入口 --help；不是启动服务或健康验收 |
| RUN_MINIMAL_TESTS | health_api、quote_api 两份测试 |
| RUN_WEB_TESTS | auth/admin/ops_overview/task_run/schedule/runtime 六份测试 |
| RUN_ARCH_TESTS | subsystem_dependency_matrix、virtual_split_boundaries 两份测试 |
| RUN_FRONTEND_BUILD | frontend 构建 |

关闭项必须记录原因和未验证范围。该脚本不是全量测试：没有运行 Wealth 构建、完整前端规则/单测/视觉回归，也不覆盖全部架构护栏或迁移验收。按实际改动补充[前端门禁](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md)及领域测试，不把“预检通过”当作全站通过。

本机不自动安装缺失依赖。编译/构建会生成本地文件，测试也须先确认环境隔离，不能把预检当纯只读脚本。

## 3. 发布动作与服务范围

获准的标准入口示例：`bash scripts/deploy-systemd.sh dev-interface`。这是远程发布命令，不在本机审计中试运行。

默认全量顺序：权限与运行环境检查、部署锁 → fetch/checkout/pull → pip 安装后端 → npm ci/build 构建 frontend 和 wealth → unit 差异同步 → init-db 迁移 → 按需 seed → daemon-reload → 服务重启 → 自检/健康/状态输出。普通发布没有在迁移前自动暂停 schedule 或停止现有服务，破坏性迁移必须走专项维护流程。

| 模式 | 默认服务重启范围 |
| --- | --- |
| 全量 | Web、通用 worker、scheduler、日期审计、完成后处理、股票分钟、指数分钟、QTF worker、realtime collector |
| --platform-only | Web |
| --foundation-only | 通用 worker、完成后处理、股票分钟、指数分钟 |
| --ops-only | scheduler、日期审计、完成后处理、股票分钟、指数分钟；同时重启通用 worker 加载分钟排除规则 |
| --qtf-only | QTF worker；不构建两前端、不 seed，只同步 QTF unit，强制迁移，跳过其他子系统与 Web 健康检查 |
| --maintenance-migration | 不同步 unit、不重启服务；见 §4 |

普通三个 *-only 默认关闭 QTF/realtime；--with-realtime 可显式带入 collector。**普通 *-only 不关闭构建、migration 或 seed，也不把 unit 同步限制成只同步要重启的服务。** QTF-only 和维护模式有独立强制分支；不混用多种模式或猜测参数组合效果。

服务名对应仓库 scripts 下的 unit：goldenshare-web、goldenshare-ops-worker、goldenshare-ops-scheduler、goldenshare-date-completeness-worker、goldenshare-ops-task-completion-worker、goldenshare-ops-stk-mins-worker、goldenshare-ops-index-mins-worker、goldenshare-qtf-worker、goldenshare-realtime-collector（均以 .service 结尾）。这是脚本管理清单，不是今日生产运行清单。

日期审计在 Ops 发布时 enable + restart；完成后处理和分钟 worker 在 Foundation/Ops 发布时 enable + restart；QTF/realtime 在对应启用时 enable + restart。Web、通用 worker、scheduler 的重启不等于脚本设置了自启。

其他重要开关：

- --skip-build 同时跳过两前端；--skip-wealth-build 仅跳过 Wealth。后端 pip 安装仍会执行。
- --skip-migration 关闭普通模式迁移；维护/QTF-only 强制开启迁移，不能以该开关声称跳过。
- 默认单源 seed 开启，source 默认 tushare；先预览，缺失时 --apply。--skip-seed-default-source 关闭。moneyflow 多源 seed 默认关闭，开启后也可能写入。
- unit 同步默认开启：与远程目标文件 cmp 比较，有差异才 install；不是检查 Git 是否修改过 unit。--skip-sync-units 不等于普通模式不执行 daemon-reload。
- --skip-realtime 关闭普通模式 collector；--with-dev-deps/--pip-install-target 改变安装范围，需纳入授权。
- 脚本环境变量还可覆盖动作与服务名。发布前记录有效模式、build/migration/seed/unit/restart 开关；不能只凭命令名称确认范围。

## 4. 维护迁移模式

在独立批准的维护窗口使用 `bash scripts/deploy-systemd.sh dev-interface --maintenance-migration`：

该模式固定关闭前端/Wealth 构建、默认规则 seed、moneyflow seed、systemd unit 同步以及 Foundation、Ops、Platform、Realtime、QTF 服务重启，并强制执行 migration；迁移后只运行 Foundation 资源加载自检，不执行 Ops 状态协调、Web 健康检查或服务状态读取，确保服务保持调用前状态。它**不负责**暂停自动任务、停止服务或恢复服务；执行前仍必须由维护流程完成 schedule 暂停、worker/scheduler 停止、开放 TaskRun/锁/长事务检查，执行后再独立完成连接池回收、服务恢复和验收。禁止再用一长串临时环境变量手工拼出同一模式，也禁止把该模式当成完整发版或恢复服务命令。

维护模式的配置审计固定如下：

| 配置 | 默认值与来源 | 持久化/范围 | 消费者与依赖 | 生效与可见性 | 测试门禁 |
| --- | --- | --- | --- | --- | --- |
| `MAINTENANCE_MIGRATION_MODE` | 默认 `0`；只由 `deploy-systemd.sh --maintenance-migration` 在当前进程导出为 `1`，运营不直接维护该变量 | 不持久化，仅本次部署子进程 | `deploy-layered-systemd.sh`；依赖 wrapper 同时把所有 deploy/build/seed/unit 开关固定为安全值，且与 `--qtf-only` 互斥 | 立即生效；日志明确显示保持 systemd 状态并跳过 Ops/健康/状态步骤 | `tests/test_deploy_layered_systemd_script.py` 固化全部关闭项、migration 开启项、互斥关系和 layered 消费分支 |


## 5. 发布后验收

1. 核对实际部署 SHA、迁移结果、seed 是否写入、unit 是否同步、哪些服务确实被重启。
2. 普通发布检查 /api/health 与 /api/v1/health；QTF-only 和维护模式不能据脚本结束宣称 Web 已验收。
3. 对受影响服务独立检查 active/enabled 和日志。当前 print_service_status 对失败也返回成功，因此“分层发版完成”不证明所有服务 active。
4. 核对登录、受保护接口和权限错误；按实际改动验证页面/任务链，而非只看健康 HTTP 200。
5. Quote 专题按[现行 API 合同](/Users/congming/github/goldenshare/docs/platform/quote-detail-api-spec-v1.md)与测试验证 page-init、kline、related-info、announcements、交易日历及错误语义，不在发布文档复制可能漂移的周期/复权限制。Wealth/Ops/QTF 分别补受影响合同验收。
6. 记录未检查项、失败和后续恢复，不把本轮文档静态核对当作生产验收。

## 6. 回退与失败处理

健康连续失败、核心接口不可用、严重数据或权限风险时，先记录失败 SHA、动作进度与影响，停止盲目重试，确定获准的恢复方案。

**现有脚本不提供固定旧 SHA 的回滚模式。** 它会 fetch、checkout 分支、pull origin 分支；手工切旧 SHA 后再无参数重跑会回到 main 流程，传 SHA 也不等于能从 origin 同名分支拉取。不得照旧文档“切 SHA → 重跑部署”操作。

恢复前分别确认代码、依赖/构建产物、数据库 schema/数据、配置和 unit 是否兼容。代码回退不自动撤销 migration、seed 或业务写入；不擅自 downgrade、清表或重建数据。明确目标版本及可执行恢复步骤、所需停服/恢复与验证，经批准后再执行。本轮仅撤销错误指令，不实现新回滚工具。

发布记录至少包括时间、执行人与验收人、目标分支/预期及实际 SHA、授权范围、预检与跳过项、实际副作用、验收、是否恢复及剩余风险。

## 7. 文档与脚本边界

[本地/生产边界](/Users/congming/github/goldenshare/docs/release/local-prod-operation-boundary-v1.md)维护环境与安装授权；[部署历史审计](/Users/congming/github/goldenshare/docs/release/remote-server-deployment-overview-v1.html)保留带日期的主机证据。脚本默认 main、非固定 SHA 回退、普通模式广泛副作用及状态打印非门禁是已识别的使用限制，不因文档修改自动启动脚本重构。
