# Goldenshare 正式发版流程

更新时间：2026-11-12。原发布边界保留；独立技术指标包漏更新的修复及隔离验证已完成，方案、LLD 与结果见 §8，尚未提交或部署。本文描述行为与操作边界，不构成安装、迁移、seed、重启或数据写入授权。

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

默认全量顺序：权限与运行环境检查、部署锁 → fetch/checkout/pull → pip 显式安装仓库技术指标包及主工程、检查实际配置 → npm ci/build 构建 frontend 和 wealth → unit 差异同步 → init-db 迁移 → 按需 seed → daemon-reload → 服务重启 → 自检/健康/状态输出。普通发布没有在迁移前自动暂停 schedule 或停止现有服务，破坏性迁移必须走专项维护流程。

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

## 8. 一键部署同步更新技术指标包：方案与 LLD（2026-11-12）

### 8.1 问题、目标与依据

本日只读检查 Prod：仓库已更新到 `f858a6e70`，但 `.venv` 实际加载的 `goldenshare-technical-indicators==0.1.0` 仍是旧安装副本。该副本 `KernelConfig` 要求 `max_output_bytes`，而先前提交 `a74374cc3` 已从仓库主工程 Settings 和包源码删除此字段；旧副本配置文件的 SHA256 与该提交之前的文件一致。Web 在启动配置转换时抛出 `AttributeError: technical_indicator_max_output_bytes`，退出并被 systemd 重启，最终表现为健康检查超时。这是带日期的审计证据，不代表后续服务状态。

现有 `deploy-layered-systemd.sh` 第 2 步只执行 `pip install -e "${PIP_INSTALL_TARGET}"`；主工程把独立包依赖固定为 `0.1.0`，已有副本满足版本条件并不能证明内容已更新。`[tool.uv.sources]` 不是该 pip 命令显式安装本地包的依据。本地 `local-build-and-run.sh` 的显式安装选项已经同时指定独立包和主工程，无需修改该入口。

目标是保持管理员原有一条命令 `bash scripts/deploy-systemd.sh dev-interface`，每次部署安装本次仓库里的技术指标包，并在数据库迁移、前端构建、unit 同步和服务重启前验证实际加载的配置。沿用现有 `.venv`、授权和服务选择，不新增安装开关、版本兼容分支、后台任务或回退机制；不修改技术指标计算、配置合同、每日指标补录或 DG。

