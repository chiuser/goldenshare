# 周/月线正式运行入口只读复核通过

2026-10-06阶段收尾说明：本报告保留当时审计/准备事实；本需求已按管理员决定暂时结束。当前开发及数据交付结果、未来日期/条件和恢复入口见[收尾记录](stock_period_raw_closeout_20261006.md)。后续执行卡继续有效，但没有自动启用授权；旧时刻服务状态不作为执行时承诺。

2026-10-06 18:41–18:43，Asia/Shanghai。依据管理员“按照你的建议继续推进”，完成后续任务第1步：正式页面、code location、launcher、daemon及已加载job合同复核。此次仅查询已有状态和Lake日历，没有启动/停止服务、执行job/check/sensor、注册分区或修改cursor/event。

## 结论和证据

| 事项 | 实际结果 |
| --- | --- |
| 正式页面 | 127.0.0.1:3000/graphql可访问。08:39拒绝连接的观察保留为历史，此时服务已在线，本轮没有执行恢复/重启。 |
| 代码位置与仓库 | location=orchestrator，LOADED，具有gRPC server；repository=__repository__。location版本267c98bd-bce5-44c9-a8a9-2b710b21b8bb，四job快照ID随JSON保存；这是加载快照证据，不是Git提交号。 |
| Launcher | 在线实例明确返回DefaultRunLauncher，与原执行卡采用Launchpad启动、Terminate取消的路线一致；此前CLI run仍无gRPC取消标记，不能复用它们验收取消。 |
| Daemon | SENSOR、SCHEDULER、QUEUED_RUN_COORDINATOR、MONITORING、BACKFILL、ASSET及FRESHNESS_DAEMON全部healthy；PG心跳距审计时刻约22–42秒、错误数均0。 |
| 两个sensor | 页面实际状态和默认状态均STOPPED，lastCursor/lastTickTimestamp均null；PG无该两sensor持久化state，页面按已加载默认值展示停止。没有启用或试运行。 |
| 并发/队列 | 全实例NOT_STARTED/QUEUED/STARTING/STARTED/CANCELING任务计数0；四主源最新run仍为前轮SUCCESS。现有实例最大并发run=1，不改配置。 |
| 加载合同 | 四个主源job分别包含本源asset和file_contract/key_partition/delivery_reconciliation三个blocking checks，checks确实属于对应job和asset。资产配置都包含automatic_intent_date；在线四项合同核对全部通过。 |
| 下一周条件 | 2026-10-09尚未结束；真实日历开市日为10月8/9日，两日Raw日线文件均不存在，上游checks未ready，两源该周目标文件不存在。取消/续跑执行条件为false；这是未来周期等待，不判为历史缺口。 |

[在线状态与下一周证据](stock_period_update_live_recheck_20261006.json)保存实例身份、配置hash、launcher/daemon、sensor、运行记录与日历指纹；[已加载四job合同](stock_period_update_loaded_jobs_20261006.json)保存GraphQL纯query、实际返回和逐job核对。没有打印token/密码、环境变量或进程完整命令行。

## 本次读取范围与实现核验

读取当前local_startup.py、安装包GraphQL schema/DefaultRunLauncher、instance daemon方法及SQL读取实现，复用原open_weekly_event_instance的禁止自动建表只读入口、load_weekly_calendar和weekly_upstream_events_ready。没有引入另一个正式实例或运行入口，也不调用DagsterInstance默认初始化。

两次本机GraphQL只读query：workspace/运行设施以及4个job/4个asset的定义，后者每个asset最多取4个check以发现超出预期3项的情况；不读取全历史物化。PG读取四job各最新1条、pending各最多10条、全局pending聚合、两sensor状态和7类心跳。Lake只读日历一个有界周窗口、2个日线及2个目标的存在性，未读行情全历史；DuckDB沿512MiB/2线程和existing_no_spill，仅private/tmp可用作审计临时目录。

正式源请求0、正式文件/event/动态分区/cursor/sensor写入0。命令运行时间分别约1.345秒和0.103秒；两次审计的编写/核验间隔不算运行时间，没有测量RSS峰值。使用现有项目.venv，没有安装、reload、重启或提交/推送操作；private/tmp脚本仅本次验证，证据存档后可清理，不接入Definitions。

## 后续任务的当前状态

1. **正式运行入口复核：已完成。** 在线位置/仓库和完整job已经确认；实际执行前仍需刷新该时刻状态，避免使用过期快照。
2. **周线真实取消/同意图续跑：待2026-10-09收盘后且源、日线、检查就绪。** 逐源按原[周线LLD执行卡](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#后续真实验收执行卡2026-10-06准备完成)冻结实际日期D和范围，再按该阶段执行；现在不伪造未完成场景。
3. **周线每日19:30启用：待第2项收口并独立批准。** 验证真实tick/提交/交付，不等月线；备用保持仅显式手动。
4. **月线新月创建和取消/恢复：待2026-11-01起、2026-10源及完整上游就绪。** 仍合并执行减少重复取源，遵守[月线LLD执行卡](../lake_console/docs/design/dagster-stock-monthly-raw-onboarding-low-level-design-v1.md#后续真实验收执行卡2026-10-06准备完成)。
5. **月线每日19:30启用：待第4项收口并独立批准。** 自动提交与交付证据单独留存。

本轮更新原总方案、两份LLD的当前入口状态及前轮任务清单引用；新增本报告与两份JSON，不改业务代码、配置、依赖矩阵或API。只读条件通过不代表正式取消/自动运行已验收，M9/M10.F保持未完成。文档完整性、170个本地链接、在线状态/四job JSON对账及git diff --check均通过；未重复运行已经通过且未变化的32项隔离测试。管理员随后要求提交，本轮记录随本次提交；未推送。
