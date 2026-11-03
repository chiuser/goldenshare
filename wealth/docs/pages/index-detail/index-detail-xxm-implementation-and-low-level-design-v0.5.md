# 徐小明当前代码实现说明 v0.5

> P5整理说明（2026-11-03）：本文保留原设计、开发及验收记录的历史含义，不是当前开工或运行入口。旧执行代码和过程产物已按清单清退；原路径文字仅作出处。现行规则与阶段见[产品文档](../../../../docs/product/wealth-top-bottom-recognition-product-v1.md)，有效原材料见[资料索引](../../../../reports/xxm/README.md)。

核对日期：2026-10-22。本文是当前工作区源码的实现说明，配套[算法与实现总结v0.5](../../../../docs/product/xxm-direction-algorithm-plan-v0.5.md)。原文件名保留以避免断开引用，正文不再是拟开发LLD。v0.6的[下一阶段方案](../../../../docs/product/xxm-next-implementation-plan-v0.6.md)与[LLD](index-detail-xxm-next-implementation-low-level-design-v0.6.md)负责新方法，不覆盖此处的代码事实。

本轮只读源码和测试正文，没有运行算法、接口、页面、数据库、Lake或测试；下述预算是代码上限，测试是已有覆盖，均不冒称本轮实测通过或生产部署状态。

## 1. 算法内核及记录

| 文件/符号 | 目前实际职责 |
|---|---|
| [spec.py:XxmSpec/MAIN_SPEC](../../../../src/biz/services/wealth/market/index_detail_xxm/spec.py:9) | 识别身份`xxm-direction-v0.1-r2`；主门槛1%，旧段最多2、当前至少2根、`strongest_eligible`、换色确认、无固定到期；除冻结研究门槛外其他设置不可随意构造 |
| [types.py:XxmBar/Wave/XxmStep](../../../../src/biz/services/wealth/market/index_detail_xxm/types.py:11) | 输入时间、close/DIF/DEA/hist和完成标志；Wave保存整段收盘/DIF独立极值；Step输出point、events、顶部/底部历史和等待变更 |
| [calculator.py:step](../../../../src/biz/services/wealth/market/index_detail_xxm/calculator.py:34) | 输入校验和升序检查→按正/负/零切段→累计价格/DIF→推进底部等待及救援→普通事件→顶部历史→底部历史/新底部历史→保存上一根及计数 |
| [_select_eligible_reference](../../../../src/biz/services/wealth/market/index_detail_xxm/calculator.py:161) | 当前累计价格先过最近旧段门槛，两个旧段按DIF强弱择合格者；不是逐局部峰或先近后远 |
| [_rescue_bottom_dull_reference](../../../../src/biz/services/wealth/market/index_detail_xxm/calculator.py:173) | 仅已有底部DULL、仍同负段且无等待，本根使整段DIF严格跌破原参照后，在发CANCEL之前尝试换强参照；可换峰而不新发事件 |
| [_advance_rearm](../../../../src/biz/services/wealth/market/index_detail_xxm/calculator.py:218) | 等待固定原参照和最近旧价，最新价格重新达标才再次DULL；等待失效/换色结束分别记录 |
| [_advance_bottom_history/_start_bottom_history](../../../../src/biz/services/wealth/market/index_detail_xxm/calculator.py:234) | 底部历史低价在形成时冻结，离开原负段后才允许历史价格撤销；与普通状态、等待分开 |

### 1.1 输入、首次选择及同段转折

计算器接收float值，不计算MACD、不做两位取数。拒绝未完成、非正close及非有限数字；日线时间须为规范日期，分钟须带`+08:00`；拒绝重复/倒序。日内端点及交易日连续性由来源层另查，不能说XxmBar本身完成了所有来源校验。

按`sign(hist)`切Wave，零也是独立符号。旧非零段遇反色或零都会进入对应历史池，池只保留最近2段；同段DIF小峰不拆段。所以真正反色分隔尚不是单独检查条件。普通状态在切段后清为NONE，零不触发换色形成。

首次顶部用整段最高close、最高DIF；底部用最低close、最低DIF。先过最近旧段价格，再在按DIF强弱排序的旧池中查严格价格突破及DIF背离；最多2段，同DIF近者优先。顶部当根DIF必须>0，底部无对应符号要求。原始相等不激活，不是比较课程两位值。

