# 财势乾坤r4指数扩展LLD v1

日期：2026-11-05（Asia/Shanghai）。状态：**第1步来源根数统计、第2步Python后端实现及限定回归、独立审计已完成；第3步前端消费及第4步真实来源/性能/页面验收尚未执行。第2步交付与测试记录限制见§13.3，新增页面范围尚未开放。**

依据：[独立扩展方案](/Users/congming/github/goldenshare/docs/product/wealth-top-bottom-recognition-index-expansion-plan-v1.md)。本LLD只细化本次扩大指数及新增30分钟的变化；原[产品文档](/Users/congming/github/goldenshare/docs/product/wealth-top-bottom-recognition-product-v1.md)、[技术方案](index-detail-top-bottom-recognition-technical-design-v1.md)、[原LLD](index-detail-top-bottom-recognition-low-level-design-v1.md)继续作为已验收r4规则及原四周期事实依据，不把原P5成绩当本次扩展验收。

## 1. 目标、范围和必须保留的行为

首页事实源仍为`majorIndices / CN_A`配置：`src/biz/services/wealth/config/definitions/major_indices.cn_a.v1.json`。本次支持上证指数（000001.SH）、深证成指（399001.SZ）、创业板指（399006.SZ）、科创50（000688.SH）、沪深300（000300.SH）、中证500（000905.SH）、中证1000（000852.SH）、中证A500（000510.SH）、上证50（000016.SH）。实际准入必须读原配置，不另建九码数组。

支持周期固定为`day / m30 / m60 / m90 / m120`，共9指数45种组合。上证原四周期保持并新增m30；其余8指数接入全部五周期。北证899050.BJ五周期全部排除，原首页10卡及普通行情保持。15分钟等其他周期不因通用行情支持而开放r4。

| 硬口径 | 编码落点 | 验证 |
|---|---|---|
| 不改r4判别、下一根求解、版本及hash | §4类型准入以外不改核心；§7预测复用 | T12—T19、T32、原金样本 |
| 名单同源，北证明确排除 | §3单次Universe准入，§8页面资格 | T01—T07、T27 |
| 实际代码贯穿取数、计算、缓存和响应 | §3—7必填参数 | T08—T11、T20—T23 |
| 五周期成套接入，不能只放行参数 | §4、§5、§7、§8 | T12—T19、T24—T26 |
| 真实MACD来自现日线/Gold，不补值、不重算 | §5正常产品取数；§10只统计根数，不作指标质量证据 | T08—T10原功能测试；T34/T35仅计数 |
| 分钟返回N，计算额外1000根 | §5窗口不变 | T15、T36 |
| 普通/debug事实一致，辅助按需 | §8保持动态模块及投影 | T24、T28—T30、§11 |
| 上证独立日线波段研究不扩大 | §8.5研究控制器 | T30 |
| 生产关闭、不改鉴权、不部署 | §9及原App装配 | T07、T31 |
| 保留预算，不开启暂缓优化 | §9 | T33、§11性能 |

初版方案/LLD及两索引已随99d876a32提交，文档收敛及根数统计口径已分别随f2c2d0f72、5339f0898提交。随后按管理员授权完成第1步来源统计及第2步Python实现、限定回归，结果见§13.1/13.3。当前停在第3步之前；配置、旧P5文档及其他工作区修改保持，不安装、不建分支、不部署。

## 2. 开发步骤、依赖、失败和交接

| 顺序 | 目标与实现范围 | 开始条件 | 完成/交接条件 |
|---|---|---|---|
| 0 文档及开工审计 | 本方案/LLD、消费者和合同检查 | 当前源码及管理员范围明确 | 方案/LLD一致；无未决业务口径；文档review完成 |
| 1 来源根数统计 | §10日线1条、分钟两类各1条聚合SELECT，禁止明细审计 | 第0步完成，当前Web目标/权限及既有环境确认 | 各指数/周期实际、预期根数及差额有结果；数量吻合，不扩大为数据质量已验收 |
| 2 核心身份/周期及来源查询 | §3—7类型、DTO、来源、缓存、API及Python工具/直接调用测试成套迁移；不改TS客户端或mjs调用 | 第1步数量吻合、当前工作区无冲突 | 后端正反向及原上证金样本通过；原TS客户端与mjs仍相互匹配，前端新范围尚不开放 |
| 3 前端消费 | §8页面身份、五周期识别/五行预判/debug、研究边界；TS客户端、mjs及其调用/测试同批迁移 | 第2步完整，公开字段/异常已冻结 | 类型、限定交互及消费测试通过；mjs调用新签名正确，不是只修改名单 |
| 4 整体回归和真实验收 | §11自动测试、45组合及代表页面/性能 | 第2—3步独立审计符合LLD | §12门禁对账、管理员review；不自动部署 |

