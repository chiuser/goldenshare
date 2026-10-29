# 财势乾坤顶底识别低层设计 v1

日期：2026-10-28；更新：2026-10-29。状态：**P1、P2限定验收完成；P2成功路径证据见§19.6，提交后发现的失败清理计时缺口已按§20修复并独立复核，最终成绩见§20.4。P2原中断保留于§18。P3预测/公开合同、P4页面及真实来源、P5清退尚未推进；本轮修复未提交或部署。**

依据：[产品文档](../../../../docs/product/wealth-top-bottom-recognition-product-v1.md)、[技术方案](index-detail-top-bottom-recognition-technical-design-v1.md)。研究规则依据为[r4研究LLD§15—16](index-detail-xxm-r4-low-level-design-v0.1.md)。本文件细化编码和验收，不恢复r3、两位确认或其他旧算法。发现与上述已确认决策不同的真实情况时，先说明并同步原方案，不能现场改变规则。

## 0. 本轮产物、后续实施范围和硬要求

本文首版及文档审计维护本组三份文档和直接索引；已完成的P1合同、独立测试材料及清单见§16。§17保留上轮文档修正；P2已完成核心迁移及限定验收；原中断事实见§18，§19保留此前成功路径证据，失败/中断清理缺口与修复和最终验收见§20。不读取真实行情、不清退、不提交或部署。后续各批的“新增/修改/删除”不代表现在已执行。

后续仅在当前`dev-interface`工作区分P1—P5推进，保留清单外修改。不安装依赖、不新建分支/worktree，不改变源SQL含义、数据库/Lake结构、鉴权或生产分钟开放范围。输入、计算结果、进度和debug资料仅内存；不增加数据库写入、结果文件、恢复文件、后台任务、用户设置或浏览器持久缓存。

### 0.1 逐项对账入口

| 编号 | 方案硬要求 | 本文编码要求 | 验收归属 |
|---|---|---|---|
| R01 | 唯一正式r4；原r2最终清退 | §2—3唯一`XxmCalculator`，§10逐文件处理 | 核心人工/删后引用/迁移对账 |
| R02 | 本地四周期上证；生产日线也禁用 | §1路由和前端同时限制，§8环境交接 | 本地无Lake日线成功、生产直接API和页面反例 |
| R03 | 不新增env或用户开关 | §1、§2配置登记及完整Spec | 缺配置/未知环境关闭，正常显式dev/local可用 |
| R04 | 真实完成根和原指标，不补算 | §2输入、§4来源/历史前段 | 非法输入拒绝、原值和连续性 |
| R05 | 真实反色，零中性且不计根 | §3逻辑色段/首次/历史/等待 | 红零红/红零绿/全零/零日首次和重激活 |
| R06 | 累计收盘与DIF极值各自日期 | §2 Wave、§3更新与同向历史池 | 极值不在同一天、并列保留原日期 |
| R07 | B优先、A备选，最多两个 | §3首次选择及固定候选集合 | B价未过/等号/第三个更强都不能绕过 |
| R08 | 已钝化同根B→A、取消前处理 | §3救援次序、§6预测路径 | 当根连续/晚一根失败/无回切或第三个 |
| R09 | 1%相邻实际DIF及前值0保护 | §3转折/回转/真实翻色优先 | 恰1%/不足/前根零柱/首次只DULL |
| R10 | 历史、等待、恢复保留真实语义 | §3—5完整内部模型 | 旧历史冻结、asOf无未来、坏恢复不污染 |
| R11 | 预测整体迁r4，不能只改显示 | §6逐函数、切点/条件/精度证明 | TOP/BOTTOM/零/全部边界/唯一step核验 |
| R12 | 正常和debug同一计算/编号 | §4—5内部结果和显式投影 | 同源公共字段、文本、ID完全相同 |
| R13 | 普通悬停简洁，正常故障可见 | §5、§8正式状态/当根事件/时间 | 无参照编号/等待；EMPTY≠error |
| R14 | 仅显式debug动态加载辅助 | §8独立模块、解码和请求身份 | 默认无import/请求/primitive；关闭和迟到 |
| R15 | 波段手动开始，独立日期/预算 | §8研究状态表/图层交接 | 未点击不计算；研究日期不污染右栏/预判 |
| R16 | 四种三角、1000根保持 | §8现画法/常量和共享图表 | 股票300/分钟500不变、301根后可用 |
| R17 | 两位仅保留独立取数和算术 | §10函数级保留/专属执行器清退 | 无产品调用、无旧源码依赖，字面算术 |
| R18 | 历史材料保留，旧程序安全删 | §10明确代码和原始材料清单 | 先解依赖/迁有效样本，后删代码和对应缓存 |
| R19 | 不读源码或SHA证明r2没改 | §10独立预期/内存迁移对账 | 无运行时源码保护；源数据身份核验仍保留 |
| R20 | 预算含最终校验/编码和重试 | §4、§9完整时限及失败处理 | 冷热/历史/源修订/超限不返回半份成功 |
| R21 | 所有消费者同步，不留兼容双轨 | §4—5、§8、§10—11 | API/query/schema/前端/CLI/Notebook清零 |
| R22 | 依据代码，不夸大研究成绩 | §11—14事实和待验收分列 | 日线922根不能替代分钟/预测/产品验收 |

### 0.2 当前实现与影响面

本节为P1时迁移前的源码核对；P2后的当前实现及验收见§19.6（§18保留原中断），不把本段旧r2描述当作迁入后的当前事实。

迁移前产品`calculator.py`为r2；研究`r4_reference_trial.R4Calculator`继承它且重写部分方法。正式查询的从空、增量、历史位置恢复，以及预测`clone`都直接构造产品类。预测还包含最强优先、零柱结束、顶部不换参照等旧假设。前端当前静态接入波段研究，App当前无条件注册日线识别、预判和波段研究。不能只改一个构造器或版本文字。

本次使用CodeGraph `codegraph_explore`核对计算器继承和查询/预测、App装配、IndexDetailPage/两个图表工作区及Wealth消费者，再用源码/AST/引用搜索补查动态入口、报告和Notebook。图索引不能代替当前文件。未改变目录分层：Biz只依赖自身/允许的Foundation能力；App做组合；Wealth消费HTTP；研究可使用正式业务类，反方向禁止；QTF不参与。

## 1. 环境、路由及配置生效

### 1.1 服务端唯一环境判断

在现`src/app/api/v1/router.py`新增私有纯函数`_xxm_local_environment_enabled(settings: Settings) -> bool`：

```python
return (
    "app_env" in settings.model_fields_set
    and settings.app_env.strip().lower() in {"dev", "local"}
)
```

必须显式提供环境值才开启。当前`Settings.app_env`默认dev；直接只看值会使缺失配置误开启本地功能。保留全局默认值及`get_settings()`现来源优先级，不为本功能修改它们。当前`get_settings`缓存一次，并将选中env文件解析值作为构造参数传入，文件中的APP_ENV因此优先于同名进程变量；本功能只使用最终Settings及其显式字段集合，不另读`os.environ`重做优先级。配置改变随现App重启生效，本轮不自动重启服务。

本轮已做纯配置对象核查：未传APP_ENV得到`app_env='dev'`且不在`model_fields_set`，显式local/prod则在集合中。未读业务数据。开发测试须另覆盖显式dev、空串/未知、文件与进程冲突，以及只给其他配置而缺APP_ENV的反例。`model_fields_set`依据Pydantic官方明确“显式设置的字段”，不是`exclude_none`或自定义布尔猜测；原项目配置加载方式仍以当前源码为准。

新增`_include_local_xxm_routers(target_router, settings) -> None`也在同文件，调用上述函数，false时不注册以下路由：

| 路由 | 本地开启条件 | 生产/未知/缺环境 |
|---|---|---|
| `xxm-signals` | 上述环境判断；不依赖分钟配置或Lake | 不注册，原路由404，不进入源/计算 |
| `xxm-key-point-forecast` | 上述环境判断；日线正常，分钟仍受现分钟能力依赖 | 同上 |
| `daily-waves` | 上述环境判断；原上证日线研究合同不变 | 同上 |
| `minute-xxm-signals` | 上述判断 **且** 原`resolve_index_minute_capability`可用 | 同上；原普通分钟K线仍按现配置，不被本功能打开 |

四条r4/核验路由统一只在_include_local_xxm_routers注册：移除原无条件日线/预判include，以及_include_local_minute_router内原minute-xxm的重复注册；后者其他普通分钟/九转等路由保持原策略。该函数只读取传入的同一Settings来解析分钟capability，将可用lake_root或None捕获到forecast/minute的依赖闭包，不在请求时另读一份全局配置。原_index_xxm_lake_root/_forecast_lake_root仅有的两处旧调用随之迁完后删除，避免保留两套取配置方式。日线普通K线、九转、趋势和MACD路由不移动到这个条件。生产OpenAPI也不含这些r4路径；`debug=1`不是环境或权限凭据。保留原鉴权，路由不存在不能改成回调r2或返回假EMPTY。分钟预测能力不足仍按原`XXMF_NOT_SUPPORTED`404，日线不可因分钟Lake缺失而被拒。

### 1.2 前端能力与配置审计

只复用`import.meta.env.DEV`和URL精确`debug=1`。生产构建即使连接本地后端或带debug，也不加载本功能；开发前端连接生产后端也不能绕过服务端路由限制。配置、Spec/预算及消费者见§2、§8—9；无新增env、数据库配置或运营项。

| 现来源 | 默认/作用域/消费者 | 本轮处理 |
|---|---|---|
| `Settings.app_env`/APP_ENV | 全局既有默认dev；App组合环境 | 不改默认/优先级；r4仅显式dev/local |
| 原本地分钟启用设置与Lake能力 | 既有配置/数据规则；普通分钟reader及分钟识别/预测 | 复用，不复制成日线限制，不开放生产分钟 |
| `import.meta.env.DEV` | 构建环境；指数详情启用判断和请求hooks | 生产false同时去入口、卡片、请求和图层 |
| URL `debug` | 默认关闭，请求级，不存储 | 精确1启用；普通客户端不传，HTTP显式0合法 |
| `MAIN_SPEC/FORECAST_SPEC/BUDGET` | 本目录不可变代码定义 | §2和§9集中登记，消费端不得重定义规则 |
| `INDEX_DAILY_HISTORY_LIMIT` | 既有1000；指数日线三条请求链及研究 | 保持；不是新配置，股票300/分钟500不改 |

## 2. 唯一计算器、类型与Spec

### 2.1 位置和调用接口

唯一类仍为 src/biz/services/wealth/market/index_detail_xxm/calculator.py:XxmCalculator；直接实现r4，不继承旧类，不留R2/R4选择器。保留step/snapshot/restore业务签名；构造器仅增加§7只读记录参数：

- XxmCalculator(*, period: XxmPeriod, source_identity: str, ts_code: str = "000001.SH", spec: XxmSpec = MAIN_SPEC, record_decisions: bool = False)。
- step(bar: XxmBar) -> XxmStep。
- snapshot() -> dict[str, Any]。
- restore(snapshot: dict[str, Any]) -> None。
- _id(*parts) -> str，仍按algorithm_version/spec_hash/ts_code/period/发生位置生成24位摘要；不读源码SHA。

保留本目录types.py的XxmPeriod、XxmBar、Wave、XxmStep、XxmBottomHistory、XxmRearmRecord；XxmRearmRecord.endReason删除旧zero允许值。色段结束只因真实反色而记color_flip；price_requalified重新激活、reference_dif_break参照失效仍按§3.2分别结束等待，不能一起删掉。公开debug RearmDto同步这三种合法原因。Wave不加日线研究候选字段；sign只能是-1或1，start/end是逻辑色段首/末实际输入时间，count只计有色柱，price/dif及各自发生时间独立。零柱可使end延长，不增加count。保留原始float输入与既有比较顺序，不引入Decimal两位确认、舍入、百分比过滤峰谷或新的价格窗口。

XxmCalculator实例状态完整保留：period/source_identity/ts_code/spec、wave、history={1: [], -1: []}、state、reference、previous、pending、pending_bottom_history、pending_rearm、processed。history各方向按时间升序，仅保存最后两个已结束逻辑色段。结果仍由调用方保存逐根point/event/历史更新，计算器不持有全量结果副本，不写文件/数据库。

XxmBar.validate现已有completed字段，必须保持completed is True；数值仅int/float且不含bool、必须有限，close>0；日线严格ISO日期，分钟保留+08:00。时间顺序由step检查，交易日/分钟端点完整性由query/source检查，不能混成一个输入层。非法输入在任何状态更新前抛ValueError；不得用默认值补缺列、把未完成根当完成根或重算实际MACD。

### 2.2 Spec的精确收敛

修改产品spec.py:XxmSpec，不保留研究0.75/1.2取值。固定字段：

| 字段 | 值或处理 |
|---|---|
| algorithm_version | xxm-direction-v0.1-r4 |
| dif_turn_pct/max_refs/min_bars | 1.0/2/2 |
| reference_policy | nearest_then_farther_two |
| active_reference_policy | same_bar_near_to_far_on_dull_break（研究r4-v2已有名称） |
| zero_policy | neutral_real_opposite（研究r4-v2已有名称） |
| allow_zero_activation/allow_zero_reactivation | True/True |
| macd_parameters/histogram_multiplier | (12,26,9)/2 |
| color_flip/flip_requires_turn | True/False |
| historical_price_only/fixed_expiry | True/None |
| bottom_history_policy | 原closed_origin_close_break_v1 |
| same_segment_bottom_policy | 原current_close_rearm_v1 |
| bottom_dull_reference_policy | 删除；不得保留prebreak_strongest_eligible_v1或以该字段暗中选择旧政策 |

__post_init__逐字段检查类型和值均等于声明默认值；bool不能通过int相等绕过。spec_hash沿当前规范asdict+sort_keys+固定分隔符序列化产生。所有规则字段都进入hash，运行预算留runtime.BUDGET，不把研究20秒/1000根等预算混入产品算法身份。

FORECAST_SPEC.forecast_version最终固定xxm-key-point-forecast-v0.3-r4，其余现行20根、250根校准、源精度、显示策略、200ms和32KiB等值保持。预测Spec增加固定reference_path_policy="r4_nearest_two_neutral_zero_same_bar_switch"，登记这次路径规则变化并纳入forecast hash；它不是用户参数或另一份可选算法。

身份分两批落实，不能只按“Spec已写清”就同时改两个Spec：**P2只修改MAIN_SPEC并生成识别hash；P3才修改FORECAST_SPEC并生成预测hash，同时迁预测模型、HTTP和前端身份消费者。**当前`index_detail_xxm_forecast.py:ForecastResponseDto.forecastVersion`仍是r2 Literal，预测query直接用FORECAST_SPEC填它；若P2先改预测版本而把模型留到P3，连EMPTY/CONFIRMED返回也会被旧模型拒绝。P2不得修改FORECAST_SPEC、预测schema或前端身份常量来提前绕过这一矛盾。两批之间只是未发布开发状态，不作为可运行的产品整体交付，不发布识别r4/预测r2混合版本。两项hash均由各自完整Spec生成，不预填伪造值；具体消费者及验收时点见§11.2.5。

### 2.3 方法迁移对照

| 迁入/保留方法 | 代码依据与要求 |
|---|---|
| step/_select_eligible_reference/_rescue_dull_reference | 迁入scripts/research/index_market/xxm/r4_reference_trial.py的r4-v2语义；按§3顺序，不复制研究类壳 |
| _point | 研究r4的逻辑段方向；源零时不能把活动方向清空 |
| _qualifies_bottom_close/_advance_rearm | 迁入r4零柱允许逻辑及当前close门槛 |
| _advance_bottom_history/_start_bottom_history | 迁入r4仅真实红色离开原绿段的规则 |
| _start_rearm/_end_rearm/_validate_bottom_history_snapshot | 原公共方法保留并按正式新_id生成关联，不复写成r2父类调用 |
| _validate_restored_state/_validate_rearm_snapshot | 用研究r4检查替换r2颜色相等/零结束假设 |
| restore/snapshot/_id | 保留公共检查后发布方式；去研究trial_spec/parentState/parentSpecHash/research_hash包装 |
| _rescue_bottom_dull_reference | 删除，不能与新_rescue_dull_reference同时执行 |

## 3. step的严格顺序

设s=逻辑色段方向，r=raw_sign=(hist>0)-(hist<0)。以下顺序就是已批准r4-v2顺序，不能为了观察/解释重排。第7—10步必须在“无已有事件且not blocked”的同一个互斥`if/elif/elif`链内；不能把它们实现为顺序独立的if。原参照突破产生CANCEL并清空ref后，本根不再进入首次选择；否则会把已有STRUCTURE的取消错误改成同根新DULL。

1. bar.validate(period)，然后拒绝time<=previous.time。保存old_wave、old_state；事件变量为空。
2. old_wave=None且r=0：只更新previous和processed，返回NONE点，无色段、无历史、无事件；开头零不能借未来颜色补段。
3. true_flip=(old_wave存在且r==-old_wave.sign)。仅首次有色或true_flip新建Wave。真实翻色时先用本根DIF与旧活动参照检查：旧s*(bar.dif-ref.dif)>0，产生CANCEL/dif_break_on_flip；否则旧state=DULL，产生STRUCTURE/color_flip。已有STRUCTURE真实换色而未突破不另发确认。事件方向/参照属于旧段。
4. 关闭旧段：深复制加入history[旧s]并截取最近两个；旧段end保持此前最后一根（可为零），不纳入反色根。新Wave首根为bar.time、count=0、price/dif初值为当前bar；state/ref置NONE/None。段内r=0不执行本步。
5. 更新当前Wave：count+=int(r!=0)，end=bar.time；s*(bar.close-wave.price)>0才更新price/price_at；s*(bar.dif-wave.dif)>0才更新dif/dif_at。相等保留原发生日期。价格和DIF日期不得强绑。
6. 先执行_advance_rearm。它返回(blocked, reactivated, records)。重新激活时产生DULL/reactivation，保存原等待参照；本根不得再走首次选择或结构确认。仍等待/参照失效时blocked=True，禁止普通首次分支绕过。
7. 仅没有预先事件且blocked=False：执行_rescue_dull_reference，再取更新后的ref。救援严格见§3.1，不先产生CANCEL再删事件。
8. 若ref存在且s*(wave.dif-ref.dif)>0：CANCEL/dif_break，state/ref清空。否则有ref及previous，执行相邻转折：basis=previous.dif、delta=s*(bar.dif-basis)、gate=abs(basis)*1.0/100。basis!=0且state=DULL、delta<0、-delta>=gate时STRUCTURE/dif_turn；basis!=0且state=STRUCTURE、delta>0、delta>=gate时回转。前值0不触发两类1%，但不跳过本根/不回退前一有色根。
9. 结构回转：TOP直接DULL/dif_return，原活动参照保留；BOTTOM先以bar.close检查§3.2。当前close合格则DULL/dif_return；不合格则_start_rearm，发STRUCTURE_DISAPPEARED/dif_return、state/ref清空。不得用此前累计低价代替当前close。
10. 仅进入上述互斥链时ref就不存在、且未命中取消/转折分支时，才检查首次资格：wave.count>=2、history[s]非空且TOP要求bar.dif>0；_select_eligible_reference选中后深复制，发DULL/activation，首次根仅DULL，不在同一根追加STRUCTURE。BOTTOM不加bar.dif<0限制。已有活动ref未达到转折时不能跌进首次选择。
11. 先构造普通事件（含old_state及事件发生参照），再推进顶部历史，再推进底部历史、必要时新建底部历史；最后构造point并更新previous/processed。同根普通事件和历史价格撤销的顺序维持原样，不能因根末state=NONE抹去真实翻色结构事件。

### 3.1 首次选择与同根救援

_select_eligible_reference(wave, history):
- 无history或count<2返回None。
- pool=list(reversed(history))[:2]，pool[0]=B、pool[1]存在时=A；不sort。
- 若s*(wave.price-B.price)<=0，直接None，不执行A的DIF检查。
- 从B到A逐一检查s*(wave.price-candidate.price)>0 AND s*(wave.dif-candidate.dif)<0；首个合格即返回，失败不补第三个。

_rescue_dull_reference(bar,old_wave,old_state):
- 只有old_state==self.state=="DULL"、self.wave is old_wave、ref非空、没有pending_rearm、r属于(0,s)才继续。
- 必须s*(wave.dif-ref.dif)>0才检查；等于原B不切换。
- pool长度恰为2且ref.reference()==B.reference()；活动ref已是A则不再选/不回切。
- 调用同一个_select_eligible_reference；结果恰等于A时deepcopy给reference。不新增DULL/CANCEL，不修改原事件、历史、等待的原参照；继续本根后续检查。
- A本根失败则第8步照常CANCEL。A下一根才合格可产生新的DULL，但不得抹掉前根CANCEL。
- STRUCTURE、WAITING、true_flip、首次激活均不执行这种救援。

### 3.2 底部当前close与等待

_qualifies_bottom_close(bar,reference,nearest_price)仍签名不变：
hist<=0、wave.sign==-1、count>=2、bar.close<min(reference.price,nearest_price)、wave.dif>reference.dif同时成立。这里使用当前close；零柱不补count。

_advance_rearm保持返回签名，顺序：
- 无记录：(False,None,())。
- 实际红柱或wave.start变了：_end_rearm(SEGMENT_ENDED,color_flip)，返回不阻止新段普通处理；无zero结束原因。
- bar.dif<保存reference.dif：INVALIDATED/reference_dif_break，blocked=True，不检查价格、不改选A。
- 必须bar.time>disappearedAt，且当前close合格才REACTIVATED/price_requalified，state=DULL、reference恢复保存对象；blocked=True使本根不追加结构。
- 其他仍WAITING，更新observedThrough并深复制。等号不使参照失效；红后又绿不能沿旧等待接回。

### 3.3 顶/底历史完整行为

顶部pending每根更新ageBars、negativeBars按实际r<0、zeroBars按r==0、colorChanges按true_flip。退出优先：
1. bar.dif>originalReference.dif → original_reference_break；
2. 普通TOP DULL/STRUCTURE → new_top_DULL/new_top_STRUCTURE；
3. 确认后bar.close>pricePeak → historical_price_break，同时追加RESEARCH_HISTORICAL_WITHDRAWAL。
其他延续。新TOP STRUCTURE随后建立新pending，保存结构所属旧/当前红段的pricePeak和日期，不能取反色首根price。

底部pending：
- 仅bar.hist>0首次设置leftOriginAt；零不算离开原段。
- 退出顺序为原参照DIF严格突破、当前STRUCTURE_DISAPPEARED、同根新BOTTOM DULL/STRUCTURE接替、已真实离段后确认日以后bar.close<保存priceLow的历史价格撤销。
- 只有最后一种追加RESEARCH_HISTORICAL_WITHDRAWAL；结束记录本身不能伪造成一个新标签。
- 新BOTTOM STRUCTURE保存原绿段priceLow、原参照及结构事件ID；若确认根为真实红柱，leftOriginAt就是该根，否则None。
- 正常events不能过滤历史撤销；事件绘制、原历史冻结和根末普通状态是三个不同事实。

## 4. 内存进度检查、查询与缓存

### 4.1 内存进度和复制

snapshot字段严格固定：specHash/tsCode/period/sourceIdentity/processed/wave/history/state/reference/previous/pending/pendingBottomHistory/pendingRearm；不接受研究外壳、缺字段或额外字段。

restore顺序保持“先独立解析，再语义验证，全部成功后一次赋值”：
1. parse_xxm_snapshot核身份、新Spec、类型、有限数字/正价格、严格时间及字段、池数量/顺序、引用属于历史池、state/ref配对；processed=0必须全空。
2. BOTTOM历史用保留方法验证结构_id/历史_id、保存参照、时间、所属原段和离段关系。保存原参照可早于最近两个池，不能因离池误拒历史；活动reference则必须在池。
3. 等待用迁入r4方法验证：仅WAITING、BOTTOM/dif_turn、stateNONE/refNone/pendingBottomHistoryNone、previous.hist<=0、wave.sign=-1、wave.end==previous.time、原段匹配、nearestPriceGate等于最近旧谷price、保存referenceWave属于历史池、wave.dif>=保存dif以及全部ID/时间关联。不得因零日拒合法等待。
4. TOP历史_id按正式_id复核；各记录原始计数及日期检查保留。
5. r4状态：wave=None仅允许全零前段，stateNONE、无ref、无history/pending/等待，previous若存在必须hist==0；wave非空必须sign±1且previous.raw_sign∈(0,wave.sign)。拒绝r2零段。
6. parsed的九个进度字段最终赋值到self；失败只抛ValueError，来件、原self和此前结果完全不变。未知程序错误不得吞成合法空状态。

clone(c)保持forecast_detector.py签名：仅构造正式XxmCalculator，完整snapshot→restore，不能浅复制可变对象。query的calculator_at、初始加载、增量加载、预测clone统一此流程；不从r4研究模块import。

### 4.2 查询、asOf、身份与缓存

#### 4.2.1 原来源及进度交接

原source.py的read_daily/read_minutes/calendar_dates/assert_continuous不改变来源口径。日线读取IndexFactorPro原close和macd_dif_bfq/macd_dea_bfq/macd_bfq；分钟按ts_code/freq/trade_date/trade_time严格配对。保留完整已有历史前段与已完成根筛选，页面窗口/1000不是识别起点。当前source限制、业务日期、日历和湖分区边界不放宽。

SeriesEntry保持现字段。_load_series在旧source_signature/已完成上限/日历完全一致时复用；新source前缀不相同或origin变更从空重算；仅真实追加可从独立snapshot继续。每source_batch_rows=1000个真实根保存内存checkpoint。全部计算和校验成功才发布新SeriesEntry，不原地修改旧points/events/history/等待。

calculator_at(count,check)：
- count须0..len(processed)。
- count=0时返回新建的空r4；不访问任何checkpoint。count等于实际末尾且非0时，独立恢复当前snapshot。
- 其他位置取offset=count//1000*1000。offset=0时新建空r4直接重放[0,count)，不读取或伪造checkpoint[0]；只有offset>0才读取该位置checkpoint，核其processed和previous.time后恢复并重放[offset,count)。仅使用该位置以前的真实根。
- 每1000循环及复制/恢复前后check；无磁盘checkpoint、无后台续跑。

#### 4.2.2 asOf必须对应同一前缀

保留forecast_query_service当前asOf校验：必须开市、已完成且不晚于业务日期允许截止；先完成这些校验，再取n=bisect_right(processed.time,expected)，expected为空时n=0。n>0才读取processed[n-1]及fingerprints[n-1]；普通状态、活动确认、等待、输入指纹、未来日历、校准和求解都针对n。

预测n=0表示空源或合法asOf早于来源首根：through/ordinaryState/direction/sourceInputId/calendarInputId均None，返回EMPTY/SOURCE_EMPTY，不读取末根、不恢复当前wave求方向、不校准或求未来日历；requestedAsOf及LATEST/REPLAY模式保留真实请求。违法asOf仍按原规则400，不能借空源放过日期检查。识别响应的空前缀同样不得取[-1]；其debug.sourceInputId仍沿现查询的sha256(b'empty')空源身份字符串，不能与预测的None混写。

识别_response保留截至through的历史投影：晚于through的confirmed记录不返回；endedAt>through还原PENDING/WAITING及None结束原因；底部leftOriginAt>through还原None；ageBars按真实前缀重算。debug中的活动参照从对应point取，不能读最新calculator.reference冒充旧日期。当研究工具额外解释历史根时，同样从该根之前的checkpoint重放唯一正式r4，不调用旧研究父类或前端推断。

正常、debug都先验证完整内部结果，再用合同规定字段投影。n>0时源fingerprint取n-1，不取最新指纹；n=0走上述空前缀分支。普通events按实际展示时间窗保留原顺序，历史参考记录可以跨左侧窗口但不得跨through带未来状态。

