# 股票详情首屏与本地 DG 取数迁移方案 v1

> 2026-11-19 · 待评审。本文记录已确认的业务口径和本期实施方案。接口变更、代码落点和阶段验收见 [实施 LLD](stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md)。

## 1. 本期目标和范围

1. 股票详情页由首次返回的页面交易日锚定整页。盘口复用首屏日 K 的最后一根实际行情，使盘口、图上四价和日线指标来自同一次计算。
2. 本地 Web 请求从 `core_serving.security_serving` 和 `core_serving.trade_calendar` 读取的证券及日历业务事实切到 DG，包括直接读取、多行查询以及 SQL 关联。覆盖股票详情以外的业务和运维 API。独立 CLI、调度及巡检进程的配置不纳入阶段 2。
3. 方案按本地后端实施和验收设计。Prod 后端的取数和接口行为沿用现有口径。共用前端的变更须在 LLD 中证明与现有 Prod 接口兼容。本期使用现有算子库的股票日线能力。
4. 去掉 DG 上交所交易日历的本地取数日期限制。代码验收后手动运行一次现有更新 Job，补齐 Raw 和 Silver，作为本地交易日历切换的前置工作。
5. **下一期范围限定本地后端。** 指数和股票详情的分钟线切换放到下一期。股票分钟线先升级并验收算子库的不复权读取、前复权和指标，再切页面。指数分钟线按 DG 的数据和周期逐项核实。下一期暂不改动 Prod 后端。
6. **股票日 K 向前翻页单独开发。** 本地首屏切换和复验已完成。先修复本地股票趋势通道的读取，再沿用上证综指的方式接入股票翻页，具体口径见 §6。

