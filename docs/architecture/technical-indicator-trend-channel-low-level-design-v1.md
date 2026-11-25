# 趋势通道算子及股票、上证接入 LLD v1

2026-11-25｜[专项方案](technical-indicator-trend-channel-plan-v1.md)记录最终需求。阶段一算子已实现，隔离验收和独立对照审计已完成，证据见 §9；提交管理员阶段 review。阶段二至四的业务接入和清理尚未实施，未发包或部署。JSON 已取消、预热与接口处理等已确认口径保持不变。

固定前置 500 根、每轨绝对误差不超过 0.01、四轨输出、旧方向清理和 MACD 保持现状均已确认，不需要重新拍板。每个后续阶段仍须先补齐该步代码、合同和验收细节并单独 review。

## 1. 当前代码与本期改动边界

| 对象 | 当前代码依据 | 本期处理 |
| --- | --- | --- |
| 算子请求与结果 | `packages/technical_indicators/src/goldenshare_technical_indicators/contracts.py` | 沿用 `CalculationRequest/CalculationValues`、数值 `fields` 和公共 `times`；不新增说明字段或说明空串。 |
| 算子接口与引擎 | 同包 `calculation/calculation.py`、`registry.py`、`engine.py`、`history.py` | 沿现有接口新增计算实现与注册，不增加 `output_info()`，不批量改造既有算子。 |
| 输出检查与编码 | 同包 `output/collector.py`、`result.py`、`encoding.py` | 四轨沿既有 DOUBLE 校验、日期对齐和编码，不为本期增加 VARCHAR 指标列或 JSON 处理。 |
| 股票调用 | `src/biz/services/wealth/market/stock_detail/stock_daily_kline_calculations.py`、`stock_daily_kline_service.py`，`src/app/dependencies/stock_daily_technical_indicators.py` | 按现有 MACD/KDJ 接法：计算指令加项 → 共享计算 → 按同批日期组装日 K 指标。 |
| 上证调用 | `src/app/dependencies/index_daily_technical_indicators.py`、`src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py` | 按现有日线装配、算子请求、数值映射和 `nextEndDate` 接入。 |
| 页面首批与续页 | 股票 `useStockDailyHistory.ts`、指数 `useIndexDailyHistory.ts`、对应页面 controller | 沿 `DAILY_CHART_PAGE_SIZE` 与 `nextEndDate` 加载，趋势四轨随同一批行情进入图层。 |
| 股票页面入口与旧路由挂载 | `src/foundation/config/stock_daily_trend_channel_capability.py`、股票查询的 `_page_options()`、`src/app/api/v1/router.py`；`tests/test_stock_daily_trend_channel_capability.py` | 当前同一旧检查同时用于页面入口、旧路由挂载和旧接口请求；阶段二只移除新页面对它的依赖，阶段四再按引用清理旧检查、旧配置和路由。 |
| 旧独立通道 | 上证 `quote_trend_channel_calculator.py`、`quote_trend_channel_query_service.py`；股票通道 query service 与 Lake reader | 属于后续清理、消费者迁移对象；不把完整旧 HTTP 响应直接换成共享库响应。 |

CodeGraph 已用于定位算子结果、请求解析与旧业务调用影响；已用 `codegraph_explore(run_index_daily_kline)` 核对上证装配，本次再用 `codegraph_explore(resolve_stock_daily_trend_channel_capability)` 定位股票页面、旧路由和旧接口的调用关系，并直接核对股票、指数的计算指令、读取器、前端批次加载和相关测试。同名 `run/calculate/resolve` 的无关命中不作为真实依赖。完整清理仍须在对应阶段按引用逐项核对，当前未证明旧数据集已无其他消费者。

## 2. 本期输出合同与范围

本期只增加 `trend_channel` 数值算子。JSON 说明字段已取消：不增加 `CalculationValues.info`，不返回 `info: ""`，不增加 `Calculation.output_info()` 或相关注册、校验、编码和测试。该能力未来需要时另议，不作为本期前置步骤。

拟新增算子 ID `trend_channel`、算法版本 `1.0.0`，参数为空。短期固定 25、长期固定 90，不开放管理员未要求的周期参数。返回四个必有有限 DOUBLE 字段：

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

