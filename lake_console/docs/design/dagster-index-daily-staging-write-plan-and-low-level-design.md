# 指数日线Raw、Silver及主要指数Gold安全写入方案与LLD

2026-11-02整理记录（历史）：本文按当时工作区源码说明已有设计；相关指数实现仍有未提交内容，文档入Git不代表代码已一并提交或部署。当次仅整理并提交本文与[分钟线写入方案](dagster-minute-raw-silver-staging-write-plan-and-low-level-design.md)，未修改代码、配置、正式数据或运行状态。2026-11-03追加的11月2日补齐范围、执行方式与结果见第8节。

保留原文件路径及既有章节链接。原文中22日缺口、Prod零行、待批准及目标旁临时文件的描述是历史阶段，不再作为当前执行指令；补数结果见[22日恢复记录](../../reports/datasets_recovery_20261022_20261024/README.md)和[30日收尾](../../reports/datasets_recovery_20261030_20261031/README.md)，已清理的过程附件不重新生成。

## 1. 目标、范围与代码位置

对指定交易日的一个文件，先生成候选，校验后逐文件替换，保留失败现场及继续执行依据。范围仅为下列三个对象；下文`defs/`均指`lake_console/orchestrator/src/orchestrator/defs/`。

| 对象 | 当前入口 | 保留的业务规则 |
| --- | --- | --- |
| `raw_index_daily` | `assets/index_daily.py::write_raw_index_daily_partition_from_prod_db`及其低层writer | 只读Prod `core_serving.index_daily_serving`目标日、登记代码集合的11列投影；保留源非空、主键、日期、范围及代码覆盖检查，不固定代码数为历史的820 |
| `silver_index_daily` | 同文件`write_silver_index_daily_partition_from_raw_file` | 原目标日归一化SQL、完全相同重复行去重及冲突重复键拒绝不变；预期行数为目标日源行数减去完全重复行数 |
| `gold_market_major_indices_daily` | `assets/market_major_indices.py::write_gold_market_major_indices_daily_partition` | 使用目标日有效seed名单及原排名，缺代码时拒绝；预期行数取有效seed数，不把历史11只写成永久常量 |

三个入口均调用`io/index_daily_writer.py::write_index_daily_partition`。不扩展到股票日线、周/月线、分钟线或QFQ/MACD/九转。Raw日期保留`YYYYMMDD`字符串，Silver/Gold使用现行`DATE`，源字段可空规则不变。完整业务合同见[原指数日线方案](dagster-index-daily-raw-by-date-prod-db-migration-plan.md)、[原LLD](dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md)和[主要指数LLD](dagster-phase-3-major-indices-low-level-design.html)。

## 2. 调用身份和入口边界

日常资产传入`context.run.root_run_id or context.run.run_id`：Raw参数名为`run_id`，Silver/Gold为`publication_id`。直接调用Silver/Gold不传身份时，模块生成独立UUID，不自动接管其他执行。

Raw的`IndexDailyRawConfig.write_mode`仍仅允许`replace`；Silver/Gold公共writer保留原替换行为，不新增job、check、配置或分区。`materialize_silver_index_daily_partition_from_raw_file`及000680专项继续复用公共writer；若目标是专项staging文件，只提交到该目标，不顺带提升为正式Lake文件。原正式checks及下游依赖保留，receipt不代替物化或检查结果。

## 3. 路径、锁与输入身份

正式Lake为`/Volumes/datasource/data_lake`，正式候选及执行记录在`/Volumes/datasource/data_lake_staging`。正式目标必须匹配`paths.py`中对应对象和日期的路径；正式Lake与staging须已存在。专项目标可位于正式staging，系统临时目录只用于隔离测试；不使用退役Lake、Kopia或文件备份。

Silver/Gold默认目录为：

```text
data_lake_staging/index_daily/<dataset>/target=<目标路径SHA256>/run_id=<执行身份SHA256>/
  receipt.json
  attempt=<UUID>/part-000.parquet
```

同一目标的锁在其`target=<摘要>`目录内。Raw由`paths.py::raw_index_daily_staging_path`生成`index_daily/raw_index_daily/run_id=<安全身份>/trade_date=<日期>/part-000.parquet`；提交模块使用该路径的父目录保存receipt和独立attempt，但仍共用按正式目标确定的锁。

文件stat身份包括设备、inode、大小、mtime和ctime。代码检查父路径穿越和符号链接，允许macOS标准`/tmp`、`/var`别名；同目标采用非阻塞`flock`，退出时释放锁。候选必须在本次执行目录，提升前与目标父目录同设备；不承诺多文件整体原子提交。

Silver绑定Raw源路径/stat、select SQL摘要、预期行数和日期；Gold另绑定有效seed行及有效期。记录还包含版本和对象。源缺失或同身份输入变化时拒绝继续；提升前再次核对文件源stat。

<a id="9-执行前新发现raw候选目录冲突待确认额外范围"></a>
<a id="10-raw额外修正方案与lld开发前"></a>

## 4. Raw内容依据与继续执行

原第9、10节对应的Raw修正已在工作区实现；以上锚点保留既有引用，不再表示待批准。

Raw先把Prod投影读入DuckDB临时表，通过原完整性检查后，以原11列输出、按`ts_code`排序的JSON计算内容SHA256。提交时绑定内容摘要、源SQL摘要及实际预期代码集合，并提供原Raw候选校验器。无文件源的例外仅限这个带业务输入依据和校验器的分支。

**Raw同身份再次调用仍会重新读取并核对Prod目标日内容。** 内容相同才可复用候选或确认完成；同样行数但值变化也会拒绝。不能把公共模块不再COPY理解为Raw整个入口不访问Prod。Silver/Gold的继续依据则是已绑定文件stat及SQL/seed等输入身份。

## 5. 候选校验与逐文件提交

1. 取得目标锁，核对路径、输入及既有receipt，记录正式目标写前stat。
2. 无记录或`building`时，创建新的attempt，先保存`building`，再由原DuckDB SQL执行COPY；旧失败attempt保留。
3. `_validate_candidate`核对现行schema的列顺序/类型、目标日期、正行数和预期行数；Raw另运行原候选校验器。公共层不代替业务主键、覆盖、冲突处理或正式checks。
4. fsync候选，计算摘要并保存`validated`；提升前再次核对候选摘要、源stat、写前目标及同设备。
5. 先持久保存`promoting`，单文件`os.replace`，fsync目标目录；目标摘要匹配后保存`promoted`。

