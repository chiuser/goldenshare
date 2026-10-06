# M10.F 九月月线预检、实际更新与重放合并验收

2026-10-06，Asia/Shanghai。管理员要求把“刷新9月月线只读预检”和“串行执行两主源job及重放”合并，尽量省时省力完成。本阶段沿原方案允许的同值既有月份验收；真实新增月份及主动取消/续跑、19:30启用仍单列。当前不提交或推送前轮尚未提交记录。

## 合并执行口径

先一次 source-free 只读预检：正式21日线/身份/事件绑定、两份9月Raw/schema/键/hash、四个基线文件、并发任务/分区/sensor状态与空间。通过后由现行asset job完成真实源拉取→页receipt→全字段候选/现有Raw比对→真实物化/checks；省去额外全市场预拉。每个主源初次job独立验收后，马上沿同意图重放，复用delivery proof；前项失败立即停止，不执行下一任务或自动覆盖差异。四次真实job串行，不使用bootstrap/runless补绿替代。

只读预检0.753秒通过：2026-09两源各5571行/ready，21日线116588行/5571期望代码，准确上游绑定通过；无周/月主源pending，9月分区已注册，sensor未启动，本日两个新意图目录均不存在。同卷且空间满足现行约2.13GiB门禁。没有预拉源，也没有正式写入。完整参考及源范围在[预检快照](stock_month_m10f_combined_preflight_20261006.json)。

## 完整命令及读写范围

cwd：`/Users/congming/github/goldenshare/lake_console/orchestrator`。
DAGSTER_HOME：`/Users/congming/.goldenshare/dagster_home`。
正式根：`/Volumes/datasource/data_lake`；staging：`/Volumes/datasource/data_lake_staging`。

按顺序初次未复权→独立读回→未复权同意图重放→独立读回→初次复权→独立读回→复权重放→独立读回。各源的初次和重放使用完全相同命令：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --attribute defs --job raw_stk_period_bar_month_update_job --partition 2026-09 --config /private/tmp/stock_month_m10f_combined_20261006/primary_unadjusted.yaml
```

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --attribute defs --job raw_stk_period_bar_adj_month_update_job --partition 2026-09 --config /private/tmp/stock_month_m10f_combined_20261006/primary_adjusted.yaml
```

配置仅对应asset的`automatic_intent_date: '2026-10-06'`。实际手动提交现行自动意图逻辑，不启用自动sensor，19:30窗口仍只约束自动触发。Source/月份/真实每日意图/唯一policy/io/schema/root参与现行hash，目录在预检冻结，不切换日期重试或提高预算。

| 性能、写入与验收 | 本阶段范围/上限 |
| --- | --- |
| 对象/月份/来源 | 5571期望代码、2026-09一月、两个Tushare主源 |
| 源请求 | 正常各1页/5571行，共2次；6000/页、最多4页、每页最多3次尝试，每源上限12次；重放增量0 |
| 返回/候选/正式 | 每源上限10000行，预计各5571行；同值既有正式文件保留字节hash，新候选/receipt/proof落各冻结staging |
| 事件 | 四次真实run及生命周期；预计4物化+12准确绑定的blocking检查，不补录runless事件或注册分区 |
| 读取/内存/spill | 当前月份21日线/116588参考行、身份及两目标；沿512MiB/2线程、2GiB spill，参考硬上限31文件/320000行，不全历史扫描 |
| 提交/恢复/拒绝 | 页receipt与请求账本持久化，同意图恢复；异值记录revision_required并停止，无覆盖、无清理账本或提额；原始正式文件保留 |
| 时间 | 无额外源预拉；正常沿既有约秒级单月实测，真实耗时另记；最坏源超时部分每源12×20秒加间隔，不把预算当ETA |

只消费现行上游，不写日线/身份、Prod、Silver、周线或其他月份；备用源和sensor/cursor均不执行。对成功job独立核验目标schema/行数/主键/全字段源hash及delivery proof和检查target binding，并核对历史/上游指纹不变；重放追加核对源请求账本与整个封存目录不变。失败保留staging/事件和正式文件，仅只读分类及差异审阅，不继续下一源。当前CLI验收不冒充正式launcher取消链路或新月份原子创建验收。

