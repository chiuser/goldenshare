# DG指定日期自动审计：五项补充LLD

日期：2026-10-31。状态：已按管理员review后的本LLD完成原入口开发、95项隔离验收、清理及实现对账，尚未执行正式日期审计或补数。对应[修改方案](automatic-audit-script-plan.md)。本文件定义当前原入口口径，原人工补查提纲不再作为常规执行步骤；实现证据见§14。

## 1. 硬口径、事实依据与范围

P1按当前catalog及模型定义分类；P2周月检查物理数据与观察日期；P3公告允许合法零行；P4周月仅使用现有Silver日历作为日期依据；P5失败/未核实/等待不算通过；P6日历、真正快照及湖健康明确排除；P7原按日/Serving语义保留，移入既有计数及错误分类修正；P8同一文件不重复扫描；P9无正式副作用；P10报告和退出状态准确。测试映射见§12。

源码依据以仓库`/Users/congming/github/goldenshare`为根：

下文`defs/`均指`lake_console/orchestrator/src/orchestrator/defs/`；未来修改白名单中的`scripts/`指本机skill目录`/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/`，不是仓库根scripts目录。

- `lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py`：`LAKE_ASSET_CATALOG`、`PARTITION_MODEL_DEFINITIONS`、`LakeAssetCatalogEntry`、`PartitionModelDefinition`及五项注册。目录列表不是数据事实。
- `defs/run_contracts/stock_period.py::period_for/source_period`：自然周坐标为周五，月坐标为YYYY-MM；`stock_period_update.py`只从此处导入函数，不为审计导入整个更新执行器。
- `defs/paths.py`：五项正式路径及现有Silver日历路径；catalog已复用这些helper，执行器使用catalog模板，不再拼一套路径。
- `defs/run_contracts/asset_column_schemas.py`：Raw/Silver周月的日期和频率列均为VARCHAR；公告六列均为VARCHAR；作为日期依据的Silver日历trade_date为DATE、is_open为BOOLEAN。
- `defs/anns_d_io.py::write_page/_audit_relation`：零行仍可生成合法Parquet，ann_date必须对应目标日，URL/rec_time允许缺失。原生公告检查会读取交付/源页，本审计不调用它们。
- `defs/stock_period_update.py::evaluate_daily_sensor`及源文档doc365：19:30触发，源说明19—20点发布；不是Silver超时合同。
- 原skill脚本的`_audit_trade_date/_stock_year_summary/_clickhouse_partition_summary/_direct_summary/main`，以及28日归档`lake_console/reports/datasets_recovery_20261028_20261029/audit_count_only.py.txt`及同目录`test_audit_count_only.py.txt`：旧分类问题、年度与ClickHouse日期计数、错误修正及直接调用方依据。归档代码只供审查，不改、不执行；不复制其固定28日入口或用模块替换保留双轨执行。

