# DG 公告 P3 正式样本验收

2026-10-04。用户“授权，进行吧”覆盖此前列明的2023年6月文件样本及取消/续跑/读回。依据原[方案](../docs/design/dagster-anns-d-onboarding-plan-v1.md)、[LLD](../docs/design/dagster-anns-d-onboarding-low-level-design-v1.md)及[预检和完整样本命令](anns_d_dg_p3_20261004.md)。本次没有修改Python主实现或API合同，仅执行获批样本并更新验收文档；[结构化证据](anns_d_dg_p3_sample_20261004.json)。P3样本通过，全量文件待批准。

## 文件事实

| 项目 | 结果 |
|---|---:|
| 范围 | 2023-06-01..2023-06-30 |
| 源行数 / 正式写入行数 | 147,952 / 147,952 |
| 完全重复 / 拒绝 / 双向集合差 | 0 / 0 / 0 |
| 正式日期文件 / 合法空日文件 | 30 / 1 |
| 缺URL / 缺rec_time仍保留 | 3 / 66,669 |
| 正式文件总大小 | 2,674,005字节 |
| capture源shard大小 | 3,523,756字节 |
| 日交付checkpoint promoted | 30 |

schema为固定六VARCHAR，只有完全重复可丢弃，本月源已没有完全重复。155162.SH / 2023-06-09的同标题两条源记录在目标读回一致：URL分别NULL/有效地址，rec_time均NULL。它们按当前六字段全量镜像口径都保留；样本双向集合差0，不恢复早期按标题合并的规则。其它缺值样本同样没有被拒绝。

capture耗时22.571秒；build取消0.868秒、恢复1.367秒；候选audit0.904秒；promote取消0.954秒、恢复1.324秒、重放1.014秒；最终formal audit0.870秒。含两次取消与重放的全部阶段约30秒，不含人工审计间隔。最大观测进程RSS414,433,280字节，约395MiB，远低于2GB DuckDB预算；约50ms的ps采样是观测峰值，不能证明绝对瞬时峰值。本月样本不能替代峰值月完整实测，但单批1万/月200万、月1800秒、SQL60秒、2GB/2线程/20GB spill和35GiB空间拒绝门禁仍生效。

## 取消、恢复与重放

build完成2023-06-01和06-02后向CLI进程发送SIGINT，命令退出1，checkpoint为cancelled，两个候选可读回，正式文件0；恢复相同计划及月份完成剩余28天，原候选路径/大小/SHA一致。

promote提交前两天后同样SIGINT，命令退出1，月checkpoint为cancelled，两个正式文件和逐日交付checkpoint保留；恢复提交其余28天，原正式文件SHA一致。再重放全月promote，30个文件指纹完全一致，零新增；月及30个日checkpoint最终均promoted。

最终formal audit只用现有capture和正式文件，重新核验schema、日期分区、六字段集合双向差、重复、缺值与指纹。退出0，passed=true，集合差0；没有重新拉取源，没有写Dagster事件。正式文件根 `/Volumes/datasource/data_lake/raw/tushare/anns_d/ann_date=2023-06-*/part-000.parquet`；执行证据在 `/Volumes/datasource/data_lake_staging/anns_d/`。日志、命令、采样及取消前读回证据在 `/private/tmp/anns-d-dg-p3-20261004/`。不访问正式DAGSTER_HOME，无Prod写入、Kopia、备份、删除或调度变更。

## 下一阶段精确范围与命令（未执行）

建议批准剩余80月、2,435自然日、11,916,097源行的文件阶段。原冻结计划整体仍2020-01-01..2026-09-30、81月/2,465日；省略 --month 由CLI按月自动推进，已经完成的2023年6月复用capture与交付证明，不重写。每个自然月独立只读事务，文件逐日提交，不建立全历史长事务。五个阶段分别执行，任一失败立即停止，不自动跨过错误；只补文件，事件和调度留P4。

工作目录 `/Users/congming/github/goldenshare/lake_console/orchestrator`；源为Prod只读公告；目标Raw同公告根及同staging根；DAGSTER_HOME不打开、无事件。原计划SHA保持不变。完整命令如下，均未执行：

```bash
.venv/bin/python -B /private/tmp/anns-d-dg-p3-20261004/run-cli.py capture --plan /private/tmp/anns-d-dg-p3-20261004/history-plan.json --fingerprint dc0a03a404d9bdbcd7cdd34bc4da0e045f9f01a7b03d478ce6d0e29ea2e40d9b --report /private/tmp/anns-d-dg-p3-20261004/full-capture.json
.venv/bin/python -B /private/tmp/anns-d-dg-p3-20261004/run-cli.py build --plan /private/tmp/anns-d-dg-p3-20261004/history-plan.json --fingerprint dc0a03a404d9bdbcd7cdd34bc4da0e045f9f01a7b03d478ce6d0e29ea2e40d9b --report /private/tmp/anns-d-dg-p3-20261004/full-build.json
.venv/bin/python -B /private/tmp/anns-d-dg-p3-20261004/run-cli.py audit --plan /private/tmp/anns-d-dg-p3-20261004/history-plan.json --fingerprint dc0a03a404d9bdbcd7cdd34bc4da0e045f9f01a7b03d478ce6d0e29ea2e40d9b --report /private/tmp/anns-d-dg-p3-20261004/full-audit.json
.venv/bin/python -B /private/tmp/anns-d-dg-p3-20261004/run-cli.py promote --plan /private/tmp/anns-d-dg-p3-20261004/history-plan.json --fingerprint dc0a03a404d9bdbcd7cdd34bc4da0e045f9f01a7b03d478ce6d0e29ea2e40d9b --report /private/tmp/anns-d-dg-p3-20261004/full-promote.json --audit-report /private/tmp/anns-d-dg-p3-20261004/full-audit.json
.venv/bin/python -B /private/tmp/anns-d-dg-p3-20261004/run-cli.py audit --plan /private/tmp/anns-d-dg-p3-20261004/history-plan.json --fingerprint dc0a03a404d9bdbcd7cdd34bc4da0e045f9f01a7b03d478ce6d0e29ea2e40d9b --report /private/tmp/anns-d-dg-p3-20261004/full-formal-audit.json --formal
```

报告必须是新的/private/tmp路径，不可覆盖；日志可保存到同目录。Ctrl-C取消当前阶段后，同计划同阶段恢复；未完成capture月重新快照，不混合批次，完整月复用；build复用已完成候选；promote保持已提交文件，冲突则阻断。不做删除回滚。完成后formal audit核对81月/2,465文件、源和去重后行数、缺值、reject和集合差；与样本相比只能增补其余日期。

本次147,952行端到端实测说明读取是主要耗时，按全量行数粗推约30分钟，再考虑月份/网络差异按30–60分钟规划；这不是ETA或承诺。完整范围实际进度仍按月份、capture行数和日提交数记录，ETA显示暂无法估算。采样月不到峰值月行数，峰值月首次执行仍须核验RSS和耗时，达到硬预算立即失败并保留可恢复事实。

## 状态与边界

本轮只是正式样本，未进入全量，未补物化/check事件，未启动schedule，不能宣布Dagster已ready或P3全部完成。开发回归沿用已验证156项，本轮没有代码变化，无需重复全套测试；文档完整性与diff检查另行执行，CodeGraph已完成的调用链和依赖矩阵不变。全量文件需按原方案P3“批准全量候选/提升”另获明确授权；验收后进入P4独立事件、衔接补拉和日常验收。

后续全量文件已获授权并完成；最新状态见[全量验收](anns_d_dg_p3_full_20261004.md)，本报告保留此前时点记录。
