# DG 指数周线、月线数据集接入方案与低层设计 v1

状态：**F 已完成启用，尚未全部验收，见 §11.18。管理员确认后，已通过原队列人工接续 2026-11-18 的周／月 Silver，两个当前分区十一代码均截至 18 日；四 sensor 已为 RUNNING，首个真实自然 tick 均因凌晨不在窗口而正确跳过，未提交业务任务。自动日更待 19 日晚间真实链路，周／月正式自动覆盖分别待实际发布，不能预填通过。E 已随 `6564bfaa2` 提交并验收；本轮只改原方案和现有拓扑说明，未改源码、单位或调度窗口，F 启用及审计记录随本次提交归档。**

更新日期：2026-11-20；§2 的 Prod 审计日期及历史数量保持原记录。

日期：2026-11-17。本文按 [DG 新增数据集模板](../templates/dagster-dataset-onboarding-template.html) 编写，将方案与 LLD 合在一份文件维护。业务口径采用本次讨论中已经确认的决定；分区、job、sensor、check 对应关系以 §3、§6、§7 为准。初稿不分区、联合 Silver job、周月链重新下载日线及重复探测 Tushare 日线的设计均已撤回；日更实际输入为已有 `silver_index_daily`。实现进度只以 §11 的阶段记录为准，未完成阶段仍是设计要求。

## 1. 目标、范围与已经确认的决定

2026-11-20 当期触发条件修复：管理员已确认只修复 Silver sensor 在当期日线／日更未完成时提前提交正式覆盖的问题。方案和 LLD 修订已完成；本轮按管理员新指令先提交文档、再修改源码和对应回归用例，不执行验证、不重启或重载 DG。具体范围和进度见 §11.20，不以源码修改表示正式运行已生效。

为 DG 现有的 11 个主要指数接入指数周线 `index_weekly`、指数月线 `index_monthly`，同时保存历史和每天更新的当期 K 线。

| 项目 | 本次口径 |
| --- | --- |
| 对象范围 | 读取 `major_indices.cn_a.csv` 中的 11 个代码；不跟随 Prod 周月线激活池的数量变化，不扩展到全市场指数 |
| Raw 初始化 | 从 Prod `raw_tushare.index_weekly_bar`、`raw_tushare.index_monthly_bar` 读取这 11 个代码的已有记录 |
| Silver 初始化 | 10 个指数直接采用 Prod Serving；科创综指 `000680.SH` 的已结束周期从 Prod Raw 转换，当前未结束周期按日线合成 |
| 历史起点 | 有 Prod Serving 的沿用其历史标准；没有的按指数发布日期所在周期开始。发布日期不是基日，也不是 DG 日线 seed 的历史起点 |
| 分区与文件 | Dagster 按周、月分区管理状态和重跑范围；Raw／Silver 各按频率保存一份完整历史文件，共四份，不按分区另建文件 |
| 后续来源 | 当期合成读取 DG `silver_index_daily`；正式周／月线由通用下载组件从 Tushare 取得，写 Raw 后覆盖 Silver 原周期。不另行下载日线 |
| 北证 50 | 已有历史直接使用 Prod Serving；日更继续用日线合成。周、月线源为空时不制造 Raw 记录 |
| Silver 单位 | 手、千元、百分数。进入 Silver 时转换一次，供下游直接使用 |
| 日更门禁 | 当天 DG 指数日线 Silver 成功写入、已有 blocking checks 通过，且当天文件包含目标 11 个指数后，周／月 sensor 才触发各自 job；不再探测 Tushare 日线 |
| 运行窗口 | 上海时间交易日 19:00 至次日 00:00 前；sensor 最小检查间隔 600 秒，与现有 DG 指数 sensor 一致 |
| 任务执行 | 沿用正式 DG 全局一次只运行一个队列任务的现有设置；四个更新 job 及人工重跑经正式队列启动，不增加本数据集专用 pool。bootstrap 按原维护流程单批执行 |
| 缺数与中断 | DG 日线未成功或缺目标指数时 sensor 等待；已触发 job 后周期日线缺失、计算失败或中断均失败，由运营先补齐 DG 日线，再人工重跑周／月任务 |
| 历史审计 | 复用 §2 已完成的 Prod 审计。不再按全历史重算行情、反复比对源站，或审查已接受历史记录是否属于正式接口原值 |

本次不接财势乾坤周、月线 API、图表和指标；不改 Prod；不改 DG 指数日线的对象范围、历史起点和摄取来源；不增加 Gold、readiness 资产、汇总资产、状态表或自动补数流程。

## 2. 直接采用的审计证据

### 2.1 11 个指数的历史起点与完整性

以下是 **2026-11-17 已完成审计的记录**，不是本次编写方案重新查询的结果。周线已结束周期截至 `2026-11-13`，月线截至 `2026-10-30`；“实有／应有”按当时交易日历与上述起点核验。数量用于证明初始化来源已经齐备，不作为未来执行时固定不变的行数限制。

| 指数 | 代码 | 发布日期 | 首根周线截至日 | 已结束周线：实有／应有 | 首根月线截至日 | 已结束月线：实有／应有 | DG Silver 历史来源 |
| --- | --- | --- | --- | ---: | --- | ---: | --- |
| 上证指数 | `000001.SH` | 1991-07-15 | 1991-07-19 | 1793／1793 | 1991-07-31 | 424／424 | Prod Serving |
| 深证成指 | `399001.SZ` | 1995-01-23 | 1995-01-27 | 1610／1610 | 1995-01-27 | 382／382 | Prod Serving |
| 创业板指 | `399006.SZ` | 2010-06-01 | 2010-06-04 | 843／843 | 2010-06-30 | 197／197 | Prod Serving |
| 科创 50 | `000688.SH` | 2020-07-23 | 2020-07-24 | 324／324 | 2020-07-31 | 76／76 | Prod Serving |
| 沪深 300 | `000300.SH` | 2005-04-08 | 2005-04-08 | 1102／1102 | 2005-04-29 | 259／259 | Prod Serving |
| 中证 500 | `000905.SH` | 2007-01-15 | 2007-01-19 | 1014／1014 | 2007-01-31 | 238／238 | Prod Serving |
| 中证 1000 | `000852.SH` | 2014-10-17 | 2014-10-17 | 619／619 | 2014-10-31 | 145／145 | Prod Serving |
| 北证 50 | `899050.BJ` | 2022-11-21 | 2022-11-25 | 204／204 | 2022-11-30 | 48／48 | Prod Serving，日线合成历史 |
| 中证 A500 | `000510.SH` | 2024-09-23 | 2024-09-27 | 111／111 | 2024-09-30 | 26／26 | Prod Serving，包含已接受修复 |
| 上证 50 | `000016.SH` | 2004-01-02 | 2004-01-02 | 1165／1165 | 2004-01-30 | 274／274 | Prod Serving |
| 科创综指 | `000680.SH` | 2025-01-20 | 2025-01-24 | 94／94 | 2025-01-27 | 22／22 | Prod Raw 转换 |

10 个指数的 Serving 已结束周期无缺期、重复周期、错误期末或错误周期起点，所查必要业务字段无 NULL。科创综指在 **2026-11-17 18:55:09 上海时间**的补齐后审计中，Raw 周线 94／94、月线 22／22，上述缺失、重复、日期错误与必要业务字段空值均为 0；对应 Serving 仍为 0 行，不要求管理员扩大 Prod Serving 池。

科创综指原缺的 `2026-07-03`、`2026-07-24`、`2026-07-31`、`2026-08-07` 四根周线已补齐，九个数值字段均与此前取得的 Tushare 样本一致。**该问题已经解决，不列为实施前重复审计任务。**

Raw 与 Silver 的完整性含义不同：北证 50 两张 Raw 均为空；中证 A500 Raw 历史周线有 7 个已知缺期，另有发布前 `2024-09-20` 一行。初始化 Raw 如实复制已有记录，不要求 Raw 与 Silver 历史行数相等，不为这些已由 Serving 覆盖的历史另行补数。

按表中数量相加，11 个指数已结束周期共有周线 **8879** 行、月线 **2091** 行。以先前 Serving 当期截至 `2026-11-16` 的状态为例，补入科创综指当期两根后分别为 8890、2102 行，合计 **10992** 行。这是文件组织的规模依据，不是 bootstrap 将来必须复现的固定快照。

### 2.2 日线合成、覆盖与单位证据

当前 Prod 实现依据为 `src/foundation/ingestion/index_period_serving.py` 的 `load_index_serving_inputs`、`update_index_serving_bar` 以及周期 upsert；自动期末覆盖调用位于 `src/ops/runtime/worker.py`。已读代码确认：期末 Raw 优先；否则使用截至目标日的日线合成；当期接续检查上一交易日；已结束周期可按完整窗口人工重算；同一代码、同一周期覆盖，禁止将截至日倒退。DG 采用这些业务规则，不跨工程 import Prod 实现。

单位依据不是源文档一句文字：Prod LLD §2.2 已记录 2026-11-10 的源值与日线汇总实测及对应代码；本次 2026-11-17 又已取得 11 个指数、5 个周交易日和 17 个月交易日的 242 条日线及 20 条可得周、月线样本，成交量比值为 100、成交额比值为 1000，涨跌幅为四位小数比例。北证 50 对应周期接口为空。源文档标注手、千元与实际周、月线返回值存在差异，Raw 沿用源值，Silver 依已确认单位转换。

Prod 将日线合成量额乘 100、1000，是为了与周、月线接口返回值和 Serving 既有股、元口径一致。DG 的下游日线使用手、千元、百分数，因此 DG Silver 统一到日线口径；这是本次已经拍板的决定，不再把单位列为待选项。已接受历史行情不因单位转换而重算 OHLC 或涨跌幅。

### 2.3 历史源请求证据：不再用于本方案周月线日更

已使用 DG 当前 `TushareResource` 请求：

```text
api=index_daily
params={trade_date: 20261116, limit: 10000, offset: 0}
fields=(ts_code, trade_date)
不传 ts_code，也不传 start_date/end_date
```

返回 9340 行，目标 11 个代码全部存在，没有代码日期重复或其他日期；该次请求耗时 0.647 秒。另一次目标日期 `20261117` 当时返回 0 行，耗时 0.036 秒。这些只证明参数可用和对应时点的返回，不推断以后每日发布时刻，也不把样本耗时写成保证。源文档对代码必填的说明与实测不符，该差异作为历史证据保留。**管理员现已明确日更复用 DG Silver：本方案不再使用此请求作周月线日更门禁，也不重复请求确认。** 日线自身既有摄取／探测流程不在本次改动范围。

审计原始记录位于本次审计的临时工作目录 `dg-index-period-deep-audit-20261117` 和 `dg-index-000680-postfill-audit-20261117`。本节已保存实施所需结论、范围、日期与数量；将来不以临时目录仍然存在作为开发前提。

### 2.4 DG 日线与通用下载组件的当前代码依据

当前 `defs/assets/index_daily.py:silver_index_daily` 从同交易日 Raw 生成标准事实；正式 job 为 `silver_index_daily_update_job`，selection 包含日线资产和它已有的四个 blocking checks。输入文件通过现有 `silver_index_daily_path` 定位：`/Volumes/datasource/data_lake/silver/index_daily/trade_date=YYYY-MM-DD/part-000.parquet`。实际 schema 是代码、DATE 类型交易日、DOUBLE 类型 OHLC／前收盘／`change_amount`／涨跌幅／量额；量额与涨跌幅已是手、千元、百分数。读取本次窗口只投影必要列并过滤 11 个代码，不下载源日线、不读 Prod 日线。

既有日线四个 blocking checks 为 `silver_index_daily_contract_check`、`silver_index_daily_key_integrity_check`、`silver_index_daily_value_domain_check`、`silver_index_daily_registered_code_coverage_check`。它们当前没有显式 `partitions_def`；本次只消费其与当天物化关联的原生结果，不顺带迁移、改名或重跑这些 checks。门禁查询方式见 §7.2，不能假设旧 check evaluation 已有日期 partition。

通用下载入口已实现于 `orchestrator.tushare_download.TushareDownloader`，提供 `DownloadTask`、`BY_OBJECT_POINT` 和完整 unit 交付。A 阶段审计时注册表尚无 `index_weekly/index_monthly`；B 阶段已只为这两项登记完整源契约和 HTTP binding，未登记 `index_daily`。组件现成的配置、请求生成、分页、源数值解析、标准错误和资源关闭直接复用，没有另写下载器或迁移既有日线链。组件真实源接入验收仍留到 E。

## 3. 数据集、资产、分区与文件

### 3.1 最终名称与 Catalog 草案

| dataset_id／中文名 | Asset key | 层级／来源 | 定义中的字段契约 | 必要 blocking check |
| --- | --- | --- | --- | --- |
| `index_weekly`／指数周线行情 | `raw_index_weekly` | Raw／Tushare；bootstrap 为 Prod Raw | `index_weekly_raw_v1`，完整 11 列源业务字段 | `raw_index_weekly_file_contract_check` |
| `index_monthly`／指数月线行情 | `raw_index_monthly` | Raw／Tushare；bootstrap 为 Prod Raw | `index_monthly_raw_v1`，完整 11 列源业务字段 | `raw_index_monthly_file_contract_check` |
| `index_weekly`／指数周线行情 | `silver_index_weekly` | Silver／周线 Raw 与 DG 指数日线 Silver；bootstrap 采用 §1 来源 | `index_weekly_silver_v1`，12 列标准字段 | `silver_index_weekly_file_contract_check` |
| `index_monthly`／指数月线行情 | `silver_index_monthly` | Silver／月线 Raw 与 DG 指数日线 Silver；bootstrap 采用 §1 来源 | `index_monthly_silver_v1`，12 列标准字段 | `silver_index_monthly_file_contract_check` |

四个资产统一 `group_name=index`，`DataDomain.INDEX_TOPIC`，按层使用 `build_asset_tags`。Raw 的 `SourceSystem.TUSHARE`、`DataContractSource.TUSHARE_RAW_CONTRACT` 表达源业务身份；Silver 使用 `SourceSystem.DERIVED`、`DataContractSource.DERIVED_CONTRACT`。Prod 只读初始化在 `bootstrap_sources` 和本次 materialization metadata 中声明，不伪装成日常依赖。

`lake_assets.py` 分别登记四个 entry：中文名、source_api、source_doc、完整 column_schema、路径、partition_model、blocking_check_names、ingestion_sources、bootstrap_sources、write_policy、event_policy、performance_contract。日常 Raw 只允许 Tushare，Silver 从本节声明的输入计算；Prod 资源仅用于 bootstrap。

### 3.2 Dagster 按周、月分区，物理文件保存完整历史

Dagster 分区表示本次处理哪一周／月，以及该周期的物化、check 和重跑状态；文件组织表示数据实际保存在哪里。两者分别定义：**四个资产都有周期分区，但正式文件仍只有四份。** 分区状态必须与物化、check 事件中的真实 partition 一致，不能只在 metadata 写一个日期代替。

| 频率 | `partitions_def`（新增、指数专用） | `partition_key` | 该分区包括什么 |
| --- | --- | --- | --- |
| 周线 | `cn_a_index_week_ends = DynamicPartitionsDefinition(name="cn_a_index_week_ends")` | 该自然周的最后交易日，`YYYY-MM-DD` | 该周各应有指数的 K 线；周线 Raw 与 Silver 使用同一个分区定义 |
| 月线 | `cn_a_index_months = DynamicPartitionsDefinition(name="cn_a_index_months")` | 自然月，`YYYY-MM` | 该月各应有指数的 K 线；月线 Raw 与 Silver 使用同一个分区定义 |

周按周一至周日划分，月按自然月划分；期末、首个开市日与应有交易日都从 `silver_trade_calendar` 取得。整周无开市日时没有周线业务分区。历史起点按 §2；不同指数在同一分区内按各自已确认起点纳入，不按代码再拆分区。Raw 保留源已有范围，不因 Silver 应有 11 个指数就补空行。

采用动态分区是为了按实际交易日历登记有效周期，避开固定周五休市及整周休市的误判。**登记当期周分区不必等到周末**：日历已覆盖全周时，在周中就能确定该周最后交易日。分区注册只表示周期可以被选择，不代表 Raw 已到数或 Silver 已更新到当天。

历史分区由受控 bootstrap 入口按下载结果批量登记；日常各更新 sensor 只判断本次目标键是否缺失，必要时在 `SensorResult.dynamic_partitions_requests` 中添加，再按源就绪结果提交该分区的 RunRequest。源未齐时允许只登记目标周期并等待，不写行情或成功物化。两层共用的键只登记一次，不另建分区注册 sensor，不修改现有指数交易日／代码分区集合。正式登记与启用均留到 §11 获批阶段。

Catalog 对四条 entry 分别登记 `week_end_partition_raw_index_weekly_full_file`、`month_partition_raw_index_monthly_full_file`、`week_end_partition_silver_index_weekly_full_file`、`month_partition_silver_index_monthly_full_file`。周线使用 `PartitionModelFamily.NATURAL_WEEK_PARTITION`、`dagster_partition_dimension="week_end_date"`；月线使用 `NATURAL_MONTH_PARTITION`、`dagster_partition_dimension="month"`；四者的 `PartitionPhysicalLayout` 都为 `SINGLE_FILE`。不再把文件完整保存误写为无 Dagster 分区。

### 3.3 四份文件与分区记录的对应

| Asset key | 正式文件（唯一正式 Lake 根目录下） | 文件内业务主键 |
| --- | --- | --- |
| `raw_index_weekly` | `/Volumes/datasource/data_lake/raw/index_weekly/full/part-000.parquet` | `ts_code, trade_date` |
| `raw_index_monthly` | `/Volumes/datasource/data_lake/raw/index_monthly/full/part-000.parquet` | `ts_code, trade_date` |
| `silver_index_weekly` | `/Volumes/datasource/data_lake/silver/index_weekly/full/part-000.parquet` | `ts_code, period_start_date` |
| `silver_index_monthly` | `/Volumes/datasource/data_lake/silver/index_monthly/full/part-000.parquet` | `ts_code, period_start_date` |

所有候选位于 `/Volumes/datasource/data_lake_staging/<run_id>/index_period/<layer>/<dataset_id>/part-000.parquet`，使用同文件系统 `os.replace()` 提升。一次 job 只改一个资产的目标分区记录，将其他周期原样合并到候选中，再替换这一个完整文件；不重算历史，不在路径中增加 `week_end_date=...` 或 `month=...` 小文件目录。

Raw 周线按 `trade_date=周分区键` 选取目标记录，Raw 月线按 `trade_date` 所属月份选取。Silver 按 `period_start_date` 所属自然周／月映射到同一分区，`trade_date` 表示该根 K 线实际截至日，不能用它作为每天变化的周分区键。历史晚到只替换目标分区，不能删除其他周期。

示例：若日历确认 2026 年 11 月 16 日至 22 日这一周的最后交易日为 11 月 20 日，则 11 月 17 日 Silver 周线使用 `partition_key=2026-11-20, trade_date=2026-11-17`，月线使用 `partition_key=2026-11, trade_date=2026-11-17`。18 日仍更新这两个分区，实际截至日改为 18 日；期末到数后也覆盖原分区，不新建一个“期末正式行情分区”。

写入策略为 `SINGLE_FILE_ATOMIC_REPLACE`。同一资产不同分区写的是同一文件，任务依 §7.4 复用正式 DG 全局单任务队列，不另设文件级并发限制。日常只记录本次目标分区的物化与 check；bootstrap 四个文件一次生成，按实际有记录的历史分区批量补录物化与 check 结果，不能仅写四次无分区事件冒充历史分区已就绪。四条 Catalog entry 的事件策略为 `DAGSTER_RUN_ONLY`。bootstrap 由每批独立原生运行承载，不新增 bootstrap 资产；人工重跑创建新运行，资产结果数量仍按 §9 的 `2N` 统计，正常运行日志另计。

## 4. 字段、日期与单位

### 4.1 Raw 完整源字段

周、月线都请求完整的 11 个源业务字段，按源顺序：

```text
ts_code, trade_date, close, open, high, low, pre_close,
change, pct_chg, vol, amount
```

| 字段 | Raw Parquet 物理类型 | 含义与写入规则 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 指数代码，只处理本次 11 个代码 |
| `trade_date` | `VARCHAR` | `YYYYMMDD`；Prod DATE 格式化到同一源日期表示 |
| `close, open, high, low, pre_close, change` | `DECIMAL(18,4)` | 保留源数值；`change` 不改名 |
| `pct_chg` | `DECIMAL(10,4)` | 比例；上涨 1% 为 `0.0100` |
| `vol, amount` | `DECIMAL(20,4)` | 股、元；不在 Raw 换算 |

数值类型沿用 Prod 已核实表定义的精度。Raw 不按 Silver 发布日期删除源历史，不补北证 50 空行，不补中证 A500 既有历史缺口。Prod 的 `api_name/fetched_at/raw_payload`、Serving 的 `source/created_at/updated_at` 是本地辅助列，不纳入 Tushare 源业务字段契约，也不复制进这两张 DG Raw 文件。

### 4.2 Silver 标准字段

列顺序固定为 `ts_code, period_start_date, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount`。

| 字段 | Silver Parquet 物理类型 | 来源／含义 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 指数代码 |
| `period_start_date` | `DATE` | 周一至周日或自然月内的首个开市日，用来定位周期；沿用 Prod Serving 定义，不等同于发布日期 |
| `trade_date` | `DATE` | 当前 K 线实际截至日；已结束周期为最后交易日 |
| `open, high, low, close, pre_close, change_amount` | `DECIMAL(18,4)` | 直接复制／改名，或按 §5 合成 |
| `pct_chg` | `DECIMAL(12,4)` | 百分数；Prod／周期 Raw 比例乘 100。整数位增加 2 位来自该换算 |
| `vol` | `DECIMAL(20,6)` | 手；Prod／周期 Raw 股数除 100，额外 2 位小数来自该换算 |
| `amount` | `DECIMAL(20,7)` | 千元；Prod／周期 Raw 元数除 1000，额外 3 位小数来自该换算 |

保留换算所需小数位是为了不因搬运重新舍入历史量额；不是新增价格精度要求。字段类型为本次新契约，既有指数日线文件不改类型。所有输入均显式投影、转换类型，不用缺列补 NULL、默认值或静默去重使文件通过。

对于 Prod Serving 已存在的十个指数，首根 K 线按其原值与周期起点保存，包括正式首期前收盘／涨跌幅为零以及包含发布前回溯行情的情况。不得改成从发布日日线重新计算。科创综指的第一根周、月线也采用已补齐 Raw 原值；发布日期只控制纳入哪个周期，不裁掉该根源行情的部分交易日。

## 5. 日常更新与覆盖规则

### 5.1 周期 Raw 更新

周线在该周最后交易日盘后运行，月线在次月首个交易日盘后取上月最后交易日。交易日期来自 `silver_trade_calendar`；休市的周五／月底不能直接作为请求日期。

每个频率每次只更新一个实际期末。业务调用现有通用下载组件，创建 `DownloadTask(contract_name="index_weekly"或"index_monthly", mode=BY_OBJECT_POINT, objects=11个代码, points=(实际期末ISO日期,))`；在 `with downloader.download(task)` 中逐个取得完整 unit，业务校验后再合并写入本频率 Raw。一次正常更新为 11 个对象时间点 unit，不传全市场或无界范围。

