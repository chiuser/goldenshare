# 财势乾坤r4指数扩展LLD v1

日期：2026-11-04（Asia/Shanghai）。状态：**编码设计已编写，供review；本轮未编码、未执行真实来源或性能验收。**

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
| 真实MACD来自现日线/Gold，不补值、不重算 | §5来源及§10核验 | T08—T10、T34—T36 |
| 分钟返回N，计算额外1000根 | §5窗口不变 | T15、T36 |
| 普通/debug事实一致，辅助按需 | §8保持动态模块及投影 | T24、T28—T30、§11 |
| 上证独立日线波段研究不扩大 | §8.5研究控制器 | T30 |
| 生产关闭、不改鉴权、不部署 | §9及原App装配 | T07、T31 |
| 保留预算，不开启暂缓优化 | §9 | T33、§11性能 |

初版方案/LLD及两索引已随99d876a32提交；本轮仅收敛本LLD与对应方案，索引位置和状态保持。不修改业务代码、测试、配置、已验收旧P5文档及其他未提交内容；不安装、不建分支、不读真实行情、不再次提交。后续按§2逐步推进，不能凭文档完成跳过来源核验进入编码。

## 2. 开发步骤、依赖、失败和交接

| 顺序 | 目标与实现范围 | 开始条件 | 完成/交接条件 |
|---|---|---|---|
| 0 文档及开工审计 | 本方案/LLD、消费者和合同检查 | 当前源码及管理员范围明确 | 方案/LLD一致；无未决业务口径；文档review完成 |
| 1 有界来源核验 | 仅§10四条日线业务SELECT及24个分钟目标文件 | 第0步完成，当前Web目标/权限及既有环境确认 | 九码同窗日线和四分钟来源合格；摘要落回原文档，不能用旧footer代替 |
| 2 核心身份/周期及来源查询 | §3—7类型、DTO、来源、缓存、API及工具签名成套迁移 | 第1步通过、当前工作区无冲突 | 后端正反向及原上证金样本通过；前端新范围尚不开放 |
| 3 前端消费 | §8页面身份、五周期识别/五行预判/debug及研究边界 | 第2步完整，公开字段/异常已冻结 | 类型、限定交互及消费测试通过；不是只修改名单 |
| 4 整体回归和真实验收 | §11自动测试、45组合及代表页面/性能 | 第2—3步独立审计符合LLD | §12门禁对账、管理员review；不自动部署 |

第2步内部先扩核心类型、DTO及30分钟端点，再改来源和查询/预测传递，最后API和直接调用者同时迁移；不得暂时给产品方法保留上证默认参数维持旧签名。第3步最后才启用页面新范围。中间提交若需进行，必须明确尚未可验收，不发布中间混配版本。

失败先停止该单元，不自动重试、切源、补数据、放宽阈值或清缓存掩盖。代码/规则与本文冲突时先汇报并修正文档，不临时加兼容路径。源码保护通过人工规则/差异审计，不读源码SHA作运行校验。无业务写入、迁移或磁盘快照；真实输入或实现改变导致证据不再适用时，只补受影响单元。

续跑按完整单元处理：日线四条SELECT是一个单元，分钟24文件是另一个单元，每个指数/周期的2或4次API请求各是一个组合单元。完整通过的单元保留；未完成的部分只作诊断，原因解决并获准继续后重做该未完成单元，不能拼旧事务的Q1/Q2与新事务的Q3/Q4，也不能换新缓存只补debug后称为热路径。无需新增持久化进度或续跑系统。

本次只扩展r4标的身份及周期，不重构既有普通分钟Hook、缓存或请求状态模型，不为“上游两个接口同时违反合同”等未观察到的问题增加必改项或成组防御测试。执行临时调用复用现有观察方法、内部工作截止及标准外层超时，不另建分阶段信号管理、进程通信或通用监督框架。