第2步内部先扩核心类型、DTO及30分钟端点，再改来源和查询/预测传递，最后API、Python工具和全部Python调用者同时迁移；不得暂时给产品方法保留上证默认参数维持旧签名。第2步保持TS客户端与mjs现有参数形状：HTTP仍接受原上证四周期请求，响应字段集合/版本不变，原前端可以继续使用。第3步再将TS客户端、Hook/decoder/fixture、mjs及其集成测试同时迁移，最后启用页面新范围。不能在第2步先让mjs给旧client传code首参，也不能为迁mjs提前扩大第2步到前端改造。中间提交若需进行，必须明确尚未可验收，不发布中间混配版本。

失败先停止该单元，不自动重试、切源、补数据、放宽阈值或清缓存掩盖。代码/规则与本文冲突时先汇报并修正文档，不临时加兼容路径。源码保护通过人工规则/差异审计，不读源码SHA作运行校验。无业务写入、迁移或磁盘快照；真实输入或实现改变导致证据不再适用时，只补受影响单元。

续跑按完整单元处理：日线1条计数SELECT是一个单元，分钟两类计数共同为另一个单元，每个指数/周期2或4次正常API请求各为一个组合单元。完整结果保留，中断部分仅诊断，原因解决并获准后重做未完成单元；不拼接不同次分钟两类计数，也不换新缓存只补debug称热路径，不新增恢复系统。

本次只扩展r4标的身份及周期，不重构既有普通分钟Hook、缓存或请求状态模型，不为“上游两个接口同时违反合同”等未观察到的问题增加必改项或成组防御测试。执行临时调用复用现有观察方法、内部工作截止及标准外层超时，不另建分阶段信号管理、进程通信或通用监督框架。

来源统计和第4步隔离API的外层临时调用只启动一个自有Python核验进程，SQL、DuckDB或隔离API在该进程中执行；不嵌套Node、浏览器或额外服务子进程。已完成来源统计的时限及实耗按§10/13保留，第4步须按§11.3先核定完整时限再使用标准subprocess超时，不借用旧工具的进程监督逻辑。自动测试仍可运行现有测试中原本就有的Node客户端夹具，不将这类夹具误当新增来源核验子进程。真实页面验收在§11.4另行进行，不纳入隔离API单元。

所有测试/查询/临时调用的过程文件在`/private/tmp`本任务目录，禁止写入工程或reports。正式结论写回本方案/LLD。自动测试的单元、成本组成和失败退出按§11.2，不设置缺乏依据的统一总时限；已完成来源单元的历史时限不自动用于新单元。产品现有限额及第4步完整执行前条件见§9/11.3，中断后重做、退出、记录和最后核验的成本均须列明。

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

### 5.1 日线

`read_daily`仅将`IndexFactorPro.ts_code == '000001.SH'`替换为必填code条件。继续从该码已有最早行到completed，按trade_date升序、1000行日期游标分页，投影trade_date/close/macd_dif_bfq/macd_dea_bfq/macd_bfq；日期DATE、必需值非空有限且close>0。保留现行行数上限和批次检查，不把响应startDate/limit变为计算起点，不补创立前历史。

保持当前Web注入Session及实际来源，不切DG或另一库，不重算DIF/DEA/柱。现日线`check()`不是能中断阻塞SQL的数据库硬超时；本次不另改生产连接或数据库配置。真实请求若超原预算立即报告，不借本需求引入新的性能框架。

### 5.2 分钟

`source.ENDPOINTS`增加30，八端点为上海时区：10:00、10:30、11:00、11:30、13:30、14:00、14:30、15:00。60/90/120端点字面值不变。此表供完成截止、归一化、窗口规划、连续性及future_calendar统一读取；测试expected必须来自正式生产合同的独立字面表。

严格保持顺序：完成截止归一化→按N+1000选择实际端点窗口→建立同code/freq/日期请求→该窗口的两类signature→内容未命中才读取一次完整pair→两源逐键对应→逐根r4。签名发现调用的`minute_request`与`read_minutes`内部构造请求必须传相同code、freq、window；不得只改内容WHERE漏改签名请求。