两份 DG 本地源契约均包含 §4.1 完整 11 字段、源参数规则、日级时间规则及 1000 行分页合同；契约名直接使用接口名，版本独立为 `1`，以现有 `TransportBinding` 固定 HTTP 调用。参数由组件 `RequestBuilder` 生成：内部源请求为 `ts_code=单代码, trade_date=YYYYMMDD, limit=1000, offset=0`。不得把 `YYYY-MM` 月分区键当源日期，不在业务中另拼 fields、limit、offset、token 或地址，不为 11 个指数创建字段子契约。

单代码单期最多一行，正常短页即结束，不额外拉全市场。十个非北证指数应有记录；北证 50 可交付合法空 unit，有返回则照常保存。其他代码缺失或组件异常则本次任务失败，人工处理后重跑，不将部分下载提升为正式文件。组件原有网络错误有限重试直接复用，不另建本数据集的重试、断点恢复或下载进程；取消、进程中断及重试耗尽均按失败／中断上报。

新期末记录按 Raw 主键替换同键旧值，其余历史保留。写入成功的 materialization 记录频率、期末及 `upstream_batch_id`，供 Silver sensor 识别一次新的 Raw 更新。批次标识使用现有 `build_batch_id`，包含生产 run 标识及频率、期末，不用 PG event storage id。

### 5.2 每个交易日更新当前周线、月线

目标为交易日 `T`。周、月线由各自的 Silver job 更新，均显式指定 §3.2 的对应分区；每次只写本频率完整历史文件。先判断各代码是否已有该周期期末 Raw：

1. 有期末 Raw：换算单位后优先使用，正式首期零值不因合成规则被拒绝。
2. 没有期末 Raw：读取从本周期首个应有交易日到 `T` 的 DG `silver_index_daily` 文件，按完整窗口合成。当期第一天可直接开始；其他交易日要求已有周／月 Silver 截至上一应有交易日或已经截至 `T`，否则失败。
3. 日线读取范围由交易日历生成，使用现有路径函数定位必要日期文件，通过一次本频率 DuckDB 查询读取需要合成的代码。仅投影 `ts_code,trade_date,open,high,low,close,pre_close,vol,amount`；日线 `change_amount/pct_chg` 不用于相加得到周期涨跌幅。无 Tushare 日线请求、Prod 日线查询、新日线资产或下载缓存。
4. DG 日线输入必须包含该代码所需窗口全部应有交易日，必要字段可计算；缺文件、缺日、缺值、重复冲突或首日前收盘为零，直接失败，不回退下载日线。运营先通过既有 DG 日线入口补齐，再人工重跑本次周／月任务。
5. 完成本次输入和本资产的一份候选后提升。某次 job 失败后 sensor 不自动追补或换日期重试，由人工补数据后重跑原分区和目标日；另一频率已成功的结果保留，不因它们在同一天更新就一并回滚或重算。

日线合成窗口从 `max(周期首个开市日, 指数发布日期)` 起；当前 11 个指数都已发布。发布日期取指数基础信息的 `list_date`，不得借用 `major_indices.cn_a.csv` 的日线历史起点。

周窗口最多 7 个自然日，月窗口最多 31 天，只读取其中的应有开市日文件。DG 日线字段实际为 DOUBLE，读取后显式适配到本次已定义的价格 `DECIMAL(18,4)`、量额 `DECIMAL(20,4)` 再按 Prod 公式聚合，不修改既有日线 schema 或数据。单位已经是手、千元，不重复转换；周期涨跌幅仍根据首日前收盘和末日收盘计算，不累加日线涨跌幅。

| Silver 字段 | 日线合成规则 |
| --- | --- |
| `open / high / low / close` | 首日开盘／窗口最高／窗口最低／末日收盘 |
| `pre_close` | 窗口首日的前收盘，不取上根周线或月线的收盘代替 |
| `change_amount` | 末日收盘减首日前收盘 |
| `pct_chg` | 先将 `末日收盘 / 首日前收盘 - 1` 按 Prod 的 `ROUND_HALF_UP` 保留四位小数，再乘 100，保持与 bootstrap 精度一致 |
| `vol / amount` | 日线成交量／成交额分别求和；日线已经是手／千元，不再乘除 100／1000 |

日线计算通过 DuckDB SQL 完成；对正负中点的舍入使用独立金样本验证与 Prod 一致，不根据函数名字推断相同。没有接口值与日线结果每日重复对账或重新计算历史指标的 check。

### 5.3 期末数据覆盖与人工补齐

Raw 周／月线成功更新后，对应 Silver sensor 在下述触发条件满足后另提交同一个周／月分区的更新，配置只传 `mode=period`，原期末从所选分区和交易日历推导，不另传 `trade_date`，与 §7.5 一致。若该 Raw 属于当天所在周／月，必须先等当天 DG 指数日线 Silver 运行成功、原四项检查通过且十一代码齐备，优先执行既有 `mode=daily` 日更；该周期 Silver 成功物化、关联检查通过并截至当天后，才允许后续 tick 提交当期正式覆盖。日线未就绪或当期日更尚未完成时，即使 Raw 已成功也只等待，不将该 Raw 批次标为已处理。旧周期正式覆盖继续按原目标周期的 Raw 及完整合成记录处理，不增加执行当天的日线依赖。

覆盖目标按 `ts_code, period_start_date` 定位，不能将历史期末替换成触发当天，也不能只看该分区当天已物化就跳过新 Raw 覆盖。北证 50 没有新 Raw 时保留已经结束且完整的合成 K 线，不为本次覆盖再次读取和计算它的全周期日线。现有 writer 的完整性判断保持不变：人工直接提交或旧周期确实缺少完整合成记录时，仍失败并交人工；本次只阻止 sensor 在已知当期日更未完成时提前提交任务。

有期末 Raw 时优先写其值；没有新 Raw 时不能用较早日线结果覆盖较晚截至日。人工使用 `mode=repair` 补齐明确指定的已结束周期时，只从 DG 日线 Silver 读取所需完整窗口，不要求事先存在上一交易日的周／月 Silver，已有完整记录直接保留。DG 日线历史不足时先由运营补齐上游，本链不自动请求 Tushare／Prod 日线。当日漏跑造成接续失败时，人工先补缺失目标日，或选择已结束周期补齐；sensor 不提交 repair，也不自动领取历史缺口。

## 6. Checks：四个资产各一个，不另设重复检查任务

| Check 名称 | 绑定的资产 | 显式 `partitions_def` | blocking／作用域 |
| --- | --- | --- | --- |
| `raw_index_weekly_file_contract_check` | `raw_index_weekly` | `cn_a_index_week_ends` | 是／`CheckScope.SCHEMA` |
| `raw_index_monthly_file_contract_check` | `raw_index_monthly` | `cn_a_index_months` | 是／`CheckScope.SCHEMA` |
| `silver_index_weekly_file_contract_check` | `silver_index_weekly` | `cn_a_index_week_ends` | 是／`CheckScope.SCHEMA` |
| `silver_index_monthly_file_contract_check` | `silver_index_monthly` | `cn_a_index_months` | 是／`CheckScope.SCHEMA` |

四个 check 名称不变，定义时绑定对应资产对象，并在 `AssetCheckSpec` 中显式传入与资产相同的分区定义。一个 check 的属性是“本次分区写入符合保存契约”：完整文件可读且物理列／类型正确；本次输入、变更行与候选分配数量一致；目标分区的新键非空且唯一、代码／周期／实际截至日正确。检查日期归属只针对本次目标分区，不能要求完整文件中的所有历史行都属于本次分区。

metadata 列出具体失败规则和样本，物化与 check evaluation 归属本次 RunRequest 的相同 partition。当前分区已经在上一交易日通过，也不能充当今天执行的 check 结果；读取状态时关联本次物化及其实际截至日。无 WARN check、独立 freshness check、价格波动 check、全历史连续性 check 或公式重算 check。日线齐全与接续是 §5 已要求的计算输入合同，失败即停止本次更新，不增加同义资产或第二组 PG 检查事件。

文件候选的传输、schema、键与日期规则和正式 check 共用一个纯 helper。在写入同一次过程中取得检查结果，提升后使用 `AssetCheckSpec` 与 `MaterializeResult.check_results` 绑定正式资产发出；不另起 check job，再读、再算一次。失败时记录失败规则并使 run 失败，不发成功物化。候选 validator 仅处理原子提升完整性，不新增行情价格范围、涨跌幅阈值等业务 guard。

初始化仅核对本次复制的字段、数量及目标文件；历史起点和连续性直接使用 §2，不重算源历史。四份候选各一次集合式处理，同时产生各历史分区的传输／键／日期统计，供事件补录复用；不能为每个分区重新打开完整文件做同一套校验。日常只检验本次新生成记录与传输结果；未改变历史通过按键替换的 SQL 原样保留，不再次逐条审计。行数、schema 可复用同次写入统计及 Parquet footer，不扫描历史行情做第二套检查。

运行 metadata 统一使用现有 `build_materialization_metadata`／`build_check_metadata`，项目字段加 `goldenshare/` 前缀。`dagster/row_count` 记录本次分区行数，`goldenshare/file_row_count` 单独记录完整文件行数；另保存 partition key、实际截至日、频率、源行数、变更行数、文件 URI、失败规则数量及代码／日期样本，不把整份文件行数冒充本次分区行数。代码样本最多为本次 11 个代码，不把行情或全历史日期表写入 PG。

DG 日线输入只记录资产名、现有路径模板、窗口起止、文件数和目标代码数；成功结果不每天复制整月输入文件路径清单或上游四种检查明细。失败显示缺失日期／代码，完整路径可由模板定位，不新增用于记录日线就绪的 check、asset 或 PG 表。

## 7. Jobs、sensor 与运行配置

### 7.1 四个 job：每个 job 对应一个资产、一个分区集合、一个 check

| Job | 写入资产 | 分区定义／键 | 唯一执行的 check | 中文 description |
| --- | --- | --- | --- | --- |
| `raw_index_weekly_update_job` | `raw_index_weekly` | `cn_a_index_week_ends`／周末实际交易日 | `raw_index_weekly_file_contract_check` | 更新所选周的主要指数原始行情。 |
| `raw_index_monthly_update_job` | `raw_index_monthly` | `cn_a_index_months`／自然月 | `raw_index_monthly_file_contract_check` | 更新所选月份的主要指数原始行情。 |
| `silver_index_weekly_update_job` | `silver_index_weekly` | `cn_a_index_week_ends`／周末实际交易日 | `silver_index_weekly_file_contract_check` | 更新所选周的主要指数行情，支持当期日更和期末覆盖。 |
| `silver_index_monthly_update_job` | `silver_index_monthly` | `cn_a_index_months`／自然月 | `silver_index_monthly_file_contract_check` | 更新所选月份的主要指数行情，支持当期日更和期末覆盖。 |

四个资产分别定义，不保留初稿的 `silver_index_period_update_job` 或把不同分区定义放进同一个 Silver `multi_asset`。各 job selection 只有本资产和本资产 check，不跨层写入。四个物理文件独立，周、月 job 可以分别成功或失败；不能为凑一个联合 run 将两个不同含义的 partition key 混用。job 文件只声明 selection 和中文说明，不存计算或源调用。

Silver 的真实只读依赖为 `silver_index_daily`、同频率 Raw、`silver_trade_calendar`、`silver_index_basic`，代码读取已有 seed。同频率 Raw→Silver 使用相同周期键；日线→周／月的执行窗口由日历和 T 显式生成，不用不同动态分区间的默认映射或“最新已注册键”决定读取范围。资产声明日线 Silver 血缘，但 job 不选择日线、Raw 或基础资产的 writer，不重跑它们的 checks，也不新增 declarative automation 扫描全部历史分区。

**当前周期 Raw 尚未到期、未物化，是 Silver 日更的正常情况。** 日更不能要求当前 Raw 分区已成功才开始；按 §5.2 有期末 Raw 就使用，没有就从日线合成。只有消费新到 Raw 的 `mode=period` 才要求该 Raw 分区本次物化及对应 check 成功。

### 7.2 四个 sensor：各自只触发同名 job

四个 sensor 默认均为 `STOPPED`；启用前完成历史初始化和获批日更验收。

| Sensor | 唯一目标 job | 日常目标分区／触发条件 | 中文 description |
| --- | --- | --- | --- |
| `raw_index_weekly_update_job_sensor` | `raw_index_weekly_update_job` | 当周最后交易日 19:00–00:00，点查上证指数该期周线已发布；`partition_key=本周最后交易日` | 当周行情发布后，触发主要指数周线原始行情更新。 |
| `raw_index_monthly_update_job_sensor` | `raw_index_monthly_update_job` | 次月首个交易日 19:00–00:00，点查上证指数上月实际期末月线已发布；`partition_key=上月 YYYY-MM` | 上月行情发布后，触发主要指数月线原始行情更新。 |
| `silver_index_weekly_update_job_sensor` | `silver_index_weekly_update_job` | 当天 DG 指数日线 Silver 成功并通过已有 checks、11 个目标代码齐备后，以本周分区、`mode=daily, trade_date=T` 更新；当周 Raw 覆盖须等本周日更成功并截至 T，旧周 Raw 覆盖仍按原周条件提交 `mode=period` | DG 指数日线成功后更新当前周，并覆盖新到的期末周线。 |
| `silver_index_monthly_update_job_sensor` | `silver_index_monthly_update_job` | 当天 DG 指数日线 Silver 成功并通过已有 checks、11 个目标代码齐备后，以本月分区、`mode=daily, trade_date=T` 更新；当月 Raw 覆盖须等本月日更成功并截至 T，旧月 Raw 覆盖仍按原月条件提交 `mode=period` | DG 指数日线成功后更新当前月，并覆盖新到的期末月线。 |

四者均 `minimum_interval_seconds=600`、时区 `Asia/Shanghai`，只在交易日 19:00 至次日 00:00 前判断更新。600 秒是既有同类 sensor 间隔，不新增独立轮询配置，不保证日线成功即刻执行。Silver sensor 通过已有事实轮询等待上游成功，不在日线 job 内新增触发代码。每个 sensor 每 tick 最多一个 RunRequest、一个本频率缺失分区键登记；Silver sensor 的 Tushare 请求数为 0，Raw sensor 至多一次正常发布探测。相应 Silver sensor 优先完成当日日更，期末覆盖后续 tick 判断，不丢弃新 Raw 批次。

Raw 发布探测由 `source_readiness/tushare/index_period.py` 复用同一下载组件，以 `BY_OBJECT_POINT` 读取上证指数单代码、单期末的一个完整 unit，只用代码／日期判断是否已发布。组件仍下载完整 11 字段，不另造两列子契约或 SDK／HTTP 客户端；正常最多一行，空 unit 则等待。Raw job 再按 11 个代码下载正式本期数据。探测不写业务文件或恢复缓存。

Silver 日更门禁按以下顺序，只读当天 T 的上游事实：

1. `silver_index_daily` 当天分区已成功物化，生成它的运行成功结束；当前正式入口是 `silver_index_daily_update_job`。仅看到日线 job 被触发、排队或正在执行不算就绪。
2. §2.4 的四个既有 blocking checks 全部通过，并原生关联到这次 T 日线物化。实现按该生产 run 有界读取四种检查结果、核对关联物化；不重复执行 checks。旧日线 check 的 event partition 为空时不能直接用 `partition_filter=T` 查询并永久等待，也不能拿其他日期的绿灯代替。当前通用 `asset_readiness_status` 会逐 check 扫最多 5000 条历史，本门禁不调用这条历史扫描路径；不因此改现有日线检查定义。
3. 读取 T 日线 Silver 文件中的代码、日期两列，过滤目标 11 个代码确认齐备。仅有文件或日线总行数不够；缺目标指数则等待并显示代码摘要，不向 Tushare 补取。完整周期输入的必要校验由 job 在读取实际窗口时完成。

基础日历／指数基础信息仍须成功及原 checks 通过，日历覆盖所需周期。日更依赖日线成功；正式覆盖仍是另一个分支，但不能绕过当期日更：当前 Raw 的原分区与当日日更目标分区相同时，复用本 tick 已取得的当前 Silver 物化、关联 check 及实际截至日，未完成当天日更就等待；不额外执行或重复读取一遍日线检查。原分区是旧周期时，继续依据该 Raw 本次物化及 check，按 §5.3 保留目标周期已完整的合成记录，不因执行当天日线未完成而阻挡。两分支均不执行上游 writer／checks，不深扫历史。新的日更是同一周／月分区再次物化，昨日结果不代表今天完成。

定义分类通过 `build_sensor_tags`：领域 `INDEX_TOPIC`，目标层为对应 `RAW` 或 `SILVER`，职责 `ASSET_UPDATE`。提交通过 `build_run_request`，显式设置正确的 `partition_key`，typed config 经运行合同转换，不拼深层 `ops` 配置。需要登记新键时使用同一次 `SensorResult` 的动态分区请求，不在 helper 内随意写 instance。

cursor 使用 `build_sensor_cursor` v1 结构，仅保存本 tick 决策、目标分区、实际截至日、日线等待／检查失败原因、缺失代码数及有限样本、下一步动作和最近批次提示。沿用典型小于 2KB、复杂阻断小于 3KB、硬上限 8KB 的既有预算；不存行情、整批 check 明细、完整历史键集合或 schema map。

### 7.3 去重、当期刷新与期末覆盖

| 场景 | RunRequest 与去重身份 | 为什么不会漏更新 |
| --- | --- | --- |
| Raw 更新 | 目标 job、`partition_key=P`；`build_asset_update_run_key` 的 subject 为对应 job，unit 为 P | 同一频率同一期末只自动提交一次 |
| Silver 日更 | 目标 job、`partition_key=P`、`mode=daily, trade_date=T`；同类 builder 的 unit 同时包含 P 和 T | 17 日、18 日虽同一周／月，仍是不同日更；不能只拿 P 当 run key，导致整周／月只跑一次 |
| 新 Raw 覆盖 | 对应 Silver job、原 Raw 分区 P、`mode=period`；`build_upstream_triggered_run_key` 使用对应 consumer 与 Raw 的 `upstream_batch_id` | 当期先完成当日日更，等待期间不消费 Raw 批次；完成后仍可另提交正式覆盖。旧周期按原分区独立处理，不被执行当天日线阻挡 |

执行参数来自显式 partition key、typed config、日历和 Raw metadata，不解析 run key。sensor 按本次分区及截至日读取匹配的物化／check 事实，cursor 不作为就绪证据。失败后不自动换 key 重试；运营在同一 job 选择原分区，重跑原模式和目标日，不重跑已经成功的另一频率。

### 7.4 沿用 DG 全局单任务队列

管理员已确认：本数据集复用正式 DG 现有 `QueuedRunCoordinator` 和 `concurrency.runs.max_concurrent_runs=1`，四个更新 job 及人工重跑均通过正式队列启动。1 是当前正式配置，不是本次新增限额，也不是 Dagster 默认值。每个 job 只执行本资产及随写入返回的 check，不在任务内部并行启动多个文件更新；在这条路径下，两个周期更新任务不会同时执行，不需要再增加四个资产专用 pool。

| 正式队列中的 job | 本次更新的文件 |
| --- | --- |
| `raw_index_weekly_update_job` | 指数周线 Raw 完整历史文件 |
| `raw_index_monthly_update_job` | 指数月线 Raw 完整历史文件 |
| `silver_index_weekly_update_job` | 指数周线 Silver 完整历史文件 |
| `silver_index_monthly_update_job` | 指数月线 Silver 完整历史文件 |

本次不修改全局并发数、pool 粒度或 executor，不配置本数据集四个 pool，不增加步骤级限额、锁文件或相关并发压力测试。周线和月线虽然写不同文件，也按当前全局队列顺序执行，不承诺同时运行。sensor 继续在本 job 已排队／运行时等待，避免重复积压；此判断只负责调度去重，任务串行由既有正式队列负责。

人工重跑在正式 Dagster 中选择原 job、原分区、原模式和目标日，经同一队列提交，不另写直接执行四个更新 job 的脚本。bootstrap 保持原受控 CLI 和每批独立原生运行；当前实现使用 `execute_in_process`，不经队列，因此继续遵守已有维护流程：四个 sensor 有效停止、四个更新 job 已结束后单批执行，不同时启动两个初始化批次。失败或中断仍直接失败，由运营按原范围人工重试，不增加恢复机制。

旧 pool 绑定及命名属性已按 §11.12 清理，当前四个资产不再绑定专用 pool；隔离验收及独立复审见 §11.13。没有修改正式队列或其他全局配置。

### 7.5 配置审计与边界

| 配置／输入 | 默认、来源与持久化 | 消费者／作用范围与生效方式 |
| --- | --- | --- |
| 11 个代码 | 现有 `seeds/market/major_indices.cn_a.csv`；不新增对象池配置 | bootstrap、DG 日线门禁和四个 job 读取代码列，不使用日线起点作为周月起点。名单变化另行审阅 |
| 指数发布日期 | `silver_index_basic.list_date`；十个指数历史以 Serving 已有范围优先，科创综指采用 §2 日期 | 首次纳入与确需合成的起点；缺失则失败 |
| 分区定义与键 | `defs/partitions.py` 引用 `run_contracts/index_period.py` 的两个名称；键持久化到正式 Dagster instance | 同频率 Raw、Silver、checks、jobs、sensors、bootstrap 共用相同定义；不复用股票或指数日线的键集合 |
| Raw 时间输入 | 只有 RunRequest／人工选择的 partition key；不再额外输入 `period_end_date` | 周直接取键日期，月从键及日历确定期末；不开放无界时间范围或重复日期输入 |
| Silver `trade_date` | `mode=daily` 必填，ISO 日期，存 run config；`period/repair` 从所选分区和日历确定期末，不另填 | 实际截至日必须属于所选周／月，不以分区末日冒充周中当日，也不以执行当天替代旧期末 |
| Silver `mode` | typed enum：`daily`、`period`、`repair`，无隐式默认 | 当期日更／消费新期末 Raw／人工补齐指定已结束周期；sensor 不提交 repair。频率由目标 job 固定 |
| bootstrap 来源 | 受控入口固定为 §1 来源，无旧湖或全市场开关 | bootstrap helper；不进入日常 run config |
| 19:00–00:00、600 秒 | `run_contracts/index_period.py` 集中声明，四个 sensor 消费，定义重新加载后生效 | 本次已确认决定，不加 env 或 PG 配置表，不修改现有 sensor |
| 正式 DG 全局单任务队列 | 现有 `/Users/congming/.goldenshare/dagster_home/dagster.yaml`：`QueuedRunCoordinator`、`concurrency.runs.max_concurrent_runs=1`；本接入不修改该文件或全局执行设置 | 全部正式队列任务共同使用；本次四个更新 job 及人工重跑使用同一队列，运行及排队状态可在 Dagster 查看。复用现有服务配置及生效方式，不新增本数据集配置；bootstrap 的单独维护流程见 §7.4 |
| DG 日线输入 | 固定依赖 `silver_index_daily` 和现有 `silver_index_daily_path`，没有可选下载来源开关 | 两个 Silver job、两个 Silver sensor、bootstrap 当前期及人工 repair；读取所需日期／11 个代码，缺失报错，不退回 Tushare／Prod 日线 |
| 周／月源下载 | DG 本地 `index_weekly`、`index_monthly` 完整契约 version=1；对应 `CONTRACTS/BINDINGS` 固定 HTTP、`BY_OBJECT_POINT` | 两个 Raw job 和单点发布探测；新增契约在定义加载后生效，不改变通用下载组件公开 API、全局策略或现有数据集登记 |
| Tushare 连接 | 由 `TushareDownloader.load()` 的现有 `ConfigurationLoader` 读取 `TUSHARE_TOKEN` 与 `TUSHARE_BASE_URL`；默认地址沿用组件定义，修改环境后新实例生效 | 仅正式周／月下载和发布探测；不从 asset 传 token／地址／fields／limit／offset，不在 Silver 日更创建下载器；未在文档或日志写凭据 |
| Prod／Lake／DuckDB 连接设置 | 复用现有 Resources，不新增主机、内存或线程设置 | 本次周月模块只在 bootstrap 连 Prod 周／月表；路径与查询复用现有 helper。DG 日线自身现有 Prod 来源保持不变，不宣称本次已将它迁移到 Tushare 直采 |