#### 4.2.3 返回合同、缓存与forecastId

按§5集中合同：现完整schema收敛为Internal*，normal/debug是两种封闭公开模型；普通没有debug字段，debug必须有对象，合法None仍保留。response_projection纯函数显式新建字段；query build最终返回bytes，不再返回公开DTO。顺序为完整内部模型校验→显式投影→公开模型校验→一次model_dump_json并检查字节/时限→返回编码body。API用Response(content=body)发送，OpenAPI声明公开normal/debug联合；所有直接build调用同步按bytes解析，不留旧返回类型兼容。缓存命中也必须完成本次投影/公开校验/单次编码并计入4秒与预测200ms；缓存只省已完成内部求解，不绕过当前请求的最终检查。


保持计算缓存key的连接/来源身份、period、MAIN_SPEC.spec_hash及共享加载业务日期/完成端点；debug不改变计算身份。预测内部缓存key继续含连接/湖身份、period、detector hash、forecast hash、前缀fingerprint、expected、asOf和未来calendar hash。

XxmCache.get_forecast/put_forecast改为存取“完整内部预测结果”，深复制返回；normal/debug公开DTO在缓存之后各自新建。不得把普通投影缓存成缺少内部关系的求解结果，也不得原地对debug对象删字段。本轮不新增第二套公开响应缓存；现有内部计算缓存与客户端按模式隔离的缓存已覆盖需求。

forecastId沿现digest算法，从同一完整内部payload（含sourceInputId/calendarInputId、mode、requestedAsOf、求解结果等）在投影前生成一次；不得把debug参数/辅助容器有无放入digest。同输入、同asOf和同模式的normal/debug公共字段及forecastId完全相同；LATEST和REPLAY本来就有mode/asOf差别，不强求同ID。新规则hash隔离旧缓存和旧进度，不接受旧hash然后重新解释。

_latest source_updated或未来calendar_updated即沿现key失效；prefix之后的修订不得改变较早asOf的指纹/识别事实。缓存失效重算仍计原时限。ERROR不缓存成EMPTY。

## 5. HTTP、内部模型及普通/debug响应的完整交接

### 5.1 文件、方法和调用顺序

修改既有`src/biz/schemas/wealth/market/index_detail_xxm.py`及`index_detail_xxm_forecast.py`，保留其中完整数值/时间/历史/等待/表达式检查；完整模型统一改名为`InternalXxm*`和`InternalForecast*`，不把已有模型先删成公开最小字段。特别是query当前按`XxmPointDto.model_fields`挑字段，必须同步改用内部类型，否则历史ID会在完整校验之前丢失。

在`src/biz/services/wealth/market/index_detail_xxm/response_projection.py`新增两个纯函数：

- `project_xxm_response(internal: InternalXxmResponseDto, *, debug: bool) -> XxmResponseDto | XxmDebugResponseDto`。
- `project_forecast_response(internal: InternalForecastResponseDto, *, debug: bool) -> ForecastResponseDto | ForecastDebugResponseDto`。

每个公开嵌套类型均封闭字段集合，Pydantic沿现`extra='forbid', allow_inf_nan=False`；数值字段在解析前检查`type(value) in (int, float)`（整数计数严格int），拒绝bool/字符串数字/NaN/无穷，同时允许101这样的合法int价格；禁止用`Any`、任意dict透传内部结果。普通模型没有`debug`字段；debug扩展模型的`debug`必填且非None。根模型使用两种模型的联合，不用`exclude_none=True`省略全部None，因为合法必有的空时间、空方向和参照空值仍须返回。

识别query `build(session, *, period, start_date, end_date, limit, debug=False, now=None) -> bytes`；预判query `build`保留现业务参数，新增同样`debug=False`，也返回bytes。所有直接调用方、API测试及验收工具同步改为解析bytes，不留旧DTO返回兼容。流程固定：

1. 在原时限内取得同一完整内部结果/缓存；按r4内部schema全部校验。
2. 预判从完整内部结果生成一次`forecastId`和普通display文本，debug不得进入该身份。
3. 显式逐字段新建公开dict→对应公开模型校验；普通请求不复制、序列化辅助数组。
4. 一次`model_dump_json().encode('utf-8')`；检查最终字节上限及原截止时间后返回该bytes。
5. API声明公开联合`response_model`供OpenAPI，实际用`Response(content=body, media_type='application/json')`复用已校验/已编码正文；现no-store等响应策略保持。不得返回DTO让框架在预算检查后再序列化一次。

预测缓存仅保存已完整校验的内部结果，读取深复制、按本请求重新投影/公开校验/编码；正常和debug不各算一遍，也不把普通删减结果放回完整缓存。debug投影失败即本请求失败，不回退普通成功；反过来也不得直接透出未校验内部对象。

### 5.2 请求参数

| 路由（均在现index-detail前缀） | 保留参数与新增参数 | 行为 |
|---|---|---|
| `xxm-signals` | 原`tsCode,period,startDate,endDate,limit` + `debug` | period仍只day，原默认日线300，上限2000 |
| `minute-xxm-signals` | 原`tsCode,freq,startDate,endDate,limit` + `debug` | freq仍60/90/120，默认500，上限2000 |
| `xxm-key-point-forecast` | 原`tsCode,period,asOf` + `debug` | day/m60/m90/m120，保留LATEST/REPLAY和完成时刻检查 |
| `daily-waves` | **仅**原唯一`tsCode=000001.SH` | 不新增debug参数；本地环境注册+前端debug手动请求控制；原严格422不变 |

前三个参数解析器继续拒未知参数、重复参数和非法空值。`debug`缺省或文本`0`→False，文本`1`→True，空/true/01/2及重复均原请求错误400。不使用Python字符串truthiness。普通客户端省略debug；debug明确传1。标的按既有大写归一化，仅上证可用，非法格式400、其他合法标的404。鉴权与日期范围原语义保持，无另一个r4接口/算法参数。

P1写回[现日线合同](index-detail-api-contract-v1.md)、[分钟合同](index-detail-minutes-api-contract-v1.md)和[预判实施/API章节](index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md)，同步全部实现与消费者；旧r2历史验收仍标历史。下述字段是完整目标，不留编码时另选的自由口径。

### 5.3 识别公开字段

| 类型 | 必有字段及类型 |
|---|---|
| `XxmResponseDto` | tsCode='000001.SH'、period四周期、algorithmVersion='xxm-direction-v0.1-r4'、specHash=MAIN_SPEC.spec_hash、source、points[]、events[]、meta、dataStatus |
| `XxmSourceDto` | kind='daily_factor'或'minute_gold'，startTime/computedThrough为本周期time或None，initialHistoryIncomplete:boolean，indicatorVersion:int或None（日线None、分钟现数值版本）；**无inputId** |
| `XxmPointDto` | time、close:number>0、dif/dea/hist:number有限、ordinaryState=NONE/DULL/STRUCTURE、ordinaryDirection=TOP/BOTTOM/None |
| `XxmEventDto` | id:string、time、direction=TOP/BOTTOM、type=DULL/STRUCTURE/CANCEL/RESEARCH_HISTORICAL_WITHDRAWAL/STRUCTURE_DISAPPEARED |
| `XxmMetaDto` | count:int≥0、responseStart/responseEnd:time或None |
| `XxmDataStatusDto` | status=READY/DELAYED/EMPTY、message:string或None、asOf:time或None |
| `XxmDebugResponseDto` | 全部普通字段 + debug:XxmDebugDto |
| `XxmDebugDto` | sourceInputId:string、points[]、events[]、topHistories[]、bottomHistories[]、rearmRecords[]；离线额外观察按§7，不加入HTTP |
| debug.points[] | time、activeReference:Reference或None、pendingTopHistoryId/pendingBottomHistoryId/pendingRearmId:string或None |
| debug.events[] | id、route、fromState=NONE/DULL/STRUCTURE、eventReference:Reference或None、relatedTopHistoryId/relatedBottomHistoryId/relatedRearmId:string或None |
| Reference | startTime/endTime、price:number>0、dif:number有限；时间升序、方向由所在记录/事件约束 |

普通point保留DIF/DEA/柱供图表原值核对；普通event id用于去重，不在普通悬停显示。历史撤销枚举仍正常画“结构消失”，不因含RESEARCH删掉。route完整值仍为activation/dif_turn/dif_return/color_flip/dif_break/dif_break_on_flip/historical_price_break/reactivation。

debug历史字段保持现完整模型，不另建丢信息的“简化历史”：

- topHistories：id/confirmedAt/confirmationRoute/pricePeak/pricePeakAt/originalReference/status/endedAt/endReason/observedThrough/ageBars。
- bottomHistories：id/structureEventId/confirmedAt/confirmationRoute/originSegmentStart/leftOriginAt/priceLow/priceLowAt/originalReference/status/endedAt/endReason/observedThrough/ageBars。
- rearmRecords：id/direction='BOTTOM'/bottomHistoryId/structureEventId/structureConfirmedAt/structureRoute='dif_turn'/segmentStart/nearestPriceGate/reference/disappearedAt/observedThrough/status/endedAt/endReason。
- 顶部原因为original_reference_break/new_top_DULL/new_top_STRUCTURE/historical_price_break；底部及等待保留现r4对应原因；等待status为WAITING/REACTIVATED/INVALIDATED/SEGMENT_ENDED，endReason仅price_requalified/reference_dif_break/color_flip或合法None，**不接受zero**。底部完整endReason为original_reference_break/new_bottom_DULL/new_bottom_STRUCTURE/historical_price_break/structure_disappeared或合法None，status为PENDING/ENDED；顶部同样PENDING/ENDED。内部模型按§3原方法逐个对应，不新增退出政策。

正常校验：严格字段、身份、时间格式/升序唯一、原数字、state方向、meta和source截止及EMPTY约束。debug在此基础上要求其points.time与普通points逐一相同、events.id与普通events逐一相同；引用的历史可早于可见窗口，必须存在且截至同through，不能把形成事件不在窗口误判悬挂。继承原双向关系/状态/ID/结束日期检查，不让history中的未来退出漏入旧asOf。

### 5.4 预测公开字段和所有内部嵌套类型

`ForecastResponseDto`普通根的**全部必有字段**：

- 身份：tsCode/period/forecastVersion='xxm-key-point-forecast-v0.3-r4'/forecastSpecHash/detectorSpecHash。
- 时点：computedThrough/requestedAsOf/mode/dataStatus；time格式按周期，requestedAsOf可None；mode为LATEST/REPLAY，dataStatus为READY/DELAYED/EMPTY。
- 当前及结果：ordinaryState/direction/status/reasonCode/forecastId；ordinaryState可None或NONE/DULL/STRUCTURE，direction可None或TOP/BOTTOM，forecastId为现完整内部结果digest；reasonCode可None。
- 目标：targetEndpoint/barsAhead/confirmedAt/confirmedDirection，按状态可None；barsAhead非空时1..20。
- 用户说明：display/applicabilityText/invalidationText/refreshAfterMs。display含statusLabel/targetText/conditionsText/asOfText；适用与失效文字仍为必有字符串。刷新60000ms。

`ForecastDebugResponseDto`增加必有debug对象，字段集合：sourceInputId/calendarInputId/precisionPolicy/rearmContext/nextBarOutcomes/activation/assumption/targetEntryRanges/targetEntryExclusions/relations/commonConditions/examples。其中sourceInputId/calendarInputId为string或None，rearmContext/nextBarOutcomes/activation/assumption为对应模型或None；precisionPolicy为rounded3_guarded/full_float；其余关系/范围/示例均数组。原可空字段保持显式None；无记录数组是[]，不伪造未知对象。正常响应完全没有这些内部字段或debug空对象。

保留现状态READY/CONDITIONAL_ENTRY/ENTRY_ONLY/NO_CANDIDATE/CONFIRMED/PRECISION_PENDING/DELAYED/EMPTY，以及现reasonCode的ZERO_WAVE/NO_REFERENCE/NO_ENTRY_RANGE/NO_CONFIRMATION_IN_HORIZON/SOURCE_DELAYED/SOURCE_EMPTY/CALIBRATION_FAILED/ROUNDING_BOUNDARY/NARROW_INTERVAL；ZERO_WAVE只表示尚无逻辑色段，不能把最新零柱一概归入它。

下表是完整内部校验和debug校验共同使用的现嵌套结构；字段不可因普通不显示就删掉。number均有限，范围边界可按原合同None表示无上界。

| 现类型 | 字段/处理 |
|---|---|
| PriceRange | lower/upper/lowerInclusive/upperInclusive；正价格、单点须两端闭合、空域拒绝 |
| CloseRange | PriceRange + route(dif_turn/color_flip)/displayLower/displayUpper/displayPlaces(2或4)，内部边界与显示边界检查保持 |
| Expression | affine(pCoefficient/cCoefficient/constant)；scale(arg/factor)；abs(arg)；sub(args恰2个)；round3(arg为affine/guard)；按现递归封闭联合，不接受任意运算 |
| Condition | left/op(lt/le/eq/ge/gt)/right，表达式合法；eq用于前值0等真正边界 |
| EntryRange/EntryExclusion | entryRangeId/priceRange/reference；exclusion含priceRange/reason；参照按B/A整域证明 |
| Activation | endpoint/ranges/exclusions；ranges+exclusions覆盖正价格且不重叠 |
| Assumption | policy='entry_range_then_flat'/activationEndpoint/intermediateEndpoints/intermediateCloseExpression |
| TargetEntryRange/Exclusion | entryRangeIds/priceRange；exclusion另reason；只引用实际存在的入口ID |
| ReferenceTransition | endpoint/fromReference/toReference；最多1，方向、时点、B→A见§6 |
| NextBarBranch/NextBarOutcomes | branchId/priceRange/outcome/reference/route；总对象endpoint/initialReference/branches；仅已有BOTTOM DULL，正价格全分区 |
| Relation | relationId/entryRangeIds/entryDomain/reference/initialReference/referenceTransitions/route/prefixConditions/targetConditions |
| CommonCondition | relationId/entryRangeIds/entryDomain/reference/route/closeRanges |
| Example | preClose/entryRangeId/closeRanges（每项含relationId） |

旧原因名`WRONG_COLOR_OR_ZERO`改`WRONG_COLOR`，`COLOR_OR_ZERO`改`OPPOSITE_COLOR`，仅实际反色触发；其他已有原因原样保留。`ZERO_RESET`从NextBarBranch、Python/TS类型、求解和解码允许值删除；允许PRESERVED/REFERENCE_SWITCHED/STRUCTURE_CONFIRMED/CANCELLED/PRECISION_UNRESOLVED。这些是本轮同步迁移的内部/debug合同，不保留旧名alias或兼容分支。

内部原schema关于区间完整、entry/关系引用、route、等待、精度、无候选/确认/目标空值的检查全部保留；r4仅改变§6明确列出的颜色/参照限制。正常公开模型按对应状态保留必有字段和空值：CONFIRMED无未来target而有真实confirmed时刻/方向；EMPTY/DELAYED不伪造目标；PRECISION_PENDING不给确定形成条件；CONDITIONAL_ENTRY/READY的target与barsAhead同时有效。debug模型先核完整语义，再核与普通根字段一致。

### 5.5 最小响应样例和故障行为

P1将独立人工输入落实为字面fixture，分别覆盖下面组合；hash由实现后的固定Spec统一登记，不能用旧JSON换hash冒充业务预期。下列是字段集合样例，`$D`为规则hash的说明占位，实际HTTP不得返回占位符。

```json
{"tsCode":"000001.SH","period":"day","algorithmVersion":"xxm-direction-v0.1-r4","specHash":"$D","source":{"kind":"daily_factor","startTime":"2023-01-03","computedThrough":"2023-01-04","initialHistoryIncomplete":true,"indicatorVersion":null},"points":[{"time":"2023-01-04","close":101,"dif":10,"dea":9,"hist":2,"ordinaryState":"NONE","ordinaryDirection":null}],"events":[],"meta":{"count":1,"responseStart":"2023-01-04","responseEnd":"2023-01-04"},"dataStatus":{"status":"READY","message":null,"asOf":"2023-01-04"}}
```

- 普通READY有事件/无事件、首段不完整提示；debug READY同公共字段另附实际参照、route及历史/等待关联。
- EMPTY：points/events为[]、meta.count0及首末None；来源时间按现完整合同合法None，不能用1970/请求日补；debug数组为空，无虚构历史。
- DELAYED：保留截至可用根的真实结果与来源延迟说明，不补最新根、不挪事件日期；正常和debug同截止。
- 预测READY/CONDITIONAL_ENTRY/CONFIRMED/NO_CANDIDATE/PRECISION_PENDING/DELAYED/EMPTY各有独立最小样例；display仍可展示，必要条件不依赖debug公式拼出。
- 400非法debug/日期、404标的不支持/生产无路由、500源合同、公开模型或一般查询失败、503预算错误按现异常登记，HTTP错误体沿现Wealth处理器，不另起错误包装。错误不转EMPTY，前端保留普通行情但清掉本请求失效标记/辅助资料。

## 6. 预测的具体实现

### 6.1 保留的数学与对外策略

继续现entry_range_then_flat：首次未钝化时求下一完成根的收盘P，后续中间根假定同P；已有DULL时P固定为上一真实close；目标根收盘C另求。最多20个未来完成端点，按现nearest_feasible_over_entry_range选择第一个有完整合法条件的目标。不增顶部下一根卡片，nextBarOutcomes仍仅BOTTOM已有DULL。

projection.py:recover_projection/ProjectionState保留：250根尾部校准，日线三位来源误差0.0005、分钟1e-8；日线source_options保留round3边界及GUARD=1e-10，分钟full_float。这里是源精度推算，不是两位有效数策略。实际信号不重算源MACD。hist零是源数值零，不用DIF正负代替。

forecast_math保留Interval/Affine/merge/intersect/subtract、source_options和显示取值。K=2/13-2/27；每个目标/前缀DIF与hist继续由已有仿射表达式计算。只在已证明分支一致的区间取代表点核验；不以中点决定整个域，不合并不同参照/切换时点的域。

### 6.2 entry_partition/stable_reference_on_band/reason_for

entry_partition(c,projection)保持返回(sorted_cuts,numeric_bands)，但历史仅固定B/A，无强弱排序。必须包含：0正价格边界、wave.price、B/A各price、DIF与wave.dif/B.dif/A.dif的交点、TOP首次当根DIF=0及日线源三位半档边界、hist真实反色/零的边界、pending_rearm保存ref.price与nearestPriceGate。每个root外包数值不确定范围沿原ulp算法标精度，不给detector加epsilon。

stable_reference_on_band仍只在区间整个都能证明同一参照时True：
- 先计算区间中所有可能源DIF/hist范围（保留day量化）；hist区间不得含真实反色，但允许零。
- count_new=count+int(hist源值!=0)，范围存在有色/零不同结果时，逐项证实最小count也>=2，不能统一count+1。
- 首次TOP每个可能当前DIF均>0，BOTTOM无额外符号要求。
- 计算当前段可能累计价格/累计DIF；先证明B价门槛。选B需整域B完整严格合格；选A需整域B不合格、整域A完整合格；若域内B可能合格/A可能合格混用，返回False而非借区间中点选A。
- pending_rearm不换参照：hist<=0、保存count门槛、当前P严格低于min(saved.price,nearestPriceGate)，累计DIF严格高于saved.dif；不是累计历史低价满足就通过。
- 与普通选择分支相同，价格相等和首次DIF相等不合格；已有ref的等号与此不同。

reason_for必须同实际检查顺序：真实反色才WRONG_COLOR拒绝，零本身不拒绝（枚举按§5，不得继续写“零必失效”）；再真实count、等待原ref/currentP、TOP正DIF、B价格门槛、B/A严格DIF资格。未检查的A不能伪造一个失败原因。

solve_entry_ranges保持现签名和区间/单点分割、源精度分支检查；activation_signature仍由唯一r4.step确认。相同参照可以在已证明同分支区间内合并；不同参照、未解精度范围不得合并。每个边界的开闭单独算，所有正价格必须落入ranges或exclusions，不能漏单点。

### 6.3 _prefix_signature的逐根演进

删除pool.sort以及_flat_cannot_switch原最强优先/TOP恒真证明。初版移除该快捷分支，全部走同一个partition_prefix_paths；不以“先返回True，验收后再补证明”交付。现200ms若不达标停止报告，不能自动放宽或恢复旧证明。

_prefix_signature保留现调用接口，可增加内部不可变状态记录。每个候选状态须至少携带reference、累计DIF、previous_dif、count、referenceTransitions；价格在flat P假设下等于原wave.price与P的有向极值。源round3临界产生的每一可能(d,h)都须保留，不能只取四舍五入一支。

- i=0且c.state==NONE：该根正是entry_ranges已证明的activation/reactivation；核对真实可能源色/根数/保存参照后建立DULL状态，不在此根追加STRUCTURE；initialReference来自原entryRangeId。
- 后续每根：先累积DIF与有色count，再按真实翻色、同根B→A、原参照突破、相邻1%顺序分类。
- h为真实反色：检查本根d是否严格突破原ref；突破为CANCEL_BEFORE_TARGET，否则EARLY_STRUCTURE。零不进入此分支。
- 同逻辑色/零：若当前ref是B且累计DIF严格突破B，先按本根累计price/DIF检查A；只有A严格合格才能append一次{endpoint,fromReference,toReference}；否则CANCEL_BEFORE_TARGET。当前ref已A不再救援。WAITING保存ref的重新激活不重新选峰，后续已变DULL时才按同样B→A规则。
- 然后若累计DIF严格超过活动ref为取消；若previous!=0且s*(d-previous)<0、反向幅度>=abs(previous)*1%则EARLY_STRUCTURE；否则继续DULL，并把previous更新为本根d（零根DIF也更新）。
- 去重只合并所有上述状态内容完全相等者；某源精度分支早形成/取消而另一支继续，或两支参照路径不同，整个该区间标PRECISION_UNRESOLVED，不拼接成确定路径。
- 不读取假设未来已经形成的历史色段作为新B/A；路径只保留尚未真翻色的原段；提前翻色已经终止该路径。

path_branch_points/branch_points将B/A、累计极值函数的全部交点补齐：每根DIF_i(P)=B.dif/A.dif/原wave.dif/0，以及DIF_i=DIF_j（当前累计极值切换）；价格P=B.price/A.price/原wave.price；hist_i=0；每相邻1%的绝对值分支（先按previous DIF=0分开，再解有符号线性等式）。day对实际合法entryDomain内会改变这些判断的源三位量化平台/±GUARD边界继续划分；minute保留ulp外包。不能对整个无界正价格轴枚举每个0.001档。先以仿射上下界及来源误差界证明整域分支不变，只对无法证明的有限范围求量化档交点；1%条件含两根源舍入时须同时保留两根可能值。若某域仍跨判断边界，继续细分，不能用代表点替代；达到200ms即预算失败，不以PRECISION_PENDING伪装未完成求解。这样每个返回关系内比较符号固定，没有全部切点/整域证明不得展示确定条件。

### 6.4 前缀条件、目标条件与零

build_path_relation保留ReferencePath(initial,transitions)表示；生成各根实际逻辑参照：
- 前缀“仍是原逻辑色”改s*hist_i>=0，不能继续gt0。当前有色count按状态推进，不在表达式中用天数代替。
- 活动ref不被突破为s*DIF_i<=s*ref.dif，已有ref允许相等。累计DIF在prefix域已逐步证明，条件和entryDomain须共同完整，不只列最后一根。
- 切换根明确旧B突破s*(累计DIF-B.dif)>0、新A背离s*(累计DIF-A.dif)<0、累计price严格突破B和A；TOP/BOTTOM用同一s公式，删BOTTOM专用lt/gt写法。
- 非切换根不伪造“曾检查A”；最多一次transitions，且只B→A。
- 尚未提前形成的条件按每个已切分分支表达：previous=0使用eq0保护；previous!=0时s*(DIF_i-previous)>-abs(previous)*1%。等于负1%就是EARLY_STRUCTURE，不能作为存活条件。ConditionDto已有eq可用，不新增逻辑运算别名；不同条件枝保留各自entryDomain/关系。

target_lines、close_bounds、common_interval必须相同目标语义：
- dif_turn：目标仍原逻辑色，s*targetHist>=0；包含真实零目标。previous!=0且-s*(targetDIF-previous)>=abs(previous)*1%，并严格反向；来源量化的所有可能值都满足。
- color_flip：s*targetHist<0，目标DIF未严格突破原活动ref；无需相邻1%。
- 参照突破先于结构。前缀已经保证历史累计极值有效；目标本根不得靠DIF转折“盖住”参照严格突破。
- 日线源hist=0对应整个round3零平台，不能仅加入一个数学零点；根数计数在此平台保持。minute恰零为单点。开闭与GUARD按source_options证明，不沿旧严格原色gt0排除零。
- 对日线的确定充分边界，dif_turn的TOP目标hist>=0使用投影原hist>−0.0005+GUARD，BOTTOM目标hist<=0使用投影原hist<+0.0005−GUARD；color_flip的TOP真实绿仍hist<−0.0005−GUARD、BOTTOM真实红仍hist>+0.0005+GUARD。等于或落在±GUARD边带时枚举source_options，不强行归一侧。minute的dif_turn直接允许s*hist>=0（闭边界），color_flip仍s*hist<0（开边界）。target_lines/close_bounds/common_interval三者必须使用同一阈值和开闭，不能只改展示条件。
- 目标根既有DULL不提供同根取消再重激活捷径；首次根不能作为目标结构根，conditional仍最早第2根。
- common_interval仍求整个entryDomain的共同充分C区间；previous可能为0时不能宣称共同1%转折。path_displayable_witness只选真实可验证示例，不反过来定义合法域。

possible_bars、event_options、confirmed_options全部clone唯一r4，按明确ReferencePath核每根：中间保持DULL及当根正确ref、无CANCEL/STRUCTURE，目标按指定route和最终ref形成；day所有可能source_options一致才确定。不能按最后标签相同忽略A/B或切换日不同。

### 6.5 _outcome与schema

_outcome先看真实step的STRUCTURE/CANCEL事件，再看最终DULL及reference是否改变；删bar.hist==0→ZERO_RESET。零日可按实际step产生STRUCTURE_CONFIRMED/CANCELLED/PRESERVED/REFERENCE_SWITCHED；源精度分支不一致为PRECISION_UNRESOLVED。solve_next_bar_outcomes仍仅BOTTOM DULL，全部正价格分区无重叠无缺口；保留精度边界而非吞为普通保持。

ReferenceTransitionDto字段继续endpoint/fromReference/toReference，内部和debug合同共同要求：
- 最多一次，TOP或BOTTOM均可；TOP必须to.dif>from.dif，BOTTOM to.dif<from.dif，from/to不是同参照。
- from是固定B，to是固定A，时间比B早；本根s*(DIF累计-B.dif)>0且A完整合格由求解结果证明，不能仅靠to.dif大小宣称允许。
- transition.endpoint属于实际前缀intermediateEndpoints，严格晚于activation时间（已有DULL为computedThrough），严格早于targetEndpoint；更新链首initialReference、末reference一致。
- 一根后立刻目标时没有前缀换参照，不能编一个target同根transition供color_flip救援。
- nextBarOutcomes目前仅BOTTOM；REFERENCE_SWITCHED的to.dif<initial.dif仍是该对象的方向规则，不误删成无方向校验。relations的TOP限制则必须放开。ZERO_RESET从内部和客户端允许值删除。

forecast_query_service的direction不能从最新hist符号给；READY状态以calculator_at(n).wave逻辑方向为准，CONFIRMED事件方向按原优先，开头全零无wave才None。最新零若ordinaryStateNONE但有逻辑绿段，预测仍按该段/等待语义给BOTTOM。

