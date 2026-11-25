# 趋势通道算子与通用 JSON 说明字段 LLD v1

2026-11-25｜[专项方案](technical-indicator-trend-channel-plan-v1.md)记录已确认需求；本文细化拟实施位置与验收。本轮仅落文档，未修改算子、业务接口、DG 数据集或正式文件，未部署。

已确认的是四轨输出、说明字段留空、前置预热固定 500 根、每轨绝对误差不超过 0.01、清理旧方向与组合状态、保留 MACD 现状。下文新增字段和方法名是拟实施设计，不代表已经存在。代码开发前仍须完成对应步骤审计；§5.3 的正式数据集迁移设计尚未补齐，不可直接执行。

## 1. 当前实现、入口与影响面

| 对象 | 代码依据 | 对本次的影响 |
| --- | --- | --- |
| 请求与通用结果 | `packages/technical_indicators/src/goldenshare_technical_indicators/contracts.py` 的 `CalculationRequest`、`CalculationValues` | 已有 `end/latest_rows`，每项结果只有 ID、版本、参数和数值字段；新增说明字段属于共享结果合同变更。 |
| 算子及工厂 | 同包 `calculation/calculation.py`、`calculation/registry.py`、`calculation/indicators/__init__.py` | 复用定义、工厂冻结与完整接口检查；趋势通道尚未注册。 |
| 计算、历史、读取 | 同包 `service.py`、`calculation/engine.py`、`calculation/history.py`、`request_parser.py`、`sources/session.py` | 各算子申报需求，引擎合并后读取一次；不让趋势通道直接读库或读预计算通道。 |
| 结果与编码 | 同包 `output/contracts.py`、`output/collector.py`、`output/result.py`、`output/encoding.py` | 数值列的 DOUBLE 校验和日期时间校验各自独立；新增 JSON 文本不能进入现有数值有限值检查。 |
| 应用入口 | `src/app/runtime/technical_indicators/{composition,execution,response}.py`，`src/app/dependencies/stock_daily_technical_indicators.py`、`index_daily_technical_indicators.py` 及周月线、分钟线现行装配 | 共用结果合同需要审计所有编码、构造、消费和测试；本次不顺手改其他指标的值或业务接口。 |
| 上证旧业务 | `src/biz/services/quote_trend_channel_calculator.py`、`quote_trend_channel_query_service.py`，`src/biz/schemas/quote_trend_channel.py`，`src/biz/api/quote.py` | 旧计算含方向标签，旧 HTTP 合同也有对应字段；不能只改计算器而漏掉 DTO 和调用方。 |
| 股票旧业务 | `src/biz/queries/wealth/market/stock_detail_trend_channel/stock_detail_trend_channel_query_service.py`，`src/foundation/clients/local_lake/stock_daily_trend_channel_{contract,reader}.py`，对应 API 与 DTO | 当前消费正式预计算文件，必须先核对生产者及 schema，不能根据新查询反推上游已有字段。 |
| 前端 | `wealth/src/features/index-detail/api/trendChannelAdapter.ts`、股票趋势通道适配器、`wealth/src/shared/charts/trend-channel/trendChannelGeometry.ts` | 传给绘图的只有日期、收盘价和四轨；着色按当根收盘价是否低于当根下轨判断。旧方向字段存在于 API 类型和测试样本，但不参与绘图。 |

本轮使用 CodeGraph `codegraph_explore(CalculationValues)` 与 `codegraph_impact(TrendChannelCalculator)` 识别共享结果、旧查询服务与测试影响，再用当前源码和精确引用搜索核实。CodeGraph 的同名 `calculate` 还命中板块等无关业务，不能把这些命中直接当成真实依赖。未来删除前必须重新核对完整引用，不用本表冒充已经清理完成。

## 2. 通用 JSON 说明字段

### 2.1 对外合同

在 `CalculationValues` 增加 `info: str = ""`，每项算子一个字段。现有 `fields` 仍只放数值数组，`times` 仍是公共时间轴。

