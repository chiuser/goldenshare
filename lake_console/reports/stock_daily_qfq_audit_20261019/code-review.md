# 日线前复权回刷：代码复核记录（2026-10-19）

本轮是管理员要求的代码复核，用来补足LLD；没有重跑历史行情审计，没有查询正式DG数据库或请求源站。
五股原因和25股已完成专项继续引用[原审计报告](report.md)。
本轮源码位置/函数签名/文件hash保存在[代码索引](code-review-index.json)，供后续定点复核，不作为数据正确证明。

## 1. 核实的方法与边界

CodeGraph使用`codegraph_status`、`codegraph_explore`、`codegraph_impact`、`codegraph_callers`。
索引正常；已追到原QFQ sensor→执行→完成判断，以及趋势日更对原批次builder的依赖。
CodeGraph对`write_stock_daily_trend_channel_factor_repair`未返回调用方；源码明确有op调用，因此采用实际源码，不把空结果当成无消费者。
检查了下述函数的实现、直接调用和相关测试入口；索引保存27份源码hash，不声称每份源码的所有业务都已审计。

本机静态配置仅读取`dagster.yaml`的队列与并发字段：`QueuedRunCoordinator`、`concurrency.runs.max_concurrent_runs=1`、`pools.granularity=run`。
未初始化instance、加载Definitions、连接数据库或输出连接信息。
Dagster安装源码核实`instance.get_concurrency_config().run_queue_config`、`DagsterRun.remote_job_origin`和有界记录API。

## 2. 需要直接指导改造的事实

| 当前代码 | 具体事实 | LLD处理要求 |
| --- | --- | --- |
| `sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py` | 只从触发run读分区，批次含producer_run_id；无变化会提交no-op任务 | 改为读未完成位置，保留no-op确认；不能只修来源筛选 |
| `stock_daily_qfq.py:621` | 原执行器先按触发日重新计算股票集合，逐日写，全部完成后返回 | 区分原因日和as-of；冻结计划；每文件可恢复 |
| `stock_daily_qfq.py:497` | as-of可缺省为trade_date，旧文件可直接覆盖 | 正式历史补跑必须走明确计划；日更拒绝改回历史旧基准 |
| `stock_daily_qfq.py:147,1097` | 前序查询最多20交易日，未查到记录时计算分支写0 | 快速窗口没有找到不等于历史没有；补充实际前序行定位，无法确认则阻断 |
| `asset_guards/stock_daily_qfq_factor_repair.py:142` | 有股票集合/非负计数等校验；没有要求选定文件数全部完成 | 新完成合同明确选定=替换+无需替换、未完成/失败=0，绑定计划和输入 |
| `bootstrap/gold_stock_daily_qfq_history.py:230` | 显式as-of且逐股取最后可用因子；已有文件可skip，TemporaryDirectory离开即删 | 复用分母语义；skip不等于正确；候选和执行证明不能随退出删除 |
| `ops/gold_stock_daily_trend_channel_repair.py:66,300` | 结束日强制为触发日前一交易日，QFQ日期数减1；不能表达任意历史更正 | 从价格修复计划取实际结果/state日期范围，不再按触发日倒推 |
| `stock_daily_trend_channel.py:1482` | 先生成全部候选，再逐文件替换，最后再次业务审计 | 拆候选计算和提升，保存验证证明；state/结果两文件分别恢复，成对完成才放行 |
| `stock_daily_trend_channel.py:_prepare_trend_repair_candidates` | 会unlink已有候选 | 已完成候选先识别并复用，不能清掉再算 |
| `bootstrap/qfq_nineturn_history.py:1340` | 恢复先fresh_plan，再全范围计算，再检查已完成目标；写入时复制backup，失败回换，finally删staging | 本次不得调用这个完整入口；仅复用纯九转计算与既有合同，采用统一候选/提交记录 |
| `qfq_nineturn.py:build_qfq_nineturn_source_fingerprint` | hash内容是路径、大小和mtime | 只能叫文件属性标识，不当作内容校验；本次执行另记录实际内容hash |
| `sensors/stock_daily_trend_channel_sensor.py:_qfq_reconciliation` | 自己从最新materialization run_id重新拼QFQ批次，并按QFQ日期数减1检查趋势 | 迁移为消费已完成计划，不能仍拼旧身份 |
| `assets/qfq_nineturn.py:gold_stock_daily_qfq_nineturn` | 直接按registered前序读取日线，未读取本次QFQ历史回刷状态 | 增加历史消费门禁，仅改日线分支，不扩到分钟资产 |
| `assets/stock_daily_qfq_nineturn_prod_core.py` | DG九转可被发布至Prod | 只加源版本/未完成阻断，不增加本轮Prod写入步骤 |

上述相对路径以`lake_console/orchestrator/src/orchestrator/defs/`为根。
不修公式之外的其他业务算法，不恢复已清退的25股专项模块。

## 3. 批量读取不能靠函数名推断

现有`latest_partition_check_records`只支持一个`PartitionKeyFilter.key`，重复调用它不能构成日期批量检查。
当前Dagster支持`event_log_storage.get_asset_check_partition_info(keys, partition_keys=...)`，返回每个check/日期的最新状态及关联materialization。
其SQL实现仍按check key循环，但不按日期循环；成本为check数量相关，不是日期数乘check数量。
LLD使用这个真实接口，显式要求materialization非空、SUCCEEDED和`is_current`。
源码确认SUCCEEDED由evaluation.passed决定；`is_current`在没有materialization时也可为真，必须另判非空，不能只用这一属性。
这些storage id仅用于事件关联核对，不进入run key、config或完成身份。

## 4. 复用判断

- 共用现有QFQ数学表达与独立金样本，拆出relation级计算供日更和批次共用；不复制第二套生产公式。
- 共用Dagster既有队列并发1；正式writer核实真实配置和运行来源，CLI不能绕过队列直接写正式根。
- moneyflow历史提升体现了提交意图、内容hash、rename后恢复的做法，但函数绑定其专属计划和“不覆盖不同目标”的合同；不能直接拿来覆盖QFQ旧错误文件。
- 公告checkpoint绑定公告状态/锁，不引入公告模块依赖。本次QFQ执行记录归本数据集，具体格式由原LLD约束。
- 新执行记录用于记录跨文件提交和恢复；Dagster运行成功、普通checks和小cursor无法记录rename前后的两个内容hash，不能代替这一记录。

具体函数签名、字段、文件修改清单、错误分支、配置审计和测试逐条见[原LLD第20节](../../docs/design/dagster-stock-daily-qfq-asset-low-level-design.md#qfq-code-design-20261019)。
