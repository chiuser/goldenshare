# 股票周线 M9 开发与只读验收

日期：2026-10-04，Asia/Shanghai。依据原方案与LLD§34，每日19:30更新已结束周，两主源串行；备用weekly仅用于明确手动任务。M9开发已落地，正式验收尚未完成。

## 已落地与验证

- 新sensor默认STOPPED，时间门禁前不读Lake/DB/源；每日每源/周一个意图，不按tick重开任务。无交易周跳过，欠账只逐周推进。
- 原point交付主链增加稳定自动assembly、receipt读回复用、持久化每页请求计数和请求间隔、执行锁、完整周门禁；不新建业务writer。手动默认参数保持原语义。
- 源trade_date保持自然周五；end_date按个股当周最后实际日线日期比较，身份只用于审计。冻结证据供正式delivery check复核，不改Raw源值。
- 已有正式文件同值可复用；异值生成revision_required.json并停止。取消/进程退出保留已完成页；提升后观测失败保留已提交文件，原意图可恢复。
- 11组相关回归167项通过，包含真实临时进程退出、取消续跑、请求预算不重置、两源实际job的三个分区checks、截断分页、源未就绪和修订反例。新代码/weekly改动Ruff通过；共享configs.py既有11项lint问题未扩大处理。

## 正式只读证据

最终预演报告：`stock_week_m9_readonly_preview_verified_20261004.json`。模拟19:30，首个欠账2026-10-02；上游checks通过。耗时约0.268秒，16次事件API，95条返回记录；只生成一个主源任务及一个新周分区注册的预览，未执行。

两源MCP样本各5565代码，匹配9月28/29/30日线代码并集。未复权5561行end_date=20260930，3行=20260929，1行=20260928，均符合个股实际日线；不得统一要求月底/周五。旧周end_date可以晚于所属周。

日线现行4个checks按target materialization绑定日期，未使用check.partition。最初分区过滤导致误报，已按当前实现校准；历史报告保留过程证据。最终读取每个check最多20条、全周最多50条materialization，找不到目标即阻断，不复用共享5000条深扫预算。

## 改动范围与剩余门禁

新增weekly planner、source readiness、update execution/state、sensor及两组测试；修改原weekly asset/point/check/job、统一config/request builder、catalog weekly事实卡、精确静态definition清单和隔离器源码只读清单。没有改变Raw/Silver/Gold路径、源字段合同、src子系统边界或业务数据库。

2026-10-04续验已解决共享测试清单漂移：隔离启动器补齐7个公告源码的精确读取权限；资产治理测试补登记实际已接入的raw_tushare_anns_d。没有修改公告业务代码、删除断言、开放正式数据读取或网络。

完整113项静态检查通过；12项资产治理检查通过，含468个subtests。改动的两个测试文件默认Ruff及全src/tests致命错误基线通过。现有dg CLI通过临时instance完成整个code location定义加载，输出“All definitions loaded successfully.”；使用已有环境、无依赖同步或安装。临时隔离逐项放行源码、项目配置、目录元数据及本次临时SQLite写入，网络和正式Lake/DB访问均禁止。报告：`stock_week_m9_defs_validation_20261004.json`。

剩余顺序：获准的最小正式两源交付与取消续跑读回 → 正式启用19:30 sensor。静态/隔离验收通过不等于正式更新已经完成；当前仍未提交Git、触发正式任务、注册分区或启用调度。

## 后续最小正式执行范围（待门禁通过与管理员批准）

- 周：2026-10-02；两主源jobs串行，各只选择本asset和原三个blocking checks。
- 新周dynamic partition一个；正式Raw最多两个文件，当前源样本预计每源5565行，合计11130行；原文件存在/差异则停止。
- 两源正常预计共2次请求，硬上限24次含技术重试；最多2个materializations+6个实际checks，不使用runless，不调用备用。
- 候选与执行证据仅在正式staging；完整验证后同文件系统原子提升。失败保留证据和已提交unit；不清表、不快照、不写Prod/Silver。
- 最小验收通过后才启用唯一weekly sensor。当前没有提交Git修改、启动任务、注册分区或启用调度。

## 管理员确认延期（2026-10-04）

管理员查看Tushare源站后报告2026-10-02周线尚未生成，要求暂记并先推进后续任务。本周最小正式验收待源端就绪，调度保持停止；这是管理员核查事实，非本轮重查API的空结果。历史MCP样本和预演不替代可交付版本证明。正式源调用/写入/分区注册均未执行；后续月线工作不能替代M9验收。
