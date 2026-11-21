# 指数周线、月线接入技术指标算子库 LLD v1

2026-11-22｜阶段一已实现，DG、Prod 只读验收和开发复核通过，结果见 §7。本文细化[专项方案](technical-indicator-index-period-plan-v1.md)。指数详情接口、页面、股票周月线及正式数据生产另行实施。

## 1. 代码基线与改动位置

开工前用 CodeGraph 和源码核对 `CalculationRequestParser`、`PriceInputSession`、`LakePriceLocator`、`PostgresTechnicalIndicatorPriceSource`、结果组装和日线及分钟线消费者。当时请求、结果和位置目录已经登记 `week/month`，运行时只启用股票日线、指数日线和指数 5 分钟线，两端实际周月线读取分支尚未接通。

[股票日线](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_calculations.py#L54)和[走算子库的上证指数日线](../../src/app/dependencies/index_daily_technical_indicators.py#L48)都把本页首尾日期交给算子库。[计算入口](../../packages/technical_indicators/src/goldenshare_technical_indicators/service.py#L92)合并各指标所需字段和前置历史，`PriceInputSession` 按这个要求调用对应读取器。DG 日线按交易日分文件，一次计算会跨日文件取数。周月线沿用这套取数规则，接入各周期实际存放行情的文件或表。

| 位置 | 本次实现与影响面 |
| --- | --- |
| [位置目录](../../packages/technical_indicators/src/goldenshare_technical_indicators/configuration/datasets.py)、[运行时装配](../../src/app/runtime/technical_indicators/composition.py) | 复用 `index_weekly`、`index_monthly` 两个已登记位置。按当前 `APP_ENV` 装配同一请求所用的 DG 或 PG 读取器，分别允许指数周、月 `none`。先在隔离配置和只读验收中验证，能力通过后才纳入应用装配。本阶段不增加环境变量或单独开关。 |
| [DG 读取器](../../src/foundation/clients/local_lake/technical_indicator_price_source.py)、[定位器](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py) | 在 `create_locator`、`LakePriceLocator.describe`、`_LakePriceStream` 和 `expected_positions` 接入单文件周期源，读取条件使用代码和周期范围。现有 `trade_date=…` 目录枚举、分区日期检查只用于有该分区的原来源。 |
| [PG 读取器](../../src/foundation/clients/technical_indicator_postgres.py) | 在 `create_locator`、`_PostgresPriceLocator.describe`、`open`、`expected_positions` 和 `_PostgresPriceStream` 接入周期数据。使用 `ts_code` 与 `period_start_date` 范围，投影两个物理日期并按日期类型交付。复用会话、取消、超时和清理。周月分支独立于分钟竞价归并及日线复权逻辑。 |
| [输入校验](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py)、[周期范围](../../packages/technical_indicators/src/goldenshare_technical_indicators/time_range.py)、[输出结果](../../packages/technical_indicators/src/goldenshare_technical_indicators/output/result.py) | 同一套日期含义、已有期内截止检查、既有批次校验和结果结构。适配层将正式字段转成现有标准列。复用 `PriceReadSelection`、`SourceDescription`、`PriceSource` 和 `CalculationResult` 的接口形状，无需改公共字段或公式。 |

实际读文件、查数据库的代码放在 Foundation 的现有读取器内，继续通过 `PriceSource` 交付标准行情。App 按运行环境选读取器，路径与表名仍由位置目录提供。指数详情名单、页面字段和翻页状态由后续业务接入负责。现有指数、股票日线及分钟线纳入回归。

## 2. 数据输入和日期映射

来源及字段以 [DG Silver 合同](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py) 和 [Prod Serving 合同](../../lake_console/orchestrator/src/orchestrator/defs/prod_db/index_period.py) 为依据。2026-11-21 的有界只读审计已核对两端现行周、月行情，10 个页面指数当期实有记录且均截至 11 月 20 日。隔离夹具分别按两端实际来源合同构造。独立验收再核对实施所用的四个真实来源。

| 项目 | 本地 DG Silver | Prod PostgreSQL Serving |
| --- | --- | --- |
| 周线 | `/Volumes/datasource/data_lake/silver/index_weekly/full/part-000.parquet` | `core_serving.index_weekly_serving` |
| 月线 | `/Volumes/datasource/data_lake/silver/index_monthly/full/part-000.parquet` | `core_serving.index_monthly_serving` |
| 定位必读字段 | `ts_code` 字符串，`period_start_date`、`trade_date` 均为 `DATE` | `ts_code` 字符串，`period_start_date`、`trade_date` 均为 `DATE` |
| 价格列 | `open/high/low/close` 为 `DECIMAL(18,4)`，指数点位 | 同左 |
| 量额列 | `vol` 为 `DECIMAL(20,6)`、手，`amount` 为 `DECIMAL(20,7)`、千元 | `vol/amount` 为 `NUMERIC(20,4)`，股、元 |

对每个指数、每个周期，源记录按 `(ts_code, period_start_date)` 唯一。`period_start_date` 是源中保存的周期起点，常见为该周期首个开市日。历史首根沿用正式周期数据提供的事实，不能套用指数日线起点或重新按公布日截短该根 K 线。读数模块以源起点归入所属自然周期，校验实际截止日仍在同一周期且不早于源起点。映射后同一自然周期有两根时按来源合同错误处理。

| 算子库标准字段 | 赋值规则 | 用途 |
| --- | --- | --- |
| `period_start` | `period_start_date` 所在周的周一或所在月的第一天 | 选择、排序、确认属于哪一根，输出为 `times[i]` |
| `period_end` | 周五或自然月末，沿用现有周期边界 | 与请求日期范围求交及核对来源版本。这是日历边界 |
| `trade_date`、`source_as_of` | 源 `trade_date` | 保存已发布的实际截止交易日，输出为 `source_as_of[i]` |

周五或月末只是周期边界。实际期末由交易日历及已发布记录确定。DG 国庆样本 `000001.SH` 的 `period_start_date/trade_date` 为 `2026-10-08/2026-10-09`，标准 `period_start` 为 `2026-10-05`。前一周实际截至 `2026-09-30`，并非 `2026-10-02`。上证 2026 年 11 月月 K 在 20 日的样本为 `period_start_date=2026-11-02`、`trade_date=2026-11-20`，输出 `times=2026-11-01`、`source_as_of=2026-11-20`。

`SourceDescription` 表明输入调整口径 `none`、结果价格单位 `index_point`，允许该周期的未完成行情，交易时区为 `Asia/Shanghai`。DG 源单位声明为 `lot/thousand_CNY`，PG 声明为 `share/CNY`，让 `PriceInputSession` 对 DG 成交量乘 100、成交额乘 1000，PG 原值进标准列。价格不走复权因子。量额合法空值原样保留。`pre_close/change_amount/pct_chg` 及页面的单位转换不进入此次算子投影，后续业务按正式周期源和已确认的日线展示口径组装。

DG 的 `_matches_type` 增加 `DECIMAL(20,6)`、`DECIMAL(20,7)` 的精确匹配，保留四价原有精度。Prod 的 `_PostgresPriceStream` 将 `period_start_date` 和 `trade_date` 都声明为日期，量额沿用各自 `NUMERIC(20,4)` 的读数类型。

## 3. 范围定位、读取和返回

1. **解析和定位。** 公开入口 `TechnicalIndicatorService.calculate(CalculationRequest)` 接收指数、`week/month`、`none`、带时区的 `start/end` 及算子参数。`CalculationRequestParser` 解析本环境位置，按上海当地日期比较。目标候选满足 `period_end >= start` 且 `period_start <= end`。沿用 [算子库已有截止检查](../../packages/technical_indicators/src/goldenshare_technical_indicators/time_range.py)，只返回满足请求截止要求的已发布行情。后续页面首屏取初始化返回的实际行情日期，翻页上界为当前首根所在周期之前最近一根实际可用的 K 线截止日。
2. **补读必要历史。** 算子库合并各指标所需字段和前置根数，一次计算只打开一个行情读取流。本次目标和所需前置历史一起读取，所有指标共用，目标范围外的行情只供计算。包含 `price` 时读取四价、成交量和成交额。定位只读取代码和两个日期，目标区间超出 `max_output_rows` 即拒绝。历史定位多看一根，用于判断是否到来源实际起点。确实取到该周期来源首根时，历史不足按现行规则初始化。
3. **按应有周期及截止日校验。** 两端定位时以请求截止日所在周期的已发布日期判断是否只存在晚于请求的版本，在目标根数判定之前按现有 `SourceUnsupportedError` 处理。读数模块将已选的源起点和实际截止日成对留在本次 `SourceReadContext`，供校验及行情交付核对，清理时释放。`expected_positions` 一次读取所需的 SSE 日历。下界取已选历史起点与请求首个相交周期两者较早的一天，再以正式来源的最早周期截住。上界取请求截止日与最新已发布截止日中较早的一天。按完整连续的日历把开市日分组，逐项对比每个应有周期和周期内的最后一个可用开市日。校验结束后继续向通用输入层交付原有的周期起始日序列。两端的行情流在交付批次前也核对两种源日期与定位结果逐项一致。已发布范围内存在缺根、错期、截止日错误、顺序或根数错误时按来源合同错误处理。无目标行情沿用 `SourceReadError`（`detail=数据缺失`）。
4. **DG 执行。** 每次请求访问该频率的一份正式 Parquet 行情文件。先用文件页脚核对字段类型及本次所读列的大小。定位时读取一遍代码和两个日期，限定请求的 `ts_code`，同时记下该指数的来源首根和最新截止日。目标日期最多保留输出上限加一根，用于判断是否超量。前置日期只保留最靠近目标的所需根数，多留一根判断是否到达来源起点。需要从来源起点计算时，也遵守现有输入和内存限制。保留这些日期就能确定范围，省掉 [`LakePriceLocator._bounds`](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L271) 用于找中间位置的第二遍日期读取。接着按选中的周期范围读取行情和对应日期，按批交付并核对日期与定位结果一致。物理起始日期按自然周期的有界范围过滤，涵盖首个开市日不在周一或月首的周期。定位和行情读取前后核对文件身份，确保来自同一文件版本。文件被替换时按来源读取失败退出，重试重新定位。
5. **Prod 执行。** 单请求使用一条 `REPEATABLE READ READ ONLY` 事务。用 `(ts_code, period_start_date)` 唯一索引查询来源首根、末根各一条，再查请求末周期最多两条日期，以便发现晚版本或同周期重复。目标最多取输出上限加一条，前置历史最多取所需加一条，日期查询均读取两个源日期。查询先用 `period_start_date` 锁定物理范围，再按自然周期判断。进入行情流后按选中的物理起止日取所需列，按源起点正序读取。正式验收检查执行计划、投影和扫描范围，原表索引、迁移、读角色及写流程沿用现状。
6. **计算与返回。** 复用内置 `price`、MA、BOLL、MACD、KDJ 的公式和跨批状态。首期验证参数来自[指数日线定义](../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py)：MA(5/10/20/30/60/90/250)、BOLL(20,2)、MACD(12,26,9)、KDJ(9,3,3)。参数以周 K 或月 K 根数计。`OutputCollector` 按同一 K 线序号取目标结果，`times[i]`、`source_as_of[i]`、行情与各算子的第 `i` 项必须对应同一条源记录。`range` 仍表示稳定周期位置的实际起止和根数。每根 K 线只返回一次，预热 K 线不输出，短历史的 MA／BOLL 未满窗口合法留空。

## 4. 配置、权限、中断与重试

| 配置或资源 | 生效与边界 |
| --- | --- |
| `APP_ENV`、`GOLDENSHARE_LAKE_ROOT` | 现有 `Settings` 和部署配置负责生效。`local/dev` 选择 `dg`，`prod/production` 选择 `prod_pg`。正式 DG 读取配置必须指向 `/Volumes/datasource/data_lake`，验收时核对。隔离测试使用测试目录，代码继续沿用现有路径校验。PG 使用已装配会话工厂。部署来源由 App 决定。 |
| `enabled_adjustments` | 已有的应用内位置条目，默认未启用。本阶段仅对 `index_weekly/index_monthly` 启用 `none`。解析和算子能力查询继续读取同一冻结配置。端到端证据分别通过后，以应用装配启用，当前环境是唯一读取位置。 |
| 读取与清理 | DG 打开正式周期文件和必要交易日历，PG 只读两张周月线 Serving 表中的一张及现有日历。申请计算及读取临时资源沿用现有路径。无源端调用、无业务数据写入、无生产任务执行，不改数据库 schema 或 DatasetDefinition。失败或取消停止新读取，释放本请求的扫描器、游标、会话和计算临时表，不返回部分结果。 |

一次计算是一个同步请求。重试从原指令重新定位和计算，单次重试承担一次同范围请求。来源更新后按新快照返回，实际截止日仍不得晚于原请求的 `end`。以取消后同一参数能重新成功、请求结束连接和资源归还作为验收。临时文件仅放 `/private/tmp` 下的本任务目录。

## 5. 性能预算与中断恢复

沿用[现行 Settings](../../src/foundation/config/settings.py) 和 [ExecutionControl](../../packages/technical_indicators/src/goldenshare_technical_indicators/execution_control.py) 的保护，不为这两类数据放宽阈值。

- **单次规模。** 一指数、一周期。目标 `R` 根受现有 500 根上限及所在环境配置限制。前置 `H` 由本次所选算子及参数决定，`R+H` 受当前输入上限约束。按 §3 的指标组合核对现有计算计划，MA250 需要 249 根前置行情，MACD、KDJ 用当前参数时需要 500 根来建立初始状态。各指标共用这 500 根。目标取满且历史充足时，读取 1,000 根，结果返回 500 根。到达来源起点且历史不足时按原规则初始化。行情沿用现有批次读取，默认每批最多 8,192 根。
- **DG 文件成本。** 每次访问相应频率的 1 个行情文件和最多 1 个交易日历文件。2026-11-21 核对了文件页脚，周线文件有 8,890 行、磁盘大小 514,479 字节，月线文件有 2,102 行、磁盘大小 124,578 字节。周线文件和月线文件各只有一组数据，即使只取一个指数，读取时也可能展开同一组中其他指数的列。按页脚记录，读代码和日期列一次、读行情及对应日期列一次、读日历一次，所用列展开后的大小估算为周线 `71,401+640,547+55,911=767,859` 字节，月线 `17,086+151,788+55,911=224,785` 字节。现有 `source_file_bytes` 统计涉及文件的大小，同一文件只计一次。验收另记实际送去计算的根数、峰值内存和分阶段耗时，并核实定位和行情各读一遍。
- **PG 查询成本。** 首尾和末周期合计至多 4 条边界记录，目标最多看 `max_output_rows+1` 条，前置历史最多看本请求所需根数加 1 条并受输入预算限制。行情流交付 `R+H` 根，日历只读取区间内的日期和开市标记。记录实际语句数、返回行数、执行计划和耗时。任何需要无界扫描、改索引或突破当前保护的做法先回到设计核对。
- **现有时间与内存约束。** 默认从请求到达起目标 8 秒内结束，留 2 秒清理，读取和计算的截止时间为请求到达后 `8−2=6` 秒。现有查询内存 128 MiB、单请求内存 256 MiB，以及一次读取单组 Parquet 数据时所用列展开后 32 MiB 的限制同时适用。§6 记录实际耗时、峰值内存及清理成本。达到限制时沿用现有超时或资源错误。
- **恢复与最后验收。** 每端各跑 6 个小样本、2 次上证周线性能请求、1 次中证 A500 周线受控中断和同参数重试，共 10 次。小样本最多送算 `9+111+26=146` 根，性能请求送算 `2×(500+500)=2,000` 根，中断和重试按两次完整输入最多计 `2×111=222` 根。每端合计最多 `146+2,000+222=2,368` 根，两端合计最多 4,736 根。每次请求单独计数，例如第二批展示的周 K 在第一批里也用于算指标。取消后从原参数重试当次请求，已通过的其他样本可以复用。
- **验收的读取成本。** DG 按周线 7 次、月线 3 次的完整开销估算，文件中所用列展开后的大小合计 `7×767,859+3×224,785=6,049,368` 字节。PG 分别记录实际用于定位、查询日历、读行情的语句数和耗时，中断只计已执行的部分。用来独立对照的行情，每端最多另取 1,646 根，其中上证性能请求共覆盖 1,500 个不同的周，小样本按最多 146 根计。两个频率各取一次所需样本的日期、四价、成交量和成交额，复用这一批对照数据。DG 额外展开估算为 `640,547+151,788=792,335` 字节，两项合计 `6,841,703` 字节，按本次样本文件大小估算。对照只取这两个指数的已选范围。

## 6. 验收及样本依据

| 验收项 | 正例与反例 |
| --- | --- |
| 配置与来源 | 两种环境的 week/month 均解析到已登记正式源并用 `none`。反例覆盖未启用、指数请求前复权、源路径／表不符、错误投影或来源失败，核实不会读另一端、日线表或复权因子。 |
| 日期与范围 | 用同一周的周一和周二两个来源版本，各返回一根 K 线。`times` 相同，`source_as_of` 和计算结果随输入变化。核对节前提前收盘的一周、节后首个开市日、自然月末休市、当月尚未结束和相邻两批。整周无交易时没有该周 K 线。反例覆盖错期、日期倒置、同一周期重复及已发布范围内应有的一根 K 线缺失。 |
| 量额、计算和对齐 | 两个来源分别按 §2 造夹具，断言统一输出股、元，量额合法空值保留。一组独立算出的期望值验证收盘序列、MA、BOLL、MACD、KDJ，含预热、短历史、恰好到窗口长度、跨批。故意错排日期或丢一根，验证该批不能通过。源夹具和指标期望由不同依据产生。 |
| 读取范围与限制 | 核对每次计算的一次行情读取包含目标和前置历史，各指标共用，返回根数等于目标根数。DG 定位时只读一遍代码和日期，之后读取所选范围的行情。Prod 核对定位和行情查询均受指数及范围约束。目标等于上限正常返回，多一根按现有规则拒绝。 |
| 失败与既有消费者 | DG 文件换代、读失败及 PG 取消时无半份成功结果，资源归还后按原参数可重试。回归 `test_stage_a_request_parser.py`、`test_stage_b_stock_daily.py`、`test_stage_b_index_minutes.py`、`test_stage_c_output.py` 及上证、股票日线应用集成测试。数据库隔离测试只用隔离 PG，正式只读样本用于验收真实驱动、索引和单位。 |

**执行方式。** 使用仓库里当前版本的算子源码。运行测试或只读验收时，在 `PYTHONPATH` 首位使用 `packages/technical_indicators/src`，保留仓库路径，沿用已安装依赖。周月隔离测试用现行 `CalculationRequest` 参数结构，覆盖周期起始日正确但截止日错误、已有部分版本和只有更晚版本，替代相关旧请求结构的用例证据。既有日线路径回归选用当前本地合同对应的 `test_stock_daily_source_repair.py` 与 `test_index_daily_kline_integration.py`，不借本阶段改动股票 API 或旧测试断言。正式只读验收用本机 DG 文件或既有 Prod 连接配置，先在本次测试配置中只开启目标数据位置，真实验收通过后才接入 App 的常规装配。

**计时方式。** 用同一请求的 `ExecutionControl` 和外部计时分别记录定位、日历、行情读取、计算、结果取回及清理。整次耗时从 `calculate` 调用起到返回或完成清理为止，峰值内存按每个性能请求单独取进程峰值，注明所用口径。现有 `statistics.elapsed_ms` 在结果取回与清理前记录，仅作分段依据。中断验收核对 `resources_released_at`、PG 连接或 DG 文件资源归还，以及同样参数重新成功，不增加结果字段。

**用真实行情对结果。** DG、Prod 各用正式周线和月线，核对实际截止日、四价、量额和指标。行情按源字段精度及明确的单位核对。指标按已有独立参考和误差规则核对。对照数据按 §5 一次采集后复用。

- 上证指数 `000001.SH` 用 `price + MA2`。周线先查 `2026-09-28` 至 `2026-10-09`（2 根），再查 `2026-09-21` 至 `2026-09-24`（1 根）。已从 DG 正式行情及日历核对三根实际截止为 9 月 30 日、10 月 9 日和 9 月 24 日。月线各取前一完整月、当时已发布的本月各 1 根，按各自实际截止发起请求。本轮审计对应 2026 年 10 月 30 日和 11 月 20 日，正式验收使用届时的最新版本。每次最多补 1 根，四次合计最多 `(2+1)+(1+1)+(1+1)+(1+1)=9` 根。
- 中证 A500 `000510.SH` 用 `price` 和 §3 所列全部指标。周线目标为 `2026-11-02` 至 `2026-11-13`，月线目标为 `2026-09-01` 至 `2026-10-30`，均 2 根。两个周期都确认从正式来源实际首根开始计算，历史不足 250 根时 MA250 留空。预算为截至目标的 111 根周线、26 根月线，依据是 [既有来源审计 §2.1](../../lake_console/docs/design/dagster-index-period-onboarding-plan-and-low-level-design-v1.md#21-11-个指数的历史起点与完整性) 及本轮对 DG 文件的有界计数复核。目标加前置历史分别为 `2+109` 和 `2+24` 根。验收前按代码和日期复核两端范围。用同一个周线样本在两端各做一次受控中断，清理后按原参数重试。

**按实际看图顺序测上证周线。** DG、Prod 分别用 `000001.SH` 跑两次，均请求 `price` 和 §3 的全部指标。先取截至 2026-11-20 的最新 500 根，然后接着取更早的 500 根。第二次请求以上一批最早一根之前的实际可用截止日为上界。每次各取 500 根前置历史参与计算。

| 请求 | 起止日期 | 预期返回的首尾实际截止日 | 前置历史最早实际截止日 | 日历覆盖范围 |
| --- | --- | --- | --- | --- |
| 首批 | `2017-02-13` 至 `2026-11-20` | `2017-02-17` 至 `2026-11-20` | `2007-05-11` | `2007-05-07` 至 `2026-11-20`，含首尾 7,138 个自然日 |
| 向左取前一批 | `2007-05-07` 至 `2017-02-10` | `2007-05-11` 至 `2017-02-10` | `1997-04-18` | `1997-04-14` 至 `2017-02-10`，含首尾 7,243 个自然日 |

2026-11-22 开工审计已在 DG、Prod 对照表中 1,500 个不同的上证周线日期和 SSE 日历，边界一致。每次核对 `statistics.source_rows` 为 1,000 根，返回 500 根。对照正式来源，确认两批拼起来没有重复、没有漏掉应有的 K 线，每根的日期和指标一一对应，两批首根的 MA250 均有值。每次分别记录定位、行情和日历读取、计算、清理、整次耗时及峰值内存，与 §5 的现有限制对照。指数详情阶段再用页面的首批加载和左拖验收整体效果和耗时。

验收记录写明各环境的文件或表、代码、日期、目标和预热根数、同一根 K 线的两种日期与输出值，以及选中行组或 PG 执行计划、读取及计算耗时、清理结果。新方案与 LLD 的文档校验只证明文件和引用可用。本阶段通过需以真实来源运行计算及回归为准，不能把现有数据就绪、已有的日期字段测试或隔离替身结果当作两端算子接入通过。

## 7. 实施与独立复核记录

2026-11-22 在两端各运行 §6 的 10 次受限调用。每端从正式来源独立读取 1,640 根对照行情，分别是上证周线 1,500 根、月线 3 根，中证 A500 周线 111 根、月线 26 根。按两端实际单位分别换算，使用独立的均值、总体标准差和逐根递推对照 MA、BOLL、MACD、KDJ。成功请求的两种日期、四价、量额、指标和空值均通过。上证两批首根 MA250 有值，中证 A500 输入从来源实际首根开始，MA250 留空。

| 环境与请求 | 行情输入／返回 | 定位 / 日历 / 行情读取 ms | 计算 / 结果 / 清理 ms | 整次 ms | 单次进程峰值 RSS MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| DG，上证首批 | 1,000／500 | 5.16 / 16.19 / 2.49 | 27.38 / 1.59 / 1.59 | 76.97 | 207.67 |
| DG，上证前一批 | 1,000／500 | 4.92 / 16.11 / 2.45 | 25.16 / 1.52 / 1.28 | 71.93 | 197.02 |
| Prod，上证首批 | 1,000／500 | 408.22 / 77.31 / 88.83 | 250.97 / 1.98 / 22.48 | 929.79 | 218.23 |
| Prod，上证前一批 | 1,000／500 | 523.59 / 80.39 / 91.24 | 256.24 / 2.29 / 22.28 | 1,047.61 | 207.19 |

每个性能请求用独立的本机进程测量。Prod 通过既有连接访问正式 PostgreSQL，只读，并计入连接和网络开销。RSS 包括解释器与依赖，单次测量包含独立进程启动后的占用高点。整次耗时还包含计算连接准备、输入批次处理和控制开销。四次结果的实际首尾日期均等于 §6 表中边界。DG 每次扫描 1 个行情日期行组并打开 1 个行情读取流。Prod 每次执行 7 条业务查询，含定位 5 条、日历 1 条、行情 1 条，沿用原超时及事务控制。审计已用真实执行计划核对目标和前置查询使用 `uq_index_weekly_serving_ts_period`。

两端各在中证 A500 周线第一批 111 根交付后注入取消，返回取消错误，未交付部分结果，随后按相同参数重试成功。DG 取消清理 1.10 ms，重试 47.24 ms。Prod 取消清理 39.25 ms，重试 680.71 ms，连接已归还。包括取消前读到的记录，每端读取预算为 2,368 根，两端合计 4,736 根。

| 复核约束 | 代码与独立验证 |
| --- | --- |
| 单环境、指定指数及周期、只启用 `none` | [应用装配](../../src/app/runtime/technical_indicators/composition.py)只增加两个指数位置。测试核对来源发现与解析配置一致、股票周月线未启用、指数前复权请求拒绝。 |
| 所属周期与实际截止日 | [共同日期规则](../../src/foundation/clients/technical_indicator_index_period.py)独立对照 SSE 开市日及应有周期。两端隔离用例验证错日期、缺整根、同周期重复、来源只保留更晚版本和整周休市。合法部分周期更新时仍是同一根。 |
| 限制读取、同版行情与统一单位 | [DG 单次日期定位](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py)、[行情文件版本检查](../../src/foundation/clients/local_lake/technical_indicator_price_source.py)、[PG 定位和流](../../src/foundation/clients/technical_indicator_postgres.py)逐根对回源日期。隔离 PG 在选定日期后并发修改测试表，当前请求仍看见原行情，下一请求才读到新值。DG 文件替换后当前请求失败，同参数重新读取成功。真实样本复核 500／1,000 根及股、元。 |
| 回归与范围 | [专项测试](../../tests/foundation/technical_indicators/test_stage_b_index_period.py)新增 24 项，覆盖真实隔离 Parquet、PG、跨批计算和边界。与现有解析、日线、分钟线、结果和依赖边界合计 100 项通过。CodeGraph 和差异复核覆盖应用装配、两个读取器、共用输入及既有消费者。变化限于指数周月线和该请求的临时日期状态。 |

验证使用本工作树的 `packages/technical_indicators/src`。可用同一 `PYTHONPATH` 运行 `test_stage_b_index_period.py`、§6 四份基础回归、上证及股票日线应用回归和 `tests/architecture/test_subsystem_dependency_matrix.py`。文档完整性、专项引用和差异检查通过。静态检查有两条未使用导入提示，与改动前相同。正式数据验收使用只读事务及 DG 正式文件，应用接入代码仍在工作树，生产部署及页面验收另行执行。
