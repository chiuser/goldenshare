# 指数日线Raw、Silver及主要指数Gold安全写入方案与LLD

整理日期：2026-11-02。本文按当前工作区源码说明已有设计；相关指数实现仍有未提交内容，本文入Git不代表代码已一并提交或部署。本轮仅整理并提交本文与[分钟线写入方案](dagster-minute-raw-silver-staging-write-plan-and-low-level-design.md)，不修改代码、配置、正式数据或运行状态。

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