forecast_text.py与query的invalidationText逐处删“出现零柱就结束”结论：有效钝化的原参照、真实反色、前序假设变化才按对应实际情况更新；等待只真实红结束、原参照严格突破或重新激活；顶部/底部B→A仍有效但结构条件重算的文字与内部结果相符。保持display.statusLabel/targetText/conditionsText/asOfText现结构；所有必要条件/假设保留普通文本，公式和详细路径仅debug不等于普通文本可以省略假设。

## 7. 保留离线真实观察，页面debug不装入完整过程账本

技术方案§6.2要求迁出`r4_observation.py`仍有用的观察能力，同时明确不要求把离线完整账本加入HTTP。本节按这一范围实现：离线观察与正式产品共用一个step，页面debug只消费§5已有真实结果，不增加逐根decision响应。

### 7.1 唯一step的可选只读记录

`types.py`给`XxmStep`末尾增加`decision: XxmDecision | None = None`；`XxmCalculator.__init__`增加内部`record_decisions: bool=False`，先检查`type(record_decisions) is bool`。step(bar)签名不变。该标志只控制观察元数据，不是Spec/env/HTTP/用户参数，不影响任何业务分支或hash/编号。

- 正式query从空和追加、`calculator_at`、预测`clone`全部使用默认False；普通与debug都不采集完整过程。不存在SeriesEntry.decisions、内部/公开decision DTO、HTTP decision字段或新接口，不改变完整缓存或1MiB上限。
- 只有手动调用的单组离线核验函数显式True。同一个step先验证bar及时间；在真实选择循环、原参照突破、转折、等待及救援赋值处保存已经计算出来的条件/输出，不第二次执行选择或转折方法，不复制step或观察Mixin去模拟结果。
- True时复制必要的本根before/Wave事实，开头零柱早返回也产非None记录；False时所有路径始终None且不分配整份观察dict。结果深复制，外部不能改回计算器。finally清局部context，失败不暴露上根last_decision冒充本根。
- decision不入snapshot/restore。restore成功清临时观察context并保留本实例标志，失败原对象/来件不变。已恢复状态可继续记录后续根，但不得编造此前没有采集的过程。

### 7.2 离线事实格式及未执行的含义

`types.py`用TypedDict固定XxmDecision及嵌套事实；它是内存研究输出，不进入API/schema/前端类型。字段均明确存在，未执行用checked=False和None，不用False冒充失败。

| 字段 | 类型和含义 |
|---|---|
| time/rawSign | 本根time、源颜色-1/0/1 |
| before | state、reference(Reference或None)、wave(WaveFacts或None)、previousDif(number或None)，本根更新前 |
| wave/referenceAfter | 根末WaveFacts或None、真实活动Reference或None |
| referenceChecks[] | stage=nearest_price_gate/activation/same_bar_rescue/not_entered；candidate=B或A；wave:WaveFacts；checked:boolean；pricePassed/difPassed:bool或None；reason:string |
| selectionCalls[] | stage=activation/same_bar_rescue、selected:Reference或None；只记录实际调用 |
| turn | previousDif/currentDif/threshold:number或None；referenceBroken:bool或None；checked:boolean；reason:string |
| rearm | blocked:boolean、status为现等待结果或None、referenceBroken:bool或None |
| switched | 真正完成本根B→A赋值才True |
| branch/reason | 实际普通route；没有普通事件时用已有观察含义leading_zero/waiting/reference_switch/segment_changed/retained/no_activation及中文说明 |

WaveFacts复用Wave的sign/start/end/count/price/dif/price_at/dif_at，价格和DIF日期各自独立，before.previousDif是前一实际根。referenceChecks真实顺序：nearest_price_gate(B)→同选择stage(B)→同stage(A)，最多3条，去重候选最多B/A两个，selectionCalls最多1次；不能把“候选最多2个”误写成检查数组最多2条。

B门槛未过只记已查B价格、difPassed=None，再为存在的A记checked=False，不重复造一条未查B。B已合格时A未查，不标A失败。没调用选择时可按B/A记not_entered，但不重新计算资格。转折阈值取真实`abs(previousDif)*1%`；翻色/等待阻断/原参照已突破未进入转折时checked=False并说明。前值0的threshold=0，真实保护不触发；不得跳过前一零柱去换basis。

同根换A的before.reference仍B、referenceAfter为A、switched=True；原事件/历史保存B不改。根末NONE但真实发生翻色STRUCTURE时，记录真实事件route，不按根末状态抹掉它。历史撤销理由只取实际history/event更新，不由观察器重造标签。

### 7.3 调用、预算、页面边界及测试

在现`history_disappearance_screen.py`保留纯事实核对函数，并新增`observe_rows(bars, *, period, source_identity, check) -> tuple[XxmStep,...]`，只构造唯一正式类`record_decisions=True`并逐根step；不读文件/数据库/网络、不写结果、不新增CLI模式。调用者提供标准XxmBar及足够历史前段，最多1000根，20秒/256MiB/16MiB，函数自己建立20秒perf_counter截止并检查输入/累计结果大小，不能只相信调用者传来的check；每根及最终复制前后同时检查本地限额并调用check，既有resource口径核256MiB上限。预算到即整项失败，不返回半份成功。该函数只迁出原观察能力，不是重新进行r2/r4或两位对照。

正式debug页面仍查看§5的活动参照、初始事件原参照、route及历史/等待事实。它没有完整decision时，**不得声称本根未检查A或1%**；不展示这一过程结论，确需提示时写“当前页面未提供这项检查记录”。手动离线记录才可回答哪些检查实际执行，不在前端或另一个算法里重算理由。

独立人工测试比较True/False：排除decision后point/events/历史/等待/snapshot逐项一致；反例抓重复选择调用、排序、未查A编失败、before/after混淆、旧记录复用、外改返回值污染状态及恢复失败。普通/debug两种HTTP都断言无decision/decisions字段、正式query不设置True。完成后可删除旧ObservedR2/ObservedR4及其父类包装，而不丢掉有用的离线事实观察。

## 8. Wealth页面、请求和研究工具

### 8.1. 硬口径与范围

- 本地开发普通页保留唯一r4的正常标签、当前状态/当根事件/时间和关键高低点预判。普通悬停不显示参照、编号、历史或等待记录。
- 生产构建不请求日线或分钟r4识别/预判/研究接口，不创建r4圆点或标签图层，不显示r4悬停/预判卡/研究入口；不留“加载中/未开放”占位，不退回r2。普通K线/MACD/MA/BOLL/九转/趋势与1000根不变。
- 只使用现有`import.meta.env.DEV`作为前端开发环境判断；后端另按本文本地路由装配。前端判断不是后端权限保护，不新增env或开关。
- `debugEnabled = import.meta.env.DEV && new URLSearchParams(search).get('debug') === '1'`；严格沿现URL入口，无页面开关、无持久化。开发环境不自动开启debug。
- 波段工具仅上证日线，进入debug只加载工具代码；用户点击“波段核对”才开始计算。r4计算周期仍只上证day/m60/m90/m120，分钟行情沿已有配置与能力，不扩大生产分钟或其他标的。
- debug只增加本次r4结果的辅助字段与呈现，不另跑识别器。正常/debug公共字段、事件编号和预判文本一致。

### 8.2. 文件与职责清单

以下新文件名为本次LLD固定实现位置。不得改成另一套页面或复制识别算法。

| 文件（wealth/src下） | 改动/新增及唯一职责 |
|---|---|
| `pages/index-detail/IndexDetailPage.tsx` | 计算本地/debug启用条件；普通业务hooks继续按规则调用；控制debug模块的延迟加载、稳定子组件挂载和有效扩展；给右栏传forecast或undefined |
| `features/index-detail/model/indexRecognitionAvailability.ts`（新） | 纯函数集中返回本地正式能力和debug能力；输入DEV布尔、tsCode、search；不读取env文件、不设置配置、不判断Lake目录 |
| `features/index-detail/debug/types.ts`（新，纯类型） | 页面与debug组件的props、扩展快照、动态模块导出和解码函数签名；禁止有运行时初始化/import副作用 |
| `features/index-detail/debug/useIndexDebugModule.ts`（新） | 仅enabled时动态import `./IndexRecognitionDebug`；管理idle/loading/ready/error、加载序号及retry，不执行行情计算 |
| `features/index-detail/debug/IndexRecognitionDebug.tsx`（新） | 动态模块入口，导出debug控制组件、识别/预测debug解码器及详情renderer；独占波段hooks、研究primitive和研究UI运行时导入 |
| `features/index-detail/debug/xxmDebugContract.ts`（新） | 迁入现adapter中参照/历史/等待/事件关联校验，按本文 DTO的debug对象校验；不重算算法 |
| `features/index-detail/debug/forecastDebugContract.ts`（新） | 迁入现预判公式/区间/参照转换/历史关联校验，并按r4迁移；不调用预判求解器 |
| `features/index-detail/debug/ForecastDebugDetails.tsx`（新） | 仅debug的预测精度、参照/路径及区间详情；由卡片注入的renderer调用，不求价 |
| `features/index-detail/debug/XxmDebugDetails.tsx`（新） | 迁移现XxmResearchDetails的参照、历史、等待说明；依据debug对象，不前端推测原因 |
| `features/index-detail/chart/indexChartPointAdapter.ts`（新） | 原日线toDetailChartPoint原样迁出为纯函数，普通图与debug图共用；不改值、不格式化后比较 |
| `features/index-detail/chart/IndexChartWorkspace.tsx` | 去除daily-wave运行时import及hooks/primitive创建；保持同一组件位置；接收纯类型定义的可选debug扩展，消费其中图表数据/辅助render slots；本地r4正常识别继续存在 |
| `features/index-detail/chart/IndexMinuteChartWorkspace.tsx` | 传本地enabled/debug模式及解码器，挂正常简要悬停和可选debug详情；不加分钟波段功能 |
| `features/index-detail/xxm/{types,adapter,apiClient,useIndexXxmLayer,XxmLayerUi}.ts[x]` | 按本文正常/debug DTO迁移，改正式r4版本，正常解码与加载/绘图；XxmLayerUi仅保留正式状态与简要详情 |
| `features/index-detail/xxm-forecast/{types,adapter,apiClient,useXxmForecast}.ts` | 正常预判DTO、请求参数、身份/模式隔离、开发环境启用与可选debug解码；正常卡只消费display等正常字段 |
| `features/index-detail/sidebar/{IndexInfoRail,IndexTechnicalTab}.tsx` | 延续forecast可选prop；生产传undefined即整卡不存在，其他技术面内容不变 |
| `features/index-detail/daily-wave/*` | 保留现算法合同/请求/说明/几何行为，仅由debug模块运行时导入；hook增加显式enabled保护，清理语义如下 |
| `features/nine-turn/ui/NineTurnLayerStatus.tsx` | 新增可选`showAlignmentDiagnostics?: boolean`，默认true；指数详情显式传debugEnabled；真实故障不受该参数隐藏；股票等调用不变 |
| `features/index-detail/model/indexDetailConstants.ts` | 保持唯一`INDEX_DAILY_HISTORY_LIMIT=1000`，不新增同值副本 |

生产无r4信息并不要求删除常规MACD的DIF/DEA/柱值。XxmMacdPrimitive和markerGeometry属于正常识别绘图；daily-wave三角与研究趋势primitive属于仅debug加载。

### 8.3. 页面props、延迟模块与稳定工作区

#### 8.3.1 页面内唯一能力计算

`resolveIndexRecognitionAvailability({development, tsCode, search})`返回：

- `recognitionEnabled = development && tsCode === '000001.SH'`。
- `debugEnabled = recognitionEnabled && debug参数精确等于1`。

该函数的development由调用方传`import.meta.env.DEV`；不是新的产品开关。周期资格仍由识别hook精确限制四种。其他指数保持不请求识别；现URL debug与page-init/权重等既有诊断能力不因本次额外扩大。

`IndexDetailPage`始终调用`useIndexDebugModule(debugEnabled)`、`useXxmForecast`等hooks，不放在条件分支。debug组件仅在模块ready、debugEnabled且当前页面存在可用行情时挂载。不是用CSS隐藏。

页面另取`effectiveDebug: 0|1 = debugEnabled && module.phase === 'ready' ? 1 : 0`，只用于识别/预测请求及其缓存key、解码模式。URL表达是否需要辅助工具，effectiveDebug表达本次实际请求格式；二者不能混用。模块loading/error时继续以0请求普通识别和预判，简要标签、状态、条件照常工作；ready后用1取消旧请求、升新模式并取得辅助投影，后端复用同源内部计算缓存，不运行第二套算法。移除URL或重试模块尚未ready时恢复0并清旧辅助，不能因为没有decoder就堵住正常请求。renderer、波段控制器和辅助扩展仍要求debugEnabled且module ready，不凭普通结果生成辅助说明。

`useXxmForecast`新增`enabled`、`debug`及`decodeDebug`参数；`active = recognitionEnabled && activeTab === 'technical' && hasData`。给IndexInfoRail的forecast prop：仅recognitionEnabled时提供，否则undefined。这样生产既不请求也不显示整卡；不能仅把分钟传false，因为day仍会计算。

#### 8.3.2 模块加载状态

`useIndexDebugModule(enabled)`：

1. false时返回idle/module=null，递增加载序号；不调用import，不注册研究listener，不构造研究图层。
2. true时设置loading并调用一次动态import；保存本次序号。成功/失败仅在enabled仍为true且序号相同才提交。
3. `retry`仅在enabled时递增重试值并重新import；不能触发波段计算。
4. 退出debug或卸载后丢弃迟到模块结果。动态import本身不可被AbortController取消；不虚称已取消网络。已经加载的JavaScript模块可能留在浏览器进程缓存，但研究数据、定时器、监听和primitive必须释放；不新增持久缓存。
5. module加载失败只在debug辅助区域显示“核验工具加载失败”和现式重试，不把普通行情置错，不伪造研究ready。该失败不改识别算法。
6. 纯普通模式不得静态import这些debug实现。`import type`允许；不得因再导出或桶文件把debug合同/样式/primitive带回主入口。构建及网络测试覆盖此点。

#### 8.3.3 扩展快照交接，不替换普通组件

页面正常日线始终渲染同一位置的IndexChartWorkspace；debug组件作为其兄弟控制组件，不能用`debug ? <DebugWorkspace/> : <NormalWorkspace/>`替换整棵图表。

`IndexRecognitionDebugProps`固定包含：

- `ownerKey`：标的、activePeriod、普通asOfTradeDate的组合。
- `tsCode/activePeriod/ordinaryAsOfDate`。
- `supportsNineTurn/supportsTrend`。
- `onChange(ownerKey, extension|null)`，稳定callback。

`IndexRecognitionDebugExtension`是纯类型，字段：

- `ownerKey`、`reviewPhase`。
- `chartOverride`可空；非空包含研究ready的`candles/dataKey/nineTurnLayer/trend/trendPhase/onNineTurnRetry/onTrendRetry/waveMainPrimitives/trendMainPrimitives/mainPriceScalePaddingPx`。
- `controls: ReactNode`（波段按钮、状态和说明）；`legend: ReactNode|null`。
- `renderWaveDetails(point): ReactNode`；识别详情renderer从动态模块直接传工作区，见§8.3.4，不重复放进extension。
- 不能带自建识别结果、普通右栏日期或一个带研究日期的整页viewModel。

controller通过effect发布useMemo稳定的extension；所有函数useCallback稳定。页面只接收ownerKey等于当前owner的扩展，且渲染时再检查debugEnabled及owner一致。旧控制器清理回调也携带ownerKey，不得清掉新实例的结果。扩展为null时普通工作区立即只消费普通数据。

开启debug但波段未开启：chartOverride=null，普通dataKey/points/趋势/九转primitive数组保持原身份，进入/退出debug不重建图表。波段ready后允许切换现研究dataKey；关闭波段或退出debug按原生命周期恢复普通dataKey，允许必要重建，不留旧研究实例。

#### 8.3.4 动态模块导出、两种解码器及工作区props

以下均写在`debug/types.ts`，只用`import type`引用现业务类型；普通路径不经运行时桶文件导入debug实现。`XxmResponse/ForecastResponse`表示§5普通模型，`XxmDebugData/ForecastDebugData`严格对应§5辅助对象。

```ts
type DecodeXxmDebug = (
  raw: unknown,
  context: { response: XxmResponse; tsCode: string; period: XxmPeriod; check: () => void },
) => XxmDebugData;
type DecodeForecastDebug = (
  raw: unknown,
  context: { response: ForecastResponse; period: ForecastPeriod; asOf?: string; check: () => void },
) => ForecastDebugData;
interface IndexRecognitionDebugModule {
  IndexRecognitionDebug: ComponentType<IndexRecognitionDebugProps>;
  decodeXxmDebug: DecodeXxmDebug;
  decodeForecastDebug: DecodeForecastDebug;
  renderXxmDetails: (layer: XxmLayerState, time: string) => ReactNode;
  renderForecastDetails: (response: ForecastDebugResponse) => ReactNode;
}
interface IndexRecognitionProps {
  recognitionEnabled: boolean;
  debug: 0 | 1;
  decodeXxmDebug?: DecodeXxmDebug;
  renderXxmDetails?: IndexRecognitionDebugModule['renderXxmDetails'];
}
```

函数返回经辅助合同检查的完整typed对象，抛错时整个本次响应失败；不返回半个字典。入口先按本次effectiveDebug核根字段集合：0必须恰为§5普通根的keys，1必须恰为普通keys加debug，缺失/额外键均拒绝。随后显式读取普通字段构造新对象进行普通校验，不把带debug的整个raw对象塞进只允许普通keys的封闭模型，也不原地删除raw.debug。仅模式1时，再将raw.debug和已校验普通根交辅助decoder，要求对象非空且通过全部关联检查。`check`使用本次请求剩余时间及取消检查，不在辅助模块新建时限。

模块未ready按§8.3.1发送普通请求；已经发出的模式1响应若合同错误，仍整份失败，不偷偷降为普通成功。工具加载失败与真实响应校验失败分开处理。

- 日线`IndexChartWorkspaceProps`移除旧`review?:DailyWaveReviewState`，新增`recognition:IndexRecognitionProps`及`debugExtension?:IndexRecognitionDebugExtension`；研究controls/legend/图数据仅经extension交接。
- 分钟`IndexMinuteChartWorkspaceProps`及其内部`LoadedIndexMinuteChart`都新增并完整向下传`recognition`，不经过日线波段控制器。页面从已加载模块直接传decoder/renderer，因此分钟可看r4实际参照/依据，但没有日线三角或波段计算入口。
- 日线/分钟工作区各自调用同一个`useIndexXxmLayer`，把recognition中的资格/debug/decoder完整传入；正常悬停总用`XxmSignalDetails`，只有合法debug数据和renderer都有才追加`renderXxmDetails(xxm,真实time)`。extension不再另带第二份renderXxmDetails，避免分钟依赖日线控制器。
- 页面给`useXxmForecast`传`decodeForecastDebug`；给右栏现forecast可选prop增加`renderDebugDetails?: IndexRecognitionDebugModule['renderForecastDetails']`。`IndexInfoRail`→`IndexTechnicalTab`→`XxmForecastCard`逐层透传，不自行拼公式。
- 新增延迟模块内`ForecastDebugDetails.tsx`，只在合法debug响应时由卡片该周期行末呈现“计算依据”的debug详情，展示已返回的精度、参照/路径和区间条件；不另请求、不求价、不改普通display文字或行状态。普通/生产不传renderer，也没有该详情DOM。源代码/绝对路径不得显示。
- `IndexRecognitionDebugModule`的renderer是普通纯渲染函数，不在条件调用中运行Hook。需要Hook的波段逻辑只放在稳定的子组件`IndexRecognitionDebug`中。

#### 8.3.5 五秒请求的同一截止时间

原API计时器在JSON返回就清除，不能仅沿用它再宣称涵盖解码/最终显示。本轮保持5秒限额和原scheduler排队政策，具体交接如下：

1. scheduler真正开始该HTTP任务、调用send之前取`deadline=performance.now()+XXM_TIMEOUT_MS`；排队期间用原外部AbortSignal取消，不提前耗掉网络时限，也不另开绕过队列的请求。
2. `sendXxm/sendForecast`网络timer只用`deadline-performance.now()`剩余值。取JSON前后、普通/辅助decode前后都调用本次`check`；check同时检查取消和当前时间，不靠timer回调是否已经执行判断超时。
3. `fetchXxm`返回`XxmRequestResult={response: XxmResponse|XxmDebugResponse, deadline:number}`；`fetchForecast`返回对应`ForecastRequestResult`。仅内部客户端交接，HTTP正文仍§5。所有hook/测试同步使用该结果，不留旧签名兼容。
4. hook在适配真实图表原值前后、以及`setState/setRows`紧前，继续检查同一个deadline、请求key/序号或generation、abort。`buildXxmViewModel`增加`check`回调，循环每128点及结束检查；不能在HTTP结束后给适配重新5秒。
5. send finally清网络timer/listener；hook自身后续不需要重复定时器，但同步重活后必须验时间。5秒已过即明确超时，清本次无效标记/辅助结果，不能把迟到decode当ready。
6. 合法内存缓存命中没有新HTTP；仅本次公开解码/图表适配建立新的5秒截止检查，不复用上一请求已到期deadline，也不改变缓存中的业务身份。deadline不进入事件/缓存key，不写浏览器持久存储。

测试用可控时钟令HTTP在4990ms返回、解码/适配越过5000ms，必须拒绝最终显示；另以HTTP+解码在时限内的正常例子证明不会误拦。预测同理；关闭或切模式的迟到请求即使未超时也必须丢弃。模块动态下载不算这5秒，模块未ready不发辅助请求；模块失败与行情失败分开。


### 8.4. 识别类型、解码、请求和绘图

#### 8.4.1 DTO和view model

前端字段以本文后端定义为准，沿技术方案§6，不另造字段别名：

- 普通XxmResponse根包含tsCode/period/algorithmVersion/specHash/source/points/events/meta/dataStatus；正常source不含inputId；正常points不含活动参照和pending IDs；正常events仅id/time/direction/type。
- debug响应的必有debug对象包含sourceInputId、同time的debug.points、同id的debug.events、topHistories/bottomHistories/rearmRecords。普通请求不允许出现该对象；debug请求要求符合本文各状态对应的对象形状。
- 保留XxmPeriod四种和正式事件语义；旧`RESEARCH_HISTORICAL_WITHDRAWAL`按既定结构消失画，不因名字含研究就过滤事件。
- XxmMarker只依赖正常event的id/time/type/direction和源DIF；markerGeometry/XxmMacdPrimitive不得强读debug route/history。
- XxmViewModel.byTime正常只关联point和events；增加可空debugDetail只在通过debug解码时构造。普通状态不能再靠pendingRearmId显示“待重新钝化”，因为该等待明细已归debug；正常按ordinaryState/direction显示真实当前状态。

#### 8.4.2 正常与debug解码分开

`decodeXxmResponse(raw, {tsCode, period, debug, decodeDebug?, check})`新增在现adapter.ts：接unknown，不直接类型断言为成功。检查根和嵌套字段集合、值类型、正式r4版本/hash、period/标的、合法时刻、排序唯一、数值有限/正收盘、state-direction关系、meta范围/count、source/dataStatus及EMPTY约束。普通没有历史ID，不能要求不存在的历史数组为[]，也不能跳过正常检查。

`buildXxmViewModel`消费已解码的正常数据和真实DetailChartPoint，保留现逐时刻close/dif/dea/hist严格相等及indicatorVersion校验。不得用显示精度比较、容差、重算、补值。

当debug=1：要求decodeDebug已由动态模块提供；先完成正常检查，再调用`decodeXxmDebug`检查辅助对象，按time/id与正常points/events精确配对，补齐本窗口引用的更早历史。迁移现合法历史/等待/恢复前后记录关系检查，不要求所有历史形成事件都在可见窗口，但被引用的记录必须存在。错参照、悬挂ID、重复ID、越过computedThrough、错方向、错结束原因均拒绝整份识别结果，不保留旧三角或把失败当EMPTY。普通/debug任一不合格仍保留正常K线。

`XxmLayerUi`正常导出XxmLayerStatus与XxmSignalDetails。简要详情含“顶底识别·r4”、当前状态、当根事件和对应时间。debug详情renderer仅在debug模块已加载且该响应有合格debugDetail时追加；不补推断原因。

#### 8.4.3 hook和请求生命周期

`useIndexXxmLayer`参数新增：`enabled:boolean`、`debug:0|1`、`decodeDebug?`。资格必须同时满足`enabled && import.meta.env.DEV && 上证 && 四周期`。生产即使调用者误传enabled也不发请求；production返回unsupported且primitive=null、macdPrimitives=[]。不再保留day无需DEV的例外。

请求key完整包含：正式algorithmVersion/specHash、tsCode、period、真实首末时刻、points.length、indicatorVersion、effectiveDebug（传给hook的debug参数）。缓存只在同key同身份复用；模式变化先失效旧序号、abort并清空旧辅助结果。不能把debug对象删字段后复用为普通对象。

数据不完整按原loading/error分支。URL开启debug但decoder尚未加载时，传给hook的debug=0，正常请求继续；不得先发模式1后临时静态import validator。普通数据仍按现图表状态可用，加载期间不展示旧辅助信息。

fetchXxm保留现scheduler的xxm通道、5秒和外部abort，截止时间交接及返回结果严格按§8.3.5；finally清timer和abort listener；params加debug?:1，普通省略、debug显式1；路径、日期、limit不改。模式变化等于新一次请求，不自动重试。所有apply/catch必须匹配请求序号、key且未abort。

primitive只有资格成立时创建，按标的/周期稳定；结果更新调用setMarkers，失败/关闭清空；正常的debug显隐不重建图。label布局/颜色/圆点规则不修改。

### 8.5. 关键高低点预判

#### 8.5.1 正常类型和显示

ForecastResponse改为§5.4普通字段；把源输入、精度策略、激活/等待、下一根分支、公式/区间/示例移入debug对象。display/applicabilityText/invalidationText等必要条件仍正常返回，不因隐藏公式删掉真实适用条件。XxmForecastCard继续仅消费正常display、status、截至时间和重试，不在前端求价或改边界。

`adaptForecast(raw, {period,asOf,debug,decodeDebug?,check})`检查正常键、正式forecastVersion/forecastSpecHash/detectorSpecHash、四周期、requestedAsOf/mode、status/state/direction/target/confirmed/null关系、refreshAfterMs与display字符串。不能继续要求正常响应必须有relations/sourceInputId等已移走的字段。

`decodeForecastDebug`在动态模块中迁移现公式/范围/entry ID/rearm/nextBar/relations校验；按r4允许方向正确的一次B→A，移除仅BOTTOM和无条件toDIF<fromDIF限制，拒绝ZERO_RESET。现nextBarOutcomes仅底部已有钝化的范围不变，不加顶部新卡片。零/方向/分支严格按§5—6同次后端合同，不保留旧枚举兜底。

#### 8.5.2 hook、身份和取消

`useXxmForecast`始终按Hook规则调用；enabled=false或非DEV时初始化无响应状态，不注册visibility/focus listener、不排队、不设刷新timer、不请求；retry无操作。整张卡由页面forecast=undefined关闭。

身份包括正式forecast/detector身份、tsCode、historicalDate或latest、minutes可用性、effectiveDebug（hook的debug参数）。模式1须decoder ready；模块loading/error期间模式0正常入队，不能一并停掉正式预判。mode切换、日期/标的/环境资格变化，先generation++、abort所有controller、清queue/timer，再设置新身份；旧响应不能填新行。

沿现可见性、technical页签激活、60秒返回刷新值、独立周期重试和页面scheduler；不扩大后台请求范围。历史日期不刷新。重试只重试该周期且使用普通页面的historicalDate，不使用研究日期。

