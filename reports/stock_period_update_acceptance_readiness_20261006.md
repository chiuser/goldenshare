# 周线/月线更新：当前准备完成与后续真实验收清单

2026-10-06，Asia/Shanghai。依据管理员“把现在能做的推进做完，需要后续验证的，在文档中记录清晰”，本轮完成运行入口审计、未覆盖的中断清理测试和后续执行卡。M9/M10.F仍待真实取消/续跑及自动运行验收；月线另欠新月份实际创建。本轮没有正式任务、取消、分区/event/cursor/sensor写入或服务启停。

## 当前完成的工作

| 工作 | 证据与结论 |
| --- | --- |
| 正式实例只读复核 | [08:39快照](stock_period_update_runtime_readiness_20261006.json)：四个主源最近run均SUCCESS、没有pending周/月任务；四run均无gRPC取消标记。两sensor无持久化state记录；不能将此描述为正在运行。 |
| 当前启动配置 | 现有dagster.yaml配置QueuedRunCoordinator、全实例最大并发run=1、run monitoring开启；未显式配置launcher，安装包默认DefaultRunLauncher。HTTP页面不可达，因此没有确认在线launcher或已加载的location/repository；不把配置推断写成在线事实。 |
| 正式页面条件 | 既有local_startup.py指定127.0.0.1:3000；只读HTTP查询得到ConnectionRefusedError/errno=61。当前端点拒绝连接，不是PG权限问题；没有据此重启服务。后续使用既有lake-dg-start入口由运营恢复后，再刷新在线位置/版本/launcher。 |
| 中断清理新增覆盖 | 在既有test_stock_weekly_source.py增加2个参数化用例，使用合成阻塞worker、真实SIGINT和Dagster的中断上下文，验证KeyboardInterrupt及DagsterExecutionInterruptedError均从监督入口退出、无遗留SDK子进程并恢复信号处理器。没有真实token、数据库或Lake访问。 |
| 定向取消/恢复回归 | 新增2例与既有6例共8项通过，7.17秒：运行中取消、超时、周/月页封存后取消/恢复、真实进程退出后恢复。封存页不重取，未完成意图保留请求预算。 |
| 自动窗口隔离回归 | 两sensor合成替身测试共24项通过，0.87秒：19:30前零外部读取、默认停止、稳定日意图、每tick最多一个主源任务、pending互斥、错误/源未就绪不调用备用、两主源ready后才推进frontier。未对正式sensor调用evaluator。 |

这些测试证明当前共享采集监督和隔离调度逻辑；没有证明正式launcher从页面取消真实任务的最终状态、实际进程退出或正式新周期续跑。历史CLI正常更新和重放已经通过，本轮不重复下载。

## 根因和匹配的运行入口

当前安装包DefaultRunLauncher启动时通过GrpcServerCodeLocation调用StartRun，并把连接信息写入run的GRPC_INFO_TAG。取消先记CANCELING，再用该标记找到执行server并调用CancelExecution。缺少标记时无法从这个launcher定位原进程；因此不能用此前CLI创建的run验证页面取消。

gRPC执行server接收取消后设置termination event，执行进程的termination thread发送中断；Dagster执行器结合实例里的CANCELING状态写CANCELED。资产也每2秒查询取消状态，共享SDK监督器每次poll前检查取消并在finally中terminate/join/必要时kill采集子进程。两主源job虽然使用in_process_executor，正式launcher仍可启动独立的run执行进程；这个executor配置不等于此前CLI运行入口。

上述是当前代码审计事实，不是实际启动/取消验收。没有给正式取消承诺固定完成秒数；SDK清理的两个1秒join不等于整个run的取消时限，也没有把free_slots_after_run_end_seconds=300当成取消超时。

审计覆盖：CodeGraph codegraph_explore核对周/月asset→point→共享source监督器、readiness/reference消费者及相关测试；补读当前jobs、config builders、两个sensor、local_startup.py和安装包DefaultRunLauncher/gRPC/execution/interrupts实现。没有改共享contract、src依赖矩阵、业务代码、资源、配置或API入口。