N默认500、最大2000；read_rows=N+1000，因此1500/3000不变。30分钟每日8根，规划开市日数`ceil(read_rows/8)+1`，分别189/376；仅是规划上界，实际文件按该码合同与所选窗口，不可直接发现所有历史。短历史不补行。`startDate`只筛响应，不改变额外1000根政策。

来源复用`MajorIndexMinsLakeReader.read_complete_history_pair`：bars仅close，indicators仅macd_dif/macd_dea/macd，保留源参数/版本和完整键核对。正式Lake仍`/Volumes/datasource/data_lake`；不改Foundation读取器、其文件signature/prepared清单共享及原已优化路径。不同code共用一份物理分区事实是合法的，产品计算缓存按§6独立。

### 5.3 下一根和精度

`future_calendar`保留SSE从anchor起未来90自然日、最多91行；选严格晚于through的首个开市端点。m30明确11:30→13:30、15:00→下一开市日10:00；09:30、午休、未完成根不可当标准完成端点，周末/休市走日历，不能时钟直接加30分钟。历史asOf仍截到原完成端点，不用后来行情冒充历史前缀。

m30沿分钟full_float、最近250根校准和1e-8容差。先precheck排除无候选，无需多余投影；有候选但少于250根或校准不通过为PRECISION_PENDING；空/滞后为EMPTY/DELAYED。近处有钝化范围就停止，不计算远处；已有结构及后续有限跟踪的预测仍按原规则。只预判下一根，不重开旧的中点试算、逐价格遍历或后19根推演。

## 6. 缓存、共享加载和发布顺序

在原key尾部增加code，保留period现有位置，避免无必要修改观察工具：

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

forecast缓存仍由原`('forecast', *key)`命名空间保存。一个共用LRU最多16项/64MiB，**不是每码16项或分别给series/forecast各扩一份**。保留原共享加载、修订重算、历史prefix及淘汰，不预计算九码，不引入新的TTL/mtime校验或缓存层。

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

当前page-init client只将JSON声明为类型，不能假定已核代码。`controller/useIndexDetailController.ts::load`在page-init返回且`isCurrent`通过后、EMPTY/后续请求之前核`pageInit.index.tsCode === normalizedTsCode`；kline返回且isCurrent通过后、buildViewModel前核`kline.indexRef.tsCode === normalizedTsCode`。不一致沿原catch进入ID_QUERY_FAILED/error，不新增整个页面decoder或异常码。

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

本需求不新增/修改配置。沿当前来源及策略中心；配置失败严格失败。StrategyConfigService按实例首次读取文件后缓存，新实例读取当前文件，不新增文件监听、全局配置缓存或自动刷新机制；Settings开关按原装配方式生效。不得为迎合文档而改变现配置读取方式。下面仅登记已有消费者及边界：

| 现配置/事实 | 来源与消费者 | 生效/本轮动作 |
|---|---|---|
| majorIndices/CN_A | StrategyConfigService→Universe；首页、详情与r4准入 | 现service实例内缓存，新实例首次读取当前文件；不改JSON/版本、不另建九码集合 |
| APP_ENV | 现App本地r4注册及前端DEV | 保持原dev/local显式启用规则；prod不注册全部r4路由 |
| WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED及现根目录能力 | App分钟能力→query reader、前端minutes | 不改开关/根目录；关闭时日线独立可用，分钟按原不支持 |
| DATABASE_URL/GOLDENSHARE_ENV_FILE | 当前Web Settings及注入Session | 不读出凭据、不切源、不改生产配置 |
| MAIN_SPEC/FORECAST_SPEC、runtime.BUDGET | 唯一识别/预测及缓存/读源 | 版本/hash/限额不变；不是新增配置项 |

预算固定：后端请求含准入/context/排队/读源/投影/序列化/最后检查4秒；READY预测计算及缓存处理400ms；客户端实际执行5秒；识别1MiB、预测32KiB；LRU16项/64MiB；后端来源请求槽2；前端调度按§8.4独占r4。继续使用现remaining、pair reader中断及finally释放，不新造缓存、强行微优化或恢复暂缓第4—7批。

状态沿原合同：识别loading→ready/empty/delayed/error；预测idle/loading→ready（具体status为READY/NO_CANDIDATE/PRECISION_PENDING/EMPTY/DELAYED）或error，unsupported仅用于当前前端不可用范围。EMPTY/DELAYED不输出旧价格冒充新预判；北证为产品不支持，不是r4 EMPTY。普通只显示原公共事实，debug显示原完整依据，不能只凭标签相同漏掉真实code/参照错绑。