源字段、单期行数与分页参数是源合同，不作为运营自由输入。配置测试覆盖分区与实际截至日不符、期末模式额外日期输入、非法模式／旧湖来源和默认 STOPPED；执行前复用已确认的全局队列配置，确认实际更新入口经队列提交，不增加 pool 设置／读回要求或用户侧开关。

## 8. Bootstrap、失败与人工重试

### 8.1 一次初始化流程

1. 在四个新 sensor 停止、四个 job 均已结束的条件下，受控 bootstrap 入口使用现有 Prod 只读事务。两次查询投影 Raw 完整 11 列、限定 11 个代码；两次查询投影 Serving 标准 12 列、限定十个已有指数。不读取全市场指数，不读无关辅助载荷。
2. Raw 原样初始化；Silver 十个指数仅做字段／日期／单位转换。科创综指从这次已下载的 Raw 构造已结束周期，利用现有交易日历确定周期起点，不重新请求 Tushare 历史周月线或重算已经完整的 Raw。
3. 当期十个指数沿用导出 Serving 实际截至日，各频率当前记录须有一致截至日。科创综指从 DG 指数日线 Silver 读取至对应截至日的必要窗口，可共用已加载关系完成周月合成，不请求 Tushare 日线。Serving 截至日领先于 DG 日线时，先等待／完成既有 DG 日线任务再重试，不删除较晚 Serving 或绕过上游补取。源快照不一致则失败，人工择时重试，不硬套 11 月 16 日审计快照。
4. 用同一套正式 writer 和 file_contract helper 产生四个候选，在同次集合式处理内按业务周期分组，取得实际分区集合、分区行数及文件契约结果，完成本次复制／传输核对后逐文件提升。历史连续性沿用 §2；不把每个周期重新算一次或每个分区重读文件。最终仍只有四份正式完整文件。
5. 在同一个获批 Dagster instance 批量登记两个频率的有效分区键；同频率两层取键的并集，已登记的键不重复新增。随后针对各资产**实际有记录的分区**补录带 partition 的物化和对应通过 check，metadata 记录来源、分区行数、完整文件行数、实际截至日及单位转换。北证 50 没有 Raw 行，不为其单独制造空记录或事件；当期 Raw 尚未到数也不补成功事件。
6. `AssetMaterialization.partition`、`AssetCheckEvaluation.partition` 必须为对应键；check 用 Dagster 原生关联字段指向本批对应物化。关联信息按资产／批次有界读取，不逐历史分区反复查询 event history 或调用 readiness。原生关联标识不进入业务 run key、源请求或批次身份。事件补录后只做集合／计数汇总及少量分区读回，不再扫行情源。实际事件数为 §9 的 `2N`，不能继续用四份文件推导仅 8 条历史结果。

文件生成、分区注册与事件记录的命令、instance、读写范围在执行前列明并取得批准。这是一次初始化，不是日常 sensor 逐周期触发历史 job；不为每个代码的每根 K 线单独写事件。

bootstrap 只在既定范围内搬运已有完整数据。按 §2 已无待自动修复的历史缺口；若实际导出发生新的缺失或不一致，则失败并交人工，而不是在 bootstrap 内增加“Prod → Tushare → 历史日线”自动补数程序。该来源顺序保留为人工确定缺口处理方式的策略。

### 8.2 简单失败规则

下载、转换、写候选或检查中断：run／命令失败，尚未提升的正式文件不变，运营重跑原分区及目标日。每个日常 job 只替换一个文件，周、月线独立成功或失败。bootstrap 逐文件 `os.replace()` 不保证四文件整体原子；若第一份已提升、第二份失败，第一份可以已经更新，人工重跑原范围，通过主键替换得到完整结果。

本次不实现自动断点续传、逐代码 checkpoint、进度持久化表、后台恢复、文件备份或自动回滚。该简化是管理员 2026-11-17 明确要求，替代模板对长回补的通用恢复流程，仅适用于本次小范围接入。候选校验与单文件原子提升继续保留。

文件已经提升但分区注册／事件记录失败时同样报失败，人工重跑并补齐事实记录；不得仅凭事件缺失就删除正式数据。物理数据重放幂等，Dagster 事件为追加记录，人工重复执行可能留下重复运行记录，不能宣称事件数据库零重复；不为本次实现额外去重状态表或自动恢复系统。无 Kopia、旧湖输入或自动恢复服务。

## 9. 请求、计算、文件与 PG 开销

以下单次任务开销不因取消专用 pool 而改变。周线、月线任务按既有全局单任务队列依次执行，预算不假定两者并行；本数据集不再产生 pool 配置／读回动作或专门并发压力测试。初始化及失败后人工重跑仍按本节的文件与事件数量计费，不因执行串行而重复读取来源历史。

| 场景 | 可复算的请求／处理范围 | 产物与事件 |
| --- | --- | --- |
| Silver 等待日线 | Tushare 请求 0；按 T 读取日线物化／生产 run、该 run 内四种既有 checks，不扫描其他日期的 check history。就绪后对当日文件投影两列、过滤目标 11 个代码 | 无新增物化／check；正常 tick／简短 cursor。日线没成功不提交周／月日更 |
| Raw 等待正式发布 | 每个 Raw sensor 正常至多 1 个单对象单期末 unit，通过组件取完整 11 字段，最多一行或合法空结果；错误重试复用组件策略 | 无物化／check；首次目标键缺失可仅登记。不存在 Tushare 日线探测 |
| 一次 Silver 周线日更 | 业务下载 0；日历窗口最多 7 天，读取其中开市日 DG 日线文件、过滤 11 个代码，逻辑输入最多 `11×7=77` 行；最多计算 11 根周线 | 一个 run，替换 1 个完整文件；本周分区 1 次物化＋1 次 check |
| 一次 Silver 月线日更 | 业务下载 0；日历窗口最多 31 天，读取其中开市日 DG 日线文件、过滤 11 个代码，逻辑输入最多 `11×31=341` 行；最多计算 11 根月线 | 一个 run，替换 1 个完整文件；本月分区 1 次物化＋1 次 check |
| 周、月两项日更合计 | **本链新增 Tushare 日线请求为 0**；两频率累计最多 `77+341=418` 条逻辑输入，重叠日线计两次，本地文件按各自窗口读取。不是 418 条不同日线或磁盘实际扫描行数 | 两个 run、2 个文件，最多 22 根当期 K 线；2 次物化＋2 次 check，4 条分区结果 |
| 一次周线或月线 Raw 更新 | 组件 11 个对象时间点 unit，单个最多一行；1000 行短页规则下正常为 11 次 HTTP 请求，含北证 50 合法空 unit。分页／重试统计取组件 summary，不另写请求循环 | 替换 1 个文件；1 次物化＋1 次 check |
| 一次期末 Silver 覆盖 | 读对应 Raw 本期最多 11 行作为变更；通常直接换算，不重取已有完整合成历史 | 替换对应 1 个文件；1 次物化＋1 次 check |
| 一次 bootstrap | Prod 两张 Raw＋两张 Serving各一次代码过滤投影；历史规模见 §2。科创综指当期读取 DG 日线 Silver，可共用窗口关系，Tushare 日线请求 0。四候选各集合式处理一次，复用分区统计 | 4 个完整文件；若四资产有记录的分区数之和为 N，补录 N 次物化＋N 次 check，即 `2N` 条结果；两个动态键集合批量登记，不逐分区运行计算 |

7 天是一周自然日数，31 天是自然月最大自然日数；停市日不要求有日线文件。这是代码日期过滤后的逻辑输入上界，不是大池日线文件的实际读取行数或压缩字节数；实际 I/O 受 Parquet 列投影、行组和过滤影响，应单独记录。**旧稿周月日更 22 次下载、两个无代码源探测的设计与预算全部撤回。** 已有 DG 日线链的源摄取是既有工作，本次消费它，不额外重复请求或重复执行上游 checks。

正式 Raw 下载正常是每频率 11 个点请求；发布探测是每次一个点请求，均通过组件。当前组件 `ConfigurationSnapshot.max_retries=3`，因此一次点请求若每次都遇可重试错误，最多首次加 3 次重试；11 个 unit 的错误尝试上界为 `11×(1+3)=44`，不把 11 次正常请求称为含重试的绝对上限。该数字来自现有配置，不新增本数据集重试参数；取消／进程中断不作为可重试网络错误，仍直接失败／中断，由人工决定重跑。真实次数和等待耗时使用组件 summary。源参数／字段证据继续复用 §2，组件新契约和 HTTP binding 的最小真实接入核验列入 §11 阶段 E 获批范围；开发阶段先用隔离资源验证组件调用，不重审历史数据，也不把隔离结果冒充真实接入通过。

初始化的 N 从本次已下载／转换数据一次分组得到，不另查 Prod 统计，不用 10992 根 K 线数量代替资产分区数。仅按 §2 历史快照举例：若 Raw 截至周线 11 月 13 日／月线 10 月 30 日，Silver 含截至 11 月 16 日的当期，则 `N=1793+424+1794+425=4436`，结果事件为 `2×4436=8872` 条；两个共享动态集合的键数为 `1794+425=2219`。这些是按已有最早指数覆盖推导的示例，不是重新审计或正式执行实测，未来按实际下载集合计数。**取消初稿 bootstrap 总共只写 8 条结果的估算；合并四个物理文件不会消除按周期跟踪所需的 PG 记录。**

表中结果记录只计 asset materialization 与 check evaluation，不包含 Dagster 正常生成的 run、step、planned 等日志，不能据此声称一次日更在 PG 总共只写四条记录。

正常日更对周／月两份旧 Silver 文件各读写一次，周期 Raw 只读目标范围，日历／基础信息按所需日期和代码读取。业务合并、排序、聚合和数量统计合在同次 DuckDB 处理，不能再起完整文件扫描做重复金融计算。初始化对导出及写入数量核对一次，后续验收不重复扫描 Prod。

复用现有 `DuckDBResource` 设置，不新增内存／线程参数。**尚无本次四个 Parquet 字节数、完整更新耗时、峰值内存及历史事件补录耗时的实测，不写伪造 MB、秒数或倍率。** 实现阶段在隔离目录验证一次对应规模的文件写入和分区事件补录，记录实际请求、累计输入、计算行、文件、字节及耗时；正式验收仅在获批范围内进行。人工中断后重试的预算是重跑本资产完整文件合并，bootstrap 重试可能重放最多四文件和 `2N` 个结果事件；没有免费续跑或固定耗时保证。

不接受全市场抓取、全历史日线重算、逐分区重读完整文件、每个代码单独写事件、日常重发历史分区事件或自动历史补数；一次 bootstrap 的 `2N` 个必要结果不属于日常重复历史事件。历史 metadata 采用资产／批次有界读取，禁止按 N 调用全历史 readiness 或事件深扫。物理文件数减少、结果事件数、Dagster 正常日志开销分别统计，不互相替代。

## 10. 实现位置与影响面

下列是全部阶段的实现位置；B 的 Raw、C 的 Silver 与 bootstrap 入口及 D 的 sensor 已实现。设计阶段已用 CodeGraph explore／impact 和当前文件核对目录与相邻链路，分析覆盖指数资产、checks、jobs、sensors、资源、Catalog 及财势乾坤日线消费者；B 阶段又用 explore 定位相邻周期链和 `TushareDownloader`，D 阶段核对现有日线生产者、四检查、请求／运行键／cursor 与原生交付读取。CodeGraph 结果只用于定位，业务规则以当前代码为准。

| 位置（均相对 `lake_console/orchestrator/src/orchestrator/`） | 本次职责 |
| --- | --- |
| `defs/run_contracts/index_period.py`（新增） | 四资产／checks 名称、typed config、分区和日期输入、DG 日线依赖、已确认运行窗口及 metadata 约定；不在这里另写下载请求拼装 |
| `defs/partitions.py` | 仅新增指数周末、自然月两个专用动态分区定义；不改变现有指数日线、股票或全局分区集合 |
| `defs/run_contracts/asset_column_schemas.py`、`defs/catalog/name_mapping.py`、`defs/catalog/lake_assets.py`、`defs/paths.py` | 四份 schema、两个中文名、四条周期分区＋完整文件布局的 Catalog entry／模型；正式、staging 路径不按分区拆文件 |
| `defs/assets/index_period.py`（新增） | 四个分别分区的资产；加载 partition key／typed config，调用正式 helper，发本分区物化及 checks；不建跨周月分区的 multi_asset，不绑定本数据集专用 pool。旧绑定已按 §11.12 清理，验收见 §11.13 |
| `defs/io/index_period_writer.py`（新增） | 读取 DG 日线窗口并用 DuckDB 合成、正式源单位转换、按键保留历史、候选及单文件原子提升；不创建日线下载器 |
| `defs/checks/index_period_checks.py`（新增） | 四个 file_contract 的稳定规则与结果构造；候选和正式 check 共用，不写第二套 SQL |
| `defs/prod_db/index_period.py`（新增） | bootstrap 只读投影，固定代码范围与字段，不连接日常 job |
| `tushare_download/contracts/index_weekly.py`、`index_monthly.py` 及 `contracts/__init__.py`、`dataset_transport_mapping.py` | 新增两份完整源契约和 HTTP bindings，供 Raw 更新／发布探测复用；不登记 index_daily，不改下载组件公开接口或已有消费者 |
| `defs/bootstrap/index_period_history.py` 及对应受控 CLI（新增） | 四文件初始化、两套历史分区注册与按分区事件补录；复用集合式文件检查及统计，不逐分区重跑 writer 或建立另一套行情公式 |
| `defs/jobs/index_period_update.py`（新增） | 四个同频率、同层 job 的单资产／单 check selection 与中文说明 |
| `defs/sensors/index_period_update_job_sensors.py`（新增） | 四个同名 job sensor；Silver 消费 DG 日线成功结果，Raw 消费正式源发布结果，保持 P＋T 去重和 Raw 原分区覆盖 |
| `defs/sensors/index_period_daily_readiness.py`（新增） | 按当天日线物化／生产 run 有界读取已有四种 check 及 11 码存在性，避开旧 check 空 partition 和全历史扫描；不执行上游或请求 Tushare |
| `source_readiness/tushare/index_period.py`（新增） | 仅正式周／月的单点发布探测，复用通用组件；不含 index_daily 源探测或新下载实现 |

现有 `source_readiness/tushare/index_daily.py` 和既有日线 source／writer／checks 保持原行为；本次不新增 11 指数 Tushare 日线探测。撤回旧稿“源下载复用旧 TushareResource、排除通用下载组件”的取舍：正式周／月下载和单点发布探测均复用现成 `TushareDownloader`，只补本次两份 DG 本地完整契约及 binding，不新写 SDK／HTTP 调用、分页、数据响应解析、下载进程或恢复逻辑。Prod 源定义只作参考，不跨工程 import，不修改 Prod 或其他数据集合同。

当前财势乾坤 `IndexDetailKlineQueryService` 只接受日线，前端周月入口尚未启用。本次新建文件和契约，无既有周月线消费者需要迁移；后续接入时直接消费 DG Silver 单位，不再做第二次单位转换。现有指数日线资产、其 820 代码范围、动态分区和历史补录入口不在本次改动清单。

## 11. 验收、阶段与交付

### 11.1 必要测试及独立依据

| 要求 | 落点与验收证据 |
| --- | --- |
| 11 个代码、历史来源和起点正确 | bootstrap 测试用 §2 已确认列表与源结构；包含北证 Raw 为空、A500 Raw 与 Serving 不等量、科创综指只有 Raw 的正例。错误混用 seed 起点、要求 Raw 必须 11 个都有历史的反例须失败 |
| 历史搬运不重算、单位只换一次 | 采用 §2 已取真实行的独立字面样本；首期零前收盘按源保留；显式核算股→手、元→千元、比例→百分数，检查输入不被当成日线再转换 |
| 当期每日更新、合成与覆盖 | 按真实 DG 日线 schema 构造独立金样本，人工核算 OHLC／前收盘／量额／舍入；覆盖首日、同日重跑、周跨月／年、节假日期末、期末 Raw 优先、历史晚到。Raw 当前分区未物化时可从已有 DG 日线成功合成，禁止为此下载日线 |
| 缺数失败、不过度防御 | DG 日线窗口缺文件／缺指数／缺交易日、接续缺前日则失败；先补 DG 日线再人工重跑。本链不能回退到源下载日线；另一频率已成功结果保留。正式源下载中断及 bootstrap 第二文件失败人工处理，不加自动恢复 |
| DG 日线门禁与零请求 | 上游仅已触发／运行中、失败、check 未通过、check 关联其他日期／物化，均不触发；当天成功且四种 checks 原生关联通过、11 码齐备才提交。旧 check 空 partition 可正确匹配，不用带日期过滤的错误查询或逐 check 扫 5000 条；断言 Silver sensor／job／bootstrap 合成均不调用 Tushare 日线或创建下载器 |
| 通用下载组件接入 | 两份完整契约／模式／时间转换／HTTP binding 与源证据一致；Raw 与发布探测实际调用公开 DownloadTask／session，字段／分页不由业务拼装，北证 50 合法空 unit 可交付；真实最小组件接入验证复用 §2 证据并仅补缺失边界，不重查全历史 |
| 分区与文件相互独立 | 本次新增四资产、四 checks、四 jobs、四 sensors、两套分区，既有日线定义不改；同频率资产／check 使用相同定义。周键实际最后交易日、月键 YYYY-MM，同期两日更新同一键，文件始终四份，其他历史不变 |
| checks 真正归属分区 | 用实际 asset／check 定义在隔离 instance 带 partition key 执行；同时断言 `AssetCheckEvaluation.partition`、`asset_check_executions.partition` 与物化相同，不能为空。完整文件含其他周期的正常样本必须通过；仅目标新记录日期错配必须失败；分区行数与完整文件行数分开 |
| 初始化不重复历史计算 | 四文件只集合式校验一次、生成分区统计；带 partition 补录 N 次物化和 N 次 check，真实原生关联正确。不以四次无分区物化冒充历史就绪，不按 N 次重读文件或调用 readiness；验证分区集合／事件计数及小样本 |
| sensor 调度边界正确 | 19:00 前／零点后／休市跳过、600 秒、默认停止；日线成功后后续 tick 才日更，同 tick 可登记周／月键再提交。P 相同 T 不同再次更新，同 P＋T 不重复；日更后新 Raw 仍覆盖原分区，旧月覆盖不误用新月当天 T；运行中等待，失败不自动重试 |
| 沿用既有队列执行 | 以现有正式配置及四个 job／sensor 的实际入口核验为依据：一次只运行一个队列任务，每个 job 只选择本资产及其 check；人工重跑走同一队列。取消四 pool 的专门并发测试，不用正式 instance 做并发试验；保留既有文件历史、原分区覆盖及人工重跑业务测试 |
| Catalog、文件与人能读懂 | schema／路径／check 名称／partition model 与方案一致；job 不选择上游 writer；cursor 的 reason_code、blocked_component、summary、next_action 和已有长度预算分别测试 |

保留的五份指数周期业务测试映射如下，均位于 `lake_console/orchestrator/tests/`。原六份测试及 123 项通过是 §11.10 的历史验收记录；额外的 `test_index_period_concurrency.py` 及旧 pool 断言已按 §11.12 清理，本轮实际结果见 §11.13。共用人工样本和生产者 schema 继续使用 `tests/index_period_test_support.py`，不复制正式数据。正式资源验收仍留 E。

| 测试文件 | 对应要求与必要反例 |
| --- | --- |
| `test_index_period_contracts.py` | 字段、单位、四组身份、两套分区、Catalog／路径；两份源下载完整契约、HTTP binding、公开组件调用模式及 ISO→YYYYMMDD；不登记 index_daily，不改既有日线定义；拒绝无界来源和错误日期输入。移除旧 pool 断言，保留同条测试中的分区等业务断言 |
| `test_index_period_writer.py` | 真实 DG 日线 schema、独立金样本、单位／舍入、接续、正式覆盖和北证 50 保留、历史行保留；源下载接口替身直接报错，证明 Silver 只读 DG 文件；缺输入／中断失败，补齐 DG 后人工重跑 |
| `test_index_period_checks.py` | 四个实际 check 定义与资产分区一致，实际物化／check evaluation／check execution 的 partition 归属和原生关联；其他历史周期合法存在、目标新增日期错配失败，不调用行情合成函数重算 |
| `test_index_period_sensors.py` | 四个 sensor 的窗口、DG 日线成功／四种关联 checks／11 码门禁、旧空 partition 兼容读取及查询范围、Raw 单点组件发布探测、动态键、P＋T 去重、正式覆盖、默认停止；断言无 Tushare 日线请求 |
| `test_index_period_bootstrap.py` | 11 指数来源／起点及既有例外、科创综指当期只读 DG 日线、Serving 领先 DG 时等待而非下载；四候选集合处理、`2N` 原生结果；不逐分区重读或深扫 readiness，不伪造无分区事件 |

临时文件及隔离 instance 均在工程目录外，不连接正式 Lake、PG 或 Tushare。替身只证明内部链路，真实源合同沿用 §2 已验证证据；正式文件验收只能在单独批准的范围内完成。性能、隔离运行和正式执行结果各自记录，不以文档检查代替测试或生产验收，不重新开展全历史源审计。

### 11.2 阶段边界

| 阶段 | 产出与通过条件 | 当前状态 |
| --- | --- | --- |
| A 方案确认 | 按模板定义字段、Catalog、paths、周期分区／完整文件、四组 job／sensor／check、初始化及预算 | 已提交 `f027076e5`，B 按此基准实施 |
| B 合同与 Raw | 字段／分区／路径、Prod 只读投影；两份完整周期契约和 HTTP binding；Raw 下载及发布探测复用现成组件，writer／check／job 隔离测试；只列本次最小真实组件接入验证范围，不改日线链、不写正式数据 | 开发及专项隔离验收完成，已随 `a01fd3f58` 提交；独立审计见 §11.4，全局治理仍有既有失败 |
| C Silver 与初始化入口 | 从 DG 日线 Silver 合成、单位转换、期末覆盖及 bootstrap；日线缺失不得下载兜底；金样本与人工重跑验证 | 主体及修复分别随 `a01fd3f58`、`44b59c121` 提交，80项隔离回归通过；管理员已授权推进D |
| D 自动化及集成 | 四个默认停止 sensor；DG 日线成功／原生关联 checks／11 码门禁，零日线请求；分区、P＋T 去重、独立 Raw 覆盖、既有全局单任务队列和分区事件集成 | 原开发已提交 `066cd891b`，方案修正已提交 `0ff2458ce`；额外 pool 代码与测试已清理，回归及独立复审通过，见 §11.13；清理改动随本次提交归档 |
| E 正式初始化与最小日更验收 | 列明实例、命令、11 代码范围、DG 日线窗口、N／2N 和既有正式队列入口；获批后完成必要的最小组件真实取数验证、四文件初始化与分区事实补录；待既有 DG 日线 T 成功，再分别经队列运行周月日更及必要读回，不重复全历史源审计 | 已完成，见 §11.16。小数搬运修复后新运行初始化成功，四文件共 21704 行，N=4436；六个手动队列任务和关联检查全部通过。E 验收时四 sensor 停止，后续 F 启用见 §11.18；同日重跑不作为跨日或期末自动时序的验收 |
| F 启用与收尾 | 管理员确认验收后启用 sensor；回填本文、资产拓扑和实际结果 | 已授权并完成 18 日人工接续及四 sensor 启用，见 §11.17–§11.18；四个首个自然 tick 的窗口等待审计通过。真实自动日更、周线／月线正式自动覆盖仍待对应自然窗口，F 尚未全部验收 |

