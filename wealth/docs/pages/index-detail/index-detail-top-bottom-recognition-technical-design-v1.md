# 财势乾坤顶底识别技术方案 v1

日期：2026-10-28。状态：**已完成P1原合同、文件/调用及迁移清单、独立人工材料与限定检查，交付及独立审计见§14和LLD§16。运行时算法、预测、API和页面尚未迁移；P2未启动，没有清退、真实数据验收或部署。**

对应[产品文档](../../../../docs/product/wealth-top-bottom-recognition-product-v1.md)、[代码级LLD及审计](index-detail-top-bottom-recognition-low-level-design-v1.md)。算法来源为[r4研究方案§15—16](../../../../docs/product/xxm-r4-implementation-plan-v0.1.md)及[r4研究LLD§15—16](index-detail-xxm-r4-low-level-design-v0.1.md)。本文是后续产品化的技术入口，内嵌实现约束和验收要求，不以旧研究计划的通过代替本次产品验收。

## 1. 目标、边界与审计结论

目标是把已批准的r4-v2变成唯一正式计算实现，先仅在本地开发环境使用；保留按需加载的核验工具，最终安全清退r2及依赖它的旧执行代码。生产暂不提供r4日线/分钟识别、预判或核验入口，不能通过debug打开，也不回退r2。

首轮审计只写文档；当前获准P1的合同、独立测试材料及清单准备见§14。后续实施不改来源SQL含义、数据库/湖结构、源指标精度、鉴权或现有分钟行情开放范围，不部署，不新增持久缓存、恢复文件、后台任务、用户算法开关或套件。当前`dev-interface`内其他修改必须保留。

**不能直接删r2父类、复制研究目录到业务目录或只替换版本号。**当前研究r4共享r2的输入、公共方法和恢复流程，预测另有r2规则假设，查询及预测复制又会显式新建产品计算器。唯一r4须覆盖这些实际执行位置，完成后研究工具反过来调用业务计算器，禁止`src/biz`导入`scripts/research`。

### 1.1 代码现状与改动位置

下列路径分别相对仓库根；位置来自本轮当前源码核查，行号仅方便定位，不作为长期合同。

| 当前位置 | 实际行为 | 产品化动作 |
|---|---|---|
| `src/biz/services/wealth/market/index_detail_xxm/calculator.py:XxmCalculator` | 正式r2判别；含公共历史/等待和恢复方法 | 原位置形成唯一正式r4，保留通用类名，不保留R2父类/模式 |
| 同目录`spec.py` | `xxm-direction-v0.1-r2`、最强参照，允许三种研究百分比 | 改正式r4固定规则，移除旧候选配置能力 |
| `scripts/research/index_market/xxm/r4_reference_trial.py:R4Calculator` | 继承上述类；复制step、选择、救援、零日历史/等待；包装研究身份 | 核实规则后迁入产品；等价验收后删除复制类和研究身份包装 |
| 产品目录`types.py`、`snapshot_validation.py` | 公共输入、状态类型、严格解析；无须依赖研究目录 | 保留；恢复仅接受r4合法状态，删除r2独立零段要求 |
| `src/biz/queries/wealth/market/index_detail_xxm/query_service.py:SeriesEntry.calculator_at/_load_series` | 最新复制、历史位置、从空计算、追加计算均显式构造XxmCalculator | 全部统一r4身份、恢复及缓存；不是只改首次新建 |
| 产品目录`forecast_detector.py:clone` | 显式构造XxmCalculator，再恢复快照 | 唯一r4；假设分支不能暗中回到r2 |
| `forecast_entry.py`、`forecast_paths.py` | DIF强弱排序、TOP不会切换的快捷证明、零柱终止、底部专用救援 | 按§5逐项迁移，不通过改文案掩盖计算差异 |
| `forecast_joint.py`、`forecast_query_service.py` | 部分条件必须有色；最新零柱被当成无方向 | 从真实r4逻辑段/状态取方向，零不自动终止 |
| `src/biz/api/wealth/market/index_detail_xxm.py`、`index_detail_minute_xxm.py`、`index_detail_xxm_forecast.py` | 日线/分钟/预测参数严格白名单，目前不接受debug | 同步合同；在App按本地环境装配，生产不进入相关读取/计算 |
| `src/app/api/v1/router.py` | 日线识别、预判和daily-wave现无条件注册；分钟按本地能力注册 | 日线识别/预判/研究也改本地装配。沿已有环境策略，不把日线绑到分钟Lake是否可用 |
| `src/biz/schemas/wealth/market/index_detail_xxm*.py` | 识别完整关联校验；预测硬编码r2、部分换参照仅允许BOTTOM | 内部完整校验保留；按§6区分正常和debug响应，改唯一r4身份及换参照规则 |
| `wealth/src/pages/index-detail/IndexDetailPage.tsx` | 已解析debug=1；研究hooks仍静态接入 | 复用现参数，研究模块仅debug动态挂载 |
| `wealth/src/features/index-detail/chart/IndexChartWorkspace.tsx`、`IndexMinuteChartWorkspace.tsx` | 默认研究悬停；日线默认构造波段研究primitive | 正式状态和研究说明拆开，后者仅debug |
| `wealth/src/features/index-detail/xxm/`、`xxm-forecast/` | 固定r2版本/hash；研究详情和旧预测校验 | 更新正式合同、正常展示和debug解码，不由前端重算波段 |
| `src/biz/services/wealth/market/index_detail_daily_wave/`及配套query/API、Wealth `daily-wave/` | 已独立实现峰谷/平台/色段/价格候选、三角和说明 | 保留，debug按需接入；不强制改r4取价 |

本轮使用CodeGraph `codegraph_explore`核对`XxmCalculator`、`IndexDetailXxmQueryService`和`IndexDetailPage`的调用/消费者，并补读实际源码、导入、动态加载和测试。覆盖Biz→App组合边界、查询→计算/预测→schema、Wealth消费及研究/报告依赖。图索引未替代源码；未运行数据库、浏览器或业务测试。

