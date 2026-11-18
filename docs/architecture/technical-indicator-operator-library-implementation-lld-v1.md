# 技术指标算子库实施 LLD v1

**状态：只读代码审计完成，实施 LLD 待评审，未开始开发。** 本文回答“在现有代码上改哪里、以什么顺序改、怎么验收”；[整体详细设计与 UML](technical-indicator-operator-library-low-level-design-v1.md)负责说明目标、类和职责。原 [内核代码级 LLD](technical-indicator-kernel-low-level-design-v1.html)仍是现行预热、计算公式及已完成阶段的历史依据；两者不互相冒充现状。

## 1. 审计结论与开工边界

现有内核的参数校验、依赖、预热、同批共享、跨批状态和输出检查继续复用。通用读取当前只装配 DG，部分 DG 来源仍按请求的复权口径选列。股票和上证日线也各自在业务侧预读行情。旧的 `limit`、`before` 和 `instance_id` 进入了定位、输出和业务组装，迁移时一并更新。新指令的 `start/end` 所有周期统一带时区，分钟沿用现有转换逻辑。

**本次锁定的目标。** 本地内核只读 DG，Prod 内核只读生产 PostgreSQL；不授权跨环境回退。读取规定的不复权行情，需要复权时另读正式复权因子并计算，不直接读复权行情列或成品。分钟线按实际读到的有效 K 线计算，不检查缺少哪些分钟位置，不补 K 线；该检查留 TODO。无目标 K 线时返回错误「读取数据失败」，`detail` 为「数据缺失」。已有公式、默认参数、预热、真实起点和跨批规则不变。股票周月线复权、股票 90m/120m 合成和 ETF 不作为首版条件。

**已确认的验收顺序。** 首轮在 DG 和 Prod PostgreSQL 各用股票日线、指数 5 分钟跑通独立算子库的不复权读取和计算。其余已登记来源逐项核对后启用，普通指数日线须在上证迁移前通过。首轮在隔离环境验收，现有业务继续走现行入口。首轮通过后再迁移股票和上证日线，保留现有 HTTP 和翻页行为。

**什么时候可以开工。** 本文给出可审查的代码改动和隔离测试方案，验收范围确认不等于授权开发、切换或部署。只有对应来源的字段、单位、时间语义和可用范围经有界核验后，才可启用该来源；未核验不得按表名推断已可交付。不开生产任务、不改 DDL、不重新取源、不补数据。

## 2. 审计结果：现在哪里在用旧口径

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
- 保留“标准化 → 本批复权（若需）→ 与既有前置窗口合并 → 生成 `PriceBatch`”的顺序。复权因子按本次实际日期批量取，一批价格只转换一次，保留的是已转换的历史，不能每个指标重复转换。任何一批失败丢弃整次结果。股票周/月不改用预复权列、不把单日因子乘整周/月。
- `output/contracts.py`、`output/collector.py`、`output/result.py`、`output/encoding.py`。内部按 `calculation_index` 验证，沿用 `value_{i}_{j}` 和 `seq` 对齐。对外保留算子 ID、有效参数、版本和固定输出字段，移除旧结果标识、`RequestedRange.before/limit`。所有周期的 `requested.start/end` 序列化为带上海时区的时间。分钟的行情位置和读入、输出区间同样带时区，日周月对应字段为日期。周月逐根输出与 `times` 对齐的实际截止日期 `source_as_of`，其他周期为 `None`。在现有校验点核对有限值、声明的可空条件和时间对齐，保留 MA/BOLL 合法的预热空值。数值及错误回归通过后再切换合同版本。

## 4. 数据源适配、定位与复权

### 4.1 一份位置目录，不同来源各自投影