fetchForecast params加debug?:1，普通省略，返回ForecastRequestResult并按§8.3.5交接同一截止时间；沿现forecast通道和5秒，不另开绕过队列的debug请求。debug关掉后不会保留旧辅助response。预判不向浏览器持久保存。

### 8.6. 波段研究生命周期与图层

`useDailyWaveReview`新增`enabled:boolean`，supported=`enabled && 上证 && activePeriod==='day'`；enabled由debug子组件传true，hook仍保留防误用校验。start/toggle/retry均先检查supported；false及卸载执行stop/closed。现contextKey加入ownerKey，deadline从用户手动start开始，不从动态模块下载开始。

状态表：

| 输入/动作 | 研究状态 | 显示与副作用 |
|---|---|---|
| 无debug/生产/其他标的 | closed且不挂控制器 | 无辅助研究模块运行、请求、定时器或图层 |
| 本地分钟debug | 不挂日线波段控制器 | 无日线波段请求/图层；识别及预测辅助解码/详情按§8.3.4运行 |
| 本地debug初次ready | closed | 仅显示现波段按钮，不请求daily-waves |
| 手动开启/重试 | loading | abort旧链、释放旧结果，序号递增，建立唯一10秒deadline；仍显示普通图 |
| daily-waves EMPTY | empty | 不请求研究K线，不建图层 |
| 合同失败/超时/请求失败 | error/timeout | 普通图保留，结果和图层清空；按现重试入口处理 |
| 研究K线原值不符 | mismatch | 仅保留已解码事实用于说明，不替换图、不画三角 |
| 两次请求及逐日核对全部成功 | ready | 一次提交研究response/candles/dataKey；随后研究九转/趋势独立加载 |
| 关闭/退出debug/换标的周期/离开 | closed/卸载 | 同步失效owner与requestId，abort，清timer/response/candles/layout/primitive，恢复普通图 |

ready dataKey保留`index:000001.SH:day:wave-review:${calculationId}`；普通仍`index:${tsCode}:day`。校验失败没有研究dataKey。任一await返回和最终setState前检查owner/requestId/abort/deadline。关闭后返回的模块、研究计算、K线、趋势或九转均不能复活研究图。

`useDailyWaveCompanionLayers`仍独立实例，active只在研究ready。endDate只取response.observationEnd；请求limit1000；重试沿同一研究日期。关闭时registry.clear和abort趋势；普通右栏九转、普通trend retry/forecast的实例与日期不改。

研究趋势primitive的lines跟随研究trend/points更新，但不自行读取overlay；chartOverride分别提供稳定waveMainPrimitives和trendMainPrimitives。原IndexChartWorkspace保持overlay状态：仅overlay===TREND_CHANNEL时选择trendMainPrimitives，再合并waveMainPrimitives和该图nineTurnChartLayer.mainPrimitives；MA/BOLL时不挂研究趋势primitive。不需要把overlay状态反传debug控制器。切换overlay不改源、日期或三角事实。

研究controller用共用toDetailChartPoint转换研究candles；用现`buildNineTurnRenderMarkers`把研究九转与这批points对应，供三角避让（这是同一纯函数，没有第二次网络读取）。`DailyWavePrimitive`、稳定研究趋势primitive、presentation、layout issues均在debug模块内部创建和更新。mainPrimitives数组在同dataKey只随真正图层变化，layout issue变化只setData，不新建数组触发共享图重建。

保留现三角四种语义：上涨开始/下降结束为K线下红上三角；上涨结束/下降开始为K线上绿下三角；共享位置/起止身份及只改画法不改算法定义不变。保持8×6、初始8px、每次外移4px、最远40px、真实九转/极值文字占位、放不下记说明、无横移日期。研究ready上下44px，其余恢复默认。说明最高240px、向上展开/滚动、键盘关闭回焦、右栏不挤压、待核对按波段去重全部保留。

daily-waves请求继续现no-store、原接口、唯一tsCode，不加后台自动运行或导出/落盘。该接口不携带debug参数，保持仅tsCode；debug由页面加载条件及服务端环境装配控制。进入该客户端的前提必须是上述本地debug且手动start。

### 8.7. 九转诊断、1000根与共享保护

NineTurnLayerStatus新增showAlignmentDiagnostics默认true。指数普通模式传false：READY且仅有droppedMarkerCount时返回null；非READY仍展示真实layer.message/fallback，不能因有drop数量而把真实失败藏掉。debug传true保持数量说明。股票等不传，默认行为不变。该开关只是组件显示prop，不是用户配置。

1000常量继续用于普通K线/趋势/九转、研究K线/趋势/九转；请求、缓存编号和清理使用同数。主图真实首末日期和根数传识别；不得因拆debug恢复旧300。股票300、分钟500不变。普通K线不以研究response生成整页模型；普通右栏日期不倒退。

共享DetailChartWorkspace不新增r4/debug知识。通过现mainPrimitives/macdPrimitives/renderTooltip/renderPanelHeader/mainPriceScalePaddingPx扩展即可。正常mainPrimitives引用需稳定；没有波段覆盖时debug显隐不进入重建依赖。共享缩放、拖动、四窗同步、九转绘制和高度变化规则不改。

### 8.8. 自动测试与验收清单

所有新合同样本手写并按本文后端DTO核验，不能把旧r2 JSON改hash后作r4真值。允许读取原报告作历史证据，当前有效测试改为r4独立字面样本。

| 测试位置/新增组 | 必须断言 |
|---|---|
| `model/indexRecognitionAvailability.test.ts`（新） | DEV true/false、上证/其他、无debug/0/1/其他；生产debug=1仍正式和debug都false；没有任何Lake依赖 |
| `debug/useIndexDebugModule.test.tsx`（新） | false不import；true才import；退出前迟到resolve/reject不发布；重试不算波段；模块对象不存业务数据 |
| `xxm/adapter.test.tsx` | 正常/EMPTY/DELAYED独立新合同；旧r2身份/错hash/混合源/重复日期或ID/NaN/state方向非法拒绝；正常strict原值对图，模式字段越界拒绝；普通无历史字段仍通过 |
| `debug/xxmDebugContract.test.ts`（新） | 正常time/id和debug双向对应；悬挂/重复/错期/错原参照/等待关联/窗口前历史/根末NONE但仍有事件，合法及非法均覆盖 |
| `xxm/useIndexXxmLayer.test.tsx` | day生产也无请求/primitive；本地day与三分钟仅支持集合；模式/indicatorVersion/key隔离、取消、迟到、失败清旧标记；debug decoder未ready不发请求 |
| `xxm/apiClient.test.ts` | 普通省略debug、debug明确1，原路径/日期/limit不变；5秒、scheduler、外部abort、失败finally清理 |
| `xxm/markerGeometry.test.ts` | 正常最小event即可绘所有事件，不依赖debug字段；不改变原颜色/位置/连线/拥挤规则 |
| `xxm-forecast/forecast.test.tsx`、identity测试 | 正常公共DTO可用；debug解码只在显式模式；r4双身份、旧/混合hash拒绝；各状态必要display与空值；不拿r2输出当预期 |
| `debug/forecastDebugContract.test.ts`（新） | r4顶底一次B→A、严格方向、entry关联、等待、精度与区间；ZERO_RESET/仅改身份的旧假设拒绝 |
| `xxm-forecast/useXxmForecast.test.tsx`（新） | disabled/生产无请求/监听/刷新；技术面激活、四周期按能力、同模式重试、模式变化取消、历史不刷新、迟到不覆盖、研究日期不进入预测 |
| `pages/index-detail/IndexDetailDailyWave.test.tsx` | 默认普通URL不再期待波段按钮；debug URL进入后手动点击才请求；保持原日期隔离/1000/不匹配/超时/迟到全部case；退出debug恢复普通数据及清图层 |
| `pages/index-detail/IndexDetailPage.test.tsx` | 生产完整技术面没有r4悬停/卡片/占位/请求；普通行情还可用；本地简要悬停无编号/参照；debug包含原依据；仅debug未开波段切换不重建图表 |
| 现daily-wave所有单测 | 人工数值、适配、几何、共享三角、开放尾段、无起点说明、键盘、空间不足及44px全部保留；新增enabled=false误调用start/retry仍无请求 |
| NineTurnLayerStatus及共享回归 | 指数普通hide诊断但真实错源/权限/错误可见；debug显示数量；股票默认不变；指数/股票日/分钟共享图无缩放拖动退化 |

生产构建不能只靠jsdom模拟DEV=false验收。P4必须完成真实生产构建/preview，在不部署、不改共享服务下确认无r4 DOM、相关请求或debug模块预载；本地开发真实路由另验功能正常。记录normal/debug Network、控制台及图层/图表创建次数；build chunk检查仅辅助，不能代替浏览器请求证据。后端生产路由禁用由本文另验，不以此处浏览器通过替代。

真实页面沿1600/1440/1280宽、45/180根、拖到301根以后、日线及现可用60/90/120分钟；普通和debug对同一固定输入公共标签/预判文本一致。生产分钟仍不开放。需现有环境的Wealth定向测试、全量test、typecheck和build，每组超过60秒先查因，不安装依赖。未运行项显式列未验收，不能只报测试数量。

### 8.9. 预算与失败收口

- 识别/预测仍各请求5秒并走原页面scheduler，包含解码和最终状态提交的迟到检查；不另给debug无限等待或绕过并发。
- 波段从手动开启起10秒覆盖计算请求、研究K线、原值核对和最终提交；服务端8秒及源读取边界依本文，不放宽。
- 普通1000根K线仍按现20次本机P95/800ms核验；研究response上限/后端内存预算不因前端隐藏字段改变。
- module加载、请求、合同、真实K线不匹配各自不伪装EMPTY；普通行情不被研究失败覆盖；旧结果不能冒充本次ready。
- 不落盘、不导出、不新增localStorage/IndexedDB/后台任务/套件；浏览器自身模块代码缓存不等于保存行情或研究结果。

## 9. 预算、错误、取消及数据读写边界

| 步骤 | 固定限额及来源 | 必须包含的开销/失败 |
|---|---|---|
| 正式识别 | `runtime.BUDGET`4秒；并发2；source批1000；源最大20000根/5000分区；返回≤2000；1MiB；缓存64MiB/16系列 | 读取、共享加载等待、增量/恢复/历史位置、内部校验、投影、公开校验和最终一次编码；检查前后均使用原deadline |
| 预测 | 共用读取4秒；求解开始另200ms；32KiB；20个未来端点/90自然日；250根校准；刷新60000ms | clone/恢复/路径划分/全部源精度分支/step复核/文本/模型/编码都在200ms；缓存命中的本次投影编码也计时 |
| 日线研究 | `index_detail_daily_wave.spec`业务读取开始8秒，内存256MiB，响应2MiB；主范围800、历史补查500、总1300；输入1MiB/日历2000行；连接2秒/查询3秒/锁1秒/清理0.5秒 | 范围仍2023-10-24—2026-10-21及来源实际可用截止；不补行，前段不完整真实标记；前端手动start至核对提交整链10秒 |
| 普通K线 | 本机20次有界样本P95对既定800ms；指数日线请求1000 | 真不足1000如实报告，不能补数据；数量变更与本轮无关 |
| 前端识别/预测 | 原scheduler及5秒取消 | 每次异步返回及最终提交前验有效序号/模式/时间；不能只有网络timer，解码超时也不显示迟到结果 |
| 一次性迁移对账 | §10捕获/重算/比较分段各20秒/256MiB/16MiB，单组测试60秒 | 不注册后台服务；等待编辑只保留内存，不占DB连接，不把停留时间冒充计算时间 |

这些是验收上限，不是当前已测成绩。源20000/5000来自现本地分钟reader常量，LLD只登记，不复制成新配置；日线已有读取边界保持其当前实现，不为凑表限制再改SQL。缓存失效或失败重试仍从本次完整输入重算并遵守各自预算；失败不发布半份结果、不静默截断引用或提高限额、不落盘续跑。

错误沿现登记：识别`XXM_REQUEST_INVALID`400、`XXM_NOT_SUPPORTED`404、`XXM_SOURCE_CONTRACT_INVALID`500、`XXM_BUDGET_EXCEEDED`503、`XXM_QUERY_FAILED`一般500（下述现有缺reader分支例外）；来源未就绪沿现200的EMPTY/DELAYED状态，并非捕获所有错误。预测使用现XXMF对应映射；波段沿`DAILY_WAVE_INVALID_REQUEST`422、`DAILY_WAVE_SOURCE_INVALID`503、`DAILY_WAVE_CALCULATION_FAILED`503、`DAILY_WAVE_BUDGET_EXCEEDED`503。当前`query_service.load_entry`缺本地分钟reader时显式以XXM_QUERY_FAILED/503抛出，与登记中的一般查询失败500不同。此处记录并保留该现有状态，不顺手改API行为；正常本地分钟装配/预测资格应先拒不支持，此分支仍用直接query调用反例覆盖。P1在原合同/登记备注清楚这一已有边界，不把所有QUERY_FAILED统一改503或500。实际错误码以[异常登记](../../system/exception-code-registry.md)及现处理器核对，不能临时增加。生产未注册路径由原框架404，不进入来源或计算。

服务端保留现只读源和会话管理，取消向上传递、finally释放信号量/连接/共享加载订阅；不因一个请求取消就修改另一请求已发布结果。新的SeriesEntry/完整预测缓存只在全部校验成功后发布。不能捕获CancelledError转成功或缓存异常为空结果。debug文字不得返回凭据、SQL或本机绝对路径。

本轮不触发数据读取。实施时涉及真实源的最小核验先限定标的/周期/日期、原字段和上限；复用仍有效证据。若需全数据集明细读取须另按根AGENTS取得明确范围批准；“只读”不是全局读取的自动许可。

## 10. 清退清单、有效能力迁移及迁移等价验收

§11.1为本清单所有有效辅助/字面测试迁移的固定落点；其中不保留的旧runner/compare格式化无需迁移。以下清单不是通配符删除授权。

### 10.1. 清退顺序与硬边界

1. 先把当前已批准r4-v2的规则、人工预期和身份约定迁入唯一正式实现；等价核验必须在旧研究r4仍绑定旧父类时取到完整基准。不能先改父类再把新继承结果叫作旧r4。
2. 迁移所有查询新建、历史位置复制、增量计算、预测clone、类型/解码/缓存身份；不保留r2模式、参数、回退或执行入口。
3. 保留工具先解除对旧算法源码、旧SHA和旧结果读取器的依赖；纯行情/日历/原图继续按明确来源核验，不能把来源校验一起删除。
4. 所有调用迁完、唯一r4和保留工具通过后，才删除本清单内旧实现、专属执行器和专属测试。旧模块的生成缓存只按对应模块清理，禁止删共享解释器环境或用户其他数据。
5. 删除前检查本清单各文件当前git状态。未跟踪文件也在清单核查范围；出现清单外调用方或他人正在修改的冲突，先停止并说明，不擅删、加兼容层或移到.txt/Markdown代码块伪封存。
6. 历史设计、开发、报告、原CSV/JSON/图片和Git历史保留；旧运行成绩不改版本、不重写。CLI和README中活动命令清零，历史记录明确不再可执行，不为死链恢复旧代码。

### 10.2. 研究主目录逐文件处理

本节路径前缀统一为 `scripts/research/index_market/xxm/`，每行都是一个实际文件。表中“迁出”只指仍被当前r4验证需要的既有能力，不为旧试验增加新框架或新运行模式。

| 文件 | 最终处理与保留边界 |
|---|---|
| `__init__.py` | 保留主题包；更新说明，不从中注册旧实现。 |
| `r4_reference_trial.py` | 新正式r4按独立人工预期及迁移前记录完成等价验收后，删除研究识别类、复制step、研究Spec和包装恢复。不是把它改成继承正式r4的第二份实现。 |
| `r4_observation.py` | 删除ObservedR2Calculator、旧研究R4继承；真实分支观察的有效能力迁入§7唯一正式step及手动离线函数。普通/debug必须调用同一规则，不在页面推断。 |
| `r4_comparison.py` | 删除r2/r4双计算、旧五字段账本和运行入口。不得把正式r4冒称r2。旧compare终端格式化不迁入产品；当前单组核验使用§11.1已有原路由工具，不留双算法入口。 |
| `r4_comparison_records.py` | 不保留硬编码r2/r4配对接口。记录引用完整性的独立反例迁§11.1所列恢复/合同tests；旧配对/因果推断及无当前消费者的格式化helper直接删除。 |
| `confirmation_only_trial.py` | 迁出纯字面算术样本后删除完整TwoDigitTurnCalculator、复制step、旧Spec/源码SHA/AST保护及双组身份。 |
| `confirmation_comparison.py` | 删除旧r2/两位计算、读取/重放/CLI入口及专属账本比较。不得去掉旧保护后悄悄继承r4。 |
| `reference_rescue.py` | 删除BottomDullRescueCalculator、R1_POLICY、new/child_of及旧比较/重放入口；其已批准且仍适用的行为只在正式r4一处存在。 |
| `reference_rescue_paths.py` | 删除旧候选clone/路径求解复制实现；正式预测直接使用本文完成修正后的产品路径，不保留研究双轨。 |
| `reference_rescue_forecast.py` | 删除旧候选forecast/make_display/main，不在正式产品或debug动态加载。 |
| `top_daily_ambiguity.py` | 删除ReferenceGateCalculator、BASE/T2/S2/ZC/ZR多算法模式及运行器。原截图事实保留，不能连带删除原图或文字观察。 |
| `top_current_close.py` | 删除TopCurrentCloseCalculator及旧对照入口；ordinary/check_time等小辅助只有确认当前单组核验仍需要时并入现测试，不能为保留旧类留下文件转发。 |
| `top_current_close_selection.py` | 删除PriceBeforeSelectionCalculator及旧运行/保护/比较。 |
| `top_reference_priority.py` | 删除NearFirstCalculator及旧运行/保护/比较。 |
| `top_return_reference.py` | 删除ReturnReferenceCalculator及旧运行/保护/比较。 |
| `cross_index_daily.py` | 删除依赖ReferenceGateCalculator的BASE/ZC/ZR实验和其运行/恢复入口。纯来源行/日历检查若仍需要，由现有有界来源模块承担；不把此清退扩为新深市r4产品功能。 |
| `same_segment_acceptance.py` | 删除r2/A1 frozen_mode、可选旧门槛及旧runner；有用独立人工输入先迁当前产品验收，不保留旧算法模式。 |
| `reference_rescue_acceptance.py` | 删除r1/r2旧frozen/semantic compare/formal_replay入口。保留验收需要的人工案例和源材料；旧expected/Spec不作为新r4结果。 |
| `bottom_history_acceptance.py` | 删除旧H/A1/R1/R2专用runner、旧frozen/API基线比较。新r4真实只读验收复用已有正式读取保护/原路由，不沿用此模块作为隐含数据库入口。必要已有日历/原始数值辅助在删除前迁当前测试。 |
| `cancellation_restart_audit.py` | 删除对A1旧事件账本要求完全相等的runner；其原材料、结论和可人工理解的案例保留文档。 |
| `cancellation_restart_detail.py` | 删除旧16次重启研究入口和对旧基线的引用；必要独立日期/资格算术样本迁当前r4测试，不保留旧版本模式。 |
| `rearm_discrimination.py` | 删除旧A1基线对账和模拟runner；仍适用的等待边界字面样本迁正式r4测试。 |
| `top_activation_expectations.py` | 删除借cross_index_daily保存/恢复旧r2 expected账本、旧源码保护和旧runner。独立字面/有理数数学预期与作者观察分离保留，不把旧计算输出重命名r4。 |
| `top_activation_math.py` | 保留pair/daily_options及独立Fraction公式；expectations仅1%字面案例，不再运行0.75/1.2门槛；该组目标零柱由旧严格边界改为包含等号，仍须满足正收盘/1%，完整手算见§11.2.1。生产不得import预期生成器。 |
| `top_activation_real_math.py` | 仅保留meet/minus/interval及必要pair依赖。删entry_domains/proof/main、旧常量和保存/日历导入；entry_domains按DIF强弱选峰不能成为r4预期，见§11.2.1。 |
| `forecast_expectations.py` | 删除未使用expected_unit导入；保留fraction/contains/regions/assert_partition/coefficients。删除verify_changed_forecast及MATH_KEYS旧oracle；其严格排除零目标/只准无切换的断言不是r4通用数学。有效字面条件迁现预测tests，见§11.2.1。 |
| `acceptance.py` | 只留sha/load_source/collect_readouts的纯来源读取和作者数值事实；删replay/main、产品类/Spec/冻结读取导入、旧结果writer及CLI，见§11.2.1。 |
| `frozen_inputs.py` | 解除§11.2.1列出的旧消费者后整文件删除，不新增替代reader。其唯一旧源reader会缺DEA反算，旧expected_*及forecast_inventory均清退。原CSV/manifest保留，完整真实源由现load_source/read_case/read_window读取，不补值。 |
| `daily_window_precheck.py` | 仅保留validate_window/read_window/isolated_client；删capture/replay_checks/validate_capture_identity/check/main、旧b/MATH_KEYS/semantic依赖及全部结果写入。隔离App在原文件接正式装配，不再借待删app_for；见§11.2.3。 |
| `history_disappearance_screen.py` | 仅保留dif_diagnostics/history_record/event_signature纯事实及REVIEWED原材料说明，并增加§7 observe_rows。删除select_candidates/load_bars/screen_period/protected_paths/identity/verify_protected/run/main、旧frozen/多门槛重放及read_unit/seal依赖。history_record只核实际结构/历史/价格关联；初始DULL可能保存B而结构已用A，不能以两者参照不同拒绝合法r4记录。来源窗口/原观察不改写。 |
| `history_replacement_screen.py` | 仅保留ordinary_index纯事件唯一性/时刻检查；删除local_followup/screen_period/select_candidates/identity/run/main及旧read_unit/seal/import/落盘/保护，清仅服务旧试验的常量，保留ordinary_index必需的ORDINARY字面集合。local_followup跳过new_*_DULL后延长旧历史是另一套旧寿命试验，不能换成r4身份继续运行。原材料/报告保留。 |
| `near_first_review.py` | 最小化保留decimal_value/quantize_dif及必要数值校验和说明；仅依赖Decimal/ROUND_DOWN及纯number。删除ReviewSpec/Reference/choose_reference/decision_signature、旧选峰/合并/replay_june/protected_evidence/check_protected/run/main。不得因“保留此函数”保留整份旧判别代码。 |
| `reference_window_review.py` | 仅留sign/build_references原始事实，删qdif及quantize导入、ReviewSpec/SPEC/LIMITATION/inspect_prefix/review_locked_reference/run/main和writer；输入由saved_minute_window供给，见§11.2.2。 |
| `same_bar_dull_review.py` | 删除advance_bottom和display_events及旧状态校验，不能继续自行产生CANCEL/DULL/STRUCTURE或隐藏“先取消再钝化”。真实r4已在取消前换参照，无需第二层抹事件。 |
| `local_extrema_study.py` | 保留纯输入/扫描/独立样本/benchmark；protected_files/assert_protected仅核原材料。删save_new/main和结果writer，notebook只返回未执行字典，不exec/写文件；既有Notebook/原材料不改，见§11.2.2。 |
| `peak_image_measurement.py` | 保留图像量取函数与人工尺寸/颜色预期，不借它计算正式标签。 |
| `saved_minute_window.py` | 保留已知来源CSV的有界定位、列/日期/数值校验及read_window，不重算MACD、不产生标签。来源SHA是数据身份，不能与旧源码SHA保护一起清空。 |

#### 10.2.1 其他主题级执行文件

这些路径不是上表xxm子目录，必须一并处理：

| 完整路径 | 处理 |
|---|---|
| `scripts/research/index_market/xxm_forecast_display_audit.py` | 改为§11.2.4原路由RAM核验；删除--candidate/--output及旧动态算法/源码SHA和所有响应写入，复用同一正式环境装配及只读App。 |
| `scripts/research/index_market/xxm_page_request_audit.py` | 原文件提isolated_app(settings)供两个Python工具复用；保留原鉴权/只读/临时server清理，删除--output和完整响应保存，按§11.2.4迁正式装配和合同。它当前尚不是RAM验收工具，不原样复用。 |
| `scripts/research/index_market/xxm_page_request_audit.mjs` | 保留真实客户端HTTP请求核验，去output/writeFile/persist，使用实际1000常量及新normal/debug合同，仅RAM；Node脚本不冒称浏览器验收，见§11.2.4。 |
| `scripts/research/index_market/xxm_history_projection_audit.py` | 仅源行情投影核对能力，未发现r2识别实现；保留。不因文件名xxm删除。 |
| `scripts/research/index_market/README.md` | 清理活动旧CLI/旧candidate/旧两位命令，保留已注明历史的事实记录；当前入口只指新LLD。不得把历史命令成功作为当前结果。 |

### 10.3. 旧报告中的执行代码

先迁仍有用的原输入/截图事实核验；只删除本节明确的代码文件，绝不删除整个报告目录。下面报告路径按表中前缀组成，均是具体待删文件，禁止删除整个目录。

#### 10.3.1 旧MACD研究执行链（45个.py）

前缀 `reports/xxm_macd_structure_20261011/`。静态AST核到以下文件自身定义旧replay或直接/间接import旧replay，全部清退执行代码，不以“.py还原为.txt”保留：

- `active_reference_candidate.py`：删除旧执行代码。
- `audit_0366.py`：删除旧执行代码。
- `audit_0369_0370.py`：删除旧执行代码。
- `audit_0374.py`：删除旧执行代码。
- `audit_20251016.py`：删除旧执行代码。
- `audit_20260105_pair.py`：删除旧执行代码。
- `audit_20260605_user_captions.py`：删除旧执行代码。
- `audit_90_history_prefix.py`：删除旧执行代码。
- `audit_active_reference_captions.py`：删除旧执行代码。
- `audit_active_references.py`：删除旧执行代码。
- `audit_context_contrasts.py`：删除旧执行代码。
- `audit_correction_lifecycle.py`：删除旧执行代码。
- `audit_july3_chart.py`：删除旧执行代码。
- `audit_july3_lecture.py`：删除旧执行代码。
- `audit_june_context.py`：删除旧执行代码。
- `audit_lifecycle_trace.py`：删除旧执行代码。
- `audit_narrated_thresholds.py`：删除旧执行代码。
- `audit_nov11_lecture.py`：删除旧执行代码。
- `audit_nov13_17_charts.py`：删除旧执行代码。
- `audit_nov13_lecture.py`：删除旧执行代码。
- `audit_nov14_daily_disappearance.py`：删除旧执行代码。
- `audit_nov14_lecture.py`：删除旧执行代码。
- `audit_november_followup.py`：删除旧执行代码。
- `audit_october_reference_membership.py`：删除旧执行代码。
- `audit_reference_extrema.py`：删除旧执行代码。
- `audit_reference_extrema_captions.py`：删除旧执行代码。
- `audit_reference_lifecycle.py`：删除旧执行代码。
- `audit_source_sensitivity.py`：删除旧执行代码。
- `audit_threshold_constraints.py`：删除旧执行代码。
- `audit_turn_filters.py`：删除旧执行代码。
- `audit_wave_boundaries.py`：删除旧执行代码。
- `audit_withdrawal_price_context.py`：删除旧执行代码。
- `freeze_post_june9.py`：删除旧执行代码。
- `reference_extrema_candidate.py`：删除旧执行代码。
- `reference_retirement_candidate.py`：删除旧执行代码。
- `replay.py`：删除旧执行代码。
- `replay_color_flip.py`：删除旧执行代码。
- `replay_frozen_25_points.py`：删除旧执行代码。
- `screen_discriminating_nodes.py`：删除旧执行代码。
- `screen_reference_retirement.py`：删除旧执行代码。
- `screen_structure_withdrawal.py`：删除旧执行代码。
- `screen_withdrawal_recensor.py`：删除旧执行代码。
- `turn_filter_candidate.py`：删除旧执行代码。
- `validate_stage2.py`：删除旧执行代码。
- `wave_boundary_candidate.py`：删除旧执行代码。

