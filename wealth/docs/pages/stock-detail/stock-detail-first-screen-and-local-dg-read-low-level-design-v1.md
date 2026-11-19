# 股票详情首屏与本地 DG 取数迁移 LLD v1

> 2026-11-19 · 待开发评审。[本期方案](stock-detail-first-screen-and-local-dg-read-plan-v1.md)确定业务范围，本文规定代码入口、数据合同、实施顺序与验收。下文标为「拟新增」的类和方法是开发合同。

## 1. 实施边界与开工条件

| 工作 | 已确认的规则 | 实施通过条件 |
| --- | --- | --- |
| DG 交易日历 | 上交所 `SSE` 取消本地起止日期限制。复用现有 Job 手动更新一次 Raw、Silver | 两层覆盖至少到 2027-12-31，并保留原有历史。之后源继续提供更远日期则照常收入 |
| 本地证券和日历 | Web、Ops、后台任务等本地运行入口读取这两类业务事实均走 DG。有效文件里查不到记录时沿用各入口原来的缺失处理 | §4 的读取入口全部换源。读 PostgreSQL 的两张旧表会报错的测试环境下，本地调用仍可走通 |
| 股票详情 | `/page-init` 的 `pageContext.tradeDate` 是整页最新日期。日 K 和指标只算一次，首屏盘口复用同一次的末根日 K | 每条后续日期请求都使用该日期，实际行情滞后和历史翻页不改变页面日期或盘口 |
| Prod 与后续期 | Prod 继续使用现行 PostgreSQL、原响应模型和原参数行为。股票、指数分钟线的行情来源与指标升级放到下一期 | 共用前端分别验证两种首屏回包。原 Prod 响应 JSON 字段集合、值与 OpenAPI 模型通过回归 |

下列核验记录交易日历接口的实际行为和证券来源切换口径。

- **日历取数。** Tushare 只读样本已返回 2026-12-30 至 2027-01-05 的 7 条 SSE 记录，以及 2027-12-29 至 2027-12-31 的 3 条。2027-01-01 为休市，上一交易日为 2026-12-31。MCP 的 `trade_cal` 工具不接受 `limit/offset`。2026-11-19 只读复核正式 Dagster 物化记录 `ab0378dd-08c8-413f-a564-f1c137e585f2`，上次带日期请求以 `limit=6000` 执行 3 页，共 13,162 条。MCP 另外在 1990-12-17 至 12-21 的边界样本中只返回 12-19 起的 3 条，在 2027-12-30 至 2028-01-03 的边界样本中只返回 2027 年末两条。随后用 HTTPS 无日期小页抽查，在偏移 0 读到 2027-12-31，偏移 13,526 读到 1990-12-19，偏移 13,527 返回空。追加一次无日期首屏请求 `limit=6000, offset=0`，实返 6,000 条。无日期分页合同已核实，实施沿用每页 6,000 条，详见 §2.2。
- **证券覆盖。** 已定位本轮计数差额。Prod 5,926 条 `EQUITY/tushare` 与 DG Raw 5,924 条的分组差异仅在 SSE、退市、CNY。该组逐键比较确认 `T00018.SH` 和 `TS0018.SH` 只在 Prod。当前未发现对正常在市搜索、已核自选和交易助手存量记录的影响，直接按旧代码访问本地详情会少这两条证券身份。已确认本地按 DG 查无标的返回 404，Prod 保留原行为，详见 §4。

## 2. DG 交易日历更新

### 2.1 改动位置及执行顺序