外层临时调用只启动一个自有Python核验进程，SQL、DuckDB或隔离API在该进程中执行，沿标准subprocess超时收尾；不嵌套Node、浏览器或额外服务子进程。真实页面验收在§11.4另行进行，不纳入这个临时单元。

所有测试/查询/临时调用在`/private/tmp`本任务目录，禁止将过程结果写入工程或reports。正式结论写回本方案/LLD。单个自动测试执行单元连退出≤60秒；来源50/15秒和正式请求预算见§9—11。失败退出、记录及最后核验均计入各自预算。

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

仅在边界做廉价字段绑定检查：load_entry取得共享entry后、yield前检查calculator的code/period/Spec；`_response`接受显式规范code，装配前检查entry一致（也覆盖内部直接装配调用）；forecast缓存命中检查code/period/版本/hash后继续原完整DTO校验一次。不得修改另一指数对象的tsCode后返回，不为身份检查重放算法或重复构造整份结果。

不匹配按来源合同错误失败，不覆盖原有效缓存。**两类缓存的原发布位置不同，不能合并或一起后移。**series在_load_series完成真实前缀、完整entry/内部响应验证及remaining后按现位置发布；后续普通投影、编码或forecast失败，可保留这份已验证的真实series，不回滚它。forecast候选才遵守：完整预测/装配→投影→序列化与字节检查→load_entry退出最后remaining成功→forecast最后check及原子发布→返回。禁止提前发布forecast候选，亦禁止因本需求后移series发布；原取消异常传播不吞掉，不返回部分成功。

## 7. 预测及直接消费者迁移

`IndexDetailXxmForecastQueryService.build`必填ts_code，交load_entry。READY/EMPTY/DELAYED以及NO_CANDIDATE/PRECISION_PENDING装配均用当前规范code。`_assemble`不再固定上证；缓存和forecastId以实际code生成，普通/debug字段集合、可空、状态和文本来源保持，不增加产品字段。

产品入口及直接消费者全部同次迁移：

| 位置 | 具体动作 |
|---|---|
| 三个API模块 | signals返回dict加code、forecast四项解包，传新build签名 |
| query_service内部build/load_entry/_load_series/_response | 所有调用明确传code，包括内部空结果和历史分支 |
| forecast_query_service | load_entry、缓存、_assemble使用实际code；不重复Universe准入 |
| tests/web三组xxm API/validation测试 | read/build/load_entry包装及替身签名接收并断言code，不用任意kwargs吞掉错传 |
| `test_xxm_snapshot_consumers / r4_internal_results / r4_following_query` | _load_series/_response及read_daily替身迁移；旧hashkey和period位置断言同步 |
| `xxm/daily_window_precheck.py`固定时钟load包装 | 显式接受并转发ts_code、window_rows、requested_end；仍只做原上证研究 |
| `xxm_page_request_audit.mjs` | 调新版forecast client时显式传000001.SH，不扩成九码性能工具 |
| `xxm_page_request_audit.py` | key[2]仍是period；核透明包装无漏参，不新增一轮观察计算 |

保留工具只做签名适配及必要回归，不运行旧研究、r2双组重放或扩工具业务范围。新增必填签名的其他真实调用若在编码前发现，先记录位置及迁移要求，不能用默认上证掩盖。

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

## 10. 编码前的有界来源核验设计

本节是后续第1步执行设计，**本轮未执行**。固定当前方案日期：日线共同cutoff为2026-11-03；分钟三日为2026-10-30、11-02、11-03。仅本轮九码，上证为控制；首错停止。日期若因后续明确需求要换，先同步方案/本节，不能执行时自行追到最新或另切来源。

### 10.1 连接、超时和退出

复用当前Web配置解析获取实际数据库目标，记录脱敏目标与原env-file路径及cutoff；不用库名prod/dg猜主机，不在输出放URL/密码。采用现有解释器和SQLAlchemy/当前PG驱动，临时核验脚本位于`/private/tmp`；不改生产factory、引入daily-wave查询依赖或新建仓库审计框架。若当前驱动/权限不能实施只读及连接/语句超时，则该步骤不得执行，报告具体条件。

