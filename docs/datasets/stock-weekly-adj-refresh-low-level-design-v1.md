# Prod股票复权周线、月线功能对齐DG详细设计 v1

2026-11-17状态：阶段2、3已分别提交`45dc21c96`、`d7559ab1a`；阶段4正式组件隔离串联、旧入口清退及独立复核已完成，详细证据及实际边界见原LLD13.28—13.30。源21字段、Raw较新保护、Serving整行选择及已定业务口径不变。阶段4已提交`86abea0c1`；阶段5已完成189/190生产迁移、2020年2月3588组重复月线重发布、d555f5965后端及运营前端发布和6/14排程切换，15暂停；服务、健康接口、排程及Quote样本读回已通过，详见原13.32。今晚20:00自然日更、实际变化历史及生产取消/恢复仍待真实任务验收，不能据此标记阶段5全部完成。管理员已定的0行按0、信任平台价格、20:00—次日00:00探针、不扩大人工范围、无全市场初始化/2010截断等口径不变；PostgreSQL16/18差异仍按决定忽略。首轮测试错误读取根配置并请求真实源的经过及纠正如实记于LLD13.30.1，不用该轮结果作为验收证据。

更新：2026-11-14。本文维护Prod已实现周线运行合同、新码策略及8月月线独立待办。第11节记录17596故障的已批准设计、本地实施验收及生产恢复；新任务17836已成功完成原批43项，实际结果见11.10。DG已改为[直接源bootstrap与每日更新设计](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)，不再把Prod搬运/8月修订作为DG重建前置；前文DG交接描述保留其历史背景，本次不据此宣称DG当前仍消费Prod闭合批。8月月线等原后置事项仍待DG对应工作完成并验收后单独确认，不因本次周线故障修复启动。第12节记录19540失败时的已知事实、管理员反馈重新提交成功，以及11月20日的只读观察安排。

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

### 2026-11-09 Prod 8 月复权月线执行细节

- 按本次授权在生产任务中心选「股票月线行情（复权）」单日 `2026-08-31`，不填个股。现有 Definition、请求构建和 `raw_core_upsert` 负责唯一单元。只更新 `raw_tushare.stk_period_bar_adj`、`core_serving.stk_period_bar_adj` 中该日 `month` 的源返回键，保留未返回键，不操作未复权月线、其他月份、周线或调度。
- 已按 `stk_week_month_adj`、`freq=month`、`trade_date=20260831` 显式读取 21 列。现有 6,000 行页大小下首尾同一页，共 5,551 个唯一代码，前复权 OHLC 和 `end_date` 齐全。生产 Raw 与 Serving 业务键各 5,551，均与源键集合一致，无同类在途任务。以平安银行、贵州茅台为写入回读样本。
- 按现有单月短事务提交两层，任务状态单独观测。本次源读取容量按实测 1 页、5,551 行计算，10 月同类生产单元曾用时 8.599 和 10.244 秒，仅作耗时参考。若失败或中断，先核任务终态和同日两层键及样本；确认本单元未提交、源与范围仍一致后，最多按原入口重提一次同范围。含重提预计最多 2 页、11,102 条返回行，以及一次故障定位和一次最终对账。目标漂移、范围或源契约不符时停止重提。
- 验收任务与节点终态、1 个单元及拒绝数，读回两层行数、业务键和样本，核对源新计算截至日、前复权 OHLC、收盘价和量额。按 9 月及 10 月已有关联计数核对范围外。使用既有单点、月份日期校验及同事务写入合同。

实际执行中，生产任务 18875 和节点 28532 均成功。任务用时 10.346 秒，完成一个单元，读取并写入 5,551 行，拒绝 0 行。源、Raw 和 Serving 的业务键一致，Raw 与 Serving 的 21 个业务字段逐行一致。该月 `end_date` 最早为 2026-09-03，最晚为 2026-11-06，没有早于 2026-08-31 的计算截至日。平安银行 `close_qfq` 从 11.6500 更新为 11.4700，贵州茅台从 1297.4000 更新为 1299.5200，均与本次源样本一致。回读相邻 9 月和 10 月的 Serving 分别为 5,571 和 5,577 行，与执行前计数一致。

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