依据：月线LLD§13–14/§M10.F身份修复及现行`deliver_month_intent`/`read_month_delivery`/`monthly_upstream_bindings`。CodeGraph explore覆盖月线asset→point→proof及reference消费，补读当前jobs/checks和候选比对；没有改变正式代码、源参数、字段/配置合同、API/前端或依赖矩阵。读写及预算不超原方案，仅移除重复预下载步骤。

## 实际结果

四次真实job及独立读回均已通过。


| 主源/阶段 | run ID | 行数 | 源请求增量 | 实际物化/检查 |
| --- | --- | --- | --- | --- |
| 未复权初次 | 9f1f413f-22d8-41b7-a819-1b849acfb8fc | 5571 | 1 | 1 / 3 |
| 未复权同意图重放 | 054854f0-441a-4ce7-8487-616785ecb62b | 5571 | 0 | 1 / 3 |
| 复权初次 | 7fb3ba12-e3ad-4380-a287-6435f710eec3 | 5571 | 1 | 1 / 3 |
| 复权同意图重放 | 4a2e3c8d-513a-4996-9ca3-58aa74bd1251 | 5571 | 0 | 1 / 3 |

两份既有Raw合计11142行，四run均SUCCESS，共新增4条物化及12条blocking check evaluation，检查全部通过并准确绑定各次物化。两源真实源页完整字段与正式文件一致，包含复权源全部qfq/hfq字段，零差异、零reject、零revision_required。正式文件schema/键/周期、全字段canonical hash及字节hash保持；各首次请求账本calls=1/第一页attempt=1，重放仍各1次，源调用总计2次，没有额外预拉。

两个冻结意图目录各10份封存文件（源CSV/Parquet、receipt、reference、请求账本、候选、delivery等）在重放前后全部不变；两源最终ready，最新物化run均为本源重放run。21日线、日历、身份及准确上游绑定、2020-02与2026-05四份历史基线均未变，周/月sensor无启动state。没有业务正式文件改写、动态注册、runless补录、Prod/Silver/周线写入、主动取消或调度启用。

Dagster持久化运行记录实测四run累计15.188秒（未复权初次4.141/重放0.808秒；复权初次9.295/重放0.944秒），不含CLI启动、独立读回、审计与编排间隔。预检0.753秒；未测RSS/过程spill峰值，不把零文件变更当作未产生staging候选。时间数据来自真实run start/end，不使用缓存源模拟验收。

详细证据：[未复权初次](stock_month_m10f_combined_primary_unadjusted_initial_20261006.json)、[未复权重放](stock_month_m10f_combined_primary_unadjusted_replay_20261006.json)、[复权初次](stock_month_m10f_combined_primary_adjusted_initial_20261006.json)、[复权重放](stock_month_m10f_combined_primary_adjusted_replay_20261006.json)、[最终集合对账](stock_month_m10f_combined_final_audit_20261006.json)。最终审计只读，没有新增正式事件或执行job。

## 完成边界与下一步

本轮已完成合并后的“既有完整月真实更新+同意图幂等重放”验收。没有新增/修改正式Python、配置、字段或依赖边界；原月线LLD及周线总方案/LLD同步本阶段事实，新增7份reports文件（本MD、预检、四份后置、最终审计）。未重新运行不相关测试：本轮没有代码变化，以真实正式执行及独立只读对账为主要证据；文档完整性与diff检查另行完成。

M10.F整体仍未完成：新月份实际创建待10月结束且源/上游就绪；主动取消/同意图续跑及正式launcher、19:30启用继续独立验收。当前已有完整月验收不代替这些环节。周线下一真实周取消验收仍等待10月9日及源/上游，备用仅按明确手动任务使用。本轮没有扩大正式执行范围；执行记录及方案/LLD随此次文档提交，未推送。
