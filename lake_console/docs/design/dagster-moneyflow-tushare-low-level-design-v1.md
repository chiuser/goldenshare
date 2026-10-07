# 七个 Tushare 资金流向数据集实施细则与 P0 收尾

日期：2026-10-06；最近更新：2026-10-07。依据原方案及 P0 只读证据；本文记录实施设计及阶段验收，不代表正式数据验收。P0收尾已提交f5c06dd3，P1大盘、THS行业、THS概念分别提交0bd4de4f、141edd3a、c9fcf389，DC板块及P1收尾提交5dc15c94。P1四个小数据集候选能力及隔离验收已完成。本轮进入P2，普通moneyflow候选能力已完成，验收见§13；P2其余两个个股数据集及P3/P4/P5尚未执行。

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

七数据集此次规划C_d均固定2026-09-30，起点见下方卡片；不把执行日变动自动纳入已冻结历史计划。MCP SSE日历2026-10-01..12确认首个后续交易日2026-10-08。P3执行前重新读取范围内计数/hash，变化unit作废重导；C_d仍不自动漂移。P5开始时取(C_d,切换日]的expected日期减已就绪日期作为明确接续集合，先登记/补采全差集，再进入最近10日自动热窗口。

历史忠实复制Prod已有记录。已知11个整日缺口：5个源端仍不可取得，按管理员决定接受且不造空成功；6个源端可取得共10968条，另DC2026-05-19缺3143键。共14111个缺键列在收尾JSON，不自动混入Prod-only bootstrap。正式历史补录需要单独列精确日期/键/来源/行数并批准；P0不是补录执行授权。

DC2026-05-19：Prod2812、源5955，无Prod独有键；212个已有键的值不同。主要close211、pct_change173，少量资金字段；不能据此推断原因是复权或源修订。保持Prod基线并保留两侧值证据，不自动覆盖。补“缺键”和修“已有值”是两个独立执行范围，P3前对补录范围取得批准。

THS2024-12-19/20/23：源/Prod均2行，所有选定字段一致，忠实迁移并说明低覆盖。普通moneyflow2010-01-04/03-30分别834/830行，源/Prod逐键逐字段一致，不按今天证券数量补造。其余历史日期只证明冻结来源计数/键唯一，不声称逐证券源覆盖全量审计已做。

## 4. 分批性能、持久化与预算

读粒度和正式写粒度分开。普通moneyflow按(ts_code,trade_date)稳定keyset，每unit≤100000；其他六表按日期索引，每unit≤20个交易日、≤100000行，年界拆分。每unit一个只读连接/事务，SQL120秒；每次完成立即持久化CSV及hash/checkpoint，禁全历史事务。初次导出、独立来源复核各一遍；SQL/连接预算包含这两遍和计划统计：347×2=694个unit读取事务，计划统计额外至多14个，unit最多4条语句（BEGIN/SET/COPY/结束），总语句上限2790，连接上限708。按120秒全部耗尽的算术上限23.1小时超出总预算，因此不允许逐unit超时预算掩盖累计超限，超过12小时即停止续跑待重估。不把样本耗时当SLA。

普通代码块跨多年，不能逐日期重复扫所有CSV。每源unit用一次DuckDB列式扫描，按冻结的年内写窗口ID分桶形成Parquet spool；每个窗口≤20日且≤100000来源行。再一次读取该窗口spool，校验整组来源/key/精度后生成最多20个日期候选。年度只是组织边界，不把全部年度数据载入Python。其余六表可直接使用日期窗；全部写入用SQL/COPY，不逐行插入。

使用现有connect_configured_duckdb及DuckDBConnectionSettings的局部profile：memory_limit=512MB、threads=1、existing_no_spill、临时目录=本次staging操作目录，max_temp_directory_size有效值0B，禁止扩展自动下载。不修改全局16GB/4threads/512GB设置或既有调用者。单进程实际RSS拒绝线768MiB，Python保留≤两页/20000key；超过即停止并保留checkpoint，不自动放大预算。P3样本必须测中断/峰值/运行时间再准入。