同段DIF转折以`abs(previous.dif) × dif_turn_pct / 100`为门槛，主值1%；前DIF非0且反向差达到门槛才由DULL形成STRUCTURE，已有结构朝原方向回转达到门槛则纠错。底部纠错另查本根最新close是否仍严格低于原参照价与最近旧段价的较小值、整段DIF是否仍严格高于原参照、是否仍负段且至少两根，全部满足直接DULL，否则STRUCTURE_DISAPPEARED加WAITING；原始DIF已严格跌破原参照时，更早走CANCEL而不是这个等待分支。当前普通首次激活分支不会继续同根确认结构。

直接反色时先核本根DIF突破原参照，突破优先CANCEL，否则原状态DULL可经color_flip确认，不要求额外1%。该根旧方向事件与根末新段普通状态NONE可以共存。

### 1.2 普通状态、历史及等待字段

| 记录 | 字段及生命周期 |
|---|---|
| `point` | 普通状态NONE/DULL/STRUCTURE、方向、当前参照，以及pendingTopHistoryId、pendingBottomHistoryId、pendingRearmId；NONE不代表此前从未形成过结构 |
| `events` | 普通事件及独立历史事件，保存id/time/direction/type/route/fromState/eventReference及历史/等待关联；同根可有普通事件和历史事件 |
| 顶部历史 | `confirmedAt/confirmationRoute/pricePeak/pricePeakAt/originalReference/status/endedAt/endReason/observedThrough`等；pricePeak创建时冻结。原DIF突破、新TOP信号优先结束；否则后根close严格突破冻结高价才发历史撤销，无离开原段要求 |
| 底部历史 | 创建时冻结`priceLow/priceLowAt/originalReference`及原段、形成事件；原段后续低价不改这份记录。`leftOriginAt`记录首次非负柱离开原负段，之后价格跌破才发历史撤销；原参照突破、结构消失、新BOTTOM信号可仅结束历史 |
| 等待 | `referenceWave/nearestPriceGate/segmentStart/disappearedAt/observedThrough`及WAITING/REACTIVATED/INVALIDATED/SEGMENT_ENDED；等待不是DULL。后续最新close重新严格跌破两个保存价、仍原负段且DIF背离才重激活；DIF严格破原参照或零/换色只结束等待，不补CANCEL |

历史价格事件为`RESEARCH_HISTORICAL_WITHDRAWAL`，同段底部结构消失为`STRUCTURE_DISAPPEARED`，DIF突破为`CANCEL`；不能合成一种内部原因。固定24/26根到期未实现，也不是当前默认规则。

### 1.3 快照与查询前段恢复

[snapshot](../../../../src/biz/services/wealth/market/index_detail_xxm/calculator.py:183)保存specHash、指数、周期、sourceIdentity、处理数、当前Wave、两个历史池、普通状态及参照、上一根、顶部历史、底部历史和等待。事件完整账本由调用方保存，不由快照自行重建。

[restore](../../../../src/biz/services/wealth/market/index_detail_xxm/calculator.py:361)要求字段集合和规则/对象/周期/来源一致，先解析校验再整体发布；对底部历史、等待的字段/时间/关联有专项校验。**顶部pending只深复制，没有底部同级别的专项验证；不能写成所有快照字段都有同等强度的完整校验。**当前快照也不包含新研究要求的全部DIF局部峰和每峰价格窗口。

## 2. 路由、来源和业务时间

### 2.1 接口及装配

| GET路径 | 当前参数及限制 |
|---|---|
| `/api/v1/wealth/market/index-detail/xxm-signals` | 仅000001.SH；日线period默认day；可选startDate/endDate/limit，默认300，最大2000 |
| `/api/v1/wealth/market/index-detail/minute-xxm-signals` | 仅000001.SH；freq必传60/90/120；同样日期窗口及limit，默认500，最大2000；条件装配 |
| `/api/v1/wealth/market/index-detail/xxm-key-point-forecast` | tsCode、必传period=day/m60/m90/m120、可选asOf；不接受图层窗口参数和limit；分钟能力未开放返回不支持 |

依据：[日线参数](../../../../src/biz/api/wealth/market/index_detail_xxm.py:15)、[分钟路由](../../../../src/biz/api/wealth/market/index_detail_minute_xxm.py:18)、[预测参数及错误映射](../../../../src/biz/api/wealth/market/index_detail_xxm_forecast.py:10)、[v1装配](../../../../src/app/api/v1/router.py:65)。路由接入既有`require_quote_access`；未知/重复参数拒绝。预测把相关XXM错误映射到XXMF，不伪装成无候选。

