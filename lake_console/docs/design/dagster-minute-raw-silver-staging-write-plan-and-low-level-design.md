# 指数与股票分钟线Raw/Silver安全写入方案与LLD

2026-11-02整理记录（历史）：本文按当时工作区源码说明已有设计；共用模块和股票接入已在Git中，普通指数接入仍有未提交改动。当次仅整理并提交本文与[指数日线写入方案](dagster-index-daily-staging-write-plan-and-low-level-design.md)，未提交代码，不据此宣称代码已部署。2026-11-03的11月2日普通指数首次补齐及失败原因见第9节；18007补源、显式替换开发与本轮完成结果见第10节。

保留原文件路径及既有章节链接。原文22日“剩65项”、Prod零行、日期识别待确认等是历史阶段，不再作为执行指令；结果见[22日恢复说明](../../reports/datasets_recovery_20261022_20261024/README.md)和[30日收尾](../../reports/datasets_recovery_20261030_20261031/README.md)。已清理过程附件不重新生成。

## 1. 目标、范围与实现

由原业务writer生成指定日、指定频率的候选，校验后逐文件替换，保留失败现场及继续依据。适用于`defs/io/minute_partition_writer.py::MinutePartitionPublication`下列六个对象；下文`defs/`均指`lake_console/orchestrator/src/orchestrator/defs/`。2026-11-03新增主要指数两层的批准范围、细节、测试及执行边界见[主要指数原方案24节](dagster-major-index-mins-data-onboarding-plan.md#24-2026-11-03写入安全修正及主要指数分钟链恢复)及[原LLD34节](dagster-major-index-mins-data-onboarding-low-level-design.md#34-2026-11-03-rawsilver写入修正和当日恢复)，不改变原四项行为。

| 对象 | 频率（分钟） | 公共writer |
| --- | --- | --- |
| 普通指数Prod Raw | 1、5、15、30、60 | `assets/index_mins.py::write_raw_index_mins_partition_from_prod_db` |
| 普通指数Silver | 1、5、15、30、60、90、120 | `assets/index_mins_silver.py::write_silver_index_mins_partition` |
| 股票Prod Raw | 1、5、15、30、60 | `assets/stk_mins.py::write_raw_stk_mins_partition_from_prod_db`及原低层writer |
| 股票Silver | 1、5、15、30、60 | `assets/stk_mins.py::write_silver_stk_mins_partition` |
| 主要指数Tushare Raw | 1、5、15、30、60 | `io/major_index_mins_raw_writer.py::write_major_index_mins_raw_partition` |
| 主要指数Silver | 1、5、15、30、60、90、120 | `io/major_index_mins_silver_writer.py`的原日常及历史fallback入口 |

不扩展到股票Tushare Raw、`merge_repair`、Gold、QFQ/MACD、历史repair或其他对象。原源请求、对象集合、派生窗口、价格/量额校准、停牌/身份规则、冻结行和正式schema/checks继续由原业务实现负责。

完整业务依据见[普通指数方案](dagster-index-mins-data-onboarding-plan.md)、[原LLD](dagster-index-mins-data-onboarding-low-level-design.md)、[股票分钟设计](dagster-stk-mins-asset-design.html)、[Prod导出方案](dagster-stk-mins-prod-db-raw-extraction-hardening-plan.html)及[股票完成门禁LLD](dagster-stk-mins-prod-task-run-readiness-low-level-design.md)。

## 2. 已有文件、替换模式与返回值

| 入口 | 当前行为 |
| --- | --- |
| 普通指数Raw/Silver | 默认`reuse_existing`时，目标已存在且没有本次receipt则交回原builder核验/复用；显式`replace_existing`传`overwrite=True`，用原builder生成完整候选并校验后替换。无目标或有本次继续记录时走提交模块。配置与执行边界见第10节 |
| 股票Prod Raw | 公共writer的`overwrite=False`默认复用既有合格文件；原Raw job显式`replace_existing`才传`overwrite=True`。该模式仅支持Prod，仍要求真实完成reference，默认builder不变 |
| 股票Silver | 原job默认`write_new`，公共writer默认`overwrite=False`，目标存在且无本次receipt时拒绝覆盖；`reuse_existing`按原入口只读复核，显式`replace_existing`走原转换并传`overwrite=True` |
| 主要指数Raw/Silver | 默认复用原业务校验通过的已有目标，坏目标拒绝；无目标或同身份receipt则走原发布类，不新增替换模式。原返回dataclass保持 |

股票显式模式由`run_contracts/configs.py`定义/解析，细节见[股票写入LLD20.10](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#2010-最小代码改动配置与发布规则)。多分支配置仍拒绝，原Prod完成、全市场及五频门禁不放宽；类参数不等于每个job都提供同样的运营选项。

保留原结果dataclass的路径、tuple/Path、计数和清洗统计。普通指数及股票Raw复用候选/完成记录时，不把历史抽取说成本次新查询；股票显式替换展示生成统计，不标成“未改写Parquet”。

## 3. 路径、锁与输入依据

正式目标须匹配`paths.py`中该对象、日期、频率的规范路径；正式根为`/Volumes/datasource/data_lake`，候选及执行记录在`/Volumes/datasource/data_lake_staging`。专项`output_path_override`可指向已批准的staging候选，不顺带提升正式Lake；系统临时目录只用于隔离测试。不使用退役Lake或Kopia，不移动正式文件制造缺失以绕过已有文件检查。

```text
data_lake_staging/minute_partitions/<dataset>/target=<目标路径SHA256>/
  writer.lock
  run_id=<执行身份SHA256>/
    receipt.json
    attempt=<UUID>/part-000.parquet
```

日常wrapper传`context.run.root_run_id or context.run.run_id`，直接调用不传则生成独立UUID。代码检查路径穿越和符号链接，允许macOS标准临时目录别名；同目标非阻塞`flock`互斥，退出释放锁，不承诺多文件整体原子提交。

| 分支 | receipt绑定的当前输入 |
| --- | --- |
| 普通指数Prod Raw | 对象/日期/频率/schema、active pool hash、源SQL摘要和writer源码摘要 |
| 普通指数Silver | 同频Raw文件stat；派生频率则绑定实际Silver源文件stat；另含writer源码摘要 |
| 股票Prod Raw | 规范化代码范围、源SQL摘要和writer源码摘要；Prod当次内容由原检查通过的候选冻结 |
| 股票Silver | 当日同频Raw、身份映射、股票日线、停牌文件stat；非1分钟另含1分钟Raw；专项目标不等于canonical时另含canonical文件stat；有历史价格修正时另含seed文件stat；另绑定源码摘要及冻结policy版本/代码 |
| 主要指数Raw | 原日期/频率/对象scope、完整字段、原请求参数及writer源码；原候选/source revision冻结本次下载结果 |
| 主要指数Silver | native Raw或derived Silver实际来源stat，显式fallback文件stat及代码；scope与writer源码 |

提交模块只保存实际`source_paths`的stat，不把业务链其他参考也说成已绑定。输入还包含`overwrite`；进入提交模块后，同身份实际绑定的schema、源码摘要、范围、源文件或该参数变化会拒绝继续，公共入口先行复用的行为仍按第2节处理。

Prod Raw候选冻结的是当次结果，不证明Prod此后未变；复用已校验候选不重新抽取源。需要获取新补源时，应按原支持入口创建新的独立执行，不能修改旧receipt接纳变化。**这与指数日线Raw仍重新核对Prod当日内容的实现不同。**

## 4. 生成、校验与提交

1. 取得目标锁，核对输入和receipt；无记录且已有目标时，按类及公共入口各自的覆盖规则处理。
2. 新执行或`building`创建新attempt，保存写前目标stat及`building`；原builder只向候选执行SQL/COPY，旧失败attempt保留。
3. 原builder保留原业务校验。`_validate`另核对schema列顺序/类型、非空代码/时间/频率、目标日、本频率、`(ts_code, trade_time)`唯一性及返回结果中的预期行数；股票Silver额外核对`trade_date`。公共层不另设“必须正行数”，合法空结果仍由原业务合同决定。
4. fsync候选，核对输入未变，保存候选摘要、原结果和`validated`；提升前再次核对输入、写前目标、候选路径/摘要及同设备。
5. 先保存`promoting`，逐文件`os.replace`、fsync目标目录；目标摘要一致后保存`promoted`。

明细计算仍由原业务SQL负责，Python提交层只处理路径、记录、计数和摘要。合同错误、源/目标/候选变化、空间不足、路径或设备错误按代码停止，保留现场，不降低原检查或自动重跑。

候选行数检查只证明与原builder返回计数一致，不证明全市场每只股票日内应有的每根K线均已齐备；源覆盖和派生窗口仍按各链路现有校验执行。

## 5. 中断、继续与验收

| receipt状态 | 当前处理 |
| --- | --- |
| `building` | 只重新生成本文件的新attempt，不删除失败候选 |
| `validated` | 输入、原目标及候选摘要一致时继续，不再调用builder或抽取Prod |
| `promoting` | 目标已匹配记录摘要时补记完成；否则仅在原目标未变且候选完整时继续 |
| `promoted` | 正式目标摘要匹配才复用原结果，不匹配即拒绝 |

公共入口默认的复用/拒绝仍优先适用，不能只依据上表推断任意入口都能覆盖。文件提交与Dagster物化/check分别核对；同root继续限原记录允许的部分，不把新补源或代码变化硬接到旧身份。

资产、检查、分区、job和sensor名称不因该模块改变。候选通过不等于原blocking checks已通过，run成功也不替代物理文件和必要覆盖核验。

## 6. 读取成本与执行预算

正常新生成除原业务SQL/COPY和候选schema/键/日期/计数外，还有生成后、提升前两次候选摘要读取及一次正式目标摘要读回，不能写成“只读一遍”。`validated`继续核对候选，完成分支核对目标；文件源按stat核对，Prod Raw候选复用不重新抽取。

当前类的空间检查为`8MiB＋1.2 × 已绑定且存在的源文件字节和`，不包含任意全任务开销；无文件来源的Prod Raw不能据此承诺8MiB足够。正式执行仍须核定对象/日期/频率、源读取、候选、原检查、临时空间和中断继续预算，不沿用22日一次批次的旧GiB/耗时估计，不新增资源或重试限制。

SHA按1MiB分块读取，不是在Python中逐股计算行情；原DuckDB连接与列式计算方式保留。历史/全局明细读取仍按仓库规则单独授权，本文不授权补数、历史重算或扩大repair。

## 7. 实施和执行记录

共用模块和四个业务wrapper已在当前工作区接入。2026-10-24修正背景及22日结果见[恢复说明](../../reports/datasets_recovery_20261022_20261024/README.md)；30日股票Raw/Silver显式替换及下游由原job完成，见[30日收尾](../../reports/datasets_recovery_20261030_20261031/README.md)。这些是有日期的历史记录，不表示本文整理时再次执行了任务。

原文“成功区间任务仍不识别”的待确认条目不再保留。当前TaskRun日期判断由`prod_db/stk_mins_task_run.py`和[完成门禁LLD](dagster-stk-mins-prod-task-run-readiness-low-level-design.md)维护，本文不重复定义或绕过完成条件。

## 8. 本次整理与验证范围

- 已逐项对照`MinutePartitionPublication`和四个实际writer，分别说明已有文件行为、输入、频率/schema、状态继续及读取成本。CodeGraph类调用查询未返回调用方，已用四个入口源码补核，不据此认定无人调用。
- 当前测试位置为`tests/test_minute_partition_staging.py`、`tests/test_stk_mins_replace_existing.py`及原Raw/Silver合同测试，均相对于`lake_console/orchestrator/`。已核对其包含四族候选/故障、进程退出、输入/目标/候选变化、路径/锁/设备/空间、seed绑定和显式替换用例，不把历史数量当成本轮重跑结果。
- 本轮只整理两份已有文档，保持文件名和外部章节链接；提交前核对源码、链接/锚点、文档完整性及两文件暂存范围，不改代码/配置或正式资源，不运行补数、原checks、性能测试或全局审计。

<a id="recovery-20261102"></a>

## 9. 2026-11-02普通指数分钟线补齐方案、LLD与执行记录

### 9.1 目标、来源核对与禁止项

授权及同批日线范围见[日线执行LLD第8节](dagster-index-daily-staging-write-plan-and-low-level-design.md#recovery-20261102)。本步仅恢复11月2日普通指数Raw五频、Silver七频、Gold七频，共19项；不涉及主要指数分钟线、股票/ETF分钟线、复权及历史repair，不开发代码或改变原源门禁、计算、schema和运行配置。

07:04:19北京时间，通过现有`bash scripts/psql-remote.sh`、`BEGIN READ ONLY`核对：`ops.index_series_active(resource='index_mins')`当前530代码；`raw_tushare.index_mins`的11月2日五频均覆盖530代码，缺失代码均0。五频行数按1/5/15/30/60为85,457/17,381/6,058/3,189/1,768；此前缺少60分钟的`000039.SH,000141.SH,000854.SH`均已存在。这只是源日期/代码覆盖计数，价格、唯一键、归一化和派生完整性继续由原job及原检查判断，不据此预先承诺全部质量通过。

### 9.2 顺序、实现及入口

| 顺序 | 原job | 本日目标 | 原检查数 |
| --- | --- | --- | ---: |
| M1 | `raw_index_mins_update_job` | Raw 1/5/15/30/60m | 5 |
| M2 | `silver_index_mins_update_job` | Silver 1/5/15/30/60/90/120m | 7 |
| M3 | `gold_index_mins_update_job` | Gold同七频 | 7 |

M1调用`assets/index_mins_raw.py`及本文公共writer，只读Prod目标日五频、当前active pool、现行11列；M2调用`assets/index_mins_silver_defs.py`、`assets/index_mins_silver.py`，只读当日Raw及必要Silver派生来源；M3调用原`jobs/index_mins_gold.py`及对应Gold资产/规范化SQL，输出七频，但实际按`CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET`读取同日1/5/30/60m Silver，不能误写成逐频读取七份同频Silver。Silver 90/120m仍按原30/60m来源和窗口派生；Gold也保留原映射。不更换源、不启用fallback，不人为补值，不把对象数写死在代码。

采用原job的默认run config、`dagster/partition=2026-11-02`。八条相关sensor原状态均RUNNING，日线Raw已自动提交；本轮优先跟进这些原sensor提交的job，后续仅在上游原检查通过后推进。不重复提交已排队/运行/成功的同日job，不执行sensor evaluation，不更改cursor、sensor开关或间隔；其他数据集自然运行保持现状。

### 9.3 读写、性能、失败和收尾

正式范围限定当前`paths.py`下11月2日19份目标；候选及receipt仅在正式staging，沿本文第2—6节处理已有文件、失败、中断及源变化。Gold同样走原单日job与原检查，不直接写文件、不补runless通过事件。不覆盖已完成的其他日期，不读取其他年份或全历史分钟明细。

本批分钟源约113,853行，为当日统计，不是全历史规模。10月30日参照文件只做stat：Raw五份7,608,323B、Silver七份7,733,387B、Gold七份7,355,226B；本日实际字节以原物化结果为准。合并日线的预算、候选摘要多次读取、一次正常运行和中断后继续的额外成本按日线8.3；不新增内存、线程、spill、并发、超时或自动重试限制。

任何原job失败、原检查失败、来源/目标变化或重复运行冲突，停止人工推进并汇报，不绕过原检查、删除正式文件制造缺失或自动重跑。保留已正式提交部分和失败staging；只有核清原receipt和输入身份后才制定后续继续安排。

最终验收复用三个精确run的终态、19项物化、19项原检查和原metadata中的行数/路径；必要时只stat这19份本日文件。合并日线为24项、31项原检查；不重复180项目录审计、不另查历史行情明细。通过后补入执行结果，清理本次无用调用文件，保留正式数据、staging/receipt和原日志。当前不预填成功。

### 9.4 实际执行、日内缺口与停止点（2026-11-03）

| 原job | 精确run | 结果 |
| --- | --- | --- |
| Raw五频 | `bbcc7482-39b1-40da-aaa6-f74c75732337` | 07:05:25—07:06:57 SUCCESS，5项物化、5项原检查通过；本批源/写入行数均113,853 |
| Silver七频 | `150e74bf-0d10-4187-9a36-c84c1c90bbca` | 07:14:10—07:14:12 FAILURE；原生五频已写入、5项原检查通过，90/120m生成前拒绝，未生成它们的正式结果 |
| Gold七频 | 尚无本日run | 原sensor等待完整Silver七频，不跳过依赖或检查 |

错误为`index_mins derived window is incomplete`：90m有1,083个不完整窗口，120m有671个不完整窗口。`assets/index_mins_silver.py::_write_derived_partition`先在`_derived_diagnostics`核对原30/60m Silver的时间点及窗口，再COPY；本次在该检查处抛错。因此保留已落地原生五频及原失败receipt，不删除或强行提升90/120m，不自动重跑。

**撤回「Prod已完整补齐」的宽泛判断。** 07:04核验只证明各代码至少有记录，未证明该日每根K线齐备。原Raw probe按代码覆盖/键/日期判断；原生Silver写入和core check也不核对全天完整时间点；派生窗口进一步检查才发现问题。原job成功/原生检查通过不能用于宣称下表五频业务完整。

为确定阻断范围，失败后只读取本日五份新原生Silver的`ts_code/trade_time`做一次时间点聚合，各频率至多5个代码样本；未读OHLC、其他日期或全局行情，未重复原窗口计算。30/60m依据原90/120m窗口所需9/5个时点；1/5m依据原Gold来源时间点；15m依据现行15m时间点合同。09:30竞价点包含在内。

| 源频率 | 530代码应有时点数 | 本批实际行数 | 缺少时点数 | 存在缺口代码数 |
| --- | ---: | ---: | ---: | ---: |
| 1m | 127,730 | 85,457 | 42,273 | 527 |
| 5m | 25,970 | 17,381 | 8,589 | 527 |
| 15m | 9,010 | 6,058 | 2,952 | 527 |
| 30m | 4,770 | 3,189 | 1,581 | 508 |
| 60m | 2,650 | 1,768 | 882 | 459 |
| 合计 | 170,130 | 113,853 | 56,277 | 各频率不能直接相加为不同代码数 |

样本`000001.SH`：30m缺09:30、11:30；60m缺10:30。07:21:20再次仅按目标日五频计数，Prod仍与本批113,853行一致，故不能解释为DG读取后源已全部补齐。源与Raw、原生Silver的五频行数一致；本次没有核定Tushare接口或Prod下载程序为何漏这些日内记录，不据此猜测原因。

**停止边界及下一步。** 人工推进已在Silver失败后停止，未补交任何job、未改代码/正式文件/开关/限制。日线独立原链仍可自然完成。后续应先补齐Prod本日五频日内记录并做时间点计数，再核清当日Raw/Silver已有文件的安全替换安排；本文第2节明确普通指数入口遇已有文件会核验/复用，不能把再次触发等同于重新提取新补源。不得直接沿用本次旧receipt接纳变化，也不因10份文件存在就宣布分钟链补齐。新的替换执行或入口变化须先按原方案/LLD核清，当前未实施。

<a id="task-18007"></a>

## 10. Prod任务18007监控、完成核验与替换入口方案（2026-11-03）

### 10.1 已授权的监控与只读审计

管理员明确要求每隔5分钟检查Prod全量指数分钟任务18007，完成后审计，若齐备则推进DG。监控仅通过现有`bash scripts/psql-remote.sh`、强制只读事务查询`ops.task_run WHERE id=18007 LIMIT 1`的身份、状态、日期/频率、完成/失败单元、进度、结束时间及结果计数；不查询其他任务、不修改Prod、不重新触发下载。首次07:45:13：`resource_key=index_mins`、`action=maintain`、目标日2026-11-02、五频、无代码过滤；running，2,018/2,650单元，失败0、拒绝0、76%。后续查询按首次完成时间加300秒安排，等待期间只读代码及完善方案，不反复读取行情。失败/取消则汇报原任务结果，不把结束等同成功。

只有原任务成功结束，且本次日期/五频/全量身份、完成单元和失败/拒绝计数可解释后，才做本日行情核验。只读`ops.index_series_active(resource='index_mins')`的当前代码集合及`raw_tushare.index_mins`的`ts_code/freq/trade_time`，限定11月2日00:00至次日00:00、原生五频、当前代码池：一次共享聚合检查代码覆盖、唯一键、原合同要求的全部时间点及范围，不读取OHLC、其他日期或全历史。源任务成功不替代这次核验。齐备才进入后续替换；不齐备则保留缺口计数和至多5个样本后汇报，不重复大审计。

### 10.2 已核清的入口缺口与批准范围

**状态：管理员已于本轮明确回复「批准」，确认10.2—10.5的最小入口修正、隔离验证、加载新代码及原job补齐范围；执行结果另行记录，不能预填。** 修正前Raw/Silver两个原job没有显式替换配置；`assets/index_mins.py`及`assets/index_mins_silver.py`遇已有正式文件且没有本次receipt时，直接交回原builder核验/复用，不会获取新补源并刷新已有10份本日文件。历史bootstrap继续调用这些writer，并非替换入口；`assets/index_mins_silver_repair.py`只处理已核实源频率全空时的5m fallback，不是本次五频日内缺口。不能另写手工补数脚本、删除/移动正式文件制造缺失、修改旧receipt或绕开原检查。

最小方案是在原Raw/Silver job增加显式`replace_existing`，默认`reuse_existing`保持；仍由原job执行全部业务计算和原检查。范围仅普通指数Raw五频与Silver七频，不修改共用`MinutePartitionPublication`、Gold、源门禁、对象池、分区、公式、fallback、其他数据集或Prod实现，不迁移历史。

### 10.3 LLD：配置、代码落点与消费者

1. `run_contracts/configs.py`增加一个普通指数分钟线配置类`IndexMinsWriteConfig(dg.Config)`，字段`write_mode: Literal['reuse_existing','replace_existing']='reuse_existing'`，非法值沿现有配置验证拒绝，不增加环境变量、数据库配置或隐含默认开关。配置仅来自本次run config，保存在原Dagster run；原sensor不传配置继续使用默认。该字段作用于使用它的单个asset，原job批量提交时必须为选中的五/七个asset统一填同一模式，不能只替换部分原生频率就宣称五频刷新完成。
2. `assets/index_mins_raw.py`的资产工厂函数注入此config，转换为`overwrite=(config.write_mode=='replace_existing')`传公共writer；`assets/index_mins_silver_defs.py`同样处理。两个job名称、selection、分区、executor、依赖和checks不变，原默认调用仍有效。运营可在原job配置中看到本字段，无自动启用。两份运行配置builder放在现有`run_contracts/index_mins.py`，从`INDEX_MINS_RAW_ASSET_NAMES`/`INDEX_MINS_SILVER_ASSET_NAMES`分别生成完整五/七项`ops.<asset>.config.write_mode`并用配置类验证。该模块已依赖`configs.py`，不得反向让`configs.py`import它造成循环；不另手写第二份资产名单。
3. `assets/index_mins.py::write_raw_index_mins_partition_from_prod_db`增加默认False的关键字参数`overwrite`；传给现有`MinutePartitionPublication(overwrite=...)`，仅在False时走原正式目标复用分支。True时用原builder的`target_override=candidate`生成完整新候选，原源schema/覆盖/日期/键/读回校验全部保留，经现有发布模块校验后逐文件原子替换。不得向原低层builder直接传正式旧文件作为新COPY目标。
4. `assets/index_mins_silver.py::write_silver_index_mins_partition`同样增加默认False的`overwrite`并传发布模块；True时跳过外层旧目标复用，用原builder写新的candidate。原生五频消费新Raw，90/120m按原依赖消费新30/60m Silver；原完整窗口和混合exchange拒绝不变。低层默认与source-empty专项不变。
5. 原结果dataclass和字段保留。默认模式的`write_mode/query_count`语义不变；显式替换报告`write_mode=replace_existing`，Raw初次抽取query_count沿原实际值，相同执行复用已校验候选/已提升结果时仍为0，不能声称再次读取Prod。原物化row_count、源/写入计数和原检查继续生成，不以配置模式代替实际结果验收。
6. 调用方已核对：两个资产工厂是正式日更调用者；bootstrap的默认writer注入和现有直接调用保持False，测试调用保持默认，其他数据集不传本字段。CodeGraph和源码搜索共同核对了两个writer、原builder、资产工厂及bootstrap；不因同名函数噪声假定前端存在消费者。没有新数据库/API或前端代码消费者；本次变更的是Dagster原运行入口配置，因此仍须管理员明确确认后编码。

### 10.4 失败、中断、测试与实现对账

- 所有本次刷新使用新的独立root run和新receipt身份，不接续07:14失败run。现有发布模块已将`overwrite`纳入输入身份；同身份模式变化应拒绝，不修改旧身份。候选building/validated/promoting/promoted、源stat、目标写前stat、摘要、同设备、锁和失败留存沿本文件第3—6节。Raw续跑复用已冻结候选不重新抽取Prod，若Prod再次变化，先核清后使用新的独立执行，不篡改receipt。
- 测试先核对真实11列Raw/Silver合同，使用专属`/private/tmp`小Parquet和独立字面预期，不连接正式源或正式instance。必须覆盖：默认已有文件不抽取/不改写；显式替换在同一代码但增加日内时间点时确实刷新Raw和Silver；首次写入及缺目标正常；非法模式拒绝；原生五频一致配置；90/120m完整窗口通过、缺一根仍拒绝；候选失败保持原文件；同身份继续与模式变化拒绝；不误改其他日期/其他资产。不能让测试只改模式字面值而不实际跑发布与转换。
- 原`tests/test_index_mins_raw_writer.py`、`test_index_mins_silver_writer.py`、`test_index_mins_checks.py`、`test_minute_partition_staging.py`及必要配置/定义静态门禁用于最小回归。仅使用现有orchestrator环境，不安装依赖，不做性能测试或正式资源试跑；测试后清理自己生成的夹具。完成后逐条对账默认行为、显式刷新、完整检查、失败/继续与真实接入证据，未覆盖项不能算通过。
- 真实接入证据复用18007成功后那次只读时间点核验；正式执行前确认已加载经隔离验证的代码、没有同日同目标活动run，核清原sensor并发影响，按原控制平面提交。源码存在不等于code location已加载，不直接用当前未加载的新参数提交任务。

### 10.5 后续正式顺序、预算与批准边界

批准并验证入口后，先保存`raw_index_mins_update_job_sensor`、`silver_index_mins_update_job_sensor`、`gold_index_mins_update_job_sensor`三条原开关/cursor/lastRunKey，仅临时停止原RUNNING的这三条；读回STOPPED并确认同目标无排队/活动run后，通过现有code location重新加载动作加载新实现，不重启整套DG、不停止其他数据集。只读核对原job配置schema已显示默认reuse_existing及显式replace_existing，确认没有加载错误；仍是旧schema或有活动冲突就停止汇报，不能直接提交新参数试错。

之后先原Raw job五频`replace_existing`，原检查通过后再原Silver job七频同模式，最后原Gold job七频默认生成。日线五项已完成，不重跑；分钟链不涉及股票复权或repair，不补runless事件。每个必要job正常一次，失败停止、不自动重跑。执行成功或失败收尾时均核清无本轮活动写入，再用原生启停动作恢复原开关，保留cursor/lastRunKey、不手动评价sensor；失败现场和已正式提交部分保留并汇报，不用恢复开关当作修复完成。不清空run key、不改历史run、不借此加载或修改其他数据集业务逻辑。

读写限定11月2日五频Prod源、已有本日10份文件及新19份分钟目标；current active pool/基础参考只按原入口必要使用，不读其他日期行情。正式预算读1GiB、写64MiB、额外空间128MiB，含原检查、三次摘要读回、候选与最后本日对账，沿第8节/日线8.3已核清的量级；这是保守估算而非设备实测或新增运行限制。中断后不自动重试；确需继续应核清未完成范围，另预留其一轮、至多上述正常预算，并先记录再执行。隔离测试总临时空间预算64MiB。

最终只核三份精确run、19项物化和19项原检查，以及必要本日计数/文件stat，不重复180项审计或全历史重算。保留正式结果和失败receipt，清理本次无用调用/测试文件，记录实际run、模式、日期和结果。管理员已单独批准10.2—10.5入口设计和执行范围；开发、隔离验收及正式替换须依此顺序，不能用批准代替通过证据。

### 10.6 任务18007及完成后源审计结果

按管理员要求约5分钟一次，仅查询指定task：

| 观察时间（11月3日北京时间） | 状态 | 完成单元 | 进度 | 失败/拒绝 |
| --- | --- | ---: | ---: | ---: |
| 07:45:13 | running | 2,018 / 2,650 | 76% | 0 / 0 |
| 07:50:28 | running | 2,542 / 2,650 | 95% | 0 / 0 |
| 07:55:38 | success | 2,650 / 2,650 | 100% | 0 / 0 |

任务实际结束于07:51:32，抓取及保存各170,130行。身份为`dataset_action/index_mins/maintain`，point日期2026-11-02，五频、没有代码过滤。运行期间未重复扫行情；确认成功后，07:56:02完成一次强制只读、可重复读事务的指定日共享计数查询，只投影代码、频率和分钟时间。

| 频率 | 代码覆盖 | 源行数／应有时间点数 | 缺时间点 | 重复 | 异常时点 |
| --- | --- | ---: | ---: | ---: | ---: |
| 1m | 530 / 530 | 127,730 / 127,730 | 0 | 0 | 0 |
| 5m | 530 / 530 | 25,970 / 25,970 | 0 | 0 | 0 |
| 15m | 530 / 530 | 9,010 / 9,010 | 0 | 0 | 0 |
| 30m | 530 / 530 | 4,770 / 4,770 | 0 | 0 | 0 |
| 60m | 530 / 530 | 2,650 / 2,650 | 0 | 0 | 0 |

**源的日期、代码和日内时间点完整性已通过，较07:21那批113,853行补齐56,277行。** 只读计数没有核验价格数值，不冒称全部质量检查通过；正式刷新仍须原job/check执行。07:25日线五项结果不重跑。完成源审计时尚未修改业务代码、触发DG新run、改开关或写Lake；该阶段等待入口确认，之后管理员已批准10.2—10.5，开发与执行结果续记下文，不能拿已有10份不完整文件当新补源结果。

证据目录`/private/tmp/dg_index_18007_mmf5ki97`保留3次精确任务查询、一次源审计JSON及对应只读SQL、源齐后的DG运行状态。未创建定时调度或持久化自动任务；18007已结束，无需继续轮询。后续按10.3—10.5执行，不以本记录冒充已经补齐DG19项。

### 10.7 开发硬口径与验收落点（批准后、编码前）

| 硬口径 | 代码落点 | 必要验证 |
| --- | --- | --- |
| 默认不变、只显式替换 | 配置类、两个完整run config builder、两个资产工厂和两个writer | 默认旧文件保持stat/内容且不访问Prod；非法模式拒绝；五/七项配置正确；真实资产job识别默认及显式值 |
| 同代码增加日内记录必须刷新 | 两个writer跳过旧目标分支、调用原builder生成candidate并传overwrite | 真实11列小Parquet经原Raw生成和Silver转换，旧1根变为2根，字面预期核对时间与数值；修正前同样请求只能复用旧文件 |
| 业务计算和检查不放宽 | 不修改原builder/SQL、窗口及checks | 原Raw/Silver/check回归；90/120m完整窗口通过、缺根拒绝；不得只mock整个writer |
| 候选完整校验后再替换，旧数据和其他日期不误改 | 现有MinutePartitionPublication | 失败保留旧文件；替换前/后中断续跑不重建；同身份模式变化拒绝；另一日期哨兵保持不变 |
| 范围不扩展 | 六个生产代码文件及本轮测试 | 不改shared writer/Gold/sensor/Prod；bootstrap默认参数及其他资产不变；配置无反向import循环 |

新增集中回归文件`tests/test_index_mins_replace_existing.py`，与10.4列出的原最小回归组合运行。现有测试中DuckDB默认temp可指向正式卷；本轮使用`/private/tmp`的进程内测试启动器统一替换仅测试进程内的连接为专属临时目录、禁止网络，并使用临时DAGSTER_HOME/ephemeral instance。原测试的业务断言不改、不skip；测试中小型固定内存参数只为隔离，不改正式资源配置。所有真实生产写入仍在隔离验证和实现对账之后。

### 10.8 开发、隔离测试及执行前对账

10.3六个生产代码文件已按表落地：配置类及五/七项builder、两个资产工厂注入配置、两个公共writer传入overwrite并仅在默认模式保留旧文件复用分支。低层SQL/公式、共用发布模块、Gold、sensor逻辑、bootstrap默认和Prod均未改。没有增加额外配置来源或绕行入口；源码与两个原接入文档中“无配置/不能显式替换”的现行表述已同步纠正，历史执行记录保留。

隔离结果：新增集中回归与原Raw writer、Silver writer、checks、contracts、共用staging回归共`60 passed`，零失败，最终耗时4.13秒。新增测试实际执行原SQL与发布模块；原Raw五频和Silver七频job在ephemeral instance中真实运行，12项原检查通过；仅替换Prod网络接入为11列小Parquet。独立字面断言核对同代码1根变2根、五频241/49/17/9/5根、90/120m量额窗口，覆盖缺根拒绝、候选失败不改旧文件、替换前后中断继续不重建、同身份改模式拒绝及另一日期不变。网络访问被禁止、正式instance和Lake未连接；临时夹具自动删除。

全src/tests的Ruff致命错误基线通过；本轮新增/改动行零新增诊断。完整文件检查在3个既有文件仍有14条历史诊断，经与HEAD源码逐项核对均已有（3条无用noqa、4条日期/时间解析风格、7条异常类型风格），本轮不扩大修改；其余4个涉及文件检查通过。测试报告、静态结果及既有诊断对照保存在10.6证据目录的`validation/`。这些结果证明隔离开发通过，正式加载和19项补齐尚待下节实际执行，不预填成功。

### 10.9 正式执行结果与收尾（2026-11-03）

按10.5保存三条分钟sensor开关、cursor、lastRunKey后临时停止，读回全部STOPPED且三个原job无活动run。通过原控制平面重新加载orchestrator，加载结果LOADED、没有加载错误；运行schema逐项确认12个Raw/Silver资产均默认`reuse_existing`且支持`replace_existing`。未重启整套DG、未修改其他sensor、未改cursor/run key、未手动评价sensor。

| 顺序 | 原job / 精确run | 北京时间 | 模式、结果及原检查 |
| --- | --- | --- | --- |
| M1 | `raw_index_mins_update_job` / `44865bc9-71ef-41a9-bd2d-92e58cf76af6` | 08:12:45—08:14:24 | 五频显式替换，SUCCESS；5项物化、5项原检查通过，170,130行；每频实际Prod抽取query_count=1 |
| M2 | `silver_index_mins_update_job` / `5b886bcc-3e66-44ff-9c6f-f275d8c1e0f1` | 08:15:39—08:15:41 | 七频显式替换，SUCCESS；7项物化、7项原检查通过，172,780行；90/120m完整窗口通过 |
| M3 | `gold_index_mins_update_job` / `361c4f19-1582-4d30-a231-a91e192f78a4` | 08:16:26—08:16:28 | 原默认生成，SUCCESS；7项物化、7项原检查通过，170,660行 |

全部为新的独立root run，未接续旧失败run/receipt；严格在上一job成功且原检查通过后提交下一job，正常各一次，没有自动重跑或新增运行限制。

| 频率 | Raw行数 | Silver行数 | Gold行数 |
| --- | ---: | ---: | ---: |
| 1m | 127,730 | 127,730 | 127,730 |
| 5m | 25,970 | 25,970 | 25,440 |
| 15m | 9,010 | 9,010 | 8,480 |
| 30m | 4,770 | 4,770 | 4,240 |
| 60m | 2,650 | 2,650 | 2,120 |
| 90m | 不适用 | 1,590 | 1,590 |
| 120m | 不适用 | 1,060 | 1,060 |

收尾辅助核对表一度把Gold 1m误写为每代码240根；核对`cn_a_derived_minute_bars.py::_build_windows(1)`及既有writer测试后纠正为241根（保留09:30）。其他Gold频率将竞价点合入首个窗口，因此不同层行数不要求相等。该错误仅在临时核对表，正式代码、job和原检查均正常，未因此改写业务结果或重跑。

验收复用本轮19项物化和19项原检查，并逐项核对日期2026-11-02、资产、行数、替换模式及检查绑定的本次精确run；只对这19个规范路径做stat，全部存在且非空，未另读行情明细或重复全目录审计。正式文件合计22,758,094B：Raw 7,626,226B、Silver 7,748,165B、Gold 7,383,703B。此前已完成的日线5项未重跑，故本次19项加日线5项，原11月2日指数链24项缺口均已处理。本数是正式结果文件体积，不能冒称实际总I/O；正常运行沿10.5预算执行，未测量设备总读写量。

确认三个原job无活动写入后，三条sensor均用原生start恢复RUNNING；恢复返回的cursor和lastRunKey与停止期间保存值完全一致，未reset。正式Lake结果、原失败记录、staging/receipt和日志保留。证据目录保留`execution_result.json`、三份逐job验收及必要源/配置/测试证据；无用调用文件、重复响应和隔离夹具清理，Git未自动提交，其他工作区改动未纳入本轮。