### 1.2 已有证据与不能沿用的结论

研究r4-v2提交`da4a97ee`，已有上证2023-01-03—2026-10-27的922根日线对照：逐日事件type/direction/route、普通状态/方向与r2相同；参照和历史关联仍有差异。04-18顶钝化同根B→A已与用户提供的04-18/19观察相符。

上述事实不能证明新产品预测、分钟源链、debug合同和删除后工具可用。本次迁移目标是忠实实现已批准r4，不把r2输出、旧报告的预期文件或原软件截图当成所有新测试的自动答案。

## 2. 唯一实现、身份与配置

### 2.1 最终目录和依赖

沿用`src/biz/services/wealth/market/index_detail_xxm/`作为识别与预测业务目录；沿用现API、query、schema和Wealth功能目录。不另建产品r4副本目录、兼容父类或算法工厂开关。

- `calculator.py:XxmCalculator`为唯一正式识别类，直接持有公共输入、Wave、历史和等待能力。
- `snapshot_validation.py`继续解析检查；各算法状态关系检查收敛为r4一套，不加`if r2`。
- 研究观察、人工测试和debug解释调用这一个类；只观察它真实执行的分支，不再复制step以生成解释。
- `index_detail_daily_wave`保留独立职责；业务r4不导入该价格候选，也不依赖研究脚本或QTF。
- App仅组合路由、权限和底层读取能力，不把算法上移App。

### 2.2 配置登记

| 名称/来源 | 目标值、用途与消费者 | 持久化/生效 |
|---|---|---|
| `MAIN_SPEC.algorithm_version`，产品`spec.py` | `xxm-direction-v0.1-r4`；query、恢复、API/schema、前端身份校验 | 代码内不可变；随同一版本交付，无env/数据库/用户配置 |
| `MAIN_SPEC`规则 | 固定1%、max_refs=2、min_bars=2；参照`nearest_then_farther_two`、零中性、零日首次/重新激活、已钝化同根B→A，均进入规范序列化/hash | 规则内容唯一来源；删除最强优先及可选0.75/1.2，不保留旧配置取值 |
| `FORECAST_SPEC.forecast_version` | `xxm-key-point-forecast-v0.3-r4`；预判query/schema/前端 | 同步新的detector hash；预测策略与预算其他值保留，新增r4预测规则身份进入hash |
| `spec_hash`及预测hash | 由各自完整固定Spec规范序列化生成，客户端只登记同次构建的结果 | 不是源码SHA，不读源码证明未修改；本设计不先编造hash常量 |
| 指数页URL `debug` | 仅精确`debug=1`打开；现页面解析后传识别/预测客户端及研究子组件 | 请求级、不持久化；没有环境自动开启或第二个开关 |
| 既有`Settings.app_env`/`APP_ENV`与前端开发环境判断 | 服务端仅显式配置`dev/local`装配r4识别/预判/核验；前端仅本地开发启用，debug还须URL=1 | 不改现默认dev或配置优先级；通过Settings显式字段集合识别未配置，不将默认dev误作开启授权。分钟仍需原配置和数据；日线不附加分钟Lake条件。具体方法/反例见LLD§1 |
| `INDEX_DAILY_HISTORY_LIMIT` | 现有1000，普通日线K线/趋势/九转和研究链共用 | 原常量继续，无新数量配置 |
| `BUDGET`、`FORECAST_SPEC`及日线研究原预算 | 原来源集中维护，见§9 | 不把研究20秒/1000根限制复制成正式识别限制 |

正式事件和历史编号仍由唯一产品计算器生成，包含正式规则身份及原标的/周期/发生位置含义。升级后不得继续声称是研究r4编号或复用r2快照身份。debug开关、窗口起点和报告筛选不进入算法身份，不改变同次事件编号。

## 3. 输入、内部结果、恢复与缓存

1. 正式日线沿用`source.py:read_daily`的IndexFactorPro原始收盘及`macd_dif_bfq/macd_dea_bfq/macd_bfq`；分钟沿用现Gold价格/指标reader按精确时刻成对读取。不换研究CSV作正式来源、不补值、不重算真实MACD。
2. 完成K线、有限数字、非布尔值、正收盘、时间升序唯一、日线日期及分钟+08:00检查全部保留。连续性按现SSE交易日历及分钟端点合同核验，不把缺少SZSE日历误判为阻塞。
3. 正式计算继续读必要历史前段，从来源实际起点建立状态，响应窗口仅裁剪显示。不把页面1000根当MACD重算起点或整个算法历史上限。
4. `SeriesEntry`保留完整内部point/event/顶部历史/底部历史/等待/前缀指纹/内存检查点；正常响应不展示，不等于内部省略。历史asOf仍按当时前缀投影，不能漏出未来确认或后来的结束状态。
5. `calculator_at`、新建、增量追加、预测clone均构造同一个r4；跨周期/标的/来源/规则或旧r2快照恢复拒绝。字段和关系全部成功后才替换进度，失败不改原对象、来件及已返回结果；合法更早前缀可以恢复。
6. 识别计算缓存键保留完整规则hash、来源及周期身份；预测缓存保留detector/forecast hash、行情前缀、asOf和日历身份。新旧身份不混用，旧数据从同源重算，不读旧r2标签或建立快照兼容层。
7. 同一内部r4计算允许供正常和debug投影复用；响应对象分别构造，不把debug对象删字段后原地复用。客户端响应缓存和请求序号必须带debug及版本；并发共享计算不能把一个debug响应交给普通调用。
8. 所有结果、检查点和debug材料仅内存。保留现失败/超时/取消释放及共享加载并发保护，失败不发布半份结果；进程退出下次重算，不增加磁盘恢复。

## 4. 识别器迁移的固定要求

### 4.1 从研究代码迁入什么