- `info == ""` 表示没有说明；不是 `null`、字符串 `"null"` 或自动填入空对象。
- 非空值是合法 JSON 文本，JSON 内部字段、含义、允许值以及是否含逐根信息，由对应算子的说明和测试定义。通用库不固定其内部业务结构。
- 接口外层的 `info` 类型是字符串，编码后内部引号会按 JSON 字符串规则转义；调用方需要使用说明时再解析该字符串。不得擅自改成外层 JSON 对象。
- 若未来某个算子的说明包含逐根结果，该算子必须定义与 `times` 对应的方式，且只交付目标结果的信息，不把预热明细交给业务。趋势通道本次无此非空结构，固定返回空串。
- 不把现有数值列改成 VARCHAR，也不为趋势通道新增五个枚举输出列。日期/分钟时间继续按 DATE/TIMESTAMP 检查，编码为现有 ISO 日期时间字符串。

拟返回形状只新增一个说明字段：

```json
{
  "calculation_id": "trend_channel",
  "algorithm_version": "1.0.0",
  "parameters": {},
  "fields": {
    "short_upper": [11.0],
    "short_lower": [9.0],
    "long_upper": [11.0],
    "long_lower": [9.0]
  },
  "info": ""
}
```

上例是一根最高价 11、最低价 9 的初始化字面样本，不是正式行情验收证据。完整响应继续包含 `times` 等公共信息。

### 2.2 算子提供与库内交接

拟在 `Calculation` 增加 `output_info() -> str`，于本次计算完成后取得该节点的完整说明文本。内置价格、内部窗口均值、MA、BOLL、MACD、内部窗口 RSV、KDJ、九转和新增趋势通道均显式返回空串；不使用 `getattr` 默认值、旧新两套接口或业务侧补字段。未来需要非空说明的算子自行实现该方法，不能在通用服务里按算子 ID 拼业务 JSON。

| 修改位置 | 拟实施内容 |
| --- | --- |
| `calculation/calculation.py`、`calculation/registry.py` | 在协议与工厂完整性检查中同步加入 `output_info`，迁移全部实际实现与测试替身。 |
| `calculation/engine.py` | 在 `finish()` 后、资源关闭前，按本次请求顺序从计算节点取得说明。相同算子、相同参数仍共享节点，各请求项各有结果；不同参数不混用说明。 |
| `service.py` | 将说明按现有整数请求下标交给输出模块；没有说明时也明确传空串。 |
| `output/collector.py`、`output/result.py` | 继续完成原数值与时间位置检查，再核对说明项与请求项对应。说明必须是字符串；非空时校验为严格合法 JSON，失败走现有整次输出错误，不返回部分成功。通用校验不判断内部业务字段。 |
| `contracts.py`、`output/encoding.py` | 构造每项 `CalculationValues.info`，外层显式编码该字符串。保留原文，不在库里重排或增删其 JSON 业务字段。 |
| `discovery/catalog.py` 与算子文档 | 能力说明注明每项结果有通用说明字段；具体算子使用非空信息时同步说明内部结构。本次各内置算子均为空。 |

非空 JSON 的通路用隔离算子测试验证；不能只给结果对象添一个永远不接算子的字段，就声称通用能力完成。说明文本不能成为绕过现有 SQL 计算、输入输出合同或来源边界的入口。未来需要从 SQL 产生非空业务说明时，在对应算子专项中明确其固定读取与交接方式，本次不开放任意 SQL 或源读取接口。

开发前消费者审计至少覆盖：上述全部构造和编码点；`tests/foundation/technical_indicators/test_contracts.py`、`test_registry_dependencies.py`、`test_d3_engine_extension.py`、`test_request_reuse_correction.py`；`tests/app/technical_indicators/test_output_encoding_correction.py`、`test_execution_cancellation.py`、`test_stock_daily_integration.py`；股票日 K helpers 与服务结果构造；当前独立包安装及 DG 引用方。严格检查结果键集合的消费者在同一变更中迁移，不保留缺字段的旧口径。包版本和内核合同版本按该次发版核对，本轮不改版本号或环境安装。

## 3. 趋势通道算子的实施位置

### 3.1 定义与公式

拟新增 `packages/technical_indicators/src/goldenshare_technical_indicators/calculation/indicators/trend_channel.py`，实现 `TrendChannelCalculation`，在 `create_builtin_registry()` 冻结前注册：

| 项目 | 拟实施值与依据 |
| --- | --- |
| ID、算法版本 | `trend_channel`、`1.0.0`；新算子自身的命名和版本，不冒用旧日线接口版本。 |
| 参数 | 空参数；短期 25、长期 90 沿既有公式，本期不开放新的参数。 |
| 输入 | 最高价 `high`、最低价 `low`；移除旧方向判断后不再需要收盘价来计算四轨。来源原有 OHLC 合同照常执行。 |
| 输出 | `short_upper/short_lower/long_upper/long_lower` 四个必有的有限 DOUBLE 值；单位沿源价格单位。 |
| 说明 | `output_info()` 返回 `""`。 |
| 支持组合 | 遵循现有证券、周期、复权与来源启用合同，不额外开放来源或添加业务未要求的周期限制；每个实际启用组合仍须有对应验收证据。既有业务清理对象是股票日线和上证日线。 |

