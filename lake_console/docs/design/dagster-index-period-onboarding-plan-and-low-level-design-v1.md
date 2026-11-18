# DG 指数周线、月线数据集接入方案与低层设计 v1

状态：**B／C 代码已提交 `a01fd3f58`。提交后复审发现 C 的 Prod Serving 读取精度错误，C 尚不能验收，须先修复再进入 D，见 §11.7。管理员已确认 bootstrap 每批使用独立 Dagster 原生运行。未访问正式源、写正式 Lake／事件、注册正式分区或启用 sensor。**

C 更新日期：2026-11-18；§2 的 Prod 审计日期及历史数量保持原记录。

日期：2026-11-17。本文按 [DG 新增数据集模板](../templates/dagster-dataset-onboarding-template.html) 编写，将方案与 LLD 合在一份文件维护。业务口径采用本次讨论中已经确认的决定；分区、job、sensor、check 对应关系以 §3、§6、§7 为准。初稿不分区、联合 Silver job、周月链重新下载日线及重复探测 Tushare 日线的设计均已撤回；日更实际输入为已有 `silver_index_daily`。实现进度只以 §11 的阶段记录为准，未完成阶段仍是设计要求。

## 1. 目标、范围与已经确认的决定

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

写入策略为 `SINGLE_FILE_ATOMIC_REPLACE`。同一资产不同分区写的是同一文件，必须使用 §7.4 的单文件串行写入约束。日常只记录本次目标分区的物化与 check；bootstrap 四个文件一次生成，按实际有记录的历史分区批量补录物化与 check 结果，不能仅写四次无分区事件冒充历史分区已就绪。四条 Catalog entry 的事件策略为 `DAGSTER_RUN_ONLY`。bootstrap 由每批独立原生运行承载，不新增 bootstrap 资产；人工重跑创建新运行，资产结果数量仍按 §9 的 `2N` 统计，正常运行日志另计。

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

Raw 周／月线成功更新后，对应 Silver sensor 另触发同一个周／月分区的更新，配置只传 `mode=period`，原期末从所选分区和交易日历推导，不另传 `trade_date`，与 §7.5 一致。覆盖目标按 `ts_code, period_start_date` 定位，不能将历史期末替换成触发当天，也不能只看该分区当天已物化就跳过新 Raw 覆盖。北证 50 没有新 Raw 时保留已经结束且完整的合成 K 线，不为本次覆盖再次读取和计算它的全周期日线；其目标周期尚未完成则失败并交人工。

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
| `silver_index_weekly_update_job_sensor` | `silver_index_weekly_update_job` | 当天 DG 指数日线 Silver 成功并通过已有 checks、11 个目标代码齐备后，以本周分区、`mode=daily, trade_date=T` 更新；另消费新成功周线 Raw，提交原周 `mode=period` | DG 指数日线成功后更新当前周，并覆盖新到的期末周线。 |
| `silver_index_monthly_update_job_sensor` | `silver_index_monthly_update_job` | 当天 DG 指数日线 Silver 成功并通过已有 checks、11 个目标代码齐备后，以本月分区、`mode=daily, trade_date=T` 更新；另消费新成功月线 Raw，提交原月 `mode=period` | DG 指数日线成功后更新当前月，并覆盖新到的期末月线。 |

四者均 `minimum_interval_seconds=600`、时区 `Asia/Shanghai`，只在交易日 19:00 至次日 00:00 前判断更新。600 秒是既有同类 sensor 间隔，不新增独立轮询配置，不保证日线成功即刻执行。Silver sensor 通过已有事实轮询等待上游成功，不在日线 job 内新增触发代码。每个 sensor 每 tick 最多一个 RunRequest、一个本频率缺失分区键登记；Silver sensor 的 Tushare 请求数为 0，Raw sensor 至多一次正常发布探测。相应 Silver sensor 优先完成当日日更，期末覆盖后续 tick 判断，不丢弃新 Raw 批次。