| receipt状态 | 当前处理 |
| --- | --- |
| `building` | 只生成本文件的新attempt，不删除原失败候选 |
| `validated` | 输入和原目标未变、候选存在且摘要一致时继续，不再次COPY |
| `promoting` | 目标已匹配记录摘要时补记完成；否则仅在原目标未变且候选完整时继续 |
| `promoted` | 目标摘要匹配才复用完成结果，不匹配即拒绝 |

未知状态、输入/目标/候选变化、锁冲突、空间不足或跨设备均按代码报错，保留现场。文件已替换而事件失败时，分别核对文件/receipt与原run，不把失败run直接改绿，不自动整链重采。

## 6. 读取成本与执行预算

正常新生成路径会计算一次候选摘要，提升前再次读取候选摘要，替换后读取目标摘要；另有候选schema/日期/计数和原业务源查询，当前实现并非“只读一遍文件”。`validated`继续核对候选，完成分支核对目标；Raw仍有第4节的当日源核验。

当前空间检查为`1.2 ×（绑定源文件字节和＋已有目标字节）＋8MiB`。无文件来源的Raw不能因此推定整个任务只需8MiB。正式执行需按实际对象、来源、候选、临时空间、原检查和中断后成本核定，不沿用22日一次批次的旧预算，不新增内存、并发或超时限制。

本文仅描述实现，不授权新日期补数或历史全局读取；正式执行沿原job和依赖顺序，在已有授权内进行，物理文件、检查和任务状态分别验收。

## 7. 验证依据与本次整理

- 当前测试位置为`tests/test_index_daily_staging_writer.py`及原Raw/Silver/主要指数合同测试，均相对于`lake_console/orchestrator/`。已核对其包含真实writer、schema/日期/计数反例、失败留存、输入/候选/目标变化、锁/路径/设备/空间、替换前后中断、真实进程退出及Raw同计数变值等用例。
- CodeGraph核对日线调用关系，源码补核Raw和Gold入口；本轮按工作区代码整理，不把文档或历史通过数量当成代码提交/部署证据。
- 本轮保留有效规则，精简历史过程，更新标题和状态，保持原文件名及外部章节引用。提交前核对源码、链接/锚点、文档完整性及两文件暂存范围；不重跑测试、补数、原checks、性能测试或全局审计。

<a id="recovery-20261102"></a>

## 8. 2026-11-02指数日线及下游补齐方案、LLD与执行记录

### 8.1 目标、授权与已核实来源