## 10. 编码前的来源根数统计

本节是唯一来源核验设计，**只做统计计算，禁止读取每根行情来审计**。2026-11-04已按本节完成，结果见§13。范围不变：九码，日线截至2026-11-03最近10个开市日所在窗口；分钟2026-10-30、11-02、11-03及30/60/90/120分钟，不追到最新、不扩大到全历史。

统计在数据库/DuckDB内完成，只向应用层返回按指数、周期分组的实际根数、预期根数和差额。只用COUNT及统计窗口所需的日历聚合；不得读close、DIF、DEA、柱值、trade_time、参数版本或首末行情样本。不做逐值/逐键/逐日对账、网格、唯一性、字段质量检查；即使只返回摘要也不得在SQL内部继续这些逐根审计。

### 10.1 连接、预算、结果和续跑

复用当前Web配置解析取得实际数据库目标，记录脱敏目标及env-file路径；不输出凭据、不切DG或其他库。现解释器及PG驱动建立自有REPEATABLE READ READ ONLY事务，连接及单条SQL最多10秒且受工作截止约束；BEGIN、事务属性和超时设置单列实际次数，不冒充行情查询。

日线1条聚合SELECT为一个单元：40秒工作+10秒关闭/摘要，总预算50秒，外层标准subprocess超时50秒。分钟2条聚合SELECT共同为一个单元：10秒工作+5秒关闭/摘要，总预算15秒，外层标准subprocess超时15秒。正常/错误路径finally关闭自有资源；计数SQL沿既有statement_timeout/DuckDB中断，不新增监督系统。首错/超时只报告，不自动重试、换源、补读、加时或改数据。

完整通过的统计单元保留；中断部分仅诊断，原因解决并获准后重做未完成单元。不拼接不同次分钟K线/指标计数，不新增持久化恢复系统。

每组输出固定字段：`sourceKind / tsCode / period / windowStart / windowEnd / tradingDays / actualCount / expectedCount / difference`。difference=actualCount-expectedCount，分组无记录时actualCount记0，这是统计结果，不是补行情。另列分钟两类根数差额。只报告数量吻合、差额或未完成，不输出“MACD有效/无缺根重复/逐时刻对齐”等超出计数证据的结论。

### 10.2 日线：一条聚合SELECT

用现`core_serving.trade_calendar`的SSE开市日期确定截止日之前最近10个开市日的窗口起点和数量，仅保留聚合结果，不返回日期明细、不做逐日日历覆盖审计。日线在同窗口按九码COUNT；从正式配置取九码形成有限绑定VALUES，不另建运行名单。

```sql
WITH recent AS (
  SELECT trade_date FROM core_serving.trade_calendar
  WHERE exchange = 'SSE' AND is_open IS TRUE AND trade_date <= :cutoff
  ORDER BY trade_date DESC LIMIT 10
), bounds AS (
  SELECT MIN(trade_date) AS window_start, COUNT(*) AS trading_days FROM recent
), wanted(ts_code, ord) AS (VALUES /* 九组(:code_i, :order_i)绑定槽 */)
SELECT w.ts_code, b.window_start, CAST(:cutoff AS date) AS window_end,
       b.trading_days, COUNT(f.trade_date) AS actual_count,
       b.trading_days AS expected_count,
       COUNT(f.trade_date) - b.trading_days AS difference
FROM wanted w CROSS JOIN bounds b
LEFT JOIN core_serving.index_factor_pro f
  ON f.ts_code = w.ts_code
 AND f.trade_date BETWEEN b.window_start AND :cutoff
GROUP BY w.ts_code, w.ord, b.window_start, b.trading_days
ORDER BY w.ord;
```

cutoff绑定为DATE。只返回九条统计；period补固定day，sourceKind标日线。窗口应有10个开市日，每码预期10、九码合计90；日历数量不足时如实报告无法按原窗口完成，不展开逐日排查。根数差额直接记录，不追加明细查询定位哪根。原日线首末/尾部样本查询、逐值检查和四查询执行约束全部删除。

### 10.3 分钟：两类各一条聚合SELECT

只构造原四频×三日×两类24条精确路径，不glob历史。bars根`gold/quote/major_index_mins`，indicators根`gold/indicator/major_index_mins_technical`，其下`freq=F/trade_date=D/part-000.parquet`，两类各12文件。路径不存在或计数SQL不能执行，报告未完成，不改源补读。