Raw 发布探测由 `source_readiness/tushare/index_period.py` 复用同一下载组件，以 `BY_OBJECT_POINT` 读取上证指数单代码、单期末的一个完整 unit，只用代码／日期判断是否已发布。组件仍下载完整 11 字段，不另造两列子契约或 SDK／HTTP 客户端；正常最多一行，空 unit 则等待。Raw job 再按 11 个代码下载正式本期数据。探测不写业务文件或恢复缓存。

Silver 日更门禁按以下顺序，只读当天 T 的上游事实：

1. `silver_index_daily` 当天分区已成功物化，生成它的运行成功结束；当前正式入口是 `silver_index_daily_update_job`。仅看到日线 job 被触发、排队或正在执行不算就绪。
2. §2.4 的四个既有 blocking checks 全部通过，并原生关联到这次 T 日线物化。实现按该生产 run 有界读取四种检查结果、核对关联物化；不重复执行 checks。旧日线 check 的 event partition 为空时不能直接用 `partition_filter=T` 查询并永久等待，也不能拿其他日期的绿灯代替。当前通用 `asset_readiness_status` 会逐 check 扫最多 5000 条历史，本门禁不调用这条历史扫描路径；不因此改现有日线检查定义。
3. 读取 T 日线 Silver 文件中的代码、日期两列，过滤目标 11 个代码确认齐备。仅有文件或日线总行数不够；缺目标指数则等待并显示代码摘要，不向 Tushare 补取。完整周期输入的必要校验由 job 在读取实际窗口时完成。

基础日历／指数基础信息仍须成功及原 checks 通过，日历覆盖所需周期。日更依赖日线成功；期末正式值覆盖是另一个分支，依据原周／月 Raw 分区本次物化及 check，不要求触发当天的新日线再次完成，按 §5.3 保留已完成的合成记录或报缺失失败。两分支均不执行上游 writer／checks，不深扫历史。新的日更是同一周／月分区再次物化，昨日结果不代表今天完成。

定义分类通过 `build_sensor_tags`：领域 `INDEX_TOPIC`，目标层为对应 `RAW` 或 `SILVER`，职责 `ASSET_UPDATE`。提交通过 `build_run_request`，显式设置正确的 `partition_key`，typed config 经运行合同转换，不拼深层 `ops` 配置。需要登记新键时使用同一次 `SensorResult` 的动态分区请求，不在 helper 内随意写 instance。

cursor 使用 `build_sensor_cursor` v1 结构，仅保存本 tick 决策、目标分区、实际截至日、日线等待／检查失败原因、缺失代码数及有限样本、下一步动作和最近批次提示。沿用典型小于 2KB、复杂阻断小于 3KB、硬上限 8KB 的既有预算；不存行情、整批 check 明细、完整历史键集合或 schema map。

### 7.3 去重、当期刷新与期末覆盖

| 场景 | RunRequest 与去重身份 | 为什么不会漏更新 |
| --- | --- | --- |
| Raw 更新 | 目标 job、`partition_key=P`；`build_asset_update_run_key` 的 subject 为对应 job，unit 为 P | 同一频率同一期末只自动提交一次 |
| Silver 日更 | 目标 job、`partition_key=P`、`mode=daily, trade_date=T`；同类 builder 的 unit 同时包含 P 和 T | 17 日、18 日虽同一周／月，仍是不同日更；不能只拿 P 当 run key，导致整周／月只跑一次 |
| 新 Raw 覆盖 | 对应 Silver job、原 Raw 分区 P、`mode=period`；`build_upstream_triggered_run_key` 使用对应 consumer 与 Raw 的 `upstream_batch_id` | 当日已日更也能另提交覆盖；不会误更新到触发当天所在的其他周期 |

执行参数来自显式 partition key、typed config、日历和 Raw metadata，不解析 run key。sensor 按本次分区及截至日读取匹配的物化／check 事实，cursor 不作为就绪证据。失败后不自动换 key 重试；运营在同一 job 选择原分区，重跑原模式和目标日，不重跑已经成功的另一频率。

### 7.4 同一文件串行写入

同一资产的多个周期都更新同一个物理文件；必须防止两个 run 同时读旧文件、后提交者丢掉另一个周期的更新。每个资产使用一个现有 Dagster op concurrency pool，limit 为 **1 个同时执行的 writer**：