**状态：2026-10-31本地实现及回归通过；2026-11-01管理员另行明确批准五步生产恢复，现已通过17836完成原批43/43项并恢复schedule14。** 本地结果见11.9，生产结果见11.10。开发范围、硬约束及正反向验收逐项以11.2—11.7为准；本次生产授权仅针对17596原批，不扩至其他批次或数据集。对应[原方案第5节](stock-weekly-adj-refresh-plan-v1.md#last-trading-day-factor-17596)，不另建平行方案。

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

恢复分为以下门禁；2026-10-31设计及开发阶段均未执行，2026-11-01获得独立生产授权后的实际结果见11.10：

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

<a id="production-recovery-17596"></a>
### 11.10 2026-11-01生产恢复及有界验收记录

**17596原批恢复完成。** 管理员在本对话明确确认按五步执行生产恢复，已自行暂停自动计划；授权包括原批更正、重试、读回验收及验收后恢复schedule14。部署由管理员完成，本次未发布代码、安装依赖或执行迁移。只读核验生产SHA为5084ef9397292f41fdcbd39315bddb463345ba1a，包含eba9cc844；生产规划、执行、更正三个文件与本地SHA256一致，实际worker于北京时间23:18:23启动，早于17833；alembic_version为20261031_000187，CHECK允许plan_correction。17833失败时该批更正为0条，仍用1.1319，说明部署后直接重试未完成原批恢复步骤。

**前置检查及更正：** schedule14=paused，同数据集queued/running/canceling任务0个。刷新读取原plan、43个原单位、13个交付头、42个因子目标及两个源周点样本，除source_evidence.observed_at外与批准清单一致。正式APPLY仍使用管理员审核的/private/tmp/weekly17596-recovery-audit-20261101.json，摘要d9482a141b0f5180f4e66bcd3cbdeeb9bd82be07c4e9e2bcee3d661c7054ef65；正式窗口新审核副本摘要eb437adc44c85d80a69f1856493db47716e5e45371a2027d07e5055f7f8e955f，仅取得时间变化。现有CLI在锁前复查源、锁内复查计划与已提交记录后追加2067；只更正301139.SZ第14项到1.00790000、依据日2026-10-27，更正本身写入行情0行。原批batch_id、原请求和execution_context未变。

**实际执行：** 通过已登录生产运营页面的17596“重新提交”调用现有retry入口，生成TaskRun17836、节点27154。任务北京时间2026-11-01 23:42:01.471595开始，23:43:48.445173结束，约107秒；前13项读取既有交付恢复计数，后30项生成2068—2097，共新增12,778行，整批25,460行。301139.SZ交付2068记录217/217/217行（源取得/去重后/写入）、保留0行、目标1.00790000、实际目标日期2026-10-27，并引用更正2067及其摘要。43项均published，取得、去重后与写入计数一致，preserved=0；TaskRun拒绝0行且无新增issue。此次无主动取消或进程退出，不能把此次生产结果表述为已实施取消演练；本步实际证明的是原已失败批次保留13项后继续30项。

**最后验收：** 按READ ONLY事务、SQL20秒期限，读取本批46条记录头（原plan1、更正1、unit43、闭合1）以及301139.SZ限定2022-07-08—2026-10-30的217行21字段源交付、Raw和Serving，不读取其他股票行情明细。独立逐项核对39项条件：原plan2053摘要不变；原13个交付的revision/unit_id/payload_digest/rows_written不变；原43个单位集合和顺序不变；scope及contract不变；闭合units_digest与43个交付摘要重新计算一致；301139.SZ全部217行21字段三方一致且源end_date均20261027。新任务及活动节点均success，43/43，TaskRun/节点/闭合行数均25,460；17596、17833仍为failed历史。batch_closed2098对应原批及2026-10-30，更正未计成第44个业务单位。

**恢复自动计划：** 通过既有自动任务页面，确认选择“每周更新股票复权周线”、from_schedule_id=14后恢复。页面提示已恢复，数据库再读回schedule14=active、next_run_at=2026-11-02 21:04北京时间；管理员同时暂停的普通周线schedule13保持paused，没有恢复其他计划。

本机证据：/private/tmp/weekly17596-apply-20261101.log（更正2067）；/private/tmp/weekly17596-final-readback-20261101.txt（有界DB事实）；/private/tmp/weekly17596-recovery-verified-20261101.json（39项对账通过）；/private/tmp/weekly17596-schedule-restored-20261101.txt（最后调度与任务状态）。这些是本次操作证据，不是运行时依赖。开发回归仍以11.9为准，本次无代码变更或测试重跑；8月月线及DG事项未执行，也未修改因子、日线、股票基础信息或任务失败历史。

<a id="weekly-adj-observation-19540"></a>
## 12. 2026-11-13任务19540的基准差异与11月20日观察

### 12.1 失败时的已知事实

以下来自11月13日晚的Prod有界只读查询、当前代码及Tushare MCP单股样本。生产两份基准检查文件与本地SHA256一致，生产当时的Git提交为`63cfdf8453d0d8bc1d080c42d39fd71d5c75097d`。这是一次故障记录，不改变第11节已完成的17596恢复结论，也不据此修改现行合同。

| 项目 | 已核实结果 |
| --- | --- |
| 原任务／节点 | 19540／32152，均为failed |
| 数据集／原排程 | 股票周线行情（复权），`stk_period_bar_adj_week`／schedule14 |
| 原批 | `87b3e429-6bb2-498d-be65-871c51f3ed0e`，冻结计划revision=2141 |
| 请求目标日 | 2026-11-13，21:04:00创建任务 |
| 执行时间 | 21:11:04开始，21:11:11失败，上海时间 |
| 失败位置 | 第1个`point_week`全市场单元，请求`freq=week, trade_date=20261113` |
| 错误 | 603444.SH，`weekly_adj.basis_not_updated`，消息为“源基准因子与本次目标因子不同，复权价格尚未覆盖本次变化” |
| 本批进度 | 共42项：1个本周全市场单元、41个股票历史刷新；完成0项、保存0行 |
| 当次业务提交 | 只有plan，无unit或batch_closed；2026-11-13的Raw、Serving周线计数均为0 |
| 上一完整批 | revision=2140，截止2026-11-06 |
| 603444.SH的日线与目标 | 11月13日实际有日线，收盘329.22；当日复权因子1.44220000于21:02已在Prod，后续MCP查询与本地一致 |
| 该股历史刷新冻结目标 | 1.44220000，依据日期2026-11-13；失败发生在前面的全市场单元，尚未执行该历史刷新 |
| 前一交易日复权因子 | 2026-11-12为1.41680000 |
| 失败回包的end_date及价格 | 未留存，具体日期和值未知 |

错误的实际判定见[源基准检查](/Users/congming/github/goldenshare/src/foundation/ingestion/stock_weekly_adj_delivery.py)：读取源行`end_date`，精确查询该股此日期的复权因子，再与本批截止日以内最后实际交易日的因子比较；不同即停止。计算并比较`close_qfq`的步骤在此检查之后，因此这条错误不能证明源价格算错。此前把它直接解释为“源周线未更新”过于确定，现以本节证据边界为准；源端具体更新顺序仍未证实。

### 12.2 后续源样本和管理员反馈

11月13日晚后续通过Tushare MCP只查603444.SH，周线范围为2026-11-06至2026-11-13，并另作`trade_date=20261113`的完整21字段点查询；日线、复权因子范围为11月2日至13日。返回的日线及复权因子与Prod对应小窗口一致，两个周线样本如下。

| 周线所属日期trade_date | 源计算截至日期end_date | 未复权收盘close | 前复权收盘close_qfq |
| --- | --- | --- | --- |
| 2026-11-06 | 2026-11-13 | 349.31 | 343.16 |
| 2026-11-13 | 2026-11-13 | 329.22 | 329.22 |

`end_date`是复权价格的计算截至日期。上周周线也可以标注11月13日，不能把它解释为这根周K内部的最后交易日。按独立字面值核算，上周收盘`349.31×1.4168÷1.4422`按两位小数四舍五入为343.16，与后续源样本一致；这只证明后续单股样本符合该基准，不还原21:11的全市场回包，也不说明源具体何时完成更新。

11月14日管理员反馈，重新提交后已成功完成。恢复结果的依据为管理员反馈；本次文档记录没有重新查询新TaskRun编号、对应节点或原批闭合记录，不将原失败任务19540改记为success。此后继续观察，暂不改调度时间、复权因子取值、检查条件或源价格；不因这次现象启动计划更正或其他生产写入。

### 12.3 2026-11-20只读观察安排

下周五为2026-11-20，已在本对话安排当晚21:30上海时间做一次只读观察。该时刻是本次观察安排，不是修改Prod自动任务的运行时间，也不是任务完成时限。观察使用现有Prod只读连接和Tushare MCP；先读取根AGENTS及Prod只读审计规则，不安装依赖或修改运行环境。

1. 按schedule14、当日及目标周2026-11-20定位最新股票复权周线任务，只读状态、当前节点、失败诊断、实际执行时间和原批交付头。只读取有关股票的冻结目标，不输出整份计划或其他股票历史。
2. 针对603444.SH，按11月13日至20日的小窗口读取日线日期、收盘价、前收盘及复权因子，确认截至目标日的最后实际交易日。周线仅核对13日、20日两个周期，必要源请求取得完整21业务字段，逐项记录取得时间、`trade_date`、`end_date`、复权价格及对应日期因子。
3. 分开记录“任务失败时已有的回包／诊断”和“观察时重新取得的样本”。失败诊断若仍没有原始`end_date`和价格，明确保留证据缺失，不能用后来样本代填，也不直接认定价格算错或推定具体更新延迟。
4. 仅汇报这一次观察结果。若任务仍在运行，记录当时状态；不自动重试、创建新批次、修改配置或因子、重写行情，也不增加原始失败回包保存功能。后续若需要开发或正式处理，再按具体问题确认范围。

本次只修改两份原文档，复用11月13日只读审计和管理员反馈，没有再次查询生产、执行重试或写入业务数据；已有文档改动保留，未修改8月月线、DG及其他事项。

<a id="daily-monthly-adjustment-refresh"></a>
<a id="prod-stock-period-dg-alignment-lld"></a>
## 13. Prod股票复权周线、月线对齐DG：详细设计

**2026-11-16状态：已按管理员已定口径校准本次设计，最后两处执行说明已补齐，本轮文档复核完成，未进入开发。** 管理员要求Prod功能对齐DG。本节取代此前“只补每日月线历史回刷、当前周范围待确认”的讨论稿，业务范围以[方案第7节](stock-weekly-adj-refresh-plan-v1.md#prod-stock-period-dg-alignment)为准。DG参照版本为2026-11-12切换后的总方案10.19、共享LLD13和月线LLD11；第0—12节记录既有Prod实现与历史执行，不能按旧合同直接启动本次新流程。

### 13.1 本轮依据和当前差距

本节同时依据当前Prod代码、DG现行实现、doc365及必要真实样本。现有Prod自动周线用最近已结束周，周内逐日比较复权因子后把新周和变化股票历史放入同一冻结批；月线为通用月份维护。新流程必须改变执行规则，不能仅修改cron。

| 已核代码 | 当前事实及拟改职责 |
| --- | --- |
| `src/foundation/datasets/definitions/market_equity.py`、`datasets/models.py`、`definitions/_builder.py` | 周/月日期轴与21字段事实在此；当前week绑定具名weekly policy，month为generic。新增统一执行合同须在Definition登记，不能给month挂week专用policy |
| `ingestion/resolver.py`、`validator.py`、`unit_planner.py`、`execution_scope.py` | 当前point仍校验周五/月末，周线拒绝未结束周。新增每日业务日意图的归一化由resolver负责，不能在Ops或builder提前决定日期范围 |
| `ingestion/request_builders.py`、`source_client.py`、`clients/bounded_tushare_call.py` | 当前月builder复用周builder；新合同区分当期周期单点、单股无日期历史及三列预检；正式请求固定完整21字段 |
| `ingestion/stock_weekly_adj_planning.py`、`execution.py`、`delivery.py`、`bootstrap.py` | 现有原批优先、周线发布锁和原始键Raw/Serving读回均限week；新历史不能继续挡当期，也不能把Serving周期选择塞入旧1:1读回合同 |
| `models/raw/raw_stk_period_bar_adj.py`、`models/core_serving/stk_period_bar_adj.py`、`dao/stk_period_bar_adj_dao.py`、`dao/base_dao.py`、`ingestion/writer.py` | 两层当前主键均为股票+源日期+频率，普通upsert无end_date条件。Raw须保护同键较新行；Serving按股票/周期重新选择整行并在一个短事务内完成 |
| `serving/publish_service.py`、`serving/builders/stk_period_bar_adj_*_serving_builder.py` | 已有发布入口也按原始三字段组键。即便日常writer改好，人工重发布仍可能恢复重复月线，必须同次迁移全部发布者 |
| `ops/services/schedule_automation_capability_resolver.py`、`schedule_probe_binding_service.py`、`operations_probe_runtime_service.py` | 已有远端预检及schedule→probe→TaskRun设施，优先扩展本数据集具名条件，不新增调度服务 |
| `ops/services/task_run_service.py`、`ops/runtime/task_run_dispatcher.py`、`worker.py`、`app/runtime/ops_worker_factory.py` | 接收意图、装配和观测；新增当期、历史依赖基于已提交业务事实，不把TaskRun进度当唯一完成依据 |
| `biz/api/quote.py`、`biz/queries/quote_query_service.py` | `/quote/detail/kline`→`build_kline`→`_load_kline_points`→`_load_stock_period_points`逐条读取Serving，随后计算指标；历史分页还读取`_load_older_trade_date`，需共同回归 |

已使用CodeGraph `codegraph_explore`、`codegraph_callers(_load_stock_period_points)`、`codegraph_impact(StkPeriodBarAdj)`；符号影响图未完整列出动态注册与SQL/字符串消费者，已用当前源码引用补查DAOFactory、Serving注册、Ops目录与观测、CLI和Quote API。没有仅凭图结果宣称消费者审计完成。前端目录未找到该表或旧Quote URL的直接引用，本次只确认后端读取链，不宣称某个当前页面已经画出重复柱。

### 13.2 功能合同与工程边界

- 对齐DG当期日更、源齐备检查、两频历史回刷、新股处理、较新源记录保护、Raw与服务层分工、闭合周期补齐和人工准确维护。
- Prod保留PostgreSQL短事务、每个已完成业务unit可读回、幂等续跑、状态与业务分离。DG现在失败后整批从头重跑，不要求Prod放弃已经具备的逐单元恢复。
- 当前股票周/月两个dataset key及完整源21列保留。只写`raw_tushare.stk_period_bar_adj`与`core_serving.stk_period_bar_adj`中明确获准的freq/股票/周期，以及经评审的本功能业务完成记录。不改未复权周/月、日线、复权因子或股票基础信息。
- 只使用Prod自己的数据及合同副本；不import DG执行器，不读DG Lake/instance作为上线前提。DG的Parquet文件和事件逻辑不复制进Prod数据库链。
- 原周线不可变业务记录保存历史，不修改plan、已提交unit或plan_correction。新执行需要共同覆盖两频，不能写入旧week专用合同；切换时原批必须先完成或显式交接，不保留新旧双轨执行和旧规则兜底。
- 不以对齐DG为由缩短Prod更早历史；Serving不发布上市前周期按本节独立规则设计；不执行退市清理。正式删除、历史重建和全局读取仍须批准准确范围及必要恢复措施。

### 13.3 三类日期与数据集消费者

| 对象 | 定义与处理 |
| --- | --- |
| 目标业务日D | 本次要求至少覆盖到哪个交易日；调度/人工只表达此意图，resolver归一化并记录到执行计划。它不是要求重现当日计算快照 |
| 周/月坐标P | D所在周的自然周五或所在月的自然月末；例如D=2026-11-10，周P=2026-11-13，月P=2026-11-30 |
| 源trade_date | 记录实际属于哪个周/月；Raw保留原值，Serving也保留被选完整行的原值，不能把28日改名为29日 |
| 源end_date | 源计算截至日期；当期必需股票至少计算到目标业务日D，允许计算到更晚的合法日期，上限为实际执行日的上海日期。历史修正保留各源行实际值，不要求等于原周期日期或执行日 |
| freshness/日期审计 | 月线仍按月、周线仍按周判断业务桶；目标日期覆盖、实际源截至日期和实际完成时间分别表达。跨日补齐不冒充原日按时完成，未来周五/月末坐标不代表数据已更新到未来 |

现有manual point/range的周五/月末含义保留。每日当期意图必须有独立明确的业务日表达，不能把任意日偷偷当成现有point而跳过validator。人工单股完整历史、准确撤回、组合处理通过现行`action=maintain`主线的具名意图/能力声明设计，公共字段及API/CLI增量见13.14，评审后实施，不先造旁路脚本。

Definition变更前逐项审计：manual actions、catalog、workflow、resolver/planner、request builder、freshness、dataset cards、snapshot rebuild、日期完整性审计、自动任务/probe、前端时间控件、所有Raw/Serving发布者及测试/模板。现有`ops/dataset_observation_registry.py`按freq过滤必须继续生效。前端继续消费后端日期及能力声明，禁止自行计算周/月坐标或从Raw挑选行情。

### 13.4 当期日更与预检

1. 复用现有Probe设施，在交易日且到达配置窗口后检查本频当天是否已有完整业务结果或活动任务；只在需要时预检。两频分别去重和提交，失败频率不占用另一频业务完成状态。
2. Foundation从Prod现有股票基础信息、上市/退市日期、人民币股票身份、停复牌结果和代码映射确定准入集合。已确认全日停牌为`suspend_type=S`且`suspend_timing`为空，允许缺席；新上市、盘中停牌均须达到本次目标日期。成功查询0行按0结果使用，不等待额外完成证明；现有合同中的真实查询错误或身份冲突按原规则报告，不能用日线缺行推断全日停牌。
3. 输入按13.16固定使用Prod现有Tushare Raw股票主数据、Raw每日停复牌、core每日复权因子、确认北交所映射及日历。管理员已定查询0行就按当天已完成且结果0使用，不增加完成证明或额外依赖下载；不把0描述为未知。security_serving只作已核消费旁证，不另算一套名单。
4. 三列预检与正式21列请求使用相同`freq + trade_date=P`、全市场分页。必须集合逐码核对，每个必需代码恰一条，且计算截至日期不早于目标业务日D、不晚于实际执行日的上海日期；不再使用`end_date=D`或以原D作为上限拒绝较新的合法回包。同数量换码、缺码、未达到最低日期、重复及真实未来日期不能通过。可选全日停牌股票有合法回包则接受，缺席不删旧行。
5. 预检不齐继续等待，不把正常源未齐创建为失败同步任务。提交后源仍可能变化，正式下载重做相同覆盖、日期、字段、身份和分页验证，通过后才写入。
6. 当期任务只更新本频当期周期，不做单股历史下载。新股首根周/月由此交付。请求周期标签可以晚于D，但源计算日期不得据此伪造为未来。
7. 一频业务提交并完成验收即可独立提供服务；两频同日完整结果齐备后，再检查是否应触发历史回刷。事务与观察失败隔离；不得因记录进度失败回滚已提交行情。

日期判断按场景明确如下，不新增过去快照保存功能：

| 场景 | 最低日期及处理 | 例子 |
| --- | --- | --- |
| 当日日更 | 必需股票计算截至日期至少达到目标交易日，且不晚于实际执行日；两个日期恰好同日时，自然只能是当天 | 11月10日日更：周trade_date=11月13日，月trade_date=11月30日，end_date=11月10日 |
| 跨日恢复原当期任务 | 继续原业务日、周期和范围；接受达到原最低日期的较新合法回包，保存真实源日期和实际完成时间，不要求回到原日版本 | 11月9日任务于11月10日补跑，同一目标周期的end_date=11月10日应通过，11月6日仍不足；不将实际值改写为11月9日 |
| 明确周期补齐 | 按该周期每股最后应更新日作为最低日期，允许更晚合法日期，采用实际执行日作为日期上限 | 某股周期最后应更新日为10月29日，源后来计算到11月13日仍可用于补齐 |
| 人工单股历史补数/修正 | 不要求每条历史记录的end_date等于旧周期日期、目标日或执行日；保留合法源值，同原键较新保护和整行选择继续适用 | 11月15日周日修正2020年2月，可以使用end_date=11月13日的源记录，不要求等于11月15日或2020年2月末 |

DG当前代码核验：`source_readiness/stock_period.py:check_period_rows`在未传expected_dates时用计算截至日期不等于business_date判为过旧，并以maximum_asof或business_date为日期上限；`stock_period_update.py:deliver_asset`的daily分支传原业务日作为上限，因此原daily配置跨日重跑也会拒绝较晚回包。closed_period分支传逐股最低日期及实际执行日；`stock_period_history_repair.py:_validate_upstreams`对采用后续完整交付的原日修复同样允许较晚日期。本次Prod设计原先复制了daily条件并泛化到恢复，属于设计错误，现按上表纠正；不修改DG代码，也不将此写成Prod新代码已经实现或已发生的线上故障。

审计结论明确为：DG原daily入口存在跨日重跑日期校验问题。触发条件是原业务日早于实际执行日且源端已经返回较新计算截至日期，此时会先按原日上限报未来日期，或因不等于原日而不通过；正常同日执行及采用正确补数路径不能据此一并判为有问题。此结论来自当前代码与配置允许传过去业务日的事实，没有执行正式DG重跑或修改其运行状态。

### 13.5 同周期多条记录：真实问题与服务层选择

2026-11-14通过Tushare MCP只查询`000001.SZ,freq=month,start_date=20200201,end_date=20200229`，显式取得完整21字段，返回两条。另通过Prod既有SSH只读事务，仅查同股同两日期、Raw/Serving所选字段，合计4行，结果如下。

| 源trade_date | 所属周期 | Prod Raw与Serving当前end_date / close_qfq | 此次源end_date / close_qfq |
| --- | --- | --- | --- |
| 2020-02-28 | 2020年2月 | 2025-09-10 / 12.0100 | 2025-09-10 / 12.01 |
| 2020-02-29 | 2020年2月 | 2025-12-04 / 11.7600 | 2026-11-13 / 11.14 |

两条未复权close均14.50，前复权OHLC不同。这里的“此次源”表示11月14日本次查询的回包，end_date是回包声称的计算截至日期；28日那条确实较旧，不把它补写成13日。源为何同时保留这两个日期未经本轮调查，不猜测其内部生产原因。

Raw当前主键为`(ts_code,trade_date,freq)`，28、29日是两个不同键，可以同时保存。问题发生在Serving仍照同样三字段写入、Quote读取按日期逐条返回：查询范围覆盖二者时会得到两个K线点，指标入口也接收两条；实际这两个点属于同一股票同一月份。尚未运行页面验收，不能直接声称当前某个图表已经画出两个蜡烛；已确认的是生产重复月份存储和后端缺少周期选择。另一个独立事实是29日记录本身也未更新到当前源版本，这由每日历史回刷解决，不能只去掉一条就算全部修复。

在上述2026-11-14核验样本中，Serving应选择2020-02-29那条完整源记录，前复权收盘价为11.14，因为它的计算截至日期2026-11-13比另一条2025-09-10更新。判断不按“28日还是29日”固定优先；若以后28日记录的计算截至日期更新，应按同一规则选择28日整行。日期完整性审计必须识别其所属自然月，不能为迎合固定月末标签而改选较旧行情或改写源日期。

以上整行选择是已定口径，不是待管理员选择哪条月线的问题。此前审计发现的是日期审计消费者未同步迁移，不能把该实现遗漏重新包装成Serving选行规则未确定。

对齐DG的发布算法如下：

1. 以确认证券身份、freq、自然周/月分组；Raw保留准入范围内全部合法源业务键，不因为服务层只需一根K线就删除Raw旧日期记录。
2. Raw相同业务键比较end_date，较早回包不能覆盖较新记录；源未返回的原键保留。跨次请求的同键end_date相同，按DG合并规则用本次合法源完整行更新，不额外阻止平台修订；同一次完整捕获内的同原键异值仍按源合同报冲突，不用最后一页覆盖掩盖问题。
3. Serving发布时读取该股票该周期所有适用Raw候选，筛选在市人民币股票及上市所在整周/整月起的适用范围；按end_date最大值选择候选，不按哪天是交易日选择。
4. 最大end_date相同的多条候选，完整业务字段一致时可合成一条，按DG确定性顺序保留trade_date较晚、再按代码的那一整行；业务字段不一致则停止该周期发布，保留原Serving结果，不随便选一条、求平均或拼接字段。
5. 发布结果保留所选源trade_date和21业务字段的值。此例取得当前源后选29日整行，前复权收盘为11.14；不得将28日的价格、29日的量额混成新记录。
6. Serving同股票同频同周期只保留所选行。保留现有表、主键和原始trade_date字段，按精确股票/周期在短事务中替换旧发布行；13.15补充两频各自的周期唯一索引及统一发布事务锁设计，不为页面增加一个“优先取最新”的临时SQL兜底。索引必须在获准的存量选择、冲突处理和读回完成后建立，不用建索引失败代替存量审计。
7. 页面和API读取已经发布好的事实，URL、复权选项及返回字段保持原结构。`bar_count`、`limit`、历史分页和MA/MACD等均按实际唯一周期记录工作；日期标签仍是所选源日期，不在页面改名。必须同时回归`_load_older_trade_date`，不能只测主查询。

源2行、Raw2行、Serving1行是合法选择差异，不能要求三者行数一律相等，也不能把未选的旧版本计为技术reject。source received、源原键去重、准入/范围排除、Raw写入、Serving选择、Serving写入、拒绝原因分别计数并对账。

### 13.6 独立历史回刷、闭合周期补齐与人工维护

- 自动名单只取相邻两个开市日均有有效复权因子、同一确认证券且数值变化的股票；新股首次出现不是历史复权变化。复用Prod现有`core.equity_adj_factor`及日历事实，不调用DG复权因子文件，不重新计算源价格。
- 每日自动回刷以复权因子业务日、该次已保存的变化名单及两频当期完整业务结果为依据。周、月任务使用同一次规划形成的名单；恢复使用原名单，不为“证明未变化”而让两个任务分别重算当天全市场名单。每个原业务日保留真实处理结果，不能只比很长窗口首尾或用后来成功掩盖漏掉的日期。
- 每只变化股票两频分别按`ts_code + freq`完整历史请求，不带任何业务日期过滤；按现行字段及分页合同取得全部记录。北交所请求有效新码，历史日期不触发旧码回退。
- 按源实际trade_date定位周期，Raw按键合并并保护较新end_date，Serving重新选择受影响周期。当前周/月可能也在历史返回中，必须经过同样较新记录保护，不能覆盖刚完成的当期新结果。
- 没有变化时保存该日零回刷结果，不请求单股历史。历史失败只影响该批历史完成，不阻挡后续当期日更；新的当期运行不自动删掉旧历史欠账。
- 单股完整历史只处理本次变化或明确指定的股票和频率，按源合法原键合并并重选其Serving；较早源日期不触发其他股票下载，不索要整周期全市场交付证明，也不自动派生全市场补齐任务。单股行或单股unit结果不代表全市场完整。运营明确选择全市场周期补齐时，才按周期内逐日必需集合并集与每股最后应更新日核验覆盖，并允许合法较晚计算截至日期。
- 跨日源已前移，原当期任务按13.4接受达到最低日期的较新合法记录；原业务日、源实际计算截至日期及实际补齐时间分别保留，不声称原日按时完成或重现原日快照。原日自动历史回刷继续使用原复权因子业务日及原名单，不改用运行当天的变化股票。
- 人工维护复用正式请求/计划/执行入口，支持明确股票完整历史、完整原业务键撤回、组合处理。撤回只删除批准的原始键；处理后重新发布所涉股票周期，必要时保留该周期其他合法候选。不得因回包没返回某个键就自动当作平台撤回。没有获准撤回清单时不删除Raw旧键。

上述变化名单只用于每日自动回刷。人工补数、指定股票修正或周末执行，按运营明确给出的股票/周期范围及原计划处理，不重新寻找“运行当天复权因子变化股票”，不要求两个人工任务反复核对全市场名单，也不因当前复权因子或无关主数据变化拒绝原任务。现有代码身份、请求范围和较新记录保护继续适用。

### 13.7 已取消的功能

2026-11-15管理员明确取消退市清理，本次不实现该功能；相关任务、探针、维护意图、删除步骤和测试已从本设计移除。股票身份与上市日期等既有准入事实继续使用，不据取消清理而扩大其他删除范围。

### 13.8 业务持久化、事务、并发与观察

继续使用`DatasetExecutionPlan`表达业务执行单元。计划必须冻结目标业务日、处理用途、频率、股票/周期范围、源合同版本、名单及输入依据；完整冻结前只允许保存不可执行草稿。历史范围可能随源返回增长，计划生成本身按批保存证据，不能在内存攒全市场多年结果。

已有`core.stock_weekly_adj_delivery`的合同、不可变触发器及消费者均限制旧周线，不能直接用于新月线或改变旧记录含义。新两频日更/回刷采用13.15的独立业务完成记录设计；不保存第二套queued/running/retrying状态，不复制完整历史行情到进度JSON。新表及公共类型属于本次拟实现设计，尚未建表、开发或执行DDL。

| 场景 | 必须可读回的事实与事务边界 |
| --- | --- |
| 当期 | `(用途,业务日,freq)`意图及单元；本次源齐备依据、Raw键与所选Serving结果分别计数；本频完整结果供历史触发 |
| 自动历史 | 原复权因子业务日、两频当期交付、同一次规划得到的变化股票名单及原单元集合；一只股票/一个频率完整捕获后提交，不以TaskRun.unit_done猜完成 |
| 人工历史 | 运营明确选择的股票、频率或周期，以及原冻结单元；不要求另一频任务存在、不依赖两频当期交付，不按运行当天复权因子重新筛名单 |
| 零变化 | 既有ProbeRunLog保存相邻日期、实际输入/比较行数及0变化结果；不请求历史、不造行情交付，不把上游0行当下载未知 |
| 准确撤回 | 原批准范围、精确代码/键清单摘要、原命中范围、逐单元实际删除数和最终残留核验 |
| 闭合周期补齐 | 一频一周期、目标业务日、完整预期代码及逐股最后应更新日证据、实际来源截至日 |

每个发布单元在一个短事务内完成Raw受控合并、Serving重新选择及业务完成记录提交；发现冲突则本单元不提交，旧业务结果保持。Raw与Serving合法行数差异按13.5分别对账。旧1:1写入回读合同必须同步迁移，不能更改测试预期来掩盖未审计差异。

所有写者使用13.15统一的按频率短事务互斥规则，并在事务中重读最新Raw/Serving：当期、历史、人工重发布和准确撤回均须覆盖。不能只锁新历史入口而让旧月末任务绕过，也不能继续拿一个跨任务共享待办锁住下一交易日。锁仅覆盖发布事务，不覆盖源请求或整个TaskRun；事务上限仍须真实预算核定及并发验证。

取消检查覆盖每个源页、单元及事务前后；提交前取消不留下半个单元，提交后退出保留业务完成事实，续跑只处理原未完成范围。相同单元重复执行幂等。同键源日期保护及Serving选择仍执行，不能因恢复而放松。

进度显示用途、阶段、股票/周期、完成量/总量、百分比、最后更新时间；运行中满足根AGENTS的30秒可见更新和取消要求，ETA不可靠显示暂无法估算。完成量只在确认业务提交后增加。Ops/TaskRun/node/issue/probe日志与业务事务分离，观测写失败不回滚业务；TaskRun与当前活动节点终态必须一致。

### 13.9 配置审计与可复算性能模型

| 配置/事实 | 当前值或来源 | 本方案安排 |
| --- | --- | --- |
| 源页大小 | 两个现有Definition为6000行，doc365同上限 | 保留真实connector分页；满页必须继续确认末页，不能拿MCP无分页输入当已验证分页 |
| 探测窗口及间隔 | Prod公共默认15:30—17:00、300秒；DG为上海交易日20:00起、60秒 | 管理员已定Prod自动任务当天20:00开始探测，不再作为待核实或编码前门禁；间隔沿DG60秒设计，窗口限定当天，不继承公共17:00结束；限流单独计入源预算 |
| Probe持久化 | `ops.schedule`及从属`ops.probe_rule`，已有window和interval字段 | 复用现有配置来源，明确唯一排程和从属规则；不另加env/脚本/页面常量各自维护 |
| 超时、响应及事务 | 原weekly policy和bounded client已有具名限制，仅旧周线已验收 | 不能自动把旧行数/页数/整批载荷预算推广到两频完整历史；第一阶段核定新用途配置、默认及消费者 |
| 每批规模/内存/SQL | 新流程尚无Prod实测 | 编码前用现有证据、有界源样本及代码推导填写设计预算；新SQL/取消/续跑的实际结果在阶段2—4隔离验收，生产实测不作所有编码的前提 |

设某次源查询实际返回原始行数为R，页大小L=6000；在分页真实有效、无额外失败且以短页结束时，完整请求数为`floor(R/L)+1`，整页结尾包含额外空页。预检R与正式下载R可能不同，分别计算。若两频各进行T_f次预检，总预检请求按每次实际分页数相加；正式当期按两频各自分页数相加，不预设每次只有一页。

某日变化股票数为K，完整历史有2K个股票×频率源单元，源请求数为各单元分页数加实际重试。续跑按持久化原未完成单元集合U求和，不把DG整批重跑的成本直接套到Prod。最终验收另计原计划/已完成事实核验、受影响Raw/Serving键读回及当前两频逐股覆盖。Serving选行可能少于Raw原键数，两层分别计数，不把两层写入相加称作独立行情行数。


第一阶段性能表必须填写：对象/交易日/周期数、源/页数、SQL次数、行数与字节、单批常驻内存、事务和锁、正常耗时、取消/退出后继续、末次验收、配额影响和超预算拒绝策略，逐项标识既有实测、代码推导和实现后验收方法。当前没有这些新流程Prod实测，不能以DG样本耗时保证Prod，也不任意乘余量填表；不要求编码前测出尚不存在的新实现结果。阶段区分见13.21。

### 13.10 硬口径、测试与真实验收

| 硬口径 | 实现位置/影响面 | 正向与反向验收 |
| --- | --- | --- |
| 每日两频更新当前周期 | Definition、resolver、planner、builder、probe | 周中/月中、自然月末休市仍请求正确P；当期覆盖后第二次不重复提交；不能拿D替代P |
| 逐码源齐备才写入 | Foundation预检及正式source client | 新股/盘中停牌必有、全日停牌可缺、同数换码/缺码/重复/过旧不通过；预检后正式源变动仍阻止错误提交 |
| 两频当期独立、历史独立 | TaskRun装配及业务完成记录 | 两种先后顺序；一频源未齐不挡另一频；历史失败后次交易日当期仍可执行 |
| 只取真实因子变化股票 | 日历、因子DAO及新规划 | 正常变化、非交易日、首次上市、因子0行按0；保留每个原业务日，不只比首尾 |
| 单股源完整历史、代码有效 | builder及bounded connector | 真实出站不带日期；新码、分页、重复页/缺字段/非法身份/源空或失败均按合同处理，不改为空成功 |
| 较新记录不得被覆盖 | Raw DAO、全部writer及发布入口 | 旧回包晚提交仍保新；日期前进及跨次同键同日期的合法新回包可更新；源缺席保留旧键；同次捕获同键异值拒绝 |
| 服务层每周期一整行 | 两频Serving builder、DAO、事务与Quote读链 | 本节平安银行两行金样本→一行；同最新日期同值可合并、异值拒绝；量额/价格/NULL均来自同一源行 |
| 指标/分页按唯一周期 | Quote主查询、older date、指标及所有实际消费者 | bar_count/limit/下一页无重复或漏月；原前/后复权选项及字段不变；不能前端自行挑选 |
| 单股回刷与全市场周期维护分开 | 人工maintain及回刷规划 | 单股源历史不要求先有全市场周期证明，不下载其他股票、不标全市场完整；明确全市场周期维护才核全周期必需集合和逐股最低日期 |
| 准确撤回范围准确 | 新维护意图、DAO、发布及审计 | 精确业务键、零命中、仅周/仅月、组合处理及范围外记录保留 |
| 取消/退出/恢复和幂等 | plan/executor/DAO/TaskRun worker | 事务前取消、提交后进程退出、重放、状态写失败、完成量单调、任务及节点一致终态 |
| 原记录和旧入口切换 | 原周批次、排程、CLI、动态注册 | 旧plan/unit/correction不改；未完批明确交接；新执行不读旧共享待办，不保留旧语义兜底 |

夹具优先使用真实生产者schema和本节有界源样本，expected用独立字面值；不调用待测选择函数生成expected。可用mock隔离HTTP及已验收上游，但必须说明替代边界。阶段2—4先用隔离数据库/资源串联。正式全量前另获准完成代表性真实运行—取消—续跑—读回，不以只有mock的通过证明真实接入。

真实源/Prod核验范围及结果以13.22为准，包含小范围分页、单股完整历史及必要Prod样本，不含全市场明细下载或新执行路径验收。本次未编码，文档检查不证明本功能已实现。

### 13.11 旧合同消费者与切换清单

1. 覆盖manual/catalog/workflow/Definition及模板、resolver/planner、builder、source/normalizer/writer、ServingPublishService及两频注册、DAOFactory、freshness/观测/snapshot/完整性审计、schedule/probe及TaskRun/worker、CLI、Quote API/历史分页、前端真实消费者及测试；第一阶段逐项落代码位置，不以本节清单替代实查。
2. 核对当前旧周批次、排队/在途任务及三条排程，先说明原范围、已提交事实、办结/交接步骤及失败退路；原任务历史不改成功，不在恢复时换范围。
3. 新Raw较新保护和Serving整行选择必须覆盖人工重发布，不能仅改IngestionExecutor。Serving已有重复周期只在批准的键范围重发布；Raw合法两条源记录不因选一条Serving而删除。
4. 日更切换时迁移旧月末6/15和旧周14的目标/日期策略与从属probe，不能只增加新排程叠在旧任务上。数据库迁移前重新核对真实Alembic head及相关唯一键/约束，不按本稿日期猜revision。
5. 明确周期维护、存量重发布、指定股票历史下载及旧入口清退均按各自准确范围执行，不因单股源历史较早或日期缺口自动新增全市场补数。正式执行继续核对授权范围、读写及恢复成本，不要求每日全量重刷。
6. 生产切换验收分别证明两频当期、实际变化历史及人工操作结果；自然日更另验收。按管理员2026-11-16精简决定，阶段5取消/原ID恢复与同一次真实历史回刷合并，不默认额外下载两股完整月线；人工新建/撤回/组合的已有隔离证据及生产是否实际操作分别记录，详见13.31.7。不能把未执行项冒称生产已验收。

### 13.12 当前评审与下一阶段门禁

13.14—13.27及两个开发说明已按管理员已定口径填写和逐项对账。2026-11-16已补齐共用名单的保存/读取步骤、准确撤回单元及相应测试安排，本轮文档复核通过。真实connector分页/单股完整历史已核，数值限制及推导在13.24；管理员已定上游0结果直接使用、不新增完成表。设计填写及文档检查不代表代码、测试或生产验收完成；新SQL/内存等在实现后验收，后续按原方案7.5分阶段推进。

### 13.13 方案复审记录与设计边界

管理员已定：每日当周/当月更新；每天因子变化驱动两频历史；按DG处理同周期源记录；信任平台价格。本轮不增加源价格正确性计算、历史价格自行修正或每天全历史扫描。

新执行器不继续调用旧weekly的价格基准推导来决定平台价格是否正确；复权因子在新流程只负责识别变化股票，当前行情是否齐备按源end_date及逐股覆盖判断。旧基准校验与原交付历史保留在历史说明，不能作为新月线的隐含新增门禁。

| 原稿缺口 | 编码设计补充 | 当前状态 |
| --- | --- | --- |
| D怎样进入原有日期合同、哪些输入不能同时传 | 13.14的明确业务日及维护意图 | 已补设计，未实现 |
| 月线完成事实、原范围和幂等续跑保存在哪里 | 13.15独立业务记录表及逐单元协议 | 已补设计，未建表 |
| 当期、历史、人工发布怎样避免互相覆盖 | 13.15频率事务锁、Raw条件upsert、Serving周期唯一性 | 已补设计，待隔离数据库实证 |
| 上游0行怎样处理 | 13.16直接使用现有数据；13.22记录管理员决定 | 已定：0行按当天0结果，不新增证明、不扩上游 |
| 当期完成后复权因子晚到，历史检查可能不再发生 | 13.17复查依赖、同日去重和零结果 | 已补设计，未实现 |
| 公共合同的消费者和验收没有逐项定位 | 13.18—13.19文件与测试对应 | 已补已查位置；实现前仍逐消费者关闭 |
| 新流程没有完整性能数值和完整分页证明 | 13.22真实分页与单股开销；13.24逐项设计预算及推导 | 源样本已核、设计限制已写；新SQL及实际资源开销在实现后验收，非当前已测 |

下文类型、表和方法名都是拟实现位置，不表示已存在；引用现有文件会说明其当前职责。设计不引入通用执行引擎、额外worker、第二套任务状态或跨工程运行依赖。

### 13.14 输入schema、归一化和冻结计划

**一、保留入口，增加本功能的明确意图。** 两个dataset key及`action=maintain`不变。拟在`datasets/models.py`登记两频共同的具名`stock_period_adj_policy`，替代活动Definition的week专用policy；其他数据集默认无此policy。新合同同时反映到`definitions/_builder.py`、Definition检查和开发模板。旧周线历史记录和读取接口保留，旧执行规则在切换后退出活动路径。

`DatasetActionRequest`及手动创建请求拟增加可选`maintenance_intent`，本功能的值如下；其他数据集不接受本功能对象。它是运营的处理意图，不直接透传Tushare。`execution_context`仍只接收resolver冻结结果，浏览器不能自行填入执行计划。

| `maintenance_intent.kind` | 输入 | resolver生成的本频执行单元 |
| --- | --- | --- |
| 缺省 / `period` | 原point/range、可选原单股过滤；保留周五/月末规则 | 周期全市场补齐或已有周期内的明确单股修订；单股不能创建完整全市场周期 |
| `current_period` | `time_input.mode=point`及新增`business_date=D`；禁止源周期日期、区间及单股过滤 | 本频D所在P的一个当期全市场单元 |
| `stock_history` | `time_input.mode=none`、明确`stock_codes` | 每只有效股票本频一个完整源历史单元，不带日期 |
| `remove_keys` | `time_input.mode=none`、非空`remove_keys`，每键含`ts_code,trade_date,freq` | 按一只股票、本频的全部指定键形成一个撤回单元；精确撤回并重新发布受影响周期，不进行源下载 |
| `stock_history_and_remove` | 上述完整历史股票及精确撤回键；均显式提供 | 按下载股票与撤回股票的并集，一股本频一个单元；需要下载的先完整捕获，在同一事务合并/撤回并重选Serving，只有撤回的单元不请求源；撤回键即使源仍返回也不写回 |

每日自动历史检查使用内部意图`factor_history`，提交`time_input.mode=point,business_date=D`。resolver按该业务日及其前一开市日的现有复权因子形成变化股票名单，供该次周、月历史回刷共用。它不进入公开手动选项，人工补数使用明确股票的`stock_history`或原`period`；取消的退市清理不保留内部意图。恢复沿原任务/原冻结计划。

`stock_codes`和`remove_keys`属于新维护意图，不把现有单值`filters.ts_code`悄悄改成多值。撤回键的freq必须与所选数据集一致，禁止另一频键。组合维护中同一股票的下载失败时，该股票对应撤回也不执行；源未涉及、但撤回清单涉及的股票仍按明确范围处理。没有源刷新股票的纯撤回使用`remove_keys`意图，不能以空下载代替成功。

准确撤回单元按`ts_code`排序，组内指定键按`trade_date`排序，`unit_id`由`purpose:freq:ts_code`稳定生成；不把同一股票拆成逐键事务，也不把多只股票放进一个全批事务。纯撤回单元数等于指定键涉及的不同股票数；组合维护单元数等于下载股票与撤回股票并集的股票数。`plan_unit.payload`保存本股是否有源请求及本股完整指定键，不在恢复时重新从页面取范围。例如撤回A股票两条月线、B股票一条月线，形成A、B两个单元；A提交后中断，恢复只处理B。组合维护若只下载A、另撤回B，则A按历史单元执行，B按无源请求的撤回单元执行；不会因为B不在下载名单而遗漏或擅自下载B。

`business_date`为可选DATE字段，增加到`DatasetTimeInput`和`ManualActionTimeInput`；手动只在`current_period`的point模式有值，内部`factor_history`也按上段使用，且必须是已确认开市日、不晚于上海当天。过去业务日表示原任务的最低覆盖要求，不是请求该日快照。原point/range继续只使用原日期字段。`business_date`和原`trade_date/start_date/end_date/month/start_month/end_month/ann_date`互斥，不能靠字段优先级忽略一部分输入。此约束由本功能resolver校验；其他数据集的合法输入行为不变。

当前dispatcher的`_prepare_dataset_action_request`会给未填trade_date/month的point请求补默认交易日；新意图已有business_date时必须原样通过，不能再补trade_date造成双日期。`_build_dataset_action_request`、`_dataset_time_input_payload`、任务受理层及workflow复制request的位置必须同时保留business_date和maintenance_intent，不能只给首个构造函数加字段。

例如提交`current_period + business_date=2026-11-10`：周计划的源日期为2026-11-13，月计划为2026-11-30；两者都保存业务日11月10日。Ops、CLI和表单原样保存11月10日；只有resolver计算P。builder只将冻结日期格式化成`YYYYMMDD`，不能再次根据运行当天推日期。旧手动`period + trade_date=2026-11-13`仍表示修订该周，不能自动改成11月13日的日更快照。

**二、每个计划只属于一个数据集、一个频率。** 自动历史依据同一D、同一变化名单和两频当期完成记录，有变化时分别生成week/month两个正式计划及TaskRun；共同保存实际输入摘要和两频当期交付引用，不让一个`DatasetExecutionPlan.dataset_key`混写两频。两频各自可恢复，完整业务验收须两频都完成。以上均复用现有任务及Probe，不另造跨频任务状态机。

同一名单仅约束同一次自动因子变化回刷，复用首次保存的规划结果；不让两个频率各自重新筛选一份运行当时的最新名单。人工补数、修正或周末执行只使用运营选择的范围，可以只执行一个频率，不要求周、月名单相同，也不要求配对创建任务。

保存和读取的具体顺序如下，范围仅为同一次自动`factor_history`：

1. 历史Probe先按`purpose=factor_history、D、本频`读取13.15的冻结计划及完成记录。已有冻结计划时，依据原范围判断是否需要入队，不重新比较因子；尚无冻结计划时，只将现有因子查询的变化条件及D用于触发本频TaskRun，不在Probe受理链生成长计划或保存整份名单。
2. 首个进入worker规划阶段的历史TaskRun，由Foundation的`stock_period_adj_planning.py`先查该D的冻结计划；不存在时，读取相邻开市日复权因子一次，形成排序后的同一份变化股票名单。用这份名单生成两份分频计划，分别有自己的`batch_id`、`用途+freq+D`意图键及单元，不重复筛选第二份名单，也不生成另一频的TaskRun。0变化仍按13.17只记录实际0结果，不冻结空历史计划、不请求源。
3. 两份计划的单元草稿分别写入原拟建`core.stock_period_adj_delivery`，完整核对后，在同一个短业务事务中按week、month固定顺序追加两条`plan_frozen`。各冻结头的`history_plan_refs`均保存`week_batch_id、month_batch_id`；共同保存本次实际输入摘要和两频当期交付引用。名单由各计划已持久化、按股票排列的`plan_unit`保存，TaskRun和冻结头不再复制完整股票数组。这里只共同冻结计划，不合并两频行情提交事务、不等待另一频行情执行。
4. 后进入的另一频任务按`purpose+freq+D`读取自己的冻结头，再按`batch_id`分页读取原`plan_unit`；其名单来自首次规划已经写好的本频单元，不再查询当天因子重算。两个首次规划同时到达时，沿已定的冻结意图唯一约束只提交一对计划；未提交的一方回滚该次冻结，读取已提交原计划，不另加锁、表或协调服务。
5. 冻结前中断的草稿不能执行，沿13.25按原D重新规划；两条冻结头同时提交或同时回滚，不会把半对草稿当成完成计划。冻结后任一任务中断，按本频原计划和已提交单元恢复；另一频即使尚未创建TaskRun，也由原从属Probe在有效窗口内根据已保存计划继续入队，不要求因子再次变化。窗口结束不另加跨夜探测；未完成范围保留供原任务恢复。TaskRun关联或观察写入失败不撤销已冻结的业务计划。

例如首次规划名单为A、B，周、月计划各保存A、B两个历史单元；周线先执行或失败，都不会让月线改取当时重新计算的A、C。此约束不用于人工任务。

**三、冻结内容。** 拟在`execution_context.stock_period_adj`保存`contract_version,batch_id,purpose,business_date,period_date,scope_digest,policy_digest,input_digest,upstream_revisions,plan_revision`，自动历史另保存上述`history_plan_refs`；具体范围及单元保存在13.15业务记录中。`purpose`区分当期、因子变化历史、周期补齐、人工历史、准确撤回、组合维护；这是计划用途，不是TaskRun运行状态。源参数仍只由request builder依据计划单元生成，不将上游引用、业务日或用途发给Tushare。 upstream_revisions只指本功能两频当期/周期业务交付，不指三个上游新增完成记录；input_digest依据现有业务行，0结果也合法。同值重跑仅fetched_at或观察状态改变不影响原业务摘要。

原范围的恢复只接收已有`resume_from_task_run_id`，核对同数据集、同合同和已停止原任务，从原冻结业务计划取未提交单元；不接受恢复时另传日期、股票、撤回键或预算。当前手动受理层只开放公告恢复、TaskRun冻结层有week专用分支，必须同时迁移，不能只改worker。每日唯一意图键为`用途+freq+D`；人工新修订具有新的请求标识。自动历史恢复直接使用原冻结名单，不用运行当天的名单覆盖原范围，也不因重复核对全市场因子而拒绝原批。人工修正或范围变化仍通过明确的新维护意图表达。

归一化后，当期源单元固定`freq+trade_date=P`；因子变化历史/人工完整历史源单元固定`freq+ts_code`，不得有trade_date/start_date/end_date；纯撤回单元没有源请求。完整源21字段从Definition注入，只有独立预检显式取三列。新policy的两频正式捕获均采用有拒绝即单元失败，替换月线当前`record_rejections`后仍继续写的行为；这只作用于本次两个数据集。

### 13.15 业务记录、DAO、事务和唯一性

**一、拟新增`core.stock_period_adj_delivery`。** 必要性是两频要保留冻结原范围、独立单元提交及完整交付事实；现有week表的不可变合同不能扩义，TaskRun又不属于业务数据事实。沿用“追加事实”的形式，不复用旧week表，不存queued/running/retrying，不复制完整行情到JSON。

| 列 | 类型及约束 | 负责的事实 |
| --- | --- | --- |
| `revision` | BIGINT identity主键 | 读取引用；允许回滚空号，不用连续号证明完整 |
| `contract_version` | SMALLINT，初版1 | 本地业务记录版本，与Tushare字段合同版本分别校验 |
| `batch_id` | UUID，非空 | 原冻结处理范围的身份，跨TaskRun恢复不变 |
| `intent_key` | TEXT，非空 | 自动为用途/freq/D，人工为用途/freq/新请求标识；只在冻结行建立唯一索引，其他记录继承原值 |
| `record_kind` | VARCHAR，限定`plan_unit/plan_frozen/unit/batch_closed` | 单元草稿、完整冻结、单元提交、整批完整交付四类不可变事实 |
| `unit_id` | VARCHAR(128)，非空 | 原单元稳定身份；冻结及闭合行使用保留值，不能与业务单元冲突 |
| `purpose/freq/business_date` | 用途枚举、week/month、可空DATE | business_date在自动用途必有；人工无目标业务日时保留NULL，不伪造历史快照 |
| `period_date/ts_code` | 可空DATE/VARCHAR(16) | 有单一周期或股票的单元直接投影，便于有界检索；全市场不填伪代码 |
| `contract_digest/scope_digest` | CHAR(64)，非空 | 源合同及原范围摘要；算法沿用现有canonical JSON与SHA-256实现规范 |
| `payload` | JSONB，非空，大小受具名policy限制 | 本类事实的输入引用、单元描述或结果；禁止完整源行情、重复任务日志及任意原始错误 |
| `created_at` | 带时区时间，数据库生成 | 事实提交时间，不代替业务日或源end_date |

唯一键`(batch_id,record_kind,unit_id)`负责幂等；`plan_frozen`按`intent_key`建立部分唯一索引，人工新意图与自动同日意图分别按上表规则生成。索引覆盖`(purpose,freq,business_date,record_kind)`和`(freq,period_date,record_kind)`。表禁止UPDATE/DELETE，沿现有week表的不可变约束实现方式编写本表独立约束，不改旧触发器。

`plan_unit.payload`只含源请求形状、精确股票/周期或批准撤回键、输入引用和本单元摘要。逐批持久化这些行后，按序计算单元数及摘要并追加`plan_frozen`；没有冻结行的草稿不能执行。`plan_frozen.payload`保存有序单元摘要、总数、输入版本、当期预期集合摘要和来源引用，不重复内嵌全部单元。同一次自动历史的两份计划另按13.14共同冻结，并在JSONB载荷中保存两份计划的`history_plan_refs`，不新增列或记录种类；其他用途仍各自冻结。冻结使用本次规划已读取的业务内容与明确意图，不为人工补数额外重读全市场复权因子来验证名单未变化。

`unit.payload`分别保存源原行数、合法原键数、准入排除原因、Raw实际新增/更新/较新保护数、Serving选中/写入数、准确删除数、分页结束证据、源及结果摘要、实际单元范围。未返回旧键不计删除，未被选为Serving不计技术reject。`batch_closed`只有在原冻结所有单元均提交且结果对账通过后追加；无变化由既有Probe日志保存真实0检查结果，不创建无行情工作的业务闭合批，不能没有查询就声称已检查。

拟新增`models/core/stock_period_adj_delivery.py`及对应DAO，进入`DAOFactory`与现有模型发现；DAO提供追加计划单元、冻结、分页列未完成单元、追加提交、核验并闭合、按D/freq取完整交付的方法。自动历史另由同一DAO提供按D读取已冻结两频计划和同事务冻结两份计划的方法，Foundation planner调用，Ops不自行拼名单。没有查询全部历史行情来恢复的步骤。重复提交同幂等键时读取原事实并比较摘要，相同返回已完成，异值报合同冲突，禁止`ON CONFLICT DO NOTHING`掩盖异值。

**二、捕获与短事务。** 当期/周期补齐以一个频率、一个全市场周期为源捕获单元；股票历史以一只股票、一个频率为源捕获单元。每个捕获必须在本policy核定的行数、字节和总期限内完成分页、归一化及校验；只保留当前单元，成功提交后释放，不积累全部股票历史。取消或退出前尚未提交的捕获下次重新请求，已提交单元绝不重抓。若代表性实测证明完整单股或全市场周期无法满足上限，先修改本LLD的捕获/持久化方案，不能编码时悄悄扩大内存或拆成未验证的部分发布。

通过完整捕获后，新发布函数按以下顺序执行：取消检查→开始业务事务→取得本频率事务锁→读取原冻结范围及已提交单元→Raw条件合并/准确撤回→读取本次受影响股票周期的Raw候选→选择Serving整行→只替换这些股票周期→分别读回Raw/Serving→追加unit事实→提交。任何冲突或失败回滚本单元三部分业务数据；既有已提交单元保留。股票历史unit仅证明该股票本频结果，不要求全市场周期交付依据，也不能生成其他股票的补齐计划或全市场完整结论。

纯撤回单元跳过源捕获，直接按上述顺序处理本股指定键；组合单元仅在该股需要下载时先捕获。事务中排除新回包内的指定撤回键并精确删除Raw原键，然后按完整受影响股票周期重选Serving；仍有候选则选择剩余最新完整行，没有候选才删除该股票该周期Serving。范围外数据不动。删除数、重选结果及unit事实一起提交，不以“已删几条”推进半个单元。取消在每个单元及事务前后检查；当前未提交事务回滚，已提交股票保留，恢复只读未提交股票，不重新下载已提交股票，不把源未返回当成撤回理由。纯撤回和组合维护均沿13.24已有计划、行数/载荷及累计事务限制，不新增撤回专用数量上限。

**三、锁和Raw条件写入。** 新发布者统一使用按freq区分的`pg_try_advisory_xact_lock`；锁键由固定用途字符串和freq按现有digest规范生成有符号64位值。锁只持有一个业务事务，源网络下载、逐股历史等待和Ops观察均在锁外；拿不到锁则本单元不写入并报告writer busy，不能持锁轮询。两频锁不同。旧week专用session锁随旧执行路径退出，不能新旧锁并用。

Raw仍以`(ts_code,trade_date,freq)`冲突，更新完整业务行的条件为：传入end_date有效，且旧值为空或`EXCLUDED.end_date >= existing.end_date`。源新捕获end_date为空或非法是合同失败，不能补成今天。旧NULL仅在合法新行到达时被替换；只有旧NULL候选而无法选择有效截至日的Serving重发布停止，列明确切范围待修复。`RETURNING`只计实际写入行；较早源被保护不是拒绝或源空。相同请求内重复原键须在upsert前完成冲突检查。

PostgreSQL依据：已通过Context7核对[事务级锁](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)在事务结束释放、[ON CONFLICT条件](https://www.postgresql.org/docs/current/sql-insert.html)在识别并锁定冲突行后判断，未更新行不出现在RETURNING。该资料支持SQL行为，不证明本项目实现或并发测试已经通过。

**四、Serving唯一性。** 保留原三个主键列及API日期，拟加两个按freq限定的唯一表达式索引：week索引为`(ts_code, trade_date - (EXTRACT(ISODOW FROM trade_date)::integer - 1)) WHERE freq='week'`，month索引为`(ts_code, trade_date - (EXTRACT(DAY FROM trade_date)::integer - 1)) WHERE freq='month'`。表达式分别得到自然周一和月初，不加本地辅助日期列，不改变Tushare21字段合同。实际DDL须在隔离数据库验证表达式可建索引及冲突样本；阶段2已在PostgreSQL18完成，管理员明确忽略16/18版本差异，不再要求按版本差异复测，见13.28.2。

Serving候选业务等同比较是21字段去掉身份/源日期/计算截至日期/频率后的17个业务字段，逐字段保留Decimal/NULL语义。选择和范围删除共用同一个周/月计算函数，Quote不再另算。所有发布者调用同一函数，禁止已有两个Serving builder或通用writer直接三键upsert绕过选择及锁。不能用全表DELETE重建；准确撤回清空最后候选时才删除该股票该周期Serving。

`ServingPublishService.execute_publish_plan`当前最终调用`target_dao.upsert_many(plan.rows)`，仅修改两个builder的分组键仍会留下旧Serving行。新具名发布路径必须把完整受影响股票/周期范围交给共同publisher，在锁内重读Raw并替换范围；dry-run只生成/检查计划，不取得发布权或写入。其他数据集继续原发布实现，不修改通用DAO全局行为。

新索引建立前先停止旧写者、按批准范围处理存量重复/冲突、读回，再建立约束；发现同最新end_date异值时停止该周期，不自动删除冲突Raw。代码不能先部署到仍有旧写者的数据库。当前静态解析全部Alembic revision/down_revision得到唯一head为`20261112_000188`；本轮不创建迁移，真正创建时重查，禁止把此快照直接当日后down_revision。

### 13.16 现有输入数据与业务对象合同

**管理员2026-11-15已定：查询返回0行，就认为当天已经下载完毕且结果为0；不新增完成证明开发。** 本功能直接使用Prod现有表，不给股票主数据、每日复权因子或每日停复牌生产者增加写入，不新增上游完成记录表，不另向源重复捕获依赖，不以TaskRun/node状态判断这些输入是否可用。

本功能Foundation输入读取模块`ingestion/stock_period_adj_inputs.py`返回实际业务日D、日历、在市人民币股票、确认身份、全日停牌集合、因子实际行数及可比较结果。只冻结本次实际所用的业务键/值摘要，0结果也有确定摘要；它属于原执行计划/恢复设计，不是另建输入下载状态。

| 输入 | 唯一读取来源与处理 | 0行及版本口径 |
| --- | --- | --- |
| 股票主数据及上市/退市日期 | raw_tushare.stock_basic的Tushare现有业务字段；按人民币股票、上市/退市日期和确认身份取范围 | 直接采用查询结果，包括0；不要求四种状态的新增完成证书，不在多源security_serving和Raw之间切换名单 |
| 股票确认身份 | core_serving_light.bse_mapping及Raw股票主数据 | 只用已有可确认的映射及证券身份，不按前缀猜、不把换码当退市；冻结所涉映射业务摘要，不以fetched_at变化误判 |
| 每日停复牌 | raw_tushare.suspend_d的D日记录；全日停牌按已定S且suspend_timing为空判定 | 0行即当天无停复牌记录，使用空集合，不等待额外完成信号；不是把0计作下载未知 |
| 相邻交易日复权因子 | core.equity_adj_factor及SSE交易日历 | 按两日实际数据形成可比较股票及变化集合；0行按0处理，无可比较股票就记本次0结果，不标为下载未完成。首次上市不当作因子变化，数值有效性沿既有合同 |
| 闭合周期范围 | 对应日期范围内上述现有业务数据及已维护的周期覆盖事实 | 按实际逐日对象/停牌结果形成集合并集与最后应更新日；0仍按0，不增加历史输入完成表 |

Prod现有后台执行器使用原冻结范围；fetched_at、任务状态或无关字段变化不影响执行。人工补数不增加当天复权因子比较或全市场输入版本检查；自动回刷使用创建本批时保存的名单。股票身份与源请求范围仍按既有合同校验，不增加上游批次证明。

当期行情自身的三列预检及21列正式下载仍按13.4逐股核对。这是已定行情源齐备规则，不是重新要求上游提供下载证明。

### 13.17 自动触发、日期欠缺和配置来源

复用ScheduleAutomationCapabilityResolver→ScheduleProbeBindingService→ProbeRuntimeService→TaskRunCommandService。Foundation只读取现有业务数据、比较因子并生成计划；Ops负责配置、入队与展示，app装配。没有新服务、worker、lane或反向依赖。

本功能只声明当期条件`stock_period_adj_current_ready`和历史条件`stock_period_adj_factor_history_ready`。每频一条对运营可见的日更自动任务，绑定本频当期、历史检查两个从属Probe，复用现有设施；历史条件仅为本功能内部依赖，不提供给其他数据集或公开手动选项。现有binding在更新/暂停时按schedule处理附属规则，本功能扩展为两个模板，其他数据集继续一份；按父schedule事务同步，不另加状态机或调度服务。

1. 当期Probe先看本频/D完整业务交付及活动任务，再做三列预检。正式worker重做字段/范围/日期验证；一频未齐不挡另一频。
2. 历史Probe只等待同D两频当期业务闭合，不等待三个上游的新完成证明。先读本D已有冻结历史计划；已有则复用原计划判断本频是否需要入队，不再比较因子。没有冻结计划才按现有相邻交易日因子实际查询结果判断变化；0行按0，没有变化就将日期、实际行数、比较股票数及0变化结果保存到既有ProbeRunLog，不请求单股历史，也不创建无行情工作的TaskRun/业务闭合批。
3. 零结果是本次检查已完成，不是下载尚未完成。已有60秒探测仍照常运行到窗口结束，实际因子数据之后到达并出现变化时可触发；0日志不占非零历史任务的当天触发名额。有变化时每频只入队一份原意图；首个worker规划同事务冻结两份历史计划，后续任务读取本频原计划，具体保存/读取及中断规则见13.14。历史失败保留原范围供恢复，不挡次日当期。
4. 窗口结束时，当期未齐或未完成的真实业务意图保留原D及具体原因，不能把上游0行描述成未知，也不能拿后来源回包伪造旧D快照。已在运行的正式TaskRun不因00:00被强制取消，原范围及恢复规则继续适用。

防重同时使用新业务意图唯一键和活动TaskRun。活动查询按dataset、purpose、D区分，不能只比较本周/月P而让周一旧任务挡周二。进度/Probe日志不是行情完成水位，写失败不回滚行情；0日志丢失只影响观察，不影响后续正常检查。

配置只在Definition具名policy及现有ops.schedule/probe_rule维护。页/行/响应/事务限制冻结到原计划，恢复不按新参数重推；窗口/间隔/时区由后端能力保存并同步两个附属Probe，前端不维护第二套常量。Tushare凭据沿已有Settings。

**已定窗口为上海时间20:00开始、目标业务日次日00:00停止新探测/入队，间隔60秒**，保存window_start=20:00、window_end=00:00，仅本功能采用，不改公共17:00默认。通用_in_window包含00:00端点，本功能按原D限制，零点不探测旧D、也不提前探测新D；列入正常边界测试，不改其他条件端点。阶段5切换旧6/15/14及附属规则，避免新旧重叠，不再验证该排程口径是否可行。

配置审计如下。数值及依据只在13.24维护，下面明确保存位置、消费者和生效方式；不新增env或页面常量。

| 配置名及值 | 来源与持久化位置 | 作用范围、消费者及依赖 | 生效、运营可见性与测试 |
| --- | --- | --- | --- |
| `stock_period_adj_policy`的页/行/载荷/计划/内存/超时限制，值见13.24 | 两条DatasetDefinition共用具名policy；冻结值及摘要保存在本功能计划业务记录，TaskRun仅保存观察副本 | 仅两条复权行情；resolver、planner、request builder、source client、publisher及control消费；Definition规划限制由policy投影 | 部署后新计划采用；原冻结计划不随新值变化。任务详情显示实际预算/超限原因；边界、恢复不改限值和其他数据集不变均测试 |
| `window_start/window_end/probe_interval_seconds`=`20:00/00:00/60`；`timezone_name=Asia/Shanghai` | 后端自动化能力声明；父`ops.schedule.probe_config_json`/`timezone`，binding同步两个`ops.probe_rule`对应字段 | 仅本功能两种从属条件；capability resolver校验，binding保存，runtime按D判断，自动页只展示后端值；依赖交易日历 | 创建/编辑后同事务同步；暂停沿现有绑定删除附属规则，不再检查。测试19:59/20:00/次日00:00、编辑回填、暂停及无关条件不变 |
| `max_triggers_per_day=1` | 沿现有Probe单日默认值并在本功能能力固定；保存到各附属规则 | 两种用途分别计数，业务意图另按freq/用途/D唯一；历史0日志不算触发，失败入队不冒充完成 | 运营查看每种用途检查/触发结果；测试0后有变化可触发、同D防重、同周不同D互不阻挡及恢复原批 |
| `probe_condition_json/on_success_action_json` | binding从13.17两种固定条件生成；保存到各附属规则 | 只携带本数据集、用途及运行时D意图，历史为内部用途；不带可随意改写的freq、源参数或固定历史日期 | 随父任务配置同步，运营只维护一条日更任务；测试错误数据集/动作/伪造内部用途拒绝及两规则同步 |
| 既有`TUSHARE_MAX_CALLS_PER_MINUTE`/Settings，当前值280次/分钟 | 既有环境及Settings；不新增或修改。客户端实际仍按现有运行配置覆盖→接口专用值→Settings顺序取值 | 既有`clients/tushare_client.py:_get_rate_limiter`及两频source调用；同进程同接口共用，不能据此声称跨进程共享或平台实际授予280配额 | 复用原加载/生效方式；任务展示限流等待原因，凭据不展示。测试等待时取消/进度，生产启用另核共用配额 |

`TUSHARE_TOKEN/TUSHARE_BASE_URL`继续使用既有Settings及client，不增加副本或运营输入。配置失败不得改写业务范围；观察配置/日志也不进入行情事务。

### 13.18 文件级改动和消费者迁移清单

| 合同/消费者 | 已定位位置 | 设计动作及阶段 |
| --- | --- | --- |
| Definition及能力投影 | `datasets/models.py`、`definitions/_builder.py`、`definitions/market_equity.py` | 阶段1完成共同policy与意图schema设计；阶段2迁移两条定义，阶段3开放已验收的历史/人工维护能力；不新增dataset key |
| 计划、校验、出站 | `ingestion/execution_plan.py`、`resolver.py`、`validator.py`、`execution_scope.py`、`unit_planner.py`、`request_builders.py`、`source_client.py`；`clients/tushare_client.py`、`clients/bounded_tushare_call.py` | D只在resolver变成P；具名新执行路径，三列预检/21列下载和完整历史严格分开；新增两频响应合同不能复用只许week的旧响应合同，其他数据集不变 |
| Raw及发布 | `ingestion/writer.py`、`dao/base_dao.py`、`dao/stk_period_bar_adj_dao.py`、`dao/factory.py`、两层行情ORM | 本功能专用条件写入，不更改BaseDAO全局upsert语义；业务记录ORM/DAO按13.15新增并登记 |
| 人工Serving重发布 | `serving/publish_service.py`、两个`stk_period_bar_adj_*_serving_builder.py` | 日更及重发布共用选择及事务锁；不得保留旧三键直接写入旁路 |
| 手动API与恢复 | `ops/schemas/manual_action.py`、`services/manual_action_service.py`、`queries/manual_action_query_service.py`、`services/task_run_service.py` | 新意图、business_date、条件时间表单及恢复同次迁移，后端权威拒绝非法组合 |
| worker及任务入参 | `ops/runtime/task_run_dispatcher.py`、`ops/runtime/worker.py`、`app/runtime/ops_worker_factory.py` | 序列化/反序列化新字段；使用已冻结计划，不重算当日日期；终态沿现有TaskRun主链 |
| 自动化与Probe | `schedule_automation_capability_resolver.py`、`schedule_probe_binding_service.py`、`operations_probe_runtime_service.py`及新本功能只读检查适配 | 当期、历史各自去重及等待；计划生成不放Ops；具体条件支持范围由Definition能力派生 |
| catalog/workflow/CLI | `ops/action_catalog.py`、`ops/catalog/dataset_catalog_views.py`、dispatcher的`_dispatch_workflow/_build_dataset_action_request/_prepare_dataset_action_request`；`src/cli.py:maintain_dataset`及`cli_parts/ingestion_handlers.py` | 两个原目录项保留；workflow逐层保留已给定意图，不自动纳入准确撤回；本轮不增加CLI命令/参数，既有调用不偷偷转当期，旧周线修订命令切换前单独审计引用 |
| freshness/卡片/快照 | `datasets/freshness_policies.py`、`ops/dataset_observation_registry.py`、`operations_dataset_status_snapshot_service.py` | 原周/月桶和freq过滤保留；新增D交付状态明确显示，不把未来P当更新到未来；业务记录表不计行情数据量 |
| 日期完整性审计 | `ops/services/date_completeness_audit_service.py`及其schema/API/查询 | 迁移ActualBucketReader及对象审计的实际日期读取：对启用本功能policy的两数据集，按Definition的自然周/月归属与预期周期比较，不再只按源trade_date等于固定周五/月末判断缺失。保留原源日期与其他数据集行为；周期存在、全市场覆盖和目标日更新分别表达 |
| 运营前端 | `frontend/src/shared/api/types.ts`、`pages/ops-v21-task-manual-tab.tsx`、`pages/ops-v21-task-auto-tab.tsx`的能力选项/编辑回填/提交体 | 请求类型、用途选项、条件日期控件及提交体同步；精确撤回必须让运营看见完整键，不用隐藏默认值产生删除；条件列表仍由后端能力响应产生 |
| 行情API及指标 | `biz/api/quote.py`、`biz/queries/quote_query_service.py`的主查询、older date及指标调用；`tests/web/test_quote_api.py` | 结构/复权选项不变，直接读取唯一周期Serving；不增加Raw去重SQL。当前Wealth股票详情另走日线后端，见下文，不为本任务增加该页面周/月能力 |
| 测试与开发模板 | `docs/templates/dataset-development-template.md`、现有resolver/周线/Quote/Ops测试 | 公共合同新增字段同次校准模板；新功能用13.19正反样本，不改旧测试来掩盖差异 |

上表是已核位置和拟改边界，不代表每个动态消费者已经实现或通过。workflow当前会复制步骤参数后重新构造请求，自动化前端当前会由能力响应生成条件选项并在编辑时回填；实施时须验证新增意图不丢失、内部条件不出现在无关动作。实现前须复制填写两条数据集开发说明；共同事实按模板“单处维护与引用”引用本节明确条目，各自差异列清，禁止两份文档各维护一套日期/预算。没有模板及消费者审计闭合，不进入该合同编码。

旧`stock_weekly_adj_*`实现清退前，重新做全部符号/字符串引用、bootstrap/修订入口及历史交付查询审计。保留历史读取不等于保留旧执行兜底；旧未完批次在生产切换前先办结或经明确方案交接，本次文档不替它修改状态。

已补查实际行情前端边界：`wealth/src/features/stock-detail/api/stockDetailApiClient.ts`请求`/api/v1/wealth/market/stock-detail/kline`，类型只允许period=day；后端`stock_detail.py`委托StockDailyKlineBackend，`stock_daily_kline_calculations.py`明确拒绝非day。它当前不是本复权周/月Serving的直接消费者，本次不新增股票详情周/月界面，也不以该页日线通过证明周/月链通过。已确认的周/月读取验收以Quote API及其实际查询/指标为准，运营表单仍须浏览器验证。

### 13.19 需求到测试与真实验收对应

下列新测试文件名为实施安排，尚未创建或运行。实现时按本阶段需要增加测试，不把全部生产验证放到最后；原有测试保留适用部分，冲突先核事实。

| 编号/阶段 | 后端权威位置与正向测试 | 必须能抓到的反例 | 真实边界/表单路径 |
| --- | --- | --- | --- |
| 1 / 阶段2 当期日期 | resolver/builder；拟`test_stock_period_adj_plan.py`：11月10日生成周13日/月30日 | D当P、在Ops算P、原point规则被放宽、business_date与区间并传、非本数据集接受该意图 | 检查真实出站参数；手动页切换当期/周期用途，控件及提交体对应 |
| 2 / 阶段2 源齐备 | 输入读取/预检；拟`test_stock_period_adj_readiness.py`：新股、盘中停牌必有，全日停牌合法缺席；11月9日任务于10日接受end_date=10日，明确周期补齐接受合法更晚日期 | 同数换码、重复、未达到最低日期、真正晚于执行日、正式下载相对预检改变、将0停牌当未知；反例必须抓住把合法较新回包按原D相等要求拒绝 | 生产者schema及必要有界样本；隔离完整源捕获再验，保留原目标日和源实际日期，不能改写end_date |
| 3 / 阶段2 整行选择 | Raw DAO/统一publisher；拟`test_stock_period_adj_publish.py`：13.5字面样本2→2→1；独立样本中28日计算截至日期较新就选28日，审计仍认所属月 | 最大end_date同值异价、NULL差异、混字段、按源trade_date强选或改名；真正缺少某月仍应识别，不能因周期归一化漏报 | 用本节真实21列样本验证映射；隔离PostgreSQL唯一索引、日期/对象审计及Quote读取共同验收 |
| 4 / 阶段2 较新保护 | 条件upsert与实际数据库事务：日期前进、跨次相同日期合法修订可更新 | 旧源晚到覆盖新源、同次同键异值被最后页覆盖、缺席被删除 | 两个数据库连接交错提交，正式writer与人工Serving发布共用锁 |
| 5 / 阶段3 自动历史 | 复权因子比较、依赖Probe及两频计划；拟`test_stock_period_adj_history.py`：相邻开市日变化、零变化、因子晚到；首次名单A/B同时形成两频冻结计划，后续任务不重新比较因子 | 未实际查询就报0、新股首现当除权、只比首尾、第二频改取A/C、只冻一频、单频完成冒充两频、历史失败挡次日当期；0结果后因子到达仍可触发 | 同D两个当前闭合引用+真实因子小样本；隔离PG两连接竞争只留同一对冻结计划，冻结前中断无可执行半对、提交后TaskRun观察失败仍可读回；另一频未入队时按原计划触发；验证出站无日期及两频各自结果 |
| 6 / 阶段3 周期/准确维护 | 规划及统一publisher：本次股票源历史合并、明确全市场周期维护、批准精确键撤回、组合中撤回优先；撤回A两键/B一键形成两个单元，组合下载A/撤回B时B不请求源 | 单股结果冒充全市场完整、因较早源日期强制先补全市场、向其他股票扩展请求、源缺键自动删除、跨freq撤回、股票下载失败仍撤回、遗漏仅撤回股票 | 人工页显示股票和完整撤回键并核实际提交体；隔离DB验A提交后取消/退出只续B、重放无重复删除；删除原Serving候选后选剩余最新行，最后候选删空才删Serving，范围外不变 |
| 7 / 阶段2—4 长任务 | executor/业务DAO/worker；拟`test_stock_period_adj_recovery.py`：每个提交可恢复、重放幂等、进度单调 | 事务前取消仍提交、提交后退出被重做、观察失败回滚业务、任务/节点终态不一致 | 隔离正式组件运行—取消—退出—续跑—读回；正式全量前另获准做代表性真实演练 |
| 8 / 阶段2—4 读取/合同 | 既有Quote/Ops测试增加唯一周期的limit/bar_count/older date、前后复权及指标输入 | 上一页/下一页重月漏月、指标仍带重复点、catalog放错日期控件、非本数据集行为改变 | Quote API真实隔离读链；运营创建/编辑表单浏览器验证，后端测试不能代替 |
| 9 / 阶段5 切换 | migration及旧入口引用审计 | 旧月末排程仍写、新旧锁各自放行、改写历史week交付、自动清表 | 先只读核三条排程/从属Probe/在途任务，再按另行批准范围执行并读回；自然日更独立验收 |

完整21字段及DB数值映射见13.23：源`change`在Raw仍为`change`，写入Serving时映射为`change_amount`，其余业务字段同名；日期DATE、价格/change及复权价Numeric(18,4)、量额Numeric(20,4)、涨跌幅Numeric(10,4)，Raw辅助列不属于Tushare合同。测试输入先核真实生产者和字段NULL规则，不能从待测消费者查询反推结构。2→2→1样本只证明合法选择，不证明全市场覆盖或分页；本轮没有把这些拟测项标为通过。

### 13.20 编码前门禁、预算及本轮交付状态

| 门禁 | 当前依据 | 缺失验证及关闭方式 |
| --- | --- | --- |
| 源接口字段及周期日期 | 本地doc365及索引、原DG源实测、本节单股月线21列样本 | 复用仍适用的证据；本接口属于股票行情，复权因子/主数据/停复牌是不同输入，不能混用字段契约 |
| 真实分页 | 13.22两频基线和offset0/1/2均通过，另补逐列内容对比；累计18次connector请求，含两次单股完整历史 | 源基本行为已关闭；6000行边界循环及全市场覆盖仍是实现/生产验收，不能混称已通过 |
| 现有输入结果 | 13.22生产节点/样本及管理员0行决定 | 已定：现有结果直接使用，0就是0；不新增完成记录或额外源捕获 |
| 捕获/SQL/内存预算 | 13.22单股实测、13.24适用条件/数值推导和SQL数量模型已填写 | 实现后对当期/历史在隔离环境测事务、单元资源开销及取消；不新增整进程树内存限制 |
| 计划和记录预算 | 13.15逐单元持久化，13.24明确单元/累计描述/冻结头限制，无全历史行情JSON | 实现后核边界实际字节；冻结前/追加前超限拒绝，不能用截断清单恢复 |
| 并发与存量索引 | 当前PK允许重复周期；13.22/13.26已核PG16.13日期表达式及不可变函数，13.18已列全部写者 | 阶段2已在PG18隔离验证DDL、两个连接并发，按13.28.2不因16/18差异复测；存量重发布及建约束须另有批准执行方案 |
| 配置与消费者 | 13.17来源/作用范围，13.18消费者，13.24具名policy限值及模板已填写 | 探针当天20:00开始已定，不另做可行性核实；实现时逐项迁移并测试，生产启用另核实际共用源配额 |

性能计算继续用13.9公式。先按代表性真实捕获记录每个单元实际R、载荷字节、末页及耗时；重试与取消后重抓只计未提交单元；最后验收另外计原计划及结果记录、有界Raw/Serving读回、整批覆盖和删除残留统计。不把price字段数、两个层写入量或重复读取量冒充独立K线数。定义捕获累计期限、单元事务累计期限、行数/载荷/计划上限后，须证明可中断调用和可见业务进度满足根AGENTS的30秒要求；单条SQL的超时不能代替整个事务累计期限。

超过核定预算时，在本单元任何业务写入前以明确错误停止；事务累计超时则回滚当前单元，原提交保留。不得自动扩限、缩字段、换旧股票代码、截断分页、部分发布全市场周期或静默拆换原范围。新错误/原因在`ingestion/codebook.py`同次登记，已有源未齐是等待原因，不能混成写入失败。

本轮已填写两频编码设计、数据集开发说明、硬需求/消费者/测试对应及13.24预算，13.22的真实分页和必要Prod有界样本已核。管理员已定上游0结果直接使用，已移除额外完成证明及范围讨论；本次LLD编写及2026-11-16文档复核完成，不把实现后验收冒充当前已通过。未创建迁移/业务代码/测试，未生产写入、改排程、读取全局明细或改DG；新SQL/内存、浏览器及生产验收均未发生。

<a id="stock-period-verification-plan"></a>
### 13.21 待核实事项的具体计划与可信边界

**2026-11-14补充。** 管理员询问怎样核实、计划是否可靠。此前将编码前源合同核实、实现后性能验收及生产排程启用条件放在同一个“编码前门禁”中不准确，容易形成“代码尚不存在，却要求先实测”的循环；现按下表纠正。此前真实单股样本和原周批完成事实继续有效，不推导为新功能已经通过。

#### 13.21.1 编码前：先复用现有生产依据

| 顺序/对象 | 核实动作与有界范围 | 通过标准 | 不通过时的处理及产物 |
| --- | --- | --- | --- |
| A1 股票主数据/确认身份 | 已读现有生产者、日期/状态字段、映射和有界样本，见13.22 | 唯一来源与业务字段已确认，实际查询结果直接使用 | 0按0，不新增完成表，不重做主数据工程 |
| A2 每日停复牌 | 现有Raw模型/字段/查询及两日计数已核，见13.22 | 按S及timing判定，0行即当日0结果 | 管理员已定，不再区分未下载，不增加表/验证门禁 |
| A3 相邻交易日复权因子 | 相邻日历及实际值来源已核，吉比特变化/平安银行同值样本见13.22 | 采用实际结果计算可比较股票及变化，首次上市不算变化 | 0行按0，无变化保存本次0结果；不追加上游完成证明或本地重算价格 |
| A4 排程口径（已定，移出核实项） | 管理员已明确Prod增加探针、自动任务当天20:00开始，直接按此实现；不再执行独立可行性核实 | 实现按13.17设置本功能当天窗口，不继承公共17:00结束；作为正常实现和测试要求，不是待拍板或编码前核实 | 阶段5只核对旧6/15/14及从属规则的切换范围与在途任务，避免重叠写入；不重新讨论已定开始时间 |

A1—A3已按13.22核实实际来源，管理员随后明确0行直接按0使用，不新增完成证明。当前不再以这些输入缺少完整批次元数据阻断设计/编码。闭合周期所需现有日期/对象仍按实际数据处理，不增加上游历史完成表。

已核的Prod工程代码行为：公共配置的默认结束时间是17:00，并非没有默认值。`ScheduleAutomationCapabilityResolver._resolve_probe_window`保存配置时会把空end补成17:00；只有运行时实际读到空end，`ProbeRuntimeService._in_window`才按当天结束处理。先前“20:00—次日17:00”说的是只改开始、不处理默认结束时可能形成的配置，并未证明线上已有任务这样运行。管理员已要求直接采用20:00探测口径，本处保留为实现说明，不再要求单独核实或等待批准。新功能显式设置当天窗口，换日后不将新回包作为旧日快照；本次仍不修改生产配置。

#### 13.21.2 编码前：最小真实源验证

使用项目现有有界connector及完整21字段；不经过同步executor/writer，不创建TaskRun，不写Prod。临时调用材料仅在`/private/tmp`，不打印凭据。MCP可用于基线/字段复核，但其不开放limit/offset，不能用MCP代替真实connector分页证明。

当前`TushareHttpClient.call_bounded`的`stock_weekly_adj/v1`响应合同显式只允许`freq=week`，不能直接拿它测month再把本地拒绝误认为源不支持月线。分页核实使用已有通用有界调用分支`response_contract=None`，只据此验字段列、身份/日期键、页数及传输；它不作为复权价格Decimal精度验收。两频正式21列/三列新响应合同在阶段2单独实现、独立验证，不修改旧week合同来运行审计。执行审计前必须列出实际使用的超时、响应大小、页数与行数守卫；B3超过已列范围即停止并报告，不自动扩读，也不将审计停止上限当新Prod性能保证。

| 验证 | 参数及请求量依据 | 通过标准与限制 |
| --- | --- | --- |
| B1 月线分页 | `000001.SZ,month,20200201—20200229`；先取范围基线，若仍为两条，再依次`limit=1,offset=0/1/2`；正常共4次 | 两个单行页原键不同、并集等于基线两键，第3页为空；检查实际出站参数及21字段。比较键集合而非假设源返回排序；源基线变化或参数无效则停止复核，不修改expected迎合回包 |
| B2 周线分页 | 同股、覆盖2026-11-06/13两个周坐标的小范围，同样基线+三个offset查询；基线确认两条时正常4次 | 同B1，证明freq=week的真实分页。若基线并非两条，不继续套用固定offset断言，也不扩大为无对象全市场查询 |
| B3 单股完整历史 | 同股分别传`ts_code+freq`，不传任何时间；每频按6000页及短/空末页终止，实际请求量为`floor(R_f/6000)+1` | 核出站无日期、字段完整、原键及冲突、实际起止周期、页尾和实际行数；记录时间、响应字节和捕获内存。单股历史读取有界，不证明全市场每只股票都具有相同行数或耗时 |

B1+B2基线均满足两行时是8次请求，B3另按两频真实行数计算，重试单列；不预先写死整个核实耗时。沿已有有界调用的超时/取消能力执行，失败或配额不足停止相应项，不自动循环打接口。B1/B2证明limit/offset基本行为，不能单凭小样本宣称已经做过6000行跨页生产验收；分页循环的边界在实现后测试，首次实际跨页按正式验收范围验证。

#### 13.21.3 编码前：设计预算与已定排程

1. 源端设计预算以既有有效实测、B1—B3及必要统计计数推导：两频预检/正式请求分别计页，变化K股产生每频K个历史源单元；不把一只样本耗时直接乘全市场后称为实测，也不任意乘余量。
2. 数据库预算按13.15列出每个单元Raw合并、Raw候选读取、Serving范围替换、读回和业务事实追加的SQL/行数；确认只有一个单元常驻、事务短且累计超时可中断。新SQL实际耗时尚未产生时写明推导依据及实现后验收方法，不填虚构实测值。
3. 续跑预算只包含原未提交单元重新抓取及原完成事实核对；最终验收另计受影响Raw/Serving读回、覆盖和删除残留。已有guard能否复用须查真正调用语义，不能只复制旧12000行等数值作为新保证。
4. Prod自动任务当天20:00开始探测已由管理员明确，直接按13.17落实，不再独立核实排程可行性。检查间隔沿DG60秒设计，窗口限定当天，不继承公共17:00结束。源请求量/限流上限及拒绝策略属于请求预算，独立保留，不能借此重新打开已定排程口径。

本阶段产物是A/B项证据及13.24预算表，逐项区分“已核”“按管理员0行口径使用”“源实测与设计冲突”。没有证据的项目不能填通过；有已验收生产合同则直接复用，不重复全市场验收。确需新源全市场明细、全局比对或历史扫描时，先说明必要性、准确范围和预计开销，取得批准后执行，不能拆批绕过。

#### 13.21.4 实现后及生产启用前：验证新代码

阶段2—4使用现有隔离资源及按真实schema构造的样本：验证13.19的输入、分页、整行选择、较新保护、并发锁、事务回滚、运行—取消—退出—续跑—读回及观察失败隔离；同时测新SQL、内存和实际耗时，更新设计预算。原代码和文档不能替代对新代码的验收，也不能把测试尚未执行误写成源合同未知。

阶段5才做批准范围内的真实全市场当前周期、代表性变化股票两频历史、迁移/排程切换和自然日更。上游等待顺序、实际缺失股票及源变动需真实验收；隔离样本和小范围分页结果不能证明所有生产日期、股票均齐备。发现超预算或合同冲突，先改回原设计并复审，不自动放宽。

**核实是否可靠的判断标准：** 每项都有固定对象/日期/代码来源、独立预期、通过/失败标准和停止点，不能以无限观察、全量重扫或不断增加门禁代替结论。本节为核实前计划；本轮B1—B3及必要Prod只读查询已经完成，结果以13.22为准，没有生产写入。管理员已决定0结果直接使用，额外完成证明方案已撤回，不再保留此项待决定门禁。

### 13.22 2026-11-14真实核验结果及2026-11-15输入口径决定

本节是13.21核实计划的实际结果，不再把B1—B3写作未执行。源码、Prod只读及真实connector分别取证；没有运行同步、DDL、全局明细读取或生产写入。

**源分页和单股完整历史已核实。** 使用现有`TushareSourceConnector.call_bounded(response_contract=None)`、完整21字段，仅查询`000001.SZ`。本地源文档为doc365，索引条目一致；MCP再次复核2020年2月两条完整月线。项目connector实际请求如下：

| 请求 | 返回与末页 | 单次调用实测 | 结论 |
| --- | --- | --- | --- |
| month，20200201—20200229，limit6000/offset0基线，再limit1/offset0、1、2 | 2；1、1、0，原键并集一致 | 396、311、278、265毫秒 | 月线limit/offset基本行为通过 |
| week，20261106—20261113，同样基线与三个offset | 2；1、1、0，原键并集一致 | 258、269、633、338毫秒 | 周线limit/offset基本行为通过 |
| week，仅股票+频率及分页，不传日期 | 1,786行/1,786原键，首个6000页为短页；19910405—20261113 | 372毫秒 | 单股周线完整历史请求通过 |
| month，仅股票+频率及分页，不传日期 | 428行/428原键，首个6000页为短页；19910430—20261130 | 676毫秒 | 单股月线完整历史请求通过，包含形成中的11月 |

合计10次请求。两频完整历史在generic connector解码后重新JSON序列化的大小分别631,878、152,501字节；这是样本序列化体积，不是网络响应字节或正式Decimal捕获内存。审计父进程峰值RSS为81,084,416字节，不含子进程，不能作为新执行器整棵进程树的内存证明。沿旧已核传输守卫20秒/响应8MiB及审计3页/12,000行停止界限执行，未扩限；这些审计限值不自动成为新Prod预算。小范围验证不冒充6000行生产跨页验收或全市场容量证明。

2026-11-15补做同两个小范围的8次请求，将两个单行页按原键合并，并逐列比较generic解码的21字段内容与该轮2行基线，均一致；不是仅比行数/键。没有重抓完整历史或扩大对象/日期范围。累计项目connector18次只读请求，另有两次MCP字段/单点复核；generic数值一致性仍不替代正式Decimal精度验收。

**Prod实际输入和生产者已定位。** 通过既有SSH在强制READ ONLY事务、10秒SQL限时内取样。服务器PostgreSQL为16.13。只读两只股票的基础身份及两日复权因子、一个北交所映射，其他业务只统计计数；任务证据按三个依赖各最近两条节点查询。

| 对象 | 实际证据 | 能证明/不能证明 |
| --- | --- | --- |
| 股票主数据 | 任务19489、19343各4/4unit，5,923行、0拒绝；另有工作流节点32093于11月13日20:00完成5,923行。Raw现有L=5,579、D=346 | 确有每天完整来源状态展开的任务；计数及TaskRun成功不能充当不可变业务完成事实 |
| 每日复权因子 | 节点32127/32047均为11月13日，5,584行、0拒绝；11月12/13日目标表各5,584行 | 数据由工作流节点写入，不能只查独立resource_key任务；原先查不到对应独立TaskRun不代表当天没有同步 |
| 因子变化金样本 | 603444.SH：11月12日1.41680000、13日1.44220000；000001.SZ两日均142.06990000 | 分别作为变化/无变化独立字面样本，不据此推算整个市场变化数量 |
| 每日停复牌 | 节点32135/32055均为11月13日，8行、0拒绝；12日计7条S、13日计8条S | 当日生产已发生；不能证明“某未来日0条”怎样形成可消费的完整业务事实 |
| 确认代码映射 | `832000.BJ→920000.BJ`，安徽凤凰，来源表list_date为2020-12-23 | 可以复用Prod自己的映射；不推断所有北交所映射都已全量验收 |
| 业务完成记录 | 元数据仅发现旧周线交付表及公告同步记录；已核通用接口默认no-op，通用源/标准/Serving写入为upsert | 仅记录现状，不据元数据名称声称不存在其他系统；按下述管理员决定，本设计不要求上游提供完整批次或合法空结果引用 |

工作流的`TaskRun.resource_key`可能为空，实际目标来自`request_payload_json.target_key`，节点才带dataset key。今后核上游必须沿节点和真实生产者，不能重复使用只按父resource_key检索的错误办法。该次检索遗漏已通过节点查询纠正。

**管理员2026-11-15决定及最终处理：0行就是当天已下载完毕且结果为0，不做额外新增开发。** 据此撤销给三个生产者追加完成事实、或由本功能额外向源抓依赖的建议。不会创建stock_period_adj_input_completion，不改stock_basic/adj_factor/suspend_d的Definition、生产提交或调度。13.16改为直接读取现有业务数据；该事项已定，不再是待讨论或编码门禁。

前述TaskRun/node和表元数据查询只作为理解当前链路的证据；不能由未见完成记录推导出必须增加开发。此前扩展成新增上游完成表的建议超过管理员期望，现已撤回。两频自身的执行计划/unit/交付记录属于原方案可恢复执行设计，继续保留，不与上游新增完成记录混同。

### 13.23 字段、响应、表单及错误合同的编码规定

两条数据集使用同一完整源字段合同；下表同时是两个开发说明0.3.3的引用事实。源文档doc365、Definition及本轮MCP/connector的21列已逐列对账。业务列均已存在，不新建行情字段；新增业务记录及索引另按13.15迁移。

| 源字段（按源顺序） | 源/归一化类型 | Raw列 / Serving列 | 业务及NULL规则 |
| --- | --- | --- | --- |
| ts_code | string | ts_code / ts_code，VARCHAR(16) | 非空，源身份及Raw键；合法格式为6位代码+交易所，确认映射后请求有效代码，Raw不改名 |
| trade_date | YYYYMMDD→DATE | trade_date / trade_date | 非空，源原日期及Raw键，Serving保留被选日期 |
| end_date | YYYYMMDD→DATE | end_date / end_date | 存量schema可空；新源必须为合法非空计算截至日，不补值 |
| freq | string | freq / freq，VARCHAR(8) | 非空，week/month；与dataset身份一致，Raw键组成部分 |
| open | float/decimal→Decimal | open / open，NUMERIC(18,4) | 保留源NULL/精度 |
| high | float/decimal→Decimal | high / high，NUMERIC(18,4) | 同上 |
| low | float/decimal→Decimal | low / low，NUMERIC(18,4) | 同上 |
| close | float/decimal→Decimal | close / close，NUMERIC(18,4) | 同上，不本地推导复权价 |
| pre_close | float/decimal→Decimal | pre_close / pre_close，NUMERIC(18,4) | 源除权参考值，不替换为前一周期收盘 |
| open_qfq | float/decimal→Decimal | open_qfq / open_qfq，NUMERIC(18,4) | 源前复权开盘价，NULL保留 |
| high_qfq | float/decimal→Decimal | high_qfq / high_qfq，NUMERIC(18,4) | 源前复权最高价，NULL保留 |
| low_qfq | float/decimal→Decimal | low_qfq / low_qfq，NUMERIC(18,4) | 源前复权最低价，NULL保留 |
| close_qfq | float/decimal→Decimal | close_qfq / close_qfq，NUMERIC(18,4) | 源前复权收盘价，NULL保留 |
| open_hfq | float/decimal→Decimal | open_hfq / open_hfq，NUMERIC(18,4) | 源后复权开盘价，NULL保留 |
| high_hfq | float/decimal→Decimal | high_hfq / high_hfq，NUMERIC(18,4) | 源后复权最高价，NULL保留 |
| low_hfq | float/decimal→Decimal | low_hfq / low_hfq，NUMERIC(18,4) | 源后复权最低价，NULL保留 |
| close_hfq | float/decimal→Decimal | close_hfq / close_hfq，NUMERIC(18,4) | 源后复权收盘价，NULL保留 |
| vol | float/decimal→Decimal | vol / vol，NUMERIC(20,4) | 源成交量单位及NULL保留 |
| amount | float/decimal→Decimal | amount / amount，NUMERIC(20,4) | 源成交额单位及NULL保留 |
| change | float/decimal→Decimal | **change / change_amount**，NUMERIC(18,4) | Raw不改名，Serving沿现有row transform映射 |
| pct_chg | float/decimal→Decimal | pct_chg / pct_chg，NUMERIC(10,4) | 源涨跌幅定义及NULL保留 |

正式响应拟新增`stock_period_adj/v1`，两频共用，只接受`stk_week_month_adj`及冻结freq；完整下载固定上述21列，预检使用独立三列合同。JSON先以Decimal解码再校验，不允许先经binary float再伪称精度保留；未知/缺/重复列、列宽错误和错误freq均拒绝当前捕获。旧`stock_weekly_adj/v1`保持历史合同不扩义，切换后活动两频均使用新合同；generic分支仅作本轮分页核实证据，不作为新业务写入合同。

三列合同标识为`stock_period_adj_readiness/v1`，仅ts_code/trade_date/end_date，freq由冻结请求指定。正式当期覆盖检查先在原始完整捕获上识别代码重复，不能先去重后掩盖重复；股票历史的同原键同值可以去重并分别计数，同次异值拒绝。两频source_fields引用同一完整字段常量，新`StockPeriodAdjExecutionPolicy`统一维护预算；Definition/计划的page_limit、max_rows、max_units从该policy投影，禁止两条定义/页面各写一套不一致值。

**Definition和维护意图。** date_model的周五/月末桶、observed_field及审计适用性不变；`business_date`是具名维护意图的执行输入，不把行情事实轴改成每日一根。`input_model.time_fields`增加business_date，新的policy声明13.14各意图的time mode/日期字段/代码与撤回键要求。action支持的时间模式为意图模式并集，但resolver必须按kind检查组合；没有kind时只代表原`period`意图，不能因union含none而允许无范围普通维护。新内部factor_history不进入公开手动选项。

拟在手动动作能力响应增加`maintenance_intents`，每项包含kind、中文名称、说明和该用途time_form及必要输入描述，数据来自Definition的具名能力；原顶层time_form仍描述默认period。手动请求`maintenance_intent`为有明确kind的结构，stock_codes为代码数组，remove_keys为三键对象数组；未知kind/混合freq/重复异值/日期混传在后端拒绝。不能把运营意图作为Tushare参数，不能让前端按dataset字符串自己猜模式。

current_period复用现有交易日控件，设置`date_field=business_date`，不必发明新日期控件类型。手动页当前point分支只识别ann_date，其余硬写trade_date；该分支和`OpsManualActionTaskRunRequest.time_input`必须显式增加business_date，恢复/工作流复制也同次迁移。允许的请求例为`time_input={mode:point,business_date:2026-11-10},maintenance_intent={kind:current_period}`；完整历史例为`time_input={mode:none},maintenance_intent={kind:stock_history,stock_codes:[000001.SZ]}`。原filters.ts_code保持单值，只用于默认period；与新意图stock_codes重复给范围必须拒绝，不定义字段优先级。

运营手动页选择“当前周期更新”后显示业务交易日；选择“指定周期维护”显示原周五/月末及范围；选择“股票完整历史”显示股票列表且隐藏日期；撤回/组合维护显示完整原键供核对。切换用途清除不适用字段，提交体与显示一致；浏览器路径分别验创建、切换及实际提交。自动页只给两个本功能动作展示对应探针，固定20:00—次日00:00及60秒，不显示股票过滤或固定历史日期；其他动作选项保持现状。

**结构化错误。** 在`ingestion/codebook.py`登记本功能独立code前缀`stock_period_adj`：`input_not_ready/source_not_ready`表示等待；`input_changed/source_schema_invalid/source_key_conflict/source_scope_invalid/latest_version_conflict`表示冻结依据或源合同不符；`writer_busy/source_deadline_exceeded/business_deadline_exceeded/row_budget_exceeded/plan_budget_exceeded`分别对应资源边界；`resume_contract_mismatch`拒绝改范围恢复。错误展示具体股票、周期、字段、原D及失败步骤，完整大名单存原业务范围而非截断错误JSON；不能记录token或把HTTP错误记作空数据成功。

上述等待码不用于把现有上游查询0行改称下载未知；已定0结果直接使用。摘要用于保存和恢复本次范围，不把fetched_at、观察状态或运行当天的全市场因子变化作为拒绝人工补数的条件；同一次自动周、月回刷复用原变化名单，人工任务各自使用明确范围，源记录仍执行已定的身份、范围及较新记录规则。

### 13.24 数值预算、SQL成本和续跑成本

以下是本次新policy的初始执行限制设计，来源逐项说明，不作为已实现性能保证。沿现有weekly已使用的传输、单元和计划限制，适用条件已重新核对：相同接口/21字段/Decimal精度，两个freq同样分页；本轮实际周/月完整历史均小于单页。它们不是将旧week交付的全批行情归档合同搬给month。

| 项目 | 设计值/公式 | 依据及超限动作 |
| --- | --- | --- |
| 单页/单元源上限 | 每页6000行；每单元最多12000源行、最多3页 | page来自接口及实测；后两项沿现有WeeklyAdjExecutionPolicy，3页容纳两满页加空末页。未见末页/行数超限拒绝，不按返回前12000条发布 |
| 单次传输及重试 | 每次真实调用20秒、响应8MiB；不自动重试/重定向；并发1 | 现有有界client和weekly policy，源失败结束当前任务，恢复重抓未提交单元；不把所有页重新获得20秒说成单元总共20秒 |
| 规范化行载荷 | 单元canonical payload上限8MiB | 代码精度推导：合法9字符代码、两个10字符DATE序列化文本、最长month、14个NUMERIC(18,4)、2个NUMERIC(20,4)、1个NUMERIC(10,4)，最大完整行对象637字节；12000行数组为12000×638+1=7,656,001字节，含rows对象为7,656,010字节，小于8,388,608字节。NULL更短；超schema精度拒绝，不舍入掩盖。2026-11-16补阶段5时纠正：原推导误把本地DATE的ISO文本按源接口8字符计算，原633字节及其数组数值错误；实际8MiB校验未变，也不放宽限制 |
| 原计划范围 | 最多1000源/维护单元，所有plan_unit描述累计及冻结头分别不超过1MiB | 沿旧week计划限制，计划只存请求/键/摘要，不存完整源行情；超限在冻结前拒绝整个计划，明确名单规模，不静默截断或自动另起不同范围。此限制是运行上限，不保证任意规模自动意图都能完成 |
| SQL批量参数 | 128行一块；受影响候选按股票及自然周期读取 | 沿现有`SOURCE_ROW_BLOCK_SIZE`的分块方式；不逐股重复扫描全表，不借128推导出新对象池或source分页 |
| 事务/锁 | 单元业务事务累计20秒，锁等待不超过2秒 | 现有有界事务/锁限制；SQL逐条使用剩余累计期限，不每条重置20秒；超限回滚该unit，已提交unit保留 |
| 取消/可见进度 | 源控制轮询2秒、业务进度间隔5秒 | 沿weekly控制值。每页/每unit前后检查取消；SQL不可分割步骤最多占剩余20秒，不能声称端到端取消固定2秒；5秒可见更新设计满足根30秒要求，业务完成量仅在提交后增加 |
| 观察写入 | 独立连接、原2秒限制 | 沿旧weekly观察隔离；失败不得回滚业务或成为恢复依据 |
| 全批行情载荷 | 不保存旧式256MiB完整行情归档 | 新业务事实仅保存范围、键/摘要、计数；内存始终单unit。批次请求量以原单元数和实际页数计算，不把过去归档上限当新批内存 |

同次自动历史的两份计划各自检查上述1000单元及1MiB描述/冻结头限制，逐批保存草稿；两条冻结头沿累计20秒事务一次提交，不提高现有限值。变化股票数为K时，每频K个源单元、两频合计2K个，源请求量仍按各单元实际分页相加，不因计划共同冻结而下载两次同频历史。规划中断重做尚未冻结的计划；冻结后恢复只读对应原计划、单元及提交事实，不重新扫描因子或已提交股票行情。纯撤回源请求数为0，单元数为指定键涉及的股票数；组合维护按两份股票名单的并集计单元，只给下载名单中的股票计算源页数。撤回验收另计指定键残留和受影响周期候选/Serving读回，不增加全表比对。

源调用上界按有源请求的实际单元U：每个最多3次，故正式调用不超过3U；无错误情况下精确值为这些单元各`floor(R_i/6000)+1`之和，纯撤回不计源页。单元最多3×20=60秒源传输，再加20秒业务事务；这只是在相关deadline均正确应用时的执行上界推导，未含配额排队、进程调度及观察开销，不能当任务ETA。任一页失败即停，不先跑完整U再汇报。配额排队每2秒检查取消、每5秒报告等待，不产生业务完成进度。

本地当前Settings的调用速率为每接口280次/分钟（来源配置项`TUSHARE_MAX_CALLS_PER_MINUTE`，非平台授予配额证明）；新客户端复用既有limiter。20:00—24:00、60秒间隔在未齐且每次只需一页时，两频最多2×240=480次预检；实际有多页则按页累加，任务成功后对应频率当期预检停止。不同进程/其他任务共用token的实际可用配额仍属生产启用时核对，不改变20:00口径；限流错误保留等待/失败原因，不无限自动重试。

**数据库数量模型。** 对当前unit，源唯一键R、相对现库新增/更新A、较新保护H、受影响股票/周期组G、原Serving命中S、选中T分开计数。Raw候选查询只覆盖这些组；每组最多一条Serving。Raw写入按`ceil(A/128)`块，Serving删除按精确组、插入按`ceil(T/128)`块，读回分别覆盖Raw原键及G组，追加1条unit事实；组范围用有界values/参数块组合，不每一字段各发SQL。既有Raw缺席键保留，选中T小于R不是reject。G内读取的旧候选数由本次股票周期范围及数据库实际行数决定，须在事务中计入行/字节上限，不能以新回包R代替旧候选扫描量。

**正常、失败和恢复分别核算。** 本轮两频单股样本网络调用实测372+676=1048毫秒，仅适用于这只股票、这次数据和这台客户端，不乘K后称为全市场实测。恢复先读原计划及已提交unit键/摘要，逐未提交单元重新捕获，完成单元不再请求源；尚未提交的最后捕获可能重复，按原guard计入。最后验收另算原unit/闭合对账、受影响Raw/Serving键读回及逐股覆盖；准确撤回另核原键残留。两层写入量不合称独立K线数量。

Source schema及payload边界现在有真实依据；新SQL耗时和单元实际资源开销在实现后核验。本次按管理员决定删除新增的整进程树256MiB硬限制、RSS监控及对应memory_limit拒绝分支；不引入替代内存限值或控制器。现有分页、单元行数、载荷和短事务边界继续使用。明确周期维护或准确撤回的正式执行，按获准周期/股票范围形成执行计划和数量预算；不默认初始化全市场历史，本LLD不授权直接全历史读取或执行。

### 13.25 实现位置、函数职责与阶段交付

| 拟实现位置 | 负责的工作与调用方向 |
| --- | --- |
| `datasets/stock_period_adj_contracts.py` | 两频源21列、三列预检、policy、canonical/摘要、同键冲突及维护意图数据类型；保持Foundation内聚，不import旧week业务执行器 |
| `ingestion/stock_period_adj_inputs.py` | 13.16的输入读取、当前/闭合周期预期集合、身份映射、相邻因子变化及版本核对；按13.16直接用现有业务结果，0按0；不增加上游完成记录或读TaskRun作为输入 |
| `ingestion/stock_period_adj_planning.py` | 归一化D→P、冻结manifest；自动历史先读取同D已冻计划，否则比较一次因子、分别生成并共同冻结两频计划；准确撤回按股/频率分组，组合取股票并集；恢复原manifest，不重新解释请求 |
| `ingestion/stock_period_adj_execution.py` | 当前unit捕获、资源/取消控制、调用共同publisher、业务进度及整批闭合；TaskRun只做外围装配/观察 |
| `ingestion/stock_period_adj_delivery.py`及两层DAO | 频率事务锁、Raw较新保护、精确撤回、Raw候选选择、Serving精确替换/读回及不可变unit事实 |
| `models/core/stock_period_adj_delivery.py`、业务DAO及Alembic | 13.15字段、部分唯一索引和不可变约束；同DAO保存/读取分频计划及同事务冻结自动两频计划，不新增共享名单表；注册模型、DAOFactory；创建迁移前查真实head。仅新增事实/索引，不清表 |
| `clients/tushare_client.py`、`bounded_tushare_call.py`、source_client | 新两频21列/三列响应合同、Decimal解码、真实分页及有界调用；旧week合同不扩义，不改其他接口 |
| `serving/publish_service.py`及两个现有Serving builder | 统一经过共同publisher；人工重发布也以Raw完整候选为依据，不直接对三键upsert、不保留源优先级覆盖最新截至日的旧规则 |
| Ops schema/query/service、dispatcher/worker及app装配 | 13.14/13.23结构、冻结传递、恢复和两类Probe；无源参数生成、无D→P计算、无第二状态机 |
| 前端手动/自动/详情页及API types | 展示后端用途及时间控件、固定探针窗口和原范围进度；Quote消费结构不变，按唯一周期Serving回归分页/指标 |

阶段1交付是本LLD、两个按模板填写的开发说明、真实证据与需拍板项；不是测试和上线完成。阶段2必须一次打通新合同→输入→Probe→捕获→Raw/Serving→任务观察及对应隔离测试，不能先上日更后补整行选择。阶段3增加独立历史、周期补齐和准确维护；各自先完善本阶段执行/测试范围再开发。阶段4做正式组件隔离串联，阶段5按准确授权范围执行生产迁移、存量重发布、最小真实验收及自然运行验收，不默认增加全市场历史初始化。

本节所称后台执行程序是Prod当前已有的`src/ops/runtime/worker.py:OperationsWorker`。现有`ops-worker-serve`入口由`scripts/goldenshare-ops-worker.service`启动，`src/app/runtime/ops_worker_factory.py:build_operations_worker`装配现有dispatcher，再进入Foundation的数据维护执行链。本次复用这些设施、现有探针、TaskRun和PostgreSQL，不引入DG的Dagster运行环境、文件式交付、Worker、队列或新服务。DG只提供业务处理规则的参照。

受理仍沿原TaskRun创建API保存明确意图；本功能可能较长的计划生成由worker进入“生成计划”阶段后调用Foundation，草稿逐批持久化、完整核对后冻结，冻结前不得写Raw/Serving。受理响应结构不变，计划/总量在规划完成后回填；其他数据集流程不改。未冻结草稿中断后可按原意图重新规划，使用新的草稿批次，不混入旧残缺unit；已有plan_frozen则只恢复原范围，不重新计算。观察快照写失败不回滚冻结或行情事实，恢复从本功能业务记录读取，不依赖TaskRun进度。

上述受理/规划调整须同时覆盖Prod现有`ManualActionCommandService._preflight_dataset_action`、`TaskRunCommandService.preflight_dataset_context/_freeze_dataset_execution_payload`、排程受理及dispatcher，不能只改后台执行器而让页面继续重复生成长计划；不为本功能另造通用受理或执行基础设施。当前只明确设计位置，尚未实施入口调整。

Ops关联入口还包括`dataset_action_request_adapter.py`及`TaskRunIngestionContext`：两频具名policy统一沿已有scheduled→schedule转换，TaskRun保留原来源标签，不能在month重新引入旧week已修正的来源不一致；新两频均采用独立取消读取/观察连接及原超时，不让业务session被进度写入提交/回滚。旧week的同步冻结分支不继续作为新执行兜底。

存量切换分三步：先只读确认旧在途批次、唯一排程及旧数据重复周期范围；再按批准范围完成业务记录表迁移和存量Serving选择，异值冲突先解决且Raw保留；最后建立周期唯一约束并一次替换全部写者/排程。失败时保留已提交业务事实，停止未完成切换，不重启旧写者跨过新约束或把失败任务改成功。恢复部署与数据恢复使用逐表范围及必要恢复安排，不引入Kopia、全表清空或双轨兼容执行。

### 13.26 首次历史范围衔接与最终对账

本轮只取`000001.SZ`两频各最早一条Raw：周线2010-01-01、月线2010-01-31；该股Raw分别856、201行。另做纯COUNT确认整个复权Raw表在2010年前week=0、month=0，没有读取全市场明细。源完整历史则分别始于1991-04-05、1991-04-30。

平安银行的样本只证明源完整历史请求会返回2010年前数据，不能据此推导管理员要求Prod扩展到该时期。此前将“缺周期补齐”直接用于现有库存起点之前，并写成“启用自动历史前必须补齐这些全市场周期”，扩大了未经确认的范围，是设计判断错误，现撤回该前置条件。

错误推导过程是：先把“源请求不带日期，会返回较早历史”当成“Prod必须覆盖源端最早日期”，再把“缺周期补齐”套到现有库存起点之前，最后推出“必须先补齐这些周期的全市场记录”。第一步就缺少业务要求和正确性证据，后两步不能据此成立。单股样本没有证明现有2010年起的行情错误，也没有证明扩展历史范围是实现日更或复权因子变化回刷的必要条件。

存储差异已核：DG的`io/stock_period_raw.py:group_history_sources`要求待合并的周期Raw文件存在；Prod使用同一张Raw表，当前ORM主键为股票代码、源日期、频率，写入按业务键合并，没有逐周期物理文件必须预先存在的要求。不能把DG文件合并的前置条件提升成Prod每个历史周期都要全市场完成证明。

本次只按已定范围处理变化或明确指定股票的源历史，合法原键进入该股本频合并与Serving选择，不向其他股票扩展，也不新增2010年过滤。不能据该股记录存在宣布全市场周期完整，不能要求先补全市场或自动创建全市场补齐任务。明确全市场周期维护仍使用单独的人工意图。此前“补到最早”和“固定2010年并另等拍板”两种建议均撤回，不再作为业务待定或编码门禁；既有历史不删。

两频数据集开发说明分别为[股票复权周线](stk-period-bar-adj-week-dataset-development.md)、[股票复权月线](stk-period-bar-adj-month-dataset-development.md)，共同源字段、输入/schema、业务记录、事务、预算及测试口径只引用本原LLD，不复制成两套事实。设计对账如下：

| 已定要求 | 设计位置 | 当前证据/状态 |
| --- | --- | --- |
| 当期每日更新、20:00至次日00:00 | 13.3/13.4/13.14/13.17 | 日期及窗口已定，实际代码入口已查，待实现测试 |
| 每日变化股票两频完整历史、与当期独立 | 13.6/13.14/13.17/13.25 | 单股无日期源已核；相邻两日变化/无变化金样本已取得，待实现 |
| 原键较新保护、同周期整行选择 | 13.5/13.15/13.23 | 真实2→2→1样本及Raw/Serving映射已核；PG16.13日期表达式结果正确且extract(date)/date_mii为immutable，DDL/并发的阶段2隔离验收已完成，见13.28 |
| 平台价格可信、不本地重算或额外找修订 | 13.2/13.13/13.23 | 新执行不复用旧价格基准推导，复权因子只驱动股票名单 |
| 明确周期及准确维护 | 13.6/13.14/13.15 | 单股合并与全市场周期维护分开，范围/事务/恢复及正反测试已写；准确撤回及正式维护均未执行 |
| 可恢复、进度、业务与观察隔离 | 13.8/13.15/13.19/13.24 | 硬限制及最小实际验收方法已写，未宣称新实现性能通过 |
| 不改DG、不加新worker、不绕原合同 | 13.2/13.18/13.25 | 仅文档及有界只读；13.22已撤回扩展上游建议，仍只改两条行情功能 |

文档主体、源核验、预算、消费者及验收对应已经填写，未编码；本轮已按管理员已定口径修正历史范围、日期和人工/自动边界，不再把已定事项列成待拍板或额外门禁。新执行路径及实际性能仍未实现或验收；正式执行范围、全局读取与写入授权继续在各自阶段核定。

2026-11-15文档校验：`python3 scripts/check_docs_integrity.py`通过；本任务五个文档的`git diff --check`通过；四份方案/开发文档的30处本地链接及锚点、两份开发说明的编号章节和最新需求项、9个既有测试路径逐项通过。校验中发现的两处架构测试路径已更正为`tests/architecture/`；这些结果仅证明文档检查完成，不代替拟建代码、测试和生产验收。临时源审计材料的有效参数/结果已写回13.22，过程文件不作为长期附件保留。

### 13.27 管理员已定口径的执行依据

已定事项统一对照[原方案7.10](stock-weekly-adj-refresh-plan-v1.md#stock-period-confirmed-decisions)，不再作为待拍板项。13.4规定最低计算截至日期及跨日恢复，13.5规定完整行选择和日期审计，13.6/13.14区分自动名单与人工明确范围，13.7/13.24记录两项取消，13.25明确Prod现有执行设施，13.26清除全市场历史扩展前置。两频开发说明及相应正反测试要求已同步；业务代码、迁移、正式任务与生产配置尚未修改。

2026-11-16补充复核：前轮剩余的两处执行说明已补齐。13.14明确自动历史由首个worker规划一次形成名单、在13.15原拟建业务表中共同冻结两份分频计划，后续按原D/本频读回，不新增共享名单表、服务或锁；准确撤回及组合维护明确一股本频一个单元、仅撤回股票无源请求、已提交股票不重做。13.19第5/6项同步竞争、退出及剩余候选重选的实际验收例子，13.24分别计规划、下载、撤回及恢复成本，13.25落实到原拟实现文件与DAO。原方案及两频开发说明已同步，未新增业务要求或重开已定问题。

接下来沿原方案7.5依次推进阶段2当期日更、阶段3历史及人工维护、阶段4隔离串联验收、阶段5生产切换与验收；每阶段先核对应设计和代码影响面，阶段结果独立验收。阶段2同时实现业务记录/恢复基础和共同publisher，不能先上线当期再补整行选择；阶段3采用本次已明确的两处步骤。生产迁移、排程和业务写入仍按阶段5的具体范围执行，不因文档补齐自动启动。

2026-11-16文档校验：文档完整性及四份文件的差异格式检查通过；33处本地链接/锚点无错误，两份开发说明各16项需求编号、53项编号章节一致，旧的待整体评审状态及不明确的撤回单元表述已更新。以上仅为文档检查；拟定的业务测试、隔离数据库验证及生产验收尚未执行。

### 13.28 阶段2开发与独立复核记录

2026-11-16管理员授权严格按本LLD开发并完成阶段2，完成后独立审计。范围为当期日更及其共同合同、业务记录/恢复、Raw较新保护、Serving选择、日期审计、任务/探针/运营表单和Quote读取回归；阶段3的自动历史、撤回与组合维护不提前开放，阶段5的正式迁移、排程切换和行情写入不执行。既有period输入含义及其他数据集行为保留。改动仅在当前dev-interface；不安装依赖；管理员已明确忽略PostgreSQL16/18版本差异，无需安装16或重复测试，按现有18隔离结果完成本阶段验收。

| 阶段2硬要求 | 实现位置 | 正向/反向与验收安排 |
| --- | --- | --- |
| REQ-01/02：D与P分开、最低截至日、对象/停牌范围 | 新contracts/inputs/planning，resolver及builder | 两频周中/月中、跨日较新通过；旧日期、缺码、同数换码、重复、日期混传拒绝；0输入直接使用 |
| REQ-03/03a—d：固定窗口、意图、防重及从属绑定 | capability/binding/runtime、任务受理、自动表单 | 20:00可检查，19:59和次日00:00不请求源；禁止股票过滤/固定日期，暂停无遗留规则；阶段2仅开放已实现当期条件 |
| REQ-04：21字段/三列分开、Decimal、真实分页 | client/source及新contracts | 复用13.22源边界证据；按真实schema造独立字面夹具；缺列、错误频率、精度损失、满页无末页失败 |
| REQ-05：较新保护、原键保留、同期整行 | 新delivery/DAO、共同publisher、全部Serving入口 | 2→2→1、28日较新选28日、同截至日跨次修订允许；旧源覆盖、同次异值、混字段失败；PG事务/锁/索引读回 |
| REQ-10/13：逐单元提交/恢复、取消、观测隔离及0 | 新业务记录/执行、现有worker与TaskRun上下文 | 运行—取消—退出—续跑—读回、重放、单调进度、观察失败、TaskRun/节点一致；0不要求上游完成表 |
| REQ-11：唯一周期读取、分页、指标及日期审计 | Quote主查询/older date、ActualBucketReader、运营表单/API | 两种复权、bar_count/limit/分页及真正缺期；创建/切换表单和实际请求体的浏览器验证 |

执行/内存/事务及恢复预算不改变13.24；生成计划仅逐批持久化描述，冻结前不写行情，逐单元业务提交，Ops观察独立。验收先使用现有依赖、隔离数据库及真实合同样本，不读取全市场生产明细、不启动Prod任务。测试日志和临时数据库统一置于本任务/private/tmp目录；实际测试版本如实记录为PostgreSQL18，按管理员决定忽略16/18差异，不再另做16版本测试。开发完成后逐条独立复核本表与13.19，实测结果及未覆盖边界回填本节，不提前标通过。

阶段2配置复核补充：`ScheduleProbeConfig`受理时先按本功能的condition_kind补齐缺省/空窗口及间隔，值从原Ops具名常量取得，再交现有能力校验和绑定；本功能缺省结束时间为00:00，不能先补公共17:00再拒绝。显式不同值仍按固定配置拒绝，其他condition_kind的公共默认不变。对应API测试覆盖省略配置、固定值冲突及暂停从属规则。

阶段2读取复核补充：原周/月freshness仍比较已结束的自然周期；两数据集观测先排除尚未结束的周期，再把合法源日期归到自然周期，避免未来P或28日日期造成误报。`freshness_note`追加本频最近完整当期业务交付的D，从业务记录读取，沿现有卡片/快照字段展示，不新增日频freshness模型。任务详情继续使用现有`current_object`：生产者填原对象、D/P、阶段、更新时间和未知ETA；查询层形成显示文本，页面对本功能固定显示“暂无法估算”，不能拿观测进度推造倒计时。

阶段2保留原period输入时，输入模块同样按13.16读取该闭合周期各开市日的上市/退市及停牌范围，必需股票取并集、截至要求取各股最后应更新日；当期模式仍按D日名单，全日停牌D可缺席。此为保留已有周期维护的正确范围，不提前开放阶段3的新历史/撤回用途。提交边界复核把取消和累计事务期限的最后检查放在COMMIT之前；COMMIT后先计入已提交单元，再响应取消，不能将已提交单元显示为0完成。

阶段2独立审计补充：通用TaskRun创建API原本允许request_payload透传；本功能手动新建必须拒绝自填execution_context，避免把别批计划贴在新的日期上。显式恢复仍只给原TaskRun ID，既有retry接口沿该ID携带服务器保存的原合同，不改变该接口行为；人工新修订仍形成新计划。对应反例直接经过通用HTTP入口验收，不依赖页面隐藏字段。


#### 13.28.1 阶段2代码与验收对账

本次在dev-interface完成编码后，另按13.19和本节硬要求逐条复读代码、测试夹具依据及数据库读回；审计发现的实现遗漏已在本阶段修正并复验。当前结论是阶段2开发、独立审计及本阶段验收完成。管理员明确忽略PostgreSQL16/18版本差异，现有18隔离结果用于本阶段验收，不安装16或重复测试；实际测试版本仍记为18。第3—5阶段未启动；下列证据不代表Prod已经部署或自然日更通过。

| 要求 | 当前实现与测试证据 | 结论/边界 |
| --- | --- | --- |
| D与P、两频独立、最低截至日及真实日期上限 | `stock_period_adj_planning.py`、`stock_period_adj_execution.py`；`test_stock_period_adj_contracts.py`及`test_stock_period_adj_p2_pg.py`的投影、跨日、代码覆盖、两种完成顺序和预检后源变化 | 必需股票、全日/盘中停牌、新股及0结果已验证；源参数仍由原request builder生成 |
| 21列与三列合同、Decimal及分页 | 新contracts、Tushare bounded client、source client；真实MCP样本夹具、28项合同测试、3项真实loopback传输测试 | 6000/offset6000/offset12000空末页、超限拒绝及不重试已验证；真实平台分页仍复用13.22的有界证据，不称6000条合成样本为全市场真实抓取 |
| Raw较新保护、原键保留及Serving整行 | 新delivery、人工publish service及两个builder；PG月末29/28两行、28日较新、同日平台修订、旧源保护、异值回滚、周期唯一索引及两连接事务锁 | Raw保留2条、Serving按截至日选1整行，change映射正确；人工dry-run不写，正式重发锁内重读Raw |
| 长计划/单元/恢复 | 新planning/业务DAO/execution；草稿取消、提交后退出、原范围恢复、幂等、输入变化、原冻结限制不随新Definition改变、累计SQL期限及提交后取消测试 | 行情和unit事实短事务提交，已提交单元不下载；进度只计真实提交，观察失败不回滚业务 |
| TaskRun受理、恢复和终态 | 原TaskRun service/dispatcher/OperationsWorker；隔离PG运行成功/失败/取消及观察事务失败；通用创建API自填execution_context反例 | 受理不生成长计划；原D/用途不丢；TaskRun/活动node终态及数量一致；恢复只用原范围 |
| Probe与配置 | 本功能probe适配、capability、ScheduleProbeConfig及原binding/runtime；API和PG源预检/活动/已完成防重测试 | 缺省20:00—00:00/60秒，19:59及00:00不查源；另一频独立；阶段2只有当期从属规则，历史规则留阶段3 |
| 读取/日期审计/观测 | ActualBucketReader、freshness query及原Quote读取；真实PG日期归属与Quote前后复权、limit/bar_count、older date和指标读取 | 不在查询层拼Raw；源28日归属原自然月，真缺月仍缺；未来P不冒充已更新到未来，当前完成D另显示。两数据集现行completeness仍为date_bucket，不新增对象审计范围 |
| 前端 | 后端实际manual/catalog响应夹具与生产者逐内容一致；手动/自动/详情及任务中心61项测试；最终构建、app/node TypeScript及前端规则检查 | 浏览器创建、用途切换清空旧值、真实交易日控件、实际提交和原ID恢复、自动固定配置均验证；本次浏览器API为隔离模拟，后端真实事务另由PG验收，不合称生产端到端 |
| 模型、迁移及架构 | 189业务表/不可变触发器，190周期索引；ORM登记及同名索引、DAOFactory；根架构/注册/错误码护栏 | 迁移拆分保持阶段5可先建业务表、批准范围内重发布、再建约束；PG18已实际执行，按管理员决定不因16/18差异重复测试；没有正式迁移 |
| 范围 | 仅两条具名policy和period/current_period；其他数据集、取消的需求及阶段3新用途均复核 | 未修改DG、未扩展上游生产者、未做全市场历史初始化/2010过滤/退市清理/新worker/RSS控制器 |

**测试记录（2026-11-16）。** 集中架构/注册/Serving/日期/freshness/Ops/Quote回归521项通过；随后修正通用受理边界，相关113项复验通过。旧周线合同151项通过，旧测试的weekly_definition明确冻结为历史v1并关闭新的两频policy，活动Definition另断言只绑定新合同，不把旧夹具当当前合同。阶段2PG18测试36项通过，另补原限制恢复测试1项通过，合计37项；3项loopback真实HTTP/子进程传输通过；前端61项通过，两个浏览器场景通过。以上测试集合存在交叉，不相加为互不重叠总数。全量Definition linter通过，前端app/node类型、规则及最终构建通过；构建保留原大包提示，未扩大本任务做打包重构。

**性能实测。** 代表性6000条人工构造股票身份、真实样本价格的单元，canonical行情为2,436,001字节。PG18本机隔离实测：规划0.0589秒，包含归一化/SQL发布/读回的执行5.1516秒，已提交计划重放0.0082秒，最终两表COUNT和unit事实读取0.0019秒；Raw/Serving各6000条，unit事实的源接收/Raw实际写入/Serving选中均6000，拒绝0。该测试替换了源网络，不能据此推算Prod或平台传输耗时；正式分页与网络期限分别由pager/真实loopback验证。取消后只续剩余单元、最后单元重抓、计划读回及闭合对账另有上述测试，不把恢复或验收成本省略。原13.24限制不提高，也不新增RSS上限。

#### 13.28.2 独立审计修正与剩余边界

初版实现中，曾把当期的“源周期日期必须精确等于P”校验用于原period维护，这是错误的，会挡住同月28/29日的合法候选；已按自然周期归属修正，独立字面样本证明两条均可入Raw且28日更晚时整行选28日。另修正了公共探针默认先补17:00、人工重发布计划仍调用旧源优先级、未来周期标签观测、提交后取消漏计已提交单元及通用API能自带执行计划等问题；相应源码和反例已复验。没有用改写源日期、放宽合法回包日期上限、额外完成表或异常吞掉成功来消除问题。

CodeGraph使用search/impact核对DatasetActionResolver、DatasetActionRequest、两个builder及freshness消费者，并完成sync/status。新函数run_stock_period_adj的callers结果为空，继续直接核对executor.run的具名路由、planner/source/publisher、Ops适配和测试，不把图中空结果当无调用。共享请求新增字段均位于原合同，Foundation无Ops/Biz/App反向依赖；Quote仍走原读取。架构快照和数据集开发模板、两频开发说明已同步。没有仍待业务拍板的新问题。

**管理员2026-11-16最终决定：忽略PostgreSQL16/18版本差异，不需要重复测试。** 此决定取消此前提出的16版本隔离复测及安装授权待办；采用已有PostgreSQL18隔离测试结果完成本阶段数据库验收，阶段2开发、独立审计及本阶段验收完成。测试记录仍如实标明实际使用18，没有在16执行，也没有安装/升级包。本次仅按管理员决定更新验收口径和状态，未重复运行功能测试；后续各阶段的新增功能及生产切换仍按原方案分别验收。

本阶段代码、测试及文档一同提交，提交编号以Git历史和交付汇报为准；本次没有部署、启动Prod自动任务、改正式排程、执行生产DDL/重发布，也没有全市场生产明细读取。后续仍按原方案7.5分阶段，阶段3需单独验收再推进。

### 13.29 阶段3开发约束与验收记录

2026-11-16管理员批准按LLD推进阶段3并在完成后独立审计。阶段2已提交`45dc21c96`。本步复用13.6、13.14—13.19、13.23—13.27的完整设计，不重开已定口径，不执行生产迁移、排程切换、正式行情维护或全市场初始化。PostgreSQL16/18差异继续按管理员决定忽略，不因此重复测试。

开工前已用CodeGraph explore/impact/callers与当前代码核对：现有具名policy只开放period/current_period；planner、capture及publisher尚按有周期日期处理；历史出站builder尚不能生成无日期请求；Probe binding目前只生成当期规则，活动查询尚未分用途。上述差异是本阶段明确实现内容，不新增旁路或执行基础设施。核心业务记录、累计短事务、逐unit提交、恢复及整行选择直接扩展阶段2实现，不新增表或迁移。

| 本阶段硬口径 | 实现位置及影响面 | 正反验收 |
| --- | --- | --- |
| 只比较原D及前一开市日现有复权因子；0按0，新股首现不算变化；价格信任源端 | stock_period_adj_inputs.py；只读core.equity_adj_factor、SSE日历及现有股票身份 | 相邻日期/跨周末、两日0行、首现、同值及变化；不使用旧week按整周比较/价格基准推导 |
| 同次自动两频共用首次名单，草稿分别保存，两冻结头同事务；恢复不重新比较 | stock_period_adj_planning.py及原业务DAO；只写原stock_period_adj_delivery | 首次A/B、后到A/C仍读A/B；两连接竞争、冻结前退出、冻结后观察失败；任一频单独恢复 |
| 股票历史只传ts_code/freq和完整21字段，无日期；不扩其他股票、不加2010过滤 | request_builders.py、planner/capture；原source_client和分页限制不变 | 核对实际出站请求；含1991年记录、同周期不同原日期、合法较新截至日；错误身份/频率失败 |
| 人工按明确股票或完整撤回键处理，不重新筛当天复权因子；组合撤回优先 | 具名意图、manual schema/query/service、原TaskRun/dispatcher；运营表单由后端能力驱动 | 无日期历史、纯撤回零下载、下载A/只撤回B；混频、混日期、未知内部用途拒绝；切换用途清空旧输入 |
| 一股本频一个维护unit；Raw合并/精确删除、Serving重选及unit事实同事务 | stock_period_adj_execution.py、stock_period_adj_delivery.py | A提交后取消/退出只续B；当前股源失败不撤回；剩余候选保留、删空才移除Serving；范围外不变 |
| 每频原自动任务绑定当期/历史两规则；历史依赖同D两频当期闭合，按用途/D防重 | 原binding/probe/runtime及配置能力；不公开历史条件，不新增配置源 | 同D两频先后顺序、零结果后晚到变化、暂停/编辑两规则同步；旧历史失败不挡次日当期 |

配置、读写范围和失败规则继续使用13.15—13.17；预算继续使用13.24（每股最多3页/12000行、8MiB，计划1000单元及1MiB，逐unit累计20秒事务），不提升数值。两频共同冻结只提交原先分别写好的草稿的两个冻结头；并发唯一约束失败的一方结束其事务后读回胜出的一对计划，不吞掉其他数据库错误。恢复只读原元数据与已提交unit；最后验收只读本次指定键及受影响股票周期，纯撤回不计源请求。新路径实测单独记录，不把阶段2当期耗时当作历史执行保证。

本步按13.19第5—8项增加历史/撤回单元、真实隔离PostgreSQL事务、Ops受理与Probe、表单及浏览器测试，复用13.22仍适用的真实源完整历史/分页证据和21字段字面样本。开发完成后逐条对账，并另做代码与LLD独立审计；阶段4串联及阶段5生产验收不提前宣称完成。

当前状态：阶段3编码、隔离验收与独立审计完成，符合本阶段LLD要求；本阶段代码、测试和文档一并提交，提交编号以Git历史和交付汇报为准，未进入阶段4或正式生产执行。

实现核对补充：人工用途能力以`input_fields`明确声明`stock_codes/remove_keys`，前端按此显示股票数组及完整撤回三键，不按dataset key猜输入。阶段2的period单股修订检查改用已有Raw自然周期范围，不能因存量源日期为28日而拒绝对该月29日周期坐标的修订；仍不据单股记录宣称全市场完整。规划进度沿原`current_object`合同，历史股票填写`entity.code`，不能把股票代码放进`time.trade_date`。

#### 13.29.1 实现与独立审计结果

本步没有新增表或迁移。Foundation在原contracts/inputs/planning中开放已定用途、读取相邻开市日复权因子并保存分频计划；原业务DAO新增两频冻结计划读取。request builder对单股完整历史只生成`ts_code+freq`。原execution/publisher处理无周期日期的股票单元和无源请求的撤回单元，精确删除、剩余候选重选、读回及unit事实在同一短事务提交。原Ops受理、恢复、Probe binding/runtime及手动表单同次迁移；未修改DG或既有工作流定义，没有让工作流自动加入撤回。

独立审计在功能测试后重新从已定口径核对入口、请求参数、SQL删除条件、两频冻结事务、原计划恢复、观察连接及前端提交体，并补充实际Worker取消/恢复和发布冲突回滚测试。审计发现并修正了四处本次实现/复用细节：自动历史受理校验最初漏传触发来源，误当人工而拒绝；原period单股修订以固定源日期查库存，误挡同月28日记录；规划股票代码最初沿旧回调进入日期显示；复权因子比较循环原先对每只股票查询取消标志，产生不必要的数据库请求。当前已分别传递原来源、按自然周期读取、使用原对象字段显示，并把无I/O的数值比较改为在读取及比较前后检查取消，并有正常/反向样本证明不会重新误拦。审计未发现未解决的阶段3阻塞项。

| 对账项 | 当前代码/测试与证据 | 结果及边界 |
| --- | --- | --- |
| 相邻因子、0结果、新股、首次名单和两频共同冻结 | `stock_period_adj_inputs/planning.py`、原业务DAO；`test_stock_period_adj_p3_pg.py`的相邻日期、A/B→A/C、两连接竞争、两冻结头中途退出、无空批及未入队另一频Probe | 使用真实隔离PostgreSQL，保存同一对计划、原范围恢复；0检查写原ProbeRunLog，晚到变化仍可触发，无上游完成证明扩展 |
| 完整历史、人工明确范围和周期补齐 | builder/capture、Definition与manual query/service；两频无日期、1991年源键、较新保护、BSE确认新码、退市股票明确历史、已有28日周期修订；工作流复制另有直接合同测试 | 完整21字段，源未返旧键不删；不查当天因子筛人工名单，不要求另一频配对，不扩大其他股票或全市场历史 |
| 精确撤回/组合事务和取消恢复 | publisher与原executor；A提交后取消/退出只续B、仅撤回股票不下载、源失败不撤回、撤回优先、剩余候选、最终删空、发布冲突回滚及另一频不受影响 | 删除以完整三键限制；同股Raw/Serving/unit同事务；实际Worker的TaskRun/节点取消、失败和成功终态一致，进度单调，观察失败不回滚业务 |
| 自动配置/防重与表单 | 原binding/runtime、五用途能力及input_fields；同父任务双规则、编辑/暂停同步、用途/D防重、内部用途拒绝、原自动历史人工恢复；接口与浏览器核实际请求 | 20:00—次日00:00、60秒及原限制不变；历史失败/活动不挡另一用途或次日当期；页面显示并提交完整撤回键 |
| CodeGraph及影响面 | 开工及收尾使用explore/impact/callers、sync/status，结合当前源码核对Definition、resolver、builder、DAO、Ops受理/dispatcher/Probe、前端API合同及测试 | Foundation只依赖自身；Quote及原Serving读取合同不变；无新worker/服务、旧执行兜底或DG修改；生产切换仍属阶段5 |

验证结果分别计数，不相加为一组互不重叠的验收：新增阶段3隔离PostgreSQL40项通过（在主验收后补Worker终态、发布回滚/跨频范围及取消查询次数，并对当前代码整组复验）；本机HTTP真实传输4项通过；共同链路改动所需阶段2PostgreSQL37项回归通过；架构/Definition/resolver/字段合同230项及另1项工作流转发通过；手动/Probe接口111项通过；前端43个测试文件167项通过，任务专项浏览器3项、既有流程及截图13项通过，未更新截图。应用与构建配置TypeScript检查、前端规则检查、Vite构建和Definition linter通过。类型检查发现的两处测试代码类型不匹配已改正，未靠跳过或放宽业务断言通过。

本轮源边界复用13.22已核实的完整历史/分页事实及独立21字段字面样本，没有重新全市场下载或请求平台；新增本机HTTP检查实际收到的历史请求只有股票、频率、分页参数和完整字段。数据库为任务独立临时PostgreSQL18，行情输入由真实字面样本和明确的人工日期/代码变体构造；这证明当前SQL和事务实现，不冒充生产真实同步。PostgreSQL版本差异按管理员决定忽略。

#### 13.29.2 本阶段性能实测与后续边界

使用与13.22单股源历史行数一致的人工日期序列、独立字面价格，通过正式normalizer/capture及真实隔离PostgreSQL的publisher执行；每频一只股票，不模拟全市场。源网络由替身替代，以下不含平台等待或限流，不按行数乘股票数推导生产耗时。

| 本次样本 | 规范化源数组字节 | 规划/草稿/冻结 | 捕获校验及业务发布 | 已提交原计划重放 | 最后限定股票计数读回 |
| --- | --- | --- | --- | --- | --- |
| 周线1786行 | 723331字节 | 0.0077秒 | 1.3147秒 | 0.0026秒，无源下载 | 0.0016秒 |
| 月线428行 | 173769字节 | 0.0077秒 | 0.2863秒 | 0.0025秒，无源下载 | 0.0014秒 |

两频均独立断言源行数=合法原键数=Raw写入行数=Serving周期数，拒绝0；原已提交股票不重抓、不重写，逐单元业务累计期限和全部原预算未增加。纯撤回测试源请求为0；组合维护只对下载名单发请求。此处字节是canonical源数组大小，不是HTTP流量或RSS实测；恢复和最后读回分别实测，未省略其开销。

阶段4仍按原方案做正式组件的集中串联与逐条对账；阶段5才按另行批准的准确范围做生产迁移、排程切换、存量发布、真实运行—取消—续跑—读回及自然日更验收。本轮没有生产明细全局读取、正式DDL、生产任务、排程修改或数据维护，不把本地通过称为已上线。

复权因子比较的效率回归使用257只明确测试股票（跨越原128行块的两个完整块及一行），4次取消检查，不随股票数逐只查询取消标志；比较前后的取消检查及原单元/分页取消规则保留。这里统计的是该输入函数调用检查回调的次数，不冒充全部SQL数量。

### 13.30 阶段4串联验收设计与记录

2026-11-16管理员批准按LLD推进阶段4。阶段3已提交`d7559ab1a`。本步目标是把已经分段验证的正式API、TaskRun、现有OperationsWorker、resolver、真实Tushare client/分页、Raw/Serving事务与Quote读取串联在隔离资源内，并补齐旧入口和文档状态对账；不改变已定业务口径，不做生产迁移、排程切换、真实行情写入或全市场初始化，不重测已忽略的数据库版本差异。

**开工代码审计。** CodeGraph callers/impact及当前引用核实：`weekly-adj-plan-correction`仅由`src/cli.py`包装注册，实际实现为`cli_parts/ingestion_handlers.py:run_weekly_adj_plan_correction`；活动Definition已不再提供旧weekly policy。此命令和包装/实现一并退出活动入口，删除仅验证该旧命令的测试，改为证明命令不再可执行且正常维护入口保留。旧交付表、DAO、历史读取、不可变约束及旧更正记录的底层合同保留；不恢复旧policy、不加兼容执行，不改旧任务状态或替生产旧批次办理交接。引用审计已定位的CLI专属测试在两个旧更正测试文件；原更正事实/恢复合同测试继续保留。

两份数据集开发说明8.4仍有“测试未开始”的旧状态，是上一阶段文档收尾遗漏。本步按13.28/13.29分别记录已完成的阶段2/3，以及本步阶段4、未执行的阶段5；不删除带日期的历史记录，不把全阶段验收一并勾选。

| 硬口径与场景 | 实现/验收位置及实际边界 | 必须独立断言 |
| --- | --- | --- |
| 正式维护API→队列记录→worker→源客户端→业务库→Quote API | 拟`tests/test_stock_period_adj_p4_integration.py`；装配正式App router，覆写数据库连接和认证依赖，关闭与本需求无关的后台生命周期；源端改为临时本机HTTP服务，业务组件不换替身 | 请求返回时未生成长计划/未写行情；源收到固定21列、正确freq/周期或无日期股票请求；源行、唯一键、写入、拒绝、读回数量；Quote原日期、前后复权、分页和唯一周期结果 |
| 两频当期与每日历史 | 正式排程API、原双Probe、worker及原业务DAO；两个股票及明确业务日，使用已有日历/主数据/复权因子模型 | 同D两频当期齐备后才触发；0结果后晚到变化能触发；首次两频计划持久化、另一频不重新筛名单；历史失败不挡次日当期 |
| 人工完整历史、周期补齐、准确撤回和组合维护 | 同一正式API和客户端，不更换capture/normalizer/publisher/Quote；源21列字面样本加明确日期/代码变体 | 人工无当天因子比较；指定键优先撤回、剩余候选重选；仅撤回股票零下载；范围外及另一频不变；不将单股结果当全市场完整 |
| 取消、进程退出、恢复与幂等 | 通过正式取消/恢复API；在真实unit提交后注入取消，另用独立进程在unit提交后退出；原业务记录作为续跑依据 | A已提交后不领B；恢复只请求B，重放已完成任务无源请求；Raw/Serving/unit一起保留；TaskRun及当前节点终态一致，业务进度只在提交后增加 |
| 观察失败及中断任务收尾 | 原TaskRunIngestionContext独立连接故障注入；原OperationsTaskRunReconciliationService识别本功能合同/进度，沿现有失联时间规则收尾 | 不回滚行情或unit；进程中断后用原超时规则将TaskRun和当前节点一起结束，再按原冻结计划恢复；不新建状态机、心跳、worker或超时配置 |
| 分页与异常回包 | 本机HTTP按真实21列和Decimal数字字面量返回；分页反例可重复同一个合法历史键，明确为人工分页夹具 | 6000行满页后继续offset=6000，到短页才写入；同键同值计数并去重；源错误/错误列不当0成功，不部分发布，不重试或加日期过滤 |
| 全部合同消费者和旧入口 | 复核13.18、阶段2/3已有测试及本轮新增覆盖 | 原period/current输入、时间审计、freshness、catalog、workflow、手动表单、Quote不漂移；旧更正命令无活动调用；旧交付历史仍可读 |

**中断收尾的已核差距。** 现有失联任务收尾会将TaskRun置为失败，但只给指数周期线的当前节点同步失败。本步只扩展到股票复权周/月线的新合同或该功能进度记录，不改变其他数据集；继续使用现有running的10分钟、canceling的3分钟规则，不增加等待或配置。测试按这些已有常量推进观察时钟，不实际等待；突然退出前尚未落到Ops的进度允许滞后，恢复必须从业务unit读回已提交量，不能据滞后的观察量重抓A。

补充代码审计：生成计划期间尚未写入冻结合同及执行进度，但已经保存`stock_period_adj:{TaskRun ID}`这个本功能专用的当前节点。本步同样识别该现有节点键，覆盖冻结前退出；不能等合同保存后才允许同步终态。以原节点键、冻结合同、任务进度及节点进度分别造例，刚到原超时边界仍保持运行，超过边界才一起结束，不新增标记或配置。

消费者回归发现阶段3漏同步了阶段2的排程HTTP测试：仍断言只有一条当期规则，且暂停后用`all()`检查空集合，不能证明规则已撤销。按13.17既定合同改为明确断言当期/历史两条规则、各自相同的固定配置，暂停后0条，恢复后重建两条；不据旧断言修改正确的双规则实现。本项在阶段3的回归中漏检，本阶段补齐。

**配置与资源。** 不新增生产配置。测试用已有`GOLDENSHARE_ENV_FILE`选择测试临时目录中的空文件，避免根`.env`优先于环境变量；再临时覆写已有`TUSHARE_BASE_URL/TUSHARE_TOKEN`指向任务自有HTTP服务及假凭据，并断言解析后的地址、凭据和数据库连接。数据库为已有任务临时PostgreSQL18和每例独立库；正式API用原数据库依赖注入，其他后台服务不启动。源平台行为继续复用13.22证据，不安排重新请求平台或生产明细。故障注入只模拟取消、提交后退出和观察写入失败，不替代业务写入或伪造成功结果；源日期与执行日期使用明确的测试时钟。

**预算与验收。** 全部执行限制沿13.24，不增加数值。普通夹具每个有源单元短页一次，当前预检/正式两频分别最多2+2次；两只变化股票的两频历史为2×2=4个源单元。取消/退出重做只计未提交股票；幂等重放源请求0，纯撤回源请求0。分页夹具取一满页6000行及一行短页，实际累计6001行、2次调用，均在原单元上限内；这些行故意使用重复合法历史键，仅验证分页及计数，不伪称6001根真实K线。最后验收只读本例原计划、unit、指定Raw键、受影响股票周期及Quote页，不做全市场对比；测量并分别记录正常执行、恢复、重放及读回耗时，不从本机结果推导生产ETA。失败保留已提交单元，本次未提交单元不留部分行情。

阶段4通过条件：上表串联路径及必要正反例通过、13.18消费者逐条对账、旧入口引用清零、两份开发说明状态一致、相关回归及文档检查通过。当前完成本步方案/代码影响面审计，开始实施，尚未宣称本步通过或已上线。

#### 13.30.1 阶段4实现及独立复核结果

2026-11-16阶段4编码、隔离串联和完成后的独立复核完成。复核重新按13.18—13.19逐项读取当前代码与测试，不把测试数量作为业务口径正确的替代。原始21列样本继续取自13.22真实回包，测试日期、股票代码和分页重复行明确为人工变体；业务预期使用独立字面值，不从待测选择函数生成。未变更Definition、公开请求类型、行情SQL或生产配置，不增加校验、兜底、worker或数据库表。

| 对账项 | 本步源码/证据 | 结果与范围 |
| --- | --- | --- |
| 正式维护API、入队、worker、真实客户端及Quote读取 | `tests/test_stock_period_adj_p4_integration.py`使用正式App路由、TaskRun服务、OperationsWorker、resolver、HTTP子进程/分页、normalizer、publisher及Quote API；只替换认证、数据库依赖、无关后台生命周期及外部行情平台 | 周线/月线分别读回正确原日期和11.14前复权价格，后复权1582.95；历史两条Raw归同一自然月、Serving一条；Quote limit/下一页及删空正确。请求返回时无计划和行情写入 |
| 当期及自动历史 | 正式排程API生成每频当期/历史两规则；ProbeRuntime→源三列预检→正式21列下载→两频闭合→因子比较→两份冻结历史计划 | 两频当期未齐时不回刷；0结果合法且不冻结空历史；因子晚到后触发；另一频使用首次保存股票名单。两股样本实际2次预检+2次当期+4次历史请求，历史请求无日期 |
| 人工范围、保护、撤回及组合 | 正式维护API依次执行完整历史、闭合周期、撤回、组合及恢复；实际读取Raw/Serving/unit，Quote读回 | 较旧历史不覆盖较新Raw；撤回29日后选28日完整行，价格12.01；组合撤回优先，仅撤回股票不下载，范围外股票保留；无2010截断或全市场初始化 |
| 取消、真实退出、恢复、重放 | SQLAlchemy真实unit COMMIT事件后经取消API停止；独立进程在同一提交位置退出；原失联收尾及恢复API | 两股票A先提交，取消或退出后Raw/Serving/unit保留；恢复只下载B，不重抓A；已完成原计划重放请求0。取消/失败/成功时TaskRun与活动节点终态一致；业务进度从已提交记录恢复 |
| 观察故障与生成计划期间失联 | 只注入TaskRun观察更新失败；`operations_task_run_reconciliation_service.py`增量识别新合同、进度及生成计划节点 | 观察失败不回滚行情，最后终态/数量读自业务结果；8个专用反例/正常边界测试覆盖四种标识、刚到10分钟不误停、超过才同步收尾，沿用原超时常量 |
| 分页、源错误、字段错误 | 真实本机HTTP→bounded client子进程→source client | 6000同键人工行满页后offset=6000再取1行；累计接收6001、唯一1、Raw写入1、两次请求；源错误或缺列任务/节点失败、不留部分行情，恢复后成功；错误不当0结果 |
| 旧入口与历史事实 | `src/cli.py`、`cli_parts/ingestion_handlers.py`及旧更正两测试文件 | 已去掉旧命令注册/实现；源码无活动调用，反向测试验证旧命令不可执行，正常维护/资源目录保留；旧更正事实、DAO、恢复和不可变约束保留，没有清理历史数据 |
| 合同全部消费者 | 复读Definition/registry、resolver/request builder、两Serving builder/publish service、manual/catalog、dispatcher含workflow、TaskRun、Probe、freshness/卡片/快照、日期审计、Quote/older date及前端能力消费者 | 新用途仍由原合同和后端能力产生；workflow原参数保留、不自动加入撤回；日期审计按自然周期、freshness排除未闭合周期并另示完整当期D；前端本步未修改，复用阶段2/3接口夹具/61项测试及浏览器证据。Wealth股票详情仍是日线消费者，不扩展周/月界面 |

旧排程HTTP测试沿用单规则预期是阶段3漏同步，现已明确断言两规则、两者固定窗口与频率、暂停后0条、恢复后重建两条；修正依据为既定13.17及当前真实生产者，不为迎合错误实现放宽断言。生成计划期间的失联节点收尾遗漏也已修正，没有扩大到无关数据集。

**本阶段测试记录。** 最终隔离串联11项通过；根架构/注册/resolver/21列合同、旧更正及失联收尾相关回归268项通过；手动/自动任务与Quote目标HTTP回归13项通过；日期完整性、freshness快照、数据集状态快照及Serving发布消费者回归29项通过。所有本步选中测试执行通过，没有以skip替代PostgreSQL或客户端边界。Definition linter、文档完整性及差异格式检查通过。数据库实际使用任务自有PostgreSQL18，版本差异按管理员既定决定忽略，没有重复16版本验证或安装依赖。既有TestClient依赖弃用提示保留，不在本轮升级依赖。

**性能读数。** 两股、每股两条Raw/一条Serving的月线样本，本机正式组件与本机HTTP实测：运行至A提交后取消0.2615秒；恢复并只处理B为0.2116秒；已完成原计划重放0.0128秒、源请求0；最后限定本例Raw/Serving/unit计数及两股Quote读回0.0075秒。各次worker计时包含其规划和观察开销，API提交/恢复受理不计入该计时；最后读回另计。该小样本不代表全市场、平台等待、Prod吞吐或ETA；13.24预算没有提高，既有6000行发布及1786/428行历史性能证据继续见13.28—13.29。

**测试配置错误与处理。** 首轮测试只设置TUSHARE环境变量，未核对`get_settings()`中配置文件的更高优先级，错误加载了根`.env`并向真实行情平台发出只读请求，包含2020年2月的全市场周期请求；这不符合本轮仅本机替身的安排，是本次执行错误。数据库由显式依赖及worker连接隔离测试库，未写生产数据库。首轮8项失败结果全部作废，不用意外源请求证明任何验收通过。随后用已有`GOLDENSHARE_ENV_FILE`选择临时空文件，并断言实际客户端地址、假凭据及测试库连接；最终11项的源请求均由任务自有HTTP服务记录和逐项断言。未将此次错误扩大成修改全局Settings行为或新增产品配置的需求。

本步使用CodeGraph callers/impact/explore补核旧CLI、失联收尾和dispatcher，结束时sync/status通过；图中动态/字符串链路继续以当前代码直接核对，没有只凭图结果宣称调用清零。两份数据集开发说明、原方案及架构快照同步；阶段4结果已满足本步要求，未发现仍需管理员拍板的新业务问题。本阶段修改随本次提交保存；未部署、未执行生产DDL/排程切换/行情写入，未开展阶段5。阶段5仍须先完成具体生产步骤的方案/LLD及范围审计，再按授权执行，不能从本步本地通过推导生产已生效。

### 13.31 阶段5生产切换的执行设计

2026-11-16管理员要求先补齐阶段5的LLD。本节补全原方案7.5、原13.25的执行细节，阶段4提交为`86abea0c1`。前次编写已完成13.31.1的计数核验；本轮按管理员“精简、不要做太重”的要求只修改文档，复用已有结果，没有重新访问生产、创建生产写入脚本、安装依赖、推送、部署或修改排程/数据。以下正式步骤须在具体范围获准后执行；本节编写完成不代表生产已切换。

#### 13.31.1 已核实的生产依据与本次范围

2026-11-16 16:42—16:46上海时间强制READ ONLY事务核实：生产代码为`f89152f787f567dbfdf524573cfc560e698c6b06`，迁移为`20261112_000188`；新业务表及两条周期唯一索引尚不存在。旧排程6、14、15均active，两数据集的queued/running/canceling任务0，旧周线plan与batch_closed各12、未闭合计划0。该快照按取得时间保留，不冒称本轮重新核实。复用已有历史数据审计；正式窗口只确认将改变的排程、当前任务和迁移状态，不重新统计全部历史行情，也不改旧任务历史。

| 数据范围 | 已核实数量/状态 | 本次切换处理 |
| --- | --- | --- |
| 股票复权周线Raw、Serving | 两层各3,056,771行，Serving重复自然周0 | 不重发存量周线，建立本频周期唯一索引；当周更新另经正式任务验收 |
| 股票复权月线Raw、Serving | 两层各716,021行；Serving重复股票/月份3,588组，多出3,588行 | 仅重选这些重复组；保留全部Raw，范围外月份不重发 |
| 重复月份中的Raw候选 | 没有有效计算截至日的组0；同最新截至日的17个行情业务字段存在异值的组0 | 使用现有整行选择；不能固定挑月末日期或改写源日期 |
| 原日期为空的其他存量 | Raw周线19,436条、月线3,149条，均属于各自没有有效截至日的组 | 不在本次重复组内，不扩大到这些历史周期，不填造日期或启动全市场补数 |

2026-11-16 17:12:25补做唯一新增核验：通过既有`psql-remote.sh`，只统计上述重复组在各自然月的组数、Serving行数和Raw候选数，强制READ ONLY，沿用前次30秒语句期限，无行情明细输出。结果只有**2020年2月**一个自然月：3,588组、7,176条Serving、7,176条Raw候选。本次拟定明细读取和写入范围因此固定为这些股票在`[2020-02-01,2020-03-01)`、`freq=month`的记录，不是整个股票月线历史。正式PLAN只在2020年2月取得这些重复组的股票/月份键，读取其Raw完整21列用于现有发布接口，不读旧Serving全部价格、不再做全局重复发现。该明细读取随执行范围单独取得批准，已有计数不代替明细读取批准。

在旧写者停止且快照不变的前提下，存量操作将7,176条Serving换成3,588条，月线总量应为716,021−3,588=712,433条；周线不变，Serving两频合计3,769,204条。Raw两频合计3,772,792条不变。这些全表数字保留为前次审计和算术推导，不再作为本次前后重跑全表COUNT的验收项目。本次只核该月这3,588组的7,176→3,588结果；仅当实际看到本范围的变化时再针对变化说明，不因担心可能变化而先做全量审计，不自动扩大写入。

#### 13.31.2 当前代码、入口及复用边界

CodeGraph query/impact及直接源码核对覆盖`ServingPublishService`、`republish_groups`、`init_db`、排程服务与Probe绑定，以及其PG/HTTP测试和App执行装配。现有`plan_publish`按输入行情键确定股票/自然周期，从Raw重新选完整行；`execute_publish_plan`在本频事务锁内重读Raw，调用共同`republish_groups`，删除该组原Serving、插入所选完整行并读回，同一事务提交。此处不调用源接口、不写Raw，也不生成当期交付或历史回刷完成记录。

本次3,588组仅形成**一个固定范围的Serving发布单元**，以现有累计20秒业务事务一次提交，不凭股票数另造29个提交批次。原128行块只用于SQL参数和读回，不是独立提交。临时操作封装放本任务`/private/tmp`目录，只组织PLAN、APPLY、VERIFY参数、调用现有服务并记录结果；本轮不编写它，不新增CLI、DatasetDefinition用途、维护动作、业务表、worker或常驻服务。正式使用前须按本节完成封装审查及隔离验证，不能把文档当已经存在的可执行脚本。

一个单元的业务持久化事实就是这批Serving完成的原子替换。固定键集合与预期结果摘要保存到只读冻结计划，结合实际Serving读回恢复，不以日志、TaskRun计数或“脚本退出码0”推定已经提交。本次直接人工Serving发布是有明确静态边界的短操作；源维护、历史回刷和自然日更仍全部走原TaskRun/OperationsWorker，并遵守13.24的取消、进度及终态要求。若隔离验证证明本封装本身超过60秒或不能保持这里的固定边界，停止正式执行，回本LLD改为满足现有Prod长任务门禁的执行方式；不能拆命令掩盖长任务，也不因尚未发生的超时先建新执行器。

#### 13.31.3 一次计划、一次提交、一次范围验收

正常路径在同一进程连续完成以下步骤，保存计划是为了中断恢复，不把正常流程拆成重新读取数据和重新规划的多个进程。只读查看计划后退出、以后另启进程执行的情况走恢复路径；恢复不能依赖旧进程内存。

1. **生成一次计划。** 显式选择正确生产配置；只在2020年2月取得已确认重复组的键，读取这些组Raw完整21列，传入现有`plan_publish`。该函数内部会重读Raw并选整行，复用其结果，不在封装里另算一套价格或逐字段审计。Raw输入数组用后释放，正常路径保留返回的`ServingPublishPlan`。不要为规避现有合同补造字段或使用无效撤回键。
2. **保存最小范围。** 保存批准代码SHA、目标库标识、数据集/频率、原3,588个股票/月初键、预期所选原始键、预期结果摘要及计数，沿原1MiB计划限制；不保存执行前Raw摘要、旧Serving全列摘要或行情数组备份。预期结果来自步骤1已取得的行，不为保存计划再查数据库。`dry_run=True`本身不读写数据库，可用于只读查看，不另做一轮相同PLAN。
3. **复用计划直接提交。** 正常执行直接把步骤1返回的计划交给`execute_publish_plan`，不重新调用`plan_publish`，不在提交前重新读一遍Raw/旧Serving做摘要比对。现有函数在本频事务锁内读取真实Raw，按最新截至日选整行；7,176条删除、3,588条插入及3,588条事务内读回在原累计20秒事务内一次提交。Raw不写，SQL参数仍按128行分块。控制台只在COMMIT后把0/1单元、0/3,588组改为1/1、3,588/3,588组。
4. **提交后只验目标范围一次。** 只读这3,588组的Serving，确认每组一行、原日期及完整业务值等于计划预期；`change_amount`按既有映射对应源`change`。不再读Raw做摘要、不查两频全表COUNT或全历史重复COUNT。事务内读回验证本次写入，提交后这次读回确认持久结果，两者目的不同，均保留。读回通过才进入190。
5. **仅中断时恢复。** 先读冻结范围的Serving并与原预期结果比较：已经完成则跳过写入；尚未完成才按原股票/月范围重建一次计划并执行。一次事务已保证不会留下本次半批提交，不再要求先读旧Serving全部字段来判定“必须等于某个旧摘要”。只中断了最终验收则只续验收，不重复发布，不重做189。
6. **取消处理。** PLAN取消不写业务；提交前可停止，事务中中断后先等连接结束，再按步骤5读回判断是否提交，不能仅因日志未落盘就重写。若确实发现输入变化，说明该范围的实际变化再处理，不额外发起全库检查。本步骤没有源请求，不产生当期或历史回刷闭合记录。

#### 13.31.4 分步迁移与部署次序

| 顺序 | 执行动作和现有入口 | 完成依据及中断处理 |
| --- | --- | --- |
| 1 确认窗口 | 记录批准目标SHA、当前迁移和要改变的服务/排程；维护窗口内不发起这两数据集的新人工请求 | 复用已完成的旧计划闭合和数据范围审计，不重新审计所有旧批次 |
| 2 停止旧写入 | 通过现有排程pause API暂停6/14/15；停止既有通用worker、scheduler和日期审计worker，记录原状态 | 停服前只看现有worker当前任务，未经授权不打断无关任务；停止后一次确认两数据集无活动任务。只在状态已改变后读回，后续子步骤不重复整套检查；发布事务沿现有锁检查，不另扫全库事务 |
| 3 单独执行189 | 使用已验收的本机现有`.venv`和批准版本源文件连接生产；`GOLDENSHARE_ENV_FILE`显式指向已核实的生产连接文件。只执行Alembic目标`20261116_000189` | 读回version=189、新业务表/不可变触发器及索引存在。命令失败读回实际版本；不执行downgrade或重建表。不得调用会直达head的`init-db` |
| 4 存量重选 | 执行13.31.3的PLAN/APPLY/VERIFY | 固定一个月、一个原子单元；失败/退出按实际Serving恢复，Raw不变。没有通过VERIFY不得进入190 |
| 5 单独执行190 | 同样环境执行Alembic目标`20261116_000190` | 读回版本190和两条索引均unique、valid，复用已经完成的目标范围验收，不再跑全历史重复COUNT。版本及索引状态不符先查明，不能以`IF NOT EXISTS`绕过 |
| 6 发布新代码和运营前端 | 使用既有发版流程，必须跳过已经分步完成的迁移、两种seed及unit文件同步，跳过未修改的Wealth构建、QTF与realtime | 远端实际SHA与批准SHA相同，源、依赖和运营前端产物对应本次版本；各相关服务真实active及健康/Quote/任务API通过。部署脚本结束或状态打印成功不是验收 |
| 7 改排程，先保持暂停 | 按13.31.5编辑6和14；15保持paused | 没有旧cron/月末策略残留；未恢复时从属规则0，人工真实演练可单独进行 |
| 8 真实日更及合并验收 | 恢复6/14，按当天20:00窗口触发当期与变化历史，在同一次实际历史任务中验取消/恢复 | 不默认另下两股完整历史；各项按实际结果记录，0变化不冒充非零历史，15不恢复 |

分步迁移从当前188到189、从189到190各自是独立命令；恢复时已达对应版本则核验后跳过，不能为了回到本快照降级或重复建表。若已有本设计之外的版本变更，先核对实际迁移链再更新执行安排。`src/cli.py:init_db`固定`upgrade(...,"head")`；`--maintenance-migration`也强制迁移到head，不能用来代替以上两步。Alembic配置路径沿仓库`alembic.ini/env.py`，当前env已有15秒迁移锁等待限制；这不是20秒行情事务期限。实际迁移代码及导入的本任务Foundation文件须与批准提交一致，不能把其他线程未提交修改带入生产执行。

步骤6的可审查命令形态为：`DEPLOY_FOUNDATION=1 DEPLOY_OPS=1 DEPLOY_PLATFORM=1 DEPLOY_QTF=0 bash scripts/deploy-systemd.sh dev-interface --skip-migration --skip-seed-default-source --skip-seed-moneyflow-multi-source --skip-sync-units --skip-realtime --skip-wealth-build`。复用已有配置/开关，不新增配置；默认值、来源和消费者引用[正式发版流程](../release/release-process-v1.md)，上述环境覆盖只作用于本次发布进程，不持久化。执行前记录有效模式及全部build/migration/seed/unit/restart值，确认运营前端build开启、QTF-only/maintenance模式关闭，不继承其他模式。该模式仍会安装现有后端包、执行运营前端npm依赖准备及构建、可能daemon-reload，并重启Web、通用worker、scheduler、日期审计worker、任务完成worker、股票分钟worker、指数分钟worker；分钟/完成处理重启是现有发布脚本的实际行为，不能假称只影响两条数据集。具体安装、构建和这些既有服务重启必须包含在执行授权中。本设计不修改部署工具；步骤2停止的服务必须在步骤6逐项核对恢复情况，不以“发布成功”替代。

#### 13.31.5 三条旧排程及配置落点

拟保留排程14作为股票复权周线日更、排程6作为股票复权月线日更；排程15保留历史并暂停，不删除。选择6是复用已有月线排程并消除重复意图，不改变数据处理规则；这是本执行设计中的安排，不冒称此前已经执行。

通过现有`PATCH /api/v1/ops/schedules/{id}`一次给6/14设置：`schedule_type=cron`、`trigger_mode=probe`、`cron_expr=null`、`next_run_at=null`、`calendar_policy=null`、`timezone=Asia/Shanghai`、`params_json={}`；`probe_config`为`condition_kind=stock_period_adj_current_ready`、`window_start=20:00`、`window_end=00:00`、`probe_interval_seconds=60`、`max_triggers_per_day=1`。不要先单改trigger_mode而保留旧cron或月末策略。两个原target_key不改，display_name可仅按业务名称更新。

这些值仍来自13.17已审计的后端能力、`ScheduleProbeConfig`和现有具名常量，持久化在原`ops.schedule`；消费者仍是原capability resolver、schedule service、binding及ProbeRuntime。无新env配置、源参数或前端常量。修改/暂停/恢复经原命令服务保存配置修订；API完成后读回schedule、从属Probe及config_revision，不直接用SQL拼配置。若配置事务失败，只处理配置事务，不能撤回已经提交的Serving。

新代码下暂停的6/14无从属规则；通过现有resume API激活后每条生成当期与内部历史两规则，最终active父排程2、active从属规则4，15仍paused且无活动规则。每条规则按用途/freq/D防重；历史条件不作为新的运营可选项。原20:00—次日00:00、60秒和上游0行口径不重新讨论。

#### 13.31.6 数量、内存、耗时与恢复预算

| 项目 | 本次依据、计算及执行要求 |
| --- | --- |
| 存量源请求 | PLAN/APPLY/VERIFY全部为0；只读取获准的2020年2月重复组，不向平台重新下载 |
| 单元与SQL | 固定1个原子单元，3,588组、7,176候选、3,588选中；128行块，`ceil(3588/128)=29`组块。共同publisher内部29次Raw候选查询、29次Serving DELETE、29次INSERT、29次Serving读回，共116条业务读写SQL；事务/锁及其设置另计，不能称116次提交 |
| 载荷 | 按修正后的637字节最大合法行对象，7,176行数组上界`7176×638+1=4,578,289`字节；3,588行数组上界2,289,145字节。适用条件为21字段、9字符有效股票代码、DATE ISO文本及现行数值精度；实际PLAN逐份检查。这里不是HTTP流量或RSS；SQLAlchemy对象开销不据此声称相等。封装须释放已用的输入数组，内存只与这一个固定单元相关，不读取整张行情表入内存 |
| 计划大小 | 冻结文件仅存两组键数组和整体摘要/元数据，实际canonical字节<=1MiB；不把7,176条行情放入计划。已有`ServingPublishPlan.rows`为运行中所选行，不把它序列化为长期备份 |
| 正常读取成本 | 取得真实Raw输入R条、现有plan_publish内部R条、锁内发布R条；正常流程共3R=21,528次Raw行出现。Serving仅事务内及提交后各G条，共2G=7,176次行出现；R=7,176、G=3,588。另有2020年2月范围内的键查询、7,176删除及3,588插入。原6R/旧Serving全列摘要/末尾Raw摘要核对已删除；这仍是累计逻辑行数，不是独立K线或磁盘读取量。现有接口内的重读保留，不为省这一轮修改共享发布接口 |
| 中断后继续 | 先读本范围G条Serving；已达预期就跳过，Raw读取和写入均0。未完成才重建一次本范围计划并重做该原子单元，成本按本次实际调用另记，不把恢复重建放在每次正常流程。不重做189、不下载源历史；源维护TaskRun仍只续原未提交unit |
| 业务期限 | 存量APPLY复用20秒累计事务、2秒锁等待；SQL取消/故障不能把每条SQL重新获得20秒当总预算。源任务继续13.24的每页20秒、最多3页、单元事务20秒、进度5秒，不提高限制 |
| 索引工作量 | 190有两次普通部分索引构建，表在存量处理后约3,769,204行；两次构建分别扫描表，不能只按3,588个改动组估算，也不能称扫描产生了新K线。迁移15秒限制只管锁等待，不是构建时长保证 |
| 未能确定的耗时 | 本次7,176候选实际发布耗时、两条生产索引构建及发版停服时长尚无适用实测；不沿用小夹具读数当Prod保证，不填固定分钟数或随意余量。正式APPLY前做本范围的隔离发布预演并记录正常/中断/恢复/最后读回；索引正式维护窗口需明确允许等待及取消方式，取得执行安排后才启动。无依据时本项保持“未实测”，不因此再安装PG16或重测版本差异 |

普通CREATE INDEX允许查询、会阻止同表写入，来源为[PostgreSQL索引说明](https://www.postgresql.org/docs/16/sql-createindex.html)。索引构建自身的表扫描是建立约束的工作，保留；删掉的是前后重复安排的全量数据审计，不以索引失败代替已经做过的首次存量审计。按当前`env.py`事务执行190，任一步失败/取消后须读回版本及两索引，不能把第一条索引的过程输出当部分成功已经可用；不擅自改为CONCURRENTLY。可通过[原生索引进度视图](https://www.postgresql.org/docs/16/progress-reporting.html)观察本次PID、表、阶段及当前阶段完成量；这些不是整个操作百分比或ETA。维护窗口、取消及恢复安排沿本节，不新增监控或全表核验步骤。

#### 13.31.7 合并真实验收与自然日更

存量范围验收、190及新代码发布通过后恢复6/14，让真实上海业务日D的20:00—00:00探针完成两频当期更新。三列预检、完整21列正式回包、逐unit提交、两频当期闭合及实际复权因子变化股票的历史回刷继续原实现；精简的是额外审计，不删除这些已定日常业务。上游0行/0变化直接使用并记录真实0，不伪造因子或强加股票来造验收数据。

**把生产取消/续跑合并进同一次真实历史回刷。** 在其中一频真实任务运行时通过原取消API申请取消，读回已提交unit，用原TaskRun ID恢复；观察已提交股票不重抓、未提交股票继续及任务/节点终态。能实际覆盖“一股提交、另一股未提交”就记录该证据，不为等待这个时点重跑历史或扩充名单。若当时任务已结束、当日没有变化股票或没有合适任务，就如实保留该项待验，结合后续实际任务完成，不靠额外下载平安银行/浦发银行完整月线来凑演练；不得因此伪称阶段5全部通过。

人工操作沿同次任务的取消及原ID恢复API核对，人工新建股票历史、准确撤回和组合维护复用阶段4已通过的正式API/隔离数据库证据，不另造生产写入；各路径是否做过生产操作分别记录。管理员本次精简决定取代原“默认另选两股完整月线做取消演练”的安排，不把自动任务冒充人工新建/撤回已经生产验收。

请求预算删除原额外人工两股的源调用：当期两频正式最多6次；K只实际变化股票的两频历史最多6K次；合并的一次取消恢复最多额外重抓当前1个未提交单元、另计最多3次。预检仍按已定4小时/60秒窗口，每频最多240次、每次最多3页，两频最多1,440次，因此首次执行、完整窗口及这一次取消恢复的预算上界为`1449+6K`。没有实际取消则没有对应重抓调用；另有真正故障恢复时仅按剩余单元另计，不重复整批。此为调用次数推导，不是能在窗口内完成的耗时保证；沿现有源限流和任务观察能力，不为核配额再做全市场试拉。

当期两频、实际非零回刷、取消/恢复、之后自然日更分别记录实际结果，尽量用同一批业务执行证据验收，不再把同一验证拆成多次数据下载。Quote只补必要样本读回，数量和范围依据本次业务记录，不全历史逐行对比。TaskRun页面仍显示真实阶段/对象/已提交量/总量及更新时间，ETA“暂无法估算”；观察失败不回滚业务。阶段2—4已经通过且本次未改的合同、分页、指标和浏览器测试不整套重跑。

#### 13.31.8 失败后的保留、测试与执行门禁

失败只停止尚未完成步骤：189成功后保留新不可变表；存量提交成功后保留正确Serving；190失败先保持旧写者停止，复核实际索引/版本后只续该步；发布失败先恢复获准版本的读取能力，6/14/15保持暂停。不能清表、回写旧失败任务、重启旧写者越过新约束或自动downgrade；Raw未修改是重新正确选择的事实依据，不添加Kopia或全历史备份流程。恢复代码、安装包/前端产物和配置分别核对，不能只切Git就认为数据及运行环境也回退了。

| 验收约束 | 执行封装与隔离验证必须证明 |
| --- | --- |
| 精确范围与整行规则 | 2020年2月重复组2→1、28日截至更新则选28日；周线、范围外月份及Raw不变；同最新异值停下，不拼字段、不自动删Raw |
| 只读计划与固定范围 | PLAN/dry-run无写，正常流程只生成一次计划并直接复用；读取/写入始终限定2020年2月这3,588组，不做全表统计或多轮摘要核对 |
| 原子提交、取消与恢复 | COMMIT前退出整批保持原状，COMMIT后只读本范围并跳过写入；只在中断时走恢复重建；生产取消/续跑按13.31.7合并到实际历史任务 |
| 可承受的实际规模 | 用7,176候选/3,588组的独立人工样本与正式publisher验证原20秒事务、数组预算及最后读回；先确认原函数调用语义，不引入字段兜底来消除失败。仅做本封装一次本范围预演，补提交前后退出/恢复所需用例，不重跑阶段2—4全套，不重测数据库版本差异，也不导出生产全量数据造夹具 |
| 迁移及发版顺序 | 189止步、读回后重选、190、跳迁移部署；脚本/参数静态审查证明不会提前init-db、seed或启动旧重复意图；索引/版本及服务逐项读回 |
| 排程及日常路径 | 6/14暂停编辑后再恢复、15留paused、2父4从属；真实D、合法0、首次名单及自然日更分开记录。复用阶段2—4仍适用的接口/浏览器与恢复证据，不把已有通过证据重复包装为生产结果 |

正式执行前须有：本节范围及维护安排确认、批准版本和运行环境、允许的明细读取/写入/安装重启清单、临时封装审查和本范围预演证据、DDL维护窗口及取消安排。设计已提供具体对象、调用、数量和恢复规则；尚未测得的生产耗时及尚未发生的真实验收如实保留，不能靠补文档直接标为完成。本轮不创建或执行上述封装，后续结果仍只回填本原LLD和对应原方案/开发说明。

**2026-11-16精简记录。** 原方案把正常执行、成功验收和故障恢复检查叠在一起，导致重复读取，是此前设计过重。管理员要求复用稳定数据依据、减少动作后，本节已删除重复全表计数/全历史重复审计、旧Serving全列及Raw前后摘要核对、正常流程重复PLAN、默认两股完整历史演练及未改功能全套回归。保留事务锁内真实Raw选择、事务内读回、提交后一次目标范围验收、索引构建和必要状态改变后的读回；正式数据是否有新变化只以实际观察为准，不把用户“数据没有什么变化”的判断写成新实测。本轮仅改原文档，未访问生产、制作封装、安装或执行切换。字节推导纠正及历史计数证据保留，实际执行及新增预演仍未发生。

精简后已核对当前发布函数调用及范围/恢复语义、3R/2G和1449+6K预算，四份原文档同步；34处本地链接路径、章节、文档完整性及差异格式检查通过。没有重跑未修改功能的测试或生产数据审计，本轮文档修改随本次提交保存，提交编号以Git历史为准。

### 13.32 阶段5执行记录

2026-11-16管理员要求按照LLD开始推进阶段5。本步复用13.31，不改变业务范围、接口、配置或基础设施。当前已提交依据为`b84d2c06ea29bdfd84c29e04dd78a006c446fa49`；先完成执行封装和隔离预演，生产操作仍依13.31.4顺序及13.31.8的实际执行条件推进，不以“开始推进”冒称已完成切换。

封装及测试仅放`/private/tmp/stock-period-p5-execution-tQkU32`。封装固定2020年2月和`freq=month`；首次只取本月重复组键及其Raw完整21列，调用原`ServingPublishService.plan_publish`，冻结组键、所选原键、整体摘要及目标库/代码标识，正常路径直接复用返回计划调用`execute_publish_plan`。提交后只读冻结组的Serving；恢复先读该范围，已达预期跳过写入，否则只重建原范围。不存在新配置项、任务用途或共同合同改动；禁止源请求、Raw写入、范围外维护及全量审计。

CodeGraph及当前源码已核对上述发布服务、`select_groups`/`republish_groups`、DAO、21字段和Raw/Serving真实模型；沿现有128行块、20秒事务、2秒锁及1MiB计划限制，性能和中断/最终验收成本引用13.31.6。隔离预演复用已存在的任务自有PostgreSQL18，仅新建任务自有测试数据库，不安装依赖、不清空或删除既有表。使用7,176候选/3,588组的独立人工样本，保留范围外周/月线；验证28日计算截至日更新时选28日整条记录、只读计划、正常一次计划、事务中退出回滚、提交后退出恢复不重写、计划大小、Raw及范围外不变，并记录正常/恢复/最后读回时间。人工样本字段以当前真实模型、原21字段合同和既有源字面样本为依据，预期采用独立字面值；不使用生产全量导出造夹具，不重跑阶段2—4或版本差异测试。

生产步骤尚未执行。临时封装预演及复核通过后，再记录具体发布版本、维护窗口和允许的暂停/迁移/存量读写/安装重启安排，执行结果回填本节及原方案、周线/月线开发说明。

#### 13.32.1 执行准备与隔离预演结果

本任务临时封装`republish_month.py`及`test_republish.py`使用真实已安装SQLAlchemy和任务自有PostgreSQL18；首轮4项隔离验证全部通过，耗时9.01秒，随后只补计划原子保存中断用例1项，0.78秒通过，共5项。计划在同目录完整写入并fsync后，以`os.replace`成为只读冻结文件，中断前的临时文件不能进入APPLY。输入21字段及类型沿真实Raw/Serving模型和原MCP字面样本，3588只代码为人工扩展，不作为生产行情正确性的证明。测试没有连接生产数据库或源接口，没有安装任何依赖；未重跑阶段2—4。

| 验收 | 实际结果及边界 |
| --- | --- |
| 固定规模正常执行 | 7,176候选、3,588组；一次计划，29条DELETE、29条INSERT，整体一次提交；规划1.3919秒，发布2.3759秒，提交后读回0.4070秒，总4.1748秒。仅为本机隔离实测，不作为生产耗时保证 |
| 计划大小与只读 | 冻结文件222,855字节，小于1MiB；dry-run写入0，Serving保持原状；文件只保存范围、所选键、摘要和库/代码标识 |
| 正确选择与范围 | 28日计算截至日期较新时选择28日全部21字段，独立字面预期逐字段核对通过；Raw全列及范围外周线、其他月份全列保持原状 |
| 提交前进程退出 | 在真实发布SQL完成后、COMMIT前退出进程，整个测试单元回滚；恢复仅按冻结范围重建并提交，无半批残留 |
| 提交后进程退出与重放 | COMMIT后、最后验收前退出进程；恢复只读Serving即判定已完成。固定规模重复恢复0.3138秒，没有Raw读取或业务写入 |
| 同最新日期异值反例 | 原范围内最新计算截至日期相同、行情业务值不同，真实选择函数拒绝；没有冻结可执行计划或写入Serving |
| 计划保存中断 | 原子改名前中断，正式冻结文件不存在且Serving无写入；重新执行可正常冻结和提交，不依赖旧进程内存或半份文件 |

按独立复核再次阅读封装与实际SQL记录：没有新增发布算法、源请求、Raw写入、跨月份维护、正常重复PLAN或全量生产审计；恢复依据是冻结范围及实际Serving，原20秒累计事务不变。现有环境没有Ruff模块，没有安装；已通过真实导入/执行、独立断言、文档完整性和差异格式检查，不冒称Ruff通过。

2026-11-16 20:37:23上海时间只读核对实际要改变的状态：生产迁移仍188，排程6/14/15仍为原active日历策略，两频活动任务0；另有ETF分钟线任务19888正在运行，不能擅自中断。7项相关既有服务均active，生产代码仍`f89152f787f567dbfdf524573cfc560e698c6b06`。只读查询限三条排程、迁移版本和最多21条活动任务，没有重新读取历史行情。另核实际远端`dev-interface`为`45fbb166756f302fc709d608c67f5fdd98fa6274`，目标提交b84d2c06e尚未推送；生产代码至目标版本在src/frontend/alembic/packages/scripts范围内仅阶段2—4本需求三次提交，无其他功能发布。维护窗口开始/最晚恢复时间已向管理员询问；确认前不暂停生产服务或执行DDL/业务写入。

#### 13.32.2 2026-11-17正式切换安排

管理员明确确认“现在prod不会写入股票周线和月线的数据库，你可以操作吧”，按本轮立即执行13.31既定切换；不再把上一轮要求另填起止时间作为额外审批。维护从本轮暂停开始，完成后恢复；未指定固定最晚恢复时刻，不制造分钟级耗时保证。迁移仍沿已有15秒锁等待、存量沿20秒累计事务；索引构建观察实际进度，管理员要求取消时取消本次DDL连接并读回版本/索引，保留已完成步骤，不清表或自动降级。无关任务不擅自取消。

2026-11-17 09:52:31上海时间必要只读核对：生产仍188、原6/14/15仍active、当前运行/取消中任务0、两频活动任务0，7项相关服务active、远端工作区干净，生产代码仍f89152f787f567dbfdf524573cfc560e698c6b06。当前dev-interface目标为`28a0d2961d9489d4b3997d3f9532aba3969e3897`，与已验收b84d2c06e相比只有DG文档提交，src/frontend/alembic/packages/scripts无差异，复用5项预演，不重测。执行封装SHA256为`73a0f559b1bd8031dd60a61e1be98a21b8ab96b28661ceb85cbe542b48ab0cf2`，未变。

按原顺序调用既有排程API暂停6/14/15并保留配置修订；停止原通用worker、scheduler和日期审计worker后一次核对无活动任务。API鉴权使用生产既有JWTService及现有有效管理员，凭据仅在服务端内存使用，不输出、保存或修改认证配置。189及存量操作由本机已验收环境显式选择`.env.web.local`连接生产，固定仅2020年2月3588组、7176候选；计划与输出留原任务临时目录。189、存量读回、190各自完成才继续，实际版本/表/触发器/索引只在对应变更后核一次，不再全表审计。

推送当前已提交目标以供远程原发版流程拉取，不携带本轮文档或其他线程未提交修改。依13.31.4既有开关发布，包含已说明的现有包安装、运营前端依赖/构建及7项既有服务重启，跳过迁移/seed/unit同步/Wealth/QTF/realtime；不修改发版工具。发布后按原API将6/14改为20:00—次日00:00、60秒两频探针，15保留暂停，再恢复6/14并一次读回2父4从属规则。当前是上午，不把尚未到来的20:00自然任务验收冒称已通过；实际回刷及取消/恢复合并后续真实任务，不额外造两股下载。

本轮推送执行疏漏及纠正：使用可随其他线程提交变化的HEAD作为推送对象，期间另一线程提交DG代码，实际推送为`d555f5965d95a7e57af9996df7facbc578d56a64`。推送已完成，生产当时尚未改动。已逐文件核对28a0d2961至d555f5965全部位于lake_console文档、orchestrator及其测试，src/frontend/alembic/packages/scripts无变化；本轮后续实际目标固定为d555f5965，封装使用同一标识，发布后核对实际SHA，不把其他线程未提交文件带入。

#### 13.32.3 已完成的生产迁移及存量处理

三条旧排程6/14/15已由原API暂停，随后原通用worker、scheduler、日期审计worker均inactive；停服后两频活动任务0。189单独执行成功并读回版本189、业务表、已启用不可变触发器及5个实际索引（含主键和唯一约束的索引）。未执行旧计划全量重审或全历史行情读取。

固定范围生产重发布已完成：计划3,588组、7,176候选，冻结文件222,804字节，生成计划6.7761秒；一次业务提交写入3,588条Serving，发布9.7477秒；提交后原范围读回1.6889秒，完整流程18.2127秒。结果status=verified、resumed=false，未改Raw、未调用源、未重发范围外周/月线，正常流程只有一次PLAN及一次发布。与隔离实测分别记录，不把本次时间套成其他任务保证。冻结计划、结果摘要和阶段输出留原临时目录，可按原范围恢复；本次没有为验收而再次发布或重新读Raw。

存量验收后单独执行190成功，读回版本190，uq_stk_period_adj_serving_month及uq_stk_period_adj_serving_week均unique=true、valid=true；不再运行全历史重复COUNT或全表行数对账。随后已启动原远程发布流程，实际发布及服务/排程结果待完成后继续记录。

#### 13.32.4 发布、排程与读取验收

远程原发版流程2026-11-17 10:00:19开始、10:01:11结束，实际拉取和部署SHA为`d555f5965d95a7e57af9996df7facbc578d56a64`，与核对目标一致。后端两个现有包均为0.1.0并从本次目录安装，技术指标包与主工程配置检查通过；运营前端依赖准备及构建完成，Wealth构建、迁移、两类seed和unit同步均跳过。原流程执行daemon-reload及既定7项服务重启，QTF和realtime未重启。逐项读回Web、通用worker、scheduler、日期审计worker、完成worker、股票分钟worker、指数分钟worker均active/running，两个health接口均status=ok、env=prod。未修改部署工具、认证配置或系统权限。

排程使用原API先保持暂停编辑6/14，再恢复，15继续paused。一次数据库范围读回确认：6/14均active+probe，cron_expr/next_run_at/calendar_policy均NULL；各自window_start=20:00、window_end=00:00、interval=60秒、max_triggers=1、source为系统默认，params为空。4条active从属规则恰为两频各current_ready与factor_history_ready；15无从属规则，旧月末配置仅作为暂停历史保留。本轮config_revision为6/14各paused、updated、resumed一条，15 paused一条，共7条。配置写入与行情事务分开，未直接SQL拼排程或修改旧任务结果。

生产Quote样本限定平安银行000001.SZ、2020年2月、前复权、limit=2，返回一条2020-02-29月线，close_qfq=11.7600，日期及OHLC逐项与该范围Serving一致。该结论证明新发布后的读取与存量选择一致，不声称已向平台重新下载历史或所有历史价格均为平台此刻最新。首轮请求漏带已有登录凭据被401拒绝，是本次执行疏漏；补用原JWT鉴权后同一样本通过，没有修改认证行为或吞掉失败。TaskRun列表API分别限两频各1条，读回周线19893、月线18875，均success；只是已有任务读取，不冒称本轮新日更完成。

本次正式源请求0，Raw写入0，只有已批准2020年2月的Serving重选；保留既有数据审计，没有全历史重复COUNT、全表行数对账、Raw前后全列摘要或额外两股历史演练。原5项隔离预演及阶段2—4未重跑。逐项按13.31.8复核：固定范围/一次计划与提交、读回、189→存量→190顺序、分步保留、真实发版版本和排程配置均有上述实际证据；实际生产取消/恢复未执行，不能以隔离进程退出或本次短事务替代长任务验收。

**当前结论：阶段5的生产迁移、指定存量处理、代码/运营前端发布及排程切换已完成；阶段5整体仍待真实业务验收。** 当前上午未手动创建当期或历史任务，今晚2026-11-17上海时间20:00起由原探针执行。两频当期完成、实际非零变化股票两频回刷、合并生产取消/原任务恢复、后续自然日更分别按13.31.7记结果；没有合适任务时如实待验，不另下两股全历史或为凑验收扩大范围。实际执行记录已同步原方案及周/月线开发说明，四份文档随本次提交保存。本次计划内的编码、隔离验证和部署已完成，剩余为上述真实生产运行验收。