现状依据见 [字段来源表及首屏时序](stock-detail-field-source-audit-v1.html#first-screen-sequence) 和 [算子库实施 LLD](../../../../docs/architecture/technical-indicator-operator-library-implementation-lld-v1.md)。

## 2. 统一页面日期

股票详情页首次取得的 `pageContext.tradeDate` 是**本次页面加载的最新日期锚点**，以 `Asia/Shanghai` 解释。随页面明确指定的日期或现行默认日期规则由后端一次解析，前端以回包值为准。

### 保留现行的日期解析和行情状态

2026-11-19 确认，本期只更换本地取数来源并统一日期传递，保留当前日期解析与行情滞后规则。后端仍以北京时间和 SSE 交易日历确定页面日期。

| 情况 | 页面锚点和盘口行为 |
| --- | --- |
| 首个请求显式传入 `tradeDate` | 页面日期采用指定日期。 |
| 未传日期，当天开市且有上一开市日 | 北京时间 20:00 前取上一开市日，20:00 起取当天。 |
| 未传日期，当天开市且查不到上一开市日 | 取当天。 |
| 未传日期，当天休市，或本地日期已超出日历的最新日期 | 取截至当天的最新开市日。日历成功读取并查无任何可用开市日时，沿用当前以当天日期作为页面日期的规则。 |
| 实际行情早于页面日期 | 盘口保留实际行情日期，状态为 `DELAYED`。后续接口继续以首个回包的页面日期作为最新边界。 |
| 无实际行情或实际行情达到锚点 | 无实际行情为 `EMPTY`，达到锚点为 `READY`。本地改造后按首屏日 K 的实际日期判断。 |

日期对照须固定时钟并分别覆盖 20:00 前后、休市、有显式日期、日历落后、日历成功读取但查无可用开市日，以及有效数据源上的行情落后。DG 文件读失败走取数错误规则。

[现行日期解析](../../../../src/biz/queries/wealth/market/context/market_page_context_query.py#L91) · [盘口状态判断](../../../../src/biz/services/wealth/market/stock_detail/stock_detail_field_mapper.py#L49)

### 后续请求如何使用日期

- 日期明确之前，页面内的行情和时间窗口请求等待该日期。锚定后，每条有日期语义的请求都用这个日期作为最新边界。
- 每个接口仍返回自己的实际数据日期和数据状态。停牌、休市或更新未到时，实际行情可能早于锚点。实际返回的最后一根日 K、行情发布时间和游标只用于各模块自身的窗口及展示，页面日期锚点由首个回包确定。
- 周期切换沿用同一页面日期。切换证券、显式切换日期或刷新才重新获取页面日期，并取消或丢弃旧页面的未完成请求和缓存结果。将来股票日 K 翻页时，页面日期仍固定，每批历史数据使用自己的截止日。
- 自选分组、权限与账户等没有日期窗口的接口继续按原对象或用户参数读取。交易助手表单的用户输入时间仍按表单合同处理。

| 页面请求 | 日期锚的用法 | 现状与本期处理 |
| --- | --- | --- |
| 首屏日 K `/kline` | 本地将 `pageContext.tradeDate` 同时传给现有的 `tradeDate` 和 `endDate`，分别表示页面日期和本批日 K 的截止日 | 本地首屏一次返回日 K、指标和盘口。Prod 仍使用现有日期参数，产品上限 500 根。 |
| 分钟行情、分钟指标、日线与分钟九转、趋势通道 | `endDate = pageContext.tradeDate` | 现有调用已从页初始化结果取日期。本期核对日期传递和请求生命周期，分钟取数与指标计算链留到下一期。 |
| 页面顶部主要指数 | `tradeDate = pageContext.tradeDate` | 现有股票页面调用 `useMajorIndexTickers()` 时未传日期，挂载即请求。本期让股票详情中的这次调用等待锚点并显式传入。 |
| 股票新闻 | 沿用现有带时区的 `endAt`，以页面锚定日次日 00:00（上海时间）作为不包含的上界 | 现有页面只传股票代码和条数，服务端省略 `endAt` 时取当前时间。新闻仍按真实发布时间排序、展示。 |

例如，页面显式锚定到休市日 2026-11-15，后续请求仍以该日期为上界。若实际最新日 K 为 2026-11-13，盘口显示该根行情并保留实际日期，页面日期仍为 2026-11-15。

[股票详情首屏和图层请求](../../../src/pages/stock-detail/StockDetailPage.tsx) · [顶部指数请求](../../../src/features/major-indices/model/useMajorIndexTickers.ts) · [股票新闻接口时间合同](../../../../src/biz/api/wealth/market/stock_detail_news.py) · [新闻窗口查询](../../../../src/biz/queries/wealth/market/stock_detail/news_query.py)

## 3. 盘口复用首屏日 K

现行顺序是前端先请求 `/page-init`，拿到页面日期、证券身份和旧股票日线技术因子表构成的盘口，再用页面日期请求 `/kline`。此时盘口已经独立返回。`/kline` 用不复权日线和股票复权因子计算，现行回包已含盘口所需的全部基础字段。

本期的目标顺序仍先取得页面日期，然后执行一次首屏日 K 和指标计算。业务端用该次计算和组装所得的**最新一根实际返回的目标日 K**组装盘口。

| 盘口内容 | 组装规则 |
| --- | --- |
| 实际日期、最新价、开高低收 | 使用该日 K 的 `tradeDate` 和内核算出的前复权四价，最新价取 `close`。 |
| 昨收、涨跌额、涨跌幅、方向 | 复用该日 K 业务层已经匹配的昨收和涨跌字段。方向沿用后端现行按涨跌幅判断的规则。 |
| 成交量、成交额、换手率、量比 | 复用同日 K 已组装的量额和股票每日指标字段，沿用现行接口单位与盘口空值显示。 |

页面初始化阶段提供页面日期、证券身份、图表默认项和功能开关。待日 K 完成后，从同一批目标日 K 结果得到盘口、图表和指标。日 K 无目标数据时显示现有空态，取数、计算或源合同错误按现有接口错误语义呈现。相同锚点的局部重试仍使用同一日期。

**2026-11-20 确认的本地首屏合同。** 沿用两个现有 URL 和现有请求参数。`/page-init` 首先确定页面日期 D。前端请求 `/kline` 时传 `tradeDate=D` 和 `endDate=D`，省略 `startDate`。后端把这组条件识别为首屏，并从同一次日 K 结果组装 `quote`，随日 K、指标和行情状态返回。无目标日 K 时，首屏回包带 `quote: null`。普通日 K 请求沿用原回包结构，判定细节见 [LLD §5.1](stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#51-现有-url-和回包结构)。

`/page-init` 当前带 `quote` 和依赖报价的 `dataStatus`，调整其回包分工属于接口合同变更。LLD 须确认现行消费者全部随本地链路迁移，明确 DTO、加载状态和本地与 Prod 的接口选择方式。Prod 响应保持既有合同，包括字段是否存在。首屏达到目标时，本地股票详情的盘口、日 K 与指标由正式不复权日线和附属数据生成，盘口链路退出 `core_serving.equity_factor_pro`。

[现行盘口查询](../../../../src/biz/queries/wealth/market/stock_detail/stock_detail_query_service.py) · [日 K 内核调用](../../../../src/app/dependencies/stock_daily_technical_indicators.py) · [盘口与日 K DTO](../../../../src/biz/schemas/wealth/market/stock_detail.py)

## 4. 所有本地后端的两类读取切到 DG

| PostgreSQL 现行对象 | DG 源及已核实覆盖 | 迁移合同 |
| --- | --- | --- |
| `core_serving.security_serving` | 股票基础信息全上市状态文件 `/Volumes/datasource/data_lake/raw/tushare/stock_basic/full/part-000.parquet`。文件有 `ts_code、symbol、name、area、industry、cnspell、market、exchange、curr_type、list_status、list_date、delist_date` 等字段。DG 样本包括贵州茅台和已退市的武钢股份。 | 按股票代码匹配，保留各消费者的上市状态、交易所、币种、搜索与存续日期规则。将源 `YYYYMMDD` 的上市、退市日归一为现行日期类型，空值沿现行语义。`security_type`、`source` 及股票以外适用范围在 LLD 逐项核对，不以单一股票文件推定全量主数据已等价。 |
| `core_serving.trade_calendar` | DG 交易日历 `/Volumes/datasource/data_lake/silver/calendar/trade_calendar/full/part-000.parquet`。已核实字段 `exchange、trade_date、is_open、pretrade_date` 及开市、休市样本。当前 DG 原始日历任务固定请求 SSE。 | 按 `(exchange, trade_date)` 匹配，保留调用方当前的交易所、开市和上一交易日语义。已有 DG SSE 日历读取可复用。通用接口保留交易所筛选，有效文件中该交易所查无记录时仍返回空列表。若业务实际依赖非 SSE 的有效记录，先核清正式来源再切换该调用。 |

**补数前覆盖。** 2026-11-19，DG 以 Parquet 元数据、Prod 以只读分组计数和最早最晚日期核对，两个日历来源均只有 SSE，起点均为 1990-12-19。补数前 DG 末日为 2026-12-31，Prod 为 2027-12-31，记录数分别为 13,162 条和 13,527 条。现有 `/market/trade-calendar` 根据调用方传入的日期范围直接查询，整表迁移若缩短末端覆盖会改变未来日期请求的返回。补数后的 DG 实际覆盖见 §4.1。 [交易日历接口](../../../../src/biz/api/market.py#L19)

**改造前正式环境。** 2026-11-19 查询正式 DG，`calendar_update_job` 已注册，负责更新原始层和整理层交易日历，未绑定 Sensor 或 Schedule。最近一次成功运行是 2026-05-24 13:07（上海时间），两层资产物化记录和 Parquet 更新时间均对应这次运行。当时部署的规则最多请求到运行当年的 12 月 31 日。阶段 1 移除该规则，正式更新按 §4.1 执行。 [更新任务定义](../../../../lake_console/orchestrator/src/orchestrator/defs/jobs/calendar_update.py#L8)

Prod 证券主数据有 5,926 条 `EQUITY / tushare`，DG 股票基础信息 Raw 有 5,924 行。按分组定位并逐键核对上交所退市人民币证券后，确认差额来自 Prod 独有的 `T00018.SH`、`TS0018.SH`（上港集箱）。在市搜索原不纳入两码，已核自选及交易助手记录无这两个代码。仅从 DG 读取后，本地按旧代码直达详情将收到查无标的，已确认按 DG 查无标的处理，Prod 保留原行为。 [核验范围与影响](stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#证券主数据源差异的只读核验)

迁移前逐个登记现行读取入口、所需字段、筛选、顺序、日期语义、关联方式和验证用例。代码搜索和 CodeGraph 已确认范围至少包括股票详情、股票搜索、自选、指数详情、板块、榜单、交易助手，另外须核对行情通用接口、运维查询、运行计划等本地运行时读取这两张表的入口。对指向同一物理表的不同 ORM 模型和原生 SQL 一并查找。只以完成全部已确认调用方迁移作为本期完成条件。

本地在 App 装配时选择 DG，由 Foundation 复用或提供两个正式的只读数据入口。运行模式沿用现有 `APP_ENV=local/dev` 与 DG 根目录配置。日历和证券字段的来源确定后，各业务模块沿用该数据入口及已有语义。需要和 PostgreSQL 业务数据关联时，先按请求范围限制读取，再按原关联规则匹配 DG 事实。证券字段影响筛选、排序或分页的，匹配和筛选须在确定最终页前完成，保留原左连接、内连接和空值口径。其他 PostgreSQL 业务数据依照原来的表和权限读取。以 PostgreSQL 物理表为对象的计数、发布前检查和显式 Prod 审计继续读取各自的实际目标。

本地只从 DG 读取这两类数据。DG 读取区分查无证券、文件无法读取和预期日历缺失，按各入口已有的空态或错误方式处理。缺失项应明确归属到数据集、证券或日期。以原请求重试时从 DG 正式数据重新读取，保留请求边界，采用现有连接和文件清理机制。业务读取迁移使用只读查询和请求内关联，后端无需在 PostgreSQL 创建临时表或写数据。DG 的 Raw、Silver 写入由 §4.1 的正式更新 Job 完成。

[正式 DG 路径](../../../../lake_console/orchestrator/src/orchestrator/defs/paths.py) · [DG 日历生产口径](../../../../lake_console/orchestrator/src/orchestrator/defs/assets/calendar.py) · [现有 DG 日历读取](../../../../src/foundation/clients/local_lake/index_daily_reader.py) · [股票搜索](../../../../src/biz/queries/wealth/market/stock_search/stock_search_query.py) · [自选证券关联](../../../../src/biz/queries/wealth/market/watchlist/watchlist_item_query.py)

### 4.1 DG 交易日历取消日期限制与一次性补数

**取数代码。** 修改 `raw_tushare_trade_calendar`，取消本地写死的起止日期，按 `exchange=SSE` 和明确的字段列表从 Tushare `trade_cal` 分页取得源已发布的全部日历。源返回更远日期时照常保留。已用无日期请求核实首尾为 1990-12-19 至 2027-12-31，并验证倒序分页和末尾空页。无日期首个整页已实返 6,000 条，实施沿用每页 6,000 条和短页结束规则。运行记录中的起止日为文件实际覆盖。Silver 沿用现有字段标准化和路径。同步核对资产目录中的取数与写入说明。 [源接口合同](../../../../docs/sources/tushare/股票数据/基础数据/0026_交易日历.md) · [Raw 与 Silver 实现](../../../../lake_console/orchestrator/src/orchestrator/defs/assets/calendar.py#L367) · [资产目录](../../../../lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py#L1986) · [实测样本](stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#22-源请求日期范围与完整性)

**单次补数。** 代码与隔离测试通过后，在正式 DG 手动触发一次 `calendar_update_job`，由现有 Job 执行 Raw 更新、Raw 检查、Silver 生成和 Silver 检查。正式 DG 沿用现有串行运行队列，每次只执行一个 Run。每层分别在正式 staging 生成候选，校验文件、字段、交易所、日期覆盖与行数后，再原子替换该层文件。若候选为空、覆盖退缩或分页不完整，保留正式文件并记录原因。若只完成一层，以实际文件和已通过的检查确认完成位置，先处理失败层，两层对齐后才能切换读取。 [Job 定义](../../../../lake_console/orchestrator/src/orchestrator/defs/jobs/calendar_update.py#L8) · [现有交易日历检查](../../../../lake_console/orchestrator/src/orchestrator/defs/checks/calendar_checks.py#L164)

**验收。** 测试证明请求不传起止日期，保留源提供的后续日期。候选日期有缺口、历史日期丢失、开市标记非法或上一交易日错误时，该层不会发布。首次正式补数在 Raw 的 Run 配置中指定 `minimum_end_date=2027-12-31`。该日期用于发布前校验最低覆盖，Tushare 请求仍读取源已发布的完整范围。正式运行后，核对 Dagster 运行和两层正式检查均通过，读回两个正式 Parquet 的实际起止日、行数和 SSE 日期键，确认无缺漏、无重复，且 Raw 与 Silver 逐日对应。抽查开休市和上一交易日。若运行前核实源尚未发布所需日期或开休市状态，记录缺口并暂停正式补数和读取切换。 [Silver 字段转换](../../../../lake_console/orchestrator/src/orchestrator/defs/duckdb_sql.py#L168)

**执行预算。** 一次更新只处理 SSE、两个全量 Parquet 和该 Job 选中的三项正式检查。改造前核实的 13,162 行是 DG 现有规模，13,527 行是作为迁移基准的 Prod 覆盖规模。Tushare 无日期实际页长已核实为 6,000 条，按当前首尾预计三页。正式总行数、文件大小和耗时以运行读回为准。 [共用取数方法](../../../../lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py#L195) · [隔离测试和正式执行记录](stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#24-阶段-1-验证记录)

**正式结果。** 2026-11-19 一次补数通过验收。DG 交易日历 Raw 和 Silver 各 13,527 条，覆盖 1990-12-19 至 2027-12-31。三项正式检查通过，两个文件逐日对账无差异。本地后端读取迁移在阶段 2 实施。 [运行和读回证据](stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#24-阶段-1-验证记录)

## 5. 实施顺序和验收

代码实施分四个阶段。方案与 LLD 评审、现行入口清单和两项来源核验属于开工准备。证券差异及日历分页已核实，逐个调用方的回归在对应阶段完成。

1. **DG 交易日历改造与补数。** 按 §4.1 完成无日期取数、候选校验和失败恢复。隔离验证通过并确认正式执行窗口后，手动更新一次 Raw、Silver。两层覆盖、逐日对账与三项检查通过后交付日历切换。
2. **本地后端读取迁移。** 装配 DG 证券与日历读取，逐入口迁移直接读取和关联。保留权限、排序、过滤及分页。用拒绝读取两张 PostgreSQL 旧表的回归证明本地目标入口走 DG。
3. **股票详情首屏改造。** 本地 `/page-init` 先确定页面日期，`/kline` 用同一次日 K 和指标计算结果组装盘口。顶部指数、新闻与图层统一沿用该日期。验证本地首屏与普通区间请求的回包、Prod 原回包，以及换股、换日期、切周期和迟到响应。
4. **联调、验收与本地切换。** 用有界真实数据覆盖在市、已退市、查无证券、开休市和 2027 年边界。逐项比对末根日 K 与盘口，回归 Prod 现行接口。记录首屏性能、读量、重复请求和中断后重试，确认资源释放和版本回退，再交付本地前后端。

首屏验收沿用单页最多 500 根、既有预热和时间预算。各阶段代码入口、通过条件与测试矩阵见 [实施 LLD §6–7](stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#6-开发顺序和验收清单)。

## 6. 本地股票日 K 向前翻页

本地股票首屏完成后，分两步交付股票日 K 向前翻页，范围包括本地股票详情日 K 和同区间的九转、趋势通道。2026-11-20 已在本机 `127.0.0.1:8000` 切换并通过浏览器复验。[本机验收记录](stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#本机切换后复验)

1. **先修复本地股票趋势通道取数。** 修复前按 `limit` 选文件，再找指定股票，停牌日的文件会占用名额。现在从截止日往前读，找到这只股票的一条有效结果才计数，取够 `limit` 条或读完该股票可用历史即停止。读取下限使用后端已取得的上市日，上市日缺失时以最早正式分区为界。结果按日期升序返回。沿用 `/trend-channel` 的 `tsCode`、`endDate`、`limit` 和现有回包格式。用实际停牌和新上市样本分别验收跨缺口取数和读取下限。
2. **修复验收后，接入本地股票日 K 向前翻页。** 复用上证综指的拖动和续页方式，随页加载九转和趋势通道，按日期补到已经加载的日 K 上。原有盘口和页面日期由首屏确定。

- **沿用上证综指的翻页方式。** 用户向左拖动时，前端把上一批 `meta.nextEndDate` 传回现有 `/kline` 的 `endDate`，`tradeDate` 始终取首次页面初始化的日期。后端按该股票实际有行情的日期给出下一批截止日，每批最多 500 根。没有更早数据时返回 `nextEndDate: null`。续页省略 `quote`，前端把更早的日 K 和指标接到图表左侧，保持当前视野、页面日期和右侧盘口。
- **计算沿用现有算子库。** 算子库从 DG 读股票不复权日线和股票复权因子，按原规则计算前复权与技术指标。复权基准留在内核结果中。页面打开期间复权因子发生更新时，接受按各请求当时可用的因子计算，前端直接展示结果。
- **九转和趋势通道按每批实际日 K 日期补齐。** 九转用既有起止日期参数。趋势通道用该批最晚日 K 日期作为 `endDate`，以该批日 K 根数作为 `limit`，按日期把已有结果画在对应的 K 线上。图层失败时已加载的日 K 继续显示，可单独重试图层。Prod、指数及股票分钟线沿用现有接法。 [参数、代码落点和验收条件](stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#54-本地股票日-k-向前翻页)

[上证综指续页请求](../../../src/features/index-detail/controller/useIndexDailyHistory.ts#L161)