## 正式取消/续跑的共用操作卡（未执行）

1. **先刷新证据，再审批执行。** 页面及code location须在线，核实location/repository实际名称和加载版本、launcher、daemon健康、job包含本源asset及全部3个blocking checks。读取当前周期日历、日线、身份和准确上游check绑定，冻结目标/staging路径、基线hash、剩余请求预算、分区注册状态及没有active/pending周/月任务；另查看全实例并发槽/队列占用，保留其他任务，不为本次验收取消它们。需要的新动态分区与job执行一并列入该阶段的精确批准清单。不要调用正式sensor preview代替只读预检；它可能包含分区/cursor写意图。
2. **从正式页面Launchpad启动一个主源job。** 分区和配置见两份LLD执行卡；automatic_intent_date取本次初始执行的真实上海日期D。保留run ID、config、source、partition、unit/plan hash及真实staging目录。确认运行后有GRPC_INFO_TAG，不输出其连接内容；缺标记就停止取消验收，保留已运行事实。
3. **选择真实未完成窗口取消。** 优先已有封存页、尚未完成正式提升时点击普通Terminate；只取消精确run ID，不强制标绿。也可以记录采集中被取消的场景，但没有封存页就不能宣称验证了“封存页不重取”。保留取消前后状态、请求账本、receipt/chunk/hash、执行进程/采集子进程退出和最新事件证据。任务先完成或窗口太短，记“未覆盖”，不能删除receipt、伪造意图、缩小正式page_limit或加延时造场景。
4. **取消必须有终态和进程证据。** CANCELING只是请求已登记。要求CANCELED并确认该run执行资源/采集子进程退出，无继续领取请求；FAILURE、残留进程或一直CANCELING均不算通过。若已在原子提升后取消，正式文件保留，单列“提交后取消”场景；不能拿它替代未完成单元续跑。失败时停下审计，不强制修改状态、清理账本或取消其他任务。
5. **原配置启动新的完整job续跑。** 相同source、partition、初始D、根路径与policy，运行ID可以不同；跨日恢复仍保留初始D。使用完整asset+3checks选择，不用仅失败step重执行代替。已封存页的receipt/chunk/canonical hash不变且不重新请求；未封存页可按原持久化尝试余额重取，不能要求它也零请求。预算耗尽如实保留，不通过换D或清账本续命。
6. **独立读回后才推进另一主源。** 新文件/同值文件、schema、键/周期、全字段源对账、delivery proof与准确绑定的3checks一致，run SUCCESS且readiness ready。取消、续跑和成功阶段各自保存实际读写量、耗时、source calls和拒绝原因。每个主源单独记录验收状态；若其中一源错过窗口，只保留该源待办，不回滚另一源成功文件。续跑后的同意图重放应无新增源请求。

单源单意图仍按现行6000行/页、最多4页、每页最多3次尝试，**取消加续跑共享最多12次源请求**；两源合计最多24次，不因新run刷新上限。每源最多10000行/1正式文件；每次成功完整job预期1物化+3检查。失败/取消事件数量记录实测，不承诺零事件。月线最多31日线/320000参考行，周线最多5日线/50000参考行；512MiB/2线程、2GiB spill沿既有配置。没有新增配置、全历史扫描、全量重拉或配额调查。

## 19:30启用的独立操作卡（未执行）

先完成对应频度两主源的新周期及取消/续跑验收，再单独确认启用范围：周线仅raw_stock_weekly_update_job_sensor，月线仅raw_stock_monthly_update_job_sensor；周线不必等月线。沿现有Asia/Shanghai每日19:30开始、最小tick间隔60秒的窗口；这是窗口内按tick检查，不能保证精确19:30:00产生run。

启用前只读记录在线定义/版本、sensor持久化state/cursor、最新物理文件及准确check绑定、最早未完成周期、无pending任务和daemon健康。代码默认history_verified_through为周线2026-09-25/月线2026-09；让现有逻辑逐周期验证并推进，不手写cursor跳过历史或用最大物化日期替代frontier。本轮未新增游标初始化或另一个定时任务。

