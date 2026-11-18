# 技术指标算子库实施 LLD v1

**阶段 C 已在独立工作树完成并通过复核，待 review。** 新指令通过公开 `calculate()` 返回目标行情和算子结果，DG 与 Prod 的首批不复权样本已通过完整调用验收。正式业务迁移在阶段 D。[整体详细设计与 UML](technical-indicator-operator-library-low-level-design-v1.md)说明目标、类和职责，[原内核代码级 LLD](technical-indicator-kernel-low-level-design-v1.html)保留现行预热、计算公式及历史验收证据。

## 1. 审计结论与开工边界

现有内核的参数校验、依赖、预热、同批共享、跨批状态和输出检查继续复用。通用读取当前只装配 DG，部分 DG 来源仍按请求的复权口径选列。股票和上证日线也各自在业务侧预读行情。旧的 `limit`、`before` 和 `instance_id` 进入了定位、输出和业务组装，迁移时一并更新。新指令的 `start/end` 所有周期统一带时区，分钟沿用现有转换逻辑。

**本次锁定的目标。** 本地内核只读 DG，Prod 内核只读生产 PostgreSQL；不授权跨环境回退。读取规定的不复权行情，需要复权时另读正式复权因子并计算，不直接读复权行情列或成品。分钟线按实际读到的有效 K 线计算，不检查缺少哪些分钟位置，不补 K 线；该检查留 TODO。无目标 K 线时返回错误「读取数据失败」，`detail` 为「数据缺失」。已有公式、默认参数、预热、真实起点和跨批规则不变。股票周月线复权、股票 90m/120m 合成和 ETF 不作为首版条件。

**已确认的验收顺序。** 首轮在 DG 和 Prod PostgreSQL 各用股票日线、指数 5 分钟跑通独立算子库的不复权读取和计算。其余已登记来源逐项核对后启用，普通指数日线须在上证迁移前通过。首轮在隔离环境验收，现有业务继续走现行入口。首轮通过后再迁移股票和上证日线，保留现有 HTTP 和翻页行为。

**启用条件。** 对应来源的字段、单位、时间语义和可用范围经有界核验后，才可启用该来源。正式切换和部署须按对应阶段处理。算子库读取正式行情，生产任务、建表和补数据均在本方案范围之外。

## 2. 实施前基线审计

本节保留阶段 A 开工前的代码和调用方基线。独立工作树已经完成的修改及阶段 C 当前断点见 §8。