开工前已阅读两个部署脚本、包与主工程的 pyproject、配置转换、Web lifespan 及现有脚本测试。CodeGraph `explore(technical_indicator_config_from_settings)` 核对配置函数及其调用方；本次仅复用该函数，不修改下层依赖或消费者。pip 普通目录安装的依据为 [官方本地工程安装文档](https://pip.pypa.io/en/stable/topics/local-project-installs/)。

### 8.2 实现位置、配置与执行顺序

只修改 `scripts/deploy-layered-systemd.sh`、`tests/test_deploy_layered_systemd_script.py` 和本文件。统一 wrapper `deploy-systemd.sh` 的参数解析不变。

| 硬口径 | 实现与验收 |
| --- | --- |
| 一次部署同时显式安装独立包和主工程 | 第 2 步改为 `.venv/bin/pip install ./packages/technical_indicators -e "${PIP_INSTALL_TARGET}"`。独立包使用普通目录安装；保留主工程现有 editable 和 extras/自定义目标语义。不依赖人工先安装包或变更版本号，不额外升级整个环境 |
| 所有现有部署模式都经过安装和检查 | 安装及检查位于所有模式共用的前端构建之前。覆盖全量、Platform-only、Ops-only、Foundation-only、QTF-only、维护迁移，以及原 `--with-dev-deps` 参数传递；服务重启和维护边界不变 |
| 检查真实配置，不启动业务运行 | 新 shell 函数以 `.venv/bin/python -` 执行内嵌 Python，先打印包版本和 `__file__`，再调用现有 `technical_indicator_config_from_settings(get_settings())`。不打印 Settings 或连接串，不创建 runtime，不调用 Web lifespan，不查数据库或 Lake |
| 检查使用本次指定的环境文件 | 仅对检查子进程设置 `GOLDENSHARE_ENV_FILE="${ENV_FILE}"`；由原 `get_settings()` 读取文件。不提前 source 文件到父 shell，不改变后续 load_runtime_env 的现有顺序 |
| 安装或检查失败就停止 | 沿用 `set -Eeuo pipefail`，不捕获或吞掉原异常。不进入后续构建、迁移、seed、unit 同步或服务重启。旧包要求已删除字段时必须在此出现同样的 AttributeError，不能给字段补默认值来通过 |

配置只复用现有 `PIP_INSTALL_TARGET` 与 `ENV_FILE`：前者默认 `.`、由 wrapper 的 `--with-dev-deps`/`--pip-install-target` 或现有环境覆盖，只供本次 pip 使用；后者默认 `/etc/goldenshare/web.env`，既有文件预检和后续环境加载继续保留，新消费者仅为检查子进程。没有新增持久化配置或改变生效范围。

失败与续跑继续使用原入口：安装可能在失败前更新部分依赖，不能声称有原子回退；修正原因后重跑同一条命令，重新显式安装两个目标并执行配置检查。中断不新增 checkpoint，不自动重试或重启服务。原地拉代码和安装对已运行进程的影响仍属原部署边界，不承诺失败时旧服务完全不受影响。

### 8.3 性能与验证范围

每次仍只有一次 pip 调用，增加一个明确的本地目录目标；包的构建、依赖解析和网络耗时取决于既有环境，尚无生产实测，不填写任意时限。新增检查只有一个 Python 子进程、包导入与一次配置转换；当前配置为 17 项技术指标字段及 Lake 路径，数量来自当前 `KernelConfig`。检查不执行 SQL、源请求、文件数据扫描或计算任务。失败重跑重新执行安装与该检查；最终验收复用原两个健康接口，不追加批量业务读取。

开发验收先补脚本执行回归，在临时目录使用 git/pip/systemd 等替身，断言安装参数、实际配置检查及先后顺序；替身不代替真实安装或生产验收。配置检查子进程使用真实主工程转换函数和已安装包；旧包反例只替换配置合同，保留本日真实缺字段错误。设置非默认环境文件，验证没有读取被继承的另一文件。

另用已有 Python/pip/setuptools/wheel 做有界、离线的真实目录安装 dry-run，确认已存在同版本包时本地目录仍在安装计划中，并构建 wheel 核对当前配置与 SQL 包文件。所有构建输入副本、缓存、报告和测试临时资源放 `/private/tmp`；不安装或升级本机现有依赖。只读 dry-run 不算实际安装成功，脚本替身通过也不算 Prod 已恢复。若既有工具无法完成某项真实验证，记录具体缺项，不自动安装工具。

验收同时执行原部署脚本回归、shell 语法/入口帮助、文档完整性和差异检查。正式恢复须在本修订提交、推送后，由管理员执行原一键命令，再核验实际包、服务和健康接口。本轮授权不包含提交、推送、生产安装或重启。

### 8.4 实现与验证结果

已落实 §8.2：产品代码只增加配置检查函数，并替换一条安装命令、紧接着调用检查。源码对照确认其余部署和服务选择代码与修改前逐字相同；没有改 wrapper、本地启动入口、包源码或业务配置。CodeGraph 已核对配置消费者并同步索引。

| 验收 | 结果及边界 |
| --- | --- |
| 部署脚本回归 | 去重 24 项通过，包含 13 项原测试及 11 项新增执行用例。实际运行两个脚本，验证全量及五种限定模式、两个原有安装目标参数、安装失败、旧包缺字段和非法配置。git/pip/systemd/npm/curl 为隔离替身，配置转换为真实代码；不代表已做生产安装 |
| 修复前反例 | 将修改前脚本复制到临时目录，旧包场景仍继续重启，新失败停止测试按预期不通过；修改后在真实配置函数处报告原 AttributeError 并停止后续动作 |
| 真实同版本目录安装计划 | 已有包为 `0.1.0`。既有 pip 25.1 离线 dry-run：只传 `==0.1.0` 显示已满足且无安装项；传临时源码目录则生成 `0.1.0` 安装项。不使用 ignore-installed/force-reinstall；没有实际安装依赖 |
| 真实构建及配置转换 | 使用既有 Python 3.13.5、setuptools 78.1.1、wheel 0.45.1 离线构建，wheel 内 55 个 Python/SQL 文件逐个与源码一致；新进程直接加载该临时 wheel，真实 Settings → KernelConfig 转换成功，无已删除字节字段。不把此项称为生产启动验收 |
| 静态检查 | 两个 shell 脚本语法、原入口帮助、变更测试 Ruff、文档完整性和差异检查通过 |

第一轮为 23 项通过、1 项新增断言失败：非法配置的报错实际使用 Settings 已声明的环境变量别名 `TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS`，测试错误地期待内部小写属性名。依据真实 schema 和报错修正该断言后，仅补跑此用例通过，没有修改产品代码或放宽配置校验。

本修订提交、推送后，首次使用须先让服务器读到新脚本。在已核对的 Prod `dev-interface` 工作目录，以一条 shell 命令执行：

```bash
git pull --ff-only origin dev-interface && bash scripts/deploy-systemd.sh dev-interface
```

原因是已经启动的旧脚本，其 main 函数不会因中途拉取新文件自动改成新逻辑。首次加载本修订后，后续仍使用原命令 `bash scripts/deploy-systemd.sh dev-interface`，不另行手工安装技术指标包。正式执行继续遵守 §1 的授权与 §5 的验收；本轮未操作服务器、未安装或升级本机依赖，临时构建与测试资源记录后删除。