1. 在现有股票日线计算清单加入趋势通道，补齐算法版本与四轨字段校验，与已有 MA、BOLL、MACD、KDJ、九转共享本次行情和复权基准。保留各环境已有装配路径。
2. 沿 `StockDailyKlineService` 的结果映射与日 K DTO 组织四轨。拟沿现有 `factors` 分组方式增加日线通道对象，字段映射为 `shortUpper/shortLower/longUpper/longLower`。具体 DTO 分派和所有构造、消费点在本阶段开工前冻结；共用周月线 DTO 的非目标路径不因此新增计算。
3. 首批和续页从同一批日 K 结果取得四轨，适配为现有 `TrendChannelPoint`；保持颜色、画法和开关，清理目标页面已经无用的独立日线趋势请求。保留盘口、页面日期、其他指标、游标和失败后的已加载图表。
4. 同步修改 `StockDetailQueryService._page_options()`：`supportsTrendChannel` 和 `availableMainOverlays` 按已经接入的股票日线能力返回，不再调用 `resolve_stock_daily_trend_channel_capability()`；具体条件与测试见 §4.5。不能将入口修改拖到阶段四，否则页面仍受旧数据集控制。
5. 使用当前 500 根首批、下一批和现有真实游标验收；四轨日期与本批 K 线一一对应、结果不混用复权基准，不为趋势通道另读一份行情。旧通道开关关闭、结果与续算状态目录不存在时仍须通过；目标页面不再发出旧独立通道请求。

### 4.3 阶段三：上证日线

1. 在上证日线请求的既有计算清单加入趋势通道；本地和生产继续使用各自现有的日 K 装配、来源与计算调用。共享清单也被其他指数使用时，仅对 `000001.SH` 的目标请求加项，其他指数保持原清单，不扩大页面范围。
2. 在现有计算结果映射和 `IndexKlineFactorsDto` 日线回包中按与股票相同的四轨含义组装，随后交给原有图层。具体 DTO 分派、字段和受影响构造点在本阶段开工前冻结。
3. 首批不超过 500 根，向左翻页后使用下一批 K 线和四轨；沿原 `nextEndDate`、历史下界和失败重试，不新增分页体系。`useIndexDetailController` 与 `useIndexDailyHistory` 改用日 K 回包中的四轨，停止 `fetchTrendChannel()` 的独立请求。
4. 上证四轨使用算子库返回值，不再调用 `QuoteTrendChannelQueryService`、`QuoteTrendChannelCalculator` 或旧通道缓存，也不在失败时退回旧链路。指数基础行情继续服务日 K 和新算子，不能随旧专用计算器清理。
5. 回归首批、续页、切日期、开关、错误重试及既有指标和图形；不因本次接入扩大单次返回数量或要求先一次算完整历史。以旧计算器、旧独立请求被调用即失败的测试验证迁移确实生效。

### 4.4 新旧接口和数据集的具体处理

| 对象 | 当前实现依据 | 接入后 |
| --- | --- | --- |
| 股票、指数日 K 接口 | 现有日线 App 装配、计算清单、结果组装和前端 API 类型 | 保留入口及既有日 K 行为，在目标日线指标中增加四轨；图层与其他指标使用同批日期、复权和游标。 |
| 股票旧独立接口 `/api/v1/wealth/market/stock-detail/trend-channel` | `stock_detail_trend_channel.py` → `StockDetailTrendChannelQueryService` → `StockDailyTrendChannelLakeReader` | 股票页面切换后不再调用。接口尚保留期间继续按原合同读结果文件；阶段四审计全部调用方后删除无消费者的路由、专用查询、schema 和读取器，不转调新日 K 接口或另造算子入口。 |
| 上证旧独立接口 `/api/v1/quote/detail/trend-channel` | `src/biz/api/quote.py` → `QuoteTrendChannelQueryService._load_consistent_series()` → `load_all_rows()` 与专用计算器/缓存 | 页面切换后不再调用，页面所需结果改由算子库计算。阶段四按引用删除旧路由及其专用计算、查询、缓存、schema 和前端请求代码；不因移除通道接口而删除 `quote.py` 中其他接口。 |
| 股票日线趋势通道结果数据集 `gold/indicator/stock_daily_trend_channel` | 旧读取器按股票、截止日期和根数读取正式 Parquet 结果 | 新算子、新日 K 接入和新页面入口均不依赖它；是否整体停产或清退由阶段四审计决定，页面切换不授权删除文件。 |
| 股票日线趋势通道续算状态数据集 `gold/indicator/stock_daily_trend_channel_state` | 旧数据生产需要数值续算；旧页面能力函数检查目录，但旧 API 读取器不读它 | 新算子在本请求内维护四个 EMA 数值，不读该文件；不能因为旧文件名带 `state` 就在阶段二删除整个数据集。 |
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

