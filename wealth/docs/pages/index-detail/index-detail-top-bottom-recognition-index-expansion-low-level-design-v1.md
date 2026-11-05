# 财势乾坤r4指数扩展LLD v1

日期为2026-11-05（Asia/Shanghai）。**扩展第1—3步及第4大步前3项已完成。本机DG取数实现、限定回归、9次定向和74次原未验请求已通过。原Prod执行见§17，本机DG结果见§18。第4项页面验收由管理员执行。**

依据：[独立扩展方案](/Users/congming/github/goldenshare/docs/product/wealth-top-bottom-recognition-index-expansion-plan-v1.md)。本LLD细化扩大指数、新增30分钟及本机DG取数，涉及本次链路的来源和日期范围以本文为准。原[产品文档](/Users/congming/github/goldenshare/docs/product/wealth-top-bottom-recognition-product-v1.md)、[技术方案](index-detail-top-bottom-recognition-technical-design-v1.md)、[原LLD](index-detail-top-bottom-recognition-low-level-design-v1.md)继续作为已验收r4规则及原四周期事实依据。

## 1. 目标、范围和必须保留的行为

首页事实源仍为`majorIndices / CN_A`配置：`src/biz/services/wealth/config/definitions/major_indices.cn_a.v1.json`。本次支持上证指数（000001.SH）、深证成指（399001.SZ）、创业板指（399006.SZ）、科创50（000688.SH）、沪深300（000300.SH）、中证500（000905.SH）、中证1000（000852.SH）、中证A500（000510.SH）、上证50（000016.SH）。实际准入必须读原配置，不另建九码数组。

支持周期固定为`day / m30 / m60 / m90 / m120`，共9指数45种组合。上证原四周期保持并新增m30；其余8指数接入全部五周期。北证899050.BJ五周期全部排除，原首页10卡及普通行情保持。15分钟等其他周期不因通用行情支持而开放r4。

| 硬口径 | 编码落点 | 验证 |
|---|---|---|
| 不改r4判别、下一根求解、版本及hash | §4类型准入以外不改核心；§7预测复用 | T12—T19、T32、原金样本 |
| 名单同源，北证明确排除 | §3单次Universe准入，§8页面资格 | T01—T07、T27 |
| 实际代码贯穿取数、计算、缓存和响应 | §3—7必填参数 | T08—T11、T20—T23 |
| 五周期成套接入，不能只放行参数 | §4、§5、§7、§8 | T12—T19、T24—T26 |
| 本机DG日线/日历、Prod普通日线；r4从2010-01-04起 | §5、§9按环境装配，信号和预测共用日线范围 | T37—T42、§10、§11.3 |
| MACD取来源现有值 | §5真实日线/Gold；§10统计日期与根数 | T08—T10、T34/T35 |
| 分钟返回N，计算额外1000根 | §5窗口不变 | T15、T36 |
| 普通/debug事实一致，辅助按需 | §8保持动态模块及投影 | T24、T28—T30、§11 |
| 上证独立日线波段研究不扩大 | §8.5研究控制器 | T30 |
| 生产关闭、不改鉴权、不部署 | §9及原App装配 | T07、T31 |
| 保留预算，不开启暂缓优化 | §9 | T33、§11性能 |

初版方案/LLD及两索引已随99d876a32提交，文档收敛及根数统计口径已分别随f2c2d0f72、5339f0898提交。随后按管理员授权完成第1步来源统计、第2步Python及第3步前端实现、限定回归，结果见§13—14。第4大步的实际执行及首错停点见§17；配置、旧P5文档及其他工作区修改保持，不安装、不建分支、不部署。

## 2. 开发步骤、依赖、失败和交接

| 顺序 | 目标与实现范围 | 开始条件 | 完成/交接条件 |
|---|---|---|---|
| 0 文档及开工审计 | 本方案/LLD、消费者和合同检查 | 当前源码及管理员范围明确 | 方案/LLD一致；无未决业务口径；文档review完成 |
| 1 来源根数统计 | 原扩展日线/分钟计数已完成；DG日线覆盖聚合已完成 | 只读统计，源和指数范围明确 | 原记录见§13.1，DG证据及适用边界见§10 |
| 2 核心身份/周期及来源查询 | §3—7类型、DTO、来源、缓存、API及Python工具/直接调用测试成套迁移；不改TS客户端或mjs调用 | 第1步数量吻合、当前工作区无冲突 | 后端正反向及原上证金样本通过；原TS客户端与mjs仍相互匹配，前端新范围尚不开放 |
| 3 前端消费 | §8页面身份、五周期识别/五行预判/debug、研究边界；TS客户端、mjs及其调用/测试同批迁移 | 第2步完整，公开字段/异常已冻结 | 类型、限定交互及消费测试通过；mjs调用新签名正确，不是只修改名单 |
| 4 整体回归和真实验收 | Codex按§2.1完成内部第1—3项；管理员执行第4项真实页面验收 | 第2—3步独立审计符合LLD；内部依赖按§2.1 | Codex交前三项结果及待验页面；管理员明确页面通过后再对账整体验收，不自动部署 |

第2步内部先扩核心类型、DTO及30分钟端点，再改来源和查询/预测传递，最后API、Python工具和全部Python调用者同时迁移；不得暂时给产品方法保留上证默认参数维持旧签名。第2步保持TS客户端与mjs现有参数形状：HTTP仍接受原上证四周期请求，响应字段集合/版本不变，原前端可以继续使用。第3步再将TS客户端、Hook/decoder/fixture、mjs及其集成测试同时迁移，最后启用页面新范围。不能在第2步先让mjs给旧client传code首参，也不能为迁mjs提前扩大第2步到前端改造。中间提交若需进行，必须明确尚未可验收，不发布中间混配版本。

失败先停止该单元，不自动重试、切源、补数据、放宽阈值或清缓存掩盖。代码/规则与本文冲突时先汇报并修正文档，不临时加兼容路径。源码保护通过人工规则/差异审计，不读源码SHA作运行校验。无业务写入、迁移或磁盘快照；真实输入或实现改变导致证据不再适用时，只补受影响单元。

续跑按完整单元处理：日线1条计数SELECT是一个单元，分钟两类计数共同为另一个单元，每个指数/周期2或4次规定API请求及比较为一个组合单元。完整结果保留，中断部分仅诊断，原因解决并获准后重做未完成单元；不拼接不同次分钟两类计数，也不换新缓存只补debug称热路径，不新增恢复系统。

本次扩展r4标的及周期，并调整§5所列本机取数；既有普通分钟Hook、缓存和请求状态模型继续沿用，不为“上游两个接口同时违反合同”等未观察到的问题增加必改项或成组防御测试。API临时调用复用现有观察方法，记录实际阶段进展；本轮不增加整组总等待阈值，产品自身截止及测试/驱动原有超时保持，不另建分阶段信号管理、进程通信或通用监督框架。

已完成来源统计的时限及实耗按§13.1保留。第4大步第3项每个组合由父调用顺序启动一个自有Python子进程，组合内共用App和缓存完成规定API请求；组合结束清理后才进下一组合，不嵌套Node、浏览器或服务子进程。实际执行组合的准备/装配/清理成本按实记录，不冒充跨组合热缓存验证。API按§11.3.5观察实际阶段和异常无进展情况，不设置额外整组等待门槛；不借用旧工具的进程监督逻辑。自动测试仍可运行现有测试中原本就有的Node客户端夹具，不将这类夹具误当新增来源核验子进程。真实页面由管理员按§11.4验收，不纳入Codex的API单元。

所有测试/查询/临时调用的过程文件在`/private/tmp`本任务目录，禁止写入工程或reports。正式结论写回本方案/LLD。自动测试的单元、成本组成和失败退出按§11.2，不设置缺乏依据的统一总时限；已完成来源单元的历史时限不自动用于新单元。产品现有限额及API第3项执行前条件见§9/11.3，中断后重做、退出、记录和最后核验的成本均须列明。

### 2.1 第4大步内部执行顺序和责任

以下第1—4项是第4大步内部工作。原执行记录及首错见§17；当前执行顺序以下表为准。

| 内部顺序 | 负责人及范围 | 开始条件 | 完成/交接条件 |
|---|---|---|---|
| 第1项执行准备 | Codex核源码、DG读取合同、环境、预算和复用证据 | 扩展第2—3步已交付，本文取数方案及范围明确 | 核准§5/6/9编码落点和T37—T42，准备阶段不提前发真实请求 |
| 第2项取数调整及回归 | Codex实现§5/6/9，执行T37—T42所涉后端回归；复用未受影响的前端回归、构建及既有测试 | 第1项通过 | 相关实现和回归通过，复用范围明确；失败即停，通过后才进入第3项 |
| 第3项真实API/debug/性能核验 | Codex按§11.3先定向补验DG，再完成原未验组合 | 第2项通过；临时程序静态复核，确认实际DG装配和只读边界 | 必需请求、规定对照及原预算通过后交页面清单；复用、失败、未执行和不可比较各自记录 |
| 第4项真实页面验收 | 管理员按§11.4实际看页面及交互 | 收到前三项结果和未完成/限制清单 | 管理员明确通过后，Codex再记录反馈、对账§12并收尾；不代替管理员判定页面通过 |

第1项只完成设计、环境和证据核对，不把写文档等同于已运行前三项。管理员决定本轮暂不设置额外整组总等待阈值，实际卡住时先判断定位、停止后续并汇报；不再等待新增秒数，也不改变产品4秒/400ms/5秒及既有测试/驱动超时。

## 3. 指数准入、API和参数传递

### 3.1 唯一产品准入位置

在现`src/biz/queries/wealth/market/index_detail_xxm/query_service.py`增加模块内函数`require_xxm_code(ts_code: str) -> str`，不另建名单、配置项或通用准入框架。步骤固定：

1. 非字符串拒绝；调用`IndexDetailUniverseService.normalize_ts_code`取得规范六位代码加SH/SZ/BJ后缀。
2. 同一service调用`require_supported(code)`一次，读取与page-init/kline相同的正式配置。失败不得用首页私有占位名单继续。
3. 对`899050.BJ`按本需求排除。返回其余已准入规范代码。
4. 显式转换下面三种Universe异常，**它们中的Request/NotFound继承ValueError，不能漏进原来源合同错误分支。**

| 条件 | query抛出 | HTTP |
|---|---|---|
| 类型/格式错误、非法周期/参数 | `XXM_REQUEST_INVALID` | 400 |
| 名单外或北证 | `XXM_NOT_SUPPORTED` | 404 |
| `IndexDetailQueryError`：配置缺失、无效或类型不正确 | `XXM_QUERY_FAILED` | 500 |
| 来源字段/缺口/结果身份不符 | `XXM_SOURCE_CONTRACT_INVALID` | 原500 |
| 超时、内存/行数/响应超限 | `XXM_BUDGET_EXCEEDED` | 原503 |

forecast仍只在路由将`XXM_`前缀转为`XXMF_`，不新增另一套query异常或异常码。沿[异常注册表](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)现有语义，不改鉴权401/403。

准入只由公共`load_entry`调用一次。该方法先启动原4秒计时，准入前后检查剩余时间；准入完成后才检查分钟来源是否配置、执行context/calendar SQL、访问缓存、参加共享加载、发现分区或读内容。直接Python query也必须走这里。北证不能因未配置分钟reader而先报来源错误。

query/reader构造目前只解析Lake路径及创建空状态，可能发生`Path.resolve`路径元信息访问，但不会读日历、分区、footer/Parquet或打开DuckDB。保留构造，不为此增加延迟reader层；“准入前不读源”指上述业务来源访问。

### 3.2 三条现有接口

前缀均为`/api/v1/wealth/market/index-detail/`，仍用现本地App注册。

| GET路径 | 参数变化 | 保持 |
|---|---|---|
| `xxm-signals` | 必填tsCode交query；period仍只day | 识别原trim/upper、日期/limit/debug规则 |
| `minute-xxm-signals` | freq允许30/60/90/120；tsCode交query | 原日期、limit、分钟能力和debug |
| `xxm-key-point-forecast` | period允许五周期；tsCode交query | 原严格规范代码格式，asOf/debug、无limit |

signals的`parse_parameters`只移除“仅上证”判断，返回原dict并加`ts_code=code`；forecast的同名函数返回`(code, period, as_of, debug)`，路由解包后明确传code。禁止仍只校验而不传值。未知/重复参数、日期格式和debug缺省0/仅0或1仍按现规则拒绝。未传日线period仍day；分钟freq和预测period仍必填，不新增默认周期。

forecast分钟asOf继续为标准端点的ISO文本及`+08:00`，m30按§5八端点校验；日线仍YYYY-MM-DD。分钟环境关闭时沿原404不支持行为，生产根本不注册r4路由。

### 3.3 必填签名和唯一参数流

下面为目标签名；未列出的原参数及返回值保持。新增`ts_code`均为必填关键字，无默认值或旧签名重载。

```python
IndexDetailXxmQueryService.build(session, *, ts_code, period,
    start_date, end_date, limit, debug=False, now=None)
IndexDetailXxmQueryService.load_entry(session, *, ts_code, period,
    now=None, window_rows=None, requested_end=None)
IndexDetailXxmQueryService._load_series(session, *, ts_code, key, period,
    now, business_date, remaining, window_rows=None, requested_end=None, context=None)
IndexDetailXxmQueryService._response(entry, *, ts_code, period,
    expected, start_date, limit, check)
read_daily(session, *, ts_code, completed, check)
minute_request(freq, window, *, ts_code)
read_minutes(reader, *, ts_code, freq, window, deadline)
IndexDetailXxmForecastQueryService.build(session, *, ts_code, period,
    as_of=None, debug=False, now=None)
_assemble(*, ts_code, period, through, as_of, data_status, ordinary, direction,
    source_id, calendar_id, result, prepared, check)
```

API→build→load_entry→require_xxm_code→_load_series→read_daily或minute_request/read_minutes→`XxmCalculator(ts_code=code, period=period, source_identity=origin)`。load_entry准入后，向下仅传规范code；signals和forecast的build均在with返回后从`entry.calculator.ts_code`取得已准入code，交_response或预测缓存/装配。直接build传入空白/小写时不能把未规范原文继续交给严格装配校验。装配处再次做廉价身份绑定，不重新读配置。

`plan_minute_window / normalize_minute_end / expected_through / calendar_dates / future_calendar`没有标的业务差异，不加code参数或重复查名单。九码共用SSE日历，不能因深市代码要求另取SZSE日历。

## 4. 核心、DTO、编号和恢复

### 4.1 只扩身份和周期准入

| 文件/符号 | 确切变更 |
|---|---|
| services/.../`index_detail_xxm/types.py` | `XxmPeriod`增加m30；`XxmBar.validate`的分钟分支增加m30，保留有限数、正价格、完成根及+08:00规则 |
| 同目录`calculator.py::__init__` | 将只允许上证改为规范代码格式校验；周期集合加m30，step及业务方法不变 |
| queries/.../`query_service.py::_PERIODS` | 扩为五周期；不顺带开放通用行情全部七个频率 |
| schemas/.../`index_detail_xxm.py` | 内部/普通响应tsCode从上证Literal改严格规范代码字符串；period加m30；debug继承同一合同 |
| schemas/.../`index_detail_xxm_forecast.py` | tsCode复用识别schema的规范代码类型，period扩五周期；普通/debug继承及完整事实验证保留 |
| `forecast_expression.comparison_envelope`、`forecast_text.make_display` | 内部允许m30，沿原分钟运算/文案；不能遗漏内部四周期限制 |

规范代码类型使用字符串严格类型及全匹配六位数字、点号、SH/SZ/BJ；不得允许DTO自动改代码或把名单校验放进DTO。核心/DTO不得读配置。可在识别schema定义可复用的`XxmTsCode`类型供预测schema引用；不新增跨层依赖。现生命周期校验用day/分钟来区分日期格式，不因其中写了m60就改写全部结构跟踪逻辑。

**保留核心构造器原上证默认供已有直接数学样本使用；全部产品构造路径必须显式传code。**本需求不机械改写所有独立研究构造器，也不扩大旧研究范围。产品方法签名仍按§3.3无默认，防止漏传悄悄算上证。

### 4.2 保留规则身份

`MAIN_SPEC`、`FORECAST_SPEC`无标的/支持周期名单字段，不修改这两个Spec、hash、算法版本、EMA初始化、1%门槛、原参照选择/失效/同根切换、零柱、有色根数、结构有限跟踪和同根显隐。现r4业务金样本逐项回归，不重新解释旧标签。

原事件/结构ID及`forecastId`已有code/period；直接复用。`source_identity` origin、逐根指纹、空指纹及`sourceInputId`算法不变，不擅加code改变上证指纹。不同代码的数值完全相同时，内容指纹可以相同，但状态、ID及缓存必须仍分开。

`snapshot/restore`、`SeriesEntry.calculator_at`及预测clone已有code/period/Spec/source身份绑定。前两者新增m30合法路径后复用：同码同周期分批结果与连续一致；跨码或m30↔m60恢复拒绝，失败不修改原对象、来件和已返回结果。不增加进度字段、磁盘副本、旧r2兼容或迁移格式。

## 5. 来源读取与30分钟完成端点

### 5.1 本机DG日线取数

**装配。** `src/app/api/v1/router.py` 在现Settings显式local/dev时，给普通指数详情日线、r4识别和预测装配本机读取依赖。普通日线只对现Universe获准九码选DG，北证和其他普通行情沿原入口。生产普通日线沿原Session与查询，生产r4路由不注册。两种装配共用原业务状态和响应代码。业务层不按机器地址、URL、debug或另一份配置选源。配置、缺源处理见§9。

普通日线从既有 `/kline` 路由向 `IndexDetailKlineQueryService` 传读源，不注册第二条同URL路由。r4的日线和分钟识别、预测通过现router builder取得App装配的读取依赖；预测的 `IndexDetailXxmForecastQueryService.source` 与识别使用同一来源绑定、同一日历和已有共享缓存。普通图表和r4各自只读该请求所需列与窗口，沿现有API字段及独立请求职责。既有观察工具若拦截旧的 `read_daily`，随实际读源调用点调整；缓存键原有位置按§6保留。

