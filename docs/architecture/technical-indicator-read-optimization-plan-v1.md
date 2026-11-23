# 技术指标算子库读取优化方案 v1

**2026-11-23｜阶段 1、2 已实现并复核。** 本专项减少已接算子库链路的重复读取。本地股票和指数日线已经由算子库按截止日和根数取数，见[股票日线复核](technical-indicator-read-optimization-low-level-design-v1.md#stage-1-read-acceptance)和[指数日线复核](technical-indicator-read-optimization-low-level-design-v1.md#stage-2-read-acceptance)。其余链路按下表分阶段推进。基线参考[股票首屏验收](../../wealth/docs/pages/stock-detail/stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md)、[指数日线验收](../../wealth/docs/pages/index-detail/index-detail-low-level-design-v1.md#local-index-daily-history-browser-acceptance)和[上一次股票日线读取修复](technical-indicator-stock-period-low-level-design-v1.md#stock-daily-read-repair)。

## 1. 范围

| 链路 | 优化前 | 本次优化 |
| --- | --- | --- |
| 本地股票日线首屏和续页 | 业务先逐日查找本页日期，再读日线展示字段。算子库另读同一批日线取价，并逐日查停牌做缺口检查。 | 算子库接收截止日和根数，直接读日 K 和所需预热，当次返回同源展示字段。缺口检查交给 DG。 [股票日线接线](../../src/app/dependencies/stock_daily_technical_indicators.py#L181) · [按根数读取](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L633) |
| 本地指数日线首屏和续页 | 业务先按开市日选页。算子库读日期和四价，业务随后另读同一行情来源的量额、昨收及涨跌字段。 | 直接按截止日和根数取实际行情，复用同次取数。整页的行情更新判断由 `/page-init` 负责。 [现行指数选页和组装](../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py#L231) · [现行定位](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L343) |
| 本地指数周线和月线 | 业务先读成品选页和取展示字段，内核再读同一个成品文件的日期和价格。部分空页或延迟还会另查成品首尾。 | 选页、预热、价格和展示字段复用同一次读数，组装时复用该次取得的截止日和必要的范围信息。 [业务选页](../../src/biz/queries/wealth/market/index_detail/index_detail_period_kline_query_service.py#L35) · [内核定位](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L539) |
| 指数 5 分钟不复权算子 | DG 和 Prod 已启用计算。DG 先读时间定位，再读行情列，部分场景还要重读时间找边界。指数分钟详情仍走现有成品接口。 | 优化已启用的 5 分钟取数。时间定位和价格共用读取结果，按真实时间戳和已有开盘规则计算。开发安排见 §5。 [分钟定位](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L245) · [分钟详情入口](../../src/biz/api/wealth/market/index_detail_minutes.py#L54) |
| Prod 已接入的链路 | 股票日线、上证综指已接入的日线分支、指数周月线和独立的指数 5 分钟算子，存在程度不同的先查范围再取价。 | 纳入后续优化评估，先以本地结果和有界 Prod 测量判断实际收益，再决定是否实施。见 §5。 [指数路由](../../src/biz/api/wealth/market/index_detail.py#L174) · [Prod 行情读取](../../src/foundation/clients/technical_indicator_postgres.py#L173) |

**股票周线、月线由原专项负责，排除在本次优化范围之外。** 原专项直接使用已发布的前复权行情，并复用已读成品计算指标。股票分钟线、指数九转迁移、趋势通道和 ETF 属于各自的后续需求。本专项只读现有来源，沿用本地读 DG、Prod 读 PostgreSQL 的运行方式。 [股票周月线专项](technical-indicator-stock-period-plan-v1.md) · [运行环境装配](../../src/app/runtime/technical_indicators/composition.py#L34)

## 2. 通用取数方式

1. **业务传截止日和根数。** 算子库增加「截至某个日期或时间，取最近 N 根」的内部调用方式。调用方传标的、周期、复权口径、指标、包含该时刻的截止点和返回根数。上游明确给出起始日期时，用它限制可返回的目标行情。已有明确起止范围的计算调用继续用原合同。当前 `output_rows` 是上限，只改上限无法替代本次取数能力。 [计算请求](../../packages/technical_indicators/src/goldenshare_technical_indicators/contracts.py#L48) · [现有根数上限](../../packages/technical_indicators/src/goldenshare_technical_indicators/service.py#L78)
2. **从实际行情选中目标记录。** 从截止点往前按时间排序，匹配该标的的记录才计一根。达到目标根数就确定本页。到数据历史起点时，返回实际可用根数。已有的业务历史下限仍约束返回范围。算子库按原有指标预热规则读取目标之前的记录，预热行情只用于计算。500 根是现有日 K 页的返回上限，部署给出较低上限时按现行限制执行。请求超限按对应接口的既有规则处理。 [前端日 K 页大小](../../wealth/src/shared/charts/dailyChartRequestLimits.ts) · [股票日 K 请求校验](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_calculations.py#L42)
3. **DG 按批查实际文件。** 按截止点和候选分区的目录日期形成一批路径，交给 DuckDB 批量读取所需字段。按标的和日期或时间过滤，倒序取所需记录。日线批量读取直接使用 DG 已发布的数据，按现有字段读取，省掉读取前逐文件检查表头和查找证券。候选范围内根数不足时，向更早的分区补读，复用已取得的记录。对单个周线或月线成品文件，用标的和周期范围读取所需数据。`LIMIT` 约束查询返回行数，候选文件范围、实际打开次数和内存开销分别验收。现有股票复权因子读取已经使用多文件查询，见 [DG 读取器](../../src/foundation/clients/local_lake/technical_indicator_price_source.py#L383)。
4. **同一批数据交给算子与组装层。** 记录按时间升序交付。计算结果提供每根的实际时间、现有行情和指标结果，读取层同时交付同源展示字段。本页最早记录之前如有更早一根，其实际时间供业务生成 `nextEndDate`。预热已经读到那一根时直接复用。没有更早可返回的行情时，业务返回空游标。算子库提供行情日期，业务负责首屏、续页和 HTTP 字段。
5. **沿用现有计算和错误口径。** 一次请求中的算子共用同一批标准行情。股票日线不复权行情与股票复权因子仍是前复权计算输入，复权基准与价格计算规则沿用现有实现。既有的单位、预热精度、指标公式、九转显示、日期时区、数据源归属、输出上限、取消和错误分类均按对应合同验收。业务正常空页与数据读取故障分别处理。一次调用的行情、预热和交接数据随请求释放，失败或取消后相同参数重新执行。

## 3. 本地日线接口

### 3.1 股票日线

- `/kline` 把截止日和根数交给算子库。DG 股票不复权日线同次读出计算用价，以及昨收、涨跌额、涨跌幅。业务使用返回的实际日期从 DG 股票每日指标补换手率、量比。两项每日指标由业务组装。
- **缺口由 DG 检查。** DG 的 Silver 股票日线覆盖检查按上市退市状态和全日停牌，核对当日应有的股票是否齐备。算子库按实际日 K 计数，取消本地股票日线请求中的逐日停牌查询及用交易日历、上市退市区间重建应有日期的历史缺口检查。字段、价格和复权因子错误仍按现有合同报告。页面确定日期所需的交易日历另有业务用途。 [DG 股票日线覆盖检查](../../lake_console/orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py#L1135) · [当前内核检查](../../src/foundation/clients/local_lake/technical_indicator_price_source.py#L338)
- **股票首屏的行情状态由 `/kline` 生成。** `/page-init` 确定页面日期和股票身份。首屏 `/kline` 用请求的截止日与末根实际日 K 日期生成行情状态，盘口也从同一根行情组装。比如请求截至周五、末根为周四，页面日期仍为周五，盘口日期为周四。这项比较直接用已有日期，无需再查交易日历。日 K 首屏和续页沿用现有 `tradeDate`、`endDate` 和 `nextEndDate`，续页更新本批 K 线和指标。九转随本批日 K 返回，前端仍只显示 1–9。 [股票初始化](../../src/biz/queries/wealth/market/stock_detail/stock_detail_query_service.py#L60) · [日 K 状态与盘口](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py#L150)
- 当前两个接口都读取股票身份和市场日期上下文。`/kline` 用这些信息校验标的、限定上市起点和组装现有 `pageContext`。LLD 要将这些业务所需信息与行情选页、历史缺口检查的读取分开核算。 [日 K 请求准备](../../src/biz/queries/wealth/market/stock_detail/stock_detail_query_service.py#L156)

### 3.2 指数日线

- **首次 `/page-init` 判断整个页面的行情更新情况。** 业务按交易日历确定应更新日期，从普通指数日线取到实际可用的行情，并把 `asOfTradeDate` 返回给前端。比如周五晚上应有周五行情而 DG 最新到周四，首屏就以周四为此次页面的实际截止日，更新状态仍由这一环节确定。 [指数初始化](../../src/biz/queries/wealth/market/index_detail/index_detail_page_query_service.py#L76)
- **常规 `/kline` 首屏和续页省掉第二次查日历选页和重判整页最新状态。** 首屏根据 `asOfTradeDate`，续页根据上批 `nextEndDate`，直接取最近 N 根实际指数日 K。同次带回四价、量额、昨收及涨跌字段。依据实际行情决定下一批从哪天开始，`meta.endDate` 继续反映调用方请求的截止日。`/kline` 按本批真实结果报告空页或部分指标缺失，前端仍使用这些状态。 [前端首屏](../../wealth/src/features/index-detail/controller/useIndexDetailController.ts#L99) · [前端续页](../../wealth/src/features/index-detail/controller/useIndexDailyHistory.ts#L162) · [状态消费](../../wealth/src/features/index-detail/model/indexDetailState.ts#L39)
- 现行 API 还允许直接传休市日或省略截止日。仓库里常规页面和调试页均明确传截止日。保留已有直接请求的日期与状态口径，所需日期由业务按对应请求解析。例如直接请求截至周日，回包 `meta.endDate` 仍是周日，周五开市且数据到齐时，期望和实际日期均为周五。保留现有 `pageContext` 与 `dataStatus` 字段。处理这些日期语义时，以所需日期为范围。 [休市日回归](../../tests/app/technical_indicators/test_index_daily_kline_integration.py#L138)
- 指数历史行情完整性是现有的另一项检查。代码级设计单独对账 DG 指数日线覆盖检查和内核已有缺数行为，沿用现行的缺数处理口径。股票日线已确认的停牌检查调整只适用于本地股票日线。 [DG 指数日线检查](../../lake_console/orchestrator/src/orchestrator/defs/checks/index_daily_checks.py#L1101) · [内核日期对齐](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L141)
- **指数首屏沿用现有接口分工。** `/page-init` 取截止日及以前最新的一根普通指数日 K，组装盘口，并用其实际日期查询估值、换手率和成分股涨跌统计。当天无行情时，读取器会向前查到最近有记录的一天，最终只使用一根日 K。首批 `/kline` 按这根的日期查整批行情，允许两个接口读到同一根。本轮消除的是同一次 `/kline` 内重复选页和读取同批行情。 [指数首屏取数](../../src/biz/queries/wealth/market/index_detail/index_detail_page_query_service.py#L76) · [查最新一根](../../src/foundation/clients/local_lake/index_daily_reader.py#L98) · [按实际日期查每日指标和成分数据](../../src/biz/queries/wealth/market/index_detail/index_detail_page_query_service.py#L106)

## 4. 指数周月线和 5 分钟线

### 4.1 指数周线、月线

运行时继续读取 DG 正式指数周线和月线成品。请求按标的、周期和日期范围取得目标及预热记录，复用成品字段完成行情与指标组装。自然周期起始日用于排序和对齐，实际行情截止日用于回包显示和更新状态。遇到空页、节假日短周、当周或当月尚未更新时，沿用已有的预期日期、历史分页和状态规则。若有业务需要用到最早或最新成品的日期，由读数结果提供或按需核对，避免再扫一遍同一批价格。 [原指数周月线方案](technical-indicator-index-period-plan-v1.md) · [当前周月线回包](../../src/biz/queries/wealth/market/index_detail/index_detail_period_kline_query_service.py#L95)

### 4.2 指数 5 分钟不复权算子

按已启用的指数范围和正式分钟数据源优化内部读数。现有分钟读数以实际记录为准，时间有空档时按已读记录计算。保留排序、重复时间处理、开盘 K 线及量额规则。核对预热、跨日及 09:35 附近读取边界，减少仅为了计数或定位时间而再次读所选行情。详情页分钟 K 线和分钟指标迁移仍由分钟线专项处理。 [现有分钟读取测试](../../tests/foundation/technical_indicators/test_stage_b_index_minutes.py)

## 5. 推进顺序

| 阶段 | 主要任务 | 通过标准 |
| --- | --- | --- |
| 1. 通用取数与本地股票日线 | 新增算子库按截止日和根数取行情的能力，打通股票首屏、历史页和组装。按已确认的范围取消请求内历史缺口和停牌查询。 | 首屏、续页、历史不足正常。日期、前复权价格、指标、九转、盘口与同口径基线一致。请求跟踪确认同一批日线用于选页和计算，业务只补独立的每日指标。 |
| 2. 本地指数日线 | 复用新取数能力，省掉业务日历选页和整页最新状态的二次判断，合并普通指数日线字段读取。 | 上证综指、深证成指、北证 50 和中证 A500 的首屏与续页可正常使用。校对页边界、空页、部分指标状态及直接请求休市日的语义。 [原验收记录](../../wealth/docs/pages/index-detail/index-detail-low-level-design-v1.md#local-index-daily-history-browser-acceptance) |
| 3. 本地指数周月线 | 合并周期成品的选页、预热和字段读取。实际截止日与行情一起交付业务。 | 分别核对周、月的首批、续页、历史起点和当期未齐场景。数据状态和日期与原合同一致，同一批成品服务于计算和组装。 |
| 4. 本地指数 5 分钟算子 | 优化已启用的分钟取数与定位，安排在日线和周月线之后，可与后续指数分钟详情迁移衔接。 | 相同输入的时间、开盘规则、量额、预热和指标一致，记录重复读取的减少量。验收范围是算子库调用。 |
| 5. Prod 评估 | 对股票日线、上证综指已接入的日线分支、指数周月线和指数 5 分钟现有路径做有界对照。评估合并日期和价格查询，以及股票日线基准日因子碰到批内日期时复用同一条。 | 单独记录查询次数、扫描范围、返回根数和耗时，按收益确定实施范围。实施和上线另行确认。 [Prod 复权基准与批次因子读取](../../src/foundation/clients/technical_indicator_postgres.py#L242) |

## 6. 性能和验收

- 用相同标的、截止日期、根数和指标做优化前后对照。股票日线复用平安银行首批和向前一批的样本。现有参考样本每批返回 500 根、另外用 500 根前置行情计算。后者是该样本和现有指标组合的记录，其他请求按自身指标所需预热计算。 [股票日线历史实测](technical-indicator-stock-period-low-level-design-v1.md#stock-daily-read-repair)
- 分开计量 DG 文件实际打开次数、唯一文件数、执行查询次数、返回根数、预热根数和端到端耗时。首屏验收分开记录 `/page-init` 与 `/kline`，分别识别同一请求内的重复读取和两个接口间的行情重叠。查询条数减少仍要核对实际文件读取范围。对比采用可说明的相同缓存条件。按现行部署的输出、内存、输入和文件限制验收。默认总时限 8 秒含 2 秒清理预留，从请求到达起的工作时限为 6 秒。 [部署配置](../../src/foundation/config/settings.py#L76) · [时限计算](../../packages/technical_indicators/src/goldenshare_technical_indicators/execution_control.py#L21)
- 新增回归集中在实际使用的路径。涉及页面的阶段验收首屏、向左翻页和历史到头，对照同一批 K 线的日期、价格、量额、指标值及空值位置和回包状态。复用股票与指数既有路由和分钟、周月算子测试，按阶段用有界正式样本核对。
- 对可能跨批读取的请求，记录取消前已读取的范围和条数、释放资源的时间、用相同参数重试的总开销。正常执行、取消清理和重试都沿用当前资源配置。
- 各阶段开工前在专项 LLD 明确具体方法、查询边界、结果字段、调用方和基线。验收完成后将相应结果回写既有设计和 本地后端技术指标来源审计表，便于核对实际运行状态。
