# 七个 Tushare 资金流向数据集实施细则与 P0 收尾

日期：2026-10-06；最近更新：2026-10-12。P3-F及P3历史物理文件阶段已关闭，实际结果见§28。P4首个数据集moneyflow_mkt_dc的资产/check/job/catalog、sensor、预演和事件执行器已完成，见§29～31；两日样本与全量正式登记均读回通过，见§32～33；本表839分区/1678物化/最近20日40检查齐全，moneyflow_ind_ths的独立资产/check/job/catalog及隔离验收已完成，见§34；三个STOPPED sensor及历史只读预演已完成，见§35，可恢复事件执行器和两日/全量冻结清单已完成，见§36，正式两日样本读回通过，见§37；全494日正式登记已读回通过，见§38，494分区/988物化/最近20来源日40检查齐全。moneyflow_cnt_ths独立资产/check/job/catalog及完整隔离验收已关闭，见§39.6；三个STOPPED sensor和历史只读预演已通过，见§40，可恢复历史登记执行器与两日/495日冻结清单已完成，见§41，完整当前门禁已复验并收尾，见§41.6，两日正式样本登记已读回通过，见§42；495日全量历史登记与收尾已完成，见§43，495分区/990物化/最近20来源日40检查齐全；moneyflow_ind_dc的独立资产/check/job/catalog及完整隔离验收已关闭，见§44.3，三个STOPPED sensor及历史预演、执行器和两日样本已完成，见§45～47；739日全量登记及本表P4历史接入已关闭，见§48，739分区/1478物化/最近20来源日40检查齐全；moneyflow_dc独立资产/check/job/catalog和完整隔离验收已完成，见§49；三个STOPPED sensor、readiness及739历史日只读预演已通过，见§50；可恢复登记执行器、隔离两日样本和739日冻结清单已通过，见§51；两日正式登记及读回已通过，见§52；739日全量登记待后续。此前阻塞记录保留；sensor启用和正式job未执行，整个P4未关闭，P5真实日更未执行。当前历史设计为七表日期批次直接生成每日候选，见§4和§19。P0/P1/P2验收记录保留；§17～18仅为旧路线记录，日期代码/隔离验收见§20，真实Prod查询见§21，索引及复测见§22。§25保留样本清单、§26保留正式两日样本、§27保留全量执行前的范围/成本与准确命令；最新进度以§28～49为准。

## 1. 硬口径和影响面

七个接口分别构成七个独立数据集；每个有独立 Raw/Silver、分区、job、sensor、check、checkpoint 和来源证明。全部只取 Tushare；历史以 Prod raw_tushare 为基线，未来由 DG 请求 Tushare。不引入 BIYING、融合、Prod日更就绪门禁、证券池裁剪或派生资金值。配额已满足；22:00登记当天分区、上海时区、正式SSE日历、不把登记等同采集成功。

当前调用链为资源→有界分页→writer→文件check→asset/job→sensor/catalog。CodeGraph explore命中了分页会话及BSE调用，但结果混入同名符号；已直接核验 resources.py、tushare_request_policy.py、duckdb_connection.py、cn_a_trade_day_sensor.py、dc_board_partition_sensor.py。现有无时钟门禁的calendar-only helper不能直接满足22:00；使用有same_day_register_start参数的注册helper，限定本次七个注册器，不改变既有注册器。

改动落点沿用原方案§12，并按数据集拆分模块。moneyflow_mkt_dc已完成资产、sensor及历史event执行器代码和隔离验收，两日样本及全量正式历史事件登记已通过；moneyflow_ind_ths已完成资产/check/job/catalog、三个STOPPED sensor、只读历史预演、可恢复事件执行器和冻结清单，两日及全量正式历史登记均已通过；moneyflow_cnt_ths与moneyflow_ind_dc全量历史登记也已关闭；moneyflow_dc独立资产/check/job/catalog及隔离验收已通过，三个STOPPED sensor、readiness及历史只读预演已通过；可恢复登记执行器和冻结清单已通过；正式历史登记待后续；moneyflow及moneyflow_ths的P4尚待逐表接入。生产DatasetDefinition/request builder、Web/API、其他资产消费者均不改变。无子系统边界或依赖矩阵变更。

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

正式路径只做stat/glob：两根目录已挂载且同为设备16777244，当时空闲约2.73TiB，28目标不存在且无邻居Parquet/符号链接；拟用operation和共享writer.lock不存在。当前assets/jobs/sensors/catalog源码没有七表日更writer，P4仍未激活。这是当时的只读事实，不能保证未来没有其他进程；正式执行需重新核对并占用人工维护窗口，不自动启停服务。实际源SQL、类型/计数/分类、逐请求证明、隔离文件/hash/字节、28准确目标、代码及测试日志hash保存在[本轮结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_selected_dates_evidence_20261008.json)。

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

正式两根挂载/权限已只读核对，同设备16777244，当时空闲约2.73TiB；拟操作目录不存在。执行前重新核对移动盘、目标文件、原writer及维护窗口。历史helper共用namespace writer锁，P4尚无七表active writer，但该锁不能保证任意外部进程不写同目录。没有自动停启服务或改调度。

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