物理位置和 `freq` 值见 [整体设计 §3.1](technical-indicator-operator-library-low-level-design-v1.md#31-数据集位置与固定条件)。本表给实现所需的关键字段和定位依据，位置登记后按环境核验并启用。日、周、月启用前，补齐用于判断应有位置的适用事实来源，明确对应字段、单位和有效区间。

| 行情 | DG 生产者字段及类型 | PG 代码声明及读取方式 | 统一字段、单位和边界 |
|---|---|---|---|
| 股票日线 | `trade_date DATE`；原价 OHLC、量额 `DOUBLE` | `equity_daily_bar.trade_date DATE`，OHLC `NUMERIC(18,4)`、量额 `NUMERIC(20,4)` | 交易日为目标位置；原价元，量手、额千元按股票日线合同，不能套分钟单位 |
| 股票分钟 | `trade_date DATE`、`trade_time TIMESTAMP`、分区 `freq` 整数，原价/量额 `DOUBLE` | 分钟视图从底表投影；`trade_time` 无时区，`freq` 为 `SMALLINT`，OHLC `REAL`、量 `BIGINT`、额 `REAL` | `trade_time` 为目标位置；量股、额元，按生产者约定核验；只开放现有 1/5/15/30/60 分钟 |
| 股票周、月线 | `trade_date/end_date` 为 `YYYYMMDD` 字符串，原价 `DECIMAL(18,4)`、量额 `DECIMAL(20,4)` | `stk_period_bar_adj` 的 `trade_date/end_date` 为日期；`freq` 分别为 `'week'`/`'month'` | 从 `trade_date` 确定周期标签，`source_as_of = end_date`。实际截止为空或含义不符时不启用对应来源。只选无后缀原价列，量额单位核验后开放 |
| 指数日线 | `trade_date DATE`；点位、量额 `DOUBLE` | `index_daily_serving.trade_date DATE`；点位及量额为定点数 | 交易日为目标位置；点位、手、千元。只读普通指数日线，不回退至指数日线技术因子文件/视图 |
| 指数分钟 | 通用 Gold `trade_time TIMESTAMP`、`trade_date DATE`、`freq` 整数；点位及量额 `DOUBLE` | `index_minute_bar`，`freq` 例如 `'5min'`，无时区时间戳，点位、量额为双精度，未配置 PG 90/120 分钟 | K 线收盘时间为位置。不复权；需核对量额单位及 DG 规范化与 PG 原生时间位置的差异。不能拿主要指数专用文件兜底 |
| 指数周、月线 | `period_start_date DATE` 是自然周期首个开市日；`trade_date DATE` 是实际截至日；点位和量额为定点数 | 对应独立视图/表的 ORM 同样提供这两个日期列；数值量额精度与 DG 不完全相同 | 由 `period_start_date` 换算自然周期标签，`source_as_of = trade_date`。量手、额千元。假期后的首个开市日需归到对应的自然周期 |

依据：[DG 字段合同](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py)、[股票周/月底层字段](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/stock_weekly.py#L60)、[股票分钟 PG 模型](../../src/foundation/models/raw/raw_stk_mins.py#L11)、[指数分钟 PG 模型](../../src/foundation/models/raw/raw_index_mins.py#L11)、[股票周期表](../../src/foundation/models/core_serving/stk_period_bar_adj.py#L12)、[指数周期表](../../src/foundation/models/core_serving/index_weekly_serving.py#L12)。通过固定版本的实际生产者小样本或有界只读样本冻结映射后再构造测试夹具。对金额和成交量优先查对应生产者列说明及标准化是否改变单位；未证实不发布该字段的通用保证。

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

### 4.4 日线、常规股票分钟线复权是独立启用项

DG 候选是正式股票复权因子 `silver/quote/adj_factor`，现有定位在 `LakePriceLocator.describe()` 选取。PG 候选 [`core.equity_adj_factor`](../../src/foundation/models/core_serving/equity_adj_factor.py#L12) 的代码模型声明 `ts_code + trade_date` 主键和 `NUMERIC(20,8)` 因子。两端因子各自登记，在当前环境内按含除权日的有界样本验证日期、覆盖、基准和读权限。前复权用当前来源的最新可用因子作基准，后复权用最早可用因子。基准独立于请求区间，缺失、零值或非有限因子按合同报错。`none` 无须读因子。股票日线前复权是 D 阶段股票迁移条件，股票日线后复权和常规股票分钟复权各自核验后启用。

## 5. 现有业务迁移：保留产品接口，不保留两套内核

现有 HTTP 日期及翻页参数仍由业务处理。业务确定页首末交易日后，将两端显式转为对应日期的上海时间 `00:00`，内核按上海交易日期包含两端读取。合法空页走现行分支。

### 5.1 股票详情日线

- `stock_daily_kline_calculations.py` 改固定指令项。七组 MA、BOLL、MACD、KDJ 的参数和版本不变；产品需要价格时调用现有 `price` 算子并和指标共享本次复权行情，十项指标加价格一项共 11 项，默认上限 16 不是保证：部署上限低于所需项数时在切换前阻止，不偷偷调上限。
- `StockDailyKlineAppBackend.work()` 保留验证、对象信息和产品页边界处理；用与内核一致的正式来源查少量日期位置以确定产品页起止，仅把代码、区间和算子传给内核。移除 `page_prices`、`read_previous` 和 `StockDailyPriceSource` 的业务喂价。产品 `limit` 不进新内核。不要从日历算固定最近 N 个自然日，也不能把旧因子文件的有数日期直接当作新来源的页边界。
- [股票字段映射](../../src/biz/services/wealth/market/stock_detail/stock_detail_field_mapper.py#L95)当前显示的开高低收取 `*_qfq`；涨幅、昨收、换手率和量比等来自业务记录。迁移时开高低收取同一内核结果；辅助字段仍按各自既有业务含义读取，在业务层按交易日一一对应。尤其振幅、昨收与前复权口径使用方式先对照生产样本，不把不复权昨收随意改写。配置的实际来源用于调试来源字段，不冒用旧表名。
- `stock_daily_kline_service.py` 固定 DTO 映射改用 `(calculation_id, 有效参数)` 查找，MACD 的 `hist` 仍按产品字段映射。保持现有 URL、`forward`、产品分页和原 HTTP 错误包络。已按业务规则确定页窗口为空时可以走原页面空态、不调用内核；一旦有要计算的目标页，内核的「读取数据失败/数据缺失」必须让业务收到，不伪造成功页。

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

**关键测试落点：**

- 合同、配置和能力查询覆盖 `test_contracts.py`、`test_configuration.py`、`test_registry_dependencies.py`。用带时区时间跨上海日期的样本核对查询日期，覆盖所有周期拒绝无时区时间及纯日期、请求回显带偏移、分钟实际时间行为沿用、日周月实际行情日期保持日期类型。验证当前环境有位置但未启用时解析和能力查询一致。
- 定位、缺数据与算法覆盖 `test_source_contracts.py`、`test_locator_error_classification.py`、`test_request_reuse_correction.py`、`test_price_adjustment.py`。分钟中间跳点、完全无目标、已选记录漏交分别造独立样本。日线验证开市缺行与休市、全日停牌的区别。周、月各自启用前核对三类截止结果，断言返回的 `source_as_of` 逐根匹配。
- 输出、取消与产品覆盖 `test_d3_output_failures.py`、`test_output_encoding_correction.py`、`test_execution_cancellation.py`、`test_response_lifecycle.py`、`test_stock_daily_integration.py`、`test_index_daily_kline_integration.py`、`test_stock_daily_technical_indicator_api.py`。上证加入同批目标四价、量额合法空值、完全无行情的错误原因、合法空页回归。旧 D3 样本按已认可的隔离测试或对应授权范围运行。
- 真实核验只读指定证券、周期、少量日期，并区分目标与预热、字段解析和产品展示。PG 权限与查询耗时未验证时，mock 和模型不能证明可启用；DG 文件存在也不能证明任意历史日期齐备。

## 7. 预算、停止和重试

- **沿用既定上限，不重新定额。** 单次上游请求最多计算并返回 500 根**目标 K 线**；如果部署的 `max_output_rows` 更低，以更低值为准。新指令虽然不传 `limit`，但仍按实际目标根数执行此限制，超限报错，不截短、不自动拆单。额外预热不计入 500 根，仍受原来的输入行数上限。现行默认输入 1,500,000 行、每批 8,192 行、8,000 毫秒总目标（含 2,000 毫秒清理预留）及来源文件/列投影上限继续沿用。时间目标不是新 PG 路径的实测承诺，不把 500 写死到 PG 查询和 DG 定位。
- **目标预算与读入预算分别计量。** 目标上限为配置 `M`，最多见到 `M+1` 个逻辑目标位置即可证实超限（默认即 501），这是逻辑判定阈值，不宣称底层只读了 501 行。实际交付总量是目标 `T` 加根据现有算法选出的前置 `B`，多个算子共享；记录定位键数、实际源行情行、因子行、源文件、SQL 处理行及各阶段耗时，不把不同指标相加当新增 K 线。以 MA20、MA60 为例，历史充足时共用首根目标前 59 根，不能按 19+59 重读。
- **上证业务页的读入预算。** 目标四价来自已读行情，最多保留 `4 × T` 个数值。辅助字段批量按页日期查询，业务验收单独记录实际读取行数和耗时，计入当前请求的总时间。重复验收和重试均包含这段查询。
- **停止、清理、重新请求。** 取消/超时后停止领新批；PG 使用剩余工作时间约束查询，PG 游标和事务由输入会话清理，并计入原有“资源已归还”标记之前的时间，不能在响应或释放并发许可后继续查询。保留既有监控停止与错误优先规则。失败不发送部分成功，不写正式资源。没有持久 checkpoint；一次重试的预算是重新定位、回看、计算和清理的一次完整请求，不能从旧批继续。验收另外计入每来源的有界小样本和同一请求重复一次的观测开销；目前无新 PG 性能实测，不能承诺阈值通过。

## 8. 本轮核验证据

- 使用 CodeGraph `codegraph_explore` 跟踪内核入口、准备、定位、输入会话和输出，以及股票/上证应用入口和测试；再用精确引用搜索补查受影响的 JSON 编码、诊断脚本和前端。CodeGraph 中同名 `calculate` 的其他业务结果未列入本方案。
- 本轮先将受保护的 D3 用例与普通回归一同执行，这是测试范围选择不当：182 项通过，11 项被 [D3 受保护夹具](../../tests/foundation/technical_indicators/d3_support.py#L398)在准备阶段拦下，没有运行相应用例；未修改计划、未绕过守卫。另单独执行合同、注册表、执行控制、股票/上证日线集成和股票 API 的现行隔离回归，**87 项通过**。两次数量有重叠，不累计，不把任何结果表述成新设计已验收。
- 本轮没有重新查询 Prod 行情、没有重读 DG 全局行情、没有改变正式入口或文件。上一轮表/路径存在性核对仅作位置清单的依据。真实数据语义、PG 只读访问和取消、复权基准及页面迁移仍是明确的实施验收门禁。