| 环节 | 当前代码证据 | 实施影响 | 解决方案 |
|---|---|---|---|
| 配置及选择 | [KernelConfig 校验](../../packages/technical_indicators/src/goldenshare_technical_indicators/configuration/settings.py#L33)把除 Lake 根以外的字段都按整数校验；[Settings 复制](../../src/foundation/config/settings.py#L150)按配置字段名反射取值；[运行时装配](../../src/app/runtime/technical_indicators/composition.py#L31)默认构造 DG 读取对象 | 直接加位置映射会被当成整数或不存在的环境变量；继续默认装配 DG 会让生产选错来源 | **分类校验、显式装配。** 原运行字段沿用 Settings；`data_location`、`dataset_locations` 和 `market_datasets` 单独传入并校验。启动时只装配本地 DG 或生产 PG 的一种读取器；缺少明确部署配置则拒绝启用，不回退。见 §3.1。 |
| 指令和排序 | [请求合同](../../packages/technical_indicators/src/goldenshare_technical_indicators/contracts.py#L100)在旧入口要求分钟带时区和日周月传日期，`before/limit` 可参与目标筛选。[依赖展开](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/dependencies.py#L41)使用 `instance_id` 绑定节点 | 删除旧字段要同步迁移日期适配和输出对应关系，避免把不同参数的多组 MA 合成一组 | **用带时区的起止和内部请求下标。** 所有周期的起止归一到上海时间。日周月取数按归一后的日期。移除 `before/limit/instance_id`。相同算子和有效参数共享一个计算节点，按原请求顺序各返回一组。见 §3.1。 |
| 执行入口 | [service.calculate](../../packages/technical_indicators/src/goldenshare_technical_indicators/service.py#L85)已分准备和执行；[Web 执行](../../src/app/runtime/technical_indicators/execution.py#L26)在排队前调用服务私有准备，并在工作线程继续执行准备结果 | 若直接在排队前调用完整 `calculate`，会提前读行情和计算；工作线程再次解析则重复工作 | **解析一次，再执行。** `CalculationRequestParser.parse()` 只产出已校验的指令、算子计划和读取位置。直接调用由 `calculate()` 发起解析；Web 在排队前调用同一解析器，工作线程复用准备结果。两者进入同一计算流程，保留原有取消与清理。见 §3.1。 |
| 行情定位 | [Lake 合同](../../src/foundation/clients/local_lake/technical_indicator_contracts.py#L51)按复权切路径/列；[定位](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L378)给股票分钟拼 `ts_code` 子路径；[分区枚举](../../src/foundation/clients/local_lake/technical_indicator_price_source.py#L93)依赖年度或日期目录；[旧选择](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L291)用 `min(targets, request.limit)` 截目标值 | 普通股票分钟不是旧前复权的按证券/年份布局；只换路径或只删 `limit`，仍会读错目录或悄悄少算 | **按配置定位原价，按实际根数判断上限。** DG 读取器改用已选路径模板：股票分钟按 `freq/trade_date` 定位文件，在文件内筛证券；PG 用已选表或视图加固定筛选。只投影不复权列，复权另读同环境因子计算。统计范围内目标根数，超限就拒绝；通过后再按既有规则补读预热历史。见 §4。 |
| 读入与空区间 | [PriceInputSession.prepare](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L38)目标为空就标记耗尽，随后能构造空成功结果；[正常结束的数量核对](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/session.py#L99)只核对定位与流的交付计数 | 要区分没有目标行情、分钟中间没有某个时间点，以及读取流漏交已选记录 | **无行情与漏读分开处理。** 定位成功但没有目标 K 线时，在读价格流或复权因子前抛 `SourceReadError("读取数据失败", detail="数据缺失")`，不返回空结果、不切环境。分钟按实际记录计算，不检查没读到的时间点；但仍校验记录顺序、重复、字段和已选行的交付数量。I/O 故障保留实际原因。见 §3.2。 |
| 输出 | [收集器](../../packages/technical_indicators/src/goldenshare_technical_indicators/output/collector.py#L56)按 `instance_id` 验证请求项，但内部 SQL 列别名已经按顺序生成；[结果归一](../../packages/technical_indicators/src/goldenshare_technical_indicators/output/result.py#L21)按上海时间返回分钟值；[编码](../../packages/technical_indicators/src/goldenshare_technical_indicators/output/encoding.py#L26)显式写 `instance_id` | 即使改完输入，结果仍可能输出旧标识，或把结构正确但值非法的数据交给上游 | **收集、结果和编码一起改。** 收集器按内部下标和 `seq` 核对，保留原 SQL 列别名和对齐逻辑。对外只用算子 ID、有效参数和固定字段，分钟结果仍带上海时区，编码不写旧标识。交付前核对有限值和可空条件，保留按算子规则允许的空值。见 §3.2。 |
| 两条产品链 | [股票接线](../../src/app/dependencies/stock_daily_technical_indicators.py#L178)把已读复权行情与回看函数交给内核。[上证接线](../../src/app/dependencies/index_daily_technical_indicators.py#L28)也预读并依赖读取对象返回回看量。两条链路都用 `instance_id` 组装结果 | 单独切换计算会让页面组装失败，或让图上的 K 线与指标用价不同 | **业务定区间，内核统一取数和计算。** 业务提交带时区的区间，两条链路的图上四价都来自各自本次计算的同批行情。上证保留前置根数供状态判断。两条链路按算子 ID 和有效参数组装既有响应，对照验收后随新合同一起切换。见 §5。 |

**复用清单。** 原 `CalculationRegistry` / `CalculationDefinition` 的参数校验与依赖规则、`CalculationEngine`、`HistoryRequirement`、内置算子代码与 SQL、`PriceAdjustmentCalculation` 的公式、投影后的 DuckDB 执行器、现有请求控制和响应发送继续使用。[引擎合并需求](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/engine.py#L103)以及[原历史合并规则](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/history.py#L38)是实现依据。既有性能、测试和观察数值不自动算作新 PG 路径的证据。

## 3. 按文件实施：共享合同与执行接线

### 3.1 指令 → 解析结果

1. `packages/technical_indicators/…/contracts.py` 与包 `__init__.py`。请求改为七个必填字段，单项只含 `calculation_id` 和 `parameters`。将现有分钟的带时区 `datetime` 校验和 `Asia/Shanghai` 转换用于所有周期，拒绝日期值和无时区时间。归一后校验起止顺序，完整保留在请求对象中。移除对外 `CalculationInstance`、`before`、`limit`、`instance_id`。保留请求项数量限制，目标数量限制改在定位实际根数时执行。
2. 同包新增 `request_parser.py`。实现 `CalculationRequestParser.parse(request)`。用注册表校验 ID、周期、参数并准备算子计划。用 `KernelConfig.market_dataset_id()` 找数据集，核对请求口径属于 `enabled_adjustments(dataset_id)`，然后解析当前环境位置。未登记、无位置和未启用口径在访问行情前报不支持。返回 `_PreparedCalculation(request, plan, target)`。
3. `calculation/dependencies.py`、`calculation/engine.py`、`calculation/calculation.py`：在遍历请求项时以 0 开始的 `calculation_index` 替代自定义 ID；`CalculationPlan.instances`、批次产出和输出定义都同步改为内部整数索引。去重键仍由当前证券、周期、调整、ID、版本、有效参数及初始化规则组成，不加入内部下标。**同一算子同样参数传两次是两项输出、一个计算节点**；不能把 7 条 MA 仅按 `ma` 合并成一条。全部项验证成功才调用算子工厂。
4. `configuration/settings.py`、`src/foundation/config/settings.py`、`src/app/runtime/technical_indicators/composition.py`：在原 `KernelConfig` 加 `data_location`、`dataset_locations`、`market_datasets`；保留现有 17 个运行字段及其 Settings 来源。分类校验并复制为只读映射，不继续用“所有新增字段都按整数校验/绑定环境变量”。首次装配显式传可信环境和完整目录，用户请求不能改。现有 `APP_ENV` 的类默认值是 `dev`，不能把缺省值当作已确认本地；启用前核对部署实际值，显式本地 `dev/local` 装配 DG、已核实的生产值装配 PG，未知值或缺少可信部署声明则不能启用新内核。不从“Lake 根找不到”推断应该读 PG。正式 Lake 根校验留在 DG 读取端或部署校验，配置查找不探盘。PG 连接从现有可信配置单独装配，不把连接串存入位置目录。源码里的 `price_contract()` 停止决定物理路径，不能与新目录同时作为路由依据。
   行情记录按环境冻结 `enabled_adjustments`，默认空集合。每个环境核验通过后填入允许的 `none`、`qfq`、`hfq`。算子说明复用 `discovery/catalog.py` 的接口，由装配遍历 `market_datasets` 并读取同一 `enabled_adjustments(dataset_id)` 生成 `SourceCapability`。配置有位置但口径未启用、配置无位置的组合均不出现在支持列表里。日历、生命周期、停牌和复权因子的位置仍以内部数据集登记。
5. `service.py`。`calculate(request)` 先调用解析器。服务用计划生成输出说明，沿用执行器和引擎算历史，再生成 `ReadRequirement(target, ts_code, period, start, end, history, batch_rows, target_adjustment)`。分钟沿用归一后的上海时间，日周月在此处取上海当地日期。App 的 `execution.py` 排队前调用同一解析器，工作线程执行准备好的对象，继续使用原线程、取消、编码和资源归属逻辑。

### 3.2 读取 → 算子 → 输出

- `sources/contracts.py` 增加 `DatasetReadTarget`，修改 `ReadRequirement`，保持 `SourceLocator` 和批次接口。数据集目录只产出 DG 模板或 PG 表名与固定条件，不生成 SQL，也不携带实际请求日期。定位结果仍用 `PriceReadSelection` 表示目标首末、实际读取首末、输入及前置行数、是否到真实起点；PG 不填写伪造的路径/行组。
- `time_range.py` 的筛选使用 `ReadRequirement` 的边界。日线按交易日、分钟按时刻含两端，周/月按周期相交并执行 §4 的截止检查。日、周、月取数使用上海当地日期匹配物理日期字段。分钟沿用现有绑定方式，查无时区的源列时仅在绑定值上去掉上海时区，读回后继续使用原时间归一逻辑。数据表字段类型和产品日线日期 JSON 保持现有格式。
- `sources/session.py`：定位器合法返回 0 个目标位置时，在准备因子、打开价格流或创建输出收集器之前抛 `SourceReadError("读取数据失败", detail="数据缺失")`。用 `errors.py` 的可选 `detail` 保持已有一参调用有效。未配置来源/不支持组合保留不支持类；文件打开失败、PG 查询失败保留实际原因和异常链，不报 `detail="数据缺失"`。非分钟已确认实缺与合法无目标分开诊断，不把读失败退化为合法空。
- 保留 `_check_delivered_count()` 和实际记录的类型、边界、顺序、唯一性校验，文件或游标漏交已选记录仍按读取合同错误处理。日、周、月在 `PriceInputSession` 新增缺口校验，使用适配器的 `expected_positions()` 比较应有位置与实际位置，覆盖整个目标区间及所选预热范围。启用前逐环境核对适用交易日历、证券存续、全日停牌等事实来源及可用日期范围。分钟只检查实际记录，生成应有分钟位置留作 TODO。
- 保留“标准化 → 本批复权（若需）→ 与既有前置窗口合并 → 生成 `PriceBatch`”的顺序。读取模块标准化所需字段时按 §4.1 将成交量换算为股、成交额换算为元，每根只换算一次。复权因子按本次实际日期批量取，复权只影响 OHLC。多算子共用标准化后的批次，历史窗口保留已标准化、已按需复权的记录。任一批失败则丢弃整次结果。股票周/月采用原价字段，周/月复权另行设计。
- `output/contracts.py`、`output/collector.py`、`output/result.py`、`output/encoding.py`。内部按 `calculation_index` 验证，沿用 `value_{i}_{j}` 和 `seq` 对齐。按读取层选定的目标序号收集结果。对外保留算子 ID、有效参数、版本和固定输出字段，移除旧结果标识、`RequestedRange.before/limit`。所有周期的 `requested.start/end` 序列化为带上海时区的时间。分钟的行情位置和读入、输出区间同样带时区，日周月对应字段为日期。周月逐根输出与 `times` 对齐的实际截止日期 `source_as_of`，其他周期为 `None`。校验有限值、字段可空性和时间对齐，保留 MA／BOLL 合法的预热空值与源端合法的量额空值。具体接线、合同版本切换和验收见[阶段 C 的实施步骤](#阶段-c-的实施步骤)。
- `output/result.py` 生成结果时，`SeriesDescription.volume_unit` 固定为 `share`，`amount_unit` 固定为 `CNY`。返回的 `volume` 和 `amount` 使用读取层已标准化的值。业务需要其他单位时在调用方换算，例如现有接口约定为手、千元时，业务分别除以 100 和 1000。

## 4. 数据源适配、定位与复权

### 4.1 一份位置目录，不同来源各自投影

物理位置和 `freq` 值见 [整体设计 §3.1](technical-indicator-operator-library-low-level-design-v1.md#31-数据集位置与固定条件)。本表给实现所需的关键字段和定位依据，位置登记后按环境核验并启用。日、周、月启用前，补齐用于判断应有位置的适用事实来源，明确对应字段、单位和有效区间。

| 行情 | DG 生产者字段及类型 | PG 代码声明及读取方式 | 源端单位与定位边界 |
|---|---|---|---|
| 股票日线 | `trade_date DATE`；原价 OHLC、量额 `DOUBLE` | `equity_daily_bar.trade_date DATE`，OHLC `NUMERIC(18,4)`、量额 `NUMERIC(20,4)` | 交易日为目标位置；原价元，量手、额千元按股票日线合同，不能套分钟单位 |
| 股票分钟 | `trade_date DATE`、`trade_time TIMESTAMP`、分区 `freq` 整数，原价/量额 `DOUBLE` | 分钟视图从底表投影；`trade_time` 无时区，`freq` 为 `SMALLINT`，OHLC `REAL`、量 `BIGINT`、额 `REAL` | `trade_time` 为目标位置；量股、额元，按生产者约定核验；只开放现有 1/5/15/30/60 分钟 |
| 股票周、月线 | `trade_date/end_date` 为 `YYYYMMDD` 字符串，原价 `DECIMAL(18,4)`、量额 `DECIMAL(20,4)` | `stk_period_bar_adj` 的 `trade_date/end_date` 为日期；`freq` 分别为 `'week'`/`'month'` | 从 `trade_date` 确定周期标签，`source_as_of = end_date`。实际截止为空或含义不符时不启用对应来源。只选无后缀原价列，量额单位核验后开放 |
| 指数日线 | `trade_date DATE`；点位、量额 `DOUBLE` | `index_daily_serving.trade_date DATE`；点位及量额为定点数 | 交易日为目标位置；点位、手、千元。只读普通指数日线，不回退至指数日线技术因子文件/视图 |
| 指数分钟 | 通用 Gold `trade_time TIMESTAMP`、`trade_date DATE`、`freq` 整数；点位及量额 `DOUBLE` | `index_minute_bar`，`freq` 例如 `'5min'`，无时区时间戳，点位、量额为双精度，未配置 PG 90/120 分钟 | 不复权。已核实的 5 分钟量额单位见下表，其他组合单独核验。5 分钟使用 DG 的开盘业务 K 线规则，Prod 的 09:30 归并入 09:35 |
| 指数周、月线 | `period_start_date DATE` 是自然周期首个开市日；`trade_date DATE` 是实际截至日；点位和量额为定点数 | 对应独立视图/表的 ORM 同样提供这两个日期列；数值量额精度与 DG 不完全相同 | 由 `period_start_date` 换算自然周期标签，`source_as_of = trade_date`。量手、额千元。假期后的首个开市日需归到对应的自然周期 |

依据：[DG 字段合同](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py)、[股票周/月底层字段](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/stock_weekly.py#L60)、[股票分钟 PG 模型](../../src/foundation/models/raw/raw_stk_mins.py#L11)、[指数分钟 PG 模型](../../src/foundation/models/raw/raw_index_mins.py#L11)、[股票周期表](../../src/foundation/models/core_serving/stk_period_bar_adj.py#L12)、[指数周期表](../../src/foundation/models/core_serving/index_weekly_serving.py#L12)。用源合同和有界只读样本确定单位映射后再构造测试夹具。

**标准返回单位。** 算子库的成交量一律用**股**，成交额一律用**元**。按源端口径做以下换算，原行情表和文件沿用原值。业务方在收到标准结果后可自行换算。

| 源端量额口径 | 已核实的示例 | 读取时换算 |
|---|---|---|
| 手、千元 | 股票和指数日线 | 成交量 ×100，成交额 ×1000 |
| 手、元 | 上证综指 `000001.SH`、上证50 `000016.SH`、科创50 `000688.SH`、沪深300 `000300.SH`、中证500 `000905.SH` 的 5 分钟线 | 成交量 ×100，成交额原样 |
| 股、元 | 深证成指 `399001.SZ`、创业板指 `399006.SZ`、深证综指 `399106.SZ` 的 5 分钟线 | 两列原样 |

DG 与 Prod 的 5 分钟样本覆盖 2026-11-16 和 2026-11-17。前五只指数的分钟成交量合计与日线手数相等，后三只为日线手数的 100 倍。八只指数的分钟成交额合计与日线换算为元后的金额一致。其余指数和其他分钟周期逐项核实，按环境、数据集、周期及必要的证券代码确定原单位。只有原单位明确且完成换算核验的组合才启用对应量额输出。 [指数日线单位定义](../sources/tushare/指数专题/0095_指数日线行情.md#输出参数) · [Prod 指数分钟入库转换](../../src/foundation/ingestion/row_transforms.py#L1030)

### 4.2 DG：改现有读取器，不新增平行链

将 `src/foundation/clients/local_lake/technical_indicator_price_locator.py` 的 `describe()` 和 `technical_indicator_price_source.py` 的 `_partition_paths()` 改为实际消费已选读取位置。按 DG 合同区分固定文件、日/周/月分区和静态分钟 `freq`；不得沿用股票前复权按证券/年份查找，也不把指数周/月固定文件当空目录。保留 key 投影、行组检查、实际分区选择、表资源边界和跨文件凑批。固定文件按所需键和范围读取，不全量明细装入 Python。读取失败留原因，不向其他源重试。

`LakePriceLocator._select()` 计算目标区间内真实根数，后续历史定位以目标首根为基点。必须统计完整目标区间或提前证明确实超过上限；不能沿用旧的 `min(..., request.limit)` 截断。越界、重复、周期截至字段错误不能被过滤后假装成合法空。对缺历史是否到真实起点沿用当前规则；若没有达到真实起点且满足不了预热，失败而不是缩短算法。区间开始前的位置扫描按需要停止，超过原输入、文件、行组和时间限制即失败。

### 4.3 PG：加同协议适配器，不改生产表

在 Foundation 增加 PostgreSQL 实现（类和字段沿目标设计），接入现有可信会话工厂。每个请求开始第一个数据查询前建立可重复读、只读事务，本次价格、日期事实和复权因子沿用该事务。不能直接在 Foundation 导入 App 的股票只读函数；复用其“借会话、限定剩余截止、关闭”的行为，不复制第二套业务接线。每次执行设置不超过请求剩余工作时间的语句超时；结束、读错误、取消均关闭游标并结束事务。验证是否能及时中断实际阻塞查询，不能把只读等同于可取消；未验证不启用 PG 长区间。

PG 定位分三步，关系名和列由可信合同选择，所有值参数化：

~~~text
1. 目标位置：代码 + 周期固定条件 + 区间条件，最少投影时间和定位键。
   有界取 max_output_rows + 1 个位置；多出一条就报超限，不返回前 500 根。
2. 预热：以目标首根为上界向前读，按现有 HistoryRequirement 限定根数。
   按记录顺序计数，不按自然日或分钟数减时间；核实真实起点，不杜撰。
3. 实际读取：同一事务下用已定位边界，按时间正序流式投影必要列；
   对齐定位计数和交付计数，适配到 SourceBatch。只保留当前批与必要历史。
~~~

**周、月线截止。** DG 与 PG 都在目标定位阶段、统计目标根数之前执行同一规则。保留截止日已有的可用部分周期记录。相交且未结束的周期只有晚于请求截止日的版本时，沿用 `SourceUnsupportedError`，例如请求截至周二而只有周五版本。已结束周期沿用原规则。PG 在查询中保留识别晚版本的证据，避免仅过滤后报成数据缺失。验收同步覆盖可用部分周期、仅有晚版本和已结束周期。 [现有截止检查](../../packages/technical_indicators/src/goldenshare_technical_indicators/time_range.py#L27) · [现有回归](../../tests/foundation/technical_indicators/test_price_adjustment.py#L213)

分钟过滤保留 `trade_time` 原列范围。必要索引、分区裁剪和首尾定位通过有界样本及执行计划核验。分钟完整性检查留作 TODO。PG 仅允许访问配置有位置且已启用的周期。

**指数 5 分钟开盘。** 定位或实际读取需要当天 09:35 作为目标或预热时，PG 在相同事务内有界补读同证券、同交易日、同频率的 09:30。不单独返回或计数 09:30。归并后的 09:35 开盘价为竞价收盘价，最高、最低比较竞价价与 09:35 的对应值，收盘价取 09:35 收盘价，量额相加。缺少任一记录时，该首根业务 K 线不存在，其余有效 K 线继续参与计算。DG 已经归并，直接用 Gold 记录。有重复、字段非法或读取出错时沿用对应错误。 [DG 归并及完整窗口条件](../../lake_console/orchestrator/src/orchestrator/defs/io/cn_a_gold_minute_bars.py#L365)

### 4.4 日线、常规股票分钟线复权是独立启用项

DG 候选是正式股票复权因子 `silver/quote/adj_factor`，现有定位在 `LakePriceLocator.describe()` 选取。PG 候选 [`core.equity_adj_factor`](../../src/foundation/models/core_serving/equity_adj_factor.py#L12) 的代码模型声明 `ts_code + trade_date` 主键和 `NUMERIC(20,8)` 因子。两端因子各自登记，在当前环境内按含除权日的有界样本验证日期、覆盖、基准和读权限。前复权用当前来源的最新可用因子作基准，后复权用最早可用因子。基准独立于请求区间，缺失、零值或非有限因子按合同报错。`none` 无须读因子。股票日线前复权是 D 阶段股票迁移条件，股票日线后复权和常规股票分钟复权各自核验后启用。

## 5. 现有业务迁移：保留产品接口，不保留两套内核

现有 HTTP 日期及翻页参数仍由业务处理。业务确定页首末交易日后，将两端显式转为对应日期的上海时间 `00:00`，内核按上海交易日期包含两端读取。合法空页走现行分支。

### 5.1 股票详情日线

- `stock_daily_kline_calculations.py` 改固定指令项。七组 MA、BOLL、MACD、KDJ 的参数和版本不变；产品需要价格时调用现有 `price` 算子并和指标共享本次复权行情，十项指标加价格一项共 11 项，默认上限 16 不是保证：部署上限低于所需项数时在切换前阻止，不偷偷调上限。
- `StockDailyKlineAppBackend.work()` 保留验证、对象信息和产品页边界处理；用与内核一致的正式来源查少量日期位置以确定产品页起止，仅把代码、区间和算子传给内核。移除 `page_prices`、`read_previous` 和 `StockDailyPriceSource` 的业务喂价。产品 `limit` 不进新内核。不要从日历算固定最近 N 个自然日，也不能把旧因子文件的有数日期直接当作新来源的页边界。
- [股票字段映射](../../src/biz/services/wealth/market/stock_detail/stock_detail_field_mapper.py#L95)当前显示的开高低收取 `*_qfq`；涨幅、昨收、换手率和量比等来自业务记录。迁移时开高低收取同一内核结果；辅助字段仍按各自既有业务含义读取，在业务层按交易日一一对应。尤其振幅、昨收与前复权口径使用方式先对照生产样本，不把不复权昨收随意改写。配置的实际来源用于调试来源字段，不冒用旧表名。
- `stock_daily_kline_service.py` 固定 DTO 映射改用 `(calculation_id, 有效参数)` 查找，MACD 的 `hist` 仍按产品字段映射。采用 `price` 结果的量额时，由业务按现有接口单位换算。保持现有 URL、`forward`、产品分页和原 HTTP 错误包络。业务已确定页窗口为空时走原页面空态。有要计算的目标页时，业务收到内核的「读取数据失败/数据缺失」。

### 5.2 上证综指日线和已有通用调用

- 只迁移现有上证普通日线内核分支（`000001.SH`、`day`、产品 `limit <= 500`）。`run_index_daily_kline()` 与 `_build_sse_kline()` 保留交易日历页窗口、身份、页信息和 `nextEndDate`，有页窗口时向新内核提交指令。取消该分支的 `IndexDailyPriceSource(rows, read_previous, …)`。结果日期必须逐项匹配页窗口。分别核对普通指数日线真实起点和现有页面可浏览下界。其他查询继续按既有路由分支处理。 [现有路由条件](../../src/biz/api/wealth/market/index_detail.py#L172)
- **四价与指标。** 服务内部按需从已校验的 `PriceBatch` 投影目标行开高低收，以同一 `seq` 顺序交接。内部增加四价投影不改变原算子所需的前置根数。上证用这四列组装图上价格，`_apply_sse_factors()` 按算子 ID 与有效参数组装原有 16 个指标字段。内核的公开结果格式按 §3.2 执行。
- **量额、昨收和涨跌。** 业务按页日期从当前环境的同一普通指数日线数据集批量只读 `vol`、`amount`、`pre_close`、`change_amount`、`pct_chg`。其中 `change_amount → change`、`pct_chg → pct_change` 交给现有字段映射器，其余原名交接。按交易日与目标行情逐项对应，复用现有单位、合法空值和数据状态规则。维持量额的可空行为，四价交接独立于 `price` 算子的量额字段要求。 [DG 普通指数日线字段](../../lake_console/orchestrator/src/orchestrator/defs/assets/index_daily.py#L570) · [PG 普通指数日线字段](../../src/foundation/models/core_serving/index_daily_serving.py#L19) · [产品字段映射](../../src/biz/services/wealth/market/index_detail/index_detail_field_mapper.py#L113)
- **内部交接。** `TechnicalIndicatorService._calculate_result()` 和 `_calculate_library()` 返回 `(result, preceding_rows, target_ohlc)`。默认 `target_ohlc` 为 `None`。App 的执行接线在上证路径显式选择 `collect_target_ohlc`，业务通过 App 接线取得三项。收集限目标位置，每根四个数，顺序和数量与 `result.times` 对齐。前置根数来自同一次已核对的 `PriceReadSelection`，交给 `_count_sse_missing()` 保留原空值判断。公开 `calculate()`、`execute_library()` 及通用 HTTP 只交付第一项。
- **错误。** App 在通用指标错误分支之前处理 `SourceReadError`，业务可取得主信息及 `detail`。转换到上证 HTTP 时沿用现有 `ID_QUERY_FAILED` 和 `message`，在原消息中保留「读取数据失败」及原因「数据缺失」。实际 I/O 故障沿用真实原因。合法空页仍由业务在调用算子库前按页窗口判定。
- 在 [App execution.py](../../src/app/runtime/technical_indicators/execution.py#L177) 的 `execute_library/execute_http` 和两条业务路由/调试路由，统一消费新准备结果；诊断脚本 `technical_indicator_d2_acceptance.py`、`technical_indicator_resources.py` 及测试夹具同步迁移。前端重点核对 [上证翻页](../../wealth/src/features/index-detail/controller/useIndexDailyHistory.ts#L62) 与 [股票空态](../../wealth/src/pages/stock-detail/StockDetailPage.tsx#L134)，无需求不改页面代码。核对外部包消费者后再决定发版。清退旧 `StockDailyPriceSource`、`IndexDailyPriceSource` 前用引用和实际接线复查，不保留兼容调用。

**切换条件。** 用真实样本解释新旧来源导致的日期、复权基准、数值和辅助字段差异，两条链路均核对图上和指标使用同一批四价。新合同采用必填且带时区的起止，移除 `instance_id`、`before`、`limit`。受影响的正式调用方在 D 阶段同次迁移。生产部署在前复权和两个产品适配验收后另行评估。

## 6. 实施顺序及验收

第 A–C 阶段在隔离环境完成首轮验收，股票日线和指数 5 分钟在 DG、Prod PostgreSQL 各走通不复权取数和计算。其他来源逐项核验后启用，普通指数日线须在上证迁移前通过。首轮通过后进入 D，正式入口随所有受影响的调用方一起迁移。

| 步骤 | 做完什么 | 必须能证明什么 |
|---|---|---|
| A. 指令和配置 | 定义计算指令、独立解析器、`KernelConfig` 和取数指令。固定首批源字段、类型、单位及时间，核查数据源范围和现有调用方 | 所有周期的起止均带时区，配置冻结，按环境绑定位置和频率。解析器与算子能力查询共享启用配置，非法指令或未启用组合在访问行情前拒绝 |
| B. 不复权取数 | 改造 DG 读取器，完成 PG 有界只读读取和输入校验。落实新取数指令、目标根数上限和读取错误 | 股票日线、指数 5 分钟在两端各有真实小样本。日线验证应有位置及合法空档。分钟保留 09:35 与 09:45，缺 09:40 仍计算。完全无目标、重复、流漏交分别报错，失败只留在当前环境。恰好上限可算，多一根报错 |
| C. 独立算子库验收 | 接回现有算子和输出检查，用独立预期核对目标两端、预热、同参数共享和跨批状态。验证 PG 取消和两端资源归还 | 价格与物理样本一致，新旧算法用相同行情对照并符合原验收标准。输出只含目标位置、有效参数和标准结果字段，保留合法指标空值。中途失败整次报错，清理后归还资源 |
| D. 业务迁移 | 核验股票日线前复权因子和基准，验收普通指数日线，再迁两条产品接线、DTO 及其他旧合同调用方 | 两条链路按日核对图上四价与指标输入，以及辅助字段和合法空值。前复权在除权日前后对照，缺因子报错，`none` 不读因子。首屏、续页、短页、合法空页和读取失败回归通过后再评估发布 |

股票日线后复权和常规股票分钟复权各自核验后启用。股票周/月复权、股票 `90m/120m` 合成和 ETF 另行评审。

### 阶段 A 的实施边界

- **独立工作树。** 阶段 A–C 在 `codex/technical-indicator-stage-a` 的独立工作树开发和验收，基线为文档提交 `0c6101d8f`。原 `dev-interface` 工作区继续承载现行服务。A 验收新的指令链，B 接读取，C 接输出与完整计算，D 统一迁移正式调用方。正式服务切换在 D 验收后评估。各阶段交接剩余的旧合同引用。
- **取数指令验收到构造。** `CalculationRequestParser.parse()` 产出请求、算子计划和已配置位置。A 用显式传入的 `HistoryRequirement` 验证 `_build_read_requirement()` 生成取数指令，核对上海日期转换、位置、所需历史和批次配置。B 在现有引擎求出实际历史需求后调用同一构造函数。A 验收的请求链对行情文件、PostgreSQL、计算连接和临时表的访问次数均为零，调用失败直接返回错误，从同一输入重新执行即可，重跑与最终验收均使用同样的无读取测试。
- **阶段 A 的首批来源证据。** 2026-11-17 DG 核验 `600519.SH` 股票日线一根和 `000001.SH` 指数 5 分钟 09:35–09:45 三根。股票日期为 `DATE`，指数时间为无时区 `TIMESTAMP`，DG 频率为整数 `5`。阶段 A 的 Prod 证据限模型和迁移定义。后续 DG、Prod 量额样本及其适用范围见 §4.1。随代码提供的行情目录默认未启用，按阶段 B 的真实读取证据逐源启用。

**配置项审计**

| 配置 | 默认值与存放位置 | 作用、消费者和验证 |
|---|---|---|
| `data_location` | 无默认。A 由隔离装配显式传入 `dg` 或 `prod_pg`。正式部署绑定在 D 验证已有 `APP_ENV`，拒绝缺省值及未知值 | 一个 `KernelConfig` 固定一个环境。解析器、能力查询和位置解析共享该值。缺失或未知环境在构造及装配测试中失败 |
| `dataset_locations` | 无构造默认。行情物理目录随包版本管理，见 `configuration/datasets.py`。各环境的 `enabled_adjustments` 缺省为空，在同一位置记录中维护 | 启动装配一次，验证并冻结位置、固定条件及复权口径。解析器与能力查询均读取当前环境的同一条记录。A 核对未登记、无位置、未启用和有权读取的样本。实际部署由能力查询查看启用组合 |
| `market_datasets` | 无构造默认。与行情目录一同版本管理，由装配传入 | 证券类型和周期映射到目录标识。配置初始化时验证引用，供解析器和能力查询复用，测试覆盖股票及指数的有效映射和错误引用 |
| 原有 17 项运行配置 | 保留 `Settings` 的默认值、环境变量和 Lake 根设置 | 显式装配将三个非运行项与原值分别传入 `KernelConfig`。保留资源边界和数值检查，配置测试核对字段复制及 500 根硬上限 |

### 阶段 B 的实施步骤

**先做通用读取和股票不复权日线。** 从 A 的 `ReadRequirement` 接入现有 `PriceInputSession`，保留读取批次、预热和清理规则。DG 原读取器消费 `DatasetReadTarget`，Prod 在 Foundation 用同一读取接口和可信会话工厂装配。先用 `600519.SH` 的 2026-11-16 至 17 日两根原价记录，在 DG 和 Prod 分别核对时间、四价、原始量额及换算结果。正式业务接线及算法公式留在原阶段范围内。

| 股票日线辅助事实 | DG | Prod PostgreSQL | 用途 |
|---|---|---|---|
| A 股交易日历 | `silver/calendar/trade_calendar/full/part-000.parquet` | `core_serving.trade_calendar` | 按 SSE 日历及请求日期核对开市，字段为 `exchange/trade_date/is_open` |
| 股票存续 | `silver/basic/stock_lifecycle/full/part-000.parquet` | `core_serving.security_serving` | 按代码取 `list_date/delist_date`，沿用股票日线的上市日含界、退市日排除规则，退市字段为空表示没有已知的退市日期 |
| 股票每日停复牌 | `silver/quote/stock_suspend_daily/trade_date={trade_date}/part-000.parquet` | `core_serving.equity_suspend_d` | 按代码和日期取 `suspend_type/suspend_timing`。只以无冲突的全日停牌事实排除目标日期，日内停牌及复牌仍按日线合同判断 |

这三项作为内部数据集由现有 `dataset_locations` 解析，随包版本生效，沿用 A 的环境绑定。日历和存续、停牌事实要覆盖本次目标与必要预热范围。DG 已发布且为空的停复牌分区表示当日没有对应事实，文件读取失败须保留实际错误。由读取诊断区分应有记录缺失与合法停牌或休市。当前 DG 样本两日均为开市日，`600519.SH` 在这两天都处于存续且无对应停牌记录。Prod 已验证相关表的读权限，并取回两根相同原价日线。 [股票日线存续用法](../../lake_console/orchestrator/src/orchestrator/defs/assets/stock_daily.py#L533) · [Prod 全日停牌判定依据](../../src/biz/services/wealth/market/trading_assistant/suspension_facts.py#L54)

**再接入指数不复权 5 分钟。** 复用同一批次及错误处理接口，以 §4.3 形成业务 K 线后再执行区间、上限和预热判断。用 §4.1 已核实的量额口径。真实对照以 2026-11-17 的 `000001.SH` 和 `399001.SZ` 为样本，分别覆盖手和股的原始成交量。已观察到同日 Prod 原生 49 条、DG Gold 48 根。验收核对 09:35 四价与量额、整日根数和后续位置。验收用例覆盖请求从 09:35 起、截止 09:30、首根恰在预热区、缺 09:30 或 09:35、普通中间缺点和重复记录。

实施使用 DG 既有定位器和批次流，按配置的固定频率读取 Gold 日期分区。Prod 复用股票日线的事务、超时、取消及游标，按视图底表的 `(ts_code, freq, trade_time)` 主键查竞价记录。定位只用业务时间和竞价是否存在，行情批次投影必要的四价与量额，实际取到的竞价原始行情纳入源端行数。八只已核实量额的指数共用 §4.1 的映射，其他代码待核实后开放。本步的同源验收使用各源实际值，跨源逐项记录差额。前置核对发现深证成指 09:40 原始成交额在 DG 为 20,337,370,986.02 元，Prod 为 20,337,370,986.00 元，归并规则只作用于 09:35，两端各自保留原值。

**两步共用的验收。** 除上述真实样本外，用独立预期覆盖合法休市、全日停牌、开市应有却缺行、空目标、准确达到及超过目标上限、已选记录未交付、取消后归还资源。沿用 §7 预算。5 分钟归并每个被检查的 09:35 窗口最多增加一条 09:30 原生记录，计入源端读取量，根数上限和预热按形成的 K 线计量。中断及验收重跑从同一指令重新开始，计入完整日期事实、定位、读取与清理的开销。PG 实际执行计划、取消和用时在隔离验收实测。当前正式 Web 账号是否与审计账号一致留作业务部署验收，阶段 B 用已验证的 Prod 只读查询入口核对样本。

**关键测试落点：**

- 合同、配置和能力查询覆盖 `test_contracts.py`、`test_configuration.py`、`test_registry_dependencies.py`。用带时区时间跨上海日期的样本核对查询日期，覆盖所有周期拒绝无时区时间及纯日期、请求回显带偏移、分钟实际时间行为沿用、日周月实际行情日期保持日期类型。验证当前环境有位置但未启用时解析和能力查询一致。
- 定位、缺数据与算法覆盖 `test_source_contracts.py`、`test_locator_error_classification.py`、`test_request_reuse_correction.py`、`test_price_adjustment.py`。分钟中间跳点、完全无目标、已选记录漏交分别造独立样本。日线验证开市缺行与休市、全日停牌的区别。周、月各自启用前核对三类截止结果，断言返回的 `source_as_of` 逐根匹配。
- 量额验收用独立预期核对手/千元、手/元、股/元三类源单位，检查 `price` 数值和结果单位标识一致。用请求内多个算子及前置历史验证只换算一次。业务迁移用现有响应样本核对调用方换算后的接口值。
- 阶段 C 的输出、错误及取消测试见下节。阶段 D 迁移 `test_output_encoding_correction.py` 的应用入口部分及 `test_execution_cancellation.py`、`test_response_lifecycle.py` 等应用测试，运行股票及上证日线业务回归。上证验收覆盖同批目标四价、量额合法空值、无行情错误和合法空页。
- 真实核验只读指定证券、周期、少量日期，并区分目标与预热、字段解析和产品展示。PG 权限与查询耗时未验证时，mock 和模型不能证明可启用；DG 文件存在也不能证明任意历史日期齐备。

### 阶段 C 的实施步骤

**目标与范围。** 从阶段 B 的提交 `7de0326f7` 继续，在独立工作树接通公开 `TechnicalIndicatorService.calculate()` 与算子库的 JSON 编码。真实验收用阶段 B 已验证的股票日线与指数 5 分钟不复权来源。隔离装配分别启用 DG 或 Prod PostgreSQL，继续使用对应的数据集目录与可信的只读连接。正式业务入口、默认启用配置、HTTP、分页、算法公式、参数默认值和预热规则归各自原有范围。周、月输出格式用受控输入核对，真实来源按各自启用步骤验证。

1. **接通内部批次和目标行。** 在 `calculation/calculation.py` 的 `BatchCalculationOutputs`、`output/contracts.py` 的 `OutputInstanceDescription` 及 `errors.py` 的输出诊断使用从 0 开始的整数 `calculation_index`，与 `CalculationPlan.instances` 和 `CalculationEngine.output_for()` 对齐。服务把已校验的 `PriceReadSelection` 交给 `OutputCollector`。当目标有 `T` 根、前置有 `B` 根时，以 `B+1` 到 `B+T` 为闭区间，逐批取与新行序号区间的交集。在 `merge_batch.sql` 只按该交集和 `seq` 对齐合并，取消按原始请求时间二次过滤。目标根数经读取层按配置核定，收集器据此核对交付。用 `select_result.sql` 按序读取，核对目标根数、首末位置、时间递增唯一和字段数组的长度。按请求顺序组装，两项同参数 MA 共享计算节点并分别返回，两个不同参数的 MA 各返回自己的结果。
2. **落实输出合同。** 在 `contracts.py`、`output/result.py`、`output/encoding.py` 同步删除 `instance_id` 和 `requested.before/limit`。返回时间与序列化规则按 §3.2。在已有输出字段及结果组装的检查中拒绝非有限值、必有字段缺值、字段缺失及时间或序号不符，抛出 `OutputContractError`。在 `calculation/indicators/price.py` 声明开、高、低、收四项为必有的有限值，成交量、成交额允许来源合法空值。有值的量额直接采用读取层换算后的股、元；为空时保留 `None`，JSON 用 `null` 表示。按算子定义保留 MA／BOLL 的合法空值。整次无行情继续由读取层报 `SourceReadError("读取数据失败", detail="数据缺失")`。严格 JSON 编码保留，完整结果通过数值及错误回归后，将内核合同标识从 `3.0.0` 更新为 `4.0.0`，以标明请求及响应结构变化。各算子的算法版本沿用现值，安装包发版随阶段 D 核对。
3. **建立独立验收基线。** 同步更新 `test_contracts.py` 的结果形状断言，让 `test_execution_control.py`、`test_executor.py` 的夹具使用新 `KernelConfig` 签名后原样复跑行为断言。用普通隔离测试复用 `test_indicator_literals.py` 的独立字面预期及 `test_d3_output_failures.py` 的故障断言。旧 D3 的计划、报告和受保护执行记录保留。输出的最小正例覆盖单批与跨批、相同与不同参数的重复算子、合法空值、上海时区和日线从中午开始的场景。反例覆盖错误下标、缺列、非有限值、必有字段为空、少行、多行、重复、错位、越界及已收集一批后的失败或取消。失败只返回整次错误，关闭资源后由同一指令重新开始。验证失败后的下一次请求可正常执行，故障测试写入仅限临时资源。

**数值对照。** 在隔离测试中，以历史用例的三根收盘价 `10、12、11` 和四价相等的条件核对 `price`、MA、BOLL、MACD、KDJ，分别按每批一根和整批三根送入，核对合法空值及状态接续。指标公式沿 [原独立数值比较](../../tests/foundation/technical_indicators/d3_support.py#L380)的容差 `1e-8 + 1e-10 × abs(预期值)`，原有严格零值和合法空值断言继续保留。`price` 的四价和量额按各源实际值独立换算并核对，使用现有双精度数值表示。深证成指的源成交额差异按阶段 B 证据逐源保留。

**真实只读验收。** 下列请求在 DG 和 Prod 各执行一次并各复跑一次，使用公开 `calculate()` 和算子库编码。隔离配置每批一根，以覆盖输出跨批接续。逐项复核结果时间、有效参数、`price` 四价及量额、实际读取区间和不含预热的输出区间。真实样本和各源字段依据见 §8。

| 对象及请求区间（上海时间） | 算子 | 目标行及独立预期 |
|---|---|---|
| 贵州茅台 `600519.SH`，2026-11-16 12:00 至 2026-11-17 12:00 | `price`、MA(2) | 结果是 11-16、17 两个交易日期。11-13 仅预热。按收盘计算的 MA 为 1444.58、1455.80 元 |
| 上证综指 `000001.SH`，2026-11-17 09:40 至 09:45 | `price`、MA(2) | 结果是 09:40、09:45，带上海时区。09:35 仅预热。MA 为 3578.79955、3582.55725 点 |
| 深证成指 `399001.SZ`，2026-11-17 09:40 至 09:45 | `price`、MA(2) | 结果是 09:40、09:45，带上海时区。09:35 仅预热。MA 为 10626.32775、10649.99125 点 |

**预算、错误和退出条件。** 沿用 §7 的目标根数、请求时间、清理和读入预算。输出临时表最多保留本次的 `T` 根目标行情。若本次各项算子共声明 `F` 个返回字段，结果最多保留 `T × F` 个字段值，含重复请求项的输出，另有时间和合同说明。上表每环境每轮交付 6 根目标、3 根预热。初跑加复跑每环境预计交付 18 根逻辑行情。按阶段 B 的同日样本推算，实际行情读取预计为 DG 18 条、Prod 22 条，Prod 多读两只指数各一条竞价，每轮共两条。定位键、辅助事实、SQL 处理量和独立故障用例另计，记录其各自的实测。一次请求中途失败时，整次结果作废，输入、算子及输出表、游标、事务和监控清理完成后才返回错误。重试走完整链并单独记账。另验证完整调用中途取消和清理，Prod 复用阶段 B 的只读取消路径核对游标与连接归还。结果合同、公式对照、DG 与 Prod 的有界样本及失败清理全部通过后，才记录阶段 C 验收完成。

## 7. 预算、停止和重试

- **沿用既定上限，不重新定额。** 单次上游请求最多计算并返回 500 根**目标 K 线**；如果部署的 `max_output_rows` 更低，以更低值为准。新指令虽然不传 `limit`，但仍按实际目标根数执行此限制，超限报错，不截短、不自动拆单。额外预热不计入 500 根，仍受原来的输入行数上限。现行默认输入 1,500,000 行、每批 8,192 行、8,000 毫秒总目标（含 2,000 毫秒清理预留）及来源文件/列投影上限继续沿用。时间目标不是新 PG 路径的实测承诺，不把 500 写死到 PG 查询和 DG 定位。
- **目标预算与读入预算分别计量。** 目标上限为配置 `M`，最多见到 `M+1` 个逻辑目标位置即可证实超限（默认即 501），这是逻辑判定阈值，不宣称底层只读了 501 行。实际交付总量是目标 `T` 加根据现有算法选出的前置 `B`，多个算子共享；记录定位键数、实际源行情行、因子行、源文件、SQL 处理行及各阶段耗时，不把不同指标相加当新增 K 线。以 MA20、MA60 为例，历史充足时共用首根目标前 59 根，不能按 19+59 重读。
- **上证业务页的读入预算。** 目标四价来自已读行情，最多保留 `4 × T` 个数值。辅助字段批量按页日期查询，业务验收单独记录实际读取行数和耗时，计入当前请求的总时间。重复验收和重试均包含这段查询。
- **停止、清理、重新请求。** 取消/超时后停止领新批；PG 使用剩余工作时间约束查询，PG 游标和事务由输入会话清理，并计入原有“资源已归还”标记之前的时间，不能在响应或释放并发许可后继续查询。保留既有监控停止与错误优先规则。失败不发送部分成功，不写正式资源。没有持久 checkpoint；一次重试的预算是重新定位、回看、计算和清理的一次完整请求，不能从旧批继续。验收另外计入每来源的有界小样本和同一请求重复一次的观测开销。当前 PG 的实际用时覆盖 §8 中的有界样本。

## 8. 本轮核验证据

**阶段 A 独立复核。** 按计算指令、位置目录、启用配置、算子计划和取数指令分别对照实现。239 项限于合同、配置、算子依赖、解析、排队和架构的回归通过。另用独立字面预期逐项核对 40 个环境与数据集组合，其中 34 个位置与固定条件匹配，6 个按规定无位置并报错。用独立进程限制行情文件和连接访问，未出现调用。按 UTC 跨上海日期及两组有效参数验证日期转换、节点共享和目标取数对象。CodeGraph 用于梳理原服务、配置装配、算子依赖和正式入口，独立工作树的实际改动再按差异和源码复核。

阶段 A 的证据覆盖新指令链及无读取边界，并验证了 500 根的配置硬上限。阶段 B 开工审计的首批来源和量额核验见 §4.1；新版股票日线读取链的证据如下。

**阶段 B 第一步独立复核，通用读取和股票不复权日线。** 先直接按证券代码和日期读取 DG 的 Parquet 和 Prod PostgreSQL 的 `core_serving.equity_daily_bar`，再用同一计算指令走新版读取链。证券为贵州茅台 `600519.SH`，目标为 2026-11-16、17 日，MA(2) 引擎要求 11-13 一根预热，同时请求四价和量额。两端均在每批一根的情况下重复执行两次。上海日期、开高低收、量额与直接读取换算一致，批次保留的前一根量额也与首次读入一致。11-14、15 的交易日历为休市，上市日期为 2001-08-27，退市日期为空，三日均无该股停牌记录。辅助查询限对应范围的五条日历、一条存续记录及该股停复牌事实。

| 交易日 | 用途 | 开盘／最高／最低／收盘（元） | 原始成交量（手） | 原始成交额（千元） | 标准成交量（股） | 标准成交额（元） |
|---|---|---|---:|---:|---:|---:|
| 2026-11-13 | MA(2) 预热 | 1404.00／1437.69／1394.00／1435.26 | 41,779.84 | 5,954,834.070 | 4,177,984 | 5,954,834,070 |
| 2026-11-16 | 目标 | 1426.30／1454.93／1425.00／1453.90 | 39,967.00 | 5,767,305.714 | 3,996,700 | 5,767,305,714 |
| 2026-11-17 | 目标 | 1458.88／1461.60／1437.71／1457.70 | 35,116.45 | 5,094,594.655 | 3,511,645 | 5,094,594,655 |

表中标准量额按原值乘 100 和 1000 计算。读取会话使用原内核的双精度，个别换算值在双精度末位有误差。

- **DG。** 每次实际交付 3 根，读取 3 条定位键，接触 8 个 Parquet 文件。其中 3 个行情、3 个停复牌、1 个交易日历、1 个股票存续。统计文件总大小约 1.02 MB。
- **Prod。** 每次实际交付 3 根，定位读取 4 条键，其中包括一条用于判断是否到历史起点的记录。目标、预热、行情三个样本查询分别使用股票日线主键索引正向、反向、正向读取。实测请求在可重复读、只读事务运行。打开行情游标后取消同一连接上的一条有界只读语句，发出取消至释放资源约 189 毫秒，连接归还池后成功再次查询。
- **失败与重试。** 两端同样验证以 1 根为上限时 2 根立即报超限，休市区间无目标统一报「读取数据失败」且 `detail=数据缺失`，两种情况均未打开行情流。隔离回归覆盖准确达到上限、合法休市和全日停牌、日内停牌或冲突事实不能抵扣开市缺行、收尾缺行、错日期分区、重复日期、漏交和文件读取失败、取消后从起点重读。260 项相关回归通过。旧 Web 取消用例还引用阶段 A 已移除的 `CalculationInstance`，该用例当前无法收集；新版 PG 取消另用真实只读连接验证。
- **交接范围。** 本步验证两种环境的股票原价读取和向现有算子交付批次。正式目录启用、对上结果收集及 Web 接线分别随既定阶段推进。股票日线改动提交为 `3cba1ab21`。 [股票日线测试](../../tests/foundation/technical_indicators/test_stage_b_stock_daily.py) · [Prod 读取器](../../src/foundation/clients/technical_indicator_postgres.py)

**阶段 B 第二步独立复核，指数不复权 5 分钟线。** 直接读取 DG Gold 和 Prod PostgreSQL `core_serving.index_minute_bar` 的两只指数 2026-11-17 单日样本，再用新版读取链按每批最多 16 根读取，各重复一次。Prod 参考值从原始 09:30 和 09:35 两行单独计算，其余时间采用原值。DG 参考值来自已归并的文件。两端实际读入值逐根匹配各自来源，目标均从上海当地 09:35 到 15:00，共 48 根。

| 证券 | 09:35 开盘／最高／最低／收盘（点） | 09:35 成交量（股） | DG 成交额（元） | Prod 成交额（元） |
|---|---|---:|---:|---:|
| 上证综指 `000001.SH` | 3585.6653／3585.6653／3567.4077／3573.3274 | 4,923,322,500 | 70,360,501,946.70 | 70,360,501,946.70 |
| 深证成指 `399001.SZ` | 10605.106／10619.501／10567.036／10595.135 | 1,502,865,307 | 37,237,871,094.55 | 37,237,871,094.52 |

两只指数的时间、四价、成交量跨源逐根一致。按人民币分比较，上证综指的成交额 48 根一致，深证成指的成交额 9 根有差异，最大差额为 09:55 的 0.04 元。差异可由各自原始记录复算。

- **根数与预热。** 两端均验证 48 根上限可读，47 根上限报错，截止 09:30 返回数据缺失。单独请求 09:35 能拿到首根行情。从 09:40 请求 MA(2) 时读入 09:35 作一根预热。DG 隔离回归保留 09:35、09:45 之间的普通缺点并拒绝重复时间。Prod 查询隔离回归覆盖缺任一开盘记录，及其他证券和频率的记录无法充当缺失竞价。 [指数 5 分钟回归](../../tests/foundation/technical_indicators/test_stage_b_index_minutes.py)
- **用量和资源。** DG 每次交付 48 根，定位读取当日和最近历史分区的 96 条键，实际样本含清理用时 188–236 毫秒。Prod 实际读取 49 条原始行情形成 48 根，定位计数 50 条键，分别为 48 条业务时间键、1 条竞价键、1 条用于判断历史起点的键。实测目标查询用主键索引取得 48 条记录，竞价索引只执行一次并取得 1 条。在已打开指数行情游标的只读事务内取消一条有界查询，用约 78 毫秒释放资源，连接随后可复用。Prod 样本含清理用时 364–895 毫秒，另以贵州茅台前一步三根日线复跑通过。
- **验收范围。** 267 项读取、请求、预热、排队及架构相关回归通过。CodeGraph 用于追查服务入口、定位器和读取会话，再在独立工作树核对实际调用及测试。实际验收使用隔离配置固定来源，正式业务切换按 D 阶段推进。

**阶段 C 开工审计。** 在阶段 B 提交 `7de0326f7` 上复现了三处输出断点。公开 `calculate()` 在 [收集器构造](../../packages/technical_indicators/src/goldenshare_technical_indicators/output/collector.py#L64)访问已移除的 `request.limit`，引擎的批次产出又被 [字符串标识校验](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/calculation.py#L298)拒绝，原 [合并 SQL](../../packages/technical_indicators/src/goldenshare_technical_indicators/output/sql/merge_batch.sql#L6)的请求时间过滤会排掉用上海时间中午作为起点时已选的当日日线。隔离读取的三根行情在批次大小为 1 和 3 时，五个算子的批内数值与独立预期一致，包括成交量为空的用例。267 项相关回归通过。执行控制和执行器另有 21 项因旧配置夹具在准备阶段失败，部分旧输出用例因仍导入 `CalculationInstance` 无法收集。上述审计覆盖读取与批内计算，完整输出和新测试基线待阶段 C 验收。

**阶段 C 实施后独立复核。**

- **合同与公式。** 按目标行序号收集，核对最终序号、根数、时间首末和字段。请求起止序列化带上海时区，日线行情位置仍是日期，分钟行情位置带上海时区。周、月截止日期用受控输入验证。结果合同为 `4.0.0`。每批一根和一次整批的五个算子结果均与独立字面预期一致。重复 MA 输出保持请求顺序，相同参数复用计算节点。合法量额空值和 MA／BOLL 的预热空值原样输出。 [输出收集器](../../packages/technical_indicators/src/goldenshare_technical_indicators/output/collector.py) · [阶段 C 测试](../../tests/foundation/technical_indicators/test_stage_c_output.py)
- **真实读取与结果。** 按阶段 C 表中的三组请求在 DG、Prod 各执行两遍，合计 12 次完整计算并编码。每环境累计返回 12 根目标、另用 6 根预热。贵州茅台和两只指数的 MA(2) 均与表列独立预期一致。四价与标准化量额逐项对照各自源值，复跑除统计信息外结果一致。正常计算实际读取 DG 18 条、Prod 22 条，后者包含 4 条竞价记录。另用直接投影取得独立参考，DG 9 条、Prod 11 条。正常请求含清理用时为 DG 989–2672 毫秒、Prod 240–1014 毫秒。
- **错误及恢复。** 两端都在收集第一根目标后取消。DG 关闭了读取与临时资源，Prod 取消了同一只读事务中的一条有界语句并归还连接。取消到资源归还分别用时约 967 和 157 毫秒。随后同一指令从头执行，两端均恢复完整结果。取消与重试额外读取 DG 2＋3 条、Prod 3＋4 条。隔离反例覆盖错误下标、字段缺失或错类型、非有限值、必有字段为空、漏行、重复、错位和越界，均按整次错误处理。
- **回归边界。** 308 项相关回归通过，包括迁移夹具后的 21 项执行控制及执行器测试和 20 项阶段 C 测试。CodeGraph 用于追查批次、收集器、结果组装、编码和已有应用消费者，实际行为在独立工作树以源码和测试复核。历史 D3 受保护执行记录沿用原范围，业务入口、控制器及 HTTP 合同验收在 D 阶段。

**实施前基线审计。**

- 使用 CodeGraph `codegraph_explore` 跟踪内核入口、准备、定位、输入会话和输出，以及股票/上证应用入口和测试；再用精确引用搜索补查受影响的 JSON 编码、诊断脚本和前端。CodeGraph 中同名 `calculate` 的其他业务结果未列入本方案。
- 本轮先将受保护的 D3 用例与普通回归一同执行，这是测试范围选择不当：182 项通过，11 项被 [D3 受保护夹具](../../tests/foundation/technical_indicators/d3_support.py#L398)在准备阶段拦下，没有运行相应用例；未修改计划、未绕过守卫。另单独执行合同、注册表、执行控制、股票/上证日线集成和股票 API 的现行隔离回归，**87 项通过**。两次数量有重叠，不累计，不把任何结果表述成新设计已验收。
- 本轮没有重新查询 Prod 行情、没有重读 DG 全局行情、没有改变正式入口或文件。上一轮表/路径存在性核对仅作位置清单的依据。真实数据语义、PG 只读访问和取消、复权基准及页面迁移仍是明确的实施验收门禁。