迁入`r4_reference_trial.py`的`step`、`_select_eligible_reference`、`_rescue_dull_reference`、`_qualifies_bottom_close`、`_advance_rearm`、`_advance_bottom_history`、`_start_bottom_history`及r4状态合法性检查。保留原业务公共`_start_rearm/_end_rearm`和底部历史安全检查；删除研究`trial_spec/parentState/parentSpecHash`包装以及仅r2需要的零段分支。

这是语义迁移，不能把研究父Spec、研究编号前缀或1000根试验上限照搬。与未变公共方法逐项对账后合成唯一类，不能先调用r2再修改或删除其事件。

### 4.2 每根完成K线的处理约束

| 部位 | 必须保持的行为与反例 |
|---|---|
| 原色/逻辑方向 | `raw_sign`看源hist正负；逻辑段只有红/绿。开头零保留previous但不建段；段内零不换色 |
| 根数/极值 | 真实同色柱才增加count；零仍更新段内收盘/DIF。最高/最低各自日期独立记录，严格改善才更新其发生日期 |
| 历史入池 | 第一根真实反色结束旧段；反色根不加入旧段；同方向池仅最近两个已结束段 |
| 首次选择 | 先过最近B价格门槛，再B完整严格资格，再A自身完整严格资格。没有B/根数不足/相等均不能绕过；TOP当根DIF>0限制保留 |
| 已有DULL | 优先沿已选参照。仅同段、原参照确为B且累计DIF严格突破B时，取消前试A；A合格当根深复制为活动参照，并继续本根结构/取消检查 |
| 切换边界 | 不新增事件、改原DULL时间/编号/原参照；不把历史原参照换A；不回切、不查第三个。A失败本根消失，后根才合格保留先消失再新钝化 |
| 相邻转折 | 仍是上一根实际完成DIF与当前DIF的1%；不能跳过零柱、取两位或比较峰间1%。上一DIF为0保护不变 |
| 真实翻色 | 保留独立确认/突破优先及原事件顺序；结构事件可能发生而根末普通状态已NONE，不能按根末状态抹事件 |
| 首次/已有结构/等待 | 首次根仅DULL；STRUCTURE、WAITING、真实翻色不套用DULL救援；底部等待沿原参照和当根收盘重新合格，不改成累计旧低价自动触发 |
| 历史结束 | 保留研究v2现行顶/底不同退出原因。自然TOP结构回转会结束原顶部历史为`new_top_DULL`，不能把它误记成继续PENDING；原历史价格撤销等事件完整保留 |

规则完整性以产品§4及原研究v2逐根实现为准。新增debug观察不能改变分支执行顺序，也不能重新推测“如果今天首次判断会选谁”来代替真实活动参照。

## 5. 关键高低点预判必须一起改

### 5.1 已发现的r2假设及修改要求

| 文件/函数 | 必须修改 |
|---|---|
| `forecast_detector.clone` | 只复制正式r4；前后状态对象隔离、快照完整校验 |
| `forecast_entry.stable_reference_on_band/reason_for` | 删除强弱排序；最近B价格门槛、B→A固定顺序与真实首次/重新激活一致。零可能属于原段，count只在实际有色时+1；不能用`count+1`和严格原色覆盖零 |
| `forecast_paths._prefix_signature` | 不把hist=0停止；TOP/BOTTOM均按原B失效、A完整合格的同根规则切换。保持固定历史池，不能选新形成的未来峰或全池重新挑强者 |
| `forecast_paths._flat_cannot_switch` | 删除依赖“最强优先/顶部不切换”的原证明。只有按r4证明整个区间不会切换才可启用快路，否则逐段求解和真实step核验，不能默认True |
| `forecast_paths.build_path_relation` | 前缀条件按逻辑同色允许零；切换条件按方向表达，TOP为突破B且仍弱于A，BOTTOM镜像；价格同时满足最近B及A自身要求，严格等号保留 |
| `forecast_paths._outcome`、`forecast_joint` | 不把真实零定义为`ZERO_RESET`；零照常可保持/形成/消失/重新激活。保留数值求解中真正的DIF=0边界和校准误差处理 |
| `forecast_query_service` | 最新零的方向来自r4逻辑段/实际状态，开头全零仍无方向；失效文案删除“零柱结束区间”的旧结论 |
| forecast schema和Wealth adapter | TOP/BOTTOM都可描述一次B→A；from/to、发生时点、严格方向及最多一次一致校验，移除仅BOTTOM及`toDIF<fromDIF`的无条件限制；删`ZERO_RESET`允许值 |

现`nextBarOutcomes`只为底部已有DULL提供下一根完整分类，本次保留该产品范围，不擅自增加顶部新卡片；顶部后续结构预测的内部路径必须正确支持换参照。

### 5.2 求价和复核

- 继续现有“先求首次钝化价格范围，再在既定后续收盘假设下求结构”的策略、最多20根及适用说明。不改变正常页面目标选择和显示政策。
- 分段依据必须包含r4所有会改变结果的边界：B/A价格、累计DIF极值、B/A原参照突破、真实柱色及零点、TOP当根正DIF、当前根有色计数变化、相邻1%及等待价格门槛；每个精确边界单独判断开闭。
- 用仿射关系证明区间内分支及参照一致；不同参照、切换日期或条件不合并后再取中点代表。区间中一点只用于已证明一致的区间核验/示例，不能作为整个区间成立的依据。
- 每条可展示预测的假设路径，用唯一r4的`step`独立复制逐根验证，覆盖所有可能的源精度结果。真实价格根不接受假设值覆盖。边界不确定沿既有`PRECISION_PENDING/UNRESOLVED`说明，不声称确定成立。
- 保留`projection.py`的250根校准、日线来源三位精度0.0005及分钟1e-8等现有来源政策；它们不是已封存的“两位有效数确认”，不得一起删掉。
- 保留现`forecast_text/display_range`的显示口径，本次不恢复旧r3整套整数/编号改造。内部边界和严格等号先算准，对外文字须与当前合法区间一致；不能通过移动显示点位修改实际识别。

