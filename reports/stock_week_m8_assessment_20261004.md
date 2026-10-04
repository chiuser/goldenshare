# M8 周线事件补录：开发及正式补录验收

2026-10-04。M8开发、正式apply及写后验收均已完成，M9未开始。下文开发/待批准段保留执行前历史记录，最新结论以末尾正式补录验收为准；就绪结论仅覆盖冻结文件范围，不代表全市场缺口消失。

## 依据与范围

执行依据为原LLD§12、§15、§33、接入模板§7A及性能治理§7.2。源为M5两主源及M7备用源最新年度sealed audit，保留M6旧审计作历史证据但不用于当前文件发布。正式Lake只读；不拉Tushare/Prod，不修改Raw/Silver或源接口合同，不启用sensor/schedule。配置只复用WeeklyBudget与已有dagster.yaml；没有新env、数据库或持久化配置。CLI参数audits/plan/report/mode/apply/start/count由运营显式输入，预算仍是唯一WeeklyBudget，命令不能超过冻结清单。

改动为四个bootstrap helper/CLI（event_files、event_instance、events、events_cli），同一weekly check源证据函数提取、两个隔离测试文件、受保护启动器精确源码/用例清单、原方案与LLD。没有改变子系统依赖矩阵、资产/check注册、数据字段、API或前端。

## 正式只读结果

[最新dry-run](stock_week_m8_dry_run_v3_20261004.json)、[冻结EventPlan](stock_week_m8_event_plan_v3_20261004.json)、[50个年度证据引用](stock_week_m8_audit_references_20261004.json)。旧v1/v2保留为开发过程证据，不作为apply输入。

- 已验证2517个文件，5926727行，文件SHA、严格物理schema、业务key、自然周归属及canonical hash均与交付证据一致。不是全市场无缺口结论，M7残余分类仍有效。
- 需要注册857个cn_a_stock_week_ends键；补2517次materialization、7551次blocking check，共10068事件。现有materialization及check记录为0，已有passed、latest failed、冲突check均0。
- 50个年度DuckDB连接、2867次SQL、14352个源证据文件校验，完整物理核验15.719秒；内存预算512MiB/2线程，existing_no_spill。未测全量apply耗时、强制spill或RSS压力，不以设计上限冒充实测。
- 当前零事件场景产生50次fetch_materializations、50次partition-info、1次动态分区查询，返回事件记录0；这是Dagster API次数，不是PostgreSQL底层SQL次数。完整事件场景受20000返回记录上限约束；每批最多100partition、每页500记录、cursor不推进即拒绝。

计划hash：`39154bfe35d3395c65472513fb08805866fa7aa707d906d76f916429368a2012`。

## 实现与计划逐项对账

| 硬口径 | 实现及验证 |
|---|---|
| 只发布当前物理文件 | event_files复用load_relation/validate_relation/relation_hashes；逐文件filename分区核验；真实全量只读结果及临时Parquet正反例 |
| 源证明与正式check一致 | verify_weekly_delivery_evidence由原check提取，年度只验证一次；apply按所选audit重验源证据，sealed条目逐字段比对；receipt改变/伪造身份拒绝测试 |
| 事件范围冻结 | EventPlan/hash/audit SHA/文件SHA/前置事件ID/缺失清单；变更计划、额外check、重复条目、越界批次拒绝 |
| 小批次有界读取 | 每asset/year及100partition批；500分页、20000记录上限；check正文按最多300个storage IDs批读；静态禁用execution-history深扫、cursor停滞/超限负例 |
| 当前目标check | partition、blocking、ERROR、passed、storage_id/run_id/timestamp全部读回核验；外部新materialization拒绝 |
| 可恢复、取消、幂等 | 每unit atomic journal；实际事件决定重放；materialization/check写后journal失败续跑不重复；取消停止领取unit |
| 只用现有正式实例 | 本机PG storage autocreate=false，固定instance home，配置SHA及非敏感存储身份冻结；拒绝自定义instance及重定向，禁用launcher/default discovery；隔离adapter测试 |
| 写后验收 | audit模式重新物理核验及聚合缺项，五代表分区实际file/check target抽查；正式apply未获本轮审批，尚无正式写后验收 |

安装的Dagster1.13.18对于同partition/check/run_id重复runless check有execution唯一键。隔离旧failed测试真实触发该约束后，改为显式blocked检查并在任何apply前拒绝；不删除记录、不伪造run_id。历史非匹配check必须另行审阅处理，不能拿事件写成功当通过。本轮正式对应记录为0。

## 验证与影响面