B 阶段使用 orchestrator 现有 `.venv` 的 pytest／Ruff，以及仓库规定的受保护治理测试启动器；无安装或升级步骤。job、checks 与分区事件只在临时目录的隔离 instance 验证，不执行正式 evaluation、materialize、bootstrap、事件补录或 sensor 启停。

以下是后续启动的任务顺序。B、C、D 是三个开发阶段；E、F 是正式执行阶段。各阶段完成本阶段测试、代码与本文口径对账，交管理员验收后再推进下一阶段。开发授权不自动包含正式读写或启用授权。

#### B：基础定义与指数周线、月线 Raw

本阶段形成可在隔离环境执行的两项 Raw 更新入口。

1. 在 `run_contracts/index_period.py`、`partitions.py`、`asset_column_schemas.py`、`paths.py` 落实 11 码范围、字段／单位、周末实际交易日与自然月分区、完整文件和 staging 路径及业务配置；不新增本数据集 pool 配置。
2. 在通用下载组件登记 `index_weekly`、`index_monthly` 两份完整契约及 HTTP bindings，使用 `BY_OBJECT_POINT`。不登记指数日线契约，不改组件公开接口、分页／重试引擎或其他数据集。
3. 两项 Raw 资产在执行线程中创建／关闭下载会话，接收完整 unit，检查本次代码、期末和字段，合并历史、生成候选、检查后原子替换。定义两个 Raw check 和两个 Raw job；导入 Definitions 不创建下载连接或读取凭据。
4. 编写 Prod 两张 Raw、两张 Serving 的只读字段投影与 11／10 码范围，供下一阶段 bootstrap 调用；只写查询能力，不执行正式导出。编写正式周期单点发布探测 helper，复用下载组件，不启动正式 sensor。
5. Catalog 先登记本阶段实际存在的两个 Raw 资产，Silver entry 在 C 阶段随实现登记，不提前生成无对应资产的条目。

验收：完成 `test_index_period_contracts.py`、`test_index_period_writer.py`、`test_index_period_checks.py` 的 Raw 部分及隔离源响应验证；覆盖完整字段、ISO→源日期、两个分区定义、北证 50 合法空结果、其他缺数失败、同键重跑、其他历史保留和中断不提升坏候选。记录两项 job／check 的真实分区归属。最小真实组件取数范围在本阶段列清，执行仍按 E 阶段获批边界，不把替身结果称为真实源验收。

本阶段不生成正式 Lake 文件、不注册正式分区、不写正式事件、不修改既有 DG 指数日线或启用自动化。

#### C：指数周线、月线 Silver 与初始化入口

本阶段形成两个 Silver 更新入口和受控 bootstrap 能力。

1. 实现从 DG 指数日线 Silver 按日历窗口、11 个代码读取和合成；适配实际 DOUBLE 输入与本次 DECIMAL 输出。首期开盘／前收盘、OHLC、量额及涨跌幅舍入按 §4、§5，不重新下载日线。
2. 实现当期接续、同日重跑、缺输入失败、人工 repair；已有正式周期 Raw 优先，正式值覆盖原周期；北证 50 无正式值时保留完整合成记录。只更新本次周期，其他历史原样保留。
3. 定义两个 Silver 资产、两个对应 check／job 和 Catalog entry，声明真实 `silver_index_daily` 血缘；不把上游 writer／checks 加入 selection。至此四个资产、四个 job 和四个新 check 均具备。
4. 编写 bootstrap helper／CLI：十个指数从 Prod Serving 转换，科创综指已结束周期从本次 Prod Raw 转换、当期读取 DG 日线；形成四份完整候选，集合式生成历史分区统计，支持注册两套键和补录带分区的物化／check 结果。
5. bootstrap 复用正式 writer、字段转换及 check helper；数据中断或事件失败直接报告，人工原范围重跑，不增加恢复表、备份、自动续跑或重复公式实现。

验收：完成 writer／checks 的 Silver 部分及 `test_index_period_bootstrap.py`；使用 §2 的真实合同和独立字面金样本，覆盖单位只转换一次、正负中点、首期零值、跨周／月／年、晚到正式值、北证 50、科创综指、历史保留和人工重跑。隔离验证四文件、分区集合、N／2N、原生检查关联；不能按分区重新读完整文件或重算已有源历史。

本阶段 bootstrap 只使用隔离输入／目录／instance 验证，不连接 Prod 执行导出，不写正式 Lake 或事件，不启用 sensor。

#### D：四个 sensor、正式队列与整体集成

本阶段形成可加载、默认停止的完整调度链。

1. 实现当天 DG 日线就绪 helper：定位 T 的成功物化和生产 run，读取其四种原有 blocking check 的关联结果，再确认当日文件包含 11 个目标代码。兼顾旧 check event 的空 partition，不修改日线定义、不重跑其 checks、不扫 5000 条历史。
2. 实现四个同名 job sensor：两个 Raw 按期末源发布触发；两个 Silver 等日线成功后触发日更，另消费新 Raw 批次覆盖原分区。落实 19:00–00:00、600 秒、目标键登记、P＋T 去重、当日合成后仍能正式覆盖和失败人工重试。
3. 复用正式 DG 已有全局单任务队列，四个更新 job 及人工重跑经队列启动；每个 job 只选择一个资产及其随写入检查。取消四个额外 pool 及其专门并发测试，已提交代码的清理按 §11.12 执行，不修改全局配置。
4. 补齐中文 description、cursor、日志、物化与 check metadata；只保留必要数量、窗口和失败样本，不添加新状态表、汇总资产或额外 check。
5. 完成 §11.1 保留的五份业务测试及整体隔离运行，覆盖“DG 日线成功 → 两项周期合成”“正式 Raw 成功 → 原周期覆盖”“缺数／中断 → 失败 → 人工重跑”，并断言 Silver 链 Tushare 日线请求为 0；不再要求四 pool 并发验收。

验收：四资产、两套分区、四 check、四 job、四 sensor、Catalog、schema、路径、默认 STOPPED 与本文逐项一致；实际检查事件和执行记录的分区正确；在 §9 对应规模下记录一次隔离文件／事件开销。按现有环境运行相关 pytest、Ruff、Definitions 静态验证和文档检查，正式资源访问与启用不混入测试。

#### E：正式初始化与手动日更验收

本阶段须单独取得正式执行授权。

1. 执行前列明命令、工作目录、正式 instance、11 个代码、四张 Prod 来源表的投影、DG 日线窗口、四份目标／staging 文件、实际 N／2N 及正式队列提交方式；沿用全局单任务设置，确认四个新 sensor 停止、相关 run 已结束。采用 §11.13 已完成的代码清理与回归结果，不重复已通过且未受影响的验证，不新增 pool 配置动作。
2. 只补尚缺的通用组件真实调用边界：周／月各一个已结束期末、一个代表代码的完整字段请求，核对请求和 unit／Raw 接入合同。沿用已有参数、字段、单位及历史审计，不重新扫描 Prod／Tushare 全历史。
3. 生成四份正式完整文件，按本次传输结果集合式校验一次；科创综指当期依赖 DG 日线，缺失先补上游，不下载兜底。然后批量注册历史分区，补录实际有记录分区的物化与 check，汇总核对数量并少量读回。
4. 待目标 T 的既有 DG 指数日线成功，分别通过正式队列手动运行周线、月线 Silver 日更，确认分区固定、实际截至日更新为 T、其他历史不变、checks 对应本次结果。不设置或读回本数据集 pool 限额。
5. 根据获批的已结束周期，完成一次“正式 Raw → 同一 Silver 分区”的手动覆盖验证，重点确认同日去重不拦覆盖、北证 50 合成值保留；不为测试另做全历史重算。

验收：记录四文件行数／字节数、两套分区与 N／2N、最小真实取数、两项手动日更／正式覆盖及必要读回证据。异常按既定人工重试规则处理；四个 sensor 继续停止，正式初始化完成不等于自动化已启用。

#### F：启用自动更新与文档收尾

本阶段在 E 验收通过、管理员明确同意后进行。

1. 启用四个 sensor，观察一次真实自动日更：日线未完成时等待，完成并通过原检查后才生成周／月任务；日线请求增量为 0，不重复提交同一 P＋T。
2. 在真实周末／月末发布周期验证 Raw 到数及 Silver 原分区覆盖。若相应期末尚未到来，明确记录“已启用、该频率期末自动覆盖待观察”，不能预填通过或用历史手动验证冒充自动运行。
3. 将实际文件、数量、配置、运行结果、失败诊断和完成状态落回本文及需要更新的现有资产拓扑／运行说明，不新建重复的过程报告。

验收：区分“已启用”“自动日更已验证”“周线／月线期末自动覆盖已验证”三类实际状态；仅在对应证据真实取得后标完成。启用和观察范围不扩展为财势乾坤 API／前端接入。

开发阶段分别交付；D、E 后续结果分别见 §11.10–§11.16，F 当前执行前置及范围见 §11.17。各阶段先将硬口径映射到 §10 的具体实现和 §11.1 测试；复用当前代码和已有审计，保留当前 `dev-interface` 工作区其他改动，不把上一阶段授权扩展为未确认的正式操作。

### 11.3 Dagster UI 与排障文字

资产 description：Raw 为“主要指数周线／月线原始行情，按周／月管理。”；Silver 为“主要指数周线／月线，按周／月管理并每日更新当期行情。”。四个 check description 为“校验所选周／月的原始／标准行情写入符合保存契约。”。jobs 与 sensors 使用 §7 中文文案；完整文件布局留在 definition metadata 与本文，不堆进列表文案。

| 现象 | 先看哪里 | 应显示的结论与动作 |
| --- | --- | --- |
| 当天没有触发 | sensor cursor／SkipReason | 周／月键与 T，明确“等待 DG 指数日线成功”“日线检查未通过”或“DG 日线缺北证50”；先处理对应上游，跨日后人工处理 |
| Raw 下载或 Silver 计算失败 | Run 日志 | 对应 job、分区、实际截至日、下载组件错误或 DG 日线缺失；“先补齐上游，再重跑本分区原目标日”，不能提示下游自行下载日线 |
| 文件 check 失败 | 本分区 check metadata | 具体规则、数量及代码日期样本；能区分分区行数与完整文件行数 |
| 文件已写而事件失败 | Run／bootstrap 错误 | 哪个文件已提升、哪些分区事实未完成；人工原范围重跑，不删除数据、不启动自动恢复 |

运行日志仅按下载、计算、写候选、提升及结果报告阶段记录，不逐历史行刷屏。完整说明在本文，cursor 和 PG metadata 不复制本文或审计明细。

### 11.4 B 阶段实施与独立审计记录（2026-11-17）

**§11.4–§11.10 是各阶段当时的实现与验收记录。下文涉及四 pool、专门并发测试及“正式 pool 留 E”的旧要求均已被 §7.4、§11.12 撤销；保留原测试数量和结果供追溯，不再作为后续开发或 E 验收要求。**

本节为 B 交付当时的记录；C 的后续实现及验收以 §11.5、§11.6 为准。

授权只覆盖 B 开发、测试与开发结果审计。本次在当前 `dev-interface` 工作区完成以下实现；未修改既有指数日线、Prod 或下载组件的公开接口／引擎，没有开始 C。

| B 硬口径 | 当前实现位置（相对 `orchestrator/src/orchestrator/`） | 验收证据 |
| --- | --- | --- |
| 只取 seed 的 11 个代码，不使用日线历史起点 | `defs/run_contracts/index_period.py:index_period_codes` | 与已确认 11 码字面清单核对；没有日期过滤或 Prod 池查询 |
| 周实际期末、月 `YYYY-MM`，文件仍完整保存 | `defs/partitions.py`、`defs/paths.py`、`defs/io/index_period_writer.py:index_period_end` | 人工休市周五样本使用周四分区；月分区从日历取月底最后交易日；错误键在下载前失败。两个文件路径均为 `raw/<dataset_id>/full/part-000.parquet` |
| 完整源合同、固定 HTTP、复用公开组件 | `tushare_download/contracts/index_weekly.py`、`index_monthly.py`、`contracts/__init__.py`、`dataset_transport_mapping.py` | 两份 version=1 的 11 字段合同，`BY_OBJECT_POINT`；ISO 日期实际转换成 `YYYYMMDD`，每对象首请求 `limit=1000,offset=0`。`limit/offset` 由现有分页合同维护，不重复登记为业务输入；未登记 `index_daily` |
| 下载完整 unit 后才允许写候选 | `defs/io/index_period_writer.py:download_index_period_rows` | 正常 11 个 unit、北证50空时10行；其他缺代码、缺字段、错代码／日期、重复行及下载中断均失败，正式目标不变；创建与关闭会话在调用线程完成 |
| 原始单位、历史保留、同键替换、失败人工重跑 | 同文件 `write_index_period_raw` | 股／元／比例及四位小数保持；两个周期20行合并与同键重跑结果一致；北证50已有记录保留；A500发布前记录及首期零值不被过滤；坏候选／提升前中断不覆盖旧文件，人工重跑成功 |
| 每资产仅一个 blocking file_contract check | `defs/checks/index_period_checks.py`、`defs/assets/index_period.py` | 两项 check 显式使用同资产分区；候选校验结果用于随写入发出的原生 check，不另起扫描任务。反例覆盖 schema、空／重复键、日期与传输行数；不增加行情重算或历史连续性 check |
| 两个 job、仅本资产／本 check、原生分区记录 | `defs/jobs/index_period_update.py`、`defs/assets/index_period.py` | 在临时 instance 实际运行两项 job；每项仅一份物化和一个检查结果。物化、check evaluation、check execution 的 partition 均为所选键，check 原生关联指向本 run 的物化；metadata 区分分区10行与完整文件20行 |
| 只有 partition 时间输入，导入时不读凭据 | 两项资产显式 `config_schema={}`；同频率固定 writer pool | 额外 `period_end_date/source` 在取源前被 Dagster 拒绝；禁止凭据加载的替身下可导入资产／job。两个 pool 名称已绑定，正式 limit 设置及并发验证仍在 D／E，不声称已生效 |
| Prod 固定字段投影和只读入口，不实际导出 | `defs/prod_db/index_period.py` | 四张表 SQL 与绑定范围均核对：Raw11码、Serving10码且排除科创综指；Raw DATE 转紧凑日期；没有 `SELECT *` 或本地辅助列；替身证明仅走 `connect_readonly_transaction` |
| 发布探测只点查上证指数正式周期 | `source_readiness/tushare/index_period.py` | 同一组件、完整11字段、单对象单期末；有值为已发布、合法空结果为等待；不下载日线、不写文件或状态，不定义 sensor |
| Catalog 只登记已实现的两个 Raw | `defs/catalog/lake_assets.py`、`name_mapping.py`、`defs/run_contracts/asset_column_schemas.py` | 逐项比对实际资产 metadata、中文名、schema、路径、check、分区维度及 `SINGLE_FILE`；没有 Silver 占位 entry。两份既有治理测试只补本次资产／check，未放宽断言 |

测试结果：

- `test_index_period_contracts.py`、`test_index_period_writer.py`、`test_index_period_checks.py` 共 **38 项通过**；现有下载组件 contract registry／request builder／pagination 回归 **28 项通过**，同次合计 **66 passed**。HTTP 编码、响应解析和 Decimal 交付使用现成 HTTP transport，只有连接被替身替换；该结果不是 Tushare 网络或真实源验收。
- `stock_suspend_confirmed_test_runner.py --scope regression --suite test_run_contract_static_gates.py` 通过全部 **113 项**受保护静态门禁；全仓 Ruff 致命错误基线及本次修改 Python 文件的默认规则均通过。文档完整性与本次改动的 diff 空白检查通过。
- 最初直接运行全局治理测试时，停牌固定输入用例因未走专用启动器而不能导入其支持模块。随后改用规定的受保护入口，该停牌用例通过；两份治理 suite 分别在既有的资产清单／check 治理缺项处停止，不能标成全绿。
- 对照本轮前的 Catalog 文件及 HEAD 的两份治理测试，确认资产清单和 check 治理都已缺少 `gold_major_index_quantitative_structure`；readiness 仍有相同的 **27 对**既有未登记关系，本轮新增缺失为 **0**。未修改这些其他数据集，也未删除／跳过失败断言。它们是全局治理未通过的限制，不是本次周月线新增定义缺失；本阶段两个 Raw 已另按同样事实逐项核对。

测试后的独立审计重新核对 §11.2 B 的五项任务，检查实际源码、SQL、两项 job 执行记录、字段字面预期及候选失败反例。结论：**本次实现符合 B 的业务范围、分区／完整文件、通用下载复用及失败处理要求，未发现本次范围内未修复问题；全局治理既有失败仍保留。** 首轮发现的 Raw 空配置约束遗漏、批次标识缺少 `producer_run_id`、资产 metadata 调用不满足静态门禁均已修正并回归。所有单元预期独立于写入计算，不以替身结果代替正式源验证。

成本范围沿用 §9：每频率一次正常 Raw 更新11个单点 unit，正常11次响应、10或11行增量、一个候选及一个完整目标文件；下载组件每请求最多3次有限重试，全部成功到第4次时最多44次尝试。读旧文件一次进入 DuckDB，再做按键合并／排序／COPY；完整文件的 schema 与行数只读元数据，键／日期检查只处理本次增量。中断后人工原范围重跑这些步骤。B 只实测上述小样本与隔离分区事件；完整历史文件字节、峰值内存和 `2N` 历史补录成本仍待 D／E 对应验证，没有沿用日线探测耗时或制造新的耗时上限。

E 阶段最小真实组件验证范围已固定：`index_weekly` 请求 `000680.SH / 2026-07-03`，`index_monthly` 请求 `000680.SH / 2026-10-30`，各一个 `BY_OBJECT_POINT` unit、完整11字段；正常各一次响应、每项应有一行。由组件生成紧凑源日期及分页参数，核对完整 unit 和 Raw 接入合同，不重新读全历史、不请求日线。**本次未执行这两项真实请求或任何 Prod 导出。**

边界：只在 `/private/tmp` 隔离目录创建文件、instance、分区及测试事件；正式 Lake／staging、正式 Dagster／PG、正式凭据及源接口均未用作测试。没有启用或新增正式 sensor，没有配置正式 pool limit，没有写正式分区或事件，没有 bootstrap；C／D／E／F 均未启动。保留工作区其他改动，尤其 Catalog 本轮前的未提交内容。

### 11.5 C 阶段开工约束与实现落点

管理员已授权 C 开发及隔离测试；本阶段不执行正式来源查询、导出、写湖、分区／事件写入或 sensor 操作。沿用 §2 证据，不重新审计 Prod 历史；不修改既有指数日线或开展 D 自动化开发。

| 要求 | 本步实现与验收 |
| --- | --- |
| Silver 入口、配置与血缘 | 扩展既有 `run_contracts/index_period.py`、`assets/index_period.py`、`jobs/index_period_update.py`、paths／schema／Catalog。新增两个 Silver 资产、对应两个 check／job；与同频率 Raw 共用分区，绑定各自 writer pool。配置仅 `mode=daily/period/repair`（必填）、`trade_date`（仅 daily 必填）；额外来源、频率或重复期末输入均拒绝。声明日线、Raw、日历和指数基础信息血缘，不选择其 writer |
| DG 日线合成 | 在既有 `io/index_period_writer.py` 按自然周期一次查询日历、11码基础信息，按发布日期构造需要的日期／代码集合；一次读取本频率必要日线文件并投影9列。缺文件、缺日／代码、空必要值、重复或首日前收盘为0时失败；没有源下载兜底。日更非首日要求旧周期截至上一应有交易日或本次目标日，同日可重跑，禁止截至日倒退 |
| 精度、接续与覆盖 | 价格和量额先适配 §4 的 DECIMAL。以整数价格单位精确实现 Prod 的比例四位 `ROUND_HALF_UP`，再乘100，不用二进制除法近似判断正负中点。Raw／Serving量额仅在进入Silver时除100／1000，比例乘100；日线量额不再换算。period 只用期末Raw加已有完整Silver，北证50不重读日线；缺完整记录失败。repair保留已有完整记录，其余优先Raw、再读DG日线补齐，不要求旧周期接续 |
| 共用文件写入与 check | 在原 writer 中提取按键合并、候选生成／检查／原子提升的共用函数，供现有Raw、Silver和bootstrap调用。check稳定规则保留同一实现，以SQL聚合传输／键／日期结果；日常仅检查增量，bootstrap四来源分别一次集合式分组产生各分区数量／截至日。schema与完整文件行数使用元数据；不逐分区读文件、查询readiness或重算行情 |
| bootstrap 生成与事件 | 新增 `bootstrap/index_period_history.py`、`index_period_history_cli.py`。四张Prod表复用B只读投影；采用命名游标、按驱动现有 `itersize` 分批交付DuckDB，不自行设请求或内存倍数。批次传输使用已有 pandas，DataFrame仅含单批；本机没有PyArrow，不新增依赖。十指数Serving仅转换，科创综指已结束期从本次Raw转换、当前期只读DG日线；Serving当前截至日不一致或DG输入不足即失败。先生成并检查四候选，再逐文件提升；批量登记两套键，按四资产实际分区数N写2N事件。每资产批量查询本次N条物化取得原生关联，不按分区查询 |
| CLI及配置审计 | `python -m orchestrator.defs.bootstrap.index_period_history_cli --operation-id <ID>` 默认只显示固定来源、对象范围和目标，无连接或写入；显式 `--apply` 才执行完整bootstrap及事件，使用既有Resources、正式roots和当前明确的DAGSTER_HOME。operation-id作为本批标签进入批次标识；候选目录使用本次原生run_id，人工重跑相互独立；不开放任意来源、代码池或Lake根覆盖。测试通过函数参数注入临时路径／instance与来源替身，不用CLI切换正式边界 |
| 失败及范围 | 单文件原子提升，四文件不保证整体原子；任何异常直接失败，人工原范围重跑。无恢复表、备份、自动续跑、自动回滚或自造锁；已经写入的文件和事件不删除。正式初始化和真实组件点查仍在E |

成本沿用 §9：日常每频率一个周期、11码、最多7／31个自然日日历范围、77／341条过滤后逻辑日线输入、0个源请求；旧完整文件一次加载后按键合并，写一个候选和两个分区结果。bootstrap四条固定范围投影查询／四次只读连接，批次大小继承现有驱动游标值，内存中的Python业务缓冲仅单批；DuckDB复用现有连接配置。四个来源一次装载、四个候选各一次保存／检查和分区聚合，事件原生关联查询每资产一次而非N次；重跑重新执行这些步骤，不将失败视为免费续跑。N由本次分区统计取得；无法精确预估字节、耗时和峰值内存，不编造上限。拒绝全市场、全历史日线重算、逐分区深扫或超出本次四文件的写入；对应规模的隔离验证在本阶段记录，正式性能仍待E。