源说明参考本地doc365、doc176、doc26；本轮不改接口参数、不请求源，不把本次文档工作称为源端重新验证。DuckDB依据为官方[Parquet列投影与过滤](https://duckdb.org/docs/current/data/parquet/overview.html)、[Hive分区](https://duckdb.org/docs/current/data/partitioning/hive_partitioning.html)、[FILTER聚合](https://duckdb.org/docs/current/sql/query_syntax/filter.html)、[日期解析](https://duckdb.org/docs/current/sql/functions/dateformat.html)，通过Context7核对。

## 2. 文件、入口与实现职责

本次代码白名单只有skill内`scripts/audit_datasets.py`及新增`scripts/test_audit_datasets.py`。文档白名单为SKILL、本LLD、方案，以及仓库`lake_console/docs/architecture/dagster-local-operations-cheatsheet.md`第2节的审计用法/字段解释。该节已在隔离验收后同步；服务启动、分区写入命令和历史审计记录未改。仓库另保留非执行源码归档与验收证据，不构成另一套运行入口。没有新Dagster definition、业务字段合同、数据库表、配置文件或跨工程依赖。

| 函数/落点 | 必须实现的职责 |
| --- | --- |
| `_parse_args` | 保留--date/--repo-root/--lake-root/--output-dir；用严格ISO格式加date解析拒绝不存在日期；重复日期按首次顺序去重 |
| `_load_catalog` | 保留原返回catalog的入口；从同一repo加载模型定义；不得初始化instance、resource或扫描Lake |
| `_build_audit_plan`（新增） | 纯函数：catalog/model核对、策略选择、精确文件、日期条件、排除/未知项、跨日期去重；不做IO |
| `_load_calendar_windows`（新增） | 仅从现有Silver日历一次取得周月所需SSE日期依据，供所有目标日期复用；不生成日历审计结果，不读取Raw日历 |
| `_period_summary`（新增） | 每个精确周/月文件一次统计，覆盖该路径所有请求日期的阈值；返回物理及更新观察，不读价格 |
| `_announcement_summary`（新增） | 每个指定自然日文件一次ann_date统计，合法空与坏文件分开 |
| `_stock_year_summary` | 同一年度文件族仅按所请求日期count(*)，去掉code_count及分钟时间极值；多日期同年合并到一次计数查询 |
| `_clickhouse_partition_summary` | 本机/Prod沿原白名单表按指定日期count()，保留原日期过滤与限额；删除代码去重、空值统计及对应附加字段，不增加另一套入口 |
| `_normalize_report`（新增） | 五组叶子结果统一分类、互斥计数、缺失/滞后/等待/未核实列表和最终判定 |
| `_audit_trade_date/main` | 单日和多日期使用同一套实现；一次调用固定observed_at和缓存，开始时一次检查Lake根并建立共享连接；失败直接报错退出。保留单日函数及三项原必传参数，不另建旧版本执行分支 |

实现可增加少量只负责版本stat、日期归一化和JSON输出的私有函数，不能引入另一套正式入口或通用治理框架。文件数和策略事实从catalog发现；测试使用同样的实际catalog定义或独立小型合同。

本轮只落实必要判断和字段约定，不增加资源监控、失败后继续其它后端的执行机制、重试、新配置或运行限制。§10的开始前检查只有一次；不是一套健康检查系统。

## 3. 分类顺序和允许排除的范围

1. 先校验asset key不重复、模型存在、模型定义唯一且family/layout与模板相容；重复或冲突记classification_issues，禁止数量抵消。
2. 按日Serving沿原`_is_trade_date_serving`、backend和表白名单；不把无日期的Serving快照混入。
3. TRADE_DATE_PARTITION按实际PARTITION_FILE/STOCK_YEAR_FILE选择原两类查询，不再由名称前缀决定业务含义。
4. 周/月模型仅对当前已明确的股票复权Raw及股票Silver策略执行§5；自然日公告按§7。策略绑定模型枚举和预期family/layout，字段/路径仍读catalog，不能只看到自然周/自然日就假定其他新数据集同语义。
5. 已明确的13项全量快照按对应模型排除，理由为full_snapshot_not_daily_completeness：Raw/Silver stock_basic、silver_stock_lifecycle、Raw/Silver namechange、silver_stock_identity_map、Raw/Silver index_basic、Raw/Silver etf_basic、silver_dc_industry_hierarchy、silver_stock_suspend_confirmed、prod_core_wealth_sector_hierarchy。
6. `raw_tushare_trade_calendar`及`silver_trade_calendar`按管理员确定的范围排除，理由为calendar_excluded_by_scope；不生成独立审计结果或Raw/Silver对账。Silver日历仅作为§4的周月日期依据。
7. lake_root_health对应已知无文件平台模型排除，理由为platform_health_not_daily_completeness。
8. 上述排除只说明本次不审计，不代表废弃、健康或新鲜度通过，不维护另一份catalog/路径/字段；新模型不因family=FULL_FILE或NON_PARTITIONED就自动排除。没有明确策略的模型、未知模板、需要新后端的对象记unclassified_asset_keys及原因，不能报no_physical_location后算分类成功。

五项以各自asset key只出现一次，不能同时在结果和excluded中出现。当前范围应由catalog推导出164/16，但测试还须插入第181项未知模型，证明它报未分类而非自动排除。两项日历只在excluded中列明，不进入审计结果或通过/缺失/未核实计数。

## 4. 日期上下文和周月日期依据

主入口一次获取UTC带时区observed_at，统一转换Asia/Shanghai用于“当天”和源窗口；generated_at可继续用UTC。测试把时钟传入纯逻辑，不新增面向运营的时间覆盖参数。指定日期D与观察日期分开，不能把历史D改成系统当天。

周期坐标复用`run_contracts.stock_period.period_for`。周窗口从D所在周周一至D，月窗口从D所在月1日至D；周六/日仍落本周周五。每个D所需自然日最多31个，两种窗口求并集，多D按实际日期集合去重，不把相隔数月的两个日期扩成中间整段历史。SQL只查SSE与这些日期。

仅为确定周月应有的更新日期，从现有Silver日历读取所需SSE记录，字段为trade_date DATE及is_open BOOLEAN，日期参数使用DATE。同一查询按日期分组，取得记录数和开休市标志，返回不超过所需日期数的结果，不取全日历，不读取Raw日历，不做两层对账。

日期依据必须能够唯一确定窗口内每天的开休市状态。所需记录缺失、重复、NULL、类型不符、文件不可读或读取前后改变时，只把受影响周月的日期判断记为unverified并说明依据不足；不另生成日历叶子结果或缺口统计，不从剩余日期猜测，也不使用Raw日历兜底。现有日历正常可用时，最后一个open日为expected_source_date；整个窗口均休市则not_due。

未来D同样需要可用日期依据；无法确定应更新日时，相关周月为unverified，不设假定等待时刻。日历只作为计算依赖，不能因读取它就声称本次审计了日历。两项日历保持§3中的排除状态；不读取其它交易所、不要求新增SZSE、不对照交易所公告。

## 5. 周/月文件统计SQL和日期判定

用catalog.path_template填入周期坐标。当前Raw周为part-000.parquet，Raw月为data.parquet，Silver两项为part-000.parquet；测试必须覆盖Raw月文件名特例。

每个目标先做普通文件stat，检查路径边界、符号链接、退役根及权限。缺失与0字节分别返回missing_file、empty_file；目录或不支持的类型返回未核实。对可读文件核对本次所需trade_date/end_date/freq均为VARCHAR，`read_parquet(...,hive_partitioning=false)`，避免目录字段覆盖文件字段。

一次聚合只读取trade_date、end_date、freq：

- count(*)及NULL end_date数。
- 严格8位日期校验与`try_strptime(...,'%Y%m%d')::DATE`，并用strftime回转检查；非法非NULL日期单独计数，不能静默变NULL后忽略。NULL end_date按现行合同合法；NULL/非法trade_date不合法。
- trade_date用原source_period等价自然周/月规则核对目标周期，freq核对week/month。月线20200228和20200229只要属于同一自然月均合法，不强制源日期等于自然月末。
- 合法end_date最大值max_source_date；每个本文件对应的不同expected_source_date分别count(FILTER end_date>=阈值)和旧日期计数。周文件阈值至多7个、月文件至多31个，因此多日期也不需要重复扫描同文件。

SQL参数化路径、日期和频率，动态字段/聚合列仅由内部受控规则生成，不拼用户SQL。TRY解析仅为统计非法值，不是源值修复；不改数据、不删行。必要极值只来自这一个精确周期文件，不是年度或全数据集扫描。

SQL日期条件的具体实现要求：先在同一CTE投影`try_strptime(trade_date,'%Y%m%d')::DATE AS bar_date`和对应end_date解析结果；合法非NULL日期须同时满足`regexp_full_match(value,'[0-9]{8}')`、解析非NULL、`strftime(parsed,'%Y%m%d')=value`。周周期匹配`date_trunc('week',bar_date)::DATE`等于目标周一，月周期匹配`date_trunc('month',bar_date)::DATE`等于目标月1日。freq与目标值直接比较；无效判定使用`NOT COALESCE(condition,false)`，避免SQL NULL漏计。max和日期阈值计数只取合法非NULL end_date，各count使用FILTER合入同一SELECT。不能用目录推导的列替代文件里的trade_date或ann_date。

更新观察字段`update_status`取以下值：

| 条件 | update_status | 含义 |
| --- | --- | --- |
| 合法最大end_date达到expected_source_date，且不超过观察日 | date_observed | 当前文件观察到需要日期的数据；不代表所有股票完整或历史当天成功 |
| 有合法end_date但最大值早于expected_source_date | behind | 更新截至日期落后 |
| 缺文件、0字节、可读0行、全部end_date为NULL、日历不可判、schema/读取失败，或观察到超过当前观察日的end_date | unverified | 没有可确认的更新日期；整项是否缺口仍按§6判断，不由此字段代替 |
| 周期截至D无开市日 | not_due | 不要求本期更新；仅stat，不为该期扫描内容 |

freq、trade_date或非NULL end_date格式错误单列invalid_data，不能作为正常更新。部分旧日期或NULL与达到目标日期的合法行并存时，不因部分股票停牌/旧观测误拦；同时输出计数，禁止据一部分新行宣称全股票覆盖。该工具不执行代码全集比较和全部原生检查。

### 5.1 缺失、空及读取失败时的固定输出

下表用于Silver日期依据有效、已确定expected_source_date且本期应更新的情况；无日期依据和not_due仍按§4、§6，不为填字段额外读取文件。不新增状态或其它查询。

| 已确认的情况 | status | row_count | max_source_date | update_status | assessment_status |
| --- | --- | --- | --- | --- | --- |
| 文件不存在 | missing_file | null | null | unverified | 源窗口未结束为pending，已结束为gap |
| 文件0字节 | empty_file | null | null | unverified | 源窗口未结束为pending，已结束为gap |
| schema正确、查询成功且0行 | present_zero_rows | 0 | null | unverified | 源窗口未结束为pending，已结束为gap |
| 缺必要列、列类型不符或读取/查询失败 | unreadable_file | null | null | unverified | unverified，不因窗口未结束改成pending |
| 内容合法、有正行且end_date全部为合法NULL | present | 实际正行数 | null | unverified | unverified，不将合法NULL直接判为缺口 |

表中expected_source_date保留已确定日期，source_window_status按同一日期和固定observed_at计算。missing_file、empty_file及读取/schema失败没有完成统计，rows_at_or_after_expected、rows_before_expected和各NULL/非法计数均为null；可读0行已完成统计，这些计数均为0。内容合法、end_date全NULL且有N行时，两项日期阈值计数均0、null_end_date_count=N、三项非法计数均0。

只有存在合法非NULL旧日期且update_status=behind时才进入update_behind_asset_keys。update_status=unverified仅表示本次没有可确认的更新日期，不能据此把已确认缺文件的gap项放入unverified_asset_keys；最终五组统计只按assessment_status归类。缺列/错类型不抛错中止整轮，也不补列或再查count(*)；保留简短原因，该项未核实，其它正常项继续。文件读取前后变化使该次统计无效，按§8丢弃其统计值、保留未核实，不以旧值或额外读取补填。

## 6. 源窗口与最终单项判定

物理`status`与最终`assessment_status`分开。每个已审计asset只有一个最终assessment：satisfied、gap、pending、not_due、unverified。

按以下优先顺序判定新增周/月：日历无法判定→unverified；有效日历无开市日→not_due，不扫描文件、stat信息仅供说明；其它应更新周期的文件读取/schema失败或运行中改变→unverified；实际读取已经发现的非法非NULL日期、频率或周期记录→gap，不能用源窗口掩盖坏记录；观察到超过观察日的end_date→unverified；可读且已观察到需要日期→satisfied；正行数但全部end_date合法NULL→unverified；其余在expected_source_date对应的20:00源窗口尚未结束时→pending；窗口已过，确认的文件缺失/0字节/0行/日期落后→gap。

文件读取失败不能被“还没到20点”掩盖为正常等待。not_due情况下只保留stat信息，不对已有文件内容做无必要的质量扫描。当前已有部分数据即满足日期观察时，不强制等到20点再认可。

not_due的物理status为not_checked_not_due，不能仅凭stat非0字节填入正行数或present；若同一文件为其他请求日期已有统计，也不把后来产生的数据说成该休市日期更新成功。本次没有需要内容的日期时不执行该文件SQL。

20:00来自已确认源发布说明，集中放审计内部周期策略，不新增CLI/env/DB配置。等待截止时刻严格取`expected_source_date + 20:00 Asia/Shanghai`并与固定observed_at比较，不能取D或系统当天的20点。它只用于解释“源窗口尚未结束”，不能充当Silver超时线。Silver在源窗口后仍落后时，报告实际缺口及“未核对任务完成时间”，不直接断言调度故障。历史D不能借当前时间窗口继续等待；休市D的expected_source_date取周期内前一开市日。例如审计10月31日周六，最后开市日为30日，31日早晨也不能继续以“未到20点”掩盖30日缺口。

## 7. 公告自然日审计

目标路径用catalog模板填D，不扫描整个九日更新窗口、不请求源。文件存在且非0字节后，核对六列VARCHAR的schema，数据只读ann_date；一次SQL返回total_rows及ann_date为NULL、格式不合法、与D的YYYYMMDD不同的计数。URL、rec_time以及其它可空字段不参与缺失判断。

- 可读且行日期均对应D、total_rows>0：status=present，assessment=satisfied。
- 同样schema的可读Parquet且total_rows=0：status=allowed_zero_rows，assessment=satisfied，source_delivery_status=not_checked，并明确只认可物理允许空、不证明源端确实无公告或任务成功。
- 0字节不是合法零行：empty_file。文件不存在是missing_file，过往/当天为gap，未来D为pending；已知错日或非法ann_date是invalid_data，无论是否未来D都为gap。读失败、schema不符、文件变化是unverified。
- 不调用AnnouncementStore、原生checks、verify_announcement_delivery或任何可能建目录、读全源页、补CP的函数；这不是完整质量检查复用。要进一步判断源交付，只在另行要求分析原因时查具体metadata，不能把它变成自动审计的隐含大读取。

## 8. 多日期、文件身份、原范围和只读连接

一次调用建立共享上下文：observed_at、catalog/model、去重日期、文件计划和内存缓存。每个五项目标及必要的Silver日历读前/读后比较dev/inode/size/mtime_ns/ctime_ns；目标变化则该文件涉及且需要内容的全部日期结果未核实，不扩大到本来不要求读取的not_due日期；日历变化按§4使受影响周月的日期依据未核实，不生成日历审计结果。不自动再读、不混用新旧缓存，不声称跨所有文件拥有数据库快照。

年度文件族沿原模板和请求年份，仅执行`count(*)`，按所请求日期过滤并分组，多日期同年合并。不能读取ts_code、trade_time、OHLC做无关摘要。文件族不存在须先有安全枚举的元数据依据；把所有DuckDB IOException都当不存在的旧逻辑必须移除。只有明确没有匹配文件或成功查询为0才报missing_date_rows；损坏、权限、IO和SQL错误一律未核实。沿用28日安全枚举思路但按请求年份泛化，不硬编码2026，不扫描其他年份。

原日表仍查精确文件count(*)；不把全球指数等原按日对象强制套SSE日历。Serving保留既有资源、表白名单、日期过滤参数、只读事务和限额，不增加CH或PG表，不把无日期层级快照强行日表化。PostgreSQL继续使用原按日期count(*)；不能把“保留既有行为”解释为保留ClickHouse不再需要的代码/分类统计。

本机与Prod ClickHouse的`_clickhouse_partition_summary`沿28日已确认的`_clickhouse_count`实现：表名仅由原CLICKHOUSE_TABLE_BY_PARTITION_MODEL映射产生，并限定为share_fact_market_breadth_daily或board_fact_technical_daily；执行`SELECT count() FROM <白名单表> WHERE trade_date = %(trade_date)s LIMIT 1`，日期按原参数绑定。成功只返回status、table、row_count，由原外层补backend；正行present、0行missing_rows，连接/查询错误沿原对应分支报未核实。不得执行uniqExact、countIf、SELECT *或读取ts_code/category做附加审计，不增加schema探测、源对账、索引修改或真实数据库验收。

原客户端readonly=2、max_execution_time=10、max_rows_to_read=1000000、max_result_rows=100及连接/接收超时保持；它们是现有审计设置，不是本轮新增限制。该范围与[agent-query-safety](/Users/congming/.codex/skills/clickhouse-best-practices/rules/agent-query-safety.md)一致，只复用已有按日计数，不扩展查询范围。固定28日适配器不再作为开发后执行依赖，历史测试和报告不重跑或改写。

DuckDB复用`connect_configured_duckdb(DuckDBConnectionSettings(temp_directory=Path('/private/tmp')),temp_policy='existing_no_spill')`，沿28日已审实现，不再改全局duckdb.connect。默认内存16GB/4线程来自现有共享helper；0 spill和禁止扩展自动安装是该既有策略，非新增job限制。仅允许审计SELECT及必要schema读取；不能COPY或写Lake。

共享连接建立失败是工具无法开始审计，按§10报错退出，不生成逐资产未核实结果，不继续Serving，不自动重连。连接正常建立后，单个文件的查询失败或内存不足按该项未核实处理，沿同一正常连接继续原流程；不扩大资源或重试失败查询。

## 9. 报告版本2与计数定义

每个D仍生成一份JSON，保留trade_date（其值仍是所请求日期，并不表示所有对象都是交易日分区）、audit_kind及原三组direct_partition_assets/stock_year_partition_assets/serving_partition_assets。新增period_partition_assets、natural_date_partition_assets。一个asset在五组中只能出现一次；每个结果必须包含原始status及归一化assessment_status，必要时有reason和有界error。周月另有period_key、expected_source_date、max_source_date、各日期计数、update_status、source_window_status；公告包含source_delivery_status。两项日历仅列excluded及范围排除理由，不生成独立结果或日历输出字段。

`report_schema_version=2`、observed_at固定，generated_at为报告完成时间；新增declared_scope说明这是物理、必要日期及覆盖审计，不是全量质量、全市场对象覆盖或历史任务成功证明。旧JSON不重写。年度原可选code_count/min_trade_time/max_trade_time及ClickHouse原附加unique_key_count/invalid_code_count/invalid_category_count不再生成；方案已核对的使用只涉及旧报告或归档测试，不改写这些证据，也不填0/null假装本次统计过。开发后skill和操作手册只说明本次实际输出。

- catalog_asset_count按不同asset key计数，沿用原入口的资产数量口径；重复登记仍记录classification_issues并使分类不完整，不能因去重而判通过。
- audited_asset_count=五组实际选入的asset数，包含读取失败的未核实项，不表示通过数。
- excluded_asset_count=有明确不适用或管理员限定范围排除理由的asset数；unclassified_asset_keys为无策略/冲突对象。分类三组必须互斥，catalog总数=审计数+排除数+未分类数。未知项仍须保留诊断结果，不能漏出总数。
- catalog_classification_complete只在无未分类、无重复/冲突且上述恒等式成立时为true。
- present_asset_count=物理有正行数且目标日期/周期位置可确认的对象数；更新落后但有行可保留在此数中，因此它绝不能单独代表审计通过。
- physical_missing_asset_count为确认文件不存在/0字节、指定日期成功计数为0等物理缺失asset去重数；不包括不可读、未知或可读零行文件。其明细分别沿用missing_file_asset_keys、missing_date_rows_asset_keys、missing_serving_asset_keys。
- present_zero_row_asset_keys与present_zero_row_asset_count单列目标分区文件total_rows=0的可读零行，不将年度/Serving的日期过滤结果0混入此列表；allowed_zero_row_asset_keys与allowed_zero_row_asset_count只含已明确允许空的公告。原按日资产的零行没有本轮获准的具体允许空合同，则assessment=unverified，不擅自报源缺失或通过。
- update_behind_asset_keys与update_behind_asset_count只含已观察到合法旧日期、update_status=behind的项，缺文件/0字节/0行及全NULL不混入；pending_asset_keys、not_due_asset_keys、unverified_asset_keys及分组未核实列表按assessment_status分别给出。错误/不可读不得进入missing列表。
- 最终assessment五组互斥，其数量相加必须等于audited_asset_count。data_gap_asset_keys与data_gap_asset_count来自assessment=gap；audit_evidence_complete要求无未分类/未核实；audit_passed要求分类完整、证据完整、gap=0且pending=0。not_due及公告允许空不阻断本次范围审计。任何“通过”必须带declared_scope，不能说全部180项健康。

有坏日期或已知错误内容可以成为data_gap，但不是physical_missing。物理missing列表与pending等维度可交叉；五个assessment列表自身必须互斥。原有按日/Serving的present归satisfied；不可读/后端不可用归unverified，确认missing归gap，原可读零行归unverified。

stdout每日期摘要必须输出版本、范围、物理缺失、零行、滞后、等待、未核实、分类完整、audit_passed及JSON路径，禁止继续只报有数据总数。skill展示表和本机操作手册第2节也同步这些字段。手册需删除把不可读直接当missing、把排除项一概解释为快照/健康及每日期重新扫描同周期文件的旧说明；历史9月报告与计数只保留为当时证据，不改成新版本结果。

### 9.1 必要字段约定

以下是输出约定，不新增JSON Schema依赖或运行时逐字段校验框架。原三组除§9明确删去的无关统计字段外，其它已有附加字段保持原义。日期从SQL DATE显式转为YYYY-MM-DD字符串；没有取得值时用JSON null，不能用0、空字符串或系统当天代替。计数为非负整数，只有真正完成对应统计后才可填0。

| 字段 | 类型及取值 | 规则 |
| --- | --- | --- |
| status | 字符串 | 按§4—8及既有Serving分支取值；例如present、missing_file、unreadable_file、allowed_zero_rows、invalid_data、not_checked_not_due |
| assessment_status | 字符串 | 仅satisfied、gap、pending、not_due、unverified；每项一个结果 |
| row_count | 整数或null | 目标文件总行数；年度/Serving为所请求日期行数；未完成统计为null |
| reason、error | 可选字符串 | 说明原因；error仅存不含凭据的简短错误，不另建错误分类体系 |
| period_key | 字符串 | 周为YYYY-MM-DD周五，月为YYYY-MM |
| expected_source_date、max_source_date | 日期字符串或null | 前者仅有效日历可推导；后者仅本次聚合取得合法非NULL end_date时有值 |
| rows_at_or_after_expected、rows_before_expected | 整数或null | 按该请求的expected_source_date统计合法非NULL end_date；没有阈值或没有完成统计为null |
| null_end_date_count、invalid_end_date_count、invalid_trade_date_count、invalid_freq_count | 整数或null | 周月本次SQL取得的各类计数；未查询或失败为null |
| update_status | 字符串 | §5的date_observed、behind、unverified、not_due；invalid_data使本项更新判断为unverified，最终assessment仍按§6为gap |
| source_window_status | 字符串 | 有应更新日时，observed_at早于其20:00为pending，否则elapsed；周期无开市日为not_due；日历无法判定为unverified。该字段不覆盖读取错误或非法数据 |
| source_delivery_status | 字符串 | 公告始终为not_checked，无论正行还是合法零行；本工具不核对源交付 |
| declared_scope | 字符串 | 报告根字段，说明“物理数据与必要日期覆盖；不代表全市场对象、全部质量检查或历史任务成功” |

周月字段在周月结果中提供，source_delivery_status在公告结果中提供；不适用其它类型的字段不添加。五个assessment列表分别固定为satisfied_asset_keys、data_gap_asset_keys、pending_asset_keys、not_due_asset_keys、unverified_asset_keys；对应数量分别为satisfied_asset_count、data_gap_asset_count、pending_asset_count、not_due_asset_count、unverified_asset_count。列表均为去重排序的asset key数组，空列表与0计数照常输出。unverified_lake_asset_keys和既有unverified_serving_asset_keys只是未核实列表的分组，不再加入五组数量相加。

下例只演示一个月文件有3行、其中2行截至28日、1行合法NULL，审计29日且源窗口已过；不是正式数据或完整报告：

```json
{
  "status": "present",
  "assessment_status": "gap",
  "row_count": 3,
  "period_key": "2026-10",
  "expected_source_date": "2026-10-29",
  "max_source_date": "2026-10-28",
  "rows_at_or_after_expected": 0,
  "rows_before_expected": 2,
  "null_end_date_count": 1,
  "invalid_end_date_count": 0,
  "invalid_trade_date_count": 0,
  "invalid_freq_count": 0,
  "update_status": "behind",
  "source_window_status": "elapsed"
}
```

合法空公告的关键输出为`{"status":"allowed_zero_rows","assessment_status":"satisfied","row_count":0,"source_delivery_status":"not_checked"}`；可读0行与未读取的row_count=null不同。测试用这类独立字面预期核对JSON输出即可，不生成一整套异常样例库。

周月缺文件且已过应更新日20:00时，关键输出为`{"status":"missing_file","assessment_status":"gap","row_count":null,"max_source_date":null,"update_status":"unverified","source_window_status":"elapsed"}`；该项进入data_gap_asset_keys及missing_file_asset_keys，不进入update_behind_asset_keys或unverified_asset_keys。可读0行在同一窗口下改为status=present_zero_rows、row_count=0，进入零行清单及data_gap，不进入物理缺失或更新滞后清单。只需用§5.1的少量字面预期覆盖这些分支。

## 10. CLI、配置、输出与错误边界

不新增命令参数、env、业务配置或自动重跑开关。已有配置审计如下：

| 项目 | 来源/默认及持久化 | 消费者/生效 |
| --- | --- | --- |
| --date | CLI可重复；无默认；不持久化 | 规划与报告，启动时固定 |
| --repo-root | CLI、既有GOLDENSHARE_REPO_ROOT，默认本仓路径 | 仅加载当前源码catalog/model；不启动服务 |
| --lake-root | 保留CLI；默认以defs.paths.DEFAULT_LAKE_ROOT为准 | 路径规划；去掉旧GOLDENSHARE_LAKE_ROOT默认来源，不能用退役根或旧config兜底。显式其它根只用于已明确的隔离样本/授权只读根 |
| --output-dir | CLI，默认/private/tmp | 仅报告输出，必须在正式Lake、staging和Dagster home之外 |
| 周期审计时间规则 | 内部策略，Asia/Shanghai；源说明20:00窗口末端 | 仅解释当天等待；不是新可调参数或Silver完成期限 |
| DuckDB参数 | §8的既有helper/default，进程内、不持久化 | 仅审计连接，不影响任何job |

日期格式错误用现有argparse错误方式，无查询。未来D保留可观察的物理结果，不设统一覆盖所有类别的pending规则：周月按§6，缺有效日历依据为unverified，能够确定应更新日且尚未到该日源窗口末端才为pending；公告按§7，未来文件尚未生成可pending，读取失败仍unverified，明确错日仍gap。原按日对象的既有日期合同不在本轮重定义。

开始实际审计前，只对所选Lake根做一次普通只读检查：stat确认它存在且为目录，再以scandir打开目录确认可读取，不递归遍历。不存在、不是目录或无法读取就清楚报错并以非0结束，不继续Serving，不生成部分结果。不得为了检查可用性创建目录或调用会写探测文件的ensure_available_for_run/evaluate_lake_root_health；也不新增挂载监控、设备探测或定时检查。显式隔离测试根按同一规则检查。

Lake根检查通过后建立共享DuckDB连接；构造或进入连接上下文失败，同样明确报错、非0结束，不继续其它后端、不为所有资产补写未核实结果、不自动重连。单日入口和多日期主入口共用这一步，一次调用只做一次。连接建立成功后，对单项可处理的IO/查询异常保留未核实，其它查询按原流程继续，不重试失败项。catalog不可加载、报告不可写或内部计数冲突仍为工具失败。

错误信息使用不含敏感连接串、token、认证头的简短说明，不能只截断原始可能带凭据的异常。

保留现有业务成功/失败CLI含义：正常生成报告时，即使其中有gap/pending/单项读取未核实，也退出0；参数错误及上述Lake根/连接初始化等工具失败退出非0。`audit_passed`是数据结论，退出0只表示报告生成成功。分类或单项读取不完整但仍可可靠输出时，报告audit_passed=false及明确原因；不能把工具未能开始审计说成数据已核验。已完成的旧报告保留，不擅自用非0表达“缺数据”。

报告使用微秒时间戳加随机后缀的文件名；完整JSON先写同输出目录的独占临时文件，flush/fsync后用`os.link(temp,final)`原子创建尚不存在的最终路径，再unlink本次temp。FileExistsError只重选报告文件名，不重读数据；不得用exists检查加os.replace覆盖可能并发出现的旧报告。该发布方式限同一报告目录，不是Lake文件写入方案。输出失败只清理本次尚未发布的临时报告，不删除已完成JSON。不得写Lake/staging、创建instance/动态分区或更改sensor。普通SIGINT使连接退出并清理自身临时输出，保留先前已完成报告；不设计自动恢复/新checkpoint系统。

## 11. 性能预算、必要性与中断收尾

本节是后续明确日期审计任务的成本模型，不是开发阶段的正式执行清单。开发、隔离测试和实现对账不读取正式Lake/数据库，不执行164项或原159项全目录审计。优先使用已核验生产者合同、已有证据和临时小样本。后续任务仅要求解释某个缺口时只核该项及必要上游；明确要求指定日期完整目录结果时才对所需目录范围运行一轮，不为本轮新增五项默认重扫原159项。

令N为去重日期数、W/M为其不同自然周/月数、F=2W+2M+N。新增五项对应的不同Parquet最多F份，另有1份必要的Silver日历；例：23/26/27日对应2周、1月、3公告，合计最多10份，不能逐日期重复扫描同一文件。每个周/月文件聚合一次，公告每文件一次，Silver日历仅一次有界查询；Raw日历读取为0。schema/footer读取和stat前后核对计为元数据访问，不冒称零IO。

令B为上述五项文件及必要Silver日历的精确stat字节和，C为只投影三列周月、ann_date公告及Silver日期依据列后的实际读取量。正常新增读取保守按B加必要footer/目录元数据估算，但B不是实测磁盘读量，不能把列投影当作固定压缩比。若实际文件规模不明，运行前先列精确stat，不读取内容测性能。Silver日期依据返回记录上界为所需自然日数，≤31N；周月每条聚合返回一行统计，单文件日期阈值≤31，不返回股票明细。

仅当后续任务确实要求当前完整目录审计时，原159项预算才另列，不藏入F：原直接文件逐路径一次计数，年度族按请求年份/日期计数且同族同年一次查询，ClickHouse/PostgreSQL均按原目标表及请求日期计数；不读额外年份或行情字段。只补查五项时，这部分正式查询为0。已有证据可复用时先确认其日期、字段合同、覆盖问题及观察时间，不能用旧快照冒充当前更新状态。年度/全局仅计数例外不能被扩大为详情或计算，也不意味着无需判断是否有必要进行全目录计数。

正常正式业务写入0、源请求0、额外源下载0、COPY0、spill0、持久化checkpoint0；报告空间按实际JSON输出字节R计。报告写入过程临时及最终文件共存按2R预算，不把它叫行情写入。正常一次统计；中断不自动重跑，若管理员后来明确重新执行同范围，预算只再预留该实际范围的一轮开销，不附带其它资产或日期；进程内缓存不承诺跨进程复用。最终验收只检查报告结构/计数和已经保存的结果，不二次扫描数据。无数值依据时不承诺秒数、GiB或“读取一定下降多少”。

隔离测试数据固定小样本，每个用例少量行，所有临时资源放专属/private/tmp目录，预计总空间≤256MiB；不是正式运行新限额。测试结束核对并删除自己创建的夹具/临时报告，保留必要小型测试结果；不得清理共享依赖或正式记录。本轮开发验收使用临时小文件，未stat正式数据、未测正式盘吞吐。

## 12. 测试与方案对账

| 硬口径 | 必须覆盖的正反场景 | 代码落点 |
| --- | --- | --- |
| P1 分类 | 当前catalog五项都被选入，164/16从事实计算；两项日历仅在排除清单，不进入审计叶子及通过/缺失/未核实计数；插入未知模型/坏模板/重复asset，不能静默排除或抵消 | 规划、normalize |
| P2 周月 | 四项参数化：29日文件有行但最大28→滞后；29日达到→观察通过；旧/NULL部分行不误拦；全NULL→未核实；已读非法日期/频率/周期→gap，缺列/错类型→仅该项未核实且其它项继续；缺文件/0字节/可读0行在源窗口前后按§5.1固定status、null/0及pending/gap，不误列更新滞后；更晚合法数据不能当历史当天成功；Raw月文件名data.parquet | period查询与判定 |
| P2/P4 日期 | 周中、周六/日、跨月/跨年、闰月、20200228与29同月；整周期休市不强求文件；缺日历依据不能猜，未来日历依据不足同样使相关周月未核实；有日历且未来行情未到窗口则等待；未来公告缺文件可等待，读取失败/错日不被等待覆盖；跨年只查所选周期，不读整个历史 | 规划、日期依据、period |
| P3 公告 | 实际六列VARCHAR样本的正行和合法0行、0字节、错ann_date、缺schema、NULL URL/rec_time；0行不调用源/原检查，不伪报交付完成 | announcement |
| P4 周月日期依据 | 现有Silver BOOLEAN/DATE合同及正常开休市例子；缺少可靠日期依据或文件读取中改变→仅受影响周月未核实；Raw日历无任何读取、无两层对账、不生成日历字段或独立结果；无SZSE也正常 | 日期依据、period |
| P5 状态 | 当天19:29/19:30/19:59/20:00，目标未到→窗口内等待/窗口后滞后；周六早晨不能替周五缺口继续等20点；已到日期不强制等待；读失败不伪装等待；不把20点当Silver超时；文件前后版本变化→未核实且0重读 | 时钟与normalize |
| P6 排除 | 当前2日历+13快照+health各有正确理由；日历范围排除与快照不适用日级判断分开；ETF snapshot_id不任取目录；新FULL_FILE模型不自动排除；输出不声称16项健康 | 规划、报告 |
| P7 既有行为 | 原日表/Serving状态、资源、表与日期参数保持；年度仅目标年/date COUNT；本机/Prod两张ClickHouse白名单表仅日期count()，不执行uniqExact/countIf或ts_code/category统计，不返回已删附加字段，不改连接只读与限额；PostgreSQL日期计数保持；无匹配文件与真实0行→缺失，损坏/权限/SQL失败→未核实，零行不混物理缺失；其它年份禁止读 | 原入口、annual、ClickHouse、normalize |
| P8 成本 | 23/26/27文件计划正好10份上界；同月/同周多日期每实际文件一次聚合；Silver日历一次、Raw日历0读取；稀疏日期不拉中间月份；收尾0数据查询 | 共享上下文、SQL记录 |
| P9 隔离 | 禁正式Lake/staging/home、网络、Tushare、job/sensor/check写入；测试只能临时根，不以验收触发正式目录全局审计；模块import只定义不执行；根不存在/不可读或连接建立失败→报错退出、无Serving调用、不补部分结果；根正常且单文件缺失→正常报告缺失；已有连接上的单文件查询失败→仅该项未核实；不写探测文件；失败和取消释放连接、清理自己的临时报告且不删旧JSON | 测试guard、main |
| P10 报告 | 带滞后/等待/未核实即audit_passed=false；公告合法空不增加缺失；五assessment互斥且数量正确；缺文件项虽update_status=unverified，整项gap/pending仍按assessment归组；可读0行不计物理缺失；未知分类为false；日期ISO字符串/null、计数0/null和窗口枚举与§5.1及§9.1字面示例一致；正常CLI输出0不等于通过；初始化/输出失败非0；输出冲突/失败不覆盖历史JSON | normalize、CLI |

测试夹具先按上述生产者合同建立：日期依据使用现有Silver BOOLEAN/DATE、公告全六列VARCHAR、周月必要日期列VARCHAR。不为已排除的Raw日历创建审计夹具。关键日期、计数和分类使用独立字面预期，不用被测period_for/normalize生成expected。真实小Parquet由隔离DuckDB创建，实际运行新增聚合SQL；schema/日期错误样本明确用于反例。Serving网络可替身但必须断言确切资源/表/日期/只读设置，不能声称真实DB验收。

采用现有orchestrator `.venv/bin/python3 -B -m pytest`显式指向skill测试，输出到专属临时目录；不uv sync、不改PYTHONPATH、不安装依赖。不调用正式producer入口绕开其路径保护。测试guard拦正式资源和网络，证明最小“真实合同小文件→实际审计函数→JSON/摘要”通过，名称仅为隔离集成，不冒称正式job端到端。

本轮代码位置、95项测试、旧错误复现、资源边界及未覆盖项已记录到§14和仓库实施报告。这里的隔离验收不证明正式数据完整或真实数据库连接成功；后续正式日期任务仍按§11判断必要范围。

## 13. 方案对账与实施顺序

文档自审须逐项核对：方案五项与本LLD相同、两项日历只排除不出独立结果、Silver日历仅用于周月日期依据、无Raw日历读取/两层对账/日历专属输出、保留既有正确修正、scope动态计数、Silver BOOLEAN合同、公告空与源交付分开、period_for真实来源、窗口与完成时间分开、同文件一次聚合、错误不算缺失、零行不混缺失、未知不排除、无正式副作用、CLI退出语义保持、正常/中断/收尾预算完整。另核对本次精简修正：根与连接初始化失败直接退出、无继续其它后端的降级流程；未来日期依各类具体规则；必要字段及简短例子明确，不增加运行时schema校验框架。

本轮两处修正必须对应到：ClickHouse日期计数→§2、§8、§9、§12 P7；周月缺失/空/schema失败输出→§5.1、§6、§9.1、§12 P2/P10。开发验收不得运行正式全目录审计→本节及§11、§12 P9。原方案、SKILL及仓库归档必须同口径，不能仍写保留原ClickHouse统计、用update_status代替最终分组或缺列时中断整轮。

本轮已按确认顺序完成：提交文档→按白名单开发原脚本与隔离测试→用临时小样本完成验收并清理→按P1—P10独立对账→同步skill已实现状态与操作手册第2节。流程不附带正式数据审计；后续收到明确日期任务时再按§11判断必要范围、复用已有证据并测算一轮成本。收尾不再读取已统计过的数据，不自动重跑失败项或补数。

本次原入口及说明已完成同步，不保留新旧两套常规执行逻辑。正式业务数据、DG状态、job/sensor/check、Prod实现和依赖均未改。隔离验收完成后的新增实现及证据与此前文档提交分开记录，不把未进行的正式数据验收标成通过。

## 14. 实现和隔离验收记录

文档先行提交为`b684397fb`，未推送。本机原`scripts/audit_datasets.py`和新增`scripts/test_audit_datasets.py`已完成实现；源码及逐项对账记录在仓库`lake_console/reports/dg_dataset_audit_scope_20261031/implementation-report.md`，`.py.txt`仅为Git追溯，不作为运行入口。

- 当前源码catalog分类为180项中164项纳入、16项明确排除；只核对源码分类，没有读取正式数据来验证这些项。
- 最终95项隔离测试全部通过，覆盖§12的必要正反例、真实合同小Parquet及CLI报告链；数据库使用替身，网络和正式路径访问被阻止，禁止访问不能被吞掉后伪装为普通未核实结果。
- 旧代码已复现ClickHouse附加统计、不可读误算缺失及零行误算物理缺失；新实现纠正。既有后端选择、表解析、连接参数及Serving编排保持，仅移入获准的日期计数和错误输出修正。
- 首轮5个反例曾因测试夹具使用`vars()`复制slots数据类而未执行，按真实catalog结构修正后通过，预期未改变。实现对账中补齐重复资产计数拒绝及路径越界反例，均属于原P1/P9要求。
- Ruff检查通过；保留原脚本0644及通过Python调用的方式，仅忽略可执行位规则EXE001。4条现有Dagster/Pydantic弃用警告未隐藏，不改依赖。
- 最后一轮清理118个测试夹具/临时报告，共126,454字节；重复草稿也已删除。此前一轮同范围清理另有记录。保留必要测试结果、源码和对账证据，未遗留测试数据树。
- 正式Lake/数据库读写、源请求、DG状态写入及安装均为0；未执行正式日期完整性审计，不据隔离结果宣称任何日期的数据已经齐备。