78项周线定向/相邻回归通过（events、event_files、definitions、candidates、contract）；受保护OS隔离运行12项asset治理、113项run-contract静态门禁通过，资产治理另有168subtests，不与常规用例合并计数。Ruff全目录致命错误基线与改动文件默认规则、文档integrity及diff检查通过。测试仅使用临时Parquet、离线源替身、临时instance；没有正式写入。

静态启动器初始拒绝：旧清单112与当前/HEAD实有113不符；修正后又因全defs AST审计遗漏已有daily_basic等源码路径被OS拒绝。精确补入20个当前只读Python路径（包括本轮4个helper），不扩大数据、网络、instance或写权限；完整113项重跑通过。保留失败过程日志并复制最终静态日志到本报告同目录。

CodeGraph使用explore、query、impact、sync/status；图分析与直接代码核验覆盖weekly contracts→catalog/assets/jobs/checks→point delivery→capture/candidate/promote/io，原audit_weekly_file及新事件CLI/5样本调用、相关测试。旧check签名/语义保持一致，delivery source核验共享一处；原消费者无前端/API合同变化。不存在待人工确认的模块依赖边界；正式apply是待审批的操作边界。

## 执行前待批准的执行卡（历史，已获本轮确认）

[完整139条分阶段命令](stock_week_m8_apply_commands_20261004.json)已列argv、cwd、DAGSTER_HOME、读写范围与恢复方式，均指向v3冻结计划。只申请本轮857注册键与10068个事件，既有目标变化即停。分区注册每100键，单分区materialization及3checks试点读回后，materialization每100条、check每25文件（最多75条），再只读聚合审计与5分区样本。试点在全量批次遇到时幂等跳过，不增加事件数。

示例完整命令（试点必须在注册阶段完成之后）：

```sh
cd /Users/congming/github/goldenshare/lake_console/orchestrator
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_events_cli --mode materializations --plan /Users/congming/github/goldenshare/reports/stock_week_m8_event_plan_v3_20261004.json --report /Users/congming/github/goldenshare/reports/stock_week_m8_apply_010_20261004.json --start 0 --count 1 --apply
```

预计低频运维成本由139次受控CLI调用、逐unit事件写/目标读回及必要文件hash组成；正式执行实测另记录，不能给未经验证的ETA。每次最多100写，异常/取消停止，保留事件和checkpoint；只重跑原未完成步骤，旧已写事件依据plan token及真实target匹配跳过。不得删除事件、回滚行情文件或绕过冲突门禁。

性能治理§7.2明确要求“用户审批apply”；orchestrator AGENTS要求完整命令与影响/恢复清单先审批。因此下一步是批准此执行卡后正式apply与写后验收，M8之后再进入M9更新机制。当前修改未提交、未推送。


## 正式补录验收（最新，2026-10-04）

用户在本线程明确确认冻结清单并要求开始补录。执行plan hash及139条命令保持不变；完成单分区试点实际readiness核验后执行余下清单，全部成功，没有重试、取消或范围扩大。

| 阶段 | CLI调用数 | 新写入 | 幂等跳过 | 命令累计秒 |
|---|---:|---:|---:|---:|
| 分区注册 | 9 | 857 | 0 | 33.946 |
| materialization | 27 | 2517 | 1 | 131.788 |
| blocking check | 102 | 7551 | 3 | 1311.883 |
| 最终只读audit | 1 | 0 | 0 | 25.978 |

新增10068事件；materialization/check跳过的是已经读回通过的试点，没有新增重复事件。命令累计1503.595秒，不含人工试点审阅等间隔。未测RSS或强制spill，不能声称性能压力全部通过；此次低频历史维护成本已实测落档。

[最终对账](stock_week_m8_final_reconciliation_20261004.json)、[实际写后审计](stock_week_m8_apply_139_20261004.json)、[逐批台账](stock_week_m8_execution_20261004.jsonl)、[试点readiness](stock_week_m8_pilot_readback_20261004.json)。全部139步exit=0，最终文件数2517、行数5926727与冻结证据一致；缺注册、materialization、check、blocked、latest failed均0，返回17619条记录，未超过20000上限。

五代表分区实际readiness均通过：未复权主源与复权主源各2010-01-01、2026-09-25，备用源2010-01-01。核验实际文件、源证据及三个passed/blocking/ERROR evaluation的partition和target storage_id/run_id/timestamp，未使用checkpoint替代实际事实。

只写本机Dagster动态分区/观测事件；没有改Raw/Prod/Silver数据，没有源请求或sensor/schedule变化，依赖矩阵/API/catalog保持一致。M7残余候选与未核验复权记录不因补录观测事件而关闭。M8完成，M9更新机制为下一独立阶段，尚未开始。原方案与LLD最新状态已同步；本轮未提交、未推送。
