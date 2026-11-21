# 九转算子及本地股票详情接入 LLD v1

2026-11-22｜本地股票日线九转已切换，首屏与续页均从算子库取得九转标记。[本机切换后复验](#10-本机切换后复验) · [专项方案](technical-indicator-nine-turn-plan-v1.md)

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

调用方在现有 `CalculationRequest.calculations` 放入 `{"calculation_id": "nineturn", "parameters": {}}`。返回的 `times` 与两个计数数组逐项对齐。收集器用 `DOUBLE` 输出，实际计数始终取整数值 0–13。注册说明按周期与当前运行环境已启用来源取交集，因此当前配置下可用于股票原价日线、股票前复权日线和指数原价日线。分钟、周线和月线由现有周期校验拒绝。固定比较间隔和计数上限不作为参数开放。[注册能力查询](../../packages/technical_indicators/src/goldenshare_technical_indicators/discovery/catalog.py#L32) · [已启用来源](../../src/app/runtime/technical_indicators/composition.py#L34) · [周期和参数校验](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/dependencies.py#L41)

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
