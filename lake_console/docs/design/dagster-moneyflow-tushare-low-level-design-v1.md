# 七个 Tushare 资金流向数据集实施细则与 P0 收尾

> 2026-10-18 最新状态：补充方案§76/本LLD§71已提交78b444d5；01:03只读审计Prod七项16923条日期/键齐全，DG仍缺14111条/层。本次需补的范围专用入口及测试尚未开发，未补写DG；审计与边界见§71.10。

日期：2026-10-06；最近更新：2026-10-17。以下长段保留历次历史接入阶段说明，正式接续最新结果以§70.27.7为准。P3-F及P3历史物理文件阶段已关闭，实际结果见§28。P4首个数据集moneyflow_mkt_dc的资产/check/job/catalog、sensor、预演和事件执行器已完成，见§29～31；两日样本与全量正式登记均读回通过，见§32～33；本表839分区/1678物化/最近20日40检查齐全，moneyflow_ind_ths的独立资产/check/job/catalog及隔离验收已完成，见§34；三个STOPPED sensor及历史只读预演已完成，见§35，可恢复事件执行器和两日/全量冻结清单已完成，见§36，正式两日样本读回通过，见§37；全494日正式登记已读回通过，见§38，494分区/988物化/最近20来源日40检查齐全。moneyflow_cnt_ths独立资产/check/job/catalog及完整隔离验收已关闭，见§39.6；三个STOPPED sensor和历史只读预演已通过，见§40，可恢复历史登记执行器与两日/495日冻结清单已完成，见§41，完整当前门禁已复验并收尾，见§41.6，两日正式样本登记已读回通过，见§42；495日全量历史登记与收尾已完成，见§43，495分区/990物化/最近20来源日40检查齐全；moneyflow_ind_dc的独立资产/check/job/catalog及完整隔离验收已关闭，见§44.3，三个STOPPED sensor及历史预演、执行器和两日样本已完成，见§45～47；739日全量登记及本表P4历史接入已关闭，见§48，739分区/1478物化/最近20来源日40检查齐全；moneyflow_dc独立资产/check/job/catalog和完整隔离验收已完成，见§49；三个STOPPED sensor、readiness及739历史日只读预演已通过，见§50；可恢复登记执行器、隔离两日样本和739日冻结清单已通过，见§51；两日正式登记及读回已通过，见§52；739日全量登记及本表P4历史接入已关闭，见§53；739分区/1478物化/最近20来源日40检查齐全。moneyflow_ths独立资产/check/job/catalog及完整隔离验收已完成，见§54；三个STOPPED sensor/readiness与431历史日只读预演已通过，见§55；可恢复执行器、隔离两日样本和431日冻结清单已通过，见§56；两日正式登记及读回已通过，见§57；431日全量登记及本表P4历史接入已关闭，见§58；431分区/862物化/最近20来源日40检查齐全。此前阻塞记录保留；sensor启用和正式job未执行，整个P4未关闭，P5真实日更未执行。当前历史设计为七表日期批次直接生成每日候选，见§4和§19。P0/P1/P2验收记录保留；§17～18仅为旧路线记录，日期代码/隔离验收见§20，真实Prod查询见§21，索引及复测见§22。§25保留样本清单、§26保留正式两日样本、§27保留全量执行前的范围/成本与准确命令；最新进度以§28～63.3为准。moneyflow独立资产/check/job/catalog及完整隔离验收已通过，见§59；三个STOPPED sensor/readiness和4067历史日只读预演已通过，见§60；本表可恢复历史登记执行器、隔离两日样本和4067日五单元冻结清单已验收，见§61；正式两日登记、读回及零新增重放已通过，见§62.5；4067日五单元全量历史登记、读回和零新增重放已完成，见§63.3。

最新状态（2026-10-17 23:37）：数据接续49/49及21个sensor实际RUNNING均已验收，21次真实首次tick正常SKIPPED，98文件/49来源收据/100原生任务保持，P4关闭。尚待P5真实自动日更至少3交易日及异常/修订验收，不能提前关闭整体接入。

历史状态（2026-10-13 14:11）：上次执行记录和两份文档已提交cdfed8af，未推送。另一项历史复权因子开发仍在进行，DG共用检查及分钟指标代码有未提交修改，代码尚未稳定，见§68.4。10-08大盘尚未登记、运行或生成文件；21个自动更新触发器继续关闭，一次只跑一个资金流任务的设置保持。管理员“现在执行”的时间许可保留，待另一项开发完成并核对实际代码后继续。P4整体和P5未完成。

## 1. 硬口径和影响面

七个接口分别构成七个独立数据集；每个有独立 Raw/Silver、分区、job、sensor、check、checkpoint 和来源证明。全部只取 Tushare；历史以 Prod raw_tushare 为基线，未来由 DG 请求 Tushare。不引入 BIYING、融合、Prod日更就绪门禁、证券池裁剪或派生资金值。配额已满足；22:00登记当天分区、上海时区、正式SSE日历、不把登记等同采集成功。

当前调用链为资源→有界分页→writer→文件check→asset/job→sensor/catalog。CodeGraph explore命中了分页会话及BSE调用，但结果混入同名符号；已直接核验 resources.py、tushare_request_policy.py、duckdb_connection.py、cn_a_trade_day_sensor.py、dc_board_partition_sensor.py。现有无时钟门禁的calendar-only helper不能直接满足22:00；使用有same_day_register_start参数的注册helper，限定本次七个注册器，不改变既有注册器。

改动落点沿用原方案§12，并按数据集拆分模块。moneyflow_mkt_dc已完成资产、sensor及历史event执行器代码和隔离验收，两日样本及全量正式历史事件登记已通过；moneyflow_ind_ths已完成资产/check/job/catalog、三个STOPPED sensor、只读历史预演、可恢复事件执行器和冻结清单，两日及全量正式历史登记均已通过；moneyflow_cnt_ths与moneyflow_ind_dc全量历史登记也已关闭；moneyflow_dc独立资产/check/job/catalog及隔离验收已通过，三个STOPPED sensor、readiness及历史只读预演已通过；可恢复登记执行器和冻结清单、两日及全量正式历史登记均已通过；moneyflow_ths独立资产/check/job/catalog、sensor/readiness、执行器及全量正式历史登记已通过；moneyflow独立定义、三个STOPPED sensor/readiness和4067日只读预演已通过，本表正式登记执行器及清单留下一片。生产DatasetDefinition/request builder、Web/API、其他资产消费者均不改变。无子系统边界或依赖矩阵变更。

## 2. 日更完成、异常与修订

1. 每次执行单位=一个数据集×一个交易日。显式trade_date和合同fields，分页2000、offset递增；短页结束，恰好2000行必须继续请求结束页。日期错、缺字段、非法精度、重复键均停止，不能截断或静默去重。单轮业务行数≤20000；两轮行数不相加作为业务行数。
2. DC板块同一轮依次请求行业/概念/地域；未来日更每类均须非空并完整结束。历史只验证冻结的实际分类集合，不套三类规则。其余六接口非空；大盘恰好1行。带schema的空响应标记source_pending，不发布空文件或成功check；无schema是错误，不能转成空。
3. 第1轮全量业务数据持久化到候选；从最后一页完成起间隔60秒再读取第2轮，规范化后的key/业务字段摘要相同才通过source_stable。两轮共享64次请求、300秒预算，包含分类、间隔和重试。间隔是观测方法，不是源端最终性保证；成熟历史样本不能证明未来盘后从不修订。
4. 空结果/两轮不同/暂时网络错误可由下一tick重采；同日自动最多6次attempt，之后等待运营复核。分页或schema/身份/精度错误直接阻断，不重复盲试。既有暂时错误分类和有限退避复用，最多3次重试，最小请求间隔1秒；认证或契约错误不重试。已核对现有SDK 1.4.29客户端默认timeout=30秒，复用该资源不修改其他消费者；每页前检查剩余总预算，不足一个请求超时预算不领取新页。实测脚本的20秒只是本轮探测设置。
5. 数量异常是诊断而非全市场证明：与前5个已通过日期行数中位数比较，下降超过20%进入人工复核；前5日不足使用09-30已验证基线。DC板块按类比较。上升不因数量变化删行；仅执行最大行数和身份/schema规则。运营不能凭一个任意宽松开关放绿，须留下来源证据并修正规则/合同后重新检查。无需额外股票池/板块目录资产依赖。
6. 每日22:00之后，注册器首次tick登记当日；600秒是最小评估间隔，不保证墙钟22:00:00完成。停机恢复从正式日历补遗漏登记；登记不请求源站。更新sensor最近10个expected交易日、每tick最多1run，优先当天、再未完成日期、再到期修订复核；有active run则不重复。超过10日的未接续日期进入明确历史接续计划，不被热窗口吞掉。
7. 已完成日期在10日窗口内每天最多复核一次；游标按日期保存last_verified_at/attempt，目标<2KiB、硬上限8KiB。两轮稳定且与旧hash相同则不重写；hash不同生成新候选，完整check通过才逐文件提升，Silver仅消费对应Raw的新摘要。窗口外修订须显式修复。运营修复与自动writer互斥，不能靠run_key证明物理文件唯一writer。
8. 文件合同成功仅证明“显式请求已完整结束、观测稳定、存储合约通过”，不宣称源站涵盖全部证券。既有低覆盖样本证明不能用当前上市集合做全历史完整门禁。materialization和check记录来源行数、请求/分页/分类、两轮时间/hash、校验结果及更新身份；metadata使用既有builder和goldenshare命名空间。源修订的具体更新值只由源取得，不计算还原。

## 3. 截止、缺口及历史来源

七数据集此次规划C_d均固定2026-09-30，起点见下方卡片；不把执行日变动自动纳入已冻结历史计划。MCP SSE日历2026-10-01..12确认首个后续交易日2026-10-08。P3执行前重新读取范围内计数/hash，变化日期批次停止并保留证据，重新冻结后再读；C_d仍不自动漂移。P5开始时取(C_d,切换日]的expected日期减已就绪日期作为明确接续集合，先登记/补采全差集，再进入最近10日自动热窗口。

历史忠实复制Prod已有记录。已知11个整日缺口：5个源端仍不可取得，按管理员决定接受且不造空成功；6个源端可取得共10968条，另DC2026-05-19缺3143键。共14111个缺键列在收尾JSON，不自动混入Prod-only bootstrap。正式历史补录需要单独列精确日期/键/来源/行数并批准；P0不是补录执行授权。

DC2026-05-19：Prod2812、源5955，无Prod独有键；212个已有键的值不同。主要close211、pct_change173，少量资金字段；不能据此推断原因是复权或源修订。保持Prod基线并保留两侧值证据，不自动覆盖。补“缺键”和修“已有值”是两个独立执行范围，P3前对补录范围取得批准。

THS2024-12-19/20/23：源/Prod均2行，所有选定字段一致，忠实迁移并说明低覆盖。普通moneyflow2010-01-04/03-30分别834/830行，源/Prod逐键逐字段一致，不按今天证券数量补造。其余历史日期只证明冻结来源计数/键唯一，不声称逐证券源覆盖全量审计已做。

## 4. 日期批次、直接生成候选与预算（当前方案）

七表统一按日期批次读取：单个dataset、明确日期集合、年内最多20个交易日且合计最多100000行。来源读取unit、候选生成unit和复核unit采用同一日期集合；按日期/本数据集业务键排序，不以代码边界续跑。只读入口沿用现行psql脚本，每次一个短只读事务，SQL超时120秒。来源COPY在内存接收后直接生成每天的Raw/Silver候选，不保存来源CSV，不生成跨日期Parquet spool，不进行二次重分区。完整实现步骤见§19。

按P0逐日计数重新计算，日期批次共423个，普通moneyflow由旧141个代码块改为217个日期批次。初采和独立复核共846个读取事务，计划统计最多14个事务时连接基线860次；每事务按BEGIN/SET/读取/ROLLBACK四条语句计，读取3384条加统计56条，语句基线3440条。上述不含失败重试/恢复；新APPLY计划需冻结总尝试数、SQL/连接预算并持续扣账，不能重置累计时间。它们是旧计数样本上的规划值，正式执行前刷新来源统计并重新冻结。

使用既有connect_configured_duckdb和DuckDBConnectionSettings的局部profile：512MB、1线程、existing_no_spill、临时目录为当前staging操作目录、有效spill上限0B，禁止扩展下载；实际RSS上限768MiB。COPY按64KiB字节块接收，一次内存传输缓冲≤32MiB，先释放初采解析缓冲/关系，再开始复核，禁止两轮全批业务数据同时常驻Python或积攒全年数据。超过字节/行数/RSS上限时停止并保留已有候选，不落CSV或启用spill兜底。

空间预算仍为七表操作合计新增占用≤32GiB、首次准入空闲≥64GiB，包含每日两层候选、正式新增输出、失败现场和控制文件；来源CSV和spool文件数均为0。staging与正式路径必须同st_dev。恢复检查待完成批次空间并计入已有文件，不自动清理现场。原8GiB来源CSV和65536个spool文件预算退役，不能转换成额外可用空间。

累计总执行预算保留12小时，单次读取及单批转换各120秒，提升/事件最多100日期一批。846次读取均耗尽120秒的算术上限为28.2小时，说明必须以实际日期查询吞吐验证12小时准入，不能靠单次超时掩盖总预算。旧代码块22.673秒、53/80/160分钟及3～6小时估算不用于新路线。当前全历史耗时暂无法估算；新样本超预算则停止重新评估，不切回代码块，不擅自加索引或放宽限制。

checkpoint记录新路线版本、dataset、截止日、plan/schema/count hash、日期批次ID和明确日期集合、逐日来源证明、阶段、文件path/hash/rows、完成量/总量、累计时间/SQL/连接/字节和最后更新时间。没有after_key/through_key/last_key或spool阶段。候选生成、复核、逐文件提升分别记录；os.replace只承诺单文件原子性。事件补录仍在物理文件对账通过后另行批准，历史check事件默认最近20日/层、最多280，其余日期保留物理证据。

以下为P0计数证据重算的日期路线计划，不是当前Prod刷新或新路线性能实测。两层Parquet大小沿用单日样本外推，仅作空间参考；生成时仍逐文件计量。

| 数据集 | 行数/日期 | 日期批次=读/生成unit | 最大批行数 | 最大单日行数 | 正式两层文件 | 两层Parquet估算MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `moneyflow` | 14,089,300/4067 | 217 | 99,839 | 5,572 | 8134 | 2610.1 |
| `moneyflow_cnt_ths` | 192,009/495 | 26 | 7,890 | 395 | 990 | 22.9 |
| `moneyflow_dc` | 4,278,673/739 | 46 | 99,888 | 6,106 | 1478 | 542.0 |
| `moneyflow_ind_dc` | 364,012/739 | 40 | 20,620 | 1,031 | 1478 | 64.0 |
| `moneyflow_ind_ths` | 44,460/494 | 26 | 1,800 | 90 | 988 | 7.6 |
| `moneyflow_mkt_dc` | 839/839 | 44 | 20 | 1 | 1678 | 4.2 |
| `moneyflow_ths` | 2,191,645/431 | 24 | 99,070 | 5,222 | 862 | 272.2 |
| 合计 | 21,160,938/7804 | 423 | ≤100,000 | — | 15,608 | 3523.0 |

## 5. 配置审计与实现/测试落点

上述是已批准运行预算；当前历史常量/消费者尚待按§19迁移，统一集中于defs/run_contracts/moneyflow.py，无运营可编辑宽松开关，无新增env/数据库配置。消费者为request adapter、writer、bootstrap planner、check、七对sensor；代码发布/reload后生效，实际参数/预算/超限reason写入运行metadata。TUSHARE_TOKEN继续既有env，SDK1.4.29和现DG endpoint为实測基线；不打印token、不切换Prod凭据。历史C_d/来源hash仅属于冻结manifest，执行必须校验manifest，不从cursor猜来源阶段。目录沿用paths.py，正式raw/silver和独立staging，不用旧湖。

日更客户端使用既有资源身份与token、既有30秒请求超时；预算会话复用BoundedCodePageRequestSession.execute_pages并consume_page/retain_rows=False。金额优先保留十进制表示，禁止pandas固定15位序列化伪差异；不静默round。资源返回数值到Decimal(str(value))的合法性及不可表达整数/精度负例须在P1证明；若需要改共享resource合同，先完成全部query消费者审计再实施，本LLD不授予无审计共享修改。

| 硬口径 | 实现点（待开发） | 正反验证（待P1/P2） |
| --- | --- | --- |
| 七个独立身份，非一数据集七来源 | contracts、partitions、assets、jobs、catalog、sensor | 14资产/7分区合同；某数据集失败不得串改其他状态 |
| fields/date/分页及三分类 | source_readiness/moneyflow.py、Raw writer、bounded session | 短页/满页后结束页；缺scope/重复/错日/64次或300秒超限失败 |
| 十进制/schema/NULL/单位保真 | asset_column_schemas、Raw/Silver writers/checks | 真样本逐字段读回；浮点尾数/非法精度/NULL变0负例 |
| 22:00及日历权威 | partitions、moneyflow sensors、time-gated注册helper | 21:59不登记当日、22:00可登记、节假日不登记、停机漏日补登记；禁止无门禁calendar-only复用 |
| 60秒两轮稳定及异常/修订 | source collector、check、update cursor | 两轮一致/不一致/空/error；旧hash不重写、新hash推进对应Silver；不把稳定当全证券完整 |
| 不访问Prod日更/Ops池/其他源 | Raw source、job selection | fakeclient请求白名单/负向静态扫描；只含本数据集Raw或Silver选择 |
| 有界bootstrap、恢复和原子文件 | bootstrap planner/file/event模块 | 取消/退出/恢复/幂等/冲突/不同st_dev；文件失败不得绿事件；P3真实小样本再验收 |
| sensor热路径与唯一writer | guard、bounded batch readiness、统一run_key/cursor builder | ≤10日/1run、active互斥、cursor≤8KiB、无全历史深扫；未绿Raw不得触发Silver |

不新增通用状态数据库或summary资产；运行状态用现有run/check/materialization/cursor。P1不注册正式分区、写正式Lake/事件、执行job或启用sensor。测试模块按tests/test_moneyflow_{d}.py逐数据集开发，fixture隔离；共享纯合同/分页测试限定资金流消费者。测试不能访问正式instance/token/Lake。

## 6. 七张逐数据集 7A 实施卡

每张卡与原方案§4显式字段顺序联合使用。无对象池；运营输入为单日/明确日期范围，日期范围在planner展开为日unit，不将ts_code/content_type/limit/offset暴露为任意运营过滤。Raw/Silver字段同名，不添加业务派生；日期唯一类型变更。所有业务列可空性按真实Prod列记录；关键身份必须非空，DC板块ts_code允许空。字段描述必须沿源文档标注原单位，definition schema是稳定事实，运行观察schema不能替代。

### `moneyflow`

- 来源：Prod `raw_tushare.moneyflow`（只读bootstrap）/ Tushare `moneyflow`（日更）；起点2010-01-04、C_d=2026-09-30；4067日期、14,089,300行，整日缺口无。唯一键 `trade_date+ts_code`；金额单位万元/量手，负值/NULL不重算或补0。
- 定义：`raw_tushare_moneyflow`、`silver_moneyflow`；专属分区`cn_a_moneyflow_trade_days`；job分别`raw_tushare_moneyflow_update_job`、`silver_moneyflow_update_job`，更新sensor分别为job名加`_sensor`，注册器`cn_a_moneyflow_trade_day_sensor`；check分别`raw_tushare_moneyflow_file_contract_check`、`silver_moneyflow_standardization_check`。
- 路径：`raw/tushare/moneyflow/trade_date=YYYY-MM-DD/part-000.parquet`和`silver/moneyflow/moneyflow/trade_date=YYYY-MM-DD/part-000.parquet`；run候选位于`data_lake_staging/moneyflow/<operation_id>/moneyflow`。Silver仅依赖本Raw。
- 请求：显式全部下表字段；单日trade_date、limit2000、offset0起，不按代码展开；实际09-30每轮3请求/5572行，日更两轮最多64次/300秒/每轮20000行，空不成功。默认/显式/关键字段、无参数/对象/点/区间/分页样本见P0证据对应api条目，不以近期无参响应替代全历史。
- 7A实测：源/归一化/Raw/Silver读回均5572行，reject0、差异0；CSV856108字节、Raw541201、Silver541177；隔离转换0.3281秒。当前bootstrap为217日期批次/8134正式文件；旧141代码块路线已退役；只读事务/512MB/0spill/20日期及100000行边界见§4。失败最小重跑源unit或单日候选，checkpoint按实际文件；P3才验证正式提升和中断恢复。

| 字段（原顺序） | Prod类型/可空 | Raw物理类型 | Silver物理类型 | 转换与消费者 |
| --- | --- | --- | --- | --- |
| `ts_code` | VARCHAR/NO | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `trade_date` | DATE/NO | VARCHAR | DATE | YYYYMMDD→DATE；分区日一致；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_vol` | BIGINT/YES | BIGINT | BIGINT | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount` | DECIMAL(20,4)/YES | DECIMAL(20,4) | DECIMAL(20,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `sell_sm_vol` | BIGINT/YES | BIGINT | BIGINT | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `sell_sm_amount` | DECIMAL(20,4)/YES | DECIMAL(20,4) | DECIMAL(20,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_vol` | BIGINT/YES | BIGINT | BIGINT | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_amount` | DECIMAL(20,4)/YES | DECIMAL(20,4) | DECIMAL(20,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `sell_md_vol` | BIGINT/YES | BIGINT | BIGINT | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `sell_md_amount` | DECIMAL(20,4)/YES | DECIMAL(20,4) | DECIMAL(20,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_vol` | BIGINT/YES | BIGINT | BIGINT | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_amount` | DECIMAL(20,4)/YES | DECIMAL(20,4) | DECIMAL(20,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `sell_lg_vol` | BIGINT/YES | BIGINT | BIGINT | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `sell_lg_amount` | DECIMAL(20,4)/YES | DECIMAL(20,4) | DECIMAL(20,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_elg_vol` | BIGINT/YES | BIGINT | BIGINT | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_elg_amount` | DECIMAL(20,4)/YES | DECIMAL(20,4) | DECIMAL(20,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `sell_elg_vol` | BIGINT/YES | BIGINT | BIGINT | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `sell_elg_amount` | DECIMAL(20,4)/YES | DECIMAL(20,4) | DECIMAL(20,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_mf_vol` | BIGINT/YES | BIGINT | BIGINT | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_mf_amount` | DECIMAL(20,4)/YES | DECIMAL(20,4) | DECIMAL(20,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |

### `moneyflow_cnt_ths`

- 来源：Prod `raw_tushare.moneyflow_cnt_ths`（只读bootstrap）/ Tushare `moneyflow_cnt_ths`（日更）；起点2024-09-10、C_d=2026-09-30；495日期、192,009行，整日缺口2024-11-04, 2025-01-20, 2026-07-09。唯一键 `trade_date+ts_code`；金额单位亿元，负值/NULL不重算或补0。
- 定义：`raw_tushare_moneyflow_cnt_ths`、`silver_moneyflow_cnt_ths`；专属分区`cn_a_moneyflow_cnt_ths_trade_days`；job分别`raw_tushare_moneyflow_cnt_ths_update_job`、`silver_moneyflow_cnt_ths_update_job`，更新sensor分别为job名加`_sensor`，注册器`cn_a_moneyflow_cnt_ths_trade_day_sensor`；check分别`raw_tushare_moneyflow_cnt_ths_file_contract_check`、`silver_moneyflow_cnt_ths_standardization_check`。
- 路径：`raw/tushare/moneyflow_cnt_ths/trade_date=YYYY-MM-DD/part-000.parquet`和`silver/moneyflow/moneyflow_cnt_ths/trade_date=YYYY-MM-DD/part-000.parquet`；run候选位于`data_lake_staging/moneyflow/<operation_id>/moneyflow_cnt_ths`。Silver仅依赖本Raw。
- 请求：显式全部下表字段；单日trade_date、limit2000、offset0起，不按代码展开；实际09-30每轮1请求/387行，日更两轮最多64次/300秒/每轮20000行，空不成功。默认/显式/关键字段、无参数/对象/点/区间/分页样本见P0证据对应api条目，不以近期无参响应替代全历史。
- 7A实测：源/归一化/Raw/Silver读回均387行，reject0、差异0；CSV41312字节、Raw24197、Silver24173；隔离转换0.0105秒。bootstrap 26导出unit/26写窗口/990正式文件；只读事务/512MB/0spill/20日期及100000行边界见§4。失败最小重跑源unit或单日候选，checkpoint按实际文件；P3才验证正式提升和中断恢复。

| 字段（原顺序） | Prod类型/可空 | Raw物理类型 | Silver物理类型 | 转换与消费者 |
| --- | --- | --- | --- | --- |
| `trade_date` | DATE/NO | VARCHAR | DATE | YYYYMMDD→DATE；分区日一致；Raw/Silver writer与check，暂无新增业务消费者 |
| `ts_code` | VARCHAR/NO | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `name` | VARCHAR/YES | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `lead_stock` | VARCHAR/YES | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `close_price` | DECIMAL(18,4)/YES | DECIMAL(18,4) | DECIMAL(18,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `pct_change` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `industry_index` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `company_num` | INTEGER/YES | INTEGER | INTEGER | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `pct_change_stock` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_buy_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_sell_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |

### `moneyflow_dc`

- 来源：Prod `raw_tushare.moneyflow_dc`（只读bootstrap）/ Tushare `moneyflow_dc`（日更）；起点2023-09-11、C_d=2026-09-30；739日期、4,278,673行，整日缺口2023-11-22。唯一键 `trade_date+ts_code`；金额单位万元，负值/NULL不重算或补0。
- 定义：`raw_tushare_moneyflow_dc`、`silver_moneyflow_dc`；专属分区`cn_a_moneyflow_dc_trade_days`；job分别`raw_tushare_moneyflow_dc_update_job`、`silver_moneyflow_dc_update_job`，更新sensor分别为job名加`_sensor`，注册器`cn_a_moneyflow_dc_trade_day_sensor`；check分别`raw_tushare_moneyflow_dc_file_contract_check`、`silver_moneyflow_dc_standardization_check`。
- 路径：`raw/tushare/moneyflow_dc/trade_date=YYYY-MM-DD/part-000.parquet`和`silver/moneyflow/moneyflow_dc/trade_date=YYYY-MM-DD/part-000.parquet`；run候选位于`data_lake_staging/moneyflow/<operation_id>/moneyflow_dc`。Silver仅依赖本Raw。
- 请求：显式全部下表字段；单日trade_date、limit2000、offset0起，不按代码展开；实际09-30每轮4请求/6024行，日更两轮最多64次/300秒/每轮20000行，空不成功。默认/显式/关键字段、无参数/对象/点/区间/分页样本见P0证据对应api条目，不以近期无参响应替代全历史。
- 7A实测：源/归一化/Raw/Silver读回均6024行，reject0、差异0；CSV786991字节、Raw400078、Silver400054；隔离转换0.0537秒。bootstrap 46导出unit/46写窗口/1478正式文件；只读事务/512MB/0spill/20日期及100000行边界见§4。失败最小重跑源unit或单日候选，checkpoint按实际文件；P3才验证正式提升和中断恢复。

| 字段（原顺序） | Prod类型/可空 | Raw物理类型 | Silver物理类型 | 转换与消费者 |
| --- | --- | --- | --- | --- |
| `trade_date` | DATE/NO | VARCHAR | DATE | YYYYMMDD→DATE；分区日一致；Raw/Silver writer与check，暂无新增业务消费者 |
| `ts_code` | VARCHAR/NO | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `name` | VARCHAR/YES | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `pct_change` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `close` | DECIMAL(18,4)/YES | DECIMAL(18,4) | DECIMAL(18,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_elg_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_elg_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |

### `moneyflow_ind_dc`

- 来源：Prod `raw_tushare.moneyflow_ind_dc`（只读bootstrap）/ Tushare `moneyflow_ind_dc`（日更）；起点2023-09-12、C_d=2026-09-30；739日期、364,012行，整日缺口无。唯一键 `trade_date+content_type+name`；金额单位元，负值/NULL不重算或补0。
- 定义：`raw_tushare_moneyflow_ind_dc`、`silver_moneyflow_ind_dc`；专属分区`cn_a_moneyflow_ind_dc_trade_days`；job分别`raw_tushare_moneyflow_ind_dc_update_job`、`silver_moneyflow_ind_dc_update_job`，更新sensor分别为job名加`_sensor`，注册器`cn_a_moneyflow_ind_dc_trade_day_sensor`；check分别`raw_tushare_moneyflow_ind_dc_file_contract_check`、`silver_moneyflow_ind_dc_standardization_check`。
- 路径：`raw/tushare/moneyflow_ind_dc/trade_date=YYYY-MM-DD/part-000.parquet`和`silver/moneyflow/moneyflow_ind_dc/trade_date=YYYY-MM-DD/part-000.parquet`；run候选位于`data_lake_staging/moneyflow/<operation_id>/moneyflow_ind_dc`。Silver仅依赖本Raw。
- 请求：显式全部下表字段；单日trade_date、limit2000、offset0起，三分类fan-out，每类非空；实际09-30每轮3请求/1031行，日更两轮最多64次/300秒/每轮20000行，空不成功。默认/显式/关键字段、无参数/对象/点/区间/分页样本见P0证据对应api条目，不以近期无参响应替代全历史。
- 7A实测：源/归一化/Raw/Silver读回均1031行，reject0、差异0；CSV191269字节、Raw95067、Silver95043；隔离转换0.0346秒。bootstrap 40导出unit/40写窗口/1478正式文件；只读事务/512MB/0spill/20日期及100000行边界见§4。失败最小重跑源unit或单日候选，checkpoint按实际文件；P3才验证正式提升和中断恢复。

| 字段（原顺序） | Prod类型/可空 | Raw物理类型 | Silver物理类型 | 转换与消费者 |
| --- | --- | --- | --- | --- |
| `trade_date` | DATE/NO | VARCHAR | DATE | YYYYMMDD→DATE；分区日一致；Raw/Silver writer与check，暂无新增业务消费者 |
| `content_type` | VARCHAR/NO | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `ts_code` | VARCHAR/YES | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `name` | VARCHAR/NO | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `pct_change` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `close` | DECIMAL(18,4)/YES | DECIMAL(18,4) | DECIMAL(18,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_elg_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_elg_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount_stock` | VARCHAR/YES | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `rank` | INTEGER/YES | INTEGER | INTEGER | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |

### `moneyflow_ind_ths`

- 来源：Prod `raw_tushare.moneyflow_ind_ths`（只读bootstrap）/ Tushare `moneyflow_ind_ths`（日更）；起点2024-09-10、C_d=2026-09-30；494日期、44,460行，整日缺口2024-11-04, 2025-01-20, 2026-07-09, 2026-08-05。唯一键 `trade_date+ts_code`；金额单位亿元，负值/NULL不重算或补0。
- 定义：`raw_tushare_moneyflow_ind_ths`、`silver_moneyflow_ind_ths`；专属分区`cn_a_moneyflow_ind_ths_trade_days`；job分别`raw_tushare_moneyflow_ind_ths_update_job`、`silver_moneyflow_ind_ths_update_job`，更新sensor分别为job名加`_sensor`，注册器`cn_a_moneyflow_ind_ths_trade_day_sensor`；check分别`raw_tushare_moneyflow_ind_ths_file_contract_check`、`silver_moneyflow_ind_ths_standardization_check`。
- 路径：`raw/tushare/moneyflow_ind_ths/trade_date=YYYY-MM-DD/part-000.parquet`和`silver/moneyflow/moneyflow_ind_ths/trade_date=YYYY-MM-DD/part-000.parquet`；run候选位于`data_lake_staging/moneyflow/<operation_id>/moneyflow_ind_ths`。Silver仅依赖本Raw。
- 请求：显式全部下表字段；单日trade_date、limit2000、offset0起，不按代码展开；实际09-30每轮1请求/90行，日更两轮最多64次/300秒/每轮20000行，空不成功。默认/显式/关键字段、无参数/对象/点/区间/分页样本见P0证据对应api条目，不以近期无参响应替代全历史。
- 7A实测：源/归一化/Raw/Silver读回均90行，reject0、差异0；CSV9427字节、Raw8078、Silver8054；隔离转换0.0062秒。bootstrap 26导出unit/26写窗口/988正式文件；只读事务/512MB/0spill/20日期及100000行边界见§4。失败最小重跑源unit或单日候选，checkpoint按实际文件；P3才验证正式提升和中断恢复。

| 字段（原顺序） | Prod类型/可空 | Raw物理类型 | Silver物理类型 | 转换与消费者 |
| --- | --- | --- | --- | --- |
| `trade_date` | DATE/NO | VARCHAR | DATE | YYYYMMDD→DATE；分区日一致；Raw/Silver writer与check，暂无新增业务消费者 |
| `ts_code` | VARCHAR/NO | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `industry` | VARCHAR/YES | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `lead_stock` | VARCHAR/YES | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `close` | DECIMAL(18,4)/YES | DECIMAL(18,4) | DECIMAL(18,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `pct_change` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `company_num` | INTEGER/YES | INTEGER | INTEGER | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `pct_change_stock` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `close_price` | DECIMAL(18,4)/YES | DECIMAL(18,4) | DECIMAL(18,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_buy_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_sell_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |

### `moneyflow_mkt_dc`

- 来源：Prod `raw_tushare.moneyflow_mkt_dc`（只读bootstrap）/ Tushare `moneyflow_mkt_dc`（日更）；起点2023-04-17、C_d=2026-09-30；839日期、839行，整日缺口2026-07-09。唯一键 `trade_date`；金额单位元，负值/NULL不重算或补0。
- 定义：`raw_tushare_moneyflow_mkt_dc`、`silver_moneyflow_mkt_dc`；专属分区`cn_a_moneyflow_mkt_dc_trade_days`；job分别`raw_tushare_moneyflow_mkt_dc_update_job`、`silver_moneyflow_mkt_dc_update_job`，更新sensor分别为job名加`_sensor`，注册器`cn_a_moneyflow_mkt_dc_trade_day_sensor`；check分别`raw_tushare_moneyflow_mkt_dc_file_contract_check`、`silver_moneyflow_mkt_dc_standardization_check`。
- 路径：`raw/tushare/moneyflow_mkt_dc/trade_date=YYYY-MM-DD/part-000.parquet`和`silver/moneyflow/moneyflow_mkt_dc/trade_date=YYYY-MM-DD/part-000.parquet`；run候选位于`data_lake_staging/moneyflow/<operation_id>/moneyflow_mkt_dc`。Silver仅依赖本Raw。
- 请求：显式全部下表字段；单日trade_date、limit2000、offset0起，不按代码展开；实际09-30每轮1请求/1行，日更两轮最多64次/300秒/每轮20000行，空不成功。默认/显式/关键字段、无参数/对象/点/区间/分页样本见P0证据对应api条目，不以近期无参响应替代全历史。
- 7A实测：源/归一化/Raw/Silver读回均1行，reject0、差异0；CSV388字节、Raw2612、Silver2588；隔离转换0.0042秒。bootstrap 44导出unit/44写窗口/1678正式文件；只读事务/512MB/0spill/20日期及100000行边界见§4。失败最小重跑源unit或单日候选，checkpoint按实际文件；P3才验证正式提升和中断恢复。

| 字段（原顺序） | Prod类型/可空 | Raw物理类型 | Silver物理类型 | 转换与消费者 |
| --- | --- | --- | --- | --- |
| `trade_date` | DATE/NO | VARCHAR | DATE | YYYYMMDD→DATE；分区日一致；Raw/Silver writer与check，暂无新增业务消费者 |
| `close_sh` | DECIMAL(18,4)/YES | DECIMAL(18,4) | DECIMAL(18,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `pct_change_sh` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `close_sz` | DECIMAL(18,4)/YES | DECIMAL(18,4) | DECIMAL(18,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `pct_change_sz` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_elg_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_elg_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |

### `moneyflow_ths`

- 来源：Prod `raw_tushare.moneyflow_ths`（只读bootstrap）/ Tushare `moneyflow_ths`（日更）；起点2024-12-19、C_d=2026-09-30；431日期、2,191,645行，整日缺口2026-07-06, 2026-07-09。唯一键 `trade_date+ts_code`；金额单位万元，负值/NULL不重算或补0。
- 定义：`raw_tushare_moneyflow_ths`、`silver_moneyflow_ths`；专属分区`cn_a_moneyflow_ths_trade_days`；job分别`raw_tushare_moneyflow_ths_update_job`、`silver_moneyflow_ths_update_job`，更新sensor分别为job名加`_sensor`，注册器`cn_a_moneyflow_ths_trade_day_sensor`；check分别`raw_tushare_moneyflow_ths_file_contract_check`、`silver_moneyflow_ths_standardization_check`。
- 路径：`raw/tushare/moneyflow_ths/trade_date=YYYY-MM-DD/part-000.parquet`和`silver/moneyflow/moneyflow_ths/trade_date=YYYY-MM-DD/part-000.parquet`；run候选位于`data_lake_staging/moneyflow/<operation_id>/moneyflow_ths`。Silver仅依赖本Raw。
- 请求：显式全部下表字段；单日trade_date、limit2000、offset0起，不按代码展开；实际09-30每轮3请求/5215行，日更两轮最多64次/300秒/每轮20000行，空不成功。默认/显式/关键字段、无参数/对象/点/区间/分页样本见P0证据对应api条目，不以近期无参响应替代全历史。
- 7A实测：源/归一化/Raw/Silver读回均5215行，reject0、差异0；CSV618534字节、Raw339557、Silver339533；隔离转换0.0434秒。bootstrap 24导出unit/24写窗口/862正式文件；只读事务/512MB/0spill/20日期及100000行边界见§4。失败最小重跑源unit或单日候选，checkpoint按实际文件；P3才验证正式提升和中断恢复。

| 字段（原顺序） | Prod类型/可空 | Raw物理类型 | Silver物理类型 | 转换与消费者 |
| --- | --- | --- | --- | --- |
| `trade_date` | DATE/NO | VARCHAR | DATE | YYYYMMDD→DATE；分区日一致；Raw/Silver writer与check，暂无新增业务消费者 |
| `ts_code` | VARCHAR/NO | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `name` | VARCHAR/YES | VARCHAR | VARCHAR | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `pct_change` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `latest` | DECIMAL(18,4)/YES | DECIMAL(18,4) | DECIMAL(18,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `net_d5_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_lg_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_md_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount` | DECIMAL(24,4)/YES | DECIMAL(24,4) | DECIMAL(24,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |
| `buy_sm_amount_rate` | DECIMAL(10,4)/YES | DECIMAL(10,4) | DECIMAL(10,4) | 原值/原单位；无改名或过滤；Raw/Silver writer与check，暂无新增业务消费者 |

## 7. 收尾验收与后续阶段

P0证据：17个历史日期/接口复核；6个源端可补整日+1个缺键日明确，5个源不可取得缺口接受；DC已有值差异独立保留；THS最早3日及普通2个低覆盖日逐字段一致。七接口09-30重测两轮，各18320行/32次总请求，跨轮至少60秒间隔且全部key/业务摘要一致。七数据集隔离列式转换18320行无reject/差异；单日期实验峰值RSS约144MiB，原100000行样本约190MiB；它们不是正式全历史峰值证明。

P0 Go范围：源参数/字段/身份/分页、已知历史差异清单、日更完成与异常设计、截止交接、逐数据集7A和有界性能设计。剩余实测门禁明确归P1/P2隔离测试、P3历史代表样本/正式apply、P4事件/definitions集成、P5日更真实运行至少3个交易日；这些没有冒充完成。首个P1目标是moneyflow_mkt_dc，之后才行业/概念/东财板块，一轮一个数据集。

历史补录及212个旧值处理仍需P3阶段明确执行范围；当前默认忠实Prod已有值，不影响P1编码准备。开发授权、正式Lake/事件/分区写入、启用自动化均单独按阶段批准。本段为P0收尾时的历史状态：当时未自动进入P1。其后管理员明确授权P1，进度见§8；没有安装依赖或写业务库、正式DG状态。

证据：[收尾JSON](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p0_closeout_20261006.json)、[原P0合同](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-p0-contract-audit-v1.md)、[原方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-onboarding-plan-v1.md)。平台依据：[Dagster分区](https://docs.dagster.io/guides/build/partitions-and-backfills)、[checks](https://docs.dagster.io/guides/test/asset-checks)，本地编码/schema/性能/模板规则优先落实当前项目语义。

## 8. P1-A moneyflow_mkt_dc候选能力验收（2026-10-06）

目标与依据：管理员“提交修改，然后进入P1”；遵循本文§3/4/5及原方案，一轮只做大盘资金流。以下代码路径相对于lake_console/orchestrator。

| 硬口径 | 当前代码 | 验收证据 |
| --- | --- | --- |
| 15字段、日期键、单日1行、十进制精度不静默舍入 | run_contracts/asset_column_schemas.py与run_contracts/moneyflow.py | 固定字段、错日、非法日、缺字段、多行、非法数值、溢出和不可安全表示浮点负例；NULL和负值保留 |
| 两轮完整读取、至少60秒间隔、共用64次/300秒预算 | source_readiness/moneyflow.py，复用BoundedCodePageRequestSession | 稳定、空结果、两轮变化、共享请求预算、超时预算与等待取消测试 |
| 第一轮先持久化候选；只有第二轮相同才ready | io/moneyflow_raw_writer.py | 变化/取消保留首轮候选，receipt仍collecting；重用operation拒绝覆盖 |
| Silver仅转换日期类型，不修改源数值 | io/moneyflow_silver_writer.py | Raw VARCHAR到Silver DATE，全部金额/NULL逐行双向EXCEPT一致；文件篡改阻断 |
| 物理schema、单行和日期严格检查 | checks/moneyflow.py纯函数，无Dagster装饰器 | 损坏文件、错日、类型/业务值变化阻断 |
| 局部512MB/1线程、0spill、不自动安装扩展 | run_contracts/moneyflow.py经既有DuckDB设置对象传递 | effective settings检查0bytes与extensions关闭；共享资源默认不变 |
| 候选禁止落正式Lake，隔离且不覆盖 | 两个writer路径预检与目录独占创建 | 正式路径、Volumes根、相对路径、路径穿越、根及子目录symlink负例；Silver正式路径在读取前拒绝 |

测试文件tests/test_moneyflow_moneyflow_mkt_dc.py使用fake Tushare、fake clock与临时目录，包含P0已保存的真实大盘样本读回；本轮未再次请求源站，60秒测试由虚拟时钟推进，不能作为真实新日更运行证据。大盘正常路径为两次请求、每轮1行，常驻行缓存最多1行；文件和读取数量固定有界。失败不提升正式文件，不发成功事件。候选receipt与sha256只作为本切片证据；跨进程续跑、原子正式提升及正式事件恢复留给P3/P4。

验证：大盘27项与共享请求策略15项，共42项通过；现有asset governance 12项及474子测试通过；run contract static gates 113项通过，后二者使用现有stock_suspend_confirmed_test_runner保护入口。初次直接pytest缺少保护support模块；正确入口初次发现新增模块不在冻结清单，本轮仅把五个新增纯模块加入CONSUMER_SOURCE_FILES精确只读清单，复测通过，网络及正式资源保护不变。

CodeGraph使用codegraph_explore分析fetch_daily_basic_pages相关采集入口、共享请求会话及消费者，结合当前resources、分页会话、DuckDB连接、路径、schema和测试实现逐项复核；开发后sync/status。影响面限定资金流纯合同/采集/候选writer/检查与精确测试清单，未修改共享Tushare资源行为、Prod DatasetDefinition、API或前端，未改变子系统依赖矩阵。当前未产生资金流active asset/check，治理回归证明现有catalog/check对账保持一致；正式编排边界尚待P4集成验收。

状态：本轮首个候选能力切片已通过隔离验收，已提交0bd4de4f；整个P1未完成。其余六个数据集及日更正式执行未覆盖。下一切片为moneyflow_ind_ths；bootstrap、正式提升、资产编排与至少3个交易日日更观察仍按P3/P4/P5门禁分别验收。

## 9. P1-B moneyflow_ind_ths实施约束（开发前冻结）

依据本文§6行业7A与原方案，当前仅实现候选能力，不接入正式Definitions或调度。12字段、trade_date+ts_code唯一键、金额亿元、业务NULL/负数原样保留；不能用行业股票求和替代来源。全部显式fields，单日trade_date+limit2000+offset请求，不按板块代码展开。短页结束，整页仍取结束页；跨页重复、错日、缺字段、非法精度阻断。两轮至少间隔60秒，完整业务键与全部字段集合一致才ready，顺序改变不视为变化。

复用现有资金流候选路径/连接/receipt能力前，使用CodeGraph检查其大盘调用方和测试；抽出实际共用的候选目录/连接/文件hash/receipt模块，所有已有大盘消费者同步迁移，不保留双轨。新增行业合同、分页采集、Raw/Silver writer和纯物理check；共享TushareResource及分页会话不改。逐页JSON来源先持久化，DuckDB SQL负责字段、数值、键校验和列式写Parquet，不在Python累积全轮数据或逐行转换。

| 性能与执行边界 | 冻结值及验收方式 |
| --- | --- |
| unit/范围 | 一个行业数据集、一个日分区；无枚举展开。真实20260930样本90行/12字段，本轮MCP复核90行；P0已核验默认、显式与关键身份字段、无时间/对象/点/区间及SDK分页 |
| 请求/行数 | 页2000；通常两轮各1次共2次；每轮最多20000行（10满页+结束空页），最多两轮22次，无重试；重试合计纳入既有64次/300秒预算，不重置 |
| 内存/扫描 | Python只保留单页；DuckDB局部512MB/1线程/0spill，逐页JSON→typed temp table，最多20000行每轮；数值与重复用SQL，最终两轮双向EXCEPT，排序写文件 |
| 写入/文件/恢复 | 仅隔离候选；最多20个非空页JSON、两个Raw（第二个用于复核）、一个Silver和一个receipt，共24文件；单页/单文件持久化，operation独占目录，错误保留候选；正式原子提升和跨进程恢复P3实现 |
| 时间/空间 | 两轮最少60秒间隔；300秒拒绝线包含请求与转换；沿用日更既有30秒超时、每页前后取消检查，不改变配额。以90行9.4KiB CSV样本外推双轮20000行约4MiB来源，候选与临时表加余量按32MiB规划；512MB/0spill超限直接失败，禁止扩大配置 |
| 正反验收 | tmp目录/fake source与clock、真实公开90行fixture读回，分页满页与终止页、乱序稳定、字段或键变化、同数量换键、跨页重复、超行数、精度/整数/NULL/负值、预算/取消、篡改与正式路径拒绝；大盘回归证明抽取复用行为保持 |

本轮不执行真实DG job、动态分区、正式Lake或event写入；新日更及历史缺口处理仍留给后续对应阶段。以下为本轮完成后的验收记录。

### 9.1 实现与硬口径对账

| 合同 | 代码落点（相对orchestrator） | 正反证据 |
| --- | --- | --- |
| 独立行业身份、12字段、两层类型、亿元和源值 | run_contracts/asset_column_schemas.py与moneyflow_ind_ths.py | 真实90行读回；白酒源50/34/15原样保留，不改算成16；业务None与负值保留，非法NaN/Infinity阻断 |
| 分页、满页终止、共享预算、60秒间隔与取消 | source_readiness/moneyflow_ind_ths.py | 2000行需结束页；每轮20000行成功、再多1行拒绝；64次/300秒共享，重试计数不重置，Silver合计执行耗时也计入300秒；逐页及等待取消均阻断 |
| 逐页持久化、严格精度/整数、键唯一 | io/moneyflow_ind_ths_raw_writer.py与run_contracts/moneyflow_ind_ths.py | 错日、空键、缺字段/多字段、跨页重复、舍入/溢出、boolean、不可表达float负例；reject reason带最多3个字段/键/数值样本 |
| 完整两轮集合一致，顺序独立 | checks/moneyflow_ind_ths.py | 乱序通过；同数量换键/改值与数量变化拒绝，首轮Raw和页证据保留，receipt仍collecting |
| Silver仅改日期，来源证明完整 | io/moneyflow_ind_ths_silver_writer.py | Raw/复核文件hash及物理合同再次读回，双向EXCEPT；Silver逐字段对账、篡改/损坏/重复/错日及覆盖冲突负例 |
| 隔离候选、内存和路径保护 | io/moneyflow_candidates.py与run_contracts/moneyflow.py | 正式/穿越/相对/symlink路径拒绝；512MB/1线程/0spill沿用；行业页前后及Silver检查768MiB进程峰值，超限阻断，不放宽 |
| 不新增正式编排或Prod依赖 | 仅纯helper与测试；现有保护runner精确只读清单 | 现有catalog/check治理对账与静态门禁通过；无资金流asset/check装饰器、job/sensor/分区注册、API或前端改动 |

共用目录、连接、file hash与receipt抽到io/moneyflow_candidates.py，大盘全部消费者及测试同步迁移；旧market_candidate_directory/connection与write_market_receipt引用已清零，没有别名或兼容双轨。使用CodeGraph codegraph_explore核验上述调用链、共享execute_pages会话及测试影响；未改共享资源/paging实现或子系统依赖矩阵。正式资产编排与其跨模块消费者尚待P4单独验收。

配置对账：MONEYFLOW_MAX_ROWS_PER_ROUND=20000和MONEYFLOW_MAX_RSS_BYTES=768MiB均是§4/5已批准预算的集中代码常量，位于run_contracts/moneyflow.py，无新增env/Settings/数据库来源。前者由行业collector及物理check消费；后者由行业collector和Silver writer消费，基于进程peak RSS拒绝；依赖既有页2000/64次/300秒与DuckDB512MB/1线程/0spill，代码发布后生效。实际rows/requests/retries/elapsed_ms/peak_rss_bytes写候选receipt，P4再接运行metadata；测试覆盖等于/超过行上限、内存超限与共享预算。MONEYFLOW_FIXTURE_CHILD仅隔离测试入口使用，不是生产配置或可放宽预算开关。

### 9.2 来源与隔离验收

2026-10-06通过tushareMcp复核moneyflow_ind_ths：20260930显式全部12字段90行；默认字段90行且全字段与显式结果相同；显式trade_date/ts_code及对象881142.TI返回1行，身份一致。MCP没有limit/offset参数入口，分页沿用同日P0保存的SDK实测证据，本轮以分页替身正反验证实现，不伪称MCP实测分页。无时间/对象/点/区间行为引用P0冻结证据，未重新跑全历史。公开90行结果保存在tests/fixtures/moneyflow_ind_ths_20260930.json。

新行业53项、大盘27项、共享策略15项，共95项隔离测试通过。现有治理回归12项及474子测试通过，合同静态门禁113项通过，后二者使用现有保护测试启动器，仅补充6个新纯模块精确只读清单；没有扩大网络、正式资源或目录权限。源端/归一化/Raw/Silver为90/90/90/90，reject0、全字段差异0；测试不把行业数固定为90。非有限数值拒绝；只把显式None作为业务NULL，不猜测非有限值的来源含义。

新进程代表样本：真实90行fixture两轮→Raw/Silver读回0.967秒（含pytest启动）、峰值RSS182.06MiB；每轮20000行/22请求/两层读回1.865秒（含pytest启动）、峰值621.12MiB，低于768MiB拒绝线。时间间隔使用fake clock，以上耗时不包含真实60秒等待或网络，不能用于承诺真实日更耗时。两个大规模fixture在清空环境的新Python进程运行：一次合并运行曾因不同fixture累积进程原生分配峰值触发拒绝线，单次大样本独立执行通过；未提高预算，也未在测试中关闭内存保护。/usr/bin/time -l的内核统计读取被沙箱限制，测量改用Python getrusage，实际数值明确来自测试进程。

历史状态：P1-B行业候选能力已完成隔离验收并提交141edd3a；P1-A已提交0bd4de4f。当时下一轮为moneyflow_cnt_ths，其实施与当前状态见§10。§9表中行业独立模块为该次提交的路径，已在§10整体迁移为共用THS板块模块，不再作为当前代码入口。历史bootstrap/正式原子提升及跨进程恢复属于P3，正式Definitions和事件属于P4，真实新日更观察属于P5。

## 10. P1-C moneyflow_cnt_ths实施约束（开发前冻结）

依据§6概念7A实施卡，本轮只完成独立概念数据集的候选能力。固定12字段，`trade_date+ts_code`唯一键；`name`、`industry_index`分别区别于行业的`industry`、`close`，`industry_index`为DECIMAL(24,4)。金额仍为亿元，源NULL、负值、net_amount原样保留；Silver只转换日期，禁止股票求和或买卖差额重算。

复用行业处理能力前已使用CodeGraph核验collector、Raw/Silver writer、物理check和全部测试消费者。原行业模块统一迁移为moneyflow_ths_board模块，调用必须显式指定独立dataset；只接受moneyflow_ind_ths与moneyflow_cnt_ths，schema、API、目录与receipt身份来自同一固定选择。全部行业消费者同步迁移，删除旧实现，不留兼容别名；既有大盘与正式catalog、Definitions、API、前端消费者不改。

性能、配置与验收冻结：单日单数据集、页2000，满页需结束页；两轮至少60秒且全部键/值一致。每轮最多20000行，无重试最多22请求；重试共用既有64次/300秒预算，转换计时不重置。单页JSON持久化、DuckDB SQL批量校验，512MB/1线程/0spill与768MiB进程峰值拒绝线沿用，不新增env/Settings/数据库配置，不提高预算。消费者为共用collector/check/Silver writer，receipt记录行数、请求、重试、耗时和峰值。最多24个候选文件，双轮来源约4MiB，连同候选/临时表按32MiB规划；超行数/内存/时间直接失败，错误保留候选。

本次MCP显式12字段查询20260930返回387行；默认字段与关键身份字段继续核验。MCP不支持limit/offset，分页依据P0 SDK实测及隔离分页正反测试，不将替身当成真实分页。源端/归一化/Raw/Silver与逐字段差异须对账；增加概念真实fixture、name/industry_index类型及行业字段串入负例、跨数据集路径/receipt拒绝、上下限、取消、两轮变化、精度、篡改测试，回归已有行业和大盘能力。

本轮不执行正式Lake写入、DG job、动态分区、event或Prod写入。历史bootstrap、正式原子提升/恢复留给P3，正式编排留给P4，新交易日实跑留给P5。

上限性能核验发现逐字段JSON提取存在重复解析成本：DuckDB逻辑表合计约10MiB，进程峰值在不同运行间明显波动，曾达781.80MiB并正确阻断。按[DuckDB官方多路径提取建议](https://duckdb.org/docs/current/data/json/json_functions)，改为一次提取字段值列表、一次提取类型列表；页处理后释放source_json/source_page临时表，仅保留当前轮typed表。字段语义和拒绝条件不变，不调整参数或预算；性能结果以改后新进程实测为准，不将单次复测通过当成收尾。

### 10.1 实现与硬口径对账

| 硬口径 | 当前代码（相对orchestrator） | 验收证据 |
| --- | --- | --- |
| 概念独立12字段、身份和源单位，Silver仅改日期 | run_contracts/asset_column_schemas.py、run_contracts/moneyflow_ths_board.py | 真实387行全字段读回；源95/75/19保留19，NULL/负值不补不重算；实际Parquet类型与独立12字段字面合同一致，industry_index超过行业close的精度范围仍合法 |
| 两个数据集复用处理代码但不混来源 | 共用模块所有入口要求dataset；io/moneyflow_candidates.py按dataset隔离 | 同operation/date下概念、行业目录和receipt不同；API与fields随各自身份固定；错dataset、跨路径、行业字段/columns、错receipt拒绝 |
| 页2000、整页结束页、共享64次/300秒、两轮60秒 | source_readiness/moneyflow_ths_board.py | 概念完整2000页需结束页；20000行/22请求成功、超1行阻断；重试共享、等待/页后取消、时间/内存拒绝；空源不ready |
| 逐页证据与SQL批量严格校验 | io/moneyflow_ths_board_raw_writer.py、run_contracts/moneyflow_ths_board.py | JSON先持久化；多路径提取值和类型，不逐行Python转换；缺/多字段、重复键、错日、精度/整数/非有限数值/boolean拒绝，诊断最多3样本 |
| 乱序稳定、全字段差异为0、源证据完整 | checks/moneyflow_ths_board.py、io/moneyflow_ths_board_silver_writer.py | 双向EXCEPT，物理schema与键检查；改值、同数量换键、数量变化及篡改/损坏拒绝；Raw和verification哈希、日期、身份、行数、60秒证明再次核验 |
| 无正式编排、无新配置/全局预算更改 | 5个THS共用模块及候选/schema模块；现有保护runner仅改5个精确文件名 | 大盘与行业回归、现有catalog/check治理和合同静态门禁通过；无资产/check装饰器、job/sensor/partition/event、Prod合同、API/前端变更 |

CodeGraph使用codegraph_explore核验入口、调用关系和测试消费者；搜索确认旧industry函数与5个旧模块引用在当前Python代码中清零，全部消费者迁移，无旧别名。开发后codegraph sync/status确认索引最新。影响限于候选内部共享实现与测试，不改变主体子系统边界、依赖矩阵或正式Dagster入口；正式资产与编排消费者留待P4核验。

### 10.2 来源与隔离验收（2026-10-07）

通过tushareMcp请求20260930：显式全部12字段387行，默认字段387行且按键排序后全字段一致；885955.TI显式trade_date/ts_code返回1行，身份一致。公开结果保存tests/fixtures/moneyflow_cnt_ths_20260930.json。源端/归一化/Raw/Silver为387/387/387/387，reject0，业务字段差异0。不是新交易日日更验收，也未真实调用当前collector等待60秒；本轮候选使用实测公开fixture和fake clock，真实两轮分页/间隔依据P0已保存SDK证据。

本地0371接口文档写单次最大5000，MCP描述与P0无参数样本为4000；本轮没有复测源端最高可传limit，不把4000条样本认定为接口硬上限。实际实现固定2000，低于两种已记录口径。MCP无limit/offset入口，分页正反例为隔离替身，P0 SDK证据另行保留。

概念64项、既有行业53项、大盘27项、共享策略15项，共159项隔离测试通过。保护启动器的治理回归12项及474子测试、合同静态门禁113项通过；仅将原5个行业纯模块文件名换成共用模块的精确只读清单，不扩大目录、网络或正式资源权限。Ruff致命错误基线与改动文件默认规则通过。

优化后新进程测量：387行真实fixture两轮→Raw/Silver读回0.775秒，peak RSS192.27MiB；每轮20000行/22请求/两层读回连续3次1.467/1.456/1.535秒，峰值324.03/308.66/342.61MiB，均低于768MiB。耗时含pytest启动，使用fake clock，不含真实60秒间隔或网络，不作为真实日更耗时承诺。此前781.80MiB失败保留为性能问题证据；优化消除了每字段重复解析并释放页临时表，未关闭拒绝门禁或提高预算。上限正反例仍在独立进程运行，避免不同操作原生分配峰值累计污染验收。

历史状态：本轮moneyflow_cnt_ths候选能力完成并提交c9fcf389；当时整个P1尚未完成，下一轮为moneyflow_ind_dc。§10共用模块在§11整体迁移为moneyflow_board，之后在§13扩展普通个股并整体迁移为moneyflow_daily；当前代码入口以§13为准。历史Prod bootstrap、正式Lake提升及恢复、DG编排与真实新日更分别属于P3/P4/P5。
## 11. P1-D moneyflow_ind_dc实施约束（开发前冻结）

依据§6 DC板块7A，本轮只完成moneyflow_ind_dc候选能力。18字段固定顺序与类型；唯一键为trade_date/content_type/name，name与分类必须非空，ts_code只校验可空文本，不能当主键。三类为行业/概念/地域，单日分别分页请求，每轮三类都必须非空，禁止默认响应代替显式三类请求。源单位元、NULL及负值保留，不计算超大单/大单合计来替代源net_amount；Silver只转换日期。

本节记录P1 DC阶段实施事实；这些共用模块在后续§13整体迁移为moneyflow_daily，当前入口以§13为准。复用前使用CodeGraph核验THS合同、collector、Raw/Silver writer、checks及测试调用链。将5个moneyflow_ths_board模块整体迁移为moneyflow_board模块，字段、业务键与请求scope由固定dataset合同选择。DC使用三scope与三字段业务键，THS保持原单scope与date/code键；调用均要求显式dataset。所有THS消费者、测试和保护runner精确源码清单同步迁移，无旧别名/双轨，不改变大盘、共享TushareResource/paging默认行为、catalog、正式编排或主体依赖矩阵。

| 性能/配置边界 | 本轮冻结值与验收 |
| --- | --- |
| unit/范围 | 一个DC板块数据集、一个日分区、固定3分类；MCP20260930为496/504/31行，合计1031；无代码枚举 |
| 请求/行数 | 页2000，短/空页结束，整页继续；每轮合计最多20000行，三类各至少1行；两轮通常6请求，最坏不含重试26请求（每轮10整页+最多3结束页）。共享64次/300秒含重试和转换，不按分类/轮重置 |
| 文件/持久化 | 候选按operation/dataset/date独占；页文件按round/scope/offset隔离，先持久化JSON；每轮最多12非空页，两轮24页加Raw/verification/Silver/receipt共28文件，失败保留证据。正式提升/跨进程恢复仍在P3 |
| 内存/磁盘/时间 | Python单页，JSON批量多路径提取与页表及时释放；DuckDB512MB/1线程/0spill，进程峰值768MiB、两轮间隔60秒、请求30秒超时沿用。真实1031行191KiB CSV外推双轮20000行约7.1MiB，候选/临时表按32MiB规划；超行数/内存/时间直接失败，不扩大配置或配额 |
| 配置来源/消费者 | 全部预算来自run_contracts/moneyflow.py集中常量，无新增env/Settings/DB配置；固定3分类来自moneyflow_board源合同，collector/page writer/file check消费，receipt按实际scope记录行数与请求/重试/耗时/峰值；发布代码生效，无运营参数扩展 |
| 验收 | 真实1031行fixture读回，独立18字段类型与源值断言；三类缺失/空类/串类、跨scope分页/同名不同类/相同或NULL代码、三键重复、错日、字段和精度、共享预算/取消、两轮变更、篡改/覆盖/正式路径、合计20000行边界；回归全部THS与大盘消费者 |

默认字段同日1031行包含三类；与三类显式18字段合并后全字段一致；行业BK1216.DC显式trade_date/content_type/ts_code/name返回1行。P0已保存无参/对象/点/区间及SDK分页行为，本轮MCP没有limit/offset入口，不把隔离分页替身当成真实源分页。

本轮不触发正式DG job/sensor/分区/event，不写正式Lake或Prod。P1-C已提交c9fcf389；P1-D开发结果在本节继续对账。

### 11.1 实现与硬口径对账

| 硬口径 | 代码落点（相对orchestrator） | 正反证据 |
| --- | --- | --- |
| 独立18字段、三字段业务键、可空code、金额元 | run_contracts/asset_column_schemas.py、run_contracts/moneyflow_board.py | 独立字段顺序与物理类型断言，源1031行读回；同名不同类、同code不同名、NULL code均合法；同类同名换code仍为重复；NULL/负值/净额原样保留，构造与大小单合计不同的净额仍保留 |
| 显式三分类、每类分页/非空、合计行数和请求预算 | source_readiness/moneyflow_board.py | 三类合计20000行而非各20000；满页与结束页、每类offset重置、两轮合计26请求成功；每类各轮为空拒绝；响应串类/未知类拒绝，64次/300秒跨scope/轮不重置 |
| 逐页持久化与严格SQL转换 | io/moneyflow_board_raw_writer.py、run_contracts/moneyflow_board.py | page按round/scope/offset持久化；多路径提取、页表释放；三键重复、错日、缺/多字段、舍入/溢出/boolean/非有限值拒绝；诊断三字段业务键与field/value样本最多3行、每字段80字符 |
| 全字段稳定与三分类物理覆盖 | checks/moneyflow_board.py | 行顺序改变通过，换键/改值/数量变化拒绝；物理缺类、未知类、重复、坏schema/日期/name拒绝；不能只凭总数1031成功 |
| 来源证明与仅日期转换 | io/moneyflow_board_silver_writer.py | Raw/复核文件hash、日期、身份、行数及scope行数再次验证；双向EXCEPT；篡改、错scope行数、覆盖、跨数据集路径和合计耗时拒绝 |
| 取消与资源/正式边界 | 共用候选路径/连接与现有保护测试runner | 类间及稳定等待取消，已持久化页/首轮Raw保留而不ready；内存超限在源请求前拒绝；正式路径拒绝；现有catalog/check与静态门禁通过，正式对象未新增 |

三类collector共享一个BoundedCodePageRequestSession，未修改共享TushareResource、request policy默认值或全局DuckDB设置。scope_row_counts为本次实际候选证据：DC记录三类行数，THS记录all行数；Silver以物理查询对账，不新增状态表、汇总资产或配置开关。两类THS原单scope请求/字段/业务键保持，页目录统一为round-N/scope-N/page-offset.json；尚无正式候选消费入口或生产文件需兼容。

CodeGraph codegraph_explore覆盖板块合同、collector、Raw writer、物理check及测试消费者；全量搜索确认当前Python代码中旧moneyflow_ths_board模块、ths_board函数及类引用清零。5个模块、两组THS测试与保护runner同步迁移，无旧别名/双轨。影响限于候选内部能力，不改变主体子系统依赖矩阵或Prod合同，不接业务API/前端；正式catalog、assets、checks、jobs、sensors及事件仍归P4验收。

### 11.2 来源与隔离验收（2026-10-07）

实测通过tushareMcp：20260930行业/概念/地域显式18字段分别496/504/31行，合计1031；默认字段单日1031行也包含三类，排序后与显式三类合并全字段一致；行业BK1216.DC显式trade_date/content_type/ts_code/name返回1行。公开fixture为tests/fixtures/moneyflow_ind_dc_20260930.json，源端/归一化/Raw/Silver为1031/1031/1031/1031，reject0，业务字段差异0。测试不将每日三类行数锁定为496/504/31，实际门禁为每类非空、分页完整与两轮稳定。

这批实测DC源net_amount恰与buy_elg_amount+buy_lg_amount一致，不能据此改成派生字段；不重算规则另用构造差异、NULL/负值样本验证。无参默认5000行及显式/关键身份SDK行为参考P0保存证据；MCP不支持limit/offset，本轮分页与等待为隔离替身，源端SDK分页与真实两轮间隔继续引用P0实测，不伪称本次真实执行日更collector。

DC新增66项，既有行业53项、概念64项、大盘27项、策略15项，共225项隔离测试通过。现有保护启动器治理回归12项及474子测试、合同静态门禁113项通过；只替换5个共用模块的精确只读文件名，未放宽目录、网络或正式资源权限。Ruff致命错误基线与本轮改动默认规则通过。

新进程性能测量：1031行真实fixture两轮→Raw/Silver读回1.000秒、peak RSS196.62MiB；三类合计20000行/两轮26请求/20来源页JSON1.688秒、326.80MiB；另一20000行分布/两轮24请求/24来源页JSON加4个候选文件共28文件1.691秒、302.34MiB。均低于768MiB拒绝线，未关闭内存保护或提高预算。时间含pytest启动，使用fake clock，不含真实60秒间隔或网络；不作为真实日更耗时承诺。三个大规模fixture在独立进程执行，避免操作间原生分配峰值累计污染验收。

状态：moneyflow_ind_dc候选能力完成，本次提交归档。原方案P1限定的四个小数据集候选能力均已完成独立隔离验收；管理员已要求P1收尾并进入P2，收尾对账见§12。七数据集整体接入未完成，P3历史bootstrap/正式提升与恢复、P4正式编排/事件、P5真实新交易日日更尚未执行。

## 12. P1阶段收尾（2026-10-07）

P1的开发和隔离验收范围已完成：moneyflow_mkt_dc、moneyflow_ind_ths、moneyflow_cnt_ths、moneyflow_ind_dc四个独立数据集，各自固定字段/类型、身份、Raw/Silver候选和物理校验。大盘、THS行业、THS概念分别已提交0bd4de4f、141edd3a、c9fcf389，DC板块与本收尾记录本次提交归档。代码消费者、原方案和各轮验收见§8–11。

| P1退出要求 | 完成证据 |
| --- | --- |
| 数据集独立，不融合来源或混身份 | 四个字段合同、候选目录与receipt分别保存；共用处理代码使用固定dataset合同，错身份/跨目录拒绝 |
| 完整分页、两轮稳定、源值/精度/NULL保留 | 大盘1行、行业90行、概念387行、DC板块1031行公开样本独立读回；负例覆盖空源、串分类、错键/日期、重复、非法精度、变化、预算、取消及篡改 |
| 有界列式处理与性能预算 | 页2000、合计20000行/轮、64次/300秒、60秒间隔、DuckDB512MB/1线程/0spill、进程768MiB；各轮来源样本与上限测试见原记录，无预算放宽 |
| 全部实现/消费者迁移、现有治理不回退 | 225项隔离测试、治理12项及474子测试、合同静态113项通过；旧helper引用清零，CodeGraph sync/status确认最新，Ruff与文档完整性检查通过 |
| 阶段执行边界清楚 | 未修改Prod合同/入口、未写正式Lake或DG状态，未新增正式编排；正式提升/恢复、编排/事件、新日日更分别归P3/P4/P5，未冒充本阶段验收 |

P1可以收尾。按管理员本次指令进入P2，顺序为普通moneyflow、moneyflow_dc、moneyflow_ths，每轮独立验收。本轮先开发普通moneyflow，不同时改三个个股数据集，不进入P3/P4/P5正式执行。

## 13. P2普通moneyflow开发约束与验收

本轮目标：按§6普通moneyflow合同实现独立日批Raw/Silver候选能力。依据本地0170接口文档、P0分页实测及本轮MCP实测。20260930全市场显式20字段返回5572行，包含348行.BJ；000001.SZ默认20字段与全市场样本一致，额外显式trade_count返回78542。trade_count不属于本次Prod raw的20字段投影，继续显式只取批准字段，不能自动扩充合同。

| 开发硬口径 | 实现与验证要求 |
| --- | --- |
| 一个数据集/一个交易日/全市场 | dataset=moneyflow；trade_date+ts_code唯一键；不传ts_code、不读股票池、不按交易所/上市状态过滤；真实5572行全部读回含348行.BJ |
| 独立20字段和物理类型 | ts_code在trade_date之前；9个量字段BIGINT、9个金额DECIMAL(20,4)，全部数值可空；量手、金额万元、负值及源净额保留，不换算或重算 |
| 请求量/分页/时间 | limit=2000，每轮offset从0递增；5572行3页，两轮通常6请求；间隔至少60秒，两轮及重试累计64请求/300秒，单次30秒；满2000行须取结束页，20000行上限22请求；空结果未就绪 |
| 内存和持久化 | 进程峰值768MiB，DuckDB512MB/1线程/禁止spill；Python仅一页JSON，SQL多路径提取与转换，逐页保存、每轮落Parquet；不得加载全日Python行用于正式转换；真实5572及20000行隔离压力验证 |
| 严格转换/完成 | BIGINT小数与64位溢出、金额超4位/16整数位、非有限值/boolean拒绝；重复键/错日/字段增删拒绝；两轮全字段一致；Silver仅日期转换，hash/物理行数/来源证明再次对账 |
| 取消/失败/隔离边界 | 每页及等待检查取消，失败留下未就绪候选证据；本轮仅临时隔离目录，不写正式Lake/DG事件/分区，不执行历史bootstrap；正式提升与续跑属于P3 |
| 配置来源与生效 | 复用run_contracts/moneyflow.py集中预算及固定moneyflow合同，无新增env/Settings/DB/运营输入；collector/writer/check消费，receipt显示请求/重试/行数/耗时/峰值；随代码发布生效 |

复用审计：CodeGraph explore核验合同→collector→Raw/Silver writer→physical checks及三类板块测试调用链。5个moneyflow_board候选模块整体迁移为moneyflow_daily，固定dataset选择独立合同；所有实现、测试、保护runner精确文件清单同步迁移，不保留旧入口或别名。普通moneyflow加入候选白名单，只扩展BIGINT校验及无可空文本列的合法情况；三个板块的字段/业务键/请求scope不变，大盘单行模块不变。尚无正式API/前端/catalog/Dagster资产消费者，不改变主体依赖矩阵或共享TushareResource行为。

### 本轮实现和逐项对账

| 约束 | 当前代码落点 | 验收证据 |
| --- | --- | --- |
| 独立字段/类型/主键/全市场 | run_contracts/asset_column_schemas.py、run_contracts/moneyflow_daily.py | 独立字面量20字段顺序/类型；5572源行全字段读回一致，含348行.BJ；构造退市代码不裁剪；请求仅date/limit/offset，无对象池或证券枚举 |
| 数值/单位/NULL保真 | run_contracts/moneyflow_daily.py、io/moneyflow_daily_raw_writer.py | 9个BIGINT逐字段±64位边界/NULL通过，小数与溢出拒绝；9个金额逐字段溢出/多余小数拒绝，正负DECIMAL(20,4)极值通过；全部NULL原样读回，源净额与合计不一致仍保留 |
| 分页/共享预算/取消 | source_readiness/moneyflow_daily.py | 3页×2轮=6请求，20000行22请求含结束页；超单页/单轮、缺schema、空、跨页重复拒绝；重试累计、不重置预算；逐页与60秒等待取消，耗时包含转换与等待 |
| 完成/来源证明 | checks/moneyflow_daily.py、io/moneyflow_daily_silver_writer.py | 两轮数量/键/任一数值改变阻断；Raw/复核hash和物理行数对账；receipt身份/来源/scope数量篡改拒绝；Silver仅日期变DATE；坏schema/日期/重复物理文件拒绝 |
| 资源与隔离 | io/moneyflow_candidates.py及上述writer | 768MiB守卫、512MB/1线程/0spill；正式/退役/跨数据集目录、覆盖和未知数据集拒绝；逐页落JSON、每轮落Parquet；无正式Lake或DG写入 |

普通moneyflow独立测试127项，加P1及请求策略225项，合计352项通过。仅将压力样本由常量数值强化为真实5572行数值循环后，对该测试再次验收通过。受保护治理runner为12项+474个子测试通过，静态run-contract为113项通过；精确源码清单只替换5个迁移文件名，未扩大网络/正式路径权限。修改文件默认Ruff及全src/tests致命错误基线通过。CodeGraph explore审计完整实现/测试影响面，sync/status索引同步；无新增API/前端/Prod合同消费者或依赖矩阵变化。

### 隔离性能和物理证据

| 样本 | 源/Raw/Silver行数 | 请求/页文件 | Raw/Silver字节 | 全候选字节 | Raw到Silver耗时 | 峰值RSS |
| --- | --- | --- | --- | --- | --- | --- |
| MCP真实20260930 | 5572/5572/5572，reject=0，全字段差异=0 | 6/6 | 541201/541177 | 6908211 | 0.713秒 | 201.0MiB |
| 真实数值循环、唯一代码压力样本 | 20000/20000/20000，reject=0 | 22/20 | 1756537/1756513 | 24262085 | 2.110秒 | 419.7MiB |

两个样本分别在新进程、临时目录验证，60秒等待及请求间隔用fake clock模拟，耗时不含真实网络和等待；不能当成盘后真实日更耗时。压力样本保留真实金额/量差异，不仅重复同一行常量；进程峰值仍低于768MiB，不调整门禁。MCP本轮不暴露limit/offset，分页真实源证据沿用P0 SDK的2000/2000/1572，本轮验证collector精确参数与全部样本转换。源码、公开fixture及[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p2_moneyflow_evidence_20261007.json)留档。历史全量耗时、长任务恢复、磁盘预算与正式原子提升仍由P3实测，不从本轮日样本外推完成。

历史状态：P2普通moneyflow候选能力及隔离验收已完成并提交973d580d；当时下一轮为moneyflow_dc，当前进度见§14。P2整体未收尾，P3/P4/P5尚未执行。

## 14. P2 moneyflow_dc开发约束与验收

普通moneyflow已提交973d580d。本轮按管理员指令推进moneyflow_dc，继续一个数据集、一个日分区的候选能力开发和隔离验收。依据§6 DC个股7A卡、本地0349接口文档、P0真实分页和本轮MCP实测。显式15字段的20260930点查询得到6024行且键全部唯一：SZ3154/SH2522/BJ348。000001.SZ默认15字段与全市场样本一致，显式身份/名称/主力净额字段亦一致。源数量高于普通moneyflow并非错误；只保留本接口事实，不用其他接口或股票池裁剪。

本地0349写单次最多6000条，MCP元数据写8000；本轮实际单次返回6024，已超本地描述。P0已实测2000/2000/2000/24分页，实施仍固定limit=2000，不用单次上限作为全日完成判断。无参数/对象/区间行为沿用P0证据，不将无参近期窗口当成完整历史。

| 硬口径/性能与配置 | 本轮落点和验收要求 |
| --- | --- |
| 身份与字段 | 独立15字段，trade_date+ts_code键；name可空且不作为键；金额万元、价格元、比例%保持，源净额不重算；固定schema选择与候选白名单仅新增moneyflow_dc |
| 请求量与范围 | 1日、1全市场scope，无代码枚举/对象池/上市状态或市场过滤；每轮6024行4页、两轮8请求；显式date/15 fields/2000/offset，不传content_type；每轮20000上限22请求含两次结束页 |
| 持久化和扫描 | 真实样本8页JSON、3个Parquet与receipt共12文件；压力20页JSON、3Parquet与receipt共24文件；只在临时隔离目录，SQL按页转换和全字段集合对账，无join或全日Python转换；正式同文件系统提升/checkpoint/续跑仍归P3 |
| 预算与拒绝 | 64请求/300秒累计含重试、转换和60秒间隔；768MiB峰值、DuckDB512MB/1线程/0spill；页超2000、日超20000、缺字段/错日/重复/数量或全字段不稳定阻断；空结果未就绪，不补零或去重 |
| 严格精度 | 金额DECIMAL(24,4)，close DECIMAL(18,4)，涨跌幅/占比DECIMAL(10,4)；NULL和负值原样保留；舍入、溢出、boolean/非有限值拒绝；全部字段逐项正反验证 |
| 隔离验收和耗时 | 6024真实值读回差异0/reject0；20000真实数值循环压力及超限/取消验收；预算预计60秒等待加8个请求和日转换，网络未测前不承诺真实日更耗时；候选空间按真实压测实录；不运行正式DG/Prod/Lake写入 |
| 配置与影响面 | 复用run_contracts/moneyflow.py集中常量、paths.py及既有resource凭据/30秒超时，无新增env/Settings/DB/运营输入；collector/writer/check通过固定dataset消费，receipt保存源身份、数量/请求/重试/耗时/峰值；发布代码生效 |

CodeGraph explore核验daily schema、collector、Raw/Silver writer、checks及4个已有数据集测试链；当前复用行为符合本卡，仅扩展独立字段合同和dataset白名单，通用算法不改。既有负例中的“未接入moneyflow_dc”将在本轮同步改为尚未接入moneyflow_ths，保留未知dataset禁止路径。没有正式API/前端/catalog/DatasetDefinition消费者变更，不改变架构依赖矩阵。

### 实现与硬口径对账

| 约束 | 代码与测试落点 | 验收结果 |
| --- | --- | --- |
| 独立身份/15字段/主键/单位 | asset_column_schemas.py、moneyflow_daily.py；test_moneyflow_moneyflow_dc.py | 字面量字段顺序和Raw/Silver类型，金额万元/价格元/比例%原样读回；6024行全部保留含BJ348；同名称不同code合法，同code换名称仍为重复，NULL name合法；源净额不等于大小单合计也不改写 |
| 严格精度和NULL | 复用daily SQL数值与文本校验；独立12数值字段逐项测试 | 各字段正负最大精度通过，超4位小数/整数位溢出/boolean/非有限值逐字段拒绝；NULL与全0值保留，不当成停牌过滤条件；空code/错日/非法name/unsafe DOUBLE拒绝 |
| 分页/两轮完整集合/预算 | source_readiness/moneyflow_daily.py、io/moneyflow_daily_raw_writer.py | 每轮0/2000/4000/6000两轮8请求，全字段双向EXCEPT差异0；名称/数字/键/数量修订均阻断；满页结束页、跨页重复、超页/超日、请求预算/重试、转换耗时与取消测试通过 |
| 来源证明与物理对账 | checks/moneyflow_daily.py、io/moneyflow_daily_silver_writer.py | receipt来源/身份/行数/scope/hash/累计时间再次核验；篡改、坏schema/日期/键、重复/业务差异、覆盖/跨dataset文件、正式和退役目录拒绝；Silver只改日期 |
| 配置/回归边界 | io/moneyflow_candidates.py、新增DC固定schema选择；3个既有测试文件更新尚未接入负例 | 通用collector/writer/check算法和预算不改；未知dataset负例迁为moneyflow_ths，跨dataset禁止仍保留；无新增可编辑参数、正式资产/编排或依赖方向 |

新增113项独立测试通过；普通moneyflow、P1四数据集与请求策略352项回归通过，共465项。修改文件默认Ruff规则与全src/tests致命错误基线全部通过。受保护治理12项+474子测试、静态run-contract113项通过，runner精确源码/隔离权限清单没有修改。CodeGraph explore审计前述复用入口、调用链、测试消费者及跨数据集边界，sync/status索引同步；无正式API/前端消费者需要迁移，主体依赖矩阵不变。

### 隔离性能与来源证据

| 样本 | 源/Raw/Silver | 请求/页文件 | Raw/Silver字节 | 全候选字节 | 处理耗时 | 峰值RSS |
| --- | --- | --- | --- | --- | --- | --- |
| 20260930真实MCP | 6024/6024/6024，reject0，15字段差异0 | 8/8 | 406655/406631 | 5828098 | 0.679秒 | 246.2MiB |
| 真实数值循环且代码唯一 | 20000/20000/20000，reject0 | 22/20 | 1069973/1069948 | 18523173 | 1.601秒 | 379.2MiB |

两次测量分别使用新进程和临时目录；含Raw/Silver生成及物理读回，网络、1秒请求间隔和60秒稳定等待由fixture/fake clock替代，不代表真实盘后耗时。压力样本使用真实字段数值和名称，未弱化预算或开启spill。完整源分页真实行为沿用P0 SDK证据，本轮MCP核验身份/默认/显式字段并用真实6024行逐字段对账。源单次上限差异已补回本地0349文档，未改默认分页或运营输入。[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p2_moneyflow_dc_evidence_20261007.json)及公开fixture留档。

历史状态：moneyflow_dc候选能力及隔离验收完成，已提交79514a11；当时P2剩moneyflow_ths，当前进度见§15。P3历史bootstrap/正式提升与恢复、P4正式DG编排/事件、P5真实新日更尚未执行，不能视为七数据集已正式接入。

## 15. P2 moneyflow_ths开发约束与验收

moneyflow_dc已提交79514a11。本轮按管理员指令推进moneyflow_ths候选能力，依据§6 THS个股7A卡、本地0348文档、P0分页证据与本轮MCP实测。20260930显式13字段得到5215行，SZ2899/SH2316，业务键全部唯一；000001.SZ默认13字段及显式date/code/name/latest/net/net_d5与全市场样本一致。实测本日不含BJ，只保留源结果，不从另一个接口补股票；通用身份合同也不禁止未来或历史源返回BJ。

| 硬口径/性能与配置 | 实现点与正反验收要求 |
| --- | --- |
| 独立13字段/主键 | schema与daily固定选择新增moneyflow_ths，主键trade_date+ts_code，name可空且不入键；latest保留字段名，禁止替换为DC的close |
| 五日净额与单位 | 金额万元、latest元、占比/涨跌幅%；net_d5_amount是源五日主力净额，原样保留且不依赖前4个分区，不用日净额重算；NULL/负值/零值不改写 |
| 范围/请求/文件 | 1日×1全市场scope，无股票池/证券枚举/市场过滤；显式date/13 fields/limit2000/offset，实际每轮3页、两轮6请求；候选6页JSON+3Parquet+receipt共10文件，20000上限两轮22请求/24文件 |
| SQL扫描与预算 | 按页JSON多路径提取、SQL转换/COPY/全字段集合校验，无join或全日Python转换；64请求/300秒累计含重试/转换/60秒间隔；768MiB峰值、DuckDB512MB/1线程/0spill；真实5215和20000真实数值循环压力测量耗时/空间 |
| 严格精度/完成 | 5金额DECIMAL(24,4)、latest DECIMAL(18,4)、4比例DECIMAL(10,4)，逐字段正负边界/多余小数/溢出/非有限值/boolean测试；错日/重复/缺字段/串字段阻断；两轮全部字段稳定、hash和行数物理对账，Silver仅日期转换 |
| 失败与隔离 | 每页和等待检查取消，超页/超日/请求/时间/内存失败留下未就绪候选；不覆盖、不补空、不去重；仅临时隔离目录；正式原子提升/checkpoint/退出续跑仍归P3，正式DG编排归P4，新日更实测归P5 |
| 配置和生效 | 复用moneyflow.py预算、paths.py及resource凭据/30秒超时，不新增env/Settings/DB/运营输入；collector/writer/check按固定dataset消费，receipt记录身份/请求/重试/行数/耗时/峰值，随代码发布生效 |

CodeGraph explore已审计daily合同、分页collector、Raw/Silver writer、checks及5个既有消费者测试；通用算法符合本卡且不修改。既有“尚未接入moneyflow_ths”负例迁为明确unknown_moneyflow，保留未知dataset查询与IO前拒绝以及跨dataset保护，不用已接入数据集作“未知”样本。新增范围只包含独立schema、白名单、公开fixture、测试及原方案对账，无Prod DatasetDefinition/API/前端/catalog或架构依赖矩阵变化。

预估日执行为60秒稳定间隔加6请求与日文件转换，不在网络未实测时承诺精确耗时；候选磁盘用下述实际fixture/压力结果核实。P0真实源分页为2000/2000/1215，MCP不提供limit/offset，本轮验证当前collector精确参数与完整5215行读回。

### 实现与硬口径对账

| 约束 | 代码与测试落点 | 验收结果 |
| --- | --- | --- |
| 13字段/独立身份/主键 | asset_column_schemas.py、moneyflow_daily.py、moneyflow_candidates.py；test_moneyflow_moneyflow_ths.py | 字面量字段顺序和物理类型；真实5215行、SZ2899/SH2316全字段差异0；NULL名称合法，同code换name重复拒绝；构造BJ/退市代码不裁剪，实际样本不自行补BJ |
| latest/源5日净额/单位 | 独立THS schema与日期-only Silver writer | latest仍为最新价元，net/net_d5及大小单金额万元，比例%；当日孤立候选保留与日净额不同的五日净额，不读取前四日；最新价改名close、缺net_d5均拒绝；两轮仅latest或net_d5变化仍阻断 |
| 数值/NULL/精度 | 复用daily SQL校验，独立10数值字段逐项正反测试 | 5金额/1价格/4比例全部正负边界通过，多余小数/溢出/boolean/非有限值拒绝；NULL/零值/负净额保留，净额不重算，unsafe DOUBLE阻断 |
| 有界分页/失败/取消 | 复用collector/Raw writer/checks | 实际两轮6请求；满页结束页、跨页重复、超页/超日、共享请求与时间预算、重试累计、页后与等待取消均通过；两轮name/键/值/数量修订拒绝，失败候选不就绪 |
| Silver/物理来源 | daily Silver writer/checks | receipt身份/来源/行数/scope/hash/累计耗时再次对账；坏文件/schema/日期/键/重复/业务差异、跨dataset、覆盖、正式及退役目录拒绝；Silver仅日期类型变更 |
| 配置/消费者迁移 | 固定THS schema/白名单及4个既有测试文件 | 未改变通用算法、预算、资源和正式编排；未知dataset样本统一为unknown_moneyflow，仍在源请求和IO前拒绝；无新增配置或反向依赖 |

新增THS个股104项及既有465项，七数据集/请求策略联合569项通过。修改文件默认Ruff及全src/tests致命错误基线通过；受保护治理12项+474子测试、静态run-contract113项通过，保护runner源码清单/隔离权限没有变更。CodeGraph explore审计合同→collector→Raw/Silver→checks及已有5个消费者测试链，sync/status索引同步；没有正式API/前端/Prod合同消费者迁移或主体依赖矩阵变化。

### 隔离性能与物理证据

| 样本 | 源/Raw/Silver | 请求/页文件 | Raw/Silver字节 | 全候选字节 | 处理耗时 | 峰值RSS |
| --- | --- | --- | --- | --- | --- | --- |
| 20260930真实MCP | 5215/5215/5215，reject0，13字段差异0 | 6/6 | 336371/336347 | 4498646 | 0.602秒 | 270.2MiB |
| 真实数值循环、代码唯一 | 20000/20000/20000，reject0 | 22/20 | 1142325/1142300 | 16802274 | 1.457秒 | 330.9MiB |

两样本各在新进程、临时目录生成并读回；耗时含候选Raw/Silver与物理对账，不含真实网络、1秒限流等待或60秒稳定间隔。压力样本保留真实名称和数值，没有扩大768MiB/512MB门禁或开启spill。不能将本轮性能或成熟历史样本稳定视为盘后真实新日更验收。[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p2_moneyflow_ths_evidence_20261007.json)和公开fixture留档。

历史状态：moneyflow_ths候选能力及隔离验收完成，当时P2具备收尾条件。其修改由本次提交归档；最新P2收尾/P3开发进度见§16～17，正式历史bootstrap、DG编排与新日更仍未执行。

## 16. P2候选能力阶段对账

| 方案P2退出要求 | 证据 | 当前结论 |
| --- | --- | --- |
| 三个个股逐个独立Raw/Silver合同和候选 | 普通§13、DC§14、THS§15，各自字段/类型/键/单位/目录/receipt | 完成候选开发，不合并来源、不改变Prod入口 |
| 股票范围与全字段精度 | 5572/6024/5215真实值全部读回差异0；BJ/退市/NULL/零值/负值及全部数值字段边界正反样本 | 保留各源范围，不能声称三个源证券集合相同或绝对无遗漏 |
| 分页与有界压力 | 三个20000行样本，两轮各22请求；请求/时间/行数/内存/取消守卫；峰值419.7/379.2/330.9MiB | 均在768MiB门禁内；真实网络耗时与全历史吞吐尚未由本轮证明 |
| 共享能力语义与回归 | CodeGraph调用链核验；七数据集/策略569项，受保护治理与静态合同门禁，Ruff | 合同选择共享流程、独立业务身份；通用算法与正式依赖方向未改 |

管理员2026-10-07要求P2收尾并进入P3。按上述四项退出条件，P2候选能力开发及隔离验收收尾；THS修改及本次收尾记录由本次提交归档。正式样本必须另行冻结命令、日期、读写范围及冲突处理并获批。全历史迁移与14个正式资产接入仍须P3/P4/P5独立验收，不能把P2收尾理解为已正式接入。

## 17. P3历史规划与受限导出SQL开发范围（2026-10-07，旧路线记录）

以下保留402c8452当时的实现和验收。当前§4/§19已替代其代码块读取和后续spool安排；历史数字与测试不作为新路线通过证据。

当时依据§3～5及原方案P3，先实现纯历史规划器`defs/bootstrap/moneyflow_history_plan.py`和受限SQL builder；入口只接受单个批准dataset、明确截止日和有界逐日计数，不读取数据库、Lake或instance，不创建CLI/APPLY入口。七表分别规划，不合并数据。验收读取P0公开逐日计数CSV，只产生临时/报告证据。

| 硬口径 | 代码与验收落点 |
| --- | --- |
| 七张raw_tushare表/固定业务列；不能任意SQL、标识符或来源 | schema选择器复用当前Raw/Silver字段合同；未知dataset与内部字段负例，SQL只生成受限COPY TO STDOUT |
| 只规划Prod已有日期；不生成缺日或改变历史分类/覆盖 | 输入非空、日期唯一、行数正整数且与distinct key数一致；历史2行日、行业独有早期日与缺日样本保留 |
| 写窗口年内≤20日、≤100000行；六表读窗相同 | 贪心批次划分及边界测试；单日超过行数预算拒绝，不拆日伪装完整 |
| 普通moneyflow读unit按(ts_code,trade_date)≤100000 | 计划记录预期行数及后续待CSV读回的边界；下一unit必须传实际after_key，复核可指定实际through_key；不从日期计数编造证券边界，禁止OFFSET |
| 来源计数/schema/计划变化阻断；计划不等于执行许可 | 确定性hash包含逐日来源计数、Raw/Silver字段、键和读写预算；SQL生成前重建并核验计划，篡改与旧schema负例 |
| 每unit只读、4条SQL、120秒 | BEGIN READ ONLY / SET LOCAL / COPY / ROLLBACK；显式日期格式、NULL文本和排序；SQL静态正反验收，不用正式资源执行测试 |

配置审计：新增`MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT=100000`、`MONEYFLOW_HISTORY_MAX_DATES_PER_WINDOW=20`、`MONEYFLOW_HISTORY_MAX_DATE_FACTS=20000`、`MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS=120`，集中于`defs/run_contracts/moneyflow.py`。前三项约束sourceunit/窗口/规划输入，最后一项约束生成SQL；仅本历史planner/builder和测试消费，代码发布生效，无env/数据库/页面开关。20,000条规划日期事实的上限约束输入及排序内存，当前七表共7,804条；它不是历史业务行数上限。后续执行器仍须实现§4全部累计时间/空间/内存/checkpoint门禁，本轮不宣称这些运行期门禁已落地。

已使用CodeGraph explore审计既有bootstrap与资金流合同消费链。既有ETF bootstrap混合Tushare采集、基础资产与分区语义，不适合本族Prod历史来源；不复用其计划/批准状态。只复用资金流固定schema/date校验，历史规划不调用日更collector、两轮稳定receipt或DC三分类每日完整判断。新增module无asset/job/sensor/check定义，不改变Prod DatasetDefinition、API/前端和主体依赖矩阵；保护测试runner只增加该纯module精确只读源码路径。

本轮完成后P3仍需：有界CSV流式导出与独立来源复核、逐unit checkpoint、CSV→spool→分日候选、历史校验、同文件系统提升及故障/取消/退出/续跑/幂等验收。之后才形成正式样本命令与精确范围供批准；正式全量文件和事件不能提前标完成。

### 本轮实现与隔离验收结果

上述planner/builder已实现。按P0逐日CSV重建七个独立计划，与§4基线逐表一致：共21,160,938行/7,804个数据集日期、347个sourceunit、423个写窗口、15,608个预计正式两层文件。两遍来源读取预计694事务，加至多14统计连接为708连接、2790条SQL。这些是规划数量，文件尚未生成，未重新查询当前Prod。普通141个读unit只冻结行数和续跑方式，实际after/through边界必须由后续CSV/checkpoint证明，不能拿计划hash充当来源内容hash或执行批准。

基于同一公开计数证据的新进程规划及七表首unit SQL生成耗时0.057秒，峰值RSS79,970,304字节（76.3MiB）。只处理有界日期元数据，不含导出、DuckDB转换或提升耗时，不能据此推断历史执行吞吐。源CSV证据hash、逐表schema/count/plan hash和边界待验状态在[moneyflow_p3_history_plan_evidence_20261007.json](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_history_plan_evidence_20261007.json)留档。

新增66项测试包含七表全范围真实计数对账、年界/20日/100000行、缺日/2行历史、未知源/非法计数/日期/键/超限generator、计划篡改、固定SQL及字面量转义、下一unit缺边界拒绝和无执行入口静态门禁。新增与七数据集/策略联合635项通过；最终NULL字面量改为显式E字符串，避免服务端standard_conforming_strings差异后，66项定向再验通过。SQL排序使用源DATE列而不是to_char输出别名，不为CSV日期格式引入全量排序表达式。受保护治理12项+474子测试、静态合同113项通过；修改文件默认Ruff、全src/tests致命错误基线及文档完整性通过。CodeGraph sync/status已同步，runner仅新增一个精确只读源码路径，没有扩大资源写入或网络权限。

P3首轮历史规划能力完成，整个P3未完成；下一轮是有界导出与checkpoint开发/隔离恢复验收。本轮无Prod/Lake/DG正式执行，也未创建APPLY命令或将计数计划标为正式来源内容已复核。

## 18. P3有界导出与checkpoint开发范围（2026-10-07，旧路线记录）

以下保留ada58b50提交的旧来源CSV实现/测试，当前路线和下一轮工作以§19为准。THS、P2收尾及P3首轮规划已提交402c8452。当时只实现历史来源CSV导出、独立复核与跨进程checkpoint；不做spool/Parquet转换、正式提升、资产或事件接入。新增`moneyflow_history_export.py`负责单unit状态机、`moneyflow_history_csv.py`负责列式校验、`moneyflow_history_source.py`负责现行psql入口流式适配。测试使用隔离目录、可控COPY来源及真实公开fixture，不读取正式数据库/Token/Lake/instance。

| 硬口径与预算 | 落点/验收 |
| --- | --- |
| 只能受限七表SQL，每次COPY一个unit，只读/120秒 | source adapter自行调用§17 builder，沿用bash scripts/psql-remote.sh -f及安静psql参数，禁止任意SQL/连接字符串/来源开关；两个64KiB管道缓冲，stderr不回显；取消/超时终止整个子进程组 |
| 单CSV≤32MiB、来源所有文件≤8GiB、总执行≤12小时、RSS≤768MiB | 集中常量；流写前后与等待期间检查；開始磁盘空闲≥64GiB。来源文件计量含失败现场和复核文件；后续32GiB总占用、st_dev及spool上限仍在转换/提升阶段验收 |
| 默认单writer、逐unit推进，不领取后续unit | 单unit API要求前序来源unit已verified，普通下一页边界从前序CSV证明读取；不提供并行/CLI入口，本阶段尚不允许正式运行；正式入口仍须维护窗口/唯一writer门禁 |
| 来源行数/字段/日期/唯一键/精度严格，历史低覆盖和DC早期分类保留 | 固定列顺序header，DuckDB512MB/1线程/0spill；CSV一次加载临时关系后做SQL聚合/精度/键验证，不拉业务行到Python；普通代码块校验排序和前后边界，六表逐日期计数与计划一致；DC允许历史行业独有日、代码空值 |
| 原子单文件持久化、checkpoint与来源证明独立 | history_export独立staging子目录、独占attempt目录；CSV完整校验/fsync后os.replace，checkpoint记录plan/schema/count hash、unit、边界、path/hash/rows、阶段、数量/字节/更新时间。CSV rename与checkpoint不是整体事务 |
| 取消/退出/中途崩溃/幂等/来源变化 | 阶段exporting/exported/verifying/verified/blocked；恢复校验已完成CSV hash。rename已完成而checkpoint未更新时重新审计并接回；partial保留并新attempt重跑；同一范围两次CSV hash/行数/键一致才verified，差异blocked，禁止覆盖/自动接受新值 |
| 不绕过累计时间预算 | 每attempt先持久化120秒预算预留，正常结束/取消按实际耗时结算；未正常退出的attempt保留预留，恢复时不会免费重置预算。预留是保守计费、不是声称实际耗时120秒 |

配置审计：在`defs/run_contracts/moneyflow.py`新增`MONEYFLOW_HISTORY_MAX_CSV_BYTES=32MiB`、`MONEYFLOW_HISTORY_MAX_SOURCE_BYTES=8GiB`、`MONEYFLOW_HISTORY_MAX_ELAPSED_SECONDS=43200`、`MONEYFLOW_HISTORY_MIN_FREE_BYTES=64GiB`、`MONEYFLOW_HISTORY_STREAM_BYTES=64KiB`；沿用120秒/RSS/512MB/线程常量。只供上述三个helper及测试消费，代码发布生效，无env/Settings/数据库/页面输入。checkpoint仅作为已批准离线来源工作证据，不新增运行状态事实源或catalog。正式路径沿用当前paths.py及staging guard，恢复路径只由固定目录规则生成，不接受checkpoint任意路径。

性能范围：最多100000业务行/32MiB一个sourceunit；初导出+复核每unit两次COPY；每CSV一次列式加载，后续校验扫描内存关系，最多20000条日期元数据。每attempt至多SQL/partial/CSV与checkpoint文件，不把完整业务CSV/行列表载入Python。P0的10万行COPY约22.673秒仍是规划依据，本轮隔离测试只验证适配器/持久化/校验/恢复成本，不代替正式年度/分桶吞吐。全部来源CSV仍最多347×2个成功文件，失败现场按8GiB共同计费并超限阻断，不清理现场以绕开预算。

CodeGraph explore已核验planner→builder和既有候选路径/连接/hash消费链。日更Raw/Silver stable receipt不能充当Prod历史证明，日更DC三分类完整check也不能直接复用；只复用固定schema、数字lexical SQL和受限DuckDB连接。主体依赖矩阵/API/Prod合同不变；受保护runner仅追加新helper精确源码路径。正式导出与正式写入本轮均未执行。

### 实现细节与验收（本次提交归档）

三个helper已实现。adapter通过既有脚本的`--env-file <repo>/.env.web.local -f <attempt>/source.sql -- -q -X -v ON_ERROR_STOP=1`固定现行连接文件，防止调用进程的ENV_FILE改变来源；不向调用方暴露环境文件/DSN参数，不改脚本本身。已有PSQL_BIN选择仍由脚本处理。本轮没有读取或输出连接文件内容、Token或数据库凭据。

CSV先分64KiB块计算hash、引号字节奇偶和末尾换行，拒绝不完整传输，再做列式字段/键/日期/精度校验。隔离负例发现DuckDB strict_mode仍可能忽略末尾未闭合引号，不能只凭行数通过；该样本现明确拒绝。采用`allow_quoted_nulls=false`，区分未加引号的NULL标记和加引号的真实`\N`文本。业务行不拉回Python，业务校验留在DuckDB临时关系。

恢复时重审完成CSV的hash及真实键/计数证明，不信任checkpoint可编辑的last_key。有界本地重审会额外扫描CSV，不新增Prod查询，也纳入本操作时间预算。首次开始须64GiB空闲；已有冻结操作恢复时检查下一双CSV的容量，不重复要求初始64GiB，以免恢复被自身文件阻断。progress保存阶段、unit、完成/总数、字节、实际/保守预留时间、COPY事务尝试数和wall-clock更新时间；CSV与checkpoint分别fsync和replace。没有并行或全历史运行入口，调用者须独占操作目录。

新增58项通过，含七表独立成功/幂等、取消、阶段恢复、实际os._exit后新进程续跑、rename与checkpoint间退出、同键同行数值变化、修改边界/路径、残缺CSV、源子进程组终止及资源拒绝。联合plan66项和候选/策略569项共693项通过（48.83秒）；固定连接文件参数调整后58项再验通过。受保护治理12项+474子测试、静态合同113项、默认Ruff和全src/tests致命错误基线通过。CodeGraph sync/status与文档/链接检查通过。

| 隔离样本 | 源/导出/复核行数 | CSV每份字节 | 导出/校验/复核耗时 | 新进程峰值RSS |
| --- | --- | --- | --- | --- |
| 普通moneyflow公开真实数值fixture | 5572/5572/5572，reject0 | 747817 | 0.439秒 | 196.3MiB |
| 普通moneyflow真实数值循环、100000唯一测试代码 | 100000/100000/100000，reject0 | 13427932 | 2.924秒 | 278.5MiB |
| moneyflow_ths公开真实数值fixture | 5215/5215/5215，reject0 | 517168 | 0.317秒 | 194.0MiB |

各样本独立新进程/临时目录流写，两份CSV hash、键/日期/精度一致；完成后幂等恢复重审，COPY仍为2次。压力CSV低于32MiB，峰值低于768MiB；无spill、扩展下载或扩大预算。数据来自公开MCP fixture并适配Prod CSV日期格式，不是本轮真实Prod导出；耗时不含网络/数据库，不能作为全历史SLA。[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_history_export_evidence_20261007.json)留档。

旧来源unit能力已提交ada58b50，整个P3尚未完成。当时的CSV→spool步骤已取消，下一轮按§19迁移日期直接生成候选和来源复核，之后才是正式提升与物理对账。全量入口还须串起来源统计刷新/内容复核、七表合计SQL/连接/时间/空间预算和唯一writer。本helper处理单个独立dataset来源操作，不把各自12小时/8GiB门禁冒充七表合计门禁。正式样本仍须精确命令与范围批准，来源CSV verified不代表正式数据或DG事件ready。

## 19. 日期直接生成的实现与验收细则（2026-10-07，当前方案）

### 19.1 目的与明确边界

管理员已批准七表按日期批次读取并直接生成每天的候选，取消旧代码keyset导出和spool。当前链路如下：

```text
冻结一个dataset的一批日期及逐日行数
  → Prod只读COPY这一批日期，有界内存接收
  → DuckDB校验字段/键/数值，直接生成每日Raw候选
  → 对应Raw直接生成每日Silver候选
  → 独立重读相同日期批次，与候选逐键逐字段复核
  → 全部候选校验通过，逐文件提升并checkpoint
```

“一次生成”表示业务输出第一次落盘就是最终每日结构的Raw/Silver候选；仍有必要的文件读回、Raw→Silver转换和独立来源复核。没有持久化来源CSV、第二份复核业务文件、年度spool或按代码生成后的重新归堆。正式目标仍为paths.py定义的Raw/Silver路径，staging只在`/Volumes/datasource/data_lake_staging`；不会新增Lake层级或合并七个dataset。

### 19.2 日期plan与只读SQL

1. 每个unit包含dataset、unit_id、明确有序日期集合、逐日row_count/distinct_business_keys、历史实际分类集合和schema/count/plan hash。年内≤20日、总量≤100000行；普通moneyflow与其他六表使用同一日期规划语义。日期缺口不扩成空成功，低覆盖和早期DC仅行业的历史事实保留。
2. 查询只允许该dataset固定表和业务字段，条件使用明确日期集合。排序采用源DATE字段和同日业务键；moneyflow不再使用(ts_code,trade_date)范围条件、after_key/through_key、深OFFSET或代码循环。SQL按行数上限+1做溢出探测，出现第100001行即拒绝，不能用LIMIT100000静默截断。单日自身超100000行则停止重新评估，不按代码切分。
3. 只通过现行`bash scripts/psql-remote.sh --env-file <repo>/.env.web.local -f <受控SQL> -- -q -X -v ON_ERROR_STOP=1`入口。BEGIN READ ONLY、SET LOCAL 120秒、COPY TO STDOUT、ROLLBACK构成单次短事务；不新增DSN、env配置或数据库直连，不修改脚本/Prod索引。
4. 新plan必须更换路线版本/hash身份；旧代码块计划及exported/verified CSV checkpoint直接拒绝，不能转译边界或保留双轨。旧CSV文件保留为历史现场，不作为新输入，也不在本任务自动清理。

### 19.3 有界接收与直接产出

COPY仍可使用CSV作为传输协议，金额保持十进制文本、NULL为未引号的`\N`、真实同名文本有引号；业务数据不保存成CSV文件。现行adapter保留64KiB块读取及进程组取消，sink改为单批最大32MiB的内存缓冲；不使用会自动落盘的缓冲器。完整COPY成功并核验header/末尾换行/引号完整性后，由局部DuckDB连接的read_csv(path_or_buffer)列式读取可寻址内存对象，显式字段类型，不做自动类型推断、忽略坏行或Python逐行处理。[DuckDB Python关系API](https://duckdb.org/docs/current/clients/python/relational_api)提供该接收入口；现有项目环境、参数和峰值行为仍须P3-A隔离验证，不新增/安装依赖来绕过门禁。

内存关系先保留词法值，复用当前严格数值精度/整数/溢出检查，再显式CAST成合同类型；源DATE转换成Raw的YYYYMMDD，Silver仅改成DATE。批次逐日行数、业务键、分类、NULL/负值按冻结合同验证；大盘1行，其他历史日期按实际来源行数，不套当日上市数或未来DC三类要求。

一批最多100000行，在DuckDB内一次形成合法列式关系；每个日期通过SQL/COPY直接输出各自Raw候选，再从该Raw生成Silver，最多20个日期/40个候选文件。按日期遍历只用于最多20个最终文件的调度，禁止Python逐行insert或扫描所有历史块；不先写一个跨日中间Parquet。生成后释放接收缓冲和临时关系，复核时读取已有Raw，不再同时保留初采全批内存。

独立复核重读完全相同日期集合并在内存解析，与当前批Raw按显式业务字段双向集合差、逐日计数和键唯一性对账；Raw与Silver再按日期类型映射逐字段比较。不能只比较字节数、文件存在或总行数。变化时记差异数量/最多20个样本并blocked，保留第一次候选，不写第二份CSV/Parquet，不自动覆盖。两个短事务的相同结果仅证明该批观测稳定，不宣称全历史跨事务一致快照。

### 19.4 持久化、取消与恢复

unit阶段为planned、reading、candidates_complete、verifying、verified、promoting、complete或blocked；逐日期、逐层记录候选path/hash/rows和正式提升事实。checkpoint包含§4列出的路线身份和累计预算，采用独立临时控制文件fsync/replace；候选文件完成校验后再登记，checkpoint与多文件不称整体事务。

- 接收或候选未完成时退出：内存字节自然丢弃，partial候选留现场；新attempt重读这一日期批次并重新生成，重跑成本最多当前日期unit，不能把半个日期文件当完成事实。
- 完整候选生成后退出：从真实文件核验schema/日期/键/精度/行数/hash，重新做独立来源复核后才能verified；不因JSON标完成便跳过复核。读取尝试和时间预扣，崩溃不重置总预算。
- 提升途中退出：逐文件对账正式hash和候选hash，已提升且一致的文件幂等接回；未提升文件继续，冲突停止。Raw成功但Silver尚未成功时保持未就绪。rename后checkpoint写失败不回滚实际正式文件。
- 每个日期unit、接收块、复核、生成日期文件及提升前后检查取消；正在COPY时停止自有进程组。DuckDB超时/取消使用现有interrupt能力。取消后不领取下一unit，保留已提升文件、checkpoint和异常现场。
- 仅一个writer操作这一范围；历史执行和未来日更互斥。progress每unit及至少每30秒显示阶段、日期批次/当前日期、完成/总量、字节、累计SQL/连接/时间和最后更新时间；全历史ETA在实测前写“暂无法估算”。

### 19.5 预算配置审计与代码影响面

配置迁移已按本节批准边界实施，集中在`defs/run_contracts/moneyflow.py`，只由日期读取adapter、bootstrap writer/planner和保护测试消费，代码发布生效，无新增env/Settings/数据库/页面输入。既有日更常量和消费者不变；引用审计及旧项清零结果见§20；七表全量累计预算仍待操作入口实现。

| 配置/口径 | 新路线用途与迁移要求 | 测试/运维证据 |
| --- | --- | --- |
| 20日期/100000行、120秒/12小时、512MB/1线程/0spill、RSS768MiB、64KiB接收 | 沿用集中边界；七表全部日期unit，重试/恢复计入同一操作与七表累计预算 | 年界/行数/时间/内存/累计预算耗尽负例；显示实际预算和拒绝原因 |
| 旧MONEYFLOW_HISTORY_MAX_CSV_BYTES=32MiB | 替换为接收缓冲字节上限这一明确职责，所有历史调用及测试同步迁移，不留旧名兼容；值不放宽 | 超过32MiB停止；完整传输/引号/NULL负例；无自动落盘或spill |
| 旧MONEYFLOW_HISTORY_MAX_SOURCE_BYTES=8GiB、spool8GiB/65536文件口径 | 来源CSV及spool均取消；旧来源文件预算常量与消费者退出新链，不能用于允许额外中间业务文件 | 隔离执行产物清单只有每日候选与控制证据，来源CSV/spool为0 |
| 启动空闲64GiB、新增总占用32GiB | 保留七表合计边界，包含已有失败现场/候选/正式新增输出；恢复按剩余工作检查 | 计量实际文件/空间；不足拒绝，不清理现场、不自动扩大 |
| 截止日、日期集合、operation ID、新plan版本/hash | 显式人工输入/冻结控制证据，不能从cursor或代码键推断 | 旧plan/checkpoint、日期越界、跨dataset、任意SQL/路径拒绝 |

本轮用codegraph_explore核验build_moneyflow_history_plan→history_schema/daily_schema、history_export→plan校验和source→SQL builder链；图未识别全部测试边，以当前test_moneyflow_history_plan/export及七表候选回归直接核验为准。影响范围为历史plan/source/export/csv模块、相应测试和保护runner；复用既有schema、候选路径、严格数值及物理check。没有Web/API/Prod DatasetDefinition消费者迁移，不改变子系统依赖矩阵或其他数据集配置。旧helper迁移前已完成引用审计，当前实现/消费者迁移及CodeGraph补查见§20。

### 19.6 新P3步骤和验收清单

按原方案§24.2的P3-A到P3-F执行；当前下一步是日期查询/接收准入与旧历史代码迁移，不开发spool。模板§7A/§18对账如下：

| 硬口径 | 下一轮代码/测试落点 | 隔离或获准真实验收 |
| --- | --- | --- |
| 七表日期unit、直接每日产物 | history_plan/source、日期writer；清零after/through/last_key和旧CSV入口 | 423批参考计数；SQL日期条件；代码遍历反例；无CSV/spool业务产物 |
| 类型/字段/分类/缺口保真 | 当前schema与strict SQL、Raw/Silver文件check | 七表真实公开样本；早期2行/行业独有/NULL/负数；源=Raw=Silver/reject理由/逐字段读回 |
| 来源变化不能绿 | 日期复核、checkpoint状态和物理check | 同键同量但值变化、缺键/多键、错日、满批+1溢出、残缺COPY反例 |
| 内存/请求/空间有界 | 日期sink、局部DuckDB、累计预算 | 单日与近10万行日期批次，真实日期查询计划/耗时；峰值RSS/32MiB/0spill；中途超限停止 |
| 退出/取消/幂等/冲突安全 | unit checkpoint、逐文件提升、独占writer | 真实子进程退出后新进程恢复；生成/复核/rename边界；状态写失败不回滚；不同st_dev/正式hash冲突拒绝 |
| 正式文件/事件/日更分开 | 精确样本命令、批次CLI、后续P4/P5 | Lake样本/全量、DG事件、日更分别获批并读回；未执行不得预填通过 |

普通moneyflow的日期查询计划、实际索引与吞吐需刷新核验；旧代码块COPY22.673秒和CSV隔离693项测试不证明新方案性能/恢复通过。如果日期路线超预算，应记录证据并修订日期批次或单独提出索引方案，禁止自行回退代码导出、自行改Prod索引或以安装依赖解决。当前已完成日期代码迁移和候选隔离验收（§20）；P3尚未收尾，正式数据、事件和自动化状态未改变。


## 20. 日期历史代码迁移、约束对账和隔离证据（2026-10-07）

### 20.1 目标、改动与边界

依据原方案§24、本LLD§19及接入综合模板§7A/§18，移除旧代码keyset和业务CSV持久化，迁移到固定日期批次直接产出。原设计文档已先提交`44904bb0`；本节记录随后代码迁移，不覆盖§17～18历史记录。

| 文件 | 当前职责及实际变化 |
| --- | --- |
| `defs/bootstrap/moneyflow_history_plan.py` | 七表统一`MoneyflowHistoryUnit(dates,row_count)`，新revision/hash；删除source_units/windows双轨与after/through参数；固定日期IN查询，LIMIT100001 |
| `defs/bootstrap/moneyflow_history_source.py` | 请求只含plan/unit/受控SQL路径，沿用原psql白名单入口、64KiB接收块、stderr排空和子进程组取消 |
| `defs/bootstrap/moneyflow_history_receive.py` | public read_csv(BytesIO)词法接收，严格日期/键/数值/NULL验证、列式CAST、历史文件检查及独立来源差异；不持久化CSV |
| `defs/bootstrap/moneyflow_history_candidates.py` | 单unit内存接收→每日Raw→对应Silver→独立来源复核；逐日hash/checkpoint、真实文件恢复、独占锁和持久化时间预扣 |
| `defs/run_contracts/moneyflow.py` | MAX_CSV_BYTES改为MAX_BUFFER_BYTES=32MiB，MAX_SOURCE_BYTES退出、MAX_DISK_BYTES=32GiB；无旧名兼容，日更常量不变 |
| 测试与保护runner | 删除旧export测试，改为history_candidates测试；plan测试改日期语义，保护精确源码清单替换旧csv/export路径 |

旧`moneyflow_history_csv.py`、`moneyflow_history_export.py`已删除；当前源码中旧参数名仅用于拒绝旧checkpoint和负向测试。所有历史调用方已迁移，没有Web/API/Prod DatasetDefinition消费者；没有新正式asset、job、sensor、partition、事件、CLI入口或配置来源。没有Lake正式写入、数据库写入或依赖矩阵变更。

CodeGraph使用`codegraph_explore`、`codegraph_impact`分析旧plan→schema、export→plan/source、source→SQL及消费者；用全量rg补齐图未覆盖的测试和保护清单。迁移后执行根索引`codegraph sync/status`，四个现行历史模块可在根索引files查询中检出；无需子项目重建索引。仍须真实核验的是Prod日期查询执行计划和全量操作入口，不是未迁移的Web消费者。

### 20.2 硬口径落点与验收

| 约束 | 代码及测试证据 |
| --- | --- |
| 七表独立，日期明确、年内20日/100000行，缺日和早期低覆盖不补造 | planner的日期事实、统一unit、schema/count/plan hash；P0基线、年界/21日/行数/缺口/篡改测试 |
| 不按代码读取，无业务CSV/spool，无第二份复核数据 | date IN +源DATE/同日键ORDER BY；BytesIO→DuckDB SQL COPY每日文件；旧参数TypeError/旧目录拒绝和产物清单断言 |
| NULL/负值/十进制/整数及身份保真 | 关闭自动推断/坏行忽略，na_values与allow_quoted_nulls=False；复用strict numeric SQL并明确CAST；负值/可空身份外字段/带引号NULL文本/溢出与精度负例 |
| 历史分类不套未来要求，源变化不能verified | receive记录unit实际分类；历史物理schema/日期/键检查与Raw/Silver相等，独立来源与Raw双向EXCEPT；早期行业独有、排序变化、同键同量金额变化测试 |
| 恢复按真实候选，取消后不领取新unit | 固定路径、逐日hash/rows复审；完整候选恢复重读来源、不重写文件；接收退出/完整候选退出的新进程恢复，后续unit须前序verified且文件实际通过 |
| 原生计算能取消，预算不放宽 | 100ms watcher+DuckDB interrupt，进程组终止；32MiB/64KiB、120秒/12小时预扣、768MiB/512MB/0spill和空间拒绝测试；单日100000行通过，100001行拒绝 |

实际字段/分类集合并未凭空放入P0只含逐日总数的CSV：日期plan冻结日期/行数/键数，unit初采source_proof记录并持久化真实分类；恢复依据候选与新来源逐字段一致。正式全量来源刷新入口仍需把外部历史分类证据一起冻结，当前helper不是这一入口。

单个操作目录使用fcntl锁，JSON/进度更新在同一锁内串行，独立临时控制文件fsync后os.replace；候选COPY到.parquet.partial，fsync/replace后逐日记hash。候选累计占用以新增文件stat计量，不在每个文件完成后重扫所有此前批次；进入/恢复及异常现场只做受控目录元数据对账。SQL控制文件计入占用；业务数据文件只有每日Raw/Silver。progress持久化阶段、明确日期、当前日期、完成/总unit、接收字节、COPY/连接/SQL数和时间，ETA明确“暂无法估算”。完整unit重放会新增一次来源复核，因此重放不是零COPY；不会改写既有候选。

### 20.3 实测及尚未完成项

本地使用现有DuckDB1.5.2，没有安装依赖。内存read_csv能保持未引号\N为NULL、引号同名文本为字符串，并保持DECIMAL精度；连接关闭后接收对象释放。六个既有公开MCP样本（普通5572、DC6024、THS5215、DC板块1031、THS行业90、THS概念387）在日期路线源/Raw/Silver行数及逐字段相等；大盘1行合约构造样本通过。上述不是本轮真实Prod导出，也不是七表源站重新审计。

10万行压力样本使用普通moneyflow真实数值循环，生成20个日期/每日5000个唯一键；初采与独立复核两次读取，共40个每日文件。最终新进程处理4.381秒、重放2.187秒、峰值398.05MiB；内存接收13420214字节，候选及控制文件19638243字节。隔离测试仅把启动空闲空间探测设为128GiB，没有放宽行数、内存、时间、缓冲或运行空间预算；不作为正式磁盘准入证明。源/Raw/Silver均100000、reject0、差异0，无CSV或spill；重放仅新增一次复核且候选hash不变。最终耗时、峰值RSS、字节、样本hash和当前源码hash见[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_date_candidates_evidence_20261007.json)。耗时不含远端查询、网络、正式提升或事件，不能外推为整个历史完成时间。

最终联合回归691项通过，其中新日期历史专项122项、既有七表/策略569项。受保护治理12项/474子测试及静态合同113项通过，Ruff默认改动检查/全src与tests致命规则及文档完整性检查通过。治理/静态由原保护启动器执行，工具提权仅用于当前环境不支持嵌套sandbox-exec，不扩大正式资源测试权限。真实进程退出分别返回37/38并由新进程成功续跑；接收中退出保留120秒预扣，正常完成初采后退出保留已记录实际耗时，不把它误当未完成步骤的预扣。

本轮仅单dataset单日期unit候选能力。其12小时/32GiB限制作用于该dataset/cutoff操作目录，不可冒充七表合计边界已闭合；全量runner仍须统一累计SQL/连接/重试/时间/空间及日更互斥。正式提升promoting/complete、同文件系统/正式冲突/提升中取消恢复、外部分类冻结和真实Prod日期查询吞吐也尚未实现/验证。本轮不提供APPLY入口，不生成正式Lake或Dagster成功事实。下一步先补真实日期查询准入证据，再按§19/原方案§24逐项实现全量控制和批准范围内的正式样本；整个P3尚未完成。本节代码随后已提交6f7c4ea9，当前只读核验及下一步见§21。


## 21. Prod日期查询与内存接收实测（2026-10-08）

### 21.1 范围、执行依据与边界

管理员要求“提交修改，然后继续推进”。上一轮日期helper、测试和文档已提交`6f7c4ea9`；本轮只推进§19.6所列日期查询/接收准入，不执行正式写湖、索引DDL、DG登记或事件。沿用开发、数据湖接入、Dagster及Prod只读导出skills；CodeGraph explore读取history_export_sql/source/receive链，直接核验实现和消费者。没有业务代码、配置、合同或子系统依赖变化。

连接固定为`bash scripts/psql-remote.sh --env-file <repo>/.env.web.local -f <受控SQL> -- -q -X -v ON_ERROR_STOP=1`；所有事务BEGIN READ ONLY/ROLLBACK，SQL超时120秒。七表共105个字段投影按当前schema白名单，精确日期集合从既有P0逐日计数选择，单日/近期批次/最大行数批次再加两个早期日期；单批年内≤20日/≤100000行，COPY保留LIMIT100001溢出探测。没有重新统计全历史，更未把目录reltuples估值当精确计数。

先用小目录查询核验PostgreSQL16.13、七对象relkind=r、18个索引及批准字段类型，做23个EXPLAIN；日期集合相同的DC板块近期日/近期批次在实际读取时去重，得到22个样本。七个最大行数批次各多读一次，共29次COPY/116条COPY事务语句、806567行；目录/EXPLAIN、一次普通最大批次EXPLAIN ANALYZE及索引大小查询另占3个事务，总计32个。EXPLAIN ANALYZE只针对已冻结的18日/99839行样本，不为摸清规模扫描全表。

### 21.2 实测、数据口径及证据

采用现行PsqlMoneyflowHistorySource、history_candidate_connection和receive_history_rows；临时驱动只建立受限sink，64KiB接收/32MiB上限/512MB DuckDB/1线程/0spill/RSS768MiB。COPY在BytesIO完整接收后做严格词法、日期、主键、字段数值与归一化校验，释放内存，不调用候选writer。本轮不声称已实测每日文件生成、正式磁盘空间或提升。

| 最大行数代表批次 | 日期数 | 源/归一化行数 | 单次接收MiB | 两次COPY秒 |
| --- | --- | --- | --- | --- |
| `moneyflow` | 18 | 99,839 | 15.02 | 12.109 / 14.766 |
| `moneyflow_cnt_ths` | 20 | 7,890 | 0.82 | 0.837 / 1.111 |
| `moneyflow_dc` | 17 | 99,888 | 12.83 | 7.621 / 6.882 |
| `moneyflow_ind_dc` | 20 | 20,620 | 3.70 | 1.869 / 2.067 |
| `moneyflow_ind_ths` | 20 | 1,800 | 0.18 | 0.706 / 0.556 |
| `moneyflow_mkt_dc` | 20 | 20 | 0.00 | 0.430 / 0.428 |
| `moneyflow_ths` | 19 | 99,070 | 11.42 | 6.674 / 6.816 |

每次源=归一化行数，29次reject均0。七个双读批次source_sha256、逐日行数、历史分类均相同，仅证明各批两次观测稳定，不是全历史一致快照。近期单日2026-09-30分别为普通5572、DC个股6024、THS个股5215、DC板块1031、THS行业90、THS概念387、大盘1行，均与选定日期计数一致。THS 2024-12-19仍2行；DC板块2023-09-12为86行、scope只有行业；不能以当前三分类要求判旧历史缺失。

22样本/29次完整读取与校验合计95.793秒，最大缓冲15753317字节（15.02MiB），进程峰值402.55MiB。全部通过硬预算；业务CSV、候选、正式文件、DuckDB spill为0。一次source侧EXPLAIN ANALYZE的PostgreSQL排序产生约18.6MiB临时读写，这是Prod数据库的排序空间，与DG DuckDB禁止spill是两件事。

[本轮结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_date_query_profile_20261008.json)集中保存完整registry、23个查询计划、真实目录、29次证明及耗时、一次ANALYZE、SQL及源码hash。临时控制文件在`/private/tmp/moneyflow-date-profiling-20261008`，无业务落盘；归属本P3任务，报告冻结并本地验真后删除一次性prepare/profile/freeze驱动，保留受控SQL和只读证明供下一轮复测。未新增常驻脚本或第二套执行入口。

### 21.3 普通moneyflow的读取放大与准入判断

其他六表都有valid/ready的trade_date前导索引，代表计划使用索引/位图读取。普通moneyflow仅有valid/ready的`pk_moneyflow(ts_code, trade_date)`；当前RawMoneyflow模型也只有该主键，没有日期前导Index。普通单日虽可使用主键第二列条件，但不能据此判定日期批次高效。

最大批次日期为2026-08-19..09-11中的18个冻结交易日、99839行：并行Seq Scan→Sort→Gather Merge→Limit，数据库执行11.469109秒；Shared Read Blocks=399690、block_size=8192，共3274260480字节，等于目录记录的当前整张堆表约3.05GiB。三路扫描每路平均Rows Removed by Filter=4663154，表明绝大部分行被过滤；该平均值不能用来冒充精确全表行数。

以既有P0普通217批、首次初采/独立复核434次为条件估算：若均重复同样整表计划，表扫描量约1.292TiB、仅数据库执行约82.96分钟；实际COPY代表批次为12.109/14.766秒。缓存命中、其他日期范围、网络和候选/提升开销均会改变总耗时；表扫描量不等于必然物理磁盘读取量。当前没有触及120秒/12小时拒绝线，问题是Prod反复扫表的负载，而非内存接收失败。

因此：日期读取/内存接收代表样本通过；六表具备后续实现依据；普通moneyflow全量负载先决定索引优化或明确接受当前扫描成本。不能自行回退代码路线、缩成大量单日请求掩盖放大、改变索引或宣称全P3通过。七表计数/真实历史分类再冻结、统一12小时/32GiB/SQL/连接/重试预算、唯一writer、原子提升/冲突/取消恢复和完整链性能仍待开发/验收。

### 21.4 日期前导索引原提案（历史记录；后续获准实施见§22）

建议只给`raw_tushare.moneyflow`新增非唯一B-tree，保持现有主键和所有业务字段语义：

```sql
CREATE INDEX CONCURRENTLY idx_raw_tushare_moneyflow_trade_date_ts_code
ON raw_tushare.moneyflow (trade_date, ts_code);
```

trade_date放首列用于日期筛选，ts_code对应同日稳定排序；不加入宽金额列，不重建表、不改主键、不增加DG配置。实施范围应为RawMoneyflow的Index声明与接真实Alembic head的新迁移，先审计所有实际消费者和迁移执行入口，不凭日期/文件名猜head。迁移开发获确认后进行，Prod执行仍需精确操作和单独授权，不能借本轮“继续推进”直接执行DDL。

PostgreSQL并发建索引避免普通写入被建索引锁阻塞，但需要两遍扫描，会增加CPU/IO并等待相关事务；不能置于普通事务块内，失败可能遗留invalid索引。[PostgreSQL16官方CREATE INDEX文档](https://www.postgresql.org/docs/16/sql-createindex.html)。执行前必须核验真实可用空间、长事务、已有同名索引及当前负载，并确认迁移入口支持事务外并发语句。现有同字段主键468402176字节（446.70MiB）仅作新索引量级参考，不是新增索引/构建临时空间承诺；不能照此数字断言磁盘足够。

建后先只读核验valid/ready/definition，再对本报告相同最大/近期批次重做EXPLAIN和有界COPY，比较扫描块、耗时、行数及两次业务证明；索引存在本身不算性能验收。优化效果现在尚无实证。若取消、失败或invalid，停止并保存现场，不自动DROP/REINDEX/重试。若决定暂不加索引，应在原方案明确接受普通434次整表读取的条件成本，再推进累计执行预算；两个选择都保持批准的日期路线。

本轮只读验收记录及原文档更新尚未提交。源码/测试八项hash与6f7c4ea9的691项隔离验收证据一致；本轮没有源码改动，因此未重复跑该套件。文档/JSON核验结果以本轮最终交付为准。P3全量和正式样本、P4/P5均未完成。

## 22. 获准的普通moneyflow日期索引实施（2026-10-08）

### 22.1 授权、影响面及执行前准入

管理员对§21.4补索引方案回复“确认。做吧”，本轮据此开发并执行该单项索引，不扩大到正式Lake、DG状态或业务同步。目标为`raw_tushare.moneyflow`新增非唯一`(trade_date, ts_code)`索引；现有`(ts_code, trade_date)`主键、字段类型、单位、时间模型、请求及发布路径不变。仅物理访问路径调整，不新增数据集、不修改DatasetDefinition/DatasetExecutionPlan；不引入BIYING处理或跨系统依赖。

CodeGraph explore覆盖RawMoneyflow/历史SQL/source和消费者，但存在同名符号噪声；直接核验模型注册、DAOFactory→GenericDAO→BaseDAO.bulk_upsert、DatasetWriter的raw_std_publish_moneyflow分支和MoneyflowReconcileService日期查询。DAO冲突键从原主键取值，索引不参与幂等；前端/API消费serving字段而非此索引，不需迁移合同。八个DG历史源码/测试hash与前轮验收版本不变；本轮正式执行只使用现行psql入口，不改部署脚本/通用Alembic env。

本地`alembic heads`与Prod `public.alembic_version`均为20261002_000183；新迁移`20261008_000184_add_moneyflow_date_index.py`的down_revision接该真实head。Prod PostgreSQL16.13，堆表3274260480字节、原主键468402176字节；`pg_lsclusters`只读确认16/main路径`/var/lib/postgresql/16/main`，同文件系统空闲53761024KiB（约51.27GiB）。预检没有>60秒事务、prepared transaction、目标表锁等待或并发建索引。初次读data_directory被数据库角色权限拒绝，事务退出后删去该受限参数并改用SSH只读目录/磁盘核验；未改权限、连接地址或配置。

| 本轮范围/资源 | 约束及拒绝条件 |
| --- | --- |
| 对象/写入 | 1张表、1个新索引、1条CREATE INDEX；仅完成后更新本次Alembic版本，不改业务行/主键、不执行旧迁移或安装部署 |
| 规模/空间 | 现有P0约1400万行仅作量级参考，不新增全表COUNT；并发索引约两遍表扫描，已有索引约447MiB作参考，实际构建空间另测；一次操作磁盘准入≥8GiB，不承诺最终索引固定大小 |
| 时间/锁 | CREATE所在会话statement_timeout=15min、lock_timeout=15s；非DDL核验120秒；源码固定迁移会话SET/RESET，无env/Settings/数据库持久配置或运营输入 |
| 事务/恢复 | Alembic autocommit_block让CREATE在事务外执行；成功索引独立持久化，版本最后提交，不声称二者原子。前后检查完整定义、valid/ready/live、非唯一/非主键；只接受已完整且完全一致的索引续跑 |
| 失败/取消 | 任何失败/超时/invalid/定义不符停止，保留真实索引状态和报告；不自动DROP/REINDEX/重试、不标迁移完成。客户端中断后只读核验实际状态，再决定是否可安全续跑 |
| 执行入口 | 本地只生成真实单revision离线SQL，经原psql-remote.sh一次执行；首尾保护检查实际版本，不能stamp或应用无关迁移；不执行部署、pull或服务重启 |
| 进度 | 自有psql应用名标记；长建索引每≤30秒只读pg_stat_progress_create_index，最多90次，展示真实phase/blocks/tuples及耗时；未有准确分母时不虚构百分比/ETA |
| 复测 | 同一最大/近期批次和2026-09-30单日，分别最多100000行/20日；双读source hash/日期计数/严格字段校验；同批EXPLAIN ANALYZE对比扫描量；不写CSV、候选或正式Lake |

模型增加Index声明；迁移采用并发CREATE IF NOT EXISTS前后严格核验，拒绝错误/未完成同名索引，不能只凭IF NOT EXISTS判完成。自动downgrade拒绝删除本次获准索引，后续移除需独立审查。采用[Alembic事务外区段](https://alembic.sqlalchemy.org/en/latest/api/runtime.html#alembic.runtime.migration.MigrationContext.autocommit_block)；本轮只执行单revision，不改全库事务制度。

执行前35项最小回归通过：3项新测试验证并发SQL事务边界/严格校验、原DAO真实ON CONFLICT键保持和禁止自动删除，另32项覆盖现有迁移/锁等待、归一化、reconcile和writer。Ruff通过，单revision离线SQL仅一个索引CREATE和对应版本UPDATE。Prod实施及建后性能结果待下节真实回填，不预填通过。


### 22.2 Prod实施、物理读回及相同批次复测

通过现行psql入口一次执行本地Alembic生成的精确183→184离线SQL，首尾版本保护检查防止错版本或无关迁移；并发CREATE在事务外，valid/ready/完整定义通过后才提交对应版本UPDATE 1。2026-10-08 10:29:52.940至10:30:16.309（上海时区），整个受控执行23.370秒，exit0、stderr为空，没有重试、DROP、REINDEX、stamp、部署或服务重启。首个进度查询时构建已结束，未以空进度记录冒充阶段百分比。

独立只读读回：`public.alembic_version=20261008_000184`；新索引valid=true/ready=true、nonunique，定义与迁移完全一致，444432384字节（423.84MiB）；原主键仍为(ts_code, trade_date)，大小468402176字节不变。源盘剩余53289316KiB（约50.82GiB），未触发8GiB准入线。目录/索引DDL只改变访问结构，业务行不更新；迁移版本表的对应版本更新不混称业务数据写入。

三组SQL/日期/字段/行数与§21完全相同，每组独立读两遍：最大18日99839行、近期12日66697行、2026-09-30单日5572行，6次COPY/344216行。源=归一化行数、reject0，六次source_sha256和逐日计数均与建索引前相等，两遍各自稳定。历史截止日仍2026-09-30，不导入未来日期、不产生CSV或候选；数据接收/严格校验共33.815秒，峰值392.55MiB，预算未放宽。

| 相同普通moneyflow样本 | 单次行数 | 建前COPY秒 | 建后两次COPY秒 |
| --- | --- | --- | --- |
| `max_batch` | 99,839 | 12.109 / 14.766 | 7.638 / 7.716 |
| `recent_batch` | 66,697 | 6.794 | 5.082 / 5.030 |
| `recent_day` | 5,572 | 2.288 | 0.669 / 0.703 |

三组EXPLAIN均为Limit→新日期索引Index Scan，不再走整表扫描/排序。最大批次实际99839行，数据库执行从11469.109ms降至129.153ms；Shared Read Blocks从399690降至2871（8KiB块），Shared Hit Blocks从92变为71620，source排序临时读写从2375/2381块变为0/0。新索引扫描会多次命中已有缓冲块，不把读块×8KiB或缓存命中总量冒充唯一数据量/真实磁盘IO。两个测量时刻的缓存和网络并未控制，不能保证全历史也有同样倍数提速；完整COPY仍包含字段文本序列化、连接及传输，本次最大批次实测约7.7秒，应据此而非0.129秒估计实际读取阶段。

普通moneyflow代表查询的访问结构和接收准入已通过，原§21.3缺索引问题关闭，不再需要管理员接受434次整表扫读。§21旧1.29TiB/83分钟条件估算只作为优化前证据，不能用于新全量预测。七表P3-A来源计数/真实分类整批冻结、累计SQL/连接/重试/12小时/32GiB/唯一writer、候选/提升全链P3-D性能和正式样本仍未完成；这次索引验收不提前关闭P3。

[本轮索引及复测结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_date_index_acceptance_20261008.json)保存权限错误及修正、预检/磁盘、实际执行SQL/log/hash、迁移版本/有效索引、三组计划、6次来源证明和代码hash，不含凭据或业务行。三个源码/迁移/测试文件与原方案/本LLD、前轮只读报告和新报告待提交；Prod已应用184，下一次源码发布必须包含该迁移，不能以stamp或无关升级掩盖源码未发布状态。此操作不需重启现有API/DG服务，未把模型源码发布冒称完成。最小回归35项、Ruff、CodeGraph sync/status均通过；全历史691项未重复执行，历史helper没有变化。

临时retest/freeze驱动在证据冻结后删除；受控SQL、目录/执行/复测证明保留在本任务`/private/tmp/moneyflow-date-index-20261008`，无常驻入口、业务CSV、Lake或DG状态写入。

## 23. 七表统一历史控制入口（2026-10-08，开发依据）

上一轮模型/迁移、两份来源及索引报告、方案/LLD和测试已提交6e25d6e0。依据§19/原方案§24，本轮只开发来源冻结与七表共享的候选执行入口，不开发正式提升、CLI、资产或事件。七表仍各自保存plan/checkpoint/每日Raw/Silver；操作级控制文件不是第八个数据集，也不合并七源字段。

### 23.1 硬口径、配置审计与验收设计

1. 日期和字段从现行合同取得；固定显式截止日。通过原psql入口对每表做两次有界聚合，冻结批准列的真实类型、逐日行数/键数及DC实际历史分类。不读取业务金额/证券行或系统字段，不按代码游标、当前证券池或三分类日更规则裁剪。聚合行数最多20000日期、DC最多60000分类行，额外一行用于发现超限；小控制JSON在≤32MiB内存内接收，持久化为JSON，不生成业务CSV。
2. 两次聚合必须完全相同；单日计数/键/无效身份/字段类型不符则阻断。单表完整冻结证据逐表持久化，七表齐全才原子冻结cohort manifest。恢复完整manifest时每表再做一次只读聚合，与冻结类型/日期/分类逐项一致，不能只信缓存计划；变化则停止，不自动刷新计划或覆盖旧候选。
3. 共用既有Store/Control及日期候选核心；不是在七个单表预算外再套摘要。七表共用一个12小时/32GiB账本，步骤120秒预扣，COPY/连接/SQL在启动前持久化计数，崩溃保留预扣。新增唯一请求上限为14+2×实际unit数+14；最后14次仅用于人工恢复/失败尝试，无自动重试。既有P0参考423批时正常860连接/3440 SQL，上限874连接/3496 SQL，实际冻结后重算。
4. 唯一writer锁位于staging的moneyflow命名空间，单unit与cohort入口都必须取得；同一或不同operation ID不能并发运行历史writer。单unit入口拒绝加入已有cohort操作，旧单表操作目录不自动接管。未来正式日更的锁接入仍属于P4，当前不能冒称已有日更互斥生效。
5. 已完成unit保存checkpoint真实hash及日期/行数摘要。恢复只对闭合前缀检查实际文件hash/路径与已验收checkpoint，不重复对全部历史文件逐日解码或重抓已完成来源；当前未闭合unit仍使用原候选复核恢复链。完成标记/JSON不一致、文件缺失或被改即阻断。最终完整候选复核只标candidates_verified，不代表正式提升/事件完成。
6. Store从操作根统计七表候选、控制及失败现场，首次/恢复只做一次受控元数据盘点，每个新文件按stat增量记账；不在每日结束重扫全历史。启动64GiB/最大32GiB、RSS768MiB、DuckDB512MB/1线程/0spill、32MiB接收/64KiB块不放宽。

配置审计：仅新增run_contracts/moneyflow.py的固定七表名单和MONEYFLOW_HISTORY_EXTRA_REQUESTS=14；前者为来源白名单，后者为全操作人工恢复余量。均为版本化代码合同，无env/Settings/数据库/页面输入，来源metadata builder、cohort planner/Control及测试消费；变更即operation identity变化，随源码发布生效。其余集中预算值保持不变，新的cohort manifest/progress记录实际上限、使用数、阶段、dataset/local及global unit、完成/总量/百分比、最后更新时间和ETA“暂无法估算”。

CodeGraph explore覆盖日期候选核心→Store/Control→source/receive→schema；直接源码核验补齐测试、保护runner及路径消费者。影响范围仅bootstrap元数据/统一控制、原候选核心/transport、集中历史名单/恢复余量及测试。日期业务SQL、七表字段/精度、正式路径、Prod/Web合同和依赖矩阵不变；没有新增Dagster definition或resource。

验收：用七表真实公开fixture做源/Raw/Silver行数与逐字段候选检查；反例覆盖缺表、错类型、日期/分类变化、键重复、旧目录接管、全操作预算不能因换dataset重置、请求上限预扣、跨operation锁、闭合文件篡改、取消及真实进程退出后续跑。实际Prod只读验收仅调用来源冻结，预计14短事务/56 SQL，依据已有21160938行量级做受限聚合，不读取业务明细或执行候选writer；冻结控制证据放本任务/private/tmp并汇总到reports。候选性能先在隔离临时目录验证，正式样本另行批准；本轮不写移动盘或正式DG。

### 23.2 实现、计划对账与真实验收

入口为bootstrap/moneyflow_history_cohort.py的freeze_moneyflow_history_cohort和build_moneyflow_history_cohort_candidates；前者只冻结控制事实，后者使用同一上下文生成候选。新增moneyflow_history_metadata.py固定SQL/有界解析；原PsqlMoneyflowHistorySource只增加metadata方法，仍走固定psql脚本和连接文件。控制JSON经COPY TEXT的UTF8十六进制传输，避免CSV长字段上限和反斜杠转义歧义；32MiB限制作用于传输字节，解码后≤16MiB。不持久化业务CSV，不新增运行配置或任意SQL输入。

| §23.1硬口径 | 真实代码落点 | 验收证据 |
| --- | --- | --- |
| 独立七表、明确日期/类型/键/历史分类 | metadata固定白名单SQL/validate；cohort._manifest重建七份现行日期plan，hash含合同与集中预算 | 七表SQL正例及非法日期/表名、缺表/错类型/NULL日期/重复键/分类/超限负例；Prod两次冻结完全相同，历史早期允许只有行业 |
| 来源两轮冻结与恢复拒绝漂移 | _metadata逐请求proof、source-freeze逐表证据、_freeze完整cohort原子落盘；恢复每表再读一次 | 首轮14请求与恢复7请求；完整/半途冻结后改变日期计数或类型被拒绝，来源不会自动刷新 |
| 七表真正共享12h/32GiB/请求余量 | _operation仅创建一个Store/Control；_build_unit接受共享实例；source请求前计数/连接/SQL持久化；_manifest上限2×7+2N+14 | 12小时/全操作磁盘/请求上限负例、换dataset不中断账本、计数不一致拒绝、真实os._exit后120秒预扣与17次请求保留，恢复累计36次且第一表不重抓 |
| 唯一writer与旧目录拒绝 | <staging>/moneyflow/writer.lock，单unit/cohort两入口共用；cohort-control identity标记 | 不同operation互斥；单unit不能加入cohort；旧单表目录拒绝接管 |
| 已闭合前缀与当前unit的不同恢复路径 | closed_units保存checkpoint hash/日期计数；_closed_prefix仅hash复核已验收字节；未闭合仍走原物理/来源双检查 | 已闭合Raw/receipt/全局完成计数篡改阻断；取消/真实进程退出后新进程续跑；七表样本恢复无业务COPY、全部文件hash不变 |
| 内存、磁盘与步骤准入 | 原32MiB流接收/768MiB RSS/512MB单线程0spill；Store单次启动元数据盘点有取消/RSS/120秒保护，文件stat增量；异常保留现场再盘点 | 真实冻结96.25MiB/恢复103.02MiB；候选290MiB；32GiB稀疏文件反例，32MiB全cohort JSON与原256KiB单unit receipt分开读，账本>256KiB可恢复而单unit上限未放宽 |

全cohort JSON/账本上限32MiB，普通单unit receipt仍256KiB。初始/恢复目录盘点为准入检查，限120秒且可取消；已进入执行的来源/候选/hash复核步骤预扣120秒并持久化，异常退出保留预扣，正常完成按实耗冲回。全局progress包含阶段、dataset/local/global unit、完成/总量、百分比、请求/连接/SQL、最后更新时间及无法可靠估算的ETA；冻结前总unit尚未知时百分比为NULL，不伪造全历史进度。元数据聚合、候选与闭合前缀恢复都消耗同一时间/请求账本，不为每表创建新账本。初始盘点和小控制文件的载入/计划重建属于有界准入，不将其计入已开始步骤的持久执行秒数。

Prod事实及逐表行数/日期/批次表见原方案§28：14次只读聚合77.891秒，7次恢复聚合35.978秒，累计21连接/84 SQL，21,160,938行/7,804日期/423批，与P0一致；源类型、日期、计数和分类均不变。来源聚合允许受限扫描既有已知规模的日期/身份索引，不是为发现未知规模新增全表COUNT；每事务120秒、READ ONLY、批准投影、LIMIT额外一行和聚合计数检查共同约束，不读取金额/证券明细。

候选测量为六表公开fixture与大盘既有负值/NULL合成样本（修正§23.1“七表真实公开fixture”的笼统说法）：5572/387/6024/1031/90/1/5215行，共18,320行，源=归一化=Raw=Silver、reject0、差异0。新进程完整cohort构建1.285秒、恢复0.019秒、峰值290MiB，共14文件；第一次28连接/112 SQL（fake metadata与业务COPY），恢复仅7个fake metadata读取，累计35/140，候选hash全部不变。最大10万行批次和正式提升耗时仍待P3-D，不能用此单日样本代替。

新专项最终38项，原日期历史122项，最终历史160项；此前联合七表/请求策略727项通过，其中36项新cohort测试，最后两项大账本与计数不一致测试通过并重跑全部160历史项。保护runner仅新增两个精确bootstrap源码清单条目，没有扩大隔离权限；治理12项/474子测试、静态合同113项均通过。默认Ruff改动检查、全src/tests致命规则、文档完整性/新链接及diff检查通过。CodeGraph explore覆盖原候选核心→source/receive/schema，query确认新cohort入口，sync/status当前；直接代码核验补齐测试、路径及保护runner。不存在Prod DatasetDefinition/API/前端合同变更，也没有foundation反向依赖或需要人工迁移的消费者边界。

[本轮结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_cohort_evidence_20261008.json)保留完整批准聚合SQL、真实类型/日期/分类、21次hash与计数、候选共享账本/checkpoint、最终代码hash与测试结果。Prod恢复实测后只补全进度百分比、账本JSON写入上限与两项账本测试，最后160项覆盖最终代码；源SQL与真实执行文件逐字一致。测试/private/tmp操作不能搬作正式完成证明；本轮不写正式Lake/DG，不发事件。下一轮仍需逐文件原子提升/幂等恢复，以及明确授权的正式样本与全链性能；P3不提前关闭。

## 24. 逐文件历史提升（2026-10-08，当前开发依据）

七表来源冻结、共享候选与测试/证据已提交a55645ee。管理员要求继续下一步；依据§19.4与原方案§24/§28，本轮只开发默认preflight的提升helper、隔离样本/恢复与性能验收。无新增CLI、资产/catalog、事件或日更入口；正式写湖仍须P3-E精确样本范围批准。本轮不操作移动盘、Prod或正式DG。

### 24.1 硬口径、影响面与预算

1. 只接受当前七表cohort、固定截止日、完整verified候选前缀和原checkpoint真实hash；逐项重建manifest/plan并核验来源两轮证明、日期计数和冻结DC分类。提升使用已独立复核的来源证明，不重新读取Prod；来源再次读取仍属于候选阶段，不在提升中发起业务或元数据请求。
2. 路径集中新增paths.py的raw_moneyflow_path/silver_moneyflow_path，固定批准布局raw/tushare/{dataset}/trade_date={day}/part-000.parquet、silver/moneyflow/{dataset}/trade_date={day}/part-000.parquet。正式根仅paths.py的DEFAULT_LAKE_ROOT，正式staging仅DEFAULT_LAKE_STAGING_ROOT；隔离测试允许可信系统临时目录下互不包含的lake/staging。拒绝相对路径、符号链接、任意移动盘/旧根、层/日期/数据集越界；正式根需已挂载且存在，不由helper创建。
3. 默认apply=False，仅核验并记录staging控制证据；apply=True才逐文件提升。整个cohort先做hash/目标冲突/邻居Parquet/同st_dev/目录准入；当前unit再复用audit_history_day做有界schema/日期/键/精度/Raw-Silver全业务字段对账，一批≤20日/40文件。不能把单文件存在或JSON绿色代替物理核验，不对全部历史逐日期解码；已验收完成前缀恢复仅检查真实文件hash和checkpoint链接。
4. 同hash正式目标幂等复用；不同hash或布局停止，无覆盖/备份/删行/重导/自动重试。Raw先于对应Silver；单文件fsync后同文件系统os.replace，随后同步源/目标目录并hash读回，再原子checkpoint。Raw成功Silver失败时日期未完成，不发事件。取消、进程退出、状态写失败不回滚实际文件；rename已发生而checkpoint未闭合时从正式hash接回。
5. 原verified候选checkpoint和closed_units hash保持不可变；每unit另有promotion.json，链接cohort/promotion合同及candidate checkpoint，保存promoting/complete与逐文件intent/complete。根promotion-contract.json绑定明确lake根/原计划，目标根不能在恢复时换。进入提升后原候选入口拒绝再生成，防止重建已移走候选；操作级writer锁与同一Control/Store继续复用。
6. 操作目录盘点加上由逐文件意图与实际正式目标确认的已提升字节，32GiB不能因rename释放额度或恢复而重置；现存相同正式文件不冒充新增写入。文件intent先落盘，未完成intent的实际目标也纳入空间。完成文件/行数/日期按实际读回汇总，候选完成数与提升完成数分别记录；阶段百分比基于当前提升文件量，不在提升途中仍显示候选100%。

本轮无新env/Settings/DB/页面配置或预算常量。apply是本次动作意图，默认false；lake_root/staging_root沿现行固定路径合同，仅临时测试根是隔离入口；新promotion版本/拒绝冲突策略是版本化恢复合同，变更会阻断旧提升状态。原12h/32GiB/120秒步骤、64GiB首次准入、32MiB/64KiB、768MiB RSS、512MB/1线程/0spill与874最大来源请求均不放宽；提升不消耗来源请求，但预检/hash/当前unit校验/逐文件提升计入同一持久时间账本。消费点为bootstrap提升helper、cohort/候选恢复与测试；随代码发布生效，progress保存拒绝原因和真实完成量。

| 规模/性能项 | 冻结量级与本轮拒绝/验收 |
| --- | --- |
| 范围 | 7独立dataset，423unit、7804数据集日期、15608最终文件、21160938行；单unit≤20日/100000行/40文件，提升批次不超过原100日门禁 |
| 来源/SQL | 提升阶段0 Prod/Tushare请求；当前unitDuckDB复用原完整校验，只扫该unit实际Raw/Silver，已完成前缀不重复深解码；所有调用有取消/120秒保护 |
| IO/临时目录 | 全操作一次有界文件hash/冲突预检，最多候选+相同已有目标各一遍；当前unit再hash/物理校验/读回，后续resume已闭合前缀hash复核。无Parquet复制/转换/spool、没有新增spill；rename不新增业务字节，控制JSON逐文件增量 |
| 提交/恢复成本 | 单文件os.replace和checkpoint，不能宣称多文件事务；重跑最多当前未闭合unit完整校验，其余hash接回。source与target不同st_dev、hash/路径/布局不符即停止 |
| 空间/耗时 | 原两层约3523MiB仅参考，本轮隔离真实fixture和接近10万行样本测hash/校验/提升/恢复耗时、实际字节/RSS；全历史网络与正式盘吞吐未测，不外推SLA |

CodeGraph explore覆盖cohort→closed_prefix/Control→候选audit、原索引/周线提升例；直接核验paths、现行Raw/Silver校验、运行账本及测试补齐图遗漏。新增moneyflow_history_promote.py和集中路径，候选/共享控制仅迁移移动后恢复、实际空间与进度消费者；保护runner增加精确源码清单，不扩权限。七表字段/类型、Prod/API/前端合同、日更语义与主体依赖矩阵不变。

验收包含七表正例、同hash复用、不同目标/邻居冲突及全范围先拒绝、跨设备/符号链接/错误根/旧状态、未verified来源、候选篡改、取消/真实进程退出/rename与checkpoint之间退出、状态写失败保留正式文件、恢复不重导且预算/字节不重置、Raw完成Silver未完成不算成功、大账本和空间拒绝。原历史160项和七表/策略569项回归，治理/静态/Ruff/文档门禁按本轮影响复核。正式样本仅形成可审阅的命令/日期/目标/冲突清单，不提前执行。

### 24.2 实现、隔离验收与剩余条件

入口为 `bootstrap/moneyflow_history_promote.py` 的 `promote_moneyflow_history_cohort`，默认 `apply=False`。它只接受完整、已独立来源复核的七表候选操作，不请求 Prod/Tushare；路径来自 `paths.raw_moneyflow_path/silver_moneyflow_path`。`promotion-contract.json` 固定来源 cohort、闭合候选 hash、目标根及冲突策略，各 unit 的 `promotion.json` 保存逐文件意图和完成事实。原候选 checkpoint/closed_units 不变，控制 ledger 继续使用同一个 Store/Control。开始提升后，原冻结/候选入口在唯一 writer 锁内、创建 Store 和改进度前拒绝，避免重新导出被移走的文件或漏算已提升空间。

| §24.1硬口径 | 实现落点 | 验收 |
| --- | --- | --- |
| 七表已验证来源、原计划和闭合证明 | `_frozen/_promotion_contract/_closed_prefix` 重建身份并核验 checkpoint/source proof/实际文件 hash | 未 verified、修改来源 scope、checkpoint/文件被改均停止；七表正例及原历史160项 |
| 全范围先检查，当前批完整物理对账 | `_preflight/_file_location/_target`；候选 `_audit_files` 通过可解析的混合路径复用原 `audit_history_day` | 后面一表有冲突或邻居文件时，一个文件也不提升；即使篡改文件与 receipt/hash 同时一致，非 Parquet 仍被 `history_columnar_error` 拒绝 |
| 原子提升、相同内容幂等、不同内容拒绝 | `_promote_file` 先写 intent，fsync、同设备 `os.replace`、目录同步/hash 读回，再落逐文件 complete | 七表实际临时目录提升；相同目标全部复用，禁止复制/重写；不同内容/跨设备/符号链接/错误根拒绝 |
| 取消、退出和状态失败保留已完成文件 | `_promotion_state` 与 `_file_location` 从 staging/正式目标解析实际位置；部分 unit 重审，闭合 unit 仅 hash 复核 | 三处取消；两个真实子进程在 rename 后、receipt 后 `os._exit(23)`，新进程恢复成功；状态写失败后实际文件仍在，续跑接回 |
| 同一空间/时间/来源请求账本 | Store 的外部字节盘点复用原32GiB准入；`_moved_bytes` 包含 intent 后实际已移入的正式文件；Control 继续120秒步骤预扣 | 恢复保留崩溃120秒预扣与累计计数；只统计 staging 尚未超限时，补入已移入正式区的字节仍触发同一个磁盘门禁；提升新增来源请求0 |
| 完成量来自文件事实 | 根 progress 分别保存 promoted_files/dates/rows/units，日期和行数仅在 Raw/Silver 都闭合后累加；恢复先重算 | Raw 提升后取消，日期/行数完成量仍0；完整七表才到100%，不会把候选100%误作提升完成 |

性能测量只写 `/private/tmp/moneyflow-promotion-20261008`，真实正式根、DG instance 和 Prod 写入均为0。六表使用已发布的20260930公开 fixture，大盘使用负值/NULL合成样本；不是本轮重新读取生产数据。最大批次将普通 moneyflow fixture 的5000个独立证券扩展到20个合成日期，构成100000行单 unit；其余六表仍使用单日样本。日期扩展仅用于隔离压力测量，不是历史日期补齐。

| 隔离样本 | 行数/数据集日期/文件 | 候选构建 | 提升前预检 | APPLY | 同内容重跑 | 进程峰值RSS |
| --- | --- | --- | --- | --- | --- | --- |
| 七表单日 | 18320 / 7 / 14 | 1.272秒 | 0.018秒 | 0.154秒 | 0.022秒 | 314.23MiB |
| 普通10万行/20日加其余六表 | 112748 / 26 / 52 | 5.521秒 | 0.043秒 | 0.459秒 | 0.046秒 | 466.09MiB |

两组实际 Raw/Silver 文件字节分别2,828,944和21,328,166；恢复账本含控制与已移入目标字节，分别2,871,030和21,381,157，不能因 staging 的 Parquet 清空而归零。源/归一化/Raw/Silver行数一致、reject0、业务差异0；提升前后与重跑每个文件 hash 都与原验证 receipt 一致，原候选 checkpoint 字节不变。首次候选28次 fake 来源请求/112 SQL，提升和重跑不新增来源请求。这些耗时包含当前批物理校验、fsync/rename/hash/checkpoint，不包含真实数据库/网络、正式盘吞吐或事件；并行执行两个隔离样本时测得，不是全历史 SLA。512MB/1线程/0spill、768MiB RSS等预算不变。

新增提升36项，联合原历史160项及七表/策略569项，共765项通过（75.50秒）。受保护治理原 runner 12项/474子测试、静态合同113项通过，精确清单只增加提升 helper，不扩隔离权限。改动默认 Ruff、全 src/tests 致命规则、diff 和文档门禁通过。CodeGraph explore/impact/sync/status核验共享 audit 与恢复、路径消费者；图中不完整的测试边由当前源码核验补齐。没有新增业务 API/CLI、Dagster definition/resource 或跨子系统依赖，无需迁移 Prod/前端消费者。

[本轮结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_history_promotion_evidence_20261008.json)保留两组文件/receipt hash、完整进度/实际字节、代码 hash、测试日志 hash及硬口径对账，不含凭据。两组最终测量均从新隔离目录完整构建，未放宽生产合同。

本轮关闭逐文件提升开发与提升侧隔离恢复验证，补齐 P3-D 的本机候选/检查/提升测量；不关闭 P3-D 正式盘性能、P3-E 或整个P3。当前 helper 只接受完整 cohort，尚不能把全历史操作裁成任意正式日期样本。下一步须先补同一执行链的有界真实来源样本入口：明确日期白名单、逐表预期行数、真实冻结/复核证明、同设备路径/冲突清单和准确命令，完成隔离验证后才提交正式写湖批准；不得删除 manifest 日期、伪造 Prod 证明或直接执行全量来代替最小样本。正式样本还需确认维护窗口/当前日更 writer 状态；历史 writer 已共享锁，P4日更接锁仍未激活。CLI、资产/分区事件、全历史和P4/P5继续后置；`files_complete` 只代表文件阶段完成，不能当作正式资产/事件验收。

## 25. 显式日期样本入口（2026-10-08，当前开发依据）

管理员要求提交并继续§24下一步。上一轮九个资金流文件已独立提交 `e3ccb04c`，逐项内容与§24验收一致，未推送。本轮只补同一 bootstrap 链的有界日期样本输入及正式样本命令，不新增CLI/asset/check/resource/event，也不执行正式文件提升。

### 25.1 硬口径、配置审计与性能门禁

1. 现有 freeze/build/promote helper 增加关键字参数 `selected_dates=None`，None仍表示原截止日以前的完整来源范围。显式样本必须是已排序、无重复的ISO日期tuple，非空且≤既有20日窗口上限、全部≤cutoff；不接收字符串/list/任意SQL，不提供对象过滤。样本每表总行数≤既有100000行unit上限，元数据发现超限就在业务COPY前停止。使用相同七表名单，不增加“七源合成数据集”。
2. 日期名单直接进入 metadata SQL 的 `trade_date IN (DATE ... )`，保留NULL日期身份拒绝检查，不先聚合全历史再筛选。元数据结果回显 selected_dates；parser/validator核验完全一致，并拒绝名单外事实。逐日/键/实际历史DC分类由同一次真实来源聚合取得；默认全历史SQL/结果合同保持不变。
3. 样本身份使用独立版本，包含明确日期名单与每表样本行数上限；原cohort manifest包含真实snapshot与对应plan，不能从完整manifest删日期。相同operation ID改变日期、变成全历史、改变截止日或预算均拒绝；promotion同样要求显式传入原日期意图，并重新核验身份与proof。缺某一天保留真实缺口并在样本manifest列出missing_dates；一个表在整个名单内都没有数据则停止，不制造空Parquet/完成事实。
4. 原日期业务COPY只使用冻结plan中实际日期，所有approved字段、精度、历史NULL/分类保持不变；两次元数据冻结、两次来源业务复核、候选完整验证、逐文件提升与恢复全复用原能力。同一namespace writer与Store/Control，32GiB/12h/RSS768MiB/512MB/0spill不放宽，不创建另一个样本状态实体或test-mode。恢复来源计数改变即停止，不自动刷新。
5. 本轮真实验证仅freeze样本控制事实，控制/SQL/proof放本任务/private/tmp，走原 `PsqlMoneyflowHistorySource` → `bash scripts/psql-remote.sh`。仅批准七表目录字段类型及选中日期的行/键/NULL/分类聚合，READ ONLY、120秒/事务、LIMIT额外一行；不读取金额/证券明细、不写候选/正式Lake/DG/Prod。业务候选与提升仍只用隔离fixture。本轮末列准确正式命令、工作目录、operation ID、两根路径、日期/行数/目标/冲突与恢复条件，正式写湖另行批准。
6. 正式样本候选调用显式传入 `expected_cohort_hash`，与本轮真实只读冻结的完整日期/类型/计数/分类合同一致才允许业务COPY。该参数默认None，已有全历史调用不变；一旦传入，批准意图保存在原progress，续跑省略参数仍执行原hash核验，换hash停止。比较在同一次14请求来源冻结后完成，不额外先freeze再build，避免平白多读7次元数据并耗掉恢复余量。

配置审计：selected_dates和expected_cohort_hash是单次bootstrap动作意图，不是env/Settings/数据库/页面配置；默认None由当前helper显式定义，样本日期名单持久化于原cohort-control/cohort/source-freeze/progress及promotion合同，批准hash保存在同一progress的reviewed_cohort_hash。唯一新固定值是样本身份版本；日期/行数拒绝线复用run_contracts/moneyflow.py的20日/100000行常量，无新预算。消费点为metadata request/SQL/parser、cohort身份/manifest/冻结/业务plan和候选准入、promotion frozen校验和测试，随代码调用生效；progress/manifest对运营显示选中和实际日期、缺失日期/行数、批准hash、请求/时间预算及阶段。

| 项 | 本轮设计预算与待实测 |
| --- | --- |
| 代表范围 | 2024-12-19与2026-09-30，来自§23真实冻结的共同日期；早日DC行业-only、近期日三类；七表预计29783行/14数据集日期/14跨年unit/28两层文件，须本轮只读刷新 |
| 请求与事务 | freeze两轮14连接/56 SQL；完整候选另28连接/112 SQL，正常合计42/168，原14次人工恢复余量后上限56/224；每COPY有界、事务结束ROLLBACK。提升0源请求；恢复freeze另7连接/28 SQL也消耗余量 |
| 最大输入 | ≤20显式日期×7表，每表合计≤100000行，总≤700000行/140数据集日期/280文件/最多140跨年unit；超出停止，不自动拆成新的样本或全历史 |
| 计算与IO | 原≤32MiB内存接收、64KiB流块，DuckDB按真实冻结unit生成每日Raw/Silver，当前unit完整校验；原checkpoint与原子提升，不写CSV/spool/spill/备份。正式文件不重编码 |
| 耗时/空间 | 两日来源聚合按已有日期索引预计主要是14次连接开销，初估10～30秒，实际回填；隔离两日转换/提升预计秒级，不能外推正式盘。仍以120秒步骤/12h累计/32GiB/RSS768MiB拒绝，首次64GiB准入 |
| 验收 | SQL名单与业务COPY范围正反例、日期/类型/数量/名单外结果、缺口/全空、跨年/超总行数、相同operation换范围拒绝、默认全历史回归、取消/进程退出/幂等与预算延续；Prod仅两轮有界真实聚合，正式文件写入另批 |

CodeGraph explore覆盖metadata→source固定入口→cohort/plan→promotion及调用方，直接源码审计补齐所有validator/parser与单unit/测试消费者；没有Prod DatasetDefinition、Web/前端、日更或active Dagster定义消费者。按模板§7A/§18，历史文件入口的时间输入、执行unit、缺口/完成审计分开：名单是请求意图，unit只含源实际日期，缺失日期不自动判错或补数据；整个表全空不能进入本次七表样本。既有API/CLI行为与依赖矩阵不变。

### 25.2 实现与真实只读、隔离验收结果

本轮已经完成显式日期入口。上一轮九文件逐文件提升已独立提交 `e3ccb04c`，未推送；本节代码、测试、报告与原方案/LLD回填尚未提交。`freeze_moneyflow_history_cohort`、`build_moneyflow_history_cohort_candidates` 和 `promote_moneyflow_history_cohort` 接受同一 `selected_dates`；不传时保留原全历史入口，七表默认SQL与§23实际执行版本的SHA256逐项相同。样本是另外一个完整操作，不裁剪原全历史manifest；同一个operation不能切换日期、截止日、预算或全历史/样本身份。

真实Prod只读通过原 `PsqlMoneyflowHistorySource` / `scripts/psql-remote.sh`，仅查询七表批准字段类型和这两天的数量、键、NULL与分类聚合。每表两次，共14个短READ ONLY连接、56条SQL；4.029秒、峰值87.02MiB，两轮一致。SQL在聚合前使用准确日期名单，保留NULL日期哨兵；最终代码生成的SQL与这14次实际执行文本/hash相同。没有导出金额/证券业务明细，没有写Prod、正式Lake/staging或DG。与全历史冻结范围相比，只核验了本次明确的两个日期：

| 独立数据集 | 2024-12-19行数 | 2026-09-30行数 | 合计 |
| --- | --- | --- | --- |
| moneyflow | 5106 | 5572 | 10678 |
| moneyflow_cnt_ths | 388 | 387 | 775 |
| moneyflow_dc | 5790 | 6024 | 11814 |
| moneyflow_ind_dc | 86 | 1031 | 1117 |
| moneyflow_ind_ths | 90 | 90 | 180 |
| moneyflow_mkt_dc | 1 | 1 | 2 |
| moneyflow_ths | 2 | 5215 | 5217 |
| 合计 | 11463 | 18320 | 29783 |

七表两天均实际存在，无缺失日期。早日DC板块只有行业86行且ts_code允许NULL；近期日包含行业/概念/地域，沿用冻结的真实分类口径。两天跨年，因此形成14个日期unit、14个数据集日期、28个Raw/Silver文件。只读来源合同hash为 `19358e2bc422173cc42e6119386124a629a25f943989e52bd01a6b927ccbdc98`。正式执行重新读取元数据后必须等于它；类型/行数/日期/分类漂移时先停，不能靠更换hash或扩大日期继续。

代表性业务链只在 `/private/tmp/moneyflow-selected-20261008/isolated-reviewed` 测量：六表近期日使用公开fixture，早日按真实数量/分类构造测试行，大盘使用负值/NULL合成值。不是实际Prod金额或早日证券数据，不能用来宣称源业务值已验收。元数据严格匹配本轮真实冻结，候选实际启用上述批准hash核验；源替身/归一化/Raw/Silver共29783行一致，reject0、业务差异0，28文件总4,712,754字节。构建2.239秒、预检0.035秒、提升0.331秒、幂等重跑0.043秒，峰值358.55MiB；提升后/重跑hash与原receipt一致，原checkpoint不变。候选42次fake请求，提升及重跑新增来源请求0。它证明入口与恢复链可用，不是正式磁盘或真实传输SLA。

| §25.1硬口径 | 当前代码点 | 正向与拒绝验收 |
| --- | --- | --- |
| 精确日期意图及默认行为 | metadata的`validate_moneyflow_history_selected_dates/sql/parser`；cohort的`_cohort_identity/_metadata/_freeze` | 七表SQL前置IN；默认SQL原hash；非法/注入/重复/无序/超过20日/晚于cutoff拒绝且不创建操作、不请求来源 |
| 实际日期与缺口分开 | metadata validator、原`build_moneyflow_history_plan`、cohort `_manifest` | 跨年实际日期进入原unit；一表缺一天只记missing_dates、不生成空文件；整表全空、名单外事实、类型/键错误拒绝 |
| 不变的操作与预算 | 原 `_operation/Store/Control`，sample identity | 相同operation切换日期或全历史拒绝；每表总行数超过100000在业务COPY前停止；仍共用原时间/空间/连接账本 |
| 经审查的来源才能导出业务 | 候选builder的`expected_cohort_hash`，progress `reviewed_cohort_hash` | 正确hash仍为42请求；错误hash只有14元数据请求、0业务COPY；续跑省略hash仍拒绝，换hash/非法持久hash拒绝 |
| 原完整校验与逐文件恢复 | 原候选/列式audit、promotion `_frozen/_preflight`，同一日期意图 | 28文件完成；省略日期提升拒绝；同内容重跑不改文件；真实子进程完成首unit后退出，新进程49请求续跑且闭合文件hash不变 |
| 取消与提升失败安全 | 沿用原候选Control/逐文件intent/complete链 | 联合原候选与提升用例覆盖中途取消、rename后退出、状态写失败、预算延续和部分正式文件接回；本次新日期用例覆盖真实退出/续跑 |

新日期入口39项通过；联合原历史/提升及七表日更/请求策略共804项通过（79.70秒）。受保护原runner治理12项/474子测试、静态合同113项通过，改动默认Ruff、全src/tests致命规则通过。CodeGraph explore、metadata/builder impact、sync/status已核验；builder符号图只有自身/file边，测试与promotion/parser/unit消费者补查实际源码，没有依赖模糊项被默认放行。没有修改Prod DatasetDefinition、业务API/CLI、Dagster definitions或子系统依赖矩阵。

正式路径只做stat/glob：两根目录已挂载且同为设备16777244，当时空闲约2.66TiB，28目标不存在且无邻居Parquet/符号链接；拟用operation和共享writer.lock不存在。当前assets/jobs/sensors/catalog源码没有七表日更writer，P4仍未激活。这是当时的只读事实，不能保证未来没有其他进程；正式执行需重新核对并占用人工维护窗口，不自动启停服务。实际源SQL、类型/计数/分类、逐请求证明、隔离文件/hash/字节、28准确目标、代码及测试日志hash保存在[本轮结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_selected_dates_evidence_20261008.json)。

### 25.3 待批准的正式两日样本执行清单

本节是可审查的下一步，不是本轮已执行记录。批准范围仅七表×2024-12-19和2026-09-30：从真实Prod读取批准投影，直接构建每日候选，再提升到正式Raw/Silver；不执行全历史、DG资产/分区事件、sensor、日更或P4/P5。工作目录固定 `/Users/congming/github/goldenshare/lake_console/orchestrator`；使用现有 `.venv/bin/python3`，不安装或同步依赖。helper不读写Dagster instance，因此不使用任何 `DAGSTER_HOME`。

候选与控制目录为 `/Volumes/datasource/data_lake_staging/moneyflow/history-sample-20261008`。正式目标由 `paths.py` 给出，每个表/日期各一个：`/Volumes/datasource/data_lake/raw/tushare/{dataset}/trade_date={date}/part-000.parquet` 和 `/Volumes/datasource/data_lake/silver/moneyflow/{dataset}/trade_date={date}/part-000.parquet`；28个完整路径见上面报告的formal_sample_proposal.targets。没有Gold或其他目标。

执行前确认维护窗口无其他七表writer、移动盘挂载/权限/空间、目标无冲突。共享namespace锁只约束复用该锁的历史helper，不能声称覆盖任意外部进程。第一步在同一次候选构建中读取两轮真实元数据并核对已审计hash；随后按14个日期unit各读两次业务COPY，共59566源行，两遍不是重复写入行数。正常42连接/168SQL，上限56/224，包括失败与恢复；无自动重试或额度重置。以下为准确命令，在上述工作目录分别执行：

```bash
.venv/bin/python3 -B - <<'PY'
import json
import os
import shutil
from pathlib import Path
from orchestrator.defs.bootstrap.moneyflow_history_cohort import build_moneyflow_history_cohort_candidates
from orchestrator.defs.bootstrap.moneyflow_history_source import PsqlMoneyflowHistorySource
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
lake, staging = Path(DEFAULT_LAKE_ROOT), Path(DEFAULT_LAKE_STAGING_ROOT)
assert lake.parent.is_mount() and lake.is_dir() and staging.is_dir()
assert lake.stat().st_dev == staging.stat().st_dev
assert all(os.access(p, os.R_OK | os.W_OK | os.X_OK) for p in (lake, staging))
assert shutil.disk_usage(staging).free >= 64 * 1024**3
result = build_moneyflow_history_cohort_candidates(
    staging_root=staging, operation_id='history-sample-20261008', cutoff='2026-09-30',
    selected_dates=('2024-12-19', '2026-09-30'),
    expected_cohort_hash='19358e2bc422173cc42e6119386124a629a25f943989e52bd01a6b927ccbdc98',
    source=PsqlMoneyflowHistorySource(),
)
print(json.dumps(result, ensure_ascii=False))
PY
```

第二步预检28个候选/实际目标的完整hash、目录、同设备和冲突，再复用原当前unit物理校验。下面 `apply=False` 不提升文件，但会在正式staging保存预检和promotion合同，所以也包含在本次待批准正式动作范围内：

```bash
.venv/bin/python3 -B - <<'PY'
import json
from pathlib import Path
from orchestrator.defs.bootstrap.moneyflow_history_promote import promote_moneyflow_history_cohort
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
result = promote_moneyflow_history_cohort(
    staging_root=Path(DEFAULT_LAKE_STAGING_ROOT), lake_root=Path(DEFAULT_LAKE_ROOT),
    operation_id='history-sample-20261008', cutoff='2026-09-30',
    selected_dates=('2024-12-19', '2026-09-30'), apply=False,
)
print(json.dumps(result, ensure_ascii=False))
PY
```

只有预检通过才执行第三步。它逐文件fsync/同文件系统`os.replace`，读回实际hash后登记完成；不同内容/跨设备/错误布局停止，不覆盖、复制、重编码、删除或备份文件。提升源请求为0：

```bash
.venv/bin/python3 -B - <<'PY'
import json
from pathlib import Path
from orchestrator.defs.bootstrap.moneyflow_history_promote import promote_moneyflow_history_cohort
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
result = promote_moneyflow_history_cohort(
    staging_root=Path(DEFAULT_LAKE_STAGING_ROOT), lake_root=Path(DEFAULT_LAKE_ROOT),
    operation_id='history-sample-20261008', cutoff='2026-09-30',
    selected_dates=('2024-12-19', '2026-09-30'), apply=True,
)
print(json.dumps(result, ensure_ascii=False))
PY
```

完成验收须读回原cohort/progress、候选checkpoint与逐文件promotion receipt，核对实际Raw/Silver日期/schema/主键/逐字段摘要和源两轮证明：源/归一化/两层均29783行、拒绝0，14数据集日期/28文件全部完成，正式每文件hash与已校验候选一致；将实际网络/磁盘耗时、RSS/字节、冲突及恢复情况回填本节。隔离4.71MB仅是测试值，真实字节以receipt为准；不因此新增预算或宣称整个P3完成。

中断保留已闭合unit和已移入文件，阶段进度及预算来自原staging账本，不删目录/重导全量/改manifest。候选未完成时只用相同第一条命令续跑（冻结复核额外7请求消耗原余量）；进入提升后只能重复第二/三条命令接回实际文件，不再调用候选builder。进程退出保留原120秒步骤预扣；连接、12小时、32GiB、768MiB RSS等原限额耗尽时停止，不能换operation绕过。来源或正式文件发生变化先解释差异并复核，不能自动改批准hash。重跑同内容以原checkpoint核验，不重新读取业务COPY。维护窗口、权限和实际目标须执行前再次确认；本轮没有启动、停止或写入正式服务。

本轮关闭显式日期样本入口及只读/隔离准备，正式28文件样本待阶段批准。按 `lake_console/orchestrator/AGENTS.md` 的正式环境门禁第3条，正式staging和Lake变更仍需精确批准；本轮授权的开发、隔离测试及Prod只读已完成，不能用只读通过替代正式文件验收。P3-D正式盘测量/P3-E和整个P3继续未关闭；全历史及P4/P5后置。

## 26. 获准正式两日样本验收完成（2026-10-09，当前进度）

管理员明确要求“提交修改，然后批准按清单执行”。先将§25的三个历史模块、日期入口测试、报告与两份原设计七文件独立提交 `b4567b43`，未推送；随后执行§25.3原三条命令，不修改Python代码或扩大日期。operation仍为原清单的 `history-sample-20261008`，日期仍2024-12-19/2026-09-30，批准来源hash保持 `19358e2bc422173cc42e6119386124a629a25f943989e52bd01a6b927ccbdc98`，不会因执行跨日另建操作绕过预算。

执行前重新只读核对：正式Lake/staging已挂载，可读写/遍历且同设备16777244，空闲2,933,093,388,288字节；28目标及邻居Parquet不存在，无符号链接；本次operation/共享锁文件不存在，对应moneyflow writer进程匹配0。当前资产/job/sensor/catalog没有七表日更writer。随后按原helper取得共享namespace锁；没有自行停启服务。工作目录、两根正式路径与批准字段/日期不变，无Dagster instance/`DAGSTER_HOME`/事件/动态分区操作。

真实来源冻结两轮与批准hash一致后，在正式staging直接构建每日候选。14个日期unit全部verified，源/归一化/Raw/Silver数量分别与§25.2逐表逐日表一致，共29783行，reject0。14个元数据读取加28个业务COPY，共42个只读连接/168SQL、两轮业务输入59566行；所有请求均走原psql入口与批准投影，不是公开fixture。第二轮业务来源与第一轮生成的Raw逐字段集合差异0，Raw/Silver按原标准化合同对账通过。

预检完整28候选hash、14原checkpoint、目标权限/布局/冲突与同设备，全为可新增文件、复用/冲突0；只有全部通过后才APPLY。28文件逐一原子移入正式Raw/Silver并读回hash后落逐文件complete；14个数据集日期、29783行、14unit全部完成，stage为files_complete。使用同一APPLY命令重跑通过，原候选checkpoint字节/hash和正式文件hash不变，无新来源请求或业务文件写入。未人为取消正式执行；真实退出/取消恢复证据仍来自§24～25的隔离验收，不能宣称本次正式盘做过故障注入。

| 正式执行步骤 | 整个进程耗时 | 峰值RSS | 新增来源请求 |
| --- | --- | --- | --- |
| 真实冻结、构建、独立来源复核及候选检查 | 21.02秒 | 248.98MiB | 42 |
| 提升前完整预检 | 0.50秒 | 87.13MiB | 0 |
| 当前unit物理检查、fsync/原子提升/hash/checkpoint | 1.11秒 | 212.30MiB | 0 |
| 同内容幂等重跑 | 0.61秒 | 89.64MiB | 0 |

耗时/RSS由本机 `/usr/bin/time -l` 记录整个命令进程，包含启动/import/输出，并非单独的SQL或rename计时。正式28文件实际4,753,392字节，与隔离合成值的字节数不同，不能互借；全部属于Raw/Silver，没有Gold。最后一次共享账本累计步骤时间21.026秒、retained_bytes4,857,359、42/56个已用来源连接，原120秒步骤/12小时/32GiB/768MiB RSS/512MB单线程0spill门禁均未触发，未调整预算。

最终只读持有原writer锁的共享读锁，复用原 `audit_history_day` 对实际正式28文件做schema、日期、业务键唯一性、逐字段Raw/Silver一致性检查，并核验原checkpoint与两轮来源proof；临时DuckDB只用/private/tmp，不写正式目录。14个日期/29783行全部通过，正式文件hash/大小与已验证候选及promotion receipt一致，源差异0、拒绝0，无候选Parquet或.partial遗留。该只读物理对账0.349秒、峰值176.94MiB，未新增源查询，也未修改progress。早日DC板块实际行业86行；近期日行业496、概念504、地域31，合计1031。两日实际样本ts_code NULL均0，不把隔离NULL测试值当成Prod事实；历史允许NULL及名称身份合同不变。

正式执行前39项日期入口测试再次通过（6.86秒）、改动Ruff通过；代码/文档/804项联合与受保护测试日志hash均与上轮验收一致，提交后没有改代码，不重复整套测试冒充正式验收。CodeGraph sync/status保持根索引最新，本轮无API/CLI、配置、DatasetDefinition、Dagster definitions或依赖矩阵变更。实际来源SQL/证明、14原checkpoint、28候选/正式hash与大小、逐文件promotion事实、三条批准命令及重跑结果、权限/writer核验和真实计时均在[正式样本证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_formal_sample_evidence_20261009.json)。报告不含凭据或业务明细值；临时审计驱动在归档源码/hash后移除，正式控制/receipt/SQL与文件均保留。

P3-E精确正式样本退出条件已通过，P3-D早期低覆盖/近期完整日的真实磁盘链路测量已补齐。本次不关闭整个P3：原方案§24.2的P3-D整体成本汇总与P3-F分批全历史仍待推进。下一步以已有真实查询/大批次接收、隔离10万行转换和本次正式提升证据形成全历史请求/时间/空间成本、完整目标冲突清单及精确执行计划，再获批推进。21160938行/7804数据集日期/15608文件仍是未执行的全历史参考，不能把28文件样本计作全量；现有两个日期届时只允许同hash幂等复用，不删样本或覆盖差异。P4资产/catalog/job/sensor/事件和P5真实日更仍后置，files_complete不代表DG资产或分区ready。

## 27. 全历史成本汇总与 P3-F 准确执行清单（2026-10-09，当前进度）

### 27.1 本轮只读结果及执行硬口径

本轮按§26下一步完成准备，未执行正式全历史。七表截至2026-09-30的来源聚合重新读取两轮，14连接/56 SQL、69.65秒、95.58MiB，字段类型/日期/行数/键/DC分类均与原全历史合同一致。来源合同hash为`05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618`。各表范围与成本表见[原方案§32](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-onboarding-plan-v1.md:603)。完整来源SQL/证明、423个准确unit和15,608个目标、28既有文件hash、估算输入/公式、代码hash及下列全部命令保存在[本轮证据报告](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_full_history_plan_evidence_20261009.json)。

| 硬口径 | 代码点及当前验证 |
| --- | --- |
| 七表独立；源实际日期保留缺口 | metadata validator→`build_moneyflow_history_plan`→cohort `_manifest`；重新生成全部plan/hash与原冻结相同，423批次全部符合20日/100000行/不跨年 |
| 经审查合同才能读取业务 | builder `expected_cohort_hash`及持久`reviewed_cohort_hash`；39项入口验收包含错误hash和续跑绕过拒绝，本轮确认代码hash未变、14真实源SQL与当前builder逐项一致 |
| 每批两次源读＋全字段完整校验 | `_build_unit/receive_history_rows/source_difference`；既有真实日期最大批次及正式样本验收复用，拒绝与两轮差异不得非零 |
| 全部候选完成后才能提升 | promoter `_frozen`必须423个closed unit；尚无“构建一批立即提升”的执行能力，清单不假设有 |
| 全局冲突检查、逐文件原子提升/复用 | `_preflight/_closed_prefix/_promote_file`；28样本真实hash本轮一致，候选hash仍须执行时对比；不同内容拒绝，不覆盖 |
| 同操作预算与续跑 | `_operation/_Store/_Control`＋原逐文件intent/complete；既有804项联合覆盖取消/退出/续跑/幂等/状态写失败；本轮代码不变，不声称做过新的正式故障注入 |
| 聚合收尾，不能用events代表文件 | 每批物理校验＋最终全部文件hash/源proof/按年日期行数汇总；收尾聚合函数在28既有正式样本只读通过，错日期/错行数/漏文件反例被拒绝，正式全量仍待执行 |

CodeGraph explore已覆盖metadata/source/plan/cohort/receive/io/promote及测试；同名`_freeze`混入其他模块的边由实际moneyflow源码补查，不据此推断QTF依赖。根索引status最新。本轮只改原方案/本LLD及报告，没有代码、配置、依赖、API/CLI、DatasetDefinition或active asset/job/sensor改动。

### 27.2 执行量、资源和风险

全量21,160,938行、7,804数据集日期、423unit、15,608个两层文件；七表每层各自保存实际日期。28个样本来自两个已验收日期，每表4文件；当前全部hash/大小一致，目标清单外Parquet/符号链接/冲突0。预计新增21,131,155行/7,790数据集日期/15,580文件；复用28的条件是新候选hash仍与原正式文件一致，不能承诺在源金额修订后依然复用。

正常14元数据＋846业务COPY＝860 READ ONLY连接/3440 SQL，业务两次输入42,321,876行。每批独立短事务、ROLLBACK后结束，不使用全历史事务。每批的两次来源一致性不等于七表共同时间点快照；尾部计数刷新也不能证明同键资金值之后未修订。

参考总耗时2.46小时，计划范围2.5～7.5小时；两层Parquet约3.77GiB，工作空间约8.53GiB。原方案§32给出分项公式和实测出处，隔离fixture/合成值与真实Prod/正式SSD测量分开。120秒是单步骤门禁，9.29分钟预检估算是两次预检中多个步骤的总时间，不允许把一轮全范围布局循环放宽至分钟级；该布局循环完整候选规模的实耗尚未测得，触限即停。

固定874连接/3496 SQL、每步骤120秒、helper累计计费12h、32GiB总执行字节、首次64GiB空闲、RSS768MiB、接收32MiB/块64KiB、DuckDB512MB/1线程/0spill不变。首次源冻结仍在原候选build内完成；不要先单独freeze一次再build，浪费7次恢复余量。失败与恢复连接计入874；续跑的七表元数据复核另外7连接，原14余量最多容纳两轮完整复核且还要扣失败COPY，不能称无限重试。

正式两根挂载/权限已只读核对，同设备16777244，当时空闲约2.66TiB；拟操作目录不存在。执行前重新核对移动盘、目标文件、原writer及维护窗口。历史helper共用namespace writer锁，P4尚无七表active writer，但该锁不能保证任意外部进程不写同目录。没有自动停启服务或改调度。

### 27.3 待批准的准确命令与读写范围

工作目录固定`/Users/congming/github/goldenshare/lake_console/orchestrator`，使用现有`.venv/bin/python3 -B`，不安装/升级或同步依赖。helper不读写Dagster instance，无目标`DAGSTER_HOME`。operation为`history-full-20261009`，cutoff固定2026-09-30，默认全历史，不传`selected_dates`。写入仅该操作的正式staging及报告列出的Raw/Silver文件：

- 控制/候选：`/Volumes/datasource/data_lake_staging/moneyflow/history-full-20261009`；共享锁为其父目录`writer.lock`。
- Raw：`/Volumes/datasource/data_lake/raw/tushare/{dataset}/trade_date={date}/part-000.parquet`。
- Silver：`/Volumes/datasource/data_lake/silver/moneyflow/{dataset}/trade_date={date}/part-000.parquet`。
- 审计与进程计时证据：仅`/private/tmp`，归档报告不含业务明细值或凭据。

第一步：mount/权限/空间准入，通过原来源入口读取两轮元数据并比对已审计hash；一致后依次构建423批候选。每个unit独立持久化，内存与单批相关，不在进程内保留全历史业务数据。这里只保留有界CSV内存流，没有CSV落地、spool或按代码导出后再重分区：

```bash
.venv/bin/python3 -B - <<'PY'
import json
import os
import shutil
from pathlib import Path
from orchestrator.defs.bootstrap.moneyflow_history_cohort import build_moneyflow_history_cohort_candidates
from orchestrator.defs.bootstrap.moneyflow_history_source import PsqlMoneyflowHistorySource
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
lake, staging = Path(DEFAULT_LAKE_ROOT), Path(DEFAULT_LAKE_STAGING_ROOT)
assert lake.parent.is_mount() and lake.is_dir() and staging.is_dir()
assert lake.stat().st_dev == staging.stat().st_dev
assert all(os.access(p, os.R_OK | os.W_OK | os.X_OK) for p in (lake, staging))
assert shutil.disk_usage(staging).free >= 64 * 1024**3
result = build_moneyflow_history_cohort_candidates(
    staging_root=staging, operation_id='history-full-20261009', cutoff='2026-09-30',
    expected_cohort_hash='05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618',
    source=PsqlMoneyflowHistorySource(),
)
print(json.dumps(result, ensure_ascii=False))
PY
```

第二步：全部423个unit候选verified后，统一核验原checkpoint/候选hash和全部实际目标，确认新增15,580、同内容28、冲突0。`apply=False`会在正式staging写promotion合同和progress，因此它属于待批准正式步骤；源请求0：

```bash
.venv/bin/python3 -B - <<'PY'
import json
from pathlib import Path
from orchestrator.defs.bootstrap.moneyflow_history_promote import promote_moneyflow_history_cohort
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
result = promote_moneyflow_history_cohort(
    staging_root=Path(DEFAULT_LAKE_STAGING_ROOT), lake_root=Path(DEFAULT_LAKE_ROOT),
    operation_id='history-full-20261009', cutoff='2026-09-30',
    apply=False,
)
print(json.dumps(result, ensure_ascii=False))
PY
```

第三步：第二步无差异、精确范围不变才APPLY。APPLY仍先做完整预检，再以原当前unit物理校验和逐文件intent/同设备`os.replace`/读回hash/complete推进。不同内容停止，不覆盖、重编码、删除、备份或调用Kopia；源请求0：

```bash
.venv/bin/python3 -B - <<'PY'
import json
from pathlib import Path
from orchestrator.defs.bootstrap.moneyflow_history_promote import promote_moneyflow_history_cohort
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
result = promote_moneyflow_history_cohort(
    staging_root=Path(DEFAULT_LAKE_STAGING_ROOT), lake_root=Path(DEFAULT_LAKE_ROOT),
    operation_id='history-full-20261009', cutoff='2026-09-30',
    apply=True,
)
print(json.dumps(result, ensure_ascii=False))
PY
```

运行时按unit/逐文件读取原`progress.json`，记录stage、dataset、current_unit/file、completed/promoted/total、percentage、last_updated、连接和计费/字节；helper有步骤内更新时间，ETA仍“暂无法估算”。工具进程计时分别留存`/usr/bin/time -l`输出，不能把估算冒充实耗；shell包装仅将上述原命令的stdout/stderr写到/private/tmp，不改变helper参数、预算或范围。无需安装服务、增加自动化或初始化instance。

### 27.4 只读收尾、续跑和退出条件

第四步只读核验精确文件集、423个原checkpoint、两轮来源date/scope/row证明及逐文件promotion receipt；实际正式hash必须等于已通过schema、日期、主键和逐字段一致性的候选hash。接着按38个“数据集＋年份”及Raw/Silver共76组执行日期/行数汇总，严格区分Raw的YYYYMMDD与Silver的DATE，按实际filename与expected date/count对齐。只扫日期/数量，schema/key/金额一致性依据此前当前unit完整校验加实际hash未变，不重新逐日扫描全部字段。

准确只读Python命令完整正文及SHA256已归档报告`execution.commands.final_readonly_audit`，运行入口仍上述工作目录/`.venv/bin/python3 -B`，临时DuckDB仅/private/tmp、512MB/1线程/0spill；每unit hash检查与每年度聚合分别≤120秒、RSS≤768MiB。结果写`/private/tmp/moneyflow-full-20261009-final-audit.json`，不修改原控制文件。该命令正文目前只做AST核验；其中实际aggregate函数/SQL已在既有28正式文件进行正向及三项反例只读核验，整个全量命令未执行。

退出要求：每层21,160,938行，7,804数据集日期/423units/15,608文件全部完成，新增15,580/复用28；来源/归一化/两层数量一致、reject和两轮逐字段差异0；checkpoint不变、无计划外文件/.partial；连接/时间/空间/RSS实耗在原门禁内。`reuse`保留28个同hash候选在staging是当前代码行为，不能要求staging零Parquet或自动删掉；`move`的候选必须已移走。新的全量实际receipt/计时/聚合证据通过后才关闭P3-F和整个P3；P4/P5单独推进。

候选阶段中断，只重复第一条原命令，复核元数据及已闭合前缀，再从未完成unit继续；相同operation/cutoff/hash/日期意图/预算不得换。进程退出保留步骤120秒预扣；失败请求也计数。开始promotion后，只重复第二/三条命令，接回已移入文件与intent，禁止调用builder重建移走的候选。来源/目标变化或预算耗尽停止后先核清原因，不改hash、reset账本、清目录或创建新操作绕过。最终只读审计失败只重跑审计，保留已完成正式文件；审计输出已存在时使用独立临时证据文件名，不覆盖原证据或业务文件。

本轮只读准备完成，P3-D关闭，P3-F待精确范围批准。依据[orchestrator AGENTS正式执行门禁第3条](/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md:68)“已有批准只覆盖当时的精确范围”，§25.3两日批准不包含本节全量正式staging/15,580新增文件及28复用动作；批准后按上述清单执行，不扩展到DG分区、event、资产登记、sensor/job或日更。

## 28. P3-F 全历史实际执行与验收（2026-10-09，当前进度）

### 28.1 批准范围与执行链

管理员明确回复“继续推进，批准”，批准§27全量清单。原四条命令从准备报告逐字提取并保存SHA256，执行顺序为候选构建→独立全局预检→APPLY内部再次全局预检及逐文件提升→最终只读验收；四条原命令均成功退出。当前分支`dev-interface`及十个历史模块hash在各阶段核对不变。本节更新§27的待执行状态，不替换原命令、拒绝与恢复合同。

执行前15,608个目标与28个原样本指纹重核通过，未知文件/冲突/符号链接0、历史writer进程匹配0；正式Lake/staging挂载、可读写遍历及同设备16777244核验通过，空闲2,933,086,965,760字节。只读预查持原writer共享锁，实际helper持独占锁；不启停服务，也不声称锁能约束任意外部writer。

操作始终为`history-full-20261009`，cutoff2026-09-30，完整合同hash`05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618`。实际14次来源元数据证明与批准manifest完全一致；随后423个原日期unit各做两轮业务COPY，接收、归一化、候选schema/key/日期/逐字段及两轮证明完整校验，全部verified后才提升。来源SQL逐条按当前白名单builder重生成一致；860个连接均READ ONLY，3,440 SQL且ROLLBACK，无Prod写入。没有重试或拒绝；两轮业务字段差异0。

### 28.2 逐表实际结果

| 独立数据集 | 源/归一化/每层行数 | 实际日期 | unit | 正式文件 | 新增 | 同hash复用 |
| --- | --- | --- | --- | --- | --- | --- |
| moneyflow | 14,089,300 | 4,067 | 217 | 8,134 | 8,130 | 4 |
| moneyflow_cnt_ths | 192,009 | 495 | 26 | 990 | 986 | 4 |
| moneyflow_dc | 4,278,673 | 739 | 46 | 1,478 | 1,474 | 4 |
| moneyflow_ind_dc | 364,012 | 739 | 40 | 1,478 | 1,474 | 4 |
| moneyflow_ind_ths | 44,460 | 494 | 26 | 988 | 984 | 4 |
| moneyflow_mkt_dc | 839 | 839 | 44 | 1,678 | 1,674 | 4 |
| moneyflow_ths | 2,191,645 | 431 | 24 | 862 | 858 | 4 |
| 合计 | 21,160,938 | 7,804 | 423 | 15,608 | 15,580 | 28 |

每个数据集仍独立保存来源、计划、checkpoint及Raw/Silver；仅writer和预算共用。日期数是数据集日期之和，七表末日均2026-09-30；源缺口及历史DC分类保留，没有BIYING、证券池过滤、融合或计算补齐。两轮业务输入42,321,876行；最终每层21,160,938行，不把两轮行数相加作为业务数量。

全部候选完成后全范围预检无冲突；15,580文件经同文件系统原子移动及读回hash完成，28个已有文件因新候选hash完全相同而复用。423个原checkpoint字节hash及28个原正式样本hash前后不变。正式两层Parquet3,724,770,049字节（3.469GiB）；28个reuse候选仍留原staging，其他候选Parquet/.partial/计划外文件0。正式文件没有覆盖、删除、备份或重新编码，不调用Kopia；保留原控制与候选证据用于恢复/审计。

### 28.3 最终只读物理闭合

最终命令持共享只读writer锁，确认完整目标集、每个实际文件SHA256/大小、423个原checkpoint、两轮来源date/scope/row证明、promotion合同/逐文件complete receipt和原progress一致。按38组数据集年份、两层合计76组查询实际文件名/日期/行数；Raw严格解析YYYYMMDD、Silver使用DATE，并设置`hive_partitioning=false`，全部日期计数与批准范围相符。审计期间原cohort、progress、promotion合同及checkpoint不变。

汇总只投影日期和数量，字段一致性沿用每批完整校验及正式文件hash连续性；没有7,804次重复深扫，没有新增来源查询、正式文件/控制写入或Dagster访问。全量原四条命令本次已经实际执行，不再只引用AST或两日样本。验收结果写原`/private/tmp/moneyflow-full-20261009-final-audit.json`并归档执行报告。来源逐批两轮一致不等于所有日期处于同一数据库快照，也不证明源端未来不修订。

### 28.4 实耗与原预算

| 原命令阶段 | 完整进程秒数 | 峰值RSS MiB |
| --- | --- | --- |
| 构建 | 4,240.39 | 697.16 |
| 独立预检 | 11.62 | 137.59 |
| APPLY | 122.21 | 428.55 |
| 最终只读审计 | 16.86 | 503.81 |

以上`/usr/bin/time -l`包含启动/import/输出，合计4,391.08秒（73.18分钟），不含命令间的核对与等待。helper原账本计费4,356.21秒；实际保留执行字节3,731,024,757。连接860/874、SQL3,440/3,496、账本计费≤12小时、执行空间≤32GiB、首次空闲≥64GiB和RSS≤768MiB全部通过；32MiB接收/64KiB流块、DuckDB512MB/单线程/0 spill和单步骤120秒合同未改变。APPLY完整进程122.21秒覆盖多个步骤，不是单步骤超限；实际峰值697.16MiB高于隔离466.09MiB代理，仍在原门禁内。§27保守估算保留为执行前依据，不拿本次实耗承诺未来SLA。

### 28.5 收尾、证据与后置工作

执行意图、四条原命令/hash、实际SQL、全部原checkpoint与两轮证明、15,608文件hash、76组汇总、持续进度及完整计时归档[本轮执行报告](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_full_history_execution_evidence_20261009.json)，原方案§33同步。临时审计driver归档源码/hash后清理，不删除批准命令、日志、报告或正式staging业务/恢复证据。report按精确路径到数据集的批准清单分组，不用共享Silver目录中的`moneyflow`字符串推断身份。

当前原代码hash与39/804项已验收测试一致，本轮未重跑这些测试。没有正式故障注入或全量APPLY重放；取消、真实退出、续跑与幂等证据仍分别来自此前隔离及两日正式样本，不能冒充本次全量故障验收。CodeGraph explore与直接源码补核验覆盖历史来源/候选/提升链；无代码、配置、API/CLI、DatasetDefinition、active Dagster定义或依赖矩阵变更，文档/证据校验另记报告。

**P3-F及P3历史物理文件阶段关闭，P4/P5尚未执行。** 本轮Prod/Gold写入及DG instance/分区/event/job/sensor操作0，没有登记runless历史事件或启动自动化。下一步按原P4接入七个独立资产、catalog、job、sensor及历史事件；P5验证DG直连Tushare日更和22:00分区登记。修改未提交、未推送，本次批准只覆盖原四条全量命令与物理收尾。

## 29. P4 首个接入：大盘资金流资产与分区检查（2026-10-09）

管理员要求“推进P4”。沿用§6逐数据集实施卡、原方案§13的独立阶段验收及orchestrator逐个迁移规则，本轮先接入`moneyflow_mkt_dc`的资产/check/job/catalog；sensor及历史注册/事件下一步推进，整个P4不提前关闭。下列为编码前对账口径，不是正式资源执行结果。

### 29.1 本轮硬口径与落点

| 硬口径 | 实现点 | 正反验收 |
| --- | --- | --- |
| 独立Raw/Silver及专属分区，不混入另六源 | assets/moneyflow_mkt_dc.py、partitions.py、catalog/lake_assets.py、name_mapping.py | 精确2资产/2check/2job/1分区；无共享全局分区、额外源或其他资产selection |
| 15字段、金额/NULL保真，Silver只改日期 | 复用§6 schema及checks/moneyflow.py；新增checks/moneyflow_mkt_dc.py | 源/Raw/Silver均1行，负值/NULL保留；错日、类型、重复、金额差异拒绝 |
| 两轮完整来源稳定后才提升Raw | 原source_readiness/moneyflow.py及io/moneyflow_raw_writer.py→io/moneyflow_mkt_dc_update.py | 复用显式fields/date/分页/60秒/64次/300秒；空、不稳定、失败不写正式文件，不产生成功materialization |
| Silver只读同日已绿Raw，不重新拉源 | assets/moneyflow_mkt_dc.py、io/moneyflow_mkt_dc_update.py | 缺materialization/check、错误分区、失败check、实际Raw hash与materialization不符均拒绝；同日已绿正常转换 |
| 日更同值复用，源修订完整校验后逐文件更新 | io/moneyflow_mkt_dc_update.py | 数据相同不重写；变更仅本层文件原子替换；已有文件非法、目标在intent后变化、不同设备、symlink阻断；替换后退出可按原intent读回续跑 |
| 历史与日更共用原writer身份 | 将原私有锁实现抽至io/moneyflow_candidates.py，迁移全部历史调用与两项测试；锁文件仍moneyflow/writer.lock | 互斥和退出释放回归；不引入第二把锁、状态表、宽松配置或旧函数别名 |
| blocking check事件属于实际日期 | checks/moneyflow_mkt_dc.py显式asset和partitions_def | 隔离asset job产生的evaluation.partition及storage execution.partition均为请求日；注入错日/金额错误后仍执行原check，必须失败且归属正确日期 |
| job只选择本层资产和check | jobs/moneyflow_mkt_dc.py | Raw job只写Raw；Silver job只写Silver，不顺手更新Raw/calendar/basic；job没有源/SQL/writer业务逻辑 |
| definition与运行metadata分工，catalog只登记/对账 | 稳定schema/path/命名合同、统一metadata/tag builder及catalog | definition完整schema/path/source；运行URI/行数/实际hash/来源请求与receipt；业务资产/check/job不得依赖catalog生成或运行规划；治理测试反查registry全对账 |

最终名称沿用§6：`raw_tushare_moneyflow_mkt_dc`、`silver_moneyflow_mkt_dc`；check分别为`raw_tushare_moneyflow_mkt_dc_file_contract_check`、`silver_moneyflow_mkt_dc_standardization_check`；job分别为`raw_tushare_moneyflow_mkt_dc_update_job`、`silver_moneyflow_mkt_dc_update_job`；分区为`cn_a_moneyflow_mkt_dc_trade_days`。资产group=`moneyflow`、data_domain=`quote_data`，仅复用现有枚举。数据合同分别为`tushare_moneyflow_mkt_dc_raw_by_trade_date`、`standardized_moneyflow_mkt_dc_by_trade_date`，catalog声明历史只读Prod及runless能力，不表示正式事件已写。

### 29.2 安全、性能及配置审计

日更unit=1数据集×1日期×1层；Raw正常2次请求、每轮1行，沿用原64请求/300秒共享预算及至少60秒间隔。日期、fields、limit/offset均由原collector产生，不新增运营参数或修改TushareResource。没有对象池、分类展开或Prod日更查询。Raw候选最多source JSON/Raw/receipt，额外提升checkpoint；Silver只读本日Raw，独立run目录生成1候选与checkpoint。两层各1正式文件，现有单日公开样本约2.6KiB/层，含稳定间隔预计约1～5分钟，失败上限保持300秒；这不是网络SLA。DuckDB512MB/1线程/0spill、RSS768MiB沿用原合同；Python只编排与小量receipt/hash，大体计算使用原列式SQL。

正式路径仍为§6/paths.py，所有候选和控制文件在原正式staging的run目录。复用原namespace writer锁覆盖源采集、候选校验、目标重核及逐文件提升；锁竞争立即失败，不重新领取源请求。首写检查两根、挂载/权限/空闲及同设备；已有合法文件与候选业务字段相等时保留文件，否则保存旧hash及新hash intent，再核对旧hash、同设备os.replace、fsync和实际hash后登记complete。替换后complete写失败保留intent及正式文件，续跑只接受新hash；任何第三方变化拒绝，不覆盖非法旧文件、不清现场、不引入备份/Kopia。Raw更新和Silver更新独立原子，Silver不匹配当前Raw时check失败，不能声称两层一起原子。

Silver运行从本日Raw最近materialization及关联blocking check确认ready，另核对metadata中的实际文件hash和完整文件合同；日常只针对选中一天，不能用于全历史逐分区扫描。Silver标准化check重新校验Raw/Silver全字段一致，结果关联同分区Silver materialization。隔离检查最多2个文件/15列/各1行；暂不实现sensor热路径或全量event深扫。

无新增env、Settings、数据库或运营配置；路径由paths.py、运行预算由moneyflow.py、fields/schema由asset_column_schemas.py提供。新资产身份/分区/名称是definition合同，不是可调开关；全部消费者为本轮资产/check/job/catalog及既有治理测试，代码加载后生效。本轮所有运行仅临时Lake/staging、fake source/clock及隔离instance；正式Lake/Prod/DG读写为0，不reload正式code location、不启用sensor、不注册分区或补事件。

CodeGraph explore/impact覆盖候选writer、readiness、catalog及原writer锁调用方，并直接核验同名歧义边界；历史锁真实消费者只有单表candidate、cohort（promotion间接复用）及两项测试，本轮全量迁移，不保留旧私有别名。既有资源/Prod/API/CLI/DatasetDefinition与依赖矩阵不变。隔离job验收及defs静态验证使用现有.venv，不安装依赖；治理回归使用现有受保护启动器，精确增加新source发现清单，不放宽正式资源/网络保护。验证结果完成后回填本节。

### 29.3 实现与隔离验收结果

资产、check、job四个独立模块已实现并由现行defs loader发现；catalog新增两个事实卡/两个物理分区model，name mapping新增中文名，partitions新增一个专属分区定义。资产直接引用稳定schema/path/命名合同及统一metadata/tag builder；catalog只登记和治理对账，不生成资产或决定运行计划。两个check名字集中在原moneyflow合同，资产readiness、check decorator和catalog共用，未改变既有请求、字段和预算合同。历史私有锁已提取至io/moneyflow_candidates.py，全部真实消费者迁移，锁文件及行为不变；无旧别名、第二把锁、备份或恢复旧主链。

| 验证 | 实际结果及限制 |
| --- | --- |
| 资金流及历史最小回归 | 230项通过：候选/cohort/提升/显式日期及原大盘合同205项，加新资产25项；新资产最终再跑25项通过 |
| 分区job/check真实存储验收 | 临时SQLite instance及临时Lake/staging执行原Raw、Silver两个job。2026-09-30两项evaluation.partition与storage execution.partition均等于请求日且SUCCEEDED；错日/金额差异的原check均FAILED，并验证失败记录的存储partition仍为请求日 |
| 来源/归一化/写入 | fake source两轮各1行/各1请求，Raw=1、Silver=1，成功样本reject=0；15字段、Raw日期字符串/Silver DATE、NULL及负金额-123.4567保真。实际文件2562/2537字节；两个job含框架开销约1.00秒，60秒稳定等待使用虚拟时钟，不是实网吞吐或盘后SLA |
| 安全及恢复 | 同值保留mtime、源修订分层替换、非法旧文件/外部目标变化/文件symlink阻断；原writer互斥；intent后取消留下候选及checkpoint、按原操作续跑不请求源；Raw/Silver替换后退出、complete未写时读回续跑不重新采集/编码 |
| catalog治理 | 受保护runner两批共12项/480 subtests通过，身份、字段schema、来源文档、path、tags、blocking check规格一致；每批原生隔离自检及7个负例通过 |
| 完整definitions | 现有Dagster1.13.18环境执行dg check defs --use-active-venv --no-check-yaml成功；使用/private/tmp隔离DAGSTER_HOME并关闭telemetry，UV离线/禁止同步，不reload正式code location |
| 全局静态门禁 | 原受保护runner首批7通过/1失败后停止，后续未执行。失败为test_dc_board_m3_writers_keep_raw_only_bounded_boundary：当前另一项东财板块改动的assets/dc_board.py不满足“包含execute_bounded_pages字面量”的原断言（test_run_contract_static_gates.py:567）。未修改东财业务代码、跳过失败或放宽门禁，不能声称全局绿 |

损坏文件检查的隔离注入使用同asset key、同partition definition的测试asset stub保留坏文件，再执行原blocking check；不替代原Raw/Silver正常job验收，不在正式代码增加checks-only兜底。当前SDK仅选择check的job不能按这套分区方式执行，本轮没有提供该生产入口。分区check在当前SDK属于preview能力，未来升级须重新验证evaluation和storage partition，不能只看passed。

受保护runner精确补四个新资金流模块，以及当前工作区东财定义已import的dc_board_quote_coverage.py/dc_board_source_freeze.py只读源码依赖；原正式资源/网络保护未放宽。首次隔离instance的telemetry默认写用户目录失败，已改测试instance为telemetry=false；最终验收全部使用临时目录。既有P3报告仍保留原接受时的代码hash，本轮锁提取后的回归不冒充重新验收15,608个正式文件。Ruff、文档完整性及git diff --check通过；CodeGraph同步后状态为up to date。无子系统边界/依赖矩阵变更，没有修改架构快照。

命令、日志/hash、最终代码hash、请求参数、source receipt、实际check存储归属、临时文件hash及尺寸已归档[首个P4接入证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p4_mkt_dc_evidence_20261009.json)。本轮未调用Tushare实网或Prod，正式Lake/DG访问和写入均0；未提交、未推送。

本轮交付仅为首个数据集的资产/check/job/catalog代码及隔离验收，**整个P4保持未完成**。下一步先完成本表默认STOPPED的22:00分区注册及Raw/Silver更新sensor、有界cursor/readiness、历史event dry-run；正式definitions准入、分区/event写入仍须清单、独立批准与读回验收，不能在全局门禁未闭合时直接发布。随后按同样流程逐个接入其余六表，P5再做真实新增日期的Tushare采集和观察。

## 30. P4 大盘sensor与历史event预演设计（2026-10-09，编码前）

管理员要求提交并继续下一步。上一轮资产/check/job/catalog及P3报告已提交4e5f2f47。本轮落实原§2/§4：仅本表三个STOPPED sensor、窗口readiness和只读历史event预演，不启动自动化、不执行正式job/分区/event写入、不切换其他六表。原源参数、15字段、日期及文件合同不变。编码前已明确性能表和正反测试要求，最终按该清单验收。

### 30.1 硬口径与实现映射

| 硬口径 | 实现点 | 验收 |
| --- | --- | --- |
| 上海22:00登记当日，日历权威，登记不拉源/提交job | sensors/moneyflow_mkt_dc_sensor.py注册器复用有same_day_register_start的现行helper；当天优先，另一位置补最早遗漏 | 21:59/22:00、SSE节假日、漏日与当日同时存在、登记结果不含run，三个sensor默认STOPPED |
| 最近10个expected日、每tick最多1run、不越过未注册/非法文件与check问题 | 同模块更新器及asset_guards/moneyflow_mkt_dc_readiness.py | 当日优先、缺partition、错日旧check/新mat、目标实际hash改变、100条记录截断均fail closed；10日之外明确离线处理 |
| 历史C_d边界不漂移、不自动回抓Prod历史缺口 | 更新器自动日期下限固定2026-10-01，来自已批准C_d=2026-09-30；注册器仍从本表2023-04-17开始 | 历史缺事件不能触发Tushare回抓；P5需先核对(C_d,切换日]差集，超过10日不得由热窗口吞掉 |
| Raw有限重试与每日复核，schema/精度/预算错误不能盲试 | 原exception补retryable字段（默认false）；mkt collector用现有failed_pages.retryable分类；Raw asset写结构化STEP_FAILURE metadata；sensor只读取字段 | 空源/不稳定/已识别临时网络可重试，认证/schema/预算/文件问题停止；每业务日每观察自然日最多6attempt；完整采集仍只在job，sensor不请求源 |
| Silver只消费当前已绿Raw修订，不拉源 | readiness同时核对Raw/Silver；Silver run key使用Raw实际file hash，不使用storage id | Raw hash改变且自身已绿、Silver旧check仍绿且旧file hash未变时可标准化新Raw；失败check/文件变化不自动修复；同hash不重复 |
| 幂等、互斥及小游标 | 复用run key/RunRequest/cursor/tag builders；两层共用原writer及既定moneyflow_tushare_writer池名 | active run阻断；新run key含日期/自然日/attempt或Raw hash，禁止event storage id；cursor最多10日的小attempt/verified_on状态，目标2KiB、硬8KiB |
| 事件预演仅认可P3已校验并提升的文件，不制造ready | bootstrap/moneyflow_mkt_dc_event_preview.py只读原cohort/checkpoint/promotion及实际文件；最近20日完整check，分批100日期 | hash/行数/日期/来源证明/提升状态变动即拒绝；统计缺注册、materialization差集和最近40个check，无report_runless_asset_event/分区写入/APPLY入口 |

readiness不逐日查事件：每资产一次partition-filtered materialization（最多100条），一次精确check key执行历史（最多100条；当前SDK仅支持单partition filter，批量路径以check key过滤并严格匹配记录partition及最近mat identity）。每层仅1个blocking check，最多两层/4次读取；记录不足以证明最近identity时阻断，不扩大扫描。实际文件hash与该mat hash相等才继承完整check语义；Silver还必须记录并匹配本日Raw hash。不新增另一份ready事实源或状态manifest。

### 30.2 配置与性能审计

所有值集中在现有run_contracts/moneyflow.py，持久化为源码，无env/Settings/数据库开关，代码加载生效，sensor定义/诊断cursor可见：REGISTER_START=time(22,0)、SENSOR_INTERVAL=600、SENSOR_WINDOW=10、AUTO_ATTEMPTS=6、EVENT_RECORD_LIMIT=100、SENSOR_START=2026-10-01、MKT_HISTORY_START=2023-04-17、RECENT_CHECK_DAYS=20、EVENT_DATE_BATCH=100、WRITER_POOL=moneyflow_tushare_writer、READINESS_FILE_MAX_BYTES=65536。新增文件hash门禁在读文件前检查stat，超过64KiB只阻断自动判断，不重写文件；两层10日最多hash 1.25MiB。这些落实原设计，不修改原source/历史预算；池容量1仅是启用前正式instance配置检查，本轮不配置池或启用。全部消费者：本表三个sensor、readiness、事件预演、两层资产及测试；无可编辑宽松开关。

| 路径 | 读写及预算 | 验收/拒绝 |
| --- | --- | --- |
| 注册tick | 原helper最多3次日历SQL、1个SSE日历文件，读取专属注册集合；本表自起点最多20000日期；仅返回≤2个注册请求 | 22:00以后当日优先，超过日期/游标预算拒绝，不拉源，不实际写instance |
| 更新tick | 22:00前直接返回，不做事件/Parquet重读；窗口≤10日；本表1次SSE日期SQL（DESC LIMIT 10，避免通用helper先全量fetchall）；≤2次active查询、1次注册集合、最多4次readiness读取及1次run读取/1条失败event | 每次返回≤1run，最多20个约2.6KiB文件hash、0数据SQL/0spill；最多100 mat/check/run记录每查询，饱和且尚未覆盖所需最新日期，或证据不足时停止。临时样本验证查询次数、文件数和耗时，不把fake时钟当网络SLA |
| 历史预演 | 仅本表839日期/1678正式文件；原44个date unit证明；逐文件hash，最近20日/40文件完整字段check；其他日期沿用P3 hash连续性。metadata按≤100日期批读取，原check key各≤100记录，无逐日期event查询 | 不读Prod/Tushare，不改控制/文件，不写事件；读前后control hash一致，缺失/变动/截断停止。预估文件仅约4.2MiB，局部DuckDB512MB/1线程/0spill、RSS768MiB、步骤120秒；实际另测，历史总event差集只是计划数量 |

重试以同业务日、观察日的六个标准RunKey和持久化运行记录为准，游标不负责累计上限；未创建的请求重复返回同一key，不消耗下一次尝试。Dagster为失败资产自动留下未执行check记录时，不将它冒充实际check失败；只有无mat、无check evaluation、无正式文件才可进入源错误重试判断。

CodeGraph explore覆盖注册helper、cursor/run key、calendar及readiness调用链；impact对exception的边少于真实消费者，已补AST全量调用审计，现有构造均只有一个reason参数。新增retryable默认false保持既有str/异常类型/参数语义，只有mkt来源路径显式标记可重试；不修改其他六源。新sensor文件遵守*_sensor.py命名。按本表运行记录的只读partition tag过滤，新增此文件到现有RunsFilter(tags=...)的精确读取许可；RunRequest/run_tags写入规则不放宽。新sensor身份须加入原static gate精确登记清单和受保护runner的精确源码清单，不跳过失败；既有东财门禁问题保留独立处理。正式只读预演若需要访问本机DG服务，使用规定权限与只读持续授权，不借此初始化instance、reload或写schema。隔离测试先完成。


### 30.3 实际实现、验证和未执行项

三项sensor、批量readiness和只读事件预演已落地；schema、源参数及其他六表合同未修改。Raw资产将原MoneyflowContractError的明确retryable属性保存为Failure metadata，不通过错误文字猜测；该属性默认false，其他消费者保持原异常字符串/类型语义。游标不能放大重试次数，未创建的请求重放同key，持久化六次RunKey耗尽后停止。原最新绿色check仍须目标identity/hash一致；失败资产导致的未执行check不会冒充真实FAILED evaluation。

新增测试test_moneyflow_mkt_dc_sensors.py和test_moneyflow_mkt_dc_event_preview.py：真实隔离partitioned job/check存储、时间/假日/当日优先、六次持久化尝试及cursor丢失、源错误分类、文件hash预算、旧check/新mat、历史proof变更与native runless事件复用/错误target等正反样本。首次23项和全资金流837项通过，追加五种已有事件样本及unit symlink读取前拒绝后，事件模块最终11项通过；治理12项/480 subtests和完整静态门禁113项通过，未跳过此前东财失败。实际shared defs CLI加载及CodeGraph同步完成。

正式只读预演覆盖原cohort hash 05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618，本表839日期/839行、44 unit、1678文件，hash总4,362,800字节；最近20日执行100条字段/日期/标准化SQL，40文件通过，90个控制文件前后不变，21次metadata查询，约1秒完成。正式差集839分区、1678 mat、最近40 check，当前正式写入0。实际结果与最终源码/日志hash归档[本轮证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p4_mkt_dc_sensor_event_preview_evidence_20261009.json)。最近20日按本表实际来源日期取，不制造历史空日。

CodeGraph explore用于注册/calendar/cursor/run-key/readiness入口和调用链，impact用于MoneyflowContractError；后者索引边不完整，补AST构造审计并实测全资金流。无需人工确认新的主体边界；正式池容量、definitions准入和事件写入的业务授权仍是执行前条件。下一步事件执行器的取消/退出/续跑/幂等及正式精确清单尚未实现；没有新增隐式APPLY、job或sensor启用入口。

## 31. P4 大盘历史分区与事件登记执行器（2026-10-09，编码前）

管理员批准提交并继续§30的下一步，上一轮已提交fe3510e2。本轮仅实现moneyflow_mkt_dc的可恢复事件登记，使用隔离instance验收；正式分区、event、pool/sensor/job写入仍等待本轮准确清单批准。新入口不加入自动Definitions，不改变既有job/sensor/API/CLI，不重写任何Parquet。

### 31.1 硬口径、实现点及正反验收

| 硬口径 | 实现点 | 验收 |
| --- | --- | --- |
| 只认原P3已闭合的日期和文件 | 原event_preview提取共享只读physical proof与原生event state；新events helper冻结cohort/control/file hash、路径、所选日期和目标instance identity | 保持旧preview返回合同；拒绝缺文件、symlink、错误cohort/checkpoint/promotion、范围外日期、错误实例或计划hash。只允许选择原实际来源日期，不登记或绿化源缺口 |
| 执行前先冻结完整计划，再按登记→物化→最近检查→读回顺序 | 新bootstrap/moneyflow_mkt_dc_events.py；显式apply，默认只读；staging/moneyflow/<原operation>/events/<plan_hash>下plan与checkpoint | dry-run不建目录/锁/控制文件，不写instance；样本选择最近两日，全量仍是839日期/1678 mat/40 check，不创建run/backfill |
| 计划身份不包含event storage id | 日期、源cohort、文件和control hash、instance连接身份构成plan hash；check在执行时使用原生最新mat的storage_id/run_id/timestamp | 写入后退出、游标或checkpoint滞后，依靠原生事件重新对账；正确已有mat/check复用，冲突/FAILED/错误target拒绝，不删除或覆盖事件 |
| 物化元数据及check语义统一 | 复用materialization/check builders和既有字段schema；mat带实际file_sha256、Silver raw_sha256、原checkpoint/cohort与plan hash；仅最近20个原实际日期写blocking check | 旧日期只有mat，不伪造check；最近日期执行同一个Raw/Silver字段标准化helper。native runless check必须有正确partition和mat target，读回后可被现有batch readiness识别 |
| 每个已提交事件保留、续跑幂等、取消及时 | staging checkpoint逐事件原子保存并fsync，唯一moneyflow namespace writer lock；每次API前后取消检查、每批实际读回；原生事件是完成事实，checkpoint只记进度 | 中途取消/实际子进程退出、事件成功后checkpoint失败、重复执行、缺失/过大/坏checkpoint、锁冲突、文件或实例变化；已提交事实不回滚。进度单调，包含阶段/当前日/层/完成量/总量/%/更新时间/耗时 |
| 唯一writer和维护窗口 | 与原日更/历史共用moneyflow/writer.lock；执行前及批次前查两个job active状态 | active run拒绝，其他调用抢锁拒绝；正式执行前保证三个sensor停止、人工维护窗口独占。不保证任意外部事件写入的事务原子性，冲突读回即停止，不做数据库删事件回滚 |

instance identity只读取SDK现有storage配置/路径，不调用get_run_storage_id：当前实现可能在缺UUID时自动插入。正式只允许已存在的本机goldenshare_dagster PostgreSQL、关闭自动建表的原适配器；连接身份包含driver/host/port/database/user，不包含密码或read-only会话options。隔离测试绑定实际临时SQLite数据库路径；在计划和执行之间换instance即拒绝。

### 31.2 配置、容量和性能门禁

新拒绝预算集中追加原run_contracts/moneyflow.py：EVENT_MAX_WRITES=4096（分区键+mat+check工作项上限），EVENT_MAX_SECONDS=600（单次APPLY上限），EVENT_MAX_METADATA_READS=256（单次原生查询API调用上限）；源码持久化、代码加载生效，无env/Settings/数据库开关，消费者只有event helper及对应测试；通过dry-run结果、checkpoint和CLI进度可见。其余复用DATE_BATCH=100、RECORD_LIMIT=100、RECENT_CHECK_DAYS=20、unit120秒、DuckDB512MB/1线程/0spill、RSS768MiB及原路径/锁。全部拒绝上限在冻结计划中记录，不能由运营随意放宽。

| 路径 | 真实规模与读写预算 | 验收/拒绝 |
| --- | --- | --- |
| 计划/预检 | 全历史839日期/44 proof unit/1678文件，hash约4.36MB；最近20日40文件、100条字段SQL；无Prod/Tushare请求/分页、无数据写入 | 复用§30已实测约1秒的proof，计划写前完整冻结；最多20000历史日期，所选工作项不得超过4096。计划JSON≤32MiB，checkpoint≤256KiB；目标或hash变化立即拒绝 |
| 登记/物化 | ≤100日期一批；本表9批登记、1678个原生mat事件，每次调用独立持久化 | 正式预期839个新partition键、1678 mat；不包全历史数据库事务，每事件后保存progress、批后读回。取消/进程退出保留已提交事件，读实际事件补齐，不能按checkpoint盲跳 |
| 最近检查 | 仅原最近20日期，40个原生blocking check；每个check绑定执行时读取的mat | 一批≤100日期；每check之前同语义审计并检查对应Raw/Silver实际hash；已有FAILED/check target变化或元数据冲突停止，不重写文件 |
| 事件metadata | 单次查询最多100记录，按asset+日期批，check按精确key；不逐日期查历史 | ≤256个metadata读取API；截断且不能覆盖所需日期时拒绝；native写API的内部SQL另计，不把API调用数当数据库SQL数。总工作项2557，正常物化/check写1718次+分区批9次 |
| 可恢复与观察 | 原staging内原子替换plan/checkpoint，逐事件保存；锁与文件hash共同保证范围 | 初步预算≤10分钟、单批≤120秒；实测隔离native事件吞吐、控制文件fsync、查询次数/耗时/内存和代表性取消—续跑—读回。PG真实写入延迟留给获批正式样本，不把SQLite值冒充PG SLA |

官方runless入口及check文档已核对：[External assets instance API](https://dagster.io/docs/api/dagster/external-assets-instance-api)、[Partitioned asset checks](https://dagster.io/docs/guides/test/asset-checks)。本机SDK1.13.18的实际签名/原生存储行为仍作为实现与隔离验收依据，不使用最新版文档推断本机行为。CodeGraph覆盖原preview、writer锁、只读instance及其他数据集事件登记的调用链；读回/取消与锁语义以当前源码补核。原preview承载共享proof/state；新增event_plan冻结计划与实例身份，events负责登记和续跑，不建立新ready事实源。

### 31.3 实际验收（2026-10-10）

执行器已实现：默认只读，显式apply才登记；计划包含原cohort、90个控制文件hash、所选日期的Raw/Silver hash及实际存储身份。每次取得原共用writer后重新验计划，按≤100日期批处理；每个原生事件成功后原子保存checkpoint并fsync。取消或退出保留已提交事件；续跑重读原生事实，即使checkpoint缺失或比真实事件落后也不重复登记。坏hash、提前声称完成、非法阶段、过大文件或symlink checkpoint均拒绝。进度观察失败记录错误但不回滚事件；checkpoint保存失败停止领取新事件，后续重读恢复。

新执行器34个场景与旧preview/sensor/history promote65个场景最终联合回归99项通过，约81.41秒，日志见证据。原生临时instance验证真实子进程在事件提交后、checkpoint写入前os._exit(47)，重启补齐剩余三事件且复用原storage id；另有取消（包含最后一次读取期间取消）、checkpoint写失败、进度回调失败、错误实例/文件/控制/plan、active run/锁冲突、FAILED/stale check、事件截断、预算耗尽和范围外日期反例。首次两个反例测试用到了本机record不支持的namedtuple._replace，已改为实际构造函数；839日测试fixture的metadata也改为模拟真实源的≤64KiB流式分块，不放宽生产限制。跨上海午夜的联合回归发现原sensor测试使用固定NOW与实际日志时间，修正测试日志工厂为同一虚拟时间，18项sensor全部通过。上述修正只改测试，未跳过失败或改生产日期逻辑。

真实SQLite样本：101来源日期对应101键/202物化/40检查、343工作项，83次metadata读取、252次原子保存；同规模839来源日期对应839键/1678物化/40检查、2557工作项，229次读取、1749次原子保存，约8.6秒。最大日期批100；最近20日以外不写check。最终耗时、fsync累计/最慢值及进程peak RSS见本轮证据，不把本机SQLite速度当正式PG承诺。所有原P3控制文件、正式布局临时Parquet、来源请求次数前后保持不变；没有源站/Prod请求。旧日期子集重放不生成check。

受保护治理12项/480 subtests、完整静态门禁113项通过；runner只增加两个新资金流模块的精确只读路径。全defs隔离加载成功，无CLI/API/sensor行为变化，无主体边界或依赖矩阵变更。CodeGraph explore覆盖原proof/事件/锁/instance调用链，impact确认原preview没有其他业务调用方；索引未列出测试调用，已核对直接消费者并保持原11项测试返回合同。正式业务授权是唯一后续执行边界。

### 31.4 精确正式清单与批准后命令

2026-10-09 23:57（上海）首次正式只读，2026-10-10 00:06使用最终执行器复核，两个plan hash及差集不变：本机goldenshare_dagster PostgreSQL、关闭自动建表且默认只读。90个原控制证明未变；839来源日期为2023-04-17～2026-09-30。没有已有可复用分区或事件。两份JSON列全实际日期、1678文件hash及全部原证明，不以日期区间冒充完整日期清单：

| 清单 | 精确范围与待写量 | plan_hash |
| --- | --- | --- |
| [两日样本](../../reports/moneyflow_p4_mkt_dc_event_registration_sample_plan_20261010.json) | 2026-09-29、09-30；2分区键、4物化、4检查，总10工作项 | 90639d04bd102597671856d0d3d9584ca80cf5799d4d77b35190e5cd0c92e319 |
| [全量](../../reports/moneyflow_p4_mkt_dc_event_registration_full_plan_20261010.json) | 原839实际日期；839分区键、1678物化、40检查，总2557工作项 | e699ce04e04ed8e792a95ff72140251945aa282cda0b18ed25972517357ce92d |

两日预检7次metadata读取、约0.42秒；全量预检23次、约0.51秒（含两个active job查询）；整个计划生成加预检约2.04秒。plan JSON分别20956/389490字节（默认JSON编码口径；归档含缩进），低于32MiB。APPLY会在预检、取得writer及最终验收三次完整核对physical proof，最近检查阶段另外审计20日；全量单次预计229次metadata读取API，低于256上限，由839日隔离样本进一步验证。事件1718个，每事件独立提交，外加最多9次分区批登记；不包全历史事务。

**本次未执行以下写入命令。** 按方案§35.3，先批准两日样本并在维护窗口保证三个sensor停止、没有本表active job或其他人工writer；样本读回通过后再独立批准全量。全量计划包含已登记样本，执行时会实际复用，因此样本通过后剩余837键、1674物化、36检查。该清单不包含reload、池配置、启用sensor、正式job或其他六表。

在`lake_console/orchestrator`目录，先用同一文件执行只读预检，`daily_basic_event_instance()`不传writable；批准对应清单后，使用已有环境执行：

```bash
.venv/bin/python3 -B - <<'PY'
import json
from pathlib import Path
from orchestrator.defs.bootstrap.daily_basic_event_instance import daily_basic_event_instance
from orchestrator.defs.bootstrap.moneyflow_mkt_dc_events import report_market_moneyflow_history_events

# 第一阶段仅两日样本；全量须另行批准后改为full清单，并核对对应plan_hash。
plan = json.loads(Path('../reports/moneyflow_p4_mkt_dc_event_registration_sample_plan_20261010.json').read_text())
assert plan['plan_hash'] == '90639d04bd102597671856d0d3d9584ca80cf5799d4d77b35190e5cd0c92e319'
with daily_basic_event_instance(writable=True) as instance:
    result = report_market_moneyflow_history_events(
        instance=instance, plan=plan, apply=True,
        progress=lambda item: print(json.dumps(item, ensure_ascii=False), flush=True),
    )
print(json.dumps(result, ensure_ascii=False))
PY
```

执行后再次默认只读预检：样本差集应为0，两日两层readiness全绿且native check partition/target一致；全量结束后839键、1678 mat及40 checks差集为0。物理文件和90个原控制hash必须与清单相同。若预算、active run、身份或hash变化，停止并回报；取消用KeyboardInterrupt，已提交事件保留，以同一冻结清单续跑。checkpoint位于`/Volumes/datasource/data_lake_staging/moneyflow/history-full-20261009/events/<plan_hash>/checkpoint.json`，不能通过编辑它改变完成事实。

最终日志、源文件hash及实际值归档[登记执行器证据](../../reports/moneyflow_p4_mkt_dc_event_registration_evidence_20261010.json)。本次正式登记、reload、sensor启用及job执行均为0，P4仍未完成；下一步按上述两日清单批准后做正式样本。

## 32. P4 大盘历史事件正式两日样本验收（2026-10-10）

§31保留执行器交付时“尚未正式登记”的历史事实；本节为最新执行结果。管理员已明确批准上一轮提出的两日样本；原12文件提交为02fa9045，未推送。本轮目标只覆盖2026-09-29、09-30的2分区/4物化/4检查，未获得或执行全量批准。

### 32.1 执行入口、边界与恢复

工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，使用已有`.venv/bin/python3 -B`，目标instance home为`/Users/congming/.goldenshare/dagster_home`。按§31.4的冻结sample plan执行，plan hash为90639d04bd102597671856d0d3d9584ca80cf5799d4d77b35190e5cd0c92e319；本机goldenshare_dagster PG、should_autocreate_tables=False。执行前和后使用默认事务只读适配器，只有登记阶段显式writable=True。没有启动或升级数据库，没有改变连接配置。

临时审计/执行脚本为`/private/tmp/moneyflow-p4-mkt-dc-formal-sample-20261010.py`，具体操作：

```bash
# 执行前纯只读预检（已执行）
.venv/bin/python3 -B /private/tmp/moneyflow-p4-mkt-dc-formal-sample-20261010.py
# 精确两日登记及其后只读验收（已执行一次）
.venv/bin/python3 -B /private/tmp/moneyflow-p4-mkt-dc-formal-sample-20261010.py --apply
```

脚本只加载已提交清单，复用原helper，不改其行为或新增正式CLI。读取三个sensor的原生持久化状态时采用PostgresScheduleStorage、只读URL、关闭自动建表；扫描106条sensor记录，三项本表sensor无持久化状态，源码默认STOPPED，未发现启用状态。两项job的active查询通过，原namespace锁提供唯一writer。正式Lake/staging目录已存在、无root symlink、剩余空间约2.93TB；不写探测文件或创建移动盘根。

正式写入仅为2个cn_a_moneyflow_mkt_dc_trade_days动态分区、4条runless materialization、4条runless blocking evaluation，及staging内sample plan/checkpoint。登记不包全历史数据库事务；每事件后保存checkpoint并fsync。完整日志和脚本hash已归档；取消/失败保留已提交事件，按同一清单恢复，不能删除原生事件回滚。该一次性样本脚本要求初始差集2/4/4，因此样本完成后不得再次用其--apply；续跑/幂等使用§31.4的原helper入口，默认只读重放检查已通过。

### 32.2 实际结果及硬口径对账

| 硬口径 | 实际证据 |
| --- | --- |
| 批准范围不扩大 | 仅两日、2键/4物化/4检查，总10工作项，completed=10、stage=complete；无job/backfill/sensor/pool变更，无其他六表写入 |
| 有界成本与持续进度 | APPLY约1.77578秒，53个metadata读取API（不含维护检查、前后验收与写API内部SQL）；进度单调，checkpoint=complete/100%，没有触发600秒/批120秒/RSS768MiB/读取256次预算 |
| native identity正确 | 四个mat storage id为7438584～7438587；run_id均为空；四个check都是SUCCEEDED/passed/blocking，partition分别对应两日，target storage_id/run_id/timestamp逐项匹配；这些id仅作诊断，不放入plan hash或RunKey |
| 完成事实来自原生事件与物理文件 | 默认只读postflight差集0/0/0，Raw/Silver两日四项readiness全部ready；sample checkpoint仅提供进度，不替代完成判断 |
| 原物理证明不变 | 样本和原全量proof再核1678文件hash及90个原控制hash；与旧cohort/checkpoint/promotion一致，无Parquet改写或源端请求；历史缺口没有补事件或制造绿灯 |
| 维护状态不变 | 前、写前、后均只读检查sensor状态，无本表启用记录；没有reload、pool配置或job，代码/子系统依赖边界不变 |

完整结果、事件身份、checkpoint、原数据hash和准确日志见[两日正式验收报告](../../reports/moneyflow_p4_mkt_dc_event_registration_formal_sample_evidence_20261010.json)。之前22份moneyflow报告及两份冻结plan保持原字节，不将旧“正式写入0”的报告改成现在的结果。

### 32.3 下一阶段准确剩余清单

全量清单仍使用§31.4已提交的full plan，hash e699ce04e04ed8e792a95ff72140251945aa282cda0b18ed25972517357ce92d，不重新生成或排除样本日期；原生状态会实际复用样本。只读全量预检completed=10/2557，缺837键/1674物化/36检查，剩余2547工作项。核验所用23次读取API、约0.49秒，未执行全量写入。

下一步需独立批准full plan：scope仍仅moneyflow_mkt_dc原839来源日期，实际新增837分区及1710个事件，最近20日检查总量最终为40。准确入口沿用§31.4，将JSON路径换为`../reports/moneyflow_p4_mkt_dc_event_registration_full_plan_20261010.json`，核对上述full hash后显式apply=True；其余参数、目标、锁和拒绝预算不变。

正式两日样本约1.78秒不能作为全量时长保证；若按剩余工作项简单线性放大，约7.5分钟，仍只是粗估（样本包括固定预检/最终审计成本）。完整执行保持≤600秒、每批≤120秒、≤256次metadata读取，不达标停止，保留已登记事实续跑，不提高预算或重写文件。本轮只修改本方案、总方案和新增验收报告；P4整体未关闭、P5未执行。

## 33. P4 大盘全量历史事件正式执行与后验（2026-10-10）

本节回填原§31.4和§32.3全量清单获批后的实际执行，不改执行器、冻结计划或预算。管理员批准原文为“提交修改，然后批准按全量清单执行，继续推进”。样本收尾先提交c1058a05，实施代码仍为02fa9045已验收版本，七个登记相关源码/测试hash保持一致。CodeGraph explore确认executor→共享native state及instance适配器链路，直接代码核对维护状态查询和正式加载入口；本轮无contract消费者迁移或人工待确认的新依赖边界。

### 33.1 准确执行入口与范围

工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，仅使用现有`.venv/bin/python3 -B`，不安装依赖。只读预检后执行以下原helper薄driver，driver源码/hash及日志归档到本节报告。driver固定读取原全量JSON、校验原hash/839日/2557工作项，再调用§31的原生执行器，维护状态只读检查不做start/stop。

```bash
.venv/bin/python3 -B /private/tmp/moneyflow-p4-mkt-dc-formal-full-20261010.py
.venv/bin/python3 -B /private/tmp/moneyflow-p4-mkt-dc-formal-full-20261010.py --apply
```

默认命令只读；实际两条命令日志分别写入`/private/tmp/moneyflow-p4-mkt-dc-formal-full-preflight-20261010.log`和`/private/tmp/moneyflow-p4-mkt-dc-formal-full-apply-20261010.log`。薄driver的首次APPLY断言批准差集837/1674/36，不能将此首次命令用作任意恢复入口；如出现部分完成，恢复仍按§31使用同一冻结plan和原helper，重读原生事实，只补剩余。本次一次完成，没有实际取消、退出或再次APPLY；恢复与幂等故障注入沿用已记录的隔离验收，不冒充本次正式结果。

正式instance仍为`/Users/congming/.goldenshare/dagster_home`的本机PG goldenshare_dagster，存储关闭自动建表。读阶段PG事务默认只读，写阶段仅显式writable=True；telemetry关闭。目标仍为历史operation history-full-20261009，cutoff 2026-09-30，原cohort hash与文件证明不变。

唯一新增控制目录：

```text
/Volumes/datasource/data_lake_staging/moneyflow/history-full-20261009/events/e699ce04e04ed8e792a95ff72140251945aa282cda0b18ed25972517357ce92d/
  plan.json
  checkpoint.json
```

原样本目录/事件复用；不更改原90控制文件或1678正式Parquet，不把checkpoint当第二份完成事实源。未使用Kopia或旧Lake。

### 33.2 硬口径对账与实际成本

| 原硬口径 | 正式证明 |
| --- | --- |
| 只登记原实际来源日期 | 839日期仍为2023-04-17～2026-09-30；仅新增837键，原样本两键复用 |
| 物化指向已验收文件 | 新增1674条，两层总1678；每条partition及file hash匹配，Silver匹配同日Raw hash |
| 最近20实际来源日检查 | 新增36条，原4条复用；合计40 SUCCEEDED、passed、blocking，target storage_id/run_id/timestamp均正确 |
| 不以checkpoint跳过 | 全量native读回完成2557项；默认预演差集为0；原样本4个mat identity未变化 |
| 文件/控制不变 | 原90控制SHA与1678正式文件全部匹配冻结证明，文件写入0；最近20日两层正式SQL通过 |
| 有界API/时间 | APPLY30.140秒，helper metadata229次，原600秒/单批120秒/256次上限未触发；Native写API内部SQL及外围验收另计 |
| 原生持久化与进度 | 新增1710原生事件及837分区，2557/2557，checkpoint complete/100%，输出completed单调；已提交原生事实不依赖临时报告 |
| 当前可消费检查 | 最近20日按10日期一批运行原readiness，两层40项均ready；不逐日深扫839日、不补早期check |
| 业务边界 | Prod/Tushare请求0、Parquet写入0、reload/pool/sensor/job变更0、其他六表P4写入0 |

执行前staging空闲约2.93TB、两根已挂载且无根symlink。真实PG全量成本已落档，不再以样本线性外推7.5分钟作为结果；本次30秒仅为本次实际执行，不是通用SLA。本轮无代码修改，复核既有99项代码SHA及原25份报告/manifest，未重复运行或将此前测试冒充新测试。文档完整性和差异检查结果回填报告；无主体分层、依赖矩阵、DatasetDefinition、现行API/CLI或配置变更。

### 33.3 下一阶段只读准入结果

使用本机正式webserver `http://127.0.0.1:3000/graphql`发纯query，10秒超时、响应上限2MiB。原生workspace返回orchestrator / __repository__ LOADED，85 jobs/95 sensors中可见本表两个job和三个STOPPED sensor（默认亦STOPPED）；只查询身份和维护状态，不宣称运行进程源码与工作区逐字一致，不请求reload。

本表pool尚无持久化limit，实际slot0、pending0。原只读事件适配器刻意没有run coordinator，原生get_concurrency_info在pool缺limit时会访问coordinator默认配置，本轮首次只读调用因此失败且未写入；后改用既有native表的3次定键只读查询读取limit/slot/pending，不改适配器、不构造新实例或落配置。缺少已确认容量1，故目前不能判定自动化准入通过。

正式SSE日历按原sensor SQL读取2026-10-01～审计当日最近10交易日，结果为2026-10-08、10-09；本表两日partition/Raw/Silver均缺。历史截止后的这两个明确日期是后续接续窗口；本轮不采源，不证明源可用性，不登记新分区或生成候选。接续边界不能漂移回9月历史；日更登记时间仍上海22:00。

下一开发切片沿原P4卡片接入moneyflow_ind_ths，再逐个推进其余；本表pool容量1和三个sensor的启用另列精确运维清单并独立准入，P5真实日更及两日接续仍后置。全量历史阶段已关闭，整个P4未关闭。完整原生身份、控制证明、日志/hash与上述准入只读结果见[全量正式证据](../../reports/moneyflow_p4_mkt_dc_event_registration_formal_full_evidence_20261010.json)。

## 34. P4 同花顺行业资产接入（2026-10-10，编码前设计）

管理员要求“提交修改吧，然后继续推进下一个开发切片”，对应§33.3指定的moneyflow_ind_ths。上一轮全量登记收尾提交059ec20b。本轮仅接入该表Raw/Silver、分区、两个blocking checks、两个独立job和catalog；不添加sensor、历史event入口或正式运行。本节继承§6的完整12字段实施卡与模板§7A，不修改P0/P1来源、金额亿元或历史494日期/44460行事实，不补源缺口。

### 34.1 开发硬口径与消费者

| 硬口径 | 代码落点 | 正反验收 |
| --- | --- | --- |
| 一个源对应独立数据集 | assets/checks/jobs各moneyflow_ind_ths.py；专属cn_a_moneyflow_ind_ths_trade_days；registry/name_mapping | 两job分别仅选择本层与本层check，Silver仅依赖本Raw；不得选择大盘、calendar或股票池 |
| 源端12字段保真 | 复用daily_schema/daily_fields及build_daily_moneyflow_raw_candidate；不修改builder参数 | 单日90行真实归档fixture、NULL/负值/精度；错字段、错日、重键、空或两轮不同不发布 |
| 两轮稳定且完整 | 一个既有collect_daily_moneyflow session，单日trade_date、limit2000、offset递增、60秒间隔 | 分页及结束页由原候选测试覆盖；正式资产job读回源/Raw/Silver行数与请求参数；不按代码或当前目录裁剪 |
| 当前已绿Raw才能供Silver | 原asset_readiness_status，精确同日最新mat identity/file hash，随后核对实际Raw hash | 无check、错日、hash变更阻断，无源请求；不是只看文件存在 |
| 候选验证与正式check共用SQL | audit_daily_moneyflow_file/equality/standardization；check显式partitions_def、blocking=True | 实际partitioned job及native check存储同日SUCCEEDED；错日/资金差异有FAILED原生记录 |
| 发布协议只维护一份 | 将mkt_dc_update的路径/挂载/空间、intent/fsync/逐文件replace协议抽取io/moneyflow_update_publication.py；两表直接消费 | 大盘原25项回归；两表取消、替换后退出、幂等、旧目标变化/symlink/非法文件反例，原大盘revision和入口不变 |
| 行业完整来源证明 | io/moneyflow_ind_ths_update.py：receipt的dataset/date/count/scope/request/gap、两轮文件hash和SQL业务集合相等 | 90行计数，不套大盘恰好1行；复核文件缺失/被改/receipt跨表不得提升；原candidate迁移后可用目标与未迁移verification核对 |
| 正式资源不作测试 | fake源/虚拟时钟、临时Lake/staging/SQLite instance；治理使用原受保护runner | 正式Lake/PG/event/sensor/job/Prod读写0；本轮源复核未取得新结果，不能计作真实运行 |

正式名称固定为§6卡片中的两asset、两check、两job及专属partition。definition登记schema/source/path，runtime只登记实际行数/hash/observed columns；不将catalog改为factory/planner，不增加Gold、配置页、Prod DatasetDefinition或API。中文dataset名为“同花顺行业资金流向”。手动job使用明确partition_key，无新增run config参数；每次仅一个日期，不解析run key。

CodeGraph explore覆盖大盘asset→update与source契约，impact update_market_moneyflow_raw覆盖大盘Raw入口；索引未列完整测试及私有monkeypatch消费者，已直接源码核对本表候选/SQL、现行readiness、catalog及大盘definition测试。发布协议提取迁移所有调用与测试注入点，不保留旧协议副本、旧别名或兼容模式。生产Web/API/前端没有本资产消费者；其他五表尚无active资产，不因共用candidate能力而接入。

### 34.2 性能、配置及验证边界

| 项目 | 已有样本与本轮上界 | 拒绝与验证 |
| --- | --- | --- |
| 日期/身份/枚举 | 每次1日，trade_date+ts_code；不展开行业成员或证券对象；90行真实归档样本 | 非目标日期、重键或空拒绝；单轮≤20000行 |
| Tushare分页 | 90行时两轮各1请求；整页必须结束页；每轮最多11页，两轮最多22页，重试仍受共享64请求/300秒预算 | 原collector不改；有限重试、30秒请求预留及60秒稳定间隔；配额管理员已确认充足 |
| 列式读写 | Raw/verification各1日≤20000行，Silver候选≤20000行；两层正式各1文件，样本约8KiB/层 | 原DuckDB512MB、1线程、existing_no_spill，RSS≤768MiB；SQL集合对账，不Python明细计算 |
| 原子边界/恢复 | 共用moneyflow/writer.lock；每文件intent→os.replace→读回complete，Raw/Silver非整体事务 | 重读candidate/target/verification、实际hash；不自动删除候选、回滚事件或备份 |
| 空间/耗时 | 沿用挂载、同设备、首次空闲64GiB；正常日预计60秒等待加两请求和秒级本机IO，网络耗时无新实测 | 既有源300秒/RSS/磁盘拒绝线不放宽；隔离耗时分开，不把虚拟等待当网络SLA |
| Lake/DG正式操作 | 本轮0写入，无reload/pool/sensor/job/dynamic partition/event操作 | 后续历史登记另立清单；现有988历史文件不重建 |

无新增env/Settings/数据库/可调预算配置。稳定schema、paths、请求预算、pool名称来自原合同，新增check名称集中run_contracts/moneyflow.py；其消费者仅本表assets/checks/catalog与测试，definition加载生效，metadata/check和catalog对运营可见。共享发布协议新增必传dataset及validator属于内部调用合同，不是运营配置；大盘显式传原dataset和原audit，原checkpoint revision不变。

来源证据已读取P0归档：默认字段12个、显式全字段和身份关键字段、无参数/对象/时间点/区间/SDK分页；2026-09-30源/Prod均90行、两轮各90且业务差异0；复用fixture。当前MCP未暴露limit/offset，分页依据仍是归档SDK实测。本轮额外两次MCP请求等待未完成已停止等待，没有结果；不能把它写成成功、空数据或新源行为结论。在线Dagster文档请求连接失败；使用dagster-expert参考、现行1.13.18官方SDK实现和既有partitioned checks实测校准API，并通过本轮隔离job重新验证。不修改Tushare参数或字段合同，P5仍须真实新增日期验收。

### 34.3 本开发切片验收通过

实现两个独立资产、两个blocking检查、两个独立job、专属动态分区及中文catalog。Raw按明确交易日完整采集行业，Silver只读取同日已绿且实际hash匹配的Raw；12字段、亿元、NULL和负值保持原合同，仅日期标准化。目录治理发现新资产源文档链接误指DC，已修正为0343 THS文档并全量重跑通过。

| 硬口径与验证 | 本轮实际结果 |
| --- | --- |
| 独立身份、来源证明、同日readiness、发布及恢复 | 行业30项与大盘25项共55通过；包含不串表、无Raw/check/错日/变更hash阻断、receipt四类损坏、退出/取消后续跑和幂等，23.32秒 |
| 分页、金额/整数精度、两轮稳定、物理合同 | 既有行业和大盘候选测试80通过，5.35秒；未放宽20000行、64请求、300秒、512MB或64GiB准入 |
| 90行真实归档样本端到端 | 2026-09-30源样本两轮各90；第二轮逆序，Raw/Silver各90、reject 0、双向业务集合一致；2请求，明确12fields、limit2000/offset0；样本881142.TI的行业/56公司/净额14亿元读回一致 |
| 原生partition/check归属 | 两层同日SUCCEEDED且checked_row_count=90，check target storage_id/run_id/timestamp与各自实际物化一致；不是只验证函数返回True |
| 单日文件/隔离成本 | Raw8110B、Silver8086B；两个job合计531.434毫秒，fake请求/虚拟60秒时钟，不能外推真实源耗时或正式SLA |
| catalog与全库门禁 | 受保护runner治理12项及486个subtests通过；静态113项全部通过，runner完整15批无skip或权限放宽 |
| 完整definitions | dg check defs --use-active-venv --no-check-yaml成功；独立/private/tmp instance、telemetry关闭、UV离线/no-sync、不加载正式凭据或提交job |
| 源码/文档 | 改动文件Ruff和src/tests致命检查通过；文档完整性与diff检查记录于报告；CodeGraph explore/impact用于预审，开发后sync/status为up-to-date |

发布协议仅抽取一份，原大盘公开入口和checkpoint revision保持不变，全部内部调用及测试注入点迁移；没有兼容副本、额外配置或子系统依赖变化。原26份资金流历史报告/清单逐字匹配059ec20b；本次不将既有P0真实接口证据冒充新请求结果。模板§7A的来源、字段、单位、预算、恢复与验证映射见§6/§34.1～3及[本轮证据](../../reports/moneyflow_p4_ind_ths_evidence_20261010.json)。

本轮正式Lake/Prod/PG/分区/event/sensor/job/pool写入及reload全部0。本表既有494日/988历史文件没有重建或本轮重新扫描，不将本轮隔离验收宣称为正式日更验收。当前切片完成，整个P4仍开放、P5未进入。下一开发切片为本表22:00分区注册、Raw/Silver更新sensor和有界历史登记预演；正式登记及启用仍需精确清单和对应阶段批准。

<a id="moneyflow-ind-ths-automation"></a>

## 35. P4 同花顺行业 sensor 与历史预演（2026-10-10）

管理员要求提交并继续§34.3下一切片；资产接入已提交5033dc1f。本轮仅实现本表三sensor与只读历史预演，原494来源日期/44460行/988物理文件沿用P3冻结证明；不补源缺口，不实现本表APPLY，不启用sensor、不改pool或reload。

### 35.1 硬口径、共享能力和影响面

| 硬口径 | 代码与消费者 | 正反验收 |
| --- | --- | --- |
| 三个独立STOPPED sensor | sensors/moneyflow_ind_ths_sensor.py；注册cn_a_moneyflow_ind_ths_trade_day_sensor，更新分别为两job名加_sensor | 同行业分区/job身份；统一tags为quote_data+partition/raw/silver+partition_registration/asset_update；无Tushare resource，无跨表run/state |
| 上海22:00、SSE日历 | 原trade_day注册helper，行业历史起点2024-09-10；更新起点仍2026-10-01 | 当日22点前不登记；历史漏登记可恢复，22点后当日优先加最早缺日，最多2键；非交易日不造当日键；更新22点前不读资源/event |
| 最近10日、每tick一个run | 将大盘evaluator/注册编排移到moneyflow_update_selection.py，两表各自明确contract绑定，保留大盘入口 | 当前日优先、再未完成日、再每日复核；active run阻断；缺分区、坏check/hash、查询饱和阻断；不对十日逐日调用event API |
| 绿check精确归属且实际文件匹配 | 共用batch_moneyflow_readiness，纯事件身份+hash；两表独立assets/checks/paths | storage_id/run_id/timestamp全部一致，限100记录/查询；缺文件/symlink/超64KiB/变更阻断；Silver新Raw hash只在已绿时提交 |
| 有限重试和cursor独立 | 既有run_key与六次attempt，run records为权威；cursor身份绑定本表job/partition | 请求重放不烧attempt、cursor丢失仍最多6次；坏JSON/超8KiB/跨表cursor拒绝；10日状态目标2KiB |
| 临时源错误显式标记 | 当前collect_daily_moneyflow沿用mkt分类：failed_pages全部retryable且非预算错误才允许；source_pending和source_unstable允许下一tick重采；Raw候选complete_round按原SQL的不稳定原因标记，归一化/精度/schema/重复仍永久失败 | 实际失败job原生metadata读回；空/两轮不同/timeout可重试，权限/schema/精度/预算不重试；无需改参数或field合同 |
| 冻结历史仅本表证明 | 抽取history_event_preview中的proof/state到moneyflow_history_event_preview.py；每表入口固定绑定；大盘plan/APPLY保留原入口及revision | 全988文件hash/54控制，最近20日两层同正式SQL；每100日一查询，不逐日readiness；跨cohort/篡改/缺文件/旧check失败阻断 |
| 默认纯只读 | preview_industry_moneyflow_ths_history只暴露查询，无apply/lock/checkpoint/save；正式只读使用既有daily_basic_event_instance默认read-only | 缺分区/两层mat/最近check明确差集；写入trap、重复预演不改文件/event；不创建instance/DDL、不调用sensor evaluation |

为避免主逻辑复制，新增固定内部MoneyflowAutomationContract仅绑定已接入mkt_dc/ind_ths的身份、check、分区起点，不生成Definitions，不消费catalog运行，不是运营配置。其字段和消费者统一落在run_contracts/moneyflow_automation.py，来自既有moneyflow常量/明确schema身份；无env、Settings、DB或开关新增，定义加载生效，cursor/tags/metadata对运营可见。两表共用运行预算，不增加额度。

CodeGraph search/explore定位evaluate_market_moneyflow；impact覆盖batch_market_moneyflow_readiness的sensor、测试、历史APPLY读回，market_moneyflow_history_proof覆盖plan与APPLY。直接源码补核私有monkeypatch、preview只读方法和现有daily_basic_event_instance初始化关闭行为。迁移全部内部调用和测试注入点，公开大盘入口保留为长期数据集适配器，不保留协议副本。通用collector只有daily Raw writer消费，六表候选测试；目前仅行业资产消费该writer，其他五表未启用，因此本轮不会批量启动其他数据集。source错误分类属于原§2已确认自动化语义补齐，不改API/request/field或物理校验通过条件；SQL本身保持纯校验，仅在采集边界给不稳定错误标记。

### 35.2 性能与验证预算

| 项目 | 设计上界/依据 | 超限处置与验收 |
| --- | --- | --- |
| 注册器 | SSE calendar 1文件，原helper最多3 SQL，2次dynamic partition读取；返回≤2键，注册数≤20000 | 21点前不造当天键；过大分区拒绝；只返回SensorResult，不执行正式登记 |
| Raw更新tick | 最近10 expected，日历1 SQL/文件；2 active-run查询、1分区读取、2 readiness查询、1 run-record查询、最多1失败记录查询，共≤7 native API；每查询≤100记录，物理hash≤10文件/640KiB | 查询饱和、hash超64KiB或坏证据停止；1个RunRequest；实际10日profiling，不以单日代替 |
| Silver更新tick | 日历1 SQL，2 active+1分区+4 readiness，≤7 native API；hash≤20文件/1280KiB，无源请求 | 1 RunRequest；Raw未绿/坏Silver不提交；仅已绿Raw修订允许重建Silver |
| 本地热路径成本 | 单日行业真实归档90行约8KiB/层；日历仍由既有资源读取，不新增DuckDB配置；稳定路径目标<1秒，隔离10日上限2秒 | 测试记录SQL/API/hash文件/字节/cursor/耗时；超过停止分析，不升窗口或读历史兜底 |
| 行业全历史预演 | 494日/44460行/26日期批次；988文件hash，约7.6MiB仅估算；54个已有控制；2×ceil(494/100)+2check+1partition=13 native读取 | 每unit≤120秒、RSS≤768MiB；控制前后hash，SQL只深检最近20日两层40文件、20组标准化对账，不把文件数当SQL语句数；关闭spill；未知范围/改变文件拒绝 |
| 预演输出/后续登记 | 只输出/tmp或repo报告；预期494键、988物化、40check，共1522工作项/1028event，当前差集必须正式读回确认 | 正式0写入；预演不实现APPLY。本表可恢复事件执行器是下一切片，正式样本/全量另按清单批准 |

本轮隔离测试使用fake源/时钟、临时Lake/staging/SQLite；大盘sensor/preview/plan/APPLY回归，六表候选回归，受保护sensor-tags/catalog/static与完整defs加载。正式只读预演只读取现行Lake与既有本机PG，不连接Prod/Tushare，写报告在/private/tmp；先检查代码及方法无隐含写入。历史源缺口不得加进登记日期集合。官方sensor/partition文档已本轮读取，实际版本API继续由既有SDK和隔离原生记录验证。

### 35.3 本切片验收通过，历史登记仍待执行器

三个独立sensor已定义并默认STOPPED，沿用600秒最小评估间隔：专属分区注册器、Raw更新、Silver更新。登记当天分区的时间仍为上海22:00；注册器可以恢复更早的历史漏登记日。两层更新仅处理2026-10-01之后最近10个SSE交易日，一次提交一个日期；临时源错误按原方案允许有限重采，schema、身份、精度和预算错误继续阻断。没有开启sensor、提交job或reload正式代码位置。

| 硬口径与验证 | 实际结果与证据边界 |
| --- | --- |
| 行业注册/更新/重试/cursor与身份隔离 | 23项通过；包含22点门禁、行业起点、跨表/跨层cursor拒绝、原生失败metadata、两轮数量/业务变化可重试、六次持久化attempt上限 |
| 六表采集与两表定义回归 | 582项通过，72.67秒；字段、分页、精度、取消/退出恢复、定义合同未放宽；fake源与临时时钟 |
| 大盘sensor/预演/可恢复事件执行器及行业预演 | 76项通过，81.84秒；包含重复纯读取、坏cohort/控制/文件拒绝、原生check identity与跨表事件隔离；保留原大盘入口和revision |
| 10日行业热路径 | 隔离SQLite中运行真实job，使用90行归档样本改写为明确的合成未来日期；Silver tick 23.420毫秒，日历1 SQL、native读取7次、20文件161960B、cursor595B，tick源请求0；不是未来源端实测或正式SLA |
| 正式行业冻结历史 | 上海2026-10-10 23:30左右纯只读预览，494实际来源日期、44460行、26日期批次、988文件8004292B全部匹配；54控制前后不变；最近20来源日40文件/20组SQL对账通过 |
| 正式原生差集 | 494分区键待登记，Raw/Silver各494物化与20最近检查待补；没有可复用本表事件。合计1522工作项/1028事件；13次native读取（1分区+10物化+2检查），预览0.8259秒 |
| 最终源码与定义门禁 | 受保护静态113项完整15批、catalog12项/486 subtests通过，无skip或权限放宽；去除正式凭据的临时instance中完整dg check defs通过；18个改动Python文件Ruff与全src/tests致命检查通过 |

本轮先用CodeGraph search/explore/impact审计共享调用链，再迁移大盘/行业适配器、全部内部调用和测试注入点；最终sync/status核对索引。变更仅在orchestrator及对应设计、治理/拓扑和证据报告，无Prod DatasetDefinition、API/CLI、前端或主体依赖矩阵变化。正式Tushare/Prod请求、Parquet写入、分区/event/job/sensor/pool变更及reload全部0。原27份资金流历史报告/清单匹配5033dc1f。

验证期间一次无文件参数的Ruff format误扫其他Python文件；逐文件AST核对后，557个本轮未改文件恢复原HEAD内容，两个测试清单恢复后仅重加本轮7条读取路径及3个sensor身份。最终受保护静态与catalog已重新完整通过，误格式化不进入交付。曾发现共享proof局部变量覆盖dataset contract及静态sensor身份清单未更新，均已修正并重跑相关完整套件，没有跳过失败项。

结果见[本轮证据](../../reports/moneyflow_p4_ind_ths_automation_evidence_20261010.json)。本切片完成，P4仍开放、P5未进入。下一切片只开发本表可恢复事件登记执行器，冻结两日样本与全494日清单；正式样本及全量APPLY分别按清单批准，不把本轮继续开发授权扩展为正式登记、sensor启用或其他五表接入。

## 36. P4 行业历史事件可恢复登记（2026-10-10，编码前）

管理员要求提交并推进§35.3下一步；行业调度和只读预演已提交bf6fa7bf。本轮按原§31登记协议接入moneyflow_ind_ths，范围仅执行器、隔离验收和只读冻结清单。正式登记、reload、pool或sensor启用不在本轮执行范围。

### 36.1 硬口径与实现、消费者、验收

| 硬口径 | 实现落点与消费者 | 正反验证 |
| --- | --- | --- |
| 一份协议、两表独立身份 | 从大盘提取moneyflow_event_plan.py与moneyflow_history_events.py；大盘/行业event_plan与events各为长期固定数据集适配器；共享固定automation contract | 原大盘34场景回归；原正式样本/全量plan逐字再构造对账，原revision/hash不变；行业适配器拒绝大盘清单，不调用其他五表 |
| 只认P3冻结日期、文件及实际行数 | common history proof从本表plan.date_counts追加行业entry.row_count；保留大盘原entry形状；本表plan冻结dataset/revision、54 controls、日期/两层hash/行数与本机storage identity | 行业90行实际归档、89/90不同日计数；缺少/伪造row_count即使重算plan hash也拒绝；范围外日期、坏文件/control/实例拒绝；不按当前股票或行业对象池裁剪 |
| 默认纯只读、显式APPLY | report_industry_moneyflow_ths_history_events默认apply=False；原适配器关闭DDL、默认read-only；readonly只查两job active及批量native差集 | 重复预演不建目录/锁、不写plan/checkpoint/分区/event；apply非bool拒绝；不加入Definitions、不新增CLI或自动触发 |
| 分区→物化→最近20日check→读回 | 专属cn_a_moneyflow_ind_ths_trade_days，两层物化含冻结行数/实际hash/原checkpoint；Silver绑定Raw hash；check先复用正式industry SQL并核对冻结行数，再绑定mat三字段身份；执行器核对已有行业mat/check记录的行数元数据 | 旧日期只物化、不伪造check；两层原生记录count正确；FAILED/stale/错hash/错行数或上游修订冲突停止；最终批量差集0和少量readiness验收 |
| 逐事件持久化、幂等恢复 | 沿用writer.lock、events/<plan_hash>/plan.json与checkpoint；每native event后fsync原子保存；native事实为完成依据 | 中途取消、实际子进程在event后checkpoint前退出、状态写失败、进度回调失败、缺失/滞后/伪造checkpoint、重放；保留已提交事件，不删除或回滚 |
| 维护窗口与预算 | 每批查本表两job active及instance identity；所有native读取和写入前后取消；原600秒/单批120秒/256读取/4096项不变 | active run/锁冲突/symlink/超时/读写或内存预算拒绝；隔离494日期全规模，记录API、批宽、fsync、RSS和耗时；正式执行前另确认三sensor停止和独占writer |

CodeGraph explore/impact覆盖build/validate_market_moneyflow_event_plan与report_market_moneyflow_history_events；部分同名token搜索混入其他域，直接核验当前实现、唯一测试调用与测试monkeypatch/子进程脚本。迁移全部内部消费者和测试注入点；大盘公开函数签名保留，不保留重复协议或兼容开关。没有生产Web/API/前端、DatasetDefinition或主体依赖矩阵变更。

### 36.2 配置审计、性能与验收边界

没有新增env、Settings、DB配置、resource、预算参数或可调开关。唯一新增稳定身份industry_moneyflow_ths_history_events_v1落在原固定automation contract的event_revision，消费者为plan builder/validator和执行器；定义加载生效，在冻结清单/进度可见。继承§31.2原拒绝预算，日期及行数取已冻结证明，不从运营输入拼装。

| 路径 | 明确规模/成本 | 拒绝/验收 |
| --- | --- | --- |
| 全证明与计划 | 494实际日期、44460行、26历史unit、988文件8004292B、54控制；最近20日40文件/20组正式SQL；无源对象/枚举/分页/Prod/Tushare请求 | proof每次≤120秒、RSS≤768MiB、DuckDB512MB/1线程/0spill；plan≤32MiB；坏hash或未知日期拒绝。两份计划生成可以各完整读proof，不能改成全494日SQL深扫 |
| 两日样本 | 2026-09-29、09-30；2键/4mat/4check，总10项；冻结每日期row_count，拒绝固定1或固定90 | 临时真实SQLite取消—退出—续跑—读回；正式PG写入另批准，预计本机秒级不能作PG承诺 |
| 全量登记 | 494键/988mat/40check，总1522项/1028事件；登记5个≤100日期批，物化5批、检查1批；每原生写独立提交，不包全历史事务 | ≤4096项/600秒/每批120秒/256读取；metadata每query≤100，日期批≤100；预算不足停止，保留已提交事实 |
| 原子边界/进度 | staging内plan/checkpoint保存，checkpoint≤256KiB；逐事件完成量/总量/%/当前日层/阶段/更新时间与耗时，API读前进度更新 | 状态写失败不回滚事件；停止领取新unit；重读native identity而非checkpoint跳过；不添加新数据库实体 |
| 最小与容量证明 | 90行业行归档fixture；不同日期89/90行；完整494日期临时文件/native instance，以当前正式行数和event数量证明预算 | 文件/hash/源调用数前后不变、旧日期check为0、重复执行新增为0；只写隔离目录，不能宣称P5或PG正式写入通过 |

复核官方[runless instance API](https://dagster.io/docs/api/dagster/external-assets-instance-api)、[asset checks](https://dagster.io/docs/guides/test/asset-checks)、[partitions](https://dagster.io/docs/guides/build/partitions-and-backfills/partitioning-assets)与安装SDK1.13.18；原runless检查的internal target API继续按本机隔离原生记录验收，不升级依赖。后续形成精确两日/全量JSON及命令，正式业务批准仍分两阶段。

### 36.3 执行器与隔离验收完成（2026-10-11收尾）

共享plan与可恢复执行协议分别落在moneyflow_event_plan.py、moneyflow_history_events.py，大盘与行业各有固定适配器。行业清单逐日绑定P3的row_count，物化、检查和已有事件读回都核对该数量；大盘继续保留单行语义、原revision、公开入口及计划格式。正式原两份大盘清单通过重新构造校验，plan hash分别仍为90639d04bd102597671856d0d3d9584ca80cf5799d4d77b35190e5cd0c92e319和e699ce04e04ed8e792a95ff72140251945aa282cda0b18ed25972517357ce92d，文件字节未改。

| 硬口径与验收 | 本轮实际结果 |
| --- | --- |
| 行业恢复、原大盘回归与两表预演 | 103项全部通过，119.02秒；涵盖逐事件取消、实际子进程在写event后保存checkpoint前退出、幂等重放、缺失/滞后/伪造checkpoint、进度回调失败、active run、互斥锁、预算及错误实例/文件/计划 |
| 行业行数与身份 | 归档真实90行fixture；另造明确89/90行两日样本，Raw/Silver物化及blocking检查原生读回数量正确、target storage_id/run_id/timestamp一致；七类重算hash的错row_count清单、跨表清单、已有事件错行数均拒绝 |
| 全494日容量 | 临时Lake/SQLite以归档90行业行改写为494个合成日期，44460行；1522/1522工作项、1028事件、494键完成，141次metadata读取，最大日期批100；重复执行新增0，旧日期不伪造check |
| 本机隔离成本 | APPLY 5.296秒，1047次原子控制文件保存合计0.386秒、最慢3.329毫秒；进程peak RSS约424.9MiB。源请求、Parquet和原控制hash不变；该数字不作为正式PG耗时或源端SLA |
| 受保护门禁 | 静态113项完整15批、catalog12项/486 subtests通过；runner只增加四个明确源码读取路径，无skip或权限放宽，正式资源拒绝区前后未变 |
| 完整definitions与源码 | 去除正式凭据、临时instance、UV离线/no-sync下完整dg check defs成功；11个本轮Python文件Ruff和全src/tests致命检查通过；文档完整性、diff及CodeGraph sync/status见报告 |

计划硬口径对账：表独立身份/正确数量由固定contract、proof、plan和原生metadata测试覆盖；最近20日检查由共享执行器及全494日容量测试覆盖；纯只读由默认入口和写入trap覆盖；逐事件提交及恢复由临时原生instance、实际退出/取消/重放验证；预算和拒绝条件由现有常量及超限反例验证。模板§7A的来源、范围、时间、资源、性能与恢复继续使用§6/§36.1～2，原P3 source counts是历史事实，不用合成样本证明未来源端可用性。

全量正式PG登记成本、维护窗口、正式check/readiness读回尚未验收，必须由获批样本与全量执行补齐；sensor启用、pool容量1和P5真实日更仍后置。CodeGraph explore/impact已用于共享协议及调用方预审，直接补核私有测试和子进程注入点；开发后sync/status为up-to-date。变更仅orchestrator内部协议、适配器、测试和两份设计/报告，无主体依赖矩阵、Prod DatasetDefinition、API/CLI或前端变化。原28份资金流报告/清单逐字匹配bf6fa7bf。本轮正式写入及Prod/Tushare请求全部0，结果见[执行器证据](../../reports/moneyflow_p4_ind_ths_event_registration_evidence_20261010.json)。

### 36.4 精确正式清单、命令与后续边界

上海2026-10-10 23:57纯只读生成与预检，目标为既有goldenshare_dagster PG，默认read-only、关闭自动建表。完整证明覆盖2024-09-10～2026-09-30的494个实际来源日期、44460行、988文件8004292B及54控制hash；逐文件hash一致，SQL深检仍仅最近20来源日两层40文件/20组标准化对账。原operation为history-full-20261009，cutoff为2026-09-30；两份清单列精确日期和逐日row_count，不把日期区间或源缺口当待补日期。

| 冻结清单 | 实际待登记范围 | plan_hash |
| --- | --- | --- |
| [两日样本](../../reports/moneyflow_p4_ind_ths_event_registration_sample_plan_20261010.json) | 2026-09-29、09-30；每日期90行业行；2键、4物化、4检查，总10项/8事件 | 72cab9be9af8b53cf47463acce087598dfe31c402161bf9c792149d2bb4a7e3b |
| [全量](../../reports/moneyflow_p4_ind_ths_event_registration_full_plan_20261010.json) | 原494来源日；494键、988物化、最近20日40检查，总1522项/1028事件 | 7dbc2c4f08774552f6f0fafa8f423338980d53fb262a300ce09506e4a1cbdc1c |

只读差集与上表一致，当前completed=0。样本生成0.370秒、预检0.377秒/7次native读取；全量生成0.307秒、预检0.409秒/15次读取，均含本表两job active查询。两份文件分别13760/270910B；整个生成/预检及大盘清单一致性验证2.582秒。正式APPLY仍三次核对完整proof，并独立审计最近日期，141次读取是隔离全规模执行值，正式必须继续遵守256次/600秒/批120秒门禁，不能从只读或SQLite速度承诺PG速度。

**以下正式写入尚未执行。** 下一步先按两日清单批准样本，在执行前只读确认三个本表sensor均STOPPED、两job无active run、无其他人工moneyflow writer；运行使用当前已验收源码及独占writer。确认正式加载代码身份与本轮源hash的范围，不能用“definitions已加载”替代源版本核对。完成样本后读回四条原生check的partition/target、两日两层readiness与物理证明，再独立批准全量。全量复用样本，剩余492键/984物化/36检查，总1512项/1020事件。本清单不含reload、pool配置、sensor启用、job执行或其他五表。

在lake_console/orchestrator目录，先用同一清单做默认只读预检：

```bash
.venv/bin/python3 -B - <<'PY'
import json
from pathlib import Path
from orchestrator.defs.bootstrap.daily_basic_event_instance import daily_basic_event_instance
from orchestrator.defs.bootstrap.moneyflow_ind_ths_events import report_industry_moneyflow_ths_history_events

plan = json.loads(Path('../reports/moneyflow_p4_ind_ths_event_registration_sample_plan_20261010.json').read_text())
assert plan['plan_hash'] == '72cab9be9af8b53cf47463acce087598dfe31c402161bf9c792149d2bb4a7e3b'
with daily_basic_event_instance() as instance:
    result = report_industry_moneyflow_ths_history_events(instance=instance, plan=plan)
print(json.dumps(result, ensure_ascii=False))
PY
```

**只有取得对应两日清单批准并通过上述维护预检后**，执行以下命令：

```bash
.venv/bin/python3 -B - <<'PY'
import json
from pathlib import Path
from orchestrator.defs.bootstrap.daily_basic_event_instance import daily_basic_event_instance
from orchestrator.defs.bootstrap.moneyflow_ind_ths_events import report_industry_moneyflow_ths_history_events

plan = json.loads(Path('../reports/moneyflow_p4_ind_ths_event_registration_sample_plan_20261010.json').read_text())
assert plan['plan_hash'] == '72cab9be9af8b53cf47463acce087598dfe31c402161bf9c792149d2bb4a7e3b'
with daily_basic_event_instance(writable=True) as instance:
    result = report_industry_moneyflow_ths_history_events(
        instance=instance, plan=plan, apply=True,
        progress=lambda item: print(json.dumps(item, ensure_ascii=False), flush=True),
    )
print(json.dumps(result, ensure_ascii=False))
PY
```

全量独立批准后，命令仅将清单文件换为moneyflow_p4_ind_ths_event_registration_full_plan_20261010.json，并将assert hash换为7dbc2c4f08774552f6f0fafa8f423338980d53fb262a300ce09506e4a1cbdc1c；同样先默认只读预检，再APPLY及后验。默认只读差集应归零；样本两日四项readiness及全量最近20日40项readiness应全绿，全部988文件和54原控制hash不变。旧日期只登记物化，不伪造check或补源缺口。

取消可用KeyboardInterrupt，已提交原生事件保留；用原冻结清单续跑。checkpoint位于`/Volumes/datasource/data_lake_staging/moneyflow/history-full-20261009/events/<plan_hash>/checkpoint.json`，它只记录进度，不能编辑后作为完成依据。触发预算、active run、锁、实例、hash或既有行数冲突时停止并报告，不改源证明或放宽门禁。本开发切片完成，P4保持开放，P5未进入。

## 37. P4 行业历史事件两日正式样本通过（2026-10-11）

管理员要求“提交修改吧。然后推进下一步，执行吧”，对应上轮明确提出的§36.4两日正式样本。执行器、隔离验收和精确清单已在当前dev-interface提交为6039fd37，未推送。本轮只执行moneyflow_ind_ths的2026-09-29、09-30，plan hash仍为72cab9be9af8b53cf47463acce087598dfe31c402161bf9c792149d2bb4a7e3b，不扩展为全量登记、启用sensor或执行job。

### 37.1 实际范围、维护状态和原生读回

上海2026-10-11 15:04～15:05，先纯只读预检，再通过原daily_basic_event_instance(writable=True)及行业固定适配器完成登记，目标DAGSTER_HOME为`/Users/congming/.goldenshare/dagster_home`，数据库为既有本机goldenshare_dagster PG，自动建表关闭。正式命令在lake_console/orchestrator目录使用既有.venv：

```bash
# 只读预检；无正式写入。
.venv/bin/python3 -B /private/tmp/moneyflow-p4-ind-ths-formal-sample-20261011.py
# 已获准的精确两日APPLY及默认只读后验；不选择全量。
.venv/bin/python3 -B /private/tmp/moneyflow-p4-ind-ths-formal-sample-20261011.py --apply
```

该临时审计驱动只复用§36.4现行入口，增加同库只读sensor维护检查、原生身份/数量读回、readiness与全量剩余差集，不新增仓库CLI或Definitions入口。脚本/日志hash和具体结果归档[正式样本证据](../../reports/moneyflow_p4_ind_ths_event_registration_formal_sample_evidence_20261011.json)。恢复仍用原两日清单及同一执行器，不编辑checkpoint、不删除原生事件、不重新生成历史文件。

| 检查与实际操作 | 结果 |
| --- | --- |
| 写前维护核验 | 本表两job无active run；原生查询扫描106个sensor状态，三个行业sensor没有持久化启用记录；当前进程实际导入的三个定义默认STOPPED；写前再次读取，写后结果相同，状态变更0 |
| 执行源码身份 | 新Python进程直接导入当前提交的适配器/共享执行器，11个已验收Python文件hash不变，实际加载的项目源码逐项匹配6039fd37；不依赖code location执行job，未reload；不宣称驻留服务所有源码hash已核对 |
| 正式新增 | 专属cn_a_moneyflow_ind_ths_trade_days增加2键，Raw/Silver各2条物化及2条blocking检查；总10工作项/8原生事件 |
| 行数与检查归属 | 两日每层均90行、source_row_count=90、checked_row_count=90；四条check均SUCCEEDED/passed/blocking，partition及target storage_id/run_id/timestamp与本层实际物化全部一致 |
| 原生身份 | 物化storage id为7441784～7441787，仅诊断记录，不进入计划身份；Silver同时绑定同日Raw hash |
| 后验 | 默认只读样本缺分区/物化/检查均0；两日两层readiness四项均ready；checkpoint为complete、10/10、100%，完成量单调 |
| 执行成本 | APPLY 1.538秒、53次helper metadata读取、60条进度记录；维护状态及外部前后验另计，53不是底层SQL总数。未触发或放宽600秒/批120秒/256读取门禁 |
| 物理证明 | 前后完整proof重构校验原494日/44460行/988文件8004292B和54控制hash，最近20来源日两层40文件SQL对账；额外控制hash复核一致，Parquet改写0 |

正式写入仅上述分区、runless物化/check及staging内冻结plan/checkpoint/互斥锁。没有Prod/Tushare请求、job执行、sensor evaluation或启停、pool配置、reload、Parquet写入、全量APPLY或其他五表接入。原31份资金流报告/清单逐字匹配6039fd37；本轮代码、源字段/参数、API/CLI、配置、路径及依赖矩阵均未改。

### 37.2 后续全量范围和边界

正式只读已再次验证原494日全量清单，hash仍为7dbc2c4f08774552f6f0fafa8f423338980d53fb262a300ce09506e4a1cbdc1c，现已完成10/1522项。全量将复用本次四条物化身份，实际剩余1512工作项：492分区键、984物化、36检查，共1020原生事件。其纯只读预检15次native读取、约0.419秒；该数字与两日APPLY成本均不能代替正式全量预算验收。

下一步按§36.4独立批准原全量清单，然后在同一维护/源码/独占writer条件下执行与读回；仍保持600秒、批120秒、256次读取、每批100日期等硬门禁，触限保留已提交事实并停止。全量后验要求494键、988物化和最近20来源日40检查差集0，物理证明不变，近期readiness按有界批次核验。更早日期只保留物理证明/物化，不伪造绿check，不补源缺口。

本轮两日正式样本阶段完成，全量行业登记未执行，P4仍开放、P5未进入。全量批准不自动覆盖pool容量1、sensor启用、代码reload或真实日更；这些仍按各自精确清单推进。

## 38. P4 行业全量历史事件正式登记完成（2026-10-11）

管理员回复“提交吧。然后继续推进”，对应§37.2明确的原494日全量清单。样本收尾的两份文档和报告已在当前dev-interface提交5e705f45，未推送；行业执行器及11个已验收Python文件与6039fd37一致。本轮执行原清单hash 7dbc2c4f08774552f6f0fafa8f423338980d53fb262a300ce09506e4a1cbdc1c，不重新生成或改变范围，源缺口保持原样。

### 38.1 执行及读回

工作目录lake_console/orchestrator，目标为`/Users/congming/.goldenshare/dagster_home`对应的既有本机goldenshare_dagster PG。先默认只读预检，再获准APPLY；自动建表关闭，三个sensor无持久化启用记录且当前定义默认STOPPED，两job无active run，使用原moneyflow writer互斥。

```bash
.venv/bin/python3 -B /private/tmp/moneyflow-p4-ind-ths-formal-full-20261011.py
.venv/bin/python3 -B /private/tmp/moneyflow-p4-ind-ths-formal-full-20261011.py --apply
```

临时驱动仅调用§36.4同一行业适配器，按冻结清单做有界原生读取、维护检查、最近20日readiness和样本身份读回，不新增正式CLI或运行入口。取消或失败保留已提交事实，续跑使用原清单；不能编辑checkpoint跳过原生验证，不删除/回滚事件或重写文件。

| 验收项 | 上海2026-10-11 15:19正式结果 |
| --- | --- |
| 本次新增 | 492分区键、984物化和36条blocking检查，共1512工作项/1020事件 |
| 最终原生事实 | 全494分区、988物化和最近20个实际来源日40检查齐；默认只读差集0/0/0，checkpoint complete、1522/1522、100% |
| 行数与身份 | 逐日物化row_count/source_row_count等于清单原date_counts；40检查checked_row_count正确，均SUCCEEDED/passed/blocking，partition和target三字段与本层物化完全一致；Silver绑定同日Raw hash |
| 样本复用 | 09-29、09-30的四条物化storage id 7441784～7441787保持不变，没有重复登记样本 |
| 近期readiness | 每批10日读取，两批共40项Raw/Silver全部ready；旧日期只有物化与物理证明，不伪造检查 |
| 性能及恢复 | APPLY 17.301秒，141次helper metadata读取，1164条进度记录，完成量单调；每日期批≤100，原600秒/批120秒/256读取门禁未触发或放宽。维护与外部前后验、写API内部SQL另计 |
| 物理及控制证明 | 原494日/44460行、988文件8004292B和54控制hash前后匹配；SQL深检仅最近20来源日两层40文件/20组标准化对账；Parquet改写0 |

实际执行进程加载的项目源码hash与5e705f45匹配，执行器由新进程直接调用，不依赖code location运行job；原32份资金流报告和清单保持原字节。正式写入仅上述分区、runless事件及staging中的冻结plan/checkpoint/互斥锁，没有Prod/Tushare请求、job执行、sensor evaluation或启停、pool修改、reload、Parquet写入或其他五表接入。源码、源参数/字段、配置、API/CLI和主体依赖矩阵没有变更。完整原生身份、日志/hash、对账及后续只读准入见[全量正式证据](../../reports/moneyflow_p4_ind_ths_event_registration_formal_full_evidence_20261011.json)。

### 38.2 本表历史登记关闭，后续条件仍明确

| 后续条件 | 上海15:20只读结果 | 后续边界 |
| --- | --- | --- |
| 行业历史事件 | 全量原生差集0，最近40项readiness通过 | 本表历史登记关闭，不重放写入 |
| 正式服务definitions | orchestrator / __repository__为LOADED，但返回的job/sensor清单未包含行业两个job和三个sensor | 代码已实现且隔离defs验收通过；日更前需独立批准加载当前代码并核对身份。本轮未reload，不能把历史事件完成当成日更可启动 |
| 请求执行池 | moneyflow_tushare_writer无持久化limit、slot=0、pending=0；三个有界表读取，没有初始化coordinator或自动配置 | 按既有合同在日更准入阶段配置容量1并读回，本轮不修改 |
| 接续边界 | cutoff=2026-09-30，sensor start=2026-10-01；正式SSE日历最近10日窗口仅10-08、10-09，两日行业partition/Raw/Silver均缺 | 这是待接续日期，不是源可用性证明；真实请求和日更验收仍在后续获批阶段 |
| 其他五表 | 尚待原P4独立资产/check/job/sensor及历史事件接入 | 下一开发切片沿原实施卡接入moneyflow_cnt_ths，不合并数据集或提前启用七表 |

日历审计仅1次有界SQL及1次专属分区查询；workspace只读GraphQL与池三个有界查询均0写入，无sensor dry-run、cursor保存或job提交。行业历史登记阶段关闭，整个P4保持开放，P5未进入；代码加载、pool、sensor和真实日更分别按后续精确清单准入。当前行业历史事实已完整登记，正式服务尚未加载其job/sensor这一差距已明确记录。

## 39. P4 同花顺概念资产接入（2026-10-11，编码前对账）

管理员要求“提交修改吧，然后继续推进moneyflow_cnt_ths”。行业全量登记收尾已提交70ee1cc9。本轮按§6概念7A实施卡，只接入独立Raw/Silver、专属分区、两个blocking checks、两个独立job和catalog；sensor、历史登记、正式资源执行属于后续切片。沿用P0/P1真实来源证据和P3既有495日/192009行/990文件，不重建历史或补源缺口。

### 39.1 硬口径与实际代码落点

| 硬口径 | 代码与消费者 | 正反验收 |
| --- | --- | --- |
| 一个源对应独立数据集 | assets/checks/jobs各moneyflow_cnt_ths.py，专属cn_a_moneyflow_cnt_ths_trade_days，catalog/name_mapping | §6确定的两asset/check/job名称；job仅选本层及本层check，Silver只依赖本Raw，不选行业、大盘、日历、股票池 |
| 概念12字段与精度保真 | 既有daily_schema/fields、Raw candidate和SQL checks；industry_index为DECIMAL(24,4) | 已归档09-30真实387行fixture，经原采集接口替身进入partitioned job；NULL/负值/高精度原值不重算、补0或成员裁剪；坏字段/日期/重复/空/两轮不同拒绝 |
| 同日完整两轮来源证明 | 行业日更helper迁到io/moneyflow_daily_update.py，Raw/Silver函数要求显式dataset；本轮仅允许ind_ths、cnt_ths | receipt必须匹配dataset/date/count/scope/request/gap，Raw及verification hash/SQL集合一致；跨表receipt、篡改verification不能发布 |
| Silver必须消费同日已绿Raw | 现行asset_readiness_status、最新mat identity及实际Raw hash；候选标准化只转换日期 | 缺/错日check、最新Raw已变、更改文件阻断；Silver不请求Tushare |
| 原子提升协议只有一份 | 继续使用moneyflow_update_publication，逐文件intent/replace/complete与namespace互斥 | 取消、replace后退出和幂等续跑；坏旧文件、symlink、空间/设备、外部变更反例；不复制协议或备份 |
| check真实分区和物化归属 | checks显式partitions_def与blocking，复用audit_daily_moneyflow_file/standardization | 原生job/check存储与target storage_id/run_id/timestamp同日；错日与字段差异产生FAILED检查 |
| 定义契约与运行事实分开 | definition使用既有schema/source/path/中文名称；runtime只记录实际计数/hash/observed columns | catalog治理对账；不把registry改成factory，不新增Gold、Prod合同、API或配置 |

CodeGraph search/explore定位行业asset→update及相关sensor，impact update_industry_moneyflow_ths_raw覆盖行业入口；索引未完整识别测试monkeypatch，直接源码补核全部引用。行业asset与definition测试、受保护runner源文件白名单同步迁移到共用日更helper，删除旧helper，不留别名或兼容副本。大盘更新helper不变；行业job/asset/check/sensor名称及checkpoint口径不变。Web/API、前端和Prod DatasetDefinition没有本资产消费者，主体依赖矩阵不变。

### 39.2 性能、配置及验收边界

| 项目 | 既有证据与执行上界 | 拒绝与验收 |
| --- | --- | --- |
| 对象/日期/枚举 | 每次1日、trade_date+ts_code，无概念成员展开；09-30真实样本387行 | 非目标日期、空、重键拒绝，单轮最多20000行 |
| 请求/分页 | 原collector显式12字段、trade_date/limit2000/offset0起；样本两轮共2请求，单轮最多11页含结束页，两轮22页，重试共享64次/300秒 | 原有限重试、30秒请求预留与60秒稳定间隔；不改源参数；配额已确认够用，超预算停止 |
| 文件/SQL/内存 | Raw/verification各1日，Silver候选1日，两层正式各1文件；既有样本24197/24173B | 共用SQL完整字段集合对账；DuckDB512MB/1线程/0spill、RSS768MiB；不Python计算资金或跨历史扫文件 |
| 发布与事务 | 每次一层一文件，共用moneyflow writer互斥、同文件系统replace、checkpoint读回 | 两层不声称整体事务；取消或退出保留已提交文件和现场，按原operation/date实际hash续跑 |
| 空间与耗时 | 沿用挂载/同设备/首次空闲64GiB；正常预期60秒等待加两请求及本机IO，隔离本机耗时需实测 | 源300秒/RSS/空间拒绝线不放宽；虚拟时钟不代表真实网络SLA |
| 正式范围 | 本轮正式Lake/PG/Prod/Tushare写入或请求、job/sensor/pool/reload/事件/分区操作均不执行 | 使用临时Lake/staging/SQLite及替身；495日历史保持原证明，后续另做历史只读预演 |

无新增env、Settings、数据库、run config或可调预算；check名称为run_contracts/moneyflow.py的固定身份常量，消费者仅本表assets/checks/catalog及测试，definitions加载生效，运营可从metadata/check/catalog查看。源字段、类型、路径、pool和所有预算继续来自原合同。复用统一候选/发布并显式指定dataset，不让源返回行决定数据集身份。

验收先跑概念真实归档fixture的隔离job及上述反例，回归行业、大盘和两表候选；再用原受保护runner执行catalog与static gates，隔离dg check defs，执行改动文件Ruff、src/tests致命检查、文档完整性和CodeGraph sync/status。不使用正式凭据或实例、不安装依赖。依据为§6/§10/§34、接入模板7A及性能规范；官方assets/partitions/checks文档与本地dg check参考已核对。

### 39.3 本轮代码与隔离结果，完整验收尚未关闭

独立资产/check/job/catalog已按§39.1落地，行业日更实现已整体迁到moneyflow_daily_update.py，所有代码/测试消费者显式传dataset，旧helper删除。没有修改源参数、字段、金额、正式Lake路径或子系统边界。

| 验收项 | 实际结果与限制 |
| --- | --- |
| 概念及行业definitions定向测试 | 64项通过；概念独立身份、字段保真、源失败、跨表receipt、检查归属、取消与Raw/Silver replace后续跑覆盖。之后修正测试侧schema读取为单次DESCRIBE，并在下列回归中复跑387行验收通过 |
| 相关回归 | 概念/行业候选、大盘definitions、行业sensor及历史事件，加更新后的387行概念job，共211项通过；源替身/虚拟时钟/临时Lake和SQLite，未访问正式资源 |
| 已归档来源样本 | 09-30全387行，源每轮/Raw/Silver为387/387/387，reject0；12字段逐值匹配fixture，industry_index为DECIMAL(24,4)，日期标准化正确；885955.TI的概念名、128家公司、净额19保留 |
| 原生检查 | 两层均SUCCEEDED/passed，同09-30分区，target storage_id/run_id/timestamp绑定对应物化；Silver只读同日已绿Raw，源请求合计两次，显式12字段及trade_date=20260930/limit2000/offset0 |
| 隔离规模与耗时 | Raw24534B、Silver24510B，均低于既有64KiB小文件门禁；两job总532.680ms，60秒稳定间隔由虚拟时钟推进，不能作为真实网络或正式SLA |
| Ruff | 所有本轮修改Python文件默认检查和src/tests的E9,F63,F7,F82通过 |
| 受保护catalog治理 | 第一批通过；第二批在本轮范围外stock_weekly_checks导入新增stock_weekly_file_checks时阻断，报ModuleNotFoundError。该新增周线文件未进入当前受保护源清单，不能计作全库通过 |
| 受保护static gates | 第一批读取本轮范围外新增prod_db/stock_weekly_adj_delivery.py被capability拒绝，PermissionError；未放宽门禁或补录周线清单 |
| 完整dg check defs | 隔离/private/tmp DAGSTER_HOME、无正式凭据、UV离线/no-sync执行，因本轮范围外stock_weekly_adj_run.py导入psutil而失败；项目现有环境未安装该套件，没有自行安装或修改周线实现 |

当前dev-interface另有未提交股票周线开发，相关文件在本轮执行期间继续变化。依据根AGENTS硬约束29，停止跨模块验收与下一切片，不创建分支/worktree、不撤销或修补他人改动、不绕过受保护runner。待该开发解决新增模块清单与环境依赖，再原样重跑catalog/static gates/完整defs，全部通过后才能关闭概念资产切片。当前只能确认本表代码和定向隔离测试通过，不能宣称完整Definitions验收通过、正式服务已加载或日更可启动。

结果、实际job证据、来源及修改清单见[本轮证据](../../reports/moneyflow_p4_cnt_ths_evidence_20261011.json)。原历史报告/清单保留原字节；正式Lake/Prod/PG/分区/event/sensor/job/pool写入、真实源请求和reload均0。下一步先解除上述全库验收阻塞；概念sensor和495日历史只读预演后置，P4仍开放、P5未进入。

### 39.4 第1步完整门禁复验（2026-10-11 上海22:48），尚未关闭

管理员批准只先做下一计划第1步：重跑受保护catalog、static gates和完整隔离defs，依据实际结果回填，不进入sensor或历史登记。概念资产提交为b2793920；复验时HEAD为b49d9cdc，周线开发已提交。概念切片13个代码/测试文件逐个hash与原证据一致，原34份资金流报告和清单保留原字节，既有64项定向与211项回归结果仍对应这些源文件；本轮未重复声称重新运行这些测试。

| 验收项 | 本次实际结果 | 当前原因 |
| --- | --- | --- |
| 完整隔离dg check defs | 退出0，All definitions loaded successfully | 临时DAGSTER_HOME、telemetry关闭、无正式凭据，UV离线/no-sync/no-download；上轮psutil阻塞已消失 |
| 受保护catalog治理 | 启动器退出1，第一批8项在collection阶段阻断，完成0项；子进程退出4 | test_asset_governance_contracts导入assets/stock_weekly.py，第46行需要stock_weekly_adj_run；该文件存在且已提交，但不在runner的consumer源清单，受保护导入报ModuleNotFoundError |
| 受保护static gates | 启动器退出1，第一批第一个测试失败，后续批次未执行 | test_confirmed_input_has_only_declared_physical_readers逐文件读取defs；新增prod_db/stock_weekly_adj_delivery.py不在相同源清单，受保护读取报PermissionError |

两个受保护入口各自原生自检通过且完成7个隔离负例，正式资源哨兵hash前后不变；这些不是catalog或完整static suite通过。直接核对runner的CONSUMER_SOURCE_FILES及source_files_for_scope，确认失败属于周线新增模块与受保护测试能力清单未同步，不能解释为套件未安装、源码文件不存在或资金流业务断言失败。下一步需由周线开发收齐新增模块的真实导入闭包，并在原受保护入口审计、同步精确清单，再重跑两项完整门禁；不允许给整个源码目录开放读取权限或绕开runner。完整defs已通过，除非源码再变，无需因另外两项失败重复运行。

本次只更新方案和[第1步复验证据](../../reports/moneyflow_p4_cnt_ths_acceptance_evidence_20261011.json)，未修改资金流或周线Python代码、测试策略、依赖和配置，也没有正式资源操作。周线现已提交，当前阻塞不再是§39.3所述的未提交工作区冲突；本轮批准范围是原样复验，未包含周线受保护能力清单迁移。依§39.2完整门禁验收条件停止后续切片，概念资产完整验收尚未关闭，P4仍开放，P5未进入。§39.3及旧失败日志保留，当前状态以本节为准。

### 39.5 第1步受保护源清单校准（2026-10-11，执行前约束）

管理员要求“提交，然后继续推进”，先将§39.4复验记录提交1a980036，再解除这两项门禁阻塞。本轮目标只关闭概念资产/check/job/catalog切片完整验收；不进入sensor、历史预演或正式操作。修改范围为受保护runner的CONSUMER_SOURCE_FILES及本节验收记录；资金流和周线业务实现、源参数、正式路径、配置、套件不变。

CodeGraph explore定位周线闭合批接收链，impact(source_files_for_scope)定位policy_for和run_isolation_child；同名搜索混入其他域，实际Python AST补核导入闭包。周线b49d9cdc新增6个源码文件，传递闭包49个，缺失集合恰为这6个：defs/prod_db/stock_weekly_adj_delivery.py、defs/run_contracts/stock_weekly_adj_delivery.py、defs/stock_weekly_adj_delivery.py、defs/stock_weekly_adj_feed.py、defs/stock_weekly_adj_run.py、defs/stock_weekly_file_checks.py。顶层无正式资源执行；唯一带调用的赋值为DeliveryHeader字段名tuple。只把这6个现存普通文件加入consumer精确读取清单，不用目录subpath，不自动发现或开放其他路径。

| 硬口径与代码点 | 正反验收及预算 |
| --- | --- |
| CONSUMER_SOURCE_FILES恰新增上述6项，其他scope和policy生成函数不变 | AST对比原清单与新清单，传递闭包无遗漏、无额外路径；比较其他scope清单及函数源码hash |
| 使用原受保护runner，不修改测试断言、用例数、连接替身或隔离策略 | 完整catalog和static gates原入口执行；各批原生隔离自检及7个负例，拒绝资源哨兵不变，零正式连接 |
| 仅本地源码和临时隔离产物，无正式Lake/PG/Prod/Tushare | 正式日期/对象/请求/分页/文件写入均0；临时产物/private/tmp，现有每批60秒/100MiB与隔离DuckDB预算不放宽 |
| 完整门禁全部通过才关闭资产切片 | 源清单变化后重新隔离完整dg check defs；Ruff、文档、diff和原35份历史报告hash检查；任何失败如实保留，不计为全库通过 |

测试清单是测试能力声明，不是新运营配置，不改变正式Definitions或主体依赖矩阵。验证可能暴露此前collection失败掩盖的其他断言问题，若出现需核对当前合同，不能改断言凑通过。最终结果待实际执行后回填，P4开放、P5未进入。

### 39.6 第1步完整验收收尾（2026-10-11）

按§39.5只补6个精确源文件路径，AST对比确认无删除项、无新增重复项，其他顶层语法树完全不变，policy_for、其他scope、测试选择与预算均未修改。顶层导入只形成定义，不执行周线闭合批接收。原缺失模块原因已修复，没有改测试业务断言或扩大正式资源权限。

| 验收项 | 实际结果 |
| --- | --- |
| 受保护catalog治理 | 完整2批，12项测试及492个subtests全部通过，批次进程累计5320ms |
| 受保护static gates | 完整15批，113项全部通过，批次进程累计23799ms；未跳过或xfail |
| 隔离与资源 | 17批各自原生自检及7个负例通过；拒绝资源哨兵hash前后不变，connection_count合计0；仍使用原sandbox-exec和受控临时资源 |
| 完整definitions | 临时DAGSTER_HOME、关闭telemetry、无正式凭据及UV离线/no-sync/no-download，完整dg check defs通过；另做最终源码hash前后核验 |
| 代码与文档检查 | runner默认Ruff、src/tests致命检查、文档完整性、diff检查及新增报告链接检查通过；CodeGraph sync/status完成 |
| 原证据与业务范围 | 原35份资金流报告和清单原字节保留；原概念资产12个其他代码/测试文件hash不变，runner变化仅上述6路径；没有新来源实测或正式操作 |

其他周线任务在本轮期间修改io/stock_weekly_raw.py和stock_weekly_adj_delivery.py，这两项非本轮修改、不提交或回退。本轮逐批核对受保护suite记录的全部source hash与当前源码一致；传递导入闭包仍恰缺原6项，最终defs验证记录前后hash一致。复验不能证明这些周线业务改动的业务正确性，只证明本次共享门禁及完整Definitions在对应源码状态通过。

至此moneyflow_cnt_ths独立资产/check/job/catalog切片完整验收关闭。§39.3～39.4的失败记录与旧日志保留，最新结果见[第1步收尾证据](../../reports/moneyflow_p4_cnt_ths_asset_closeout_evidence_20261011.json)。本轮仅测试清单、两份原设计文档及新证据变化，主体边界和依赖矩阵不变；P4整体仍开放、P5未进入。下一独立切片为概念三个STOPPED sensor及495日历史有界只读预演；尚未实现或执行，不登记分区/event、不加载代码、不配置pool、不启用sensor、不跑正式job。

## 40. P4 同花顺概念 sensor 与历史只读预演（2026-10-11，执行前对账）

管理员要求“提交，继续推进后续开发”；§39收尾已提交96475a31。本轮只实现moneyflow_cnt_ths三sensor及只读历史预演。依据§6独立实施卡、§10/P4范围、§35已验收的行业共用能力和接入模板7A；历史沿用P3冻结495实际来源日/192009行/990文件，不补源缺口、不重导历史、不实现本表APPLY或冻结执行清单。正式Lake与既有Dagster PG只读审计遵守持续授权，禁止初始化实例、DDL和其他正式写入。

### 40.1 硬口径、消费者与配置审计

| 硬口径 | 代码落点与影响面 | 正反验收 |
| --- | --- | --- |
| 三个独立STOPPED sensor | sensors/moneyflow_cnt_ths_sensor.py；cn_a_moneyflow_cnt_ths_trade_day_sensor及本表Raw/Silver两job名加_sensor | 600秒间隔、quote_data及对应partition/raw/silver tags、专属分区；不依赖tushare资源、不提交其他表job |
| 上海22:00登记当日，历史起点2024-09-10 | register_moneyflow_trade_days固定概念合同；更新沿用2026-10-01之后最近10个SSE日 | 22点前不造当日键；历史可恢复；22点后当日优先加最多1个旧缺日；非交易日不造当日键；更新22点前不读event/文件 |
| 每tick最多1run且cursor不串表/层 | MoneyflowAutomationContract增加固定概念身份，复用moneyflow_update_selection与batch_moneyflow_readiness；新增概念readiness适配器 | current day优先、缺分区/active/坏check/hash/饱和阻断，有限6次持久化attempt与请求重放；行业或大盘cursor、Raw到Silver cursor均拒绝 |
| 绿check准确归属与实际hash | 两层实际storage_id/run_id/timestamp匹配；本表专属check名字、文件与上游hash | 单日原生job/check验收；错归属、坏/缺文件/symlink/超过64KiB、Raw更新后旧Silver阻断；Silver仅绿Raw新hash可重建 |
| 历史只读取冻结概念证明 | bootstrap/moneyflow_cnt_ths_event_preview.py固定绑定；共用proof/state/SQL验收；概念entry显式携带源每日row_count | 错cohort、未闭合/篡改控制、缺/改正式文件拒绝；原生差集只查询本表，不复用行业/大盘事件；重复预演文件和事件不变 |
| 三表历史revision各自固定 | event_revision改为三表显式映射，原大盘和行业值及所有现行入口保持不变，概念为concept_moneyflow_ths_history_events_v1 | 三值逐项断言；未知数据集或篡改身份拒绝；大盘/行业sensor、preview和event执行器回归 |
| 身份治理同步，不绕开门禁 | 静态sensor身份增加3项；受保护runner精确增加新sensor/readiness/preview源码路径 | 完整sensor-tags、catalog、static和隔离defs；不放宽目录权限、跳过测试或改预算 |

CodeGraph explore/impact审计MoneyflowAutomationContract及行业入口，实际源码补核全部合同消费者：sensor选择器、delivery_readiness、两表preview/proof、history_events的plan/APPLY和其原适配器、相关测试与受保护runner。共享验证允许增加固定概念合同，但本轮没有概念APPLY适配器或正式执行入口。共用proof只给ind_ths/cnt_ths提供每日row_count，大盘返回形状不变；不新增通用Definitions factory、协议副本或兼容链。

配置与身份继续来自run_contracts/moneyflow.py、moneyflow_automation.py、paths.py及既有resources。新增的是固定概念asset/check/job/partition/起点/中文标签和revision身份，不是运营可调配置；无env、Settings、DB、run config或预算新增，消费者如上，definitions加载生效，运营从sensor tags/cursor和预演报告可见。600秒、22点、10日、6次、100记录、20最近来源日、100日批次、120秒unit、512MB/1线程/0spill与768MiB RSS均保留。

### 40.2 性能与真实只读验收边界

| 范围 | 已知规模/预算 | 验收与拒绝策略 |
| --- | --- | --- |
| 分区注册 | 1个SSE日历文件、原helper最多3 SQL/2分区读，返回最多2键，分区总数最多20000 | 仅SensorResult；隔离验证当日优先、历史起点及22点/假日，不在正式实例evaluate_tick |
| Raw tick | 最近10日，日历1 SQL；最多7 native读取/每查询100记录，hash最多10文件/640KiB，最多1run | 源请求0；饱和/坏check/hash/超过64KiB停止，不读历史兜底 |
| Silver tick | 最近10日，日历1 SQL、2 active+1分区+4 readiness=7 native读取；最多20文件/1280KiB | 387行真实归档样本改为明确合成未来日期，实际20个job验证；目标<1秒，测试上界2秒，cursor目标2KiB/硬上界8KiB，tick不请求源 |
| 历史冻结预演 | 495实际来源日/192009行/26日期unit、990文件；实际字节和控制文件数正式只读读回 | 所有文件hash匹配冻结证明；SQL仅深检最近20来源日两层40文件/20组标准化对账；每unit120秒、RSS768MiB、DuckDB512MB/1线程/0spill；未知/变更证明拒绝 |
| 原生历史差集 | 1专属分区读+2×ceil(495/100)物化查询+2最近check查询，共13 native读取 | 不逐日readiness；最多预期495键+990物化+40checks=1525工作项/1030事件，必须读回实际差集，不预填 |
| 读写与事务 | 正式Prod/Tushare请求0；正式Lake/staging/PG写入0；既有PG read-only/10秒statement timeout/关闭autocreate | 报告只写/private/tmp或repo；不锁写、不保存cursor、不登记事件/分区、不改pool或reload，不以只读通过表示正式服务已加载 |

隔离测试使用临时Lake/staging/SQLite和fake源/时钟，保留真实归档387行全字段事实；注册/选择/重试/cursor与原生物化归属反例均须通过。真实只读验收仅运行固定概念preview入口及已有默认read-only instance适配器。官方[sensor文档](https://dagster.io/docs/guides/automate/sensors)及dagster-expert参考已核对默认STOPPED、最小间隔和run-key语义，实际SDK通过隔离原生记录验证。结果执行后回填；整个P4保持开放，P5未进入。

### 40.3 本切片验收通过，历史正式登记后置

三个独立sensor已实现且默认STOPPED：cn_a_moneyflow_cnt_ths_trade_day_sensor、raw_tushare_moneyflow_cnt_ths_update_job_sensor、silver_moneyflow_cnt_ths_update_job_sensor。注册器上海22:00后优先当天最多再补1个历史漏日；Raw/Silver更新继续使用最近10个实际SSE日与各自专属job/check/partition/cursor，tick不接触Tushare。概念history revision为独立固定值，原大盘/行业值与入口保留；没有新增可调配置或正式执行入口。

| 验收项 | 实际结果与限制 |
| --- | --- |
| 概念sensor/身份/重试/readiness | 30项通过；包括真实原生job/check、21点不读资源、22点/假日/历史起点、六次持久化attempt、重复run-key及跨表/跨层cursor、篡改固定合同拒绝 |
| 概念历史preview | 修正测试误用行业check常量后15项全部通过；坏文件/控制/cohort/symlink、失败或旧check目标阻断，行业/大盘事件不复用，源每日row_count保真。首次3项失败日志保留，修正的是测试归属，未改业务断言或放宽proof/state |
| 大盘、行业及通用合同回归 | 两表sensor、preview、历史plan/APPLY及sensor-tags共147项通过，135.82秒；临时文件/SQLite、fake源/时钟；没有正式运行 |
| 10日概念热路径 | 用真实归档387行字段、明确合成未来日期及20个实际隔离job；Silver tick 22.914ms，日历1 SQL、native读取7次（2 active/1 partition/2 mat/2 check）、20文件490440B、cursor595B，tick源请求0；不是新源端请求或正式SLA |
| 正式冻结历史纯只读 | 495实际来源日、192009行、26日期unit，990文件24402584B全部匹配；54控制前后不变；最近20来源日两层40文件/20组标准化SQL对账通过 |
| 正式原生差集与成本 | 待登记495专属分区，Raw/Silver各495物化和20最近check；可复用事件0，合计1525工作项/1030事件。13次native读取（1 partition/10 mat/2 check），0.8409秒，formal_writes=0 |
| 完整治理与源码 | 受保护catalog12项及492 subtests、static113项/15批均通过；17批原生自检/各7负例及拒绝哨兵不变；完整隔离defs通过且前后源码hash一致；9个本轮Python文件Ruff、src/tests致命检查、文档/diff/链接、CodeGraph sync/status通过 |

CodeGraph explore/impact及直接源码完成共享合同全部消费者审计；变更限3个固定概念适配器、共享automation合同/proof entry、2个新测试、静态身份/受保护源清单及两份原设计文档。大盘/行业preview形状及历史revision不变，主体依赖矩阵、Prod DatasetDefinition、API/CLI、源参数和字段不变。受保护suite记录的所有source hash与当前一致；其他周线工作原样保留。原36份资金流报告和清单保留原字节，详情见[概念自动化证据](../../reports/moneyflow_p4_cnt_ths_automation_evidence_20261011.json)。

正式动作只有既有PG和Lake/staging的只读预演，没有Prod/Tushare请求、Parquet或正式staging写入、动态分区/event/job/sensor/pool变更、依赖安装或reload。不能把源码及隔离defs通过当成正式服务已加载或sensor可启用。本切片关闭，P4仍开放、P5未进入；下一独立开发切片为概念可恢复历史事件执行器及两日/495日冻结清单，正式样本及全量APPLY各按精确清单批准。


## 41. P4 同花顺概念历史登记执行器与冻结清单（2026-10-11，执行前）

管理员要求提交并推进概念历史登记执行器、两日样本和全量清单；上一切片已提交76d61613。本轮批准开发、隔离验收和正式只读计划生成，未包含正式APPLY。沿用§36已验收的共享协议，为概念增加固定event-plan和events适配器；原市场、行业入口和清单保持原语义。

### 41.1 硬口径、消费者与验收映射

| 约束 | 实现与消费者 | 本轮验收 |
| --- | --- | --- |
| 单独概念数据集，仅冻结P3实际来源日期，不补源缺口；截止2026-09-30 | moneyflow_cnt_ths_event_plan固定CONCEPT_THS合同→共享moneyflow_event_plan→proof | 伪造/重复日期拒绝；跨市场、行业、概念清单拒绝；两日和全495日精确清单 |
| 原生分区、物化和check为续跑事实，checkpoint只作进度；默认apply=False | moneyflow_cnt_ths_events→moneyflow_history_events；同实例身份与plan_hash绑定 | 默认0写入、取消、真实子进程退出后续跑、checkpoint失败不丢已提交事件、幂等重放 |
| 概念每一天行数以冻结Prod证明为准，不固定387；12字段，Silver只标准化 | 共享执行器已有_row_count；扩展两处行业专属行数守卫到概念；metadata/check/readiness消费者 | 两日386/387隔离行数；重算hash伪造行数拒绝、旧事件错误行数拒绝、SQL计数不符不发布绿check |
| Raw/Silver全部历史物化，只有最近20个实际来源日补blocking checks | 共享分阶段执行器、原生storage_id/run_id/timestamp精确绑定 | 495日容量：495分区+990物化+40检查；旧日不能伪造check成功 |
| 冻结证明先核验全990文件和54控制，APPLY前后再次核验；冲突/活跃run停止 | proof/validate/native state/既有writer lock | 文件、控制、计划、实例、锁、活跃run、预算和取消反例；正式只读不创建events目录 |

CodeGraph explore/impact已用于共享入口审计；分词混入同名report/plan，impact未连通两个固定适配器，因此直接核验共享plan、writer、proof、市场/行业适配器、readiness、原生存储及测试。全部现行消费者是orchestrator内的固定历史适配器和隔离测试，不涉及Prod DatasetDefinition、request builder、API、前端或主体依赖矩阵。

### 41.2 配置、成本及执行边界

不新增配置或CLI。固定概念身份取已提交CONCEPT_THS_MONEYFLOW_AUTOMATION，budget仍取run_contracts/moneyflow.py：100日/批、4096工作项、600秒/次、120秒/unit、256 metadata reads；DuckDB512MB/1线程/no-spill、RSS768MiB、20近期来源日、每查询100条，来源请求0、Parquet写入0。既有预算只由plan、writer、proof消费，修改后需重新冻结计划；本轮不改变默认值、环境/Settings/数据库、pool或sensor配置。

两日样本选择2026-09-29与2026-09-30，预计2分区+4物化+4检查=10工作项/8事件；全量495日/192009概念记录，预计1525工作项/1030事件。全量native预演13次元数据读取，APPLY隔离容量预计141次读取、1050次控制原子保存；深SQL只20组。上述为执行前估算，须以本轮真实只读与隔离测量回填，不承诺正式PostgreSQL耗时。单事件独立提交、分区每100日一批，无全历史数据库事务；逐事件保存进度，源端行数与SQL不符/预算耗尽fail closed。checkpoint原子os.replace并fsync，退出后保留已提交事件，续跑同一清单、同一实例；不能改checkpoint跳过工作。

两份新计划只写仓库reports，本轮不写正式staging/events、Lake、Dagster原生分区或事件。正式样本APPLY和全量APPLY分别按精确清单批准，维护核验/reload/pool/sensor启用和P5另行推进。验收覆盖新concept suite、旧两表plan/APPLY回归、受保护catalog/static gates、完整隔离defs、Ruff、文档/diff/链接及旧报告hash保留。


### 41.3 执行器、恢复与容量验收完成

概念固定适配器为moneyflow_cnt_ths_event_plan.py与moneyflow_cnt_ths_events.py。前者绑定concept revision/identity/proof，后者默认只读；共享writer的既有事件行数与近期SQL计数守卫均覆盖行业、概念。Raw/Silver物化记录逐日来源行数、12字段、文件hash、cohort/cutoff，近期blocking检查绑定storage_id/run_id/timestamp。时间输入、执行单位、freshness分别沿§6卡片、P3实际来源日和近期检查，不把源缺口造成功。

| 验收 | 实际结果 |
| --- | --- |
| 概念恢复 | 46项通过，66.45秒；默认只读、逐事件取消、真实子进程退出、checkpoint缺失/伪造/保存失败、进度回调失败、续跑、幂等 |
| 行数与独立身份 | 两日386/387行物化/check读回正确；七种假计数、旧事件错计数、SQL错计数、市场/行业交叉清单拒绝；只写概念专属分区/资产 |
| 旧市场/行业 | 79项通过，114.07秒；正式旧四份冻结清单重新构造相等，文件字节和plan_hash不变 |
| 495日容量 | 归档387行fixture改为495个明确合成日期，共191565行；临时SQLite完成495分区+990物化+40检查=1525项；旧日不造check，重放不重复；来源与Parquet不改 |
| 成本 | 隔离APPLY7.8053秒，141次native读取，日期批≤100；RSS558841856B（约533MiB）；1049次控制原子保存合计0.5699秒、最慢10.752ms；不作为正式PG耗时承诺 |
| 完整门禁 | 首轮及第一次刷新catalog12项/492 subtests、static113项/15批、完整隔离dg check defs通过；17批各7负例、正式连接0、拒绝哨兵不变；5个Python文件Ruff和src/tests致命检查通过。随后其他源码再次变化，当前完整门禁待复验，不能关闭切片 |

首次concept suite45项通过，容量用例因§41.2多估一次保存失败。494和495日都是5个分区批，新增1日只增加2条物化保存；准确模型为1030事件+5分区批+11批读回+plan/初始/最终进度3次=1049。只改测试预期并重跑全部46项，未改产品行为或放宽门禁，旧日志保留。

首次完整门禁后，另一周线任务改了defs/prod_db/stock_weekly_adj_delivery.py，无新增导入，资金流代码/清单无变化。保留其修改，重跑catalog、static和完整defs全部通过；刷新时suite源hash和defs前后hash一致。随后周线继续改动defs/bootstrap/stock_weekly_history.py、defs/bootstrap/stock_weekly_history_cli.py及defs/prod_db/stock_weekly_adj_delivery.py，刷新证据已不能代表当前工作区。概念本轮5个Python源hash不变，46/79项及冻结清单仍有效，但完整门禁未关闭。按根AGENTS第29条不另建分支/worktree绕过，停止下一阶段，待周线源码稳定后重新做完整隔离验收；保留两轮成功日志和当前差异，不能反复追赶可变源码后预填通过。原37份资金流报告/清单原样保留，详见[执行器证据](../../reports/moneyflow_p4_cnt_ths_event_registration_evidence_20261011.json)。

计划对账：固定日期/身份/只读由adapter、plan校验及跨表/假日期反例证明；行数由proof、metadata、两个writer守卫及数量反例证明；20日check/100日批由容量证明；原生续跑由取消、实际退出、checkpoint失败/重放证明；冻结文件和预算由文件/控制/实例/活跃run/时间/读取上限反例及正式只读证明。§6卡片、§36和§41继续覆盖接入模板的来源、时间、执行、资源、性能和恢复。没有新增API/CLI、资源、配置、asset/check/job/sensor定义或主体依赖矩阵，P4仍开放、P5未进入。

### 41.4 精确清单与下一阶段边界

上海2026-10-11 23:51生成；既有goldenshare_dagster PG默认只读、禁止自动DDL，并禁止分区/event写入API。operation=history-full-20261009，cutoff=2026-09-30，cohort_hash=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618。proof验证990文件24402584B、54控制及最近20来源日标准化对账。两份计划仅保存仓库reports，逐份读回并重构相等，正式staging/events库存前后相同，正式写入0。

| 清单 | 精确范围与当前缺口 | plan_hash |
| --- | --- | --- |
| [两日样本](../../reports/moneyflow_p4_cnt_ths_event_registration_sample_plan_20261011.json) | 2026-09-29、09-30，各387行，共774行；2分区+4物化+4检查=10项/8事件 | 728f979259727100dab6bf7598a491f64a7fd8254e3255ddfa85e93de6426d5b |
| [全量](../../reports/moneyflow_p4_cnt_ths_event_registration_full_plan_20261011.json) | 2024-09-10～2026-09-30的495个精确来源日，192009行，逐日379～395行；495分区+990物化+最近20日40检查=1525项/1030事件 | ff4a6fd4ab4dc4f98eb1ee479c9938a6d3076d0d95949455211f51b2c1329c77 |

样本文件13761B、生成0.4961秒、预检0.3922秒/7次native读取；全量271926B、生成0.2933秒、预检0.4489秒/15次读取，均含2次active查询。旧四份清单校验及新清单生成/预检/重构合计4.0325秒。样本完成后全量按原生事实差分，预计剩493分区+986物化+36检查=1515项/1022事件；保留完整全量清单，不改hash或范围。

下一步先待并行周线工作区稳定，完整复验当前catalog/static/defs；全部通过后才按两日精确清单准入正式样本，写前核验本表三个sensor的持久化状态、两job无active run、当前源码hash/同一实例、无其他人工writer和维护窗口；隔离defs不能替代正式维护核验。样本完成后读回四条check的partition/target、两日两层readiness与物理证明，再独立准入全量。正式PG成本、正式check/readiness和sensor实际加载状态尚未验收。不删除原生事件、不手改checkpoint、不重建Lake或引入备份，异常续跑同一plan_hash。

从lake_console/orchestrator目录做默认只读样本预检：

```bash
.venv/bin/python3 -B - <<'PY'
import json
from pathlib import Path
from orchestrator.defs.bootstrap.daily_basic_event_instance import daily_basic_event_instance
from orchestrator.defs.bootstrap.moneyflow_cnt_ths_events import report_concept_moneyflow_ths_history_events
plan = json.loads(Path('../reports/moneyflow_p4_cnt_ths_event_registration_sample_plan_20261011.json').read_text())
assert plan['plan_hash'] == '728f979259727100dab6bf7598a491f64a7fd8254e3255ddfa85e93de6426d5b'
with daily_basic_event_instance() as instance:
    print(report_concept_moneyflow_ths_history_events(instance=instance, plan=plan))
PY
```

仅获准该清单且维护核验通过后，才在同一入口显式用daily_basic_event_instance(writable=True)、apply=True及逐unit progress。此为后续约束，本轮未执行；不新增CLI、不包含reload、pool、sensor启用、日更job、P5或其他四表。


2026-10-12收尾附记：本轮两份文档的资金流报告链接、新计划canonical hash/文件hash、原37份报告保留与git diff --check均通过。全仓check_docs_integrity在其他任务未跟踪的docs/product/xxm-macd-structure-research-v1.md报3处dead-absolute-links（带行号路径），不属于本轮文档；不改该任务文件，也不把全仓门禁记为通过。当前概念执行器、测试和两份冻结清单已完成，本开发切片因共享周线源码变动及全仓文档门禁未关闭；稳定工作区后复验，不进入正式APPLY。


### 41.5 完整门禁复验与收尾范围（2026-10-12，修改前）

管理员要求提交上轮并检查阻塞、继续完整门禁和收尾。10文件已提交f872faaa，不动旧两份冻结计划或已归档证据。当前709个DG Python源码在约90秒观察内hash相等，3处研究文档链接阻塞已由其他任务修正，全仓文档初检通过；这只证明本次观察稳定，不能承诺之后不变。

受保护catalog完整初检通过，static第一批因读取新defs/bootstrap/stock_weekly_adj_bootstrap.py被sandbox拒绝而停止。CodeGraph explore/impact已预审，分词结果混入其他weekly符号，直接核验CLI/history到新bootstrap的真实导入，以及32文件传递导入闭包；只有该新模块不在CONSUMER_SOURCE_FILES。它在模块导入时定义函数/类，不创建reader或执行Prod/文件写入；这些操作只在显式调用路径。修改仅在stock_suspend_confirmed_test_runner.py的consumer固定源码元组增加该一个精确只读路径，policy模板、其他scope、网络/正式资源拒绝区、预算、测试断言不改，不允许目录级读取或安装。

随后复验完整catalog/static/isolated dg check defs。完整当前源码与受保护runner、suite前后hash必须一致；若别的任务继续改共享源码，不能把旧suite输出记作当前通过。资金流业务、测试源码和旧40份报告/计划必须hash不变；新样本和全量冻结计划只读重构/预演，正式分区/event/Lake/staging写入、reload/pool/sensor/job动作均0。来源字段/日期/配置和主体依赖矩阵不变。Ruff、致命检查、文档/diff/报告链接和CodeGraph同步作辅助门禁，不能替代完整native与defs验收。


### 41.6 完整当前门禁通过，概念历史登记开发切片关闭（2026-10-12）

§41.5初始catalog12项/492 subtests通过，static第一批的PermissionError已精确定位为新周线bootstrap源码读取清单遗漏。只给CONSUMER_SOURCE_FILES增加defs/bootstrap/stock_weekly_adj_bootstrap.py一条路径，其32文件导入闭包其余文件已在清单中；完整catalog重新12项/492 subtests通过，static完整113项/15批通过。17批各7个原生负例、拒绝哨兵不变、正式连接0；完整隔离dg check defs退出0，UV离线/no-sync/no-download、无正式凭据、telemetry关闭。runner完整Ruff、全src/tests致命检查、CodeGraph sync/status、文档/diff/报告链接通过。旧3处研究文档链接由其他任务修正，本轮没有改其文件。

工作区仍有其他任务的未提交文件，不声称干净。初始约90秒709个DG源码hash无变化；随后整个门禁前后1133份DG源码及顶层测试快照相等，受保护各批suite源码和defs前后hash均与当前工作区匹配。验收基于HEAD f872faaa与当时周线未提交源码的完整hash事实，不仅靠HEAD判断版本，不承诺后续共享工作区不会再变。当前没有脏文件阻塞，§41.3～4及10-12附记的旧阻塞解除，保留原失败/刷新记录。概念业务及测试源码未改，46项恢复、79项市场/行业回归和495日容量沿用已提交且hash一致的证据，本轮未重复跑这些无变化的业务测试。

两份原冻结计划在既有正式PG只读重构和预演通过，文件及plan_hash不变，正式events控制库存不变；样本2分区/4物化/4检查，7次native读取，1.0588秒；全量495分区/990物化/40检查，15次读取，0.4866秒。计时包括库存核对，不能外推正式APPLY。proof重新核验冻结文件/控制及最近20来源日完整标准化；两日/全量仍未登记，现有completed=0。原40份资金流报告和清单均逐字保留。当前原生事实和源码身份、具体批次及初始失败保留在[完整收尾证据](../../reports/moneyflow_p4_cnt_ths_event_registration_closeout_evidence_20261012.json)。

计划对账：§41.1～2日期/身份/来源行数/恢复/批次/check口径继续由已提交业务与46/79项证据证明；§41.5新增当前全门禁与精确源码只读能力由当前17批负例和完整defs证明；物理证明/计划不改由本轮正式只读预演、canonical hash及旧40份文件hash证明。没有业务边界/主体依赖矩阵、API/CLI、配置、源参数、正式Lake路径变更，唯一代码改动为受保护reader源码清单，不涉及周线业务。正式分区/event/Lake/staging写入、job/sensor、状态/cursor/pool/reload、来源请求和安装均0。

**概念历史登记执行器与冻结清单开发切片现已关闭。** 整个P4仍开放，P5未进入；正式样本和全量各后置精确清单批准。下一阶段具备先执行2026-09-29/30两日正式登记的技术条件，执行前仍核验三个sensor实际持久化状态、两job无active run、当前代码身份、独占writer及维护窗口。样本后读回4条check的partition/target和两日两层readiness/物理证明，再单独进入495日全量；预计复用样本后剩493分区/986物化/36检查=1515项/1022事件。未批准正式APPLY，本轮不推进这些动作，也不把“开发收尾”记成P4或P5完成。


## 42. moneyflow_cnt_ths两日正式登记样本（2026-10-12）

### 42.1 执行前范围、授权与门禁

管理员在§41.6开发收尾后要求“提交吧，然后继续推进”，按上轮明确的下一阶段执行两日正式登记；收尾4文件已提交9ecce77e。本次只执行已冻结sample_plan_20261011.json，plan_hash=728f979259727100dab6bf7598a491f64a7fd8254e3255ddfa85e93de6426d5b，日期2026-09-29/30，每日387行。范围为2个cn_a_moneyflow_cnt_ths_trade_days动态分区、Raw/Silver各2条materialization、各2条blocking check，共10项/8事件。495日全量APPLY、sensor启用/evaluation、job、reload、pool、来源请求及Parquet改写不在本次范围。

当前CodeGraph explore已追到固定concept adapter、共享登记引擎、readiness及正式instance adapter；没有新增产品代码、配置、资产契约或主体依赖。当前工作区另有4个周线源码变化，与旧完整门禁快照不同；不把旧全门禁记作当前全仓通过。实际样本进程加载的资金流及依赖源码逐文件核对旧验收hash及9ecce77e提交，执行前后再次核验；不改其他任务文件。

只读预检实际completed=0、缺2键/4物化/4检查，7次helper native读、0.8165秒。当前3个sensor定义默认STOPPED，实际原生状态须未启用；两job须无active run。既有PG adapter默认read-only、自动DDL关闭、单SQL 10秒；APPLY显式writable=True，writer独占并再次校验计划、来源控制、全部物理hash与active run。sensor写前/写后只读核对，不更改状态。API依据继续采用[Dagster asset checks文档](https://docs.dagster.io/guides/test/asset-checks)与现有已验收runless实现，当前不改平台API。

| 成本或门禁 | 本次口径 |
| --- | --- |
| 来源与文件 | Prod/Tushare请求0；复核P3冻结495日192009行、990文件24402584字节及54控制hash；最近20来源日40层文件SQL与20次标准化比较 |
| 业务写入 | 2分区/4物化/4检查，逐独立事件提交，不使用全历史长事务；Parquet写入0 |
| staging | 仅现有moneyflow/history-full-20261009/events/样本plan_hash的冻结plan、原子checkpoint及writer锁；无备份/Kopia |
| 单批与上限 | 100日/批、4096项、600秒总预算、120秒单unit、256次helper native读、DuckDB 512MB单线程不spill、RSS 768MiB |
| 耗时与磁盘 | 正式样本实测后记录，不把只读耗时外推APPLY或全量；执行前staging空闲必须大于32MiB |
| 拒绝条件 | 源码/身份/hash漂移、sensor启用、active job、writer冲突、预算超限或检查失败立即停止；不删事件、不编辑checkpoint，按相同清单和native事实续跑 |
| 验收 | 精确读回4条check的partition及storage_id/run_id/timestamp target、774行来源/物化/checked计数、两日两层readiness；相同样本幂等重放0新键/事件；原全量清单剩493键/986物化/36检查 |

执行目录/命令：/Users/congming/github/goldenshare/lake_console/orchestrator，使用现有.venv，不同步或安装依赖。临时driver只负责固定清单调用和证据读回，不进入正式Definitions；本轮责任人为当前任务，归档后不再作为新的生产入口维护。默认命令只读，正式命令增加--apply。INSTANCE_HOME固定/Users/congming/.goldenshare/dagster_home，连接现有本机goldenshare_dagster；不启动完整instance或正式job。

```bash
.venv/bin/python3 -B /private/tmp/moneyflow-p4-cnt-ths-formal-sample-20261012.py
.venv/bin/python3 -B /private/tmp/moneyflow-p4-cnt-ths-formal-sample-20261012.py --apply
```

本节先记录获准范围与门禁，不预填执行成功。正式结果另见§42.2。


### 42.2 正式样本与幂等重放验收通过

正式预检扫描106条native sensor状态，三个概念sensor均无持久化启用记录，当前导入定义默认STOPPED；APPLY前、后及重放后状态相同。两个概念job的active-run guard在预检和执行各批均通过。52份资金流/正式adapter源码与前轮验收hash一致，实际加载83份项目源码前后均与9ecce77e及原验收hash相等。其他任务继续改周线文件，本次没有加载其bootstrap/候选/提升/CLI链；没有把先前1133源码全仓门禁称作当前完整通过，也没有修改它们。

新增2个动态分区、4条物化和4条blocking检查，10/10项完成。两日每层row_count/source_row_count/checked_row_count均387，合计每层774行；4条check均SUCCEEDED且passed/blocking，partition与日期相同，target.storage_id/run_id/timestamp逐条匹配对应物化。Raw与Silver两日4个readiness均ready。APPLY引擎实测1.4522秒、53次helper native读取、60次进度回调，完成量单调；读取计数不包含外部sensor/pre/postflight或native写内部SQL，不把样本耗时外推全量SLA。

相同冻结样本再以APPLY重放，完成仍10/10，新增分区0、事件0；之后事件ID/时间/行数与第一次读回一致，sensor状态未改变，原子checkpoint为complete/100%。样本及原495日计划文件/hash不变；重新构建物理证明核对全部990个文件和54个来源控制，最近20来源日标准化SQL通过，Parquet改写0。

原全量冻结清单保持plan_hash=ff4a6fd4ab4dc4f98eb1ee479c9938a6d3076d0d95949455211f51b2c1329c77，正式只读预演completed=10/1525；后续只需493键/986物化/36检查=1515项、1022新事件，复用样本4条物化和4条check，不重生成或删减全量清单。全量APPLY本轮未执行，须下一阶段单独批准；P4整体仍开放，P5未进入。

本轮执行完整结果见[两日正式样本证据](../../reports/moneyflow_p4_cnt_ths_event_registration_formal_sample_evidence_20261012.json)。旧41份报告与冻结清单按9ecce77e提交逐字保留。文档对账：§42.1精确范围和身份由固定adapter/原计划验证，维护状态由native读取与active guard，文件事实由冻结proof/标准化SQL，事件正确性由native精确target读回与batch readiness，幂等由同清单真实APPLY重放证明。来源/API/CLI/配置/主体依赖矩阵和正式Lake路径均不改，本次只增DG事件、样本staging checkpoint、两份文档及新报告；job/sensor/reload/pool/来源请求/安装均0。


## 43. moneyflow_cnt_ths冻结全量历史登记与收尾（2026-10-12）

### 43.1 执行前范围、授权与性能门禁

管理员明确要求“提交修改，然后批准按冻结全量清单执行，继续推进moneyflow_cnt_ths的全量历史登记和收尾”。§42两日样本的3文件已提交a9973d19。只执行原full_plan_20261011.json，文件SHA256=37860dae065606ccf28ca901cf512c2e4ad4887f2aaecb21b5226ef3640fa400，plan_hash=ff4a6fd4ab4dc4f98eb1ee479c9938a6d3076d0d95949455211f51b2c1329c77；不重生成或删改冻结清单。

目标是2024-09-10至2026-09-30的495个实际来源日，192009行/层，Raw/Silver共990文件、24402584字节，54个来源控制，cohort=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618。全部历史登记495分区/990物化，只为清单最近20个来源日登记40条blocking check，共1525项；不能把更早日期“未补check”记成已ready，也不能补造来源历史缺口。

全量只读预检completed=10，缺493键/986物化/36检查，需写1515项/1022事件，15次helper native读、0.8326秒。样本4物化及4check需保留原ID、target与timestamp。三个sensor原生状态未启用、当前定义默认STOPPED，两个job active guard通过。52份资金流/adapter源码及实际加载83份项目源码仍与旧验收和a9973d19提交一致；CodeGraph explore已核对固定adapter到共享引擎和readiness的边界。其他任务周线脏文件与文档提交保留，不将旧全仓门禁称作当前通过。

初次driver在连接前因其他任务文档提交720ce5a9使HEAD变化而停止，正式读写0。校正临时driver的版本门禁：要求a9973d19是HEAD祖先，实际加载源码继续逐文件对照该提交和验收hash，执行前后再核验。允许无关文档提交不降低业务源码身份门禁；不存在产品代码、契约或配置变化。

| 项目 | 本次范围与上限 |
| --- | --- |
| 来源、文件与SQL | Prod/Tushare请求0；全部990文件/54控制hash；仅最近20来源日40层文件及20次Raw/Silver标准化深核，不做495日逐日readiness深扫 |
| DG写入 | 最多493分区/986物化/36检查；已完成样本复用；每独立事件提交，100日期/批，原清单与native事实驱动幂等续跑 |
| staging与Lake | 仅既有moneyflow/history-full-20261009/events/全量plan_hash的plan、原子checkpoint与writer锁；Parquet写入0、无Kopia/备份 |
| 执行上限 | 1525项低于4096项；总600秒、单unit120秒、helper native读256次；PG单SQL10秒，DuckDB512MB/1线程/no-spill，RSS768MiB |
| 预计成本 | 相同引擎行业494日实测17.3009秒/141读，仅作为约几十秒的规模参考；本概念全量以实际测量为准，不能由样本外推SLA；staging空闲须大于32MiB |
| 拒绝与恢复 | 身份/hash漂移、sensor启用、active job、writer冲突、文件/检查错误或预算耗尽即停止，不删除已提交事件、不改checkpoint；同清单读native事实继续，不能扩大范围或放宽预算 |
| 收尾 | 495键/990物化/最近20日40check精确集合与逐项target、日期行数正确；最近20日每10日一批readiness共40项；真实全量APPLY重放0新键/事件；全部物理/control/样本事实不变 |

执行目录/正式instance仍为§42.1的orchestrator及/Users/congming/.goldenshare/dagster_home、本机既有goldenshare_dagster。现有.venv与默认只读adapter，不安装、同步依赖或自动DDL。命令如下，APPLY仅调用当前固定concept入口，不经code-location job/sensor；进度逐项输出、取消/退出后按持久化native事实恢复。临时driver归档后不作为新正式入口维护。

```bash
.venv/bin/python3 -B /private/tmp/moneyflow-p4-cnt-ths-formal-full-20261012.py
.venv/bin/python3 -B /private/tmp/moneyflow-p4-cnt-ths-formal-full-20261012.py --apply
```

本轮不启用sensor、触发job、reload、改pool、请求源、改写Parquet或推进其他数据集；P4整体仍开放，P5未进入。成功结果另记§43.2，不预填完成。


### 43.2 全495日正式登记及收尾通过

本次补493个动态分区、986条物化和36条blocking check，共1515项/1022新事件，累计1525/1525项完成。最终cn_a_moneyflow_cnt_ths_trade_days与冻结495个来源日期集合一致，Raw/Silver累计990条物化，每日row_count和source_row_count均与冻结date_counts相同，合计每层192009行。最近20来源日40条检查均SUCCEEDED、passed且blocking，partition逐条匹配日期，target.storage_id/run_id/timestamp精确对应当前物化；每10日一批的两层readiness合计40/40 ready。更早475日不补check，本轮不声称它们已具备检查型ready。

APPLY实测18.4033秒、141次helper native读取、1166次进度回调，完成量单调，未触发或放宽预算。逐独立事件提交，原子checkpoint complete/1525/100%；相同冻结全量清单真实APPLY重放3.7094秒、141读，新增0分区/0事件，990物化及40检查身份、时间和计数均不变。两日样本4物化及4check的原ID/target/time复用，不删改或覆盖样本证据。

预检与执行前后83份实际加载项目源码均与a9973d19及旧验收hash一致，52份资金流/正式adapter源码hash一致；同工作区无关文档提交和周线修改保留。当前三个concept sensor无持久化启用记录，直接导入定义默认STOPPED，执行前、后及重放后native sensor库存一致；active-run guard各批通过。仅写授权全量native分区/event及既有staging plan/checkpoint/writer锁，正式Parquet未写；全990文件/24402584字节和54来源控制hash仍匹配冻结P3，最近20来源日标准化SQL语义复核通过。原两份计划文件/hash和此前42份报告/清单均逐字保留。

另作正式只读日更边界盘点：09:42上海时间当前workspace LOADED，两个concept update job已存在，但三个concept sensor尚未加载；不能用workspace LOADED推断当前源码全部已加载。moneyflow_tushare_writer无持久化limit、slot/pending均0，不改pool。现有日历在10月1日至今支持10月8、9、12三日，当前无概念分区及Raw/Silver文件；这只说明现有日期/文件边界，没有请求源或证明源站可取，10月12日当时也尚未到22:00，不记作日更失败。正式日更需后续独立批准加载当前代码、核对定义身份/既有pool方案，并完成真实Tushare验收和sensor启用，不能以历史登记代替P5验收。

本轮完整证据见[全量正式历史登记与收尾证据](../../reports/moneyflow_p4_cnt_ths_event_registration_formal_full_evidence_20261012.json)。计划对账：原计划不改由文件/hash与同cohort重构验证；全部日期/事件集合和行数由native读回对账；40条check正确性由精确target和最近20日标准化/readiness证明；可重复执行由真实全量重放0新增证明；文件事实由全部物理/control hash证明；停止自动触发由native状态及直接导入边界证明。原46项概念执行器与79项市场/行业回归沿用hash一致验收，未重复跑未变化产品测试；旧全仓门禁仅是当时源码快照，本轮不声称当前周线并行代码完整验收。文档/diff/链接与报告hash辅助检查不能替代上述正式结果。

**moneyflow_cnt_ths的P4全量历史登记切片关闭。** 已关闭的是历史物理文件与DG事件识别，sensor启用和真实日更未执行。资金流API/CLI/配置/契约、主体依赖矩阵及Lake路径不变；没有新增产品源码或Definitions，job/sensor evaluation、reload、pool修改、来源请求、安装均0。当前P4已有moneyflow_mkt_dc、moneyflow_ind_ths、moneyflow_cnt_ths三表历史登记关闭，其余四表P4仍待逐表开发和验收，P4整体开放、P5未进入。


## 44. moneyflow_ind_dc的P4独立资产/check/job/catalog切片（2026-10-12）

### 44.1 编码前范围及硬口径

管理员要求“提交修改，然后继续推进moneyflow_ind_dc的P4”；§43概念全量收尾的3文件已提交8335cf3c。本轮按§6东财板块7A和§10/P4，接入独立Raw/Silver、专属动态分区、两个blocking check、两个独立job及catalog/name_mapping；sensor/历史预演/登记另分切片，正式PG/Lake/Prod/Tushare请求或写入均0，reload/pool/sensor/job不执行。沿用P0/P1真实接口与1031行归档fixture、P3冻结739来源日/364012行/1478文件，不重导或补造历史。

CodeGraph explore核对concept assets→daily_update→原collector/candidate/check/publication；impact(_assert_daily_update_dataset)定位两个THS资产及Raw/Silver路径，直接核验该显式发布白名单和测试消费者。白名单只加入已获准moneyflow_ind_dc，其他未接入数据集继续拒绝；本轮不扩展MoneyflowAutomationContract或history事件协议。现有src.foundation/API/前端不消费这些DG新资产，主体依赖矩阵不改。遵守接入模板7A、asset schema contract与性能治理规范；核对本地0344源文档、Dagster官方assets/partitions/checks文档及已安装SDK，不凭接口名猜口径。

| 硬口径 | 实际代码点与正反验收 |
| --- | --- |
| 独立一源一数据集，不合并7源 | 新assets/checks/jobs/moneyflow_ind_dc.py，专属cn_a_moneyflow_ind_dc_trade_days，catalog/name_mapping；各job只选本层asset/check，Silver只依赖本Raw，拒绝跨表/跨日receipt |
| 三类完整、固定18字段，唯一键日期+类别+名称 | 复用daily_fields/key_fields/request_scopes和既有collector/candidate/check；明确行业/概念/地域每轮分别分页、每类非空，两轮稳定；NULL ts_code、同代码不同名称允许，重复三元键/缺类/串类/错日拒绝 |
| 源金额元、NULL/负值/精度保真，不自行计算 | Silver仅日期转DATE；真实归档1031行全字段字面expected对账，source/Raw/Silver计数一致且reject0，禁止缩放或用大小单合计覆盖net_amount |
| 发布与恢复协议只有一份 | shared daily_update显式白名单加入DC，receipt/count/scope/hash/gap验真；原namespace writer锁与候选校验/单文件replace/checkpoint，不复制协议；验证取消、replace退出与幂等续跑 |
| Silver必须同日已绿Raw且最新身份/hash未变 | 当前asset_readiness_status、最新mat identity及物理hash；缺/失败/过期check或改文件阻断，Silver请求源0 |
| 正式checks归属与事实源 | blocking+显式partitions_def，复用物理schema/日期/三元键/三类和标准化SQL；隔离真实job/native event check partition/target三字段读回，错误文件产生FAILED |
| 定义事实与运行事实分开 | schema/path/source_doc由既有固定合同进入definition metadata及catalog；runtime仅row_count/hash/observed columns；无新Gold、运营输入、配置或平台contract |

### 44.2 成本、配置与验收

| 项 | 本轮口径/门禁 |
| --- | --- |
| 日期/对象/类别 | 每次1日，3类别，不展开板块成员；历史既有739日仅复用旧证据；真实09-30 fixture1031行=496行业+504概念+31地域，不把这组数量硬编码为每日生产要求 |
| 请求与分页 | trade_date+content_type+limit2000+offset，显式18fields，两轮最少6请求，单轮最多13页含结束页/两轮26页；重试共享64次/300秒，30秒请求预留和60秒轮间隔不改；三类任一空/超预算拒绝 |
| 文件与SQL | 每日Raw/verification各一候选、Silver一候选，每层正式一文件；实际文件大小与隔离job成本据实归档；单次Raw物理check3 SQL，标准化9 SQL，完整字段集合对账，不全历史深扫 |
| 内存与空间 | 原DuckDB512MB/1线程/no-spill、RSS768MiB、同设备与首次空闲64GiB，不放宽预算；隔离测试虚拟时钟不代表真实网络SLA |
| 事务/恢复 | 每层每文件独立intent/replace/complete，namespace独占，取消/退出保留已提升文件及候选；按原operation/date和物理事实续跑，不备份/Kopia，不声称两层整体原子性 |
| 配置审计 | 无新env/Settings/run config/数据库配置；仅新增两check固定身份常量，在moneyflow.py定义，消费者本表assets/checks/catalog及测试，随definitions加载生效，运营从metadata/catalog/check可见；既有路径、pool、预算和源字段不改 |
| 验收范围 | 新DC隔离job/反例+原DC候选+THS资产及未批准数据集负例回归；原受保护catalog/static gates、完整隔离dg check defs、Ruff/致命检查、文档/链接/源码hash；共享工作区有其他任务修改，若门禁或源码稳定性失败如实保留，不放宽断言或完整通过口径 |

受保护runner仅新增三个精确只读源码路径assets/checks/jobs/moneyflow_ind_dc.py，其他scope、policy、网络/正式资源拒绝区、预算不改。当前白名单原概念负例中DC项在新增接入后已失去“未批准”前提，应从该负例集合移除，并在新增DC真实正向与跨表/非法dataset反例证明范围；不是允许其他数据集发布。本轮先落约束，不预填验收完成。

完整catalog验收还需同步test_asset_governance_contracts.py的显式ACTIVE_ASSET_DEFINITIONS清单，加入本表两层资产，让原有metadata/tag/schema/check全量断言覆盖新资产；不修改断言或排除新资产。首次门禁发现144项catalog与142项测试清单不一致，按此消费者登记修正，完成后重跑。


### 44.3 独立资产切片及完整隔离门禁通过

已接入Raw/Silver两个独立asset、cn_a_moneyflow_ind_dc_trade_days、两个分区blocking check、两个单层job与catalog/name_mapping。共享daily_update只增加已批准DC数据集，固定18字段、三元键、三分类、源金额元和NULL/负值/精度保留；没有复制来源采集、候选或提升协议，没有扩展sensor/历史事件合同。受保护runner只增加三条精确源码读取路径，catalog测试显式资产清单新增两项，原断言不改；概念负例仅移除已失去“未批准”前提的DC项，其他禁止数据集仍有反例。

新DC专项42项及包含其在内的资金流回归339项全部通过。覆盖三类每轮非空、分别分页及2000行整页结束请求、缺字段/错日/串类/重复键/两轮变化拒绝；代码可空、同代码不同名称允许；Silver缺同日绿Raw、其他日期、过期或失败check、物理hash变化均阻断且不请求源。候选receipt/分类/verification hash错误、跨表receipt、取消后保留候选、Raw/Silver replace后退出续跑、同内容不重写及来源修订均有验收。旧DC候选和THS/市场链回归通过，不把原来源/API合同改成新口径。

P1归档2026-09-30真实样本1031行经本轮假源、虚拟时钟进入隔离job，行业496/概念504/地域31。两轮共6次假源调用，显式18fields、trade_date/content_type/limit2000/offset0；Silver追加调用0。输入每轮、Raw、Silver及两层checked_row_count均1031，reject0，18字段逐值完全一致。Raw95073字节、Silver95049字节；两job实测0.6735秒，但轮间60秒由虚拟时钟模拟，不能当作真实网络耗时或日更SLA。额外读回临时instance的两条native check，均SUCCEEDED/passed、partition=2026-09-30，target.storage_id/run_id/timestamp逐项等于对应当前物化；Raw的scope_row_counts另核合计1031。未把归档fixture重放称作新的Tushare实测，也不把输入计数伪写为不存在的运行metadata字段。

完整受保护catalog门禁12项/498子断言、static门禁113项均通过，共17批，每批7个原生网络/正式资源拒绝反例通过；没有改隔离策略。完整隔离dg check defs --use-active-venv --no-check-yaml加载成功，使用临时HOME/DAGSTER_HOME与现有虚拟环境，未安装或同步依赖。改动文件Ruff、全DG src/tests致命检查、文档完整性通过；全部1138份DG源码及测试在回归和完整门禁前后hash一致，先前43份资金流报告/清单逐字不改。CodeGraph sync/status完成，根索引up to date；其他任务已提交或未提交修改均保留，本次验收只对应记录的1138文件快照，不能代替其他任务的功能验收。

首次fixture结果读取误用了SDK事件函数，改成event_specific_data.materialization；首次catalog门禁因测试资产清单漏两项而报144/142，补齐消费者后重跑通过；Ruff的导入顺序与dict字面量问题已修正。完整证据及源码/日志/native身份见[东财板块P4资产验收](../../reports/moneyflow_p4_ind_dc_evidence_20261012.json)。计划对账：独立身份由catalog/job/partition测试证明；日期+类别+名称与字段保真由三类正反样本及1031行全字段对账证明；发布/取消/退出由原协议真实临时文件重放证明；Silver绿Raw门禁由native状态及hash反例证明；检查归属由临时instance精确target读回证明；性能上限由旧DC分页预算与本轮整页反例证明，未放宽上限。

**moneyflow_ind_dc的P4资产/check/job/catalog切片关闭。** 本轮新增或修改assets/checks/jobs、partition/check身份、共享发布白名单、catalog/name_mapping及相关测试，回填原方案/LLD并增加证据。没有生产DatasetDefinition/API/CLI/配置或主体依赖矩阵变更；正式PG/Lake/source/job/sensor/reload/pool/事件写入均0。下一切片接三个默认STOPPED sensor及739来源日历史只读预演，仍按P3冻结364012行/层和1478文件；历史缺类按冻结实际范围，不套未来日更三类非空规则。历史执行器、两日/全量清单及正式登记继续各自验收与批准，整个P4仍开放、P5未进入。


<a id="moneyflow-ind-dc-automation"></a>

## 45. moneyflow_ind_dc三个STOPPED sensor与739日历史只读预演（2026-10-12）

### 45.1 编码前范围、命名与影响面

管理员批准本切片；上一资产切片已提交872bc135，未推送。复用现行单表自动编排与P3冻结证明，新增固定BOARD_DC_MONEYFLOW_AUTOMATION和三个独立sensor，不做正式sensor evaluation、reload、启用、pool修改、job运行、分区或event写入。历史执行器、两日样本、全量执行清单留在下一切片。

| 硬口径 | 代码落点及正反验收 |
| --- | --- |
| 默认STOPPED且不在sensor请求来源 | sensors/moneyflow_ind_dc_sensor.py；cn_a_moneyflow_ind_dc_trade_day_sensor、raw_tushare_moneyflow_ind_dc_update_job_sensor、silver_moneyflow_ind_dc_update_job_sensor；min interval600秒，resources只有lake_root/duckdb，定义及无来源调用反例 |
| 上海22:00登记当天，最多另补一个历史漏登记日 | register_moneyflow_trade_days复用固定cn_a_moneyflow_ind_dc_trade_days，历史起点2023-09-12；交易日/假日/22点前/起点前反例；输出仅SensorResult |
| 每tick最近10交易日最多一个单日job | evaluate_moneyflow_update复用2026-10-01日更新起点、SSE日历DESC LIMIT10；每层mat/check各1次limit100，active job各1次limit1，分区1次；不扫描739日事件或SQL |
| 跨表/跨层cursor拒绝，丢cursor不重置重试 | 固定合同身份、8192B cursor上限、原生run key最多6次；无消费request重复同key，临时错误可重试，权限/字段/精度/身份错人工处理 |
| 最新真实green check+mat+文件才ready | asset_guards/moneyflow_ind_dc_readiness.py封装共用readiness；精确target三字段、hash、无symlink，Silver核对Raw hash；原三表64KiB保留，DC单独预算及超预算拒绝 |
| 历史分类按P3实际事实，日更新仍必须三类非空 | bootstrap/moneyflow_ind_dc_event_preview.py封装共享历史proof；历史分支复用audit_history_day，按manifest snapshots的日期/类别/行数核对最近20日；仅行业的早期历史合法，日更缺概念/地域仍拒绝，不生成缺口 |
| 历史739日/364012行每层/1478文件，原证明不改 | 同history-full-20261009、cutoff2026-09-30、cohort05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618；验证全部本表文件hash与原控制文件，proof entries包含每日row_count及scope_row_counts；控制/文件变化、跨cohort/跨表事件拒绝 |
| 正式只读采用真实PG但没有写路径 | daily_basic_event_instance默认readonly、default_transaction_read_only=on、statement_timeout10秒、should_autocreate_tables=False；包装只暴露分区/mat/check读取，临时脚本及报告只写/private/tmp |
| 原门禁覆盖全部新定义而不放宽隔离 | protected runner仅增sensor/readiness/preview三个精确源码路径；static gate增三个期待身份；两个sensor标签HTML同步；全量受保护catalog/static及隔离defs，旧3表回归 |

CodeGraph explore/impact已审计固定automation合同、注册/selector、readiness、历史proof及event plan/engine消费者；当前代码复核确认历史audit_daily_moneyflow_standardization会要求三类，不能直接复用到早期DC历史。仅共享历史入口增加DC专用history audit分支，日更checks/collector不改。无Prod DatasetDefinition/API/CLI、主系统依赖矩阵变更；固定历史执行adapter未接入，不能把preview通过当成正式登记已可执行。后续执行器须审计共享engine的每日计数验证消费者。

### 45.2 性能与配置审计

| 项目 | 固定上限、拒绝策略与证据 |
| --- | --- |
| 新预算常量 | MONEYFLOW_IND_DC_READINESS_FILE_MAX_BYTES=4*1024*1024，在run_contracts/moneyflow.py唯一声明，持久化为源码，无env/Settings/数据库/运营覆盖项；唯一生产消费者共用readiness的固定DC分支，随definitions加载生效；超限返回file_hash_budget且不hash |
| 新预算依据 | 实际1031行Raw95073B/Silver95049B已超过原64KiB；现行每轮20000行按样本体积约1.84MB/文件，DC4MiB提供有界余量，不能保证任意字符串都通过；最长tick20文件最多80MiB顺序hash，实际10日fixture约1.9MB；旧三个数据集仍用64KiB，未知合同拒绝 |
| 日更sensor成本 | 两层最多2mat+2check+2active run+1partition+1日历SQL；最多20文件hash，无来源请求，cursor实际<2048B、10日隔离tick<2秒；不放宽源端64call/300秒、512MB DuckDB/1线程/no-spill、RSS768MiB、writer/pool预算 |
| 历史proof成本 | 仅本表40个已完成P3 unit、1478文件hash、82控制文件；最近20日期做20次Raw/Silver历史标准化及各1次分类group by（8 SQL/日期），不对739日逐日深扫；按冻结分类行数和日期总行数核对，不将fixture固定分类数量当成每日要求 |
| 历史native读取 | 分区1次、每层ceil(739/100)=8次mat、每层1次最近check，共19次helper查询；limit100，分区/date facts最多4096；截断或已有事件身份/hash/target不符拒绝 |
| 事务与取消 | 无正式事务写入、无锁/目录创建、无计划/checkpoint变更。现有proof每文件取消检查、每unit120秒与RSS限制；正式预演驱动另设120秒进程上限，只读中断可从同冻结事实重跑 |
| 正式验证命令 | 工作目录lake_console/orchestrator，现有.venv/bin/python3 -B执行/private/tmp下DC只读驱动；固定Lake/staging根及既有/Users/congming/.goldenshare/dagster_home/dagster.yaml readonly native adapter，查询上述两asset/check及专属partition set；无Tushare/Prod请求，不执行sensor，输出临时JSON后归档 |

官方依据：[Dagster sensors](https://docs.dagster.io/guides/automate/sensors)说明default_status与run_key去重，[partitions](https://docs.dagster.io/guides/build/partitions-and-backfills)说明分区模型；实际语义仍以当前源码、临时native instance正反验收和正式只读读回为准。本节为编码前约束，结果另据实填写。


### 45.3 实际验收与正式只读结果

三个独立sensor已按§45.1身份及标准tags接入，default_status均STOPPED、min interval600秒，依赖只有lake_root/duckdb。sensor不调用Tushare，不合并三个数据集的历史或cursor，不新增运营参数。共用固定合同仅增加BOARD_DC身份；共用readiness只为DC使用4MiB文件预算，原市场/行业/概念三表64KiB保持原样，超预算在hash前拒绝。历史proof入口复用audit_history_day，按冻结每日行数及分类核对；早期仅行业的历史正例通过，同文件日更三类检查拒绝；分类总数相同但分布不同、总行数偏差都有反例。

资金流专项及旧市场/THS sensor、历史proof/提升回归共303项通过，其中新DC sensor/preview50项；两个新测试文件仅整理import后，50项再跑通过。受保护catalog12项/498子断言、static113项及完整隔离dg check defs通过，所有原生拒绝反例按原policy执行，没有改断言、删反例或跳过完整套件。项目cwd下改动文件Ruff和DG src/tests致命检查通过。完整回归/门禁期间1143份源码及测试hash一致；随后只有两份新测试import排序修正，当前1143份hash与修正后快照一致，所有产品源码保持原hash，最终50项与正式预演据此复验。先前44份资金流报告/清单逐字保留，共享工作区其他任务脏文件不改。CodeGraph sync/status根索引up to date，无主体边界/依赖矩阵变更。

隔离10日期sensor使用归档1031行fixture，经临时native Raw/Silver job产生20个文件后实际tick：2mat+2check+2active run+1partition+1日历SQL，20次hash共1901220字节，0.0253秒、cursor590字节，tick来源调用0。没有把假源/虚拟时钟重放称作新Tushare实测；这些结果证明sensor有界读取，不代表日更网络SLA。

2026-10-12使用既有readonly PG adapter执行本表正式只读预演，并同事实重复执行：739来源日、每层364012行、40个P3 unit、1478个正式文件共70542522字节，82控制文件hash均未变。最近20来源日Raw/Silver schema、日期、三元主键、全部字段一致性、每日行数与实际分类核对通过；20次深核共160 SQL，其余日期依赖已冻结P3证明及当前文件hash。helper native查询实测19次（1partition+16mat+2check），首次1.1672秒、重跑0.6305秒，两次结果完全一致；1724次hash调用包含同一控制文件多次复核，不将它写成1724个文件。

| 目前原生缺项 | 实际只读预演结果 |
| --- | --- |
| 专属动态分区 | 待登记739个，当前可复用0个来源日 |
| Raw/Silver物化 | 各739条待登记，共1478条；现有可复用0条 |
| 最近20来源日blocking检查 | 各20条待登记，共40条；现有可复用0条 |
| 后续正式写入量 | 739分区键+1518事件=2257项；此处只是预演计数，没有执行或冻结APPLY清单 |

真实readonly连接配置default_transaction_read_only=on、statement_timeout10秒、should_autocreate_tables=False；包装仅开放三类原生读取。没有初始化正式instance、job/sensor evaluation、reload、启用sensor、pool调整、分区/event/正式Lake或staging控制文件写入、Prod/Tushare请求、安装。定义STOPPED已从当前源码直接读回，不把它称作已reload进当前workspace或已审计全部持久化sensor状态。

计划对账：独立命名/标签/STOPPED由专属测试和完整静态门禁证明；22点/假日/起点与有限重试由临时native正反例证明；readiness身份、hash、最新check与上游修订由真实临时job和反例证明；历史分类边界由冻事实scope/row proof与日更反例证明；739日期/1478文件/82控制hash由正式只读读回证明；无正式写入由readonly adapter与只读包装的入口审计保证。首次测试辅助函数名错误和首条广域命令的不存在测试文件已纠正，最终正确路径全部通过；证据区分初始失败与最终验收。

本轮源码、日志hash、原生门禁报告及全部正式文件/control hash见[DC sensor与739日只读预演证据](../../reports/moneyflow_p4_ind_dc_sensor_event_preview_evidence_20261012.json)。本切片关闭，P4整体仍开放，P5未进入。下一步开发固定DC历史登记执行器，校准共享engine的每日计数/分类消费者，完成隔离恢复/幂等/预算门禁及两日样本、冻结全量清单；正式分区/event写入仍需对应精确清单批准。


<a id="moneyflow-ind-dc-event-registration"></a>

## 46. moneyflow_ind_dc历史登记执行器、两日样本与冻结全量清单（2026-10-12）

### 46.1 编码前范围与硬口径

管理员要求继续推进§45.3下一切片。上一sensor/preview修改保留，当前dev-interface开发，不创建分支/worktree，不处理其他任务脏文件。本轮只接固定DC事件PLAN/执行adapter和对应共享验证，做临时native SQLite恢复/容量验收，生成正式只读两日样本和739日全量冻结清单；本轮不提交、推送或执行正式APPLY。正式分区、event、Lake/staging控制写入、sensor evaluation/reload/启用、pool修改、来源请求均不包含。

| 硬口径 | 实现与正反门禁 |
| --- | --- |
| 固定DC身份、默认只读 | bootstrap/moneyflow_ind_dc_event_plan.py、moneyflow_ind_dc_events.py仅绑定BOARD_DC_MONEYFLOW_AUTOMATION，共用原moneyflow_event_plan/history_events；拒绝其他三表清单、篡改身份、日期与bool以外apply |
| 原P3事实与精确范围不可改 | 同operation/cutoff/cohort、739日364012行每层1478文件；每entry冻结row_count及scope_row_counts；validate重建同原证明，错行数、同总数错分类及改hash拒绝，不计算补缺口 |
| metadata必须与每日事实一致 | DC物化row_count/source_row_count、18个observed_columns及scope_row_counts；最近20日检查checked_row_count与同分类事实，target.storage_id/run_id/timestamp精确绑定；已有事件错行数/分类拒绝且不覆盖 |
| 历史分类与未来日更分开 | 共享历史proof与engine复用同一DC冻结分类SQL helper；早期719合成单行业日期不补check，后20日完整三类真实归档fixture；实际正式最近20日照旧深核，不放宽未来collector/check三类规则 |
| 每unit可恢复、原生事实续跑 | 原事件逐条提交、分区每100日一批；原writer锁及plan/checkpoint原子保存复用，无长历史事务；取消/进程退出保留已提交event，原生读回胜过cursor/checkpoint，缺失checkpoint、观测写失败、幂等重放有正反例 |
| 性能与共享消费者保持边界 | 只扩DC到共用两处row_count守卫和专属分类metadata守卫，原market/THS事件metadata与六份旧冻结清单不变；CodeGraph explore/impact核对固定adapter、plan/proof、engine/readiness和测试，主系统契约与依赖矩阵不变 |
| 完整隔离门禁 | 新DC events suite及原三表events回归，DC sensor/preview回归；受保护runner仅新增两个bootstrap精确源码路径，原拒绝policy与断言不改；完整catalog/static/isolated defs、Ruff、文档/链接、稳定源码和旧45份报告hash |

### 46.2 性能、配置与正式只读计划

| 项目 | 预算/执行方式 |
| --- | --- |
| 全量范围 | 739来源日，364012行/层，1478个已存在Parquet约70.5MB；无源请求、分页或Parquet生成；739分区+1478物化+40最近check=2257工作项/1518事件，检查只最近20日 |
| 两日样本 | 2026-09-29、2026-09-30；行数及分类从P3逐日事实读回，不假定两天相同；2分区+4物化+4check=10工作项/8事件，只生成清单与只读预检 |
| 文件/SQL成本 | proof复核1478文件与82控制hash，最近20日同源历史标准化与分类深核160 SQL；APPLY后续多次重建proof并深核，仅20日检查阶段再核，不对739日反复SQL；512MB/1线程/no-spill，RSS768MiB |
| 原生预算 |100日/批，limit100；计划不读取event ID作身份，绑定既有PG/临时SQLite实际storage；full默认预检预计21次helper读含2active，隔离full APPLY预计207次读，低于256；上限4096项/600秒总/120秒unit不变 |
| 控制写入成本 | 临时739日APPLY预计1546次原子保存=1518事件+8分区批+17批读回+plan/初始/最终3次；逐事件checkpoint最多256KiB、plan32MiB，保存失败保留已提交事件；全量与样本正式APPLY成本待批准后实测，不外推SQLite/只读耗时 |
| 内存/持久化 | Python仅日期、文件hash、3类聚合和事件编排，单事件独立持久化；不将364012行明细放内存；formal执行本轮0，计划JSON只在仓库reports，temp scripts/临时SQLite在/private/tmp |
| 配置审计 | 无新增env/Settings/数据库/run config；固定revision/partition/check沿§45合同，既有budget、路径、锁、pool不改；新增metadata仅DC日期分类事实，消费者共享writer native readback和专属测试 |
| 真实只读验证 | 现有daily_basic_event_instance(writable=False)，已有本机goldenshare_dagster PG，强制readonly、10秒statement_timeout、should_autocreate_tables=False；包装暴露原生只读storage identity/分区/mat/check/active run查询，无写方法；原生只读PLAN与report(...apply=False) |
| 拒绝与恢复 | 当前source/hash/identity漂移、active job、错误event/check、writer冲突、取消/预算立即拒绝；不删事件、不改原清单/checkpoint、不初始化正式instance；正式异常后续同plan_hash按原生事实续跑 |

正式驱动命令从lake_console/orchestrator用现有.venv/bin/python3 -B调用/private/tmp/moneyflow-ind-dc-events-20261012/formal_plans.py，固定Lake=/Volumes/datasource/data_lake、staging=/Volumes/datasource/data_lake_staging、operation=history-full-20261009、cutoff=2026-09-30、cohort=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618，只读既有/Users/congming/.goldenshare/dagster_home/dagster.yaml native adapter；只写仓库reports与/private/tmp日志，不写正式staging/events。两份JSON读回后重新构造相等、原45报告逐字保留。维护核验、正式样本APPLY、全量APPLY各自等待精确批准。

官方[report_runless_asset_event](https://dagster.io/docs/api/dagster/internals#dagster.DagsterInstance.report_runless_asset_event)定义资产事件不归属run；本次沿已批准直写补录模式，不称Dagster backfill。当前安装SDK与临时native读回决定实际partition/target/metadata语义。本节为编码前约束，完成后按真实结果对账，不预填通过。


### 46.3 执行器、恢复与容量验收完成

固定DC入口moneyflow_ind_dc_event_plan.py与moneyflow_ind_dc_events.py已接入，共用plan/proof/history_events协议，不复制锁、checkpoint或事件写入机制。DC每日期row_count及实际scope_row_counts进入冻结entry；Raw/Silver物化保留source_row_count、18个observed_columns和分类行数，最近20日检查记录checked_row_count和同分类事实。已存在事件计数/分类不符拒绝，不覆盖；plan自行重算hash不能伪造事实。共用行数守卫新增DC，分类SQL从前一proof抽成同一helper供proof和检查阶段复用；原三表metadata与清单结构不改。

| 验收项 | 实际结果 |
| --- | --- |
| DC专项 | 57项通过，67.21秒；默认只读、取消、真实子进程退出47、缺失/伪造/错误checkpoint、保存失败、进度观察失败、续跑与幂等 |
| 日期/分类/行数 | 两日1030/1031隔离fixture计数及18字段/分类metadata读回正确；七类假行数、五类假scope、原生错/缺scope与行数、SQL错计数、check阶段scope失败、跨原三表清单均拒绝 |
| 原链回归 | 175项通过，171.14秒；原三表events、DC sensor/preview均覆盖；正式旧三表六份样本/全量冻结清单重新验证相等且文件/hash不变 |
| 739日期容量 | 719个合成单行业日期各1行+最近20个三类1031行归档fixture日期，共21339行；临时SQLite完成739分区+1478物化+40检查=2257项，旧日期不生成check，重放不重复、来源/Parquet不改 |
| 容量成本 | 8.2396秒，207次helper native读，批次≤100；RSS458752000B（437.5MiB）；1546次原子控制保存共0.6204秒，最慢11.044ms；此为临时SQLite测试，不能代替正式PG APPLY耗时 |
| 完整门禁 | 受保护catalog12项/498子断言、static113项/15批、完整隔离dg check defs通过；合计17批每批7个原生拒绝反例通过；改动文件Ruff及DG src/tests致命检查通过，未放宽policy/断言 |

首次DC测试55通过/2失败，是新反例构造错误地用AssetCheckEvaluation._replace；按当前SDK及旧测试的显式构造方法修正，57项全部重跑通过，产品实现没有因测试失败放宽。最终1146份DG源码及测试在完整门禁、只读PLAN前后hash相等，原45份资金流报告/清单逐字保留；其他任务修改保留，不宣称它们业务功能已验收。CodeGraph explore/impact和sync/status覆盖fixed adapter、shared plan/proof/writer/readiness/native metadata消费者，根索引up to date；无主体边界、依赖矩阵、DatasetDefinition、API/CLI、配置、来源请求或日更合同修改。

### 46.4 正式只读样本与全量清单

上海2026-10-12 12:10左右在既有goldenshare_dagster PG强制readonly/禁自动DDL adapter下生成；目标仍为P3冻结history-full-20261009/cutoff2026-09-30/cohort05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618。逐份JSON读回和重新构造完全相等；所有entry逐日行数等于scope合计，范围为2023-09-12～2026-09-30的739个实际来源日、364012行/层，每日86～1031行。文件/control hash核验复用全部1478正式文件和82个P3控制证明；正式events目录库存前后相等。

| 清单 | 精确范围与当前缺项 | plan_hash |
| --- | --- | --- |
| [两日样本](../../reports/moneyflow_p4_ind_dc_event_registration_sample_plan_20261012.json) | 2026-09-29、09-30各1031行，共2062行；每天行业496/概念504/地域31；待2分区+4物化+4check=10项/8事件 | 86e1014ec5fbfee902d2ff0269c379882513243502e108012b58e12bb2be4ab1 |
| [全量](../../reports/moneyflow_p4_ind_dc_event_registration_full_plan_20261012.json) | 739日/364012行，待739分区+1478物化+最近20日40check=2257项/1518事件 | c47968312063d88aa523f5e46e7e36e3d0444eb5254d7bd02e42af58d1acd417 |

样本20059B、默认预检0.4772秒/7次native读取含2active；生成、读回及重构全过程2.1182秒。全量465398B、默认预检0.6333秒/21读含2active；对应全过程1.8419秒。加上原六份清单验证，本轮正式只读驱动6.1781秒。没有请求Prod/Tushare、写任何正式分区/event/Parquet/staging control、运行sensor/job、reload、启用sensor、改pool或安装；新增两JSON只保存仓库reports。本轮没有提交或推送。

样本以后完成时，完整全量清单保持原hash，根据native事实差分预计剩737分区+1474物化+36检查=2247工作项/1510事件；不重写全量计划或删除样本证据。正式样本APPLY尚未批准/执行，正式check/readiness结果未取得，不能把只读/临时SQLite结果称作正式登记完成。

默认只读样本预检命令（从lake_console/orchestrator，现有.venv，禁止同步/下载）：

```python
import json
from pathlib import Path
from orchestrator.defs.bootstrap.daily_basic_event_instance import daily_basic_event_instance
from orchestrator.defs.bootstrap.moneyflow_ind_dc_events import report_board_moneyflow_dc_history_events
plan = json.loads(Path('../reports/moneyflow_p4_ind_dc_event_registration_sample_plan_20261012.json').read_text())
assert plan['plan_hash'] == '86e1014ec5fbfee902d2ff0269c379882513243502e108012b58e12bb2be4ab1'
with daily_basic_event_instance() as instance:
    print(report_board_moneyflow_dc_history_events(instance=instance, plan=plan))
```

### 46.5 计划对账与下一阶段准入

§46.1独立身份/默认只读由固定adapter、PLAN hash/instance重建和跨表负例证明；每日计数/分类由冻结proof、复用SQL、metadata和原生读回反例证明；100日批/20日check由739日期容量证明；取消/退出/观测错误与幂等由真实临时native持久化和子进程验收证明；739正式来源日与文件事实由实际PG只读清单读回与P3 hash证明；读取/内存/时间上限由预算反例、207读和RSS实测证明。源码与源文件不是checkpoint可随意替代的事实；无正式写入由readonly连接、apply=False和无写API的包装入口保证。

本轮完整源码/日志/native门禁、容量、正式只读及两份计划hash见[DC历史登记执行器证据](../../reports/moneyflow_p4_ind_dc_event_registration_evidence_20261012.json)。两份文档/本轮链接/报告结构作辅助门禁，不能代替上述实际验收。

**DC历史登记执行器与清单开发切片关闭。** 下一步先按两日清单取得正式样本阶段批准，写前核验本表三个sensor持久化状态未启用、两job无active run、维护窗口、writer互斥、当前源码及同一storage/hash、staging空闲大于32MiB；隔离Definitions不证明正式workspace已加载新定义。本表正式样本批准不包含reload、pool、sensor启用、日更job或全量APPLY；样本读回四check partition/target、来源/checked计数、分类、四readiness及幂等后，再独立准入冻结全量清单。P4整体仍开放，P5未进入。


<a id="moneyflow-ind-dc-formal-sample"></a>

## 47. P4东财板块历史事件两日正式样本（2026-10-12）

### 47.1 本轮授权、执行范围与恢复方式

管理员在上轮已明确展示两日样本清单及其10项/8事件后要求“继续推进吧。”，本轮据此执行该正式样本，739日全量仍需独立批准。沿用§46验收的固定DC adapter和共享writer，不修改产品代码或新增CLI/配置。当前dev-interface HEAD为9d8d25d1（其他任务提交），本任务执行源码以§46报告的1146份源码/测试hash为验收依据，不能把它说成已提交或已reload。工作区无关修改保留。

固定输入是[两日清单](../../reports/moneyflow_p4_ind_dc_event_registration_sample_plan_20261012.json)：2026-09-29、09-30，每日每层1031行，行业496/概念504/地域31；只登记cn_a_moneyflow_ind_dc_trade_days的2键、raw_tushare_moneyflow_ind_dc与silver_moneyflow_ind_dc的4物化，以及对应4条blocking check。plan_hash=86e1014ec5fbfee902d2ff0269c379882513243502e108012b58e12bb2be4ab1，文件SHA256=d0b320a760d64599bf279556da706d6fbe9d6917665aa3150540bb733437278e。operation=history-full-20261009、cutoff=2026-09-30、cohort=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618均不变。

工作目录/Users/congming/github/goldenshare/lake_console/orchestrator，使用既有.venv/bin/python3 -B。只读预检命令为`.venv/bin/python3 -B /private/tmp/moneyflow-ind-dc-formal-sample-20261012/run.py`，批准的样本登记命令加`--apply`；临时驱动复用固定helper，不进入正式Definitions。目标是/Users/congming/.goldenshare/dagster_home对应的既有本机goldenshare_dagster PG，默认read-only，只有样本APPLY及同清单幂等重放显式writable=True，禁止自动DDL。读取现有sensor状态、两个job的active状态、原生事件、全部1478个冻结Lake文件及82份来源控制；只写该样本动态分区/事件、既有staging中的events/<plan_hash>/plan.json及逐项checkpoint、namespace writer锁，以及/tmp日志/仓库报告。正式Lake只读，不请求Prod/Tushare，不reload、启用/evaluate sensor、调整pool或执行job。

维护门禁：三个本表sensor的native持久化状态均未启用，实际导入默认STOPPED；两个job无active run，writer锁独占；当前源码和所有已冻结文件/control hash一致，Lake=/Volumes/datasource/data_lake、staging=/Volumes/datasource/data_lake_staging根已存在、无根symlink、同设备，staging空闲超过32MiB。原生查询单SQL10秒、100日一批、600秒总预算、256次helper native读/768MiB RSS门禁沿用，驱动进程限120秒，进度逐项写/tmp并flush/fsync。

失败或取消时保留已经提交的native事实及checkpoint；继续使用同一清单和固定helper幂等续跑，不编辑checkpoint、不删除事件、不重建历史文件。写后逐条读回partition、row/source/checked计数、分类、18个observed_columns、check的storage_id/run_id/timestamp精确target，四个readiness须通过；同清单真实APPLY重放须0新增事件/分区且原生ID不变，再只读计算冻结全量剩余差集。以下验收结果在执行后追加，不预填通过。


### 47.2 正式样本、读回与幂等重放通过

本轮完成的是历史数据的DG登记：两日Raw/Silver文件早已在P3落湖，本轮把它们对应的分区、物化和检查写入DG，未重新采集或生成Parquet。只读预检实际缺2键/4物化/4检查，耗时0.6930秒/7次helper native读；全量预检仍缺739键/1478物化/40检查，0.5781秒/21读。

原生sensor查询扫描106条状态，本表三项均没有持久化记录，实际导入默认STOPPED；写前、写后及重放后状态和全库存name/status hash一致。两个job的active guard各批通过，writer锁独占成功。当前60份资金流/正式adapter源码及83份实际加载项目源码与上一轮验收相符；全部1146份DG源码/测试hash前后不变，故沿用§46隔离门禁，本轮没有重新运行产品测试或reload，亦没有把正式code-location进程的源码版本称作已核验。

| 正式验收 | 实际结果 |
|---|---|
| 首次APPLY | 10/10项，2分区键、4物化、4blocking checks；1.9173秒，53次helper native读 |
| 行数/分类 | 两日每层各1031行，source_row_count/checked_row_count一致；行业496、概念504、地域31，每个物化18个observed_columns |
| 原生物化身份 | 09-29 Raw/Silver storage_id=7450761/7450762；09-30 Raw/Silver=7450763/7450764，均为runless记录 |
| 检查target及就绪 | 四检查partition正确、SUCCEEDED/passed/blocking，storage_id/run_id/timestamp精确指向对应物化；两日两层四个readiness全部ready |
| 写后差集 | 样本缺分区/物化/检查均0 |
| 同清单真实重放 | 1.7966秒/53次helper native读；新增键和事件均0，物化ID/timestamp和检查target、分类及计数前后相等 |
| checkpoint及进度 | complete/10 of 10/100%；首次APPLY60条进度记录，完成量单调，逐项持久化；重放checkpoint同样complete |
| 空间/内存 | 执行前staging空闲2928877031424字节，Lake/staging同设备；驱动峰值RSS380256256字节，约362.6MiB，未触发拒绝预算 |

只读/hash/SQL、native写内部SQL、sensor维护查询和额外读回的计数边界分开：53只统计helper native读，不声称整个驱动只执行53条PG SQL。来源证明保持739日/364012行每层/1478文件/70542522字节及82控制hash；最近20实际来源日深核语义，未对全部739日重新跑深核SQL。驱动额外保留原其他三表冻结证明，总计5408份Lake/来源控制文件hash前后相同，48份既有报告和清单逐字保留。正式staging只新增本样本plan/checkpoint并使用既有namespace锁；无正式Parquet写入。

完整记录和临时驱动/日志hash见[两日正式样本证据](../../reports/moneyflow_p4_ind_dc_event_registration_formal_sample_evidence_20261012.json)。计划硬口径对应：独立DC身份与精确范围由固定adapter/冻结清单校验；维护与互斥由native sensor查询、各批active guard和writer锁；文件/历史分类由P3 proof及现行SQL复核；原生正确性由逐条target/metadata读回与batch readiness；恢复幂等由同清单真实APPLY重放。没有修改产品代码、API/CLI/配置或主体依赖矩阵，其他工作区修改保留，本轮未提交或推送。

### 47.3 下一步全量准入

**两日正式样本阶段完成，DC全量历史登记尚未执行。** [739日冻结全量清单](../../reports/moneyflow_p4_ind_dc_event_registration_full_plan_20261012.json)保持原plan_hash=c47968312063d88aa523f5e46e7e36e3d0444eb5254d7bd02e42af58d1acd417及原文件SHA256；正式只读差分已确认10项完成，剩737分区+1474物化+36检查=2247项/1510事件，0.5921秒/21读。全量须保留本样本原生物化身份、target和文件，不重新生成清单或覆盖样本证据。

全量需独立批准该冻结清单；批准后重新核验维护状态、active job、源码/storage/来源及物理hash、空间和writer互斥，按原逐项checkpoint执行并读回。样本PG实测不能作为全量SLA；全量仍受§46既定预算约束。全量批准不包含reload、pool配置、sensor启用或真实日更。P4整体仍开放，P5未进入。


<a id="moneyflow-ind-dc-formal-full"></a>

## 48. P4东财板块739日全量历史登记（2026-10-12）

### 48.1 本轮批准、只读准入和执行清单

管理员在上轮明确提出原冻结全量清单及剩737分区/1474物化/36检查后要求“提交修改，然后继续推进”。本轮先将此前sensor/readiness/preview、事件执行器及两日正式样本等24个任务文件提交为5883ae7a，未推送，工作区其他任务修改保留；随后按该全量清单完成登记和验收。本轮没有产品代码、配置、CLI、contract或依赖矩阵修改，不扩展到sensor启用、code-location reload、pool配置、正式job和P5日更。

固定输入是[原739日全量清单](../../reports/moneyflow_p4_ind_dc_event_registration_full_plan_20261012.json)，plan_hash=c47968312063d88aa523f5e46e7e36e3d0444eb5254d7bd02e42af58d1acd417，文件SHA256=e2c0ab5adbf3a3348d51636ec6a084b4219dd9acf869f3588d4fcc26512f8158。覆盖2023-09-12～2026-09-30的739个实际来源日、每层364012行；已有两日样本10项原样复用，只新增737个cn_a_moneyflow_ind_dc_trade_days键、Raw/Silver的1474条物化和最近20来源日的36条blocking check，总2247项/1510事件。历史缺口保留，不补造日期或资金值；20日之外不补check，也不把它们说成event ready。

只读准入确认上述差集、样本10项齐全、原生target和源文件一致。本表三个sensor无持久化启用记录、当前定义默认STOPPED，两job无active run；60份相关源码、83份实际导入源码既匹配§46验收，也匹配5883ae7a提交；1146份DG源码/测试快照不变，沿用原隔离门禁。冻事实1478文件/70542522字节、82来源control不变，并额外保留其他三表P3证明共5408文件/control与49份报告/清单。执行前只读记录原三表分区、物化/check原生ID与timestamp摘要，写后须相同，样本checkpoint保持原hash。

工作目录/Users/congming/github/goldenshare/lake_console/orchestrator，命令`.venv/bin/python3 -B /private/tmp/moneyflow-ind-dc-full-20261012/run.py`默认只读，获批登记命令加`--apply`。目标是/Users/congming/.goldenshare/dagster_home对应的既有本机PG goldenshare_dagster，原adapter自动DDL关闭；只有全量登记及同清单真实重放显式writable=True。Lake=/Volumes/datasource/data_lake只读，staging=/Volumes/datasource/data_lake_staging，两根既有/无根symlink/同设备。写入仅限该全量分区/event、既有staging/moneyflow/history-full-20261009/events/<plan_hash>/plan.json与逐项checkpoint及namespace writer锁，另写/tmp进度/日志和仓库报告。

预算沿用§46：100日期/批、4096工作项上限、600秒helper总/120秒unit、256次native读、RSS768MiB，SQL单次10秒、DuckDB512MB/1线程/no-spill。全量隔离APPLY已测207读、8.2396秒；两日PG样本1.9173秒仅是准入证据，不外推全量SLA。驱动包络660秒，运行中逐项保存进度并flush/fsync，外部持续读取进度；每个批次active guard，独占writer成功后再次校验。

中断保留已提交事件和checkpoint，用原清单原执行器幂等续跑，不改checkpoint或删除原生事实。验收通过聚合集合差异和批量原生读回证明739键/1478物化/40最近检查齐全，核对每日row/source/checked计数、实际分类、18个observed_columns及精确check target；仅最近5来源日抽取10个readiness，避免全历史逐分区深扫。再对同全量清单真实APPLY重放，新增必须0、原生物化/check身份及样本保持；物理文件、控制、旧报告和其他三表原生摘要不变。以下结果在执行后追加。


### 48.2 全量正式登记、读回和重放通过

本轮准入预检缺737键/1474物化/36检查，completed=10，0.9905秒/21次helper native读；两日样本10项保持。整个预检驱动3.1111秒，包含维护状态、样本/全量native读取和原三表事实摘要。APPLY重新预检后独占writer，复用样本原生记录，完成如下：

| 验收项 | 正式实际结果 |
|---|---|
| 首次全量APPLY | 2257/2257项，新增737分区、1474物化、36检查；26.5388秒、207次helper native读 |
| 写后集合/计数 | 739键、1478物化、40最近检查齐全，缺分区/物化/check均0；预检读回0.8855秒/21读 |
| 内容metadata | 每层累计364012行，各日row/source计数及实际分类均匹配冻结清单；每个物化18个observed_columns |
| 原生checks | 2026-09-02～09-30最近20实际来源日，40条SUCCEEDED/passed/blocking，partition、checked计数、分类、精确storage_id/run_id/timestamp target均正确 |
| 有界就绪验收 | 最近5实际来源日09-23、24、28、29、30，两层10个readiness全部ready；未逐日扫描739日readiness |
| 全量真实APPLY重放 | 5.7220秒/207读，新增分区/event均0；1478物化的ID/timestamp及40检查自身record ID/event timestamp、target和metadata前后相同 |
| 样本保留 | 原两日4物化、4检查自身身份和target均不变，原样本checkpoint hash=8ee3e111b3306d9145fdde93b68e6d9acd2337358c2bb9764f83bfc72e10d4e0 |
| 进度/恢复 | 首次APPLY1723条真实进度记录，完成量单调；逐事件checkpoint持久化，最终complete/2257/100%，重放后同样complete |
| 时间/内存/磁盘 | 全部驱动含预检/登记/读回/重放39.1292秒，峰值RSS433930240B约413.8MiB；staging空闲2928876863488B，未触发预算拒绝 |

207是helper native读预算值，不含native写内部SQL、源proof的hash/SQL、sensor维护和额外聚合读回，不冒充总PG SQL次数。本次实测完成的就是冻结739日范围，不把26.54秒作为未来规模的固定SLA，也未重新做正式故障注入；取消/退出/续跑边界继续引用§46的隔离验收和此前样本。

三个DC sensor原生状态未启用、当前导入默认STOPPED；写前/后/重放后106项sensor name/status库存一致，两job active guard每批通过。60份相关源码、83份实际加载源码与5883ae7a及原验收hash相符，1146份源码/测试快照不变。DG正式code-location进程源码没有另行核验或reload，本次是新进程直接调用已提交helper，不是正式job/sensor evaluation。

DC冻结1478文件/70542522字节、82控制仍匹配P3，最近20来源日深核按原协议进行；没有对739日全量重新做标准化深核SQL。包括原三表在内5408份Lake/control hash与49份既有报告/清单逐字保留。原大盘839键/1678物化/40检查、THS行业494键/988物化/40检查、THS概念495键/990物化/40检查的原生ID/timestamp摘要前后相同，未扩展到其他表。正式Parquet/Prod/Tushare/source/job/sensor/reload/pool操作均0；只新增本DC分区/event及全量plan/checkpoint和锁。

完整审计、逐日原生身份/计数、sample保留、真实重放、源码与临时驱动/日志hash归档[全量正式登记证据](../../reports/moneyflow_p4_ind_dc_event_registration_formal_full_evidence_20261012.json)。本轮验收文件和两份方案的收尾变更尚未提交；先前24个文件已提交5883ae7a，未推送。文档完整性、链接/hash与限定diff另列报告，不重复运行源码未变的产品测试。

### 48.3 切片关闭与后续边界

**moneyflow_ind_dc的P4全量历史登记及本表历史接入阶段关闭。** 历史源缺口按冻结实际范围保留；最近20来源日有green check，不宣称更早日期已有事件check ready。资产/check/job/catalog、默认STOPPED sensor/readiness、预演、执行器、两日及全量正式登记已分别验收，原方案硬口径由固定身份/清单、native集合/metadata/target、历史scope SQL/P3证明、持久化checkpoint与幂等重放一一落实。

整个P4仍开放，P5真实日更未进入。下一开发切片按原顺序推进moneyflow_dc的独立Raw/Silver资产、checks、jobs和catalog，先审计已验收P2/P3的字段/日期/文件及实际消费者，再列影响面和专项验收；不自动启用本表sensor或日更，也不夹带另两表。正式操作继续按各自精确清单批准。


<a id="moneyflow-dc-p4-definitions"></a>

## 49. P4东财个股独立定义接入（2026-10-12）

### 49.1 开发目标、范围与前置审计

管理员要求先提交板块全量收尾，再推进moneyflow_dc的P4接入。上轮三份收尾文档/报告已提交4486b08f，未推送。本轮只接入moneyflow_dc的独立Raw/Silver、两条blocking check、两job、专属动态分区与catalog；传感器、历史预演/登记及正式日更分后续切片。依据§6的逐表7A卡、§14的P2真实源验收、§28的P3逐日物理验收与原方案，不改变源字段、请求模型或历史导出方式。

CodeGraph explore核查assets/moneyflow_ind_dc.py及update_daily_moneyflow_raw/update_daily_moneyflow_silver，impact追踪共享发布入口；索引遗漏的别名消费者用当前代码引用审计补齐，包括THS行业/概念、DC板块assets、daily请求/候选/审计、catalog、Definitions加载和测试。Source readiness、daily schema、15字段schema及标准化checks均已支持moneyflow_dc；只扩展正式daily publisher的固定允许集合，不重写已验收P2管线，不新增兼容路径。新增定义文件自动由现有Definitions loader加载。Prod DatasetDefinition/ExecutionPlan、业务API、前端与主体依赖矩阵不变。

### 49.2 硬口径、代码点与验收

| 硬口径 | 落地代码 | 正向/负向验证 |
| --- | --- | --- |
| 每源独立数据集，两层两job/check及专属分区 | assets/checks/jobs/moneyflow_dc.py、partitions、catalog/name_mapping、moneyflow check names | Definitions加载、精确job选择、catalog、独立分区，不执行其他数据集 |
| 15源字段，日期+股票代码主键；名称可空；金额万元，保留NULL/负值，不重算 | 既有moneyflow_daily schema/request/candidate/audit；新definition metadata | 存档实测6024行全字段读回，BJ348/SZ3154/SH2522；同名不同代码允许，同码不同名拒绝；缺字段/空代码/重复键/越日期拒绝 |
| 单日全市场，不按对象池/板块/市场切割 | 既有daily_request_scopes=(None,)、显式fields和单日分页 | 源参数严格只有trade_date/limit/offset；2000整页必须取空尾页；两轮行序改变可接受、字段变化拒绝 |
| Raw稳定后发布，Silver只读同日最新绿Raw及匹配hash，日期唯一转换 | 既有daily update、公用writer锁/receipt/checkpoint；独立Raw check与Silver门禁 | 错日期、旧check、失败check、hash变更、字段不等均拒绝；原生检查target精确对应物化 |
| 逐文件原子提升、可恢复且不污染其他源 | 既有candidate/file hash/atomic replace/checkpoint；dataset命名空间 | replace后退出与意图后取消续跑不重采；幂等/修订与异源receipt隔离；未批准数据集写前拒绝 |

无新增配置项。复用MONEYFLOW_WRITER_POOL现有并发池、固定64请求/300秒/20000行、512MB单线程DuckDB无spill、RSS768MiB及已有正式Lake/staging根；配置来源和所有消费者沿用原moneyflow run contract与paths定义，既有预算测试继续回归。新增分区名与check名只是独立身份，不是运营可调配置。

一日是执行unit，候选和checkpoint逐文件持久化，不开全历史事务。固定分页2000；6024行两轮8次请求，60秒稳定间隔，20000行整页需空尾页，两轮最多22次页请求，仍受包含重试的64请求/300秒总预算限制。超过行数、时间、内存或源不稳定立即拒绝发布；本轮隔离时钟不能外推正式网络耗时。P3已有739实际来源日、每层4278673行，缺口2023-11-22保持；本轮不会重生成历史文件。

隔离验证使用现有项目.venv、fake source/clock、临时Lake与SQLite instance；完整受保护catalog/static、其他已接入四表及P2回归、隔离Definitions、Ruff和文档完整性门禁必须通过。正式物理只读抽验一个既有日期，不能当作正式job运行验收。旧报告不改。正式instance/PG/event/分区、Lake与staging control写入、reload、sensor启用、pool配置及Tushare请求均为0。

Dagster依据：[asset metadata](https://docs.dagster.io/guides/build/assets/metadata-and-tags)、[partitioned blocking checks](https://docs.dagster.io/guides/test/asset-checks)、[dynamic partitions](https://docs.dagster.io/guides/build/partitions-and-backfills/partitioning-assets)。复用现有项目版本已使用的API，并以隔离原生执行确认，不安装/升级依赖。执行后追加实测结果；P4整体开放、P5未进入。


### 49.3 接入验收完成，正式登记未进入

moneyflow_dc的两层资产、两job、两条分区blocking check及专属cn_a_moneyflow_dc_trade_days已经接入。catalog新增两条物理文件合同与两个分区模型，使用既有15字段schema；name_mapping标注东财个股。共享daily publisher只新增固定moneyflow_dc允许项，原三表消费者与拒绝未知来源边界保持。完整catalog消费者测试同步补入这两个实际资产，受保护启动器只新增三份定义源码到精确只读清单，不放宽正式资源或网络权限。

| 验收 | 当前实际结果 |
| --- | --- |
| 独立原生定义/job/check | 39项通过；job仅选择自身一层，两个checks归属同日，原生target的storage_id/run_id/timestamp精确匹配物化 |
| 存档真实源行完整读回 | 2026-09-30的6024行，两轮分页8请求，第二轮倒序仍一致；Raw/Silver各6024行，15字段全值一致、reject0；SZ3154/SH2522/BJ348，未裁剪市场 |
| 单位、身份、缺值 | 金额万元，源net_amount不按分项重算，NULL名称和数值、负值保留；同名异码允许，同码异名拒绝，错日期/空代码/缺字段/板块多余字段/不稳定源阻断 |
| Raw到Silver门禁及恢复 | 无绿Raw、其他日期、过期或失败check、物理hash变化不生成Silver；字段差异check失败。两层replace后退出、意图后取消续跑、幂等修订及异源receipt隔离均通过 |
| 原链回归 | 原四表P4定义与七表P2候选测试共683项通过，89.80秒；moneyflow_dc原P2保留113项精度/20000行/22请求/分页/时间/取消/预算验证 |
| 完整受保护门禁 | catalog12项/504子断言及static113项通过，全部原生resource gate和denied区域不变；隔离完整Definitions加载通过，改动文件Ruff及全DG致命错误检查通过 |
| 正式物理只读 | 同日两文件各6024行/6024唯一键，15字段Raw/Silver保真，P3原hash和bytes匹配；0.2482秒，写前后hash不变，不访问正式instance、不运行正式job或check |
| 证据稳定性 | 最终1150份DG源码/测试hash在完整门禁期间不变，原49份资金流报告逐字保留；CodeGraph根索引同步及impact复核完成 |

存档样本两个job用fake source/clock、临时Lake和native SQLite执行1.0224秒，不把它说成真实盘后请求性能或正式日更验收。正式物理Raw=70fda8fd7a63552c3b5d5ea99e48cf1583ed5fc207f9a21f85e68da7f72afad4、Silver=ac089a2ddd393bce9429e38d0ca5daab80a03d022418c66fd5e77515f91714f2，分别406655/406631字节，与P3原样本证明相同。历史739日全范围的P4登记尚未执行，不用单日抽验推断全量event ready。

初轮测试有一项把重复身份reason误写为duplicate_identity，既有审计实际按file_count_date_or_key拒绝；测试对齐既有合同后39项全部通过。初轮catalog发现显式消费者清单未包含两个新资产（146对144）；补齐真实资产后完整12项/504子断言通过，未减少测试或放宽断言。受保护启动器的独立macOS沙箱不能在工具沙箱内嵌套启动，按工具提权运行原有拒绝策略通过，无业务操作或安装权限扩展。

[本轮报告](../../reports/moneyflow_p4_dc_evidence_20261012.json)归档源样本、原生job/check、物理只读、源码/旧报告hash和门禁证明。无Prod合同、Web/API或依赖矩阵变更，无新增配置、源请求、正式Lake/staging control/PG/event/分区写入，无reload、sensor启用、pool配置或正式job执行。上轮收尾提交4486b08f未推送，本轮新增接入修改未提交。

本切片已关闭，P4整体保持开放、P5未进入。下一切片接本表三个默认STOPPED sensor、专属file/event readiness和739历史来源日的有界只读预演；仍沿22:00登记当日分区、最近10日期和单tick单run口径。之后再开发登记执行器及两日/全量冻结清单，正式执行按精确阶段清单批准。


<a id="moneyflow-dc-automation"></a>

## 50. P4东财个股sensor、就绪判断及739日只读预演（2026-10-12）

### 50.1 本轮授权、命名与硬口径

管理员要求先提交上一切片，再继续本表三个STOPPED sensor、就绪判断和739历史来源日只读预演。资产切片16个文件已提交0e432a94，未推送。本轮沿§6/§14/§28/§49及新增DG模板7A，新增固定STOCK_DC_MONEYFLOW_AUTOMATION、三个sensor、独立readiness/preview薄入口与测试；原方案和LLD先落本节，再编码。正式登记执行器、两日/全量冻结APPLY清单留到下一切片，本轮不触发正式job/sensor evaluation，不reload、启用、改pool、注册分区或补event。

| 硬口径 | 实现与正反验收 |
| --- | --- |
| 每源独立身份、默认STOPPED、sensor不请求源 | sensors/moneyflow_dc_sensor.py：cn_a_moneyflow_dc_trade_day_sensor、raw_tushare_moneyflow_dc_update_job_sensor、silver_moneyflow_dc_update_job_sensor；间隔600秒、resources只有lake_root/duckdb，定义与Source调用次数反例 |
| 标签统一且为静态分类 | build_sensor_tags：quote_data / partition / partition_registration，quote_data / raw / asset_update，quote_data / silver / asset_update；同步治理/拓扑HTML与完整static清单 |
| 上海22:00登记当天，最多再补一历史漏日 | 复用register_moneyflow_trade_days，固定cn_a_moneyflow_dc_trade_days，history_start=2023-09-11；22点前/假日/起点前/异源分区反例，输出SensorResult不调用写接口 |
| 更新仅最近10交易日，每tick最多一个单日job | 复用evaluate_moneyflow_update：SSE日历、2026-10-01起点、DESC LIMIT10、当日优先；active job阻断，不在热路径查739日期 |
| 最新同日物化+完整green check+物理hash才ready | asset_guards/moneyflow_dc_readiness.py封装batch_moneyflow_readiness；target storage_id/run_id/timestamp精确匹配，blocking/通过、无symlink/hash匹配，Silver绑定对应Raw hash；跨日/旧check/错hash/上游修订/超限反例 |
| cursor与有限重试独立 | dataset/layer固定身份，8KiB硬上限，原生run key为每日6次权威计数；丢cursor不重置尝试，临时错误重试，权限/字段/精度失败人工处理 |
| 历史只用实际来源日，不补缺口或拼资金值 | bootstrap/moneyflow_dc_event_preview.py复用P3冻结proof：739日期、每层4278673行、46unit、1478文件；2023-11-22缺口保留，最近20日核查date+ts_code/15字段及冻结每日行数，proof entry含row_count但不含板块scope |
| 原证明/事件不改，已有事实不匹配则拒绝 | 固定history-full-20261009、cutoff2026-09-30、cohort05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618；全文件/control hash、精确原生mat/check及batch集合查询；冻结文件/control/cohort、event hash/target变化反例 |
| 原consumer完整回归，无正式写路径 | 固定合同只加本表；旧四表revision/身份/metadata/文件预算保持，完整catalog/static与隔离Definitions。正式readonly adapter禁止自动DDL和事务写，仅包裹三类native读取，旧报告逐字保留 |

CodeGraph explore/impact已核查sensor、固定automation contract与batch readiness；索引对别名/属性消费者不完整，用当前代码引用补齐selector、history proof、event plan/engine、四表固定adapter和测试。新增合同保持现有class shape和旧四表revision不变；本表event_revision=stock_moneyflow_dc_history_events_v1作为独立身份，未增加正式执行adapter。Prod DatasetDefinition/request builder、Web/API/CLI及主体依赖矩阵不变。源字段、请求策略、万元单位、NULL/负值/北交所保留沿已验收P2/P4，不新增源请求。

### 50.2 性能、配置与正式只读边界

| 项目 | 成本、上限与拒绝策略 |
| --- | --- |
| 新固定预算审计 | MONEYFLOW_DC_READINESS_FILE_MAX_BYTES=4*1024*1024，唯一源码声明run_contracts/moneyflow.py，无env/Settings/数据库/运营覆盖；唯一生产消费者batch_moneyflow_readiness的固定moneyflow_dc分支，随definitions加载生效；超限返回file_hash_budget且不hash，UI/日志通过cursor reason显示 |
| 预算依据与影响 | 已实测6024行单日Raw406655B/Silver406631B，超过旧64KiB；按20000行样本比例约1.35MB/文件，4MiB为有界余量，不承诺任意字符串长度。市场/THS行业/概念仍64KiB，DC板块仍其独立4MiB，新旧预算分别正反验证 |
| 日更tick | 最多2mat+2check（limit100）+2active run（limit1）+1partition+1日历SQL，最多20文件/80MiB顺序hash，无Tushare请求；Raw提交时额外1个选中日run records及临时错误时1个failure记录读取，不称只有7次总查询；10日期fixture实测目标<2秒、cursor<2KiB，硬上限8KiB |
| 历史proof | 仅本表46已完成unit、1478文件/585570020B hash、94份cohort/progress/逐unit控制证明；最近20日做标准化全字段SQL及冻结行数核查，其余依赖P3完整schema/主键/值证明+当前hash，不逐日期重新扫描全明细 |
| 历史native读取 | 1partition+每层ceil(739/100)=8次mat+每层1次recent check=19次helper读取；单批100日期、limit100、记录截断/既有revision/target不匹配拒绝；无739日期逐日readiness循环 |
| SQL/内存/事务 | DuckDB512MB/1线程/no-spill，RSS768MiB；单unit120秒，原生PG statement_timeout10秒/default_transaction_read_only=on、should_autocreate_tables=False；预演驱动总120秒包络，无正式写事务 |
| 持久化/取消/恢复 | 只读取消每文件检查，可中断后从同一冻结事实重跑；不建正式锁、目录、plan或checkpoint。已有writer锁只用rb共享锁避免并发历史修改；报告/驱动/日志仅/tmp及仓库，不引入状态实体 |
| 实际验收 | isolated fake source/clock/native SQLite：身份、22点/假日、重试、check/hash、10日batch成本与旧链；正式739日只读预演及同事实重跑，全物理/control/旧报告hash不变，无Prod/Tushare访问 |

正式驱动工作目录lake_console/orchestrator，命令`.venv/bin/python3 -B /private/tmp/moneyflow-dc-automation-20261012/formal-preview.py`，用既有/Users/congming/.goldenshare/dagster_home/dagster.yaml的readonly native adapter，固定Lake=/Volumes/datasource/data_lake、staging=/Volumes/datasource/data_lake_staging，仅读本表两asset/check和分区。写范围只有/private/tmp日志JSON及本轮仓库报告。正式源API、分区/event/正式文件/staging control、job/sensor/reload/enable/pool全部0。

官方依据：[Dagster sensors](https://docs.dagster.io/guides/automate/sensors)、[dynamic partitions](https://docs.dagster.io/guides/build/partitions-and-backfills/partitioning-assets)。default STOPPED与run_key不是正式执行证据，当前SDK与隔离native验收决定实际语义。以下据执行结果回填，不预填通过，P4整体开放、P5未进入。


### 50.3 本切片验收通过，正式登记尚未执行

三个sensor已按独立moneyflow_dc身份接入，默认STOPPED、600秒最小间隔和quote_data静态标签通过完整定义/static校验。注册器保持上海22:00后登记当日、最多再补一历史漏日；SSE假日、22点前和2023-09-11起点前不会登记当天或越界日期。更新器只取最近10交易日、每tick至多一个单日job；sensor资源没有Tushare，Silver只消费同日最新绿Raw及对应hash。

就绪判断核对最新同日物化、SUCCEEDED/passed/blocking检查、target的storage_id/run_id/timestamp和物理文件hash，不能只凭文件存在放绿。跨数据集或层cursor、旧check、错hash、Raw修订、过大文件、饱和截断和既有event不匹配均拒绝；6次持久化run key的重试上限不因cursor丢失重置。共享合同只增加固定本表身份，旧四表revision和readiness预算不变；本表4MiB预算超限在hash前拒绝。

| 验收项 | 实际结果 |
| --- | --- |
| 新sensor/readiness/history preview测试 | 51项通过，31.22秒；包括实际来源日期不补缺口、最近20日冻结行数变化拒绝、739日19次有界读取、旧四表revision不变 |
| 原链回归 | 四表sensor/preview/可恢复事件执行器及本表已提交definition测试共381项通过，300.34秒；使用隔离Lake/staging/native SQLite及现有项目.venv |
| 十日热窗口 | 存档6024行样本复制到10个隔离日期，20个真实原生job/check；tick读取2mat+2check+2active run+1partition+1日历SQL，20文件/8132860B hash，0.0247秒，cursor570B，源请求0 |
| 739日正式只读预演 | 两遍一致：Raw/Silver各4278673行，46unit、1478文件及585570020B完整hash、94份控制证明不变；最新20来源日15字段/date+ts_code/标准化及冻结行数一致 |
| 正式预演成本 | 每遍1partition+16批mat+2check=19次native helper读，分别1.6939/0.8047秒；最长文件424480B，低于本表4MiB上限，无正式写入 |
| 正式就绪状态 | 最近10来源日独立只读判断共4次native查询，两层均file_without_materialization、ready=false；文件完整不等同历史事件已登记 |
| 待登记数量 | 739partition、Raw739+Silver739物化、最近20日/层共40checks；合计1518条event、2257个登记unit，2023-11-22不造空分区 |
| 完整受保护门禁 | catalog12项/504子断言、static113项/15批全部通过；每批resource gate、denied区域不变和退出码均通过；仅新增三份精确允许源码 |
| 完整性 | 隔离Definitions加载、改动Python Ruff、全DG致命错误、文档完整性和diff空白检查通过；最终1155份DG源码/测试hash在最终门禁期间不变，原50份报告逐字保留；CodeGraph根索引同步完成 |

[本轮证据](../../reports/moneyflow_p4_dc_sensor_event_preview_evidence_20261012.json)归档两遍正式proof、1478文件/94控制hash、native查询数、逐日冻结行数、十日窗口和完整门禁。正式PG使用只读事务、should_autocreate_tables=False；已有writer.lock只读共享打开，没有创建正式目录、锁、plan或checkpoint。正式file/control/partition/event写入、源请求、job/sensor evaluation、reload/enable/pool变更均为0。默认STOPPED是源码定义状态，不能据此声称正式workspace已加载或持久化sensor状态已复核。

隔离十日日期是合成未来日期，6024行来自既有实测归档；25毫秒不能外推实际盘后网络请求耗时或正式日更已验收。历史最新20日追加全字段SQL，其他日期依赖P3已验收证明与本轮全文件hash；不声称重新向源端逐证券查全历史。初轮测试复制时误把600秒断言改成800，修正测试后51项通过，产品间隔没有修改；临时readiness报告字段名修正后只读核验通过。

上一资产切片已提交0e432a94，未推送。本轮sensor/readiness/预演代码及文档/报告尚未提交。本切片关闭，P4整体仍开放、P5未进入。下一切片开发本表可恢复历史登记执行器、隔离两日样本和739日冻结全量执行清单；正式APPLY及sensor启用仍按精确阶段批准，不把这次只读预演当作执行授权。


<a id="moneyflow-dc-history-events"></a>

## 51. P4东财个股可恢复历史登记执行器、两日样本与739日冻结清单（2026-10-12）

### 51.1 编码前目标、依据与硬口径

上一sensor/readiness/只读预演切片16个文件已提交06a68313，未推送。管理员要求继续本表历史登记执行器、两日样本和739日全量冻结清单。本轮按§6/§14/§28/§49/§50及DG模板7A，开发固定入口、沿现行恢复协议做隔离native SQLite样本/容量验收，并从正式PG只读构造样本和全量PLAN。两日正式APPLY、本表全量正式登记及任何reload/enable/job不在本轮范围，不能把清单冻结当成正式执行。

| 硬口径 | 真实代码点与正反验证 |
| --- | --- |
| 单独本表身份、默认只读 | 新bootstrap/moneyflow_dc_event_plan.py和moneyflow_dc_events.py绑定STOCK_DC_MONEYFLOW_AUTOMATION，复用build/validate_moneyflow_event_plan与report_moneyflow_history_events；apply默认False且只接受bool，拒绝其他四表plan及错误storage/revision |
| 完整冻结事实，不补缺口 | 739个实际来源日，每层4278673行；plan固定P3 operation/cutoff/cohort、94control hash、每日期两文件hash及row_count；重建验证阻断篡改日期/行数/hash/control/instance，2023-11-22不造空日期 |
| 原生metadata与物理计数一致 | 复用_materialization/_evaluation与history_schema；15 observed_columns、row_count/source_row_count、checked_row_count与target三字段；不加入板块scope_row_counts。共享engine两处daily行数守卫加moneyflow_dc，原四表逻辑保持；假既有/源count不能复用或发布绿check |
| 只最近20来源日补check | 旧日期只登记物化；最近20日复用同日15字段/date+ts_code标准化SQL与冻结行数后才发布绿check。739日容量检查40事件，早期日期不强行日更全证券覆盖或补check |
| 逐unit持久化与恢复 | 分区100日一批、event逐条native提交；原namespace writer锁、plan/checkpoint原子保存复用，无全历史数据库事务。取消每读/写前后检查，真实子进程事件后退出/缺失checkpoint/保存失败/观察失败后按native差分续跑，幂等不重复且不删除事件 |
| 运行预算与进度 | 复用4096工作项、600秒总、120秒批、256 metadata读、100日期/批、limit100、DuckDB512MB/1线程/no-spill、RSS768MiB；当前stage/date/layer/completed/total/percent/updated_at持续输出；预算耗尽、active/writer冲突阻断 |
| 全消费者和隔离门禁 | CodeGraph explore/impact加当前引用补齐四固定adapter、plan/proof/engine/readiness/tests；新本表events测试、旧四表events及本表sensor/preview回归；受保护runner只加两个精确源码，不放宽拒绝policy，catalog/static/defs/Ruff/docs均验证 |

CodeGraph解析到共享planner的四固定入口与writer直接调用方，但对partial别名和部分测试消费者不完整；已用当前代码引用补齐所有实现方/测试。新增薄入口不改变共用函数签名、现有plan形状、旧四表revision/metadata或已冻结清单。Prod DatasetDefinition、请求builder、API/CLI、资源/资产/check/sensor/分区定义和主体依赖矩阵均不改；本表15源字段、万元/NULL/负值/北交所沿P2/P4，不新增源请求。

### 51.2 成本、配置、恢复与正式只读边界

| 项目 | 本轮测算与拒绝策略 |
| --- | --- |
| 正式范围 | 739来源日、4278673行/层、1478既有文件/585570020B；0证券枚举、0源请求/分页/Parquet生成；739partition+1478materialization+40recent checks=2257工作项/1518event，低于4096 |
| 两日样本 | 2026-09-29为6023行，09-30为6024行，共12047行/层；2分区+4物化+4check=10项/8event；隔离样本另用6023/6024归档fixture，不冒称正式执行 |
| proof与SQL | 每次build/validate重建1478文件hash及94controls，最近20日全字段标准化+冻结计数SQL；执行检查阶段另核20日，不对739日逐分区readiness。Python只编排日期/hash/事件，不读取427万行明细，spill0 |
| native只读成本 | 两日默认预检7 helper读含2active，全量21读含2active；100日批/limit100防截断。相同facts反复重构必须得到相同plan_hash，旧四表八份冻结PLAN再验证保持原hash |
| 739日隔离容量 | 早期719合成日期各1股票行，最近20日期完整6024行fixture，共121199行；临时SQLite需完成2257项/1518event，预计207 native读、17phase batch、1546次原子控制保存，全部低于既有预算。必须记录耗时/RSS/每save成本，不能外推正式PG APPLY耗时 |
| 持久化/取消 | 单事件提交即事实，逐event checkpoint最多256KiB，frozen plan最多32MiB，原子写入+fsync，100日期批最多120秒；进度/checkpoint失败保留已提交事件，续跑原native状态差分，不依据checkpoint跳过实际检查、不删除event回滚 |
| 配置与互斥 | 无新增env/Settings/DB/run config；固定STOCK_DC合同和原event预算/paths/namespace writer锁沿既有已审计消费者，旧预算/revision保持。历史登记运行与本表daily两个job互斥active guard；只读driver已有writer.lock以O_RDONLY共享锁，不新建正式锁或events目录 |
| 正式只读 | daily_basic_event_instance(writable=False)，既有本机goldenshare_dagster，强制readonly、10秒SQLtimeout、禁自动DDL；仅原storage identity、分区、mat/check和两job active查询，report(...apply=False)。只写/private/tmp日志及仓库reports两PLAN，不改正式staging control |

正式只读driver从lake_console/orchestrator运行现有`.venv/bin/python3 -B /private/tmp/moneyflow-dc-events-20261012/formal-plans.py`，固定Lake=/Volumes/datasource/data_lake、staging=/Volumes/datasource/data_lake_staging、operation=history-full-20261009、cutoff=2026-09-30、cohort=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618，既有/Users/congming/.goldenshare/dagster_home/dagster.yaml readonly adapter。plan保存仓库reports，正式event目录库存/旧51份报告前后hash不变；正式源API、partition/event/file/control写入、sensor evaluation、job、reload/enable/pool/安装均0。

全量正式耗时尚未实测；临时SQLite容量和正式只读只证明本轮成本/一致性。样本以后执行后全量原plan不改，按native差分预计剩737分区+1474物化+36checks=2247项/1510event。正式APPLY前重新验证当前hash/storage/source、active状态、维护窗口、sensor未启用、空间与writer互斥；两日样本和全量分别按精确清单批准。

依据：[runless asset event](https://dagster.io/docs/api/dagster/internals#dagster.DagsterInstance.report_runless_asset_event)、[dynamic partitions](https://dagster.io/docs/guides/build/partitions-and-backfills/partitioning-assets)、[asset checks](https://dagster.io/docs/guides/test/asset-checks)。原生事件不归属于run，沿已批准直写补录模式，不称Dagster backfill；本地当前SDK隔离持久化/target读回决定实际行为。下面在验收后回填，P4整体开放、P5未进入。


### 51.3 执行器、两日隔离样本及739日容量验收通过

moneyflow_dc_event_plan.py与moneyflow_dc_events.py仅绑定STOCK_DC_MONEYFLOW_AUTOMATION，复用原build/validate/report主链，不复制锁、checkpoint、原子写入或事件机制。共享engine的两处每日行数守卫增加moneyflow_dc：既有物化的row_count/source_row_count和检查的checked_row_count必须匹配冻结每日行数；检查阶段全字段SQL返回行数必须相等。原四表metadata、plan形状、revision与预算保持；本表15个observed_columns没有板块分类字段。

| 验收项 | 实际结果 |
| --- | --- |
| 本表执行器与恢复 | 49项通过，74.04秒；默认只读、精确身份/预算/日期反例、取消及最终读时取消、子进程实际退出47、checkpoint丢失/伪造/保存失败、观察失败、幂等重放均通过 |
| 每日行数与metadata | 隔离两日6023/6024行，共12047行/层、10项/8event；四物化/四检查15字段、source/checked行数及target storage_id/run_id/timestamp一致，无scope_row_counts；四ready、reject0，重放新增0 |
| 反向边界 | 重算hash仍造假行数、错误native物化/source/check计数、错上游hash、失败/旧check、饱和记录、异instance/control/file、active/writer冲突、非bool apply和其他四表清单均拒绝，不覆盖既有event |
| 739日期容量 | 临时SQLite完成739分区+1478物化+最近20日40检查=2257项/1518event；719个合成日期各1股票行、最近20日期完整6024行归档，共121199行；旧日期无check，来源/Parquet不改、幂等重放不重复 |
| 容量实测成本 | 最终运行8.8395秒，207次helper读，batch最大100；峰值RSS640630784B（约611MiB），低于768MiB；1546次原子控制保存共0.6088秒、最慢8.527ms |
| 原链回归 | 原四表events与本表sensor/preview共233项通过，236.25秒；旧四表八份正式冻结清单重建验证通过且hash不变 |
| 完整受保护门禁 | catalog12项/504子断言、static113项/15批通过；17批resource gate/denied区域/退出码均通过；runner只增两个精确bootstrap路径，拒绝policy与断言不放宽 |
| 完整性与稳定性 | 隔离Definitions、改动Python Ruff、全DG致命错误、文档/链接/空白门禁通过；最终1158源码/测试hash在最终门禁与只读PLAN期间相等，旧51份报告逐字保留；CodeGraph根索引同步完成 |

两日隔离样本使用既有09-30真实归档fixture复制到合成日期，首日截取6023行；用于检验不同每日计数、字段/target和幂等，不声称这些值就是正式09-29源行。正式两日清单来自原P3冻结的真实每日文件与行数。容量测试验证739日期编排/恢复及最近20日完整行规模，不把121199隔离行等同正式4278673行，也不外推临时SQLite8.8秒为正式PG APPLY耗时。

### 51.4 正式只读两日与全量冻结清单

正式PG使用既有goldenshare_dagster只读连接、10秒SQLtimeout、禁自动DDL，仅读原storage identity/分区/mat/check及两job active状态；已有writer.lock以O_RDONLY共享打开，没有创建正式锁/events目录。两PLAN从P3 operation=history-full-20261009、cutoff=2026-09-30、cohort=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618重建，保存仓库reports时先完整读回校验，再原子冻结；JSON读回和再次构造相等。本表1478文件/585570020B与94控制hash保持。

| 冻结清单 | 精确范围、当前缺项与成本 | plan_hash |
| --- | --- | --- |
| [两日样本](../../reports/moneyflow_p4_dc_event_registration_sample_plan_20261012.json) | 2026-09-29为6023行、09-30为6024行，共12047行/层；2分区+4物化+4check=10项/8event；22105B，默认预检0.7806秒/7读含2active，生成/验证/重构3.5328秒 | 5624f20348a7bb103cd620a92fce765f638c2763f74fa5a46109d06aa9c0ebbb |
| [739日全量](../../reports/moneyflow_p4_dc_event_registration_full_plan_20261012.json) | 2023-09-11～2026-09-30，4278673行/层、每日2812～6106行；739分区+1478物化+40最近check=2257项/1518event；404934B，默认预检0.8694秒/21读含2active，对应全过程2.9459秒 | 5ce84b78a5f9f9960d520400e6485ff71dd78018c85efbf19b52afd71e87642c |

包括旧四表八份清单再验证，正式只读driver共9.7319秒；正式events目录文件库存前后相同。2023-11-22未进入清单，不补空记录。源请求、正式分区/event/Parquet/staging control写入、job/sensor evaluation、reload/enable/pool/安装全部0。两日和全量APPLY均未执行，不能把文件完整或预检通过说成已登记。样本正式成功后全量计划hash保持，根据native差分预计剩737分区+1474物化+36checks=2247工作项/1510event。

默认只读样本预检入口（lake_console/orchestrator，现有项目.venv，禁同步/下载）：

```python
import json
from pathlib import Path
from orchestrator.defs.bootstrap.daily_basic_event_instance import daily_basic_event_instance
from orchestrator.defs.bootstrap.moneyflow_dc_events import report_stock_moneyflow_dc_history_events
plan = json.loads(Path('../reports/moneyflow_p4_dc_event_registration_sample_plan_20261012.json').read_text())
assert plan['plan_hash'] == '5624f20348a7bb103cd620a92fce765f638c2763f74fa5a46109d06aa9c0ebbb'
with daily_basic_event_instance() as instance:
    print(report_stock_moneyflow_dc_history_events(instance=instance, plan=plan))
```

### 51.5 计划对账与下一阶段准入

固定身份/默认只读由两个薄入口、实际storage/hash重建与四表交叉负例验证；每日计数/15字段由冻证明、共享SQL守卫、metadata/target及native错误计数反例验证；批次和最近20日检查由739容量及207读验证；取消/退出/观测失败与幂等由native SQLite持久化和真实子进程验证；正式范围/文件/控制事实由只读PG预检及两份冻结PLAN、旧八份清单再验证证明。所有硬口径完成，无Prod合同、API/CLI、主系统依赖矩阵、资源/资产/分区或日更合同改动，无新增配置。

[本轮验收报告](../../reports/moneyflow_p4_dc_event_registration_evidence_20261012.json)保留完整代码快照、隔离容量/样本、原生门禁和正式只读proof/plan证据。上一切片已提交06a68313，未推送；本轮新执行器、测试、文档和三份报告尚未提交，其他任务修改保留。

本开发切片关闭，整个P4开放、P5未进入。下一阶段为按冻结两日样本清单获批后正式登记：写前核验本表三个sensor持久化状态未启用、两job无active、维护窗口、writer互斥、当前源码/storage/hash及staging空闲大于32MiB；样本必须读回4mat/4check的partition/target/source与checked计数、四readiness和幂等重放。样本批准不包含全量、reload、sensor启用、pool或日更job；样本验收后再独立推进同一739日全量清单。


<a id="moneyflow-dc-formal-sample"></a>

## 52. P4东财个股两日正式样本登记（2026-10-12）

### 52.1 执行前清单与边界

管理员明确批准“按冻结两日清单执行，继续推进 moneyflow_dc 的正式样本登记和读回验收”。先将§51执行器、测试及两份冻结清单等10个任务文件提交为9f61abea，未推送；其他工作区修改保留。本轮不修改产品代码，目标是验证正式PG中历史文件的登记及就绪状态，沿用§51的固定adapter和共享可恢复执行器，不改变API、CLI、配置、依赖矩阵。

固定输入为[两日清单](../../reports/moneyflow_p4_dc_event_registration_sample_plan_20261012.json)，2026-09-29每层6023行、09-30每层6024行，合计每层12047行。plan_hash=5624f20348a7bb103cd620a92fce765f638c2763f74fa5a46109d06aa9c0ebbb，文件SHA256=ed911805fbfbc5dfe6deb8ffc00c3d97aaf860357d0d8c900dd43c5685a142c8。operation=history-full-20261009、cutoff=2026-09-30、cohort=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618均不变。写入上限为cn_a_moneyflow_dc_trade_days的2键、raw_tushare_moneyflow_dc和silver_moneyflow_dc的4物化，以及raw_tushare_moneyflow_dc_file_contract_check和silver_moneyflow_dc_standardization_check的4条blocking检查，共10项/8事件。临时驱动对两个写API额外限制为这两日和本表身份。

工作目录为/Users/congming/github/goldenshare/lake_console/orchestrator。只读预检完整命令为`.venv/bin/python3 -B /private/tmp/moneyflow-dc-formal-sample-20261012/run.py`；获准正式样本命令为`.venv/bin/python3 -B /private/tmp/moneyflow-dc-formal-sample-20261012/run.py --apply`，包含同清单幂等重放和读回。现有项目venv启动干净子进程，HOME位于临时目录，禁止环境自动同步、下载或安装。native adapter显式读取/Users/congming/.goldenshare/dagster_home/dagster.yaml，只连接既有本机goldenshare_dagster PG、关闭自动DDL；默认只读，仅两日APPLY及其重放使用writable=True，不加载scheduler/launcher。

| 门禁 | 本轮核验及失败行为 |
| --- | --- |
| 维护与身份 | 三个本表sensor导入默认STOPPED且native持久状态未启用；两个job无active；已存在writer.lock独占；1158份已验收源码/测试及实际导入源码hash一致。未核验code-location服务器源码，不把直接helper执行当成已reload。 |
| 文件与空间 | 既有正式Lake与staging根、同设备、非根symlink、staging空闲大于32MiB；94份冻结来源控制和1478个本表文件完整hash一致；已有四表物理证明、历史事件控制和55份既有报告保持。 |
| 有界成本 | 单SQL10秒、100日期/批、600秒helper总预算、120秒单批、256次helper native读取、RSS768MiB；DuckDB512MB/1线程/no-spill。临时驱动120秒上限；额外维护、四表原生读回和hash核验另行计量，不混同helper读预算。 |
| 正式写范围 | 只写本两日分区/8事件，以及既有staging/moneyflow/history-full-20261009/events/本样本plan_hash/plan.json和逐项checkpoint、既有writer锁；报告和进度写仓库reports或/private/tmp。正式Parquet、来源、job、sensor、pool、reload均无写入。 |
| 恢复与验收 | 分区批/单事件为提交unit；逐项原子checkpoint，取消或失败保留已提交事实，按同hash续跑；不手改checkpoint或删除事件。写后4物化/4检查逐条核对日期、15字段、行数、cohort/plan/file/upstream hash与storage_id/run_id/timestamp target，四readiness均须通过。同清单重放须0新增，旧四表原生事实身份不变。 |

全量清单只做差分只读预演，不执行全量APPLY。正式执行结果在以下追加，执行前不预填通过。依据已核对当前代码及CodeGraph的report_moneyflow_history_events、read_stock_moneyflow_dc_event_state、batch_stock_moneyflow_dc_readiness；官方[runless API](https://docs.dagster.io/api/dagster/internals#dagster.DagsterInstance.report_runless_asset_event)、[分区](https://docs.dagster.io/guides/build/partitions-and-backfills)、[checks](https://docs.dagster.io/guides/test/asset-checks)与现有SDK语义保持一致。


### 52.2 正式登记与读回结果

执行成功，实际新增2分区、4物化、4检查，10/10项完成，checkpoint为complete/100%。两日每层行数分别6023、6024，与冻结来源及检查计数一致；每条物化记录15个真实业务字段，没有板块scope字段。Raw/Silver物化ID分别为09-29的7452309/7452310、09-30的7452311/7452312。四条native检查均SUCCEEDED、passed=True、blocking=True，日期及storage_id/run_id/timestamp精确target与对应物化一致；file/cohort/checkpoint/plan/cutoff及Silver raw_sha256均读回相符。四个batch readiness结果均ready。

正式首次APPLY实测2.7752秒、53次helper native读、60条单调进度，整个驱动峰值RSS428621824B（408.8MiB）；同清单真实重放2.4057秒/53读，0新增键、0新增事件。重放前后物化ID、时间、check target及计数完全相同。逐项checkpoint用于恢复观察，原生持久化事实仍是续跑依据。本轮没有真实取消动作；取消/失败/退出恢复由§51隔离回归覆盖，不能把本次成功重放说成正式取消恢复演练。

三个本表sensor在native的106份记录中均没有持久化记录，当前源码导入默认STOPPED；这证明未发现启用记录，不证明正式code location已加载三个定义。本轮未reload或evaluate sensor；前后全sensor状态inventory hash一致。两个本表job各批active guard通过，既有writer锁独占。正式Lake1478个本表文件及94份来源控制与冻结证明一致；连同旧四表共6978份物理/控制文件hash保持，旧16份历史事件plan/checkpoint保持，55份既有仓库资金流报告逐字保持，1158份源码/测试及83份实际加载源码保持。旧四表全部原生分区/物化/check target身份读回一致，正式数据和其他任务工作区修改保留。

完整证据见[两日正式样本验收](../../reports/moneyflow_p4_dc_event_registration_formal_sample_evidence_20261012.json)。本轮文件变化只有本LLD、原接入方案及该新报告，未改变产品代码、API/CLI/配置或依赖边界。正式动作只有上述2键/8事件及本样本staging计划/checkpoint；来源请求、Parquet写入、job、sensor变更、pool配置、安装和reload均为0。

### 52.3 全量差分与下一阶段

[原739日冻结全量清单](../../reports/moneyflow_p4_dc_event_registration_full_plan_20261012.json)的plan_hash=5ce84b78a5f9f9960d520400e6485ff71dd78018c85efbf19b52afd71e87642c及文件SHA256保持不变。样本后正式只读预演0.8401秒/21次helper native读，确认已完成10项，剩737分区、1474物化、最近20来源日中余下18日的36检查，共2247项/1510事件。全量未执行；下一阶段按原冻结清单独立批准并重新核验维护/源码/物理证明后执行，保留本样本原生身份与检查target。全量PG耗时尚未经真实APPLY测量，不能将样本耗时直接外推承诺。

本两日正式样本阶段关闭；moneyflow_dc全量登记、整个P4和P5真实日更仍未关闭。硬口径已对账：精确身份/范围由冻结hash和固定adapter及临时写白名单保证，维护由native查询/active guard/writer锁保证，文件由冻结hash和现行DuckDB SQL保证，检查关联由native逐条读回保证，就绪及幂等由四readiness和0新增真实重放保证。无需管理员重新拍板本次已批准的两日范围。


<a id="moneyflow-dc-formal-full"></a>

## 53. P4东财个股739日全量历史登记（2026-10-12）

### 53.1 明确授权、固定清单与执行约束

管理员明确批准“按冻结全量清单执行，继续推进 moneyflow_dc 的全量历史登记和收尾”。本轮先将§52两日样本的两份文档及验收报告提交为e33a9c92，未推送，其他任务工作区修改保留。本轮只完成本表P4历史登记，不改产品代码、API/CLI、配置、资源或主体依赖矩阵；沿用已验收固定stock DC adapter和共享执行器。CodeGraph已复核report_moneyflow_history_events的调用链、native状态读取、逐事件提交/checkpoint、检查SQL和恢复边界，源码1158文件须仍匹配§51验收，实际导入源码须同时匹配e33a9c92提交。

[原739日冻结全量清单](../../reports/moneyflow_p4_dc_event_registration_full_plan_20261012.json)保持plan_hash=5ce84b78a5f9f9960d520400e6485ff71dd78018c85efbf19b52afd71e87642c、文件SHA256=5eb49184a8cb6089cdab5b0600405e7ad28bb3cbfe9ffd7cbbbfa362575d5987。实际来源日2023-09-11～2026-09-30，每层4278673行，1478个Parquet文件/585570020B，94份来源控制；2023-11-22缺口保留。operation=history-full-20261009、cutoff=2026-09-30、cohort=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618不变。全量总2257项，原样复用两日样本10项，只新增737个cn_a_moneyflow_dc_trade_days键、raw_tushare_moneyflow_dc和silver_moneyflow_dc的1474物化，以及最近20实际来源日中的36条对应blocking check，总2247项/1510事件；不额外造日期或更早check。

工作目录/Users/congming/github/goldenshare/lake_console/orchestrator，完整只读预检命令`.venv/bin/python3 -B /private/tmp/moneyflow-dc-full-20261012/run.py`；已获准正式全量命令`.venv/bin/python3 -B /private/tmp/moneyflow-dc-full-20261012/run.py --apply`，含同清单真实幂等重放及读回。现有项目venv/干净HOME、禁止下载同步安装；native adapter显式读取/Users/congming/.goldenshare/dagster_home/dagster.yaml对应的既有本机PG goldenshare_dagster，自动DDL关闭，默认read-only，仅全量APPLY及重放writable=True。临时写白名单限定本表冻结日期、分区/asset/check身份和full plan_hash，禁止重写样本两日事件。

| 门禁/成本项 | 实施和拒绝口径 |
| --- | --- |
| 维护和身份 | 三个本表sensor无启用持久状态，源码默认STOPPED；两job每批无active；已有writer锁可独占、取得锁后再次验证；源码、同一instance storage身份、冻结计划及文件hash一致。任一冲突停止保留事实，不切换分支或环境。 |
| 读取及来源 | helper21读预检，全量协议207次native元数据读已隔离验证；另读取维护状态、原四表有界native身份和本表集合/metadata；全1478文件及94控制hash与P3相符，深SQL限定最近20来源日，非739日逐日深扫。来源请求/分页0，无新业务行或Parquet文件。 |
| 时间、内存及空间 | 100日期/批、4096工作项、600秒helper总、120秒unit、256次helper native读、SQL10秒、RSS768MiB；DuckDB512MB/1线程/no-spill。staging既有、同设备、根非symlink、空闲大于32MiB；驱动660秒上限。真实全量耗时执行后记录，不以两日样本外推SLA。 |
| 写入和事务 | 单事件持久化/分区100日批，逐项原子checkpoint，无全历史事务。只写批准分区/event，以及staging/moneyflow/history-full-20261009/events/本全量plan_hash/plan.json、checkpoint和既有锁；进度逐项写/tmp并flush/fsync，报告写仓库。正式Lake只读，无Prod/Tushare、job、sensor evaluation/启用、pool或reload。 |
| 取消/失败与续跑 | 每批/读/事件前后既有cancel/time/RSS检查。中断保留native已提交unit和checkpoint，按原清单原hash幂等续跑；不删除事件、不手改checkpoint、不重建文件。观测回调失败不回滚已提交事实。 |
| 集合及metadata验收 | 核对739分区/1478物化/40最近check齐全、每日row/source/checked行数与15字段，cohort/file/checkpoint/cutoff/plan及Silver raw hash匹配；check partition和storage_id/run_id/timestamp target精确匹配。样本原生身份和原plan/checkpoint保持，旧四表身份保持。 |
| 有界就绪与幂等 | 最近5来源日09-23/24/28/29/30两层共10个readiness须ready；不做全历史逐日readiness。全量真实重放新增必须0，1478物化和40检查自身ID/timestamp/target前后不变。 |

原56份仓库资金流报告/清单、旧16份其他四表历史事件控制、本表样本2份event控制，以及6978份冻结物理/control文件保持。隔离正反测试与受保护门禁沿用§51且必须hash不变；本轮用正式读回验收批准动作，不拿正式资源做测试或故障注入。执行结果以下追加，不预填通过。


### 53.2 全量登记、验收和重放通过

上轮获批全量命令在聊天中断后继续运行，并正常退出，退出码0。没有重新启动全量APPLY；本轮先读回原进程完成结果，再单独执行无写入的复核。原冻结计划和实际完成事实如下：

| 验收项 | 正式结果 |
| --- | --- |
| 准入差集 | 已完成样本10项，缺737分区/1474物化/36检查；helper1.3279秒/21读，只读驱动4.2620秒 |
| 首次全量登记 | 2257/2257项完成，新增737分区/1474物化/36检查；27.5267秒/207次helper native读 |
| 聚合读回 | 739分区、1478物化、40最近检查齐全，缺口均0；Raw/Silver每层累计4278673行，各日row/source计数均匹配冻结清单 |
| metadata | 每条物化15个observed_columns，没有板块scope；cohort/file/checkpoint/cutoff/plan及Silver raw_sha256相符，样本仍用原sample plan_hash |
| 原生检查 | 最近20实际来源日的40条SUCCEEDED/passed/blocking，日期、checked计数、file/plan hash与精确storage_id/run_id/timestamp target正确 |
| 有界就绪 | 最近5来源日09-23/24/28/29/30，两层10个readiness全部ready；未逐日深扫739日readiness |
| 同全量清单重放 | 6.6044秒/207读，0新增键/事件；1478物化的ID/timestamp及40检查自身record ID/event timestamp、target与metadata保持 |
| 样本保留 | 两日原4物化/4检查自身身份与target不变，原样本plan和checkpoint未改；checkpoint SHA256=c8bbb5672c24af46b2ad77ebcdafce3cdb1c21a2030ebaab82e480635adc77f1 |
| 进度及成本 | 首次APPLY1723条真实进度，完成量单调；最终checkpoint complete/2257/100%。整个原驱动44.1049秒，峰值RSS391086080B（373.0MiB），staging空闲2928859779072B，未触发预算拒绝 |
| 恢复后只读复核 | 另开只读进程，helper1.1942秒/21读；整个复核3.5327秒，正式写入0。2257项齐全，原生身份/target/metadata与原APPLY后一致，10 readiness仍ready，full plan/checkpoint相符 |

207为helper预算内元数据读，不含写API内部SQL、来源proof hash/SQL、维护状态和额外native读回，不当作总PG SQL次数。27.53秒是这次精确范围的实测，非未来规模SLA。正式源文件没有重写；1478文件/585570020B与94来源控制保持P3证明，最近20来源日按原SQL/check语义核验，没有把739日期重新全部做标准化深核。更早日期保留物理和物化证明，不声称已有green check/event ready；2023-11-22历史缺口仍保留。

所有原四表native分区、物化ID/timestamp和check精确target前后一致；6978份冻结物理/control、56份旧仓库报告、旧16份四表event控制以及本表样本2份event控制保持。正式events目录只新增本full plan_hash的plan.json和checkpoint.json。三个本表sensor在106份native记录中仍无启用持久状态，当前源码默认STOPPED；两job active guard通过，前后sensor状态库存一致。68份相关源码和83份实际加载源码匹配已提交e33a9c92及验收hash，1158份DG源码/测试快照不变，未重复运行源码未变的隔离产品门禁。

只读复核的临时比较器起初将内存tuple与已保存JSON数组直接比较，造成旧四表比较断言误报；按JSON表示归一化后同一只读核验通过，失败日志保留在证据中。没有修改产品代码、事件或控制文件来规避问题。聊天中断不等同于正式执行取消；本轮没有在正式资源做故障注入，取消/退出/失败续跑能力仍由§51隔离回归证明。

完整原执行、恢复只读复核、逐日原生计数/身份、check target、样本保留及驱动/日志hash归档于[全量历史登记验收报告](../../reports/moneyflow_p4_dc_event_registration_formal_full_evidence_20261012.json)。本轮只变更两份原方案文档和该新报告，尚未提交；前一两日样本收尾已提交e33a9c92，未推送，其他任务工作区修改保留。

### 53.3 本表历史接入收尾与后续

**moneyflow_dc的P4全量历史登记及本表历史接入阶段关闭。** 独立Raw/Silver资产、checks、jobs、catalog、默认STOPPED sensor/readiness、只读预演、可恢复执行器、两日与全量正式登记均已分别验收。硬口径落点：固定身份和全量范围由原清单hash/adapter/临时写白名单保证；来源真实范围由P3冻结证明保证；逐日行数/15字段及检查关联由native读回与SQL保证；恢复边界由逐项checkpoint、原生事实为准和0新增真实重放保证；性能由207读/27.53秒/373MiB实际结果保证本次范围合格。

整个P4仍开放，P5真实日更未进入。下一独立开发切片按原顺序推进moneyflow_ths的P4接入，先按原模板审计其已验收P2/P3证据及当前消费者，列出资产/check/job/catalog的范围和门禁后实施。本轮不进入下一表，不reload、启用sensor、调整pool或执行正式job，不改变22:00日更设计；这些后续动作按各自阶段推进。


<a id="moneyflow-ths-p4-definitions"></a>

## 54. P4同花顺个股独立定义接入（2026-10-12）

### 54.1 开发目标、范围与依据

moneyflow_dc全量历史登记收尾三份文件已提交fea34b23，未推送。本轮按管理员指令推进moneyflow_ths的P4第一片：独立Raw/Silver资产、两条blocking checks、两job、专属动态分区和catalog。依据本LLD§6逐表7A卡、§15真实源验收、§28历史物理验收、原方案及现行数据集接入模板。sensor、readiness扩展、历史预演及登记执行器分后续片验收；本轮正式执行写入不在范围内。

CodeGraph explore核查相邻个股资产及共享日更入口，impact分析update_daily_moneyflow_raw；索引对别名消费者覆盖不足，直接当前代码补核四个daily资产、候选/请求/检查、测试、catalog和Definitions加载。P2已有13字段固定schema、单日分页及SQL标准化实现；本轮只给daily publisher增加固定moneyflow_ths允许项。原定义测试中尚未接入THS的负例同步移除，未知源/未接入moneyflow/异源receipt拒绝保留。没有Prod DatasetDefinition/ExecutionPlan、API或前端消费者改变，不改变主体依赖矩阵，不新增旧实现兼容路径。

### 54.2 硬口径、落点与验证预算

| 硬口径 | 实现落点 | 正向与反例验证 |
| --- | --- | --- |
| 一个源一个数据集，两层两job/check，专属分区 | assets/checks/jobs/moneyflow_ths.py、partitions、moneyflow check names、catalog/name_mapping | 完整Definitions/catalog；单job只执行本层；分区和检查归属本表，不混合DC或板块 |
| 13字段、日期+股票代码主键，名称可空，证券不裁剪 | 既有THS schema/daily request/候选/check；新定义metadata | 存档实测5215行全字段读回；SH/SZ保留，构造BJ允许；同名异码合法，同码异名、空码、错日、缺/多字段拒绝 |
| latest不改名，net_d5_amount保留源值；金额万元、NULL/负值不重算 | 既有13字段schema、SQL Raw/Silver标准化 | latest与5日净额逐值对账；构造源净额不等于分项和；DC close字段替换及关键字段篡改拒绝 |
| 单日完整结果，两轮稳定、明确fields，Silver不请求源 | 既有daily collector/publisher；专属资产/check | 仅trade_date/limit/offset，2000整页查空尾页，乱序通过、源值变化/空源拒绝；同日最新绿Raw与匹配hash才能写Silver |
| 每文件原子提升、checkpoint可恢复、其他源隔离 | 既有writer锁、run候选、receipt、publication；按dataset命名空间 | replace后退出、意图后取消、幂等重放和修订；异源receipt不复用、未知来源I/O前拒绝 |

配置审计：本轮没有新增配置。复用run_contracts/moneyflow.py的writer pool与2000页、20000行/轮、64请求（含重试）、300秒、两轮60秒间隔、DuckDB512MB/1线程/无spill和RSS768MiB；路径来自paths.py正式Lake及staging常量。消费者为现行daily collector、candidate/audit/publisher及本表资产/check，预算由定义测试和原P2负例共同验证。新增分区/check名是固定身份，不是运营开关；生效依现有Definitions loader，正式reload另阶段处理。

| 成本与边界 | 本片方案 |
| --- | --- |
| 执行unit/对象/分区 | 一个完整来源日期，不按代码或市场展开；隔离2个资产/2文件，正式只读抽验1日期；历史431日、每层2191645行沿P3，不重生成或逐日深扫 |
| 请求/分页/行数 | 存档2026-09-30实测5215行，每轮3页，两轮6请求；每轮上限20000行，整页空尾页两轮22请求，仍受64次含重试总上限限制 |
| 扫描/写量/磁盘 | 两轮逐页落候选，SQL双向全字段比较、Silver仅日期转换；§6原候选样本Raw339557B/Silver339533B为既有预算参考；正式P3文件与隔离执行结果以本轮实测为准；512MB单线程无spill，run临时目录；正式空间和文件不改 |
| 提交/失败恢复 | 每文件校验后同文件系统os.replace、checkpoint持久化，无全历史DB事务；失败重跑本日候选或本文件，取消后不领取下一unit；隔离退出/续跑证据 |
| 耗时/拒绝策略 | 正式源含至少60秒稳定等待，全部请求/等待受300秒约束；隔离fake clock耗时不当网络SLA。行数、时间、内存、schema/identity/hash或稳定性超界即拒绝发布；只读单日审计30秒/RSS768MiB上限 |

验收用项目现有.venv、fake source/clock、临时Lake及native SQLite；新定义真实行fixture测试、五表原P4/七表P2回归、完整受保护catalog/static、完整Definitions、Ruff和文档完整性都必须通过。最终门禁期间源码/测试hash稳定，原56份moneyflow报告保留。正式既有文件仅只读验证schema/主键/13字段等价及P3 hash，不运行正式asset/check，不访问正式instance，不调用Tushare。正式Lake/staging control/PG/分区/events写入、reload、sensor、pool变更和安装均0。P4整体开放，P5未进入；完成后再记录实测，不能提前宣告历史登记完成。


### 54.3 独立定义验收收尾

moneyflow_ths独立Raw/Silver、两条分区blocking checks、两job和cn_a_moneyflow_ths_trade_days已接入；catalog新增两资产及两分区模型，name_mapping登记同花顺个股。共享daily publisher仅增加moneyflow_ths固定允许项；其他四个daily资产入口不改，原测试中的尚未接入THS负例移除，未知moneyflow、未知来源和路径穿越的写前拒绝仍测试。catalog实际资产清单及受保护runner只读源码清单同步新增，不放宽正式资源或网络边界。原P2字段/request/collector/writer/check算法及配置不改。

| 验收项目 | 本轮实测 |
| --- | --- |
| 新独立定义与原生job/check | 41项通过，20.43秒；job仅选本层，检查分区与materialization同日，storage_id/run_id/timestamp精确target相符 |
| 存档真实5215行 | 2026-09-30两轮分页各3请求，offset0/2000/4000，第二轮倒序；Raw/Silver各5215行、13字段全值一致、reject0；SH2316/SZ2899，没有凭其他源补BJ；构造BJ源代码可正常保留 |
| THS字段/单位/身份 | latest不改名，源net_amount/net_d5_amount不按分项或日净额重算；万元/NULL/负值保留。同名异码允许，同码异名拒绝；DC close替换、缺/多字段、空码、错日、空源、两轮d5变化都阻断 |
| 上游及恢复门禁 | 同日最新绿Raw和hash才可生成Silver；无Raw、异日、旧/失败检查、物理hash变化拒绝。Silver的latest/d5/net字段修改检查失败；replace后退出、意图后取消续跑、幂等修订及异源receipt隔离通过 |
| 原链完整回归 | 已接入五表P4定义与七表P2共716项通过，104.79秒；包括THS原P2精度、分页、20000行/22请求、重试/时间/内存/取消负例；原MCP样本没有重新请求 |
| 完整受保护/加载门禁 | catalog12项/510子断言、static113项通过，原生resource gate通过，denied区域不变；隔离完整Definitions加载、14份改动源码Ruff及全DG致命检查通过 |
| 正式既有文件只读 | 2026-09-30两文件各5215行/唯一键，Raw/Silver13字段保真；0.2425秒/RSS163168256B，P3原hash/bytes一致，前后未改变；不访问正式instance或执行正式job/check |
| 证据与影响 | 最终1162份DG源码/测试hash在完整门禁期间及报告归档时不变；56份旧moneyflow报告逐字保留；根CodeGraph sync/status已确认最新。Prod合同、API/前端和主体依赖矩阵不变 |

存档样本两job实际执行0.8763秒，使用fake source/clock和隔离SQLite，不能作为真实盘后请求耗时或日更验收。正式P3 Raw336371B、Silver336347B，hash分别d68f42062195bf7a7f74bc794f74a56c0f6814c9f4a8700a4f8fe7fe9db32775、b40f28495e8217140aac53ef97894d1be948609260fc347bab7c3a685bf8a0b3；这是正式文件实测，与§6旧候选编码字节数不同，以P3证明和本轮读回为准，不修改历史候选记录。

完整测试、存档源全字段、原生target、正式物理只读、预算、旧报告及源码hash已归档至[本轮结构化报告](../../reports/moneyflow_p4_ths_evidence_20261012.json)。现有SDK的分区check preview和job partitions_def弃用提示保留，未升级或安装；原生分区/check归属已经实测。本轮正式Lake/staging control/instance/PG/event/分区写入、源请求、reload、sensor评估/启用、pool变更及正式job/check执行均0。隔离临时资源写入仅用于本片验收。

**本定义切片关闭，moneyflow_ths历史登记阶段未进入，P4整体开放，P5未进入。** 前轮已提交fea34b23，未推送；本轮14份源码/测试、两份方案文档和一份新报告尚未提交，其他任务文件保留。下一独立片按原方案接三个默认STOPPED sensor、专属file/event readiness与431历史来源日有界只读预演，继续沿22:00登记当日分区、最近10日期、单tick单run口径；之后再做可恢复历史执行器及两日/全量冻结清单，正式执行按准确阶段清单批准。两个历史源缺口2026-07-06/2026-07-09保留。


<a id="moneyflow-ths-automation"></a>

## 55. P4同花顺个股sensor、就绪判断及431日只读预演（2026-10-12）

### 55.1 本轮授权、命名与硬口径

管理员要求先提交上一切片，再继续本表三个STOPPED sensor、就绪判断和431历史来源日只读预演。资产切片17个文件已提交f4095071，未推送。本轮沿§6/§15/§28/§54及新增DG模板7A，新增固定STOCK_THS_MONEYFLOW_AUTOMATION、三个sensor、独立readiness/preview薄入口与测试；原方案和LLD先落本节，再编码。正式登记执行器、两日/全量冻结APPLY清单留到下一切片，本轮不触发正式job/sensor evaluation，不reload、启用、改pool、注册分区或补event。

| 硬口径 | 实现与正反验收 |
| --- | --- |
| 每源独立身份、默认STOPPED、sensor不请求源 | sensors/moneyflow_ths_sensor.py：cn_a_moneyflow_ths_trade_day_sensor、raw_tushare_moneyflow_ths_update_job_sensor、silver_moneyflow_ths_update_job_sensor；间隔600秒、resources只有lake_root/duckdb，定义与Source调用次数反例 |
| 标签统一且为静态分类 | build_sensor_tags：quote_data / partition / partition_registration，quote_data / raw / asset_update，quote_data / silver / asset_update；同步治理/拓扑HTML与完整static清单 |
| 上海22:00登记当天，最多再补一历史漏日 | 复用register_moneyflow_trade_days，固定cn_a_moneyflow_ths_trade_days，history_start=2024-12-19；22点前/假日/起点前/异源分区反例，输出SensorResult不调用写接口 |
| 更新仅最近10交易日，每tick最多一个单日job | 复用evaluate_moneyflow_update：SSE日历、2026-10-01起点、DESC LIMIT10、当日优先；active job阻断，不在热路径查431日期 |
| 最新同日物化+完整green check+物理hash才ready | asset_guards/moneyflow_ths_readiness.py封装batch_moneyflow_readiness；target storage_id/run_id/timestamp精确匹配，blocking/通过、无symlink/hash匹配，Silver绑定对应Raw hash；跨日/旧check/错hash/上游修订/超限反例 |
| cursor与有限重试独立 | dataset/layer固定身份，8KiB硬上限，原生run key为每日6次权威计数；丢cursor不重置尝试，临时错误重试，权限/字段/精度失败人工处理 |
| 历史只用实际来源日，不补缺口或拼资金值 | bootstrap/moneyflow_ths_event_preview.py复用P3冻结proof：431日期、每层2191645行、24unit、862文件；2026-07-06/07-09缺口保留，最近20日核查date+ts_code/13字段及冻结每日行数，proof entry含row_count但不含板块scope |
| 原证明/事件不改，已有事实不匹配则拒绝 | 固定history-full-20261009、cutoff2026-09-30、cohort05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618；全文件/control hash、精确原生mat/check及batch集合查询；冻结文件/control/cohort、event hash/target变化反例 |
| 原consumer完整回归，无正式写路径 | 固定合同只加本表；旧五表revision/身份/metadata/文件预算保持，完整catalog/static与隔离Definitions。正式readonly adapter禁止自动DDL和事务写，仅包裹三类native读取，旧报告逐字保留 |

CodeGraph explore/impact已核查sensor、固定automation contract与batch readiness；索引对别名/属性消费者不完整，用当前代码引用补齐selector、history proof、event plan/engine、五表固定adapter和测试。新增合同保持现有class shape和旧五表revision不变；本表event_revision=stock_moneyflow_ths_history_events_v1作为独立身份，未增加正式执行adapter。Prod DatasetDefinition/request builder、Web/API/CLI及主体依赖矩阵不变。源字段、请求策略、万元单位、NULL/负值/北交所保留沿已验收P2/P4，不新增源请求。

### 55.2 性能、配置与正式只读边界

| 项目 | 成本、上限与拒绝策略 |
| --- | --- |
| 新固定预算审计 | MONEYFLOW_THS_READINESS_FILE_MAX_BYTES=4*1024*1024，唯一源码声明run_contracts/moneyflow.py，无env/Settings/数据库/运营覆盖；唯一生产消费者batch_moneyflow_readiness的固定moneyflow_ths分支，随definitions加载生效；超限返回file_hash_budget且不hash，UI/日志通过cursor reason显示 |
| 预算依据与影响 | 已实测5215行单日Raw336371B/Silver336347B，超过旧64KiB；按20000行样本比例约1.29MB/文件，4MiB为有界余量，不承诺任意字符串长度。市场/THS行业/概念仍64KiB，DC板块与DC个股仍各自独立4MiB，新旧预算分别正反验证 |
| 日更tick | 最多2mat+2check（limit100）+2active run（limit1）+1partition+1日历SQL，最多20文件/80MiB顺序hash，无Tushare请求；Raw提交时额外1个选中日run records及临时错误时1个failure记录读取，不称只有7次总查询；10日期fixture实测目标<2秒、cursor<2KiB，硬上限8KiB |
| 历史proof | 仅本表24已完成unit、862文件/281281240B hash、50份cohort/progress/逐unit控制证明；最近20日做标准化全字段SQL及冻结行数核查，其余依赖P3完整schema/主键/值证明+当前hash，不逐日期重新扫描全明细 |
| 历史native读取 | 1partition+每层ceil(431/100)=5次mat+每层1次recent check=13次helper读取；单批100日期、limit100、记录截断/既有revision/target不匹配拒绝；无431日期逐日readiness循环 |
| SQL/内存/事务 | DuckDB512MB/1线程/no-spill，RSS768MiB；单unit120秒，原生PG statement_timeout10秒/default_transaction_read_only=on、should_autocreate_tables=False；预演驱动总120秒包络，无正式写事务 |
| 持久化/取消/恢复 | 只读取消每文件检查，可中断后从同一冻结事实重跑；不建正式锁、目录、plan或checkpoint。已有writer锁只用rb共享锁避免并发历史修改；报告/驱动/日志仅/tmp及仓库，不引入状态实体 |
| 实际验收 | isolated fake source/clock/native SQLite：身份、22点/假日、重试、check/hash、10日batch成本与旧链；正式431日只读预演及同事实重跑，全物理/control/旧报告hash不变，无Prod/Tushare访问 |

正式驱动工作目录lake_console/orchestrator，命令`.venv/bin/python3 -B /private/tmp/moneyflow-ths-automation-20261012/formal-preview.py`，用既有/Users/congming/.goldenshare/dagster_home/dagster.yaml的readonly native adapter，固定Lake=/Volumes/datasource/data_lake、staging=/Volumes/datasource/data_lake_staging，仅读本表两asset/check和分区。写范围只有/private/tmp日志JSON及本轮仓库报告。正式源API、分区/event/正式文件/staging control、job/sensor/reload/enable/pool全部0。

官方依据：[Dagster sensors](https://docs.dagster.io/guides/automate/sensors)、[dynamic partitions](https://docs.dagster.io/guides/build/partitions-and-backfills/partitioning-assets)。default STOPPED与run_key不是正式执行证据，当前SDK与隔离native验收决定实际语义。以下据执行结果回填，不预填通过，P4整体开放、P5未进入。


### 55.3 本切片验收收尾

三个独立sensor已接入，默认STOPPED、最小间隔600秒，静态标签和完整Definitions校验通过。上海时间22:00后优先登记当天，最多再补一个历史漏登记日；假日、22点前和2024-12-19起点前的日期按约定拒绝。更新器只看最近10交易日，每次最多提交一个单日job。sensor不请求Tushare；Silver必须对应同日最新绿Raw及其hash。

就绪判断同时核对最新同日物化、SUCCEEDED/passed/blocking检查、精确storage_id/run_id/timestamp target和文件hash。文件存在但没有物化不能放绿，旧检查或Raw修订不能误放行Silver。跨源/跨层cursor、超大文件、读取截断、冻结行数或已有事件不匹配均拒绝；每日6次原生run key重试不因丢cursor重置。共享合同只增加固定THS身份和本表4MiB预算，旧五表revision与预算不变。

| 验收项 | 实际结果 |
| --- | --- |
| 新sensor/readiness/preview | 53项通过，31.23秒；覆盖22点/假日/起点、重试、同日check/hash、异源隔离、冻结行数与源缺口不补算 |
| 原五表回归及本表定义 | 483项通过，454.0秒；五表sensor、预演、可恢复登记执行器，以及moneyflow_ths已提交定义；隔离native SQLite/Lake/staging |
| 十日热窗口 | 存档5215行样本复制到10个隔离日期，两层20个原生job/check；tick为2mat+2check+2active run+1partition+1日历SQL，顺序hash20文件/6727180B，0.0253秒、cursor575B、tick源请求0 |
| 正式全历史只读 | 两遍结果一致：431来源日，每层2191645行，24unit、862文件/281281240B及50控制hash保持；每个文件hash/bytes同时匹配P3原审计，最近20来源日13字段、date+ts_code及冻结行数核验通过 |
| 历史读取成本 | 每遍1partition+10批mat+2check=13次helper原生读取，耗时1.3089/0.6583秒；最大文件340787B，小于4MiB，未逐日深扫事件 |
| 正式十日readiness | 两层20个判断为file_without_materialization、ready=false；2mat+2check读取，没有把文件存在当作已登记 |
| 待登记清单 | 431分区、Raw431+Silver431物化、最近20来源日两层40检查：902条event、合计1333项工作；2026-07-06和2026-07-09缺口保留 |
| 完整受保护门禁 | catalog12项/510子断言、static113项/15批通过；逐批resource gate、denied区域保持及退出码核对通过；runner只新增三份精确源码条目 |
| 完整性与影响 | 隔离Definitions、改动Python Ruff及全DG致命检查通过；最终1167份DG源码/测试在完整门禁期间保持，原57份moneyflow报告逐字保留；根CodeGraph已同步。主体依赖矩阵、Prod契约和API/CLI/前端不变 |

[本轮证据](../../reports/moneyflow_p4_ths_sensor_event_preview_evidence_20261012.json)保存两遍完整proof、862物理/50控制hash、逐日冻结行数、原生查询数、十日热路径及完整门禁。正式PG使用只读事务、should_autocreate_tables=False；已有writer.lock只读共享打开，没有创建正式锁、目录、plan或checkpoint。正式file/control/partition/event写入、源请求、job/sensor evaluation、reload/enable/pool变更均0。三个STOPPED是源码默认值，不宣称正式workspace已加载或持久化状态已验收。

十日日期为合成未来日期，5215行来自既有实测归档；25毫秒不能外推正式网络请求耗时。最近20来源日追加全字段SQL，其余日期依据P3完整证明与本轮逐文件hash，未重新向Tushare请求全历史。本轮只关闭sensor、就绪判断和只读预演这一片；P4整体开放、P5未进入。上一17文件已提交f4095071未推送，本轮尚未提交。下一步开发THS可恢复历史登记执行器、隔离两日样本和431日冻结全量清单；正式登记与sensor启用仍各按精确阶段批准。THS正式执行adapter及其row_count写入/读回校验尚未在本轮接入，不能用通用engine可接受固定合同推定该阶段已经完成。


<a id="moneyflow-ths-history-events"></a>

## 56. P4同花顺个股可恢复历史登记执行器、两日样本与431日冻结清单（2026-10-12）

### 56.1 编码前目标、依据与硬口径

上一sensor/readiness/只读预演切片16个文件已提交2c23180d，未推送。管理员要求继续本表历史登记执行器、两日样本和431日全量冻结清单。本轮按§6/§15/§28/§54/§55及DG模板7A，开发固定入口、沿现行恢复协议做隔离native SQLite样本/容量验收，并从正式PG只读构造样本和全量PLAN。两日正式APPLY、本表全量正式登记及任何reload/enable/job不在本轮范围，不能把清单冻结当成正式执行。

| 硬口径 | 真实代码点与正反验证 |
| --- | --- |
| 单独本表身份、默认只读 | 新bootstrap/moneyflow_ths_event_plan.py和moneyflow_ths_events.py绑定STOCK_THS_MONEYFLOW_AUTOMATION，复用build/validate_moneyflow_event_plan与report_moneyflow_history_events；apply默认False且只接受bool，拒绝其他五表plan及错误storage/revision |
| 完整冻结事实，不补缺口 | 431个实际来源日，每层2191645行；plan固定P3 operation/cutoff/cohort、50control hash、每日期两文件hash及row_count；重建验证阻断篡改日期/行数/hash/control/instance，2026-07-06/2026-07-09不造空日期 |
| 原生metadata与物理计数一致 | 复用_materialization/_evaluation与history_schema；13 observed_columns、row_count/source_row_count、checked_row_count与target三字段；不加入板块scope_row_counts。共享engine两处daily行数守卫加moneyflow_ths，原五表逻辑保持；假既有/源count不能复用或发布绿check |
| 只最近20来源日补check | 旧日期只登记物化；最近20日复用同日13字段/date+ts_code标准化SQL与冻结行数后才发布绿check。431日容量检查40事件，早期日期不强行日更全证券覆盖或补check |
| 逐unit持久化与恢复 | 分区100日一批、event逐条native提交；原namespace writer锁、plan/checkpoint原子保存复用，无全历史数据库事务。取消每读/写前后检查，真实子进程事件后退出/缺失checkpoint/保存失败/观察失败后按native差分续跑，幂等不重复且不删除事件 |
| 运行预算与进度 | 复用4096工作项、600秒总、120秒批、256 metadata读、100日期/批、limit100、DuckDB512MB/1线程/no-spill、RSS768MiB；当前stage/date/layer/completed/total/percent/updated_at持续输出；预算耗尽、active/writer冲突阻断 |
| 全消费者和隔离门禁 | CodeGraph explore/impact加当前引用补齐五固定adapter、plan/proof/engine/readiness/tests；新本表events测试、旧五表events及本表sensor/preview回归；受保护runner只加两个精确源码，不放宽拒绝policy，catalog/static/defs/Ruff/docs均验证 |

CodeGraph解析到共享planner的五固定入口与writer直接调用方，但对partial别名和部分测试消费者不完整；已用当前代码引用补齐所有实现方/测试。新增薄入口不改变共用函数签名、现有plan形状、旧五表revision/metadata或已冻结清单。Prod DatasetDefinition、请求builder、API/CLI、资源/资产/check/sensor/分区定义和主体依赖矩阵均不改；本表13源字段、万元/NULL/负值及源证券范围沿P2/P4；latest与源net_d5_amount保持，不新增源请求。

### 56.2 成本、配置、恢复与正式只读边界

| 项目 | 本轮测算与拒绝策略 |
| --- | --- |
| 正式范围 | 431来源日、2191645行/层、862既有文件/281281240B；0证券枚举、0源请求/分页/Parquet生成；431partition+862materialization+40recent checks=1333工作项/902event，低于4096 |
| 两日样本 | 2026-09-29为5214行，09-30为5215行，共10429行/层；2分区+4物化+4check=10项/8event；隔离样本另用5214/5215归档fixture，不冒称正式执行 |
| proof与SQL | 每次build/validate重建862文件hash及50controls，最近20日全字段标准化+冻结计数SQL；执行检查阶段另核20日，不对431日逐分区readiness。Python只编排日期/hash/事件，不装载219万行明细，spill0 |
| native只读成本 | 两日默认预检7 helper读含2active，全量15读含2active；100日批/limit100防截断。相同facts反复重构必须得到相同plan_hash，旧五表十份冻结PLAN再验证保持原hash |
| 431日隔离容量 | 早期411合成日期各1股票行，最近20日期完整5215行fixture，共104711行；临时SQLite需完成1333项/902event，预计141 native读、11phase batch、921次原子控制保存，全部低于既有预算。必须记录耗时/RSS/每save成本，不能外推正式PG APPLY耗时 |
| 持久化/取消 | 单事件提交即事实，逐event checkpoint最多256KiB，frozen plan最多32MiB，原子写入+fsync，100日期批最多120秒；进度/checkpoint失败保留已提交事件，续跑原native状态差分，不依据checkpoint跳过实际检查、不删除event回滚 |
| 配置与互斥 | 无新增env/Settings/DB/run config；固定STOCK_THS合同和原event预算/paths/namespace writer锁沿既有已审计消费者，旧预算/revision保持。历史登记运行与本表daily两个job互斥active guard；只读driver已有writer.lock以O_RDONLY共享锁，不新建正式锁或events目录 |
| 正式只读 | daily_basic_event_instance(writable=False)，既有本机goldenshare_dagster，强制readonly、10秒SQLtimeout、禁自动DDL；仅原storage identity、分区、mat/check和两job active查询，report(...apply=False)。只写/private/tmp日志及仓库reports两PLAN，不改正式staging control |

正式只读driver从lake_console/orchestrator运行现有`.venv/bin/python3 -B /private/tmp/moneyflow-ths-events-20261012/formal-plans.py`，固定Lake=/Volumes/datasource/data_lake、staging=/Volumes/datasource/data_lake_staging、operation=history-full-20261009、cutoff=2026-09-30、cohort=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618，既有/Users/congming/.goldenshare/dagster_home/dagster.yaml readonly adapter。plan保存仓库reports，正式event目录库存/旧58份报告前后hash不变；正式源API、partition/event/file/control写入、sensor evaluation、job、reload/enable/pool/安装均0。

全量正式耗时尚未实测；临时SQLite容量和正式只读只证明本轮成本/一致性。样本以后执行后全量原plan不改，按native差分预计剩429分区+858物化+36checks=1323项/894event。正式APPLY前重新验证当前hash/storage/source、active状态、维护窗口、sensor未启用、空间与writer互斥；两日样本和全量分别按精确清单批准。

依据：[runless asset event](https://dagster.io/docs/api/dagster/internals#dagster.DagsterInstance.report_runless_asset_event)、[dynamic partitions](https://dagster.io/docs/guides/build/partitions-and-backfills/partitioning-assets)、[asset checks](https://dagster.io/docs/guides/test/asset-checks)。原生事件不归属于run，沿已批准直写补录模式，不称Dagster backfill；本地当前SDK隔离持久化/target读回决定实际行为。下面在验收后回填，P4整体开放、P5未进入。


### 56.3 可恢复执行器、两日样本及冻结清单验收完成

本表独立planner/validator和登记入口已接入，共用恢复算法保持；共享engine只将moneyflow_ths加入已有行数校验：既有物化的row_count/source_row_count、既有检查checked_row_count与冻结每日计数相符，最近20日检查前SQL行数必须相符。13个observed_columns保留latest和net_d5_amount，检查绑定精确storage_id/run_id/timestamp；不加入板块scope。默认apply=False，错误bool、异源清单、storage/文件/control/行数变化和读取截断均阻断。

| 验收项目 | 结果 |
| --- | --- |
| 新执行器测试 | 50项通过，60.68秒；取消、真实子进程事件后退出、缺失/损坏/超大checkpoint、保存/观察失败续跑、幂等、active/writer互斥、错误计数及跨五表清单拒绝 |
| 原链回归 | 五表可恢复events及THS sensor/preview共284项通过，297.47秒；隔离SQLite/Lake/staging，源请求和正式资源均未使用 |
| 隔离两日样本 | 5214/5215行、13字段、4mat/4check精确target、reject0；10/10项完成，0.2756秒/53读，重放0.2033秒、0新增，物理/来源control保持 |
| 431日隔离容量 | 411个单行日期+最近20日完整5215行，共104711行；1333/1333项，新增431分区/902event，4.9175秒、141 native读，RSS峰值580.9MiB，低于768MiB |
| 原子控制成本 | 921次plan/checkpoint保存，合计0.3263秒，最长0.0014秒；100日批读取，只有最近20日40checks |
| 正式只读清单 | 两PLAN完整重建相同；样本预检7读/0.5307秒，全量15读/0.5681秒；均completed0、formal_writes0，尚未登记 |
| 旧清单/事实 | 旧五表十份sample/full PLAN重建验证通过、hash保持；862本表文件/281281240B与原审计一致，50来源controls及20既有event控制文件不变；全部只读驱动9.5678秒 |
| 完整门禁 | catalog12项/510子断言、static113项/15批resource gate通过，拒绝区域保持；完整隔离Definitions、改动Ruff与全DG致命检查通过，最终1170源码/测试hash保持，原58报告逐字保留，CodeGraph根索引同步 |

两份清单均只保存在仓库reports，不创建正式staging/events目录；plan内部不含event storage_id，因此样本执行后全量清单保持原hash，下一次按原生差分续跑。外部文件sha256和内部plan_hash各自校验，不混为一个值：

| 清单 | 范围与工作项 | 内部plan_hash | JSON文件sha256 |
| --- | --- | --- | --- |
| [两日样本](../../reports/moneyflow_p4_ths_event_registration_sample_plan_20261012.json) | 09-29/09-30，10429行/层；2partition+4mat+4check=10项/8event；12675B | c62919f2df2ecb6f925d9c121a521888b622899ae4938563d77a559af4b37147 | cf7624f3292f026b88d3a6582c80c573666a5815461c3326636edcc34ba4ffe7 |
| [431日全量](../../reports/moneyflow_p4_ths_event_registration_full_plan_20261012.json) | 2024-12-19至2026-09-30实际来源日，2191645行/层；431partition+862mat+40check=1333项/902event；236072B | eb867fc0e4c58e8816cff0888079b3f2fc06b24230612b34b5e2eac3552d35ea | 8f81291b7ddf181e4843a22ce4f398bc2abd8b70d6874d2513d2f463b9f9edd0 |

两处源缺口2026-07-06/07-09不造空日期；只有最近20实际来源日补check。样本正式执行后预计剩429分区、858物化、36checks，共1323项/894event，仍使用原全量清单。完整proof、清单、计数、查询、旧十PLAN及恢复/容量证据见[执行器验收报告](../../reports/moneyflow_p4_ths_event_registration_executor_evidence_20261012.json)。

隔离样本不是正式09-29源明细；容量日期也不是交易日清单，而是用合成日期测算法规模。隔离SQLite的4.9秒不能视为正式PG全量耗时。正式PG只读、禁自动DDL，正式Lake/staging control/分区/event写入、源请求、job/sensor evaluation、reload/enable/pool/安装均0，无Prod契约、API/CLI和主体依赖边界变更。文档完整性、相对链接和限定diff检查另行核验，不代替上表语义测试。

本开发片关闭，P4整体仍开放、P5未进入。上一16文件已提交2c23180d未推送；本轮代码、两份方案、两PLAN及新报告尚未提交。下一阶段按冻结两日清单获批后正式登记，执行前复核持久化sensor未启用、两job无active、维护窗口、当前源码/storage/hash、writer互斥和staging至少32MiB空间；必须读回4mat/4check身份/target/行数、四readiness及0新增重放。两日批准不包含431日全量、reload或sensor启用。


<a id="moneyflow-ths-formal-sample"></a>

## 57. P4同花顺个股正式两日历史登记和读回验收（2026-10-12）

### 57.1 执行前范围、命令与验收约束

上一执行器、两份冻结清单和验收证据十文件已提交b4e1a5e0，未推送。管理员本轮明确批准“按冻结两日清单执行，继续推进moneyflow_ths的正式样本登记和读回验收”。本轮落实§56已确认的样本步骤，不修改Python主代码、配置、definitions或源契约。P4整体开放，P5未进入；以下实际结果在执行后回填，不预填通过。

| 项目 | 本轮精确执行约束 |
| --- | --- |
| 日期与数量 | 仅2026-09-29/09-30，来源5214/5215行，共10429行/层；分区cn_a_moneyflow_ths_trade_days；2partition+Raw2/Silver2materialization+两层4checks=10项/8事件 |
| 授权清单 | sample内部plan_hash=c62919f2df2ecb6f925d9c121a521888b622899ae4938563d77a559af4b37147；文件sha256=cf7624f3292f026b88d3a6582c80c573666a5815461c3326636edcc34ba4ffe7；两个hash分别核对，不能替换清单 |
| 正式入口 | report_stock_moneyflow_ths_history_events复用原engine；既有daily_basic_event_instance适配器加载/Users/congming/.goldenshare/dagster_home/dagster.yaml，localhost goldenshare_dagster、禁自动DDL、SQL10秒timeout；preflight/readback用只读事务，APPLY和幂等重放才用writable=True |
| 写前门禁 | fresh Python导入源码与已验收1170源码/测试hash一致；三个sensor源码默认STOPPED，持久化无RUNNING，若未保存状态须记为缺失、不能称持久STOPPED；两job无active、当前维护执行授权、writer非阻塞互斥、同盘staging至少32MiB、原7888物理/control、20event控制、执行前62份既有moneyflow文件（61份JSON及1份CSV）及冻结清单保持 |
| 精确写边界 | 只允许两日分区和raw_tushare_moneyflow_ths/silver_moneyflow_ths及各自检查；driver再加日期/asset/check配对白名单。只沿原writer锁写sample plan_hash目录下plan.json/checkpoint.json及原子保存partial；不写Parquet，不登记431日全量，不调用Prod/Tushare，不reload/enable/job/pool或安装 |
| staging控制路径 | /Volumes/datasource/data_lake_staging/moneyflow/history-full-20261009/events/c62919f2df2ecb6f925d9c121a521888b622899ae4938563d77a559af4b37147；正式Lake仍为/Volumes/datasource/data_lake，仅只读，不创建其他控制目录 |
| 预算与恢复 | 原4096项/600秒总/120秒批/256 helper读/100日期批/DuckDB512MB单线程no-spill/RSS768MiB预算不变；driver总120秒。逐事件native提交并原子checkpoint，持续stage/date/layer/completed/total/percent/updated_at；失败保留已提交事实，沿原清单差分恢复，不删除事件或回滚业务事实 |
| 读回验收 | 同正式instance读回2分区、4mat、4SUCCEEDED/passed/blocking check，row_count/source_row_count/checked_row_count与冻结每日数一致，reject0、13观察字段、文件/来源hash与Silver Raw绑定；check精确target storage_id/run_id/timestamp正确；Raw/Silver两日共4ready，真实重放0新增且所有身份不变 |
| 保持原清单 | 全量plan_hash=eb867fc0e4c58e8816cff0888079b3f2fc06b24230612b34b5e2eac3552d35ea及文件sha256=8f81291b7ddf181e4843a22ce4f398bc2abd8b70d6874d2513d2f463b9f9edd0保持；只读复核样本后剩429分区+858物化+36check=1323项/894event，不在本轮执行；2026-07-06/07-09缺口保留 |

工作目录固定/Users/congming/github/goldenshare/lake_console/orchestrator。只读预检命令`.venv/bin/python3 -B /private/tmp/moneyflow-ths-formal-sample-20261012/run.py`；获批执行、只读读回和0新增幂等重放命令`.venv/bin/python3 -B /private/tmp/moneyflow-ths-formal-sample-20261012/run.py --apply`。driver只用现有.venv，不uv sync、不传PYTHONPATH、不加载登录shell/token；临时脚本和日志在/private/tmp，结论归档仓库reports。原生writer不是code-location job执行，因此不宣称正式workspace当前已加载新源码；本轮import源hash验证当前批准的独立执行进程。

依据沿§56官方[runless asset event](https://dagster.io/docs/api/dagster/internals#dagster.DagsterInstance.report_runless_asset_event)和[asset checks](https://dagster.io/docs/guides/test/asset-checks)，以及当前适配器/engine/批量readiness真实代码。CodeGraph explore核对固定入口→共享writer/state及本表readiness调用链；索引对别名调用和部分测试覆盖不完整，已读当前实现补齐。API/CLI、主体依赖矩阵和配置不变。产品源码/测试不变，本轮复用§56全部已通过门禁，新增验收为正式预检、真实APPLY/读回/重放及文档完整性。


### 57.2 正式两日登记、读回和幂等重放验收通过

2026-10-12 20:25（上海时间）按批准清单完成正式样本登记，写入2个分区、4条物化和4条检查，10/10项完成。真实进程使用b4e1a5e0当前源码与正式PG；没有执行code-location job或sensor。只读预检样本7次helper读/1.0907秒，全量15读/0.9098秒；首次正式APPLY1.9518秒/53读，真实重放1.9856秒/53读、0新增分区/事件，所有样本物化和检查身份/target不变。driver峰值RSS367.1MiB，空间约2.93TB，既有预算保持。读取次数是原helper计数，不包含额外维护状态审计、旧五表读回、hash和底层SQL；不拿样本耗时外推全量。

| 日期 | 每层来源/物化/检查行数 | Raw / Silver物化storage_id | Raw / Silver检查execution_id | 就绪 |
| --- | --- | --- | --- | --- |
| 2026-09-29 | 5214 / 5214 / 5214 | 7456993 / 7456994 | 1599362 / 1599363 | 两层ready |
| 2026-09-30 | 5215 / 5215 / 5215 | 7456995 / 7456996 | 1599364 / 1599365 | 两层ready |

每层累计10429行；4mat均记录13个observed_columns、来源计数、reject0、file/cohort/checkpoint/plan hash与cutoff；Silver对应同日Raw摘要。4check均SUCCEEDED/passed/blocking，partition与每日checked_row_count正确，target storage_id/run_id/timestamp精确指向上表同层物化。两日检查阶段重新执行完整13字段/date+ts_code标准化SQL和冻结行数校验；latest、net_d5_amount及万元/NULL/负值口径沿原合同。原文件完全未改，不重新调用源站。

60条进度记录完成量单调并以complete结束；正式sample plan/checkpoint保存于§57.1指定目录，checkpoint total=completed=10、stage=complete、percent=100。执行前正式库存扫描106条sensor记录，本表三sensor均无持久化记录，源码默认STOPPED；不是“已持久化STOPPED”，没有新建或启用状态。执行前后及重放后的完整sensor name/status库存摘要一致，两个job无active；原五表3306分区/6612物化/200最新检查的分区集合、物化storage_id及检查execution_id/run_id/timestamp/target均前后一致。

7888份冻结物理/来源控制文件、20份既有event控制、执行前61份JSON及1份CSV、1170源码/测试全部hash保持；本表862文件/281281240B、50来源control逐文件匹配原P3证明。新增staging控制只有本样本plan.json/checkpoint.json，无遗留partial；两份仓库冻结PLAN hash与字节均保持。深SQL范围为证明最近20来源日和两日检查；没有重跑431日每行全字段SQL，其他日期依据已验收P3完整证明和本轮逐文件hash。

[正式样本验收报告](../../reports/moneyflow_p4_ths_event_registration_formal_sample_evidence_20261012.json)保存预检、真实写入、原生event/check身份、4ready、0新增重放、进度、原文件/控制/源码/旧事件与报告指纹。未改产品代码，复用§56已有50项执行器测试、284项回归和完整catalog/static/defs/Ruff门禁；本轮新增真实正式验证和文档完整性/链接/diff检查。不重复正式取消实验，恢复行为来自已验收隔离进程退出/取消测试。API/CLI/配置和主体依赖矩阵不变；源请求、Parquet写入、reload、sensor evaluation/enable、job、pool、安装均0。

样本片关闭；P4整体开放、P5未进入。下一独立阶段按原431日全量PLAN批准执行；原hash不改，native差分已实测completed10/1333，剩429分区+858物化+36检查=1323项/894event，预演15读/0.5869秒。全量应复用这4条样本物化及4条检查，不新增重复；源缺口2026-07-06和07-09保留。b4e1a5e0已提交未推送，本轮两文档和新报告尚未提交；没有获得全量、reload或启用批准。


<a id="moneyflow-ths-formal-full"></a>

## 58. P4同花顺个股431日全量历史登记与本表收尾（2026-10-12）

### 58.1 执行前约束、完整命令与验收计划

上一两日正式样本收尾的两文档及报告已提交d8f3e45c，未推送。管理员本轮明确批准按原冻结全量清单执行moneyflow_ths全量历史登记和收尾。本轮执行§56～57已确认的全量步骤，按原生事实差分补录；不修改产品Python、配置、definitions或源契约。下列实际结果执行后回填，不预填通过；本表历史片收尾不等于整个P4关闭或P5真实日更已运行。

| 项目 | 精确口径、代码点、预算与验收 |
| --- | --- |
| 原始冻结清单 | moneyflow_p4_ths_event_registration_full_plan_20261012.json：2024-12-19至2026-09-30的431实际来源日，每层2191645行；内部plan_hash=eb867fc0e4c58e8816cff0888079b3f2fc06b24230612b34b5e2eac3552d35ea；文件sha256=8f81291b7ddf181e4843a22ce4f398bc2abd8b70d6874d2513d2f463b9f9edd0。两种hash分别验证，原清单不重建替换 |
| 差分与已有样本 | 总431partition+862materialization+最近20来源日40checks=1333项；样本10项已完成，本次预期剩429分区+858物化+36checks=1323项/894event。已有09-29/30四mat storage_id=7456993～7456996，四check execution_id=1599362～1599365及target/metadata、样本plan/checkpoint全保留 |
| 固定事实与范围 | STOCK_THS_MONEYFLOW_AUTOMATION、report_stock_moneyflow_ths_history_events→原shared engine；P3 operation=history-full-20261009、cutoff=2026-09-30、cohort=05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618。2026-07-06/07-09源缺口不创建空分区、不算资金值；13源字段/latest/net_d5_amount及万元/NULL/负值保持 |
| 原生读取与互斥 | dry-run15 helper读含两job active；100日期/批、每批limit100，预计APPLY及重放各141 helper读，256硬上限；初次读现有facts、原writer.lock非阻塞独占、每phase批active guard及storage identity复核，读取截断、wrong rows/hash/target和writer/active冲突拒绝 |
| SQL与文件 | 重建862文件/281281240B及50来源control当前hash，匹配P3原证明；最近20来源日重复13字段/date+ts_code标准化和冻结计数SQL；其他411日期依据P3已验收证明+当前hash，不做431日逐分区readiness或全明细重扫；0源请求/分页/证券枚举/Parquet写入 |
| 执行预算 | 原4096工作项、600秒每helper调用总、120秒当前批、RSS768MiB、DuckDB512MB/1线程/no-spill保持；整个driver660秒超时包络。原431日隔离容量141读/4.9175秒、921次原子保存不外推正式PG；已有正式两日约1.95秒，旧DC全量仅用于预算参考，实际耗时/RSS待记录 |
| 原子保存与取消 | 分区100日一批、event逐条native提交、逐项checkpoint fsync+原子replace，plan≤32MiB/checkpoint≤256KiB，无全历史事务。进度含stage/date/layer/completed/total/percent/updated_at；每读写前后预算/取消检查；失败已提交事实保留，沿原冻结清单差分续跑，不按checkpoint盲跳、不删除event回滚 |
| 写前正式门禁 | 既有DG home/storage、禁自动DDL、10秒PG timeout；当前dev-interface提交及1170源码/测试hash、runtime加载源码Git blob核对；本表三sensor源码STOPPED、持久化无RUNNING（缺失须如实记录），两job无active，本轮维护执行批准；正式Lake/staging同盘、staging≥32MiB/可写；既有7888物理/control、22event控制及执行前moneyflow报告保持 |
| 精确写边界 | driver对白名单再约束：仅431原来源日中尚缺的429日期，本表partition、raw_tushare_moneyflow_ths/silver_moneyflow_ths物化；check只允许最近20日中未登记的18日对应两层且asset/check配对正确，不写样本日期。只新增全量plan_hash目录plan.json/checkpoint.json及原子保存partial |
| 正式instance与路径 | 既有/Users/congming/.goldenshare/dagster_home/dagster.yaml；localhost goldenshare_dagster，daily_basic_event_instance默认readonly、仅APPLY/重放writable=True、should_autocreate_tables=False；正式Lake=/Volumes/datasource/data_lake只读，staging=/Volumes/datasource/data_lake_staging，原namespace writer锁 |
| 全量读回与重放 | 同正式instance分批读回431分区、862mat、40最新checks及1333项完成；每mat行数/来源数、13字段、reject0、file/cohort/checkpoint/plan/cutoff和Silver Raw摘要正确，按层总2191645；check SUCCEEDED/passed/blocking且精确target，近5日两层10ready；真实全量重放0新增、全部身份不变；再以新只读进程独立复验 |
| 保持与阶段边界 | 原五表3306分区/6612mat/200最新check身份、sample四mat/four check及两个control保持，最终event控制仅旧22+本全量2。0Prod/Tushare、Parquet、reload、sensor evaluation/enable、job、pool或安装；API/CLI/配置/主体依赖矩阵不变 |

工作目录/Users/congming/github/goldenshare/lake_console/orchestrator；只读预检命令`.venv/bin/python3 -B /private/tmp/moneyflow-ths-full-20261012/run.py`；按已批准全量执行、只读读回及0新增幂等重放命令`.venv/bin/python3 -B /private/tmp/moneyflow-ths-full-20261012/run.py --apply`；新进程独立只读复验命令`.venv/bin/python3 -B /private/tmp/moneyflow-ths-full-20261012/readback-run.py`。临时driver/log在/private/tmp；只沿现有.venv，禁止uv sync、PYTHONPATH或登录shell/token装载。正式staging新增目录固定/Volumes/datasource/data_lake_staging/moneyflow/history-full-20261009/events/eb867fc0e4c58e8816cff0888079b3f2fc06b24230612b34b5e2eac3552d35ea，不改样本目录或来源control。

依据沿§56～57当前实现、已验收50项执行器测试/284项回归及完整受保护catalog/static/defs/Ruff；本轮1170源码/测试不变，复用产品门禁，新增正式全量预检/APPLY/读回/重放与文档检查。CodeGraph explore核对THS固定planner/writer/state/readiness，别名调用与部分测试识别不足以当前实现补齐；只走fresh process直接native API，不宣称workspace已reload或日更已验收。官方[runless event](https://dagster.io/docs/api/dagster/internals#dagster.DagsterInstance.report_runless_asset_event)和[asset checks](https://dagster.io/docs/guides/test/asset-checks)沿原已批准补录模式，不称Dagster backfill。


### 58.2 全量登记、独立只读复验和本表历史片收尾通过

2026-10-12 20:38（上海时间）按原冻结431日清单完成全量登记；首次APPLY新增429分区、858物化、36checks（894event），复用已有样本10项，原生完成1333/1333、100%。所有工作项由原生事实读回确认，不能仅靠checkpoint判断完成。没有删除旧event或重写任何Parquet。

| 实际验收 | 数量、成本与结果 |
| --- | --- |
| 最终历史范围 | 2024-12-19至2026-09-30共431实际来源日，cn_a_moneyflow_ths_trade_days分区集合完全相符；Raw431/Silver431物化，合计862，40检查只覆盖最近20来源日两层 |
| 行数与字段 | Raw/Silver各2191645行；每个物化row_count/source_row_count与冻结每日计数一致、13 observed_columns、reject0；file/cohort/checkpoint/plan/cutoff正确，Silver精确绑定同日Raw摘要；保留latest、源net_d5_amount和万元/NULL/负值 |
| 检查与就绪 | 40check均SUCCEEDED/passed/blocking，分区及checked_row_count一致；storage_id/run_id/timestamp精确指向最新同日同层物化；09-23/24/28/29/30两层10ready，未对431日逐个做readiness |
| 样本身份 | 09-29/30四mat storage_id7456993～7456996、四check execution_id1599362～1599365、target、全部metadata及sample plan/checkpoint hash与上轮证据一致；全量没有重发样本 |
| 只读预检 | 全量completed10/1333，待补429/858/36；0.8716秒/15helper读；样本完整10/10，0.4994秒/7读；driver4.3501秒，0正式写入 |
| 正式执行与进度 | 首次APPLY18.8205秒/141helper读，1038条进度、完成量单调且complete结束；driver含预检/读回/重放/旧事实核验共31.1796秒，峰值RSS395.6MiB、低于768MiB，未触预算拒绝 |
| 实际幂等重放 | 完整431日清单重放3.9994秒/141读，0新增分区/event；862物化、40检查的全部身份/target/metadata与首次执行后一致 |
| 独立新只读进程 | 20:39复验通过，驱动3.0577秒；原helper0.9824秒/15读，completed1333/1333且三类缺失均0，原生数量/按层行数/10ready、全部身份和plan/checkpoint匹配，无正式写入 |
| 既有事实与控制 | 原五表3306分区/6612mat/200最新check身份及完整sensor name/status库存摘要保持；7888冻结物理/来源控制、22既有event控制（含sample2）、执行前62JSON+1CSV、1170源码/测试hash保持；只新增全量目录plan.json/checkpoint.json，无partial遗留 |

本表862文件/281281240B和50来源controls仍逐文件匹配P3及§56证明；recent20来源日的13字段/date+ts_code、标准化和冻结行数复验通过，其余411日依据已验收P3完整证明+本轮hash，未全明细重跑431日SQL或请求源站。2026-07-06/07-09两处源缺口不造空分区、不计算补齐；不存在“每天所有证券必须有行”的额外门禁。

本表三个sensor在正式106条库存中仍无持久化记录，当前源码默认STOPPED；不是“已持久化STOPPED”，未reload/启用或执行sensor。两更新job无active。fresh Python过程加载源码与已验收1170文件snapshot及d8f3e45c的Git blob一致；没有验证或改变正式code-location加载状态。计数读取为helper内计数，额外维护/旧五表/独立读回、文件hash和底层SQL不在141次内。18.8秒是本表已冻结事实的正式历史事件登记耗时，不能替代未来Tushare日更耗时或最终性证明。

完整预检、APPLY、物化/检查逐日身份与行数、进度、重放、新只读复验、源文件/控制/旧事件/报告指纹归档于[全量登记验收报告](../../reports/moneyflow_p4_ths_event_registration_formal_full_evidence_20261012.json)。原[全量PLAN](../../reports/moneyflow_p4_ths_event_registration_full_plan_20261012.json)内部plan_hash=eb867fc0e4c58e8816cff0888079b3f2fc06b24230612b34b5e2eac3552d35ea、文件sha256=8f81291b7ddf181e4843a22ce4f398bc2abd8b70d6874d2513d2f463b9f9edd0保持；正式staging保存同一payload，checkpoint complete1333/1333、percent100。

本轮没有产品代码改动；沿用§56的50项执行器测试、284项回归和完整受保护catalog/static/defs/Ruff，以当前1170源/测试hash和runtime Git blob核对确认可复用。新增验证为真实获批全量登记/读回/幂等、独立新只读验收和文档完整性/链接/diff检查；未重复正式取消实验，恢复语义仍来自已验收的隔离子进程退出/取消/保存失败测试。API/CLI/配置及主体依赖矩阵不变，Prod/Tushare、Parquet写入、job、reload、sensor evaluation/enable、pool和安装均0。

本表P4历史接入阶段关闭，P4整体仍开放、P5未进入。当前六表已有独立asset/check/job/catalog及历史事件链；moneyflow仍未建立对应active资产/catalog/sensor和历史登记链，下一独立开发片应先接入moneyflow的资产/check/job/catalog，按原方案逐片验收，不在本轮自行编码或执行。此前d8f3e45c已提交未推送，本轮两份收尾文档及新报告尚未提交；其他工作区改动保留。


<a id="moneyflow-p4-definitions"></a>

## 59. P4传统个股独立定义接入（2026-10-12）

### 59.1 目标、依据和改动边界

moneyflow_ths全量历史收尾三文件已提交03019748，未推送。按管理员指令及已确认原方案，本轮推进moneyflow第一片：raw_tushare_moneyflow、silver_moneyflow、两条blocking checks、两个update job、cn_a_moneyflow_trade_days及catalog/name_mapping。依据本LLD§6的逐表7A卡、§15/P2真实源证据、P3历史物理验收、现行接入模板及性能治理规范。sensor、专属readiness、4067历史来源日预演和登记执行器留后续片；不运行正式job、不reload或写正式分区/event/Parquet。

CodeGraph explore核查相邻资产、日更publisher和check，impact核查update_daily_moneyflow_raw；索引别名覆盖不足，直接代码引用补齐五个daily资产、schema/request/collector/candidate/publication、catalog和测试消费者。20字段契约及P2请求策略复用，不改Prod DatasetDefinition/ExecutionPlan、API/CLI/前端或主体依赖矩阵。新分区/check/job名是独立身份。共享publisher固定允许项增加moneyflow；四份既有定义测试中“尚未接入moneyflow”负例相应移除，未知源、market专用链错误入口及路径穿越的拒绝保留。

### 59.2 开发约束、落点与测试

| 硬口径 | 代码落点 | 正反验证 |
| --- | --- | --- |
| 每源独立，Raw/Silver各自job和分区blocking check | assets/moneyflow.py、checks/moneyflow_stock.py、jobs/moneyflow.py、partitions、run_contracts/moneyflow.py、catalog | 实际Definitions/catalog与原生分区target；单job仅本层、无其他源混入 |
| 20源字段、trade_date+ts_code主键，金额万元/成交量手 | 既有asset_column_schemas、moneyflow_daily request/candidate/check及新metadata | 存档5572行20字段读回，含真实BJ348行；不按市场或对象池裁剪，空码/错日/重复/缺多字段拒绝 |
| BIGINT成交量、DECIMAL(20,4)金额；NULL/负值及源net_mf_vol/net_mf_amount不重算 | 既有SQL词法/精度校验、Raw/Silver标准化 | 全字段独立expected，非整数/溢出/布尔/精度超界拒绝；构造源净值与分项不一致仍保留；净量/净额/买入量篡改检查失败 |
| 单日trade_date/limit2000/offset，无代码展开；两轮稳定 | 既有daily collector/Raw publisher | 5572行每轮3页，两轮6请求；满页空尾页、乱序通过、空源或两轮净量变化失败；显式20字段 |
| Silver仅日期转DATE，绑定同日最新绿Raw及hash | 新Silver资产、原readiness与全字段check | 无Raw、跨日、旧/失败check、hash变化拒绝，Silver不请求源 |
| 已校验候选逐文件原子发布及持久checkpoint | 原writer锁/candidate/receipt/publication | replace后退出/意图后取消续跑、幂等修订、异源receipt隔离，禁止项在I/O前失败 |

配置审计：不新增配置。沿run_contracts/moneyflow.py的2000分页、每轮20000行、64请求（含重试）、300秒（含稳定等待）、两轮间隔60秒、RSS768MiB及DuckDB512MB/1线程/无spill；路径由paths.py唯一声明，writer pool保持现状。消费者为现行daily collector/candidate/audit/publisher与新资产/check；固定Python声明随definitions加载生效，无env/Settings/数据库覆盖。原P2预算负例和本片native job共同验收。没有新运营开关、状态表或summary资产。

| 性能/恢复项目 | 本片预算和验证 |
| --- | --- |
| unit、对象、历史、分区与枚举 | 完整单来源日，不按代码/市场展开；每次两层2文件；历史4067日/14089300行每层、8134文件沿P3，本轮不逐日深扫；无枚举扩张 |
| 请求、源行数与写入 | 存档09-30实测5572行、每轮3页/两轮6请求、reject0；20000行满容量两轮含空尾页22请求，含重试仍受64总上限 |
| SQL/磁盘/内存 | 按页落候选、两轮全字段SQL比较、Silver日期类型转换；P2样本Raw541201B/Silver541177B和压力候选约24.3MB供预算，正式编码字节以只读实测为准；配置512MB/1线程/无spill，单run临时目录 |
| 持久化/事务/取消 | 每文件先完整校验再同盘os.replace及checkpoint；没有全历史数据库事务。取消不领取下一unit，已提升文件保留；按持久receipt/checkpoint及物理hash幂等恢复，不备份/Kopia |
| 时间与拒绝 | 真实日更含至少60秒稳定间隔且全部请求等待受300秒上限；fake clock不当网络SLA。行数、请求、时间、RSS、schema/主键/hash、精度/稳定性超界拒绝；只读单日审计30秒/RSS768MiB |

编码前正式只读09-30两文件已经核对：每层5572行、全部20字段一致，SH2320/SZ2904/BJ348，P3文件hash和bytes不变，0.3382秒。只用既有正式writer.lock只读共享锁，不访问instance、不执行正式check。现有项目.venv、fake source/clock、临时Lake/staging和native SQLite用于功能验收；六表原定义/七表P2回归、完整受保护catalog/static、隔离全Definitions、Ruff及文档门禁通过后才收尾。原63份moneyflow JSON报告逐字保留，最终完整门禁源码/测试hash需保持稳定。实施结果后填，本片结束不等于历史登记或P4整体完成，P5未进入。

编码前补核文件名：checks/moneyflow.py是既有市场级纯SQL校验，被P2/P3和mkt_dc消费；本表checks独立放checks/moneyflow_stock.py，避免同名覆盖及导入环。旧市场helper及全部消费者不改，最终check名称仍沿§6批准身份。


### 59.3 定义切片验收收尾

本表独立Raw/Silver、两条分区blocking checks、两个单层update job、cn_a_moneyflow_trade_days及catalog两资产/两partition models已接入；checks放moneyflow_stock.py，原moneyflow.py市场SQL helper和消费者保留。daily publisher仅增加固定moneyflow允许项；既有其他源、数据路径和请求/标准化算法不改。两条check固定名称沿§6，显式分区与asset一致，Silver只依赖本表Raw。不新增sensor、配置、summary或状态表。

| 验收项目 | 当前实测 |
| --- | --- |
| 新本表隔离原生job/check | 48项通过，20.30秒；单job仅选本层，check同日且target storage_id/run_id/timestamp与最新materialization一致 |
| 存档真实源5572行 | 明确20字段，两轮各3页，offset0/2000/4000、第二轮倒序；Raw/Silver各5572行、reject0、20字段全值一致，SH2320/SZ2904/BJ348 |
| 数值、单位及禁止项 | BIGINT量手、DECIMAL(20,4)金额万元保留；源净量/净额与分项不一致、NULL和负值不改。非整数、BIGINT溢出、布尔、超安全浮点、超精度/金额范围拒绝。错日/空码/重复/缺多字段/THS字段替换、空源或净量两轮变化无成功事件 |
| 上游及恢复 | 无Raw、异日、旧/失败check或hash变化拒绝Silver；净额/净量/买入量篡改check失败；replace后退出、意图后取消续跑、幂等重放及修订、异源receipt隔离通过 |
| 原链回归 | 六表原P4定义及七表P2共749项通过，116.22秒；原分页、精度、20000行/22请求、重试/时间/内存/取消门禁保留 |
| 完整治理和加载 | 现有受保护runner的完整catalog12项/516子断言、static113项通过；各批resource gate通过、denied区域不变。只增加三个新definition文件到精确可读清单，不弱化拒绝和限额。隔离全Definitions、15份变动Python Ruff与全DG致命检查通过 |
| 正式物理只读 | 09-30两文件各5572行/唯一键，20字段保真，P3 hash/bytes一致且前后不变；0.3382秒/RSS175570944B，不访问正式instance、不运行正式job/check |
| 范围与证据保留 | 1174份DG源码/测试hash在最终门禁期间及报告生成时保持；63份旧moneyflow JSON报告逐字保留；CodeGraph explore/impact及根sync/status已完成。主体依赖矩阵、Prod契约、API/CLI/前端不变 |

存档样本两job执行1.0078秒使用fake source/clock与临时SQLite，不当作真实网络或盘后日更耗时。正式P3样本Raw541201B、Silver541177B。真实历史规模从P3全量执行报告复核：2010-01-04至2026-09-30共4067日、每层14089300行、8134文件、2750606591B；本轮未深扫或重生成全部历史，不宣称本表正式分区和历史event已登记。

依据当前已验收P2 MCP实测与P0 SDK分页证据，未修改源参数/字段合同，本片没有重复调用源。定义设计前本轮重新查阅Dagster官方assets/resources/partitions/checks文档；沿当前已安装SDK，保留既有显式partitioned check的preview及job partitions_def弃用提示，原生归属已验证，没有升级或安装。临时门禁驱动首次使用了启动器不支持的suite别名，参数解析即拒绝，改为现有完整suite文件名后通过；没有绕过启动器或放宽测试策略。

[本轮结构化验收报告](../../reports/moneyflow_p4_moneyflow_evidence_20261012.json)保存全字段源读回、原生job/check、P3物理指纹、成本、完整门禁及旧报告/源码hash。正式Lake/staging control/instance/PG/event/分区写入、正式job/check、源请求、reload、sensor evaluation/enable、pool和安装全部0；隔离临时写入仅用于验收。文档完整性和本片相对链接/锚点检查需通过，不能替代语义验收。

本定义切片关闭，moneyflow历史登记阶段未进入，P4整体开放、P5未进入。本轮15份源码/测试、两份方案文档和一份新报告尚未提交，其他任务工作区改动保留。下一独立片接三个默认STOPPED sensor、专属file/event readiness与4067历史来源日有界只读预演；沿上海22:00登记、最近10交易日/单tick最多1run，历史不逐日深扫。之后再做可恢复执行器和两日/全量冻结清单；正式执行按阶段精确清单批准。


<a id="moneyflow-automation"></a>

## 60. P4传统个股sensor、就绪判断及4067日只读预演（2026-10-12）

### 60.1 开发目标、边界与硬口径

上一独立定义切片18文件已提交d93cd771，未推送。管理员明确要求推进moneyflow三个STOPPED sensor、就绪判断及4067历史来源日只读预演。依据本LLD§6/§14/§28/§59、已确认原方案、现行DG接入模板7A及性能规范，本节先于代码记录约束和预算。新增STOCK_MONEYFLOW_AUTOMATION固定身份、三个sensor和readiness/preview薄入口；正式登记执行器、两日/全量冻结APPLY清单留下一片。本轮不运行正式job/sensor evaluation、不reload/启用、改pool、登记分区/event或写正式Lake/staging。

| 硬口径 | 代码落点与正反验收 |
| --- | --- |
| 每源独立且三个默认STOPPED，不在sensor请求源 | sensors/moneyflow_sensor.py：cn_a_moneyflow_trade_day_sensor、raw_tushare_moneyflow_update_job_sensor、silver_moneyflow_update_job_sensor；600秒最小间隔，仅lake_root/duckdb；定义/标签/调用次数测试 |
| 上海22:00后优先当天、最多再补一漏登记日 | register_moneyflow_trade_days固定cn_a_moneyflow_trade_days/history_start2010-01-04；22点前、假日、起点前和其他源分区反例；隔离evaluate_tick只返回请求 |
| 更新仅最近10交易日、每tick最多一job | evaluate_moneyflow_update：SSE日历、2026-10-01日更起点、DESC LIMIT10、当天优先；active run阻断；热路径不查4067日期 |
| 最新同日物化/green blocking check精确target及文件hash才ready | asset_guards/moneyflow_readiness.py→batch_moneyflow_readiness；storage_id/run_id/timestamp、hash及无symlink；Silver绑定Raw hash；跨日/旧或失败check/篡改/hash预算反例 |
| 独立cursor，尝试次数由原生run key约束 | 固定dataset/layer、cursor8192B硬上限；丢cursor不重置六次每日attempt；临时源错误可重试，权限/字段/精度失败阻断 |
| 20字段、量手/金额万元及源净量/净额保留 | 复用P2/P4 schema/request/SQL；5572行存档native job读回、真实BJ348行；本片不改字段/源参数、不新增请求或市场过滤 |
| 历史只用冻结来源日期和证明 | bootstrap/moneyflow_event_preview.py→shared history proof；operation=history-full-20261009、cutoff2026-09-30/cohort05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618；217unit/8134文件、最近20日schema/主键/20字段及冻结每日行数；proof保留row_count，无scope派生 |
| 原事件/证明不匹配则拒绝，不冒充登记完成 | 全文件/control当前hash与P3一致；每批100日期读取原生事实、截断/旧revision/错upstream/错target反例；已有文件无物化必须not ready；只读接口无写方法 |
| 旧六表不改语义，完整门禁 | 共享合同只增加本表、旧revision与预算保持；测试/治理HTML/静态清单同步，完整catalog/static、Definitions及原六表回归；64份旧JSON报告逐字保留 |

CodeGraph explore/impact覆盖sensor、固定automation合同、batch readiness、history proof/native state和shared event engine；索引对别名消费者不完整，用当前源码补核selector、六表adapter及全部测试。新增合同不改class shape或原六表revision，不增加正式APPLY入口。Prod DatasetDefinition/ExecutionPlan、API/CLI/前端及主体依赖矩阵不变。模块名现存无冲突；原checks/moneyflow.py市场helper不动。

### 60.2 配置审计、性能和只读执行约束

| 项目 | 预算、来源和拒绝策略 |
| --- | --- |
| 新固定文件预算 | MONEYFLOW_STOCK_READINESS_FILE_MAX_BYTES=4*1024*1024，唯一源码run_contracts/moneyflow.py；唯一生产消费者batch_moneyflow_readiness的固定moneyflow分支，无env/Settings/DB/配置文件覆盖，随definitions加载生效；超限reason=file_hash_budget且不hash，cursor可见，正反测试 |
| 配置依据/依赖 | 09-30实测Raw541201B/Silver541177B；P2 20000行压力Raw1756537B/Silver1756513B，小于4MiB。它只限制日更hash，不改schema或支持任意长字符串；其他六表64KiB/独立4MiB预算保持；依赖512MB/1线程/无spill和RSS768MiB原预算，无新运营开关 |
| 日更热路径 | 最多2mat+2check（limit100）+2active run（limit1）+1partition+1日历SQL，最多20文件/80MiB顺序hash；Raw选中日另读1批run records，失败时另读1条failure记录；source请求0、最多1run；10日5572行fixture测量目标<2秒/cursor<2KiB，硬上限8KiB |
| 历史规模/扫描 | P3已实测4067日/每层14089300行、217已完成unit、8134文件/2750606591B；436份cohort/progress/逐unit checkpoint/promotion控制。每文件当前hash，最近20日才深验Raw/Silver全字段及冻结行数，其余依据P3完整证明；不逐日扫描全明细、不导出或写Parquet |
| 原生事件成本 | 1partition+每层ceil(4067/100)=41次mat+每层1次recent check=85次helper读；100日期/100记录边界与截断拒绝，禁止4067次逐日readiness |
| SQL/DB/时间 | DuckDB512MB/1线程/no-spill、RSS768MiB、单unit120秒；正式PG statement_timeout10秒/default_transaction_read_only=on、should_autocreate_tables=False。每遍预演120秒包络/逐文件取消检查，两遍一致性复验驱动270秒上限，运行期间输出进度；原预算不因容量扩大放宽 |
| 取消/恢复与持久化 | 只读可中断后从相同冻结证明重跑；只打开既有writer.lock的rb共享锁，不创建正式目录/锁/plan/checkpoint。报告/driver/log只写/private/tmp和仓库，不新建运行状态实体，无写事务/备份/Kopia |
| 隔离验收/正式只读 | fake source/clock、临时Lake/native SQLite验收22点/身份/retry/check/hash/10日性能；容量4067日期85次查询反例。正式两遍全来源日proof与native差集、最近10日readiness，原文件/control/报告不变；不是正式sensor/job测试 |

正式预演工作目录/Users/congming/github/goldenshare/lake_console/orchestrator，命令`.venv/bin/python3 -B /private/tmp/moneyflow-automation-20261012/formal-launch.py`；只读readiness命令`.venv/bin/python3 -B /private/tmp/moneyflow-automation-20261012/readiness-launch.py`。使用既有/Users/congming/.goldenshare/dagster_home/dagster.yaml解析的只读native adapter，不自动DDL/不加载schedule storage，不读token。正式Lake=/Volumes/datasource/data_lake、staging=/Volumes/datasource/data_lake_staging，仅读本表两asset/check和分区。输出只在临时目录和仓库。正式文件/control/PG/event/分区写入、源API、job/sensor evaluation、reload/enable/pool/安装均0。

官方依据：[Dagster sensors](https://docs.dagster.io/guides/automate/sensors)、[partitions](https://docs.dagster.io/guides/build/partitions-and-backfills/partitioning-assets)，当前SDK原生隔离结果决定实际语义。default STOPPED定义不证明workspace已reload或持久状态；以下结果执行后回填，P4整体开放，P5未进入。


### 60.3 本切片验收收尾

三个独立sensor已接入，默认STOPPED、最小间隔600秒。上海22:00后优先登记当天，最多补一个历史漏登记日；22点前、假日和2010-01-04起点前拒绝登记。更新只看最近10交易日，每tick最多一job；sensor不请求Tushare，Silver绑定同日最新绿Raw及对应hash。STOPPED指源码默认定义，正式workspace没有reload或启用，不据此宣称持久sensor状态已验收。

就绪判断核对最新同日materialization、SUCCEEDED/passed/blocking check和精确storage_id/run_id/timestamp target，再核对物理hash与Silver raw_sha256。已有文件但没有物化不能放绿；旧check、失效check、Raw修订、异源/异层cursor、hash预算和读取截断均有拒绝反例；丢cursor不重置每日6次原生run key尝试。共享实现只加本表固定身份、row_count核对和4MiB预算，原六表身份/revision/预算及接口保留。

| 验收项 | 实际结果 |
| --- | --- |
| 新sensor/readiness/preview | 55项通过，32.01秒；22点/假日/起点、每日重试与cursor、旧/失败check/hash、上游修订、冻结行数、异源隔离、合成缺日不补算、4067日/85次读取和截断拒绝 |
| 原链回归 | 593项通过，487.63秒；原六表sensor、预演和可恢复事件执行器，以及moneyflow已提交定义；隔离native SQLite/Lake/staging |
| 十日热窗口 | 存档5572行样本复制到10个隔离日期，两层20个原生job/check；tick为2mat+2check+2active run+1partition+1日历SQL，顺序hash20文件/10823780B，0.0259秒、cursor555B，tick源请求0 |
| 正式全历史只读 | 两遍一致：2010-01-04..2026-09-30共4067来源日，每层14089300行、217unit、8134文件/2750606591B和436控制hash不变；各文件sha256/bytes同时匹配P3原审计，最近20来源日20字段/date+ts_code/冻结行数核验通过 |
| 历史读取成本 | 每遍1partition+82批mat+2check=85次原生helper读取，耗时5.7461/5.0194秒；最大文件553963B<4MiB；没有4067次逐日事件查询或全明细SQL深扫 |
| 正式十日readiness | 两层20个判断均file_without_materialization、ready=false；2mat+2check查询，不以文件存在代替已登记 |
| 待登记数量 | 4067分区、Raw4067+Silver4067物化、最近20来源日两层40检查：8174条event，合计12241项工作；本表不继承THS缺日清单，不造空分区 |
| 完整治理门禁 | 受保护catalog12项/516子断言、static113项/15批通过；逐批resource gate/denied区域保持/退出码核对通过，runner仅新增三份精确源码条目 |
| 完整性和影响 | 全Definitions隔离加载、11份改动Python Ruff及全DG致命检查通过；1179份DG源码/测试在完整门禁期间保持，64份旧报告逐字保留；根CodeGraph sync/status通过。主体依赖矩阵、Prod DatasetDefinition/ExecutionPlan、API/CLI/前端不变 |

[本轮证据](../../reports/moneyflow_p4_moneyflow_sensor_event_preview_evidence_20261012.json)保存两遍完整proof、8134物理/436控制hash、逐日冻结行数、原生查询数、十日热路径及完整门禁。正式PG只读事务、should_autocreate_tables=False；既有writer.lock仅只读共享打开。没有创建正式目录/锁/plan/checkpoint，正式Lake/staging control/partition/event写入、源请求、job/sensor evaluation、reload/enable/pool/安装全部0。

十日为合成日期和存档5572行样本，约26毫秒不能外推真实网络日更耗时；两遍历史hash速度也不等于源请求速度。最新20来源日追加全字段SQL，其他日期依据P3完整证明及当前逐文件hash，不重新请求历史。本轮只关闭sensor、readiness和只读预演这一片，P4整体开放、P5未进入。上一片已提交d93cd771未推送，本轮尚未提交。下一片是本表可恢复历史登记执行器、隔离两日样本与4067日冻结全量执行清单；正式登记按精确阶段批准。本表row_count写入/读回须随执行器接入，不能用shared engine已有本表身份推定已完成。


<a id="moneyflow-stock-history-events"></a>

## 61. P4传统个股可恢复历史登记、两日样本和4067日冻结执行清单（2026-10-12）

### 61.1 目标、依据、范围与编码前约束

上一片16文件已提交e22a68e3，未推送。管理员批准开发本表可恢复登记执行器、隔离两日样本与4067日全量冻结清单。依据原方案§6/§14、LLD§28/§31/§59/§60、当前已验收六表planner/publisher、接入模板7A和性能规范。新增bootstrap/moneyflow_stock_event_plan.py与bootstrap/moneyflow_events.py固定入口；共享moneyflow_event_plan.py保持原结构。本表单源独立，不新增asset/job/sensor/CLI，不改20字段、金额万元/数量手、NULL/负值/源净量和净额，不引入股票池过滤。

4,067日共12,241工作项，不能组成一个可APPLY的旧格式plan：现行max_work_items=4096会提前拒绝，直接提高上限又会突破256次读取。当前批准上限适用于每次独立APPLY，因此全量冻结清单由五个有序独立plan组成：1000/1000/1000/1000/67日，依旧覆盖同一个moneyflow数据集，不能解释成五数据集。各plan共享同一P3来源证明/截止/正式instance身份，按原生日期排序无重复无遗漏。planner只读一次完整proof，再用原_assemble按范围冻结；不重复五次扫描2.75GB文件。不改变原六表清单和预算，不重置同一个plan的读取计数来绕过门禁。

| 硬口径 | 当前代码落点及正反测试 |
| --- | --- |
| 默认只读、固定本表身份 | build_stock_moneyflow_event_plan/build_stock_moneyflow_event_plans/validate_stock_moneyflow_event_plan→原planner；report_stock_moneyflow_history_events→原publisher、apply=False；异源plan/其他instance/nonbool apply拒绝，不接Definitions |
| 全量有界五单元 | plural builder一次proof、1000来源日切段；每段max4096项/256读/600秒、内层100日期/120秒；4067来源日精确覆盖、单一4067日plan拒绝、不同源revision保持、尾段不造空日 |
| 行数事实 | proof每日期row_count；原_row_count/materialization/check metadata直接使用，state读回dagster/row_count、source_row_count与checked_row_count；加入moneyflow到两处固定验证集合，错误已有计数拒绝，不覆盖 |
| 物理绿后才登记 | 每plan重验P3全部8134文件hash/436控制及最近20来源日完整20字段/date+code/冻结行数；check阶段只对本plan与最近20来源日的交集执行同一SQL/冻结计数，不扩到更早日期 |
| 可恢复及幂等 | 原publisher原生分区/mat/check为完成事实；分区100日提交、每event持久化，plan.json/checkpoint.json fsync+os.replace；取消/真实进程退出/观测失败后重读native只补差集，checkpoint不能冒充完成 |
| 唯一writer和实例 | 原moneyflow writer全命名空间互斥、每批检查两job active，真实storage身份不包含event ID；计划/control/path/symlink/文件hash/旧revision/旧check target变化拒绝 |
| 进度/拒绝 | 每提交和批量读回输出stage/current_date/layer/completed/total/percent/updated_at/elapsed/reads；观察回调失败不回滚事件，checkpoint失败停止但保留已提交event；超时/读取/写入/RSS预算拒绝 |
| 样本和容量 | 存档5572行fixture构造隔离两日5571/5572差异，20列metadata及精确原生check target、累计10项/8event；1000日真实临时文件/native容量、4067日五plan覆盖和恢复；真实正式两日只读取实际计数，不能用合成计数冒充 |
| 完整门禁 | 原六表events和本表definitions/sensors/preview回归、完整受保护catalog/static、隔离defs、默认Ruff；65旧JSON、12旧冻结清单和DG源码hash保留；主体依赖矩阵/Prod/API/CLI不变 |

CodeGraph explore/impact覆盖shared plan、publisher、THS/DC/板块/行业/概念/大盘fixed adapters、proof/native state与测试；别名impact不完整，以当前实际imports和六表源码补核。此次仅完成已批准本表fixed adapter和metadata计数门禁，不改已有planner/publisher参数或原六表revision/limits。

### 61.2 配置与成本审计

| 项 | 设计上限/拒绝/测量方法 |
| --- | --- |
| 本表新切段常量 | MONEYFLOW_STOCK_EVENT_PLAN_MAX_DATES=1000，唯一来源run_contracts/moneyflow.py；源码持久化，无env/Settings/DB/运营覆盖，唯一生产消费者build_stock_moneyflow_event_plans，导入生效，不reload正式workspace。每个plan显式entries/limits运维可见；测试999/1000/1001/4067边界、一次proof、exact date coverage/固定旧预算 |
| 常量依据与依赖 | 当前最坏1000日且含20最近检查：3*1000+40=3040项，按现行publisher全新登记最多251 helper读取，均低于4096/256；无recent的1000日3000项/225读，尾67日241项/53读。依赖100日期batch、20来源日check、256读取及4096工作上限；不是源请求参数 |
| 真实来源/范围 | P3 operation history-full-20261009、cutoff2026-09-30、cohort05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618；2010-01-04..2026-09-30共4067日、每层14089300行、217unit、8134文件/2750606591B、436control；不访问Prod/Tushare |
| 读取/SQL | 全量五子清单共用一次完整proof；两日sample单独重验，重建一致性检查同样重读proof；正式预览分别validate重验proof，不缓存掉真实hash。一个sample default preview7native；四个1000日plan各23native、尾67日7native；全量clear list default preview99native，不是底层SQL数。完整后全范围native差集另85读；不逐日期readiness |
| 写入量 | 本轮正式0；批准后sample2分区/4mat/4check=10项/8event，全量4067分区/8134mat/40check=12241项/8174event；前四plan各3000项/2000event，尾241项/174event。只有本表已有文件登记，不写Parquet或其他源 |
| APPLY预算 | 五独立plan各≤600秒/256native/4096项/100日期批/批120秒/RSS768MiB；完整列表静态最多3000秒/1280读/12241项。全新登记预计225*4+53=953native，外部85读及维护检查另计。批准全量前用样本真实成本再准入，不能把隔离SQLite耗时当PG SLA |
| 内存/文件/spill | 原DuckDB512MB/1线程/0spill，单JSON完整proof/plan32MiB，checkpoint256KiB；native每次≤100条、物化条目只保存4067级file facts而不是14089300业务明细。候选生成/提升为0，正式只读existing writer.lock rb共享开，不创建目录/锁/control |
| 恢复与跨单元 | 每单元独立plan_hash/plan/checkpoint，未完成单元先重读native差集再续跑；已完成单元重放零写且身份保持，再推进后续。全量清单记录五子plan顺序/hash/路径和覆盖总数；没有另一份“已完成”状态表，也不以清单完成标记代替native最终85读对账 |
| 冻结产物/批准边界 | 本轮只在仓库reports保存两日plan、五个分段plan和汇总冻结执行清单，记录各内部hash/外部sha256。正式staging/PG/partition/event写入、source/job/sensor/reload/enable/pool/安装均0；正式sample与五单元full分别按清单批准 |

官方依据：[Dagster instance/runless API](https://docs.dagster.io/api/dagster/internals)、[metadata](https://docs.dagster.io/guides/build/assets/metadata-and-tags)、[asset checks](https://docs.dagster.io/guides/test/asset-checks)。本轮用已安装SDK和隔离native storage确认，不升级依赖。全量清单是范围和审批依据，不是正式完成事实；结果执行后回填，P4整体开放、P5未进入。


### 61.3 本开发片验收完成

本表固定planner/validator、五单元builder及登记入口已接入。共享engine只将moneyflow加入已有行数验证集合，原六表参数/revision/预算保持。物化记录20个observed_columns和冻结逐日行数，检查使用SQL读回计数并绑定精确storage_id/run_id/timestamp；默认apply=False，异源、storage、文件/control、行数、旧check target变化与读取截断拒绝。

| 验收项目 | 实际结果 |
| --- | --- |
| 本表执行器 | 57项通过，246.79秒；取消、真实子进程退出、丢失/错误checkpoint、保存或观察失败、续跑/幂等、active/writer互斥、错误计数、跨六表拒绝、999/1000/1001/4067边界及一次proof |
| 原链回归 | 原六表events及本表definitions/sensors/preview共384项通过，415.35秒；隔离SQLite/Lake/staging，不请求真实源 |
| 隔离两日 | 存档09-30源构造5571/5572行两日，20列、4mat/4check精确target、reject0；10/10项、0.2471秒/53读，重放0.1893秒、0新增，物理/来源control保持 |
| 1000日最坏单元 | 980单行旧日加最近20日5572行，共112420行；3040/3040项、2040event、251native读；11.8888秒，2074次原子保存/0.8936秒，最长0.0135秒 |
| 4067日五单元 | 合成日期容量，不是正式来源历史；115487行、12241/12241项、8174event、953native读，单元读取[225, 225, 225, 225, 53]，每单元均在4096项/256读/600秒内；仅最近20日40checks |
| 持久化/内存 | 五单元APPLY合计58.4785秒；8313次原子plan/checkpoint保存，累计3.1162秒、最长0.0045秒；RSS峰值635.2MiB<768MiB |
| 正式只读冻结 | 两次完整重建样本与五子plan相同；sample预检7读，五子plan23/23/23/23/7读，共99读；均completed0/formal_writes0。首次驱动55.9364秒；完整门禁通过后最终等值重建56.1223秒，六子plan及总清单内外hash保持，PG只读/禁自动DDL |
| 物理/原清单 | 8134文件/2750606591B和436来源control保持，文件sha256/bytes同时匹配上一P3-backed正式审计；原六表12份sample/full重建验证通过、65份旧报告逐字保留，正式events目录清单不变 |
| 完整门禁 | 受保护catalog12项/516子断言、static113项/15批通过；逐批resource gate、拒绝区域和退出码通过。隔离Definitions、六份改动Python默认Ruff与全DG致命检查通过；最终1182源码/测试hash保持，根CodeGraph同步 |

隔离容量使用合成日期、较早单行文件和最近20日存档5572行样本，测量登记算法规模；不等于4067正式来源日的业务覆盖或正式PG耗时。正式清单覆盖的是P3实际2010-01-04..2026-09-30来源日，每层14089300行；09-29/09-30真实文件只读冻结行数为5571/5572，样本源值仍须正式登记后读回。只有最近20实际来源日追加完整字段SQL，早期依据P3闭合证明及当前逐文件hash，不补THS缺日或重算任何资金值。

[执行器验收报告](../../reports/moneyflow_p4_moneyflow_event_registration_executor_evidence_20261012.json)保存容量/恢复/原生读回、8134物理/436控制事实、原12清单、完整门禁及源码hash。全部正式Lake/staging control/partition/event写入、Prod/Tushare请求、正式job/sensor evaluation、reload/enable/pool/安装均0；主体依赖矩阵、Prod DatasetDefinition/ExecutionPlan、API/CLI及前端不变。开发中两处测试表达错误已修正并整套重跑：合计953读不能与单元256读上限混比，跨源测试引用真实已存在的固定函数名。

### 61.4 冻结清单与下一阶段

六份子清单沿用既有可恢复事件plan格式；全量总清单使用stock_moneyflow_frozen_execution_list_v1，仅记录有序范围、子清单路径及内外hash，不作为完成状态，不可直接传给publisher。正式APPLY时核对总清单manifest_hash和文件sha256，再按顺序给固定publisher传入各原格式子plan；每个子plan独立重验当前物理/控制证明和native差集，已完成单元重放零写，失败单元先续跑，未领取单元不启动。

| 清单 | 冻结范围 | 内部plan_hash | JSON文件sha256 |
| --- | --- | --- | --- |
| [两日样本](../../reports/moneyflow_p4_moneyflow_event_registration_sample_plan_20261012.json) | 2026-09-29..2026-09-30；2来源日；11143行/层；10项 | 45aadf69d0f719f5cecf525932c6ce65a2b40b33915d201602b694d12ae63444 | a4951d3a1ab8043666977f95b47839efad29e128416cda42029b35f1921309de |
| [full_unit_01](../../reports/moneyflow_p4_moneyflow_event_registration_full_unit_01_plan_20261012.json) | 2010-01-04..2014-02-24；1000来源日；2149165行/层；3000项 | 698ce6c0ba7b04e895c4b08027278255c54b7d40e26669cfa153e5acfe844edf | f1965bd2c5f8c601647207bad830e9d94871b77175fc68cd1abcc2b53c1404af |
| [full_unit_02](../../reports/moneyflow_p4_moneyflow_event_registration_full_unit_02_plan_20261012.json) | 2014-02-25..2018-03-27；1000来源日；2625320行/层；3000项 | 1f054cd3bfb1d52bf31df9a276021efa58832de9be0c64ff26b9cbf1680c68e9 | 23ab172f749fe68c516e006fcd5210b6ddb8f992197c302cdd53b07962223df5 |
| [full_unit_03](../../reports/moneyflow_p4_moneyflow_event_registration_full_unit_03_plan_20261012.json) | 2018-03-28..2022-05-12；1000来源日；3910246行/层；3000项 | 0d0ae62d5f9fdcdde3c6812288f1fd45dcb8f7dfa53eef57e7500a9f15115de4 | 49746c56591a3d9bf6f5b77dc18d26fcc135489a1da7115ca462c5ed31f38cae |
| [full_unit_04](../../reports/moneyflow_p4_moneyflow_event_registration_full_unit_04_plan_20261012.json) | 2022-05-13..2026-06-26；1000来源日；5042058行/层；3000项 | cfefb1077989bed00b5070d9a26917afc60bbc4bb70685346e06290d5255c5fc | 64c4909ddb4bc35e75175979751f67d11faab4f201c7014125e25177664aa5bf |
| [full_unit_05](../../reports/moneyflow_p4_moneyflow_event_registration_full_unit_05_plan_20261012.json) | 2026-06-29..2026-09-30；67来源日；362511行/层；241项 | 026108aeccb54667ee9fba4ff4ac24be8c564040d3a06447e2f9a1d4f278e216 | 81b0b68726d1d6cc8bc54e45717fa8ea1a3da692ab663f2911e4240bbddd2595 |

[4067日冻结总清单](../../reports/moneyflow_p4_moneyflow_event_registration_full_plan_20261012.json)：manifest_hash=578f70c1119a5cd901726c2103fd0703ac309b348c6cc4d3b3d70cc26245ea55，文件sha256=c1fcd6a100533b1a7556f832e4e52590d960884ea022a6bab484256980fd0f90，4361B。精确覆盖4067分区/8134物化/最近20来源日40checks，共12241工作项/8174event；五子清单无重复无遗漏，同一正式storage身份/cohort/截止，仍是一个独立数据集。全量全新APPLY预计953helper读，完成后另做85次全范围native差集读回；单元预算不得互相借用，最大静态总预算1280读/3000秒，原读取/时间/内存/写入门禁不变。

正式只读冻结工作目录为/Users/congming/github/goldenshare/lake_console/orchestrator，命令`.venv/bin/python3 -B /private/tmp/moneyflow-events-20261012/formal-launch.py`，临时驱动/日志在/private/tmp，只开既有writer.lock为只读共享锁，不创建正式目录或状态。驱动重建并比对冻结内容，拒绝覆盖已存在但不相同的清单；正式PG adapter为writable=False、should_autocreate_tables=False。该命令可复现本轮冻结证据，正式登记后completed应按native事实变化，不能仍要求completed0。

本开发片关闭，P4整体仍开放、P5未进入。上一片e22a68e3已提交未推送，本轮六份Python、两文档、七份冻结JSON和一份验收报告尚未提交；其他工作区修改保留。下一阶段按冻结两日清单获批后登记2分区/4mat/4check、读回精确身份/target/20字段/行数和两层四readiness，并实际重放0新增。执行前复核持久sensor未启用、两job无active、维护窗口、当前源码/storage/hash、writer互斥和staging至少32MiB空间，再冻结具体正式驱动命令；本轮没有构造或调用正式APPLY命令。

两日样本批准不含全量。样本正式完成后，全量原冻结清单hash保持，预期剩4065分区/8130物化/36checks，共12231项/8166event；实际按native差集为准。再以样本正式PG成本测算五单元、独立批准全量并最终全范围对账。sensor启用、正式job、reload与P5保持独立阶段。


<a id="moneyflow-formal-sample"></a>

## 62. P4传统个股正式两日历史登记与读回验收（2026-10-13）

### 62.1 已批准范围、依据与执行约束

上一开发片16文件已提交feb54805，未推送。管理员本轮明确批准按原冻结两日清单正式登记并读回；仅2026-09-29/09-30的cn_a_moneyflow_trade_days、raw_tushare_moneyflow和silver_moneyflow各2物化、各2 blocking检查。原文件每层5571/5572行、20字段、reject0。sample plan_hash=45aadf69d0f719f5cecf525932c6ce65a2b40b33915d201602b694d12ae63444，外部sha256=a4951d3a1ab8043666977f95b47839efad29e128416cda42029b35f1921309de；全量manifest_hash=578f70c1119a5cd901726c2103fd0703ac309b348c6cc4d3b3d70cc26245ea55、文件sha256=c1fcd6a100533b1a7556f832e4e52590d960884ea022a6bab484256980fd0f90，五子清单只读，不APPLY。

| 硬约束 | 当前实现与本轮核验 |
| --- | --- |
| 精确两日写入 | 固定report_stock_moneyflow_history_events/STOCK_MONEYFLOW_AUTOMATION；driver再次限制2日/2asset/2check/专属partition，最多2key+8event；不传五子plan或总清单进入APPLY |
| 源码与真实实例 | 已接受1182源码/测试快照，运行时已加载模块hash一致；dev-interface，feb54805必须为当前HEAD祖先，全部1182源码hash保持。既有daily_basic_event_instance对应正式home、PG goldenshare_dagster，禁自动DDL/初始化，readonly使用default_transaction_read_only=on |
| 维护/互斥/空间 | 三个本表sensor源码STOPPED且持久状态不得RUNNING；两job无active，既有writer.lock独占非阻塞测试通过、publisher内真正独占；挂载、无symlink、同设备、staging至少32MiB。当前管理员精确批准为维护窗口 |
| 只读先行 | 默认驱动预检sample，原publisher重验8134文件/436控制及最近20日完整SQL；4067日全scope使用85次批读native差集，原六表98次批读身份对照，不逐日readiness |
| 行数和身份 | 4mat验证20 observed_columns/source及row_count/file/cohort/cutoff/checkpoint/reject/Silver raw_sha256；4check须SUCCEEDED/passed/blocking、checked_row_count与精确storage_id/run_id/timestamp target；两日两层4ready |
| 可恢复与重放 | 原publisher逐key batch/逐event提交、同plan_hash plan/checkpoint原子持久化；异常保留native事实，重复同命令补差集，不删事件。实际重放0key/0event且身份保持；再独立新只读进程复验 |
| 保留事实 | 73既有JSON/既有CSV、1182源码/测试、P3全部15608文件/来源控制、原六表native身份及24旧event控制保持；只新增本sample的plan/checkpoint |
| 范围外 | 不导出/请求Prod或Tushare、不写Parquet、不启动job或执行sensor、不reload/启用、不改pool/配置/契约，不进入全量/P5 |

CodeGraph explore核对固定publisher→共享engine→native读回、adapter/readiness及实际imports；driver只编排既有已验收入口，不改正式Python/定义/catalog/字段合同或主体依赖矩阵。依据[Dagster instance/runless API](https://docs.dagster.io/api/dagster/internals)、[checks](https://docs.dagster.io/guides/test/asset-checks)、模板7A及性能规范；使用现有SDK，不安装/升级。

### 62.2 成本、完整命令与阶段顺序

| 项目 | 上限与拒绝策略 |
| --- | --- |
| 写入 | 最多2partition+4mat+4check=10项/8event，仅登记既有4日层文件；源请求/候选/Parquet写入0，只新增events/<sample_hash>/plan.json、checkpoint.json |
| 来源 | cutoff2026-09-30/cohort05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618/operation history-full-20261009；样本11143行/层。全量4067日/14089300行每层仅读 |
| 原预算 | 100日batch/4096项/256native读/600秒/每unit120秒/RSS768MiB；DuckDB512MB/1线程/0spill；隔离sample53读/~0.25秒不是正式PG SLA，记录真实APPLY/重放/driver耗时 |
| 外部审计 | 本表完整范围85native读、sample5读、原六表98次批读，mat/check每请求limit100；sensor仅native一次只读inventory，超过2000条拒绝。全P3文件只核对sha/bytes、不把业务明细读到Python |
| 事务/恢复 | PG statement_timeout10秒；分区batch和每event独立提交，无全历史长事务，checkpoint fsync+os.replace。失败不回滚既有事件或Parquet，按native差集续跑，不信任checkpoint完成数 |
| home/目录 | 工作目录/Users/congming/github/goldenshare/lake_console/orchestrator；正式home=/Users/congming/.goldenshare/dagster_home；Lake=/Volumes/datasource/data_lake，staging=/Volumes/datasource/data_lake_staging |
| 最终验收 | 新进程writable=False，4mat/4check/4ready、85次全scope缺口、sensor/active/source/native/物理/control复验；仅读模式不创建正式目录/锁/control |

临时driver由本任务负责，仅/private/tmp保存本次证据，不进入active Definitions或新增正式CLI/配置；样本收尾后不作为日更入口，不可用于全量。命令：

1. 默认只读预检：`.venv/bin/python3 -B /private/tmp/moneyflow-formal-sample-20261013/run.py`。
2. 预检绿后执行已批准两日及实际0新增重放：`.venv/bin/python3 -B /private/tmp/moneyflow-formal-sample-20261013/run.py --apply`。中断后用相同清单/hash重跑此命令，以native事实补差集。
3. 独立新进程只读复验：`.venv/bin/python3 -B /private/tmp/moneyflow-formal-sample-20261013/run.py --verify`。

全量子plan只核对外部sha、内部plan_hash和总manifest_hash，不执行。样本后预期完整scope完成10/12241项，剩4065partition/8130mat/36check，共12231项/8166event，以native差集为准。执行结果随后回填，P4整体开放、P5未进入。


执行前工作区核验：另一任务新增f3bd42cb文档提交，仅改两份周线文档；1182验证源码hash全部保持，因此使用实现提交feb54805作为祖先及源码hash锚点，记录实际execution HEAD，不把HEAD字符串相等当作源码等价。另一任务将pyproject/uv.lock拟升级至1.13.26，实际已验收.venv仍Dagster1.13.18/Postgres0.29.18/DuckDB1.5.2；本任务不安装/同步或修改该依赖变更。直接现有解释器，并在每次分区/event写入前核验这三个runtime版本；版本变动则停止，已提交native事实保持。依赖文件当前hash和执行版本落入证据。


### 62.3 执行前环境变动与当前阻塞（未登记）

默认只读预检通过，sample完成0/10项，缺2分区/4物化/4检查；全范围缺4067分区/8134物化/40检查。随后另一已授权升级任务将共享.venv从Dagster1.13.18/Postgres0.29.18切换为1.13.26/0.29.26，DuckDB仍1.5.2。本任务正式命令在任何instance打开、分区或事件写入前被verify_runtime拦截；没有apply.json、没有样本checkpoint，本次正式写入0。此前62.2末段是预检时版本，不能据此认定当前仍1.13.18。

升级后的.venv为软链接，实际环境目录是本项目venv.bak/dg-1.13.26。受保护启动器tests/stock_suspend_confirmed_test_runner.py的policy_for只允许读取PROJECT/.venv；完整catalog门禁第一批在启动Python时被sandbox-exec拒绝，尚未执行8个测试，不是业务断言失败。既有启动器不得绕过；新SDK下隔离功能测试仍在运行，结果随后落报告，不能代替完整门禁。本任务不回退/安装/移动环境，不修改其他任务的pyproject、uv.lock或升级记录，不将1.13.18的完整门禁结果冒充1.13.26的通过结果。

#### 待管理员确认的最小修正方案

这是升级后受保护测试启动器的兼容修正，尚未修改正式源码。目标仅是让当前隔离门禁支持已存在的软链接虚拟环境，不能扩大正式数据访问能力。

| 项 | 具体范围 |
| --- | --- |
| 实现 | tests/stock_suspend_confirmed_test_runner.py的policy_for及其路径校验；解析当前PROJECT/.venv，验证实际目录后仅追加该精确环境目录的只读权限；不得放开整个venv.bak、仓库、/Volumes、正式.goldenshare或网络，不新增CLI/env配置 |
| 拒绝策略 | 环境不存在、目标不是目录、目标越界、环境标识不符或执行中软链接目标变化时拒绝；原源码逐文件白名单、隔离临时区写权限和正式资源拒绝保持 |
| 测试 | 真目录与当前软链接环境正例；越界/不存在/非目录/错误环境及变化目标反例；I03-I08原隔离测试、完整catalog与static门禁复跑，逐批核对resource gate和denied区域；所有套件使用原启动器，不用直接pytest代替保护 |
| 验收 | 新SDK下本表57项、原六表及本表384项、完整catalog12项/516子断言、static113项、隔离Definitions和Ruff；更新受影响源码快照并保留旧基线，原冻结JSON和来源/物理事实不变 |
| 继续条件 | 上述修正经确认且门禁全绿后，固定新运行版本、重做正式只读预检，再执行原已批准两日登记/读回/0新增重放/独立复验；不进入全量、不启用sensor |

CodeGraph sync/status已确认根索引最新；impact policy_for覆盖run_isolation_child/run_isolation_batch/run_startup_gate_batch/main，共6个符号。当前实际调用与policy源码再次核对。该修正只涉及测试启动器，不改变业务数据集、生产契约、API/CLI和主体依赖矩阵。依据本目录AGENTS“有专项受保护测试启动器时…不得绕过它直接运行pytest”及设计确认门禁，修正设计待确认；不能把样本登记批准扩大成隔离安全边界修改批准。


### 62.4 已批准修正与复验范围

管理员随后明确答复“批准修正并继续两日登记”。按62.3实施最小修正，仅变更tests/stock_suspend_confirmed_test_runner.py和tests/test_stock_suspend_confirmed_isolation.py：验证当前.venv真目录或直接指向本项目venv.bak子目录的软链接、pyvenv.cfg为普通文件且prompt=orchestrator/include-system-site-packages=false、Python与当前解释器一致；只允许这个精确环境真实目录的读取。记录真实路径、目录dev/inode、配置sha256和解释器，启动子进程前再次比对身份；执行命令固定已验证环境真实路径，软链接更换不能改道到另一目录。不新增CLI或env/Settings配置，不放行整个venv.bak，也不修改既有数据/网络拒绝或隔离区写入能力。

10个环境路径正反案例与原6个退出案例均由原保护启动器执行；测试只在已允许临时区构造环境路径，不安装解释器或依赖。复验发现原基础resource白名单缺少当前paths.py的静态导入闭包，补入moneyflow.py、asset_column_schemas.py、column_schema.py和stock_monthly.py四个已存在源码的精确只读路径，直接阅读当前imports确认，无source执行请求/资源构造副作用、不放行目录。此处属于原启动器准入修正，不修改这些业务文件或contract。最终还需I03-I08、完整catalog/static、两份测试默认Ruff及所有原冻结事实对账全绿。

共享SDK升级后功能回归已完成：本表57项通过（271.69秒），原六表events及本表定义/sensor/preview384项通过（417.41秒）；这些业务源码与原1182快照相同，仅上述2测试文件因已批准修正允许更新。原1.13.18结果保留，新增1.13.26证据单独记录，不能覆盖旧验收报告。新版本隔离Definitions和全DG致命Ruff通过。门禁最终完成后，正式执行驱动绑定1.13.26/0.29.26/1.5.2及本轮新增源码快照，再只读预检与原两日APPLY。


### 62.5 正式两日登记收尾完成

2026-10-13上海时间00:39完成两日登记，00:40完成实际重放，00:41完成独立只读复验。实际使用Dagster1.13.26、dagster-postgres0.29.26、DuckDB1.5.2；共享升级由另一任务完成并提交082cb66d，本任务没有安装、切换环境或启动/重启服务。开始时的环境版本拦截与隔离门禁故障记录保留；管理员批准修正后才继续，未绕过保护。

| 验收 | 实际结果 |
| --- | --- |
| 2026-09-29 | 原始层和标准化层各5571行；物化storage_id分别7458801/7458802，检查execution_id分别1599481/1599482 |
| 2026-09-30 | 两层各5572行；物化storage_id分别7458803/7458804，检查execution_id分别1599483/1599484 |
| 正式写入 | 2个动态分区、4条物化、4条通过的blocking检查，完成10/10项；只新增本样本plan.json/checkpoint.json。每条检查都绑定对应物化的storage_id/run_id/timestamp，行数与冻结清单相符，20字段及来源hash/截止/cohort一致，reject0 |
| 就绪 | 两日两层共4项均ready；新进程writable=False独立复验事件身份、检查target、就绪、checkpoint全部一致，正式写入0 |
| 重复执行 | 实际再次APPLY同一sample plan，新增分区0、事件0；原4物化/4检查身份完全不变，checkpoint完成10/10 |
| 实测成本 | APPLY10.7393秒/53次helper读取，实际重放10.4997秒/53次；整个执行驱动含前后只读审计45.6053秒，峰值496.8MiB<768MiB。独立只读驱动16.9933秒，峰值418.5MiB；进度60条、完成量单调 |
| 保留 | P3全部15608文件sha256与字节数保持；848来源控制、24旧事件控制、原六表原生登记身份、73旧JSON与1CSV全部保持。只有已批准的2测试文件更新，其余1180源码hash不变；新增样本控制文件恰为2个 |
| 完整门禁 | 新SDK下57项执行器、384项原链回归、catalog12项/516子断言、static113项/15批、I03-I08及新增10路径+原6退出案例全部通过。逐批resource gate和拒绝区域核验通过；隔离Definitions、2测试默认Ruff、全DG致命检查和文档检查通过 |

隔离启动器最终基础源码白名单为38个精确文件：补齐资源真实导入闭包的9个现存源码，不放行源码目录。虚拟环境只读权限只针对当前已验证真实目录与软链接入口；严格解析所需的目录祖先只允许metadata，不允许读取目录中的数据。真实环境路径、标识、配置摘要与解释器会在启动前再次核验；错目标、错标识、缺文件和执行前变更均有负向案例。SDK在本次每次分区/event写入前核验；当前已加载正式源码及1182源码/测试hash在阶段前后与最终再次核对，源数据集代码及契约没有变化。

[正式样本验收证据](../../reports/moneyflow_p4_moneyflow_event_registration_formal_sample_evidence_20261013.json)保存批准、版本变动与修正、新版本完整门禁、2日实际计数、8事件精确身份/target、原六表身份、物理/control/源码保留、实际重放及独立复验证据。样本与全量manifest、五子plan内外hash全部保持，既有正式PG identity没有变化。本轮执行头082cb66d含另一任务的依赖升级提交，实现提交feb54805仍是祖先；本任务新增2测试、2文档和1报告待提交，未推送。

本两日样本阶段关闭。P4整体仍开放、P5未进入；没有请求Prod/Tushare、写Parquet、运行job、执行或启用sensor、修改pool、进入全量。原三个sensor源码STOPPED，正式持久状态本轮前后均未出现RUNNING，本任务没有reload或改变调度状态。

下一阶段是原4067日五单元冻结清单的全量历史登记，须单独批准。当前原生差集：完成10/12241项，剩4065分区、8130物化、36检查，共12231项/8166事件；全量终验另85次批读。每单元仍100日期批、4096项/256读/600秒/768MiB，静态总上限1280读/3000秒，不扩大预算。两日样本实测含完整文件证明重验，不能按“4067/2倍总耗时”推算全量，更不能把隔离SQLite耗时当正式PG保证；执行驱动按五子plan原顺序逐单元准入、原生差集续跑、逐单元真实计时，超限即停并保留提交事实。全量清单不变，sensor启用及真实日更仍为后续独立阶段。


<a id="moneyflow-formal-full"></a>

## 63. P4传统个股全量历史登记（2026-10-13）

### 63.1 本轮批准与固定执行约束

管理员已要求先提交样本修改，再批准原冻结全量清单执行。五文件样本片已提交9f904f2e，未推送。本轮只执行§61的五个子清单；总manifest是执行顺序清单，不能直接传给publisher。manifest_hash仍为578f70c1119a5cd901726c2103fd0703ac309b348c6cc4d3b3d70cc26245ea55，五个子plan内外hash和原预算不变。4067来源日、每层14089300行、8134物化和最近20来源日40检查；原样本10项保持，预期本轮新增4065分区/8130物化/36检查。以原生差集为准，不以checkpoint冒充完成。

| 硬约束 | 实现与核验 |
| --- | --- |
| 逐子单元执行 | 原report_stock_moneyflow_history_events及共享engine，不改正式源码。临时driver仅按ordered_units顺序传原child，写入代理限制当前child的日期、2asset、专属partition及最近日期2check；单次写入计数不得超过child原工作范围 |
| 原预算 | 每child日期批100、4096项/256helper读/600秒/单批120秒/RSS768MiB，DuckDB512MB/1线程/0spill，PG statement_timeout10秒。五次初始APPLY静态上限3000秒/1280读；超限停止，不增加限额，不用反复重置计数绕过预算 |
| 预检 | 固定当前1.13.26/0.29.26/1.5.2运行版本，复核1182源码与上轮全绿门禁hash、5冻结清单hash/实例身份、互斥/挂载/同设备/32MiB可用空间。正式只读全scope85helper读及每child有限预演，全部通过后才能APPLY |
| 维护与范围 | 正式home=/Users/congming/.goldenshare/dagster_home、PG goldenshare_dagster；三个本表sensor不得RUNNING、两个job不得active；原publisher每批检查job、持有既有writer锁。无Prod/Tushare请求、Parquet写入、job/sensor执行或启用、reload、配置/定义/字段合同变更 |
| 持久化/恢复 | 分区按batch、event逐条独立提交，无全历史长事务。每child仅新增events/<hash>/plan.json与checkpoint.json；native身份是续跑依据。失败保留提交事实，同冻结child补差；事件误写不得直接删除回滚 |
| 独立验收 | 每child完成后有界原生批读核对所有mat的20字段/行数/来源hash/cohort/cutoff/checkpoint及check精确target；随后实际同child零新增APPLY重放，身份不变。重放是已完成单元的独立验收调用，沿用原600秒/256读，禁止用于重启未完成超预算unit |
| 全量验收 | 五child完成后全scope85次批读汇总4067keys/8134mat/40check；最近20日两层共40readiness，禁止4067日期逐日深扫。新只读进程再次核验全部身份、五个complete checkpoint、原样本和原六表身份/调度库存 |
| 保留 | 75既有moneyflow报告、15608 P3文件sha/bytes、848来源控制、26既有event控制、1182源码/测试及原六表native身份保持；最多新增五child共10个event控制文件。源码或环境变动则停止重新核验 |

使用CodeGraph explore核对固定入口→共享publisher→原生批读和readiness；调用面只在orchestrator内部，不影响主体依赖矩阵。官方依据为[instance API](https://docs.dagster.io/api/dagster/internals)和[checks](https://docs.dagster.io/guides/test/asset-checks)，模板7A和性能规范沿用。源/Parquet处理已由P3完成，本轮不新增字段或源参数契约。

### 63.2 完整命令、观察与外部审计成本

工作目录/Users/congming/github/goldenshare/lake_console/orchestrator，临时驱动仅/private/tmp/moneyflow-formal-full-20261013内保存本轮证据，不成为正式CLI或日更入口：

1. 原清单只读预检：`.venv/bin/python3 -B /private/tmp/moneyflow-formal-full-20261013/run.py`。
2. 顺序执行五child及各自零新增重放：`.venv/bin/python3 -B /private/tmp/moneyflow-formal-full-20261013/run.py --apply`。
3. 新进程只读独立复验：`.venv/bin/python3 -B /private/tmp/moneyflow-formal-full-20261013/run.py --verify`。

driver在每个child前后重新核验环境/已加载源码/全源hash和保留事实，publisher内每批active检查、每事件checkpoint和进度输出；/private/tmp另记逐child进度JSONL和阶段结果。取消后不领取新child；任何失败停止后续child。正常同命令续跑依赖native差集，不信任临时结果标记。原生终验每次完整scope85helper读；child状态21/21/21/21/5，外加最近检查最后child2读，五child合计91读。每child只读publisher另有active2读，五child预演合计101读；原六表身份98读。以上外部只读审核和零新增重放的成本与初始APPLY分列，不隐藏在1280读预算内；每个独立调用仍有界。全范围event明细只保存有限元数据，不读取业务明细到Python；全P3文件以sha/bytes证明不变。

执行结果待回填。此前样本和冻结证据保持历史原文；本轮批准不包含sensor启用或P5真实日更，P4整体仍开放。


#### 63.2.1 最终就绪窗口限制与只读收尾

五child已全部登记、读回、实际重放0新增；全scope已读回12241/12241项。临时driver最终调用readiness时一次传20日，现行batch_moneyflow_readiness只允许MONEYFLOW_SENSOR_WINDOW=10，因此抛readiness_window并停止。这是临时审核调用粒度错误，所有正式登记已提交且无须重做，不修改现行窗口、sensor或源代码。原失败apply.json/log原样保留，不能把其passed=false改为通过。

只读收尾按当前10日合同拆成2个批次，合并最近20日两层40项readiness；每批每层mat/check各1次helper，合计8次。只使用daily_basic_event_instance默认writable=False，重新核对全范围事件、五checkpoint精确内容、原样本事件身份、原六表、全部物理/control/hash和调度库存。样本身份核验与全量partition总数分别判断，避免把新增历史分区当成样本身份变更。首次收尾结果冻结，再由独立新只读进程比较全部身份和36个event控制hash。正式publisher与原预算均不变，后续不再APPLY。

实际收尾命令（同§63.2工作目录/home）：`.venv/bin/python3 -B /private/tmp/moneyflow-formal-full-20261013/run_closeout.py`；独立复验为`.venv/bin/python3 -B /private/tmp/moneyflow-formal-full-20261013/run_closeout.py --verify`。临时驱动拒绝--apply并且只打开只读instance；20日期拆分严格使用当前MONEYFLOW_SENSOR_WINDOW，不引入新配置。原初始APPLY脚本保留，未在运行中修改。


### 63.3 全量登记与独立验收完成

2026-10-13T01:46:04.879258+08:00，按原冻结五child顺序完成。正式结果为4067个动态分区、8134条物化、最近20来源日40条通过的blocking检查，共12241/12241项；每层14089300行，与来源证明一致。原样本2分区/4物化/4检查保持身份，本轮新增4065分区、8130物化、36检查。没有填造源缺失日。

| 单元 | 新分区 | 新事件 | 首次登记实测 | 实际同清单重放 |
| --- | --- | --- | --- | --- |
| 1 | 1000 | 2000 | 45.903秒/225读 | 15.670秒/225读，新增0 |
| 2 | 1000 | 2000 | 40.197秒/225读 | 16.650秒/225读，新增0 |
| 3 | 1000 | 2000 | 46.066秒/225读 | 16.413秒/225读，新增0 |
| 4 | 1000 | 2000 | 47.453秒/225读 | 12.448秒/225读，新增0 |
| 5 | 65 | 166 | 11.397秒/53读 | 8.126秒/53读，新增0 |

五次首次APPLY合计191.017秒/953次helper读；五次零新增重放合计69.307秒/953读。全部原预算通过；helper读取不等于底层SQL语句数。包括预检、前后读回、保留核验与重放的完整driver为349.087秒，首次driver最终审核因readiness_window停止，其整个进程峰值未记录；五次正式publisher全程执行768MiB内存门禁。随后只读收尾27.001秒、峰值556.5MiB；独立新只读进程23.642秒、峰值540.3MiB，均低于768MiB。各child完成量单调，逐event/batch持久化与进度记录通过，记录最大间隔13.256秒。

所有8134物化逐条核对20字段、精确行数、文件/上游hash、cohort、cutoff和来源checkpoint；40检查核对SUCCEEDED/passed/blocking、checked_row_count及storage_id/run_id/timestamp target。逐child真实零新增重放保持全部身份；最后完整scope85次批读及独立新进程再次读回一致，五个checkpoint均complete。最近20来源日两层40项readiness全部通过；旧历史未逐日补check，不把每个历史日宣称为严格ready。

全部15608 P3文件sha256/bytes、848来源控制、75既有资金流报告、26旧事件控制、1182源码/测试、原样本mat/check身份及原六表原生身份保持。恰好新增五child的10个plan/checkpoint控制文件。三个本表sensor仍源码STOPPED，持久库存没有RUNNING，本轮前后106条sensor身份/状态库存一致；无active本表job。没有Prod/Tushare请求、Parquet写入、job/sensor执行或启用、reload、安装/升级或配置/契约变化。

最终readiness首次调用20日被现有10日上限拒绝；原APPLY报告passed=false和错误记录保持，并明确区分五个正式单元已完成与最终审核尚未完成。后续两次仅用新只读进程，按现行MONEYFLOW_SENSOR_WINDOW分为2批，合计8次readiness helper读、40项全部ready；正式写入0。样本mat/check身份与全量partition总数分别核对，新增checkpoint全文及36个event控制hash精确一致。初始运行脚本保持原样，修正限于临时只读审核调用粒度；正式publisher、清单和预算不变。

[全量正式验收证据](../../reports/moneyflow_p4_moneyflow_event_registration_formal_full_evidence_20261013.json)保存五单元、全范围8134物化/40检查身份、真实重放、独立复验、成本与保留证据。本轮只有两文档与此报告新增修改待提交，未推送；原样本片提交9f904f2e。七个数据集的历史登记均已完成；本表P4历史阶段关闭，整个P4仍需调度启用前收口，P5真实日更未进入。下一阶段应审计历史截止后的接续窗口、七族源/目标当前状态和调度准入，再按独立批准启用；不能把历史登记批准扩大为日更启用。


## 64. P4调度收尾：七表接续窗口与启用条件只读审计（2026-10-13）

### 64.1 目标、依据与执行边界

管理员要求先提交上一轮，再审计七表日更接续窗口和sensor启用条件。上一轮两份文档与moneyflow全量验收报告已提交为`7bcf268a`，未推送。本轮依据原方案§3、§8、§11、本文§2及§63.3、DG性能治理规范和当前源码，审计范围为正式日历、历史原生身份、最近检查、接续文件、已加载定义、持久化sensor状态、运行状态、专属池和锁。仅更新本节、方案§69及审计报告，不实施发现的修正。

正式只读审计于上海时间2026-10-13 09:09执行。数据库连接使用既有`daily_basic_event_instance()`默认只读模式、禁止自动建表；schedule storage复用相同只读连接。池容量用三条明确SELECT读取，事务`transaction_read_only=on`，没有调用可能执行reconcile写入的`get_pool_limits/get_concurrency_keys`。日历由既有`connect_configured_duckdb`读取，512MB、1线程、existing_no_spill、临时目录为已有`/private/tmp`、spill为0、禁止扩展下载；只取日期/计数元数据，不把业务全表拉进Python。锁用已有文件的只读描述符探测并立即解锁，不创建或截断文件，不调用会创建锁的writer helper。

审计未执行sensor评估、启用/停用、游标更新、reload、job、分区或event写入、Tushare请求、正式Lake/staging写入及安装。纯源码定义导入不等于sensor评估。Lake健康写入canary也未运行，因此本次目录/磁盘检查不能代替获准执行时的原有写盘门禁。

证据：[P4调度接续审计报告](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p4_scheduling_continuation_audit_20261013.json)。临时审计驱动及输出位于`/private/tmp/moneyflow-p4-scheduling-audit-20261013`，报告记录驱动摘要。临时序列化首次将SDK的浮点`create_timestamp`当成datetime，已阅读当前SDK定义修正并从头重跑；两次均无正式写入。成功审计阶段6.613秒、RSS峰值318.281MiB；资产/run有界元数据读295次，另sensor清单2次、池SELECT6次、只读事务确认2次，合计305次，不含两次只读GraphQL请求。该耗时不代表日更或真实网络性能。

### 64.2 接续窗口：已有历史结束，不等于新增数据已接上

七表bootstrap截止日均为2026-09-30，日更选择起点`MONEYFLOW_SENSOR_START=2026-10-01`。正式SSE日历10月31个日历日期完整且无重复；10月1日至7日没有expected交易日。审计时已完成的交易日为10-08、10-09、10-12；10-13是交易日，但当日分区应等上海22:00后才登记。当前代码的Raw/Silver更新选择在22:00前直接返回`before_window`，先前日期也不会在白天自动补采。注册器可以白天补已结束日期，22:00后优先当日。

| 数据集 | 已登记历史来源日 | 历史物化 / 最近绿检 | 当前应接续三日 | 今晚22:00后集合 | bootstrap保留的整日来源缺口数 |
| --- | ---: | ---: | --- | --- | ---: |
| moneyflow_mkt_dc | 839 | 1678 / 40 | 10-08、10-09、10-12 | 前三日加10-13 | 1 |
| moneyflow_ind_ths | 494 | 988 / 40 | 同上 | 同上 | 4 |
| moneyflow_cnt_ths | 495 | 990 / 40 | 同上 | 同上 | 3 |
| moneyflow_ind_dc | 739 | 1478 / 40 | 同上 | 同上 | 0 |
| moneyflow_dc | 739 | 1478 / 40 | 同上 | 同上 | 1 |
| moneyflow_ths | 431 | 862 / 40 | 同上 | 同上 | 2 |
| moneyflow | 4067 | 8134 / 40 | 同上 | 同上 | 0 |

三日合计21个“数据集×日期”，分别需要21个Raw和21个Silver执行；今晚四日合计28个，分别需要28个Raw和28个Silver执行、56个正式目标文件。这是审计时的待接续数量，不是自动扩日的执行批准。三日及10-13在七表中都没有分区、Raw/Silver文件和物化：Raw readiness为`missing_materialization`，Silver为`raw_not_ready`，符合尚未采集的事实，不属于历史收尾失败。21个sensor没有持久化记录，当前加载定义和有效状态全部STOPPED；尚未首次启用时记录不存在是正常状态，不是丢游标。

当前四日都在最近10个expected日期窗口内，窗口外接续差集为0。按当前正式日历，第11个截止后交易日为10-22：若届时10-08仍未完成，就会滑出热窗口。启用前须重新冻结`(2026-09-30,执行边界]`全部应接续日期减已就绪日期的差集；不能只把sensor打开后假定历史接续已完成，也不能把窗口扩成全历史扫描。超过10日的差集使用明确日期清单的接续执行，不混入Prod bootstrap或历史缺口补录。

### 64.3 已满足的启用前提与本次验证边界

1. 当前正式DG为1.13.26，`orchestrator`代码位置健康。只读GraphQL确认全部21个sensor、14个独立job、14个Raw/Silver资产与14个blocking checks已加载；资产绑定各自动态分区，Silver依赖同日对应Raw，14个资产均声明`moneyflow_tushare_writer`。sensor默认及有效状态均STOPPED、最小间隔600秒；登记sensor不提交job，更新sensor目标各自对应job。最小间隔不是22:00:00的准点承诺，[Dagster sensor文档](https://docs.dagster.io/guides/automate/sensors)与当前实现口径一致。
2. SENSOR、BACKFILL、SCHEDULER、QUEUED_RUN_COORDINATOR、MONITORING、ASSET、FRESHNESS七类daemon健康。当前项目code server、webserver、daemon进程中只核验了`TUSHARE_TOKEN`存在且非空，没有把凭据写入报告、打印、散列或更换token；这不证明本次新日期的接口权限或源站晚间发布时间。
3. 七表7804个历史来源日的原生分区/15608项物化/280个最近检查身份与已验收结果一致。每表最近20来源日分为两组各10日复跑物理hash与关联check readiness，280项全绿。更早历史文件本轮未重扫，沿用未改变的P3及全量收尾证据。当前14个job各自有界查询的运行记录均为空，无本族active run。
4. 正式Lake与staging路径正确、外盘已挂载、同设备、raw/silver/gold与DuckDB临时目录存在；空闲约2.66TiB，高于64GiB既有门槛。共用writer.lock未占用，探测未修改锁内容。
5. 当前源码/测试1182个文件摘要与全量收尾基线一致，75份既有moneyflow JSON报告未变；审计前后正式日历摘要、21个sensor状态、专属池状态一致。审计不改变边界、依赖矩阵、API/CLI、请求参数或合同。

### 64.4 开发前审计发现的三个问题（最新处理结果见§65.4）

**A. 日更注册器仍从历史起点登记。** `moneyflow_update_selection.register_moneyflow_trade_days`传入`min_trade_date=contract.history_start`，而更新选择器只处理10-01以后。正式日历减冻结来源集合确认：mkt_dc缺2026-07-09；ind_ths缺2024-11-04、2025-01-20、2026-07-09、2026-08-05；cnt_ths缺2024-11-04、2025-01-20、2026-07-09；dc缺2023-11-22；ths缺2026-07-06、2026-07-09，共11个数据集日期。启用现行注册器会把这些已有来源缺口登记成没有文件、且日更不会处理的空分区。例如mkt_dc今晚首次登记会选择10-13和07-09，而不是10-13和10-08。

这11项不是本轮新发现的源端不可补结论：其中源端无法取得的部分按既有决定接受，源端可补的部分仍须独立批准。整日缺口与DC05-19的部分缺键也不能混为一类。本轮不能借分区登记把任何历史缺口纳入源采集。

待批准的最小修正：七表共用日更注册器的下界改为既有`MONEYFLOW_SENSOR_START`，保持`contract.history_start`、历史冻结清单及bootstrap校验不变，不改其他家族的通用注册helper。正反例须覆盖全部七表：历史来源缺口不登记、09-30及以前不登记、10-01后已结束交易日补登记、22:00前不登记当日、22:00后当日优先再补一个旧接续日、非交易日不登记、已登记不重复、最多两key/tick及资源/游标有界。

**B. 专属写入池只有代码名称，没有正式容量。** native`concurrency_limits`和`concurrency_slots`没有`moneyflow_tushare_writer`记录，pending为0；实例当前全局`max_concurrent_runs=1`、pool粒度run。因此现有全局队列提供串行保护，但不能宣称专属池容量1已落实。writer.lock还用于排斥手工/bootstrap执行，不能把锁冲突失败代替排队。

配置审计：配置名为native专属pool `moneyflow_tushare_writer`的limit；本次读取为未配置，目标明确为1；持久化在正式Dagster PostgreSQL的concurrency表，由现有native配置入口设置，作用域是已加载的14个Raw/Silver资产，生效于后续运行的队列准入。没有新env、Settings、前端开关、额外限流器或安装。消费者是这14个asset/job及native queued run coordinator；依赖是当前run粒度、已声明pool、全局队列与writer.lock；运营可通过native pool状态和只读SELECT核验容量、claimed及pending。设置后须读回limit=1、有效槽位1且无异常占用，其他池与全局并发配置不变。原方案§8的Raw专属池措辞须校准为14个Raw/Silver共用同一容量1池，以符合唯一物理writer边界；只配置native容量需要另行正式写入批准。

**C. 六表没有执行既定的行数下降门禁。** 本文§2第5条已要求以前5个已通过日期的行数中位数为基线，下降超过20%转人工复核，前5日不足则用已验证09-30基线，DC板块按类比较。当前六表资产→`update_daily_moneyflow_raw`→`collect_daily_moneyflow/build_daily_moneyflow_raw_candidate`→file checks只核验非空、每轮≤20000、分页闭合、两轮行数/字段一致及schema/身份，没有前5日、中位数、09-30或分类下降比较。两个稳定的低行数响应仍可能发布，不能把两轮相等当成该门禁已通过。大盘固定恰好1行，不需要另一个相对数量阈值。

待批准实施沿用已有规则，不新增任意放绿开关：只在Raw run中、正式提升前读取同表目标日期之前最多5个已通过且物理证据一致的日期，用现有事件/readiness与既有连接做有界核验；不把逐日全历史Parquet扫描放进sensor。数量不足5时只用已验证09-30基线，无法验证基线则阻断，不把缺基线当成无异常。DC板块分别比较行业/概念/地域并记录参考日期、行数和关联证明。下降`>20%`保留候选、给出明确非自动重试的人工复核原因，不提升、不发成功交付；刚好20%、增长、NULL金额与合法零值按原规则处理，不裁剪证券、不造数。落码前须进一步审计既有metadata/receipt字段落点与全部消费者，给出≤5日期、event查询、文件hash/SQL/RSS和基线缺失的明确预算。测试至少覆盖稳定但显著少行、刚好20%、增长、分类各自下降、数量不足5的09-30回退、失效/缺失基线阻断、无正式提升及无成功事件。历史bootstrap接受的真实低覆盖不因此重新否决。

### 64.5 后续顺序与阶段验收

结论是**审计完成，尚不具备直接启用条件**。本轮不实施A/C、不设置B，不进入P5正式执行。

1. 下一开发切片先修正A并补齐C，按已写明的范围补正反例及性能预算，复跑受保护门禁；没有request builder/fields/源参数变更。不动bootstrap、七表数据集划分或其他家族sensor。CodeGraph本轮用了explore、search、callers；callers只返回5个注册入口，已直接核验七个当前源码入口/导入定义及实际加载清单，不把不完整索引当成完整影响面。实施前继续核验C的事件、metadata/receipt消费者与测试，并回填原方案和LLD。
2. 开发通过并提交后，重新只读读取当前日历、差集、目标文件、native状态和writer互斥，冻结专属池设置、精确接续日期/Raw-Silver job/目标路径、sensor启用及失败停机清单。正式配置/分区/job/sensor写入按阶段取得批准；本轮审计授权不涵盖这些动作。
3. 按批准清单先设置并读回专属池容量1，再加载已验收代码并检查全部21个sensor仍STOPPED。优先让登记器登记接续窗口，核对只新增C+1以后目标日期，不创建11个历史缺口分区；更新sensor只有窗口所需分区齐全才发run，不能把首次`missing_partition`算作源站故障。
4. 先对moneyflow_mkt_dc做一个已成熟接续日的真实Raw→blocking check→Silver→blocking check→readiness读回，再按清单接续该表全部日期，确认无误后逐表推进其余六表。登记与启用按表推进，更新sensor每tick至多一个run；已active不重复，失败按既有限次/非重试规则处理，文件已落但check未绿时先停下复核。每天22:00后优先当日，旧接续日期仍必须逐项闭合。
5. 七表全部接续差集清零，并核验21个sensor有效RUNNING、目标/游标正确、池/锁无异常、实际job/materialization/check和物理数据闭合后，才能关闭P4调度接入。P5仍按原要求做至少3个不同交易日的真实采集、源/规范化/写入行数及拒绝原因、修订/取消续跑/幂等和源端晚间稳定性验收；成熟日期接续可作为明确验收样本，但不能替代尚未观测到的未来日更或宣称源站最终性。

按09-30实际行数及每页2000的短页结束规则估算，每个七表交易日两轮请求约32次：mkt_dc/ind_ths/cnt_ths各2、ind_dc三类共6、dc8、ths6、moneyflow6。三日约96次、四日约128次，不含重试或未来行数变化，也不是新源实测。Raw每个run仍最多64次/300秒，每轮最多20000行、RSS768MiB；每个Raw两轮至少间隔60秒，三日21个Raw仅稳定等待累计至少21分钟，四日28个至少28分钟。三日Raw活动执行预算之和105分钟、四日140分钟，不包含queue、600秒tick、其他job、Silver/check及失败重试，不能作为整个接续的墙钟上限或ETA。当前ETA暂无法估算，管理员已确认配额充足，不再审计配额。停机或变更日期范围后必须重新冻结，不自动扩容或扩大热窗口。


## 65. P4日更登记起点与数量下降门禁开发（2026-10-13）

### 65.1 已批准目标、硬口径与实现落点

管理员明确要求提交审计后，按§64/方案§69修正七表日更登记起点、补齐六表行数下降门禁并复跑完整门禁，先不启用sensor。审计文档和报告已提交`4a8ce2fa`。本轮只开发并隔离验收，不配置正式pool，不reload、启用或评估正式sensor，不登记分区/events，不执行正式job，不写正式Lake/staging，不安装依赖或变更源请求。

| 硬口径 | 代码落点 | 正反例 / 验收 |
| --- | --- | --- |
| 七表登记只取10-01以后 | moneyflow_update_selection.register_moneyflow_trade_days，复用MONEYFLOW_SENSOR_START | 七表历史缺口、09-30以前不登记；22:00前/后、休市、当日优先、幂等与每tick最多2key |
| 历史起点/bootstrap/其它注册家族保持 | 不改contract.history_start或通用calendar注册helper | 当前七个历史起点及bootstrap源码保留，既有历史回归 |
| 六表Raw提升前必须校验数量 | 新asset_guards/moneyflow_row_count.py，经moneyflow_daily_update调用，六个Raw asset传入context.instance | 实际job稳定少行失败、无Raw提升/成功物化，六个调用方静态及实际验证 |
| 基线必须来自同表、目标日前、已通过且物理一致的日期 | 原生materialized partition聚合元数据选最近最多5个日期，再复用batch_moneyflow_readiness(layers=raw) | 未通过、过期target、损坏文件/计数、未来日期不得冒充基线；候选基线失效直接阻断，不略过错误找更宽松历史 |
| 不足5日只回退已验证09-30 | guard沿用bootstrap截止，目标日必须晚于回退日期；重新验证该日事件/check/文件 | 回退正确、缺失或失效回退阻断；不凭文件存在或注册key放绿 |
| 下降超过20%人工复核 | 原整数计数以current*100 < baseline*80判定；前5个计数取中位数，DC按行业/概念/地域分别比较 | 超过20%失败、等于20%通过、增长通过、分类独立下降，即使总数不降也失败；NULL和合法零金额不删行 |
| 失败保留候选且不自动盲重试 | 现有receipt增加row_count_guard结果，再抛retryable=False的MoneyflowContractError；原asset错误metadata路径复用 | 源两轮稳定仍可被数量门禁拒绝，原目标摘要不变，候选/证明可读回；重放重新核验，不信任旧receipt里的passed |
| 不增加任意开关或新状态实体 | 常量统一放run_contracts/moneyflow.py，结果通过既有receipt和metadata builder | 无新env/DB表/resource/asset/check/job/sensor；保留21个STOPPED定义与现有身份/schema/路径/run key |
| 门禁在Raw run，sensor不深扫基线 | guard复用当前候选DuckDB连接，持有原writer.lock期间执行；Silver与bootstrap不调用 | 每tick旧预算不变；单run扫描最多5个Raw基线文件；取消/恢复/无源重采回归 |

已审计全部生产调用方为六个assets/moneyflow*.py，均由既有context提供instance；没有外部API/CLI调用该内部helper。测试中直接调用入口的六份definitions测试同步迁移必填instance，其他源候选/历史入口保持。六个_result通过既有build_materialization_metadata将result附加字段放入goldenshare命名空间，readiness只消费file/raw hash，event历史证明消费者不要求receipt字段集合完全一致；新增row_count_guard仅为运行诊断，不作为run key或完成身份。中位数/分类计数只对少量汇总整数运算，业务行仍由DuckDB处理。

基线日期聚合使用当前SDK的get_materialized_partitions，仅列本asset的日期键，不加载全历史event payload；其实现为native索引聚合只读查询。日期事实沿用现有20000上限；选择最新五个目标日前已物化日期，全部核验当前blocking check及物理hash，任何一个失效立即阻断，不通过跳过坏基线来寻找更低行数。历史初次接续的最近五日均已完成最近检查；若未来异常记录令基线失效，按既定人工复核处理。通过后SQL核对真实行数与dagster/row_count，DC同时核对scope_row_counts；源数量异常不宣称全市场覆盖率下降，更不按现有证券池补值。

### 65.2 性能预算、常量审计与验证方式（编码前）

| 项目 | 单Raw run成本 / 上界 |
| --- | --- |
| 对象、日期、枚举 | 1表×1目标日；最多5个基线日；DC三类，其余all一类 |
| native读取 | 1次materialized日期聚合（返回最多20000日期事实），1次有界materialization及1次check批读，各limit100；不逐日查询原生事件 |
| 基线文件及业务行 | 最多5个Raw；每文件沿用64KiB或4MiB readiness预算，合计最多20MiB；每文件最多20000行，合计100000行，不进入Python业务row循环 |
| DuckDB/hash | 复用512MB/1线程/no-spill候选连接；每文件schema/身份/计数/分类SQL合计最多4条，最多20条；hash先由readiness验证，SQL后再次确认，最多40MiB摘要读取；无join、临时业务落盘或额外连接 |
| 请求与输出 | 基线0源请求、0业务写入；日更仍64次/300秒、两轮间隔60秒、每轮20000行、RSS768MiB；新增receipt汇总最多5条证据，保持既有64KiB控制文件限制 |
| 提升及失败 | 每目标一个os.replace/checkpoint，不改变原协议；门禁失败前0提升，保留原目标及候选，不自动清理或备份 |
| 时间与空间 | 数量校验计入原Raw300秒总预算，每次native读/SQL前后检查取消、时间和内存；仅汇总receipt新增少量KiB，配额不再审计，无新磁盘/限流配置 |
| 拒绝 | 日期事实>20000、事件饱和且证据不足、文件超预算、基线缺失/失效、计数不一致、数量下降>20%、总时间/RSS超限均停止，不放宽或回退全历史深扫 |
| 验证 | 隔离真实Parquet/native target检查及六表job；最大基线文件/日期事实的边界反例；获准只读实际六表×最近5日量测，不执行正式check/job |

新增常量审计：MONEYFLOW_ROW_COUNT_BASELINE_DAYS默认5、MONEYFLOW_ROW_COUNT_FALLBACK_DATE默认2026-09-30、MONEYFLOW_ROW_COUNT_MAX_DROP_PERCENT默认20；来源与持久化均为run_contracts/moneyflow.py版本化合同，无env/DB/可编辑运营参数，消费者仅新guard和相关测试。下界继续消费已有MONEYFLOW_SENSOR_START，既有20000事实/RSS/时间/文件上限不新增双份配置。生效方式为后续经批准加载代码；运营从receipt/materialization goldenshare/row_count_guard或既有Failure.reason_code观察。测试证明无关闭门禁/任意放绿开关，不调整专属池或全局并发。

完整验收拟包含七表全部moneyflow功能回归和请求策略、catalog governance全部逻辑/子断言、run-contract static全部逻辑/批次、I03-I08及启动/运行环境保护反例、隔离Definitions、改动源码/测试Ruff、全DG致命Ruff、文档和whitespace。治理/隔离继续调用原受保护启动器；新增guard若进入consumer静态源码清单，只更新精确只读文件清单，不扩大目录/正式Lake/数据库/网络权限。实际结果在本节后续记录，不预填通过。

### 65.3 实现、消费者迁移与测试对账

本轮代码落点如下，正式sensor和job尚未执行：

| 批准口径 | 当前实现 | 隔离验收落点 |
| --- | --- | --- |
| 七表日更只登记C+1以后 | moneyflow_update_selection.register_moneyflow_trade_days使用已有MONEYFLOW_SENSOR_START；七个wrapper保持原名、600秒、STOPPED | test_moneyflow_registration_boundary覆盖七表×22点前后，以及历史缺口/09-30/节假日/重放/每tick≤2key/游标≤8192B；七份既有sensor测试同步校准历史登记断言 |
| 前五日中位数，不足用已验证截止日 | 新asset_guards/moneyflow_row_count只聚合native日期键并批读最新五日或09-30的交付；核对check target、文件hash、schema、真实整数行数 | test_moneyflow_row_count的五日非均匀数量/未来排除/回退/坏基线不跳过/缺失与失效原生证明/记录行数不一致/文件及日期事实超预算 |
| 六表提升前拦截数量下降 | 六个Raw资产传context.instance到现有update_daily_moneyflow_raw；guard在原候选、复验及分类计数校验之后、publish_moneyflow_update_file之前执行 | 六表实际隔离Raw job都验证稳定的少行响应失败、0成功mat、0目标提升、候选仍在且retryable=false |
| DC板块逐类比较，下降超过20%复核 | 每类独立比较整数count×100与median×80；不受其他类别增长影响 | 一类下降且总量增长仍失败；刚好20%及增长通过；native分类计数与物理分类不同则阻断 |
| 失败、续跑不覆盖事实 | 在原receipt增写row_count_guard；任何重放重新查native和物理基线，不信任receipt的passed标记 | 现有目标hash保持、伪造旧passed后续跑仍阻断、候选保留、不重复请求；原退出/取消/幂等/修订回归保留 |
| 资源有界，不进入sensor扫描 | 使用同一个候选DuckDB连接和现有writer互斥；native批读、每SQL前后预算检查 | 五文件正例恰好20条SQL、取消在第三条SQL后不再读取；超文件预算拒绝；实际六表30文件只读量测 |

六份definitions测试使用真正的隔离Raw Parquet和绑定准确materialization target的native绿色检查作为09-30基线；基线生成放在单独临时测试目录，不污染用于断言“失败前无IO”的执行staging。测试目标日移为10-08；既有09-30归档样本只在测试内映射trade_date，其他字段、键、数量与金额逐字段验收保留，不能把它写成新的源站实测。bootstrap/cohort/冻结历史清单与正式文件不受影响。

原受保护启动器仅在精确只读源文件清单加入新guard，不扩大目录或正式资源权限。首次在外层沙箱内调用被sandbox_apply拒绝；使用工具许可后在本机运行同一启动器，catalog、static、root-guard、I03—I08及启动器自身反例都通过，未绕过原隔离。既有sensor测试仍期待历史起点登记的断言已按批准的新口径修正；首次完整功能回归为未完成证据，不计为通过，最终从头完整运行。

CodeGraph开发前使用explore/impact审计共享Raw helper、登记器和readiness；impact只列出部分符号，已用当前源码核验六个Raw调用方、六份直接调用测试和七表sensor消费者。改动后执行根目录codegraph sync/status，索引正常；没有更改主体依赖矩阵、跨域边界、DatasetDefinition、API/CLI、来源字段/请求参数、run key或历史身份。

完整功能回归首次单进程收集1742项，大历史样本后的进程累计峰值内存令既有assert_moneyflow_memory_budget连续报memory_budget_exceeded，结果为826通过/557失败/359错误，不能算完整门禁通过。同一history_candidates文件独立进程实际65通过，新增38项也独立通过。为隔离测试之间的进程累计峰值，最终全套按43个测试文件各启动干净进程、最多3进程并行，各用独立临时HOME/basetemp，记录每文件用例数、退出码、独立父进程RUSAGE_CHILDREN峰值、耗时和日志摘要，再对账总1742项。此调整只改变临时测试驱动的批次，不改生产768MiB上限、源预算或测试断言，不以单进程的部分通过替代完整复验。

### 65.4 最终完整复验与本开发片收尾

最终43个资金流向/请求策略测试文件各用干净进程复跑，**1742项全部通过**，包含新增24项数量门禁与14项七表登记边界；总墙钟462.422秒，最高单进程峰值630.203MiB，小于既有768MiB上限。每文件都有退出码、数量、耗时、峰值、原pytest命令及日志摘要；全量前后本族源码/测试摘要一致。没有跳过失败用例，也没有提高生产预算。此前未完成及失败尝试保留，不能计作本轮通过证据。

原受保护门禁通过：catalog 12项逻辑检查（含资产/目录逐条子断言）；run-contract static 113项/15批；root-guard 13逻辑项在5631源码文件的6批审计中通过；I03—I08、I07的15项启动反例，以及启动器6项退出/10项运行环境路径反例通过。各实际测试批次resource gate与denied区保持均核对通过；故意拒绝启动的反例按原启动器的预期阻断结果验收。隔离dg check defs、改动34份Python的默认Ruff、全DG致命Ruff、文档及whitespace通过。CodeGraph根索引sync/status正常。

真正只读的六表基线均为09-23、09-24、09-28、09-29、09-30这五个已交付日期：

| 数据集 | 中位数基线 | 五文件字节数 | 完整单表读取耗时 |
| --- | --- | --- | --- |
| moneyflow_ind_ths | 90 | 40,560 | 0.314秒 |
| moneyflow_cnt_ths | 387 | 121,830 | 0.056秒 |
| moneyflow_ind_dc | 行业496 / 概念504 / 地域31 | 475,383 | 0.071秒 |
| moneyflow_dc | 6,022 | 2,040,975 | 0.052秒 |
| moneyflow_ths | 5,211 | 1,589,918 | 0.074秒 |
| moneyflow | 5,569 | 2,717,066 | 0.130秒 |

总共30个Raw文件、18次helper native读及120条SQL，基线检查没有源请求；完整初次审计1.175秒、峰值233,668,608B。结束后10:19:29再次独立只读复查，总耗时1.559秒、峰值227,000,320B：30份基线的日期/行数/分类/hash/mat身份与初次一致；七表分区及最新Raw/Silver身份保持，合计7804个历史分区；21个sensor有效及默认状态都STOPPED。专属池仍未配置，未对native做容量写入。既有75份验收JSON摘要保持。

本切片**开发与门禁收尾完成，正式调度接续尚未执行**。没有正式分区/event/job/sensor/池或Lake写入，没有源请求、依赖安装或服务reload。七表独立数据集、历史起点/源缺口、字段、API/CLI和主体依赖边界保持。本轮修改尚未提交；上一轮已提交4a8ce2fa，未推送。

完整证据见[本开发片验收报告](../../reports/moneyflow_p4_daily_guard_evidence_20261013.json)。后续先提交本轮，再重新核对实际日期、hot window、分区与物理/原生差集、池和writer互斥，冻结准确正式配置与接续清单；按§64.5的阶段批准推进容量1、代码加载、逐表接续与sensor启用。当前仍不能关闭整个P4或开始宣称P5真实日更验收通过。

最终报告sha256为486782be3790d3be0fd4cc91e77562044b8ab985ca47b3aaedf8cd8fb966c551，169,082B；报告内列清37个本轮文件（34份Python、2文档、1报告）、逐批日志与原权限报告摘要、三项版本化常量及资源预算，便于下一轮限定范围提交。其他工作区修改未纳入本轮。

## 66. P4专属池与成熟接续清单冻结（2026-10-13）

### 66.1 本轮授权、提交与实际差集

上一开发片37文件已提交为`6386dbd4`，未推送。管理员本轮批准的是“刷新七表日更接续窗口，冻结专属池容量1的配置及正式接续执行清单，先不启用sensor”。本轮只读审计、保存清单和更新本文/方案§71；**没有设置池容量、重载代码、登记分区、提交job、评估/启用sensor或调用Tushare**。

12:41:43上海时间的正式SSE日历确认：10-01～10-07、10-10～10-11休市；已成熟接续日为10-08、10-09、10-12。每表都缺这三个日期的注册、Raw和Silver交付，共21个数据集日期。10-13是交易日，但未到22:00，仅列后续候选，**不在本次正式接续范围中**；到22:00再独立刷新/冻结并批准后，才可增加当天七个日期单元。本次Raw/Silver任务最早按既定晚间窗口于今天22:00提交，容量配置/加载/已成熟日期登记的批准顺序另见下文。

| 数据集 | 历史已登记日期 | 本次固定接续日期 | 计划文件 / job / mat / check |
| --- | ---: | --- | ---: |
| moneyflow_mkt_dc | 839 | 10-08、10-09、10-12 | 各6 |
| moneyflow_ind_ths | 494 | 同上 | 各6 |
| moneyflow_cnt_ths | 495 | 同上 | 各6 |
| moneyflow_ind_dc | 739 | 同上 | 各6 |
| moneyflow_dc | 739 | 同上 | 各6 |
| moneyflow_ths | 431 | 同上 | 各6 |
| moneyflow | 4067 | 同上 | 各6 |
| 合计 | 7804 | 21个数据集日期，21个待登记key | 各42 |

七表15,608历史物化身份、最近20来源日280项检查及280份物理交付就绪仍与已验收事实一致。11个历史来源缺口全部排除；不将其登记成日更空分区，不重新bootstrap。21个已加载sensor的默认和有效状态都STOPPED，持久化中没有这21条状态记录属于现行默认停用情形；没有写入cursor或停用状态来“制造”此结论。14个正式资产均声明同一个moneyflow_tushare_writer池，分区名、blocking check和Silver只依赖本表Raw已从当前服务读回。

实例全局max_concurrent_runs仍1、pool粒度run；目标池无limit/slot记录，pending为0。当前唯一已配置的gold_stk_mins_qfq_writer容量1必须保持。七表及全实例均无active run，writer.lock只读互斥探测无占用；正式根与staging同设备、挂载正常，空闲2,927,652,409,344B，高于64GiB既有门槛。只做POSIX可写权限读取，没有写canary，不能把权限读取写成实际写入验收。

### 66.2 两份冻结清单与配置口径

[容量1配置清单](../../reports/moneyflow_p4_writer_pool_capacity1_plan_20261013.json)：sha256=80d8283d7c577e2662459e9637e3f1ef318b935f85a9de997c1062232a13233d，120,521B。配置唯一目标是native pool moneyflow_tushare_writer的显式limit=1；由现有setConcurrencyLimit调用set_concurrency_slots落入正式PG的concurrency_limits/concurrency_slots，不写自定义SQL、不新增env/Settings/表或限流服务。14个Raw/Silver资产共用，作用于后续run粒度队列准入；实例全局配置、其他池和writer互斥不变。运营通过原生pool页面及只读SQL观察。

批准后执行的请求已冻结为`setConcurrencyLimit(concurrencyKey:"moneyflow_tushare_writer",limit:1)`，成功后必须读回显式limit1、一个有效未占用slot、pending0和其他池配置保持。若已经满足该状态，验证后跳过setter；若与冻结前提不同则停下，不清除claims/pending、不删除池、不自动改全局并发。冻结不是配置已应用，当前真实容量仍未设置。

[成熟三日正式接续清单](../../reports/moneyflow_p4_daily_continuation_mature_plan_20261013.json)：sha256=7eef98524390c6f1b64dfe449e55c6a3be33f979fb9beeb043ac178c7631a772，307,900B。清单逐项列出21个日期单元的专属分区名、原Raw/Silver job、资产/check、正式目标路径、标准run key、native请求参数、依赖与读回条件。不是数据回填入口，不借runless event把文件登记成成功；使用原有完整job及blocking check，不选单独op或check绕过数据采集。

Raw身份使用现有build_repair_attempt_run_key，固定目标日、观察日2026-10-13和attempt1；现有最多六尝试规则不改变，本清单不授权额外尝试。Silver key依赖尚未生成的Raw SHA，冻结的是既有builder的严格绑定方式：只从本日当前已绿Raw的native metadata读取SHA，重新核对文件和check target，绑定后保存实际请求再提交。不得传占位符、人工改hash或另造完成身份。原生分区tag由现有PartitionedConfig生成，不新增项目自定义tag。

重要限制：当前GraphQL launchRun没有run_id输入，也不会因同run_key自行去重。本清单要求独占运营执行、21个sensor保持STOPPED、提交前查询标准身份，每个动作只发一次POST；超时、错误或身份歧义必须先停下读回，不盲重发。active等待、成功且当前物理/native交付完整则跳过；失败/取消/不完整交付转人工处理。Native事实和原run-scoped候选/checkpoint负责续跑，临时进度文件不能充当成功依据，不删除已完成事实。

### 66.3 顺序、加载阻断与有效期

1. 获准后先设置/读回容量1；另行批准当前code location加载，确认实际使用已验收的moneyflow代码且全部21sensor继续STOPPED。
2. 按获准的范围用native addDynamicPartition只登记清单中的成熟key；保持sensor不启用、不评估。若只批准首样本，只操作moneyflow_mkt_dc的10-08一个key与对应两个job；全范围登记21key不能借首样本批准执行。
3. 先执行moneyflow_mkt_dc 10-08的Raw→准确绑定的blocking check→Silver→准确绑定的blocking check，读回schema/日期/键/字段/数量/源证明/file hash/Raw关联及两层readiness。**到此停止，取得独立样本验收**；清单中stop_after_first_market_sample不是可关闭开关。
4. 后续获准后完成大盘另外两日，再按行业THS、概念THS、板块DC、个股DC、个股THS、普通moneyflow顺序逐表逐日推进。每次一个job、每个日期Raw通过后才可提交Silver；每表读回差集清零才能进入下一表。
5. 最终核对本范围新增21key、42目标文件、42mat和42准确绑定的绿色blocking check，以及历史身份保持。21sensor继续STOPPED；长期日更启用和P5真实日更验收仍是后续阶段。

**代码加载目前有额外阻断。** 冻结期间同工作区另一项周线开发新增了jobs/stock_weekly_event_backfill.py和ops/stock_weekly_bootstrap_checks.py，并修改共享configs及周线bootstrap模块；后续引用审计确认已有实际job/ops消费者，不能再当作“只有无运行影响的历史helper”。七表moneyflow代码仍与6386dbd4的1742项验收摘要一致，但shared code-location reload会一并加载这些在建定义。因此冻结清单显式标记source_reload_blocked，当前不能直接加载/提交正式接续job。保留他人修改，等待其收尾及加载范围确认；不通过临时分支/worktree或覆盖文件绕过。工作区稳定后须重新核对完整来源摘要、当前窗口/原生差集、准确加载范围，再冻结可执行版本；本轮不批准这项周线开发或其正式执行。

本次观察日与Raw身份固定为10-13，有效期至10-14 00:00上海时间。跨日、源码/日历/配置/目标范围漂移、已有active/锁占用、身份无法确认、文件或check不一致均停止后续动作并重新冻结剩余差集；已在运行的job继续读回其真实终态，保留已提交事实。10-22为截止后第11个交易日，10-08会退出现行十日热窗口；不能通过本清单自动扩大sensor窗口或让过期计划继续运行。

### 66.4 成本与本轮验证

只读审计实测6.669秒、峰值338.656MiB，记录314个有界资产/run/helper读，加上sensor/池等辅助读取及3个只读GraphQL请求；400次helper/300秒/768MiB预算未触发。最近检查按十日分批，事件查询各limit100；基线六表各5日真实Raw核验，120条SQL，0源请求。预算不将SQL内部次数冒充一次外部数据采集。

以09-30已观测分页量估算，成熟三日约96次Tushare请求，预计42文件/42job；这是估算，不是新源实测或数量保证。每Raw仍最多64请求/300秒、每轮20000行/RSS768MiB，最多5个基线文件、20条额外SQL；21个Raw的请求硬上限之和1344，活动预算之和105分钟，稳定等待累计下限21分钟。队列、初始化、Silver/check和源异常另计，整段墙钟ETA暂无法估算。清单将native job观察限定每10秒一次、最多120次/20分钟；超观察预算停止后续提交，不能把仍在运行的job标成成功。管理员已确认配额充足，不再审计账户额度。

现有CLI的pool set、job launch、dg launch只执行--help，未连接正式instance执行。65份pool/reload/注册/job请求在当前安装的GraphQL schema中完成纯语法和输入类型校验；它不执行resolver、不构造正式instance，也不等同真实job成功或GraphQL写权限通过。此前Silver空交付应为raw_not_ready的判断已按当前readiness语义校准，未通过的组合草稿只保留在/private/tmp，完整校验后才发布最终三份冻结文件。Frozen全套仍apply_authorized=false。

完整证据见[冻结与只读验收报告](../../reports/moneyflow_p4_continuation_freeze_evidence_20261013.json)，sha256=11396eb1cb8abcd47bc5ba7abaf307ae77cbc3922a8869c1779f2af397fbb318，254,786B。本轮只新增三JSON和修改两原文档，不改变API/CLI、主体依赖矩阵、数据集或sensor行为；CodeGraph explore覆盖登记器七个调用方、数量门禁与标准request/run-key builder，未索引完整的新周线定义部分已直接核验当前源码引用。P4/P5仍未关闭。


## 67. 共享工作区与加载阻断复核（2026-10-13）

管理员本轮要求先提交，再检查共享工作区是否稳定和加载阻断是否解除，仅在具备条件后刷新七表接续窗口、重新冻结可执行清单，保持sensor停用。上一轮3报告/2文档限定提交已完成：`a5e18e44af7927378dfe34b6c2e578f742f68cf5`，未推送，其他修改保留。本轮只新增复核报告并更新两份原设计文档，不改正式代码、配置、API/CLI或依赖矩阵。

13:31:29上海时间，746项源码/项目配置摘要与上一轮冻结完全相同，七表1742项验收对应的129项源码摘要没有漂移；本次审计前后源码和待加载清单也一致。**这只能证明短时间内没有改动，不能证明共享开发已验收收尾。** 5份tracked周线bootstrap/共享configs仍有未提交修改，jobs/stock_weekly_event_backfill.py和ops/stock_weekly_bootstrap_checks.py仍为untracked。当前definitions.py依旧通过load_from_defs_folder加载同一defs目录；新job导入新op，新op消费StockWeeklyBootstrapEventChecksConfig及周线bootstrap，周线/月线CLI也引用已改模块。因此上一轮加载阻断仍成立，不把“文件hash暂时没变”当作可以重载的依据，也不覆盖他人文件或切换临时工作区规避。

正式服务两次只读读回一致：21个moneyflow sensor默认/有效均STOPPED，14个job仍在，新增周线raw_stk_period_bar_adj_week_event_backfill_job尚未加载。原生PG连接确认transaction_read_only=on；moneyflow_tushare_writer仍没有limit或slot、pending0，其他gold_stk_mins_qfq_writer显式容量1保持，全实例active runs为空。没有进行重载来验证未验收的周线代码，没有正式pool/分区/event/Lake写入、job提交、sensor评估/启用、Tushare请求或依赖安装。

本轮条件检查不通过，**不进入日期窗口刷新及新可执行清单冻结**。原三份冻结文件SHA保持，仅作为12:41观察的历史目标/请求证据；不能将其旧日期、观察日run key或有效期自动延期。待共享周线改动收尾、明确加载范围后，重新核验完整源码摘要、日历/成熟窗口、原生/文件差集、pool/active/writer维护条件，再冻结剩余范围；容量配置、正式加载和首样本仍按阶段执行，不启用sensor。

完整证据见[共享工作区与加载阻断复核报告](../../reports/moneyflow_p4_shared_workspace_recheck_20261013_133129.json)，sha256=934a1d0500c05d27037b3aa4b98f488a2bc288ba1a799d2ecfdc2275c7283994，124,975B。成功只读阶段实测0.542秒/RSS177MiB，2个只读GraphQL、4条SQL、1次有界active run读取；此前临时查询缺少闭合括号返回HTTP400，已定位并经本地schema校验后修正，合计3个只读请求，未执行任何mutation。CodeGraph explore用于共享job/op/config/加载入口分析，泛名索引未完整覆盖新周线符号，缺项以当前源码和import引用核验补足。阻断明确保留，不以文档或GraphQL静态校验替代正式加载验收。P4整体与P5仍开放。


### 67.1 共享开发提交后的复验与可执行清单重新冻结

本轮结束检查发现另一周线任务已提交`5a25e578cb4f45998fe58a8a5666da982b42f4da`，此前7项源码全部纳入该提交，orchestrator/src没有未提交文件；前节13:31的阻断记录保留为当时事实，已由本节后续复核取代。周线提交对应当前job/op/config源码及正式补录结果见周线原LLD A21，记录193项专项验收、真实样本及全量读回；本任务没有重新执行周线job或改变其自动化状态。共享根分支仍dev-interface，其他Web/研究修改不进入此code location的加载范围。

重新核验当前definitions.py及新增周线job→op→config/bootstrap引用：defs按原load_from_defs_folder加载，新周线入口是手动job，不新增自动触发器。使用现有项目环境、隔离/private/tmp DAGSTER_HOME和无正式凭据的环境运行`dg check defs --use-active-venv --no-check-yaml`，exit0/All definitions loaded successfully，日志sha256=bd69366b36ad5660d01287093fbb54f56a4260e8584ae7213c233675486feb1a。本次实际加载解析包含新周线定义；不将其他任务文档或源码“已提交”单独当作加载验收。CodeGraph根索引已sync/status正常。七表1742项原验收对应129项源码/测试摘要仍完全相同，没有重跑已有功能测试或安装依赖。

13:34:46上海时间正式只读刷新：七表都缺10-08、10-09、10-12的登记/Raw/Silver交付，共21key、42目标文件/原job/物化/准确绑定blocking check；10-13未到22点仍只列候选，排除当前执行范围。四日均在现有10日热窗口内；不扩大窗口或把11项来源缺口接入日更。7804历史key/15608物化身份和最近280check/物理就绪保持。21个已加载sensor默认/有效STOPPED、14资产/job/check合同仍准确，当前服务尚未重载新源码。全实例active0，writer锁未占用；目标池未配置/pending0，其他gold_stk_mins_qfq_writer显式容量1及全局run上限1/run粒度保持。正式根/staging同设备且空间门槛满足，没有写canary。

新清单以当前已提交源码5a25e578及746项源码/项目配置摘要冻结，dependencies_dirty_at_freeze为空、source_reload_blocked=false、workspace_loading_condition_cleared=true；**原共享源码加载阻断已解除，可执行范围和请求已重新冻结，但尚未应用配置或启动任务。** 原三份目标清单和前节阻断报告均保持原SHA，不覆盖或延期它们。

| 新冻结文件 | SHA256 | 字节 |
| --- | --- | ---: |
| [专属池容量1配置](../../reports/moneyflow_p4_writer_pool_capacity1_refrozen_plan_20261013.json) | bf14ac492260460c072224904562ec45b58323561c53d510403552a70cc316e1 | 119,956 |
| [成熟三日正式接续](../../reports/moneyflow_p4_daily_continuation_mature_refrozen_plan_20261013.json) | 644066a66d5665b8e5f317371032b7eccb46eadce2732d845fa0280dc84af56b | 307,347 |
| [重新冻结与只读证据](../../reports/moneyflow_p4_continuation_refreeze_evidence_20261013.json) | 1d72e8be8d48e72a7faf61e80d834c3cc88676c0394bb0288dc3ce9ae9a7f948 | 254,982 |

顺序和恢复沿用§66/方案§71的已确认规则：按阶段批准设置容量1并读回、加载这一准确源码并确认七表21sensor仍STOPPED及手动周线入口正确；只登记获准的成熟key，先moneyflow_mkt_dc 10-08一个key/Raw→check→Silver→check首样本后停止独立验收，再批准剩余范围。原完整job、不选op/check、标准Raw身份、Silver只绑定当前已绿Raw SHA、GraphQL每动作单次提交及超时先读回、native差集续跑和既有预算保持。不能把清单标记可执行理解为本轮已批准正式写入；apply_authorized仍false，ready_for_formal_launch_now仍false，仅剩容量/加载/晚间窗口/首样本等既定阶段门禁。21个sensor全程保持STOPPED。

清单观察日10-13，正式Raw/Silver最早22:00；有效期仍10-14 00:00上海时间。到22点并不会自动把10-13加入本次范围，若纳入须重新刷新/冻结并批准；跨日或源码/日历/配置/目标差集漂移停止下一动作，保持已完成事实。本轮没有reload、pool配置、分区/event/Lake写入、job或sensor评估/启用、Tushare请求或安装。

本次完整只读刷新7.743秒/RSS352.656MiB、314个有界helper/asset/run读和3个只读GraphQL；原400读/300秒/768MiB门槛内，六表30基线文件共120SQL通过，81份既有moneyflow报告摘要保持。65份pool/reload/登记/job请求在安装版本GraphQL schema中纯语法/输入类型校验通过，没有resolver执行。成熟三日估算96源请求，Raw硬上限合计1344、活动预算合计105分钟、稳定等待下限21分钟，总墙钟ETA仍暂无法估算；不审计配额、不增加预算。P4整体与P5仍未关闭。

## 68. 专属池、冻结源码加载与大盘首样本执行（2026-10-13）

管理员本轮已明确批准按§67.1新冻结清单设置并读回容量1、加载冻结源码，以及moneyflow_mkt_dc首样本执行与验收，保持sensor停用。上一轮6文件已提交5424ccd0，未推送；冻结文件保持原SHA和apply_authorized=false，其静态标记不取代本轮明确批准。本次精确范围仅原生容量setter一次、共享code location加载一次、10-08大盘一个key及Raw/Silver两个完整job；不操作剩余20key/40job，不启用或评估21sensor。

正式执行工作目录为/Users/congming/github/goldenshare/lake_console/orchestrator，DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home，入口为原http://127.0.0.1:3000/graphql。临时driver位于/private/tmp/moneyflow-p4-market-sample-20261013；不安装、改正式Python或yaml，日志不输出凭据。

| 步骤 | 完整执行命令/请求 | 读写与验收 |
| --- | --- | --- |
| 前置只读 | python3 /private/tmp/moneyflow-p4-market-sample-20261013/run_audit.py | 原314次有界读模型，核验历史、21sensor、pool/active/锁/文件/日历及129验收源码摘要，不写正式事实 |
| 容量设置 | python3 /private/tmp/moneyflow-p4-market-sample-20261013/run_control.py pool | 子进程固定项目.venv/bin/python3 -B、上述工作目录/HOME，POST清单原setConcurrencyLimit(concurrencyKey=moneyflow_tushare_writer,limit=1)，原生limit/slot写；只读读回显式1/一个未占slot/pending0，其他池和全局配置保持 |
| 冻结代码加载 | python3 /private/tmp/moneyflow-p4-market-sample-20261013/run_control.py reload | POST清单原reloadRepositoryLocation(repositoryLocationName=orchestrator)，更新code location，不启停服务/sensor；读回loaded状态/serverId/版本/新增手动周线job及14资产合同、全部21sensor STOPPED |
| 首样本 | 原清单units[0]的registration及Raw请求，Silver只绑定该日当前已绿Raw SHA | 单key/2job/2文件/2物化/2准确绑定blocking check，最终两层物理与native就绪；到此停止，不进入余表 |

每次mutation前检查完整746项冻结源码/项目配置摘要、code location所属工作区、日历、正式concurrency配置、无active及writer锁；写请求先在/private/tmp原子保存request和sent_or_about_to_send状态，只发一次。HTTP异常/超时或失败后保留已成功容量、实例与文件事实，先读回，不再次发送不明请求，不删除pool/claims/pending、分区、事件或文件。reload不得越过尚未提交的共享源码。原生事实为续跑依据，临时状态只用于避免无依据重复提交。

本轮13:44:19正式预检7.688秒/RSS328.297MiB、314次有界读通过，成熟日期仍三日、全active0、pool未设置、21sensor STOPPED、历史/日历/旧报告/129项源码保持。临时driver的runtime/资产GraphQL查询已在当前安装schema静态校验。依据沿用原批准设计、[官方并发文档](https://docs.dagster.io/guides/operate/managing-concurrency)、[官方asset check文档](https://docs.dagster.io/guides/test/asset-checks)及本地1.13.26 mutation实现，正式结果待读回记录。

注意§67.1冻结的source_job_not_before仍为10-13 22:00，现在尚未到窗口；本轮先执行获准的容量与加载，Raw/Silver不得自行提前。到窗口时再次按当前文件/native身份核验，若跨日/漂移/冲突按原清单停止并重冻；不把10-13加入首样本，不新增调度器、后台等待服务或自动启用sensor。

### 68.1 已执行准备与单次历史首样本时点提案

容量原生setter及读回完成：moneyflow_tushare_writer显式limit1、一个未占用slot、pending0，其他pool和全局配置保持。已批准的冻结源码reload完成，serverId变更，新手动周线job在加载范围，14资产/分区/检查/Raw依赖合同准确，21sensor仍STOPPED，无job提交。具体响应和读回证据保留/private/tmp/moneyflow-p4-market-sample-20261013的pool_evidence.json/reload_evidence.json，最终报告随后汇总。

**待确认的仅是这一处时点例外：** 当前本次手动目标10-08早已成熟，原asset/writer没有22点限制；22点限制来自自动sensor和本次清单的统一source_job_not_before。建议本轮只允许units[0]的10-08大盘一个key/两个完整job于容量和加载验收后立即执行。其余20日期单元、当日10-13候选、自动登记/日更22:00、全部STOPPED sensor、标准run key、60秒两轮稳定、原请求/预算和首样本后停止均保持。原清单文件不覆盖；仅在管理员明确批准此提案后，保存单次首样本时点批准附录、当前精确请求及同一source/plan摘要再执行。没有确认时继续遵守原22:00时点，不能把“批准按原清单”推定为提前执行授权。

### 68.2 已批准现在处理10月8日的大盘数据

管理员随后明确答复“现在执行”。本次只提前执行10-08的大盘手动验证：登记一个日期，运行原始数据下载及检查任务，再运行整理文件及检查任务。每天自动更新仍保持22:00，当前21个自动触发器全部关闭；其他日期和六表不执行。原清单文件保持，单次批准记录在/private/tmp/moneyflow-p4-market-sample-20261013/sample_timing_authorization.json，绑定原清单SHA、一个key和两个job，不作为任意提前运行的开关。

在前述正式工作目录与DAGSTER_HOME执行命令依次为`python3 /private/tmp/moneyflow-p4-market-sample-20261013/run_sample.py register`、`raw`、`silver`、`accept`；这些参数只代表本次三项操作和读回，不扩展日期或数据集。Raw/Silver仍使用原清单完整任务请求，Silver绑定刚验证通过的同日Raw文件SHA；各步骤先核对当前源码、已加载版本、池/active/锁和21个停用状态，再保存请求，只提交一次。每10秒最多120次观察运行，失败或超时停止下一任务，不盲重发。读回复用原文件/整理检查规则，核对15字段、日期/行数、两轮源证明及文件hash、真实任务/物化/检查关联；完成这一天后停止。正式结果随后记录。


### 68.3 已完成的设置和代码加载，以及当前停下的原因

管理员本轮批准设置、加载和处理10-08大盘数据，随后明确答复“现在执行”。上一轮4报告/2文档已提交5424ccd0，未推送；本次时间许可已记录，后续无需再问是否允许现在处理这一天。

13:47:34完成后台“一次只运行一个资金流任务”的设置，原生moneyflow_tushare_writer显式limit1、一个未占用slot、pending0读回正确；其他gold_stk_mins_qfq_writer容量1和全局设置保持。13:47:54完成DG代码加载，serverId实际变更、手动周线任务已加载、14资金流资产的任务/分区/检查/依赖准确、21个自动触发器都保持STOPPED。前后新只读进程确认7804历史日期、15608物化记录、最近280检查和280份文件就绪保持，84份既有报告SHA保持。

准备登记10-08日期时，其他开发又修改了共用的checks/adj_factor_checks.py，并新增bootstrap/stock_adj_factor_history_repair.py及stock_adj_factor_history_repair_candidates.py；对应测试也仍未提交。修改包含正式复权因子检查函数，不是单纯文档。当前工作区代码已经与本次批准的完整摘要不同；虽然129项资金流源码/测试摘要没变，也不能绕过整个DG加载和运行的代码一致性要求。依据根AGENTS第29项保持当前工作区，不使用别的分支/worktree、不覆盖或移走其他人的改动。

登记driver在任何写请求前停下；紧接着的Raw driver也被同一检查拒绝，在发送请求前停止。13:59:43独立只读确认大盘仍839日期，10-08未登记，两层目标文件都不存在、物化0、两个资金流任务运行记录0。没有请求Tushare、写文件或补造成功记录；两个临时driver退出不能说成正式任务运行失败。一次只运行一个任务的设置和已经完成的代码加载保留，全部自动更新仍关闭。Silver没有提交，这一天尚未验收完成。

本轮新增[设置、代码加载与大盘执行结果报告](../../reports/moneyflow_p4_pool_reload_market_sample_evidence_20261013.json)，sha256=18e566ea5e769f19e110d73fd0c159aae7e1a1ca2a009e35e5b8749f2d8719bc，469,325B，并更新两份原设计文档，尚未提交。报告保留准确请求/原生响应、加载前后serverId/资产、两次历史审计、最后独立读回和“现在执行”的批准；正式变更只有一次容量setter和一次代码加载，日期/任务/数据写入都是0。文档及报告不改变代码、API/CLI或依赖边界。

下一步先等复权因子开发收尾，再核对完整代码和加载范围、更新本次允许运行的版本及实际日期/文件差集，然后只完成10-08大盘下载和整理验收。当前不能继续使用已漂移的代码，也不自动扩大到余下20日期单元；整个P4和P5仍未完成。


### 68.4 再次检查另一项开发是否完成（2026-10-13 14:11）

管理员要求先提交，再检查代码是否稳定；具备条件才继续10-08大盘下载、整理和检查，自动更新保持关闭。上次3文件已限定提交cdfed8af，未推送，其他修改保留。

直接读取“周线月线dg集成”当前任务，仍为active/inProgress；该任务正在处理25股历史复权因子及下游修复，目前还在明确旧数据问题的检查范围。当前Git代码也证实未完成：adj_factor_checks.py仍未提交（91行新增/116行删除），两份历史修复工具及测试未提交；检查期间又出现stk_mins_qfq_macd_kdj.py的修改。完整代码与上次批准版本有4项文件差异，129项资金流源码/测试本身保持，不能据此忽略共用代码尚未完成。

14:11:10新只读进程确认一次只跑一个任务的设置保持（显式limit1、一个未占slot、pending0），全active0；21个资金流自动触发器默认及有效均STOPPED。大盘仍839个已登记日期，10-08尚未登记、两层文件都不存在、物化0、两项任务均无运行记录。旧84份报告与上一轮执行报告SHA保持，本轮没有新增日期、提交任务、请求Tushare、写Lake、重载代码、配置池或安装依赖，也没有去修改另一项开发。

本轮条件不满足，按根AGENTS第29项和原方案的代码一致性要求停止，不换工作区或越过检查。时间许可已获得，不需要再次问是否能立即处理历史数据；下一步等共用代码开发完成、核对实际版本及加载范围后，再只处理10-08大盘。当前这一天仍未验收，P4整体/P5未完成。

证据见[开发完成情况与大盘状态检查](../../reports/moneyflow_p4_market_sample_development_recheck_20261013_141110.json)，sha256=fe5bc83545d02b43baf6996b68490126a404d86ccecbe6b18b54442e2bf9e1eb，113,612B。本轮只新增此报告及更新两份原文档，尚未提交；不改代码、API/CLI、依赖边界或正式数据。


## 69. 按10月17日审计恢复后台并完成首日样本

管理员已批准按审计建议的下一步执行。本轮只恢复DG后台、更新已过期的执行清单和临时检查脚本，然后完成已批准的moneyflow_mkt_dc / 2026-10-08一个日期。七表独立、历史事实、正式字段、资产/check/job、每日22:00和21个自动触发器STOPPED均保持；其余48个数据集日期不执行。§68的“现在执行”许可保留，不再把手动历史样本限制到22点。

### 69.1 恢复方式和影响

10-17审计确认7个后台心跳停在03:39，虽然进程仍在，队列不能正常领取任务。安装版本的dagster/_cli/dev.py表明父进程统一管理webserver和daemon，单独杀子进程会使父进程关闭整个服务。因此使用现有启动入口整体恢复DG，不改依赖、配置或安装包。本机PG、CH和Prod CH隧道的现有只读探测均通过，全部复用。

执行命令：在`/Users/congming/github/goldenshare/lake_console/orchestrator`运行`.venv/bin/python3 -B /private/tmp/moneyflow-p4-resume-20261017/run_recover.py`。脚本先读回无活动任务、资金流并发1及21个开关关闭，再向核对过身份的旧DG父进程45785发送SIGINT；等待它按安装版本原有退出流程关闭子进程，全部退出后仅调用一次`/Users/congming/github/goldenshare/lake_console/bin/lake-dg-start`。正式DAGSTER_HOME为`/Users/congming/.goldenshare/dagster_home`，endpoint为`http://127.0.0.1:3000/graphql`。不初始化/升级数据库，不手工删除锁，不强行启动第二份DG。

恢复会让原有89个已开启的其他sensor继续原本工作，保留它们现有状态；资金流21个sensor仍关闭。DG页面会短暂断开；没有活动任务才允许停止。若旧进程不退出或新后台未恢复心跳，则保留日志并停止，不盲目重复启动、不切换工作区。后台连续两次有新心跳且七表状态正确后才能提交样本。

### 69.2 更新清单与检查边界

10-17已成熟日期为10-08、09、12、13、14、15、16，七表共49个数据集日期、98个完整任务；这只是待办范围，本轮执行仅首个日期的两个任务。旧10-13清单不覆盖、不延期，生成包含当前日历、源码摘要、实际缺口、运行身份和有效期限的新清单。

临时执行脚本不再以“orchestrator任意未提交文件”一刀切阻断。改为记录本轮当前源码并在每次动作前后逐文件核对，明确84份已验收生产代码保持、共享字段/路径/SQL及14个catalog条目语义保持、当前Definitions隔离加载通过，正式加载的14资产/分区/check/上下游依赖正确。其他历史修复工具的稳定修改经引用审计不进入资金流执行链；新发生的源码漂移、配置/日历变化、加载失败、活动任务或writer冲突仍停止。检查脚本自身用临时文件覆盖允许的稳定无关改动及拒绝相关代码漂移、过期清单等反例，不访问正式资源。

### 69.3 首样本硬边界和预算

只登记10-08一个key，依次提交原有完整Raw job和Silver job，不选子步骤、不补造事件、不改sensor cursor。Raw标准身份使用当前观察日期及attempt1，Silver身份只绑定读回通过的同日Raw SHA。每个mutation先持久化请求再发送一次，结果不明时先查原生记录，不重发。两次任务独立等待成功、检查准确绑定本次物化，再做15列/日期/一行/两层转换及来源凭证读回后停止。

预算沿用已验收实现：一个对象/日期、2个正式文件、每层1行15列；通常2次Tushare请求，两轮至少相隔60秒，Raw至多64请求/300秒/768MiB；每任务观察上限20分钟。DuckDB以单日小文件及512MB/1线程/no-spill验收，无全量扫描、join或行循环；正式逐文件候选校验和同盘原子提升不变，失败保留已完成文件和请求/原生运行事实。重跑只读回已有身份，不覆盖不明文件。新清单、实际命令、恢复结果和样本结果见§69.4～69.5，不把准备完成当作样本已成功。


### 69.4 本轮执行前读回

原入口已恢复DG，7项后台心跳连续更新，21个资金流自动触发器保持关闭。恢复后的其他原有调度正常补跑，未改它们开关或优先级；提交样本前再次确认无活动或排队任务。完整历史身份7804日期/15608物化、最近280项文件就绪及检查保持。当前84份已验收生产源码未变；当前全部723份生产Python文件及pyproject/uv.lock共725项登记摘要，隔离Definitions加载通过。当前保护测试启动器相对旧回归版本已有其他专项变动，旧1742项只作为当时验收，未声称本轮重跑；本轮临时检查8项独立反例/正例通过，不访问正式资源。

[当前七表接续清单](../../reports/moneyflow_p4_continuation_current_plan_20261017.json)sha256=23c97f499500b33365c8daa33e07572c74af17147bc0dfe3f71eb45c1be4522d，共49日期单元/98任务，147份请求通过安装版本GraphQL输入校验。全范围估算224次源请求，仅供后续计划；本轮唯一获准项是10-08大盘、一个key/两个完整job，旧容量设置不重复、服务启动已经加载当前代码，不再重载一次。清单到10-18零点失效；原10-13文件保持原内容。

执行命令在orchestrator目录依次为`.venv/bin/python3 -B /private/tmp/moneyflow-p4-resume-20261017/run_sample.py register`、同入口参数`raw`、`silver`、`accept`。每步通过当前源码/日历/配置、加载身份、后台健康、无活动任务及21个开关关闭检查后，才发送该步请求。只用正式完整job写两份候选并校验提升，读回它们实际生成的事件/检查；不得直接制造成功记录。请求和返回在发送前后分别落盘，出现失败/未知结果就停止下一步并查原生事实。


### 69.5 首日正式样本完成及收尾

10-17按本轮范围完成，仅新增moneyflow_mkt_dc / 10-08一个日期的登记。Raw完整任务`7f9ea4b6-171b-4177-b545-0d245b768e38`及Silver完整任务`06491beb-e782-4898-85f9-1b110f8cbfb0`均SUCCESS。原生Raw物化7627129、检查1633880；Silver物化7627157、检查1633881，检查均SUCCEEDED/passed/blocking，目标storage_id、run_id及timestamp准确对应本次物化。没有手工补造事件、单选步骤或自动重发。

来源实际为Tushare两次请求、零重试，两轮间隔60.167秒，采集60.436秒。Raw/Silver各1行15列；Raw日期VARCHAR `20261008`转成Silver DATE `2026-10-08`，其余14列类型和值逐项一致。正式Raw 2612B，SHA256=303338656986d7a84cb07d1baca2b544b9877915df3089156f9f18e46e10ce0b；Silver 2588B，SHA256=d5e1f303bfe1e232f9e43e4c6274d161ddcd520c9ad1d4472c0a4ec07a2b790a。两个文件均通过原有候选校验及逐文件提升，Silver身份准确绑定该Raw摘要。实际源端1行、归一化1行、Raw写入1行、Silver写入1行、拒绝0；两层查询各1行。

后续独立只读对账7.092秒/RSS330.938MiB、314次有界读取：原7804历史日期及15608物化身份未变，最近280项历史检查和物理交付保持；本轮只新增一个日期和两次成功任务，资金流当前登记总数7805。其余48个数据集日期仍未登记/生成文件/产生物化，没有暗中继续执行。725项当前生产源码及项目配置在首尾一致，113个已加载sensor开关全部保持，其中资金流21个仍STOPPED，其他原已开启的89个不变；后台7项心跳持续正常。原容量1只读核对，未再次设置，也没有额外重载。

当前工作区只增加两份报告并更新原方案与LLD，临时执行脚本位于/private/tmp；没有修改正式Python、配置、API/CLI、依赖矩阵或安装包，没有提交/推送。本轮隔离Definitions加载、临时脚本8项测试、147份请求输入校验、正式单日样本及最终原生/物理对账分别形成证据；不把既有1742项测试冒充本轮复跑，也不把成熟历史日样本等同未来当天22点的源最终性验证。

[恢复与正式样本验收报告](../../reports/moneyflow_p4_environment_recovery_market_sample_evidence_20261017.json)，SHA256=62ca1015abf602ec9debe5cd8c4071791f8459b13faefabc166861dc246a6ac2，496002B。报告保留当前计划摘要、三次准确mutation请求/原生返回、两层来源/文件/检查证据以及首尾七表只读事实。DG最初停止工作的触发原因仍未确认，本轮确认的是原入口恢复和后续持续正常工作，不声称已修复底层软件缺陷。

本轮按首样本验收边界停止。下一阶段是大盘剩余6天及其他六表各7天，共48个数据集日期/96个完整任务，沿原七表顺序推进；执行前须按当时实际缺口和日期更新清单，不能跨日沿用本清单。之后仍有自动更新启用及P5真实日更验收，须遵守原有阶段边界，本轮未开启。


<a id="moneyflow-continuation-lld"></a>

## 70. 七表按日期接续执行工具：开发前设计

### 70.1 本步目标、现状与明确边界

本节落实上一轮方案审计发现的8项缺口，作为开发依据；方案总览见[实施方案§75](dagster-moneyflow-tushare-onboarding-plan-v1.md#moneyflow-continuation-design)。本节开工设计及§70.13保留当时记录；用户随后批准提交、开发并修正复验，**本步开发验收及10-09正式单日验证已完成，当前结果见§70.19；§70.14、§70.16保留此前失败与准备记录。** §69是已完成的大盘单日操作记录，不能把其中的临时脚本当作七表工具实现。

本步只增加一个运营命令行工具：对明确清单里的“数据集＋日期”，调用原有完整Raw/Silver任务，读取它们真实生成的文件、物化和检查，支持工具退出后的继续观察和跳过已验收日期。它不自己采集业务数据、生成Parquet、补发物化或检查，也不接入新的调度链。

范围固定为七个独立Tushare数据集。以10-17 14:18验收为基准，剩余48个日期单元/96个完整任务：大盘10-09、12～16共6天，另外六表10-08、09、12～16各7天。大盘10-08已经成功，只保留其证明，不再下载。真正执行前按当时事实更新差集；48是已知待办数，不是以后永远不变的日历。

以下边界不变：原七表资产/job/check/partition/sensor名称、字段类型/单位/NULL/证券范围、Tushare请求与分页、行数下降规则、正式Lake和staging路径；日更仍22:00，21个资金流sensor全程STOPPED。11项历史整日来源缺口及此前部分缺键/已有值差异不进入本工具；不读Prod、不使用biying、不改Ops/Web/ClickHouse、不安装依赖、不设置容量或重载/重启DG、不修改其他家族的开关。不新增资产、数据库表、另一套业务完成状态或可任意选择来源的框架。

### 70.2 当前代码依据与复用范围

已用CodeGraph `codegraph_explore`分析`MoneyflowAutomationContract`、`update_daily_moneyflow_raw/silver`、`batch_moneyflow_readiness`，并直接核对正式资产入口、文件提升函数、命令请求与测试。跨系统消费者不变：本步只调用orchestrator的固定合同和本机Dagster，生产API、前端和Prod数据模型不消费新工具，也不新增对src.foundation/ops/biz/app/qtf的依赖。

| 已有依据 | 本步如何使用 | 不允许偷换的语义 |
| --- | --- | --- |
| `defs/run_contracts/moneyflow_automation.py` | 固定七表的资产、任务、检查和分区身份 | 不从输入JSON自行拼出第八个数据集或任意job |
| `run_contracts/asset_column_schemas.py`、`moneyflow_daily.py`、`paths.py` | 核对每层实际字段、键、分类和路径 | 不把大盘1行15列套到六表，不新增字段合同副本 |
| `checks/moneyflow.py`及`checks/moneyflow_daily.py` | 单日文件/转换验收复用现有完整语义 | 不只检查文件存在、行数非零或任务SUCCESS |
| `asset_guards/moneyflow_delivery_readiness.py` | 按表、每批至多10日读取同日两层事件与物理摘要 | 保留准确的检查绑定及Raw/Silver摘要关联；记录不足即停止，不无限翻页找绿检 |
| `io/moneyflow_mkt_dc_update.py`、`io/moneyflow_daily_update.py` | 仍由原正式任务调用，工具不直接调用writer | 两轮稳定、字段/键校验、六表数量基线、候选校验及逐文件提升全部保留 |
| `io/moneyflow_update_publication.py`及`io/moneyflow_candidates.py` | 读取已产生的receipt/checkpoint，保留原写文件锁 | 工具单实例锁必须独立；不能拿住writer.lock后等待任务来写文件 |
| `bootstrap/daily_basic_event_instance.py` | 默认`writable=False`读取现有PG，禁止自动DDL | 不用它提交任务/补事件，不设置`writable=True` |
| `run_contracts/run_keys.py` | 复用两个标准builder | 不解析run key生成参数，不把event storage id写入身份 |

临时`/private/tmp/moneyflow-p4-resume-20261017/sample.py`是审计反例：写死数据集、日期、行数、列数及请求目录，只适用于已完成的一天；其`control.py`没有跨进程提交锁，`gate()`还会在识别本人上次运行前因全实例active而停止。新的实现按本节职责重新编写，不复制这些限制再层叠条件。原报告和脚本保留历史追溯，不删除或覆盖。

### 70.3 文件职责、入口与参数审计

新代码放在`lake_console/orchestrator/src/orchestrator/`下的独立工具包，位于`defs`扫描范围之外。以下是拟新增文件，不是已有实现：

| 拟新增位置 | 单一职责 | 主要验收落点 |
| --- | --- | --- |
| `moneyflow_continuation_cli.py` | 解析plan/inspect/apply三种操作，打印进度和退出原因 | `tests/test_moneyflow_continuation_cli.py` |
| `moneyflow_continuation/contract.py`及包说明 | 固定七表顺序、工具预算、输入/输出结构 | `tests/test_moneyflow_continuation_plan.py` |
| `moneyflow_continuation/plan.py` | 日期白名单、当前差集、新旧清单衔接、原完整任务请求构造/校验 | 同上 |
| `moneyflow_continuation/state.py` | 只读核对run、物化/check、文件/来源证明，计算下一步动作 | `tests/test_moneyflow_continuation_state.py` |
| `moneyflow_continuation/submission.py` | 工具单实例锁、请求记录的持久化、一次提交及不确定结果核对 | `tests/test_moneyflow_continuation_submission.py` |
| `moneyflow_continuation/execution.py` | 逐表逐日编排、等待原任务、停止与进度汇总 | `tests/test_moneyflow_continuation_execution.py` |
| `tests/test_moneyflow_continuation_integration.py` | 新工具与当前真实job/asset/check的隔离链路验证 | 使用真实定义、临时instance/Lake和假源 |

不改旧CLI行为、`definitions.py`、正式asset/job/check/sensor、共享resources、run-key builder、受保护测试启动器或pyproject依赖。不把工具模块导入active Definitions，不再保留一条临时脚本正式执行链。后续若发现必须越出此表，先回原方案/LLD说明原因、影响与测试，满足确认规则后才改。

命令形式如下，实现状态见§70.14；能执行命令不代表已批准正式apply：

```text
工作目录 /Users/congming/github/goldenshare/lake_console/orchestrator
.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli plan --scope-file <明确日期白名单.json> --output <新清单.json> [--parent-plan <旧清单.json>]
.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli inspect --plan <清单.json>
.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli apply --plan <清单.json> --expect-plan-sha256 <已确认摘要>
```

不提供`--force`、`--retry-failed`、任意job/SQL/URL/Lake根、扩大窗口、放宽质量检查或启用sensor参数。`apply`既可首次执行，也可在同一有效清单下继续观察，是否提交由真实状态决定，不依赖另一个危险的“重跑所有”选项。`dg launch`的本地执行语义不替代现有服务队列，本工具使用已验证的本机GraphQL完整job请求；语法及版本仍以安装版本schema和CLI参考为准。

| 参数或设置 | 默认、来源与持久化 | 消费者/依赖、生效与可见性 |
| --- | --- | --- |
| `scope-file` | plan必填，无隐含“截至今天”；只含七表与明确ISO日期 | plan校验固定合同、日历、09-30截止及授权白名单；新交易日仅提示，不自动加入 |
| `parent-plan` | 可选已有清单；跨日继续时必须提供包含旧请求身份的父链 | plan/state核对父链摘要、同一批准范围和提交记录；只保留或缩小范围 |
| `output`、`plan`、`expect-plan-sha256` | 运营显式文件/摘要，不进入env、DB或前端 | output只允许已有`/private/tmp`或仓库`lake_console/reports`下的新普通文件，拒绝覆盖、符号链接及正式Lake/staging/instance路径；apply拒绝不匹配摘要、过期或含占位符的实际请求 |
| 实例、endpoint、repository | 复用正式INSTANCE_HOME、本机`http://127.0.0.1:3000/graphql`、`orchestrator/__repository__`；写进清单 | 读回实际身份；不允许CLI换地址。plan/inspect只读PG/GraphQL，apply只放行登记与launchRun |
| 工具控制目录 | 固定`/Volumes/datasource/data_lake_staging/moneyflow/continuation/`；会话按批准的日期集合摘要寻址 | 仅apply在已批准执行时创建；plan/inspect不得创建目录/锁。仅记录请求与恢复线索，不作为成功事实源 |
| 工具上限 | `ContinuationPolicy`集中定义§70.10的新工具预算，值写入清单并打印；不暴露调大参数 | plan/submission/execution/state共同消费；变更必须同步两文档、测试和确认，不散落脚本常量 |
| 原Raw/SQL/质量预算 | 复用`run_contracts/moneyflow.py`和原writer实际配置，默认不变 | 工具不得覆盖64次/300秒/768MiB及DuckDB512MB/1线程；容量1由原生队列维持 |

这是新增CLI输入与固定工具策略的配置审计；没有新增系统env、Settings、DB配置或用户页面。Tushare凭据由原任务资源获取，工具不读取/复制token，不把环境、连接密码或完整异常堆栈写进报告。

### 70.4 七表验收方式和固定执行顺序

开发时真实生产者校准：`partition_set`字段表示动态分区定义（`cn_a_moneyflow…_trade_days`），用于登记及资产分区核对；原生run的`dagster/partition_set`标签则是`<job_name>_partition_set`。Dagster 1.13.26完整任务会生成该标签，并将两个完整执行步骤写入`step_keys_to_execute`。已只读核对10-08原Raw/Silver任务及安装版本生产代码。新工具按完整job的原生标签和完整两步骤核对，不能要求标签等于动态分区名，也不能把原生保存的完整步骤误判为运营请求子步骤。请求仍不包含step/asset/check选择字段。

开发输入细化（2026-10-17）：`scope-file`采用`{"units":[{"dataset":"…","trade_date":"YYYY-MM-DD"}],"verification":{"path":"绝对证据路径","sha256":"文件摘要"}}`。verification只引用只读审计证据，不是新增业务参数或批准开关。证据必须包含当前运行依赖文件摘要、日历/instance配置摘要、当前serverId及14资产/21开关读回、隔离Definitions验证报告的路径和摘要；工具逐项重新比对，不接受单独的`approved=true`。依赖按七表入口及本工具的本地Python导入闭包计算，含共享模块；全库存另外记录。隔离报告须注明实际命令、退出码、覆盖的源码摘要及无正式凭据/隔离instance事实，不能用报告文件存在代替其内容核对。正式使用前由只读审计生成这份证据；本轮只在临时资源测试证据读取和拒绝分支。

固定顺序为大盘→THS行业→THS概念→DC板块→DC个股→THS个股→moneyflow；每表日期升序。同日Raw及其blocking check完成后，才提交同日Silver及其blocking check。本工具每次最多拥有一个尚未终结的资金流任务，不提前把整批任务塞入队列。

| 数据集 | 当前Raw/Silver列数 | 业务键 | 来源与数量核对 |
| --- | ---: | --- | --- |
| moneyflow_mkt_dc | 15 | trade_date | 两轮各恰好1行，逐字段保真及日期类型转换 |
| moneyflow_ind_ths | 12 | trade_date、ts_code | 非空、键唯一、两轮一致、前5日数量基线 |
| moneyflow_cnt_ths | 12 | trade_date、ts_code | 同上 |
| moneyflow_ind_dc | 18 | trade_date、content_type、name | 行业/概念/地域三类齐全、分别两轮一致及数量比较 |
| moneyflow_dc | 15 | trade_date、ts_code | 完整分页、非空、两轮一致及数量基线 |
| moneyflow_ths | 13 | trade_date、ts_code | 同上，保留此接口自己的证券覆盖 |
| moneyflow | 20 | trade_date、ts_code | 同上，不加其他接口/股票池过滤 |

列数只是当前代码核对结果，运行时比较现有完整schema，不以“列数相同”代替字段名/类型正确。Raw/Silver行数必须与真实来源receipt/verification证明一致，不能把09-30行数写成未来固定行数。六表每次Raw执行时按已有实现重新取得前5个已交付日期的基线，不使用计划生成时缓存的基线；下降超过20%即停止，DC逐类核对，不能因总数增长忽略某类下降。

完成一个日期必须同时满足：原生run成功；同日最新物化存在；对应blocking check成功且target的storage_id/run_id/timestamp准确绑定该物化；正式文件schema/日期/键/行数/摘要及来源证明正确；Silver绑定当前同日已绿Raw摘要且全字段转换一致。存储事件id只用于核对，不进入请求身份。新增六表的第一个日期先完整验收并保存表级样本报告；在已批准的同表清单范围内通过后连续执行剩余日期，不为每一天另造审批步骤。表级验收失败即停止整个会话，不跳过去把后续日期算完成。

### 70.5 清单生成、已完成差集和跨日继续

1. 输入只能是已明确的`(dataset, trade_date)`白名单。本阶段单清单至多49项；当前预计48项，超过上限须先拆分清单及核对整体范围，不自动提高上限。日期必须大于09-30、存在于正式SSE开市日历，并在生成时已经成熟；当天未到22点不纳入，休市日拒绝。历史整日缺口不能混进来。
2. 按表、每批至多10日读取登记、Raw/Silver交付和job事实，将每项分为“已验收”“仅登记”“待Raw”“Raw在跑”“Raw已绿待Silver”“Silver在跑”“需人工处理”。已登记不是完成；已有绿Raw只补Silver；两层完整就绪只记录跳过，不再请求源。不能再要求所有表缺同一组日期，也不能要求所有目标文件都不存在。
3. 新清单保存：格式版本、父清单/批准范围摘要、精确日期/顺序、生成与观测失效时间、管理员批准范围/依据及其明确期限（如有）、当前源码/依赖/隔离加载/正式加载身份、日历与实例配置摘要、每项原始事实及下一动作、固定完整任务/分区/check/目标路径、预算、原请求身份和sensor关闭要求。清单完整校验后原子发布；旧文件不覆盖。计划阶段不登记日期、不发送mutation、不调用sensor评估，不写正式staging。
4. 根清单保存完整批准白名单，范围摘要由排序后的`dataset/date/asset/job/check/partition_set/正式目标路径`及现有schema字段名/类型的规范JSON生成，不含观察日、当前源码commit或临时进度。子清单无论剩余项如何减少，都继承根范围摘要和原控制目录；本轮实际执行项只能是根白名单子集，不能按“剩余日期”重新算摘要另开目录。字段/目标合同变了不得接续原批次，先修订设计。这个摘要只定位请求记录，不表示文件自行授予权限，也不是业务完成证明。
5. 每个Raw动作首次记录时，用既有`build_repair_attempt_run_key(subject=raw_asset,repair_scope_id=trade_date,attempt=1,attempt_scope=原动作登记日)`生成身份；一旦已有持久化意图或原生run，跨日继续也沿用原身份。仅连`request.json`都未创建的动作可在子清单中确定当前日期身份；已有准备请求即使尚未创建send_intent，也保持原请求内容和身份，不覆盖旧文件。不能仅换观察日就再提交一次。
6. Silver身份在提交前通过现有builder绑定刚读回的同日已绿Raw SHA，不在实际请求中发送占位符。跨日子清单继承已提交动作的run_id、run key、请求摘要及未决意图；重新核对源/日历/代码/文件，已完成仍跳过，新成熟日期只列建议范围，不自动合并。
7. 清单的**观测有效期**为生成日次日00:00上海时间；过期先停止新的登记/任务提交，仍可inspect和读回已有任务。它与业务授权分开：同一剩余范围、处理规则及读写边界已经明确批准且未被管理员限定到期时，只需按父链重新只读核对、生成新清单并记录继承的授权依据，不为同一范围重复请示。管理员若明确限定批准时间/准确请求版本，则严格遵守该限制；新增日期、失败重试、改变合同/预算/写入范围等不继承旧许可。任何新清单都不能把旧大盘一天的授权扩成48项，原已提交身份和已完成事实保持。

### 70.6 工具防重复、请求记录与单次提交

工具锁为`continuation/executor.lock`，与`moneyflow/writer.lock`是两个文件。apply打开前校验路径、挂载/同盘/空间及无符号链接，再用`flock(LOCK_EX|LOCK_NB)`持有工具锁到会话退出；第二份工具在任何mutation前退出，不删除/重建锁绕过竞争。不同清单也用同一把工具锁，防止交叠范围同时推进。它不阻塞原正式job使用writer.lock；worker只在原写入阶段持有原锁。

控制目录按`<批准范围摘要>/<dataset>/<date>/<register|raw|silver>/`分开，不能像单日脚本一样复用全局`raw_launch`、`raw_delivery.json`。每动作分别保留不可改写的`request.json`（准备好的请求/身份）、`send_intent.json`（即将或可能已经发送）及`response.json`（实际原始响应）；`observation.json`只原子更新最后观察。只有request而没有send_intent，才能在核对原生仍未开始后认定尚未进入发送阶段。它们用于避免重发和定位run，不是第二份业务成功账本；删除/损坏记录不能令工具假定“从没提交”。

请求流程固定如下：

1. 在锁内先读取原生登记/运行/交付与既有请求记录，检查§70.7。查找job＋partition＋原run key；还须检查同job/partition是否有未被本批记录覆盖的运行。查询返回上限3；重复或无法解释的运行即停止，不能挑一个成功的使用。21个资金流sensor必须关闭，本批日期不得与外部人工维护并行。
2. 重新验证白名单、当前允许动作、清单有效性、源码/加载、日历/配置、原生队列与写入维护条件。只允许精确addDynamicPartition和原有完整launchRun；请求中不得含任意job、子步骤选择、预算覆盖或额外源参数。
3. **先独占创建request，再独占创建send_intent并持久化，最后才允许一次POST。** 两文件均拒绝覆盖，文件和父目录分别fsync；一旦send_intent存在就进入“可能已发送”，即使实际尚未调用网络也不能自动重发。请求包含数据集/日期/层、请求JSON摘要、标准身份、原生查询的已知状态、时间下界和预算。原响应拒绝覆盖；观察文件采用同目录临时文件→flush/fsync→os.replace→目录fsync。响应/进度写失败即停止新提交，不能回滚已提交业务数据。
4. GraphQL `launchRun`不按run key自动去重。读取操作可在预算内重试；登记/launch不使用HTTP自动重试。异常、超时、响应损坏或退出后“可能已发送”的记录先按原身份读回：仅找到一个与提交前状态、job/分区/来源位置/run config/请求身份一致的run时接回观察；找到多个、找不到、服务仍不明时都停止，**没有查到不等于可以重发**。
5. 只有完整持久化状态能证明该动作还在“准备、未进入可能发送阶段”，且当前原生/文件事实也没有对应写入时，才允许首次发送。已写发送意图但进程在真正POST前退出，也保守按不确定处理，不猜测。
6. 动态分区登记超时后只读核对精确key：存在则继续，重复登记不作成功次数；不存在且发送结果仍不明则停止。不得删除分区、run、事件、claims、pending或候选来制造可重跑状态。

### 70.7 状态判断表与恢复限制

**先识别并核对本工具已经提交的run，再决定是否存在冲突。** 不能先用“全实例active为空”挡住自己的续跑。以下每个分支都须有独立测试：

| 当前真实状态 | 唯一允许的动作 | 禁止动作 |
| --- | --- | --- |
| 未登记，且无文件/物化/运行/未决意图 | 登记清单内这一天，读回后重新判断 | 批量登记所有未批准日或历史来源缺口 |
| 已登记，Raw尚无文件/物化/运行，且从未发送Raw | 提交一个完整Raw任务 | 因日期已登记直接算完成 |
| 原记录Raw/Silver run为QUEUED/STARTING/STARTED/CANCELING等未终态 | 只继续观察该run_id | 生成新身份或再次launch |
| Raw成功且检查/文件/来源证明齐，Silver尚未发送 | 绑定Raw摘要，提交一个完整Silver任务 | 重采Raw或写入不同日期Silver |
| 两层已成功并满足全部交付条件 | 读回并跳过，增加已验收数 | 为了生成本地成功文件再跑一次 |
| 收到成功响应但本地结果未保存，或响应未知 | 按§70.6核对原生唯一运行；可确认则接回，否则停止 | 用“本地无response”判断未提交 |
| run成功但相应物化/check缺失、失败、过旧；文件已落但无完整原生交付 | 停止并记录精确不一致，保留文件和运行事实 | 补造绿事件、自动覆盖或只补跑子check |
| run失败/取消，或源为空/不稳定/数量下降/身份错误 | 停止并保留reason code、候选及来源证据 | 本工具自动加attempt、换run key、跳过错误继续后续日期 |
| 找到未记录的同日运行、重复运行、文件与摘要冲突、Raw发生新修订 | 停止，重新审计范围/来源再形成修复方案 | 按最新文件随意重新绑定Silver或覆盖既有数据 |
| 清单/源码/加载失效，但有已提交run | 停止新写请求，按run_id读回真实终态；数据验收待重新核对有效依据 | 把停止工具写成任务失败，或把未验收run写成日期完成 |

本步“可恢复”明确只指：工具中断后找回已有任务、继续等待，以及保留已验收日期并接上尚未提交的下一层。它**不承诺失败任务换run_id以后自动复用旧候选**。现有asset用`context.run.run_id`作为operation_id，已有同operation_id的文件恢复测试不能替代新run重试验收。失败后的候选复用、已有文件但无事件、真实修订等修复，必须按具体现场另立原方案内的修复步骤；当前命令没有这条隐藏重试链。这是明确停止策略，不是等待开发时临时决定。

### 70.8 正常排队、停止与可见进度

其他原已开启的89个sensor保持原状态。其他数据集有正常运行/排队任务时，允许本工具把当前唯一一个资金流任务提交原生队列等待，不改全局并发1、不插队、不停别人的任务。提交前目标资金流池仍须显式容量1、无不明占用；观察本人queued/running时允许它正常占槽/等待，不能仍要求claimed/pending均为0。发现另一个资金流writer或人工bootstrap维护则停止新提交，不清理其锁/槽位。

正常停止方式为当前工具Ctrl-C/SIGTERM：在每个本地动作、mutation前和状态轮询间检查停止标志；一旦收到，不再登记/领取/提交下一动作，保存当前run_id和原生状态后退出。本步不发送terminateRun，不声称后台任务随工具取消；需要取消正式job时沿用另行批准的现有原生操作。进程被强制结束时依靠已持久化意图和原生run恢复，不在finally里删除请求记录。

每10秒最多轮询一次当前run；只负责输出的定时器可每10秒打印最后已确认状态和等待时长，不读写业务或增加完成数，并单独保留“最后实际进展时间”，不能用定时输出冒充推进。提交、排队、下载/整理、检查、验收各阶段均输出当前表/日期/层、已验收数/批准总数、已登记数、已提交数、当前run_id、原生状态、等待时长、最后更新时间和reason code；每次有界I/O前后可更新阶段，正常运行不连续30秒无输出。打印“仍在等待”不增加已完成数，进度只在真实交付核验后增加，续跑初始数由原生事实重建。ETA显示“暂无法估算”。

每个原任务观察上限120次/20分钟，起点与累计次数写入请求记录，重启工具不重置。到观察上限仍在运行：标明“任务仍在后台，本工具停止观察和新提交”，保留run_id，不标失败/取消；后续inspect可读回，重新安排观察预算须显式说明，不能悄悄无限等待。跨午夜、后台失去心跳、源码/配置改变也先停止新动作；已有run真实结果仍须与工具退出原因分开记录。

### 70.9 源码和加载证明的更新规则

先保存当前整个orchestrator源码/项目配置清单，再逐项确认资金流运行实际依赖：七表asset/job/check/sensor、两类writer、publication/readiness/数量基线、字段/路径、资源、SQL/连接、标准请求/身份及本工具源码。相关依赖、共享定义或加载入口有变化时必须重新对账和跑受影响隔离测试；不能只凭文件名认为无关。

稳定的未提交文件本身不构成拒绝依据。当前周/月线改动已涉及paths、schema及catalog；已核对资金流路径/schema符号未变，但这不等于整个代码位置已经重新加载验收。其他改动须明确是否进入加载范围，并保留核对结论；无关且未进入实际运行/加载闭包的改动，不为了追求全仓干净而反复停工，也不据此修改/提交他人文件。

开发验收须使用无正式凭据、隔离DAGSTER_HOME的当前Definitions加载结果。正式apply必须绑定当前已确认代码加载记录/serverId，核对14资产的job/分区/check/依赖和21个开关。清单记录整个源码库存供审计，真正的写前比较必须依据已核验的运行/加载依赖清单；不能仅因全库存中无关文件摘要改变就阻断，也不能把共享路径/schema文件整份排除。若按符号判断无关，需记录所比较AST符号和导入/调用闭包依据，未能证明无关就停止确认，不能自己猜。发生未经确认的代码加载、运行依赖变化或无法解释的新模块时停止新提交；本工具绝不自行reload、重启或修复共享开发。若只是本工具包新增且未进入Definitions，须说明这一点，不能无故再重载一次。相关源码在每次新写动作前及每个日期验收后比较；无关变化单列审计，不修改原清单摘要或“默认忽略所有变化”。

工具退出结果固定区分：0表示当前命令正常完成，报告必须另有`mode`及交付结果，plan生成成功不能当作数据完成；2表示输入/清单无效；3表示事实冲突或需要人工处理；4表示仍有后台运行、预算到期或待继续观察；SIGINT正常停止返回130。apply的报告只有批准项全部验收后才能标`complete=true`，部分完成必须保留剩余项、当前run和原因。

### 70.10 性能测算和拒绝条件

工具元数据的有界实现补充：源码库存最多3000个文件、导入依赖闭包最多1000个文件、单动作目录最多8个控制文件（含中断残留临时文件），均收敛到`ContinuationPolicy`；超界停止，不能递归扩大读取。原采集的请求/时间/SQL内存上限直接引用既有moneyflow合同常量，不在新工具复制一套可调整值。

以下均为开发约束，不是新实测结果；原账户配额已确认够用，不再审计配额。实际行数估算引用10-17验收报告中的09-30物理行数，不能冒充48天的实测：90、387、1031、6024、5215、5572行，加大盘每天1行，预计本批约128239行/层；未来合法增长不因此裁剪。

| 项目 | 本步预算/估算及处置 |
| --- | --- |
| 对象、日期、枚举 | 固定七表；当前48个日期单元，单清单最多49；仅DC板块按现有三类请求，不能把三类拆成新数据集 |
| 正式动作量 | 当前最多48个新增key、48 Raw＋48 Silver完整任务、96正式文件、对应96物化/96blocking检查；若已完成则减少，不增加补造事件 |
| 源请求与分页 | 预计222次请求，含两轮，DC板块各类分别分页；已有每Raw64次/300秒、每轮20000行、page size2000保持，工具不能自行重试源 |
| 等待与总时长 | 两轮间隔累计至少48分钟；48个Raw活动预算合计至多4小时，不含排队/Silver/check，不能写成整批ETA。最多96个任务各120次状态观察；会话到观测失效时停止新动作；须先按§70.5重新核对和生成子清单，不能直接改旧文件有效期 |
| 计划/汇总只读 | 默认先按表≤10日批量读取，单次plan/最终汇总至多400次有界helper/原生读、300秒、RSS768MiB；不重扫7804天历史。超限保留未完成审计结果，不能发布可执行清单 |
| 执行只读 | 每日最多5个转换（登记、Raw提交/验收、Silver提交/验收），每转换≤40次有界读；每原任务另≤120次轮询。当前48项上界`48×5×40＋96×120=21120`次，另计划/汇总各≤400次；进程重启继承已用计数，不从0再给预算。每run查询≤3条，readiness沿现有100事件/检查上限；读回未知响应也记入对应转换预算 |
| 常驻内存 | 当前一个日期的控制/汇总元数据，≤49项计划元数据；业务行不进入工具内存，不能读取整批业务JSON/Parquet明细 |
| DuckDB与scan/join | 复用单日完整校验和SQL全字段对账，512MB/1线程/no-spill；无跨日期join。Raw数量门禁最多读前5个基线文件，并按当前执行时事实取得；不重复在sensor中扫描 |
| 磁盘和控制文件 | 沿用新增总量32GiB、启动可用≥64GiB门槛；计入本批run-scoped候选和验证文件，不能只算96正式文件。控制清单≤4MiB、单动作请求/响应/观察文件各≤64KiB、整批工具控制文件≤16MiB，不保存业务明细、token或无界事件日志 |
| 持久化与事务 | 原job逐文件校验/os.replace/checkpoint不变；工具每动作fsync后提交，状态文件逐个原子替换。无覆盖48日期的长PG事务，无远程库事务；业务写入由原job自己的正式边界负责 |
| 唯一写入和重试成本 | 一把独立工具锁＋原生队列/资金流容量1＋原writer锁；工具恢复优先读原run，新增重复源请求应为0；正式job失败重跑不在本步能力和预算内 |

预计行数和请求量不构成质量“应等于”值；只使用真实源与当前合同。超时间/内存/读取/空间预算、schema/分类/行数门禁失败、不明运行、源码/加载冲突和开关变化均停止新动作。不能自动改预算、删文件腾空间、换来源或跳过坏日期。控制目录空间应按本批已知run目录有界统计，只遍历本批原生run_id对应、已核验的dataset/date运行目录，每run最多512个普通文件、相对深度最多8，遇到符号链接或超界即停；该新增工具策略同样集中在ContinuationPolicy并写入清单。统计调用数在隔离压力测试中测量；不得全盘递归扫描所有历史staging来算一次余量。

### 70.11 硬口径—实现—测试对应表

下列拟新增测试以当前固定七表生产合同和既有真实报告/来源文档为依据；字段名/类型/日期/主键/空值及分类样本须先与生产者核对。expected使用独立字面值，不调用被测planner生成预期。计划阶段不预填任何“通过”。

| 编号/必须做到的事 | 代码点 | 正反验收 |
| --- | --- | --- |
| C01 只允许七表和明确成熟日期，不增加历史缺口/新日期 | contract、plan | 七表完整样本；未知表/休市/09-30前/当天未成熟/越权日期拒绝；不完整plan不发布 |
| C02 按真实各表字段/键/分类验收，复用原完整job | contract、state、submission | 15/12/12/18/15/13/20列及三类独立金样本；同列数错字段、错类型、重复键、缺分类、子步骤选择拒绝 |
| C03 已完成跳过、Raw完成只补Silver | plan、state、execution | 真实定义隔离链路；仅登记不算完成，Raw/check缺失不能继续，过旧Silver/摘要冲突停止 |
| C04 跨进程只提交一次 | submission | 两个真实子进程同时启动，第二个在POST前退出；检查后崩溃/意图后崩溃/响应后崩溃均不盲重发；锁与writer不同且不死锁 |
| C05 未知响应按原生事实核对 | submission、state | 服务已创建但响应丢失可接回；未查到、多条、不同job/日期/config/位置不得重发或误认 |
| C06 本人active接回观察，正常其他任务可排队 | state、execution | 本人queued/started不触发全局active拒绝；别人正常job不被取消/改优先级；另一个资金流维护者阻断 |
| C07 跨日保持已发送身份，剩余差集不重复 | plan、submission | 午夜前意图、午夜后父子清单继续；已完成不重采，旧Raw identity不换日；新日期不自动加入、旧清单不能发送 |
| C08 正式失败和残缺交付明确停止 | state、execution | 文件已提升但mat/check缺失、FAILED/CANCELED、数量下降/分类异常、Raw新修订：保留原事实且无后续POST/绿事件；不得承诺新run复用旧operation_id |
| C09 退出工具与取消原任务分开 | execution、CLI | Ctrl-C/SIGTERM、强制进程退出、观察超时；不领取下一动作、不发送terminateRun；原run仍可完成并由下次读回 |
| C10 恢复事实不靠本地“成功”标记 | state、submission | 伪造/损坏/丢失控制文件、路径越界/符号链接、已有未记录run均不能重复写；状态写失败不回滚业务文件/原生run |
| C11 资源与进度有界 | contract、execution、state | 49项元数据压力、≥10日拆批、记录/文件/查询上限反例；每10秒观察、预算不因重启重置、完成量只随真实交付单调增加 |
| C12 自动化与其他项目保持 | CLI、submission静态门禁 | Mutation白名单只含登记/launch；拒绝sensor评估/开关、pool setter、reload、runless event、Prod访问及任意源/根/配置覆盖 |
| C13 源码/配置/加载证明按实际影响更新 | plan、state | 相关代码/实际加载漂移阻断，无关稳定脏文件不一刀切；旧加载证明不能冒充当前；21 sensor非STOPPED即停止 |

新功能测试按现有项目`.venv`、临时HOME/instance/Lake及无正式凭据的方式运行；实际GraphQL提交边界用本机隔离假服务/确定响应替身，双进程竞争须用真实OS文件锁而不是mock锁。原受保护的catalog/static/root-guard与I03～I08仍用原受保护启动器，不把普通新功能测试冒充这些门禁。基础回归保留七表已有定义/写入/基线/恢复测试。只重跑本步触达和依赖变动实际影响的范围；若共享字段、路径或请求行为发生变化，则先停止并扩大消费者审计，不能默认沿用1742项旧通过。受保护测试始终使用原启动器和隔离资源；新模块不在允许清单时先补相应设计，不绕过或扩大为整个目录可读。隔离集成至少使用当前真实Raw/Silver job及checks完成七表最小链路，按真实来源合同构造输入，明确假源未覆盖真实网络。

### 70.12 开发顺序、正式样本和退出条件

本步开发按同一目标分为：先实现纯计划/合同/状态判断，再实现独立锁/持久化/单次提交，最后接入编排/CLI/隔离链路。每部分完成必须按C01～C13对账，不得先跑正式48项再回补测试。开发前重新记录当前代码、实际依赖和加载影响；其他周/月线改动不在本步提交范围。没有改变模块边界或共享合同，不更新主体依赖矩阵/CodeGraph架构快照。

开发完成的必要证据：新工具测试和上述相关回归通过，当前Definitions在无正式凭据的隔离环境加载通过，Ruff新文件默认规则及现有致命错误基线通过，文档与相对引用检查通过，C01～C13逐项列出测试/验证/未覆盖项。测试数量不替代真实来源/执行证据。

正式执行分开批准，不能从本次写文档推定。建议下一执行范围为大盘10-09这一天两个完整任务：用新工具在Raw已提交后正常停止工具（不取消job），再用同一请求身份接回，确认只出现一个Raw run、一次两轮来源采集、两层交付正确；再次调用同一清单应新增0请求/0登记/0run。该真实样本专门补工具继续观察边界，不重做已通过的10-08。结果不符则停止，不进入剩余清单。

新工具样本通过后，在明确批准的完整剩余清单内逐表处理；其他六表第一天完整读回验收后继续同表剩余日期。失败任务修复、sensor启用、未来新交易日及P5至少3个交易日验收均不属于本步开发或上述一个日期样本许可。最终批量退出条件是批准范围每项都有准确的原生/物理证明，已完成不重跑，未决/失败/停止数明确、完整历史保留证据充分，21资金流sensor仍STOPPED；未完成项不能省略或标成整个P4完成。

### 70.13 设计审计对账（开工前记录）

下表及本小节末尾是写设计时的审计事实；当前实现与未通过项统一见§70.14，不再以当时的“未实现”描述当前代码。

| 前次审计问题 | 已写明的决定 | 后续怎样证明，不冒充已完成 |
| --- | --- | --- |
| D1 仅有大盘一天及1行15列 | §70.3固定新工具职责，§70.4逐表真实合同，复用原完整任务 | C01～C03及七表隔离链路；新工具未实现 |
| D2 两份工具可能重复提交 | §70.6独立全局工具锁、动作意图先持久化、单次POST | C04/C05/C10跨进程与崩溃测试，正式样本新增运行数读回 |
| D3 本人active被挡、响应丢失不明 | §70.7先认本人run；§70.6唯一原生结果核对，不明即停 | C03/C05/C06，不能只测HTTP正常返回 |
| D4 跨日身份变化且清单假设全缺 | §70.5真实差集、父子清单、继承原身份、过期不发送 | C07及已完成/半完成独立样本，子清单缩小范围不改根记录目录 |
| D5 文件恢复被误当成正式新run续跑 | §70.7限定为继续原run观察；失败后停止，无隐藏重试入口 | C08/C09；新run复用旧候选不在本步声称范围 |
| D6 其他正常调度导致阻断、退出语义不清 | §70.8沿原生队列排队，工具退出不取消job，观察有上限 | C06/C09/C11；不修改89个现有开关 |
| D7 八项旧检查未覆盖批量工具 | §70.11完整正反测试与真定义隔离集成，§70.12明确正式样本 | 开发完成后逐项补实证，不把旧1742或八项算新工具通过 |
| D8 工作区和加载证明已变化 | §70.9区分实际依赖和无关修改，重新验收加载影响 | C13；本轮静态核对不代表当前整个Definitions已重新加载 |

本轮完成原方案/LLD互引与本地链接核验、14个Raw/Silver字段结构核对、48项/96任务/222请求/128239行估算和21120次执行读上界算术对账，8项审计问题与13条实现/测试硬口径均有唯一落点。文档检查未访问正式资源、未运行功能测试。

本轮静态审计已给这8项问题逐项确定处理方式，并对照当前真实代码/消费者和原性能规则校核设计；**结论仅为文档设计缺项已补齐，不是新工具已实现、已测试或获准正式执行。** 后续若实测证明某个前提不成立，必须先回本节及方案§75修订影响和验证，再满足已有确认规则进入下一动作，不能以临时脚本绕过。

### 70.14 2026-10-17实现、实测及验收阻塞（修正前记录）

以下为问题发现时的历史事实；修正后状态及复验结果见§70.16。

用户批准“提交修改，如果没有新的卡点就推进完成本步”后，先提交三份原文档/根规则，提交号`d631ae974`；随后按§70.3新增七个工具源码文件和六份测试，未更改已有Dagster定义、共享合同、受保护启动器或其配置。CodeGraph开工分析覆盖原合同、writer、readiness及调用入口，开发后执行`codegraph sync/status`，索引正常；没有跨子系统依赖、Lake路径或架构矩阵调整。

工具已经实现plan/inspect/apply、固定七表和成熟SSE日期白名单、父子范围限制、跳过已验收/仅补Silver、独立跨进程锁、请求和发送意图先持久化、未知响应核对、观察原run、失败停止、信号停止、持久化读取/观察预算、代码/配置/加载核对及有界文件核验。它不直接写业务Parquet或补造事件。原生分区标签/完整步骤的真实差异已先同步§70.4再修正新工具。

证据文件：

- [开发及验收报告](../../reports/moneyflow_p4_continuation_development_20261017.json)：本轮源码摘要、99项新测试、267项相关回归、C01～C13测试映射、真实只读结果、未通过门禁及日志摘要。
- [隔离Definitions加载报告](../../reports/moneyflow_p4_continuation_definitions_isolated_20261017.json)：实际命令`.venv/bin/dg check defs`、退出0、临时instance/无正式凭据、113个依赖文件及736项源码库存；加载前后库存一致。它只证明隔离加载，不能代替正式serverId/加载确认。

99项新测试覆盖真实双进程锁竞争、意图后真实进程退出、实际SIGINT/SIGTERM、真实本机假HTTP服务响应丢失、独立原生身份反例、49项压力、代码/加载漂移和文件遍历边界；新测试进程峰值RSS为368492544字节，低于768MiB。七表隔离链路使用当前真实Raw/Silver job、asset check、临时SQLite事件存储和Parquet，来源/时钟及HTTP提交边界使用替身。in-process测试适配器显式核对它与正式GraphQL在origin及空asset selection上的差别，没有放宽正式validator；正式native identity另以独立反例及10-08既有任务只读核验。每表重复调用均新增0源请求/0任务；故意损坏文件后停止。267项既有回归分别在新进程运行，覆盖七表定义/写入/恢复/来源及数量门禁；不宣称真实网络采集或正式队列恢复已验收。

另外用新只读backend核对既有正式`moneyflow_mkt_dc / 2026-10-08`：9次原生读取，两层各1行，准确绑定原run、物化、blocking检查、当前摘要和来源证明，判为complete。没有重新提交、登记、采集或写湖。原Raw/Silver run分别仍为`7f9ea4b6-171b-4177-b545-0d245b768e38`及`06491beb-e782-4898-85f9-1b110f8cbfb0`。本轮未作任何正式mutation、启用sensor、设置容量、reload或重启服务。

| 未通过项 | 当前代码/实测依据 | 本步处理与退出条件 |
| --- | --- | --- |
| B1：受保护启动器仍要求已删除文件 | `tests/stock_suspend_confirmed_test_runner.py:263`仍列`defs/bootstrap/stock_weekly_event_files.py`；文件已由`09ea909fd`正式删除，当前Git无该路径。目录治理和run-contract静态套件均在启动器预检退出，不能记为测试断言通过 | 保留原失败日志，不恢复退役实现、不拓宽目录读权限、不改启动器。后续须先审计重构后的精确文件白名单/消费者并完成修正设计和既有确认，再改并复跑 |
| B2：根门禁将历史报告中的测试名误作运行引用 | 原启动器执行根门禁，到第三份源码切片失败；`tests/architecture/test_lake_console_retirement_guardrails.py:160`扫描`moneyflow_p4_daily_guard_evidence_20261013.json`，命中的只是其中保存的测试函数名称，无实际被禁命令或import | 保留不可改写的历史报告，不删字段迎合检查。后续须审计运行代码、运行配置与历史证据的识别边界，保留真实禁用引用的反例测试，再修正原门禁并复跑 |

上述两项在本轮首次实测发现，说明此前开工审计没有覆盖测试基础设施当前可运行性；不能用历史通过或本轮366项通过替代。**当前状态为“功能实现及局部验收完成，完整开发收尾阻塞”，不满足§70.12全部退出条件。** 新增实现和本小节记录留待提交；正式10-09样本、剩余48项、自动更新及P5均未开始。本次授权未扩展到受保护启动器/根门禁修正，下一步先落实其方案与审计，满足原确认要求后处理B1/B2；通过后再回到§70.12既定正式样本顺序。

### 70.15 两项测试问题的修正设计（2026-10-17，用户已批准修正并复验）

目标是消除§70.14的B1/B2，让原检查真实运行；不恢复周线旧实现、不削弱网络/正式Lake/数据库隔离、不删除历史报告，不借本步登记分区、运行正式job、切换sensor或重载服务。用户本轮已明确要求“马上修正这俩问题，然后复验，继续推进”，覆盖以下测试修正及隔离验证，无需重复请求同一授权。

**代码与影响面审计。** 已核对原启动器`source_files_for_scope/policy_for`、consumer套件真实imports及当前defs文件库存，CodeGraph检索后用当前代码补足测试文件未清晰索引的部分。isolation/adapter/regression/root-guard源码列表均无失效路径；仅consumer列表残留6项：`stock_weekly_event_files.py`、`stock_weekly_event_instance.py`、`stock_weekly_events.py`、`stock_weekly_history.py`、`stock_weekly_adj_bootstrap.py`和`prod_db/stock_weekly.py`。它们已被周/月线重构提交`09ea909fd`删除，现行调用方为`stock_period_history`及其CLI；保留的旧CLI明确抛出retired错误，不能写入。删除这6个失效权限条目，保留上述拒绝入口的测试读取权限。

consumer用于真实全量定义导入/AST审计，当前还必须读取5个已存在的新模块：`defs/bootstrap/stock_period_silver_cli.py`、`defs/checks/stock_period_silver_checks.py`、`defs/io/stock_period_silver.py`、`defs/run_contracts/stock_period_silver.py`、`defs/stock_period_silver.py`。已逐项读取其imports：它们与现有周/月线asset/check/catalog相连，其余本地依赖已在精确列表内。只新增这5个普通文件字面路径，不自动收集目录、不新增目录递归权限；consumer唯一文件数从728变为727。其余4种scope保持原列表，原runtime目录身份校验、network deny、正式路径deny及启动/计数/skip/xfail门禁保持。`CONSUMER_SOURCE_FILES`本身是原有隔离配置：默认仍为精确静态tuple，来源/持久化为原启动器源码，仅consumer套件消费，下次生成隔离policy生效，不新增env、DB、CLI或全局设置。

**历史证据与运行代码分开。** 根门禁保留Git跟踪/非忽略新文件的完整库存，以及所有Python文件的真实退役import检查。将现有运行引用判断提成测试文件内纯函数：只将`lake_console/reports/`下的`.json`识别为报告数据，允许包含测试名称/历史引用；不排除整个reports目录。该目录中的`.py/.sh/.mjs`仍检查，正式代码/配置路径下的JSON/YAML仍检查，名称相似的`reports_backup`也不能绕过。原错误报告只保存了`cases`里的测试函数名，不是运行配置，不改写其内容。新增独立字面正反样本，证明历史报告允许、真正命令/import/配置仍能抓住；根套件固定断言数随新增参数样本同步，原断言不减少。

**实现文件。** 仅修改`orchestrator/tests/stock_suspend_confirmed_test_runner.py`、根`tests/architecture/test_lake_console_retirement_guardrails.py`，新增`orchestrator/tests/test_protected_test_runner_inventory.py`核对当前真实文件库存和失效/符号链接拒绝。两份资金流原方案/LLD同步记录；既有周/月线实现、共享脏文件及旧执行证据不改。

**验证与预算。** 先用新增反例证明修正前失败，再复跑原consumer目录治理、run-contract静态、asset-check增量治理、root-guard与I03～I08；这些仍只通过原受保护启动器执行，不直接pytest绕过。新增启动器静态库存测试只读本地源码，使用项目现有venv和临时资源，无Dagster/网络/正式数据访问。复跑资金流99项新测试；上一轮267项既有回归代码/依赖未变，保留其摘要，不为测试基础设施修正重复源采集。根门禁仍按原每1000文件切片，原完整Git库存不缩减；每child沿原时限/资源/失败即停策略。只保存小型元数据/日志到临时目录和reports，不读写业务行、无源请求；无新增数据量/事务/配额成本。

中断保留日志后重跑测试，不撤回或改写业务事实；失败不跳过、不降断言、不扩大文件/网络权限。完成条件是新增正反样本、上述原门禁、当前隔离Definitions、Ruff和文档检查全部通过，并记录准确数量和代码摘要，再将本步开发验收状态改为完成。若发现新的真实依赖差异，先回本节说明具体路径和调用方再调整，不恢复旧代码或盲放行整个目录。正式单日样本与全量接续继续遵守§70.12的阶段边界。

§70.15复验补充：B1修正后目录治理已能执行；静态套件暴露一个同源的旧断言问题：`test_gold_wealth_market_turnover_keeps_single_json_integrity_check`按三行源码字符串寻找`GOLD_WEALTH_MARKET_TURNOVER_CHECKS`，当前catalog只是排版成一行，真实值仍是唯一integrity检查。已读取真实赋值、check定义及目录治理消费者，并对全静态套件可解析的多行assertIn做只读核对，仅发现这一处失配。修正范围补入`tests/test_run_contract_static_gates.py`该断言：解析实际赋值AST，要求赋值唯一且字面tuple恰为原单一检查名称；原JSON类型、唯一check断言均保留，113个逻辑测试不减少。补同方法内独立单/多行及空/多项/错名样本；不修改catalog或期望业务值。该修正是完成原静态复验所必需，继续按本轮已批准的修正/复验范围执行，原隔离边界和正式动作禁区不变。

§70.15增量治理对账补充：原目录/静态检查已通过后，增量治理套件实际执行发现测试矩阵未登记七表Raw/Silver共14个资产及已存在公告Raw资产。已读取七表真实blocking checks、`moneyflow_delivery_readiness`及各sensor转发的`MoneyflowAutomationContract`，确认检查参与同日就绪判断；当前通用测试适配器仅识别AssetReadinessSpec，漏识别这类合同。公告实际有file_contract、delivery_reconciliation两个blocking check，无对应sensor readiness入口；正式保留清单也未包含这些资产。只在已被其他任务修改的`tests/test_asset_check_incremental_governance.py`新增独立资金流/公告段：category保持KEEP_BLOCKING_DAGSTER、retention_allowed=False；资金流readiness=True、公告False；测试实际消费者发现补识别sensor模块中真实导入并转发的MoneyflowAutomationContract。保留周/月线原有未提交段，不重排或收走他人差异，不改生产检查、retention列表或任何调度。对账仍由原6个完整方法核对catalog、实际checks和实际consumer，补独立保护断言，不能仅把缺项过滤掉。该项属于本轮完整复验中发现的测试清单缺失，按用户要求修正后复验；不是新增数据集或业务能力。

§70.15当前工作区刷新：收尾核对发现16:05周/月线另有实际修改：两个period合同变化，并新增`defs/asset_guards/stock_period_silver_readiness.py`。已读取该文件及两个合同的新增接口，内容只服务周/月线update/event evidence，不修改资金流合同；但当前全量defs审计确需读取新模块。白名单在已审计5项之外再补此1个普通文件，consumer现为728项；仍不开放目录，不改动这些他人源码。旧隔离加载证明因此不能继续当作当前证明，最后一次验收须重新采集库存和加载结果；资金流源码本身未变，不凭“无关”跳过实际影响核对。若加载前后库存再次变化，则该次证明作废，不标当前验收通过。

### 70.16 两项问题已修正、开发验收完成及下一步准备

本轮按用户指令完成§70.15修正，并以原受保护启动器完成复验；当前本步开发状态从“验收阻塞”变为“开发验收完成”，不是P4全部完成。证据见[复验报告](../../reports/moneyflow_p4_continuation_gate_recheck_20261017.json)、[本轮隔离加载报告](../../reports/moneyflow_p4_continuation_gate_recheck_definitions_20261017.json)。先前失败报告和10-13历史报告全部保留，已核对后者与当前Git HEAD的字节摘要相同。

| 要求/修正 | 真实落点及证据 |
| --- | --- |
| 周线旧文件不再需要 | 读取现行stock_period历史实现、旧CLI的retired拒绝及`09ea909fd`删除事实；consumer移除6条失效路径，按当前imports/全定义发现补入6个精确普通文件，最终唯一文件数728。其余4种scope列表不变，不使用exists过滤来默默丢检查 |
| 历史报告误报消除 | 根测试先按用途判断文件，报告目录JSON仅作为数据；同目录Python/Shell/JS、正式目录JSON/YAML及相似目录仍检查。11个独立正反样本通过；真实Python退役import检查仍覆盖原完整Git库存 |
| 拒绝坏权限条目 | 新增8项启动器库存测试；修正前实际2失败/6通过，修正后8项全过，包括真实缺文件、符号链接必须拒绝，当前defs发现与显式名单逐项对账 |
| 格式变化不改变合同 | 静态检查改读实际AST唯一赋值及原单元素tuple；单/多行都接受，空、多项、错名拒绝，原JSON类型及唯一check断言保留；113项逻辑测试不减少 |
| 治理记录与生产者一致 | 仅补测试矩阵漏登的14资金流资产及公告Raw资产，读取现行真实checks与readiness消费者；blocking/不进入专用retention的现状保持，原周/月线未提交段保留。6项原方法及180个子测试通过 |
| 原门禁真实复跑 | 目录治理12项、run-contract静态113项、增量治理6项通过；root-guard每切片24逻辑用例，8个切片均通过，完整Git库存7633项，无删减；I03～I08全部通过，包含启动防护正反、Python/native网络隔离及正式根拒绝 |
| 新工具仍正确 | 七表接续工具99项加库存8项，共107项最新复验通过，无skip/xfail代替通过；七个工具源码摘要与上一轮一致。此前267项既有回归保留其原日期/摘要，本轮不冒充重跑 |
| 当前隔离加载与边界 | 临时HOME/instance、无正式凭据执行`.venv/bin/dg check defs`，退出0，加载期间737项源码库存稳定；113项资金流依赖在收尾核对一致。Ruff新库存/根测试默认规则、项目致命错误检查及文档检查通过 |

本轮实际修改4份已有测试文件、增加1份库存测试，并同步两份原文档和新增复验报告；没有修改资金流业务代码、共享目录/依赖矩阵、正式Lake路径、asset/check/job/sensor、源请求或保留执行逻辑。测试代码层的新增读取严格为上文逐项审计的普通文件；I03～I08证明原网络、正式数据与启动边界未放宽。

**共享工作区的准确限制。** 隔离加载之后，三个既有周/月线模块又有修改：`stock_period_silver_readiness.py`、`stock_period_silver_cli.py`、`stock_period_silver.py`。它们不在已审计的113项资金流执行/工具导入闭包内；全库存文件集合未新增/删除，相关路径与当前摘要已单列在复验报告。不能声称整个共享项目源码从此不变，也不因此重跑资金流源采集或退回旧实现。本步结论绑定报告时间与资金流依赖；下一正式动作仍按§70.9重新核对当时实际源码/加载证明。隔离报告不是正式服务加载批准。

继续完成了下一步的只读准备：正式实例中`moneyflow_mkt_dc / 2026-10-09`未登记、无两层交付，确为已成熟SSE开市日；21个资金流sensor全部STOPPED；资金流池显式容量1、未占用、无pending，daemon/14资产合同读回通过。下一动作应从登记这一天开始，再按§70.12执行Raw提交后停止工具/接回原run/Silver/重复零新增的样本。此处只读准备不构成可执行清单或正式写入授权，正式源码加载绑定尚需在该步骤核对；未悄悄扩大到剩余48项。

本轮正式mutation、分区登记、运行提交、Tushare请求、写湖、开关修改、容量设置、reload及服务重启均为0。源码/文档/报告改动尚未提交或推送；后续按用户提交指令白名单处理，不混入周/月线他人修改。

§70.16末次核对补充：在上述全套复验通过、生成报告之后，周/月线继续修改了`run_contracts/stock_period.py`与`run_contracts/stock_period_silver.py`，另有4个period helper实现变化。两个合同位于保守导入闭包内，**末次核对已不再与本轮隔离加载摘要一致**；不能沿用上文“生成报告时一致”的事实证明当前正式加载。五份本次修正测试的摘要未变，全套测试通过记录保留，但正式执行就绪为False，已追加`post_report_recheck`及精确路径/时间。不自行修改、回退或锁住周/月线实现，不因此重复重跑已经通过的测试；待共享代码稳定后，刷新受影响验证与正式加载绑定，再进入10-09正式样本。本步已完成测试缺陷修正和对应复验，不能据此声称共享工作区从此稳定或正式样本可以直接运行。

### 70.17 10月9日大盘单日执行说明与当前代码审计

**目标及边界。** 按用户本轮继续推进指令，执行§70.12既定的 `moneyflow_mkt_dc / 2026-10-09` 单日真实验证。本次最多登记1个日期、启动2个原有完整job、生成Raw/Silver各1个文件及其原有检查；预期每层1行15列、Tushare两轮共2次请求、0 reject。21个sensor保持STOPPED，另外47项、所有Prod数据库、共享周/月线修改和配置setter均不在本步范围。不取消Dagster后台任务，不改调度时刻。

**开工核对。** 2026-10-17 16:45正式只读核对：当天已成熟且SSE开市，尚未登记，没有Raw/Silver文件、物化或任务，下一步确为register。84份已验收资金流业务源码摘要均与已验收记录相同；对提交7bed457a148e26b08398bf8d29b361d98626d9fc的共享符号比较确认：paths中的lake_path/raw_moneyflow_path/silver_moneyflow_path，14项moneyflow字段定义，以及目录moneyflow相关35项节点（含14个分区枚举、14个分区模型调用和7个Raw资产构造；补充独立核对14个Raw/Silver构造全部相同）AST保持。共享period合同新增completion/update函数只由周/月线消费者使用；资金流路径、检查及writer不调用它们。CodeGraph explore已检查dependency_files/verification的调用方，再以当前导入与AST核对补足动态Definitions加载边界。当前113项依赖整文件摘要及737项库存已重新采集，隔离Definitions加载通过且前后稳定，不修改工具白名单或忽略共享文件。正式14资产/job/分区/check/依赖读回吻合，21开关STOPPED；绑定serverId 906ed8b6-8fd2-4f1f-b724-3ce491b35e69。新工具位于defs外，不需要reload。

**具体操作。** 工作目录为 `/Users/congming/github/goldenshare/lake_console/orchestrator`，正式DAGSTER_HOME为 `/Users/congming/.goldenshare/dagster_home`；SDK查询仍通过已有只读入口，唯一正式变更走固定本机GraphQL。只读准备已保存 `/private/tmp/moneyflow-sample-20261017-pp5aj2f8/verification.json`（SHA256 2356a8705568b81a09f838d44391e3c9159201caca133b52a55565780927ecc1）及scope.json。命令：

```sh
.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli plan --scope-file /private/tmp/moneyflow-sample-20261017-pp5aj2f8/scope.json --output /private/tmp/moneyflow-sample-20261017-pp5aj2f8/plan.json
.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli inspect --plan /private/tmp/moneyflow-sample-20261017-pp5aj2f8/plan.json
.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli apply --plan /private/tmp/moneyflow-sample-20261017-pp5aj2f8/plan.json --expect-plan-sha256 369da01df15dfa733ac74e76a48952cf1a6bf2abdd2208d040d5eb0e3fbaba1a
```

先在日志及持久回执看见Raw run id，再仅向CLI进程发送SIGTERM；停止退出后运行同一apply命令接回原run，不给Dagster job发取消信号。写前再次核对完整依赖、服务、日历、配置、一次一个资金流任务及物理冲突；新动作前发现真实变化立即停止。请求/发送意图/回执按既定工具规则保存在正式staging的moneyflow/continuation下，不改写旧请求，不靠重发处理未知结果。正式文件仍经原候选检查和同文件系统原子提升。

**预算和验收。** 一个日期、最多3项mutation、2个完整job；Raw正常两轮请求间隔至少60秒，上限64请求/300秒/20000行、768MiB RSS，SQL 512MB/1线程/不spill；正式新增文件预计约5KiB，保留原32GiB写入/64GiB余量门槛。每个job间隔10秒读回、最多120次/20分钟，预算持久化，排队不伪造完成；超时仅停止新提交，保留后台任务及接回依据。源码变化不终止已提交任务，先观察原run。仅两层run成功、检查准确绑定对应物化、物理schema/日期/键/行数/摘要、来源两轮证明、Raw/Silver逐字段转换全部一致，才计本次1/1完成；停止/接回必须证明只有一个Raw run、两次来源请求。随后同一apply应0新增登记/0新增job/0新增源请求。结果、命令和准确清单SHA另行追加，不能提前标完成。当前总体接续仍1/49，剩48，单日通过后才变2/49、剩47。

### 70.18 实测恢复阶段错误的修正设计

**已观测原因。** 16:47登记10-09并提交Raw run 23b6eeee-9189-44bb-a812-0951bc20a5c7；仅停止CLI后退出130，后台仍STARTED。恢复apply只看registered就将phase设raw；随后重复收取Raw阶段读额度，已有raw预算从首轮检查累计至40而触发read_budget。此前假原生边界guard不读数据库，未覆盖真实写前检查的读量，原单元通过不能证明此项真实恢复已经通过。

**实现及影响面。** 只改defs外`moneyflow_continuation/execution.py`与对应execution测试，不改请求、Journal、额度常量、共享业务文件或CLI参数。阶段必须由已经完成的初始原生/物理snapshot的next_action决定：待注册→register，无Raw→raw，Raw已绿→silver；若原run仍在执行，直接用既有journal及run id进入wait_run观察，成功后再进入下一阶段，不重复计入上次提交阶段预算。初始snapshot仍严格验证原任务身份、检查及文件，未登记/失败/非本工具任务等原拒绝保留。poll预算和所有旧action预算保持，不清零、不加额度、不新增Raw。

**验收及继续。** 先在隔离资源构造原生已提交、Raw阶段预算恰为40的反例，分别覆盖后台仍运行和已成功两种恢复时机；修正前必须失败，修正后只新增Silver一个job，Raw仍只有原run、raw预算仍40，未绕过新写前guard；已有超时/源码变化/过期/未知结果/49单元/真实七表job回归一并复验。只读观察已有Raw不等待修正，不取消任务。随后重新生成无正式凭据的当前Definitions证明及113项完整依赖证据，以原单日plan为parent生成同范围子清单保留root/request/run，更新源码证明；不能改原plan或budgets.json。新清单SHA写入执行记录后用原CLI接回并完成单日验收；其他47项和21个自动更新边界保持。性能、读写路径及失败处理沿用§70.17，修正不扩大任何预算。

§70.18执行前复验：两项恢复反例修正前均退出4而失败，修正后与七表真实job/Parquet隔离链路及原新工具回归共109项通过（15.85秒），Ruff及文档检查通过。最初将测试临时根放入允许输出的/private/tmp，导致既有“禁止输出目录”反例前提不成立；已纠正测试命令使用默认隔离临时目录，未修改该测试或产品边界。后台原Raw已成功，只读子清单判定下一步silver。当前隔离Definitions再次通过，113依赖/737库存保持，正式serverId及21停止状态不变。保留原plan及所有40次Raw检查记录，子清单 `/private/tmp/moneyflow-sample-20261017-pp5aj2f8/repair1/plan.json` SHA256=19000c4b0ef4a4d4e1fda26939ba158d551c180802497b58b9c9c5329f1213e1，parent SHA=369da01df15dfa733ac74e76a48952cf1a6bf2abdd2208d040d5eb0e3fbaba1a，root_scope_digest保持2934652b347cc928bbbb7576638baf05955bb65d3c4c026ac9ba1deeb7ed5f5a。下一命令为同一工作目录下 `.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli apply --plan /private/tmp/moneyflow-sample-20261017-pp5aj2f8/repair1/plan.json --expect-plan-sha256 19000c4b0ef4a4d4e1fda26939ba158d551c180802497b58b9c9c5329f1213e1`；读取原Raw事实并仅启动尚缺Silver，不重新登记或下载。

### 70.19 单日验证已完成及后续准确待办

2026-10-17 16:53独立只读验收通过，详见[10-09正式单日验收](../../reports/moneyflow_p4_continuation_market_20261009_acceptance_20261017.json)（SHA256 6ec3adbdc089626f0070b3a881a2e3486924c75f130f869e48d807b60bb3a2bf）。本步正式变更仅登记1个日期、启动2个完整job、生成2份文件及原有2条物化/2条blocking检查，来源请求2次；没有sensor变更、配置setter、reload、Prod访问或其他日期写入。

| 层 | 原生run id | 物化 / check id | 结果 | 正式文件 |
| --- | --- | --- | --- | --- |
| Raw | 23b6eeee-9189-44bb-a812-0951bc20a5c7 | 7630545 / 1636315 | SUCCESS，1行15列 | 2612B，SHA256 5a1b514102d11e3bac35be81841833a8b10d0c6ff36f1056313569182eaec0df |
| Silver | 09d2f9ee-903f-4fdb-adc6-d93d93b7361b | 7630573 / 1636316 | SUCCESS，1行15列 | 2588B，SHA256 f17e61165ae320ebd827dd939a60fea5c8eca8eb01b8de1dcae65eb672ce31ba |

检查target的storage_id、run_id及timestamp均准确绑定对应物化；Raw来源凭证记录2请求、稳定间隔60.196303秒，源端/归一化/两层写入各1行、reject 0，Raw日期VARCHAR到Silver DATE及其余14字段逐项通过原检查。初次工具SIGTERM退出130，原Raw持续执行；旧版本恢复曾因read_budget退出4，按§70.18修正后，原Raw已成功，新工具直接转Silver，只新增1个整理任务。正式实测覆盖“停止后接回已完成的同一Raw”；“接回时Raw仍运行”的修正路径由新增隔离反例覆盖，不虚称又做了第二次真实下载实验。全部旧清单、请求和预算保留，Raw提交检查计数仍40。再运行相同子清单退出0、complete=true，独立读回每层恰好1个run/物化/准确绑定check，两次来源采集未增加。

修正后工具、库存及七表真实job/文件/检查的隔离回归109项全部通过，新增两项反例修正前均失败，Ruff和文档检查通过。资金流84份业务代码保持，当前113依赖/737库存隔离Definitions验证通过，正式14资产合同、serverId和21停止状态保持。[当前隔离加载](../../reports/moneyflow_p4_continuation_sample_definitions_20261017.json)与[源码/服务核对证据](../../reports/moneyflow_p4_continuation_sample_verification_20261017.json)已持久保存。先前267项原业务回归和完整受保护门禁沿用本日先前记录，本次未重复冒充复跑；没有业务字段、API/CLI参数或依赖矩阵变化。

**准确进度与下一步。** 只针对10-08、09、12～16七个成熟交易日重新只读核对七表，共49项，203次有界读取、未扫描全部历史。已完成2项（大盘10-08、10-09），剩47项/94个完整任务：大盘剩5天，其他六表各7天。7804项历史接入结果保留。已生成[剩余47项清单](../../reports/moneyflow_p4_continuation_remaining_plan_20261017.json)，SHA256 5d3da048513b7d99cd0051280f42c83bd2451182a625b1c15b9fb784d677b252，未apply；该清单及其代码证明保存于仓库reports，避免仅依赖临时目录。下一阶段按该范围接续，先各新表首日完整验收再继续同表，沿用§70的预算/原生恢复/不重发规则。当前单日步骤已收尾，没有未观察的活动资金流run；21自动更新保持STOPPED，启用及P5真实调度验证继续待办。

### 70.20 整体第一步：47项正式接续执行说明

**目标、授权与禁止项。** 用户本轮明确要求按方案继续并完成整体第一步，授权承接§70.19已列出的剩余47项/94完整任务。父清单为`lake_console/reports/moneyflow_p4_continuation_remaining_plan_20261017.json`，SHA256=5d3da048513b7d99cd0051280f42c83bd2451182a625b1c15b9fb784d677b252，47项、root_scope_digest=79c34e4ed75be094554311d6b46d29f5be11ae2d1310303a85f5f32dc39628d0。完成这一清单及独立物理/原生对账为本轮终点，21个sensor始终STOPPED；不启用调度、不进入P5、不新增成熟日期、不重跑大盘10-08/09、不补历史来源缺口，不访问Prod/BIYING、不修改其他家族、配置或重载服务。

**当前代码及影响。** 原CLI、固定七表合同、原完整job及原检查不变。执行路径为CLI→plan/verification→既有状态核对/持久请求→固定GraphQL登记及launch→原生队列→原Raw/Silver writer与checks→物理和原生验收。84份已验收资金流业务源码保持；本次开工发现`run_contracts/stock_period_silver.py`增加周/月线`resume_from_execution_id/recovery_run_id`，当前catalog只导入该模块的check_names；资金流工具、七表asset/writer/check不调用新增函数。读取实际模块及import消费者核对后，仅更新无正式凭据的隔离加载、当前113项完整依赖和737源码库存证明，旧证明/旧清单保留，不修改shared period实现。CLI仍在defs之外，不需要reload；每次新动作由原guard重新验证源码、已加载14资产/21开关、日历、实例配置、容量1、挂载/空间及无冲突写入。

**执行分段与命令。** 工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，正式DAGSTER_HOME=`/Users/congming/.goldenshare/dagster_home`。只用当前项目.venv。新源码证据与13段的scope/plan/精确SHA、正式控制请求和运行身份分别保存；每个子清单均通过CLI plan的`--parent-plan`继承同一47项root，不能新增或重置旧请求/预算。大盘5天；其他六表每表先10-08一天，独立读回完整schema、键/日期、源两轮/数量门禁/行数、摘要及精确mat/check绑定并保存表级样本报告，再处理同表10-09、12～16六天。每一日期仍Raw成功且准确绿检后才启动Silver。执行入口模板如下，实际绝对路径和摘要在开始该段前登记：

```sh
.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli plan --scope-file <本段scope.json> --output <新的本段plan.json> --parent-plan /Users/congming/github/goldenshare/lake_console/reports/moneyflow_p4_continuation_remaining_plan_20261017.json
.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli apply --plan <本段plan.json> --expect-plan-sha256 <本段实际SHA256>
```

只读准备文件位于`/private/tmp/moneyflow-full-20261017-fv3pao_e`，最终证明、13段清单/命令、表级样本与总验收持久保存至reports。正式请求及逐动作观察沿原工具保存到`/Volumes/datasource/data_lake_staging/moneyflow/continuation/<原root>`；每job候选沿原staging/run_id/dataset/date，正式文件仍只在`/Volumes/datasource/data_lake/raw|silver`，无跨日期长事务。

**性能及失败规则。** 此次47个日期、最多47次登记/94次launch、94份正式文件及各94条物化/准确blocking检查；预估220次来源请求、每层约12.8万行。47轮稳定等待合计至少47分钟，Raw活动预算上限235分钟，不含排队/整理，不给出虚假整批ETA。原单Raw64请求/300秒/每轮20000行/768MiB、SQL512MB/1线程/no-spill、每动作40读、每run120次10秒观察及20分钟、总新增32GiB/余量64GiB保持；不并行占用资金流任务。计划和汇总每命令≤400读/300秒；固定13段额外只读规划成本有界（首日1项、同表后续最多6项），不能用重复执行规避动作或poll持久预算。每段只读初始核验及每表首日读回单独记录，最终49项汇总复用有界批读，不深扫7804日历史。

中断先观察原run并使用原请求和预算接续，不重发；跨日只生成同范围、同root的剩余子清单，原授权继续覆盖，不自动扩大。原任务失败/未知响应、物理或check不一致、数量/分类门禁、相关代码/服务变化或预算超限均停止新动作、保留成功日期和现场。无关源码变化须按实际调用与加载核对后更新证明，不能擅自忽略全部shared文件；不取消其他调度，不修复或覆盖源数据来造绿检。每60秒内报告当前表/日期、实际完成数、剩余数和等待/失败原因。

**验收。** 每个新表首日保存真实来源行数、规范化/Raw/Silver行数、reject及原因、表合同/全字段转换、准确run/mat/checktarget及文件摘要。47项全部两层就绪后，独立有界核对全49项的原生唯一run/物化/通过检查、当前文件及源证明，当前接续49/49、剩0；对同根完整剩余清单再apply必须0新登记/0新job/0新来源请求。记录实际请求/耗时/读取/文件及行数、原7804日历史结论保持、所有21sensor仍STOPPED，然后完成本步方案对账。测试沿用上一轮109项及原业务/受保护门禁记录，若生产代码不变不重复声称复跑；本轮增加的是正式执行证据，不拿隔离结果替代。

§70.20执行前记录：当前隔离Definitions通过，113依赖保持；加载后改变的两个period helper不在该依赖闭包内，按原verification规则记录为无关变化，不重跑资金流采集或扩大读取权限。13段的绝对清单路径、SHA256、完整plan/apply命令已保存于[执行命令清单](../../reports/moneyflow_p4_continuation_full_20261017/execution_manifest.json)，当前源码及隔离加载证据也保存在该目录。首段为moneyflow_mkt_dc 10-12～16五日，plan SHA256=e3a083379fc08df15a4f3639feb26c091bb43a367c2b046fa3eb63edabfb72d9，执行其原CLI apply命令，首段写前guard已只读通过；准备阶段正式mutation为0。表级首日验收后才运行manifest中下一段，不把命令清单存在当作实际数据完成。

### 70.21 单次启动前失败恢复设计与继续执行

**现场事实与为何需要新处理。** 2026-10-17 18:16:15，第十一段因`moneyflow_ths / 2026-10-14` Silver原生run 656aa7d0-94c5-477e-a72e-452a48618d2c失败而退出3。引擎记录为启动RPC的`DagsterUserCodeUnreachableError`/嵌套`Stream removed`，队列标记失败后，迟到worker 3228记录“Ignoring a run worker that started after the run had already finished”并退出；当前PID已不存在。无RUN_START/STEP_START、业务物化或实际check评估，只有创建run时的计划事件。正式Silver目标及该run的Silver staging目录均不存在；原Raw run 4bc448cd-db99-4441-9c21-a2ab7f999101成功且绿检/来源证明完整，5215行，SHA256=d813d99b7739b622d358fb8cc58916c816b0c3371c93474c0bb079244e2e1fc9。当前runtime再次检查通过、serverId仍906ed8b6-8fd2-4f1f-b724-3ce491b35e69，21个sensor均STOPPED。证据：[事件及错误链](../../reports/moneyflow_p4_continuation_full_20261017/failure-engine-cause.json)、[全部末次事件](../../reports/moneyflow_p4_continuation_full_20261017/failure-last-events.json)。只能确认这次启动连接中断和无业务执行，不能凭此声称已定位底层网络断流的永久原因；目前无须重启或reload。

旧能力不能直接接回：当前DefaultRunLauncher继承RunLauncher.supports_resume_run=False，Instance.resume_run也只允许IN_PROGRESS状态，不允许将FAILED原run改回执行中。当前工具的snapshots/reconcile要求同日每层最多一个run，Journal已持久保存本次失败响应；直接多发一次会破坏原合同。§70.7明确禁止自动失败重跑，故单列本恢复步骤。管理员在收到本节具体恢复问题后表示“刚才程序暂停更新了，现在可以继续推进了”，本轮据此继续该一次恢复及原剩余范围，不扩大为通用失败重试。

**精确范围。** 只新增一次上述Silver完整任务；沿用原Raw、原日期、原七表合同与根记录目录。原失败run/status/events/request/response/poll和提交预算完整保留，不删除、不改状态、不复写旧请求。禁止Raw重采、业务步骤/质量失败重试、已有Silver文件但缺交付的恢复、源修订、任意其他failed run、任意来源/根/配置/子步骤选择、递归重试及开启sensor。恢复再次失败即停止，不能自动申请第二个run。完成后仅继续原剩余10项中的其他9日：THS个股10-15/16、moneyflow10-08/09/12～16。整体成功仍为49项，不把一次失败从历史中抹掉。

**原生请求依据及读写。** 已读安装版dagster_graphql/schema/roots/mutation.py的GrapheneLaunchRunReexecutionMutation与implementation/execution/launch_execution.py的launch_reexecution_from_parent_run；原生支持parentRunId＋ALL_STEPS＋继承父tags，可得到保留父子关系的完整job新run，不传局部asset/op/check选择，也不靠run key自动去重。候选请求已保存为[明确请求草案](../../reports/moneyflow_p4_continuation_full_20261017/proposed_silver_reexecution_request.json)，executed=False，不代表已执行。请求为launchRunReexecution(reexecutionParams:{parentRunId:"656aa7d0-94c5-477e-a72e-452a48618d2c",strategy:ALL_STEPS,useParentRunTags:true})；parent ID为String，实际query与变量须在安装schema纯验证通过后使用。新run继承原job/partition/config/标准Silver run key，parent_run_id/root_run_id明确指向原失败run，仍应恰有原asset＋blocking check两个步骤。

**参数/配置审计。** 不新增env、Settings、数据库配置或业务开关。拟在本工具明确scope/子plan增加可选`launch_recovery`描述，默认无恢复（None）；仅允许1项，字段含dataset、trade_date、layer=silver、failed_run_id、Raw SHA及有摘要的只读失败证据。字段由本次运营批准范围生成，持久保存在新子清单，不能由错误消息自动推导批准。plan/CLI负责结构、原47项范围和单次上限；state负责真实父run/原请求/步骤和文件事实；submission负责独立发送意图；execution只在描述明确且全部门槛通过时动作；inspect和最终报告保留失败事实。旧无恢复清单仍按同一合同的默认无恢复语义执行，不能悄悄将它解释成通用重试许可。依本轮继续指令生成新证据/子清单并记录准确SHA；不得修改旧47项或13段清单。

**实现位置及全消费者审计。** CodeGraph explore已覆盖CLI→plan.request_for→Journal.read/submit_once→NativeBackend.snapshots/reconcile→execution.apply/inspect及对应测试，当前代码逐项确认：

| 落点 | 必须同步的行为 |
| --- | --- |
| moneyflow_continuation/plan.py、CLI | 明确解析/验证可选恢复描述，parent子清单只缩范围；原普通计划不产生重执行请求 |
| 独立moneyflow_continuation/recovery.py | 集中单次描述验证、失败前置条件及原生完整重执行请求；不能把特殊判断散落在七个业务writer |
| state.py | 对指定父run做有界事件、原请求、终态/worker退出/无业务副作用核验；严格区分已知启动失败与唯一有效子run，其他额外/未知/部分执行失败仍拒绝 |
| submission.py | 增加固定silver_reexecution动作目录（原silver目录并列），同一47项root内独立request/send_intent/response/observation；原记录不改；按parent＋标准身份只读接回，不明响应不重发 |
| execution.py | 原记录无恢复描述时仍失败停止；有明确描述时只提交一次完整重执行，观察它并验收；成功后正常下一日期，重复调用0新提交 |
| tests/test_moneyflow_continuation_*及新的恢复测试 | 更新每个真实消费者，普通失败反例保持，新增原生父子/明确许可/不确定结果/旧日志保护/预算/字段文件合同反例 |
| 本轮只读验收工具与报告 | 对这一个日期明确报告1个启动失败＋1个成功Silver；只计真实ASSET_CHECK_EVALUATION，区分失败run的计划记录；其他48项仍唯一正常run |

不修改资产、jobs、checks、sensors、catalog、Lake字段/路径、Tushare参数、资源和全局并发，不影响Ops/Web/qtf/Prod或架构依赖矩阵。重执行仍在原CLI受控动作中，不复制旧临时正式驱动链。新底层helper及恢复分支须覆盖所有上述调用方，不允许只在最终验收时过滤掉失败来冒充完成。

**执行前门槛。** 同日Raw成功且准确绿检/当前文件/来源凭证及固定SHA保持；父run确为原Journal已发送/响应绑定的这个Silver完整任务，FAILURE、父链无已有恢复；有明确的队列启动/IPC失败和worker最终退出记录，且不存在RUN_START/STEP_START/业务物化/实际check评估、正式Silver或任何该run候选目录。原始事件查询有界，截断或不明即拒绝；不得只匹配一句错误文本。原生服务/当前源码与加载、21个停止状态、单资金流任务、日历、挂载/空间和原父范围再次核对；有任一实质变化就停止。

**身份与幂等。** 原失败记录只读保留。新固定动作silver_reexecution单独fsync请求与发送意图后仅一次POST；读回须找到唯一parent_run_id正确、继承同job/partition/config/Raw run key和完整步骤的子run，不能只选最新成功。HTTP超时或进程退出仍先读parent关联及原意图；未找到不盲重发，已有子run则只观察。该父ID只许一个子run，第三个同层run或其他父链都拒绝。NativeBackend的“同日最多1run”只对清单明确记载且证明无副作用的这一个已知失败改为“原父失败＋唯一有效子run”，在报告中完整暴露两者；Raw和其他日期仍原口径。不能笼统忽略FAILED/CANCELED。

**性能预算与失败处理。** 原47项提交上限94增加为95，仅多1次原生重执行POST、1次独立发送/观察动作及1个Silver候选/正式文件；Tushare新增请求0，Raw活动、每轮行数、768MiB RSS、SQL512MB/1线程/no-spill、32GiB新增/64GiB余量等原界限不变。新动作读≤40、观察≤120次/20分钟、每次10秒；原预算不清零，新动作单独持久计数，不把上限扩给其他日期。启动失败证据读取≤20条该run事件、≤3条同日运行，超界拒绝。重执行成功前不得继续另外9日；再次失败或未知状态保留并停止，不再造新的恢复。恢复后预期原47项94次成功任务＋保留的1次启动失败；全49项98次成功任务＋该1次失败，实际物化/通过检查仍每层49条，不增加补造事件。

**测试、验收与批准顺序。** 先确认本节及额外1次Silver提交，再进入生产Python修改。隔离反例至少覆盖：无描述拒绝、错误dataset/date/layer/parent/Raw SHA、运行未终止、已有子run、存在RUN_START/STEP_START/物化/check/候选/正式文件、原请求不符、任何非指定失败与第三run、子run只执行局部步骤、HTTP丢响应及重启接回、旧记录/预算保持、第二次调用0提交。使用本次真实事件顺序与独立字面父子身份作为fixture依据，不用待测helper生成expected；新父子链与原七表真实job/SQL/文件隔离回归分开说明证据范围，并复跑已有109项及受影响静态/隔离加载/Ruff/文档门禁。完成后刷新源码证明、生成明确恢复子清单和准确请求SHA，通过原CLI只执行1次Silver，读回同日5215行13列及全字段转换、新run/物化/精准check target和Raw SHA；只此一步通过后才接回原剩余9日并完成49项全验收与重放。2026-10-17管理员已要求继续推进，本轮先实施及验证本节，再执行这一次恢复和原剩余9日；不设置pool/reload，49项验收前不声称第一步完成。


§70.21执行前实测（2026-10-17 19:11）：恢复代码覆盖plan/CLI、Journal、NativeBackend与apply/inspect，42项新恢复测试通过；完整旧109项加首批41项恢复测试共150项通过，补充原生reconcile绑定测试1项随后通过，合计151项不同用例。临时HTTP端口及受保护启动器子进程使用工具规定的提权执行；没有以正式资源做测试。原受保护目录治理及113项静态门禁通过，项目Ruff致命基线、本次文件默认规则和文档检查通过。当前隔离Definitions加载通过，114份依赖、740份源码清单加载期间稳定，84份已验收资金流生产文件及共享moneyflow AST均保持；当前正式服务身份未变、14资产合同一致、21sensor停止，无须reload。

本轮精确四段命令见[恢复及余下执行清单](../../reports/moneyflow_p4_continuation_recovery_20261017/execution_manifest.json)。工作目录仍为orchestrator，正式DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home，CLI只读PG并通过原生GraphQL提交，写入只限原已批准Raw/Silver目标及其run staging/事件和同一控制根。第一段仅THS个股10-14 Silver，plan SHA256=e014216c4b972eeb4463cfba3ef364689b922591b9129bf9cf7e0003ebc0d603；完整命令为 `.venv/bin/python3 -B -m orchestrator.moneyflow_continuation_cli apply --plan /Users/congming/github/goldenshare/lake_console/reports/moneyflow_p4_continuation_recovery_20261017/01-ths-oct14-silver-plan.json --expect-plan-sha256 e014216c4b972eeb4463cfba3ef364689b922591b9129bf9cf7e0003ebc0d603`。当前只读plan已验证原失败全部10条事件、worker退出、5215行Raw原摘要及无Silver/候选；没有提前POST。中断仍只读接回原恢复任务，响应不明不重发；成功读回后继续其余三段，不启用sensor。


§70.21恢复结果及源码核对刷新：10-14 Silver新run 3a5b03dc-c6c1-4284-b6c0-e981e26576ea已SUCCESS；独立读回确认5215行13列、两层全字段转换/摘要和真实blocking检查target正确，原失败run仍FAILURE；本次恢复新增来源请求0。当前40/49、剩9。CLI在成功后的源码检查因catalog摘要变化退出3，未继续任何下一日期；不是恢复任务失败，不能再提交第二个恢复任务。对比当前代码及已验收commit的AST，catalog变更仅周/月线Raw/Silver的3处notes说明，资金流35节点及84份生产文件保持；不涉及资金流数据合同或调用。按§70.9重新做当前隔离加载及源码证明，生成原47项同根新只读清单和3段剩余执行清单（THS两日、moneyflow首日、其余六日）；保留本节一次恢复描述，旧清单/记录/预算不改、不启用sensor，不因无关说明文字变更重跑数据。刷新仅更新当前核验依据，执行日期、完整job、预算及一次恢复上限均保持。


源码核对刷新已完成：114份当前依赖及740份源码加载期间稳定，正式服务serverId保持、21sensor停止。新的同范围总清单SHA256=b4b01f914d89e56068e47605ac8e466f4c8f7b8650a8670b844ac23de0a46cc7；三段剩余命令见[刷新后的执行清单](../../reports/moneyflow_p4_continuation_recovery_20261017/refresh/execution_manifest.json)。先执行THS 10-15/16，清单SHA256=d8f58632ef3335855c5e3d123c2be043a0587a7385cf0fea4f495f7f99d61b9e；其后moneyflow首日及六日摘要分别为77c87df9ece4751ec14529d6f01612b08c6102625c69ff0af601c577ed004d48、89d4d1cd865e2b26b170555582f7de37773ea699d828676a29969f08d0d71681。旧执行退出及恢复成功分别记录；本次不新增恢复任务或重写旧请求。


### 70.22 最终汇总前去除重复任务查询

**目标及当前依据。** 在§70.21的同根47项只读实测中，38项完成、9项待做时snapshots已耗396次读取。state.snapshots每层已按job＋partition读过至多3个run并拒绝重复，却在有Journal时又调用reconcile，重复按同样日期读一次、按run key再读一次。全部47项完成预计450次，超过原400次上限；不能通过提高上限、过滤失败或分次清零掩盖。CodeGraph已覆盖snapshots→reconcile/validate_run、CLI plan/apply/inspect及测试消费者。此步是完成原第一步验收所需的有界读取修正，不改变业务任务及外部契约。

**实现及硬边界。** 只改state.snapshots：复用本轮已经查到的唯一run，直接用validate_run核对原Journal完整job、partition、标准run key、空配置、origin、完整步骤，再核对持久化intent和原响应绑定；两层各少2次重复查询。原submit_once中的写前/写后reconcile继续独立实时查询，不复用缓存；重复run、错误key/日期/父链、未知响应、原失败拒绝、绿检及物理文件验证均保持。单次恢复仍按§70.21完整父子核验并保留失败，不能把本优化扩展为忽略失败。预计完整47项约266次snapshots读取，最终49项含额外事件汇总仍≤400；原300秒、768MiB、动作40次及所有写入预算不变。无新增配置，无源码加载或服务变更，无正式数据写入。当前THS两日正式段结束后再改本工具，避免在运行中改变依赖导致guard中止；之后刷新当前隔离Definitions/源码证明和同范围剩余清单，不改变已提交身份及持久预算。

**测试及验收。** 新增独立字面run key/原生run合同样本，断言snapshots每层只查1次且错误key、重复run、无intent、错误响应仍拒绝；先证明旧代码的查询次数断言失败，再修正。复跑受影响状态/提交/控制器/恢复和七表隔离真实job链路、Ruff/静态/加载/文档；用正式只读快照验证读取下降和当前全部已完成日期事实保持。剩余7日沿原完整job执行；最终49项独立审计、原47项重放0新增均必须在原预算内通过。失败/中断仍保留原请求、已成功日期与预算，不放开自动重试或sensor。


§70.22开发复验已通过：旧代码次数断言实际4次、预期2次而失败，4个身份反例原本通过；修正后5项全部通过，全156项隔离回归（含原七表真实job/检查/Parquet和42项恢复测试）、原受保护113项静态、Ruff致命基线及本次默认规则均通过。当前114依赖、740源码隔离加载稳定；仍无正式Definitions、源参数、配置或业务文件合同变更。

当前THS两日已结束并独立验收，各5215行，两层共4任务/4物化/4实际绿检、来源请求12，reject0。当前总42/49，剩moneyflow7日。更新当前核对依据后的精确命令见[最终剩余执行清单](../../reports/moneyflow_p4_continuation_recovery_20261017/final/execution_manifest.json)，同根47项SHA256=3566965e64feed34092a4f32c614eacf057159f884dd9bd686a9172c1a989b70，moneyflow10-08首日SHA256=a3ee1a2fc9185f213c47a0fb194b03f12430be67ccddedfa6a842ceb3e47bb1a，余六日SHA256=73cf2c14ce03bfb6323228898b517e44381e1aec3d75f8471516108e2e36c2c9。沿原CLI按manifest执行，Python加-u只确保进度日志即时可读，不改变业务参数；正式home、路径、停止/续跑及原预算不变。首日独立读回后才继续六日。


moneyflow10-08首日独立验收已通过（19:21）：两层各5572行20列、原始与规范化全字段转换正确，来源两轮6请求、retry0、reject0，准确绿检及物化均绑定成功run。证据见[首日验收](../../reports/moneyflow_p4_continuation_recovery_20261017/03-moneyflow-first-acceptance.json)。当前43/49，依原命令清单继续10-09、12～16六日，SHA256=73cf2c14ce03bfb6323228898b517e44381e1aec3d75f8471516108e2e36c2c9；无新增范围和源码修改。


### 70.23 新发现：60秒等待边界错误及待确认的单日Raw恢复

**已证实的失败。** 2026-10-17 19:27，moneyflow10-13 Raw run ca3d12ad-717e-4291-a87f-6c2a3d37204a在真实STEP_START之后失败。原生STEP_FAILURE异常链为ValueError: sleep length must be non-negative，准确堆栈指向defs/source_readiness/moneyflow_daily.py:91。该循环先用clock判断未满60秒，经过guard（包含另一次时间读取）后又用clock计算sleep；如果刚好跨过60秒，会传入负数。第一轮Raw候选已写完，收据仍collecting，无第二轮、无正式Raw/Silver、无物化或实际check评估，故不能把第一轮直接提升或报成功。大盘采集器source_readiness/moneyflow.py:74～76存在相同实现。现有测试Clock只有sleep才推进，遗漏了代码运行期间跨过边界的真实情况；此前测试通过不能证明这个边界安全。

当前已完成45/49；moneyflow10-08、09、12已通过，10-13失败，10-14～16未执行。六日CLI已经退出3，未跳过失败日期。既有THS10-14单次Silver启动恢复已用完，不能把§70.21的批准挪用于本次已开始业务的Raw失败。下面是待确认的新修复及执行方案，未修改生产采集器、未reload、未重试该Raw。后续§70.24审计证明只修等待不足，必须一并闭合该节的恢复、进度、总时限、加载和验收要求，不能把本节初稿当成已经可执行。

**修复目标、范围与依据。** CodeGraph已审计collect_daily_moneyflow→daily_raw_writer→daily_update→六个daily Raw资产及相应测试，同时追到大盘collect_market_moneyflow独立writer。首先修正两个既存采集器的同一等待计算错误：每轮先guard，再读取一次remaining；remaining≤0直接退出，否则sleep(min(1,remaining))，再次循环仍执行取消/300秒/RSS门禁。保留两轮独立请求、至少60秒的真实间隔、分页/字段/行数/内容一致性及所有拒绝条件；不缩短等待、不吞ValueError、不改Tushare参数、配置、schema、job、check、sensor或DatasetDefinition。修复同时覆盖7表的同类缺陷，已经完成的45项不重采。

**生产代码加载及影响面。** 修改仅两个source_readiness模块及独立回归；恢复控制涉及现有plan/CLI、recovery、state、submission、execution与全部测试消费者。实现前核对当前差异和CodeGraph影响面，不能改周/月线或共享合同。修复验证后，核对无活动资金流任务，按现行code location加载流程加载当前修正源码，再刷新当前隔离Definitions、原生14资产合同、21停止状态和依赖证明；不重启DG服务，不修改并发/pool或启用sensor。正式加载的完整GraphQL请求须先按安装版schema验证并列入本节执行清单，不能以只读名义调用reload。

**单日恢复的明确输入与持久记录。** 原launch_recovery（已执行Silver）保持原值及全部证据。拟新增可选collection_recovery，默认None、最多1项，只绑定本次moneyflow/10-13/Raw父run、首轮候选摘要、完整失败证据引用；不得由错误文本自动推断批准。plan/CLI验证root范围及不可更换父run；recovery集中验证这类真实等待失败，不复用“无业务执行”的启动失败断言；Journal固定新增raw_reexecution动作目录，原raw/request/intent/response/预算及候选全部只读保留。原生仅一次ALL_STEPS父run重执行，产生新run和新候选目录，重新完成两轮下载，不复用collecting候选；原run仍FAILURE。子run须同job/日期/空配置/标准原Raw key、parent/root均指原父、完整asset+blocking check。没有批准项或未知/额外父子、第三个同层run、其他业务失败均拒绝。不能做成通用retry-failed开关，也不支持第二次恢复。新Raw成功且准确绿检/来源证明通过后，原正常Silver按新Raw摘要执行，然后才进入10-14～16。

**执行前门槛及副作用核对。** 固定父run确为原Journal已发送并有响应的完整Raw任务，终态FAILURE、worker退出，事件有界≤60条且不截断；唯一STEP_FAILURE为上述ValueError且堆栈准确指向等待计算，必须无STEP_SUCCESS、业务物化、实际check评估或正式Raw/Silver。候选只允许已核对的首轮目录、raw.parquet及collecting收据，没有第二轮验证或promotion；独立按现行20列/主键/日期审计首轮并固定摘要。此旧候选仅证明现场，不作为正式数据。原Raw已实际请求来源，缺少最终收据中的计数，必须明确已存在的成功分页数和未知重试数，不能声称请求为0或精确总请求数已知。

**预算及中断。** 原47项最大任务尝试从95增为96，仅增加本次Raw恢复1次提交；原成功目标仍94个完整任务，全49项最终98成功＋2保留失败。失败父候选和新候选均计入原32GiB/余量64GiB；由于collecting收据没有elapsed_ms，不改旧收据，按已验证事件绑定并保守占用单Raw完整300秒活动预算，计入原4小时总上限。失败请求按已有成功分页数作为下界、原单run64请求作为上界计账；新run仍≤64请求/300秒/768MiB、每轮≤20000行、等待≥60秒，预期新完整两轮6请求。新raw_reexecution动作≤40读、观察≤120次/20分钟/10秒，旧计数不清零；元数据总命令≤400读/300秒。仅明确这一个失败允许collecting证据改按上述保守计量，其他不完整收据仍拒绝。写前持久化新请求/发送意图，响应不明先读原生唯一子run，未找到不盲重发。新恢复失败即停、不递归重试；传输失败、源修订、质量或数量失败仍保留现场并停止。

**测试及验收。** 独立时钟夹具必须模拟在循环判断、guard、计算remaining之间自然跨过60秒，先证明旧代码对六表及大盘都能传负数失败；修正后断言每次sleep严格为正、第二轮请求前真实间隔≥60秒、时间未满不提前、取消/超时仍拒绝。不得让测试时钟只有sleep才走时。复跑7表采集/真实job/check/Parquet回归、156项控制回归及受影响保护/静态/Ruff/加载。恢复新增反例覆盖未授权/错父/错候选/实际业务成功或正式文件/非该错误/额外子run/部分选择/响应丢失/旧记录预算保持/失败不再重试/重复0新增。修复及加载通过后先只执行10-13完整Raw＋Silver并独立读回，成功再继续三日；全49项独立验收须同时保留2失败与2条计划但未评估的check记录，原47项重放0新增。完成前不得把45/49写成第一步完成。


§70.23只读收尾补充：独立核对已完成45项、每层105996行，共90份正式文件、90次成功任务、90条真实物化及90条准确通过检查，核验311读、原400上限保持。另保留THS10-14启动失败和moneyflow10-13等待失败，整个49项范围当前92次任务（90成功＋2失败），无活动资金流任务，21sensor仍STOPPED。详见[45项独立验收与剩余状态](../../reports/moneyflow_p4_continuation_recovery_20261017/45-partial-acceptance.json)。失败Raw首轮5574行20列、3个持久化成功分页，collecting收据无最终request/retry计数；完整成功来源收据证明200次请求，失败任务额外请求下界3、原策略上界64，整个范围当前来源请求只能报告203～264，不能伪称精确总数203。证据见[失败现场](../../reports/moneyflow_p4_continuation_recovery_20261017/moneyflow-oct13-failure.json)。此首轮未提升，既有45项不重采；新恢复问题已向管理员明确提出，尚未收到答复前不修改采集器、加载或提交新Raw。


### 70.24 剩余四日前置风险审计（先审计，不开发或重试）

管理员要求在修复之前检查未完成任务的风险，避免继续逐个碰错。本轮范围仅moneyflow10-13～16的下载、60秒核对、分页/限时/取消、Raw/Silver发布、失败任务接续、当前源码加载、查询/空间预算、45项保护及49项最终验收/零新增重放。依据为当前代码、原生失败证据、原控制记录、安装版SDK、原方案§75.16和本LLD§70.23；使用CodeGraph核对采集器→request session→writer→publication→asset/job/check，以及CLI→plan/Journal→state→execution。只读正式DG及Lake；隔离实验只用/private/tmp、假源/时钟/临时实例，原生产代码与tests不修改，不请求Tushare、不reload、不注册/重试、不启用sensor、不改周/月线。

审计单位为4日/8个预期成功job、原2个保留失败和全49项验收。正式审计每命令≤400读取/300秒、只读事件每失败≤60条、同日运行≤3条；只枚举指定4日和现有47项控制根，不扫描7804日历史。文件只校验指定候选/基线及已完成45项摘要；隔离风险实验内存≤768MiB、每用例≤20秒，最多12类场景，不联网、不用真实凭据。失败实验记录当前真实结果及独立预期，不修改实现或期待值来造通过；结论必须区分确定缺陷、尚未实现的恢复要求、已有保护、外部残余风险和未知项。结束时将每项对应到代码/实验/现网只读证据及修复验收条件，回填原方案和本LLD。若实测发现§70.23恢复设计还不完整，先补齐该设计，不直接编码。审计报告使用原本轮reports目录，原证据不覆盖；工作中断可从保存的报告接续，不触发业务任务。


**§70.24审计结论：目前不具备继续正式执行的条件。** 2026-10-17 20:40只读复核仍为45/49，90份文件的摘要/行数及成功交付全部保持。四日均为成熟交易日；moneyflow10-13只有原失败Raw，14～16无任务及正式文件。资金流任务无活动者，池容量1且空闲，21sensor均STOPPED；日历和instance配置保持，挂载及同设备正常，剩余空间约2.66TiB，超过64GiB要求。读取288次、约5.85秒、正式写入0、Tushare请求0。完整证据见[剩余风险审计报告](../../reports/moneyflow_p4_continuation_recovery_20261017/remaining_risk_audit_20261017.json)。

| 项目 | 核对到的真实问题 | 修复或继续前要求 |
| --- | --- | --- |
| R1 等待边界 | 两个采集器都可在真实走时/提前醒来后传入负数sleep；隔离实验均复现-0.00015秒 | 每轮guard后只计算一次剩余时间，到点退出，否则只等正数；两处同时修，测试覆盖自然走时、提前醒来、取消及预算，等待仍至少60秒 |
| R2 Raw失败接续 | 现工具只允许指定Silver启动恢复；直接再启动Raw会被判重复。同一控制根读失败collecting收据时，disk_budget已只读复现raw_activity_proof | 全部plan/CLI、父子识别、Journal、提交/观察、状态流转和磁盘/活动预算同时迁移；只恢复指定10-13 Raw；失败预算保守300秒，旧记录/候选不改。新Raw成功必须进入普通Silver，不能误走Silver恢复的“完成”分支 |
| R3 进度和只读状态 | 先完成1项、后失败1项的独立样本，apply返回完成0/剩2；inspect直接抛异常，无法看到逐项事实 | 先统计已ready事实再决定停止，失败仍禁止提交；inspect保留全清单成功/失败/待做事实和明确错误退出码，不能因为一个失败把已完成进度清零 |
| R4 请求总时限 | 安装版SDK的timeout=30是连接/读空闲超时；300秒检查只能等阻塞调用返回后执行，不保证到点结束。慢速分块本地假源以0.1秒timeout执行约0.277秒仍成功 | 先补完整的资金流专属总截止时间及取消设计，再实施。需能终止进行中的请求并释放资源；不能只改大timeout、用仍在后台跑的Future替代，或擅改全项目TushareResource/global配置。所选机制、平台/线程限制、进程或连接成本及资源释放必须验证，本轮尚未选定/实现，不得声明300秒硬终止已具备 |
| R5 当前加载依据 | 当前serverId为1dee22e1-cff8-4af2-8195-f70354f9c35a，旧证明为906ed8b6-8fd2-4f1f-b724-3ce491b35e69；114份依赖及源码成员均未变化 | 修复后重新核对当前源码与加载，刷新隔离Definitions和正式14资产/21停止状态依据；不得因标识变化盲目reload。确需加载修正源码才按授权加载一次；保持原完整47项parent/root，生成剩4日子清单，跨午夜只刷新同范围，不重置原预算 |
| R6 最终验收 | 当前只读验收脚本只识别原Silver父失败；增加Raw恢复后，重复run及计划检查会再次被判错。不能靠临时脚本跳过失败冒充完成 | inspect/实际验收/重放统一识别两组明确父子。全49项预期98成功任务＋2保留失败=100任务，98份正式文件/物化/实际通过检查，2条“计划但未评估”记录单列；不得删除父失败或把计划记录算实检。验收逻辑和命令保存进现有受维护入口/证据，不只留在/private/tmp |

**测试及证据边界。** 新增审计实验未改生产代码或仓库tests：两种采集器的时间边界均复现；一项已完成+一项失败的进度错误复现；inspect失败丢逐项事实复现；丢HTTP响应的独立替代原生边界实测仍只有一次POST及一个原run。另用现有独立真实5572行公开夹具、跨页/尾页、同量内容变化、取消/预算、hash和逐文件提升/接回等37项针对性隔离回归全部通过。它们证明现有保护，不证明尚未实现的Raw原生父子恢复。特别是原test_exit_after_replace_resumes_without_source_or_rebuild保持operation_id=resume直接调用helper，不能据此声称更换Dagster run ID后的整条链已验收。

R4的官方依据为[Requests超时文档](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts)，本机Tushare1.4.29/Requests2.34.2源码也已核对。HTTP实验仅127.0.0.1、无效测试token、单次假请求，未访问Tushare或正式资源。隔离实验见[边界结果](../../reports/moneyflow_p4_continuation_recovery_20261017/remaining_risk_isolated_probes_20261017.json)及[慢响应结果](../../reports/moneyflow_p4_continuation_recovery_20261017/remaining_risk_http_timeout_20261017.json)。测试失败场景按现行代码原样记录，没有改预期或实现凑通过。

**本轮修复应合在一次完整交付中。** 复用已有原生重执行、Journal及受控提交能力，不再复制第二套正式执行器/临时writer。配置继续沿现行来源；若总截止时间设计需要新增或改变参数，必须先补默认、持久化来源、全部消费者、生效范围及测试，不得散落脚本和常量。R3只改变观测完整性，绝不能放开任何失败后的写入。R6不可只改报表，须与真实父子/文件/check合同同迁移。上述实现均需沿原方案确认后开展；本轮没有编码或提交正式任务。

**修复后的整段隔离演练。** 在临时资源中一次走完“45项已完成保持→原失败Raw及首轮现场→一次显式新Raw→新Raw准确绿检→普通Silver→后续三日→全49项验收→原47项重放0新增”。至少插入：发送后丢响应、控制器退出接回、已完成项后遇失败、错误父链/候选/部分步骤、观察超时以及慢速HTTP总截止时间。新Raw恢复不得调用旧Raw提交目录或旧动作预算，不得直接记complete；普通提交的写前/写后独立原生核对不省略。最终report必须有成功、保留失败、未执行和来源请求未知范围，不能用“统计0”掩盖错误。此整段通过才允许正式恢复；正式先仅10-13读回，再10-14～16，保持原顺序。

**成本和后续中断规则。** 剩余4个日期，最多新增3次日期登记、8个成功job/8份文件；预计正常24次来源分页请求，硬请求上限仍每Raw64、四日总新增≤256，不计原失败任务未知请求。Raw总活动预算仍4小时，旧失败按300秒保守计入；SQL512MB/1线程/no-spill、进程族内存768MiB、总文件32GiB/余量64GiB保持，R4新增资源成本未测完不得认为预算通过。每动作40读、观察120次/20分钟（包含排队）、全命令400读/300秒不增加；最终49项及新增Raw父子分支须实测在此上限内，不能分次清零规避。控制进程退出不取消后台任务，先找同一run接回；已批准原范围内控制接回、只读证明刷新、跨日同root子清单刷新不重复请求业务批准。真正源内容不一致、20%下降、文件/检查不一致或新的未授权业务失败仍停止，不能为减少暂停而吞错。

10-13已只读审计前五来源日，行数中位数5572，首轮5574未触发行数下降；但第二轮与14～16实际返回尚未请求，不能提前宣称源端全部可用。旧Silver历史恢复还用数字PID检查进程是否存在，未来PID复用可能造成误报；当前未触发，最终验收用例需区分已完成交付事实和无关PID，不能引入广泛进程管理功能。外部断网、服务退出、真实源修订和文件发布后未形成原生交付等无法靠本次审计保证不发生；后者须独立处理，不能把现有逐文件checkpoint等同于任意原生失败可自动恢复。

### 70.25 剩余四日的完整修复设计（开发前记录；实现结果见§70.26）

#### 70.25.1 目标、依据和禁止项

本节对应原方案§75.18，按管理员本轮“先完成方案和LLD，再开始修复代码”的指令编写。它完成技术选择和开发约束，不表示管理员已经批准新Raw恢复或源码加载，也不是实现/正式验收报告。§70.24中“总截止时间尚未选定”是当次审计事实，现由本节明确；原风险报告不改写为通过报告。

最近一次正式只读证据为2026-10-17 20:40：45/49完成，两层各105996行，90份文件/成功任务/物化/实际通过检查；保留2次失败。剩余仅`moneyflow / 2026-10-13、14、15、16`。本轮写文档不重新读湖、不调用源端。执行范围固定到这四日；两处采集器修复覆盖同类缺陷，但不重采其他六表或已完成45项，不处理历史缺口，不扩到新日期，不启用21个sensor，不进入P5。源接口字段、分页、日期、schema、asset/check/job名称、run key生成口径和并发配置保持。

依据包括当前两个source_readiness采集器、`resources.TushareResource.call`、`tushare_request_policy._BoundedRequestRunner`、两套Raw writer/update/publication、`moneyflow_continuation`及CLI、原生失败事件、四份remaining_risk报告和当前安装版Tushare1.4.29/Requests2.34.2。CodeGraph本轮使用`codegraph_explore`核对`effective_runs`、`disk_budget`与控制入口影响面；索引未完整给出的动态resource调用、临时验收脚本和SDK边界以当前代码补查。无Foundation/Ops/Biz/QTF或前端消费者，不改变主体依赖矩阵。

#### 70.25.2 硬口径与实现位置对账

下表是后续开发清单；所有“修改/新增”均指待开发，不能读成已经实现。路径相对`lake_console/orchestrator/src/orchestrator/`。

| 硬口径/风险 | 真实实现位置及待改动 | 必须取得的证据 |
| --- | --- | --- |
| R1 60秒核对间隔不能缩短、sleep不能负数 | `defs/source_readiness/moneyflow.py`、`moneyflow_daily.py`；循环每次先guard，单次读取`remaining=60-(clock()-first_end)`，≤0退出，否则sleep(min(1,remaining)) | 两处旧实现均被自然走时/提前唤醒反例抓住；修后间隔≥60，sleep>0，取消/预算仍拒绝 |
| R4 来源请求必须可停止 | 新增`defs/source_readiness/moneyflow_transport.py`与`moneyflow_request_worker.py`，仅上述两个采集器显式调用；`defs/io/moneyflow_daily_update.py`及`moneyflow_mkt_dc_update.py`传下原Raw截止点；共享`resources.py`及`tushare_request_policy.py`不改 | 同安装版SDK的真实本地慢分块、阻塞、取消、崩溃和退出试验；无遗留请求进程；参数/返回及原重试分类一致，预算不重新起算 |
| R2 只恢复指定Raw一次 | `moneyflow_continuation/plan.py`、`recovery.py`、`submission.py`、`state.py`、`execution.py`及`moneyflow_continuation_cli.py`统一接受新说明、识别父子、选择动作、计账、接回 | 原生ALL_STEPS完整job父子、独立控制记录/预算、新目录/两轮、新Raw→普通Silver；所有未授权反例拒绝 |
| R3 失败不能抹掉完成数 | `execution.Progress/apply/inspect`及CLI退出码转换；`state`逐项采集时保留可读事实和错误，写入判断继续严格 | 字面“一项完成、一项失败”应为1/2及原因，未读事实不得算待做；失败退出3，POST=0；心跳不伪造业务进度 |
| R5 只用当前代码与加载依据 | 现有`state.verification/guard`、`plan.make_plan/validate_plan`及原报告生成流程 | 改动依赖全部纳入当前证明；隔离Definitions通过；正式加载与14资产、21停止状态绑定；跨日不扩范围/不清预算 |
| R6 真实交付与两次失败一起验收 | 新增`moneyflow_continuation/acceptance.py`只读汇总，由原CLI增加`audit`子命令；复用`state`身份、文件SQL和父子识别，不复制正式提交器 | 49项98成功＋2失败、98实检和2计划未评估分开；47项重放零新增，错误父/额外任务仍拒绝 |

新增模块只承载上述稳定职责，不另造正式执行脚本。现有`defs/assets/moneyflow.py`与check/job/catalog/sensor合同保持不变；两个update只增加原Raw截止点向下传递，writer通过已有collection_options转交，候选验证、唯一writer锁、逐文件checkpoint及原子提升不变，不搬到请求子进程。源请求合同没有修改，本步不为了修复再次访问Tushare进行资料探测。

测试消费者必须同步迁移：现有七个`tests/test_moneyflow_moneyflow*.py`、`test_moneyflow_row_count.py`及相关定义/sensor用例，`test_moneyflow_continuation_{plan,state,submission,execution,recovery,cli,integration}.py`，已有只读验收报告生成逻辑。运行前用当前`rg --files`确认路径，不按历史测试清单猜。新增传输/Raw恢复/验收测试按职责命名；原受保护启动器不修改、不绕过，不能恢复已清退的文件白名单。

2026-10-17开发授权及低成本隔离约束：管理员已要求提交方案后按本节修复和隔离演练，正式加载/恢复仍不在本轮范围。旧采集/文件/job测试继续使用原假源；在`tests/conftest.py`登记一个非自动fixture，只由明确标记的资金流测试使用，显式替代请求传输层，避免旧假源用例每页启动进程。真实传输测试不使用该fixture，单独以本地SDK/HTTP验证；整段控制演练先用极小字面状态覆盖49项和两个父失败，新增4日再用小型真实Parquet/job链核对，不能为凑数量重复生成45项大文件。只对受影响回归做一次完整运行，失败修复后只重跑受影响项；最后统一静态/加载验收，不重复全仓测试。

#### 70.25.3 可停止请求的技术选择和边界

**选择及理由。** 每次真实HTTP尝试启动一个资金流专用请求子进程，串行执行、结束后回收，最多同时1个；不建跨日期常驻服务或进程池。父进程仍执行现有采集器、60秒等待、分页及request session，子进程只用已解析token重建现行`TushareResource`并调用其`call(api_name,params,fields)`。每页数据返回后，仍由原writer校验、写候选和核对两轮；子进程无正式路径或instance输入，不负责业务发布。保持外层64次尝试/普通错误至多3次重试和原退避，不在子进程再加重试。

不选线程Future，因为超时返回不能结束仍在请求的线程；不选在Dagster处理进程设置SIGALRM，因为它占用进程级信号、只在主线程执行Python处理器且长C调用可能延迟处理。独立子进程允许操作系统直接结束网络/DNS/解码，不用等SDK自己返回。Python[信号文档](https://docs.python.org/3.13/library/signal.html#execution-of-python-signal-handlers)、[子进程文档](https://docs.python.org/3.13/library/subprocess.html#subprocess.Popen.communicate)与[Requests超时文档](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts)是机制依据；当前安装版源码已确认普通timeout只是连接/读空闲上限。设计只支持当前macOS和经测试的POSIX环境；能力缺失在首次HTTP之前明确拒绝，不静默退回无截止时间的旧调用。

**计时。** 全部采用单调时钟。两个update在现有`started=perf_counter()`处派生`raw_deadline=started+300`，作为内部collection_options经原writer传给采集器，不能由CLI/resource/env配置覆盖。采集器独立调用时以自身开始时间+300为上限；进入正式update时取传入截止点与自身上限的较早者。原Raw预算不重置，传输每次从该固定截止点取剩余值。发起前仍预留原30秒：剩余≤30秒直接`request_budget_exceeded`，不创建新请求。单次30秒从创建子进程之前计起，包含启动、SDK调用、IPC接收及回收；最后2秒留给结束进程。SDK本身仍按现行空闲timeout工作，但子进程的工作截止点是`min(单次开始+28秒, Raw截止-2秒)`，不存在网络持续滴流就延长的路径。完整响应也必须在该点之前收齐、合法且子进程正常退出，否则不能返回成功页。

到工作截止点：发TERM，最多等1秒；仍未退出则KILL，最多再等1秒，确认回收后抛非重试的`MoneyflowContractError("source_total_deadline")`，这一Raw停止。不能把本地强制截止包装成可重试socket错误。取消优先级高于超时：父进程每≤0.1秒检查现有`check_cancel`，原样传播取消，在finally关闭通信端并结束/回收自有子进程；不改Dagster信号处理。结束失败则`source_worker_cleanup_failed`并停止整个接续，不释放后启动新请求。成功页、普通源错误、取消及异常都必须走同一finally。

这里保证的是进行中的网络请求不会因SDK空闲超时语义而无限占用处理进程，并在预算内开始并完成正常OS下的终止流程；**不声称操作系统进程创建、磁盘fsync、不可中断内核I/O或整台机器停顿能被Python精确限在300秒内**。原Raw的SQL/文件边界检查仍有效；若终止确认超过预算，报告实际超时并停止，不能报成功、调大预算或领新任务。20分钟控制器观察上限只限制观察，不是取消后台任务的依据。

**通信与保密。** 使用标准库`subprocess.Popen`和非阻塞管道/`selectors`，固定当前项目解释器、`shell=False`、`-B`，仅运行内部worker模块。请求正文经stdin传入，≤64KiB，只含已解析的token、API名、白名单业务参数、显式fields及截止点；未解析EnvVar或空token在创建请求前拒绝，token不得进argv、日志、报告或临时文件。只有非敏感的单调时钟工作截止点通过内部argv传入，使子进程启动后即可设OS计时器，随后与输入正文核对相同值；不是新增运营参数。子进程环境移除正式DG/Prod数据库凭据和TUSHARE_TOKEN，只保留解释器所需环境及当前请求实际使用的代理/证书环境，不新造网络配置。白名单API只含本七表，日期/分页/fields仍取现行合同，禁止任意URL/任意callable入口。新模块被Definitions发现导入时仅定义函数/类，不启动进程、设信号、读取token或访问网络；worker执行仅限内部main入口。

stdout只有一次长度受限的结果帧：8字节无符号大端body长度、有界JSON body、8字节无符号大端子进程峰值RSS（bytes），合计≤32MiB。子进程发送完body后用RUSAGE_SELF读取自身峰值再发送尾部，父端须收齐并确认正常退出；缺尾部不能接受。父进程按≤64KiB分块非阻塞接收，每块之间检查截止、取消及资源，不得在poll后直接调用可能无限阻塞的整帧recv。stderr不直接传播SDK栈或请求正文。结果为现行columns/rows/metadata的有界JSON；Decimal沿用现有writer的十进制字符串序列化，非有限数字和错误类型仍交原合同拒绝，不能转成NULL/0；不得通过传输补缺列或重排字段。超长/截断/多帧/非法结构直接拒绝，不把其视为空页。单次返回后才发下一页，无预取，无累计全日期数据。

子进程在导入SDK前用系统默认终止动作的`SIGALRM/setitimer`设定自己的工作截止时间；不是在父进程装Python信号处理器。stdin读完一条输入后保持连接，由一个仅监测父端EOF的守护线程在父进程消失时退出该请求进程；即使该线程受阻，子进程自己的系统计时器仍限定其生命周期。正常父进程始终负责wait回收；子进程不得派生下级进程。父进程被强杀后的实际退出时延列入隔离验收，不宣称父进程被强杀时还能同步写完整来源收据。

**错误合同。** 子进程将普通SDK异常先用当前`classify_tushare_error`归类，只传category/retryable及脱敏错误类型，不传token或完整原异常。父进程按固定类别重建可被现行分类器识别的异常：合同错误→ValueError，非重试错误→PermissionError，权限/参数→状态403的HTTPError，限流→429，暂时错误→503，非标准响应→TushareResponseError；逐类断言父端分类与原category/retryable完全一致。未知类别、矛盾retryable或worker非正常退出均非重试拒绝，不猜源错误。纯socket超时/断网仍按原策略处理，强制总截止和取消不能重试。共享分类器不加资金流特例。

**资源及测试接缝。** 进程成本计入原预算：父进程和当前自有请求子进程RSS合计≤768MiB，退出后另记子进程峰值；不能各给768MiB。利用当前POSIX的`/bin/ps`只读取这两个确切PID的RSS（无全系统枚举、无终止无关PID），该本地调用超时复用0.1秒poll限值，首次及至多每1秒采样，前后均检查取消/截止。仍活着却读不到有效值即拒绝；若已确认正常退出且完整结果在手，按尾部峰值核验，不把正常PID消失误报成内存读取错误。回收后以现有resource.getrusage的父峰值加该child自报峰值作保守核验（macOS/Linux单位按现有helper一致换算），超过总预算拒绝该页；不是把各页子进程峰值相加。异常退出、没有峰值尾部或尾部值不合法均不得接受该页，不得把取不到的RSS按0计。通信超限同样结束自有请求、停止本Raw。采样不是内核级内存预留，短时分配峰值仍需上述退出核验和独立隔离实测；不安装psutil或改全机限制。资源证据写本轮开发/运行日志，原收据peak_rss_bytes含义不改、不伪填为进程合计。请求不落临时页文件，原staging页、候选和收据仍由writer统一管理。

单元测试可显式注入请求函数，必须注明绕过了传输边界；生产默认只能走上述worker，不得按“对象不是TushareResource”自动转同步调用。传输集成测试用无凭据、仅监听127.0.0.1的真实慢响应服务和安装版SDK；仅测试夹具可替换worker内部SDK地址，生产入口不接收URL。七表隔离job用明确的假源覆盖文件链，再以独立传输集成连接这两个边界；不得声称mock job已经证明真实网络截止。现有源码/测试和原受保护启动规则若不能支持该边界，先报告并修订设计，不绕过启动器。

#### 70.25.4 配置审计与性能预算

所有值集中在现有`defs/run_contracts/moneyflow.py`（采集）与`moneyflow_continuation/contract.py`（控制），不在脚本/页面复制；不新增env、配置表、resource参数或UI开关。新增的是资金流内部固定限值，进入源码依赖摘要，随下次代码加载生效。来源token仍是现行TushareResource已解析配置；不持久化到控制记录。

| 配置名/来源 | 值及作用 | 消费者、生效及测试 |
| --- | --- | --- |
| 现有MONEYFLOW_REQUEST_TIMEOUT_SECONDS / MAX_ELAPSED_SECONDS | 30/300秒，值保持；从“请求前预留”落实为传输也执行该上限 | 两个采集器、writer/update、专用传输；截止点/启动成本/取消/重试累计测试 |
| 新MONEYFLOW_WORKER_CLEANUP_SECONDS | 2秒，包含在原30/300内；TERM和KILL各最多1秒 | 仅专用传输和worker；到点回收、失联、无法回收测试；不计成可额外放宽的时长 |
| 新MONEYFLOW_WORKER_POLL_SECONDS / RSS_SAMPLE_SECONDS | 0.1/1秒；分别为取消/截止检查和确切PID内存读取间隔 | 专用传输；无忙轮询、取消延迟、PID退出竞态、RSS读取失败测试 |
| 新MONEYFLOW_WORKER_INPUT_MAX_BYTES / RESULT_MAX_BYTES | 64KiB/32MiB；单页IPC上限，最多持有当前页；不累计两轮 | 专用传输和worker；边界长度/截断/非法帧/内存测试；超限拒绝不截短 |
| 现有来源策略 | 页2000、每轮20000、每Raw64尝试、间隔60秒、原重试/限流/退避 | 两个采集器及原session；新增worker不自行重试，调用参数与普通错误分类对照 |
| 现有SQL/空间/RSS | 512MB/1线程/no-spill；进程合计768MiB；总32GiB、余量64GiB | 原SQL/writer/guard及传输；失败父候选与新目录均计入，不加备份/快照 |
| 现有控制上限 | 清单/审计400读/300秒；动作40读；观察120读/1200秒、10秒间隔；每unit最多5次转换；Raw累计4小时 | 原meter/Journal/guard；失败父保守300秒，新恢复单独计数并总计；续跑不清零 |
| 新collection_recovery，清单JSON | 默认None、最多1个明确说明；不是环境开关，不自动开启 | plan/CLI/recovery/Journal/state/execution/acceptance；新清单产生时生效，逐项身份验证，见下一节 |

剩余四日最多新增3次日期登记、8个成功job、8份正式文件；正常预计每Raw两轮各3页，即共24次来源请求，单Raw仍≤64、四日新增总≤256。每尝试最多1个串行子进程，正常24次启动、硬上限256次，不在等60秒期间保留请求子进程。启动/IPC/退出单页额外成本验收目标≤2秒；正常样本每Raw预期60秒等待＋6页网络/进程/校验成本，目标≤120秒、硬拒绝仍300秒。目标值是待测预算，不是实测结论；不达目标先分析，不得调大硬上限。新增消息、结果和两进程峰值均纳入768MiB实测。

最终49项限定这7个交易日做文件/事件复验；不读7804日历史明细，不读取Prod。现有45项验收作为前后对照；最终严格文件SQL复验沿现有`NativeBackend.audit`，不以旧报告直接替代当前文件事实。预计查询在原311次45项验收基础上增加4日及父失败核对，仍必须≤400/300秒，实测超限不能拆命令清零规避。根规则的全数据集读取审批继续适用；本设计没有批准全历史扫描，若实施出现该需求，先说明必要性/范围/成本并取得批准。

#### 70.25.5 指定Raw恢复说明、父子身份和计账

新清单仍用format=1，在现有可选说明中增加`collection_recovery`；缺省规范化为None。历史不可变清单和原Journal不重写；新清单和CLI消费者同步校验此唯一语义，不另开第二种正式执行模式。原`launch_recovery`逐字继承，不替换已验收Silver说明。Raw说明固定字段如下（摘要须取现有证据计算，不手工捏造）：

```json
{
  "dataset": "moneyflow",
  "trade_date": "2026-10-13",
  "layer": "raw",
  "failed_run_id": "ca3d12ad-717e-4291-a87f-6c2a3d37204a",
  "first_round_sha256": "63739fcb41a8fc65f198b4933199c0352435730b78bd2b6be670cfa1a24a83b4",
  "evidence": {"path": "原失败证据的仓库绝对路径", "sha256": "生成清单时计算的64位摘要"}
}
```

上面的evidence占位是结构说明，不是可执行输入。实际引用原`moneyflow-oct13-failure.json`，路径必须通过原safe_path/报告目录约束、≤64KiB，读取前校验SHA；仅取脱敏必要字段比对，不另造无来源证据。必须只含这些字段、UUID/SHA格式正确、unit属于原root；首次增加必须来自原47项完整父清单，之后父清单已有说明时只允许原样继承。父清单过期仅可用于证明旧范围/身份，不可apply；新执行子清单须当日有效。

原根SHA/范围以原47项清单为准：root_scope_digest=`79c34e4ed75be094554311d6b46d29f5be11ae2d1310303a85f5f32dc39628d0`。先从完整47项parent建立包含两份恢复说明的新完整47项清单，再派生13日、14～16和剩4日清单；不能从4日parent反向扩回47日。控制根仍为原`.../moneyflow/continuation/<root_scope_digest>`。所有旧请求/意图/响应/观察预算、父失败及首轮文件只读保留。

仅对此Raw，recovery确认：父任务为原Raw Journal拥有、原响应绑定的完整任务，FAILURE且无父链；≤60条完整事件（读61条以探测截断），确有RUN/STEP开始、唯一STEP_FAILURE对应负数sleep的ValueError及准确模块/语句、worker结束；无STEP_SUCCESS、物化或实际check评估。首轮5574行20列、3页及摘要与原证据一致，receipt仅collecting，第二轮/verification/promotion/正式Raw/Silver均不存在。错误类型或文件/事件现场不匹配立即拒绝。首次重执行前检查父worker已结束；只管理本次拥有的worker，不使用无关PID存在性判定已验收交付失效。

Journal新增固定动作`raw_reexecution`，与原`raw`、`silver`和`silver_reexecution`分开；动作到物理层显式映射，不能靠“不是raw就当silver”。复用现有`launchRunReexecution(parentRunId, ALL_STEPS, useParentRunTags:true)`，提交前后仍独立查原生唯一性。新run必须同job/日期/空配置/完整asset+blocking check，parent/root指原Raw，继承原Raw run key（包含原尝试日期，跨午夜不得按新日期重造key）。只允许一个这样的child；普通同层最多1run，只有这两个指定恢复层可见1父＋1子；第三个、无说明的重复run、错父、错key或部分步骤全部拒绝。

生产者路径校准：`moneyflow_daily_raw_writer.consume_page`实际写`round-1/scope-1/page-{offset}.json`，本次moneyflow只有scope-1；旧失败报告的file字段只保存页文件名，不含scope目录。恢复必须按这一真实层次核对唯一scope-1及0/2000/4000三页，不能按文件名反推它们直接位于round-1。以真实writer先写完首轮再中断的隔离样本验证该边界。

disk_budget按run去重统计原失败目录与新目录，按物理target去重统计文件；`raw_reexecution`必须走Raw来源收据/目标而非Silver。仅已验证的本次失败父collecting收据允许保守占用300秒；其他无elapsed_ms收据仍`raw_activity_proof`。新Raw用自己的最终elapsed_ms，并保留原4小时累计上限；控制转换仍最多5次/unit，本次13日为Raw重执行＋Silver两次，不因新增动作扩大上限。原47项94成功任务＋2失败最多96尝试；整个49项最多100，新增恢复再次失败即停，不能递归加次数。

开发前成本细化：原失败5574行候选的独立SQL核对在每个控制命令首次识别时完成一次；同一backend实例后续提交前/后的重复识别，必须仍重读父事件并重核证据、候选、三页及收据摘要，只有这些输入和unit均完全相同时才复用本命令已通过的SQL结论。缓存最多一个明确父候选，不跨进程、不写控制记录；任何摘要/范围变化即重新校验或拒绝。这样避免把同一旧候选重复SQL扫描挤入40读动作额度，正式新Raw/正常提交的前后独立查询、来源两轮和文件验收均不省略，预算不增加。

成功45项最终收据证明200次来源请求，旧失败只能证明3～64次，因此当前203～264；后续成功4日若各6次，则完整成功收据共224，整体227～288，实际须用新收据重算，不能预填。保留未知区间，不根据新run成功去补造旧父请求数。worker异常导致新收据不完整时同样报告未知，不伪报0；该新失败不在本次可恢复授权内。

#### 70.25.6 状态转换、进度与续跑

1. **只读识别现场。** unit先取完整可读事实，再计算完成数；一般FAILURE仍阻止写入。指定父失败保留在`preserved_failures`，不混入当前有效child；未知失败保持blocked。`next_action`不在读取成功事实之前抛出并清空整个结果。
2. **Raw重执行。** 新动作有独立request/send_intent/response和持久预算。无child且无发送意图才能提交一次；有意图却响应不明，先查同父唯一child，有则接回，没有则明确uncertain并停止，不能盲目重发。

   响应确已丢失时，原HTTP response文件继续缺省，不能伪造响应补齐记录。最终验收以原request/send_intent绑定、唯一原生读回、正确父子/完整job及准确交付共同证明该动作，并单列“HTTP响应丢失、原生读回确认”；不能让执行器已经支持的接回在验收时报成缺response。若response存在仍逐字绑定run；没有意图、错原生身份或没有唯一child继续拒绝。
3. **接回观察。** 已有自有child只观察同run、原started_at/读取次数保持。控制器退出不取消后台任务；额度用尽/20分钟到点停止新增操作，不按新清单日期重置额度，也不自动取消任务。原生取消沿现有Dagster机制，资产check_cancel负责清理请求worker。
4. **Raw交付。** child SUCCESS仍须物化/准确绿检/新Raw来源收据/文件摘要一致才算Raw ready；之后动作必须是普通`silver`，以新Raw摘要生成原标准请求，不能套Silver恢复的完成分支。child再失败、文件已发布却无完整原生交付、质量不通过等均停止，不再造第二个child。
5. **完成及后三日。** 普通Silver成功且文件/check绑定新Raw才完成13日，独立读回后按14→15→16逐日执行。每日前五来源日基线当时再核对，保留20%下降拒绝；不跳过13日或用未验收候选构造基线。
6. **已完成恢复的验收。** 旧Silver与新Raw各自的原父退出事件、固定证据和父子关系保持验证；一旦已有准确child SUCCESS交付，不再用历史数字PID是否被别的程序复用否决它。首次提交child前仍要求原worker结束；未知/实际活动同job保持拒绝，不因PID误报问题而删除并发保护。

Progress保留现有字段，增加`remaining/blocked/unknown/preserved_failures`等可核验汇总及当前dataset/date；完成数只来自两层ready事实，与是否准备提交分开计算。`inspect`逐项返回完整成功/失败/待做/未读事实与原因，发现业务阻塞退出3，输入错误2，停止130、观察超限4沿用原值；原先“未完成但正常待做”的inspect仍退出0。读取本身出错时将该unit标unknown，不能假称无任务或未开始；全局证明无效仍禁止执行。不得catch所有错误后继续写入。进度至少每10秒可见，心跳只更新reported_at；last_actual_progress_at只随真实任务/日期/阶段推进变化。

#### 70.25.7 受维护的只读验收和精确执行顺序

R6只扩充原工具，不再依赖`/private/tmp`中只认识旧Silver失败的脚本。拟新增的只读命令为：

```text
工作目录 /Users/congming/github/goldenshare/lake_console/orchestrator
解释器 .venv/bin/python3 -B -u
模块 -m orchestrator.moneyflow_continuation_cli
audit --plan <当前有效完整47项清单> --expect-plan-sha256 <实际SHA> --output <新报告绝对路径>
```

此行是设计时的CLI合同；当前已在§70.26实现并隔离验证audit，但**占位命令仍不可执行，不能当成已批准的正式命令**。audit从明确47项及已验收大盘两日组成49项，逐项`unit_identity`去重校验；只按既定7日期查询，不扩大root、不写Journal/动态分区/事件/业务文件、不POST mutation，仅创建新本地报告。报告输出不得覆盖旧证据。复用`NativeBackend`的批量readiness、准确check与文件SQL、统一父子识别；保留独立的字面目标计数与SQL聚合交叉检查，不能只把`next_action==complete`当成物理验收。snapshot原重复查询优化保持，正式提交的前后独立核对不省略。

最终报告必须包括：每unit两层文件路径/hash/行数/主键/日期/全字段转换/来源和发布依据，成功run/原父/child与实际check引用，按身份去重的全49和原47计数、2条计划未评估检查、来源请求精确部分和未知区间、21停止状态、当前版本/源码/加载依据、读取/耗时/RSS及正式副作用计数。49项目标98成功＋2失败=100run；98文件/物化/实际通过检查，2计划未评估单列。90份已验收文件和原收据须与45项基线摘要相同。失败或未执行报告完整现状，不得把目标数写进实际结果。

开发及隔离验收通过后，顺序固定：

| 顺序 | 动作与准入 | 输出/停止条件 |
| --- | --- | --- |
| 1 | 核对本步代码/文档/测试，取得设计确认后开发，整段隔离演练及全部门禁 | 记录实际通过及未覆盖边界；未通过不加载、不正式恢复 |
| 2 | 核对当前源码/配置/正式加载、资金流及共享code location的活动/排队任务；确需更新修正模块且获授权、确认不会干扰正在使用该location的任务后才加载一次 | 原schema验证的reloadRepositoryLocation请求和完整工作目录/home/范围填回执行清单；有冲突等待/报告，不取消别人的任务、不重启服务、不启用sensor |
| 3 | 隔离Definitions/114依赖基线（以当时实际新增依赖数为准）/14资产/21停止状态刷新，从完整47项parent生成完整及4日子清单 | 新SHA、当日有效期、原root/旧预算和两份恢复说明；不得复用过期SHA或虚构当前serverId |
| 4 | 满足此次Raw恢复批准后，原apply只处理13日，原生Raw child→普通Silver | 新两层准确读回、旧5574行首轮保留、45项未变；失败即停 |
| 5 | 13日验收通过后，按原范围依次apply14～16，每日读回 | 最多3登记/6普通job；不跨缺口 |
| 6 | 当前完整49项audit，然后原47项apply重放并前后比对 | 0新增登记/任务/物化/实际检查/来源请求/正式文件改变，保留两个失败；形成第一步收尾记录 |

步骤2～6届时沿原本轮reports目录保存精确输入JSON、绝对路径、SHA和命令，并填写`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`、现行GraphQL和正式Lake/staging根；当前没有未来源码摘要或新清单，故不编造值。正式加载和Raw恢复不能用本轮文档指令代替阶段批准；原范围内纯只读证明刷新/控制接回不重复索要已有授权。跨午夜重新生成同root/同unit子清单、保留预算；不得借日期过期重跑已绿Raw或改run key。未来新增真正业务失败应另行审计，不能用本节自动放行。

#### 70.25.8 测试矩阵和证据独立性

| 组 | 最小正向与反向样本 | 通过条件/证据边界 |
| --- | --- | --- |
| 等待 | 两个采集器，时钟每次读取自然前进、guard跨点、提前唤醒、刚好到点、等待中取消/300秒到点 | 旧实现复现负数，修复后无负数、未满不提前、≥60秒；expected由字面时间线计算 |
| 传输合同 | 安装版SDK＋本地假HTTP，独立20列2000行/尾页样本、空但有列、无列、错序/类型、Decimal及NaN；逐类普通源错误 | API/params/fields、列顺序及值不变，错误分类与原独立金样本一致，普通重试次数/退避保持 |
| 请求生命周期 | 每次小块但总时间超限、DNS/响应不返回替身、半帧/超长帧、正常返回却进程未退出、worker崩溃、父进程强杀、SDK期间取消、ps失败/RSS超限 | 在缩小时限的隔离测试中真实结束并回收，无后台请求继续；另外实测一次正式30秒预算的本地慢响应，记录TERM/KILL/退出延迟和总耗时。无正式token/网络；全局300秒用独立单调时钟/累计样本验证 |
| Raw恢复 | 当前脱敏原生事件合同、原失败JSON/摘要，唯一child完整ALL_STEPS；未授权、错父/根/key/日期/证据、非该错误、出现正式文件/实检、第三run、部分步骤 | 先验证真实生产者字段再建夹具；恰好1次重执行，新目录两轮，旧记录逐字保持；新失败不递归 |
| 持久预算/接回 | 原raw预算用尽、collecting旧父300秒、旧＋新目录/target去重、发送后丢响应、无响应无child、控制退出后child运行/成功 | 一次POST；有child接同run，无child不盲发；原计数不清零；Raw恢复成功只进入普通Silver |
| 进度/验收 | 字面1完成1失败、1未知、两组父子及2计划未评估、PID被无关进程复用、错误实际check/文件摘要、49/47统计 | 数量与单位事实一致、错误退出码准确、失败后0POST；计划记录不算实检，错误/额外父子仍拒绝 |
| 整段隔离 | 45项受保护基线→指定Raw父失败→新Raw→普通Silver→后三日→49项audit→47项重放，插入丢响应/退出/超时 | 用临时Dagster/文件、独立源样本和实际SQL/Parquet/check；两处传输和控制的mock边界单列。原45 hash不变，预期98成功＋2失败，重放0新增 |

完整回归涵盖原156项资金流控制/七表job/check/Parquet基线及新增相关测试；上次37项风险针对性通过只作原保护证据，不冒充新功能通过。按当前真实路径选测试，不通过filter/skip/改预期掩盖失败。受影响的catalog/静态/目录/启动器门禁按原启动器运行；项目致命Ruff、本次改动文件默认Ruff、无正式凭据隔离`dg check defs`、文档检查和`git diff --check`均须通过，不装依赖。传输测试涉及监听/子进程时按工具权限执行，不能把沙箱拒绝误报为业务失败。

单元、传输集成、隔离job和正式执行四种证据分开。真实Tushare第二轮及14～16来源状态只有正式阶段才知道，不能通过假源“预先保证”。若实际安装版进程/IPC成本或编码规范使本设计不可实现，先回原方案和本节修订，禁止改走无时限同步请求、改大预算或先修一半正式运行。

#### 70.25.9 设计轮审计与交付状态（历史记录，后续实现见§70.26）

本轮逐项复核了R1～R6的代码位置、消费者、读写边界、状态转换、失败/取消/续跑、配置来源、成本及测试。设计决定已具体化：R4采用可终止的专用请求子进程；R2用一次明确Raw原生父子重执行并迁移所有控制消费者；R3保留完整逐项事实；R5刷新当前依据而非盲目重启；R6进入原工具的受维护只读验收。原§70.23“只改两个采集器”的范围由本节对账表扩展为必要的传输/控制/验收修复；无共享Tushare调用行为变化、无新增自动更新/业务字段/主体依赖。

当次代码与方案审计没有遗留“之后再选择机制”的设计空白；尚待取得的是**设计确认后的实现、真实本地传输性能/资源验证、整段隔离结果和正式阶段批准/执行证据**，这些不是已经通过的结果。若任何门禁失败，准确报告失败项、已完成量及剩余范围，保留记录并停止写入。本轮仅更新原方案与本LLD，未修改修复生产代码或测试、未安装、未加载、未调用源端、未正式恢复；整体第一步仍45/49，不能写成完成。

本轮文档交付校验：六项风险均已映射到实现位置和正反验收，九个设计小节齐全；审计报告记录的10份修复相关源码当前SHA仍一致。`scripts/check_docs_integrity.py`与这两份文档的`git diff --check`通过；另核对本次新增仓库引用和测试路径。文档完整性脚本不扫描lake_console的全部链接，也不证明传输、恢复或正式任务通过，故不将上述检查写成开发验收。

### 70.26 修复实现、隔离验收与剩余正式边界

#### 70.26.1 授权、目标及改动对账

本轮指令为“提交修改，然后按照方案和LLD来推进修复和隔离演练”，并要求尽可能小成本。已先提交`61650e27`（两份设计及四份风险报告），再按§70.25开发。下列是实际实现，不是新执行授权。全部43份本任务Python路径、SHA、原始日志/XML、命令和覆盖边界记录在[验收报告](../../reports/moneyflow_p4_continuation_recovery_20261017/repair_isolated_acceptance_20261017.json)及同目录`repair_isolated/`，新实现尚未提交。

路径以下相对`lake_console/orchestrator/`。CodeGraph使用`codegraph_explore`审计入口/调用/恢复影响面，完成后`codegraph sync/status`确认仓库根索引最新（4210文件）；动态SDK与原生Dagster事件补读现行代码、安装类型和生产者。正式加载、共享服务活动和真实来源行为仍需下阶段核验，未声称CodeGraph代替运行证明。无Foundation/Ops/Biz/QTF、前端或主体依赖矩阵变化。

| 设计硬口径 | 实际代码 | 独立验收 |
| --- | --- | --- |
| R1 保留60秒间隔及取消/总预算，只等待正数 | `src/orchestrator/defs/source_readiness/{moneyflow,moneyflow_daily}.py` | `test_moneyflow_recovery_boundaries.py`四项真实缺陷反例先在旧代码失败，修复后通过；原采集器时钟/取消测试保留 |
| R4 请求真正可结束、30秒含启动/回收、Raw300秒不重算 | 新`moneyflow_transport.py`/`moneyflow_request_worker.py`；两处update沿已有collection_options传原deadline；限值在`defs/run_contracts/moneyflow.py` | 安装版SDK经本地假HTTP、2000行独立样本；慢分块完整30秒、取消/TERM无效/KILL、父退出、错误分类、坏帧/超限及RSS不可读均拒绝或回收 |
| R2 只允许指定失败Raw恢复一次并接普通Silver | `moneyflow_continuation/{plan,recovery,submission,state,execution}.py`、原CLI | `test_moneyflow_collection_recovery.py`15项，真实5574行/20列旧候选合同、scope-1分页、摘要变化拒绝、唯一父子、丢响应接回、错误父/第三run拒绝；旧collecting按300秒计账，不改原收据 |
| R3 失败仍显示已完成数量；未知不能当未做 | `execution.py`、`state.py`及CLI | 字面1完成1失败/未知；逐项事实保留，inspect阻断退出3，不发送新任务；现有控制/CLI回归 |
| R5 当前依赖必须能加载，不能沿用旧证明 | 专用worker显式import进入依赖闭包；原verification/guard保持 | 临时home、无正式凭据Definitions通过；117依赖/744源码稳定，当前逐份SHA仍相符；本轮没有正式加载证明 |
| R6 全49真实交付与保留失败分别计数 | 新`moneyflow_continuation/acceptance.py`，原CLI新增audit；输出位置先验证再读数据 | `test_moneyflow_continuation_acceptance.py`12项＋四日实际job/check读回；错误check所属run/target、额外任务和误计planned均拒绝；响应丢失时凭原intent及唯一原生成功事实接受，不伪造响应 |

配置及读写边界均按§70.25.4：新增内部限值集中为回收2秒、轮询0.1秒、RSS抽样1秒、输入64KiB、输出32MiB，无新env/数据库/页面开关。token只走stdin，不进argv/日志/中间文件；传输worker不写湖/数据库/事件。POSIX/信号计时器、可执行`/bin/ps`、有限deadline及真实字符串token均在启动前验证，不支持则拒绝；当前macOS已测，未声明其他平台通过。共享`defs/resources.py`和`tushare_request_policy.py`与提交基线无差异。通用字段、参数、分页、重试分类、并发、sensor和run key口径不变。

恢复读取的证据仅限仓库reports或`/private/tmp`，必须先验路径再验SHA；旧候选分页按真实生产者`round-1/scope-1/page-{0,2000,4000}.json`验证。单命令内旧候选SQL可复用，但cache绑定unit/父run/证据SHA/候选SHA/receipt SHA；事件与文件摘要继续核对，不跨进程持久复用，正式提交前后独立核对保持。两组恢复说明及旧消耗继续继承，不能跨日重置身份或预算。新恢复再次失败仍停止，没有自动放行其他失败。

#### 70.26.2 最小隔离演练及成本

没有为隔离验收重新生成已完成45项的大文件，也没有发真实Tushare请求。`tests/conftest.py`的非autouse fixture只在明确标记的资金流旧假源测试替代传输；真实传输用例不使用它。

1. 全49项状态/统计和两组父失败用明确替代存储验证45→49、完整47项重放零新增；安装版原生事件和check target类型真实，外层查询存储为替身。因此这部分不是98次真实job，也不是正式49项物理验收。
2. `test_moneyflow_continuation_four_days.py`只为剩四日各造3行，使用临时Dagster SQLite、真实job、Parquet/SQL及阻塞check，实际8次成功任务，保留1次真实失败；假源请求8次、控制提交11次（含3次登记）。模拟提交已落地但HTTP响应丢失，再接回同一原生run，重放0新增。临时文件读回经实际acceptance记录校验。正式GraphQL/来源边界和旧失败父证据在本测试明确替代，旧候选与父证据分别在R2用例验证，不冒充该临时失败等同正式旧父。
3. 单动作最多34读，已计入22次正式守卫读取等价成本（HTTP运行态2、日历2、池4、活动任务14），限额40；全演练meter95读。没有上调400读/300秒总审计、观察120次/20分钟等既有限额。300秒Raw及一分钟等待用独立时钟验证，不为四日演练真实等待四分钟。
4. 请求传输16个不同用例分批全部通过。安装版SDK本机2000行一页实际0.907秒，请求计时833.34毫秒；子进程峰值189513728字节，父子峰值保守合计上界347389952字节（约331.3MiB），限额768MiB。另一次正常返回＋完整30秒慢分块试验通过，用例总耗时30.26秒；这是测试运行时间，不是承诺每次业务请求在该耗时返回。父进程检查总deadline、子进程独立计时器、TERM/KILL及回收保证无后台继续请求；未声称真实源网络永远成功。

证据没有覆盖正式GraphQL/shared PostgreSQL的实际重执行、当前共享池状态、真实来源日期数据或未来修订，也未验证其他平台。正式13日第二轮、14～16行数和外部网络结果仍待实际执行。不能把上述隔离完成转换成49/49正式完成。

#### 70.26.3 实际门禁与执行顺序

受影响33个模块完整跑一次，**1203项通过、0失败/跳过，339.481秒**；命令保存在`repair_isolated/moneyflow-full-repair-command-20261017.json`。随后增加worker能力/token前置拒绝、证据路径前置拒绝两处小边界，仅重跑对应恢复/验收/四日/前置测试，**29项通过，7.261秒**；不将此前完整回归误写为两处追加后的全量重跑，也不重复长测试。传输快速分组12项、最终2000行测量1项、先前正常/慢分块1项及RSS/父退出分组均通过，存在重叠，不相加冒充更多不同用例。

原受保护测试启动器未改动或绕过；静态、catalog与root-guard均记录regression_suite_passed。43个本任务Python文件默认Ruff通过，项目致命错误基线通过。隔离Definitions无正式凭据、exit0，117依赖/744源码加载期间不变，最终文件摘要逐份复核仍一致。文档完整性检查、本任务diff空白检查及17份持久化证据/43份代码测试摘要复核全部通过；这些检查不代替业务验收。原始日志、XML、Definitions和文件SHA已复制进reports，报告不只依赖临时目录。

本轮正式reload、job、源请求、日期登记、Lake写入、sensor变更全部0，也未刷新正式只读状态。20:40的45/49（两层各105996行、90份成功交付、2次失败、21个sensor关闭）只作最近证据，不声称它是本轮现场复验。原45项仍待正式前后摘要比对，49项目标98成功＋2失败/98文件/98物化/98准确通过检查、2planned单列仅是正式验收目标。

后续严格继续§70.25.7步骤2～6：先按7日期有界核对当前环境、加载依据及任务，再在满足阶段授权后加载修正代码和重新生成同root清单；先13日Raw唯一child→普通Silver读回，再14～16；最后全49项audit、原47项零新增重放。旧清单SHA或上次serverId不可直接执行，本节不虚构新的正式命令/证明。源码加载和Raw恢复仍按阶段授权，不能把本轮修复/隔离指令延伸成正式写入；21个自动更新保持关闭，P5不进入。当前剩余的是正式恢复和收尾，不是继续修补隔离验收。

### 70.27 本轮正式审核、代码加载与四日恢复执行记录

#### 70.27.1 执行范围及准入

管理员本轮已批准提交修复并按计划推进正式审核、数据恢复及验收，覆盖§70.25.7步骤2～6。修复提交`db67e7d8`，本轮不再要求重复批准。仍仅moneyflow10-13～16，严格先13日Raw唯一原生child→普通Silver→读回，再14～16。21sensor保持关闭，其他45项、历史7804项及P5不进入写入范围。

当前正式审核见[preflight.json](../../reports/moneyflow_p4_continuation_recovery_20261017/formal_recovery/preflight.json)：2026-10-17 22:47，45/49、90文件摘要不变、原两次失败与剩四日动作准确，无活动或排队任务；14资产、21停止、专用并发容量1且空闲、同盘及空间门禁通过。117依赖/744源码与已通过的隔离Definitions逐份一致；审核NativeBackend计数272读，另4条只读池SQL，合276读/5.76秒，0正式变更/0源请求。因本次变更真实采集器、截止点传递及请求worker，必须加载当前代码一次，不能只凭资产名称相同视为代码已更新。

#### 70.27.2 原生代码加载的精确操作

工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，解释器`.venv/bin/python3 -B -u`，现有instance home `/Users/congming/.goldenshare/dagster_home`，GraphQL `http://127.0.0.1:3000/graphql`。薄操作记录脚本为`/private/tmp/moneyflow-formal-recovery-20261017/reload.py`，仅执行原方案已有`reloadRepositoryLocation(repositoryLocationName:orchestrator)`；精确body已保存`formal_recovery/reload-request.json`，按安装版schema验证后发送，不启停服务、不改配置/池、不启用sensor、不启动job、不写Lake。

发送前重新核对源码/config/calendar及无活动/排队共用任务，持久化原请求和发送意图；最多发送一次。响应不明保留原意图，仅只读核对加载事实，禁止盲发第二次。读回14资产合同、版本、serverId、21STOPPED和源码摘要；源码漂移或加载错误即停止，不进入数据恢复。加载及此后正式job所运行的源码均绑定当前依赖摘要，而不是只绑定提交号（工作区另有未提交的catalog文档说明，其当前字节已在隔离证据中）。旧失败/候选/控制日志保持。

#### 70.27.3 清单刷新与数据执行约束

加载读回通过后保存新verification（当前runtime、源码依赖、隔离Definitions、正式日历/config摘要）；从完整47项父清单`final/00-all-current-plan.json`生成同root的新完整清单，增加既定10-13 collection_recovery并继承THS10-14 launch_recovery，再生成单日子清单。调用原`orchestrator.moneyflow_continuation_cli plan/apply/inspect/audit`，不新增正式数据驱动器。精确命令、SHA、home、Lake/staging根和输入路径在`formal_recovery/execution_manifest.json`中逐份生成并在首次apply前核对。本节不预填尚未生成的SHA。

请求量正常预期四日24次、硬上限各64/合256，原30秒请求、300秒Raw、两轮≥60秒、前五日下降20%拒绝、768MiB、动作40读及累计预算均保持。13日只恢复一次，任何新失败停止，不递归。逐日inspect与物理文件/准确check/来源收据确认后才处理次日。终验仅7日期全49，保留两失败/两planned，98成功文件/任务/物化/实检目标；原90文件及收据hash保持，47项重放零新增。跨午夜按§70.25.7原范围更新有效期，不重置root/run key/控制消耗。最终实际数量、行数、请求区间、命令及未覆盖边界回填本节；尚未发生的加载和恢复不算完成。

#### 70.27.4 加载读回与首次apply前的精确清单

原生加载已成功且仅一次，serverId由`1dee22e1-cff8-4af2-8195-f70354f9c35a`变为`622f590d-45b0-47b3-99dd-fc54145f0c32`；14资产及21STOPPED读回通过。新verification SHA256=`4beeea0907a53d55f99d61403520bfeb6a97bd5db3bcf808b73addc94f662ce5`，依赖/库存与加载前一致，未提交任何数据任务。

[精确执行清单](../../reports/moneyflow_p4_continuation_recovery_20261017/formal_recovery/execution_manifest.json)已生成并逐份只读核对，包含完整argv、绝对路径及SHA。完整47项SHA=`b036e672b870ad7e9a4368befb85c9e889456d1b4d1290e0d6f212e7de89bf42`，root仍`79c34e4ed75be094554311d6b46d29f5be11ae2d1310303a85f5f32dc39628d0`，有效期至2026-10-18 00:00上海时间。

| 执行顺序 | 单日清单（均在formal_recovery/） | SHA256 |
| --- | --- | --- |
| 1 | 01-moneyflow-2026-10-13-plan.json | 5f709a1311031f893ba1c033b2916aa62fdab6ebd3982755931b817f906ff646 |
| 2 | 02-moneyflow-2026-10-14-plan.json | 2117e4b42bbdfd239ba052db75ec10e868e29c5d1d706a8e7a384192d535477e |
| 3 | 03-moneyflow-2026-10-15-plan.json | 337e0ac92275437a5d40b66a1162a098005c84cdc12549753b722fa8ad55fe60 |
| 4 | 04-moneyflow-2026-10-16-plan.json | 2a8d41856a1cb0f36a866b9947c362ab1d516ce217d2a16144be68a342f76e97 |

每一步只调用清单对应的原CLI apply命令；日志写新文件，完成后原CLI inspect及独立按真实SQL/物化/check/收据读回，确认前45项保持再进入下一日。最终audit和47项重放使用同一完整清单及原控制目录，命令亦在执行清单中，不能另造root。正式读写边界及停止条件沿§70.27.1～3；没有逐日完成证据前不执行下一日。

#### 70.27.5 逐日正式恢复与独立读回

10-13已通过原apply及inspect，再独立SQL/Parquet/物化/check/收据读回通过：两层各5574行，6次源请求、0重试，Raw来源阶段72478.50毫秒。Raw child=`863def44-10b5-412a-99a7-dbc407967806`，父仍`ca3d12ad-717e-4291-a87f-6c2a3d37204a`；普通Silver=`daa1a755-e96d-4192-ab47-060cc318dac0`。原90文件/45收据摘要保持，旧5574行候选仍在，21sensor停止。独立审核38读，通过后进入14日；本时点46/49，后三日未提前记完成。证据见formal_recovery/01-moneyflow-2026-10-13-acceptance.json。

10-14按下一单日清单完成并独立读回：两层各5574行，6次请求/0重试，Raw来源70798.63毫秒；Raw=`1ff1d4e1-e4d5-4e15-b829-22fd823d4f31`，Silver=`081a560f-a15b-46e9-8706-810cc68d7645`。原90文件/45收据、旧失败候选和21STOPPED保持，36读。证据formal_recovery/02-moneyflow-2026-10-14-acceptance.json；通过后进入15日，本时点47/49。

10-15按下一单日清单完成并独立读回：两层各5576行，6请求/0重试，Raw来源72352.35毫秒；Raw=`26bdcd5c-a53d-466a-bb03-80689a0e8f43`，Silver=`2d24458e-a2ff-42c4-8d55-0ea319e1a9d9`。原90文件/45收据、旧失败候选和21STOPPED保持，36读。证据formal_recovery/03-moneyflow-2026-10-15-acceptance.json；通过后进入16日，本时点48/49。

10-16按最后单日清单完成并独立读回：两层各5577行，6请求/0重试，Raw来源73280.90毫秒；Raw=`bf937cb4-155d-4294-a45f-79b884a05d72`，Silver=`f8f5497d-6eb2-4878-a18e-4b0b2debfea2`。原90文件/45收据、旧失败候选和21STOPPED保持，36读。证据formal_recovery/04-moneyflow-2026-10-16-acceptance.json。本时点逐日完成49/49，统一audit和47项重放尚须验收，不据逐日成功提前关闭步骤。

#### 70.27.6 全49项正式audit通过，进入原47项零新增重放

原受维护CLI audit已通过：49/49、98成功任务/98文件/98物化/98准确通过检查，两次原失败及两条未评估planned保留，共100原生任务；两层各128297行，共19828828字节。成功收据224请求、0已知重试；旧失败仍保留3～64未知区间，整体227～288，不伪造精确总数。90份旧文件、45份收据摘要均保持。审核339读、5.293秒、峰值342851584字节，未越400读/300秒/768MiB门禁。证据formal_recovery/49-final-acceptance.json。

现在按已记录execution_manifest的replay_command，对相同完整47项清单执行原apply。先对原root下精确动作文件及budgets保存摘要（不扫其他控制根或全部历史）；执行后重新运行同范围49项只读audit并比较49份交付记录、98文件/收据、实际任务/物化/check总数和runtime。两次audit输出分别49-final-acceptance.json及49-replay-acceptance.json；薄只读控制摘要工具为/private/tmp/moneyflow-formal-recovery-20261017/control_fingerprint.py，before/after命令已记入执行清单。本动作只验证幂等性，不允许借重放新增任何日期登记、任务或来源请求；差异即不通过，保留证据并停下，不靠修改预期消除差异。

#### 70.27.7 正式恢复和零新增重放全部通过

重放后同范围audit通过：49/49、98成功任务/文件/物化/实际通过检查、2失败/2planned，共100原生任务，两层各128297行。原47范围94成功＋2失败=96；未把planned计为实检。重放前后49交付记录（含全部98文件及来源收据摘要）、totals和runtime完全相同；精确控制根下573个动作/预算文件逐份SHA一致。新增登记/任务/物化/实检/来源请求/正式文件改变均0，见formal_recovery/47-replay-control-after.json及49-replay-acceptance.json。apply日志的registered47/submitted94表示现有已完成事实，不是这次新增数量。

本轮四日共24次真实Tushare请求、0重试；8个新完整成功job、8份文件/物化/准确检查、3日期登记，两层各新增22301行，未拒绝行。Raw来源时长约70.8～73.3秒，含两轮至少60秒间隔，未改变300秒/64请求/768MiB及下降20%门禁。原失败父run、5574行首轮、3页、旧收据及旧执行消耗都保留；两次原失败仍在，不通过删除事件或无界重试处理。

两轮全49只读审核分别339读/5.293秒/342851584字节RSS和339读/5.474秒/329728000字节RSS；在400读/300秒/768MiB内。逐日独立读回分别38/36/36/36读；原45项文件与收据保持。真实源6请求/日证明源端完整分页→两轮5574/5574/5576/5577行→两层同数→真实阻塞check通过；该结论只覆盖此次日期及观察窗口，不替代未来日更和来源最终性。成功收据总请求224，旧失败只能确认3～64，整体仍227～288，旧失败重试总数未知。

本轮操作为1次代码location加载（无服务重启）、1次指定Raw原生重执行、3次普通Raw及4次普通Silver；最终加载serverId仍622f590d-45b0-47b3-99dd-fc54145f0c32，14资产合同和21默认/实际STOPPED保持。无sensor启用、无其他数据集写入、无7804历史日期重扫、无schema/源参数/共享策略/配置或主体依赖矩阵改动。临时操作脚本只按原CLI及原生reload执行，原文及SHA已存formal_recovery/operation_sources/供复核，不作为新正式采集主链。完整执行清单、输入和新文件SHA、每日证据、全量前后验收及零新增结果索引见[closeout.json](../../reports/moneyflow_p4_continuation_recovery_20261017/formal_recovery/closeout.json)。

§70.25.7步骤2～6均有实际证据，故数据接续第一步关闭；之前§70.26的“正式恢复待后续”保留为当时交付状态，由本节实际结果接续。原P4自动启用、P5真实日更及历史源缺口不在此次完成范围，21sensor继续停止。新增正式执行记录/本节与方案§75.21尚未提交、未推送，修复代码提交db67e7d8已完成。

### 70.28 既有21个自动更新触发器启用方案与执行门禁

#### 70.28.1 目标、依据与范围

对应方案§75.22，管理员“完成前三步”已授权提交旧记录、启用前审计及逐表正式启用，不重复申请批准。本步不新增生产实现；资金流117依赖、原七个sensor模块、moneyflow_update_selection、原生Dagster1.13.26 GraphQL及已验收49项为依据。CodeGraph explore确认登记/更新共用helper各七个调用方，补读真实resource/health/原生start/stop/tick schema及原生生产者，不凭名称推断只读。修复提交db67e7d8、正式接续记录提交ed79cba5，P4历史与数据接续保持；P5三交易日观察不在本轮完成范围。

硬口径：七个独立数据集，各3个sensor；工作目录/Users/congming/github/goldenshare/lake_console/orchestrator，home=/Users/congming/.goldenshare/dagster_home，GraphQL=http://127.0.0.1:3000/graphql，正式Lake=/Volumes/datasource/data_lake，staging=/Volumes/datasource/data_lake_staging。保持默认STOPPED，通过原生持久状态启动为RUNNING，不修改源码默认值；不配置新全局参数、不改并发池/服务、不重启、不为此reload、不修改其他线程文件。

#### 70.28.2 当前代码和首次启动行为审计

资金流所有117份依赖与70.27证明一致；另5份复权支持模块已变、2新增，均不在资金流闭包，记录实际摘要及加载状态，不发布这些未完成改动。已有资金流代码不变，所以不以无关源码变化为由重复跑1203项大回归或重载共享location。正式审计验证加载serverId/原生14资产合同、21停止、daemon、当前任务、容量1及空闲/互斥、日历/config和依赖，已验收98文件/49来源收据与最新成功run/check绑定；用七日期或≤10日期批次，不扫描7804历史明细。

当前helper先检查22:00，再查每表Raw/Silver活动任务；登记器从10-01后SSE开市日补漏，最多当日+1个漏日；更新器只查最近10个expected开市日，一tick最多1个run，有active不提交。Raw已ready且物化为本观察日时自动记verified_on，今日不再采；其他已ready旧日按既有每日最多一次复核。Silver只在Raw已绿且缺Silver或上游hash变化时请求，身份绑定Raw hash。恢复后的原父失败不直接作为ready依据，首次预演必须验证现在的成功交付与最新任务不会被旧失败误判。

实读日历确定当前窗口；截至23:02原49项Raw的物化时间全部为10-17，若现场仍相同且10-17休市，则首次21个触发器应0新分区、0job/源请求/文件变化。没有证明前不启用，任何预演意外request或阻断均停止复核，不改游标造all_ready。未来窗口每日正常源请求估算32次/七表日期，7日全部复核约224次，10日约320次（不含重试），可能最多70个Raw/70个对应Silver更新，只有实际hash变化才需后者；原每Raw64请求/300秒/两轮≥60秒、20%数量门禁及本族串行保持，tick最小600秒，不承诺墙钟22:00:00完成。未来自动行为已由启用授权承接，不能拿本次首次0请求保证未来也0请求。

#### 70.28.3 配置、读写边界与低成本验证

无新增配置。持久启停来自原生sensor状态表，经startSensor/stopSensor GraphQL写入；消费者为现有daemon及各sensor；即时/下次tick生效，状态/tick/cursor可从Dagster读回。默认源码STOPPED不变，显式RUNNING持久状态在正常重载后仍由原生逻辑处理。600秒、22:00、10日、六次attempt和token均沿现行来源，token不打印/落盘。启用范围严格白名单21名字，其他sensor状态前后保持。

静态审计已发现LakeRootResource.ensure_available_for_run会执行现行可读写健康canary（创建后读回删除），不是纯只读；DuckDBResource默认managed连接也可能创建temp目录。因此启用前的helper决策预演只在明确替代这两项resource副作用后执行：lake根只读检查所需目录/os.access，DuckDB使用既有configured helper的512MB/1线程/existing_no_spill连接；真实PG由daily_basic_event_instance默认只读、禁自动DDL，实际helper/日历/分区/原生事件/check/文件hash判断不替代，返回的cursor只存本地证据，不写正式游标、不执行RunRequest。登记器所需log只用于本地日志。不把这层预演声称为完整原生tick；正式启用后的daemon首次tick才验收真实resource/状态/游标路径。正常sensor固有健康canary在启用授权范围内，不能将其误报为新增业务Parquet写入。

已有sensor隔离回归及上轮1203项证据在生产代码/测试摘要一致时复用；只补当前真实7日期决策、游标复算和schema/操作边界验证。隔离Definitions若当前共享库存有变化，只在无正式凭据的临时home做一次加载确认，禁止隐式依赖同步/安装，不将其当正式reload。审计/预演单命令≤400读取/300秒/RSS768MiB；窗口≤10日期/数据集、cursor≤8KiB、各tick目标<30秒、不得逼近60秒RPC超时；采样记录实际query/hash次数与耗时。若超限/读取失败不放宽预算。

#### 70.28.4 正式启用、失败和续跑

先实读确认预演零动作、已验收文件/收据/当前成功check保持且依赖/加载一致，再按moneyflow_mkt_dc、moneyflow_ind_ths、moneyflow_cnt_ths、moneyflow_ind_dc、moneyflow_dc、moneyflow_ths、moneyflow顺序逐表；每表登记→Silver→Raw。使用当前安装schema验证的startSensor(sensorSelector:{repositoryLocationName:orchestrator,repositoryName:__repository__,sensorName:<固定名>})，21项最多各1次POST。每次新目录保存request、发送意图和response并读回实际RUNNING后再下一项。响应不明先只读查该sensor真实状态/原意图，已RUNNING接回，不盲重发或换身份。既有RUNNING且可证明本步骤已执行的只读接回；不重置cursor、lastTick或attempt。

每表启动后等该表3个sensor产生本次启动后的实际完成tick；应为SUCCESS或正常SKIPPED、无error、runIds空、无新增分区，cursor身份/时间/窗口正确，Raw reason=all_ready、Silver=all_ready。每10秒更新当前表/已启用数/已确认tick数；单表观察≤120秒、≤12轮，每轮对当前表3sensor批读（限1～2条tick），从持久操作记录保留起始时间，控制器退出不取消原生进程。超时停止下一表并报告，不反复重置观察时间。如果daemon评估尚未完成，不能只凭RUNNING宣布正常。未来3天观察另做，不在本轮等待。

任何失败、非预期run、新增坏文件/未绿检查、依赖或加载漂移，停止继续启用；只对本轮明确已启用的资金流sensor按原生stopSensor(id:<本次读回sensorState.id>)关闭并读回STOPPED，保留原请求/响应、游标和数据，不reset、不删除、不取消其他任务。业务任务若已在运行，停止sensor不等于取消任务：保留并只读观察，实际业务失败另行审计，不恢复到旧文件或自动发新attempt。控制器退出后下次从保存的state/tick及发送意图接回，不再start同项。

#### 70.28.5 执行记录与验收

本步证据目录lake_console/reports/moneyflow_p4_sensor_activation_20261017/，操作临时目录/private/tmp/moneyflow-sensor-activation-20261017/。薄操作脚本仅复用原生GraphQL启停和只读核验，不新建正式CLI/采集执行器；每阶段开始前将具体argv、工作目录/home/endpoint、输入SHA和21请求/停止body写execution_manifest.json，原文/SHA最终归档。审核结束才生成精确启用清单，未生成的SHA不预填。

退出条件：21个明确sensor实际RUNNING、各自本轮首次原生完成tick正常（含skip）、当前七日缺口0、98份文件/49来源收据和准确check/run事实保持、首次新任务/来源请求/数据变化0、池/锁/daemon及其他sensor状态无异常。源码默认STOPPED保持，不改变主体边界；关闭P4调度接入，但P5≥3交易日、故障恢复/修订与最终整体交付仍待后续。未满足哪一项就逐项报告，不用空源/伪造cursor或手动job代替自动触发链验收。

#### 70.28.6 当前审计与正式启用前的精确依据

审计已通过，197读/2.931秒/RSS281591808字节。21个实际helper决策及Raw游标再评估均无请求，98个物化/准确检查/原生run绑定和98文件/49收据摘要与23:02验收保持。SSE窗口确认为10-08、09、12～16共7日，10-17休市；所有Raw最新成功物化都为本观察日，首次应0新任务。当前隔离Definitions再次通过，117依赖/746源码稳定；资金流117依赖完全未变。另7份复权支持文件（含2新增）记录为无关变化，未纳入发布，不reload正式location，现有serverId/14资产合同仍与已验收版本相同。

精确21项启动/停止body、真实sensor ID、逐表顺序及命令见[execution_manifest.json](../../reports/moneyflow_p4_sensor_activation_20261017/execution_manifest.json)，SHA256=`e5bdcd3122fa6943baa3af0e9147e3be015def7441d64773e17fff61cfd32c2a`。每个body已用当前schema/变量纯校验，未执行resolver；只读准备2次HTTP。正式命令（上述工作目录/home）为`.venv/bin/python3 -B -u /private/tmp/moneyflow-sensor-activation-20261017/activate.py`，脚本内固定核对该SHA及21白名单，持久意图后单次原生POST。它只操作既有sensor开关、读取tick并记录报告，不能发launchRun/registerPartition/reload。每项身份/载入/源码/calendar/config/旧文件和收据再次核对，表级120秒/12轮观察不重置，失败执行仅针对本轮已启动项的原生stop。正常情况下本轮无job、无新分区、无源请求；首次真实tick的健康canary/游标/状态写入按§70.28.3明确边界验收。

本节仅完成审计和精确执行准备，21项尚未启动，不提前写成P4完成。首次真实tick及启用后的独立读回还必须取得实际证据。

#### 70.28.7 实际启用完成，进入独立读回

23:35:13原生21项启动均成功，按七表顺序每表3个RUNNING后等待3个真实完成tick，再进入下一表；全21首次tick正常且无任务/分区请求。共87次只读边界调用，21次明确原生start POST，无stop/reload/配置变化。每表观察2轮、约10秒，无预算重置或手动评估正式sensor。原始动作请求/发送意图/响应、逐表accepted和actual tick/cursor均已保存，不把只读预演当成实际tick证据。

独立最后读回命令为上述工作目录及home下`.venv/bin/python3 -B -u /private/tmp/moneyflow-sensor-activation-20261017/readback.py`，准确argv及脚本SHA见final-readback-command.json；仅查21状态/实际tick、原7日期的14资产批量readiness、按日期过滤原生任务及文件/收据摘要、池/锁和其他sensor状态。它复用先前全49项的物理SQL验收并用当前摘要/准确检查身份证明未改变，不再次扫全历史或重采数据。任何异常不关闭P4，必须关闭本轮已启用项并报告；通过前不声称独立收尾完成。

#### 70.28.8 独立验收通过，关闭P4

按本节完整顺序完成21次startSensor，7表各3个实际RUNNING且启动后21次真实tick全部SKIPPED/无error，无RunRequest/动态分区请求；每表2轮观察约10秒，实际最长tick0.616645秒。原生请求/发送意图/响应逐项保存，未遇响应不明或新失败，不触发stop；没有reset游标、手动evaluate正式sensor或手动launchRun。源码默认STOPPED与显式持久RUNNING分开报告，不将默认值改成RUNNING。

独立新进程只读验收48读/1.026111秒/RSS198098944字节，通过21状态/准确首次tick及cursor身份、七日期批量readiness、按日期过滤的原生任务集合、98文件/49收据摘要、专属池空闲/锁和其他sensor状态。原49交付、98准确检查/成功任务、两失败=100原生任务全部保持；首次新分区/任务/源请求/物化/check/业务文件改变为0。全部14资产合同、117依赖、正式serverId622f590d-45b0-47b3-99dd-fc54145f0c32及原配置保持，无reload/服务重启/并发更改。完整证据见[final-readback.json](../../reports/moneyflow_p4_sensor_activation_20261017/final-readback.json)与[closeout.json](../../reports/moneyflow_p4_sensor_activation_20261017/closeout.json)。

审核前隔离Definitions117依赖/746库存加载成功，资金流依赖不变；7份无关复权支持文件没有被本轮修改、提交或重载。当前阶段复用已通过的生产代码/测试和1203项回归及既有完整49项SQL验收，只新增真实现场预演/原生tick/摘要和准确身份复核。操作记录脚本5份语法核验、3个非白名单名称反例拒绝、42个原生start/stop body均经安装schema校验；原生启用实际21次，预演0副作用。临时脚本原文归档operation_sources/供追溯，不作为新的正式CLI/采集主链。资源canary正常发生并清理，只声明业务数据无新增，不谎称本轮零正式写入。

§64.5第五项和本节退出条件满足，P4调度接入关闭；P5仍需至少3个不同交易日的实际自动采集/字段与行数/耗时/资源、暂时失败与非重试错误、修订/续跑/幂等证据。首次真实skip只证明启用及当前判断正确，不证明未来源端一定成功，也不替代P5。后续新步骤仍先写回原方案和LLD，不借本次启用自动扩大历史补缺或改变热窗口。前三步完成；本轮新启用报告及两文档尚未提交、未推送，旧接续记录提交ed79cba5已完成。


### 70.29 P5异常证据对账（执行前设计）

#### 70.29.1 目标、范围与代码审计

本步承接方案§75.24，只完成“提交启用记录”和“异常证据整理”。启用记录已提交07dd36df；这里不运行正式job，不开关sensor，不重新加载共享代码。当前代码由CodeGraph `codegraph_explore`检查`evaluate_moneyflow_update`及Raw/Silver更新调用链，并直接核验七表sensor/definition测试、两个更新器、采集/传输、行数检查和恢复控制器。影响限于orchestrator现有链路及本步文档/报告，无Foundation/Ops/Biz/QTF、Web/API或依赖矩阵调整。

当前关键语义：Raw仅明确临时错误可自动重试，未知失败停止；六次持久run key不能被丢游标重置。Silver按同日Raw摘要识别修订；Raw未通过或文件/检查不符不能继续。文件发布按已有intent/checkpoint及原子替换续接；提交不明先找既有run，不能重复POST。六表行数下降门禁与大盘恰好一行分别检查，不能把六表规则套到大盘。

#### 70.29.2 对账清单和证据边界

| 项目 | 当前实现位置 | 必须找到的独立验收 |
| --- | --- | --- |
| 临时错误 | sensors/moneyflow_update_selection.py；source_readiness/moneyflow*.py | 七表真实临时失败metadata可重试；超时后成功及请求计数另有采集测试 |
| 不可重试错误 | 同上及字段合同 | 七表非法精度真实失败后停止；不得发布空/非法文件 |
| 尝试上限 | sensors/moneyflow_update_selection.py | 七表六个持久key用完后，即使cursor丢失也不再提交；该用例替代错误分类，不能独自证明分类 |
| 取消和进程退出 | source_readiness/moneyflow_transport.py及worker；采集器 | 保留页/候选、取消结束自有进程、父进程退出也结束请求；SDK实验为本地假HTTP |
| 文件发布中断 | io/moneyflow_*update.py及既有发布helper | Raw/Silver替换后checkpoint失败可续接；不重新请求来源、不损坏旧文件 |
| 提交响应不明 | moneyflow_continuation/submission.py（含Journal） | 丢响应只提交一次；只有意图无run时停止；真实子进程退出后保留不明状态 |
| 重复执行 | 更新器及continuation控制器 | 内容相同不重写；正式原47项重放0新增，573控制文件保持 |
| 源端修订 | sensors/moneyflow_update_selection.py；更新器/readiness | 七表Raw修订后Silver判为待更新；独立job测试证明Silver更新且来源请求不增加 |
| 文件/检查不符 | asset_guards及blocking checks | 七表错日期/摘要/检查身份不能被当成就绪；已有成功不能掩盖坏文件 |
| 行数下降 | asset_guards/moneyflow_row_count.py；六表Raw更新器 | 六表从5行降为1行不得发布，候选保留且非临时失败；分类下降不能由总量增长掩盖。大盘单行合同独立验证 |
| 预算边界 | run_contracts/moneyflow.py；采集/传输 | 64请求、300秒Raw、30秒请求含回收等现有边界的拒绝与资源回收证据；不为审计重新等待 |
| 正式恢复 | continuation recovery及原正式报告 | 两个失败父run保留、新Raw/Silver成功及49项独立验收；不把手动恢复说成daemon自动重试 |

复用的测试夹具依据原源接口字段合同与真实生产者；本步不修改夹具或预期。源错误/分钟等待可用明确假源与独立时钟，真实Parquet/临时Dagster/check不能被mock替代；进程生命周期另用安装版SDK的本地回环实验证明。sensor发请求判断和job实际处理由各自测试证明，这不等于正式daemon遇错后全链已演练。未来真实自动交易日仍须验收，不用休市skip或手动历史job充数。

#### 70.29.3 文件、执行和成本边界

只读当前仓库代码、Git对象和已归档报告；写入仅限两份原文档、`lake_console/reports/moneyflow_p5_exception_evidence_20261018/`与/private/tmp的本次审计临时文件。报告保存12项映射、实际JUnit testcase身份、当前源码/测试及旧报告SHA256、验证方法和未覆盖项；审计脚本仅作本次验证动作原文归档，不注册Definitions或新增正式CLI。

不新增配置、env或持久业务状态；正式Lake/staging、正式Dagster home/数据库、网络和来源读取/写入均为0。不启动测试子进程或请求，不重复长回归。审计只用Python标准库读取文本/JSON/XML和Git只读命令，单文件≤16MiB，最多1000个文件/总读取≤128MiB，预期小于10秒，不加载业务Definitions。报告可覆盖本次尚未完成的审计输出，旧证据不可改；失败必须非零退出并列明不一致，不生成完成结论。中断重跑只重复本地读取，没有正式续跑动作。

退出条件：12项均有代码和通过证据映射；七表对应测试不得漏表，参数化用例不得只按函数名算通过；所引用报告原摘要一致，当前相关源码/测试与已验收提交或固定摘要一致；测试替身、正式恢复、未来交易日的证明边界明确。若证据足够，不为增加测试数新增重复测试。若存在真实缺口，先记录缺口并补齐精确隔离设计再实施，不降标准。

本步完成只关闭异常证据整理，不关闭P5整体。后续仍是至少3个不同交易日的真实自动采集、行数/字段/检查与请求/耗时/资源记录，以及据此进行最终操作文档和项目收尾；本轮不新建未来提醒或计划任务。


#### 70.29.4 唯一补测：父进程退出的具名证据

证据核验第一次在“父进程退出”项停止，未生成完成报告：旧日志仅有三项通过的汇总，缺逐项身份。这里调整§70.29.3“不启动测试”的范围，仅执行现有`tests/test_moneyflow_transport.py::test_parent_death_closes_real_inflight_sdk_request`一次，补具名JUnit和完整命令/日志；不新增或修改代码/夹具，不重复30秒实验。

已逐行核验该测试：安装版SDK访问127.0.0.1随机端口的临时HTTP服务器；20字段独立fixture、假token；创建本测试独占的父/请求子进程，确认一条请求已发出后结束该父进程，断言连接两秒内断开、子进程退出，finally清理仅本测试进程组。请求子进程使用现有环境白名单，剔除正式Dagster/数据库/Tushare凭据；pytest入口也移除DAGSTER_HOME、TUSHARE_TOKEN、PGPASSWORD、DATABASE_URL。测试既不加载正式instance也不读写Lake。该transport专项不是受保护静态启动器的测试目标；沿既有专项命令执行，不改或绕过静态启动器。

执行目录`lake_console/orchestrator`，命令：`env -u DAGSTER_HOME -u TUSHARE_TOKEN -u PGPASSWORD -u DATABASE_URL .venv/bin/python3 -B -m pytest -q -o junit_family=legacy --junitxml=/private/tmp/moneyflow-p5-parent-exit-20261018.xml tests/test_moneyflow_transport.py::test_parent_death_closes_real_inflight_sdk_request`。如工具需要本地loopback/进程权限，按工具提权机制申请；不增加业务审批。本轮用户已批准完成异常证据整理及必要隔离补验。

最多1个测试、1次本地假源请求，预期小于5秒、总上限40秒、临时响应最多1行；没有业务明细计算或正式数据读写。失败保留日志并停止该项结论，不能改成skip或降低断言；超时由外层终止本次测试并检查其专属进程。重跑只能在分析原因后按同一隔离范围进行，不反复盲试。JUnit必须记录该精确名称、1 passed/0失败/0跳过，之后才并入12项证据表。旧匿名日志仍保留，不修改成具名记录。


#### 70.29.5 同一匿名日志的第二条身份补证

逐项匹配全部用例后确认，旧匿名三项日志的另外两条是2000行容量和RSS读数失败；容量已有具名JUnit可复用，只有`test_rss_observation_failure_ends_owned_request`仍缺具名记录。父进程退出已单独通过，不能把这次审计脚本停止说成业务测试失败；它没有生成完成报告。

补测仅该现有函数一次：沿§70.29.4相同env清理/目录/解释器/pytest参数，改JUnit为`/private/tmp/moneyflow-p5-rss-exit-20261018.xml`，目标为`tests/test_moneyflow_transport.py::test_rss_observation_failure_ends_owned_request`。测试启动自身的sleep临时请求进程，替代`_pair_rss`抛出明确`source_worker_rss_unavailable`，断言拒绝且workers fixture确认进程和管道全部结束；不发HTTP，不读正式进程或正式资源。最多1用例、预期小于3秒、40秒总上限；没有独立采集/文件输入，不能用其证明真实内存采样值准确。本轮累计2条既有用例，不重复父退出或2000行/30秒测试。通过后分别保留两份JUnit及命令，证据审计仍要求所有12项完整才输出完成。


#### 70.29.6 实际验收与计划对账

本步代码/方案审计及归档核验通过，12/12类已映射到实际代码、138个不同测试用例及所需正式历史证据；不是本轮运行138条测试。117依赖、43修复文件均与原摘要一致，34个相关测试模块与db67e7d8逐字相同；总计323份固定摘要核验通过。最终本地核验334份文件/7244105字节、约0.78秒，无业务Definitions加载。没有业务、测试、配置、源参数、主体边界/依赖矩阵或Lake路径变化。

§70.29.2每条验收的具体模块/函数、参数化case名称、JUnit路径、源码行和SHA均保存在[evidence.json](../../reports/moneyflow_p5_exception_evidence_20261018/evidence.json)；人读结论见[证据表](../../reports/moneyflow_p5_exception_evidence_20261018/README.md)。第一次核验因旧匿名日志缺逐项身份而停止，没有形成通过结论；依§70.29.4～5补跑两条现有用例后完整核验通过。父进程退出1 passed（suite 2.411秒）；RSS读取失败1 passed（suite 0.530秒），均0错误/失败/跳过；精确命令、XML和日志各自归档。前者1次本地假HTTP、后者0次HTTP；正式读取/写入/源请求/新故障注入均0。没有绕过静态启动器或改测试预期，旧1203项及后续29项的时间边界说明保持。

12项中：临时/致命错误及尝试上限由七表临时原生失败/持久key证明；取消/发布中断由真实临时文件和拥有的进程证明；丢响应由控制器替身、本地真实HTTP和进程退出分别证明；重复执行另有正式573控制文件/49交付/98文件不变记录；修订由七表sensor判断和实际临时job处理分别证明；坏文件/check身份及六表下降/大盘单行合同均有反例；时间、请求、内存边界复用独立假时钟及真实安装SDK回环证据；两次正式失败及一次性获批恢复另有历史正式验收。上述边界不能互相冒充，不将一次手动恢复称为自动重试，也不将休市skip称为真实交易日采集。

前两项已完成：启用记录07dd36df已提交；本步异常证据与文档已落地、尚未提交，未推送。下一阶段仍只按原P5收集至少3个不同交易日真实自动更新及其运行/数据/成本，再进行最终运行文档和项目收尾。本步不新增其他开发切片，不需要新的实现决策，不提前宣布整体接入完成。

## 71. 从Prod定点补齐DG历史数据（补充LLD；2026-10-18，原7项正式验收完成）

### 71.1 目标、范围和来源依据

承接原方案§76：管理员先补齐Prod，DG再导入五个数据集的7个明确日期；Raw、Silver都要补齐，不修改Prod。本轮交付仅方案和LLD，不进入编码或正式写入。7项名单、00:36只读基线、源端资料依据及14111条缺失见§76.2与P0原始对账；其中源端数量已在本次对话逐项用MCP身份字段再次核对，Prod已用日期条件count复查，DG已查14个精确文件路径。当前没有逐字段重新核验7日来源，不能把这些计数当成补录完成证据。

输入严格为`moneyflow_mkt_dc: 2026-07-09`、`moneyflow_ind_ths: 2026-07-09/2026-08-05`、`moneyflow_cnt_ths: 2026-07-09`、`moneyflow_ths: 2026-07-06/2026-07-09`、`moneyflow_dc: 2026-05-19`。截止标记仍2026-09-30，作用仅为历史范围边界，不把查询展开成截止日前全表。五表使用[历史字段合同](../../orchestrator/src/orchestrator/defs/bootstrap/moneyflow_history_plan.py)，不给字段加列，不读api_name/fetched_at/raw_payload等内部字段；不使用BIYING、证券池、旧Lake或Kopia。

### 71.2 当前实现与最小改动落点

CodeGraph `codegraph_explore`追到source→date plan→candidate→promotion及event plan；`codegraph_impact`确认`publish_moneyflow_update_file`消费者为大盘/六表日更更新器，单unit候选函数目前没有其他正式调用入口。动态调用和全历史证明限制已直接阅读实现补齐；没有Foundation/Ops/Biz/QTF、Web/API消费者需要迁移。

| 当前文件/能力 | 本步复用方式 | 必须保留的边界 |
| --- | --- | --- |
| `bootstrap/moneyflow_history_metadata.py` | 单表`selected_dates`元数据请求及验证 | 不用None作为日期默认值，名单外禁止COPY；元数据SQL的NULL日期统计可保留，不能借此读取全量明细 |
| `bootstrap/moneyflow_history_plan.py` | 每个明确日期一个plan/unit，固定字段COPY SQL | 不把7项展开成“七表×四日期”；沿现有类型、主键、日期规则 |
| `bootstrap/moneyflow_history_source.py` | `PsqlMoneyflowHistorySource`及可取消有界管道 | 固定psql入口、READ ONLY、120秒；无任意SQL/DSN/表名参数 |
| `bootstrap/moneyflow_history_candidates.py`、`moneyflow_history_receive.py` | `build_moneyflow_history_unit_candidates`生成两轮一致的Prod Raw/Silver候选；`audit_history_day`实际校验 | 单日候选复验和source proof保持；不伪造cohort或把合并候选说成完整Prod镜像 |
| `io/moneyflow_update_publication.py` | 经本次计划校验后调用`publish_moneyflow_update_file`，逐文件CAS、intent、原子替换及恢复 | 函数没有“只补缺键”保护；调用前必须自己完成§71.4的旧值保留证明及目标旧摘要核对 |
| `io/moneyflow_candidates.py`及配置连接 | 路径/摘要/全资金流writer锁、512MB/1线程/no-spill连接 | 不新增锁实现，不在持有该锁时再次调用会自行获取同锁的候选入口 |
| `run_contracts/moneyflow_automation.py`与`metadata.py` | 固定asset/partition/check身份及现有metadata builder | 不修改既有自动化合同、字段或cursor版本 |
| `bootstrap/moneyflow_history_events.py`、`moneyflow_history_event_preview.py` | 复用原生事件协议、检查绑定和SQL验收语义 | 旧完整入口依赖全七表cohort且拒绝旧物化摘要变化，不直接执行、不放宽旧validator |

计划新增一个内部入口`defs/bootstrap/moneyflow_history_supplement.py`，集中负责7项范围校验、持久总预算、阶段推进、DC合并和本次原生事件接回；不注册active Definitions，不新增正式job/sensor或通用force开关。测试落在`tests/test_moneyflow_history_supplement.py`；如模块需进一步拆分，先回填本节，不能自行复制7套实现。正式操作薄脚本只调用该入口和既有GraphQL API，不自行实现导出/合并/写事件主逻辑。旧API/CLI及全历史cohort、promotion、event validator行为保持。

本次publisher的`audit_file`参数沿既有更新器绑定：大盘用`audit_market_moneyflow_file`，其余用`partial(audit_daily_moneyflow_file, dataset=...)`，以满足其`(connection, path, day, silver=...)`接口；`audit_history_day`用于两层成对的历史验收，不能当作单文件callback传入。底层函数签名和语义保持不变。

### 71.3 操作计划与配置审计

每份执行计划必须有版本、operation_id、计划SHA、代码摘要、正式instance只读身份、两根目录、固定截止日、7项有序列表、当前schema/日期/键数、源端身份依据和Prod两轮证明、目标旧文件SHA/大小、已有最新物化/check身份、动作阶段及写入上限。条目分别为`insert_day`（6项）或`append_missing_keys`（仅DC/05-19）。同一operation_id更改任一日期、数据集、来源、目标或保留规则均拒绝；新operation也不能借改名字重复登记已完成事实。

| 配置/输入 | 默认与来源/持久位置 | 消费者、生效方式与验收 |
| --- | --- | --- |
| 来源连接 | 复用`.env.web.local`与`PsqlMoneyflowHistorySource`，计划不保存凭据 | 只读source；每次沿现有psql入口；禁止env/DSN覆盖参数 |
| 路径 | 正式`/Volumes/datasource/data_lake`；候选`/Volumes/datasource/data_lake_staging/moneyflow/<operation_id>/...` | 原路径helper/validator；执行前核对挂载、同设备、拒绝符号链接/旧路径；/private/tmp仅操作报告 |
| 数据范围和模式 | 无宽泛默认值；必须显式传入并核对上述7项及模式，写入本次计划 | source、merge、publisher、event全部使用同一计划；增删日期/换模式反例必须0业务COPY/写入 |
| 既有共享限值 | 复用32MiB接收、512MB DuckDB/1线程/no-spill、768MiB RSS、单SQL120秒、64GiB最低余量 | 当前`run_contracts/moneyflow.py`及connector；本步不改其默认，不扩大其他数据集预算 |
| 本次更窄上限 | 每日候选≤10000行、总来源候选≤20000行；业务COPY14正常/最多16；元数据10正常，总只读连接24正常/最多26；已消耗数持久保存 | 补录入口计划中的固定政策，不新增env/DB/页面配置；读取/重试前计费，重启不清零，超限拒绝 |
| 操作成本 | 本次全部staging/控制证据≤128MiB、活动处理≤1200秒、DG元数据读取总计≤400次 | 含样本、恢复及开关核对，不能分表重置；预计2～5分钟只是估计，首次样本实测后复核 |
| 执行开关 | `apply=False`；物理发布、runless登记与暂停/恢复开关按审核清单分别批准 | dry-run只读正式环境，不能暗藏canary/目录/分区写；候选生成也是staging写入阶段，不能混称只读 |

候选API内部的`_Control`只记录本unit的业务COPY；新入口须在传入的source适配层对`copy`和`metadata`都先持久计费，根账本统一约束全部7项的连接/语句/耗时/磁盘。不能仅把每unit局部进度相加当成已有全局限额，也不能在补第2张表时重新开始计时。根账本写入失败时不发下一次来源请求。

单unit候选的路径以`operation_id+dataset+cutoff`识别，不能在同一个子operation下为THS或行业的两个日期分别传入不同plan，否则第二次会触发现有`history_plan_changed`。父补录计划固定派生每日期的`candidate_operation_id = parent_operation_id + "-" + YYYYMMDD`；每条仍是单日plan/unit-0，dataset维度由原路径保留。根计划保存7项到子路径的唯一映射，子ID不是可自由输入的新执行计划，所有子项共用父预算，不得借派生ID重置计费。仅遍历这7个子目录及父控制目录做空间核对，最多512个本操作文件，不能扫描整个staging。

上述更窄预算是拟新增补录入口的运行限制，不改变现行通用组件常量；消费者只有该入口和其测试。计划/进度报告显示阶段、当前表/日期、候选/发布/登记完成量、总数、最后更新时间、累计读取/时间及停止原因，ETA不确定时写“暂无法估算”。没有新增页面、服务或数据库状态表。

### 71.4 Prod就绪、候选生成和DC缺键合并

1. 管理员完成相应Prod任务后，按五表各自明确日期读一次元数据。审核Prod任务结束及当前无同日写入，不能只凭成功状态认定数据完整；复用同次可靠来源证据，缺失时对7日各做一次MCP日期/代码身份查询，确认返回未达到接口截断上限、日期正确、无重复，Prod候选键集合与来源一致。最多7个点请求，不拉其他日期；权限/截断/空结果不明时停止，不能换成全历史请求。
2. 逐日调用既有单unit候选构建：第一次COPY直接生成当日Prod Raw/Silver候选，第二次独立COPY逐字段验证。7项各自单unit，源行数当前合计16923、两轮33846；生成后五表再读一次元数据，比较schema、日期/键数保持。若数量与设计基线不同，先更新本步计划/预算与清单，不自动把未知差异纳入写入。
3. 六个`insert_day`必须在预检时确认对应两层目标都不存在。若已存在，只能在同一补录操作的持久证据能够解释时接回；未知文件、仅一层存在、其他写入者或旧事件不匹配均停止，不能一概覆盖。
4. DC旧Raw/Silver先通过物理合同、逐字段转换、已有物化文件摘要及当前同日检查核对，固定旧文件SHA和旧事件身份。原历史登记只保证最近20来源日检查，不能要求05-19一定已有check：若该日缺检查，本次只读完整SQL建立基线证明，不伪造旧passed事件；若已有同日检查，则核对其实际状态/目标物化，失败或过期先停止分析，不能继承别日绿灯。通过实际SQL确认：旧键是Prod候选键的子集；旧键数=2812，新增键数应由当前对账得到（本次基线3143）。有旧键不在Prod、重复键或错日期即停止。现有值与Prod的差异数量只作旁证，不能成为自动覆盖理由；此前212是历史数字，不要求重采后必定还是212。
5. DuckDB SQL生成最终Raw：`SELECT <合同字段> FROM old_raw UNION ALL SELECT <合同字段> FROM prod_raw ANTI JOIN old_raw USING (trade_date,ts_code)`，按原业务键排序后`COPY ... TO parquet`；所有Parquet读取显式`hive_partitioning=false`。不是Python逐行合并，不插入NULL/0代替来源值。
6. 合并前后双向EXCEPT证明旧键对应的全部字段保留；新键对应值与Prod候选双向EXCEPT为0；最终键集合=Prod键集合、无重复、日期唯一。然后从合并Raw按`history_schema`的同一合同字段投影，仅将trade_date从YYYYMMDD转换成DATE，生成最终Silver并调用现有物理标准化SQL核对。不要调用要求Tushare两轮receipt的日更Silver candidate builder并伪造其证明；本输入是历史Prod候选加DG旧记录。
7. 合并证明记录旧Raw/Silver摘要、Prod候选摘要、缺键集合摘要/数量、保留/新增/最终行数、最终两层候选摘要及SQL差异计数。与Prod的来源候选证明分开保存，不改写原receipt，不把合并结果的摘要塞回Prod镜像证明。旧Raw被原子替换后，恢复仅需核对已持久证明所绑定的候选/新文件摘要，不能要求重读已不存在的旧Raw或重新从Prod推算旧值；不复制旧文件作备份。

### 71.5 发布、自动更新与原生登记

正式前保存七表14个Raw/Silver更新sensor的原状态/身份/cursor摘要，只暂停原来RUNNING的这些项并读回；7个日期登记器和其他sensor不动。等相关活动/排队任务归零；发现其他资金流writer持锁则停止，不抢锁或取消任务。七表更新器共用`moneyflow/writer.lock`且为非阻塞获取，只停目标五表不足以避免另一表与本步冲突。

候选构建入口自行持有/释放现有writer锁；跨入发布/登记阶段再次获取同一锁并重新核对目标摘要、正式instance、计划和来源证明，不能外层持锁再调用单unit入口造成嵌套锁冲突。每个阶段重进都核对累计预算；全部写入串行。不修改原并发池、600秒评估间隔、22点、10日窗口、2026-10-01自动更新起点或默认STOPPED。

先完成该日期两层候选全量校验，再逐文件调用现有publication helper；DC调用前必须将当前旧摘要与计划基线比较，防止helper把“刚刚读到的新文件”误当成已批准旧基线。Raw/Silver分别os.replace，不声称两文件整体原子。日期未完成两层和SQL读回之前，不登记新的成功物化/check。已有DC旧事件保留，文件更新过程中的旧检查不能被当成新文件通过。

本次不调用要求完整cohort的旧`report_moneyflow_history_events`主入口，也不放宽其`history_event_existing_revision`。补录入口复用固定自动化合同、metadata builder和原生`report_runless_asset_event`：核对/补注册对应动态分区，写Raw物化→实际Raw检查并绑定该新物化→Silver物化→实际Silver标准化检查并绑定该新物化。全部7项都生成准确检查，不受旧“最近20来源日”抽查范围限制。metadata保存当前file_sha256、行数、Silver的raw_sha256、补录计划SHA/operation_id/来源及DC合并证明引用；不用假的cohort_hash，不伪造run或job成功。

原生状态是续接依据：写前按明确asset+partition查询当前物化/check；同计划、同文件摘要且绑定准确则接回，无则单次追加。DC只允许从计划所列旧storage_id/旧摘要前进到新摘要；发现另一操作或未知修订停止，不能忽略已有冲突。事件已提交、checkpoint未写时，按计划身份和原生记录接回；不能只看本地计数重发。保持旧物化/check/失败记录，禁止删除或reset。

当前预期12份新增文件、2份更新文件，14条新物化、14条新检查，至多6个新增partition key；DC原key复用。动作实际缺项在正式前逐项算出，不强行凑数；样本已完成的项在余下清单中只读接回。纯检查失败时不写passed事件，记录原因/有限样本并停，不以“登记”掩盖业务错误。

完成后独立进程读回7项文件/准确检查，再按原状态恢复本次暂停的sensor并读回，cursor不重置。若失败但尚未动正式文件，确认原数据事实保持、无活动写入后恢复原状态；若已有文件更新且该日期未完整交付，保持本次更新sensor暂停、显式报告已完成/剩余和具体原因，待同清单续接完成再恢复；不能在finally里无条件全部开启。恢复开关失败单独显示为未收尾，不回滚已提交数据，不自行重启daemon或reload代码。该入口不接active Definitions，正常不需要加载共享location。

### 71.6 持久阶段、中断和幂等

全部7项已accepted且文件/原生证据仍匹配时，重放在只读预检后直接返回；不再暂停/恢复sensor，不重新请求Tushare或Prod，不为重放另建候选。这样最终零新增验收也包含0开关变化。

每项按`planned → prod_verified → merged_or_passthrough_verified → raw_published → silver_published → events_complete → accepted`持久推进；总计划另保存原sensor状态、累计预算、样本完成及原生动作发送意图/响应。只有两层文件和准确事件都完成才增加“完成日期”。每个来源请求、单文件替换、原生事件前后检查取消和预算，长SQL沿现有可中断连接；不能把全7项置于长数据库事务。

- 完整Prod候选已验证时，发布/登记重放只查候选/目标摘要、证明和原生记录，0新增业务COPY；本次适配以已有验证证明作为续接依据，不盲目重调会独立复查来源的单unit构建入口。
- 在候选读取中断且无完整验证证明时，可重新读取该日，旧attempt保留并计入总预算；只有2次额外读取余量，耗尽即停止报告，不能换operation_id清零续跑成本。
- 替换前取消保留候选/旧目标；替换后checkpoint失败由原publication协议按intent和新目标摘要接回，不重建旧文件，不还原到旧版本。新目标与新候选不符、候选被改、旧基线被另一写入者改动均停止。
- 原生写入丢响应，先只读查相同身份；查不到明确结果时保持“不明”并停止，不盲重发。跨进程重启前先恢复原操作计划/暂停状态，不重新抓取一份新计划覆盖现场。
- 总阶段、行数、读取次数和已耗时间都从持久状态恢复；报告必须显示当前真实完成量，不把错误项导致整个完成数归零。每次重放的只读成本也计入上限。

### 71.7 性能和请求量

| 项目 | 本次基线/预算 | 拒绝条件与核验 |
| --- | --- | --- |
| 处理规模 | 五表7个单日unit；Prod候选16923行，DC旧2812行；最终每层16923、净增14111 | 不读名单外日期，不做全局明细；source/旧目标变化先更新审核依据 |
| Prod读取 | 元数据前后各5次＋每unit独立COPY两次14次=24连接/96语句；最多26/104 | 元数据请求与COPY均先计费；无自动重试；源只读COUNT例外不能扩大成全历史明细 |
| 来源返回 | 两轮业务读取33846行；MCP预检0～7次身份点查询，最多20000身份行 | MCP返回到单次上限、字段/日期/键异常或证明不足停止，不自行无限翻页 |
| DG读取/输出 | 旧DC两文件有界读取；7项候选/发布文件复核；最终14文件、约几MiB，精确大小由候选给出 | 不全历史hash/逐日readiness；审计只围绕14路径和对应原生事件 |
| 内存/磁盘 | 原32MiB缓冲、DuckDB512MB/1线程/no-spill、进程RSS768MiB保持；本操作staging/控制证据≤128MiB，现有最低空闲64GiB保持 | 含候选、校验、中断保留attempt、合并文件及证据；超限停止，不安装扩展、不spill或做快照 |
| 时间/观测 | 预计2～5分钟待实测；SQL≤120秒、累计活动≤1200秒、DG元数据读取≤400次 | 暂停等待不重复清零；等待已有任务单次≤120秒，不取消它们；超时结束本次预检并报告 |
| 正式动作 | 业务job0；文件12新增/2更新；物化14、检查14、分区新增≤6；候选和发布分段，sensor最多28次stop/28次start | 每类动作独立计数；实际原本STOPPED不操作；开关和资源canary不得伪称“零正式写入” |

本次只读审计与将来补录均不需要全局数据读取。开发/执行前若认为必须全局读某数据集明细，须按根“数据集全局读取审批”说明范围/方式/成本并另获批准，禁止拆批绕过。不得为本方案追加全7804日期审计、全21百万行比较或重分区。

### 71.8 测试和真实验收清单

先复用现有`test_moneyflow_history_plan.py`、`test_moneyflow_history_candidates.py`、`test_moneyflow_history_selected_dates.py`、`test_moneyflow_history_promote.py`及`test_moneyflow_dc_events.py`对应能力；不修改其已有预期来迎合补录。新补录测试必须覆盖下表，不用数量代替语义。

| 硬口径 | 正向证明 | 反例必须拒绝 |
| --- | --- | --- |
| 只处理7项 | FakeSource记录SQL，明确7个单日unit；源=两层候选行数/字段正确 | None日期、七表×日期展开、其他源/表/日期、scope或plan摘要改变，0业务COPY/正式写入 |
| Prod已补齐 | 真实合同小样本/独立预期键集合与当前候选一致 | 只有任务成功但少键、空日、截断、重复键、schema/字段/日期错误 |
| DC只补缺 | 独立3行金样本：DG旧2行、Prod3行且一个旧键数值不同，最终旧2行不变、仅新增第3行；NULL/负值保留 | 整日替换覆盖旧值、旧键丢失/重复/错误日期；不得调用merge helper生成expected |
| 来源证明分离 | Prod全候选证明与合并证明各自摘要可读回，最终Silver与合并Raw一致 | 把合并候选当Prod逐字段一致、伪造Tushare两轮receipt/cohort |
| 原子发布/恢复 | 复用真实临时文件和os.replace；Raw替换后退出、Silver替换后checkpoint失败均可续接 | 外部改旧目标、新候选篡改、路径/跨设备/符号链接，保留已提交文件，不覆盖冲突 |
| 原生事件不重复 | 临时Dagster SQLite、真实Parquet/SQL，旧DC物化及已有check保留，新检查准确绑定新物化；旧历史无同日check可经完整基线SQL进入；丢响应/退出续接0重复 | 旧绿检查冒认新文件、只更Raw就记完成、未知旧revision、伪passed、只有checkpoint无原生事件 |
| 自动更新隔离 | 14个更新sensor实际状态替身/当前schema验证，原本STOPPED保持、注册器不动 | 未暂停共同writer就写、活动任务未结束、无条件finally开启、游标reset或开其他sensor |
| 成本与进度 | 一个计划跨7项累计，取消/重启/样本后续跑均不清零；完成量单调 | 超128MiB/1200秒/400读/26连接、重复COPY、失去预算仍继续 |

隔离集成只用3行DC和1行大盘等字面样本、临时instance与临时Lake，不访问正式源或故障注入；复用原传输/30秒实验，不重新等待长稳定轮次。源字段夹具以本地原接口文档、P0真实样本和当前Prod生产者为依据，错误fixture标注为反例。新增测试运行规则：开发前确认`tests/test_moneyflow_history_supplement.py`存在后，从orchestrator目录用现有`.venv/bin/python3 -B -m pytest -q -o junit_family=legacy --junitxml=/private/tmp/moneyflow-history-supplement.xml tests/test_moneyflow_history_supplement.py`执行；再只跑受影响既有模块中的相关用例，总隔离验收预算≤120秒，不人为等待60秒、30秒或拉取真实网络。共享helper若未修改，不重复其整套回归；若发生必须修改共享helper的范围变化，先更新本节/方案并按影响面补相应回归。默认Ruff只检查本步新改Python文件，原受保护静态/目录/catalog检查通过既有启动器执行，不改其库存或豁免规则。若环境不能满足预算，先解释实测瓶颈再调整方案，不能跳过负向断言。以上均使用现有环境，不安装包、不绕过受保护启动器。

正式先做大盘1行的2文件/2物化/2检查及分区读回，再按同清单完成剩6项。最终验收需同时满足：五表7项键集合完整；六项新增字段与Prod逐字段相同；DC旧2812行保留、新键值与Prod一致；两层schema/日期/键/行数/转换一致；14文件摘要与14准确物化/检查绑定一致；旧DC事件保留；更新sensor恢复原状态；同一清单重放0新增业务COPY/文件变化/分区/物化/check。任何来源变化导致实际规模不同，先刷新该计划及文档中的准确数字，再进入正式apply，不提前填通过。

### 71.9 本轮设计审计结论与后续授权

审计已处理当前实现不适配的位置：旧cohort七表共同范围、旧promotion拒绝不同摘要、旧事件validator拒绝修订、单unit同数据集多日期的plan路径冲突，以及旧历史只保证最近20日check而非05-19必有check；选择单unit候选＋现有publication＋范围专用事件接回，保持旧保护不变。已审计共享writer、日期窗口、readiness的file_sha256/raw_sha256/准确check绑定消费者；已将DC缺键与已有值修订分开，并补齐Raw后退出、事件后退出、暂停状态恢复和计费续接设计。上述结论来自当前代码，CodeGraph影响面与人工核对补足边界已列§71.2。

本方案具备指导下一步补录入口开发和最小隔离验收的内容，但入口/新测试尚未实现，不能把本节称为新增代码验收。正式执行清单还需等待Prod补齐后产生当前来源/目标/原生身份及源码SHA，再按阶段批准数据/事件写入和短暂停止/恢复更新器。现在不实施任何正式操作；不把本轮写文档的授权当作补录批准。若后续改成DG直采或允许覆盖已有值，先回填原方案和本LLD、审计新成本与范围，再继续。

本轮文档门禁：原文档相对引用、7项/16923总行/14111增量对账及`git diff --check`通过；全仓`check_docs_integrity.py`通过。未运行新增补录测试或正式操作，这些仍属于后续开发/执行验收，文档检查不能替代它们。

### 71.10 Prod就绪核验及代码缺口复核（2026-10-18 01:03）

方案提交78b444d5后，按管理员要求对7项做有界只读核验：[完整报告](../../reports/moneyflow_history_supplement_prod_ready_audit_20261018.json)。五表7日Prod日期/代码投影共16923条，键集合与00:36已获取的MCP身份记录完全相同，缺/多/重复/空键均0；一个只读事务7条查询，每日LIMIT10001防止不受控返回，无全历史明细扫描。DG14个精确路径中六日12文件仍不存在；DC05-19两层均2812条/2812键，两层键集合一致且为Prod子集，差3143键；合计缺14111条/层。DC当前Raw SHA为67e22f627a79ffa4ad1abafe964e224b988bcbce4e8439ef7e6534f564c44d96，Silver为9ea615b7de45f2400a0e66e4d16dc2f0f18a69f0d6b9a4e334903d2a56f29fbd，仅作本次审核事实，正式执行前重新核对，不当成无期限执行授权。

代码复核使用CodeGraph explore并直接阅读：`build_moneyflow_history_unit_candidates`确实可复用单表日期plan及来源复验，但同dataset/cutoff共享plan路径，仍按§71.3固定派生子operation防冲突；现有cohort仍强制七表；旧promotion和event state仍分别拒绝已有不同文件摘要/物化修订。`moneyflow_history_supplement.py`当前不存在，所以不是“只跑现成命令即可完成”。需要新增范围专用入口、DC保留旧值的ANTI JOIN合并、修复文件的新事件/准确检查接回及其隔离测试；不修改旧validator或新增全历史读取。Prod已补齐不消除这几项代码缺口，既定方案保持。

此次未读业务金额字段，未逐字段确认新Prod所有值，也未用正式instance跑测试；完整字段/精度、候选两次独立来源比较、旧值保留、实际物化/check身份、暂停恢复和幂等执行继续按§71.4～8验收。没有源端新请求、Prod写入、DG写入、原生事件、sensor开关、代码加载或业务实现修改。此报告不替代正式执行清单，不将数据就绪说成新增补录代码验收通过。

### 71.11 编码前的接口及恢复审计（2026-10-18）

本轮目标为补齐代码和低成本隔离验收，再只读审计正式条件。正式Lake/staging、sensor、分区和事件本轮均不写。新增以下文件，均位于`defs/bootstrap/`，不接入active Definitions：

| 文件 | 职责和接口 |
| --- | --- |
| `moneyflow_history_supplement.py` | `prepare_moneyflow_history_supplement`只读生成7项审核计划；`apply_moneyflow_history_supplement`要求显式apply及计划摘要，串行协调来源、暂停恢复、发布和事件；样本模式只发布首项，候选共用同一计划 |
| `moneyflow_history_supplement_control.py` | 固定7项范围、计划/源码/instance身份、原子JSON、根预算和进度；读取与执行共享固定限制，不加env或运维配置 |
| `moneyflow_history_supplement_files.py` | 旧文件基线、已验证来源receipt接回、SQL缺键合并和证明、受控逐文件发布；复用现有候选、连接、发布组件 |
| `moneyflow_history_supplement_events.py` | 原生按asset+partition读取、旧身份固定、新物化/check精确绑定、intent和丢响应接回；不改旧cohort validator |
| `moneyflow_history_supplement_sensors.py` | 固定14项更新器GraphQL状态/stop/start，复用当前NativeBackend HTTP；不提供任意sensor参数，不操作登记器或cursor |

计划包含固定scope、日期/代码身份证据、五表前置metadata、目标两层旧摘要/行数/事件身份、正式instance身份、源码摘要及固定路径。真实正式数量须与§76.2一致；隔离样本允许缩小行数，日期和数据集仍固定7项。来源证据必须明确提供，不能把Prod自身键集合当作Tushare证据。准备阶段SQL只写临时审计目录，不创建正式staging；5次metadata读取纳入后续父账本。`apply=False`只验证计划及当前事实，不能产生staging、canary或开关操作。

实际Dagster版本支持`get_asset_check_execution_history(..., partition_filter=PartitionKeyFilter(key=day))`，本步按明确日期查询，不从最近若干个其他日期的check推断。每次读取均计入根400次上限。旧历史缺同日check允许物理SQL验证进入；存在的同日check必须准确绑定旧物化、状态成功。新check必须绑定本次新物化storage_id，成功报告前已完成真实文件SQL；事件已提交但本地落盘失败时以原生记录接回。已有intent而读不到结果时停止为结果不明，不自动重发。

先生成全部7项来源候选并完成五表后置metadata对比，才允许发布首项。每项来源候选receipt独立保留；合并结果另存证明。父操作目录复用`moneyflow_writer_lock`作控制器生命周期锁；候选调用自身持资金流共享锁，合并/发布/登记再分别持共享锁。最多7个不同子operation（按日期派生，dataset仍是路径维度），所有开销共用父账本，不能复用子ID重新计费。阻塞来源请求先持久预留120秒；进程正常返回按实际耗时结算，进程退出则保留预留，避免重启清空时间。线程内取消/心跳和目录预算检查沿已有0.1/0.2秒检查回调；根进度最多间隔30秒输出阶段/日期/完成量及累计开销。父根加7个子根的字节/文件检查不得扫描整个staging。source COPY≤16、metadata≤10、总连接≤26，总SQL≤104，其他限额仍为§71.7。

发布前只接受计划中的旧摘要或本操作已持久证明的新摘要；publication checkpoint中的candidate/prior/published摘要须与父证明一致，不得借已有checkpoint绕过目标CAS。候选已被移动到目标时按intent接回；原来源receipt和DC保留旧值的证明不变。原生动作先写intent，按原生事实接回；部分日期已变更且未验收则不恢复自动更新。全部7日已验收后重放只读，不暂停更新、不请求Prod、不创建文件或追加事件。样本停点完成后保持本操作暂停状态，剩余项续跑验收完成后才按最初状态恢复。

测试入口`tests/test_moneyflow_history_supplement.py`及必要拆分测试文件，使用字面三行DC（金样本旧值、NULL、负数与Prod旧键不同值）与其余六日各一行；真实临时Parquet、原publication、临时SQLite Dagster实例，Source和更新器替身仅替代网络。须覆盖范围/摘要/类型拒绝、缺键旧值保留、旧历史无check、准确新check、事件和发布中断续跑、零COPY重放、计划/目标篡改、暂停恢复、取消及预算持续。GraphQL请求另用已安装schema纯验证；新接口不依赖真实网络测试。pytest显式使用独立的`--basetemp=/private/tmp/moneyflow-supplement-tests-<本轮编号>`，因为现有instance身份校验只允许`/private/tmp`，不能为macOS默认临时目录放宽边界。共享helper不修改，按§71.8仅补受影响旧例及原启动器静态/目录/catalog门禁；隔离目标总计120秒以内，禁止真实稳定轮次等待。正式审计复用已有源身份证据，若需字段边界只读验证最多抽取两条指定日Prod记录，不扩大到全历史，也不将隔离通过说成正式数据已补齐。

编码自审补充：前后metadata正常共10次，2次额外来源连接的恢复余量由COPY和metadata共用，总连接26不变，故metadata独立上限为12（COPY仍16），不能两类各自再加2。后置每表通过即保存结果，恢复只补未完成表。预算在来源请求前及每个候选/发布阶段检查；已全部验收的只读重放使用内存中的受限读取计数，不回写完成账本，满足0文件变化。准备阶段元数据读取数和活动耗时写入计划，在执行根账本初始化时继承，不漏算准备阶段；正式候选和金额字段完整验证仍留在获得执行批准之后。

DC合并中断时若尚未保存完整证明，旧正式文件仍在，允许在新的合并attempt子目录重做SQL，不额外读取Prod；保留失败候选并继续计入512文件/128MiB限制，不删除旧文件。暂停请求丢响应但原生状态已是STOPPED时，可按原id/cursor和已持久intent确认成功，再恢复原RUNNING状态；状态仍不明确则停止，不重发。

真实SDK审计补充：已安装Dagster的`asset_check_executions`对asset/check/run_id/partition有唯一约束，runless使用空run_id，因此同日同名旧runless检查不能直接追加第二条。2026-10-18本次7项逐日检查均不存在，不影响当前范围；预检若后来出现旧runless检查必须在发布前拒绝，不能删旧记录、改库、伪造run或另起check名称绕过。原§71.4的“已有同日check可进入”仅在其来自实际任务、与旧物化准确绑定且不会占用空run_id约束时成立。未来出现该冲突须重新审计并确认方案，当前入口不承诺通用检查修订能力。反向测试使用真实原生物化修订使旧check绑定失效，不能制造违反SDK存储约束的测试输入。

### 71.12 候选审核与发布必须分段

本节把既有§76.5第3～4项落实为代码硬停点，并非新增数据范围。公开维护函数增加`publish=False`（默认）、`expected_candidates_sha=None`两个显式参数，只有本入口和隔离测试消费；来源为调用者传入并与父目录`candidates.json`逐项校验，不是新增env、持久配置或服务开关。`apply=False`仍全程只读。`apply=True,publish=False`生成7项来源候选、后置metadata、DC合并证明，写下包含7项两层摘要/证明摘要的候选清单，确认正式文件未变后恢复原更新状态并返回；不登记分区/事件。正式执行前将该清单及摘要纳入审核。

`apply=True,publish=True`必须在任何来源/开关/文件动作之前，核对管理员已审阅的`expected_candidates_sha`和现有候选清单。缺摘要、摘要不符、与父计划/逐项证明不符均拒绝；本阶段不能边生成未知候选边发布。继续复用已验证来源、DC证明和同一账本，0新增Prod COPY或metadata；重新暂停原RUNNING更新器，核对文件与事件没有未知变化，然后执行大盘样本停点或剩余项。样本完成后依§71.11保持暂停，全部验收后恢复原状态。全部accepted只读重放仍无需暂停或重导。

正常多一次暂停/恢复循环，最多28次stop和28次start（实际按原RUNNING数量）；元数据读取仍≤400、正常来源24/最多26连接、1200秒、128MiB和512文件不变。暂停请求与恢复请求每轮分别按intent/原生状态接回，不复用上一轮“已暂停”作为当前事实。部分正式文件已变更时禁止退回候选生成阶段去恢复开关，只能继续原发布清单；生成阶段中断则保留候选与账本，按旧基线确认未改正式文件再恢复更新器。隔离端到端必须使用同一两段入口，不能为测试绕过候选摘要门禁。正式审计只生成只读审核计划，尚无正式候选摘要时，结论只能为“具备进入候选生成准备的条件”，不能称已获得正式发布批准。

读取预算复核：每层事件登记后的原生读回同时验证完整物化metadata和准确check绑定，当日接受无需马上重复同样读取；全部7日完成后仍另做独立物理/原生读回，保持验收强度。恢复用例须额外再做一次完整只读重放，累计读取不得超过400，不能只测无中断的正常路径。

### 71.13 开发与只读验收记录（2026-10-18 01:46）

当前进展以原方案§76.9为准，§71.1/9/10中的“待开发”是此前设计/来源审计的历史状态。本步5个模块已实现，`tests/test_moneyflow_history_supplement.py`46项通过，复用真实字段和日期SQL合同13项通过，共59项/47.06秒；静态113项、catalog治理12项和原根边界门禁通过，未改受保护启动器或共享validator。硬口径→代码→正反测试映射、源码SHA、只读范围、临时证据及残余边界在[开发就绪报告](../../reports/moneyflow_history_supplement_development_readiness_20261018.json)。没有新的asset/check/job/sensor定义或跨Foundation/Ops/Biz/QTF依赖，既有API/CLI行为保持。

最小链路用真实临时Parquet、publication和SQLite原生事件验证；只有网络Source/开关用替身，不能据此声称正式全量金额通过。实际Prod另按05-19明确两个代码抽取2行，完整历史合同转换与SQL检查0拒绝；首个临时审计脚本误将接收buffer置于开头，修正审计脚本后独立重读两行验证，共2次两行查询、4行读取，没有修改生产实现或正式数据。五表7日metadata和此前MCP身份依据仍完整，01:46实际DG文件/事件/开关/活动任务/写锁复核通过。

隔离正常计费为COPY14、metadata10、连接24、原生读取327；最重恢复读取371，后续独立只读重放累计400。候选阶段结束时正式文件/事件不变且更新器恢复；没有候选摘要不能发布。全部通过后0新增业务COPY、0文件变化、0重复事件/开关动作，不靠删checkpoint或换operation清账。旧runless检查唯一约束已按§71.11在发布前拒绝；当前实际14项旧check均缺，因此没有这一阻断。

[只读计划](../../reports/moneyflow_history_supplement_readonly_plan_20261018.json)及其摘要见§76.9，尚无正式`candidates.json`。后续先按`apply=True,publish=False`生成候选并恢复开关，审核两层与来源/合并证明后，才按`publish=True,expected_candidates_sha=<审核摘要>`进入样本或其余发布。候选阶段使用只读instance；正式事件发布必须显式构造原helper的`writable=True`实例并先核对其角色写权限，禁止用写探测替代审核。每阶段按原方案授权，正式命令/目标实例/读写边界在执行前列清，不安装依赖或加载共享Definitions。本轮只读结论为可进入候选准备，正式数据补齐仍未执行、每层缺口14111条保持。

### 71.14 本轮正式执行与执行前预算修正

目标、授权和7项范围承接原方案§76.10。先修正`moneyflow_history_supplement_sensors.idle`的读取方式：当前每轮对14个job分别`get_runs(limit=1)`，读取预算会被正常的全14项RUNNING及样本续跑耗尽。CodeGraph explore追到prepare/apply调用方，直接阅读SDK的`RunsTable`、SQLite/Postgres `run_storage.connect`，确认可用同一原生连接执行`SELECT run_id FROM runs WHERE pipeline_name IN (<固定14个job>) AND status IN (<现有ACTIVE状态>) LIMIT 1`。使用SDK表定义构建绑定参数SQL；只返回最多一个任务ID，不读run_body，不扫描其他job，不引入其他数据表。每轮通过父Control计费一次，仍等任务归零，最多120秒，不取消任务；不能为预算改成只看某一个job或无限扩大限额。

改动范围仅该内部函数及其测试；没有新配置/存储/Definitions/CLI/业务合同。临时SQLite中通过真实`run_storage.add_run(DagsterRun(...))`造当前SDK合同的运行记录，验证14个job中任一个QUEUED/STARTED都会阻断、无关job不阻断、单次一次只读查询；不再mock已不调用的get_runs。另加14个更新器全RUNNING的候选—样本—剩余6项—只读重放用例，确认预算≤400、COPY14/metadata10/连接24、原开关及cursor恢复、0重复文件/事件。重跑原59项和原静态门禁，不修改旧预期来掩盖来源或登记错误。

正式执行使用当前orchestrator `.venv/bin/python3 -B`，工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`。受审临时脚本`/private/tmp/moneyflow-supplement-execute-20261018.py`只提供固定步骤`review/candidates/sample/complete/audit`，每步命令为`.venv/bin/python3 -B /private/tmp/moneyflow-supplement-execute-20261018.py <步骤>`。不是新增持久CLI。准备读取当前五表7日metadata及旧14目标/原生记录，复用已有Tushare身份证据，按固定白名单字段/日期通过原psql只读入口COPY；正常源读取24连接/96语句、16923行两轮，最多26/104。正式instance固定`/Users/congming/.goldenshare/dagster_home`，PostgreSQL `goldenshare_dagster`，不自动建表或加载Definitions。

`review`只读并保存仓库执行清单及临时审计文件；先读回DB角色对原生事件/分区表及sequence的写权限，禁止写探测。`candidates`按`apply=True,publish=False`只写`/Volumes/datasource/data_lake_staging/moneyflow`本操作及派生7子目录，暂停后恢复原14项；逐字段/键/日期/精度/两层转换及DC原2812行不变、新3143行一致的SQL通过才保存候选清单和摘要。审核者按本轮授权对照这些明确条件审核，不以本地checkpoint代替数据或原生事实；出现差异停止。

`sample`和`complete`使用同一执行计划、同一候选摘要及`daily_basic_event_instance(writable=True)`，依次只发布大盘07-09和剩余6项，样本属于原7项、不重复导出。正式仅新增12文件/更新DC2文件、追加14物化/14准确检查、最多6分区；14个更新器按两阶段原状态暂停/恢复，登记器及其他开关不动。异常保留已完成文件和逐项证据；未完成的正式发布保持暂停，续接同一计划，不删除旧文件/事件，不重置成本。全部accepted后`audit`独立进程核对14文件schema/键/行数/摘要、准确原生绑定、旧DC事件保留及原开关/cursor，然后同计划只读重放确认0新增COPY/事件/文件/开关。独立审计查询单独受限≤80次，不参与任何写入，执行器自身累计仍≤400；不使用全历史扫描或实际交易日观察替代本次7项验收。

执行前结果：原59项加16项本轮针对性用例共75项通过，53.84秒；原受保护启动器113项静态检查和变更文件Ruff通过。排队fixture按当前SDK补齐实际RemoteJobOrigin记录，没有降成其他状态或mock查询。正式只读`review`已成功，五表7日计数未变、14项RUNNING，新的批量任务查询在真实PostgreSQL通过；原生5表SELECT/INSERT/UPDATE及关联sequence USAGE均具备，显式可写instance的`transaction_read_only=off`已只读查询确认，未试写。当前[正式执行计划](../../reports/moneyflow_history_supplement_execution_plan_20261018.json)以本轮源码和现场为准，取代上轮仅供审阅的旧源码计划；尚未生成候选时不得称正式数据已补齐。

#### 71.14.1 正常检查时间更新造成的误判

实际首次candidates在`apply`创建操作目录之前报`supplement_sensor_baseline_changed`。只读差异证据在`/private/tmp/moneyflow-supplement-execution-20261018/sensor_change_readonly.json`：仅THS Raw cursor的`evaluated_at`变化，其余完整JSON相同，14项状态/id均保持。实际生产者`moneyflow_update_selection.py:115`的before_window分支每次调用`build_sensor_cursor(evaluated_at=now,...)`，`run_contracts/cursors.py`将其序列化为顶层观测时间，不是处理进度。不改变“cursor不重置”的要求。

修正在本次补录内部`moneyflow_history_supplement_sensors.py`增加cursor及单项/整组状态比较函数，供transition、apply预检/完成重放及受审脚本使用；不改共享cursor生产者、schema或现行更新器。字节相同（包括None/现有文本测试值）直接通过；不同值必须都是当前schema 1的完整8键JSON，`evaluated_at`须为合法带时区ISO时间，其余7项递归完全相同，才允许只去掉该时间比较。id/status/集合完整性仍精确匹配，禁止忽略runtime_state、reason、计数、日期或其他新增字段，不能通过更新时间掩盖任何进度改变。只读取、不提交新的cursor值。

补齐时间自然更新的真实生产者夹具和完整两阶段用例，反向覆盖进度/日期/身份/状态/非法时间/未知schema/新增字段变化；原75项保持。旧误判发生前尚无本操作目录，先保留原plan及差异记录，再将原五表metadata、源键、旧目标/事件不变的依据与修正后源码、最新开关观察值重新绑定为执行清单；不重复Prod请求或清零已发生的候选成本（目前0）。本步正式范围和预算不变，继续原7项修复。

结果：85项隔离/既有合同测试通过，52.79秒，原113项受保护静态门禁通过。真实cursor每次正常检查更新时间的两段+样本+全量+重放用例通过，进度/日期/数量/身份/状态/schema/非法时间/新字段9类反例均拒绝。原计划保存在临时审计目录`plan_before_cursor_fix.json`；对首次拒绝和两次额外只读查询保守追加31次读取、60秒活动预算，仍遵守原400/1200上限，没有已发生的COPY被清零。父计划准备读取现71，候选生成后累计133。

正式7项候选及独立SQL审核已通过，具体摘要和数量见原方案§76.10及[候选审核](../../reports/moneyflow_history_supplement_candidate_review_20261018.json)。尚无正式文件/事件变化，Source连接24/COPY14/metadata10，14更新器已恢复；执行者依据本轮完整修复授权和既定全部条件核验通过，接下来只向`sample`/`complete`传入上述同一候选摘要，不再读取Prod。cursor恢复/审计比较仅允许正常检查时间自然变化，原处理进度必须不变。

#### 71.14.2 样本通过后共享源码发生变化的安全收尾

大盘07-09样本已发布，独立进程验证两层各1行、SQL/摘要/2物化与2准确检查绑定通过，source计费仍24连接、14COPY、10metadata，父读取168。继续complete时，在任何剩余写入之前被`execution_code_changed`拒绝。只读差异证据`code_difference_readonly.json`确认仅`stock_adj_factor_history_repair_cli.py`从计划59bf68d3摘要变为ec81949a，其他资金流执行模块及其余源码都与清单相同；Git HEAD也在本任务执行期间由其他操作推进。本任务没有修改该复权CLI，禁止覆盖其他任务改动或绕过发布入口的源码核对。

安全收尾仍属本轮已批准的暂停/恢复范围：先逐项核对全部正式目标，只有样本两文件与已审核候选一致、其余12路径仍符合旧基线，且样本原生物化/check准确、剩余6项仍未accepted；再确认14个更新job均无活动任务。因为唯一已改变日期已完整验收，不存在半个日期的未完成发布，允许按原规则恢复原14个RUNNING更新器，保持处理进度/cursor、不重置任何值。使用原计划中摘要仍匹配的现有transition函数，只做失败收尾；不调用被拒绝的publish，不改任何业务文件、旧事件或计划摘要。保存共享源码差异、实际文件/事件、开关恢复结果和未完成清单。原source/候选/计划/账本完整保留，源码阻断未解决前不领取剩余项。

后续须先按根AGENTS“工作区存在阻塞…必须停下…等待用户处理或明确授权”协调共享工作区。本次整个orchestrator源码清单的保守核对范围过大，不能把“另一个CLI变化”说成资金流算法变化；需要单独明确如何审核并更新本次执行代码依据、保持原数据计划/已登记身份和候选证明可续接，再按“方案及LLD先于代码”落地。不临时改plan哈希、伪造code_identity、不删除进度或重导已完成来源。此处尚未授权源码例外或恢复他人文件。

安全收尾于02:21完成，见[实际报告](../../reports/moneyflow_history_supplement_shared_source_blocker_20261018.json)：原14个RUNNING更新器全部恢复，cursor没有reset；收尾业务文件/事件写入0、Prod读取0。父账本累计连接24、COPY14、metadata10、DG读取188、物化2、检查2、新分区1；阶段为`waiting_for_shared_source_review_updates_restored`。已经接受的仅第0项大盘样本，其余6项仍未接受，文件基线保持；源、候选、原计划及进度保留。再次对比完整源码清单仍仅该复权CLI不同，无新增Python文件；外部提交`98b0817c0`不会自动解除旧计划的源码差异。

当前不是“全部修复完成”或“可直接重跑complete”的状态。新的源码审核与续跑方式尚待明确，暂不修改原计划、候选摘要或原生身份，不因开关已恢复就领取其余日期。85项本轮隔离/合同测试和受保护静态113项通过，不能代替未完成6项的正式文件、检查绑定和最终幂等验收。

### 71.15 经批准修正检查范围及原操作续跑设计

管理员已允许保留共享改动、修正检查后继续补录。本节在代码修改前完成。目标仅为解除无关复权CLI对本操作的误阻断，并让原7项在同一计划、候选和账本下完成；禁止篡改旧计划、重新导出、绕过检查、覆盖其他任务源码、扩大日期或已有值修订范围。

**当前依据与影响面。** CodeGraph explore/impact确认`code_identity`的消费者为prepare和validate；直接阅读apply、临时执行脚本和完整旧计划发现两处整工程相等检查（control及执行脚本）。静态AST核对四个真实入口：`moneyflow_history_supplement`、`moneyflow_history_source`、`daily_basic_event_instance`、`moneyflow_continuation.state`，本地导入闭包74文件，包含catalog/name mapping、所有引用schema、checks/readiness、paths、DuckDB和publication；所有父包初始化文件也执行，必须包括。闭包唯一子进程为原`psql-remote.sh`，无动态Python导入；间接种子为`major_indices.cn_a.csv`。复权CLI及planning不在闭包。此分析不授权修改共享catalog或放宽这些真实依赖。

**代码与配置。** 新增`defs/bootstrap/moneyflow_history_supplement_code.py`只负责有界AST依赖发现及文件摘要；采用上述固定四入口，追踪绝对本地import/from和父包初始化，拒绝未经审计的相对import；共享模块整文件计入。最多150个Python依赖、每文件≤2MiB，总体≤16MiB；路径必须位于工程src下、拒绝symlink和缺失的模块来源。额外固定核对project的`pyproject.toml`、`uv.lock`、上述CSV及仓库`scripts/psql-remote.sh`，不读取或输出.env密钥。仅本地文件读取，无网络、DB或新配置项；固定预算是本步骤实现边界，非env/页面/DB配置。现control的`code_identity()`转为调用该模块；公开prepare/apply的业务语义保持。

**源码审核记录。** `validate_plan`及apply增加可选`source_review`、`expected_source_review_sha`参数，默认None。无记录时必须与计划源码清单完整相等，不把旧整工程清单投影后自动放行。有记录时必须同时提供摘要，记录只含revision、`plan_sha256`、`prior_code_sha256`、`candidates_sha256`及完整新`code`五项；分别绑定原计划、旧源码清单、已核验候选和当前完整依赖清单。任意缺项、多项、错摘要或当前相关源码变化均拒绝。它是显式重新审核代码的依据，不能伪称原源码未改变；没有自动生成并无条件信任新hash的路径。正式记录由本任务在设计、代码和测试审核完成后生成，临时执行脚本显式固定其摘要并传入新接口，替换原整工程相等断言。

apply须在任何正式写入前确认原父目录已有候选且其摘要与审核记录相同；原计划文件、候选文件和每项证明不修改。第一次正式续跑在父控制锁内原子保存`source-review.json`并把摘要存入原state；已有记录/摘要必须完全相同，不可重写换版本。只读审计不能首次保存记录。中断若只保存记录而尚未保存state，下次允许同一记录接回；state已绑定但记录丢失/变化则停止，不自动重建。完成后只读重放核对同一记录，不写state或重发事件。每日期发布前重核相关源码及审核记录，避免检查后源文件变化。数据计划身份、候选身份和所有已有/新增事件的原计划关联不变；新代码依据由同一操作内审核记录追溯，不新增资产、表、配置或第二条业务状态链。

**续跑与失败。** 保留当前1项accepted及188次读取等账本，先以新审核记录只读核对14文件及原生记录、开关/相关活动任务；依照原候选继续6项，Raw/Silver与登记失败恢复仍按§71.4～6。14个更新器仅在正式续跑期间暂停、完整读回后恢复原状态，不reset游标、不改登记器或22点规则。失败仍保留原文件/checkpoint与候选，不能因代码检查修正清零计费或删除旧样本。正式命令仍从orchestrator目录调用`/private/tmp/moneyflow-supplement-execute-20261018.py complete`和`audit`，正式instance仍为`/Users/congming/.goldenshare/dagster_home`，写入仅原7项的14文件/对应原生记录与14开关，源码审核记录仅写原staging父目录。无需reload或重启服务。

**性能及验收。** 本步代码扫描≤150文件、≤16MiB，每次仅本地AST/hash；正式业务范围、读取/输出行数、文件和source连接不变。续跑新增Prod读取0、最多补12物化/check，原累计DG读取≤400、活动≤1200秒、staging≤128MiB/512文件。沿用原候选字段、旧DC保留证明；隔离测试使用临时工程证明真实Python绝对import、共享模块和包初始化均纳入，复权CLI变化不影响摘要，但共享依赖/源码/集合/锁文件/命令变化会拒绝；symlink、缺失模块、相对import与超限拒绝。用真实临时Lake/SQLite覆盖样本完成后恢复开关、代码重新审核、剩余6项续跑、旧plan/candidates摘要不变、候选COPY不重复、原生记录无重复、无审核/错审核/审核篡改/已绑定后丢失拒绝，以及完成只读重放0写。关键预期用字面文件集合/7项数量/旧DC字面值，不用待测helper生成expected。总测试目标≤120秒，受保护静态检查仍走原启动器、不更改规则或测试库存。正式最终结论只在实际14文件、14准确检查和原更新器状态读回后填写。

续跑前再次精算当前188次读取后的余量：文件预检不读DB，开关1次、活动任务1次；正式续跑预计176次（暂停15、任务1、已完成样本4、剩余6项113、全7项最终准确记录28、恢复15），合计366。最终独立进程只读重放本身已核对全部14对物化/check（28次）及开关（1次），不得在同一审计脚本前后重复同一轮28次检查、再重复开关查询；另外只查旧DC物化2次及七项动态分区的单次有界集合查询，总计最终审计32次、总计398次。原engine每项发布前的原生基线检查保持，不能为省读跳过。最终审计前在同一父账本预留32次，实际查询须符合该清单；预留在正式完成阶段保存，审计及幂等重放本身保持0写。暂停/源异常等已消耗次数不清零；若任务等待导致余量不够，则在领取下一项之前停止，不盲试突破400。预算中的外部审核不能另建从零计数的Control来隐去成本。

实现后的本地单次扫描实测约0.16秒、79文件（75个Python及4个固定依赖/脚本/种子），无DB、网络或依赖安装。隔离测试必须显式使用`--basetemp=/private/tmp/...`，不能依赖系统默认`/private/var/folders/...`，因为现行补录合同只允许临时Lake位于`/private/tmp`；首次测试未指定该参数，70个夹具在scratch路径检查处拒绝，未执行对应业务验收，该次结果不得报通过。修正的是测试命令，不放宽路径合同或修改夹具预期。

本节代码和审计已完成：[源码审核记录](../../reports/moneyflow_history_supplement_source_review_20261018.json)摘要`6ef4fd6a24b907eadb638ebf49a12b6e5f4fa053b4ee92dcfc130fb6594d7f28`；[审核及测试依据](../../reports/moneyflow_history_supplement_source_review_audit_20261018.json)确认相对旧清单仅本次补录入口/control及外部复权CLI变化，新增本域源码审核模块，其他资金流实际依赖保持。91项隔离/合同测试通过，123.98秒，比120秒目标多3.98秒；完整真实文件/SQLite恢复测试与重复本地源码检查产生该耗时，未请求正式资源或人为等待，不因这4秒差异扩展业务优化范围。最后增加已存审核记录丢失/换版本/缺显式传入和“记录保存后state尚未绑定”的针对性断言，12项复验4.44秒通过。原受保护静态113项、默认及致命Ruff通过；不再重跑无关全量回归。静态启动器首次在外层沙箱内无法启动macOS sandbox-exec，随后经工具提权按原启动器执行通过，未更改隔离规则。

正式依次执行临时脚本`resume-review`、`complete`、`audit`；源码审核摘要已作为脚本字面值固定，校验完整新依赖集合，原数据计划及候选摘要仍是§71.14中的原值。`resume-review`仅保存本操作计费/审计证据，实际文件和原生记录不写；逐日期原生基线及样本准确记录由随后complete入口在写入前验证。complete成功后在原state记录最终32次查询的预留，正式累计计数加预留不得超过400；最终audit在独立进程消费这32次，只读查询和实际文件校验，不重复第一轮原生查询或开关查询，不更改state。审计开始在临时证据目录留标记，若中断不盲目重新消费整个32次预算，先核对已保留证据再决定恢复。当前尚未宣称剩余6项已正式补齐。

### 71.16 原7项正式修复及验收收尾（2026-10-18 02:36）

上述修正及原操作续跑已按顺序完成。源码审核记录实际保存至原父目录`source-review.json`，state绑定审核摘要`6ef4fd6a24b907eadb638ebf49a12b6e5f4fa053b4ee92dcfc130fb6594d7f28`，旧计划和候选仍分别是`e698725123f1d974d8c35672c5560f101ae44fe64680c2a6875d89c4cdcc9bee`、`be18a6763c8c2eaf1e3acd205ffd4e88e6b9d1c2f5e73b4fa6522cc9e5807eb5`。源码差异没有通过改写旧计划、修改原生身份或重新导出来消除。

`resume-review`保存当前文件及来源证明校验结果、更新器状态和活动任务查询，父读取188→190；正式complete按原候选接续，最终7项accepted，父读取190→366，14物化/14检查/6新增分区。没有新COPY/metadata或第8个日期。实际两层分别16923行，每层净增加14111行；逐项行数见方案§76.13。DC两层5955行，其中原2812行保留、新3143行与Prod候选一致。最终报告为[独立验收结果](../../reports/moneyflow_history_supplement_completion_20261018.json)，包含全部14文件路径/摘要、旧DC原生身份、准确检查与恢复状态及重放结果。

最终独立进程对实际14文件执行完整schema/日期/键/行数/转换SQL，逐份hash与原已批准候选一致；通过只读重放内的28次原生查询核对14对物化/检查准确绑定，通过一次原生开关快照核对14个原RUNNING状态；额外两次指定storage_id读取证明旧DC物化7453633/7453634保留，一次`DynamicPartitionsTable`精确七对(name,date)、LIMIT8的集合查询确认全部分区存在。共32次，沿用complete末尾在state保存的预留，不以新Control从零预算隐去读取。执行366＋最终32＝398≤400；原state中`counts.reads=366`和`final_audit_reserved_reads=32`分别保留，报告明确两者合计。审计及重放没有修改state、文件、分区、事件、开关或cursor，返回`complete/accepted=7/replay=True/writes=0`，审计前后state摘要一致。

开发约束对账：相关依赖变化由新源码闭包和显式审核摘要拒绝；原计划/候选/7项范围由原validate和审核父身份共同约束；DC旧值由原独立SQL证明及最终候选摘要约束；正式文件用原发布协议逐文件原子提升，原生记录用既有准确绑定验收；暂停恢复与计费沿同一父state，不新增配置、定义或跨子系统依赖。CodeGraph explore/impact和实际AST/源码核对已记录于§71.15，未发现需要人工确认的调用或业务边界。静态/隔离测试与真实正式验收分别列证，未将原测试通过当成数据补齐。

本次补缺已完成，不再领取正式写入；原源端缺口、早期覆盖不足、DC已有字段修订与未来交易日运行验证不属于这7项修复。没有为本轮提交Git、推送、reload、重启、安装依赖或改动其他任务源码；后续若需提交，只能按本任务文件清单处理。

自动更新开关次数另作实际对账：§71.7的28次stop/start是正常候选、发布两轮的设计数；本次样本完成后因共享代码变化安全恢复、经批准续跑再暂停/恢复，实际共三轮，各42次stop和start，全部只涉及原14项，最终状态仍与执行前一致。这额外一轮已由§71.14.2的安全收尾和§71.15的批准续跑覆盖，读取开销包含在上述398次内，不增加业务job、来源请求或重复事件。