| 位置 | 实现 |
| --- | --- |
| [`assets/calendar.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/assets/calendar.py#L105) | 删除 `TRADE_CALENDAR_START_DATE`、按运行年份算出的 `end_date` 及对应请求日志。Raw 请求固定 `exchange=SSE`，显式投影 `exchange, cal_date, is_open, pretrade_date`。Raw 和 Silver 均先写 run-scoped staging 候选并校验，再发布。日志报告候选和正式文件实际起止日、行数、实际页数及耗时 |
| [`tushare_api_io.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py#L468) | 沿用已实测的 6,000 条页长及现有短页结束规则。保留其他接口的现有行为。日历候选须核对日期连续性、最新和历史边界及唯一键，防止漏页、重复页或提前截断形成可发布文件 |
| [`paths.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/paths.py#L150)、[`catalog/lake_assets.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py#L1986) | 统一定义本次日历候选路径，并校准两个资产的写入、性能及合同说明。正式日历路径沿用现有 helper，字段合同沿用 `RAW_TUSHARE_TRADE_CALENDAR_SCHEMA`、`SILVER_TRADE_CALENDAR_SCHEMA` |
| [`calendar_update_job`](../../../../lake_console/orchestrator/src/orchestrator/defs/jobs/calendar_update.py#L6)、[`checks/calendar_checks.py`](../../../../lake_console/orchestrator/src/orchestrator/defs/checks/calendar_checks.py#L163) | 继续选择两层资产及三项正式检查。执行顺序为 Raw 发布、Raw 检查、Silver 发布、两项 Silver 检查。对候选的文件完整性检查复用现有检查的稳定规则。Raw 与 Silver 的一致性在发布前验证，正式检查及运行记录仍发出 |

候选读取和发布由日历资产负责。Job 继续负责选择资产和检查。测试与正式执行均使用相同的资产逻辑，分别注入临时目录和正式路径。

```python
@dataclass(frozen=True, slots=True)
class CalendarFileStats:
    path: Path
    first_date: date
    last_date: date
    row_count: int
    sha256: str

# 拟在日历资产内部补充。候选须唯一，且属于本次 Job 运行。
def calendar_candidate_path(staging_root: Path, run_id: str, layer: str) -> Path: ...
def inspect_calendar_candidate(path: Path, *, layer: str) -> CalendarFileStats: ...
def verify_calendar_coverage(
    candidate: CalendarFileStats, *, current: CalendarFileStats | None
) -> None: ...
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

1. **分页合同。** `trade_cal` 请求保留 `exchange=SSE` 和四个显式字段，省略 `start_date/end_date`。沿用共用分页方法，以 `limit=6000` 从 `offset=0` 取数，每个满页后按实际约定增加 6,000，遇合法短页结束。完整候选经 §2.3 校验后才发布。6,000 是已验证可用页长。
2. **生成 Raw 候选。** 正式取数以源实际发布范围为准，程序不根据本地年份裁剪 `start_date/end_date`。以实测的有效 `limit` 分页，每页字段和交易所一致。校验日期有效、序列和页间边界符合已验证的方向，且 `(exchange, cal_date)` 无重复。请求失败、字段缺失、重复页、意外空页和超出实测预算均作为取数失败。用一次聚合核对 `distinct_date_count == (last_date - first_date).days + 1`，同时确认无 NULL 主键及非法开市标记。
3. **与现有文件对账。** Raw 候选必须包含原日历的日期范围及日期键。记录开休市或上一交易日的变化，用源记录核对不能解释的差异。检查历史事实的业务抽样，并抽检跨年、开市、休市的 `pretrade_date`。源真实修订可随更新写入，运行前核对本次切换要求的日期及状态，发现所需范围尚未由源发布时，记录缺口并暂停本次正式补数与读取切换。日常候选发布比较已有正式文件的范围及键，2027-12-31 用于这次迁移验收。
4. **生成 Silver 候选。** 调用 [`silver_trade_calendar_select`](../../../../lake_console/orchestrator/src/orchestrator/defs/duckdb_sql.py#L168) 将 `cal_date` 转为 `trade_date: DATE`，将 `is_open` 的 0/1 转为 `BOOLEAN`，将 `pretrade_date` 转为可空 `DATE`。Raw 保留原 `YYYYMMDD` 字符串和整型开市标记。Silver 候选与 Raw 规范化后以日期键双向比对，行数相等且字段逐日对应。首条历史记录允许源合同中的空上一交易日。非法日期或无效开市值报错，不填默认值。

### 2.3 发布、失败恢复与执行预算

- 在维护窗口查询正式 DG 同一资产是否有排队或在跑的运行。确认正式 Lake 和 staging 挂载、可写、同文件系统、存在可用空间，且只有本次 `calendar_update_job` 是这两张文件的写入者。通过正式 Dagster UI 触发，也通过同一实例读回运行和检查结果。正式执行时另按已批准的执行窗口操作。
- staging 位于 `/Volumes/datasource/data_lake_staging`。候选完整通过后分别用 `os.replace` 提升为正式文件。每次提升后记录 run ID、层、路径、行数、范围、摘要及状态到该次运行的物化信息与 staging 的检查点。检查点写不完整时，用正式文件读回、摘要和 Dagster 检查交叉确认完成位置。正式路径分别为 `raw/tushare/trade_calendar/full/part-000.parquet` 和 `silver/calendar/trade_calendar/full/part-000.parquet`，根目录为 `/Volumes/datasource/data_lake`。
- Raw 未发布就按源错误处理，已经发布的正式文件保留。Raw 已更新且通过检查、Silver 未完成时，以该 Raw 为输入，在现有 Job 的失败重执行路径补齐 Silver 及其检查。重执行前复核 Raw 未被改写，读回摘要与记录一致。若失败发生在文件替换后、记录完成前，先对照候选、正式文件及检查结果再决定重做的步骤。两层检查和读回复核全部通过才允许本地日历切换。
- 验收留存实际文件构成和两层起止日期、行数、重复键数、缺日期数、差异数、开休市与上一交易日样本、Job run ID 和三个 check 结果。覆盖至少达到 2027-12-31，该日期只用于本次切换下限。下游日期范围照原产品条件查询。

| 成本项 | 核算与控制 |
| --- | --- |
| 请求与页数 | 一个交易所，两个资产均是一个全量文件，没有按日期 fan-out。源确认有效页长为 `L`，从偏移 0 取 `N` 行、以首个合法短页结束时，请求数为 `N // L + 1`，包括整页情况下的末尾空页。按当前抽查的首尾、偏移和实测页长，预计更新请求偏移 0、6,000、12,000 三页，页行数分别为 6,000、6,000、1,527。核验实际读取了首个整页和各边界小样本；后两页的实际行数及正式文件总行数在 Job 执行时复核。把边界探测和异常请求次数另记 |
| 读写量 | 当前已知正式 Silver 为 89,590 字节、13,162 行。一次正常 Job 生成一个 Raw 候选、一个 Silver 候选，最多各提升一次。按来源页、候选、检查及最后读回分别记录文件字节、投影行数、SQL 次数；检查用聚合与小样本，禁止逐日打开文件或逐日请求 |
| 中断恢复 | 源尚未完成的失败重执行最多重做当前一次完整 Raw 取数及后续步骤。Raw 已核实的 Silver 恢复不发 Tushare 请求，只增加一次 Raw 读取、Silver 生成与两层对账。实测记录正常和断点恢复的请求数、DuckDB 用时、staging 峰值、检查和读回用时 |
| 正式运行停止条件 | 页长、覆盖、预计页数、文件空间与耗时先用有界探测和隔离验证确定。正式开始前以实测补齐预算记录，当前文档不把估算作为运行耗时承诺。发现未解释的截断、缺口、正式目标冲突或空间/耗时超出核准预算时停止发布 |

## 3. 本地证券和日历的读取合同

### 3.1 配置和注入

沿用 [`Settings`](../../../../src/foundation/config/settings.py#L17)、现行 [内核运行时选择](../../../../src/app/runtime/technical_indicators/composition.py#L33) 和 [本地构建配置](../../../../scripts/local-build-and-run.sh)。`APP_ENV=dev/local` 选择 DG，`prod/production` 选择 PG。`GOLDENSHARE_LAKE_ROOT` 从同一套设置读取，本地正式配置预期为 `/Volumes/datasource/data_lake`。本地缺配置、文件读失败或合同错误直接走取数错误。通用交易日历接口继续接受调用方的 `exchange`。现行本地默认 `DEFAULT_EXCHANGE=SSE`，两个来源经核验均只含 SSE，因此接口收到一个合法但无记录的交易所时照常返回空列表，不自动映射成 SSE。沪深 A 股共用 SSE 日历的现有业务调用继续保留显式 SSE。

- 在 App 组合根按显式部署模式一次构造 `ReferenceData`。Web 在 [`src/app/web/lifespan.py`](../../../../src/app/web/lifespan.py) 组装并通过各路由已有依赖或路由工厂传给 Biz、Ops 和日 K 后端。CLI 从 [`src/cli.py`](../../../../src/cli.py) 接线，后台任务从 [`ops_worker_factory.py`](../../../../src/app/runtime/ops_worker_factory.py#L80) 传给 worker、dispatcher、planner 与实际查询。Foundation 只定义读取合同和适配器。下层只接收解析完成的读取对象，依赖方向按 [子系统架构基线](../../../../docs/architecture/subsystem-boundary-plan.md#3-目标依赖方向)。
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
    def get(self, session, *, exchange: str, day: date) -> TradeCalendarRow | None: ...
    def range_rows(self, session, *, exchange: str, start: date, end: date,
                   open_only: bool = False) -> tuple[TradeCalendarRow, ...]: ...
    def recent_open_rows(self, session, *, exchange: str, bound: date, limit: int,
                         include_bound: bool = True, start: date | None = None
                         ) -> tuple[TradeCalendarRow, ...]: ...
    def context_rows(self, session, *, exchange: str, end: date,
                     recent_open_days: int) -> tuple[TradeCalendarRow, ...]: ...

class SecurityReferenceReader(Protocol):
    def get(self, session, *, ts_code: str) -> SecurityReferenceRow | None: ...
    def read_by_codes(self, session, *, ts_codes: Sequence[str]
                      ) -> Mapping[str, SecurityReferenceRow]: ...
    def listing_dates(self, session, *, ts_codes: Sequence[str]
                      ) -> Mapping[str, date | None]: ...
    # 保留各入口 filter、rank、limit 语义所需的具体实现，不共用单一股票池。
    def search_a_shares(self, session, *, keyword: str, escaped_prefix: str,
                        limit: int) -> tuple[SecurityReferenceRow, ...]: ...
    def planning_equities(self, session) -> tuple[SecurityReferenceRow, ...]: ...

@dataclass(frozen=True, slots=True)
class ReferenceData:
    calendar: TradeCalendarReader
    security: SecurityReferenceReader

# App 的 Web、CLI、常驻进程入口复用此装配。不承担写入。
def build_reference_data(settings: Settings) -> ReferenceData: ...
```

- PG 方法使用调用方已有的会话和事务。`session` 的类型为 `Session | None`，PG 需要现有会话，DG 直接读文件。对日 K、交易助手等已有请求时限的入口，把剩余工作时间传给 DG 读取，沿用对 [`IndexDailyLakeReader._read`](../../../../src/foundation/clients/local_lake/index_daily_reader.py#L169) 的 DuckDB 查询中断与连接清理做法。读入前与读入后都检查请求状态，取消或过期时保留原异常分类。直接读取方法按调用方已知过滤实现。给联表提供的内部投影固定白名单，日期、代码、筛选值和上限绑定传入。测试通过临时 Lake 根及指定的会话注入替身。
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

清单来自 CodeGraph 的 `codegraph_explore` 对首屏、证券/日历查询和 DG Job 的三次调用链跟踪，以及仓库中对 ORM 别名、DAO 访问及原生 SQL 的核对。表内组别按改造动作划分。实际提交在每个入口补上新读取方法和回归用例。

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

## 5. 股票详情首屏

### 5.1 现有 URL 和回包结构

保留两条 GET。App 在 [`src/app/api/v1/router.py`](../../../../src/app/api/v1/router.py#L107) 装配对应环境的 [股票详情路由](../../../../src/biz/api/wealth/market/stock_detail.py)。参照同文件的指数路由，由股票详情提供 `build_router(..., local: bool)` 注册两条路径及对应 `response_model`。选用与 §3 相同的部署模式。环境在组合根确定，仅注册一组路由，Prod 的 OpenAPI 与现有两个响应模型保持一致。本地 `/kline` 的 OpenAPI 使用 `LocalStockDetailFirstKlineResponseDto | StockDetailKlineResponseDto`。现有 ASGI 响应由后端选择具体 DTO 后序列化，首屏 `quote:null` 必须保留，普通页不输出该键。认证依赖及参数校验沿用。

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
    # 沿用现有 tradeDate 与 endDate 参数，用两个相等的值表达首屏。
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
| 历史 `/kline` 或普通区间 `/kline` | 继续提供原 K 线响应和区间状态。若页面随请求带 `tradeDate=D`，实际续页仍用早于 D 的 `endDate`。没有显式首屏合同的调用维持原回包 | 原 `StockDetailKlineResponseDto` |

第一个请求的输入仍由 URL 决定，两个日期相等的约定只用于辨认本地首屏，旧的请求字段和窗口优先级保持。共用前端在两种回包下都使用页面日期锚定后续日期窗口，Prod 单独调用各接口时的默认行为保持。共用前端只给新本地合同发送首屏日期组合，Prod 仍使用原请求参数。已有股票页面当前只有首屏请求，若已有客户端按区间读取历史，继续沿用其原合同，本期不增加股票图表分页功能。Prod 的首屏 `quote: null` 仍是现有字段存在的结果，前端通过字段是否存在区别两种合同。

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
| [`StockDetailPage.tsx`](../../../src/pages/stock-detail/StockDetailPage.tsx#L60) | 使用当前证券与 URL 日期初始化一次请求。先发 page-init，成功即存 `pageInit` 和 `pageContext.tradeDate`，再发日 K。新轮次清除旧锚点、盘口、图层和挂起请求。渲染时只使用本次证券与显式日期的结果，响应落状态前同时核对当前轮次和 AbortSignal，避免相同证券不同日期的上一轮结果短暂显示或回写 |
| [API 类型](../../../src/features/stock-detail/api/stockDetailApiTypes.ts) 与 [`buildStockDetailViewModel`](../../../src/features/stock-detail/api/stockDetailViewModelAdapter.ts#L62) | `pageInit` 类型区分 Prod 有 `quote/dataStatus` 键与本地无这两个键的合同。`kline` 支持首屏可出现的 `quote`。用键存在检查选择来源，本地只使用首屏 K 线回包中的盘口和状态，Prod 继续使用旧初始化盘口。K 线空数组用当前空态。非空本地首屏缺少盘口属于接口结果不匹配，交给现有页面加载失败状态 |
| [`useMajorIndexTickers`](../../../src/features/major-indices/model/useMajorIndexTickers.ts) | 为 hook 增加调用级的 `enabled` 参数，既有调用默认启用，只有股票详情在拿到有效 `pageInit` 之前传 false。启动后向现有指数接口显式传 `tradeDate=D`，锚点切换时取消旧请求，其他页面的默认加载时机照旧 |
| [`StockInfoRail.tsx`](../../../src/features/stock-detail/sidebar/StockInfoRail.tsx)、[`StockDetailNewsPanel.tsx`](../../../src/features/stock-detail/news/StockDetailNewsPanel.tsx) | 由页面直接沿 props 传 `D`。新闻面板以 `tsCode+D` 为缓存和请求标识，激活时使用 `endAt=上海 D 次日 00:00:00+08:00`，含下界、排除该上界。换日期时取消旧请求并清缓存。客户端以日期加一天计算日历边界，结果不受浏览器所在时区影响；如 D=2026-11-15，传 `2026-11-16T00:00:00+08:00`。原详情新闻的默认回看、去重和 50 条面板上限维持 |
| 分钟 K 线和指标、九转、趋势通道 | 继续使用同一个 `D`。分钟缓存以证券、D、频率随加载轮次隔离，九转和趋势通道的 `endDate` 只从有效页上下文取。历史窗口或换周期不能改变首屏盘口。自选组和交易助手表单的非日期参数保持现行合同 |

具体日期和状态断言如下。若显式选休市日 2026-11-15，后续日 K、顶部指数、新闻窗口和图层都以 11-15 为边界。若首屏在 DG 查到的最新目标日 K 是 11-13，则 `quote.tradeDate=2026-11-13`，`dataStatus.expectedTradeDate=2026-11-15`、`observedTradeDate=2026-11-13`、`status=DELAYED`。通过既有交互重试日 K 或单个图层时使用相同的 D。若用户主动刷新整个页面，才允许重新发 page-init 并取新的默认日期。

## 6. 开发顺序和验收清单

| 阶段 | 代码落点及测试 | 完成凭据 |
| --- | --- | --- |
| 1. 日历取数与 Job | §2 的文件及资产。加一个专用隔离回归，例如 `lake_console/orchestrator/tests/test_trade_calendar_update.py`。固定不同年份，断言请求仅有 SSE、字段和分页参数；有效短尾页、整页续请求、重复页、漏日、无效类型、历史缩水、源修订、Raw 已完成后恢复 Silver 均需覆盖。用现有 Job 执行两层及校验，不用仅 materialize 资产代替 | 通过独立项目现有环境的目标 pytest、Ruff，按 §2.3 核对页数、时间、空间和恢复预算。正式一次执行后给出 run ID，两文件对账和三项 check。正式运行需按单独已批准窗口执行 |
| 2. 本地后端读取迁移 | §3、§4 的文件。读层用临时 Parquet，以真实 Raw/Silver 字段构造夹具。覆盖前导零、退市、缺代码、缺列、非法日期、主键重复、开休市和日期范围。用 [`test_wealth_market_page_context_query.py`](../../../../tests/test_wealth_market_page_context_query.py) 扩充 PG/DG 日期对照，固定时钟和 DB 路径对照。每个联表用 PG 只读 SELECT 验证空关系、原 left/inner join、排序、游标和聚合，再用本地真实入口旧表拒绝测试证明没有隐式回读 | 提交一份守卫覆盖清单。按 §4 核对所有读取点，指定 Prod 连接与 PG 写入业务继续通过原回归。DG 证券计数差异、异常记录及有效窗口现场证据可复查 |
| 3. 首屏接口和前端 | §5 的 DTO、组装、App 路由、页面和 hooks。扩充 [股票 HTTP 测试](../../../../tests/web/test_wealth_stock_detail_api.py)、[日 K 集成](../../../../tests/app/technical_indicators/test_stock_daily_integration.py)、[首屏页面测试](../../../src/pages/stock-detail/StockDetailPage.test.tsx)、[新闻面板测试](../../../src/features/stock-detail/news/StockDetailNewsPanel.test.tsx) 和 [ViewModel 测试](../../../src/features/stock-detail/api/stockDetailViewModelAdapter.test.ts)。断言本地初始化和完整首屏都禁止旧因子表，K 线只算一次，延迟、错误、休市、无目标和翻页各有样本。比较末根日 K 与盘口的每个字段，包括 null 与非空单位 | 本地与 Prod 的真实路由合同、OpenAPI、认证和错误包络均通过。Wealth typecheck、定向 Vitest、build 通过，浏览器网络核对无锚点时无日期请求、各请求同一 D、不同锚点下旧响应无法回写 |
| 4. 联调、验收与本地切换 | 真实 DG 有界窗口选在市 `600519.SH`、退市 `600005.SH`、不存在代码、开市和休市，以及 2027 边界。以同一锚点检查日线及辅助字段实际来源，核对分钟/九转和指数原有行为。测量相同请求重复、断开后恢复、两个同到请求，检查名额、连接、事务清理。只读对照 Prod 的已知样本，保持输入和回包的原合同 | 本地两来源替换与首屏同时通过，按阶段记录实际文件、请求参数、计数、耗时和未覆盖场景。有任一依赖差异尚未解释，暂停对应切换 |

阶段 1 的源分页已实测，正式运行窗口和发布验收仍按 §2.3 执行。阶段 2 的证券差异已有核验结论，完整读路径按 §4 验收。首屏 UI 的实现可用隔离数据和明确合同开发。真实整体验收依赖阶段 1、2 的来源就绪。

首屏日 K 预算沿用现有部署设置。默认产品上限 500 根，内核配置可设更低；并行 2、等待 2、排队上限 2 秒、请求总目标 8 秒含 2 秒清理预留，数值见 [Settings](../../../../src/foundation/config/settings.py#L72)。此前一次 DG 两条并发实测为 5.64/5.74 秒，距离 6 秒工作窗口较近。改造后抓取单次、双并发和断开重试的实际响应，分别记录 page-init、日 K、DG 文件读取次数、一次计算、会话清理及重试后的资源归零。先用单代码和限量窗口做验证；失败时定位哪个步骤超预算，保留既有产品和内核阈值。 [历史验收样本](../../../../docs/architecture/technical-indicator-operator-library-implementation-lld-v1.md#L318)

发布时在本地同一构建交付对应的前端与后端合同。暂停或回退时恢复上一套成对的本地构建，按原请求条件验证服务，再修正后续切换。日历文件的后续修复用 §2.3 的逐层核对和 Dagster 入口，数据库迁移及正式数据源的整体回滚不属于本次发布。

## 7. 编码门禁矩阵

逐项对照 [Wealth 模块交付清单](../../system/module-delivery-checklist-v1.md)。本期变更的是已上线页面的取数、响应分工和请求时序。沿用 [股票详情视觉验收基线](stock-detail-figma-pixel-verification-ledger-v1.md)。以下是开工和提测要核对的项目。

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

- **后端真实路由。** 使用现有 Web 测试环境，运行 `python -B -m pytest -q -p no:cacheprovider tests/test_wealth_market_page_context_query.py tests/web/test_wealth_stock_detail_api.py tests/app/technical_indicators/test_stock_daily_integration.py`，测试临时产物按仓库规则放到 `/private/tmp`。在既有 DG、Prod 只读合同样本上分别请求相同日期。本地 init 检查 `pageContext.tradeDate`、证券身份、图表默认项和能力开关，确认省略 `quote/dataStatus`。本地首屏检查 `quote` 的日期和全部价格、量额、方向和股票每日指标，与末根 K 线逐项匹配。检查 `dataStatus` 的预期和实际日期，以及图表消费的 MA、BOLL、MACD、KDJ。旧代码样本在本地返回 `404001`，Prod 保留现行响应。历史页保留区间、排序、状态和根数，且不返回盘口。验证源错误用既有包络，取消、超时和重试后连接及计算名额正常归还。
- **前端页面。** 运行 `npm --prefix wealth run typecheck`、`npm --prefix wealth run test -- src/pages/stock-detail/StockDetailPage.test.tsx src/features/stock-detail/news/StockDetailNewsPanel.test.tsx src/features/stock-detail/api/stockDetailViewModelAdapter.test.ts` 和 `npm --prefix wealth run build`。浏览器连接真实本地接口，确认先有 page-init 回包再有日期请求。按 §5.3 对照网络参数、页面状态和末根日 K 的实际盘口，覆盖退市、空态、旧响应取消和新闻时间边界。Prod 回包夹具用于类型和消费回归，另在 Prod 合同的真实路由上做只读对照。