| 资产／唯一 job | asset 的 pool 名称 | 限制所保护的文件 |
| --- | --- | --- |
| `raw_index_weekly`／`raw_index_weekly_update_job` | `raw_index_weekly_writer` | 周线 Raw 完整文件 |
| `raw_index_monthly`／`raw_index_monthly_update_job` | `raw_index_monthly_writer` | 月线 Raw 完整文件 |
| `silver_index_weekly`／`silver_index_weekly_update_job` | `silver_index_weekly_writer` | 周线 Silver 完整文件 |
| `silver_index_monthly`／`silver_index_monthly_update_job` | `silver_index_monthly_writer` | 月线 Silver 完整文件 |

1 是共享文件不能同时由两个 run 做读旧值再替换的约束，不是估测性能参数。范围覆盖下载、读旧文件、合并、候选校验和提升所在的资产 step；不能只在 sensor 看“正在运行”就声称已经保护了人工并行重跑。各文件的 pool 独立，周、月及两层互不增加串行限制。必须设置 instance pool limit 并读回，只有写 `pool=` 名称没有 limit 不能视为已生效。

sensor 仍在本 job 已排队／运行时等待，避免积压。人工维护先暂停对应 sensor；bootstrap 不经过资产 step，须暂停四个 sensor 并等待四个 job 结束，再调用同一正式 writer。无需自造锁文件、租约、恢复表或回滚流程。

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
| 四个 writer pool | 名称集中在同一运行合同；instance 原生并发限制持久化，op 粒度，各 limit=1 | 四个资产 step 使用；池限制配置／读回在正式启用前另行获批执行，运行中可从 Dagster 并发管理查看，不改全局 executor 设置 |
| DG 日线输入 | 固定依赖 `silver_index_daily` 和现有 `silver_index_daily_path`，没有可选下载来源开关 | 两个 Silver job、两个 Silver sensor、bootstrap 当前期及人工 repair；读取所需日期／11 个代码，缺失报错，不退回 Tushare／Prod 日线 |
| 周／月源下载 | DG 本地 `index_weekly`、`index_monthly` 完整契约 version=1；对应 `CONTRACTS/BINDINGS` 固定 HTTP、`BY_OBJECT_POINT` | 两个 Raw job 和单点发布探测；新增契约在定义加载后生效，不改变通用下载组件公开 API、全局策略或现有数据集登记 |
| Tushare 连接 | 由 `TushareDownloader.load()` 的现有 `ConfigurationLoader` 读取 `TUSHARE_TOKEN` 与 `TUSHARE_BASE_URL`；默认地址沿用组件定义，修改环境后新实例生效 | 仅正式周／月下载和发布探测；不从 asset 传 token／地址／fields／limit／offset，不在 Silver 日更创建下载器；未在文档或日志写凭据 |
| Prod／Lake／DuckDB 连接设置 | 复用现有 Resources，不新增主机、内存或线程设置 | 本次周月模块只在 bootstrap 连 Prod 周／月表；路径与查询复用现有 helper。DG 日线自身现有 Prod 来源保持不变，不宣称本次已将它迁移到 Tushare 直采 |

源字段、单期行数与分页参数是源合同，不作为运营自由输入。配置测试覆盖分区与实际截至日不符、期末模式额外日期输入、非法模式／旧湖来源、pool 名称与有效 limit、默认 STOPPED，不引入用户侧开关。

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

下列是全部阶段的实现位置；B 的 Raw、C 的 Silver 与 bootstrap 入口已实现；sensor 仍未实现。设计阶段已用 CodeGraph explore／impact 和当前文件核对目录与相邻链路，分析覆盖指数资产、checks、jobs、sensors、资源、Catalog 及财势乾坤日线消费者；B 阶段又用 explore 定位相邻周期链和 `TushareDownloader`，逐项阅读实际组件、资源、Catalog 与测试。CodeGraph 结果只用于定位，业务规则以当前代码为准。