使用现DuckDB，内存256MiB、线程1、禁临时落盘和扩展安装；只读统计分组及范围过滤所需字段，禁止投影行情/指标值。对bars的12路径和indicators的12路径分别执行下列聚合，各最多返回九码×四周期的36条计数，不返回每日或每根记录：

```sql
SELECT ts_code, freq, COUNT(*) AS actual_count
FROM read_parquet(?, hive_partitioning=false)
WHERE ts_code IN (SELECT unnest(?))
  AND freq IN (SELECT unnest(?))
  AND trade_date IN (SELECT unnest(?))
GROUP BY ts_code, freq
ORDER BY ts_code, freq;
```

参数顺序为该类12路径、九码、[30,60,90,120]、三个DATE。只在应用层合并这36个统计分组并计算差额，不拉取/遍历任何行情明细；不调用会读取完整pair的产品reader进行来源审计。

| 周期 | 每日根数 | 三日每码每类预期 | 九码每类合计 |
|---|---|---|---|
| m30 | 8 | 24 | 216 |
| m60 | 4 | 12 | 108 |
| m90 | 3 | 9 | 81 |
| m120 | 2 | 6 | 54 |
| 合计 | 17 | 51 | 459 |

每类459、两类918仅是总量汇总，逐指数/周期仍列实际、预期和差额；不只看两类合计。原端点网格、键集合差、两源逐键、NULL/有限数、价格、schema全列和参数版本审计全部删除，不变换为SQL条件聚合继续执行。这里只证明根数，不要求额外校准或源质量结论。正常产品§5的取数、识别、预测和已有校验保持，本节不修改它们。

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
| T27 | validated=null/串码/北证、初始shell/loading/empty/error；正常九码 | 前者不发r4、后者正常；page-init和kline串码进错误态 | availability/Page/controller |
| T28 | 切指数/日期/debug，旧成功/失败延迟返回；另切主图周期 | 旧结果不回写；识别/研究清理对应owner，主图周期变化不重启五行预测 | Hook/Page |
| T29 | 通过真实scheduler排队普通请求+五行r4 | 轻请求上限2，r4独占；5秒从开始执行算，不把Hook mock五pending当网络并发证据 | scheduler/client |
| T30 | debug上证day手动开研究；其他码/m30/退debug/切页 | 研究仅原范围手动；其他码r4辅助可用、无daily-waves请求/覆盖 | debug/daily-wave/Page |
| T31 | 普通页、debug页、生产构建 | 普通无动态辅助import，debug按需，生产关闭 | dependencyBoundary/useIndexDebugModule |
| T32 | 上证原相同输入及code默认核心数学样本 | 旧指纹/ID/hash稳定；产品构造显式传code | snapshot_consumers/forecast_api/forecast_validation/现规则组 |
| T33 | 17个合法缓存项、冷热及forecast候选最后检查失败 | 共用16项/64MiB正常淘汰；最后失败不发布forecast候选，但已验证series仍可保留，不改原两类发布顺序 | cache/API validation |
| T34 | §10日线九码分组计数，窗口10个开市日 | 每码预期10、合计90；独立字面统计样本中实际9/11时差额为-1/+1；SQL仅计数，不返回或逐根核行情值 | 临时来源统计及摘要 |
| T35 | §10分钟两类按九码/四周期计数 | 每码每类24/12/9/6，各类459；逐分组列实际/预期/差额及两类数量差，不生成日期/端点网格或逐键审计 | 同上 |
| T36 | 真实9码×5周期正常API | §11.3请求身份、完成时间、状态、计数及大小正确；正常产品返回什么就记录什么，不额外补校准/逐根审计 | 真实只读API |

T13/T17复用现独立数学/业务金样本，换成正式合同中的m30合法时间，不用被测端点表生成时点；预测校准长前缀可沿已有高精度Decimal独立参考构造，expected不调用recover_projection/同一求解器。T23只构造真实可能的“另一合法对象被放错key”，不造无意义内部坏状态。不能将所有真实行情强行要求有信号；非空规则路径在独立人工样本保证。

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

### 11.3 45组合的真实只读API验收

在原App本地路由的隔离调用中执行，不启共享lifespan、不重启服务或改生产配置。使用当前Web实际只读DB连接及正式Lake，真实Universe/query/source/calculator/DTO不替代；鉴权凭据层可沿现获准测试身份，须单独说明，鉴权自身由原401/403测试覆盖。禁止以mock service或自造数据宣称真实来源通过。