短期递推系数为 `2/26`，长期为 `2/91`；上轨用最高价、下轨用最低价。首次输入时分别取该根最高价、最低价初始化，后续为 `新 EMA = α × 本根价格 + (1−α) × 上根 EMA`。计算中不按两位或四位小数逐根量化；0.01 是绝对误差要求，不是中间结果舍入规则。

### 3.2 历史需求、状态与 SQL

`input_requirement(session, max_input_rows)` 直接声明 `HistoryRequirement(fields={high, low}, preceding_rows=0, warmup_rows=500, requires_source_origin=False, state_fields=(last_seq, short_upper, short_lower, long_upper, long_lower), ...)`。在 `trend_channel.py` 以 `TREND_CHANNEL_WARMUP_ROWS = 500` 保存唯一数值来源，历史需求与算子能力说明读取该算法常量；测试以管理员确认的 500 作独立预期。该值随算子版本生效，不存入 Settings、环境变量或数据库，不开放运营输入，也不复用 MACD 的最低值常量。它不引用 `PRICE_ABSOLUTE_BOUND`，不使用 MACD 的动态误差搜索。

`prepare/consume/release_batch/release` 沿现有算子生命周期：

1. `prepare` 准备固定系数和本请求数值状态表；复用现有 `smoothing_parameters.sql` 的分段范围计算，不自行另定无依据的段长。
2. `consume` 首次设置四个 EMA 和 `last_seq`，之后仅处理新序号；使用固定 SQL 对四条独立 EMA 分段递推，每段末尾更新四个原始数值和序号。批次重叠历史不得再次推进状态。
3. 拟增加固定资源 `trend_channel_first.sql` 与 `trend_channel_segment.sql`，登记到该类的 SQL 资源声明与现有白名单。SQL 只读取本请求共享行情、自有参数和数值状态，输出 `seq` 与四轨。
4. 每批只保留数值续算状态，释放本批临时输出；结束、失败、超时或取消时沿引擎统一清理。

四个 EMA 数值和序号是计算所需状态，不能因为删除“方向状态”而一并删除。不得新增 `short_state/long_state/combined_state`，不得用旧 `_position` 或历史突破标签驱动数值或颜色，不读取已有通道成品来填四轨。

## 4. 截止日期、根数与预算

请求沿 `CalculationRequest(end=带时区的截止时间, latest_rows=R, ...)`；业务通常不传 `start`，现有入口明确给定目标下界时仍保留其语义。日周月读取按现有上海时间归一后的业务日期处理，分钟使用现有业务时间。来源支持仍按 `CalculationRequestParser` 的实际启用范围核对，不能声称任意 Prod/DG 组合已经支持按根数定位。

读取模块先定位目标 R 根，再补 500 根实际 K 线；到已确认的来源起点而不足 500 时用已有历史初始化。来源错误或应有记录缺失沿现有合同处理，不截少、不补零。收集器只收集目标区间，四轨数组与 `times` 一一对应，输出不含预热。

| 场景 | 可复算的计算输入与恢复成本 |
| --- | --- |
| 单算趋势通道，返回 R 根 | 历史足够时 `R + 500` 根，四条 EMA 在同一批行情上计算。 |
| 返回 500 根 | `500 + 500 = 1,000` 根计算输入；只返回后 500 根。 |
| 同算其他指标 | `R + max(各算子实际历史需求)`，窗口历史按现有规则共享；不得相加、逐指标取源或逐指标复权。 |
| 中断后重试 | 不保存新的跨请求业务状态；同一请求重新读取、计算与清理。一轮原请求加一轮完整重试至多按两轮所需计算输入计，单算时为 `2 × (R + 500)`；实际中断点可能少于完整一轮。 |
| 最后验收 | 每个获准验收请求的参考与被测输入分别计量；已有样本复用，不把参考计算也说成唯一源行情根数。真实来源只做获准证券、周期和有界窗口，不默认扫描数据集。 |