若区间证明或200ms预算不能满足，停止报告具体价格区间、发生路径、调用数和耗时，补方案后再实施；不退回r2预测，不扩大误差，也不以抽样通过代替证明。

## 6. 正常与debug接口合同

### 6.1 请求和版本

沿用三个现有接口路径，不新增另一个算法接口；以下仅为本地开发合同。生产按现本地分钟的装配方式不提供这些r4路由，不因带debug参数返回r4或转调r2：

- `/api/v1/wealth/market/index-detail/xxm-signals`
- `/api/v1/wealth/market/index-detail/minute-xxm-signals`（现本地分钟路由，不增加生产分钟开放）
- `/api/v1/wealth/market/index-detail/xxm-key-point-forecast`

已有`daily-waves`核验路由也仅本地装配。后端环境先拦住，不是前端隐藏后仍允许生产读取/计算。本轮不改变正常日线、MACD、九转和趋势接口。

在现严格参数白名单增加可选`debug`：缺省或`0`为普通，`1`为debug；空值、其他值、重复参数仍400。前端普通请求省略该参数，debug页面显式传1。日线/分钟/预测各自原标的、周期、asOf/日期、limit及鉴权约束不变。debug不是权限凭据，仍走原鉴权，不返回连接串、文件绝对路径、凭据或原始SQL。

正式算法/预测版本按§2升级，并更新原接口文档、schema、客户端类型/解码及夹具。以下字段分配是目标合同，P1须写回现API合同；不允许实施时临时自由挑字段，也不保留r2响应兼容。

### 6.2 识别响应

内部完整结果先通过全部关联、日期、身份和数值检查，再构造正常投影；debug只增加辅助投影，不另计算算法。不能删完整校验以便省掉字段。

| 位置 | 普通响应必有 | 仅debug=1返回 |
|---|---|---|
| 根层 | `tsCode/period/algorithmVersion/specHash/source/points/events/meta/dataStatus` | `debug`对象；普通时该字段不存在，不用空数组伪装未加载 |
| `source` | `kind/startTime/computedThrough/initialHistoryIncomplete/indicatorVersion`；前段不完整是正常产品限制提示，不能藏进debug | 原`inputId`移为`debug.sourceInputId`，不输出原路径 |
| `points[]` | `time/close/dif/dea/hist/ordinaryState/ordinaryDirection`，用于按时间严格核对真实图表 | `debug.points[]`按同time记录`activeReference/pendingTopHistoryId/pendingBottomHistoryId/pendingRearmId`；不加入离线完整过程账本 |
| `events[]` | `id/time/direction/type`，事件语义和排序不变 | `debug.events[]`按同id记录`route/fromState/eventReference/relatedTopHistoryId/relatedBottomHistoryId/relatedRearmId` |
| `meta/dataStatus` | `meta.count/responseStart/responseEnd`；`dataStatus.status/message/asOf`，原空值含义和READY/DELAYED/EMPTY不变 | 性能或输入核对详情，不吞掉正常状态 |
| debug历史 | 不返回，不留悬挂历史ID | `debug.topHistories/bottomHistories/rearmRecords`完整所需关联记录；本窗口需要引用的更早记录也须带齐 |

实现位置固定为产品服务目录`response_projection.py`；schema分开内部完整模型、公开正式字段和debug模型。query在原预算内完成完整内部校验、投影、公开校验及一次编码，返回bytes供原API直接发送，不再让框架二次编码；所有直接调用方同步。正常模型校验自己的字段和与图表的原值对应；debug模型继续校验历史/等待双向关联，并按time/id与正式point/event一致。内部`RESEARCH_HISTORICAL_WITHDRAWAL`现事件语义仍保留，正式页面按既有“结构消失”绘制；本次不借旧枚举名字发明新算法或丢事件。

手动离线观察时，可由唯一step记录选峰、当根换参照、相邻转折及等待中实际执行的检查；默认关闭，正常/debug查询和预测clone均不采集完整过程，不加入SeriesEntry、HTTP或缓存。页面debug仍返回上表实际参照、事件route、历史及等待。具体类型、内存预算及正反测试见LLD§7。这样保留离线有用能力，又不把1000根重复过程塞入原1MiB响应，不抬预算或删关联。

普通响应中的事件id是稳定去重所需，不在普通tooltip显示编号。保留的离线观察工具调用唯一r4；迁移`r4_observation.py`中仍有用的真实分支观察能力，不把整个研究比较器搬入，也不新增一套前端推断原因。上述debug合同保留现页面所需依据，不要求把离线完整双组账本加入响应。离线记录明确未执行的检查才写“本根未执行该检查”；页面没有该过程记录时不展示此结论，或说明“当前页面未提供这项检查记录”，不得把未提供误说成未执行。

### 6.3 预测响应

内部先按r4检查完整relations/历史/等待/参照转换和边界，然后投影：

- 普通必有：`tsCode/period/forecastVersion/forecastSpecHash/detectorSpecHash`，`computedThrough/requestedAsOf/mode/dataStatus`，`ordinaryState/direction/status/reasonCode/forecastId`，`targetEndpoint/barsAhead/confirmedAt/confirmedDirection`，`display/applicabilityText/invalidationText/refreshAfterMs`。空值和无候选/不确定/延迟含义沿现合同，不把无解当报错或把出错当无解。
- 仅debug：`sourceInputId/calendarInputId/precisionPolicy/rearmContext/nextBarOutcomes/activation/assumption/targetEntryRanges/targetEntryExclusions/relations/commonConditions/examples`。普通文本必须已经包含对判断有影响的假设、条件及失效说明，不能因详细公式进debug而省掉必要条件。
- debug字段收拢在单独`debug`对象，不沿用“正常字段全返回、页面不显示”的做法。预测结果身份与正式识别身份配套，旧r2或混合hash拒绝。

