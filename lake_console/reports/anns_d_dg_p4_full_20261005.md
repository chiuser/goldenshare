# 公告DG P4 全量历史事件验收（2026-10-05）

状态：用户明确授权样本报告所列三条全量命令，物化→检查→最终audit已完成；历史文件与事件均已齐。衔接补拉、正式日任务验收及schedule启用尚未执行，P4尚未全部退出。本报告是最新事实，开发/样本报告保留历史时点。

## 全量事实

同一冻结计划SHA `c6aa13f0e81631089cd7955fdf3f966957355fde8caf3d27d645e7e2b2177e34`，正式已有本机DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home。本轮新增2,435物化+4,870check，共7,305事件；六月样本30/60自动跳过。总计2,465物化+4,930检查，共7,395，覆盖2020-01-01..2026-09-30、81月/2,465日/12,064,049行。

三阶段均完成81月并逐月批量读回，通过文件合同和六字段源/输出完整集合proof后追加绿色事实；两项检查明确日期、blocking ERROR和正确同日mat storage ID/run/timestamp。最终audit返回24,650记录（两次批量mat/info/body），未达到30,000门禁；新只读plan返回12,325记录，缺失物化0、缺失check0、冲突0。所有2,465文件、源页、日交付及父捕获凭据字段/指纹与原冻结计划完全一致；83空日、URL/rec_time缺值保留沿用P3全量事实，未进行其它清洗。

81月事件checkpoint均checks_verified且归属同一事件计划；写入仅正式Dagster事件及获准staging事件checkpoint/锁。无正式Parquet/Prod写入，无Tushare/PDF请求或启用动作。未删除或重建事件/表/文件，未增加动态分区、启动job、安装或升级。

少量readiness抽查通过：2020-01-01、2023-06-09缺值案例、2023-06-23空日、2024-04-30峰值月、2026-09-30。物化metadata/文件SHA、两项check及target绑定全正确，仅返回25记录。不是逐partition运行正式checks，也不把历史通过当作日常链路验收。具体IDs、三阶段全部月结果及数量见[结构化证据](anns_d_dg_p4_full_20261005.json)。

## 实测性能

| 阶段 | 新增事件 | 返回记录 | 观测秒数 |
|---|---:|---:|---:|
| materializations | 2,435 | 2,735 | 94.693 |
| checks | 4,870 | 14,910 | 183.384 |
| audit | 0 | 24,650 | 47.39 |

观测累计325.467秒，约5.4分钟，符合先前5–15分钟估算。口径为各阶段日志创建时间至最后业务进度timestamp，含进程启动/物理proof/事件操作/读回，未含阶段间等待或退出后尾部时间；不是纯SQL耗时。没有RSS采样，不声称实测内存峰值。月31日/93事件/1800秒、SQL10秒、DuckDB2GB/2线程/20GBspill和空闲空间/返回记录门禁未触发。

实际命令与授权范围沿用[样本报告中的全量命令](anns_d_dg_p4_sample_20261005.md)。日志及详细报告为/private/tmp/anns-d-p4-full-{materializations,checks,audit}-20261005.{log,json}；最终只读缺口/private/tmp/anns-d-p4-after-full-plan-20261005.json、readiness/private/tmp/anns-d-p4-full-readiness-20261005.json。样本已真实验证SIGINT取消、续跑和0新增重放，本轮无失败，不额外灌同一事实。

## 下一阶段：衔接2026-10-01..04，尚未执行

2026-10-05仅处理已结束四个自然日，公告无需交易日有数据。默认间隔5秒，limit2000/offset受控、三次尝试、30秒调用上限、每日至多100请求、窗口350请求/60分钟；不开放额外源参数。实际行数/分页量尚未请求源，不能以假期或估算当作源真值。

只读CLI计划已保存/private/tmp/anns-d-p4-bridge-plan-20261005.json，稳定window_id=anns-d-p4-bridge-20261005。四个预期delivery路径manifest位于/private/tmp/anns-d-p4-bridge-deliveries-20261005.json；仅运营意图，没有创建Lake/staging目录或执行来源请求。当前四个交付路径均未存在，目标Raw四文件也未存在。默认固定正式Lake/staging、2GB/2线程/20GBspill及5GiB reserve。

申请下一阶段授权范围：四日Tushare源分页及正式Raw四文件、对应run/window凭据；交付绿色后，单独event plan生成并校准实际缺口，再补至多4物化+8check及audit，期间验收SIGINT取消/相同window续跑、指纹不变和完全重复幂等。四日范围或正式事实改变必须停下，不自动扩日期。此授权不包括正式日asset/job执行或schedule启用；它们在衔接完成后按原LLD另列具体验收命令。

从/Users/congming/github/goldenshare/lake_console/orchestrator，以下流程尚未执行：

```bash
.venv/bin/python -B -m orchestrator.defs.anns_d_cli run \
  --start-date 2026-10-01 --end-date 2026-10-04 \
  --interval-seconds 5 --window-id anns-d-p4-bridge-20261005

.venv/bin/python -B -m orchestrator.defs.bootstrap.anns_d_events_cli plan \
  --delivery-manifest /private/tmp/anns-d-p4-bridge-deliveries-20261005.json \
  --report /private/tmp/anns-d-p4-bridge-event-plan-20261005.json

ANN_D_BRIDGE_EVENT_FP=$(.venv/bin/python -B -c 'import json; print(json.load(open("/private/tmp/anns-d-p4-bridge-event-plan-20261005.json"))["fingerprint"])')

.venv/bin/python -B -m orchestrator.defs.bootstrap.anns_d_events_cli materializations \
  --event-plan /private/tmp/anns-d-p4-bridge-event-plan-20261005.json \
  --fingerprint "$ANN_D_BRIDGE_EVENT_FP" \
  --report /private/tmp/anns-d-p4-bridge-materializations-20261005.json

.venv/bin/python -B -m orchestrator.defs.bootstrap.anns_d_events_cli checks \
  --event-plan /private/tmp/anns-d-p4-bridge-event-plan-20261005.json \
  --fingerprint "$ANN_D_BRIDGE_EVENT_FP" \
  --report /private/tmp/anns-d-p4-bridge-checks-20261005.json

.venv/bin/python -B -m orchestrator.defs.bootstrap.anns_d_events_cli audit \
  --event-plan /private/tmp/anns-d-p4-bridge-event-plan-20261005.json \
  --fingerprint "$ANN_D_BRIDGE_EVENT_FP" \
  --report /private/tmp/anns-d-p4-bridge-audit-20261005.json
```

需要现有环境TUSHARE_TOKEN，不能硬编码、持久化或打印秘密。源失败、窗口过期、拒绝原因或目标冲突阻断；先解释实际原因，不清空/覆盖正式事实。SIGINT保留提交unit；同window、日期及间隔续跑，预算不能重启重置；续跑报告用新的/private/tmp名不覆盖。过期未完成日必须提出新的明确补拉意图。CLI日文件只用于获准衔接与恢复，不代替日常asset/job。

## 交付边界

本轮无源码、配置、CLI行为、asset/check/partition/job/schedule或依赖矩阵改动。仅新增全量报告/聚合证据并更新原方案/LLD最新状态，保留历史开发/样本记录；未提交。166项开发回归和样本恢复证明保持有效，不为无源码改变重复全套测试；文档完整性和diff检查单独记录。正式写入授权仅覆盖本次全量历史事件；新源请求、日任务、启用未执行，授权规则来自根/目录AGENTS及原LLD§20。