分钟后端能力要求dev/local、`WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED`配置为真（默认False），以及读取依赖和正式Lake路径可用。代码检查不等于本轮已确认本机实际配置/目录可用。依据：[能力条件](../../../../src/foundation/config/local_minute_capability.py:40)、[默认设置](../../../../src/foundation/config/settings.py:56)。

### 2.2 来源及连续性

[source.py](../../../../src/biz/queries/wealth/market/index_detail_xxm/source.py:50)日线读`core_serving.index_factor_pro`的close、macd_dif_bfq、macd_dea_bfq、macd_bfq。分钟经既有读取器匹配Gold价格与指标两流，身份/日期/时间集合须一致；正式路径为`/Volumes/datasource/data_lake/gold/quote/major_index_mins`和`gold/indicator/major_index_mins_technical`，路径合同见[major_index_mins_contract.py](../../../../src/foundation/clients/local_lake/major_index_mins_contract.py:84)。本轮没有读取这些数据。

来源层以SSE日历核输入首根到末根的交易日及日内端点：60为10:30/11:30/14:00/15:00，90为11:00/14:00/15:00，120为11:30/15:00。中间缺根、重复、乱序或错端点失败。该检查不证明源首根以前历史完整；图层响应仍明确`initialHistoryIncomplete=True`。

### 2.3 业务日期及READY/DELAYED

[load_entry](../../../../src/biz/queries/wealth/market/index_detail_xxm/query_service.py:169)使用默认页面业务日期，不是每到当天分钟端点就推进。当日开市且20点前用上一开市日，20点起用当日；休市沿最近开市日。依据：[MarketPageContextQuery](../../../../src/biz/queries/wealth/market/context/market_page_context_query.py:85)。图层及预测共用此加载边界。

实际截至与期望截至比较为READY/DELAYED/EMPTY；尾部未到可DELAYED，中间缺口拒绝。没有事件仍可READY，不是错误。预测DELAYED不输出有效候选。指定历史asOf只使用真实截至前段，分钟asOf须是合法端点且带`+08:00`，不允许把未来数据用于过去结果。

## 3. 查询、缓存、窗口及预算

[IndexDetailXxmQueryService](../../../../src/biz/queries/wealth/market/index_detail_xxm/query_service.py:139)先加载实际完整前段并计算，再按请求窗口裁剪points/events及相关历史。窗口改变不改变初始化起点；sourceInputId由实际数值/时间前段的链式指纹形成。历史查询将截至之后才结束的历史/等待回退成当时PENDING/WAITING，重算观察范围，不能把未来结束状态带到过去。

当前只有进程内序列及预测响应LRU，没有持久化算法结果表。来源旧前段一致时，复制快照增量处理；前段修订从源首根重算。每1000根保存内存检查点；历史asOf从真实前段检查点补算，假设未来状态不存入实际序列缓存。

日线加载重新读源；分钟源签名不变可复用已有raw。`SharedLoads`只共享正在重叠的加载，完成就移除pending，不是完成结果长期TTL缓存；失败可重试，等待方超时不取消主加载。依据：[查询与缓存](../../../../src/biz/queries/wealth/market/index_detail_xxm/query_service.py:97)、[共享加载](../../../../src/biz/queries/wealth/market/index_detail_xxm/shared_loads.py:5)。

| 代码预算 | 当前值及来源 |
|---|---|
| 源批/总行/分区文件 | 1000根一批；最大20000根、5000分区文件。总量由分钟读取器合同导入，不是本轮允许读取量 |
| 图层响应 | 默认日线300、分钟500，最多2000根、1MiB |
| 共享缓存 | 64MiB、最多16项，序列和预测响应共同占用 |
| 来源加载/查询期限 | 同时2个来源加载，查询期限4秒 |
| 前端HTTP | 图层与预测超时均5秒，从队列实际发出时开始计时 |

依据：[runtime.py](../../../../src/biz/services/wealth/market/index_detail_xxm/runtime.py:8)、[分钟行数上限](../../../../src/foundation/clients/local_lake/major_index_mins_reader.py:80)、[分区合同](../../../../src/foundation/clients/local_lake/major_index_mins_contract.py:34)。这些是容量和拒绝条件，不是已达成的性能实测，也不是v0.6离线8案/60秒预算。

## 4. API记录怎样进入页面