2026-11-03管理员说明已重新下载此前缺失数据，并授权「如果补齐了，你就开始推进dg的补数」。本步仅恢复11月2日五项日线资产；同日普通指数分钟线19项按[分钟线执行LLD第9节](dagster-minute-raw-silver-staging-write-plan-and-low-level-design.md#recovery-20261102)推进。不开发代码，不改变对象池、公式、schema、配置、job/check/sensor入口，不重做已完成股票链或其他日期。

07:04:19北京时间，强制只读Prod事务确认`core_serving.index_daily_serving`中`931772.CSI`、`931834.CSI`的11月2日各1行；07:04:16原Raw sensor的现有探测记录为820个登记代码全部覆盖、820行、缺失/额外/重复/空键/错日均0、ready=true。该记录足以使用原Raw入口，不另做全表价格审计或重新下载。

### 8.2 原job顺序与实现位置

| 顺序 | 原job | 本日正式结果 | 原检查数 |
| --- | --- | --- | ---: |
| D1 | `raw_index_daily_update_job` | `raw_index_daily` | 2 |
| D2 | `silver_index_daily_update_job` | `silver_index_daily` | 4 |
| D3 | `market_major_indices_daily_update_job` | `gold_market_major_indices_daily` | 4 |
| D4 | `gold_major_index_daily_nineturn_update_job` | `gold_major_index_daily_nineturn` | 1 |
| D5 | `prod_core_index_daily_nineturn_sync_job` | `prod_core_index_daily_nineturn` | 1 |

D1—D3沿本文第1—6节现行writer；D4沿`assets/major_index_nineturn.py`、`major_index_nineturn.py`的原单日生产与integrity check；D5沿`assets/index_daily_nineturn_prod_core.py`和`prod_db/index_daily_nineturn.py`的原发布入口。复用原run config，目标分区固定`2026-11-02`；Raw的既有`write_mode=replace`不变。只消费已有基础资产、登记集合及有效seed，不把基础资产加入selection。

07:04:16原sensor已提交D1：`dc11ccab-8d8b-404f-9aad-949226370004`。沿用该run，观察原RUNNING sensor按依赖提交后续job；不另交重复run，不执行sensor evaluation，不改cursor/开关/间隔，不以临时调用writer代替job。若原链报错、检查失败或来源变化，停止本轮人工推进，核对该run现有记录后汇报，不自动重跑。完成部分保留，未完成部分需按原记录和输入身份核清后再安排，不改失败run为成功。

### 8.3 明确读写边界、历史上下文与预算

- D1只读Prod目标日、现行登记代码、原11列投影；D2只读当日Raw；D3只读当日Silver及有效主要指数seed。此前820个代码是本次证据，不改成永久常量。
- D4原`MAJOR_INDEX_NINETURN_SOURCE_CONTEXT_TRADE_DAYS=20`：只读取截至11月2日最近20份主要指数日线Gold的代码、日期、close，以及10月30日前一日九转seed；不是全历史读取或历史重算。该日Gold尚未生成时，预先stat的最近20份旧日文件共52,535B、前一seed1,214B；原planner最终只选19份前日上下文加目标日，不固定为这20份旧日。公式、历史计数延续及原检查不变，只写11月2日九转结果。
- D5只写Prod `core_serving.index_nineturn_daily`的11月2日分区，使用原事务替换及原读回检查；不写Prod日线源表、其他日期或其他Serving表。代码/行数取当日有效seed和原检查，不把11只写成永久要求。
- 与分钟线第9节合并，本轮24资产、8个原job、31项原检查，保守估算读1GiB、写64MiB、额外空间128MiB；包括候选/目标摘要、原检查和最后有界收尾，预算不等于设备IO实测，不作为新增执行限制。日线普通文件约KiB级，分钟线10月30日参照19份文件约21.65MiB，作为预算量级依据，不冒充11月2日实际字节。
- 正常每个必要job一次；若中断，不自动重跑。后续确需继续原范围时应额外预留该未完成部分一轮、至多本轮正常预算的开销并先核清现场，不擅自重做已完成步骤。正式Lake/staging规则、逐文件原子提交、receipt留存沿原实现，异常现场不清理。

### 8.4 验收与记录方法

仅核对本日五个精确run的终态、5项物化、12项原检查及其对应物化；复用原job报告的行数/路径/发布读回，必要时只stat精确本日文件。不重复运行全目录审计、checks-only或历史公式重算。候选通过、run成功及最终物理数据分开判断。已有源码未提交改动保留，本轮不重启DG或加载另一套代码。

只读来源与运行证据目录：`/private/tmp/dg_index_recovery_20261102_yxhydnqj`；本段为执行前安排，实际run、检查、物理结果及清理记录见8.5，不以计划预填成功。

### 8.5 日线正式完成及本轮分钟链停止结果（2026-11-03）

**11月2日日线链五项已完成。** 下列五个原job均由既有RUNNING sensor按依赖自动提交并SUCCESS；未额外手工启动重复run。时间均为11月3日北京时间。

| 步骤 | 精确run ID | 开始—结束 | 本日行数 | 物化/通过原检查 |
| --- | --- | --- | ---: | ---: |
| D1 Raw | `dc11ccab-8d8b-404f-9aad-949226370004` | 07:04:25—07:04:30 | 820 | 1 / 2 |
| D2 Silver | `6bc8ecaf-9e32-44e3-aa64-bb24989c94fe` | 07:14:30—07:14:36 | 820 | 1 / 4 |
| D3 主要指数Gold | `a25ca2b4-fcb7-4b46-8095-694d2652511a` | 07:17:39—07:17:44 | 11 | 1 / 4 |
| D4 日线九转Gold | `461337cb-d756-4a1e-86c2-9afb80a2c29e` | 07:23:46—07:23:51 | 11 | 1 / 1 |
| D5 九转Prod | `7271f074-a59b-4679-b459-afa1b36f382e` | 07:24:17—07:24:23 | 11 | 1 / 1 |

12项原检查全部通过，核对到本次目标资产、分区及targetMaterialization对应run；Prod原发布读回检查通过。日线完整结果与当日四份正式文件stat相符。没有追加价格读取、历史重算或日线重复执行。

**合并本轮的真实状态。** 计划24项中，日线5项完成；分钟Raw五频和Silver原生五频虽有10项正式物化、10项原检查通过，但经必要时间点计数确认日内行情仍不完整，不能销账为业务补齐。分钟Silver 90/120m生成前报不完整窗口，Gold七频没有本日run，合计9份文件仍缺失。详见[分钟线9.4](dagster-minute-raw-silver-staging-write-plan-and-low-level-design.md#recovery-20261102)。既有原生检查覆盖边界与日内完整性不同，不宣称原31项计划已全部通过。

07:25收尾只复用七个精确run（6 SUCCESS、1 FAILURE）、15项物化、22项已通过原检查，以及指定23份预期Lake文件的stat（14份存在非空、9份缺失），未重新运行180项目录审计。检查记录的asset/check名称与当前catalog一致、目标物化run正确。正式失败run及staging现场保留，不改状态、不自动重跑；本轮未修改业务代码、运行限制、sensor开关/cursor，未直接调用writer补数或手工写业务数据。日线sensor正常推进不因独立分钟链失败而被擅自停用。

执行结果和必要来源证据保留于上述临时证据目录的`execution_result.json`、`source_coverage.txt`、`source_coverage_current.txt`、`window_counts.json`、`window_counts_other.json`、`silver_minute_failure_details.json`共6份小型证据。本轮29个临时调用脚本、SQL调用文件、重复状态/事件快照和输出文件已按精确清单删除，共344,575B；必要物化和检查依据已归入执行结果JSON，正式数据、staging/receipt及原日志未动。原06:51全目录审计JSON及此前原因审计证据保持原样。两份本轮设计/LLD文档尚未提交，其他工作区改动保持原样。文档完整性检查与两文件`git diff --check`通过，不把文档检查当数据验收。

## 9. 2026-11-04指数日线及下游补齐方案、LLD与执行记录

### 9.1 目标、来源与授权

2026-11-05管理员确认此前缺少的5个指数代码已补入Prod，并明确要求推进本日日线和下游。本轮仅覆盖第8.2节D1—D5的五项资产，日期固定为`2026-11-04`；不开发代码，不改对象池、公式、schema、配置、sensor状态或cursor，不涉及THS资金流、国际指数或分钟线，不重刷其他日期。

复用原Raw sensor在06:47:24北京时间保存的Prod覆盖证据：`core_serving.index_daily_serving`当日应有820个代码，实际820个、820行，缺失、额外、重复、空键和错日均0。此前5个缺口为`930767.CSI,931039.CSI,931136.CSI,931772.CSI,931834.CSI`，本次不再重复读取Prod价格明细或请求Tushare。820是本次运行证据，不是代码常量。

核验时D1原sensor已提交`12b9c090-14b2-4b23-ba88-f301e2f1ebf2`并成功，D2原sensor已提交`abd5bcb0-e208-4876-863b-2d61269933c5`并成功；沿用二者，不重复提交。四层正式文件和Prod目标沿第8.2节原实现，不调用writer临时补数。

### 9.2 执行顺序与LLD

| 顺序 | 原job | 本轮处理 | 原检查数 |
| --- | --- | --- | ---: |
| D1 | `raw_index_daily_update_job` | 核对已有成功run及本日Raw | 2 |
| D2 | `silver_index_daily_update_job` | 核对已有成功run及本日Silver | 4 |
| D3 | `market_major_indices_daily_update_job` | Silver通过后生成本日主要指数Gold | 4 |
| D4 | `gold_major_index_daily_nineturn_update_job` | D3通过后生成本日日线九转 | 1 |
| D5 | `prod_core_index_daily_nineturn_sync_job` | D4通过后发布本日Prod九转并原生读回 | 1 |

五个相关sensor均已RUNNING。优先观察原sensor依赖顺序提交，不能执行sensor evaluation、修改cursor、开关或间隔。每步通过后才推进下一步；查询发现同日相同job已有QUEUED、STARTING或STARTED则等待，SUCCESS则复用。确需人工提交时，只通过现有本机DG `http://127.0.0.1:3000/graphql`向`orchestrator/__repository__`提交表中原job，`dagster/partition=2026-11-04`、原run config及原全部检查，使用现有正式DAGSTER_HOME；不得本地in-process执行、直接写湖或补报事件。

本机启动入口`local_startup.configuration`只接受既有`/Users/congming/.goldenshare/dagster_home`，本轮仍使用该实例，不启动、重启或初始化服务。人工提交D4时，工作目录为`/Users/congming/github/goldenshare/lake_console/orchestrator`，完整命令如下；请求只声明原job、空run config和上述本日分区标签，由正式run coordinator执行，不在提交脚本中读取行情或运行计算：

```bash
curl --fail-with-body --silent --show-error --max-time 25 \
  http://127.0.0.1:3000/graphql -H 'Content-Type: application/json' \
  --data-binary @/private/tmp/dg_index_daily_20261104_0kwok7ua/launch-nine.json \
  --output /private/tmp/dg_index_daily_20261104_0kwok7ua/launch-nine-response.json
```

请求采用官方`launchRun(executionParams)`，selector的jobName为D4；提交前仍先检查是否已由sensor创建。D5优先沿原run-status sensor接续；确需人工提交时按同一形式只替换jobName和该job的partition-set标签，必须先验收D4。

本轮依据包括`assets/market_major_indices.py`、`major_index_nineturn.py`、`assets/major_index_nineturn.py`、`assets/index_daily_nineturn_prod_core.py`和`prod_db/index_daily_nineturn.py`。CodeGraph已核对主要指数Gold、九转planner和Prod发布调用关系；再逐项阅读真实SQL、原检查及路径，确认未改变计算与消费者。

### 9.3 读写范围与成本依据

- D1/D2已完成，不再重复读写。已有Raw、Silver文件stat分别为62,301B、62,291B；D3只消费本日Silver、当日有效主要指数seed及原检查所需基础引用。当前CSV有11个在本日有效的代码，D3—D5预期各11行，以原检查最终确认为准。
- D4按现行`MAJOR_INDEX_NINETURN_SOURCE_CONTEXT_TRADE_DAYS=20`取最近20个日线Gold文件，包括目标日。执行前仅stat了19个前日上下文，范围`2026-10-08`至`2026-11-03`、合49,897B；另读`2026-11-03`九转seed，stat为1,225B。读取字段是代码、日期、close及前日计数/信号，不读更早历史、不重算既有日期。20来自代码；19=20−目标日1份，不是另设上限。planner目录枚举只发现文件名，不读取所有历史内容。
- D3随后已由原sensor完成，run为`e5bc4302-efe1-41f0-9653-a1cb1204ec56`，11行和4项原检查通过。本日Gold stat为2,626B，因此D4所需20份行情文件压缩大小为49,897＋2,626＝52,523B，连同前日seed共53,748B；这仍不是实际设备IO测量或整个job全部读取量。
- D5只读取本日两个Gold文件，调用原事务更新`core_serving.index_nineturn_daily`的本日11行，并执行原读回检查；不写Prod日线源表、其他日期或其他表。原事务失败回滚本次本日发布。
- 正常执行成本以各未完成原job一次及其6项原检查为单位；完整链合计12项检查，D1/D2的6项只核对已有结果。D3沿原writer保留候选验证及候选/目标摘要，D4保留源文件stat核对、候选验证及原integrity check，D5保留原Gold核验、发布读回及独立检查，不另外重算公式或运行checks-only。最终收尾只读上述精确run事件及四个本日文件stat/footer计数，不再次审计全目录。
- 以上字节数是已存在文件的压缩大小，不冒充磁盘实际读取量。目标Gold、九转文件尚未生成，其压缩大小、数据库页/WAL、DuckDB缓存和实际设备IO不能在执行前准确确定；本轮不为此编造固定字节预算、倍率或耗时保证，也不套用第8节混合分钟链的旧1GiB预算。执行后记录实际文件大小。新增正式文件仅D3/D4各一份、各11行；候选仍在正式staging，同文件系统替换，现行空间检查和连接参数保持。
- 中断或失败即停止人工推进，不自动重跑，不回滚已成功的前序步骤。后续确需继续，先核对未完成job的正式文件、receipt及输入身份；只对未完成步骤另行确认，最坏需再承担其同一组有界来源、候选生成和原检查一轮，已完成job及19份历史文件不另做人工重读。收尾只整理已有证据，不把中断成本隐去。

### 9.4 验收与记录

分别核对五个原job终态、五项物化、本日目标及12项原检查与对应物化run的绑定；四个Lake文件存在非空、footer行数应与物化一致，Prod由原发布读回与原检查证明。此前全目录审计JSON保留，不改写，不重复执行全局审计。业务staging/receipt和原日志保留；本轮过程文件统一在`/private/tmp/dg_index_daily_20261104_0kwok7ua`，有效执行结果回写本节后清理无用过程文件。

本轮无业务代码改动，不新增测试或性能测试。文档执行完整性和差异检查；数据验收以原job及其原检查为准，不用文档检查代替。下节只在取得真实结果后填写，不预填成功。

### 9.5 正式完成与收尾（2026-11-05）

**11月4日指数日线链五项已补齐。** 以下时间均为11月5日北京时间，五个原job均SUCCESS。D1、D2、D3、D5由原RUNNING sensor提交；仅D4在D3四项检查通过、且确认本日没有九转run后，通过第9.2节GraphQL提交一次原job。未直接调用writer、执行in-process计算或重复提交前序job。

| 步骤 | 精确run ID | 开始—结束 | 本日行数 | 通过原检查数 |
| --- | --- | --- | ---: | ---: |
| D1 Raw | `12b9c090-14b2-4b23-ba88-f301e2f1ebf2` | 06:47:32—06:47:39 | 820 | 2 |
| D2 Silver | `abd5bcb0-e208-4876-863b-2d61269933c5` | 06:47:51—06:47:57 | 820 | 4 |
| D3 主要指数Gold | `e5bc4302-efe1-41f0-9653-a1cb1204ec56` | 06:52:02—06:52:07 | 11 | 4 |
| D4 日线九转Gold | `447870f4-32df-42d2-9bc4-c77fb7f90141` | 06:54:50—06:54:57 | 11 | 1 |
| D5 九转Prod | `00267b8a-5e92-40dd-b0b0-69fd81d69a77` | 06:55:21—06:55:27 | 11 | 1 |

五项物化均对应`2026-11-04`。12项检查全部通过，`targetMaterialization`分别绑定上表run，物化storage ID依次为`7897480`、`7897520`、`7897578`、`7897633`、`7897661`。D1—D3原检查事件的partition字段为空，按其明确绑定的本日物化验收，不伪写成事件自身带有日期。D4、D5检查的partition明确为本日。九转物化报告来源文件数21，等于20份行情上下文加1份前日seed，与原planner范围一致。

四份本日Lake文件经一次footer计数及前后stat核对，行数依次820、820、11、11，均非空且读取时未变化；大小依次62,301B、62,291B、2,626B、1,212B。新增D3/D4正式结果合3,838B，该值只表示文件压缩大小，不表示运行写IO、数据库WAL或原检查总读取量。未追加历史行情明细读取或重复公式验算。

Prod原发布读回11行，原分区检查再次读回11行、失败0行，Gold与Prod业务内容摘要均为`dc868d51ff15b421b84648ba18e09acd9867a9b8269361ab52d249613ff8ea08`。只更新`core_serving.index_nineturn_daily`的本日数据，没有写入Prod日线源表或其他日期。

收尾复用五个精确run的原事件及上述物理计数，未再次执行全目录审计、checks-only、Tushare下载或其他数据链补数。仅本文件增加第9节，业务代码、sensor开关/cursor、运行参数及其他工作区改动保持。本轮10份私人临时请求、响应、范围和计数文件共处于第9.4节目录；必要结果已归入本节，收尾删除该临时目录，不清理正式数据、业务staging/receipt或Dagster原日志。文档完整性和本文件差异检查通过；本轮文档未提交，未推送。

## 10. 2026-11-06指数日线及下游补齐结果

2026-11-07管理员确认已补齐Prod并要求推进11月6日指数日线链。11月6日23:53和11月7日07:35的Raw传感器记录显示，Prod日线源表缺`931772.CSI`、`931834.CSI`，当时只覆盖818个登记代码。11月7日07:45:41，原传感器确认`core_serving.index_daily_serving`目标日覆盖820个登记代码、共820行，缺失、额外、重复、空键和错日均为0，随后提交Raw，检查编号为`3364227`。五个原任务按第9.2节的依赖顺序由各自传感器提交并成功。表中时间均为11月7日北京时间。

| 步骤 | Dagster运行编号 | 开始—结束 | 本日行数 | 通过的原检查数 |
| --- | --- | --- | ---: | ---: |
| Raw指数日线 | `31b66f28-d305-427c-93ae-d550c9429065` | 07:45:47—07:45:53 | 820 | 2 |
| Silver指数日线 | `52cb6940-b6bc-4f80-8585-be1ced8c6e91` | 07:54:05—07:54:10 | 820 | 4 |
| 主要指数日线Gold | `47b04fa7-3c6c-4606-9060-dbcee0c3943e` | 07:54:25—07:54:30 | 11 | 4 |
| 指数日线九转Gold | `268ce2a7-cd1e-474a-98ee-2e33f2425526` | 07:55:37—07:55:42 | 11 | 1 |
| 指数日线九转Prod | `d4744288-ca77-44b7-9644-dc4cedd89acc` | 07:56:02—07:56:08 | 11 | 1 |

五项物化均属于`2026-11-06`分区，存储编号依次为`7926673`、`7926713`、`7926771`、`7926826`、`7926854`。12项原检查都通过，并分别绑定表中对应运行的物化记录。四份正式Lake文件的Parquet元数据行数与物化记录一致，文件在读取期间稳定，压缩大小依次为61,240、61,230、2,628和1,212字节。

Prod发布与原分区检查分别从`core_serving.index_nineturn_daily`读回当日11行，检查失败0行。Gold与Prod的业务内容摘要一致，均为`70f4caeb08a21ea46b665ef11cfa3dc66dbd80163a2a5b85584d80918b35f674`。本次验收复用了原任务和读回记录，并只读取四份目标日Lake文件的Parquet元数据。

## 11. 2026-11-11指数日线及下游补齐结果

2026-11-12管理员要求「推进下游补数吧」。本次沿第9节原任务、依赖顺序、正式Lake和staging边界核查，仅覆盖11月11日指数日线及其四项下游，不涉及其他日期、分钟线或其他数据集。07:59只读核验时，Prod仍缺碳中和60（`931772.CSI`）和福建100（`931834.CSI`）两条当日指数日线；09:15只读核验确认两者已在Prod原始表和服务表各有1行。原Raw传感器09:10的探测已确认820个登记代码全部覆盖，随后原自动调度依次推进。

收到本次指令后，09:20首次检查发现Raw、Silver和主要指数日线Gold已成功；进一步核查期间，日线九转和Prod发布也由既有传感器完成。五个运行的`dagster/sensor_name`及原run key均已核对，没有人工提交重复任务、运行sensor evaluation或修改开关、cursor、间隔。没有直接调用writer，不重启或初始化DG，不改变业务代码、公式、字段、对象池或资源配置。下表时间均为11月12日北京时间。

| 步骤 | Dagster运行编号 | 开始—结束 | 本日行数 | 通过的原检查数 |
| --- | --- | --- | ---: | ---: |
| Raw指数日线 | `1a4c9e45-d1a0-4cfb-b2bf-a41d68246ef7` | 09:10:49—09:10:54 | 820 | 2 |
| Silver指数日线 | `217472fe-ae55-49c2-988d-1d81e5448d94` | 09:18:41—09:18:47 | 820 | 4 |
| 主要指数日线Gold | `f10d77b2-2d01-4261-80b4-6e5198f2f86b` | 09:19:37—09:19:43 | 11 | 4 |
| 主要指数日线九转Gold | `34db44eb-1985-4f89-9778-55189439d4cd` | 09:20:54—09:21:00 | 11 | 1 |
| 指数日线九转Prod | `fd33c3eb-a7c2-4c0d-a62e-dac01b8b8eea` | 09:21:30—09:21:37 | 11 | 1 |

五个原任务均SUCCESS，五项物化均属于`2026-11-11`；物化存储编号依次为`8025501`、`8025541`、`8025599`、`8025654`、`8025682`。12项检查名称与当前catalog一致，全部通过，且分别绑定表中对应运行的物化。前三步检查的partition字段为空，按其绑定的本日物化验收；后两步检查明确带有本日partition，不改写事件本身的日期语义。

本次代码核对覆盖原九转planner、日线九转资产、原job选择、Prod发布资产、原发布事务和下游run-status传感器。九转沿`MAJOR_INDEX_NINETURN_SOURCE_CONTEXT_TRADE_DAYS=20`读取截至本日最近20份主要指数日线Gold及11月10日九转seed，物化报告来源文件数21。只stat确认这些20份行情文件的日期范围为10月15日至11月11日、合52,525字节，前日seed为1,224字节，合53,749字节；该值是源文件压缩大小，不是设备实际IO或整个任务的读取量。本次没有人工重读这些历史明细、重算公式或重新执行原检查。自动链已全部完成，因此没有中断续跑或重试成本发生；若以后需要重跑，仍按第9.3节核对原任务、文件和输入身份，只处理未完成步骤，不由本记录授权重跑。

09:23最终验收只复用上述五个精确运行的原事件，并对四份本日Lake文件各做一次计数及前后stat核对。实际行数依次为820、820、11、11，文件读取期间稳定；压缩大小依次为61,387、61,377、2,628、1,156字节，合126,548字节，不作为磁盘读取量。Prod原发布及原分区检查均从`core_serving.index_nineturn_daily`读回本日11行，失败0行；Gold与Prod业务内容摘要一致，均为`02740d922bffe2d2e181b88ef8dbe008704e150c0149d775392a7f5b9a0a08f8`。没有追加远程明细导出、Tushare请求、全目录审计或其他数据链补数。

必要验收结果保存在`/private/tmp/dg_index_daily_closeout_20261111_20261112/acceptance.json`；原Dagster事件、日志、正式数据及业务staging保留。本轮仅在本原方案与LLD追加本节，保留文件原有改动和其他工作区内容，不提交、不推送。文档检查不代替上述数据验收。

## 12. 2026-11-13指数日线及下游补齐方案与LLD

### 12.1 本次目标、来源和授权

2026-11-13管理员要求先审计刚同步的Prod，来源已齐时推进指数这条链全部补齐。本次日期固定`2026-11-13`，范围仅为第9.2节D1—D5五项原资产和12项原检查，包含向Prod发布本日指数日线九转；不扩展到国际指数、分钟线、资金流、股票技术面因子或其他日期，不开发或修改业务代码、公式、字段、名单、配置或任务入口。

23:49:24北京时间，通过仓库规定的Prod入口执行只读事务，确认碳中和60（`931772.CSI`）和福建100（`931834.CSI`）在`raw_tushare.index_daily`、`core_serving.index_daily_serving`的本日记录均各1行；两表的开高低收、前收、涨跌额、涨跌幅、成交量和成交额一致。此前23:40的原Raw探测覆盖818/820个登记代码，只缺这两个代码；该历史探测不伪写成当前已全覆盖。完整登记集合仍由原Raw探测/入口核对，必须通过原代码覆盖、主键及日期检查才能写入或进入下游。若仍有来源缺口，停止人工推进并报告。

### 12.2 当前代码、执行方式与影响面

复用第1—6节及第9.2节：D1为`assets/index_daily.py::write_raw_index_daily_partition_from_prod_db`，D2为同文件原Silver入口，D3为`assets/market_major_indices.py`原主要指数入口；三者沿现有`io/index_daily_writer.py`。D4沿`assets/major_index_nineturn.py`和`major_index_nineturn.py`的原日线生产、候选校验及完整性检查。D5沿`assets/index_daily_nineturn_prod_core.py`、`prod_db/index_daily_nineturn.py`原事务发布和读回。CodeGraph核对Raw生产者及其来源/覆盖校验调用链，并逐项核对五个job的asset及check选择、九转20日来源planner、日线资产、Prod事务和原run-status传感器；不改变这些实现或消费者。

五个传感器当前均RUNNING，调度健康。本次优先沿用传感器已创建的本日原任务；每步先查询同日同job，QUEUED、STARTING、STARTED则等待，SUCCESS且本步原检查通过则复用。仅当本步没有原任务且前序已验收时，才经现有本机GraphQL提交该原job一次；不执行sensor evaluation，不改变开关、cursor或间隔，不本地in-process运行，不直接调用writer或补报事件。原任务失败、检查不通过或输入变化即停止人工推进，不自动重试、不把失败run改绿。

工作目录为`/Users/congming/github/goldenshare/lake_console/orchestrator`，目标是现有正式`/Users/congming/.goldenshare/dagster_home`实例、`http://127.0.0.1:3000/graphql`和`orchestrator/__repository__`，不启动、重启或初始化服务。每次人工提交的完整命令为：

```bash
curl --fail-with-body --silent --show-error --max-time 25 \
  http://127.0.0.1:3000/graphql -H 'Content-Type: application/json' \
  --data-binary @/private/tmp/dg_index_recovery_20261113_20261113/<原job名>.launch.json \
  --output /private/tmp/dg_index_recovery_20261113_20261113/<原job名>.launch-response.json
```

这里的`<原job名>`仅取下表对应名称。请求采用已经核对官方文档的`launchRun(executionParams)`；selector只指定上述location、repository和原job，`executionMetadata.tags`固定`dagster/partition=2026-11-13`，保留原完整job selection。D1使用原builder产生的`{"ops":{"raw_index_daily":{"config":{"write_mode":"replace"}}}}`；D2—D5的`runConfigData`均为`{}`，不新增配置。每次提交前再次排除传感器已创建原run；D5优先由原run-status传感器接续。

| 顺序 | 原job | 读写范围 | 本步原检查数 |
| --- | --- | --- | ---: |
| D1 | `raw_index_daily_update_job` | 只读Prod源表本日登记代码的原11列投影，写本日Raw一份 | 2 |
| D2 | `silver_index_daily_update_job` | 本日Raw归一化为本日Silver一份 | 4 |
| D3 | `market_major_indices_daily_update_job` | 本日Silver及有效主要指数seed，写本日Gold一份 | 4 |
| D4 | `gold_major_index_daily_nineturn_update_job` | 最近20份主要指数日线Gold及前日九转seed，写本日日线九转一份 | 1 |
| D5 | `prod_core_index_daily_nineturn_sync_job` | 本日两份Gold，事务替换`core_serving.index_nineturn_daily`本日数据并读回 | 1 |

D1实际预期代码数取当前登记集合，本次探测为820，不成为代码常量。有效主要指数CSV本日有11个代码，D3—D5以原seed覆盖和分区检查实际结果验收。D5不写Prod指数日线源表，不更新其他日期或其他Serving表。

### 12.3 成本、失败、中断与收尾边界

执行预算按每个未完成原job一次、完整链12项原检查计；不额外运行checks-only、全目录审计、源下载或全历史计算。D4的20日窗口来自现行`MAJOR_INDEX_NINETURN_SOURCE_CONTEXT_TRADE_DAYS=20`。执行前仅stat了19份前日行情文件，范围10月19日至11月12日，压缩大小合49,902字节；11月12日九转seed为1,227字节。已有来源合51,129字节，另加尚待D3生成的本日Gold一份，构成20份行情加前日seed的21份来源；不把压缩大小当作实际IO、内存或总读取量，不人工读取这19份历史明细。

正式根及staging仍分别为`/Volumes/datasource/data_lake`和`/Volumes/datasource/data_lake_staging`；二者已核对同设备，候选校验、逐文件原子提升、receipt及原锁机制不变。当前可用空间stat为2,858,027,454,464字节，只表示检查时可用空间，不设新余量或执行限制。候选/目标的最终压缩大小、数据库页/WAL和运行耗时无法事先精确确定，执行后记录实际文件大小和起止时间，不套用其他日期的混合分钟链预算。原连接、内存、并发、临时目录及超时配置保持，不安装扩展或依赖。

D4提交前补核：D1—D3已由原传感器完成，10项原检查均通过，复用三个成功run，不重复读写。D3本日正式Gold为2,627字节，因此D4的20份行情来源压缩大小为49,902＋2,627＝52,529字节，连同前日seed共53,756字节；这不是实际设备读取量。提交前查询本日D4任务为空，按第12.2节只提交原九转job一次。

失败或中断保留已完成文件、正式事件、日志和业务staging；停止领取下一步，不自动重跑。后续确需续跑，先核对未完成步骤的原run、文件/receipt及输入身份，只为该步骤承担同一组有界来源、候选和原检查一轮成本，已完成步骤不重复。D5事务失败只回滚本日当前发布。来源仍不齐或任何原检查失败时，不绕过检查补写下游。

最后验收只读五个精确run的终态、五项本日物化、12项原检查及其对应物化绑定，再对四份本日Lake文件做一次计数和前后stat核对；Prod复用原发布读回、原分区检查及内容摘要。结果写回本节，必要小型证据仅保存于上述`/private/tmp`目录；清理无用请求/响应副本，不清理正式数据、原日志或业务staging。不提交或推送已有工作区改动。文档完整性与差异检查只验证文档，不能替代正式数据验收；无业务代码改动，不新增或重跑隔离测试。

### 12.4 执行与验收结果

**11月13日指数日线及下游五项已全部补齐。** 原Raw探测23:50:49确认Prod覆盖全部820个登记代码、820行，缺失、额外、重复、空键、错日均为0；D1—D3沿原自动调度完成，10项原检查验收通过后，只人工提交D4一次。D5由原run-status传感器接续。以下时间均为11月13日北京时间。

| 步骤 | 精确run ID | 开始—结束 | 本日行数 | 通过的原检查数 |
| --- | --- | --- | ---: | ---: |
| D1 指数日线Raw | `359002fa-ea4f-4fb5-aa37-a20397058a01` | 23:50:57—23:51:03 | 820 | 2 |
| D2 指数日线Silver | `9d62c407-a452-45fe-a4a3-8e043ea6cad4` | 23:52:13—23:52:19 | 820 | 4 |
| D3 主要指数日线Gold | `28006051-83ff-4a1c-85f6-810e1adf0f5b` | 23:52:44—23:52:49 | 11 | 4 |
| D4 主要指数日线九转Gold | `667d2ccd-03fb-455c-99d0-a3f15b67b3e8` | 23:54:41—23:54:46 | 11 | 1 |
| D5 指数日线九转Prod | `26730a67-f0f2-47c3-a989-78268e37f5fd` | 23:55:16—23:55:22 | 11 | 1 |

五个原任务均SUCCESS，五项物化均属于`2026-11-13`；12项检查名称与当前catalog一致，全部通过，且分别绑定上表本日对应run的物化。检查自身的partition字段与原事件一致保存，不把前三步的空partition改写为日期。D4物化报告来源文件数21，与20份行情上下文加1份前日九转seed一致。

四份正式Lake文件各完成一次计数和前后stat核对，读取期间稳定，行数依次820、820、11、11；文件大小依次60,999、60,989、2,627、1,214字节，合125,829字节。该合计仅为文件压缩大小，不是设备实际读取或写入量。五个原任务耗时依次为5.411、5.756、5.339、4.836、5.393秒，分别由原run结束时间减开始时间计算，不含排队或各段间等待，也不作为后续耗时保证。

Prod原发布和原分区检查均读回本日11行，检查失败0行，Gold与Prod业务内容摘要一致，均为`58ab1f10c4a9568b4b0a0ed4ebe1f904d22ab826c89177157e665d2e947b10b9`。只更新本日`core_serving.index_nineturn_daily`，没有写入Prod指数日线源表、其他日期或其他表。本次来源核验复用了原23:50探测及原Raw生产/检查，不额外导出全市场价格，不重新请求Tushare或重读19份历史行情明细。

23:56验收结果保存在`/private/tmp/dg_index_recovery_20261113_20261113/acceptance.json`，两条Prod来源的只读SQL和结果另保留`prod_source.sql`、`prod_source.txt`。原23:39全目录审计JSON不改写；本节和上述验收只将其中本条链五项销账，不重扫或声称其他缺口已修复。重复的临时请求、响应、检查事件副本及状态快照在收尾清理，正式数据、原Dagster事件和日志、业务staging均保留。没有中断或重试，没有启停传感器、修改cursor、调整配置、安装依赖或重启DG。仅本原方案与LLD追加本次执行内容，不提交、不推送。

## 14. 2026-11-20 指数日线及下游补齐方案与 LLD

管理员已补齐 Prod 的碳中和60、福建100，并要求先推进指数日线，再推进下游。21 日 01:02 北京时间，沿规定 Prod 只读入口确认 `core_serving.index_daily_serving` 的 20 日登记集合为 820 个代码、820 行、无缺码；DG 尚无当天 Raw、Silver 文件及相应运行。本次只处理 20 日，沿第 12.2 节 D1—D5 的五个原任务、12 项原检查和原读写合同，随后接续指数周线、月线 Silver，后两项执行边界见周期原方案 §11.21。不涉及分钟线、其他指数数据集或其他日期，不改业务代码、sensor 开关／游标、队列、名单、单位或公式，不请求 Tushare。

当前代码核对了 `jobs/index_daily_update.py`、`jobs/silver_index_daily_update.py`、`jobs/market_major_indices_daily_update.py`、`jobs/major_index_nineturn_update.py`、`jobs/index_daily_nineturn_prod_core_sync.py` 的原资产及检查选择，以及原配置 builder、九转来源 planner 和发布 sensor。各步的实现位置、候选校验、原子替换和发布事务沿第 12.2–12.3 节；D5 只替换 `core_serving.index_nineturn_daily` 的 20 日记录并读回，不修改 Prod 指数日线源表。

每步先查询同日同 job：已排队／运行则跟踪，已成功且原检查绑定本次物化并通过则复用；没有任务才按依赖顺序人工提交原 job。正式入口仍是 `/Users/congming/.goldenshare/dagster_home` 对应的 `http://127.0.0.1:3000/graphql`、`orchestrator/__repository__`，工作目录仍为本工程 orchestrator。沿第 12.2 节原 `launchRun` 请求，分区统一改为 `2026-11-20`；D1 使用现有 `build_raw_index_daily_update_job_run_config(partition_key="2026-11-20", write_mode="replace")`，D2—D5 配置为 `{}`，保留完整原 job selection。人工请求及响应只存 `/private/tmp/dg-index-recovery-20261120-20261121/<原job名>.launch.json` 和 `<原job名>.launch-response.json`，用既有 curl 提交命令，只改变该路径；不得本地执行 writer、补报事件或触发 sensor evaluation。提交前再次排除已有运行，D5 优先复用原成功运行触发的发布任务。

本批成本按五个尚未完成的原 job 各一次及 12 项原检查计算；D1 只读 20 日登记集合的原 11 列，D2 只读本日 Raw，D3 只读本日 Silver 及原有效名单。D4 使用原常量规定的最近 20 份主要指数日线 Gold 和前日九转承接文件；提交前仅 stat 确认这些来源及其压缩大小，不人工读取历史明细。D5 读取本日两份 Gold 并承担一次本日事务及原读回。最终只对四份本日 Lake 文件做一次代码／日期计数及 stat，核对精确运行的终态、12 项原检查与物化绑定，并以本日有界计数确认发布覆盖；不运行 checks-only、不重跑完整目录审计或全历史计算。压缩大小及耗时执行后记录，不能事先作为实际 IO 或耗时保证。

失败／中断停止后续人工提交，保留已完成文件、原生事件和业务 staging；需要人工续跑时，先核对该步原 run、文件／receipt 与来源，只承担未完成步骤同样的来源、候选及原检查成本，不重做成功步骤。验收依据仍是五步成功、对应原检查通过并绑定目标物化，以及本日 Raw／Silver 820 码、主要指数与九转／发布 11 码各一行；实际集合以原登记和有效名单为准。结果回写本节，原缺口证据保持不变。

### 14.1 执行结果与有界验收（21 日 01:10 北京时间）

五步均成功，12 项原检查均通过并绑定本次目标资产、物化及运行。Raw 与九转 Prod 发布由原 sensor 自动提交；中间三步在排除已有运行后人工经原队列提交，没有重复执行。

| 数据集 | 本次原运行 | 开始—结束（北京时间，21 日） | 本日行数 | 原检查数 |
| --- | --- | --- | ---: | ---: |
| Raw 指数日线 | `a2cd0437-870d-4088-a1bb-f16dc6054982` | 01:04:41—01:04:47 | 820 | 2 |
| Silver 指数日线 | `c3077184-64a3-4b41-b0ab-8aff46f80e2b` | 01:05:07—01:05:12 | 820 | 4 |
| 主要指数日线 Gold | `33f27590-ead0-4aec-b4c4-7d75de031754` | 01:05:53—01:05:59 | 11 | 4 |
| 主要指数日线九转 Gold | `269ec7cb-4832-45a9-9145-eaabceea8503` | 01:06:39—01:06:44 | 11 | 1 |
| 指数日线九转 Prod 发布 | `283b8e32-3515-4f52-9c2f-b6c5d45ca836` | 01:07:04—01:07:10 | 11 | 1 |

最终实际文件核对确认四份本日 Lake 文件分别覆盖 820、820、11、11 个代码，代码／日期键数量与行数一致，均只有目标日，读取前后 stat 稳定；Raw 文件内日期为 `20261120` 字符串。四份文件压缩大小分别为 63,428、63,418、2,627、1,325 字节。Prod 原事务及关联检查读回 11 行，另经规定只读入口按 20 日计数，确认正式 `core_serving.index_nineturn_daily` 为名单十一码各一行。发布物化内容摘要为 `1658749b98f31142237e60e6cca33311114fab11ffa8163850bc72d65d63496a`，未额外导出价格或九转明细。

九转原任务报告 21 份来源；19 份前日行情（10 月 26 日至 11 月 19 日）压缩大小 49,902 字节，加本日 2,627 字节及前日九转承接文件 1,211 字节，共 53,740 字节。该数是来源文件压缩大小，不是实际 IO、计算行数或耗时保证，未人工重读历史行情。周月线接续结果见周期原方案 §11.21。

临时验收脚本先因未安装的可选文件库退出，未发生数据读取；改用现有 DuckDB 后，默认目录分区推断覆盖了 Raw 文件内日期，导致脚本错误地判类型不符。已对照原 writer 的 `hive_partitioning=False` 读取规则纠正，正式数据和任务不受影响。实际多发生一次本日 Raw 的代码／日期计数，其余最终物理投影各一次；未安装依赖、重跑正式任务、增加原检查或扩展审计。最终原生运行、检查、物理结果及来源 stat 合并保存在 `/private/tmp/dg-index-recovery-20261120-20261121/acceptance.json`。本批没有任务失败或中断续跑，未改业务代码或服务配置，未重启服务、启停 sensor 或提交 Git。