普通和debug使用同一个内部求解结果和同一条display生成逻辑。开关只控制辅助序列化、传输及加载。对照同输入时，所有公共字段、标签编号和预测文本应完全相同；不跨两次来源已更新的请求强求同一asOf。

## 7. 页面改造和辅助工具加载

### 7.1 普通路径

本节普通/debug区分仅适用于本地开发环境。`IndexDetailPage`沿现URL解析；本地普通页挂载正式识别和预测，不挂载daily-wave研究hooks，不import研究UI/primitive的运行时代码。主工作区保留正式`XxmMacdPrimitive`的标签、圆点及既有布局。

生产不发r4日线/分钟识别、预判和核验请求，不绘标签、圆点、识别悬停或预判卡片，也不显示“未开放/加载中”的空卡占位；URL带debug=1不能绕过。普通日线K线、原MACD指标、九转、趋势和1000根能力保留。

`XxmLayerUi`拆出正常“顶底识别·r4”状态和简要悬停：当前顶/底状态、当根事件及时间；研究参照/编号/历史/等待另放debug模块。正常MACD指标本身的DIF/DEA/柱值保留。加载中、无数据、延迟、错误和重试仍可见，移除“研究指标”措辞，不把故障一起藏掉。

研究区接口类型可通过TypeScript纯类型引用；可执行研究模块不得被普通入口静态import或预加载。debug模块通过动态加载在显式debug时挂载，Hook放进该子组件，不能在同一组件中条件调用Hook。

### 7.2 debug路径

debug子组件仅在本地开发且URL带debug=1时加载，不增加页面调试入口。它协调研究详情、`useDailyWaveReview`、`useDailyWaveCompanionLayers`、`DailyWavePrimitive`、核对说明及图例；主工作区仅接受可选扩展。未开启波段核对时，仅切换debug不重建正式图；退出已开启的波段核对时，按既有`dataKey`和图表生命周期恢复普通数据、日期及图层，不为强行避免重建而保留研究实例，也不新增跨数据原地切换机制。

1. 进入debug才请求识别/预测辅助投影；由现正式请求传debug=1，内部仍共用本次正式r4计算。禁止额外启动r2或比较重放。
2. “波段核对”仍手动开启，之后才执行现“研究计算→读取实际研究日期K线→原值逐日核对→一次显示”流程；debug页面加载本身不自动执行三年波段计算。
3. 保留研究独立日期、独立九转/趋势实例、整链10秒、取消/序号/迟到检查以及不匹配不画三角。研究实际日期不覆盖普通页面日期、右栏、正式预测和普通重试。
4. 保留已认可四种三角画法、起止身份、共享位置及仅画法移动不改算法定义；本轮不重新设计三角。44px研究留白仅研究ready时使用，退出恢复普通图默认行为。
5. `debug=1`移除时，立即使旧请求序号失效、abort、清理定时器和所有辅助结果，卸载研究primitive/监听；若正式请求也需取消，应按普通合同重新加载，不闪回旧研究响应。关闭波段核对、切周期/标的、离开同样清理对应范围。
6. “未找到对应K线的九转标记数量”只在指数详情debug显示；共享九转组件须新增可选显示策略或在指数调用方控制，保持股票等原默认行为。实际九转缺源/无权限/错误仍正常显示。

### 7.3 数量、环境和缓存

普通日线K线、趋势、九转仍传唯一1000常量，研究链仍用同值；股票300、分钟500和后端默认/上限不变。识别继续按图表实际首末日期和实际根数请求。

当前分钟限制位于`indexDetailViewModelAdapter`、`useIndexMinuteSeries`、`useIndexXxmLayer`及页面预测开关；分钟继续受其现有本地配置/数据约束。本次新增要求是**日线r4也只本地支持**：需取消识别Hook中“day无需开发环境”的例外，预判请求和整张卡片、debug研究挂载一起受本地环境控制；App日线识别/预判/研究路由同步本地装配。不能仅关分钟或只藏日线标签。

环境区分沿用已有前端开发判断和后端`Settings.app_env`的`dev/local`策略，不新增独立env或用户开关；不直接复用分钟数据可用性作为日线门槛。生产现不支持分钟K线，本次不开放任何生产分钟。r4生产开放以后另行决定，不作为本轮隐含交付。

客户端识别/预测请求键和缓存加入debug标志及正式版本身份；切debug无旧辅助缓存残留。普通与研究日期仍隔离。浏览器只使用现内存缓存，不增加localStorage/IndexedDB/ServiceWorker结果保存。

URL已开启但debug模块尚在加载或失败时，识别/预测仍请求普通投影；模块ready才请求debug=1及辅助字段，按实际请求模式隔离缓存和取消旧请求。加载工具失败不能堵住正常识别/预判；实际debug响应合同错误则整份失败，不偷偷转普通成功。解码先核对应模式的根字段集合，再核普通字段，最后由延迟模块核debug对象，避免把合法debug键误当成普通响应的额外字段。

## 8. r2清退和研究基建保留清单

### 8.1 按能力处理，不按文件名清空目录