响应schema分开校验`points/events/topHistories/bottomHistories/rearmRecords`，时间、方向及关联分别检查。依据：[index_detail_xxm.py](../../../../src/biz/schemas/wealth/market/index_detail_xxm.py:23)。schema校验是交付边界，不能反过来概括为计算器内部每个快照字段同样严格。

Wealth[adapter](../../../src/features/index-detail/xxm/adapter.ts:27)核对对象、周期、算法版本/hash、来源与指标版本，并逐根与已经加载的图表close/DIF/DEA/MACD完全相等；不一致明确失败，不使用容差拼接。图层绘在MACD面板，事件锚在当根DIF位置，悬浮详情分别显示事件、原参照、顶部/底部历史和等待记录。等待文案不冒充已有钝化，历史结束不一律画绿。

图层[useIndexXxmLayer](../../../src/features/index-detail/xxm/useIndexXxmLayer.ts:13)按图表首尾和数量请求；分钟还须`import.meta.env.DEV`。切换取消并忽略旧响应，支持手动重试，没有独立60秒轮询。UI仍标“徐小明V0.1·研究”和历史寿命未验证，不是作者软件复刻认证。

预测[useXxmForecast](../../../src/features/index-detail/xxm-forecast/useXxmForecast.ts:16)只在技术页签活跃、页面就绪且上证时请求；最新模式按后端60000ms刷新，历史模式不轮询，分钟历史固定该日15:00。页面隐藏/切换取消，再可见重取；分钟行也要求DEV及supportsMinute。四周期行独立显示状态、失败及重试；显示文案来自后端，不在页面重新计算算法。

页面请求调度先图表、九转、XXM图层、预测；XXM和预测独占页面队列，其他轻请求最多两个并行。它与后端来源加载并发不是同一设置。依据：[页面装配](../../../src/pages/index-detail/IndexDetailPage.tsx:67)、[请求调度](../../../src/features/index-detail/api/indexDetailRequestScheduler.ts:1)、[图层UI](../../../src/features/index-detail/xxm/XxmLayerUi.tsx:33)。

## 5. 条件预测的当前实现

| 文件/符号 | 当前行为 |
|---|---|
| [forecast_spec.py:FORECAST_SPEC](../../../../src/biz/services/wealth/market/index_detail_xxm/forecast_spec.py:7) | v0.3-r2，最多20根，尾250根校准，计算200ms、响应32KiB、刷新60000ms，未来日历最多90自然日 |
| [forecast_query_service.py](../../../../src/biz/queries/wealth/market/index_detail_xxm/forecast_query_service.py:87) | 同源加载真实识别结果；真实当前确认优先CONFIRMED，无需再为其校准未来投影；其他状态准备投影及未来端点 |
| [projection.py](../../../../src/biz/services/wealth/market/index_detail_xxm/projection.py:21) | 从已加载完整收盘序列首根close初始化两条EMA、DEA从0开始，逐根重建；用末250根已有DIF/DEA/柱校准。日线容差0.0005、分钟1e-8，失败精度待定；日线三位舍入与课程两位规则不同 |
| [forecast.py](../../../../src/biz/services/wealth/market/index_detail_xxm/forecast.py:15) | 已钝化时假定中间收盘维持当前close；未钝化先求下一根进入价范围，再假定中间保持进入价，寻找最近可行结构端点，输出范围、排除和示例 |
| [forecast_detector.py](../../../../src/biz/services/wealth/market/index_detail_xxm/forecast_detector.py:9) | 克隆r2计算器与真实快照，用假设K线调用原step验证事件，不改变实际计算器；保留现底部换峰路径及来源舍入不确定性 |

未来端点按SSE日历及各周期完成时间生成，日历不足或缺口拒绝。预测状态包括已确认、有效钝化下条件、等待/条件触发、无候选、精度待定及来源异常；条件区间不是承诺未来价格会走到那里。UI显示后端display文案，不计算另一套价格条件。上述200ms等同样只是设置值，本轮未实测。

## 6. 研究脚本与产品入口分开

当前[local_extrema.py](../../../../src/biz/services/wealth/market/index_detail_daily_wave/local_extrema.py)只有原始局部转折、平台及后根确认时间；[near_first_review.py](../../../../scripts/research/index_market/xxm/near_first_review.py:47)已有两位算术，但其选择器每根独立、最多两项，另有历史合并试验。这些没有被产品XxmCalculator作为完整DIF参照池调用。