现有 `max_output_rows/max_input_rows`、批量、请求时限、内存、文件、SQL 及编码字节限制沿用本次装配，不新增数值上限、不擅自扩大容量。四条 EMA 的累计递推次数与 K 线根数、文件读取量分别记录。当前没有趋势通道在共享 SQL 链路上的端到端耗时、物理读量或内存实测，不能套用旧业务计算器的耗时；实施验收记录实测后再判断现有预算能否满足，中断后的重跑与清理也计入。

## 5. 旧业务清理：本次需求中的独立步骤

### 5.1 先明确删什么

清理对象是短期方向、长期方向及二者组合：`short_state/long_state/combined_state`，HTTP 中短期/长期通道的 `state` 与 `combinedState/combined_state`，以及只为这些标签服务的枚举、突破保留计算、缓存负载、schema/check 条件和测试断言。旧 `stateRule`、带 `hysteresis` 的公式标识及公式版本也随实际规则核对，在该步原方案中冻结最终值并同步全部消费者，不能数值已切换而公式说明仍宣称保留突破方向。

同日位置 `short_position/long_position` 与历史方向不是同一含义。本次新算子不输出位置，也不填入说明 JSON；存量位置字段是否随清理删除，必须在消费者审计中列出明确清单，不默认为管理员授权删除所有其他字段。保留四轨、必要行情、日期和真正用于后续递推的 EMA 数值。

### 5.2 代码、API 与页面清单

| 链路 | 必须逐项核对的实施方和消费者 | 清理验收 |
| --- | --- | --- |
| 上证指数 | `quote_trend_channel_calculator.py`、`quote_trend_channel_query_service.py`、`quote_trend_channel_query.py`、`schemas/quote_trend_channel.py`、`api/quote.py`；`tests/test_quote_trend_channel_{calculator,query_service}.py`、`tests/web/test_quote_trend_channel_api.py` | 删除无用方向计算和 DTO 字段；原鉴权、证券/周期边界、目标日期及翻页行为分别回归。四轨切换固定 500 后按 0.01 验收，不再宣称与旧全历史结果逐位相同。 |
| 股票日线 | `stock_detail_trend_channel_query_service.py`、对应 schema/API、`stock_daily_trend_channel_contract.py`、`stock_daily_trend_channel_reader.py` 和其契约/API 测试 | 必须先核对正式文件生产者；不得只删查询投影而遗留仍强制要求旧字段的 schema 校验。 |
| 前端 | 指数 `trendChannelApiClient.ts`，股票 `stockTrendChannelApiTypes.ts`，两条 ViewModel adapter、测试样本与股票历史控制测试 | 同步清除旧方向类型和样本。现有绘图只用日期、收盘价和四轨，保持其画法、颜色和开关行为。 |
| 共享包接线 | 迁移需要行情与轨道同批时，请求已有 `price` 和新 `trend_channel`，按公共时间轴组装；使用各自已启用的来源与复权口径 | 不让业务侧计算轨道或拼初始值；不将股票预计算结果与指数完整历史算法当成新算子的第二套实现。 |

当前 Prod 的按根数读取并未对全部组合启用。具体业务环境接入前，应先在本 LLD 补齐目标入口、来源支持、请求构造、完整消费者及最小真实验证，不用业务端自行倒推日期替代缺少的读取能力。API 字段移除在同次获准变更中迁移所有消费者，不保留运行时双合同；部署与代码审查分开处理。

### 5.3 股票日线正式数据集的清理边界

当前 `lake_console/orchestrator/src/orchestrator/defs/stock_daily_trend_channel.py` 同时计算和校验方向标签；`run_contracts/asset_column_schemas.py`、`defs/assets/stock_daily_trend_channel.py`、相关 checks、catalog、日常与 repair job/sensor、bootstrap 和 readiness 都属于审计入口。正式结果文件和续算文件分别由上述原 DG 方案与 LLD 管理。

这里不能只删除一个 `state` 文件：续算表中 `short_upper_raw/short_lower_raw/long_upper_raw/long_lower_raw` 是四个 EMA 原始数值，`state_source_trade_date/observed_on_partition` 还参与当日观察与延续判断。它们与无用的方向字符串必须分开核实。算法升级不能误删停牌延续、股票生命周期、源日期或覆盖检查。

本次把下列工作纳入清理步骤，尚未以本轮静态阅读代替其实施前审计：

