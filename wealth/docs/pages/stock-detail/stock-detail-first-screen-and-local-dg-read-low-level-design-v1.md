# 股票详情首屏与本地 DG 取数迁移 LLD v1

> 2026-11-26 趋势通道专项阶段四（源码清理，未部署）：旧股票/上证独立通道接口、上证专用计算器与缓存、股票旧成品读取器和开关、前端旧请求已删除。现行四轨随日K接口返回；首批、续页、开关、摘要及环境差异沿专项LLD。下文涉及旧独立通道读取、请求或专用测试的内容仅保留为原阶段历史记录；本文其他功能与验收记录保持。现行依据及本次验收见[专项LLD §5](../../../../docs/architecture/technical-indicator-trend-channel-low-level-design-v1.md#5-阶段四旧业务清理与总验收)。

**2026-11-25 后续趋势通道专项（阶段二实现及技术验收完成，未部署）。** 阶段二实现由同一次算子库调用取得行情、原指标和四轨，并在 `/kline` 的每根日 K 中返回必有 `factors.trendChannel`。字段、日线/周月线类型隔离、原函数消费者和测试以[专项 LLD §4.2](../../../../docs/architecture/technical-indicator-trend-channel-low-level-design-v1.md#42-阶段二股票日线)为准；本文件下方旧接口、独立图层与性能记录保留历史语义，不再作为新实现的取数要求。阶段二代码、隔离技术验收、正式 DG 有界及浏览器核验和对照审计见[专项 LLD §10](../../../../docs/architecture/technical-indicator-trend-channel-low-level-design-v1.md#stock-trend-channel-stage2-execution)；常用服务、共享包和 Prod 未切换。

阶段二的具体交接为：`StockDetailPage.loadStockDetail()` 由日 K 生成首批通道点并与 candles 一同保存；`useStockDailyHistory.loadPage()` 先完成 K 线、四轨和九转等转换，成功后才一起提交页数组及 `nextEndDate`，失败保留原图、原游标并重试原批。`StockChartWorkspace` 合并首批和历史页通道点，保留原画法/着色，开关只切绘制；移除新页面的 `useStockTrendChannel()` 调用和历史 `loadTrend/ensureTrend/retryTrend`、独立请求及其重试 UI。保留现有取消和迟到响应处理。

本地继续每批最多 500 根及实际游标，首批盘口/续页省略盘口保持；Prod 沿原环境和参数、原 page-init 盘口及原无本地游标的加载方式，只给日线增加四轨，不新增生产分页或内联九转。本文原迁移阶段“Prod JSON 字段集合不变”不限制此项明确批准的四轨增量，其余原行为仍保留。页面支持标志脱离旧通道配置、结果和续算状态目录；旧接口未删除期间的原限制只控制旧接口。

管理员指定在专项第三阶段整理公共组装：每指标独立 build，公共组合复用，各业务 `assemble()` 显式组合；公共职责迁出日线服务，日线独立调用趋势通道 builder，周月线不新增计算或空轨道。阶段二先完成计算清单隔离和日线接入，不提前拆改公共四组组装。源码依据、函数名、实施范围、预算和逐项回归见[专项 LLD §4.3](../../../../docs/architecture/technical-indicator-trend-channel-low-level-design-v1.md#43-阶段三逐指标组装整理与上证日线接入)。第三阶段已按该设计迁入 `stock_kline_factor_mapper.py`，日、周、月显式组合各指标；改前/改后完整 JSON 一致，48 项股票定向测试通过。分步审计见[专项 LLD §12.1](../../../../docs/architecture/technical-indicator-trend-channel-low-level-design-v1.md#121-股票组装整理的分步审计)，未发包、切换或部署。

> 2026-11-19 · 待开发评审。[本期方案](stock-detail-first-screen-and-local-dg-read-plan-v1.md)确定业务范围，本文规定代码入口、数据合同、实施顺序与验收。下文标为「拟新增」的类和方法是开发合同。

## 1. 实施边界与开工条件

| 工作 | 已确认的规则 | 实施通过条件 |
| --- | --- | --- |
| DG 交易日历 | 上交所 `SSE` 取消本地起止日期限制。复用现有 Job 手动更新一次 Raw、Silver | 两层覆盖至少到 2027-12-31，并保留原有历史。之后源继续提供更远日期则照常收入 |
| 本地证券和日历 | 阶段 2 覆盖本地 Web 请求实际读取的两类业务事实，包含业务与运维 API。有效文件里查不到记录时沿用各入口原来的缺失处理 | §4 中由本地 Web 请求实际执行的读取换源。读 PostgreSQL 的两张旧表会报错的测试环境下，本地调用仍可走通 |
| 股票详情 | `/page-init` 的 `pageContext.tradeDate` 是整页最新日期。本地首屏用现有 `tradeDate` 和 `endDate` 传同一日期，只算一次日 K 和指标，盘口复用末根日 K | 每条后续日期请求都使用该日期。即使实际行情滞后，页面日期仍取初始化结果 |
| Prod 与后续事项 | Prod 继续使用现行 PostgreSQL、原响应模型和原参数行为。股票、指数分钟线的行情来源与指标升级放到下一期。本地首屏已切换，独立的股票日 K 向前翻页设计见 §5.4 | 共用前端分别验证两种首屏回包。原 Prod 响应 JSON 字段集合、值与 OpenAPI 模型通过回归 |

下列核验记录交易日历接口的实际行为和证券来源切换口径。

- **日历取数。** Tushare 只读样本已返回 2026-12-30 至 2027-01-05 的 7 条 SSE 记录，以及 2027-12-29 至 2027-12-31 的 3 条。2027-01-01 为休市，上一交易日为 2026-12-31。MCP 的 `trade_cal` 工具不接受 `limit/offset`。2026-11-19 只读复核正式 Dagster 物化记录 `ab0378dd-08c8-413f-a564-f1c137e585f2`，上次带日期请求以 `limit=6000` 执行 3 页，共 13,162 条。MCP 另外在 1990-12-17 至 12-21 的边界样本中只返回 12-19 起的 3 条，在 2027-12-30 至 2028-01-03 的边界样本中只返回 2027 年末两条。随后用 HTTPS 无日期小页抽查，在偏移 0 读到 2027-12-31，偏移 13,526 读到 1990-12-19，偏移 13,527 返回空。追加一次无日期首屏请求 `limit=6000, offset=0`，实返 6,000 条。无日期分页合同已核实，实施沿用每页 6,000 条，详见 §2.2。
- **证券覆盖。** 已定位本轮计数差额。Prod 5,926 条 `EQUITY/tushare` 与 DG Raw 5,924 条的分组差异仅在 SSE、退市、CNY。该组逐键比较确认 `T00018.SH` 和 `TS0018.SH` 只在 Prod。当前未发现对正常在市搜索、已核自选和交易助手存量记录的影响，直接按旧代码访问本地详情会少这两条证券身份。已确认本地按 DG 查无标的返回 404，Prod 保留原行为，详见 §4。

## 2. DG 交易日历更新

### 2.1 改动位置及执行顺序

| 位置 | 实现 |
| --- | --- |
| [`assets/calendar.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/assets/calendar.py#L367) | Raw 请求固定 `exchange=SSE`，显式投影 `exchange, cal_date, is_open, pretrade_date`。Raw 和 Silver 均先写本次 Run 的候选并校验，再发布。日志报告实际起止日、行数、实际页数及耗时 |
| [`tushare_api_io.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py#L195) | 沿用已实测的 6,000 条页长及现有短页结束规则。共用方法允许调用方提供写入前的源记录检查，本期由交易日历传入开市标记检查，其他调用沿用原行为 |
| [`paths.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/paths.py#L178)、[`catalog/lake_assets.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py#L1986) | 统一定义本次日历候选路径，并校准两个资产的写入、性能及合同说明。正式日历路径沿用现有方法，字段合同沿用 `RAW_TUSHARE_TRADE_CALENDAR_SCHEMA`、`SILVER_TRADE_CALENDAR_SCHEMA` |
| [`calendar_update_job`](../../../../lake_console/orchestrator/src/orchestrator/defs/jobs/calendar_update.py#L8)、[`checks/calendar_checks.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/checks/calendar_checks.py#L164) | 继续选择两层资产及三项正式检查。执行顺序为 Raw 发布、Raw 检查、Silver 发布、两项 Silver 检查。发布 Silver 前逐行核对与 Raw 的一致性 |

候选读取和发布由日历资产负责。Job 继续负责选择资产和检查。测试与正式执行均使用相同的资产逻辑，分别注入临时目录和正式路径。本阶段沿用共用分页与现有串行队列。验证完成的文件，用日期键、连续性和正式历史对账防止残缺候选被发布。执行预计三次源请求，正式窗口的用量以隔离验证和来源核验确认。

每层的候选和发布记录保存到 `data_lake_staging/trade_calendar/run_id=<run_id>/<layer>/`，分别命名 `part-000.parquet`、`publication.json`。发布记录含正式路径、实际日期范围、行数、文件摘要及发布状态。先记候选已校验，再替换正式文件，随后记已发布。Silver 在正常 Job 与从失败重执行时核对正式 Raw 与本次或父 Run 的 Raw 发布记录，沿父链向上查找最近一次 Raw 发布；匹配后继续 Silver，不重新取 Tushare。已有仅生成 Silver 的资产调用继续读取校验过的正式 Raw。中断后如上次记录仍是「已校验」、候选已经移动且正式文件摘要一致，复用这个已发布文件并补齐记录。摘要差异或候选仍在时，不能把它判断成已发布。

首次正式补数通过 Raw 的 Run 参数 `minimum_end_date=2027-12-31` 指定最低验收日期。该参数默认 `null`，只在当前 Run 的发布前验证候选最大日期，始终不传给 Tushare。它记录在 Dagster 的 Run 配置中，消费者只有日历 Raw 资产，重新运行时取该 Run 的配置。来源若已发布更远日期全部保留。测试覆盖无参数、尾端不足、刚好达标和超出验收日期。Raw 写文件前检查源开市标记，允许整数 0/1 和文档中的字符串 0/1，避免 DuckDB 把小数转换成有效开市值。两层文件校验逐日比对上一交易日与前方最近开市日期。已对当前正式 Silver 做只读计数校验，13,162 条均符合该规则。

隔离验收从 `lake_console/orchestrator` 用项目 `.venv` 运行 `test_trade_calendar_update.py` 和相邻基础资产治理回归。Dagster 用隔离 instance，Tushare 用预先核实字段和页界的替身，DuckDB、候选和 Parquet 使用 `/private/tmp` 下的临时目录。

```python
class TradeCalendarUpdateConfig(dg.Config):
    # 本次运行的发布验收下限，ISO 日期。不发送给 Tushare。
    minimum_end_date: str | None = None

@dataclass(frozen=True)
class CalendarFileStats:
    path: Path
    first_date: date
    last_date: date
    row_count: int
    sha256: str

# 按运行编号和层生成候选路径。
def trade_calendar_staging_path(root: Path, run_id: str, layer: str) -> Path: ...

# 校验物理字段、交易所、日期键、连续性和上一交易日。
def inspect_calendar_candidate(connection, path: Path, *, layer: str) -> CalendarFileStats: ...

# 核对旧文件日期键，记录开休市和上一交易日修订的行数。
def _compare_published_history(
    connection, candidate: CalendarFileStats, target: Path, *, layer: str
): ...
```

### 2.2 源请求、日期范围与完整性

**2026-11-19 无日期分页核验。** 通过 Tushare 官方 HTTPS 接口发送 6 次定点只读请求。请求使用 `exchange=SSE`、`limit=3` 和指定 `offset`，仅投影四列交易日历字段。省略 `start_date/end_date`，各偏移返回情况如下。

| `offset` | 行数 | 该页日历日期，按返回顺序 |
| --- | --- | --- |
| 0 | 3 | 2027-12-31 至 2027-12-29 |
| 3 | 3 | 2027-12-28 至 2027-12-26 |
| 5,999 | 3 | 2011-07-29 至 2011-07-27 |
| 11,999 | 3 | 1995-02-23 至 1995-02-21 |
| 13,525 | 2 | 1990-12-20 至 1990-12-19 |
| 13,527 | 0 | 空页 |

总计取到 14 条样本，跨越现有 6,000、12,000 分页位置，且末条日期的上一交易日为 `NULL`。首尾跨度按自然日计算为 13,527 天，与末尾偏移吻合。正式发布前仍要对候选文件检查连续性与重复键。另用相同四列发送一次无日期请求，参数为 `exchange=SSE, offset=0, limit=6000`。实际返回 **6,000 条**，按日期倒序从 **2027-12-31** 到 **2011-07-29**，6,000 个日期互异且逐日连续，所有记录的交易所和开休市标记符合合同，页内相邻记录的上一交易日一致。该次响应体为 192,190 字节，请求和读取共 378 毫秒。单次耗时只作抽查记录。

1. **分页合同。** `trade_cal` 请求保留 `exchange=SSE` 和四个显式字段，省略 `start_date/end_date`。沿用共用分页方法，以 `limit=6000` 从 `offset=0` 取数，每个满页后按实际约定增加 6,000，遇合法短页结束。完整候选经 §2.3 校验后才发布。6,000 是已验证可用页长。该共用分页方法也供股票、指数、ETF 基础信息等资产使用。本期的日期顺序、覆盖校验与回归仅针对交易日历。正式日历 Job 的 3 条历史运行均成功，最近一次使用带日期请求。本次无日期样本也表明偏移正常推进。重复返回同一个完整页属于异常反例，这些样本无法估计其发生率。
2. **生成 Raw 候选。** 正式取数以源实际发布范围为准，程序不根据本地年份裁剪 `start_date/end_date`。以实测的有效 `limit` 分页，每页字段和交易所一致。已实测源按日期倒序及偏移分页。候选按日期键检查连续性和重复，排序只用于核验和读取。请求失败、缺列、空候选和重复日期导致取数或校验失败。用一次聚合核对 `distinct_date_count == (last_date - first_date).days + 1`，同时确认无 NULL 主键及非法开市标记。
3. **与现有文件对账。** Raw 候选必须包含原日历的日期范围及日期键。记录开休市或上一交易日的变化，用源记录核对不能解释的差异。检查历史事实的业务抽样，并抽检跨年、开市、休市的 `pretrade_date`。源真实修订可随更新写入，运行前核对本次切换要求的日期及状态，发现所需范围尚未由源发布时，记录缺口并暂停本次正式补数与读取切换。日常候选发布比较已有正式文件的范围及键，2027-12-31 用于这次迁移验收。
4. **生成 Silver 候选。** 调用 [`silver_trade_calendar_select`](../../../../lake_console/orchestrator/src/orchestrator/defs/duckdb_sql.py#L168) 将 `cal_date` 转为 `trade_date: DATE`，将 `is_open` 的 0/1 转为 `BOOLEAN`，将 `pretrade_date` 转为可空 `DATE`。Raw 保留原 `YYYYMMDD` 字符串和整型开市标记。Silver 候选与 Raw 规范化后以日期键双向比对，行数相等且字段逐日对应。首条历史记录允许源合同中的空上一交易日。非法日期或无效开市值报错，不填默认值。

### 2.3 发布、失败恢复与执行预算

- 正式 DG 已配置 `QueuedRunCoordinator`，实际配置 `concurrency.runs.max_concurrent_runs=1`。日历更新沿用同一串行队列。启动时确认正式 Lake 和 staging 挂载、可写、同文件系统并有可用空间。通过正式 Dagster UI 触发，也通过同一实例读回运行和检查结果。正式执行时另按已批准的执行窗口操作。
- staging 位于 `/Volumes/datasource/data_lake_staging`。候选完整通过后分别用 `os.replace` 提升为正式文件。每次提升后记录 run ID、层、路径、行数、范围、摘要及状态到该次运行的物化信息与 staging 的检查点。检查点写不完整时，用正式文件读回、摘要和 Dagster 检查交叉确认完成位置。正式路径分别为 `raw/tushare/trade_calendar/full/part-000.parquet` 和 `silver/calendar/trade_calendar/full/part-000.parquet`，根目录为 `/Volumes/datasource/data_lake`。
- Raw 未发布就按源错误处理，已经发布的正式文件保留。Raw 已更新且通过检查、Silver 未完成时，以该 Raw 为输入，在现有 Job 的失败重执行路径补齐 Silver 及其检查。重执行前复核 Raw 未被改写，读回摘要与记录一致。若失败发生在文件替换后、记录完成前，先对照候选、正式文件及检查结果再决定重做的步骤。两层检查和读回复核全部通过才允许本地日历切换。
- 验收留存实际文件构成和两层起止日期、行数、重复键数、缺日期数、差异数、开休市与上一交易日样本、Job run ID 和三个 check 结果。覆盖至少达到 2027-12-31，该日期只用于本次切换下限。下游日期范围照原产品条件查询。

| 成本项 | 核算与控制 |
| --- | --- |
| 请求与页数 | 一个交易所，两个资产均是一个全量文件，没有按日期 fan-out。源确认有效页长为 `L`，从偏移 0 取 `N` 行、以首个合法短页结束时，请求数为 `N // L + 1`，包括整页情况下的末尾空页。按当前抽查的首尾、偏移和实测页长，预计更新请求偏移 0、6,000、12,000 三页，页行数分别为 6,000、6,000、1,527。核验实际读取了首个整页和各边界小样本；后两页的实际行数及正式文件总行数在 Job 执行时复核。把边界探测和异常请求次数另记 |
| 读写量 | 当前已知正式 Silver 为 89,590 字节、13,162 行。一次正常 Job 生成一个 Raw 候选、一个 Silver 候选，最多各提升一次。按来源页、候选、检查及最后读回分别记录文件字节、投影行数、SQL 次数；检查用聚合与小样本，禁止逐日打开文件或逐日请求 |
| 中断恢复 | 源尚未完成的失败重执行最多重做当前一次完整 Raw 取数及后续步骤。Raw 已核实的 Silver 恢复不发 Tushare 请求，只增加一次 Raw 读取、Silver 生成与两层对账。实测记录正常和断点恢复的请求数、DuckDB 用时、staging 峰值、检查和读回用时 |
| 正式运行停止条件 | 页长、覆盖、预计页数、文件空间与耗时先用有界探测和隔离验证确定。正式开始前以实测补齐预算记录，当前文档不把估算作为运行耗时承诺。发现未解释的截断、缺口、正式目标冲突或空间/耗时超出核准预算时停止发布 |

### 2.4 阶段 1 验证记录

- **隔离回归。** 交易日历、相邻基础信息合同和 ETF 基础资产共 36 项测试、40 项子测试通过。用 13,527 条模拟数据执行现有 Job，确认请求偏移为 0、6,000、12,000，两个文件的日期覆盖为 1990-12-19 至 2027-12-31，三项检查通过。两次完整样本的 Raw 耗时 1,555–1,636 毫秒、Silver 耗时 23–24 毫秒，文件分别为 96,334 和 108,961 字节。耗时取自两个资产日志，包含本地文件处理，源请求使用替身。用 6 条样本在持久化的隔离 Dagster 实例验证两次失败重执行，Raw 替换后记录写入失败和 Silver 校验失败均可恢复，无额外源请求。当正式 Raw 的文件摘要不匹配时，隔离重执行拒绝覆盖 Silver。
- **独立复核与静态检查。** 复核确认最低覆盖校验仅作用于发布、开市标记先校验再转型、上一交易日逐日核对，两种重执行路径都有隔离证据。文档完整性检查和本阶段代码语法检查通过。共用取数文件仍有两个已有 Ruff 问题，扩大运行的两组资产治理测试仍有七个失败，均在 `995fa46c8` 上复现。
- **正式执行。** 2026-11-19 按批准窗口重新加载 `orchestrator`，核对新版 Job 定义后仅提交一次 `calendar_update_job`。Run ID 为 [`a818321d-5d93-481d-97fc-695a43964246`](http://127.0.0.1:3000/runs/a818321d-5d93-481d-97fc-695a43964246)，运行于当日 21:40:42–21:40:53（上海时间），状态 `SUCCESS`，耗时约 11.54 秒。Raw 请求参数仅含交易所 SSE 和共用分页参数，物化记录为每页上限 6,000 条、共 3 页、13,527 条。最低验收日期为 `2027-12-31`。Raw 和 Silver 资产日志耗时分别为 1,583 和 31 毫秒，包含各自的取数或生成、校验和发布。
- **正式检查与读回。** Raw 合同、Silver 唯一键、Silver 必填列三项检查全部通过。Raw 为 88,084 字节，Silver 为 92,061 字节。两层各 13,527 条，覆盖 **1990-12-19 至 2027-12-31**。原有 13,162 个自然日全部保留，新增 2027 年 365 个自然日。运行记录显示已发布历史的开休市和上一交易日均无变化。对两个正式 Parquet 独立读回，重复日期、缺失日期、非法记录、上一交易日错误均为 0，标准化后双向逐行比对差异为 0，两层文件摘要均与发布记录和物化记录吻合。样本中 2027-01-01 休市、2027-01-04 开市，上一交易日均为 2026-12-31。两层读回共约 251 毫秒。

阶段 1 正式验收通过。阶段 2 按 §3、§4 推进本地后端读取迁移。

## 3. 本地证券和日历的读取合同

### 3.1 配置和注入

沿用 [`Settings`](../../../../src/foundation/config/settings.py#L17)、现行 [内核运行时选择](../../../../src/app/runtime/technical_indicators/composition.py#L33) 和 [本地构建配置](../../../../scripts/local-build-and-run.sh)。`APP_ENV=dev/local` 选择 DG，`prod/production` 选择 PG。`GOLDENSHARE_LAKE_ROOT` 从同一套设置读取，本地正式配置预期为 `/Volumes/datasource/data_lake`。本地缺配置、文件读失败或合同错误直接走取数错误。通用交易日历接口继续接受调用方的 `exchange`。现行本地默认 `DEFAULT_EXCHANGE=SSE`，两个来源经核验均只含 SSE，因此接口收到一个合法但无记录的交易所时照常返回空列表，不自动映射成 SSE。沪深 A 股共用 SSE 日历的现有业务调用继续保留显式 SSE。

- 在 App 组合根按显式部署模式一次构造本地的 `ReferenceData`。Web 在 [`src/app/web/lifespan.py`](../../../../src/app/web/lifespan.py) 组装。已有路由会话由 Web 依赖把已构造的读取对象放进本次会话的 `Session.info`，查询在涉及这两个来源时显式取用它。日 K 后端自建会话由其已有的 App 组装位置传递同一对象。Prod 调用保留原 PG 查询。阶段 2 沿用本地 Web 已配置的 `GOLDENSHARE_LAKE_ROOT`，范围涵盖本地 Web 内实际执行的读请求。独立 CLI、调度器和独立巡检进程列在 §4 仅用于识别调用边界。Foundation 只定义读取合同和适配器，依赖方向按 [子系统架构基线](../../../../docs/architecture/subsystem-boundary-plan.md#3-目标依赖方向)。
- 新建角色专一的 `src/foundation/clients/reference_data.py` 保存独立行合同和读取接口，`local_lake/reference_data_reader.py` 实现两个 DG 文件读取。PG 直读方法复用现有 DAO 的查询条件与会话。调用方显式接收读取对象，不通过模块全局变量、导入时打开文件、线程本地变量或 ORM SQL 拦截做换源。只读对象可被多个请求复用，连接、候选行及异常属于该次请求或任务。
- 每个请求每类文件在一个联表读步骤批量读一次。查询投影只含调用所需的列，筛选在文件扫描中完成。同一查询把所用行带到后续组装或传入同一 SQL 查询，避免每个证券重新打开文件。独立请求重新读正式文件，能看见已原子更新的数据。

### 3.2 对象与方法

```python
@dataclass(frozen=True, slots=True)
class TradeCalendarRow:
    exchange: str
    trade_date: date
    is_open: bool
    pretrade_date: date | None

@dataclass(frozen=True, slots=True)
class SecurityReferenceRow:
    # ts_code 保留后缀和前导零。主键及名称为必有字段。
    ts_code: str
    name: str
    symbol: str | None
    area: str | None
    industry: str | None
    fullname: str | None
    enname: str | None
    cnspell: str | None
    market: str | None
    exchange: str | None
    curr_type: str | None
    list_status: str | None
    list_date: date | None
    delist_date: date | None
    is_hs: str | None
    act_name: str | None
    act_ent_type: str | None
    security_type: str
    source: str

class TradeCalendarReader(Protocol):
    # 最近开市日用 <= bound 或 < bound，由调用方显式指定。
    def get(self, *, exchange: str, day: date) -> TradeCalendarRow | None: ...
    def range_rows(self, *, exchange: str, start: date, end: date,
                   open_only: bool = False, timeout_seconds: float | None = None
                   ) -> tuple[TradeCalendarRow, ...]: ...
    def recent_open_rows(self, *, exchange: str, bound: date, limit: int,
                         include_bound: bool = True, start: date | None = None
                         ) -> tuple[TradeCalendarRow, ...]: ...
    def context_rows(self, *, exchange: str, end: date, recent_open_days: int,
                     start: date | None = None, timeout_seconds: float | None = None
                     ) -> tuple[TradeCalendarRow, ...]: ...

class SecurityReferenceReader(Protocol):
    def get(self, *, ts_code: str, timeout_seconds: float | None = None
            ) -> SecurityReferenceRow | None: ...
    def read_by_codes(self, *, ts_codes: Sequence[str], timeout_seconds: float | None = None
                      ) -> Mapping[str, SecurityReferenceRow]: ...
    # 按本次 SQL 关联或展示使用的列投影。columns 含 ts_code。
    def project_by_codes(self, *, ts_codes: Sequence[str], columns: Sequence[str]
                         ) -> tuple[tuple, ...]: ...
    # 各入口分别保留既有过滤规则、排名与上限。
    def search_a_shares(self, *, keyword: str, escaped_prefix: str, limit: int,
                        exchanges: Sequence[str]) -> tuple[tuple[str, str], ...]: ...
    def leaderboard_codes(self, *, trade_date: date) -> tuple[str, ...]: ...
    def suggest_equities(self, *, keyword: str, limit: int) -> tuple[tuple[str, str], ...]: ...
    def planning_equities(self) -> tuple[SecurityPlanningRow, ...]: ...

@dataclass(frozen=True, slots=True)
class ReferenceData:
    calendar: TradeCalendarReader
    security: SecurityReferenceReader

# App 组装本地 Web 请求使用的读取对象。
def build_reference_data(settings: Settings) -> ReferenceData | None: ...
```

- PG 方法使用调用方已有的会话和事务。DG 的适配器直接读文件，关系查询在 App 注入来源后仍使用原有 PostgreSQL 会话。日 K 和交易助手沿用各自的请求时限，读取日期范围可接收已有剩余秒数。给联表提供的内部投影固定白名单，日期、代码、筛选值和上限绑定传入。测试通过临时 Lake 根及指定的会话注入两类来源。
- **日历来源。** 使用 Silver 正式文件。日期范围 `start/end` 两端包含，`range_rows()` 按日期升序，`recent_open_rows()` 先倒序限量再按日期升序返回。若函数只需最后一条开市日，从这个读取结果取最后一条即可。`context_rows()` 应含上界当天记录（即便休市）和指定数量的近期交易日，保留现有 [`IndexDailyLakeReader.calendar_rows`](../../../../src/foundation/clients/local_lake/index_daily_reader.py#L33) 的语义；由新的日历读取入口统一实现，原方法作为已有指数消费者的委托入口。
- **证券来源。** 使用 `raw/tushare/stock_basic/full/part-000.parquet`。按 `ts_code`，保留所有上市状态。日期按显式 `YYYYMMDD -> DATE` 转换，合法空值为 `None)。`security_type=\"EQUITY\"`、`source=\"tushare\"` 是这个数据集的固定业务事实，来自 DG 的资产来源和 Prod 的 [证券合同](../../../../src/foundation/models/core_serving/security_serving.py#L12)。其他名称、状态、交易所、币种等字段逐列保持原值。Raw 无 PG 写入时间，现行调用方不使用该值作为业务事实。
- [`get_active_equities`](../../../../src/foundation/dao/security_dao.py#L19) 实际接收 `L/P/D`，映射为 `planning_equities()` 保留条件。股票搜索和自选准入各自保留 `L + CNY + SSE/SZSE/BSE + EQUITY`，股票详情查找没有在市限制。板块历史池和成分股查询保留各自的上市与退市日期谓词，不能复用当前在市搜索结果。
- **错误和正常空值。** `get` 查无主键返回 `None`，多行接口返回空集合。既有找不到标的的 404、候选为空、日期超出有效日历等行为由原调用入口处理。文件缺失、不可读、缺字段、非法主键或日期转换报错都属于取数失败。异常包含数据集名与必要的代码/日期，HTTP 错误框架沿用当前入口。计划、审计与规则判定因源故障失败时走已有失败记录和重试入口。

### 3.3 与 PostgreSQL 事实关联

1. **只展示引用字段。** 在筛选、排序、分页不依赖证券字段时，先执行原有有界 PostgreSQL 查询，再按该批证券代码一次读 DG。比如自选 `WatchlistItemQuery.page` 的排序由分组置顶、行情字段及成员 ID 决定，证券表只供名称、行业和上市状态。保留原来的 `limit + 1`、游标以及左关联未匹配后的空值。过滤和组归属在原事务中完成，DTO 在最终组装前读齐。
2. **证券字段参与筛选、排序、聚合或内连接。** 先拿请求日期、板块或池范围内的候选键，向 DG 一次投影必要字段。使用绑定的有类型 JSONB 参数和 PostgreSQL `jsonb_to_recordset` 構造该查询的只读关系，例如 `ts_code text, name text, list_date date, delist_date date`，原关系别名仍沿用。把临时关系放入同一条 SQL 的 `JOIN`，保留原有连接类型、条件、排序及 tie-break、聚合和分页顺序。同一个现有业务事务承担权限和其余数据库事实读取。零行用空关系表达。SQLAlchemy 的有类型表值函数写法可参考现有 [计算台账查询](../../../../src/biz/queries/wealth/market/trading_assistant/calculation_ledger.py#L96)。代码不得将绑定值拼接成 SQL，也不创建任何临时数据库表。Prod 的语句仍引用原 ORM 表。若候选集本身是现有全市场逻辑中的必要对象池，只投影有据的谓词和字段，不为普通请求常驻完整主数据。
3. **日历关联。** 用 `range_rows()` 或 `recent_open_rows()` 得到该次必需的开休市或日期序列。原 SQL 仅以开市日过滤时绑定日期数组；若读休市标记、上一日或依赖左关联空值则使用同一有类型只读关系，保持 `exchange, trade_date, is_open, pretrade_date`。原生 SQL 的日历关系由调用方显式传入，保留原本的价量、停牌及权重等 PG 事实表。
4. **范围和计算负担。** 读路径每次只涉及证券 Raw 或日历 Silver 各一个文件，常规证券详情按一个代码，搜索在投影、排序和过滤后应用原上限。关联读的上界为候选去重键数（K）和已验证文件行数（N）的较小者，日期关联上界则为现有窗口天数及文件覆盖的较小者。按代表性调用记录 PG 语句数、候选行/投影字段数、文件读次数、字节与耗时；重复请求及失败重试分别记录。以现有入口的分页、超时、对象池和日频计算预算约束，禁止通过放宽这些阈值掩盖换源开销。

## 4. 本地调用方迁移清单

清单来自 CodeGraph 的 `codegraph_explore` 对首屏、证券/日历查询和 DG Job 的调用链跟踪，以及仓库中对 ORM 别名、DAO 访问及原生 SQL 的核对。按 Web 实际执行路径判断阶段 2 范围。相同服务由独立进程调用时，由该进程原有接线决定读取方式。按直接读取、筛选关联与分页、已有日 K 时限、运维业务参考读取验证。

| 当前代码入口 | 本地改造与验收 |
| --- | --- |
| [`QuoteQueryService`](../../../../src/biz/queries/quote_query_service.py) 与 [`biz/api/market.py`](../../../../src/biz/api/market.py) | 股票身份用 `security.get`，保留股票、指数、ETF 的解析顺序和各自来源。交易日历用 `range_rows` 映射原 `trade_date/is_open/pretrade_date`，原日期校验及 HTTP 字段保持 |
| [`MarketPageContextQuery`](../../../../src/biz/queries/wealth/market/context/market_page_context_query.py)、[指数日 K](../../../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py)、[`IndexDetailQuery`](../../../../src/biz/queries/wealth/market/index_detail/index_detail_query.py) | 本地 `resolve_context` 路径复用 `resolve_local_context` 的已实现日期规则及新的 `context_rows`。`resolve_sse_kline_context/load_sse_preceding_dates` 按原有开市日窗口处理；已直接使用 DG 的指数路径合用日历读取。指数基本信息沿用既有数据集。指数权重名单若查询股票名称，从 DG 补齐原证券字段与回退 |
| [股票详情身份与盘口查询](../../../../src/biz/queries/wealth/market/stock_detail/stock_detail_query_service.py)、[股票新闻查询](../../../../src/biz/queries/wealth/market/stock_detail/news_query.py)、[日线九转](../../../../src/biz/queries/wealth/market/stock_nine_turn/stock_nine_turn_query_service.py)、[分钟九转](../../../../src/biz/queries/wealth/market/stock_minute_nine_turn/stock_minute_nine_turn_query_service.py) | 股票身份一律按代码读 DG，日历通过公共查询。新闻事件表、已生产的九转结果表、分钟取数与算法维持现有来源及规则。仅首屏盘口按 §5 单独改造 |
| [`StockSearchQuery`](../../../../src/biz/queries/wealth/market/stock_search/stock_search_query.py)、[`WatchlistItemQuery`](../../../../src/biz/queries/wealth/market/watchlist/watchlist_item_query.py) | 股票搜索的股票代码/简称拼音匹配、SQL 通配符转义和名次依原查询。普通股票搜索、数据中心搜索和自选搜索共用该结果。自选加股资格按代码批查原准入条件，列表按 §3.3 第 1 项读取名称、行业和状态。验收同名、缺失、排序同值、置顶、游标第二页和其他用户的分组 |
| [交易助手业务读](../../../../src/biz/services/wealth/market/trading_assistant/market_facts.py)、[`suspension_facts.py`](../../../../src/biz/services/wealth/market/trading_assistant/suspension_facts.py)、[`validation_basis.py`](../../../../src/biz/services/wealth/market/trading_assistant/validation_basis.py)、[持仓](../../../../src/biz/queries/wealth/market/trading_assistant/positions.py)、[记录](../../../../src/biz/queries/wealth/market/trading_assistant/record_scope.py) | 证券资格和 SSE 日历连续性走 DG，复权因子、停牌记录、持仓及检查点按现有 PG 查询。对同一验证批次，构造原字段名、顺序和类型供 `facts_digest`，保留批准规则依赖的摘要计算。按保存页中的确切日期重查日历，保持 `IS DISTINCT FROM` 等价的空值比较，缺日或变动仍触发已有的 `ValidationBasisChanged`。同一截止时限覆盖 DG 读取、数据库查询和对账 |
| [榜单股票池与排名](../../../../src/biz/queries/wealth/market/leaderboards/stock_pool_query.py)、[`equity_rankings_query.py`](../../../../src/biz/queries/wealth/market/leaderboards/equity_rankings_query.py)、[`dc_hot_rankings_query.py`](../../../../src/biz/queries/wealth/market/leaderboards/dc_hot_rankings_query.py)、[涨停结构](../../../../src/biz/queries/wealth/market/limit_up/limit_up_structure_query.py) | 从 DG 读取原池过滤字段和名称。原内连接、排名有效集合、数量聚合和排序在最终截取前完成。没有身份的股票是否参与由各原连接决定。验收一个候选因生命周期出池时，榜单能按原先顺序补上下一项 |
| [板块概览成分](../../../../src/biz/queries/wealth/market/sector_overview/sector_member_query.py)、[历史有效股票池](../../../../src/biz/services/wealth/market/sector_overview/effective_a_stock_pool_query.py)、[板块概览来源查询](../../../../src/biz/services/wealth/market/sector_overview/sector_heat_source_query.py) | 分别保留历史池及股票状态筛选，原来用 `list_date <= 日期 < delist_date` 的地方保持退市日排除。涉及跨多日池计算，用该范围的同一证券关系参与原日期联表，不按当前上市状态裁掉历史记录 |
| [板块分析](../../../../src/biz/queries/wealth/market/sector_analysis/sector_analysis_meta_query.py)、[成分股明细](../../../../src/biz/queries/wealth/market/sector_analysis/sector_member_detail_query.py)、[板块运维读取](../../../../src/biz/services/wealth/market/sector_analysis/daily_facts/source_query.py) | 日历支撑所需日期和原就绪规则，证券数据支撑股票名称/字段，板块来源、发布状态和已有缓存键保持。组内逐项核对 `sector_analysis_fact_reader.py`、`sector_daily_insight_query.py`、`sector_member_breadth_query.py`、`sector_momentum_query.py`、`history_input_auditor.py`、`replay_planner.py`、`sector_heat_replay_planner.py` 的排序、范围、缺日和截止日期 |
| [市场状态基线](../../../../src/biz/queries/wealth/market/summary/summary_state_query.py)、[指数成交额](../../../../src/biz/queries/wealth/market/index_turnover_insight/index_turnover_insight_calendar_query.py)、[指数研究日历](../../../../src/biz/queries/wealth/market/index_detail_xxm/source.py) | 各业务保留自己的取最新、历史区间、均线计数和就绪规则，只换日历数据。核对 `breadth`、`leaderboards`、`limit_up`、`major_indices`、`money_flow`、`sector_overview`、`streak_ladder`、`style`、`summary`、`turnover`、`turnover_common`、`turnover_insight` 下各状态、历史和统计查询，以及 `index_detail_daily_wave/query.py`、`index_detail_xxm/forecast_query_service.py`、市场情绪计算及验证查询。保留与 PG 中其他事实的一次性聚合和左右连接 |
| [Ops 新鲜度](../../../../src/ops/queries/freshness_query_service.py)、[数据表卡片](../../../../src/ops/queries/biz_table_card_query_service.py)、[研判中心](../../../../src/ops/queries/review_center_query_service.py)、[日历完整性任务](../../../../src/ops/services/date_completeness_run_service.py) | “业务上哪天应开市”“哪些证券应纳入”的判断改读 DG。核对 `date_completeness_audit_service.py`、`date_completeness_schedule_service.py`、`task_run_service.py`、`task_run_dispatcher.py`、`news_stock_linking_service.py`、`sector_analysis_daily_upstream_readiness_service.py`、`sector_heat_upstream_readiness_service.py`。PG 任务履历、表物理计数和被审计表中的实际记录依旧查询被观测对象，否则会把 DG 的覆盖当成 PG 的物理观测 |
| [Ops 探针入口例](../../../../src/ops/services/index_mins_remote_probe_service.py)、[回补计划例](../../../../src/ops/services/etf_minute_history_alignment_plan_service.py) | 本地运行中用作 SSE 业务日期、股票列表的 `TradeCalendarDAO/SecurityDAO` 读取替为 DG。核对 `index_daily_*`、`index_period_serving_probe_service.py`、`idx_factor_pro_remote_probe_service.py`、`kpl_list_remote_probe_service.py`、`margin*_remote_probe_service.py`、`stk_mins_remote_probe_service.py` 和 `operations_probe_runtime_service.py` 的显示条件和合法空数据。远端探针的目标数据仍从原被探测对象读入 |
| [Foundation 计划器](../../../../src/foundation/ingestion/unit_planner.py)、[标准化入口](../../../../src/foundation/ingestion/executor.py)、[实时时钟](../../../../src/foundation/realtime/market_clock.py)、[CLI 共用日期](../../../../src/cli_parts/shared.py)、[CLI 维护入口](../../../../src/cli_parts/maintenance_handlers.py) | 本地取执行窗口、股票池和上市日时明确传入共用读对象，同查 `index_month_calendar.py`、`stock_period_adj_inputs.py`、`stock_weekly_adj_planning.py`、`stock_weekly_adj_bootstrap.py`。保留计划 unit 数量、截日、缺自然日诊断、数据写入边界和命令参数。DAO factory 中的写 DAO 与读取注入分开，禁止因本地选择 DG 而改写现有 PG 发布逻辑 |

**数据库事实与业务参考的边界。** `DatasetDefinition`、ORM 目标表模型、PG 写入合同及写入前的“目标行确实存在”检查仍指向其实际存储对象。例如 [股票主数据写入器](../../../../src/foundation/ingestion/writer.py#L1985) 的 `get_existing_ts_codes` 决定 PG 写入行为，改成 DG 会产生错误的新增/更新分类。QTF [显式 Prod 行情来源](../../../../qtf/adapters/prod/sector_source_adapter.py) 与算子库 PG 数据源仍使用指定的 Prod 连接。上述引用不能当成应用本地读取达标的例外，只有明确的写入或被观测对象才保留原目标。

### 各模块的其余文件

以下文件与上表一起作为迁移实施清单。先核对被调用方法的入参与返回值，保留各自日期范围、SQL 结果顺序及 DTO。

- `src/biz/queries/wealth/market/` 下的日历直接读包括 `breadth/breadth_history_query.py`、`breadth/breadth_state_query.py`、`leaderboards/leaderboards_state_query.py`、`limit_up/limit_up_history_query.py`、`limit_up/limit_up_state_query.py`、`major_indices/major_indices_state_query.py`、`money_flow/money_flow_query.py`、`money_flow/money_flow_state_query.py`、`sector_overview/sector_overview_state_query.py`、`streak_ladder/streak_ladder_state_query.py`、`style/style_query.py`、`style/style_state_query.py`、`turnover/turnover_query.py`、`turnover/turnover_state_query.py`、`turnover_common/turnover_daily_average_query.py`、`turnover_insight/turnover_insight_query.py`。证券点读同时迁移 `stock_detail/stock_detail_query.py`。
- `src/biz/services/` 的 `market_mood_calculator.py` 在行情联表中使用上市日，按 §3.3 第 2 项替换，保留原池筛选。`market_mood_walkforward_validation_service.py` 的历史开市序列改走日历读取对象。
- `src/ops/services/` 的指数读取还包括 `index_daily_completeness_reconciliation_service.py`、`index_daily_completeness_repair_service.py`、`index_daily_remote_probe_service.py`、`index_daily_source_serviceability_service.py`，融资融券读取包括 `margin_remote_probe_service.py` 和 `margin_detail_remote_probe_service.py`。同一运行的交易日规划、应有数据判断和补数目标选择使用同一来源。
- `src/foundation/dao/` 的 `factory.py`、`trade_calendar_dao.py`、`security_dao.py` 保留现有 PG 读写类，新增读取对象的 PG 实现可委托其有界查询。数据库读写的模型、定义与发布仍指向现物理对象，包括 `datasets/definitions/market_equity.py`、`datasets/definitions/reference_master.py`、`models/all_models.py`、`models/core/trade_calendar.py` 和 `models/core_serving/trade_calendar.py`。

### 提交时的核对方式

1. 沿每个运行入口追到真正执行的 SQL，逐项登记依赖注入、源、字段、日期窗口、连接方式、返回秩序和失败处理。扫描同时覆盖 `TradeCalendar` 的 `core`/ `core_serving` 导入别名、`Security` 的别名、DAO factory 以及原生 SQL。
2. 运行时测试禁止本地业务 SQL 触及两张旧表，其他 PG 表和只读会话正常。对直接读、整个日期窗口、两种关联、后台计划和时钟至少各有一个正例，并逐入口加上原行为用例。表级监控查询、写路径、显式 Prod 读分别标注执行目的，由对应测试证明仍读取真实目标。
3. 证券来源切换前执行下述回归。其余分组的计数一致只用于定位差异，不能作为字段全量等价的证据。需要验证的既有搜索、历史详情和关联行为继续按本节与 §6 的样本执行。

### 证券主数据源差异的只读核验

2026-11-19 使用 Web 已配置的 Prod PostgreSQL 读取身份，在只读事务核对 `core_serving.security_serving`，并读正式 DG 的 `raw/tushare/stock_basic/full/part-000.parquet`。按交易所、上市状态、币种和代码前三位分组计数。Prod 的 5,926 条均属于 `EQUITY / tushare`。两端分组只在上交所退市人民币证券有差异，Prod 151 条、DG 149 条。该组按 `ts_code` 定点比较，149 个共同代码的名称、交易所、状态、币种、上市日、退市日和简称拼音均一致，DG 无独有代码。在市样本 `600519.SH`、`000001.SZ` 与退市样本 `920305.BJ` 的同组字段也一致。

| 仅 Prod 有记录 | 名称 | 上市日 | 退市日 |
| --- | --- | --- | --- |
| `T00018.SH` | 上港集箱(退) | 2000-07-19 | 2006-10-20 |
| `TS0018.SH` | 上港集箱(退) | 2000-07-19 | 2006-10-20 |

- 按两个旧代码查询，当前 Tushare `stock_basic` 的 SSE 退市查询均为空，DG 正式 Raw 的全状态点查和股票生命周期点查均为空。现行 Tushare 的 `600018.SH` 为「上港集团」，上市日为 2006-10-26。使用该代码替换旧代码会改变身份与生命周期，未经确认不得映射。
- 股票搜索和自选新增资格要求 `list_status=L`，这两条记录原本即不纳入。Prod 对这两个代码的自选成员、交易助手规则版本与账户初始持仓只读计数均为零。研判中心证券搜索未限定上市状态，本地全市场分钟行情计划的候选池也可含退市代码，所以这两个入口的候选集中会少这两条。 [股票搜索](../../../../src/biz/queries/wealth/market/stock_search/stock_search_query.py#L50) · [研判中心搜索](../../../../src/ops/queries/review_center_query_service.py#L480) · [分钟行情候选池](../../../../src/foundation/ingestion/unit_planner.py#L1893)
- 现有股票详情路由允许这两个路径，`/page-init` 按证券原代码直接查身份。两码在 Prod 的股票不复权日线和股票日线技术因子中，2000-07-19 至 2006-10-20 按代码计数均为零。现有主数据能返回身份，迁移后本地若只读 DG，则会按原未找到合同返回 HTTP 404（`404001`），Prod 保留现状。范围外行情和其他存量业务表未纳入上述定点查询。 [详情身份查询](../../../../src/biz/queries/wealth/market/stock_detail/stock_detail_query.py#L44) · [详情错误映射](../../../../src/biz/api/wealth/market/stock_detail.py#L54)
- **已确认。** 本地对这两个代码采用 DG 查无标的规则，给这两个代码增加本地 404 和 Prod 原行为的回归。

### 阶段 2 开发与独立审计

- 本地 Web 由 [应用启动](../../../../src/app/web/lifespan.py) 构造 DG 读取对象，经 [Web 会话依赖](../../../../src/app/dependencies/db.py) 或日 K、交易助手自己的会话入口传给查询。通用交易日历、股票详情与九转、证券搜索、自选、市场状态及日历窗口、指数和板块关联、交易助手、Web 运维查询与维护计划读取同一来源。独立调度、巡检和补数沿用各自入口。
- [DG 读取实现](../../../../src/foundation/clients/local_lake/reference_data_reader.py) 读取股票基础信息 Raw 文件及交易日历 Silver 文件。直接读取按代码或日期过滤，关联读取先确定候选再按所需列投影，用 [有类型的 JSONB 参数](../../../../src/foundation/clients/reference_data_relations.py) 保留原 SQL 的过滤、聚合、关联和截取顺序。自选列表先按原游标分页，再补该页证券名称、行业和上市状态。历史股票日线技术因子与盘口组装属于阶段 3。
- 新代码只读回查正式 DG 的五个股票代码和跨年五个自然日。平安银行的证券代码保留前导零，贵州茅台为上市状态，武钢股份的退市日期为 2017-02-14。两个已确认的旧证券代码仍查无记录。SSE 在 2027-01-01 休市、2027-01-04 开市，后者的上一交易日为 2026-12-31。2027-12-31 有记录，SZSE 请求返回空。测试记录中的 416.7 毫秒是冷启动后的第一笔五代码读取，8.4 毫秒是随后五日范围读取。样本计时用于说明测量范围。
- 独立审计发现三处行为差异并各补回归。损坏的日历主键要报读失败。交易助手的 DG 文件读取异常返回既有查询失败码。股票日 K 的两次 DG 读取沿用已有工作时限，超时退出后走原错误分类和资源清理。[隔离测试](../../../../tests/test_local_web_reference_data.py) 验证直接 API、目录缺失、无效日期、已存在的时限和错误码，以及缺少两张旧表时实际 PostgreSQL 关联的空值、日期类型和先筛选后排名。
- 467 项定向回归通过。复审加入空交易所反例后，8 项阶段 2 专用用例通过。独立复审确认正常空结果、合法查询区间和 Prod 路径保持原合同。文档及改动语法检查通过。交易助手执行资源中的 Ruff `F821` 在改造前的 `91f143a76` 同样存在。

## 5. 股票详情首屏

### 5.1 现有 URL 和回包结构

保留两条 GET 及现有请求参数。App 在 [`src/app/api/v1/router.py`](../../../../src/app/api/v1/router.py#L107) 装配对应环境的 [股票详情路由](../../../../src/biz/api/wealth/market/stock_detail.py)。参照指数路由，由股票详情提供 `build_router(..., local: bool)` 注册两条路径及对应 `response_model`。选用与 §3 相同的部署模式。环境在组合根确定，仅注册一组路由，Prod 的 OpenAPI 与现有两个响应模型保持一致。本地 `/kline` 的 OpenAPI 使用 `LocalStockDetailFirstKlineResponseDto | StockDetailKlineResponseDto`。现有 ASGI 响应由后端选择具体 DTO 后序列化，首屏空结果保留 `quote: null`，普通请求的回包省略该字段。认证依赖及参数校验沿用。

```python
class LocalStockDetailPageInitResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 与现行 page-init 公用字段使用同一类型，原字段名保留。
    pageContext: MarketPageContextDto
    stock: StockDetailStockIdentityDto
    chartDefaults: StockChartDefaultsDto
    capabilities: StockDetailCapabilitiesDto
    debugInfo: StockDetailDebugInfoDto | None = None

class LocalStockDetailFirstKlineResponseDto(StockDetailKlineResponseDto):
    # 首屏始终输出键名。EMPTY 时显式返回 null。
    quote: StockQuoteSnapshotDto | None

def is_stock_detail_first_page(request: StockDailyKlineRequest) -> bool:
    # 只在本地调用。页面日期与日 K 截止日相同，且未指定区间起点。
    return (
        request.trade_date is not None
        and request.end_date == request.trade_date
        and request.start_date is None
    )
```

| 请求 | 本地 | Prod |
| --- | --- | --- |
| `/page-init?tsCode=…&tradeDate=…` | `LocalStockDetailPageInitResponseDto`。省略可选请求日期沿用 §5.2。不返回 `quote`、`dataStatus` | `StockDetailPageInitResponseDto`，继续提供 `quote` 和 `dataStatus` |
| `/kline?tsCode=…&tradeDate=D&endDate=D&period=day&adjustment=forward&limit=500` | 识别为首屏。回 `LocalStockDetailFirstKlineResponseDto` | 原 `StockDetailKlineResponseDto`，按现有 `endDate` 优先语义读取 |
| 其他 `/kline` 请求，包括仅传 `endDate`、两日期不同或显式指定 `startDate` | 原 `StockDetailKlineResponseDto`，沿用现有查询区间和状态，回包省略 `quote` | 原 `StockDetailKlineResponseDto` |

**2026-11-20 确认。** 前端先请求 `/page-init`，可从页面 URL 向它传可选的 `tradeDate`。后端确定页面日期后，在 `pageContext.tradeDate` 返回 D。前端请求本地首屏 `/kline` 时，从这个回包取 D 同时填写现有的两个参数，`tradeDate` 表示整页的日期，`endDate` 表示这批日 K 的截止日，包含当天。两日期相等且省略 `startDate` 时，本地返回首屏结构。手动打开历史日期同样以当次 `/page-init` 返回的 D 判定。有效截止日仍以 `endDate` 优先。

共用前端通过 `/page-init` 回包是否有 `quote` 键来区分本地新合同和 Prod 合同。Prod 即使回 `quote: null`，也有该键，前端继续只传原有日 K 日期参数。两种环境的后续日期请求都以各自 `/page-init` 返回的 D 为准。本期股票页面每次打开只请求一批日 K。股票日 K 的交互翻页留到 §5.4。

### 5.2 日期解析与后端接线

- 在 [`StockDetailQueryService`](../../../../src/biz/queries/wealth/market/stock_detail/stock_detail_query_service.py#L51) 抽取共用身份和能力组装。构造时接收 `ReferenceData`。新增 `build_local_page_init(ts_code, trade_date, debug)`，只读 DG 证券和日历，返回本地 DTO。旧 `build_page_init` 在 Prod 维持旧股票日线技术因子及每日指标的盘口行为。删除当前由本地 page-init 执行的旧股票日线技术因子查询和专供该路径的 `daily_lake/kernel_config` 传参。调试信息如实列出所读数据集。
- 本地 `MarketPageContextQuery.resolve_context` 使用 DG 的 `context_rows(exchange="SSE", end=显式日期 or 上海今天, recent_open_days=2)`，将 `TradeCalendarRow` 投影为既有 `resolve_local_context` 的 `(trade_date, is_open, pretrade_date)`，复用其日期推导。指定日直接作为锚点；默认且当日开市，20:00 前取上一开市日、20:00 起取当天。默认且休市或日历落后，取截至当天的最后开市日。文件有效但完全没有可用开市日才按既有规则取当天。显式休市日和显式超出覆盖的日期仍按其日期响应，保留生成时刻、时区、`isTradingDay` 和上一交易日语义。DG 无法读取时走源错误。
- [`StockDailyKlineAppBackend.work`](../../../../src/app/dependencies/stock_daily_technical_indicators.py#L178) 继续走一个现有 Admission/ExecutionControl 和工作线程。在同一个预算中使用 DG 证券、日历、正式日线及辅助数据准备目标窗口。确认本地准备链已无 PG 读取后，本地不创建 `open_stock_daily_read_session`，其只读事务和超时管理留给 Prod。准备入口的 `session` 参数对 DG 可传 `None`。放弃请求时仍通过原中断、归还名额和源连接清理路径。
- `prepare_kline_input` 的有效截止日仍是 `end_date or trade_date or 解析结果`，目标根数、排序、页边界、复权基准、预热与内核指令保持既有 [计算 LLD](../../../../docs/architecture/technical-indicator-operator-library-implementation-lld-v1.md)。有效日线目标为空就返回原空态，内核调用次数为零。有目标窗口才调用一次 `TechnicalIndicatorService.calculate`。内核有目标却缺数据、源 I/O 失败、结果日期不匹配、超时和取消各使用原错误及清理合同。数据缺失仍用原 HTTP 500 错误包络，保留「读取数据失败」及「数据缺失」。
- 在 [`StockDailyKlineService.assemble`](../../../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py#L76) 完成校验和组装后，本地首屏用 `bars[-1]` 生成 `quote`，使用同一日期组装原 `dataStatus`。内部保留具体 DTO，序列化仍保留原本的 null；首屏空态明示 `quote:null`，普通 K 线 DTO 不含该键。现有 Response ASGI 执行中沿用一次输出及取消路径。用实际本地和 Prod 来源名称修正 `debugInfo.sourceTables`。

```python
# 拟新增于 stock_detail_field_mapper.py，使用已经转换成接口单位的 bar。
def build_quote_from_kline_bar(bar: StockKlineBarDto) -> StockQuoteSnapshotDto:
    return StockQuoteSnapshotDto(
        tradeDate=bar.tradeDate,
        price=bar.close,
        change=bar.change,
        changePct=bar.changePct,
        direction=resolve_direction(bar.changePct),
        open=bar.open, high=bar.high, low=bar.low, close=bar.close,
        preClose=bar.preClose,
        turnoverRate=bar.turnoverRate, volumeRatio=bar.volumeRatio,
        vol=bar.vol, volDisplay=bar.volDisplay, amount=bar.amount,
    )
```

`open/high/low/close` 是算子输出的前复权价格，`preClose/change/changePct` 是业务层用正式不复权日线匹配的字段。换手率和量比来自同日 `raw/tushare/daily_basic`，保留 null，现有盘口显示 `--`。内核的成交量单位为股、成交额为元，现行日 K DTO 分别除以 100 和 1,000，盘口直接复用日 K DTO 的量、额及现有显示文本。这一步不做第二次换算。状态继续用 [`build_data_status`](../../../../src/biz/services/wealth/market/stock_detail/stock_detail_field_mapper.py#L49) 根据实际末根日期与请求截止日判断 `READY/DELAYED/EMPTY`。迟到的行情或末根日期都不写回首屏锚点。

### 5.3 前端日期传递与请求生命周期

| 位置 | 具体改法 |
| --- | --- |
| [`WealthRouter.tsx`](../../../src/app/routes/WealthRouter.tsx#L56) | 将 `location.search` 内的显式交易日和 debug 传入 `StockDetailPage`，作为页面加载的依赖。股票代码或显式日期改变，以及用户刷新页面时开始新的加载轮次。保留现有路由和 URL 参数 |
| [`StockDetailPage.tsx`](../../../src/pages/stock-detail/StockDetailPage.tsx#L60) | 用当前证券与 URL 日期请求 `/page-init`，成功即存 `pageInit` 和页面日期 D，再发日 K。本地发送 `tradeDate=D&endDate=D`，Prod 沿用仅传日期参数 `endDate=D` 的方式。新轮次清除旧锚点、盘口、图层和挂起请求。渲染只使用本次证券和显式日期的结果，响应落状态前同时核对当前轮次和 AbortSignal，避免同一证券的上一日期结果短暂显示或回写 |
| [API 类型](../../../src/features/stock-detail/api/stockDetailApiTypes.ts) 与 [`buildStockDetailViewModel`](../../../src/features/stock-detail/api/stockDetailViewModelAdapter.ts#L62) | `pageInit` 类型区分 Prod 有 `quote/dataStatus` 键与本地无这两个键的合同。`kline` 支持首屏可出现的 `quote`。用键存在检查选择来源，本地只使用首屏 K 线回包中的盘口和状态，Prod 继续使用旧初始化盘口。K 线空数组用当前空态。非空本地首屏缺少盘口属于接口结果不匹配，交给现有页面加载失败状态 |
| [`useMajorIndexTickers`](../../../src/features/major-indices/model/useMajorIndexTickers.ts) | 为 hook 增加调用级的 `enabled` 参数，既有调用默认启用，只有股票详情在拿到有效 `pageInit` 之前传 false。启动后向现有指数接口显式传 `tradeDate=D`，锚点切换时取消旧请求，其他页面的默认加载时机照旧 |
| [`StockInfoRail.tsx`](../../../src/features/stock-detail/sidebar/StockInfoRail.tsx)、[`StockDetailNewsPanel.tsx`](../../../src/features/stock-detail/news/StockDetailNewsPanel.tsx) | 由页面直接沿 props 传 `D`。新闻面板以 `tsCode+D` 为缓存和请求标识，激活时使用 `endAt=上海 D 次日 00:00:00+08:00`，含下界、排除该上界。换日期时取消旧请求并清缓存。客户端以日期加一天计算日历边界，结果不受浏览器所在时区影响；如 D=2026-11-15，传 `2026-11-16T00:00:00+08:00`。原详情新闻的默认回看、去重和 50 条面板上限维持 |
| 分钟 K 线和指标、九转、趋势通道 | 继续使用同一个 `D`。分钟缓存以证券、D、频率随加载轮次隔离，九转和趋势通道的 `endDate` 只从有效页上下文取。历史窗口或换周期不能改变首屏盘口。自选组和交易助手表单的非日期参数保持现行合同 |

具体日期和状态断言如下。若显式选休市日 2026-11-15，本地首屏日 K 的 `tradeDate` 和 `endDate` 都是 11-15，顶部指数、新闻窗口和图层也以 11-15 为边界。若首屏在 DG 查到的最新目标日 K 是 11-13，则 `quote.tradeDate=2026-11-13`，`dataStatus.expectedTradeDate=2026-11-15`、`observedTradeDate=2026-11-13`、`status=DELAYED`。同一轮重新请求日 K 或重试图层时沿用 D。用户主动刷新整个页面时，可以重新发 `/page-init` 并取新的默认日期。

### 5.4 本地股票日 K 向前翻页

本节保留原翻页实现与验收记录。2026-11-25 后续趋势通道接入决定见文首专项说明：新四轨与日 K 同批返回，下面旧独立趋势请求及分图层重试不是新接入的实现要求；已有盘口、日期、游标和历史记录保持。

本节记录 2026-11-20 的翻页实现。2026-11-22，本地股票日线九转已切换到 `/kline`。下文的独立九转请求用于记录当时的实现和验收。当前接口与验收见[九转专项 LLD](../../../../docs/architecture/technical-indicator-nine-turn-low-level-design-v1.md#10-本机切换后复验)。

本节是本地首屏切换后的独立开发设计。§5.1–5.3 记录首屏切换时的合同。先修复本地股票趋势通道取数并独立验收，再沿用[上证综指的拖动及加载方式](../../../src/features/index-detail/controller/useIndexDailyHistory.ts#L161)接入股票日 K 翻页和两个续页图层。

#### 第一步 修复本地股票趋势通道取数

[`StockDailyTrendChannelLakeReader.read`](https://github.com/chiuser/goldenshare/blob/75006c992c05239b79aeec6e93a126691b55c141/src/foundation/clients/local_lake/stock_daily_trend_channel_reader.py#L68) 原先按文件数提前截断，再按股票代码读取。现统一为与日 K 相同的计数口径。`limit` 表示指定股票的实际结果条数。沿用 `/trend-channel` 的 `tsCode`、`endDate` 和 `limit`，默认 300 条、最大 2,000 条，回包字段、日期解析、空态和错误包络沿用现行实现。阶段一的修改落在读取器、已有业务查询和测试，首屏仍使用现有请求。

1. 复用现有正式目录发现和路径校验，按 `endDate` 截止（含当天）排列日期，由近到远。[`StockDetailTrendChannelQueryService.read`](https://github.com/chiuser/goldenshare/blob/75006c992c05239b79aeec6e93a126691b55c141/src/biz/queries/wealth/market/stock_detail_trend_channel/stock_detail_trend_channel_query_service.py#L56) 将已取得的证券 `list_date` 传给 `StockDailyTrendChannelReadRequest` 作为内部读取下限，包含上市当天。上市日缺失时以最早正式分区为界。读到某一批时才校验该批对应的正式文件，按股票代码筛选 `gold/indicator/stock_daily_trend_channel` 的已产出结果。 [正式数据的上市日规则](../../../../lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-low-level-design-v1.md#L34)
2. 第一批文件数最多为 `limit`，后续每批只选至多等于剩余结果条数的文件。对该批复用现有字段投影、分区和日期一致性、单日唯一性、公式版本及数值校验。只有指定股票通过校验的记录计数。有效文件里无该股票时继续向前。已选中的正式文件缺失、格式非法或查询失败时沿用原错误路径。
3. 找满 `limit` 条或读完该股票能取的日期即停止。按交易日期升序组装响应，最新日期和 `meta.count` 取实际结果。少于 `limit` 时返回现有记录。市场有可读正式分区但该股票尚未上市或没有结果时返回原 `EMPTY`，截止日内无正式分区时沿用源未就绪。整个请求复用现有单连接，成功或失败均由路由关闭。原请求重试从同一截止日重新读取。

**读取预算与验收。** 有连续记录的普通请求仍只读一批。遇到停牌或无该股票记录时，后续按剩余条数逐批往前读，最多读上市日至截止日内可用的正式文件，上市日未知时使用数据集的现有覆盖。记录实际查询的文件数、结果条数和耗时，分别核对连续样本、停牌样本和历史不足时的开销。旧性能实测的每个文件都有该股票记录，只用来对照连续样本。第一步用[读取器测试](https://github.com/chiuser/goldenshare/blob/75006c992c05239b79aeec6e93a126691b55c141/tests/test_stock_daily_trend_channel_reader.py)和[真实路由测试](https://github.com/chiuser/goldenshare/blob/75006c992c05239b79aeec6e93a126691b55c141/tests/web/test_wealth_stock_trend_channel_api.py)验证停牌和其他股票的文件不占名额，覆盖查够即停、新上市历史不足、截止日在上市前、已有源错误和同参数重试。验收用有界 DG 样本核对返回记录和实际读取开销。开工前实测万科 A 截至 2016-07-05 请求 5 条只返回 2 条，2015-12-18 有更早结果。另有 `920309.BJ` 于 2026-11-17 上市，截至 11-19 只有 3 条，上市前有 3,128 个市场日期分区。修复后以这两个样本验证跨缺口和上市日停止，并核对回包字段及连接归还。 [原性能实测范围](../../../../lake_console/docs/design/dagster-stock-daily-trend-channel-m0-readonly-performance-validation-2026-09-01.md#7-本地-api-读取)

##### 第一步实施与审计

2026-11-20 · 本地趋势通道读数修复通过。验收将真实趋势通道路由装到隔离的本地应用，读取 DG 正式证券与趋势通道文件。测试请求的会话未绑定数据库。线上和正在运行的本地服务均未切换。

- **万科 A `000002.SZ`，截止 2016-07-05，取 5 条。** 旧读取只返回 07-04、07-05。修复后补回 2015-12-16、12-17、12-18，共 5 条，排序正确。同参数重试回包一致。两次均查询 135 个文件，读取器耗时分别为 272.0、175.7 毫秒。
- **新上市样本 `920309.BJ`，截止 2026-11-19，取 500 条。** 返回上市日至 11-19 的 3 条，只查询 3 个趋势文件。截止日改为 11-16 时返回 `EMPTY`，查询 0 个趋势文件。读取器耗时分别为 31.2、23.8 毫秒。
- **贵州茅台 `600519.SH`，截止 2026-11-19，取 500 条。** 查询 500 个文件，全部原始结果与旧版逐条一致。隔离应用中读取器耗时 538.8 毫秒，该数值为本次样本实测。实际接口只接收原有三个参数，回包字段照旧，五次请求均结束后关闭读取器。
- **回归。** 两条新增测试在旧代码上均复现少取，修复后通过。读取器、趋势通道路由、环境能力、股票详情及架构测试共 24 项通过。本次验收范围是第一步的本地后端读取。

#### 第二步 接入本地股票日 K 翻页

##### 请求和计算

现有 `/kline` 参数含义照旧，`tradeDate` 是首次 `/page-init` 确定的页面日期，`endDate` 是本批含当天的截止日。用页面日期 2026-11-18、首批最早日 K 为 2024-10-28、上一根实际日 K 为 2024-10-25 举例。

| 本地请求（省略 `startDate`） | `tradeDate` | `endDate` | `meta.nextEndDate` | 盘口 |
| --- | --- | --- | --- | --- |
| 首屏 | 2026-11-18 | 2026-11-18 | `2024-10-25`，无更早行情时为 `null` | 返回 `quote`，无目标日 K 时为 `null` |
| 向前翻页 | 2026-11-18 | 2024-10-25 | 本批最早日 K 之前的上一根实际行情日期，已到最早时为 `null` | 省略 `quote` |

- **确定下一批日期。** 在 [`StockDailyKlineAppBackend._load_page_fields`](../../../../src/app/dependencies/stock_daily_technical_indicators.py#L224) 复用 `daily_page_dates`。本地两日期显式给出、`endDate <= tradeDate` 且无 `startDate` 时，日期查询最多找 `limit + 1` 个匹配日。因为日期按升序返回，若多一根，以第一根日期作为 `nextEndDate`，仅用余下 `limit` 根读取本批业务字段和发起计算。找不到额外一根时，包括恰好 `limit` 根、短页和空页，返回 `null`。日期来自该股票的实际行情，跳过休市与无行情日期。仅有 `endDate`、有 `startDate` 或 `endDate > tradeDate` 等其他本地查询，以及 Prod，保留原取数和回包。
- **确定股票历史起点。** 本地分页将当前业务准备已读取的上市日用作日期查询的内部下限，包含上市当日。上市日缺失时以最早可用日线分区为界。这个日期仅限制目标日期和游标的查找，回包 `startDate`、预热方式和其他请求的读取规则沿用原口径。
- **回包。** `StockDailyKlineService.assemble` 接收日期读取阶段得到的下一批截止日。本地分页的元数据增加必有但允许为 `null` 的 `nextEndDate`，在本地首屏 DTO 与本地续页 DTO 中使用。`build_router` 只在本地 `/kline` 的响应声明纳入对应 DTO。原 `StockKlineMetaDto` 和 Prod 路由继续使用原字段。首屏仍由 `is_stock_detail_first_page` 决定。续页的 `meta.endDate`、`dataStatus` 和回包内的 `pageContext` 沿用现有查询语义，整页日期始终以首次 `/page-init` 为准。
- **算子。** `build_calculation_request` 继续按本批首末根实际日期组装区间，一批有目标日 K 时计算一次，无行情时直接返回现有空态。内核从 DG 的 `silver/quote/stock_daily` 和 `silver/quote/adj_factor` 读取不复权日线与股票复权因子，并沿用原前复权和预热规则计算价格及 MA、BOLL、MACD、KDJ。`CalculationResult.price_adjustment` 已含 `basis_date`、`basis_value`。它们留在内核结果中，股票详情 HTTP 回包沿用现有价格字段。跨请求遇到 DG 更新时接受各自按当时可用的因子计算，前端展示回包值。

##### 前端和两个图层

- [`StockDetailPage`](../../../src/pages/stock-detail/StockDetailPage.tsx#L128) 保留首屏快照。本地日线首批有 `meta.nextEndDate` 时，用股票详情的续页状态管理当前游标和页结果。`StockChartWorkspace` 接入共享 `DetailChartWorkspace` 的 `onHistoryViewport` 和 `historyPhase`。沿用上证综指的触发条件，向左拖到已加载行情左端剩 100 根时请求下一批。同一批在途时合并重复触发，按日期将更早行情和指标接到左侧，保持当前视野。失败时保留图表，下次向左拖重试同一截止日。切换证券、日期或离开日线时取消旧请求并丢弃迟到结果。`nextEndDate` 为 `null` 后停止续取。右侧盘口、顶部指数和新闻继续使用首屏数据及日期。
- **九转。** 续页日 K 返回后，沿用 [`fetchStockNineTurnSeries`](../../../src/features/nine-turn/api/nineTurnApiClient.ts#L40)，使用日线能力、股票代码、该批最早和最晚的实际日 K 日期作为 `startDate/endDate`，`limit` 沿用日 K 页大小。续页使用日 K 提供的日期窗口，沿用九转已有数据来源、日期匹配和缺失检查。按日期将结果交给原九转图层。
- **趋势通道。** 沿用现有能力开关和选择指标后加载的时机。对于已经加载的历史日 K 批次，复用 [`fetchStockTrendChannel`](https://github.com/chiuser/goldenshare/blob/75006c992c05239b79aeec6e93a126691b55c141/wealth/src/features/stock-detail/trend-channel/api/stockTrendChannelApiClient.ts#L13)，传股票代码、该批最后一根日 K 的日期作为 `endDate`、本批实际根数作为 `limit`。图层用该批已有的日 K 日期对齐趋势结果，只画对应日期的点。DG 缺少某日的趋势结果时该日留空，查询补足数量而返回的更早结果依日期排除在本批图层之外。首屏继续使用页面日期发出原请求。
- 每批各图层使用自己的加载状态，任一失败保留日 K 和已成功图层。重试只补该批失败的图层。首屏的两路图层和分钟周期的加载方式沿用现有路径。

##### 开发和验收

趋势通道读取修复验收后，先实现本地 `/kline` 日期游标，再接图表及两个图层。复用 §6 的请求时限、取消、资源归还和本机回退流程。每批最多返回 500 根目标日 K，只额外查一个匹配日期用于游标。存在停牌时，找到这一根所经过的 DG 日期分区数可能超过一个，验收记录实际读取成本。每批最多发一个日 K 请求以及两个图层请求，图层重试仅重发对应请求。复用已记录的阶段 4 性能样本作为对照，测量首批、续页及断开重试，保留现有时限配置。

- 扩充[日 K 真实路由测试](../../../../tests/app/technical_indicators/test_stock_daily_source_repair.py)，覆盖首批和续页相邻、长停牌、末批短页、恰好满页但已到最早、空页、源失败和重试。验证每批日 K 与指标时间一致、续页省略盘口、不复权日线与股票复权因子沿用原来源。Prod 和非分页本地回包按原合同回归。
- 扩充[股票详情前端测试](../../../src/pages/stock-detail/StockDetailPage.test.tsx)和[共享图表测试](../../../src/shared/charts/detail-workspace/DetailChartWorkspace.test.tsx)的对应场景。检查固定页面日期、向左拖触发和保持视野、无重叠、到末页停止、首屏盘口稳定、换股换日期后旧回包失效、九转和趋势通道按实际批次查询，以及单图层失败可独立重试。断言趋势通道请求的截止日和根数来自该批，图层按日 K 日期对齐，缺失日期留空，更早的结果不会画到本批图上。
- 用实际本地版本和有界 DG 样本复核贵州茅台首批与至少一批历史日 K，同时核对盘口和两个图层。上证综指保持原拖动及续页方式。按 §7 对照交付清单，以实际接口和浏览器证据验收。

##### 第二步实施与审计

2026-11-20 · 在隔离的本机服务运行本轮构建并用浏览器验收。日 K 和趋势通道读取 DG 正式文件，九转从现有本机接口进行有界只读查询。测试会话隔离了自选及其他非目标请求。常用本地服务和 Prod 均未切换。

- **开始和衔接。** 贵州茅台 `600519.SH` 页面日期为 2026-11-19，首批 500 根日 K 覆盖 2024-10-30 至 2026-11-19，盘口收盘价为 1460.21 元。向左拖动只发出一次续页请求，`tradeDate` 仍是 2026-11-19，`endDate` 来自上一批的 2024-10-29。续页 500 根覆盖 2022-09-30 至 2024-10-29，下一截止日为 2022-09-29，省略盘口。两批无重叠，数据接入图表后可视日期和右侧盘口保持稳定。
- **图层。** 续页九转按实际首末日期查询，500 个行情日期均匹配。首次续页趋势请求人为返回 503，图表和九转保持可用。点击趋势通道的重试只重发该图层，结果 500 条与续页日 K 日期逐一对齐。验收浏览器无脚本错误。
- **历史边界。** 新上市样本 `920309.BJ` 请求 500 根，返回上市后 3 根和 `nextEndDate: null`。请求截止日早于上市日时返回空日 K、`quote: null` 和 `nextEndDate: null`。真实路由测试覆盖最后一批恰好满页、短页、空页和跨停牌。
- **性能和中断。** 首次浏览器与测试并行运行时首批触发一次现有工作时限。单独复验首批 4.717 秒、续页 4.464 秒。另从真实 HTTP 请求中观察到续页占用计算名额后断开，约 12 毫秒后观察到占用和等待均为 0。按同一截止日重试，5.470 秒返回 500 根，结束后资源归零。沿用现有时限配置。
- **回归和边界。** 44 项后端、80 项前端定向回归通过。前端使用串行执行复查了初次并行测试中的一个分钟线用例。类型检查和前端构建通过。Prod 股票详情 OpenAPI 与本轮开发前逐项相同。用 CodeGraph 核对本地股票日 K 路由、计算调用、股票图表和现有图层消费者。指数和股票分钟线继续使用原实现。

##### 本机切换后复验

2026-11-20 · 在常用本地服务 `127.0.0.1:8000` 完成股票日 K 翻页切换。重启后的后端已提供本地分页响应，沿用该进程，将仍在服务的旧 Wealth 静态包换成阶段 2 版本 `b62deb494` 对应的新构建。类型检查、构建及服务实际返回的静态资源校验均通过。浏览器复验使用隔离会话和自选项，股票、指数及图层使用实际接口。Prod 未切换。

- **首批与续页。** 贵州茅台 `600519.SH` 以 2026-11-19 为页面日期，首批 500 根覆盖 2024-10-30 至 2026-11-19。盘口收盘价为 1460.21 元，开高低收、日期及其余共用字段与末根日 K 一致。向左拖动仅发出一次日 K 续页请求，`tradeDate` 仍为 2026-11-19，首批的 `nextEndDate`（2024-10-29）用于续页的 `endDate`。续批 500 根覆盖 2022-09-30 至 2024-10-29，下一批截止日为 2022-09-29。两批日期无重叠，续页省略盘口，页面日期、右侧盘口与接入续页前的可视日期保持稳定。
- **两个图层。** 续页九转和趋势通道各发一次请求，分别核得 500 个匹配日期。额外以万科 A `000002.SZ` 核对趋势通道跨停牌返回的 5 条记录，实际日期为 2015-12-16、12-17、12-18、2016-07-04、07-05。
- **上证综指。** 从页面顶部的上证指数卡打开日线，返回并展示 500 根，页面日期和末根日 K 日期均为 2026-11-19，下一批截止日为 2024-10-29。两页均无浏览器脚本错误。贵州茅台首批与续批的单次请求实测分别为 4.738 秒与 3.769 秒。

首屏时序、翻页流程及本地字段来源已同步到[股票详情页数据字段来源表](stock-detail-field-source-audit-v1.html)。

## 6. 开发顺序和验收清单

| 阶段 | 代码落点及测试 | 完成凭据 |
| --- | --- | --- |
| 1. 日历取数与 Job | §2 的文件及资产。专用 [隔离回归](../../../../lake_console/orchestrator/tests/test_trade_calendar_update.py) 验证请求只有 SSE、字段和分页参数。覆盖整页续取、短尾页、重复日期、漏日、无效类型、历史或最新覆盖不足、源修订、Raw 已完成后的恢复。用现有 Job 执行两层及检查 | 运行独立项目现有环境的目标 pytest、Ruff，按 §2.3 核对页数、时间、空间和恢复预算。正式一次执行后给出 run ID、两文件对账和三项 check。正式运行需按单独已批准窗口执行 |
| 2. 本地后端读取迁移 | §3、§4 的文件。读层用临时 Parquet，以真实 Raw/Silver 字段构造夹具。覆盖前导零、退市、缺代码、缺列、非法日期、主键重复、开休市和日期范围。用 [`test_wealth_market_page_context_query.py`](../../../../tests/test_wealth_market_page_context_query.py) 扩充 PG/DG 日期对照，固定时钟和 DB 路径对照。每个联表用 PG 只读 SELECT 验证空关系、原 left/inner join、排序、游标和聚合，再用本地真实入口旧表拒绝测试证明没有隐式回读 | 提交一份守卫覆盖清单。按 §4 核对所有读取点，指定 Prod 连接与 PG 写入业务继续通过原回归。DG 证券计数差异、异常记录及有效窗口现场证据可复查 |
| 3. 首屏接口和前端 | §5.1–5.3 的 DTO、组装、App 路由、页面和 hooks。扩充 [股票 HTTP 测试](../../../../tests/web/test_wealth_stock_detail_api.py)、[日 K 集成](../../../../tests/app/technical_indicators/test_stock_daily_integration.py)、[首屏页面测试](../../../src/pages/stock-detail/StockDetailPage.test.tsx)、[新闻面板测试](../../../src/features/stock-detail/news/StockDetailNewsPanel.test.tsx) 和 [ViewModel 测试](../../../src/features/stock-detail/api/stockDetailViewModelAdapter.test.ts)。断言本地初始化和完整首屏都不读取旧股票日线技术因子表，有目标日 K 时只算一次，覆盖延迟、错误、休市、无目标和普通区间请求。比较末根日 K 与盘口的每个字段，包括 null 与非空单位 | 本地与 Prod 的真实路由合同、OpenAPI、认证和错误包络均通过。Wealth typecheck、定向 Vitest、build 通过。浏览器核对无锚点时无日期请求、本地首屏两个日期均为 D、其他日期请求沿用 D，以及上一日期的响应无法回写 |
| 4. 联调、验收与本地切换 | 真实 DG 有界窗口选在市 `600519.SH`、退市 `600005.SH`、不存在代码、开市和休市，以及 2027 边界。以同一锚点检查日线及辅助字段实际来源，核对分钟/九转和指数原有行为。测量相同请求重复、断开后恢复、两个同到请求，检查名额、连接、事务清理。只读对照 Prod 的已知样本，保持输入和回包的原合同 | 本地两来源替换与首屏同时通过，按阶段记录实际文件、请求参数、计数、耗时和未覆盖场景。有任一依赖差异尚未解释，暂停对应切换 |

阶段 1 的源分页和隔离测试见 §2.2、§2.4，正式运行和发布验收按 §2.3 执行。阶段 2 的证券差异已有核验结论，完整读路径按 §4 验收。首屏 UI 可用隔离数据开发。真实整体验收依赖阶段 1、2 的来源就绪。

首屏日 K 预算沿用现有部署设置。默认产品上限 500 根，内核配置可设更低；并行 2、等待 2、排队上限 2 秒、请求总目标 8 秒含 2 秒清理预留，数值见 [Settings](../../../../src/foundation/config/settings.py#L72)。此前一次 DG 两条并发实测为 5.64/5.74 秒，距离 6 秒工作窗口较近。改造后抓取单次、双并发和断开重试的实际响应，分别记录 page-init、日 K、DG 文件读取次数、一次计算、会话清理及重试后的资源归零。先用单代码和限量窗口做验证；失败时定位哪个步骤超预算，保留既有产品和内核阈值。 [历史验收样本](../../../../docs/architecture/technical-indicator-operator-library-implementation-lld-v1.md#L318)

发布时在本地同一构建交付对应的前端与后端合同。暂停或回退时恢复上一套成对的本地构建，按原请求条件验证服务，再修正后续切换。日历文件的后续修复用 §2.3 的逐层核对和 Dagster 入口，数据库迁移及正式数据源的整体回滚不属于本次发布。

## 7. 编码门禁矩阵

逐项对照 [Wealth 模块交付清单](../../system/module-delivery-checklist-v1.md)。本期变更的是已上线页面的取数、响应分工和请求时序。沿用 [股票详情视觉验收基线](stock-detail-figma-pixel-verification-ledger-v1.md)。以下是开工和提测要核对的项目。

股票日 K 翻页按 §5.4 核对本地响应合同、现有能力开关、日期边界、请求和重试成本、图层状态及真实页面展示。该后续事项沿用本节对应的交付门禁、现有图表坐标和视觉基线。

| 通用清单 | 本期适用性、落点及核验 |
| --- | --- |
| §2.1 交付事实链 | 适用。业务范围以本期方案为准，代码合同以本文为准，画面以现有视觉基线为准。阶段验收前核查两份文档、实际接口和页面是否一致 |
| §2.2 后端事实归一 | 适用。§5.2 后端从末根目标日 K 组装盘口，前端读取响应既有字段。对比盘口、K 线和指标使用的价格及日期 |
| §2.3 状态机与超时 | 适用。无页面上下文或首屏日 K 读取中为 loading，成功有行情为 ready，滞后时展示实际行情，回包携带实际行情日及 `DELAYED` 数据状态，无目标行情为 empty，HTTP/源错误为 error。日 K 服务使用 §6 的既有 8 秒总目标和 2 秒清理预留。客户端沿用 `wealthFetch` 的取消和现有错误展示，测试超时时不渲染行情或复用上次盘口 |
| §2.4 显示语义 | 适用。方向取 DTO 的 `direction`，量额用现有接口单位，换手率和量比缺失显示 `--`。回归覆盖涨、跌、平及真正为零与缺失两种样本 |
| §2.5 行为过程 | 适用。§5.3 和阶段 3 测试覆盖等待锚点、空态、超时文案、旧请求取消、切换周期及同一证券切换日期 |
| §2.6 文档同步 | 适用。接口、字段、状态、阶段边界和首次上线证据同轮核对方案、LLD、字段来源表和契约测试。现行截图继续作为布局回归依据 |
| §2.7 渐进替换 | 适用。本期两个引用数据集按 §4 逐入口迁移，首屏后端与前端配对切换。记录现有 `APP_ENV` 选择和发布版本。按 §6 复核真实来源和回退，范围覆盖用户已批准的所有本地调用 |
| §2.8 契约先行 | 适用。§5 固定两个 URL、环境对应 DTO、null 与缺键语义。真实路由断言 HTTP、认证、OpenAPI 及页面消费字段，新旧构建交叉风险用同版本配对避免 |
| §2.9 坐标和文案 | 不适用新坐标或说明文案。本期复用图表和格式化组件。页面回归对照现有图表主副区 |
| §2.10 查询与传输 | 适用。§3.3 将筛选、聚合和分页留在原查询边界，只读取必要 DG 字段。PostgreSQL 专用关联 SQL 走隔离 PostgreSQL 测试。无联表场景可用临时 Parquet 或原既有单测库 |
| §2.11 策略配置 | 不适用。本期无策略中心注册项。已有环境和 Lake 根目录的读取、生效和无效配置行为按 §3.1 测试 |
| §2.12 映射矩阵 | 适用。本节与 §6 对照逐项验收 |
| §2.13 例外与断言 | 适用。无需新增模块例外。适用的日期锚点、回包字段、数值及异常均有断言 |
| §2.14 显式坐标 | 不适用新坐标参数。本期未改 `yMin/yMax/yTickValues`，现有图表坐标测试随页面回归 |
| §2.15 双图对齐 | 不适用新并排双图。本期复用现有工作台布局 |
| §2.16 卡片单行 | 不适用新指标卡片或文案样式。本期盘口用现有数值格式及布局 |
| §2.17 核心测试 | 适用。按本节后述测试及 §6 的正式验收执行，走真实路由及页面消费 |
| §2.18 跨模块原则 | 单一来源见 §2–4，契约和默认行为见 §5.1–2，配置见 §3.1，筛选和排序见 §3.3–4，性能预算见 §2.3 和 §6，错误和调试来源见 §3.2 和 §5.2，实际页面状态和展示门禁见 §5.3 和本节核心测试 |

### 核心测试和通过标准

- **后端真实路由。** 使用现有 Web 测试环境，运行 `python -B -m pytest -q -p no:cacheprovider tests/test_wealth_market_page_context_query.py tests/web/test_wealth_stock_detail_api.py tests/app/technical_indicators/test_stock_daily_integration.py`，测试临时产物按仓库规则放到 `/private/tmp`。在既有 DG、Prod 只读合同样本上分别请求相同日期。本地 init 检查 `pageContext.tradeDate`、证券身份、图表默认项和能力开关，确认省略 `quote/dataStatus`。本地首屏用 `tradeDate=D&endDate=D` 请求，核对 `quote` 的日期、价格、量额及股票每日指标与末根 K 线一致，方向按末根 K 线的涨跌幅校验，空态显式返回 `quote: null`。普通请求分别覆盖仅传 `endDate`、两日期不同、两日期相同但指定 `startDate`，确认原区间、排序、根数与状态沿用，回包省略 `quote`。检查 `dataStatus` 的预期和实际日期，以及图表消费的 MA、BOLL、MACD、KDJ。旧代码样本在本地返回 `404001`，Prod 保留现行响应。验证源错误用既有包络，取消、超时和重试后连接及计算名额正常归还。
- **前端页面。** 运行 `npm --prefix wealth run typecheck`、`npm --prefix wealth run test -- src/pages/stock-detail/StockDetailPage.test.tsx src/features/stock-detail/news/StockDetailNewsPanel.test.tsx src/features/stock-detail/api/stockDetailViewModelAdapter.test.ts` 和 `npm --prefix wealth run build`。浏览器连接真实本地接口，确认先有 page-init 回包再有日期请求。按 §5.3 对照网络参数、页面状态和末根日 K 的实际盘口，覆盖退市、空态、旧响应取消和新闻时间边界。Prod 回包夹具用于类型和消费回归，另在 Prod 合同的真实路由上做只读对照。

### 阶段 3 实施核对记录

2026-11-20 · 本地首屏已实现，待 review。阶段 4 的联调和切换另行验收。

- **本地合同。** [隔离路由回归](../../../../tests/app/technical_indicators/test_stock_daily_source_repair.py) 对本地股票详情业务禁用 PostgreSQL 会话，使用符合正式 DG 字段的临时数据。首屏两日期相同时，日 K 有结果只计算一次，末根日 K 与盘口逐字段一致。空首屏明确返回 `quote: null`，普通区间省略 `quote`。覆盖查无标的和 DG 读失败。
- **正式 DG 只读样本。** 浏览器通过本地实际两个股票详情路由打开贵州茅台，将页面日期明确设为 2026-11-15。初始化先返回页面日期，随后两日期均为该日的日 K 请求返回 500 根。末根和盘口日期为 2026-11-13，状态为 `DELAYED`，右侧显示 1435.26，与末根收盘和源文件按复权因子重算的价格一致。测得一次算子调用 3.68 秒，此数值是该样本的计算时间。浏览器环境的登录与其他模块响应使用隔离夹具，已核到顶部指数、九转和新闻请求使用页面锚点，新闻上界为上海时间 2026-11-16 00:00。
- **回归。** 75 项后端定向测试、78 项前端定向测试、Wealth 类型检查和构建通过。Prod 两个股票详情接口的 OpenAPI 路径和 20 个相关 schema 与改动前完全相同，隔离路由回归覆盖原回包和 500 根上限。保留股票日 K 元数据原字段。向前翻页仍按 §5.4 作为后续事项。

### 阶段 4 联调验收记录

2026-11-20 · 以阶段 3 提交 `e1504ae51` 为基线。接口和候选前端联调通过。浏览器使用该提交临时构建的 Wealth，访问正在运行的本机 Web 及实际数据接口。验收浏览器使用测试会话，个人自选组返回隔离样本。当前 Web 提供的 Wealth 静态包未替换，正式切换未执行。

- **股票首屏和日期边界。** 贵州茅台 `600519.SH` 默认锚定 2026-11-19，初始化耗时 0.062 秒，调试来源为 DG 股票基础信息和交易日历。日 K 请求在初始化回包后发出，两个日期同为 11-19。图表返回 500 根，末根日期为 11-19，盘口全部对应字段与末根一致，右侧显示 1460.21。指定休市日 11-15 时页面保留 11-15，末根与盘口为 11-13，状态为 `DELAYED`。1998-12-31 的空首屏返回 `quote: null`，不存在的标的 `999999.SH` 返回 `404001`。武钢股份 `600005.SH` 的身份接口返回退市状态。2027-01-01 休市、2027-01-04 开市，两者的上一交易日均为 2026-12-31。
- **图层和指数。** 顶部指数、股票 5 分钟行情及指标、九转和趋势通道均用 11-19 请求并返回 200。九转匹配 500 根，缺失为零。新闻上界为北京时间 11-20 00:00。初次两轮浏览器分别在 10 秒和 35 秒等待上限内未收到新闻回包，原请求与带日期的新请求随后在有时限的只读查询中各返回 50 条。同参数的本机 HTTP 复核耗时 0.407 秒，浏览器重试返回 200 和 50 条。两次等待超时的原因未复现。上证综指 11-19 的 DG 指数日线 Raw 和 Silver 更新后，首批和向前续页各返回 500 根，首批最早为 2024-10-30，续页最晚为 2024-10-29。
- **性能和中断。** 同一股票、同一日期请求 500 根，单次和重复耗时 4.429、3.214 秒，双并发为 5.094、5.097 秒。请求中途断开后两次并发重试均返回 200，耗时 4.962、4.882 秒，所有成功响应的 K 线与盘口内容一致。单独观察同配置的隔离进程，强制在开始 DG 文件读取后断开，计算名额和等待数都回到零。成功重试只调用一次算子，记录 3,502 个去重后的行情、复权因子及相关文件路径，未创建股票日 K 业务 PostgreSQL 会话。文件计数为请求读入记账口径。
- **Prod 对照。** 用只读事务在 `core_serving.equity_daily_bar` 和 `core_serving.index_daily_serving` 分别读取 11-19 的贵州茅台和上证综指单行。与 DG 同日普通日线的四价、昨收、涨跌和量额共九个字段逐项一致。Prod 回包合同使用隔离路由回归核对，含原响应形状和 500 根上限。此次定向回归 15 项通过。

### 阶段 4 本机切换后复验

2026-11-20 · 联调验收记录提交 `aa2dc0ce6` 后，本机 Web 开始提供新 Wealth 构建 `index-DAUBOUAb.js`。运行中的本机后端已提供阶段 3 接口，沿用该进程。Prod 未发布或写入。浏览器使用测试会话，个人自选组使用隔离样本，页面文件和下列行情接口均来自实际运行的本机服务。

- **贵州茅台 `600519.SH`。** `/page-init` 返回页面日期 2026-11-19，没有盘口字段。随后页面只发出一次日 K 请求，`tradeDate` 和 `endDate` 均为 2026-11-19，返回 500 根。盘口日期和对应字段与末根日 K 一致，右侧显示 1460.21 元。
- **上证综指 `000001.SH`。** 从顶部「上证指数」卡片打开详情，初始化和日线接口均返回 HTTP 200，日线图显示 500 根，末根与页面日期均为 2026-11-19，返回的 `nextEndDate` 为 2024-10-29。两条页面路径均未出现浏览器脚本错误。