| 范围 | 保留/迁移/删除要求 |
|---|---|
| 产品`index_detail_xxm` | 原位置改为r4；公共types、snapshot_validation、projection、forecast_math、源读取/日历/并发能力保留。替换r2专用选择/零处理及配置，不删除整个产品目录 |
| `r4_reference_trial.py`、`r4_observation.py` | 正式迁入并等价验收后删研究识别副本/研究包装；观察有用逻辑迁为唯一r4的可选离线记录，页面debug用实际参照/历史；删`ObservedR2Calculator` |
| `r4_comparison.py/r4_comparison_records.py`及专属测试 | 删除双组编排、旧配对/推断/格式化；有效引用完整性反例迁现恢复/合同tests，不新增报告框架或“r2”伪基线，见LLD§11.1 |
| `confirmation_only_trial.py/confirmation_comparison.py`及两份测试 | 已确认在唯一r4和工具迁移验收后清退完整两位执行器、r2基线及专属源码SHA/AST保护和测试；先迁出需保留的字面算术样本，历史文档保留。不移除旧保护后让该实验悄悄继承r4 |
| 两位取数最小保留（已确认） | 保留`near_first_review.py`已有独立`decimal_value/quantize_dif`及人工算术测试；必要只迁入原两位测试的字面取数样本，不保留整份旧suite间接依赖r2。不新增取数副本、完整试验或r4两位模式，不声称保留完整旧试验重跑能力；保留函数不等于整文件保留旧选峰/判别逻辑 |
| `reference_rescue.py`、`top_daily_ambiguity.py`、`top_current_close.py`、`top_current_close_selection.py`、`top_reference_priority.py`、`top_return_reference.py` | 删除旧候选算法类及专属执行/比较路径；必要通用取窗/格式化/观察先抽出，不通过改继承父类冒充原实验 |
| 这些变体的调用链 | 核`cross_index_daily`、`reference_rescue_paths`、`reference_rescue_forecast`、旧replay、bottom_history_acceptance和配套tests/README命令；逐个删旧用途或迁通用能力 |
| `frozen_inputs.py` | 旧expected/runner消费者迁清后整文件删除，其源reader含缺DEA补算；不新增替代reader。原CSV/JSON/manifest保留，完整真实源由现load_source/read_case/read_window读取，不补值，见LLD§11.2.1 |
| 独立峰谷/取窗/量图/两位算术工具 | 按LLD§10/11.2逐函数保留，去旧判别和源码保护；local_extrema去结果writer/exec，notebook仅返回未执行字典；reference_window仅原事实且去qdif；same_bar旧判别清退，不整文件照留 |
| 独立数学工具 | top_activation_math仅保留1%字面/Fraction，并手算修正其旧目标零柱开边界，包含合法零且不包含价格0；top_activation_real_math仅meet/minus/interval，去最强选峰entry_domains/proof；forecast_expectations去旧verify_changed_forecast oracle，仅保留纯算术。新r4求价以独立字面规则验，见LLD§11.2.1 |
| daily_window及原路由核验入口 | daily_window只留validate/read_window/isolated_client，去旧capture/账本/输出和待删acceptance依赖；page_request/forecast_display在原文件迁正式本地装配及仅RAM核验，去--candidate/--output及完整HTTP/VM落盘。Node用实际1000常量和normal/debug新合同，不冒称浏览器验收，见LLD§11.2.3—4 |
| `local_extrema_study.protected_files()`、`near_first_review`旧路径保护 | 不再从历史run.json继承可执行源码保护依赖；历史manifest原文保留供审计，新工具不把其源码清单当运行前提 |
| `reports/xxm_macd_structure_20261011/` | 内有独立旧replay/候选算法和调用脚本；逐文件识别，旧实现/重放代码删除，纯输入/结论文档按证据保留，不按目录含reports豁免 |
| `reports/xxm_bottom_history_precheck_20261016/`、`xxm_forecast_range_precheck_20261014/`、`xxm_minute_reader_optimization_20261014/`、`xxm_forecast_precheck_20261014/`、`xxm_forecast_range_implementation_20261014/` | 含旧候选/复制预测或旧执行器；编码前核实实际文件名并列清单。有用通用只读校验迁出后删除旧代码，不留`.py.txt`伪封存 |
| Notebook和动态入口 | 只import日线峰谷扫描器的`review.ipynb`保留；含旧算法可执行单元迁文档或删单元。`xxm_forecast_display_audit.py --candidate`的旧动态候选加载清退，正常r4接口核验保留 |
| 测试/文档 | 有效人工规则、安全/恢复/API/前端测试迁r4独立预期；旧r2零段/最强选峰/旧身份专属断言与执行夹具清退。设计和开发文档保留并标历史，不改写旧成绩 |

上述是能力范围，LLD§10/11.2已固定逐文件/函数及消费者交接，**不是可直接执行的通配符删除命令**。P1复核实施当日文件和消费者，按既定保留/迁移/删除清单核查；测试、CLI、动态import、生成Notebook的文字、报告脚本、未跟踪文件均覆盖。工作区有大量未提交研究文件，路径在清单之外不得删除；若与他人修改冲突，停下说明。

两位最小保留已确认。现代码依据：`quantize_dif`只负责Decimal朝零截两位有效数，Q(0)=0；其必要数值校验和人工算术测试一并保留，不依赖产品计算器。保留正负数、零、跨数量级和相等值等字面样本，expected不由被测函数生成。这里只保留研究过的取数方法，不把它当作作者现行规则已证实，也不进入正式r4判别。

完整`TwoDigitTurnCalculator`同时继承产品类、复制r2 step并执行旧SHA/AST核验；保留整套并删掉保护会改变历史试验含义，复制r2到旁边又违反清退决定。因此仅保留上述独立算术能力，完整旧试验从Git/文档追溯。逐文件/函数清单须先解除依赖并迁出样本，待唯一r4及保留工具验收后再删旧执行器；本轮未改变或删除任何代码。

### 8.2 清退完成定义

- 维护中的工作区没有r2算法类、step副本、旧两位/r2执行器、算法别名、隐藏参数、r2默认值或运行时回退。
- 通用路径`calculator.py`指向唯一r4，所有活动调用方理解它是r4，不把新类输出写进旧r2命名的实验。
- 历史文档可以出现r2、旧版本及旧路径作为事实；禁止把旧实现搬进Markdown代码块/`.txt`作为可重建的封存副本。已有正常历史说明不因关键字删掉。
- 目标旧模块的已知`__pycache__`等生成代码缓存一并有界清理，范围仅本次清退模块；不清共享解释器、依赖或用户其他文件。历史Git对象不删除、不重写。
- 保留工具能在旧文件不存在时通过正常人工输入运行；不能靠临时兼容文件、源码SHA跳过或吞错通过。

## 9. 预算、失败与验收开销