临时调用自有一个只读连接，事务为REPEATABLE READ READ ONLY；连接超时≤10秒。每个业务SELECT前设置事务内statement_timeout为`min(10秒, 工作截止剩余时间)`，保留既有驱动取消/关闭方式。4条指业务读取SELECT；BEGIN、事务属性及每条超时设置等控制语句单列实际次数，耗时全部计入预算，不以“四条”隐去。

总计时从启动临时调用前开始，工作截止40秒；连接/读取/校验使用该截止，预留10秒关闭、摘要及退出，总预算50秒。临时调用外层沿标准`subprocess.run(..., timeout=50)`的超时处理，内层正常/错误路径finally rollback、关闭自有连接/engine；超时报告本单元未完成，不自动重试。仅管理本次自有调用，不杀共享Web/DG服务或修改共享连接设置；不为本需求另写逐级信号/进程组监督框架。SQL阻塞由既有驱动statement_timeout约束，不能把Python批次check说成数据库硬中断。

### 10.2 四条日线SQL及校验

现模型合同：`core_serving.trade_calendar(exchange, trade_date DATE, is_open BOOLEAN)`；不是Raw cal_date。日线六列为`ts_code, trade_date, close, macd_dif_bfq, macd_dea_bfq, macd_bfq`，值列可空Float(53)。按这些显式投影，不先DESCRIBE全表或SELECT *。不存在列/类型不符直接失败，不另查源尝试修补。

下列为固定查询结构，九个code和日期均用绑定参数。`wanted`是从正式配置取九码后用于本次查询的VALUES关系，不是新增运行名单；顺序按原配置。不能使用库中全部指数。

| SELECT | 具体结构 | 正常结果/失败条件 |
|---|---|---|
| Q1 日历 | recent取SSE、is_open=true、trade_date≤cutoff，日期降序LIMIT 10；bounds取最早选中日；同SQL用bounds到cutoff自然日序列，与该窗口全部SSE日历做覆盖、重复和is_open非空统计。返回按升序的最多10开市日数组及摘要 | 恰10个不同开市日；窗口首末覆盖、自然日期无缺/重、布尔合法。不能仅过滤开市而忽略非法日历行；空或不足直接报告 |
| Q2 每码范围 | wanted LEFT JOIN日线，以`ts_code`及trade_date≤cutoff过滤聚合COUNT(trade_date)/MIN/MAX；按wanted顺序返回 | 恰9行，包括缺数据code的count=0；任何count=0、首末日期无效、max落后Q1最新开市日均失败。只统计，不导全历史 |
| Q3 首末样本 | 把Q2每码首/末日期去重，构成绑定VALUES(code,date)，JOIN日线，显式取六列，按code/date | 正常≤18行且实际键等于所选首末键；首末同日仅1个。允许正常上限+1作溢出证据，但一旦超量必须失败，不能截断后通过 |
| Q4 同窗尾部 | wanted×Q1同一10个开市日，JOIN六列日线，按code/date；不能每码各取自己最新10行 | 正常恰90键；所选集合的缺日、重复及必需数值异常失败。读取上限91用于超量失败，不截断成功。只证明这10个开市日的覆盖，不检查休市日或其他指数的异常行 |

Q3/Q4逐值检查日期对象、code绑定、close>0、非NULL和math.isfinite；不要把DuckDB的数值函数直接套PG。Q1摘要同时检查selected开市日期的重复；记录请求日期、实际日历窗口、每码count/min/max及至多10个坏键，不输出整份价格。Q2统计count获准不等于导出全历史获准，不能追加全历史读取。

Q1固定SQL如下，cutoff绑定为DATE；一行结果含日期数组和摘要，不另查日历明细：

