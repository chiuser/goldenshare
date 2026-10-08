# 七个 Tushare 资金流向数据集实施细则与 P0 收尾

日期：2026-10-06；最近更新：2026-10-08。当前历史设计已按管理员决定改为七表日期批次直接生成每日候选，见§4和§19。P0/P1/P2验收记录保留；§17～18为旧路线开发记录，旧历史代码已按日期路线迁移；当前代码和隔离验收见§20，真实Prod日期查询核验见§21，管理员确认后的Prod索引及复测完成证据见§22，§17～18不作为新路线证明。正式历史执行、P4/P5未执行。

## 1. 硬口径和影响面

七个接口分别构成七个独立数据集；每个有独立 Raw/Silver、分区、job、sensor、check、checkpoint 和来源证明。全部只取 Tushare；历史以 Prod raw_tushare 为基线，未来由 DG 请求 Tushare。不引入 BIYING、融合、Prod日更就绪门禁、证券池裁剪或派生资金值。配额已满足；22:00登记当天分区、上海时区、正式SSE日历、不把登记等同采集成功。

当前调用链为资源→有界分页→writer→文件check→asset/job→sensor/catalog。CodeGraph explore命中了分页会话及BSE调用，但结果混入同名符号；已直接核验 resources.py、tushare_request_policy.py、duckdb_connection.py、cn_a_trade_day_sensor.py、dc_board_partition_sensor.py。现有无时钟门禁的calendar-only helper不能直接满足22:00；使用有same_day_register_start参数的注册helper，限定本次七个注册器，不改变既有注册器。

改动落点沿用原方案§12；当前无七数据集定义。生产DatasetDefinition/request builder、Web/API、其他资产消费者均不改变。无子系统边界或依赖矩阵变更。

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