| 位置（均相对 `lake_console/orchestrator/src/orchestrator/`） | 本次职责 |
| --- | --- |
| `defs/run_contracts/index_period.py`（新增） | 四资产／checks 名称、typed config、分区和日期输入、DG 日线依赖、已确认运行窗口及 metadata 约定；不在这里另写下载请求拼装 |
| `defs/partitions.py` | 仅新增指数周末、自然月两个专用动态分区定义；不改变现有指数日线、股票或全局分区集合 |
| `defs/run_contracts/asset_column_schemas.py`、`defs/catalog/name_mapping.py`、`defs/catalog/lake_assets.py`、`defs/paths.py` | 四份 schema、两个中文名、四条周期分区＋完整文件布局的 Catalog entry／模型；正式、staging 路径不按分区拆文件 |
| `defs/assets/index_period.py`（新增） | 四个分别分区的资产与四个 writer pool 绑定；加载 partition key／typed config，调用正式 helper，发本分区物化及 checks；不建跨周月分区的 multi_asset |
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
| 同文件串行写入 | 四资产分别绑定正确 pool，启用前验证各有效 limit=1。隔离测试用不同历史分区的两个 run 证明同资产 writer 不重叠且两个更新都保留；不同文件不因本设计互相串行，不用正式 instance 作测试 |
| Catalog、文件与人能读懂 | schema／路径／check 名称／partition model 与方案一致；job 不选择上游 writer；cursor 的 reason_code、blocked_component、summary、next_action 和已有长度预算分别测试 |

各阶段测试文件映射如下，均位于 `lake_console/orchestrator/tests/`。B／C 已实现前三份的 Raw／Silver 部分、源响应隔离用例及 bootstrap 测试；sensor 与完整并发集成用例留在 D，不记为已通过。共用的人工样本和生产者 schema 保存在 `tests/index_period_test_support.py`，不复制正式数据。

| 测试文件 | 对应要求与必要反例 |
| --- | --- |
| `test_index_period_contracts.py` | 字段、单位、四组身份、两套分区、Catalog／路径／pool；两份源下载完整契约、HTTP binding、公开组件调用模式及 ISO→YYYYMMDD；不登记 index_daily，不改既有日线定义；拒绝无界来源和错误日期输入 |
| `test_index_period_writer.py` | 真实 DG 日线 schema、独立金样本、单位／舍入、接续、正式覆盖和北证 50 保留、历史行保留；源下载接口替身直接报错，证明 Silver 只读 DG 文件；缺输入／中断失败，补齐 DG 后人工重跑 |
| `test_index_period_checks.py` | 四个实际 check 定义与资产分区一致，实际物化／check evaluation／check execution 的 partition 归属和原生关联；其他历史周期合法存在、目标新增日期错配失败，不调用行情合成函数重算 |
| `test_index_period_sensors.py` | 四个 sensor 的窗口、DG 日线成功／四种关联 checks／11 码门禁、旧空 partition 兼容读取及查询范围、Raw 单点组件发布探测、动态键、P＋T 去重、正式覆盖、默认停止；断言无 Tushare 日线请求 |
| `test_index_period_bootstrap.py` | 11 指数来源／起点及既有例外、科创综指当期只读 DG 日线、Serving 领先 DG 时等待而非下载；四候选集合处理、`2N` 原生结果；不逐分区重读或深扫 readiness，不伪造无分区事件 |
| `test_index_period_concurrency.py` | 隔离 instance 中四个原生 pool 各 limit=1；同资产不同分区写入串行且结果均保留，不同文件不互相串行；不引入自造锁或自动恢复状态 |

临时文件及隔离 instance 均在工程目录外，不连接正式 Lake、PG 或 Tushare。替身只证明内部链路，真实源合同沿用 §2 已验证证据；正式文件验收只能在单独批准的范围内完成。性能、隔离运行和正式执行结果各自记录，不以文档检查代替测试或生产验收，不重新开展全历史源审计。

### 11.2 阶段边界