启用后记录真实19:30窗口tick、reason code、run key/config、动态分区意图和实际run：未完成周期/源未就绪须等待并说明，不能跑本周/本月或自动用备用；只有最早已完成且缺少的主源进入队列，两源串行、不重复提交同一日意图，两源文件与检查ready后才推进周期。停止sensor只能停止新调度，不能替代取消在途任务。若启用当时已无缺口，允许真实skip/tick验证，但“自动提交及交付”仍需下个实际缺失周期；不得把skip当作自动更新全链路验收完成。

## 日期、责任和关闭条件

| 待验证事项 | 最早候选与必要条件 | 下一步/关闭证据 |
| --- | --- | --- |
| 周线正式launcher、两源取消/同意图恢复 | 2026-10-09收盘之后且源已发布、该周实际开市日线及上游checks就绪；当前日历证据为10月8/9日开市，届时重新核实 | 按[周线LLD执行卡](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#后续真实验收执行卡2026-10-06准备完成)刷新、列清单批准后执行；运营确认运行条件，当前任务负责审计/执行记录。 |
| 月线新月原子创建、正式launcher及两源取消/恢复 | 2026-11-01起，2026-10已结束且源已发布、完整10月日线/身份/上游checks就绪；到日期并不自动满足条件 | 按[月线LLD执行卡](../lake_console/docs/design/dagster-stock-monthly-raw-onboarding-low-level-design-v1.md#后续真实验收执行卡2026-10-06准备完成)执行；源日期沿现行自然月末坐标，2020-02例外不改变。 |
| 周线19:30启用及实际自动运行 | 周线取消/恢复验收收口，在线服务/daemon可用，独立启用批准 | 保存真实tick/请求/交付/check绑定；不等月线。 |
| 月线19:30启用及实际自动运行 | 月线新月/取消恢复验收收口，在线服务/daemon可用，独立启用批准 | 保存月线真实tick/请求/交付/check绑定。 |

本轮修改仅1个测试文件、原总方案和两份LLD，新增本报告及运行入口JSON。新增测试是长期回归门禁；/private/tmp/stock_period_update_readiness_20261006仅本任务验证脚本，证据落盘后可清理，不接入Definitions或正式运行入口。文档完整性、158个本地链接及执行卡锚点、改动文件Ruff、项目src/tests致命错误基线与git diff --check均通过。未安装依赖；准备记录随本次提交，未推送，不处理工作区中其他任务的改动。

隔离验证命令（cwd为lake_console/orchestrator，现有.venv；没有设置正式DAGSTER_HOME或访问正式资源）：

```bash
.venv/bin/python3 -B -m pytest -q tests/test_stock_weekly_source.py::test_execution_interrupt_reaps_source_worker tests/test_stock_weekly_source.py::test_cancel_running_worker_kills_process tests/test_stock_weekly_source.py::test_timeout_kills_worker_and_precall_cancel tests/test_stock_weekly_update.py::test_successful_page_survives_cancel_and_resumes tests/test_stock_weekly_update.py::test_process_exit_after_sealed_page_then_resume tests/test_stock_monthly_update.py::test_cancel_after_successful_page_resumes_without_refetch tests/test_stock_monthly_update.py::test_real_process_exit_preserves_captured_page
.venv/bin/python3 -B -m pytest -q tests/test_raw_stock_weekly_update_job_sensor.py tests/test_raw_stock_monthly_update_job_sensor.py
.venv/bin/ruff check tests/test_stock_weekly_source.py
.venv/bin/ruff check --select E9,F63,F7,F82 src tests
```

文档检查从仓库根运行lake_console/orchestrator/.venv/bin/python3 -B scripts/check_docs_integrity.py。测试仅出现安装包既有Pydantic弃用及partitioned AssetCheck preview提示，无失败；本轮不安装或升级套件消除提示。