### 5.1 清理对象

删除对象是历史短期方向、长期方向和组合：`short_state/long_state/combined_state`、HTTP 中对应 `state/combinedState/combined_state`，以及只为它们服务的枚举、保留突破方向的计算、缓存负载、schema/check 条件和测试断言。旧 `stateRule`、带 `hysteresis` 的公式标识与版本随实际规则核对，冻结最终值并同步全部消费者。

新算子不输出当根位置，既有 `short_position/long_position` 是否随清理删除按消费者审计给出明确清单，不自动扩大为删除所有其他字段。保留四条轨道、必要行情与日期、真正的 EMA 原始数值和续算所需事实。

### 5.2 消费者清单与代码清理

- 上证：旧 calculator/query service/query/schema/API、`tests/test_quote_trend_channel_calculator.py`、查询服务和 API 测试。
- 股票：趋势通道 query service、schema/API、`stock_daily_trend_channel_contract.py`、`stock_daily_trend_channel_reader.py`、旧路由挂载、`stock_daily_trend_channel_capability.py`、旧 Settings 开关及配置说明和测试；页面对旧能力判断的依赖应在阶段二移除，不能留到本阶段才处理。
- 前端：指数 `trendChannelApiClient.ts`、股票通道 API 类型、首批和历史控制、两个 ViewModel adapter、测试样本；按真实引用决定删除和保留。
- 数据生产与检查：股票通道结果和续算字段、生成 SQL、schema、catalog、日更和 repair、bootstrap、readiness 与对应测试，先完成完整实施方和消费者审计。

活动消费者在同次获准变更中同步迁移，不留下旧方向口径或新增兼容分支。不能只删除 DTO 而继续计算无用方向，也不能因页面不再调用就自行退休整个数据集或删正式文件。历史报告保留并注明适用版本。

旧接口和专用代码在引用审计确认无消费者后删除，不长期保留旧实现或改造成兼容入口。股票旧结果和续算数据集的完整消费者及停产范围尚未冻结；该项只约束阶段四正式清理，不阻塞新算子和两个页面沿现有日 K 接入。基础行情和股票复权因子数据始终不是旧通道清理对象。

### 5.3 正式数据集迁移与执行门禁

当前 `lake_console/orchestrator/src/orchestrator/defs/stock_daily_trend_channel.py` 同时生成方向标签、轨道和续算数值。续算文件中的 `short_upper_raw/short_lower_raw/long_upper_raw/long_lower_raw` 以及 `state_source_trade_date/observed_on_partition` 分别承担数值连续性与观察日期判断，不能随方向字符串一并清空。

如清理需要改变正式 schema，在原 [DG 方案](../../lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-plan-v1.md)和[原 DG LLD](../../lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-low-level-design-v1.md)补齐：字段保留/删除、版本、全部依赖、日期/证券/文件范围、候选校验、逐文件提升、checkpoint、失败续跑和最终物理对账。预算要包括读写行数/文件数、耗时、空间、中断重跑和最后验收。当前尚未测量这些正式迁移成本，不能填造数字或直接进入执行。

正式 Lake 为 `/Volumes/datasource/data_lake`，候选在 `/Volumes/datasource/data_lake_staging`；完整校验后同文件系统逐文件原子提升。全局明细读取、正式文件写入/删除、事件补录和任务变更按各自授权执行，不能以清理为由扩大范围。遵守[性能治理](../../lake_console/docs/design/dagster-data-pipeline-performance-governance.md)，本轮未操作这些正式资源。

## 6. 测试与分阶段验收