固定cutoff仍2026-11-03，九码按首页顺序排除北证，每码按day/m30/m60/m90/m120。

- 每组合一次普通识别（day limit=300、分钟limit=500，endDate=cutoff），一次普通forecast（day asOf=cutoff、分钟asOf=cutoff的15:00+08:00），共90业务请求。不得重复读旧行情跑完整r2对比。
- 五个代表组合另各一次debug识别及debug forecast：上证day、上证m30、深证m60、科创50m90、中证A500m120，共10请求。与同组合普通公共字段比较；共100业务请求，不另为“更好看的信号”随意加日期。比较先按本次code/period绑定唯一一对，再复用现`compare_modes`的同源前提：sourceInputId、calendarInputId、indicatorVersion、请求截止、computedThrough及实际窗口相同。固定cutoff不等于冻结历史修订；来源不同时记`not_comparable`、不登记该比较通过，也不追加读源或重发请求来凑一致。这是现比较方法的复用，不新增产品检查。
- 每个组合是规定的2或4次请求，不按时间剩余增加请求。原后端4秒及预测400ms保持；真实TS客户端仍从调度实际开始执行时计5秒。2×5=10秒、4×5=20秒仅是按现客户端限额推导的请求执行阶段累计额度，**不含排队、准备、关闭、摘要和核验，也不是隔离Python进程的全程上界**。单Python隔离API不会自动执行TS的5秒取消，后端剩余时间检查也不能硬中断同步阻塞SQL，不能因此声称已实现5秒外部硬截止。
- 完整成本必须列为准备/导入及连接、规定请求、公共结果比较、关闭/退出、摘要及最后核验之和；中断后的未完成组合另计重新准备、完整2或4请求、比较及收尾，不拼接旧单元。当前尚无适用于本隔离调用的准备/关闭等阶段耗时依据，因此不设置固定全程秒数或固定余量。**第4步启动前须先审计最终临时调用，核清外部请求截止及整个进程含收尾的时限依据并落回本节；未核定前不得编写或执行45组合调用。**可用适用的已有实测、可复算的具体步骤或管理员明确指定的本轮执行值，不得套用旧工具绑定原场景、Node及服务线程的时限。这个条件只约束第4步，不要求为第2步编码补测来源或引入新监督框架。
- 核定上述时限后，外层用标准subprocess超时、内部沿已核截止及finally清理；超时停止并报告，不发下一组合或自动重试。仅沿用旧工具的透明观察方法，不搬入其旧执行入口或进程组/通信监督框架。先完成并记录一个组合再进下一个，不积攒全部响应到末尾。
- 使用临时进程自有缓存，不清共享Web缓存。代表组合普通识别首次为series冷路径，普通预测首次为预测冷路径；紧接debug请求作为同窗热路径。记录实际是否命中，不伪称保证命中；不为测冷反复启动相同请求。
- 每次只记录code/period、请求截止、完成时点、原状态/原因、根数、读取次数/范围、缓存、响应字节及原阶段耗时。沿现透明观察方式，在原读取返回处只取结果长度，在原`project_xxm_response / project_forecast_response`处取得内部已有输入/日历编号、完成时点和code/period、响应meta.count及公共摘要；不另遍历entry时间、拼前缀、逐根核指纹或保留行情值作审计。现普通预测不公开sourceInputId，编号从内部DTO取得，不新增公开字段或debug请求。只保留这些观察，不直接搬入旧工具中逐根生成时间列表及整套通信校验，不加第二次读取/重放。
- 识别和预测响应的code/period必须等于请求。完成端点、source初始历史状态、events与引用一致。实际无候选/精度待定如实记录，不能作为有价格预测通过。
- m30按正常产品路径执行；产品已有校准则只记录原返回状态/耗时，NO_CANDIDATE未校准就保留该状态。禁止为审计保留整份前缀再逐根核指纹、补调recover_projection或第二次读源，不另做真实行情逐根检查。原人工数学/规则测试及产品正常读取、识别、预测和原有校验不变。
- 有任何性能不达标，首个失败即停止后续真实性能请求并汇报实际路径/数量/阶段耗时；不改预算/自动重试。其他纯静态或已获准隔离回归可继续，但本批真实验收不得报全部通过。

按§2完整单元续跑：一个组合内2或4次正常请求及规定的公共结果比较完成后登记；不额外要求独立校准审计。中断部分仅诊断，原因解决并获准后重做未完成组合，不换新worker只补debug称热路径。完整通过的其他组合保留。每单元仅保存小摘要，正式文档记录45组合状态及代表性能，不向reports保存100份完整JSON。接口成功、NO_CANDIDATE和人工非空样本分别报告，不新增恢复系统。