容量设计：全部来源CSV、分桶spool、两层候选及正式输出的新增占用总预算32GiB；来源CSV和spool各≤8GiB，每来源unit≤32MiB、spool文件总数≤65536。开始前空闲空间≥64GiB且staging与正式路径同st_dev；不满足停止。空间预算按下表线性样本估算加余量，不把近期宽度、Parquet压缩比或小文件头当全历史精确预测。spill=0，不能借全局512GB临时目录绕过。

耗时设计：单轮导出unit120秒上限、完整一次导出+一次复核按下表unit数测算；普通导出按10万行22.673秒外推约53分钟，按同吞吐推七表纯导出约80分钟、两遍约160分钟；转换/分桶小文件/提升和事件不能从单块速度精确外推，预留约一倍余量的3～6小时仅为规划估计。本方案给12小时总执行预算，单窗口转换120秒、提升及事件100日期一批。实际代表性年度/分桶样本超过预算时，P3禁止全量APPLY并修订计划；P0不为了验收跑全历史。CSV→spool→候选最多三层扫描，来源两遍复核另计；取消在sourceunit/page/window/file前后检查。

checkpoint记录plan_hash、schema_hash、来源unit边界、阶段、完成量/总量、日期、path/hash/rows、last_updated。源unit、分桶、Raw/Silver文件独立记录；每文件os.replace原子提升，非多文件事务。已有同hash幂等跳过，不同hash冲突停止；恢复核验已提交文件再续跑，不删除业务表/正式文件、不引入备份或Kopia。事件补录在文件全量对账通过后另行批准，materialization按物理日期，check仅最近20日/层，最多280，较早历史保持物理证据。

| 数据集 | 行数/日期 | 导出unit | 写窗口 | 最大窗行数 | 正式两层文件 | CSV/两层Parquet估算MiB | spool文件保守上界 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `moneyflow` | 14,089,300/4067 | 141 | 217 | 99,839 | 8134 | 2064.5/2610.1 | 30597 |
| `moneyflow_cnt_ths` | 192,009/495 | 26 | 26 | 7,890 | 990 | 19.5/22.9 | 26 |
| `moneyflow_dc` | 4,278,673/739 | 46 | 46 | 99,888 | 1478 | 533.1/542.0 | 46 |
| `moneyflow_ind_dc` | 364,012/739 | 40 | 40 | 20,620 | 1478 | 64.4/64.0 | 40 |
| `moneyflow_ind_ths` | 44,460/494 | 26 | 26 | 1,800 | 988 | 4.4/7.6 | 26 |
| `moneyflow_mkt_dc` | 839/839 | 44 | 44 | 20 | 1678 | 0.3/4.2 | 44 |
| `moneyflow_ths` | 2,191,645/431 | 24 | 24 | 99,070 | 862 | 247.9/272.2 | 24 |

## 5. 配置审计与实现/测试落点

上述值都是本次稳定运行合同的常量，集中于defs/run_contracts/moneyflow.py，无运营可编辑宽松开关，无新增env/数据库配置。消费者为request adapter、writer、bootstrap planner、check、七对sensor；代码发布/reload后生效，实际参数/预算/超限reason写入运行metadata。TUSHARE_TOKEN继续既有env，SDK1.4.29和现DG endpoint为实測基线；不打印token、不切换Prod凭据。历史C_d/来源hash仅属于冻结manifest，执行必须校验manifest，不从cursor猜来源阶段。目录沿用paths.py，正式raw/silver和独立staging，不用旧湖。

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
- 7A实测：源/归一化/Raw/Silver读回均5572行，reject0、差异0；CSV856108字节、Raw541201、Silver541177；隔离转换0.3281秒。bootstrap 141导出unit/217写窗口/8134正式文件；只读事务/512MB/0spill/20日期及100000行边界见§4。失败最小重跑源unit或单日候选，checkpoint按实际文件；P3才验证正式提升和中断恢复。

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

状态：P2普通moneyflow候选能力及隔离验收已完成，本轮普通moneyflow修改本次提交归档；下一轮为moneyflow_dc，再moneyflow_ths。P2整体未收尾，P3/P4/P5尚未执行。