| 能力 | 保留预算/边界 | 核验要求 |
|---|---|---|
| 正式识别 | `runtime.BUDGET`：4秒总时限、并发2、响应≤1MiB、缓存≤64MiB/16系列、返回≤2000；默认日300/分500 | 覆盖冷/热、历史位置、增量、源码输入修订后重建；正常/debug完整校验、投影和最终序列化均计入，不能仅计step |
| 预测 | `FORECAST_SPEC`：计算200ms、响应≤32KiB、最多20根/未来90自然日、刷新60秒 | 含复制、恢复、区间划分、精度分支、核验、debug投影和序列化；请求时限仍用现识别读取保护 |
| 日线研究工具 | 后端业务读取后8秒，前端计算/K线核对整链10秒；既有主范围≤800、K线请求1000上限 | 不因进入debug放宽；失败/中断后再次完整请求及最终核对包含在既定计时中，不做磁盘续跑 |
| 普通K线 | 本机有界20次P95对照既有800ms预算 | 1000请求链不退回300；真实不足1000如实记录，不能补行 |
| 前端识别/预测 | 既有5秒请求取消和调度规则 | debug显隐取消、迟到丢弃和清理也纳入观察，不留下旧标签/说明 |

debug辅助响应仍受同一响应上限；超限明确失败，不静默截断关联或临时提高预算。若单次现有最大合法窗口无法在预算内完成，报告实际根数、字节、路径、冷/热耗时后review设计。

保留原错误类别和明确400/404、来源/校准/超时/合同错误语义，文案由“研究指标”改“顶底识别”。EMPTY不是异常兜底；真实数据不匹配不画错误标签，提示失败并保留正常行情。是否需要增异常码先同步异常码登记，不临时发明。

本方案不新增网络/数据库写入。后续真实核验使用有界、明确周期/日期和投影字段的只读查询及既有隔离App方法，避免重启共享服务；全局读取若确有需要另按根AGENTS审批。

## 10. 开发批次和停点

| 批次 | 具体动作 | 本批交接/禁止项 |
|---|---|---|
| P1：合同和清单 | 把§6写回现API合同，列完整字段/空值/错误及全部消费者；枚举§8逐文件删除和迁移清单；核实本轮涉及的全部脏文件；准备独立人工r4预期和迁移前r4依据 | 仍不删实现。各消费者不能自由拼字段；有规则冲突先停，不要求再讨论已拍板r4规则 |
| P2：唯一r4 | 替换产品计算器/Spec，整合安全恢复；迁全部新建/历史/增量/预测clone位置及内存身份 | 使用人工序列验核心和恢复；没有research→product反向依赖，不提供r2模式 |
| P3：预测和合同 | 修§5所有数学假设、方向、schema，完整内部校验和正常/debug投影；前端类型/解码同步迁 | 不保留“识别r4、预测r2”；不发布中间混合版本 |
| P4：页面与保留工具 | 本地正式文案/四周期支持、生产禁用全部r4、debug懒加载；解除旧依赖 | 保留三角和正常行情；本地API/浏览器验收及生产构建和路由禁用反例均通过 |
| P5：清退与最终审计 | 全部调用已迁移后删除清单内旧执行代码/专属测试/生成缓存，更新命令和索引，完整回归 | 删后再验正常r4和debug；交付后停止，提交/部署按后续指令，不自动执行 |

迁移等价核验以**已批准r4-v2**而非r2作基准。迁移前需要的有界r4输出可在验收进程内保留，对同输入的迁入结果核对规则、标签、参照、历史与等待；正式/研究身份不同只允许明确的编号映射，不能忽略参照差异。不得在产品升级后仍调用继承新类的旧研究包装，冒充“迁移前r4”。长期回归采用独立可手算字面预期；不保存一份r2实现来维持对照。

任何批次失败，保留工作和事实、说明具体输入/错误/影响，不发布未完成版本。不通过运行时回退r2绕过；必要代码回退属于后续发布管理，不在本方案引入双算法。

P1的目标响应fixture以无默认值的显式身份参数准备，不用当前r2 hash冒充r4；P2固定Spec后统一生成并填入身份，业务预期仍手写不重生成。缺必要真实分钟证据时P4记未验收，不能用日线替代或自动进P5清退。详见LLD§11.2.5。

产品/技术大面及两位最小保留范围现已确认。代码级LLD已按上述顺序细化并独立审计，P1原合同和独立fixture准备已完成，实际记录见§14及LLD§16。运行时迁移和清退尚未进行；后续按批次推进，已拍板事项不再作为待问项。

## 11. 测试和编码门禁矩阵