| 阶段 | 产出与通过条件 | 当前状态 |
| --- | --- | --- |
| A 方案确认 | 按模板定义字段、Catalog、paths、周期分区／完整文件、四组 job／sensor／check、初始化及预算 | 已提交 `f027076e5`，B 按此基准实施 |
| B 合同与 Raw | 字段／分区／路径、Prod 只读投影；两份完整周期契约和 HTTP binding；Raw 下载及发布探测复用现成组件，writer／check／job 隔离测试；只列本次最小真实组件接入验证范围，不改日线链、不写正式数据 | 开发及专项验收完成，独立审计见 §11.4；全局治理仍有既有失败，待管理员验收 |
| C Silver 与初始化入口 | 从 DG 日线 Silver 合成、单位转换、期末覆盖及 bootstrap；日线缺失不得下载兜底；金样本与人工重跑验证 | 主体开发已提交；提交后复审发现 Serving 读取精度错误，须先修复并补回归，见 §11.7；D 未开始 |
| D 自动化及集成 | 四个默认停止 sensor；DG 日线成功／原生关联 checks／11 码门禁，零日线请求；分区、P＋T 去重、独立 Raw 覆盖、四 pool 和分区事件集成通过 | 未开始 |
| E 正式初始化与最小日更验收 | 列明实例、命令、11 代码范围、DG 日线窗口、N／2N 和 pool；获批后完成必要的最小组件真实取数验证、四文件初始化与分区事实补录；待既有 DG 日线 T 成功，再分别运行周月日更及必要读回，不重复全历史源审计 | 未授权、未执行 |
| F 启用与收尾 | 管理员确认验收后启用 sensor；回填本文、资产拓扑和实际结果 | 未授权、未执行 |

B 阶段使用 orchestrator 现有 `.venv` 的 pytest／Ruff，以及仓库规定的受保护治理测试启动器；无安装或升级步骤。job、checks 与分区事件只在临时目录的隔离 instance 验证，不执行正式 evaluation、materialize、bootstrap、事件补录或 sensor 启停。

以下是后续启动的任务顺序。B、C、D 是三个开发阶段；E、F 是正式执行阶段。各阶段完成本阶段测试、代码与本文口径对账，交管理员验收后再推进下一阶段。开发授权不自动包含正式读写或启用授权。

#### B：基础定义与指数周线、月线 Raw

本阶段形成可在隔离环境执行的两项 Raw 更新入口。

1. 在 `run_contracts/index_period.py`、`partitions.py`、`asset_column_schemas.py`、`paths.py` 落实 11 码范围、字段／单位、周末实际交易日与自然月分区、完整文件和 staging 路径、配置及 pool 名称。
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

#### D：四个 sensor、写入串行与整体集成

本阶段形成可加载、默认停止的完整调度链。

1. 实现当天 DG 日线就绪 helper：定位 T 的成功物化和生产 run，读取其四种原有 blocking check 的关联结果，再确认当日文件包含 11 个目标代码。兼顾旧 check event 的空 partition，不修改日线定义、不重跑其 checks、不扫 5000 条历史。
2. 实现四个同名 job sensor：两个 Raw 按期末源发布触发；两个 Silver 等日线成功后触发日更，另消费新 Raw 批次覆盖原分区。落实 19:00–00:00、600 秒、目标键登记、P＋T 去重、当日合成后仍能正式覆盖和失败人工重试。
3. 四个资产绑定各自 writer pool。隔离 instance 设置各 limit=1，验证不同周期写同文件时串行，两个修改都能保留；不同文件不被本设计强制互相等待。正式 instance 的配置留到 E。
4. 补齐中文 description、cursor、日志、物化与 check metadata；只保留必要数量、窗口和失败样本，不添加新状态表、汇总资产或额外 check。
5. 完成六份测试文件的相关部分及整体隔离运行，覆盖“DG 日线成功 → 两项周期合成”“正式 Raw 成功 → 原周期覆盖”“缺数／中断 → 失败 → 人工重跑”，并断言 Silver 链 Tushare 日线请求为 0。

验收：四资产、两套分区、四 check、四 job、四 sensor、Catalog、schema、路径、默认 STOPPED 与本文逐项一致；实际检查事件和执行记录的分区正确；在 §9 对应规模下记录一次隔离文件／事件开销。按现有环境运行相关 pytest、Ruff、Definitions 静态验证和文档检查，正式资源访问与启用不混入测试。

