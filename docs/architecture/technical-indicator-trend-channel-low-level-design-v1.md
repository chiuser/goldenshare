# 趋势通道算子及股票、上证接入 LLD v1

**2026-11-26 管理员确认的范围纠正。** 阶段4只清理股票、上证页面已经不用的旧趋势通道接口及专用代码，并回归新链路。把 DG 数据生成、数据集停产或文件字段迁移纳入本需求，是此前方案的范围错误，现撤回；本次不处理 DG 工程、数据集、文件、生产任务及其检查，方向专项清理后续单独做。删除测试中仅用于拦截旧实现调用的导入、替换和断言，不为测试保留旧实现；固定历史行情样本和仍使用的共享绘图代码保留。以下现行范围按本条校准，历史验收记录保留当时事实。

**2026-11-26 阶段四实施状态。** 已完成旧业务源码清理、隔离技术验收及与编码分开的LLD对照自审，提交管理员review；本轮代码和文档纳入阶段四提交，未发包或部署。现行清理状态和逐项证据见[§14](#trend-stage4-results)。

历史进度（2026-11-25）｜[专项方案](technical-indicator-trend-channel-plan-v1.md)记录最终需求。阶段一算子已实现，隔离验收和独立对照审计已完成，证据见 §9；提交管理员阶段 review。阶段二股票日线接入代码、隔离技术验收及对照审计已完成，提交管理员 review，证据见 §10；阶段三开发、技术验收及单独对照审计已完成，提交管理员 review，证据见 §12；阶段四尚未实施，未发包或部署。JSON 已取消、预热与接口处理等已确认口径保持不变。

固定前置 500 根、每轨绝对误差不超过 0.01、四轨输出、不迁入旧方向、方向专项后续单独清理和 MACD 保持现状均已确认，不需要重新拍板。阶段二、三设计已补齐，每步按其现行代码、合同和验收范围复核并单独 review。

**2026-11-25 后续设计确认。** 管理员确认每个指标独立 build、公共组装复用、业务 `assemble()` 显式组合，并指定在第三阶段实施该组装架构修改。此处记录开发前设计：阶段二先完成股票日线接入及计算范围隔离；阶段三先整理公共组装，再接入上证；阶段四清理不变。本地和 Prod 各沿原有接法与环境，Prod 不新增本地式分页。以下 §4.2、§4.3 已按此补齐；本段记录开发前决定，阶段二实施现状与证据见 §10。

## 1. 当前代码与本期改动边界

本表保留开发前代码依据与分阶段处理范围；其中旧模块已在阶段四删除，当前完成状态见§14，不能把历史路径当作仍有运行实现。

| 对象 | 当前代码依据 | 本期处理 |
| --- | --- | --- |
| 算子请求与结果 | `packages/technical_indicators/src/goldenshare_technical_indicators/contracts.py` | 沿用 `CalculationRequest/CalculationValues`、数值 `fields` 和公共 `times`；不新增说明字段或说明空串。 |
| 算子接口与引擎 | 同包 `calculation/calculation.py`、`registry.py`、`engine.py`、`history.py` | 沿现有接口新增计算实现与注册，不增加 `output_info()`，不批量改造既有算子。 |
| 输出检查与编码 | 同包 `output/collector.py`、`result.py`、`encoding.py` | 四轨沿既有 DOUBLE 校验、日期对齐和编码，不为本期增加 VARCHAR 指标列或 JSON 处理。 |
| 股票调用 | `src/biz/services/wealth/market/stock_detail/stock_daily_kline_calculations.py`、`stock_daily_kline_service.py`，`src/app/dependencies/stock_daily_technical_indicators.py` | 按现有 MACD/KDJ 接法：计算指令加项 → 共享计算 → 按同批日期组装日 K 指标。 |
| 上证调用 | `src/app/dependencies/index_daily_technical_indicators.py`、`src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py` | 按现有日线装配、算子请求、数值映射和 `nextEndDate` 接入。 |
| 页面首批与续页 | 股票 `useStockDailyHistory.ts`、指数 `useIndexDailyHistory.ts`、对应页面 controller | 沿 `DAILY_CHART_PAGE_SIZE` 与 `nextEndDate` 加载，趋势四轨随同一批行情进入图层。 |
| 股票页面入口与旧路由挂载 | `src/foundation/config/stock_daily_trend_channel_capability.py`、股票查询的 `_page_options()`、`src/app/api/v1/router.py`；`tests/test_stock_daily_trend_channel_capability.py` | 开发前该检查同时用于页面入口、旧路由挂载和旧接口请求；阶段二已移除页面调用，旧路由和旧接口仍沿原限制，阶段四再按引用清理。 |
| 旧独立通道 | 上证 `quote_trend_channel_calculator.py`、`quote_trend_channel_query_service.py`；股票通道 query service 与 Lake reader | 属于后续清理、消费者迁移对象；不把完整旧 HTTP 响应直接换成共享库响应。 |

CodeGraph 已用于定位算子结果、请求解析与旧业务调用影响；已用 `codegraph_explore(run_index_daily_kline)` 核对上证装配，本次再用 `codegraph_explore(resolve_stock_daily_trend_channel_capability)` 定位股票页面、旧路由和旧接口的调用关系，并直接核对股票、指数的计算指令、读取器、前端批次加载和相关测试。同名 `run/calculate/resolve` 的无关命中不作为真实依赖。完整清理仍须在对应阶段按引用逐项核对，当前未证明旧数据集已无其他消费者。

## 2. 本期输出合同与范围

本期只增加 `trend_channel` 数值算子。JSON 说明字段已取消：不增加 `CalculationValues.info`，不返回 `info: ""`，不增加 `Calculation.output_info()` 或相关注册、校验、编码和测试。该能力未来需要时另议，不作为本期前置步骤。

算子 ID 为 `trend_channel`、算法版本 `1.0.0`，参数为空。短期固定 25、长期固定 90，不开放管理员未要求的周期参数。返回四个必有有限 DOUBLE 字段：

| 字段 | 计算 | 单位 |
| --- | --- | --- |
| `short_upper` | 最高价的 25 周期 EMA | 输入价格单位 |
| `short_lower` | 最低价的 25 周期 EMA | 输入价格单位 |
| `long_upper` | 最高价的 90 周期 EMA | 输入价格单位 |
| `long_lower` | 最低价的 90 周期 EMA | 输入价格单位 |

日期时间仍由 `times` 与各字段数组一一对应，日线为日期，分钟为既有带时区业务时间。说明、位置、方向、组合状态均不进入新算子结果。数值输入只需要 `high/low`，来源原有 OHLC 检查继续执行；无需读取收盘价来判断历史方向。

通用算法沿现有标准行情及已启用来源合同注册，不自动开放新的证券、周期、复权或环境组合。页面接入范围是股票日线及上证日线；股票周月线、分钟线、其他指数页面不因本次接入自动增加通道图层。

## 3. 阶段一：完整实现趋势通道算子

### 3.1 文件与接口

实现位于 `packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/trend_channel.py`，实现 `TrendChannelCalculation` 的现有六个方法：`input_requirement/dependencies/prepare/consume/release_batch/release`。在 `calculation/indicators/__init__.py` 的 `create_builtin_registry()` 冻结前注册，沿现有 `CalculationDefinition/CalculationOutput` 和能力查询，不改变通用协议。

在该算子定义中以 `TREND_CHANNEL_WARMUP_ROWS = 500` 保存唯一数值来源，历史需求和能力说明读取它；测试以管理员指定的 500 为独立预期。此值随算法版本生效，不存入 Settings、环境变量或数据库，不开放运营输入，不复用 MACD 的最低预热常量或 `PRICE_ABSOLUTE_BOUND`。

`input_requirement(session, max_input_rows)` 声明 `fields={high, low}`、`preceding_rows=0`、`warmup_rows=500`、`requires_source_origin=False`，并声明 `last_seq` 与四条 EMA 数值状态。没有额外算子依赖，不读现有通道成品。

### 3.2 初始化、递推与批次

短期 `α=2/26`，长期 `α=2/91`。首个已读取的最高价初始化两组上轨，最低价初始化两组下轨；以后按 `EMA_t=α×价格_t+(1−α)×EMA_(t−1)` 递推。

1. `prepare` 准备固定系数和本请求数值状态。复用现有 `smoothing_parameters.sql` 的分段范围计算，不另造段长上限。
2. `consume` 仅首次初始化，其后只处理新序号；四轨使用共享行情执行固定 SQL，每段末尾更新四个原始 EMA 和 `last_seq`。批次重叠行不重复推进。
3. 使用新增的 `trend_channel_first.sql`、`trend_channel_segment.sql`，登记到该类资源声明和现有 SQL 白名单。输入只限本请求共享行情、自有参数和数值状态，输出 `seq` 与四轨。
4. `release_batch` 释放本批输出，跨批保留四个 EMA 与序号；`release` 沿引擎的结束、失败、超时和取消路径释放剩余资源。

计算中不按两位或四位小数逐根量化；0.01 是结果绝对误差标准。四个 EMA 数值是必要的续算状态，与要删除的方向标签不同。不得增加 `short_state/long_state/combined_state`，不得为新算子增加价格位置判断或旧方向保留规则。

### 3.3 读取、重试和预算

单算时沿当前已启用的读取方式定位目标：支持按根数时使用截止时间和本批数量，已有范围调用继续由当前装配确定目标日期；本阶段不改请求解析器的来源选择或扩大来源支持。读取模块在目标之前补最多 500 根实际 K 线。到已确认的来源起点而不足 500 时使用已有历史，不补造行情，不把缺失或 I/O 错误当成合法短历史。只返回目标区间，前置行情不进入结果。

| 场景 | 计算输入与恢复成本 |
| --- | --- |
| 历史充足，单算返回 R 根 | `500 + R` 根，R 不超过本次业务每批 500 根。 |
| 单算返回 500 根 | `500 + 500 = 1,000` 根计算输入，返回后 500 根。 |
| 与其他指标同算 | `R + max(各算子实际历史需求)`，不相加、不重复取数或复权；其他指标确需更多历史时整次输入可能更大。 |
| 中断后完整重试一次 | 两轮计算输入按 `2×(500+R)` 核算，实际中断点可能少于一轮；沿现有取消与资源清理，不新增持久化状态。 |
| 最后验收 | 完整参考与被测窗口的输入分别计量；复用固定样本，真实核验仅限获准证券、周期和有界窗口。 |

这些是计算 K 线数量，不是物理文件读量、重复 SQL 处理量或耗时保证。现有输出/输入容量、批量、时限、内存、文件和编码预算沿当前装配，不扩容、不新增参数。共享 SQL 链路的耗时、物理读量、内存、中断重跑与清理费用在阶段一有界验收时实测；现无依据预填新的数值阈值或套用旧业务计算器耗时。

### 3.4 阶段一开工审计（2026-11-25）

开发前结论：阶段一具备开始开发的条件，没有需要重新拍板的业务口径。范围仅为算子实现、注册、固定 SQL 资源和必要测试，不修改业务日 K、页面、旧接口或正式数据集。以下保留开工时证据，实施后对账见 §9。

本次用 `codegraph_explore` 检索 `MACDCalculation/CalculationEngine`，返回结果包含无关同名项；下表结论已逐项复核当前算子、引擎、读取、输出代码和相关测试，不以索引结果代替源码。

| 已确认约束 | 当前代码依据及实施要求 |
| --- | --- |
| 完整四轨、无参数、固定 500 根预热 | `CalculationDefinition`、六方法 `Calculation` 协议及 `HistoryRequirement` 已支持；`history.py` 合并历史需求取最大值，趋势通道独立返回 500，不使用 `session.recursive_warmup` 或 MACD 价格上界。 |
| 固定 SQL 和数值续算 | 沿 MACD/KDJ 声明 `TABLE_ROLES/SQL_FILES/FIXED_SQL_STEPS`，分别保存参数、四个 EMA 与序号、批次工作表及输出。`sql_templates.py` 的白名单加入本算子两份 SQL；分段控制读取复用引擎已允许的 `read_smoothing_limits/read_segment_bounds`，不增加新的控制读取名称或修改通用引擎。 |
| 分批、共享输入及只返回目标 | `service.py` 先准备算子、合并历史再创建输入会话；`sources/session.py` 区分预热与目标、按 `preceding_rows` 保留输入；`OutputCollector` 按目标区间收集已声明的 DOUBLE 字段，支持四轨而无需新结果协议。 |
| 结束、取消及失败清理 | `CalculationEngine.release_batch_tables()` 释放本批表并保留请求状态；`close()` 逆序释放各算子资源。新算子按现有 MACD 的释放方式处理自有表，测试覆盖失败后完整重试，不增加持久续跑状态。 |
| 0.01 精度和独立预期 | §6、§7 已区分不同起点的预热误差与相同起点的分批一致性；固定上证输入夹具的 1,599 根记录和 SHA-256 与 §7 一致。新 SQL 的金样本、误差、短历史、共享、跨批和取消仍须实现后验收。 |

已执行 74 项既有基线测试并全部通过，覆盖合同、注册/依赖，以及选定的执行器配置、标量绑定、取消后清理和 SQL 失败后的资源释放。测试只用本地隔离资源，未运行受保护 D3，未读取正式数据。该结果证明上述现有基础可用，不代表未实现的趋势通道已验收。

本机 `.venv` 默认加载已安装的旧版算子包，首次测试因缺少 `configuration.datasets` 在收集阶段失败；显式指定工作区源码后通过，无需安装依赖或改本机配置。阶段一测试从仓库根运行，必须沿当前源码路径启动；新增算子测试文件落地后加入下列明确清单，不直接运行整个指标目录：

```bash
trend_audit_tmp="$(mktemp -d /private/tmp/trend-channel-stage1-XXXXXX)"
PYTHONPATH=packages/technical_indicators/src:. PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B -m pytest -q -p no:cacheprovider --basetemp="$trend_audit_tmp" \
  tests/foundation/technical_indicators/test_contracts.py \
  tests/foundation/technical_indicators/test_registry_dependencies.py \
  tests/foundation/technical_indicators/test_executor.py::test_private_connection_uses_all_confirmed_settings \
  tests/foundation/technical_indicators/test_executor.py::test_execute_uses_returned_count_and_bindings_without_an_extra_scan \
  tests/foundation/technical_indicators/test_executor.py::test_stopped_cleanup_only_accepts_owned_resources_and_is_idempotent \
  tests/foundation/technical_indicators/test_executor.py::test_failed_creation_retains_cleanup_eligibility_and_original_database_cause
```

这份清单是本次开工基线；阶段一完成验收还须运行 §6 对应的新算子、同批共享、输出、失败与取消测试。新增和复跑均使用工程外临时目录，验收后删除无用临时文件，保留必要证据于本 LLD。

## 4. 阶段二、三：沿现有业务接法接入

### 4.1 已核对的现有方式

- **股票。** `stock_daily_kline_calculations.py` 集中构造算子清单；`StockDailyKlineService` 校验结果并由 `build_kline_factors()` 组装日 K 指标；App 按环境调用共享库。本地 DG 已使用 `build_recent_calculation_request()` 的 `end/latest_rows`，Prod 沿现有 `prepare()` 确定目标日期后，以 `build_calculation_request()` 调用共享库。股票日线请求本来就限制 1–500 根。
- **上证。** `run_index_daily_kline()` 构造现有 MACD、KDJ 等指令；DG 用 `calculate_with_source()`，Prod 先由查询服务确定本批目标日期，再沿现有范围计算与结果映射。`apply_calculated_kline_factors()`、`_calculated_daily_response()` 负责指标和 `nextEndDate`。
- **页面。** 股票与上证日 K 都用当前 `DAILY_CHART_PAGE_SIZE` 请求，当前为 500；下一次沿服务返回的 `nextEndDate` 取更早一批。旧独立趋势端点的 2,000 上限不是本次页面单次请求的要求。接入不要求共享库支持一次 2,000 根，也不以全量替换旧端点为前提。

因此此前审计把“旧端点允许 2,000 根”直接当成本次接入阻塞，遗漏了当前页面的 500 根批次调用，是判断错误。本次沿已有入口加算子、组装四轨和翻页，不强制新增 Prod 的原生按根数读取，也不自行改写现有 2,000 根旧端点的合同。

### 4.2 阶段二：股票日线

目标是沿现有 `/api/v1/wealth/market/stock-detail/kline` 返回本批四轨，停止页面的独立通道请求，并保持周月线和各环境原有行为。本阶段不执行 §4.3.1 的公共四组指标拆分，不修改算法、通用结果合同、正式文件或部署配置。

#### 4.2.1 计算清单和实际调用

阶段二开发前，周月线 `StockPeriodKlineService.calculate()` 也调用 `stock_daily_calculations(include_nine_turn=True)`；只按旧函数名认为它是日线独有，会错误扩大计算范围。本次经 `codegraph_callers(stock_daily_calculations)` 及源码核对，消费者包括请求构造、日线结果检查、周月线计算和 App 启动检查。阶段二作如下必要隔离：

1. 在 `stock_daily_kline_calculations.py` 将原共用清单命名为 `STOCK_COMMON_CALCULATIONS`，由 `stock_common_calculations(include_nine_turn=...)` 保持原指标、实际参数及九转选择。新增的 `STOCK_DAILY_CALCULATIONS` 是不含可选九转的公共基础清单加无参数 `trend_channel`；日线 `stock_daily_calculations()` 对公共函数返回的原序列在末尾加通道，保留已有指标与可选九转的顺序。公共指标只声明一份，不按周期复制参数或先加通道再过滤。
2. `StockPeriodKlineService.calculate()` 改调用公共清单，实际请求集合与改前一致；日线两个请求构造、`StockDailyKlineService._validate_result()`、App 启动检查使用日线清单。版本映射加入 `trend_channel=1.0.0`，字段映射加入四轨，沿现有检查核对实例、参数、版本、字段、长度和数值输出。
3. 本地继续 `StockDailyKlineAppBackend.work()` → `StockDailyKlineService.prepare_recent()` → `build_recent_calculation_request()` → 传入的 `TechnicalIndicatorService.calculate_with_source()`。首批和续页只是不同的截止日，不另造翻页接口。
4. Prod 继续 `work()` → `prepare()` 取得本批日期 → `build_calculation_request()` → `TechnicalIndicatorService.calculate()`。保留原 PostgreSQL 只读范围、会话、错误与取消规则，不要求新增按根数读取或生产翻页。

代码中的算法调用仍在组装之前。各 build 函数只映射已经算完的结果，不读取数据、不调用算子库、不决定计算清单。

#### 4.2.2 日线字段、类型与组装

固定字段路径为 `bars[].factors.trendChannel`：

| API 字段 | 算子结果字段 | 合同 |
| --- | --- | --- |
| `shortUpper` | `short_upper` | 25 周期最高价 EMA，必有有限数值，单位元 |
| `shortLower` | `short_lower` | 25 周期最低价 EMA，必有有限数值，单位元 |
| `longUpper` | `long_upper` | 90 周期最高价 EMA，必有有限数值，单位元 |
| `longLower` | `long_lower` | 90 周期最低价 EMA，必有有限数值，单位元 |

在 `src/biz/schemas/wealth/market/stock_detail.py` 增加 `StockTrendChannelFactorsDto`、`StockDailyKlineFactorDto`、`StockDailyKlineBarDto`。日线 factor 类型在原公共四组上增加必有 `trendChannel`，日线 bar 明确声明该 factor 类型；`StockDetailKlineResponseDto.bars` 使用日线 bar，本地首批、续页响应沿原继承使用它。`StockDetailPeriodKlineResponseDto.bars` 显式保留 `list[StockKlineBarDto]`，原公共 factor/bar 不增加通道、可选空对象或空轨道。无行情时沿原空 `bars`，不造空 K 线。

阶段二在 `stock_daily_kline_service.py` 增加 `build_stock_trend_channel_factors(results, index)`，输入为本请求按实际算子参数整理的数值数组，输出上述通道 DTO；不使用 `special_factors` 名称。日线 `assemble()` 继续调用现有 `build_kline_factors()` 得到公共四组，再显式组合通道形成 `StockDailyKlineFactorDto`。公共字段按现有对象成员合入，不重新列写一份 MA/BOLL/MACD/KDJ 的数值映射。价格及基础字段复用 `build_kline_bar()` 已生成的成员，替换 `factors` 后构造明确的日线 bar；不复制一套 OHLC、幅度或盘口映射。

四轨必须在实际 JSON 和 OpenAPI 中出现，不能只验证 Python 对象上有属性。Pydantic 默认按字段声明的模型类型序列化嵌套对象，基类声明不会自动输出子类新增字段；已按[官方序列化说明](https://docs.pydantic.dev/latest/concepts/serialization/#subclasses-of-model-like-types)和本机 2.13.4 有界实例核对。因此响应、bar、factor 三层均须明确对应类型，不开启全局多态序列化来代替合同定义。

`StockDailyKlineService.assemble()` 是完整响应组装；上述每指标 build 是其子步骤。首批与续页都调用同一个 `assemble()`，不是算一次后再重复组装另一份相同响应。

#### 4.2.3 前端首批、续页和图层交接

`stockDetailApiTypes.ts` 区分日线 bar（必有四轨）和周月线 bar（原字段）。`fetchStockDetailKline()` 仍是同一个入口，以 `period=day` 与 `week/month` 的请求类型分别声明对应返回类型；通过函数重载保持现有调用方式，不新增 HTTP 端点或按是否缺字段猜回包版本。

在 `stockDetailViewModelAdapter.ts` 增加 `buildStockDailyTrendChannelPoints()`，将每根日 K 的日期、收盘价和 `factors.trendChannel` 转为现有 `TrendChannelPoint`。沿既有日期、数值及上下轨合同适配，不计算 EMA、不使用旧 API 响应类型拼造新结果。

| 位置 | 实施动作 |
| --- | --- |
| `StockDetailPage.loadStockDetail()` | 日 K 返回后同时生成原 viewModel 和首批通道点；`StockDetailLoad` 增加 `dailyTrendPoints`，与首批 candles 一同保存，之后才进入 ready。首批图层无须再等待另一请求。 |
| `useStockDailyHistory.loadPage()` | `HistoryPage` 保存必有 `trendPoints`；先完成本批原日期/游标核对、candles 转换、通道点转换和九转读取，再一次提交 `nextEndDate`、candles、pages。失败时不推进游标、不追加部分数据，重试同一 `endDate`。现有代码先写游标再转换的顺序须随本次接入调整。 |
| `StockChartWorkspace` | 用 `initialTrendPoints` 替代旧 `trend` 对象，类型为 `readonly TrendChannelPoint[]`；日线传入首批数组，非目标周月线传空数组并维持禁用。合并历史页的 `trendPoints` 与首批点，沿已有 `buildTrendChannelLines()` 和 `TrendChannelPanePrimitive` 绘制。 |
| 开关和历史状态 | 移除页面的 `useStockTrendChannel()` 调用、`onTrendSelect` 请求回调，以及历史控制的 `loadTrend/ensureTrend/retryTrend`、独立 phase 和通道失败重试 UI。`changeOverlay()` 只控制绘制；未选择通道时加载的历史页仍保存四轨，之后打开无需补请求。 |

保持页面初始图层、画法、着色、盘口和页面日期。首批失败由 `loadStockDetail()` 处理，本地续页失败由 `loadPage()` 处理并保留已加载图表及当前视野；切证券、切页面日期或离开日线沿现有取消和迟到响应隔离，不创建跨页面通道缓存。

旧通道接口读取的是 DG 后台已生成的股票日线趋势通道结果文件，不是首屏计算缓存。接入后每个日 K 请求计算自己的目标与预热，浏览器保留该批结果供开关重复使用；不同 HTTP 翻页请求不复用首屏 EMA 状态。旧前端请求模块与后端接口按 §5 清理，阶段二只保证新页面不再调用，不提前改变旧路由限制。

#### 4.2.4 本地与 Prod 范围

| 环境 | 保持的现有行为 | 本次增加与验收 |
| --- | --- | --- |
| 本地 DG | 由 page-init 锚定日期；首屏含盘口、续页不含；每批最多 500 根、沿实际 `nextEndDate` 续取，保留日 K 内联九转 | 每批日 K 必有四轨，入口不依赖旧开关和旧通道目录；首批与至少一批续页验收。 |
| Prod | 原 page-init 盘口、原日 K 参数和范围计算、原 meta；前端原先不创建本地 historySeed 的行为保持 | 现有日 K 回包增加四轨，首屏可展示；不添加 `nextEndDate`、本地九转字段、首屏盘口迁移或新的分页流程。 |

页面入口修改沿 §4.5；旧通道开关关闭、两个旧目录不存在时，两个已接入环境的日线均应支持新通道。缺行情仍走各自原有日 K 错误/空态，不改成关闭功能或回退旧源。

#### 4.2.5 影响面、测试与预算

代码落点为：计算清单与版本/字段表、股票日线服务及请求/结果检查、周月线清单调用、股票 schema/路由响应声明、页面能力判断、App 装配、前端 API 类型与 adapter、`StockDetailPage`、`useStockDailyHistory`、`StockChartWorkspace`。原股票首屏与本地 DG 方案/LLD同步记录本次后续切换，保留已有实施与生产证据。

后端至少覆盖 `tests/test_stock_daily_kline_service.py`、`tests/app/technical_indicators/test_stock_daily_integration.py`、`tests/app/technical_indicators/test_stock_daily_source_repair.py`、`tests/web/test_wealth_stock_detail_api.py`、`tests/web/test_stock_daily_technical_indicator_api.py`，同步迁移 `tests/stock_daily_kline_helpers.py` 等日线夹具；新增 `tests/test_stock_period_kline_service.py` 隔离验证周月线清单、组装和原 JSON。基础周期计算继续引用现有 `tests/foundation/technical_indicators/test_stock_period_calculation.py` 的适用合同，不把无关正式 PG 测试整组运行。验证日线有四轨且参数/版本匹配，周月线计算指令、字段集合不变；验证真实 `model_dump`、HTTP JSON、OpenAPI，避免嵌套类型漏字段。本地与 Prod 分别装配隔离应用，不能用本地通过代替生产路径合同。

前端覆盖 `stockDetailViewModelAdapter.test.ts`、`useStockDailyHistory.test.tsx`、`StockChartWorkspace.test.tsx`、`StockDetailPage.test.tsx` 及受 API 类型影响的周月线测试。正向覆盖首批、续页、未选通道先翻页后打开、反复开关、切证券/日期、周月线切换；反向覆盖日线缺轨/非有限值/错日期、续页失败后原游标重试、迟到响应丢弃、旧接口请求次数为零。夹具按新日线/原周月线合同分别构造，预期四轨用独立手算或 Decimal 参考，不调用待测 builder 生成 expected。

沿 §3.4 的工作区算子源码路径运行；不为开发安装包或改变部署。前端执行 `npm --prefix wealth run typecheck`、相关 Vitest 和 build，并将缓存、编译产物等本次输出放到工程外临时目录；浏览器核对网络只走日 K、首批/续页数据和图形、开关、失败重试、盘口及页面日期。

预算沿当前 App 配置：默认公共清单是 7 组 MA 加 BOLL/MACD/KDJ/price 共 11 项；本地分页原有九转后为 12 项，加通道后为 13，Prod 沿原选择从 11 增为 12，均低于现有实例上限 16。共享行情取各算子的最大前置需求，不叠加读取或复权；目标 R、最大前置 500 时交付 `R+500`，R=500 时为 1,000 根，合法历史不足据实减少。计入新增 DTO 构造、前端点转换、正常请求、取消清理、完整重试和最后验收，不新增或抬高耗时/内存/文件阈值。

真实有界验收优先复用原股票页面 LLD 的 `600519.SH`、截止 2026-11-19、首批和至少下一批各最多 500 根的来源与接口证据；新四轨及新调用仍须实际验证。目标环境覆盖不足时保留失败原因、先选当前正式覆盖内的有界窗口并记录选择依据，不回填数据或跨环境兜底。记录各请求实际源行/文件、SQL处理量、组装编码、总耗时和取消至资源归还，不能把旧实测当成接入后结果。核对范围为单证券有界窗口，不全市场扫库；真实 Prod 访问和部署仍遵守原授权边界。

### 4.3 阶段三：逐指标组装整理与上证日线接入

本阶段包含两个依次验收的步骤，四个总阶段不重新编号。先完成管理员指定的组装架构修改，再接入上证；不将该重构提前到阶段二，也不推迟到旧业务清理阶段。

**2026-11-25 设计补齐。** 本节将管理员确认的职责划分落实到两个步骤的函数、类型、调用方、前端交接及验收，不再把这些工程细节留作“开工前定稿”。阶段二股票接入验收是本阶段的执行前置条件：阶段三使用其日线类型、通道 build 和接口基线，不能把阶段二尚未实施说成阶段三还缺业务决定。本段记录阶段二开发前的设计补齐；阶段二实施现状见 §10；阶段三后续实施和审计见 §12。

#### 4.3.1 公共组装与每指标独立函数

重构前，`build_kline_factors()` 位于日线服务，但同时被股票日线与周月线 `assemble()` 调用。它是固定 MA/BOLL/MACD/KDJ 映射，不是指标算法，也不是所有算子的自动处理器。目标是公共映射只维护一份，各业务显式选择自己的指标，不在公共函数中累积 `day/week/month` 判断。

新增 `src/biz/services/wealth/market/stock_detail/stock_kline_factor_mapper.py`，承接当前两个股票调用方的公共职责：

| 函数 | 职责与输出 |
| --- | --- |
| `stock_calculation_key()` | 从现有 `_calculation_key()` 迁入公共模块，以算子 ID 和实际参数形成原有键；所有调用方同步迁移，无旧名兼容别名。 |
| `index_stock_calculation_results()` | 每请求一次整理 `CalculationResult.calculations` 的索引，保留各数值元组引用；不复制整列、不读源、不算算法。 |
| `build_stock_ma_factors()` | 按实际 MA 周期取当前根，返回 `StockMovingAverageDto`，保持现有周期和字段名。 |
| `build_stock_boll_factors()` | 返回现有 `StockBollDto`。 |
| `build_stock_macd_factors()` | 返回现有 `StockMacdDto`，保留 hist 到 macd 的既有字段映射。 |
| `build_stock_kdj_factors()` | 返回现有 `StockKdjDto`。 |
| `build_stock_trend_channel_factors()` | 将阶段二的独立通道函数移入该模块，仍只由获准的日线业务调用，返回 `StockTrendChannelFactorsDto`。 |
| `build_stock_common_factors()` | 明确调用 MA/BOLL/MACD/KDJ 四个独立函数，返回这四组已组装对象的命名映射，供日线和周月线复用；不包含趋势通道或周期分支。 |

日线 `assemble()` 使用公共组装结果，加上独立的通道 build 结果，构造阶段二已确定的日线 factor/bar/响应。周月线 `assemble()` 使用公共组装结果，维持原 factor/bar/响应及自己的周期日期、九转等组装；本次没有专属指标时不造空专属函数。后续共性指标放入独立指标 build 并由公共组合调用，专属指标由所属业务 `assemble()` 显式调用。

原 `_calculation_key/build_kline_factors` 的消费者须全量迁移，周月线不再从日线服务导入公共映射。各 build 不决定要算哪些算法，不修改通用结果，不获取行情；上游请求清单仍由业务装配负责。采用直接函数组合，不新增策略注册表、处理器链、继承体系或周期兼容分支。

本次公共映射范围是已核实的股票日/周/月调用方；不要求指数业务依赖股票私有 DTO，也不为追求统一重写未涉及的业务。该步骤不改变阶段二已经发布的字段合同、不增加算法或来源；上证的新增组装继续位于指数业务路径。

各函数的输入交接固定如下：`index_stock_calculation_results(result.calculations)` 每请求调用一次，返回以 `stock_calculation_key(id, parameters)` 为键、以字段名到原数值元组的映射为值的索引。MA build 接收该索引和当前根下标，按原七个周期分别取值；BOLL/MACD/KDJ/趋势通道 build 接收本指标已验证的字段映射和下标。`build_stock_common_factors()` 接收请求索引和下标，调用四个公共 build，返回键为 `ma/boll/macd/kdj` 的对象映射。各业务 `assemble()` 先复用公共组合，再处理自己的内容；日线显式调用通道 build，价格、九转、日期和游标仍由原步骤处理。输入已经过原合同检查，每个 build 不重复校验、不另算指标。

```mermaid
flowchart TD
    A[业务后端指定本次计算清单] --> B[算子库返回 CalculationResult]
    B --> C[index_stock_calculation_results]
    C --> D[build_stock_common_factors]
    D --> E[MA / BOLL / MACD / KDJ 各自的 build]
    C --> F[日线 assemble 调用 build_stock_trend_channel_factors]
    E --> G[日线 assemble 合成日线响应]
    F --> G
    E --> H[周月线 assemble 合成原响应]
```

重构前保存独立字面金样本及当前日/周/月 JSON 基线，重构后逐项验证相同输入下的字段、数值、日期、空值、游标与错误行为一致。新增 `tests/test_stock_kline_factor_mapping.py` 验证每个指标 build 的独立字段映射，包含不同 MA 周期不可混用、公共指标只维护一处、日线有通道而周月线不计算/不输出通道；再跑阶段二后端/页面及新增周月线服务回归。不得从待测 builder 生成 expected，或为通过测试修改已有正确字段和行为。

改动只有请求内结果读取和对象组装，不新增源读取、复权、SQL计算、状态持久化或重试；沿原请求预算，计入重构后的组装、错误清理、取消、重试和最后回归开销。记录前后源行/文件及计算次数一致，实测总请求费用；没有未测依据的新性能阈值。实现、接口与原方案对账后，独立审计该步骤，再进入上证接入。

#### 4.3.2 上证日线接入：计算与组装

本步骤只给 `000001.SH + day` 已接入算子库的日 K 请求增加四轨。本地与 Prod 页面均沿现有每批 500 根和 `meta.nextEndDate` 翻页；**上证 Prod 原来已有日 K 游标，不能套用股票 Prod 不翻页的情况。** 其他指数、指数周月线、分钟线、顶底识别及波段接口不新增通道。基础指数日线行情继续使用，旧独立通道接口留至阶段四清理。

**计算指令与结果分组。** 当前 `SSE_DAILY_CALCULATIONS` 的七个 MA 加 BOLL/MACD/KDJ，不仅供指数日线使用，也被 `index_period_technical_indicators.py` 的周月线调用；`apply_calculated_kline_factors()` 同样被日线和周月线查询调用。本步骤保留这份公共清单与公共映射的现有输入，不向其中直接塞入通道。

在 `index_detail_kline_query_service.py` 增加 `index_daily_calculations(ts_code, *, include_price_and_nine_turn)`：先返回原清单，本地加原有 price、nineturn，最后仅对上证日线追加 `trend_channel`、空参数。App 日线装配及相应 query 的完整结果检查都使用这个函数，不复制另一份期望清单；原实例相对顺序保留。App 移除静态 `_DG_CALCULATIONS` 的使用，本地显式传 `include_price_and_nine_turn=True`，Prod 为 False。周月线继续原公共清单，不调用该日线函数。

`_build_recent_daily_kline()` 先验证实际返回的实例与本次请求一致，再分出 price、nineturn 和上证趋势通道；仅将原十个公共指标交给 `apply_calculated_kline_factors()`。`_build_calculated_daily_kline()` 同样先检查完整结果，再分出通道、交公共指标给原映射。沿原日期/根数对应检查，趋势通道按算子定义检查空参数、版本 `1.0.0`、四字段、根数和有限数值；不修改共享结果协议，也不把缺轨当正常 PARTIAL。空目标无计算结果时仍返回合法空页。公共映射继续核对自己实际接收的十个实例，不能让它接收十一项却仍核对十项，也不能用“忽略未知项”吞掉错误。

**环境与调用不变。** `index_detail.py:query_kline_response()` 沿原分支调用 `run_index_daily_kline()`。DG 使用现有 `end/latest_rows` 和 `calculate_with_source()`；Prod 先按原交易日窗口选择目标日期，再沿当前 `_prepare_calculation/_calculate_library` 范围计算并收集同批 OHLC，保留现有辅助行情查询。保留各自历史下界，不强制改 Prod 为按根数来源。通道在同一请求中与公共指标共享行情，历史需求取最大值，不能再请求旧通道接口、旧缓存或全历史计算器。

**字段与类型。** 上证目标响应的每根 K 线必有 `factors.trendChannel`，四字段是有限数值，单位为指数点，不强制舍入：

| 算子字段 | JSON 字段 | 含义 |
| --- | --- | --- |
| `short_upper` | `shortUpper` | 最高价的 25 周期 EMA |
| `short_lower` | `shortLower` | 最低价的 25 周期 EMA |
| `long_upper` | `longUpper` | 最高价的 90 周期 EMA |
| `long_lower` | `longLower` | 最低价的 90 周期 EMA |

在 `src/biz/schemas/wealth/market/index_detail.py` 增加以下类型；原公共 factor/bar/response 不加可空通道，其他指数及周月线 JSON 字段集合不变。

| 类型 | 具体约定 |
| --- | --- |
| `IndexTrendChannelFactorsDto` | 上表四个必有数值，无状态、说明或 JSON 文本。 |
| `IndexSseDailyKlineFactorsDto` | 复用 `IndexKlineFactorsDto` 的四组公共指标，增加必有 `trendChannel`。 |
| `IndexSseDailyKlineBarDto` | 复用原行情字段，将 `factors` 明确标注为上述上证类型。 |
| `IndexDetailSseDailyKlineResponseDto` | Prod 目标响应，明确 `period=day`、上述 `bars` 类型和原 `IndexDetailSseKlineMetaDto`；不添加九转字段。 |
| `LocalIndexDetailSseDailyKlineResponseDto` | 保留原本地日线类型的必有 `nineTurnMarkers`，明确覆盖 `bars` 为上述类型。 |
| `IndexDetailSseDailyKlineDebugResponseDto` / `LocalIndexDetailSseDailyKlineDebugResponseDto` | 在 debug schema 中分别保留相应普通响应的完整 bars、meta 和本地九转，`debugInfo` 为原诊断类型。 |

原 `index_detail_field_mapper.py` 内的公共映射拆为 `build_index_ma_factors/build_index_boll_factors/build_index_macd_factors/build_index_kdj_factors`，由 `build_index_common_factors(row)` 返回四组对象的命名映射；不改变源列、正常空值和 hist 到 macd 的原映射。新增 `build_index_trend_channel_factors(fields, index)` 只做四轨映射。现有 `build_kline_bar()` 与新增 `build_index_sse_daily_kline_bar(row, trend_factors)` 共用从原函数提取的 `build_index_kline_bar_fields(row)` 和公共指标组合，分别构造原 bar 和上证 bar。行情和公共指标映射各维护一份，公共 build 不判断周期/代码，不导入股票 DTO；本次只拆直接受影响的组装，不重写其他指数业务。

`_calculated_daily_response()` 的上证日线分支按目标下标调用通道 build、上证 bar build，选择本地/Prod 响应；其他指数仍用原 bar 和响应。首批、续页都经过这里，只有当前请求的一次组装。类型覆盖必须到 factor、bar、普通/本地 response 和 debug response 每一层，不能把子类对象塞进仍标注为公共基类的字段而丢失四轨。

`index_detail.py`、`index_detail_debug.py` 的响应声明，`debug_response.kline_response()` 的投影类型选择及 `add_openapi_responses()` 同步迁移。debug 使用当前 `project` 回调，不另算一次；普通与 debug 的行情、四轨、游标及本地九转一致，只保留原诊断差异。Prod 大于 500 根的旧请求仍沿原分支，不在本次新增算子支持，也不补空通道冒充目标响应；页面始终显式请求 500 根。旧独立通道端点的 2,000 根上限留至阶段四引用审计，本次不改其合同。

#### 4.3.3 上证前端首批、续页及图层交接

`indexDetailApiTypes.ts` 增加与上述上证日线 factor/bar 对应的类型，普通与 debug 消费者同步使用；保留其他指数及周月线原类型。`fetchIndexDetailKline()` 沿原 URL、参数和调度，目标日线类型明确包含四轨，不通过字段碰巧存在与否选择新旧来源。

在 `indexDetailViewModelAdapter.ts` 新增 `buildIndexDailyTrendChannelPoints(response)`：对目标上证日线逐根读取 `tradeDate/close/factors.trendChannel`，映射为已有 `TrendChannelPoint`。每根都有四轨，日期和该根行情对应；缺轨、非有限值等按本批合同错误失败，不沿旧 adapter 丢点后显示一部分，也不前端计算 EMA。其他指数返回空通道点数组，不增加请求。

| 位置 | 修改及交接 |
| --- | --- |
| `useIndexDetailController` | 首批日 K 及四轨全部转换成功后，同一次状态提交保存 `dailyTrendPoints`、viewModel、九转和 historySeed。删除独立通道 AbortController、`requestTrend/commitTrendSuccess/commitTrendFailure/retryTrend`，不再因该独立请求制造页面 PARTIAL。 |
| `IndexDailyHistorySeed` / `HistoryPage` | seed 保存首批通道点；每页必有 `trendPoints` 数组，上证来自本批四轨，其他指数为 `[]`。删除旧 `trend` 异步加载状态。 |
| `useIndexDailyHistory.loadPage()` | 先完成原游标核对、K 线、九转和通道点转换，成功后一起更新页数组与 `nextEndDate`。失败保留原图和游标，使用原截止日重试；不得先推进游标再发现缺轨。 |
| 历史缓存与展示 | 保留现有预取阈值、缓存页和显示页规则。用户拖回近期时，回包暂存；再次拖入历史范围时，该页 K 线与通道点一并展示。切证券/日期、离开日线沿原取消和所有者检查丢弃迟到回包，不重置缩放、位置或用户叠加选择。 |
| `IndexChartWorkspace` | 改接 `initialTrendPoints`，与历史可见页点合并后交原 `buildTrendChannelLines/TrendChannelPanePrimitive`。删除独立 `trendPhase` 依赖；开关只切绘制，保持原默认叠加及逐日收盘相对下轨的着色。 |
| `IndexDetailPageView`、`IndexInfoRail`、`IndexTechnicalTab` | 传递首批 `dailyTrendPoints`；技术面四轨摘要只取首批最后一根日 K，历史翻页不改变摘要。删除 `onTrendRetry` 及通道专用加载/失败展示，沿日 K 原页面状态；切周月或分钟仍保留原右栏日线语义。 |
| 既有九转 | DG 首批/续页继续内联九转，Prod 继续原独立九转。历史异步图层的加载、失败与重试只保留仍需它的九转，不因删除通道分支删掉九转逻辑。 |

页面链不再引用 `fetchTrendChannel()`、旧通道 adapter、`QuoteTrendChannelQueryService`、`TrendChannelCalculator` 或旧缓存。阶段三移除已迁移页面中的调用、状态和专用重试；阶段四才按全部引用删除无消费者的模块、路由、schema 和专用测试，不恢复兼容分支。page-init 的支持范围仍只有上证日线；其他业务来源和能力不扩大。

```mermaid
sequenceDiagram
    participant P as 首批controller或历史loadPage
    participant A as 原index-detail/kline接口
    participant W as run_index_daily_kline
    participant Q as IndexDetailKlineQueryService
    participant L as 算子库与本环境行情来源
    P->>A: 上证day、endDate、limit=500
    A->>W: query_kline_response
    W->>Q: build_kline或query_kline加debug投影
    alt 本地DG
        Q->>L: calculate_recent回调到calculate_with_source
    else Prod
        Q->>Q: 原交易日窗口选择
        Q->>L: calculate回调到原范围计算
    end
    L-->>Q: 本批行情、公共指标与趋势通道
    Q->>Q: 公共映射、通道build、对应日线类型
    Q-->>W: 同批bars、四轨、原游标及本地九转
    W-->>P: 原编码与HTTP返回
    P->>P: 全部转换成功后保存该批及游标
    Note over P,L: 首批与续页各计算自己的目标批次；开关及缓存内拖动不增加请求
```

#### 4.3.4 预算、恢复和测试验收

**2026-11-25 读取核查范围纠正。** 本要求仅约束趋势通道新增算子和本次股票、上证接入：同次请求共用行情和复权结果，组装不另取数，页面不并行保留新旧通道请求；具体依据和必要重叠见[§11](#trend-channel-read-scope)。上一轮将既有 DG 交易日历、Prod 通用定位/取价和复权读取整改设为上证接入前置，超出了本需求，现撤回；不因此改造其他周期或增加阶段三前置任务。原两个步骤和验收顺序保持。

纯股票组装整理沿 §4.3.1，不新增计算或源读取。上证 DG 原有 `7 MA + BOLL + MACD + KDJ + price + nineturn = 12` 项，加通道为 13；Prod 原有 `7 MA + BOLL + MACD + KDJ = 10` 项，加通道为 11。其他指数和周月线项数不变，不提高现有实例上限 16。数字依据是当前 App 清单和 `src/foundation/config/settings.py`。

通道申报 500 根，整次仍按 `R+W` 交付行情，`W=max(本次各算子实际历史需求)`；只有其他指标历史需求均不超过 500 时，R=500 才是 1,000 根计算输入。不是物理文件量，不按各指标叠加。请求中断后按同一截止日完整重试，不持久化跨请求 EMA。正常首批、续页，再以首批相同截止日取消并完整重试，这组验收按 `2×(R首批+W首批)+(R续页+W续页)+C取消已交付` 分别记账；独立参考与回归测试另外计量，不能说整个验收只有这些读量。

沿实际生效配置；当前 Settings 默认 SQL 内存 128 MiB、请求内存 256 MiB、总目标 8,000 ms，其中清理保留 2,000 ms。这是已有预算，不是新接入的实测保证，不调整环境值。开发后记录定位、源行/文件、SQL 处理、组装编码、总请求、取消到资源归还、完整重试和最后验收成本。连接、算子清理及 HTTP 失败继续沿原 `_execute` 和释放流程，清理失败不能报告成功，不新增自动重试或全历史回退。

| 硬口径 | 代码及合同落点 | 必要验收 |
| --- | --- | --- |
| 公共映射单处维护、每指标独立 build | 股票 mapper 及日/周/月 assemble；指数 mapper 的公共与通道 build | 新增 `tests/test_stock_kline_factor_mapping.py` 和 `tests/test_index_trend_channel_mapping.py`。字面金样本验证字段、MA 参数及 hist 映射，expected 不调用待测 build；同输入下改前/改后日周月 JSON、日期、空值和错误行为一致。 |
| 只给上证日线追加通道 | 日线清单、App、query 完整结果检查；原公共清单/周月线保持 | `tests/app/technical_indicators/test_index_daily_kline_integration.py` 验证日线；`tests/web/test_wealth_index_detail_weekly_monthly_api.py` 的 local/Prod 隔离应用验证周月线实际计算请求及普通/debug JSON 不包含通道。其他指数和周月线原实例及相对顺序保持；目标日线重复、缺项、错参数和错版本反例失败。`tests/integration/test_index_period_derived_from_daily.py` 比较数据库中的行情派生结果，不经过本次指标组装，且默认跳过，已从本步验收清单移除；不得将其跳过结果计作本步通过。 |
| 普通/debug 都完整返回四轨 | schema、mapper、debug 投影、路由及 OpenAPI | 上述 App 测试及 `tests/web/test_wealth_index_detail_api.py`、`tests/web/test_wealth_index_detail_dg_kline.py`、`tests/test_index_detail_field_mapper.py`；真实序列化、HTTP JSON、OpenAPI 均声明四个必有数字；普通/debug 日期、数值、游标及本地九转一致，其他响应不增加 null 字段；空页成功。 |
| 首批/续页和摘要只用当批结果 | adapter、controller、history、PageView、chart、sidebar | `indexDetailViewModelAdapter.test.ts`、`useIndexDetailController.test.tsx`、`indexDailyHistoryRequests.test.tsx`、`IndexChartWorkspace.test.tsx`、`IndexDetailPage.test.tsx`、`IndexTechnicalTab.test.tsx`；覆盖先翻页后开通道、反复开关、缓存回包暂存、切日期/指数/周期、迟到回包丢弃、摘要不被历史页改写。 |
| 失败不推进游标、不回退旧链 | 日 K 失败及取消，通道旧调用退出 | 缺轨或错误页后保持原图、原游标并重试原截止日；删除仅用于拦截旧实现调用的测试代码，保留新回包、失败重试与资源释放验证。九转合法空标记、MA/BOLL 正常历史不足的 null 不误拦；Prod 九转原重试保留。 |
| 500 根预热、每轨误差 ≤0.01 | 共享算子及 §3、§7、§9 的独立参考 | 固定上证样本复用来源和 SHA，参考从样本首根计算，被测从目标前 500 根初始化，逐轨最大误差比较；同起点分批一致性另验，不把固定样本起点冒充全部历史。 |

后端分别装配 DG 与 Prod 隔离应用，不能以 DG 成功代替 Prod 合同。真实只读验证限定 `000001.SH` 的首批和下一批，各最多 500 根，优先复用固定样本截止 2026-08-07；实际覆盖按当次来源核验，不覆盖时记录原因后选已覆盖窗口，不回填数据或跨环境取数。记录代码版本、参数、返回日期、数值与费用，不全市场或全历史读取。沿 §3.4 源码启动，受保护 D3 与无关正式 PG 测试不整组运行。

前端执行 typecheck、上述相关测试及 build，产物和日志放工程外临时目录。浏览器核对首批/续页网络、四轨与图形颜色、开关和失败重试；没有旧通道请求，仍需的其他业务请求保持。旧性能记录只作基线，接入后费用必须实际记录。

本轮设计核对使用 CodeGraph `codegraph_explore`，并核验 App、日线/周月线 query、schema、API、OpenAPI、controller/history/chart/sidebar、相关测试及配置。共享常量和跨语言消费者以实际 import、构造和调用补齐，不能把 CodeGraph 返回“无调用方”当作可删除依据。设计无新增待拍板业务项；阶段二验收及该步现状复核是执行前置，股票组装审计通过后才进入上证步骤。部署、正式写入另按原阶段授权。

### 4.4 新旧接口和数据集的具体处理

| 对象 | 当前实现依据 | 接入后 |
| --- | --- | --- |
| 股票、指数日 K 接口 | 现有日线 App 装配、计算清单、结果组装和前端 API 类型 | 保留入口及既有日 K 行为，在目标日线指标中增加四轨；图层与其他指标使用同批日期、复权和游标。 |
| 股票旧独立接口 `/api/v1/wealth/market/stock-detail/trend-channel` | 删除前为 `stock_detail_trend_channel.py` → `StockDetailTrendChannelQueryService` → `StockDailyTrendChannelLakeReader` | 阶段四已删除该路由、专用查询、schema、读取器及能力检查；隔离HTTP返回404，无代理或兼容入口。四轨由现有日K接口返回。 |
| 上证旧独立接口 `/api/v1/quote/detail/trend-channel` | 删除前为 `src/biz/api/quote.py` → `QuoteTrendChannelQueryService` → 全历史查询、专用计算器及缓存 | 阶段四已删除该路由及专用查询、计算器、缓存、schema和前端请求；隔离HTTP返回404。`quote.py`其他四个路由/函数保持。 |
| 股票日线趋势通道结果数据集 `gold/indicator/stock_daily_trend_channel` | 旧读取器按股票、截止日期和根数读取正式 Parquet 结果 | 新算子、新日 K 接入和新页面入口均不依赖它；本次不处理该 DG 数据集的字段、生产、检查或文件，也不决定停产。 |
| 股票日线趋势通道续算状态数据集 `gold/indicator/stock_daily_trend_channel_state` | 旧数据生产需要数值续算；旧页面能力函数检查目录，但旧 API 读取器不读它 | 新算子在本请求内维护四个 EMA 数值，不读该文件；该 DG 数据集及其字段、生产、检查和文件均不在本次清理范围。 |
| 股票、指数基础行情和股票复权因子数据 | 本环境现有日 K 来源和共享库读取装配；旧上证查询读取 `IndexDailyServing` 的 OHLC | 继续使用，保留现有读写职责；退出的是旧通道专用计算/成品读取，不能清理基础行情及复权因子数据。 |

### 4.5 股票页面入口判断与失败处理

旧检查的目的，是在本地具备预计算文件读取条件时才展示入口。`resolve_stock_daily_trend_channel_capability()` 依次检查 `APP_ENV` 为 `dev/local`、`WEALTH_LOCAL_LAKE_STOCK_DAILY_TREND_CHANNEL_API_ENABLED` 开启、正式 Lake 根路径及可读性、DuckDB 可发现、结果和续算状态两个目录均可读。它只检查环境与目录，不读取具体股票记录，不检查某日期分区是否齐备，也不查询 Dagster instance、任务或资产状态。`tests/test_stock_daily_trend_channel_capability.py` 使用空的两个目录即可验证旧检查返回启用。

阶段二按以下位置修改，不重做数据可用性检查：

1. 股票页面初始化的 `_page_options()` 移除旧能力函数调用及相应导入。在本环境已接入股票日线算子能力的页面中，`supportsTrendChannel=true`，`availableMainOverlays` 包含 `TREND_CHANNEL`；沿既有图层限制只在目标日线使用，不顺带开放周月线或分钟线。
2. 新页面不继承旧接口的 `dev/local` 限制、专用开关和通道目录检查；本地 DG 与 Prod 沿各自已接入的日 K 装配。算子库读取 DG 行情所需的原有组件和配置仍保留，不把“去掉旧通道检查”扩展成绕过日 K 来源合同。
3. 当前无行情、合法短历史和源读取失败继续按现有日 K 合同处理；`supportsTrendChannel` 表示功能支持，不随单次空行情或 I/O 失败关闭。不能以 `false` 隐藏算子计算或读取错误，也不新增独立开关、就绪查询、重试和额外取数。
4. `src/app/api/v1/router.py` 对旧路由的挂载、旧 API 请求内部的检查，在旧接口仍保留时只控制旧接口；不得因页面修改而让它提前对生产开放。阶段四按全部引用删除无消费者的旧路由、能力函数、Settings 字段、配置说明和专用测试。

性能和恢复沿现有日 K 请求：不为入口判断增加文件内容读取、数据库查询或 Dagster 请求；计算输入按 §3.3 的同批最大历史需求核算。取消、超时、编码错误和重试使用现有资源清理与响应规则，失败不返回新旧结果混合的批次，也不退回旧通道数据；前端失败后保留已加载图表及原有重试行为。

阶段二与阶段三分别审计、开发和验收，不在阶段一同时改业务。共享包发布与业务部署是各阶段验收后的独立动作；当前没有自动部署或正式写入授权。新算子阶段一通过不等于两个页面接入已完成。

## 5. 阶段四：旧业务清理与总验收

### 5.1 目标、范围与禁止项（2026-11-26 纠正）

目标是删除股票、上证新页面已不再使用的旧趋势通道业务实现，并验证新算子及页面功能保持。阶段2、3的四轨接入已完成，不重做算法、不增加字段、不改变500根预热、误差口径、分页、单位或通道画法。

本次不处理 DG 数据生成、数据集、正式文件或生产检查：不修改股票日线趋势通道结果和续算状态数据集，不改生成 SQL、schema、版本、日更、repair、bootstrap、readiness、catalog、日审计或任务状态，不决定停产，也不做历史文件迁移。方向专项清理后续单独做。此前把这些内容纳入阶段4或列为开工前提，是范围错误，现撤回。

旧专用模块删除时，其内部已无用途的类型、位置或方向字段随模块一起退出；不据此开展对其他业务或 DG 方向字段的专项清理。新算子内存中的 EMA 数值递推继续保留。

### 5.2 删除与保留对象

| 对象 | 本阶段动作 | 保留边界 |
| --- | --- | --- |
| 上证旧独立接口与实现 | 删除 `src/biz/api/quote.py` 中仅属于 `/detail/trend-channel` 的路由和导入；删除旧 `quote_trend_channel_calculator.py`、query service、query、schema、缓存及专用测试。 | `quote.py` 的其他接口、新日 K App/query、算子库计算和指数基础行情保留。 |
| 股票旧独立接口与实现 | 删除旧 trend-channel API/query/schema、旧路由挂载、Web 旧成品 reader/contract、旧 capability、专用 Settings 开关与专用测试。 | 仅清理 `src/` 中旧 Web 读取代码，不修改 DG 自己的字段合同或生产实现；股票新日 K、行情及复权读取保留。 |
| 旧前端请求及专用模块 | 删除指数旧 `trendChannelApiClient.ts/trendChannelAdapter.ts`、股票旧 trend-channel API/adapter/hook、无调用方的专用类型和测试；混合文件只去掉旧部分。 | 新首批/续页数据、四轨适配、controller、图层开关和右栏摘要保留。 |
| 测试中的旧模块拦截 | 删除仅为“不调用旧实现”而保留的旧模块 import、monkeypatch、替换函数和对应断言，不建立替代的旧类或兼容模块。 | 新算子字面数值、缺轨/非有限值、整批失败、取消清理、同参重试和页面回包断言保留。 |
| 固定历史行情样本 | 保留 `tests/fixtures/quote_trend_channel/000001_sh_daily_input.json` 及其来源、SHA和独立参考测试。 | 它是新算子误差测试的输入数据，不是旧计算实现；不因目录含旧名称而删除。 |
| 股票、上证页面共用的通道画图代码 | 保留 `wealth/src/shared/charts/trend-channel/`：`trendChannelGeometry.ts` 将四轨和日期整理成线段，`TrendChannelPanePrimitive.ts` 将线段画到图表；对应测试及新页面使用的 `TrendChannelPoint` 等类型保留。 | 这是两个页面正在使用的产品代码；不改画法、颜色、缩放或图表位置。 |
| DG及正式数据 | 本次无修改、无迁移、无停产、无正式查询或写入动作。 | DG当前的数据集、文件、字段、生产、检查与日审计保持；不修改 DG 方案与LLD。 |

清理依据为当前业务调用和实际用途，不做按目录或关键词整体删除。只删除已无业务调用的专用实现；旧模块自己的测试引用不构成保留旧实现的理由。历史文档保留适用版本，现行说明指向新链路。

固定行情文件是测试输入，不是产品功能或旧计算器。`tests/foundation/technical_indicators/test_trend_channel_calculation.py` 在运行测试时读取它，用本文件中的独立 Decimal 公式作为参考，与真实算子 SQL 的四轨结果比较；500根预热用例的参考从样本首根开始，被测从目标前500根开始。固定输入用于检查以后修改算法、SQL或分批处理时，是否破坏原来已验证的结果；它只证明这份历史样本上的结果，不能替代所有行情的正确性验证。正式页面和接口不读取该样本，也不调用测试中的参考公式。样本来源及误差证据见§7.1。

两个产品调用方分别是 `wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx`（股票日线）和 `wealth/src/features/index-detail/chart/IndexChartWorkspace.tsx`（上证日线），都调用 `buildTrendChannelLines()` 和 `TrendChannelPanePrimitive`。每个页面用自己的日K回包日期、四轨及收盘价生成线段，再由绘制类转换为屏幕坐标并画线；共用的是同一份画图实现，各自的数据和图层实例独立。这里不计算EMA、不读取行情文件、不执行数值对照测试；对应测试另放在测试文件中。

### 5.3 本轮先取消的测试检查

本节记录阶段四开工前已取消的检查；随后已完成的接口、旧模块删除和完整验收见§14。

本轮只落实管理员明确取消的三处后端测试拦截，不提前删除接口和旧业务模块：

- `tests/app/technical_indicators/test_index_daily_kline_integration.py`：去掉对旧上证计算器和缓存的导入、报错函数及替换；保留本批计算、四轨、普通/debug、游标和九转断言。
- `tests/app/technical_indicators/test_stock_daily_source_repair.py`：去掉对旧股票成品读取器的导入和替换；保留缺轨/非有限值导致整批失败、资源释放及重新请求验证。
- `tests/web/test_wealth_stock_detail_api.py`：去掉对旧能力函数的替换；直接验证股票页面声明日线趋势通道能力及原回包。

这三项不读取或改动正式 DG/Prod，也不改业务实现。其定向回归通过后，本轮检查删除才算完成。阶段4其余旧模块清理按下一节约束实施。

### 5.4 后续代码清理的执行与验收

先核对本节删除对象的实际引用；再删除旧路由及其专用实现、配置和前端消费者；最后清理失去用途的旧专用测试和文档现行说明。新链路与共享代码不随旧目录一起删除，不保留兼容代理或空模块。

业务配置只删除服务旧接口的开关，不新增开关。清理不新增源查询、文件写入、计算或复权，因此本次新增正式查询和正式文件写入均为0；测试使用工程外临时夹具，沿已有日 K 和算子预算，不为删除代码抬高阈值。失败时保留测试结果，只纠正本阶段变更；不存在正式数据回滚或迁移续跑步骤，不触发正式任务或部署。

验收包括：旧专用模块运行引用清零；旧独立路由不再挂载；新股票及上证普通/debug日 K仍完整返回四轨，首批/续页、开关、摘要、失败和取消保持；股票日/周/月公共指标与非目标指数保持；固定行情误差样本、共享几何/primitive测试仍通过。相关后端定向测试、前端类型检查/相关测试及构建按原门禁执行，临时产物放工程外。DG生产、检查和正式文件均不作为本次验收或开工条件。

#### 5.4.1 混合测试与测试输入的具体修改清单（2026-11-26 开工前补齐）

当前代码中，下面的保留文件仍检查旧文件是否存在，或导入、模拟旧接口。只删除旧业务模块会使文件存在断言、模块导入或类型检查失败。因此，阶段四须在删除对应旧模块时同步完成下表修改；不能为这些测试保留旧实现，也不能整份删除仍验证其他功能的文件。

| 当前文件与依据 | 删除内容 | 保留内容 |
| --- | --- | --- |
| `tests/architecture/test_lake_console_retirement_guardrails.py`：`test_current_lake_consumers_and_clickhouse_tools_are_present()` 的文件列表 | 仅移除 `src/foundation/clients/local_lake/stock_daily_trend_channel_reader.py` 这一项。 | 该函数对其他现行文件的存在检查及本文件其余测试全部保留。这是仓库测试同步，不修改 DG 生产、数据集或检查实现。 |
| `wealth/src/features/index-detail/controller/useIndexDetailController.test.tsx` | 删除 `fetchTrendChannel` 导入、`vi.mock`、旧回包配置、仅针对该替身的调用断言，以及随之无用途的 `trendCalls` 和 `makeTrendPayload` 导入。 | 新日 K 首批、续页及缓存合并，四轨、摘要、开关、迟到响应、失败重试和九转用例；继续断言日 K 请求参数与次数。 |
| `wealth/src/features/index-detail/api/indexDailyHistoryRequests.test.tsx` | 删除 `fetchTrendChannel`、`makeTrendPayload` 导入，专门验证旧通道请求默认根数的整项用例，以及模拟 `/trend-channel` 返回的分支。 | 原日 K 请求参数、取消信号、首批500根与整页重试、四轨同批返回和原MACD映射用例；原研究路径的日 K 参数断言保持。 |
| `wealth/src/features/index-detail/debug/IndexRecognitionDebug.test.tsx` | 删除 `makeTrendPayload` 导入和模拟 `/trend-channel` 返回的分支。 | debug日 K、波段核对、九转、历史范围及请求次数等原有用例。 |
| `wealth/src/pages/index-detail/IndexDetailPage.test.tsx` | 删除 `makeTrendPayload` 导入、各处旧通道回包分支，以及 `mockFetch()` 的 `trend` 选项和调用方传入的旧请求报错函数。 | 页面首批、切指数/日期/周期、开关、摘要、日 K缺轨整页失败与重试、权限及其他模块的用例。 |
| `wealth/src/pages/index-detail/IndexDetailDailyWave.test.tsx` | 删除 `makeTrendPayload` 导入和旧通道回包分支。 | 普通页面不展示或请求波段核对功能的原有用例，以及新日 K输入。 |
| `wealth/src/features/index-detail/testing/indexDetailTestFixtures.ts` | 上述消费者同步清理后，删除 `TrendChannelRawResponse` 导入、`makeTrendPayload()` 和其专用 `rawBar()`。 | `makePageInit()`、`makeKline()`、`makeOrdinaryKline()`、`readyStatus()`；新日 K中的四轨输入继续保留。该文件只服务测试。 |
| `wealth/src/features/stock-detail/controller/useStockDailyHistory.test.tsx` | 删除 `fetchStockTrendChannel` 导入、对应 `vi.mock` 和仅针对该替身的未调用断言。 | 首批/续页数据交接、四轨合并、游标、九转、取消、失败与重试用例。 |
| `wealth/src/pages/stock-detail/StockDetailPage.test.tsx` | 删除只供旧独立通道请求使用的 `stockTrendChannel` 回包、成功/失败分支、`failTrend` 选项及调用方传参；相关用例名称按保留后实际验证的行为调整。 | 新日 K四轨、页面开关和摘要、首批/历史加载、日 K失败重试，以及页面其他功能的用例。 |

旧模块自己的专用测试随模块删除：`wealth/src/features/index-detail/api/trendChannelAdapter.test.ts`、`wealth/src/features/stock-detail/trend-channel/api/stockTrendChannelViewModelAdapter.test.ts`、`wealth/src/features/stock-detail/trend-channel/controller/useStockTrendChannel.test.tsx`。后端旧计算器、查询服务、旧API、读取器和能力判断的专用测试仍按§5.2删除；§5.3已改动的三个后端测试纳入同次阶段四交付，不丢失原有修改。

实际HTTP请求记录中已有的旧接口请求为零断言可以保留，它不要求导入或保留旧模块；不再通过旧模块替身验证新链路。固定历史行情JSON和 `tests/foundation/technical_indicators/test_trend_channel_calculation.py` 不属于上表待删样本：它们只在测试时校验算子数值、500根预热误差及分批处理，继续保留。股票、上证实际使用的通道点类型及画图实现也按§5.2保留。

#### 5.4.2 对应验收与执行边界

1. 删除对应模块后，按上表逐项复核导入、类型和字符串形式的模块替换；已删除模块在保留测试中不再有导入或替换，`makeTrendPayload/rawBar/failTrend/mockFetch.trend` 等旧专用构造无剩余引用。新四轨输入不改为旧独立接口回包。
2. 运行 `tests/architecture/test_lake_console_retirement_guardrails.py`，确认其余文件存在检查和原有禁止项仍通过；不删除、跳过整个测试函数来消除旧读取器移除造成的失败。
3. 回归上表保留的前端测试、股票和指数图表及共享通道画图测试，并完成前端类型检查和构建。后端沿§5.4、§6清单回归新算子误差、股票/上证日 K、普通/debug四轨、翻页、失败重试与资源释放；不能将已删除的旧测试计为通过。保留测试的预期继续来自新日 K合同、独立字面值或既有独立公式，不调用待测组装函数生成预期。
4. 本补充只明确同次代码删除所需的测试修改，不新增正式读取、写入、数据迁移或性能阈值。执行和最终验收沿§5.4既有预算及工程外临时目录规则；失败先按新日 K合同检查本次删除和测试修改，中断后继续核对未完成清单，不恢复旧模块、不屏蔽失败，不扩大到DG工程。

#### 5.4.3 删除后的路由与文档引用核验

除上述回归外，以工程外临时脚本装配真实路由，验证两个旧独立通道地址不再挂载、请求返回404，新股票/上证普通及debug日 K路由仍存在；`quote.py` 的其他路由及函数与删除前逐项比较。该检查不调用正式数据来源，不为验证删除而重新导入旧模块或新增兼容实现。新日 K四轨由既有隔离来源HTTP用例验收。

删除文件后，修正直接指向这些文件的文档链接。原上证专用计算方案/LLD、页面实施说明与门禁中的旧接口、旧测试命令标为对应历史阶段，现行入口指向本专项；涉及研究文档时只把旧代码链接改为删除前Git版本的固定链接，并注明旧趋势通道引用的适用范围，不修改研究结论。此次核对范围为本专项两份文档、`sse-daily-trend-channel-realtime-computation-*`、股票详情实施/门禁/本地日K方案与LLD、指数详情实施/门禁/日K接入方案与LLD，以及直接引用旧文件的三个 `docs/product/xxm-*` 文档；不修改DG方案、数据集合同或生产实现。历史内容保留，不能将当时的状态描述当作当前接口仍存在的证明。

临时验证、构建输出、缓存和日志统一位于 `/private/tmp` 下本任务目录，不安装依赖、不启动正式应用或后台任务。结束后删除无用临时产物，实际结果和逐项对照审计写回本方案及LLD。

## 6. 测试与分阶段验收

| 目标 | 正向测试 | 反向测试与正常例外 |
| --- | --- | --- |
| 四轨完整输出 | 首根最高 11、最低 9，两组轨道为 11/9；下一根最高 12、最低 10，按 2/26、2/91 独立手算 | 缺轨、非有限值、少根或错位失败；合法短历史可初始化。 |
| 固定预热 500 | 首目标前申报 500，输出根数另计；同算其他指标取最大需求 | 不读取 MACD 的价格上界或旧方向；到真实起点不足 500 不补造、不误报缺失。 |
| 预热误差 | **参考**从已确认完整历史起点连续计算；**被测**从目标前 500 根开始初始化；以同一行情、同一复权基准比较相同目标日期，每轨最大绝对误差不超过 0.01 | 保留 485 根的超限反例；不得把“参考与被测同一起点”用于预热误差验收，也不得用显示舍入或平均误差替代逐轨最大误差。 |
| 跨批正确性 | 这是另一类测试：整批与分批使用相同输入、相同初始化，逐轨比较 | 批次切换不重置 EMA，历史重叠行不重复计算；不能与上一行的不同起点误差测试混为一项。 |
| 同批共享 | 与现有指标同算使用同批行情、同一复权基准 | 不新增每指标取源或复权；不同参数的既有指标仍分别返回正确结果。 |
| 股票接入 | 本地日 K 首批/续页各最多 500 根，沿原游标；Prod 原回包及加载增加四轨；真实 JSON 和 OpenAPI 明确日线类型 | 周月线公共清单不含趋势通道、字段集合不变；页面不请求旧通道接口、不调用旧读取器；本批转换失败不推进游标，重试原批，保留原图和盘口。 |
| 第三阶段组装架构 | 每指标独立 build，公共组合供股票日/周/月调用，日线显式加通道；日/周/月 JSON、数值与错误行为与改前一致 | 不保留旧函数兼容别名，不复制公共映射、不创建笼统 special 函数、不按周期堆条件；不增加算法、来源或字段；上证不得依赖股票私有 DTO。 |
| 股票页面入口 | 已接入的股票日线 page-init 声明通道能力，新日 K 返回四轨，沿实际回包验证 | 不为测试导入或替换旧能力函数；正常空行情、短历史及基础行情失败沿现有合同；旧路由专用测试在对应旧接口删除时退出。 |
| 上证接入 | 沿当前装配与回包映射，首批/续页、开关、切日期、重试通过，四轨只用算子库结果 | 不再通过旧计算器/缓存导入和调用拦截验证；保留独立结果、日期和同批回包断言，不要求一次返回2,000根。 |
| 接口与数据边界 | 阶段4只删除已无业务调用的旧接口、专用代码和配置；基础行情和复权读取保持 | DG数据集、生产及文件全部排除，方向专项后续单独做；固定行情样本及共享绘图必须保留。 |
| 方向专项的范围 | 新算子仅输出四轨；废弃业务模块内部的专用类型随模块删除 | 不清理其他业务或DG数据集的方向字段；方向专项后续单独做，不列入本期验收。 |
| 本期不做 JSON | 既有请求、结果与算子接口保持原结构，新增算子仅四个数值字段 | 不增加 `info`、说明空串、`output_info()` 或 JSON 专项测试。 |
| MACD 不变与取消 | 原默认/自定义参数、历史需求、数值和版本回归；跨批失败/取消可清理并重试 | 不调整 100 万常量或既有精度；失败不返回部分结果，不把状态清理失败当成功。 |

阶段一已新增 `tests/foundation/technical_indicators/test_trend_channel_calculation.py`，覆盖注册、历史需求、输出、取消和来源隔离；未增加 JSON 说明测试。阶段二至少覆盖 `tests/web/test_wealth_stock_detail_api.py`、现有股票日 K 服务测试与股票页面/历史加载测试，页面用例不再以伪造旧 capability 启用来证明新接入；`tests/test_stock_daily_trend_channel_capability.py` 在旧接口保留时继续验证旧接口限制，不能为了新页面修改预期而提前开放旧路由。阶段三补现有指数日 K、`useIndexDetailController`、历史加载和页面测试，独立断言算子结果映射及新日 K 回包；按2026-11-26决定删除仅用于拦截旧模块调用的测试代码。部署前进行实际目标环境的有界只读与浏览器验收。受保护 D3 测试继续按原启动与预算执行，不直接全量运行。

正式测试先核对生产者、schema 和必要样本；expected 不调用待测算子或相同 helper 生成。真实验收复用有来源的证据，只补获准窗口，不全市场扫库。若真实目标场景误差超 0.01，保留样本回到方案，不自行改变已确认的 500、放宽误差或引入全历史回退。

## 7. 已有测算证据及其范围

### 7.1 固定样本与正确起点

[上证输入夹具](../../tests/fixtures/quote_trend_channel/000001_sh_daily_input.json)的 SHA-256 为 `ed585326d64fae260f14e7ec53b885037db31609726ed38cb20c1cbe772e42ad`，共 1,599 根，2020-01-02 至 2026-08-07，为当时正式指数日线服务表的固定快照。本轮没有重读生产库，也不把该样本起点称为上证全部历史起点。

已有测算先从样本首根用 70 位 Decimal 递推四轨，作为独立完整参考；再对目标位置 H 至 1598，分别取该目标前 H 根加目标一根，以双精度从截取窗口首根初始化。两种计算的起点不同，比较相同目标日期；每轨窗口数为 `1599−H`。

| H | 每轨窗口数 | 最大绝对误差（点） | 结果 |
| --- | --- | --- | --- |
| 485 | 1,114 | 0.010067342861678173 | 长期上轨有一个窗口超出 0.01 |
| 486 | 1,113 | 0.0098460825786383 | 四轨全部窗口不超过 0.01 |
| 500 | 1,099 | 0.007213467416398642 | 四轨全部窗口不超过 0.01 |

500 根时，短期上轨、短期下轨、长期上轨、长期下轨最大误差分别约为 `4.70×10⁻¹²`、`4.12×10⁻¹²`、`0.0072134674`、`0.0068476520` 点。纠正的是原测试说明中“参考与被测同一起点”的错误文字，实际测算并非如此，已有数值不受影响。上述证据不代替共享 SQL 新算子或真实页面集成验收。

### 7.2 最终决定与未采用的推导

500 根是管理员确认的固定预热；486 仅是这份样本的测算结果。829 根来自假定初始差值不超过 100 万的 90 周期 EMA 衰减推导，未采用，不进入预算。100 万是现有 MACD 的范围假设，不是实际误差，管理员决定保留，当前 MACD 算法和精度要求本期均不改。

默认 MACD 的最低 500 与误差公式是两层规则。按原默认参数、100 万范围与既有误差条件，去掉固定下限时 467 根已满足、466 根不满足；此记录只解释既有行为，不是调整 MACD 的建议。趋势通道的 500 不依赖该推导，0.01 也不扩展为 MACD 的新容差。

## 8. 开发前订正与后续阶段

开发前文档修订已明确：旧端点最多 2,000 根、已取消的 JSON 说明设计、旧通道目录或开关、旧数据集整体清退均不是阶段一算子开发的前置条件。股票页面入口脱离旧目录必须与阶段二取数切换一同完成；上证页面使用算子库结果、专用计算器退出该调用链必须与阶段三一同完成。

阶段一实现及验收见 §9；阶段二按 §4.2 接入股票日线，阶段三按 §4.3 先整理逐指标公共组装、再接入上证；阶段4仅按§5清理旧页面通道代码，DG及正式数据迁移均不在本需求内，方向专项后续单独做。每步开工前完成该步所需代码、消费者、合同、预算和测试准备，不把前一步通过当成后续全部完成。正式环境部署继续单独授权，本次不执行正式文件写入。

## 9. 阶段一实现、验收与独立对照审计（2026-11-25）

阶段一完成，尚未进入业务接入。开发前文档提交为 `29c1c1598`；以下按该提交中的硬口径，对完成后的源码和测试另作一轮逐条审计。`codegraph sync/status` 确认索引正常，`codegraph impact TrendChannelCalculation` 辅助核对影响；最终范围以当前源码与 Git 差异为准，不以索引中缺少调用方推断无人使用。

### 9.1 按 LLD 逐条对账

| 要求 | 实现与验收证据 | 结论 |
| --- | --- | --- |
| 完整四轨、无业务参数、版本 1.0.0 | `trend_channel.py` 的定义与六方法、两份新增 SQL；测试 `test_definition_discovery_and_fixed_history_do_not_use_macd_bounds`、独立两根行情金样本及参数拒绝用例 | 符合；无说明、位置、方向或组合字段。 |
| 最高价/最低价各自的 25/90 周期 EMA | 首根 SQL 按 high/low 初始化四轨；分段 SQL 使用共享平滑系数与四个 EMA 数值，未量化；金样本分别验证上轨与下轨，1,599 根真实来源固定快照与独立 70 位 Decimal 逐根对照 | 符合；不读取旧通道成品或收盘价判断方向。 |
| 固定预热 500、只返回目标、合法起点不足可用 | 算子独立常量及历史需求；公开服务用临时股票日线文件验证首批目标 500＋预热 500，共 1,000 根；下一批目标 500＋真实起点前可用 3 根，共 503 根；缺少应有预热文件的反例必须报错 | 符合；未动共享读取、MACD 预热或 100 万常量。 |
| 不同起点误差不超过 0.01 | 固定快照以首根生成独立参考，测试 SQL 分别从目标前 500 根开始；覆盖三个目标窗口和独立参考选出的最差长期上轨窗口；保留 485 根超限反例 | 符合当前快照；不扩展为任意价格、任意数据源的误差保证。 |
| 跨批、重叠输入不重复推进 | 固定快照按每批 17、257、2,048 根执行并加入两根重叠；每批严格核对序号、四轨与独立参考，释放批表后保留两个请求状态表 | 符合；2,048 为测试分批方式，不是新的业务返回上限。 |
| 多指标共用同一批行情与复权 | 公开服务同算 price、MA、BOLL、MACD、KDJ 和趋势通道；既有指标结果、源行、文件及复权批次与不含通道的基线一致 | 符合；没有为通道另取行情或另做复权。 |
| 输出异常、失败及取消不返回部分成功 | 新测试在第二批注入缺轨、非有限值、漏行与错位，整次报错并清理；分段后取消和异常均释放四张自有表，完整重试与独立参考一致 | 符合；非有限值沿既有最终结果检查，错位缺首序号沿既有 missing_rows 优先规则，不修改通用校验来迎合测试。 |
| 不改业务、协议、来源或健康上下文 | 本阶段实现只新增算子、两份 SQL、测试，及注册与 SQL 白名单两处小改动；对开发前提交核对 MACD/KDJ、history、engine、contracts 及股票/指数装配无差异 | 符合；无业务接口、页面、Settings、正式数据、发包或部署变更。 |

新增算子测试 **21 项通过**；加上既有合同、注册/依赖、阶段 C 输出、九转和选定执行器测试，合计 **128 项通过**，这两个数量包含重叠，不能相加。Ruff、文档完整性和差异检查通过。测试数据来自固定上证快照和工程外临时文件；已重核 DG 生产者的股票日线、股票复权因子、交易日历、证券生命周期与停复牌 schema，夹具按当前读取所需字段投影构造。这里验证的是隔离计算与当前读取合同，不声称正式环境或页面验收通过，未运行受保护 D3。

最终回归命令沿 §3.4 的源码路径和临时目录启动，明确选择：新增 `test_trend_channel_calculation.py`、`test_contracts.py`、`test_registry_dependencies.py`、`test_stage_c_output.py`、`test_nine_turn_calculation.py`，以及 §3.4 中四个执行器节点；未执行整个指标测试目录。

提交前发现并行九转任务也修改了同一注册文件，已将暂存内容限定为趋势通道的导入和注册两处，保留工作区的其他任务修改。另将暂存的算子包和测试导出到工程外临时目录，以该版本重跑同一组 128 项，全部通过；这是相同用例的复核，不累计为额外测试数量。

### 9.2 数值、用量及取消恢复实测

固定快照的最差 500 根长期上轨窗口，目标下标为 623（从 0 开始）；被测 SQL 以 501 根输入初始化并计算至目标，参考从快照首根连续递推。该目标四轨绝对误差依次约为 `2.70×10⁻¹²`、`2.34×10⁻¹²`、`0.007213467416`、`0.006847651987` 点，均不超过 0.01。与 §7 旧测算在双精度舍入范围内一致；该样本仍不是上证全部历史。

性能与恢复只使用同一份临时股票前复权输入：首屏取最后 500 根、固定预热 500 根，每批计算 64 根；未访问正式 Lake 或数据库。正常、重复及取消后重试三个完整请求均交付 1,000 根行情、返回 500 根，库统计 SQL 处理行均为 8,862、登记文件均为 2,000、登记文件字节合计均为 3,465,000，复权批次均为 16。文件数按各请求去重，字节合计不是磁盘块实际 I/O；SQL 处理行不是独立 K 线数量。

| 本地隔离请求 | calculate 调用至清理返回耗时 | SQL 步骤结束时采样的 DuckDB 已分配内存最大值 | 结果 |
| --- | --- | --- | --- |
| 正常请求 | 627.879 毫秒 | 64,223,792 字节 | 返回 500 根并释放资源 |
| 相同请求重复 | 514.950 毫秒 | 64,223,792 字节 | 完整重算，结果一致 |
| 首个通道分段完成后取消 | 280.256 毫秒 | 31,612,318 字节 | 已交付 64 根；取消至释放资源 7.091 毫秒，无部分成功 |
| 取消后完整重试 | 524.877 毫秒 | 64,223,792 字节 | 重新读取 1,000 根、返回 500 根并释放资源 |

取消请求当时已登记 1,065 个文件、文件字节合计 2,491,665；64 只指已交付给计算的行情根数，不能据此忽略定位和股票复权因子准备的成本。

内存为额外观测在 SQL 步骤之间调用 `duckdb_memory()` 的采样值，不是进程 RSS 或真实峰值；上述耗时包含观测开销，不能作为生产性能保证，也未用于抬高现有限制。这组恢复验收累计交付 `1,000×3＋64＝3,064` 根（含重读），另有 128 项隔离测试与固定快照 SQL 对照成本，不能把 3,064 当作全部验收读量。未增加持久状态或性能阈值，仍沿现有请求预算和错误处理。

独立对照审计未发现未处理的阶段一 LLD 偏离；业务接入、旧接口和正式数据集清理继续留在阶段二至四，不因本次完成而自动进入下一阶段。


<a id="stock-trend-channel-stage2-execution"></a>
## 10. 阶段二开发约束与开工核对（2026-11-25）

管理员已明确授权按 LLD 推进阶段二并在完成后审计。本步沿 §4.2、§4.5 的设计实施，开工核对时股票四轨尚未接入。CodeGraph 已再次核对清单四处调用及页面/历史/图层消费者，并直接读取 schema、结果检查和旧入口判断。来源与复权仍沿现有日 K，不写正式数据、不安装依赖、不部署；第三阶段公共拆分和上证接入、第四阶段旧模块/数据集清理不在本步实施。

| 必须满足的口径 | 实现位置 | 验证方式 |
| --- | --- | --- |
| 日线加通道，周月线保持原清单和字段 | stock_daily_kline_calculations、stock_period_kline_service、schema | 逐项请求清单字面预期；新增周月线服务请求/组装回归，原 JSON 字段不增通道。 |
| 四轨必有且完整序列化，不改公共四组组装 | 日线独立通道 build、日线 factor/bar/response、路由 | 字面四轨、坏字段/版本/日期/非有限反例；真实 model_dump、HTTP 与 OpenAPI。 |
| 本地首批/续页共用，Prod 沿原方式 | 日线 App、服务和原请求构造 | DG/Prod 分别隔离装配；本地九转和盘口、Prod 原 meta 及无新增分页。 |
| 入口不再查旧开关/目录 | 股票 query 的 _page_options | 旧目录不存在和旧开关关闭仍支持；旧 capability/reader 在页面请求中被调用即失败，旧路由限制保持。 |
| 首批和历史页存同批四轨，开关只绘制 | 页面、adapter、history、workspace | 首批/续页/先翻页后开通道，旧请求零次；图层数据与日期对应。 |
| 转换失败不推进游标，取消丢弃迟到回包 | loadStockDetail、loadPage | 缺轨/非有限/错日期反例后原批重试；切证券/日期/周期、已有图表和盘口保持。 |
| 不加方向/组合/JSON，不改算法和画法 | 新日线字段及共享图形消费者 | 输出字段集合、原几何/配色回归；共享算子与 MACD 源码本步不改。 |
| 性能和恢复沿原预算 | §4.2.5 及现有 runtime | 记录正常、取消清理、完整重试、最终验收费用；真实验证限单股票有界窗口，临时产物仅 /private/tmp。 |

使用现有 Python/Node 环境，测试显式使用仓库共享包源码，不安装或发布包。Context7 本轮查询 Pydantic 返回 fetch failed；嵌套类型按 §4.2.2 已核实的官方规则与本机有界实例继续验证。自动化测试不替代真实来源及浏览器验收；实现后在本节逐项记载证据，并另作对照审计，不能凭测试总数宣称全部完成。


### 10.1 本步真实只读与浏览器验证方式

核对过现行 `LakeSecurityReferenceReader.read_by_codes()` 的代码过滤和交易日历日期范围；真实核验限 `600519.SH`、截止 2026-11-19、首批与下一批各最多 500 根，沿正式 DG 根目录和现有读取器，不全市场或全历史扫描。使用 `/private/tmp` 隔离 FastAPI 实例装配真实股票路由、共享包源码和 DG 来源；拒绝业务 PostgreSQL 会话、旧通道读取及旧能力函数，避免启动完整应用的其他后台任务。鉴权在此隔离实例替代，不把它作为登录或发布验收；来源、计算、组装、编码与 HTTP 路径是真实实现。

浏览器使用临时 Vite 入口挂载原 `StockDetailPage`，只替代应用外壳与鉴权，不改页面、图表和交互源码；正式股票请求交隔离实例。非本任务后台模块不在临时服务启动；真实浏览器错误、取消和网络范围分别记录，不用页面 mock 代替股票来源。构建输出、日志、临时服务代码和审计数据全部在 `/private/tmp`。正常 API、浏览器、取消和同参重试分别记账，验证完停止本任务的临时服务，不重启或替换正在使用的服务，不执行部署。

旧 Web 测试夹具选择本地 DG 路由却只准备 SQLite 的 Prod 数据，且将已支持的 week 当非法输入；已按当前路由和来源合同改为本模块显式 Prod 路由的隔离应用，并以 quarter 作为非法周期。计算项数随新指令调整；数值预期来自独立字面样本，常量行情 EMA 的精度按已确认绝对误差 0.01 判断，不用逐位浮点相等。没有改变运行中路由、周月线支持范围或原错误口径来迁就测试。


### 10.2 实现与逐项对照审计

阶段二开发完成后，另行重新阅读 LLD §4.2、§4.5、当前代码及全部相关差异，并用独立字面预期、真实来源和浏览器结果对账。没有用编写过程的完成清单替代审计，也不声称有第二名审计人员。

| 硬口径 | 实现位置 | 测试与实际证据 | 审计结论 |
| --- | --- | --- | --- |
| 只给日线加四轨，原实例顺序保留 | `stock_daily_kline_calculations.py` 的公共/日线清单；日线两个 request、结果检查及 App 启动检查沿原调用 | 独立清单字面断言；真实 DG 请求 13 项，nineturn 在通道之前；Prod 隔离路径 12 项 | 符合。业务没有复制 EMA 或另行提供种子。 |
| 四轨必有且完整序列化 | 新 `StockTrendChannelFactorsDto/StockDailyKlineFactorDto/StockDailyKlineBarDto`、日线响应及 `build_stock_trend_channel_factors()` | 四个不同字面数值映射，真实 JSON、OpenAPI 必有字段；缺项、重复、错参数/版本、缺轨、NULL/非有限值均失败 | 符合。无方向、组合、说明或空串字段。 |
| 周月线计算与字段不变 | `StockPeriodKlineService.calculate()` 只调用公共清单；period 响应显式使用原 bar | 新 `test_stock_period_kline_service.py` 检查 week/month 的原 12 项、完整公共 factor、日期及游标；既有周期 DG/隔离 PG 回归通过 | 符合。公共 `build_kline_factors()` AST 与改前相同，未提前拆分或创建阶段三 mapper。 |
| 日线首批和续页同批四轨 | `StockDetailPage`、日线 adapter、`HistoryPage.trendPoints`、`StockChartWorkspace.initialTrendPoints` | 本地首批/续页、Prod 原回包；先加载历史再开通道；真实页面展示历史日四轨与回包一致 | 符合。开关只绘制，无独立通道请求。 |
| 错误不提前推进游标 | `loadPage()` 先转换全部结果，再提交页数组与 `nextEndDate` | HTTP 失败、缺九转、缺轨、非有限值和错日期后保留原图、原游标，重试原截止日；切证券/日期/周期丢弃迟到回包 | 符合。不提交部分页面或回退旧结果。 |
| 页面不依赖旧目录和开关 | `_page_options()` 已移除旧能力调用及 import | 旧函数被调用即失败的页面初始化用例、无旧通道目录的 DG 来源夹具、新能力声明；旧能力单测仍验证旧接口限制 | 符合。旧路由、Settings、读取器及正式文件未删除。 |
| 保留原环境行为与图形 | DG 保留首屏盘口、内联九转和原游标，Prod 保留原 page-init/日 K；几何与 primitive 源码未改 | 周月线、九转、图表位置及开关回归；浏览器原颜色与历史点正确 | 符合。未扩建 Prod 分页或修改共享画法。 |
| 不越界进入后续阶段 | 上证业务、MACD、通用结果协议和正式数据未改 | 对照差异及引用审计；库/source/schema 的既有数值合同继续有效 | 符合。阶段三组装整理及上证接入、阶段四整体清理留待各自阶段。 |

### 10.3 自动化与静态验证

- 股票后端定向验收 **59 项通过**：覆盖日线服务、新周月线服务、本地真实读取模块的隔离文件集成、Prod 路径隔离合同、HTTP/OpenAPI、错误清理和旧能力限制。SQLite 替代正式 PG 的用例仅证明装配及合同，不称作生产库验收。
- 前端五个相关测试文件 **52 项通过**，TypeScript 检查和完整构建通过，构建输出位于工程外临时目录。新增历史通道绘制用例按现有 `IChartApi.removeSeries` 补齐图表替身，实际调用路径仍执行，未删减断言；浏览器另外验证真实图表。
- 趋势通道算子 **21 项**及两项指定隔离 PG 周期回归，合计 **23 项通过**；既有 DG 周期边界用例也通过。数字包含既有回归，不是新增用例数，重复运行不重复计数。未运行受保护 D3 大组或正式生产测试。
- 生产改动、新增测试及其余修改测试 Ruff 通过；两个既有测试文件各保留原有 E731/F401 提示，经 HEAD 对照确认无新增，未顺手改无关代码。文档、修改链接及差异检查随收尾完成。
- 初轮旧并发夹具等待未完成，已中断该诊断运行，不引用其通过结论；本次所需的请求、启动检查、真实源错误释放和取消恢复均由后续有界用例验证。隔离 PG 最初在默认沙箱因回环监听权限失败，核实是临时新集群后按工具规则执行，不连接正式库、不安装依赖。

### 10.4 正式 DG 有界只读与浏览器结果

使用仓库共享包源码和隔离应用，只读取 `600519.SH`，页面日期 2026-11-19，不调用正式 PG、不启动其他后台任务。常用本地服务、静态包和 Prod 均未切换。

| 请求 | 实际返回 | 原游标 | 客户端完整 HTTP 耗时 |
| --- | --- | --- | --- |
| 首批，endDate=2026-11-19、limit=500 | 500 根，2024-10-30 至 2026-11-19，含四轨、原盘口及九转 | 2024-10-29 | 2,975.922 ms |
| 续页，endDate=2024-10-29、limit=500 | 500 根，2022-09-30 至 2024-10-29，含四轨及九转 | 2022-09-29 | 1,979.128 ms |
| 首批同参取消后重试 | 重新成功返回 500 根及同批四轨 | 与首批一致 | 1,407.649 ms |

上述每次成功计算的统计均为 `source_rows=1,000`、`price_conversion_batches=1`、`sql_processed_rows=53,585`、`source_files=2,001`。首批源文件大小合计 278,428,236 字节，续页 247,944,280 字节；这是计算模块记录的文件大小，不是实际磁盘 I/O 字节，也不是包括所有页面参考/辅助读取的全量文件统计。完整 HTTP 耗时包含原辅助查询、组装和编码，未将未单列统计的费用当作零。 本轮正式 DG 的成功完整计算共 6 次（含浏览器和重复请求），累计交付 6,000 根计算输入；两次取消以及两次未成功的临时观测还有额外源读取，不计在这个数内。6,000 不是独立 K 线数量或整个验收的磁盘读量，失败的临时观测不计作通过证据。

取消在第一批源读取完成后触发真实 `request_stop(cancel)`，原 HTTP 错误路径返回，未产生部分成功结果，资源释放后活动请求数为零。补充观测记录该批 500 个行情文件、500 行已读取源记录，取消到资源归还 **6.344 ms**，该次 HTTP 总计 **678.460 ms**；随后相同参数重试返回 500 根，总计 **2,520.539 ms**。这与跨批 SQL 取消的算子单测共同覆盖不同取消位置，不将已读取记录等同于已向算法交付的根数。临时观测脚本的两次失败尝试不计为有效验收，费用不隐去：真实 DG 全过程另有重复读取，不能把表内两次正常请求当作全部验收开销。

浏览器直接挂载原页面组件，使用上述真实 DG API。观察到首批四轨 1410.86 / 1381.88 / 1348.13 / 1322.23；实际拖动只请求一次原 `/kline` 续页，endDate=2024-10-29、limit=500。继续拖动至历史日 2024-10-16，屏幕显示 1420.53 / 1364.05 / 1397.98 / 1359.69，与该响应四个原始数值按原显示精度一致。开关不新增请求，旧通道请求为零，旧读取器调用为零，未观察到控制台 error/warn。记录范围为股票目标组件和 API，鉴权及其他未启动的模块不在此次验收范围，不能冒充完整应用或生产发布验收。

本轮重新执行了固定快照的独立精度验收，预热仍为 500、每轨绝对误差仍为 0.01；真实股票只读核对证明接入、日期和图层对应，不宣称已对股票全部历史重新做精度比较。实测费用低于现有请求预算，未据此提高任何预算或保证任意股票/环境均有相同耗时。

### 10.5 交付结论

阶段二代码、隔离技术验收、单独的 LLD 对照审计和正式 DG 有界/浏览器核验完成，未发现阻止本阶段交付的 LLD 偏离。提交管理员 review，不自动进入阶段三。未安装/发布共享包、未部署常用本地或生产服务、未清理正式文件；Prod 实际发布及目标环境复验仍按原授权单独执行。


<a id="trend-channel-read-scope"></a>
## 11. 本需求内的读取核查（2026-11-25 范围纠正）

### 11.1 范围与结论

管理员明确只检查本次趋势通道需求。上一轮将既有 DG 交易日历、Prod 通用行情/复权、指数周月线及分钟读取优化列为整改清单和阶段三前置，是扩大范围，现撤回；相关通用读取优化文档中的本轮扩展已移除，其他并行修改保留。本需求不承担外部代码的读取优化，也不因这些既有行为增加开工任务。

本节只核对新增趋势通道算子、阶段二股票接入、阶段三组装及上证接入会新增或改变的读取。已实现代码中，未发现为趋势通道增加单独行情查询、重复复权、旧通道文件读取或额外文件写入。上证接入仍是设计，完成后必须按下表验收，不能提前称为已通过。

### 11.2 本需求的具体读取与必要性

| 对象 | 当前实现或已确认设计 | 判断及验收 |
| --- | --- | --- |
| 趋势通道算子 | [TrendChannelCalculation](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/trend_channel.py)接收引擎提供的同一价格批次，用其中最高价、最低价计算四轨；自身不查询正式数据库或读取 DG 文件。 | 无独立源读取。读取请求内的价格、参数及 EMA 状态表是四轨计算步骤；工作表均在私有内存库中，不额外保存通道文件或写回正式表。 |
| 阶段二股票后端 | [计算清单](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_calculations.py)在原同次请求追加通道实例；[assemble 与通道 build](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py#L162)按本根下标读取已经返回的结果，其他指标共用行情和复权结果。 | 新增的是四轨计算和字段映射，没有再调用读取模块。当前各 build 不查表、不读文件、不计算 EMA；第三阶段拆分公共映射后仍保持此边界。 |
| 阶段二股票页面 | 首批和续页直接从本批日 K 的 `factors.trendChannel` 保存通道点；页面、历史控制和图层已停止旧独立通道请求。 | 不再为同批图表补发 `/trend-channel`，开关只绘制。现有页面测试验证旧端点不可用也不影响新通道，相关请求次数为零。 |
| 阶段三上证接入 | 在原同次算子请求中增加趋势通道，四轨随日 K 返回；结果转换和逐指标 build 不另取行情。切换后移除该页面的旧通道首批、续页请求及专用重试。 | 不能在新增算子通道后继续旧接口取数，同一次 debug 请求也不能先计算普通回包、再为调试回包重算一次；阶段三须验证同次计算、同批结果和旧通道零调用。新日 K 接通前，不能先停掉仍供现有页面展示的旧通道。 |
| 固定 500 根预热和独立翻页 | 每个请求按自己的截止日期读取预热及目标，前后请求的数据可能重叠；同一请求的各指标取最大历史需求，共用输入，不逐指标相加。 | 这是已确认的初始化误差和独立请求要求，具有计算用途；不能删除下一页预热。重试继续原失败重试流程，不增加成功后的重复请求或跨请求持久 EMA。 |

阶段二已有实现与验收见 §10；上一轮补跑的 `test_stock_daily_reads_each_quote_partition_once_and_uses_only_actual_dates` 已验证本地股票行情查询路径及实际目标日期，页面测试已验证不请求旧通道。上述证据限定本次新增链路，不外推为旧通用来源完全没有重复读取。阶段三继续沿 §4.3 的测试矩阵，额外检查本次修改前后源读取调用没有因通道或 build 拆分而增加、同批不再次复权、组装及开关不取数。若本次代码确需重复读取，必须逐项写明用途和不能复用的原因；不能说明的不得加入。

本次只纠正文档范围，保留前一轮测试选择和阶段二状态的正确修订；阶段三仍按“股票逐指标组装整理并审计 → 上证接入”推进，未编码、提交或部署。


## 12. 阶段三执行约束与验收记录（2026-11-25，开发中）

本轮执行 §4.3 的两个步骤，先股票组装整理并单独对照审计，再上证接入。代码与测试使用工作区算子源码；临时基线、输入和测试产物位于工程外独立目录。沿原预算，不改正式数据、通用来源读取、其他指数能力、周月线算法、分钟线或阶段四旧路由清理，不安装、发包或部署。

| 本轮硬口径 | 实现位置 | 验证与交付要求 |
| --- | --- | --- |
| 每指标独立 build，公共指标单处复用，业务显式组合 | 股票公共 mapper、股票日线和周月线 assemble；指数公共 mapper | 独立字面映射预期、日/周/月改前改后 JSON 基线、空值/错误回归；旧映射函数及导入清零，不留兼容别名。 |
| 只给上证日线增加四轨，保持原环境/分页/九转 | 日线计算清单、App、query、日线及 debug schema、路由/OpenAPI | DG/Prod 分别验证；非目标指数和周月线不请求/不输出通道；重复、缺项、错版本/参数、缺轨/非有限值拒绝，空页合法。 |
| 本次新增链路不重复取数或计算 | 同次算子请求、结果索引、build、前端 controller/history/chart/sidebar | 组装仅用本批结果；普通/debug 不重复算；股票及上证页面旧通道零请求；每页四轨与行情同批转换后才提交游标，失败重试原批。 |
| 保持图层与历史交互，摘要固定首批末根 | 上证 controller/history/PageView/chart/InfoRail/TechnicalTab | 首批、续页、缓存暂存与显示、先翻页后打开、反复开关、切日期/指数/周期、取消及迟到结果、摘要不被历史页改写。 |
| 完成技术验收后再报告符合预期 | 本节回写逐项证据，原页面方案及 LLD 同步状态 | 必要后端/前端测试、类型检查/构建、单指数有界真实接口及浏览器；记录正常、取消清理、完整重试、源行/文件和最终验收开销，明确替身与未覆盖边界。 |

开工前已用 CodeGraph `codegraph_explore/codegraph_impact` 核对原公共映射的两个业务调用方及服务测试；当前日线和周月线仍从日线服务取得公共映射，和 §4.3.1 的迁移前提一致。先保存当前 JSON 基线和有界测试结果，再迁移；本步不改计算清单、来源、API 类型或前端。


### 12.1 股票组装整理的分步审计

已保存改前日/周/月完整 JSON，并用独立字面值区分 MA 周期、MACD hist 和通道各轨。改后 JSON 逐字段一致；新增逐指标映射测试及既有日线、周月线、真实临时 Parquet 接入测试共 48 项通过。CodeGraph 与当前引用搜索核对日线、周月线两个调用方：公共映射已迁入股票公共模块，旧 `_calculation_key/build_kline_factors` 定义及导入清零，数值元组复用，日线单独组合通道，周月线保持原指标。该步骤只改变内存映射，未改计算清单、行情来源、复权、SQL 或 HTTP 行为。此项单独对照审计通过后进入上证接入。阶段三总验收见下。


<a id="trend-stage3-results"></a>
### 12.2 上证实现与独立对照审计

完成编码后，另行重读 §4.3、§11、本节硬口径、全部本次代码差异及验证结果，逐项核对；这里指与编码分开的自审，不声称有第二位审计人员。CodeGraph 使用了 `codegraph_explore/codegraph_impact`，收尾 `codegraph sync/status` 确认索引为当前版本；并直接核对了股票日/周/月、指数日/周/月、普通/debug/API 类型、前端页面及测试。图中未识别出的测试关系以实际 import 和执行结果补齐。没有调整子系统依赖方向，也未修改 Foundation 来源或算子算法。

| 原要求 | 当前实现及验证 | 结论 |
| --- | --- | --- |
| 公共能力单处维护，每指标独立 build | `stock_kline_factor_mapper.py` 的 MA/BOLL/MACD/KDJ/趋势通道 builder，日/周/月各自组合；指数自己的 mapper 同样逐指标 build，公共组合不要求通道。股票改前/改后完整 JSON 一致，元组引用复用，旧公共函数及导入清零。 | 符合，无兼容别名或周期判断大函数。 |
| 只给目标上证日线追加四轨 | `index_daily_calculations()` 保留原实例与相对顺序，仅 `000001.SH` 追加通道；App 同一次调用使用该清单；query 分开校验、映射公共结果与四轨。非目标指数、周月线和 Prod 大于 500 根原分支回归。 | 符合，无额外行情请求或业务内 EMA。 |
| 普通/debug 四轨不被父类型丢弃 | 明确的上证 factor、bar、Prod/本地 response 及两种 debug response；debug 投影先识别上证类型，普通/debug 路由和 OpenAPI 声明完整。HTTP 对照四轨、日期、游标、状态和本地九转一致，每个 HTTP 请求只算一次。 | 符合，四轨必有且有限；其他响应不加空通道。 |
| 结果完整、合法历史不足可用 | 重复/缺项、错参数/版本、缺轨/重复轨、错长度、NULL/NaN/Inf 反例失败；正常短历史的 MA/BOLL 空值、本地空九转与空页成功。固定样本 SQL 预热误差继续使用 §9 的独立参考及 SHA。 | 符合，500 根和 0.01 均未改。 |
| 首批/续页全部转换后再保存游标 | adapter 从同根日期、收盘和四轨生成点；controller 保存首批，history 保存续页；转换失败不提交页或游标。缺轨、NaN、错日期、HTTP 失败后重试原截止日；取消、切指数/日期/周期丢弃旧结果。 | 符合，不用旧通道补齐。 |
| 绘制与摘要符合原语义 | 初始点加可见历史点交原几何和 primitive；开关只切绘制，缓存暂存及缩放/位置机制保持。InfoRail/TechnicalTab 只取首批末根摘要；九转的本地内联与 Prod 独立重试保留。 | 符合，浏览器也验证历史图变化而摘要不变。 |
| 退出旧页面链路，清理不越界 | controller/history 不再 import/调用旧通道 API/adapter；旧专用加载、状态提交和重试 props 已移除。测试将旧计算器与缓存调用设为立即失败，页面网络旧通道请求零次。 | 符合；旧路由、模块、专用旧测试与正式文件留阶段四。 |
| 本需求不新增重复读取/写入 | 股票仅调整内存映射；上证共享同次算子输入和原环境读法；新增通道、builder、图层不读取行情表或通道文件，无新写入。DG 实际每个完整请求共交付 1,000 根行情，四轨没有再加一批。 | 符合 §11 范围，不改既有通用 DG/Prod 读取。 |

本阶段没有未处理的 LLD 偏离或新增待拍板业务项。阶段四消费者清理、正式数据迁移、共享包发布和部署没有在本轮执行。

### 12.3 自动化与既有失败的界限

- 后端定向 **128 项通过**：股票整理的 48 项；指数映射、DG 接入、普通/debug/OpenAPI、字段映射与趋势通道独立参考共 71 项；`tests/app/technical_indicators/test_index_daily_prod_trend_channel.py` 的 Prod 日线临时 PostgreSQL 接入 1 项；DG/Prod 周月线临时 PostgreSQL 回归 8 项。重复运行不累计为新增用例。Prod 用例通过真实 PostgreSQL 及当前模型构造行情，并以独立常量高低价验收 EMA，同时验证大于 500 根原分支仍用原结果；不连接正式 Prod。
- 前端 **8 文件、104 项通过**，覆盖 adapter、controller、历史缓存、图表、页面、右栏、周月线和 debug 消费者。移除旧通道专用 UI 后的三个受影响文件另复核 32 项通过，包含在原 104 项内。TypeScript 检查与完整构建通过；tsc 元数据、Vite 缓存及构建产物放在工程外。构建保留原有大文件提示，不扩大本次功能做拆包。
- 本次新增 Python 代码和测试 Ruff 通过；指数 query 中保留的 `IndexDailyLakeSourceError` 未使用 import 在 HEAD 中已存在，未顺手清理。引用及差异检查、文档检查另随收尾执行。
- `tests/web/test_wealth_index_detail_api.py` 的通用总应用夹具仍用 dev/DG 路由，但只准备 SQLite 的 Prod 表，并且刻意不装配指标 runtime：**20 项失败、14 项通过**。以 HEAD `569377c4e` 的本次相关模块源码替换后，在相同配置和夹具重跑，20 个失败用例完全相同。未修改生产逻辑来迎合夹具，也不把这些失败说成通过。上述 1 项新的 Prod 真实隔离接入、DG 真实文件/HTTP 用例及普通/debug 字段对照，独立承担本阶段新增边界的验收。
- 没有执行受保护 D3 大组、无关正式 PG 测试、全市场/全历史源读取，也没有安装依赖。Context7 检索本轮返回 fetch failed；类型和工具行为使用当前安装版本、实际序列化、类型检查及构建核验。

### 12.4 正式 DG 的有界只读、取消及费用

工作区基于 HEAD `569377c4e` 的本次未提交改动，使用共享包源码启动工程外隔离实例，只访问正式根 `/Volumes/datasource/data_lake` 的 `000001.SH`；截止 2026-08-07，首批和下一批各最多 500 根。真实行情、日历、算子、组装、普通/debug 路由和编码保持原实现。鉴权替代；页面初始化的指数日线基本指标与指数成分权重查询接空的临时 SQLite，未连接正式 PG，合法显示部分基本面缺失。本核验不声称登录、完整基本面或生产部署通过。

| 正常 HTTP 验收 | 返回范围及数量 | 原游标 | 完整 HTTP 耗时 |
| --- | --- | --- | --- |
| 首批 endDate=2026-08-07、limit=500 | 2024-07-17 至 2026-08-07，500 根 | 2024-07-16 | 2,071.086 ms |
| 续页 endDate=2024-07-16、limit=500 | 2022-06-27 至 2024-07-16，500 根 | 2022-06-24 | 665.367 ms |
| 同参取消后完整重试 | 首批 500 根、四轨/日期/游标/状态完全一致 | 2024-07-16 | 448.119 ms |

两个完整窗口每请求交付 1,000 根源行情，返回 500 根，SQL 累计处理 53,585 行，登记 1,001 个源文件，复权批次为 0。首批登记文件字节合计 54,723,143，续页 57,659,254；这是文件登记和逻辑行统计，不是磁盘块实际 I/O 或独立 K 线总数。算子共同消费这 1,000 根，不按指标个数叠加行情数量。组装编码等其余阶段以完整 HTTP 耗时包含，不另虚构未采样的分项数值。

取消使用本任务临时观测器：首个通道 SQL 分段结束后调用现有 `request_stop("cancel")`，没有改正式逻辑、延时或预算。补记取消源计数时，取消 HTTP 670.372 ms，取消至计算资源清理 10.988 ms；已交付 1,000 根、登记 1,001 文件/54,723,143 字节，没有部分成功。随后同参重试 HTTP 397.724 ms，重新读取 1,000 根并返回一致首批。请求结束查询活动租约为 0。这项证明运行时取消与释放，不冒称真实网络断线测试。

此精确记账组合为首批、续页、补记取消、完整重试四次，交付 `1,000×4=4,000` 根（包含重读），不能说只读了 1,000 根。中间步骤最大 DuckDB 已分配内存采样为 57,938,004 字节；这不是进程 RSS 或真实峰值。仍使用 SQL 128 MiB、请求 256 MiB、总目标 8,000 ms、清理保留 2,000 ms 原配置，未抬高阈值。

全部真实来源诊断、浏览器和复核累计 15 次计算调用：11 次成功、3 次受控取消、1 次临时记录器错误；调用到资源释放累计 9,144.410 ms（包含采样，不含 HTTP 的全部阶段）。成功请求及补记取消共记录 12,000 根源行情；最早两次取消与记录器错误未采集源计数，不把 12,000 称为完整累计或独立行情数量。记录器曾误将带来源的返回对象当作普通结果，纠正后重试；这次没有业务代码错误。隔离自动化测试及固定参考另有费用，不包含在这组正式 DG 统计中。

### 12.5 浏览器与收尾边界

CUA 连接超时后，使用本机已有 Playwright/Chromium 运行工程外入口，挂载原 `IndexDetailPage`、真实共享图表和上述 HTTP 实例，没有安装套件或改页面源码。首屏四轨显示 3918.69、3861.58、4008.26、3953.52，与同批末根四轨按两位小数展示一致；原几何、红绿/蓝紫通道及九转绘制保持。

原页面首批成功后反复关闭/打开通道，日 K 请求数量保持 1。拖入历史范围时，临时实例注入一次续页 HTTP 500，页面保持原图，下一次拖动重试完全相同的 endDate=2024-07-16，成功返回 500 根；历史图随实际日期变化，右栏四轨摘要仍为首批末根。全程日 K 请求依次为首批 200、续页 500、同参续页 200，旧通道 API 请求零次，页面 JavaScript 异常零次。未挂载的顶部行情/量化结构/预测接口产生的 404 与故意注入的 500 单独保留，不把它们当作趋势通道异常或完整页面所有功能验收。

临时浏览器及本任务 HTTP/Vite 实例已关闭；无用临时测试资源在收尾删除，必要结论和数字保留在本节。没有提交、推送、共享包发布、部署、正式数据写入或阶段四清理；并行工作区修改保持原样。


## 13. 2026-11-26 范围纠正与检查删除记录

管理员明确确认：本需求不处理 DG 数据生成或数据集；方向专项后续单独清理。此前把 DG 停产、字段迁移和正式文件处理写入阶段4，是范围越界，本轮已从现行方案和本LLD §5撤回，不再作为开工前提。§9—12的历史执行、测算及当时测试记录保留，不将其中旧范围描述作为当前实施要求。

本轮只修改原方案、LLD以及§5.3列明的三个测试文件，去掉旧上证计算器/缓存、旧股票成品读取器和旧能力函数的导入或替换检查；两个测试按仍实际验证的新行为改名。保留新算子四轨、缺轨和非有限值失败、同参重试、资源释放、游标、普通/debug及页面能力断言，没有修改业务实现、旧接口或任何 DG 文件。

三个文件定向回归 **48项通过，6.78秒**。输入均为既有隔离临时夹具；不访问正式 DG/Prod，不运行数据生产。固定历史行情样本 SHA-256 仍为 `ed585326d64fae260f14e7ec53b885037db31609726ed38cb20c1cbe772e42ad`；该样本和共享绘图目录相对提交版本均无改动。CodeGraph已用于定位测试函数，相关导入、测试主体与引用以当前代码直接核实；本轮不改变运行时边界或依赖矩阵。

旧接口和专用模块的整批删除尚未执行，继续按纠正后的§5推进。没有改动或审计DG生产链及数据集，没有方向专项清理、发包或部署；测试产物只在工程外临时目录，收尾删除。

随后按管理员要求仅提交原方案和本LLD，三个测试文件的修改留在工作区，不混入文档提交。提交前以CodeGraph `codegraph_callers` 和当前代码确认通道画图函数的两个产品调用方，并在§5.2分开说明测试输入与产品画图代码；§6同步撤销残留的方向专项清理验收项。

<a id="trend-stage4-results"></a>

## 14. 阶段四实施、验收与独立对照自审（2026-11-26）

### 14.1 执行范围与实际修改

按§5及§5.4.1—5.4.3实施。删除前以CodeGraph `codegraph_explore/codegraph_impact/codegraph_callers`及当前import、路由和前端消费者核实引用；同名方法的无关命中不作为依赖依据。执行基线为 `75006c992c05239b79aeec6e93a126691b55c141` 加开工时已有的本需求文档、三个测试修改；其他并行工作区修改保留。

| LLD硬口径 | 实际代码与保留边界 | 验收证据 |
| --- | --- | --- |
| 删除上证旧独立接口及专用实现 | `src/biz/api/quote.py`只删除旧通道路由及导入；旧calculator、query service、query、schema及专用测试删除，缓存随旧query service删除。 | 真实聚合路由装配后旧地址HTTP 404；`quote.py`其余四个函数的完整AST与删除前一致，原四个路由仍在。 |
| 删除股票旧独立接口、读取器和配置 | 删除旧API/query/schema、Web成品reader/contract、capability、专用Settings字段、路由挂载及专用测试；旧query包的空 `__init__.py`一并删除，无空兼容模块。 | 全部旧模块在运行源码和保留测试中的import/替换引用清零；旧地址HTTP 404；仓库文件检查只去掉旧读取器这一项，其余架构检查通过。 |
| 删除旧前端请求与专用类型 | 删除指数旧API client/adapter、股票旧API/types/adapter/hook及其专用测试；只删除指数model中无人使用的 `TrendChannelViewModel`，在用的 `TrendChannelPoint`保留。 | 前端类型检查通过；旧client、hook、回包构造及替换无剩余运行或测试引用；未添加兼容入口。 |
| 混合测试同步清理 | §5.4.1所有列明文件已逐项处理，删除旧调用替身、旧回包分支、`makeTrendPayload/rawBar/failTrend/mockFetch.trend`；保留新日K、四轨、日期、游标、开关、摘要、失败重试与其他模块断言。 | 前端14个文件154项通过；删除的旧专用测试不计作通过。§5.3三个后端测试的先前修改也保留并通过回归。 |
| 新链路及其他周期保持 | 没有改动新股票/上证的日K计算、取源、组装、控制器或图表实现；其他指数、股票周月线及原MA/BOLL/MACD/KDJ保持。 | 本地临时Parquet来源HTTP、Prod隔离PostgreSQL普通/debug及周月线接入、服务/映射/失败清理测试通过；171项后端及架构节点去重见§14.2。 |
| 保留测试输入、数值验证与产品画图 | 共享包Python/SQL、日线调用装配、通道画图与测试输入等71个文件的SHA-256与开工前一致。原始行情输入、新算子独立Decimal参考测试均保留。 | 固定500根预热、四轨0.01绝对误差、分批和取消用例通过；画图的几何及绘制类测试通过。没有新增JSON、方向或组合状态。 |
| 不新增重复读写、不改正式数据 | 没有新增源查询、文件读写、复权步骤或计算入口；本次正式查询和正式写入均为0。 | 既有同批读取和逐分区读取断言通过；验证只使用固定样本、临时Parquet、内存SQLite及新建隔离PostgreSQL。没有读取正式DG/Prod、操作DG任务、迁移数据或部署。 |

两份固定JSON均无修改。`000001_sh_daily_input.json`仍由新算子测试读取，其SHA-256为 `ed585326d64fae260f14e7ec53b885037db31609726ed38cb20c1cbe772e42ad`。旧 `000001_sh_daily_expected_v1.json`还被已有研究记录作为历史数值证据引用，因此保留；新算子不读取它，也不把其中旧方向标签作为当前输出合同。

文档处理按§5.4.3执行：原上证说明和股票/指数页面实施、门禁、日K说明注明旧通道部分的历史适用范围；三个研究文档只补历史引用说明并将旧源码链接固定到删除前Git版本，不改原有研究结论。原方案和本LLD同步当前完成状态；DG文档及工程未改动。

### 14.2 测试、真实装配核验与执行费用

后端全部使用现有 `.venv`，显式设置 `PYTHONDONTWRITEBYTECODE=1`、共享包源码 `PYTHONPATH`、工程外 `GOLDENSHARE_ENV_FILE`和pytest临时目录，并禁用pytest工程缓存，不自动读取仓库根 `.env`。

- 首组为新算子、股票和上证日K、指数映射及四组架构检查，共118项。117项通过，一项架构扫描因本轮删除空包文件与扫描同时发生而报文件不存在，耗时29.86秒。这是本次执行顺序错误，不是业务通过证据。文件清理结束后重跑该检查。
- 第二组为股票日线/周月线服务、逐指标映射、股票隔离接入、HTTP合同、指数临时DG来源及上述架构检查重跑，共53项通过，12.22秒，其中9项与首组重复。
- 第三组为上证Prod普通/debug日K及指数周月线local/Prod接入，共9项通过，12.90秒。使用工程外新建PostgreSQL集群，未连接配置中的正式数据库；结束后集群均已关闭。
- 按实际测试节点去重为 `(118−9)+53+9=171` 项，均已有通过结果；另作收集核对为171项。首轮失败及重复运行成本保留，不将执行次数当成独立测试数。
- 前端14个保留文件154项全部通过，5.55秒，覆盖§5.4.1混合测试、两页图表、回包映射、摘要与通道绘制；154项不叠加此前单独运行的2项几何启动核验。

前端使用现有Vitest 3.2.4、Vite 7.3.3和React插件5.2.0。Context7本次查询返回fetch failed；随后核对本机已安装工具的配置定义与实现。bundle和runner装载器在解析现有插件的可选 `vite/internal` 导入时启动失败，尚未运行测试；改用工具已支持的native装载器后通过，没有修改或安装项目依赖、修改插件、跳过失败用例。临时配置沿原根目录、React插件及setup，仅将缓存放工程外；前端原 `npm --prefix wealth run typecheck`通过，构建用继承原tsconfig的工程外配置完成 `tsc -b`，再沿原插件和 `/wealth/` base完成生产构建，输出在工程外，Vite构建1.42秒。

工程外tsconfig首轮因无法从临时目录解析 `vitest/globals`而失败；临时目录引用项目已有node_modules后通过，没有安装依赖或修改项目tsconfig。构建保留工具的原有大包告警和工程外输出提示，没有为通过检查调整阈值。

工程外ASGI脚本装配真实 `src.app.api.v1.router`，两个旧独立地址均返回404，股票日K、指数普通/debug日K及原quote其他路由仍存在；新日K的四轨数值、序列化与HTTP响应由前述隔离来源用例验收。该路由核验没有请求正式数据，也不代表鉴权、正式部署或生产完整页面验收。

### 14.3 与编码分开的LLD对照自审

编码与回归完成后，重新对照§5、§6、源码差异和本节执行结果，逐项核查删除对象、混合测试、保留算法/画图/输入、源读取边界、路由和文档引用。这里是另一次对照自审，不声称有第二位审计人员。旧通道模块引用已清零，未发现本阶段未处理偏离；`codegraph sync/status`确认索引已同步。没有新增跨子系统依赖或修改依赖矩阵。

本次技术验收限定隔离来源、临时数据库和真实路由装配；未重读正式DG/Prod，未运行DG生产/检查任务、发包或部署。既有三个测试修改与两份指数文档的原有内容已核对保留；检查期间另有 `docs/README.md` 和指数成交量归一化方案发生并行变化，本任务未修改或覆盖它们。测试资源统一在工程外，临时数据库已关闭，无用产物已清除。阶段四源码和文档随本次提交交付，供管理员review；两份指数文档仅提交阶段四说明，其他需求的修改留在工作区，未推送、发包或部署。

### 14.4 后续九转绘图回查与验收范围更正（2026-11-26）

管理员反馈指数日线九转消失后，核实真实接口仍返回453个九转标记、末根为下跌第9根。实际图表复现确认：近期指数右侧留白改动使可见范围超出末根，九转绘制类精确读取右端返回空后整层提前结束。阶段四没有修改该绘制类；但此前对“九转绘制保持”的验收没有覆盖这个真实边界，是漏测，不能用原单测通过或数据存在来宣称该场景绘制正常。171项后端和154项前端通过仍是对应测试事实，其覆盖范围不包含该场景。

本次修复设计先补入[图表原方案 §6.2](../../wealth/docs/system/detail-chart-zoom-implementation-design-v1.md#62-指数详情页最新-k-线右侧留白2026-11-26)和[原LLD §10.6.1](../../wealth/docs/system/detail-chart-zoom-low-level-design-v1.md#1061-九转显示缺陷修正2026-11-26编码前设计)，只修正共享九转绘制对可视空白的处理，保留既定留白与算子数值，不恢复旧趋势通道实现或改DG数据。修复已完成：同一真实回包和相同留白范围下，实际Chromium画布由0个九转数字恢复为109个；199项相关测试、类型检查和构建通过。修复前4个失败反例、覆盖范围及执行结果保留原图表LLD。修复、测试和文档随本次提交交付，未推送或部署。