验收扩展原三份测试并新增 `test_index_period_bootstrap.py`：独立字面金样本、正负中点、单位一次转换、首期零值、跨周／月／年、发布日期、接续／同日重跑／禁止倒退、缺输入失败和人工重跑、晚到Raw及北证50、科创综指、四候选失败不提升、2N原生关联与集合式读取。运行现有组件回归、受保护静态／Catalog／check治理入口和Ruff；既有治理问题继续区分，不放宽断言。

#### C 实测后的事件归属修正（2026-11-18，管理员已确认）

隔离测试发现安装的 Dagster 对同一资产／check／分区重复补录 runless check 会撞唯一键。第一次文件和事件可完成，第二次物化已追加而check插入失败，因此原文“runless事件中断后直接整段重跑”的方式不能满足本任务。已核对当前安装代码：runless分支直接插入，键包含空run_id；有原生运行ID时按运行和分区保存。未查询或修改正式PG。

管理员明确同意改为**每批独立的Dagster原生运行**。本项替代本文所有涉及本数据集bootstrap的runless事件执行要求，不改变其他数据集或全局runless能力：

- CLI仅在显式 `--apply` 后构造并执行一次 `index_period_history_bootstrap_job`；该入口只在CLI调用时创建，不登记成日常Definitions的第五个更新job，也不新增bootstrap资产。固定一个op完成整批，运行终态由Dagster维护。
- 四文件生成／检查／逐文件提升保持不变；物化和check均归属本批真实run_id，check继续原生关联本批对应分区物化。每次人工重跑是新的运行，旧文件及事件不删除，无自造去重表、恢复状态或自动重试。
- 仍按本批分区统计批量登记两套键，并写 `N` 次物化、`N` 次check，即 `2N` 条资产结果。额外存在一次原生运行的正常运行／步骤日志，与资产结果数量分开，不再称为runless补录；不按N启动job。
- 扩展测试须证明两次完整bootstrap数据一致、两次原生run_id不同且成功；中途事件失败时四文件保留，人工新运行重试可以完成。原生关联仍每资产一次批量读取，不逐分区查询。

正式执行仍留到E阶段单独授权；本轮只在隔离instance验证。原先被该冲突阻断的测试保留为人工重跑的回归，修正后必须通过，不能删掉或跳过。

### 11.6 C 阶段交付与独立审计（2026-11-18）

以下保留提交前的开发及隔离验收记录；其中“未发现未修复问题”的结论已被 §11.7 的提交后复审更正。管理员确认的“每批独立原生运行”已落地。未开始D，未执行正式Prod／Tushare请求、正式Lake／staging写入、正式分区／事件补录、pool配置或sensor操作。

| C 要求 | 实现落点与证据 |
| --- | --- |
| 两项Silver及对应入口 | `assets/index_period.py`、`checks/index_period_checks.py`、`jobs/index_period_update.py`。四个日常资产／check／job均已具备；周／月仍各用原动态分区。两个Silver的12字段、手／千元／百分数、pool、Catalog、路径及四项只读血缘逐项匹配；job实际只执行本资产和本check，不触发上游writer |
| 真实DG输入合同 | `io/index_period_writer.py` 明确读取既有DG日线DOUBLE输入并转DECIMAL；仅投影需要的9列、按日期／代码集合读取，日线涨跌额／涨跌幅不参与周期相加。夹具使用已核对的calendar／index_basic／index_daily生产者schema；源下载器替身直接失败，证明Silver不请求Tushare。科创综指发布日期取基础信息，seed日线起点未参与 |
| 合成、单位和舍入 | 独立字面样本验证OHLC、首日前收盘、量额求和及涨跌额。比例四位ROUND_HALF_UP通过整数运算后乘100，正负中点及中点两侧均有独立预期。Raw／Serving历史只转换单位一次，保留首期零值；DG日线量额不再换算 |
| 日更、修复及正式覆盖 | 验证同日重跑、缺前一交易日失败、缺文件／代码／值或重复失败、禁止截至日倒退；先补DG输入再人工重跑成功。repair仅允许上海日期下已结束周期，不要求旧周期接续，已有完整记录保留；发布日期、休市周五、跨周／月／年与新周期首日已覆盖。期末Raw成功后同一Silver分区另行覆盖；北证50已有完整合成值保留，不重读日线 |
| 物理保存与原生检查 | Raw／Silver／bootstrap复用同一按键合并、候选检查及提升入口；检查仅覆盖本次传输与身份，不重算价格公式。Silver将旧完整文件一次加载，供接续和合并共用；计数测试证明没有第二次读旧Parquet。隔离实际job验证物化、check evaluation、check execution的partition及本run原生关联；分区行数、文件行数和逻辑输入数量分别记录 |
| 四来源初始化 | `prod_db/index_period.py` 使用命名游标和原有只读事务；`bootstrap/index_period_history.py`按游标itersize分批传输，Python只保留当前批。十指数Serving直接采用，科创综指已结束期从同次Raw转换、当期从DG日线合成；没有重新查询或复核Prod历史。四份候选全部通过后才逐文件提升；坏的最后候选或DG输入不足均不提升任一文件 |
| 批次运行、事件与重跑 | 每次CLI apply创建一次原生运行，固定一个op，未向Definitions增加日常job或bootstrap资产。真实run_id用于候选目录和事件归属；四资产Catalog事件策略均为DAGSTER_RUN_ONLY。两次完整初始化的数据一致、run_id不同且均成功；模拟事件中断时文件保留、原运行失败，人工新运行重试成功。既有事件不删除、不加去重表或恢复服务 |
| CLI与运维边界 | `index_period_history_cli.py` 默认只输出来源／投影／代码范围，未创建资源；额外Lake根输入与非法operation-id在连接前拒绝。只在显式apply时使用既有Resources和明确DAGSTER_HOME。测试只注入临时路径、真实隔离instance和PG来源替身；没有用正式连接或凭据试跑 |

测试与限制：

- 四份指数周期测试共 **75项通过**，加现有通用下载组件28项回归，合计 **103 passed**；包含B阶段回归。受保护静态门禁 **113项通过**。Ruff致命错误基线、本次Python文件默认规则及文档检查分别验收；未安装或升级套件。
- 初始化人工样本一次传输Prod替身60行（两份Raw各10、两份Serving各20），生成四文件64行（Raw各10、Silver各22）。科创综指当期两频率累计6条过滤后逻辑日线输入，重叠日期重复计，不是磁盘实际扫描量。四资产分区数合计N=6，每批资产结果12条，即2N；两个共享动态集合各2个键。原生关联公开查询每资产一次，共4次；未按N读文件或查询readiness。完整真实历史规模和来源耗时仍待E，未把小样本耗时当作正式保证。
- 全局Catalog／check治理测试仍在原有缺项处失败：`gold_major_index_quantitative_structure`未列入治理测试清单，27对readiness关系未登记。与C开工前的Catalog及两份治理测试快照对照，新增缺失为0；没有更改其他数据集或放宽断言。不能将全局治理称为全绿。
- Prod来源在本轮由游标替身替换；HTTP／PG真实访问、正式完整文件、正式历史事件和正式pool有效限额均未验收。源参数／历史完整性／单位沿用§2；真实组件点查及正式初始化仍在E。

提交前的审计重新逐项核对C的五项任务、实际SQL／消费者、配置、四资产关系、失败反例和运行记录，修正了遗漏的repair已结束周期约束、Silver旧文件重复读取及来源数量／metadata表达；runless冲突按管理员明确决定改为每批原生运行并验证人工重跑。**当时“本次C范围内未发现未修复问题”的判断遗漏了来源精度与目标精度的区别，该结论撤回，以 §11.7 为准；全局既有治理缺项继续保留。** 下一阶段需管理员另行授权，当前不进入D。

### 11.7 提交后 C 阶段复审与 D 开工判断（2026-11-18）

已在 `dev-interface` 提交 `a01fd3f58`，仅含本任务26个文件，混在资产目录文件中的其他格式调整未提交。提交后核对当前代码、C五项任务及已有隔离证据；没有重复读取Prod／Tushare或正式Lake历史，也没有修改业务代码。

**发现一项必须先修复的错误。** `bootstrap/index_period_history.py:load_prod_index_period_relation` 在载入Prod Serving时直接使用DG Silver schema，而此时单位仍是股／元／比例。Prod周线、月线Serving的 `vol/amount` 都是 `Numeric(20,4)`，依据为 `src/foundation/models/core_serving/index_weekly_serving.py` 和 `index_monthly_serving.py`。DG Silver成交额的 `DECIMAL(20,7)` 为换算后的千元保留七位小数，只有13位整数；在换算前套用它，会先缩小合法源值的整数范围。

只用内存DuckDB和单行游标替身复现：来源成交额 `10000000000000.0000` 元（10万亿元，符合Prod的20位总精度、4位小数定义）应转换为 `10000000000.0000000` 千元，符合DG目标定义；现有loader在转换前报 `ConversionException: value is out of range`。该样本用于证明合同内输入被错误拒绝，不代表本轮查询到了同额的正式记录。错误发生在候选生成前，未造成正式数据变更。既有bootstrap样本成交额为 `98765.4321` 元，未覆盖此处，因此103项既有通过结果不能证明来源精度适配正确。

其余已核对部分与C口径一致：DG日线合成和单位只转换一次、Raw覆盖原周期与北证50完整记录保留、四个独立job／check和周期分区、四候选全部校验后才提升、每批独立原生运行和人工重跑。真实HTTP／PG接入及正式执行仍未验收；全局治理的既有失败仍按 §11.6 说明保留。

下一步仍属于C修复，不是D开发：

- 在 `load_prod_index_period_relation` 的来源临时关系中保留Prod Serving实际字段类型和原始单位，完成单位转换后才套用DG Silver schema；核对完整12字段，保持Raw及DG最终文件合同不变。
- 增补来源精度的独立字面样本，至少覆盖上述失败值、普通值及小数的保留；证明失败值修复前会被拒绝，修复后得到上述千元值，成交量与涨跌幅仍只转换一次。复用既有四文件及人工重跑隔离测试，不重新审计已有全历史。
- 不新增配置、源请求、文件、check或恢复机制；四次固定来源查询、按游标批次传输、失败人工原范围重跑和正式执行留E的边界保持不变。修复、重跑及最后验收沿用 §9 的相同步骤开销，不新增全量比对。

**本次提交后复审的结论是C尚不符合全部验收条件，须先修复再进入D。** 修复后的最新状态见 §11.8。D的四sensor、上游成功及原检查关联门禁、P＋T去重、Raw独立覆盖与四pool串行验证已在 §7、§11.2 明确，无需因此重新讨论业务口径；修复通过后再按阶段授权开工。

#### C 修复执行约束（2026-11-18，管理员已授权修复）

修复前已用 CodeGraph explore／impact 和实际引用核对：来源loader仅由本文件的四来源初始化调用，再由受控CLI进入；日常四个job、财势乾坤读取、Prod写入均不受本次内部类型修正影响。没有现成的Prod指数周期Serving字段类型定义可直接复用，不能继续用DG Silver目标schema反推来源类型。

| 硬口径 | 实现与验收 |
| --- | --- |
| 来源完整12字段保持Prod原类型、原单位 | 在 `defs/prod_db/index_period.py` 用既有 `ColumnContract` 定义 `PROD_INDEX_PERIOD_SERVING_SCHEMA`，从它派生原 `SERVING_COLUMNS`，保持SQL字段顺序和投影不变。代码为VARCHAR，两日期为DATE，六个价格／涨跌点位为DECIMAL(18,4)，涨跌幅为DECIMAL(10,4)，成交量／成交额为DECIMAL(20,4)。依据为两份当前Prod Serving模型；不运行时导入Prod工程 |
| 换算后才使用DG最终schema | `load_prod_index_period_relation` 的Serving分支使用上述来源schema；后续 `index_period_silver_from_source_sql` 仍只换算一次，再在既有目标投影中使用DG schema。Raw、日线、文件路径、job／check／分区、配置、源请求及事件方式均不改变 |
| 先复现、再修复、再验收 | 扩展 `test_index_period_bootstrap.py`：两频率来源完整schema与原数值；普通值、成交额10万亿元及四位小数、超过原错误成交量范围的值、Prod DECIMAL(20,4)最大值。预期均为独立字面值，不调用转换helper生成expected。先证明原实现失败，再验证四文件、单位一次转换、原生分区关联和人工原范围重跑 |

本次不增加正式读取或写入；隔离测试的PG来源继续用游标替身，文件及instance仅位于本任务 `/private/tmp` 目录。正式执行仍在E。查询、分页／批次、DuckDB装载／转换／候选生成及每文件提升次数不增加，沿用 §9 和 §11.5 的正常及人工重跑开销；测试复用原四文件样本，不读取或重新审计正式全历史。失败直接报告，修复不加捕获、补值、扩大目标精度、恢复机制或新生产check。验收执行受影响的四份指数周期测试、修改文件Ruff、既有致命错误基线及文档检查；与本次未变的全局治理缺项区分。

### 11.8 C 来源精度修复与复审结果（2026-11-18）

管理员要求按修复流程处理后，先补齐 §11.7 的执行约束，再增加反例，最后修改来源读取。修复仅涉及 `defs/prod_db/index_period.py`、`defs/bootstrap/index_period_history.py`、`tests/test_index_period_bootstrap.py` 和本文；没有修改其他任务的文件。

| 修复要求 | 实际落点与验证 |
| --- | --- |
| 完整来源类型独立于DG目标类型 | `PROD_INDEX_PERIOD_SERVING_SCHEMA` 明确保存Prod的12字段及类型，SQL列名从同一来源定义派生；loader只在Serving分支改用它。逐项核对两份Prod模型，周／月隔离测试分别检查完整schema与原比例、股、元数值 |
| 旧错误能被回归抓住 | 改生产代码前，来源schema两例及大额成交额／大成交量／来源精度最大值三例失败，普通样本通过，即5失败、1通过。失败分别为错误来源类型或换算前DECIMAL溢出；未修改预期迎合旧实现 |
| 单位转换只做一次，精度不丢失 | 在原四文件初始化测试中增加独立字面样本：`10000000000000.4321`元得到`10000000000.0004321`千元；`100000000000000.6789`股得到`1000000000000.006789`手；Prod DECIMAL(20,4)最大值`9999999999999999.9999`分别得到`99999999999999.999999`手和`9999999999999.9999999`千元。普通值及涨跌幅仍沿用原预期，两频率均检查 |
| 初始化与人工重跑保持原行为 | 每组金额样本均执行四文件初始化及新原生运行的人工重跑，检查数据一致、run_id不同、两套动态分区、物化／check关联及2N结果。原来的坏候选不提升、事件失败保留文件后人工重跑等用例保留并通过 |
| 不扩大来源、执行与性能范围 | 将当前两份Serving SQL与修复前提交中的12列顺序作静态比较，字符串一致，仍为10码且排除科创综指。Raw合同、四文件目标schema、日更与期末覆盖、批次大小、四次来源查询及候选／事件次数未改。隔离样本每批仍为四文件64行、N=6和12条资产结果；没有新增正式请求、全历史读取或生产check |

本次重新运行四份指数周期测试为 **80 passed**，用时6.70秒，是当前人工小样本隔离结果，不代表正式历史耗时；较原75项增加两项来源schema检查及三项金额参数用例。修改的三个Python文件Ruff默认规则、项目既有致命错误基线 `E9,F63,F7,F82`、文档完整性及本次diff检查均通过。未修改通用下载组件，未重复运行其原28项回归；§11.6的全局治理既有缺项也未改，不能将其称为本轮已全绿。

测试后按来源模型、实际SQL、loader和转换调用链重新复审：源类型在换算前保持完整，最终DG字段类型没有扩大；无跨工程运行时导入、额外配置、补值或异常兜底。CodeGraph explore／impact及实际引用确认本次修改仅进入bootstrap链，既有日更与消费者不受影响。**§11.7的C阶段阻塞已解除，当前C开发与隔离验收满足本方案，可交管理员验收；D具备开工条件，但本轮未进入D。** 真实HTTP／PG接入、正式四文件初始化、正式pool限额和sensor启用仍分别遵守E／F授权，本次均未执行。

### 11.9 D 开工约束与实现落点（2026-11-18）

管理员已授权提交C修复并推进D；C修复提交为 `44b59c121`。本阶段只开发及隔离验收，不操作正式instance、Lake、来源连接、pool配置或sensor启停。复用 §7、§9 的口径与既有审计，不重新读取Prod／Tushare历史。

CodeGraph explore及当前代码核对覆盖原生日线生产者／四检查、周期资产与job、运行键／cursor／请求构造、相邻股票周期sensor和readiness。股票周期消费的是其专有completion协议，主要指数通用输入helper又按日线seed起点过滤，均不能直接用于本次11码当期门禁。通用readiness还存在5000条check历史读取；本次使用现成原生查询API按目标物化／生产run取结果，不修改通用helper或既有日线定义。

| D硬口径 | 本步实现与验收 |
| --- | --- |
| 当日日线成功、四种原检查原生关联、11码齐备 | 新增 `sensors/index_period_daily_readiness.py`：T分区最新物化1条、生产run1条、该run最新四条check evaluation（数量来自当前单资产job的四种checks，无自动step重试）。核对check名称、blocking／passed、目标storage_id及run_id；partition允许原来的空值或T。之后仅从T文件投影代码／日期、过滤11码。缺失等待，不创建下载器、不重跑检查 |
| 基础信息和周期交付的已有检查 | 同一helper从Catalog取得当前blocking检查名，批量读最新结果并关联最新物化；周期按P过滤，无分区基础资产不套日期过滤。一次交付读取只取一条目标物化并返回该记录。Raw顺序候选与该P最新物化各取一条，用于排除被同P新批次替代的旧候选，不按历史分区深扫。派生readiness specs供既有治理消费，四项周期检查的sensor参与标记改为true，不新增check |
| 四sensor同名job、日历与窗口 | 新增 `sensors/index_period_update_job_sensors.py`；全部默认STOPPED，19:00至零点前、600秒，先判断窗口和本job是否已有排队／运行，再读基础事实及日历。按所需频率读取：两个周线sensor只读本周7个自然日；月线Silver只读本月最多31个自然日；月线Raw读上月首日至当天，最多31+31=62个自然日，以判断上月期末和本月首个交易日。不把无关上月或未来下周日历缺口作为当前周线门禁。周Raw仅当周末交易日，月Raw仅次月首个交易日；各至多1次现成单码完整unit探测 |
| 日更及独立Raw覆盖 | Silver先尝试当天P＋T日更；已完成／已提交或上游等待时，仍可判断新Raw。每tick至多1个RunRequest和1个缺失周期键的同批登记。typed配置转换函数补在 `run_contracts/index_period.py`，sensor不拼深层ops配置。复用现有两种run-key builder；同一运行键已有成功／失败／取消记录均不自动重试，人工从原job重跑 |
| 新Raw顺序与首次启用 | cursor只存一个Raw事件位置。首次从该资产最新物化开始，若来自bootstrap，仅建立起点而不重放历史初始化；之后每tick按位置升序取1个新Raw物化。原生run仍在执行时等待，失败或同P已被更新批次替代时跳过旧候选并保留原因；成功且关联检查通过才使用其batch_id及原P提交period。已提交批次以后续运行事实确认，不拿cursor当就绪证据；不丢弃后续不同P的批次，不新增状态表 |
| 单文件串行及整体链路 | 新增 `test_index_period_sensors.py`、`test_index_period_concurrency.py`，扩展必要的现有测试／治理登记。并发测试使用隔离持久instance及真实multiprocess执行器、四原生pool各limit=1，两个不同周期的真实资产step写同文件时记录进入／退出并核对两次修改保留；不同文件可在同一时段进入。测试用临时协调文件控制验证时序，不是生产锁或恢复机制。正式pool仍留E |

配置沿用 §7.5，没有新增env、数据库或运营参数；测试专用目录／协调信息仅在 `/private/tmp/dg-index-period-d-20261118` 及其pytest临时目录，测试资源明确替代来源网络、正式根和DuckDB临时目录。原生pool／分区／事件也只写隔离instance。正常、失败后人工重跑及最后读回的文件／事件开销沿用 §9；sensor额外开销只有上述有界元数据查询和日历／当天两列读取，业务下载0、行情输出0；不承诺未测得的正式秒数或字节数。

验收先跑六份指数周期测试及原生集成：正向包括空partition旧检查、同P不同T、Raw晚到／旧月原P覆盖、首次bootstrap起点、连续不同P批次和跨月／节假日期末；反向包括仅触发／运行中／失败上游、错误或缺check关联、缺目标码、窗口外零重读／零请求、失败不自动重试、坏候选与人工重跑、cursor长度。再跑修改文件Ruff、致命错误基线、必要受保护静态／Definitions验证及文档检查。只补D未覆盖的验证，不重复历史源审计；已有全局治理失败须单列，不能放宽断言或宣称全绿。完成后另行按代码与本文复审，不自动进入E。

### 11.10 D 交付、性能样本与独立复审（2026-11-18）

C修复先按管理员要求提交为 `44b59c121`，没有推送。D仅修改本方案、`run_contracts/index_period.py`，新增两个sensor／门禁模块及两份对应测试；既有检查治理文件只改四项周期检查的sensor参与标记（两处布尔值）。当前工作区其他任务的目录格式调整及未提交内容保留。D 开发验收时尚未提交，随后按管理员要求提交为 `066cd891b`，未推送。

| D任务 | 实现与验收结果 |
| --- | --- |
| 当天DG日线门禁 | `index_period_daily_readiness.py`按T最新物化、其成功生产run及四种原检查的原生关联判断；旧空partition可用。反例覆盖运行中、失败、缺检查、红灯、非blocking、其他物化／run、缺文件／目标代码和其他日期。检查未完成的PLANNED记录判为未就绪，不当成evaluation访问；不扫5000条历史、不重跑检查、不请求Tushare |
| 四sensor与三种触发 | `index_period_update_job_sensors.py`四名称、同名job、默认STOPPED、上海19:00至零点前、600秒和领域／层级标签一致。窗口外不读资源／事件；运行中不积压。原生 `SensorDefinition.evaluate_tick` 分别验证四sensor同tick返回缺失键登记及正确RunRequest，evaluation未直接修改动态分区。测试按实际RPC入口提供隔离instance_ref，不用测试入口缺失的实例引用反推生产行为 |
| 日期、去重与Raw覆盖 | 验证同周不同T生成不同运行键、同P＋T不重复、失败后原job人工重跑；日更完成或失败不挡独立Raw分支，上月Raw覆盖原月。首次跳过bootstrap历史；后续不同P的Raw按顺序各处理，同P修订跳过旧候选；使用既有运行键、typed config和cursor，无新表、额外check或自动恢复 |
| 四pool与文件保存 | 隔离持久SQLite instance中四pool各limit=1，真实 `execute_job(reconstructable(...))`＋multiprocess执行器运行实际四种资产step。四组同文件不同周期测试均观察到原生pool阻塞事件，第二writer在第一退出后才进入，最终Raw20行或Silver22行、两个周期的更新均保留；不同文件的pool可在另一writer仍被测试协调暂停时进入。测试HTTP替身只替换源，不替换文件writer／检查或执行器 |
| 真实生产者最小链路 | 在临时Raw文件上运行现有 `silver_index_daily_update_job` 与四个原检查，确认旧检查partition为空、原生关联完整，再由两项sensor结果执行真实周期job并检查物化／check分区一致。上游文件、原检查SQL与周期writer均实际执行；仅网络、正式根、临时目录及instance隔离。缺数失败、补齐后人工重跑与正式Raw覆盖保留原有验证 |

