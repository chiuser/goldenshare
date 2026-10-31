# Prod周期行情供数LLD：既有周线合同与8月月线修订

更新：2026-10-31。本文维护Prod已实现周线运行合同、新码策略及8月月线独立待办。第11节记录17596故障的已批准设计和本地实施验收；代码和测试已修改，生产数据未写入。DG已改为[直接源bootstrap与每日更新设计](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)，不再把Prod搬运/8月修订作为DG重建前置；前文DG交接描述保留其历史背景，本次不据此宣称DG当前仍消费Prod闭合批。8月月线等原后置事项仍待DG对应工作完成并验收后单独确认，不因本次周线故障修复启动。

## 0. 当前入口与事实源

DatasetDefinition在src/foundation/datasets/definitions/market_equity.py；resolver归一化时间和对象，DatasetExecutionPlan规定units；request_builders.py生成参数，executor/具名周线执行器写业务；Ops/TaskRun只受理意图与观测。foundation不得依赖ops。复用API/CLI，不新增worker lane、通用状态机或未审计配置。

日期模型周为friday、月为month_last_calendar_day，支持point_or_range但不代表每天都有行情。当前月请求builder复用周builder后固定freq=month，新码转换并未因此自动实现；须先审计对象来源、全市场回包和全部消费者，实施时一次迁移，不留旧码兜底。

<a id="source-field-contract"></a>
## 1. 业务字段与存储

复权源21列：ts_code,trade_date,end_date,freq,open,high,low,close,pre_close,open_qfq,high_qfq,low_qfq,close_qfq,open_hfq,high_hfq,low_hfq,close_hfq,vol,amount,change,pct_chg。Prod日期DATE；价格/change/qfq/hfq Numeric(18,4)、vol/amount Numeric(20,4)、pct_chg Numeric(10,4)。Raw键(ts_code,trade_date,freq)，Raw→Serving同键upsert，不做全表删除。DG导出日期为YYYYMMDD业务文本、Decimal字符串/NULL；api_name/fetched_at/raw_payload和内部时间不进入Parquet。

