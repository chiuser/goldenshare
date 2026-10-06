# DG 股票周线 M4 开发及隔离验收

2026-10-07纠偏说明：本报告保留历史结论；搬运/审计中间数据文件已按管理员要求清理，不再是正式检查或调度依赖。现行口径为 bootstrap 完整对账一次即结束、日常只检查当前新增周期。详见[清理记录](stock_period_reports_cleanup_20261003.md#2026-10-07运行依赖纠偏及清理)。

截至2026-10-03，M3已提交`1638d42b`，未推送。M4完成三份Raw资产、九个blocking checks、三个手动更新jobs及catalog/schema/自然周分区合同接入；本轮M4修改尚未提交。正式Lake、正式Dagster instance、动态分区、bootstrap、runless事件、sensor与schedule均未执行或启用。

## 目标、依据和范围

依据原方案、代码级LLD §3/5/9/15/24和dataset新增模板 §7A。三源独立：`stk_period_bar_week`未复权主源、`stk_period_bar_adj_week`复权主源、`weekly`备用镜像。Raw仅保留源业务字段，复用M1精确schema和path；不增加采集字段、不换单位、不生成复权值、不新增Silver。

| 实现文件（orchestrator下） | 职责 |
|---|---|
| `defs/assets/stock_weekly.py` | 三个真实可执行asset；直接使用统一definition/materialization metadata构造器 |
| `defs/checks/stock_weekly_checks.py` | 每源file contract、key/partition、delivery reconciliation三项检查 |
| `defs/jobs/stock_weekly.py` | 每job仅选择自己的asset和checks，分区从asset推导，无调度 |
| `defs/stock_weekly_point.py` | 有界单周请求、冻结意图、逐页capture/receipt、候选审计与M3原子提升 |
| `defs/stock_weekly_source.py` | 抽取参数化监督子进程；原M2调用签名和语义保持 |
| `defs/run_contracts/stock_weekly.py`、`configs.py` | 统一名称、源文档、点请求预算及受限typed config |
| `defs/catalog/lake_assets.py`、`name_mapping.py` | 三份active catalog、三个自然周partition model、中文名及来源/写入/事件/性能政策 |
| `tests/test_stock_weekly_definitions.py` | 真实job/临时instance/物理文件、分区事件及拒绝反例 |
| 三个现有治理测试/runner文件 | 校准active资产清单、checks治理矩阵和精确源码读取白名单 |

没有改变Prod DatasetDefinition、TaskRun、API、前端或子系统依赖方向。全部新依赖位于独立orchestrator项目。OS隔离runner仅增加九个确切源码文件的读取权限，未增加网络、正式Lake/instance、数据库或写入权限。

## 可执行口径与预算

主源接受一个已注册的ISO周五分区，发送`trade_date=YYYYMMDD,freq=week,limit=6000,offset=页偏移`，显式13/21列；不按股票扇出。每页捕获即落staging并封存receipt；短页结束，满页必须继续，重复key或到达页数/行数上限均阻断，不能把截断记成成功。源空结果阻断，不生成绿色materialization。

备用源仅接受绝对路径、无symlink、冻结hash的单列`ts_code` CSV，最多20只、64KiB，来自reports/正式staging或隔离临时目录。每代码请求该自然周的周一至周日，不用周五点查询，保留真实trade_date。成功空响应保留`success_empty` receipt；全空不交付正式文件，失败不等同无数据。大范围历史缺口仍走M2/M3离线冻结计划。

`StockWeeklyRawConfig`仅有`write_mode=create_or_identical`与`code_list_path=None`，未知字段禁止；主源拒绝code_list。来源为手动job run config，持久化于Dagster run config及staging intent；消费者仅三asset和point适配，不增加env、Settings、数据库配置或页面输入。预算由集中不可变`StockWeeklyPointPolicy`和既有`WeeklyBudget`给出，不接受运营覆盖：6000行/页、最多4页、主源最多10000行、备用最多20代码，重试最多2次，主源最多12次调用、备用最多60次，每次20秒监督超时，调用间至少1秒。源端调用理论上界分别约252秒/1260秒，另加本地处理；这不是ETA，不据此自动扩大范围。

DuckDB统一设置512MiB、2线程、spill上限2GiB；正式提升复用M3同文件系统原子replace、dataset/week锁、逐文件checkpoint和读回。已有目标只接受值一致重放；异值或新增key需离线修订，不通过手动job自动覆盖。进度包含阶段、周、对象/页、已捕获行；等待源调用每10秒更新，ETA明确不可估算。单页最多6000行的DataFrame用于源传输，合并/校验/COPY均由DuckDB完成，不积攒全历史。

九个checks只读当前周真实文件。delivery check读取当前分区最新materialization引用的封存audit、source receipts及hash，独立核验源控制行数、候选逻辑hash、实际文件hash/行数；文件或证据变化阻断。没有用asset返回的row_count作为唯一对账依据，没有源网络请求，没有创建spill或正式目录。

## 真实证据与性能

[源实测JSON](dg_stock_weekly_m4_source_probe_20261003.json)：两主源针对`000001.SZ/20250926/freq=week`分别实测默认字段、全量文档字段、关键字段显式请求，均返回1行。身份字段包含`ts_code/trade_date/freq`，时间字段包含`end_date`。本次原始源返回end_date为20251024、复权源为20260930，均不同于trade_date；Raw按源保留，不能将end_date当该周末或强行改写。接口选型/对象/区间/SDK分页的前序证据继续见M0；MCP工具未暴露limit/offset，本次不冒称用MCP完成分页实测。

隔离交付JSON（历史中间文件已清理）：将本次两套MCP真实返回重放至私有临时目录，均源1行、归一化1行、写入/读回1行、reject0，所有业务字段双向EXCEPT ALL差异0。耗时分别0.0783/0.0825秒，仅含离线交付与对账。

容量样本从一条真实业务行生成10000个合成代码，6000+4000两页，offset为0/6000，最终1个8950字节文件、10000行，交付与delivery check共1.2962秒。累计峰值RSS276.156MiB、spill0。代码和高压缩重复价格为合成样本，不代表真实市场文件大小、传输耗时或全历史性能；未完成强制spill验收。正式端到端网络与Lake执行须在M5/M6获准范围验收。

## 验证及影响面

- M1–M4定向及静态门禁共218 passed；最后的config类型校准后17个真实definitions测试及113个static tests再次通过，最后请求参数断言追加后17个definitions测试再次通过。
- OS隔离既有runner：asset治理12项及465个subtests；增量checks治理6项，均通过。测试真实临时instance中的九个check evaluations和execution history，partition均为`2020-02-28`，不是仅断言装饰器参数。
- `dg check defs --use-active-venv`使用临时DAGSTER_HOME、现有.venv及假的连接配置，完整项目加载成功；不执行asset/job/sensor，不安装或同步依赖。
- 新模块、修改的纯合同/catalog/source/tests默认Ruff通过；configs.py的11项既有DTZ007/TRY004未扩大修复，均在HEAD原行存在。全项目致命错误Ruff基线、docs integrity及diff检查通过。
- 5条库警告包括4条既有Pydantic警告、1条Dagster显式check分区PreviewWarning。当前1.13.18真实事件和执行表均验证分区正确；升级需保留此回归。

CodeGraph使用CLI sync/status、query StockWeeklyPointWorker、impact PartitionModelFamily及两层fetch supervisor，结合直接imports/消费者搜索核验asset→point→capture→DuckDB候选→promote及asset/check/catalog/job关系。图中enum影响面不完整，已读当前实现补审：通用历史materialization reconciliation仅处理TRADE_DATE_PARTITION，未擅自将自然周加入其旧日期路径；周线正式历史事件由M7专项实现。没有周线sensor/schedule消费者，M9仍待完成。

首次OS runner因嵌套sandbox-exec启动受限，改用获准的沙箱外启动，仍保留runner内部拒绝网络/正式资源规则。初次重复行测试被M2提前拒绝，最终断言正确reason code `source_duplicate_key`；跨页重复另断言`raw_duplicate_key`。未放宽测试门禁。

## 后续阶段

M4开发及隔离验收完成，尚未提交。M5需先冻结真实Prod库存/边界、相交邻年capture计划和聚合对账预算，获准后再做小范围正式bootstrap及扩展。M7负责周线runless事件与历史delivery证据，M9负责自动更新/readiness、历史修订和启用验收；第一阶段不能因M4完成就宣布周线更新机制已正式启用或全部缺口已补齐。
