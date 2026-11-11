# 股票技术因子 DG 数据集接入 LLD v1

日期：2026-11-11。状态：源端代码齐备、完整日发布和指定日期人工补跑的现行设计见§21。前五批及第六批前两步是已有代码基线；新规则第1～4小步已完成开发、隔离验证及独立审计，见§21.16～21.19。第5小步的上游/日摘要读取已实现，隔离验证及独立审计结果见§21.20；全仓治理因工作区其他新增sensor未登记而未通过，尚未全部验收收口。第6小步及以后未实施。正式资源操作按阶段另行授权。

依据：[原技术方案](dagster-stock-technical-factor-onboarding-plan-v1.md)、[DG接入模板](../templates/dagster-dataset-onboarding-template.html)、[性能治理规范](dagster-data-pipeline-performance-governance.md)、[Prod审计报告](../../reports/stock_factor_pro_prod_audit_20261021/README.md)。下载器依据[组件LLD](dagster-tushare-download-component-low-level-design-v1.html)与[业务使用文档](../architecture/tushare-download-component-usage-v1.html)，不在本数据集重做。

精确阶段引用、实际发布日期通知和隔离验收均按§19落实，历史设计修正及本批证据分别记录于§18.8和§19.10～19.13。第五批的Definitions验收通过现有隔离入口完成。

## 1. 范围、日期与已经拍板的规则

本文所称股票复权因子数据集，是现有 Tushare `adj_factor`（DG Raw资产`raw_tushare_adj_factor`）；技术因子数据集`stk_factor_pro`中另有同名`adj_factor`字段。前者是变化名单、历史回刷和输入修订的依据；后者保持源业务值。日发布及常规历史回刷记录差异，已完成后的自动追修按§3.6核对可对照记录。

历史从Prod bootstrap，缺口在导入过程中按§10.5利用本地数据统计，不以前置Prod全历史覆盖审计放行；范围已确定为正式开始时在来源维护窗口内确认的`raw_tushare.stk_factor_pro`全部现有业务数据，包含全部股票（含退市股票）、全部日期及261业务字段，不按固定年份或当前上市名单裁剪。先完成物理导入及完整性审计，数据完整后才能补历史事件；历史事件全部补齐、核对通过并另获启用批准后，DG直接从Tushare日更和获取必要历史。合法已导入文件可读，不等于初始化已通过；不把每日来源改回Prod，不迁移其他数据集。

**bootstrap只在开发阶段使用，上线后不再执行。**适用范围固定如下，后文初始化接口、上下文、记录和预算均受本段约束：

| 使用场景 | 输入、输出及编码边界 |
| --- | --- |
| 开发阶段Prod搬迁 | §10.1～10.5导出及恢复，保存本次导入批准、完成事实和缺口。实际目标可以是正式Lake目录；这不代表已经上线。 |
| 开发阶段上线前初始化补数 | §10.5.6～10.7使用`bootstrap_supplement`人工用途，复用日更job从Tushare补日数据及必要历史；仅本用途及其上线前重新执行/历史repair读取原导入记录、保存bootstrap_context、更新导入result/summary。全部初始化补数、必要历史和统计须在上线前收尾。 |
| 上线后日更、日更重新执行及历史repair | 使用DG正式文件、已有Dagster运行/物化/check、覆盖和历史范围事实，从Tushare更新。bootstrap三项配置为None，阶段观察bootstrap_context为null、bootstrap_coverage_refs为空tuple、bootstrap_summary_ref为None；不读取原初始化批准/导入完成/缺口汇总，不调用初始化resolver或统计收尾函数。 |

operation_id只是这次初始化导入的编号。共用代码与复用已确认的历史边界，不等于上线后继续运行bootstrap或维护导入统计；已有历史边界可从DG范围事实取得，不依赖重启bootstrap或原导入统计目录。普通任务即便读到旧初始化观察，也只消费所需DG发布/历史范围事实，不继承初始化用途。区分用途沿用既有配置、调用路径和开发阶段人工执行范围，不增加“是否上线”开关、表、锁或隐藏Definitions机制。

| 日期名称 | 定义 |
| --- | --- |
| 执行日D | 上海自然日期，记录本次执行的安排日期。自动日更只在开市D运行。 |
| 目标日T | 本次实际更新的交易日。自动T=D；人工可以明确指定历史交易日。 |
| 前交易日P | T的`pretrade_date`确认的严格上一SSE开市日，用于股票复权因子比较。 |

现行日更入口、源端代码齐备、完整日发布及指定日期补跑集中在§21。上市首日股票代码可选，其他股票按目标日纳入必需集合，确认全天停牌扣除，盘中停牌保留，按目标日期统一身份。源端必需缺码或未知多码均不提交自动job。日更job正式下载后也须在发布前确认代码集合相等。

每次日更先读取权威股票复权因子T/P，保存完整变化名单及同T待刷范围，先完成目标T日数据，再按原规则回刷d<T。§3.6、§5的复权比较、范围、历史起点、整范围成功和失败重下继续适用。

日下载只在本run内存中保留，成功关闭会话并核summary后才构造候选。新run完整新下载，逐文件发布安全和资源复用继续按§8、§18执行。

### 1.1 一次同步任务内的统一复用规则

一次同步任务是一个日更/repair run，或一次bootstrap入口执行。首次需要时取得输入并计算结果，主入口持有数据、原批准/计数/记录、PG事实、SQL关系、审计、覆盖及摘要；以后各函数直接接收这些值。同一版本的业务数据、小记录、事件、统计和摘要都不能按函数或阶段重新读、重新算、重新审。

一个日期只保留一份当前有效统计。新版本计算一次，只有持久化成功才替换为新有效结果；旧结果因实际变更失效时先退出有效合计、如实标未知。上线后RawCoverage、历史资格和进度共用本次结果；只有开发阶段初始化还生成BootstrapDateCoverage及导入summary，普通任务不创建或维护它们。summary不自行打开任何记录/业务文件、不查PG、不重新求和。写入持久记录后直接返回已得对象和摘要并更新本任务变量，不让下一步从磁盘取回刚生成的结果。

源或新候选首次格式/传输审计一次；源组合成日、候选移动到正式路径仍使用同一份事实。候选实际写入首次读回属于新输出传输审计，此后不再打开其正式副本复审。实际变换和必要写入可消费本连接已有关系，不能以“业务需要”重读已持有输入。源审计的具体项目见§18.3。

新进程/新run首次加载必要持久事实一次；Tushare失败新run仍完整新下载。固定事实复用与运行控制区分：取消、当前时间/实际磁盘剩余属于会变化的新状态，只在既定边界观察。输入身份变化停止本轮，不在本次重审后继续。仅使用任务局部变量和现有主要连接，不创建通用缓存平台、全局字典或新状态表。

## 2. 定义、代码结构与接口

### 2.1 Dagster定义

| 对象 | 固定名称与职责 |
| --- | --- |
| 源契约 | `stk_factor_pro`、独立`version="1"`；261个完整源业务字段；固定HTTP；使用BY_POINT与BY_OBJECT_RANGE。 |
| 两个资产 | `raw_tushare_stk_factor_pro`、`silver_stock_factor_pro`；日数据依次发布，后续历史仍写这两个资产的旧日期，不新增清单/完成状态资产。 |
| 分区 | `cn_a_stock_factor_pro_trade_days`；两资产及两项check共用；只日常新增今天和Q，旧键不删除。 |
| 日更job | `raw_tushare_stk_factor_pro_update_job`；上线后用于自动单T/单轮及原生日更重新执行，包含名单、日发布和必要历史。开发阶段上线前另复用该job的bootstrap_supplement人工用途补齐初始化数据并更新导入统计；上线后不使用该分支，不由sensor生成，不另建补日job或自动历史job/sensor。 |
| 管理员手动历史job | `raw_tushare_stk_factor_pro_repair_job`；只恢复原目标日、原批名单/范围的历史，复用同套历史函数，不发T全市场BY_POINT日请求、不执行T日发布；无自动sensor，精确输入见§4.1。 |
| 注册sensor | `stock_factor_pro_trade_day_sensor`；按日历新增今天及Q，不下载，不等Tushare或因子就绪。默认STOPPED。 |
| 更新sensor | raw_tushare_stk_factor_pro_update_job_sensor；只自动选当天，通过本地前置及源端两列代码严格匹配才提交，默认STOPPED。 |
| Raw综合check | raw_tushare_stk_factor_pro_file_contract_check；原有字段/主键/日期和来源/候选对账；日源覆盖准入另在提升前完成。 |
| Silver综合check | `silver_stock_factor_pro_file_contract_check`；对应Raw、DATE/主键、完整261字段及逐行对账；本期不增加清洗过滤，后续新增规则不是前置。 |

采用一个`@dg.multi_asset`定义两个资产，在一个同步生成器内明确执行日Raw→Raw检查→日Silver→Silver检查→原T Raw齐备判断→历史。两个`AssetSpec`均声明`skippable=True`，`can_subset=True`让没有实际文件的分支能够省略物化和检查输出。业务入口仍必须完整选择两个资产及两个检查；job固定完整selection，asset函数在任何预检、下载或写入前按本节规则再次核对，不能只选Raw、只选Silver或漏掉检查。

固定期望集合为`{dg.AssetKey("raw_tushare_stk_factor_pro"), dg.AssetKey("silver_stock_factor_pro")}`及对应两个`dg.AssetCheckKey(asset_key, check_name)`。asset开头精确比较`context.selected_asset_keys`、`context.selected_asset_check_keys`与这两个集合；任何缺项、额外项或只选检查均抛`dg.Failure(..., allow_retries=False)`，按§6.1输入/契约错误记录`failure_phase=precheck,retryable=False,source_error_code=None`，零技术请求、零业务文件写入、零物化/check。不得自动补选、忽略选项或以`can_subset=True`为由开放业务局部更新。完整selection通过后，实际分支仍可能因预检等待或无可用日数据而没有文件输出；其终态分别按§4和§4.0.1判断。

`check_specs`恰好两个，使用`AssetCheckSpec(..., blocking=True, partitions_def=cn_a_stock_factor_pro_trade_days)`。日检查用`AssetCheckResult`，severity为ERROR；**同一multi_asset内失败后，业务必须显式停止后续步骤**，不能只设置blocking就继续写Silver或历史。候选提升前先用同组必要校验，发布后check不能代替撤销错误写入。

### 2.2 拟新增/调整的文件

路径相对`lake_console/orchestrator/src/orchestrator/`。

| 文件 | 责任、接口和禁止项 |
| --- | --- |
| `tushare_download/contracts/stk_factor_pro.py` | 一份完整源字段、参数、模式、分页；其他消费者引用，不抄261字段。 |
| `tushare_download/contract_registry.py`、`dataset_transport_mapping.py` | 解除`@version`名称绑定、登记契约和HTTP；无旧名别名，不迁移其他消费者。 |
| `defs/run_contracts/stk_factor_pro.py` | 本数据集资产/check身份、执行日/目标日/轮次、输入和业务记录结构，以及§10单处维护的时点、sensor间隔、20日合并/5000行导出参数和验收目标；不请求网络、不复制既有DuckDB默认。 |
| `defs/run_contracts/asset_column_schemas.py` | 从源字段维护Raw日期VARCHAR、Silver日期DATE及259个可空DOUBLE的本地映射，不把存储类型回写源合同。 |
| `defs/paths.py`、`partitions.py` | 正式/候选路径与专属分区，不使用旧Lake、任意路径或新的配置入口。 |
| `defs/sensors/stock_factor_pro_trade_day_sensor.py` | 只注册今天和Q。 |
| `defs/sensors/raw_tushare_stk_factor_pro_update_job_sensor.py` | 只选当天、同slot去重、本地上游及源端两列集合检查，见§21。 |
| `defs/asset_guards/stk_factor_pro_readiness.py` | 输入就绪、已发布可读、覆盖及历史未完分别判断；纯代码集合函数供日更/bootstrap统计共用，但不带入含instance日更前置。提供活动任务检查、原run/PG观察身份读取及§6.2结果读取；不import bootstrap模块。 |
| `defs/io/stk_factor_pro_history.py` | 技术因子下载前的完整名单；原T Raw齐备后完整历史范围；历史前输入再核对、窗口和完整发布依据。 |
| `defs/io/stk_factor_pro_download.py` | 日完整unit及最终summary仅在当前调用内存核验；历史完整unit逐个保存/读回，全部会话成功后才形成历史源完整记录；适配组件通知。不保存日下载中间文件，不重试业务写入，不把实际开始记录藏在进度回调。 |
| `defs/io/stk_factor_pro_candidates.py`、`stk_factor_pro_publication.py` | 按日期批量合并、必要校验、同文件系统提升与逐文件记录；T日唯一来自日阶段，历史只合并d<T。 |
| `defs/checks/stk_factor_pro.py` | 两项检查的规格及纯校验，multi_asset内调用；不另定义同名check形成重复注册。 |
| `defs/assets/stk_factor_pro.py`、`jobs/stk_factor_pro.py` | 同一multi_asset/job的七字段分支装配、bootstrap首次/重新执行授权、完整日更和必要历史、按阶段/批次更新统计；不建线程、子进程或额外job。 |
| `defs/ops/stk_factor_pro_history_repair.py`、`defs/jobs/stk_factor_pro_history_repair.py` | `repair_stk_factor_pro_history` op的4项必填配置/预检/历史新下载与手动repair job装配；不注册自动sensor，不调用日下载/发布函数。 |
| `defs/bootstrap/stk_factor_pro_history.py` | 原operation批准/源/导入记录、按月5000行服务端导出及覆盖；§10.7 bootstrap授权resolver编排，调用readiness已有PG身份/纯集合函数；§10.5.6补数后统计更新。仅开发阶段初始化用途的asset/op组合调用本模块；上线后普通用途不调用其导入授权/统计收尾，不从readiness反向import本模块。不累积整月、不经下载器导出Prod、不做Prod全历史覆盖预审；正式执行另批。 |
| `defs/catalog/lake_assets.py`及定义装载入口 | 两资产事实登记；现有catalog不是动态生成所有运行定义的引擎。 |

依赖：装配→sensor/资产/check→本数据集业务函数→组件/既有DuckDB和路径。不得跨工程import Prod定义或Ops入口，不替换其他数据集配置/下载/写入。token和地址直接用组件现有配置单元读取。

### 2.3 业务函数的数据输入与输出

以下定义本数据集内部函数接口；参数传dataclass/不可变记录，Parquet内容不放进sensor cursor。第三批历史规划、下载和发布的完整签名、输入与批次边界以§16.2为准，不能把本表的(...)当成允许任意参数的实现。

| 函数 | 主要输入 | 输出与必须保证的行为 |
| --- | --- | --- |
| `select_stk_factor_pro_request(...)` | D、当前slot、已提交/活动run、T的有效结果、本地上游及源端代码比较 | 一条当天T的请求或明确skip；不生成历史名单。 |
| `read_stk_factor_pro_other_active_runs(instance, *, own_run_id=None)` | 同一正式instance、可选当前run_id；固定两job及五种活动状态 | 返回至多4个其他活动任务的原生DagsterRun对象；每job一次limit=2查询，不按目标日期过滤，查询失败不得伪装为空。详见§4.2。 |
| `require_stk_factor_pro_no_other_active_runs(instance, *, own_run_id=None)` | 上述同一读取接口 | 无其他任务才返回；有冲突或读不到事实则立即Failure、allow_retries=False，给出任务身份及下一动作；不循环等队列。 |
| `require_stk_factor_pro_inputs(...)` | T、P、对应股票复权因子Raw因子路径及其真实就绪结果 | 已核对的T/P输入身份/指纹；不足就不下载，不能返回“没有变化”。 |
| `build_stk_factor_pro_history_plan(...)` | 当前T/P完整因子、可信历史范围、DG记录定位的同T未完成/成功事实 | 每次日更新重新比较并在技术因子请求前保存本run完整名单；合入已有原未完成范围，输入未变时业务摘要可相同，但不把旧plan直接当本run新计划或下载完成。T/P重比相等不抹掉旧待处理；原下载前未生成计划不妨碍重新规划。 |
| `download_stk_factor_pro_day(...)` | T、本run身份、已持久化的开始事实 | `VerifiedDaySource`：当前内存中的唯一完整日`UnitResult`、已成功关闭的最终summary及本次身份/摘要；不写文件，源少股票不缩减原变化名单，网络半unit不返回成功。 |
| `publish_stk_factor_pro_day(...)` | 本次`VerifiedDaySource`、T已发布文件及目标预期、必传on_raw_candidate回调 | 从当前内存U与正式B直接构造唯一Raw发布候选，候选唯一审计后先执行回调代码检查，再提升/记录并从Raw生成Silver候选及发布结果；按主键更新补入、旧未返回行保留。不先写另一份日源Parquet。 |
| `require_stk_factor_pro_history_raw(...)` | 仅§5.2原T Raw覆盖结果 | 不为True就抛约定Failure；日更在完整日发布及绑定后调用，repair在历史请求前直接调用，不保留部分日发布后的缺股等待分支。完整名单/范围由各自后续流程另核。 |
| `download_stk_factor_pro_history(...)` | 原T Raw齐备、target_silver.ready=True、完整原失败范围、再次核对的权威T/P | 当前run全部unit全新下载/保存/读回；失败新run不复用旧source-complete。 |
| `publish_stk_factor_pro_history(...)` | 完整历史源、名单/基准、现有d<T文件 | 仅更新d<T；历史响应的T仍完整留在源候选并用于核对，不覆盖日阶段T。 |
| `summarize_stk_factor_pro_result(...)` | 文件读回、两层checks、覆盖、完整名单/历史结果、错误 | 分别说明可读数据、缺股票、待回刷、两接口差异和本轮终态；不增加覆盖状态资产。 |
| `repair_stk_factor_pro_history(...)` | 手动配置指向的原T、原完整名单/范围和原批次 | 不重新计算扩大授权范围；核原T Raw齐备及原T Silver有效且对应当前Raw后，重新下载完整原失败范围，复用同套业务函数，只d<T，无BY_POINT或T提升。 |

### 2.4 日更入口与人工指定日期

`ops.stk_factor_pro.config`为唯一配置入口，`StkFactorProRunInput`及schema由`defs/run_contracts/stk_factor_pro.py`维护。目标日必须等于分区，具体七字段、用途和消费者见§21.4。人工指定历史日期复用同一update job，允许首次提交，无需先有失败run；也可在已核原任务身份下重执行同一T。

正式源下载继续使用完整契约；两列源端齐备查询是业务准入，参数和调用落点见§21.2。没有fields、地址、路径、账号或分页的运营覆盖参数。初始化`bootstrap_supplement`仅在上线前按§10.7核原批准并更新其result/summary。普通人工补日不进入初始化分支。

### 2.5 主入口持有的对象与完整串联

下列是asset/op或bootstrap主函数的局部变量清单，不是新增组件、全局单例或独立持久账本。使用现有冻结类型及字典按日期/真实身份索引，通过内部参数显式交接；参数缺失即接口错误，不允许helper自行回盘、查询或计算补齐。

表中列出的是不同使用场景可能需要的对象，不是要求每个任务全部加载。上线后普通日更/repair不创建初始化日期账本及总汇总，不读取导入批准/计数/SourceComplete；这些仅由开发阶段Prod导入或上线前初始化补数持有。初始化汇总所需小记录首次读取范围及成本单独列明，后续只用同一任务内的结果，不回读业务文件或重复求和。

| 本任务持有内容 | 首次取得/更新者 | 所有后续消费者及生命周期 |
| --- | --- | --- |
| 已解析记录及其摘要：路径→(对象,摘要) | 入口首次读取必要旧事实；writer产生新版本后直接返回替换 | 批准、来源、计数、plan/ranges/manifest、source/intent/complete、日期result共用；一个版本本任务只读一次，不每helper序列化/反解析。 |
| 已核run/观察/物化/check：真实身份→对象 | §6.2及授权首次读；本run新yield首次持久化后首次取id | 资格、授权、阶段结果、bootstrap收尾共享；旧事实不重查，新事件是新事实；当前20日批映射使用完释放。 |
| 批准计数及来源/固定预检结果 | bootstrap首次需要Prod时取得 | 月规划、recover/pending、写SourceComplete及统计共用；每月不同计数窗口首次一次，不各自再preflight。 |
| 全局依据及当日停牌关系/身份 | 本任务覆盖准备首次取得 | 日历/生命周期/身份按连接复用，当日停牌一次；Raw覆盖、bootstrap统计、历史资格共用，未变不再prepare。 |
| 当前日B、U、RAW_EXPECTED、旧Silver及键关系 | 本日首次读取/生成 | 合并、等价比较、Silver生成、一次覆盖/差集、scope结果均用同一关系；本日需要数据的合并/转换/覆盖/scope完成并交出小结果后释放；后续事件/记录只消费小结果，禁止再读Raw补回。 |
| 本次历史源关系 | 下载每个unit首次读取/审计时写入同一主要连接 | 保留至本任务历史完成；20日批从此关系取数，既存源Parquet只作本次源证据，不被每批重新打开。网络UnitResult/DataFrame仍逐unit释放。 |
| 单日覆盖counts、missing/extra关系及引用 | 本日首次必要代码集合运算 | 两种统计记录及历史门槛共同消费；非零明细写一份，计数/样本/引用交出后释放关系，记录包装不依赖该关系。 |
| 日期账本及各日期贡献/合计 | 入口首次加载已有结果；本任务产生新版本时替换 | 单日任务只持一份当前日期结果；bootstrap保存原批准范围小型结果，不存全历史Python行。summary直接使用已维护的合计/集合/摘要，退出时释放。 |

known_pg、known_records均由入口创建一次并必填传入上述消费者；它们只保存本任务局部事实，不是新增类/服务。固定键和值如下，消费者不得自建另一份字典、接受未知kind或将运行控制状态放入：

| 字典/键 | 值与取得规则 |
| --- | --- |
| known_pg[("run",run_id)] | 已核原生DagsterRun或已确认不存在的None；入口已有current_run直接登记，其他run仅首次缺少时精确读取。取消/当前活动状态仍走既定实时检查。 |
| known_pg[("observations",T)]、[("observation",storage_id)] | 本T首次有界观察tuple及按真实storage_id登记的原生EventLogRecord；已在tuple中者不再精确查一次，缺少明确引用时才首次读取。 |
| known_pg[("recorded_results",T)]、[("first_observation",run_id)] | 本任务首次组装的StkFactorProRecordedResults、原生重执行/初始化授权共用的首条观察tuple；只保存已取得对象，后续不重发同一查询。它们是第五批入口查询结果索引，不是持久化或跨任务缓存。 |
| known_pg[("latest_day_runs",T)] | 本T首次有界日更run查询结果；其run对象同时登记run键。授权和结果reader共同使用。 |
| known_pg[("materialization",asset,T)]、[("check_execution",asset,check_name,T)] | 本任务已得原生物化/分区检查记录或已确认不存在的None；新yield后的新记录用真实身份更新，不再次查询同一旧记录。 |
| known_pg[("check_event",storage_id)]、[("failure",run_id)]、[("phase_result",storage_id)] | 对应真实check事件、§6.1首次解析的失败metadata或未知结果、已解析既定阶段结构；不同编号和类型不混用。 |
| known_records[受控绝对Path] | (已解析原记录或已核文件audit,字节摘要,文件身份)。JSON首次读取一份字节后登记；本次writer直接登记返回对象/payload摘要/保存后stat。业务文件登记首次audit或首次加载的文件身份/摘要。 |

asset/op的既得当前日/当前20日批事件直接登记上述映射，bootstrap当前发布结果和资格检查使用这些对象。只有新物化/check首次持久化后为取得真实id的必要查询属于新增事实；check execution id与evaluation事件storage_id不得互猜。批次消费者结束后可释放该批完整事件对象，仍有后续引用的身份/摘要保留；既有事实不得被驱逐后又重新查询。

上线后日更固定按§21.5执行发布前完整日源及候选代码检查，再发布Raw/Silver并绑定唯一覆盖结果，随后按既有范围处理历史。所有已取得的数据、依据、覆盖和摘要在本任务内直接复用。

仅开发阶段上线前初始化补数增加两处收尾：目标日首次覆盖结果同时用于初始化日期记录，保存后更新本任务合计；历史只在原导入批准日期交集内计算所需覆盖一次，批末取得真实事件后用已有小结果包装日期记录、更新合计及summary。不得先算初始化统计再重复算Raw覆盖。具体分支集中在§10.5.6～10.7，不能将它复制到普通日更/repair。

DG检查结果从唯一audit构造，source/Raw/Silver业务数据均不为metadata再读一次。bootstrap纯导入在本日回调使用同一条发布/一次覆盖链，不另建一条统计计算。所有正常/异常/取消收尾只消费已持有结果，不再次classify、prepare或重读；新进程恢复才首次从持久事实重建本次对象。

## 3. 分区、时点与日更选择

### 3.1 分区注册

`stock_factor_pro_trade_day_sensor`按SSE当天记录的`pretrade_date`确认上一交易日，只新增已确认的今天和上一交易日缺失分区。缺失上一日记录时不拿更早日期代替，默认STOPPED、最小间隔600秒。它只负责分区登记，具体已验收行为见§20.3。更早人工目标若未登记，运营按明确日期先登记后提交。

### 3.2 sensor判断顺序

按§21.3依次核时点、目标分区、已提交/活动任务、本地上游、是否仍需日更或既有复权追修，再取得目标日应有代码及Tushare两列代码。排除可选首日代码后，集合完全相等才构造一个RunRequest。自动只选D，不扫描旧日缺口。

### 3.3 固定时点与午夜

沿用上海开市日19:00～23:30每半小时的10个计划时点、午夜截止和排队run实际开跑复核。每slot至多提交一次，过往slot不补发。源端未齐就等待后续合法时点，午夜仍缺由人工指定T补跑。午夜前已实际开始的任务可结束。

### 3.4 人工补跑与开始事实

人工指定T按§21.4进入同一完整日更流程，不受自动时点及D是否开市限制。开始观察用于定位真实执行及初始化授权，仍先持久化再调用正式下载。次数、自动补前日额度及对应提交序号退出日更决策。探测只有两列，既不产生业务物化，也不宣告日发布完成。

### 3.5 去重和小型cursor

同一sensor使用`build_asset_update_run_key`，业务单元固定为D、T、slot。已提交依据使用本sensor、job和按D/T/slot构造的确切run_key过滤的持久run记录，并沿用Dagster同sensor的run_key去重。cursor只记录当日最近已探测slot和必要摘要，减少同slot重复网络查询。清cursor最多导致再次轻量探测，已用run_key仍不产生第二个job；不再恢复旧的补前日次数或读取已完成tick来拼装机会状态。活动任务结束后只按当前合法slot处理，不补过去时点。

日更sensor不创建业务记录、分区或Parquet。源端未齐/查询异常写本次SkipReason和小摘要，日覆盖及历史完成仍来自实际job。接口、成本及反例见§21.3、§21.7。

### 3.6 当晚复权因子修订后的自动追修

1. 沿§3.2的交易日、时点和活动任务判断。一轮结束后，在后续合法时点选择今天。今天存在待处理工作时按原流程处理。仅在日覆盖已确认齐备、日Silver有效且历史已经处理完成，本可跳过今天的分支，才比较复权因子摘要。确定需要提交追修后，同样先经过§21.2的源端代码齐备门槛。
2. **自动追修以同T最近一次有效日更的T/P摘要为准。**从§6.2已取得的`day_result_ref`取同一份已解析日观察，要求它来自日更job，`phase=day`、`result=completed`，并且其日Raw/Silver发布和对应检查仍有效。是否齐备单独由第1项的日覆盖判断决定。取该日观察自身的`history_plan_ref`。用`read_stk_factor_pro_history_plan`按引用run/T读取一次`history-plan.json`，核对`RecordRef`与已读文件摘要、计划T/P及身份。直接使用计划的`factor_t_ref.file_sha256`和`factor_p_ref.file_sha256`，与当前对应日期的本地Raw复权因子文件摘要分别比较。复用现有摘要函数，同一评估每份文件最多读并算一次，不读取范围Parquet或技术因子历史。摘要一致则跳过，变化且上游已就绪则提交既有`today`日更。日观察、计划或文件不可用时按已有就绪规则等待或报告，不猜摘要一致。
   - 日观察有效时，生产run后来历史失败仍可作为日更摘要依据。历史是否完成独立用§6.2当前待刷引用、未解除失败及有效历史结果判断。历史`completed`或`no_action`的成功条件沿用现行规则。手动repair成功只确认原授权范围，即使其计划保存了更新的T/P摘要，也不参与第2项比较。不能取最新入口、开始观察或历史观察的`history_plan_ref`代替日观察自身的引用。
3. job按现有T/P输入重新生成计划并先完成日发布。追修历史完整源已交付后，在历史publisher的既有资源清理范围内、创建首个历史候选前，复用已核历史源关系及本轮T/P因子关系做一次比较。范围限定本次追修待发布的股票，按`ts_code`和同一个`trade_date`连接，只比较T、P上两边均有实际数值的行。沿现有因子值比较口径。同一股票不同日期的数值互不比较。缺T行的全天停牌股沿§5.2处理，无可对照行继续使用既有覆盖、源完整性和范围校验。
4. 若有明确差异，沿§6.1保存`history waiting`及本轮完整待刷范围，再以`failure_phase=history`、`retryable=True`、`source_error_code=None`结束本轮。历史Raw/Silver发布、物化、check和`publication-complete`均为0，当天已发布结果保留。后续允许的轮次按已有待刷计划重下全范围，继续应用同一项核对。通过后走原历史发布和完成流程。执行中的输入变动、取消、其他文件错误沿既有处理。

**第六批接线。**用现有`history-ranges.parquet`的`plan_reasons`记录当晚复权因子修订追修，新增`HistoryPlanReason.SAME_NIGHT_FACTOR_REVISION=7`，沿用原字段和1～6的含义。已有有效日观察的自动`today`在生成本轮计划前，用第2项的同一取法取得日观察中的计划摘要，与本轮已取得的T/P摘要比较。首次发现修订时，只给本轮按现行规则需要回刷的范围加此原因，原因本身不增加股票或延长范围。无有效日更可比较的首次正常更新沿原流程。后续同T自动`today`从`pending_plan_refs`中仍未完成的范围继承此原因，即使新日观察已使用新摘要，历史核对仍继续。自动历史发布只对本次实际下载且带该原因的范围做第3项核对。成功后由原有完成流程移除待刷引用，后续比较取最近一次有效日更的摘要。沿用现有日更、手动repair及初始化补数的入口配置，修复原授权历史不建立新的日阶段结果。

**定向验收。**用同一小样本证明输入未变时跳过，T或P修订时在后续合法时点提交。原日更已经发布日数据，随后手动repair只修原授权范围且计划包含更新因子时，比较仍用原日观察的计划。历史源连续两轮仍返回旧值时均保持完整待刷范围且零历史发布，源更新后原范围完整发布。核对第2项文件读取次数和第3项源端比较次数。日发布、手动repair和全天停牌例外沿既有用例回归。

## 4. job内的严格顺序与Dagster编码组织

下图仅描述上线后的普通日更。开发阶段初始化补数复用下载/发布步骤，其额外授权与导入统计收尾单列于§10.7，不放进本图作为所有job的必经步骤。

```text
sensor：日历/时点/已提交及活动任务 → 本地T/P股票复权因子及目标日依据 → 源端两列代码相等 → 提交单T job
  ↓
job开头：唯一写入/普通用途配置 → 自动截止或原生日更重新执行身份 → 再核原T/P就绪
  → 读取T/P并比较 → 完整保存T回刷名单/待处理原因
  → 持久化本轮开始下载事实
  ↓
下载T日全部页 → 只在当前内存持有完整日unit → 正常关闭session并核最终summary
  → 核当前日源字段/主键/日期及双向代码集合 → 构造并核Raw候选代码 → 才进入正式提升
  → 发布日Raw并读回/check → 发布日Silver并读回/check
  → 完整日数据两层发布并通过检查后可读，历史完成另行报告
  ↓
发布前代码校验结果绑定实际日物化/check，交历史资格使用
  → 按§5.2.3确认原T Silver有效且对应当前Raw
  → 以adj_factor数据集T/P确定回刷范围
  → 自动追修按§3.6在历史发布前核对源端明确差异
  → 仅整范围成功且仍有效的同基准历史不重复
  → 完整变化/原失败名单不按本轮返回集合缩小
  → 历史前再次核对股票复权因子数据集输入
  → 重新下载本轮完整待处理范围的全部股票/窗口并完整保存
  → 按日期批量合并/校验/发布d<T的Raw和Silver
  → 每批保存真实物化/check及历史阶段结果，失败亦保留真实日结果
  ↓
分别报告日数据可读、代码覆盖、完整名单与历史完成/待处理
```

股票复权因子数据集T/P未就绪就停在job预检，不进入日下载。日Raw/Silver和常规历史回刷记录两接口差异，源值照原样发布。自动追修的历史发布按§3.6核对可对照的差异。两接口的同名值对上，也只能说明这些值一致，源端历史指标仍由Tushare提供。

编码组织采用两个`AssetSpec`和两个`AssetCheckSpec`的multi_asset，job的selection包含该定义的两个资产及两项check；选择同一个`cn_a_stock_factor_pro_trade_days`。`can_subset=True`及开头完整selection拒绝规则严格按§2.1执行。同步函数依次调用§2.3业务函数；没有下载线程/进程或IPC职责下沉组件。

日阶段在§21.5确认完整日源及最终候选后，每资产最多产生一次输出。Raw候选验收、提升及完成记录后yield该Raw的物化及检查，再处理Silver。日Raw事件记录实际文件/完整合同/处理版本、本轮scope及day_source_digest；没有日源文件引用。Silver事件保存对应Raw的SHA和实际绑定身份。合法零输出只表示预检等待或发布前失败，不以虚假物化填补框架输出。历史多日期事件按以下已核方式产生。

预检明确未下载时，先yield包含`PRECHECK_NO_DOWNLOAD`的真实观察，恢复后正常结束，run为SUCCESS；没有物化及check评估，也不写任何补采机会或次数。已经下载但没有可用日数据的分支按§4.0.1记录业务失败，不能标为PRECHECK_NO_DOWNLOAD。本定义不调用`set_requires_typed_event_stream`，使用`can_subset=True`允许省略实际未执行的输出，不补造`Output(None)`或绿色检查来凑输出数。对应临时instance回归必须分别断言这两种终态、观察持久以及没有虚假物化/check，不能只检查装饰器属性。框架输出组织与业务是否更新成功是两个判断；允许省略检查并不表示业务必须SUCCESS。

日更和手动repair均沿用原对象历史窗口，结束日期可以是原T；这不是全市场BY_POINT日更。完整保留该对象请求的T行用于来源和差异诊断，正式历史只改d<T，因此不重复yield日阶段同一个资产输出。历史日期采用显式`AssetMaterialization(asset_key, partition=d, metadata=...)`；对应check使用本机已有的`AssetCheckEvaluation(partition=d, blocking=True, ...)`并关联该次物化。当前`AssetCheckResult`没有partition参数，禁止自造。事件要按正常run写入，不把日常更新变成runless补记。

历史事件固定通过生成器yield：文件读回后yield本批各日期/层的`AssetMaterialization`，生成器恢复后按当前run有界批量读取这些已保存的物化，再构造并yield各自`AssetCheckEvaluation`。只按本批已发布的资产/日期/文件身份匹配真实记录，缺记录或身份不符停止，不猜storage_id；`target_materialization_data`绑定该真实物化。不得先`context.log_event`后立即读取尚在缓冲的记录，也不能每日期深扫全部event history。相应API依据与当前实现见§9，仍须在临时instance验证顺序、持久化及分区关联。

当前日Silver结果交出后，控制层先完成本日必要本地计算，再恢复publisher进入下一日。当前批以日期为键保存两层target/audit、scope/缺原键结果；仅开发阶段上线前初始化补数、且d在原导入批准范围时，才另存首次coverage_counts、样本/明细引用、依据身份和原SourceComplete/摘要。上线后的常规历史不执行这一额外覆盖或导入记录维护。最多20个日期，业务行不进入该字典。此后释放本日固定SQL关系，允许下一天复用DAY_PRIOR/RAW_EXPECTED等名称。上线后的常规历史在批末绑定真实事件并保存自己的历史阶段结果；仅上线前初始化补数再用已得小事实包装CurrentPublication/DateCoverage并更新导入统计，不重新查询前19天的关系或Raw。Raw-only尾日只保留实际层事实并进入incomplete，不造Silver或完整覆盖结果。

批次处理保存当前run实际已发布且读回通过的目标及audit列表，每文件完成才加入，不把候选或未确认提升加入。正常批末flush；可捕获的普通业务异常先保留原异常，再对已经完成的目标flush同样的物化/check事件及§10.5.6统计，最后重新抛原异常；尾部只有Raw也只发真实Raw事件。若flush再失败，作为附加原因记录，不能覆盖最初错误。不能在GeneratorExit/强制进程退出时依赖finally里yield；此时只关闭资源、保留文件/intent，旧统计身份不匹配便不可用，下次原生重执行仍全新下载，不承诺硬退出时一定补完事件或统计。取消可安全收尾时仅处理已经完成的目标，不领新文件。

批读固定使用`instance.get_records_for_run(context.run_id, of_type=dg.DagsterEventType.ASSET_MATERIALIZATION, limit=N, ascending=False).records`，N为本批实际已yield的物化数量，最多40；N=0不查询。本数据集同run由单个执行线程产生这些物化，读取后按本批预期的(asset_key, partition_key)一一对应，数量、重复、当前run或物化metadata的`file_sha256`不符均停止。检查构造引用当前已保存的EventLogRecord：

```python
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation, AssetCheckEvaluationTargetMaterializationData,
)

target = AssetCheckEvaluationTargetMaterializationData(
    storage_id=record.storage_id,
    run_id=record.event_log_entry.run_id,
    timestamp=record.timestamp,
)
yield AssetCheckEvaluation(
    asset_key=record.asset_key,
    check_name=expected_check_name,
    passed=audit.passed,
    metadata=check_metadata,
    target_materialization_data=target,
    severity=dg.AssetCheckSeverity.ERROR,
    blocking=True,
    partition=record.partition_key,
)
```

`expected_check_name`按已核本批目标的层取§2.1固定check名，check_metadata复用该目标读回校验结果。timestamp来自真实物化，不取当前时间；构造方式参考现行`defs/bootstrap/moneyflow_history_events.py::_evaluation`及`defs/checks/stock_suspend_confirmed_checks.py`，不调用其业务或runless流程。已存在且内容等价的正式文件不重复replace，但如实产生本轮验证事件、metadata标记`mode=reuse`及真实file_sha256；无正式文件的空日期不造事件。

历史下载/处理失败时，已发布的日Raw/Silver不回滚、不删除，不要求业务等待跨文件快照。run可失败且历史pending，与日文件及对应检查真实通过同时存在。不得通过把失败run整体当作“没有任何可用数据”抹掉先前发布。

### 4.0.1 发布前日代码校验

日更完整下载会话结束且summary通过后，复用当前`DAY_SOURCE`及目标T已准备的应有代码关系，做双向差集。必需缺码、未知多码、错误日期、重复主键或覆盖依据无法确认，均在Raw首次提升前结束本轮，正式日发布及历史请求为0。零行且应有集合非空同属这条规则，无需旧的部分可用/空源补采分支。

Raw候选生成后，继续用同一必需/可选首日集合核RAW_EXPECTED代码。现有合并保留的旧行若产生额外代码，停止并报告，保留原正式文件。日源和候选检查共用已载入关系，无重复读取261列。完整源或候选不齐均不得用旧行补出一次虚假的本轮成功。详见§21.5。

### 4.1 管理员手动历史repair入口

`raw_tushare_stk_factor_pro_repair_job`仍为手动op job，无自动sensor。`repair_stk_factor_pro_history`使用`out={}`、同步生成器和既有`lake_root`、`duckdb`资源；配置层级固定为`ops.repair_stk_factor_pro_history.config`。观察/物化/历史检查直接yield，失败前阶段观察须先yield落入原生事件流，不只写log_event缓冲。本入口只处理原目标日T完整名单、原起止范围内的d<T历史；不发全市场T日请求，不进行对象T日确认查询，不发布T，不嵌套调用任何日更新函数。

配置固定为以下四项，全部必填；其他字段一律在配置校验时拒绝，不能忽略或增加兼容分支。

| 字段 | 类型及校验 | 消费者和含义 |
| --- | --- | --- |
| `target_trade_date` | 严格ISO日期str，解析为date；SSE开市日，已登记；必须与原记录T相同。 | 当前运行的历史所属日期，不是实际执行日。 |
| `source_run_id` | 已核实的本数据集update或repair run_id；记录必须属于相同原T。 | 只定位原完整plan/ranges授权、未完成历史意图和原失败引用；不得读取其下载文件作为当前网络结果。 |
| `expected_history_plan_digest` | 64位小写SHA-256，精确匹配原完整plan。 | 防止复制错误任务或用部分股票名单代替原完整授权。 |
| `expected_history_ranges_digest` | 64位小写SHA-256，精确匹配原完整代码/起止范围。 | 不接受管理员另传股票、年份或文件路径扩大范围。 |

```yaml
ops:
  repair_stk_factor_pro_history:
    config:
      target_trade_date: "2026-10-21"
      source_run_id: "<原自动任务或上次repair的真实run_id>"
      expected_history_plan_digest: "<原完整plan摘要>"
      expected_history_ranges_digest: "<原完整范围摘要>"
```

本配置持久化于当前Dagster run_config，不新增env、表或页面开关。实际执行日只用于metadata和维护记录，不能替换T/P。配置源run是前一次repair时，读取它保存的原完整授权引用，仍直接核对原T和完整原范围，不把前一次repair实际处理范围当成新授权。所有新记录只写当前run的受控staging目录；只按已验证的source_run_id和固定授权引用读取原记录。

仅开发阶段上线前，为初始化补数收尾且source_run属于bootstrap_supplement或继承其上下文的repair时，才从该精确run的开始/阶段观察读取已核bootstrap_context，核原导入编号/approval/T及§10.7原授权；四项repair配置不增加字段。该初始化repair在首个历史请求前保存并读回同一Context，发布后按§10.5.6更新导入日期result/summary；这些收尾须在上线前完成。不能从同T任意run猜导入编号，也不重新要求当前T缺口>0。上线后的正式repair只消费原T和原历史授权的DG事实，不沿旧初始化Context读取批准、导入记录或统计，不触发T日更新。

严格顺序如下：

1. 校验配置、source_run身份、同T、两项完整授权摘要和受控路径；验证维护窗口、无其他活动写入及bootstrap未运行。任意错误在网络和正式提升前停止。
2. 核对日历T/P和原完整范围，不下载历史；先进入下面原T Raw检查。这样原T Raw缺失时优先给出约定的日数据缺失提示，不先被其他来源错误掩盖。
3. 调用§5.2统一Raw齐备检查，读取**原T当前正式、合并后的Raw文件**；不能从旧下载候选、今天Raw、旧绿色check或一份有相同行数的文件判断原T齐备。
4. 若原T文件缺失、必要字段/check不通过、应有代码缺失，或生命周期/停牌输入不足以确认覆盖，立即抛`dg.Failure(..., allow_retries=False)`。主提示固定为`原日期数据缺失：<T>；请管理员处理原日期数据后重试历史repair。`，metadata补充具体原因。此分支零技术因子请求、零历史提升、零T写入；管理员另外处理原日期数据。本repair绝不代办，不让外层重试策略把这个报错变成重复执行。Raw齐备后紧接着执行§5.2.3的原T Silver检查：已有正式文件、最新有效物化及绑定通过check、对应当前Raw。失败直接按该节固定提示退出，同样零技术请求/零正式提升，不补当天Silver。
5. 原T Raw齐备且Silver有效后，读取当前`adj_factor`原T/P就绪及实际因子，核关键因子/可信范围；不足明确停止，不伪造0变化。只允许原范围内因子值修订，保存当前依据和差异；T/P重新相等不能删除原未完成历史意图，不追加股票、延长范围或更换T。完整保留原授权名单及原范围。按§5.4核对**此前独立整范围成功且仍有效**的事实，确定本次原失败范围；失败run部分或全部物理完成均不能用于缩小它。若已无待处理历史，保存真实`no_action`结果后结束，零技术请求、零正式提升，不伪造本run新完成历史。存在待处理历史则完整保存当前请求范围；不能因失败run只下载了部分股票而缩减该失败范围。全天停牌股票可无T技术行，不额外请求T。缺关键因子或可信范围时明确停止，不能挑一部分先回刷再宣称完整。
6. **每次重新执行，都从头下载该原失败范围的全部历史unit。**不读取失败run的`source/history`文件作为本次源，不复用其source-complete，不因失败run曾发布部分日期而跳过对应历史请求；只有当前run刚下载、保存、读回完整的历史源可用于当前run后续处理。组件单页有限重试仍适用，不增加op/job外层自动重试。
7. 当前历史全部源完整后，按原20交易日批次和日期升序，逐日期Raw合并/候选唯一审计/提升/完成记录→从这份Raw生成Silver并候选唯一审计/提升/完成记录。仅d<T。已经发布的文件不删除、不回滚；本次新下载结果与当前正式文件按既定主键规则合并，不使用旧失败run候选覆盖。当前run文件提升前后仍写既有intent/checkpoint；这是本次文件发布依据，不是跨失败run省下载的理由。
8. 仅在全部当前请求范围通过检查和原子发布事实确认后记录历史完成。失败/取消/异常退出保留正式已发布文件和原完整未完成意图；下一次repair仍全新下载原失败范围，不从页、股票或日期下载断点继续。成功/失败均在metadata说明原T、来源授权、当前新下载行数和实际发布范围。

原T Raw齐备且原T Silver有效并对应当前Raw，是自动job和手动repair进入历史的共同条件。日更通过当轮发布及检查建立事实，手动repair只读取已有有效DG凭据，不重新全字段对账。成功只确认原授权范围并解除对应历史失败，保留日阶段结果及其计划引用。正式历史只d<T；T行即使出现在完整历史响应中也只留源证据，不发布T。不得要求所有待回刷历史日的Silver预先存在：某历史d缺Silver时，应从本轮刷新后的Raw d生成并检查。

### 4.2 自动、手动与bootstrap的写入互斥

本节只保证本数据集的业务写入安排，不改变下载器。沿用既有Dagster队列、入口预检及运营维护步骤，不新增锁、线程、进程管理、维护表、维护状态文件或repair运行开关。

#### 4.2.1 既有队列与适用范围

2026-10-23已只读核对本机正式`dagster.yaml`：使用`QueuedRunCoordinator`，`concurrency.runs.max_concurrent_runs=1`。正常经同一队列提交的日更及手动repair串行启动；正式repair和人工重执行仍通过该队列提交，不用`execute_in_process()`或直接调用资产函数绕过队列。运行前由运营核对该配置仍成立；若已改变，先停止本次手动执行并复核安排，程序不自行修改配置。队列行为依据[Dagster运行队列说明](https://docs.dagster.io/guides/operate/managing-concurrency/run-queue-limits)。

bootstrap是直接文件写入，不受该队列的单任务数量限制。例如19:30日更已经排队，管理员在终端直接执行bootstrap，稍后日更出队就可能同时改同一日期文件。停止更新sensor只停止后续自动提交，不会取消已排队任务，也不会停止正在执行的任务。

终端bootstrap和sensor活动状态使用NOT_STARTED/QUEUED/STARTING/STARTED/CANCELING五种，正常队列job入口仅查STARTING/STARTED/CANCELING。状态选择须在数据库查询前完成，不能先五状态limit=2后丢弃排队记录，否则真正运行项可能被挤出。不同T历史可改同一旧文件，均不加T过滤；只排除own_run_id。

#### 4.2.2 运营在提交手动任务前完成的步骤

1. 记录更新sensor原本的RUNNING/STOPPED状态，在Dagster原生界面停止`raw_tushare_stk_factor_pro_update_job_sensor`并确认已停；分区注册sensor不下载、不写业务文件，不因本操作新增停启要求。不改cursor或run_key，不暂停其他数据集。
2. 在同一instance查看本数据集上述两个job的全部活动任务。等待它们正常结束；确需取消时由管理员明确操作，取消后仍等终态。停止sensor时已在进行的评估仍可能提交任务，因此提交手动操作前必须重新查询，不能只凭刚点了停止判断已经清空。
3. 确认没有另一手动repair或终端bootstrap正在写本数据集；维护期间由运营保证不启动第二个直接写入。bootstrap没有Dagster run，活动run查询无法发现它；不增加进程扫描、锁或维护登记来假称程序能证明这一点。
4. 完成这些步骤后，才提交获准repair，或启动获准bootstrap。repair继续只用§4.1四项配置，不增加`maintenance=true`、跳过检查或任意覆盖参数。bootstrap继续使用§10批准输入，来源维护窗口与DG写入维护步骤都须满足。
5. 运行中保持更新sensor停止，不再提交本数据集其他写入。程序不接管sensor停启，不自动取消队列中任务。

运营等待发生在手动操作提交前。正常队列job启动后只拒绝真正同时启动/运行/取消中的写入，后续等待/QUEUED不阻断。终端bootstrap发现五状态冲突立即停止，不在内部等队列；程序不替运营取消任务。

#### 4.2.3 编码落点、调用顺序和失败处理

在既有文件`defs/asset_guards/stk_factor_pro_readiness.py`内维护§2.3的两个函数；固定两job名称和活动状态在`defs/run_contracts/stk_factor_pro.py`单处维护。读取方式沿用现行`asset_guards/dc_board_run_recovery.py::read_dc_run_history`的有界活动查询语义，不调用其东财业务恢复逻辑，也不迁移旧消费者：

```python
def read_stk_factor_pro_other_active_runs(
    instance, *, own_run_id=None,
    active_statuses=STK_FACTOR_PRO_ACTIVE_RUN_STATUSES,
):
    active = []
    for job_name in STK_FACTOR_PRO_WRITE_JOB_NAMES:
        records = instance.get_run_records(
            filters=dg.RunsFilter(
                job_name=job_name,
                statuses=active_statuses,
            ),
            limit=2,
        )
        active.extend(
            record.dagster_run for record in records
            if record.dagster_run.run_id != own_run_id
        )
    return tuple(sorted(active, key=lambda run: (run.job_name, run.run_id)))
```

STK_FACTOR_PRO_WRITE_JOB_NAMES仍单处维护两job。现有reader增加内部active_statuses关键字参数，默认既有五状态，供sensor/终端bootstrap原消费者；正常队列job在第五批传固定三状态。两组状态由run_contracts单处定义，不是业务配置，也不接受运营任意值。每job limit=2，排除本run后返回有界样本；无新增查询/锁/循环。共享reader在修正轮同步签名及现有消费者测试，终端默认行为不变。

五状态常量名保持STK_FACTOR_PRO_ACTIVE_RUN_STATUSES；三状态常量固定为STK_FACTOR_PRO_RUNNING_RUN_STATUSES，值仅STARTING/STARTED/CANCELING。RunsFilter在存储查询内先应用statuses，随后limit取样，依据[Dagster实例及RunsFilter接口](https://dagster.io/docs/api/dagster/internals)。本步只修改这两个固定常量及既有reader的内部参数，不新增PG读取函数或队列job调用方。

| 调用点 | 查询及有冲突/读不到事实时的动作 |
| --- | --- |
| 更新sensor §21.3第2步，本次评估唯一活动任务查询 | 不传自身run_id，结果在本次评估中复用；有其他活动任务则SkipReason。查询失败返回本次等待原因，后续按§21.3评估；不新增排队任务。 |
| 自动job开始、任何技术请求前 | reader显式传内部固定三状态STARTING/STARTED/CANCELING并排除自身；查询前选状态。真实并行写入或证据不可读按PRECHECK_NO_DOWNLOAD结束，纯排队不阻断；结果本run直接复用。 |
| 手动repair入口、历史网络前 | 与自动job一样仅入口查询固定三状态，排除自身；真实并行写入/查询失败抛原Failure，纯排队不阻断，不调用终端bootstrap五状态require。 |
| bootstrap入口、首次Prod明细读取前 | 使用调用方提供的既有instance进行只读查询，`own_run_id=None`；不初始化instance、不创建run。冲突或查询失败立即终止，不读取明细、不提升文件。 |
| 仅终端直接bootstrap首次正式提升前 | 再调用同一require函数，own_run_id=None；本入口不受队列串行管理，维护条件继续保留。第五批正常队列job不得在此再查队列或因后来QUEUED任务中断下载/发布。 |

require函数保留给终端bootstrap五状态维护检查，入口与首次提升前各一次，至多4次PG查询。正常队列job在第五批仅入口用reader固定三状态（查询前选择），共至多2次PG查询，排除自身及纯等待run，不在首次提升前再查。sensor仍用五状态避免积压，每次评估仅一次两job查询。查询失败不能当空队列，不新增锁、等待、配置或源重试。

一次查询不是锁，无法阻止查询结束后有人绕过维护要求启动另一终端bootstrap。程序预检与运营保证共同成立才可执行；正式替换前仍逐文件核对已有目标指纹，发现意外改写立即停止，不覆盖未知结果。保持候选完整校验、逐文件提升和失败后重新下载规则，不承诺多个文件整体原子提交。

#### 4.2.4 收尾和恢复自动化

手动任务结束后，运营确认对应run已到终态或直接bootstrap进程已经退出，并查看已发布文件、未完成范围和错误。正常完成且允许恢复时，仅将原本RUNNING的更新sensor恢复为RUNNING；原本STOPPED的继续保持STOPPED，首次bootstrap也不会顺带启用尚未获准的自动化。

失败、取消、进程状态不明或恢复操作失败时，先保持sensor停止，由运营确认处理后再明确恢复；不能在`finally`里无条件启动sensor。恢复失败只影响后续自动调度，不回滚已发布文件，不改写手动任务的业务结果，后续只处理当前合法时点。后续按§21的自动时点、午夜截止和源端门槛运行。

本节新入口与队列行为在实现后使用临时instance验证；当前仅有配置、现行代码与设计依据，未执行新入口测试，也未操作正式sensor或队列。

## 5. 完整回刷名单与本轮候选记录

### 5.1 先名单，后技术因子下载

本节名单算法也供开发阶段上线前bootstrap_supplement人工补数及其原生重执行复用；这些初始化调用同样先核T/P、再生成名单，不因此把初始化授权或统计加入上线后普通日更。

每次同T的日更job（自动或人工重新执行）都用当前`adj_factor`数据集原T/P重新比较、重新保存本run完整名单。通过§6.2直接读取DG已有观察中的同T未完成范围和成功事实；业务输入未变时内容摘要可以相同，不复用失败run的下载源、候选或部分下载进度。手动历史repair严格按§4.1先查原T Raw齐备，之后才核T/P及原完整授权，不重新扩大授权。两入口都保留已知未完意图：修订后T/P相等也不删除旧未完历史，仅生命周期证明该股本无待刷历史时记录依据和排除原因。不能因本轮源少了一只、源超时、股票暂时无T行就把它从已知变化名单删除。

例如19:00的任务记录A股待刷，19:30接手后，管理员再重跑19:00。只从同T当前记录取待刷股票及起止日期。A股仍待刷就重新下载完整范围，已有符合§5.4.3的完整成功记录就跳过该范围。当前明确引用的名单或完成记录无法读取时，报告具体引用并停止。当前确实没有历史计划时，依据当前T/P生成本轮名单。日数据每轮重新下载，已发布文件保留供合并。

比较以T/P的`FULL OUTER JOIN`按代码显式对应，再并入本数据集可信既有历史/同一目标T旧pending中明确应核对的有界代码范围；不能只以T为左边，也不能inner join后漏掉P有T无旧股。至少区分两日都有且变化/不变、T有P无、P有T无、以及既有范围/旧pending证明应核对但两日都缺。后两类没有生命周期或其他明确解释时保留无法判断，不写“0变化”；证明退市也要留下解释，不能静默删除待处理。生命周期可证明的真新股不造上市前历史，单列新股结论；旧股票缺P保留原因。这是本数据集有界对象比较，不新增全市场覆盖发布门槛。没有变化必须能证明输入已检查；股票复权因子Raw文件就绪不意味着每只股票都必有两日值。

只比较股票复权因子数据集值，不新增任意浮点阈值。需要更新历史的变化股从可信既有最早日期到T；无既有历史时解释新上市或异常。最早日期取初始化验收/可信范围或有界聚合，不在sensor逐tick扫描全湖。修订后的因子恢复旧值不取消原未完回刷；下载和发布仍应完成原范围，不能把“写了新清单”当成旧任务自动完成。


#### 5.1.1 历史起点的统一规则（所有历史入口必读）

**历史起点是这只股票在DG已有且可信的最早技术因子日期。**Prod的2017-01-03是本次确认的全量bootstrap起始边界，见方案§3.2。某只股票在DG的首条记录若是2020-06-15，该股就从2020-06-15回刷到原T。

1. 优先复用已确认的每股起点。有多个有效依据时保留最早边界。手动repair沿原授权起点。普通日更、原生日更重执行和初始化补数对剩余缺起点股票按§19.12取得本地可信Raw日期集合。
2. 使用同一主要DuckDB连接，仅投影`ts_code`、`trade_date`，一次按代码求`MIN(trade_date)`。日期与文件分区的一致性在同一聚合中检查。后续规划及范围核对直接复用本次结果和文件依据。合并按实际处理日期读取其必要业务字段，起点聚合及额外主键扫描次数为0。
3. 通过`StkFactorProHistoryStart`交接起点、依据种类及依据日期，按§5.4保存到既有`history-ranges`。必需回刷的旧股票缺可信依据时保留原对象及NULL起点，按§5.1.2停止本轮历史。生命周期已证明无原历史的新股走原因6。

#### 5.1.2 完整名单到本次下载unit的逐项判定

`full_code_count`始终等于history-ranges的唯一股票数；`expected_units`只描述本次确实需要新下载的完整范围，两者不能强制相等。先保存完整plan/ranges及其业务摘要，再按以下表确定是否能进入下载。处理结论由既有字段和成功引用推导，不新增可由业务随意填写的状态列或字符串枚举。

| 对象/范围的实际情况 | 完整名单和依据 | 是否进入本次expected_units |
| --- | --- | --- |
| T/P没有变化、没有旧未完意图 | 已核比较说明确无新工作；可为空名单，不伪造源完成 | 不进入，不建立0-unit下载任务 |
| 本次变化，或已知原未完；关键T/P及完整起止已知 | 保留完整原范围；当前T/P重新相等不抹掉旧意图 | 每个仍需刷代码一项mode5完整范围，不按20日切短 |
| 该独立完整范围已有成功且输入仍匹配 | 保留原成功记录引用；严格核§5.4.3的producer SUCCESS、原T/代码/起止/T/P/合同及后续影响 | 仅该已证明成功的完整范围免刷；失败run的部分成果不进入此分支 |
| 生命周期及已有记录已证明没有原历史 | 保留原因6及依据；不造上市前范围 | 不进入，不能把“起点查不到”当作原因6 |
| 必须回刷但关键因子或起点尚未判明 | 原对象、NULL范围/值、原意图仍留在ranges及plan摘要 | 整个本轮待请求范围不可执行；历史请求/提升0，不能先过滤未知行再称完整 |

未知分支由正常日更编排保留有效日发布、记录历史waiting及具体对象/原因，不生成历史source-complete或publication-complete；手动repair按既有前置规则停止并提示。若内部代码越过判断而调用下载函数，函数必须在网络前拒绝不完整输入，按§6.1输入合同错误处理，不能默默缩小范围。第三批落实这个零网络的输入保护，第五批负责把判断接到正式阶段观察及入口；不增加自动补数或断点能力。

原完整待请求范围无未判明项后，排除有完整成功证明或原因6的对象，按code/start/end排序生成唯一expected_units；其scope_digest及后续manifest精确描述这份已判明的完整请求范围。plan摘要仍包含所有保留对象和未知行，不能只摘要实际下载子集。原成功范围、无历史解释和本次完成结果一同供后续整体判断，不能用本次unit数代表全名单完成。

例如：完整名单A/B，B必须回刷但起点未知，本轮不能只下载A并记录“历史完整”。若B是有依据证明没有旧历史的真新股，则保留原因6后，A的完整范围可以形成实际下载清单。

### 5.2 原目标日Raw齐备后才允许历史处理

完整变化名单在正式261字段日下载前依据权威adj_factor的T/P生成并保存。日源及最终日候选代码须通过§21.5后发布。原T Raw完整及Silver有效仍是历史共同前置。

应有代码按现有语义构成：

使用已就绪且实际schema有效的silver_stock_lifecycle确定目标T有效上市股票；list_date=T且非全天停牌的股票代码为可选首日集合，其余有效上市且非全天停牌代码为必需集合。日更、历史repair资格和bootstrap当前覆盖统计均按§21.10的同一规则计算，避免源端准入通过后又被旧覆盖口径阻挡。

两项文件blocking check沿既有定义。日更在首次正式提升前按§21确认日源及候选代码完整，日Raw/Silver都已发布并通过检查后，历史资格直接复用本次覆盖和两层凭据。手动历史repair仍先核原T覆盖及Silver，不通过按§4.1报错；全天停牌股的d<T历史、自动追修源因子核对和原授权范围继续沿原规则。

#### 5.2.1 内部接口与结果

以下evaluate/require读取判断接口放在既定`defs/asset_guards/stk_factor_pro_readiness.py`；write_stk_factor_pro_missing_codes诊断写入放在既定`defs/io/stk_factor_pro_history.py`，由job/repair编排调用。记录类型在既定`defs/run_contracts/stk_factor_pro.py`；读取判断模块不反向调用写入，不新增平台、数据库表、锁或独立状态资产。

```python
@dataclass(frozen=True)
class StkFactorProRawCoverage:
    target_trade_date: date
    complete: bool | None
    raw_check_passed: bool
    raw_file_sha256: str | None
    lifecycle_file_sha256: str | None
    suspend_file_sha256: str | None
    identity_file_sha256: str | None
    expected_count: int | None
    actual_count: int | None
    missing_count: int | None
    extra_count: int | None
    coverage_rule_version: str
    missing_sample_codes: tuple[str, ...]
    reason: str
    raw_materialization_storage_id: int | None
    raw_check_storage_id: int | None
    missing_codes_ref: RecordRef | None

def evaluate_stk_factor_pro_raw_coverage(
    instance: dg.DagsterInstance,
    connection,
    *,
    lake_root: Path,
    target_trade_date: date,
    known_pg: dict, known_records: dict,
    calculated: Mapping[str, object] | None,
    verified_raw_audit: StkFactorProFileAudit | None = None,
) -> StkFactorProRawCoverage: ...

def require_stk_factor_pro_history_raw(
    coverage: StkFactorProRawCoverage,
) -> None: ...

def write_stk_factor_pro_missing_codes(
    connection, *, staging_root: Path, identity: RunIdentity,
    coverage: StkFactorProRawCoverage, calculated: dict | None,
    known_records: dict,
) -> StkFactorProRawCoverage: ...
```

同一readiness模块提供纯函数build_stk_factor_pro_coverage_keys(connection, *, target_trade_date:date, listed_relation:str, full_suspend_relation:str, optional_relation:str, actual_relation:str, identity_relation:str)。五个relation名只能来自本调用已验证的内部临时关系，前四者列为trade_date DATE、ts_code VARCHAR，identity列引用现行身份schema；不得来自run_config/任意SQL。返回固定计数结构StkFactorProCoverageCounts，字段为expected_count/actual_count/matched_count/missing_count/extra_count、identity_unmapped_count/identity_ambiguous_count（均int|None）、identity_unmapped_sample_codes/identity_ambiguous_sample_codes（均tuple[str,...]，升序最多20项）及reason:str。这个纯集合函数只在现有连接计算，不读取instance、不读路径、不写文件。

StkFactorProCoverageCounts按当前实现只承载上述计数、身份映射异常样本及原因，不包含missing_sample_codes/extra_sample_codes。缺失/额外样本在首次需要保存诊断时，从同一次集合计算保留的missing/extra关系各取一次（升序最多20项，0或未知为空tuple），与名单引用一起交接。现有初始化实现由_write_codes返回(reference,sample)，compute_stk_factor_pro_bootstrap_coverage_date把coverage_counts、两类样本及引用放入同一个calculated字典，evaluate直接消费它。

普通日更的诊断writer同样首次取样本后填入RawCoverage；仅上线前初始化补数同时需要两类结果时，调用方传递同一份计数/样本/引用，不能再查样本或再保存相同名单。不为对齐文档给现有计数类型新增字段。

`calculated`固定使用现有compute返回的七个键：coverage_counts、unknown_input_kinds、reason、missing_codes_ref、extra_codes_ref、missing_sample_codes、extra_sample_codes。普通日更在唯一集合计算后建立同样的字典；未保存明细时两个ref为None、对应sample为()。evaluate只包装计数、原因和已经取得的样本/引用，不执行SQL。writer仅在正缺失且尚无引用时，从仍保留的missing关系取样本一次、保存明细一次，将所得ref/sample回填这份任务局部字典，并返回新的冻结RawCoverage。已有引用、0缺失或未知直接交接，不再查询或保存。初始化compute已经保存两类明细并返回字典时，即使临时差集关系已释放，evaluate/writer仍须能够完成交接。

目标T的初始化明细引用为StkFactorProBootstrapCodesRef，creator_run_id为当前run；转成RawCoverage的RecordRef时只复制creator_run_id、relative_path、file_sha256，不重新读取或复制文件。反方向从普通日更明细建立初始化引用时，只补入已得missing_count作为row_count。历史d<T的operation相对引用不转成RawCoverage。两类包装收到的计数、样本及引用必须来自同一个calculated；writer不得另建known_records或从磁盘补取已经取得的结果。普通日更仅需缺失明细时，不为填满七个键额外保存extra附件。

新覆盖固定为“共用算法一次→calculated→必要诊断首次保存→各自结果构造/记录保存”。初始化compute负责同一次算法和所需诊断的编排，不能先在外面算一次core再调用它。普通RawCoverage在输入未变且原完整结果有效时，可按其既有接口显式传calculated=None复用；初始化最终DateCoverage构造则始终接完整七键字典，若旧结果适用，由主入口提取已有计数/样本/引用供纯包装，不执行SQL，也不传旧DG引用给计算。新结果或正缺失且无引用/首次计算结果属于接线错误，不能回盘或隐式重算；等价新事件只更新最终引用。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProCoverageCounts:
    expected_count: int | None
    actual_count: int | None
    matched_count: int | None
    missing_count: int | None
    extra_count: int | None
    identity_unmapped_count: int | None
    identity_ambiguous_count: int | None
    identity_unmapped_sample_codes: tuple[str, ...]
    identity_ambiguous_sample_codes: tuple[str, ...]
    reason: str

def build_stk_factor_pro_coverage_keys(
    connection: DuckDBPyConnection, *, target_trade_date: date,
    listed_relation: str, full_suspend_relation: str, optional_relation: str,
    actual_relation: str, identity_relation: str,
) -> StkFactorProCoverageCounts: ...

def _build_stk_factor_pro_coverage_keys(
    connection: DuckDBPyConnection, *, target_trade_date: date,
    listed_relation: str, full_suspend_relation: str, optional_relation: str,
    actual_relation: str, identity_relation: str,
) -> StkFactorProCoverageCounts: ...
```

两个入口使用同一份集合计算实现。公共函数保留首次外部输入的schema、日期、代码及关系名检查，再调用私有实现。本任务内已核生命周期、最终停牌、身份和Raw产生的固定两列投影，直接交同一私有实现；这些投影只使用已核代码和固定原T日期，不再DESCRIBE或扫描同一批代码做第二次有效性检查。私有函数不接跳过检查开关，不接受运营输入，也不增加另一套算法。公共函数错误输入仍拒绝；可信内部路径由首次依据/Raw审计与固定投影约束。两种调用都只执行一次映射和集合差，随后包装、记录及汇总不得再调用它。

纯函数对上市、全天停牌、首日可选、实际四侧的原代码/日期去重并集核每项恰一有效映射，再按§10.5.3及§21.10生成统一身份的E/F/C及missing/extra。可选关系先与扣除全天停牌后的有效上市集合相交，不能用它豁免停牌或未知代码。映射不能确认时覆盖计数为None，保留映射异常计数/样本；不能伪造缺0。源为空时传同schema空actual关系，正常计算并拒绝非空必需集合的缺失，不保留独立的空源补采路径。bootstrap采用同一纯算法，不调用含instance的日更evaluator。actual_count为排除可选首日后的参与比较代码数，物理行数另记。

identity_file_sha256来自已核正式身份文件，与Raw/生命周期/最终停牌SHA及coverage_rule_version一起决定覆盖能否复用。新规则固定版本和迁移见§21.12；仅文件SHA不变不足以复用旧规则计数。history-eligibility和PG阶段观察保存完整RawCoverage，repair和bootstrap消费者同次迁移；不修改其他数据集readiness。

`complete=True`仅允许全部必要输入已确认、当前规则版本匹配、Raw文件check通过、missing_count=0且extra_count=0，并满足expected_count=actual_count；未知计数不能通过。False表示已确定不满足，None表示必要证据不足。raw_check_passed=True的物化/check编号必须对应实际有效记录。reason只作中文说明，不解析它决定分支。多码计数进入RawCoverage，不增加一套多码附件writer；正式日源/候选不齐按§21.5在提升前失败。

完整缺失清单固定写当前run目录的`diagnostics/day-missing-codes.parquet`，schema为`ts_code VARCHAR NOT NULL,trade_date DATE NOT NULL`，唯一键(ts_code,trade_date)、trade_date全部为原T，代码升序，行数精确等于missing_count。它只保存缺失股票及日期，不保存下载指标，不是日下载缓存。**写入eligibility/阶段观察等持久记录时**，missing_count>0必须有有效missing_codes_ref，sample是完整清单前至多20个代码；缺失0或计数未知时ref=None、sample为空，不制造空指标文件。先原子保存并读回清单，再保存引用它的eligibility/阶段观察；PG只存计数、样本和引用，不塞1000只股票全文。

计算与保存职责分开：控制层在同连接首次取得必要输入并执行一次代码集合SQL，将完整coverage_counts及差集关系保留交接；evaluate只使用传入counts、已得事件/audit包装RawCoverage，不重新计算或写staging。首次集合计算在传入连接建立固定临时表`stk_factor_pro_raw_coverage_missing(ts_code,trade_date)`保存本次完整差集，并先返回missing_codes_ref=None的内存结果；此结果不能直接冒充已持久化记录。job/repair紧接着调用write_stk_factor_pro_missing_codes，使用当前可信RunIdentity和已核staging根，使用首次集合计算已确认的目标T、计数/主键/日期及差集关系，不再次SELECT计数或审计该关系；COPY原子保存后只做该新输出首次传输读回，返回填入RecordRef的新不可变结果。内部根路径不是新增运营配置。

sensor只读已有有效coverage；需要时可以计算上述临时摘要，但**不调用写清单函数、不保存eligibility/阶段事实**，不把无引用的内存摘要当作已保存结果。业务job保存日阶段结果或历史判断前必须完成清单保存。复用覆盖结论时保留原有效引用；引用丢失/损坏，只对原T重算必要代码及差集，job重新保存诊断，不重新下载、不重做261字段对账。输入未变且原引用有效时，不创建临时表或重写清单。

DG PostgreSQL中的物化、check和阶段结果是直接使用的凭据，不能把查询这些结果写成“每次重跑完整审计”。日阶段通过`verified_raw_audit`传入刚完成的当前Raw读回结果，核passed、T、layer、正式路径及文件sha后直接复用，不重做261字段对账。`raw_materialization_storage_id`取物化EventLogRecord.storage_id；本合同的`raw_check_storage_id`取绑定检查的AssetCheckExecutionRecord.id，与Silver的silver_check_execution_id同属检查执行记录编号，不是检查evaluation事件的storage_id。初始化CurrentPublication的raw/silver_check_event_storage_id另从真实检查事件取得，不能将这几种编号互填。所有编号只从实际已持久化记录取得，不猜id。

repair或sensor没有本次B/U时，**不调用Raw合并对账函数、不读取旧下载数据来重做B+U、不用Raw与自身比较填全零**。按现行`readiness.py::_latest_materialization`、`asset_readiness_status`的资产/分区过滤与`target_materialization_data.storage_id`关联方式，读取原T Raw最新物化和对应Raw综合check；确认检查通过、blocking、契约/处理版本匹配、检查指向该物化，正式路径及当前文件sha与两项metadata一致，直接接受该文件生产时已经通过的字段/主键/日期/源保存/合并对账结论。例：原日run因历史失败而终态FAILED，不能否定此前Raw真实通过的检查。仅缺检查/绑定错误/文件身份变化时不得沿旧结果放行，报告管理员处理；本repair不替原日补做来源对账。

覆盖也复用已有结果：先核DG日阶段raw_coverage关联Raw物化/check真实有效，再按T、Raw SHA、契约/处理版本、生命周期、最终停牌及identity_file_sha256判断适用。全部不变直接用原计数/complete，不重算集合；新等价Raw物化/check只在核真实绑定后换记录id，不能仅因事件id变化重算或把新id填进未经核验的旧结果。

新执行准备时原日无覆盖，或既有输入身份已经改变，才对原T必要代码计算一次覆盖；Raw没有有效生产check时先拒绝。已进入本run历史处理后，发现输入变化按上一规则停止，不能在三个边界重新evaluate。Silver身份及既有DG结果同次复用，不重做261列；sensor不走写入串联。

日更和repair的固定串联为evaluate→write_stk_factor_pro_missing_codes（有效旧引用/0缺失/未知时直接返回，无额外文件）→保存本次coverage→判断历史资格。`require_stk_factor_pro_history_raw`仅在coverage.complete is True且raw_check_passed为True时返回；其他结果一律按§5.2.2抛固定Failure。自动调用方不足或未知时写历史waiting并结束，不调用require；仅True时调用require，再核原T Silver及完整名单/范围。repair调用方保存实际coverage后直接调用require，不能把失败转成等待或执行日更新。sensor不走保存串联。

本结果保存到本轮历史判断记录，文件固定为`history-eligibility.json`，结构为record_version=1、当前RunIdentity、当前完整plan/ranges摘要、raw_coverage对象（逐字段对应上述结果）、target_silver:StkFactorProTargetSilver|None、evaluated_at。target_silver仅在按§5.2.3完成核验后填入，Raw前置未过或尚未进入该步时为None；不能把None当Silver通过。两接口因子差异另留诊断。该记录不作为下一失败任务复用旧下载数据的依据。

开始历史下载前、首次历史提升前、完整范围完成前三处只比较本run已确认的T/P、原T Raw/Silver及覆盖依据身份，复用首次结果和摘要，不重新读PG、计算全文件SHA或再做字段/覆盖审计。身份改变即停止本轮历史，已提升文件保留；不能在本次重新读取、重新审计并判断“仅范围外变化”后继续。下一获准执行重新准备。三个逻辑边界保留，不把它们实现为三轮完整审计；细节见§18.5。

#### 5.2.2 repair不通过时的失败与metadata

直接使用本数据集已规划的`dg.Failure(..., allow_retries=False)`及§6.1既有字段，不给下载器新增错误码：

```text
description/summary = 原日期数据缺失：2026-10-21；请管理员处理原日期数据后重试历史repair。
goldenshare/retryable = false
goldenshare/failure_phase = history
goldenshare/target_trade_date = 原T的ISO文本
goldenshare/source_error_code = None
goldenshare/summary = 上述固定主提示
goldenshare/next_action = 说明Raw文件缺失/缺哪些代码/输入未知；先由管理员另行处理原T，本job不嵌套日更新。
```

同一失败metadata附`raw_coverage_complete`（bool或None）、`raw_check_passed`（bool）、coverage_rule_version及expected/actual/missing/extra计数（未知为None）、至多20个缺失代码及首次已确认文件sha。只放统计和受控文件位置，不含token。原T不能替换成repair执行日，错误不转成历史请求；同次结果和摘要直接复用，不为生成metadata重新读业务文件。

#### 5.2.3 原目标日Silver的有效性

原T Raw覆盖通过后，日更与手动repair均使用本节首次evaluate结果及require，取得并记录target_silver.ready=True后才下载历史；日更前面的T日Silver发布/check已经完成，不重复做全字段校验，直接接收该次已取得的凭据，不重新读取。两入口在历史下载前、首次提升前和完成前使用同样条件；同run输入未变直接复用上次结果。这里的DG记录要求属于历史资格及最终结果有效性，不是共用集合计算的前置；不得将事件编号或检查查询下沉到calculate_stk_factor_pro_coverage。实现仍在`defs/asset_guards/stk_factor_pro_readiness.py`，类型在既定run_contracts，不新增检查定义或资产。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProTargetSilver:
    target_trade_date: date
    ready: bool
    silver_file_sha256: str | None
    current_raw_file_sha256: str
    source_raw_file_sha256: str | None
    silver_materialization_storage_id: int | None
    silver_check_execution_id: int | None
    reason: str

def evaluate_stk_factor_pro_target_silver(
    instance: dg.DagsterInstance, *, lake_root: Path,
    raw_coverage: StkFactorProRawCoverage,
    known_pg: dict, known_records: dict,
    verified_silver_audit: StkFactorProFileAudit | None = None,
) -> StkFactorProTargetSilver: ...

def require_stk_factor_pro_history_silver(
    result: StkFactorProTargetSilver,
) -> None: ...
```

调用前直接接收本任务已持有的RawCoverage及两层事件映射；没有本次已得事实才首次有界读取，不能在每个consumer重新查latest。raw_coverage必须complete=True、raw_check_passed=True且Raw文件身份有效；复用已取得的Raw身份，不再查一次Raw或重新比较股票集合。固定步骤：

1. 先使用known_pg中本T的Silver物化及检查；只有本任务尚未取得该事实时才用`instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=Silver, asset_partitions=[T.isoformat()]), limit=1)`取得原T最新Silver物化；没有记录不扫旧历史寻找绿色结果。check_key固定`silver_stock_factor_pro_file_contract_check`，沿现行`partition_dataset_readiness_status_from_latest_checks`调用`get_latest_asset_check_execution_by_key((check_key,), partition_filter=PartitionKeyFilter(key=T.isoformat()))`取得该分区最新检查；PartitionKeyFilter按现行readiness.py同一模块导入。没有物化时不再查询check。只读既有记录，不调用被装饰的asset/check执行函数，不改通用readiness消费者。
2. 核物化、check均是原T的Silver；check状态SUCCEEDED、passed=True、blocking=True，target_materialization_data的storage_id/run_id/timestamp均与这份物化对应。silver_materialization_storage_id取真实物化record.storage_id，silver_check_execution_id取返回检查记录的id，不能将检查执行id当成物化storage_id。核契约、处理版本和固定正式路径。生产run不必与本repair相同，也不能仅因原生产run后来历史失败而否定已通过的Silver检查。
3. 固定正式Silver文件须存在、无越界符号链接，其当前字节SHA与物化/check metadata中的file_sha256相同；本run传入verified_silver_audit时直接使用其摘要及文件身份；否则仅本任务首次加载该旧文件时取得摘要并登记known_records，后续不重算。Silver物化及check必须同时保存`raw_sha256`，两者一致且等于已确认的当前Raw文件SHA。日更Silver发布时写入此字段，不能由repair猜测补齐。Raw后来等价重物化、事件id变而文件SHA未变时仍可通过；不要求两层生产run相同，不用Raw事件id变化误判Silver过期。
4. 全部满足才ready=True；此时两项Silver记录id及所有文件SHA全有。缺文件、缺物化、缺check、绑定错误、旧Raw SHA、当前文件变化或读取失败均ready=False并写明原因；可缺的信息为None，不自行重建Silver或重做261列对账。整个任务首次缺少旧Silver事实时最多1次物化查询+1次分区check查询+原T一份Silver首次身份核对；本run发布已得事实则对应查询/SHA为0；后续输入未变直接复用，不按历史日期增加。

require仅在ready=True时返回，否则抛`dg.Failure(..., allow_retries=False)`，主提示固定为`原日期Silver不可用：<T>；请管理员先处理原日期Silver后重试历史repair。`。failure_phase=history、retryable=False、source_error_code=None，metadata附Silver结果、原T、受控正式路径、当前Raw SHA及已有记录id；管理员看到具体缺失/不匹配原因。此分支零技术因子请求、零历史提升、零原T写入，不嵌套调用日更新/生成Silver。该提示与§5.2.2的Raw缺失提示分开，先Raw、后Silver，不能混淆原因。

本节检查的是**原目标日T**的Silver；不要求每个待回刷历史d的Silver预先存在。历史d缺Silver时，由本次刷新后的Raw d生成并检查，仍只发布d<T。日更、历史回刷及bootstrap历史事件补记产生的Silver物化/check均维护同一个raw_sha256字段，不能不同入口各用一个名字。target_silver结果写入已有history-eligibility及历史阶段观察的同名字段；失败前先yield包含实际检查结果的阶段观察，再抛Failure，不制造新的T物化或绿色check。

### 5.3 文件与结构

本run候选/业务记录位于`/Volumes/datasource/data_lake_staging/stk_factor_pro/trade_date=<T>/run_id=<当前run>/`，路径只由paths.py生成。失败后不删除旧证据，但新run不读取旧下载/发布候选作业务输入；原完整名单和范围授权可读回，避免丢失待修复意图。

| 文件/记录 | 当前用途 |
| --- | --- |
| `history-plan.json`、`history-ranges.parquet` | 技术下载前保存完整变化/原未完名单、权威T/P、可信范围和授权来源；不按本轮返回代码缩小。 |
| `history-eligibility.json` | 本轮原T Raw覆盖判断及输入身份。 |
| `source/history/`及其`source-files.parquet` | 仅当前run新下载的完整历史261字段unit，逐unit保存/首次读回并释放网络/Python对象，SQL源继续保留；不创建`source/day/`。 |
| `source/history/source-complete.json` | 只供当前运行在全部预期历史unit及全部会话成功后进入处理；失败后下一run不得沿用。日下载的完成凭据是当前内存`VerifiedDaySource`，不保存日source-complete、日manifest或另一份日源Parquet。 |
| `publication/<phase>/<d>/<layer>/` | 当前run原子发布必需的候选、intent、逐文件checkpoint及历史缺原键诊断；仅供当前run发布。day只构造一份Raw发布候选，随后从同连接已发布Raw对应的RAW_EXPECTED构造一份Silver候选，不能把日unit另存为下载中间文件。失败任务的候选不再被新任务读取。 |
| `publication/<phase>/publication-complete.json` | 当前完整范围物理发布读回事实；历史去重还须来源run最终成功，失败run部分或全部文件事实不免除新下载。 |

完整plan由writer原子保存并直接交出对象/摘要后，先yield AssetObservation记录T/P、D/轮次、当前run、plan/ranges位置及摘要、受控staging目录，再写开始下载观察并读回，成功才联网。阶段完成和失败结果仍走已有事件metadata；历史source-complete不替代文件验收，run SUCCESS也不代替完整范围事实。日阶段没有保存下载中间文件或复用下载结果的分支。只按已验证run和固定路径读取历史工作范围/发布记录，不全扫staging。

### 5.4 现有记录的封闭结构与摘要

本节限定Tushare日更及历史处理记录的字段结构；bootstrap批准/源记录及覆盖附件分别以§10.2～10.5为准。记录类型/字段顺序/有限原因集中在`defs/run_contracts/stk_factor_pro.py`，读写在既定io模块；不新增数据库或记录平台。

#### 5.4.1 公共类型、身份与读写

| 类型 | 固定要求 |
| --- | --- |
| Date / Instant | Date为Python date、JSON YYYY-MM-DD、Parquet DATE；Instant为aware datetime、JSON固定微秒和+08:00。时间不参与业务输入摘要。 |
| Digest / Count | Digest为64位小写十六进制SHA-256；Count为非负精确int，不能是bool。 |
| Double | 经§9.1转换的有限float，Parquet DOUBLE；NULL按源字段可空合同，不用NULL冒充0。 |
| RecordRef | `{creator_run_id:str,relative_path:str,file_sha256:Digest}`；路径必须在已验证run的staging根内，不接受绝对路径、..或符号链接越界。 |
| ContractIdentity | `{contract_name:str,contract_version:str,contract_content_digest:Digest,processing_version:str}`，本期源名stk_factor_pro、独立version和processing_version均为1。 |
| RunIdentity | `{creator_run_id:str,source_run_id:str|null,execution_day:Date,target_trade_date:Date,previous_trade_date:Date,purpose:str,scheduled_slot:int|null}`；source_run仅指原名单/范围授权；目标结构删除旧提交序号及机会字段，见§21.12。 |
| phase / purpose / layer | phase为day/history；purpose为today/manual_date/bootstrap_supplement/manual_repair；layer为raw/silver。 |
| record_version | 精确int=1；未知/缺失字段、错类型或错版本拒绝，不能猜默认。 |

自动和指定日期身份按§21.4；历史repair的T/P仍取原授权日期。配置、RunIdentity、阶段观察及原生重执行同步使用目标结构，不保留自动补前日字段。原历史范围、因子比较和成功判定不因此改变。

`HistoryPlanReason`集中定义名单原因。1=本次T/P变化，2=原T失败/未完范围保留，3=缺P，4=缺T，5=两日因子都缺，6=生命周期证明无原历史。第六批按§3.6新增7=当晚复权因子修订追修，只用于自动追修的生成和待刷继承。每股原因去重升序，原1～6的记录继续按原含义读取。

统一写入：校验完整结构/交叉条件→内存合法对象序列化并计算payload摘要一次→受控临时文件→flush/fsync→os.replace→fsync父目录→直接返回对象、摘要与引用。旧历史下载文件可保留排障，日下载没有单独保存的中间文件。读取原记录时只取历史工作范围/授权/失败或已成功事实，不把旧历史Parquet当本run源。接口：

```python
def read_stk_factor_pro_history_plan(root: Path, *, expected_target: date,
    expected_run_id: str, known_records: dict) -> HistoryPlanRecord: ...
def write_stk_factor_pro_history_plan(root: Path, record: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...], *,
    connection: DuckDBPyConnection, known_records: dict,
) -> tuple[HistoryPlanRecord, str]: ...
def read_stk_factor_pro_history_ranges(
    connection: DuckDBPyConnection, *, root: Path, plan: HistoryPlanRecord,
    known_records: dict,
) -> tuple[HistoryRange, ...]: ...
def verify_stk_factor_pro_current_source(root: Path, record: SourceCompleteRecord,
    *, connection: DuckDBPyConnection, current_run_id: str,
    expected_units: tuple[UnitProjection, ...],
    source_relation: str, source_complete_ref: RecordRef,
    known_records: dict,
    verified_files: tuple[SourceFileRecord, ...],
    file_identities: tuple[tuple[str, tuple[int, int, int, int, int]], ...],
) -> VerifiedSource: ...
```

`read_stk_factor_pro_history_ranges`首次读取时完成schema、唯一代码、NULL/日期/原因、full_code_count及摘要检查，使用同一主要连接返回冻结tuple。plan writer已经首次确认物理传输的同次ranges结果直接交接，download/publication不得再从Parquet解析并完整审计同一ranges。新执行首次读取原授权仍核一次；受控路径、run及摘要绑定保持，不另开连接。

`write_stk_factor_pro_history_plan`负责新ranges文件的物理引用：输入record的身份、固定相对路径及两个业务摘要先严格核对；写成并读回新Parquet后，以实际文件字节SHA构造最终ranges_ref，使用dataclasses.replace生成最终冻结plan，再原子保存JSON并直接返回(final_plan,payload_sha256)；原ranges tuple及首次物理引用继续交接，不从Parquet重载。输入record仅作本次新计划的构造值，其ranges_ref SHA不能被调用方当成已落盘凭据；调用方必须使用函数返回的plan。已有ranges或plan一律拒绝覆盖，不用此方法修补旧记录；业务摘要不被writer改写。

内部把上述保存步骤集中为私有保存函数。公开writer接收首次独立输入时核对业务摘要一次，再调用该函数；builder已经按同一合同生成完整合法计划和两个摘要，直接交同一保存函数，不再走公开writer的首次输入核对。两条调用共用唯一写入实现，不新增公开入口、缓存键或“跳过检查”参数；公开writer的错误输入反例继续有效。

计划摘要函数仍接收完整ranges，但必填接收调用方已算出的ranges_digest；其内部只组装计划摘要内容，不再次计算范围摘要。builder先算范围摘要，再算计划摘要；独立writer首次核验同样复用本次核验得到的范围摘要。摘要算法和保存字段不变，全部内部调用方及测试同步传递，不提供缺参重新计算的分支。

本节record reader统一必填接收同一known_records：首次明确需要的旧记录未登记时，只由这些读取函数读一份字节/Parquet并登记对象、摘要和身份；键已存在直接返回。下载、源组装和发布是消费者，当前plan/ranges/manifest/source-complete缺少既定登记即接口错误，不能自行回盘补齐。已确认不存在的旧路径登记(None,None,None)，坏文件继续报错；本次合法写入成功才更新该键。原成功范围的plan/ranges/source/publication同样只首次取得一次。

```python
def write_stk_factor_pro_source_files(
    root: Path, *, connection: DuckDBPyConnection,
    identity: RunIdentity, contract: ContractIdentity,
    files: tuple[SourceFileRecord, ...], known_records: dict,
    check_space: Callable[..., BootstrapSpaceEstimate],
) -> RecordRef: ...

def write_stk_factor_pro_source_complete(
    root: Path, record: SourceCompleteRecord, *, known_records: dict,
    check_space: Callable[..., BootstrapSpaceEstimate],
) -> tuple[SourceCompleteRecord, str]: ...
```

该writer返回(record,payload_sha256)，内部_json_write直接返回首次payload形成的RecordRef并登记known_records；不得写完再读。build_history_plan返回(final_plan,ranges,plan_ref)，其中plan_ref直接使用计划writer的首次payload摘要、当前run和固定history-plan.json构造；原ranges tuple继续交接。download接这三项及known_records，SourceComplete.history_plan_ref直接等于plan_ref；源writer成功后，当场由其返回摘要构造source_complete_ref并传verify。verify的VerifiedSource.source_complete_ref直接取该引用，plan/manifest各引用与已登记值比较，不能重新读记录或序列化计算摘要。manifest writer直接返回首次RecordRef；输入的已核files tuple由调用方原样继续交接，不额外构造第二返回值。publish只消费完整VerifiedSource与已传plan/ranges/关系，无须为此另取记录。

`verify_stk_factor_pro_current_source`改为首次源审计事实的组装入口，connection仍为现有主要连接。各unit在首次保存时完成一次完整审计并产生SourceFileRecord/摘要；全部session正常退出后，该函数只核当前run、契约、expected_units、manifest及已审记录完整对应，不再打开每份源做完整检查或SHA。VerifiedSource承接这些本run已核事实及文件身份；发布消费它，不第二次调用完整源审计。具体接口交接见§18.3。

`SourceCompleteRecord`及`VerifiedSource`只用于phase=history，保存当前run历史文件引用/统计。verify必须要求record.phase==history且record.identity.creator_run_id==current_run_id，错阶段/错run即拒绝，不能通过原run有效而放行旧源。日阶段使用以下仅存内存的类型和接口，不执行JSON序列化、Parquet写入或RecordRef生成：

```python
@dataclass(frozen=True, slots=True)
class VerifiedDaySource:
    identity: RunIdentity
    contract: ContractIdentity
    unit_result: UnitResult
    summary: DownloadSummary
    raw_relation: str
    scope_digest: str
    day_source_digest: str

def verify_stk_factor_pro_day_source(
    connection: DuckDBPyConnection, *, identity: RunIdentity, result: UnitResult,
    summary: DownloadSummary, contract: ContractIdentity,
) -> VerifiedDaySource: ...
```

`verify_stk_factor_pro_day_source`只在下载session成功退出后调用。校验当前run/T/契约、单一BY_POINT unit及scope、全部scope完成的termination、observed_field_sets、统计与最终summary，精确要求total/completed/delivered unit均为1、两项summary行数均等于len(result.records)及unit统计。随后按§9.1从本次records按列构造当前U，在本任务主要连接执行`CREATE TEMP TABLE stk_factor_pro_day_source AS SELECT <显式261列转换> FROM current_batch`；校验字段/日期/主键/数值和完整业务内容后按§5.4.2计算day_source_digest。必须是独立临时表，不能用解除DataFrame注册后即失效的view；转换DataFrame注册可解除，临时U及B/RAW_EXPECTED保留至本日必要数据计算及小结果交接完成，控制层统一DROP；事件/统计/阶段收尾只保留小结果，finally同样释放。不COPY出日源文件。raw_relation只能是此内部固定名，不接受配置SQL或外部名称。类型是调用内部传递数据，不能来自读取旧文件，构造器不得接受外部传入passed或摘要来绕过计算。

组件`UnitResult.records`为已交付tuple；`DownloadSession`关闭释放自己的引用，不修改调用者仍持有的tuple，因此可在with成功退出后处理本次结果。不得把它存入全局缓存、其他run或序列化为日源文件。网络UnitResult及DataFrame/列转换对象不再需要时及时释放引用；SQL的U、B、RAW_EXPECTED及相关键关系保留至本日必要数据计算和小结果交接完成，再由控制层统一释放；后续事件、统计与阶段收尾仅用已得结果。失败路径收尾只消费已有结果，finally同样清理。日阶段调用方用同一个try/finally包住下载、verify和publish，不能只清局部result却继续让VerifiedDaySource持有它，或带着它进入历史阶段。日发布函数只返回§5.4的文件/计数/摘要事实，不在发布结果、进度闭包或阶段记录中夹带UnitResult/行集合。原始tuple、当前转换列和DuckDB关系的同时存活须计入§10，不额外复制一份完整Python行列表。失败阶段不触发业务源自动重试；下次新执行全新下载。

#### 5.4.2 摘要投影

复用现有`contract_registry.content_digest`；业务调用为`content_digest({"record_kind":kind,"record_version":1,"value":projection})`。日期先为ISO文本；DOUBLE因子为有限float.hex()，数值0统一0.0.hex()；投影不直接含float/date/Decimal。1、1.0、1.00归一化后相同，不引入容差。源contract_digest仍直接采用组件原算法。

| 摘要 / kind | 精确投影 |
| --- | --- |
| history_ranges_digest / stk_factor_pro.history_ranges | 按代码/起止排序的`[{ts_code,start_date,end_date}]`；未知范围保留null行，不删原完整名单对象。 |
| history_plan_digest / stk_factor_pro.history_plan | T/P、ContractIdentity、history_ranges_digest及按code排序entries；每项code、t_present/p_present、t_value_hex/p_value_hex、plan_reasons、去重升序origin_target_dates、earliest_basis(kind/date)。 |
| unit_key / stk_factor_pro.unit | 单个UnitProjection，固定字段mode/object_code/point/start_date/end_date；mode为整数，日期先转ISO文本，null显式保留。精确公式为content_digest({"record_kind":"stk_factor_pro.unit","record_version":1,"value":projection})，不含run、ordinal、文件路径或20日批号。 |
| scope_digest / stk_factor_pro.scope | phase、T及排序units；UnitProjection固定`mode:int,object_code:str|null,point:Date|null,start_date:Date|null,end_date:Date|null`。day只有mode2/point=T，history按§5.1.2取已判明、尚需本次新下载的完整请求范围，每code一项mode5/start/end；已证明独立成功及原因6对象保留在完整plan中但不进入本次units，不能按实际返回几只再缩请求范围。 |
| history_input_digest / stk_factor_pro.history_input | T/P、ContractIdentity、scope_digest及该完整请求范围内按code排序的权威t_value_hex/p_value_hex。不含范围外股票或整份因子文件sha。 |
| day_source_digest / stk_factor_pro.day_source | 仅日阶段：ContractIdentity、scope_digest、当前单unit的UnitProjection、source_row_count=len(records)、完整U的row_count、schema_content_digest及§8.1算法计算的Raw表示content_sha256；不含文件路径、manifest、run或时间。由当前内存U计算，不生成日下载完整记录文件。 |
| files_manifest_digest / stk_factor_pro.source_files | 仅历史阶段：scope_digest及按unit_key排序的unit业务投影、源/保存行数、file_sha256/file_rows/schema_content_digest。不含当前路径/run/时间。 |
| schema_content_digest / stk_factor_pro.local_schema | 契约字段顺序的`[{name,type}]`，本地类型只VARCHAR/DATE/DOUBLE，不取DataFrame dtype展示文本。 |

上述业务摘要不含run_id、追溯路径、slot/提交序号、诊断、完整因子文件sha或20日批次参数。摘要只在对应产物首次形成/审计时计算并保存；同次RecordRef交接比较已有摘要和归属，不因_ref_path调用重新读取全部字节计算SHA。plan/ranges写成后不可原地修改；新run输入变化按原revision规则准备，处理中发现变化停止，不重审后继续。

业务内容摘要用于本次候选/正式文件等价比较、成功结果核对及bootstrap片段校验，算法见§8.1。失败run的源及候选不得作为新run的业务输入。

#### 5.4.3 各现有文件

**history-plan.json**：`record_version,identity:RunIdentity,contract:ContractIdentity,revision:int>=1,created_at:Instant,history_plan_digest,history_ranges_digest,ranges_ref:RecordRef,full_code_count:Count,factor_t_ref:FactorFileRef,factor_p_ref:FactorFileRef,revision_of:RecordRef|null,origin_plan_ref:RecordRef|null,origin_history_plan_digest:Digest|null,origin_history_ranges_digest:Digest|null`。

FactorFileRef固定`trade_date:Date,asset_key:str=raw_tushare_adj_factor,file_sha256:Digest,rows:Count`；路径按正式paths复算。自动首次origin三项null，repair全有。repair始终保留原完整授权引用，不把本次新权威值摘要替换原授权。full_code_count等于ranges唯一代码数。

**history-ranges.parquet**：`ts_code VARCHAR NOT NULL,t_present BOOLEAN NOT NULL,p_present BOOLEAN NOT NULL,t_value DOUBLE NULL,p_value DOUBLE NULL,start_date DATE NULL,end_date DATE NULL,plan_reasons INTEGER[] NOT NULL,origin_target_dates DATE[] NOT NULL,origin_record_refs VARCHAR NOT NULL,earliest_basis_kind INTEGER NULL,earliest_basis_date DATE NULL`。唯一键ts_code；origin_record_refs是固定字段T/run/relative_path/file_sha的规范JSON数组，仅追溯。present=false必须value=NULL；有效历史请求因子/范围必须已判明、start<=end、end=T；范围未知不猜起点。earliest_basis_kind只1=可信现有最早日期、2=已批准bootstrap事实。缺关键因子/范围保留未判定并明确停止对应历史，不用技术行相等作门槛。

**history-eligibility.json**：`record_version,identity:RunIdentity,history_plan_digest,history_ranges_digest,raw_coverage:StkFactorProRawCoverage,target_silver:StkFactorProTargetSilver|null,evaluated_at:Instant`。覆盖结构及完整缺失清单引用见§5.2.1。原T Silver有效性独立保存，未执行该步为null。本记录确认下载历史前的日覆盖及Silver资格。自动追修历史源下载后的因子核对按§3.6处理。

**source/history/source-files.parquet**：`phase VARCHAR,unit_key VARCHAR,component_unit_id VARCHAR,ordinal BIGINT,mode INTEGER,object_code VARCHAR NULL,point DATE NULL,start_date DATE NULL,end_date DATE NULL,source_row_count BIGINT,saved_row_count BIGINT,file_relative_path VARCHAR,file_sha256 VARCHAR,file_rows BIGINT,schema_content_digest VARCHAR,contract_content_digest VARCHAR,verified_at TIMESTAMPTZ`，除明确NULL列外均NOT NULL。phase只能history，唯一键(phase,unit_key)，每完整历史unit一个261列文件（合法0行也保存明确schema文件）。mode5/code/start/end全有且end=T，point=null。ordinal仅当前任务内序号；component_unit_id保留组件原值。statistics.row_count==len(records)==saved_row_count==file_rows；逐项字段/范围/身份必须对应，不能只比unit数。日阶段无该文件及引用。每个unit源文件固定为当前run下`source/history/units/<unit_key>.parquet`，manifest的file_relative_path从当前run根表达为同一路径；合法0行也写完整schema文件。只由unit_key函数生成文件名，写前核safe_path和source/history归属、拒绝已有文件，不能套用仅允许candidates目录的检查或放宽候选目录规则。

**source/history/source-complete.json**：`record_version,identity:RunIdentity,phase:Literal["history"],contract:ContractIdentity,history_plan_ref:RecordRef,history_plan_digest,history_plan_revision:int,origin_history_plan_digest:Digest|null,origin_history_ranges_digest:Digest|null,history_input_digest:Digest,scope_digest:Digest,expected_units:list[UnitProjection],files_manifest_ref:RecordRef,files_manifest_digest:Digest,completed_unit_count:Count,verified_at:Instant`。历史input必填；repair原授权非null。仅在§6全部历史会话正常退出、最终summary通过后，全部expected_units与manifest身份/计数/读回一一对应，且全部属于当前run才写成。空历史名单直接跳过，不伪造下载完成。任何新run都不得以此省去失败任务的重下载。不存在日阶段source-complete。

**publication/<phase>/<d>/<layer>/intent.json及complete.json**：同一当前run固定结构`record_version,identity,phase,trade_date:Date,layer,contract,scope_digest,history_input_digest:Digest|null,day_source_digest:Digest|null,source_manifest_digest:Digest|null,target_path:str,candidate_relative_path:str,prior_sha256:Digest|null,candidate_sha256:Digest,candidate_rows:Count,expected_published_sha256:Digest,mode:Literal["reuse","replace"],stage:Literal["intent","complete"],unrefreshed_keys_ref:RecordRef|null,unrefreshed_count:Count|null,verified_at:Instant|null,actual_sha256:Digest|null,actual_rows:Count|null`。day必须day_source_digest非空、source_manifest_digest及history_input_digest为null；history反过来，day_source_digest为null、两项历史摘要必填。day候选固定candidates/day/<layer>/data.parquet，history候选固定candidates/history/<d>/<layer>/data.parquet；历史缺原键附件固定publication/history/<d>/<layer>/unrefreshed-keys.parquet。路径都相对当前run，d必须小于原T；日分支仍只能T，不改变既有日候选路径。target按T/d/layer复算并核对；prior仅当前候选构建时的正式文件sha，缺文件为null。reuse指当前正式内容已与**本次新下载生成的候选**等价、无需replace，不指旧源复用；其expected=prior，replace的expected=candidate。intent末三项null、complete全有；历史缺原键计数必填；0缺口时引用为null且不写附件，非零才有真实非空附件引用，日二者null。

**publication/<phase>/publication-complete.json**：`record_version,identity,phase,contract,history_plan_digest,history_ranges_digest,scope_digest,history_input_digest:Digest|null,source_complete_ref:RecordRef|null,day_source_digest:Digest|null,source_manifest_digest:Digest|null,targets:list[PublishedTarget],verified_at:Instant`。day的source_complete_ref、source_manifest_digest、history_input_digest均为null，day_source_digest必填且来自本次内存U；history的上述三项必填、day_source_digest为null。不能为满足结构而生成日下载文件或虚构其引用。PublishedTarget固定`trade_date:Date,layer,skip_no_file:bool,file_sha256:Digest|null,file_rows:Count,checkpoint_ref:RecordRef|null,unrefreshed_count:Count,scope_rows:Count|null,scope_content_sha256:Digest|null,scope_content_version:int|null`；无旧无源日期明确skip=true、hash/ref=null/数量0，不假物化；有文件则skip=false、hash/ref齐全。历史scope三项全有，记录该完整成功范围在本日期/层的行数、业务内容摘要及版本1，空范围为0及空串SHA；day三项全null。全部预期日期/层去重升序无遗漏，历史所有unrefreshed_count=0才可完整。正式完成后还须同producer run最终成功才可成为后续正常轮次的历史免重刷依据。失败run即使此文件存在也不能复用其源/候选或部分checkpoint跳过重下载。

后续同T轮次通过§6.2读取**原来独立成功的整个范围**的DG阶段记录及publication-complete引用，并核其计划、范围和source-complete元数据。原T、该完整范围的全部代码/起止、对应权威T/P、契约及处理版本匹配时复用成功结论。新增无关股票不使原独立范围失效。其他目标日回刷覆盖相同历史日期时，旧任务仍按自己的完成记录判断，不追查跨目标日的发布记录，不重读历史文件或重算范围摘要。后一次回刷成功就保留其发布结果，后一次失败由该任务保留待刷范围并按失败规则重新下载。失败run不能作为成功依据，也不按页、股票或日期领取其部分成果。

#### 5.4.4 小样本门禁

必须用独立字面样本证明：换run/路径不改业务输入摘要，改code/边界/权威值必须变；未知范围null不可删；历史source记录错run拒绝；日0行合法完整unit只留内存、历史0行完整unit可保存，缺列/计数不符拒绝；所有record必填/类型/未知字段校验生效。日阶段不得创建source/day、日source-files/source-complete或另一份日源Parquet；完整UnitResult须在with退出后仍可转成本次U，最终summary不成功则Raw候选及正式提升均0。day/history来源摘要与引用的互斥条件必须有反向测试。失败run即使历史source-complete及全部候选存在，新run仍有实际新网络请求，测试必须让旧Parquet一旦被当新输入读取就失败，不能只检查配置flag。bootstrap使用自身独立合同，不套本节失败重下规则。

## 6. 下载契约、线程、进度、错误与取消

完整契约名`stk_factor_pro`，独立version，不加来源前缀或`@1`。完整261业务字段含ts_code/trade_date及259数值；本地辅助列不进入接口fields。普通单日`DownloadTask(..., mode=DownloadMode.BY_POINT, points=(T.isoformat(),))`，历史`BY_OBJECT_RANGE`；代码扇开在组件内，业务规划范围/窗口。相同代码多窗口分次任务，同任务重复object_code被1102拒绝。

本文T、起止日期为本地`datetime.date`；进入组件前显式转为ISO字符串。历史统一使用`TimeRange(start.isoformat(), end.isoformat())`；各股范围不同则`ObjectTimeRange(code, TimeRange(start.isoformat(), end.isoformat()))`，不得把date直接传入组件。写本地unit记录时，组件scope中的ISO文本按本地Date合同显式解析，不把HTTP源行的YYYYMMDD与scope日期混用。`component_unit_id=result.unit.unit_id`，`ContractIdentity.contract_content_digest=result.unit.content_digest`；不按本地记录字段名猜组件属性。

分页暂定limit10000、offset从0步进10000、短页/空页结束、满页继续；属于源契约，不让业务传fields/limit/offset/token/地址。第一批已验证一股五日的小页offset和固定HTTP，真实10000满页边界仍未验证；不得将二者混同。每unit全部页取全后交业务一次。日阶段只留当前一个完整unit；历史必要校验、当前unit落盘/读回后释放，不积累全历史内存。

日下载固定一个BY_POINT任务、一个T、一个unit。with内只接收并保留该UnitResult，不建日下载文件，不创建Raw发布候选；若收到第二个unit立即失败。须正常消费至StopIteration并成功退出with，之后取得`summary=session.summary`。精确要求`summary.status == DownloadStatus.SUCCEEDED`、download_complete为True、total_units/completed_units/delivered_units均为1，summary.row_count/completed_row_count均与唯一unit统计及len(records)相等；然后强制check_cancel，再调用§5.4.1的verify函数构造当前内存U及VerifiedDaySource，交日发布函数。session退出、summary校验或此取消检查失败时直接释放结果，本次不得构造Raw候选或提升。不要在with内先写源、先提升、再等关闭结果。

历史仍采用with内逐完整UnitResult校验、保存历史源片段并读回；正常退出with后核最终summary。每个历史DownloadTask须同样SUCCEEDED、download_complete为True，total/completed/delivered均等于该任务规划unit数，summary两项行数等于该任务manifest行数之和。多窗口分次调用逐session核各自子范围；只有全部历史任务成功关闭、manifest完整覆盖expected_units且行数/身份读回一致，才保存`source/history/source-complete.json`并进入历史合并/提升。空历史名单直接跳过，不创建零unit下载任务。

session关闭可能在全部unit交付后抛1304，或最终为STOPPED/CANCELLED/FAILED；日分支释放当前内存、不构造Raw候选，历史分支不写source-complete，两者均不进入正式发布。已有历史staging仅保留证据。UNIT_COMPLETED/100%或download_complete单独为True不能放行。组件最后一个unit完成回调取消但最终SUCCEEDED的既有行为仍按上述最终summary判断，不自行改组件取消语义。

`TushareDownloader.load()`和`with downloader.download(...) as session`沿用现接口；创建、使用、回调、关闭同线程。DG执行进程直接在执行线程调用，页面业务另开下载线程；跨线程/进程通信由业务接入层负责。组件不创建线程/子进程、锁、额度或全机限频，连接配置直接复用现有读取方法。

PAGE_COMPLETED/RETRY_SCHEDULED/UNIT_COMPLETED只传摘要，业务不在通知中写数据。UNIT_COMPLETED在交付前，100%不等于保存、日发布或历史全完。普通观察回调异常由组件隔离；业务校验/保存异常停止消费并关闭session，不交给组件重试业务写入。

组件错误码保持现有1001配置、1101契约、1102输入、1201权限/参数、1202限频、1203临时源、1204无有效响应、1205协议、1302容量、1304清理/关闭、1401取消、1501未分类源错误。业务原因集中登记，不随意扩展组件错误码。组件同页有限重试不消耗新的前日机会；一次已开始的前日日阶段失败且不能证明已齐，或仍缺/未知，则当天不自动补第二次或推进今天；仅历史失败而Q日阶段已齐不阻止今天。今天的临时源错误可等后续计划时点，永久输入/契约/权限、业务结构或目标冲突先报告停下，不盲重试。

分页/退避取消不交付半unit；完成通知时取消仍交完整当前unit再停，末unit可正常下载完成。业务取消后不领下一unit或提升新文件；replace前检查取消，当前文件一旦已经替换则尽力完成本文件fsync及保存checkpoint小记录后停止下一文件，失败保留intent排障，新run仍重新下载，不回滚已发布内容。网络可能等返回/超时，不强杀线程。with/finally关闭资源，已发布文件保留；午夜允许已运行任务结束，不模拟用户取消。历史前输入或Raw覆盖变了则停历史并留待处理，不能额外自动启动新任务或把它写成全部完成。

取消适配固定在`defs/io/stk_factor_pro_download.py`，日更和repair共用，不直接把现有moneyflow的`_check_cancel(context)`传给组件：该函数返回None/抛错，而组件`DownloadControl.is_cancelled`要求精确bool。

```python
def build_stk_factor_pro_run_control(
    instance: dg.DagsterInstance, *, identity: RunIdentity,
    phase: Literal["day", "history"],
    monotonic: Callable[[], float] = system_monotonic,
) -> tuple[DownloadControl, Callable[[], None]]: ...
```

返回第一个对象传给`downloader.download(control=...)`，第二个`check_cancel`交源保存、候选及发布函数。内部用同线程闭包保存最近一次已核run状态及monotonic时刻：首次必须`get_run_by_id(identity.creator_run_id)`，之后组件的普通取消检查至多每1秒读一次，其余调用只读该局部值；已确认取消永远保持True。`check_cancel`在每个业务unit保存前后、历史合并批前、每文件replace前强制刷新，不受1秒复用限制，取消即抛`dg.Failure(..., allow_retries=False)`并按§6.1记录当前phase及retryable=False。不为每行/每个数值/排序比较查询PG；同一阶段所有下载session和发布步骤复用这对对象，不每页重建。

run_id必须等于当前执行身份；CANCELING/CANCELED返回True，STARTING/STARTED返回False。查不到run、读状态异常或执行中出现其他不匹配状态，直接报业务状态读取错误并停止，不能返回False，也不映射成源端临时错误重试。组件`SessionControl`对控制函数异常直接传播，该适配不放到可吞普通异常的进度回调中；Dagster原生中断同样沿with/finally清理，不吞中断、不强行改成下载成功。只在已有请求/排序/退避等取消检查点读取，不增加后台线程、锁、IPC或定时任务；网络仍可能等当前调用返回/超时。1秒只控制取消状态读取成本，不承诺1秒内终止网络调用。

### 6.1 执行失败与既有历史恢复

sensor源端未齐不创建job，只保存本次评估原因。job的下载、校验、文件写入或取消按实际阶段记录`goldenshare/failure_phase`、目标T、原组件错误码、安全摘要和下一步。正式日数据发布前代码不相等是day失败，零正式日发布；人工指定T重新执行仍完整新下载。

日阶段完成后发生历史失败，保留真实日发布及完整待刷范围。既有历史临时失败、永久失败、范围成功复用、手动repair和按精确run引用解除失败沿原规则执行。自动只对今天在后续合法时点处理可重试任务；更早T由管理员指定日期补跑或使用原授权历史repair。不能因历史失败反推已发布的日数据不齐。

`read_stk_factor_pro_failure`仍只读已核run最近一条STEP_FAILURE，按已有失败metadata定位阶段和是否可重试。未知错误、契约/文件错误与取消不靠切换slot解除，成功事实按实际执行阶段保存。活动任务两job各`limit=2`，当前T结果沿§6.2读取；旧的D/Q提交批和补前日机会查询删除。

每个实际经过的阶段以`AssetObservation(asset_key=Raw, partition=T, metadata=...)`保存固定摘要；开始和预检观察也按§6.2转交完整现有结果：`phase_result_version=1, observation_kind(day/history), target_trade_date, phase, result(completed/waiting/no_action), producer_run_id, recovery_of_run_id|null, pending_plan_refs:tuple[RecordRef,...], successful_publication_refs:tuple[RecordRef,...], unresolved_day_failure_run_id|null, unresolved_history_failure_run_id|null, day_source_digest|null, source_complete_digest|null, publication_complete_digest|null, history_plan_ref:RecordRef|null, history_ranges_ref:RecordRef|null, raw_coverage:StkFactorProRawCoverage|null, target_silver:StkFactorProTargetSilver|null, bootstrap_context:StkFactorProBootstrapContext|null, bootstrap_coverage_refs:tuple[tuple[Date,str,Digest],...], bootstrap_summary_ref:{relative_path:str,file_sha256:Digest}|null, prior_day_result:{run_id,storage_id}|null, prior_history_result:{run_id,storage_id}|null`。字段全有，可空值显式null；record_version/日期/计数按§5.4，storage_id是正精确int。bootstrap_context只用于开发阶段上线前初始化补数，按§10.5.6核验；上线后的普通日更/重新执行/历史repair固定为null，相应bootstrap_coverage_refs为空tuple、bootstrap_summary_ref为None，不读取或更新导入记录，也不因旧观察含Context而转入初始化用途。日阶段source_complete_digest始终null，day_source_digest仅在本次会话及当前U通过后填写；它是摘要，不包含日下载行或日下载文件引用。历史day_source_digest始终null、完整源形成后才填source_complete_digest。日阶段观察保存本run完整计划引用和实际覆盖结果；repair观察保留原授权及当前原T覆盖。失败未形成新计划时引用为null并说明失败阶段，不能伪造计划。

target_silver字段在尚未核原T Silver时为null，核过则完整保存§5.2.3结果；历史completed必须ready=True，失败则保存实际false及原因。raw_coverage仍只表达股票覆盖，Raw齐但Silver坏时保持complete=True，不能改写成股票缺失。完整缺失清单的引用随raw_coverage同时存入PG和eligibility；清单明细不是日下载数据。

bootstrap_coverage_refs保存本阶段实际已更新日期的(date,operation相对result路径,文件字节SHA)，升序唯一；bootstrap_summary_ref只保存本次确已原子写入成功的summary相对路径/payload SHA，未完成为None。无Context时前者为空tuple、后者None。有Context时路径必须在该operation固定coverage目录、无..或符号链接越界，不能套用指向run目录的RecordRef；不要把记录了一个路径当成写入已成功。每日/历史批次收尾把真实值写入阶段观察，历史失败仍保留已完成日引用。

未执行或等待不能写completed，未解除失败及此前独立成功范围沿已验证引用继续保存；新日发布不清除旧历史失败。`prior_day_result`和`prior_history_result`仅指已持久化的同T相应阶段观察。没有相应既有结果时才为null，不能因结果来自同一run而省略。日阶段观察yield并恢复后，按同资产/同T最近1条观察取得实际storage_id，核producer_run_id、phase和本次摘要；已有本次持久化返回身份则直接使用。不能猜编号，也不能在事件尚未持久化时生成引用。进入历史阶段后，每条历史批次观察均保存该实际日结果引用；repair保存本次核验所用的原T日结果引用。`prior_history_result`固定指进入本run前已核的旧历史结果，不把同run每20日的历史观察逐条串成链；当前批次进展由本条观察及完整plan/ranges表达。这样下一run可直接定位既有PG事实，不扫描staging。自动资产及out={}的repair op均用同步生成器yield观察；历史未刷新全范围时，**先yield waiting，恢复执行后再抛Failure**。禁止`context.log_event()`后立即抛错而把尚未持久化的观察丢在缓冲中。没有完成历史不能写publication-complete。

管理员指定T的新run或原授权历史repair可以实际进入失败阶段，真实完成后按原字段保存recovery_of_run_id。日成功只解除日失败，历史成功只解除对应授权历史失败；SUCCESS但未执行该阶段不解除。所有待刷范围和有效日观察按§6.2直接引用。

### 6.2 直接读取DG已有结果

实现仍在`defs/asset_guards/stk_factor_pro_readiness.py`，接口保持`read_stk_factor_pro_recorded_results(instance, *, target_trade_date:date, known_pg:dict, exclude_run_id:str|None=None)->StkFactorProRecordedResults`。该冻结类型及现有字段不变。reader只读取原生run、观察、物化/check和明确引用，不增加状态表，不执行覆盖SQL或完整文件审计。

**生产者必须先保证直接可读。**所有本数据集观察用固定observation_kind区分start/precheck/day/history，均保存phase_result_version=1。§6.1的阶段观察、开始下载和PRECHECK_NO_DOWNLOAD均保存当前完整`pending_plan_refs`、`successful_publication_refs`、`unresolved_day_failure_run_id`、`unresolved_history_failure_run_id`和`prior_day_result`/`prior_history_result`。这四个前置结果字段使用StkFactorProRecordedResults的同名类型；初次执行使用空tuple/None，不能省略字段。待处理引用必须覆盖所有已知原未完成范围，不仅是本次变化；新plan完整合并并保存这些范围后可以用本run的完整plan引用替换被其覆盖的旧意图引用。仅具有最终SUCCESS及有效完整发布依据的独立范围进入成功引用；失败run的部分发布不能进入免下载列表。保存引用不要求复制旧源、候选或业务明细。

普通阶段结果仍按§6.1保存自身结果及完整plan/ranges。开始/预检观察只转交已经核实的结果，不产生自己的阶段完成。start之前若已经保存本run完整plan/ranges，必须把合入旧未完意图后的本run完整plan加入pending_plan_refs，并保存本run计划引用；不能只传旧pending而漏掉本轮新发现的变化。precheck尚未形成新计划时保留已有待处理引用，不制造新计划。日观察写入时`prior_day_result`仍指旧日结果，读该观察时由真实事件身份把day_result_ref更新为本条；历史同理。所有历史批次直接保存已持久日结果和进入本run前的历史结果，不将批次逐条串成链。成功、失败和等待均完整携带当前待处理事实，不能因日发布而丢失旧历史失败。

**调用时点。**asset/op必须在本run首条本数据集观察之前首次调用reader。其后按yield真正持久化的新增记录更新同一known_pg及任务内结果；不再次调用reader查询自己的观察。sensor没有当前run，直接首次读取。`exclude_run_id`用于核实本次入口未把自己当旧结果，不用于先取有限列表后丢弃任意数量自身记录；违反调用顺序是内部接线错误，不能靠增大limit或翻页补救。

```python
entry = instance.fetch_observations(
    dg.AssetRecordsFilter(
        asset_key=dg.AssetKey("raw_tushare_stk_factor_pro"),
        asset_partitions=[target_trade_date.isoformat()],
    ),
    limit=1,
    ascending=False,
).records
# 仅对entry明确引用、且known_pg尚未取得的日/历史结果执行：
referenced = instance.fetch_observations(
    dg.AssetRecordsFilter(
        asset_key=dg.AssetKey("raw_tushare_stk_factor_pro"),
        asset_partitions=[target_trade_date.isoformat()],
        storage_ids=[reference.storage_id],
    ),
    limit=1,
    ascending=False,
).records
```

1. 最新入口核实际asset/T/run、producer、封闭字段、job及配置；日更原生分区等于T，repair虽无job分区，其观察显式partition=T。没有入口才是首次无记录；入口结构坏、明确引用读不到或身份不符均停止，不能扫描旧记录找一条绿色替代。
2. 只取入口自身及其直接日/历史引用。相应阶段就是入口时直接复用，否则按明确storage_id各读一次；核实际run、T、phase和结构。**不沿被引用记录的prior字段递归展开。**当前完整待处理/成功引用和未解除失败取最新入口。被引用阶段提供对应覆盖、Silver或结果凭据。自动追修按§3.6额外使用已解析日观察自身的计划引用，直接复用`known_pg`中该事件，无新增观察查询。查到的同一(run_id,storage_id)供所有消费者复用。
3. 同T最新日更run仍用`get_run_records(RunsFilter(job_name=update_job,tags={PARTITION_NAME_TAG:T.isoformat()}),limit=2,ascending=False)`。排除本run后保留第一条`RunRecord`，其`dagster_run`直接登记`known_pg`。最新日更失败或取消时，从已有失败记录确定阶段，再按下述顺序决定是否用终态补足。最新日更在首条观察前退出且没有更晚的同阶段结果时，仍记录未解除失败。原生run的SUCCESS仍不代替覆盖齐备或历史完成。
4. run按真实run_id精确核身份/最终状态一次。成功发布引用需要的producer也按引用中实际不同run_id首次取得，不设人工任务次数上限，不遍历祖先；普通原生重执行另精确核parent及必要root，初始化授权额外只核明确authorization_run_id。原生run查询已经返回的对象一律复用。历史repair的成功只能解除对应原T/阶段及原范围失败，日失败与历史失败分别保留。入口或直接历史结果若为completed，只在其producer最终SUCCESS、原T资格及完整发布依据有效时，把该run固定publication/history/publication-complete.json及其已存摘要纳入成功引用，并移除被其完整覆盖的待处理意图；producer仍运行或终态失败时保留原完整待处理范围。当前run写观察时尚未有最终SUCCESS，因此不得提前将自己计为独立成功或清除旧历史失败。日阶段真实完成可独立保留，即使该run后来历史失败。
5. bootstrap_context只解析为可空结构。普通上线后用途不展开它或读初始化文件；仅上线前初始化调用方走§10.7专用resolver。readiness不import bootstrap。覆盖/文件凭据不变直接使用，首次必要输入变化才重算原T代码；本run历史中途输入变化只停止，不重新审计后继续。

**同日历史失败的读取顺序（第六批开工前修正）。**修正`defs/asset_guards/stk_factor_pro_readiness.py`的`read_stk_factor_pro_recorded_results`，供日更、repair和第六批sensor共用。先按最新入口及其直接阶段记录得出未解除失败，再处理日更终态。既有`recovery_of_run_id`和生产任务终态核对先执行，已经解除的失败不恢复。日更终态若指向历史阶段，且当前未解除历史失败由另一个已失败或取消的任务的直接历史观察确认，取已加载的该观察的`event_log_entry.timestamp`，与日更的`RunRecord.end_time`比较。没有`end_time`时使用同一记录的`update_timestamp.timestamp()`。历史观察时间等于或晚于日更结束时间时，保留当前历史失败。日更更晚且无对应完成结果时，用终态补足。比较限定同一目标交易日和历史阶段，日阶段失败及阶段未知的退出按原规则单独处理。

**定向验收。**用临时Dagster实例构造同日两条实际任务记录。日更历史因网络失败，后续手动repair明确记录需人工处理的历史失败。读取结果须保留repair的run及不可自动重试的结论。复用既有开始后未写历史结果、首次观察前退出及repair成功解除失败的用例，确认终态补足仍有效，日阶段结果仍单独处理。正常读取、终态补足及回归核对都沿用下述查询上限，无新增表、事件类型、业务文件读取或历史遍历。调用方沿用现有失败详情读取，按最终适用的run复用`known_pg`，每个必要run最多读取一次失败详情。

**查询量及依据。**首次入口1次、limit=1；入口最多有日/历史两个直接引用，额外精确观察查询至多2次、各limit=1，合计至多3条事件，不随历史批次或人工处理轮数增长。最新日更run查询1次、limit=2。其余get_run_by_id次数等于本任务实际必要且尚未取得的不同run_id数量R；先从入口/直接阶段/成功范围及授权引用建立去重集合，记录R和真实调用数，不能用10个自动时点推导人工引用数量。没有必要引用时R=0；失败metadata读取同一run最多一次。历史修复原范围文件的必要读取另按原范围清单计，不藏在观察发现查询里。

依据为本机Dagster 1.13.26的AssetRecordsFilter/fetch_observations实际签名及[官方记录过滤定义](https://github.com/dagster-io/dagster/blob/master/python_modules/dagster/dagster/_core/event_api.py)。本机该filter没有tags参数，不新增依赖该参数的调用，不直接查询框架私有PG表。第五批先以临时统一SQLite事件库存入真实生产格式观察，验证发现和精确读取，再开发完整编排。

回归必须覆盖：大量历史批次后仍直接取得早先日结果；多次合法人工处理不因次数被拒绝；最新开始/预检观察仍带完整旧结果；修复成功解除原失败；首次观察前退出能被原生run记录识别；存在日成功事实也须核其当前绑定；日成功历史失败保留日凭据；缺引用/错T/错run明确报错且零扩大扫描；同一事实重读0。旧源/候选一旦被作为本次输入读取则测试失败。不再用固定轮数制造拒绝测试。

## 7. 失败后的完整新下载

Tushare日更任务失败、取消或进程退出，人工重新执行从目标T完整日源开始；旧日源、下载页、候选不能继续使用。新源及候选均通过§21.5才发布。自动当前日后续处理仍先经过源端齐备门槛。

历史阶段失败保留已发布日文件和完整原失败范围，新执行重新下载完整原失败历史范围，不逐股、逐页或按已发20日续接。手动历史repair仍先确认原T Raw齐备及Silver有效，只处理原授权d<T范围。整范围已成功且业务输入匹配的历史按§5.4.3复用。

单文件replace后退出仍保留已提交文件和原发布事实；下一run使用当前正式文件及全新源生成新候选。文件安全、源重试和Prod bootstrap各自已有恢复规则保持各自职责。

## 8. 合并与逐文件发布

Raw正式路径`/Volumes/datasource/data_lake/raw/tushare/stk_factor_pro/trade_date=<d>/data.parquet`，Silver为`/Volumes/datasource/data_lake/silver/stock_factor_pro/trade_date=<d>/data.parquet`；本run候选仅正式staging根。没有旧Lake、Kopia、备份或跨文件快照。

### 8.0 完整日数据与历史的Raw/Silver顺序

1. 当前run取得T的261字段完整日unit，正常关闭会话并核summary；复用目标T的应有集合检查`DAY_SOURCE`双向差集，缺码或多码即终止，零正式发布。
2. 当前新源与旧Raw形成候选，核`RAW_EXPECTED`代码及原有完整字段/主键/日期对账。通过后发布Raw T，再从该Raw生成和发布Silver T。两层check及唯一覆盖结果直接交历史前置和阶段记录。
3. 原T两层有效后，按完整名单及既有范围下载历史，全部源确认完整才逐日发布d<T的Raw、Silver。历史响应里的T只作诊断，不覆盖日阶段T。

历史日d<T继续使用B-K+U保留未变化旧行。目标日T也复用已有候选构造，但最终代码必须等于T的应有集合，旧Raw额外代码会在提升前停止，具体处置见§21.5。Silver保留完整261业务字段及对应合法值，仅归一化日期为DATE。

### 8.1 当前run的候选、提升意图和逐文件记录

复用现有连接与发布算法，不直接带入moneyflow字段、阈值或锁。所有输入来自当前run的新下载；本轮开始已按既定唯一写入/维护流程排除其他任务。对每个日期/层固定执行：

1. 第一次取得当前正式B时按合同确认其有效记录/身份，所需摘要只取一次。日Raw消费已核VerifiedDaySource的U，历史Raw消费已核本run历史源，不再次完整审计U；构造B−K+U并对新Raw候选完整审计一次。Silver从本日期首次已核Raw生成并对新Silver候选审计一次。差集先计数，非零才保存附件。
2. 新候选首次读回完整审计，产生唯一candidate audit/摘要/行数；后续描述及intent引用它，不重新扫描同一候选。当前目标与本次新结果等价时reuse，保留目标已有结果及摘要，不重复对同一expected关系做字段检查。
3. 当前run intent直接绑定首次已审候选/已有目标摘要、日期、层和范围。提升前只比已有摘要引用及必要文件元信息、同文件系统、空间和取消条件，不重新读取全部字节算SHA。异常身份变化停止，不把重算摘要写成新授权；通过后同文件系统os.replace。
4. 原子提升成功并同步父目录后，沿原candidate audit构造正式文件事实并保存complete；不对同一字节重新DESCRIBE/count/全字段join或重算内容摘要。DG物化/check复用这一事实。I/O或记录失败保留已经发布文件，不伪造成功，也不回滚。
5. replace后取消尽力完成该文件同步及继承唯一audit/摘要的checkpoint，小记录原子写成功即直接交接已得对象和payload摘要，不写后重开。随后停止下一文件；新run不使用旧候选。

历史缺原键清单固定列`layer VARCHAR,ts_code VARCHAR,trade_date DATE`，只对非零差集按d/层保存并首次核验。临时Parquet首次CTAS为本函数持有的读回临时表，schema及双向差异仅消费该表，不重复打开同一附件；临时文件SHA只算一次，原子提升后沿用该摘要并登记正式文件identity，不重新hash。差集表及读回表均由本函数finally各清理一次，保留最初业务错误。0缺口在intent/complete保存unrefreshed_count=0、unrefreshed_keys_ref=None，PublishedTarget只记录已有unrefreshed_count=0，不新增其字段；不COPY、不建目录/附件、不为已知零差集额外执行schema/EXCEPT/SHA。skip_no_file同样只保留零数量及None引用。缺旧键时合法新行和旧行仍保留，不新增blocking check；非零则本轮历史不得写publication-complete，编排先yield waiting及原完整未完范围/数量/非空清单，再抛原Failure。Raw/Silver按层计数及失败新run全范围重下规则不变。

自动今天在后续合法slot经源端门槛可重下原完整待刷范围，仍核午夜和本地上游。更早T使用人工指定日期或原授权历史repair，原失败范围和已发布文件保留。

完整业务内容等价/摘要沿现有ETF形式：261字段固定顺序struct_pack→to_json，按(ts_code,trade_date)升序换行string_agg→sha256，空集为sha256空串，数量另比。Raw和Silver使用各自日期schema，NULL真实编码，不填值或舍入；算法版本1。历史成功范围的scope_rows/scope_content_sha256只记录当轮实际发布范围中各code的start_date<=d<=end_date且d<T的行，同日期多个范围以唯一代码/日期筛选、不重复计行，版本同为1。按当前日期及层在当轮发布时计算。后续复用历史完成记录时按§5.4.3判断，无需再计算这份摘要。

### 8.2 历史20交易日批次与整范围成功

**本节的本次完整请求范围精确取自已验证source-complete.expected_units；完整plan/ranges作为授权上界保留所有对象。**发布前将expected_units与manifest逐项核对，并确认均属于原授权，不用完整名单中的已成功/原因6对象扩大本次U或缺原键差集。

控制层只一次从完整请求范围和已核SSE日历生成d<T开市日期并集publication_dates，去重升序，每20个交易日切批；同一结果供预算、发布及事件计划复用，尾批1～20日直接处理，不凑自然日。先核历史分区已批准登记，缺分区停止，repair不自动注册。无旧无源日期不造空文件/假物化，存在源则以空基础生成。

全部历史源保存并核source-complete后、首次历史提升前，继承每个unit首次源审计已经确认的股票和日期闭区间事实，不再全量重查这两项；使用同一DuckDB连接一次聚合总源关系的日期及本日行数。其中d<T的所有源日期必须包含在上述已核SSE开市日期并集，且每个日期的本数据集分区已登记。日历缺日期/状态未知、已确认休市却有源行、或源日期未进入发布计划时直接失败，说明日期及计数，历史提升0次；不能过滤这些行后宣称范围完整。源中的T行只作既定诊断保留，不进入d<T清单；请求范围外日期包括T之后的行在首次unit源审计已拒绝。用聚合日期集合核对计划，不逐行发起日历或分区查询。

每批至多40个日期/层文件，同任务一个主要DuckDB连接做列式合并与校验；当前日期Raw→Silver完成后再处理后续日期，批内逐文件checkpoint，不是20日事务。当前run完整历史源先保存，不能边下载一股边改全年。批次大小/序号不进入源unit或业务输入身份。

只有当前完整范围所有必要文件/check/读回及原键刷新核对通过，才写publication-complete；producer run最终成功后才成为后续同T轮次可跳过历史的依据。失败后已完成19日、第20日失败也不能跨run领取前19日为下载断点：重取原失败完整范围，再与当前文件合并，已提交不回滚。成功的其他独立完整范围不混入本次失败范围。

bootstrap按§10独立合同恢复。

#### 8.2.1 完整历史先取得，在同连接复用并按20日发布

历史下载首次转换/保存/审计每个unit时，同时将这些已经取得的行保留到主要连接的固定临时关系stk_factor_pro_history_source。仅当前unit网络对象/DataFrame及时释放；SQL源关系保持至本任务历史结束，不能在unit收尾丢掉后由日期规划、发布批次反复read_parquet取回。首次保存源的实际读回关系也物化一次供审计复用，不让临时view在各检查中反复解码文件。

publication_dates由控制层在历史下载前根据expected_units和已核日历一次规划，供空间估算及发布共同使用；股票和闭区间继承每个unit首次源审计，之后只从完整源关系首次聚合实际日期及行数，核其属于该已注册日期集合，不重新生成发布日期计划。正式只发布d<T，T响应行仍留作本次源事实，不覆盖日阶段。批次数ceil(D/20)，每批从已持有关系筛20日，逐日处理：本日旧Raw B首次读取一次，合并结果RAW_EXPECTED直接供候选审计、等价判断、Silver日期转换、覆盖及scope结果使用；旧Silver若需要首次读取一次供等价及缺原键判断，不在_publish_file再打开。

每个日期Raw→Silver及必要scope/缺原键结果完成后，先执行本日最后一次数据消费，再由控制层释放该日固定关系。仅bootstrap_context非空且d属于原operation批准范围时，此时利用RAW_EXPECTED计算一次覆盖、保存必要非零明细。控制层必须在收到Silver结果后、恢复publisher进入下一日期前做完这一步；不得等批末再算。普通无关联历史不读取历史日停牌或执行逐日全市场覆盖。批末释放本批关系，保留下一批还要消费的本次源关系；历史完整结束或异常/取消finally关闭时释放总源关系。任何失败的新run仍全新下载原完整失败范围，不复用此连接的临时关系或旧源证据。

历史容量采用§18.6.1的唯一公式和同一check_space闭包：分别计源Parquet、整份SQL源、当前20日回刷股票及单日工作量、所有尚需两层候选和记录。完整源行数上界按各unit闭区间自然日数（含T）计算，发布日期另按开市日d<T规划，不能混为同一个数量。沿既有内存/临时空间设置；不足在首个历史session前停止，不靠释放已取关系再重读绕过。源文件只保存一份，SQL关系不作为跨run恢复入口。

控制层把同一publication_dates和check_space交发布；其源日期核验不重新规划N或预算。连接作用域及受控spill依据[DuckDB临时表说明](https://duckdb.org/docs/current/sql/statements/create_table.html)。验收：unit/源文件首次取得与首次传输审计各一次；后续日期规划和各20日批打开历史源Parquet次数0，批次查询仍ceil(D/20)且只访问已持有关系；1/20/21/41/45日按原批次边界验，日Raw不被历史覆盖、无关股票不变。正常/失败/退出成本包含保留源关系空间和最终释放，不以小样本冒充完整范围性能。

## 9. 两个综合checks与事件

| 结果 | 合同与不能混淆的边界 |
| --- | --- |
| 输入就绪 | 股票复权因子Raw T/P完整复刻现有Raw因子必要check语义，sensor及job预检均必需；不用非空文件或Raw技术因子市场覆盖替代。 |
| Raw综合check | raw_tushare_stk_factor_pro_file_contract_check；原有字段/主键/日期和来源/候选对账；日源覆盖准入另在提升前完成。 |
| Silver综合check | DATE、主键、对应Raw范围、完整业务字段/合法值及逐行对账；本期无新增过滤或填值，无数量比例门槛。 |
| 日可读/覆盖 | 文件及必要检查通过即可用；应有集合是T日上市人民币股票减全天停牌，盘中仍应有，按代码求差。上游覆盖依据未知不宣告补齐、不清空正式数据。本期Silver不额外过滤，成功生成后与Raw主键/行数对应；日更按§21.5在发布前确认完整，Prod原有缺口仍按原导入规则独立记录。 |
| 历史完成 | 原T Raw应有代码已齐、原T Silver有效且对应当前Raw，完整名单、adj_factor数据集T/P、本轮完整范围及全部已发布事实对应；缺关键因子/覆盖未知/Silver无效不能伪装完成。producer最终成功后才可供后续轮次跳过历史；失败run的物理完成不免除重新下载。常规历史差异只诊断，自动追修还须通过§3.6的源端差异核对。 |

生命周期有效期采用list_date <= T AND (delist_date IS NULL OR T < delist_date)。当前股票代码覆盖的必需/可选划分按§21.10，全天停牌按§5.2的已核依据扣除，盘中停牌仍列必需。

sensor与job复核均使用现行`raw_tushare_adj_factor_ready_for_trade_date(instance, trade_date)`，只针对T/P读取Raw因子物化及其3项检查事实，共2分区×3项check；它不是全市场股票覆盖证明。job再对实际两份Raw文件执行字段/日期/唯一性/正值等必要业务校验并比较。不得改用`batch_raw_adj_factor_lake_readiness`然后声称只扫两份Raw：当前实现即使layer=raw仍构造Silver路径、校验Silver并进入含生命周期的聚合，隐藏读写范围和成本不符合本次边界。本需求不修改该已有helper；sensor不算全名单，job显式处理无P与旧待处理。

每天检查定义始终两个，不按股票/字段/窗口新增。日阶段两资产各一个输出/check；历史涉及D个d<T日期时最多另有2D个物化和2D个检查结果。内容未变不重复替换，事件如实标注保留当前文件并通过本轮校验，不能宣称文件内容发生变化。十个计划时点包含前日补采占用，不能预算成10次今天另加1次Q；此外还需计预检记录、下载开始/名单观察及历史事件，整晚不只两条事件。

采用`multi_asset(specs, check_specs, partitions_def)`及`AssetCheckSpec(blocking, partitions_def)`；同一步内阻断由业务显式执行。`AssetCheckResult`没有partition；历史`AssetCheckEvaluation`及`target_materialization_data`参考现行repair/资金流事件代码。相应实现后隔离验证：日物化后历史失败仍可读、检查真实绑定正确partition/run/materialization、重复输出不产生异常、观察持久化时点、历史批量取事件而非逐日深扫。静态代码核对不等于事件API运行验收。

发布及DG checks复用新产物首次审计结果和已有摘要，不能以保存事件或更新统计为由重复运行完整校验。sensor只看今天T的有界有效结果及必要输入，不全湖/全事件扫描；覆盖及历史待处理不新增状态资产，cursor不是事实源。

每次Silver只对新候选完整检查一次：DATE、261列合同、主键、分区、合法NULL/数值及与对应Raw的全字段一致。提升后直接复用唯一audit及Raw来源摘要生成物化/check，不重新DESCRIBE/count/全字段比较，也不多次hash Raw。它证明这份Silver来自当前Raw，不证明源端当天全市场已齐；覆盖另按既有代码集合计算一次。

日代码在发布前按§21.5确认；两层发布后将同一覆盖结果绑定实际物化/check并保存，供历史和后续读取复用。不再在Silver发布后首次发现日源缺股。

### 9.1 来源输入到本地列的确定转换

编码落点：源值检查及分批转换放 `defs/io/stk_factor_pro_candidates.py`；源合同字段名只引用 `tushare_download/contracts/stk_factor_pro.py`；两层 schema 由既定 `defs/run_contracts/asset_column_schemas.py` 映射，不抄写259个字段名。普通 HTTP 入口固定传内部来源 `http`，bootstrap 固定传 `prod_postgres`，业务不选择 transport。

```python
def stk_factor_pro_raw_trade_date(value: object, *, source: Literal["http", "prod_postgres"]) -> str: ...
def stk_factor_pro_double(value: object, *, source: Literal["http", "prod_postgres"]) -> float | None: ...
def stk_factor_pro_http_rows(
    result: UnitResult, contract_fields: tuple[str, ...],
) -> Iterator[tuple[object, ...]]: ...
def build_stk_factor_pro_raw_batch(
    *, rows: Iterable[Sequence[object]], source_fields: tuple[str, ...],
    source: Literal["http", "prod_postgres"], expected_dates: tuple[date, ...],
) -> pandas.DataFrame: ...
def write_stk_factor_pro_raw_fragment(
    *, connection: DuckDBPyConnection, frame: pandas.DataFrame,
    candidate_path: Path, expected_row_count: int,
    on_verified_fragment: Callable[..., None],
) -> StkFactorProFragment: ...
def build_stk_factor_pro_silver_candidate(
    connection: DuckDBPyConnection, *, verified_raw_relation: str, raw_audit: StkFactorProFileAudit,
    target_trade_date: date, candidate_path: Path, run_root: Path, known_records: dict,
) -> StkFactorProFileAudit: ...
```

HTTP实际fields必须与完整源契约字段集合一致、无重名，每行值数与实际fields一致；依实际fields建立位置映射，再显式投影为契约的固定顺序。仅顺序不同不丢行、不错位；缺列、多列或重复列明确拒绝，不借zip截断或补None兜底。bootstrap的SELECT本身按白名单排序，游标description须与该完整投影顺序一致。

HTTP适配必须接真实`UnitResult`：先确认termination全部scope完成、statistics.row_count与len(records)一致，核`observed_field_sets`（包括合法空结果的字段集）；逐个SourceRecord用它自己的fields映射自己的values。同unit跨页列顺序不同也不能用第一页位置套所有行。`stk_factor_pro_http_rows`按契约顺序惰性产生值tuple给公共批转换函数，不先复制整个unit为第二份行列表。比较日期时，源YYYYMMDD按本节严格解析为date，unit的ISO point/time_range按§6解析为date，再作日期比较，不能直接比较两种文本。日BY_POINT逐行日期须等于result.unit.point对应日期；历史BY_OBJECT_RANGE逐行ts_code须精确等于result.unit.object_code且日期落在result.unit.time_range闭区间，T诊断行也遵守对象限制。请求000001.SZ却返回600000.SH时直接报源业务数据不符，不静默过滤、不写入别股；全市场日请求不套单一股票限制。unit的对象/point/time_range还须与本任务规划值一致，不能仅凭返回unit自证范围。Prod则用cursor.description的列名核顺序，直接把本批tuple rows交同一转换函数；公共函数不直接接受SourceRecord，也不猜其结构。

`StkFactorProFragment`是frozen dataclass，固定`relative_path:str,file_sha256:str,content_sha256:str,schema_content_digest:str,row_count:int,observed_schema:tuple[tuple[str,str],...],min_trade_date:date|None,max_trade_date:date|None,first_code:str|None,last_code:str|None`。路径、摘要和计数按§5.4校验；零行时日期/首尾代码全None，非零时日期/首尾代码全有且有序。它只描述当前已保存片段，不放业务行；历史HTTP一个完整unit对应一个文件，bootstrap各5000批对应各自片段。日HTTP不调用片段写函数、不产生Fragment或源文件引用。

| 字段/来源 | 接受值 | 明确拒绝/禁止 |
| --- | --- | --- |
| `ts_code` 两来源 | `type(value) is str`，精确匹配本数据集股票代码合同，当前A股为六位数字加 `.SH/.SZ/.BJ`；保留原字符串 | NULL、空白、前后空白、整数、任意对象转str；不自动trim/补前缀/改代码 |
| `trade_date` HTTP | `type(value) is str`，ASCII八位数字；先核正则 `[0-9]{8}`，再按年月日构造 `date`，最后 `%Y%m%d` 回写必须与原文一致；该日期须处于本unit约定日期范围 | 空、NULL、`2026-10-21`、整数20261021、`20260230`、多余空白、日期越界；不使用宽松自动推断、不静默转NULL |
| `trade_date` Prod | `type(value) is datetime.date`（不接受子类datetime），源 schema 核为DATE后，显式 `value.strftime('%Y%m%d')`；检查本批准窗口/本次选中日期 | timestamp/date字符串/NULL；源 schema 变化须先停下核合同，不临时兼容 |
| 259数值 HTTP | `None`、精确 `int`（不含bool）、精确 `Decimal`；符合有限DOUBLE范围后显式一次转 `float` | bool、str、float（当前HTTP合同不交付float）、NaN/Infinity的Decimal、转换溢出；不把字符串数字、空字符串当合法数 |
| 259数值 Prod | `None`、精确 `float`；以当前Float(53)真实合同为依据 | Decimal、str、bool、NaN/Infinity；遇见不同真实源类型先报源合同不符，不隐式容纳 |

数值标量规则：先检测来源精确类型，None直接保留NULL；Decimal先 `is_finite()`，其他可接受数值使用 `float(value)`，捕获 `OverflowError/ValueError`，再 `math.isfinite(result)`。负数、0、极小但DOUBLE仍可表示的有限数、合法NULL均通过，不按价格正数或指标合理区间过滤。若有限非零输入转换成0，报无法无损表示该非零数，不能静默消失；一般十进制->IEEE754 DOUBLE的舍入属于已声明存储映射，不逐位要求Decimal精确相等。正负0按数值等价比较；不新增容差。

HTTP unit 已完整交付后，只处理当前一个unit并创建其列数组；bootstrap则仅处理当前5000行批次。5000不是下载器参数，不为HTTP新增一个同值配置，也不能自行把分页当完整unit。数值明确 `pandas.array(..., dtype="Float64")`，缺失使用 `pd.NA`；不先让DataFrame推断把None与源NaN混为一谈。`stk_factor_pro_double`是标量语义和小样本测试依据；实际批内按列构建，禁止构造全历史Python行集合。批内必要类型/范围校验不执行任何逐行数据库写入。

注册当前批DataFrame到本任务既有DuckDB连接，SQL以显式`CAST(... AS VARCHAR/DOUBLE)`建立当前批临时关系，并校验转换前后NULL数量/行数一致。

- 日HTTP：只在内存建立固定临时U，保留当前完整UnitResult至日两层完成。直接对`B-K+U`执行一次COPY生成唯一Raw发布候选；不对U另做一次COPY、不调用write_stk_factor_pro_raw_fragment。Raw候选首次审计的expected始终来自本次内存U与本次B，不读取日源文件。Silver从同连接中已由唯一audit证明等于正式Raw的RAW_EXPECTED生成，不重新打开正式Raw。最后解除注册、DROP当前U、释放result/列数组/frame，finally同样清理。DuckDB如按既有资源策略发生临时spill，只是本次计算临时文件，不是日下载缓存，下一run不能读取或复用。
- 历史HTTP及bootstrap：按既定当前unit或5000行批次执行`COPY (SELECT <261白名单列> FROM current_batch ORDER BY trade_date, ts_code) TO <受控片段> (FORMAT PARQUET)`，写后读回schema、行数、主键/日期和当前批完整业务值；最后unregister、清临时关系、释放rows/列数组/frame，才取下一批。

历史已核SQL行先并入总源，bootstrap已核行先交当前日/跨日批关系；只清注册/转换关系，控制层按最后使用者释放保留的SQL关系。仅当前unit/批次来源对象和必要转换对象共存；不使用executemany，不额外构造无用SDK DataFrame，不新装依赖。

### 9.2 两项综合check的共同校验结构与SQL

固定内部输出（定义在 `defs/run_contracts/stk_factor_pro.py`）：

```python
@dataclass(frozen=True, slots=True)
class StkFactorProComparison:
    expected_rows: int
    actual_rows: int
    missing_key_count: int
    unexpected_key_count: int
    changed_row_count: int
    changed_field_counts: tuple[tuple[str, int], ...]  # 固定字段顺序，零项可保留

@dataclass(frozen=True, slots=True)
class StkFactorProFileAudit:
    trade_date: date
    layer: Literal["raw", "silver"]
    path: Path
    file_sha256: str  # 本次实际文件读回得到的字节摘要；不是另一份持久化记录
    observed_schema: tuple[tuple[str, str], ...]
    row_count: int
    invalid_key_count: int
    duplicate_key_count: int
    invalid_date_count: int
    invalid_numeric_count: int
    comparison: StkFactorProComparison
    passed: bool
    diagnostics_path: Path | None  # 本run受控路径，仅错误样本/摘要
```

file_sha256在新产物首次完整审计时计算一次；业务审计期间只比较文件元信息稳定性，不在前后各读一遍全部字节。passed来自本次必需检查结果，不接受业务传入true。schema、主键、日期、合法NULL及有限值规则保持，但已核内部expected不再重复require；原子提升后的正式audit继承这份结果和摘要。

为每日期构造有明确来源的两份关系：

- 源片段保存对账：仅历史HTTP与bootstrap，expected为本批按上述规则转换后的261列，actual为读回片段；两者统一Raw表示。日HTTP无片段及该对账分支。
- Raw合并对账：B为本次构建时已验证的旧Raw；日U为本次完整内存UnitResult转换的临时关系，历史U为当前run完整保存并读回的历史源。两者均须当前日期完整、主键唯一。expected关系为 `SELECT B.<261列> FROM B WHERE NOT EXISTS (SELECT 1 FROM U WHERE U.ts_code=B.ts_code AND U.trade_date=B.trade_date) UNION ALL SELECT U.<261列> FROM U`；actual为首次读回的Raw候选，已发布check直接复用该audit。日check的expected不读取下载中间文件，源行数与保存条数的核对在内存U计数及B-K+U最终行数中完成；不能用正式Raw与自身比较。
- Silver对账：expected直接从本日期核验后的Raw显式投影，`CAST(strptime(trade_date, '%Y%m%d') AS DATE)`，actual为首次读回的Silver候选，已发布check直接复用该audit；不存在旧Silver独立合并分支。

所有输入类型/日期验证先于转换 SQL；不使用TRY_CAST把非法值悄悄变NULL。SQL中 relation/列名只从静态白名单生成；文件路径由paths.py生成并验证后传入，不接受配置SQL片段。核心比较如下，`mismatch`是对259数值列逐列生成的 `e.<field> IS DISTINCT FROM a.<field>` 的OR，代码与日期通过主键等值JOIN：

```sql
WITH joined AS (
  SELECT e.ts_code AS expected_code, a.ts_code AS actual_code,
         e.trade_date AS expected_date, a.trade_date AS actual_date,
         (<mismatch>) AS value_diff
  FROM expected e FULL OUTER JOIN actual a
    ON e.ts_code = a.ts_code AND e.trade_date = a.trade_date
)
SELECT
  count(*) FILTER (WHERE expected_code IS NOT NULL AND actual_code IS NULL) AS missing,
  count(*) FILTER (WHERE expected_code IS NULL AND actual_code IS NOT NULL) AS unexpected,
  count(*) FILTER (WHERE expected_code IS NOT NULL AND actual_code IS NOT NULL AND value_diff) AS changed
FROM joined;
```

逐列变化计数使用同一次有明确唯一主键的JOIN聚合259个 `count(*) FILTER (WHERE e.field IS DISTINCT FROM a.field)`，仅统计两边均有键的行。NULL对NULL相等，NULL对数值不同；负数正常，0.1的HTTP Decimal与DB float均先得到同一个DOUBLE表示再比较。禁止只比行数、只比主键、只比sha、任意epsilon或用普通 `<>` 漏掉NULL差异。主键双向差异和全部259数值差异共同覆盖全部261业务字段。

历史U缺原键不进入合并对账missing_key_count，因为B−K+U按要求保留旧行；另算原scope旧键未被U刷新的差集，只有非零才保存unrefreshed-keys.parquet和引用。0仅计数/None，无文件。非零阻止整范围完成，不新增check、不删旧行；最终行数仍核B_rows−K+U_rows。

候选完成前校验和正式两项check复用上述内部结果，发布后确认实际目标对应已校验候选，再输出同一结果；不能为了复用而跳过目标已变的核对。metadata放汇总、样本位置/摘要、对应Raw身份；完整错误样本固定最多20行，错误总数必须全量计入本次有界日期关系，不截前20行就算通过。历史20日按日期批量构造SQL，不全历史回读。

## 10. 配置、规模与性能门禁

不新增下载器频率/账号额度/线程/锁配置。组件现有2GiB单unit工作空间、64MiB响应、5/30/45秒超时、最多4次同页尝试及1/2/4秒退避沿用；工作空间不是进程总内存承诺，不重测用户拍板值。业务调度控制请求频率。

本数据集运行合同在现有`defs/run_contracts/stk_factor_pro.py`单处维护，随代码加载。sensor装饰器、历史planner、bootstrap和验收代码均import相应常量，禁止在入口、脚本、测试之外另写一套业务默认。没有新增env、配置表、页面开关、任意run参数或运行中热更；修改常量须同步方案/LLD和消费者测试，代码重新加载后对新执行生效，既有run记录仍保留当时取值。

| 参数名/规则 | 已确认默认与来源/持久化 | 作用范围、消费者、生效与运维可见性 | 必须测试 |
| --- | --- | --- | --- |
| 首轮/后续/截止 | 管理员：只在开市执行日，19:00、固定30分钟、D+1 00:00，最后23:30，Asia/Shanghai；run_contracts单处代码规则。 | sensor选时点、run身份及job开跑复核；D/T/slot写run_config及metadata，不支持任意运行覆盖。 | 18:59/19:00/23:30/00:00、延迟与活动跨时点；使用模拟时钟。 |
| 管理日期 | 自动T=D，历史缺口由管理员明确指定T。 | sensor、人工日期入口及运行身份按§21统一。 | 缺码或多码不触发，指定旧日不挡今天。 |
| `STK_FACTOR_PRO_UPDATE_SENSOR_INTERVAL_SECONDS` | `60`秒；run_contracts代码常量。 | 更新sensor的`minimum_interval_seconds`；代码加载生效，定义可见并记录于评估摘要。只限评估频度，不改半小时slot、重启去重或午夜。 | 定义取统一常量；模拟多次tick不能一分钟下载一次或补发旧slot。 |
| `STK_FACTOR_PRO_PARTITION_SENSOR_INTERVAL_SECONDS` | `600`秒；同上。 | 注册sensor的`minimum_interval_seconds`；默认STOPPED，不等数据就绪；定义/评估摘要可见。 | 间隔与更新sensor分开，只注册真实今天/Q、不删除旧键、不造未来。 |
| `STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS` | `20`个交易日；同上，管理员确认。 | 自动历史和手动repair共用§8升序切批；run metadata记录取值、当前批日期/序号、完成文件与耗时。完整源后才合并，逐文件生效。 | 1/20/21/41日、节假日、无行日、末批和批间失败；不改变unit/历史范围，不新增分区。 |
| 对象历史下载窗口 | 每股可信最早已有日期至原T，一次完整unit；依已批准可信范围和run_contracts的规划规则，不默认按年切。 | history planner和下载函数，范围/digest保存到原完整plan/ranges；下载器扇开代码，分页按源契约。 | 未截短历史；20日合并不切请求；无法证明最早日期时停止，并说明缺少的依据。 |
| `STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS` | `5000`行；run_contracts代码常量。 | §10.1 planner/服务端cursor的itersize和fetchmany共用；bootstrap metadata记录月份、批数、保存行数及实际取值，单批落盘释放。 | 0/4999/5000/5001行、同一天跨批、月边界、日未完整重取；不得普通cursor/fetchall/累计整月。 |
| DuckDB资源 | **引用现有**`DEFAULT_DUCKDB_CONNECTION_SETTINGS`：16GB、4线程、临时目录`/Volumes/datasource/.goldenshare_duckdb_tmp`、512GB临时空间上限；事实源为`defs/duckdb_connection.py`，非本数据集新默认。 | asset/op通过既有`DuckDBResource.connect()`；离线bootstrap通过同一`connect_configured_duckdb()`；同任务同时只保留1个主要计算连接，传给本批函数复用并finally关闭。metadata从实际settings记录，不写死第二套值；不改其他调用者。4线程是SQL计算，不是4个下载对象。 | 替身证明同批不嵌套创建主要连接；隔离读取实际settings与原设置相符，关闭后释放；临时目录与run候选路径不能混用。 |
| 下载器容量/批内存估算 | 继续组件既有2GiB unit、64MiB响应；单日结果150～220MiB、处理峰值约0.5～1GiB，按约1GiB处理余量规划；bootstrap128MiB工作空间估算/256MiB余量分别见下文。 | 组件限制只对Tushare；估算不是新硬限、无新配置，也不是整个进程或DuckDB总内存承诺。512GB是spill上限而非预占，实际需核剩余空间。 | 不将数据库5000行float估算套到HTTP Decimal；无隐式截断/缩字段；不为估算另拉数据压测。 |
| bootstrap人工入口七字段 | §2.4及§10.7的本job配置，普通today/manual_date按§21.4，三项bootstrap字段默认None、人工必填；单处run_contracts schema。 | run_config持久化、按用途解析/parent/root和授权核验、RunIdentity、开始/阶段观察、记录读取及repair继承；仅该run生效，无env/配置表/热更新，不修改通用RunRequest。 | 自动不生成新用途、错字段/摘要/日期拒绝；无parent首次及gap归0后原生重执行均有正反例。 |
| 取消状态读取间隔 | 内部常量`STK_FACTOR_PRO_CANCEL_STATUS_POLL_SECONDS=1`秒，在run_contracts单处维护；无env/run_config覆盖。 | §6同线程控制闭包，普通组件检查按monotonic节流，业务保存/replace等边界强制刷新；加载后生效，进度摘要记录实际状态读取次数。它不是下载频率或线程调度参数，不改组件。 | 模拟时钟及假instance证明密集检查每秒至多1次读取、首次必读、强制边界必读、取消保持、读取失败停止。 |
| 输入gate | T/P股票复权因子就绪及源端代码齐备。 | sensor按§21先本地后源查询，job正式日源/候选通过后才提升。 | 缺码、多码或依据未知不提交，探测后源变化时日发布为0。 |
| 性能验收目标 | 同run_contracts单处`STK_FACTOR_PRO_SENSOR_TARGET_SECONDS=5`、`STK_FACTOR_PRO_DAY_UPDATE_TARGET_SECONDS=120`、`STK_FACTOR_PRO_HISTORY_REFERENCE_TARGET_SECONDS=1200`；管理员接受的初值。 | 分别用于sensor一次评估、无历史正常日更，以及类似17股原完整历史的成本外推比较；测试/验收报告记录样本、推算和目标，**不是运行超时、kill或任务请求预算**，不写入下载器限制。 | 模拟负载/隔离小批计时与独立报告；超目标先定位原因，不删除数据或强杀，也不据外推冒充全范围实测。 |

`DuckDBResource.connect()`直接调用`connect_configured_duckdb()`，该函数在contextmanager中校验并关闭连接。在本数据集函数间传递连接，避免helper自行再开连接令16GB看似单份实为多份；传感器只在必要有界核验期间短暂持有连接。资源设置以原模块为准，本数据集记录实际使用值。

| 场景 | 可确定的成本模型 | 验证项目（未实测） |
| --- | --- | --- |
| 每轮预检/名单 | sensor直接读候选T/P和已有DG结果；job读两因子文件重新生成本run完整名单，保留旧未完意图，不复用失败run下载数据。 | §6.2首次发现1条入口，日/历史直接引用各至多精确读1条，额外run身份查询按实际未缓存不同run数R计；同任务不重复取得同一事件/run，不递归追查历史任务。Raw因子两日期三项check查询；Raw/生命周期/停牌身份未变复用原覆盖，改变才重算原T必要代码列，不逐tick重做261字段/全部历史对账。 |
| 单轮日源 | 有界样本5568行×261字段，暂定10000页大小约1次正常请求，恰满须继续。 | 完整HTTP字节/耗时；当前唯一UnitResult、列转换与DuckDB临时U短暂共存的内存；唯一Raw候选及后续Silver候选读写、T旧文件与两层必要checks/覆盖成本。无日源文件、manifest、source-complete或重复Raw源落盘成本。 |
| 晚间自动与人工补日 | 自动只处理当天，正常cursor下最多10个固定时点；无自动前日补采或积压。分页、清cursor重探测及人工指定日期另计。 | 整晚源/合并/事件/候选留存峰值；不是下载组件请求总上限。 |
| 复权历史 | C代码、W窗口、D历史日期，完整原范围正常请求`sum(floor(H_i/10000)+1)`；同页最多另加3倍尝试；原T Raw不齐时0历史请求，整范围成功且输入未变才不重复。 | 完整历史源保留T但只发布d<T；20日/最多40文件局部合并，当前正式B与新源U字段/主键对账、缺旧键记录、空间与事件批量读取。 |
| 失败后重新执行 | 无论失败在下载、候选、Raw/Silver发布或事件收尾，重新执行均计入整阶段新下载请求；完整旧源不省网络，Q不重获自动机会。 | 当前正式文件读回/合并/校验、全部原失败范围重新下载、当前run候选与intent、最终读回和保留失败证据的空间；不计旧候选续接收益。 |
| 手动repair | 先核原T Raw完整，再核原T Silver有效且对应当前Raw；不通过0技术因子请求/0提升，不代补T。两项通过后完整原失败范围全部新下载，只d<T合并/事件。 | 原run有界授权定位、4字段/两摘要校验、原T覆盖及Silver已有凭据复用。新增Silver核验最多2次PG查询及T一份Silver身份检查，同run身份未变复用；不加261字段或全历史审计。计入T/P因子、完整新下载/20日批次/最终读回，无T资格窄查询，纳入人工维护边界。 |
| bootstrap人工首次/重新执行 | 同日更单T日源及必要历史请求；首次原导入小记录最多一遍、当前T缺口/依据有界校验，重执行至多三条精确身份run及有界观察；无Prod请求。 | 当日统计在两层/check后即保存；历史每20日批次更新已完成日期和summary，普通异常也收尾已完成事实；首次装载旧账本一次，此后summary读取/覆盖SQL/重新求和均0，未变不重写。旧新代码覆盖共用纯函数，必要主键集合运算及身份读回计入，不重算指标。失败后仍计T及原失败历史全部网络重取。 |
| bootstrap | 获准Prod范围显式261字段，按自然月及5000行服务端流式批量；单月约`ceil(月行数/5000)`次取批、非每日期新连；逐文件候选/发布，事件另授权。 | 当前准确范围/源截止与月计数、来源维护窗口、只读事务/超时、峰值磁盘，以及未完成日期重取、完整日源复用、逐文件继续和最后对账成本。 |

容量不足、范围超批准或候选不完整停止并说明，不减少字段/股票或缩短历史造完成。禁止无界导出、全历史长事务、Python逐行大合并、每日期新连远程库的未经测量默认。参数与验收目标已确认，尚无对应来源/性能运行验收结论；不因写了目标就宣称已经达标，也不将尚未实现的完整链路运行验收错置为现在必须通过。

**单日内存估算及编码约束：**

| 项目 | 估算方法与范围 |
| --- | --- |
| 规模依据 | 既有有界来源样本5,568行；按5,600～6,000行、261列规划，包含259个数值列。不请求新的来源样本、不跑内存压测。 |
| 净数值 | `N×259×8`字节，约11～12MiB，仅表示转换成DOUBLE后的数值载荷，不是Python结果或Parquet文件体积。 |
| 下载结果 | 当前`source_response.parse_http()`以`int/Decimal`解析，`SourceRecord`保存fields和值tuple。按64位CPython常见Decimal约104字节、tuple引用8字节，259列全部非空且按Decimal计算约144～154MiB；再计行、值元组、代码/日期及分配余量，完整日UnitResult按150～220MiB估算。fields元组按页/合同共用，不逐行复制字段名；int/NULL比例与数值长度会改变实际量。 |
| 阶段峰值 | 下载时计响应字节/JSON解析及`UnitMemory`统计对象，转换合并时计UnitResult、列数组/frame、临时U、当天旧Raw和候选计算缓冲；按各阶段较高值估计约0.5～1GiB，先按约1GiB处理余量规划。不把这些本不同时存在的对象全部长期保留。 |
| 既有边界 | 2GiB是组件单unit工作空间，64MiB是响应限制；二者沿用，不预占内存、不改为整个进程上限。解析预留计数仍服从现有算法，估算不能保证任意64MiB响应均可通过。DuckDB16GB限制不代表预占16GB，也不限制全部Python内存。 |

本估算依据当前`download_models.SourceRecord/UnitResult`、`source_response.parse_http()`、`unit_memory.UnitMemory`和`unit_output.UnitOutput.finish_unit()`，以及§9.1的本次列转换和临时表流程；不是bootstrap5000行float批次的估算，也不是多股票全历史同时常驻的预算。没有新增内存配置或自动扩容，实际容量错误按既定停止规则处理。

取消状态读取另计入PG预算：设同一阶段经历t秒并实际执行C次普通取消检查，普通状态读取不超过`min(C, floor(t)+1)`次，另加F次业务边界的强制读取；无检查点的等待期间不产生后台查询。记录实际调用次数供小样本核对，不把259列或行数乘进PG请求量；这些只读本run，不扫描历史事件。

编码必须让生命周期可核对：会话正常关闭并核summary前不创建Raw候选；仅持有本次一个结果，不先复制完整行列表；转换注册只在构造临时U期间保留，完成后解除注册并释放列/frame，保留独立临时U及原结果供日校验；本日必要数据计算和小结果交接完成后，DROP临时U/B/expected关系并清除本次结果引用，异常/取消finally也执行相同清理。不得把结果放入全局、下一轮或失败记录；发布候选不是可复用下载缓存。内存释放表示不再持有对象引用，不要求RSS立即回落，也不为此调用强制GC或增加后台清理线程。§11用小夹具验证释放路径、旧数据不被复用和多轮不累计引用，不靠大范围跑数证明估算。

bootstrap的5,000行估算依据是当前`RawStkFactorPro`和261字段契约：代码按9字节ASCII、Prod DATE净值4字节、259个Float(53)按8字节，全非空净值`5000×(9+4+259×8)=10,425,000`字节，约9.94MiB；不是PG整行或Parquet文件大小。常见文本数值平均8～12字节时，计每列4字节长度及每行协议头约15～20MiB，数值按24字节估算约35MiB；格式、NULL及驱动改变会影响实际量，不把它当绝对协议上限。64位CPython基本tuple/float/date/code对象约40MiB，另有libpq缓冲和列式转换；本批工作空间先按128MiB估算、256MiB留余量，不新增硬限制，也不声称进程峰值。仅取261列，不读raw_payload等辅助列；实现采用服务端named cursor，不得以普通cursor.fetchmany冒充流式。上一批保存并释放后才领下一批，不能在Python累计整月。Tushare的64MiB响应/2GiB unit限制不用于Prod数据库导出，DuckDB的16GB也不是Python/libpq总内存上限。正式导出前复用已有schema证据核准实际字段类型；不为大小估算另拉5,000行压测。

### 10.1 bootstrap自然月规划、5000行流式和恢复

`defs/bootstrap/stk_factor_pro_history.py`的正式入口先按§4.2执行只读活动任务检查，再核原operation的批准及完整日期/发布记录。由这些记录机械区分“还需来源读取或业务文件恢复”和“全部业务文件已完成、仅本地统计”，不增加模式参数或独立入口；两种分支的维护及来源边界见§10.2。首次正式文件提升前再检查活动任务。由调用方传入既有instance，不在入口初始化instance、创建run或停启sensor。月导出/恢复函数只由该已检查入口调用，不能将单月函数另作绕过维护步骤的正式入口。

初始化业务范围固定为Prod来源表全部现有业务数据。2026-11-05 09:27（北京时间）确认的业务日期为`2017-01-03～2026-11-04`，包含两端。日期和历史规模核验见方案§3.2。正式开始时在约定来源维护窗口内取得实际首尾和按日计数，保存在既有批准记录，并以该次记录确定完整执行范围。来源维护窗口、每月上界/超时、资源开销及正式执行仍需执行前核准。

planner将实际最早至最晚日期完整拆为相邻自然月窗口，记录闭开边界`[month_start, next_month_start)`，首末月仅裁到源实际范围；不漏月、不加股票过滤。显式投影261业务字段并按`trade_date, ts_code`稳定排序，不select *或读取raw_payload等辅助列。通过既有`ProdPostgresResource.connect_readonly_transaction()`每月建立独立只读事务、`connection.cursor(name=受控唯一名称)`及统一`itersize/fetchmany`批量；不能一条完整历史长事务，也不能每天重复建远程连接。Prod原有缺股/缺日只登记现状，不阻止其余合法已有行导入，不为解释旧数量差异而另拉全部源历史；导出漏行、字段/日期错误、来源变化或目标冲突仍须停止。

准备批准记录时，对上述每个相邻自然月使用只读事务、语句超时及绑定边界，执行以下计数SQL，仅返回每日计数：

```sql
SELECT trade_date, COUNT(*) AS row_count
FROM raw_tushare.stk_factor_pro
WHERE trade_date >= %s AND trade_date < %s
GROUP BY trade_date
ORDER BY trade_date
```

在源实际首尾间的自然日序列补明确0行日期，汇总所有月得到源总行数；这份计数只用于来源传输核对，不计算市场应有股票，也不要求先完成Prod覆盖预审。缺月、边界不符或任一月查询失败就不能形成完整计数依据，不用估计值补齐。不要求另跑全表`COUNT(*)`；导出前的当前计数复核也限定当前月及其selected_dates。

每次取至多5000行，按已核对源类型进行列式转换，保存为该run该月staging下连续编号的Parquet片段，读回核对源/保存条数和必要字段后释放rows及转换对象，才取下一批；日边界可以跨多个5000行批次，不能当成多份正式日文件或只保留最后一批。禁止fetchall、客户端普通cursor冒充服务端流式、Python逐行大表写入及把整月累积到列表。查询按`trade_date, ts_code`有序，看到下一日期或游标EOF才确认前一日期已收齐，保存其完整日源清单后，由同一主要DuckDB连接生成该日Raw/Silver候选并逐文件发布；不要求整月源完成才发布已完整日期，也不在每5000行时覆盖正式日文件。本入口仅支持首次无目标、与本次来源结果内容等价，或同operation沿原intent恢复；已有不同内容目标一律停止，不执行没有对应批准结构的合并/覆盖，交管理员另行处理。

自然月仅是远程查询窗口，不新增月级完整门槛或恢复平台。游标中断时，当日未收齐的源片段不发布；已完整保存/发布的日期按既有日源完整事实和逐文件intent/checkpoint核验后保留或复用，完整日源存在但发布失败不强迫重读数据库。获准重执行时对本月尚未完成的日期做有界查询，整日重新读取，不按OFFSET、5000行批号或最后一行继续；没有明确完整事实的日期不能猜已经完成。需要来源读取/业务文件恢复时发现源范围或截止修订即停止，不原地改批准或把旧源假作新依据完整；仅本地统计沿已批准原范围报告，不探测Prod是否又增加数据。正式事件补录仍独立授权，物理阶段不借机运行正式Dagster。

### 10.2 bootstrap批准输入的封闭结构

bootstrap继续是单独获准的直接文件写入，不接入日常job或下载器。唯一来源固定 `ProdPostgresResource` + `raw_tushare.stk_factor_pro`；261字段来自唯一源合同。以下是执行前审核并保存的业务输入，不是env、页面配置或任意SQL入口；普通调用不得自行生成一份“批准”记录。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapApproval:
    record_version: int                 # 固定1
    operation_id: str                   # 受控安全标识，非路径
    start_trade_date: date              # 维护窗口内源表实际MIN，非可剪裁输入
    end_trade_date: date                # 同次源表实际MAX，闭区间
    source_cutoff_trade_date: date      # 必须等于end，不能截掉已有日期
    source_maintenance_start: datetime  # 有Asia/Shanghai偏移
    source_maintenance_end: datetime
    source_identity_digest: str         # 非秘密来源定位+表+schema白名单摘要
    contract_content_digest: str
    approved_daily_counts_ref: str      # 受控staging相对路径
    approved_daily_counts_digest: str
    approved_source_evidence_ref: str   # 源全量实际边界/计数合计/维护约定/固定样本证据
    approved_source_evidence_digest: str
    month_limits: tuple[StkFactorProBootstrapMonthLimit, ...]
    source_statement_timeout_ms: int    # 正整数，正式数值执行前批准

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapMonthLimit:
    month_start: date                   # 按源全量实际首尾裁切后闭边界
    month_end_exclusive: date
    row_upper_bound: int                # >=此月批准日计数之和，非5000
```

JSON读取拒绝未知字段、缺字段、重复键、非标准日期/无时区时间、bool冒充int、非正timeout、负上界、月份重叠/缺月、首末月未按源实际范围裁切、cutoff不等于end、引用越界/符号链接、摘要不符。维护窗口的先后关系及有时区类型总要核验，是否仍在窗口内则按下文实际工作分支判断。既有`approved_source_evidence`必须记录同次全表实际MIN/MAX和按日计数合计；校验start/end与该证据一致，需来源读取时执行预检，再核当前源边界及按日计数，来源变化就停止，不静默缩小范围或自动改批准记录。零行月可上界0；5000/20日/DuckDB参数不放此输入供覆盖。`approved_daily_counts`是Parquet固定 `trade_date DATE,row_count BIGINT`，源实际首尾间每个日历日期一行，0明确记录；范围外不得混入，计数不得负数/NULL/重复，其合计必须与来源证据一致。已确认休市而源非空的日历冲突与字段/类型错误不得静默跳过；日历缺失或未知不冒充已确认休市，按§10.5保留未知并忠实导入合法已有行。原有缺日单独报告，不阻止其余合法已有行导入。

来源身份摘要在首次批准及实际来源读取时从resource解析出的非秘密主机/端口/数据库定位、固定schema/table、获准源列名/源类型和合同生成，不包含口令、完整DSN或token。实际数据库表的schema核验属于来源读取分支的执行预检，不能跨工程import Prod ORM充当真实schema证明。仅本地统计时从已验摘要的批准来源证据解析原身份，不创建resource连接、不访问远程schema/计数/样本，也不要求Prod连接凭据继续存在。维护约定和固定有界样本核验不等于逐行证明整个来源从未变化；来源读取及业务文件恢复必须明确依赖已获准维护窗口，发现违反维护约定/样本或计数变化即停止。

同一入口的分支顺序固定为：读回并验证不可变approval及批准计数/来源证据→按批准自然日期逐个核完整日源及两层完成事实→确定实际剩余工作→执行以下条件。不允许调用者传一个布尔值绕过条件，也不因现存summary自称完成而跳过文件核验。

| 实际工作 | 来源条件与允许动作 |
| --- | --- |
| 任一日期源未完整，或任一业务文件尚需生成/提升/恢复 | 必须仍在原Prod维护窗口，来源读取前核当前resource/实际schema/范围及本月计数；完整日源恢复业务文件也须原维护约定仍适用。过期即停，另行取得明确执行批准，不能自动延长原approval或改源摘要。 |
| 批准范围的业务文件已完成并按§10.4读回，仅补缺失/失效覆盖统计或汇总 | 原operation、approval、原导入证据/合同照常核验；尚未补数的当前文件核原完成记录，已有§10.5.6合法补数的当前文件核补数发布/check及当前SHA，不要求仍等于原导入SHA。不要求Prod维护窗口仍有效，不连接Prod、不下载、不重建或提升业务文件。继续满足DG维护及唯一写入要求，缺口/未知只影响统计及§10.6门槛。 |
| 本地统计过程中发现业务文件缺失、无合法补数凭据的改写或完成事实无效 | 停止相应日期的有效结论并报告；不自动切换来源读取/业务恢复，不把当前文件登记成原导入。合法补数凭据对应当前两层时走§10.5.6当前结果分支；凭据不全或文件不匹配时列当前不可核验，不回退Prod覆盖，交管理员处理。 |

所有批准记录、来源片段、日期完成记录和候选位于 `/Volumes/datasource/data_lake_staging/stk_factor_pro/bootstrap/operation_id=<id>/`下，由paths.py生成；正式路径仍使用既定Raw/Silver路径。调用者不得传Lake根、staging根、表名、字段清单、SQL、过滤片段或任意文件路径。读回引用按规范相对路径限定本operation或明确引用的旧operation，拒绝`..`、绝对路径与符号链接穿越。

```python
def validate_stk_factor_pro_bootstrap_approval(
    *, approval: StkFactorProBootstrapApproval, now: datetime,
    source_identity: StkFactorProSourceIdentity,
) -> tuple[StkFactorProBootstrapMonthLimit, ...]: ...
def require_stk_factor_pro_bootstrap_source_window(
    *, approval: StkFactorProBootstrapApproval, now: datetime,
) -> None: ...
```

月导出及完整日回调的唯一精确接口见§10.3.1，包含入口首次source_inputs、preflight_context、known_records以及首次日源SHA/关系交接，不在此重复声明。

`StkFactorProSourceIdentity`为frozen dataclass：全部字段按`host:str,port:int,database:str,schema:str,table:str,columns:tuple[tuple[str,str,bool],...],contract_content_digest:str`声明，不在有默认字段之后声明必填字段；schema/table分别校验为固定raw_tushare/stk_factor_pro，不是调用参数默认。columns按261字段白名单顺序保存真实源列名、数据库源类型及nullable，来源摘要使用§10.3的规范投影，禁止含密码/DSN。端口1～65535，身份文本不得空，schema/table不能由输入任意替换。本节相互引用的类型在同一run_contracts模块定义并使用未来注解，不能为声明先后问题引入跨工程导入。

validate只做完整结构、引用、摘要及source_identity与批准证据的一致性核验；不会访问网络，也不以当前时间拒绝仅本地统计。require_source_window固定要求`source_maintenance_start <= now < source_maintenance_end`，由已分类的主入口在实际来源预检前、每月查询前、每次业务文件提升前调用；窗口过期不领取下一日期，不开始新提升，已完成文件保留。该内部职责拆分不是允许运营选择跳过校验。

`approved_source_evidence`固定保存`record_version=1,operation_id,source_identity:StkFactorProSourceIdentity,source_identity_digest,contract_content_digest,min_trade_date,max_trade_date,total_rows,approved_daily_counts_ref,approved_daily_counts_digest,source_maintenance_start,source_maintenance_end,maintenance_statement:str,verified_at,source_sample_ref:str,source_sample_file_sha256`。maintenance_statement须非空并记录批准的来源静止条件；样本ref仅引用原有获准有界核验结果，不增加每次统计的网络抽样。source_sample记录固定`record_version=1,operation_id,source_identity_digest,contract_content_digest,sample_date:date,sample_codes:tuple[str,...],row_limit:int,request_columns:tuple[str,...],returned_rows:int,observed_source_schema:tuple[tuple[str,str,bool],...],passed:bool,verified_at:datetime`；参数必须与已批准样本一致、row_limit精确正整数、returned_rows不超上限、request_columns严格261字段白名单且passed为实际核对结果。不保存任意SQL、DSN或口令。来源证据、批准计数及approval各自文件字节SHA核引用，source_identity_digest按§10.3规范投影计算；相互记录的范围/计数/窗口/合同必须一致。不可变approval.json的`approval_digest`统一为保存文件实际字节SHA-256，后续引用绝不另算“去掉时间后的批准摘要”。

`StkFactorProBootstrapMonthResult`为frozen dataclass：`month:StkFactorProBootstrapMonthLimit,attempt_id:str,source_rows:int,fragments:tuple[StkFactorProFragment,...],complete_dates:tuple[date,...],pending_dates:tuple[date,...],file_audits:tuple[StkFactorProFileAudit,...]`。fragments按保存顺序、日期集合去重升序。该结果不是恢复事实源，完整日期和文件仍须有固定路径记录读回。逐日覆盖统计另按§10.5保存，不在此结果内增加全历史业务行。

`StkFactorProBootstrapDateResult`为frozen dataclass，固定`trade_date:date,source_complete_digest:str,raw_audit:StkFactorProFileAudit|None,silver_audit:StkFactorProFileAudit|None,coverage:StkFactorProBootstrapDateCoverage|None`。有源行时两份audit全有且passed，coverage全有；源0且无旧文件时两份audit为None，开市/日历未知仍有coverage，已知休市0行才可coverage=None。返回值不含业务行。export校验返回日期、摘要和上述交叉条件，再把两份audit汇入MonthResult；不能因回调仅正常return就假定发布成功。

bootstrap重执行沿用原批准`operation_id`及该根的不可变`approval.json`，不增加“自动找旧operation”功能。开始时按批准日期清单逐个计算固定日完成记录位置；有效完整日直接读回复用，缺完整事实的日期整日重读。每次实际导出内部生成一个32位小写hex的attempt_id，源片段放在该operation的`source/month=<YYYY-MM>/attempt_id=<id>/fragment-<连续编号>.parquet`，避免重读时覆盖已被其他完整日期引用的跨日片段；attempt_id不进入业务输入摘要，也不是下载断点。新的operation_id代表另一份明确批准的执行，不扫描其他operation复用。批准/来源依据变更时停止，不能原地改approval继续。

### 10.3 bootstrap SQL、上限检测与分批源文件

每月一个 `connect_readonly_transaction()`；不改resource，不跨月持有事务、不上表锁、不新增隔离级别。入口首次取得的`source_inputs=(counts,evidence,sample)`及`preflight_context={"fixed_done":False,"checked_windows":{}}`是本任务局部依赖，显式交给恢复预检和月导出；不新增配置、类型或跨run缓存。checked_windows按month_start保存本月已经核实的`date→count`，恢复分支先核pending与recover的联合日期后，导出分支的pending子集直接复用；只有尚未核实的日期才执行一次相应日期窗口计数。实际需要Prod时，schema、全源首尾及批准固定样本本任务首次一次；无剩余来源或业务恢复工作不连接Prod。每个新事务仍先用普通控制cursor执行：

```python
control.execute("SELECT set_config('statement_timeout', %s, true)",
                (str(approval.source_statement_timeout_ms),))
```

这是事务内 `SET LOCAL statement_timeout`的可绑定参数实现，事务退出现有resource会rollback并关闭连接。它约束每次数据库语句执行，不等同整个bootstrap/网络传输的总超时；现有10秒connect_timeout仍只约束建连。超时后立即关闭named cursor、退出只读事务，不把当前日标完整、不自动重发查询。

使用 `psycopg2.sql.SQL` + 固定 `sql.Identifier('raw_tushare', 'stk_factor_pro')` 和白名单列Identifier生成：

```sql
SELECT <261业务字段>
FROM raw_tushare.stk_factor_pro
WHERE trade_date >= %s AND trade_date < %s
  AND trade_date = ANY(%s::date[])
ORDER BY trade_date, ts_code
LIMIT %s
```

绑定值为本月裁切边界、已批准且尚需重新读取的日期数组、`R+1`。R取该月已批准 `row_upper_bound`；selected_dates由planner从该月完整日期集合中，仅扣除同operation已有有效完整源记录且复核通过的日期后生成，不能由调用者任意筛选。首次全无完成记录时必须覆盖全部源日期，不能漏掉某天或某只股票。日期数组全在本月和源实际范围内、升序去重；空则无需开连接。SQL永远不加OFFSET或股票过滤；表名/列名不取用户字符串，也不拼接日期。普通控制cursor只做SET/schema/有界计数/固定样本核验；261字段明细只通过 `connection.cursor(name=受控唯一名, scrollable=False, withhold=False)` 的单条SELECT读取。`itersize=STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS=5000`，每次 `fetchmany(min(5000, R+1-seen))`，不得fetchall。

预检批准的日计数和当前按日计数一致，selected_dates计数之和<=R；导出最终又按每日期实际行数核批准计数。R+1是运行中的截断防护，不是正常数据分页大小。**先检测是否收到了第R+1行，再把该行当“后一天已经开始”的依据。**触及R+1立即停止，不保存额外行，也不把当前未关闭日期记完整；此前已经完整发布的日期保留。恰好R行且真正EOF、日计数/主键/日期等均核对通过时才允许完成最后日期，不能把LIMIT造成的返回结束误当来源本来就没有更多行。

每批先核完整261字段、类型/日期范围和排序。跨批维持上一批最后 `(trade_date, ts_code)`，键必须严格升序；同日跨批重复/逆序即停，不能去重。当前批转换成Raw表示后存 `source/month=<YYYY-MM>/attempt_id=<id>/fragment-<至少六位从000001起的连续编号>.parquet`，原子保存并按§9首次实际读回为StkFactorProFragment。读回使用本连接唯一命名的TEMP TABLE，不能用指向Parquet的VIEW代替物化；完成唯一传输对账、完整审计及摘要后，原子移动继承同一份事实，不再hash最终路径。writer通过`on_verified_fragment(path=最终路径, fragment=已核描述, source_relation=实际读回表名)`交接实际表；callback成功后表由调用方持有，writer只释放写前批关系、frame注册及Python转换对象。callback未成功时writer负责清理实际读回表，原异常优先。片段描述及首次文件身份直接登记，不在remember_saved再次SHA。当前日数据从该表依源日期顺序加入唯一BOOTSTRAP_DAY_SOURCE，跨批不重新打开片段；本批各日期已提取后释放本批实际表，仅保留当前日及仍供后续日期使用的跨日批表。片段first_code/last_code对应源排序中第一行/最后一行代码，首尾完整键为(min_trade_date,first_code)/(max_trade_date,last_code)，跨日时不能额外要求first_code<=last_code。Python侧只保留片段的小型描述和本日累计行数，不保留本日业务行列表。

以下完整记录类型统一放`defs/run_contracts/stk_factor_pro.py`，读写/验证复用该模块的封闭结构校验及原子JSON办法。不是另一套通用状态平台；路径只由既有`defs/paths.py`扩展受控函数生成，实际读取/发布仍在`defs/bootstrap/stk_factor_pro_history.py`。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapFragmentRef:
    fragment_no: int                    # 精确int>=1；attempt内连续
    attempt_id: str                     # 32位小写hex
    fragment: StkFactorProFragment      # §9完整结构，文件在本operation

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapSourceComplete:
    record_version: int                 # 固定1
    operation_id: str
    approval_digest: str                # approval.json字节SHA
    source_identity_digest: str
    contract_content_digest: str
    source_cutoff_trade_date: date
    month_start: date
    month_end_exclusive: date
    attempt_id: str
    query_scope_digest: str
    selected_dates: tuple[date, ...]
    row_upper_bound: int
    trade_date: date
    approved_rows: int
    actual_rows: int
    fragments: tuple[StkFactorProBootstrapFragmentRef, ...]
    fragments_manifest_digest: str
    schema_content_digest: str           # Raw schema
    date_content_sha256: str             # 筛本日后261列业务内容SHA
    date_content_version: int            # 固定1，即§8.1算法
    close_reason: Literal["next_date", "eof"]
    next_trade_date: date | None
    source_empty: bool
    source_complete_digest: str
    completed_at: datetime               # §5.4 aware Instant
```

同一片段可含多个日期。已保存批内出现新日期时，只关闭其前一个日期；批末日期暂不关闭，等下一批新日期或真正EOF。完整日期记录的固定路径为`source/dates/<YYYY-MM-DD>/source-complete.json`。按trade_date筛选已审fragments集合后，本日累计行数必须等于approved_rows；字段/类型/数值及保存对账继承片段首次审计，唯一性继承源端跨批严格键序，不在完整日再次扫描全部列审计；从同一payload计算记录摘要并原子保存后，直接把对象/摘要向后续发布传出。fragments按fragment_no升序，无重复且全属同attempt、本月及本operation；每个片段的min/max必须覆盖本日，且实际筛本日行数大于0，禁止仅凭min/max混入无本日行的片段。非零日期fragments非空，approved_rows=actual_rows>0、source_empty=False；next_date须满足next_trade_date>trade_date且在selected_dates，eof则next_trade_date=None。记录只允许固定本日过滤，不增加字符串SQL字段。

源0日期要求approved_rows=actual_rows=0、fragments=空、source_empty=True、close_reason=eof、next_trade_date=None，date_content_sha256为SHA256空串；只有本次selected_dates明确包含该日期、正常EOF、源计数复核为0且未触R+1时才能写。EOF还须核seen等于selected_dates批准计数之和，逐日实际计数（未出现日期补0）与批准计数完全一致；以最多31项计数字典处理，不生成全月业务行集合。正计数日完全未返回必须报导出漏行，不能在处理0源日期时跳过。已知休市且源0只形成这份完整空源事实，不制造业务文件或假事件；开市/日历未知源0仍依§10.5形成可解释覆盖结果。异常退出的空白、半日或LIMIT截断绝不生成空源事实。

本节的文件字节摘要与字段内容摘要分工固定：

| 摘要 | 统一算法及精确投影 |
| --- | --- |
| 所有`file_sha256`、approval_digest、JSON引用摘要 | 对最终保存的文件字节计算SHA-256。JSON采用UTF-8、ensure_ascii=False、sort_keys=True、separators=(",", ":")、allow_nan=False，末尾一个换行；日期/时间先按§5.4转换。不是对反序列化对象再次序列化后核字节。 |
| source_identity_digest / kind=stk_factor_pro.bootstrap_source_identity | 同§5.4.2的content_digest外层；value固定host、port、database、schema、table、columns及contract_content_digest；columns保持白名单顺序，每项name/type/nullable，不自动把不同数据库源类型当同一类型。 |
| query_scope_digest / kind=stk_factor_pro.bootstrap_query | value固定approval_digest、source_identity_digest、contract_content_digest、source_cutoff_trade_date、month_start、month_end_exclusive、selected_dates、row_upper_bound；日期ISO，selected_dates升序去重。不得含attempt/时间或随意减少日期。 |
| fragments_manifest_digest / kind=stk_factor_pro.bootstrap_fragments | value为fragment_no升序数组；每项含fragment_no、attempt_id及fragment的§9全部固定字段，observed_schema按列顺序。这里是文件追溯，路径/attempt必须参与，不能套业务范围摘要的“忽略路径”规则。 |
| source_complete_digest / kind=stk_factor_pro.bootstrap_source_complete | value为SourceComplete除source_complete_digest和completed_at外全部字段，fragments以fragments_manifest_digest代替；其他计数、范围、close_reason/next_trade_date均保留。日期ISO；内容中不直接出现float。 |
| fragment.content_sha256、date_content_sha256、候选/正式业务内容SHA | 严格采用§8.1版本1：固定261字段顺序、当前层日期表示、按(ts_code,trade_date)升序序列化行并计算SHA。片段算整个片段，完整日算筛出的本日；空集为空串SHA。两者不因都叫content而互相比。 |

以上kind统一调用现有`contract_registry.content_digest`，不能另造json/hash helper改变算法。SourceComplete的schema_content_digest必须等于既定Raw schema；读取记录时核固定路径、完整结构、operation/批准/来源/合同及记录摘要。完整源实际用于候选重建或业务文件恢复时，才进一步核引用片段字节、261列及本日行数/内容。两层业务文件已完成、仅补统计时，依据原完整源记录、两层完成事实和当前正式文件身份，不重复读取源片段261列；缺失或不匹配仍须停止，不能只因文件存在就相信。首次原子写入后不原地改写已有效日源记录；同operation发现相同路径已有不同内容即停止，不能覆盖后悄悄改变被引用事实。

#### 10.3.1 完整日同步回调与资源收尾

on_complete_date由正式主入口在当前调用线程创建并传入，内部闭包持有已经核验的approval、当月coverage inputs及同一个主要DuckDB连接，不再创建线程、进程、队列、连接或业务配置。它是bootstrap内部的逐日处理接口，与下载组件的进度通知回调不同；异常不能吞掉继续导出。

固定调用顺序为：当前批片段首次保存/核验→判定完整日期→在同连接建立一次BOOTSTRAP_DAY_SOURCE继承片段已核字段/数值，仅完成日计数/引用及合同日摘要→原子保存SourceComplete小记录并直接交接对象/摘要→同步on_complete_date(source_complete)直接消费现成关系→Raw/Silver新候选各首次审计/原子发布→本日覆盖统计→返回DateResult后释放本日关系。保存记录及发布回调不能再次load_complete_source重建和重审。本日关系按当前单日持有，不累计整月；异常关闭游标和关系，半日不交付。

逐日处理函数固定为以下内部接口，闭包只完成依赖绑定，不再实现第二份发布流程；所有根路径是主入口已核验的内部依赖，不是运营输入。

```python
def process_stk_factor_pro_bootstrap_complete_date(
    connection: DuckDBPyConnection, *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    source_complete: StkFactorProBootstrapSourceComplete,
    source_record_sha256: str, source_relation: str,
    inputs: StkFactorProBootstrapCoverageInputs,
    basis_inputs: dict, known_records: dict, date_results: dict,
    before_publish: Callable[[], None] | None = None,
    check_space: Callable[..., BootstrapSpaceEstimate],
    progress: _BootstrapProgress | None = None,
) -> StkFactorProBootstrapDateResult: ...

def publish_bootstrap_date(
    connection: DuckDBPyConnection, *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    source_complete: StkFactorProBootstrapSourceComplete,
    source_record_sha256: str, source_relation: str,
    before_publish: Callable[[], None],
    check_space: Callable[..., BootstrapSpaceEstimate],
    known_records: dict, date_results: dict,
) -> tuple[StkFactorProFileAudit | None, StkFactorProFileAudit | None]: ...

def read_stk_factor_pro_bootstrap_source_complete(
    connection: DuckDBPyConnection, *, staging_root: Path,
    approval: StkFactorProBootstrapApproval, trade_date: date,
    known_records: dict,
) -> StkFactorProBootstrapSourceComplete | None: ...

def write_stk_factor_pro_bootstrap_source_complete(
    connection: DuckDBPyConnection, *, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    record: StkFactorProBootstrapSourceComplete,
    approved_date_rows: int, source_relation: str, known_records: dict,
    check_space: Callable[..., BootstrapSpaceEstimate],
    verification: BootstrapFragmentVerification | None = None,
) -> tuple[StkFactorProBootstrapSourceComplete, str]: ...

def preflight_stk_factor_pro_bootstrap_source(
    *, prod_postgres, connection: DuckDBPyConnection, staging_root: Path,
    approval: StkFactorProBootstrapApproval, month: StkFactorProBootstrapMonthLimit,
    selected_dates: tuple[date, ...], source_inputs: tuple,
    preflight_context: dict, known_records: dict,
) -> None: ...

def export_stk_factor_pro_bootstrap_month(
    *, prod_postgres, connection: DuckDBPyConnection, staging_root: Path,
    approval: StkFactorProBootstrapApproval, month: StkFactorProBootstrapMonthLimit,
    selected_dates: tuple[date, ...], source_inputs: tuple,
    preflight_context: dict, on_complete_date: Callable[..., StkFactorProBootstrapDateResult],
    check_space: Callable[..., BootstrapSpaceEstimate],
    verification: BootstrapFragmentVerification, known_records: dict,
    progress: _BootstrapProgress | None = None,
) -> StkFactorProBootstrapMonthResult: ...

def load_complete_source(
    connection: DuckDBPyConnection, *, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    record: StkFactorProBootstrapSourceComplete,
    verification: BootstrapFragmentVerification, known_records: dict,
) -> str: ...
```

source_record_sha256专指SourceComplete JSON首次payload字节SHA，由writer第二返回值提供、在known_records对应路径登记；SourceComplete.source_complete_digest以及DateResult/DateCoverage同名字段仍为§10.3已定义的业务内容摘要，从原对象直接取，两者不得互换。

source读函数仅固定路径不存在时返回None，坏记录仍报错；写函数只核既有本日审计结果与记录归属/日期/行数/摘要，原子保存后直接返回对象及payload摘要，删除内部load_complete_source。正常process/publication直接消费同步保留的BOOTSTRAP_DAY_SOURCE及结果，不重复加载/全验。bootstrap新执行恢复确需源重建时才load_complete_source一次，首次确认必要片段身份后得到唯一日关系，继承有效源审计，不在日层重审字段/数值；本次后续直接交接。已完成两层只补统计不读261列源；已有合法补数日期不沿旧Prod源重建。连接/同步回调/只读事务及关闭规则不变。

主入口按已有逐日期分类决定是否调用process：两层均完成且当前文件身份有效的日期，直接将date_results中已有SourceComplete、Raw/Silver audit及合法当前发布引用交给现有覆盖步骤，不调用process、不创建BOOTSTRAP_DAY_SOURCE，也不调用load_complete_source。仅Raw已完成、Silver未完成时，首次读取已核正式Raw到BOOTSTRAP_DAY_SOURCE，复用原Raw完成事实和首次文件身份，交process/publication生成缺少的Silver；不为满足source_relation参数再读取原Prod片段。只有确需从完整源重建Raw时，才由恢复主入口调用load_complete_source一次并交出现成关系。已有合法补数日期仍只允许更新当前统计，不进入原Prod源恢复分支。

source_inputs三项分别是入口首次已经核实的`dict[date,int]`、SourceEvidence、SourceSample，原样传入，不在preflight/export重新调用_approved_inputs或把日期再逐项read_source_complete。selected_dates直接来自主入口本次classified；source只核该冻结tuple的日期顺序、所属月份及批准计数，不重做分类。preflight_context只在固定schema/首尾/样本全部通过后置fixed_done=True；日期窗口也仅在对应当前计数全部通过后登记checked_windows，同月已核子集不再发查询。事务内timeout每个新事务都执行，与这两个复用事实分开。

正常导出的完整日调用固定为`on_complete_date(record, source_record_sha256=payload_sha, source_relation=BOOTSTRAP_DAY_SOURCE)`。建立该关系的导出complete作用域持有它到同步回调返回或抛错，再finally释放一次；process/publication不得提前清除或重新创建调用方的日源关系。恢复driver由load_complete_source取得同名关系后，持有到同一回调结束并finally释放一次。process负责清理自己建立的B/expected/旧Silver/审计关系，不能与外层重复清理日源。回调失败时，已写完整SourceComplete和正式文件保留，当前日SQL关系正常清理；下一批fetch不再发生。

真正EOF且计数通过后，先关闭仍持有的最后非零日，完成其同步回调并释放DAY，再按日期处理批准0行日的空DAY；月结果的complete_dates仍升序。0源须等EOF成立，不要求其内部回调排在最后非零日之前，不为这个未规定的顺序增加表重命名或复制。

覆盖准备发现按合同可判定的输入无效时，按§10.5.2、§17.8.4记录对应依据未知并正常返回，继续合法导入；不能把这一分支抛成统计异常。除此之外，真实回调/转换/写入/统计异常立即停止领取下一日期和fetch，不自动重试数据库、不把本地写失败当源错误重发。try/finally先关闭named cursor及控制cursor，再由既有connect_readonly_transaction执行rollback和close；本地主要DuckDB连接由唯一主入口finally关闭。清理阶段的异常不得覆盖最初业务异常，应作为附加错误记录；若本来正常而关闭失败，整体按失败结束。已经落盘的完整日源和已发布文件保留，统计失败不回滚业务文件；下一次按§10.2实际剩余工作分类处理。中断在半日时不回调半日，中断在Raw/Silver之间只保留已完成层。JSON从已核对象序列化/计算摘要一次，临时文件、fsync、同文件系统replace、父目录fsync后直接返回；新明细Parquet保留首次传输读回。两者均不写半个最终记录。

例：片段1含A日5000行；片段2含A日500行+B日4500行；两片段保存并读回后，A完整记录同时引用片段1、2，仅筛A日得到5500行。B须等后续片段见到C或真实EOF才能关闭，不能只因片段2已存便发布B。完整A可立即进入本日候选/Raw/Silver逐文件发布，不要求B或整月完整。批准0行日期只保存明确空源结论，不制造正式空文件/假物化，也不借此删除原有文件。

### 10.4 bootstrap中断、目标冲突与最小验收

完整日源用于候选重建或业务文件恢复时，必须核原批准输入/来源身份/合同及源截止、维护约定仍适用、引用片段全部存在且指纹内容匹配、日行数和完整业务字段读回通过。随后从其Raw源重建候选并沿既有逐文件意图恢复；事件写成功与否不是完整源成立条件。仅本地统计按§10.2不要求Prod窗口继续有效，核不可变原导入事实及当前文件对应的原导入或合法补数依据；无依据或不匹配则不产生当前有效结论，不为每日期重新读取源片段或复做261列对账。已合法补数的日期只准更新当前统计，不再进入旧Prod源恢复/提升分支。同operation重执行不得改写已被完整日期引用的旧attempt片段，原完整日记录不可变；当前attempt只写新片段和此前未完成日期的完成记录。新的operation不得扫描或悄悄接用旧operation。

当前日未关闭、查询超限、超时、schema/类型/计数变化或游标断开：不发布该未完整日期；获准再执行时在对应批准月内按尚需日期数组整日重读。不能按最后code、OFFSET、fragment编号接读，不因已读了某股而跳过；已完整日源即使尚未发布可直接核验复用。已经提升Raw且其完成记录与当前文件身份有效、Silver尚未完成时，按照§8.0从正式Raw首次取得的同一关系生成Silver，不重开原来源片段。两层已完成仅补统计时，不进入process或完整源重建；读取和调用顺序按§10.3.1。

首次bootstrap没有旧文件直接生成；已有目标仅可确认内容等价而不覆盖。已有不同目标一律停止，交管理员单独获准的修复步骤；本bootstrap入口不支持覆盖不同目标，不能给执行参数增加任意overwrite开关。恢复时自身已提升、意图尚未记完成的情况照既有目标/候选指纹读回补事实；旧完整源不得覆盖后来合法修改的正式文件。

bootstrap恢复沿同一获准operation的逐文件记录，独立于§8的Tushare失败重下规则。以下两类记录为frozen dataclass，读写位置固定`publication/<YYYY-MM-DD>/<raw|silver>/intent.json`及`complete.json`，候选位置固定`candidates/<YYYY-MM-DD>/<raw|silver>/part-000.parquet`；相对路径均在原operation内，正式目标由日期/层按paths复算，不接受记录任意指定目标。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapPublicationIntent:
    record_version: int                 # 固定1
    operation_id: str
    approval_digest: str
    trade_date: date
    layer: Literal["raw", "silver"]
    source_complete_digest: str
    raw_file_sha256: str | None         # Silver绑定生成它的最终Raw；Raw为None
    mode: Literal["reuse", "replace"]
    prior_file_sha256: str | None
    candidate: StkFactorProFragment
    expected_file_sha256: str
    intent_digest: str
    created_at: datetime

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapPublicationComplete:
    record_version: int                 # 固定1
    operation_id: str
    approval_digest: str
    trade_date: date
    layer: Literal["raw", "silver"]
    source_complete_digest: str
    intent_relative_path: str
    intent_file_sha256: str
    intent_digest: str
    actual_file_sha256: str
    actual_rows: int
    schema_content_digest: str
    content_sha256: str
    content_version: int                # 固定1
    audit: StkFactorProFileAudit
    verified_at: datetime
```

audit持久化时保存首次候选完整审计的全部字段，正式path按日期/层复算；observed_schema、行数、comparison及schema/content摘要均继承唯一audit，不从正式文件再审产生。complete要求actual_file_sha256等于intent.expected、actual_rows等于audit.row_count、audit.passed=True。Silver来源Raw引用继承当前日已核事实，不通过反复hash确认。

intent_digest统一为kind=stk_factor_pro.bootstrap_publication_intent的content_digest，value固定operation_id、approval_digest、trade_date、layer、source_complete_digest、raw_file_sha256、mode、prior_file_sha256、candidate的全部§9字段、expected_file_sha256；时间及intent_digest自身不参与。候选内容/字节摘要仍为§10.3统一算法，不用intent摘要冒充候选SHA。reuse只在正式文件已通过完整业务对账且与本次源生成候选内容等价时使用，prior非空且expected=prior；replace则expected=candidate.file_sha256=candidate_audit.file_sha256；其中candidate_audit必须是原完整检查的不可变结果，不能在描述候选时把变化后的文件SHA重新认作已校验SHA。reuse的candidate仍绑定原候选检查SHA，expected/prior则绑定已通过完整检查的正式目标SHA，二者可以因Parquet表示不同而不同。首次创建intent时，replace必须prior=None且目标不存在；已有不同目标一律停止，批准结构不支持覆盖开关或口头批准分支。恢复只接受原intent的prior/expected状态，不能补写新prior授权覆盖。

固定持久化顺序：当前本日已核源→新候选首次完整audit及固定摘要→保存小型候选描述/intent（直接引用audit，不重算）→终端bootstrap首次维护核验及轻量身份/空间检查→原子提升→继承原audit生成正式事实→原子保存complete小记录并直接返回对象/摘要。提升后不读业务schema/行数/全字段，不重新计算摘要；任何实际I/O失败按原失败处理。

读写方法同样在既定bootstrap模块，接口如下；写函数只消费本任务已经核验的文件事实及记录，保存后直接登记对象与首次摘要，不调用reader自证。read只在新执行首次需要旧事实时读取，返回None仅表示固定文件确实不存在；坏记录、有complete却无intent仍抛错。它们均不连接Prod，不因一个不存在记录自动写入另一个记录。

```python
def read_stk_factor_pro_bootstrap_publication(
    *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    trade_date: date, layer: Literal["raw", "silver"],
    known_records: dict,
) -> tuple[StkFactorProBootstrapPublicationIntent | None,
           StkFactorProBootstrapPublicationComplete | None]: ...

def write_stk_factor_pro_bootstrap_publication_intent(
    *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    record: StkFactorProBootstrapPublicationIntent,
    known_records: dict,
    check_space: Callable[..., BootstrapSpaceEstimate],
) -> StkFactorProBootstrapPublicationIntent: ...

def write_stk_factor_pro_bootstrap_publication_complete(
    *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    record: StkFactorProBootstrapPublicationComplete,
    known_records: dict, date_results: dict,
    check_space: Callable[..., BootstrapSpaceEstimate],
) -> StkFactorProBootstrapPublicationComplete: ...
```

bootstrap新执行恢复先读取批准及原intent/complete小记录。对确需恢复的现存候选或目标仅首次确认其摘要及所需audit一次，随后复用；目标expected分支可无已被移走的候选，按已有完整审计结果补complete，缺本次必要事实时对该实际产物首次确认，不重复重建/全验同一expected。目标prior且候选合法才继续原子提升；两者不符停止，不改prior/expected。两层已完成只补统计不重新读取源；Raw已完成从其已核结果生成新的Silver候选。此规则仅bootstrap，不授权Tushare失败run复用旧源。

预算继续复用已确认5000行估算（约9.94MiB净字段、128MiB工作空间/256MiB余量），不把估算当进程硬限制；一批源对象、显式列数组和写入缓冲的短暂共存纳入估算。每月事先给出批准日计数之和、R、261字段行宽估算、预期5000批次、日/两层文件数量、单语句超时和剩余空间。按§17.8.2的纯内部预算、设备归并及强制检查时点执行；明细SELECT前必须确认能容纳尚需保留的源、当前日期两层候选和DuckDB临时开销，中断续跑及最终统计也在预算内，不只算最终文件。保留完整日源所需空间随批准范围变化，不自动删除旧源来腾空间。

测试落点：`test_stk_factor_pro_candidates.py`、`test_stk_factor_pro_checks.py`、`test_stk_factor_pro_bootstrap.py`。均临时文件/隔离DuckDB及假Prod游标，无真实批量读库。

| 必须证明的边界 | 独立小样本与断言 |
| --- | --- |
| 类型/日期 | HTTP Decimal('0.1')、int、None、负指标正常；Prod float/date正常；bool、字符串数字、datetime、YYYY-MM-DD源日期、20260230、NaN、Inf、overflow及非零下溢各自明确拒绝，不能变NULL继续 |
| 精确对账 | 0.1转换后通过；NULL/NULL通过，NULL/0及任一末尾业务字段变化失败；缺键与多键同数量抵消仍失败；重复键失败；不因合法负数或少股票失败 |
| Prod全量范围 | 早于2020的日期、退市股票均规划/导入；人为缩窄源实际首尾、漏月或首次漏源日期均拒绝；cutoff不能截掉已有日期。源原有缺日/缺股只记录，不误报为导出漏行，不触发Tushare历史补采；实际导出行数少于来源计数仍失败。 |
| Silver来源 | Raw5000/Silver4800、本轮U4800，期望Silver5000；历史一天两股中只刷新一股，另一股261字段不变；不等待其他历史日期完成 |
| 5000与完整日 | 5000+500跨批同日，第二片段另含下一日；本日完整记录引用全部片段并按日筛选；未关闭日期绝不发布；0行不造文件 |
| R+1 | R-1、R、R+1行；R行真实EOF才正常，R+1触限先停止，不能用超限行关闭当前日；批准计数不符即停；此前完整日期保留 |
| SQL安全/只读 | 字段/表固定；日期/数组/limit/timeout值绑定；named cursor、5000、关闭/rollback；反例抓fetchall、OFFSET、普通cursor明细、系统字段/任意路径/未知输入参数 |
| 失败恢复 | 完整日源后退出可0次远程明细重读；半日片段须整日重读；Raw已提升Silver未成从当前合法Raw生成；仍需来源/业务文件恢复而窗口过期、片段损坏/正式目标后改均停，不旧源覆盖；全部文件已完成仅本地统计不因Prod窗口过期拒绝，也不得发schema/计数/样本请求 |
| 完整日回调及持久记录 | 同批非零日期按早到晚回调；批准0源日按§10.3.1等真实EOF并先关闭最后非零日后处理，月结果仍升序。半日不回调；完整日记录含全部片段，字节SHA/内容SHA混用会失败；同operation已完整记录不得改写。回调在Raw后、Silver后、统计写入分别抛错，均不继续fetch，游标关闭/事务rollback/连接关闭，保留已成文件并可按相应事实重入；清理异常不能掩盖原始失败 |
| 性能与真实边界 | 复用批准小响应/既有schema证据作最小来源交接；不为5000行估算去读5000行或全历史；批次1/5000/跨日边界用小夹具替换批量常量测试；记录正常/恢复/最后对账的读写和SQL数量 |

### 10.5 在bootstrap中利用本地数据统计缺口

本节是已确认的实施方式：不再把Prod全历史股票覆盖审计作为bootstrap前置；在忠实导入过程中，用已经落地的数据和DG本地依据计算缺口。§10.1～10.4的来源边界、按月按日源计数、261字段/主键对账、R+1、5000行、来源维护、目标冲突和恢复规则继续有效。必要源计数证明有没有导出漏行，不计算市场应有股票；不能以取消覆盖预审为由删除传输校验，也不能再在Prod联表扫描全部技术因子、生命周期和停牌来预先计算缺口。仅上线前初始化补数完成后，按§10.5.6更新同一operation的当前覆盖结果和汇总；原Prod源完成、原导入完成记录保持不变，不另建修复后审计入口。

#### 10.5.1 任务内一次准备、一次计算及结果交接

使用既定bootstrap/IO/readiness模块与§2.5主入口局部变量。原批准、摘要、日计数、来源证据/样本、原SourceComplete/发布事实和当前日期result在本任务首次需要时一次读取/解析，后续显式传对象和摘要。月窗口只控制业务处理规模，不让prepare/evaluate/write/update/summarize各自读取同样的输入。

本日已取得raw_audit、silver_audit及RAW_EXPECTED/键关系后，由控制层调用既有calculate_stk_factor_pro_coverage一次并共用代码集合core，保留完整StkFactorProCoverageCounts、missing/extra关系、非零明细引用及样本。统计不接DG事件编号、CurrentPublication、原Prod计数或用途；原导入传输检查和补数授权由各自入口提前完成。RawCoverage、BootstrapDateCoverage只是同一计算的不同字段包装；同一代码/日期/依据不得再执行第二次身份映射、集合SQL或从正式Raw读代码。必要上游采用§10.5.2/§5.2同一规则，含既定生命周期、北交所开市边界、全天停牌及身份语义。

职责及内部接口按下表迁移全部调用方，不保留可缺参数后回源计算的兼容分支：

| 函数 | 接收本任务已经取得的值 | 允许动作 |
| --- | --- | --- |
| prepare_stk_factor_pro_bootstrap_coverage_month | 已核approval/digest、已加载全局依据、该月尚未取得的停牌/日历事实 | 仅首次取得该月新增事实并返回；全局关系及相同日期不能重复读。 |
| prepare_stk_factor_pro_bootstrap_coverage_date | 当前trade_date、月输入及已加载关系、两层audit | 仅提取本日当前事实，输出与单日准备相同的prepared，不收原来源/DG对象/旧最终记录，不选择业务或执行SQL。合法无文件由入口按§10.5.7直接提供已确认空事实。 |
| compute_stk_factor_pro_bootstrap_coverage_date | 当前prepared、已有Raw关系、首次已得input_digest、同任务known_records及诊断归属 | 委托共用算法一次，保存必要非零明细；approval仅供诊断路径归属，不交集合算法。不读正式Raw补参数、不重算input_digest、不等待DG编号。 |
| evaluate_stk_factor_pro_bootstrap_coverage_date | prepared、唯一calculated、approval_digest/已得input_digest、原SourceComplete、明确传入的DG引用及旧result | 在所属入口事实已满足后纯构造最终DateCoverage，只在此一次核DG引用与已得audits的对应；不选择用途、不读文件/PG、不执行SQL、不另存明细。 |
| write_stk_factor_pro_bootstrap_coverage_date | 已构造result、旧result及摘要、既有路径/check_space | 版本未变直接返回；新版本只序列化/持久化一次并返回对象及摘要，更新唯一日期账本。没有_verify_result或二次明细/文件读取。 |
| update_stk_factor_pro_bootstrap_after_publication | 已构造最终result及旧result/摘要、已有日期条目和写入边界 | 只调用现有保存步骤，成功后交接本日结果；不再接两层audit、prepared或publication重复核对，不调用prepare/evaluate、不重读source/result。 |
| summarize_stk_factor_pro_bootstrap_coverage | 本任务日期账本、已维护合计/日期集合/记录摘要、旧summary及摘要、已核approval及写入边界 | 只从已有值形成并保存必要的新summary；没有文件/PG读取、覆盖SQL、全范围重新求和。 |

上述接口仅描述各自职责的内部显式参数，不是新增运营输入。生产两类结果只在相同本日最终Raw代码、相同覆盖依据下共用；不可用时本次只生成一次未知结果，不能一个wrapper猜0另一个又重新审。没有bootstrap关联的普通日更不建立bootstrap账本。

全流程顺序为§2.5及§18.2.1。各层物理替换和完成记录分别立即登记，不等待process正常返回；新覆盖结果先作为本日已计算结果保留，只有result原子保存成功才登记当前持久结果及摘要。主入口据本次已有事实更新imported/current及贡献；变更后旧结果已不适用时即退出有效覆盖合计，未持久新结果不能填入成功汇总。原import/source事实不变；等价且原结果仍适用时保留，不因任意统计异常一律作废。异常收尾不回盘，原错误继续抛出。

按§19.11修正后的内部签名如下；本轮源码与直接消费者已同步，后续asset/op沿这些接口装配。初始化准备、诊断和最终记录收尾留bootstrap_coverage.py，共用集合算法留readiness，控制层仍在stk_factor_pro_history.py；不新增业务入口或持久格式：

```python
def prepare_stk_factor_pro_bootstrap_coverage_month(
    connection, *, lake_root, staging_root, approval, month,
    basis_inputs: dict, known_records: dict,
) -> StkFactorProBootstrapCoverageInputs: ...
def release_stk_factor_pro_bootstrap_coverage_month(connection, *, basis_inputs: dict) -> None: ...
def release_stk_factor_pro_bootstrap_coverage_inputs(connection, *, basis_inputs: dict) -> None: ...
def read_stk_factor_pro_bootstrap_coverage_date(
    connection, *, staging_root, approval, approval_digest: str, source_complete,
    trade_date: date, known_records: dict,
) -> StkFactorProBootstrapDateCoverage | None: ...
def prepare_stk_factor_pro_bootstrap_coverage_date(
    *, trade_date: date, inputs, basis_inputs: dict,
    raw_audit: StkFactorProFileAudit,
    silver_audit: StkFactorProFileAudit,
) -> dict: ...
def compute_stk_factor_pro_bootstrap_coverage_date(
    connection, *, lake_root, staging_root, approval, prepared: dict,
    raw_relation: str | None, diagnostic_run: RunIdentity | None,
    input_digest: str, check_space, known_records: dict,
) -> dict: ...
def require_stk_factor_pro_bootstrap_coverage_identities(
    *, lake_root, prepared: dict, known_records: dict,
) -> None: ...
def evaluate_stk_factor_pro_bootstrap_coverage_date(
    *, prepared: Mapping[str, object], calculated: dict,
    approval_digest: str, input_digest: str,
    source_complete: StkFactorProBootstrapSourceComplete,
    current_publication: StkFactorProBootstrapCurrentPublication | None,
    previous_result: StkFactorProBootstrapDateCoverage | None,
) -> StkFactorProBootstrapDateCoverage: ...
def write_stk_factor_pro_bootstrap_coverage_date(
    connection, *, lake_root, staging_root, approval, result,
    previous_result: StkFactorProBootstrapDateCoverage | None,
    previous_result_digest: str | None, date_results: dict,
    check_space, known_records: dict,
) -> tuple[StkFactorProBootstrapDateCoverage, str]: ...
def new_stk_factor_pro_bootstrap_coverage_totals(*, natural_dates: tuple[date, ...]) -> dict: ...
def refresh_stk_factor_pro_bootstrap_date_contribution(
    *, trade_date: date, entry: dict, totals: dict,
    is_open: bool | None, approved_rows: int,
) -> None: ...
def summarize_stk_factor_pro_bootstrap_coverage(
    *, staging_root, approval, approval_digest: str, totals: dict,
    previous_summary: StkFactorProBootstrapCoverageSummary | None,
    previous_summary_digest: str | None, check_space, known_records: dict,
) -> tuple[StkFactorProBootstrapCoverageSummary, str]: ...
```

入口只创建一份`basis_inputs={"files":{},"months":{},"active_month":None}`。files按已核绝对Path保存`{"basis":既有BasisFile,"reason":str,"relation":str|None,"owned":bool}`；months按month_start保存既有FrozenInputs；active_month是当前MonthLimit或None。同月关系仍有效时返回同一对象，已释放月份本任务不得再次prepare。全局或日期文件的首次schema/行数/SHA/identity及实际SQL关系同时登记本任务known_records；已经由本任务其他模块加载的关系直接借用，只补尚未取得的必要依据规则，不重开文件。月release清本月停牌及日工作，全局release在入口finally仅清本模块own的余表，不删除借用关系。文件缺失、专属不可读、已定义schema/代码/业务规则不符按原依据unknown分类；源/正式/统计文件错误及程序/SQL错误不因此吞掉。首次读取后identity改变即停止，不在同任务重新准备。

prepared的固定字段及单日签名见§10.5.7：仅当前日期、两层audit/行数/SHA、已取覆盖依据与关系名，不含原来源、DG引用、旧最终记录或reusable_result。原bootstrap月入口同样输出该布局。raw_physical_code_count继承本日已审唯一主键的raw_audit.row_count，不追加DISTINCT/count。合法无文件由入口用已确认两层0行、无文件身份及空代码关系提供同样事实；不能用缺audit推断源为空或推断业务用途。

旧统计适用性由主入口首次根据已得输入版本确认；适用时提取其计数/样本/明细作为本次同一calculated，不再调用集合算法，不把整个旧DateCoverage或其DG编号传给统计准备。calculated固定七键，evaluate最终记录构造始终接收这份字典；不要用calculated=None让它再猜业务分支。unknown也是明确七键结果，其中计数/原因沿原三态语义，不触发回盘。原SourceComplete/approval_digest和input_digest分别由初始化入口保留、首次生成并交给记录构造/诊断writer，不并入共用prepared。

compute只委托既有calculate_stk_factor_pro_coverage。该函数用已首审生命周期、当前Raw、最终停牌及身份关系作固定本日投影，内部共用_build_stk_factor_pro_coverage_keys；原公共build入口的首次外部输入检查保留，但本模块不再次DESCRIBE或重扫已核代码/日期，不新增skip flag。普通T和初始化T不分别调用两次算法；日期/字段变换不引入新业务值。

diagnostic_run仅为内部已核RunIdentity，纯bootstrap显式None；补数日d等于其原T时用该run的diagnostics/day-{missing|extra}-codes.parquet，d<T时只用原operation日期/input摘要目录。BootstrapCodesRef的creator_run_id据此分别为当前run或None，RawCoverage与Bootstrap日期记录复用同一非零文件/摘要/样本；已知0不创建文件或目录、不做附件EXCEPT/SHA。只有真正非零新输出首次实际读回/对账/摘要一次，原子移动继承；已有同输入附件只首次读入一次并复用，不能先写一份临时附件再重新审旧附件。

主入口的唯一`summary_state`由new_*_coverage_totals创建，传给参数totals；imported/current直接引用其sets中的imported_dates/verified_current_dates，不另存第二套集合。字段固定为：natural_dates（既有批准tuple）、counts（原导入三项、当前两层及已知覆盖五项，键与Summary同名、初值0）、sets（known_open_dates、known_closed_dates、calendar_unknown_dates、imported_dates、source_empty_dates、import_pending_dates、known_coverage_dates、gap_dates、current_files_unverified_dates、verified_current_dates、open_coverage_pending_dates各set）、unknown_by_date（日期→kinds/reason）、date_result_digests（日期→首次payload SHA）、version（初值0）、saved_version（初值None）。open_coverage_pending_dates仅是本任务已有开市日尚无已知覆盖的集合，不新增持久字段。

refresh仅接本日entry、上述合计及本日已知is_open/批准数，不接受路径/连接/instance。entry.previous_contribution保存本日原导入三项/当前两层/已知覆盖五项数量、所属集合、unknown及已持久result摘要；完全相同直接返回，只有摘要改变只更新摘要映射，数量/分类改变才减旧加新一次。初次载入与正常/失败收尾都用这同一方法；覆盖失效先撤旧有效贡献，computed_result不冒充persisted_result，适用旧记录保留。summary不重新调用refresh或遍历date_results；仅序列化现成sets/maps及counts。version未变直接返回同一previous_summary对象和摘要；新执行首次比较既有summary时沿用其evaluated_at，内容相同不改时间/重写；只有必要新版本才取当前时间并保存、更新saved_version。正常summary在主业务try/except之外执行一次；业务失败仅在except收尾一次summary，失败附原异常，不因正常summary保存失败再重复保存。

本bootstrap保持最少写入频率：正常处理结束保存summary一次；业务处理异常时，以已登记日期事实和合计收尾，最多保存summary一次，再抛最初异常。正常summary调用放在业务处理的try/except之外，summary自身失败不得再次进入异常分支重写。逐日只保存必要result并更新本日贡献，不增加逐日或逐月summary写入。未处理月份仍按未知/未完成表达，不加载这些月份文件来凑完整结论。第五批人工补数T及历史20日批末按§10.5.6保存同一state的汇总，仍不全范围重新求和。

旧result仅由read_*_coverage_date在本任务首次读取时确认归属、SourceComplete对应、原输入摘要及实际需要的非零引用身份；已经登记的对象直接复用。坏旧记录不能因文件存在而放行，也不在write/update/summary重新_verify_result。pure prepare_date发现本日源、两层文件摘要、依据及开市分类与已核旧结果相同，直接继承其input_digest；只有新事实才计算新input_digest，不重复计算同一个摘要。原完整0源且当前无文件允许raw_relation显式None，compute建立明确空actual；原source_empty=True但补数已有非空audit时，必须使用当前Raw关系，不能按旧源0推当前0。未知依据可不取得Raw键；其余非空且需已知覆盖的None关系是接口错误，不回盘补参。

解析BootstrapCodesRef时，operation分支继续由operation_path对最终路径执行既有require_stk_factor_pro_safe_path；run分支在受控run根拼接diagnostics相对路径后，同样对最终完整路径执行该检查，不能只核run根。diagnostics子目录或文件为符号链接时，在任何读取/SHA前拒绝，不跟随外部路径；正常路径不增加其它检查或复审。

旧result引用非零明细首次实际消费时，借同一主要连接CTAS一次，核固定ts_code VARCHAR、trade_date DATE列序、本日日期/代码/唯一键/既有行数与SHA一次；已由本任务writer完整首审并登记的引用不再次读回。旧错误列序如实拒绝，不引入legacy格式或自动迁移，本轮不读取/修改正式旧附件。update仍须纯标量核publication的批准契约、processing_version及Silver来源Raw绑定，不能只因publication与result彼此相等就放行错误归属。

输入身份检查由控制层在pure prepare_date之后、复用或新计算之前调用require_*_coverage_identities一次；它仅比较本日basis与Raw/Silver的当前stat和首次known_records.identity，零SQL/文件SHA/业务读取。真正执行compute的路径在result保存前再比较一次；复用路径不做紧接的第二次相同比较。变化停止，不重新prepare后继续；缺失或专属不可读依据按首次已登记unknown处理，不能借检查身份将该合法unknown口径改成失败。guard先核Raw/Silver；当前文件identity无法确认时先置prepared.current_files_verified=False再抛错，basis变化则保留True。控制层catch统一撤旧有效覆盖，仅据这个已得bool决定是否同时撤当前物理数量，不再次stat。pure prepare/evaluate不承担I/O，不因旧result跳过compute而漏掉这条控制边界。

#### 10.5.2 本地依据、日期范围与无法判断的条件

StkFactorProBootstrapCoverageInputs是frozen dataclass，固定字段为 operation_id:str、month:StkFactorProBootstrapMonthLimit、natural_dates:tuple[date,...]、open_dates:tuple[date,...]、closed_dates:tuple[date,...]、calendar_unknown_dates:tuple[date,...]、basis_files:tuple[StkFactorProBootstrapBasisFile,...]、unknown_by_date:tuple[tuple[date,tuple[str,...],str],...]、input_digest:str。每个日期集合升序去重；open_dates、closed_dates、calendar_unknown_dates互斥，三者并集等于natural_dates。这里只保存小型身份、日期及问题摘要，业务行保存在同连接的受控临时关系中，不放进Python对象或JSON。

StkFactorProBootstrapBasisFile固定 kind:Literal["calendar","lifecycle","identity","suspend"]、trade_date:date|None、file_sha256:str|None、schema_content_digest:str|None、row_count:int|None、valid:bool。前三类trade_date为None，停牌为对应日期；路径从kind/日期按正式paths复算，不从记录读取任意路径。缺文件时摘要/行数为None且valid=False；有文件但校验失败不能记录valid=True。unknown_by_date中的kind只取上述四值、去重升序，末项中文原因仅作说明，不用可增长的原因字符串驱动程序分支。

每月输入准备只读取本月裁切范围内的本地文件。日历、生命周期及身份小表在同一执行内文件身份未变时读入连接临时表后复用；最终停牌文件按本月日期一次规划，最多一个自然月，不逐股票、逐日期查询Dagster事件。每月结束释放该月临时关系；全局小表可继续复用。各输入读前后核文件身份，改变则本次受影响日期不能使用旧结论；下一获准执行时才在本地首次准备，不重新导出Prod。

| 输入 | 必须执行的实际核验及判定 |
| --- | --- |
| 日历 | 正式Silver schema含exchange VARCHAR、trade_date DATE、is_open BOOLEAN、pretrade_date DATE；只采用SSE。以批准源首尾之间的完整自然日期序列为主表，检查每日恰好一行、日期可解析及is_open非NULL，再分类开市/休市/未知。缺日期、重复或冲突标志对应日期记未知，不能从“没有因子行”反推休市。完整日历不可得时保留整段未知，不能把工作日当交易日。 |
| 生命周期 | 固定正式silver_stock_lifecycle文件可读、现行完整schema及必需字段非空、代码唯一、curr_type='CNY'且is_cny_stock为True、DATE上市/退市及非倒置区间等必要物理规则通过，且读前后身份一致时，接受这份正式历史事实作为本次统计依据，再使用现行人民币股票select。不按当前list_status或日线自己的最早日期裁剪，不允许用silver_stock_basic等当前上市快照替代。文件缺失、为空、schema或必要规则失败则受影响日期未知；不附加未定义的人工审批或事件检查。该资产没有“全部历史证券已收录”的覆盖起止字段，不能虚构该字段，或仅凭min(list_date)/schema通过宣称绝对全市场完整；报告固定说明按本次DG正式生命周期事实统计，而非独立证明来源从未遗漏某只历史证券。 |
| 身份映射 | 使用正式silver_stock_identity_map；核现行schema、source_ts_code全局唯一、latest_ts_code存在于生命周期、valid_from非空及valid_to区间合法等现行必要规则。按source_ts_code及业务日期匹配，条件为 d>=valid_from AND (valid_to IS NULL OR d<valid_to)。self与旧码映射完全同样处理，不无条件self兜底。参与比较的原始代码日期匹配0条或多条，对应日期记未知并记录数量/至多20个原代码样本，不取第一条、不临时读取Prod映射。 |
| 最终停牌 | 只读silver_stock_suspend_daily的正式日文件，不另读confirmed或Raw自行合成。固定正式文件可读、现行完整4列schema、非空代码、DATE恰为本日，业务键(ts_code,trade_date,suspend_type,COALESCE(suspend_timing,''))唯一，suspend_type非空且仅S/R，按现行停牌时段规则校验，通过且读前后身份一致时接受该正式最终停牌事实；合法时段非空仍是日内停牌。符合这些条件的0行文件表示没有停牌，不附加未定义的生成证明或逐日事件门槛；缺文件、无法读回、坏schema或日期错位不能当0停牌。不调用写入/修正停牌函数，也不声称本次另外核实了源端全部历史停牌。 |

代码合法性也是准备阶段的必要规则：生命周期ts_code、身份source_ts_code/latest_ts_code及最终停牌ts_code均复用本数据集现行`[0-9]{6}\.(SH|SZ|BJ)`合同，不只检查非空。错误归入实际出现问题的lifecycle/identity/suspend依据；影响日期、依赖传播及异常界限按§17.8.4处理。不得删除无效代码后继续宣称该依据有效。

schema必须直接引用SILVER_TRADE_CALENDAR_SCHEMA、SILVER_STOCK_LIFECYCLE_SCHEMA、SILVER_STOCK_IDENTITY_MAP_SCHEMA、SILVER_STOCK_SUSPEND_DAILY_SCHEMA，不重新维护另一份列定义。必要物理SQL逐项对照checks/calendar_checks.py、stock_lifecycle_checks.py、stock_identity_map_checks.py、suspend_d_checks.py中的同名资产现行检查，移到本连接本月关系上执行；不调用这些会自行创建连接的Dagster装饰函数，不因本节只列摘要而漏掉其主键、必需非空及域规则。涉及其他资产、全历史事件或来源重新下载的步骤均不进入本节。

输入只作为覆盖依据，不是传输成功门槛。已确认休市而Prod有本日源行，属于原规则中的已知日期冲突，停止处理，不能把它归为覆盖未知后发布。日历缺失或尚不可判断不等于已确认休市：源DATE、范围及传输校验有效的行可忠实导入，覆盖记“是否开市无法判断”；不伪造开市标志、动态分区或物化事件。分区注册只针对已确认开市日期，未确认部分保持未确认，正式事件补记仍另行授权。

自然日期范围严格为approval.start_trade_date至end_trade_date，不默认从2017开始，也不扩展至执行当天。该范围内源计数0的开市日同样进入统计；首尾以外例如22、23日可说明不在本次范围，但不能混入已判定缺口总数或自行追加远程查询。已确认休市且源0的日期只在日历分类中汇总，不制造股票覆盖结果或正式空文件。

#### 10.5.3 两种差异的判定及集合SQL

先完成“来源确实导入”的核对，再判断“应有股票是否齐备”，二者分别记录：

- 本期首次导入或等价复用的完整日期，源批准计数、当前源复核计数、实际导出/片段读回行数、正式Raw行数及Silver行数必须一致；同时通过§9.2完整字段/主键双向对账，不能只比数量。任一导出漏行、重复、值错或目标身份冲突都停止当前流程，不用市场缺口解释同步错误。
- 上述导入核对通过后，以实际正式Raw的唯一物理代码/日期为输入，只为本地覆盖统一身份。Raw及Silver本身的源代码、业务值和行数不因统计而改写或去重。一个身份有两个源别名时，物理行数/物理代码数可以大于实际身份数，必须分别保留。
- 确认全部应有依据有效后，上市集合按list_date<=d AND (delist_date IS NULL OR d<delist_date)，北交所不早于2021-11-15；其中上市首日按§21.10作为可选代码；在同一有效身份规则下统一上市、停牌、可选首日及实际四侧，去重后仅扣除S且suspend_timing为NULL的全天停牌，日内停牌仍应有。

连接中的输入临时关系为listed_keys(trade_date DATE,ts_code VARCHAR)、full_suspend_keys/actual_keys/first_day_keys（同列），first_day_keys来自目标日list_date=T。所有关系在同一纯函数内按目标日统一身份一次；缺映射或歧义不得静默丢行。以下SQL使用已统一身份的关系，首日集合先与合法上市且非全天停牌的集合取交集，再同时用于排除必需侧和实际比较侧，原实际业务行保留。

对当前日期的这些小关系，以DuckDB SQL一次生成受控临时expected、missing、extra关系，后续数量和明细从同一结果读取，不为输出三个计数重算全套输入：

~~~sql
-- 所有关系均已限定当前日期、统一身份并去重。
CREATE TEMP TABLE stk_factor_bootstrap_eligible AS
SELECT trade_date, ts_code FROM listed_keys
EXCEPT
SELECT trade_date, ts_code FROM full_suspend_keys;

CREATE TEMP TABLE stk_factor_bootstrap_optional AS
SELECT trade_date, ts_code FROM stk_factor_bootstrap_eligible
INTERSECT
SELECT trade_date, ts_code FROM first_day_keys;

CREATE TEMP TABLE stk_factor_bootstrap_expected AS
SELECT trade_date, ts_code FROM stk_factor_bootstrap_eligible
EXCEPT
SELECT trade_date, ts_code FROM stk_factor_bootstrap_optional;

CREATE TEMP TABLE stk_factor_bootstrap_actual_compared AS
SELECT trade_date, ts_code FROM actual_keys
EXCEPT
SELECT trade_date, ts_code FROM stk_factor_bootstrap_optional;

CREATE TEMP TABLE stk_factor_bootstrap_missing AS
SELECT trade_date, ts_code FROM stk_factor_bootstrap_expected
EXCEPT
SELECT trade_date, ts_code FROM stk_factor_bootstrap_actual_compared;

CREATE TEMP TABLE stk_factor_bootstrap_extra AS
SELECT trade_date, ts_code FROM stk_factor_bootstrap_actual_compared
EXCEPT
SELECT trade_date, ts_code FROM stk_factor_bootstrap_expected;
~~~

关系名均为代码固定内部标识，日期/文件引用按既有绑定和路径白名单生成；处理下一日期前删除本连接的上述临时表，不创建持久数据库表。missing/extra完整明细用COPY显式投影ts_code、trade_date，ORDER BY trade_date,ts_code写本地Parquet，不用fetchall拿回全市场历史。集合去重语义及COPY写法核对[DuckDB集合运算](https://duckdb.org/docs/stable/sql/query_syntax/setops.html)与[COPY查询结果](https://duckdb.org/docs/stable/sql/statements/copy.html)，具体字段和业务预期仍以上述本地合同及独立样本为准。

coverage_complete只有在本覆盖规则版本和依据有效且missing_count=0、extra_count=0时为True；忠实导入有缺口仍记录False，不阻止合法原源行导入。

计数定义唯一：expected_count=expected行数；actual_count=统一后actual排除可选首日代码的唯一身份数；matched_count=expected与actual交集数；missing_count=missing行数；extra_count=extra行数。必须同时满足 expected_count=matched_count+missing_count、actual_count=matched_count+extra_count。源物理行数和Raw物理代码数另列，不能代替matched_count，也不能拿extra抵消missing。应有A/B、实际A/C的独立样本必须得expected=2、actual=2、matched=1、missing=1、extra=1。

上述A/B/C仅是说明用简称，测试Raw代码必须符合源合同。独立夹具可固定A=000001.SZ、B=600000.SH、C=000002.SZ，三者生命周期/有效映射完整，其中C有本日全天停牌事实；来源及DG都含A/C，故应有A/B、缺B、额外C。预期代码和数量用字面值独立指定，不能调用待测覆盖函数生成expected。该夹具证明集合规则，不声称这些股票现实中某日发生了这一情况。

原bootstrap入口忠实导入源0行日期时，只有在对应查询已正常EOF、未触R+1、所选日期包含该日、源批准/当前计数均为0且来源条件仍有效时，才能按§10.3保存无片段的完整空源事实。正式Raw/Silver均不存在时，actual关系明确为空，不生成两层空文件：开市且依据有效时应有N个身份即缺N个；日历未知时可确认原源空/导入完成，但覆盖仍未知；确认休市时只作日历分类。该首次分支已有任一目标文件时先按§10.4处理冲突，不删文件或拿旧目标冒充原源。上线前初始化补数已形成合法两层数据后，原source_rows=0不再要求当前无文件；按§10.5.6核当前两层并计算实际集合，原空源记录保留，不能继续报“本日实际0”。月游标中断、来源变化或未取得完整空源事实仍是原导入未完成，不得伪造原源空证明。

覆盖依据未知（含准备阶段已分类的非法代码）时，不进入要求合法四侧的已知覆盖计算分支，也不调用该分支后笼统捕获ValueError。source_rows、raw_rows、silver_rows及物理代码数仍可来自已经完成的传输核对；expected/actual身份数/matched/missing/extra及coverage_complete统一为None，不猜0。记录具体缺少或无效的输入种类。缺股票、额外合法源行和覆盖未知不新增blocking check、不阻止其余合法日期导入，不自动调用Tushare补采，也不自动修复本地上游。

#### 10.5.4 逐日记录、文件与最终汇总

StkFactorProBootstrapDateCoverage及Summary按以下完整类型读写；record_version固定1，日期/计数/摘要遵守§5.4公共标量规则，未知键拒绝。不是新平台状态表，所有记录是本次既有bootstrap operation目录内的审计附件；bootstrap物理阶段没有可替代它的正式物化事件，源完成记录也不能代替正式文件已导入的结论。

~~~python
CoverageInputKind = Literal["calendar", "lifecycle", "identity", "suspend"]

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapCodesRef:
    creator_run_id: str | None
    relative_path: str
    file_sha256: str
    row_count: int

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapContext:
    operation_id: str
    approval_digest: str
    target_trade_date: date
    authorized_date_result_digest: str
    authorized_gap_input_digest: str
    authorized_missing_count: int
    authorized_missing_codes_ref: StkFactorProBootstrapCodesRef
    authorization_run_id: str

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapCurrentPublication:
    run_id: str
    trade_date: date
    raw_materialization_storage_id: int
    raw_check_event_storage_id: int
    silver_materialization_storage_id: int
    silver_check_event_storage_id: int
    raw_file_sha256: str
    silver_file_sha256: str
    silver_source_raw_sha256: str
    contract_content_digest: str
    processing_version: str

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapPublicationBatch:
    publications: tuple[StkFactorProBootstrapCurrentPublication, ...]
    incomplete_dates: tuple[date, ...]
    unchanged_dates: tuple[date, ...]

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapDateCoverage:
    record_version: int
    coverage_rule_version: str
    operation_id: str
    approval_digest: str
    trade_date: date
    source_rows: int
    raw_rows: int
    silver_rows: int
    raw_physical_code_count: int
    source_complete_digest: str
    raw_file_sha256: str | None
    silver_file_sha256: str | None
    import_complete: bool
    source_empty: bool
    current_publication: StkFactorProBootstrapCurrentPublication | None
    is_open: bool | None
    basis_files: tuple[StkFactorProBootstrapBasisFile, ...]
    unknown_input_kinds: tuple[CoverageInputKind, ...]
    input_digest: str
    identity_unmapped_count: int | None
    identity_ambiguous_count: int | None
    identity_unmapped_sample_codes: tuple[str, ...]
    identity_ambiguous_sample_codes: tuple[str, ...]
    expected_count: int | None
    actual_count: int | None
    matched_count: int | None
    missing_count: int | None
    extra_count: int | None
    coverage_complete: bool | None
    reason: str
    missing_codes_ref: StkFactorProBootstrapCodesRef | None
    extra_codes_ref: StkFactorProBootstrapCodesRef | None
    missing_sample_codes: tuple[str, ...]
    extra_sample_codes: tuple[str, ...]
    evaluated_at: datetime

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapCoverageSummary:
    record_version: int
    operation_id: str
    approval_digest: str
    start_trade_date: date
    end_trade_date: date
    evaluated_at: datetime
    known_open_dates: tuple[date, ...]
    known_closed_dates: tuple[date, ...]
    calendar_unknown_dates: tuple[date, ...]
    imported_dates: tuple[date, ...]
    source_empty_dates: tuple[date, ...]
    import_pending_dates: tuple[date, ...]
    known_coverage_dates: tuple[date, ...]
    coverage_unknown_dates: tuple[
        tuple[date, tuple[CoverageInputKind, ...], str], ...
    ]
    gap_dates: tuple[date, ...]
    verified_source_rows: int
    verified_raw_rows: int
    verified_silver_rows: int
    current_raw_rows: int | None
    current_silver_rows: int | None
    current_files_unverified_dates: tuple[date, ...]
    date_result_digests: tuple[tuple[date, str], ...]
    expected_count_known_dates: int
    actual_count_known_dates: int
    matched_count_known_dates: int
    missing_count_known_dates: int
    extra_count_known_dates: int
    all_coverage_determined: bool
    total_missing_count: int | None
    all_expected_present: bool | None
~~~

| 字段 | 固定合同 |
| --- | --- |
| record_version、operation_id、approval_digest、trade_date | 固定版本、本operation及其不可变批准摘要、本日DATE；所有引用均核同operation和日期。 |
| source_rows、raw_rows、silver_rows、raw_physical_code_count | 非负精确int。source_rows始终取原Prod完整日源计数；后三项取最近一次已核验的当前正式两层及Raw物理代码数量。原bootstrap入口在忠实导入/原源恢复时核source_rows=raw_rows=silver_rows；初始化补数按当前有效两层及主键合并结果记录，不再与原Prod计数强等。职责由入口确定，不用current_publication的空值选择流程；记录类型自身不根据该字段是否存在施加某种业务用途的数量条件。旧结果身份失效时不得当成当前数量。 |
| source_complete_digest、raw_file_sha256、silver_file_sha256 | 完整原日源记录摘要必填且不改写；后两项是当前正式两层SHA，不是原导入文件SHA。原空源且尚无补数时可均None；正式补数后即使source_rows=0，两项也必须非空且对应current_publication；不能用候选摘要冒充正式目标。 |
| current_publication | 仅保存已持久化DG发布/check的真实引用，由最终记录构造函数消费；共用覆盖准备/计算不接收此对象。原导入无DG引用及合法无文件分支由各自入口明确处理，不能通过该字段空/非空推断用途。字段有值时只核结构及对应日期/文件，不据此选择业务。 |
| import_complete、source_empty、is_open | import_complete固定True，表达原忠实导入已完成，不因后来补数失败抹去；source_empty仅代表原Prod已核验0源，补数后仍保留True，不再推出当前没有文件。is_open为True或None。确认休市且0源不产生此记录，休市有源是冲突。原导入未完成日期不能由补数记录伪造完成，由汇总明确列出。 |
| current_publication | 初次导入为None；正式补数后保存上面完整类型。run_id来自真实获准补数任务；四个id均为对应真实事件记录的正精确storage_id，两个check字段不是check执行id、不是目标物化id；各check的target_materialization_data须绑定本类型对应的物化。实际文件SHA、Silver来源Raw SHA、契约及处理版本必须匹配。类型不能从运营传入的passed=True或随意id构造，核验步骤见§10.5.6。 |
| basis_files、unknown_input_kinds、input_digest | 月Inputs包含本月全部必要文件；逐日result只保留日历/生命周期/身份三份全局引用及本日停牌引用，不能复制其他日期停牌引用。有限输入种类不作为下载器错误码。摘要投影见下文，不含时间或attempt计数。 |
| identity_unmapped_count、identity_ambiguous_count及各自sample_codes | 对本日上市/停牌/首日可选/实际四侧参与代码日期的去重并集统计映射0条/多条数量，样本按原代码升序最多20条；映射文件本身无法核验时数量None、样本空并记identity未知，能核验时0必须明确。已知覆盖结果要求两数均0；无映射不能当0股票。 |
| expected_count、actual_count、matched_count、missing_count、extra_count | 已知覆盖时全部非负int并满足上述两项算术；未知时全部None，不混合拼接来自旧输入的数值。 |
| coverage_complete、reason | True仅表示本日已确认开市、覆盖规则版本一致、依据齐全且missing=0 AND extra=0；False表示已确定缺失或额外代码，None表示日历或其他依据不足。reason只作中文说明，不把extra抵消missing，也不删除原源行。 |
| missing_codes_ref、extra_codes_ref、missing_sample_codes、extra_sample_codes | 已知非零差集保存本日完整明细引用；引用固定creator_run_id/relative_path/file_sha256/row_count；creator_run_id为必填可空字段。0差集不创建文件、ref=None，样本代码升序最多20项；未知时引用None、样本空，靠nullable计数区分未知与0。 |
| evaluated_at | aware datetime，JSON固定+08:00；不进入input_digest。 |

BootstrapContext八字段均必填且拒绝未知键：operation_id/authorization_run_id为已核安全标识/真实run_id，target_trade_date为原T；三个digest均为64位小写SHA-256，authorized_missing_count是正精确int，authorized_missing_codes_ref按其原creator_run_id确定的受控operation/run根核schema/行数/摘要，保留首次授权引用且row_count等于该正缺失数。authorization_run_id始终指首次持久化有效开始授权观察的run，读回可在原run或后续获准重执行核实，不随历史d或retry更换；核既有授权不要求读已被更新的旧result。PublicationBatch三组日期升序唯一且互斥：publications为本批两层/check完成；incomplete_dates为当前两层已知无效、或触及发布后无法确认；unchanged_dates为未触及或目标未变且原依据仍有效的日期。未触及但发现原事实已失效时仍列incomplete，不能宣告有效；三组共同解释原批准交集内需文件日期，不能将仅未执行等同文件失效。

本节补充§5.4.2的bootstrap专属摘要，统一调用同一content_digest的外层record_kind/record_version/value，不另写算法：月摘要kind固定stk_factor_pro.bootstrap_month_basis，value按字段顺序包含operation_id、approval_digest、month_start/month_end_exclusive、natural/open/closed/calendar_unknown日期数组，以及按kind、trade_date排序的全月basis_files；日期摘要kind固定stk_factor_pro.bootstrap_date_coverage，value包含operation_id、approval_digest、trade_date、is_open、source_complete_digest、source_rows、raw_file_sha256、silver_file_sha256、source_empty及排序的本日basis_files。日期先转ISO文本，None保留null；BasisFile全部六字段参与，不能把月input_digest直接当逐日input_digest。同一日停牌改变只影响本日；全局依据改变才影响引用它的多个日期。

路径全部由paths.py从已批准operation和日期派生：coverage/<YYYY-MM-DD>/result.json；直接bootstrap的非零差集位于operation的coverage/<YYYY-MM-DD>/input=<input_digest>/missing-codes.parquet与extra-codes.parquet；目标日T补数共用已保存run明细；历史d<T只沿operation日期目录保存一次，具体归属见§10.5.6。两列统一ts_code VARCHAR NOT NULL、trade_date DATE NOT NULL，主键两列，完整缺失行数必须等于missing_count，额外行数必须等于extra_count。不得在source/dates的不可变完整源记录内追加或改写覆盖结果，也不把字段加进261列业务文件。

写入顺序：核当前输入身份→临时明细COPY/读回数量和键→同文件系统原子保存明细→校验完整result结构及引用→按§5.4由同一payload计算摘要、临时JSON/fsync/replace/父目录fsync，直接返回对象/摘要，最后使result成为当前日期的唯一结果。非零明细先于JSON，输入摘要区分复算版本；绝不先覆盖旧明细让旧JSON引用新内容。写失败不回滚已发布Raw/Silver，也不能谎称该日期统计成功；下次可在本地补算。结果只在同operation同日期替换，不能按批次/恢复次数累加。

最终summary使用本任务已持有的批准日期账本、已维护计数/日期集合及记录摘要。任务入口首次加载必要旧记录并形成合计一次；后续每个日期版本变化时精确替换旧贡献一次，版本未变不更新。summary不自行读取SourceComplete、complete、result、任何业务文件或PG，不从各日记录重新求和。

- record_version、operation_id、approval_digest、start_trade_date、end_trade_date、evaluated_at；
- known_open_dates、known_closed_dates、calendar_unknown_dates三个升序日期数组；完整自然日期范围必须无遗漏。日历全段不可确认时，前两数组可空但未知日期不能丢。
- imported_dates、source_empty_dates、import_pending_dates表达原导入事实；imported只能取verified_import_dates，包含已证明源0且日历未知的日期；source_empty_dates取原源0的已导入日期，后来补出行也不删除该历史事实。设C0为已确认休市且原批准源计数0的日期，固定import_pending_dates=完整自然日期集合-C0-imported_dates，防止正常休市日被算成未完成；休市有源仍是冲突。原导入未完成不能用补数覆盖结果冒充完成。
- known_coverage_dates、coverage_unknown_dates、gap_dates；known只能取verified_current_dates中当前result有效、日历及其他依据齐全的日期；不能仅因旧JSON有数值就纳入。unknown保留每日期原因；只是当前文件不可核验时，其unknown_input_kinds可为空tuple并明确文件/发布原因，不另造第五种上游输入。gap_dates必须是known且missing>0。
- verified_source_rows、verified_raw_rows、verified_silver_rows只从原完整日源及原两层PublicationComplete的行数汇总；原源0且原两层未造文件时，按已核空源事实三项取0，不要求不存在的PublicationComplete。三项相等是原忠实导入的传输证明；不能从已被补数改为5000的当前coverage.raw_rows取原导入合计，也不将它们改写成5000。
- current_raw_rows、current_silver_rows是当前正式两层的全范围合计，只在所有需导入日期原导入完成且当前文件均可核验时给出非负int，否则均为None；不把部分已知数量叫作全范围当前总数。两者按本期完整字段/不增删行规则相等，但允许不同于verified_source_rows。current_files_unverified_dates明确列出已原导入但当前文件缺失、改写无凭据、补数两层未完成等日期；这些日期归入coverage_unknown_dates，不抹去imported_dates。
- date_result_digests保存本次从小记录同一字节取得的(date,SHA)，绑定summary输入；使用完整性结果时核小记录引用及控制层已确认发布事实，不据此重新打开全部Raw/Silver计算SHA。缺必要事实报告未知/停止，不能只信旧summary的True，也不把summary改成全历史审计。
- expected_count_known_dates、actual_count_known_dates、matched_count_known_dates、missing_count_known_dates、extra_count_known_dates：只汇总known_coverage_dates，满足两项集合算术；不能把unknown日期实际行数掺入这些分母。
- all_coverage_determined:bool、total_missing_count:int|None、all_expected_present:bool|None。仅批准范围内所有日期已确认开休市、所有需导入日期原导入完成、current_files_unverified_dates为空且所有开市日当前覆盖可判定时all_coverage_determined=True，此时total_missing_count=missing_count_known_dates，all_expected_present=(total_missing_count==0)。其他情形后二者为None，但保留已判定范围及已知缺口数，不能把部分结果命名为全范围精确总数。

summary固定保存coverage/summary.json。只在日期账本版本改变时序列化和原子写入一次，直接返回内存对象和payload摘要，不回读、不再反解析。正常日/每20日批末及异常收尾共用同一个合计；账本未变不重复写summary。新执行从实际逐日持久记录首次重建本次账本，不盲加旧持久summary总数。

#### 10.5.5 失败、恢复、输入修订与成本

| 位置/条件 | 固定动作 |
| --- | --- |
| 源游标未完整、片段/两层对账失败 | 继续原§10.3～10.4停止/重读规则；当前日不生成最终覆盖记录，不把半日算成Prod缺口。此前合法文件保留。 |
| 日源完整但候选/一层尚未发布 | 沿既有bootstrap逐文件记录恢复；两层均完成前不形成正式逐日覆盖。完整日源可复用，不为覆盖重读远程。 |
| 原导入两层完成而覆盖未保存/明细或JSON写失败 | 核当前正式文件及原日源身份后，仅本地补算并原子保存；不重新导出该完整日期，不回滚已提升文件。Tushare补数任务失败后的重新执行仍按§10.5.6全新下载，不把本行当作失败补数续用源的例外。 |
| 本日统计、源和目标及本地依据身份均匹配 | 复用本日期结果；不重算、不累加。仍在最后汇总中计一次。 |
| 只本地依据修订或原统计为未知且现有依据已可判断 | 旧覆盖结果失效，下一获准执行时首次准备新输入并计算一次；不下载Prod或Tushare，不把旧None/0保留成新结论。没有适用依据仍返回未知。 |
| 当前正式文件因§10.5.6获准补数发生变化 | 核补数两层发布/check及当前身份，更新同一result及summary的当前部分；原导入记录/计数不变，不再要求当前行数等于原来源，也不重启旧Prod恢复。 |
| 正式目标无合法补数凭据地变化，或源批准/来源身份变化 | 先执行§10.4冲突停止规则；不能用“统计复算”绕过文件冲突，不能重设prior或更改approval。原已完成导入事实保留，当前文件无法核验时进入current_files_unverified_dates。 |
| 已确认日期有缺口或仍无法判断 | 已导入合法文件继续保留和可读，报告缺失/未知；不新增最低覆盖率，不启动补采、停牌重建、跨工程契约修改或日更任务。 |

处理期间输入身份变化时，当前受影响日期不保存旧结论，停止本轮，不重新prepare该月或再次审计后继续。下一获准执行按实际剩余工作首次准备必要输入、仅算缺失/失效统计一次。正常最后summary复用已确认日历分类及逐日结果，不重新逐月prepare、不核业务路径SHA，不将首次准备混到每批汇总。

新增成本在执行前随原预算记录，且不得隐藏在“顺便统计”中：

| 成本 | 上界与拒绝/退回规则 |
| --- | --- |
| 正常本地读取 | 本月自然日期至多31；一次准备生命周期/身份/日历必要列及本月最终停牌文件。实际代码用本次已有Raw主键关系，统计不再读261列；不逐行Python计算、不逐日event深扫、不新增Prod查询。 |
| SQL及内存 | 设本月导入R行、生命周期L行、停牌S行，所有代码关系至多O(R+31L+S)；逐日差集只对当前d计算，不能对每个日期重新拼整月历史。沿同一DuckDB设置及临时目录，不新建全历史Python集合或新内存配置。 |
| 持久文件 | 需要统计的日期N，每日1个result，非零缺失/额外至多各1个明细，另1个summary；最终当前版本最多3N+1文件，复算历史证据另计。单日明细不超过相应应有/实际唯一身份数，不能把全部261列复制成诊断。 |
| 中断后继续 | 已有效结果仅核身份；缺失/失效统计只投影对应完整日Raw主键并读取受影响依据，预算包括本地明细重写。来源未完整的日期远程重读成本仍属原bootstrap，不因覆盖统计而省略。 |
| 最后验收 | 直接使用本任务已得日期规划、源计数、逐日结果与已维护合计；首次构造记录时确认的集合算术/引用数量继续复用，只列未知/未完成范围；不再次扫描全部指标或跑Prod全历史缺口SQL。 |
| 预算无法满足 | 在执行前按真实日期/行数/文件及可用空间列开销，结合原源超时/R/空间上界检查；不能满足则停止或缩小本地计算批次，业务批准范围不变。不能静默丢日期、只存20条样本冒充完整缺口、以扩大Prod扫描来规避本地设计，也不自行增设资源参数。 |

精简验收仅用现有合同构造小型临时文件和独立字面预期，覆盖：A/B对A/C；应有5000、源4800且DG4800与源4800却DG4799的两类差异；同日跨5000批；合法0行停牌与缺停牌文件；已确认开市源0/半日中断/日历未知/已知休市有源；日期首尾及范围外22/23；合法负值/NULL原样保留；双别名同身份不重复；self/alias日期边界、缺映射/同source多映射；Raw已发布Silver失败不统计成功；结果写失败、重入不累加、依据改变只本地复算、统计完成不再重扫。不得为证明这些分支重跑全历史或另读5000行生产样本。实现后的最小真实来源交接与正式执行授权继续按§11.1办理，隔离用例不能宣称正式bootstrap已经通过。

#### 10.5.6 上线前初始化补数结束后更新原导入记录

本节仅用于开发阶段、上线前的初始化补数及其重新执行/历史repair。上线后普通日更和正式repair不调用本节函数，不读取导入批准/原SourceComplete及缺口统计，不维护这次初始化的总汇总。operation记录就是某一次初始化导入留下的记录，operation_id是该次导入编号。初始化补数在自己的收尾流程更新这次导入的`coverage/<d>/result.json`及`coverage/summary.json`，不建立另一套审计入口、job、状态表或全历史数据扫描。补数的下载/合并/发布仍遵守本数据集原规则；本节只负责接收已经真实发布并通过检查的两层结果，不下载、不提升业务文件，不替代补数授权。原bootstrap SourceComplete和PublicationComplete始终不改，bootstrap恢复也不得用旧Prod源覆盖补数结果。

**调用关系和内部接口。**asset/op持有本次用途及已核Context；原导入记录读取与初始化授权位于`defs/bootstrap/stk_factor_pro_history.py`。共用集合计算位于`defs/asset_guards/stk_factor_pro_readiness.py`，初始化诊断、最终记录构造、保存及summary位于`defs/bootstrap/stk_factor_pro_bootstrap_coverage.py`，职责按§19.11。运营不能直接传路径、计数、passed或事件id，IO候选/发布模块不接初始化授权来选择业务。补数控制层在维护检查后读固定operation的approval并核approval_digest、原全范围物理导入已完成及本日原SourceComplete/两层导入完成记录；不要求旧覆盖已经齐备，也不要求历史事件已经补齐。首次补数按§10.7解析七字段及bootstrap授权；原生日更重新执行沿已核Context，历史repair从精确source_run继承Context而不增加四项配置。不得扫描staging猜operation或伪造parent。

具体调用者为asset/op控制层：文件检查后、当天关系尚在时计算覆盖，不要求DG编号先存在。下面两个接口只负责取得已有事件事实和保存最终记录，分别在真实事件保存后取得引用、最终记录构造后执行保存，不能将它们的时点当成共用覆盖计算的前置。IO候选/发布模块不import bootstrap；bootstrap原导入仍可复用这些IO函数，不形成bootstrap→publication→bootstrap循环。Context是内部传参/PG意图，不是让IO自行发现operation或另开线程执行统计。

```python
def read_stk_factor_pro_bootstrap_current_publications(
    instance: dg.DagsterInstance, *, context: StkFactorProBootstrapContext,
    run_id: str, audits: tuple[StkFactorProFileAudit, ...],
    expected_file_dates: tuple[date, ...],
    attempted_dates: tuple[date, ...],
    known_pg: dict, known_records: dict,
) -> StkFactorProBootstrapPublicationBatch: ...

def update_stk_factor_pro_bootstrap_after_publication(
    connection: DuckDBPyConnection, *,
    lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    result: StkFactorProBootstrapDateCoverage,
    previous_result: StkFactorProBootstrapDateCoverage | None,
    previous_result_digest: str | None,
    known_records: dict, date_results: dict,
    check_space: Callable[..., BootstrapSpaceEstimate],
) -> tuple[StkFactorProBootstrapDateCoverage, str]: ...
```

上述接口已按§19.11同步到本轮源码和直接消费者；实际job装配及其验收仍未完成。第一个函数只负责取得/复用已保存的真实事件事实；第二个只保存已构造的最终result并更新现有日期条目，不再接prepared、publication和两层audit重复交叉核对。DG引用与本次两层audit的一次对应核验在现有evaluate记录构造函数中完成，不新增独立绑定接口。write继续核本operation/日期、原记录摘要及保存顺序，不重新审计文件或计算覆盖。

执行用途由asset/op已解析的入口及既有purpose确定。bootstrap_context、approval和原SourceComplete仅由初始化入口持有；不传入共用覆盖计算。bootstrap_context的operation/摘要、原T及授权仍按§10.7/§4.1核。上线后普通阶段观察Context固定null，不能从任意同T run猜授权。初始化记录收尾的发布日期可为T或原plan范围内d<T，只更新原批准日期交集；范围外只做正常发布和事件。CurrentPublication只在两层及对应check已经保存后用于最终记录；缺DG编号不阻止本日覆盖计算，不能反向改变任务用途或伪造完成。

**补数收尾的空间检查绑定。**本段是第五批控制层的编码要求，本轮只校准接口，不提前实现控制层。它不经过bootstrap主入口，不能把内部必填`check_space`遗漏或传测试用`check_test_space`。具体顺序固定为：

1. 授权核验后、首次本地覆盖计算及非零明细保存前，取得本任务内部容量闭包；不能等批末真实check事件保存后才建立。日补数只处理1日；历史直接复用§18.6.1已接收operation日期交集和统计预算的同一闭包，不另算一套历史预算。不调用`_bootstrap_space_check`重做整个operation分类，也不重启bootstrap。
2. 复用本任务已取得的`temp_directory`，尚未取得时才从当前主要连接读取一次。日补数的统计部分复用`estimate_bootstrap_space`和`require_bootstrap_space`，固定`statistics_only=True`，`pending_source_rows_by_month=()`、`remaining_layer_rows=()`、`pending_fetch_rows=0`。两层audit交出后，以已得Raw行数设置本日`work_rows=(raw_audit.row_count, raw_audit.row_count)`，不重新读取业务数据。直接处理已确认合法无文件的日期可取0，沿§10.5.7的零实际分支。非空补数的最终记录由evaluate接真实CurrentPublication与已得两层audit完成一次关联核验；update_after_publication只接该最终result，不接或重新核同组audit。容量回调不能放宽文件、事件或合法空结果的要求，缺必要事实不能猜0。统计部分S=C_new=0，T沿§17.8.2仅统计公式，J覆盖尚需写的本日result及1份summary；历史这些量已含于§18.6.1的W/J，不重复相加。
3. 同一闭包显式传给本地覆盖计算/明细保存、批末`evaluate构造最终记录 → update_after_publication(result=最终记录)/write`及最后`summarize`。参数为§17.8的`stage/path/trade_date/rows/event`；路径只接受已核operation内的位置。尚待日期由本批待更新日期建立去重集合；writer原子保存成功并登记本日对象/摘要后才用`event=date_completed`移除该日，同结果复用而没有重写也只移除一次。`record_saved`仅观察已持久大小，不提前移除日期。全部日期完成后remaining_date_count=0，仍为summary保留1份J，summary原子保存成功并登记对象/摘要后结束闭包。后续读写边界按设备重新检查free；实际JSON大小按日期组增量维护，已占字节不重复计为新增，设备归并及16MiB余量仍由原函数处理。
4. 回调与批次同生命周期，仅保存预算元信息。统计失败或空间不足继续抛出，保留已发布文件；重执行仍按既定日/历史新下载规则，不把统计回调变成下载缓存或恢复入口。来源/候选预算和校验均不能借统计闭包绕过。本段统计闭包只为上线前初始化收尾建立；普通日更/repair不加载初始化小记录、不创建该闭包或导入总汇总。
5. 不新增运营输入、连接、表、锁、磁盘扫描或Prod请求。summary只用本任务已维护合计，不能重新读取小记录、求和或扫描业务字段。第五批验收须覆盖正常日收尾、20日尾批、原源0补出、空间不足、重复收尾不累加及零Prod/零业务全历史读取。

**实际写入日期的取得。**日/历史发布源码已增加下面的内部回调，并已有发布内核及隔离事件测试；完整asset/op故障收尾与统计接线尚未完成。后续复用原回调，按新版职责补受影响的定向验收，不重写候选、替换或yield流程。固定可选关键字参数：

```python
on_publish_attempt: Callable[[date, Literal["raw", "silver"]], None] | None = None
```

该参数由两个外层发布函数原样传入内部`_publish_file`，只供本数据集编排使用，不进入运营配置、下载器契约或标准进度通知。每个实际文件在候选检查、目标身份及原有前置核验完成后，**紧接首次写intent之前**同步调用一次，参数为该候选的实际trade_date和layer。内容等价复用仍需保存本run intent/complete，故同样通知一次；`skip_no_file`和下载/校验尚未进入发布的日期不通知。通知不表示文件已经改变或发布成功，成功仍以读回、complete及原yield结果为准。

控制层回调只把`(trade_date,layer)`加入当前批次内存集合：日阶段至多1日/2项，历史当前批次至多20日/40项；由此升序去重得到attempted_dates。不能用所有计划日期代替实际通知，不能把成功yield当作唯一触及证据。回调不查询数据库/文件、不写记录或业务数据、不新增日志、线程、锁；它是编排正确性的内部调用，异常直接向上传播，不能像进度通知一样吞掉，且本文件尚未写intent/replace，不重试该回调。

正常批次收尾，或发布迭代器发生可捕获异常/协作取消时，控制层仍持有本批集合、§18.2.1逐层登记及此前已交出的真实audits/事件；据这些事实更新统计，不重新打开业务文件，保留最初错误，收尾错误附后。只有本批事件、result/summary及阶段观察收尾完成后才清空集合/进入下一批，禁止在finally中yield。GeneratorExit/进程直接退出时不强行yield收尾事件，不依赖此内存集合恢复下载，下次仍按原完整范围重新下载；原已发布文件和持久事实保留。

例如第2日Raw已经replace、写complete失败，此层未yield，回调仍记录第2日Raw已进入发布边界；不能把第2日旧统计当作当前两层已通过。第1日已完成事实保留，第3～20日尚未进入发布的日期不被一并作废；若逐层登记表明attempted日期尚未改变且原依据有效，也不误作废。第五批验收须覆盖上述失败点、intent失败前后的区分、等价复用、skip_no_file、内部回调失败时零intent/零replace、未注册时现有正常顺序及结果不变；只用隔离文件及临时instance。

事件读取接收整批实际完成audits（含Raw-only尾日）、本批需文件计划expected_file_dates（skip_no_file不加入）及真正进入文件发布边界的attempted_dates。后者在写intent/replace前记录，不能用整个未执行计划代替；未触及日期沿原有效事实核验。先匹配全部实际事件，再求原批准交集；publications只含本日两层/check俱全，incomplete_dates只含已改变/无法确认当前两层的日期。attempted但逐层登记表明目标仍未变且原依据有效可归unchanged_dates，不能因尾日失败丢前19日，也不能把未执行的后18日一律标无效。N按整批实际yield事件数，至多40，N=0不查；不匹配/伪造/坏授权报错。调用方更新完整凭据、保留unchanged_dates的有效结果，仅incomplete_dates排除verified_current_dates；历史任务仍整范围未完成，不能以统计状态缩减下次网络范围。

固定时序：

1. asset/op根据已解析用途进入对应流程。仅初始化入口首次加载原批准、计数及必要日记录；普通日更/repair不进入此分支。已读PG/事件、本地记录及依据都由主入口持有并复用。
2. T以及需要初始化统计的历史d，在本日最终Raw/Silver通过原文件检查、关系尚未释放时，调用共用calculate_stk_factor_pro_coverage一次。它只接当前Raw代码关系和coverage_inputs，输出固定七键calculated，不接原Prod计数、SourceComplete、approval、用途或DG引用。普通T的RawCoverage与初始化T统计共用该同一结果；普通历史不额外算初始化覆盖。
3. 初始化控制层若需保存非零明细，从本任务已持有的原日源及当前输入首次计算原合同input_digest，交诊断writer作为路径标识，不交给集合算法选择流程；后续直接复用。仅d=T时，普通RawCoverage与初始化记录共用run的diagnostics/day-missing-codes.parquet，extra沿day-extra-codes.parquet。d<T仅保存到原operation的coverage/<d>/input=<input_digest>/，creator_run_id=None；不生成run副本。0/未知不建附件，非零明细和样本各首取一次，沿现有身份归属和原子保存规则。
4. 本日小字典保留prepared、calculated、必要原导入事实及已有摘要，随后释放本日SQL关系。CurrentPublication不放入覆盖prepared/calculated，不先构造缺编号的DateCoverage；§18.2.1的computed_result只有在最终记录真正构造后才设置。
5. 日T按§4逐层保存物化/check，已有引用直接复用，不因统计再保存一次。历史d<T按原20日批末保存本批物化/check并首次取得真实引用；当天覆盖计算不等待此步骤。初始化控制层在该日期的实际事件已保存后，将原SourceComplete、approval_digest/已得input_digest、已有prepared/calculated和实际CurrentPublication显式交现有evaluate，纯构造最终DateCoverage；该函数不选择业务、不查PG/文件、不执行SQL，不重复计算摘要或统计。原source_rows/source_empty/source_complete_digest保持不变，当前行数来自本次两层audit。
6. 将最终result交update_after_publication/write保存；成功后替换同一内存日期贡献、更新合计。summary消费同一totals，版本未变不重复写；不打开全范围JSON/Raw/Silver、不重新准备或计算覆盖。
7. 任何写入失败都不回滚已发布文件、不自动重发网络。Raw-only或缺真实事件不能登记两层完整成功；收尾只用本次已知事实保留原错误，不回盘猜测。新run仍按原完整范围全新下载，首次重建必要的小记录账本，它不承担下载续跑。

#### 10.5.7 上线前补数首次加载、单日准备及一次覆盖的交接

本节补齐第五批控制层的具体编码约束，**只在上线前初始化补数及其重新执行/历史repair使用**。普通日更/repair的调用次数、初始化文件读取及导入summary更新均为0。物理bootstrap继续使用原完整月合同，不把单日伪装成完整月份、不改变原CoverageInputs的整月分类要求。

**准备当前日期的依据。**在既定readiness模块增加以下只读内部入口；将现有bootstrap coverage的_load_basis及其直接依赖的依据元信息/schema/业务规则读取部分移到同模块供两侧复用，不能复制两套读取器，也不能将operation批准/来源记录/统计writer移入readiness。现有月入口继续按原月日期调用这一读取能力，原行为和未知分类不变。

```python
def prepare_stk_factor_pro_coverage_inputs(
    connection, *, lake_root: Path, trade_date: date,
    inherited_facts: dict, known_records: dict,
) -> dict: ...

def prepare_stk_factor_pro_bootstrap_supplement_date(
    *, trade_date: date,
    raw_audit: StkFactorProFileAudit,
    silver_audit: StkFactorProFileAudit,
    coverage_inputs: dict,
) -> dict: ...

def evaluate_stk_factor_pro_bootstrap_coverage_date(
    *, prepared: Mapping[str, object], calculated: dict,
    approval_digest: str, input_digest: str,
    source_complete: StkFactorProBootstrapSourceComplete,
    current_publication: StkFactorProBootstrapCurrentPublication | None,
    previous_result: StkFactorProBootstrapDateCoverage | None,
) -> StkFactorProBootstrapDateCoverage: ...

def load_stk_factor_pro_bootstrap_supplement_state(
    *, staging_root: Path, approval: StkFactorProBootstrapApproval,
    approval_digest: str, approved_counts: Mapping[date, int],
    known_records: dict,
) -> dict: ...
```

第一个入口只首次取得日历、生命周期、身份映射和当前d的最终停牌事实。inherited_facts为同任务按实际路径保存的fact字典，fact沿现有basis/reason/relation/owned结构；优先接收历史prepare已读取的生命周期关系及已核schema/行数，坏依据同样复用未知事实，不能回读。返回键固定trade_date、is_open、basis_files、unknown_input_kinds、reason、relations；relations固定calendar/lifecycle/identity/suspend，非法或缺失者为None。全局关系留至最后消费者结束，当日停牌在该日覆盖小结果交出后由其创建者释放；继承关系不重复释放。一个日期不会因返回同月而再加载其停牌文件，不读取其他日期停牌。原T的准备结果及覆盖小结果留到任务收尾。

上述为已确认的新接口，本轮已同步迁移源码和全部直接消费者，不保留旧参数兼容。单日补数prepare放在原coverage模块，只从已得两层audit和单日coverage_inputs提取当前数据事实；不接approval、SourceComplete、previous_result、CurrentPublication或purpose。返回键固定为trade_date、raw_audit、silver_audit、raw_rows、silver_rows、raw_physical_code_count、raw_file_sha256、silver_file_sha256、is_open、basis_files、unknown_input_kinds、reason、relations。没有原源计数、DG引用、原导入授权或按用途选择的数量检查，不调用SQL/文件/PG。

原月prepare仍由原bootstrap控制层调用：入口已明确执行忠实导入/原源恢复时，核原源与原两层一致；仅核已有补数文件或本地统计时，沿已有正式文件及合法发布依据，不能用旧Prod源覆盖补数。共用只读依据及集合算法，源传输、授权和DG记录不合入通用准备。取消_prepare_stk_factor_pro_coverage_date_from_facts中混合原导入/补数规则的职责；需要保留私有提取函数时只能提取上列当前事实，不得接原源或事件对象来识别业务。

共用算法沿readiness.calculate_stk_factor_pro_coverage(connection, coverage_inputs=已有单日事实, raw_relation=现成Raw关系)，仍委托现有代码集合core，不复制两套SQL。原初始化compute函数仅编排这一次计算及非零诊断保存：保留connection/lake_root/staging_root/approval/prepared/raw_relation/diagnostic_run/check_space/known_records参数，新增显式input_digest用于诊断路径；不从prepared提取原SourceComplete或DG引用。approval只供诊断writer限定operation路径，不进入集合算法。input_digest按原合同只首次生成，不改变持久字段或摘要公式。

合法无文件分支由入口已有的完整空源或本轮成功空unit且正式两层不存在的事实明确确认，直接用空代码关系进入同一集合算法；不向要求两层文件的单日prepare或update_after_publication传None伪造audit。相应0实际/缺口result沿已有write保存，不造CurrentPublication或绿色check。缺文件但无完整空源/本轮空unit事实，仍是未知或失败，不能靠缺对象猜0。

已有有效覆盖结果的适用性在主入口首次核输入身份时确认；适用时仅提取已有计数、样本及明细作为同一calculated，跳过集合计算。原previous_result留给最终记录构造及保存，不传共用算法；后续DG记录编号更新只改变最终引用，不使相同输入再计算一次。

evaluate在本节仅表示现有最终记录构造函数：输入原SourceComplete/approval_digest、已得input_digest及本日prepared/calculated，DG事件保存后再显式传真实current_publication。它只组合字段、一次核日期/合同/处理版本/两层SHA及Silver来源Raw对应，不重新审计或算摘要。原bootstrap入口明确不产生正常DG事件时传None；合法无文件入口同样明确传None；初始化补数非空文件入口须传真实引用。该可空字段用于表达记录内容，不参与推断用途或选择数量规则。最终记录类型/parser保留字段结构校验，不在__post_init__中按该字段空/非空决定是否执行原Prod数量相等规则；源传输要求在所属入口执行。write/update只消费已构造结果及现有原记录身份，不再接两层audit或prepared重复同组关联检查。

**首次小记录加载。**load_stk_factor_pro_bootstrap_supplement_state放在bootstrap history控制模块，授权已经取得的approval及approved_counts直接传入；不调用bootstrap主入口、_execute、_classify_date或整月prepare。返回字典固定date_results、totals、previous_summary、previous_summary_digest。授权resolver将该字典保存在known_pg[("bootstrap_supplement",operation_id)]，补入同次已读取的approval、approval_digest和approved_counts；这只是任务内对象交接，不新增运行配置或持久缓存。N为批准自然日期数，A为本任务实际触及的批准交集日期数：

1. 通过现有read_json首次读取coverage/summary.json及每个批准日期固定coverage/<d>/result.json，解析本身结构、operation/approval/d及本日输入摘要；每个路径只取一次。只建立小记录账本，不展开所有差集附件、不查询各日期PG、不取所有Raw/Silver摘要或内容。合法无记录日期保留未知；日历确认休市且批准0行可保留合法无文件事实，不伪造result。
2. summary只供原物理导入完成事实及原记录索引使用；**当前覆盖合计不能从旧summary总数开始加减**。从本次实际读到的逐日小记录构造previous_contribution并首次累计一次。原source/raw/silver导入数量按已核全范围导入完成事实及批准日计数对应（原导入已要求三者相等）；当前两层/覆盖数量使用该日最后持久结果。result比summary新时以result为准；summary引用的result缺失/损坏则该日不算当前成功，原T首次授权若依赖此记录直接拒绝。不得把这次加载称为对全湖当前物理文件的重新审计；最终物理验收仍按批准流程独立执行。
3. 复用现有refresh_stk_factor_pro_bootstrap_date_contribution的贡献结构及增减算法。把其中应用original/current/known/sets/unknown/result_digest贡献的部分抽为唯一私有纯函数，旧刷新函数和首次小记录加载共同调用；不造虚假的SourceComplete/audit来迎合旧参数。未触及日期保存已持久结果及原贡献，不通过重新读取业务文件确认。已知先前失败使某日结果失效时先将其列未知；summary的current_files_unverified_dates只使evaluated_at不晚于该summary的旧result失效，日期result晚于summary时采用新result（日期保存成功、summary保存失败的正常分支）。缺少明确完成事实不能靠旧summary洗成成功。
4. 第一次实际处理某个批准日期前，再首次读其原SourceComplete和两层原导入complete小记录，校原来源摘要、批准计数和合法空源；原T授权已读的直接复用。补齐该日entry中原事实，其余字段沿§18.2.1。当前audit来自本次发布，CurrentPublication来自本任务真实事件；未发布日期不补读当前业务文件。此后update/write及异常收尾只用entry和totals，不回盘。
5. 本任务初始化小文件首次取得最多N+3+3A个不同路径：approval、批准计数、summary各1，日期result至多N，实际触及日期原SourceComplete及两层complete至多3A；缺失文件只登记缺失，实际文件读取更少。授权先取得的路径计在这个集合内，不再加一次。原T授权需要的非零缺失附件只首次核验该一份，历史更新需要的新明细另按实际非零输出计；不展开未触及日期附件。参数N/A取批准日期和实际工作，不另拍上限。原导入完整性不能由这些小记录确认时停止，回原维护流程处理，不在日任务里扩大为全历史审计。
6. 日期result保存成功才替换该日贡献；Raw已改变而Silver/统计失败时按§18.2.1退出旧有效贡献。summary继续使用同一totals，无读取/SQL/重新求和；写失败保留真实发布及原异常。新run只首次重建自己的小记录账本，日/历史源仍重新下载，账本不是下载续跑缓存。

**覆盖与记录的顺序。**计算只需当前数据，最终记录必须引用实际保存的执行事实；两者并不要求所有场景采用同一事件时点：

| 场景 | 具体顺序 |
| --- | --- |
| 原bootstrap忠实导入 | 原传输及两层文件检查→用现成Raw/依据计算一次→保存原导入覆盖记录/合计；不等待正常DG物化/check。 |
| 日T更新及初始化补日 | 沿§4逐层Raw发布/物化/check→Silver发布/物化/check；在本日关系释放前计算一次覆盖，T的RawCoverage与初始化T记录共用calculated。最终初始化记录复用已经取得的本日事件引用，不重新发送或查询。事件先发生并不构成集合算法的依赖。 |
| 初始化补数涉及的历史d<T | 每日Raw→Silver文件及原检查→一次覆盖/必要非零诊断→保留小结果并释放日关系；批末保存本批DG物化/check→用既有calculated及真实引用构造最终日期记录→保存并更新合计。 |

普通用途不调用初始化记录收尾。合法无文件沿已有专门分支，不造事件；身份未知、0缺口、0源、跨月回到原T、批末关系释放及记录写失败均作定向验收。完整文件处理、检查和统计只各自首次一次，不能为了统一时序再发事件或重复计算。

### 10.6 上线前从初始化导入到历史事件、自动化启用的条件

完整顺序固定为：忠实导入并记录缺口→完成批准范围物理及覆盖审计→管理员批准历史事件补录→补录并读回核对所有应有历史事件→管理员批准启用本数据集自动化。前一项未完成，不进入后一项；物理bootstrap函数不调用事件写入或sensor启用接口。这里把阶段衔接接上，不把后续正式事件/启用执行授权并入bootstrap批准。

| 阶段 | 必须已有的输入与通过条件 | 未通过时的动作 |
| --- | --- | --- |
| 物理bootstrap | 沿§10.1～10.5忠实导入；来源完整性、源到Raw及Raw到Silver261字段核对均有完整事实；合法Prod原缺口不阻止其余日期导入。 | 传输/文件错误按原规则停；市场缺口/依据未知记录在既有逐日统计和summary，合法已导入文件保留且可读。不因缺口删文件或自动补采。 |
| 批准范围完整性审计 | 同operation原导入事实完整；当前result/summary、文件/依据身份匹配，所有缺口/未知/当前不可核验日期为空且total_missing_count=0。原导入对账及当前两层check有效，允许当前数量不同于原source_rows；按本规则extra_count=0，不能以解释额外代码代替集合相等。另核本operation已产生的必要历史计划无未完成范围/未解除失败，完成或确实无历史的阶段事实有效。 | 缺失/未知/两层未完成、当前身份不符或必要历史未完均不放行。即使T已补齐、summary缺口0，后续历史失败仍阻止补绿/启用；复用已有阶段/plan/完整发布事实，不重算全历史。补数收尾更新现有统计，覆盖绿灯不冒充历史完成。 |
| 历史事件补录 | 引用上述同范围最新有效result/summary及当前正式文件身份；先做只读事件计划，列资产/分区、已存在、应补、冲突及精确写入上界，管理员另批后写入。补数任务已产生且与当前文件绑定的物化/check直接使用，只补仍缺失的合法事件；先物化后check。原源0但已补出数据的日期按当前文件处理，仍无文件日期不造事件。 | 有缺口/未知不补绿色；旧失败、旧文件或metadata冲突不能覆盖掩盖为通过，也不能因原source_rows少于当前数量而拒绝合法补数。写入失败保留已成功事件，按已核缺失清单继续并读回，不重导业务文件、不自动启用。 |
| 自动化启用 | 当前数据、同operation必要历史完成及事件补录三类依据都仍有效，全部应补事件已关联核对、无活动修复/发布。管理员按§4.2明确启用分区/日更sensor。 | 任一事件缺失/失败/绑定不明或补数必要历史pending/失败，均STOPPED；不能只凭文件存在、缺口0、run结束或summary已保存启用。 |

首次启用仍要求批准范围数据完整性、历史事件和绑定检查通过。日更sensor按§21只判断当天，本节不再提供上一交易日覆盖结论给sensor作放行条件。

事件阶段沿现有[性能治理§7](dagster-data-pipeline-performance-governance.md#7-dagster-event-与-runless-event-规则)使用有界批量读取/补录和写后核验；不在日常sensor逐日扫描历史。它的正式写入实现和执行清单必须在进入该阶段前完成独立审查和批准，物理bootstrap交付只输出可接用的文件及审计事实，不自行增加事件job、状态表或启用配置。事件补录及启用的必要验证为：物理导入成功但仍缺一股/有一个未知日期时均禁止补绿及启用；审计已过但少一个历史check时仍禁止启用；两者范围/身份均匹配且事件已完整读回后才可按批准启用。

管理员已确认：原来源及忠实导入4,800条、应有5,000条时，原导入证明继续记录4,800条；上线前初始化补数后当前Raw/Silver各5,000条、缺口0，由补数入口按§10.5.6直接更新同一operation当前结果及汇总。最终事件/启用条件读取这一最新有效结果，不再要求当前数量与原Prod来源相等；无需另外创建修复后审计入口。文件变化必须有合法发布/check依据，不能把任意改文件登记成补数。

最终只读事件计划须同时列出本operation关联的补数原T、已核授权/最近日与历史阶段引用及必要历史完成/未完状态。沿§6.2同Context记录和原plan/publication-complete核验；只有真实整范围成功及producer成功，或已检查输入且明确no_action，才可标历史已处理。没有发生补数的原导入不因此重算全历史因子；已知pending/失败/引用不明则停止。这里使用既有元数据，不增加状态表或审计入口；超过治理阈值时按授权run/阶段引用批量读取，避免每个历史分区重做readiness/数据扫描。具体事件写入实现仍按本节既有独立阶段方案/LLD批准，不将其混入本次物理导入函数。

### 10.7 开发阶段上线前初始化补数及重新执行

本节仅用于开发阶段上线前收尾，完成后不再用于上线后的普通日更或正式repair。复用同一个raw_tushare_stk_factor_pro_update_job、同一multi_asset和§2.4七字段配置，purpose=bootstrap_supplement；不另建job、sensor、命令平台、审批表或下载缓存。一次处理一个原bootstrap批准范围内的缺口交易日T，首次无需旧日更run，仍走完整日更新及必要复权历史。管理员按§4.2先停自动sensor、清空本数据集活动队列、明确批准本次执行；bootstrap批准记录用于限定来源和日期，不能替代本次正式网络/写湖授权。

#### 10.7.1 配置、日期与入口解析

```yaml
ops:
  stk_factor_pro:
    config:
      execution_day: "2026-10-25"
      target_trade_date: "2026-10-21"
      purpose: bootstrap_supplement
      scheduled_slot: null
      bootstrap_operation_id: "<已完成物理导入的operation标识>"
      expected_bootstrap_approval_digest: "<approval.json文件字节SHA-256>"
      expected_bootstrap_date_result_digest: "<coverage/2026-10-21/result.json文件字节SHA-256>"
```

执行时选择T对应分区。首次execution_day必须等于本次上海日期，允许周末；实际T仍必须是已确认且已注册的SSE开市日，P仍取T的严格前交易日。原生重执行保留原execution_day，不因已经隔日拒绝；本次实际开始时间另记。operation_id及两个摘要是本用途三项必填，自动用途全部None，类型/未知字段按§2.4封闭校验。示例不构成执行批准，不伪造原parent/root，也不将source_run_id或股票/日期数组加进此入口。

resolve_stk_factor_pro_bootstrap_context固定在既定defs/bootstrap/stk_factor_pro_history.py，复用本模块原operation/日期result读取，并调用readiness已有PG身份/原运行观察核验及纯覆盖函数。asset/op分别组合这两模块；依赖为asset/op→bootstrap→readiness→run_contracts，readiness不得import bootstrap，不能用局部import掩盖循环。纯统计函数仍不读instance；本授权resolver仅作有界PG元数据及本地记录读取，不改通用RunRequest或其他数据集。接口：

```python
def resolve_stk_factor_pro_bootstrap_context(
    instance: dg.DagsterInstance, connection: DuckDBPyConnection, *,
    lake_root: Path, staging_root: Path, current_run: dg.DagsterRun,
    run_input: StkFactorProRunInput, calendar: tuple[date, ...],
    known_pg: dict, known_records: dict,
) -> StkFactorProBootstrapContext | None: ...
```

普通today/manual_date由既有配置解析确认bootstrap三字段为None，asset不调用此resolver。仅明确执行开发阶段初始化补数，或其上线前重执行/repair时，才在§4.2活动任务检查及配置解析后调用本函数，按以下分支返回经核Context；无效身份或依据在名单保存、开始下载及任何正式写入前拒绝。不在helper里初始化instance、创建run、注册分区或更改approval。

#### 10.7.2 首次无parent的授权校验

1. 按paths.py生成固定operation根，核安全标识、approval文件字节SHA、完整结构和本数据集合同；只读原批准/原源与导入完成事实，不探测Prod、不要求原Prod维护窗口继续有效。原物理导入须全范围完成，含已证明源0日，import_pending_dates为空；当前市场仍有缺口是本入口用途，不要求all_expected_present=True或历史事件已补完。全范围原导入事实复用有效批准/汇总及原完成记录，只读小记录，不扫描全部261列或每个日期的事件。
2. T必须在原批准闭区间且有明确原导入完成事实；原源0日接受SourceComplete.actual_rows=approved_rows=0、原无文件的完整证明，不要求原本存在Raw/Silver。原导入半日/漏行/字段对账失败先按bootstrap原恢复处理，不能由补数伪造完成。
3. 读取固定coverage/<T>/result.json，字节SHA必须等于配置expected_bootstrap_date_result_digest；核operation/approval/T、原source_complete_digest、原导入事实。按§10.5核当前正式文件的原导入或合法补数依据、当前本地日历/生命周期/身份/停牌及完整缺失清单。必须coverage_complete=False、missing_count为正精确int、代码差集依据已知且清单行数/键/日期/摘要匹配；不能只看数量，不能拿未知或文件损坏冒充缺股票。
4. 结果已齐、依据过期/未知、摘要变化、错operation/日期或文件无有效依据均停止，给管理员具体文件/原因及“先刷新现有统计或处理依据，再按新摘要提交”的动作；不自动改配置、不就地换成另一份缺口授权。若日已齐但原补数历史/记录失败，提示重新执行原补数任务，而非伪造新的首次缺口。
5. 核原T/P股票复权因子Raw就绪及当前维护/唯一写入；按§5.1比较并保存完整变化名单。历史起点严格采用§5.1.1的统一规则及§5.1.2的完整范围判断：优先复用已有可信边界，无现成依据时对本次代码和已批准可信Raw日期作一次批量最早日期聚合，不截短、不猜起点。该规则同样适用于普通日更和repair，不只用于本入口。
6. 正式261字段技术因子网络请求前，把Context随既有“开始下载”AssetObservation保存并按§3.4读回；必须匹配当前run/T及以下完整字段。首次预检未通过时保存明确PRECHECK_NO_DOWNLOAD，不能写已经授权并开始。

StkFactorProBootstrapContext的完整字段以§10.5.4为准：operation_id、approval_digest、target_trade_date、authorized_date_result_digest、authorized_gap_input_digest、authorized_missing_count、authorized_missing_codes_ref、authorization_run_id。首次后三个依据从已核缺口result取得，authorization_run_id为本次实际保存首次授权观察的run_id；不存全部下载行，不复制日源或另建授权文件。开始观察本身的storage_id在保存后从真实记录取得，不放入自身payload形成循环引用；后续阶段观察完整保留同一Context。

#### 10.7.3 原生重执行及授权保留

直接parent和必要root必须同update job、终态、同T分区及解析后的相同七字段；首次root可以是bootstrap人工run，不要求自动日更run。先从parent开始/阶段观察读取Context，再按authorization_run_id精确读取首次授权观察；仅匹配goldenshare/download_started=True、producer run等于authorization_run_id且同T的唯一一条，后续带同Context的阶段观察不算。核原operation/approval/T、两个摘要、正缺失数及原缺失清单引用，该授权run还须同job/七字段。已缓存记录复用，最多核parent/root/明确授权run三条不同运行；原授权是该authorization_run的第一条开始下载观察；开始下载前允许有预检观察的run必须已经以PRECHECK_NO_DOWNLOAD终止，不能在同一run继续下载。用get_records_for_run(authorization_run_id, of_type=ASSET_OBSERVATION, limit=1, ascending=True)取实际首条，核download_started=True、producer、T及完整Context；不扫描该run全部观察。

有有效授权后，当前missing_count可以已为0，当前result字节SHA也可以因合法补数改变；不再将它们与首次配置SHA强行比较，不读一份已被替换的旧result作为本次源。仍核原approval、当前文件/依据、原T/P及同T未完成历史意图，保留已知完整原失败范围。每次完整重新下载T，历史符合门槛后重新下载所需原失败范围；只复用原授权/工作意图和已正式发布文件，不复用失败源或候选。

重新执行前不要求当前Raw/Silver已配齐或旧current_publication/result仍匹配，否则Raw已提升而Silver/记录失败会被错误拦截。按§7核本数据集已发布文件、原run的intent/完成或物化事实与当前SHA，合法单层提交也作为当前基础；replace后checkpoint未完成可用已核intent.expected身份确认已发生的写入，只读其元数据，不读取旧源/候选作新U。仍先做当前B必要物理校验，无法解释的外部改写拒绝；完整两层/check及新统计要求在本次重下T后重新建立。测试必须证明Raw完Silver失败、两层完统计失败后都确实进入新网络，而非在预检要求旧结果已齐。

若原run在授权保存前即以明确PRECHECK_NO_DOWNLOAD终止，允许当前run重核首次缺口/批准条件，authorization_run_id由真正首次保存者确定；parent/root及原七字段不变，即使隔日也不重新要求原execution_day等于现在，不将此原生重执行误当无parent的新申请。预检Context只表达意图，无download_started=True观察不算授权持久化；须区分明确未下载与已有开始标记却授权损坏。授权本应存在却缺失/损坏、是否下载无法判断或首次依据已变时停止，不猜作首次。管理员处理原因并取得有效新缺口后可明确新建首次请求，但仍完整满足§10.7.2，不领取旧失败部分下载进度。

#### 10.7.4 完整日更新与初始化统计

维护及唯一写入 → 七字段/原批准/缺口授权 → 目标T源端两列预检 → T/P权威股票复权因子及完整名单 → 当前261字段完整日源及候选代码严格相等 → Raw/Silver发布和检查 → 当前operation日统计 → 必要历史及每批统计。

预检不齐结束为真实等待，正式完整日源或候选不齐则首次提升前day失败。两种情况均未改变正式文件，原导入和当前覆盖统计仍保留原事实，不把源返回0替代已有Raw行数。正式文件已实际改变后发生事件、Silver或统计失败，按§10.5.6只保存可确认的真实层事实，不能宣告两层成功。普通异常和取消不回滚已提交文件，不以统计错误重发源请求。历史回刷仍只写d<T，阶段完成及失败整范围重下沿原规则执行。

#### 10.7.5 配置消费者、成本与验收

七字段均由run_contracts单处维护并持久化run_config，消费者为asset解析、source/Context核验、RunIdentity、开始/阶段观察、§6.2记录读取及repair继承；三项bootstrap字段无其他默认或运行时热改。Dagster原生parent/root/传感器身份沿原能力，不新增自定义run tags。开始观察保存小型授权计数和引用，PG不塞全部缺失代码或业务数据；原缺失清单仍在受控operation目录，当前缺失诊断按原run路径维护。

首次授权只核原完成小记录及T日文件/主键依据；原范围小记录遍历最多一次、本地输入同次按月复用。重执行额外至多三条精确run及各一次有界授权/阶段观察读取，不遍历运行史。日及历史下载请求、内存、磁盘/失败全范围重下、20日合并仍按§10原预算；追加的是当前日期主键统计、阶段/每批summary小记录和已产生事件配对，不能将这些省略为“零成本”。无不确定代码范围的全湖扫描、无Prod再审计、无新任务总请求预算。

最小隔离验收包括：无parent合法首次通过；错operation/approval/result SHA/T、0缺口/未知、原导入未成、未登记日期、自动用途携带bootstrap字段均在网络前拒绝；周末首次/隔日重执行通过；授权观察保存或读回失败零网络；首次授权后退出、Raw完Silver失败、日齐历史失败、result/summary失败均能沿同七字段原授权重执行并实际新下载，不要求旧两层已齐。T两层后立即记统计、历史失败不抹日事实；20日批第2日Raw内容已改变后失败时d1统计更新、d2当前不可核验、未触及d3～20原事实仍有效，整个历史仍失败并全范围重下。覆盖全0缺但必要历史失败时禁止最终补绿/启用；repair继承Context；普通旧配置无parent拒绝；人工纳入活动写入互斥；原4800→当前5000、原源0补出数据、重复不累加及已有事件不重复。均为隔离小样本，不构成正式执行批准。

## 11. 测试与验收要求

现行日更变更的逐项正反例、源合同核验、隔离串联和成本对账见§21.7。既有完整契约、数字转换、Raw/Silver逐文件原子提升、历史范围、复权比较、资源释放、Prod bootstrap忠实导入及来源/覆盖分开统计的测试继续各自验证。

日更必须覆盖源端缺码、多码、重复键、错日期、未知依据、两列分页完成、新股首日合法NULL、无原run的指定旧日补跑、探测后源变化时正式零发布、旧候选不可续用、清cursor不重复job。历史必须证明补旧T仍读T/P，回刷只写d<T，原自动追修和手动历史repair的授权及整范围重下生效。

### 11.1 已确认的最小验证安排

管理员已确认§10参数及以下精简验证安排。尽可能复用仍适用证据，用小样本证明关键边界；不以大范围反复跑数代替边界验证，不为5000行大小估算另读生产样本。参数拍板不表示测试或真实验收已经完成。

| 时机/内容 | 最小范围与证据要求 |
| --- | --- |
| 开发前来源确认 | 261字段、本地源文档及已有审计继续复用；第一批已按§14.4限定的一股五日、4次实际HTTP请求验证公开load及小页offset，固定HTTP交接的字段/参数证据已具备。后续优先复用保存的同一响应，不重复来源跑数；真实10000满页边界与全市场范围仍须区分。出现新差异先列额外最小范围、请求数和必要性，不自动扩大或把小页改成业务契约。 |
| 实现后日更读写/性能 | 重用同份获准真实响应，隔离做正常日更及同日补入各1次；分别记录正常/补入的两层读写、检查和最终对账成本。无历史正常日更与120秒目标比较；sensor单次评估与5秒目标比较。十个时点、60/600秒定义、去重、活动任务跳过使用模拟时钟/运行事实测试，不要求十次真实网络或十轮完整文件重写。 |
| 实现后历史读写/性能 | 一只股票、一个不超过20个交易日的临时样本批次，保留接近真实全市场宽度的日期文件，核无关股票不变；记录本批扫描/SQL/写入/峰值空间、失败后完整范围重新下载、当前正式合并及最后读回成本。结合可信日期/文件规模估算类似17股原完整历史，比较1200秒目标并明确外推局限；不默认跑17股完整历史，不把外推当成正式全范围已验收。批次1/20/21/41日等边界用小人工计划/临时数据，不为此扩真实历史范围。 |
| 实现后事件/恢复 | 同一套临时文件和独立临时instance，事件存储明确为§14.3的ConsolidatedSqliteEventLogStorage，目标T加两个历史日期核物化/check关联；网络可替换，事件真实落库并重开核持久。源未完整、源完整未发布、替换后未记完成、事件失败四个位置做有针对性恢复验证；至少一次真实进程退出后由新进程恢复，其他细分位置用有依据的隔离错误注入，不要求每点重复真实进程/来源跑数，不对真实源制造故障。验证完整源也重下、当前正式已提交保留、新源覆盖而旧候选绝不参与、repair原T缺失零网络及事件失败不回滚。该测试不证明正式PG的锁、队列及性能。 |
| 扩大范围的条件 | 小范围出现性能或语义差异，先说明具体问题及已有证据，提出额外最小验证范围；不自行扫描全湖、导出全历史或重复全量压测。正常、恢复、最终读回的成本分别记录，已有仍适用证据不反复重跑。 |

开工前明确范围、参数、成本及必要来源证据；业务完整发布/事件/恢复的运行验收在相应实现后隔离进行。不能要求尚未编码的完整链路现在已经运行通过，也不能因此省掉开工前设计/性能门禁。第一批来源和框架API验证见§14；本节完整业务读写、进程退出恢复及性能目标尚未验收，后续正式初始化及全范围验收仍须对应批准。

## 12. 已确认业务边界与工程核验

### 12.1 权威因子和源值

变化、原T/P修订及历史依据以`raw_tushare_adj_factor`为准。Raw/Silver保持技术源业务值。日发布及常规历史回刷记录技术行同名值的差异，已完成后的自动追修按§3.6核对可对照的差异。核对通过只说明未发现所核行的因子差异，源端指标仍以Tushare返回为准。权威因子缺必要值或范围不明时保留原因并停止对应历史。

### 12.2 原T Raw齐备及Silver有效是历史共同前置

历史前置以原T当前正式Raw覆盖原T应有代码集合、Silver有效且对应当前Raw为准。日更先按§21完成严格日源/候选校验及两层发布；历史repair只消费原T已有有效事实。全天停牌变化股可无T日技术因子行而继续其d<T历史。

Q日已齐仅历史失败可推进今天；原Q失败历史完整名单和范围保留，人工repair始终原T/原P，不以今天行或今天零变化抹掉旧意图。原范围内权威值修订可保存新依据，但不追加股票/延边界。历史失败重执行全新下载。

### 12.3 时间、Silver和重试范围

仅SSE开市日自动，19:00～23:30固定slot、午夜截止，自动只选当天；历史缺口人工指定日期。§2.4管理员已验证重新执行可跨原午夜，仍原T/P、全新下载并在同job继续必要历史；不放开自动窗口/次数。Silver本期261字段和对应行，仅日期DATE，每日期来自最终Raw，未来清洗不阻塞本期。Tushare失败/取消/退出后新下载，不删除正式数据；日下载只保留本次内存，无日下载中间文件或缓存复用。历史名单保存需要回刷的股票及起止日期，不是下载断点。历史漏原键为失败，自动日更可在下一允许slot重取原完整范围；手动repair失败后由管理员修正并再次手动执行，sensor不提交repair。下载器当前运行内同页有限重试与Prod bootstrap独立恢复不变。

### 12.4 编码与验收仍须逐项核验

| 落点 | 必须核验 |
| --- | --- |
| 自动配置/原任务 | §2.4七字段用途分支、parent/root及bootstrap授权只取意图、错run源拒绝；任何失败阶段新run均实际新下载。 |
| Raw历史前置 | §5.2覆盖结果三态/原T文件/check/生命周期/停牌身份；自动等待、repair固定失败消息及零网络/零嵌套。 |
| 原T Silver前置 | §4.1、§5.2.3：最新Silver物化/分区check绑定、正式文件/当前Raw SHA、契约处理版本；直接使用DG结果，Raw等价重物化可通过，不做全字段；失败固定提示/零网络/零提升，不能要求全部历史Silver先存在。 |
| repair四字段 | §4.1四项封闭配置、原完整授权、只d<T、缺日零网络、失败源再完整也重下。 |
| 发布与新执行 | §7～8只当前run新源/候选、当前正式B-K+U、逐文件intent/replace/fsync/readback、正式不回滚及缺原键诊断。 |
| sensor/事件 | §21的当前日持久提交及源端齐备读取、观察先持久后网络、失败阶段metadata；日物化后历史失败仍可读、历史check真实partition关联。 |
| bootstrap覆盖统计 | §10.5：函数/记录/SQL/读写时点、可信本地输入的机械核验、源0/日历未知、两层完成、代码差集、身份异常、摘要失效/重入和最终未知总数；不新增Prod审计或修复入口。 |
| 上线前初始化补数后的记录更新 | §10.5.4/§10.5.6：原传输事实与当前状态区分，真实物化/check事件storage_id、原空源补数、result/summary原子更新及不一致拒绝；仅重算受影响日期主键，原bootstrap恢复不覆盖补数结果。首次补数明确走§10.7的bootstrap_supplement授权分支，原生重执行及历史repair按已核Context继承。 |
| DG凭据与人工补日 | §2.4、§5.2、§6.2：原T人工跨午夜重执行、日齐后同job历史；直接读取绑定物化/check和阶段结果，输入未变不重复全字段/全历史对账；上次在生成回刷名单前失败，这次重新比较原T/P并生成本次名单。 |
| 历史失败和初始化顺序 | §6.1、§8.1、§10.6：历史少旧键waiting后抛Failure、自动下slot及手动不自动重试；完整性审计通过后历史事件，事件全部核对后才可另批准启用。 |
| 配置/性能 | §10单处常量和原资源；成本包括失败后全范围网络重取、当前正式文件合并/最终验收。bootstrap明确例外。 |

按§11.1分阶段补充验证证据；正式运行和写入另行取得批准。

## 13. 开发对账清单

| 管理员决定 | 方案与LLD落点 |
| --- | --- |
| 允许省略未执行输出但禁止局部调用 | §2.1/2.4/§4及§14.3：can_subset=True、两个skippable资产，固定job及入口精确核两资产/两检查；漏选下载前拒绝。PRECHECK_NO_DOWNLOAD只观察且SUCCESS，不伪造物化/check。 |
| 完整日源或候选不齐 | §21.5、§21.7，源返回0行或代码差集非空均在首次正式提升前失败。 |
| SQLite测试存储及证据边界 | §14.3：临时instance只覆盖ConsolidatedSqliteEventLogStorage，真实事件绑定及重开持久；不改PG、不混run/index id或弱化断言；首次5 failed保留，修订后14项已通过，见§14.3.3及第一批验收记录；本轮文档核对未重跑测试。 |
| 原失败任务不论阶段均重新下载 | §2.4、§5.3～5.4、§7～8、§11；不复用失败run旧源/候选，不按页/股/日期断点。 |
| 单日内存估算及对象释放 | 方案§10.1、LLD§5.4.1/§9.1/§10～11；完整日结果150～220MiB、阶段峰值约0.5～1GiB，先按约1GiB余量，不新增硬限；保留组件2GiB，当前结果/列/frame/U在正常和finally释放，不以RSS立即下降验收。 |
| 当日日下载不保存或复用中间文件 | §2.3、§4、§5.3～5.4、§6、§8～11；唯一完整日unit只在本次内存，最终summary成功后直接构造Raw发布候选；无source/day、日manifest/source-complete，日来源引用为null；历史及bootstrap各沿自身合同。 |
| 正式文件和证据保留 | §5.3、§7～8；当前正式文件是新合并基础，名单/授权/失败记录保留。 |
| 原T Raw齐备后才历史 | §4、§5.2、§8、§9、§11；应有代码集合判断；日更发布前完整日源和候选代码严格相等，历史按完整待处理范围执行。 |
| 原T Silver有效后才手动回刷 | §4.1、§5.2.3、§9、§11：原T Silver存在、有绑定通过check并对应当前Raw；失败提示管理员，不代补T数据；历史d可从刷新Raw生成缺失Silver。 |
| repair同门槛且缺日直接报错 | §4.1、§5.2、§11；原T缺/不齐/未知立即“原日期数据缺失”，无日下载/T窄查询/日发布调用。 |
| repair四必填 | §4.1；T/source_run/完整plan与ranges摘要；未知字段拒绝。 |
| 完整名单先于技术下载 | §1、§4～5；保留旧未完范围，T/P改回相同也不抹掉原意图。 |
| 日先历史后、两层逐日期更新 | §4、§8；先日Raw→Silver，再经齐备前置，历史逐d Raw→Silver，T不被历史写。 |
| 成功历史避免无故重复 | §5.4、§7；仅整范围成功、producer成功且输入有效，失败物理部分完成不冒充。 |
| 日期、时点及指定旧日 | §21，自动T=D，19:00～23:30固定slot和午夜截止；更早T人工指定，不挡今天。 |
| 合并、导出、资源及精简验证 | §8、§10～11；20日只合并组织，bootstrap5000独立；60/600秒sensor，16GB/4线程等原资源及5/120/1200秒目标保留。 |
| bootstrap过程中统计缺口 | 方案§7.3、LLD§10.5及§11：直接忠实导入后比较DG本地应有/实际集合；源原缺口不挡合法导入，同步漏行失败；全缺日、未知依据、按日期恢复及精确范围均记录。 |
| 补数收尾更新当前状态 | 方案§7.2～7.3、LLD§10.5.4～10.5.6及§10.6；原source/import保留，当前两层/覆盖/发布引用由上线前初始化补数更新，当前5000不必等于原4800；无独立修复后审计入口。 |
| 本轮已确认衔接 | §2.4、§5.2、§6.1～6.2、§8.1、§10.2～10.6、§11：人工原T日齐且日Silver检查通过即同job回刷；DG已有凭据直接读；上次在生成回刷名单前失败，这次重新比较原T/P并生成本次名单，失败下载仍全新；历史未全刷为FAILURE；月完整日同步交付及唯一记录；纯本地统计免Prod窗口；完整审计→全部历史事件→批准启用。 |

## 14. 第一批：契约与基础结构的编码及验收清单

本批按原方案§13.1的第一批实施，不将后续日发布、历史、bootstrap或自动化提前开工。目标是交付可以直接由第二批调用的真实契约、schema、输入解析和基础类型；不是建立空的下载/发布入口。本批完成前不得标记整个数据集已经接入。

### 14.1 已完成实现的依据

第一批已登记完整261字段源契约、两种下载模式、固定HTTP、路径及基本类型，并验证框架物化/check绑定和隔离事件存储。旧日更补采相关的规划和测试预期已删除；当前运行配置及日更验收统一见§21。第一批原计划和执行细节可从原提交追溯。

### 14.2 契约基线

完整261字段、版本、两种源下载模式、源类型转换及路径合同已由第一批实现。现行日更运行用途和发布条件见§21。

### 14.3 框架与事件隔离

第一批使用临时Dagster实例的ConsolidatedSqliteEventLogStorage核实际物化/check身份及重开持久。该证据不替代正式PostgreSQL或新日更准入验收。

#### 14.3.3 历史测试证据范围

当时首次5项失败作为原测试过程保留，修订后框架14项通过。旧日补采相关预期已退出现行设计，新规则按§21.7验证。

### 14.4 固定来源实测

2026-10-26固定000001.SZ及20261012～20261016共4次真实HTTP请求、0重试。完整261字段5行与limit=2、offset=0/2/4所得2/2/1行一致。只证明小页及该股票区间，满10,000行和新工程探测仍须分别验收。

### 14.5 后续验收

新日更以§21.7为准，正式阶段继续独立授权。

### 14.6 2026-10-26第一批实际验收

第一批当时的硬约束已逐项核实并记录[实现及证据对账](../../reports/stock_factor_pro_batch1_20261026/README.md)。定向合并回归281项通过（契约/既有下载器199、基础结构68、框架14），既有受影响回归159项主测试及513项子测试通过；受保护Definitions加载1项通过，真实调用project_defs/validate_loadable且无本数据集可执行入口。Python默认Ruff、本工程致命错误门禁及文档完整性通过。

框架按修订设计真实验证预检正常结束与成功请求0行但无日数据的业务失败，不伪造文件/check；分区、物化storage_id/run/timestamp及绑定检查均严格核对，关闭后重开同一临时instance仍成立。最终复核修正两处基础类型计数一致性：对账匹配/缺失/额外/变化须符合实际集合数量关系，诊断样本不能超过已知数量；只增加纯结构校验和回归，没有提前实现后批集合计算或PG读取。

§14.4固定来源范围实际4次发送、0重试：组件完整请求5行、261字段，小页2/2/1，主键并集无重叠且全部业务值一致；证据已保存，收尾不再次请求。真实10000行满页、全市场性能/内存、正式PG及业务发布链路未在本批验证；这些仍按对应后批完成。测试第一次遇到沙箱本机监听权限拒绝，核明原因后按获准权限运行同一组并通过，未修改断言或skip。

结论：第一批通过。其后第二批已另获批准并按§15完成验收；第三批、正式bootstrap、历史事件和自动化均未启动。第一批没有新增需要管理员拍板的业务设计问题。

## 15. 第二批：日下载、校验与发布的编码约束

### 15.1 当前实现与现行变更

第二批已实现当前run日源内存接收、261字段转换、Raw候选、Silver生成、唯一audit及逐文件发布。正式下载/候选/发布失败时新run全量重下。现有按键合并和bootstrap共用构造保持各自语义，新的日源及候选代码门槛按§21前移，不能继续使用旧的日覆盖不足时先发布规则。

### 15.4 候选路径与逐文件安全

既有候选路径须在写入前确认位于受控run staging内，符号链接反例及正常路径均有回归。新日更门槛不改变这项安全要求。

### 15.6 当前日更验收

按首日可选口径验收源端及发布前完整性，见§21.7，原批次通过数字仅属于历史代码基线。

### 15.7 2026-10-26第二批实际验收

本批已完成并通过：定向合并373项（第一批及既有组件281、本批新增92）、既有受影响159项及Definitions加载1项，共533项主测试；另518项子测试通过。默认Ruff、src/tests致命错误门禁及文档检查通过。实现位置、独立输入依据及正反例逐项见[第二批验收记录](../../reports/stock_factor_pro_batch2_20261026/README.md)。

公开load→本机HTTP→503后重试→日适配实际经过组件代码，三类标准通知及普通回调异常隔离验证通过，假token、2次本机请求、真实Tushare请求0。第一批五日已存响应按目标T筛出10月16日1行261字段，做正常及等价更新各一次，两层全部业务值逐项对应；成本原始记录列明SQL/逻辑文件读取/字节SHA读取、候选/原子写入、最终读回及清理，不能据此宣称全市场120秒或内存峰值达标。

正常两轮unit引用数回到基线，U及转换临时关系均已释放；失败/取消清表，不以RSS回落或强制GC作证明。独立子进程在Raw已发布后退出，新进程实际重新调用下载且最终Silver为新值，未接旧候选。原T旧未返行保留、Raw先交结果后才处理Silver、等价不replace、源成功0行不造文件、已发布不回滚及覆盖未知不伪0均已验证。发布后继承唯一候选audit的摘要/schema/行数，避免重复整套259列JOIN；记录日期/层/run物理路径、+08时刻、候选固定位置及挂载门槛有反向测试。

首次0源的完整缺失/阶段观察后业务Failure，含instance的readiness/覆盖复用及PG事件，仍由第五批落实；第三批、第四批当前完成状态见§16.4、§17.7，正式装配尚未实施。本批不存在新增需管理员拍板的业务设计问题，具备申请第三批条件，不自动推进。

### 15.8 提交后的独立审计（2026-10-26）

第二批已提交`5edb6409`，未push。发现§15.4的符号链接拒绝检查未在候选生成前落实：run目录下candidates子目录可指向外部，COPY先写出候选，发布函数随后才报错。1行临时样本已复现，正式文件未替换。本轮91项隔离回归通过，但既有根目录符号链接测试未覆盖该分支。该缺陷随后按本节修复，候选写入前检查覆盖Raw/Silver反例及正常run交接回归，再重新验收；不改变业务设计，不增加锁。本轮未修代码。完整依据与建议见[独立审计](../../reports/stock_factor_pro_batch2_20261026/independent-audit.md)。

### 15.9 第二批候选路径修复方案（2026-10-26，已批准）

目标是修正§15.8已复现的写入顺序错误：Raw/Silver候选的完整路径在首次目录创建和COPY之前就必须被拒绝，不能先写到符号链接指向的位置再报错。本轮只修改`io/stk_factor_pro_candidates.py`、`io/stk_factor_pro_publication.py`及对应候选/发布测试，报告同步原方案与本LLD；不改字段、下载模式、源配置、正式资产/任务或其他数据集，不开发第三批。

**依据及依赖：**CodeGraph与全仓引用搜索确认两个候选构造函数当前各只有日发布函数这个正式调用方，另有隔离测试替身；未装配PG/正式资产。现行`_safe`已有绝对路径、父级遍历、任意祖先符号链接及退役根拒绝规则，只需把它移为候选模块内`require_stk_factor_pro_safe_path(path:Path)->None`并由发布模块引用同一函数，不复制规则、不反向import发布模块、不新增通用平台或配置。

**内部接口及调用顺序：**

1. 新增`require_stk_factor_pro_candidate_path(*, candidate_path:Path, run_root:Path)->None`，对run_root及完整candidate_path使用上述同一安全函数，并要求candidate严格位于`run_root/candidates/`下、不是该目录本身；现存候选文件拒绝覆盖。日发布仍固定生成`candidates/day/raw/data.parquet`和`candidates/day/silver/data.parquet`，run_root只由当前RunIdentity及既定staging路径函数产生。这里不改变日目标和候选命名，也不通过resolve把非法链接转换为合法路径。
2. `build_stk_factor_pro_raw_candidate`与`build_stk_factor_pro_silver_candidate`均增加必填`run_root:Path`关键字参数，唯一正式调用方同步传当前run目录，不保留旧签名或缺省兜底。两个构造函数在执行候选SQL前先检查路径；已有计算完成后、mkdir前重检，mkdir后、COPY前再检。任何检查失败立即抛ValueError，不能继续COPY或记录intent。
3. 日发布入口在旧候选存在性判断前对两层固定候选路径作预检查；Raw交付后进入Silver时，候选构造函数仍独立重检，覆盖业务处理Raw结果期间出现的错误子目录。后续发布前的候选/目标校验、prior SHA、设备/空间及原子替换流程保留。
4. 允许先前步骤已经写入`history-plan`的普通run目录；拒绝越界、相对路径、`..`、存在或悬空的符号链接及旧日候选。检查只在当前任务路径上读取目录元信息，不扫描其他任务或全湖。

**读写、失败及性能边界：**正常仍只有T日内存源、两个候选/两个正式目标及既有逐文件记录，网络/SQL/数据行/候选数/正式写入数不增加；新增成本只是有限路径深度的元信息检查，单日固定两层。非法路径在候选写入前结束，预存Raw/Silver及前序名单不删不改；若Raw已经发布后才发现Silver路径异常，则保留Raw及其完成记录，Silver不生成，调用方finally清理内存。获准的新run按原规则重新下载，失败候选不复用；不引入锁、线程或并发修改目录的对抗性机制，不声称重复路径检查能提供多进程安全。最终验收复用1行261字段样本，失败重做与最终读回沿§15.6，无正式IO、无全量跑数。

**硬口径与验收映射：**

| 约束 | 代码落点 | 正向/反向验证 |
| --- | --- | --- |
| 首次候选mkdir/COPY前拒绝链接 | 共用路径检查及两候选函数 | 原复现：run下candidates指向外部空目录；报错且外部目录没有任何新增子目录/文件、正式测试目标0文件 |
| Raw/Silver均由构造函数保护，不只依赖入口 | 两候选函数必填run_root | 直接调用两函数，候选叶文件、层目录的已存在/悬空链接均在写前拒绝；外部文件内容保持不变 |
| 绑定当前run，禁止越界及旧候选 | candidate_path精确归属检查、发布固定路径 | 相对路径、`..`、其他run路径、已有候选拒绝，断言COPY未执行 |
| Raw先交付后Silver路径仍复核 | 日发布与Silver构造入口 | Raw yield后设置Silver子目录链接；下一次迭代拒绝，Raw内容及complete保留，链接指向处没有新增 |
| 正常目录不误拦 | 原run目录及日发布 | 存在history-plan仍正常生成两层，名单内容不改；既有合并、等价发布及失败新下载回归保留 |

先增加能在修复前暴露真实越界写入的反例并确认失败，再实施修复；本批四个离线测试文件（仅排除本机HTTP适配测试）及修改文件Ruff、全src/tests致命错误门禁、文档完整性执行一次。HTTP/组件协议未变，本轮不重复源请求；独立审计继续覆盖源生命周期、取消/清理、Raw→Silver、失败新下载、纯覆盖。通过后回填实际结果，未通过不恢复第三批条件。

### 15.10 路径修复后的验收与独立复核（2026-10-26）

§15.9已落实到两个候选/发布模块及两份测试，所有正式调用方同步必填run_root。原布局4项在修复前实际失败、修复后通过；18项直接builder反例明确先于任何SQL拒绝，1项history-plan普通目录正例保留，针对性合计23项通过。第二批四文件离线回归113项通过、1项本机HTTP适配明确未重复、23.22秒；默认Ruff、全src/tests致命错误及文档检查通过。没有新增skip、未改HTTP测试断言，HTTP代码及组件未变。

1行261字段读回仍正确，正常/等价更新0.5057/0.8806秒，52/70条SQL、候选各2份、正式替换2/0次，没有增加数据IO或源请求，不把该样本当全市场预算验收。修复前后完整输出与成本见[独立审计](../../reports/stock_factor_pro_batch2_20261026/independent-audit.md)及[path-fix-results.json](../../reports/stock_factor_pro_batch2_20261026/path-fix-results.json)。失败不写外部位置，Raw已完成而Silver失败仍保留Raw和complete；重试新run重新下载的原规则不变。

修复后独立只读复核全部调用方与写前检查，并复核本批源生命周期、取消/清理、两层合并发布、失败新下载及纯覆盖，未发现新的确证问题。CodeGraph修改前explore、修改后sync/status完成。§15.8的路径缺陷及验收暂停关闭，第二批具备申请第三批条件；本轮未提交、未push，没有正式执行，不自动推进第三批。

## 16. 第三批：历史回刷的编码约定与开工核验

### 16.1 目标、范围与现有代码依据

第三批只完成方案§13.1的复权变化名单、原完整范围、当前run完整历史源、20交易日合并及d<T的两层发布/完整范围依据。第一批契约及基础身份、第二批日转换/纯检查/取消/逐文件发布和路径修复直接复用；本节约定已按批准计划实现，实际验收见§16.4—16.5。接口调用和影响面已通过CodeGraph及实际源码核对。

`stk_factor_pro_http_rows`与`build_stk_factor_pro_raw_batch`复用完整261字段和标量转换；历史层另核任务规划的unit/code/start/end，不能仅凭result.unit自证。Raw候选在本数据集内抽出“已核单日关系＋实际处理日期”的共用构造，日入口仍接VerifiedDaySource，历史入口接本批临时表中的日期U；关系名由内部固定生成，不接受配置SQL。Silver候选复用verified_raw_relation/raw_audit/target_trade_date/run_root，本日全部消费者结束后统一清理expected关系。发布记录/解析器已按§5.4.3在同一实现扩phase/history和实际d，保留所有day字段互斥与路径反例，不复制另一套writer。

该共用构造固定为`build_stk_factor_pro_raw_candidate_from_relation(connection, *, source_relation, source_row_count, target_trade_date, prior_path, candidate_path, run_root, known_records)`。source_relation只允许本模块固定的DAY_SOURCE、HISTORY_DAY_SOURCE（stk_factor_pro_history_day_source）或BOOTSTRAP_DAY_SOURCE；bootstrap传首次确认的source_row_count且prior_path=None，处理日期必须为精确DATE；同用DAY_PRIOR、RAW_EXPECTED临时表和既有B−K+U/候选核验。日wrapper继续校验VerifiedDaySource，传入DAY_SOURCE和原T；历史调用者先从本批源表物化当日HISTORY_DAY_SOURCE，再显式传d。不接收外部SQL、任意关系名或较宽日期集合，候选写前路径检查保持不变。

不在本批实现bootstrap批准/导出/统计、正式PG结果读取、覆盖evaluator、job/repair装配、sensor/catalog/历史事件或正式执行；不修改公共下载器、Prod、已有数据集、配置来源，不新增状态平台、锁或线程。只为本批在原指定模块落实类型、函数与隔离测试。

### 16.2 完整接口、内部记录与后批分工

以下均为本数据集内部接口，不新增管理员输入。类型集中在`defs/run_contracts/stk_factor_pro.py`；已有RecordRef、RunIdentity、ContractIdentity、HistoryPlanReason、StkFactorProRawCoverage、StkFactorProTargetSilver、PublishedTarget直接复用。HistoryRange/HistoryPlanRecord/FactorFileRef/SourceCompleteRecord严格按§5.4闭合结构落实为冻结dataclass，不另维护一套字段表。新增的起点参数记录和历史资格记录只封装已有信息：

```python
@dataclass(frozen=True, slots=True)
class StkFactorProHistoryStart:
    ts_code: str
    start_date: date | None
    earliest_basis_kind: int | None  # 仅1/2，规则见§5.4.3
    earliest_basis_date: date | None

# HistoryEligibilityRecord精确对应§5.4.3 history-eligibility.json：
# record_version, identity, history_plan_digest, history_ranges_digest,
# raw_coverage, target_silver, evaluated_at。
# VerifiedSource承接当前run首次审计结果及元信息，不保存业务行、不序列化为新持久记录：
@dataclass(frozen=True, slots=True)
class VerifiedSource:
    identity: RunIdentity
    contract: ContractIdentity
    source_complete: SourceCompleteRecord
    source_complete_ref: RecordRef
    source_relation: str  # 当前主要连接持有的stk_factor_pro_history_source
    files: tuple[SourceFileRecord, ...]  # 当前run首次审计已完成的unit结果
    file_identities: tuple[tuple[str, tuple[int, int, int, int, int]], ...]
    # (受控相对路径, (st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns))，仅内存
```

StkFactorProHistoryStart来自§5.1.1真实记录读取/批量聚合，不新增存储；known start的三个日期/种类字段全有，start_date等于earliest_basis_date且不晚于T，未知时全None。重复代码、非法日期/kind或输入窄范围裁短原可信边界均拒绝。bootstrap读取/批准核验由既有初始化控制层提供已核内部记录；历史内核不import bootstrap执行器。

```python
def resolve_stk_factor_pro_history_starts(
    connection, *, lake_root: Path, target_trade_date: date,
    codes: tuple[str, ...], known_starts: tuple[StkFactorProHistoryStart, ...],
    approved_raw_dates: tuple[date, ...], check_cancel: Callable[[], None], known_records: dict,
) -> tuple[StkFactorProHistoryStart, ...]: ...

def build_stk_factor_pro_history_plan(
    connection, *, identity: RunIdentity, contract: ContractIdentity,
    lake_root: Path, staging_root: Path,
    factor_t: FactorFileRef, factor_p: FactorFileRef,
    factor_relations: tuple[str, str], lifecycle_relation: str | None,
    known_records: dict,
    prior_results: StkFactorProRecordedResults, prior_history: tuple[dict, Callable],
    history_starts: tuple[StkFactorProHistoryStart, ...],
    check_cancel: Callable[[], None],
) -> tuple[HistoryPlanRecord, tuple[HistoryRange, ...], RecordRef]: ...

def prepare_stk_factor_pro_history_inputs(connection, *, identity: RunIdentity,
    lake_root: Path, factor_t: FactorFileRef, factor_p: FactorFileRef,
    known_records: dict, check_cancel: Callable[[], None],
) -> tuple[tuple[str, str], str | None]: ...
def release_stk_factor_pro_history_inputs(connection, primary: BaseException | None = None) -> None: ...
def release_stk_factor_pro_history_source(connection, primary: BaseException | None = None) -> None: ...
def recheck_stk_factor_pro_history_inputs(connection, *, plan: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...], expected_units: tuple[UnitProjection, ...],
    lake_root: Path, recheck_inputs: Callable, known_records: dict,
) -> tuple[FactorFileRef, FactorFileRef, StkFactorProRawCoverage, StkFactorProTargetSilver]: ...

def resolve_stk_factor_pro_history_units(
    connection: DuckDBPyConnection, *, plan: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...],
    prior_results: StkFactorProRecordedResults, staging_root: Path,
    known_records: dict,
) -> tuple[UnitProjection, ...]: ...

def download_stk_factor_pro_history(
    connection, *, identity: RunIdentity, contract: ContractIdentity,
    plan: HistoryPlanRecord, ranges: tuple[HistoryRange, ...],
    plan_ref: RecordRef, known_records: dict,
    expected_units: tuple[UnitProjection, ...],
    prior_results: StkFactorProRecordedResults,
    eligibility: HistoryEligibilityRecord,
    lake_root: Path, staging_root: Path,
    recheck_inputs: Callable[[], tuple[
        FactorFileRef, FactorFileRef,
        StkFactorProRawCoverage, StkFactorProTargetSilver,
    ]],
    downloader=None, control=None, check_cancel: Callable[[], None],
    check_space: Callable[..., BootstrapSpaceEstimate], on_progress=None,
) -> VerifiedSource: ...

def publish_stk_factor_pro_history(
    connection, *, source: VerifiedSource, known_records: dict,
    plan: HistoryPlanRecord, ranges: tuple[HistoryRange, ...],
    lake_root: Path, staging_root: Path,
    calendar: tuple[date, ...], registered_dates: tuple[date, ...],
    publication_dates: tuple[date, ...],
    check_space: Callable[..., BootstrapSpaceEstimate],
    recheck_inputs: Callable[[], tuple[
        FactorFileRef, FactorFileRef,
        StkFactorProRawCoverage, StkFactorProTargetSilver,
    ]],
    check_cancel: Callable[[], None],
) -> Iterator[tuple[PublishedTarget, StkFactorProFileAudit | None]]: ...
```

此处列当前已实现签名；第五批按§10.5.6增加内部on_publish_attempt通知，用于控制层登记实际尝试日期，不能据此提前装配第五批。

`resolve_stk_factor_pro_history_starts`只聚合`known_starts`未解决的代码。`approved_raw_dates`由调用方按§19.12构造，传入本任务首次取得的、不晚于原T的可信Raw日期tuple。空集合进入既有未知分支。第五批按§19.12落实类型校验的复用和批量读取，保留单次主键聚合与§5.1.2的缺失处理。

`build...`直接消费入口首次确认T/P时取得的factor_relations、FactorFileRef及known_records中的摘要/身份；不重新打开两文件或再核同一schema/数值。变化比较首次执行一次，本runplan/ranges原子保存后直接交接。lifecycle_relation来自入口首次加载的正式silver_stock_lifecycle关系，名单原因6和后续覆盖共同使用；已确认不可用时为None并保留未知，helper不能因此另读一次或用当前上市快照替代。两因子及生命周期关系由控制层在本任务最后消费者完成后统一释放。prior_results严格采用§6.2完整冻结类型。确认无旧事实时传全None/空tuple的合法结果，查询失败或坏引用不能伪装为空。规划阶段允许保留未知行；下载阶段的入口核完整原待请求范围，未知或无实际工作不得启动session。正常编排按§5.1.2等待/no_action；若误调用下载函数则作为输入合同错误拒绝，不能返回伪造VerifiedSource。

`recheck_inputs`由第五批装配本run首次确认的四个实际结果及文件身份。下载前、首次历史提升前、整范围完成前三边界只比较元信息并返回原冻结结果，不重新读PG、hash全文、重建T/P表或计算覆盖。任一身份改变停止本轮，不保留“范围外变则重新比较后继续”的分支。新执行按新输入正常规划，跨run已独立成功范围的业务摘要复用规则不变。

`download...`必须核plan/ranges/plan_ref/eligibility属于当前run和原T、摘要相互匹配、Raw/Silver资格为真；控制层先从整份完整ranges及已有独立成功引用按§5.1.2调用unit resolver一次，返回expected_units并传download；download只核当前计划/范围身份及实际unit/股票/闭区间，不再调用resolver重算。每unit完整落盘/首次读回，将已得SQL行并入本任务历史总源关系后释放网络/Python对象，全部session成功退出、manifest逐项核验后写source-complete并调用§5.4.1 verify得到VerifiedSource。manifest的unit_key/file_relative_path精确采用§5.4.2/5.4.3，不依赖下载序号猜范围。一次失败不构造可交付的VerifiedSource，不隐式重试业务保存。

历史unit在同一连接固定HISTORY_CURRENT_UNIT完成确定转换，源文件首次保存后一次审计由require_factor_history_relation及传输对账完成。保存前只做必要解析，不重复完整关系审计；读回得到行数/schema及首次摘要后直接写SourceFileRecord。后续会话收尾、发布和最终完成均消费这份结果，不再全验源；清理和失败不产VerifiedSource规则不变。

unit成功保存/首次核验后，先把已得SQL行并入同连接stk_factor_pro_history_source，再逐项尝试删除读回临时表、删除当前unit表和解除DataFrame注册；一项失败不能跳过后两项。已有业务主错误时，将清理错误附到主错误后继续抛出主错误；正常收尾发生清理失败时则报告清理失败，不生成可发布的完整源结果。

`publish...`的on_publish_attempt仍为第五批可选内部接线；当前修正轮先使发布只消费本run首次已核源、完整manifest/范围及已有摘要，不再次完整verify源。缺原键只在非零时保存附件，0时ref=None；无文件日期skip_no_file/audit=None，不能造检查。每层原子提升后交付继承唯一候选audit的结果，完整范围收尾只汇总这些结果及既有摘要，不再次hash全部正式目标。第五批在yield点绑定真实DG事件并保存阶段结果，不能先list迭代器。

调用方必须在finally中明确关闭该迭代器，包含业务处理某个yield结果时抛错、取消或提前结束；不能等待垃圾回收。以下是第五批装配须遵守的控制结构，results为上述接口返回的迭代器，handle_result为业务逐层处理位置。若业务错误与close清理错误同时发生，继续抛最初业务错误，把清理错误附在其后；只有清理错误时才直接报告清理错误。普通contextlib.closing不能单独保证这一点。

```python
primary = None
try:
    for target, audit in results:
        handle_result(target, audit)
except BaseException as error:
    primary = error
    raise
finally:
    try:
        results.close()
    except BaseException as cleanup:
        if primary is None:
            raise
        primary.add_note(f"历史发布关闭同时失败：{type(cleanup).__name__}")
```

| 输入事实 | 第三批职责 | 对应后批职责 |
| --- | --- | --- |
| 权威T/P文件、可信每股起点 | 按现有schema/日期/范围和引用验证，比较/规划；缺依据保持未知 | 第四批可产生初始化依据，第五批从既有正式入口取得并准备输入，不改变起点规则 |
| 同T旧未完/完整成功事实 | 消费StkFactorProRecordedResults及精确引用，核原范围，不读失败源 | 第五批实现§6.2的有界PG读取与最终producer状态核验 |
| 原T Raw/Silver资格、开始事实及运行互斥 | 按类型/日期/指纹和现有require规则保护下载/发布 | 第五批正式evaluator/开始观察/互斥及事件装配；本批不加PG查询 |
| 日历与已登记日期 | 接受明确tuple，核源日期及d<T计划，不自动注册 | 第四/六批各自获准的注册流程，不因本批测试声明正式已注册 |

### 16.3 编码顺序、失败及资源边界

1. 在run_contracts落实上述历史类型、§5.4摘要和闭合读写验证；unit_key由同一函数供manifest写入及核验使用。
2. 在既定io/stk_factor_pro_history.py实现起点取得、T/P比较、原未完/成功范围核对及plan/ranges读写。未知、真新股、已有成功分别按§5.1.2，不用WHERE start_date IS NOT NULL掩盖未知。
3. 在既定io/stk_factor_pro_download.py实现当前run历史保存及VerifiedSource；源/manifest只位于本run/source/history，使用同一safe_path和该namespace归属规则，写目录/文件前检查，不能放宽candidates保护。
4. 在既定candidates/publication/checks模块内复用字段和合并/原子发布算法，按显式日期适配历史，落实§8.2.1批关系。原day入口仍只接VerifiedDaySource，原日路径/类型/0行及失败重下回归保留。
5. 实现范围publication-complete及原键差集汇总；文件完成事实只说明当前物理结果，producer最终成功由第五批使用DG事实确认。不提前伪造run成功。
6. 用小型真实schema夹具覆盖本节和§11；对照所有硬约束给代码、正反例和性能证据，第三批通过后才独立确认第四批，不开展正式执行。

沿§10现有连接和容量默认，不新增配置或请求预算。设需新下载C股、各H_i行、历史D个交易日，正常请求按§10的sum(floor(H_i/10000)+1)，失败新run同范围重下；本批同页重试沿组件，20日不改变请求数。当前run保存C个完整源unit及manifest，批源查询ceil(D/20)次、每批最多40个日期/层目标，当前日期B/U及两个候选之外不持有全部历史Python行；完整源、失败证据、批临时关系/受控spill、当前候选、读回和最终验收均计空间与耗时。源0行保留schema；半unit不交付。受控路径/空间/设备或输入无法确认时先停，不截字段/股票/日期，不静默删除旧源腾空间。

任何下载、保存、候选、文件或业务接收异常都关闭session/迭代器并在finally清表；Raw已发布Silver失败仍保留Raw，后续新run重新下载原完整失败范围，不能从第几个unit/日期/批次接续。取消前后行为继续按§6，replace后尽力收尾当前文件，下一文件前停止；错误定位使用既有业务类别及组件错误码，不新增随意字符串枚举。正式DG/PG/Prod/Lake操作及全局读取仍分别批准，本节的实现和隔离验收不替代正式执行授权。

### 16.4 启动条件和本批验收对账

| 启动/验收项 | 明确落点及必须证明的行为 |
| --- | --- |
| 前两批基础与路径修复 | 第一批0daf0b5e、第二批5edb6409及修复0e8b5baa；复用已提交证据，未改变时不重复真实来源跑数 |
| 历史起点没有新业务决策 | §5.1.1与§10.7.2同一规则；原可信更早边界不裁短、一次代码/日期有界MIN、未知不默认；所有入口适用 |
| 跨批输入可独立编码 | §16.2；第三批不依赖尚未实现的PG/导出执行器，已核冻结输入按现行schema夹具验证；查询失败不能由空输入代替 |
| 完整名单与下载范围 | §5.1.2；无变化、旧pending且因子回等、匹配独立成功、原因6、关键未知各有独立小样本；A/B有B未知时源请求/历史提升0，plan仍有B |
| 摘要/文件/记录生产者消费者一致 | unit_key准确封装、固定unit源路径、manifest逐项范围及字节SHA；换run/路径不改业务摘要，改code/边界/值必变；day/history来源互斥反例保留 |
| 当前源完整与关闭 | 每完整unit首次读回后保留SQL行、释放网络/Python对象；全部会话summary/关闭通过才形成当前runVerifiedSource，1304/错unit/错股票/超范围/旧run文件均零提升 |
| 按20日处理并保持其他数据 | §8.2.1与§11；1/20/21/41/45边界及源读取查询数、T边界、无关股票全部业务值不变、临时关系释放、Raw后Silver失败保留 |
| 缺原键及重入 | 先保存真实缺失，原键非0不得写完整记录；新run实际重下整个失败范围，旧源一旦作为输入读取测试立即失败 |
| 性能与证据范围 | §11.1规定的一股至多20日有界样本、宽日期文件与成本记录；复用已有来源响应，不做全市场/17股全历史压测；全市场/10000真实满页和正式PG事件验收未执行不写成通过 |

2026-10-26第三批已按管理员批准的七步顺序完成：历史类型和统一记录、起点/完整名单、实际unit与资格、完整源下载、20日逐日两层发布、缺旧键及范围完成、最终回归与独立审计。历史源verify已按批准补充必传connection，始终复用调用方连接；未修改公共下载器、源契约或其他数据集，未新增运行配置、连接、线程或正式入口。

本数据集530项及受保护Definitions/治理门禁126项，共656项通过。合并回归中两项因沙箱不能绑定本机假HTTP端口而失败，获得对应端口权限后，与另一个既有localhost用例合计3项补验通过；断言未删改，未遗留失败。Ruff默认及致命规则、文档完整性、差异空白和CodeGraph sync/status通过。2026-10-26该批验收未遗留业务决策；逐条实现及正反验收结论保留本节及§16.5，旧原始输出附件已清理。

保存的真实5行261字段响应经过实际组件registry/planner/session、历史保存和4个d<T的8个两层目标；一份5,568行旧Raw中的5,567只无关股票在两层全部业务字段保持一致，T文件不变。真实子进程在完整源及首Raw后退出，新进程重新请求原完整五日范围，旧源/候选读取护栏为0。源边界为已有响应和离线transport，资格为按真实结构构造的冻结输入；没有真实Tushare请求、正式PG查询或正式资源操作。

该次修正前成本记录包含最终范围收尾对2D目标补算SHA及小记录核验；当前§18明确删除这项额外全文读取，完成范围直接汇总已核事实。原SQL/空间/退出证据只证明当时小样本，不外推为全历史或新性能口径通过。

第三批通过隔离验收，具备制定第四批详细计划的条件；不自动推进第四批。bootstrap仍按§10独立批准、导出和恢复合同实施，不能套用Tushare失败重新下载规则或把本批固定单日期关系当作Prod导出入口。正式执行及自动化启用仍另行授权。

### 16.5 资源收尾

实际创建SQL关系、注册当前批对象、打开游标/事务的函数负责finally收尾；历史总源关系由任务入口在历史全部消费者完成或失败时统一释放。本日关系在必要覆盖/scope完成并把小结果交出后释放，事件和统计包装只用小结果；不由中间helper提前清理后迫使下一步重读。无源表/关系的轻量输入比较不创建清理动作。

业务异常优先保留，收尾异常附后；正常路径只有收尾失败时报告该失败。取消/进程退出、真实I/O失败按原流程处理，不靠清理重试、另开连接或重读输入掩盖问题。测试只对实际创建资源处做代表性异常，不要求人为改写内部U或因子来强迫轻量步骤创建关系。

### 16.6 旧过程附件清理与测试输出位置（2026-11-03）

对应方案16节。先将四组旧报告的有效结论留在各原方案/LLD，删除外部引用，再移除本次盘点的52份附件；本步不是重新审计或重跑数据。只涉及管理员点名的四目录、直接引用它们的七份原设计文档、根AGENTS及下述一个测试文件；其他脏文件保留。

当前代码依据：`tests/test_stk_factor_pro_history_integration.py`的全局`REPORT`指向本工程reports，`evidence(section,value)`读取并合并旧JSON，再写回；它是输出收集器，不是输入夹具。正常链和真实进程退出/新进程重下两个测试调用它；真实输入仍由`stk_factor_pro_history_test_support.saved_real_rows()`提供。生产源码没有引用这四组报告。

删除全局REPORT常量；改为`evidence(output_dir,section,value)`，仅向`output_dir / 'integration-evidence.json'`写入，两个原调用均显式传本测试`tmp_path`。其余字段、Metrics、业务断言、子进程exit/recover临时文件和原超时均保持。测试可生成必要结果供本次排查，但不能再写工程目录，也不引入env开关、旧路径兜底或新的长期附件。

验收只跑该文件原两个隔离测试，覆盖正常下载/发布和真实退出/新进程重下；不改断言。全部工作资源及pytest缓存放本任务`/private/tmp`目录，沿现有测试支持连接与离线transport，禁止正式资源和网络。预计测试30秒、临时峰值64MiB；失败只保留本轮排查材料，不删无关文件、不自动运行其他数据链，修正后只补必要验证。通过后只汇总已生成结果，删除测试目录及四组旧附件，核验旧目录均不存在、活动路径引用为0。没有数据重读、正式写入、安装或提交动作。

实际收尾：原两项测试通过（11.93秒），AST核对38处原断言全部保留；Ruff通过。删除前确认52份文件与盘点身份均未变化，随后四目录共52份、943,659B全部删除；仅原方案16节保留删除范围说明，不再有链接或代码依赖。有效历史结论已回填各原方案/LLD，文档完整性及本次相对链接检查通过。本轮自有测试/整理临时目录随收尾删除；未改生产逻辑或正式数据，未提交。


## 17. 第四批编码约束与逐步验收

2026-10-26管理员批准方案§13.6的八步开发。本节保留该批编码约束及已有实现依据；主体实现及§17.8五项修复现均已实现并完成隔离验收，正式操作未执行。§9～11全部合同继续生效；不修改公共下载器、261字段源契约、Prod实现或其他数据集。

### 17.1 代码结构与依赖

对外接口保持在`defs/bootstrap/stk_factor_pro_history.py`，负责唯一入口、依赖绑定及重导出§10既定函数。同目录私有实现按稳定职责分为`stk_factor_pro_bootstrap_records.py`（批准/路径引用/记录与摘要）、`stk_factor_pro_bootstrap_source.py`（月规划、来源预检、游标及完整日）、`stk_factor_pro_bootstrap_publication.py`（候选/逐文件恢复）、`stk_factor_pro_bootstrap_coverage.py`（本地依据、日期统计、summary和补数更新）。它们不是新增运行入口；不新增子目录、CLI、job、sensor、check或配置。公共冻结类型仍统一在run_contracts/stk_factor_pro.py，受控路径统一在paths.py。依赖单向：入口调用各实现；source/publication/coverage可依赖records和既有纯IO/check/contract；records不得反向导入入口或后三模块。日更/历史IO不得import bootstrap。

新增固定内部单日关系`BOOTSTRAP_DAY_SOURCE`供共用Raw候选构造使用；该来源必须prior_path=None，只生成完整源U，不做正式旧文件合并。DAY_SOURCE/HISTORY_DAY_SOURCE现行行为不变，日入口仍要求VerifiedDaySource。首次候选创建继续使用既有禁止覆盖检查；bootstrap恢复自行核既存候选及原intent，不能放宽公共候选保护。

### 17.2 合同、路径与读写

严格落实§10所有frozen类型及已有类型复用。完整FileAudit的Path显式转文本再读回Path；正式path由日期/层复算，diagnostics仅允许本operation受控位置。不可变approval/source-complete/intent/complete首次取得后持有对象及摘要，相同内容直接复用、不再回读或重写，不同内容拒绝；result/summary按§10原子替换。JSON拒绝重复键、未知/缺字段、bool冒充计数、非法ISO日期/时区、坏摘要及引用。不存在固定记录才返回None，损坏不伪装成未完成。文件字节SHA、业务内容SHA与各kind摘要按原精确投影计算，不新造hash算法，不将operation伪装成run。

### 17.3 顺序、来源读取与失败

主流程只接受受控operation标识及现有resource/instance内部依赖，读取固定approval；不接受根目录、表、字段、SQL、overwrite、模式开关或运营传入的passed/event id。正式根由现有资源/默认路径解析；隔离测试通过内部依赖使用临时目录。入口拥有唯一主要DuckDB连接，helper只借用并释放自身关系。

1. 入口先核§4.2活动任务，再读回批准、计数、来源证据与日完成事实；核实际剩余工作，不按summary自称完成跳过核验。
2. 月规划完整覆盖批准源首尾全部自然日期，含0源日、退市股票及2020前数据；selected_dates仅扣同operation已核完整日期。
3. 终端bootstrap继续使用§4.2五状态reader，入口和首次提升前各一次，own_run_id=None。该行为不是第五批正常队列job的接线模板；第五批只保留入口核验并排除纯排队冲突，不加首次提升前二查。
4. bootstrap注册原批准范围中已确认SSE开市日，包括源0开市日；只新增，不删除，不注册休市/未知。这不是第六批日常注册sensor，正式分区写入仍独立批准。
5. 每月借现有只读事务，control cursor设置绑定timeout，named cursor固定without hold及5000批量；显式261列、闭开月范围、DATE数组及R+1。不fetchall、不offset、不普通cursor取明细、不累计整月，不更改resource。
6. 每批先核R+1/字段/日期/严格键序，保存/首次读回后把已核SQL行交当前日及跨日批关系，仅释放Python转换对象；只有下一日期或真实EOF关闭日期。遇R+1的当前批在写片段及回调前拒绝，此前完整日期保留。EOF复核selected各日及合计计数，源0也必须有EOF证明。
7. 完整日记录原子保存成功并直接交接后，同线程同连接同步process；真实回调异常立即停止fetch；已分类的坏覆盖依据正常返回未知，不属于异常。Raw/Silver完成后才统计；半日不发布，0源无旧文件不造空业务文件。
8. 收尾逐个尝试关闭named/control cursor及事务，再释放主要DuckDB；保留业务/取消原始异常，关闭异常作为附注；仅关闭失败时任务失败。现有resource退出若另抛异常，由本数据集局部包装保留原异常，不改公共resource。

### 17.4 发布与恢复的准确分支

完整源首次审计事实→新候选首次完整审计及固定摘要→描述/intent引用该结果→仅终端bootstrap首次维护核验及轻量身份/空间比较→原子replace或等价reuse→继承audit保存complete。正常路径没有描述后/意图前/提升前反复全文件SHA，也没有提升后的schema/count/261列复审；新执行恢复按§18.3仅首次确认所需产物一次，不改prior/expected。

新执行恢复按§10.4：对缺少本次事实的实际产物首次确认一次，已有audit/摘要则直接补complete，不额外重建expected或重复审计。目标prior分支仍须原意图和候选有效；目标冲突停止。Raw已完成则沿其既有结果生成新Silver候选，不能重新审计同一Raw。

半日失败整日重读；完整日源可复用；记录不得覆盖旧attempt片段。需要来源或业务文件恢复时核原维护窗口；仅统计不访问Prod，窗口过期不阻拦。未知改写、缺文件或缺合法补数凭据时停止，不自动改为旧Prod恢复。统计失败不回滚已发布文件。上述仅bootstrap适用，Tushare日更/历史失败始终新下载。

### 17.5 覆盖、补数及后批交接

prepare/evaluate/write/summarize按§10.5实现，已有首次审计事实直接交接，覆盖仍只计算实际变化日期的必要代码集合一次。summary直接消费本次已维护合计，不读小记录、不重算、不因同批收尾读全范围Raw/Silver。全局依据按既有月窗口复用，未知分类及原传输/当前数量分工不变；具体改动按§18.2。

完整明细先写、JSON后写；summary使用本任务已经维护的日期账本及合计，不累加，不把未知报为0。原传输与当前补数状态分开，统计失败不回滚。正常最后不再prepare/局部复算；处理期间输入变化停止，下一获准执行才准备新输入。

第四批历史验收使用真实临时文件audit及来源明确的发布输入，不代表正式DG事件读取已验收。后续代码以§19.11为准：已有补数文件被读取作为基础时，首次核合法发布/check及文件身份，不从JSON编号猜passed；本次新文件通过原文件检查后即可计算覆盖，不等待事件。DG引用只在最终记录构造中与同任务已得audit对应一次，update/write只保存结果。原导入传输要求留原入口，新补数原/当前数量分别记录；不新增audit状态文件、空reader或独立绑定接口。

### 17.6 逐步验收与成本

按方案八步分别测试后继续。合同/路径/摘要先验收；再测月规划和活动/分区；再测游标；再测两层恢复；再测覆盖/补数；最后串联及独立审计。每项硬口径对账代码、正反测试及证据。测试覆盖§10.4/10.5.5/10.5.6全表，并包括0/4999/5000/5001、跨批同日/同批多日、R−1/R/R+1、未知/合法0停牌、原源0补出、重复补数、统计失败、窗口过期、目标改写、双重清理异常。至少一次真实子进程退出后同operation恢复；已完整日期零重复远程明细，半日整日重读。

资源沿原5000行约9.94MiB净字段、128MiB估算/256MiB余量及单主要DuckDB设置，无新硬限。分别计正常、半日重读、完整源复用、本地统计及最终验收的查询、Parquet/SHA读取、记录/候选/提升数量、临时关系、峰值空间及耗时；月计数/EOF也计入，不能宣称全程序只读一次。summary消费本任务已维护的合计，零业务/JSON读取、零重新求和。Prod类型复用既有schema/有界证据，HTTP样本不冒充PG游标实测，不新增真实源请求或5000行压测。

只用临时文件、隔离DuckDB/instance及模拟Prod；受保护测试走既有runner。默认Ruff、本项目致命规则、文档/空白检查及CodeGraph核验通过后独立审计。正式PG、全量bootstrap、分区写入、事件补录均未执行；第四批通过不自动推进第五批。

§17编码补充：export/preflight的staging_root是主入口传入的内部依赖，正式入口不暴露根路径；正常export在同月事务内完成预检，不由入口重复开连接。日历BasisFile.valid只表达文件级可读/schema/身份稳定及不可归属坏行检查；可归属某日的缺失、重复或空开市标志按unknown_by_date仅使对应日未知，不能把无关日期一起置未知。其他三类依据仍执行完整物理规则。全局三类依据的已载入身份允许保存在同连接TEMP小表以复用，随连接释放，不持久化或新增配置。最终停牌非空timing按现行producer保留为盘中，不新增时间格式正则；producer本应转为NULL的空白最终timing列依据异常未知，不推定全天停牌。

§17来源与校验补充：非零日期随游标确认完整后即时处理；源0日期只能真实EOF后确认，因此EOF阶段把待处理末非零日与零日合并升序，不承诺含源0月份的全月回调绝对升序。bootstrap只核四类正式输入文件的消费物理规则；identity producer的seed_latest_code_explainable检查的是仓库种子最新码是否出现在生命周期，不检查本次映射行，本批不引入种子作为第五类统计依据、不修改该正式上游check。

§17清理审计补充：第四批复用的audit_stk_factor_pro_file原finally直接DROP VIEW，若主体字段检查已失败且DROP也失败会掩盖原始错误。本批在同一本数据集纯检查函数保留主体异常并附注清理错误，仅清理失败时仍失败；增加真实临时缺列文件与DROP失败的回归，不变更检查规则或其他数据集。


### 17.7 第四批实际验收与后批条件

2026-10-27当前验收：提交28b7894a后的三处补齐已完成，进度18、空间接线12、空间纯预算58、bootstrap入口9及真实进程恢复1，共98项不同用例通过；最后观察边界补验1项与前述重叠不累计。14处已实现固定接口AST对照一致，独立审计未发现新的确定问题；默认Ruff、全src/tests致命规则、CodeGraph同步、文档/局部链接及差异检查通过。具体证据见§17.8.7和[当前验收](../../reports/stock_factor_pro_batch4_20261026/README.md)。此前868项普通回归及126项受保护门禁，共994项，保留为五项主体修复阶段证据；本轮未重跑完整994或受保护门禁，不将旧摘要冒充当前改动的全套验证。

以下保留2026-10-26原主体测试证据，不作为五项修复的当前结论。

2026-10-26原八步主体开发已提交。以下是五项独立审计修正前的历史测试结果，不证明§17.8修复已完成：最终明确文件清单的整批回归731项通过；新增真实临时DagsterInstance分区注册用例通过（入口文件9项重测通过，其中8项已含整批），独立不同数据集用例共732项。受保护Definitions/资产治理/静态合同仍走原runner，分别1/12/113项通过，合计858项不同用例。没有通过skip/修改预期绕过错误；初次批量命令错误包含受保护Definitions，已按正确入口重测，原执行记录保留。

真实进程在Raw完成、Silver前退出后，新进程同operation恢复：Prod仅5条控制查询、0明细SELECT/0fetch，原完整源和Raw的SHA/mtime不变；第三进程在来源窗口到期、无Prod凭据时，仅本地统计通过。真实临时instance验证只新增已知开市日（含源0），不删除旧键、不注册未知，重复执行键集合不变。纯覆盖计数证明首次日期集合1次、未变重执行0次，result不替换；summary只重写自身，不累加。

独立审计与14项专项反例已核发布Raw绑定、空源身份、诊断相对路径、complete业务摘要/行数和共享audit双异常。月份关系finally释放，全局身份缓存不随批准历史扩大；这些是该次既有修复的证据。随后独立审计发现的§17.8五项问题已于2026-10-27修复并完成针对性回归和独立复核；不能用原858项替代当前验收。完整成本/测试/逐项对账见[第四批验收](../../reports/stock_factor_pro_batch4_20261026/README.md)。报告明确SQL/SHA与真实物理扫描的区别、小样本观测空间与估算边界，不能外推为全源性能已通过。

2026-10-27五项修复、针对性回归及独立对账完成，第四批通过隔离验收；未推进第五批，不将本轮验收视作正式执行授权。第五批须落实真实DG物化/check及完成结果读取、开始授权/BootstrapContext、日更和历史repair装配、首次人工补数及事件持久后调用统计更新。第四批没有空reader占位，也没有提前接正式Definitions；正式Prod范围/窗口/月R/timeout和磁盘、正式写入/分区/事件仍各自批准。本批提交不包含正式执行，不自动推进第五批。

### 17.8 五项审计修正的编码与验收要求

本节五项已获管理员批准，并于2026-10-27按顺序完成实现、回归及独立复核，是§10及§17相应步骤的现行约束。原批准结构、JSON版本/摘要算法、5000行批量、单主要连接及既有资源参数保持不变。不新增CLI、配置、状态表、跨进程缓存、线程或锁；不改公共下载器及其他数据集。修复时先核以下对应的当前代码，再按本节修改并逐项测试。

#### 17.8.1 唯一候选audit及原摘要直接交接

候选描述、发布意图和完成记录绑定同一candidate_audit及其摘要。新执行规则为：候选首次完整审计产生不可变audit、字节/业务摘要及文件身份；fragment描述、intent/expected均引用同一份结果，不重新取SHA。后续只核已有归属/摘要引用及必要元信息，真实I/O错误继续传播。

正常原子提升后继承audit形成正式完成事实，不再schema/count/全字段对账。新执行恢复按§10.4/§18.4对实际需要的产物首次确认一次，不能重设prior/expected。终端bootstrap维护核验保留，但不为此重审候选。

验收只要求首次audit与intent/complete摘要绑定一致、描述函数不换摘要、原子提升失败不生成complete、正常首次和等价reuse及原intent恢复可用。真实外部坏源、I/O和原始身份绑定反例仍保留；不以反复改写内部已核文件为由要求各层重读。本项已在§18修正轮实现并验收，结果见§18.8。

#### 17.8.2 空间预算、检查时点及中断处理

**位置及接口。**`stk_factor_pro_history.py`入口负责依据批准日计数和当前已核完成事实准备剩余工作；在本数据集既有bootstrap模块内提供纯内部`estimate_bootstrap_space(...)`及`require_bootstrap_space(...)`，不暴露新运营参数、不改变approval。前者返回按用途区分的字节估算，后者只读路径元信息/`shutil.disk_usage`，按设备核free，不创建测试文件测容量。 临时目录只读当前主要连接的`SELECT current_setting('temp_directory')`，不执行SET、不硬编码另一条路径；API依据[DuckDB配置读取](https://duckdb.org/docs/current/configuration/overview.html)。source、publication及统计写入借用入口绑定的同一空间检查函数；直接调用这些内部写入口的测试也必须提供检查依赖，不能绕过检查。

估算输入固定为：批准记录及已核按日计数、当前operation/attempt、实际剩余日期、已保存且可复用的源引用、当前待写批行数、本日Raw/Silver预计行数、当前步骤及正式/staging/DuckDB临时路径。行数只能来自批准计数、已核片段或当前连接关系的已得计数，不能为估算重读Prod明细或扫描正式全历史。每月`sum(selected_date_counts) <= R`仍独立核验，R不是磁盘字节数。 候选新增量在入口按未满足文件数和总行数维护递增/递减计数，传纯预算函数计算同一公式，不在每次边界重遍历全范围日期；JSON已占字节按日期分组增量维护；最后只切换summary预算，直接使用已维护合计，不重开统计范围或再次汇总日期。 入口一次建立月份日期索引，无指定单日的批次检查仅遍历本月最多31日；入口首次取得必要最大工作量，后续包括最终summary仅复用，不重新遍历全范围。它们只替代重复的元信息遍历，不改变S/C_new/C_work/T/J算法，不持久化、不增加配置。

初值按以下固定内部算法估算，集中在上述纯函数中维护并用字面小样本核算；这些是保守空间估算，不是新增配置、Parquet大小上限或能够保证外部磁盘永不被占用的承诺：

- Prod净行宽仍为`9 + 4 + 259*8 = 2085 B`，5000行约9.94MiB。落盘Raw日期为8字符，按较大值`W = 9 + 8 + 259*8 = 2089 B`同时估计两层。单个新文件估算`P(n) = 2*W*n + 4 MiB`（n>0）；确认不生成文件时为0。系数2与每文件4MiB用于编码、页和元数据余量，不假定压缩节省；不得把2085 B当成实际Parquet行宽或内存对象大小。
- 新增保留源预算S：对批准范围内全部仍需导出的日期，按其所在月合计n，分为5000行片段，累加每片`P(min(5000, remaining_rows))`。当前attempt以其开始时固定selected_dates的批准计数减该attempt已读回保存的行数计算尚需行数，已核完整日期只在确定selected_dates时排除一次；若按动态剩余日期重新计算，则只能减这些日期对应的已保存行，禁止再减整个attempt行数。例如A/B各5000行，A已排除后n=5000，不能再减A的5000行。尚未开始月份只排除已核完整日期；换attempt重读半日时，旧半日片段不可复用，不从新attempt尚需行数中扣减，旧文件仍占用磁盘，不删除腾空间。尚未执行的后续月份也计入S，避免只给当前批留空间而忽略源文件一直保留。
- 尚需留存的候选/正式数据预算C_new：对全部剩余日期、两层逐项累加尚需新增的`P(rows)`。首次无目标时候选replace只是同设备改名，这份候选/最终文件只算一次；已有可复用候选覆盖其对应最终文件需求时也只算一次，不能既扣候选又扣目标。正式文件或可复用候选已落盘的对应需求只扣一次且不小于0，不按路径存在便扣减；同一条需求已由现有文件满足后不再进入剩余项。reuse分支若仍须新建候选而正式目标已存在，另计新候选且不减旧目标占用。已有不同内容目标/坏候选仍按冲突规则停止，不删除重建。全部剩余日期的最终文件会累积，不能用“最大一日候选”代替其新增总量。
- 临时计算预算T：先独立计算本日工作量`C_work=P(raw_rows)+P(silver_rows)`，月开始尚未选本日时取待处理日期中最大值，不因文件已落盘而扣减；再取`T=4*(P(min(5000,本月尚需新读行数))+C_work)`，覆盖当前批转换、单日关系、两层读回及覆盖差集余量。完整源恢复无新批时首项为0，但仍要核两层读回工作量。只有本地统计时不新增两层数据文件，C_new=0，T按待统计日最大`4*P(raw_rows)`估算。不能将C_new=0误认为无需临时计算空间，不把整月业务行物化，也不把512GB spill上限当可用或必须预留512GB。无法由既有计数确定工作量时停止说明缺少哪项依据，不能当0。
- 小记录/最终统计预算J：按尚待更新的日期数与1份summary，合计`1 MiB * (remaining_date_count + 1)`；仅单日收尾则按1日加summary计算。另为本次实际使用的每个设备保留16MiB余量。J及每文件余量同样是内部估算；实际文件超出估算时必须以实际字节重算后续预算，不静默沿用偏小估算或把超出直接当数据错误。业务JSON原子保存成功并返回对象/摘要后的record_saved仅观察真实大小并更新预算，不把已写字节再当未来写入；下一读写边界仍检查实际free。

空间检查把S、C_new、J放到staging/正式所在设备，把T放到既有DuckDB临时目录所在设备；根据`st_dev`合并同一设备，仅核一次`free >= 该设备尚需新增量 + 16 MiB`。目标目录未创建时取受控根/最近已存在父目录，不借此创建新正式目录；根/路径/同文件系统安全检查仍先执行。同设备不能各项单独比较free后同时通过，不同设备不能用一处空闲抵另一处不足。已落盘文件本身已从free扣除，不再次当新增量扣除；估算的是从当前时点到剩余工作完成还需的空间。

必须执行的边界依次为：

1. 入口只读核批准/计数/已完成事实后、首次远端明细SELECT前；每月开始按当前实际剩余工作重算。控制/schema/计数查询不等于明细SELECT，不靠拉样本才能算预算。
2. 每批片段保存前、每日Raw候选及Silver候选构造前、每次正式提升前；覆盖明细和result/summary写入前也核小记录/本日临时量。复用源或只做本地统计仍执行对应边界，不能因零Prod请求跳过空间检查。
3. 每批保存/候选生成后以实际文件大小更新估算依据，下一边界重读free；若实际空间增长超过初值，使用二者较大值重算后续量。此修正只读取本次文件stat和已得计数，不重扫业务字段。正式执行前预算及运行摘要须同时说明初始估算与实际观测的差异，不宣称初值是物理硬上界。

不足、无法读容量或无法确定所需设备时，抛出包含operation、阶段、设备、required/free及下一动作的明确错误，停止新fetch和后续写入，按原finally收尾。初始不足必须零明细SELECT；途中不足保留已完成源、正式文件和记录，不回滚、不删除旧源、不改R或偷偷缩范围。外部占用导致实际写入ENOSPC仍按写入失败处理，不重试Prod/Tushare请求。中断后重入先核剩余工作并重新预算，完整日期仍可复用；最终只补统计也须核J/T，不能只预算正常首次运行。

验收使用临时目录和假容量：初始不足/正好满足/有余量，途中容量下降，同设备合并/不同设备不足，旧半日保留加新attempt整日重读，10日正式文件累计保留，A日排除后不重复扣A保存行，完整源/已有候选复用仍有C_work及仅统计模式，实际尺寸高于初估后的重算。独立断言预算字节数及零明细SELECT/正式替换，覆盖正常小幅增加仍能通过，不能只证明拒绝路径。不安装依赖、不做正式磁盘压力测试或全量数据读取。

#### 17.8.3 同一源片段的完整检查只做必要次数

**位置与生命周期。**在`stk_factor_pro_bootstrap_records.py::load_complete_source`及写SourceComplete的共用片段核验路径实现复用。入口持有显式的内部验证上下文，固定绑定当前主要DuckDB连接和operation；由主流程传给source/records/publication，禁止模块全局字典、持久缓存或另开连接。当前月结束及操作finally清空；因异常退出也释放，不随全历史月份累计。已有全局小表依据缓存不因此扩大。

验证上下文只保留已成功片段的元信息和首次摘要；首次实际取出的业务行由当前日/跨日批SQL关系持有至最后消费，不放入该元信息字典，不保存整月表；绑定主要连接、operation/批准及月份。固定路径、fragment描述及文件元信息用于轻量交接，SourceComplete小记录首次读取或本次写入成功后直接传对象，不每层重新解析/计算摘要。没有新全局缓存或持久副本。

处理顺序：

1. 拒绝符号链接/越界及缺失文件，获取文件stat；无完全相同缓存项时，执行原文件字节SHA、261列schema/类型、主键、日期范围、行数及整片段业务内容核验。结束再次stat，身份改变或任何检查失败都不登记成功；不得缓存异常或部分通过结果。
2. 首次保存片段若已经从真实落盘Parquet完成同样的完整核验，可以登记；仅用写前内存关系生成期望描述不能登记。saved必须是首次实际读回的TEMP TABLE；writer交接原描述、原SHA及source_relation，remember_saved只核连接/operation/路径归属并登记已有事实，不再hash或重审。原子移动只继承同一产物。保存/读回和新执行首次加载走同一个核验方法，避免“写时一次、读时再一次”各自全验。
3. 命中且文件元信息未变直接复用，完整审计/摘要不再执行。当前同步中身份或已冻结描述变化立即停止，不重新全验后继续。新执行按正常流程对实际需要的未核产物首次确认一次；不得修改manifest迎合变化。
4. 每个完整日仅建立一次本日关系，继承片段字段/数值及严格键序审计，仅核片段引用、本日过滤计数和合同日摘要；同连接同步保存日记录、发布及统计直接消费该结果，不重新创建/全验本日。候选各首次审计一次；提升后继承audit，不以源片段缓存之外为由追加复审。
5. 首次审计记录文件元信息；后续实际取本日数据前作一次必要身份比较，变化停止，不在各helper前后重复比较或重算摘要。只有明确的阶段边界保留轻量身份核验，不引入锁。

内部方法固定补足为：`remember_saved(*, connection, path, fragment, source_relation) -> None`接收writer唯一实际表；`verify(connection, *, staging_root, approval, record, reference) -> (path, file_identity, source_relation)`在新执行首次需要时CTAS并完整核一次，已登记时只返回同一表及首次事实；`release_source_relation(path) -> None`在本片段所需日期已提取后释放实际表，保留本月已核元信息；`close() -> None`尝试释放全部尚存片段表再清元信息。SQL关系名是连接内已有表的引用，不在字典保存业务行或全月表。已释放关系不能在本任务重新回盘建立；恢复按日期升序使用相邻日仍需的跨日片段表，已提取且不再需要的表立即释放，月末finally释放余项。该上下文所有关系仍只归当前主要连接和月份。

验收用一个真实临时片段含3日、每日至少1行，串联片段保存、三日SourceComplete及两层发布，断言同连接/operation内整片段全验恰好1次（含可登记的首次落盘读回），三日本日过滤计数及唯一日摘要首次核验，字段/数值继承片段结果。分别测只改mtime/替换inode/文件身份改变/描述损坏/跨连接或operation/跨月清理；变化不能复用，损坏不能转为成功。额外记录Parquet查询与SHA次数，不能把“全验1次”说成只有1次物理读文件，也单日从已持有SQL关系过滤，不能再打开相同片段Parquet。

#### 17.8.4 准备阶段识别坏覆盖依据，合法导入继续

**位置与合同。**在`stk_factor_pro_bootstrap_coverage.py`准备月依据时补齐生命周期、身份及最终停牌的代码格式检查，复用`asset_guards/stk_factor_pro_readiness.py::build_stk_factor_pro_coverage_keys`当前`[0-9]{6}\.(SH|SZ|BJ)`要求及§10.5.2实际生产者schema。在本数据集既有文件内抽出同一谓词复用，不在两个位置各维护不同规则，不改变其他数据集或上游正式check。Raw源本身不因统计而改码、删行或补映射。

归类固定使用原CoverageInputKind四值，不新增可无限增长的错误枚举：

| 实际不合约的位置 | 记录和后续动作 |
| --- | --- |
| 生命周期ts_code | lifecycle.valid=False；其依赖的当月覆盖不能确定，受影响日期记录lifecycle未知。不把合法的生命周期行单独留下后宣称全市场齐备。 |
| 身份source_ts_code或latest_ts_code | identity.valid=False；当月依赖该文件的日期记录identity未知。若因生命周期已无效而不能检查引用，只记录原lifecycle未知，不把“未执行引用检查”伪装成另一个身份错误；若身份自身代码也错则两类均如实记录。 |
| 最终停牌ts_code | 对应日期suspend.valid=False，只使该日覆盖未知；不得把坏停牌行丢掉当作没有停牌。其他合法日期继续正常统计。 |
| 可归属单日的日历问题 | 继续原unknown_by_date仅标受影响日，文件级问题沿原规则，不将无关日期一起改成未知。 |

已分类问题写入原BasisFile/unknown_by_date及现有result；中文原因包括依据种类、非法数量及至多20个代码样本，不增加状态文件或逐坏行日志。unknown_by_date已有原因字符串只用于解释，分支仍看固定kind/valid。空值/schema/区间/重复等原规则同样适用，不只修这一次代码格式。

生命周期无效时，身份自身检查仍执行；自身通过可标identity自身文件规则有效，但不代表已完成生命周期引用核验，整体覆盖仍因lifecycle未知而不能放行。生命周期恢复有效后，原依赖缓存身份改变，必须重新核引用。只有依据全部有效才调用已知覆盖计算；无效时直接走§10.5.3未知结果，源/Raw/Silver物理计数继续记录，expected/身份actual/matched/missing/extra及coverage_complete为None。完整日合法源及两层仍处理，后续日期继续，不伪造绿check或0缺口。准备期间文件缺失、不可读、坏schema/坏字段等可识别输入问题按已有输入分类返回未知；连接执行错误、程序类型错误、意外SQL错误、源/候选/正式文件读写错误、计数不符等仍传播并停止，不用`except Exception/ValueError: unknown`掩盖。

已确认休市而源有行仍是原停止条件；源本身非法代码属于源合同错误，不能混成覆盖输入未知放行。统计写失败仍失败并保留已发布数据，不把文件系统故障改成“依据未知”。

验收以真实schema的两日合法源和`INVALID`生命周期/身份代码分别测试：两日Raw/Silver都忠实发布，原源计数不变，相应日期unknown且kind准确，未宣称缺口0。另测坏停牌代码仅影响本日、正常A/B/C差集继续正确、生命周期错误但身份本身合法不误报身份自身代码坏；不属于覆盖输入缺失/不可读分类的意外SQL错误，以及源/候选/正式/统计文件I/O错误及休市有源仍停止。夹具错误只在反例中故意引入，不能复制当前消费者的遗漏来生成expected。

#### 17.8.5 运行摘要与失败说明

**位置与方式。**bootstrap入口、source及完整日处理沿现有模块的`logging.getLogger(__name__)`方式输出；使用一个本数据集内部摘要方法统一字段和计数，不新增日志文件入口、运营回调配置、状态表、监控线程或固定间隔心跳。它与on_complete_date业务处理回调不同，日志不能授权发布或代替持久完成记录。

固定事件及触发点：

| 事件 | 输出时点与事实 |
| --- | --- |
| month_started | 批准/空间检查通过、本月处理开始前；需要远端明细时必须在SELECT前；说明selected日期数、批准行数、R、5000行批量及恢复模式。 |
| batch_saved | 完整片段保存、必要读回及源检查通过后；说明本批和本attempt已保存源行数、批次号、当前日期，不能在仅fetch成功时增加saved_rows。 |
| date_completed | 该日两层发布/完成记录及覆盖result写入均完成后；说明Raw/Silver行数、该日源行数、覆盖complete/incomplete/unknown、已完成日期数。不把Raw已完成但Silver失败记成日期成功。源0且无两层文件时明确说明合法无文件结果，不伪造发布数量。 |
| operation_finished / operation_failed | 最后summary原子保存成功并返回既有对象/摘要、且资源关闭结果已知后报完成；任一业务/容量/关闭异常报失败，包含出错阶段、已持久完成量及下一动作。失败日志不把未保存的内存行计为完成。 |

字段固定包含operation_id、attempt_id（尚未创建则None）、month（操作级可None）、stage、event、batch_no、batch_rows、saved_rows、completed_dates、total_dates、trade_date、source_rows、raw_rows、silver_rows、coverage_state、reused_source_rows、elapsed_seconds、updated_at及outcome。无该事实用None，不填0冒充结果；stage使用现有阶段的清晰中文说明。耗时由同进程monotonic计算，updated_at为带Asia/Shanghai时区的当前时间；不承诺ETA或请求阻塞期间定时更新。失败原因及next_action用中文，不打印token、密码、DSN、整行业务数据或完整缺失列表。

`date_completed(..., source_rows: int)`显式接收该日原`SourceComplete.actual_rows`，普通导入、完整源恢复及补数后本地统计三个调用分支一致；不能用本attempt的saved_rows或当前Raw行数代替。原源0行、当前补数两层各5行时必须输出source_rows=0、raw_rows=silver_rows=5。月份、批次及最终操作汇总的source_rows为None，避免沿用前一日数值；它不改变原SourceComplete/result或任何业务记录。

**空间摘要接线。**`_bootstrap_space_check(..., progress=None)`仅增加内部观察依赖，主入口传本次`_BootstrapProgress`。在每次已有预算算完、`require_bootstrap_space`及`record_saved`返回前调用`progress.observe_space`更新内存快照；此方法不emit、不做I/O。所有既有事件携带以下固定字段，不新增事件或逐边界日志：

| 字段 | 精确含义 |
| --- | --- |
| space_estimate_stage | 最近计算预算时的stage。批/日完成日志先于保存后容量检查，可能携带上一边界快照，必须保留此字段，不宣称是本事件即时free。 |
| space_initial_estimate / space_latest_estimate | 首次/最近四项`source_bytes,candidate_bytes,temp_bytes,record_bytes`，均为尚需新增字节的估算；首次固定不变。最近值会因完成工作或切换最后summary预算而升降，不把二者差额当成真实磁盘增减。尚未完成首次预算时为None。 |
| space_initial_row_bytes / space_observed_row_bytes | 4178与原容量算法按实际文件更新的保守每行估算。观测值是后续预算用的余量，不是Parquet真实平均行宽。 |
| space_initial_record_bytes / space_observed_record_bytes | 1MiB与原算法按已观察日期记录组更新的保守余量；不是额外存储或文件大小硬限。 |
| space_latest_observation | 最近一次原检查路径已取得的文件观测，或None。固定stage、trade_date、kind、rows、initial_estimate_bytes、actual_bytes、difference_bytes。数据文件kind=data_file，初估为4178*rows+4MiB；JSON按同日期已观察记录组累计，kind=record_group、rows=None、初估1MiB。差额=实际−初估，可以为负；不含文件路径或业务明细。 |

初始/最近预算均复制已有纯预算结果；观测只复用原`path.stat().st_size`、已得行数及记录组大小，不增加stat、disk_usage、SHA、SQL或业务扫描。observe_space只复制常数规模字典；普通日志错误仍在原emit处理。后检不足时先更新最近预算再抛容量错误，failed日志因此保留当前预算及已完成量；不调整原“通知持久完成后才后检”的顺序。按设备required/free仍由原容量函数检查及报错，不把四分量简单相加冒充跨设备要求。

saved_rows指本attempt真正保存并读回的源行数；operation内复用的旧完整日另以reused_source_rows说明，不混成新导出行数。completed_dates按同operation已核日期处理完成的唯一集合计算：有数据日期要求两层完成及覆盖记录；合法源0且无文件的日期要求完整空源事实及覆盖/日历分类结果，不能要求不存在的两层complete。恢复时先使用已读且与当前文件一致的日期结果恢复基数；已确认休市且具有合法完整空源、无业务文件的日期，月准备后恢复其分类基数。本轮成功日期只新增一次，不因重复执行累加。完整日两层及统计记录保存并核实后，先更新完成量并通知，再执行容量后检；后检失败不能把已完成事实显示成0。total_dates为批准范围内纳入当前operation日期处理的日期数，包含合法源0日；确认休市无源可完成日历分类，不能伪装成资产物化。已保存源行数或日期进度100%不表示市场覆盖齐备，coverage_state必须分别展示。

日志普通Exception仅影响观察：用有限的标准错误提示说明日志失败，不递归调用同一坏handler；不停止合法业务、不重发网络/Prod请求、不重复保存或发布、不回滚文件。KeyboardInterrupt/SystemExit、取消异常和主体业务异常继续传播；不能因捕获日志错误把主体错误吞掉，失败收尾保留原始原因。此规则只针对日志输出，业务on_complete_date、记录写入或校验失败仍按原停止规则执行。

测试用日志捕获和会抛普通异常的handler，验证月→批→完整日→最终顺序、同attempt保存量和operation完成日单调且不重复；跨月/新attempt的saved_rows允许从0重新开始，operation源总量只从唯一已核持久引用求和，不累加日志；验证Raw后失败不出现date_completed、原业务错误不被日志错误替换。取消继续传播，零新增源请求/重复replace；只用一月两日小样本，不新增真实源请求或长跑压测。

内部调用关系固定为：正式bootstrap入口自动绑定check_space和进度对象，每月创建verification；业务不配置这些参数。source/export、完整日处理、publication及coverage写入口必须收到同一check_space；直接内部测试显式使用临时容量依赖，缺参在写入前拒绝。verification是可选的内部性能依赖，不传时仍执行同一完整核验，不能因为没有缓存而跳过检查。进度对象由正式入口持有，source只在同线程调用；借用连接的内部入口不伪造最终关闭成功。

| 内部对象/函数 | 输入与输出约定 |
| --- | --- |
| BootstrapSpaceEstimate | 冻结的source_bytes/candidate_bytes/temp_bytes/record_bytes四个非负整数字节值，不持久化。 |
| estimate_bootstrap_space | 接收已核各月尚需源行数、逐文件行数或互斥的remaining_layer_totals=(总行数,非空文件数)、本日两层工作行数、当前批行数、尚需日期数及实际观测余量，返回上述预算。参数只来自本次计划/已核事实，不能成为运营配置。 |
| check_space | 入口内部闭包，接收中文stage、受控path及已核日期/层/行数和有限事件；source_saved按本attempt减源，candidate_verified只减C_new，publication_verified才解除对应未完成层，date_completed减剩余日期，final_statistics仅切换最后summary预算，复用既有总量/日期集合，不重开统计或重新求和，尚需业务文件量为0、工作行数=(0,0)、T=0、J仅本次必要summary版本，record_saved只观察实际大小。返回预算仅用于观测，不作为发布授权。 |
| BootstrapFragmentVerification | 连接/staging/approval/month固定；verify返回(path,首次文件身份,已核实际关系)；remember_saved接writer实际表及原描述/摘要，不再次SHA；片段日期提取后由release_source_relation释放，close释放余表并清空，关闭后拒绝复用。 |
| 运行摘要 | 标准INFO logging；固定字段见§17.8.5，另含月批准行数/R/批量/selected_date_count。调用环境沿用现有日志配置接收INFO，不由组件安装handler或修改全局日志设置。 |

`_bootstrap_space_check`收到final_statistics后只将本闭包切到summary阶段；删除旧remaining_dates.update(counts)及sum(record_group_sizes.values())分支。后续沿原纯估算函数传pending_source_rows_by_month=()、remaining_layer_totals=(0,0)、work_rows=(0,0)、pending_fetch_rows=0、remaining_date_count=0、statistics_only=True，按已有观测余量得到S=C=T=0、仅1份summary的J；不减去其他日期已保存记录大小。正常末尾或业务失败收尾的每次实际summary尝试前各调用同一final_statistics边界一次，summary自身失败不再重写。其他导入/恢复阶段预算参数及公式不变。

#### 17.8.6 修复顺序及对账完成条件

先完成发布SHA绑定和空间检查，再完成片段复用及覆盖分类，最后补运行摘要；每步先定向正反例再进入下一步。五项分别对账当前实现位置、正常/失败测试与成本；旧858项仅作既有回归基线，不能用测试总数代替本节反例。最终分别报告单元、隔离串联、既有真实有界证据及未执行的正式操作。提交28b7894a保留五项主体修复及当次994项证据；随后审计的三处补齐已按下节完成，当前结论以本轮定向回归和独立核验为依据。不自动授权第五批或正式执行。

#### 17.8.7 三处补齐的限定实现与验收

本轮依据原方案§13.6.2和管理员批准实施，不扩大开发范围。当前代码依据为28b7894a的`_BootstrapProgress`、`_bootstrap_space_check`及9处既有bootstrap签名；只改`stk_factor_pro_history.py`的日志字段/接线及直接测试，records/source/publication/coverage的容量计算、数据与持久接口行为保持。LLD签名只同步当前真实参数；补数回调的正式装配留第五批。

| 硬要求 | 实现位置及输入/输出 | 失败及验收 |
| --- | --- | --- |
| 本日源行数 | date_completed显式source_rows；两处主流程调用都传当前SourceComplete.actual_rows，输出与当前Raw/Silver分别独立。其余事件清本日值为None。 | 普通跨日不同计数、恢复源及原0补5均使用独立字面预期；不能从待测日志反造expected。 |
| 空间估算与实测摘要 | 工厂progress可选，主入口显式传入；observe_space保存固定初始及最近预算/余量/文件观测，字段见§17.8.5。预算计算后、require前更新，不调用emit。 | 相同小样本开启/关闭观察时预算、容量检查次数、日志事件顺序和文件结果一致；实际尺寸增长时用已取得size输出准确差额；首次/途中不足包含最近快照，记录写后观察不变成新写入许可。 |
| 日志不干预业务 | 继续原emit隔离普通日志异常，关闭成功才finished。源/日期完成量更新与容量后检时序不改。 | 原异常、取消、关闭失败、坏handler及后检失败定向回归；不重复fetch/replace、不吞主体错误。 |
| 接口和下一批交接 | §10九个实现签名按参数顺序/必填/默认值同步；check_space及verification/progress都是内部依赖。§10.5.6明确仅统计绑定。 | 静态AST逐项比对接口，不能靠文档完整性检查证明API匹配；不实现新控制层或借测试回调充当正式方案。 |

性能和读写边界：网络请求/业务扫描/连接/SQL/新数据文件均增量0；磁盘检查次数及元信息读取沿原实现，新增工作只为每个既有边界复制常数规模摘要。常驻只保留初始、最近和最近文件观测，不按文件/日期累计日志副本；中断/最终统计同样只更新这份快照。定向真实临时Parquet测试不超过三日、每日至多5行；观察增长可用已有大小注入，不读取巨型文件或压测。正常及失败成本断言沿原查询/替换计数，禁止安装依赖、正式读写、启停DG或推进第五批。定向98项通过，末次1项补验通过且与前述重叠不累计。14处已实现签名按AST逐项匹配；独立审计已核本轮日志及第四批原链，未发现新的确定问题。原发布/范围/恢复/覆盖实现未改，正式执行和第五批仍未推进。


## 18. 第五批之前的整体复用修正轮

### 18.1 范围与顺序

本轮已获准按8步实施，逐步结果见§18.8。修正轮覆盖已实现第二至第四批的数据读取、源/候选/发布、批准/小记录、覆盖与统计全过程；第五批PG reader、job/repair接线按相同规则实现。公共下载器、261字段源合同、源分页、Prod及其他数据集不动，正式资源不在本轮操作范围。

顺序为：主入口局部变量及首次读取交接→源/旧目标/新Raw与Silver关系复用→单次完整审计和摘要→共享覆盖/样本/单份明细→唯一日期账本与合计→PG/事件结果交接→次数回归与独立对账。所有内部签名与现有消费者同次迁移；禁止缺参数时回盘/查询/计算兜底，不增加缓存平台、状态表、后台进程、配置或锁。

### 18.2 唯一日期账本及合计

主入口首次需要时读本任务必要原日记录一次并形成date_results字典，每日只有一个当前条目，使用既有DateResult/DateCoverage及原SourceComplete/发布事实。仅同步一天时，就是一份内存日期记录。首次载入时计算合计一次；本任务产生本日新版本后按§18.2.1登记和持久状态替换贡献一次；未持久的新结果不进入成功合计，已失效旧贡献先退出，并更新日期集合及有效记录摘要。版本未变不更新、不重写，不使用旧持久summary总数作累加起点。

summary只消费这份账本及本次已经维护的合计/集合/记录摘要：JSON、业务文件、PG读取0，覆盖SQL/重新求和0。必要新summary序列化/保存一次，无变化直接返回既有对象；正常、批末、失败和最后收尾同样执行，不重新classify、prepare或扫描日期。序列化当前必需字段属于新输出，不是再次计算各日统计。

本bootstrap正常末尾一次、业务失败收尾最多一次调用summary；正常summary在业务try/except外执行，保存summary本身失败时不重试第二次写入。每日result/文件事实即时登记和本日贡献更新不触发额外summary写入。主入口首次为所有批准日期形成小型条目及贡献；进入某月后只首次准备该月输入，更新这批日期的日历分类和旧结果适用性，后续正常/异常仅更新实际受影响的日期。不在末尾再次classify、prepare、evaluate或遍历全体日期重求合计；尚未处理月份保留未知/未完成。

原导入计数与当前状态分开，缺口/未知/未完成如实保留。原子发布后记录失败不回滚业务数据；账本保存真实已确认与未确认状态，下一获准执行从持久事实首次建立自己的账本。不存在跨进程共享或逐日断点续传。

#### 18.2.1 登记、日期条目与失败收尾

日/历史publish外层→_publish_file→intent/complete/publication-complete writer及IO _json_write/_write_rows必须原样传入口同一known_records；manifest writer登记首次files tuple、引用摘要及身份。纯转换/候选函数若已显式取得所需关系与audit，不为凑参数重复传字典。

同一known_records同时供bootstrap records/source/publication/coverage/history调用；date_results复用主入口classified的按日字典，不另建持久账本。每个日期条目的字段固定为：source_complete及摘要、原raw_complete/silver_complete、当前raw_audit/silver_audit、current_publication、needs_restore、replaced_layers（raw/silver集合）、persisted_result及摘要、computed_result、current_files_verified、coverage_record_current、unknown_reason、previous_contribution。原分类的source/valid/needs_restore/trusted四项分别迁为source_complete/current_files_verified/needs_restore，以及拆开的current_publication/raw_audit/silver_audit，不保留另一份旧tuple。以上均是现有对象/标量；computed_result只是本次待保存值，不成为第二份当前持久统计。主入口统一维护imported/current集合及合计，底层不自行维护另一套总数。

| 真实边界 | 内存登记及允许的结论 |
| --- | --- |
| SourceComplete原子保存成功 | writer立即登记对象/摘要，再交回调；首次原源0沿原合法空源规则。 |
| Raw/Silver的os.replace返回 | 立刻把该层加入replaced_layers，登记原候选audit/摘要对应的正式目标事实；父目录fsync及complete未结束时，不宣告该层完整发布完成。 |
| 本层complete原子保存成功 | 立即登记同一known_records中的complete对象/摘要。原源及原两层complete均成立才加入imported；不等evaluate/write_result返回。正常DateResult仍只在整日函数成功时返回，不用它承载半完成状态。 |
| 首次coverage计算完成 | computed_result保存本次唯一计算值和引用；不填persisted_result_digest或summary.date_result_digests。 |
| result原子保存成功 | 登记对象/payload摘要为persisted_result，computed_result清空；替换本日旧贡献一次，更新current及已知覆盖集合。 |
| 物理数据/必要依据已变、统计失败 | 原import事实保留；旧result不再适用就移出当前有效覆盖贡献，本日标统计未知/未完成，computed_result不能冒充持久成功。正式文件不回滚，不回盘核实。 |
| 文件、依据和旧记录都未改变，只是等价新引用保存失败 | 适用旧result及原贡献保留；不机械清掉整日。若result路径已被替换但后续同步失败，该路径不是已确认持久结果，不能继续引用旧摘要。 |

replace与父目录fsync之间的登记用已有atomic_promote增加可选内部on_replaced回调实现，紧接os.replace调用；回调只更新本任务字典/集合，不查文件/PG、不计算覆盖、不另写记录。IO日/历史发布的对应替换点同样登记当前文件事实；这是内部调用，不套下载进度通知的吞异常规则。JSON实际替换时先移除该路径旧known_records项，全部同步成功后才登记新对象/摘要；对于coverage/<d>/result.json，若异常时仍未登记新版本，主入口清除该日persisted_result及摘要、置coverage_record_current=False，仅保留computed_result作本次诊断；失败发生在替换前则旧登记未移除，仍按原适用性判断。失败不把准备好的payload摘要伪装为保存成功。父目录同步成功后必须先登记，再执行保存后的容量/进度检查；后检查抛错时，外层仍接受已经登记的持久事实，不能因函数未正常返回就倒退为未保存。异常分支只消费日期条目和已登记事实；不存在合法新确认值的地方明确未知，不能回读补齐。

```python
def read_json(path: Path, record_type: type, *, known_records: dict) -> object | None: ...
def write_json(path: Path, record: object, *, known_records: dict,
               mutable: bool = False, check_space=None,
               on_replaced: Callable[[], None] | None = None,
) -> tuple[object, str]: ...
def atomic_promote(temporary: Path, path: Path, *, replace_existing: bool = False,
                   on_replaced: Callable[[], None] | None = None) -> None: ...
```

process_complete_date、publish_bootstrap_date及其_publish_layer必填传同一known_records/date_results；source/intent/complete/result包装writer把同一known_records传到底层write_json，IO历史_json_write同样登记。发布层在on_replaced中登记正式目标及replaced_layers；complete写成功再登记完成事实。主入口正常/except都按本日固定键消费上述事实并更新classified/imported/current，不再次_classify_date；只有完成原导入条件才增加原导入贡献。current仅包含当前两层及所需统计引用可确认日期，其他日期明确进入summary的未知/当前不可确认集合，不能把旧行数当新文件数量。数据和记录全未变化时previous_contribution原样保留；变化时先移出旧贡献，再在持久result有效后加入新贡献，同一版本不得重复计入。

previous_contribution固定保存原导入三项数量、当前两层数量（不可确认时None）、已知覆盖五项数量（未知时None）、该日所属分类集合及已持久result摘要。主入口内部替换方法只接本日条目、合计和日期集合，不接受路径/instance/连接：先从已登记事实形成新的小贡献；与旧贡献完全相同时直接返回。数量/分类改变才从合计减旧、加新一次；只有记录摘要改变时只替换date_result_digests，不重新计算数量。所有集合增删按日期幂等；初始化与变更使用同一方法，summary不调用它重新遍历日期。原source_empty、imported事实不因当前覆盖失败被清除；未确认当前文件/统计的日期按既定summary字段列未知。

验收使用真实已有失败边界：Raw后Silver失败、两层完成后evaluate失败、4800补到5000后result保存失败、replace成功但父目录同步/complete失败、等价数据引用保存失败。外层即便没收到DateResult也能正确保留已完成事实；断言失败收尾读取/覆盖重算0，未持久结果不进入成功计数或date_result_digests，适用旧结果不被误清。原异常及次要收尾错误分别保存；Tushare失败的新run仍整范围新下载。

### 18.3 首次源审计的具体项目

历史首次prepare使用同一主要连接，把T/P各物化为固定`stk_factor_pro_history_factor_t/p`；schema、行数、唯一股票、原日期、有限正值及文件SHA各首次确认一次，登记原FactorFileRef、SHA、identity和关系。生命周期首次物化固定`stk_factor_pro_history_lifecycle`，schema有效时向后续规划/覆盖交关系；缺失或原规定schema不可用时为None，未知不猜值。builder直接消费这些关系；它不再打开同一文件或释放调用方的输入关系。准备失败清自己已创建关系；规划失败、无历史工作由控制层在本次调用最后一个消费者结束的finally调用release_inputs，正常历史任务在最终退出时统一释放。无历史工作但仍需日覆盖时，名单生成后不能提前释放覆盖仍需借用的生命周期关系，遵守§18.4最后消费者原则。三个输入再核边界必填同一known_records，只比较首次T/P/lifecycle实际identity及已有四项结果；变更停止，零SQL、零文件SHA、零重新读取后继续。

历史prepare首次读取生命周期后，known_records[path]首项的既有三元组为(relation,row_count,observed_schema)；schema不符且实际表已清理时relation为None。coverage准备直接继承这个已得坏schema及计数，归lifecycle unknown，不能因None而重新打开同一文件。若schema原本合法但relation已释放，则本任务报错，不通过重新读取补回关系。此为已有三元组含义澄清，不新增记录格式或宽松兜底。

历史下载先创建固定空的`stk_factor_pro_history_source`，每个完整unit保存临时Parquet后只实际读回/完整核验一次；已核实际关系并入该总关系，再释放本unit网络、DataFrame及转换/读回关系。只有全部会话正常退出、manifest逐项齐备才组装七字段VerifiedSource。source verifier不再读记录或源Parquet、计算文件或业务摘要；直接对比同任务已登记对象、摘要、unit和文件identity，并只按元信息确认源文件仍为首次保存的版本。含T响应仍留总关系，发布只处理已定d<T日期。

download在非空完整units、当前身份/plan_ref及新source目录条件通过后，eligibility写入/recheck/取消/容量前进入callee收尾范围；此前参数拒绝/无工作仍由caller finally释放inputs，不做父子双清。成功将总关系及输入关系交publisher，进入该范围后的失败/取消调用release_source清总源及inputs；unit只由_save的finally清一次，release_source不重复清unit。publisher整个生成器都在同一收尾范围内，包括首次yield前失败、业务处理yield抛错、提前close和正常完成；日表由逐日scope清、批表由逐批scope清，外层只清总源及inputs，不重试已失败的日/批清理。保留原业务错误并附清理错误。每个Silver结果交给控制层后，先完成该日最后的数据计算及小结果交接，恢复迭代器才清本日表；20日只从总关系过滤一次，不能重新read_parquet源文件。无独立完成unit复用或跨run续跑。

首次源日期聚合同时保留各日行数，后续HISTORY_DAY_SOURCE不再count；代码及原闭区间归属继承各unit首次审计，仅在总关系首次聚合核SSE/已登记发布日期。Raw缺原键复用首次B/U交集RAW_MATCHED_KEYS，缺口为0不保存附件、不再执行EXCEPT或SHA；无旧关系已知0时连空差集表/count也不创建。Raw范围行数直接为本日源行数加该范围未刷旧键数；Silver从同一Raw转换，复用相同行数，范围业务摘要按两种既定日期表示分别首次计算一次。完成记录汇总已有targets/audits/引用，不回读刚生成的记录或重新计算源/范围摘要。

| 项目 | 本数据集具体检查 | 明确边界 |
| --- | --- | --- |
| 请求及交付完整 | unit属于本任务规划，分页正常结束；session正常关闭，最终SUCCEEDED及unit/row统计对应实际交付 | 半unit、关闭失败不进入发布；合法0行是源请求成功，是否有可用日数据由既定业务条件判断一次。 |
| 源字段及转换 | 全部261业务字段齐全，按每条记录自己的fields映射；规范化后的Raw列类型/顺序符合唯一合同 | 不因跨页列顺序不同错位；不补列/补值，不建立字段子契约。 |
| 代码和主键 | ts_code非空、符合当前A股代码合同；(ts_code,trade_date)非空且唯一 | 历史unit只允许请求的股票，不能收到别股后静默过滤。 |
| 日期和范围 | 源日期可严格解析；日请求全为T，历史为该股[start,end]闭区间；Prod为批准月/日期及严格跨批键序 | 不做宽松日期推断，不将非法日期变NULL；实际输出Silver新候选另按DATE合同首次确认。 |
| 数值与NULL | 按HTTP/Prod现有源类型转换DOUBLE，保留合法NULL、负值和0，拒绝非有限值/溢出及未经允许的类型 | 不校验MA/MACD数学公式，不设指标高低或正数门槛，不清洗/填补业务值。 |
| 传输保存 | 必要源片段/新候选首次实际输出与本次已持有期望关系一次对账，行数/主键/全部业务值和NULL应对应；取得合同实际使用的摘要一次 | 原子移动同一候选不产生新数据，不再次审计。bootstrap完整日继承片段结果，只核跨片段日计数/引用并算合同日摘要一次。 |

首次审计集中在源unit/片段及新输出第一次确认处。转换时必要解析和范围归属按一次处理收集，后续不再require相同关系、重新JSON化全列算摘要或重做同一JOIN/计数。首次已有的行数、NULL统计、B/U键匹配/K及本日差集结果随关系一起传递；新候选传输对账仍必须真实，不能从输出自身反推依据。

日U持有到本日最后一个需要业务数据的消费者结束；计数/摘要/引用交出后，事件和记录包装不再持有或重建该表。历史每unit首次取得的行保留到同一连接总源关系，源文件首次保存/审计的实际关系直接复用，之后unit网络对象/转换对象释放；日期规划和20日批次不重新打开源Parquet。bootstrap首次批片段审计后，按源排序将当前日数据保留在BOOTSTRAP_DAY_SOURCE；跨批只保留当前日及尚被下日引用的跨日批关系，不重新从片段加载当前日、不累计整月Python行。新执行恢复某片段首次读取一次后仍按此消费，读过的片段不为相邻日期再开文件。

### 18.4 原文件、新候选与审计结果

本轮内部接口精确同步如下，所有调用方同次迁移，不保留旧路径参数或缺参回读：

```python
def build_stk_factor_pro_raw_candidate(connection, *, source: VerifiedDaySource,
    prior_path: Path | None, candidate_path: Path, run_root: Path,
    known_records: dict) -> StkFactorProFileAudit: ...
def build_stk_factor_pro_raw_candidate_from_relation(connection, *, source_relation: str,
    source_row_count: int, target_trade_date: date, prior_path: Path | None,
    candidate_path: Path, run_root: Path, known_records: dict) -> StkFactorProFileAudit: ...
def build_stk_factor_pro_silver_candidate(connection, *, verified_raw_relation: str,
    raw_audit: StkFactorProFileAudit, target_trade_date: date,
    candidate_path: Path, run_root: Path, known_records: dict) -> StkFactorProFileAudit: ...
def audit_stk_factor_pro_file(connection, *, path: Path, expected_relation: str,
    target_trade_date: date, layer: str, known_records: dict,
    diagnostics_path: Path | None = None) -> StkFactorProFileAudit: ...
def factor_file_identity(path: Path) -> tuple[int, int, int, int, int]: ...
def factor_known_file_sha(path: Path, *, known_records: dict) -> str | None: ...
def load_stk_factor_pro_prior_relation(connection, *, path: Path, relation: str,
    target_trade_date: date, layer: str, known_records: dict
) -> tuple[int, tuple[tuple[str, str], ...]]: ...
def release_stk_factor_pro_audit_relations(connection) -> None: ...
# _publish_file新增必填prior_relation: str | None；其余已定参数不变。
```

首次旧文件读取直接登记`known_records[path]=((relation,row_count,observed_schema),首次SHA,文件identity)`，其中三个本地值就是本次已取得的SQL关系名、行数和schema；发布等价比较通过时用该正式旧文件的StkFactorProFileAudit替换首项，摘要和identity不变；不等价时仍保留首次旧文件事实，只有实际replace后才登记新产物，不把比较不等当成旧文件损坏或本轮已发布。新候选登记首项始终为实际首次audit。已确认文件缺失仍为`(None,None,None)`；不得用无摘要的半记录冒充已核产物。factor_known_file_sha仅首次取得文件SHA，以后只核已有identity；变化停止，不重新hash后继续。以上均只在本任务变量中，不新增持久格式或记录种类。

source_row_count直接使用首次来源结果，不再计数U。Raw首次B行数及B/U交集只算一次，交集临时关系同时供合并和K计数；不在构造expected后重新统计B/U/expected。旧文件第一次读取后已得关系、行数、schema、SHA及元信息向发布函数交接，等价判断不再打开旧文件。内容等价但Parquet字节不同，复用正式旧文件的首次audit及SHA；replace则继承新候选audit。

新输出首次读回物化到本连接临时表，完整审计/文件SHA各一次；表名由已得路径和文件SHA派生，绑定实际文件版本，不再读取文件来派生。首次输入schema/计数已得后，同文件针对另一个expected关系的必要新比较只复用实际表及摘要，不能直接返回上次passed，也不能重新打开实际文件或重新审基础合同。本日最后的数据计算及小结果交接完成后统一清理本模块审计表；已经释放后不得拿旧任务字典继续新一轮审计，新任务首次读取自己的必要输入。缺文件时factor_file_identity抛FileNotFoundError，由允许目标不存在的外层明确记录缺失。

旧Raw首次读取到DAY_PRIOR后，等价判断和合并均用该关系，不在_publish_file再打开目标。RAW_EXPECTED对应唯一Raw候选audit，保持至本日必要数据计算和小结果交接完成；build_stk_factor_pro_silver_candidate接收verified_raw_relation、raw_audit及既有根/日期，不再用verified_raw_path读取刚发布Raw。历史旧Silver若需要首次读取一次，缺原键和等价比较共用该关系。

候选首次audit、文件/业务摘要、schema及计数向描述、intent、complete、DG checks、scope/覆盖消费者直接交接。发布后不重新DESCRIBE/count/全字段对账或hash；记录摘要从序列化payload计算一次。B−K+U及候选对账用首次已有计数/匹配结果，不重新构造相同B/U JOIN或expected。compare_factor_relations现有单次FULL JOIN聚合语义保留，不另跑259字段JOIN。

已知0缺口不创建诊断文件、目录，也不追加EXCEPT/SHA；intent/complete为count=0/ref=None，PublishedTarget只用已有count。非零差集只计算、保存、首次审计一份，普通RawCoverage及bootstrap结果引用它；共享引用规则见§10.5.6。合法0行源unit仍按源合同保存，不与空诊断混淆。

### 18.5 小记录、来源预检、PG及输入边界

read_json首次读取一份字节，同时完成JSON结构解析及需要的摘要，返回对象/摘要供本次所有消费者复用；approval_sha、source身份、plan/ranges/manifest和日期分类不能再读相同文件。已由本模块构造的合法记录不在writer反解析/再次审计；序列化payload及摘要一次，原子写成功后直接返回新版本更新本任务变量，不读刚写文件来确认自己已知的值。相同版本不重复写入。

bootstrap_publication将旧`_publication_identity`拆成意图和完成记录各自的首次校验。read_publication按intent/complete两个固定路径，只有本任务首次读取该记录才检查其归属、摘要及引用；后续从同一known_records直接交出已确认对象，不重新校验已知intent、不重新计算intent_digest，也不因Silver重复读取已核Raw完成记录。公开write_intent对独立输入保留首次意图校验，再调用唯一私有保存体`_write_verified_stk_factor_pro_bootstrap_publication_intent`；内部_publish_layer已按既有规则构造合法intent、计算唯一intent_digest，直接调用同一保存体，不重复计算。保存体参数沿用公开writer的原参数，不新增skip/布尔开关或公开入口。write_complete直接消费本任务已核intent，只检查新complete与该intent、正式audit及其首次摘要的对应，不再校验整份旧intent或递归读Raw。首次坏记录、意图/完成错误绑定及首次Silver对应错误仍须拒绝。故障注入应覆盖实际JSON保存/原子提升边界，不为保留旧mock入口恢复重复检查。

bootstrap入口已读approval/计数/evidence/sample后，月导出、write_source_complete、publish及coverage只收这些值。source_inputs及preflight_context的固定内部签名、checked_windows日期子集复用规则见§10.3.1；不能以recover联合日期和pending子集不同为由重复计数。实际需要Prod时，固定schema、全源首尾和批准固定样本本任务首次一次；每月新事务SET LOCAL timeout、各不同待读日期窗口计数首次一次，同月recover/pending共用该月结果，不各自preflight。没有Prod剩余工作不连接Prod。

同一PG run/观察/物化/check在整个run按真实身份首次读一次，不以reader、授权resolver、Silver资格、bootstrap收尾分别缓存一次。本run新yield首次持久化后读取新增事实以取得真实id属于新事实，所得对象及批映射继续交接。历史三个边界仅比本次已确认身份，未变复用，变化停止；不重新读取PG/全文件SHA或覆盖后继续。队列job入口三状态且不二查，终端bootstrap原维护检查保留。

### 18.6 修正代码清单、成本及验收

| 已实现位置 | 修正轮统一任务 |
| --- | --- |
| bootstrap_records read_json/write_json/approval_sha/source_identity/approved_counts，io.history _json_read/_json_write/_ref_path/_read_rows/_write_rows | 首次字节/对象/摘要直接交接，写入返回新版本；清除多层读盘、SHA和反解析。 |
| bootstrap source preflight/selected_dates/complete_day、入口classify/末尾prepare | 入口和当月首次结果共用，日期账本直接更新，源当前日关系不丢后重载；固定远程事实不按月重查。 |
| coverage update→evaluate→write→summary | 控制层首次覆盖一次；pure包装/单次保存；原日账本/合计复用；不读source/旧result/明细或重新核两层。 |
| io download/history/候选/publication/纯检查 | T/P及生命周期已加载关系、源总关系、旧B/旧Silver、RAW_EXPECTED复用；首次audit/摘要/计数共享，不重复源文件读取或正式Raw读取。 |
| 本数据集记录类型和诊断引用消费者 | 非零明细一份共享，补齐BootstrapCodesRef的受控run/operation归属；同步所有parser/writer/测试，0附件和旧格式无兼容分支。 |

bootstrap控制层的`_classify_date`首次确认正式目标SHA后，将现成audit、摘要和identity登记同一known_records；`_bootstrap_space_check`直接消费classified中的complete及本次已登记intent对象，目标/候选SHA统一复用factor_known_file_sha，不再次调用publication reader或直接hash同一文件。恢复process沿用这些首次事实；预算公式、设备归并及行宽估算不变。验收以初始分类→预算→process整个任务计数，不能只证明某个helper局部减少读取。

控制层内部由`_execute_stk_factor_pro_bootstrap`持有首次classified、唯一summary_state/basis_inputs及已有summary，私有`_process_stk_factor_pro_bootstrap_months`只顺序处理月份和日期，接收这些既得对象及本日贡献更新闭包。入口以同一finally释放本模块own的全局依据；月函数只释放该月关系。月函数不保存summary、不返回另一份账本，入口正常收尾一次、业务失败收尾最多一次按§18.2保存。删除原末尾重新prepare/classify/evaluate的整段流程，不保留第二路径。

已用CodeGraph explore核完整日process与发布/覆盖调用链，impact核Silver构造影响；对索引未完整显示的调用方，另按真实引用核日/历史publication、bootstrap publication/coverage/history及对应候选、发布、覆盖、恢复测试。该项是修正轮的静态证据。按§2.5完成的第五批运行验收见§19.13。

历史双份留存、所有候选与正常/失败重新下载空间严格按下节唯一公式计算；首次计算的unit/日期/页脚计数及估算直接交接，不在边界重新规划。网络/Python对象逐unit释放，旧B仍逐日、当前批仍20日。预算不足停止，不引入持久缓存、配置或绕过重读。

验收以一个完整任务为边界，而非每个helper各自宣称一次：每个必要旧JSON/Parquet/PG事实首取一次；写回后重读0；同日期版本coverage键运算1、计数/样本各首次取得1、两类包装额外计算0、非零同一明细文件1；summary的读取/SQL/重新求和0，未变重写0。Raw旧文件/旧Silver各首次1，Silver及覆盖再开正式Raw0；后续历史日期规划/批次开源Parquet0。首次新输出传输读回是该新版本一次审计，不能取消或拆名成多次。

一次单日完整链、原0源补数、跨批同日、20日尾批、合法值保留、真实I/O/记录失败、取消及新run全新下载使用已有离线样本和临时资源。断言首次结果的实际对象/版本被下游接收，spy禁止相同输入版本及投影、相同PG身份、相同覆盖输入再次读取或计算；首次取得先前未读的必要字段/新版本属于新事实，不得借此重复已做审计；新版本只更新一次贡献。测试预期用独立字面样本，既要抓重复，也不能拦真实新增事实。没有实际业务写入步骤会篡改内部关系时，不构造内部UPDATE来要求常态全扫。仅用现有环境及受保护runner，无正式资源操作/真实源新增请求/全历史跑数。

#### 18.6.1 历史下载及发布的容量算法与入口

本节只用于本数据集Tushare历史，不调用bootstrap审批/attempt/恢复状态机。已有BootstrapSpaceEstimate在run_contracts中复用；io/history不得为预算反向import bootstrap。所有数字是保守估算，不是新的业务配置、物理内存保证或新的请求额度。

**首次输入。**控制层在原T覆盖/Silver及历史资格通过后，取得一次expected_units；据已核日历生成一次publication_dates=N（实际需处理的d<T开市日期），按20/20/尾批固定分组。每unit i的h_i=(end_i-start_i).days+1，含T、每股每日唯一键提供行数上界；H的输入是这些自然日行数之和，不能用发布日期数量代替。首次仅对N内现存Raw/Silver取已得audit行数；没有本任务audit时，批量读取各目标Parquet页脚num_rows一次并记入任务字典，不读259指标来估大小、不让每个边界再取同一页脚。后续真正合并首次需要业务字段仍沿§5.1.1不同投影规则，不重复统计页脚或重审已知键。

**估算值的单处来源。**把既有同值提取到本数据集run_contracts，不再在bootstrap/history/progress各写一份：r对应STK_FACTOR_PRO_ESTIMATED_ROW_BYTES=4178，f对应STK_FACTOR_PRO_ESTIMATED_FILE_OVERHEAD_BYTES=4MiB，j对应STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES=1MiB，m对应STK_FACTOR_PRO_FREE_SPACE_MARGIN_BYTES=16MiB；既有单日1GiB估算对应STK_FACTOR_PRO_DAY_WORKSPACE_ESTIMATE_BYTES。消费者仅本数据集两种纯预算、容量闭包及进度摘要，依代码加载生效，记录实际估算；无env、数据库或run_config覆盖，不修改既有值/公共DuckDB参数。测试用独立字面期望证明原bootstrap预算数值保持及新历史公式正确，实际文件增长的观测值继续按已有规则增量维护。

**唯一公式。**沿§17.8.2已批准的r=4178字节/行、f=4MiB/非空文件、j=1MiB/小记录和m=16MiB/设备余量。P(n)=0（n=0），否则r*n+f。定义u_d为expected_units中覆盖d的unit数量；单股票每d至多1行。b_d、s_d分别为旧Raw/Silver页脚行数，缺文件为0。

| 项 | 首次任务估算 |
| --- | --- |
| S 源文件 | sum_i P(h_i)，一unit一份源Parquet；含T。 |
| H 完整SQL源 | P(sum_i h_i)，保留到历史结束。 |
| U 当前unit | max_i P(h_i)，只有一个网络unit及必要转换对象同时处理。 |
| B20 当前批源 | P(max_批 sum_批内d u_d)，只含回刷股票，不是20天全市场旧数据。 |
| W 单日工作量 | 入口首次用已得审计行数计算G=sum P(本连接仍持有的T/P、生命周期、身份等依据关系行数)；W=max(原已拍板1GiB处理余量, max_d 4*(G+P(b_d)+P(s_d)+2*P(b_d+u_d)))。覆盖全部既有依据、当前日B、旧Silver、两层expected及首次审计，不持有20天全市场。 |
| T 临时计算 | H+max(2*U, B20+W)：下载时当前unit/首次读回短暂共存，发布时当前批加单日工作。 |
| C 两层新文件 | sum_d 2*P(b_d+u_d)，每个计划日期/层各计一份。等价reuse留下的候选也计入；replace只是改名，不再加同一份正式副本，不预支删除旧目标收益。 |
| J 记录与明细 | j*k。D=len(N)，D_op仅用于开发阶段上线前初始化补数，表示本次原导入批准交集日期数；上线后普通日更/repair的D_op=0、operation_dates=()，不读取初始化记录；k包含尚未写的manifest/source-complete/publication-complete各1份、每日期两层intent/complete共4D份、每日期每层最多1份缺原键明细共最多2D份；有operation时另加每日期result及最多2份missing/extra共3D_op份，再加每个会更新该operation的批次1个summary版本。零附件不落盘，原已保存plan/ranges/eligibility不计未来新增；eligibility若尚未保存则另计1份，并由同一回调核写前容量、写后扣除该份，不能无预算写入。PG事件不计本地文件。 |

纯函数固定为：

```python
def estimate_stk_factor_pro_history_space(
    *, unit_row_bounds: tuple[int, ...], max_batch_rows: int,
    remaining_layer_row_bounds: tuple[int, ...],
    remaining_record_file_count: int, day_work_bytes: int,
) -> BootstrapSpaceEstimate: ...

def require_stk_factor_pro_history_space(
    *, required_by_path: tuple[tuple[Path, int], ...],
    run_id: str, stage: str,
) -> None: ...

def build_stk_factor_pro_history_space_check(
    connection: DuckDBPyConnection, *, identity: RunIdentity,
    expected_units: tuple[UnitProjection, ...], publication_dates: tuple[date, ...],
    lake_root: Path, staging_root: Path, known_records: dict,
    basis_row_counts: tuple[int, ...], operation_dates: tuple[date, ...] = (),
) -> Callable[..., BootstrapSpaceEstimate]: ...
```

容量工厂只绑定本任务已得unit、日期、依据行数和原operation交集，不读取批准或PG。已有目标audit直接给行数；其余目标用同一连接的parquet_file_metadata一次批量取页脚行数，保留在闭包局部字典。回调固定接收stage及path、rows、trade_date、layer、event，字段沿既有内部容量通知，不加运营配置；首次预算及每个文件/版本的贡献保留在闭包，保存事件仅增量扣除。实际新文件超过本项估算时停止并说明，不重新全量计算，也不静默沿用偏小值。

estimate仅首次对已得整数按上述公式计算，返回既有四字段(source_bytes=S,candidate_bytes=C,temp_bytes=T,record_bytes=J)；unit为空应沿no_action，不创建预算或下载会话。stage只是中文错误说明，不作为可扩张错误码/运营输入。require按实际路径最近存在父目录的st_dev归并，每设备新增量求和后只加一次m，并核disk_usage.free；同设备S/C/J/T相加，不同设备分别核。source/candidate/record归现有staging路径，T归该主要连接既有temp_directory；manifest/source-complete、intent/complete及必要诊断/汇总写入前同样传check_space核J，不为早已保存的plan/ranges再计算一次；16GB内存及512GB临时配置不修改、不当成磁盘剩余量。初始设备无法确认或空间不足就明确Failure，零历史session/请求。容量闭包按§6.1将此本地错误归入history阶段、source_error_code=None、retryable=False及allow_retries=False，携带已有run/T、stage、设备required/free和管理员处理动作；不新增下载器错误码，不把磁盘错误交源重试。

**本次任务的后续边界。**download与publish必填接收同一check_space闭包，入口持有首次预算、按unit/目标的贡献及剩余合计。首个session前核全任务；下一unit取数前必须先check_cancel再check_space，放在next(session_iterator)之前（不能拿到结果后才检查）；保存并入SQL前、20日物化前、本日候选写前及replace前复用该预算核实际free。source_saved/candidate_verified/record_saved使用已得文件大小及归属，每个计划文件版本仅一次移除对应尚需新写贡献；summary同路径的不同必要批次版本分别在初始计划计入，相同版本不重写/重扣。rename不再扣第二份，不遍历全部日期重新求和。实际大小超过估算时，按已得尺寸增量调整剩余同类估算或停止说明，不能静默使用偏小值。已占正式/旧run文件自然已从free扣除，不再作为尚需新增量重复扣；失败新run仍完整预算自己的新S/H/C，不从中减掉旧失败源或已发布日期。

临时空间另避免把已落盘spill再次当未来新增：在这些已有容量检查边界，当前主要连接只读取一次duckdb_temporary_files()的path/size元信息，按现有temp_directory归属取得当前已占量A；未来临时新增量为max(T-A,0)。这不是业务数据审计，不解码源或正式Parquet、不遍历目录、不另开连接/线程；H即使当前仍在RAM也包含在未来可能spill的T内，不能仅按已插入行数扣掉H。当本边界T为0、仅写最后summary时不查询spill元信息。元信息读取失败明确停止，不把A猜成0或已有业务成功回滚。[DuckDB临时文件说明](https://duckdb.org/2024/07/09/memory-management.html)给出path/size字段；[官方实现](https://github.com/duckdb/duckdb/blob/main/src/function/table/system/duckdb_temporary_files.cpp)从当前context的BufferManager取得文件。现有主要连接为独立内存数据库；T/W必须包括该连接仍持有的T/P及生命周期等依据，A只能来自同一实例，不能减其他实例的文件。

**精简验收。**只用日期/整数与替换容量返回值：一股周五至下周一T，h=4、N仅周五，P(4)=4,211,016字节，S=H=P(4)，B20=P(1)=4,198,482；旧Raw/Silver各2行，u=1，C=2P(3)=8,413,676。断言S与H同时存在，含T不混作d<T；同设备只加一次16MiB，不同设备分别检查；A=0和已占spill均不重复扣；45日纯日期按20/20/5，预算只算一次，完成后仅增量更新。初始不足零session/请求，途中不足不领下一unit；原业务失败优先、最后释放关系，新run整范围重下预算保留。使用临时资源/已有离线样本，不做大文件、真实源新增请求或内存压测。DuckDB内置元信息接口的当前安装版本语法在修正轮开始的最小隔离连接检查一次，不能拿正式连接探测。

### 18.7 第五批实现边界

本节第五批的初始化统计要求只适用于开发阶段上线前人工补数。物理bootstrap按顺序月份prepare；不得把该全月准备直接挂到补数单日或每20日批末，更不能带入上线后的普通日更/repair。T及历史日期只首次取得实际需要的新依据/日期事实，已算T小结果保留至记录收尾，不能因为先释放某月份再返回同月而重读。compute/evaluate始终消费本任务已取得关系及事实，不以“重新prepare整月”作为调用前提；本修正轮不开发第五批入口。

修正轮不承担第五批PG reader、授权、asset/op/job或完整统计收尾；其历史验收见§18.8。第五批计划现已批准，部分reader、授权及事件辅助代码已存在，实际进度见§19.10；第3～4步相关实现先按§19.11修正并验收，完整job及收尾仍待装配。全程按§2.5交接同任务已得事实，不重新读取或审计；历史修正轮通过不表示第五批或正式执行已验收。

文档完整性、本地链接、Python示例AST及差异检查单独执行，不能代替§18次数及性能验收。修正轮只运行隔离回归，不操作正式数据或启用自动化。

### 18.8 修正轮执行与验收

2026-11-04按管理员批准的8步执行，每步完成定向回归后再进入下一步。下列各组存在重复用例，不直接相加；整体结论只在第8步独立审计完成后给出。

| 步骤 | 当前结果与证据范围 |
| --- | --- |
| 1 记录、摘要及参数交接 | 通过。合同107项、历史records28项、bootstrap直接调用57项；其余接口/plan/adapter/完成边界及已有真实响应、跨进程测试已完成定向验证。旧同任务改盘后要求回读的测试改为本任务不重读、新执行首次坏输入仍拒绝。独立复核无遗留记录交接问题。 |
| 2 一次规划及容量 | 通过。新增历史容量14项，bootstrap空间/进度89项，历史records28项及直接接口回归。纯预算及元信息读取验证使用DuckDB 1.5.2临时连接；有/无资格记录、同/异设备、spill、首unit前及下一unit前失败均覆盖。 |
| 3 日数据及共用候选/发布 | 通过。publication25项、candidate相关64项；bootstrap发布/主入口/审计反例39项，摘要命名3项补验与其重叠。单日U、旧两层及新候选首审/摘要次数已核，Silver重新打开正式Raw为0；异字节等价复用和异常即时登记保留。受影响records28及容量14项再验通过；CodeGraph同步后核过共用调用方。 |
| 4 历史源及20日发布 | 通过。源/下载及合同直接回归73项、输入身份3项、records28项、清理/完整性17项、20日批次10项、发布/完成及重入31项、离线集成2项分别有通过证据。非零附件每层实际读回及SHA各1，正式路径SHA为0；零缺口附件/EXCEPT/读取/SHA为0。独立复核未发现其他重复回源或业务审计；各组有重叠，不相加。 |
| 5 bootstrap来源及完整日交接 | 通过。source/records/fragment57项、发布与审计22项、完整任务4项、SHA/空间直接18项及覆盖调用3项分别有通过证据。单片段跨3日首读/SHA各1、日内容摘要各1，正常load为0；新执行相邻日恢复同片段只首读一次。只缺Silver和纯统计均不读原源。固定预检各1，同月子集不重复计数，新事务timeout保留；各组重叠不相加。 |
| 6 覆盖、日期统计及汇总 | 通过。输入/进度/空间49项、公共及可信覆盖内核13项、主coverage原35项及7处定向修正、process4项、真实入口六故障及最终两种旧结果适用性对照/发布记录首验次数均有通过证据，分组重叠不相加。同日覆盖内核1次，包装/summary额外SQL及输入读取0，同版本重写0；非零附件实际首读/SHA各1，零附件无附加EXCEPT/SHA。真实借用坏schema事实不再开文件；最后summary仅S=C=T=0/J一份记录预算。 |
| 7 已有活动任务查询参数 | 通过。13项验证默认五状态、内部三状态、存储过滤先于limit、排除自身及两job各一次/limit2，不按T过滤；终端bootstrap原入口及首次提升检查不变。未新增PG reader或第五批装配。 |
| 8 整体回归及独立审计 | 通过。17文件407项组合中403初过；2处旧消费者按当前合同迁移后补验通过，2项仅本机临时HTTP端口权限受限，沿工具权限运行后通过。另补2项run诊断首读/符号链接回归。受保护runner的1/6/12/113项全部通过，隔离策略未绕过。默认Ruff覆盖本轮49个Python文件、全项目致命错误基线及文档检查通过。交叉独立审计发现的最终路径漏查已按既有规则修复，无未修确定问题；第五批未推进。 |

以下按硬口径核实现位置、测试及结果，不将每步重叠用例累加成新的总数：

| 步骤 | 当前实现及消费关系 | 实际验收 |
| --- | --- | --- |
| 1 记录/摘要交接 | run_contracts封闭类型；bootstrap_records与io/history的known_records贯穿主入口、writer和consumer。SourceComplete/manifest/plan直接交对象与首次摘要，公开首次输入检查和内部已核保存共用实现。 | history_records的test_written_records_keep_first_payload_and_parquet_facts、test_fresh_record_reader_reads_bytes_and_parquet_only_once，bootstrap_records的test_json_first_bytes_and_approval_digest_are_shared及test_approved_counts_reuse_first_rows_and_digest；首次坏输入、跨run/路径及零引用反例保持。 |
| 2 一次规划/容量 | io/history.py的resolve_stk_factor_pro_history_units、plan_stk_factor_pro_history_publication_dates、build_stk_factor_pro_history_space_check只首次得到本次unit/N/预算；同一check_space贯穿下载、候选、发布及统计。 | history_space14项独立字面预算；源文件与总关系同时存在、同设备余量一次、spill不重复扣、下一unit前不足即停。最后summary为S=C=T=0、J仅一份必要记录；不扩大账户额度或限频职责。 |
| 3 日数据/共用发布 | io/candidates和checks保存首次U/B/audit，publication继承候选及原摘要，Silver消费RAW_EXPECTED，正常移动后不复审正式副本。 | publication的test_complete_day_reuses_source_old_files_and_unique_candidate_audits、test_first_candidate_transport_corruption_is_rejected_before_formal_publish；同时验证真正新输出错误仍被首次审计拒绝。 |
| 4 历史/20日 | download逐unit首次实际读回并入H；publisher每20日筛H一次，逐日两层，最后仅已有targets/audits形成完整记录；三个再核边界只比身份。 | 原batches10项与integration2项；1/20/21/41/45日对应1/1/2/3/3次筛选，45日20/20/5；源含T但正式T不改，真实新进程重新下载原完整范围，旧源/候选读取为0。小型组件unit_id协议核对保留，不另算业务范围或重读文件。 |
| 5 bootstrap来源 | source固定预检首次一次、事务timeout保留、同月已核计数复用；fragment实际关系到DAY到process直交，原源恢复仅首次必要加载。 | fragment_verification的test_normal_three_day_task_reads_source_once_and_hands_same_facts，以及process的test_small_cross_batch_source_hands_each_complete_day_to_real_process、test_new_task_restores_saved_complete_source_once_before_publication及真实子进程：正常load0，只缺Silver/纯统计源0，确需重建Raw才首次源读1。 |
| 6 覆盖/合计 | coverage首次prepare/compute、pure evaluate/write/update，公共首次检查和可信固定投影共用同一集合core；主入口唯一date_results及summary_state，真实replace/complete/result分开登记，逐日贡献按版本更新。 | coverage的test_replay_zero_keys_zero_result_rewrites_and_global_hash_reuse、test_nonzero_diagnostic_saved_once_in_run_t_or_operation_history、test_real_control_failure_summarizes_registered_facts_without_reauditing等；core1、包装/summary额外计算0，非零单份，零附件无附加EXCEPT/SHA。六种真实入口故障、3→5保存失败与等价引用失败均核已有文件/原导入/当前覆盖/摘要；同日未持久结果不计成功，适用旧结果不误清。真实history坏schema事实到coverage仍只首读/SHA一次。 |
| 7 活动任务 | 既有readiness reader默认五状态，内部可传固定三状态；状态先入RunsFilter，require及终端bootstrap两次维护检查保持。 | bootstrap的test_three_running_states_filter_before_limit_and_exclude_only_own_run及原五状态/错误查询反例，13项通过；两job各一次、limit2、不按T筛选。 |
| 8 最终闭合 | 独立审查方交叉阅读非本人模块，CodeGraph explore/impact及sync/status核调用方；人工核代码、SQL、关系所有权及原方案/LLD。 | 407项组合的4项均有精确补验，另2项路径回归及132项受保护治理/Definitions测试通过。34个Python文档片段可解析，66处现有函数声明的参数及必填性与代码匹配；修正3处旧声明，未来第五批通知参数只保留在对应未来要求，不混入第三批现签名。 |

独立审计最后确认的run诊断引用路径漏查已按原路径规则补齐：两种归属都对最终文件路径使用既有安全检查。正常旧run引用首次明细SQL/SHA各1、同任务再次消费0；实际diagnostics父目录符号链接在SQL/SHA前拒绝，未加新安全机制。

本轮验收只证明获准模块的代码、合同与隔离执行符合新规则。公共下载器及261字段、分页未变，未创建第五批PG读取/授权/job/repair/sensor/catalog，未写正式数据或启动DG。后续按第五批详细计划review推进，不能将本轮通过当作正式补数、历史事件或自动化执行授权。

本轮真实源新增请求、正式Lake/数据库/Dagster写入均为0；已有真实响应仅在临时资源中重放，不宣称正式运行或全历史性能已验收。

正式旧bootstrap记录和诊断附件本轮未读取、未迁移。引用中的creator_run_id及非零附件的ts_code/trade_date列序按本文唯一合同执行，不增加旧格式兼容分支；代码与隔离测试通过不代表正式存量已经一致。后续获准正式执行时，首次核对实际需要消费的记录及附件，格式不合约应明确停止并交管理员处理，不能据本轮结论跳过，也不因此开展全量历史数据审计。

第4步的有界成本已使用原261字段、一股五日响应在临时目录重放：总源关系5行，保留T但只发布此前4日的8份两层文件；其中一个旧日期文件含5,568行，独立核对其他5,567只股票业务值不变。源unit首次Parquet读取及文件SHA各1次，发布和最后完整记录阶段重新读取/摘要该源均为0；20日批关系筛选1次，候选实际输出8次、正式替换8次。正常链本次观察3.55秒，包含独立结果验证约0.90秒；实际进程退出后，新进程完整重新下载同一范围并完成约2.54秒，读取旧run源/候选为0。计时仅说明这个样本，不外推全历史吞吐；SQL次数和Parquet查询次数也不等同物理磁盘读取次数，测量用查询与业务查询分开计数。两条隔离集成测试及本步其余定向门禁均已通过，完整范围见上表。


## 19. 第五批：完整日更、手动历史repair及上线前初始化收尾

### 19.1 既有完整链的实现基线

第五批已完成观察/身份、DG记录读取、唯一覆盖结果、上线前初始化授权及统计交接、日更job和独立历史repair装配，并完成临时实例验证。实现日期和提交在后续实际记录中保留。旧日补采步骤、部分日发布预期和自动补前日约束已删除，现行配置、代码前置及验收集中在§21。

### 19.6 已有完整日更与历史规划入口

assets/stk_factor_pro.py的_plan_history读取目标T/P股票复权因子并复用同T既有范围，日更job承接两资产和两检查。新准入和人工日期入口按§21迁移全部消费者，历史比较及授权范围算法沿§5执行。

### 19.10 本批逐步执行记录

管理员已批准按八步实施，第六批及正式资源仍不在授权范围。第1步已完成：新增11项真实临时Dagster事件库回归及受影响既有测试合计124项通过；其中两项本机HTTP测试首次因监听权限失败，经工具授权只补验这两项后通过，不访问真实来源。原观察引用/首次退出/重执行身份/关闭重开/错误引用和不重复查询均有代码与测试；尚不据此宣称整个第五批验收通过。第2步开始前已核_load_basis实际调用方及schema/身份生产者；原月控制和统计writer留bootstrap，只提取只读依据部分。

第2步组合回归83项、补充30项及末次定向3项通过（范围有交叠）；第3步既有覆盖48项、补数/记录21项通过；第4步发布/批次/清理49项、真实文件事件3项通过。历史比较结果交接的9个直接测试消费者分两组回归61项及101项通过；发布事件metadata补齐后3项定向补验通过，Ruff、文档完整性及空白检查通过。CodeGraph已sync并核历史规划影响面，动态/测试引用由实际调用补查。§19.11的接口修正和定向证据见§19.12。第5～8步及整批验收见§19.13。


### 19.11 已确认的入口、覆盖计算及记录收尾分工（2026-11-05）

本节已获管理员确认，是第五批相关代码及测试后续修正的依据。第3～4步相关接口及直接消费者已按本节修正，既有验证证据及首次回刷接线见§19.12。恢复顺序固定为第3～4步修正/定向验收→第5步完整日更及Catalog→第6步独立repair→第7步实际job整链与中断验证→第8步最终独立审计；第1～2步仅回归受影响部分，不重复旧来源实验。

**职责边界。**

| 层次/位置 | 输入与输出 | 禁止混入的职责 |
| --- | --- | --- |
| bootstrap原入口及其原传输/恢复步骤 | 原批准、SourceComplete、原两层导入完成事实；忠实导入时核源/Raw/Silver一致。仅本地统计已有补数文件时沿已核当前事实，不重放旧Prod源。 | 不用可空DG对象、文件是否存在或事件编号推断正在执行哪种业务。 |
| asset/op初始化用途分支及授权resolver | 既有purpose=bootstrap_supplement；其重执行/上线前repair沿明确source_run用途及既有授权。处理日数据、必要历史及初始化统计。 | 不新增is_bootstrap开关，不从同T任意记录猜用途，不让普通日更/repair读取初始化记录。 |
| 共用只读依据和calculate_stk_factor_pro_coverage | 当前日期、已有Raw代码关系及coverage_inputs，输出既有七键calculated。 | 不接原Prod数量、SourceComplete、approval、purpose、CurrentPublication或DG编号；不授权、不选择流程、不保存DG事件。 |
| 初始化单日准备及诊断收尾 | prepare只提取本次audit和单日依据；现有初始化compute复用一次集合计算，调用原诊断writer保存非零明细。 | 不要求先有DG引用，不复制集合SQL，不为了保存明细再计算计数/样本；原input_digest只用于受控附件路径。 |
| 现有evaluate最终记录构造 | prepared、唯一calculated、原SourceComplete/approval_digest、已得input_digest和已保存DG引用，输出完整DateCoverage。 | 不读文件、不查PG、不执行SQL、不重新算摘要；不修改prepared补事件，不先造缺编号的最终记录。 |
| 现有update_after_publication/write及summary | 最终result、原记录身份和本任务日期条目/合计；保存成功后替换贡献。 | 不再收prepared/publication/两层audit重复交叉核对，不重新prepare、计算覆盖或求和全部日期。 |

准确签名、prepared字段及合法无文件分支以§10.5.6～10.5.7为准，本轮源码及直接消费者已同步迁移。_prepare_stk_factor_pro_coverage_date_from_facts中原先混合原导入、补数、DG事件的职责必须移出；保留私有提取函数时只做当前事实提取，不加用途bool/枚举来延续混合分支。通用最终记录类型及parser只维护字段/引用结构；“原源必须等于原导入数量”放在明确的原传输入口，不根据current_publication的空值选择业务。

**完整顺序。**

1. 入口确定场景并完成该场景原有授权/输入检查；初始化专用原记录只首次加载一次，普通用途不加载。
2. 当前日期按已有Raw→Silver发布及文件检查处理，audits、行数、关系和摘要直接交接，不新增审计。
3. 初始化实际影响且在原批准范围内的日期，用现成Raw及单日依据计算一次覆盖，按需保存一次非零诊断；T的普通RawCoverage与初始化统计共用同一结果。未知保留None/原因，零差集不落附件。
4. 当前批字典只保留prepared、calculated、诊断引用及所属入口已持有的原事实；释放当天业务关系。最多沿原20日批次，不累积业务明细，不在此构造DateCoverage或更新有效合计。
5. 历史批末保存本批DG物化/check，首次取得的真实引用直接复用；日T的事件已按§4随逐层发布保存，不能在此步骤再次发送或查询。引用只定位执行记录及对应检查，不是股票/因子行的新业务编号，也不是覆盖计算前置。
6. 事件已保存后调用现有evaluate，关联实际引用并构造最终日期记录；只在此做一次本次引用与已有audits的对应核验。然后现有writer保存，成功后替换本日旧贡献，summary直接消费同一totals。无独立绑定接口、额外编号状态、编号等待队列或中间最终记录。

上列顺序中的批末事件步骤仅适用于历史；三种场景的准确时点见§10.5.7顺序表。日T不得改成历史批末事件，原bootstrap物理导入不等待正常DG事件。共用的是计算算法，各自授权、传输及最终记录收尾保持独立；本次小结果不成为跨run的下载续跑依据。

**数量与例子。**原导入计数不可变，当前计数来自本次有效合并。独立人工样本固定同一日期的原Prod模拟源只有A共1行；初始化补数给出A/B/C，当前Raw/Silver各3行，原source_rows仍1、当前raw_rows/silver_rows为3。按既有主键更新/补入并保留源未返回的合法旧行，不以本节为由删行或无条件接受任意数量。“1→3”仅为隔离小样本，不是Prod实测或真实Tushare补数结果。原源0补出数据同理；合法无文件零实际沿§10.5.7，不伪造audit/CurrentPublication/check。

**失败及恢复。**

| 情况 | 动作 |
| --- | --- |
| 文件处理或原检查失败、只Raw完成 | 保留已发布文件，报告实际完成层；不构造两层完整统计。若旧当前结果因实际文件变化失效，沿原日期条目标未知，不猜两层已齐。 |
| 日代码不齐或依据未知 | 源端不齐不提交；正式日源/候选不齐在首次提升前停止。历史repair仍核原T已有两层。 |
| 覆盖已算、DG事件尚未保存 | 保留本次小结果并正常完成原事件步骤，不阻塞计算、不伪造编号，不提前登记最终执行完成。 |
| DG事件保存失败 | 如实报告事件失败，已发布业务文件不回滚；不把未保存事件写成成功，不为取编号再审业务文件。 |
| result/summary保存失败 | 保留已发布文件和已保存事件，不重算或回滚；保留原错误，不伪称记录完成。 |
| 取消、硬退出或获准重执行 | 沿既有关闭/失败规则；新Tushare run完整重新下载原T/原失败历史，不复用本次内存结果、旧源或候选。不增加断点续传。 |

**直接实现及消费者迁移。**

| 位置 | 实现要求 |
| --- | --- |
| bootstrap/stk_factor_pro_bootstrap_coverage.py的两种日期prepare | 接口按§10.5.1/10.5.7同步改，输出同一当前事实布局；原传输数量检查回原入口，共用准备不接事件或原源。 |
| 同模块compute/evaluate/update/write | compute接已得input_digest并复用集合core一次；evaluate在记录收尾显式接原事实及DG引用；update仅保存最终result。所有消费者同次迁移，不留旧参数兜底。 |
| bootstrap/stk_factor_pro_history.py | _save_prepared_bootstrap_coverage、_complete_existing_bootstrap_coverage、process_stk_factor_pro_bootstrap_complete_date等实际调用方，分别交接当前prepared、唯一calculated及所属入口已得原事实，不能把这些重新合成一个混合prepared。保留直接bootstrap原恢复及仅本地复算边界。 |
| run_contracts/stk_factor_pro.py及parser | 保留持久字段和已有记录可解析性；移除DateCoverage.__post_init__里根据DG对象空值选择原源数量规则的行为。普通字段结构、日期和引用对应约束保留，调用入口负责原传输/初始化补数要求。 |
| 待装配asset/op | 按既有purpose或明确source_run选择流程；在日关系释放前持有唯一小结果，事件保存后只构造/保存最终记录，不调用新的编号绑定层。 |
| 直接测试 | 原传输数量差额的反例必须走真实原导入入口，不能继续用“prepare缺DG对象应拒绝”证明正确性。合法新增行、相同计数但新事件、无事件可计算、记录失败等分别按本节独立预期验收。 |

**实现范围与验收。**后续只修本数据集原准备/构造/保存函数、相关record/parser规则、bootstrap/asset/op直接调用和测试；不改公共下载器、261字段、分页、路径、DG表结构、配置或其他数据集。保留CurrentPublication和DateCoverage已有持久字段；调整使用时点及职责，不新增记录实体或格式兼容。

| 必须验收 | 独立预期及读写要求 |
| --- | --- |
| 原bootstrap传输 | 源1行却漏搬或多搬仍在原入口拒绝；合法等量及合法原空源通过，不靠DG对象是否为空决定规则。 |
| 初始化补数新增行 | 上述1→3及0→有行的合法样本可先计算，原导入事实不改，当前数量/缺口正确；不是复制一条股票记录。 |
| 无事件时的计算 | 覆盖计算不传DG对象/编号即可得出结果；DG未保存不构造虚假最终成功记录，不出现事件查询。 |
| 关系释放及最终构造 | 本日关系释放后，仅用同一calculated和真实引用完成evaluate/write；该过程SQL、业务文件读取、覆盖重算均0；错日期/文件关联在最终构造处拒绝。 |
| 次数与复用 | 同输入业务审计、覆盖计算、非零明细/样本各首次一次；两类记录包装不新增计算，0缺口0附件，summary不重新读取或求和。 |
| 入口及失败隔离 | 普通日更/正式repair初始化调用与文件IO为0；Raw-only、事件失败、统计失败不回滚业务文件、不造完整成功，重新执行仍新下载。 |

以上为当前采用的接口与职责要求。接口修正的验证见§19.12，完整第五批隔离验收见§19.13。

原方案及本LLD的接口表、Python接口示例、执行顺序和记录要求与本轮修正同步核对；恢复开发后的验证及未完成项以§19.12为准。

### 19.12 接口修正证据及第5步首次回刷接线（2026-11-05）

本轮修改bootstrap_coverage中的两种prepare、compute、evaluate、update，原bootstrap_history直接消费者，DateCoverage的通用结构约束及对应测试。prepared只保留当前数据事实；入口将原来源、批准及首次input_digest单独交接。compute只委托readiness.calculate一次，不再复制集合SQL；旧有效记录只提取counts/样本/引用供最终构造，同内容不重写日期记录。update仅消费最终result，不再接prepared/publication/audits重复核。合法空原源由原入口明确处理，不向要求真实两层audit的prepare传None。

原导入传输数量约束仍由明确的原bootstrap入口负责；本轮没有放松源到Raw、Raw到Silver的既有传输检查。DateCoverage/parser只维护当前两层、字段和引用结构，不用DG对象空值推断用途。新隔离例子原源A共1行、当前A/B/C共3行，期望source_rows=1、raw_rows=silver_rows=3、缺失0；不提供DG编号即可计算，在日关系释放后只用calculated及真实引用构造最终记录。清理异常不覆盖业务异常、所有所属临时表均尝试释放；测试针对实际I/O清理故障，不主动篡改内部已核数据。

本轮测试结果记录在本节收尾；不把中途失败/已中止的测试轮算通过，也不把纯函数/隔离事件验证说成实际job已完成。原测试test_initial_authorization_and_explicit_precheck_reexecution实际只核首次授权，现按实际覆盖改名test_initial_authorization_rejects_wrong_result_digest，不再用名称暗示原生重执行已验收。

**第5步采用以下接线和查询预算。**起点规则见§5.1.1，Prod全量导入日期证据见方案§3.2。日期集和起点在job内首次需要时取得，并在同一任务内直接交接。

1. **先复用旧范围。**本次T/P比较沿§19.6取得一次。将需要解析的股票与§6已有引用指向的、已核验的`history-ranges`对照。同一旧计划和范围按原引用只加载一次，起点准备和builder复用同一份任务内结果。仅对剩余缺可信起点的股票生成去重代码集合，集合为空则结束起点查询。手动repair沿原授权范围，起点补查次数为0。
2. **按入口取一次日期。**普通日更和普通原生日更重执行，复用本任务已有的Raw物化日期集合。首次缺该集合时，最多调用一次`instance.get_materialized_partitions(dg.AssetKey(STK_FACTOR_PRO_RAW_ASSET_KEY))`。以§10.6的历史事件补全为上线前提，使用已加载的开市日历核对不晚于原T的Raw物化日期。仅注册但未物化的分区不进入集合。初始化补数用本次已经加载的`approved_counts`和`date_results`，取不晚于原T且已有可信Raw的日期。原导入有行的日期必须纳入，原源0行但已有有效补数Raw的日期也纳入，已确认无文件的空源日期跳过。完整日期集合缺乏可信依据时按§5.1.2记录未知，禁止丢掉可疑日期后用剩余文件推算。初始化入口为起点解析增加的DG日期查询、bootstrap记录读取均为0。
3. **只补必要的文件类型事实。**用`raw_stk_factor_pro_path`按唯一日期映射文件，保留既有路径约束。应有文件缺失或键列缺失、类型不符，沿现有错误语义停止。任务内已有通过的`StkFactorProFileAudit`且`factor_file_identity`对应时，直接复用`observed_schema`中的两个键列类型，额外摘要计算为0。其余文件参考`defs/io/stock_period_raw.py`现有`parquet_schema(?)`列表用法，最多一条元数据SQL。按`file_name`归组，仅返回`column_id>0`且`name`为`ts_code`或`trade_date`的`name/duckdb_type`，要求每个预期文件两列各一条，类型均为`VARCHAR`。全部可复用时跳过此查询。`resolve_stk_factor_pro_history_starts`使用本步骤的集中元数据查询发现混合文件类型或缺列。
4. **所有缺起点股票共用一条聚合。**把已确认路径、日期和缺起点代码一次传给现有起点函数的批量查询，只投影`ts_code`和`trade_date`。原有日期合法性和文件分区一致性检查随`MIN`同批返回。返回最多每股一条，直接传给builder并存入既有`history-ranges`。后续规划、发布和验收复用本任务的结果及已有文件身份。业务合并只读其必要数据，禁止另开逐股或逐日查询重算起点、重复查已核类型、另扫全字段或为估算成本执行计数查询。

| 起点解析场景 | 新增DG日期集合调用 | 批量键列元数据SQL | 两列数据聚合SQL |
| --- | ---: | ---: | ---: |
| 无待处理股票、起点均已知或手动repair沿原授权 | 0 | 0 | 0 |
| 日常首次缺起点且可信Raw范围有效 | 至多1次，本任务已有则0 | 至多1条，类型均已核则0 | 1条 |
| 初始化补数首次缺起点且可信Raw范围有效 | 0 | 至多1条，类型均已核则0 | 1条 |
| 范围或文件在聚合前确认不可用 | 至多一次必要的范围获取 | 文件条件不足时0，遇类型冲突只保留该次校验 | 0 |

表中计数仅针对起点解析。必需的job前置读取沿原流程交接。文件上界取该任务确认的日期集合大小，数据聚合最多访问每个日期对应的两列；DuckDB内部实际读取字节及耗时按既有性能门禁实测。此路径使用现有连接和任务内对象，没有额外源请求、临时明细或新持久状态。若完整可信范围超出运行预算，按既有失败规则报告，保留全范围要求。

**验收。**在隔离job测试中分别记录DG日期集合调用、键列元数据SQL和数据聚合SQL，按表逐项断言。覆盖同轮多股缺起点、已有起点、初始化合法无文件日和原空源后已有补数、缺原早期文件、混合文件键类型、日期与分区不符。一次聚合后让builder和后续步骤消费同一结果，断言无再次读取旧范围或重算起点。正式读取仍按既有全局读取审批执行。实际job计数及第6～8步结果见§19.13。

第3～4步接口修正的定向回归为10个文件共210项全部通过，执行覆盖bootstrap_supplement、bootstrap_coverage、publication_events、readiness、recorded_results、bootstrap_records、bootstrap_process、bootstrap_contracts、bootstrap_progress和bootstrap_coverage_inputs。使用项目现有解释器，pytest关闭缓存，全部样本/事件库/Parquet及测试输出位于/private/tmp；没有安装依赖或新增真实Tushare请求。将共用算法接入原月处理后发现停牌投影缺少当前日期过滤：test_month_coverage_uses_only_target_day_suspend修正前失败、补trade_date参数后通过；次日未知代码不再污染本日覆盖。依据未知时直接记录未知，不要求为不执行的集合运算另取Raw关系。旧类型测试中根据DG对象空值推断原导入的断言，按§19.11迁移为结构/解析验证；原入口传输不一致反例仍通过。

Ruff、两份文档完整性和git diff --check通过。CodeGraph在修改前核入口影响面，修改后sync/status及evaluate影响面核到_save_prepared、_complete_existing和process_complete_date；另用rg及人工核对动态测试调用方、两个prepare/compute/evaluate/update的参数与所有直接消费者。共用算法仍在readiness，原导入授权及统计writer仍在bootstrap，未增加跨工程依赖。该组证据适用于第3～4步接口修正和原调用链。两个job及重执行整链的证据见§19.13。


### 19.13 第五批第5～8步隔离验收（2026-11-05）

| 顺序 | 实现与验收 |
| --- | --- |
| 第5步 | 完整日更job、两资产、两check及Catalog已装配。现行源端门槛、指定日期及发布前完整性另按§21补齐。 |
| 第6步 | `defs/ops/stk_factor_pro_history_repair.py`和对应job装配四字段授权。原T Raw/Silver失败均先记录实际结果，退出时零请求、零物化。修复沿已保存的完整授权重新下载，只写d<T；原T文件保持原内容，成功解除对应历史失败，已完整成功的同范围再次提交为no_action。上线前初始化repair经精确授权更新实际受影响日期统计，原T记录及原导入数量保持真实。 |
| 第7步 | 临时Dagster事件库及Parquet上，用已保存的一股五日261字段响应重放正常日更和硬退出后原生重执行。旧子进程在历史Raw发布后退出，隔离测试按实际退出登记终态，再由另一个进程执行新run。两次各新发1次日请求和1次完整历史请求。对旧源与候选的SQL及文件读取设反向断言。发布的日期、两层物化及绑定检查、Raw字符串/Silver DATE、NULL、负指标及未参与股票值均核对。 |
| 第8步 | 按入口、输入来源、发布/收尾及错误分支重新对照方案和LLD。日发布按§21完整代码门槛执行，历史批次观察保留已绑定结果及当前真实来源摘要。治理测试登记两项内联检查，继续核真实定义与Catalog一致。CodeGraph核到日更、repair、历史规划及发布和DG事件读取边界，动态定义装载以受保护测试为准。 |

起点读次数按一次实际job统计。先复用旧范围，首次必要时一次取DG Raw物化日期集合或复用已经加载的初始化批准日期，只对未经同一文件身份校验的文件集中核类型，所有待查股票共享一条两列聚合。

| 实际运行场景 | DG Raw日期集合 | Parquet键列元数据 | 两列起点聚合 |
| --- | ---: | ---: | ---: |
| 日更两股首次缺起点，使用两份已物化Raw | 1 | 1 | 1 |
| 同一原T后轮已有可信起点、无变化的日更、独立repair或原生新run复用起点 | 0 | 0 | 0 |
| 上线前初始化补数首次缺起点 | 0 | 1 | 1 |
| 早期已物化文件缺失 | 1 | 0 | 0 |
| 键类型冲突 | 1 | 1 | 0 |
| 键日期与分区不符 | 1 | 1 | 1，同一聚合返回不符证据 |

小样本实际成本见下表。行数为两次离线请求的2行日数据和5行历史数据；后者包含T，发布计划为T日两层及此前四日两层。Parquet项统计业务SQL调用，SHA字节统计被观测文件的哈希输入；空间为临时staging在原子替换边界的实测值，重执行包含保留的旧证据。计时包含临时运行环境准备和任务本身，最后小范围结果读回单列。

| 样本 | 离线请求 | Parquet SQL / 批源查询 | 候选COPY / Lake文件原子替换 | SHA次数 / 输入字节 | staging峰值（字节） | 实际耗时 / 最后读回（秒） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 正常完成 | 2 | 21 / 1 | 10 / 9 | 17 / 441071 | 152609 | 3.80 / 0.016 |
| 历史Raw后退出 | 2 | 14 / 1 | 3 / 2 | 10 / 197837 | 98994 | 2.15 / 未进入 |
| 新进程原生重执行 | 2 | 23 / 1 | 10 / 7 | 20 / 516782 | 326830 | 4.11 / 0.017 |

完整两次运行均得到10条物化和10条绑定检查。首轮历史内核定向回归337项，末次日更、repair、整链及直接消费者回归43项，起点、初始化覆盖和repair追加定向回归68项，两组范围有交叠。受保护的定义、资产目录、检查登记及运行契约分别1、12、6、113项通过。实际数据和事件均在临时目录与隔离实例，真实Tushare网络请求为0。正式实例装载、初始化验收、历史事件补录和启用按后续阶段的既有授权和顺序执行。

**第五批收尾。**§6.2的历史失败顺序已在`read_stk_factor_pro_recorded_results`实现。隔离回归使用实际日更和repair任务及临时Dagster事件库，下载替身让日更历史返回临时源错误，随后repair发现原日期Silver缺失。修复前读到旧日更run，修复后读到新repair run并确认不可自动重试，已有日结果仍归原日更。该次读取查询任务列表1次（limit=2），查询观察2次（各limit=1）。同组回归验证较新日更未写历史观察时仍由终态补足，首次观察前退出仍可见，repair成功仍可解除对应历史失败。结果读取、repair、日更和第五批整链的31项定向回归通过，新增用例另行复核通过，包含在这31项范围内。Ruff与文档检查通过。验证使用临时资源，真实Tushare请求和正式DG及Lake写入均为0。

## 20. 第六批：自动追修、分区注册和更新sensor

### 20.1 依据和开工范围

对应技术方案§13.12。以§19.13已经隔离验收的日更、手动repair和结果读取为入口。按下述第1～5步依次实施，每步通过定向回归和代码核对才进入下一步。第1步独立使用已有job及临时实例，第2步独立验证分区请求，第3步消费前两步的接口。第4～5步完成隔离串联、Definitions及治理验收。

使用现有分区、资源、任务配置、检查和失败记录。本批开发范围是本数据集的追修接线、两条sensor和对应治理登记及测试。第1～5步使用临时实例和文件，复用已保存的有界样本。正式code location装载单独授权。Prod搬迁、上线前补数实际执行、历史事件补录及正式sensor启用走§10.6，不是开发步骤的前置，也不由测试触发。

### 20.2 第1步：日更job接好自动追修

本节保留该步已完成时的实现与隔离证据；日发布现行准入及新sensor读取方式按§21，不再以当时允许部分日发布作为后续要求。

1. 在`defs/asset_guards/stk_factor_pro_readiness.py`复用§6.2的直接阶段读取。追修比较的唯一旧输入是`day_result_ref`所指的有效日阶段观察及该观察自身的`history_plan_ref`。使用同一`known_pg`、`known_records`，将计划解析和引用核验按§3.6交给现有历史计划读取链。把两个已核SHA交给比较处。历史完成和未完范围继续从当前DG结果取得，repair的历史结果仍可用于它授权范围的完成判断。
   日更job核旧日发布时，按日观察所属run一次读取最早两条`ASSET_CHECK_EVALUATION`。日Raw和Silver检查先于历史阶段，用这两条绑定结果及文件摘要核对原日发布。这是第1步当时允许部分日发布的实现依据，现行入口已改由§21要求完整日发布；新run启动时登记的待执行检查不作为旧日发布的证据。实际文件摘要在同一run内复用，后续发布读取当前文件时沿用已有摘要缓存。
2. `defs/assets/stk_factor_pro.py`在保存本轮历史名单前把是否发现修订交给`defs/io/stk_factor_pro_history.py`的现有planner。比较使用本轮已经准备的T/P文件引用。仅自动`today`按§3.6追加和继承`HistoryPlanReason.SAME_NIGHT_FACTOR_REVISION`。新增原因落在`defs/run_contracts/stk_factor_pro.py`，范围读取校验同时接受原1～6和新值。job配置、文件列、日期范围和下载入口沿用原接口。
3. `defs/io/stk_factor_pro_publication.py`在历史源已经完整确认、进入现有源清理范围后，创建首个候选前完成追修比对。资产入口交接已经加载的T/P关系与本轮`expected_units`中带追修原因的股票。以`ts_code`和规范后的同一`trade_date`连接，比较双方非NULL的`adj_factor`，同一批只执行一次。自动追修历史使用该次比较结果排障，移除这一路径原先对同一历史源另做的T日诊断查询。日阶段和普通历史诊断沿原流程。差异由现有历史阶段失败出口按§3.6保存完整待刷范围和可重试原因，确保该分支释放本次源关系。执行中止后，下一轮全新下载失败范围。

**本步验收。**用现有job证明日成功、历史失败后日观察仍有效。随后手动repair成功，日观察的计划来源仍保持原值，repair结果只用于原授权历史。断言追修历史比对一次、旧因子时零历史候选/发布/事件，仍有日发布和可重试记录。下一轮继续拿到旧因子时仍保留完整范围，源值更新后两层历史发布完成。核对历史只写d<T、停牌缺T行照常处理、repair无T日写入以及已独立成功范围无需重读历史文件。

**隔离结果。** 在实际日更job、临时Dagster实例和临时文件中，复用已有一股有界源样本，分别只修订T或P的权威因子。前两轮模拟对应日期的历史源仍旧，每轮各执行一个日下载、一个完整历史范围下载、一次历史因子比较，保存两条日物化和两条日检查，历史候选、物化、检查均为零。第三轮重新下载同一股四个交易日的原范围，历史源实际返回早于T的三行，成功保存三日共六条历史物化和六条绑定检查。手动repair隔离回归确认新历史计划不会替换旧日观察的T/P摘要。该验证使用下载替身，真实Tushare请求为零。

### 20.3 第2步：独立注册今天及上个交易日

在`defs/sensors/stock_factor_pro_trade_day_sensor.py`定义`stock_factor_pro_trade_day_sensor`，使用`STK_FACTOR_PRO_PARTITION_SENSOR_INTERVAL_SECONDS`和`STOPPED`。从现有lake root和`DuckDBResource`获取Silver交易日历，使用上海日期D。先取SSE的D日记录，D已确认开市才作为候选。上一交易日Q以D日的`pretrade_date`为准，只在它早于D且对应的SSE记录确认开市时登记Q。缺少Q记录或无法确认Q开市时，保留已确认开市的D，不改用更早日期。D日记录缺失或开市标志未知时不登记。对最多两个候选键通过本数据集的`cn_a_stock_factor_pro_trade_days`查询是否已登记，只把缺少键排序后交`build_add_request`，由`SensorResult.dynamic_partitions_requests`返回。无需上游资产就绪，不创建RunRequest。

每次评估用一条日历查询，在同一份Silver交易日历Parquet中按D及其`pretrade_date`匹配所需SSE记录，返回D的开市标志和确认的Q。用现有lake root定位日历文件即可，评估不需要探测写入权限。重复评估沿用同一条查询和逐键登记检查，中断后只提交仍缺的候选键。定义会随现有Definitions加载，所以本步同时登记该注册sensor的分类和静态测试名单；第5步再核对本批两个定义的整体装载。

**本步验收。**临时实例证明开市日新增D/Q、已有键不重复登记。已确认休市时仅可新增缺失的Q，休市D和未来日均不登记。增加周一指向周五、周五缺失或未确认开市、周四开市且尚未登记的反例，验证只登记已确认开市的周一。日历不可用时不写入，现有旧键保留。评估只读取日历和候选分区登记，不读因子、技术数据、任务及事件记录。

**隔离结果。** 使用当前Silver日历schema的临时Parquet和临时Dagster实例，核对开市、休市、缺SSE当天记录及缺日历文件。每次评估执行一次日历查询，按有效候选逐键查询登记状态，至多两键。已有旧键保留，重复评估无新增，所有分支均无`RunRequest`。本步定义装载1项、运行合同静态治理113项通过。第1、2步及直接消费者最终定向回归合计218项通过，含本步及现有股票分区注册测试。正式DG、Lake和Prod未参与验证，整链成本按第4步验收。

**上一交易日补强验收。** 使用临时Silver交易日历Parquet复现周一指向周五、周五缺失或休市、周四开市且尚未登记。旧实现三个反例均误选周四。改用`pretrade_date`后，周一开市只登记周一，休市则不新增分区。股票日线技术因子及现有股票分区注册的定向回归共8项通过，每次评估仍执行一条日历查询，至多检查两个候选键。

### 20.4 第3步采用新日更规则

现行目标、代码、配置与成本见§21。先完成完整日发布前检查及人工指定日期入口，再接源端代码齐备sensor。原自动补前日选择、提交序号、机会恢复和部分发布验收退出本步。

### 20.5 第4步隔离串联与读回

按§21.7串联临时实例、两列源端等待、完整日发布、午夜形成缺口、人工指定旧日补跑及原有复权历史追修。分别记录源端请求、本地依据读取、PG查询、正式提升、失败全范围重下和最后读回的数量与耗时。

### 20.6 第5步：定义装载、治理及交付

两条sensor使用`defs/run_contracts/sensor_tags.py`的`build_sensor_tags`写定义`tags`。数据域为`quote_data`。注册sensor使用`partition`和`partition_registration`，更新sensor使用`raw_silver`和`asset_update`。在编码交付中同步运行合同治理和资产任务拓扑的两条登记及静态门禁。资产Catalog沿第五批已有两条资产和分区模型，不另建状态或资产。

**本步验收。**通过`tests/stock_suspend_confirmed_test_runner.py`执行对应受保护Definitions和治理套件。将`test_stk_factor_pro_definitions.py`的第五批“sensor尚未登记”断言更新为验证两个确切名称、绑定、60/600秒间隔、定义标签和默认STOPPED，保留两个资产、两个job及既有检查的核对。按§11.1完成相关回归、Ruff和文档检查，逐项在原方案和LLD记录代码位置、证据与未覆盖的正式步骤。隔离装载验收后，正式code location核验、历史事件补齐及正式启用仍分别按授权和§10.6的顺序执行。

### 20.7 2026-11-06两层缺口的正式状态核验

11月8日只读核验发现正式代码位置已识别技术因子资产及专属动态分区集合，集合登记数为0，注册sensor为STOPPED。日更sensor在正式定义中未找到，11月6日也无原日更任务。正式Raw目标根目录尚不存在。工作区代码的日更入口会在请求源数据前拒绝未登记的目标日。本次保留既定接入顺序，未登记分区或启动任务，两层11月6日仍缺失。

## 21. 源端代码齐备后日更的详细设计（2026-11-11）

### 21.1 目标、代码基线和影响面

本章实现方案§17已确认的变更。自动只处理当天T=D；源端代码与T应有代码完全一致才提交job。新股上市首日代码可选。午夜未齐的日期由管理员指定T补跑，普通补日不依赖原run或初始化operation。

当前代码基线有日更job、手动历史repair、分区注册sensor及既有历史追修。`_published_day`在日文件发布后计算覆盖，`parse_stk_factor_pro_run_input`仍限制自动当天/前日及bootstrap用途；日更sensor未实现。原有实现尚不满足本章，历史批次验收不能代替本章验收。

| 改动位置 | 目标及消费者 |
| --- | --- |
| `defs/source_readiness/stk_factor_pro.py`，待新增 | 固定两列源查询及完整分页；sensor和人工日期预检共用。复用既有HTTP传输、凭据和日期规则，不新增字段子契约。 |
| `defs/asset_guards/stk_factor_pro_readiness.py` | 复用生命周期/全天停牌/身份准备及纯集合计算，将实际侧接收两列关系或当前日源关系。按§21.10在剔除可选首日代码的比较关系中核missing=0 AND extra=0，日更、历史repair及bootstrap当前覆盖同步使用。 |
| `defs/run_contracts/stk_factor_pro.py` | 自动today、人工manual_date及初始化bootstrap_supplement七字段合同；同run身份、序列化、观察和原生重执行消费者同步。 |
| `defs/assets/stk_factor_pro.py`及`defs/io/stk_factor_pro_publication.py` | 手动日期预检、正式日源和最终候选代码校验前移至首次Raw提升前；同一覆盖结果交后续记录/历史，不发布有效部分日数据。 |
| `defs/sensors/raw_tushare_stk_factor_pro_update_job_sensor.py`，待新增 | 只选当天、源端门槛、单slot单job、既有复权追修。 |
| jobs、checks、Catalog、治理和直接测试 | 复用两个资产/两check/现有job，更新运行说明、配置样例、Definitions断言和两sensor登记。 |

CodeGraph已沿日更入口、配置解析、日源下载、Raw候选/发布、覆盖及历史规划核调用关系；另核原生重新执行、初始化授权、手动repair及测试这些共享身份消费者。变更局限DG，不修改Prod数据集定义、跨工程契约、前端/API或其他资产。

### 21.2 源端两列查询与集合规则

目标T由SSE日历确认开市。应有集合仍由`prepare_stk_factor_pro_coverage_inputs`及纯集合算法生成，按目标T的上市/退市区间、确认全天停牌和有效身份映射计算。不能用今天的上市清单补旧日，也不能把历史查询里的退市股票遗漏。身份统一只参与覆盖，不改源业务代码和历史下载对象。

固定请求为`api_name=stk_factor_pro`、`trade_date=YYYYMMDD(T)`、`fields=ts_code,trade_date`，不传股票过滤。沿既有源分页规则，页容量10,000，offset从0逐页加10,000，短页或空页结束；不足一页只需一次请求。取满页时继续取终页，不能把截断集合相等当成源已齐。返回必须只有这两列，交易日期全为T、原主键非空唯一。复用已完成小页分页证据，工程两列完整分页仍须§21.7验证。

两列查询用于业务准入，正式`DownloadTask`和`RequestBuilder`仍使用完整261字段契约。投影请求复用现有`HttpProTransport`的单次请求/余时控制与响应解析能力，源接口名、字段和分页参数固定在本数据集只读探测函数中；不把fields变为运营配置或另建两字段契约。不得直接用缺少本次评估总时限控制的SDK调用替代。

已准备必需集合E、可选首日集合F和实际集合A，三者按T统一身份后去重。先得参与比较的实际集合C=A EXCEPT F，再计算E EXCEPT C及C EXCEPT E，两侧为空才ready。首日股票缺行可通过；首日已有行保留。其他多码不得过滤后假作相等。字段/日期/重复主键错误、依据未知、分页未完整、网络异常或预算耗尽均不能返回ready，查询失败不伪装为空结果。

探测不产生业务物化、资产检查、下载开始观察、历史名单或业务文件。结果返回目标日、ready、总源代码数、必需/实际参与比较/必需缺少/未知多出数量，以及可选首日代码的小摘要、请求数、页数及耗时，完整代码关系只留本次评估内存。全套新股样本及5,573代码/0.526秒实测记在方案§17.2。

### 21.3 sensor、时点、去重和读取边界

定义沿用60秒最小评估间隔、`quote_data/raw_silver/asset_update`分类和STOPPED。按如下顺序执行。

1. 确认正式根、上海日期、SSE开市及19:00至午夜窗口。slot仍按19:00开始每30分钟计算，只处理当前slot。
2. 目标固定T=D，确认专属分区，先用统一builder构造D/T/当前slot的run_key。按本sensor、update job和该确切run_key查询持久run，limit=1；存在任何终态或活动run均不再次提交该slot，不扫描当晚其他slot或恢复提交序号。活动任务沿现有两job各limit=2检查，有活动则当前不提交。
3. 沿§6.2读取同T已有日/历史结果，并复用当轮已取得的run。已有日发布有效且历史完成时，按§3.6比较有效日观察所引用的T/P摘要；未修订即结束。保留原有待刷及失败判定，永久历史失败不靠反复新建日更解除。
4. 确认T/P股票复权因子Raw就绪，以及目标T生命周期、身份和最终停牌的覆盖依据。先复用raw_tushare_stock_basic_ready_for_trade_date及silver_stock_lifecycle_ready_for_trade_date确认输入与生命周期已更新到T，并核生命周期物化不早于所依赖的最新股票基础信息物化，避免两边同时遗漏首日新股。准备应有代码，随后按§21.2查源。源端未齐不提交job，下个合法slot再探测。
5. 源查询返回后再次确认仍为同D及同slot且未到午夜；跨slot则结束本次评估，下一评估按新slot处理。相等才构造一条today RunRequest，partition=T，run_key由现有builder按D/T/slot生成。开始执行仍由job复核自动窗口、唯一写入和本地上游；排队跨午夜零正式下载，午夜前已实际开始的任务可完成。

cursor沿现有factory只保存D、最近已探测slot及小摘要，正常同slot重复评估不重复网络探测。清cursor/进程退出最多重复一次轻量探测；持久自动run及同sensor固定run_key保证同slot不重复job。当前slot尚未取得应有依据时可等本地上游，无需关掉整晚。过去slot不回放，旧日缺口不进入自动选择。

每个评估最多读当前日结果一次、当前slot提交记录一次、活动两job一轮、本地T/P就绪各一次；复权追修需要时读既有小计划一次和两份Raw股票复权因子摘要各一次。生命周期/日历/身份和T日停牌按本连接各准备一次，投影必要列。新增股票基础信息及生命周期就绪的物化/check事实也在本轮复用。禁止重读股票日线技术因子Raw/Silver的261字段来证明源端覆盖，禁止扫描历史技术因子分区或旧tick恢复次数。已有覆盖、检查和摘要在本轮直接复用。

### 21.4 七字段配置与人工日期

配置仍位于`ops.stk_factor_pro.config`，持久于run_config，消费者是输入解析、观察身份、日下载、原生重执行和初始化授权。无新增env、配置表或地址/fields覆盖。以下是目标合同，当前旧合同须在同一开发步骤同步全部消费者。

| 字段 | 自动today | 人工manual_date | 上线前bootstrap_supplement |
| --- | --- | --- | --- |
| execution_day | 原计划上海开市日D | 本次提交的上海自然日期D | 原初始化补数提交日，按§10.7授权 |
| target_trade_date | T=D | 明确选定、早于D的开市历史日期T | 原批准范围内缺口T |
| purpose | today | manual_date | bootstrap_supplement |
| scheduled_slot | 精确整数0～9 | None | None |
| bootstrap_operation_id | None | None | 原operation标识 |
| expected_bootstrap_approval_digest | None | None | 原approval文件SHA |
| expected_bootstrap_date_result_digest | None | None | 首次授权的当前缺口结果SHA |

日期均为ISO日字符串解析成date，T必须等于分区。P由SSE的T日记录中pretrade_date确定，并确认P记录存在、开市且早于T；缺P时等待，不从剩余日期中改选更早一天。manual_date允许无parent首次运行，不要求D开市；原生重新执行保持原T及原用途意图，人工执行使用原有直接parent/root身份核验，额外开始时间另记。原执行日不作为人工跨午夜的拒绝理由。

manual_date及bootstrap_supplement在job内复用§21.2完成一次两列源端预检，未齐返回真实precheck等待，不下载261字段或发布。通过后进入与自动相同的完整日流程。自动job已有sensor探测，不重复两列请求，直接对本次完整日源作§21.5校验。人工日期和初始化用途均走既有维护/排队互斥步骤，目标缺分区时先登记该明确日期，不在job中顺带补全历史分区。

`previous_day`用途、submission_no及business_attempt从配置、RunIdentity、阶段观察schema和全部直接消费者删除，不以固定None保留空字段。开始事实、原生parent/root核验、bootstrap首次授权仍有各自现行用途，继续保留。上线前记录格式收敛、已有正式记录的核对和暂停条件见§21.12，不新增运行时旧字段兼容分支。

### 21.5 从当前完整日源到正式文件

job首次确认目标T的股票基础信息/生命周期新鲜度及输入绑定，再准备T应有代码及依据，保存当前权威股票复权因子T/P生成的完整名单和既有待刷范围。自动job在保存正式下载开始事实前再次核午夜截止，避免名单规划跨午夜后才联网。当前run完整261字段unit在内存核会话、summary及原字段/主键/日期合同后，以其DAY_SOURCE作为A，按§21.10先排除可选首日集合F，再与必需集合E做双向差集。依据未知、缺码或多码立即day失败，正式Raw/Silver候选提升及历史请求均为0。此处复用当前源关系，不能用旧Raw行掩盖本轮缺码。

调用现有Raw候选构造，按本连接RAW_EXPECTED再核，排除可选首日代码后最终集合等于同一E。已有旧Raw多余行会被当前合并保留，若导致额外代码则在提升前停止并说明，旧正式文件留存。普通日更和人工补日均无自动删旧行能力。新日源完整后同代码覆盖的旧值按现有键合并更新；历史d<T仍保留其未变化股票行。

通过后沿既有唯一候选audit、同文件系统os.replace、逐文件完成事实，先Raw T再Silver T。字段值合法NULL按契约保留，新股首日记录可缺，已有首日记录完整保留且无需MA/KDJ/RSI齐值。两层及检查完成后，已有覆盖结果绑定本run实际物化/check身份，交日观察和历史资格，不再读正式副本重算。

Raw提升后Silver失败、取消或进程退出保留真实已提交文件，按现有逐文件恢复。再次执行完整重下T并重新校验，不引入两文件事务或备份。源端未齐时的部分日发布已经退出日更流程；真实执行中断留下的一层文件按失败处理，不宣告该日更新成功。

### 21.6 复权历史、初始化及失败衔接

自动today、manual_date和初始化补日均使用所更新T的权威股票复权因子与P比较，名单生成、历史起点、同T待刷范围、完整历史源、20交易日批次、只写d<T及整范围失败重下沿§3.6、§5、§8执行。更早目标日的人工补跑不能读执行日D的股票复权因子替代T/P。历史失败保留完整T日发布，既有手动历史repair只处理原授权历史，不替换有效日更摘要。

Prod bootstrap沿§10.1～10.5忠实导入全部批准源行并记录已有缺口，不套用Tushare日更准入。上线前bootstrap_supplement仍核原批准及当前缺口，通过新完整日门槛后发布并更新同operation当前统计；源端未齐不写虚假新统计，原导入事实留存。普通manual_date不接入该operation，防止上线后补日变成维护原导入账本。

源探测不齐只是sensor评估等待。完整日下载或候选不齐是本run日阶段失败，更新成功以实际两层发布/检查和覆盖为准。下载/写盘/取消沿现有失败及清理机制。新run均重新下载；历史失败仍依已有临时/永久规则处理，真实历史状态及成功事实继续保存，不能连同旧日补采状态一起删除。

### 21.7 性能模型、验收和开工条件

探测数据量设N为目标日源端返回行数，页容量为现有10,000。按短页/空页终止规则，完整成功查询的请求量为`floor(N/10000)+1`，N为正整页倍数时包含最后空页。5,573行样本因此为1页/1请求；只是会话实测，不是所有日期或网络的耗时保证。正常未重启的10个半小时时点最多10次探测求值，各自页数按实际N计算；清cursor后重探测另计。正式261字段下载、内存、候选和历史成本沿§10/§18模型，不把两列查询耗时当成完整任务成本。

sensor以既有5秒性能目标核对本地读取、T/P摘要和源查询的总耗时；它不是运行超时，也不因一次超过5秒而拒绝已齐备源。HTTP超时来源与总探测时限见§21.14：沿现有ConfigurationSnapshot的45秒请求时限覆盖一次完整探测，各页共用余时、不在同tick重试。现有SDK调用不能交接这一余时，故本数据集直接复用现有HTTP传输。投影解析、余时配置和资源关闭先按§21.13做最小隔离验证；不修改通用下载器完整字段规则。

失败或进程退出后，下一合法时点重新取得两列源端数据；无需保存探测代码文件。job重跑完整重下T和原失败历史范围，成本按原模型全计。最终隔离验收读回本次目标两份正式临时文件、物化/check绑定和必要小记录一次，历史按已有批次审计事实及必要有界样本读回，不因收尾扫全部历史。

| 必须证明的规则 | 正反例与验收 |
| --- | --- |
| 源端集合 | 必需A/B、可选首日N时，实际A/B或A/B/N均通过；实际A、A/B/C、重复主键和错日均不通过。除可选首日外的额外代码不得过滤。 |
| 应有集合 | 新股首日缺行可通过、已有行保留；下一交易日起必须有该代码，上市前不纳入；基础信息或生命周期未更新到T、生命周期早于最新输入均等待；退市有效期、全天与盘中停牌、历史身份映射按T；依据未知不提交。用前述6只真实首日样本核合同，NULL指标允许。 |
| 两列分页与总时限 | 普通短页1请求，满页后继续、末页完整，不能截断后判相等；响应只两列，异常不等同空源，deadline耗尽不提交。复用已有小页实测并补工程传输的最小有界验证。 |
| 发布前完整性 | sensor探测相等而261字段源随后缺/多/空，Raw首次提升为0；源相等但旧Raw合并候选多码也不提升。相等及合法NULL可按正常Raw→Silver发布。 |
| 人工指定日期 | 无原run也能在11月11日补11月10日；按T/P及T生命周期处理，D休市可执行；T错分区、未来日或非交易日拒绝。普通人工不读初始化目录。 |
| 自动时间和去重 | 18:59、19:00、23:30、00:00及休市；源不齐后续slot可再探测；源请求或名单规划跨午夜、缺pretrade_date所指P行均不启动正式下载；同slot已有run/清cursor不重复job，旧日缺口不阻挡当天；排队跨午夜零正式下载。 |
| 原复权历史 | T/P修订、原同T待刷、旧历史源等待、后续整范围新下载、手动repair授权和d<T边界继续通过；不因去掉日缺股补采而删除历史恢复事实。 |
| 中断与读回 | Raw已发Silver失败、发布后事件失败、取消及进程退出保留已提交文件，新run全新下载，验证当前两层及真实绑定；不使用失败候选。 |

实际推进按本章§21.13分步，每步定向回归通过再继续。Definitions及静态治理使用既有受保护runner，两sensor默认STOPPED。共用两列探测和日更发布门槛的隔离验证分别见§21.18、§21.19；完整日更sensor与串联尚待实施，不能据此宣称正式自动化验收完成。

### 21.8 整体审计结论及工程验证缺口

| 审计点 | 处理 |
| --- | --- |
| 旧自动补采、发布后才查日覆盖与新门槛冲突 | 已删除旧规则，新流程集中在本章及方案§17。旧批次仅保留代码事实和证据，不能继续作为执行指令。 |
| 指定日期无原run时旧解析会拒绝 | 新manual_date明确允许首次提交，执行日与目标日分开，生命周期和股票复权因子都按T。 |
| 两列齐备后正式源变化 | DAY_SOURCE及最终Raw候选在首次提升前分别检查，同一应有关系复用。 |
| 旧Raw多余代码被保留 | 最终候选多码则停止并报告，自动清理旧业务行不在本次权限中。 |
| 源端与本地同时遗漏首日新股 | 检查目标T股票基础信息、生命周期的就绪/新鲜度及先后绑定，不以陈旧生命周期构造应有集合。 |
| 分页截断、探测或名单规划跨午夜 | 源取完终页才比较，源查询返回后复核D/slot，正式下载开始事实前复核自动午夜截止。 |
| 删除日补采时误删复权历史恢复 | 日/历史阶段的真实结果、原授权、待刷范围和整范围失败重下保留；只删除自动补前日次数和部分日成功路径。 |
| 初始化导入与日更范围混淆 | Prod忠实导入和既有缺口统计独立；bootstrap_supplement的日发布经过同一新门槛，普通manual_date不维护导入operation。 |

工程验证缺口及处理已具体落在§21.13～21.14。原readiness.py逐项读取6份物化、16项check，最多22次API调用，check历史每项limit=5000，理论可返回80,000条旧check；不能直接放进新sensor。目标改为6次最新物化和按无分区/T/P三组读取对应最新check，共9次API调用、最多22条相关结果，所有检查仍绑定对应物化。该数量来自现有spec及本机已安装Dagster存储接口，不是实测耗时。

先按§21.13验证固定投影传输和有界事件读取，再写正式sensor编排；不调整全工程CHECK_HISTORY_LIMIT或扩大扫描。五秒仍只作性能验收目标，正常/异常、冷启动/同slot跳过、重开实例和最后读回分别计时。未取得这些新接口的隔离证据前，不声称新sensor已经实现或通过。

2026-11-11文档修订已通过仓库文档完整性检查及git diff空白检查，并专项核对两份文件的代码围栏、现行章节、旧执行规则清理及本次相对链接。检查结果证明本轮文档结构和规则对账；新接口投影及sensor工程性能按上述条件继续验证。

### 21.9 目标2026-11-10的只读源端覆盖检测

2026-11-11北京时间13:00，通过Tushare MCP请求stk_factor_pro，参数trade_date=20261110、fields=[ts_code,trade_date]，未传股票或limit。返回5,572行、5,572唯一代码，两列和日期全部符合，远端调用完整往返482毫秒。

读取正式DG的SSE目标日记录及生命周期、身份映射、目标日最终停牌文件，投影必要列，在临时内存DuckDB调用现有build_stk_factor_pro_coverage_keys。生命周期目标日上市5,580只，确认全天停牌7只，应有5,573只，源实际5,572只，匹配5,572只，缺1、多0。身份无缺失或歧义，读取前后文件身份未变。全天停牌代码为000831.SZ、002129.SZ、002717.SZ、688053.SH、688121.SH、688496.SH、688798.SH。

唯一缺码688827.SH为目标日上市新股，DG名称N钶锐，源股票列表当前名称C钶锐。追加该股目标日两列技术因子查询仍0行；股票列表list_date=20261110，目标日日线返回1行。该反例说明首日正样本不构成普遍保证，该次按首日必需旧口径判断为不通过。管理员随后确认首日可选，按同一批结果复算必需5,572、实际参与比较5,572、必需缺0、未知多0，数据门槛通过。原单股查询及原比较作为有日期证据保留。

本地必要投影读取271.865毫秒、现有集合函数36.606毫秒，本地完整审计319.737毫秒，模块首次导入另649.743毫秒。源请求与本地完整审计两段实测相加801.737毫秒；分段执行及工具编排时间不作为整tick实测。此次只读核验覆盖源数据和物理代码集合，未执行正式sensor/job、未写cursor或事件，也未执行Dagster任务/上游事件就绪查询。因此本次不替代§21.8的完整sensor性能验证，22次/80,000条上界仍须在工程验证中检查。

### 21.10 上市首日代码可选（2026-11-11）

管理员根据688827.SH的首日缺行反例确认，上市首日记录存在不再是齐备的必要条件。定义必须按目标交易日T判断，人工补旧日仍用旧T，首日之后的交易日重新纳入必需集合。首日指标可空与首日整行可缺分别遵循字段合同和本节代码规则。

设L为目标日有效上市股票扣除确认全天停牌后的统一身份集合。F为L中list_date=T的首日代码，E=L EXCEPT F为必需代码，A为源或Raw的全部实际统一身份代码。C=A EXCEPT F是参与覆盖比较的实际集合。缺失=E EXCEPT C，额外=C EXCEPT E，两者都为空才通过。首日代码返回时保留全部原字段和业务行，不在Raw/Silver中过滤F；已确认全天停牌或其他不属于L的源代码仍按未知多码处理。

源端探测、正式261字段日源、最终Raw候选、日覆盖及历史资格共用这套代码规则。bootstrap的当前覆盖/缺口统计同样调整必需集合，原Prod完整导出和源到Raw到Silver的实际全字段传输对账仍按真实行数核实。历史复权比较、历史范围、原授权及d<T更新算法继续按已有规定执行，新股无上市前历史仍按已有历史起点规则处理。

计数使用现有CoverageCounts字段，expected_count=|E|，actual_count=|C|，matched_count=|E与C交集|，missing_count和extra_count为上述差集数量。因此原有expected=matched+missing、actual=matched+extra仍成立。源返回总量、Raw/Silver行数及raw_physical_code_count继续记录包含可选首日行的真实数量，界面说明actual_count为参与比较代码数，不能再拿它等同整份Raw物理代码数。可选首日集合由本次已准备生命周期计算并复用，不形成新的业务状态或下载缓存。

2026-11-11第1小步已完成共享首日可选算法和覆盖记录，证据见§21.16；日更配置、源端探测、完整日发布前移和日更sensor仍按后续小步推进。build_stk_factor_pro_coverage_keys、calculate_stk_factor_pro_coverage、bootstrap纯覆盖/包装及RawCoverage资格消费者已同步，避免后续历史资格继续按旧规则报缺。纯集合函数新增必传optional_relation，输入为目标日首日代码的DATE/VARCHAR关系；与上市、停牌及实际三侧一起统一身份，无首日传同schema空关系。当前连接准备的E/F和已核身份映射显式交接、同日复用并随日期释放。输入摘要纳入覆盖规则版本；原来源计数、导入事实、历史授权和完整成功事实保留，不增加运行时双轨判断。

覆盖结果复用须同时核本覆盖规则，具体字段及消费者见§21.12。不能只因Raw及生命周期/停牌/身份文件SHA未变而复用首日必需或只检查缺码的旧计数。该判断限定在覆盖统计，不改股票复权因子历史计划及整范围成功记录的业务摘要，避免规则变化无故触发历史整范围重下。

验收使用独立字面样本，必需A/B且首日N时，源A/B和A/B/N均通过并保留实际已有行；少A或多未知C拒绝。把目标日推进到N上市后的交易日，缺N拒绝。源、Raw候选、历史资格、bootstrap当前覆盖以及两个计数等式须分别验证，防止只改sensor。11月10日同批数据的5572必需/5572实际比较通过是已记录事实的规则复算，尚不代表新实现或完整sensor已验收。

本轮已在临时内存DuckDB执行本章引用的文档集合SQL，核对首日缺失、首日存在、必需缺失、未知多码、全天停牌多码及下一交易日缺该股6个独立金样本，结果及两个计数等式均符合上述规则。该验证覆盖集合SQL语义，源端字段/接口和新sensor工程集成继续按§21.7验收。文档完整性及git diff空白检查通过。

### 21.11 多个上市日期的下一交易日记录核验（2026-11-11）

本轮有界查询new_share的20260815～20261031发行区间，返回34条候选，从中选择2026-09-07～2026-11-06的12只股票，覆盖12个上市日期、沪深北三家交易所各4只，以及主板、创业板、科创板、北交所。逐只用stock_basic.list_date核实际上市日，12只均与new_share.issue_date一致。下一交易日由正式SSE日历的开市记录及其pretrade_date反向确认，避免用自然日加一天或在日历缺行时取错日期。

每股只请求stk_factor_pro的ts_code/trade_date，范围固定上市日至下一交易日，最多两个交易日。12次单股请求共返回24行，代码、日期和唯一键均符合，每只下一交易日均1行，次日缺记录反例为0。首日历史记录本次也均1行。

| 股票 | 上市日 | 下一交易日 | 首日行数 | 下一交易日行数 |
| --- | --- | --- | --- | --- |
| 天博智能 603448.SH | 2026-09-07 | 2026-09-08 | 1 | 1 |
| 燧原科技 688801.SH | 2026-09-11 | 2026-09-14 | 1 | 1 |
| 信诺维 688837.SH | 2026-09-16 | 2026-09-17 | 1 | 1 |
| 沈鼓集团 601091.SH | 2026-09-17 | 2026-09-18 | 1 | 1 |
| 力勤资源 001246.SZ | 2026-09-30 | 2026-10-08 | 1 | 1 |
| 联亚药业 301569.SZ | 2026-10-15 | 2026-10-16 | 1 | 1 |
| 文峰光电 920296.BJ | 2026-10-21 | 2026-10-22 | 1 | 1 |
| 通则康威 301718.SZ | 2026-10-22 | 2026-10-23 | 1 | 1 |
| 远大健科 920285.BJ | 2026-10-23 | 2026-10-26 | 1 | 1 |
| 天元重工 920306.BJ | 2026-10-29 | 2026-10-30 | 1 | 1 |
| 皇冠新材 001381.SZ | 2026-11-03 | 2026-11-04 | 1 | 1 |
| 森峰激光 920085.BJ | 2026-11-06 | 2026-11-09 | 1 | 1 |

另按sensor将使用的全市场单日两列方式查2026-09-17、2026-10-08、2026-11-04、2026-11-09，分别返回5,553、5,557、5,572、5,573个唯一代码，均无错日或重复。对应样本688837.SH、001246.SZ、001381.SZ、920085.BJ均在返回中，单股可查与按日可查在这4例一致。9月30日上市后下一交易日为10月8日，11月6日上市后下一交易日为11月9日，均已按日历核对。

本轮共29次MCP调用，包含1次候选查询、12次上市日核实、12次单股首日/次日查询、4次全市场按日核验；不把MCP调用数称为底层HTTP请求数。单股两日查询往返100～620毫秒，4次全市场两列查询往返235～550毫秒。这些均为本次分段实测。

证据支持这12个历史样本下一交易日已有技术因子记录。历史回看不能证明各自上市次日晚间首次出数时刻，也不能作为所有新股第二交易日必定即时可得的保证。688827.SH的下一交易日是2026-11-11，本轮查询时尚未到既定19:00日更窗口，留待当晚源端出数后核验，不将当前时点未到窗口当作次日缺失反例。源端代码门槛仍按实际返回决定是否提交。

### 21.12 旧代码逐项清退及记录衔接

以下以2026-11-11第1小步实施前的工作区代码为基线，是需求变更的完整改造清单。第1小步完成的共享覆盖及记录部分见§21.16，其余部分仍待后续小步。不得只新增sensor而留下旧日发布分支，或把旧字段填None后声称已经清退。此前文档保留这些空字段的建议撤回；源契约261字段和股票复权因子历史算法不因此改变。

| 当前落点和实际行为 | 本次删除或替换 | 继续保留的功能及直接消费者 |
| --- | --- | --- |
| `run_contracts/stk_factor_pro.py`的UpdatePurpose/Purpose、`_update_fields`、UPDATE_CONFIG_SCHEMA、RunInput、parse及RunIdentity含previous_day、submission_no、business_attempt | 删除用途和两字段；today只允许T=D且slot为0～9；manual_date允许无parent、T<D、D休市；bootstrap用途按原授权。七字段不再接受旧提交序号。 | source_run_id、T/P、真实开始时间、parent/root和三项bootstrap授权仍按各自职责保留。 |
| 同模块`_STK_FACTOR_OBSERVATION_TYPES`及metadata builder/parser仍输出两项次数；readiness的`_stk_factor_pro_observation`、`_stk_factor_pro_update_input`、`resolve_stk_factor_pro_source_run`核旧八字段 | 同步删除观察两字段和比较分支，统一七字段重执行核验及manual_date用途；更新错误说明和配置样例。 | start/precheck/day/history、日/历史结果直接引用、较新repair失败优先、原授权摘要核验继续使用，不扫描旧tick恢复机会。 |
| `assets/stk_factor_pro.py::_published_day`先发布后准备覆盖；主入口按usable给部分日写completed，再等待历史资格 | 覆盖依据在下载前准备；DAY_SOURCE检查在候选前、RAW_EXPECTED检查在Raw提升前；删除部分日completed及缺股后续补采分支。完成日以完整两层及本规则覆盖为准。 | 逐文件发布和故障事实、正常预检等待、真实文件/事件失败、取消及下一run全新下载保留。 |
| `io/stk_factor_pro_publication.py::publish_stk_factor_pro_day`构造Raw候选后直接提升 | 增加必传on_raw_candidate回调，在Raw候选audit后、任何Raw替换/等价发布事件前调用；asset闭包检查最终候选并保留calculated，publisher仍yield原(target,audit)，不反向import readiness。 | 现有B−K+U合并、完整候选audit、等价不替换、Raw→Silver及on_publish_attempt保留；历史publisher不套全市场完整日门槛。 |
| `asset_guards/stk_factor_pro_readiness.py`两层纯覆盖函数没有首日关系，RawCoverage仅看missing=0；`ops/stk_factor_pro_history_repair.py`也构造RawCoverage | 增加必传optional_relation，统一E/F/C；RawCoverage增加extra_count及coverage_rule_version；两种evaluator及repair构造处改为缺0且多0。 | 名单、差集诊断和有效文件/check身份继续复用。repair仍先确认原T Raw及Silver，零T日下载/发布；不把完整日准入误加到每股历史源。 |
| `bootstrap/stk_factor_pro_bootstrap_coverage.py`共用calculate，但DateCoverage.coverage_complete只看missing；history入口及覆盖摘要函数用旧input_digest | 同步首日集合、actual_count及缺0/多0；DateCoverage保存规则版本，月/日覆盖输入摘要纳入规则版本，更新summary贡献及其复用判断。 | Prod原source_rows、SourceComplete、approval、import_complete、实际Raw/Silver行数及原导入完整性含义不变；有缺口仍可忠实导入并记录，不能报覆盖齐备。 |
| `read_stk_factor_pro_day_factor_shas`为了证明日发布有效，读取技术因子Raw/Silver全文SHA | 保留job既有验证入口；抽出只接受已核日结果、读取该日观察所指计划的小函数，供sensor使用，见§21.13。 | 同T最近有效日观察所指计划仍是旧T/P摘要来源；repair历史计划不能替换它。 |
| 原补前日选择、机会及tick恢复设计没有已装载的日更sensor | 新sensor直接按T=D实现；不新写旧选择器、前日阻挡、提交序号、attempt计数或已关闭tick恢复。 | 分区注册仍按SSE的D/pretrade_date新增缺失键，STOPPED/600秒不变。 |

**共享合同的完整修改范围。**生产代码包括`defs/run_contracts/stk_factor_pro.py`、`defs/asset_guards/stk_factor_pro_readiness.py`、`defs/assets/stk_factor_pro.py`、`defs/io/stk_factor_pro_publication.py`、`defs/io/stk_factor_pro_history.py`、`defs/ops/stk_factor_pro_history_repair.py`、`defs/bootstrap/stk_factor_pro_history.py`及`defs/bootstrap/stk_factor_pro_bootstrap_coverage.py`；新增两列探测及日更sensor。jobs/checks/Catalog只改确有旧输入或说明的消费者，不改名称、分区或261字段schema。改前以CodeGraph和当前rg引用再次核实清单，不扩至Prod、Web、其他数据集或通用下载器改造。

**上线前记录格式。**当前尚未完成本数据集正式bootstrap；§20.7仅证明11月8日核验时无目标文件/日更任务，不能当作11月11日正式记录仍为空的证明。实施共享记录修改前，先只读计数本数据集正式两job运行、Raw资产阶段观察和现有bootstrap operation/本数据集run记录目录。计数与必要单条身份即可，不读全库或全历史业务明细。正式本数据集记录为0时，直接收敛为本文新结构，全部当前生产者、读取器、独立测试样本同次迁移；临时测试旧JSON不作为上线兼容理由。若发现正式旧记录，先报告其种类、数量和被引用关系，补写并确认迁移方案后再改封闭parser；本章不授权删除记录、改SHA引用、清空DG状态或增加运行时双轨。§5.4的源contract/processing版本和历史业务摘要含义保持原值。

**覆盖版本。**在run_contracts单处定义`STK_FACTOR_PRO_COVERAGE_RULE_VERSION = "1"`，表示首次显式登记的“上市首日可选、其余缺0且多0”规则；它不是源接口或历史处理版本。新RawCoverage、BootstrapDateCoverage及其metadata固定保存该值。复用须同时匹配规则版本、Raw和三份覆盖依据SHA；bootstrap月/日input_digest的现有固定投影增加这个内部常量，调用方不另传可随意填写的版本。date-result字节摘要改变后，summary沿已有日期贡献替换更新；summary不重读业务文件。原历史plan/history_input/scope/ranges业务摘要投影不加覆盖版本，不无故重刷已成功范围。旧统计不能补填版本后直接冒充新计数。

**测试清退。**更新`test_stk_factor_pro_foundations.py`、`test_stk_factor_pro_contracts.py`、`test_stk_factor_pro_jobs.py`、`test_stk_factor_pro_recorded_results.py`及`test_stk_factor_pro_batch5_job_integration.py`中的旧配置/身份/部分日成功预期；删除前日一次机会的正向需求，保留为拒绝旧字段或不再选前日的反向测试。`test_stk_factor_pro_readiness.py`及bootstrap覆盖、覆盖输入、supplement测试同步新首日关系、计数、规则摘要和实际行数；历史contract/repair/space/publication测试中所有RunIdentity及RawCoverage构造同步迁移，保留原范围、故障、资源释放和历史公式金样本。不能为新日门槛删掉历史源部分日期失败、Raw成功Silver失败或硬退出的回归。

### 21.13 新代码接口、调用次序与分步实施

这是原第六批第3步内部的实施顺序，原第1步自动追修和第2步分区注册不重新编号。每小步先核当前代码与本章，再完成直接消费者和定向正反例；上一小步通过后再进入下一小步。正式开发另按管理员授权，本轮只写设计。

**1. 统一集合与记录。**先按§21.12核已有正式记录数量。修改§5.2.1公共及私有覆盖签名、calculate、bootstrap包装和所有直接调用。prepare继续交接已读生命周期/身份/停牌；在同一连接用`list_date=T`投影首日关系，纯算法内部与有效上市扣停牌集合相交。源、候选、repair、bootstrap分别按同一算法使用其实际侧；每个不同实际侧只计算一次，不能为了“复用”把源校验结果直接当作候选结果。无首日传空关系，无新可选参数、隐式文件读取或重复DESCRIBE。更新RawCoverage/DateCoverage、版本与摘要、复用和summary贡献。独立验证首日缺/有均通过且有行保留、次日缺拒绝、缺/多各一、全天停牌代码出现在源端仍拒绝，以及同文件SHA不同覆盖版本不能复用。

应有E/F只在本任务当前T首次准备和统一身份时生成，作为coverage_inputs中的同连接内部关系复用。公共build函数仍负责外部五关系的首次合同核验；私有算法将“准备E/F”和“映射当前实际侧、比较E/F”分开。内部`compare_stk_factor_pro_coverage_keys(connection, *, target_trade_date, expected_relation, optional_relation, actual_relation, identity_relation, basis_mapping_relation)`显式接收已准备的上市/停牌/首日代码身份映射；已有映射不重复计算，仅为实际侧新增代码核映射，再按四侧参与代码的并集统计映射异常及C/missing/extra。不重新读取或重算生命周期/停牌。已有calculate、源探测和候选闭包按各自首次实际关系调用它，原公共build也委托同一比较实现；bootstrap每个日期只准备一次。准备结果与当前连接/日期一起释放，不增加跳过校验开关、跨任务缓存或另一套集合算法。源/候选首次运行都没有旧覆盖复用必要；calculated=None仅用于版本/输入均匹配的已保存结果包装。

**2. 七字段与指定日期入口。**同步§21.12的解析、身份、观察、parent/root、bootstrap授权和测试消费者，删除旧两字段。today新自动提交仍T=D；manual_date首次可以无parent，本小步先验证配置和身份合同，完整人工日更新在第4小步验收；按历史T取完整SSE记录和其pretrade_date所指P，不按有缺行的开市tuple下标选P。普通人工不读bootstrap目录；原生日更重执行保持原T及原用途，按原授权重新下载。11月11日补11月10日、休市D补旧开市T和无原run必须通过；旧字段/previous_day、未来T、错分区、缺严格P必须拒绝或预检等待。维护/队列按§4.2，不在job内自动启停sensor。

本小步实施时，`_open_calendar`从本连接已核日历关系一次投影SSE开市日的`trade_date/pretrade_date`，按日期交接映射；parse和历史repair用目标T记录的P确认开市、存在及P<T。历史规划和bootstrap授权仍接收同一映射的升序开市日期tuple，不新增日历文件读取。manual_date首次提交核D为本次上海自然日期，不套自动时点；原生重执行沿原parent/root核七字段，不以实际开始日期替换原D/T。

改动限本数据集run_contracts、assets、readiness、bootstrap授权、repair及直接测试，不改源请求、日发布门槛、历史算法、定义名称或正式路径。七字段默认值与持久位置沿§21.4；闭合观察和嵌入RunIdentity的记录同步收敛，不保留旧字段兼容。故障、取消和跨进程重下沿现行机制，本步不新增业务写入阶段。配置/身份检查源请求和额外文件写入均为0；原生重执行最多读取直接parent/root各一次，重复身份复用；日历沿既有一次准备及必要投影，内存随日历开市日期数线性增长。中断后重新解析同份输入，最后隔离读回该run的七字段与观察，不扫描历史业务文件；耗时以本步有界验证实测记录，不另设无依据阈值。

测试按独立字面配置验证11月11日补11月10日、休市D和无parent，反向拒绝旧用途/两字段、T≥D、错分区及缺失/休市/不早于T的P；周一缺周五但有周四不得误选周四。原生重执行跨日保留原输入、改用途或日期拒绝；普通人工对bootstrap目录读取为0；既有bootstrap首次授权及重执行、repair原范围和历史回刷回归继续通过。正式旧记录计数沿§21.12，前次16:24核验为0，开工只复用同会话该证据，不据此授权正式执行。

**3. 同一源端探测函数。**在`defs/source_readiness/stk_factor_pro.py`新增`probe_stk_factor_pro_source`，输入为目标T、已准备的覆盖输入/本连接、既有连接配置和时钟，返回§21.2小结果。只请求固定API、固定两列、固定目标日及源分页参数。使用既有完整STK_FACTOR_PRO_CONTRACT和transport binding，以PageRequest固定fields构造只读请求，复用HttpProTransport及parse_http；不能经会强制填完整字段的RequestBuilder生成投影请求，也不能把两列响应交给完整unit输出器。用既有内存/计数/取消接口，仅调用单次fetch_page，不走下载session的同页重试或文件输出。传输返回的字段形状、日期、原主键及页完整性由本函数核验，分页取得的实际集合直接交纯覆盖函数，全部额外代码保留参与比较。

沿§21.14余时和现有资源关闭合同。不能直接复制`idx_factor_pro_source_probe.py`：该函数会丢弃非预期代码且只查一页，不满足本需求；不改这个指数消费者。先用安装环境的真实parse_http、PageRequest和可控HTTP响应做投影、空页/短页/满页、重复跨页、错日、额外字段、源错误、超时及关闭验证，再复用已获准的有界源样本核两列合同。正式源请求仍按只读授权与权限执行，不使用正式sensor evaluation做实验。

第3小步具体输入为同T的connection/coverage_inputs/target_trade_date、既有ConfigurationSnapshot、Clock和DownloadControl；调用方交接同连接已准备的依据，本函数不加载配置或正式文件。结果StkFactorProSourceProbeResult保存目标日、ready、reason、source_row_count/source_code_count、既有StkFactorProCoverageCounts小记录、optional_count/optional_present_count/optional_sample_codes、request_count、page_count、elapsed_ms及既有DownloadErrorCode。计数摘要不返回完整代码；源分页未完成时source_code_count和coverage_counts为None，身份未知时仍保留完整源代码数，coverage_counts中应有/实际/差集值为None并保留身份诊断。可选首日样本沿现有代码样本合同至多20项。

每页只调用一次HttpProTransport.fetch_page，复用完整契约及其binding；只接受两列，按列名对应值、允许两列顺序变化，代码必须为非空字符串，日期必须为目标日YYYYMMDD。按页将两列数组批量插入本连接临时表，以原主键拒绝页内及跨页重复，不用逐行入库。短页/空页后仅调用一次calculate_stk_factor_pro_coverage，直接交接当前关系；该函数不读取业务文件、不写诊断附件，并复用已有E/F和身份映射。未知依据或未确认开市时零HTTP；源失败或超时返回ready=False及明确失败，不能以已得部分页计算齐备。取消沿既有DownloadCancelled向上退出；本地SQL错误向上报告。

关闭复用已有resource_cleanup，仅调用传入的transport.close、UnitMemory.clear、SessionControl.clear和本函数临时表释放；该helper导入及使用不读取bootstrap目录。源异常或取消也尝试全部清理并保留原异常，清理失败不能返回ready。coverage_inputs的E/F及覆盖关系由调用方沿现有日期/连接生命周期释放，不删除调用方准备结果。累计行数只计实际已解析行，完整代码数及覆盖计数在完整分页后才确定；页数计已接受页，含合法空终页。耗时包括关闭，结束时再核总deadline；不修改通用下载器、指数探测或既有日更入口。

本步新增一个生产文件及直接测试，§21.14预算不变：单目标日、两列、零业务文件/正式事件/正式数据库写入，Python常驻单页，完整两列关系位于受控DuckDB连接，复用既有2GiB统计及连接自身限制。中断后不保存页进度，下次从offset=0重探测；最后验收只读临时关系及小结果，清理后不得遗留本函数临时表或HTTP句柄。测试使用固定10,000页容量核满页/终页，覆盖错误、首日缺/有、次日必需、停牌、多码、无效身份、近deadline与清理；有界来源复用已保存的一股五日样本，投影目标日两列通过真实localhost HTTP/parse_http，不新增正式源请求。

**4. 将完整日门槛移到发布前。**assets入口取得本run唯一known_pg/known_records及同一主要连接，先准备T的覆盖依据和E/F，再按原算法保存完整历史计划。manual_date及bootstrap_supplement在保存名单、正式下载开始观察和261字段下载前，调用第3小步的同一两列探测；不齐只写真实precheck观察，不产生正式下载/物化/历史资格。today消费sensor已通过的准入，不重复两列请求。下载完整日unit、关闭session并核summary后，投影DAY_SOURCE的两列计算一次；不齐按日阶段失败出口报告真实差集。publisher新增必传on_raw_candidate(*, raw_relation, raw_audit)回调，由asset提供同连接闭包；Raw候选audit完成后、_publish_file之前恰调用一次，闭包对RAW_EXPECTED作本次候选比较，失败即抛原日阶段错误，通过才提升Raw，随后Silver沿原逻辑生成。闭包保留candidate_calculated供evaluate及初始化统计消费，publisher继续yield原(target,audit)，不新增返回包装类或IO→readiness反向依赖。evaluate仅绑定真实物化/check，不再重算或读取正式Raw。历史publisher和bootstrap忠实导入路径不调用这个全市场日发布回调。

自动正式下载开始前复核原D和午夜截止；已经实际开始的完整日任务允许结束。完整日源在探测之后变化造成缺码/多码，属于本轮日失败，可在下一合法slot重新探测并全新下载，不保留缺股补采进度。旧Raw合并候选有多码则停止并报告，不自动删行。正反例覆盖零提升、合法NULL/首日有行完整保存、旧Raw不能填补本轮源缺码、Raw已发Silver失败、事件保存失败和新run完整重下。源检查和候选检查各一次是两个不同输入的必要计算，不是重复审计。

第4小步的人工入口须与第3小步已验证的源探测联通后验收；替身测试与真实合同验证分别说明，不能以替身验收声称接入已通过。

第4小步实施范围是assets/stk_factor_pro.py、asset_guards/stk_factor_pro_readiness.py、io/stk_factor_pro_publication.py、bootstrap/stk_factor_pro_bootstrap_coverage.py及直接测试。job先核目标日股票基础信息及生命周期最新物化和已绑定检查，两份无分区物化各取1条、5项检查按既有spec一次读取，结果留在known_pg；按T核新鲜度，生命周期不得早于股票基础信息。只落实本步job必需的两项基础输入，不提前实现第5小步的全部上游批量入口或sensor摘要读取。

覆盖模块从现有calculate中抽出prepare_stk_factor_pro_expected_coverage_keys，仅准备同一连接/日期的E/F及身份映射；calculate继续委托它，不复制上市/停牌谓词。job在保存历史计划前调用一次；人工两列预检、当前DAY_SOURCE及最终RAW_EXPECTED分别用各自实际数据调用原calculate，不能互相替代。publisher的必传回调位于Raw候选唯一audit后、_publish_file前，包括等价发布；保持原yield和on_publish_attempt含义，迁移所有真实调用及隔离测试。source不齐按可再次取源的day失败，候选不齐沿现有候选错误停止并报告，不新增删除旧行或兼容分支。

_published_day显式接收已准备的coverage_inputs，candidate_calculated由回调交后续evaluate和初始化统计。_prepare_initialization_result增加显式calculated输入：目标日使用候选已有结果，历史日期收尾仍以None沿原日期复用/计算；仅复用本步新算结果，不用旧统计代替当前源或候选检查。bootstrap忠实导入及独立历史repair不套全市场日准入。零差集沿现有规则不写空附件；失败在metadata报告差集数量及至多20个样本，不保存日源副本。只有Raw/Silver和绑定检查、覆盖均有效才写day completed，删除部分日completed及其history waiting分支；真实逐文件失败和历史失败事实保留。

manual_date/bootstrap_supplement在计划和正式开始记录前调用第3小步探测，ConfigurationLoader沿既有来源取得只读配置，不新增env或参数。today新自动任务仍不重复两列查询；原生today重执行保留原用途，不套本次自动时点限制。午夜复核只作用于没有source_run_id的新自动today，在计划完成、开始观察之前再次检查原D/时点；跨午夜等待且零正式下载，已经开始的任务沿原合同完成。人工补日和其原生重执行不套自动窗口。

读写及性能沿§21.14：人工额外两列完整探测一次，自动零次；E/F首次准备一次，完整日源/候选各计算一次，publisher候选audit、Raw/Silver写入/物化/check次数不增加。新增两份基础物化及5项检查至多7条结果、3次API，按现有事实复用；这是本步job增量，不冒充第5小步完整上游预算。输入、候选、失败诊断及最终验收使用已有连接/临时关系，未知或缺/多在首次提升前停止。Raw已提交而Silver失败时保留已提交Raw和真实事件，下次重下完整T；中断/最终验收仍按原日下载和逐文件预算，不扫描正式全历史或重算相同覆盖。

验收使用临时实例/目录、保存的一股五日261字段样本和可控本机HTTP，真实串联人工两列探测及完整字段下载/发布；其他单元测试可替代源与上游，但分别说明边界。正反例包括未齐零计划/下载/提升、源少/多及旧Raw不能补本轮缺、最终候选旧多码零提升、首日缺/有及NULL保留、等价发布仍过回调、Raw成功Silver失败、事件保存失败、跨午夜和跨日重执行、bootstrap原导入事实与当前统计分离、E/F及各实际侧计算次数，以及进程退出后完整重下。开发后再按原方案逐条独立对账，不进入第5小步或正式执行。

**5. 有界上游读取和日摘要。**在本数据集readiness模块增加`read_stk_factor_pro_upstream_status`，固定接受T/P及任务局部known_pg；复用readiness.py已核spec、检查判定及_asset_readiness_status_from_check_results的纯状态构造，保持原日期新鲜度语义，不调整全工程helper。股票基础信息、生命周期各取最新1条无分区物化；Raw股票复权因子T/P、Raw和Silver最终停牌T各取对应分区最新1条。check按无分区、T、P三组调用已存在的`get_latest_asset_check_execution_by_key`，T/P使用PartitionKeyFilter精确过滤，当前spec的检查名按资产唯一。核status=SUCCEEDED、blocking/passed、资产/分区及target_materialization_data真实绑定；最新check缺失、等待、失败或绑定旧物化均等待，不深扫历史找旧绿灯。日期新鲜度沿原helper的T规则，生命周期物化不得早于本轮最新Raw股票基础信息物化。当前producer没有保存源文件SHA绑定，本设计不把时间先后声称为SHA证明，不为此修改共享上游资产或新设状态。

从`read_stk_factor_pro_day_factor_shas`抽出`read_stk_factor_pro_day_plan_factor_shas`：必传已核的同T有效日观察和已有两层发布/检查结果，读取该观察自身明确引用的plan一次，只返回T/P摘要。job原入口完成原有物理验证后调用它；sensor通过最新日阶段覆盖、对应物化/check及其文件摘要metadata核有效日结果后调用它，不能调原helper重新计算技术因子Raw/Silver全文SHA。sensor按既有唯一writer和d<T写入合同读取已保存事实；真正job仍核本轮实际文件。repair的历史观察可解除它授权的失败，不能替代日观察。测试须抓住旧helper全文读取，断言sensor对两层261字段及全历史读取为0；job原真实性核验及第1步追修回归保留。

第5小步实现限asset_guards/stk_factor_pro_readiness.py、assets/stk_factor_pro.py、repair对原上游检查函数的直接引用迁移及直接测试；不改通用sensors/readiness.py、上游producer、源请求或日发布/历史算法。repair从daily.raw_tushare_adj_factor_ready_for_trade_date改为直接引用通用readiness同一函数，原T/P参数、检查语义、读取量及业务算法不变；不在日更模块保留无消费者用途的旧导出。新增read_stk_factor_pro_upstream_status(instance, *, target_trade_date, previous_trade_date, known_pg)，返回既有DatasetReadinessStatus。三个分区组的物化/check及最终结果保存在本任务known_pg；T停牌结果同时交接既有("suspend_readiness", T)，供_basis_for_day复用。删除asset的_reference_inputs_ready及T/P逐项旧检查调用，不用旧别名维持双轨；其他历史日期的停牌检查保持原入口。全局两项按T核新鲜度，分区资产沿原helper只核准确T/P分区，不另加物化自然日限制。正常完整输入最多6次limit=1物化API及3次最新check批读，取得6+16条记录，同份known_pg重复调用新增读取为0；不深扫旧check，不调用get_asset_check_execution_history。

read_stk_factor_pro_day_plan_factor_shas(*, day_observation, publication_checks, previous_trade_date, staging_root, contract, known_records)接收调用方已核的同T有效日观察和两层check映射，不重做已完成的覆盖/check计算。它只核计划引用属于该日发布的producer及两层check绑定run，沿现有referenced_history_plan读取同T、同合同记录，核P后返回T/P摘要。旧job入口保留原日观察、两层绑定及物理SHA检查后调用它；repair不能以自身观察/计划替代原日计划。相同计划沿known_records复用；缺坏引用/错T/P按原ValueError出口，不增加兼容回退或异常吞掉。新函数不请求源、不读技术因子Raw/Silver、不读全历史、不写文件/事件；此步仅验证将供sensor使用的函数，第6小步再证明实际sensor调用边界。

本步无配置或持久状态变更；中断后丢弃任务内缓存，下次重新读取本轮明确T/P记录，最后隔离读回的成本仍为上述9次API/22条结果及一份计划小记录，不扫描历史找旧结果。测试使用临时原生实例核无分区/T/P精确批读、同check跨日期、最新等待/失败/旧绑定均阻止、正常更新通过、生命周期先后和同任务零重复；实际job验证T停牌缓存交接。使用原日更/repair产出的有效观察及保存真实样本生成的小计划，核摘要无技术因子文件读取、错引用拒绝、repair不替代及job原物理校验保留；不以自造helper替代被验收函数。耗时按本轮隔离测量分别记录，不将上轮API探测或完整sensor目标当成本步实测。

**6. 实现只处理当天的sensor。**新文件固定`defs/sensors/raw_tushare_stk_factor_pro_update_job_sensor.py`。按§21.3的轻量顺序，先时间/分区、已有当前slot提交、活动写入，再取得T/P就绪及当前日/历史结果；无需更新且权威摘要未变即结束。有必要才准备E/F并调用第3小步。源端不齐或源调用失败是本slot探测结果，cursor记已探测slot，后续合法slot重探测；仅本地依据尚未就绪时可在同slot等待，不保存未发生的源探测。跨slot返回不提交，也不把新slot标成已探测。ready且仍处同D/slot才提交一条today请求，使用`build_asset_update_run_key(subject=现有update job名, unit_id=由D/T/slot组成的明确业务单元)`；日期/slot来自本轮判断，不能反解析run_key。tags显式保存执行日、目标日和slot供持久过滤，不放DG事件编号。cursor只存D/slot/小摘要；清cursor后run_key及已保存run仍去重，不查旧tick。此行为依据[Dagster sensor的run key与cursor规则](https://dagster.io/docs/guides/automate/sensors)，同sensor同run_key不会因cursor重置再创建任务。

测试模拟19:00/23:30/午夜、休市、本地晚就绪、源不齐后下一slot、探测跨slot、清cursor/实例重开、活动repair、前日缺口而今天齐备。固定一次评估最多一个RunRequest。预检/下载/历史失败沿现有retryable及同T当前结果判断，不引入旧补前日的机会状态。若本数据集源查询失败但结果未知，不能把空集合当成功。

本步同步更新本日更sensor的Definitions断言和治理测试清单，不延后到第7小步。当前definitions.py通过load_from_defs_folder自动装载defs目录中的定义，新文件加入后即进入Definitions。因此，test_stk_factor_pro_definitions.py须将原“不存在日更sensor”的断言改为确认该确切名称存在，并核默认STOPPED、60秒最小评估间隔及定义tags；test_run_contract_static_gates.py的EXPECTED_SENSOR_DEFINITION_IDS须同步加入本日更sensor的文件及函数身份。两项均随本步实现使用既有受保护runner验证，不保留与新代码冲突的旧断言。此调整只改变本数据集测试和登记的完成步骤，不改变sensor业务规则或正式启用授权。

**7. 串联和治理。**使用临时实例、模拟时钟、已有261字段和两列有界样本，串联注册分区、源等待、完整日发布、午夜留下缺口、下一日更新及manual_date补旧日、复权历史源仍旧/随后成功。重新打开实例并清cursor核持久去重。同步`dagster-run-contract-governance.html`、`dagster-asset-job-topology.html`，并复核第6小步已同步更新的Definitions断言和治理测试清单；两个确切名称、60/600秒、定义tags和STOPPED均核。分区注册器不因旧自动前日逻辑清退而删掉上一交易日注册功能。受保护测试按既有`stock_suspend_confirmed_test_runner.py`，普通定向测试使用本项目现有.venv和工程外临时目录；不安装依赖、不写正式instance或Lake。每步回写实际证据，未完成项目明确列出。

### 21.14 配置、读取量、恢复与验收成本

新增覆盖版本是代码合同常量，默认固定"1"，无env/运营覆盖；随代码加载对新结果生效，持久于RawCoverage/BootstrapDateCoverage、观察metadata及覆盖输入摘要。消费者是纯结果包装、复用判断、历史资格、bootstrap当前统计和测试；不进入历史名单/成功摘要。七字段的持久位置和用途按§21.4；删除的两项次数不保留别名。以下预算补充§10，不另造性能配置。

| 阶段 | 数量依据、读写和预算 | 中断、继续及最后核验 |
| --- | --- | --- |
| 本地上游 | 当前spec：股票基础信息2项check、生命周期3项、T/P复权因子各3项、停牌Raw2项/Silver3项；6条物化+16条check。6次物化API，check按无分区/T/P三组，共9次API、最多22条相关结果；不等同数据库内部固定9条SQL。 | 本轮全部结果传known_pg，job不复查同事实。进程重启重新读取；隔离spy核API量并记录实际数据库/事件读取，不扫旧check历史。 |
| 运行和阶段记录 | 当前slot按sensor/job/确切run_key查一次limit=1，只判断是否已提交，不按整晚读取次数；活动两job各limit=2。阶段入口最新1条，日/历史明确引用各至多1条，原生run/失败读取按§6.2的不同真实身份首次计入，引用已得对象不重查。 | 缺引用或明确坏记录按原失败处理；不恢复旧tick和机会。实际run数、查询数分别记，不能把阶段reader调用算一次PG查询。 |
| 应有集合与摘要 | 一个必要评估最多准备SSE日历、生命周期、身份和T最终停牌四份依据一次，投影业务必要列；T/P权威复权因子摘要各一次，日计划小记录一次。文件SHA读取仍按实际字节另记，不能说只读了投影列。 | 无技术因子261字段/全历史扫描，不写探测代码文件；重开丢弃内存关系，下次重新准备。日历以精确T/pretrade_date定P，不沿缺行tuple改选。 |
| 两列源请求 | 单目标T、无股票/枚举展开；N行按页容量10,000，完整请求数floor(N/10000)+1。样本5,572/5,573行各1请求；恰满页须再取空终页。正常cursor下一晚最多10次探测，实际总请求为各次页数之和，重置cursor另计。 | 进程退出后不保存页进度，下个合法slot完整重探测；不齐不启动job，午夜无自动补前日。一次完整探测的请求数、源行数、页数、代码数及耗时记入摘要。 |
| HTTP时限与容量 | 读取现有ConfigurationSnapshot：默认request_timeout_seconds=45秒、connect=5秒、read=30秒、poll=0.1秒、响应64MiB及unit工作空间2GiB；不创建另一套env值。探测总deadline=探测开始monotonic+现有request_timeout_seconds，分页共用该时限。每页三个超时取原值与剩余时间的较小值；余时不足现有poll间隔就结束，不发下一请求；同tick无重试。 | 这些是既有配置及本探测的共用余时方式，不是5秒性能目标。异常立即关闭已拥有连接/响应/内存；下一合法slot全新请求。总tick还包含本地计算和事件读取，不能把45秒说成整个评估的绝对上界；用工程计时核对现有60秒gRPC边界，超过时先定位并修订实现，不加任意余量或抬目标。 |
| 完整日job | 自动不重复两列探测；人工manual_date/bootstrap用途先探测一次。261字段完整下载按§10；当前源、最终候选各一次集合运算，复用已准备E/F和当前SQL关系。通过后两层各一份文件、一条物化和绑定检查，原有audit/提升次数不增加。 | 源/候选不齐首次提升0；Raw已发Silver失败保留已发层，新run完整重下T。最后读回本次临时目标两份文件及对应记录一次；取消状态读取另沿§10公式。 |
| 历史与初始化 | 原sum(floor(H_i/10000)+1)对象完整历史请求、20交易日合并、逐文件提升及原批准范围统计预算沿§10/§18，不因新日门槛增加历史覆盖扫描。 | 历史失败完整失败范围重下；整范围成功引用仍直接复用。初始化统计仅相应用途更新已有日期贡献，最后summary不再读全部业务文件，最终样本读回不扩为全历史审计。 |

性能记录分正常首次、无需更新、同slot已提交/已探测、源不齐、源异常、跨slot、重开实例和最后验收；记录本地SQL/文件SHA、事件/运行、HTTP及清理各阶段实际耗时、数量。5秒sensor、120秒无历史日更及1200秒历史参考沿原管理员接受的性能目标，不能变成新硬超时。现有MCP0.482/0.526秒和局部DuckDB耗时只证明那些阶段，不证明工程全部评估满足5秒。工程最小验证复用既有有界来源，缺少的投影HTTP和事件批量读取证据在相应小步补齐，不为计时重拉全市场261字段或全历史。

### 21.15 本轮复审结论与交付条件

本轮使用CodeGraph explore/callers/impact核对日更、配置、纯覆盖及共享入口，再逐项读取当前代码验证；RunIdentity的callers未列出调用方，公共纯覆盖函数impact也只列本文件，已用rg补核assets、repair、bootstrap、私有算法及测试中的真实消费者，不把图结果当作完整清单。另核已安装Dagster的分区最新check查询实现、HTTP传输/响应解析、readiness spec、bootstrap包装及源字段合同。检查范围不含其他任务的脏文件清理、Prod修改或正式数据操作。

| 发现的具体矛盾/遗漏 | 已写明的处理及交付证明 |
| --- | --- |
| 原方案§15.1仍要求先补前日，历史结果段仍允许部分发布 | 删除旧执行指令；自动仅当天，预检SUCCESS不冒充完整日成功。旧批次有日期证据保留并标明当时含义。 |
| 首日可选只在新章写明，原纯函数签名及实际计数不一致 | §5.2.1、§10.5.3与本章统一optional关系及E/F/C；actual_count为参与比较代码数，物理行数保留全部源行。 |
| 当前Raw及bootstrap“齐备”只判断缺码 | 两种结果均检查missing=0 AND extra=0；独立反例证明多一只会阻断，并证明首日实际有行不会误拦。 |
| 日发布后才计算覆盖；多余旧Raw可能被合并留下 | 前移两次不同实际侧检查，旧行多码停止并报告，无自动删业务行授权。 |
| 旧次数字段留空仍进入共享记录和测试 | 按§21.12同步移除当前生产者/消费者；先核正式记录，不私自迁移或清空旧状态。真实历史授权、完成和失败事实继续保留。 |
| sensor复用旧摘要helper会重读两层261字段；上游helper可深扫80,000条check | 抽出只读明确日计划的小函数；按目标物化和分区批读最新check，查询数量及反向测试已列清。 |
| 源探测目录错误、与正式261字段下载职责混淆 | 固定source_readiness位置及PageRequest投影，复用现有HTTP/完整契约，不复制会过滤额外代码的指数逻辑，不修改通用RequestBuilder。 |
| 五秒目标被误作运行时限 | 恢复原目标含义；探测余时引用现有45秒配置，分别测全评估及gRPC约束，不声称既有MCP耗时就是工程验收。 |

设计中的旧业务要求已从执行条款撤销，代码尚待按表清退；两者不得混称完成。开始正式编码前逐小步核本章和最新影响面，记录格式计数、投影HTTP及有界事件读取分别在对应步骤完成最小验证。定义装载、隔离串联和实测通过后才能报告该步实现通过。正式bootstrap、补日、历史事件补录、code location操作和sensor启用继续分别授权。本轮不执行这些操作，也不提交代码。

### 21.16 第1小步实现与独立审计（2026-11-11）

本节是§21.13第1小步“统一集合与记录”的实际结果，不代表第六批全部完成。前置条件复用本会话2026-11-11北京时间14:09的只读核验：正式两job运行数均0、两资产物化/阶段观察均0，Raw/Silver及本数据集staging根不存在；两资产各1条freshness状态事件不含本次业务记录。没有正式旧业务记录需要迁移。开发和验收仅使用工程外临时资源与已有一股五日261字段样本，没有新的源端或Prod查询。

| LLD硬口径 | 实际实现 | 主要验证 |
| --- | --- | --- |
| 首日可缺、已有行保留、下一交易日起必需 | readiness的公共/私有build新增必传optional_relation；calculate从本次生命周期取list_date=T。prepare先统一上市/停牌/首日代码，F与有效上市扣停牌集合相交，再得E；compare将当前实际代码统一后减F，计算缺失和额外。 | coverage的首日缺/有、次日、全天停牌/未上市不能借可选关系通过、首日身份别名、必需缺失、身份未知与四侧样本升序；readiness使用临时Parquet及真实绑定物化/check核历史资格。 |
| 只算本次必要数据、显式交接E/F及映射 | `_prepare_stk_factor_pro_expected_keys`将E/F及basis_mapping_relation交接，calculate在本日期coverage_inputs保存同连接关系；compare仅为实际新增原代码核身份，复用既有映射。release与日期/连接生命周期一起清除这些关系及引用。 | 同日不同实际输入应有集合和基础映射各创建1次；可信内部路径没有DESCRIBE/重复输入有效性审计。未知身份不遗留旧差集；中断保留原异常并尝试释放全部自有表。 |
| 缺0且多0才齐备，未知不伪造0 | RawCoverage新增extra_count和coverage_rule_version，complete=True要求两项差集均0且参与比较数量相等；evaluator、require和repair资格同步；失败metadata含多码与版本。 | 完整文件/check通过但有1个额外全天停牌代码时，覆盖False且不能进入历史；首日缺/有两种情况下Raw实际1/2行，参与比较均1，历史资格均通过。 |
| 本规则结果不能复用旧统计 | run_contracts固定COVERAGE_RULE_VERSION="1"；Raw及bootstrap日期记录保存它。日更、repair、结果包装及bootstrap日期复用核版本；bootstrap月/日覆盖输入摘要加入同一常量。 | 保持文件SHA不变而改变规则版本，Raw显式复用拒绝、bootstrap已缓存结果拒绝、月/日摘要均变化。新记录仍用封闭字段解析，未新增旧格式兼容分支。 |
| 参与比较数量与原导入/物理行数分开 | bootstrap包装和汇总复用唯一calculated；expected/actual为E/C，source_rows、Raw/Silver行数和raw_physical_code_count保留全部实际行。日更摘要改称“参与核对”，多码另列。 | 首日缺行时源与两层均2行、E/C均2；首日有行时源与两层均3行、E/C仍2。原导入数量及current数量均如实，Raw首日代码仍存在。 |
| 多码不能误报bootstrap整体齐备 | DateCoverage.coverage_complete也要求缺0且多0。summary.all_expected_present继续只说明必需代码都存在；结束摘要同时核extra_count_known_dates=0才显示complete。 | 忠实导入3行而仅2只必需、另1只是全天停牌时，不删源行，日期覆盖False、额外1，最终摘要incomplete。 |
| 历史算法与下一小步边界 | 未改RunInput、RunIdentity、T/P规划、历史业务摘要、历史范围及下载/发布实现；仅同步历史资格所消费的覆盖结构和清理调用。 | 开发后按AST独立核9个运行/历史规划与摘要符号，另核history/download/publication三文件字节与实施前相同。既有完整历史、失败整范围重下、repair授权和硬退出回归保留。 |

**消费者核对。**生产改动限定readiness、run_contracts、assets、history_repair及bootstrap history/coverage六个既有文件。RawCoverage全部构造处、bootstrap日期记录及原输入摘要、日更/repair的旧统计复用、JSON字面样本和异常清理调用已同步。删除旧重复的reusable赋值，保留唯一实际判断。测试中的同输入“计算一次”观察改为当前compare入口，同时保留SQL次数、文件SHA及零空附件断言，未把读取或计算错误吞掉。既有历史原因7由原第1步自动追修实现，旧基础测试遗漏该原因，本轮只按§20.2修正旧断言。

**实际检查。**普通回归显式列出48个本数据集测试文件，排除必须受保护运行的Definitions。共969项，完整执行968项通过；唯一失败是本轮新增测试将身份异常代码样本顺序写反，预期应按既定升序为300001.SZ、600000.SH。修正该字面断言后，覆盖与完整JSON合同边界两个文件共52项重跑全部通过；未再改生产代码。受保护Definitions按原runner另外1项通过。所有变更Python文件Ruff、全src/tests致命错误检查、文档完整性及git diff空白检查通过。

第一次普通回归误将Definitions文件也显式传给pytest，--ignore没有排除这个显式输入，测试在导入隔离支持模块时失败，未进入定义装载；随后改为生成排除该文件的明确清单。Definitions始终以原受保护runner的通过结果为准。该runner在工具沙箱内因sandbox-exec不允许嵌套未能启动，采用同一runner经工具授权后通过，没有绕过隔离。3个既有本地HTTP模拟用例也因工具沙箱不允许绑定127.0.0.1而未启动，最终普通回归在允许本地模拟服务的执行环境完成；不连接正式Tushare或其他外部来源。

**独立审计。**开发完成后重新读取实际改动，与实施前源码及独立字面样本比较，不用待测函数生成预期。两股票人工样本中，首日缺新股时旧计数(expected/actual/missing/extra)=(2,1,1,0)，新计数=(1,1,0,0)；首日有行时旧=(2,2,0,0)，新=(1,1,0,0)，两行仍在；下一交易日缺该股时两实现均为(2,1,1,0)。另验证旧RawCoverage类型允许缺0、多1时标齐备，新类型拒绝。新实现3次内存集合计算实测11.198、10.245、9.708毫秒，范围仅这3个人工样本，未含源请求、正式文件、Dagster读取或完整sensor开销。CodeGraph explore/impact后用rg补齐直接消费者，结束执行sync及status；图未覆盖的动态序列化边界由实际代码和JSON测试核对。

独立审计未发现本小步未实现的业务要求。曾发现并修复日更/repair清理调用遗漏和JSON字面样本漏新增字段，受影响回归已重跑。运行配置的previous_day及两项次数字段仍按第2小步删除；本轮没有实现manual_date、源端两列探测、发布前门槛、日更sensor，或执行正式bootstrap/事件补录/自动化启用。临时审计脚本和日志收尾删除，保留本节必要结论。本轮代码尚未提交。

### 21.17 第2小步实现与独立审计（2026-11-11）

已按§21.13第2小步完成七字段配置与指定日期身份。实施前使用CodeGraph explore、impact核共享输入和身份，再以当前rg及源码补齐图未列出的日更、readiness、bootstrap、repair和测试消费者；_open_calendar的callers未完整列出repair，已按真实调用同步修改。开发后执行codegraph sync/status，索引状态正常。正式旧记录处理复用本会话16:24只读计数：两job运行和两资产物化/阶段观察均0，本数据集正式Raw/Silver和staging目录不存在；两项freshness状态事件没有本次业务记录。没有运行时兼容或正式旧记录迁移。

| LLD硬口径 | 实现位置与实际行为 | 验证 |
| --- | --- | --- |
| 七字段，旧用途及两字段删除 | run_contracts的用途、配置schema、RunInput、RunIdentity、观察schema和builder同步删除旧项；readiness读原配置、观察和parent/root核七字段，bootstrap授权错误说明同步。 | foundations、recorded_results及manual_date测试核精确字段、原生配置默认值和序列化；旧字段即使为null，配置、观察、嵌入身份均拒绝。完整JSON字面样本同步迁移。 |
| today只支持T=D；人工允许无parent、T<D、D休市 | RunInput核日期关系；manual_date不占slot、不带bootstrap三项授权。assets首次人工核D为上海本次日期，原生重执行沿原输入，不以新开始日期替换。 | 独立字面配置11月11日补11月10日、11月14日休市提交均通过；T=D/未来、错分区、旧用途、人工slot和越权bootstrap字段拒绝。临时真实job在开市/休市D均可无parent进入真实precheck，下载及物化为0。 |
| T记录的pretrade_date决定严格P | _open_calendar一次投影已核日历关系的SSE开市日期及pretrade_date；parse和repair共用严格P判断。日更/repair给历史规划及bootstrap的仍是同一升序日期tuple。 | 使用Silver日历生产者schema构造有界Parquet：正常周一/周五通过；缺周五但有周四、周五休市、其他交易所同日、P为空/P=T/P>T及T休市均拒绝。真实job缺P在规划/下载前失败，没有本run staging记录或物化。 |
| 普通补日不读初始化记录；重执行保持原授权 | 普通用途保留既有非bootstrap分支，source_run_id/parent/root和开始观察继续使用；人工首次日期检查不限制原生跨日重执行。 | 普通人工授权loader调用0、初始化resolver调用0；原生manual_date从10月16日提交到10月19日重执行仍下载原10月15日，没有写10月16日。改原用途或目标日期拒绝。bootstrap首次授权、错摘要、缺口变0后原授权复用及repair原范围回归通过。 |
| 不调整股票复权因子历史算法及发布过程 | 生产只改run_contracts、assets、readiness、bootstrap授权和repair五文件；历史repair仅同步身份和严格P。 | 与实施前副本逐字比较io/stk_factor_pro_history.py、io/stk_factor_pro_download.py、io/stk_factor_pro_publication.py均相同；AST核其余contract函数及历史业务摘要函数未变，原完整范围重下、取消/硬退出和逐文件发布回归继续通过。 |

**实际验证与成本。**普通隔离回归显式列出49个文件，排除受保护Definitions，997项一次完整执行全部通过，耗时345.70秒。受保护Definitions1项和运行合同静态门禁113项分别按既有runner通过；全部变更Python文件Ruff、全src/tests致命错误检查、文档完整性与空白检查通过。既有本地HTTP模拟用例仅连接回环测试服务，全部Lake/实例写入为工程外临时资源；没有新增正式源查询、正式资源执行、依赖安装或sensor操作。

新增测试曾把解析后的date预期误写为字符串，并误用Dagster结果方法名；按既有date合同和已安装execution_result API纠正后，上述完整997项通过，没有为迎合测试改生产行为。前轮125项定向验证也是通过记录，不与997项重复累加。

开发后另加载实施前源码作独立对照，不用待测函数生成预期：旧输入拒绝的两种manual_date字面日期现可通过；周一缺周五的旧开市tuple会接受并取周四，新映射拒绝，正常周五仍通过；旧身份带null次数字段原可接受，新封闭parser拒绝。五个开市日期的内存样本，三次配置解析实测0.010125、0.006000、0.004958毫秒，仅代表这三次解析；不是完整job或sensor性能。日期映射复用已读关系，没有额外日历文件读取；原生重执行的parent/root读取及复用边界不变。

本步独立审计未发现遗漏。源端两列探测、发布前完整日门槛、完整manual_date日更新验收、日更sensor均未提前实施，分别留给第3小步以后。未提交本步代码；正式bootstrap、补日、事件补录和自动化启用均未执行。临时副本、脚本、测试输出和日志收尾删除，只保留原文档中的必要结果。

### 21.18 第3小步实现与独立审计（2026-11-11）

文档修正先提交939f5a263，仅删除两列探测额外响应字节统计要求。其后完成本小步，生产只新增defs/source_readiness/stk_factor_pro.py，测试为test_stk_factor_pro_source_probe.py；原有生产文件、通用下载器及其他数据集均未修改。开工前复用本章并补齐同一节的函数输入、结果、失败及资源所有权，没有新增另一份方案。

| 硬口径 | 实际代码与读取边界 | 验证 |
| --- | --- | --- |
| 同一接口、固定两列、单目标日、无股票过滤 | PageRequest固定stk_factor_pro、ts_code/trade_date和YYYYMMDD(T)，分页容量取完整源契约；ConfigurationSnapshot只由调用方传入，函数不加载配置。 | 真实localhost HTTP逐项核payload，额外字段/缺列拒绝，两列交换顺序正常通过；完整261字段契约本身未变。 |
| 10,000行满页必须继续，短/空页才结束 | 每页一次fetch_page、attempt_number=1，不走DownloadSession/RequestBuilder/UnitOutput。原主键临时表按页批量插入，拒绝页内和跨页重复。 | 10,000+0及10,000+1均为2请求，offset分别0/10000；超长页、满第一页后第二页503/错日/字段变化/重复均不计算齐备；源错误不重试。 |
| E/F及身份规则复用，多码保留 | 完整源关系直接交calculate一次，复用同连接coverage_keys；原始唯一代码数与排除可选首日后的actual_count分开。 | 首日缺/有均通过，周四上市到周五缺码拒绝；额外普通股及全天停牌股均多1而拒绝。身份别名正常通过，未映射/歧义为未知，不能过滤后放行。同T两次探测只准备一次E/F；Path.open替身证明探测不读文件。 |
| 未知输入、源不齐及失败不能伪造成功 | 未知依据/未确认开市零HTTP；字段、日期、非空代码及主键错误为SOURCE_PROTOCOL。源结果不完整时不报完整代码数；身份未知时保留完整源代码数，但不报覆盖齐备。 | 空终页字段有效时正常计算缺失，缺响应及源失败保留未知；source_row_count只记录本轮已解析行，未知覆盖计数不冒充缺0。 |
| 全探测共用原45秒预算，仍遵守现有容量 | 每页按剩余时限收紧三种超时；余时不足poll不再请求；计算及关闭后再核deadline。 | 模拟首满页用40秒后第二页三个超时均5秒；用44.95/45秒均零第二请求。真实等待响应发生超时/取消并关闭句柄；关闭用满预算也不放行。既有响应及UnitMemory容量不足均不齐备。 |
| 关闭及取消保持真实失败，不额外写状态 | 复用既有resource_cleanup，尝试关闭传输、内存、控制器及本函数临时表；保留调用方E/F。取消原样向上，本地SQL错误原样向上。 | 关闭错误使成功源也不齐备；源失败/取消与关闭失败同时发生时保留原失败及清理说明，内存清空和临时表释放继续尝试。普通SQL错误不会被当作源等待。探测无文件、事件或任务提交入口。 |

**真实合同与隔离链路。**读取本地Tushare doc328的参数/两列类型及限量，结合第一批真实分页证据（000001.SZ、2026-10-12至16、limit=2的三页及完整261字段样本）。本轮复用其中10月16日的真实代码/日期，独立断言为000001.SZ/20261016；按完整生产者schema准备临时生命周期/身份/停牌/日历Parquet，经过现有prepare、真实localhost HTTP、完整契约的parse_http、纯覆盖及小结果，源/应有/实际均1。网络响应由测试服务重放，不是新的Tushare实测或正式环境验收。没有新增源请求、Prod查询、正式instance或Lake操作、安装、sensor启停或分区注册。

**实际检查。**最终直接回归145项一次完整通过（新探测45项），10.57秒；受保护Definitions1项及静态门禁113项分别按既有runner通过。变更Python文件Ruff及全src/tests致命错误检查通过。初轮31项通过、3项因测试误用FakeClock.now失败；读取既有夹具后改为seconds，截止时间及预期未放宽，生产代码未因此改变。临时独立审计首次直接执行时无法导入项目tests，改从项目目录以-c执行同一临时脚本后通过，没有改PYTHONPATH或安装环境。

**独立审计。**使用CodeGraph explore/impact核传输、parse_http、共享覆盖及依赖，再以当前源码补齐图未列全的调用；开发后sync/status正常。开发前37份既有本数据集及通用下载组件文件逐字比较均未变，源码确认无job/sensor/事件/业务文件调用。另在临时内存副本故意改成满页即停止：满10,000行后实际源503的例子，错误副本1请求误放行，实际实现2请求拒绝。再故意移除extra=0，E={A}、F={B}、源={A,C}的例子错误副本误放行，实际实现拒绝并保留extra=1。两个对照独立于待测函数计算预期，证明能抓住本次真实禁止项。

**局部性能。**单线程临时DuckDB、已准备关系、真实本机HTTP及5,573个合成代码，三次新连接首次探测分别119.188、119.221、119.077毫秒，均1请求/1页，包含本次E/F、集合比较及关闭。不含真实Tushare网络延迟、上游文件SHA/准备或DG事件读取，不作为完整sensor五秒目标的证明。关闭错误、deadline、中断后的新调用从offset=0开始；无需保存源页或做额外历史扫描。

本小步独立审计未发现遗漏。第4小步的发布前完整日门槛和人工入口接通、第5小步上游/摘要优化、第6小步sensor及第7小步串联均未提前实施。代码及本次实施记录尚未提交；临时脚本、错误副本、测试输出和日志收尾删除，必要证据保留本节。

### 21.19 第4小步实现与独立审计（2026-11-11）

本节仅验收§21.13第4小步。实施前在本章及方案§17.4补齐实际调用、配置来源、故障恢复及读取预算，再开始编码。生产修改限定assets/stk_factor_pro.py、asset_guards/stk_factor_pro_readiness.py、io/stk_factor_pro_publication.py；bootstrap覆盖模块和历史repair的生产实现未修改，没有新增配置、正式路径、返回包装类或兼容分支。

| 硬口径 | 当前实现及验证 |
| --- | --- |
| 下载前准备应有代码和必要上游 | job先核股票基础信息、生命周期最新物化及绑定检查，生命周期不得早于基础信息；原T/P股票复权因子和T停牌就绪要求保留。两份无分区物化各取1条、5项检查一次批读，同known_pg再次调用零增量读取，真实临时事件已核2次物化API和1次检查API。原生失败、缺检查、错绑定、错分区、过旧日期、生命周期早于基础信息均拒绝，正常新物化通过；缺身份或停牌文件时零计划/下载/发布。 |
| 人工入口先探测 | manual_date与bootstrap_supplement在保存计划、start观察和261字段下载前调用第3小步探测；未齐仅有precheck。实际人工job与初始化job均验证未齐零计划及正式下载；普通人工不进入bootstrap授权读取。today不重复探测，原生重执行保持原用途。配置沿ConfigurationLoader现有来源读取，未增参数或持久配置。 |
| 本次完整日源不能由旧行补齐 | calculate对DAY_SOURCE计算一次，缺/多/空在候选前以day失败结束，数量和至多20个样本进入失败metadata。实际job先放完整旧Raw，再返回缺1只的当前源，确认旧Raw字节不变、无Silver及物化；额外有效身份代码和零行也拒绝。身份未知不伪造0。 |
| 最终候选在任何Raw发布前检查 | publisher必传on_raw_candidate，唯一候选audit后、_publish_file前恰调用一次，包括等价发布。asset闭包对RAW_EXPECTED计算一次；旧Raw中的退市额外代码使候选失败，零提升/物化，不删旧行。publisher仍yield原(target,audit)，on_publish_attempt语义不变，IO没有引入readiness依赖。 |
| 一份依据复用，各实际输入分别检查 | prepare_stk_factor_pro_expected_coverage_keys从原calculate原样提取上市、全天停牌、首日及身份准备。自动任务E/F一次、日源和候选各一次；真实HTTP人工回放也核E/F一次、两列/日源/候选三种实际输入各一次。候选calculated直接交evaluate与初始化统计，不重算或读取正式Raw/Silver来证明相同覆盖。 |
| 日完成与统计 | 两层文件、实际物化/check、覆盖均有效才写day completed；删除usable返回标记、部分日completed、空源waiting及随后缺股等待分支。首日缺/有两种情况均完整发布，实际首日行及合法NULL保留。初始化补日的独立样本保留原导入source_rows=1，当前Raw/Silver各3行、missing=0，零差集无空名单附件；历史日期仍显式传calculated=None沿原算法处理。 |
| 午夜、中断和失败 | 新自动today在计划后、start前复核原D/时点，跨午夜零正式下载；原生跨日重执行沿原身份。实际job的Silver失败或Raw物化未保存均报失败并保留Raw，下一run重新下载完整T并发布两层；原跨进程硬退出、新进程完整重下和历史失败整范围重下回归通过。历史源等待、名单授权和d<T边界未改。 |

**旧测试清退。**早期dagster_events测试用自造generator模拟“部分日照常发布”和“空源先保存缺股诊断/统计再waiting”。这些分支及其5个旧用例已删除，保留原生事件顺序、绑定、失败、选择不完整及持久化API测试；新的业务准入由实际日更job测试验证。其他publisher机制测试显式提供no-op回调，只验证文件发布机制，不将其作为市场代码齐备证据。初始化repair原夹具只返回B、借旧Raw保留A才进入历史，这与新要求冲突；改为当日日源A/B齐全后再注入原历史失败，原repair范围、日期写入及统计断言保留。覆盖清理故障测试原先依赖“实际比较后才释放应有输入”的顺序；提取准备函数后改为分别在应有准备、实际比较发生主取消，再注入各自清理失败，仍验证原取消不被覆盖且全部自有关系尝试释放。没有为了测试恢复旧业务分支。

**验收证据。**全量51文件回归首次1064项中1062通过、上述2项旧夹具假设失败，耗时355.93秒；修正后bootstrap coverage和history repair两个文件60项全部通过，57.48秒。最终版本的complete_day、dagster_events、jobs、batch5_job_integration、publication五文件76项全部通过，83.31秒。没有把首次全量称为全部通过。Definitions经原受保护runner 1项通过，运行合同静态治理113项通过；全部变更Python Ruff、全src/tests致命错误、文档完整性和git diff空白检查通过。

另以21只必需股票、源0行补验失败诊断上限，1项通过、1.88秒：missing_count如实为21，缺失样本仅前20只、额外样本为空，Raw未发布且未写缺股Parquet附件。该用例直接运行实际job，不与待测函数共享预期计算。

来源验证复用已保存真实000001.SZ的2026-10-16完整261字段行，在本机HTTP依次实际接收两列请求与完整字段请求，各返回1行；实际manual_date job完成Raw/Silver及各自绑定检查。核物理Raw的trade_date为VARCHAR、pe为DOUBLE及已知值5.2346，显式关闭DuckDB目录分区推断，避免目录日期遮住文件实际类型。单次job计时0.809秒，包含本机回放和临时实例的该次执行，不含创建上游夹具；不作为正式Tushare、全市场或sensor耗时保证。其他单元/任务测试明确替代上游状态或HTTP；真实临时事件另核基础输入绑定，真实源HTTP边界由上述回放覆盖。本轮无新的正式源/Prod查询，无正式数据或DG状态写入。

**独立审计。**重新读取改动和实施前快照：_plan_history、_basis_for_day、_factor_file_refs、初始化结果持久化函数AST不变；_publish_history仅增加初始化统计calculated=None的显式交接。完整历史下载、历史IO、repair、bootstrap history/coverage、run_contracts、两列探测七个生产文件逐字节不变。当前生产publisher调用只有asset一处，必传回调已迁移；测试调用及跨进程代码一并核验。临时撤掉日源门槛时，缺1只的源借旧Raw发布，实际任务回归失败；临时撤掉候选门槛时，旧额外代码先发布才日失败，零发布断言失败。两项错误均被本轮回归捕获，审计变体只在临时进程生效。CodeGraph explore/impact核入口及依赖后，用当前rg和AST补齐图未列出的asset调用、动态generator和统计交接，结束sync/status正常。

未发现本小步剩余遗漏。未实施第5小步完整上游/日摘要读取、第6小步日更sensor或第7小步串联；未执行正式资源操作。第4小步代码及验收记录随本轮提交。临时副本、脚本和测试输出收尾删除，必要结果保留本节。

### 21.20 第5小步实现、独立审计与治理待办（2026-11-11）

本轮只实施§21.13第5小步。编码前已在原方案§17.3及本章写清两个入口、直接消费者、配置/读写边界、缓存交接、中断恢复和验证；复用既有9次API/22条结果预算，没有新增配置、状态文件、sensor或依赖安装。生产改动为本数据集readiness、assets和repair的引用迁移三个文件；通用sensors/readiness.py没有改动。

| 硬口径 | 实现与验证 |
| --- | --- |
| 同一任务只读必要上游 | read_stk_factor_pro_upstream_status返回既有DatasetReadinessStatus。两份无分区物化、T的股票复权因子Raw和停牌Raw/Silver、P的股票复权因子Raw各取最新1条；check分无分区/T/P三组，以PartitionKeyFilter精确过滤。原生临时事件核6次limit=1物化API、3次check批读，返回5/8/3项check，合计22条记录；同known_pg再次调用是同结果对象，新增API和SQL均0。 |
| 不深扫、不用旧成功掩盖当前状态 | 不调用get_asset_check_execution_history；只有最新SUCCEEDED且passed/blocking、资产/分区、storage_id/run_id/timestamp绑定正确才通过。原生PLANNED、失败、无绑定、错run/时间、旧物化绑定及空实例均未就绪。T/P任一失败不会污染另一分区的正常结果，正常新物化和对应新检查可通过。 |
| 保持原日期和覆盖准备语义 | 全局输入仍按T核新鲜度，生命周期不得早于最新基础信息；分区资产沿原口径只核准确T/P，不增加自然日限制。删除asset的_reference_inputs_ready及日更T/P逐项旧调用；T停牌结果交既有suspend_readiness缓存，实际日更job在禁止通用深扫和二次T停牌读取的测试中正常发布。历史其他日期原停牌入口保留。 |
| 日摘要只读明确计划 | read_stk_factor_pro_day_plan_factor_shas接收已核日观察及两层check，沿其自身history_plan_ref取同T、同producer、同合同计划，核P后只返回T/P摘要。原生实际日更产出的观察和保存真实261字段样本所生成的计划作为输入，连续两次调用共打开1份history-plan.json，技术因子Raw/Silver及全历史读取0，既有known_records复用有效。 |
| 原真实性、repair与追修不变 | 旧job入口原日观察、绑定及物理SHA核验完整保留，再调用新摘要函数。Raw或Silver物理SHA不符时均停止，不调用新函数。缺引用、错producer/日期/P/digest及与任一层check的producer不符均拒绝；repair观察不能替代日观察。repair只把原股票复权因子检查的引用来源从daily改为通用readiness，参数与检查行为未改；原日摘要不被repair计划覆盖的既有回归保留。 |
| 中断、恢复及边界 | 两个新读取函数无文件、事件或源请求写入。缓存仅本任务持有，重启按原明确日期及引用重新读取，不扫描过去tick/check/历史文件。第4小步完整日准入、原生重执行和跨进程完整重下回归通过。真正sensor及其调用边界留第6小步，本节不声称实际sensor已验收。 |

**测试中的实际发现及修正。**原生PLANNED测试发现我在确认检查成功之前访问了只有完成记录才有的target_materialization_data，导致AttributeError。已将SUCCEEDED判断前移，再读取完成结果；该原生反例通过，没有以getattr兜底吞错。消费者审计起初漏掉repair经daily访问原上游函数，删除导出后两个repair用例报AttributeError。补核整个本数据集生产调用后，先补原方案/LLD范围，再将repair直接引用同一原函数，不恢复旧导出；测试替身同步到真实引用处。另有新增摘要夹具把观察缓存键写错，已按实际phase_result生产者修正，没有改业务预期。上述失败均在验收过程中发现，修正后的结果才用于本节结论。

**实际验证。**首次相关回归64项通过，源HTTP回放项另随完整回归执行；新上游16项通过，新摘要与repair等33项定向回归通过。修复消费者之后重新启动最终完整回归，明确列出53个本数据集文件、排除须受保护运行的Definitions，1092项全部通过，435.88秒。较早已装载修复前代码的整套回归被主动停止，其部分输出不作通过证据；部分取消测试会捕获中断信号，最终只终止了已确认的本轮临时pytest进程，未操作任何正式服务。Definitions经原受保护runner 1项通过。所有本轮Python Ruff、全src/tests致命错误、文档完整性及本轮文件git diff空白检查通过。工作区其他股票周期测试的空白问题不属于本轮，未改动，也不将全工作区空白检查称为通过。

**读取量与耗时。**独立临时SQLite实例使用真实6条上游物化和16项绑定检查，SQLAlchemy监听仅覆盖首次调用：9次API对应实际15条SQL、0.017857秒，第二次调用0条新增SQL。该数字不包括构造夹具、执行上游模拟job、source HTTP或完整sensor评估，也不作为正式PostgreSQL耗时保证。新日摘要真实文件访问测试仅打开一份计划JSON，故障输入不回退寻找别的历史计划。API数、结果数与SQL数分别记录，未把9次API称为9条SQL。

**独立审计。**重新从实施前快照核对，_plan_history、_published_day、_publish_history、_basis_for_day、_suspend_ready、_automatic_window六个函数AST不变；旧日摘要入口在计划读取之前的实际验证AST不变。repair函数AST仅有原检查函数的引用来源变化。历史下载、历史IO、日/历史publisher、候选、bootstrap coverage/history、run_contracts及两列探测八个生产文件逐字节不变。临时进程撤掉分区过滤，正常T/P就绪用例失败；恢复“最新未成功时回查旧成功”，原生PLANNED用例失败，证明确实能抓住本次禁止行为。变体未写入仓库。CodeGraph explore/callers/impact用于入口和引用分析；图未列出asset及repair的全部动态访问，已用当前全范围rg和AST补核全部本数据集调用，再执行sync/status，索引正常。消费者遗漏的错误如上明确记录，不用图覆盖不足代替说明。

**未通过的治理项。**原受保护运行合同治理runner在第7批停止，前6批通过，第7批为7通过/1失败，113项没有全部执行/通过。唯一已报告失败是test_sensor_definitions_use_registered_definition_tags：工作区其他新增sensors/moneyflow_ths_page_cleanup_sensor.py:raw_tushare_moneyflow_ths_page_cleanup_sensor未登记到EXPECTED_SENSOR_DEFINITION_IDS。该文件在本轮范围外，本轮没有新sensor，也未修改该文件、治理清单或过滤该失败。须由相应改动完成登记后重新运行原套件；本节只确认第5小步功能实现和隔离验证符合设计，不将全仓治理待办隐藏为通过。

本轮未进入第6小步，未执行正式bootstrap、补日、事件补录、code location操作或自动化启用。第5小步代码及验收记录随本轮提交。临时副本、脚本、变体、隔离实例和测试日志收尾删除，必要证据保留本节。
