# M9 周线两主源幂等重放验收

2026-10-07纠偏说明：本报告保留历史结论；搬运/审计中间数据文件已按管理员要求清理，不再是正式检查或调度依赖。现行口径为 bootstrap 完整对账一次即结束、日常只检查当前新增周期。详见[清理记录](stock_period_reports_cleanup_20261003.md#2026-10-07运行依赖纠偏及清理)。

2026-10-06，Asia/Shanghai。管理员要求“提交，并继续推进”，本轮先提交上轮正常交付六份文档与报告（c453afbd），再执行此前列出的同意图幂等重放阶段。没有推送，没有修改正式代码、配置合同或依赖边界。

## 执行清单

cwd：`/Users/congming/github/goldenshare/lake_console/orchestrator`。
DAGSTER_HOME：`/Users/congming/.goldenshare/dagster_home`。
正式Lake：`/Volumes/datasource/data_lake`；staging：`/Volumes/datasource/data_lake_staging`。

两源均使用2026-10-02周分区、真实2026-10-06每日意图和上轮同一配置文件。只读预检确认两源ready、原成功run仍是各job最新运行、没有活动任务；两个assembly各11份已封存文件、请求账本各calls=1/page0 attempts=1，目标文件指纹与正常交付报告一致。详见预检快照（历史中间文件已清理）。

串行执行；前项独立读回成功后才执行后项：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --attribute defs --job raw_stk_period_bar_week_update_job --partition 2026-10-02 --config /private/tmp/stock_week_m9_recovery_20261006/primary_unadjusted.yaml
```

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --attribute defs --job raw_stk_period_bar_adj_week_update_job --partition 2026-10-02 --config /private/tmp/stock_week_m9_recovery_20261006/primary_adjusted.yaml
```

两个配置仅为对应asset的`automatic_intent_date: '2026-10-06'`。执行理由：验证现行封存audit复用路径，不再次取源或改写数据。只读消费当前上游和两份Raw文件；预计源调用增量0、正式文件改写0、staging audit/receipt/捕获内容改写0；提升checkpoint按既有promoter语义在读回后刷新verified时间。正式instance新增2次run及其生命周期，成功时新增2条materialization与6条blocking check evaluation，检查必须准确绑定各新run物化。数据仍为每源5565行，总11130行；沿现有512MiB/2线程预算，不扩大历史扫描。

失败立即停止，保留所有历史事件、请求账本、receipt、audit及数据，不清理记录、不提高预算、不使用备用源；必要时只读诊断。重放不注册分区，不写Prod/Silver/月线，不主动取消、不启用sensor。本阶段独立记录，不能代替主动取消/续跑验收。

## 结果

未复权第一次严格树指纹验收发现仅`checkpoints/2026-10-02.json`变化，正式job SUCCESS，数据和账本不变。原因是既有`promote_weekly_candidates`每次成功读回都会原子写入verified检查点及当前updated_at；原LLD/测试要求数据/audit不变，未要求观测时间冻结。本轮没有改正式实现。保留首次严格核对证据（历史中间文件已清理），校准审计为audit/receipt/捕获等封存证据全部不变、仅checkpoint可刷新且hash/status必须对应当前audit和目标文件。复权执行采用此准确口径。


两个真实重放均成功并独立读回通过：

| 主源 | run ID | 行数 | 实际新增物化/检查 | 源调用增量 |
| --- | --- | --- | --- | --- |
| 未复权 | bf98de39-0616-4dd1-83e0-e350c07df7e7 | 5565 | 1 / 3 | 0 |
| 复权 | 2e327e73-ffca-44f4-baef-327fd5704126 | 5565 | 1 / 3 | 0 |

未复权独立对账（历史中间文件已清理）、复权独立对账（历史中间文件已清理）：两源均ready、全字段源hash一致、schema/唯一键校验通过，三个check均绑定本次run物化；请求账本仍各calls=1，audit、receipt、捕获chunk及意图/参考文件全部不变，正式文件字节hash不变；只有提升checkpoint刷新，status=verified且audit_hash/sha256正确。旧失败账本、两个历史基线与上游指纹未变。没有新失败、源调用、数据修订或备用源；sensor仍未启动。

## 主动取消/续跑阶段准备

已用CodeGraph `codegraph_explore`核对asset→point→update execution/receipt恢复→promoter主链，并读取本机Dagster CLI及DefaultRunLauncher实现。没有修改源码、API/前端、字段/配置合同或子系统边界。

取消入口必须与启动方式匹配：本次`dg launch`调用`job_execute_command_impl`/`execute_job`本地执行，两次run均没有grpc termination tag；`DefaultRunLauncher.terminate`先记CANCELING，再寻找grpc client，没有tag会返回false。因此下一轮不能对本地CLI run直接调用该launcher或只改状态，就声称执行进程已取消。建议通过正式code location的Launchpad提交同一主源job，用它的既有取消入口验证实际自动运行链路；提交前核对真实run origin、launcher、grpc tag及无并发任务。若选择本地CLI的终端中断，只验证CLI方式，不能替代正式launcher取消验收。此为入口审计，不是当前已执行取消或已批准新的操作清单。

下一候选周为2026-10-09；截至2026-10-06 01:17:56的只读准备条件（历史中间文件已清理）：本周未结束，正式日历开盘日为10月8/9日，两份日线尚不存在，上游事件不ready，两主源该周正式目标均不存在。源是否发布尚未核验，不向未来周发请求。当前10月6日两个已封存意图不能用于验证运行中断，不删除证据、伪造日期或改分页大小来造场景。

待真实周完成且源、日线、身份及准确绑定的上游checks就绪后，冻结精确执行清单：限定单个主源/周及实际每日意图，在首个完整页receipt已封存、正式提升尚未完成的安全窗口取消；记录实际run终态、worker退出、receipt/chunk/账本及文件状态。若任务先完成、错过窗口，记录未覆盖，不伪称取消成功。保持同一意图恢复，已封存页不再取源，未封存页按原预算处理；有异值则停止修订，不覆盖；读回正式数据与当前物化/check绑定。另一主源独立验收，不回滚已经完成的文件。具体启动/取消命令、run ID、读写上限和恢复路径在实际条件刷新后确认。

主动取消/续跑通过后再按独立阶段启用唯一周线sensor，沿用每日Asia/Shanghai 19:30、两主源串行、备用仅手动的已批准口径。当前不启用、不改cursor，不增加automation；M9仍未整体完成。月线新增月份M10.F继续等待10月结束及源/上游就绪。

本轮新增六份reports文件并同步原方案与LLD最新状态；正式执行与只读证据已完成，静态文档检查结果在交付中列出。本轮新增记录及方案/LLD随此次文档提交；未推送。