1. 在原 DG 方案/LLD 写清每个待删字段、保留字段、schema/公式版本、实际依赖与迁移顺序；核对日更、repair、历史、readiness、catalog、事件和物理文件消费者。
2. 列出目标日期/证券/文件范围、只读核验方式、候选生成与校验、正式提升、逐文件 checkpoint、失败续跑、最终 schema 与覆盖对账。范围、文件量、读写量、耗时、空间、重跑和最终验收预算目前未测，不得填造数字或直接进入编码/正式执行。
3. 原方案与 LLD 复审通过后，才按对应阶段修改 DG 实现、执行获准的正式迁移。正式 Lake 为 `/Volumes/datasource/data_lake`；候选只能在 `/Volumes/datasource/data_lake_staging`，完整校验后同文件系统逐文件原子提升。本轮不包含全局明细读取、重写、删文件、补事件或变更自动任务；后续确有必要时分别遵守对应授权和性能门禁，不得以清理为由扩大范围。
4. 历史验收和旧报告保留并标明适用版本；活动实现及全部消费者切换后才能验收旧方向引用清零。不得以新算子验收通过代替数据集清理完成。

这部分遵守[性能治理](../../lake_console/docs/design/dagster-data-pipeline-performance-governance.md)及原 DG 规则。本轮未访问正式 instance、Lake 或数据库，也未执行任何 Dagster 命令。

## 6. 测试、真实验收和开发前对账

以下是待实施门禁，不是本轮通过清单。测试夹具先核对现有生产者、schema 和有界样本；预期不得由待测算子或同一计算 helper 生成。

| 约束 | 正向验证 | 反向验证及不会误拦的样本 |
| --- | --- | --- |
| JSON 通用说明 | 两个隔离算子用不同内部 JSON 字段，通过统一计算与编码原样返回；空串、中文和引号可正确编码 | 非字符串、非空非法 JSON 不返回成功；合法空串及合法不同结构不因无统一 schema 被拒绝。 |
| 四轨完整输出 | 首根最高 11、最低 9 时两组上下轨分别为 11/9；下一根最高 12、最低 10，独立按 2/26、2/91 手算 | 缺任一轨道、非有限值、错位或少根按现有输出合同失败；真实短历史正常初始化。 |
| 固定 500 | 历史充足时首目标前恰好申报 500；返回根数另计；与其他算子同算取最大需求 | 不受 `PRICE_ABSOLUTE_BOUND` 变化驱动，不请求旧方向状态；来源起点不足 500 的合法样本仍可计算，不能误认缺失或补造行情。 |
| 跨批与共享 | 一次输入与分批输入使用同一初始化，逐轨比较；与 MACD/KDJ 同算只准备一批行情、只做一次该批复权 | 检查批次切换不重新初始化，重叠行不重算；相同与不同参数的既有算子仍分别正确。 |
| 0.01 绝对误差 | 固定样本及获准真实窗口逐轨对完整参考核验；参考与被测使用相同来源、复权基准、起点 | 485 根的既有反例应能超限；不以显示两位小数相同、总平均误差或某一轨道通过替代逐轨最大误差。 |
| 方向清理 | 四轨和原绘图仍正常；JSON 说明为空；所有活动消费者按新合同运行 | 活动实现不再产出/读取旧方向与组合标签；不得仅删 DTO 而继续计算。保留原始 EMA 续算值的正常样本。 |
| 失败与取消 | 首批、跨批、失败后的同请求重试，资源按现有生命周期归还 | 一批成功后故障/取消也不得返回部分结果，不把清理失败当成功。 |
| MACD 不变 | 默认及既有自定义参数的历史需求、数值、算法版本与说明空值回归 | 不改变 MACD 的 100 万常量、最低预热、误差要求或动态搜索；趋势通道的 0.01 不扩展为其他指标的新容差。 |

拟新增普通隔离测试 `tests/foundation/technical_indicators/test_trend_channel_calculation.py` 与 `test_calculation_info.py`；现有注册、合同、编码、执行取消和业务测试按实际影响补充。文件名是拟实施位置，当前不存在不代表已漏跑测试。受保护 D3 用例继续遵守其原启动与预算，不直接全量执行。

最小真实验收优先复用有来源的固定证据，仅补缺失的获准证券、周期和少量日期。核对源 high/low、复权基准、目标及前置根数、输出时间和四轨误差，区分隔离输入、真实只读和正式迁移；不为凑验收覆盖而全市场扫描。实际场景超过 0.01 时先记录证据并回到设计，不自行加预热、放宽误差或引入全历史回退。