**只读入口。** 在 `src/foundation/clients/local_lake/` 定义日线和SSE日历读取入口，维护Web自己的正式路径及字段合同，不在运行时import Dagster工程。复用现DuckDB读取方式，按日期范围批量确定正式分区路径并传入同一读取单元，只取已发布的 `part-000.parquet`。分区路径限制在本次需要的日期范围，批量识别存在的路径后才发SQL；不把全目录通配符作为页面请求输入。SQL绑定代码和日期，显式投影，以文件内DATE字段排序及判截止。不逐日执行SQL、不逐文件额外开读验结构、不扫无关历史。缺分区不补行情；已有文件读取或合同错误沿原接口错误退出，不回退Prod。

| 正式DG位置（相对于 `GOLDENSHARE_LAKE_ROOT`） | 使用方式 |
|---|---|
| `silver/index/index_factor_pro/trade_date=YYYY-MM-DD/part-000.parquet` | r4读 `trade_date/close/macd_dif_bfq/macd_dea_bfq/macd_bfq`；普通图表按 `index_detail_query._KLINE_FIELD_NAMES` 取原字段。两条路径对重叠日期使用同源数值 |
| `silver/calendar/trade_calendar/full/part-000.parquet` | 只取SSE的 `trade_date/is_open/pretrade_date`；见本节日历规则 |
| `silver/index_basic/full/part-000.parquet` | 普通日线身份读原五列 `ts_code/name/market/publisher/category`，沿现身份构造 |
| `silver/index_daily/trade_date=YYYY-MM-DD/part-000.parquet` | 普通日线的因子落后判断。在有因子数据且末日早于请求截止时，查该码 `(observed_trade_date, query_end_date]` 是否已有原始日线，只取代码和日期 |

**r4计算历史。** 日线读者使用共同下限 `date(2010, 1, 4)`（含），上限为 `load_entry/_load_series` 按原业务日与完成时点得到的 `completed`（含）。按 `floor <= trade_date <= completed` 取实际目标指数并升序返回，晚起指数从范围内第一根开始。无completed或上限早于下限时直接走原空输入处理。无有效输入走原EMPTY，有输入但末端落后走原DELAYED，实际首末之间的断档沿 `assert_continuous`。保留 `XxmBar` 必需值、正收盘及总行数检查；按现 `BUDGET.max_source_rows` 加一根作为读取上限，超过预算按原错误处理。识别的 `startDate/endDate/limit` 继续裁剪响应，预测 `asOf` 继续选择已计算历史前缀。两者不改变计算下限或最近完成日，不把4087根写入读源逻辑。

**普通图表。** `get_index_detail_kline` / `IndexDetailKlineQueryService.build_kline` 只替换九码本机读取依赖。保留身份、原图窗 `startDate/endDate/limit`、顺序、MA预热及部分数据状态。按图窗从近到远批量取最近limit根，每批最多limit个开市日，遇短历史或缺行只向前扩展未读过的日期，达到条数或范围下限即停，最终升序。日期下限取请求startDate和DG已发布最早分区中较晚者；未传startDate时以最早已发布分区为界。如果读取入口已有可靠的按码覆盖下限，可在规划时进一步裁剪；禁止为获取这个下限单独逐日探测或扫描行情。图窗有MA缺值才用同一DG因子源统计图窗首日前有效收盘数，达到原最大MA周期即可停止，沿现预热规则。普通图窗不套用r4下限。九码本机图表的身份、日历、历史和落后状态不另查Prod；摘要、成分、独立波段研究、普通分钟及鉴权沿原入口。

**交易日历。** 同一DG日历读者供普通日线上下文和r4各周期使用。保持 `MarketPageContextQuery.resolve_context` 的显式日期、上海时区、20:00业务日切换、上一开市日及session状态语义，只替换取日历事实的依赖，其他市场消费者沿原来源。日线连续性取计算下限至完成日的开市日，分钟沿原窗口所需开市日数，预测在原来需要确定目标端点的分支读取§5.3范围。已读到的正式K线直接使用，不额外查它当天是否开市。请求内复用已取得的日期窗口，确需更远日期时只补缺的范围，不为确定业务日读取1990年以来日历。

### 5.2 分钟

`source.ENDPOINTS`增加30，八端点为上海时区：10:00、10:30、11:00、11:30、13:30、14:00、14:30、15:00。60/90/120端点字面值不变。此表供完成截止、归一化、窗口规划、连续性及future_calendar统一读取；测试expected必须来自正式生产合同的独立字面表。

严格保持顺序：完成截止归一化→按N+1000选择实际端点窗口→建立同code/freq/日期请求→该窗口的两类signature→内容未命中才读取一次完整pair→两源逐键对应→逐根r4。签名发现调用的`minute_request`与`read_minutes`内部构造请求必须传相同code、freq、window；不得只改内容WHERE漏改签名请求。

N默认500、最大2000；read_rows=N+1000，因此1500/3000不变。30分钟每日8根，规划开市日数`ceil(read_rows/8)+1`，分别189/376；仅是规划上界，实际文件按该码合同与所选窗口，不可直接发现所有历史。短历史不补行。`startDate`只筛响应，不改变额外1000根政策。

来源复用`MajorIndexMinsLakeReader.read_complete_history_pair`：bars仅close，indicators仅macd_dif/macd_dea/macd，保留源参数/版本和完整键核对。正式Lake仍`/Volumes/datasource/data_lake`；不改Foundation读取器、其文件signature/prepared清单共享及原已优化路径。不同code共用一份物理分区事实是合法的，产品计算缓存按§6独立。

### 5.3 下一根和精度

本机 `future_calendar` 使用§5.1同一DG日历依赖。保留SSE从anchor起未来90自然日、最多91行，选严格晚于through的首个开市端点。m30明确11:30→13:30、15:00→下一开市日10:00；09:30、午休、未完成根不可当标准完成端点。历史asOf仍截到原完成端点。

m30沿分钟full_float、最近250根校准和1e-8容差。先precheck排除无候选，无需多余投影；有候选但少于250根或校准不通过为PRECISION_PENDING；空/滞后为EMPTY/DELAYED。近处有钝化范围就停止，不计算远处；已有结构及后续有限跟踪的预测仍按原规则。只预判下一根，不重开旧的中点试算、逐价格遍历或后19根推演。

## 6. 缓存、共享加载和发布顺序

保留现有键形状及period、ts_code的位置。将实际行情及日历来源写入现有的 `lake_identity` 位置；日线series和forecast键仍以ts_code结尾，分钟series及flight仍按原顺序在base后追加窗口或日期。series、共享加载和forecast共用同一份装配身份，跨来源不复用计算状态。

```text
base = (bind_id, lake_identity, period, detector_hash, ts_code)
day series = base
minute series = (*base, output_rows, read_rows, start_time, end_time)
day flight = (*base, context_trade_date, now_date, completed_hint)
minute flight = (*base, output_rows, normalized_end,
                 context_trade_date, now_date, completed_hint)
forecast = (bind_id, lake_identity, period, detector_hash, forecast_hash,
            source_id, expected, requested_as_of, calendar_id, ts_code)
```

App在装配时一次生成DG的 `lake_identity`，内容为DG来源标记和规范化正式根。day/m30/m60/m90/m120的周期位区分日线Silver和分钟Gold；两类均使用同一根下的DG日历，无需再加一个日历来源字段。DG的 `bind_id` 使用固定本机标记，原数据库调用保持原bind身份；构造键无需连接Prod。该身份仅作内部隔离，有序内容指纹、calculator源身份和公开编号沿现规则。forecast缓存仍由 `('forecast', *key)` 保存，共用LRU最多16项/64MiB，沿用现有共享加载、修订重算、历史prefix及淘汰。

仅在缓存读取和装配边界做廉价字段绑定检查：`_load_series`的日线/分钟`cache.get`取得非空旧entry后，必须立即核calculator的code/period/Spec，再复用输入或判断修订；不能让源值变化后的重算覆盖错绑entry、掩盖错绑。load_entry取得共享entry后、yield前再核同一身份；`_response`接受显式规范code，装配前检查entry一致（也覆盖内部直接装配调用）。这些entry检查共用模块内的`_check_entry_identity`方法，不重读配置、不重放算法或重复构造整份结果。forecast缓存命中检查code/period/版本/hash后继续原完整DTO校验一次。不得修改另一指数对象的tsCode后返回。

不匹配按来源合同错误失败，不覆盖原有效缓存。**两类缓存的原发布位置不同，不能合并或一起后移。**series在_load_series完成真实前缀、完整entry/内部响应验证及remaining后按现位置发布；后续普通投影、编码或forecast失败，可保留这份已验证的真实series，不回滚它。forecast候选才遵守：完整预测/装配→投影→序列化与字节检查→load_entry退出最后remaining成功→forecast最后check及原子发布→返回。禁止提前发布forecast候选，亦禁止因本需求后移series发布；原取消异常传播不吞掉，不返回部分成功。

## 7. 预测及直接消费者迁移

`IndexDetailXxmForecastQueryService.build`必填ts_code，交load_entry。READY/EMPTY/DELAYED以及NO_CANDIDATE/PRECISION_PENDING装配均用当前规范code。`_assemble`不再固定上证；缓存和forecastId以实际code生成，普通/debug字段集合、可空、状态和文本来源保持，不增加产品字段。

以下按被调用函数所在步骤成套迁移，不能因本节同时列出两种语言就把TS改造提前到第2步：

| 位置 | 具体动作 |
|---|---|
| 三个API模块 | signals返回dict加code、forecast四项解包，传新build签名 |
| query_service内部build/load_entry/_load_series/_response | 所有调用明确传code，包括内部空结果和历史分支 |
| forecast_query_service | load_entry、缓存、_assemble使用实际code；不重复Universe准入 |
| tests/web三组xxm API/validation测试 | read/build/load_entry包装及替身签名接收并断言code，不用任意kwargs吞掉错传 |
| `test_xxm_snapshot_consumers / r4_internal_results / r4_following_query` | _load_series/_response及read_daily替身迁移；旧hashkey和period位置断言同步 |
| `xxm/daily_window_precheck.py`固定时钟load包装 | 显式接受并转发ts_code、window_rows、requested_end；仍只做原上证研究 |
| `xxm_page_request_audit.mjs` | **第3步**与TS forecast client同批改：调用新版时显式传000001.SH；第2步不改该调用，不扩成九码性能工具 |
| `xxm_page_request_audit.py` | key[2]仍是period；核透明包装无漏参，不新增一轮观察计算 |

表中其余Python入口、包装、工具和直接测试均归第2步；mjs及其TS客户端集成测试归第3步。保留工具只做签名适配及必要回归，不运行旧研究、r2双组重放或扩工具业务范围。新增必填签名的其他真实调用若在编码前发现，先记录位置及所属步骤的迁移要求，不能用默认上证掩盖。

## 8. 前端编码设计

### 8.1 页面身份和资格

当前page-init client只将JSON声明为类型，不能假定已核代码。`controller/useIndexDetailController.ts::load`的顺序必须如下：

1. page-init返回后，先执行原`isCurrent`检查；已经过期或取消的响应直接沿原逻辑返回，不再核身份或更新页面。
2. 当前响应立即核`pageInit.index.tsCode === normalizedTsCode`；只有通过后，才能判断`EMPTY / !pageInit.quote / !pageInit.asOfTradeDate`并进入空状态，或发起后续请求。
3. kline返回后，同样先执行原`isCurrent`检查；当前响应立即核`kline.indexRef.tsCode === normalizedTsCode`，只有通过后，才能判断`EMPTY / kline.bars.length === 0`并进入空状态，或继续构建非空页面模型。

**两次代码身份检查都必须位于各自的空数据提前返回分支之前，不能仅放在`buildIndexDetailViewModel`紧前。**代码不一致沿原catch进入ID_QUERY_FAILED/error，不新增整个页面decoder或异常码；同码合法空数据继续使用原empty处理，不误报身份错误，也不启用r4。这是既有身份绑定要求的顺序细化，不改变普通分钟检查范围或页面状态模型。

`model/indexRecognitionAvailability.ts`目标签名：

```ts
resolveIndexRecognitionAvailability({development, tsCode, validatedTsCode, search}: {
  development: boolean; tsCode: string;
  validatedTsCode: string | null; search: string;
})
```

`IndexDetailPage`只在当前hasData且`viewModel.identity.tsCode === normalizedTsCode`时传validatedTsCode，否则null。函数计算`recognitionEnabled = development && validatedTsCode === tsCode && tsCode !== '899050.BJ'`；debug再要求URL精确debug=1。初始shell、名称映射、旧viewModel、loading/empty/error不能放行。前端不复制九码名单，后端仍为最终产品准入。

### 8.2 五周期识别

- `xxm/types.ts`：XxmPeriod加m30，response.tsCode改string，版本/hash不变。
- `useIndexXxmLayer`：移除仅上证判断，保留enabled、DEV、debug解码就绪及实际points条件，周期仅五个；requestKey原code/period/窗口/版本/hash/debug/indicatorVersion全部保留。
- `fetchXxm`已有tsCode，不改参数形状；m30沿现分钟路径发送freq=30。
- `decodeXxmResponse`去掉额外上证限制，仍要求raw.tsCode===expectedTsCode、period/指标版本正确。
- `timeKey`显式按m30/m60/m90/m120查各自端点，不让m30落入“否则120分钟”的分支，也不为非法周期兜底。
- day/minute两个ChartWorkspace继续传当前真实code/period/points；buildXxmViewModel保留逐根时间、close/DIF/DEA/hist与当前图表对应检查。非当前或缺数据不画旧标签。

普通分钟query/reader已有请求代码、周期及目标行检查，Hook已有requestId、abort和Map缓存；本需求沿用这些机制。对“两接口同时错返同一别码”不新增前端防御要求。切主图周期沿原loading→新数据交接，不增加“切换当次render必须清空”的状态模型；不能仅凭短暂旧state推断有错发r4或持续串图。正常切换和迟到响应仍做既有回归，实际页面验收如发现可见错误再按具体问题最小修复。

### 8.3 五行预判

`ForecastResponse.tsCode`改string；`FORECAST_PERIODS=['day','m30','m60','m90','m120']`，PERIOD_LABELS补`m30: '30 分钟'`。卡片沿现map及样式生成五行，不重排其它栏或新增周期按钮。

```ts
fetchForecast(tsCode: string, period: ForecastPeriod,
  asOf: string | undefined, signal: AbortSignal, options = {})
```

sendForecast使用传入code构URL，交`adaptForecast`的options新增必填tsCode；校验raw.tsCode===options.tsCode，保留原period/asOf/mode/版本/hash/状态/下一根端点/barsAhead合同。所有直接调用者一次迁移，不留旧签名重载或上证默认。debug外层身份核过后，decoder沿该response身份，不另读名单。

本段全部归第3步。`scripts/research/index_market/xxm_page_request_audit.mjs::runTab`中的forecast调用随上述新签名增加`000001.SH`首参；同时核`test_xxm_p4_audit_tools.py::_node_fixture_prelude`中动态导入TS fixture及字符串中的调用。对应客户端集成测试按§11.2在本步迁移和验证，第2步保持这条旧TS→旧mjs调用链，不增加兼容重载。

`useXxmForecast`移除仅上证限制，保留页面enabled+DEV+debug decoder；每次fetch显式传code。identity原有code、历史日期、minutes、版本/hash及debug不删；initial(minutes)生成五行，分钟能力关闭时只请求day。仍在技术面预判激活及页面可见时排队，按原refreshAfterMs刷新，单行重试、abort/generation/owner隔离保持。历史分钟asOf仍为历史日15:00+08:00，目标下一根由后端返回，前端不加30分钟。

### 8.4 调度和迟到结果

**保留`indexDetailRequestScheduler.ts`的真实现状：普通轻请求最多2个；xxm/forecast为exclusive，等在途结束后独占执行。不是两路r4并发。**五行可以进入队列，但不得改成两路或五路r4同时跑。客户端原5秒从调度实际开始计时，排队不算入这5秒，不因增加一行提高后端预算。

切指数/日期/debug、离开页面或不可见时，原abort、generation和identity失效继续生效；晚到的旧指数成功/失败不能更新当前状态。**切主图周期仅清理识别和独立研究对应owner；五行预测各有自己的period，现预测身份不含主图activePeriod，不因切主图周期重新发五行请求或丢弃仍合法结果。**预测激活/可见性变化仍沿原清理和恢复。debug URL变化仍允许普通行情重请求和图表重建；辅助模块自身loading/error/ready不新增行情刷新。普通页不import辅助包；生产不启用或加载。

### 8.5 独立研究与r4辅助分开

`debug/IndexRecognitionDebug.tsx`仅在`tsCode==='000001.SH' && activePeriod==='day'`时挂载DailyWaveController。其他指数/分钟返回null，但该debug模块导出的r4 decoder、renderXxmDetails及renderForecastDetails仍可用于全部获准范围。

原`useDailyWaveReview`保留上证+day+enabled+手动点击；daily-waves client固定上证/研究日期不改。非上证及m30不出现研究入口、不读取上证研究材料、不创建研究override。ownerKey变化清理原研究扩展，不能把它画到新指数。不得全局替换全部000001.SH常量误扩研究。

## 9. 配置、装配、性能与状态

复用现Settings与策略中心，沿现配置生效方式，不增设日线选源开关。环境与正式根由App装配时确定；本机无正式根或相应源不可用，在相关请求返回现有错误或数据状态，禁止回退Prod或影响无关路由。普通日线读取失败沿 `ID_QUERY_FAILED`；r4沿现 `XXM_QUERY_FAILED`、`XXM_SOURCE_CONTRACT_INVALID` 或预算错误，预测继续沿原异常映射。