### 11.4 页面核心验收

复用已运行且获准的本地前端/后端；缺服务时先报告，不自行重启、安装或改连接。使用真实API驱动页面，不用mock adapter。查看上证m30、深证m60、科创50m90、中证A500m120及北证排除，另核上证day原研究手动入口；正常/debug切换和指数切换覆盖一次。仅为这些页面访问产生的请求按实计数，不宣称包含在上述100请求内，也不预加载另外九码。

核心字段：code/period、时间/close/DIF/DEA/hist、ordinaryState/direction、events.type/time/displayOnChart，debug参照及structure关联；预测status/reasonCode、targetEndpoint/barsAhead、display四文本及来源时间。前端只画对应本图结果，预判五行有正确周期名、状态/条件、单行重试和完成时间，不能前端重算标签。北证无r4占位，普通行情仍正常。

记录页面可见结果、console及请求身份/次数；核普通无辅助import、debug按需、研究仅上证day手动、生产负向测试。网络/数据失败如实展示并记录，缺数据不制造标签或强改测试预期。页面访问不另施加“必须撞到并发共享”的人为要求。

## 12. 编码门禁矩阵、例外及交付

对应[通用清单](/Users/congming/github/goldenshare/wealth/docs/system/module-delivery-checklist-v1.md)，未列为不适用的条目均要执行：

| 清单 | 适用性与本需求落点 | 验证 |
|---|---|---|
| 2.1事实链 | 适用：本方案为独立实施依据，本LLD细化；视觉沿已验收页面和明确五行变化，不另造Figma/benchmark | 文档review、§11.4 |
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
| 2.17核心case | 适用真实API及真实页面，mock不能代替 | §11.3—11.4 |
| 2.18八原则 | 下表逐条映射 | 不得空项 |

| 原则 | 编码/证据落点 |
|---|---|
| 事实源单一 | Universe、现日线/Gold和原r4；T01/T08—T10 |
| 契约先行 | §3.3/4/8目标合同及全消费者；T24—T25 |
| 配置一致 | §3/9，不复制名单/不新配置；T04 |
| 默认显式 | 北证、五周期、空/延迟、minutes关闭；T02/T05/T06/T11 |
| 排序筛选确定 | code过滤、时间升序、预判五行顺序；T08/T15/T26 |
| 性能预算前置 | §9现产品限额保持；§11.2完整记录测试成本；§11.3第4步先核定含退出/重做的时限，未核定不执行；T33及真实性能 |
| 异常标准 | §3.1现码、普通/debug分层；T03/T04/T24 |
| 用户可见结果 | 标签/时间/五行预判/辅助及生产边界；§11.4 |

模块级例外白名单：**无新增规则例外**。保留已验收产品的显式本地能力及条件预判，不将通用“无主观预测”误解为禁止本已获准的下一根条件范围。没有变更坐标/视觉体系、源字段合同或三工程共享契约，不修改Foundation/DG生产者。

交付逐条记录硬口径→实际代码→测试/真实证据；未完成的来源/性能/页面验收明确列出。完成后只收尾本需求及管理员认可的文档，不自动提交、部署或扩大研究。

## 13. 审计记录、第1步执行结果及状态

编码设计已依据当前代码与CodeGraph核API、Universe、query/source、缓存、核心/恢复、预测、TS/page/controller/debug及直接消费者。第1步先提交统计设计，再执行来源计数，当时没有读取行情值或修改产品代码；第2步实现记录见§13.3。方案与本LLD对应为：方案§1—2→本§1—2；§3→本§5/10；§4—5→本§3—8；§6→本§9；§7→本§11—12；§8→本§2/10—11。

已核对signals规范代码、两类缓存各自发布时序、配置实例缓存事实、主图周期不重启五行预测及m30夹具下一根时点。正常EMPTY的page-init身份字段已核对真实生产者/schema/既有测试，原已设计的身份检查不把正常空行情误判为串码。

来源执行要求以§10根数统计为准：日线1条聚合、分钟两类各1条聚合，只返回指数/周期实际根数、预期根数及差额。旧的四查询、行情样本、逐日/逐键/数值审计执行内容已删除，不以标记过时的方式留作开发入口。§11正常API验收也不额外补校准或逐根核前缀。正常产品§5和独立人工规则/数学测试保持。

