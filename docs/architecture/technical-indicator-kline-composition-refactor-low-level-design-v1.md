# 股票与指数 K 线指标组装架构改进 LLD v1

**状态**　2026-11-27，三个阶段均已通过验收，阶段 3 的完整回归和独立对照见 §9。本文承接[架构改进方案及目标流程图](technical-indicator-kline-composition-refactor-plan-v1.md)。原代码审计基线为 `de20bc808`，本需求相关代码与九转阶段一提交 `9d7e10c04` 无差异。阶段 1 的改造前比较点为方案、LLD 的提交 `c58b840e4`，阶段 2 的源码比较点为阶段 1 提交 `199d16e13`。

## 1. 开发约束

- 股票日线和周月线各自的 `assemble()` 保留现行职责。改为调用原文件中更名后的 `build_stock_calculation_field_map()`。不提取股票与指数组装的共享函数，不搬迁股票逐指标组装文件。
- 指数日线和周月线各自负责整份算子回包，按需调用指数业务 `compose/` 里的逐指标函数。周月线脱离日线查询类与文件。指数的算子路径直接从计算结果取指标值，旧列仍供现有直读预计算结果路径使用。
- API 地址、路由分支、请求边界、鉴权、算子请求和预热、源和读取次数、日期、分页、单位、字段、空值、异常与 debug 诊断均以当前行为为准。只读会话移到技术指标运行目录，复用的是数据库资源管理，不是股票或指数的业务逻辑。
- 暂停 Prod 股票日线九转阶段二旧能力删除。主要指数日线趋势通道扩展另按方案 §5 推进。本次上线范围也不增加任何周期、标的或 API 字段。分钟线、独立九转、数据集、前端业务代码和部署均不改动。

## 2. 交叉引用审计与修正

以下行号对应本轮源码。用 CodeGraph `codegraph_explore` 追到入口、服务和回包，并以源码导入、符号引用、测试替换点和前端消费者核对动态调用。具体路径也列在 §3–§5。