```sql
WITH recent AS (
  SELECT trade_date FROM core_serving.trade_calendar
  WHERE exchange = 'SSE' AND is_open IS TRUE AND trade_date <= :cutoff
  ORDER BY trade_date DESC LIMIT 10
), bounds AS (
  SELECT MIN(trade_date) AS first_day FROM recent
), expected AS (
  SELECT g::date AS trade_date FROM bounds b
  CROSS JOIN LATERAL generate_series(b.first_day, CAST(:cutoff AS date),
                                    INTERVAL '1 day') AS g
), actual AS (
  SELECT c.trade_date, c.is_open FROM core_serving.trade_calendar c, bounds b
  WHERE c.exchange = 'SSE' AND c.trade_date BETWEEN b.first_day AND :cutoff
)
SELECT ARRAY(SELECT trade_date FROM recent ORDER BY trade_date) AS open_dates,
       (SELECT COUNT(*) FROM expected) AS expected_days,
       (SELECT COUNT(*) FROM actual) AS actual_rows,
       (SELECT COUNT(DISTINCT trade_date) FROM actual) AS distinct_days,
       (SELECT COUNT(*) FROM actual WHERE is_open IS NULL) AS invalid_flags,
       (SELECT COUNT(*) FROM expected e WHERE NOT EXISTS
         (SELECT 1 FROM actual a WHERE a.trade_date = e.trade_date)) AS missing_days;
```

Q1返回的is_open由现BOOLEAN合同保证类型；异常类型/列缺失会使SQL或驱动结果检查失败。open_dates须恰10个不同DATE；expected_days=actual_rows=distinct_days且invalid_flags=missing_days=0才通过，不能以空窗口的全0统计当成功。

Q2—Q4的SQL固定为以下结构：wanted值槽从本次九码按顺序绑定；selected值槽由Q2首末键去重后绑定，最多18组；不插入标的/日期原文拼SQL。

```sql
-- Q2: wanted(ts_code, ord)为九组(:code_i, :order_i)的VALUES。
WITH wanted(ts_code, ord) AS (VALUES /* 九组绑定槽 */)
SELECT w.ts_code, COUNT(f.trade_date) AS row_count, MIN(f.trade_date) AS first_day,
       MAX(f.trade_date) AS last_day
FROM wanted w LEFT JOIN core_serving.index_factor_pro f
  ON f.ts_code = w.ts_code AND f.trade_date <= :cutoff
GROUP BY w.ts_code, w.ord ORDER BY w.ord;

-- Q3: selected(ts_code, trade_date)为首末键的绑定VALUES，日期绑定为DATE。
WITH selected(ts_code, trade_date) AS (VALUES /* 最多18组绑定槽 */)
SELECT f.ts_code, f.trade_date, f.close, f.macd_dif_bfq, f.macd_dea_bfq, f.macd_bfq
FROM selected s JOIN core_serving.index_factor_pro f
  ON f.ts_code = s.ts_code AND f.trade_date = s.trade_date
ORDER BY f.ts_code, f.trade_date LIMIT 19;

-- Q4: codes与dates使用SQLAlchemy expanding绑定，分别9码与Q1的10个DATE。
SELECT ts_code, trade_date, close, macd_dif_bfq, macd_dea_bfq, macd_bfq
FROM core_serving.index_factor_pro
WHERE ts_code IN :codes AND trade_date IN :dates
ORDER BY ts_code, trade_date LIMIT 91;
```

VALUES生成只构造占位符和有限序号；Q2固定9组，Q3用实际去重键数量，禁止把正常上限变成额外循环查询。Q3返回19或Q4返回91立即按超量失败；少于上限仍须逐键集合相等，不能只看行数。

### 10.3 分钟24文件

只构造四频×三日×两类24条精确路径：bars根`gold/quote/major_index_mins`，indicators根`gold/indicator/major_index_mins_technical`，其下`freq=F/trade_date=D/part-000.parquet`。路径存在及实际内容待执行，禁止glob全历史。使用当前DuckDB环境，内存256MiB、线程1、禁临时落盘/自动扩展安装；10秒工作+5秒关闭/摘要，总预算15秒。从启动临时调用前计时，外层沿标准`subprocess.run(..., timeout=15)`处理超时，内层沿既有DuckDB Timer及finally取消计时器/关闭。Timer仅用于SQL中断，不宣称它覆盖连接打开/关闭；不新增分钟专用监督器或修改产品reader。