同目录4个不导入旧replay的文件不能按目录一并删：

- `audit_90_numeric_semantics.py`：保留原始数值/来源/EMA精度审计用途；不接正式识别或debug，不把它的来源模拟当产品指标。若其中固定历史路径不再存在，则从当前活动运行命令移除，保留其文档结果，不恢复旧识别实现。
- `audit_june26_lecture.py`：保留原始数值/来源/EMA精度审计用途；不接正式识别或debug，不把它的来源模拟当产品指标。若其中固定历史路径不再存在，则从当前活动运行命令移除，保留其文档结果，不恢复旧识别实现。
- `audit_software_numeric_history.py`：保留原始数值/来源/EMA精度审计用途；不接正式识别或debug，不把它的来源模拟当产品指标。若其中固定历史路径不再存在，则从当前活动运行命令移除，保留其文档结果，不恢复旧识别实现。
- `export_90_jan13.py`：保留原始数值/来源/EMA精度审计用途；不接正式识别或debug，不把它的来源模拟当产品指标。若其中固定历史路径不再存在，则从当前活动运行命令移除，保留其文档结果，不恢复旧识别实现。

#### 10.3.2 其他已核旧实现/执行器（18个.py）

- `reports/xxm_bottom_history_precheck_20261016/candidate.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_bottom_history_precheck_20261016/finalize_report.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_bottom_history_precheck_20261016/run_additional.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_bottom_history_precheck_20261016/run_budget.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_bottom_history_precheck_20261016/run_forecast.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_bottom_history_precheck_20261016/run_frozen.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_forecast_range_precheck_20261014/http_precheck.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_forecast_range_precheck_20261014/range_model.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_forecast_range_precheck_20261014/run_precheck.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_forecast_range_precheck_20261014/synthetic_cases.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_forecast_range_precheck_20261014/text_model.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_forecast_range_precheck_20261014/validate_model.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_minute_reader_optimization_20261014/checkpoint_compare.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_minute_reader_optimization_20261014/compare.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_minute_reader_optimization_20261014/http_precheck.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_minute_reader_optimization_20261014/prototype.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_forecast_precheck_20261014/precheck.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。
- `reports/xxm_forecast_range_implementation_20261014/http_acceptance.py`：不保留候选/旧预测/旧runner；仍有用的独立数学或当前读取验证先迁至主题现有测试/工具，再删除该报告执行文件。该目录的JSON/CSV/图片/README不随之删除。

#### 10.3.3 Notebook、原始材料和历史文档

- `reports/xxm_local_extrema_trial_20261021_01/review.ipynb`：保留。代码单元只导入正式daily_wave扫描器和local_extrema_study，无r2执行；生成器`local_extrema_study.notebook()`同步核当前路径，不能因清退旧报告.py把Notebook连带删除。
- 不修改历史`run.json/manifest.json`的内容或SHA，不把当前代码重新登记成旧运行代码。新运行保护仅白名单验证所需原始数据/图片，不从旧manifest的protected/codeSha字段递归要求旧源文件存在。
- `local_extrema_study.CASES`三份必要材料保留：`reports/xxm_m120_reference_trace_20261020_01/source_window.json`、`reports/xxm_same_day_m90_m120_20230301_20261020_01/m90_source_window.json`、`reports/xxm_feb25_m90_reference_evidence_20261021_01/source_projection.json`。
- 原算术/图像材料保留：`reports/xxm_jun25_reference_evidence_20261021_01/saved_comparison.json`、`reports/xxm_aug07_price_reference_evidence_20261021_01/old_segment_source_projection.json`、`reports/xxm_peak_comparison_images_20261021_01/02_near_and_skipped_peak.png`，以及引用这些材料的历史README/作者图文。旧条件判断只保留为历史结论，不继续作为新r4判别。
- `reports/xxm_source_audit_20261013_213852/`中的原始日线/分钟源和SSE日历、`reports/xxm_forecast_precheck_20261014/future_sse_calendar.json`等仍被测试使用的输入不得按父目录删除。原始输入与旧API输出必须分开登记。
- `reports/xxm_top_activation_r2_implementation_20261019/api/`、`reports/xxm_reference_rescue_r1_implementation_20261017/api_02/`、`reports/xxm_same_segment_a1_implementation_20261016/api/`的旧响应JSON只作历史结果；活动测试不能只换版本/hash继续把它们当新r4金样本。不改写旧JSON来迎合新实现。
- 新增/整理LLD索引时，原r2设计与开发文档标历史及后继入口，不删除整份研究演进。不能把本清单状态写成已删除。

### 10.4. 迁移前r4基准与内存等价核验

最终正式位置仍为`src/biz/services/wealth/market/index_detail_xxm/calculator.py:XxmCalculator`；不新增临时产品类、旧实现转发或第二个产品入口。下述仅为人工触发的迁移验收，不注册后台任务/服务，不保存源码、行情、账本或恢复文件。

1. **捕获时点。**原首次捕获在P2改`calculator.py`/MAIN_SPEC前，由验收进程使用当时真实研究`R4Calculator`（researchVersion明确为`xxm-research-r4-v2`）和未迁移父类，计算已批准的同一组人工输入。先独立断言关键结果符合本LLD的字面预期，再深复制成仅含标准Python数值、字符串和列表/字典的输入及完整业务记录。释放旧计算器对象；不能把旧类/方法传给新进程，也不能把旧恢复进度交给新r4。
2. **保留内容。**仅内存保留输入的time/close/dif/dea/hist/completed，四周期身份，以及逐根point、事件、顶部/底部历史及等待记录、原始编号关联；同时保留标准化业务进度的wave、history、reference、previous、processed及pending各项，用于比较计数、原值极值和发生日期。这些进度只作比较，绝不能restore给新算法。必要旧研究版本/hash作为事实元数据保留，不是源码SHA保护。每组最多1000根，不读取真实来源；原始数值不截位、不重算MACD。
3. **新实现计算。**原位置改为独立正式r4后，新进程必须exec现有解释器启动，不能fork继承旧sys.modules；只用有界stdin/stdout管道交接标准数据、退出非零即失败。新进程只导入正式业务模块，按保留的标准输入从空状态重算，结果经有界管道返回验收进程。新进程禁止import研究旧包装或根据旧输出决定标签。旧进程不重新import/reload产品或再次调用旧研究计算器；这防止新父类污染所谓迁移前基准。
4. **编号映射。**按`(time,type,direction,route,eventReference四字段、对应原色段起点)`先对应不依赖历史/等待编号的普通事件（包括STRUCTURE），再由STRUCTURE对应顶部/底部历史，继而对应等待记录，最后对应历史价格撤销/重新激活等带关联事件并核全部引用。新旧身份本来不同，只允许编号及其关联按这份明确映射变化。映射缺失、多义、跨类型、未来引用或悬挂引用均失败，不能按最近日期强配。所有原参照的日期/价格/DIF、结构/钝化时点、历史冻结值与退出原因、等待门槛与状态、根末状态及方向必须逐项相等，不能只数标签。
5. **预算。**148个案例/周期的捕获合计一个20秒阶段；全部新计算、管道交接及父进程比较合计另一个20秒阶段，不逐案例或逐周期重置时间。单进程256MiB、全部保留记录16MiB；单组自动测试60秒。等待代码编辑不记计算耗时，不轮询计算、不读来源、不作为后台业务任务。管道输入/输出均有数量/字节上限，不能收到半份即报告成功。等待期间仅保留核验需要的内存，不持有数据库连接。
6. **失败/中断。**任何一侧输入、版本、完整性、编号映射、资源或结果不一致，整项验收失败，无部分通过。进程退出丢失内存，该次迁移对账作废；禁止升级后再用旧包装补一份基准或把独立单测冒称该对账通过。届时保留未发布工作并说明缺失依据，不自动checkout、创建worktree、恢复r2副本或写恢复文件。重新开展此项须先具备真正的迁移前捕获条件；独立字面测试继续用于定位，不替代已丢失的迁移对账。
本次旧内存丢失后的重新捕获已获管理员明确批准：仅按§19从固定迁移前提交在隔离进程内加载五个旧源码，不使用当前旧包装，不恢复工作区或旧产品副本。此前失败记录保留；此例外不构成长期Git加载能力。

7. **长期回归。**对账只是迁移证据，永久预期仍为独立人工可核的字面输入/输出和已确认软件观察。删除旧r2/研究副本后，长期测试不再需要旧类、旧Spec或Git源码加载。不得为“可重跑比较”重新保留r2运行模式。

#### 10.4.1 P2开始时先建立核验入口，再保留旧结果

这一项是P2的第一个编码步骤，**不是P1已经完成的事实**。先新增下列仅测试用文件及其限定测试；在终端实际收到本节的`CAPTURE_READY`前，不得修改产品`calculator.py`、`spec.py`、`types.py`、`snapshot_validation.py`或研究`r4_reference_trial.py`。这些文件直接决定旧r4的计算或记录形状，必须全部排在捕获之后。新工具不复制step，不借现`r4_comparison`双组执行器；该旧执行器还会计算r2，不符合本次只核对迁入前后同一r4的范围。

| 预定文件（均在`scripts/research/index_market/tests/`） | 责任与禁止项 |
|---|---|
| `xxm_product_v1_migration.py` | 一次性父进程入口；`capture_baseline()`按独立预期检查并保留旧结果，`assert_case_facts()`核P1字面断言，`compare_records()`核完整记录及编号。原首次捕获只有capture函数可延迟导入旧研究类；现重新捕获由§19独立旧子进程承担，父进程不导入旧类；import/帮助/协议单测不计算。收到READY后不再调用旧类、restore、import或reload产品/研究模块 |
| `xxm_product_v1_migration_worker.py` | 新实现的单次计算入口；只用标准库和正式业务模块，从stdin接人工输入，从空计算并返回标准记录；不导入研究包装、旧双组工具或父进程的旧结果。不提供restore或算法选择参数 |
| `xxm_product_v1_migration_capture.py` | §19限定旧捕获子进程；仅固定Git提交的五源码在内存编译加载，不checkout、不写源码或pycache，不导入当前正式计算器 |
| `test_xxm_product_v1_migration.py` | 用独立手写标准记录检查数据协议、编号映射、缺项/多义/数值差异/超限/异常清理；通过替身验证进程调度时明确只证明协议，不冒充实际迁移对账。P2最后必须执行真正的新进程对账 |

上述四个路径是本次明确的一次性测试范围，纳入§11.1允许落点；不增加产品CLI、HTTP、配置或长期验证框架。P5在迁移证据已写入实施记录后删除上述一次性入口、worker及专属协议测试；有效独立业务断言留在当前正式r4测试，不保留旧类调用以便重放。

**人工输入与保留字段。**固定使用`xxm_product_v1_cases.CASES`的37例，按该文件`PERIODS`顺序day/m60/m90/m120、每周期按CASES声明顺序执行，共148个独立案例；每例重新从空开始，不把前例状态传给后例。`Case.inputs(period)`只格式化日期，不能补行情。`sourceIdentity`在两侧统一传`p1:{period}:{case.name}`，`tsCode`固定000001.SH。预期仅来自P1的`references/checks/facts`；`event@6`等只表示第6根实际事件的关联，不能当正式ID。`assert_case_facts`逐项显式对应真实point/事件/历史/等待/进度字段，未知事实名必须失败，不得忽略。该映射完成且人工断言通过，才允许发布READY；不按旧程序输出改写预期。

每例标准记录固定含`caseName/period/sourceIdentity/bars/steps`；bars只含time/close/dif/dea/hist/completed。每步含`point/events/histories/bottomHistories/rearmRecords/stateBefore/stateAfter`；前五项分别完整深复制`XxmStep.point/events/histories/bottom_histories/rearm_records`，后两项按现snapshot键提取`wave/history/state/reference/previous/processed/pending/pendingBottomHistory/pendingRearm`，包含空值、极值发生日期和顶部历史的全部计数。history沿现快照的字符串键`"1"/"-1"`；其他字段、数值、数组顺序不得丢弃或重算。研究外壳的parentState仅用来提取这些字段，不传给worker；specHash、researchHash、算法版本及包装后的sourceIdentity另留元信息，不拿身份差异当业务差异，也不据此豁免业务字段比较。两侧输入的原始sourceIdentity必须相同；仅允许旧parentState中的研究包装和正式身份按各自预期存在差异。

**终端操作与进程交接。**下列保留原首次P2操作顺序；本次修复执行按§19，真正结果已见§19.6。

```text
.venv/bin/python -B -m scripts.research.index_market.tests.xxm_product_v1_migration
CAPTURE_READY cases=148 periods=day,m60,m90,m120
（保持同一终端进程，另行修改已批准的P2产品文件并完成定向测试）
compare
（全部一致时输出PASS摘要并退出；失败输出差异位置并非零退出）
```

原首次操作的第1—2项仅为历史顺序；本次不再改核心，也不等待编辑。按§19重新捕获后立即发送compare，既有两个20秒整批限额不变。

1. 原首次父进程先确认当前MAIN_SPEC仍是实际r2身份、研究Spec仍为已批准r4-v2，检查输入/限制，再按四周期分别捕获。只核当前对象字段，不读源码、源码SHA或Git旧代码。每一步独立事实和完整字段检查通过才保存；全部148例通过后释放计算器/旧方法对象，仅保留标准记录及元信息，输出并flush唯一READY行。任何失败在修改产品文件前终止，不能捕获半份后继续。
2. READY后父进程阻塞等待stdin的一行`compare`或`abort`；无轮询、网络、数据库或磁盘保存。等待编辑不计计算时间，不持有源连接；它是人工维护的临时核验进程，不是后台业务服务。`abort`、EOF、Ctrl-C均释放内存并退出，不能将其记为验收成功。其他命令拒绝且不开始计算。
3. 输入compare后，父进程以`sys.executable -m scripts.research.index_market.tests.xxm_product_v1_migration_worker`只启动一个全新解释器，不复用旧模块。一次只发全部148例的`caseName/period/sourceIdentity/bars`，**不发旧结果、P1预期或旧快照**。worker检查正式Spec为r4，再对每例从空计算；返回正式版本/hash及按原顺序的全部标准记录。worker只写一份结果JSON到stdout，不写调试日志；错误向stderr写有限原因并非零退出。
4. 父进程验证worker身份、案例集合/顺序、日期、有限数值、完整字段及引用，再先核P1独立事实、后按§10.4第4项映射编号比较全部结果。普通事件原色段起点从事件前后state的wave和事件方向确定；历史价格撤销事件用其related历史确认记录确定，不能取撤销当天的新wave。顶部历史没有structureEventId，必须凭confirmedAt/confirmationRoute/originalReference及该STRUCTURE事件唯一关联；底部历史和等待使用显式structureEventId及bottomHistoryId。建立完整一对一映射后，仅在比较用深复制里替换明确的ID及引用字段，再精确比较；不修改原记录、不断言“标签相同即通过”、不放宽数值误差。缺失或不唯一立即失败。
5. 使用§10.4第5项的两个整批20秒截止，单调时钟从各阶段首个动作前开始，包含独立断言、序列化、完整性检查及清理；不得逐案例或周期重置。计算、收发和比较最多用前19秒，末1秒保留终止/回收，不能额外追加超时等待。每个案例/周期≤1000根；输入/输出消息分别≤16MiB，父进程全部保留数据（含收到的新记录）合计≤16MiB、单进程≤256MiB；stderr≤64KiB。编码/解码前检查结构数量，管道分块读并在累积超限时停止，不能先无界communicate再查长度；超限、卡住或非零退出立即停止后续工作、终止并回收child。自动测试每组仍≤60秒，默认pytest收集不得启动捕获或等待编辑。
6. 父进程最后只输出案例数/周期、耗时、结果字节及PASS或首个`case/period/bar/字段`差异摘要，不打印全份行情/业务记录，不写任何结果文件。成功/失败/中断都关闭管道并回收child，失败没有部分成功；父进程或内存丢失沿§10.4第6项处理。P2实施记录只登记摘要与覆盖范围，不保存可恢复进度或旧实现。

**验收先后不可互换。**协议测试通过→真正READY→允许修改旧依赖文件→正式r4独立测试通过→全新worker实际比较通过→P2独立审计。前一步只为后一步提供条件，不代表后一步已完成；不得用P1材料测试、协议替身、编辑后的旧包装或新r4自己的输出替代真正旧结果。

### 10.5. 主题测试逐文件处理

前缀统一为 `scripts/research/index_market/tests/`。删除旧专属测试前，已批准且仍适用的反例先迁当前r4单组测试；删除不是跳过错误或降低覆盖。

| 文件 | 处理 |
|---|---|
| `test_xxm_calculator.py` | 迁当前正式r4；保留独立人工核心、1%、翻色、原参照、历史、等待、恢复预期；移除旧r2零切段/最强选峰专属预期和旧frozen账本相等测试。 |
| `test_xxm_input_validation.py` | 保留，改为唯一正式r4入口；布尔/NaN/无穷/逆序/未完成拒绝及合法输入反例均保留。 |
| `test_xxm_snapshot_validation.py` | 保留严格恢复、拒错后对象不变及合法继续；删旧r2独立零段合法性断言，按r4零中性/新身份预期。 |
| `test_xxm_snapshot_consumers.py` | 保留真实查询calculator_at/load/clone恢复调用；所有构造器为唯一正式r4，不能mock恢复成功。 |
| `test_xxm_r4_reference_trial.py` | 有效R4-18—24、选峰/零日/恢复人工样本迁正式r4测试后删除研究包装/父r2身份专属测试；不保留第二识别类。 |
| `test_xxm_r4_observation.py` | 有效真实调用次数、before B/after A、转折理由及不篡改记录测试迁§7离线观察；ObservedR2和旧父方法包装测试删除。 |
| `test_xxm_r4_comparison.py` | 删除双算法重放/旧组身份专属测试；资源上限、当前结果完整性、无副作用及独立字面报告用例按保留工具迁移。 |
| `test_xxm_r4_records.py` | 仅迁仍被保留的当前记录/独立预期引用完整性反例；旧r2/r4组配对预期删除。 |
| `test_xxm_confirmation_only_trial.py` | 取数字面样本迁最小算术测试；整份旧类/源码保护/旧r2政策/恢复suite删除。 |
| `test_xxm_confirmation_comparison.py` | 删除旧r2/两位编排、CLI和专属账本预期；当前来源核验能力已有正式测试承接，不能为留此suite恢复旧执行器。 |
| `test_xxm_near_first_review.py` | 最小化为decimal_value/quantize_dif人工算术及非法输入；删除旧choose_reference/合并/条件重放预期。 |
| `test_xxm_reference_window_review.py` | 仅核sign/build_references的原始日期、平台、数值；删qdif及旧eligible/selected/两位生命周期和writer测试。 |
| `test_xxm_same_bar_dull_review.py` | 旧advance_bottom/display_events删除后本专属文件删除；已批准的同根B→A人工行为由正式r4测试承接，不测试“先双报再隐藏”。 |
| `test_xxm_saved_minute_window.py` | 保留纯取窗/列/原值/边界测试，无标签计算。 |
| `test_xxm_local_extrema.py` | 保留扫描器/平台/图像量取字面预期。 |
| `test_xxm_local_extrema_study.py` | 保留输入身份、独立数学/图像和扫描性能；旧拒覆盖writer测试改为无结果写入/原料不变；Notebook仅核返回的未执行字典，不执行真实窗口。 |
| `test_xxm_top_activation_r2.py` | 将仍适用的首次TOP正DIF、两根、预测资格独立用例迁当前测试，删除旧版本/旧frozen期望及旧文件。 |
| `test_xxm_top_activation_expectations.py` | 独立数学预期迁当前预测测试；删除旧r2账本保存/保护/IdMap专属预期。 |
| `test_xxm_top_activation_real_math.py` | 仅保留meet/minus/interval纯数学预期；删entry_domains/proof及旧报告身份测试。r4选峰/求价另用P1独立字面预期，不沿用最强排序oracle。 |
| `test_xxm_top_current_close.py` | 删除旧TopCurrentCloseCalculator专属测试；通用收盘口径反例先迁正式r4。 |
| `test_xxm_top_current_close_selection.py` | 删除旧PriceBeforeSelectionCalculator专属测试。 |
| `test_xxm_top_reference_priority.py` | 删除旧NearFirstCalculator专属测试；已批准先B后A反例由正式r4覆盖。 |
| `test_xxm_top_return_reference.py` | 删除旧ReturnReferenceCalculator专属测试，不能影响正式r4原参照跟踪测试。 |
| `test_xxm_top_daily_ambiguity.py` | 删除BASE/T2/S2/ZC/ZR多变体测试；已确认正DIF和根数规则迁当前r4。 |
| `test_xxm_reference_rescue.py` | 删除旧研究候选类测试；正式r4顶/底DULL当根救援和失败边界保留。 |
| `test_xxm_cross_index_daily.py` | 旧多指数变体实验测试删除；SSE共用日历、日期/字段合法性仍由当前来源测试核验，不恢复研究算法。 |
| `test_xxm_acceptance_scope.py` | 保留真实读取边界/权限/有限范围等当前仍适用的检查，迁当前入口；删旧frozen/spec/候选模式及旧账本混合预期。 |
| `test_xxm_daily_window_precheck.py` | 保留validate/read_window和isolated_client的独立合同；删旧capture身份、frozenOverlap、writer及旧响应基线测试，补正式装配/字节正文与normal/debug投影。 |
| `test_xxm_cancellation_restart_audit.py` | 旧A1账本相等及旧runner专属测试删除；仍适用的取消/连续钝化人工反例迁正式r4。 |
| `test_xxm_cancellation_restart_detail.py` | 旧16次研究专属suite删除；有效严格价格/等号用例迁正式r4。 |
| `test_xxm_rearm_discrimination.py` | 旧A1对账suite删除；等待/当根收盘/原DIF边界迁正式r4。 |
| `test_xxm_history_disappearance_screen.py` | 保留dif_diagnostics/history_record/event_signature的独立字面测试，补§7 observe_rows及合法B→A后原DULL/结构不同参照；删旧runner/保护/frozen/候选排序测试。 |
| `test_xxm_history_replacement_screen.py` | 仅保留ordinary_index的时刻/唯一性/方向反例；删除local_followup和旧延长历史/runner测试，不将旧替换政策迁r4。 |
| `test_xxm_confirmed_cases.py` | 保留来源明确的作者截图观察及其原预期，迁正式r4；如真实观察不符应报告，不改原预期凑通过。 |
| `test_xxm_key_point_forecast.py` | 保留独立求价/精度/区间/禁止中点概括等有效测试，按唯一r4和全部路径修正；不依赖旧算法生成expected。 |
| `test_xxm_forecast_reference_paths.py` | 迁正式r4顶底B→A/零日路径，删除研究候选路径类及旧排序预期。 |
| `test_xxm_forecast_display.py` | 保留当前正式r4文本和条件显示，解除经key_point_forecast.frozen间接导入旧账本。 |

#### 10.5.1 跨层现存夹具消费者必须迁移

| 当前消费者 | 要求 |
|---|---|
| `tests/web/test_wealth_index_detail_xxm_api.py` | 唯一r4请求/来源/DTO/恢复、普通与debug投影及本地/生产门禁。旧API JSON不作新金样本。 |
| `tests/web/test_wealth_index_detail_xxm_forecast_api.py` | 第239/268/587附近读取r2 API夹具、301及594/625附近读A1/R1旧响应的测试分开处理：新r4金样本用独立输入/手写期待；旧响应只用于明确“旧版本必须拒绝”的反例，不能改几个身份字段后声称当前完整合同。 |
| `tests/web/test_xxm_shared_loads.py` | 保留并核普通/debug及识别/预测共用读取不串模式，不借清退删除并发/取消测试。 |
| `wealth/src/features/index-detail/xxm-forecast/identity.test.tsx` | 新r4身份/旧r2拒绝；不再把r2报告目录读成current()。 |
| `wealth/src/features/index-detail/xxm-forecast/forecast.test.tsx` | 原第132附近报告JSON消费者改独立r4当前合同，不能仅换version/hash。 |
| `wealth/src/features/index-detail/xxm-forecast/r1Contract.test.tsx` | 当前r4路径/等待字段有效测试迁新语义测试；旧r1/r2 JSON只保留拒绝反例。 |
| `wealth/src/features/index-detail/xxm/rearmContract.test.tsx` | 当前r4等待/悬挂引用验证用独立字面fixture；旧报告不伪装当前。 |
| `wealth/src/features/index-detail/xxm/useIndexXxmLayer.test.tsx` | 当前身份迁r4，补本地普通/debug与生产无请求；不再expect r2。 |
| `wealth/src/features/index-detail/xxm/xxmFixtures.test-support.ts` | 独立明确构造普通/debug不同投影，输入/expected不依赖待测adapter生成。 |
| `wealth/src/features/index-detail/xxm/types.ts` | 唯一r4识别身份，配套adapter拒绝旧身份，无r2选项。 |
| `wealth/src/features/index-detail/xxm-forecast/types.ts` | 唯一r4预测身份；识别器身份/hash与正式r4一致，无r2回退。 |

`tests/test_index_detail_daily_wave*.py`、`tests/web/test_wealth_index_detail_daily_wave_api.py`、`tests/test_index_detail_daily_wave_connection.py`及前端daily-wave测试全部保留；只按本地/生产/debug新门禁调整输入和调用，不改变四种三角、极值/色段/价格候选定义、真实1000根限制或原始数据精度。

### 10.6. 独立验收矩阵与删后引用检查

| 断言 | 独立输入与必须抓住的反例 | 落点 |
|---|---|---|
| 两位纯算术保留 | 40.057→40、−8.086→−8.0、41.01→41、40.99→40、41.9与41.4同41、0/±小数/数量级及bool/NaN拒绝；expected字面给定 | 最小化near_first_review与其人工测试；不得构造产品计算器或读源码/数据 |
| 旧依赖已解除 | 在临时目录中只提供已声明原始CSV/JSON/图像，不提供top_reference_priority/top_return_reference/旧r2源码；保留工具可运行。篡改原始数据SHA仍拒绝 | local_extrema_study和纯取窗/量图测试 |
| 无第二套识别 | 页面debug指向真实r4活动参照、离线观察只记实际分支；保留工具不能调用choose_reference/inspect_prefix/advance_bottom/display_events产生新标签或遮事件 | 产品debug tests及静态导入/符号检查 |
| 当根切换与历史 | 人工A/B价与DIF、零日/缺A/等号/晚合格/结构及等待边界，原DULL事件B保持，activeA；旧历史依原参照正常退出 | 唯一正式calculator人工测试，从原r4-v2 R4-18—24迁移 |
| 身份与内存复制 | r2/研究v1/研究v2旧快照不能作为正式r4进度；坏输入拒绝后正常输入仍成功；旧API JSON仅拒绝反例 | 恢复、真实调用方及前后端合同测试 |
| 迁移等价 | §10.4完整业务结果和唯一编号关联映射；原数值、参照、历史和等待差一项都失败 | 迁移验收进程，不保存账本，不调用升级后的旧研究包装 |
| 默认不触发研究 | 本地普通URL和生产任何URL不得加载辅助研究包/请求/三角；本地debug=1且点击波段核对才计算；生产日线也无r4请求/信息 | 页面/API/浏览器真实验收；不能只用mock声称整个环境门禁通过 |
| 删后仍工作 | 删除清单中的旧模块和已知生成缓存后，当前核心/预测/API/debug/峰谷工具的定向测试通过，原市场数据/历史报告字节未改 | 全部迁移完成后再执行，不拿删前成绩充数 |

#### 10.6.1 静态和动态引用清零

1. 使用当前AST列所有活动Python的Import/ImportFrom及明确动态import路径；核`.mjs/.ts/.tsx/.sh`中的模块/命令和生成Notebook字符串。以清单中每个旧模块路径、旧类名、旧CLI模块名检查，不能只搜r2字串。
2. 必须为零的运行引用包括：TwoDigitTurnCalculator、ObservedR2Calculator、BottomDullRescueCalculator、ReferenceGateCalculator、TopCurrentCloseCalculator、PriceBeforeSelectionCalculator、NearFirstCalculator、ReturnReferenceCalculator、旧研究R4Calculator，以及旧replay/candidate动态加载入口。
3. 历史Markdown中的叙述或旧JSON的版本身份不算运行引用，不能为了让rg无结果删除有效事实。测试中的旧version/hash可出现，但必须是“拒绝旧身份”的明确反例；不能仍有旧版本成功路径、实例化或产生旧算法结果。
4. 扫描旧研究MODULE.main/argparse入口、README活动命令、`runpy`/`spec_from_file_location`、Notebook code cells。只删Python源文件但保留可执行Notebook或动态复制源码，不算清退。
5. 对已清退模块精确删除对应__pycache__项，不做整个repo/环境缓存清空；检查无软链接、转发文件、`.py.txt`、兼容别名或r2算法选择。Git历史不动。
6. 删除后从干净新Python进程导入所有现入口，按现pytest发现配置收集目标测试；不skip失败、不把旧测试仅移出testpaths。保留测试/工具在旧文件缺席时必须真实执行到原始材料校验。
7. 根三份架构、研究依赖方向、必要后端/Wealth测试、类型/构建及文档链接检查按本文相关章节统一执行。本章节不另造数据库/外部源验收，也不授权重跑922根。

## 11. 分批编码顺序和上下游交接

本LLD已把方法、字段、限制和清单细化；P1负责把同一合同写回原接口文档、落实独立fixture及核对实施当日文件，不重新讨论已批准规则。每批开始前先核适用AGENTS和本批原方案/LLD，范围变化先同步；各批用户验收后再推进下一批。不自动提交或发布中间混合版本。

| 批次 | 代码级步骤 | 上游必须交付/本批验收/停点 |
|---|---|---|
| P1 合同和独立样例 | 按§5回写三个原合同；登记现所有直接query调用；逐文件复核§10的git状态/消费者；把§3/6/12人工输入和手写预期放入现产品主题tests；确定公开normal/debug fixture | 不删代码；字段、None、错误、Spec新字段已按本文冻结；设计冲突先停；迁移前基准捕获须排在P2改父类前 |
| P2 唯一r4 | 先按§10.4.1建立一次性测试入口并实际捕获旧r4-v2；再原位置迁step、MAIN_SPEC/识别hash和安全检查；迁from-empty/append/calculator_at/clone/识别缓存；迁可选离线记录（查询默认关闭）；独立预期及内存对账 | 仅一个产品类，无r2参数/转发；全部业务记录一致。FORECAST_SPEC/预测schema/HTTP/前端不在本批；核心及内部查询通过不能称整条产品可用。逐步顺序见§11.3 |
| P3 预测及HTTP合同 | P2核心及迁移对账验收后，统一修改FORECAST_SPEC/预测hash、§6预测路径与数学、§5识别/预测内部及公开模型、query bytes/API、两类前端身份/类型/解析/fixture | 预测版本/模型/消费者一次交接；不能单改预测Spec。普通/debug公共字段及ID/文本相同；正常返回无辅助；完整校验不能取消；失败不露旧缓存 |
| P4 环境、页面、保留工具 | §1本地路由；§8本地正式/生产关闭、debug动态模块及decoder；研究工具依§10解除旧算法/SHA依赖 | 本地日线无分钟Lake仍可用，分钟按已有能力；生产API和真实build无入口；三角/1000/原图不退化；用户review页面 |
| P5 清退及最终审计 | P2—P4验收后按§10名单删旧实现/专属suite和对应生成缓存；清活动命令/动态入口/Notebook字符串；原设计/开发文档标历史并指新入口 | 删后新进程导入、核心/预测/HTTP/debug/峰谷工具回归；没有r2执行副本/模式；原始材料和研究事实保留；停止待下一指令 |

P2只验识别核心、内部查询/恢复与独立clone，不调用完整预测build、HTTP或页面宣称集成通过；P3才同步预测Spec、两类公共合同及其前端消费者，P4才交付环境/页面与真实来源验收。不得用“消费者后续同步”或“同一未发布改动”把这些归属留给开发临时决定。P2—P4均不发布中间混合版本，也不新增兼容字段、旧版本回退或临时算法开关。每批完成回写实际改动/测试/未覆盖来源，不能把本文的“计划测试”改写成已经通过。公共接口、配置和主链有实质变化时，按根规则同步CodeGraph并核是否需要更新架构快照；不为普通文件数增加另建图索引。

### 11.1 保留能力的明确落点

§10出现的“迁移有效能力”按下面落点执行，不能临时增加通用框架或保留旧容器转发：

| 旧能力 | 唯一落点/不迁的部分 |
|---|---|
| 研究r4真实选峰/救援/转折观察 | §7唯一step的可选内存记录及history_disappearance_screen.observe_rows；不入SeriesEntry/HTTP，不保留Observed类/第二份判别 |
| 两位算术 | 最小化`near_first_review.decimal_value/quantize_dif`和`test_xxm_near_first_review.py`；完整类/重放不迁 |
| 人工首次、1%、同根切换、历史、等待、取消边界 | 现`test_xxm_calculator.py`及恢复/输入tests；研究wrapper/旧Spec测试不迁 |
| 独立有理数/求价/源精度案例 | 现`top_activation_math.py`、`forecast_expectations.py`及现`test_xxm_key_point_forecast.py`；不得import产品来生成expected |
| 纯数值窗口/来源/日历/截图 | 最小化现`saved_minute_window.py`、`local_extrema_study.py`、`peak_image_measurement.py`、纯事实`reference_window_review.py`；不在这些工具继续输出selected/eligible/标签 |
| 正式来源/路由/显示核验 | 现`daily_window_precheck.py`、`xxm_page_request_audit.py/.mjs`、`xxm_forecast_display_audit.py`，只有唯一r4原路由，无candidate模块参数 |
| 旧compare ID/记录完整性中的有效反例 | `test_xxm_snapshot_validation.py`、当前web合同及debug合同tests的独立字面输入；旧r2/r4配对、原因猜测、完整runner不迁 |
| 旧report复制预测/候选实现 | 不迁实现；仍适用的字面数学反例迁上述现预测tests，原材料/结论保留；无新r4通用框架 |
| 同根双报后隐藏`display_events` | 删除而不迁；r4必须取消前换A，正式events是真实结果，不允许事后抹事件 |
| 一次性迁移前后核验 | §10.4.1四个测试路径（原三文件及§19捕获子进程）；P2先实现协议与人工事实映射、再捕获、再迁核心，P5删除这些一次性文件；长期r4测试不得导入待删工具 |

没有在上述落点和§10名单内的能力不因“也许有用”新增开发。实施时新发现真实调用或多人改动冲突先说明，不能随意扩删。

### 11.2 保留工具的逐函数交接及仅内存要求

以下是§10各行的唯一细化，当前只静态核对，均待后续获准实施。不新增验证框架、算法副本、HTTP接口或结果目录。

#### 11.2.1 旧输入读取器与独立数学

| 现文件/函数 | 固定处理及真实依据 |
|---|---|
| `scripts/research/index_market/xxm/frozen_inputs.py` | 整文件删除。`expected_unit/expected_steps/assert_expected_recognition/forecast_inventory`属于旧账本；`load_frozen_inputs`第35—37行缺DEA时按DIF/柱反算，不能继续构造新r4输入。原CSV、JSON、manifest和作者观察不删、不重写。 |
| `xxm/acceptance.py` | 只留`sha/load_source/collect_readouts`。`load_source`沿原CSV字段读取真实DEA并验证原数据SHA；`collect_readouts`保留27条作者数值事实及图片出处。删`replay/main`、产品计算器/Spec及`load_frozen_inputs`导入、旧baseline/软件对照结果写入和CLI。 |
| `xxm/top_activation_math.py` | `pair/daily_options`和独立Fraction公式保留；`expectations`迁当前验收时只保留1%字面案例，并按下文手算包含合法零柱目标，不能直接复用旧lowerStrict=True。原其他门槛结论只留历史材料。 |
| `xxm/top_activation_real_math.py` | 只留`meet/minus/interval`纯区间数学及必要`pair`依赖。删`entry_domains/proof/main`、旧报告路径/版本常量及来源、日历、保存模块导入。`entry_domains`当前第53行按DIF强弱排序，是旧选择政策，不可换身份后作为r4预期。 |
| `xxm/forecast_expectations.py` | 删除未使用的`expected_unit`导入，解除旧冻结模块依赖。保留`fraction/contains/regions/assert_partition/coefficients`。删除`verify_changed_forecast`及MATH_KEYS：它硬编码dif_turn目标hist>0、无transitions/prefix等旧断言，唯一消费者reference_rescue_acceptance也将删除，不能继续当r4 oracle。 |

旧proof/context中仍有效的独立字面条件迁现`test_xxm_key_point_forecast.py`，不调用已删entry_domains/proof、旧oracle或正式预测器生成expected。B→A、零柱和更多端点路径按§6独立手写预期。保留coefficients仅用于其已有明确正D1前提的算术案例，不把abs分支当负值/跨零域的通用解释器。

`top_activation_math.expectations`原minuteRelations.difTurn的lowerStrict=True也是旧边界，P1须同步纠正。原字面P=100给D1=22/13、初始DEA=-2，第一步DEA1=-82/65；第二步hist=0时D2=DEA1，因此D1-D2=192/65，严格超过1%门槛22/1300。一般在这组已证明D1>0的入口域，D1-D2=4*D1/5+8/5也大于D1/100，所以零目标不能遗漏。仅在该组独立证明hist零点对应C>0的域内，将目标下界包含等号（lowerStrict=False），真实反色color_flip仍严格，不改变实际1%规则。正收盘C>0始终独立保留；其他样本若max下界恰为0，不能把价格0闭入。测试同时核零点、两侧、恰1%和来源精度不确定边界，expected用上述Fraction推导，不从产品输出生成。
`top_activation_real_math`不再需要旧`calendar_rows/future_slots/read_unit/seal/OUT/ROOT/SOURCE`；不为保留这些旧runner依赖再造日历框架。
必要日历端点的预期直接写入当前测试字面输入；真实产品仍使用自己的正式日历模块。

删除`frozen_inputs.py`前清零的当前消费者为：

- `acceptance.main`、待删`top_activation_expectations`及`reference_rescue_acceptance`中的旧运行分支。
- `daily_window_precheck.validate_capture_identity`里的旧`expected_unit`身份补全。
- `forecast_expectations`顶层未使用导入。
- `test_xxm_calculator`旧冻结账本组、`test_xxm_top_activation_r2`及旧acceptance专属mock。

现`test_xxm_confirmed_cases.py`不导入该冻结模块，不得为了清退它而删除作者观察测试。
旧JSON可供拒绝旧身份的反例；不得换hash后作为新r4结果。删除后用新进程收集、执行保留测试，不能靠移动测试目录隐藏引用。

#### 11.2.2 纯峰谷、取窗和Notebook

| 现文件/函数 | 固定处理 |
|---|---|
| `xxm/saved_minute_window.py` | 保留`_timestamp/_parse_row/read_window`及原常量。它只读取已有、有SHA且受行数/字节/定位上限约束的90分钟原CSV；不计算标签、不落盘，无旧算法依赖。 |
| `xxm/local_extrema_study.py` | 保留`SavedCase/CASES/sha/validate_rows/read_case/series_turns/summarize_case/literal_anchor_checks/benchmark`。它们仍属于独立峰谷核验，不能把其统计当r4识别政策。 |
| 同文件`protected_files/assert_protected` | 仅验证已声明CASES和原图SHA；删除继承`PREVIOUS/run.json`、旧算法源码及源码SHA的要求。原始材料修改仍须拒绝。 |
| 同文件`save_new/main` | 删除旧结果writer和旧`--output`runner，不再写run、行情窗口、峰谷结果、benchmark或新的恢复文件。 |
| 同文件`notebook` | 改为返回未执行Notebook字典的纯组装函数，不`exec`代码单元、不调用`save_new`、不生成文件。代码单元调用原扫描器及`read_case/summarize_case`，不复制实现；已有`review.ipynb`和既存结果不改。 |
| `xxm/reference_window_review.py` | 只保留`sign/build_references`的原始色段、DIF转折、日期/价格窗口事实；删除`qdif`字段及`quantize_dif`导入，避免继续输出旧两位资格。 |
| 同文件其余 | 删除`ReviewSpec/SPEC/LIMITATION/inspect_prefix/review_locked_reference/run/main`、旧两位选峰/突破/转折、条件重放、输出目录及源码hash；输入由现`read_window`提供。 |
| `xxm/peak_image_measurement.py` | 保留原量图函数、必要类型及人工尺寸/颜色测试；无旧算法或结果落盘依赖，不安装新的图像套件。 |

`test_xxm_local_extrema_study.py`保留原输入身份、独立数学、图像及性能测试；旧“拒覆盖新结果目录”用例改为验证没有结果写入、原始材料不变。
Notebook组装测试检查返回字典、未执行的代码单元和当前导入，不运行真实窗口来证明格式正确。
`test_xxm_reference_window_review.py`仅核原始日期/平台/数值，不再断言`eligible/selected`或两位生命周期。

#### 11.2.3 日线窗口核验不再借旧acceptance运行器

`xxm/daily_window_precheck.py`仅保留`validate_window/read_window/isolated_client`，删除`capture/replay_checks/validate_capture_identity/check/main`及旧源捕获CLI。
同时删除`bottom_history_acceptance as b`、`MATH_KEYS/semantic/expected_unit`、旧R1/R2响应比较、全部`b.save`及结果目录逻辑。
`read_window`只返回现有上证字段和SSE日历，保留原START/数量约束、字段/交易日检查；不把它变成新的下载器或正式来源。
它读取真实源时仍须单独限定标的/范围/原字段，不能因保留函数就自动运行2020年以来全部明细。

`isolated_client(bars, calendar, now)`继续是人工/已明确输入的隔离合同测试，不冒充正式PostgreSQL性能或原鉴权验收：

1. 原SQLite内存表、真实字段、只读开关、冻结时钟和缓存隔离保持；不写正式数据库。
2. 在原文件内建立最小`FastAPI`，安装现异常处理，调用正式本地r4路由装配函数；不再调用待删`b.app_for`。装配和分钟能力统一用传入的同一Settings，不重新从全局env猜一次。
3. 用显式本地Settings建立测试装配；依赖替换仅限该临时App的会话及原用例明确声明的鉴权替身，不改全局配置/环境。
4. 原`get_db_session`替换为内存会话；测试自身声明替代了存储/鉴权，真实r4读取转换、计算、DTO和投影仍实际执行。
5. `finally`恢复时钟/查询包装及原缓存并释放SQLite；新的普通/debug响应按bytes及目标DTO解析，不再按旧对象取字段。

`test_xxm_daily_window_precheck.py`保留窗口/缺交易日/字段测试及上述隔离客户端合同，删除旧capture身份、frozenOverlap、报告writer及旧响应比较测试。
真实源和原鉴权的路由核验由下节现有工具承担，不能把本SQLite通过结果当真实接入或性能通过。

#### 11.2.4 三个原路由核验入口改为仅内存

`scripts/research/index_market/xxm_page_request_audit.py`目前已自带只读会话、原鉴权、隔离App、临时server和清理，且不导入待删研究模块；可在原文件迁移，不另建框架。
将现App构造部分提为`isolated_app(settings)`上下文管理器供本脚本及`xxm_forecast_display_audit.py`复用：

- 使用原`get_db_session`与`SET TRANSACTION READ ONLY`，原`require_quote_access`、异常处理及正式本地路由装配；不能直接include r4路由绕过环境判断。
- 普通日线/分钟/九转仍用原路由和原reader；仅当前隔离进程注入受批准来源，`lifespan='off'`，不启动后台任务。
- 保留原私有`/__audit__/context/reset/metrics`用途，不新增HTTP路径；正常/debug按同一正式合同请求。
- 最终恢复修改过的reader/service/calendar/build包装及原缓存；请求失败、Node失败和中断均关闭临时server/socket/会话。
- 两个Python入口移除`--output`、创建目录及完整HTTP/行情/视图写入，正文只在RAM核对；终端仅输出数量、字节、日期、时限、状态及验收摘要。

`xxm_forecast_display_audit.py`在原文件删除`--candidate`、动态源码加载/源码SHA、候选display/recover包装及旧候选身份；不保留算法选择。
其`request`继续验证HTTP状态、真实目标DTO、字节与时限，区分normal/debug；删除旧固定锚日/固定全四周期全组执行，按P1声明的有限周期和asOf核验。
20次性能采样、冷热及并发检查仍遵守原预算；只运行本轮已明确授权的范围，不由一次入口默认展开所有历史窗口。

两个Python入口的执行参数在本轮固定为：`--periods`必须显式给出day/m60/m90/m120的非空去重子集；`--as-of`可省略表示latest，非空仅接受YYYY-MM-DD，日线用该日，分钟映射该日15:00:00+08:00且必须已完成；`--mode`为normal/debug/both，默认normal；`--samples`为1或20，默认1，20仅在获准性能验收时显式使用。--candidate/--output均不再接受；README和所有调用同次迁移，不留忽略参数的兼容壳。mjs由父进程传base及相同周期/模式/时点，不接output位置参数，也不偷偷补默认全周期。

单周期/单模式采样为一个≤60秒的有界组，超时即停止报告，finally含关闭server/socket和恢复patch，不在后台继续下一组。latest记录实际完成截止，不把所有分钟末根强断为当日15点；显式asOf非法仍按原API错误处理。原鉴权、真实源和原请求预算均不放宽。

`xxm_page_request_audit.mjs`固定要求：

1. 删除`output`参数、`writeFile/resolve/persist`及所有完整response/VM保存；requests/rounds只在内存，错误body不写文件。
2. 继续现Node/esbuild、`bundle:true/write:false`及内存data-URL模块，不安装依赖；显式采用本地开发客户端所需的编译环境；只导入pure decoder/客户端，不把React图层及CSS带进Node执行。该工具不替代真实production build。
3. 编译入口导入现`INDEX_DAILY_HISTORY_LIMIT`供日线K线/九转使用，不再硬编码300；分钟500不变。
4. 普通请求不得期待根层`rearmContext/bottomHistories/pendingRearmId`；debug才动态导入已规定的辅助decoder，并按`debug`容器验证关联。
5. 两种模式公共字段/标签ID/显示文本在同一固定输入下相等；来源变更/日期切换时按原规则终止本次比较，不硬配。
6. 指定周期不可用时如实报告；不得丢掉失败周期后说四周期通过。该Node客户端工具不是实际浏览器或生产构建验收。

#### 11.2.5 测试、身份和真实来源停点

P1只准备独立字面业务输入/预期及字段形状，不先修改`MAIN_SPEC`或父计算器来生成新hash；真正迁移前捕获仍在P2改这些文件前完成。
P1 fixture构造函数将detector/forecast hash作为无默认值的显式参数，业务预期仍为字面数据；不能取当前r2 hash作r4真值。文档样例的说明占位不进入实际HTTP。
P2实现MAIN_SPEC后只生成正式detector hash，用于核心/恢复、内部SeriesEntry/query、clone及其人工测试。P1识别材料可由调用方显式传该真hash用于内部字段核对，但普通/debug公开响应尚不交旧模型验收。现识别完整XxmResponseDto的版本/hash动态校验MAIN_SPEC、没有r2 Literal，P2可继续用它核完整内部结果；这是沿现内部模型，不是提前实现P3公开投影。
P3实现FORECAST_SPEC并生成forecast hash后，才把两项正式hash填入公开识别/预测合同fixture、两个前端types身份常量、decoder和拒绝旧/混配身份测试，同步预测Python模型及query/API。forecast响应工厂需要两项hash的用例不能在P2塞r2预测hash或人工占位凑通过。P1可校对字段和手算结果，不拿未迁移r2模型验目标公开响应，不靠skip/xfail伪装该路径通过；业务预期仍手写，不随实际标签重生成。
清退后测试收集须覆盖新数学、纯窗口、离线观察、普通/debug HTTP、工具RAM及异常清理；静态检查不能替代真实入口执行。
针对工具补负例：缺旧模块仍可import；禁止旧动态candidate加载；不创建结果目录或写完整body；启动/请求/Node失败后清理及包装恢复。
真实分钟不可用时保留该周期“未验收”并说明原因；不得把日线或人工替身抵充。P4按已声明四周期完成条件判断，缺必要真实证据不能宣称整批通过或据此进入P5。
若管理员后续批准暂缓某周期，先同步产品/方案/LLD的验收范围再继续；本轮不默认得到这种批准，也不重问已确认算法。
上述均为工程细化，无新增算法、产品开关或需要重新拍板的规则；先补进原方案/LLD，再编码。

### 11.3 P2六步的前置条件与交付

以下保留§11中P2首次实施的六步依赖顺序，不增加批次；第6步原中断见§18，后续已批准修复/重新捕获及验收见§19。

| 步骤 | 开始前必须具备 | 本步改动及结束证据 |
|---|---|---|
| 1 测试入口与旧结果 | P1材料已验；旧父类、MAIN_SPEC及研究r4-v2尚未改变；工作区无目标文件冲突 | 只实现§10.4.1三个测试文件和独立事实映射，限定协议测试通过后实际捕获。收到148例CAPTURE_READY才准进入第2步；未收到则停在旧实现仍完整的状态 |
| 2 迁识别核心和Spec | 同一父进程仍持有效完整旧结果 | 按§2—3在原位置迁唯一XxmCalculator、Wave/types及MAIN_SPEC，生成detector hash；不动FORECAST_SPEC。不复制旧父类/不留算法选择；核心字面断言覆盖选峰、零柱、同根切换及1%分支 |
| 3 输入及恢复安全 | 新核心的业务字段/身份已固定 | 迁共享解析和r4状态关系检查，错快照先拒不污染，合法更早恢复可继续；研究包装的parentState不交新计算器恢复 |
| 4 构造与内部缓存 | 新输入/restore已通过定向正反例 | 同步from-empty、append、SeriesEntry.calculator_at、forecast_detector.clone及识别缓存身份；用人工输入验连续/分批/历史/clone一致。完整预测求解和预测返回尚未验，不改预测缓存策略或HTTP合同 |
| 5 离线记录 | 第4步各路径均使用唯一正式类 | 按§7实现可选record_decisions及实际分支记录，默认关闭、不入SeriesEntry/snapshot/HTTP；记录开关不改变结果或编号。保留待清退研究文件但不把它当新基准再运行 |
| 6 独立验收和停点 | 前五步定向测试通过；最初父进程仍持捕获结果 | 触发compare，全新worker从空计算、独立字面及完整业务记录对账均通过，补必要架构/依赖/文档检查并独立审计；汇报实际覆盖与P3未做项后停止。对账失效按§10.4失败处理，不能拿单测成绩替代 |

P3开始前须取得P2第6步的真实通过记录；P3首步同时列出FORECAST_SPEC、预测Literal/双hash校验、预测数学、识别/预测公共模型、query返回bytes、API及两个前端身份/decoder/fixture的完整改动清单。它们完成前不运行旧公共消费者来声称r4整体通过，也不因为旧Literal报错而回改算法。P4真实路由/来源/页面及预算证据不足时，仍不得进入P5清退。


## 12. 测试、真实验收和完成标准

### 12.1 独立预期与必要反例

§3/6/8/10的测试表是本节的一部分。新增预期使用已确认规则/独立手算字面值，不能由被测step、预测器或adapter生成。旧r2报告只可当明确拒绝的旧身份反例或历史事实；不能换version/hash后当r4金样本。

| 组别/代码位置 | 必须证明的结果（含正常变化不误拦） |
|---|---|
| 核心`test_xxm_calculator.py` | 顶/底B合格先B、B失败才A、第三个更强不查；相等/不足两根拒绝；前段零、真反色、零首次/重激活；同根B→A无新增标签且原事件B不改；A晚一根资格保留消失后新DULL |
| 核心历史和相邻1% | 实际相邻恰1%/不足/前值0；前根零柱不跳过；首次根只DULL、翻色独立、突破优先；自然顶回转结束旧历史；底部当根close和等待原参照；所有asOf历史不带未来 |
| 输入/恢复/consumer | 四周期合法更早前缀恢复后正常继续；旧身份/NaN/bool/缺参照/错ID/未来日期/逆序/未完成拒绝且来件/self未变；零日合法等待不误拒；两个实例无可变共享 |
| §7真实记录 | 每次选择/救援/转折只调用原业务分支一次；B未过时A明确未检查；有活动参照不编造首次选择；同根before B/after A但初始DULL事件B；trace开关不改变业务字段或增加事件 |
| query/cache/asOf | 新建/增量/历史calculator_at和clone均正式r4；count=0/999/1000/1001与offset=0无checkpoint的恢复/重放；空源及合法asOf早于首根返回EMPTY、非法asOf仍400，不取[-1]；源修订重建/纯追加；并发普通debug同计算且响应不串；完整内部先校验、bytes只编码一次、预算后无二次编码；源全前段和显示窗口区分 |
| 预测数学/源精度 | §6每个切点、开闭单点、TOP/BOTTOM、零平台/恰零、等待count/currentP；初始B/当根换A路径、整域证明、所有source_options逐根step相符；不同路径不能合并用中点代表；无解/精度不确定保留真实原因 |
| HTTP/模型 | 独立普通/debug及各状态字面样例；400/404/500/503、波段422/503；普通无辅助字段、debug必须对象、None不省；旧hash/混合版本/重复或悬挂ID拒绝；正常和debug同公共字段/forecastId/文本 |
| 环境装配 | 显式dev/local、缺失/空/未知/prod以及env文件优先级；本地日线不绑分钟Lake；生产debug=1直接访问不调用source/计算且OpenAPI无路径；原日线K线仍正常 |
| 前端合同/状态/懒加载 | 采用§8完整测试位置；DEV=false无r4 DOM/placeholder/请求/定时器/primitive；默认不import辅助；URL debug开启但模块loading/error仍正常发模式0，ready后才模式1；两种根字段集合分别合法、普通夹带debug/模式1缺debug拒绝；辅助合同错误不能默默降级；退出/重试/日期变化和迟到不复活 |
| 保留研究/共享绘图 | 原独立峰谷/平台/候选/四种三角/说明/44px不改；无起点也能看说明；1000三条链、股票300/分钟500；原300重叠指标与同日期标记保持；日期隔离及缩放/拖动/四窗同步 |
| 删后回归 | 无旧代码/缓存仍可导入当前core/query/API/前端及最小研究工具；保留原始文件改坏仍拒绝，缺旧算法文件不阻塞；AST、动态import、CLI、Notebook均不留旧执行路径 |

必要新增测试固定落点：`tests/web/test_wealth_xxm_local_routes.py`（纯路由装配及无源调用反例）；`scripts/research/index_market/tests/test_xxm_response_projection.py`（内部/公开投影和编码预算）；其余复用上表已有主题文件和§8明确的新前端tests。测试helper只服务本模块，不新增运行时代码依赖测试或研究目录。

### 12.2 有界真实核验（实施阶段，当前未执行）

- 使用已有隔离本地App办法、原路由和原鉴权、只读来源；不重启共享服务，不通过mock声称真实接入通过。
- 先选择单上证有限日期/已有可用分钟的各周期，记录真实源字段/时区、读取范围、实际根数、响应字节、冷/热/历史/增量耗时及source ID，不补缺值或计算实际MACD。若正式服务需要更长历史，事先注明有界上限和来源，不把报告区间当计算起点。
- 一次性迁移对账用§10独立人工输入和真正迁移前捕获；来源真实核验另用唯一r4和已知规则检查，不在删r2后重建双组产品。
- 本地普通/debug对同固定前缀公共结果一致；分钟不可用时单列未验收，不能拿日线922根或人工替身抵充。
- 真实生产构建仅在本机preview验证，无r4 DOM/请求/辅助chunk预载；后端以生产设置构建隔离路由验无源调用。本项不部署到生产。
- 浏览器1600/1440/1280宽、45/180根、拖至301根以后，记录普通/debug的请求、控制台及图层/图表创建次数；退出研究恢复普通日期，标签/条件与真实API一致。页面最终交用户review。
- 每个测试组超过60秒停止查因；性能不满足200ms/4秒/8秒/10秒或字节限额时报告实际输入、路径数和耗时，先补方案，不放宽上限或退r2。

### 12.3 命令和交付对账

使用现有环境，不安装。实施时先确认测试路径存在，再分组执行：

- `.venv/bin/python -m pytest`选本模块人工/恢复/预测/投影及web路径；不得整组触发旧冻结数据回放或未授权真实读取。
- 根三份架构：`tests/architecture/test_subsystem_dependency_matrix.py`、`test_platform_legacy_guardrails.py`、`test_operations_legacy_guardrails.py`，另核Biz不导入research/App/QTF。
- Wealth定向/全量`npm --prefix wealth run test`、`typecheck`、`build`；真实preview单独登记。每组有界，不用skip/吞错过关。
- `python3 scripts/check_docs_integrity.py`和本组相对链接/标题/字段覆盖检查；它们只能证明文档完整性，不能证明新算法或接口已经通过。

每批交付按R01—R22逐条记录“代码点/测试/真实证据/未覆盖”，不是只报测试数量。最终完成还须P5删后验证、全部消费者同合同、用户页面review；未完成来源或性能不得宣称整体产品已验收。

## 13. 内嵌编码门禁

以下逐项映射[模块交付通用清单](../../system/module-delivery-checklist-v1.md)的18条。适用范围为已接真实API的指数详情，不恢复市场总览mock/real切换，也不借此修改策略配置中心或其他页面。

| 通用清单 | 本模块适用性及明确要求 | 代码/验收 |
|---|---|---|
| 2.1 交付事实链 | 适用；产品/技术v1→本文→原API合同→实现→测试/页面review；现页面/用户四种画法为视觉事实 | §0、5、8、11—12；不重做Figma、不用历史图覆盖当前界面 |
| 2.2 后端事实归一 | 适用；源原MACD、唯一r4、内部完整后投影 | §2—7；前端不自行选峰/算结构 |
| 2.3 状态机 | 适用；NONE/DULL/STRUCTURE、历史/WAITING及研究closed等分清 | §3、5、8；加载/EMPTY/DELAYED/错误反例 |
| 2.4 显示与数据语义 | 适用；正常正式信息、debug原依据、生产无功能 | §5、8；普通故障可见、原值不格式化比较 |
| 2.5 过程测试 | 适用；重试/取消/迟到/切周期/卸载/进度恢复 | §4、8、12；不能只快照DOM |
| 2.6 文档同轮 | 适用；原方案/LLD/合同/索引和实际状态同步 | P1/P5及交付对账；历史成绩不改写 |
| 2.7 渐进替换 | 适用；P1—P5依赖顺序；不发布混合识别/预测版本 | §11；最终无双轨/兼容r2 |
| 2.8 契约消费者 | 适用；query字节、公开模型、API、TS、decoder、fixture全迁 | §4—5、8、10；旧JSON仅反例 |
| 2.9 图坐标/文案 | 适用；事件原日期，三角仅原认可画法/避让 | §8；范围外/空间不足不捏造点 |
| 2.10 统计/传输 | 适用；后端完整算，普通不传debug；响应上限 | §4—5、9；不裁断关联凑限额 |
| 2.11 策略中心 | 不适用新增策略配置；本功能不消费/修改策略中心 | 既有env/Spec审计§1—2，无数据库配置或用户算法开关 |
| 2.12 映射矩阵 | 适用，本表覆盖18项，每项注明实施/测试 | P1复核，交付逐项对账 |
| 2.13 例外白名单 | 无新增例外；生产暂不开放是产品范围，不用mock或r2兜底 | 本节白名单表；开发真实/生产无请求反例 |
| 2.14 参数优先级 | 适用；图配置不改真实日期/标签/方向；研究44px只影响画法 | §8；共享默认、1000及缩放回归 |
| 2.15 双图对齐/避让 | 本轮无新增并排图；现四窗坐标/九转及三角避让适用 | §8既有尺寸和占位；301根后/宽度/高度回归 |
| 2.16 卡片文案 | 适用；正常预测沿现display和单行/长度约束；复杂公式仅debug | §5—6、8；中文有限容器/溢出不改语义，无新卡片 |
| 2.17 真实API+显示 | 适用；独立合同样例+真实最小来源链+真实build/页面 | §12.2；当前文档检查不替代 |
| 2.18 八原则 | 适用，见下一表 | 全链审计，不能只填“通过” |

| 八原则 | 明确落点/反例 |
|---|---|
| 事实源单一 | 源原值、唯一r4、debug取实际输出，离线过程只记真实分支，禁止产品import研究及新MACD补算 |
| 契约先行冻结 | §5字段/None/类型/错误/单次编码；P1回原合同再编码全消费者 |
| 配置一致 | §1最终Settings与显式来源、前端DEV、固定Spec、1000和原预算唯一来源 |
| 默认行为显式 | 普通正式/无辅助、debug手动研究、生产全部r4禁用、不回r2 |
| 排序筛选确定 | 仅B/A时间序、严格比较/相等、固定窗口和历史投影，禁止最强排序 |
| 预算前置 | §9含缓存命中/恢复/精度分支/序列化/失败重做/最终验收 |
| 异常标准化 | 原注册错误/状态、真实错普通可见、取消释放、不把错误当空 |
| 用户结果中心 | 标签/文本/依据同源、三角/1000/原图、真实浏览器和用户review |

例外白名单：**无新增条目**。本模块没有为绕过通用门禁引入mock、公开配置、独立聚合接口、特殊展示算法或持久化。通用清单仅限homepage的mock切换不适用于这个已经真实接入的指数页，属于适用范围说明，不是假设获准的例外。

编码前确认项：本LLD/原方案一致、P1原API合同回写/独立样例及实施当日引用清单完成、明确该批执行授权；其后按每批验收。LLD写完不等于已经授权删除或整体开发。

## 14. 文档独立审计与当前事实

### 14.1 首次独立审计

全文完成后，由后端、前端和清退三个独立复核方向对照已确认方案及当前源码交叉检查；修改后只对发现项做窄复核，没有重复运行相同业务审计。以下问题已在本文及受影响技术方案中修正：

| 原问题 | 最终要求/复核位置 |
|---|---|
| 环境缺失时默认dev可能误开启 | §1要求最终Settings显式提供dev/local，不改全局默认或来源优先级 |
| 伪步骤可能先CANCEL后又在同根首次激活 | §3第7—10步明确一个互斥if/elif/elif；已有STRUCTURE取消不套用DULL救援 |
| indicatorVersion/message类型和空值写错 | §5按当前生产者恢复int或None、string或None；日线样例为null，不改合法None为空串 |
| B/A两个候选误解成最多两条检查 | §7离线事实允许门槛B+B资格+A资格共3条，仅不同候选最多2 |
| HTTP里新增每根完整过程与1MiB冲突 | 纯字面紧凑JSON估算，1000条新增过程本身即超过1MiB；按原方案撤回这项额外响应，§7仅保留手动离线记录，§5/技术方案回原公开字段，不放宽预算或裁断关联 |
| 研究趋势与MA/BOLL切换无人交接 | §8.3/8.6分开wave/trend primitive，由原工作区overlay选择 |
| decoder/分钟详情/预测详情传参未定 | §8.3.4冻结模块导出、check及props；分钟直接用延迟模块renderer，不依赖日线波段控制器 |
| 网络计时结束后解码仍可迟到显示 | §8.3.5从scheduler实际发送起共用同一个deadline，覆盖JSON/两层解码/图表适配/提交；合法缓存命中另计本次处理时限 |
| 旧历史核对中仍有另一套寿命逻辑 | §10.2函数级删除local_followup及旧runner，只留纯事实/事件检查；保留原材料，不换r4身份让旧政策继续运行 |
| 普通查询错误与缺reader现503混写 | §9分列一般500和当前缺分钟reader显式503，P1同步原合同备注，保持现入口行为 |

独立窄复核确认：方案与LLD未发现仍需管理员重新拍板的规则/范围问题，前后交接可用于P1准备；完整过程没有残留进入HTTP/缓存的要求，分钟debug与日线波段范围明确，旧寿命函数不再作为当前核验政策。

首次实际检查：仓库文档完整性检查通过；本组三文档相对链接、空白、代码围栏、R01—R22和通用清单2.1—2.18覆盖检查通过。另做过纯配置对象和纯字面JSON容量核查，均无行情/数据库读取。它们只证明文稿和上述边界，不证明未开发产品已经通过。

### 14.2 再次核对与当前结论（2026-10-28）

本次对照产品要求、技术方案及当前源码，按计算/恢复、接口/页面、工具清退分别独立复核；修正后只复核发现项。下列缺口已补入对应正文，技术方案同步受影响交接，产品规则不变：

| 原问题及可能影响 | 已明确的处理 |
|---|---|
| 空前缀可能误取最后一根；不足1000根时可能读取不存在的checkpoint[0] | §4.2分别处理count=0及offset=0；合法空前缀返回原EMPTY语义，非法asOf仍拒绝。识别空源身份与预测空值不混写；§12补0/999/1000/1001及日期反例 |
| 等待记录“结束只看换色”的缩写可能漏掉重新激活和参照突破 | §2.1保留color_flip、price_requalified、reference_dif_break三种结束原因；只对“本段已结束”使用color_flip，不改研究r4处理 |
| debug工具加载失败可能连普通识别/预测也停掉 | §8.3—8.5按实际模块就绪状态决定请求0或1；加载或失败时仍提供普通结果。模块就绪再请求辅助投影，迟到响应不能串用 |
| debug响应带额外根字段，若先通过普通封闭模型会被误拒 | §8.3.4先验证本次模式的根字段集合，再复制普通字段验证，最后验证辅助关联；真实合同错误整份失败，不降级掩盖错误 |
| 新本地装配与旧注册位置并存，可能重复注册或让日线依赖分钟Lake | §1.1四条r4/核对路由只从一个本地装配方法注册，旧重复位置清除；使用同一传入Settings决定环境及分钟reader。普通分钟路由不顺带迁移 |
| 拟保留工具仍含DIF最强选峰、缺DEA反算、另一套预测预期或结果写盘 | §10—11.2落实到文件/函数及消费者：清退这些旧判别和writer，原始材料保留；只留独立算术、原值读取及调用唯一正式r4的核验工具，不新增替代算法 |
| 独立数学样本也沿旧边界排除合法零柱目标 | §11.2.1登记Fraction手算及正收盘范围：该字面1%样本纳入合法零目标，价格0和真实反色等号仍排除；不能只改版本/hash沿用旧预期 |
| P1预期身份与后续hash交接、缺分钟证据时的停点不够具体 | 当时补显式无默认身份参数，但把两种hash都安排P2仍有顺序遗漏；本次§17已纠正为P2仅detector、P3 forecast及全部公开消费者。业务字面预期不重生成；缺必要分钟实证时P4未验收，不自动进入P5 |

上述问题属于把已确认要求写准确、落实到当前代码的工程交接，不新增算法规则或产品范围。本次未发现仍需管理员讨论、会阻碍P1的口径；§10—11.2的工具调整属于后续开发要求，当前源码并未被修改或删除。

**开工前审计结论：方案与LLD一致，具备按§11启动P1的条件。**P1须先回写原API合同、准备独立人工预期并复核实施当日引用和脏文件；这是已排定的第一批任务，不要求再讨论既定规则，也不允许越过它直接迁入或删除。实际算法迁入、求价区间、性能、四周期真实来源、API/浏览器和删后验收仍须后续逐批完成，本文不预判通过。此后P1的实际状态见§16，不以本段开工前状态覆盖后续交付。

本次仅做CodeGraph/当前源码核对、文稿修正及文档检查，没有运行识别重放、业务测试、行情/数据库读取或浏览器验收，没有提交、部署或删除代码。仓库文档完整性、本组三文档的相对链接/空白/围栏、R01—R22及通用清单2.1—2.18覆盖检查均通过；这些检查不能代替上述产品验收。

## 15. 依据、库说明及版本记录

- 权威规则：[产品v1](../../../../docs/product/wealth-top-bottom-recognition-product-v1.md)、[技术v1](index-detail-top-bottom-recognition-technical-design-v1.md)、[研究r4-v2](index-detail-xxm-r4-low-level-design-v0.1.md)。此前研究成绩仍只作研究依据。
- 当前代码依据：技术方案§1.1及本文逐文件/方法；CodeGraph覆盖入口/调用/消费者后以当前源码补核。实现后仅实质主链变化按根规则更新架构快照，不在本次另建架构项目。
- 本轮通过Context7查Pydantic/Pydantic Settings官方资料，确认`model_fields_set`标显式字段、`exclude_none`会删除全部None、构造参数来源优先于默认。参见[模型源码说明](https://github.com/pydantic/pydantic/blob/main/pydantic/main.py)、[序列化说明](https://docs.pydantic.dev/latest/concepts/serialization/)、[Settings来源说明](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)。项目实际env文件优先顺序仍由`get_settings()`现源码决定；不因官方默认不同擅改本仓行为。

| 日期 | 状态/变化 |
|---|---|
| 2026-10-28 | 首版代码级LLD；细化唯一r4、环境、预测、完整合同、debug交接、清退及验收；仅文档，未实施。独立审计见§14。 |
| 2026-10-28 | 再审计补齐空前缀、debug加载/解码、唯一环境装配、保留工具函数边界及P1/P2身份交接；发现项独立复核后关闭。可按序启动P1，尚未编码或实际验收，见§14.2。 |
| 2026-10-28 | 按批准范围完成P1三原合同回写、文件/调用/迁移清单和独立人工材料；限定材料162项、三架构16项通过。核心/Spec/运行接口未改，P2未启动，见§16。 |
| 2026-10-28 | P1后开工审计纠正迁移入口遗漏及预测Spec/模型分批矛盾；§10.4.1、§11.2.5、§11.3明确实际捕获先于改旧依赖、P2识别与P3预测/公开消费者的交接。仅文档，P2未执行，见§17。 |

## 16. P1执行与验收记录

### 16.1 本次范围及实施约束

管理员已批准按既定方案完成P1，结束后独立审计并停止，不进入P2。目标是落实§11的五项准备：当前文件/调用清单、三个原合同、函数级迁移去向、独立业务样例、普通/debug响应样例。产品规则仍以§2—6为准，本节不增加新规则。

- 原合同仅修改`index-detail-api-contract-v1.md`、`index-detail-minutes-api-contract-v1.md`及`index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md`相应识别/预测章节；明确现行r2与待实施r4目标，不能把目标写成运行时已生效。
- 独立测试材料放在现`scripts/research/index_market/tests/`：`xxm_product_v1_cases.py`、`test_xxm_product_v1_cases.py`负责手写核心/数学案例；`xxm_product_v1_responses.py`、`test_xxm_product_v1_responses.py`负责普通/debug响应及关联样例。它们只服务本模块，无产品对测试/研究的反向导入。
- 业务预期均依据本文人工推导，不调用研究/产品计算器、预测器或adapter生成expected。P1只验材料字段、关联和独立算术，不运行目标r4算法或将目标响应交当前r2 schema验证；不能以skip/xfail伪装P2/P3通过。
- 响应工厂的detector/forecast身份hash为调用方必须显式给出的参数，无默认值，不import现r2 Spec。测试中的人工身份只验参数交接，不登记为正式身份。后续时点按修正后的§11.2.5：P2生成detector hash用于内部验收；P3生成forecast hash并同步公开fixture/前端，业务预期不重算。
- 文件和直接query消费者清单写回本节，沿§10—11.2确定保留/迁移/删除，不在P1删除任何实现、修改预测/页面/配置。当前已有脏文件不覆盖；新发现会改变既定规则或真实冲突时停止说明。
- 不读取行情、数据库、Lake或外部接口，不捕获迁移前研究结果；该捕获严格留P2修改父类及Spec之前。无结果落盘/恢复；仅维护文档及手写测试源文件。
- 验收使用现有环境；单组测试60秒内有界执行，失败先说明原因，不安装依赖或放宽规则。只执行本批材料测试、必要静态/架构及文档检查，不运行旧冻结行情回放。进程中断后重跑本批检查即可，最后独立审计也在同一范围内。
- 完成时逐项记录改动、测试和未覆盖；不自动提交或推进P2。P1通过只证明准备材料完备，不证明r4产品、预测或真实接口已经验收。

### 16.2 当前文件和调用清单

2026-10-28在`dev-interface`以CodeGraph及当前Python导入/引用静态核对；未执行这些入口。下表登记实际调用，不使用运行时源码SHA保护。P3把直接build返回从DTO迁为bytes并同步解析；P4接正式本地装配；P5仅删除已登记旧运行器，不能把该表误当P1删除许可。

#### 16.2.1 query直接调用及包装

路径均相对仓库根；括号为本次源码行号，仅辅助定位。

| 当前文件/调用 | 后续处理 |
|---|---|
| `src/biz/api/wealth/market/index_detail_xxm.py`（62） | P3日线build增加debug；发送同一已校验bytes，不二次编码 |
| `src/biz/api/wealth/market/index_detail_minute_xxm.py`（25） | P3同合同，保留分钟来源/权限；P4按本地能力装配 |
| `src/biz/api/wealth/market/index_detail_xxm_forecast.py`（47） | P3预测build的debug和bytes，P4同Settings传入reader |
| `src/biz/queries/wealth/market/index_detail_xxm/forecast_query_service.py`（85） | 内部持识别query、使用load_entry而非另跑一份算法；P2仅随共享识别query取得新核心，本文件/预测身份及完整结果迁移属P3 |
| `tests/web/test_wealth_index_detail_xxm_api.py`（106、128、149、211、274、306、377等） | P3直接build和_response断言改按目标合同；保留来源、恢复、历史及失败反例，不只替换hash |
| `tests/web/test_wealth_index_detail_xxm_forecast_api.py`（104、387、498、520、567、621等） | P3直接build结果解析bytes；旧r2/A1/R1响应只留明确拒绝反例，P4环境验收 |
| `scripts/research/index_market/tests/test_xxm_snapshot_consumers.py`（40） | P2保留真实query/恢复调用，改唯一r4身份；P3受影响响应按bytes |
| `scripts/research/index_market/xxm/daily_window_precheck.py`（133—143、205—249） | P4仅保留§11.2.3的窗口/隔离客户端；旧build计时/check/capture包装随旧runner清退 |
| `scripts/research/index_market/xxm_page_request_audit.py`（50—60） | P4保留原真实只读/鉴权计时，适配bytes和模式，finally恢复；不写响应文件 |
| `scripts/research/index_market/xxm_forecast_display_audit.py`（56—95） | P4同上，移除candidate/旧display替换；使用唯一正式r4 |
| `scripts/research/index_market/xxm/bottom_history_acceptance.py`（268—348） | P5删除旧build/_response计时及来源runner；有效独立样例先迁出 |
| `scripts/research/index_market/xxm/reference_rescue_acceptance.py`（173—216） | P5删除旧build包装及比较；不让它继续当正式r4入口 |
| `reports/xxm_bottom_history_precheck_20261016/run_budget.py`（55） | 已在§10.3.2具体删除名单；P5清退旧query/预算运行器，保留原报告 |
| `reports/xxm_forecast_range_precheck_20261014/http_precheck.py`（42） | 同上，旧query直接调用随文件清退 |
| `reports/xxm_forecast_range_implementation_20261014/http_acceptance.py`（43—70） | 同上，旧forecast build替换随文件清退 |
| `reports/xxm_minute_reader_optimization_20261014/http_precheck.py`（45—60） | 同上，旧build包装随文件清退 |

query_service自身的_response/历史投影互调仍属于该query实现，不是遗漏的外部消费者。另有间接消费者：`tests/web/test_xxm_shared_loads.py`保留并发/取消及共享来源；研究tests中借上述工具的调用依§10.5迁移。前端实际HTTP消费者为`xxm/apiClient.ts`→`adapter.ts`→`useIndexXxmLayer.ts`→日/分钟图表，以及`xxm-forecast/apiClient.ts`→`adapter.ts`→`useXxmForecast.ts`→页面/右栏；P3统一字段/身份，P4再接延迟辅助模块。`daily-wave/apiClient.ts`的原合同和算法不变，仅P4环境/debug生命周期变化。

#### 16.2.2 逐文件状态及处理边界

以下为实施前git状态核对。`clean`表示文件已跟踪且当时无改动，`M`表示已有未提交修改，`??`表示已有未跟踪文件；后三类均不代表可以直接覆盖或删除。具体每文件动作仍唯一引用§10—11.2，不另列一套删除政策。

| 已核清单 | 当前状态与具体例外 | 后续落点 |
|---|---|---|
| §10.2研究xxm目录37个实际文件 | 29 clean；`reference_rescue_acceptance.py`为M；下列7个为??：`top_current_close.py`、`top_current_close_selection.py`、`top_reference_priority.py`、`top_return_reference.py`、`history_disappearance_screen.py`、`history_replacement_screen.py`、`saved_minute_window.py` | 每个文件保留/迁移/删除及函数边界已在§10.2、§11.1—11.2对应；P1不改这些文件 |
| §10.2.1主题级5项 | 4 clean；`scripts/research/index_market/README.md`为M | 三个原路由工具P4迁移，history_projection_audit保留，README活动命令P5清理；当前已有修改保留 |
| §10.3.1旧报告代码49个 | 均clean；其中45个具体旧执行文件待清退，另外4个原数值工具明确保留 | 不能按整个目录删除，4个保留文件不得误计入45个删除项 |
| §10.3.2其他报告18个执行文件 | 均clean，18个路径全部存在 | P5按具体文件清退；JSON/CSV/图片/README及原结论不动 |
| §10.5研究tests表37个实际文件 | 25 clean；`test_xxm_acceptance_scope.py`为M；下列11个为??：`test_xxm_near_first_review.py`、`test_xxm_reference_window_review.py`、`test_xxm_same_bar_dull_review.py`、`test_xxm_saved_minute_window.py`、`test_xxm_top_current_close.py`、`test_xxm_top_current_close_selection.py`、`test_xxm_top_reference_priority.py`、`test_xxm_top_return_reference.py`、`test_xxm_history_disappearance_screen.py`、`test_xxm_history_replacement_screen.py`、`test_xxm_confirmed_cases.py` | 有效独立样例迁唯一r4；专属旧runner测试到P5才清退，作者观察及最小两位算术保留 |

正式计算/Spec/types/恢复/预测、两个query与schema、三个识别/预测API、App router及现web识别/预测tests当前均无本轮需合并的已有修改。其完整实现位置见技术方案§1.1、本文§2—6；P1不修改它们。独立daily_wave算法/三角定义不在P1范围。

本次三个原合同中，`index-detail-api-contract-v1.md`和`index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md`已有M，分钟合同clean；只在对应识别/预测位置补目标章节，原修改和历史不覆盖。本产品/技术/LLD三文档在本次开始前均为??。Wealth页面、样式、右栏及Lake等其他M/??不属P1，无额外编辑授权。

§10.3.3列明的原输入/原图/日历/Notebook与历史API输出仅作保留清单定位，不打开其行情内容。原数据SHA仍是数据校验，不能与旧源码保护混同。本次没有发现清单外必须新增的算法、路由或运行器；P2/P4/P5实施当天仍须重新核引用和他人改动，不能把本日状态当永久删除许可。

### 16.3 验收与独立审计

#### 16.3.1 五步交付对账

| P1步骤 | 实际产物与核对依据 | 状态 |
|---|---|---|
| 1 当前代码及范围 | §16.2的16个外部query调用/包装文件；§10各表逐文件存在/git状态核对；CodeGraph入口、继承、query/API及前端消费者加当前源码静态补核 | 已完成；运行时未改 |
| 2 原接口合同 | [日线原合同§10](index-detail-api-contract-v1.md)、[分钟原合同§8](index-detail-minutes-api-contract-v1.md)、[原预判文档§36](index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md)完整登记目标参数/字段/null/关系/错误/环境/预算/返回；明确当前r2与待实施r4，不覆盖其他接口或历史 | 已完成；未宣称HTTP已生效 |
| 3 迁移与删除去向 | §10—11.2文件/函数及已有消费者逐项对应，§16.2补本日状态。保留独立峰谷、最小两位算术、原材料及有用测试；P5才清退旧执行器 | 已完成；未删除或迁运行器 |
| 4 独立业务预期 | `xxm_product_v1_cases.py`的37个手写核心案例及FORECAST_MATH独立Fraction人工上下文，配`test_xxm_product_v1_cases.py`的53项材料检查。四周期仅格式化输入日期，不据此证明来源连续性 | 已完成；未运行实际识别/求解 |
| 5 普通/debug样例 | `xxm_product_v1_responses.py`及其测试109项：7类识别材料、8类预测状态、四周期时间、REPLAY及空源、跨窗历史/等待、B→A及非法关联/旧身份/zero反例；hash无默认显式传入，未使用r2 Spec | 已完成；只验字段/关联材料 |

材料文件位于`scripts/research/index_market/tests/`。响应里的编号和预测价格是明确标注的合同形状样例，不冒充正式事件编号或完整求价结果；真实数学预期由FORECAST_MATH和核心字面案例单独提供。P2/P3须把这些预期对实际唯一r4断言，不能因本批材料通过就跳过算法/DTO验收。

既有`test_xxm_input_validation.py`的非法数值/完成标志/日期/顺序/正价格及合法输入反例、`test_xxm_snapshot_validation.py`的独立进度字段/损坏关系/恢复失败不污染等人工样本已静态核对，继续按§10.5在P2迁正式身份；本次不改现r2测试或将其成绩充当r4通过。

#### 16.3.2 独立审计发现与修正

合同、业务材料、响应材料、文件清单分别由未撰写该产物的一方对照本文/当前生产者独立核对；修正后只复核发现项，不重复行情或算法审计。

| 审计发现 | 已完成修正及证据 |
|---|---|
| 文件清单误写不存在的useXxmSignals.ts | §16.2.1改为真实useIndexXxmLayer.ts，日/分钟工作区调用均核实 |
| nullable写法可能被理解成必须总为null | 日线10.2、预测36.2明确“允许null；无值时显式返回，不省略键”，不改合同实际类型 |
| 分钟预测样例把未来日期统一映射15点，与barsAhead不符 | 独立字面未来端点表按m60/m90/m120实际收盘点给出1/2/3根；目标/激活/中间/切换/nextBar全部同步；历史与请求保留15点。测试用另一份手写时点断言，独立窄复核关闭 |
| 已有案例尚不能直接抓住几项重要退化 | 补无B、仅一根有色、真实翻色时A合格仍不得救援、已DULL价格回落但DIF未变仍保持四例；未改原有业务预期 |
| 数学entry范围缺少足够人工前提 | 明确TOP/NONE、当前count1/price100/DIF2、B.price70/DIF10无A、EMA12/26=102/100及DEA=-2。手算证明价格门槛已满足、第二根真红及累计峰条件，原范围只对这个上下文成立，不是通用公式 |

#### 16.3.3 实际检查与停点

- `.venv/bin/python -m pytest -q scripts/research/index_market/tests/test_xxm_product_v1_cases.py scripts/research/index_market/tests/test_xxm_product_v1_responses.py`：**162 passed，0.09秒**；只执行本批手写材料及独立算术，没有计算器、预测器或目标schema导入/回放。
- 根要求三架构文件：**16 passed，13.30秒**；只证明既有依赖和legacy边界，不证明r4运行结果。
- 三原合同的字段/空值/时间/枚举与§5—6逐项核对；文件/调用表由另一方静态复核。运行时核心/Spec/query/schema/API/App router仍clean，页面已有XxmLayerUi等修改保持，不把其原有dirty算成本轮修改。
- 仓库文档完整性检查通过；本次六份文档/四测试材料的相对链接/围栏/空白/Python AST、R01—R22与通用清单2.1—2.18及P1章节覆盖检查通过，`git diff --check`通过。不把文档检查当产品验收。

最终另由未撰写本批产物的审计方按五步整体核对：交付齐备、目标合同与LLD一致、预期独立、运行时未改，未发现实质遗漏或越界。技术方案文首的旧状态表述及本段检查结果已据实收尾，不遗留本批阻塞项。

本批仅维护三份主文档、三个原合同及四个手写测试材料文件，不新增依赖、配置、数据库/Lake读写或产品代码。没有读取真实行情、捕获旧r4基准、运行双组对比、浏览器、产品性能或真实接口验收，也没有提交/部署。

P1完成后停止；P2按§10.4.1先建立核验入口，真正保留旧r4-v2有界内存结果后才改旧依赖及MAIN_SPEC；正式detector hash限本批内部验收，forecast hash及公开消费者按P3统一。P1通过不允许提前清退r2，不允许跳过P3预测/合同或P4真实来源/页面验收。

## 17. P1后开工审计的顺序修正（2026-10-28）

本次按管理员要求只修改文稿，不开发、不捕获旧结果、不运行算法/HTTP/真实来源或性能测试。P1实际交付和既有测试成绩保留；旧审计中的“设计细化已完成”不能证明阶段依赖已经闭合。

| 发现及实际原因 | 已补的开发约束 | 开工时必须看到的证据 |
|---|---|---|
| 只写先捕获旧结果，却未给实际入口；旧r4又继承待改父类，先改代码就永久失去本次真正基准 | §10.4.1明确一次性父/子测试文件、P1独立事实映射、终端启动/READY/compare/abort、逐根字段/映射次序、整批预算及丢内存停点；§11.3第1步先实现它 | 真正148例CAPTURE_READY是允许修改旧依赖的前提，不能拿协议mock或P1材料检查替代。最终新进程对账通过才算P2该项完成 |
| P2要求改FORECAST_SPEC，预测模型却排P3；模型当前Literal只认r2，单改Spec会使返回失败 | §2.2、§11和§11.2.5明确P2只MAIN_SPEC/识别核心/内部调用，P3才预测Spec/hash、数学/模型/HTTP和前端一起切；原分钟§8.3、预测§36.6及产品/技术方案同步 | P2不得提前改预测Spec凑身份，不调用完整预测返回宣称通过；P3迁移清单覆盖两项正式身份与全部公共消费者，不留混配版本 |

独立复核按两个方向进行：一方核当前Spec→模型→query→前端身份的实际调用，另一方核旧研究继承→捕获→修改→新进程→字段/编号比较→失败停点。本文已消除允许P2—P4任意同步消费者的笼统说法，明确各步前置、动作和验收归属；本次只可形成文档准备结论，不能预判尚未实现的核验工具、P2核心或P3预测验收通过。

本轮独立复核发现的两类细节已同步修正：标准记录沿真实snapshot的`pendingBottomHistory/pendingRearm`键，不能误用对象属性的下划线名称漏记录；“P3同步query消费者”限定为公开返回合同，不能误把P2内部构造/历史计算也推迟。修正后按相同前置和消费顺序交叉检查，未发现本次两项修订还有未明确的阻塞点。本轮仓库文档完整性、五份文档81个本地链接目标/代码围栏、过时阶段表述及限定差异检查通过；核心/Spec/query/schema/P1材料无本轮改动。不将这些静态检查称为P2验收。

## 18. P2实际开发与中断（2026-10-29，未验收）

### 18.1 执行顺序与已实施项

先重读根/src/scripts/scripts-research AGENTS、架构基线及本方案，使用CodeGraph explore/callers/impact核计算器继承、SeriesEntry及预测clone和消费者。目标源码无已有冲突；其他工作区修改保留。只新增§10.4.1三个测试文件及限定协议测试后，真正启动父入口并收到`CAPTURE_READY cases=148 periods=day,m60,m90,m120`；此前没有修改calculator/MAIN_SPEC/types/恢复解析。随后按下列顺序实施，未再运行旧研究包装。

| P2步骤 | 实际改动及验证 | 状态 |
|---|---|---|
| 1 核验入口及捕获 | 三个一次性测试路径；37个手写协议/映射/资源反例通过（0.73秒）；真正148例旧r4-v2逐根记录捕获完成后才修改旧依赖 | 当时完成；最终失败退出后内存丢失，现已不具备有效旧基准 |
| 2—3 核心/Spec/安全 | calculator.py直接实现r4；spec.py固定全部字段/精确类型；types.py去zero等待结束；snapshot_validation.py拒零色段；输入/恢复测试补合法零状态、旧身份及坏关系拒绝/不污染、37例四周期各前缀恢复续算 | 定向测试通过；不能替代完整迁移对账 |
| 4 内部构造/缓存 | query_service.calculator_at(0)显式新建空状态、不读快照或checkpoint；forecast_detector.clone完整带ts_code；内部人工读取/增量/真实1000边界/来源修订/前缀及clone隔离 | 合并输入/恢复/consumer实跑355项通过（0.75秒）；没有改变cache.put或预测缓存政策 |
| 5 只读离线记录 | types加入固定decision事实及Step可空字段，calculator默认关闭；实际选择/救援/转折处记录，finally清context；history_disappearance_screen.observe_rows仅用唯一正式类、最多1000根及20秒/256MiB/16MiB、无来源读取/写入 | 168项通过（0.57秒），含37×4独立P1点/事件及开关不改业务结果/编号，旧观察器有效反例迁唯一正式类 |
| 6 最终对账及审计 | 向原捕获进程发送compare，启动全新worker；父入口最终超时并按失败规则清内存退出 | **失败；P2未验收，不进入P3** |

正式detector身份为`xxm-direction-v0.1-r4`、hash=`ebd2afeefd470e19520daa8f86467d58977b02134313b9363a95e71c6b9e356e`。FORECAST_SPEC、公开schema/HTTP/客户端/前端身份均未改。旧研究文件仍按P5留待清退，不把已依赖新父类的包装当旧基准。observe_rows所在原文件及其他无关M/??保留，不覆盖原材料。

既有test_xxm_calculator.py人工核心组57项通过（0.11秒）；按已定r4口径将“零退出原段”的样本改为真实红柱以测试离段/恢复，另保留零不离段/零等待反例；固定1%不再将0.75/1.2作为现产品人工测试参数。该次明确排除6个旧冻结重放参数用例和1个P3预测分区用例，未运行旧行情或完整预测，未用skip/xfail掩盖失败。P1原CASES/响应材料的输入与字面预期没有修改。

### 18.2 最后失败及独立只读审计

终端实际返回`FAIL TimeoutError: phase exceeded its work deadline`，没有PASS，没有完整逐字段等价结论；这既不证明业务不一致，也不能据已有单测宣称完全一致。父入口异常后执行baseline.clear并退出，真正迁移前的内存结果随之丢失。按§10.4第6项，本次迁移对账作废并停止；没有自动checkout、恢复旧副本、加载Git旧实现、创建worktree或写恢复文件。

由未编写核验工具的独立审计方只读核对实际代码，确认：compare_records每例两次对retained=(baseline,cases,result)重新bounded_size，保留对象包含整批新旧记录；148例完整走完仅这两处就安排296次全批扫描。管道分块还重复扫描保留记录，JSON编码每个片段及编号替换每个节点都进行资源检查。协议成功替身只有短消息，没有验证148例整批交接/比较耗时。

上述额外开销已由代码证实；但TimeoutError没有阶段/案例位置，不能凭静态代码断言超时唯一发生在比较、收发或解码中的哪一步。捕获打印的seconds也不包含最后检查/READY前GC，不能单凭该数值称完整耗时已验收。当前未运行进一步性能定位、架构全组或完整产品验收；不把计划检查写成已经通过。

**后续需管理员确认后再定稿/执行：**核验工具先消除重复全批扫描、补阶段耗时及整批有界测试，20秒总限额和精确比较不放宽；另外确认如何重新具备真正迁移前的捕获条件。当前r4包装不可充当旧基准，不能直接再跑compare、延长时限或用新程序输出补旧结果。原方案/LLD未同步且没有确认前，不继续修代码或重新执行。源码和人工测试修改保留、未提交、未部署，整体产品仍未交付。


## 19. P2核验工具修复及固定旧提交重新捕获（2026-10-29，已获执行授权）

### 19.1 目标、范围及步骤

管理员批准处理§18暴露的重复扫描和超时，并允许重新取得真正迁移前结果。本轮修§10.4.1四个一次性测试文件及三份主文档，并按§19.5修正已有P2离线记录缺陷；独立P1材料、正式算法/Spec、预测、API和页面不改变。先修原方案/本LLD，核代码影响，再修工具及反例，先做148例完整工具性能检查，随后执行真正旧r4-v2→正式r4核对，最后独立审计P2。P3不开始，不提交、安装、读真实行情或写结果文件。

### 19.2 旧源码读取与隔离

唯一提交固定为`528659ae97843f06e5be560aa24fc10019fdb039`，仅允许下列五个源码，禁止参数选择版本、自动重试、checkout、worktree或磁盘源码副本：

- `src/biz/services/wealth/market/index_detail_xxm/spec.py`
- `src/biz/services/wealth/market/index_detail_xxm/types.py`
- `src/biz/services/wealth/market/index_detail_xxm/snapshot_validation.py`
- `src/biz/services/wealth/market/index_detail_xxm/calculator.py`
- `scripts/research/index_market/xxm/r4_reference_trial.py`

`xxm_product_v1_migration_capture`在独立解释器中通过一次`git cat-file --batch`读取，每文件正文只取一次；按固定blob身份核类型/长度/完整正文/分隔，无缺失重复或额外响应，五源合计≤1MiB。身份是本次旧来源定位，不是产品运行时源码SHA门禁。返回commit、五路径读取次数（均为1）和总字节数，正文不得输出或持久化。父、旧/新子进程从启动时使用`-B`，不生成pycache。

自定义加载器只映射五个完整模块名；安装前五模块必须未加载。父包只允许本仓路径中的namespace或初始化AST仅docstring/pass；未知项目算法依赖必须失败，不能借当前正式模块补缺。五源依赖已静态确认闭合为彼此及标准库。旧子进程核实际旧MAIN_SPEC与研究r4-v2全部字段/类型后从空算人工输入，只返回标准业务记录及旧身份元信息；父进程核输入对应、完整字段/引用和P1独立事实后才发布READY。新正式worker仍只接人工输入，不能接旧结果或源码，不导入旧捕获模块。

### 19.3 去除重复扫描及资源检查

不再每案例、每管道块扫描整批已保留记录。固定记录在阶段边界只登记一次实际对象大小及身份集合；局部索引/映射/副本仅检查新增对象，不复制整批身份集合。不断增长的结果只登记新增记录及容器容量变化，完成后完整交叉检查一次。局部身份集合随局部对象释放，避免对象编号复用漏计。管道每64KiB按已登记大小加请求/接收容器实际容量检查，仍限制消息16MiB、stderr64KiB。编号对应使用集合和按业务字段索引，拒绝多义/缺失/未来/悬挂引用；逐字段精确相等、原数值、数组顺序及独立预期均不放宽。

资源检查放在阶段边界、每例/每根、固定字节/节点批次；不得每JSON片段/递归节点调用RSS检查。19秒工作截止的定时中断保留；最后1秒只用于关闭/终止/回收全部子孙进程。捕获20秒从父生成输入前开始，含启动、Git读/编译/旧计算、编码收发解码、父验证、GC和READY；比较20秒含新计算、全部交接、独立事实、映射、精确比较、最后检查和回收，不为新增步骤重置。单进程256MiB、全部保留数据16MiB保持。清理进程组前先poll回收已退出的直接子进程，再照常终止整个组；不因主进程退出而假定后代已退出，不吞PermissionError。失败输出阶段与案例/字段位置，无部分通过，清理内存后停止，不自动重试。

### 19.4 测试及验收

先用人工输入和完整148例记录验证编码、真实分块子进程交接、解码及精确比较在同一原预算内完成；工具性能样本不作为旧新等价证据。统计37/74/148例实际对象访问量，防止整批重复扫描再次出现；最后一例故意改值/编号也必须失败。补齐Git五源一次读取、缺失/截断/错类型/超限/额外输出、污染模块/父包执行语句/第六源码拒绝、无pycache/源码输出、超时及后代进程回收反例，并保留原协议及独立业务断言。

工具性能通过后才执行固定旧提交的真正148例捕获和新进程对账。记录实际两个阶段完整耗时、字节、各源读取次数和全部业务/编号结果；未通过不进入P3，不能延长预算或把相同标签代替完整相等。补跑P2定向与三架构检查、原文档检查，再由未编写相应代码的人员独立核实现与LLD。修复后实际验收见§19.6，工具性能样本不替代真正旧新对账。


### 19.5 独立P2审计发现的离线记录修正

`_advance_rearm`遇真实红柱会先结束等待，尚未检查保存的原参照DIF；原离线记录却按结束原因反推`referenceBroken=False`。按既定§7.2未检查应为None。修复在原检查执行的位置保存实际布尔值，移除按原因反推；红柱直接结束仍None，未结束/重新激活为实际False，原参照突破为实际True。不新增计算、不改变顺序/业务状态/事件/编号；只改`calculator.py`记录赋值及`test_xxm_r4_observation.py`独立红柱反例。与默认不记录的完整业务结果逐项相等；修复后由独立审计方复查。


### 19.6 实际验收、独立审计及交接

本节保留提交130bb7a3前的成功路径证据及当时判断。提交后发现的失败清理计时缺口由§20.1明确更正，修复及最终结论见§20.4；不能单凭本节成功耗时证明全部失败退出已受限。

| 硬要求 | 实现/测试证据 | 本次实际结果 |
|---|---|---|
| 旧来源真实且不重复读取 | capture固定五blob、一次cat-file batch；父核commit/身份/次数；合成截断/错类型/额外/超限/污染/第六依赖反例 | commit `528659ae97843f06e5be560aa24fc10019fdb039`；五源均1次，正文64,493字节；旧源码只在隔离进程RAM |
| 全部业务字段及编号 | 父`assert_case_facts/_index/compare_records`；独立TOP/BOTTOM字面记录、悬挂/多义/最后一例改值反例 | 真正37例×四周期=148例PASS；正式结果消息1,909,729字节，原值/标签/参照/历史/等待/进度均精确一致 |
| 原整批预算 | 同一绝对截止传子进程；READY、最终检查/GC/清理纳入；每阶段≤20秒，单进程≤256MiB，保留≤16MiB | capture 1.191秒；compare 1.427秒；没有加时或按例重置 |
| 消除重复整批扫描 | `RetainedSize`增量登记、局部索引/副本；按37/74/148例统计实际对象访问次数；缓冲合计反例 | 不再每案例/每块扫整批，不复制整批身份集合；最终完整交叉检查仍保留 |
| 异常及子孙回收 | 原deadline、权限错误不吞；先poll再group signal；专用pipe EOF核后代、Git忽略TERM跨工作截止反例 | 原错误不被计时中断掩盖，真实权限拒绝明确失败，后代退出，清理未越原end |
| 观察记录真实 | `_advance_rearm`只在真实执行DIF比较处记录；红柱结束None，-20/-5两侧反例 | 业务状态/事件/snapshot与默认关闭记录逐项相等；独立复查关闭此缺陷 |
| 正式核心及内部调用 | 唯一正式r4、安全恢复/拒错不污染、from-empty/append/calculator_at/count0/clone及观察 | 最终核心582项通过；未修改FORECAST_SPEC、公开schema/API或前端 |

最终合并定向回归：637 passed、7 deselected，3.99秒（核心582＋工具55）；排除原6个冻结重放参数和1个P3预测求解节点。三份架构测试16 passed，11.72秒。完整148例工具性能测试另使用当前正式实现两侧的完整记录，只证明交接/比较成本，已与上述真正旧→新PASS分开记录。各组均未超过60秒；未安装依赖。

原失败独立审计发现的全批重复扫描已移除；后续交叉审计另查到红柱等待的False记录、Git清理被alarm抢断、吞PermissionError、READY在时限外、编码合计内存事后检查，分别按§19修复并补反例。最终由未编写对应文件的审计方核核心与工具，不以作者自测替代独立核验。CodeGraph explore/callers/impact核核心、query/clone及消费者，并sync/status确认现索引；一次性未索引工具按实际源码/进程协议人工审查，不凭检索缺失推断无影响。

**执行偏差如实保留：**最后汇总回归曾漏排除`test_full_four_period_top_oracle_and_first_activation_are_preserved`的3个旧冻结参数，误读取本地冻结日线，在旧r2 Spec/hash断言失败（当次637通过、3失败、4排除）。随后只纠正为原LLD已要求的精确排除命令，最终637通过、7排除；未改原冻结预期、未skip新失败、未重复读取固定五旧源码、未调真实DB/API。这3项错误执行不作为P2通过证据，也不能表述为本轮完全未读冻结材料。

**P2验收通过并停止。**输入/旧源码/新旧完整结果/恢复副本均未持久化；PASS后旧基准与结果在同一比较预算内清理。仅保留本节汇总事实、代码及长期独立预期；一次性四文件按P5清退，不加入产品运行链。不提交/部署，不自动进入P3。P3再同时处理预测Spec/数学求解/公开及前端身份，P4再做真实来源与页面/生产禁用，P5最后删旧代码。P2不证明这些后续能力已经通过。


### 19.7 P2提交边界

`history_disappearance_screen.py`在P1清单中属于工作区未跟踪旧研究文件。本次提交只登记P2新增`observe_rows`及其必要标准库/正式计算器导入，不把原有旧runner、保护文件读取或其他未提交研究混入P2。工作区原文件完整保留，因此提交后该文件仍有未提交旧内容；P4/P5继续按§10.2清理/迁移，不提前删除。提交前从Git暂存内容在内存加载该模块，执行观察函数的独立测试，确保提交本身具备P2能力、无旧运行器依赖。其他已跟踪P2文件按明确清单提交，其他工作区修改不动。


## 20. 提交后审计的退出清理修复（2026-10-29，已批准）

### 20.1 问题、范围与执行顺序

提交`130bb7a3`的核心、内部查询、观察及真正148例成功对账仍有效；但父入口在计算失败后已撤掉工作计时器，才在main.finally执行baseline.clear/gc.collect。独立人工故障例在0.15秒预算下运行0.219秒，证明失败清理不受原阶段截止控制。此前P2完整通过结论收窄为成功路径通过，修复/独立复核完成后再形成最终结论。

本步只改现一次性父入口`xxm_product_v1_migration.py`、公共协议里的Budget退出清理方法、专属`test_xxm_product_v1_migration.py`和本组三份主文档。不改捕获子进程五源协议、正式算法/Spec/输入/restore/query/API/预测/前端/P1预期；不提交、安装、创建分支/worktree或进入P3。先同步方案/LLD、审计当前代码和调用，再修复、补定向回归和独立审计。原成功148例及读取次数保留，不重新加载五份旧源码、不重读市场材料、不重跑真正旧→新对账。完整148例工具成本可继续用当前正式实现的人工输入/结果测量，只证明工具成本。全部结果内存、不落盘；其他工作区修改保持。

### 20.2 每条退出路径与代码要求

1. `capture_baseline(*, terminal=False)`与`compare_baseline(..., terminal=False)`各建立且仅建立原一个20秒Budget；真正计算/验证迁为接收该Budget的私有函数，不在其中重置。包装函数负责成功、异常及KeyboardInterrupt的清理，并将清理耗时计入原阶段。比较`release_baseline=False`仅在成功的工具性能测试保留基准，失败一律释放。
2. Budget增加退出清理上下文，先于清理任何异常帧/记录开启，沿同一绝对`end`，不得以当前时刻再加20秒或新的清理宽限。工作仍最多前19秒，最后1秒只清理；已过end时，实际CLI立即以非0退出，不能继续做GC。
3. 实际一次性命令行以`__main__`显式传`terminal=True`。该清理阶段使用SIGALRM的系统默认终止动作及原end定时器，避免Python回调需等待C调用返回；原end到即由OS终止父进程并回收RAM。普通单测/导入调用默认False，使用能抛TimeoutError的处理器，不声称普通函数对C调用有强制终止保证；慢GC的硬终止证明必须在独立python -B子进程执行，不能终止pytest进程。该参数仅内部测试/CLI装配，不增加产品配置、命令行算法开关或用户开关。
4. 在捕获/比较包装函数内清理异常的完整cause/context链traceback，释放已结束私有计算帧持有的输入/结果/RetainedSize强引用；再清空属于本次的基准并执行必要GC。不能只清main的baseline，遗漏捕获局部结果、比较新结果或异常链。保留原异常种类和阶段/案例原因；清理超时须明确失败、无PASS。清理中屏蔽后续SIGINT，防止第二次Ctrl-C打断释放；所有清理后的控制返回均恢复原信号状态，实际终止路径保留原生截止直至进程退出。
5. main删除无预算clear/GC。捕获失败由捕获包装清理；比较失败/中断由比较包装沿该次end清理，main不得另起Budget补清理。READY等待中的abort、EOF、非法命令或KeyboardInterrupt没有新的计算阶段，收到命令/中断起只有最多1秒退出清理，不开启新20秒、不调用比较、不读来源。等待本身继续不计计算耗时。
6. actual CLI的有限失败摘要、终端flush及最终退出同样处于终止清理截止内；摘要写入/flush遇断开管道或关闭的错误流时，不得阻止清帧/clear/GC，也不得把原计算错误改成日志错误；只作有限尝试、不重复输出，仍按原截止清理并非0退出。清理计时器产生的TimeoutError不能被日志错误处理吞掉。成功比较也须先完成独立事实/精确对账/清理与最后检查才输出PASS。实际CLI最后显式flush后以os._exit(code)退出，避免返回解释器后又执行无截止GC；子孙在已有_run_child.finally内按同一end先回收，不以父退出替代子孙清理。直接调用main的单测返回既有0/1/2，不使用os._exit；没有新HTTP/API/产品入口。

### 20.3 限额、失败与测试门禁

两整批20秒、每进程256MiB、保留16MiB、每例1000根及单组测试60秒均不放宽，不新增重试或恢复文件。[Python 3.13官方信号说明](https://github.com/python/cpython/blob/v3.13.9/Doc/library/signal.rst)明确Python处理器可能等待C函数返回；本修复的系统强制终止仅指实际CLI的退出清理，不据此宣称整个19秒工作阶段所有C调用或普通函数都具备硬实时保证。

独立人工回归覆盖：捕获私有帧已有结果后失败；比较保留新旧记录/registry后失败；工作超时后只用原剩余end；KeyboardInterrupt及第二次SIGINT；cause/context链强引用释放；READY等待后abort/EOF/非法命令/中断；正常成功且releaseFalse保留；正常快清理能返回；实际CLI慢GC（含延迟Python处理器的C调用）在原end终止、非0、无PASS。对子孙回收及原55项协议反例保持检查。测试先核旧实现缺陷能被对应新增用例抓住，不通过修改业务预期或放宽时限消除失败。

最后进行P2原定向人工回归（准确排除6项旧冻结重放和1项P3预测）、必要架构/依赖及文档检查。独立审计方核本轮代码、所有退出路径、预算对象沿用和测试证据，再给是否完成P2验收的结论。本步实际修复、反例与独立验收见§20.4。


### 20.4 退出修复与P2最终验收

本轮按§20.2完成以下代码及对应独立回归；没有改变识别数学、选峰、事件、编号、原数值比较或来源协议：

| 要求 | 实际落点与证据 |
|---|---|
| 失败清理不再脱离原end | 父capture_baseline/compare_baseline包装统一持有Budget，私有work函数接收同一对象；main不再裸clear/GC。新增原缺陷用例修复前观察到alarm=0而失败，修复后通过；工作先超时再慢清理仍在原end终止，不重开时限 |
| 捕获局部/比较新旧结果及异常链释放 | _clear_exception_frames清完整cause/context链；在guard内释放局部帧、RetainedSize强引用与本次基准。捕获/比较×普通错误/KeyboardInterrupt四例均以弱引用核私有对象已释放；releaseFalse仅成功保留，失败仍清空 |
| 真实CLI清理期间C调用也受终止约束 | Budget.cleanup_at_deadline实际terminal=True使用系统SIG_DFL及同一end；三条捕获失败/比较失败/主动终止的延迟C清理替身、工作已超时后再C清理均在独立python-B子进程被SIGALRM终止、非0且无PASS；过期预算直接退出，不再进入GC。快清理对照正常返回 |
| 第二次中断不抢断清理 | 清理期间SIGINT忽略；普通调用退出后恢复先前ALRM/INT及旧定时器的绝对剩余，不追加原时长；实际终止路径保留guard到flush/os._exit。独立反例通过 |
| READY等待退出只有清理 | abort/EOF/非法命令/KeyboardInterrupt均只建立Budget(1,1)用于退出，不启动工作/比较/来源读取；捕获成功不留guard杀等待；四种退出及快清理对照通过 |
| 原错误在慢清理前可见，输出失败不挡清理 | _report_failure在清帧/GC前于guard内有限输出原类型、阶段/原因并先标已报，主入口不重复；READY退出明确写清理位置。独立审计发现并复现的慢C丢诊断、stderr断管/关闭挡清理两处均修复；六个写/flush反例修复前全部失败、修复后通过。TimeoutError、未知程序错误和KeyboardInterrupt不被IO处理吞掉 |

最终P2定向人工回归：**664 passed、7 deselected，5.35秒**。其中原核心/内部查询/观察582项、一次性工具82项（原55项＋本次27项），准确排除原6项旧冻结重放及1项P3预测分区。三份架构检查**16 passed，11.91秒**；各组未超60秒。代码/限定差异、文档链接/围栏和完整性检查通过。CodeGraph核上下文和调用影响并sync/status；未精准索引的测试工具按实际源文件补核。

独立审计方先核设计和实际退出支路，再报告并验证诊断的两项遗漏，修复后独立28项定向回归通过且逐项代码复核无剩余阻断；本次新增的3项日志异常传播反例也随664项最终回归通过。没有让作者成绩代替独立审查。

原真正148例旧r4-v2→正式r4成功对账仍沿用§19.6：捕获1.191秒、比较1.427秒、五源各读取1次。**本轮没有重读这五份旧源码、市场材料或重新执行旧捕获；没有据此伪造一份新的旧新对账成绩。**完整148例工具成本回归只使用当前正式实现两侧人工结果，仍只证明工具成本。正式核心/Spec/输入恢复/query/P1材料、捕获子进程协议无本轮差异，原业务迁移证据未因退出修复失效。

**P2最终限定验收通过，停在P2。**此结论包含本轮退出缺陷修复，不扩展到P3预测/公开合同、P4真实来源/页面及生产禁用、P5清退。实际CLI的退出清理有系统终止保护，普通导入调用及整个19秒工作阶段的C调用不据此声称硬实时。所有结果内存，不新增持久化、配置或重试；本轮修复尚未提交、推送或部署，不自动进入P3。
