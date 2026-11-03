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