| 现配置/事实 | 来源与消费者 | 生效/本轮动作 |
|---|---|---|
| majorIndices/CN_A | StrategyConfigService→Universe；首页、详情与r4准入 | 现service实例内缓存，新实例首次读取当前文件；不改JSON/版本、不另建九码集合 |
| APP_ENV | App装配及原前端DEV门禁 | 显式dev/local为九码装配DG来源；生产普通日线沿Prod，r4不注册、不请求 |
| GOLDENSHARE_LAKE_ROOT | 现Settings，默认空；本机DG日线/日历读者及现Lake消费者 | 复用现值，只允许正式 `/Volumes/datasource/data_lake`，随进程装配生效 |
| WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED | App分钟能力→Gold读者、前端minutes | 只控制原分钟能力，关闭时本机日线仍独立装配 |
| DATABASE_URL/GOLDENSHARE_ENV_FILE | 当前Web Settings及注入Session | 保留生产普通行情和未纳入本次的消费者；本机九码图表和r4读源不由DB地址决定 |
| MAIN_SPEC/FORECAST_SPEC、runtime.BUDGET | 唯一识别/预测及缓存/读源 | 版本/hash/限额不变；不是新增配置项 |

r4预算固定：后端请求含准入/context/排队/读源/投影/序列化/最后检查4秒；READY预测计算及缓存处理400ms；客户端实际执行5秒；识别1MiB、预测32KiB；LRU16项/64MiB；后端来源请求槽2；前端调度按§8.4独占r4。继续使用现remaining、pair reader中断及finally释放，不新造缓存、强行微优化或恢复暂缓第4—7批。

状态沿原合同：识别loading→ready/empty/delayed/error；预测idle/loading→ready（具体status为READY/NO_CANDIDATE/PRECISION_PENDING/EMPTY/DELAYED）或error，unsupported仅用于当前前端不可用范围。EMPTY/DELAYED不输出旧价格冒充新预判；北证为产品不支持，不是r4 EMPTY。普通只显示原公共事实，debug显示原完整依据，不能只凭标签相同漏掉真实code/参照错绑。

## 10. 来源统计和证据范围

方案§8.1记录本机DG九码的已完成统计，截止2026-11-04。用正式Silver因子及SSE日历，在DuckDB内按指数汇总首末日期、开市日数、实际根数及日期计数。以2010-01-04为下限另统计计算根数，同截止的上证、深证与Prod记录相符。较晚的DG首日是本次统计事实，代码只用共同下限及实际结果，不维护第二份首日配置。

后续复用该统计。只有核验明确需要不同截止的根数证据时，才按九码和所需日期范围做一次只读聚合，只投影代码和日期、只返回各码汇总。不得按日发查询、读取K线明细、对比实际MACD数值、额外重算或全量导出。聚合结论限日期覆盖和数量。

初次扩展的Prod近期日线和Gold分钟计数是已完成的历史单元，范围、预算和结果见§13.1及方案§11。Gold数据及K线/指标生产合同未改，复用既有计数。第4大步产品API验证按§11.3执行。

## 11. 测试case、执行组及真实验收

### 11.1 测试case设计

下表为必须覆盖的设计，不是已执行测试数量。可在现文件参数化，不强求一行一个新测试。输入依据为正式配置/生产合同/已验收人工金样本；expected不得调用被测函数生成。错误输入明确用于反向，业务状态必须从合法逐根序列达到，不随意修改内部对象造不可达行情。

| Case | 输入及操作 | 必须断言 | 文件落点 |
|---|---|---|---|
| T01 | 正式首页10码逐码请求五周期 | 九码获准、北证拒绝；含上证m30，不只新8码 | web/xxm_api、forecast_api |
| T02 | 000680.SH、合法名单外代码、北证；直接API及load_entry/build | cache/context/源spy均未调用；404；forecast XXMF前缀 | 同上 |
| T03 | 非字符串、缺code、非法格式；识别小写/空格与预测小写/空格；直接build空白/小写正常码 | 识别沿trim/upper；预测严格400；直接query格式400，合法可规范输入与规范码结果一致 | 同上 |
| T04 | 配置不可用/类型错；正常正式配置对照 | 500 QUERY_FAILED，不回退、不误报来源或名单外；正常不误拦 | 同上 |
| T05 | freq=30、period=m30；freq=15/m15；未知/重复/debug/date/limit错误 | m30正向、未获准周期400，其余原参数行为保持 | 同上 |
| T06 | 本地分钟能力关闭，正常日线及分钟请求 | day可用，分钟原不支持；直接北证优先不支持而非源错误 | local_routes |
| T07 | prod完整App装配及前端生产态，十码五周期 | 无r4路由/页面请求/辅助import；原行情路由仍在，鉴权401/403保持 | local_routes、页面 |
| T08 | 两指数合法不同日线，spy SQL及响应 | WHERE真实code、只该码、所有装配分支code正确 | xxm_api |
| T09 | 两指数m30，真实合同临时Gold，signature/内容请求 | 同code/freq/窗口；pair一次；响应与图表数值属于该码 | xxm_api、输入测试 |
| T10 | 非法NULL/NaN/缺根/重复/两源错键，及正常短历史 | 真实错误被抓；合法短历史不补值/不误拦，不读别码 | 同上 |
| T11 | READY/EMPTY/DELAYED/NO_CANDIDATE/PRECISION_PENDING分别跨code | 内外层code一致，不返回上证或假价格；状态正确 | forecast_api/validation |
| T12 | 原上证四周期全部既有业务金样本 | 逐根状态/参照/结构/显示/ID及hash不变 | calculator/r4_rules/product_v1_cases等现组 |
| T13 | 相同人工业务值给m30合法独立时点 | 钝化/形成/回转/参照失效/跟踪/同根显隐沿原字面预期，非空事件/结构 | calculator/r4_rules/following |
| T14 | m30八端点；09:30、12:00、未完成端点、+08:00异常 | 合法值通过、非法拒绝；最新截止归一化正确 | 输入测试、API、前端adapter |
| T15 | N=1/500/2000、短历史、历史end | 读N+1000；m30规划开市日数由公式独立算，默认189/最大376；不发现全历史 | saved_minute_window、xxm_api |
| T16 | m30 11:30、15:00、周五/休市前及历史asOf | 下一根13:30或下开市日10:00；无未来数据越界 | forecast_api |
| T17 | m30完整候选/结构跟踪序列，独立EMA参考及边界字面预期 | 真正经过comparison_envelope/make_display；非空条件及文本，不以EMPTY绕过 | key_point_forecast/following_forecast/p3_forecast_math |
| T18 | 无候选、249根、250根正常/校准错误 | 无候选不投影；校准/精度状态沿原，分钟full_float/1e-8不放宽 | 同上 |
| T19 | m30连续/分批、calculator_at、clone；跨code/m60恢复 | 同组一致、跨组拒绝且双方不污染；关联完整 | r4_restore/snapshot_validation/snapshot_consumers |
| T20 | 两code同period/端点、每根数值完全相同的合法输入 | sourceInputId可相同；series/flight/forecast分开；非空ID随code不同 | xxm_api/forecast_api/shared-load |
| T21 | A/B交替及并发，B失败/修订/取消 | 各码独立；A有效结果不变；同码同窗共享不重复读取 | 同上 |
| T22 | m30与m60各合法输入、端点相同 | 缓存/快照/forecast不同周期不混；同周期热命中正确 | 同上 |
| T23 | 在缓存边界放入另一code的合法完整entry/forecast对象；entry分别配本码相同/不同源值 | 即使DTO现允许多码也拒绝错绑，不因修订重算覆盖旧缓存；不重放算法验证 | 同上 |
| T24 | 五周期普通/debug结果，同code同窗 | 普通字段投影一致；普通无辅助，debug参照/事件/结构关联完整 | API validation、debug contracts |
| T25 | 第3步forecast client/adapter及mjs调用，非上证/m30、错code/period/asOf | 所有调用新签名、URL实际code，正确通过、错误拒绝；mjs原上证工具不扩业务范围 | client/identity/r1Contract及p4_audit_tools客户端节点 |
| T26 | 激活五行预判，单行失败/重试，minutes=false | 顺序day/m30/m60/m90/m120；重试仅本行；分钟关闭只day | forecast.test、Card |
| T27 | validated=null/串码/北证、初始shell/loading/empty/error；正常九码；page-init及kline各自同码/错码EMPTY响应 | 前者不发r4、正常九码可用；两接口都先核身份再判断空数据，同码EMPTY进empty，错码EMPTY及错码非空进ID_QUERY_FAILED/error | availability/Page/controller |
| T28 | 切指数/日期/debug，旧成功/失败延迟返回；另切主图周期 | 旧结果不回写；识别/研究清理对应owner，主图周期变化不重启五行预测 | Hook/Page |
| T29 | 通过真实scheduler排队普通请求+五行r4 | 轻请求上限2，r4独占；5秒从开始执行算，不把Hook mock五pending当网络并发证据 | scheduler/client |
| T30 | debug上证day手动开研究；其他码/m30/退debug/切页 | 研究仅原范围手动；其他码r4辅助可用、无daily-waves请求/覆盖 | debug/daily-wave/Page |
| T31 | 普通页、debug页、生产构建 | 普通无动态辅助import，debug按需，生产关闭 | dependencyBoundary/useIndexDebugModule |
| T32 | 上证原相同输入及code默认核心数学样本 | 旧指纹/ID/hash稳定；产品构造显式传code | snapshot_consumers/forecast_api/forecast_validation/现规则组 |
| T33 | 17个合法缓存项、冷热及forecast候选最后检查失败 | 共用16项/64MiB正常淘汰；最后失败不发布forecast候选，但已验证series仍可保留，不改原两类发布顺序 | cache/API validation |
| T34 | 已完成的日线来源聚合 | 原Prod近期计数见§13.1，DG覆盖及新计算范围见§10，只返回统计 | 已有统计 |
| T35 | 已完成的Gold分钟分组计数 | 九码每码每类24/12/9/6、各类459 | §13.1既有统计 |
| T36 | 定向DG实测及原未完成组合 | §11.3来源、范围、状态、端点、响应和预算如实记录 | 真实只读API |
| T37 | 真实App装配显式local/dev、prod；本机分钟开关关闭 | 本机九码普通日线和r4只走DG，日线独立于分钟开关；生产普通日线走Prod，r4路由关闭；北证及未纳入对象沿原入口 | local_routes及普通日线API |
| T38 | 样本含2010-01-04前、当天、完成日后各一根；另一指数首日更晚；同码不同显示窗/asOf | 前后越界排除，当天纳入，晚起不补行；显示窗/asOf不改变计算起止，识别预测共享输入范围 | 日线读者、query、forecast |
| T39 | 普通图窗有早于r4下限的数据；另含正常完整、短历史MA预热、因子落后三种样本 | 原图窗、完整字段和状态保留，同日图表/r4的close、DIF、DEA和柱同源；无MA缺值时不查预热 | kline API及DG读者 |
| T40 | DG SSE日历覆盖20:00前后、休市日、分钟15:00及下一个开市日 | 图表业务日、r4完成日/连续性/预测下一根沿旧口径；本机不用Prod日历，同请求日期窗口复用 | context、source、forecast |
| T41 | 正常缺文件导致空或滞后、中间断档、实际读取失败；Prod替身可读 | 沿原空/延迟或来源错误分支；所有情况禁止回退Prod，失败不发布候选 | source及local_routes |
| T42 | 本机DG来源写入既有键位置，普通和debug沿同一来源装配 | series/共享加载/forecast按来源隔离，保留原键形状及末位代码规则；共享和公开编号复用适用的已有测试 | cache/query/forecast |

T13/T17复用现独立数学/业务金样本，换成正式合同中的m30合法时间，不用被测端点表生成时点；预测校准长前缀可沿已有高精度Decimal独立参考构造，expected不调用recover_projection/同一求解器。T23只构造真实可能的“另一合法对象被放错key”，不造无意义内部坏状态。不能将所有真实行情强行要求有信号；非空规则路径在独立人工样本保证。

T27的空响应沿现page-init/kline生产者及schema构造，保留合法EMPTY的身份和空数据字段，不制造与合同矛盾的READY空行情。具体覆盖：

- page-init同码EMPTY：页面进入empty，不报ID_QUERY_FAILED，不继续发kline或r4请求。
- page-init错码EMPTY：使用另一合法指数的完整空响应；必须进入ID_QUERY_FAILED/error，不得被EMPTY分支提前接收，也不继续发kline或r4请求。
- page-init同码正常，随后kline同码EMPTY且bars为空：页面沿原逻辑进入empty，不报身份错误、不启用r4。
- page-init同码正常，随后kline错码EMPTY且bars为空：使用另一合法指数的完整空响应；必须进入ID_QUERY_FAILED/error，不得按empty接收、不启用r4。

以上与既有错码非空、正常九码及初始/错误状态用例一起验证。过期/取消响应仍先由isCurrent忽略，迟到结果覆盖沿T28，不因新增身份检查将旧响应变成当前页面错误。

### 11.2 自动测试分组和消费者核对

先核现文件及环境存在再运行。使用现解释器，pytest加`-p no:cacheprovider --basetemp=/private/tmp/<本任务>/pytest`并禁字节码写入。前端保留package.json的类型检查及Vite构建两项职责，但不执行会写工程内构建信息的裸`tsc -b`。固定：根目录执行`npm --prefix wealth run typecheck`；wealth工作目录以现`./node_modules/.bin/vitest run --no-cache --configLoader runner`执行限定/完整测试，`./node_modules/.bin/vite build --configLoader runner --outDir /private/tmp/<本任务>/wealth-dist`构建。runner避免临时config bundle，构建目录是本任务新目录；不清其他产物、不修改package/config、不使用可能下载的npx。

**测试成本及执行安排：**当前`pyproject.toml`未配置统一测试总超时。[原LLD§22.16.4逐文件实测及§22.16.6最终对账](index-detail-top-bottom-recognition-low-level-design-v1.md)中，原识别API187项全程19.820993秒、原预测API117项全程5.773790秒；它们只说明原输入、原测试数量和当时环境的实耗，不能推导扩码/m30后的全程上界。每个后端执行单元取下表一个明确文件，或本节已划分的工具节点；前端限定测试按文件，typecheck、完整test和build各为独立单元。保留测试原有局部超时，不新增统一总时限，也不宣称测试已满足尚未有依据的全程秒数。

每个单元从准备临时调用开始，分别记录准备/导入收集、实际测试、资源关闭/退出、摘要和最后数量/退出核对的耗时；完整单元总耗时为这些实际阶段之和。新增测试的各阶段耗时在执行前不能确定，如实登记这个限制，不加固定余量。原产品4秒/400ms/客户端5秒仍按其实际生效位置断言，不以测试进程总时间替代。第2步只执行A—D的后端必要文件/节点及F中的架构、依赖和文档检查；前端类型检查、测试及构建在第3—4步执行。

使用原测试的首错退出方式（pytest `-x`、Vitest `--bail=1`）；断言失败、非零退出、现有局部超时或取消后，不再领取后续单元，关闭本次自有资源并记录已经发生的准备、测试和收尾成本，不动共享服务。未完成单元在原因解决并获准继续后完整重做，其重新准备、全部测试和收尾另计；已完整通过且依赖未变的单元不重跑。测试进程退出后才核数量、退出状态及本次自有资源释放；没有这些结果不得登记完成，不自动重试、跳过失败或为通过测试增加新的超时值。

