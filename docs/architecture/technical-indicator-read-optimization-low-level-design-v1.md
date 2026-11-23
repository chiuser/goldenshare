# 技术指标算子库读取优化 LLD v1

**2026-11-23｜本轮已完成。** 本文落实[读取优化方案](technical-indicator-read-optimization-plan-v1.md)。原设计所用代码基线为 `dev-interface` 的 `52d0bc207`。阶段 1 至 4 的提交与复核证据见[本地交付记录](#local-read-optimization-closeout)。阶段 5 已完成，见 [Prod 只读评估](#prod-read-optimization-evaluation)。

## 1. 交付边界

本期在 DG 依次实现股票日线、指数日线、指数周月线和指数 5 分钟算子读取优化。股票周月线继续由[原专项](technical-indicator-stock-period-plan-v1.md)处理。指数首屏的 `/page-init` 继续读最新一根日 K，提供盘口并按同一日期取估值、换手率及成分股统计。首批 `/kline` 仍包含这根日 K。优化的是一次日 K 请求内的重复选页和读取。

本地继续读取 DG。已有指标定义、股票前复权基准、预热精度、九转计数与显示、接口 URL、入参及回包字段沿用现行合同。指数 5 分钟仅改算子库，详情分钟接口和九转结果表归各自专项。Prod 使用既有读数路径，最终阶段仅做只读评估。现有数据、配置、Dagster 任务及页面渲染均由原入口维护。

## 2. 计算指令与读数结果

### 2.1 指令与解析

在 [contracts.py](../../packages/technical_indicators/src/goldenshare_technical_indicators/contracts.py#L48) 给 `CalculationRequest` 增加按根数取数的方式。

~~~python
@dataclass(frozen=True, slots=True, kw_only=True)
class CalculationRequest:
    security_type: SecurityType
    ts_code: str
    period: Period
    adjustment: Adjustment
    end: datetime
    calculations: Sequence[Mapping[str, object]]
    start: datetime | None = None
    latest_rows: int | None = None

    def __post_init__(self) -> None:
        # 校验两种范围，保留现有标的、指标参数和时区检查。
        ...
~~~

- `latest_rows=None` 时继续要求 `start`，按含首尾的起止范围计算。区间内根数超过现有上限时按原规则报错。`calculate(..., output_rows=...)` 继续表示现有的上限配置，与新方式的目标根数各自校验。
- 提供 `latest_rows` 时必须是大于零的整数，布尔值拒绝。`end` 是包含的截止时间。`start` 可作为目标最早允许日期，预热可向其之前读取。日线与周月线转为上海日期，分钟线保留带时区的时间。校验起始不得晚于截止。目标历史不足时交付实际根数。
- [CalculationRequestParser.parse](../../packages/technical_indicators/src/goldenshare_technical_indicators/request_parser.py#L23) 在 I/O 前检查请求根数不超过环境已配置的上限，解析并校验已启用的数据集。若调用还选择了更低的 `output_rows`，在 `TechnicalIndicatorService` 确定有效上限后再次对照两项值，此时还未进入读取。随阶段启用 DG 股票日线、指数日线、指数周月线的按根数读取。指数 5 分钟本轮保留现有区间调用方式。其它来源继续使用各自已有范围合同。超过上限沿用现有错误分类和业务 HTTP 映射。
- `_build_read_requirement()` 将新字段传给 [ReadRequirement](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/contracts.py#L93)。保留 `output_limit(config)` 为绝对上限，`latest_rows` 为本次想要的根数。将 `RequestedRange.start` 改为可空，仅新增指令方式允许为空。`CalculationResult.range.actual_start/actual_end` 记录真实返回边界。
- [calculation/engine.py](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/engine.py#L104) 原样计算复合指标的历史需求。不同算子的预热不相加，复用既有 `HistoryRequirement` 和 `preceding_limit()`。业务的 500 根和内核的预热行数分别处理。

### 2.2 本次行情如何交给业务

以下内部结果定义在 `sources/contracts.py`。这些字段供应用装配和业务使用，HTTP 继续通过现有 DTO 输出。阶段 1 实现股票日线用到的目标行情字段与续页日期，阶段 2 增加指数日线的日历记录，阶段 3 增加指数周月线的最早周期和最新实际截止日。股票已有的 `PeriodBarMetadata` 继续由原专项使用。

~~~python
@dataclass(frozen=True, slots=True)
class TargetBarFacts:
    position: date                 # 日线为交易日，周月线为自然周期起始日
    trade_date: date               # 来源记录的实际截止日
    pre_close: float | None
    change_amount: float | None
    pct_chg: float | None

@dataclass(frozen=True, slots=True)
class CalendarDayFacts:
    trade_date: date
    is_open: bool
    pretrade_date: date | None

@dataclass(frozen=True, slots=True)
class SourceReadFacts:
    target_bars: tuple[TargetBarFacts, ...] = ()
    previous_target_date: date | None = None   # 比首根更早、且符合目标下界的实际行情日
    first_available_period: date | None = None # 指数周月线最早成品的周期起始日
    latest_available_date: date | None = None  # 指数周月线最新成品的实际截止日
    calendar_days: tuple[CalendarDayFacts, ...] = ()

@dataclass(frozen=True, slots=True)
class CalculationWithSource:
    result: CalculationResult | None      # 内部选页为合法空页时为 None
    selection: PriceReadSelection
    source_facts: SourceReadFacts
~~~

- 在 `SourceDescription` 挂可选 `source_facts`。`ReadRequirement` 增加内部选项 `include_source_facts: bool`，由应用装配调用时传入，默认关闭。读取器将价格 Arrow 批次和事实字段分开保存，`source_projection` 仍只列标准行情所需原始列。换手率和量比仍由股票详情业务查询。
- 在 [TechnicalIndicatorService](../../packages/technical_indicators/src/goldenshare_technical_indicators/service.py#L78) 新增 `calculate_with_source(request: CalculationRequest) -> CalculationWithSource`。复用同一解析、执行、取消和清理流程。仅这条内部选页入口能接收成功读取后的零目标结果。`PriceInputSession.prepare()` 在零目标时跳过行情流和复权因子读取，由调用方按各接口合同区分合法空页与应有行情缺失。文件缺失导致的读取错误、无效结果和算法错误原样传播。原 `calculate()` 的无目标异常和原结果结构继续适用。
- [PriceInputSession](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L49) 继续检查交付根数、顺序、首尾、价格及因子合同。业务展示字段的时间序列必须和 `result.times` 逐根相同。`/kline` 调用现有 `price` 算子取得四价、股、元，辅助字段按数据源原口径返回。保留原调试字段。
- `SourceReadContext` 仅在本请求存放待交付的行情和标记。`LakeTechnicalIndicatorPriceSource.open()` 对已保留输入的链路用内存中的批次创建记录流。复用 [_LakePriceStream](../../src/foundation/clients/local_lake/technical_indicator_price_source.py#L421) 的批次交付和清理，不再次打开所选行情文件。业务返回前释放候选、预热和行情批次，结果只保留目标值及必要事实。

## 3. 阶段 1　DG 日线按根数读取与股票详情

### 3.1 文件、字段与执行步骤

`dataset_locations.stock_daily.dg` 指向 `silver/quote/stock_daily/trade_date={trade_date}/part-000.parquet`。阶段 2 的 `index_daily.dg` 指向 `silver/index_daily/trade_date={trade_date}/part-000.parquet`。两者日线日期均为 `DATE`。股票每日指标的 `trade_date` 为 `YYYYMMDD` 文本，只在业务匹配时转换。文件来源由 [datasets.py](../../packages/technical_indicators/src/goldenshare_technical_indicators/configuration/datasets.py#L17) 确定。

2026-11-20 的 DG 股票不复权日线样本确认，昨收 `pre_close`、涨跌额 `change_amount`、涨跌幅 `pct_chg` 均为 `DOUBLE`。按发布字段直接查询，随目标行情交付给业务组装盘口。

- [`LakePriceLocator._select_recent_daily()`](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L633) 复用 `_dated_partitions()`、`_safe_path()` 和既有行情字段。以截止日过滤路径，再用目标下界确定选页最早分区。用已有 `batch_rows` 作为单次候选文件数上限，用仍缺的目标和预热所需根数限制每批规模。日线每日每标的最多一根，取所缺行数个候选分区。没有该股记录的分区直接跳过，继续取更早路径，每个候选文件只进入一批查询。
- 候选路径的选择只处理目录日期和文件位置。用 `SourceReadContext.record_file()` 登记候选文件和大小，复用文件数上限。非空批次把路径直接交给当前请求的 DuckDB 连接，沿用现有输入根数、内存和时限。按行组读取的现有路径继续使用原行组限制。
- 读取目标和预热采用同一倒序遍历，先确定目标，再由 `preceding_limit()` 计算可用预热容量。确认续页位置时，优先复用预热读到的第一根实际行情。`start` 只限制目标和游标，向其之前找到的记录用于预热。若需确认历史起点且已达输入上限，允许查一条更早的记录，存在额外历史则按既有资源错误退出。若无需预热但仍有符合目标下界的较早分区，最多取一根实际行情确定游标。
- 最终把预热和目标合并为升序，构造 `PriceReadSelection`（`target_start/target_end/read_start/read_end`、目标根数、预热根数、是否到源起点）。只有被交付的目标和预热计入 `source_rows`；额外空间、候选文件和 SQL 工作量另记。算指标时从第 `preceding_rows + 1` 根起输出结果。

读取器按以下步骤组织，不新增单独查日期的入口。

~~~python
def _select_recent_daily(
    self, paths: tuple[Path, ...], *, price_projection: tuple[str, ...],
) -> SourceDescription:
    # paths 已按截止日裁切，输入保持日期升序，由本方法从尾部获取批次。
    target_rows = []
    history_rows = []
    previous_target_date = None
    # 每次查询只取尚未读过的候选，DuckDB 按交易日倒序返回实际行情。
    # 先在 start 及之后的候选分区查找目标行情。
    # 目标满额或目标分区用完后，从剩余分区继续读取预热。
    # 首个更早的实际行情日若仍在 start 范围内，可用作 previous_target_date。
    # 达到既有预热要求及游标判断条件，或到源起点后停止。
    # 只用最终保留的目标和预热构造 PriceReadSelection 及标准行情。
    ...
~~~

### 3.2 DG 日线批量 SQL

放在 DG 行情适配层，路径列表、证券代码、批次行数绑定为参数。下列完整投影用于详情请求的目标行情。普通计算和预热使用 `daily_price_projection()` 构造白名单投影，附加字段只随目标行情读取。候选路径按目录日期选定，包含截止日。直接采用 DG 发布的字段和每标的每交易日一条记录的约定，去掉额外的逐文件表头、分区日期和重复行检查。

~~~sql
-- lld: dg-daily-batch
SELECT trade_date, open, high, low, close, vol, amount,
       pre_close, change_amount, pct_chg
FROM read_parquet(?, hive_partitioning=false)
WHERE ts_code = ?
ORDER BY trade_date DESC
LIMIT ?
~~~

拿到本批结果后，按 §3.1 划分目标与预热，再交给现有输入会话。实际查询失败沿用现有读取错误处理。候选批上限以 §7 的基线和内存条件验收，标的筛选在 DuckDB 内完成。

### 3.3 股票业务接线

- [StockDailyKlineAppBackend.work](../../src/app/dependencies/stock_daily_technical_indicators.py#L181) 的 DG 分支通过 [StockDailyKlineService.prepare_recent](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py#L58) 解析证券身份及请求上下文，再构造带 `latest_rows=request.limit` 的计算指令。分页首屏与续页使用股票上市日作为目标下界，显式普通区间使用请求下界。Prod 业务装配沿用原先选页后按起止日期计算的方式。
- `stock_daily_calculations()` 原样选择现有指标和 `price`。保持本地首屏及续页请求九转，普通区间沿用既有形状。将 `source_facts.target_bars` 与结果日期对齐后，由业务按这些日期查询 `stock_daily_basic` 的 `turnover_rate`、`volume_ratio`，沿用现有 `daily_rows()`。每日指标文件缺少当日记录时按旧规则留空。本阶段沿用这条独立查询，传入实际日期即可。
- [LakeTechnicalIndicatorPriceSource.expected_positions](../../src/foundation/clients/local_lake/technical_indicator_price_source.py#L325) 对 DG 股票日线直接使用本次已选日期序列，停止重建应有日期及逐日读取 `stock_suspend_daily`。字段无效、行情文件不能读取、因子缺失等错误继续沿用现行处理。交易日历和上市日仍供现有业务 `pageContext`、上市起点使用。历史漏数交给 [DG 覆盖检查](../../lake_console/orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py#L1135)。
- `prepare_basis()` 和 `prepare_factors()` 保持原逻辑，仍以当前来源上该股票最新可用因子为前复权基准。候选日线截止点只限报价，不能误用为因子基准截止日。实际需要的目标和预热日期用既有因子选择；同一批 OHLC 的复权结果供全部指标共用。
- [StockDailyKlineService.assemble](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py#L102) 继续用同批 `price`、指标及辅助事实组装。单位按既有 DTO 转回手、千元。`expectedTradeDate` 用请求截止，`observedTradeDate` 用末根实际日期。`quote` 只在首屏按末根组装，首屏空页为 `null`。业务用 `previous_target_date` 生成 `nextEndDate`。`/page-init` 继续先给页面日期和证券身份。

## 4. 阶段 2　本地指数日线

1. [run_index_daily_kline](../../src/app/dependencies/index_daily_technical_indicators.py#L29) 的 DG 分支提供 `calculate(end, start, limit)` 回调，让业务直接传标的和范围。保持 `dg_index_daily_origin()` 作为目标返回下界，包括科创 50 的起点规则。调用 `calculate_with_source`，指标清单增加现有 `price`，其余沿用 `SSE_DAILY_CALCULATIONS`。投影沿用 §3.2，成交量额从同次 `price` 输出恢复为接口单位。移除 DG 分支的 `collect_target_ohlc` 私有收集及 `load_dg_fields()` 二次行情读取。`apply_calculated_kline_factors()` 只接原指标，`price` 单独组装。
2. [IndexDetailKlineQueryService._build_recent_daily_kline](../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py#L236) 用算子库返回的实际日期组页和生成游标。首批截止来自 `asOfTradeDate`，续页截止来自前批 `nextEndDate`，`meta.endDate` 对应调用方的截止日。前端普通和调试入口继续使用原调用。`/page-init` 继续掌握整页的行情日期和更新状态，盘口、估值、换手率和成分涨跌统计仍按其日 K 日期查询。
3. **现有历史完整性和页面上下文。** 指数的应有日线缺失仍报错。已有日历校验保留在指数读数流程，由读取结果决定有效校验的起点。对显式截止日，在已知行情和预热范围后用同一次有界日历读取核对已选行情并返回组装上下文所需字段。起点取本次预热和目标最早需校验日；历史不足时覆盖目标下界至请求截止日；已读到更早的实际续页日期时核对其与本批的衔接。供业务上下文使用的上一开市日可由首行的 `pretrade_date` 提供。对原有日期范围衔接误差使用现有 `scheduled_open_days()`，避免无依据推断缺口。将行序列与日历中相应开市日对比，在该次读数后一次完成。已达到 N 根时，从实际读取的最早校验日向后比对。目标不足 N 时，按目标下界检查应有目标，避免把漏行情当成合法短页。应有开市日却没有任何目标行情也走 `ID_QUERY_FAILED`。保留一次该校验读数，移除业务用日历先选整页的重复读取。

~~~sql
-- lld: dg-calendar
SELECT trade_date, is_open, pretrade_date
FROM read_parquet(?, hive_partitioning=false)
WHERE exchange = ? AND trade_date BETWEEN ? AND ?
ORDER BY trade_date
~~~

4. 业务调用 [resolve_local_context()](../../src/biz/queries/wealth/market/context/market_page_context_query.py#L224) 时传已取得的日历记录和当次 `now`。常规首屏与续页以给定日期组装 `pageContext`，本批状态仍能报告空页或部分指标缺失。历史日期查询早于源起点的空页只取上下文所需日期事实。直接请求省略截止日时，先用现有短窗口日历规则解析一次默认日期，后续以该日期作为读取上界。直接请求休市日，仍以该日生成 `meta.endDate`，使用上一开市日给出现有状态日期。持久化字段没有对应行情时沿用旧错误分类。正常页面调用不产生重新判断全页应更新到哪天的逻辑。
5. 界面沿用现有参数和 DTO。[DG 读取器](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L641) 在返回选页结果之前校验日历，覆盖当期应有行情却全部读不到的情况。阶段验收核对周日直接请求时 `meta.endDate` 为周日，最近开市日行情齐备时返回 `READY`。历史漏行情、缺收盘价的错误处理沿用 [已有指数日线回归](../../tests/app/technical_indicators/test_index_daily_kline_integration.py)。

## 5. 阶段 3　本地指数周线、月线

### 5.1 读取与选页 SQL

[DATASET_LOCATIONS](../../packages/technical_indicators/src/goldenshare_technical_indicators/configuration/datasets.py#L41) 提供 DG 单文件 `silver/index_weekly/full/part-000.parquet` 和 `silver/index_monthly/full/part-000.parquet`。两种日期均为 `DATE`。`period_start_date` 是来源保存的周期起点，可以是节假日后的第一个开市日。按其所在自然周或月计算 `period_start`。`trade_date` 是实际行情截止日。保持现行列类型。四价、昨收、涨跌额为 `DECIMAL(18,4)`，涨幅为 `DECIMAL(12,4)`，成交量 `DECIMAL(20,6)`、成交额 `DECIMAL(20,7)`。单位继续沿用 [index_period_projection()](../../src/foundation/clients/technical_indicator_index_period.py#L73) 和现行来源说明。

[`LakePriceLocator._describe_recent_index_period()`](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L544) 处理按根数的 DG 请求，在当前工作连接中投影单只指数的必要列，结果保留在请求私有临时表。临时表受现行 DuckDB 内存预算约束。在阶段验收对照旧实现的单标的文件读取和内存，确认只保存一只指数的投影列。输入根数上限应用于实际交给算子的目标和预热，表内其余记录用于同次确定最早和最新成品。若指数成品投影使用的资源超出现有预算，应调整读法再验收，不能使用截断的成品推断边界。

~~~sql
-- lld: dg-period-materialize
CREATE TEMP TABLE ti_index_period_rows AS
SELECT period_start_date, CAST(date_trunc(?, period_start_date) AS DATE) AS period_start,
       trade_date, open, high, low, close, vol, amount, pre_close, change_amount, pct_chg
FROM read_parquet(?, hive_partitioning=false)
WHERE ts_code = ?
~~~

~~~sql
-- lld: dg-period-bounds
SELECT count(*) AS source_count, count(DISTINCT period_start) AS distinct_periods,
       min(period_start) AS first_period,
       arg_min(row(period_start_date, trade_date), period_start) AS first_source_dates,
       arg_max(row(period_start_date, trade_date), period_start) AS latest_source_dates
FROM ti_index_period_rows
~~~

~~~sql
-- lld: dg-period-target
SELECT * FROM ti_index_period_rows
WHERE period_start <= ? AND trade_date <= ?
  AND (?::DATE IS NULL OR (period_start >= ?::DATE AND trade_date >= ?::DATE))
ORDER BY period_start DESC
LIMIT ?
~~~

~~~sql
-- lld: dg-period-warmup
SELECT * FROM ti_index_period_rows
WHERE period_start < ?
ORDER BY period_start DESC
LIMIT ?
~~~

- 成品 SQL 第一项绑定已校验的 `week` 或 `month`，其次绑定一个配置文件路径和指数代码。边界查询要求周期键有效且 `source_count = distinct_periods`。目标 SQL 前两个参数分别绑定截止日所属自然周期的起始日和截止日；有 `startDate` 时绑定原请求的起始日和相应周期边界，复用旧选页对于首、尾周期的日期规则。`LIMIT=N+1`，第 `N+1` 根如存在，仅提供其实际 `trade_date` 作为下一页截止事实。需要预热时，若目标 SQL 已读到第 N+1 根，直接将该记录用作第一根前置，前置 SQL 的排他边界使用该记录的周期起点，限量减去已取得的一根。否则前置 SQL 的边界使用首个目标周期起点。源起点、有效预热和历史结束继续用现行 `preceding_limit()`。如需要用额外一行判断源起点，结果只参与选择。
- `first_period` 和最新实际截止日来自同次成品。边界 SQL 同时返回最早和最新一根的原始日期对，沿用 `check_period_key()` 校验。以选中行情的实际起止日和预热范围复用日历校验。文件版本以现有 `_file_version()` 做同一快照的读前和读后核对。取数结束后关闭临时表，交给行情流的是已选择、升序的 Arrow 批次。单位按数据来源确定，DG 成品为手、千元，算子库转换为股、元，页面接口转回手、千元。明确定义起止的原调用仍走原读取方式和原超限、当期版本错误语义。
- *状态对账。* 有目标时按 `result.source_as_of[-1]` 与业务期望日比较。选中截止日更早且源最新截止也更早时，沿用旧延迟判断，允许显示已有历史。若源已有期望日及之后的发布而所请求的范围内应有记录仍缺失，沿用旧错误。无目标时按最早周期和请求下界判断历史空页，沿用 [read_page()](../../src/biz/queries/wealth/market/index_detail/index_detail_period_kline_query_service.py#L63) 的同一条件。新增读法用同次事实替代 `index_period_boundary()` 的额外文件读取。

### 5.2 业务接线

[run_index_period_kline](../../src/app/dependencies/index_period_technical_indicators.py#L31) 仍负责业务日期和控制对象的交接。常规本地请求显式传截止日，保持同一日期解析。省略截止日仍沿用已有用日行情确定截止的现行规则。本地分支用一次 `calculate_with_source()` 取周期行情、预热、指标和辅助字段。`IndexDetailPeriodKlineQueryService.query_period_kline()` 用 `times` 对齐，用 `source_as_of` 和游标事实组装显示日期与续页。`INDEX_PERIOD_PAGE_FIELDS` 的昨收、涨跌额、涨跌幅直接取目标成品。指数周月线仍按实际截止日显示和判断未更新状态，既有日历历史完整性校验在同请求限于所需窗口。Prod 继续走现有读取。

## 6. 阶段 4　DG 指数 5 分钟与阶段 5 Prod 评估

### 6.1 已启用的 DG 指数 5 分钟

路径为 `gold/quote/index_mins/freq=5/trade_date={trade_date}/part-000.parquet`。源 `trade_time` 为无时区的上海本地 `TIMESTAMP`。SQL 参数在进入适配层后从上海时间转换为本地墙上时间，行返回内核时按当前约定恢复时区。指数代码支持范围、单位采用 [index_minute_volume_unit()](../../src/foundation/clients/technical_indicator_index_minutes.py#L8)。

[`LakePriceLocator._select_index_minutes()`](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L702) 将区间选择、边界定位和行情读取合在一起。候选按交易日倒序查询，每个分区查询一次。目标开始日同时取目标和该日可用的预热，仍缺预热时才查询更早分区。按请求上下界核对目标根数，超限报错。检查批间时间、分区日期、`freq=5` 和重复时间。源已按现行规则处理开盘 K 线，DG 直接使用 09:35 业务行，09:30 行违反合同。缺失分钟照常按实际记录计算。

~~~sql
-- lld: dg-minute-batch
WITH selected AS (
    SELECT CAST(regexp_extract(filename, '/trade_date=([0-9-]{10})/', 1) AS DATE) AS partition_day,
           trade_date, trade_time, freq, open, high, low, close, vol, amount,
           count(*) OVER (PARTITION BY trade_time) AS position_rows
    FROM read_parquet(?, hive_partitioning=false, filename=true)
    WHERE ts_code = ? AND trade_time <= ?
)
SELECT * FROM selected
ORDER BY trade_time DESC
LIMIT ?
~~~

SQL 投影中的价格与量额字段由本次指标要求确定。Python 按 `start` 将同批结果划分为目标和预热。目标开始日之后的分区最多查询剩余目标容量与输入容量较小值再加一。目标开始日最多查剩余输入容量再加一，以便同一次查询同时覆盖两段。更早分区最多查剩余预热容量再加一。额外一行用于判断超限或是否还有更早行情。候选文件按 §3 核算，已有 DuckDB 内存及时限配置继续生效。选中的行情按时间升序交给现有输入会话，计算阶段直接消费保留的批次。 [跨日预热与读取回归](../../tests/foundation/technical_indicators/test_stage_b_index_minutes.py#L131)

### 6.2 Prod 只读对照

阶段 5 使用现有只读连接和代表性请求，核对股票日线、上证综指已接入的日线分支、指数周月线、指数 5 分钟。分别记录选页、定位、预热取价、辅助字段和复权因子查询数，并检查相同读数范围的 PostgreSQL 执行计划。评价合并查询的效果时，用已有索引及以下等价限量查询作对照。实施前另行确认范围。

~~~sql
-- 对照模板。relation、projection 由现有配置和字段白名单确定。
SELECT {projection}
FROM {relation}
WHERE ts_code = %s AND trade_date <= %s
ORDER BY trade_date DESC
LIMIT %s
~~~

- 日线分别用 `core_serving.equity_daily_bar` 和 `core_serving.index_daily_serving`，辅助字段随同行情列。若有业务历史起点，在目标选取中绑定下界，预热范围独立计量。周月线用对应指数成品表、`period_start_date` 排序、`trade_date` 判断实际覆盖和截止。5 分钟用现有 [`_price_scope()`](../../src/foundation/clients/technical_indicator_postgres.py#L47) 的频率条件和开盘归并，限量在业务 K 线归并后应用。
- 股票复权因子用现有 `core.equity_adj_factor`。记录基准查和所需日期批量查是否返回了同一基准日，比较在同一事务复用这条记录后可省的实读。区间停牌查询采用现有业务语义。使用会话的既有只读事务，范围限单标的和约定窗口。此阶段不执行数据库结构、数据或生产部署变更。 [当前 Prod 读取器](../../src/foundation/clients/technical_indicator_postgres.py#L119)

## 7. 开发顺序、预算与验收

本地四个实施阶段已完成代码、隔离回归及有界真实读取验收。阶段 5 已完成 Prod 只读对照，Prod 实施另行决定。

| 阶段 | 实施和过关证据 |
| --- | --- |
| 1. 通用能力与本地股票日线 | 复用 [请求合同测试](../../tests/foundation/technical_indicators/test_stage_a_request_parser.py)、[DG 股票日线读取测试](../../tests/foundation/technical_indicators/test_stage_b_stock_daily.py) 和 [股票 HTTP 回归](../../tests/app/technical_indicators/test_stock_daily_source_repair.py)。新增回归覆盖 500 根首屏、向左续页、历史不足和翻页到头。核对前复权价格、指标、九转及盘口；用请求跟踪确认选页和计算共用行情，业务不再提前查日期或查逐日停牌。 |
| 2. 本地指数日线 | 复用 [指数日线集成测试](../../tests/app/technical_indicators/test_index_daily_kline_integration.py)，重点核对实际日期、游标和页面状态。按原验收的上证综指、深证成指、北证 50、中证 A500 复验首屏和续页。分别记录 `/page-init` 跨请求使用的最新一根，以及 `/kline` 内的价格和辅助字段查询。 |
| 3. 本地指数周月线 | 复用 [算子周月测试](../../tests/foundation/technical_indicators/test_stage_b_index_period.py) 和 [周月接口测试](../../tests/web/test_wealth_index_detail_weekly_monthly_api.py)。核对周、月的首批、翻页、节假日短周和当期未齐时的截止日。核对源文件只投影读取一次，同次结果给出实际截止日和辅助字段。 |
| 4. 本地指数 5 分钟 | 复用 [分钟算子回归](../../tests/foundation/technical_indicators/test_stage_b_index_minutes.py) 及上证综指、深证成指的有界样本。核对开盘归并、跨日预热、实际时间、量额和指标。 |
| 5. Prod 评估 | 输出旧查询和对照方式的次数、扫描范围、返回根数及耗时；明确潜在收益和是否值得纳入后续开发。 |

### 7.1 数量和时间预算

- 沿用 [Settings](../../src/foundation/config/settings.py#L76) 和 [ExecutionControl](../../packages/technical_indicators/src/goldenshare_technical_indicators/execution_control.py#L21)。按现有生效配置限制目标、输入、文件和内存。按行组读取的路径沿用原行组尺寸限制。默认 8 秒总时限包含 2 秒资源清理，读取、计算和交付使用到达后 6 秒工作窗口。并发与队列使用现有参数。
- 重点比较每请求的目标行数、预热行数、仅用于界定范围的探测行数、实际 Parquet 文件打开、唯一文件、数据查询次数、内存峰值、总耗时。单次输入是目标加预热。若保留额外一行用于游标或判断源起点，单列为探测行。用相同标的、参数及可说明的文件缓存条件比较，同时核对查询数、实际文件打开及端到端耗时。
- 股票日线正式样本沿用 [平安银行前次修复验收](technical-indicator-stock-period-low-level-design-v1.md#stock-daily-read-repair) 的首批和一批续页。每批 500 根目标与该组合所需 500 根预热，共 1,000 根输入；两批前后各一次，共 4,000 根次，选页、文件、复权因子及独立对照另计。指数日线按既有四只指数每只首批与续页，按请求数与实际短页记录，不额外扩大历史。指数周期和 5 分钟用[既有周期样本](technical-indicator-index-period-low-level-design-v1.md#7-实施与独立复核记录)及[现有分钟样本](technical-indicator-operator-library-implementation-lld-v1.md#8-本轮核验证据)约定的标的、实际历史和预热规模；用对应旧版本或独立计算作为参照。
- 中断只对每个新读取方法做必要样本。记录取消前的候选文件、实际读数与已完成查询，按现有 `ExecutionControl` 中断，同一次请求清理 SQL、Arrow 与上下文。下一次以同参数从头读，用正常一次请求的同一限额测完整重试。取消前开销、清理耗时和重试开销分别记录。正式读取只做有界只读。

### 7.2 跨阶段回归与复核

1. 对照函数及 SQL 查询范围，证明本地股票日线路由不再选择日期后重读行情，指数日线不再按历法预选整页，指数周月线计算与回包用同一份成品，指数 5 分钟定位不再重扫同一批时间。验收记录附实际查询范围与调用方。
2. 核对输入日期、四价、量额、指标空值与数值、九转 1–9 标记、页面状态和页间日期。状态口径中的唯一明确变化是本地股票日线历史缺口交给 DG，浏览器正常流与周月、分钟其它范围继续按原合同核对。保留零目标、合法短页、数据读取失败、取消、超限之间的区别。
3. 旧区间计算、Prod 现有路由和股票周月线等路径复跑既有测试。新增回归聚焦各阶段实际改变的读取和业务结果，使用约定的有界真实样本核对。DG 日线批量读取无需构造文件损坏或字段类型错误的专门用例。验收完成后将实际数据源和运行状态写回本地后端技术指标来源审计表。

<a id="stage-1-read-acceptance"></a>

## 8. 阶段 1 实施与复核

2026-11-23 使用同机隔离的本地 HTTP 应用和正式 DG 文件，只读核对平安银行 `000001.SZ`。前后两版各跑一次首屏与向左一页，沿用默认 500 根。系统文件缓存未清空。除每次生成的 `pageContext.generatedAt` 外，`/page-init` 和两次 `/kline` 回包逐字段相同，覆盖交易日期、前复权四价、成交量额、指标值及空值、九转标记、盘口、状态和续页日期。

| 请求 | 返回日期 | 目标／预热 | 优化前 | 优化后 |
| --- | --- | ---: | ---: | ---: |
| 首屏 | 2024-10-31 至 2026-11-20 | 500／500 根 | 3.56 秒 | 2.47 秒 |
| 向左一页 | 2022-10-10 至 2024-10-30 | 500／500 根 | 2.47 秒 | 1.86 秒 |

- 每批取消 1,001 次业务行情查找和字段读取，以及内核 1,000 次逐日停牌读取。原路径可观察到 2,001 次日线 `ParquetFile` 读取器创建。新路径用两条 DuckDB 行情查询，分别读取目标和预热的 500 个文件，DuckDB 查询统计合计 1,000 个文件，两批路径无交叉。统计口径是读取器和查询所见文件，操作系统打开文件的次数未测。股票每日指标仍按实际目标日期读取，复权因子仍按原规则读取。
- 两个请求的 DuckDB 行情查询缓冲峰值均约 66 MiB，低于现行 128 MiB 查询内存配置。隔离应用进程峰值由约 398 MiB 增至约 441 MiB，含 Web、Arrow、Python 和 DuckDB，不能直接当成单条查询占用。两次 HTTP 请求均在现行默认 6 秒工作时限内。
- 用隔离样本在完成第一批的一文件一行后取消，约 0.7 毫秒释放资源。以相同参数重新读取约 20 毫秒，取得两根目标与一根预热。
- 阶段相关后端回归共 234 项通过，包括股票日线首屏、翻页、到头、空页、取消，以及指数日线、指数 5 分钟、周月线和隔离 PostgreSQL 的既有用例。补充真实空页断言后，97 项相关用例复跑通过。前端图表和续页的 12 项既有用例通过。页面验收覆盖隔离应用的 HTTP 回包和前端测试。全目录试跑另有旧测试引用未导出的 `CalculationInstance`，旧股票路由测试有三项在原版本同样失败。
- CodeGraph 复查了计算指令到 DG 读取会话、本地股票日线到业务组装和路由，以及前端续页消费者。实际变更限定在阶段 1 的共用指令和本地股票日线接线，后续范围通过原调用链的回归检查。

<a id="stage-2-read-acceptance"></a>

## 9. 阶段 2 实施与复核

2026-11-23 在同机隔离 HTTP 应用中，用正式 DG 文件对照优化前后的指数日 K。以 2026-11-20 为首屏截止日，每版对同样四只指数各请求一次首屏与续页，系统文件缓存未清空。每页用时是本次样本的实测值。

| 指数 | 首屏根数 | 续页根数 | 首屏优化前 → 后 | 续页优化前 → 后 |
| --- | ---: | ---: | ---: | ---: |
| 上证综指 | 500 | 500 | 2.94 → 0.81 秒 | 2.58 → 0.50 秒 |
| 深证成指 | 500 | 500 | 2.70 → 0.38 秒 | 2.67 → 0.35 秒 |
| 北证 50 | 500 | 450 | 2.30 → 0.33 秒 | 1.37 → 0.21 秒 |
| 中证 A500 | 500 | 23 | 1.51 → 0.25 秒 | 0.14 → 0.07 秒 |

- 各指数的日期、四价、成交量、指标及空值位置、分页状态和游标一致。北证 50 与中证 A500 的续页到各自历史起点并返回空游标。另测 2026-11-22 周日调试请求，保留周日请求截止日，预期与实际行情均到 11 月 20 日，返回 `READY`。
- 两次运行的生成时间戳各自生成。金额从算子标准单位元换回接口单位千元时，5 条记录有浮点末位差异，最大约 0.00012 元。其余回包字段逐项相同。
- 实测显式日 K 请求每次执行一次日历 SQL，用于检查行情日期和组装页面状态。行情执行一到两条批量 SQL，按实际日期取得目标和预热；同一请求内的行情查询路径无重叠，计算直接消费已读行情。业务的日历选页、辅助行情二次读取及逐文件重新打开行情流均为零次。
- 上证综指与深证成指每页提交 1,000 个不同日线文件给行情 SQL。北证 50 首屏与续页分别为 950、450 个，中证 A500 为 523、23 个。上述数量是查询路径及对应行情行数，未测操作系统打开文件的次数。整轮隔离应用进程峰值约 446 → 458 MiB，含 Web、Arrow、Python 和 DuckDB。
- 隔离样本读取 3 根行情和 4 条日历记录后取消，约 0.9 毫秒释放资源。用相同参数重试约 13 毫秒，返回两根目标，使用一根预热。
- 259 项相关后端回归通过，涵盖空页、覆盖期内缺行情、缺收盘、部分缺失、默认日期、真实数据源接入，以及股票、指数周月线、指数分钟线和隔离 PostgreSQL 的既有用例。27 项前端控制器、分页请求及字段映射测试通过。CodeGraph 核对了普通与调试入口、算子库读数、回包组装和前端续页消费者。范围限定为阶段 2 的本地指数日 K。

<a id="stage-3-read-acceptance"></a>

## 10. 阶段 3 实施与复核

2026-11-23 在同机隔离 HTTP 应用中用上证综指 DG 成品，对比阶段 2 提交 `bf7c58c51` 与本次实现。两版依次发送同一组请求，系统文件缓存未清空。正常请求的行情日期、四价、量额、指标值及空值、游标和状态逐字段一致，响应生成时间随请求变化。

| 请求 | 根数 | 末根实际截止日 | 优化前 → 后耗时 |
| --- | ---: | --- | ---: |
| 周线首屏 | 500 | 2026-11-23 | 240 → 232 毫秒 |
| 周线续页 | 500 | 2017-02-17 | 159 → 166 毫秒 |
| 月线首屏，历史到头 | 425 | 2026-11-23 | 153 → 152 毫秒 |
| 月线首屏，显式 100 根 | 100 | 2026-11-23 | 111 → 109 毫秒 |
| 月线续页，显式 100 根 | 100 | 2018-07-31 | 107 → 104 毫秒 |
| 国庆短周，按实际起止日 | 1 | 2026-10-09 | 84 → 90 毫秒 |

- 周线和月线续页沿用前页实际游标，月线 425 根短页返回空游标。国庆短周从源的 10 月 8 日开始，归入 10 月 5 日的自然周，仍展示 10 月 9 日的实际截止。月线文件只有 11 月 23 日的版本时，请求截至 11 月 20 日仍返回 `ID_QUERY_FAILED`，错误内容一致。该请求本次耗时约 22 → 101 毫秒，新流程先计算已选历史行情，再由业务根据最新发布日判定错误。
- 上述每次请求只执行一次源文件投影。选页、边界和预热都从同一张请求内临时表读取。业务预选页、另查周期边界和重新打开文件交付行情均为零次。行情输入保持 DG 的手、千元口径，算子库转换为股、元，HTTP 转回手、千元。正常请求耗时总体持平。两轮隔离应用进程峰值约 419 → 411 MiB。
- 取消样本在一个文件的 3 根目标指数行情写入临时表后停止。约 0.9 毫秒释放资源，重试约 18 毫秒，得到两根目标和一根预热。回归同时验证了选页读取失败及取消时删除临时表。
- 259 项后端回归、27 项前端测试通过。覆盖既有时期范围、隔离 PostgreSQL、默认截止日、涨跌和量额单位、空页、延迟、期内缺根、节假日周期及续页。CodeGraph 复核普通与调试入口、成品和交易日历、业务组装及前端分页消费。真实样本验收使用正式 DG 文件和隔离 HTTP 应用。

<a id="stage-4-read-acceptance"></a>

## 11. 阶段 4 实施与独立复核

2026-11-23 使用本地 Web 的算子装配配置，从公开 `TechnicalIndicatorService.calculate()` 调用算子库。对照改动前的 `51692eaf7`、本次结果，以及直接查询的 2026-11-16 和 17 日正式 DG 指数 5 分钟行情。样本为上证综指 `000001.SH`、深证成指 `399001.SZ`，请求 `price` 和 MA(2)。两只指数的时间、目标和预热边界、四价、量额及 MA 逐根一致。09:35 取 DG 已归并的 K 线，截止 09:30 时两版都返回 `数据缺失`。上证综指的源成交量从手换算为股，深证成指源成交量直接使用股，两者成交额均为元。

| 11 月 17 日目标区间（上海时间） | 目标与预热 | 每只指数的读取步骤，前 → 后 | 定位返回行数，前 → 后 | 用时，前 → 后（毫秒） |
| --- | --- | ---: | ---: | --- |
| 09:40–09:45 | 2 根目标，同日 09:35 预热 | 4 → 1 | 6 → 3 | 上证 24.4 → 20.0，深证 22.8 → 18.6 |
| 09:35–09:45 | 3 根目标，前一交易日 15:00 预热 | 6 → 2 | 51 → 5 | 上证 70.5 → 28.0，深证 25.1 → 25.4 |
| 09:35–15:00 | 48 根目标，前一交易日 15:00 预热 | 6 → 2 | 96 → 50 | 上证 36.8 → 26.5，深证 30.1 → 27.8 |

- 旧版计数包括行情文件元数据读取、时间定位或边界重扫、行情列读取。新版每个候选文件只提交一次 DuckDB 查询，输入会话直接使用这份结果。表中计的是代码中的读取步骤，定位行数是返回给定位器的记录。操作系统打开文件次数和物理读取字节数未测量。跨日查询额外读到的那根历史记录用于判断是否到源起点，不计入算子的输入行数。用时为单次样本，两版依次运行，系统文件缓存未清空。各轮隔离 Python 进程峰值约 258–266 MiB，整日样本两版均约 258 MiB。
- 在上证综指跨日样本的第一条查询取得 3 根目标后取消，未查询更早文件，约 0.9 毫秒释放资源。同参数重试约 20.6 毫秒，重新查询两个分区，得到 3 根目标和 1 根预热。
- 上证综指整日样本在目标上限为 48 根时完整返回，上限改为 47 根时按原分类报超限。区间从 11 月 16 日最后一根到 11 月 17 日第一根时，两根均返回，确认跨分区的起止时间仍包含在目标区间内。
- 260 项相关后端回归通过。新增回归验证跨日预热使用前一交易日行情，计算时不再打开 Parquet，且不继续查询第三个交易日。既有回归核对开盘规则、正常分钟间隔、上限、空目标、重复时间、未启用的指数，以及其他既有读数路径。CodeGraph 核对算子入口、DG 定位器、现有行情流及指数分钟详情入口。验收范围为本地算子库调用，指数分钟详情仍从原有 DG 成品读取。

<a id="local-read-optimization-closeout"></a>

## 12. 本地交付记录

2026-11-23 核对 `dev-interface`，阶段 1 至 4 的实施提交均已纳入当前分支。四项均有独立复核记录。

| 已交付范围 | 实施提交 | 验收记录 |
| --- | --- | --- |
| 本地股票日线按截止日和根数读取 | `e7d00f9ca` | [阶段 1](#stage-1-read-acceptance) |
| 本地指数日线按截止日和根数读取 | `bf7c58c51` | [阶段 2](#stage-2-read-acceptance) |
| 本地指数周月线复用周期行情 | `51692eaf7` | [阶段 3](#stage-3-read-acceptance) |
| 本地指数 5 分钟算子复用 DG 行情 | `a419eb7c8` | [阶段 4](#stage-4-read-acceptance) |

本地后端技术指标来源审计表已同步四条读取链路。Prod 只读对照单独记录于 §13。

<a id="prod-read-optimization-evaluation"></a>

## 13. 阶段 5 实施与复核

2026-11-23 以 `dev-interface` 的 `a419eb7c8` 所含 Prod 读数代码为基线，经仓库现有 Web 数据库连接访问 Prod PostgreSQL。通用只读账号只具备部分行情表的读取权限。实际对照会话设置为只读、可重复读，使用相同数据库快照，完成后回滚。原方式按代码重放选页、定位、读行情和辅助字段的查询。对照方式用同一条 SQL 查询有限的目标及预热行情，继续核对原有日历、存续和停牌事实。对照只是临时 SQL，未接入业务或算子库。

- 行情范围限贵州茅台 `600519.SH`、上证综指 `000001.SH` 和下表的样本。`core_serving.equity_daily_bar`、`index_daily_serving`、`index_weekly_serving`、`index_monthly_serving` 和 `index_minute_bar` 只投影日期时间、四价、量额和相应的昨收、涨跌额、涨跌幅。分钟视图对应 `raw_tushare.index_mins`，固定 `5min`，按原有方法将 09:30 归并入 09:35。周月分别按周期起始键排序，按实际截止日筛选目标。
- 辅助读取只查 `core_serving.trade_calendar` 的 SSE 日期、是否开市及选页所需的上一个交易日，`security_serving` 的该股上市及退市日期，`equity_suspend_d` 的区间停牌日期、类型和时段，`equity_daily_basic` 的该股票标的及目标日换手率和量比，以及 `core.equity_adj_factor` 的日期和复权因子。股票日线、指数日线、周月线的 500 根预热来自当前生产指标组合的规划结果。分钟样本使用 MA(2)，需一根预热。

| 样本 | 实际读入首末日期 | 目标＋预热根数 | 业务数据 SQL 次数，现有 → 对照 | 行情扫描行数，现有 → 对照 | 客户端耗时中位数，现有 → 对照 |
| --- | --- | ---: | ---: | ---: | ---: |
| 贵州茅台日线，截至 2026-11-23 | 2022-10-11 至 2026-11-23 | 500＋500 | 9 → 6 | 3,001 → 1,001 | 207.0 → 95.0 毫秒 |
| 上证综指日线，截至 2026-11-17 | 2022-09-28 至 2026-11-17 | 500＋500 | 6 → 3 | 2,501 → 1,001 | 77.6 → 48.1 毫秒 |
| 上证综指周线，截至 2026-11-20 | 2007-05-11 至 2026-11-20 | 500＋500 | 8 → 4 | 2,505 → 1,004 | 355.3 → 141.0 毫秒 |
| 上证综指月线，截至 2026-10-31 | 1991-07-31 至 2026-10-30 | 100＋324 | 8 → 4 | 952 → 427 | 312.9 → 271.1 毫秒 |
| 上证综指 5 分钟，2026-11-17 09:35–15:00 | 11-16 15:00 至 11-17 15:00（上海） | 48＋1 | 3 → 1 | 101 → 51 | 31.8 → 13.4 毫秒 |

- 五组结果的目标及预热日期、行情、辅助字段逐项一致。周线续页截止日同为 2017-02-10，月线同为 2018-06-29。月线读到历史起点，实际有 324 根预热。分钟样本另以实际 09:30 和 09:35 两条原始记录复算合并后的四价和量额。股票最新复权基准为 2026-11-23，该日也在批次内。复用后因子批次从查询 1,000 条降到 999 条，恢复基准行后因子序列一致，所需 SQL 次数相同。
- 股票日线、上证综指日线、周线、月线的目标最早允许日期分别为 2022-01-01、2010-01-04、2012-01-01、2000-01-01。先确定目标页，再按所需根数读取更早的预热。上证综指日线对照保留交易日历选页，合并了目标定位、预热定位、取价和行情辅助字段四条查询。周月线对照把成品首尾合为一条查询，保留对截止周期的检查。股票的交易日历、存续、停牌校验和两次复权因子读取仍分别执行。
- 每种方式交替运行三次，耗时是客户端逐条 SQL 返回的合计，含数据库往返及结果传输和转为 JSON 的时间。另执行一轮 `EXPLAIN (ANALYZE, BUFFERS)`。行情扫描行数按行情表扫描节点的实际返回行数乘循环次数相加，包含同一行的重复读取与分钟竞价查找。表中 SQL 次数含样本的业务选页、校验及辅助查询。HTTP、身份和页面上下文装配、游标控制、超时设置、指标计算均未计时。执行计划均命中已有索引或通过其位图选取数据，未观测到共享缓存之外的块读取。未测冷缓存、并发吞吐或生产接口总耗时。
- 上证综指日线在保留交易日历选页和核对的前提下，全部被测查询的共享缓存块访问从 1,972 降到 205，收益最明确。股票仍要查独立的股票每日指标及复权因子，合并查询主要节省往返及股票原价日线的重复扫描。周线少查四次，交易日历仍返回 7,138 条。月线仍返回 12,907 条交易日历，三次耗时有明显波动。5 分钟样本的 PostgreSQL 执行计划总耗时约 0.29 → 0.23 毫秒，所见客户端收益主要来自减少往返。
- **开发建议。** 先保留 Prod 现行实现。若实际接口耗时需要优化，优先安排上证综指日线，其次是股票日线。周线可以单独评估排期，月线和独立 5 分钟算子暂不优先。股票复权基准行复用可随股票日线一起做。 [Prod 算子读取与复权](../../src/foundation/clients/technical_indicator_postgres.py#L173) · [上证综指日线组装](../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py#L290)