| 硬要求 | 代码点 | 正向/反向验收 |
|---|---|---|
| 唯一r4、原值和完成K线 | calculator/types/spec | 四周期独立字面输入；拒bool/NaN/无穷/逆序/重复/未完成；不得出现两位转换、数据补算或可选1%门槛 |
| B→A最多两个 | 选择/救援 | B合格即停，B价未过不查A，B失败A完整合格才选；A价不合格/缺失/第三个更强仍不选；严格相等反例 |
| 同根切换连续 | step/历史记录 | 顶底同段B被突破且A合格，活动参照当根A、events无消失/新DULL，原记录B不改；A当根失败/次根才合格保留先消失后钝化；STRUCTURE/WAITING/真实翻色不误救援 |
| 零中性与两根色柱 | Wave/step/rearm | 红零红、红零绿、开头全零、仅1根有色、零日满足首次/结构/消失/重激活；前一实际根为零仍参与1%比较 |
| 历史/等待完整 | 公共方法及恢复 | 顶部自然回转原历史结束、底部等待和当根收盘门槛、原参照离池仍合法；历史asOf不带未来，坏关联/缺参照先拒不污染 |
| 复制/增量一致 | calculator_at/load/clone/cache | 从空、合法更早恢复、分段追加和连续计算逐根一致；旧r2/跨来源/跨周期/损坏快照拒绝后正常继续；并发两请求不共享可变对象 |
| 预测同r4 | §5所有位置 | 顶/底切换、零日根数、首次/等待、原值等号，精确边界及内部样本与唯一step一致；真实来源精度不确定拒绝、禁止以中点包办不同路径 |
| 合同和版本 | API/schema/client/adapter | 正常/debug独立手写样本，旧hash/混合预测身份/未知或重复debug/非法空值拒绝；EMPTY/DELAYED/错误不混为一类 |
| 默认不加载辅助 | 页面/动态模块/客户端 | 无debug及开发环境普通URL均无研究UI、请求、动态加载、primitive、辅助响应；debug=1才加载，点击波段才计算；debug=0/缺省为反例 |
| 本地支持、生产禁用 | App环境装配/日线识别Hook/预测/研究入口 | 本地日线不依赖分钟Lake，分钟按既有配置和数据；生产无日线r4标签/悬停/预判卡/请求，debug=1不绕过；直接访问API不进入源读取/计算，不回退r2，正常日线仍可用 |
| debug不改变业务 | 投影/缓存/观察 | 同输入普通公共字段与debug公共字段完全相同；同算法事件编号一致；逐根解释指向真实活动参照，悬挂历史/事件ID和串缓存拒绝 |
| 生命周期/原图 | 研究hooks/工作区 | 加载中移除debug、重试、切标的/周期、离开后无迟到复活；普通右栏日期不变；保留44px/四种三角/1000链及股票300/分钟500 |
| 安全清退 | §8清单/全部调用 | 删除前引用逐项迁，删后import/动态候选/CLI/Notebook/生成文字无旧执行引用；保留峰谷工具在旧文件不存在时仍可运行，旧r2结果不可当新预期 |
| 性能及产品来源 | runtime/forecast/真实接口 | 有界源样本+真实原路由最小链；记录日期、数量、字节、耗时及浏览器请求，不能用mock声称真实集成 |

现有研究`test_xxm_r4_reference_trial.py`和安全测试中有效用例迁到唯一产品类；删除r2独立零段及双组专属断言。后端`tests/web/test_wealth_index_detail_xxm_api.py`、`test_wealth_index_detail_xxm_forecast_api.py`以及前端`xxm`、`xxm-forecast`、`IndexDetailDailyWave`测试同步换真实r4合同。旧JSON不能只替换version/hash就成为r4预期，须逐条说明独立依据。

实施时运行本模块定向测试、共享恢复/查询/预测回归、三份根架构测试、Wealth全量测试/typecheck/build及文档检查；每组超过60秒检查原因，不安装依赖，不为通过而跳过失败。真实分钟不可用时单列未覆盖范围，不拿日线成绩补齐。

真实浏览器确认普通入口没有预载debug专用代码/请求；1600/1440/1280宽度、45/180根、拖至301根以后及日线/现可用分钟检查正式标签、条件、悬停、debug开关和取消。用户review页面是交付门禁之一，不由本轮文档检查替代。

## 12. 设计原则对应与开工条件

| 原则 | 本方案落点 |
|---|---|
| 事实源单一 | 源行情不重算；唯一正式r4，debug解释同一计算 |
| 契约先行 | §6完整目标投影，P1写回接口合同后再改消费者 |
| 配置一致 | §2集中Spec/预算，debug复用现URL，无持久开关 |
| 默认行为显式 | 普通保留正式能力，辅助不加载；分钟开放边界不扩大 |
| 排序/筛选确定 | B→A最多两个、严格比较及既定历史窗口 |
| 性能前置 | §9原预算，含复制、失败重做和最终校验 |
| 异常清楚 | 真实故障普通显示，不吞错成EMPTY，不静默删关联 |
| 用户可见验收 | §11标签、预判、请求、图层和删后工具均核验 |

**算法、本地/生产范围、普通悬停、debug方式及两位最小代码保留均已确认，P1准备已完成。**配套LLD已列明方法/字段/处理顺序、逐文件清退和有效能力落点；P2开工须复核当日引用和工作区，再先捕获迁移前依据，不把已完成的LLD细化再留开发临时决定。预测区间证明、四周期真实接入及性能仍须实施时验收，当前未运行、不能预判通过。发现会改变已定范围的事实再说明，不重复询问已拍板事项。

## 13. 文档交接

本产品文档和本文作为r4本地集成/清退入口。原r4研究方案/LLD继续记录B1/B2/v2及922根证据，文首注明新的产品决策；“保留r2离线基准”不再作为后续执行要求。两位方法仅保留独立取数、必要数值校验及人工算术测试的范围已确认，不能以此恢复完整旧r2试验。

P1同步原识别/预测API合同，后续各批把已实施/已测试/未验收事实写回本文；原v0.5当前r2代码总结在正式迁移完成后标为r2历史实现说明，不提前改成已上线r4。历史报告、截图观察和开发文档不删除，不拿旧状态描述现实。

## 14. P1本次执行与交付（2026-10-28）

已按批准范围落实§10的P1五步，逐项产物及独立审计见LLD§16：三个原合同分别补日线§10、分钟§8、预测§36；登记当前文件/query调用/迁移去向；现主题tests新增四份独立业务/响应材料及检查。37个人工核心案例、独立Fraction上下文、7类识别及8类预测状态均准备完毕，hash显式必传，不以当前r2身份冒充r4，预期不由旧/新算法生成。

本批材料检查162项通过（0.09秒），三架构16项通过（13.30秒）；分别只证明材料/独立算术和依赖边界。独立交叉审计修正了分钟未来目标与barsAhead、补齐真实翻色不救援/价格回落保持等反例，并明确数学入口前提；未改变已定算法。完整对账、文档检查及未覆盖见LLD§16.3。

本批未修改运行时计算器、Spec、API、预测、页面或环境配置，未读取真实行情、捕获旧r4基准、删除旧实现、提交或部署。停在P1，不自动进入P2；P2获准后须先捕获真正迁移前r4-v2，再改父类/Spec。P1不证明产品预测、分钟来源、真实接口、性能或页面已经验收。