前端临时输出参数在设计时已依据现安装CLI及[Vitest 3.2.4文档](https://github.com/vitest-dev/vitest/blob/v3.2.4/docs/guide/cli.md)、[Vite 7 CLI](https://v7.vite.dev/guide/cli)和[配置加载说明](https://v7.vite.dev/config)核对；第2步不运行这些前端测试或构建，留第3—4步执行。

| 组 | 执行范围 | 说明 |
|---|---|---|
| A 核心/恢复 | scripts/research/index_market/tests下现calculator、r4_rules、following、restore、snapshot_validation、input_validation、product_v1_cases及`test_xxm_index_expansion_dto.py` | 原四周期已有金样本加m30必要参数化；新增DTO测试只覆盖本需求代码格式/五周期准入，按文件切单元，不运行冻结行情回放 |
| B 预测数学 | 现key_point_forecast、p3_forecast_math、forecast_expression_contract、r4_following_forecast、forecast_display | 覆盖m30内部限制及原数学不变 |
| C 查询/API | tests/web/test_wealth_index_detail_xxm_api.py、forecast_api.py、forecast_validation.py、local_routes.py、test_xxm_shared_loads.py | API实际路由、Universe配置和真实query；临时DB/Gold按当前生产合同构造；替代哪层须说明 |
| D 内部消费者/工具 | 现snapshot_consumers、r4_internal_results、r4_following_query、saved_minute_window、p4_audit_tools的Python节点及`test_xxm_daily_window_precheck.py` | 第2步核Python签名/观察包装、历史/发布顺序；daily_window_precheck完整覆盖新code/window参数；p4_audit_tools下列TS客户端节点归E，不因文件是Python就提前迁TS |
| E 前端及TS工具调用 | availability、controller/Page、xxm及xxm-forecast、debug、daily-wave、scheduler及下列p4_audit_tools客户端节点 | 第3步同步新client首参、mjs、全部adaptForecast options及fixture字符串调用；五行fixture/Record补m30 |
| F 通用检查 | 现typecheck、完整test、构建各独立单元；测试禁缓存，构建仅调整输出到上述临时路径；架构三测试及研究依赖、文档检查 | 前端全回归失败不得登记全部通过；无关旧TODO不趁机修复 |

`test_xxm_p4_audit_tools.py`不物理拆文件。第3步随client/mjs同批迁移并验证下列五组现有函数及其参数化节点：`test_actual_node_clients_selected_counts_dates_and_debug`、`test_actual_node_clients_reject_empty_bad_source_and_old_contract`、`test_actual_minute_node_clients_wait_for_paired_indicators`、`test_actual_minute_node_clients_reject_mismatched_pair_before_signals`、`test_real_node_failure_protocol_preserves_client_error_records`。它们实际加载TS fixture及mjs，不能提前按新签名修改。第2步执行该文件除上述五组客户端节点外的其余现有节点，按明确nodeid列清选择；不能因名字中含node就误排原通用进程监督测试。第4步按当前完整文件节点清单对账，复用代码/输入/依赖未变且完整通过的结果，只补未覆盖或依赖变更节点；完整文件覆盖不等于强制整文件重跑，复用及本次执行不重复计数。不拆文件或新增case，也不因此扩工具业务范围。

研究依赖用CodeGraph影响面及临时AST导入检查复核本次`src/biz/services/wealth/market/index_detail_xxm`和`queries/wealth/market/index_detail_xxm`：不得引入scripts/research、reports、App或QTF；纯计算不新增DB/文件/网络依赖，runtime既有Foundation限额引用保持。检查只分析当前文件导入，不运行研究或读源码SHA。架构三项为`tests/architecture/test_subsystem_dependency_matrix.py`、`test_platform_legacy_guardrails.py`、`test_operations_legacy_guardrails.py`。不虚构依赖测试文件，也不把整仓测试作为本次最小验收。

需要迁移的前端直接消费者必须全部核到：forecast client测试及工具mjs、adaptForecast的identity/r1Contract调用、ForecastRows字面量、forecastFixtures/xxmFixtures、页面mock、debug contract参数表、原m30 unsupported断言。forecastFixtures显式接收tsCode；m30默认through为前一开市日15:00时，target用独立字面“下一开市日10:00”，不能落入现“非60/90则11:30”分支。逐个改为显式code/五周期，不用放宽断言或任意kwargs让签名错误通过。

#### 11.2.1 取数调整的回归与证据复用

原第4步完整前端回归和构建的实际结果见§17.2。本轮对应§2.1第1—2项，按下表推进。每条要求有一次适用的通过证据即可；同一个测试可覆盖多条要求，无需拆开重复执行。

| 顺序 | 执行要求 | 完成条件 |
|---|---|---|
| 1 对账 | 按T37—T42列出实际改动和现有测试文件或用例。核原证据所覆盖的实现、输入合同、依赖及相应构建输入。仍适用的直接复用；对账时只看代码差异和现有结果 | 明确每项已覆盖、需补跑或需补测试。前端文件有变化时，旧结果继续证明原版本，受本次交付影响的前端检查按实际依赖选取 |
| 2 实现并补测 | 实现§5/6/9。优先扩展既有路由、读取、普通图表、r4 query和forecast测试，只补缺少且会改变结论的场景。DG测试使用真实生产字段合同的隔离Parquet，生产路由对照沿原隔离数据。真实DG API留到§11.3 | 能覆盖本机来源、实际输入范围、日历、状态和生产路径。合并同一文件或节点的覆盖一次执行，按影响补必要的类型检查或构建；取数改造无前端影响时不自动触发整轮前端回归 |
| 3 对账和交接 | 记录执行文件或节点、复用证据、通过/失败和实耗。准备、执行、退出及最后核验的耗时均按实记录。临时夹具和输出放本任务 `/private/tmp`，使用已安装的工具 | 必需项通过才进入§11.3。失败即停止；修复后仅重跑失败或受修复影响的单元，通过且证据仍有效的单元保留 |

本阶段是自动回归和实现对账。定向DG真实请求与管理员页面验收分别按§11.3、§11.4推进，已有有效结果不为另出一份报告而重复执行。

### 11.3 第3项真实只读API、debug和性能核验（Codex执行）

本节对应方案§8.3，由Codex执行；第4项页面验收另交管理员。仅在第2项取数调整和受影响回归通过、临时程序静态复核后开始。原Prod链路的执行见§17。

#### 11.3.1 定向补验、原未验组合及完成标准

沿原API请求截止2026-11-03，实际记录现装配计算的completed及输入范围，区分响应与计算截止。按§2.1实现和回归通过后执行两段。

| 执行段 | 组合及请求 | 对照与完成条件 |
|---|---|---|
| DG定向补验 | 上证day发一次普通 `/kline`，再连续发普通识别、普通预测、debug识别、debug预测。深证m60按同顺序发四种r4请求 | 上证核图表/r4同源、2010-01-04下限、根数、普通/debug及公开结果；深证m60核DG日历、原Gold、分钟窗口和下一根端点。记录实际耗时，共9次请求 |
| 原未验组合 | 从创业板day开始，按首页顺序排除北证，每码依次day/m30/m60/m90/m120。失败组合完整重做、34个未启动组合续验；每组普通识别和预测，科创50m90、中证A500m120各再发debug识别和预测 | 35组合、70次普通加4次debug，共74次；创业板day核晚起首日。首错停后续，保留完整通过单元 |

`/kline` 沿原图窗参数，传 `period=day&limit=300&endDate=2026-11-03`，只比对该响应和r4响应中同日已有的收盘与MACD。日线识别xxm-signals传period=day、limit=300；分钟minute-xxm-signals传freq及limit=500，均传实际tsCode及endDate=2026-11-03。预测xxm-key-point-forecast传实际tsCode/period，日线asOf=2026-11-03、分钟asOf=2026-11-03T15:00:00+08:00。debug仅加debug=1，保持组内连续。两段请求分别记账。

复用原公开摘要，在标的、输出窗口和计算前缀可比较时核结果一致。原摘要缺字段或输入修订则记录不可比较及原因，不另发真实行情查询。已完成分钟组复用Gold、周期和功能证据，DG日历由定向组合核验；深证日线保留原功能证据，DG日线路径由上证定向及剩余日线实测证明。旧证据、新源实测、失败和未执行分列。

组合关闭及摘要核验后才进入下一组。核实际来源、身份、窗口、公开合同、响应大小和规定的普通/debug；r4按原4秒/400ms预算，普通图表单列实际耗时并沿其既有合同。合法空、滞后、精度待定或无候选按实际状态记录。相同输入下的普通/debug差异按首错处理。

#### 11.3.2 临时程序装配和只读边界

为按完整组合交接、续跑并能单独中断本轮程序，每组合由父调用顺序启动一个临时Python子进程，不为它设置额外整组总超时。组合内装配一次App和自有XxmCache，完成2或4次r4请求后清理退出，上证定向另含一次普通图表请求。同组debug不另开进程或清缓存。实际准备、资源初始化、读取和清理成本按执行单元计入，不把此方案说成跨组合缓存/淘汰的真实验收，也不因此增加测冷或并发请求。跨码共享/淘汰规则继续由既有隔离测试及当前实现证明。

| 当前代码依据 | 临时程序中的具体用法 | 保持/禁止 |
|---|---|---|
| src/foundation/config/settings.py::get_settings、src/app/web/run.py | 导入设置前明确传入当前Web使用的GOLDENSHARE_ENV_FILE；核APP_ENV为显式local/dev、分钟能力及正式Lake根，记录脱敏目标/文件路径 | 不默认回退根.env、不输出凭据；沿本机正式配置，由实际App装配DG读者 |
| src/app/api/v1/router.py::_include_local_xxm_routers | 在临时FastAPI和/api/v1的APIRouter中调用原装配方法，安装src.app.exceptions.install_exception_handlers | 不启动完整Web lifespan、uvicorn、监听端口、Node或浏览器；定向补验同时挂载普通指数详情路由；均沿实际产品装配 |
| src.app.dependencies.get_db_session、src.db.get_session_factory | 沿本机产品实际依赖装配；若路由仍注入Session，允许创建未连接的会话，取数及退出均无需访问Prod | 旧临时脚本在每次请求前执行的 `SET TRANSACTION READ ONLY` 不进入新脚本；目标请求触发Prod连接或SQL即为失败 |
| src.app.auth.dependencies.require_quote_access | 只在临时App dependency_overrides中提供测试身份凭据 | Universe/query/source/calculator/DTO和本地能力检查保持真实；原401/403由既有测试证明，本次不宣称重新验收鉴权 |
| query_service._CACHE / XxmCache | 在子进程上下文内使用一个新的原XxmCache实例，沿原16项/64MiB限额 | 不清或修改共享Web缓存，不增限额或新缓存实现 |
| 当前TestClient用法及local_routes测试 | 使用进程内TestClient，不以context manager启动App lifespan；请求真实已装配路由，最后关闭client | 不替代query/source返回值；TestClient/ASGITransport的timeout参数不能冒充阻塞SQL的硬截止 |

在自有进程的 `src.db.get_engine()` 所用Prod连接入口放一个拒绝连接的测试钩子。目标请求试图连接即在发出网络请求前报错并停止后续组合，记录触发请求及阶段。该钩子只用于验收进程，不改生产代码，不用mock替换真实DG读源或业务结果。旧临时脚本的Session包装不复用；仅复用不读源的摘要观察和 `compare_modes`。临时程序、日志和摘要放本任务 `/private/tmp` 目录。

TestClient进程内请求、lifespan和依赖清理已对照现已安装实现及[FastAPI TestClient](https://fastapi.tiangolo.com/reference/testclient/)、[测试生命周期](https://fastapi.tiangolo.com/advanced/testing-events/)、[yield依赖清理](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)核对；文档引用只说明用法，不替代当前路由/真实来源证据。

#### 11.3.3 观察位置、数量和耗时

所有包装只调用原方法一次，使用原返回值，异常原样抛出；不改参数、返回值、时钟值、截止或业务分支。每次请求完成后只保留小摘要，不复制内部完整entry或日历。观察器的额外开销包含在本次实际耗时中，不从结果中扣除来凑预算。

| 包装/读取位置 | 仅记录原已有结果 | 禁止追加的动作 |
|---|---|---|
| §5实际装配的DG因子/日历读者、query_service中的read_minutes | 来源、调用次数、原返回len、代码/周期、计算窗口和读源耗时，定向另记录普通图表来源 | 不重发查询获取计时、根数或明细，不读无关指数或重算MACD |
| query_service.plan_minute_window | 原返回output_rows/read_rows/start_time/end_time | 不重新规划窗口、不发现全历史文件；分钟limit=500仍沿产品最多1500根 |
| XxmCache.get/get_forecast/put_forecast | 原返回是否命中/发布、调用次数、原entries中已有大小/项数 | 不造错key、不预热、不清缓存、不添加第二套缓存验证 |
| response_projection.project_xxm_response | 原internal.source.inputId/indicatorVersion/startTime/computedThrough、meta.count/responseStart/responseEnd及public结果摘要 | 不拿entry.processed生成时间列表、逐根核指纹或额外恢复prefix |
| forecast_query_service.project_forecast_response（该模块已导入的别名） | 原internal.sourceInputId/calendarInputId/computedThrough/precisionPolicy及public摘要 | 不为了取得普通响应未公开的编号再发debug或新SQL |
| load_entry透明上下文 | 当前请求只持有原entry：len(entry.raw)为缓存输入长度、len(entry.processed)为已计算长度；身份取entry.calculator.source_identity，分钟indicatorVersion沿原身份末段读取、day为None；预测仅在internal.computedThrough及entry.processed均非空时取entry.processed[0].time，末端用internal.computedThrough，EMPTY记空 | 两个len均不能称历史asOf的实际prefix长度；不二分/遍历时间重算prefixRows，退出即释放引用 |
| build及原预测perf_counter观察 | 分别记录原build调用耗时、API往返及原预测计算阶段 | 不把HTTP/完整build耗时称为400ms计算耗时，不伪造计时数据 |

预测计算计时沿旧透明clock思路：只在forecast_query_service模块的time别名上转发真实perf_counter，记录本次build中原400ms deadline建立时的首次调用，到原build结束的实际间隔；没有进入该阶段则记“不适用”。使用本次请求自己的记录，finally清理，不修改全局time函数、源now或原返回值，不复制旧collector及其额外遍历。IndexDetailXxmQueryService.build和IndexDetailXxmForecastQueryService.build分别测原调用，API往返另测；后端4秒及预测400ms按原实际生效位置和最终预算检查评价。若只得到整体耗时，不能宣称已量得计算分段。

日线正常产品按§5读取，分钟也可能因真实修订重新读取；**只禁止观察器增加读取，不强制一个组合只能读源一次或热请求必须零读源。**实际读取根数、响应根数及多请求累计次数分开，不将累计数量称为独立K线数或物理磁盘扫描量。

#### 11.3.4 普通/debug对照

先按当前tsCode/period及signals/forecast找到唯一普通/debug一对，再用既有compare_modes。保留requestedAsOf、computedThrough、sourceInputId、calendarInputId、indicatorVersion和实际窗口的同源前提；signals没有日历编号则按原方法记空，不额外计算新编号。round/tabId仅沿原比较字段使用固定同一单次记录，不代表本轮双页/并发测试。publicDigest只对已经投影的公共响应按原方法生成，排除debug；不对源码或真实行情另建指纹。

实际源/日历/窗口不一致时记not_comparable，不追加请求、读源或重放来凑一致；前提相同而公共摘要不同则失败并停止下一组合。当前组合比较结束释放完整响应，仅保存结果状态和摘要；不积攒45组合或100份完整JSON。版本/hash、ID/结构关联仍由原DTO及已通过业务金样本约束，不为核验再运行一次识别。

#### 11.3.5 阶段进展、异常中断、失败和续跑

管理员已明确：本轮暂不设置额外整组总等待阈值，真正卡住时由Codex先判断定位，再汇报讨论。临时调用不要求先取得总秒数，不新增外层subprocess固定timeout、额外整组deadline或固定轮询/判卡秒数。产品4秒/400ms/真实TS客户端5秒、驱动和测试原有超时继续在各自生效位置保持；已完成来源统计的历史限额不因本决定重写。

执行顺序为：完成设计及静态审计→第2项取数调整和受影响回归通过→按设计准备临时程序并静态复核→逐组合执行。第1项准备不提前请求真实DB/Lake；第3项的首次正式请求本身核验实际DG读取，不额外做一次探测/预热或重复读源。

每组合记录从准备开始到最后核验结束的实际耗时，包含启动/导入、资源初始化、该组合规定请求、比较、关闭/退出和父调用摘要核验；不宣称全程有固定秒数保证。每个阶段开始/结束立即输出当前tsCode/period、阶段、请求序号及实际时间并刷新输出，日志在本任务/private/tmp。通过当前工具已有运行会话分段查看新输出，保留本轮自有进程身份，不为此新增心跳、进程通信或监督框架。

没有结果或进展显得异常时，先查看现有日志最后阶段、已耗时及本轮进程状态，区分正常计算/读源、真正停滞与工具暂未返回输出。进程存活不等于业务前进，一次没有新输出也不能直接判超时；不能承诺立即识别所有阻塞。判断卡住后停止领取后续组合，报告当前指数/周期、阶段、最后成功项、实际耗时和已核实原因，再讨论处理；不额外发API/SQL来“试一下”，不自动增加时限、改规则或启动其他服务。

正常完成/异常退出时finally关闭本轮实际创建的只读Session、DuckDB连接、client及Engine，退出观察上下文。需要中断时只针对本次临时调用的自有进程，沿工具/标准子进程的取消或终止能力处理，确认退出后不继续下一组合；不终止共享Web/DG/数据库等服务，不改正式数据。若强制终止，明确记录清理未完成，不能伪称执行了finally。TestClient和产品remaining不能硬中断所有阻塞SQL，不用其timeout参数冒充新增全程截止。

HTTP错误、合同/身份错误、产品既有查询/计算预算失败、实际异常卡住或比较失败，首个问题即停止后续组合，汇报完成/当前/未执行范围、实际数量及耗时。没有新增总等待阈值，不把“未达到某个自定秒数”当作继续异常任务的理由，也不把正常较长耗时自动改记为产品超时。NO_CANDIDATE等合法状态不是失败；not_comparable按§11.3.4单列，不登记比较通过；本项不加载TS或声称客户端端到端验收。

完整通过且依赖未变的组合保留，中断部分仅作诊断。原因核清并获准继续后，从未完成组合完整重做2或4请求和比较，含重新准备/关闭/核验的实际成本另计；不能换新进程只补debug并称热路径。不自动重试、换源、补数据或放宽产品预算。

#### 11.3.6 前三项结果和管理员交接

Codex汇总第1—3项及独立审计：自动回归/构建及其复用、新增证据、DG定向补验、未验组合的完成/失败/未执行状态和规定普通/debug对照、后端4秒/预测400ms实际阶段、读取次数/范围、缓存及响应大小；没有执行的项留为未执行，不按计划量填通过数。只保存小摘要到原方案/LLD，不向reports写过程报告或复制全部响应。

提交给管理员的页面清单使用§11.4代表组合及普通/debug切换、指数/周期切换、五行状态/重试、北证排除和上证day手动研究入口，并指出API阶段真实出现的EMPTY/DELAYED/精度待定等限制。只有必需自动回归、构建、API及规定对照均通过、独立审计符合要求时，才能写“第4大步前三项完成，真实页面待管理员验收”；首错/未执行写实际停点，not_comparable写“请求已完成，对照未证实”，不能升级为全部通过。Codex不替管理员点击或登记页面通过；管理员明确反馈后再对账§12并记录整体验收，不能从API成功直接跳到需求收尾。

### 11.4 第4项真实页面验收（管理员执行）

本项由管理员完成。Codex在第1—3项结束后提供代表页面/周期、API状态/限制和检查清单，不自行打开真实页面执行本项，不以自动测试、构建或API通过替代管理员的实际反馈。页面问题由管理员反馈后再核当前代码和影响面；需要修复时先补对应方案/LLD，不直接修改r4规则或扩大范围。

管理员使用现有本地前端/后端，以真实API驱动页面，不用mock adapter。缺服务或需要改变连接时，由管理员决定处理；Codex不因准备交接自行启动/重启、安装或改连接。查看上证日线的图表、识别和预测，再看上证m30、深证m60、科创50m90、中证A500m120及北证排除，另核上证day原研究手动入口；正常/debug切换和指数切换覆盖一次。页面产生的请求与Codex按§11.3执行的请求分别记录，不预加载另外九码。

核心字段：code/period、时间/close/DIF/DEA/hist、ordinaryState/direction、events.type/time/displayOnChart，debug参照及structure关联；预测status/reasonCode、targetEndpoint/barsAhead、display四文本及来源时间。前端只画对应本图结果，预判五行有正确周期名、状态/条件、单行重试和完成时间，不能前端重算标签。北证无r4占位，普通行情仍正常。

由管理员反馈页面可见结果及检查到的console/请求身份与次数；未提供的证据如实注明，不补造，也不默认要求Codex再跑一次页面。普通无辅助import、debug按需、研究仅上证day手动及生产关闭的自动测试证据由Codex先交付，不能将构建成功当生产页面实测。网络/数据失败如实展示并记录，缺数据不制造标签或强改测试预期。页面访问不另施加“必须撞到并发共享”的人为要求。

## 12. 编码门禁矩阵、例外及交付

对应[通用清单](/Users/congming/github/goldenshare/wealth/docs/system/module-delivery-checklist-v1.md)，未列为不适用的条目均要执行：

| 清单 | 适用性与本需求落点 | 验证 |
|---|---|---|
| 2.1事实链 | 适用：本方案为独立实施依据，本LLD细化；视觉沿已验收页面和明确五行变化，不另造Figma/benchmark | 文档review；§11.4管理员页面反馈 |
| 2.2事实归一 | 适用：§3—7唯一后端事实，TS只绑定/渲染 | T08—T11、T24—T25 |
| 2.3状态机 | 适用：§9原状态及5秒超时 | T11、T26—T28 |
| 2.4显示语义 | 适用：原方向/颜色/时间/文本映射不改 | T13、T24、页面 |
| 2.5行为测试 | 适用：五行、切换、错误/重试/迟到 | T26—T31 |
| 2.6文档同步 | 适用：方案/LLD/索引及实际执行事实 | 逐项对账 |
| 2.7渐进替换 | 只适用单模块及失败停止；本次已有real能力扩范围，不是mock→real，不新增source开关或退回mock | §2、§9、T31 |
| 2.8契约 | 适用：字段集合不变，code/period值扩展；第2步Python生产者/调用方同迁，第3步TS客户端/mjs/调用及测试同迁 | §2/3—8、T24—T25 |
| 2.9坐标说明 | 适用原MACD坐标/标记；家数/累计值非负等例子不适用，DIF允许负值 | T13、页面 |
| 2.10传输/性能 | 适用：源code/窗口下推、4秒/400ms/5秒；无新增中位数或数据库特有聚合 | §5、§9—11 |
| 2.11配置 | 适用复用审计；不新增配置或热加载 | §9、T04 |
| 2.12映射 | 适用：本表完整映射 | 文档审计 |
| 2.13例外/断言 | 无新增例外；MACD允许负数属原语义，不套累计值规则 | T13、T24 |
| 2.14显式坐标参数 | 无坐标算法/参数修改；现行为保持，不能以扩码改图表范围 | 页面/原图表测试 |
| 2.15并排双图 | 不适用：本需求无新增并排双图 | 范围检查 |
| 2.16单行文案 | 适用现卡片样式；新增30分钟行不挤压其他卡片 | T26、页面 |
| 2.17核心case | 适用：Codex执行§11.3真实API；管理员执行§11.4真实页面，mock及API成功不能替代页面通过 | 两类证据及执行人分别记录 |
| 2.18八原则 | 下表逐条映射 | 不得空项 |

| 原则 | 编码/证据落点 |
|---|---|
| 事实源单一 | Universe、按环境装配的日线/日历、正式Gold和原r4；T01/T08—T10 |
| 契约先行 | §3.3/4/8目标合同及全消费者；T24—T25 |
| 配置一致 | §3/9，不复制名单/不新配置；T04 |
| 默认显式 | 北证、五周期、空/延迟、minutes关闭；T02/T05/T06/T11 |
| 排序筛选确定 | code过滤、时间升序、预判五行顺序；T08/T15/T26 |
| 性能预算前置 | §9原限额保持；§11.2记录自动测试成本；API不设额外整组等待阈值，按§11.3.5观察进展、异常停后续并汇报；T33及真实后端性能 |
| 异常标准 | §3.1现码、普通/debug分层；T03/T04/T24 |
| 用户可见结果 | Codex交API/自动证据及页面清单；标签/时间/五行预判/辅助及页面切换由管理员按§11.4验收 |

模块级例外白名单：**无新增规则例外**。保留已验收产品的显式本地能力及条件预判，不将通用“无主观预测”误解为禁止本已获准的下一根条件范围。没有变更坐标/视觉体系、源字段合同或三工程共享契约，不修改Foundation/DG生产者。

交付逐条记录硬口径→实际代码→测试/真实证据及执行人。只有前三项必需回归/构建/API及规定对照均通过、独立审计符合要求后，才记录“前三项完成，真实页面待管理员验收”；失败/不可比较/未执行项按实际停点与证据限制列出，不自动升级为前三项通过，不自动开始页面或声称整个需求通过。管理员明确反馈页面通过后，再对账本表、记录其反馈与证据范围并收尾本需求及认可文档；不自动提交、部署或扩大研究。

## 13. 审计记录、第1步执行结果及状态

编码设计已依据当前代码与CodeGraph核API、Universe、query/source、缓存、核心/恢复、预测、TS/page/controller/debug及直接消费者。第1步先提交统计设计，再执行来源计数，当时没有读取行情值或修改产品代码；第2步实现记录见§13.3。方案与本LLD对应为：方案§1—2→本§1—2；§3→本§5/10；§4—5→本§3—8；§6→本§9；§7→本§11—12；§8→本§2/10—11。

已核对signals规范代码、两类缓存各自发布时序、配置实例缓存事实、主图周期不重启五行预测及m30夹具下一根时点。正常EMPTY的page-init身份字段已核对真实生产者/schema/既有测试，原已设计的身份检查不把正常空行情误判为串码。

初次扩展在编码前完成了日线1条和分钟两类各1条计数查询，统计及预算见§13.1。新DG覆盖证据见§10，当前开发及验收用T37—T42和§11.3。两类统计的结论限日期覆盖或数量，真实API的功能及性能另行核对。

### 13.1 第1步执行对账（2026-11-04）

执行前已核现Settings解析、正式首页名单和计数字段合同；临时脚本独立复核未发现额外来源查询、明细读取或写入。分组摘要9/10/11对预期10的差额分别为-1/0/+1，按独立字面值检查通过。临时调用复用现Python、psycopg、DuckDB，不安装依赖、不改产品配置。

| 执行要求 | 实际结果 |
|---|---|
| 当前Web日线目标、只读事务 | `.env.web.local`经现get_settings解析；远程`152.136.*.251:5432/goldenshare`，连接默认只读，事务REPEATABLE READ READ ONLY，最后ROLLBACK/关闭；未切源 |
| 日线1条聚合SELECT | 两张获准表、九码，窗口2026-10-21至11-03，开市日数10；返回9组，每组实际10/预期10/差额0，合计90；BEGIN、SET LOCAL、ROLLBACK另计3条 |
| 分钟两类各1条聚合SELECT | 正式`/Volumes/datasource/data_lake`，按当时指定的2026-10-30、11-02、11-03三日、四周期及两类24路径；每类返回36组，未glob或逐文件查询 |
| 分钟实际/预期及两类差额 | 九码每码bars、indicators均为m30=24、m60=12、m90=9、m120=6；各类459、两类918；72个实际/预期分组差额和36个bars-indicators差额全部0；完整代码计数表见方案§11 |
| 日线40秒工作/50秒全程 | 连接0.093秒、SELECT 1.580秒；worker至关闭/摘要2.215秒，全程至退出2.304秒；无超时/重试 |
| 分钟10秒工作/15秒全程 | bars计数1.341秒、indicators计数0.013秒；worker至关闭/摘要1.592秒，全程至退出1.679秒；无超时/重试 |
| 范围、读写及停点 | 仅3条来源计数SELECT，应用只收到分组摘要；未读价格、DIF或时间键明细，未额外运行识别/预测/校准，未写DB/Lake、未改产品代码；到第1步完成停止 |

已独立复核保存的分组统计及执行记录，代码、日期、根数、差额、查询数和预算均符合当时已确认的统计口径。第1步数量吻合，满足第2步来源数量前置条件；不宣称指标质量、唯一性、时间位置、算法结果或产品4秒/400ms通过。临时脚本及统计摘要仅在`/private/tmp`，正式结论保留本节和方案§11，不生成reports过程附件。下一步为§2第2步编码，本轮未启动。

### 13.2 第2步开工条件补齐及独立审计

本轮只修改方案和本LLD：第2步限定Python后端/工具及调用测试，第3步同步TS客户端、mjs及五组客户端集成测试；第4步按完整节点清单对账，复用仍适用的通过结果，不强制重跑或重复计数。已分别独立复核工具/测试交接和数字依据，未发现本次修正引入提前迁TS、漏测、步骤冲突或预算冒充。T01—T36、r4核心规则、实际来源范围及产品现有限额保持。

文档完整性、两文档本地链接/代码围栏、case编号、五组客户端测试函数位置和限定差异检查通过；未查询来源、运行测试、修改业务代码或提交。第1步数量前置、后端编码设计、调用方/测试交接及工作区相关路径已具备第2步条件。后续第4大步按§2.1分工，本轮不设额外整组总等待阈值，API实际卡住时按§11.3.5定位和汇报。本轮到文档修正和审计结束。

### 13.3 第2步实现、测试及独立审计（2026-11-05）

本步只实施§2第2步。已按开工硬口径复核API→Universe→query/source→calculator→DTO及Python调用链；开发后独立审计当前差异，不以测试数量代替实现核对。

#### 13.3.1 硬口径与实际落点

以下路径在`src/biz`下时省略该前缀；测试文件在本节表中列清。

| 硬口径/Case | 实际代码 | 已验证内容及边界 |
|---|---|---|
| 唯一产品准入、规范code必填；T01—T05 | `queries/wealth/market/index_detail_xxm/query_service.py::require_xxm_code/build/load_entry`；两个`api/wealth/market/index_detail_xxm*.py` | 查询4秒计时内先核名单，之后才context/cache/read；现Universe一次准入，北证及名单外404、格式400、配置500。识别trim/upper和预测严格格式分别保留；直接Python调用无产品默认上证 |
| 核心/DTO只扩身份和五周期；T12/T13/T19/T32 | `services/wealth/market/index_detail_xxm/{types,calculator}.py`；`schemas/wealth/market/index_detail_xxm*.py` | 核心只改构造准入/period类型，DTO严格规范代码，不读配置；原业务方法、Spec/hash/ID/snapshot格式不变。跨code及m30/m60恢复拒绝且原状态不变，m30恢复/历史/clone通过 |
| 实际来源绑定；T08—T10/T15 | `queries/wealth/market/index_detail_xxm/source.py::{read_daily,minute_request,read_minutes}`及query `_load_series` | SQL过滤当前code；分钟签名发现和pair请求同code/freq/window；保持N+1000及短历史、不补值/重算MACD、不遍历其他指数，不改Foundation读取器 |
| m30端点及下一根；T05/T14—T16 | `source.py::ENDPOINTS`及其现窗口/完成/下一根消费者 | 八端点、11:30→13:30、15:00/周末→下开市日10:00、历史asOf及非法/未完成输入；默认/最大规划沿189/376开市日，非实际文件读取次数 |
| series/共享加载身份与淘汰；T20—T23/T33 | `query_service.py::load_entry/_load_series/_check_entry_identity/_response` | key尾部加code、period保留原位置；旧缓存取出后立即核code/period/Spec，之后才能复用或重算。相同/不同源值的错绑都拒绝且不覆盖；同输入跨code、flight成功/失败、17项共用容量及淘汰重算通过 |
| 预测身份、非空路径及发布；T11/T17/T18/T20—T24/T33 | `forecast_query_service.py::build/_assemble`；`forecast_expression.comparison_envelope`；`forecast_text.make_display` | 实际code进入普通/debug全部分支和forecast key；命中先核code/period/版本/hash。保持装配/投影/编码/大小检查→退出load_entry→最后检查→原子发布，取消继续传播。m30普通候选、旧结构价格/颜色条件、独立Decimal校准、249/250及扰动通过 |
| Python工具/直接调用迁移；T19/T24/T32 | `scripts/research/index_market/xxm/daily_window_precheck.py`及当前透明包装/直接测试 | 预检load包装显式接收并转发code/window；原透明`*args/**kwargs`包装无需改实现，以专门用例证明参数只转发一次。恢复/历史查询及工具Python节点通过 |
| 普通/debug及本地/生产；T06/T07/T24 | 现投影模块保持；`tests/web/test_wealth_index_detail_xxm*.py` | 五周期两方向非上证普通/debug公共事实一致，既有辅助字段投影不变；prod App十码五周期不注册r4路由。T07前端无请求/辅助import仍归第3—4步，本步不冒充完成 |

相同输入内容的跨code样本允许sourceInputId相同，用现身份及key隔离计算状态，不改指纹公式。已确认`MAIN_SPEC`、`FORECAST_SPEC`、runtime、mjs没有本步改动；calculator构造以外的方法AST与开工基线一致，其他算法文件只增加m30准入。API公开字段集合及原上证四周期HTTP请求保持，不新增接口、配置、依赖或版本。

#### 13.3.2 限定回归结果

测试均使用现`.venv`，禁字节码及pytest缓存，`--basetemp`和日志摘要在`/private/tmp/r4-index-expansion-step2-7IU911`。C组和部分D组走实际路由、Universe/query/source/calculator/DTO，真实DB由隔离SQLite替代，Lake内容由正式合同下的临时Gold人工样本替代；没有读取远程/正式Lake行情、调用真实45组合或运行冻结回放。鉴权和生产路由边界沿原测试覆盖。该结果为隔离集成及人工规则回归，不是第4步真实来源/性能结论。

下表A/B/D文件均位于`scripts/research/index_market/tests/`，C位于`tests/web/`，F位于`tests/architecture/`。耗时单位秒，为外层临时调用从启动子进程前到进程退出且日志摘要写完的实测；不代表单次产品计算耗时。

| 组 | 文件/明确执行范围 | 最终通过项 | 调用耗时（秒） |
|---|---|---:|---:|
| A | test_xxm_calculator.py | 50 | 0.372 |
| A | test_xxm_r4_rules.py | 504 | 0.842 |
| A | test_xxm_r4_following.py | 435 | 6.478 |
| A | test_xxm_r4_restore.py | 239 | 0.897 |
| A | test_xxm_snapshot_validation.py | 249 | 1.244 |
| A | test_xxm_input_validation.py | 107 | 0.224 |
| A | test_xxm_product_v1_cases.py | 16 | 0.144 |
| A | test_xxm_index_expansion_dto.py | 252 | 0.358 |
| B | test_xxm_key_point_forecast.py | 82 | 1.545 |
| B | test_xxm_p3_forecast_math.py（最终补齐m30/249/250后） | 58 | 0.231 |
| B | test_xxm_forecast_expression_contract.py | 82 | 0.273 |
| B | test_xxm_r4_following_forecast.py（最终补齐m30旧结构后） | 99 | 1.595 |
| B | test_xxm_forecast_display.py | 16 | 0.213 |
| C | test_wealth_index_detail_xxm_api.py（先原范围，后新增投影10项，节点不重复） | 256+10=266 | 29.863+1.509 |
| C | test_wealth_index_detail_xxm_forecast_api.py（夹具修正后完整重跑） | 209 | 10.738 |
| C | test_wealth_index_detail_xxm_forecast_validation.py | 59 | 5.137 |
| C | test_wealth_index_detail_xxm_local_routes.py（最终生产矩阵） | 14 | 7.439 |
| C | test_xxm_shared_loads.py | 5 | 1.472 |
| D | test_xxm_snapshot_consumers.py | 22 | 1.196 |
| D | test_xxm_r4_internal_results.py | 39 | 0.721 |
| D | test_xxm_r4_following_query.py | 27 | 0.725 |
| D | test_xxm_saved_minute_window.py | 41 | 0.168 |
| D | test_xxm_daily_window_precheck.py | 12 | 3.881 |
| D | test_xxm_p4_audit_tools.py（37个明确函数节点，排除§11.2五组TS客户端函数） | 138 | 1.412 |
| F | test_subsystem_dependency_matrix.py | 4 | 1.253 |
| F | test_platform_legacy_guardrails.py | 3 | 2.691 |
| F | test_operations_legacy_guardrails.py | 9 | 9.032 |

最终有效**28个执行单元、3037项全部通过**：A1852+B337+C553+D279=3021，F16。上表调用耗时按未四舍五入记录相加为91.654265秒；包括被替代的首轮/中间轮在内，32次实际调用累计111.644244秒。这里累计的是多次测试调用实耗，不是连续墙钟时间、完整开发总时长或产品性能预算。pytest标准警告为现httpx/FastAPI旧用法提示，没有安装/升级依赖处理它。

**测试计时记录限制：**§11.2要求分别记录准备/导入收集、执行、关闭退出、摘要和最后核验；实际仅保留pytest报告总耗时与上述外层调用实耗，未独立采集各阶段，也未单独计时调用前准备和最后独立核验。因此这项记录粒度要求没有完整落实，不将两种时间相减冒充某阶段，不宣称已获得完整分阶段成本或真实产品4秒/400ms通过。该限制不改变测试断言/退出及数量证据，不为补时间拆分而重跑已经完整通过且依赖未变的单元。后续执行仍按§11.2准备记录，不把本次限制改写成已满足原要求。

#### 13.3.3 独立复核、问题处理和交接

1. 开发后独立审计发现：若只在共享加载返回/响应装配核身份，错绑旧缓存遇源值变化时可能先重算覆盖。已先在§6、T23和方案§5.2补清原身份要求，再复用`_check_entry_identity`于日线/分钟缓存取出后，早于源修订判断。相同/不同输入两种回归都证明拒绝且旧缓存对象保留；未新增源码SHA检查或重放算法核验。
2. 首轮forecast API出现1项失败、207项通过（调用10.497秒）：新m30夹具在10:30后立即请求，却按当日完成日作预期，忽略现20点切换；又需覆盖A500真实起点。已核当前context规则和正式起点，将模拟区间置于2025-10-09之后，显式历史asOf=10:30、now=当日21:00，保留完成10:30/下一根11:00和独立Decimal预期。没有改产品/断言迎合错误。该文件完整重跑209通过，首轮207不再加到最终通过数。
3. 最终独立复核补齐T17旧结构预测和T18校准边界：原四周期字面价格/颜色样本增加m30；独立高精度Decimal历史保留原1500根断言，并检查前249/250根、250末根DIF扰动，使用合法15:00端点。只重跑这两个受影响文件，最终99/58通过取代旧93/57；不重复计算通过数。生产路由矩阵补全十码五周期后，最终14项取代旧14项（原调用7.734秒）。
4. CodeGraph explore/search/impact/callers覆盖API/Universe、query/source/cache、core/schema/forecast、Python工具及测试消费者；图谱模糊处回到当前源码核实，最终sync/status显示索引正常。临时AST导入检查核22个计算/查询模块，没有引入scripts/research、reports、App或QTF；三份架构护栏通过。源码差异核算法、Spec/hash及既有编号/发布顺序，未发现剩余第2步业务偏差。文档、链接和限定差异检查完成；这些检查不代替第4步真实验收。
5. `xxm_page_request_audit.mjs`、`_node_fixture_prelude`及§11.2五组TS客户端函数与本步开工前一致；D组只执行其余37个函数的138项参数化用例。它们的具体nodeid仅保存临时执行清单，正式归属见§11.2，不把跳过的五组登记为通过。没有改前端客户端、页面或首页；工作区其他修改保持，不纳入本次审计结论。

**交接：第2步功能实现、限定回归与独立代码审计完成，测试计时记录限制如上。**第3步前端的后续实施和交付已记录在§14；第4大步的第1—3项由Codex负责，第4项页面由管理员负责，按§2.1/11执行，本轮不设额外整组总等待阈值。开发阶段未自动提交，随后获准提交及复核见§13.4；未执行前端typecheck/test/build、真实DB/Lake API验收、安装、推送、部署或业务写入。本需求整体尚未验收收尾。

### 13.4 第2步提交后独立审计（2026-11-05）

按管理员要求，先在当前`dev-interface`提交`3a2929b83`，再独立对照方案及本LLD审计当前代码。提交34个文件；根`docs/README.md`只暂存本需求两行索引变化，其他需求改动保留；没有推送或部署。

已分别核对：核心/DTO/恢复及预测数学，API/Universe/来源/缓存/发布顺序，以及全部Python调用者/工具和第3步交接。使用CodeGraph explore/impact/callers/node追影响面，模糊名称命中回到当前源码及静态调用检查；没有把交付记录或测试数量作为代码正确的依据。

- 九码五周期、北证拒绝及异常转换符合§3；实际code进入SQL、分钟signature/pair、计算器、cache key及所有响应分支。相同输入跨码仍分开，旧缓存先核身份再判断修订；series与forecast分别保留原发布顺序。
- 核心仅扩规范代码和m30准入，Spec/hash、业务规则、EMA、指纹/编号、snapshot/restore算法保持。非空候选、旧结构价格/颜色、同根显隐、249/250根校准与扰动、恢复隔离有独立预期覆盖。部分原RC/PF大矩阵仍只覆盖原四周期，不宣称全部旧金样本均已增加m30。
- 必填ts_code的九个目标签名与全部已跟踪Python调用方匹配；透明包装原样转发。没有改TS/mjs、五组客户端测试及prelude、App装配、Foundation或DG；原上证TS/mjs调用仍匹配，新增页面范围未提前开放。
- 保存的28个有效单元与3037项通过、四个被替代结果及§13.3数量/耗时一致。p4工具选中37个函数、138项，恰好排除第3步五组TS函数。原证据涉及的实现和输入未变，本轮未重跑测试、读取真实来源或扩大验收。§13.3.2的测试计时粒度不足继续保留，不冒充真实来源/性能结论。

**结论：未发现第2步剩余业务实现偏差、漏迁或错改，功能实现符合方案及本LLD的第2步要求。**该轮只补回提交/审计事实，不修改业务代码。第3步前端实施另见§14；当前第4大步分工/交接统一按§2.1，API按§11.3.5记录进展、定位实际卡住情况。文档完整性及限定差异检查通过。

## 14. 第3步前端实现、限定回归及独立审计（2026-11-05）

本步在重读根、wealth、scripts/research规则及适用基线后，复核第2步后端合同、最新§8和T27空响应顺序，按第3步获准范围实施。只改前端身份/周期消费、对应测试及既有mjs调用，不修改后端、数据来源、配置、r4规则或预算。测试使用现环境，没有安装、启动/重启服务或读取真实DB/Lake。

### 14.1 硬口径、代码及测试对账

下表前端路径位于`wealth/src/features/index-detail/`，Page位于`wealth/src/pages/index-detail/`。

| 要求 | 实际落地 | 测试/审计 |
|---|---|---|
| T27当前页面身份及空数据 | `controller/useIndexDetailController.ts`两处先isCurrent、再核code、最后EMPTY；`model/indexRecognitionAvailability.ts`和Page按hasData及当前viewModel身份传validatedTsCode | controller新增6项；Page覆盖同码/错码EMPTY共4项、pending及九码正向；availability覆盖九码/生产、未验证/错码及北证，不复制产品名单 |
| T14/T24/T25五周期识别 | `xxm/{types,adapter,useIndexXxmLayer}.ts`加入m30、移除仅上证限制；timeKey明确四种分钟端点，仍核expected code/period/版本/hash及图表close/DIF/DEA/hist | 非空普通/debug五周期、9×5 Hook、八端点及反例；保留原primitive/marker及数值对齐，未改两个ChartWorkspace传参 |
| T25完整预测代码传递 | `xxm-forecast/{types,apiClient,adapter,useXxmForecast}.ts`、全部调用/fixture及debug测试显式使用tsCode；Card沿原数组生成五行 | 非上证m30普通/debug实际client URL、错code/period/asOf拒绝；next endpoint用独立字面值；不留旧签名或默认上证 |
| T26五行及单行行为 | 现FORECAST_PERIODS依day/m30/m60/m90/m120；分钟关闭只请求day；Card、样式和状态模型保持 | 激活后五行、m30独立失败/重试、其他行保留、m30 READY普通/debug后端文案及本行计算依据 |
| T28取消及迟到结果 | 原requestKey、abort/generation/owner及预测身份保持，主图activePeriod未加入预测身份 | code/date/debug切换的旧成功/失败、退出取消及可见性/刷新；Page切主图仍传同一预测资格/参数，Hook依赖经源码审计，不据Hook pending宣称真实并发 |
| T29调度和5秒起点 | 调度器实现未改；API client仍在调度实际执行时建立截止 | 用真实scheduler和五个真实forecast client，只替代HTTP、普通任务和测试时钟；证明轻请求最多2、r4独占、排队不消耗执行5秒。不是实测排队耗时或真实性能结果 |
| T30/T31辅助/研究边界 | `debug/IndexRecognitionDebug.tsx`仅上证day挂载研究；r4 decoder/render仍供其他获准范围，普通页沿原动态加载 | 非上证/分钟不挂研究及切出取消；debug按需、普通依赖边界、生产关闭；独立daily-wave Hook/client原回归通过 |
| 工具同批迁移 | `xxm_page_request_audit.mjs`给forecast增加000001.SH首参；`test_xxm_p4_audit_tools.py::_node_fixture_prelude`显式传两类fixture代码 | §11.2五组实际TS客户端节点37项通过，原工具标的/周期/预算不扩；Python包装和D组方法不改 |

产品tsCode只由当前页面已核身份传入，前端不另建九码运行名单。事件显示、颜色、版本/hash、来源指纹及判断规则不变；业务源码改动仅限§8列清的接入位置。原`IndexInfoRail.tsx`、页面CSS与开工前内容一致，Page测试原有其他需求的11行断言保留，未覆盖他人修改。

### 14.2 限定执行结果及成本

本轮使用现有Vitest/TypeScript及Python环境。前端按文件运行`vitest run --no-cache --configLoader runner --bail=1`，类型检查使用`npm --prefix wealth run typecheck`；工具使用pytest首错退出、禁缓存/字节码，basetemp位于本任务`/private/tmp/r4-index-expansion-step3.Z6Dsrn`。各单元摘要、日志、测试结果及临时计时调用只在该目录，不写reports或工程临时目录。

测试边界分别为：Page接线测试替代图表、预测Hook或debug loader；Hook测试替代API client；真实client测试替代HTTP；调度测试保留真实scheduler/client；工具五组使用原人工输入/替身传输，实际加载TS/mjs。没有以这些替代层宣称真实行情接入、实际浏览器展示或4秒/400ms性能已验收。

| 单元（前端路径相对`wealth/src`） | 通过项 | 至摘要/核验完成（秒） |
|---|---:|---:|
| features/index-detail/model/indexRecognitionAvailability.test.ts | 19 | 1.110 |
| features/index-detail/controller/useIndexDetailController.test.tsx | 6 | 1.278 |
| pages/index-detail/IndexDetailPage.test.tsx | 50 | 2.492 |
| features/index-detail/xxm/adapter.test.tsx | 23 | 0.927 |
| features/index-detail/xxm/apiClient.test.ts | 11 | 0.874 |
| features/index-detail/xxm/useIndexXxmLayer.test.tsx | 59 | 4.082 |
| features/index-detail/xxm/rearmContract.test.tsx | 1 | 0.716 |
| features/index-detail/xxm/markerGeometry.test.ts | 10 | 0.860 |
| features/index-detail/xxm-forecast/apiClient.test.ts | 14 | 1.377 |
| features/index-detail/xxm-forecast/identity.test.tsx | 3 | 0.770 |
| features/index-detail/xxm-forecast/forecast.test.tsx | 19 | 1.290 |
| features/index-detail/xxm-forecast/r1Contract.test.tsx | 7 | 0.873 |
| features/index-detail/xxm-forecast/expressionContract.test.ts | 2 | 0.789 |
| features/index-detail/debug/xxmDebugContract.test.ts | 9 | 0.992 |
| features/index-detail/debug/forecastDebugContract.test.ts | 52 | 0.764 |
| features/index-detail/debug/IndexRecognitionDebug.test.tsx | 14 | 1.359 |
| features/index-detail/debug/useIndexDebugModule.test.tsx | 5 | 1.010 |
| features/index-detail/debug/dependencyBoundary.test.ts | 4 | 0.966 |
| features/index-detail/api/indexDetailRequestScheduler.test.ts | 4 | 0.715 |
| features/index-detail/daily-wave/useDailyWaveReview.test.tsx | 21 | 0.840 |
| features/index-detail/daily-wave/apiClient.test.ts | 9 | 0.759 |
| scripts/research/index_market/tests/test_xxm_p4_audit_tools.py的五组TS客户端节点 | 37 | 6.072 |
| 最终typecheck | 通过，不计测试项 | 4.771 |

最终**21个Vitest文件342项＋工具37项＝379项全部通过**；最终typecheck通过。以上23个有效执行单元原始计时累计35.684713秒，包括被替代的两个类型检查单元共25次调用累计45.138337秒。类型检查、测试项及实际调用次数分开统计，不重复累计被替代结果，不将累计时间说成单次API耗时或完整开发墙钟时间。

本轮临时记录分别采集调用准备、导入/收集、实际测试、退出、摘要解析和最后数量/退出核对；前端测试生命周期按[Vitest 3.2.4 reporter合同](https://github.com/vitest-dev/vitest/blob/v3.2.4/docs/advanced/api/reporters.md)核对，pytest沿现session/collection/sessionfinish回调，均不修改仓库测试配置。最终有效单元中，测试导入/收集累计16.665秒、执行至报告累计12.440秒、退出累计1.797秒；类型检查进程含载入/关闭的4.770秒单列，不虚构它的测试收集阶段。准备、摘要及核验的单元记录一并保留；表内总时间截止最后核验，不包含后续文档编写和独立人工审计。记录精度与范围如实保留，不用其推导真实请求预算或性能保证。

首轮typecheck在4.729秒后报告新人工夹具的Time包含BusinessDay，超出实际图表时间合同；已只将夹具返回时间收窄为string/UTCTimestamp，没有放宽生产类型或断言。修正后typecheck通过；随后为独立审计补齐A500日期及m30卡片测试，再执行最终typecheck，结果通过。受影响单元使用独立名称保留各轮记录，未继续执行失败单元之后的测试来掩盖错误。

### 14.3 独立审计与证据复用

开发后分别独立核对预测客户端/解码/五行与调度、识别/页面身份/研究边界、工具消费者及测试依赖。已关闭以下发现：

1. EMPTY页面的“不启用r4”原有分层断言不足以直接验证Page接线；已按T27补4项真实controller＋替身Hook/loader的页面断言，正常empty不误拦、错码empty进入error，两者均不启用r4。
2. m30原卡片测试只验证失败/重试；已补正常/debug READY文案及本行依据2项，不改生产展示逻辑。
3. A500的9×5 Hook人工样本原用2023日期，早于正式来源起点；只将A500日期映射到2025-11-04至11-13的独立合法日期。分钟端点、相对顺序、原段3根及下一同色2根、业务数值/关联保持，默认上证day原事实不变；Hook用字面日期断言实际采用起点后样本。

核CodeGraph explore/impact/callers及当前源码/静态调用，未发现漏迁、新增兼容签名或第3步剩余业务实现偏差。图谱模糊命中回到明确路径核实，批量修改后sync/status正常。后端r4核心/查询/schema/API、Spec/hash、Foundation/DG和原调度器无本轮改动；依赖边界测试及限定差异检查通过。

原第2步3037项中未受影响的结果保留，不计入本轮379项。其中P4 D组138项并非仅凭函数体未变而复用：已核42个测试函数只改共享prelude，只有E组五函数会调用它；D组进程用自有Python字符串/node -e或替换_run_node，不加载变化的产品mjs/TS fixture。相应Python工具与后端依赖未变，因此D组138项仍适用；本轮新执行E组37项，两组不重计。完整文件节点仍由第4步按§11.2对账。

**第3步交接时的结论：代码、限定回归及独立审计符合本LLD，当时停在第4步之前。**该步没有执行完整前端回归、构建、45组合真实API、真实页面或真实性能验收。第4步责任按§2.1：Codex完成准备/自动回归/API前三项，管理员做第4项页面；不设额外整组等待阈值，不得以本步人工样本代替真实结果。第3步开发阶段未自动提交，也未推送、安装、部署、切源、读真实行情或写数据库/Lake；后续实际执行及当前停点见§17。

### 14.4 提交后的独立审计（2026-11-05）

按管理员要求提交`def22627a`，共34个文件。复核提交清单及暂存内容：根`docs/README.md`只包含本需求两行更新；Page测试只包含P4相关改动，原有其他需求11行断言、`IndexInfoRail.tsx`及页面CSS保持未提交。没有推送或更改其他任务内容。

提交后按§8及T24—T31重新分别审计当前代码、调用方和测试：

- 页面两接口均按isCurrent→代码身份→EMPTY执行；只有当前非空页面身份通过才启用r4，北证及生产仍关闭。
- 五周期识别使用实际代码/周期，m30八端点明确，图表四值绑定及迟到结果隔离保留；r4辅助与仅上证日线手动研究的边界没有扩大。
- forecast必填代码从Page、Hook、client贯穿URL和adapter，TS及mjs调用迁移完整；五行、分钟关闭、单行重试、刷新/可见性/取消保持，主图周期不进入五行预测身份。
- 调度器源码未改；普通轻请求最多2个，r4独占，5秒截止仍从调度实际执行开始。核对测试使用的真实scheduler/client，未把Hook的五个待处理请求误作网络并发证据。
- 对照21份Vitest原始结果及工具、类型检查记录，342＋37＝379项、23个有效单元及25次实际调用的统计与§14.2一致。核工具五组客户端及原D组依赖，未发现遗漏调用或复用已失效证据；未用人工样本宣称真实接入或性能通过。

**结论：未发现第3步剩余业务实现偏差、漏改或错改，符合本方案及LLD的第3步要求。**该次只补提交/审计事实，不改业务代码，不重跑已通过且依赖未变的测试，不进入第4步。CodeGraph explore/callers/impact/status及代码核对覆盖Page、识别/预测Hook、客户端、图表消费者和工具；图谱未列出的动态mjs调用已用源码补核。该次审计时第4大步尚未开始；后续实际执行见§17。Codex的前三项结果和管理员页面反馈分别登记，不能把本审计扩大为整体需求验收结论。

## 15. 第4大步执行设计及独立审计（2026-11-05）

本节保存执行前的设计审计记录；后续实际执行及当前停点见§17。

本轮按管理员最终分工补齐§2.1和§11.2.1—11.4：Codex负责内部第1准备、第2自动回归/构建、第3真实API/debug/后端性能，管理员负责第4真实页面。当前只编文档，不编写临时API脚本或执行任何业务/测试单元；源码、配置、实际来源及原预算保持。

静态核对覆盖当前package/tsconfig/vite配置、App本地r4装配、Web只读Session、query/source/cache、预测计算截止、两类投影、旧工具的观察和compare_modes；使用CodeGraph explore补查比较方法并回到具体源码核实。当前FastAPI/TestClient及Vitest/Vite用法结合已安装实现和官方资料核对，没有运行服务、测试、CLI构建、DB/Lake查询或旧核验工具。

独立审计已关闭以下文档问题：

1. 类型检查复用须覆盖整个wealth的TypeScript输入、配置和依赖，不能只看本需求文件；不确定就按原命令检查一次，不加源码SHA或新跟踪系统。
2. 真实API先完成设计及静态审计，再按设计准备临时程序并复核、正式执行；记录阶段进展，异常卡住时先停后续和汇报，不另设整组等待数值前置，也不出现“先有最终程序才允许设计程序”的循环。
3. 观察使用len(entry.raw)、len(entry.processed)、entry.calculator.source_identity等真实属性，不误用len(entry)，不将已计算长度当历史asOf前缀长度；不额外读源或遍历前缀。
4. 每组合2/4请求同App/Engine/Cache连续完成，实际启动/连接/清理成本分开；真实API不冒充TS客户端5秒端到端验收，也不声称验证跨组合热缓存或淘汰。
5. 自动回归/构建/API及规定比较均通过后，才能登记前三项完成；失败/未执行/not_comparable按实际停点报告，不能无条件转为“前三项通过、待页面”。第4项和整体验收由管理员明确反馈后再记录。

当前分工、先后依赖及代码落点清楚。管理员已决定本轮暂不设置额外整组总等待阈值，**新增等待秒数不再是第3项的执行前置。**前三项按§2.1/11的既定顺序进行，原产品预算保持；实际卡住时先定位、停后续并汇报。当前只完善文档和审计，不登记第4大步已经执行或通过。

## 16. 不设额外整组等待阈值的同步及就绪审计（2026-11-05）

本节保存开工前审计；后续实际执行和当前停点以§17为准。

管理员决定本轮暂不设置额外整组总等待阈值，真正卡住时先判断定位、汇报讨论。已清除§2/2.1/11.3/12及各阶段未来交接中的“先核定完整等待值才能执行API”等前置，§11.3.5改为阶段进展、异常中断、首错停止和完整组合续跑；没有为取消阈值另建心跳、固定轮询、信号或进程监督系统。原4秒/400ms/TS5秒、已有测试/驱动超时和§10/13.1来源统计50/15秒历史保持。

就绪审计核当前代码、配置及既有文件，未运行测试/业务CLI、连接数据库、读取Lake行情或探测服务：

- 当前dev-interface新增其他任务提交4f7253487，变化在独立technical_indicators内核和共用Settings；r4仍走IndexFactorPro及MajorIndexMinsLakeReader，不调用该内核。r4的2000行上限、N+1000、原算法/版本/hash和产品预算未改，没有被该内核500行限制替换。
- 共用Settings确有变化，第2项已明确补跑tests/web/test_wealth_index_detail_xxm_local_routes.py核当前local/prod装配；其他核心/数学及未受影响消费证据继续按依赖清单复用，不能把旧3037项全部当作未变。当前Web配置未发现旧内核输出上限覆盖引发的拒绝问题，不更改该配置。
- 现Python及所需包文件、Vitest/Vite/TypeScript、本次Web配置和两批原始测试证据在位；APP_ENV为显式local、分钟能力开启。正式Lake根及两类分钟Gold目录存在，只核目录存在，不读分区/行情。前三项使用隔离回归及进程内App，不依赖Web/Vite监听服务已启动。
- 真实DB/Lake连通和原性能预算仍由第3项规定请求核验；本次静态条件核实不能被写成真实功能/性能通过。完整前端回归仍包含范围外日期TODO，遇到实际失败如实停止并报告，不提前假定通过，也不把尚未执行的测试当当前阻塞。

**结论：没有发现新增开工阻塞，具备按§2.1执行前三项的条件。**先完成第1项设计、环境及证据准备，再完成第2项规定自动回归/构建；第2项通过后，准备临时API程序并完成静态复核，再进入第3项执行。不跳过依赖、不自动运行管理员第4项页面。本轮只修文档和做只读审计，没有运行功能测试、构建、真实API或页面，未提交/推送/部署。

## 17. 第4大步原Prod链路执行记录（2026-11-05）

本节记录切源前的实际执行及诊断，当前续验入口见§11.3。

### 17.1 准备及执行约束对账

管理员授权按方案/LLD推进后，重读适用AGENTS、基线、§11—12及当前代码。当前仍为dev-interface、HEAD 4f7253487；任务目录为`/private/tmp/r4-index-expansion-step4.e3vdmlur`，包含执行前工作区记录、临时调用、各单元日志/JSON及临时构建。没有修改业务、测试、配置或锁文件，没有安装、启动/重启服务、切源、业务写入、推送或部署；其他任务的原有修改保持。

旧证据逐文件/节点复核：第2步28个有效单元3037项、第3步23个有效单元379项均有原始退出0记录；P4工具42个函数由D组37函数138项、E组5函数37项覆盖，函数集合无交叉、漏项或失效名称。共用Settings变化用本次完整local_routes补跑替换旧装配证据；其他依赖未变结果复用。前端原3处dirty与第3步保存输入一致；仍按本节执行完整前端，类型检查本次也重新执行，不重复累计旧通过项。

CodeGraph explore和当前代码覆盖原App装配、query/load_entry、forecast、投影、缓存及旧compare_modes；FastAPI的TestClient/yield清理用法已核Context7及当前实现。临时API程序在第2项通过后才编写，独立静态审计后才执行：同组合只装配一次App/Engine/原XxmCache，观察方法只调用原方法一次；不调用旧isolated_app/_observe、不增加前缀遍历、来源核验、预热或重算。每Session首条为SET TRANSACTION READ ONLY，鉴权只在该App中提供测试身份，不运行完整Web lifespan。

临时程序静态复核先修正两项再执行：Session回滚失败也必须finally关闭，client/Session检查/Engine清理分别完成且Engine.dispose不能被前一清理失败跳过；forecast直接核响应requestedAsOf/mode与实际请求，不能只相信观察记录中从参数抄入的值。阶段日志保留自有PID。未修改产品实现或另建监督框架。

### 17.2 第2项自动回归及构建

全部沿§11.2.1命令，pytest追加沿用的临时阶段记录插件，Vitest追加沿用的临时reporter，只记时间，不改输入、断言、筛选、超时或快照。过程文件全部在本任务目录；无统一总等待阈值。

| 单元 | 实际结果 | 进程耗时（秒） | 准备至摘要/退出核验（秒） | 原始证据 |
|---|---|---:|---:|---|
| 现有local_routes完整文件 | 14通过、0失败；隔离SQLite及测试环境 | 7.377486 | 7.377997 | local-routes.log/json/phases.json |
| wealth类型检查 | 退出0 | 4.880257 | 4.880677 | typecheck.log/json |
| wealth完整前端，无筛选 | 187文件、1615项全部通过，失败/跳过/TODO均0 | 18.535614 | 18.538840 | frontend-all.log/json/vitest.json/phases.json |
| Vite临时目录构建 | 退出0 | 1.530904 | 1.531294 | build.log/json、wealth-dist |

构建后读取临时index.html，沿/wealth/前缀定位到本次产物，2个实际引用JS/CSS均存在；该最后引用核验另计0.002976秒，记录在build-verified.json。未运行裸tsc -b、preview或开发服务。旧342项与本次完整1615项重叠，不相加；旧工具175项覆盖单列，不据此声称真实行情验证通过。先前日期TODO本次未失败，结论限于本次完整运行，不顺手改其他模块。

pytest实际收集完成标记前1.055893秒，收集完成至sessionfinish 4.823125秒，之后退出1.498621秒。Vitest收集与执行并行：进程启动至首个模块收集标记1.390551秒，该标记至run结束17.041000秒，退出0.104449秒；中间阶段包含其余收集和执行，不能写成全量导入已经结束。typecheck/build未采内部阶段，进程时间含其载入和退出，不伪造拆分。准备、摘要解析和最后核验按各json保留；工具并行阶段报告不相加冒充墙钟时间。

**第1—2项完成。**本次回归未改变r4业务规则、版本/hash、前端及配置；隔离测试和构建不能代替第3项真实来源/API或第4项页面。

### 17.3 第3项真实API结果及性能停点

使用当前`.env.web.local`、显式local和现Web数据库，分钟使用正式`/Volumes/datasource/data_lake`。目标主机/库仅在脱敏临时摘要记录，不输出凭据。按首页配置顺序，截止2026-11-03；未追加探源/预热请求，也未强求某种信号或可用价格。

| 已启动组合 | 请求及结果 | 缓存输入/识别返回根数 | 原build最长（秒） | 预测计算最长（毫秒） | 状态/对照 |
|---|---|---|---:|---:|---|
| 000001.SH day | 4次HTTP200 | 4087/300 | 1.335040 | 17.078 | 预测NO_CANDIDATE、NO_ENTRY_RANGE；signals/forecast普通debug各1项equal |
| 000001.SH m30 | 4次HTTP200 | 1500/500 | 1.121745 | 55.624 | 预测READY、ROUNDING_BOUNDARY；两项equal；下一根11-04 10:00+08:00 |
| 000001.SH m60 | 2次HTTP200 | 1500/500 | 0.960592 | 51.091 | 预测READY、ROUNDING_BOUNDARY；下一根11-04 10:30+08:00 |
| 000001.SH m90 | 2次HTTP200 | 1500/500 | 1.039684 | 55.042 | 预测READY、ROUNDING_BOUNDARY；下一根11-04 11:00+08:00 |
| 000001.SH m120 | 2次HTTP200 | 1500/500 | 1.164312 | 92.696 | 预测READY、ROUNDING_BOUNDARY；下一根11-04 11:30+08:00 |
| 399001.SZ day | 首次普通signals HTTP503，XXM_BUDGET_EXCEEDED | 未正常返回，根数未知 | 19.821952 | 不适用 | API往返20.143539秒，read_daily阶段19.648430秒；预测未发出 |

原build和API往返分别记录，不能混称一次计算。预测计算从原400ms deadline建立时的真实perf_counter起，到原build结束；已通过的最长92.696ms，未进入计算阶段不补0冒充实测。上证最大API往返1.717113秒；全部成功请求的原build不超过4秒、预测计算不超过400ms，响应大小符合原上限。上证日线无价格条件，不能称有效点位预测通过。

同一上证日线组合4次请求均按产品原逻辑调用read_daily，正常完成每次返回4087；4个分钟组合各只有首次识别调用read_minutes一次，返回1500，后续同窗series命中；m30 debug预测还命中已有forecast。未让观察器额外读源，不把多次累计根数当独立K线或磁盘扫描量。缓存最大3,303,696字节、最多2项；本次每组合新缓存，不能宣称跨45组合的热缓存/淘汰实测通过。公共摘要只来自已投影响应，四项比较均equal，没有not_comparable。

深证失败只定位到原read_daily阶段，包含分页查询及行转换/校验；没有采每批SQL和处理分段，不能断言具体SQL等待、网络或处理各占多少、哪批慢，也不能从returnedRows=None推断0根。当前source.py::read_daily每轮按原1000根分页并在读取前check，阻塞SQL不受该4秒检查硬中断；可能等返回并处理后到下次check才报预算超限。这解释“4秒预算却在约20秒后返回503”的可能执行路径，未通过附加查询确认具体批次。未调用深证forecast，因此不是400ms预测失败，不因失败重试或改预算。

### 17.4 关闭、数量、独立审计及续跑

实际启动6个组合：**5个完成、1个失败、39个未执行；15次请求＝14成功＋1失败，原100次中85次未执行。**深证日线首次失败后父调用立即退出1，没有启动其预测或任何后续组合。4项代表普通/debug比较均通过；剩余3代表组合未执行，不能登记全部5组比较通过。

6个子进程均已退出，实际6个数据库连接，15个Session opened=closed；所有组合cleanup=closed，自有client/Engine已关闭，观察上下文退出。父调用累计至结果核验47.142043秒、子进程内部累计43.536606秒，前者包括子进程启动/退出及结果读取，均含失败单元；这些累计数不当作单次API耗时。原始api-parent.log、api-summary.json和每组合api-<code>-<period>.log/json保留在任务目录，未保存完整行情或全部响应。

独立只读审计核对原始结果、执行顺序、请求/组合数量、比较、4秒/400ms计时范围、读源包装和资源关闭：没有发现本次执行偏离LLD。第1—2项完成，但第3项性能失败，**禁止登记“前三项完成”或整体验收通过**。页面第4项未执行，仍由管理员负责。

该次首错后停止，未自动重试、追加请求、切源或改预算。深证单次复测、诊断和原链路续跑分别见§17.5—17.8。结果同步方案、LLD和两索引，未提交。

### 17.5 管理员指定的深证日线单组合复测（2026-11-05）

管理员要求“再测试一遍”，本次范围固定399001.SZ/day，不自动继续其他组合。复用§17原已审计的api_verify.py，先原样复制到本次新建/private/tmp目录，再以既有--worker 399001.SZ day入口执行；该入口本身完整执行本组合2请求，仍由原load_entry做正式Universe准入。不得调用默认parent入口重跑已通过上证或继续39组合，不改脚本业务/观察逻辑，不修改源码/测试/配置，不附加SQL、统计计数或预热。

进入条件为已有第2项自动回归/构建及5个上证组合的有效证据、原临时调用和当前r4代码未变，以及本次管理员明确的复测授权；原因尚未确定，此次运行用于检验原慢读取是否复现，不额外要求先证明根因。顺序保持普通xxm-signals（tsCode=399001.SZ、period=day、endDate=2026-11-03、limit=300）→成功后普通xxm-key-point-forecast（同code/period、asOf=2026-11-03），无debug、startDate或新参数。首错即退出，本次最多2请求。

采用新自有App/Engine/原XxmCache，Web env、只读Session、原路由/query/取数/投影/计时和finally关闭均按§11.3，不启动服务、换源或写正式数据。预算仍4秒/400ms，无额外整组总等待值。原失败日志和5个完整成功组合保留，新结果不覆盖旧文件；逐请求记录read_daily返回根数及耗时、缓存输入长度、识别返回数量、build/API及预测计算耗时、HTTP/错误码、进程退出与Session/Engine关闭。首次没有正常返回的根数继续记未知；读取次数是原读取函数调用次数，不冒充SQL次数或物理扫描量。

复测结束只汇报这一个组合：成功则将深证day最新完整结果纳入当前覆盖，保留首次性能失败历史；失败则仍按原停点汇报。两次不同结果可证明耗时发生变化，不能单凭重跑成功认定具体网络/数据库根因或整个性能问题已永久解决。其余39组合及页面保持未执行；不自动接续。

**复测实际结果：再次失败并按首错退出。**原api_verify.py原样复制至`/private/tmp/r4-index-expansion-deep-day-retest.z_w52tjp`，静态核同一文件、worker入口及当前r4实现无变化后执行；没有启动parent、重做上证或自动领取其他组合。

| 深证day首次普通识别 | 首轮 | 管理员指定复测 |
|---|---:|---:|
| HTTP／错误码 | 503／XXM_BUDGET_EXCEEDED | 503／XXM_BUDGET_EXCEEDED |
| read_daily耗时（秒） | 19.648430 | 20.159479 |
| 原build耗时（秒） | 19.821952 | 20.319977 |
| API往返（秒） | 20.143539 | 20.661388 |
| 读取根数 | 未正常返回，未知 | 未正常返回，未知 |
| 后续预测 | 未发出 | 未发出 |

复测准备/导入/装配2.958053秒，子进程内部含清理共23.620589秒；自有进程正常按失败状态退出1，1个Session opened=closed，实际1个数据库连接，cleanup=closed。原失败证据保持，新api-399001.SZ-day.log/json保留于上述新目录，不覆盖任何旧文件。

独立静态核对原样复用、单组合范围、原预算、原只读边界及首错关闭；结果复核单次HTTP503、原阶段计时和资源关闭。两次读取都约20秒，本次重复出现相同失败；现记录仍未细分每批SQL/行处理，不能确定具体SQL、网络、索引或数据量原因，不将上证4087根当成深证根数。不追加统计/SQL或第三次请求。

本次仅重复原失败位置1次，因此覆盖仍5组合通过、1失败、39未执行；两轮累计实际16次请求＝14成功＋2失败，原计划85次尚未发出不因重复失败减为84。第1—2项通过证据保留，第3项仍未完成，页面未验收；暂停在此汇报，未改业务代码、测试、配置、预算或规则，未提交。

### 17.6 深证日线读取原因定位设计（2026-11-05）

管理员已授权排查确定原因，本节只定位，不实施修复或继续验收。CodeGraph和当前迁移/模型核明：read_daily两码走同一五列分页SQL；core_serving.index_factor_pro按迁移是Raw表直接视图；底层设计有(ts_code,trade_date)复合主键及单列trade_date索引。它们只是源码定义，不能替代Prod实际结构/执行计划。原read_daily的completed来自当前context，可能不同于请求endDate；后续观察须记录真实completed，不能把界面截止擅作原SQL上限。

1. 使用现Web env/get_engine的自有连接，首条SET TRANSACTION READ ONLY，finally回滚、关闭连接及Engine；不默认根.env，不输出凭据。白名单仅对应视图、实际Raw表，以及pg_class/pg_namespace/pg_index/pg_stat_all_tables等对应对象的目录信息，不读无关业务表。
2. 第一单元只核pg_get_viewdef、pg_get_indexdef/indisvalid/indisready、对应表统计概要及两码同形EXPLAIN(FORMAT JSON)。不带ANALYZE的EXPLAIN只取计划，不执行行情SELECT；五列为trade_date、close、macd_dif_bfq、macd_dea_bfq、macd_bfq，WHERE ts_code=:code AND trade_date<=:cutoff，ORDER BY trade_date LIMIT1000。cutoff暂用本次请求2026-11-03，仅作同形计划比较，不宣称原实际source截止已知。另SELECT ts_code,COUNT(*)按两码及同截止GROUP BY，仅返回最多2条计数；不输出首末行情值或逐日清单。
3. 若计划不足确定慢步骤，第二单元复用已审计临时App，仅发399001.SZ/day普通signals（endDate=2026-11-03、limit=300）1次，禁预测/debug/其他组合。临时透明包装原Session.execute对该视图SQL的调用，分别记录execute返回、原Result.all返回的耗时及len(batch)，用原批次首末行O(1)取日期记录after位置；不另跑同一SQL核对，不改参数/返回行/remaining/验证逻辑，不复制旧prefix遍历。原source.read_daily入口记录真实completed；相邻批次之间的实际间隔只能称转换/校验等程序阶段，不冒充单一函数的纯CPU时间。客户端execute含数据库与驱动/传输，不能直接称纯数据库耗时。
4. 若需确认服务器内部扫描/过滤/排序，针对第二单元捕获的实际慢批参数，或第一单元发现的明确异常计划，执行原五列LIMIT1000查询的EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON)；只返回计划，不导出行情。使用必要的对应上证同形查询作对照，不遍历全部批次或日期、不另算MACD。若计划显示将读取无关的大范围业务明细，先评估并停下讨论，不以诊断绕过全局读取要求。
5. 以上为独立诊断，不把探查次数记入原100次验收计划，不将改过观察程序的时长冒充原验收成绩。元数据返回数量按实际记录，计数最多2条、计划每码1份、明细SQL最多原1000条/批；不新增套件、并行压测、采样循环、自动重试、固定判卡秒数或全程超时。参考既有单次读取19.648/20.159秒安排分段查看，实际准备、连接、查询、关闭、摘要核验全程记实；不能据旧实耗保证新阶段上界，卡住时沿已有会话只停自有调用。
6. 每个定位单元结果只放本任务新/private/tmp目录，成功和失败均保存小摘要；失败退出、回滚并关闭自己的资源，保留已完成单元，后续按证据决定必要查询，不重复已完整获得的事实。正式结论同步本方案/LLD；没有足够证据时明确缺口，不用猜测填成根因，不修改产品或生产表。

第一至第四单元已定位原第3批execute约20秒，但同批EXPLAIN ANALYZE显示服务器执行仅毫秒级。为区分不同次缓存/等待变化与结果传输，允许追加一个针对该原LIMIT1000慢批的正常SELECT单元：只记录客户端execute/all墙钟及自身CPU、返回长度/日期位置，不导出值；先取得该自有连接pg_backend_pid以便定位。若原SELECT仍在等待，另用同一Web账户的只读连接，对pg_stat_activity中这个PID取一次state/wait_event_type/wait_event/query_start/state_change/clock_timestamp快照（每次快照只返回该1个自有会话），不用轮询循环或查询其他业务会话，不终止任何后台进程。若首次快照显示正在执行且尚不足判断，可结合现有阶段进展做必要的后续单次确认，逐次说明目的，不自动持续采样。该单元只用于定位，不修改驱动、连接参数、查询方式或产品，不把诊断结果替代原性能验收。

已发现单独Connection.exec_driver_sql取回原慢批正常，而原API内Session.execute第3批慢，尚不能把两次差异直接认作网络或数据库根因。允许再对原单次深证signals作同样透明观察，并用原SQLAlchemy before_cursor_execute/after_cursor_execute回调记录驱动执行阶段及进程CPU，回调不改statement/parameters/cursor；从该原连接的driver_connection.info.backend_pid读取自有PID，不为取PID再发查询。结果仍按原行数/预算/请求清理。真正等待时按上一段只查这个PID的会话状态，区分SQL尚在服务器执行、服务器等待客户端，或时间耗在驱动调用前后；不将不同次EXPLAIN的快耗时直接当作原慢请求的服务器耗时。

外层工具单次快照若因调用准备延迟错过等待期，不得据空结果断言服务器状态。为取得同次等待证据，可在下一次同样单请求诊断内，使用一个自有只读观察连接和一个临时线程做一次状态快照：原read_daily开始后，以原产品4秒预算作为观察时点（不是新超时，不中断请求），若读取尚未结束，仅查询已捕获的本请求backend PID一次；读取先结束则不查询。线程通过开始/结束事件等待，不轮询、不领取其他工作；read_daily的finally等待该一次观察退出并关闭观察连接，正常/失败均清理，原worker退出前不得遗留线程/连接。该安排只服务本次等待取证，不加入产品或通用监督系统；新增的只读SET和最多1条自有会话目录SELECT及观察开销单列，不计成原验收请求。

若带观察的诊断首次恢复正常，保留该正常证据但不转成原验收完整组合通过；可再作一次相同单请求诊断以补缺失的“慢时同次会话状态”，仍只按已有4秒时点取一次快照，不自动循环。若仍未出现慢读取，则先汇报间歇性现象和实际证据边界，不以不断重试制造确定结论。

慢时快照未取得时，可最后只读检查pg_extension是否已有pg_stat_statements；若已启用，只核当前用户/当前库中本次原五列SELECT的现有calls/min/max/mean执行时间及行数，用既有历史统计补充判断，不新增行情SELECT。没有扩展或没有对应记录就如实保留缺口，不安装/启用/重置统计、不修改服务器配置，不扩大到其他用户/业务SQL。

### 17.7 原因排查实际结果及独立复核（2026-11-05）

本轮只定位，不修复产品；结果目录`/private/tmp/r4-deep-day-cause.twy4st5_`。CodeGraph、迁移/模型和当前源函数核对后，先运行元数据/普通计划/分组计数，再按§17.6取得原单请求分段、慢批计划、服务器内部计时、正常SQL和必要的会话证据。没有安装、启用扩展、更新数据库统计、改索引、切源、改规则/预算或写正式数据；没有导出逐根行情值、再算MACD或继续原45组合验收。

#### 17.7.1 结构、数量及当前取数上限

metadata-plans.json核明：core_serving.index_factor_pro实际是Raw直接视图，无JOIN/计算；底层pk_raw_tushare_idx_factor_pro(ts_code,trade_date)及idx_raw_tushare_idx_factor_pro_trade_date均valid/ready。表统计n_live_tup=9,355,698为估计，不是本轮全表计数或读取数量；last_autoanalyze=2026-10-17，不能仅据日期判断为本次根因，未执行ANALYZE维护。

两码按trade_date<=2026-11-03的分组COUNT均4086；该统计0.364890秒，只返回2条根数。原产品分段实际捕获completed=2026-11-04，成功输入4087，与原上证输入4087对应；请求endDate只是后续响应裁剪，两者1根之差不是缺数、也不是20秒原因。首批及实际慢批两码的普通EXPLAIN均为复合主键Index Scan；没有发现缺索引或本次已证实的错误查询路径，不据此新增索引。

#### 17.7.2 原请求批次及驱动阶段

source-trace.json记录第1次透明分段，仍只发深证普通signals一次，原4秒检查保持；实际source completed=11-04：

| 批次 | 返回根数 | 日期范围 | Session.execute（秒） | Result.all（秒） |
|---|---:|---|---:|---:|
| 1 | 1000 | 2010-01-04—2014-02-24 | 0.021236 | 0.000723 |
| 2 | 1000 | 2014-02-25—2018-03-27 | 0.020143 | 0.000559 |
| 3 | 1000 | 2018-03-28—2022-05-12 | 20.003957 | 0.000772 |

本次读源总20.056920秒（函数内部记录），第三批之后原check报预算失败；read_daily没有整体返回，但分段已确认这次取得3000根，不能将其反填前两轮未记录根数的失败。相邻批次程序间隔约0.0024秒，末批之后约0.0019秒，包含原转换/验证及观察开销，不说成纯CPU或把全部处理笼统写成不到1毫秒。

cursor-trace/source-trace.json是第2次带游标回调的单请求诊断：第3批execute恢复0.018409秒；第4批1000根（2022-05-13—2026-06-26）在before_cursor_execute至after_cursor_execute之间18.951854秒，Session.execute共18.954764秒，其中进程CPU0.013609秒，Result.all约毫秒级；原预算随后失败。**已定位约19秒落在数据库驱动调用返回之前，主要不是本地CPU运算；该区间仍包含服务器执行/等待、网络及驱动接收，不能直接认作网络故障。**慢处换到第4批，也不能认定为第3批那段数据本身异常。

#### 17.7.3 服务器执行、正常查询及会话观察

slow-batch-plans.json沿实际第3批SQL/参数（after=2018-03-27、completed=11-04、LIMIT1000），两码均正确复合索引。slow-batch-analyze.json中，同批服务器Execution Time深证2.884ms/上证7.277ms，各返回计划Actual Rows1000；深证shared hit1009/read0，上证hit1/read1009，没有临时落盘。该执行只返回计划/数量，不能拿这些后续快查询当作原慢调用的同时刻服务器状态。

slow-select.json直接原SQL取回同批1000行，execute0.143159秒、CPU0.001629秒，all0.000235秒，未保存行值；该调用正常，只证明同一批可快。session-snapshot.json外部快照因调用准备延迟到达时原会话已退出，rows为空且driverPending=false；**无效于判断慢时服务器状态，不能据此声称服务器早已空闲。**

随后在独立目录wait-snapshot及wait-snapshot-confirm各执行一次同样的单signals诊断，保持源、参数、逻辑和预算；观察连接用原Engine构造函数独立建立，避免混入产品pool的关闭检查。以原4秒为一次观察时点，读取先结束则不发pg_stat_activity SELECT，结束事件让线程立即关闭并join：

| 诊断 | 输入根数 | read_daily（秒） | API往返（秒） | 结果 |
|---|---:|---:|---:|---|
| wait-snapshot | 4087 | 1.510805 | 2.807346 | HTTP200、READY |
| wait-snapshot-confirm | 4087 | 0.123376 | 1.484617 | HTTP200、READY |

两次读取均在4秒前结束，没有触发会话快照；monitor-closed.json均closed、无错误，未遗留线程/连接。existing-statement-stats.json确认pg_extension里无pg_stat_statements，没有可用历史语句耗时；未安装、启用、重置或进一步重发行情。

#### 17.7.4 结论、未确定项及当前验收状态

独立只读复核实际索引、4086/4087日期口径、各批数量、Session/游标/CPU分段、后续快查询与两次200：记录相符；没有把不同次查询合并为同次证据。当前**耗时区间已确定，最终根因未确定**：直接失败因为原远程数据库调用约19—20秒才返回，下一次检查触发4秒预算；不能据现有证据将具体原因写成缺索引、数据规模、网络丢包、数据库锁、IO或JIT。尚缺慢时同一调用的服务器状态/等待事件；没有慢时快照及现成历史统计，后续快查询不能补这个事实。

本轮4次诊断单signals＝2次503＋2次200，不计入原100次计划；正常SQL/EXPLAIN/目录统计也单列，不冒充业务API请求。两次200都没有预测，因此原验收覆盖仍5组合通过、1失败、39未执行，不能登记深证完整组合通过、前三项完成或页面通过。所有临时进程已退出，自有Session/Engine/只读观察资源已关闭；不再重跑，先汇报确定部分和证据缺口。源码/测试/配置/规则/索引及预算均未改；只同步原方案/LLD，未提交。

### 17.8 管理员授权后的原计划续跑（2026-11-05）

管理员授权按原方案继续。最近一次单识别诊断返回HTTP 200，读4087根用时1.581297秒，API往返3.365233秒，证据保存在`/private/tmp/r4-deep-day-cause.twy4st5_/user-retry-_pscxf4l`。此前慢调用的具体原因仍待确认。该单识别诊断按§17.7的口径单列。

开跑前核对dev-interface的HEAD仍为`4f7253487`，相关源码、测试及前端输入的工作区差异与首轮一致。当前`.env.web.local`仍指向原prod目标，分钟使用正式`/Volumes/datasource/data_lake`。保留第1—2项证据及首轮上证5个完整组合、14次请求和4项对照。原`api_verify.py`仅在临时父程序增加对这5组已完成记录的核对和跳过逻辑，子程序原样复用。从`399001.SZ/day`开始，待执行40组，计划86次请求，其中含重做失败的识别请求1次。Universe顺序、每组2或4次、截止2026-11-03、单组自有App/Engine/Cache、Session只读及4秒/400毫秒预算均按当时的原请求计划执行。

| 本次启动的组合 | 请求结果 | 输入根数 | 通过请求的原build最大（秒） | 预测状态和计算耗时（毫秒） |
|---|---|---:|---:|---|
| 深证成指日线 | 2次HTTP 200 | 4087 | 1.251609 | NO_CANDIDATE（NO_ENTRY_RANGE），21.382 |
| 深证成指30分钟 | 2次HTTP 200 | 1500 | 1.252152 | READY，61.566 |
| 深证成指60分钟 | 4次HTTP 200，普通/debug识别和预测均一致 | 1500 | 1.037780 | READY，最长87.592 |
| 深证成指90分钟 | 2次HTTP 200 | 1500 | 1.100033 | READY，96.436 |
| 深证成指120分钟 | 2次HTTP 200 | 1500 | 1.071879 | READY，26.924 |
| 创业板指日线 | 首次普通识别HTTP 503，`XXM_BUDGET_EXCEEDED` | 读源未正常返回 | — | 预测待执行 |

创业板指日线的`read_daily`耗时6.864333秒，原build为7.162924秒，API往返7.575046秒。读取未正常返回，实际根数、慢批位置及当时服务器状态未知。父进程按首错退出1。13次请求涉及13个Session，均已关闭。6个自有子进程及其6个实际连接均清理完毕，前5组退出0，失败组退出1。父调用从续跑清单确认到最终核验为34.697746秒，6个子进程内部累计31.201204秒，均含失败单元。原始摘要及逐组记录见`/private/tmp/r4-index-expansion-step4-resume.xs26f_v_/api-summary.json`及同目录日志。

合并保留证据后的26个通过请求中，数据状态均为READY，13次预测为10次READY及3次NO_CANDIDATE。通过请求原build最长1.335040秒，API往返最长2.091077秒，预测计算最长96.436毫秒。识别、预测响应最大分别为189932和9019字节，缓存最多2项、最大3342744字节。深证日线两个请求各按原逻辑读4087根，深证分钟四周期各首次读取1500根，识别返回分别为日线300和分钟500。读源次数按调用分别记录。深证60分钟的两项普通/debug对照均为equal，合计3个代表组合、6项对照一致，另4项待执行。

独立复核核对了临时父程序差异、保留证据、原顺序、预算、关闭记录和实际首错停点。原链路记录为**10组通过、1组失败、34组尚未启动，26/100次规定请求通过**。原剩余工作含失败组合的完整重做，共35组、74次规定请求。当前的DG定向补验和续跑以§11.3为准。


## 18. 本机DG取数的实现、回归与真实API核验（2026-11-05）

按§2.1完成准备、实现及受影响回归、真实API核验，交管理员执行第4项。CodeGraph与源码核过普通图表/r4路由、查询、日历、预测、直接工具消费者和缓存键。实际改动及证据对账如下。

| 硬口径 | 实际落点 | 验证 |
|---|---|---|
| 按后端环境装配，生产普通图表沿Prod、生产r4关闭，本机日线独立于分钟开关 | `src/app/api/v1/router.py` 解析一次正式DG根，为九码普通图表、r4信号和预测传同一读取器；非本机不创建读者 | 隔离App路由和普通接口回归，真实本机连接拦截 |
| 日线、身份、日历及图表状态的DG读取 | `src/foundation/clients/local_lake/index_daily_reader.py` 按日期确定已发布分区、批量投影；普通图表查询保留原窗口、MA预热及落后判断 | 隔离Parquet、图表与r4的同日公开值 |
| r4计算范围、分钟窗口和下一根 | `index_detail_xxm/source.py` 下限含2010-01-04；查询与预测复用DG日历；分钟仍走Gold及N+1000 | 隔离日线下限、晚起、连续性、20:00切换和真实Gold分钟夹具；定向及剩余API |
| 原缓存形状、编号和公开合同 | `query_service.py`、`forecast_query_service.py` 使用固定本机绑定及既有来源位置；缓存发布与指纹沿原流程 | 识别/预测回归，普通/debug与定向历史证据比较 |
| 直接调用方 | 两个保留工具适配当前路由，页面审计共享同一DG读者，日线预检沿隔离存储直接装配实际预测路由 | 15项工具定向测试；旧路由对象引用清零 |

本次五组自动检查分别通过4项（读取器）、3项（图表DG）、51项（环境、普通指数API、分层）、478项（r4识别和预测）、15项（保留工具），共551项。各组通过结果单列，未重复运行用例；原有Starlette/TestClient弃用提醒不影响本次测试。原前端及构建证据保留原适用范围。本轮验收不代替页面反馈。

### 18.1 真实读取和性能

2026-11-05 17:44—17:46（上海时区）以§11.3的2026-11-03响应截止执行。37个子进程全部退出0、资源关闭，父调用从验收开始至最后摘要核对共170.149秒，含准备、执行和收尾。**9次定向及74次剩余请求均为HTTP 200，实际Prod连接尝试0次。** 其中普通图表1次、识别41次、预测41次。r4数据状态82次READY；预测22次READY、19次NO_CANDIDATE。

| 定向对象 | 结果 |
|---|---|
| 上证日线 | 图表返回300根；2026-11-03收盘、DIF、DEA、柱与识别一致。r4输入从2010-01-04至2026-11-04，共4087根。识别和预测普通/debug两项一致，对原同输入摘要两项一致 |
| 深证60分钟 | r4输入1500根，下一端点为2026-11-04 10:30+08:00。使用DG日历及Gold分钟行情；识别和预测普通/debug两项一致，对原同输入摘要两项一致 |
| 创业板日线（原失败组合） | 2010-06-01至2026-11-04共3988根；首次因子批量读取0.686053秒，识别后端2.584739秒、HTTP 2.592272秒；预测计算238.434毫秒 |

其余新实测日线在相同计算截止下：科创50自2019-12-31共1657根，中证A500自2024-09-23共511根；沪深300、中证500、中证1000、上证50均自2010-01-04各4087根。深证日线沿用原功能证据，未登记为本轮DG日线实测。

r4后端最长2.584739秒、预测计算最长238.434毫秒，分别低于原4秒和400毫秒。识别响应最大189932字节，共用缓存观测最大2项、3172598字节。上证图表HTTP用时1.003秒，发现6501个已发布候选日期分区，行情查询实际读取300个分区并返回300根。候选分区数与实际行情读取数分别统计。静态复核发现，普通图表不传起点且请求根数超过该码历史时，会按§5.1向前查询剩余分区；例如中证A500的普通图表请求1000根，而本次同截止r4有效历史只有511根。该普通图表请求的耗时未实测。未将真实API往返耗时当成浏览器5秒验收。证据保存在 `/private/tmp/r4-index-expansion-dg-api.sgh5ga/api-summary.json` 及同目录调用日志。

### 18.2 覆盖复用和页面交接

本次DG实测37个组合，新做普通/debug公共结果对照8项均一致。旧链路的8个未重做组合保留适用的原功能证据，原上证30分钟两项对照仍属旧证据。45组合的覆盖由两类证据构成；只把本次实际请求计入DG实测。已执行检查、切源、调用顺序、性能预算、隔离、首错停点及退出边界与方案一致。

**第4大步前3项通过，第4项真实页面待管理员执行。** 依§11.4查看上证日线图表/识别/预判、代表分钟、普通/debug及指数切换、五行状态、北证排除及上证原手动研究入口。真实NO_CANDIDATE是有效结果，页面验收不要求显示价格区间。