一次按各类路径集合投影，`hive_partitioning=false`、带filename，只WHERE九码。bars取四键ts_code/freq/trade_date/trade_time和close；indicators取四键、macd_dif/macd_dea/macd、params_key/indicator_version。只核所需列类型（bars.freq INTEGER、technical.freq SMALLINT、date DATE、time TIMESTAMP、指标DOUBLE等），不核无关列全顺序、其他指数或文件mtime。

独立字面端点表为30八根、60四根、90三根、120两根，三日九码生成459个预期键；bars/indicators各459，合计918。核path中的freq/date与内部键相同、无重复、实际/预期双向键差集、两源键集合相同、必需非空有限、正close、params_key及indicator_version符合Web当前合同。合法范围外000680.SH已被code条件排除，不算目标异常。SQL返回摘要及最多10坏键，不回传918行全价格，也不逐码重复调用36次pair reader。

不得因不足918便自动补读其他日期；不得LIMIT 918掩盖重复或额外目标键。15秒是硬截止，不是已测通过。超时先报告；拆分或提高限额须先更新执行设计，不现场继续。24文件同窗通过也不代替1500根前缀、250根校准或产品4秒/400ms验收。

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
| T23 | 在缓存边界放入另一code的合法完整entry/forecast对象 | 即使DTO现允许多码也拒绝错绑，不覆盖旧缓存；不重放算法验证 | 同上 |
| T24 | 五周期普通/debug结果，同code同窗 | 普通字段投影一致；普通无辅助，debug参照/事件/结构关联完整 | API validation、debug contracts |
| T25 | forecast client/adapter传非上证及m30，错code/period/asOf | 请求URL实际code，正确通过、错误拒绝 | client/identity/r1Contract |
| T26 | 激活五行预判，单行失败/重试，minutes=false | 顺序day/m30/m60/m90/m120；重试仅本行；分钟关闭只day | forecast.test、Card |
| T27 | validated=null/串码/北证、初始shell/loading/empty/error；正常九码 | 前者不发r4、后者正常；page-init和kline串码进错误态 | availability/Page/controller |
| T28 | 切指数/日期/debug，旧成功/失败延迟返回；另切主图周期 | 旧结果不回写；识别/研究清理对应owner，主图周期变化不重启五行预测 | Hook/Page |
| T29 | 通过真实scheduler排队普通请求+五行r4 | 轻请求上限2，r4独占；5秒从开始执行算，不把Hook mock五pending当网络并发证据 | scheduler/client |
| T30 | debug上证day手动开研究；其他码/m30/退debug/切页 | 研究仅原范围手动；其他码r4辅助可用、无daily-waves请求/覆盖 | debug/daily-wave/Page |
| T31 | 普通页、debug页、生产构建 | 普通无动态辅助import，debug按需，生产关闭 | dependencyBoundary/useIndexDebugModule |
| T32 | 上证原相同输入及code默认核心数学样本 | 旧指纹/ID/hash稳定；产品构造显式传code | snapshot_consumers/forecast_api/forecast_validation/现规则组 |
| T33 | 17个合法缓存项、冷热及forecast候选最后检查失败 | 共用16项/64MiB正常淘汰；最后失败不发布forecast候选，但已验证series仍可保留，不改原两类发布顺序 | cache/API validation |
| T34 | §10日历缺/重/非法与正常同窗 | 四查询读源范围和摘要准确，正常不误拦；无换源/全历史明细 | 临时来源核验及摘要 |
| T35 | §10两类24文件目标键、合法非目标码 | 各459、合计918；只验九码，异常不得截掉，未读无关列/历史 | 同上 |
| T36 | 真实9码×5周期 | §11.3请求身份/完成时间/状态/计数/大小正确，m30完整前缀及校准有证据 | 真实只读API |

