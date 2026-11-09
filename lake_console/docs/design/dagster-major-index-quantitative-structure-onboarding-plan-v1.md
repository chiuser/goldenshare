# DG 主要指数量化结构 Gold 数据集接入方案 v1

2026-11-09。已确认每日全量重算和上海时间 18:00 开始检查。依据 [DG 数据集资产接入综合模板](../templates/dagster-dataset-onboarding-template.html)。实现、正式 bootstrap 和验收步骤见[详细设计](dagster-major-index-quantitative-structure-onboarding-low-level-design-v1.md)。开工条件见第 8 节。

**交付状态（2026-11-09）**。DG 数据集已部署，2010-01-04 至 2026-11-06 的 4,089 个交易日已通过 Gold 文件和 DG 事件验收，分区登记 Sensor 和日更 Sensor 均已启用。待首个自动日更触发后，按 LLD 核对运行、Gold 文件及两项检查。财势乾坤的读取切换见 [§9](#9-财势乾坤接入技术方案)。 [正式执行记录](dagster-major-index-quantitative-structure-onboarding-low-level-design-v1.md#72-正式执行记录)

## 1. 目标与范围

在 DG 从历史起点连续计算并保存已完成 K 线上的量化结构事件。首次初始化写齐批准范围内每个交易日的结果。日更用同一计算方法从历史起点算到目标交易日，只写该日结果。两种运行的识别状态都只在本次运行的内存里使用。产出的 Gold 数据集作为财势乾坤加载历史量化结构的来源。

复用 r4.1 识别内核，覆盖日线和 30、60、90、120 分钟。范围为上证指数（`000001.SH`）、深证成指（`399001.SZ`）、创业板指（`399006.SZ`）、科创50（`000688.SH`）、沪深300（`000300.SH`）、中证500（`000905.SH`）、中证1000（`000852.SH`）、中证A500（`000510.SH`）、上证50（`000016.SH`）。先验收 DG 数据集和历史初始化，再接入财势乾坤的数据读取。 [研究交接](../../../docs/product/xxm-research-and-implementation-v0.6.md) · [九指数范围与来源](../../../docs/product/wealth-top-bottom-recognition-index-expansion-plan-v1.md)

### 1.1 数据集说明卡（模板 §3）

| 项目 | 本次定义 |
| --- | --- |
| 中文名与编码 | 主要指数量化结构，`major_index_quantitative_structure`，中文名登记在 `defs/catalog/name_mapping.py` |
| 业务事实与消费方 | 记录已完成 K 线上的钝化、结构形成和消失。财势乾坤读取历史结果 |
| 层级、数据域与来源 | Gold、`DataDomain.INDEX_TOPIC`、`SourceSystem.DERIVED`，按指数行情计算量化结构 |
| 写入与分区 | 一个 SSE 开市日一个分区、一份结果文件。资产目录、路径、检查和入口见第 5 节 |
| 手动运行 | 在 DG 选择待处理的交易日分区，沿用日更 job。业务输入由 `partition_key`、九指数范围和内核版本确定，无需手填运行配置 |
| 历史初始化与验收 | 从 2010-01-04 起按各序列有效日期连续计算。范围与预算见第 6 节，样本及验收见第 7 节 |
| 不适用项 | 本次只新增 Gold。Raw、Silver 开发、Tushare 拉取与分页实测（模板 §7）、Prod 只读来源均不适用，原因是直接读已有的 DG 文件 |

## 2. 上游与历史起点

| 现有 DG 来源 | 投影字段和物理类型 | 送入内核的值 |
| --- | --- | --- |
| Silver `index_factor_pro`，资产 `silver_index_factor_pro` | `ts_code VARCHAR`、`trade_date DATE`，`close`、`macd_dif_bfq`、`macd_dea_bfq`、`macd_bfq` 均为 `DOUBLE` | `trade_date` 转为日线完成日期，四个数值依次映射到 `close`、`dif`、`dea`、`hist` |
| Gold `major_index_mins` 的四个频率 | `ts_code VARCHAR`、`freq INTEGER`、`trade_date DATE`、`trade_time TIMESTAMP`、`close DOUBLE` | 上海本地完成时刻按内核合同带 `+08:00`，并传入 `close` |
| Gold `major_index_mins_technical` 的四个频率 | `ts_code VARCHAR`、`freq SMALLINT`、`trade_date DATE`、`trade_time TIMESTAMP`，`macd_dif`、`macd_dea`、`macd` 均为 `DOUBLE` | 与同一根价格 K 线对齐后依次映射到 `dif`、`dea`、`hist` |
| Silver `trade_calendar` | `exchange VARCHAR`、`trade_date DATE`、`is_open BOOLEAN` | 以 `exchange='SSE'` 的开市日确定应处理日期 |

直接沿用这三项上游。分钟价格和指标按 `ts_code`、`freq`、`trade_date`、`trade_time` 对齐，使用已经完成的 K 线。分钟 MACD 由 DG 技术指标任务按指数、周期使用收盘价计算，参数为 12、26、9。指标日更继承前一交易日的 EMA 和 DEA 状态，柱值为 `2 × (DIF − DEA)`。本资产读取上游已产出的收盘价和 MACD。 [DG 分钟指标计算](../../orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py)

日线和分钟统一以 **2010-01-04** 为计算下限。每个序列取计算下限与上游合同有效起点中较晚的一天，从空的识别状态开始。按代码、周期和日期选取应有记录。日线以 `(ts_code, trade_date)` 唯一。分钟按指数、频率、日期和完成时刻逐根对齐。日线源允许指标为空，本数据集所需输入按现有 `XxmBar` 合同使用有限数值和正收盘价。应有输入缺失、重复或不符合合同，则本次计算失败。起点前的记录属于范围外。物理类型以关闭 Hive 分区推断的文件检查为准。 [源字段合同](../../orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py) · [现有 K 线输入合同](../../../packages/technical_indicators/src/goldenshare_technical_indicators/xxm/types.py)

| 指数 | 日线计算起点 | 30、60、90、120 分钟计算起点 |
| --- | --- | --- |
| 上证指数、上证50、沪深300、中证500、深证成指 | 2010-01-04 | 2010-01-04 |
| 创业板指 | 2010-06-01 | 2010-06-01 |
| 科创50 | 2019-12-31 | 2020-07-23 |
| 中证1000 | 2010-01-04 | 2014-10-17 |
| 中证A500 | 2024-09-23 | 2024-10-22 |

表中日期根据现有 [日线有效范围](../../orchestrator/src/orchestrator/defs/run_contracts/idx_factor_pro.py) 和 [分钟有效范围](../../orchestrator/src/orchestrator/defs/run_contracts/major_index_mins.py) 推导。历史初始化时按该范围对账实际应有记录。

第 1 节的九个指数是本 Gold 固定的计算范围，适用于日线、四个分钟周期、首次初始化和日更。现有 DG 合同决定这九个指数各自在什么日期有效。科创综指（`000680.SH`）在 DG 日线和分钟上游范围内，北证50（`899050.BJ`）在 DG 日线范围内且已由分钟 Silver 合同排除。两者都在本 Gold 的九指数范围之外。上游增减其他指数时，仍按本节范围计算。 [DG 日线名单和起点](../../orchestrator/src/orchestrator/defs/run_contracts/idx_factor_pro.py#L126) · [DG 分钟名单和排除规则](../../orchestrator/src/orchestrator/defs/run_contracts/major_index_mins.py#L256)

只读抽查证据如下。

| 交易日 | 核验范围 | 结果 |
| --- | --- | --- |
| 2010-01-04 | 四个分钟周期各两份文件 | 上证指数、深证成指、沪深300、中证500、上证50的价格与指标时间键匹配。每个指数分别有 8、4、3、2 根，必需值均有效 |
| 2026-11-06 | 一份日线和四个分钟周期各两份文件 | 九指数日线与四个分钟周期分别有 9、72、36、27、18 根，分钟时间键逐根匹配 |

另对 2026-11-06 上证指数 90 分钟做了只读复算。使用 11 月 5 日的日末 EMA、DEA 和 11 月 6 日三根 Gold K 线收盘价，复算的 DIF、DEA 和 MACD 柱值与同日 Gold 技术指标对得上，最大绝对差约 `1.8 × 10⁻¹²`。本次按 2026-11-06 样本检查了日线、90 分钟 K 线和指标文件的上述物理类型。全历史文件数量和体积见第 6 节。

## 3. 每日结果字段

按 SSE 交易日分区，每天一份 Parquet、一行。主键为 `trade_date`。日期和成功标志按日保存，只有发生识别事件才在 `results` 中写明细。除 `bar_end_time` 的日线值外，以下业务字段均不可空。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `trade_date` | `DATE` | 交易日，与分区一致 |
| `success` | `BOOLEAN` | 当天所有应计算的指数和周期是否均已成功完成 |
| `results` | `STRUCT[]` | 有序识别事件列表，空时为 `[]` |

`results` 的元素字段如下。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 指数代码 |
| `period` | `VARCHAR` | `day`、`m30`、`m60`、`m90` 或 `m120` |
| `bar_end_time` | `TIME`，可空 | 分钟 K 线的上海本地完成时刻，日线为空 |
| `event_type` | `VARCHAR` | `DULL` 钝化、`STRUCTURE` 形成结构、`CANCEL` 消失 |
| `direction` | `VARCHAR` | `TOP` 顶部或 `BOTTOM` 底部 |
| `display_on_chart` | `BOOLEAN` | 普通图是否画出该事件的标记，沿用现行规则 |

同一指数、周期、K 线的多个事件按内核顺序保留。以上证 90 分钟的 r4.1 回归案例为例，11 月 4 日 11:00 先取消旧结构，再按远参照形成新钝化。两项都保存，普通图按各自的 `display_on_chart` 决定画哪些标记。判断时只用同一根 K 线自己的事件，再汇总各指数和周期的结果。行情数值仍从上游取。结果文件只保存表中的业务字段。 [图上标记的显示规则](../../../packages/technical_indicators/src/goldenshare_technical_indicators/xxm/event_display.py) · [r4.1 案例](../../../docs/product/xxm-research-and-implementation-v0.6.md)

| 当天情况 | 结果行 | DG 状态 |
| --- | --- | --- |
| 成功且有事件 | `success=true`，保存事件列表 | 已完成 |
| 成功且无事件 | `success=true`，`results=[]` | 已完成 |
| 作业确认识别失败 | `success=false`，`results=[]` | 失败，原因看 DG 日志 |
| 上游未就绪或尚未执行 | 无结果行 | 等待 |

人工启动时上游尚未就绪，作业跳过且没有产出，之后仍可正常自动触发。开始计算后，若任一交易日的应有上游输入缺失或确认识别失败，记录实际出错日。日更写目标日失败行并登记产出，再由完成检查标记该分区失败。修好上游后用同一个日更 job 重跑目标日，仍从历史起点重新计算。首次初始化失败时停止写入，按详细设计第 5 节重跑同一获批范围。

## 4. 数据集版本和全量替换

Gold 只保留一份当前有效结果，整份数据集使用一个识别版本。版本以共享包的 `MAIN_SPEC.algorithm_version` 为准，当前值为 `xxm-direction-v0.5-r4.1`。日更和历史补录的 DG 产出元数据均记录实际运行的算法版本。每日结果行沿用第三节的字段。 [现有版本定义](../../../packages/technical_indicators/src/goldenshare_technical_indicators/xxm/spec.py)

计算逻辑变化时更新内核版本。经确认后复用首次初始化的历史批量入口，从 2010-01-04 按各指数、周期的有效起点重新计算全部历史，对账并替换整套结果文件，再登记新版产出和对应检查。历史行情修订时先确认受影响的分区，再用当前版本按目标分区重跑。

## 5. DG 定义与收盘后更新

### 5.1 编码名称和职责

下表是本方案拟采用的编码定义，待详细设计审阅后实施。

| 对象 | 编码名称 | 职责 |
| --- | --- | --- |
| 数据集 ID | `major_index_quantitative_structure` | 主要指数量化结构，Gold 层，归入 `index` 组 |
| Asset | `gold_major_index_quantitative_structure` | 每次生产一个交易日的文件，文件覆盖当天应计算的全部指数和周期 |
| 资产目录分区模型 | `TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_QUANTITATIVE_STRUCTURE` | 按 `trade_date` 分区，写入单位为一个交易日文件 |
| Dagster 动态分区集 | `cn_major_index_quantitative_structure_trade_days` | 量化结构数据集专属。分区键为 `YYYY-MM-DD`，每个 SSE 开市日一个键，起点为 2010-01-04 |
| 分区注册 sensor | `major_index_quantitative_structure_trade_day_sensor` | 按 SSE 日历注册本数据集的日期，注册本身不启动计算 |
| 日更 job | `gold_major_index_quantitative_structure_update_job` | 接收一个交易日分区，仅选择本 Gold asset 和对应检查。行情和指标由原任务生产，量化结构作业只读消费 |
| 日更 sensor | `gold_major_index_quantitative_structure_update_job_sensor` | 检查下一个待更新交易日是否可算，符合条件时提交一次该日 job |
| 结果合同检查 | `gold_major_index_quantitative_structure_result_contract_check` | 检查文件字段、日期、单日一行、空结果语义和事件取值 |
| 更新完成检查 | `gold_major_index_quantitative_structure_completion_check` | 检查分区结果为 `success=true` |

在 `LAKE_ASSET_CATALOG` 登记第 1.1 节的来源与领域、字段合同 `major_index_quantitative_structure_v1`、本节分区与检查、逐文件原子替换及历史事件补录能力。分区模型同步登记到 `PARTITION_MODEL_DEFINITIONS`。运行代码和 Catalog 引用同一份字段、路径和分区定义，Catalog 用于登记和静态检查。正式文件由 `defs/paths.py` 的路径函数生成，路径为 `/Volumes/datasource/data_lake/gold/indicator/major_index_quantitative_structure/trade_date=YYYY-MM-DD/part-000.parquet`。 [DG 编码与资产登记规范](../../orchestrator/CODING_STANDARDS.md) · [Dagster asset job](https://docs.dagster.io/guides/build/jobs/asset-jobs)

两个检查均为阻断检查，显式绑定本资产的动态分区集。结果合同检查接受 `success=false, results=[]` 的失败行，由完成检查阻断。r4.1 计算正确性和同根事件顺序由金样本测试验证。WARN 检查不适用，当前需求没有独立的观测阈值。 [模板 §11](../templates/dagster-dataset-onboarding-template.html#checks)

运行信息按模板 §4A 分开记录。

| 位置 | 内容与写法 |
| --- | --- |
| 资产定义 | 用 `build_asset_definition_metadata` 登记中文名、来源、分区和由路径函数生成的模板。稳定字段结构登记到 `dagster/column_schema`。用 `build_asset_tags` 登记 Gold、指数专题 |
| 本次产出 | 交易日用 DG 分区键。日更和历史补录均用 `build_materialization_metadata` 写 `dagster/uri`、`dagster/row_count`、`goldenshare/observed_columns`、`goldenshare/formula_version`、`goldenshare/source_row_count` 和 `goldenshare/event_count`。取值见 LLD §3.2 |
| 本次检查 | 用 `build_check_metadata` 记录交易日、文件路径、失败规则、数量及少量样本。结果合同用 `CheckScope.SCHEMA`，完成检查用 `CheckScope.VALUE_SANITY` |
| Sensor | 用 `build_sensor_tags`。注册器采用 `INDEX_TOPIC / PARTITION / PARTITION_REGISTRATION`，日更采用 `INDEX_TOPIC / GOLD / ASSET_UPDATE`。用 `build_run_request`、统一 run key 生成器和 `build_sensor_cursor` 提交请求并记录本次决定 |

编码名称按本节名称表与 [DG 命名规范](../../orchestrator/CODING_STANDARDS.md) 核对。两个 sensor 的分类随实现同步登记到 [运行合同治理](dagster-run-contract-governance.html)、[资产与任务拓扑](../architecture/dagster-asset-job-topology.html)及静态检查。

### 5.2 分区怎么注册

以 `silver_trade_calendar` 中 `SSE` 的开市日为准。独立分区集使识别资产从 2010-01-04 开始登记，同时保持既有日线因子和分钟资产各自的历史范围。首次初始化按核定日期集合批量注册历史键。日常注册器只检查最近 10 个已完成开市日，按日期顺序补注册，每次最多 2 个，沿用现有注册上限。

本数据集两个 sensor 的自动检查均从**每日上海时间 18:00 起**。18:00 前直接跳过，18:00 后按交易日历补登记近期缺口。开市日可登记当天，休市日只可补之前的开市日。两者最短检查间隔为 600 秒，实际检查时刻由 Dagster 调度。两个 sensor 默认停用，历史初始化验收后再按批准的顺序启用。 [交易日注册规则](../../orchestrator/src/orchestrator/defs/sensors/cn_a_trade_day_sensor.py) · [现有 18:00 注册示例](../../orchestrator/src/orchestrator/defs/sensors/stock_mins_trade_day_sensor.py)

注册 sensor 一次最多查询 10 个日期键的注册状态，找齐 2 个缺失键即可停止查询，最多提交 1 个批量注册请求。它只查询一份交易日历文件，按开市、时点和历史下限过滤，再取最近 10 个开市日。Cursor 记录检查时间、最早缺失日、已请求注册的键和结果摘要。

### 5.3 什么时候启动日更

量化结构分区 `D` 按相同日期键依赖下表中的 9 个上游资产。Dagster 资产依赖使用同日分区映射 `IdentityPartitionMapping`。`silver_trade_calendar` 是无分区的日历来源，负责确定应处理的日期。

| 上游 | 资产名 | 上游分区集 | 当日就绪证据 |
| --- | --- | --- | --- |
| 日线技术因子 | `silver_index_factor_pro` | `cn_major_index_factor_trade_days` | 最新产出及对应的 3 项阻断检查通过 |
| 四个分钟周期的 K 线 | `gold_major_index_mins_{30,60,90,120}m` | `cn_major_index_mins_trade_days` | 各周期最新产出及对应的 1 项阻断检查通过 |
| 四个分钟周期的技术指标 | `gold_major_index_mins_technical_{30,60,90,120}m` | `cn_major_index_mins_trade_days` | 各周期最新产出及对应的 6 项阻断检查通过 |

检查名称复用上游已登记的 `IDX_FACTOR_PRO_SILVER_CHECKS`、`MAJOR_INDEX_MINS_GOLD_CHECKS` 和 `major_index_mins_technical_checks(freq)`。DG 查的是目标日期最新产出的检查记录。上游重新产出后，旧产出的绿灯不能满足这次检查。 [同分区就绪检查](../../orchestrator/src/orchestrator/defs/sensors/readiness.py) · [同日分区映射](https://docs.dagster.io/api/dagster/partitions#dagster.IdentityPartitionMapping)

日更 sensor 每次按以下顺序判断。

1. 上海时间 18:00 起，用 SSE 日历和本资产两项 DG 检查选择最近 10 个已完成开市日中最早未完成的 `D`。以两项检查均通过且对应当前产出为完成。此前已发现的待处理日期即使超出窗口，也继续提示使用同一个日更 job 处理该分区。
2. 确认量化结构、日线因子和分钟三个分区集均已注册 `D`。同分区任务在运行时等待。独立查 `D` 的最新产出，避免两项检查都未执行时把已有产出当成从未产出。该日最近一次运行已失败或取消，或已有产出但两项检查尚未通过时，停在该日，提示用同一日更 job 手动重跑。
3. 核对 `D` 的 9 个上游资产及其阻断检查。日线先好就等分钟，分钟先好就等日线。**9 项产出和对应检查全部就绪后的首次有效 sensor 检查，才提交日更。** 缺分区、缺检查或检查失败时，DG 显示具体等待对象。
4. 每次最多提交一个 `RunRequest`，`partition_key=D`。复用 `build_asset_update_run_key(subject="gold_major_index_quantitative_structure_update", unit_id=D)` 去重。Cursor 只保存最近一次检查时间、目标日期、等待原因和少量状态摘要。

日更 sensor 的 DG 状态接口调用上限为 `1 + 3 + 1 + 1 + 9 + 1 = 16` 次，依次对应本资产批量完成情况、目标日三个分区集、最近运行、本资产目标日最新产出、九个上游产出和一次上游批量检查。上游批量检查涉及 `3 + 4 × 1 + 4 × 6 = 31` 项。Sensor 读取一份交易日历，行情和指标文件读取量为零。开发后验证实际调用次数。 [分区检查批量读取](../../orchestrator/src/orchestrator/defs/bootstrap/daily_basic_events.py) · [DG 性能规范](dagster-data-pipeline-performance-governance.md)

### 5.4 Job 如何写入

Job 启动后复核目标日上游就绪状态。用 DuckDB 按月读取从 2010-01-04 到目标日的行情和指标，从各指数及周期的有效起点连续计算。日更只保留目标日的事件，计算状态只存于当次进程内。历史行情在读取时按日期、指数和周期核对实际输入。耗时见 [LLD 的只读计时](dagster-major-index-quantitative-structure-onboarding-low-level-design-v1.md#61-开发前全历史读取与识别计时)。

目标日结果在 `/Volumes/datasource/data_lake_staging` 中写出、读回并校验，再原子替换该日正式文件。单日漏写、中断或失败时，用同一个日更 job 手动选择该分区，从历史起点算到该日，只写该日。上游有缺失时先由原上游任务补齐。日更、历史批量执行和人工重跑同一时间只有一个写入者。 [写入与恢复规范](dagster-data-pipeline-performance-governance.md)

### 5.5 DG 界面和排障

| 对象 | 中文说明 |
| --- | --- |
| Asset | 按交易日保存主要指数的量化结构事件，供财势乾坤读取。 |
| Job | 日线和四个分钟周期齐备后，计算指定交易日的量化结构。 |
| 分区注册 sensor | 上海时间 18:00 起登记交易日分区并补近期缺口。 |
| 日更 sensor | 上海时间 18:00 起检查同日行情与指标，全部通过后启动下一个待完成日。 |
| 两项检查 | 检查结果文件符合字段合同。检查当天量化结构已计算成功。 |

等待时在 sensor 的跳过原因显示目标日期、缺失资产或检查及下一步。计算或写入失败看同日 Run 日志。文件或结果不合格看对应 Check 的失败规则、数量和样本。历史作业按批汇报日期范围、已完成天数和累计事件数。

## 6. 一次性历史初始化

开发和小样验收完成后，先按 [LLD §2.2](dagster-major-index-quantitative-structure-onboarding-low-level-design-v1.md#22-正式-dg-安装与加载) 核对正式 DG 加载的源码，获准后安装 r4.1 并验证定义。历史初始化与日更共用从历史起点连续计算的代码。运营按批准的日期范围启动一次计算，DuckDB 在运行内部按月分批读取，结果逐日写入。

1. **确定范围。** 按 SSE 日历取得探查上限，复用 `plan` 只读找出九路输入文件连续齐备的最后一个开市日。以当次计划冻结截止日、算法版本和预期交易日，统计来源文件、预计输入根数及目标文件，核对可用空间。 [截止日查询和计划命令](dagster-major-index-quantitative-structure-onboarding-low-level-design-v1.md#51-计划与审批)
2. **一次读取、计算和写入。** 先按第 7 节验收，再登记获批分区。正式计算读取所需列，分钟价格与 MACD 逐根对齐。按日期、指数、周期统计与合同匹配且有完整输入的 K 线，日线及四个分钟周期应分别为 1、8、4、3、2 根，适用范围按第 2 节。应有键缺失或重复就报告对应日期、指数和周期。根数对齐后，用同一批输入计算。当天结果写出并校验后提升到正式目录。中断后用同一计划从头计算，只从第一个未完成日开始写文件。
3. **按数量验收并补录事件。** 对齐预期日期、实际结果文件和已成功校验天数，再按已验收日期统计并补录缺少的 DG 事件。 [操作命令](dagster-major-index-quantitative-structure-onboarding-low-level-design-v1.md#54-操作入口)
4. **接到日更。** 核对历史截止日后的 SSE 开市日。超出自动窗口的未完成分区用同一个日更 Job 补跑。再依次启用分区注册和日更 Sensor，验收首个自动 Run、正式文件和对应的两项检查。 [启用与首日验收](dagster-major-index-quantitative-structure-onboarding-low-level-design-v1.md#55-启用并验收日更)

### 6.1 来源与执行预算（模板 §7A）

以 **2026-11-06** 为本次只读实测的截止日。SSE 日历有 **4,089 个开市日**。按每个交易日一份日线、四份分钟价格、四份分钟指标核对了 **36,801 份文件**，物理文件合计 **253,652,591 字节**。按第 2 节有效起点与开市日计数，预期日线 30,696 根，分钟为 29,388 个指数交易日乘以每天 `8 + 4 + 3 + 2 = 17` 根，共 499,596 根。合计 **530,292 根**，与详细设计第 6.1 节的实际读取结果一致。

下表按指数和周期拆分预期输入量，单位为根。每个指数从各周期有效起点开始按开市日计数。日线每天 1 根，30、60、90、120 分钟每天分别为 8、4、3、2 根。分钟价格与 MACD 对齐后按同一根 K 线计一次。 [Gold 分钟周期合同](../../orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py)

| 指数 | 日线 | 30 分钟 | 60 分钟 | 90 分钟 | 120 分钟 | 合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 上证指数 | 4,089 | 32,712 | 16,356 | 12,267 | 8,178 | 73,602 |
| 深证成指 | 4,089 | 32,712 | 16,356 | 12,267 | 8,178 | 73,602 |
| 创业板指 | 3,990 | 31,920 | 15,960 | 11,970 | 7,980 | 71,820 |
| 科创50 | 1,659 | 12,200 | 6,100 | 4,575 | 3,050 | 27,584 |
| 沪深300 | 4,089 | 32,712 | 16,356 | 12,267 | 8,178 | 73,602 |
| 中证500 | 4,089 | 32,712 | 16,356 | 12,267 | 8,178 | 73,602 |
| 中证1000 | 4,089 | 23,448 | 11,724 | 8,793 | 5,862 | 53,916 |
| 中证A500 | 513 | 3,976 | 1,988 | 1,491 | 994 | 8,962 |
| 上证50 | 4,089 | 32,712 | 16,356 | 12,267 | 8,178 | 73,602 |
| **合计** | **30,696** | **235,104** | **117,552** | **88,164** | **58,776** | **530,292** |

| 项目 | 预算及验收方式 |
| --- | --- |
| 日更 | 单次读入从历史起点到目标日的输入。2026-11-06 的范围为 36,801 份行情和指标文件，530,292 根。只写目标日 1 份结果文件。任一交易日九指数均有效时最多有 `9 × (1 + 8 + 4 + 3 + 2) = 162` 根 |
| 日更实测依据 | 管理员已接受截至 2026-11-06 的全量回放实测开销，读取、对齐和识别共 111.33 秒，峰值内存 2.13 GiB。正式写入和 DG 记录在实际运行中另计 |
| 历史 | 核定 `D` 个交易日则写 `D` 份结果文件，共 `D` 行。按本次估算范围为 4,089 份文件和 4,089 行。无既有事件时，最多补录 `D` 条产出和 `2D` 条检查事件，共 12,267 条。实际补录按已存在事件扣减 |
| SQL、内存和写入 | 使用 DG 配置的 DuckDB 连接做列投影、对齐和 Parquet 写入。日更按月读取并保留至多 `9 × 5 = 45` 个序列的当前状态。Bootstrap 按日写结果并在当次执行目录记录完成位置。Tushare 和 Prod DB 请求、分页均为 0 |
| 中断与验收成本 | 日更重跑读取相同历史范围，只重写目标日。首次初始化重跑同样从头计算，只补写尚未完成的日期。最终核对全部结果分区和事件集合 |
| 执行和停止条件 | 按批准的日期范围执行，正式写入前核对候选占用和可用空间。输入不齐、写前检查不通过或超出批准范围时停止。按管理员要求取消正常计算和中断重算的小样计时 |

存量文件体积用于估算输入规模。读写、恢复与最终验收的文件量及行数见详细设计第 6 节。 [模板 §7A](../templates/dagster-dataset-onboarding-template.html#source-contract-budget) · [DG 性能规范](dagster-data-pipeline-performance-governance.md)

## 7. 开发与验收顺序

1. **A，共用 r4.1 内核，已完成。** `goldenshare-technical-indicators==0.1.0` 已提交为 `42acc9928`，财势乾坤回归和 DG 隔离安装验收已通过。正式 DG 接入按详细设计第 2 节执行。Raw 与 Silver 切片不适用。 [共享包验收](../../../docs/architecture/calculation-operator-shared-package-low-level-design-v1.md#8-实现与验收记录)
2. **C2，Gold 和金样本。** 复用上证 90 分钟 r4.1 同根取消、新钝化的固定预期，逐项核对事件和顺序。另用小样验证成功无事件、输入缺失或重复、失败行，以及从同一起点连续计算与中断后重算一致。 [r4.1 金样本](../../../scripts/research/index_market/tests/test_xxm_r4_following.py) · [续算验证](../../../scripts/research/index_market/tests/test_xxm_r4_restore.py)
3. **D/E，日更入口与 sensor。** 在隔离 DG 中核对实际 job 选择、两项检查的分区键、任一上游未就绪、不同到达顺序、重复触发、断日和查询预算。核对 UI 中文描述、等待原因与失败位置。
4. **F，小样读回、历史初始化和日更。** 先用获准的上证日线和 90 分钟小样，记录源行数、对齐后根数、失败原因和样本、写入及读回行数、事件数。每个日期的一行输出及其中的事件分别对账。通过后按第 6 节核对范围、分批写文件、补录事件和启用日更。历史读取、正式写入、事件补录和启用按实际范围确认。
5. **财势乾坤接入。** 按 [§9](#9-财势乾坤接入技术方案) 切换指数详情页的事件读取，核对读取范围、版本、结果和耗时。

## 8. 开发前确认（模板 §18）

| 核验点 | 当前结论 |
| --- | --- |
| 适用范围、资产登记和入口 | 本文已列明，见第 1、3、5 节 |
| 来源和字段 | 已核对源合同、样本物理类型和历史文件清单。按日期、指数、周期核对正式读取的有效根数 |
| 质量、自动化和界面 | 阻断检查、日更职责、触发和排障已定义。隔离定义和行为测试已通过，见 LLD §7.1 |
| 路径、预算和恢复 | 详细设计已列日更回放和 bootstrap 的文件、行数及恢复口径。管理员已确认本数据集历史回放复用 r4.1 Python 内核 |
| 阶段和验收授权 | 隔离验收和首两个交易日的只读小样已完成。正式安装和加载、历史执行范围、事件补录和启用按 LLD 分阶段确认 |

业务范围、输出字段、历史起点、每日全量重算、18:00 自动检查和换版口径已确认。正式安装、历史执行范围、事件补录和 sensor 启用在相应阶段确认。 [模板 §18](../templates/dagster-dataset-onboarding-template.html#checklist)

## 9. 财势乾坤接入技术方案

### 9.1 页面范围

指数详情页的「量化结构」覆盖九个指数的日线及 30、60、90、120 分钟，识别标记直接使用 DG 的主要指数量化结构数据集 `major_index_quantitative_structure`。沿用现有本机开放范围和日线、分钟接口。首批 K 线和技术指标就绪时发起识别请求，副图开关只控制显示。日线和分钟的量化结构副图都单独读取识别所用的 MACD（12、26、9），用它画曲线、读数和标记。普通 MACD 副图继续用各自图表接口的数据，上证普通日线仍由 `/kline` 通过现有技术指标计算内核计算。今后普通副图即使切换参数，量化结构也继续显示生成识别结果时所用的曲线。晚间 Gold 产出后，按财势乾坤现有默认业务日期在上海时间 20:00 切换的口径，刷新页面读取新结果。切回周期或页签沿用现有请求方式。 [量化结构页面范围](../../../wealth/docs/system/detail-chart-quantitative-structure-requirements-v1.md#4-首批数据与页面状态)

画标记时使用 Gold 的 `display_on_chart`。普通页悬停只展示该根 K 线的时间和事件，同根有多项时按 Gold 顺序显示。网页路由在本机开发版且网址带 `debug=1` 时才加载核验页。核验页直接请求独立的 `/debug/` 接口，沿用原识别计算和参照明细。技术面页签的「下一根预判」继续计算，两种入口分别组装结论和核验明细。 [普通与核验请求拆分 LLD](../../../wealth/docs/pages/index-detail/index-detail-debug-separation-low-level-design-v1.md)

打开上证波段核验时，网页只发一次波段请求。后端沿用原方式读取收盘价、MACD、前段行情和交易日历，算完返回波段结果。网页按日期在已有 K 线上加标记，更早的 K 线加载后用已返回的波段结果补画。日线、九转和趋势仍按页面原有的加载和翻页流程取数。取消整批换图及为换图追加的取数和逐根比较。普通和核验各自复用自己的结果，服务器沿用现有的同时处理数量。

### 9.2 数据怎么读

财势乾坤后端按请求的日期范围和根数，从 SSE 交易日历选出应读的交易日，读主要指数量化结构文件得到已覆盖日期和事件。对已覆盖的 K 线，日线读指数日线技术因子数据集 `index_factor_pro` 的收盘价和不复权 MACD，分钟读主要指数分钟线数据集 `major_index_mins` 的收盘价和主要指数分钟技术指标数据集 `major_index_mins_technical` 的 MACD。沿用识别原来使用的取值，读取范围只覆盖返回窗口。一次识别请求返回曲线点、事件、覆盖范围和状态。网页按指数、周期和 K 线完成时刻对齐，同一根没有事件也照常画曲线。末尾日期尚未产出时显示已可用的范围并提示滞后。明确的识别失败和窗口内的文件缺口走错误提示。 [结果合同](#3-每日结果字段)

### 9.3 实施和验收

先拆后端入口和响应，再接两个网页入口，同版迁移客户端和研究脚本。普通识别请求沿用 4 秒后端预算和原计时口径，交易日历、主要指数量化结构文件和曲线数据读取共用剩余时间。用真实日线和分钟样本核对量化结构 MACD、事件、顺序及等待和失败提示。验收记录实际文件清单、响应和耗时，确认只读取当前窗口所需的文件，历史识别计算、核验代码加载和核验请求均为零。用两副图 MACD 数值不同的样本核对量化结构曲线和标记仍取自己的值。核验页回归原识别计算、预判和波段，以及页面初始化、日线和权重诊断。 [Gold 读取 LLD §8](dagster-major-index-quantitative-structure-onboarding-low-level-design-v1.md#8-财势乾坤接入详细设计) · [普通与核验请求拆分 LLD](../../../wealth/docs/pages/index-detail/index-detail-debug-separation-low-level-design-v1.md)
