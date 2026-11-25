# 本地股票分钟线接入算子库 LLD v1

2026-11-25，阶段 1 已按 30 分钟先验收、再扩展的顺序完成。基础周期读取 DG Silver 同频率不复权行情，接受历史成交额的小额舍入差异。验收见 §9。阶段 2 的 90／120 分钟合成已完成，验收见 §10。阶段 3 已通过隔离验收，本机 Wealth 开发入口已切换并通过验收。验收见 §11。单请求和整批错误行为见 §6。 [本期方案](technical-indicator-stock-minute-plan-v1.md)

## 1. 现状和改动位置

[股票分钟 API LLD](../../wealth/docs/pages/stock-detail/stock-detail-minutes-api-low-level-design-v1.md)文首先给出现行接口，后面保留迁移前的 Gold 读取设计。下表记录迁移前的三个入口和页面消费者。

- `stock_detail_minutes.py` 的 `/minutes`、`/minute-indicators` 调用 `StockMinuteQueryService` 和 `StockMinsLakeReader`，分别读 DG 股票分钟前复权 K 线和分钟前复权 MACD／KDJ。
- `stock_detail_minute_nine_turn.py` 的 `/minute-nine-turn` 调用 `StockMinuteNineTurnQueryService`，先读取股票前复权分钟行情的时间，再按时间关联股票分钟前复权九转成品。标的校验已有本地证券基础信息入口。
- `StockDetailPage.handlePeriodChange()` 并行请求行情与 MACD／KDJ，`useNineTurnSeriesRegistry` 再为支持的分钟周期请求九转。分钟图目前只拖动已加载的窗口。后端支持游标，当前页面不发分钟续页请求。 [行情和指标调用](../../wealth/src/pages/stock-detail/StockDetailPage.tsx#L222) · [九转调用](../../wealth/src/pages/stock-detail/StockDetailPage.tsx#L100)

Foundation 负责路径、读取、复权、合成和有限预热。App 装配现有运行环境，Biz 保留标的、回包和 v1 游标处理，前端消费结果。用 `codegraph_explore` 核对了旧读者、页面调用、分钟算子入口和价格转换。修改前按符号复核旧读者的测试、包导出和其余消费者。 [API 装配](../../src/app/api/v1/router.py#L173) · [指数分钟参考](../../src/app/dependencies/index_minute_technical_indicators.py#L21) · [价格输入会话](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L51)

## 2. 数据来源和类型

正式根目录为 `/Volumes/datasource/data_lake`，仍由 `GOLDENSHARE_LAKE_ROOT` 提供。以下路径相对于正式根。Parquet 查询绑定文件列表和股票代码。

| 输入 | 路径 | 实际字段与口径 |
| --- | --- | --- |
| DG 股票不复权分钟行情 | `silver/quote/stk_mins/freq={base_freq}/trade_date={trade_date}/part-000.parquet` | `ts_code, exchange` 为 VARCHAR，`freq` 为 INTEGER，`trade_date` 为 DATE，`trade_time` 为不带时区的上海墙钟 TIMESTAMP，`open/high/low/close/vol/amount` 为 DOUBLE。成交量是股，成交额是元。 |
| DG 股票复权因子 | `silver/quote/adj_factor/trade_date={trade_date}/part-000.parquet` | `ts_code` 为 VARCHAR，`trade_date` 为 DATE，`adj_factor` 为 DOUBLE。按证券与交易日匹配。 |
| 既有 DG 成品 | `gold/quote/stk_mins_qfq`、`gold/indicator/stk_mins_qfq_macd_kdj`、`gold/indicator/stk_mins_qfq_nineturn` | 在本期新读取链路中只用于独立验收的有界对照。 |

基础五档均直接读取 Silver 同频率原价，成交额取该周期原值，首根的 09:30 竞价沿用现有归入方式。90／120 沿用 DG 的基础频率与窗口。

| 目标分钟数 | Silver `base_freq` | 完整交易日第一根 | 每日目标根数 |
| ---: | ---: | --- | ---: |
| 1 | 1 | 09:30 | 241 |
| 5 | 5 | 09:35 | 48 |
| 15 | 15 | 09:45 | 16 |
| 30 | 30 | 10:00 | 8 |
| 60 | 60 | 10:30 | 4 |
| 90 | 30 | 11:00 | 3 |
| 120 | 60 | 11:30 | 2 |

沿用股票分钟 Silver 历史起始口径 2014-01-01。实际起点为可读且含该标的有效行情的最早位置。物理分区采用 `freq=30` 这样的整数路径。HTTP 调用端和算子输出用上海时区，查物理文件时才去掉时区偏移。按北京时间交易日匹配因子。 [正式分区路径](../../lake_console/orchestrator/src/orchestrator/defs/paths.py#L321) · [股票分钟历史合同](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/stk_mins.py#L13) · [DG 窗口与频率](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py#L10)

<a id="stock-minute-amount-rounding"></a>

### 2.1 成交额精度的来源

对 Tushare `stk_mins` 发了两条有界查询。参数为 `600519.SH`、北京时间 2026-11-17 14:31 到 15:00，频率分别为 `5min` 和 `30min`，显式读取时间、周期、成交额和成交量。返回六根 5 分钟和一根 30 分钟。只读查到 DG 当日的两个频率分区属于 `stock_mins_raw_update_from_prod_job`，两条生成记录均标注 `source_method=prod_db_raw_tushare`。该批数据当时从 PostgreSQL `raw_tushare.stk_mins.amount REAL` 导出。

| 数据 | Tushare 成交额（元） | 按 `REAL` 保存后（元） | 与 Tushare 之差（元） |
| --- | ---: | ---: | ---: |
| 14:35 的 5 分钟 | 147,748,540 | 147,748,544 | +4 |
| 14:40 的 5 分钟 | 154,690,526 | 154,690,528 | +2 |
| 14:45 的 5 分钟 | 149,009,884 | 149,009,888 | +4 |
| 14:50 的 5 分钟 | 185,172,697 | 185,172,704 | +7 |
| 14:55 的 5 分钟 | 260,082,620 | 260,082,624 | +4 |
| 15:00 的 5 分钟 | 331,388,310 | 331,388,320 | +10 |
| 六根 5 分钟相加 | 1,228,092,577 | 1,228,092,608 | +31 |
| 15:00 的 30 分钟 | 1,228,092,577 | 1,228,092,544 | −33 |

将 Tushare 的七个值逐个转为单精度，可逐条复现 DG Raw 和 Silver 中的成交额。两层 Parquet 都使用 DOUBLE 承载导出值，扩大类型保留的是已舍入的值。两个频段复权输入的成交量都是 841,723 股，误差点在成交额，不涉及因子。当前 Gold 30 分钟将六根 5 分钟已舍入金额相加，得到 1,228,092,608 元。主样本的 64 元差由 +31 和 −33 构成。

本需求接受历史样本的这类金额差异，按选定 Silver 周期的原值和既有竞价、合成规则复算。64 元是上述单根样本的实际差值。2026-11-25 Prod 已切换精确成交额写入，历史金额仍按存量提供。DG 继续输出 `DOUBLE`，首批新数据按[上游精度验收](../datasets/stk-mins-amount-precision-low-level-design-v1.md#63-阶段-3-首批真实验收和故障恢复)对账。

[源字段说明](../sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md) · [Prod 原始表定义](../../alembic/versions/20260427_000080_slim_stk_mins_storage.py#L71) · [DG Raw 导出](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1108)

<a id="stock-minute-source-evidence"></a>

### 2.2 只读样本

- `600519.SH`、2026-11-17 的 Silver 1／5／15／30／60 分钟各有 241／49／17／9／5 根，均有 09:30，最晚 15:00。Gold 页面历史有 241／48／16／8／4／3／2 根。用相同复权乘数（该日 Gold 对照为 1），按 DG 既有基础频率和窗口独立重建七频，时间、四价和量额逐根一致。改用 Silver 同周期再合并竞价，5／15／30／60 分钟样本最大单根成交额差分别为 8／16／64／64 元。同日补查深市 `000001.SZ`，同频量额与旧合成方式在这四档的最大成交额差分别是 5／8／14／32 元。两只股票所比的时间、四价和成交量一样。样本结论限定在这些标的和窗口。
- 同股 2026-06-25 因子为 8.4464，06-26 为 8.6463。查询到的最新可用因子是 2026-11-24 的 8.6469。06-25 的 1 分钟收盘原价为 1212.0999755859375，按新基准计算约 1183.994407 元。旧 Gold 约 1184.076568 元，对应较早的 8.6463 基准。对照预生成成品时先固定共同基准，再比较合成和指标。独立验收还需验证普通请求确实使用最新可用基准。
- 原稿的合成 SQL 用共同基准验证了旧 DG 生成路径。30 分钟前两个窗口（读 5 分钟）及 90／120 分钟的全部窗口逐根匹配正式 DG 的时间、四价、量额和交易所。更新后的 SQL 用同频率 Silver 30 分钟核对了 10:00 和 15:00 两根。10:00 的开盘价采用 09:30 竞价收盘价 1,458.88 元，成交额含竞价为 1,133,854,464 元。15:00 成交额保留原值 1,228,092,544 元。此项核对设计 SQL，完整算子及 HTTP 验收在实施阶段进行。
- 2026-11-17 的 30 分钟指标成品样本使用 `paramsKey=macd_12_26_9__kdj_9_3_3`、`indicatorVersion=1`。页面分别按股和元显示成交量、成交额。
- 2026-11-01 至 11-17，同股每个频率用一条 DuckDB 多文件查询读取 12 个交易日。1／5／30／60 分钟得到 2,892／588／108／60 条基础行情，单次投影聚合耗时约 20／27／19／17 毫秒。这是有界读取测量。11-17 单日的 1 分钟文件约 21.3 MB、11 个行组，5 分钟约 5.4 MB、3 个行组，两者各有 1 个行组的股票代码统计范围包含该股票。正式 HTTP 耗时与内存仍须按第 7 节验证。

## 3. 算子请求与配置

`TechnicalIndicatorService` 增加与指数分钟入口同形的受控方法。请求仍用 `CalculationRequest`。

```python
def calculate_stock_minutes_recent(
    self, request: CalculationRequest, *, output_limit: int
) -> CalculationWithSource:
    """接收本地股票分钟指令，返回计算与本次读取事实。"""
    ...
```

调用形状为 `security_type="stock"`、`period="30m"`、`adjustment="qfq"`、带上海时区的 `start/end`、`latest_rows`、`calculations`。`start` 只约束目标行，预热可以读到它之前。根数按实际业务 K 线计算。探测行只用于 `has_more`，可与预热行复用。

- 在 `configuration/datasets.py` 声明 DG 股票分钟目标与 Silver 原价路径、基础频率的对应关系，沿用指数分钟的专用配置方式。既有股票分钟位置和 Prod 配置保留原含义。首个隔离版本只启用 DG 30 分钟的 `qfq`，通过验收再为其余基础周期启用。阶段 3 才接入本地页面。新目标的 Prod 对应位置为空。
- 在 `request_parser.py` 复用参数和算子依赖展开，增加与 `index_minute_output_limit` 对应的股票分支。只允许已启用的 DG 股票分钟、前复权、有 `latest_rows` 的指令。输出上限由可信 App 传入。常规入口仍受原 500 根上限，其他数据和周期沿用原解析路径。源层用 `ReadRequirement` 接收目标、频率、时间、预热和根数。
- 在 `calculation/indicators/nine_turn.py` 的 `additional_sources` 分阶段加 `stock + 30m/60m/90m/120m + qfq`，复用比较前 4 根、内部计数到 13 和现有 16 根预热。MACD／KDJ 使用既有按参数求有限预热的规则。用 `combine_history_and_fields` 合并所需字段和最大预热长度。
- 复用 `WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED`（Settings 默认 false，dev/local 本机 Web 配置启用）和 `GOLDENSHARE_LAKE_ROOT`（Settings 默认空，实际指向正式 DG）。股票路由、`pageInit.capabilities` 和算子路径使用同一套配置。切换时用股票分钟源已启用的事实替换 `resolve_stock_nine_turn_minute_capability` 的 Gold 文件目录依赖。配置在 Web 启动时装配，测试 local 开／关及 Prod 路由。已有执行预算见第 7 节。

[现有解析器](../../packages/technical_indicators/src/goldenshare_technical_indicators/request_parser.py#L31) · [运行配置](../../src/app/runtime/technical_indicators/composition.py#L33) · [九转定义](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/nine_turn.py#L19)

## 4. 按截止时间批量读原价

`LakePriceLocator.describe()` 的分钟分支新增 `_describe_recent_stock_minutes()`。复用指数分钟的按需读取、预热和 Arrow 批次交付办法。股票的频率映射、竞价归入与复权留在股票读取方法。 [指数分钟批量读取](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L826)

1. 用 `_partition_paths()` 枚举目标对应的一个 Silver 基础频率，以截止日期裁剪分区。业务层直接传截止时间、根数和可选下界，不用先查交易日历或停牌表来找日期。 用下界到截止日之间的可用分区数乘以每日目标根数，限制首批目标行预算。更早日期按预热所需读取。股票复权因子只检查实际取用的基准候选和入选行情日期的文件路径。
2. 每批用一条 SQL 传入多个 Parquet 文件路径，显式投影字段、按代码和基础频率过滤，按 DG 时段映射到目标窗口。按目标完成时间过滤截止，再按完成时间降序取需要的候选根数。
3. 候选保留窗口内原价基础行。若目标、预热或下一页探测不足，再读取更早的不重叠分区。选定后只保留目标和预热对应的原价基础行，以请求内 Arrow 交给复权。定位与实际计算共用这些行。
4. 空档按实际有效窗口计数。无目标行情时返回空 `CalculationWithSource`，业务入口组装空窗状态。有效行情匹配不到复权因子时按源合同错误处理。

SQL 形状如下。1 分钟的每个基础时点就是单个目标窗口，其中包括 09:30。5、15、30、60 分钟用同频率普通行情作为目标行，普通时点一一对应，09:30 只进入该周期第一根。90、120 分钟按 DG 现有窗口映射多根基础行情，09:30 同样只进入第一根。同一个窗口的来源时点由映射表固定。要求总行数和不同来源时点数都等于映射表中的时点数，等价于每个时点恰好收到一行。这个条件在读取 SQL 内完成。

```sql
WITH window_map(source_clock, target_clock, is_auction, source_count) AS (
  VALUES /* 从现行 DG 时段表生成，时钟用 TIME 类型 */
),
mapped AS (
  SELECT b.trade_date, b.trade_date + w.target_clock AS target_time,
         b.trade_time, b.open, b.high, b.low, b.close, b.vol, b.amount,
         b.exchange, w.is_auction, w.source_count
  FROM read_parquet(?, hive_partitioning=false) AS b
  JOIN window_map AS w ON CAST(b.trade_time AS TIME) = w.source_clock
  WHERE b.ts_code = ? AND b.freq = ?
)
SELECT trade_date, target_time, exchange,
       list(struct_pack(
         trade_time := trade_time, open := open, high := high, low := low,
         close := close, vol := vol, amount := amount, is_auction := is_auction
       ) ORDER BY trade_time) AS base_bars
FROM mapped
WHERE target_time <= ?
GROUP BY trade_date, target_time, exchange, source_count
HAVING count(*) = source_count AND count(DISTINCT trade_time) = source_count
ORDER BY target_time DESC LIMIT ?;
```

同频读取每个目标最多需要一个普通行和首根的竞价行。90、120 分钟每个目标的基础行数由既有窗口表定义。用所需候选数除以完整日目标根数并向上取整得到初批文件数，参考既有指数分钟批量读取的上限。若截止日在盘中、遇到空档或可读分区不足，按实际返回继续取更早批次或结束。计算按目标窗序排列，目标与预热分别计数。 [DG 窗口完成定义](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py#L302)

## 5. 同批一次前复权，再合成并计算指标

### 5.1 价格转换及合成

有目标行情后，用 `LakeTechnicalIndicatorPriceSource.prepare_basis()` 读取该标的最新可用因子。基准独立于 HTTP 截止日，与股票日线一致。仅为目标和预热对应的交易日用 `prepare_factors()` 批量读一次因子，复用同批已经读过的基准值。基准、按日因子和行情使用同一个请求的 DuckDB 连接。仅用于探测的窗口无需匹配因子。

将保留的 Arrow 窗口展开成 `ti_stock_minute_selected_rows`，保持交易日、原始时间、窗口完成时间和竞价身份。

将 `PriceInputSession.next_batch()` 中核对交易日因子的 SQL 提取到 `sources/price_adjustment.py`，让现有会话和股票分钟定位器共用。定位器先确认基准日期和基准值有效，基准值必须有限且大于 0。合成前用已选行情与已准备好的因子关系执行下列检查，日线继续使用自己已读出的对应关系。股票分钟只在内存中核对本次入选交易日，无额外 Parquet 查询。SQL 返回任一交易日时抛出现有的 `SourceContractError`，停止复权和合成。

```sql
SELECT prices.trade_date
FROM (SELECT DISTINCT trade_date FROM ti_stock_minute_selected_rows) AS prices
LEFT JOIN ti_stock_minute_factors AS factor USING (trade_date)
GROUP BY prices.trade_date
HAVING count(*) <> 1 OR count(factor.adj_factor) <> 1
    OR NOT bool_and(isfinite(factor.adj_factor) AND factor.adj_factor > 0)
ORDER BY prices.trade_date LIMIT 1;
```

[现有因子校验](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L257) · [复权实现位置](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/price_adjustment.py#L11)

按交易日算一次 `adj_factor / basis_value`，用该值乘基础行的四价，再聚合。计算时保留 DOUBLE，沿用页面显示精度。

```sql
WITH adjusted_days AS MATERIALIZED (
  SELECT f.trade_date, f.adj_factor / a.basis_value AS multiplier
  FROM ti_stock_minute_factors f CROSS JOIN ti_stock_minute_basis a
),
adjusted AS (
  SELECT b.trade_date, b.target_time, b.exchange, b.trade_time, b.is_auction,
         b.open * d.multiplier AS open, b.high * d.multiplier AS high,
         b.low * d.multiplier AS low, b.close * d.multiplier AS close,
         b.vol, b.amount
  FROM ti_stock_minute_selected_rows b
  JOIN adjusted_days d USING (trade_date)
)
SELECT trade_date, target_time AS trade_time, exchange,
       coalesce(max(a.close) FILTER (WHERE a.is_auction),
                arg_min(a.open, a.trade_time) FILTER (WHERE NOT a.is_auction)) AS open,
       greatest(max(a.high) FILTER (WHERE NOT a.is_auction),
                max(a.close) FILTER (WHERE a.is_auction)) AS high,
       least(min(a.low) FILTER (WHERE NOT a.is_auction),
             max(a.close) FILTER (WHERE a.is_auction)) AS low,
       arg_max(a.close, a.trade_time) FILTER (WHERE NOT a.is_auction) AS close,
       sum(a.vol) AS volume, sum(a.amount) AS amount
FROM adjusted a
GROUP BY trade_date, target_time, exchange
ORDER BY target_time;
```

首根使用 09:30 竞价收盘价作开盘，最高和最低把竞价价纳入比较，收盘使用最后一根普通行情的收盘价。量和额只求和。1 分钟保留其原有四价和时间。90 分钟收在 11:00、14:00、15:00，第二根使用 11:30、13:30、14:00 的 30 分钟记录。120 分钟收在 11:30、15:00，上午使用 10:30、11:30 的 60 分钟记录及 09:30 竞价。截止时间落在窗口中间，取此前完成的窗口。 [DG 前复权与输入关系](../../lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py#L249) · [已有因子读取](../../src/foundation/clients/local_lake/technical_indicator_price_source.py#L373)

### 5.2 交给现有指标会话

为使元数据反映实际输入和价格转换，内部 `SourceDescription` 增加可选 `delivered_adjustment: Adjustment | None = None`。股票分钟定位器设置 `input_adjustment="none"`、`delivered_adjustment="qfq"`、`converted=True` 及已确定基准。默认值对应原有输入口径。

`PriceInputSession.prepare()` 仍检查物理来源到目标所支持的转换，随后按实际交付口径判断是否需要再次准备因子。交付已是 `qfq` 时使用源提供的有限正基准。`next_batch()` 用实际交付口径决定是否转换四价。这样日线仍在现有会话内复权，股票分钟在合成前完成一次。复权后的完整目标和预热按时间升序写入 `SourceReadContext.retained_price_batches`，用 `_LakePriceStream` 将其交给已有收集器。源事实返回目标窗口的 `has_more` 和逐行交易所，定位阶段只执行一条已选价格转换和合成 SQL。在 `PriceInputSession.prepare()` 接收不同于物理输入的交付口径时，将该一次转换计入 `price_conversion_batches`。之后会话直接复用批次。

```python
def stock_minute_calculations(freq: int, output: StockMinuteOutput) -> tuple[dict, ...]:
    """按整张图、独立指标或九转选择同批算子。"""
    ...
```

`indicators` 选 MACD(12,26,9) 与 KDJ(9,3,3)。`nine_turn` 选 `nineturn`。`chart` 选 K 线、MACD、KDJ，并按 30／60／90／120 分钟加入九转。MACD 的 `hist` 映射到 `macd`，KDJ 的三线映射原字段，九转调用现有 `build_nine_turn_marker()` 生成 1–9 标记。候选、因子和合成后的数据均限本次请求，失败或取消会随同执行环境清理，重试重新计算。

[当前会话](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L51) · [结果元数据](../../packages/technical_indicators/src/goldenshare_technical_indicators/output/result.py#L150) · [九转标记输出](../../src/biz/services/wealth/market/nine_turn/nine_turn_response_policy.py#L94)

<a id="stock-minute-http"></a>

## 6. 本地 HTTP 和页面

### 6.1 请求与回包

路径前缀为 `/api/v1/wealth/market/stock-detail`。继续用当前鉴权、错误码和行情请求参数。`/minutes` 直接返回同一批 K 线和指标，形状参考本地股票日线。

| 路由 | 请求与算子调用 | 回包 |
| --- | --- | --- |
| `GET /minutes` | 沿用 `tsCode, freq, startDate, endDate, limit, cursor, debug`。调用一次 `chart`。页面传 `pageContext.tradeDate`，默认请求 500 根。 | 在现有行情字段上增加 `indicators` 和 `nineTurn`，返回 `StockMinuteChartResponseDto`。 |
| `GET /minute-indicators` | 现有请求参数，调用 `indicators`。 | 现有 `StockMinuteIndicatorsResponseDto`。 |
| `GET /minute-nine-turn` | 保留当前支持频率、证券校验及请求，调用 `nine_turn`。 | 复用 `NineTurnSeriesDto`。 |

```python
class StockMinuteChartResponseDto(StockMinutesResponseDto):
    # 行情、指标和九转来自同一批目标窗口。
    indicators: list[StockMinuteIndicatorDto]
    nine_turn: NineTurnSeriesDto | None = Field(alias="nineTurn")
```

指标字段沿用 `macdDif/macdDea/macd/kdjK/kdjD/kdjJ/paramsKey/indicatorVersion`，参数标识沿用 `macd_12_26_9__kdj_9_3_3`，版本为 1。用 `result.times` 对齐全部输出。1／5／15 分钟的 `nineTurn` 返回 null。支持周期用同一页的输入和算子输出构造九转响应。有效无标记的日期可正常返回空标记。由于九转和行情由同一批数据计算，`sourceRowCount` 与 `matchedRowCount` 均为目标根数，`missingRowCount` 为 0。外层 `nextCursor` 属于 bars，独立指标和九转的回包各用原数据集类别编码。 [现行行情 DTO](../../src/biz/schemas/wealth/market/stock_detail_minutes.py#L34) · [现行九转 DTO](../../src/biz/schemas/wealth/market/nine_turn.py#L36)

### 6.2 日期、分页和错误

- 用 `resolve_stock_minute_query_window()`。显式 `endDate` 含当天，省略时用北京时间今天作为查询上界，`expectedEndDate` 保留原显式值。请求起日只限制交付和游标，预热可越过。现有 HTTP 允许最多三个日历年份，省略 `startDate` 时交付下界仍为截止年往前两年的 1 月 1 日。算子预热可按需读其前的行情。单独调用九转沿用同样的目标年份合同。
- 复用股票现有 v1 游标验证和编码，保持 bars、indicators、nine-turn 各自的字段及校验。用游标的上海交易日和完整时间构造边界，再减 1 微秒传给算子的包含式上界。按目标窗口完成时间比对，保留截止日前同一天较早的窗口。实际最早一根 K 线生成下页游标。探测到的记录若落在目标下界之前，`hasMore=false`。
- HTTP 默认 500 根，范围 1–10,000。超过契约年份跨度、无效游标或参数沿用各入口的参数错误。按实际最终 JSON 的 UTF-8 字节给回包计量。整图回包和独立指标都沿用 5,000,000 字节门禁。合并回包的大小包括指标和九转，超过时返回 `400 SM_REQUEST_INVALID`，不截短也不自动拆单。独立九转保留现有错误和输出限制。
- 行情和 MACD／KDJ 的空、延迟、就绪状态沿用 `StockMinuteQueryService._to_status()`，按 `expectedEndDate` 与实际首尾时间判断。没有交易行的合法空结果与缺因子、源列错误、查询失败分开。沿用各现有入口的 `SM_SOURCE_CONTRACT_INVALID`、`SM_QUERY_FAILED`、`NT_SOURCE_CONTRACT_INVALID`、`NT_QUERY_FAILED` 分类与 HTTP 状态。独立九转接口保留现有股票身份校验和错误处理。整图请求按已确认的整批处理方式，MACD、KDJ 或九转计算失败均由页面展示分钟错误态。
- `debug=1` 按实际来源列出 Silver 股票分钟和股票复权因子，并沿用已公开的扫描文件数、耗时和期望日字段。普通响应不把复权基准交给页面判断或用于拒绝续页。

[日期解析](../../src/biz/queries/wealth/market/stock_detail_minutes/stock_detail_minutes_query.py#L14) · [行情游标](../../src/foundation/clients/local_lake/stock_mins_reader.py#L330) · [分钟算子请求与游标转换](../../src/biz/queries/wealth/market/stock_detail_minutes/stock_minute_calculation_reader.py#L62)

### 6.3 文件和职责

- `src/app/dependencies/stock_minute_technical_indicators.py` 提供 `run_stock_minute_page(request, *, output, arrived_at, ...)`。用现有 `_execute` 处理排队、取消和预算，创建一次 `TechnicalIndicatorService`。序列化后以同一份字节计算大小并发回。
- `src/app/api/v1/router.py` 装配三条现有本地路由，接入上述依赖。 `src/biz/api/wealth/market/{stock_detail_minutes,stock_detail_minute_nine_turn}.py` 保留鉴权、参数校验和状态映射，让 `/minutes` 回包直接携带同批指标。切换的那个阶段一起迁移本地九转 capability 的消费者，避免因 Gold 文件目录退场而失去已计算的九转。
- `StockMinuteQueryService` 复用窗口、meta、行情和指标映射，让算子回包取代 Gold 读者。 `StockMinuteNineTurnQueryService` 保留证券校验、九转 DTO 和标记规则。先做引用审计，再退出现有 Gold 读取器中已无业务调用的方法或导出。游标编码和校验保留给新入口复用。交易助手的 `StockRuleMinuteReader` 仍使用 `build_stock_mins_qfq_paths()` 和现有错误类型，保留这些共享引用。 [交易助手读取](../../src/foundation/clients/local_lake/stock_rule_minute_reader.py#L37)
- `wealth/src/features/stock-detail/api/stockMinuteApiClient.ts` 增加整图的 API 调用和对应类型。 `StockDetailPage.handlePeriodChange()` 以一次请求替换原行情与指标并行请求。通过现有图表适配器组装分钟图。分钟九转取这次返回的 `nineTurn`，不再调用独立九转查询。日线和周月线标记从各自现行路径取得。频率切换取消旧请求，缓存仍以股票、页面日期和频率为键。九转图层开关不额外起取数请求。图表的拖动、显示精度和指标叠加沿用现行实现。
- 切换到未缓存的分钟周期时，使用页面已选周期显示「正在加载 30 分钟行情…」格式的文案。加载占位只显示这条提示。即使错误文案为空，也要显示加载提示。既有请求、缓存、取消和失败处理沿用同一流程。前端测试在回包前检查文案和所选周期，回包后检查加载提示消失。
- 更新[股票分钟 API LLD](../../wealth/docs/pages/stock-detail/stock-detail-minutes-api-low-level-design-v1.md)的现行回包与数据源说明和类型测试。以正式 HTTP／浏览器验收通过后更新总审计表。其它接口、产品域和部署配置按既有分层运行。

## 7. 预算与失败恢复

沿用[股票分钟接口性能门禁](../../wealth/docs/pages/stock-detail/stock-detail-minutes-api-low-level-design-v1.md#10-性能安全与观测门禁)。默认 500 根接口的 P95 目标为 1.5 秒，实测单请求不得超过既有 5 秒门禁，响应体目标 2 MB、硬上限 5 MB。每个请求一个 DuckDB 连接，无 Tushare、Prod 行情查询、DG 事件查询或数据写入。使用现有请求池配置，无需增加环境参数。

下表是标准请求的文件量估算，用 `ceil((500 + 500) / 每个完整日目标根数)`。其中后 500 根是现行默认参数的内核递推预热基线。实际预热取内核返回的值。探测复用首根更早的行。文件占用和行情扫描字节由实测区分。最后一列是这批日期文件中单个标的原有完整日基础行数之和，用于估算范围。

| 目标分钟数 | 基础分钟数 | 完整交易日分区数 | 单股票基础行数 |
| ---: | ---: | ---: | ---: |
| 1 | 1 | 5 | 1,205 |
| 5 | 5 | 21 | 1,029 |
| 15 | 15 | 63 | 1,071 |
| 30 | 30 | 125 | 1,125 |
| 60 | 60 | 250 | 1,250 |
| 90 | 30 | 334 | 3,006 |
| 120 | 60 | 500 | 2,500 |

标准足量请求每批一条行情 SQL，另有最新基准定位和一次按日期的批量因子读取。因子检查只使用本次已经读取的数据。缺少行情的股票、盘中截止和续页可能增读分区。记录实际行情 SQL 数、读取的行情和因子文件数、独立基础行数、预热和目标根数、结果体积与峰值内存。仅把已选的窗口基础行和随后交付的标准窗口留在请求内。清理时释放 Arrow、临时表和 DuckDB，再归还执行槽。

复用 `src/foundation/config/settings.py` 的既有 `TECHNICAL_INDICATOR_*` Settings。仓库默认单请求 DuckDB 128 MiB、请求预算 256 MiB、输入上限 1,500,000 根、文件上限 10,000、批大小 8,192 根、并发执行 2 个，实际值以运行装配为准。文件预算累计计入行情文件和因子文件。目标上限由第 3 节的分钟专用入口传入。验收对长窗口、稀疏标的和大回包先有界测量，超预算沿用现行请求失败处理。不得因尚未达到验收目标扩大配置。

失败或客户端取消时沿用内核取消与资源归还。验收在真实只读窗口测试取消，记录从发出取消到资源释放的时间，再用同参数重试，复核原窗口和响应时间。重试至多重做本次的读价、因子定位和预热，累计验收成本按对照请求、取消请求及完整重试分别计量。正式核验只读所列标的和窗口，不执行全集比对。 [执行配置](../../src/foundation/config/settings.py#L75) · [有限预热](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/history.py#L5) · [共享执行与取消](../../src/app/runtime/technical_indicators/execution.py#L38)

## 8. 分阶段开发与验收

### 阶段 1　先做 30 分钟，再扩展基础周期

1. **先实现并验收 30 分钟。** 按 §2 至 §5 开发共用代码，首个隔离装配只启用 DG 30 分钟。用 2026-06-25、06-26 以及验收时的最新基准因子独立核算收盘价。带预热的请求按批读取原价，并对入选数据做一次复权。用 11-17 的 30 分钟样本核对截止时间、竞价归入、收盘、跨日和不足 500 根，以 Silver 原值复算量额。用有行情但缺因子的样本确认整批报源合同错误。
2. **核对 30 分钟指标。** MACD／KDJ 用独立算式复算，拿相同前复权基准的 Gold 结果核对两位小数显示与首尾值。记录实际误差，定位同基准的可见差异。九转用人工样本及旧标记对照跨窗 8→9、长于 9 的延续和反向计数。
3. **通过后扩展 1、5、15、60 分钟。** 共用已验收的读取、复权和计算代码，按频率配置同频 Silver 输入和竞价归入。用 11-17 对应样本逐频核对时间、量额、首尾根和预热。60 分钟启用九转，1／5／15 分钟沿用无九转的页面口径。
4. 回归股票日线前复权、周月线、指数七频、Prod 及默认 500 根的通用算子入口，核实内部交付口径的默认值没有带来重复转换或行为变化。 [股票日线复权回归](../../tests/app/technical_indicators/test_stock_daily_source_repair.py#L322) · [日线因子错误回归](../../tests/app/technical_indicators/test_stock_daily_source_repair.py#L416) · [指数回归](../../tests/foundation/technical_indicators/test_index_minutes_recent.py)

### 阶段 2　补 90、120 分钟的合成

复用阶段 1 的读取、复权和计算。只新增两档目标的来源和窗口映射，以及同一算子可用的频率配置。

- 以同基准 DG 正式样本逐根核对两档的时间、四价、量额、指标和九转。用独立样本核上午、跨午休、收盘、日期切换，以及截止时间落在窗口内的行为。
- 取最近 500 根并按需预热，验证根数按合成后的窗口计算。选取一个较大的续页窗口和接近源起点的窗口复核选页、游标候选和预算。只测代表窗口，无须全历史对照。

### 阶段 3　本地接口和页面切换

实现 §6 并更新当前 HTTP 说明。在真实只读 DG 和临时本地服务上验证三条入口。

- 用正常鉴权和配置矩阵回归 local 开／关与 Prod 路由。测试一次回包含行情和指标，原有行情字段仍可读取，覆盖原 v1 游标、日期窗口、默认 500 根、跨年、空态和延迟。代表性大 limit 不足时返回实际根数，触及 5 MB 的请求按合同拒绝。
- 用浏览器验证一只代表股票的 30／1／90／120 分钟，以及另外三档的 HTTP 结果。核对一次请求内 K 线、MACD／KDJ、九转时间对齐，产品周期和图层开关正确，原先三次请求收敛成一次。断开或切换频率之后完成重试与资源审计。 [行情 API 回归](../../tests/web/test_stock_detail_minutes_api.py) · [九转 API 回归](../../tests/web/test_wealth_stock_minute_nine_turn_api.py) · [页面消费用例](../../wealth/src/features/stock-detail/api/stockMinuteViewModelAdapter.test.ts)
- 用真实调用路径和引用清单确认三条股票分钟详情接口不再读 DG 前复权成品。记录各成品还服务的其他接口、研究和 DG 下游依赖。停止生产或回刷属于后续单独动作。

## 9. 阶段 1 独立验收记录

2026-11-25。先用只启用 30 分钟的隔离装配验证，再扩展 1、5、15、60 分钟。CodeGraph 核对了指数分钟选取、股票日线复权和业务调用链。新入口为 `TechnicalIndicatorService.calculate_stock_minutes_recent()`。股票与指数分钟共用按日期批量选取的逻辑，股票按 Silver 自身频率及竞价规则组窗。选中后复用日线的因子检查和已加载的基准数据，按交易日算乘数并执行一次复权，交付给现有指标会话。默认 Web 装配尚未启用这些数据集，页面继续走原接口。90／120 分钟留在阶段 2。

| 验收项 | 实际证据 |
| --- | --- |
| 30 分钟价格和量额 | 正式 DG 贵州茅台 `600519.SH` 的 2026-06-25 15:00、06-26 10:00 分别用因子 8.4464、8.6463，以该次请求最新基准 8.6469 独立复算，收盘约 1183.9944、1187.2776 元。11-17 首根含竞价共 1,133,854,464 元，收盘一根为 1,228,092,544 元，对照旧 Gold 分别少 16 元和 64 元，符合各自取数口径。两根成交量一致，四价归一到同一复权基准后一致。 |
| 指标和预热 | 贵州茅台 30 分钟请求返回 500 根、预热 500 根。MACD 和 KDJ 用独立递推逐根复算，全样本最大误差低于 1e-8，九转计数完全一致。另将旧 Gold 10:00 和 15:00 的价格及 MACD 换算到同一复权基准，KDJ 和九转直接按时间核对，结果一致。临时夹具验证九转跨批次 8→9 和计数到 13。 |
| 其余基础周期 | 2026-11-17 同股 1／5／15／60 分钟分别返回 241／48／16／4 根，首根分别为 09:30／09:35／09:45／10:30，末根均为 15:00。逐根以同频 Silver 和当天因子独立复算四价、成交量和成交额，均一致。临时夹具核对 60 分钟启用九转、1／5／15 分钟不支持九转。 |
| 文件、耗时与取消 | 30 分钟 500+500 根的正式样本用一条行情 SQL 读 125 个行情文件。统计含 126 个因子文件，其中一个用于最新基准，入选基础行 1,125 条。独立对账一次测得算子耗时约 536 毫秒。60 分钟 500+500 根，一条行情 SQL 读取 250 个行情文件，含因子的总文件数 501，独立进程测得算子耗时约 918 毫秒、峰值 RSS 204 MiB。RSS 为整个测试进程的高水位。30 分钟在因子读完处取消，约 2 毫秒完成资源清理，同参数重试返回预期 8 根。上述是隔离算子读数，接口及页面性能在阶段 3 验收。 |
| 合同和回归 | 校准 LLD 的日线复权用例引用。测试覆盖已选交易日缺因子时报源合同错误、探测行无须读因子、目标下界与预热分开、同批只复权一次、专用上限及 DG 配置隔离。五频新用例、日线、周月线、指数分钟、请求解析和依赖边界共 85 项通过，其中 Prod 周月线在临时 PostgreSQL 验证。 |

正式数据核验限贵州茅台及已列样本。没有执行全量行情扫描、写入或回刷。

## 10. 阶段 2 独立验收记录

2026-11-25。按 CodeGraph 和当前代码核对股票分钟算子入口、DG 读取、复权及 DG 成品生成规则。90 分钟读取 DG Silver 股票不复权 30 分钟行情，120 分钟读取 60 分钟行情。两档沿用一次复权、一次合成及 MACD、KDJ、九转计算。本地 Web 继续使用现有装配，Prod 使用现有数据位置。

- **合成与指标。** 用贵州茅台 `600519.SH` 独立复算首批和续页，两档各 1,000 根。开高低收、成交量（股）、成交额（元）和九转计数逐根一致，MACD 和 KDJ 的最大绝对误差小于 `1e-8`。同股 2026-11-17 的 DG Gold 成品用 8.6463 作为复权基准，算子使用最新可用基准 8.6469（2026-11-24）。换算到同一基准后，90 分钟 11:00、14:00、15:00 和 120 分钟 11:30、15:00 的四价、量额、指标及九转 1–9 标记一致。
- **截止和历史边界。** 同日以 13:59 请求 90 分钟、以 14:59 请求 120 分钟，且起点为当天，各只返回已完成的上午一根。以首批最早一根前 1 微秒为续页截止时间，90 分钟由 2026-03-13 14:00 接回当日 11:00，120 分钟由 2025-11-06 11:30 接回 11-05 15:00。对照 Silver 合成结果，两档均无重复或断根。截止 2014-01-06 时，最早均为 2014-01-02，分别返回 9、6 根，预热为 0 且无更早一页。
- **取消和重试。** 在因子读完时发出取消，两档分别约 3.7、3.2 毫秒释放资源。原参数重试约 621、786 毫秒，均返回预期的上午一根。
- **回归。** 股票分钟、指数分钟、股票日／周／月线、指令解析和依赖边界共 87 项通过。周月线的 Prod 分支使用临时本机 PostgreSQL 验证。

贵州茅台每次请求返回 500 根并使用 500 根预热，实际读取和用时如下。每批行情只用一条 SQL，120 分钟续页截止在上午第一根之前，首批分区少一根用于预热，随后用一条 SQL 补读一个更早的分区。

| 周期及请求 | 行情 SQL 次数 | 行情文件 | 股票复权因子文件 | 入选基础行情行数 | 算子实际耗时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 90 分钟首批 | 1 | 334 | 335 | 2,999 | 1,727 毫秒 |
| 90 分钟续页 | 1 | 334 | 335 | 3,001 | 1,179 毫秒 |
| 120 分钟首批 | 1 | 500 | 501 | 2,500 | 1,760 毫秒 |
| 120 分钟续页 | 2 | 501 | 501 | 2,500 | 1,663 毫秒 |

分别启动进程测两档。测到首批时进程峰值 RSS 约为 219、238 MiB，完成续页后分别约为 238、251 MiB。RSS 是整个进程的内存高水位。四次 500 根请求均低于 5 秒，其中三次算子耗时已超过 1.5 秒。阶段 3 用实际接口验收 P95 和回包体积。实测只查询上述股票及请求窗口的行情，以及对应的股票复权因子和单日对照成品。

<a id="stock-minute-phase-three-acceptance"></a>

## 11. 阶段 3 独立验收记录

2026-11-25。沿真实路由、DG 读取、算子执行和前端请求核对。临时本地服务使用正式 DG 有界只读数据、实际行情鉴权和临时 SQLite 审计账号。前端使用本次构建产物，在 Chrome 中验收。本机原服务和 Prod 未切换。

| 验收项 | 结果 |
| --- | --- |
| 七档 HTTP 与算子输出 | 贵州茅台 600519.SH，截止 2026-11-17。七档默认请求均返回 500 根，K 线与指标时间逐根相同。1／5／15 分钟九转为 null。30／60／90／120 分钟标记均在本批 K 线上，序号 1–9。独立指标和九转 30 分钟各用 20 根与合并回包对照。三个路由均报告 Silver 不复权分钟行情和股票复权因子。 |
| 游标、上限与鉴权 | 原 bars v1 游标从 90 分钟 15:00 续到同日 14:00。90／120 分钟各 500 根首批与续页无重复，120 分钟首批覆盖 2025 至 2026 年。指定单日、limit=10,000 的 120 分钟请求返回实际 2 根。单个股票的 1 分钟请求触及实际 5,000,000 字节门禁，得到 HTTP 400 和 SM_REQUEST_INVALID。实际鉴权拒绝未登录请求。分别以 local 关闭和 Prod 配置核对三个路由均未挂载。 |
| 浏览器与取消 | 30／1／90／120 分钟均在 Chrome 渲染。切换每个周期只请求一次 /minutes。截止日为页面日期，limit=500。九转开关无额外请求。发出 120 分钟请求后切到 1 分钟，浏览器取消旧请求，随后重试 120 分钟成功。服务器在收到取消后约 1.85 毫秒释放算子资源，验收结束执行池占用为 0。临时 SQLite 环境的自选分组请求返回 500，分钟接口均正常，前端无未捕获异常。 |
| 回归 | 后端 129 项、Wealth 59 项通过，TypeScript 检查和构建通过。独立核对空态、缺因子、游标所属路由、实际回包字节和配置开关。 |
| DG 成品消费者 | 三个股票详情分钟入口已退出前复权成品读取。交易助手仍读取 DG 1 分钟前复权行情。DG 的股票分钟前复权 MACD／KDJ 和九转生成仍使用其前复权行情，相关检查仍按现行定义读取。代码引用审计未发现其它股票详情或 QTF 分钟成品读取调用。 |

验收时缩小了大 limit 的首批读取范围。算子先用请求覆盖的分区数估算最多能返回多少根，再按预热要求补读。复权因子只检查实际读取的文件。两项调整仅应用于股票分钟读取，沿用现行 500 根预热和资源配置。

| 500 根请求 | 样本数 | HTTP 中位耗时 | 样本耗时上界 |
| --- | ---: | ---: | ---: |
| 90 分钟首批 | 5 | 960 ms | 1,046 ms |
| 90 分钟续页 | 5 | 704 ms | 969 ms |
| 120 分钟首批 | 5 | 1,186 ms | 1,194 ms |
| 120 分钟固定续页复测 | 20 | 1,216 ms | 1,431 ms |

120 分钟固定续页的 20 次样本 P95 为 1,376 ms。此前五次续页试测中单次最高 1,571 ms，最终重启后首批单次 1,505 ms。所有默认 500 根样本均低于 5 秒，回包约 0.28–0.35 MB。最后一轮 HTTP 和浏览器验收服务进程峰值 RSS 约 602 MiB，包含整套 Web 运行，单请求内存见阶段 2 记录。耗时结果限定在同一标的、窗口和本机隔离环境。

### 本机切换与加载提示验收

2026-11-25。用户确认股票分钟图加载提示验收通过。修复提交为 `28df3f8bb`。前端测试覆盖回包前的所选周期提示及回包后提示消失，Chrome 确认 30／120 分钟加载占位只显示对应文案。

本机 `5174` 的 Wealth 开发入口已加载合并请求和修复后的加载组件。本机 `8000` 的 `/minutes` 已启用合并回包。贵州茅台 `600519.SH` 的 2026-11-17 30 分钟有界核验返回 HTTP 200，同一回包内有 1 根 K 线、1 组指标和九转对象，调试信息指向 DG Silver 股票不复权分钟行情和股票复权因子。股票分钟线专项的本地开发入口切换收尾完成。

`8000` 同时提供的一份 Wealth 静态构建仍为旧版本。本次页面验收使用 `5174` 开发入口。
