# 普通指数与股票分钟线Raw/Silver安全写入方案与LLD

整理日期：2026-11-02。本文按当前工作区源码说明已有设计；共用模块和股票接入已在Git中，普通指数接入仍有未提交改动。本轮仅整理并提交本文与[指数日线写入方案](dagster-index-daily-staging-write-plan-and-low-level-design.md)，不提交代码，不据此宣称代码已部署。

保留原文件路径及既有章节链接。原文22日“剩65项”、Prod零行、日期识别待确认等是历史阶段，不再作为执行指令；结果见[22日恢复说明](../../reports/datasets_recovery_20261022_20261024/README.md)和[30日收尾](../../reports/datasets_recovery_20261030_20261031/README.md)。已清理过程附件不重新生成。

## 1. 目标、范围与实现

由原业务writer生成指定日、指定频率的候选，校验后逐文件替换，保留失败现场及继续依据。只适用于`defs/io/minute_partition_writer.py::MinutePartitionPublication`的四个对象；下文`defs/`均指`lake_console/orchestrator/src/orchestrator/defs/`。

| 对象 | 频率（分钟） | 公共writer |
| --- | --- | --- |
| 普通指数Prod Raw | 1、5、15、30、60 | `assets/index_mins.py::write_raw_index_mins_partition_from_prod_db` |
| 普通指数Silver | 1、5、15、30、60、90、120 | `assets/index_mins_silver.py::write_silver_index_mins_partition` |
| 股票Prod Raw | 1、5、15、30、60 | `assets/stk_mins.py::write_raw_stk_mins_partition_from_prod_db`及原低层writer |
| 股票Silver | 1、5、15、30、60 | `assets/stk_mins.py::write_silver_stk_mins_partition` |

不扩展到股票Tushare Raw、`merge_repair`、Gold、QFQ/MACD、历史repair或其他对象。原源请求、对象集合、派生窗口、价格/量额校准、停牌/身份规则、冻结行和正式schema/checks继续由原业务实现负责。

完整业务依据见[普通指数方案](dagster-index-mins-data-onboarding-plan.md)、[原LLD](dagster-index-mins-data-onboarding-low-level-design.md)、[股票分钟设计](dagster-stk-mins-asset-design.html)、[Prod导出方案](dagster-stk-mins-prod-db-raw-extraction-hardening-plan.html)及[股票完成门禁LLD](dagster-stk-mins-prod-task-run-readiness-low-level-design.md)。

## 2. 已有文件、替换模式与返回值

| 入口 | 当前行为 |
| --- | --- |
| 普通指数Raw/Silver | 目标已存在且没有本次receipt时交回原builder核验/复用；不增加股票式`replace_existing`选项。无目标或有本次继续记录时走提交模块 |
| 股票Prod Raw | 公共writer的`overwrite=False`默认复用既有合格文件；原Raw job显式`replace_existing`才传`overwrite=True`。该模式仅支持Prod，仍要求真实完成reference，默认builder不变 |
| 股票Silver | 原job默认`write_new`，公共writer默认`overwrite=False`，目标存在且无本次receipt时拒绝覆盖；`reuse_existing`按原入口只读复核，显式`replace_existing`走原转换并传`overwrite=True` |

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
