# 九转算子及本地股票详情接入 LLD v1

**2026-11-27 Prod股票日线后续设计已确认，待开发。** 管理员确认Prod九转也接算子库，并批准删除旧股票独立日线九转接口及专用查询代码。现行本期设计见[§12](#prod-stock-nine-turn-lld)，方案见[§6](technical-indicator-nine-turn-plan-v1.md#prod-stock-nine-turn-plan)。下方原阶段“Prod不变／无标记数组／保留独立接口”的要求仅适用于原实施阶段，不再限制本次已批准变更；历史验收结果保留，不改写为本次通过。

2026-11-22｜本地股票日线九转已切换，首屏与续页均从算子库取得九转标记。[本机切换后复验](#10-本机切换后复验) · [专项方案](technical-indicator-nine-turn-plan-v1.md)

§1–10 记录日线九转的首期范围、代码和验收。其他股票周期见[股票周月线 LLD](technical-indicator-stock-period-low-level-design-v1.md#stock-period-nine-turn)和[股票分钟线 LLD](technical-indicator-stock-minute-low-level-design-v1.md)。

2026-11-25｜[本地指数日线与分钟九转](#local-index-nine-turn-lld)阶段 1–3 已通过本机隔离验收，待切换常用本地服务。

## 1. 现状和改动边界

本专项开始前，本地股票详情先取 `/kline`，再在首批和每次续页请求 `/nine-turn`。后者用股票日 K 日期匹配 PostgreSQL `core_serving.equity_qfq_nineturn_daily` 的预计算结果。DG 原始九转算法保留连续计数，页面组装只生成 1–9 标记。原有 `/kline` 已一次计算日 K 和各个日线指标，输入会话统一准备复权收盘价。[日线九转取数](../../src/biz/queries/wealth/market/stock_nine_turn/stock_nine_turn_query.py#L57) · [本地日 K 调用](../../src/app/dependencies/stock_daily_technical_indicators.py#L183) · [首批及续页调用方](../../wealth/src/pages/stock-detail/StockDetailPage.tsx#L94)

本期新增日线 `nineturn` 算子，并把它接入本地股票详情的首批和续页。技术指标算子库的请求格式、数据源配置和数值输出格式沿用原合同。股票分钟、指数详情、Prod 股票详情及未切换的独立九转请求保持原行为。共同依赖只复用现有行情与执行接口，算子库无需依赖 DG 工程。DG 的生成与同步代码、数据文件、数据库表及部署配置均保持现行版本。

## 2. 算子接口与批次实现

### 2.1 注册和结果字段

新增 `packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/nine_turn.py`，在 [内置注册入口](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/__init__.py#L4) 冻结前注册。复用 `CalculationDefinition`、`Calculation`、`CalculationSession` 和 `CalculationOutput`。[算子定义与接口](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/calculation.py#L53)

```python
# 算子名称、算法版本和固定输入输出。
DEFINITION = CalculationDefinition(
    calculation_id="nineturn",
    algorithm_version="1.0.0",
    description="比较前第 4 根收盘价的连续九转计数，最高为 13",
    parameter_specs=(),
    input_fields=frozenset({"close"}),
    output_fields=(
        OutputField("up_count", "up_count", "DOUBLE", False, "无可比较的收盘价时为 0"),
        OutputField("down_count", "down_count", "DOUBLE", False, "无可比较的收盘价时为 0"),
    ),
    initialization="行情起点方向和计数均为 0",
    history_rule="首根目标前最多 16 根，批次之间保留前 4 根收盘价",
    units=(("up_count", "count"), ("down_count", "count")),
    supported_periods=("day",),
    public=True,
)
```

调用方在现有 `CalculationRequest.calculations` 放入 `{"calculation_id": "nineturn", "parameters": {}}`。返回的 `times` 与两个计数数组逐项对齐。收集器用 `DOUBLE` 输出，实际计数始终取整数值 0–13。注册说明按周期与运行环境已启用来源取交集，日线首期配置可用于股票原价日线、股票前复权日线和指数原价日线。日线首期的周期校验拒绝分钟、周线和月线。固定比较间隔和计数上限不作为参数开放。[注册能力查询](../../packages/technical_indicators/src/goldenshare_technical_indicators/discovery/catalog.py#L32) · [已启用来源](../../src/app/runtime/technical_indicators/composition.py#L34) · [周期和参数校验](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/dependencies.py#L41)

### 2.2 类、状态和 SQL

```python
@dataclass(frozen=True, slots=True)
class NineTurnCalculation:
    parameters: Parameters  # 工厂传入的已校验空元组。

    SQL_PACKAGE: ClassVar[str] = "goldenshare_technical_indicators.calculation"
    TABLE_ROLES: ClassVar = MappingProxyType({
        "state": ("ti_nineturn_state", "state"),
        "output": ("ti_nineturn_output", "batch"),
    })
    SQL_FILES: ClassVar[tuple[str, ...]] = ("nineturn_batch.sql",)
    FIXED_SQL_STEPS: ClassVar  # create_state、initialize_state、update_state。

    def input_requirement(self, session: CalculationSession, max_input_rows: int) -> HistoryRequirement:
        # close，跨批保留 4 根，单独计算预热 16 根，无需读到历史起点。
        ...

    def dependencies(self) -> tuple[Dependency, ...]:
        # 无其他指标依赖。
        ...

    def prepare(self, session: CalculationSession) -> None:
        # 登记本请求的状态表，写入方向 0、计数 0。
        ...

    def consume(self, batch: PriceBatch, session: CalculationSession) -> CalculationOutput:
        # 计算并返回本批新行。用本批末行更新状态。
        ...

    def release_batch(self, session: CalculationSession) -> None:
        # 只释放本批输出表。
        ...

    def release(self, session: CalculationSession) -> None:
        # 用引擎的清理模式释放剩余输出表和本节点状态表。
        ...
```

`input_requirement()` 返回 `HistoryRequirement(frozenset({"close"}), 4, 16, False, ("direction", "count"), DEFINITION.initialization)`。九转跨批只依赖前 4 根已处理的收盘价。多个指标同算时，输入会话仍按各算子的最大窗口保留行情。九转的方向及计数放在本请求节点的单行临时表 `state(direction INTEGER, count INTEGER)`。同一请求不同节点的表名由引擎追加节点编号。释放批次只删输出表，整次结束后释放状态。处理中断或发生错误沿用引擎清理。[已有状态与清理做法](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/kdj.py#L78) · [现有行情批次管理](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L280)

新增 `calculation/sql/nineturn_batch.sql` 并加入 [SQL 资源白名单](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/sql_templates.py#L18)。资源已由 [包配置](../../packages/technical_indicators/pyproject.toml) 的 SQL 模式包含。SQL 仅操作本次请求的共享行情和自有临时表。

1. 对共享行情表按 `seq` 做 `LAG(close, 4)`。本批的前置重叠行要参与 `LAG`，比较结束后再按 `new_first_seq` 到 `new_last_seq` 过滤。两个边界由 `SqlStep.bindings` 绑定。每个新行按比较结果生成方向 `1`、`-1` 或 `0`。
2. 在本批新行内按方向切段。第一行、方向变化或相等归零处开始一个新段，使用段内 `ROW_NUMBER()` 取得局部计数。本批第一段方向与上批末行方向相同且非零时，加上状态表的 `count`。方向为 0 时计数归零。最后用 `LEAST(count, 13)` 封顶。
3. 按 `seq BIGINT, up_count DOUBLE, down_count DOUBLE` 建本批输出表。只有本批新行进入输出表，方向相反的一列填 0。用输出表内最大 `seq` 的一行回写状态方向和计数。`CalculationOutput` 声明相同的新行边界，公共收集器再按目标区间截取输出。预热的新行同样更新状态，但不会出现在最终结果。

`create_state` 和 `initialize_state` 负责一次性状态初始化。主文件对应 SQL 步骤 `nineturn_batch`，用固定表名角色 `price`、`state`、`output`，声明读取行情表和状态表，写入本批输出表。最后 `update_state` 声明读取本批输出表以及读写状态表，从本批输出表末行更新单行状态。每批最多产生与新行一样多的结果。取到已有的上一批状态后，下一批只需保留前 4 根收盘价。每次新请求由读取模块按合并后的历史需求取数，单算九转时最多额外取 16 根。

## 3. 股票日 K 后端接入

### 3.1 计算请求和结果映射

- 在 [日 K 计算指令构造](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_calculations.py) 保留 `STOCK_DAILY_CALCULATIONS` 原有 11 项，定义固定九转请求项及对应版本、结果字段。在该模块增加 `stock_daily_calculations(*, include_nine_turn: bool)` 返回本次期望项，并在 `build_calculation_request(source, *, include_nine_turn: bool = False)` 使用它。
- [本地日 K 后端](../../src/app/dependencies/stock_daily_technical_indicators.py#L183) 复用 `paginated` 作为 `include_nine_turn` 的值。`paginated` 要求本地 DG、显式 `tradeDate/endDate`、`endDate <= tradeDate` 且无 `startDate`。因此本地首批、续页各只有一次 `calculate()`。Prod 和普通日 K 调用继续使用原来的 11 项。`StockDailyKlineAppBackend.__init__` 只在 DG 装配时将九转加入现有注册版本校验。业务查询已有的日期、昨收和每日指标沿用原入口。
- [日 K 结果组装](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py#L55) 的 `_validate_result(source, result, *, include_nine_turn: bool = False)` 使用同一 `stock_daily_calculations()`。`assemble()` 从现有 `paginated` 参数传入，由日 K 时间位置对齐两列计数。计数值须在 0–13 内且为整数值，两个方向不能同时大于 0，校验后再转 `int`。字段缺失、空值或错位沿用 `OutputContractError` 处理。
- 在 [现有九转标记规则](../../src/biz/services/wealth/market/nine_turn/nine_turn_response_policy.py#L82) 抽出 `build_nine_turn_marker(*, trade_date: date, trade_time: datetime | None, up_count: int, down_count: int) -> NineTurnMarkerDto | None`。已有 `_marker_from_row()` 继续负责匹配和数据库整数读取，再调用该组装函数。日 K 组装使用同一函数并传 `trade_time=None`。规则和原有行为一致，两个方向计数都不在 1–9 时返回空，9 使用完成标记。分钟时间的校验与时区转换继续只在生成标记时执行。旧入口仍接受大于 13 的数据集整数计数，它们在图上留空。

### 3.2 HTTP 回包

```python
class LocalStockDetailPagedKlineResponseDto(StockDetailKlineResponseDto):
    meta: LocalStockKlineMetaDto  # 包含现有 nextEndDate。
    nineTurnMarkers: list[NineTurnMarkerDto]  # 新增，必有，允许空列表。


class LocalStockDetailFirstKlineResponseDto(LocalStockDetailPagedKlineResponseDto):
    quote: StockQuoteSnapshotDto | None  # 沿用现有首批盘口。
```

在 [现有回包类型](../../src/biz/schemas/wealth/market/stock_detail.py#L212) 只给本地分页 DTO 加字段。各标记使用现有 `tradeDate`、`tradeTime`、`direction`、`sequenceNumber`、`completed`，按本批日 K 日期升序返回。日线的 `tradeTime` 为 `null`。有行情且无标记、以及既有的合法空日 K 回包，均须提供 `nineTurnMarkers: []`。计算只在有目标行情时发起。`/page-init`、原 `StockDetailKlineResponseDto`、Prod 的 OpenAPI、已有请求参数及 `nextEndDate` 均照旧。`/nine-turn` 和 `/minute-nine-turn` 沿用原回包。[路由的 DTO 分派](../../src/biz/api/wealth/market/stock_detail.py#L91) · [九转标记 DTO](../../src/biz/schemas/wealth/market/nine_turn.py#L16)

以已有的贵州茅台翻页样本为例，首批的 `tradeDate` 和 `endDate` 都是 `2026-11-19`，回包有盘口和该批标记。续页保持 `tradeDate=2026-11-19`，将首批 `nextEndDate=2024-10-29` 作为 `endDate`，回包含续页标记并省略盘口。[已有两批日 K 的真实日期](../../wealth/docs/pages/stock-detail/stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#本机切换后复验)

## 4. 本地股票前端接入

1. [股票日 K 前端 DTO](../../wealth/src/features/stock-detail/api/stockDetailApiTypes.ts) 新增 `nineTurnMarkers?: NineTurnMarkerDto[]`。共用前端需要同时读取原普通或 Prod 回包，因此类型为可选。本地首批及本地续页代码按各自既有的本地条件，要求该字段是数组，空数组表示合法结果。前后端使用同次构建切换。
2. [股票详情页](../../wealth/src/pages/stock-detail/StockDetailPage.tsx#L94) 的 `StockDetailLoad` 增加可选 `dailyNineTurnLayer: NineTurnLayerViewModel`。沿用首批已有的本地判断 `!("quote" in pageInit)`，在判断日 K 空态前验证本地标记字段是数组，类型错误沿用首屏请求错误。由 [视图模型适配器](../../wealth/src/features/stock-detail/api/stockDetailViewModelAdapter.ts) 新增 `buildStockDailyNineTurnLayer(markers)` 供首批成功时保存图层。有标记为 `READY`，并令 `message=null`。无标记为 `EMPTY`，空态沿用「当前窗口暂无九转标记」。`period="day"`，`data=null`，`errorCode=null`，`canRetry=false`。本地日线直接选该图层，`ensure("day")` 与九转重试回调均跳过独立请求。分钟和 Prod 继续使用原有 `useNineTurnSeriesRegistry`。切股、切日期和迟到回包使用 `requestKey` 与现有取消逻辑。
3. [本地续页控制](../../wealth/src/features/stock-detail/controller/useStockDailyHistory.ts#L95) 从 `payload` 读取本批 `nineTurnMarkers`，与身份、日期、游标一起验证，通过后再更新 `nextEndDate`、已加载的图和批次列表，空批也必须有标记数组。将 `HistoryPage.nineTurn` 的独立请求状态换成 `nineTurnMarkers: readonly NineTurnMarkerDto[]`。只保留 `trend` 的独立加载状态及重试，删除此处日线九转 API 请求、`supportsNineTurn` 和九转独立重试分支。日 K 续页失败保留已有图表、盘口、页面日期和本批游标。用户下次向左拖按原逻辑重试同一个截止日。
4. [日 K 图表](../../wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx#L67) 按已加载日 K 日期合并首批和续页标记，沿用已有 `useNineTurnChartLayer` 定位。合并后任何一批有标记时为 `READY`，因此首批无标记、续页有标记时不会继续显示空提示。沿用九转开关和 9 的样式，开关只控制显示。趋势通道错误仍单独显示和重试。Prod 原日线九转图层的状态与重试沿用原路径。[图层状态与提示](../../wealth/src/features/nine-turn/model/nineTurnTypes.ts) · [标记绘制](../../wealth/src/features/nine-turn/controller/useNineTurnChartLayer.ts)

## 5. 预算与恢复

- 单独请求九转时，交付给算子的行情最多是目标根数 `T` 加 16，默认最多 516 根，历史短时以实际根数为准。股票详情默认请求 500 根并同算现有指标，股票现有 MACD、KDJ 默认参数的预热需求都是 500 根。历史充足时同页输入仍是 1000 根，九转不增加这次请求所需的源行情、复权因子范围或复权次数。这里的根数指输入会话交付的 K 线，文件投影、定位和磁盘读量单独记录。[历史合并](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/history.py#L38) · [现有预算](technical-indicator-operator-library-implementation-lld-v1.md#7-预算停止和重试)
- 维持现有默认 8,192 根输入批次。在默认股票详情样本中，1000 根可作为一批交付。跨多个批次时每批九转读取本次共享窗口，并保持一个状态行。主计算 SQL 的 `processed_rows` 按 `batch.new_row_count + batch.history_rows + 1` 记录共享窗口及状态行，状态回写单独按本批输出根数和一个状态行计量。这是逻辑处理量。九转最多在 HTTP 回包添加 `T` 个标记，默认上限 500，实际以本批有标记的日期为准。当前日 K 指令由 11 项增至 12 项，默认算子请求项上限为 16。[现有设置](../../src/foundation/config/settings.py#L85)
- 沿用现有请求期限和清理预算。默认总目标 8 秒，清理预留 2 秒。500 根首批和续页分别对照同一正式 DG 样本的现有用时。已记录的常用本地服务贵州茅台两页为 4.738 秒、3.769 秒，属于历史实测。开发验收重新记录用时、`source_rows`、文件数、复权批次数、SQL 处理行、回包大小及浏览器请求数。九转与已有指标合算的读量和复权次数对比同一输入的原指令。现有时限内失败应定位实际开销。[既有本机验收记录](../../wealth/docs/pages/stock-detail/stock-detail-first-screen-and-local-dg-read-low-level-design-v1.md#本机切换后复验)
- 取消或异常后由现有输入会话、引擎、并发许可清理。九转状态仅在本次计算中有效。重试预算按同批的完整读取、计算与清理重新计量。验收固定同一股票，按第 6 节跑首批、续页和一次中断后的同页重试。以每次有足够历史、耗用完整输入范围计算，三个成功请求合计最多交付 3000 根行情给内核，另记录中断请求在取消前已实际处理的量。两环境的正式数据只读，计算不发布任何数据。

## 6. 验收与开发文件

| 阶段 | 验收与证据位置 |
| --- | --- |
| 1. 算子注册和基础值 | 新增 `tests/foundation/technical_indicators/test_nine_turn_calculation.py`。走 `TechnicalIndicatorService.calculate()` 验证公开注册、日线支持、拒绝非空参数和非日线、每个日期两个结果字段。用现有配置测试验证股票前复权、股票原价和指数原价日线能力的枚举。 |
| 1. 数值边界 | 用独立字面预期测试前 4 根为零、严格方向、相等归零、达到 9 后继续、达到 13 后保持、换向重启。用收盘价 `0,1,…,16` 与 `4,1,…,16` 对照最后一根分别为 13 和 12，两者最近 15 根历史加当前根相同。整段和从中间请求比对重叠结果。用 1 根、能让 9 和 13 落在跨批边界的分批、一次整批三组验证 `LAG` 与封顶状态。覆盖预热输出被截去及同请求与 MA、MACD、KDJ 合算。 |
| 1. 正式来源只读 | 从本地正式 DG 取 `600519.SH` 的一个有界前复权日线区间，用同一份实际前复权收盘价核对独立九转预期。复用 [DG 公式覆盖到 10 的用例](../../lake_console/orchestrator/tests/test_nineturn_formula.py#L69)，增加封顶独立预期。在相同输入上比对 DG 全计数的 `min(count, 13)`，按请求 `times` 对齐。另用已启用的股票原价和上证指数原价日线各一组有界日线请求验证公开能力。 |
| 2. 后端合同 | 扩充 [日 K 组装测试](../../tests/test_stock_daily_kline_service.py) 与[真实路由隔离测试](../../tests/app/technical_indicators/test_stock_daily_source_repair.py)。覆盖首批有盘口、续页无盘口、`nineTurnMarkers` 顺序、0 与 10–13 不画、空列表、非法结果按现有错误返回。旧 PG 九转结果表在本地日 K 验收中设为不可读，断言首批和续页仍各完成一次算子计算。Prod 和本地普通日 K 回包无新字段，未选九转计算。旧日线及分钟九转的 HTTP 与原标记规则继续回归。 |
| 2. 前端与浏览器 | 扩充 [股票详情页测试](../../wealth/src/pages/stock-detail/StockDetailPage.test.tsx)、[续页 Hook 测试](../../wealth/src/features/stock-detail/controller/useStockDailyHistory.test.tsx)与[日 K 图表测试](../../wealth/src/features/stock-detail/chart/StockChartWorkspace.test.tsx)。正向断言首批、续页、切股和首批无标记、续页出现标记。负向断言本地日线打开、向左拖和开关九转均不请求 `/nine-turn`。覆盖标记字段缺失时续页保留已有图和盘口且重试同一个截止日。保留分钟与 Prod 原请求测试、趋势通道独立重试。执行 Wealth 类型检查、相关 Vitest 和构建。用实际本地接口与浏览器完成 500 根首批和 500 根续页，再核对分钟和上证综指原行为。 |

本机切换前检查同一构建的前后端，以 `600519.SH`、页面日期 `2026-11-19` 复用已有首批/续页日期范围。保留上一套本地构建以便成对恢复。完成真实验收后，再更新股票详情字段来源表中的现行九转路径。

## 7. 开工前独立审计

**2026-11-22 审计结论。方案与 LLD 口径一致，可以从第 1 阶段开始。** 对照整体算子库设计、现行股票日 K 和九转入口、现有页面及测试，确认读取、复权、预热、日 K 组装和图表的改动位置。正式 DG 数据与本地浏览器的验收在开发后执行。

- **算子库。** 用 CodeGraph `codegraph_explore` 核对注册、预热合并、共享行情、SQL 会话和结果收集，再逐项核对源码。确认九转只需新增算子及 SQL 注册，沿用现有程序准备的收盘价。按 §2 的步骤在内存 DuckDB 验证分段 SQL，以独立的逐根向前计数作参照，116 组整段、切片及分批组合一致。另验证 13 与 12 的样本最近 15 根历史完全相同，最早的第 16 根会改变结果。这次验证使用小样本 SQL，正式算子及 DG 接入在第 1 阶段验收。
- **后端与前端。** 核实 `paginated` 覆盖本地首批和续页。浏览器首批与续页目前分别调用独立的日线九转接口，接入时两个调用点都要切换。复核后明确续页先验标记字段再推进游标，避免失败后错过本批，并补上首批无标记、续页出现标记的显示用例。普通日 K 和 Prod 继续适用原回包，相关既有分支保留。
- **现有回归。** 算子注册与输出、股票日 K 组装及隔离路由共 68 项通过。股票详情页、历史续页和日 K 图表共 33 项通过。后端回归通过 `PYTHONPATH` 使用仓库里的算子库源码，与现有本地启动脚本一致。两组回归均针对当前代码，现有行为符合本专项的接入前提。[本地启动脚本使用的源码路径](../../scripts/local-build-and-run.sh#L219)

## 8. 阶段 1 实施与独立审计

**2026-11-22 审计通过。** 阶段 1 的变更限于算子及其注册、SQL 资源清单和测试。用 CodeGraph `codegraph_explore` 核对注册至输出的共享调用链，再检查实际实现和测试。新算子只读取共享收盘价，两列计数随 `times` 对齐，状态随当前请求清理。股票详情的业务接入和浏览器验收在阶段 2 执行。[九转算子](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/nine_turn.py) · [批次计算 SQL](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/sql/nineturn_batch.sql)

| 方案要求 | 实施审计结果 |
| --- | --- |
| 日线算子合同与封顶 | `nineturn` v1.0.0 无可调参数，公开股票原价、股票前复权及指数原价日线。验证分钟、周、月都被拒绝。按字面预期核对前 4 根、相等清零、换向、连续计数越过 9 和在 13 封顶。 |
| 预热与分批 | 独立请求额外读取最多 16 根实际日 K，预热行不会出现在输出。保持最近 15 根历史相同，只改第 16 根，首根结果由 13 变为 12。按 1、12、16、64 根分批验证结果，同段日期计数逐根一致。取消用例在生成一批输出后中断，确认状态表和输出表都释放，重试从头计算。 |
| 正式 DG 有界只读 | 贵州茅台 `600519.SH` 前复权日线从 2026-10-26 至 11-19 返回 19 根，交付 35 根含 16 根预热。用同一份前复权收盘价和 DG 原始公式对照，两列计数封顶后 19 个日期逐根一致。整批、每批 12 根和单算最后 2 根的重叠输出也一致。贵州茅台与上证综指 `000001.SH` 的不复权九转各核对 3 根。 |
| 与原日 K 指令共用行情和复权 | 同一贵州茅台前复权请求，返回 11-18 和 11-19 两根日 K。加入九转前后均交付 502 根行情，库统计文件数均为 1,509，复权各 1 次，原 11 项计算结果一致。逻辑 SQL 处理量从 21,649 行增至 23,662 行，两次样本耗时分别约 3.35 秒和 2.06 秒。此处只记录单次观测，阶段 2 验现有 500 根页面请求。 |

算子库和股票日 K 相关回归共 337 项通过，含 13 项新增九转用例及 SQL 资源核对。相邻的 DG 指数周月线回归 12 项通过，DG 原九转公式隔离测试 5 项通过。更大范围试跑中，12 个旧测试文件仍引用已移除的 `CalculationInstance`，已用变更前的 `c59bd35d6` 复现。另有 11 个指数周月线数据库用例在隔离 PostgreSQL 监听端口时被执行环境拦下，未进入断言。阶段 1 结论依据本节专项回归和 DG 只读核验。[九转专项测试](../../tests/foundation/technical_indicators/test_nine_turn_calculation.py) · [SQL 资源核对](../../tests/architecture/test_technical_indicator_dependencies.py#L62)

## 9. 阶段 2 实施与独立审计

**2026-11-22 隔离本机验收通过。** 浏览器运行同一轮构建的 Wealth 前端。实际股票日 K、趋势通道、股票分钟和上证综指日线接口读取正式 DG，登录、自选和顶部指数条使用隔离数据。当时常用本机服务尚未切换。用 CodeGraph `codegraph_explore` 核对本地日 K 调用、合同、首屏和续页的消费端。复查实际组装确认只有本地分页分支请求九转，Prod 与普通本地日 K 使用原合同。无标记时回包为 `nineTurnMarkers: []`。[本地日 K 调用](../../src/app/dependencies/stock_daily_technical_indicators.py#L183) · [结果校验与组装](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py#L56)

| 场景 | 贵州茅台 `600519.SH` 实测 |
| --- | --- |
| 首屏 | `/page-init` 确定页面日期 2026-11-19。日 K 回包 500 根，覆盖 2024-10-30 至 2026-11-19，含 452 个九转标记和盘口。盘口收盘价 1460.21 元，与末根日 K 一致。HTTP 约 4.95 秒，回包 383,664 字节。 |
| 向左翻页 | 拖动触发一次续页，带原页面日期 2026-11-19，并以 `nextEndDate=2024-10-29` 为截止日。返回 2022-09-30 至 2024-10-29 的 500 根和 453 个九转标记，省略盘口，下一批截止日为 2022-09-29。浏览器在 2024-07-18 的行情区核到九转标记仍可绘制，右侧盘口保持 1460.21 元。HTTP 约 4.90 秒，回包 389,568 字节。 |
| 请求与资源 | 打开、拖动和开关九转共触发两次日 K 请求、零次独立日线九转请求。每次日 K 调用只计算一次，含 12 项，交付 1,000 根含预热行情，复权 1 次。每次库统计文件数为 3,003，逻辑 SQL 处理 48,571 行。两页九转日期各与该页日 K 逐日匹配，浏览器无脚本和控制台错误。 |
| 断开与重试 | 客户端断开已取得名额的续页请求，约 52 毫秒后观察到占用、等待均归零。补测同一中断点时，取消前交付给算子的行情为 0 根。同一截止日重试约 5.43 秒返回 500 根，九转标记和分页信息与前次成功回包一致。 |
| 其他入口 | 趋势通道两批独立请求均通过。切 30 分钟后，分钟行情、指标和独立九转三个原接口均返回 200。实际本地上证综指日线仍返回 500 根。核对本地与 Prod 配置生成的 OpenAPI，新增必填数组仅在本地首批和续页模型，两个环境的日 K 请求参数一致。 |

后端 59 项、前端专项 50 项及共享图表 44 项回归通过，Wealth 类型检查和隔离构建通过。覆盖旧独立九转、普通本地日 K、空标记、非法算子结果、迟到请求以及续页缺字段后重试原截止日。隔离验收之后的实际运行情况见[本机切换后复验](#10-本机切换后复验)。

## 10. 本机切换后复验

2026-11-22｜常用本机服务的股票日 K 已返回九转标记。浏览器仍加载 2026-11-20 生成的 Wealth 静态前端，实测会继续请求独立日线九转。常用的 `scripts/local-build-and-run.sh` 构建的是 `frontend`，股票详情页由本机 Web 的 `/wealth` 提供，读取 `wealth/dist`。Wealth 的构建命令为 `npm --prefix wealth run build`。本次在临时目录用已提交的代码构建 Wealth，避免带入工作区的其他修改。构建通过后先复制带内容指纹的静态资源，再切换 `index.html`，保留浏览器已加载页面引用的旧资源。随后在同一服务复验股票日线首屏、九转开关和向左翻页。[Wealth 静态资源入口](../../src/app/web/app.py) · [本机启动脚本](../../scripts/local-build-and-run.sh)

构建和类型检查通过。浏览器实际加载 `/wealth/assets/index-YQ2DMgaX.js`。以贵州茅台 `600519.SH` 复验，`/page-init` 返回的页面日期为 2026-11-19，两次 `/kline` 请求都保留该日期，股票接口读取正式本地 DG。登录、自选和顶部指数条使用隔离数据。

| 场景 | 常用本机服务实测 |
| --- | --- |
| 首屏 | `endDate=2026-11-19`，返回 2024-10-30 至 2026-11-19 的 500 根日 K 和 452 个九转标记。首批盘口收盘价为 1460.21 元，与末根日 K 相同。 |
| 向左翻页 | `endDate=2024-10-29`，取自首批的 `meta.nextEndDate`。返回 2022-09-30 至 2024-10-29 的 500 根日 K 和 453 个九转标记，省略盘口，下一批截止日为 2022-09-29。浏览器拖到 2024-10-22 所在区间，核到历史九转标记仍可绘制，右侧盘口保持 1460.21 元。 |
| 九转显示与请求 | 两批的标记逐日对应各自的 K 线。九转开关隐藏和恢复绘制，打开首屏、向左翻页和切换九转共触发两次 `/kline`，独立 `/nine-turn` 请求为零。切换后浏览器验收无脚本和控制台错误。 |

首次浏览器探测在切换 Wealth 前收到过一次日 K HTTP 500，响应无具体原因。随后直接请求首批和续页均返回 200，使用新前端复验两批也均返回 200。股票详情来源主表已按切换后的实际行为更新。[本地股票日线九转字段](../../wealth/docs/pages/stock-detail/stock-detail-field-source-audit-v1.html#local-daily-nine-turn)


<a id="local-index-nine-turn-lld"></a>

## 11. 本地指数日线和分钟线九转

2026-11-25｜阶段 1–3 已通过本机隔离验收。对应[方案 §5](technical-indicator-nine-turn-plan-v1.md#local-index-nine-turn-plan)。本节沿用 §2 的计算、预热和结果合同，补齐本地指数的接入。现行指数日 K、分钟取数及分页的实现与实测见[指数详情 LLD §28–29](../../wealth/docs/pages/index-detail/index-detail-low-level-design-v1.md#local-index-daily-library-expansion-lld)。

### 11.1 阶段 1｜为本地指数分钟启用九转算子

- [九转定义](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/nine_turn.py)继续使用 `NineTurnCalculation`。为 DG 运行时的定义追加 `("index", "<频率>m", "none")`，频率为 5、15、30、60、90、120。保留既有日线及股票组合。`index` 的 1 分钟、周线和月线继续按现有不支持规则处理。
- 在[内置注册装配](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/__init__.py)给 `create_builtin_registry` 增加可选关键字 `enable_index_minute_nine_turn: bool = False`。启用时只替换九转定义的 `additional_sources`，共用原工厂、版本、参数和 SQL。[运行时装配](../../src/app/runtime/technical_indicators/composition.py)按现有 `config.data_location == "dg"` 传入。这样 Prod 既有 5 分钟来源不会因共用注册表获得新的九转能力。默认注册行为、通用请求字段和环境设置照旧。
- 日线复用 `index_daily` 的 `silver/index_daily` 普通日线。分钟调用现有 `TechnicalIndicatorService.calculate_index_minutes_recent(request, output_limit=MAX_INDEX_MINUTE_LIMIT)`，按 `DG_RECENT_INDEX_MINUTE_DATASETS` 解析。5、15、30、60 分钟都是正式 DG `gold/quote/major_index_mins` 的同频不复权行情。90／120 分钟分别取 `silver/quote/major_index_mins` 的 `30min`／`60min` 分区，沿用现有 SQL 合成后才向算子交付。 [数据集位置](../../packages/technical_indicators/src/goldenshare_technical_indicators/configuration/datasets.py) · [分钟读取及合成 SQL](../../src/foundation/clients/technical_indicator_index_minutes.py)
- 业务传 `security_type="index"`、指数代码、周期、`adjustment="none"`、现有时间上下界和 `latest_rows=limit`，计算项为 `{"calculation_id": "nineturn", "parameters": {}}`。截止时间使用上海时区。用现有读取模块按行情时间、根数和历史需求批量读文件。九转与同次请求中的其他算子共用这批行情。单独计算最多额外需要 16 根目标周期 K 线；同批计算取已有指标各自预热需求的最大值。90／120 分钟的 16 根指合成后的根数。已有读数、合成、单位换算、预热规则和 `nineturn_batch.sql` 均直接复用。

### 11.2 阶段 2｜日 K 回包带九转

1. **后端。** [`run_index_daily_kline`](../../src/app/dependencies/index_daily_technical_indicators.py)只在 DG 的 `_DG_CALCULATIONS` 增加九转。[日 K 查询服务](../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py)的 `_build_recent_daily_kline` 从结果按 `calculation_id` 取 `price`、`nineturn`，以余下原计算实例调用 `apply_calculated_kline_factors`。该校验按原清单执行。以已核对的 `result.times` 对齐两列计数和 `target_bars`，按 §3.1 校验并转成整数，调用 `build_nine_turn_marker(trade_date=day, trade_time=None, ...)`。每个日期最多一枚标记。指标和九转都随这一次计算返回，目标为空沿用原日 K 空页流程。
2. **HTTP。** 在[普通日 K DTO](../../src/biz/schemas/wealth/market/index_detail.py)增加 `LocalIndexDetailDailyKlineResponseDto(IndexDetailKlineResponseDto)`，字段 `nineTurnMarkers: list[NineTurnMarkerDto]` 必有，合法空页或没有 1–9 标记时为 `[]`。在[调试 DTO](../../src/biz/schemas/wealth/market/index_detail_debug.py)及[`kline_response`](../../src/biz/queries/wealth/market/index_detail/debug_response.py)增加相应的本地日线投影，声明同一字段并保留诊断内容。普通、调试的本地路由各声明对应 DTO，Prod 和周月线继续用原类型。请求 `GET /index-detail/kline` 仍用原来的 `tsCode, period=day, startDate, endDate, limit`，首屏和向左翻页显式传 `limit=500`。返回现有 `meta.nextEndDate`。本地九转计算或结果错误走原日 K 错误，续页失败保留已显示行情并重试原截止日。独立日线 `/nine-turn` 继续服务 Prod 和现有接口调用。
3. **前端。** 在[`indexDetailApiTypes.ts`](../../wealth/src/features/index-detail/api/indexDetailApiTypes.ts)声明本地日 K 字段；共用调用侧用回包中的数组识别内嵌九转，`[]` 同样识别成功，Prod 回包走原独立查询。[`useIndexDetailController`](../../wealth/src/features/index-detail/controller/useIndexDetailController.ts)保存首批，[`useIndexDailyHistory`](../../wealth/src/features/index-detail/controller/useIndexDailyHistory.ts)随每批日 K 保存标记，按现有历史页显示时机接到图上。首屏已有该字段时，续页也须包含数组，失败时游标保留。[`IndexDetailPageView`](../../wealth/src/pages/index-detail/IndexDetailPageView.tsx)以本地回包给日线图和技术面摘要提供标记，本地成功链路跳过 `ensure("day")` 和续页九转独立请求。摘要显示首批最后一根 K 线对应的标记；当天没有标记时显示空，向左翻页不回写摘要。复用既有图层开关及时间位置，无需前端计算计数。

### 11.3 阶段 3｜分钟行情带九转，技术面也从算子取

1. **共用读取。** [`IndexMinuteCalculationReader`](../../src/biz/queries/wealth/market/index_detail_minutes/index_minute_calculation_reader.py)给 `read_bars(request)` 的计算清单按现有六档追加 `nineturn`，复用 `price` 的时间轴，`_result_columns` 增加两列计数。提供同类的 `read_nine_turn(request)` 供摘要查询，只提交九转计算项。两者使用同一个按根数及时间边界的读取过程。保留 `read_indicators(request)` 与现有独立常用指标的加载及失败行为。对 `899050.BJ` 沿用现有分钟空结果分支，在调用读取器前返回。[原分钟查询服务](../../src/biz/queries/wealth/market/index_detail_minutes/index_detail_minutes_query_service.py)
2. **同批组装。** `IndexMinutesResponseDto` 增加必有的 `nineTurn: NineTurnSeriesDto | None`。5、15、30、60、90、120 分钟时，[分钟查询服务](../../src/biz/queries/wealth/market/index_detail_minutes/index_detail_minutes_query_service.py)从同批返回行组装 `nineTurn`。沿用[共享组装函数](../../src/biz/services/wealth/market/nine_turn/nine_turn_response_policy.py) `build_nine_turn_response` 和现有股票分钟的组装方式。每根的键为 `tradeDate, tradeTime`，分钟时间带 `+08:00`。有行情时 `sourceRowCount == matchedRowCount == count`、`missingRowCount=0`，零计数也算匹配。合法空页是九转 `EMPTY`。1 分钟为 `nineTurn: null`。图表九转异常沿用 `/minutes` 的读取／计算错误，对同一窗口重试。常用指标请求失败时，已返回的 K 线和九转可继续显示。
3. **独立摘要接口。** 在 [App 分钟装配](../../src/app/dependencies/index_minute_technical_indicators.py)把 `/minute-nine-turn` 接到同一算子运行时和 `IndexMinuteCalculationReader.read_nine_turn`。[API 路由](../../src/biz/api/wealth/market/index_detail_minute_nine_turn.py)参照现有股票分钟九转的异步装配，沿用鉴权、七个请求字段、`NineTurnSeriesDto` 及已发布的 `NT_*` 错误码。[查询服务](../../src/biz/queries/wealth/market/index_minute_nine_turn/index_minute_nine_turn_query_service.py)复用上一项的分钟结果组装。省略截止日时仍读取最新已发布行情，并按原独立接口规则用本地当天生成九转状态。诊断只打印实际行情来源、文件数和耗时。运行链改为依赖现有指数分钟行情就绪条件，[路由注册](../../src/app/api/v1/router.py)与 [page-init 能力](../../src/biz/queries/wealth/market/index_detail/index_detail_page_query_service.py)共用该条件。移除生产代码对 DG 主要指数分钟九转成品目录的就绪判断和读取器装配，复用现有环境配置。保留已开放的指数及周期范围。
4. **请求与游标。** `/minutes` 和 `/minute-nine-turn` 都沿用 `tsCode, freq, startDate, endDate, limit, cursor`，独立九转继续允许 `debug`。默认 500 根、参数上限 10,000。行情顶层游标仍为现有 bars v1；独立九转和同批 `nineTurn.meta` 使用 [原九转游标编解码](../../src/foundation/clients/local_lake/nine_turn_minute_contract.py)及 `dataset="index_minute_nine_turn"`。沿用 `tsCode/freq/startDate/endDate` 绑定，算子结束时间取原截止与游标首根之前 1 微秒的较早值。下一页游标来自内核 `has_more` 和实际返回首根。页面继续在已取的分钟范围内移动；游标兼容在接口层验收。
5. **页面调用。** [`useIndexMinuteSeries`](../../wealth/src/features/index-detail/controller/useIndexMinuteSeries.ts)把 `/minutes` 内的九转随当前指数、周期、日期一同缓存，再由 `adaptNineTurnSeries` 交给分钟图。[`IndexDetailPageView`](../../wealth/src/pages/index-detail/IndexDetailPageView.tsx)打开当前图时只用这份九转，原分钟图重试按该窗口重新发 `/minutes`。技术面打开后，已取到的当前窗口复用行情回包，技术面里尚未加载的其他周期才使用独立接口。周期切换时仍按现有请求取消及身份判断丢弃迟到响应。摘要保持原有周期列表和「末根没有标记显示空」规则。1 分钟沿用无九转开关，北证 50 分钟沿用空态。普通页和使用同一个页面视图的本地调试入口一同回归。

### 11.4 资源、验收和切换

- **读取与性能。** 复用 [设置中的算子预算](../../src/foundation/config/settings.py)和各接口的限制。日线一批一次行情计算；分钟行情及九转一次，独立常用指标仍为原请求。按当前行情 SQL 一批传入一组文件，九转只在内存中的已有行情上运行。原既定 1.5 秒 P95 目标、5 秒硬门禁和每个分钟响应 5,000,000 字节上限继续用于验收。按同一标的和日期测首轮及取消后的同参重试，记录文件数、读取 SQL 数、目标与实际预热根数、响应体和耗时。验证原分钟合同的首批及续页各 5,000 根代表窗口，超 5 MB 走原 HTTP 400；实际回包大小待开发后测量。[已有指数分钟合同与性能依据](../../wealth/docs/pages/index-detail/index-detail-minutes-api-contract-v1.md#6-m5-b-正式验收与切换边界)
- **恢复。** 请求失败或取消沿用算子会话资源清理，重试重新计算原窗口。首屏及摘要的日期锚保持 `page-init` 回包值，日线续页和独立分钟九转拿各自游标。前后端按阶段同次切换、回退同批部署版本。实现前把批准后的回包字段及其范围同步到现有指数日线、分钟 API 合同，切换后再更新总审计 HTML 的实际数据来源。
- **阶段 1。** 在 [九转计算测试](../../tests/foundation/technical_indicators/test_nine_turn_calculation.py)和 [指数分钟读取测试](../../tests/foundation/technical_indicators/test_index_minutes_recent.py)增补定向用例。用可手算序列验证 1–9、10–13、换向、等价归零和首根预热；以实际 DG 同一标的有界窗口对照六档单算与同行情合算。核对合成周期按合成后收盘比较。另验收 1 分钟以及 Prod 注册仍拒绝新的指数分钟九转组合。
- **阶段 2。** 回归 [本地指数日 K HTTP](../../tests/web/test_wealth_index_detail_dg_kline.py)、[独立日线九转](../../tests/web/test_wealth_index_nine_turn_api.py)和 [指数详情页面](../../wealth/src/pages/index-detail/IndexDetailPage.test.tsx)。用上证综指、深证成指、北证 50、中证 A500 覆盖全页及短页。实际请求首屏和上一页，按日期与独立读到的旧标记对照，复核边界差异、无标记与空页。浏览器向左翻页和打开技术面时，确认本地日线独立请求为零，原日期、光标和趋势通道行为正常。
- **阶段 3。** 回归 [分钟 HTTP](../../tests/web/test_index_detail_minutes_api.py)、[独立分钟九转](../../tests/web/test_wealth_index_minute_nine_turn_api.py)和 [分钟图控制](../../wealth/src/features/index-detail/controller/useIndexMinuteSeries.test.tsx)。用上证综指或深证成指的有界真实窗口逐档验收六频，以 90／120 分钟核对时间键、旧游标续页和合成后的收盘价。对照旧标记时若来源收盘价或时间键不同，用本次实际 K 线独立复算该处并记录原因。浏览器确认当前图表与摘要共用一次九转结果，未加载周期的摘要从独立接口拿到算子结果，1 分钟无九转、北证 50 分钟为空，常用指标失败时行情和九转还可显示。通过隔离数据或读数追踪验证两个新路径都无需读取 DG 主要指数分钟九转成品。复验 Prod 分钟路由仍未开放。
- **验收后盘点。** 用实际浏览器网络和接口调用确认本地指数详情依赖退出。保留旧独立日线接口的 Prod 消费和DG 生成、同步等外部依赖的审计记录。旧数据源的对照限代表性指数、周期和窗口，不做全量扫描。


<a id="local-index-nine-turn-phase-one-audit"></a>

### 11.5 阶段 1 实施与独立审计（2026-11-25）

**实施通过。** [内置注册](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/__init__.py)复用原九转定义和工厂，在[本地运行时](../../src/app/runtime/technical_indicators/composition.py)按 `data_location="dg"` 启用六档指数不复权分钟九转。只追加适用周期，[原计算及 16 根预热](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/nine_turn.py)沿用。阶段 2 的日 K 回包与阶段 3 的分钟接口、摘要和页面各在后续验收。

**代码与回归。** 用 CodeGraph 和当前源码对照运行时、注册表、分钟按根数入口及合成 SQL。52 项定向测试通过，覆盖默认注册、DG 与 Prod 装配、指数 1 分钟仍拒绝、股票日线九转、计数及换向、16 根预热、已有分钟读取与量额，以及 90／120 分钟用合成后收盘价计算。Prod 的旧 5 分钟区间九转请求在读取前按原规则拒绝。 [注册测试](../../tests/foundation/technical_indicators/test_nine_turn_calculation.py) · [分钟计算测试](../../tests/foundation/technical_indicators/test_index_minutes_recent.py)

**实际 DG 只读对照。** 用上证综指 `000001.SH` 截至 2026-11-17 15:00 的样本，独立从有限日期的 Parquet 读取时间和收盘价。90／120 分钟分别从 Silver 30／60 分钟取各窗口最后一根有效收盘价，再按前第 4 根独立复算。日线 12 根、各分钟周期 24 根的时间、收盘价和两列计数逐根一致。单算九转均预热 16 根，与价格和 MA20 合算预热 19 根。与只算价格和 MA20 的对照相比，加入九转后两者结果一致，读到的文件数也一致。六档分钟每次取数各用一条批量 SQL，同算九转前后每次选择同一批文件。

| 周期 | 单算／同算的算子记录文件数 | 单算／同算的单次算子耗时（毫秒） |
| --- | --- | --- |
| 日线 | 29／32 | 442／136 |
| 5 分钟 | 1／1 | 64／54 |
| 15 分钟 | 3／3 | 63／55 |
| 30 分钟 | 5／6 | 71／55 |
| 60 分钟 | 10／11 | 74／56 |
| 90 分钟 | 14／15 | 612／57 |
| 120 分钟 | 20／22 | 157／60 |

独立复算每个周期读取 1–28 个已限定日期的文件。表中为本机单个算子请求实测。另以相同的 120 分钟参数做取消和重试。首轮 87 毫秒，注入取消后约 1.1 毫秒释放资源，九转输出表和状态表均清理。重试 73 毫秒，一条 SQL 读取相同 22 个文件，24 根目标结果与首轮一致。HTTP 体积与页面性能在对应接入阶段实测。


<a id="local-index-nine-turn-phase-two-audit"></a>

### 11.6 阶段 2 实施与独立审计（2026-11-25）

**通过隔离验收。** [指数日 K API 合同 §5.7](../../wealth/docs/pages/index-detail/index-detail-api-contract-v1.md#local-index-daily-kline-api)确定了本地 `nineTurnMarkers`。后端在一次 DG 日 K 计算里组装行情、原有指标和九转，普通、核验回包均有标记数组。合法空页的数组为 `[]`。本地 OpenAPI 保留带标记的类型，旧 Prod 日 K 和独立九转合同沿用原类型。用 CodeGraph 与源码检查了日 K 装配、核验投影、历史控制和技术面摘要。

**实际来源对照。** 隔离路由读正式 DG 普通指数日线，以独立的收盘价序列复算每批 1–9 标记并逐日比对。用本地已配置的只读连接对照 Prod `core_serving.index_nineturn_daily`，查询仅含四个指数、下表日期区间以及 `ts_code, trade_date, close, up_count, down_count`，最多返回 2,970 行。实际对照 2,970 行，收盘价和标记全部一致。

| 指数 | 页锚 | 首屏根数／标记数 | 续页根数／标记数 | 最早核对日期 |
| --- | --- | --- | --- | --- |
| 上证综指 | 2026-11-17 | 500／453 | 500／439 | 2022-09-28 |
| 深证成指 | 2026-11-17 | 500／452 | 500／440 | 2022-09-28 |
| 北证 50 | 2026-11-17 | 500／461 | 447／383 | 2022-12-19 |
| 中证 A500 | 2024-10-30 | 23／19 | 历史到头 | 2024-09-23 |

核验接口的中证 A500 标记与普通接口一致，早于起点的请求返回空日 K、空标记和空游标。上证综指首轮与同参重试均用两批 SQL 读取 1,000 个行情文件，预热与目标各 500 根，算子另记录一份来源文件。一次注入取消约 11.8 毫秒清理资源，同参重试 414 毫秒，行情和标记一致。首轮 890 毫秒，回包 385,444 字节。这些是隔离本机样本的单次结果。

**浏览器。** 用本轮 Wealth 构建和本机隔离服务打开四只指数。页面日期和日 K 读正式 DG。登录、顶部指数、估值和成分统计使用隔离数据，趋势通道用受控回包核对请求范围。三只可翻页的指数都按上一页的 `nextEndDate=2024-10-25` 请求 500 根，北证 50 的短页结束历史，中证 A500 首屏即到头。打开技术面、切换九转及拖动的过程中，四只指数的独立日线九转请求均为零。续页保持页锚、盘口和首屏摘要，上证综指仍发出原首屏和续页两次趋势通道请求，后者使用实际续页首末日。最终浏览器验证无脚本或资源错误。

**回归。** 后端 73 项、Wealth 专项 83 项通过。类型检查、隔离构建通过。覆盖本地普通页与核验页、旧接口、首屏末根无标记时的摘要，以及续页缺少标记字段后重试原游标。本次验收范围为日线。分钟接入的实施与验收见 §11.7。

<a id="local-index-nine-turn-phase-three-audit"></a>

### 11.7 阶段 3 实施与独立审计（2026-11-25）

**通过本机隔离验收。** 本地 `/minutes` 一次计算并返回分钟行情与九转。技术面复用已加载分钟图的结果，其余已开放的摘要周期按原入口单算九转。常用分钟指标继续独立加载。用 CodeGraph 和源码核对路由装配、读取器、游标、Wealth 调用方及测试。Prod 配置下向三个指数分钟接口发请求，均返回 404。[指数分钟 API 合同 §3.4](../../wealth/docs/pages/index-detail/index-detail-minutes-api-contract-v1.md#34-九转)

**DG 实际行情。** 截至 2026-11-17，上证综指六档各取 500 根。每档独立查询与同批九转一致，按行情收盘价另写连续计数复算，全部 500 根的标记逐时间键一致。六档各截取 11 月 16–17 日的窄窗口与原 DG 主要指数分钟九转成品对照，共 82 根，标记全部一致。读取跟踪显示，每个行情请求提交一次 `price + nineturn`，每个独立九转请求只提交 `nineturn`，两种请求都用一条 DuckDB 查询批量读行情，实际各预热 16 根。读数路径只命中下表行情，独立的旧成品对照查询另行执行。

| 周期 | 读取行情 | 每个请求文件数 | 500 根分钟图回包耗时（毫秒） | 独立九转回包耗时（毫秒） |
| --- | --- | ---: | ---: | ---: |
| 5 分钟 | Gold 5 分钟 | 11 | 106 | 66 |
| 15 分钟 | Gold 15 分钟 | 33 | 111 | 67 |
| 30 分钟 | Gold 30 分钟 | 65 | 200 | 72 |
| 60 分钟 | Gold 60 分钟 | 129 | 224 | 81 |
| 90 分钟 | Silver 30 分钟合成 | 172 | 173 | 98 |
| 120 分钟 | Silver 60 分钟合成 | 258 | 188 | 106 |

**续页与限制。** 用原 v1 九转游标续读。90 分钟从 11 月 17 日 14:00 之前取到 11 月 16 日 15:00、11 月 17 日 11:00。120 分钟从 11 月 17 日 11:30 之前取到 11 月 16 日 11:30、15:00。两档均从相应 Silver 分钟文件核对合成 K 线收盘价，旧游标与同窗口时间键和标记一致。5 分钟用行情游标请求两批各 5,000 根，时间无重叠。每批一条 SQL 读取 105 份文件并预热 16 根，两批分别为 1,671,275 和 1,673,057 字节，耗时 188 和 173 毫秒。超出 10,000 根的参数请求返回 HTTP 400，5 MB 门禁由超尺寸回归覆盖。耗时为单请求样本。

**Chrome。** 使用隔离本地前后端和正式 DG 行情。深证成指 30 分钟图和摘要共用一次 `/minutes`，打开技术面只为 15、60、90、120 分钟请求独立九转。模拟 60 分钟常用指标 HTTP 500 后，K 线和九转仍显示。1 分钟回包 `nineTurn=null`，九转开关禁用。北证 50 的 90 分钟行情和九转均为空，页面显示原空态。浏览器取消一次上证综指 120 分钟请求后原参重试，136 毫秒返回 500 根行情和对应九转。认证、估值和成分数据使用隔离配置，顶底识别接口未纳入本轮浏览器验收。

**回归与切换。** 后端 112 项、Wealth 专项 90 项通过。前端类型检查、隔离构建、文档检查和 Git 差异检查通过。常用本地服务待整体切换，切换后复验并更新数据来源总审计 HTML。

<a id="prod-stock-nine-turn-lld"></a>

## 12. Prod股票日线九转接入与旧独立接口删除（2026-11-27，设计已确认、待开发）

### 12.1 目标、批准范围和现状依据

目标是让Prod股票日线九转复用现有算子库的同次日K计算，并让股票页面在各环境消费同批标记。管理员要求Prod也接算子库，对删除旧 `/api/v1/wealth/market/stock-detail/nine-turn` 及专用查询明确回复“删除吧”。删除范围含该接口原2000根上限、独立日期查询和游标，不保留旧URL转发、兼容参数或错误时读成品的后备实现。

当前源码依据及影响面已用CodeGraph `codegraph_explore`、`codegraph_impact`和实际引用核对：

| 位置 | 当前做法 | 本步如何改 |
| --- | --- | --- |
| `src/app/dependencies/stock_daily_technical_indicators.py` | Prod调用 `build_calculation_request(snapshot)` 默认不含九转；注册版本检查按DG决定是否含九转 | 所有股票日线使用同一固定九转清单；Prod继续原选页和PostgreSQL输入，不另建计算入口 |
| `src/biz/services/wealth/market/stock_detail/stock_daily_kline_calculations.py` | `stock_daily_calculations()`及请求构造带 `include_nine_turn`，缺省Prod不选 | 日线清单固定包含九转，删除日线专用的选择参数；共用 `stock_common_calculations(include_nine_turn=...)` 保持周月线已有用途 |
| 同目录 `stock_daily_kline_service.py` | `prepare_recent()`和 `assemble()`把 `paginated`当成是否选九转、校验九转的条件；已有标记组装可复用 | 日线计算、校验和标记输出与分页分开，复用现有组装及 `build_nine_turn_marker()` |
| `src/biz/schemas/wealth/market/stock_detail.py` | 普通日线父类没有数组；本地分页、周月子类各自已有数组 | 公共响应字段定义必有数组；子类继承，周月线原JSON保持 |
| `src/biz/api/wealth/market/stock_detail.py` | 普通/本地日K共用路由，按环境声明模型 | 同步OpenAPI和各响应模型，保留现有请求、500根上限及环境分页差异 |
| `wealth/src/pages/stock-detail/StockDetailPage.tsx` | 只在 `local` 时取回包标记；Prod通过registry请求独立九转 | 所有股票日线从回包取标记；本地判断继续只承担盘口与历史分页职责 |
| `wealth/src/features/stock-detail/api/stockDetailApiTypes.ts` | 共用字段 `nineTurnMarkers`可选 | 所有股票日/周/月K响应中该数组必有，所有类型消费者与测试输入同步 |

CodeGraph响应类型影响面覆盖日线/周月线组装、Python继承类、前端API client/adapter、股票页及测试。字符串及导入引用另核对旧独立接口的前端请求、混合测试、浏览器夹具、股票分钟合同和运营统计；不能仅凭CodeGraph没有显示测试就判无消费者。仓库内旧独立股票日线九转的产品调用方为股票详情页；本次删除已由管理员批准，不把未证明的外部访问量作为保留旧实现的理由。

### 12.2 计算和数据读取

1. 固定日线清单按原共用顺序保持MA、BOLL、MACD、KDJ、price，再加nineturn和trend_channel。`STOCK_DAILY_CALCULATIONS`、`stock_daily_calculations()`、`build_calculation_request()`、`build_recent_calculation_request()`和私有请求构造同步清零日线 `include_nine_turn=False` 口径。周月线的共用选择函数不借机改造。
2. `StockDailyKlineAppBackend`在所有环境校验日线九转版本和日线支持能力；Prod仍用当前 `prepare()`及一次 `indicators.calculate()`，DG仍用当前 `prepare_recent()`及一次 `calculate_with_source()`。不另起独立九转算子请求，不把Prod改成本地读数或增加分页。
3. `StockDailyKlineService`按固定清单校验完整结果，所有有目标行情的日线必须有九转结果。复用已有0—13整数、方向互斥及日期对齐检查，不在下层再增加一套校验；普通请求不再绕过九转验证。组装读取已校验的同一份结果，并沿当前标记helper生成1—9，0和10—13不画。
4. Prod输入沿 `core_serving.equity_daily_bar`、`core.equity_adj_factor`；本地沿DG股票不复权日线和股票复权因子。复用同次输入会话的复权后收盘价，不读 `core_serving.equity_qfq_nineturn_daily`、DG九转成品或旧趋势通道成品。基础行情、股票每日指标及复权因子仍各按现有职责读取。
5. 当前Prod业务选页的 `StockDetailQuery.load_kline_rows()`仅选本批日期、昨收、涨跌、换手率和量比；行情价格、预热及复权由算子输入会话读取。不得将这两步误写成两次九转计算，或为本次新增第三次取价。既有Prod定位、日历和复权基准读取不在本次重构；比较增量时固定同一日K请求，列清各查询的用途、表和字段。

### 12.3 返回、页面与失败规则

| 合同 | 明确要求 |
| --- | --- |
| `/stock-detail/kline` | 路径及参数保持，日线缺省/上限500根保持；`nineTurnMarkers`为必有数组，普通本地日线及Prod都新增该字段，不保留旧缺字段日线类型 |
| 数组内容 | 使用现有 `NineTurnMarkerDto`，按本批日期升序；日线 `tradeTime=null`，只展示1—9，第9根沿原完成样式；预热不进入回包 |
| 无标记与空行情 | 正常无标记及合法空日K均显式返回 `[]`；不得用数组缺省值掩盖漏算、缺字段或错误结果 |
| Python继承及OpenAPI | 在 `StockDetailKlineResponseDto`声明数组，本地分页和周月类继承；去掉同字段的重复声明，同步普通、本地和debug响应。周月线原本已有标记，原输出不变 |
| 前端类型 | `StockDetailKlineFields.nineTurnMarkers`改为必有；迁移全部日/周/月响应构造、API overload、adapter及测试输入，禁止保留可选旧口径 |
| 首屏消费 | `StockDetailPage.loadStockDetail()`在所有日线回包均校验数组并用 `buildStockDailyNineTurnLayer()`保存。原 `local` 判断仍处理盘口来源和历史seed，不再决定九转来源 |
| 历史页与环境 | 本地 `useStockDailyHistory`沿现有批次、日期、四轨和标记一起提交，成功才更新游标；Prod沿原首屏与日期请求方式，不增设本地式续页 |
| 显示与重试 | 原开关、样式、颜色及日期定位不变，开关不取数；九转计算/合同错误随日K失败、取消和重试，不单独重试九转或回读成品 |

股票页删除 `loadStockNineTurnSeries`、`useNineTurnSeriesRegistry`调用、相关日线周期常量、`ensure("day")`及 `retry("day")`。加载占位沿现有图层状态，成功使用同批结果。`StockChartWorkspace`删除仅为独立九转准备的 `onNineTurnRetry`参数及传递；共享 `NineTurnLayerStatus.onRetry`本已可选，股票图层不再传它，指数及其他调用方保持。共用registry、状态组件、标记DTO、`useNineTurnChartLayer`及 `NineTurnMarkerPrimitive`均保留。

失败或取消后，输入会话、数据库连接、临时表、工作许可及发送资源按现有执行流程释放；没有业务数据写入、补算落库或持久化续跑。重试是同一日K请求的完整重新读取、计算和返回。本地历史失败保留原图和原游标；Prod首屏失败沿原日K页面错误处理，不新增独立九转错误UI。

### 12.4 删除、保留及混合消费者清单

| 对象 | 处理及原因 |
| --- | --- |
| `src/biz/api/wealth/market/stock_detail_nine_turn.py` | 删除旧路由及专用错误映射；`src/app/api/v1/router.py`同步删该模块导入、挂载，其他路由顺序不改 |
| `src/biz/queries/wealth/market/stock_nine_turn/` | 删除专用query、service及包文件，清零运行代码引用，不为测试保留实现 |
| `wealth/src/features/nine-turn/api/nineTurnApiClient.ts` | 删除 `StockNineTurnFetchParams`、`fetchStockNineTurnSeries`和私有函数中的股票专用类型/分支；保留指数请求、通用错误处理及其原行为，不重写指数入口 |
| `tests/web/test_wealth_stock_nine_turn_api.py` | 删除旧接口的读表、部分匹配、独立日期窗口/游标、参数及品种拒绝测试；将仍有效的page-init九转能力和Prod分钟路由未开放断言迁入现有股票日K路由测试，不整文件丢弃仍有效行为 |
| `tests/wealth_watchlist_browser_fixture.py` | 清理只为旧股票日线九转接口准备的结果表导入、建表清单项和种子；保留自选、身份、日历、行情及其他夹具。该文件不是Prod清表脚本，不操作正式库 |
| 前端混合测试 | 清理股票页面和历史测试中旧请求的mock/import/期望，更新缺失标记字段、Prod内联输出及零独立请求断言；不导入旧模块并设置“调用即报错”来证明删除 |
| `src/foundation/clients/local_lake/stock_nine_turn_contract.py` | 保留：股票分钟独立九转API及新分钟算子读取器仍用其上限与支持周期，不能因名称含stock_nine_turn就删除 |
| Prod股票日线前复权九转表及模型 | 保留 `core_serving.equity_qfq_nineturn_daily`、对应模型/全局注册/迁移及服务表合同测试；运营卡片和DG发布仍有用途，不改表结构或删除数据 |
| 指数与其他周期 | 指数独立日线/分钟九转、股票分钟九转、周月回包和共享标记绘制均保留；不删除整个nine-turn前端目录或通用 `NineTurnSeriesDto` |
| DG相关对象 | 不启停sensor、不改生成/修复/同步/check/日审计、不改文件或数据集，也不把这些事项设为本次开工前提 |

旧路径在完整路由装配和OpenAPI中退出；隔离应用请求返回404。不把旧2000根接口截断、分批代算或转发为500根 `/kline`，不追加开关保留两种股票日线九转来源。前后端组成同一交付候选，发布另行授权。

### 12.5 性能预算与真实验证范围

本节数字是现行代码或逐项推导，不是本次已测结果：

- 日线输出上限为500根，沿现有请求校验。固定日线清单为7个MA实例，加BOLL、MACD、KDJ、price、nineturn、trend_channel各1个，共13个实例；现有默认上限为16，不新增或提高配置。
- 单算九转所需前置行情为16根。令本次其他指标已解析的联合预热为 `W`，当前日线已有固定500根预热的趋势通道，所以 `W≥500`；增加九转后为 `max(W,16)=W`。目标 `T≤500` 时，交给算子的行情按已有 `T+W`范围处理，历史短时用已有历史；`W=500、T=500`时为1000根，这不是所有请求的数学上限，也不是磁盘扫描行数。
- 默认总目标8000毫秒、清理预留2000毫秒，来自 `Settings.technical_indicator_total_target_ms/cleanup_reserve_ms`；运行时沿实际配置，不抬高时限、输入、文件或内存上限。新增开销是九转自身SQL和至多T个标记的组装、编码；不得宣称耗时为零，实测后记录。
- 最小真实来源验证选已有股票日线验收用过的 `600519.SH`，目标截止日用当次页面交易日，正常请求500根；历史不足按真实返回，不人为补齐。隔离应用只装配实际股票日K路由及其计算运行环境，连接真实PostgreSQL只读来源；不调用完整 `web_lifespan`，不启动会写正式状态的交易助手等后台组件。不重启或替换正式Web，不创建正式账户、不绕鉴权；正式线上发布和登录页面验收另按授权执行。
- 一次正常请求、一次中断请求、同参完整重试、一次最后验收分别记账。三个完整请求各按 `T+W`计，合计逻辑交付量为 `3×(T+W)`，另加取消前实际已读量 `R取消`；它们是重复请求的累计处理量，不是独立K线或实际磁盘读量。每次分别记录耗时、价格SQL、股票复权因子SQL、源行数、复权次数、回包体积和资源释放。
- 为独立复算，从该次执行已准备的共享复权后 `PriceBatch` 临时行情表记录收盘价，最多保留T根目标及其前16根，共最多516根；按seq与目标日期对应，不再向Prod追加取价或复权查询。工程外验收记录这次临时表投影、独立复算和最后对账的额外开销，不把验收自身SQL当作产品请求查询。预期计数用独立比较与连续计数实现，不能调用待测九转算子或标记helper生成expected。

修改前后用同一请求口径对照价格/复权读取量，不能把删掉一次独立HTTP读取说成Prod所有既有SQL重复都已消除。重试的结果按该次真实输入独立验证；来源正常更新时不新增跨请求必须完全相等的拒绝或重试门槛。临时脚本、配置、数据样本、日志、测试缓存及构建输出统一在 `/private/tmp`本任务目录，结果回写原方案/LLD，退出后关闭临时资源并清理无用产物。

### 12.6 测试、合同和验收矩阵

| 要求 | 代码点和测试消费者 | 必须验证的正反例 |
| --- | --- | --- |
| 各环境股票日线同算九转 | 计算清单、App backend、`tests/test_stock_daily_kline_service.py`、`tests/app/technical_indicators/test_stock_daily_integration.py`、`tests/web/test_stock_daily_technical_indicator_api.py` | Prod与DG普通/本地分页均只发一次联合算子请求；必含九转，缺实例/字段/错误计数或日期错位拒绝；不得仍以paginated控制是否算九转 |
| 新日线字段及OpenAPI | Python DTO、路由模型、TypeScript必有类型；上述测试及 `tests/app/technical_indicators/test_stock_daily_source_repair.py` | Prod普通/debug、DG普通/首批/续页和合法空页均有数组；无标记合法 `[]`，缺字段不能当空；周月原JSON不变 |
| 九转数值与预热 | 现有 `tests/foundation/technical_indicators/test_nine_turn_calculation.py`及日K集成 | 以独立字面值覆盖行情真实起点的前4根、相等归零、换向、9与10—13、13封顶、历史短/上市前、跨批和从中间窗口请求；同批真实Prod输入独立复算，不借旧成品缺记录判新算法错误 |
| 无多余源读取 | Prod日K来源装配、真实只读追踪及日K集成 | 同一目标加入九转不增加独立价格/复权查询或复权次数，不读旧九转表/文件；保留当前选页辅助字段的合理查询，不顺手改通用source |
| 前端首屏与本地历史 | `StockDetailPage.test.tsx`、`useStockDailyHistory.test.tsx`、`stockDetailViewModelAdapter.test.ts`、`StockChartWorkspace.test.tsx` | Prod和本地首屏从日K保存标记，打开/开关/切股/切日及本地续页无股票独立九转请求；旧响应缺字段必须失败；本地失败不提交游标，重试同一批；首批无标记而历史有标记可显示 |
| 共用类型与周期回归 | 前端API overload、`useStockPeriodKline.test.ts`及股票周月线真实路由隔离测试；股票分钟与指数九转原测试 | 必有类型的所有构造同步；周月字段、分钟及指数入口和绘图保持，无股票清理误删共用能力 |
| 旧接口退出 | 主路由/OpenAPI、前端client和专用query删除清单、迁移后的股票日K路由测试 | 旧URL返回404、OpenAPI不存在，运行源码无旧模块或股票独立fetch引用；不为断言保留旧实现，不移除运营模型/服务表合同测试 |
| 失败、中断及预算 | 现有execution/admission和相关日K集成、工程外真实只读验证 | 计算失败、回包字段错误、断开与同参重试均沿日K处理，资源释放、旧页面状态稳定；不提高预算或安装依赖掩盖失败 |

前端真实浏览器验收在与候选后端配套的构建中完成：Prod模式股票日线首屏、九转开关、换股和换日期；本地额外核首批/续页与游标。请求真实后端并使用真实来源，登录和其他非目标模块可用既有隔离夹具，须写明隔离层。匿名线上探测401仅证明鉴权，不能作为真实业务结果验收；未执行正式线上登录验收时据实说明。所有当前相关后端回归、Wealth类型检查、定向测试和生产构建完成后，再做与编码分开的LLD逐项对照审计；不存在第二审计人时明确为另一次自审，不声称独立人员审计。

### 12.7 阶段、文档交接和当前状态

按方案§6.4的三个阶段推进：先后端同批计算及合同，再页面消费与旧业务代码清理，最后有界真实验证和对照审计。阶段之间不发布半套候选，不为过渡新增兼容层；前后端及旧接口退出作为同一交付候选review。发布、服务重启、共享包发包和DG停产均不是本次文档批准包含的正式执行。

原股票页面实施方案、首屏/DG取数方案与LLD及股票日线内核接入方案与LLD同步注明本次后续设计，保留原阶段历史。开发完成后，才将实际字段来源和验收结果补入相关来源审计；目前不把在线旧链路写成已切换。当前完成的是源码与消费者核对、方案审计及本文设计，无新增业务待拍板项；实现、测试、真实Prod数值/费用验证、浏览器及最终对照审计均未在本轮执行，不能以本节或既有本地通过记录宣称开工后已完成。