#### E：正式初始化与手动日更验收

本阶段须单独取得正式执行授权。

1. 执行前列明命令、工作目录、正式 instance、11 个代码、四张 Prod 来源表的投影、DG 日线窗口、四份目标／staging 文件、实际 N／2N 与并发限制，确认四个新 sensor 停止、相关 run 已结束。
2. 只补尚缺的通用组件真实调用边界：周／月各一个已结束期末、一个代表代码的完整字段请求，核对请求和 unit／Raw 接入合同。沿用已有参数、字段、单位及历史审计，不重新扫描 Prod／Tushare 全历史。
3. 生成四份正式完整文件，按本次传输结果集合式校验一次；科创综指当期依赖 DG 日线，缺失先补上游，不下载兜底。然后批量注册历史分区，补录实际有记录分区的物化与 check，汇总核对数量并少量读回。
4. 配置并读回四个原生 writer pool 的有效 limit=1。待目标 T 的既有 DG 指数日线成功，分别手动运行周线、月线 Silver 日更，确认分区固定、实际截至日更新为 T、其他历史不变、checks 对应本次结果。
5. 根据获批的已结束周期，完成一次“正式 Raw → 同一 Silver 分区”的手动覆盖验证，重点确认同日去重不拦覆盖、北证 50 合成值保留；不为测试另做全历史重算。

验收：记录四文件行数／字节数、两套分区与 N／2N、最小真实取数、两项手动日更／正式覆盖及必要读回证据。异常按既定人工重试规则处理；四个 sensor 继续停止，正式初始化完成不等于自动化已启用。

#### F：启用自动更新与文档收尾

本阶段在 E 验收通过、管理员明确同意后进行。

1. 启用四个 sensor，观察一次真实自动日更：日线未完成时等待，完成并通过原检查后才生成周／月任务；日线请求增量为 0，不重复提交同一 P＋T。
2. 在真实周末／月末发布周期验证 Raw 到数及 Silver 原分区覆盖。若相应期末尚未到来，明确记录“已启用、该频率期末自动覆盖待观察”，不能预填通过或用历史手动验证冒充自动运行。
3. 将实际文件、数量、配置、运行结果、失败诊断和完成状态落回本文及需要更新的现有资产拓扑／运行说明，不新建重复的过程报告。

验收：区分“已启用”“自动日更已验证”“周线／月线期末自动覆盖已验证”三类实际状态；仅在对应证据真实取得后标完成。启用和观察范围不扩展为财势乾坤 API／前端接入。

开发阶段分别交付；当前停在 C，不自动开始 D。后续获准启动时，先将该阶段硬口径映射到 §10 的具体修改文件和 §11.1 测试；复用当前代码和已有审计，保留当前 `dev-interface` 工作区其他改动。未经下一步授权不提前进入 C、D 或正式执行阶段。

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

**当前C尚不符合全部验收条件，暂不能推进D。** 先完成上述修复与必要回归，再重新验收C。D的四sensor、上游成功及原检查关联门禁、P＋T去重、Raw独立覆盖与四pool串行验证已在 §7、§11.2 明确，无需因此重新讨论业务口径；修复通过后再按阶段授权开工。

## 12. 本版确认范围与实施约束

业务单位、11 个指数、初始化来源、每日当期更新、运行窗口与失败人工重试已确认。管理员本轮进一步明确：日更从既有 DG 指数日线 Silver 合成，必须在当天日线成功及原 checks 通过后触发；本链不再探测或下载 Tushare 日线。正式周／月线下载复用现成通用组件，不重复开发下载能力。

管理员已确认 **Dagster 按周、月分区，Raw／Silver 每频率各一份完整历史文件**。本版明确为四个资产、两套指数专用周期分区、四个 job、四个同名 sensor、四个随目标分区写入执行的 check；对应关系见 §7.1、§7.2。文件路径保持四份，周／月内每天重复更新同一分区，实际截至日单独记录。

