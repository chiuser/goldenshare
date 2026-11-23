# 股票周线、月线算子库方案 v1

**2026-11-24｜阶段一股票日线读取修复、阶段二股票周月线区间计算和阶段三股票详情接入均已完成验收。** 阶段三复用通用取数入口，接入 DG 和 Prod 前复权周月线。本方案落实[股票周月线需求](technical-indicator-stock-period-requirements-v1.md)，设计与实测见[专项 LLD](technical-indicator-stock-period-low-level-design-v1.md#stock-period-phase-three-acceptance)。

## 1. 取数与计算

股票周月线直接使用本环境正式发布的前复权行情。

| 环境 | 股票周线 | 股票月线 |
| --- | --- | --- |
| DG | `silver/quote/stock_weekly/week_end={week_end}/part-000.parquet` | `silver/quote/stock_monthly/month={month}/part-000.parquet` |
| Prod | `core_serving.stk_period_bar_adj`，`freq=week` | 同表，`freq=month` |

股票详情后端把股票、周期、截止日和指标配置交给日线已在用的 `calculate_with_source()`。周线另传返回根数，月线取截至该月的全部可用历史。算子库选出本批成品、按需读前置历史并计算指标，同时交付本批行情、指标、九转、成品覆盖事实和周线下一页截止日。DG、Prod 的股票周月线接入这个入口，沿用各自现有的成品读取方式。股票详情沿用 `/kline` 组装回包，页面按结果原顺序绘图。日线和分钟线继续按各自合同运行。趋势通道及其他独立图层另行安排。[通用取数合同](technical-indicator-read-optimization-low-level-design-v1.md#2-计算指令与读数结果)

股票周月线首期提示框显示日期、前复权开高低收、成品涨幅、成交量和成交额，省略振幅和换手率。`/kline` 保留 `amplitude`、`turnoverRate` 两个字段，首期返回 `null`。两项数值的计算、取数和展示作为后续独立需求接入。[接口和提示框细节](technical-indicator-stock-period-low-level-design-v1.md#stock-period-tooltip)

## 2. 历史起点

**DG 和 Prod 股票周线共用 2014-01-02 历史起点，包含截至 2014-01-03 的成品。** 展示、翻页和预热均按这一口径。首周沿用已发布的整根前复权周 K。平安银行两端的第一根均显示 **2014-01-03**。覆盖范围内的新股按实际首根成品起算。股票月线按各端正式成品覆盖范围起算。

历史上整周或整月停牌且没有该股成品时，图表直接跨过该周期。分页、预热和指标都按实际成品根数计算。当前周期是否应有行情，仍按个股应更新日判断。[股票周期取数与校验](technical-indicator-stock-period-low-level-design-v1.md#stock-period-suspension)

整个股票详情页共用 `pageContext.tradeDate` 作为行情日期锚，沿用北京时间 20:00 切换规则。首屏把这个锚点作为算子的截止日，续页使用算子上次返回的游标。后端用现有交易日历、上市退市和全日停牌规则确定个股应更新日。首屏使用算子同次读到的当期成品 `end_date` 确认数据到哪天，历史 K 线用成品 `trade_date`。行情、指标、九转和提示框字段使用同一批结果。成品未达到应更新日时，图表继续显示可用数据，并提示应到日期和当前显示到哪天。当期覆盖日无法确认时，由算子保留可展示的历史，页面显示更新未确认的提示。[日期与延迟处理](technical-indicator-stock-period-low-level-design-v1.md#stock-period-freshness) · [算子读数和接口组装](technical-indicator-stock-period-low-level-design-v1.md#stock-period-read-handoff)

`/kline` 按周期处理缺省参数。日线默认 500 根，周线默认 100 根，月线在算子库现有输出上限内一次返回可用历史。周月线省略日期时，先按页面的日期规则补齐，再判断是否为首屏。日、周、月分别管理图表视野和加载状态。周线向左追加旧数据时保留视野，重新进入周线或月线时重新请求首屏，以最新回包更新行情和延迟提示。[接口与页面规则](technical-indicator-stock-period-low-level-design-v1.md#stock-period-page)

## 3. 算子库参数配置和首期指标

算子库内置**返回 500 根**和**返回 100 根**两套配置。阶段二的日期区间计算使用配置限制输出根数。阶段三的股票周线由算子库按截止日选最近一批，首批和续页上限均为 100 根，历史不足时返回实际可用根数。月线由算子库按截止月返回可用历史。现有日期区间调用继续使用原有默认行为和环境上限。[配置和调用细节](technical-indicator-stock-period-low-level-design-v1.md#stock-period-calculation-options)

返回根数和预热精度独立设置。股票详情的前复权周线首批和续页选 **100 根**，并显式选择 MACD、KDJ 初值误差上限 **0.00001**。两项配置随同一次计算传入，DG 和 Prod 共用。指数周月线等现有调用继续使用现有返回范围和预热规则。

股票周线和月线首期使用 MA(5、10、20、30、60、90、250)、BOLL(20、2)、MACD(12、26、9)、KDJ(9、3、3) 和九转。按股票周线所选精度，MACD 需 359 根、KDJ 需 56 根、MA250 需 249 根、BOLL20 需 19 根、九转需 16 根。各指标共用前置行情，取最大值 **359 根**。首期周线一页最多送 **459 根周 K** 给算子，历史不足时从最早可用周 K 计算。新增九转周期能力适用于股票前复权周、月线。

股票月线一次返回各端全部可用月线成品，从最早可用的一根开始计算，额外预热为 0 根。

## 4. 实施和验收顺序

1. **先验收股票日线读取修复。** 完成第 5 节的独立修复，对比读数次数及修复前后的行为。
2. **实现并独立验收算子库。** 先实现两套返回配置和独立的预热精度选择，再接 DG、Prod 的前复权成品和五类指标。开工前核对两端覆盖、日期类型、量额单位和单股有界读数耗时。用同一标的、同一截止日对照两套配置的重合行情和指标精度。两端用平安银行分别测周线首批 100 根、向前一批、最早一批和月线全历史，用同源成品从历史起点独立计算，对照未舍入的指标和逐根九转计数。记录请求、取消和重试耗时，沿用 6 秒工作时限和 8 秒总时限。
3. **将股票周月线接进通用取数，再接详情。** 先在 `CalculationRequest`、`calculate_with_source()` 和股票周月线成品读取中补齐 DG、Prod 的截止日选页、周线预热与续页、月线全历史和正常空页。两端算子验收后，再接 `/kline` 和 `/page-init`，后端直接组装算子结果。最后接页面周期切换、周线左拖、九转及延迟提示。两端逐根核对日期、指标、九转和提示框，振幅与换手率返回 `null` 并省略对应两行。[阶段三代码对照与实施范围](technical-indicator-stock-period-low-level-design-v1.md#stock-period-phase-three) · [股票详情接口实施方案](../../wealth/docs/pages/stock-detail/stock-detail-implementation-design-v1.md#stock-period-contract)

性能验收同时核对耗时和实际读取。单次请求中，算子读取的成品供行情、指标、九转和回包组装共用。预热按指标实际需要读取。记录 DG 文件打开次数、Prod 查询次数、读取字段和根数，并核实 Web 组装时的额外行情读取为 0。阶段三用 DG、Prod 的平安银行实测周线首批、续页、末页和全量月线，并记录真实页面的周月切换和左拖加载耗时。算子沿用 6 秒工作、8 秒总时限；正常页面操作按 Wealth 清单的默认 5 秒核对，不改通用超时机制。计量方法和阶段二实测见[专项 LLD](technical-indicator-stock-period-low-level-design-v1.md#stock-period-performance)。

## 5. 算子库股票日线读取修复

保留先于周月线算子库实施的独立修复轮次。DG 复用日线定位和取价的读取结果，并减少重复打开停牌文件。已有复权基准因子复用照常使用。用相同请求对照修复前后的结果、错误、取消行为和实际文件打开次数，回归原有股票、指数和分钟链路。范围和验收见[独立修复设计](technical-indicator-stock-period-low-level-design-v1.md#stock-daily-read-repair)。