六份指数周期测试整体 **123 passed**（B／C80项＋sensor38项＋原生并发5项），耗时31.93秒。复审调整日历范围及中文状态后，又运行sensor38项、受影响的两项失败／Raw独立覆盖及四项文件／日期用例，均通过；它们是原123项的重跑子集，不额外累加。文件日期反例保留完整11码，只改文件内部日期，避免由缺代码提前阻断而掩盖日期错误。受保护静态门禁113项通过；修改的Python文件Ruff默认规则、项目致命错误基线、文档和diff检查通过。既有 `.venv` 的 `dg check defs --use-active-venv --no-check-yaml` 在任务临时DAGSTER_HOME中返回“All definitions loaded successfully”；未安装、同步或升级依赖，未改YAML定义。

按 §2 的已接受历史行数生成一次人工保存规模样本，以现行writer执行两项真实Silver日更；历史价格是重复人工值，日期也非正式日历历史，以下字节和耗时不能推算正式数据大小或性能保证：

| 人工文件 | 更新后行数 | 更新后字节 | 本次过滤后逻辑日线输入 | 本次物化＋check | 隔离run实测秒数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 指数周线Silver完整文件 | 8890 | 52202 | 33 | 2 | 0.04755 |
| 指数月线Silver完整文件 | 2102 | 10809 | 143 | 2 | 0.04540 |

两频累计输入为 `33+143=176` 条，周窗口日期已包含在月窗口内，不能称为176条不同日线或磁盘实际扫描量；共替换两个完整文件、写四条资产结果，日线源请求为0。真实文件字节、完整历史初始化／事件耗时和正式pool有效限额仍留E，未以此小样本替代正式验收。

独立复审在测试后重新核对本阶段五项任务、读取API、原生事件、配置与消费者，纠正了周线读取无关上月日历可能误挡执行的问题，并用“上月有缺口、本周完整仍可执行”的反例验证；也修正了已完成日更仍显示等待日线、失败日更未明确提示人工重跑的文字与blocked_count。没有增加价格重算或历史连续性check，没有更改既有日线生产口径、四文件schema或保存路径。

全局检查治理的受保护测试本轮仍在原有 `gold_major_index_quantitative_structure` 未登记处失败（1失败、1通过后停止），没有删断言或跳过失败。本轮未运行到原27对readiness关系的断言，该数量只沿用C记录，不能当成D重新测得的值；四项新增周期关系已按实际消费登记。**本次D范围内未发现未修复问题，开发及隔离验收符合方案，可交管理员验收；全局治理不能称为全绿。** 本轮未进入E，不读取正式源、不写正式Lake／staging／分区／事件、不配置正式pool，也未启用sensor；正式资源验收和启用仍须后续阶段分别授权。

### 11.11 D 提交后的 E 开工审计（2026-11-18）

**更正：本节的来源计数、当期日线和目录／运行只读证据继续保留其原时间范围；原“并发粒度不同，所以阻塞 E”的判断及再加四个运行级 pool 的建议撤回。管理员已确认的执行方式见 §7.4，本轮文档修正及尚未完成的代码清理见 §11.12。**

本轮只提交 D 并审计 E 的前提，不执行 E。D 提交仅含上述七份文件，检查治理文件只提交两处参与标记，保留同文件原有格式改动及其他任务内容；没有重跑已通过的 123 项隔离测试。本轮没有业务代码修改，不把只读核验称为正式执行验收。

#### 已核验的正式前提与读取范围

本次 Prod 只读事务通过 `scripts/psql-remote.sh` 执行：四个代码白名单范围的计数，加十码 Serving 各频率的最新日期及科创综指 Raw 各频率的最新日期，共返回 26 行汇总／日期结果，不读取历史行情明细。历史起点、完整性、连续性与单位继续采用 §2，不重复计算。DG 复用现有只读 instance 连接，禁止自动建表且事务 `default_transaction_read_only=on`；只读取相关运行、四个 sensor／pool、基础交付、目标日关联检查及下表窗口的代码／日期存在性，没有执行 sensor evaluation 或 checks。

| 前提 | 当前证据与结论 |
| --- | --- |
| 来源截至日一致 | 两频率的十码 Prod Serving 最新日期均为 `2026-11-17`；科创综指 Raw 最新周线 `2026-11-13`、月线 `2026-10-30`，没有领先 Serving 快照 |
| DG 上游已成功 | `silver_trade_calendar`、`silver_index_basic` 的当前原生交付就绪；`silver_index_daily` 的 `2026-11-17` 生产运行 `21b78ebb-4e72-4717-b3ca-037a61154e57` 成功，四种原 blocking checks 均通过并关联该次物化 |
| 当期日线存在性 | 周窗口为 `2026-11-16`、`2026-11-17` 两个开市日；月窗口为 `2026-11-02` 至 `2026-11-17` 的十二个开市日。合并读取十二个日线文件，只投影代码／日期并过滤十一代码，共 `12×11=132` 个唯一组合，缺文件、缺组合及重复组合均为 0；科创综指 bootstrap 当期所需组合无缺失。周窗口已包含在月窗口内，不能将两者累加称为不同日线数量 |
| 日历范围 | 只读取 `2026-11-01` 至 `2026-11-30` 的 SSE 日期／开市标记，共 30 行；当前周键为 `2026-11-20`，月键为 `2026-11`，实际截至日仍为 `2026-11-17` |
| 四文件与目录 | 四个正式目标文件尚不存在，没有覆盖现有周期文件的问题。正式根和 staging 均存在、可写，同设备号 `16777244`；本次可用空间为 `2756617609216` 字节，属于当时读数，不是未来空间保证，也未据此虚构文件大小 |
| 相关任务与 sensor | 四个周期 job 和 bootstrap job 均未发现排队／执行中的运行；四个新 sensor 无持久化状态，代码默认 STOPPED。不能把“无状态”说成已有四条显式 STOPPED 记录；正式执行前仍需在加载本次代码的 location 中确认有效停止状态 |
| 既有正式队列 | 当时已核对 `QueuedRunCoordinator`、`concurrency.runs.max_concurrent_runs=1`，四个周期更新任务经队列执行时不会同时运行。四个专用 pool 当时尚未配置；其配置／读回任务现已取消，不再是 E 前提 |

以上 DG 核验完成时间为 **2026-11-18 11:01:27 上海时间**。源数量和最新日期是本轮查询结果；历史无缺口等结论仍来自 §2 已接受审计。本轮未重新请求 Tushare、导出源历史或读取历史 OHLC／量额。

#### 本次快照的初始化规模

| 目标完整历史文件 | 本轮源计数／既有证据推导的输出行数 | 资产有记录分区数推导 |
| --- | ---: | ---: |
| 指数周线 Raw | 8669 | 1793 |
| 指数月线 Raw | 2043 | 424 |
| 指数周线 Silver | `8795+94+1=8890` | 1794 |
| 指数月线 Silver | `2079+22+1=2102` | 425 |

Silver 的 94／22 来自 §2 已审计的科创综指已结束周期，另各一根当期由 DG 日线合成；不重新导出其历史来重复计数。四张来源合计 `8669+2043+8795+2079=21586` 行，四份目标预计合计 `21704` 行；两者差值 118 为科创综指进入 Silver 的 `95+23` 行，并非传输丢失。

分区数沿用已接受历史范围并结合本轮分区计数推导，`N=1793+424+1794+425=4436`，预计物化与 check 结果合计 `2N=8872` 条，不包含 run／step 等正常日志。正式 E 必须从当次传输和转换结果取得实际分区集合与 N，不把本表冻结为代码上限，也不为取得它再扫一次源历史。四文件字节数、正式执行耗时和峰值内存尚未实测，继续按 §9 记录实际结果。

#### 原并发判断的更正

此前把其他运行条件下可能发生的并发覆盖当成本项目当前风险，没有先考虑 DG 全局只运行一个队列任务和每个周期 job 只更新一个资产的实际情况，这是判断错误；随后提出再加四个运行级 pool，也是重复保护。原步骤级 pool 设计、后续四个运行级 pool 建议，以及因此暂停 E 的理由一并撤回，不再要求管理员选择并发粒度。

