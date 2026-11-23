# 股票周线、月线算子库 LLD v1

**2026-11-24｜阶段一股票日线读取修复、阶段二股票周月线区间计算和阶段三股票详情接入均已完成验收。** 本文细化[需求](technical-indicator-stock-period-requirements-v1.md)及[专项方案](technical-indicator-stock-period-plan-v1.md)。各阶段验收分开记录。

<a id="stock-daily-read-repair"></a>

## 独立修复现有股票日线读取

修复在新增股票周月线能力之前独立实施和验收。范围为 DG 股票日线的两项重复读取。对已有的股票日线及九转、指数日线和周月线、分钟线及相关业务入口做回归。各项改动以请求内的数据和资源为边界，Prod 及现有复权基准因子的读取沿用原有行为。

| 现有读法 | 修复位置与方法 | 现有行为的验收 |
| --- | --- | --- |
| DG 股票日线定位读日期，行情交付时再次打开同一文件取价。每个交易日分区对同一股票最多一条，正常日线无需按序号再扫日期找边界。 | [DG 定位器](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L243)用同一个 Parquet 读取器检查文件头和读取所需列。对同一股票用日线日期计数、确定目标和前置起点，保留选中的单股记录，经同一次请求的读数状态交给[行情读取器](../../src/foundation/clients/local_lake/technical_indicator_price_source.py#L391)，按原批次和升序交付。 | 保持目标范围、首尾日期、前置历史、源起点和分区日期判断。保留键列与行组限制，价格列合同和大小错误仅在选中时生效。覆盖目标行数正好达到上限、超限、合法空范围、候选文件无该股以及名单内价格列异常。 |
| DG 逐日处理停牌文件，每次先开文件检查行组大小，再开文件读选中的停牌事实。 | 在 [DG 停牌事实读取](../../src/foundation/clients/local_lake/technical_indicator_price_source.py#L273)中按本次所需日期处理。每份停牌文件用同一个 Parquet 读取器检查行组并按批取该股所需列。 | 保留停牌分区日期校验、文件错误、行组大小限制及全日停牌判断。全日停牌、应有日线却缺失、日线与全日停牌冲突均维持原判定。 |

只在 DG `stock_daily` 定位和 `stock_suspend_daily` 事实读取启用。行情保留范围受现有输出、前置、输入及文件上限约束，每个已选文件最多保留一条紧凑记录。取消或失败时按现有执行清理关闭读取器并清除请求内记录，使用相同参数从头重试。

### 修复阶段的回归和通过条件

- **修复前记录基线，修复后逐项对照。** 用同一环境、相同输入和同口径数据比较 `calculate()`。目标及前置行数、交易日期、四价、量额、指标值和空值位置、输出结构、错误及取消行为须符合现有合同。定位行数、实际文件打开次数、SQL 查询数和耗时单独记录，反映实际读取变化。
- **用隔离测试覆盖边界。** 运行现有[股票日线读取测试](../../tests/foundation/technical_indicators/test_stage_b_stock_daily.py)、[股票日线接入回归](../../tests/app/technical_indicators/test_stock_daily_source_repair.py)、[指数日线](../../tests/app/technical_indicators/test_index_daily_kline_integration.py)、[指数分钟线](../../tests/foundation/technical_indicators/test_stage_b_index_minutes.py)、[指数周月线](../../tests/foundation/technical_indicators/test_stage_b_index_period.py)及[取消测试](../../tests/app/technical_indicators/test_execution_cancellation.py)。覆盖股票不复权及前复权、九转、历史分页、短历史以及日线和停牌事实冲突。新增用例须能识别修复前的实际重复读取，也须证明必要校验仍执行。
- **用 DG 真实样本对照。** 截至 2026-11-20，用平安银行股票日线测首批和向前一批。每批目标 500 根，另读现有默认指标组合需要的前置历史，历史足够时最多 1,000 根输入。修复前后各测一次，合计 4 次只读调用，最多 4,000 根日线输入，日期定位、停牌和复权因子读数另计。在隔离环境测试一次读数中止和同参数重试，分别记录已读数量及释放资源开销。Prod 保留现有路径回归。
- **读数与资源条件。** 核对 DG 行情定位与取价共用所需记录，停牌文件头和选中记录共用读取器。按路径核对实际文件打开次数，唯一文件数另用于现有文件预算。继续遵守 6 秒工作时限、8 秒总时限、内存与输入上限。首次、复跑的缓存条件随记录保留。两项重复读取均减少，且现有功能回归通过，修复轮次即通过。

### 2026-11-23 阶段一验收

在同一台机器上用 DG 正式数据调用算子库，修复前后各测首批和向前一批。每批返回 500 根平安银行前复权日线，另用 500 根历史日线计算指标。四价、成交量额、交易日期、指标值及空值位置、九转和返回的行情范围逐项一致。修复前后各用一个进程，未清空系统文件缓存。

| 请求 | 返回日期 | 修复前 | 修复后 |
| --- | --- | ---: | ---: |
| 首批 | 2024-10-31 至 2026-11-20 | 3.867 秒 | 1.895 秒 |
| 向前一批 | 2022-10-10 至 2024-10-30 | 3.316 秒 | 1.404 秒 |

每批的 1,000 份日线文件现在各打开一个读取器，省去原有的 1,000 次独立读日期和 1,000 次再次开文件取价。1,000 份停牌文件也从各打开两次减为各打开一次。DuckDB 执行入口调用从 1,038 次减至 38 次，标量查询入口调用从 1,003 次减至 3 次。这里记录的是程序调用次数。

回归共通过 95 项，其中 12 项用本机隔离 PostgreSQL 验证现有数据库读取。用修复前代码跑新增用例时，重复开文件用例按预期失败。在隔离 Parquet 样本中读到一行后取消，确认文件关闭，释放资源约 0.7 毫秒。相同参数重试约 20 毫秒，读取 3 根，返回 2 根，日期和行情符合预期。

## 1. 现有流程与改动位置

阶段三前，股票 `/kline` 及页面仅使用日线 K 线合同，本地日线已随回包提供九转标记。阶段二在算子库启用 `stock_weekly`、`stock_monthly` 的 `qfq` 能力并分别接入 DG、Prod。九转按证券类型、周期和复权口径声明周月支持。表中股票详情接线属于阶段三。

| 位置 | 改动和边界 |
| --- | --- |
| [配置](../../packages/technical_indicators/src/goldenshare_technical_indicators/configuration/settings.py)、[运行装配](../../src/app/runtime/technical_indicators/composition.py)、[解析和能力](../../packages/technical_indicators/src/goldenshare_technical_indicators/request_parser.py) | 股票周月沿各自已登记数据集接入 `qfq`。解析和[能力查询](../../packages/technical_indicators/src/goldenshare_technical_indicators/discovery/catalog.py)使用同一配置。现有日线、分钟线和指数的能力保持原有规则。 |
| [DG 读取器](../../src/foundation/clients/local_lake/technical_indicator_price_source.py)、[Prod 读取器](../../src/foundation/clients/technical_indicator_postgres.py) | 路由按证券类型对应的数据集和频率决定，股票读股票周月成品，指数按原路径读取。股票按一股、一个周期范围，保留定位时已经读取的成品记录给指标使用。 |
| [计算入口](../../packages/technical_indicators/src/goldenshare_technical_indicators/service.py)、[输入会话](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py) | 股票成品输入与目标均为 `qfq`，直接交付 `PriceBatch`，不触发复权基准或逐日股票复权因子读取。指标按周期计算。 |
| [计算入口及读数准备](../../packages/technical_indicators/src/goldenshare_technical_indicators/service.py#L77)、[计算引擎](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/engine.py#L103) | 算子库轮次先接入返回根数和预热精度两项独立配置，按次传给读数模块和指标计算。现有调用省略配置时走原有默认规则。详见 §4.1。 |
| [九转定义](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/nine_turn.py)、[计算校验](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/dependencies.py)、[能力查询](../../packages/technical_indicators/src/goldenshare_technical_indicators/discovery/catalog.py) | 计算校验和能力查询共用支持范围，同步开放股票前复权周、月线九转，保留现有日线支持。登记周、月时须同时限定证券类型和复权口径，因为单按周期筛选会把指数周月线也列为支持。沿用原九转公式及输出。 |
| [股票详情 API](../../src/biz/api/wealth/market/stock_detail.py)、[股票详情 DTO](../../src/biz/schemas/wealth/market/stock_detail.py)、[股票详情页面](../../wealth/src/pages/stock-detail/StockDetailPage.tsx) | 算子库验收后，现有 `/kline` 接入周、月分支。日线接口行为及分钟线、趋势通道各自调用维持现行规则。股票周月线的行情、指标、九转及延迟状态来自同一回包，见 §3.4。 |

## 2. 读取范围、来源和字段

| 数据 | DG 正式 Silver | Prod PostgreSQL |
| --- | --- | --- |
| 股票前复权周线 | `silver/quote/stock_weekly/week_end={week_end}/part-000.parquet` | `core_serving.stk_period_bar_adj`，`freq=week` |
| 股票前复权月线 | `silver/quote/stock_monthly/month={month}/part-000.parquet` | 同表，`freq=month` |

DG 路径相对于 `/Volumes/datasource/data_lake`。按股票代码和周期读取 `trade_date`、`open_qfq`、`high_qfq`、`low_qfq`、`close_qfq`、`vol`、`amount`。目标页提示框所需的成品 `pct_chg` 和首屏目标周期的 `end_date` 随同一批成品记录读取，交接见 [§3.2](#stock-period-read-handoff)。DG 样本中两种日期为 `YYYYMMDD` 文本，按日期解析，Prod 为 `DATE`。本地只读 DG，Prod 只读 PostgreSQL，运行时不读发布记录、股票不复权日线或复权因子来取得周月行情，也不重新合成周月 K。

量额按股票日线的单位处理。源成交量按手、成交额按千元，算子库输入时分别乘 100 和 1000，输出为股、元。股票 `/kline` 组装时恢复现有日线接口和图表的手、千元口径。DG 平安银行 2026-10-30 周 K、2026-10 月 K 的成品量额分别与同周期 5 根、17 根 DG 日线相加一致到成品精度。Prod Serving 保留源量额原值，截至 2026-11-20 的平安银行最新周、月成品与 DG 的四价、量额和涨跌幅一致。[输入单位换算](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L14) · [Prod 发布映射](../../src/foundation/ingestion/stock_period_adj_delivery.py#L91) · [股票日线回包](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py#L138)

## 3. 日期、分页与延迟处理

1. **周线首屏和续页。** 详情后端把截止日、返回根数和指标配置交给算子。算子按截止日所属自然周向前选成品，首期每页最多 100 根，即使当周成品 `trade_date` 是较晚的周五，也按所属周期找到该行。续页以本页最早周期起始日为排他上界。算子只读取本页所需成品和 §4.1 所需的前置历史，首期最多补 359 根。是否还有更早的成品由算子从本次读数判断。正常无目标由算子返回空页，接口据此组装空结果。
2. **股票周线历史起点。** 展示、翻页和预热都从 `2014-01-02` 所在自然周开始。起点判断允许自然周起始日 `2013-12-30`，DG 读取 `week_end=2014-01-03` 的首周成品，Prod 按同一所属周取数。包括平安银行在内，有 `2014-01-03` 成品的个股整根保留，原 `trade_date` 用于展示。首周无需查个股在起点前的日线或停牌，也无需拆分或重算。更早的自然周在范围之外。覆盖范围内周中新股照常保留其首根成品。月线从各端最早正式成品返回到目标月，一次返回全部可用月 K，额外预热 0 根。现有算子库的通用输出和资源上限照常适用。
3. **日期分别有用途。** 算子以自然周期起始日 `times` 对齐行情、指标、九转计数和翻页。股票周月线新增读取路径将成品 `trade_date` 作为随结果逐根返回的 `source_as_of`，该值是成品的周期日期。历史 K 线直接使用它。首屏最新一根由股票详情后端按下节确认显示日期，K 线、指标、九转标记、横轴和提示框共用。翻历史页时，页内最后一根仍用历史成品日期。既有指数的 `source_as_of` 仍按指数自身实际截止日组装。

<a id="stock-period-suspension"></a>

**历史上整周或整月停牌。** DG 和 Prod 股票周月线用选中的个股成品周期作为行情输入会话的预期日期。历史周期因整期停牌而没有该股成品时，图表直接跨过该周期，分页、预热、九转和其他指标按现有 K 线逐根计算。继续核对送入周期的顺序、根数以及首尾边界。当前周期是否应有行情按 §3.1 处理。现有指数校验按交易所开市日推导每个周期的行情，继续用于指数。[现有指数周期校验](../../src/foundation/clients/technical_indicator_index_period.py#L128) · [行情输入会话的日期检查](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L141)

<a id="stock-period-freshness"></a>

### 3.1 页面行情日期锚与个股应更新日

- **整个页面共用行情日期锚。** 股票详情初始化使用现有 `MarketPageContext` 产生 `pageContext.tradeDate`。交易日北京时间 20:00 前给出此前最近开市日，20:00 起给出当天，休市日给出最近开市日。同一次页面加载、周期切换及后续行情查询复用初始化给出的锚点。历史翻页用自己的截止边界选择更早的成品，页面行情日期锚照常保留。参见[现有首屏用法](../../wealth/src/pages/stock-detail/StockDetailPage.tsx#L135)。
- **后端统一推导目标周期和个股应更新日。** 首屏把页面行情日期锚、目标周期和截至锚点的应有交易日保存在同一份请求日期上下文，供显示日期和延迟状态复用。沿用 [DG 日线日期事实读取](../../src/foundation/clients/local_lake/technical_indicator_price_source.py#L325)和 [Prod 日线日期事实读取](../../src/foundation/clients/technical_indicator_postgres.py#L199)里的交易日历、上市退市和全日停牌来源，复用 `scheduled_stock_days` 和 `full_day_suspension` 的判定规则。只读该股和目标周期起始日到页面锚之间的事实，同一请求已经读到的日历及用于股票身份的上市退市信息直接复用。最后一个应有交易日就是个股应更新日。直接调用未提供页面日期的周月线接口时，按已有市场上下文规则解析一次。续页继续返回原页面锚，省去当期停牌和日历范围读取。目标周期内无应有行情时，显示已有历史，按正常无当期行情处理。[日线日期函数](../../src/foundation/clients/technical_indicator_stock_daily.py#L59)

<a id="stock-period-read-handoff"></a>

### 3.2 复用通用取数入口和同一次读数

本地股票日线已使用 `CalculationRequest.latest_rows` 和 `TechnicalIndicatorService.calculate_with_source()`，该方法返回 `CalculationWithSource`，包括计算结果、实际读到的范围和同一次读数获得的信息。阶段三沿用这个入口，将 DG、Prod 股票周月线选页接入 `describe_stock_period`。原按日期区间计算继续适用。[通用取数 LLD](technical-indicator-read-optimization-low-level-design-v1.md#2-计算指令与读数结果) · [本地日线调用](../../src/app/dependencies/stock_daily_technical_indicators.py#L192) · [请求解析](../../packages/technical_indicators/src/goldenshare_technical_indicators/request_parser.py#L29)

| 股票前复权请求 | 传给 `calculate_with_source()` 的条件 | 由算子完成 |
| --- | --- | --- |
| 周线首屏及续页 | `period=week`、`adjustment=qfq`、`end`、`latest_rows` 和首期指标；`start` 省略。配置 `output_rows=100` 和 `warmup_error_budget=0.00001`。 | 从截止日所属自然周往前，选最近 `latest_rows` 根可用成品。沿用 `2014-01-02` 所在周起点。按 §4.1 读更早的预热，交付本页和下一页截止日。 |
| 月线全历史 | `period=month`、`adjustment=qfq`、`end` 和首期指标；`start`、`latest_rows` 和两项覆盖配置均省略。 | 由股票月线读取模块从正式成品起点读到截止月，共用现有输出上限。计算从实际首根开始，额外预热为 0 根，返回空游标。 |
| 原日期区间调用 | 传 `start` 和 `end`，沿用现有入口、配置和校验。 | 按起止范围计算，超限及空区间沿用原有处理。 |

1. **请求和执行。** 在 `CalculationRequest` 和解析器中开放 DG、Prod 的股票前复权周线按根数读取。在股票前复权月线的同一内部入口中，允许只给 `end`，保留其他调用方式的日期约束。将 `calculate()` 已支持的 `output_rows` 和 `warmup_error_budget` 交由 `calculate_with_source()` 传入同一个 `_calculate_request()`，沿用既有上限和精度校验。周线的请求根数与输出上限分别校验，月线仍使用环境上限。仅股票周月线首屏需要确认当期成品覆盖日，由已有首屏上下文设置内部选项传给读数模块，无需外部新增参数。[通用计算方法](../../packages/technical_indicators/src/goldenshare_technical_indicators/service.py#L79) · [读取指令及结果](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/contracts.py#L66)
2. **沿用已有股票周月线读数。** 两端共用 `describe_stock_period` 确定目标与预热范围。DG 由现有读取器倒序遍历所需周期 Parquet 分区，按股票代码取行情，每个分区只打开一次。Prod 继续用股票代码、频率和有界 `trade_date` 条件，按日期倒序限量。周线选完目标后，把顺手读到的更早一根用于预热，补读从本次最早已读成品的自然周期之前开始；续页只取目标根数时，从最早目标周期之前补预热。目标、预热及翻页判断复用已读记录。月线一次读截止月以内的全部可用记录，沿用现有超限处理。无需另查最早月、总根数或游标。[共用股票周月读取](../../src/foundation/clients/technical_indicator_stock_period.py#L47) · [DG](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L451) · [Prod](../../src/foundation/clients/technical_indicator_postgres.py#L288)
3. **当前周期和下页截止日。** 首屏保留截止日所属自然周期的成品信息。该条成品 `end_date` 无法确认时，由算子在选择本批时将其排除，仍保留该条覆盖信息供页面提示。周线首屏读取至多 `latest_rows + 1` 根候选，用于补足这一根或作为已读到的第一根预热。若历史足够，仍交付请求根数；历史不足返回实际根数。周线用更早一根已读成品的 `trade_date` 填 `SourceReadFacts.previous_target_date`，直接作为下一页截止日。下一次按该日期所属周读取，遇整周无行情也能接到前一根实际成品。没有更早记录时该字段为空。月线全量返回空游标。普通空页复用 `CalculationWithSource.result=None`，当前周期有成品但覆盖日不明时，仍把当期成品信息随空页交付。[共用返回结构](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/contracts.py#L66) · [现有空页处理](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L52)
4. **使用同批数据组装。** `SourceReadContext` 保存本批成品，`StockPeriodStream` 直接交给计算引擎。原 `price` 算子交付前复权四价、成交量和成交额；`period_bars` 内的成品涨幅 `pct_chg` 和覆盖日 `end_date` 与 `times`、`source_as_of`、指标及九转逐根对应。当期覆盖信息复用 `PeriodBarMetadata`，经现有 `SourceReadFacts` 另带一个可空的当期成品字段，以便区分当期缺行与覆盖日未知。详情后端按 §3.1、§3.3 用这份信息确认显示日期和更新状态，按算子顺序组装 DTO，直接使用算子游标。组装过程的额外行情读取、选页和游标计算均为零。前端按回包绘图。请求复用现有执行时限、取消、失败处理和资源清理。[行情流](../../src/foundation/clients/technical_indicator_stock_period.py#L92) · [股票周期成品元数据](../../packages/technical_indicators/src/goldenshare_technical_indicators/contracts.py#L185)

2026-11-23 上午的只读审计中，11 月 20 日应更新的 5,572 只股票在 DG 和 Prod 的最新周、月成品都满足 `end_date=2026-11-20`。成品中较早的日期涉及 5 只当天全日停牌的股票，两端逐只核对，日期均对应本月该股最后一笔日线。本次审计覆盖这一次应更新日。

### 3.3 状态和页面处理

| 情况 | 页面处理 |
| --- | --- |
| 当期成品的 `end_date` 达到该股应更新日 | 最新一根标到该股应更新日，状态使用 `READY`。 |
| 该股应有行情，当期成品缺行或 `end_date` 较早 | 保留旧行情和同批指标，状态为 `DELAYED`。本周期已有较早成品时，标截至其 `end_date` 的最近应有交易日。只剩历史周期时使用最后一根的 `trade_date`。 |
| 当期成品有行，`end_date` 为空或无法解析 | 展示有可标日期的历史记录及对应指标、九转标记。状态为 `DELAYED`，当期覆盖日按未知处理，图旁提示「暂未确认最新周线／月线已更新」。 |
| 该股在目标周期内没有应有交易日 | 有历史则正常展示，状态为 `READY`；无历史用 `EMPTY`。 |
| 历史续页无更早成品，或读取失败 | 成功到头返回 `EMPTY` 和空游标。读取失败走现有错误响应，浏览器保留已加载的历史并允许重试该页。 |

后端返回状态、该股应到日期及可确认的已显示日期。前端在当前周、月图表旁显示对应提示，以首屏回包更新状态，收到 `READY` 后撤下，历史翻页照常保留首屏状态。周二 20:00 前，周一版是正常。20:00 起应有周二行情而只有周一版时，提示「周线尚未更新到周二，当前显示周一数据」。以该规则同样验收月线。重新进入该周期或刷新页面时重新取首屏，数据补齐后用这次回包更新图表和提示。

<a id="stock-period-page"></a>

### 3.4 股票详情接口与页面接入

1. **接口。** 本地和 Prod 都沿用 `GET /api/v1/wealth/market/stock-detail/kline`，以 `period=week/month` 分流，前端传 `adjustment=forward` 和初始化的 `tradeDate`。日线仍是默认周期，分钟线沿用现有独立入口。`/page-init` 在当前环境启用股票前复权周月线后公布相应周期和九转能力。沿用现有请求、鉴权、普通与调试模式的入口。

   入口保留 `limit` 是否省略的信息，再按周期处理。日线缺省使用 500 根，周线缺省使用 100 根，可取 1～100 根，超出沿用参数错误响应。月线页面省略 `limit`，按算子库现有输出上限一次取可用历史。直接请求周月线时，`tradeDate` 省略就按已有 20:00 规则解析一次，`endDate` 省略就用补齐后的 `tradeDate`。正常首屏的 `endDate` 等于页面锚。周月线页面只使用页面锚或服务端给的下一页截止日，无用户日期输入和时间漫游。`startDate` 继续用于原日线日期区间请求，周月线正常调用省略它。[现有入口的默认值](../../src/biz/api/wealth/market/stock_detail.py#L72) · [现有日线首屏判断](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_calculations.py#L55)

2. **翻页。** 周线每页最多 100 根，页面首批和续页均请求 100 根。首批 `endDate` 取页面行情日期锚，续页保留原 `tradeDate`，把上次 `meta.nextEndDate` 作为新的 `endDate`。后端把这个截止日和根数交给算子，将 `source_facts.previous_target_date` 原值填入 `meta.nextEndDate`。周线到历史尽头及月线全历史回包均返回空游标。后端与前端区分正常到头和请求失败，失败时保留已显示的 K 线、指标和九转，重试沿用该页请求及配置。
3. **回包。** DG、Prod 共用周月响应结构，加入现有路由的响应类型声明。`period` 为 `week` 或 `month`，`adjustment=forward`，`sourceAdjustment=qfq`，沿用 `pageContext`、`stockRef`、`bars`、`meta`、`dataStatus`，并返回 `nineTurnMarkers`。`meta.count` 等于 `bars` 根数，`meta.limit` 是周线请求根数或月线现有输出上限，`meta.startDate` 为 `null`，`meta.endDate` 为本次截止日，`meta.nextEndDate` 直接取算子的返回值。首屏 `dataStatus.expectedTradeDate` 是个股应更新日，无当期应更新日时沿用非空的页面锚；续页用页面锚。`observedTradeDate` 是本批最后一根可确认的显示日期，空批为 `null`。延迟提示用 `dataStatus.note`，即使没有历史可画也显示延迟提示。标记使用[日线现有组装规则](../../src/biz/services/wealth/market/nine_turn/nine_turn_response_policy.py#L94)，传入与 `bars[].tradeDate` 相同的日期。只画 1–9，9 沿用原样式，0 和 10–13 留空，无标记时返回 `[]`。调试回包从同次执行记录来源及参数。股票已有日行情摘要仍由原日线流程提供。
4. **前端。** 在[股票详情页面](../../wealth/src/pages/stock-detail/StockDetailPage.tsx)接入周、月分支。统一从该周期 `/kline` 回包更新 K 线、指标、九转图层和延迟状态，股票的日行情摘要仍使用现有日期和数据。图表按股票代码、周期和页面行情日期锚区分，切换周期时用该周期首屏初始化视野。周线向左拖动后将更早的一批按日期左接，沿用当前图表标识，保留视野和首批状态。月线直接绘制全部可用记录。九转沿用现有开关和样式，切换开关直接使用已加载的结果。周月分支使用回包标记，绕过独立九转请求。切股或切周期后取消过期请求并忽略迟到回包。切回周线或月线时按 §3.3 重新请求首屏。[现有图表视野处理](../../wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.tsx#L603) · [现有指数周期首屏加载](../../wealth/src/features/index-detail/controller/useIndexPeriodSeries.ts#L53)

<a id="stock-period-tooltip"></a>

### 3.5 周月线提示框和预留字段

- **接口。** DG、Prod 的周线首批、周线续页和月线回包中，`changePct` 取同条成品的 `pct_chg`，单位为百分数，量额按 §2 转换。每根 `bars[]` 的 `amplitude` 和 `turnoverRate` 首期均序列化为 `null`，本次未读的前收、涨跌额和量比也留空。读数和指标计算沿用 §2 和 §4 的字段范围，振幅和换手率的取数与计算留到独立需求。[股票 K 线字段](../../src/biz/schemas/wealth/market/stock_detail.py#L150)
- **提示框。** 显示日期、前复权开高低收、成品涨幅、成交量和成交额。周、月分支省略振幅与换手率两行，响应映射保留这两项的空值，避免沿用日线映射把空值转成 `0`。后续需求通过这两个字段接入真实数值。[现有行情映射](../../wealth/src/features/stock-detail/api/stockDetailViewModelAdapter.ts#L35) · [现有股票提示框](../../wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx#L429)

<a id="stock-period-phase-three"></a>

### 3.6 阶段三代码对照和实施顺序

| 顺序 | 开工前代码 | 阶段三修改 |
| --- | --- | --- |
| 1. 算子 | `CalculationRequest.latest_rows` 和 `calculate_with_source()` 已在本地日 K 等链路使用。解析器尚未开放 DG、Prod 股票周月线的新调用方式。`describe_stock_period` 已能按区间共用源数据、计算并返回成品覆盖日和涨跌幅。 | 按 §3.2 扩展现有通用入口，接 DG、Prod 的周线按根数读取和月线全历史。复用成品读取器、预热、正常空页及清理流程，补齐同批成品覆盖信息和周线游标。先独立通过两端算子验收。[请求解析](../../packages/technical_indicators/src/goldenshare_technical_indicators/request_parser.py#L29) · [股票周月读数](../../src/foundation/clients/technical_indicator_stock_period.py#L47) |
| 2. 后端 | `/kline` 默认日线和 500 根，日线校验拒绝其他周期。本地股票日线已用 `calculate_with_source()` 获取行情页，Prod 股票日线仍按原流程运行。`/page-init` 只声明日线 K 线能力。 | 按 `period` 分流到相应的请求默认值和校验。现有 App 装配调用共用入口并复用请求执行控制。业务层使用统一日期上下文和算子返回值组装 §3.3、§3.4。`StockDetailQueryService._page_options()` 依据当地运行环境的股票前复权周月线能力公布周期和九转。接口类型同时覆盖周月响应和原日线响应。[路由](../../src/biz/api/wealth/market/stock_detail.py#L72) · [后端执行](../../src/app/dependencies/stock_daily_technical_indicators.py#L192) · [页面能力](../../src/biz/queries/wealth/market/stock_detail/stock_detail_query_service.py#L125) · [接口类型](../../src/biz/schemas/wealth/market/stock_detail.py#L65) |
| 3. 页面 | `StockDetailPage` 先加载日线，切周期只处理日线和分钟线。请求类型只允许 `day`，历史状态和九转加载也走各自已有入口。 | 补齐 `stockDetailApiClient`、`stockDetailApiTypes`、`stockDetailViewModelAdapter` 和股票详情周月线加载逻辑。复用现有图表组件和向左追加后的视野处理。周线首屏及续页、月线首屏按 §3.4 发请求，按回包顺序交给图表，九转开关只切图层，提示框按 §3.5 处理。[股票页面](../../wealth/src/pages/stock-detail/StockDetailPage.tsx#L135) · [请求参数](../../wealth/src/features/stock-detail/api/stockDetailApiClient.ts#L52) · [日线翻页](../../wealth/src/features/stock-detail/controller/useStockDailyHistory.ts#L39) |

该阶段只接股票详情的前复权周、月线。现有按日期区间计算、指数周月线 500 根配置、股票日线与分钟线和各自的九转接口继续按原路径运行。无需改生产成品、数据库表或环境配置。股票详情整体合同入口见[股票详情实施方案](../../wealth/docs/pages/stock-detail/stock-detail-implementation-design-v1.md#stock-period-contract)。

## 4. 指标输入和结果

一根成品对应一个自然周或月，按周期升序进入指标计算，与显示的行情、量额一一对应。`statistics.source_rows` 计实际交给计算的周月 K 根数，定位、打开文件和日期补查单列。取消或超时沿用现有机制，关闭文件、连接并清理临时资源，按原请求重试。

<a id="stock-period-calculation-options"></a>

### 4.1 返回根数、预热精度和首期指标

`CalculationRequest` 同时承载起止日期和按根数请求。`KernelConfig.max_output_rows` 限制单次输出。现有 `calculate()` 支持按次选择 `output_rows` 和 `warmup_error_budget`，阶段三让 `calculate_with_source()` 复用相同参数处理。股票周线页面请求 `latest_rows=100`，配置 `output_rows=100`、`warmup_error_budget=0.00001`。根数、上限和预热精度分别生效，调用之间独立。[请求定义](../../packages/technical_indicators/src/goldenshare_technical_indicators/contracts.py#L48) · [资源上限](../../packages/technical_indicators/src/goldenshare_technical_indicators/configuration/settings.py#L92) · [现有预热规则](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/history.py#L5)

| 配置 | 本次调用的行为 |
| --- | --- |
| 返回根数 | 算子库内置 500 根、100 根两个输出上限选项。有效上限是所选配置与环境 `max_output_rows` 中较小的数。日期区间内选出的根数或按根数调用的 `latest_rows` 超过有效上限，沿用资源上限错误。股票周线取最近的 `latest_rows` 根，历史不足返回实际根数。月线使用环境上限内的全历史。 |
| 预热精度 | 省略该项或选择通用设置时，MACD、KDJ 沿用最低 500 根和 `2.5e-9` 初值误差预算的通用规则，保留各指标已有例外。股票详情的前复权周线明确选择 `0.00001`，由现有指标窗口和递推衰减确定前置根数。切换返回 100 根或 500 根时，继续使用本次选择的预热精度。 |

1. **详情后端传截止日和配置。** 周线首屏和续页按请求根数取数，页面默认 100 根，两类调用都用同一组指标和 `0.00001`。月线用 §3.2 的截止月请求。现有指数周月线和其他调用继续使用各自的配置。股票周月线沿用现有 HTTP 入口和参数。
2. **计算入口处理一次。** [共用计算入口](../../packages/technical_indicators/src/goldenshare_technical_indicators/service.py#L85)确定本次返回上限与预热配置，随[读数请求](../../packages/technical_indicators/src/goldenshare_technical_indicators/request_parser.py#L46)传给 DG、Prod，在定位和[输入检查](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L93)沿用有界读取。按 §3.2 的三种调用分别确定范围。本次调用选择的参数不写回共享的环境配置。
3. **同一套公式计算预热。** [计算引擎](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/engine.py#L103)把本次预热配置交给 MACD、KDJ 的 `input_requirement`。两者继续使用已有 SQL，其最少根数和误差值已作为输入参数。选 `0.00001` 时取消额外的 500 根最低要求，保留 SQL 现有的窗口和递推衰减下界。取各指标需求的最大值，一次读取所需前置行情。指标清单决定计算哪些指标和各自需要的根数，精度由调用参数决定。读到历史起点时仍以实际可用历史为准。

股票周线和月线首期使用 MA(5、10、20、30、60、90、250)、BOLL(20、2)、MACD(12、26、9)、KDJ(9、3、3) 和九转。周、月线页面在现有 `calculations` 中都请求这一组。下表为股票周线使用 `0.00001` 时，这组指标所需的前置根数。

| 指标 | 本页第一个目标之前所需周 K | 根数依据 |
| --- | ---: | --- |
| MACD(12、26、9) | 359 | 沿用绝对价格不超过 1,000,000 的误差推导。358 根的误差上限约为 `0.0000106944`，359 根约为 `0.0000099022` |
| KDJ(9、3、3) | 56 | 55 根的误差上限约为 `0.0000130563`，56 根约为 `0.0000088611` |
| MA250 | 249 | 加上目标这一根，恰好有 250 根 |
| BOLL(20、2) | 19 | 加上目标这一根，恰好有 20 根 |
| 九转 | 16 | 最长保留连续 13 次同向计数。第一次比较最早在当前根之前第 12 根，需取那根之前第 4 根的收盘价 |

根数按[现有误差公式](technical-indicator-kernel-low-level-design-v1.html#warmup-sql-math)推导。读数模块使用计算引擎合并后的最大值 359，指标共用这段周 K。验收比较未舍入数值，`0.00001` 用于核对截取历史带来的误差。

<a id="stock-period-nine-turn"></a>

### 4.2 九转输入与输出

调用使用 `{"calculation_id": "nineturn", "parameters": {}}`。输入是同批同周期 K 线的 `close`，即成品 `close_qfq`。按实际收到的 K 线根数向前比较 4 根，换向从 1 开始，相等或不足 4 根时归零，同向最多计到 13。周线默认组和其他指标共用最多 359 根前置 K 线，月线全历史从首根开始算。单独请求九转时沿用该算子的 16 根需求，历史不足时算到可用起点。输出 `up_count`、`down_count` 两列逐根对齐 `times`，计数逐根精确一致，只有 MACD、KDJ 适用 §4.1 的误差判定。[九转算子](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/nine_turn.py) · [前置根数合并](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/history.py#L38)

设计核验使用 DG 平安银行截至 2026-11-20 的 28 根周 K 和 26 根月 K。现有九转 SQL 的计数与独立逐根计算一致；各取最后 6 根并仅保留此前 16 根，结果仍一致。此记录用于验证现有算法可以复用。DG、Prod 的完整算子调用、接口和页面验收见 §6。

<a id="stock-period-performance"></a>

## 5. 性能预算和时间证据

- 沿用[现有配置](../../src/foundation/config/settings.py)默认 6 秒工作时限、2 秒清理预留及 8 秒总时限，以及查询内存、单请求内存、输入和文件读取上限。计时区分成品定位与读取、必要的日历停牌读取与日期上下文组装、指标、结果组装和清理。当期成品的 `end_date` 随同次读数返回。
- 股票周线首期用返回 100 根和 `0.00001` 的配置，单次最多向指标交付 `100 + 359 = 459` 根。正常首屏读到的第 101 根作为第一根预热，后续最多再读 358 根。当期覆盖日未知而剔除该根时，这一条只用于确认状态，源最多返回 `1 + 100 + 359 = 460` 条，计算仍最多用 459 根。九转共用这批输入。DG 分开记实际打开的周期文件、读出的个股行及日期事实，停牌导致有些分区无该股记录时，文件数可多于行数。Prod 周线最多两条成品查询，分别取得目标和读到的第一根预热、补齐剩余预热；月线一条有界成品查询，输入是本环境截至目标月的可用根数。Prod 日期事实查询单列。
- **核对同一次请求实际读了什么。** DG 对需要检查的周期分区用同一个读取器检查文件头、取所需列。Prod 按单股、周期和有界日期范围读成品，以最早已读周期限定预热补查的上界，两次查询返回的记录无重叠。已经读到的行供定位、行情、指标和九转共用。记录 DG 每个文件实际打开次数、Prod 每条查询的日期条件、返回行数和取出的字段。字段限于周期定位、计算、行情输出和 §3.2 的组装所需。阶段三日期判断只取当期所需的日历和停牌等事实，历史日期和周期检查直接用已有成品。成品来源只读，算子计算沿用现有请求内临时表。
- 阶段二用隔离样本验证 500 根和 100 根两套配置的边界与组合，传入同一标的和截止日下各自的起止日期。阶段三验收周线只传截止日和根数，月线只传截止月。前一页的预热成品可以出现在下一页的展示或预热中，按各页实际使用计量，同一次请求里只读一次。
- 独立算子库验收使用截至 2026-11-20 的平安银行样本。DG 和 Prod 各测周线首批、向前一批、最早一批及全部可用月 K，合计 8 次正式来源只读调用。周线最多向计算交付 `2 × 3 × 459 = 2,754` 根次，月线按各端实际根数相加。按同源成品从首根独立计算的对照读数另计，读取一次后供本环境各页结果复核。取消另计取消前已读数量及清理耗时，原参数重试按一次同范围调用计量。有界样本的首次和复跑条件随验收记录保留。
- 阶段三在 DG、Prod 各用平安银行测周线首批、按真实游标续页、末页及全部可用月 K。接口分记日期上下文、行情读取、指标计算、响应组装和清理。周线正常页只读本页和所需预热，月线只读截至目标月的全部历史。Web 组装阶段额外行情查询为 0，首屏交易日历及停牌等事实读取单列。阶段二下表及 §6 的结果仅供对照，阶段三按实际请求独立计时。
- 页面从点击周期或左拖发起请求开始计时，计至新 K 线和对应指标可用。正常操作按 [Wealth 交付清单 §2.10](../../wealth/docs/system/module-delivery-checklist-v1.md)默认 5 秒核对，超时仍由现有加载失败和重试流程提示。统计首次加载与原参数重试，列出两端样本日期和浏览器所连后端。失败或主动取消另外记已读范围、释放耗时和一次重试耗时。重试按同一请求预算，历史加载失败保留图上已有数据。独立对照只按单股和验收期间读一份，供本环境各页复用。

**2026-11-23 开工前取数实测。** 截至 2026-11-20，只读平安银行成品。周线测首批所需的 459 根，范围为 `2017-12-08` 至 `2026-11-20`。月线取到 2026 年 11 月，DG 从 2014 年 1 月起，Prod 从 2010 年 1 月起。

| 读取范围 | DG | Prod |
| --- | --- | --- |
| 周线首批所需 459 根 | 459 个分区文件，逐文件读取所需列约 0.82 秒 | 单股和日期范围走主键索引，限定 459 根的查询约 0.10 秒 |
| 全部月线 | 155 个分区文件，读到 155 根，约 0.18 秒 | 读到 201 根，查询约 0.03 秒 |

DG 表中耗时为文件读取，目录定位另计。Prod 表中耗时为客户端执行有界查询并返回统计和最新一条样本。两端各测一次。完整算子请求、取消和重试仍按本节预算独立验收。

## 6. 验收

| 项目 | 通过条件 |
| --- | --- |
| 返回根数和预热配置 | DG、Prod 隔离测试中，用同一标的和截止日分别请求选好的 500 根与 100 根，日期和行情在重合范围内一致，指标各自满足所选精度。验证返回 100 根仍可用通用预热，显式选择 `0.00001` 才使用对应预热，指标顺序、是否请求九转和行情均不改变精度选择。覆盖不足一页、范围超过所选上限、环境上限更小。连续在同一运行实例交替请求两套配置，验证后一次不受前一次影响。未传选项的指数、股票日线和分钟线按原有合同回归。 |
| 成品直读 | DG、Prod 各用正式成品核对前复权四价、量额及周期唯一性。隔离测试跟踪读取调用，验证选择范围、交付价格和五类指标共用成品，周月线请求只读本环境成品和所需日期事实。验证股票周月启用 `qfq` 并按频率读对源。 |
| 选页、计算和组装共用成品 | 两端用包含当前周期和历史周期的样本，逐根核对行情、指标和 `pct_chg`，确认当期状态只用对应成品的 `end_date`。用不同的成品周期日期和实际覆盖日期证明两者用途正确。跟踪 DG 文件和 Prod 查询，确认已选目标成品行直接用于计算与组装，额外读数限于所需预热与既定日期事实。 |
| 能力边界 | DG、Prod 的能力查询和实际调用一致，股票前复权周、月线可请求 `nineturn`。指数周月线、分钟线和未启用的复权口径仍按现行规则拒绝九转请求。原有成功的日线九转、指数已有指标和股票分钟线入口继续通过。 |
| 历史日期与起点 | 历史逐根核对成品 `trade_date`，检查国庆短周、周中新股、末页和月线全历史。DG、Prod 的平安银行最早周 K 都须返回 `2014-01-03`，历史预热也须允许用这根成品。隔离样本同时包含更早一周的成品，验证展示和预热都排除该周。历史回刷改变 `end_date` 后，日期继续取成品原标签。验收指数周月结果仍逐根返回其实际截止日期。 |
| 历史整期停牌 | 以深深房 A（`000029.SZ`）2020-03-09 至 2020-03-13 全日停牌、DG 无日线及周线成品的实际情况构造隔离样本，两端覆盖整周和整月停牌。让选页或预热范围跨过停牌周期，检查只返回已有 K 线，指标和九转按实际根数计算，停牌前后每根 K 线的日期和指标一一对应，翻页无重复或遗漏。 |
| 分页与指标 | 两端各测首批 100 根、向前一批和末页，核对周期无漏无重，覆盖前置历史充足和不足。月线核对从本环境正式起点到目标月的全量返回及 0 根额外预热。按同源成品独立计算未舍入指标。股票周线首期配置和指标参数下最多读 359 根前置周 K，MACD 和 KDJ 的初值误差上限为 `0.00001`。其他数据集和周期按现行精度验收。 |
| 九转计数 | 用[九转测试](../../tests/foundation/technical_indicators/test_nine_turn_calculation.py)补齐日、周、月的能力边界与目标结果。验证短历史、同向计数、相等归零、换向、封顶 13、跨内部批次及跨页，用第 16 根前置周 K 或月 K 的变化能影响首个目标值的样本覆盖边界。在 DG、Prod 的真实首批、续页、末页和全量月线中，逐根与同源成品的独立计算精确对照。 |
| 性能和清理 | 按 §5 记录首批、续批、末页、月线全量、取消及重试，确认时限、峰值内存和资源释放。隔离测试按文件路径和查询范围核对实际调用，验证已读目标和前置成品均被复用。记录同一默认组加入九转前后的成品读取次数及输入根数，两者应一致。 |

### 2026-11-23 阶段二独立验收记录

截至 2026-11-20，平安银行两端各有 661 根允许使用的周 K。每页 100 根，末页 61 根。独立对照按同源成品从历史起点逐根计算 MA、BOLL、MACD、KDJ 和九转。八个请求逐根对齐 `times`、成品 `trade_date`、前复权四价、量额、涨跌幅和九转，MACD 与 KDJ 的实际最大绝对差分别约为 `1.85e-12` 和 `8.53e-14`。末页从 `2014-01-03` 开始。11 月成品标签为 `2026-11-30`，覆盖日为 `2026-11-20`。覆盖日与成品涨跌幅保存在 Python 结果的 `period_bars`，供阶段三内部使用。

| 请求 | 返回根数 | 交给算子的总根数 | DG 文件打开次数 | DG 总耗时 | Prod 行情查询次数 | Prod 总耗时 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 周线首批 | 100 | 459 | 459 | 434 毫秒 | 2 | 800 毫秒 |
| 周线向前一批 | 100 | 459 | 459 | 396 毫秒 | 2 | 753 毫秒 |
| 周线实际末页 | 61 | 61 | 61 | 121 毫秒 | 1 | 544 毫秒 |
| 月线全量 DG | 155 | 155 | 155 | 180 毫秒 |  |  |
| 月线全量 Prod | 201 | 201 |  |  | 1 | 254 毫秒 |

DG 每份所需文件只打开一次，定位和读取耗时约 51–362 毫秒。Prod 目标与前置查询日期范围互不重叠，查询耗时约 161–672 毫秒，包含本机调用仓库只读 PostgreSQL 工具和取回记录的开销。算子执行和日期、价格、指标对照均在本机进行。Prod 原生读取连接和取消用本机隔离 PostgreSQL 验证。两端处理指标约 12–18 毫秒，最终结果组装约 1 毫秒，资源清理约 1–4 毫秒。DG 与 Prod 验收进程的峰值常驻内存约 343、337 MiB，包含 Python、数据参考和相关库。每批使用正常系统缓存，起初测的 100 根最早范围另计，表中是按实际分页重新测得的 61 根结果。

隔离验收在 DG 首份文件读完、Prod 首个有界查询返回后分别取消，确认无结果交付且资源释放，约用 1.0、1.5 毫秒。同参数重试读取 2 根，约用 17、18 毫秒。选定回归共通过 352 项，覆盖 100／500 根配置交替调用、环境输出上限、历史停牌空档、九转加入前后读取一致及现有日线、指数和分钟线路径。阶段三再验收 `end_date` 对页面更新提示的影响。

### 6.1 股票详情接口与浏览器验收

- **先验收阶段三算子。** DG 与隔离 PostgreSQL 直接调用同一个 `calculate_with_source()`。周线只传截止日和根数，验证只取最新 N 根、连续使用返回的实际游标、跨过整周停牌、满页或短页到头、正常空页、最多 359 根预热。构造当期覆盖日未知且有历史的样本，验证当期成品只用于提示，上一根可用行情补入且无重读。月线只传截止日，验证该月及之前全部可用成品、0 根额外预热和空游标。核对成品、指标、九转、`end_date` 和涨幅逐根对应，验证 `calculate()` 原区间与其他数据集调用继续通过。两端用 §5 的真实单股样本核对选页结果和耗时，完成后再接 `/kline`。
- 两端直接请求 `/kline`，省略 `limit` 和日期，验证日线缺省上限为 500 根，周线首屏缺省上限为 100 根，月线首屏返回截至目标月的全部可用历史。隔离样本验证周线 `limit=1` 只返回最近一根，显式越过 100 沿用参数错误。周、月线按 20:00 规则补齐日期后进入首屏状态判断。再传周线续页游标，核对续页沿用原页面行情日期锚和选页上限。
- 验证股票详情后端只凭截止日和根数调用算子，DG 文件和 Prod 行情查询均由算子库发起。跟踪周线首批和续页的文件及查询，核对目标和前置范围无重读，并从已读前置成品返回下一页截止日。覆盖刚好满页到头、不满一页、正常空页和月线全量，按同一请求记录选页、计算、回包组装和清理耗时。
- 两端对照周线首批、续页和月线响应，检查每根 `bars[]` 都含 `amplitude: null` 和 `turnoverRate: null`。浏览器切换周、月线并查看提示框，确认其省略振幅和换手率两行，其余行情字段正常显示。切回股票日线验证原有两项照常展示。
- 两端用正式样本核对 `/kline` 首批、续页和全量月线的日期、数量、单位、指标和 `nineTurnMarkers`。隔离测试固定时钟，覆盖 19:59 和 20:00、周末及节假日、全日和盘中停牌、当期缺行、`end_date` 较早或无法确认、补齐和历史回刷。核对 `pageContext.tradeDate` 在周期切换和翻页间一致，历史回刷的 `end_date` 不影响历史日期，续页不会触发当期提示。[股票接口回归入口](../../tests/web/test_wealth_stock_detail_api.py) · [原九转接口回归入口](../../tests/web/test_wealth_stock_nine_turn_api.py)
- 页面使用平安银行切换周线和月线，验收周线首批和向左拖动续页、月线一次加载。逐项核对横轴、提示框、指标与九转标记的日期。核对开关、9 的样式、无标记时图表正常、切换周期时迟到结果被丢弃、向前加载失败可重试。检查周月线的行情、指标和九转都来自各自的 `/kline` 回包。成品延迟时保留旧线、指标和九转，准确提示当前显示日期，更新到应有日期后撤下提示。分别记录周线首批、续页及月线加载耗时。[股票页面回归入口](../../wealth/src/pages/stock-detail/StockDetailPage.test.tsx)
- 先缩放并左拖周线，再切到月线和日线，检查各周期从自己的首屏初始化视野，周线追加历史时保留正在查看的位置。用先返回 `DELAYED`、数据补齐后返回 `READY` 的样本验证，切回周线或月线会重新发出首屏请求，更新 K 线和指标并撤下提示。

**验收命令和证据。** 算子先运行 `GOLDENSHARE_ENV_FILE=/dev/null APP_ENV=test python -m pytest tests/foundation/technical_indicators/test_stock_period_calculation.py tests/foundation/technical_indicators/test_stage_a_request_parser.py tests/app/technical_indicators/test_stock_daily_source_repair.py`。接口以同样隔离设置运行 `python -m pytest tests/web/test_wealth_stock_detail_api.py tests/web/test_wealth_stock_nine_turn_api.py`，测试临时文件放仓库以外。前端执行 `npm --prefix wealth run typecheck` 和 `npm --prefix wealth run test -- src/pages/stock-detail/StockDetailPage.test.tsx src/features/stock-detail/chart/StockChartWorkspace.test.tsx src/features/stock-detail/controller/useStockPeriodKline.test.ts`，覆盖周期能力、回包字段、请求次数、加载状态、日期和提示框。接口和前端再走真实路由及浏览器，以 §5 的 DG、Prod 单股样本核对并记录响应字段和耗时。代码对账逐项检查读取发起方、读数范围和结果传递，并回归日线、分钟线和现用指数调用。

### 6.2 阶段三编码门禁

依 [Wealth 交付清单](../../wealth/docs/system/module-delivery-checklist-v1.md)核对下表。实际接口和浏览器证据见 §6.3。

| 清单 | 适用范围和落点 |
| --- | --- |
| 2.1 交付事实链 | 适用。专项需求、方案、股票详情合同和本 LLD；沿用股票详情原图表设计。 |
| 2.2 后端事实归一 | 适用。§3.2 算子定页，§3.3 后端交付显示日期和状态。 |
| 2.3 状态机 | 适用。§3.3、§3.4、§5 和 §6.1 覆盖加载、正常、延迟、空、失败和重试。 |
| 2.4 显示语义 | 适用。§3.4、§3.5 定义日期、涨幅、九转和可空字段。 |
| 2.5 行为过程测试 | 适用。§6.1 验证切换、左拖、刷新、取消和延迟恢复。 |
| 2.6 文档同步 | 适用。按 §3.6 同轮核对股票详情合同、LLD 和新增实现。 |
| 2.7 渐进替换 | 适用。§3.6 先算子，再接口，再接页面；验收原日线及分钟线。 |
| 2.8 契约和消费者 | 适用。§3.4、§3.6 同步后端 DTO、前端请求与类型、加载和图表。 |
| 2.9 图表日期及文案 | 适用。§3.3、§3.4 确定横轴、提示框、九转和按状态显示提示。 |
| 2.10 性能和传输 | 适用。§3.2、§5 核对有界读取、同批结果复用和实际端到端耗时。 |
| 2.11 策略配置 | 不适用。本轮是股票详情行情，采用已批准的算子配置。 |
| 2.12 门禁矩阵 | 适用。本表和 §6.1 的可执行验收。 |
| 2.13 模块例外与累计值坐标 | 不适用。本轮沿用现有坐标规则，不新增例外或累计值图表。 |
| 2.14 图表显式参数 | 不适用。本轮没有新增或修改显式纵轴参数。 |
| 2.15 并排双图 | 不适用。周期在同一张图切换。 |
| 2.16 指标卡片 | 不适用。本轮改的是 K 线提示框，没有新增指标卡片。 |
| 2.17 真实 API 和页面 | 适用。按 §6.1 的命令、字段清单及两端正式单股样本验收。 |
| 2.18 跨模块八项原则 | 适用。股票详情方案 §3.2.1 逐项映射，本 LLD 落在 §3.2 的单一行情来源、§3.4 的合同、§4.1 的配置、§3.4 的默认值、§3.2 的选页排序、§5 的性能预算、§3.3 的状态和 §6.1 的用户可见验收。 |

<a id="stock-period-phase-three-acceptance"></a>

### 6.3 2026-11-24 阶段三独立验收

按 §3.6 核对了算子、接口装配和浏览器三处。CodeGraph 和源码核对覆盖 `calculate_with_source()`、DG/Prod 股票周月读数、`/kline` 接线与页面的周期及续页消费者。接口只从算子取得周月 K 线和游标，组装阶段追加读取行情为零。首屏另读当前周期日历、该股上市退市日期和有界停牌记录，续页保留页面日期锚。范围限定为股票前复权周月线，原日线、分钟线和指数调用通过回归。

用平安银行 `000001.SZ` 的正式成品验证新算子入口。以 2026-11-20 为周线截止日，依次取首批 100 根、续页 100 根、末页 61 根。首批和续页各用 359 根预热，末页从 2014-01-03 开始、预热 0 根。对照同环境按区间计算，日期、四价、量额、成品涨幅、九转计数及指标空值逐根一致，MACD、KDJ 的最大绝对差分别约为 `1.85e-12` 和 `8.53e-14`，符合 `0.00001`。DG 每次请求分别打开 459、459、61 个不同文件，每个只读一次。Prod 首批两条查询返回 101、358 行，续页返回 100、359 行，末页一条查询返回 61 行。已读到的第 101 根同时用于前置计算和下页截止日。月线 DG 读 155 个文件、Prod 一条查询读 201 行，额外预热 0 根。两端均读正式来源，Prod 强制只读。

接口和浏览器用同一真实数据锚点 2026-11-23。两端周线首批、续页、末页分别返回 100、100、62 根，多出的 1 根是 11 月 23 日所在的新周。末页从 2014-01-03 开始并返回空游标。月线 DG 155 根、Prod 201 根，最新一根均显示实际覆盖日 2026-11-23。历史直接使用成品日期。接口继续返回 `amplitude: null` 和 `turnoverRate: null`，页面提示框省略两项，日线照常显示。

| 操作 | DG 算子 | Prod 算子 | DG 接口 | Prod 接口 | DG 浏览器 | Prod 浏览器 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 周线首批 | 440 毫秒 | 163 毫秒 | 702 毫秒 | 300 毫秒 | 779 毫秒 | 474 毫秒 |
| 周线向前一批 | 388 毫秒 | 162 毫秒 | 526 毫秒 | 336 毫秒 | 679 毫秒 | 461 毫秒 |
| 周线末页 | 103 毫秒 | 206 毫秒 | 150 毫秒 | 299 毫秒 |  |  |
| 全部月线 | 174 毫秒 | 116 毫秒 | 296 毫秒 | 629 毫秒 | 394 毫秒 | 476 毫秒 |

浏览器连接本机的隔离应用，行情路由和数据来源均走真实实现。两端用鼠标左拖触发续页，同一屏幕位置在追加前后均对应 2026-07-03。实际提示框的交易日期、收盘价和主图 MA5 与接口同一根 K 线一致。九转标记对应回包日期，开关沿用原样式，切换时周月线未发出独立九转请求。切回周线重新读取首屏，页面未出现未处理异常。隔离测试用固定时钟核对 20:00 前后、全日停牌、延迟及更新后恢复，并验证切周期取消、历史失败重试和首屏提示保留。

后端及依赖边界回归共 82 项通过，前端 38 项通过，类型检查、前端构建和文档完整性检查通过。隔离 DG 在首个成品文件读完后取消，约 0.83 毫秒清理，按原参数重试约 18.54 毫秒。隔离 PostgreSQL 在第一条成品查询返回后取消，约 1.18 毫秒清理并归还连接，按原参数重试约 20.85 毫秒。两次重试都得到原请求的两根周 K。