## 7. 已有测算证据及其范围

### 7.1 固定上证指数样本

来源为[输入夹具](../../tests/fixtures/quote_trend_channel/000001_sh_daily_input.json)，SHA-256 为 `ed585326d64fae260f14e7ec53b885037db31609726ed38cb20c1cbe772e42ad`，日期 2020-01-02 至 2026-08-07，共 1,599 根。来源说明为当时 `core_serving.index_daily_serving` 的固定快照；本轮不重读生产库。四价的基本合同见[既有测试](../../tests/test_quote_trend_channel_calculator.py)。

本轮先从样本首根用 70 位 Decimal 独立递推四条完整轨道。对每个 H，从目标位置 H 到 1598，分别取该目标之前 H 根加目标一根，用双精度重新初始化和递推，与独立完整参考比较。每轨窗口数为 `1599−H`。在同一段初始化后，后续误差按 EMA 衰减；此验证主要检查每个可用窗口的第一根输出，不冒充 SQL 新算子或真实业务集成验收。

| H | 每条轨道的窗口数 | 最大绝对误差（点） | 达标情况 |
| --- | --- | --- | --- |
| 485 | 1,114 | 0.010067342861678173 | 长期上轨有一个窗口超过 0.01 |
| 486 | 1,113 | 0.0098460825786383 | 四轨各窗口均不超过 0.01 |
| 500 | 1,099 | 0.007213467416398642 | 四轨各窗口均不超过 0.01 |

H=500 时短期上轨、短期下轨、长期上轨、长期下轨的最大绝对误差分别约为 `4.70×10⁻¹²`、`4.12×10⁻¹²`、`0.0072134674`、`0.0068476520` 点。这里只验证这批输入及其起点；486 不是全证券最低预热根数，500 是管理员最终确认的设计决定，不能写成已证明覆盖任意价格序列的数学保证。

### 7.2 讨论中各数字的最终含义

| 数字 | 已核实含义与本次处理 |
| --- | --- |
| 0.01 | 管理员确认的趋势通道逐轨绝对误差要求；单位沿输入价格，不是浮点位数或每步舍入。 |
| 500 | 管理员确认的趋势通道固定前置根数；不能因为与 MACD 下限数值相同，就共用 MACD 的推导依据或误差参数。 |
| 486 | 既有 1,599 根上证样本的窗口复算结果；保留证据，不用于修改最终 500 根决定。 |
| 829 | 假定初始差值不超过 100 万，按 `误差 = 初始差值 × (89/91)^H` 得出的条件根数；未采用，不是本次预算，也不与 500 相加。 |
| 100 万 | 当前共享计算库 `calculation/history.py` 的 `PRICE_ABSOLUTE_BOUND`，由 MACD 固定预热 SQL 使用；是价格范围的验证假设，不是实测价格或实测误差。原 LLD 声明其用途，但本次未找到选择该值的充分业务取值说明。管理员决定保留，不在本轮整改。 |
| 默认 MACD 的 500 | 标准精度路径先规定最低 500，再按参数、100 万范围与 `2.5×10⁻⁹` 初始化误差要求验证是否足够；较长自定义参数可能需要更多。不能说“100 万恰好推导出最低 500 根”。 |

按当前 MACD 误差公式、默认参数 12/26/9 和上述原条件复算，去掉固定 500 下限时 467 根已满足、466 根不满足。这只是说明“固定下限”与“误差校验”是两件事；不是本次降低 MACD 预热或更改其精度的建议。旧所谓“内核”实际仍是当前共享技术指标计算库中的 MACD 模块，没有另外一套已退役运行系统。

## 8. 本轮文档验收与后续开工边界

本轮只对账需求、源码引用、样本测算、索引和文档完整性；不以这些结果宣称新算子、JSON 能力或清理已实现。业务结果合同开发、旧 API 消费者同步迁移、正式数据集字段迁移和部署是不同步骤。

后续每步开工前按本文映射补齐该步尚缺的完整消费者清单、来源支持、真实样本、性能预算及验收，再按获准范围实施。尤其 §5.3 尚缺正式迁移的范围与成本，不能据本 LLD 直接修改生产 schema、正式 Parquet、sensor、job、cursor 或事件。用户已确认的 500 根、0.01、JSON 留空、清理步骤和 MACD 保留决定无需再次拍板；新增实施范围与正式写入仍按阶段处理。