研究包中的当前价、近峰优先、改选参照等子类仍是明确试验，不能因类名或测试存在就称产品已采用。完整新方法拟用的`course_rules.py/dif_references.py/offline_replay.py/software_observations.py/software_mark_review.py`尚未创建；具体未来职责只维护在v0.6，不在本文作为已实现能力。

## 7. 已有测试与本次核对边界

| 已有测试文件 | 已读到的覆盖；不是本轮运行成绩 |
|---|---|
| [test_xxm_calculator.py](../../../../scripts/research/index_market/tests/test_xxm_calculator.py:37) | 字面DULL/STRUCTURE及历史优先级、两个旧池/最强参照、1%边界、零柱、价格/DIF不同根、恢复和底部历史/等待 |
| test_xxm_reference_rescue.py（原测试已清退） | 底部救援换参照、不够格则取消、原值相等、段内累计价而非本根价、等待不救援、顶部不镜像救援 |
| test_xxm_top_activation_r2.py（原测试已清退） | 首次TOP当根DIF>0边界、旧快照身份、负DIF既有结构与预测资格；另有读取历史源的用例，不能当无行情读取测试整包运行 |
| [图层接口测试](../../../../tests/web/test_wealth_index_detail_xxm_api.py:64) | 真实路由/查询/schema与参数鉴权、窗口前段、日历、EMPTY/READY、分钟两流、历史/等待关联、修订及淘汰；夹具使用临时内存数据库/本地样本，不等于正式数据库验收 |
| [预测接口测试](../../../../tests/web/test_wealth_index_detail_xxm_forecast_api.py:56) | 路由/合同、精度、预算、确认优先、20点切换、历史前段、共享加载和规则身份；同样不能代替真实源/线上运行 |
| [共享加载测试](../../../../tests/web/test_xxm_shared_loads.py:9) | 同时请求共享、不把完成加载当TTL、失败重试及等待超时不取消主请求 |
| Wealth `xxm/`与`xxm-forecast/`测试 | adapter、等待合同、版本身份、图上位置、请求/刷新等；不少使用夹具或替身，不作本轮真实API页面验收 |

本轮没有执行测试、全历史读取、行情核对、真实API/UI、回测或部署。静态源码只能证明相应路径存在及其条件，不能证明当前进程启用了分钟能力、真实来源完整、API可用、历史测试现在全过或与徐小明软件全部相容。

此次改写记录、改写前v0.5及源码SHA见核对记录（原记录：`reports/xxm_v05_current_code_summary_20261022_01/README.md`）。后续实现改变时同时更新本说明及v0.5总述；未来设计继续更新v0.6方案/LLD，不将拟实现行为写回本说明充当现实。

## 7. 2026-10-27：隐藏MACD标题旁常驻研究文案

依据管理员截图要求、展示基准§3及v0.5总述§8，仅修改`wealth/src/features/index-detail/xxm/XxmLayerUi.tsx:XxmLayerStatus`：删除固定身份文案；计算原状态提示后，无提示时返回null，避免留下原margin-left空位。日线`IndexChartWorkspace`与分钟`IndexMinuteChartWorkspace`继续使用同一组件；设置按钮由原面板头部负责，悬停`XxmResearchDetails`标题及全部业务逻辑保持。

本步不新增配置、数据读写、依赖、请求或缓存。加载/空数据/延迟/失败提示和重试、title沿现规则；无状态提示时不输出状态容器。执行失败或离开无新增资源可清理，重试继续原流程。计算仅增加一次常量级判断，不增加网络、恢复或最终验收的数据开销。

编码门禁与验收：范围只含上述组件及对应原文档；沿用`xxm/adapter.test.tsx`的加载、空数据和错误重试覆盖，并执行日线/分钟工作区相关测试、Wealth typecheck/build及文档完整性和差异检查。每组测试/构建以60秒为检查界限，超时先查因；复用现有依赖，不运行真实行情或后端算法。结果在完成后记录，不以计划代替通过。

实际完成：固定身份文案已从`XxmLayerStatus`移除，无状态提示时返回null，悬停标题保留。`xxm/adapter.test.tsx`、`IndexChartWorkspace.test.tsx`、`IndexMinuteChartWorkspace.test.tsx`共3文件15项通过，Wealth typecheck/build通过；构建保留既有chunk超过500kB提示。文档完整性和本次差异检查通过。只做静态文案调整及既有组件回归，未执行浏览器实看、真实API/行情重放、提交或部署；无API、算法、配置或CSS改动。