必须同时采用的约束：两个 Silver job 只读 DG 日线窗口，日更去重包含 P 和 T；上游未成功不提前运行；当前 Raw 未到数不阻塞已就绪日线的合成；新 Raw 仍可另行覆盖同一原分区，不被当日已合成挡住；同文件 writer 串行；bootstrap 按分区补录 `2N` 结果。B 已登记两份周期下载契约并通过隔离组件接入测试，不能据此声称真实源或正式运行已验收。尚未设置正式 pool limit、注册正式分区、写正式 Lake／事件或启用 sensor；C 的 Silver 与 bootstrap 入口已提交，但须先修复 §11.7 的来源精度错误再验收；自动化仍留在 D，正式初始化和启用仍分别留在 E／F。

## 13. 依据与模板对账

- [DG 新增数据集模板](../templates/dagster-dataset-onboarding-template.html)：本文 §1–4 对应数据集卡、分层、Catalog、命名、路径与来源字段；§5–7 对应计算、checks、jobs、sensors 与人类可读说明；§8–11 对应初始化、失败、性能及分阶段验收。
- [DG 数据管道性能治理](dagster-data-pipeline-performance-governance.md)、[Asset schema contract](dagster-asset-schema-contract-design.md)、[Orchestrator 编码规范](../../orchestrator/CODING_STANDARDS.md)：本文的连接、计算、候选提升、检查、metadata 和 UI 文案约束。
- [Prod 指数现行机制](../../../docs/datasets/index-series-active-sync-mechanism.md)、[Prod 指数周月线 LLD](../../../docs/datasets/prod-index-period-low-level-design-v1.md)：仅作业务规则与既有证据参考；本文不修改 Prod 的单位或读取合同。
- Dagster 官方 [Assets](https://docs.dagster.io/guides/build/assets)、[Resources](https://docs.dagster.io/guides/build/external-resources)、[Partitions](https://docs.dagster.io/guides/build/partitions-and-backfills)、[Asset checks](https://docs.dagster.io/guides/test/asset-checks)。已结合当前安装版本的 `multi_asset(check_specs=...)`、`MaterializeResult(check_results=...)` 签名核验检查随物化返回的支持，不新增独立重复执行检查任务。
- 本次分区细化核对官方 [动态分区 API](https://docs.dagster.io/api/dagster/partitions)、[分区资产依赖与执行范围](https://docs.dagster.io/examples/full-pipelines/dbt/managing-the-project)、[分区 checks](https://docs.dagster.io/guides/test/asset-checks)、[并发管理](https://docs.dagster.io/guides/operate/managing-concurrency)。已静态核对当前安装版 `AssetCheckSpec.partitions_def`、`AssetCheckEvaluation.partition`、`SensorResult.dynamic_partitions_requests` 和现有 `build_run_request(partition_key=...)`；没有执行正式 Dagster evaluation。
- 小文件选择依据保留为官方 [DuckDB 物理分区建议](https://duckdb.org/docs/2.0/data/partitioning/partitioned_writes)、[Arrow 分区开销](https://arrow.apache.org/docs/python/dataset.html#partitioning-performance-considerations)、[Dagster 按月分区而集中存储的示例](https://docs.dagster.io/examples/full-pipelines/etl-pipeline/partition-asset)。完整文件布局是结合本项目规模的设计决定，不是本任务实测最快结论，也不意味着没有分区事件。
- [通用 Tushare 下载组件使用说明](../architecture/tushare-download-component-usage-v1.html)和[组件 LLD](dagster-tushare-download-component-low-level-design-v1.html)：公开 `DownloadTask/BY_OBJECT_POINT`、完整 unit、配置读取、分页、标准错误与会话关闭；实际登记以当前 `tushare_download/contracts/__init__.py`、`dataset_transport_mapping.py` 为准，不按旧文档登记数量推断已支持指数接口。
- 当前 `defs/assets/index_daily.py`、`defs/jobs/silver_index_daily_update.py`、`defs/checks/index_daily_checks.py`、`defs/run_contracts/asset_column_schemas.py` 和 `defs/sensors/readiness.py`：日线实际 schema、路径、成功物化、四种原 checks 及现成历史查询的边界。仅静态核对，无新增 Prod／Tushare 请求或全历史数据审计。