| 目标 | 正向测试 | 反向测试与正常例外 |
| --- | --- | --- |
| 四轨完整输出 | 首根最高 11、最低 9，两组轨道为 11/9；下一根最高 12、最低 10，按 2/26、2/91 独立手算 | 缺轨、非有限值、少根或错位失败；合法短历史可初始化。 |
| 固定预热 500 | 首目标前申报 500，输出根数另计；同算其他指标取最大需求 | 不读取 MACD 的价格上界或旧方向；到真实起点不足 500 不补造、不误报缺失。 |
| 预热误差 | **参考**从已确认完整历史起点连续计算；**被测**从目标前 500 根开始初始化；以同一行情、同一复权基准比较相同目标日期，每轨最大绝对误差不超过 0.01 | 保留 485 根的超限反例；不得把“参考与被测同一起点”用于预热误差验收，也不得用显示舍入或平均误差替代逐轨最大误差。 |
| 跨批正确性 | 这是另一类测试：整批与分批使用相同输入、相同初始化，逐轨比较 | 批次切换不重置 EMA，历史重叠行不重复计算；不能与上一行的不同起点误差测试混为一项。 |
| 同批共享 | 与现有指标同算使用同批行情、同一复权基准 | 不新增每指标取源或复权；不同参数的既有指标仍分别返回正确结果。 |
| 股票接入 | 现有指令、日 K 结果和图层接上四轨，首批/续页均最多 500 根，沿原游标；本地 DG 与 Prod 分别验证 | 页面不请求旧通道接口，不调用旧读取器；失败后保留已有图、盘口、页面日期和游标；非目标周期不被顺带启用。 |
| 股票页面入口 | 旧开关关闭、两个旧通道目录都不存在时，已接入的股票日线 page-init 仍声明支持并展示入口，日 K 能返回四轨 | page-init 与新日 K 请求期间调用旧能力函数、旧通道目录检查或 Dagster 查询即失败；正常空行情和短历史不误关入口，基础行情读取失败仍按现有错误合同处理。旧路由启动挂载的检查按原合同单独验证，不计入新页面请求断言，也不得提前开放旧独立接口。 |
| 上证接入 | 沿当前装配与回包映射，首批/续页、开关、切日期、重试通过，四轨只用算子库结果 | 旧专用计算器、旧通道缓存、旧独立请求被调用即失败；不要求一次返回 2,000 根，不改变旧独立端点合同来冒充接入；四轨与当批 K 线对齐。 |
| 接口与数据边界 | 阶段四引用审计后删除无消费者的旧接口、专用代码和配置；日 K 与基础行情、股票复权因子数据继续可用 | 页面接入不读旧通道成品/续算文件；取消或失败不回退旧链路；未批准整个数据集退出前不删正式文件、停产或修改调度。 |
| 旧方向清理 | 四轨、图形、实际 EMA 续算数值仍正确，活动消费者同步切换 | 活动链路不再产出或读取旧方向、组合标签；不能误删数值续算、生命周期、停牌延续及源日期事实。 |
| 本期不做 JSON | 既有请求、结果与算子接口保持原结构，新增算子仅四个数值字段 | 不增加 `info`、说明空串、`output_info()` 或 JSON 专项测试。 |
| MACD 不变与取消 | 原默认/自定义参数、历史需求、数值和版本回归；跨批失败/取消可清理并重试 | 不调整 100 万常量或既有精度；失败不返回部分结果，不把状态清理失败当成功。 |

阶段一已新增 `tests/foundation/technical_indicators/test_trend_channel_calculation.py`，覆盖注册、历史需求、输出、取消和来源隔离；未增加 JSON 说明测试。阶段二至少覆盖 `tests/web/test_wealth_stock_detail_api.py`、现有股票日 K 服务测试与股票页面/历史加载测试，页面用例不再以伪造旧 capability 启用来证明新接入；`tests/test_stock_daily_trend_channel_capability.py` 在旧接口保留时继续验证旧接口限制，不能为了新页面修改预期而提前开放旧路由。阶段三补现有指数日 K、`useIndexDetailController`、历史加载和页面测试，独立断言算子结果映射及旧计算器不被调用。部署前进行实际目标环境的有界只读与浏览器验收。受保护 D3 测试继续按原启动与预算执行，不直接全量运行。

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

阶段一实现及验收见 §9，提交管理员 review 后再分别推进股票接入、上证接入；旧业务清理与正式数据迁移按阶段四补齐设计、审计和执行范围。每步开工前完成该步所需代码、消费者、合同、预算和测试准备，不把前一步通过当成后续全部完成。正式环境部署和文件写入继续按阶段授权。

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
