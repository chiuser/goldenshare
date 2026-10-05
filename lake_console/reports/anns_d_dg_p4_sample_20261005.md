# 公告DG P4 正式事件样本验收（2026-10-05）

状态：用户明确授权上轮2023-06样本，正式取消/续跑/重放/文件及事件读回完成并通过。本轮仅样本，尚未全量；衔接补拉、正式日任务及schedule启用未执行。P4尚未全部退出。

## 样本事实

同一冻结计划SHA `c6aa13f0e81631089cd7955fdf3f966957355fde8caf3d27d645e7e2b2177e34`，固定本机DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home。六月30自然日/147,952行/1空日，最终30物化+60检查全部正确；两项blocking ERROR检查均带日期分区并准确绑定同日mat storage ID/run/timestamp。正式文件、六字段源页、日交付及父捕获checkpoint与原冻结计划一致，无Parquet/Prod写入、Tushare/PDF请求或调度变更。写入仅Dagster事件及获准staging事件checkpoint/lock。

物化和checks各在观察到第2条业务进度后发送SIGINT。异步信号到达前第3条已进入提交，因此两阶段取消后实际各保留3条；取消至退出分别0.238秒/0.227秒。续跑基于实际事件身份，物化新增27、checks新增57，补齐30/60；没有删除或重置任何文件、凭据或事件。该事实区分信号发送时的进度与最终已提交量，不把进度日志误当成事务事实。

物化重放0新增、checks重放0新增；最终audit通过，批量读取300记录（两次30物化+60 check info+60 check body），不逐日深扫历史。首日2023-06-01、缺值案例06-09、空日06-23及尾日06-30的额外少量readiness全部正确，仅返回20记录。详细storage IDs及执行命令见[结构化证据](anns_d_dg_p4_sample_20261005.json)。

## 实测时间

每行是独立CLI进程墙钟耗时，含Python启动、月完整文件审计、PG读写、checkpoint和读回；不是纯SQL时间，也未测RSS。

| 操作 | 秒 | SIGINT至退出秒 |
|---|---:|---:|
| mat-cancel | 2.315 | 0.238 |
| mat-resume | 1.96 | - |
| checks-cancel | 1.408 | 0.227 |
| checks-resume | 2.939 | - |
| mat-replay | 1.437 | - |
| checks-replay | 1.532 | - |
| sample-audit | 1.488 | - |

全量预检在样本后再次通过81月/2,465文件/12,064,049行，所有冻结文件/交付/捕获证据完全一致，现有匹配物化30/check60，其余缺口2,435物化+4,870check，共7,305。当前缺口仅剩80月，已完成六月可被同一计划自动跳过。该聚合预检/private/tmp/anns-d-p4-sample-20261005/after-sample-plan.json只用于审计，后续apply继续使用原冻结事件计划。

估算：样本完成及读回单次约1.4–2.9秒；考虑81月反复物理proof、事件事务、实例负载，剩余执行先按5–15分钟规划，属于预算估算，非ETA承诺。每月仍保留31日/93事件/1800秒、SQL10秒及整次30000返回记录门禁，实际月进度/耗时逐批写checkpoint。无需按7,305条单独审批或手工启动任务。

## 待批准全量命令

从/Users/congming/github/goldenshare/lake_console/orchestrator依次执行下列三个阶段，省略--month即原计划全部81月；已完成样本跳过，最多新增2,435物化+4,870check。授权范围仅本机公告Dagster事件及staging/anns_d/events/<原计划SHA>/月checkpoint/锁；正式Raw文件保持原事实，不重拉源、不写Prod、不启用调度。这三条尚未执行。

```bash
.venv/bin/python -B -m orchestrator.defs.bootstrap.anns_d_events_cli materializations \
  --event-plan /Users/congming/github/goldenshare/lake_console/reports/anns_d_dg_p4_frozen_event_plan_20261005.json \
  --fingerprint c6aa13f0e81631089cd7955fdf3f966957355fde8caf3d27d645e7e2b2177e34 \
  --report /private/tmp/anns-d-p4-full-materializations-20261005.json

.venv/bin/python -B -m orchestrator.defs.bootstrap.anns_d_events_cli checks \
  --event-plan /Users/congming/github/goldenshare/lake_console/reports/anns_d_dg_p4_frozen_event_plan_20261005.json \
  --fingerprint c6aa13f0e81631089cd7955fdf3f966957355fde8caf3d27d645e7e2b2177e34 \
  --report /private/tmp/anns-d-p4-full-checks-20261005.json

.venv/bin/python -B -m orchestrator.defs.bootstrap.anns_d_events_cli audit \
  --event-plan /Users/congming/github/goldenshare/lake_console/reports/anns_d_dg_p4_frozen_event_plan_20261005.json \
  --fingerprint c6aa13f0e81631089cd7955fdf3f966957355fde8caf3d27d645e7e2b2177e34 \
  --report /private/tmp/anns-d-p4-full-audit-20261005.json
```

SIGINT/SIGTERM可取消，已提交事件保留；同计划同命令换新的/private/tmp报告名即可续跑。月集合proof/文件或凭据/实例/外部事件改变、旧红灯、预算超限会阻断。只追加事实，不删除历史事件；发现错误先停下说明并单列更正范围，不扩大原授权。

全量后用原计划audit全月批读事件，并单独抽少量readiness；不会全量逐partition运行正式asset checks。之后再具体提出2026-10-01起衔接范围、正式日任务取消恢复及schedule启用，分别获批；本轮授权不包含这些步骤。

## 代码和文档边界

本轮无Python、配置、asset/check/job/schedule、CLI或依赖矩阵变更；沿用166项开发回归及scoped Ruff。仅新增本报告/聚合证据，更新原方案和LLD最新事实；P4开发报告保留预检时点。未提交。本轮属于获批正式样本验收，不把隔离测试替代实际读回，也不把样本通过算成P4全部完成。审批依据根AGENTS DG只读授权第3条、orchestrator正式执行第3条和LLD§20分阶段边界。