trade_date是业务周期，end_date是源计算截至日期，历史周/月也可能更新到当前，不能当该K线内部最后交易日、采集时间或用请求截止覆盖。pre_close/pct_chg沿源除权参考口径，保留源单位。doc365实测与完整字段见[DG共享源合同](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#source-field-contract)，Prod具体字段仍由本节及当前Definition约束，DG新设计不自动修改Prod。

周线使用raw_tushare.stk_period_bar_adj和core_serving.stk_period_bar_adj的freq=week；月线复用同表freq=month，未复权月线为raw_tushare.stk_period_bar/core_serving.stk_period_bar的freq=month。不能仅凭write_path名raw_core_upsert虚构core行情表或跨频写入。

## 2. 周线规划、源验证与写入

首次历史按周全市场unit，后续point_week加变化股票stock_history区间；每个交易日与前一交易日比较因子取变化并集，缺上市前因子不算除权。未完成原plan优先，unit参数及预算冻结，恢复不能用当前意图重推。

有新代码时对象历史请求只用新码。全市场回包按确认身份选择有效新码，旧码不自动兜底或混作同一新码；已有Raw旧行原始身份保留。安徽凤凰832000.BJ/920000.BJ当前返回不同基准已由MCP确认，不能以旧接口非空当最新数据。对象池、builder、归一化/Writer、DG消费者及测试要同步迁移。

源字段/页尾/唯一键/周期/覆盖/基准必须完整。源价对本地价的差异仅诊断，不能因显示精度不同阻断或覆盖源价；目标因子没覆盖、缺核验依据的日常修正仍保持未完成。历史bootstrap保留源值但明确未经价格基准验证，不把保存等同核验。

## 3. 可恢复性、可观测性与事务

执行unit为新周或单股历史区间，不持覆盖全历史长事务。单unit完整捕获后，一个短事务upsert Raw/Serving并append交接unit，三者同提交；Ops/node/issue/progress独立观测，失败不得回滚或污染业务。

每页/unit前后取消，源调用可由父进程终止；取消不领新unit。已提交unit由业务交接键恢复，不看TaskRun.unit_done猜完成，不重复请求。可见阶段/对象/完成量/总量/更新时间≤30秒，心跳不充业务进度，ETA不可靠即不可估算。成功/失败/取消时TaskRun及活动节点一致终态；状态写失败保留业务事实并明确观测异常。

## 4. 配置与性能基线

| 配置/来源 | 现有值、消费者及生效 |
| --- | --- |
| 具名weekly policy/Definition | 冻结到plan；resolver/planner/executor/linter消费，新意图用新版本，恢复校验原版本 |
| 分页/规模 | page6000、unit12000行/3页；计划≤1000unit/1MiB，执行器事前/实际门禁 |
| HTTP | 每页一次真实请求，adapter重试0、禁redirect，总期限20秒、连接/读取各5秒、响应8MiB；监督器和诊断使用实际值 |
| 事务/并发 | 周线发布者PG advisory session锁、多个短事务；锁只属week adjusted，不锁month；进程退出释放 |
| 内存 | 源子进程256MiB目标；整棵进程树另列，不能用单进程或DuckDB buffer替代RSS |
| 交接 | unit payload8MiB、日常整批256MiB、closure头投影4KiB；达到上限拒绝不自动拆新状态机 |
| 控制/观测 | 固定安全details≤8KiB，进度/取消/状态与业务提交分离 |

源参数/字段/policy冻结一次，不逐unit拷贝整个Definition；Python不积累完整全市场多年结果。内存优化已收口，不以本轮文档再发一轮无目标专项。月线正常page6000按单月成本测量，不能套周线1,000unit批次制造额外请求。

<a id="delivery-contract"></a>
## 5. core.stock_weekly_adj_delivery/v1

该表已经实现并正式使用，保存不可变业务交接值而非第二套TaskRun状态。不能用可变Raw、fetched_at、截断观测或DG永久证明替代它。

| 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| revision | BIGINT identity PK | 同一发布者串行提交的读取顺序；允许rollback形成空号，不以连续号证明完整 |
| contract_version | SMALLINT，固定1 | 未知版本DG拒绝 |
| batch_id / unit_id | UUID / VARCHAR(128)，UNIQUE(batch_id,record_kind,unit_id) | 恢复和重复发布幂等键；不是TaskRun主键 |
| record_kind | VARCHAR(24)枚举plan/unit/batch_closed/bootstrap_closed | 冻结计划、实际unit、闭合交付批次；append事件，不维护queued/running等TaskRun状态 |
| intent / unit_kind | JSONB / VARCHAR(24) | mode、原trigger_source、bootstrap布尔值和intent_digest；point_week/stock_history等具名unit |
| cutoff_week / start_date / end_date / ts_code | DATE/DATE/DATE/VARCHAR(16)可按kind为空 | 源周期截止/历史窗口/原始股票代码 |
| factor_scan_start / factor_scan_end / factor_target | DATE/DATE/NUMERIC(20,8)可空 | 扫描覆盖窗与股票因子目标；不能靠全局 MAX(date)证明覆盖 |
| outcome | VARCHAR(32) | published/source_empty_preserved/partial_source_preserved/no_trading_week；网络/权限失败不能写成preserved成功 |
| payload | JSONB | plan的有界unit清单，或日常unit的21列标准化行情；bootstrap unit只摘要，不存全历史副本 |
| rows_received / rows_unique / rows_written / rows_preserved | BIGINT，非负 | 明確区分源、去重、写入、保留；rows_written是每层业务键数，不把Raw+Serving相加 |
| basis_date / payload_digest / scope_digest | DATE可空 / VARCHAR(64) / VARCHAR(64) | 本unit基准及本次传输完整性；不是永久历史hash门禁 |
| reason_summary | JSONB，有界 | 原因/计数/≤20展示样本、单元预算内的完整preserved_keys及基准样本；不含token/SQL凭证 |
| published_at | TIMESTAMPTZ | 业务提交记录时间，不用它代替revision水位 |

固定dataset/freq=week由合同及CHECK约束表达；索引(record_kind,revision)、(batch_id,record_kind,unit_id)。plan共享合同/预算只存一次；unitID/参数由builder冻结，不夹带完整Definition或全部行情。日常payload为标准化21列，日期文本、Decimal字符串、NULL、固定排序canonical摘要；bootstrap unit只存范围/完成摘要，不复制全历史进交接表。

提交算法：冻结plan→单发布者锁→按(batch,unit)查询已提交→捕获/校验→Raw/Serving/unit同事务提交→独立观测→全部单位有业务终结结果且读回通过后append batch_closed。失败/取消/源未就绪不闭合，原批恢复。partial_source_preserved须明确缺键与有效基准，当前全市场缺码不能冒充正常闭合。

闭合头记录实际最大输入周max_input_week，空行批为null；cutoff_week仍为任务上界。DG以实际最大周作anchor，历史修正不能凭当天日期造分区。合法空闭合批验证后仅消费水位，不造行情/物化/通过检查。revision可因rollback有空号，不用连续号判断完整。

DG只读下一闭合头和该批unit，按规定psql包装显式投影；不可写ack表/扩任意schema。交接payload是可重放增量，不是废弃搬运证明，不随DG未复权目录删除。清理交接记录须另定水位/保留窗及授权，停机超保留窗受控bootstrap。

<a id="weekly-bootstrap-closeout-execution"></a>
<a id="weekly-bootstrap-formal-20261012"></a>
<a id="weekly-bootstrap-closeout-20261013"></a>
## 6. 已完成B0及保留恢复能力

首批历史plan逐unit摘要并一次对账持久化，bootstrap_reconciled后闭合；独立补刷plan关联首批，完成剩余新周/基准差异及对账后append bootstrap_closed。0-unit补刷仍保存plan/closure/B0，未完成补刷不能由新意图跳过。DG在固定B0下捕获完整Raw，检测全部业务revision漂移，按键覆盖、保留DG独有键，一次文件/事件/水位收尾，不永久读旧reports。

2026-10-13首批15565完成876周/3,028,907行，补刷15604完成9股/6,345行，B0=1785；DG859文件、859新物化/2,577准确检查及水位已迁移。已完成的全量刷新、源故障恢复及旧发布命令不再作为当前执行卡。当前共享sensor水位1785是10月15日只读快照，不预先保证未来没有在途批。

<a id="bounded-tushare-source-diagnostics"></a>
## 7. 已实现的共享源异常诊断合同

BoundedTushareError的安全details随code/message传递，周线与公告包装、父子IPC及持久化消费者同步使用，不保留旧包解析双轨。rows/rate_limit/api_error及业务错误code/retryable规则不因诊断而改变。

| 字段 | 事实来源与含义 |
| --- | --- |
| exception_type、cause_types | 实际异常类名及有限的cause/context类名链；requests可能将ReadTimeout包装成ConnectionError，保留链便于区分 |
| failure_stage | 当前代码实际进入的阶段：request、response_body、decode、validate；父进程只能记录ipc_wait或ipc_receive，不能声称知道被终止子进程的最后HTTP阶段 |
| http_status | 已收到响应时的HTTP状态；未收到响应为null |
| elapsed_ms | 单次调用当前可测耗时，使用monotonic；不是整个任务耗时 |
| connect_timeout_seconds、read_timeout_seconds、total_timeout_seconds | 本次真实生效的期限，不读取另一个普通客户端的默认值 |
| worker_exit_code | 无结果时如已观察到子进程自然退出，记录退出码；未知为null，不把父进程清理产生的终止信号当成原故障或OOM证明 |
| api_name、dataset_key、request_params | 源包装层补充接口/数据集和业务参数；参数仅trade_date、ann_date、start_date、end_date、ts_code、freq、limit、offset |
| page_number、offset、attempt_number | 本次真实页、偏移和从1开始的实际尝试次数；周线为1，公告按原重试序列累计 |

诊断在进入IPC或日志前投影到白名单，只传短字符串、数值、null和有限列表/字典。类名/参数字符串最多96字符，cause_types最多4项且防循环，整个details最多8KiB；这是固定安全边界，不新增运营配置。超限裁剪诊断但保留错误码，不影响业务异常处理。禁止序列化异常对象、原始str(exc)、HTTP响应正文、请求完整payload、token、认证头、凭证URL或traceback局部变量。

EOF/OSError按父进程真实IPC阶段记录；不能把清理信号当原故障或OOM证据。诊断沿原IngestionSourceError/StructuredError→TaskRun issue.technical_payload.details→详情API→前端JSON，保持现有字段，不新增表/API。日志失败不能替换原业务错误或阻塞提交；不得为定位错误额外请求源。

公告仍为首次+最多3重试、0.5/1/2秒退避、总期限25秒，不能把周线无重试合同回灌公告。具体消费者仍在原实现，不属于DG重复数据集删除面。

<a id="weekly-factor-precision-policy-20261012"></a>
<a id="factor-repair-manual-tasks-20261012"></a>
<a id="factor-repair-execution-20261012"></a>
## 8. 因子精度纠偏与独立专项边界

保留真实采集精度，当前源少小数位不自动证明旧值错误；源周线21字段照收，本地价格对比仅诊断。不能由三位舍入解释的25股/2,489因子键曾在Prod完成有限维护，原451日精度变化不扩大为DG修复。DG自主日线/分钟QFQ及指标是另一专项，R1/R2开发通过、R3已暂停，不以周线B0完成代替其正式修复。

## 9. 本轮8月月线修订与数据删除边界

按[Prod方案](stock-weekly-adj-refresh-plan-v1.md#3-8月月线独立待办)仅处理两个Prod月线数据集的20260831/month源返回键，Raw及现行Serving同事务upsert；其余month/week键不变、未返回旧键保留/单列。不删除Prod两数据集，不修改表结构或扩大source参数，不沿用周线交接表作为月线新通道。

Prod正式更新前确认单月源分页、13/21字段、新码请求、精确范围及实际差异；沿现有维护入口，有界原unit恢复和TaskRun状态。DG不再开发单独8月修补链，而由新直接源bootstrap接收历史；Prod其他月份若需维护另列实际范围，不能把DG重建当Prod完成证据，也不要求DG等待本项。

DG已完成三个重复数据集根及活动入口清退；新直接源bootstrap前删除两个旧复权Raw根，按DG总方案的独立范围和阶段执行。Prod因子、全部行情表、交接表、Web进度页和Ops调度均不在DG删除清单。执行命令、数据库写入和部署另行审批，不因文档更新触发。

## 10. 测试与当前未验事项

保留P1/P2合同、日期规划、Decimal、完整分页/源末端、业务unit同事务、唯一发布者、冻结恢复、空批/历史anchor、原批取消重放、观测失败、TaskRun/节点终态及安全诊断正反例。新码对象/全市场响应、新月8月覆盖与范围外不变新增专项反例。静态/文档检查不证明真实业务通过，旧结果不冒充新代码验收。

<a id="p0-d0-review"></a>
<a id="p1-implementation"></a>
<a id="p2-implementation"></a>
<a id="weekly-basis-correction"></a>
<a id="weekly-memory-optimization"></a>
<a id="weekly-memory-closeout"></a>
<a id="weekly-prod-run15378"></a>
<a id="weekly-delivery-anchor-correction"></a>
历史索引：P0/D0来源/容量评审、P1协议/迁移、P2执行及真实小样本、日期误判修正、内存typed-JSON优化、15378进程观察和实际输入anchor修正均已发生；不再保留互相覆盖的“待部署/原批运行中”正文。精确提交/失败日志保留在Git历史，必要运行合同已合入本文，未完成的真实新批/Silver/8月修订仍按当前主方案独立验收。

## 2026-10-24 周线执行计划故障修复

管理员要求修复本次来源不一致，且明确只纠正周线执行计划、不影响其他数据集。Ops任务来源scheduled在交给foundation周线计划时转换为schedule；TaskRun、查询、前端、新闻任务和公共调度保持现行行为。创建冻结、preflight及worker共用转换；foundation业务合同、事务、续跑和预算不变。不执行上文8月修订、DG搬运或22/23历史行情补数。方案/LLD、性能、测试、发布边界和实际状态见[周线修复方案与LLD](/Users/congming/github/goldenshare/docs/ops/ops-scheduler-failure-recovery-plan-and-low-level-design-v1.md)。

<a id="last-trading-day-factor-17596"></a>
## 11. 2026-10-31 最后实际交易日因子与17596恢复

**状态：2026-10-31管理员已确认本设计并授权严格按LLD本地开发，本地实现及回归已通过，实际结果见11.9；生产未迁移、未正式执行。** 开发范围、硬约束及正反向验收逐项以11.2—11.7为准，完成后在本节补实际结果。授权不包含生产发布、迁移、调度变更或17596正式恢复。对应[原方案第5节](stock-weekly-adj-refresh-plan-v1.md#last-trading-day-factor-17596)，不另建平行方案。

### 11.1 目标、依据和当前代码审计

目标是让规划与执行对同一股票使用同一日期规则，并在保留原冻结记录及已提交数据的前提下恢复17596。源接口参数、21列行情合同、日期输入模型、股票身份、新码专项、月线及DG写入均不在本步修改范围。

本对话在2026-10-31完成的有界证据：生产17596/节点26914及issue288；交付批次ed03de09-2d4d-4864-be8a-2399484022f9的14条记录头；本股10月下旬日线/因子；本批42个股票目标的最后日线/因子比较。Tushare MCP的daily、adj_factor、stk_week_month_adj默认和显式字段请求分别返回3、6、2行，stock_basic显式返回元道退、D、20261028；suspend_d返回空不能用来推断停牌。本股最后日线20261027，因子1.0079；周线20261023/20261030的end_date均为20261027。退市后28—30日因子为1.1319，Prod与当前源样本一致。源请求均为单股和限定日期，没有全市场历史明细读取。

源合同依据：[daily，doc_id27](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0027_A股日线行情.md)、[adj_factor，doc_id28](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0028_复权因子.md)、[周/月复权，doc_id365](</Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md>)。源trade_date/end_date是YYYYMMDD文本，Prod已归一化的日级字段是DATE；内部计划和审核JSON用YYYY-MM-DD、因子用8位小数字符串，不把本地目标日期传作源end_date或覆盖源输出end_date。MCP未提供limit/offset，本步样本没有触及6000行上限，不把这些小样本说成重新验证了完整分页。

| 已审计实现 | 当前行为及本次影响 |
| --- | --- |
| stock_weekly_adj_planning.load_changed_codes / resolve_weekly_adj_units | 周内变化并集后直接取days[-1]因子；新计划在这里改为按股票最后实际日线取因子 |
| stock_weekly_adj_delivery._load_basis_inputs / validate_weekly_adj_source_basis | 已按原截止日以内最后日线找目标日期，再比较冻结因子和源基准因子；复用同一取值方法，不取消这两个比较 |
| stock_weekly_adj_bootstrap.bootstrap_factor_scope / plan_bootstrap_catchup / publish_bootstrap_boundary | 已按股票最后实际日线取目标；携带依据日期时同步其返回值和消费者，不重跑bootstrap、不改变其范围 |
| restore_units的3个调用方 | resolve_weekly_adj_units、unit_planner._build_stock_weekly_adj_units、run_weekly_adj；三处必须共同读取原计划及获准更正，不能只改resolver后被planner再次恢复旧值 |
| stock_weekly_adj_scope.freeze_weekly_adj_execution / restore_scheduled_request | 校验原意图、scope、policy和contract摘要；原execution_context保持原样，不把更正塞入意图或改contract_digest骗过校验 |
| StockWeeklyAdjDeliveryDAO / model / 000185迁移 | 当前只有4种record_kind；DAO追加同键异值拒绝，PG触发器禁止UPDATE/DELETE，因此当前没有合法修改原plan的入口 |
| TaskRunCommandService._freeze_weekly_payload / retry_task_run / dispatcher | 重新提交创建新TaskRun，带原execution_context交给resolver；继续复用，不把原失败任务改成功 |
| Ops task_runs API、query/schema及两个任务前端页面 | retry路由、现有进度展示继续使用；页面不计算因子，不新增日期/因子输入或更正API |
| latest_frontier / oldest_unclosed_plan / publish_closed_batch、bootstrap读取及DAO next_closed_header / iter_units | 更正不得当作行情unit或闭合水位，所有读取按kind过滤；原43个unit_ids及闭合摘要规则保留 |

CodeGraph已使用explore、impact(load_changed_codes)、callers(restore_units)、node(retry_task_run)，再以代码核对动态注册的unit builder、API和前端调用。影响从foundation规划到执行/交付、Ops受理和观测，foundation不得读取ops模型。对当前orchestrator源码的表名/模型引用审计未找到Prod交付表的活动读取方；不据旧文档要求修改DG，也不宣称完成DG消费验收。正式开发前若出现新的消费者或跨工程交接，须复核并回到本节补齐，不能扩大范围默默实施。

### 11.2 因子取值的具体规则

1. 本批截止日C保持原计划值。对每个股票code，从core_serving.equity_daily_bar按`ts_code=code AND source='tushare' AND trade_date<=C`倒序取1行，日期记为D；从core.equity_adj_factor精确读取(code,D)。D必须存在，因子必须非NULL且大于0；否则weekly_adj.factor_coverage_missing。不能取市场统一最后开市日、退市日、最新因子日期，不能从D之后回填一个值。
2. 在拟新增的周线专用stock_weekly_adj_basis.py内共用这段查询，模块只依赖基础模型，不反向导入planning/execution。按最多128只股票一块做索引查询和精确因子键投影，返回日期和Decimal，不读取每股全历史明细；保留原SQL/行数/单元预算。新计划在stock_history单元progress中同时保存factor_target及factor_target_date，后者为取值依据，不进入源参数、业务主键或运营配置。
3. 执行仍重新读取原C以内的D和因子，与已冻结或经批准更正的目标值比较，再比较源end_date对应因子与该目标值；缺依据或数值不一致仍停止。日期较早但因子相同可以通过；源价格与本地公式的小额显示精度差异继续仅作诊断。不因新增日期记录就把“日期变化但因子相同”错误拦住。
4. 原计划只存因子而未存依据日期的单元，不自动改写：同样按上述唯一规则取实际日期并比较冻结值，在新提交交付单元的reason_summary记下实际所取日期。所有计划使用同一算法，不保留旧的“按市场周末取目标”分支；新增日期只补可解释性，不能成为绕过旧冻结值检查的兜底。
5. 保留逐日因子变化并集及停牌变化候选。只有目标值的日期选择改动；本轮不把“最后实际交易日之后变化”另改成自动删除历史刷新单元的规则。17596即使重新计算候选，也不能删原第14个单元或把43改成42。
6. 本例D=2026-10-27、目标=1.00790000。日线缺失若其实是本地漏同步，不能据此认定股票没有交易；正式恢复前复用并刷新单股MCP证据。有源端更晚日线、当天因子修订或源周线基准不同，均按新事实停止重审，不把本例推广为所有缺行情都可通过。

### 11.3 原计划不变，追加更正记录

**为什么不能只修load_changed_codes：** 有原plan时resolve_weekly_adj_units直接restore_units，根本不走新规划；执行器还要求持久化plan与payload及摘要完全相同。普通重试/新maintain不能合法更正；直接UPDATE/DELETE又违反不可变合同及PG触发器。也不能伪造一个空unit来跳过本股，它会污染完成数和交付结果。

拟扩展现有core.stock_weekly_adj_delivery，增加内部记录类型`plan_correction`，不新建状态表。它表示批准过的更正事实，不保存queued/running/重试次数。现有plan/unit/闭合记录内容、contract_version=1、policy_snapshot、contract_digest和scope_hash保持原值；行情交付合同仍为21列。更正有独立的payload格式correction_version=1，未知格式拒绝。

| 项目 | 拟定约束 |
| --- | --- |
| 唯一键 | 同一batch_id，record_kind=plan_correction，unit_id=plan_correction；本设计每批最多1条，追加不同内容拒绝，不按“最新记录覆盖” |
| 记录头 | contract_version=1；原intent/scope_digest/cutoff_week，rows_received/unique/written/preserved均为0；outcome=published只表示更正已发布，不表示行情已完成 |
| 原计划绑定 | payload保存原plan revision、payload_digest、scope_digest、contract_digest和原43个unit_ids摘要；全部比对通过才可使用 |
| 更正范围 | changes仅允许原计划中未提交的stock_history单元，完整列出unit_id、ts_code、old_factor_target、new_factor_target、factor_target_date及依据；本次只1项，不允许任意JSON路径补丁 |
| 已提交保护 | 保存审核时已提交单元的revision/unit_id/payload_digest/rows_written及整个清单摘要；本例13项、12,682行；APPLY前比较，不能用TaskRun进度代替业务记录 |
| 审计依据 | source_task_run_id=17596只作来源说明；批准引用、批准清单摘要、取值查询边界、必要源样本摘要；foundation不依赖或更新TaskRun |
| 大小及摘要 | 清单/更正payload各不超过现有max_plan_bytes=1MiB，canonical digest覆盖完整内容；不放历史行情全集、凭证或任意SQL |
| 实际提交单元 | 更正后的第14个unit仍用原ID；factor_target=1.00790000，reason_summary保存所用更正revision/摘要及实际目标日期；它的实际源行情仍按原合同写Raw/Serving |

模型和DAO新增对该kind的严格校验；SQL的kind枚举同步扩展，另加只对plan_correction限制1MiB的CHECK，原payload大小CHECK及UPDATE/DELETE拒绝触发器保留。新大小检查用CASE仅在该kind时计算payload字节数，避免验证迁移时解码所有旧行情载荷。迁移不重建行情表、不修改旧记录、不改任何业务因子。2026-10-31按迁移文件中的revision/down_revision静态计算，当前唯一head为20261010_000186；**创建迁移前再次核对真实head**。生产现存CHECK名称受命名约定截断，不能照原迁移源码猜名字：先按目标表和pg_get_constraintdef定位并要求唯一匹配，再更换指定kind CHECK。锁预算2秒、SQL20秒；新CHECK先NOT VALID并验证，旧kind CHECK移除与替换保持事务原子性，失败回滚DDL。正式迁移另行批准。

更正写入与行情恢复是两件事。更正使用同一publisher_lock；先检查同键记录，完全一致则返回“更正已存在”且无写入，内容不同则拒绝。首次写入还必须确认原批未闭合、更改单元没有unit结果、13个已提交记录及所有白名单前提仍一致；一次短事务追加1行并读回。事务中断没有半条更正，提交后中断则从该持久化记录恢复；不得删除更正或改回原计划。

后续恢复读取时，审核清单中的原13个单元必须仍作为不变的子集存在；允许其余原计划单元正常新增交付记录，不能再要求总记录数永远等于13。第14个单元完成后，其交付目标和更正引用必须相符，不能因它现在已有结果而拒绝后续续跑。更正本身不是可撤销的临时开关；本轮只设计同批一次更正，未来其他故障类型不自动适用。

### 11.4 同一套恢复读取及拟改文件

业务原plan及其execution_context始终保持原样；执行单元由“原plan + 已验证的更正记录”得出。更正不是第二套计划来源：只允许上述字段替换，完整单位清单、请求、顺序及边界仍来自原plan。没有更正时完整验证原计划，有更正时先验证其原计划绑定，再应用白名单变化；两条路径最终使用同一因子查询和写入逻辑。

| 拟改位置 | 明确改动 |
| --- | --- |
| src/foundation/ingestion/stock_weekly_adj_basis.py（拟新增）、stock_weekly_adj_planning.py、stock_weekly_adj_delivery.py | basis模块集中按股最后实际日线取因子；规划使用返回日期/值；校验复用，不重写源价 |
| src/foundation/ingestion/stock_weekly_adj_bootstrap.py | 已有最后日线算法核对一致；若返回结构增加依据日期，同步两个解包位置及摘要测试；不改变bootstrap范围或执行已闭合历史 |
| src/foundation/ingestion/stock_weekly_adj_plan_correction.py（拟新增） | 仅本数据集的清单构建、校验、追加及恢复读取；接收基础参数及已按原payload恢复的units，不import ops或顶层import planning；读取只依赖DAO/basis，APPLY函数调用时局部导入既有publisher_lock/事务控制，避免execution与本模块的顶层循环import |
| planning.restore_units及resolver旧批分支、unit_planner._build_stock_weekly_adj_units、execution.run_weekly_adj | 三处通过同一个有界读取方法取得单元；进入publisher_lock后再次读取并核对更正revision/摘要，不能把锁外旧计划单元直接用于执行，也不能只跳过tuple相等检查 |
| src/foundation/models/core/stock_weekly_adj_delivery.py、dao/stock_weekly_adj_delivery_dao.py、拟新增Alembic迁移 | 新kind、严格内容/大小校验、幂等追加；闭合头和unit读取显式排除更正记录 |
| src/foundation/datasets/stock_weekly_adj_contracts.py | 更正清单及记录的纯格式校验放在已有合同模块，供DAO和恢复模块共用；DAO不导入恢复编排或承担业务计划更正 |
| delivery.publish_unit / publish_closed_batch | 单元记更正依据；闭合前要求43个原unit齐全，目标因子与已批准更正一致，更正记录本身不进入unit_ids、行数、bytes或units_digest |
| src/cli.py、src/cli_parts/ingestion_handlers.py | 增加weekly-adj-plan-correction运营命令；CLI可以定点读17596核对来源，再调用foundation；既有maintain-dataset和TaskRun API行为不改 |
| docs/templates/dataset-development-template.md | 开发时同步“冻结目标更正必须有不可变批准记录、保留已提交单元及现有长任务门禁”，本轮不修改模板或代码 |
| tests/test_stock_weekly_adj_basis.py、p1_contracts.py、p2.py、p3_bootstrap.py、pg.py及tests/web/test_ops_scheduler_failure_recovery.py | 按11.7实施；新更正模块/CLI专项测试可单列，不复制通用调度规则 |

Ops/API/前端是必须回归的消费者，本设计不要求修改它们。若回归证明必须改，先回本节写明具体原因和影响再开发。DatasetDefinition、DatasetExecutionPlan的公开类型及日期模型不变；manual actions、catalog、workflow、freshness、cards、snapshot、日期审计和时间控件不新增输入，不能把内部依据日期暴露为运营可选参数。现有错误码basis_not_updated、factor_coverage_missing、delivery_contract_mismatch、scope_mismatch、writer_busy和row_budget_exceeded继续各自表达失败；如确需新增错误码，必须同改codebook，不先造未注册错误。

所有读取必须覆盖更正：包括创建时resolver、unit builder、worker重建、锁内执行器检查、实际unit生成及闭合检查。更正后的单元progress同时携带更正revision/摘要，使三处单元比较也覆盖所用更正的身份。TaskRun保存的计划快照用于观测；worker按最新持久化更正重建并保存快照后执行，若重建后到拿发布锁之间更正又变化，则拒绝这次执行并要求重新提交，不在锁内偷偷替换待执行单元。业务原plan及execution_context始终不改。更正头读取按(batch,kind,unit_id)索引，追加1行不触发其他数据集状态重建。

### 11.5 17596的审核清单与正式步骤

审核清单必须绑定以下本次只读事实，正式执行前重新读取；不能把本节当成永不变的运行凭证：

| 项目 | 本次已核实值 |
| --- | --- |
| TaskRun / node / 状态 | 17596 / 26914 / failed |
| batch_id / cutoff_week | ed03de09-2d4d-4864-be8a-2399484022f9 / 2026-10-30 |
| 原plan revision / digest | 2053 / af569f7751a11f4b1117625cb30e2a541f592e576c656b7f1766ffed5c8e3a50 |
| scope_digest | 00c731f75e5033928a4e7b8fc621d4b5c61a216e402507917f8423ff82af09f6 |
| contract_digest | c3953fe68d87e79139f32b0ddf0a287c782431c0e1eee1c993b76de86943116f |
| 原单元 / 已提交 | 43 / 13，业务revision2054—2066，合计12,682行 |
| 唯一更正unit_id | 5ad7b281686980471ccc627a780d392fb13fceb4becdda189ec882d3638cd6db |
| 股票 / 原请求 | 301139.SZ / freq=week，start_date=20220708，end_date=20261030 |
| 原因子 → 新因子 / 依据日期 | 1.13190000 → 1.00790000 / 2026-10-27 |
| 待执行 / 闭合 | 剩余30个单元，包含第14个；本批尚无batch_closed |

恢复分为以下门禁，**本轮均未执行**：

1. 设计确认后开发、隔离测试，再独立确认发布SHA、CHECK迁移和正式恢复授权。发布遵守现有流程，不借默认部署脚本自动安装、seed或重启未批准服务。
2. 正式窗口内先经授权用现有Ops流程暂停schedule14，记录原状态；定点查同数据集queued/running任务并用既有取消流程等待停止。不能只暂停schedule却放任已入队任务抢跑，也不停止整个共享worker。确认部署的所有周线执行进程都认识更正记录，未确认前禁止APPLY。
3. 新CLI默认只读模式：指定task_run_id=17596及本地output路径，生成完整43个单位身份、13个交付头清单、42个目标日期/值比较、唯一差异和批准所需摘要。数据库READ ONLY、statement_timeout<=30秒；源只查301139.SZ两周及所需日线/因子小窗口。周线样本复用现有request builder和受控source_client，日线/因子仍以现有接入合同和本对话MCP证据核验，不新建下载组件；审核清单记明实际请求、取得时间及完整返回摘要。审核总期限30秒，每次查询/受控源请求同时受剩余期限限制，超时终止并且不生成可执行清单。缺证据、更多差异或已闭合时同样停止。
4. 运营审核生成的清单。APPLY必须显式提供approved-plan路径、其expected-digest及approval-ref；必要源样本复核在拿发布锁之前完成，不能在业务事务内等待网络。在publisher_lock内重新比对原plan、scope、contract、已提交头、目标日线/因子；只有同一批准内容仍成立才追加更正。不得根据运行当天自动重算并偷偷替换清单；本例APPLY只允许上述1项，无Raw/Serving写入、无自动重试。
5. 追加更正提交并读回后，单独调用既有`POST /api/v1/ops/task-runs/17596/retry`，记录返回的新TaskRun/节点ID。该调用是未来正式写入，本轮不调用。现有retry本身不设置resume_from_task_run_id字段，直接沿携带原execution_context的路径恢复；不得为了文档好看声称它已经保存不存在的来源字段。来源关联同时保存在批准清单和更正记录。
6. 新任务必须使用原batch_id及原43个unit_ids，恢复已提交计数13/43和12,682行，跳过这13个单元的下载/写入，从第14个开始实际执行剩余30个；第14个必须下载完整历史、核对源/归一化/写入/拒绝/读回，拒绝数为0。其余29个继续原计划的因子、源参数和校验。
7. 全部业务单元完成后才追加batch_closed，闭合仍是原批和2026-10-30；更正不算第44个单元。新TaskRun和活动节点一致success，17596和26914保留failed；原plan及13个旧unit的revision/摘要/计数逐项不变。本股第14个实际factor_target为1.00790000，Raw/Serving按本次完整源值读回；原第1个单元的新周线不重复写入。最终验证不得凭全表updated_at计数代替上述业务证据。
8. 记录取消/退出/再次续跑结果及实际性能；确认恢复完毕后，经授权恢复schedule14的原状态。失败时保留已提交更正和unit，不追加假closure、不直接改任务状态；暂停状态及剩余欠账明确交付，恢复调度由管理员决定。

批准清单提交前后若发现其他单元已提交：首次APPLY停止并重新审核；完全相同更正已经存在时按幂等返回，不因后续正常进度增加而再写第二条更正。更正后若因子或源基准出现新的不同值，不能再次修改旧更正；本设计只支持一次批准更正，停止并另审实际事实。

### 11.6 读写、性能和可恢复性预算

本步不新增env、Settings、数据库配置或页面常量。沿原WeeklyAdjExecutionPolicy：128股一块只是现有批量查询方式，不是可调配置；page6000、单元12000行/3页、单元payload8MiB、计划1MiB、整批256MiB、源20秒、业务SQL20秒、锁2秒、进度5秒及取消2秒预算不提高。新CLI的30秒只读审核期限和45分钟恢复窗口是本次执行预算，不是修改源或事务超时配置。

| 阶段 | 数据范围、开销和中断处理 |
| --- | --- |
| 新计划 | 延用本周含前一开市日的因子变化扫描；仅对变化股票查各自最后日线及同日因子，按128股分块，候选受原max_units/max_rows约束；不新增全市场历史明细扫描，不逐股加载历史列表 |
| 17596审核 | 1个plan、43个单位定义、13个已提交记录头及42对目标查询；载荷<=1MiB，目标30秒内，分块前后检查取消。只在完整校验通过后以临时文件加os.replace生成审核JSON，取消不留下可APPLY的半成品 |
| 更正APPLY | 1条追加及读回；publisher_lock，SQL20秒、锁2秒；不持有覆盖30个行情单元的事务。中断以是否存在完全相同的更正记录判断，不看CLI退出码猜是否提交 |
| 行情续跑 | 恢复13个已提交单元计数时逐unit读取和校验载荷，合计已知12,682行/约5.1MiB，随后仅请求剩余30个单元；每单元最多3页×20秒源等待+20秒业务事务，最坏40分钟；正常预期5—10分钟需实测，超预算查原因而非增配额或放松检查 |
| 中断后继续 | 再次读取同一plan、更正和已经提交的unit，内存仅保留当前unit及小摘要；只计算剩余n个单元的n×80秒预算。每页/单元前后取消，不领新单元；当前事务未提交即回滚，已提交不回滚 |
| 最后验收 | 预留5分钟，逐unit有界读回43个交付摘要、原13项不变、必要业务键及第14个完整接入范围；读取源/归一化行数、零拒绝及Raw/Serving一致性。closure遵守原事务预算，超时保留43个结果并续跑闭合，不放大事务或重下全部行情 |

源进程目标内存沿256MiB，父进程保持单unit和<=1MiB更正证据；不得同时保留30个完整结果。共用publisher_lock序列化周线发布及更正，不新增worker/lane；Ops状态会话继续独立，观测失败不回滚更正或行情。更正记录本身不递增业务进度；恢复任务沿现有页面显示阶段、当前股/范围、13/43起始完成量、百分比和更新时间，运行中5秒更新、不得连续30秒不可见，ETA仍不可估算。正式执行前验证现有环境及测试资源，缺依赖不安装；上述预算包括恢复和最后验收，均是待测门禁而非已测性能结论。

### 11.7 开发前确定的需求、代码与验收清单（实际结果见11.9）

关键夹具使用11.1的真实生产者字段和本例字面值：原截止2026-10-30、最后日线27日、27日1.0079、28—30日1.1319、周线end_date=27日；expected不得由待测取值函数生成。隔离数据库可以缩小单元数量验证机制，但13/43和12,682的真实验收必须另行定点读回，不以缩小夹具冒充生产恢复。

| 要求 | 拟实现位置 | 正向及反向测试 / 真实验收 |
| --- | --- | --- |
| 最后实际日线取因子 | planning共用查询、delivery验证；basis/p2测试 | 本例修复前冻结1.1319并失败，修复后取1.0079通过；正常周末有日线仍取当日；C之后有更晚日线/因子不得使用；不同股票不能取全市场MAX日期 |
| 缺依据必须拒绝 | 同上；basis测试 | 旧基准日期但同因子允许；缺日线、缺同日因子、NULL、0/负数拒绝，不能改取后一日；日期后补但因子相同不误拦 |
| 停牌变化检查保留 | load_changed_codes；p2现有停牌测试 | 保留停牌期间变化候选并取最后实际日线同日因子；原停牌夹具须显式补该日因子作为新取值所需输入，预期依据管理员新口径；另测故意缺该因子确实拒绝，不删除测试回避失败 |
| 源基准检查不放松 | validate_weekly_adj_source_basis；basis测试 | end_date=27且同因子通过；源基准对应不同因子、混用计算截至日、缺关键字段拒绝；价格显示精度差异仍仅诊断 |
| 原计划不可变、更正严格绑定 | model/DAO/新模块；p1及PG | 正确单批单项追加成功；plan/unit UPDATE或DELETE仍被PG拒绝；错批、错摘要、错旧值、改范围/ID、修改已提交unit、已闭合或超1MiB均拒绝；SQL约束用真实PG验证，不能只mock DAO |
| APPLY和更正读取一致 | 新CLI/模块及restore_units三个消费者 | 默认只读不产生DB写入；正确清单只加1行；相同清单重放无新增，不同内容拒绝；清单后正常进度增长不影响“已存在同一更正”的幂等返回；首次写入前进度或目标变化必须重审 |
| 排队竞争不能错用旧值 | resolver/unit builder/run_weekly_adj；p2/PG/web | 创建预览后追加更正，worker重建及锁内复核必须使用同一值；另一个发布者先提交待更改单元或更正时拒绝不一致；原plan/policy/scope验证不被绕过 |
| 原批完整恢复 | 执行、publish_unit/closed；p2/PG/web | 读取receipt跳过已提交下载/写入，剩余单元继续；更正不进入43个业务单位或闭合摘要。漏任一原unit不得闭合；正常43个完成允许，不因追加记录误拦 |
| 取消/退出/观测隔离 | 原事务及TaskRun链；PG/web | 更正事务提交前/后退出、行情中途取消、unit提交后退出、幂等续跑、进度单调；状态写失败不回滚业务；TaskRun/节点终态一致，原失败历史保留 |
| 性能及范围不扩张 | 查询/CLI/执行；p2/memory/PG及真实读回 | SQL证据证明索引定点查询和128块上限；不全量加载日线历史，不重新请求前13单位；审核、迁移锁、取消、恢复和最后验收均计时；月线及其他数据集路径回归 |

沿用现有tests/test_stock_weekly_adj_*.py、tests/web/test_ops_scheduler_failure_recovery.py及必要CLI测试；实现阶段先确认隔离PG实际可用，禁止把Prod连接传入测试。含真实PG约束的测试若跳过，该项就是未验，不能据“其余全绿”发布。因新增迁移和恢复单元合同，实施时同步模板、文档、迁移头及相关消费者；保留现有架构依赖和dataset codebook门禁。

开发后先完成一次隔离数据库的真实运行—取消—续跑—读回，再申请生产发布及17596恢复。正式本股历史请求必须核对源行数、去重、归一化、写入、拒绝原因与目标读回；任何reject解释到reason code和样本。源本身变化导致新错误时保留未完成结论，不将本次设计认定为允许忽略后续失败。

### 11.8 设计阶段交付和后续授权边界

设计阶段只更新原方案和本LLD，复用真实源小样本并补取生产原plan/13个unit摘要及真实约束，没有执行生产写入。管理员随后已确认并授权本地开发；开发结果见11.9，不能继续用设计阶段的“尚未修改代码”描述当前本地状态。

已获管理员确认的具体实现是：共用最后实际交易日取值方法；新增严格有界的plan_correction追加记录及其CHECK迁移；三个单元恢复消费者同步；默认只读的运营更正CLI；17596保留13个已提交单元、按原43个单位恢复剩余30个。确认设计不等于批准生产发布、迁移、schedule14变更或行情写入，这些须在开发验收后按具体执行清单单独授权。

<a id="implementation-17596"></a>
### 11.9 2026-10-31 本地实现及验证记录

**本地开发完成，生产发布、迁移和恢复未执行。** 全部代码位于当前dev-interface工作区，没有创建分支或worktree，没有提交、推送、安装依赖或改动其他工程。实际实现对应11.4清单：

- 新增stock_weekly_adj_basis.py；规划、源校验共用实际日线日期查询，128股分块，精确读取同日因子。新日常及bootstrap历史单元记录factor_target_date；保留逐日变化候选，不使用退市后因子替代。
- 新增stock_weekly_adj_plan_correction.py及合同纯校验；三处restore_units消费者使用同一持久化更正，发布锁内再次核验单元及更正身份。原计划、请求、单位ID和顺序不改；原已提交记录作为必须不变的子集，允许后续正常新增结果。
- 模型/DAO支持严格的plan_correction头、payload、单批单项更正及幂等追加；迁移20261031_000187接真实head 20261010_000186，按实际CHECK表达式发现旧约束。新增大小检查只计算更正载荷，保留原UPDATE/DELETE拒绝触发器。迁移只在任务独占的隔离PG执行，Prod仍为原约束。
- CLI入口weekly-adj-plan-correction默认数据库READ ONLY，30秒审核期限内生成审核JSON并原子落文件；APPLY要求明确批准文件/摘要/引用，复核源样本在发布锁之前，锁内不等待网络。新命令不创建TaskRun，不续跑行情。已暂停排程及无排队/在途任务是CLI首次正式追加前的检查条件。
- publish_unit记录实际目标日期及更正revision/摘要，publish_closed_batch核对实际目标与引用，更正不进入业务单位数及闭合摘要。本次更正已证明历史非空，执行时突然返回空历史会停止重审，不能用空结果制造第14个单元完成。
- 新增tests/test_stock_weekly_adj_plan_correction.py、tests/test_stock_weekly_adj_correction_pg.py；仅更新p2既有测试的新增返回日期及最后实际交易日必需因子夹具。模板已同步，未修改DatasetDefinition、Ops/API或前端实现，也未新增配置、worker或队列。

**测试及独立依据：** 先以真实故障同形小样本证明旧实现因1.1319对1.0079失败，再修复实现。关键预期来自本例/MCP及独立字面值，没有调用待测取值函数生成expected。测试先修正了临时PG初始化的字符集；使用本机既有PostgreSQL 18.4、UTF-8、任务独占/private/tmp目录及Unix socket，没有安装或升级套件。测试保留自有临时库供读回，不使用生产连接。

集中执行以下范围，共**402项通过，26.25秒，无skip**：test_stock_weekly_adj_p1_contracts/p2/basis/p3_bootstrap/memory/pg/plan_correction/correction_pg；web/test_ops_scheduler_failure_recovery；test_dataset_definition_registry、test_dataset_action_resolver；architecture下subsystem_dependency_matrix、platform_legacy_guardrails、operations_legacy_guardrails、dataset_runtime_registry_guardrails、dataset_codebook_guardrails。原有Starlette测试客户端有1条弃用提示，本次未安装替代包。完整输出保存于本机/private/tmp/weekly17596-validation.log。

其中隔离真实PG验证新CHECK迁移、禁止UPDATE/DELETE、超1MiB更正拒绝、默认审核事务拒绝写SQL、更正追加、原批运行—取消—续跑—Raw/Serving读回；既有PG回归覆盖进程退出、发布锁、业务回滚、观测失败及TaskRun/节点终态。专项还覆盖重复APPLY、正常新增单元后重放、旧排队单元拒绝、resolver与注册unit builder一致、退出后只补闭合而不重下已提交单元、缺同日因子、C以后日期不取、0/负因子拒绝、源空返回拒绝、首次APPLY前新增交付拒绝及257股恰按3个128块/6条SQL读取。外部源在这些隔离测试中被替代，不能据此宣称生产行情写入成功。

**真实只读核验：** 使用实际新CLI入口、.env.web.local及强制READ ONLY事务，对17596限定原批和两个周线点样本完成审核；没有APPLY。实际源请求复用既有builder/source_client，返回完整21列并经过capture、归一化和基准校验。审核结果为：原plan=2053，43个单位，13个已提交单位、12,682行，42个因子目标中仅301139.SZ不一致；更正建议1.13190000→1.00790000，日期2026-10-27，两个真实周线样本通过，审核在30秒期限内完成。

生成的本机审核文件为/private/tmp/weekly17596-prod-readonly-audit.json，canonical digest为0010008d32cf70bfd3e33d131d0570f83cfe0ac8e3ef6ec5e9daf8a328e7ceb2。它只是本次只读证据，**未获准APPLY，正式恢复前必须按11.5刷新审核并取得准确执行授权**；不得把文件存在当成执行批准或让运行时依赖临时报告。

Ruff、实际goldenshare ingestion-lint-definitions及新命令help入口均通过；CodeGraph已按仓库根同步并核验影响面，依赖矩阵门禁通过。生产仍未部署新代码、未执行187迁移、未追加plan_correction、未暂停/恢复schedule14，也未对17596调用retry；17596的failed历史和原批欠账仍保留。后续唯一正式步骤是11.5中的受限发布、真实约束迁移、重新审核、更正追加及原批30个单元恢复，不因本地通过扩大到其他数据集。