T13/T17复用现独立数学/业务金样本，换成正式合同中的m30合法时间，不用被测端点表生成时点；预测校准长前缀可沿已有高精度Decimal独立参考构造，expected不调用recover_projection/同一求解器。T23只构造真实可能的“另一合法对象被放错key”，不造无意义内部坏状态。不能将所有真实行情强行要求有信号；非空规则路径在独立人工样本保证。

### 11.2 自动测试分组和消费者核对

先核现文件及环境存在再运行。使用现解释器，pytest加`-p no:cacheprovider --basetemp=/private/tmp/<本任务>/pytest`并禁字节码写入。前端保留package.json的类型检查及Vite构建两项职责，但不执行会写工程内构建信息的裸`tsc -b`。固定：根目录执行`npm --prefix wealth run typecheck`；wealth工作目录以现`./node_modules/.bin/vitest run --no-cache --configLoader runner`执行限定/完整测试，`./node_modules/.bin/vite build --configLoader runner --outDir /private/tmp/<本任务>/wealth-dist`构建。runner避免临时config bundle，构建目录是本任务新目录；不清其他产物、不修改package/config、不使用可能下载的npx。每组≤60秒，超时停止查因，不反复盲跑或跳过失败。

临时输出参数依据现安装CLI及[Vitest 3.2.4文档](https://github.com/vitest-dev/vitest/blob/v3.2.4/docs/guide/cli.md)、[Vite 7 CLI](https://v7.vite.dev/guide/cli)和[配置加载说明](https://v7.vite.dev/config)核对；这是后续执行设计，本轮不运行测试或构建。

| 组 | 执行范围 | 说明 |
|---|---|---|
| A 核心/恢复 | scripts/research/index_market/tests下现calculator、r4_rules、following、restore、snapshot_validation、input_validation、product_v1_cases | 原四周期已有金样本加m30必要参数化，按文件切单元，不运行冻结行情回放 |
| B 预测数学 | 现key_point_forecast、p3_forecast_math、forecast_expression_contract、r4_following_forecast、forecast_display | 覆盖m30内部限制及原数学不变 |
| C 查询/API | tests/web/test_wealth_index_detail_xxm_api.py、forecast_api.py、forecast_validation.py、local_routes.py、test_xxm_shared_loads.py | API实际路由、Universe配置和真实query；临时DB/Gold按当前生产合同构造；替代哪层须说明 |
| D 内部消费者/工具 | 现snapshot_consumers、r4_internal_results、r4_following_query、saved_minute_window、p4_audit_tools及`test_xxm_daily_window_precheck.py` | 签名及观察工具透明转发、历史/发布顺序；后者必须覆盖待改固定时钟load包装的新code/window参数，不新造研究用例 |
| E 前端 | availability、controller/Page、xxm及xxm-forecast、debug、daily-wave、scheduler各现测试 | 新client首参和所有adaptForecast options同步；五行fixture/Record补m30 |
| F 通用检查 | 现typecheck、完整test、构建各独立单元；测试禁缓存，构建仅调整输出到上述临时路径；架构三测试及研究依赖、文档检查 | 前端全回归失败不得登记全部通过；无关旧TODO不趁机修复 |

研究依赖用CodeGraph影响面及临时AST导入检查复核本次`src/biz/services/wealth/market/index_detail_xxm`和`queries/wealth/market/index_detail_xxm`：不得引入scripts/research、reports、App或QTF；纯计算不新增DB/文件/网络依赖，runtime既有Foundation限额引用保持。检查只分析当前文件导入，不运行研究或读源码SHA。架构三项为`tests/architecture/test_subsystem_dependency_matrix.py`、`test_platform_legacy_guardrails.py`、`test_operations_legacy_guardrails.py`。不虚构依赖测试文件，也不把整仓测试作为本次最小验收。

需要迁移的前端直接消费者必须全部核到：forecast client测试及工具mjs、adaptForecast的identity/r1Contract调用、ForecastRows字面量、forecastFixtures/xxmFixtures、页面mock、debug contract参数表、原m30 unsupported断言。forecastFixtures显式接收tsCode；m30默认through为前一开市日15:00时，target用独立字面“下一开市日10:00”，不能落入现“非60/90则11:30”分支。逐个改为显式code/五周期，不用放宽断言或任意kwargs让签名错误通过。

### 11.3 45组合的真实只读API验收

在原App本地路由的隔离调用中执行，不启共享lifespan、不重启服务或改生产配置。使用当前Web实际只读DB连接及正式Lake，真实Universe/query/source/calculator/DTO不替代；鉴权凭据层可沿现获准测试身份，须单独说明，鉴权自身由原401/403测试覆盖。禁止以mock service或自造数据宣称真实来源通过。

固定cutoff仍2026-11-03，九码按首页顺序排除北证，每码按day/m30/m60/m90/m120。

- 每组合一次普通识别（day limit=300、分钟limit=500，endDate=cutoff），一次普通forecast（day asOf=cutoff、分钟asOf=cutoff的15:00+08:00），共90业务请求。不得重复读旧行情跑完整r2对比。
- 五个代表组合另各一次debug识别及debug forecast：上证day、上证m30、深证m60、科创50m90、中证A500m120，共10请求。与同组合普通公共字段比较；共100业务请求，不另为“更好看的信号”随意加日期。比较先按本次code/period绑定唯一一对，再复用现`compare_modes`的同源前提：sourceInputId、calendarInputId、indicatorVersion、请求截止、computedThrough及实际窗口相同。固定cutoff不等于冻结历史修订；来源不同时记`not_comparable`、不登记该比较通过，也不追加读源或重发请求来凑一致。这是现比较方法的复用，不新增产品检查。
- 每个组合为独立有界单元，最多2或4请求；每请求客户端5秒、后端4秒/预测400ms保持。从准备临时调用前计时，工作截止25秒，预留5秒关闭/摘要，总预算30秒；外层沿标准`subprocess.run(..., timeout=30)`，内层使用原截止检查及finally清理，超时停止并报告，不发下一组合或自动重试。不直接复用旧固定50/60秒执行入口后宣称30秒，也不为本需求开发新的进程组/通信监督框架；只沿用其透明观察方法。先完成并记录再进下一组合，不积攒全部响应到末尾。
- 使用临时进程自有缓存，不清共享Web缓存。代表组合普通识别首次为series冷路径，普通预测首次为预测冷路径；紧接debug请求作为同窗热路径。记录实际是否命中，不伪称保证命中；不为测冷反复启动相同请求。
- 每次记录code/period、requested cutoff、computedThrough、实际数量、状态/原因、源读取次数/范围、是否缓存、响应字节、请求及预测阶段耗时。复用`xxm_page_request_audit.py::_observe / AuditCollector.projected`的透明观察方式：在原load_entry yield期间按requestId关联实际entry，在原`project_xxm_response / project_forecast_response`调用点取得同一请求的内部输入编号、日历编号、完成时点及code/period，再记录公共结果摘要。现普通预测响应不公开sourceInputId，不从普通JSON取该字段，不新增公开字段/debug请求，也不用entry自己的指纹替代内部响应编号作为预期。只保留本次需要的观察和绑定，不搬入旧工具整套分组/通信校验；不加第二次读源或重放来计时。
- 识别和预测响应的code/period必须等于请求。完成端点、source初始历史状态、events与引用一致。实际无候选/精度待定如实记录，不能作为有价格预测通过。
- 九个m30组合各记录一次真实输入及校准结果，不能只核上证代表。临时观察保留本次forecast实际entry.processed及内部投影取得的请求身份/编号；响应返回后按内部computedThrough截取实际前缀，核末尾指纹等于该请求内部sourceInputId。不是从公开500根响应恢复1500根输入，也不再次调load_entry读源。产品recover_projection已执行则直接记原状态/耗时；仅NO_CANDIDATE未执行时，针对同一前缀补调用一次原函数，使用本单元25秒工作截止的剩余时间，不复用已结束HTTP的4秒remaining。补校准不改产品响应、不作400ms产品预测证据；debug请求不再补第二次。记录后释放本单元数据；不足250或校准失败如实登记，不换源/放宽。
- 有任何性能不达标，首个失败即停止后续真实性能请求并汇报实际路径/数量/阶段耗时；不改预算/自动重试。其他纯静态或已获准隔离回归可继续，但本批真实验收不得报全部通过。

按§2完整单元续跑：一个组合内2或4次请求及其校准/比较共同完成才登记该单元通过；中断部分仅诊断，原因解决并获准继续后重做该未完成组合，不能换新worker只补debug而宣称同缓存热路径。完整通过的其他组合保留。保存每单元小摘要到临时目录，正式文档只记45组合状态表及代表性能，不保存100份完整JSON到reports。接口成功、NO_CANDIDATE和算法非空样本分别报告，不混为一项通过；不新增恢复或续跑框架。

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
| 2.8契约 | 适用：字段集合不变，code/period值扩展，全消费者同迁 | §3—8、T24—T25 |
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
| 性能预算前置 | §9—11全部含退出，超标先报；T33及真实性能 |
| 异常标准 | §3.1现码、普通/debug分层；T03/T04/T24 |
| 用户可见结果 | 标签/时间/五行预判/辅助及生产边界；§11.4 |

模块级例外白名单：**无新增规则例外**。保留已验收产品的显式本地能力及条件预判，不将通用“无主观预测”误解为禁止本已获准的下一根条件范围。没有变更坐标/视觉体系、源字段合同或三工程共享契约，不修改Foundation/DG生产者。

交付逐条记录硬口径→实际代码→测试/真实证据；未完成的来源/性能/页面验收明确列出。完成后只收尾本需求及管理员认可的文档，不自动提交、部署或扩大研究。

## 13. 本轮审计记录及状态

本轮依据当前代码与CodeGraph explore/impact/callers核API、Universe、query/source、缓存、核心/恢复、预测、TS/page/controller/debug及直接工具消费者。合同核验止于源码，未读真实行情/数据库。主方案与本LLD的对应为：方案§1—2→本§1—2；§3→本§5/10；§4—5→本§3—8；§6→本§9；§7→本§11—12；§8→本§2/10—11。

已核对signals规范代码、两类缓存各自发布时序、配置实例缓存事实、主图周期不重启五行预测及m30夹具下一根时点。正常EMPTY的page-init身份字段已核对真实生产者/schema/既有测试，原已设计的身份检查不把正常空行情误判为串码。

本轮按重新核实的必要性收敛执行设计：普通分钟Hook保持现状，不追加同时错码防御或切换当次强制清空；Q4只证明所选10个交易日；真实输入编号从既有内部投影观察点取得，同源后比较公共结果；续跑按完整单元；补入已有daily_window_precheck包装回归。50/15/30秒预算保持，用标准外层超时和既有内部截止收尾，不新增监督/恢复系统。上述调整不改变r4规则或增加开工门槛。

T01—T36仍为36组设计case，不因本次收敛新增普通分钟防御case。文档检查及独立复核只评价设计一致性，不代表这些业务case、真实来源或性能已通过。

收敛后已分别对来源执行设计和前端范围进行独立复核，两文档的范围、依赖、预算及测试口径一致，未发现需要新增业务拍板或扩大实现的问题。文档完整性及限定差异检查通过。

当前可供管理员review；文档完成不等于第1步来源核验通过。后续先按本LLD做有界来源核验及执行前检查，再进入第2步编码；本轮到文档交付即停止。