| 当前代码 | 问题及修正 |
| --- | --- |
| [`index_detail_period_kline_query_service.py` 11–19、35–60、147 行](../../src/biz/queries/wealth/market/index_detail/index_detail_period_kline_query_service.py#L11) 继承 `IndexDetailKlineQueryService`，使用父类的 `_universe_service`、`_context_query`、`_query`、`_daily_lake`、`_status_resolver`、`_build_identity_or_raise()`。 | 周月线只需要同一套指数身份、上下文和数据状态能力，没有调用日线 K 线流程。去掉继承。周月线查询类直接装配原 `IndexDetailUniverseService`、`MarketPageContextQuery`、`IndexDetailQuery` 和 `daily_lake`，将本页对象字段交给周月线组装服务。日线与周月线组装服务分别使用现有 `IndexDetailStatusResolver`。原身份错误处理提到指数领域共用的 `index_detail_field_mapper.py:require_index_kline_identity()`，四个日线调用和一个周月线调用全部迁移。保持缺身份、缺名称两种 `IndexDetailNotFoundError` 和原异常链。 |
| [`index_period_technical_indicators.py` 9、49 行](../../src/app/dependencies/index_period_technical_indicators.py#L7) 从日线查询文件导入 `SSE_DAILY_CALCULATIONS`。[`index_daily_technical_indicators.py` 11–13、53–59 行](../../src/app/dependencies/index_daily_technical_indicators.py#L9) 从同一查询文件导入 `index_daily_calculations()`。 | 算子清单属于指数 K 线业务，查询文件承担的是选行情和日期。将清单和两个请求清单函数放入 `src/biz/services/wealth/market/index_detail/index_kline_calculations.py`。App 日线、周月线入口分别用各自函数，日线结果检查也用同一个日线函数核对实例。保持原顺序、参数、加权方式、市场和周期。 |
| [`index_detail_period_kline_query_service.py` 11–13、145–146 行](../../src/biz/queries/wealth/market/index_detail/index_detail_period_kline_query_service.py#L120) 从日线文件导入 `apply_calculated_kline_factors()` 和 `count_calculated_kline_missing()`。[`index_detail_kline_query_service.py` 116–139、340–341、385–386 行](../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py#L116) 通过旧列共用校验与缺项统计。 | 将公共结果校验和缺项统计迁移到 `src/biz/services/wealth/market/index_detail/index_kline_result.py`。校验后的指标列直接供 `compose/` 使用，缺项统计从同一批行情及指标列取值。删除旧写入函数。两条算子路径不再把 MACD `hist` 写成 `macd_bfq`，再从该列取回相同的数。现有直读路径继续用 `build_kline_bar(row)`。 |
| [`index_detail_kline_query_service.py` 142–159、392–419 行](../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py#L392) 同时负责查询和算子回包装配，调用旧行情行组装函数。周月线在 [`query_period_kline()` 120–158 行](../../src/biz/queries/wealth/market/index_detail/index_detail_period_kline_query_service.py#L120) 做同类的工作。 | 日线算子回包迁到 `.../index_detail/index_daily_kline_service.py`，周月线算子回包迁到 `.../index_detail/index_period_kline_service.py`。业务查询只调用各自服务。`compose/` 不导入任何查询文件、App 或股票代码。现有行情展示映射、状态解析与九转标记规则继续依赖现有共用函数。 |
| [`index_daily_technical_indicators.py` 9、87 行](../../src/app/dependencies/index_daily_technical_indicators.py#L85) 和 [`index_period_technical_indicators.py` 7、60 行](../../src/app/dependencies/index_period_technical_indicators.py#L54) 都从股票日线入口导入 `open_stock_daily_read_session()`。定义在 [`stock_daily_technical_indicators.py` 43–149 行](../../src/app/dependencies/stock_daily_technical_indicators.py#L43)。 | 此函数只封装 PostgreSQL 只读会话及清理，完全没有股票业务入参。整体移到 `src/app/runtime/technical_indicators/read_session.py:open_technical_indicator_read_session()`，三个 App 入口显式导入同一函数。保留所在请求的会话边界、超时执行、清理顺序和现有错误内容。详见 §3。 |
| [`index_detail_field_mapper.py` 30–33 行](../../src/biz/services/wealth/market/index_detail/index_detail_field_mapper.py#L30) 的 `to_float()` 也由指数权重查询在 [`index_detail_weights_query_service.py` 17 行](../../src/biz/queries/wealth/market/index_detail/index_detail_weights_query_service.py#L17) 导入。 | 若逐指标组装从整个旧行情字段文件借用这一个转换，会让新组装继续依赖旧组装。将函数原样移到 `src/biz/services/wealth/market/index_detail/index_detail_value_conversion.py`，老字段映射、权重查询和需要转型的 `compose/` 文件直接导入。权重查询仅改这一行导入，保持原调用和功能。 |

核实后保留的依赖也有明确理由。周月线未传 `endDate` 时通过 `IndexDetailQuery.load_latest_quote()` 获取现有业务截止日，这是一次必要的日行情查询，与继承日线 K 线查询是两件事。`technical_indicator_stock_daily.py` 文件名带 `stock`，但文件定义的是底层普通股票和指数日线行情合同，指数 `dg_index_daily_origin()` 还被数据源和指数九转使用，本次保留。`build_nine_turn_marker()` 已经放在九转业务公共目录，既有引用继续使用。Prod 上证 App 经 `_prepare_calculation()` 与 `_calculate_library(..., collect_target_ohlc=True)` 取得同批 OHLC，其算子库调用合同留在本阶段。 [行情合同](../../src/foundation/clients/technical_indicator_stock_daily.py) · [九转标记](../../src/biz/services/wealth/market/nine_turn/nine_turn_response_policy.py)

## 3. 股票与 App 只读会话

| 文件 | 保留及修改内容 |
| --- | --- |
| [`src/biz/services/wealth/market/stock_detail/stock_kline_factor_mapper.py` 10–53 行](../../src/biz/services/wealth/market/stock_detail/stock_kline_factor_mapper.py#L10) | 第 14 行更名为 `build_stock_calculation_field_map(calculations)`，保留 `stock_calculation_key()` 对参数排序、字段名及原结果元组引用。所有逐指标函数和 `build_stock_common_factors()` 照旧。 |
| [`src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py` 34、60–84、86–132、134–206 行](../../src/biz/services/wealth/market/stock_detail/stock_daily_kline_service.py#L134) | 第 34、144 行更新导入和调用。`prepare_recent()` 仍从同批行情拿日期后读取日线基础指标。`_validate_result()` 保留 series、日期、根数、实例、算法版本、字段、空值、有限值和九转校验的次序。`assemble()` 保留同一下标取价格、四组指标、四轨及九转计数，保留原报价与三个响应类型选择、截断诊断的数据范围和异常链。 |
| [`src/biz/services/wealth/market/stock_detail/stock_period_kline_service.py` 21、52–83、86–138 行](../../src/biz/services/wealth/market/stock_detail/stock_period_kline_service.py#L75) | 第 21、96 行更新导入与调用。保留周/月 `calculate_with_source()` 的原入参、最新一期覆盖及显示日，`build_kline_bar()` 与九转用同一显示日期，原 `period_bars`、`source_as_of`、单位、状态、游标照旧。 |
| [`src/app/dependencies/stock_daily_technical_indicators.py` 43–149、188–236、240–269 行](../../src/app/dependencies/stock_daily_technical_indicators.py#L43) | 移走会话函数和仅为它使用的导入。在第 219、255 行换成新的会话函数调用。股票日线 Prod 保持先准备、退出会话再计算。周月线 Prod 保持同样的准备会话边界。DG 两条分支保持原调用和参考资料读取。 |
| `src/app/runtime/technical_indicators/read_session.py`（新增） | 移入 `open_technical_indicator_read_session(session_factory, control)`。连同局部 `set_timeout()`、`record_cleanup()`、`discard_connection()` 原样迁移；保留 `stock_daily_database/...` 的错误和清理诊断文本，连同原有 driver 检查、连接只读、事件监听、`ceil(remaining * 1000)` 毫秒的 SQL 超时、取消时原分类、listener 移除、会话关闭、连接失效处理、主异常优先与无提交规则。旧入口无重导出。 |
| [`src/app/dependencies/index_daily_technical_indicators.py` 85–90 行](../../src/app/dependencies/index_daily_technical_indicators.py#L85) 与 [`src/app/dependencies/index_period_technical_indicators.py` 54–66 行](../../src/app/dependencies/index_period_technical_indicators.py#L54) | 调用同一个 `open_technical_indicator_read_session()`。日线 Prod 的 `build(session)` 仍全程处于原会话里。周月线保持 `use_dg and end_date is not None` 才无会话，其他情况原会话只覆盖 `read_page()`，后续 `query_period_kline()` 保持当前时机。 |

测试迁移至相同的调用点。`tests/test_stock_kline_factor_mapping.py:11` 使用新函数名。`tests/stock_daily_kline_helpers.py:147`、`tests/test_local_web_reference_data.py:245`、`tests/app/technical_indicators/test_stock_daily_source_repair.py:100`、`tests/app/technical_indicators/test_stock_daily_integration.py:360` 更新对股票 App 模块中实际导入的符号名。同一 integration 测试 `test_database_session_ownership_and_timeout()` 在原第 507 行改为导入 `src.app.runtime.technical_indicators.read_session`，原第 575–577 行改为替换该模块实际引用的 `event.listen/contains/remove`，原第 586 行直接调用新的会话函数。保留全部会话分支、故障注入、断言和预期值。

阶段 1 回归中发现 `tests/test_local_web_reference_data.py:test_stock_daily_reference_reads_share_the_existing_deadline()` 原夹具用 `object.__new__()` 跳过后端构造，未设置 `runtime`。在 `c58b840e4` 原源码与原测试上复现同一 `AttributeError`，因此旧用例进不到 DG 读取及故障注入。修正该用例的装配，使用临时 DG 配置创建并关闭实际 `TechnicalIndicatorRuntime`，用正常构造器创建后端。保留原 4 秒、3 秒传参和拒绝 PostgreSQL 的断言，明确断言现有 `stock_daily_reference_data/deadline` 错误。业务代码仍按 §3 只迁移和改名。

## 4. 指数公共清单、校验与指标组装

以下服务相对于 `src/biz/services/wealth/market/index_detail/`。

| 目标文件与函数 | 实施要求 |
| --- | --- |
| `index_kline_calculations.py` · `INDEX_MA_PERIODS`、`INDEX_COMMON_CALCULATIONS`、`index_daily_calculations(ts_code, *, include_price_and_nine_turn)`、`index_period_calculations()` | 七个 MA 周期按原顺序 `5, 10, 20, 30, 60, 90, 250`，随后 BOLL `period=20, multiplier=2`、MACD `fast=12, slow=26, signal=9`、KDJ `window=9, k_period=3, d_period=3`。日线按原开关追加 `price`、`nineturn`，最后仅上证追加 `trend_channel`。周月线为 `price` 在前、公共指标在后。App 两个 `CalculationRequest` 只换清单来源。日线版本表仅用于保留现有日线检查。 |
| `index_kline_result.py` · `validate_index_common_calculation_fields(ts_code, calculations, row_count)` | 从现有 `apply_calculated_kline_factors()` 分离校验。以 `(calculation_id, tuple(sorted(dict(parameters).items())))` 为键，使用 `dict(item.fields)`，只新建字典并引用原值元组。先检查输入实例数与去重后实例数等于公共清单，再按原清单和字段顺序检查名字和长度（各 MA `value`，BOLL `upper, middle, lower`，MACD `dif, dea, hist`，KDJ `k, d, j`），准确复用 `本页指标实例不完整` 与 `指标结果字段不完整：{id}.{field}`。返回已验证的字段字典。保留原有对额外公共输出列的处理，不把日线版本检查加到周月线。 |
| 同一文件 · `count_calculated_kline_missing(rows, fields_by_calculation, preceding_rows)` | 对于每根 K 线，统计行情列 `open/high/low/close/pre_close/change/pct_change/vol/amount` 的 `None` 数，加上 MACD 的 `dif/dea/hist` 与 KDJ 的 `k/d/j` 的 `None` 数。每个 MA 仅在 `preceding_rows + index + 1 >= period` 时计缺，BOLL 三列仅在有效根数达到现有周期 20 时计缺。按缺失字段计数，不按缺失 K 线计数。趋势通道继续单独按强合同检查，本地九转继续单独检查，二者都不加入缺项数。判定使用原值，在 DTO 转型前完成。 |
| `index_detail_value_conversion.py` · `to_float(value)` | 沿用 `None → None`、其他值 `float(value)` 及原错误行为。新旧指标组装沿用同样的数值表示。趋势通道保留现有有限数值检查及 DTO 转型，不增加中间舍入。 |
| `index_detail_field_mapper.py` · `require_index_kline_identity(identity_row, *, ts_code)`、`build_index_kline_bar_fields(row)`、`build_kline_bar(row)` | 身份函数搬运原 `_build_identity_or_raise()`，`build_identity()` 规则不变。两个新服务使用 `build_index_kline_bar_fields()` 复用行情显示字段。`build_kline_bar(row)` 与旧列映射由直读预计算结果路径继续使用。只被算子日线调用的 `build_index_sse_daily_kline_bar()` 由日线服务构造原 DTO 取代，移除旧定义。 |

`compose/` 新增 `__init__.py` 和下列模块。输入为已校验的结果列和当前 `row_index`，没有 I/O、算子调用、策略判断、按标的开关或跨业务导入。

| 模块与函数 | 输入、输出及转换 |
| --- | --- |
| `compose/ma.py` · `build_index_ma_factors(fields_by_calculation, row_index)` | 按清单中的七个 MA 参数取 `value[row_index]`，沿 `to_float()` 组 `IndexMovingAverageDto` 的 `ma5/ma10/ma20/ma30/ma60/ma90/ma250`。 |
| `compose/boll.py` · `build_index_boll_factors(fields, row_index)` | 依 `upper/middle/lower` 取值并转 `IndexBollDto`，列校验仍按原 `upper, middle, lower` 顺序。 |
| `compose/macd.py` · `build_index_macd_factors(fields, row_index)` | `dif → dif`、`dea → dea`、`hist → macd`，转 `IndexMacdDto`，不创建 `macd_bfq`。 |
| `compose/kdj.py` · `build_index_kdj_factors(fields, row_index)` | `k/d/j` 同名取值，转 `IndexKdjDto`。 |
| `compose/trend_channel.py` · `build_index_trend_channel_factors(fields, row_index)` | 从 `index_detail_field_mapper.py` 移入现有实现。`short_upper/short_lower/long_upper/long_lower` 对应 `shortUpper/shortLower/longUpper/longLower`，仍返回 `IndexTrendChannelFactorsDto`。 |
| `compose/common.py` · `build_index_common_factors(fields_by_calculation, row_index)` | 直接调用上面的四个公共指标函数，固定按 `ma`、`boll`、`macd`、`kdj` 返回原类型对象的字典，两种周期的业务服务各自选择 `IndexKlineFactorsDto` 或已有上证类型。趋势通道由日线服务单独调用。 |

旧行情行映射涉及 [测试 `test_index_detail_field_mapper.py`](../../tests/test_index_detail_field_mapper.py) 及 `index_detail_kline_query_service.py:281` 的预计算结果入口，保持这条真实消费者链。更新 [`test_index_trend_channel_mapping.py` 11–14、70–150、155–228 行](../../tests/test_index_trend_channel_mapping.py#L70) 的导入和断言目标。清单从新模块测试，`_split_daily_results()` 从日线服务测试，指标改用独立字面结果列测新 builder，含四轨的类型经日线服务或实际接口序列化核对。原 `build_kline_bar(row)` 的独立映射用例继续验证原接口字段。

## 5. 指数日线、周月线的逐段交接

### 5.1 日线

保留 [`src/biz/api/wealth/market/index_detail.py:query_kline_response()` 166–205 行](../../src/biz/api/wealth/market/index_detail.py#L166) 的鉴权和分支。当前 Prod 只有上证且 `limit <= 500` 进入算子，其他现有日线请求继续直读，原日线入口可接收至 2,000 的合同原样保留。本地已经接算子的日线保留现有 `runtime.config.max_output_rows` 检查。`index_detail_debug.py` 继续复用同一查询和 `debug_response.kline_response()` 投影。后端类型、OpenAPI 描述及前端 `useIndexDailyHistory.ts`、`indexDetailViewModelAdapter.ts` 均无需改动。

| [`index_detail_kline_query_service.py`](../../src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py) 原代码 | 修改和交接位置 |
| --- | --- |
| 45–79 行，旧常量同时供直读和算子路径使用 | 旧列 `_TECHNICAL_REQUIRED_FIELDS`、`_MA_FIELDS` 和直读 `_count_non_ma_missing()`、`_has_ma_missing_after_effective_history()` 留给旧路径。`_SSE_FACTOR_FIELDS` 由 §4 的算子字段清单取代。`SSE_DAILY_AUX_FIELDS` 仍由 Prod 查询使用。 |
| 175–289、429–508 行，直读预计算指标 | 只更新身份 helper 调用。保留北证 50 的来源选择、是否检查早期有效历史、落后判断、空页、未分页 meta 和 `build_kline_bar(row)`。这条路径的列名和缺项算法照旧。 |
| 291–321、343–349 行，本地取数及控制 | 保留查身份、下界、原 `datetime.now()`、显式端点与默认上下文分支、`calculate(query_end, lower, limit)` 和已读 calendar facts。存在 `result` 时立即调用 `IndexDailyKlineService.prepare_local_result(ts_code, calculated)`，保留在可能发生的后续 `resolve_local_context()` 前完成原检查。`result is None` 和起点前空窗继续空页。保留最后的 `check_active()`，然后调用日线 `assemble()`。 |
| 322–342 行，本地结果检查和辅助行情 | 移入 `prepare_local_result()`。依次校验 `facts.target_bars` 的交易日与 `result.times`、`range.count`，执行原 `_split_daily_results(..., include_price_and_nine_turn=True)`，从 `price` 列提取行情，先按原规则生成九转标记，再构造只有行情与辅助字段的行。`volume / 100`、`amount / 1000`、`pct_chg` 口径沿用。从 §4 的函数取得公共字段和缺项数，以 `calculated.selection.preceding_rows` 为有效历史基数，游标继续来自 `facts.previous_target_date`。 |
| 353–381、387–390、421–427 行，Prod 取数 | 保留 `_PROD_SOURCE_ORIGIN` 及 `resolve_sse_kline_context()` 选日期方式。取得 `(result, preceding_rows, target_ohlc)` 后先检查日期和 OHLC 长度，再调用一次原 `_read_sse_auxiliary()`。日期或 OHLC 不合法时仍在辅助 SQL 前失败。按原查询日期键序检查辅助行，再组原行情行，沿用 `vol`、`amount`、`pct_chg` 不再换算的现行行为。游标仍为满页时原窗口的上一交易日，并按原 `start_date` 截断。 |
| 382–386 行，Prod 结果检查 | 行情行建立后调用 `IndexDailyKlineService.prepare_prod_result(ts_code, rows, result, preceding_rows)`。按现行顺序校验 `range.count`，再 `_split_daily_results(..., include_price_and_nine_turn=False)`、公共字段校验和缺项统计。保留无日期时不调用算子或辅助 SQL。 |
| 95–114、142–159、392–419 行 | `_split_daily_results()` 和 `_build_nine_turn_markers()` 搬到 `index_daily_kline_service.py`。保留实例键、完整集合及算法版本校验，现有上证四轨无缺字段、等长、有限值检查，九转计数长度与范围互斥检查和原提示。由 `IndexDailyKlineService.assemble()` 取代 `_calculated_daily_response()`。 |

`index_daily_kline_service.py` 只依赖已有业务 schema、展示/状态规则、算子结果类型与本域 `compose/`。新增仅由该服务产生的 `IndexDailyCalculatedPage`，字段为行情 `rows`、`common_fields`、`trend_fields`、`nine_turn_markers` 和 `missing_count`。`prepare_local_result()` 和 `prepare_prod_result()` 只处理已读数据。`assemble(*, context, identity, page, start_date, limit, next_end, include_nine_turn)` 接收它和原查询上下文，`context` 沿用 `MarketPageContextLike`，空页直接传 `page=None`。查询负责传现行 `next_end`，本地从 `source_facts.previous_target_date` 按原有结果分支赋值；Prod 继续从原窗口算游标。空页的 `missing_count` 仍为 `None`，本地九转字段仍为 `[]`，Prod 仍无九转字段。

`assemble()` 沿原优先级确定 `expectedTradeDate` 和状态。每根使用 `build_index_kline_bar_fields()` 得到行情字段，再取 `compose/common.py` 的指标，收成普通 `IndexKlineBarDto`。上证本页有行时，按旧调用的求值顺序先调用 `compose/trend_channel.py` 构造四轨，再转换行情和公共指标，构造原 `IndexSseDailyKlineBarDto` 和 `IndexSseDailyKlineFactorsDto`。按本地/Prod 与上证/普通的原选择返回原 DTO 与 `missing_count`，保留 `IndexDetailSseKlineMetaDto` 的 `nextEndDate` 和 debug 投影基于响应类型的分支。检查无须把四轨或指标值写回行情行。

### 5.2 周线、月线

[`src/app/dependencies/index_period_technical_indicators.py` 22–79 行](../../src/app/dependencies/index_period_technical_indicators.py#L22) 继续原能力探测、App 请求时机、投影和 JSON 编码。阶段 2 只换清单来源，沿用阶段 1 的会话函数。现有 `latest_rows` 分支对应 `calculate_with_source()`，其他保留 `calculate()`。

| [`index_detail_period_kline_query_service.py`](../../src/biz/queries/wealth/market/index_detail/index_detail_period_kline_query_service.py) 原代码 | 修改和交接位置 |
| --- | --- |
| 23–36 行 | `IndexPeriodPage` 留在查询文件，去掉日线继承与导入。周月线装配查询所需的原依赖，另持有 `IndexPeriodKlineService`。新增服务不导入该查询或 `IndexPeriodPage`。 |
| 38–66 行 | 保留标的校验、DG/Prod 交易日历、查身份、未传截止日时的报价查询，以及 `expected` 计算。只改为直接调用 `require_index_kline_identity()`。 |
| 67–118 行 | DG 从 `calculate_recent()` 的 `source_facts` 组本页和历史游标，Prod 用 `index_period_page(..., limit=limit + 1)` 做当页选择。有需要才保留原 `index_period_boundary()` 检查，日期顺序、空窗、延迟、发布范围缺数据、`check_period_key()` 校验和超一根的裁剪全部照旧。 |
| 120–158 行 | 查询仅按原条件取得 `result`。若 `page.rows` 空，跳过 `calculate`。有行时，DG 复用 `page.result`，Prod 原样调用 `calculate(page.periods[0], page.cutoffs[-1])`。把明确的命名字段传给 `IndexPeriodKlineService.assemble()`。 |

`src/biz/services/wealth/market/index_detail/index_period_kline_service.py:IndexPeriodKlineService.assemble(*, ts_code, context, index_ref, auxiliary_rows, periods, cutoffs, end, expected, next_end, result, pct_scale, period, start_date, limit)` 接收原请求标的、本页已有值和临时结果。诊断继续使用查询参数 `ts_code`，回包继续使用已取到的 `index_ref`。`pct_scale` 由查询传现值，Prod `100`、DG `1`。函数按原顺序做以下工作。

1. 若有行情行，验证 `result.times == periods`、`result.source_as_of == cutoffs`、`result.range.count == len(auxiliary_rows)`。保留 `price` 的原实例选择方式和六列存在、长度检查、错误名称及顺序。
2. 按 `source_as_of` 和辅助行逐根拼价格和辅助数据，保持涨跌幅缩放、成交量 `/100`、成交额 `/1000`、原 `None` 和交易日。用 §4 的公共字段校验与缺项统计替换对旧日线函数的调用。有效历史数仍用 `result.statistics.source_rows - result.range.count`。
3. `IndexDetailStatusResolver.resolve()` 继续取 `expected` 和本页末日期，使用原空页与缺项数。使用 `build_index_kline_bar_fields()` 和 `compose/common.py` 得出行情及指标，构建原 `IndexKlineBarDto`、`IndexKlineFactorsDto`、`IndexDetailKlineResponseDto`、`IndexDetailSseKlineMetaDto`。固定原状态、分页和空页时 `missing_count=None`。已有不含日线趋势通道和九转的周月线合同照旧。

## 6. 实施顺序与验收

### 6.1 三个推进阶段

各阶段按顺序推进。上一阶段完成对应验收后，才进入下一阶段。三个阶段的验收证据分别见 §7、§8、§9。

阶段 1 的前后对照优先复用 `tests/app/technical_indicators/test_stock_daily_source_repair.py` 的本地股票日线、周月线，`tests/web/test_stock_daily_technical_indicator_api.py` 的股票 Prod 路由测试，`tests/app/technical_indicators/test_index_daily_kline_integration.py` 的本地指数日线，以及 `tests/app/technical_indicators/test_index_daily_prod_trend_channel.py` 和 `tests/web/test_wealth_index_detail_weekly_monthly_api.py` 的临时 PostgreSQL 测试。区分真实算子和测试替身，用现有 `.venv` 和 `PYTHONPATH=packages/technical_indicators/src:.` 运行。临时采样和原始回包放在 `/private/tmp`，在本文记录可复验的样本、对照摘要和限制。

| 阶段 | 工作范围 | 完成条件 |
| --- | --- | --- |
| **阶段 1　记录基线、迁移只读会话并完成股票改名** | 实施 §3 前，通过当前入口记录股票和指数代表样本的 JSON、请求参数、日期上下文、读取与计算次数。保留独立字面预期，用于核对 `hist → macd`、MA 周期、短历史空值、四轨和九转。随后把 `open_technical_indicator_read_session()` 迁到 App 技术指标运行目录并切换三个入口，完成股票组装函数改名及测试引用更新。 | 基线可重跑。股票日线和周月线定向回归通过，三个入口的只读会话、超时、取消和清理行为与基线一致，旧会话名和旧股票函数名无调用。 |
| **阶段 2　完成指数日线、周月线组装拆分** | 按 §4–§5，在同一次完整改动中迁移指数公共清单、校验、缺项统计、指数数值转换、各 `compose/` 函数及日线和周月线组装服务。切齐 App、查询与测试调用，移除算子路径写旧指标列的操作，以及周月线对日线查询的继承与导入。 | 指数日线与周月线使用新组装路径，现有直读预计算入口仍按原口径运行。定向测试覆盖算子原字段、旧预计算字段、正常短历史和错误分支。源码引用核查通过，再进入整体验收。 |
| **阶段 3　完整回归与独立对照审计** | 用阶段 1 的相同请求和样本，对照本地和 Prod 的股票、指数日线及周月线，覆盖普通与 debug、首批与续页、空页、故障和取消。另在改造前提交和当前提交上，用相同的隔离 PostgreSQL 样本跑股票 Prod 日、周、月 K 线的实际 API、只读会话、行情读取和算子。逐项核对 §6.2 的回包、数据源、读取与计算次数、权限、异常、性能及消费者。 | 回包和接口行为与基线一致，相关依赖按 §2 清零，原九转独立入口继续可用。记录所有验证证据和未通过项。发现差异则回到对应阶段修正并重验，全部通过后完成本次架构改造。 |

Prod 股票日线九转旧能力删除维持暂停。主要指数日线趋势通道扩展走后续功能方案。

### 6.2 回归与独立审计清单

验收使用实际路由、响应模型和独立样本。改造前后使用相同输入和日期上下文，每条反向用例须能触发原行为。

| 覆盖范围 | 必须对照的内容 |
| --- | --- |
| 股票 `tests/test_stock_kline_factor_mapping.py`、`tests/test_stock_daily_kline_service.py`、`tests/test_stock_period_kline_service.py`，以及 `tests/web/test_wealth_stock_detail_api.py` | 对照首屏、续页、普通 Prod 日线、周线和月线。根日期、OHLC、MA/BOLL/MACD/KDJ、九转、四轨、首屏报价、空值、分页、单位及错误不变。反例覆盖根数错位、日线结果校验失败及周月线不依赖四轨。 |
| 指数 `tests/app/technical_indicators/test_index_daily_kline_integration.py`、`tests/app/technical_indicators/test_index_daily_prod_trend_channel.py`、`tests/web/test_wealth_index_detail_dg_kline.py`、`tests/web/test_wealth_index_detail_weekly_monthly_api.py`、`tests/web/test_wealth_index_detail_api.py` | 对照 DG 上证与非上证日线、Prod 上证首批/续页、501 根仍走预计算分支以及 DG/Prod 周线与月线。普通和 debug 的字段、标记、单位、状态、缺项数、游标和日期相同。反例覆盖日期错位、字段缺失、上证四轨非法和本地九转非法；正常短历史、空页、数据延迟与已发布范围内缺失分别验证。沿用相同 `check_active` 和辅助查询时机，在可观察边界证明错误分类和读取次数一致。 |
| 指数指标级 `tests/test_index_trend_channel_mapping.py`、`tests/test_index_detail_field_mapper.py` | 分开核对算子原字段和预计算旧列两条路径。新增针对原规则的缺项统计回归，至少覆盖 MA 与 BOLL 各自临界根数前后、同一根多个字段为 `None`、MACD/KDJ 数值为零、正常无缺项和真正缺项。注册清单顺序和已存在的版本合同不变。 |
| App 只读会话 `tests/app/technical_indicators/test_stock_daily_integration.py:test_database_session_ownership_and_timeout`，加指数日线与周月线现有接口集成 | 确认正常只读、查询超时、驱动不匹配、取消、清理失败和主异常优先仍按原协议；用同一真实临时 PostgreSQL 路径核对分支、游标与异常。 |
| 依赖和消费者 | 通过引用检索、CodeGraph 与分层护栏验证：`index_stock_calculation_results` 和 `open_stock_daily_read_session` 无源码或测试调用，两个指数 App 入口无股票 App 导入，指数周月线查询与 App 入口无日线查询导入，`apply_calculated_kline_factors` 无实现及调用。检查 `compose/` 只有本域服务及数字/DTO 依赖。保留并校验原独立九转入口与 OpenAPI schema。前端历史消费回归用 `wealth/src/features/stock-detail/controller/useStockDailyHistory.test.tsx` 和 `wealth/src/features/index-detail/api/indexDailyHistoryRequests.test.tsx`；不修改页面。 |

**性能、失败与中断。** 沿用 [`src/foundation/config/settings.py` 的现行限制](../../src/foundation/config/settings.py#L85)，包括 `TECHNICAL_INDICATOR_MAX_INPUT_ROWS`、`TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS`、`TECHNICAL_INDICATOR_MAX_SOURCE_FILES`、`TECHNICAL_INDICATOR_REQUEST_MEMORY_BYTES`、`TECHNICAL_INDICATOR_TOTAL_TARGET_MS` 和 `TECHNICAL_INDICATOR_CLEANUP_RESERVE_MS`，同一环境使用相同配置值。保留 [`_execute()` 的工作期限和取消处理](../../src/app/runtime/technical_indicators/execution.py#L90)。对每个样本记录前后实际目标根数、源调用和读取次数、计算次数及耗时。同一成功请求中的算子次数、读取次数和读取范围与基线一致。正常空页、校验失败及取消也按基线对照，避免后移检查后增加一次 SQL 或文件读取。内存中保留每个指标结果元组的引用，减少逐根写旧字段的步骤。组装层不写数据库或文件，不加重试或持久化。请求失败仍走原错误与资源清理。验证被中断时只重新发对应原请求，记录重跑与独立回归花费。现阶段没有新增毫秒阈值，开发前后以同一环境的测量记录与原预算验收。

**验收环境。** 先用现有仓库环境运行定向测试，用生产者生成的临时 DG 文件与临时 PostgreSQL 验证实际读链，以及正常、空页和错误响应。隔离夹具与调用替身所覆盖的部分分别记录。通用 Web 回归在导入应用前设置 `APP_ENV=test`，通过 `GOLDENSHARE_ENV_FILE` 指向本任务的临时空配置文件，避免工作区 `.env` 选择本地路由。阶段 3 的股票 Prod 对账按确认范围使用同一份有界的隔离 PostgreSQL 样本，保留原始业务单位及字段。正式数据、线上配置和部署在本 LLD 执行范围之外。三个阶段的实际证据见 §7–§9。

**已完成的设计核对。** 单独运行现有缺项统计函数，与 §4 的直接读取算子列规则对照。使用 16 组历史根数，分别覆盖无缺项、25 个字段各自缺项及同根全部缺项，共 432 组构造输入，计数一致。该检查只验证设计公式，运行时取数、组装与接口回包按上表验收。

## 7. 阶段 1 实施与独立对照审计（2026-11-27）

阶段 1 已通过。迁移的只读会话实现位于 [read_session.py](../../src/app/runtime/technical_indicators/read_session.py)，股票新名称位于 [stock_kline_factor_mapper.py](../../src/biz/services/wealth/market/stock_detail/stock_kline_factor_mapper.py#L14)。审计以 `c58b840e4` 的源码为对照，再单独检查实际差异、测试、回包和读取记录。

- **引用与会话行为。** CodeGraph 确认新会话函数有四处调用，分布在三个原 App 入口，股票新函数仍只有两个业务调用方。逐文件对照确认，会话函数体和装饰器除改名外逐字符相同。四处调用与各自的会话开始、结束和异常边界除导入及改名外相同。股票三个映射及组装文件除函数名外相同。旧符号在 `src/`、`packages/` 和 `tests/` 的 Python 源码无引用。原故障注入断言保留，DG 参考数据超时用例的原夹具问题及修正见 §3。
- **回包基线。** 以 §6.1 的既有夹具使用同一批请求。改造前后各 14 个测试全部通过，各记录 48 个 K 线请求。股票为日线 13、周线 2、月线 2。指数为日线 9、周线 16、月线 6。状态码各为 40 个 200、1 个 404、7 个 500，含用例明确断言的错误响应。请求参数、状态、响应类型及 JSON 按请求逐条一致，只忽略随请求时间自然变化的 `pageContext.generatedAt`，实际交易日、游标、价格、指标、九转、四轨和 debug 诊断均参加对照。
- **读取与计算。** 每个请求的实际观测计数逐项一致。真实算子执行 38 次，另有 2 个股票 Prod 路由请求使用 SQLite 和算子替身，测试各断言一次计算请求。临时 PostgreSQL、DG 行情及参考数据按调用位置分别计数。对照包括 203 次 PostgreSQL SQLAlchemy 查询事件、57 次算子 PostgreSQL 查询调用、57 次 Lake 定位查询，以及 9 次股票周月线分区读取，前后各相同。调用位置可能有层级关系，各项不相加为物理读次数。逐请求耗时已记录，本批样本中位数为 70.8 → 65.6 毫秒，最大为 116.9 → 125.2 毫秒。这是隔离回归实测，验收仍使用 §6.2 的原工作期限。
- **定向回归。** 扩展回归 110 项通过，涵盖股票组装与接口、会话故障注入、取消和资源释放、DG 参考数据及分层护栏。其中另用隔离 PostgreSQL 对照搬迁前后的会话，验证事务开启只读、已设置正的 SQL 超时且退出后连接归还。隔离测试没有连接正式 Prod。

保留本地临时对照原始记录 `/private/tmp/goldenshare-kline-phase1.WCtgXR/before-timed.jsonl`、`/private/tmp/goldenshare-kline-phase1.WCtgXR/after-timed.jsonl`，以及同目录的 `kline_capture.py` 和 `compare_kline.py` 供阶段 3 使用。归一化结果的 SHA-256 为 `f5b9f49afe3c4c3f86ff99adcb174eea13fec62f906c91a4fa3de6f41b9fc2b0`。阶段 1 收尾时，阶段 2、3、主要指数趋势通道扩展和 Prod 股票九转旧能力清理均未启动。

## 8. 阶段 2 实施与独立对照审计（2026-11-27）

阶段 2 通过。独立核对以 `199d16e13` 为源码比较点，覆盖 App 入口、原查询、移出的校验和组装、回包与消费方。

- **依赖与职责。** 周月线 App 从 [指数请求清单](../../src/biz/services/wealth/market/index_detail/index_kline_calculations.py) 取清单。[周月线查询](../../src/biz/queries/wealth/market/index_detail/index_detail_period_kline_query_service.py) 已去掉日线继承与导入。计算结果分别交给 [日线组装服务](../../src/biz/services/wealth/market/index_detail/index_daily_kline_service.py) 和 [周月线组装服务](../../src/biz/services/wealth/market/index_detail/index_period_kline_service.py)。CodeGraph 和源码引用复核覆盖公共校验、缺项统计、指标入口和权重使用的数值转换。算子路径已移除 `apply_calculated_kline_factors()` 和旧列写入，MACD 的 `hist` 直接交给 `compose/macd.py`。预计算结果入口仍用原行情行组装。权重查询只更新 `to_float()` 的导入。
- **错误和取数时机。** 逐函数对照确认，日线预计算读取、辅助 SQL、周月线选页以及日线实例、版本、四轨和九转校验保留原行为。新增对照用例证明 Prod 日线日期或 OHLC 不匹配时在辅助 SQL 前失败，本地九转错误在后续上下文解析前失败。缺项统计使用实际旧函数与新实现，逐项对照 §6.2 的 432 组构造输入，结果一致，传入的行情行没有被写入指标字段。
- **相同输入对照。** 重跑 §7 的 14 个用例、48 个请求，逐条核对 HTTP 状态、业务 JSON、读取与计算计数，均一致。只归一化 `pageContext.generatedAt`。对照包括本地上证和非上证、Prod 上证与预计算分支、周月线及既有失败响应。股票 Prod 路由中有两个请求继续使用原 SQLite 和算子替身。48 个隔离请求中位数 66.0 毫秒、最大 133.4 毫秒，仍按现有工作期限验收。阶段 2 原始对照记录为 `/private/tmp/goldenshare-kline-phase2.TdCkU2/after-timed.jsonl`，归一化摘要与 §7 一致。
- **回归。** 126 项后端定向用例通过，覆盖字段映射、真实临时 DG 与 PostgreSQL、普通与 debug、缺页、取消、旧预计算结果、指数权重与独立九转接口。股票与指数的前端历史加载用例共 12 项通过。未触及正式环境。阶段 3 的完整对照审计待单独推进。

## 9. 阶段 3 完整回归与独立对照审计（2026-11-27）

阶段 3 通过。对照改造前 `c58b840e4` 和验收时 `56e0e99e1`，确认日、周、月 K 线的接口行为、取数和算子调用符合 §6.2。阶段 3 仅补充验收与文档记录。

### 9.1 股票 Prod 隔离 PostgreSQL 对照

两份源码分别启动临时 PostgreSQL，使用相同的测试输入和设置。通过 `GET /api/v1/wealth/market/stock-detail/kline` 调用实际 Prod 路由、应用只读会话、PostgreSQL 行情读取、算子和响应模型。测试固定市场时间，通过临时数据库写入合成行情。基础表用当前模型创建，停复牌查询视图按[正式迁移中的投影](../../alembic/versions/20260828_000155_make_suspend_d_raw_view.py)创建。数据库和算子均实际运行。外层使用测试应用装配，未连接线上网关、正式数据库或正式 DG。

样本窗口为 2026-07-01 至 2026-09-11，包含 52 根有效日 K、11 根周 K、3 根月 K，以及一次全天停牌和一次复权比例变化。每个周期各验首批、debug、较早截止日和空页。周线按回包游标续页，日线和月线按已有截止日期语义回查。另测非法周期、不存在的股票、缺复权因子和启用认证后的匿名请求。

| 首批 | 返回 K 线根数 | 算子实际处理的源行情行数 | 记录到的 SELECT/WITH 次数 | 算子调用 |
| --- | ---: | ---: | ---: | ---: |
| 日线 | 52 | 52 | 17 | 1 |
| 周线 | 2 | 11 | 5 | 1 |
| 月线 | 3 | 3 | 4 | 1 |

- **回包。** 16 个请求的 HTTP 状态、业务 JSON、SQL 与参数、算子调用和处理记录逐条一致，只将单次测量耗时排除出逐值比较。用独立预期核对日线价格、停牌、复权、日线基础指标、四轨、短历史空值及上升九转标记，并核对周月线日期、单位、已有分页语义和指标字段。异常分别保留 400、404、500、401；非法周期及未认证请求在 SQL 和算子执行前返回。
- **只读与耗时。** 每个周期首批均观察到应用会话的只读选项和算子连接的只读事务。每次请求结束连接均已归还。两次 16 请求的中位耗时为 53.0、60.7 毫秒，最大耗时为 1102.5、847.4 毫秒。数据仅反映隔离样本，按现有期限验收，不用于推算线上负载。便于检查处理批次，验收将转换批大小固定为 8 行，改造前后设置相同。

### 9.2 其余回归和独立审计

- **本地与指数基线。** 重放 §7 的 48 个请求，只归一化 `pageContext.generatedAt`，业务 JSON、SQL 和 DG 读取计数、算子执行计数与基线一致。其中包含 38 次实际算子执行，原有两个股票 Prod 替身请求由 §9.1 的实际 PostgreSQL 链路补足。前后中位耗时为 70.8、66.8 毫秒，最大为 116.9、117.6 毫秒。
- **失败、取消与资源释放。** 另在两份源码上各跑 14 项用例。40 个 HTTP 请求的回包和读取、计算计数一致，覆盖指数 DG/Prod 周线选页失败与取消、非法参数与权限、股票本地日线合同失败和同请求重跑。另用独立故障注入对照股票会话超时设置、驱动不匹配、清理失败、主异常优先与取消后释放。临时监听器首次与清理故障替身冲突，修正采集脚本后在两份源码上完整复跑通过。后端定向回归 259 项通过，耗时 48.85 秒。前端股票和指数历史加载 12 项通过。
- **依赖与正式消费者。** 用 CodeGraph `codegraph_explore` 核对股票、指数入口、只读会话、查询、组装和调用方，再用源码、回归与分层测试确认 §2 的交叉引用已清除。将原函数名归一后比较源码结构，确认只读会话函数和股票指标字段映射函数的实现、签名与装饰器均一致。指数日线和周月线各用自己的查询和组装服务，算子结果直接交给逐指标函数，原预计算日线分支仍用行情行组装。股票与指数的旧独立九转入口通过回归，股票 OpenAPI 和前端历史加载合同与基线一致。API、DTO、算子包及前端业务源码与本轮改造前比较点无提交差异。

对照记录保存在 `/private/tmp/goldenshare-kline-phase3.mVRJk3`。其中 `test_stock_prod_kline_compare.py`、`compare_stock.py`、`stock-before.json`、`stock-after.json` 对应 §9.1，去掉耗时后的 SHA-256 为 `618f7f4c3114d315b3c6b362325a5840c33d6d356927266f1ccef5e1ed4ecd03`。`stage3-common-isolated.jsonl` 与 §7 的摘要一致。`failure-replay-before.jsonl` 和 `failure-replay-after.jsonl` 的归一化 SHA-256 为 `1017df19bf9a055a63b1c60188e45c08030558d44ac31f4c54becf7bac852649`。源比较点可从 Git 重建，测试使用现有 `.venv` 和任务临时空配置文件。
