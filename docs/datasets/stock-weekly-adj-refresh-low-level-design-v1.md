# Prod周期行情供数LLD：既有周线合同与8月月线修订

更新：2026-10-15。已实现的周线运行合同保留；新码请求策略及8月月线修订为本轮待实施范围。DG清退不删除Prod数据。任务/状态以[总方案](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)为准，本轮仅文档。

## 0. 当前入口与事实源

DatasetDefinition在src/foundation/datasets/definitions/market_equity.py；resolver归一化时间和对象，DatasetExecutionPlan规定units；request_builders.py生成参数，executor/具名周线执行器写业务；Ops/TaskRun只受理意图与观测。foundation不得依赖ops。复用API/CLI，不新增worker lane、通用状态机或未审计配置。

日期模型周为friday、月为month_last_calendar_day，支持point_or_range但不代表每天都有行情。当前月请求builder复用周builder后固定freq=month，新码转换并未因此自动实现；须先审计对象来源、全市场回包和全部消费者，实施时一次迁移，不留旧码兜底。

<a id="source-field-contract"></a>
## 1. 业务字段与存储

复权源21列：ts_code,trade_date,end_date,freq,open,high,low,close,pre_close,open_qfq,high_qfq,low_qfq,close_qfq,open_hfq,high_hfq,low_hfq,close_hfq,vol,amount,change,pct_chg。Prod日期DATE；价格/change/qfq/hfq Numeric(18,4)、vol/amount Numeric(20,4)、pct_chg Numeric(10,4)。Raw键(ts_code,trade_date,freq)，Raw→Serving同键upsert，不做全表删除。DG导出日期为YYYYMMDD业务文本、Decimal字符串/NULL；api_name/fetched_at/raw_payload和内部时间不进入Parquet。

trade_date是业务周期，end_date是源计算版本，不能当采集时间或用请求截止覆盖。pre_close/pct_chg沿源除权参考口径，保留源单位。源doc365/336及MCP样本详见[月线LLD](../../lake_console/docs/design/dagster-stock-monthly-raw-onboarding-low-level-design-v1.md#1-数据卡来源与字段)。

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

按[月线LLD](../../lake_console/docs/design/dagster-stock-monthly-raw-onboarding-low-level-design-v1.md)仅处理两个Prod月线数据集的20260831/month源返回键，Raw及现行Serving同事务upsert；其余month/week键不变、未返回旧键保留/单列。不删除Prod两数据集，不修改表结构或扩大source参数，不沿用周线交接表作为月线新通道。

正式更新前完成单月完整源/新码/日线月末覆盖、计划及实际差异；沿现有维护入口，有界原unit恢复和TaskRun状态。DG复权月线异值目前会revision_required，必须先开发明确范围修订路径，不能假定重复提交自动覆盖。异常4月等先读源证实并列范围，未核实不自动重刷或宣布全部通过。

DG物理删除仅其未复权三个数据集根/相关活动代码，Prod因子、全部行情表、交接表、Web进度页和Ops调度不在删除清单。执行命令、数据库写入和部署另行审批，不因文档精简触发。

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