已核对当前四个 job 的 selection、sensor 的 `RunRequest`、资产更新函数、受控 bootstrap 入口及正式队列配置，并查 Dagster 官方[运行队列限制](https://docs.dagster.io/guides/operate/managing-concurrency/run-queue-limits)：正式更新任务沿用现有全局队列即可；bootstrap 按原维护窗口单批执行。原并发测试属于旧设计的隔离结果，不证明当前存在并发错误，也不要求重跑或补一套新的并发测试。

#### E 仍需完成的任务

按修正后的 §11.2，E 仍需完成执行范围确认、两项已固定的单码真实组件请求、四文件初始化及实际 N／2N 补录、经正式队列执行两项 Silver 手动日更，以及正式 Raw 覆盖原 Silver 分区；不再设置或读回四个 pool。这些工作不能用本轮只读审计替代。正式代码 location 的加载状态、队列启动参数与实例仍在 E 执行清单中列明，不在本轮重载或启动服务。

若初始化仍取截至 `2026-11-17` 的快照，手动日更应明确目标 T：同为 17 日只证明同日重跑，跨日刷新须等后一个交易日的 DG 日线成功及原检查通过后再验证；等待期间不额外下载日线。源截至日若变化，只更新必要的当前日期／窗口和实际执行计数，不重做 §2 历史审计。失败按原规则人工处理；bootstrap 重试为新的独立原生运行，最多重放四文件及当批 `2N` 结果，开销不能算作免费续跑。

**更正后的结论：本节审计时业务数据与存储前提齐备，不能把额外 pool 的粒度当作 E 阻塞项。执行选择现已确认；按 §11.12 清理旧代码和测试、完成必要回归后，即可准备 E 的具体执行清单，正式执行仍须按阶段授权。F 的 sensor 启用继续单独审批。** 本节只读审计没有执行初始化、正式任务、动态分区／事件写入或 pool 配置，没有启用 sensor。

### 11.12 已确认的队列执行方式与代码清理安排（2026-11-18）

管理员先确认采用 §7.4 的选择并要求只修正原方案与 LLD，随后授权“提交方案和 LLD，再清理代码和测试、必要回归及独立审计”。本节是先行提交的清理设计依据，方案修正提交为 `0ff2458ce`；以下目标、范围和验收要求保留，实际完成结果见 §11.13。两步均不包含正式数据写入或 sensor 启用。

#### 当前依据与后续改动范围

正式 instance 已有全局单任务配置；四个周期更新 job 各选择一个资产及随写入检查，sensor 只返回 `RunRequest`，实际资产更新函数顺序调用一次对应 writer。CodeGraph explore 已定位四个 job 与 sensor 入口，当前源码及引用搜索确认旧 pool 的依赖仅在下表范围；不涉及财势乾坤 API／前端、Prod、通用下载组件或其他数据集。

| 后续代码清理位置（相对 `lake_console/orchestrator/`） | 需要完成的工作 |
| --- | --- |
| `src/orchestrator/defs/assets/index_period.py` | 移除四个资产的 `pool=` 绑定，保留资产、分区、检查、配置、血缘及 writer 调用 |
| `src/orchestrator/defs/run_contracts/index_period.py` | 移除只为这四个绑定提供名称的 `raw_pool`、`silver_pool` 属性；保留代码名单、周期键、业务配置和运行窗口 |
| `tests/test_index_period_contracts.py` | 移除对应 pool 断言；Silver 原合并断言仍保留分区断言，其他字段、单位、路径及下载组件合同测试不因清理删除 |
| `tests/test_index_period_concurrency.py` | 删除该专门验证四 pool 的测试文件；不将其中线程／进程协调逻辑迁入生产实现，不另造并发压力测试 |

其余四个 job、四个 sensor、两个分区集合、四个业务 check、四份文件和 bootstrap 的每批原生运行设计均按已确认口径保留。正式 instance、全局配置、pool 存储、Lake 和事件不在本次代码清理写入范围；不新增队列提交器、状态表、配置字段、锁或直接执行四个更新 job 的入口。现有正式 pool 未设置的只读记录已在 §11.11 保留，无需为清理再查库或执行删除。

#### 失败、开销与验收

代码清理只删除额外限制和相关测试，不改变失败行为：下载／计算／写入中断仍失败，运营补齐上游后从原 job、原分区人工重跑；bootstrap 重跑仍创建新原生运行，不增加自动恢复或备份。正式业务的请求、文件、事件及重试开销继续采用 §9，本次不因清理新增源请求或正式数据读写。

后续清理使用现有 `.venv`，不安装或同步依赖，在工程外临时目录运行 §11.1 保留的五份指数周期业务测试；检查字段／单位、分区归属、历史保留、日更与正式覆盖、失败及人工重跑、DG 日线零重复请求仍成立。配合修改文件 Ruff、现有 Definitions 静态验证和必要受保护静态门禁，核对旧 pool 属性／绑定的实际引用已清零；不新增生产 check，不反复运行已通过且未受影响的测试，不重复历史审计。若失败，按失败位置修正并重跑受影响用例，不以放宽业务断言消除失败。既有全局治理缺项继续单列，不得称全绿。

清理及验证都只使用临时资源，不启动正式任务；临时测试文件与事件开销沿用现有夹具，不新增并发压力样本或正式资源探测。测试秒数和清理后通过项数尚未测得，不从原 123 项直接推定新结果。最后验收复用本次测试结果及引用搜索，不再读一遍来源历史或执行整链正式重算。

**本节编写时只完成方案与 LLD 修正，代码清理及回归尚未执行；随后方案已先提交，清理与验收已按本节完成，见 §11.13。** 本节不构成提前运行 bootstrap、job 或启用 sensor 的授权。

### 11.13 代码清理、必要回归与 E 开工独立复审（2026-11-18）

管理员授权后，先仅提交原方案与 LLD 为 `0ff2458ce`，未推送；随后在当前 `dev-interface` 清理 §11.12 列出的四个代码／测试文件。没有修改正式配置、其他数据集、下载组件、文件 writer、分区或业务检查。

| 已确认要求 | 实际修改及验收证据 |
| --- | --- |
| 删除额外并发限制 | `assets/index_period.py` 仅删除四个 `pool=` 参数；`run_contracts/index_period.py` 仅删除 `raw_pool`、`silver_pool` 两个命名属性。复审逐项对照提交前源码／语法树，确认没有夹带计算、配置、血缘或写入行为变化；源码及测试的旧属性／命名／专测引用已清零 |
| 删除专门并发测试，保留业务断言 | 删除 `test_index_period_concurrency.py`；`test_index_period_contracts.py` 删除 Raw 的 pool 断言，Silver 原合并断言仍保留分区检查，并将其测试名中的 pool 去除。其他业务断言未删减，没有新增压力测试、生产 check 或替代限制 |
| 保留四资产／两套分区／四检查及停止状态 | 重新加载实际四资产，确认 pool 均为空，周／月动态分区名称未变，各仍有一个同分区 blocking file_contract check；四个 sensor 代码默认 STOPPED、600 秒。完整 Definitions 加载通过；未读取或修改正式 sensor 持久化状态 |
| 既有正式队列与维护方式 | 只读取正式 `dagster.yaml`，确认仍为 `QueuedRunCoordinator`、全局 `max_concurrent_runs=1`；源码核对四 job 各只选择本资产及其随写入检查，sensor 仍通过 `RunRequest` 编排。人工重跑按 §7.4 经正式队列，bootstrap 仍按原维护窗口单批执行，没有新增直接执行入口 |
| 已确认业务口径继续成立 | 五份指数周期业务测试实际 **118 passed**，耗时 **15.53 秒**，覆盖既有 Raw 下载替身、临时文件 writer、分区／check 原生关联、DG 日线生产者及周期更新、正式值覆盖、历史保留、失败与人工重跑、bootstrap 原生事件和 sensor 门禁。网络、Prod、正式根和 instance 均被隔离；该结果不是正式源或 E 运行验收 |

上述整体测试后，仅将已不含 pool 验证的 Silver 测试重命名，并运行该测试的两个频率用例，**2 passed、0.83 秒**；属于原 118 项子集，不另加为 120 项。受保护启动器完整运行 `test_run_contract_static_gates.py`，**113 项通过**；修改文件 Ruff 默认规则、项目致命错误基线、文档／本地链接及 diff 检查通过。现有 `.venv` 的 `dg check defs --use-active-venv --no-check-yaml` 在本任务临时 `DAGSTER_HOME` 下返回“All definitions loaded successfully”，没有安装／同步依赖或加载正式 instance。

测试完成后另行对照 §7.4、§7.5、§11.12 和实际差异复审，核验旧引用、四资产定义、job／sensor 入口及队列配置。CodeGraph explore／impact 覆盖命名属性和指数周期入口，实际引用搜索补足动态调用；删除专测后执行 `codegraph sync`／`status`，索引正常且已更新。没有跨工程合同、API 或前端消费者变更；正式队列的实际任务运行与代码 location 加载验收仍是 E 的执行事项，未在本轮冒充已运行。

性能及数据边界：本轮 Prod／Tushare 请求为 0，正式行情读取和写入为 0，正式分区／事件／pool 写入为 0。测试及定义验证只在 `/private/tmp/dg-index-period-pool-cleanup-20261118` 与受保护启动器创建的临时隔离目录中执行；全局单任务配置只读未改。§2 历史审计及 §11.11 的来源／当期日线证据未重复读取，仍明确使用原时间范围，不将旧数量称为本轮新测结果。

本次没有改变 Catalog 或检查关系，未重复运行此前已因 `gold_major_index_quantitative_structure` 未登记而失败的全局检查治理套件；其失败记录继续保留，不能将本次范围内通过说成全局治理全绿。

**独立复审结论：本轮清理符合已修正方案，未发现未处理的本次范围问题，具备进入 E 的开工条件。** E 执行时按 §11.2 列明具体实例、来源投影、目标日期、读写范围和命令，确认当时的代码 location、目标文件及维护窗口；沿用已有历史审计，不重审历史完整性。两项最小真实组件请求、四文件正式初始化与实际 `N／2N`、两项手动日更及正式 Raw 覆盖仍由 E 完成，未完成的 E 工作不倒算为开发缺陷。本轮不启动 E，不写正式数据或事件，不启用 sensor；代码清理及本次收尾记录尚未提交。

### 11.14 E 正式执行范围与步骤（2026-11-18，执行前）

管理员已授权推进 E 并在完成后审计；本次不进入 F，四个新 sensor 保持停止。采用 §11.13 已通过的代码与隔离回归，不重跑开发测试，不重复 §2 历史完整性、连续性或单位审计。正式写入前完成下述只读现状确认；若出现与既定来源或业务口径冲突，先报告，不改公式或加兜底。

#### 实例、来源和目标

工作目录固定为 `/Users/congming/github/goldenshare/lake_console/orchestrator`，使用现有 `.venv/bin/python3 -B`；正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，当前 GraphQL 为 `http://127.0.0.1:3000/graphql`，repository 为 `orchestrator / __repository__`。先只读确认实际 code location、四 job／资产／check／sensor 定义、全局单任务配置及活动运行；不为读状态初始化 instance，不启用 sensor。若 location 未加载当前定义，仅重新加载该 location，不重启 DG 或其他服务。

对象固定为 `000001.SH`、`399001.SZ`、`399006.SZ`、`000688.SH`、`000300.SH`、`000905.SH`、`000852.SH`、`899050.BJ`、`000510.SH`、`000016.SH`、`000680.SH`。bootstrap 来源投影沿用 `prod_db/index_period.py`：

| 来源 | 对象与历史读取范围 | 字段与处理 |
| --- | --- | --- |
| `raw_tushare.index_weekly_bar`、`raw_tushare.index_monthly_bar` | 上述十一代码的已有全部周／月记录，各表一次流式传输 | `ts_code, trade_date, close, open, high, low, pre_close, change, pct_chg, vol, amount`；仅日期按已定 Raw 表示转换，数值原样保留，不读辅助载荷 |
| `core_serving.index_weekly_serving`、`core_serving.index_monthly_serving` | 上述名单排除 `000680.SH` 的十个代码，已有全部周／月记录，各表一次流式传输 | `ts_code, period_start_date, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount`；按已定单位和精度进入 Silver，科创综指已结束周期复用同批 Raw |
| DG 指数日线 Silver | 只读 Serving 当前截至日所在周／月的开市日文件，过滤本次十一代码；bootstrap 当前合成只需科创综指 | 复用现有日线字段，不请求或导出源日线，不扩大历史日线范围 |

§11.11 的来源统计为 21586 行、预计四文件 21704 行，预计 `N=4436`、`2N=8872`；这是已有审计范围估算，正式执行以当次传输、候选检查及分区分组结果为准，不额外做一轮全历史统计／重算。管理员已明确批准本批四表的指定代码全部已有历史、仅上述业务字段、每表一次搬运，以及初始化和六次手动更新所需的四份 DG 完整历史文件读取；不扩展为额外全历史重算或比对。批准前完成的仅为元数据查询及两项单期最小真实取数。

四个目标为 `/Volumes/datasource/data_lake/{raw,silver}/{index_weekly,index_monthly}/full/part-000.parquet`；四个候选为 `/Volumes/datasource/data_lake_staging/<native_run_id>/index_period/<layer>/<dataset>/part-000.parquet`。不使用旧湖、备份或 Kopia；候选使用正式 check 语义完整校验后逐文件 `os.replace()`。全局读取的必要性是第一次生成已确认范围的四份完整历史文件，不能用抽样替代搬运；后续只做必要 footer 计数、运行／事件汇总和少量周期样本，不追加全历史金融比对。

#### 命令、执行顺序与验收

临时命令输入、日志和验收证据放在 `/private/tmp/dg-index-period-e-20261118`，结果最终落回本文。正式前置以本次查询结果确定 Serving 实际截至日 T，不把此前 `2026-11-17` 冻结为未来输入。当前周／月分区 P 按该 T 与现有日历取得；已结束周期的手动正式覆盖范围固定周 `2026-11-13`、月 `2026-10`（实际期末 `2026-10-30`）。

1. **只读确认。** 使用 `curl --fail-with-body -sS http://127.0.0.1:3000/graphql -H 'Content-Type: application/json' --data-binary @/private/tmp/dg-index-period-e-20261118/<query>.json` 查询已加载定义及状态；必要原生运行／check 查询复用 `daily_basic_event_instance(writable=False)`。Prod 日期元数据通过仓库根的 `bash scripts/psql-remote.sh -f /private/tmp/dg-index-period-e-20261118/<metadata>.sql -- -A -t`，事务只读，只返回十码各频率最新日期及科创综指 Raw 最新日期。确认目标文件、挂载、同文件系统、剩余空间、四 sensor 有效停止、四周期 job／bootstrap 无活动运行和所需 DG 日线已成功。不进行历史行情明细读取。
2. **最小真实组件。** 按现有 `download_index_period_rows` 的公开组件调用方式，周线 `000680.SH / 2026-07-03`、月线 `000680.SH / 2026-10-30` 各一个完整 `BY_OBJECT_POINT` unit；通过 `.venv/bin/python3 -B /private/tmp/dg-index-period-e-20261118/source_probe.py` 调用同一组件并读取 session summary，复用现有连接配置，不另写 HTTP／分页。每项正常一次响应、一行、完整十一字段；只记录请求身份、数量和状态，不记录 token。不重复源接口的历史资料审计。
3. **正式初始化。** 全局历史读取获具体批准且现状满足后，运行 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B -m orchestrator.defs.bootstrap.index_period_history_cli --operation-id index-period-e-20261118 --apply`。本批独立原生运行承载四文件和历史分区物化／check；一次转换与检查，批量注册两套键，事件按实际 N／2N。只读汇总该 run 的成功状态、四文件 footer／计数、分区数量、物化与检查数量及有限期末样本，禁止按 N 次深扫 readiness。
4. **正式队列手动日更。** 使用 Dagster 官方 `launchRun` GraphQL mutation，selector 固定上述 repository 与对应 Silver job，tag `dagster/partition=P`；`runConfigData` 由既有 `build_index_period_silver_run_config` 生成 `mode=daily, trade_date=T`。两频率逐项提交并等待原生成功，检查分区／实际截至日、本次关联 blocking check、完整文件计数及必要历史样本。若 T 与初始化相同，只证明同日重跑及真实合成链路，不宣称已验证跨日刷新；跨日实证在后一个交易日日线完成后取得，不为制造日期变化篡改初始化数据。
5. **正式 Raw 覆盖。** 经同一正式队列依次提交周线 Raw `2026-11-13`、同周 Silver `mode=period`，再提交月线 Raw `2026-10`、同月 Silver `mode=period`。Raw config 为空，Silver config 由既有 builder 生成；每项成功后再执行下一项。两项 Raw 正常共 `2×11=22` 个 unit，北证 50 合法空，其完整 Silver 合成结果保留。确认晚到 Raw 后相同 P 可另行覆盖、check 原生关联正确、当前周／月及少量其他历史样本保留；不执行 sensor evaluation 冒充自动覆盖。

两项最小组件取数加两次 Raw 正常更新，合计正常 24 个 HTTP unit 请求；单点分页及错误重试继续用现有组件，实际请求数以 summary／运行结果为准。两次 Silver 日更的日线源请求为 0；其窗口输入与完整文件读写预算按 §9，不重复计算历史行情。初始化最多四次候选提升及当批 `2N` 结果；之后四个覆盖任务、两个日更任务各更新自己的一个文件和一个目标分区，正常共六个队列 run。文件大小、正式秒数和事件补录耗时尚未实测，执行时记录，不沿用人工压缩样本作保证。

失败或中断直接失败，不自动重试业务任务；原生 run／已提升文件保留，按原范围人工处理。重试 bootstrap 使用新原生 run ID，最多重做四文件及 `2N` 结果；单个队列任务人工重跑只重复该频率／模式，其他已成功结果保留。最终验收复用本批候选结果与原生运行证据，只做汇总和有界读回，不再读取 Prod 全历史，不新增生产 check／pool／状态表。四 sensor 保持停止；本节记录执行准备，不预填 E 已完成。

#### 已完成的 E 前置与最小真实请求

| 项目 | 实际结果 |
| --- | --- |
| 组件真实接入 | `index_weekly / 000680.SH / 2026-07-03` 与 `index_monthly / 000680.SH / 2026-10-30` 各完整交付一行、十一字段、一个 unit；各请求一次、重试 0，`download_complete=true`。session 实测分别 0.161572、0.121328 秒，仅是本次样本，不作为后续耗时保证 |
| 当前来源日期 | 通过只读脚本返回 22 条日期元数据；两频率十码 Serving 均截至 `2026-11-17`，科创综指 Raw 周／月最新为 `2026-11-13`、`2026-10-30`。未重新读取历史行情明细或重复完整性审计 |
| 当前 DG 前置 | 两项基础交付就绪，`2026-11-17` 指数日线成功及四项关联 checks 通过；当前周键 `2026-11-20`、月键 `2026-11`。周需要两个开市日、月需要十二个开市日，合并读取 132 个代码／日期组合，缺文件／缺组合／重复均为 0；正式四目标均不存在，相关四 job／bootstrap 无活动运行，正式根与 staging 同文件系统可写 |
| 正式 location | 初次查询尚无四个周期 job／sensor；按本节重新加载 `orchestrator` 后四 job 可见，四 sensor 的代码默认和有效状态均为 STOPPED。限定四 asset key 查询确认 pools 均为空、两套动态分区正确、各有一个 blocking file_contract check。仅加载定义，没有执行 sensor evaluation 或启动任务 |
| 执行准备 | 受控 CLI 默认范围输出已生成，不带 `--apply`，未连接或导出历史；六个正式队列请求文件已按实际 T／P 和既有 typed config 生成，尚未提交 |

临时就绪脚本首次因路径函数导入位置写错，在连接／读取前失败；按当前 `io/index_period_writer.py` 的真实定义修正后完成上述只读核验，没有改业务代码或以兜底绕过错误。

管理员已回复“批准上述历史读取范围”，本批按上述边界进入正式初始化及六个手动任务。E 的完成验收和最后审计在任务完成后进行，不预填通过。本次此前源数据和运行状态的完整只读结果保留在本节列明的任务临时目录，正式结论以本文为准。

### 11.15 E 首次初始化失败审计与修复建议（2026-11-18）

为了完成 E，需要先保证合法的 Prod 小数在批量搬运中按既定精度进入临时来源表，再继续已确认的四文件初始化和手动更新。本次只执行了首次初始化，随后按“失败直接失败、人工重跑”的规则停止；没有自动重试或继续后面的六个任务。

#### 实际结果与影响

正式运行 `b94be1a7-85a5-445d-8450-03d4ab0413b9` 的状态为 **FAILURE**。失败位于 `bootstrap/index_period_history.py:load_prod_index_period_relation`，正在装载第一项来源 `raw_tushare.index_weekly_bar`，错误为 `Casting value "1011.3470" to type DECIMAL(7,4) failed: value is out of range`。尚未进入其余三项来源及四候选生成流程；本次成功搬运的行数未形成结果，不将预计 21586 行写成已完成数量。

| 失败后审计项 | 实际结果 |
| --- | --- |
| 正式行情文件 | 四个目标均不存在，没有正式行情提升或覆盖 |
| 候选 | 本 run 的 `data_lake_staging/<run_id>/index_period` 目录不存在 |
| 历史资产结果 | 本 run 的物化、check evaluation 均为 0；原生日志只有启动、执行失败、运行失败等六条运行事件，没有补绿灯 |
| 动态分区 | `cn_a_index_week_ends`、`cn_a_index_months` 均为 0 个键，没有历史分区登记 |
| 后续任务／自动化 | 六个手动任务未提交；正式 GraphQL 复核四个 sensor 有效状态均为 STOPPED，没有进入 F |

上述核验只读取本 run 的状态／事件计数、两套分区数量、目标路径存在性及四 sensor 状态；没有再次导出 Prod 历史，没有清理失败记录或写入回滚数据。

#### 原因与此前验收的范围

目标 Raw 字段合同已明确采用价格／涨跌点位 `DECIMAL(18,4)`、涨跌幅 `DECIMAL(10,4)`、量额 `DECIMAL(20,4)`，并未声明 `DECIMAL(7,4)`。实际 loader 先用 `pd.DataFrame.from_records` 保存 Python Decimal，再向 DuckDB 注册该 DataFrame；DuckDB 在执行目标 SQL 的显式 CAST 之前，先对 DataFrame 的 object 数值列取样推断输入类型，类型过窄时就在输入扫描处失败，后面的合同 CAST 无法补救。

已核对当前 DuckDB **1.5.2**，其 `pandas_analyze_sample` 的当前值为 **1000**；官方[DataFrame object 列说明](https://duckdb.org/docs/2.0/clients/python/data_ingestion)描述了这种取样推断及 `Failed to cast value` 失败。此处属于搬运实现错误：不应让抽样代替已知来源合同决定小数精度。此前两行一批、量额同量级的隔离样本未覆盖同一批后部出现更大合法数值的情况；原 118 项隔离测试及两个真实组件请求仍只证明其实际覆盖范围，不能证明完整 Prod 历史搬运已验收。

#### 已确认的修复范围

管理员已明确同意“修复并重跑 E”，包含下述两个文件的修复及回归，并在通过后使用新原生运行重读原四表指定十一／十码历史各一次，继续原六个手动任务；四个 sensor 保持停止。不是自动重试原失败运行，也不复用其 ID。

1. 仅修改 `bootstrap/index_period_history.py` 的批次输入转换：每批 Decimal 按不丢精度的文本传给 DuckDB，再由现有来源 schema 的显式 CAST 解析为已声明类型。继续分批、列式传输，不转 float，不改 Raw／Prod 来源／DG Silver 类型、单位或输出字段；不扩大全局抽样数，不升级或安装依赖，不增加兜底／新 helper／新入口。
2. 在 `test_index_period_bootstrap.py` 为同一输入批次增加“前部数值较小，后部出现 `1011.3470` 等更大合法小数”的回归，用 Raw 和 Serving 各自真实字段合同及独立字面预期验证；先证明旧 loader 因本次错误失败，再证明修复后精确装载。保留既有源最大值、精度、单位换算、失败不提升和新原生运行重跑用例，不删除或放宽断言。
3. 修复及验收只使用人工有界批次和现有临时资源，优先运行受影响 bootstrap／合同测试及修改文件检查；没有新变化不重跑所有已通过的 sensor 测试，不读取真实历史来反复试错。测试规模由本机已核实的采样行为和复现所需行数确定，不制造新的业务数值限制。

编码前已在本机隔离内存连接复现：默认采样 1000、输入 2000 行、索引 1001 的合法 `1011.3470` 未进入类型样本，输入被识别为 `DECIMAL(7,4)` 并出现与正式失败相同的错误；同一输入用精确文本传递、原类型 CAST 可完整读取。2000 行及该位置是本次已复现的测试条件，不作为生产批次或业务阈值；不调整生产采样设置。新增 Raw／Serving 回归使用该条件和独立字面预期，先运行旧实现确认失败，再修改 loader。此前 1001 行且把大数放最后的人工探测未触发错误，不将其误写为成功复现，也不修改预期迎合该探测。

建议修复不改变指数周月线的业务口径，也不扩展到其他采用 DataFrame 的数据集。当前执行与代码存在这个实际缺陷，按修复流程先确认并落地修复，再人工启动新的原生初始化运行；原失败 run 保留，不复用其 ID。人工重跑仍只搬运既定四表、指定十一／十码及原字段集合，每表一次，其中指数周线 Raw 将再次读取；开销为一次新的四文件初始化和实际 `2N` 结果，失败尝试的耗时和读取不能记为免费续跑。

**本次失败审计的结论是 E 未完成，不能进入 F。** 当时尚未修改 loader 或测试，也未再次发起历史读取。管理员随后已批准修复及人工重跑；后续实施与结果见 §11.16，不以本节失败记录覆盖后续实际状态。

### 11.16 小数搬运修复及 E 人工重跑（2026-11-18）

目标和范围沿用 §11.15 已确认修复及 §11.14 的 E 执行清单。仅修改 `bootstrap/index_period_history.py` 的 DataFrame 数值输入为 StringDtype，随后仍使用原来源 schema 的显式 CAST；Raw／Serving 读取范围、DG Silver 单位及精度、分批边界和正式写入逻辑均未改变。对应 bootstrap 测试补充 Raw／Serving 两个同批大数回归，不扩展到其他数据集。

先在旧实现运行新增两项回归，均因输入被推为 `DECIMAL(7,4)` 失败；修改后运行 `test_index_period_bootstrap.py` 与 `test_index_period_contracts.py`，**30 passed、4.31 秒**，包含同两项回归、原有最大量额／来源精度／单位和原生初始化测试。2000 行人工批次中的大数及量额上限使用独立字面预期；没有改变预期迎合错误实现，没有读取真实历史做回归。修改文件 Ruff 默认规则、项目致命错误基线通过。CodeGraph explore／impact 和引用核对表明修改只进入该初始化装载函数及其调用链，不影响日常 Raw／Silver、API 或前端；正式取数、文件与事件验收结果见本节下文。开发后 CodeGraph sync／status 已完成，索引为最新。

人工重跑命令为：在原工作目录使用 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -B -m orchestrator.defs.bootstrap.index_period_history_cli --operation-id index-period-e-20261118-retry1 --apply`。新运行 ID 由 Dagster 生成，保留原失败 run；仅重读原四表指定十一／十码历史各一次。先确认四 sensor 仍停止、目标文件仍不存在且无执行中 DG 任务，再启动。后续原六个手动任务仍经正式队列逐项执行，不使用直接执行脚本绕过队列，也不进入 F。

本次重跑的请求、候选／文件／事件、失败及人工重跑开销沿用 §9、§11.14；不把首次失败开销算为免费续跑，不增加源点查、全历史重算或连续性审计。两个已通过的真实组件点请求继续复用，不重复请求。修复测试只使用 `/private/tmp/dg-index-period-e-20261118/repair-tests` 及隔离内存资源；正式执行日志、汇总和有界读回仍放在既有 E 临时目录。

#### 正式初始化结果

新原生运行 **`89b380b3-18f4-48d0-ab15-1b85d08e8db4` 为 SUCCESS**。四来源按固定十一／十码和原字段投影各读取一次；loader 对每项传输行数与临时表行数进行核对，四候选通过原合同检查后逐文件提升。最终输出如下，后续六个手动任务未改变这些文件的总行数。

| 正式完整历史文件 | 行数 | 文件字节数 |
| --- | ---: | ---: |
| `raw/index_weekly/full/part-000.parquet` | 8669 | 483474 |
| `silver/index_weekly/full/part-000.parquet` | 8890 | 514482 |
| `raw/index_monthly/full/part-000.parquet` | 2043 | 118115 |
| `silver/index_monthly/full/part-000.parquet` | 2102 | 124577 |
| 合计 | 21704 | 1240648 |

实际初始化 `N=4436` 个资产／分区结果，补录 **4436 次物化、4436 次检查，共 8872 条这两类事件**；不把该数说成全部运行日志或 PG 表行数。两套动态分区分别为周 1794 个键、月 425 个键；这是四个资产共用的键集合，不与 N 混为一谈。原生运行从开始到成功实测 **154.696 秒**，包含文件初始化及事件补录，不把它单独归为事件补录耗时。来源总行数 21586 继续保留为 §11.14 的前置统计，本次 CLI 未另行输出四来源行数汇总，不将旧统计冒充本轮独立实测。

#### 六个正式队列任务结果

六项均通过既有 `launchRun` 入口逐项提交，每项均有一次原生入队记录，前项成功后再提交后项。以下耗时为原生 run 的开始至结束，包含本次资源与执行开销，不含人工等待或排队时间，不作为性能保证。

| 顺序／任务 | 分区／实际截至日 | 原生 run ID | 结果／实测秒数 |
| --- | --- | --- | --- |
| 1 指数周线 Silver 日更 | `2026-11-20`／`2026-11-17` | `c9be7b1e-6ed3-4bd1-8522-6dc1c7c668fb` | SUCCESS／2.811 |
| 2 指数月线 Silver 日更 | `2026-11`／`2026-11-17` | `cc05217a-3d69-45a1-8d55-02cf34a3b322` | SUCCESS／2.827 |
| 3 指数周线 Raw 正式更新 | `2026-11-13`／`2026-11-13` | `95c0e76c-aeba-4d90-ba0f-8388ac5d601f` | SUCCESS／5.162 |
| 4 指数周线 Silver 正式覆盖 | `2026-11-13`／`2026-11-13` | `6944f78d-dc91-4b74-9210-612763a7dac3` | SUCCESS／2.778 |
| 5 指数月线 Raw 正式更新 | `2026-10`／`2026-10-30` | `9202f18f-c3c4-44d2-8d78-b2d09371474a` | SUCCESS／5.221 |
| 6 指数月线 Silver 正式覆盖 | `2026-10`／`2026-10-30` | `95570834-97e1-4bf7-b0a6-3b2e585498ad` | SUCCESS／3.366 |

两项日更均只读 DG 指数日线 Silver：周为 2 个开市日文件、22 行；月为 12 个开市日文件、132 行，各输出当前分区十一行，日线源请求为 0。两任务累计逻辑输入 154 行，其中周窗口与月窗口重叠，不能称为 154 个独立代码／日期组合；前置合并范围为 132 个组合。

两项正式 Raw 分别交付十行，北证 50 合法空；对应 Silver 各十一行。正式覆盖任务携带现成规则生成的消费 run key，分别对应 Raw 批次 `raw_index_weekly:2026-11-13:958c1ba2522f`、`raw_index_monthly:2026-10:bcea4c0e2010`；没有新增消费状态表。两项 Raw 的正常请求量仍为 `2×11=22` 个 unit，加两项已完成组件点查为正常 24 次的推导；Raw 物化汇总不含 HTTP 尝试／重试统计，不能据此声称实测请求数或实测重试为零。

#### 完成后的独立审计与验收边界

执行完成后对照当前 loader、Prod 固定投影、Silver 单位转换和合并代码及原生运行结果，完成下列必要验收；没有再次导出 Prod 历史、全历史重新计算或逐分区循环深查。

| 验收对象 | 实际证据与结论 |
| --- | --- |
| 小数搬运 | 原问题的 Raw／Serving 两项回归在旧实现失败、修复后通过；正式四来源搬运和四文件生成成功，字段类型保留原合同，未转为 float |
| 物化、分区与 check | 初始化及六任务合计 **4442 次检查**，均成功；按当批原生记录汇总关联，每项 check 对应同一 run、同一 asset、同一 partition 的真实物化；六手动任务各只有一次物化和一次 blocking check，未补造无归属绿灯 |
| 正式值及单位 | 有界读回周 `2026-11-13`、月 `2026-10-30`：各十条 Raw 对应 Silver 的点位、涨跌点位一致，涨跌幅 ×100、成交量 ×0.01、成交额 ×0.001 精确一致；Raw 股／元／比例，Silver 手／千元／百分数，量额分别保留 6／7 位小数 |
| 合成及保留范围 | 两频率当前分区各十一条截至 `2026-11-17` 的合成记录在正式覆盖后保持不变；北证 50 对应已结束周期记录与初始化读回相同；四文件各两个历史上证指数样本与初始化一致，总行数不变。该结论是有界样本、计数及既有合并回归的证据，不声称全历史逐行比对 |
| 失败记录及自动化 | 原失败 run `b94be1a7-85a5-445d-8450-03d4ab0413b9` 仍为 FAILURE，新初始化与六手动任务分别为 SUCCESS；正式 location 为 LOADED，四个新 job 可见，四 sensor 代码默认及有效状态均为 STOPPED，没有执行 sensor evaluation 或启用自动更新 |

**E 按获批手动范围完成，未发现本阶段剩余阻断项。** 两项日更截至日与初始化相同，证明真实 DG 日线接入、同日合成及重跑；正式覆盖证明成功 Raw 可进入原分区并保留其他周期和北证 50。尚未验证跨日推进，也未制造“同一周期当天先合成、源正式发布后自动覆盖”的时序；这些正式自动运行证据留在 F，不能用此次旧周期手动覆盖代替。四 sensor 继续停止，未进入 F；本次修复和收尾记录随本次提交归档。

### 11.17 F 启用前审计及执行安排（2026-11-19）

目标是在已完成 E 的四份正式指数周月线文件上启用原四 sensor，使当日 DG 指数日线成功及四项原检查通过后自动刷新当期，并在正式周期 Raw 到达后覆盖其原分区。管理员已授权推进 F、严格按本文执行并独立审计；本节不改变单位、对象、公式、下载组件、分区、19:00–00:00 窗口、600 秒最小间隔或既有全局单任务队列。F 不包含再次 bootstrap、Prod 历史读取、全历史重算、修改源码、财势乾坤 API／前端接入。

#### 判断标准、当前代码与实际前提

1. **启用成立**：正式 location 加载原四 sensor／job，四 sensor 有效状态为 RUNNING；代码默认 STOPPED 可以保留。开启状态与 daemon 实际 tick 分别核对，不能仅凭 mutation 返回成功声称已自动运行。
2. **自动日更成立**：真实交易日 T、上海时间 19:00 至零点前，日线未齐时等待；DG 日线原生生产 run 成功、四项关联检查通过且当日十一代码齐备后，sensor 才提交正确的周／月分区及 `mode=daily, trade_date=T`。任务经原队列成功、check 对应其真实物化，当前分区十一代码截至 T，后续 tick 不重复同一 P＋T。午夜和 19:00 前没有当日日线属于正常情况，不判为源缺失或同步失败。
3. **期末自动覆盖成立**：周 Raw 在该周最后开市日探测正式发布；月 Raw 按现行规则在次月首个开市日探测上月正式值。只有实际发布、Raw 原生 run／check 成功、新批次触发同一原分区的 Silver `mode=period`，且对应正式值读回一致，才标该频率已验收。尚未发生的发布不能以 E 的旧周期手动覆盖代替。

当前依据为 `sensors/index_period_update_job_sensors.py` 的窗口、日历、P＋T／批次去重及四个 sensor 定义，`sensors/index_period_daily_readiness.py` 的日线 run／关联 check／十一代码规则，`io/index_period_writer.py` 的日更接续及完整文件合并，`run_contracts/index_period.py` 的固定配置与 typed config。CodeGraph explore 已追到 sensor → 日线就绪读取；再核对当前 writer 的实际接续条件，不以 sensor 的一次 ready 结论代替能否接续的判断。正式启用使用现有 GraphQL 入口，schema 已按本机 Dagster 1.13.26 核对；不新增生产脚本或配置项。

11 月 19 日凌晨只读核验结果：正式 location 为 LOADED，四 sensor 有效状态均为 STOPPED，SENSOR 与 QUEUED_RUN_COORDINATOR daemon 健康。周分区 `2026-11-20`、月分区 `2026-11` 的十一代码，物理 Silver 与对应成功物化均截至 **2026-11-17**，关联 checks 通过；**2026-11-18 的 DG 指数日线已 ready，缺代码为 0**；19 日日线尚未物化，在凌晨属于正常。SSE 日历确认 18／19 日均开市，因此不是休市造成日期差。

**本次原 F 执行清单遗漏了启用前人工接续停止期间交易日的步骤。** writer 在当前周期要求已有截至日为 T 的上一开市日或 T：若直接等 19 日自动触发，已有 17 日不能跳过 18 日，会报“周月线未接续上一应有交易日”。这由当前文件、日历与代码共同确定，不是仅凭日期较早判断异常；18 日日线已齐也排除了上游尚未完成这一解释。19:00 之前 sensor 直接返回 `outside_window`，不会自动追补 18 日；不能通过改时钟、缩短间隔、制造历史 tick 或放宽接续检查绕过。

#### 已确认的最小执行扩展与后续顺序

在启用前补两次现有 Silver job，是当前最小办法；不增加新入口或新模式，不改变既定业务口径。管理员已明确回复“同意先补18日，再启用四个sensor”，批准两项人工接续、对应两份 Silver 完整文件读写，以及启用后按方案继续读写四份完整历史文件。执行前四 sensor 保持停止；两项人工任务均成功后才启用。

| 顺序 | 操作、目标与边界 |
| --- | --- |
| 1 人工接续周线 | 经原正式队列提交 `silver_index_weekly_update_job`，分区 `2026-11-20`，既有 builder 生成 `mode=daily, trade_date=2026-11-18`；只消费 DG 指数日线，成功及本次关联 check 通过后再继续 |
| 2 人工接续月线 | 同一入口提交 `silver_index_monthly_update_job`，分区 `2026-11`，`mode=daily, trade_date=2026-11-18`；保留其他月份，不重跑 Raw 或 Prod bootstrap |
| 3 启用原四 sensor | 同一正式 instance、`orchestrator / __repository__`，对四个 `raw/silver_index_weekly/monthly_update_job_sensor` 各调用一次 `startSensor(sensorSelector:...)`；重新读取有效状态，保留代码默认 STOPPED，不写 cursor、不运行 dry-run evaluation 冒充 daemon tick |
| 4 观察与有界验收 | 读取每个 sensor 启用后的最新自然 tick 和 cursor，核对当前实际窗口的等待原因与 run IDs；真实 19 日日线完成后再按上面的自动日更标准验收。周／月正式发布分别等待其真实发布日，不制造源数据或重新发送 E 批次 |

工作目录、正式 `DAGSTER_HOME`、GraphQL、四正式文件和候选路径沿用 §11.14；所有临时请求／状态／审计记录放在 `/private/tmp/dg-index-period-f-20261119`。队列提交采用既有 `launchRun` 与 typed config，身份为原 job／P／T；sensor mutation 使用上述 selector，不修改其他 sensor／schedule。正式源码和测试没有变化，复用 §11.13、§11.16 已有测试与 E 真实合同证据；不重跑无关测试或重新审计历史完整性。

#### 读写开销、失败与最后验收

两次人工接续按当前文件统计合计读取并合并 **8890＋2102＝10992 行** Silver 历史，当前文件合计 **514482＋124577＝639059 字节**；这是两份输入文件的当前大小，不是 DuckDB 总 I/O 或候选大小保证。读取完整文件是既定单文件布局下保留其他周期并生成候选的必要步骤，不能仅取当前十一行后覆盖整份文件。日线只读十一代码的当前周 3 个开市日、当前月 13 个开市日，累计逻辑输入 `11×3＋11×13＝176` 行，窗口重叠后为 143 个独立代码／日期组合；月份窗口沿用 E 已验证日历并增加已核实的 18 日。Raw 查询仅限本期，不重读其历史作计算；不连接 Prod，不请求 Tushare 日线。

正常两项人工任务各产生一次物化和一次关联 check，合计四条这两类结果，不另设生产检查。各替换一份完整 Silver 文件，候选检查与原子提升沿用现有代码。E 同类日更实测 2.811／2.827 秒及当前文件大小仅作现有样本，不写成 F 耗时保证。失败或中断保留原生结果和已完成文件，不自动换 key／重提任务、不删除或回滚业务数据，报告后由人工确定重跑；单次人工重跑重复该频率对应历史合并、窗口与一份候选的开销。

启用后的正常自动读写继续沿用 §9 的四份完整文件及本期窗口方式，失败按既定人工处理。最后验收只读四 sensor 的本批状态／有限 tick、相关 run／check、当前分区十一行及必要的已有历史样本；复用 E 基线，不再次全量金融计算或逐行历史比对。凌晨不在窗口时，预期是自然 tick 的 `outside_window` 且无本次提交的业务 run；这只验证启用和窗口行为，不能作为自动日更或期末覆盖通过证据。

**执行前记录：已完成启用前只读审计和本节方案补充，管理员已确认执行扩展；两项人工接续与启用即将按上述顺序执行。** 截至此记录尚无正式 Lake／PG 状态写入，无额外源请求；后续结果另行记录，不覆盖此前事实。

### 11.18 F 人工接续、启用及独立审计结果（2026-11-19 凌晨）

按 §11.17 已确认的扩展，先在四 sensor 停止时通过原正式队列逐项接续 18 日；两项成功并通过本次关联检查后，再启用原四个 sensor。没有直接执行资产、写 cursor、手工执行 sensor evaluation、变更时钟或缩短间隔，也没有再次 bootstrap／读取 Prod 或请求日线。

#### 人工接续的真实结果

| 任务 | 目标分区／实际截至日 | 原生 run ID | 结果与原生执行秒数 |
| --- | --- | --- | --- |
| `silver_index_weekly_update_job`，`mode=daily` | `2026-11-20`／`2026-11-18` | `9ac6242a-a5c4-4436-809f-84639bb91804` | SUCCESS；3.086 秒 |
| `silver_index_monthly_update_job`，`mode=daily` | `2026-11`／`2026-11-18` | `a549c00f-d435-4c27-b3c2-7ee72775d42b` | SUCCESS；2.989 秒 |

两项各有一次原生入队、一次物化、一次成功 blocking check；check 的目标 storage ID／run ID、资产和分区与本次物化一致。持久化 config 均为上述原分区的 `daily / 2026-11-18`，没有用 repair 或期末模式替代。原生 metadata 与实际窗口一致：周消费 3 个 DG 日线文件、33 行，月消费 13 个文件、143 行；来源资产只有 `silver_index_daily`，本链日线下载为 0。

有界物理读回确认，两份 Silver 当前分区各十一代码全部截至 18 日；完整文件总行数仍为周 8890、月 2102，当前字节数分别为 514468、124588。两文件各两个历史上证指数样本、已结束周期的北证 50 记录与 E 基线一致。两份 Raw 文件未由本批人工接续改写。此处验收的是人工跨日接续、实际输入接入及样本保留，不能称为 sensor 自动日更。

#### 启用和首个自然 tick

以下四个原有 sensor 的 `startSensor` 各调用一次成功；正式读取确认有效状态均为 **RUNNING**，代码默认仍为 STOPPED，`minIntervalSeconds=600`，每个目标仍只有其同名 job。首个自然 tick 如下，时间均为上海时间。

| sensor | 首个 tick ID／时间 | 实际结果 |
| --- | --- | --- |
| `raw_index_weekly_update_job_sensor` | `3763662`／`2026-11-19 00:44:00` | SKIPPED，`outside_window`，run IDs 为空 |
| `raw_index_monthly_update_job_sensor` | `3763664`／`2026-11-19 00:44:05` | SKIPPED，`outside_window`，run IDs 为空 |
| `silver_index_weekly_update_job_sensor` | `3763663`／`2026-11-19 00:44:05` | SKIPPED，`outside_window`，run IDs 为空 |
| `silver_index_monthly_update_job_sensor` | `3763671`／`2026-11-19 00:44:11` | SKIPPED，`outside_window`，run IDs 为空 |

独立审计分别核对正式查询返回的 sensor 状态／目标 job、tick 与持久化 cursor：四项决策均为 `skip`、selected_count 为 0、原因与实际时钟匹配；原生 run 查询也确认这四个 job 在启用后尚无新运行。当前代码在窗口判断后才进入基础数据、源发布及 DG 日线就绪读取，因此此批凌晨跳过没有进入这些业务路径；这是代码与真实 tick 的证据，不是对全系统 HTTP 流量的测量。四项首个自然 tick 正常，不能据此证明晚间的去重或正式覆盖已经发生。

#### 本次结论与仍待观察的业务条件

| F 验收项 | 当前结论与下一次实际条件 |
| --- | --- |
| 18 日人工接续 | 已完成并验收，十一代码、目标日、当前周期、队列及本次 checks 均符合方案 |
| 四 sensor 启用 | 已完成，有效 RUNNING；600 秒间隔、原目标 job 不变 |
| 窗口外自然运行 | 首个真实 tick 审计通过，凌晨正确等待且没有提交业务 run；18 日为此时最近已结束的交易日，当前 Silver 截至 18 日正常 |
| 真实自动日更及同 P＋T 去重 | **待观察**。19 日日线在凌晨尚未产生属于正常；需 19 日 19:00 后该日线 run、原四检查及十一代码就绪，再取得两项 sensor 触发的成功 run、物理结果和后续去重 tick，才可标通过 |
| 周线正式自动覆盖 | **待观察**。有界日历确认 11 月 20 日开市，是本周最后一个开市日；待实际源发布后验证 Raw → 同一周分区 Silver。未在 19 日提前请求未来正式值 |
| 月线正式自动覆盖 | **待观察**。有界日历确认 11 月 30 日及 12 月 1 日开市；按现有“次月首个开市日”规则于 12 月 1 日探测 11 月正式值，再验收 Raw → `2026-11` Silver 原分区 |

本批正式变更范围为两个已获批的人工 Silver 日更和四个 sensor 启用；未改其他 sensor／schedule、全局队列、源码、单位、检查或配置项，未安装依赖。补充了现有[资产与 job 拓扑说明](../architecture/dagster-asset-job-topology.html)的四个周期资产、四个 job、分区／完整文件及 check／sensor 对应关系；其运行状态引用本文和正式 instance，不再另存重复运行报告。

**独立审计结论：启用和当前凌晨窗口行为符合预期；F 尚未全部验收，真实自动日更与周／月正式自动覆盖证据仍未取得。** 不用两次人工接续或 E 的手动覆盖证明自动链路，不因日期尚未到来就判失败；保留四 sensor 运行，等待上述真实条件。后续验收继续按既定有界范围读取相关 run／check、当前十一行和必要样本，不重算已有历史。

### 11.20 当期指数周线、月线 Silver 触发条件修复（2026-11-20，源码已修改、未验证）

本次只解决 `929f2825-d1bb-4081-a854-44ba978ab411` 暴露的触发顺序问题。管理员已确认：现有北证 50 日线合成、正式值优先、完整文件合并及 checks 均保留；仅修正周／月共用 Silver sensor 的触发判断，并补对应回归。此前已完成本方案和 LLD 修订并向管理员汇报。管理员随后要求先提交文档、再修复，不重启 DG，也不需要验证；本轮据此修改源码和对应回归用例，但不执行 pytest、Ruff、Definitions 或正式运行验证，不重跑任务、不启停 sensor、不重载正式 location 或写正式数据。

#### 已有证据与原因

复用本次已完成的只读分析，不重新读取源数据或审计历史。11 月 20 日 19:00:52，周线 Raw 运行 `cdd32b24-d478-4cc0-b81b-e75efac93f34` 成功，本期十行且关联检查通过，北证 50 合法空。19:02:37，Silver sensor 在当天指数日线尚未物化、当周 Silver 十一码仍截至 19 日时，提交 `mode=period` 的 `929f2825…`；19:02:45 writer 报“期末Raw缺失且无完整Silver：('899050.BJ',)”。本次没有生成候选、成功物化或检查结果，正式 Silver 未改写。上述日期与当前数据状态仅指该次失败及截至 19:37 的分析证据，不推断后续运行结果。

修复前 `evaluate_index_period_sensor` 在日线未就绪后仍继续读取新 Raw，并可进入 `period_requested`。原 §7.2 将正式覆盖与日更分成两条独立分支，没有区分当期覆盖和旧周期覆盖；我此前设计及验收漏掉了“正式 Raw 先到、当天日线后到”的正常顺序。writer 拒绝不完整北证 50 记录符合原完整性规则，不应修改该判断来消除报错。既有测试 `test_raw_after_daily_overrides_original_partition_and_dedups` 提前准备了完整北证 50 记录，不能证明本次顺序正确。

#### 唯一生产代码改动与影响面

| 硬口径 | 实现位置与处理 |
| --- | --- |
| 只改共用 Silver sensor 判断 | 后续仅修改 `src/orchestrator/defs/sensors/index_period_update_job_sensors.py:evaluate_index_period_sensor` 的 Silver 分支；两个 Raw sensor 分支不改，周／月 Silver 同时使用该修正 |
| 当期不能绕过当天日线／日更 | 保持现有 `index_period_daily_readiness` 和 `daily_requested` 顺序。新增判断放在原 Raw 来源、生产运行及关联检查处理之后，构造 period run key／判断批次已处理之前：Raw 原分区 `original_key == key` 且本 tick 的 `completed` 为假时，不提交 `mode=period`；先等日线运行成功、原四检查通过、十一代码齐备，再沿原分支提交 daily。已有当天日更在排队或运行时沿用 `job_active` 等待；当日日更失败／取消时沿用人工处理，不另发 period 绕过 |
| 当期完成后仍允许正式覆盖 | `completed` 继续采用已读取的当前周期 Silver 成功物化／关联 check 及 `goldenshare/trade_date == today`，不以文件存在、昨日记录或日更刚提交代替。完成后保留原 Raw 成功及关联 check 判断、原批次 run key 和 period 配置 |
| 等待不丢 Raw，失败不自动重试 | 尚未满足当期条件时，保留 `raw_after_storage_id`，不把候选标为已处理、不制造消费 run。沿用本 tick 已有的日线未就绪／日更状态说明。既有 `period_attempt_exists` 及人工重试规则保持；不换 key、不清 cursor，不自动重放 `929f2825…` |
| 旧周期覆盖不新增依赖 | `original_key != key` 时继续原路径；旧周／旧月可以在执行当天日线未完成或当天日更失败时覆盖。目标周期缺完整合成记录仍由原 writer 失败处理，不增加旧周期 readiness helper 或扫描 |

CodeGraph explore 和当前源码核对覆盖：四 sensor 包装入口 → 共用 `evaluate_index_period_sensor` → 原生日线／周期就绪读取 → 原 job → `write_index_period_silver`；对应消费为四个既有 job 中的两个 Silver job，无 API／前端消费者或跨工程接口变更。修复不改 `index_period_daily_readiness.py`、writer、下载组件、资产／job／check 定义、Catalog、schema、单位、分区、文件路径、19:00–00:00 窗口、600 秒间隔或全局单任务队列；不增加 helper、配置项、状态表或生产检查。后续源码改动只落上述 sensor 文件，测试只落 `tests/test_index_period_sensors.py`；本轮文档只改本文。

#### 回归与验收

复用现有隔离 instance、原生物化／检查夹具及 `index_period_test_support.py` 的输入合同；新场景的独立预期取自本次真实顺序：十码正式 Raw 已成功、北证 50 当期记录仍截至上一开市日、当日日线尚未就绪。原生成功和关联检查分别构造，不以 cursor 或 mock 的 ready 布尔值代替全部证据；不改 writer 预期或先补完整北证 50 来绕过失败条件。

| 验收场景 | 必须证明的结果 |
| --- | --- |
| 当期 Raw 先到、当日日线未完成 | 周／月参数化复现，旧代码会错误请求 period，修复后无 RunRequest、无分区登记／业务写入，Raw 批次未被消费。结合既有日线反例覆盖运行未成功、关联检查未通过及缺目标代码，确认均不能绕到当期覆盖 |
| 当日日线正常完成 | 同一场景补齐真实合同所需的当日日线及原生成功／四检查／十一代码后，优先请求原分区 `mode=daily, trade_date=T`；已有周／月 writer 负责已到正式值与北证 50 合成，不能被新条件误拦 |
| 日更完成、正式 Raw 后到 | 沿用并核对既有“日更后覆盖”用例；本次物化及关联 check 成功且截至 T 后，允许原批次 period，保留原周期、原 run key 与后续去重，不因当天已日更而永久挡住正式值 |
| 日更失败与旧周期覆盖 | 当期日更失败／取消不自动重试或转 period；既有 `test_raw_original_month_independent_of_today_daily` 必须继续通过，证明旧月覆盖不依赖执行当天日线；同样核对旧周路径不受当期条件影响 |

上述表格保留为本次修复的回归要求，补写对应用例，不删除或放宽既有断言。管理员本轮明确要求“不需要验证”，因此本轮不运行旧代码复现、新回归、Ruff、Definitions 或正式运行验证；此前“先运行失败用例再修复、运行专项测试”的执行顺序仅对本轮按管理员指令不执行，不能将未运行写成通过。后续确需验收时再按上述场景及现有隔离环境执行，不扩展为无关全套测试。正式数据与真实源边界复用已有 E／F 证据，不重新调用 Tushare／Prod 或重算历史。

#### 读取、写入和失败成本

新增条件只比较本 tick 已有的 `original_key`、`key`、`completed`，状态说明复用已有 `attempt`、`reason`／`missing`。因此新增数据读取、PG 查询、源请求、Parquet 扫描及生产 check 数均为 **0**；这是依据上述既有变量和原调用链的增量推导，不是新的性能实测。原日线门禁仍只读目标 T 的一次物化／生产运行和最多四条原检查，文件读取仍是目标 T 的代码／日期投影，不重复执行门禁；原 tick 预算和每 tick 最多一个 RunRequest 继续适用。

等待不提交任务，不形成新行情文件或物化／check；条件满足后的任务沿用 §9 原读写成本，修复不新增第二遍计算或写入。隔离回归全部使用 `/private/tmp` 下本任务临时资源；不安装依赖、不访问正式凭据。测试失败直接报告，修正本次判断后仅重跑受影响测试；中断后的测试重跑只重建相同隔离夹具，最后验收复用已保存的本次失败证据和隔离结果，不重新承担正式完整历史读写。代码修复与原失败任务恢复分开，未另获明确执行指令不重跑原任务或改变正式 sensor／运行状态。

**实施记录：方案和 LLD 已先提交为 `2213e05f3`。** 随后仅在共用 Silver sensor 的原 Raw 检查通过后、构造 period run key 前增加 `original_key == key and not completed` 的等待判断；当期日更失败／取消仍提示人工处理，等待期间不推进 Raw 游标，旧周期继续原路径。未修改日线合成、writer、下载、资产／job／check、单位、分区、窗口或队列。

对应 `test_index_period_sensors.py` 已补写周／月 Raw 先到时的日线缺失、运行失败、检查未通过、缺代码等待，以及日线就绪后优先请求 daily、完成后允许原批次覆盖、日更失败／取消和旧周独立覆盖用例；两项原有批次／失败去重用例补充“当期日更已完成”的原生夹具前提，原断言保留。按管理员要求，没有运行这些用例，也没有运行 pytest、Ruff、Definitions、正式查询或其他修复验证；未执行 DG 重启／重载、sensor 启停或任务重跑，正式生效情况未核验。源码修改及本段收尾记录随本次提交归档，不将源码修改写成验收通过。

## 12. 本版确认范围与实施约束

业务单位、11 个指数、初始化来源、每日当期更新、运行窗口与失败人工重试已确认。管理员本轮进一步明确：日更从既有 DG 指数日线 Silver 合成，必须在当天日线成功及原 checks 通过后触发；本链不再探测或下载 Tushare 日线。正式周／月线下载复用现成通用组件，不重复开发下载能力。

管理员已确认 **Dagster 按周、月分区，Raw／Silver 每频率各一份完整历史文件**。本版明确为四个资产、两套指数专用周期分区、四个 job、四个同名 sensor、四个随目标分区写入执行的 check；对应关系见 §7.1、§7.2。文件路径保持四份，周／月内每天重复更新同一分区，实际截至日单独记录。

必须同时采用的约束：两个 Silver job 只读 DG 日线窗口，日更去重包含 P 和 T；上游未成功不提前运行；当前 Raw 未到数不阻塞已就绪日线的合成；新 Raw 仍可另行覆盖同一原分区，不被当日已合成挡住；四个更新 job 和人工重跑经既有全局单任务队列执行，取消本数据集额外四个 pool 及其专门并发验收；bootstrap 按原维护流程单批执行，并按分区补录 `2N` 结果。B 已登记两份周期下载契约，真实组件接入及正式运行的后续证据见 §11.14、§11.16。C 来源精度修复已提交 `44b59c121`；D 原开发记录见 §11.10，方案修正已提交 `0ff2458ce`，代码清理、必要回归及独立复审见 §11.13。E 已生成四份正式历史文件、登记历史分区及关联物化／检查，并完成六个手动队列任务及有界验收。F 已获批完成 18 日人工接续及四 sensor 启用，真实自动日更与期末覆盖仍待自然条件，当前验收范围见 §11.18。

## 13. 依据与模板对账

- [DG 新增数据集模板](../templates/dagster-dataset-onboarding-template.html)：本文 §1–4 对应数据集卡、分层、Catalog、命名、路径与来源字段；§5–7 对应计算、checks、jobs、sensors 与人类可读说明；§8–11 对应初始化、失败、性能及分阶段验收。
- [DG 数据管道性能治理](dagster-data-pipeline-performance-governance.md)、[Asset schema contract](dagster-asset-schema-contract-design.md)、[Orchestrator 编码规范](../../orchestrator/CODING_STANDARDS.md)：本文的连接、计算、候选提升、检查、metadata 和 UI 文案约束。
- [Prod 指数现行机制](../../../docs/datasets/index-series-active-sync-mechanism.md)、[Prod 指数周月线 LLD](../../../docs/datasets/prod-index-period-low-level-design-v1.md)：仅作业务规则与既有证据参考；本文不修改 Prod 的单位或读取合同。
- Dagster 官方 [Assets](https://docs.dagster.io/guides/build/assets)、[Resources](https://docs.dagster.io/guides/build/external-resources)、[Partitions](https://docs.dagster.io/guides/build/partitions-and-backfills)、[Asset checks](https://docs.dagster.io/guides/test/asset-checks)。已结合当前安装版本的 `multi_asset(check_specs=...)`、`MaterializeResult(check_results=...)` 签名核验检查随物化返回的支持，不新增独立重复执行检查任务。
- 本次分区细化核对官方 [动态分区 API](https://docs.dagster.io/api/dagster/partitions)、[分区资产依赖与执行范围](https://docs.dagster.io/examples/full-pipelines/dbt/managing-the-project)、[分区 checks](https://docs.dagster.io/guides/test/asset-checks)、[并发管理](https://docs.dagster.io/guides/operate/managing-concurrency)。已静态核对当前安装版 `AssetCheckSpec.partitions_def`、`AssetCheckEvaluation.partition`、`SensorResult.dynamic_partitions_requests` 和现有 `build_run_request(partition_key=...)`；没有执行正式 Dagster evaluation。
- 全局单任务执行依据为已核对的正式 `dagster.yaml`、当前四个更新 job／sensor／资产函数及官方[运行队列限制](https://docs.dagster.io/guides/operate/managing-concurrency/run-queue-limits)；bootstrap 的 `execute_in_process` 直接执行依据为当前受控入口和已确认维护流程。原四 pool 设计及并发试验记录已撤销为后续要求，不以假设的多任务并发扩展本次方案。
- 小文件选择依据保留为官方 [DuckDB 物理分区建议](https://duckdb.org/docs/2.0/data/partitioning/partitioned_writes)、[Arrow 分区开销](https://arrow.apache.org/docs/python/dataset.html#partitioning-performance-considerations)、[Dagster 按月分区而集中存储的示例](https://docs.dagster.io/examples/full-pipelines/etl-pipeline/partition-asset)。完整文件布局是结合本项目规模的设计决定，不是本任务实测最快结论，也不意味着没有分区事件。
- [通用 Tushare 下载组件使用说明](../architecture/tushare-download-component-usage-v1.html)和[组件 LLD](dagster-tushare-download-component-low-level-design-v1.html)：公开 `DownloadTask/BY_OBJECT_POINT`、完整 unit、配置读取、分页、标准错误与会话关闭；实际登记以当前 `tushare_download/contracts/__init__.py`、`dataset_transport_mapping.py` 为准，不按旧文档登记数量推断已支持指数接口。
- 当前 `defs/assets/index_daily.py`、`defs/jobs/silver_index_daily_update.py`、`defs/checks/index_daily_checks.py`、`defs/run_contracts/asset_column_schemas.py` 和 `defs/sensors/readiness.py`：日线实际 schema、路径、成功物化、四种原 checks 及现成历史查询的边界。仅静态核对，无新增 Prod／Tushare 请求或全历史数据审计。