T01—T36仍为36组设计case，T34/T35已改为数量统计，T36只验正常API；不新增普通分钟防御case。计数吻合仅说明数量，不扩大成指标、唯一性、时间位置或数据质量结论。已执行来源单元50/15秒限额及实耗按§13.1保留，不外推到新阶段；后续测试成本、真实调用时限的依据和执行条件分别按§11.2/11.3，不新增监督/恢复系统。

已分别独立复核来源统计和步骤/测试交接，两文档的范围、查询数量和预期根数一致。统计设计修正未改变产品编码设计；本轮另补清第2—3步的工具与测试归属、测试成本和第4步执行前条件，没有修改r4规则、源范围或产品现有限额。文档检查只评价文档，不代替各步功能或性能验收。

### 13.1 第1步执行对账（2026-11-04）

执行前已核现Settings解析、正式首页名单和计数字段合同；临时脚本独立复核未发现额外来源查询、明细读取或写入。分组摘要9/10/11对预期10的差额分别为-1/0/+1，按独立字面值检查通过。临时调用复用现Python、psycopg、DuckDB，不安装依赖、不改产品配置。

| 执行要求 | 实际结果 |
|---|---|
| 当前Web日线目标、只读事务 | `.env.web.local`经现get_settings解析；远程`152.136.*.251:5432/goldenshare`，连接默认只读，事务REPEATABLE READ READ ONLY，最后ROLLBACK/关闭；未切源 |
| 日线1条聚合SELECT | 两张获准表、九码，窗口2026-10-21至11-03，开市日数10；返回9组，每组实际10/预期10/差额0，合计90；BEGIN、SET LOCAL、ROLLBACK另计3条 |
| 分钟两类各1条聚合SELECT | 正式`/Volumes/datasource/data_lake`，按§10.3指定三日/四周期/两类24路径；每类返回36组，未glob或逐文件查询 |
| 分钟实际/预期及两类差额 | 九码每码bars、indicators均为m30=24、m60=12、m90=9、m120=6；各类459、两类918；72个实际/预期分组差额和36个bars-indicators差额全部0；完整代码计数表见方案§11 |
| 日线40秒工作/50秒全程 | 连接0.093秒、SELECT 1.580秒；worker至关闭/摘要2.215秒，全程至退出2.304秒；无超时/重试 |
| 分钟10秒工作/15秒全程 | bars计数1.341秒、indicators计数0.013秒；worker至关闭/摘要1.592秒，全程至退出1.679秒；无超时/重试 |
| 范围、读写及停点 | 仅3条来源计数SELECT，应用只收到分组摘要；未读价格、DIF或时间键明细，未额外运行识别/预测/校准，未写DB/Lake、未改产品代码；到第1步完成停止 |

已独立复核保存的分组统计及执行记录，代码、日期、根数、差额、查询数和预算均符合§10。第1步数量吻合，满足第2步来源数量前置条件；不宣称指标质量、唯一性、时间位置、算法结果或产品4秒/400ms通过。临时脚本及统计摘要仅在`/private/tmp`，正式结论保留本节和方案§11，不生成reports过程附件。下一步为§2第2步编码，本轮未启动。

### 13.2 第2步开工条件补齐及独立审计

本轮只修改方案和本LLD：第2步限定Python后端/工具及调用测试，第3步同步TS客户端、mjs及五组客户端集成测试；第4步按完整节点清单对账，复用仍适用的通过结果，不强制重跑或重复计数。已分别独立复核工具/测试交接和数字依据，未发现本次修正引入提前迁TS、漏测、步骤冲突或预算冒充。T01—T36、r4核心规则、实际来源范围及产品现有限额保持。

文档完整性、两文档本地链接/代码围栏、case编号、五组客户端测试函数位置和限定差异检查通过；未查询来源、运行测试、修改业务代码或提交。第1步数量前置、后端编码设计、调用方/测试交接及工作区相关路径已具备第2步条件。第4步完整进程时限须在其执行前核定，不将未知耗时填成固定数字；该限制不阻塞当前第2步编码。本轮到文档修正和审计结束。

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

**交接：第2步功能实现、限定回归与独立代码审计完成，测试计时记录限制如上。**管理员review后再进入第3步，按§8同步TS客户端/mjs/全部消费者和页面，不能只改名单；第4步先核定§11.3全程临时调用时限，再做45组合、代表页面及真实性能。未执行前端typecheck/test/build、真实DB/Lake API验收、安装、提交、推送、部署或业务写入。本需求整体尚未验收收尾。
