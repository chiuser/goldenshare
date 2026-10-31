# 财势乾坤顶底识别低层设计 v1

更新：2026-10-31。状态：三项已确认修正已同步为本文件当前目标，代码与测试均待修改。当前实现为识别v0.3-r4、预测v0.5-r4，本次目标为v0.4-r4/v0.6-r4。§15—17仅为修改前历史实施/验收；本次文件、测试及后续顺序见§18。本轮只改文档，不执行行情、测试代码、提交或部署。

依据：[产品文档](../../../../docs/product/wealth-top-bottom-recognition-product-v1.md)、[技术方案](index-detail-top-bottom-recognition-technical-design-v1.md)。本文件只规定当前目标、代码迁移位置、开发顺序和验收，不包含已废弃的开发流程。实施必须使用本文规则和独立用例，不得从旧实验或旧输出推导当前预期。

## 0. 本轮产物、后续实施范围和硬要求

本轮依据专项回测方案§29及管理员最新确认，只细化三项修正：旧结构从首次反色起逐根检查价格；排除单根同色段引发的提前停止；同根旧价格消失及新同向首次钝化均保留计算事实但只画钝化。三项业务方向已经确定，不再列为待拍板；原软件内部怎样保存事件仍未被证实，不影响本产品采用该口径。

当前代码尚未执行本次修补。严格按§18先核心/记录/恢复/聚合与测试，再单根预测与测试，随后受控对比review，通过后才续P3第3—4步公开投影和必要前端。不得从本文设计完成推出开发或回测已通过；§15—17旧成绩不能替代本次。

只在当前dev-interface工作区保留清单外修改，不创建分支/worktree、安装依赖或恢复旧算法。输入、进度和结果仅内存，无数据库/Lake写入、结果/恢复文件、后台任务、用户算法开关或浏览器持久缓存。原1%、近远选择、首次资格、原EMA、预算及正式来源精度保持；P3完整400ms含最终校验和编码，不因三项修正放宽。

### 0.1 逐项对账入口

| 编号 | 方案硬要求 | 本文编码要求 | 验收归属 |
|---|---|---|---|
| R01 | 唯一正式r4；原r2最终清退 | §2—3唯一`XxmCalculator`，§10逐文件处理 | 核心人工/删后引用/迁移对账 |
| R02 | 本地四周期上证；生产日线也禁用 | §1路由和前端同时限制，§8环境交接 | 本地无Lake日线成功、生产直接API和页面反例 |
| R03 | 不新增env或用户开关 | §1、§2配置登记及完整Spec | 缺配置/未知环境关闭，正常显式dev/local可用 |
| R04 | 真实完成根和原指标，不补算 | §2输入、§4来源/历史前段 | 非法输入拒绝、原值和连续性 |
| R05 | 真实反色，零中性且不计根 | §3.2、§3.4、§3.7及§14 | 红零红/红零绿/全零/零日首次；零不首次反色 |
| R06 | 历史极值独立记录，首次使用当根C/D，记住本轮曾击穿 | §3.2—3.4及§14 | 禁止借旧价格；击穿后不回用；仅相等不算击穿 |
| R07 | B优先、A备选，最多两个 | §3首次选择及固定候选集合 | B价未过/等号/第三个更强都不能绕过 |
| R08 | 已钝化同根B→A、取消前处理 | §3救援次序、§6预测路径 | 当根连续/晚一根失败/无回切或第三个 |
| R09 | 1%相邻实际DIF及前值0保护 | §3转折/回转/真实翻色优先 | 恰1%/不足/前根零柱/首次只DULL |
| R10 | 原色段1%考核；首次反色起逐根比价、单根段不终止、首个有效同色段结束停止 | §2—4、§6.12、§14.15 | 顶底镜像、完整原Wave、正常结束不报消失；恢复/聚合/预测同口径 |
| R11 | 预测整体迁r4，不能只改显示 | §5.4/§6单步、先前提后有限边界、近处有解停止 | PF01—34、M1—M5，旧多步/中点/全float路径清退 |
| R12 | 正常和debug同一计算/编号 | §4—5内部结果和显式投影 | 同源公共字段、文本、ID完全相同 |
| R13 | 普通悬停简洁，正常故障可见 | §5、§8正式状态/当根事件/时间 | 无参照编号/等待；EMPTY≠error |
| R14 | 仅显式debug动态加载辅助 | §8独立模块、解码和请求身份 | 默认无import/请求/primitive；关闭和迟到 |
| R15 | 波段手动开始，独立日期/预算 | §8研究状态表/图层交接 | 未点击不计算；研究日期不污染右栏/预判 |
| R16 | 四种三角、1000根保持 | §8现画法/常量和共享图表 | 股票300/分钟500不变、301根后可用 |
| R17 | 两位仅保留独立取数和算术 | §10函数级保留/专属执行器清退 | 无产品调用、无旧源码依赖，字面算术 |
| R18 | 历史材料保留，旧程序安全删 | §10明确代码和原始材料清单 | 先解依赖/迁有效样本，后删代码和对应缓存 |
| R19 | 不读源码或SHA证明旧算法没改 | §14独立预期及代码审计 | 无运行时源码保护；源数据身份核验仍保留 |
| R20 | 预算含最终校验/编码和重试 | §4、§9完整时限及失败处理 | 冷热/历史/源修订/超限不返回半份成功 |
| R21 | 所有消费者同步，不留兼容双轨 | §4—5、§8、§10—11 | API/query/schema/前端/CLI/Notebook清零 |
| R22 | 依据代码和实际证据交付 | §11—14按层验收 | 单元/数学测试不能替代完整API、真实来源和页面验收 |

### 0.2 当前代码依据和影响面

当前唯一计算器为v0.3-r4、预测为v0.5-r4。已用CodeGraph codegraph_explore核对XxmCalculator、snapshot_validation及调用关系，再用当前源码补核query_service、forecast_next/forecast_detector、内部schema、前端adapter和专项对比。CodeGraph对通用query_service名称匹配到无关域的结果未作为依据，已回到明确的xxm路径核实。

当前_advance_followed_structures在nextSameColorStart非空前不查价格，并在下一同色段第一次反色即停止；forecast_next复用了相同的旧柱色限制；snapshot_validation和聚合又把下一段起点当成不可重置事实。前端尚消费旧公开合同。必须按本文成套修改，不在现旧接口/页面上临时隐藏标签。

Biz仍只依赖自身及允许Foundation；App组合，Wealth消费HTTP；研究工具可调用正式类，业务反向依赖研究、App或QTF均禁止。本次不改变这些边界。接口和TS目标文书同步见§5/§8，但运行消费者仍按原阶段实施，不提前发布混配版本。

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

## 2. 唯一计算器、类型与固定规则身份

### 2.1 当前依据及改动位置

现有唯一XxmCalculator、XxmBar、Wave及原数字校验继续复用；当前识别v0.3-r4、预测v0.5-r4仅是本次修补前基线。首次当根价格/DIF、近B后远A、相邻1%原浮点顺序和曾突破记忆没有新增变更；不得因此恢复r2、独立日线候选或两位判断。

本次识别身份升为`xxm-direction-v0.4-r4`，预测升为`xxm-key-point-forecast-v0.6-r4`。先落实完整Spec/新跟踪字段和真实hash，再依次迁移恢复、缓存、模型、预测、公开投影及前端；旧身份和缺新字段一律拒绝并由同源重算，不添加兼容分支。不得硬写假hash或读取源码SHA。

当前作用点：calculator/types/spec；snapshot_validation；src/biz/queries/wealth/market/index_detail_xxm/query_service.py及内部schema；forecast_next/forecast_detector/forecast/types/spec；第3步既定response_projection和公开schema；第4步Wealth xxm类型/decoder/adapter/详情。测试文件及具体修改见§18.3。

### 2.2 MAIN_SPEC目标字段（完整集合）

| 字段 | 固定值 |
|---|---|
| algorithm_version | `xxm-direction-v0.4-r4` |
| dif_turn_pct / max_refs / min_bars | `1.0 / 2 / 2` |
| reference_policy | `nearest_then_farther_two` |
| active_reference_policy | `same_bar_near_to_far_on_dull_break` |
| zero_policy / allow_zero_activation | `neutral_real_opposite / True` |
| activation_policy | `current_close_and_current_dif` |
| reference_break_policy | `strict_break_within_current_segment` |
| structure_return_policy | `adjacent_one_percent_to_dull` |
| structure_follow_policy | `price_until_first_valid_same_color_end` |
| structure_follow_min_bars | `2`，只约束结束旧结构跟踪的有效同色段，不改变首次min_bars或historical_min_bars |
| structure_follow_price_policy | `closed_origin_wave_extreme` |
| historical_min_bars / top_activation_requires_positive_dif | `1 / True`（两个已暂缓TODO保持现状） |
| macd_parameters / histogram_multiplier | `(12,26,9) / 2` |
| color_flip / flip_requires_turn | `True / False` |

删除`allow_zero_reactivation/historical_price_only/fixed_expiry/bottom_history_policy/same_segment_bottom_policy`等旧等待/撤销或无作用字段，不留旧值别名。`__post_init__`逐字段精确检查类型及默认值，bool不能冒充int。`spec_hash`保持asdict、sort_keys及现固定分隔符的规范序列化后SHA256；这是规则身份，不读取源码或核源码SHA。

新预测Spec完整集合见§6；版本固定`xxm-key-point-forecast-v0.6-r4`；当前物理实现v0.5仍须同步。两项hash只在对应完整Spec、模型和消费者同次迁移时真实生成；文档不预填假hash。旧r2、旧r4-v2/正式v0.1-r4和混配快照/缓存/响应均拒绝，按同源重算；不设运行时切换。

### 2.3 统一结构记录与事件（本次完整目标）

顶底仍共用XxmStructureRecord；新增三字段统一进入类型、snapshot、内部/公开debug结构、聚合、恢复、查询和相应fixture。不是env、数据库或用户配置。完整集合如下，不以缺省补值兼容旧副本。

| 字段 | 类型及准确含义 |
|---|---|
| id / structureEventId | 沿_id("structure", structureEventId)；同一形成事实的编号不因后续变化而改变 |
| direction / formedAt / formationRoute | TOP/BOTTOM；形成根；dif_turn/color_flip |
| originSegmentStart / originalReference | 原同色段起点；形成时六字段参照深副本，永久不变 |
| priceExtreme / priceExtremeAt | 形成当根已知原段最高/最低收盘及发生位置，保持形成事实 |
| originWave | None，或首次真实反色时固定的完整旧Wave，排除该反色根；后续价格门槛仅用其price |
| status | ASSESSING/FOLLOWING/FINISHED/DISAPPEARED；只有后两者终结 |
| firstOppositeAt | 有效结构首次真实反色根；原参照在该根先失效则仍None |
| nextSameColorStart | 当前被观察的后续同色段起点；尚无同色段为None；单根段结束时清None，后续同色段可填新起点。不是永久第一次同色段日期 |
| nextSameColorCount | 新增严格int>=0；start为None时恰0，否则为该当前同色段实际有色根数。零不增数；单根结束清0；FINISHED保留已完成有效同色段的起点和根数>=2 |
| trackingPriceExtreme / trackingPriceExtremeAt | 新增。首次反色之前均None；首次反色根起，在仍有效的跟踪根中累计TOP最高/BOTTOM最低收盘及首次发生时点，包含所有柱色和零柱。不包括正常FINISHED的终止反色根。两字段同时有值或同时None；用于恢复拒绝曾突破后回撤伪装有效，不改变originWave门槛 |
| trackingEndedAt | ASSESSING/FOLLOWING为None；正常结束或消失当根为实际时点 |
| disappearedAt / disappearanceReason | 仅DISAPPEARED非空；dif_return/reference_dif_break/structure_price_break |

允许转换：创建ASSESSING，或color_flip当根创建FOLLOWING；ASSESSING→FOLLOWING/DISAPPEARED；FOLLOWING可推进当前同色起点/根数和跟踪极值，或→FINISHED/DISAPPEARED。单根段结束可重置当前起点/根数，但不改变firstOppositeAt/originWave/形成事实。终态不得复开。color_flip形成当根若已价格突破，按§3.10当根直接最终DISAPPEARED，保留形成及消失两个事件，structures只发该id一份最终记录。

计算进度仍active_structure及followed_structures精确TOP/BOTTOM两槽，最多两份FOLLOWING，无无限单根段列表、历史全集或磁盘保存。完整历史仍由SeriesEntry聚合同根最终更新；任何已返回对象均不可变。

XxmStep仍point/events/structures/decision。内部point及六字段Reference不改；内部event精确id/time/direction/type/route/fromState/eventReference/relatedStructureId，不加入显示标志。DULL为activation/dif_return，STRUCTURE为dif_turn/color_flip，CANCEL为dif_break/dif_break_on_flip/structure_price_break。原段考核不套用后续价格途径。

旧价格消失id沿_id(time,"CANCEL","structure_price_break",relatedStructureId)，事件方向/原参照取被撤销结构，fromState=STRUCTURE不强等于当前新段状态。先处理根前旧跟踪、再普通关系；当前根刚进入FOLLOWING的记录由同一单记录推进函数处理一次，不能再次推进根前旧槽。所有真实事件保留，按§3.10确定顺序；structures每id本根至多一份最终副本。

图上显隐不属于step事件删除：§5.3后端公开投影新增必填displayOnChart，普通/debug共同标明该事件是否画标记及进入普通当根事件说明。完整事件、id和debug关联不丢失。严格只对同根同方向的旧CANCEL/structure_price_break及新DULL/activation组合隐藏前者；DULL/dif_return、STRUCTURE、不同方向/日期及其他CANCEL不扩大隐藏。

## 3. r4识别规则

本节是唯一识别规则。当前实现必须按本节修正，测试预期只来自已确认规则和§14独立人工样本。规则测试必须独立手算预期，不能拿旧算法输出当答案。

### 3.1 阶段含义和本周期边界

| 阶段 | 进入前提 | 判断 |
|---|---|---|
| 钝化评估期 | 未钝化，存在价格解 | 正常当根价格/DIF、根数、参照同时满足才首次钝化 |
| 结构评估期 | 有效钝化 | 保持/结构形成/钝化消失，不重复首次价格门槛 |
| 结构形成考核期 | 结构已成、原色段未结束 | 原参照DIF破直接消失；否则1%回转退钝化或保持 |
| 首次真实反色起 | 原结构有效，或color_flip当根形成 | 冻结完整原Wave；从该根起逐根比收盘，反色/零柱也检查 |
| 后续同色段当前仅1根 | 仍有效FOLLOWING | 价格突破即消失；段结束不终止跟踪，清当前起点/根数继续；不预测未来根数 |
| 后续同色段至少2根 | 首个有效同色段已达到资格 | 段内含零逐根检查价格，真实反色结束时正常FINISHED，结束反色根不再比价 |

DIF拐头但仍同色、零柱或单根段结束均不正常终止旧跟踪；FINISHED/DISAPPEARED不复活。两方向镜像。正常新一轮与旧跟踪并行，显示优先不改变任何计算事实。

### 3.2 数值、色段和历史参照

只使用完成K线的源收盘价C、源DIF值D和源MACD柱H；不重算实际指标、不改用high/low，不取两位有效数字，不增加epsilon或额外百分比筛峰。日线和60/90/120分钟采用同一识别规则，仅时间格式和实际来源不同。

- H>0红柱、H<0绿柱、H=0中性。真实反色才结束色段；红→零→红仍同段；红→零→绿到绿根才结束旧红段。零不增加有色柱根数，但它的C和D属于尚未结束的原段；开头全零不借后面的颜色补建历史。
- 红段保存最高收盘及最高DIF，绿段保存最低收盘及最低DIF，价格和DIF日期各自独立。Wave.price/dif分别表示这个方向的极值，不是每段额外保存另一方向的全部极值；独立日线基础工具仍保留自己的完整记录。相等保留原极值发生日期。这里的累计极值用于结束后作为历史参照，以及检查本轮是否曾突破某参照DIF，不能用累计价格代替当根首次钝化价格。
- 首次真实反色根属于新段，不能计入旧段根数、旧段价格或DIF极值。旧段end为前一根（可为零）。同一根可以对旧结构完成首次反色，又作为新段第1根。
- 每方向只保留最近两个已结束同色段：最近B、较远A，按时间确定，不按DIF强弱排序；不查第三个。历史单根段仍保留并可作参照，不新增历史至少两根过滤。
- 反弹红段正在运行时，之前结束的绿段是近谷，其左侧旧红段是近峰；反弹红段结束后，它成为新的近峰。首次反色结构的历史事实与色段极值分开保留；新一轮正常判断与§3.7规定的旧结构有限跟踪独立运行，后者只跳过单根段，首个有效同色段结束后不能再扩展。

### 3.3 当根资格与本轮曾击穿，必须分别检查

对参照X的历史价格Px、DIF峰谷Dx，当前逻辑方向s取顶部+1、底部−1：

| 判断 | 顶部 | 底部 |
|---|---|---|
| 当根首次价格合格 | C>Px | C<Px |
| 当根首次DIF合格 | D<Dx | D>Dx |
| 本轮曾严格突破参照DIF | 本段任一完成根D>Dx | 本段任一完成根D<Dx |

“本轮”是当前尚未结束的逻辑同色段，包括其中零柱。不论突破发生在首次钝化之前还是之后，一旦s*(D−Dx)>0出现过，X在本轮不可恢复使用；后来DIF回到合格一侧、价格再次突破也无用。近B失效后只能按顺序检查A；A也失效，本轮没有其他参照。新色段按新的历史池重新开始，不永久封禁某个数值。

当根严格背离与历史是否曾击穿不是同一判断。D曾等于Dx不算击穿；等号当天不能首次背离，但之后恢复严格背离且其余条件满足时可以首次钝化。已有钝化D等于Dx也不因等号取消。实现可用本段累计DIF极值判断“是否曾严格击穿”，但不能把“累计极值必须严格背离”当成同义条件，否则会误拒只曾相等的场景。

### 3.4 首次钝化

当前无活动钝化/结构且本根没有更高优先事件时，依次检查：

1. 已知非零逻辑色段；含本根后，真实同色柱count>=2。只有一根有色柱后加零仍不足；已够两根时允许零柱当天首次钝化。
2. TOP额外要求本根D>0；BOTTOM不增加D<0限制。
3. 真实同色历史B存在；当根C严格突破B的历史收盘价格，不得借本段以前某根的价格通过此门槛。未过B价格门槛不绕去A。
4. 先检查B：本轮没有击穿B，且本根C、D同时严格满足B资格。B不合格再检查A自身完整资格；当根C仍须同时越过B和A两个价格门槛，且本轮未击穿A。失败不检查第三个。
5. 选中参照后深复制保存，产生一次DULL/activation。同一根仅首次钝化，不继续在同根追加1%结构；根末更新previous为本根实际DIF。

此处B→A是已成事实的当根选择顺序。预测“先求B完整价格范围，只要有解就不计算A”的额外计算顺序另见§6，不能混为事实识别的全局价格扫描。

### 3.5 已有钝化的保持、消失及当根切远

已有钝化沿用原参照，不每天重新寻找DIF最强者，也不重复首次价格门槛。价格在旧谷上方或下方（顶部镜像）都可保持；原参照未被严格突破且未发生结构确认，就保持DULL，不每天再产生activation。

DULL仍在同一逻辑色段时：若原参照是B且本根严格突破B，取消前按§3.4的当根C/D、A未被本轮击穿、根数和最近价格门槛检查A。A完整合格则当根切A并保持DULL，不额外发CANCEL→DULL，不改写此前事件的参照。A不存在/不合格则当根CANCEL。A已作为活动参照时，不回切B、不查第三个。A下一根才合格不能删除本根消失事实。

同根切远只限已有DULL；首次激活、已有STRUCTURE及真实反色分支不调用此处理。既有STRUCTURE原参照被突破时直接CANCEL，不为保住结构临时换参照。已经严格突破的B不会因之后DIF回升重新成为可用参照。

### 3.6 结构形成、回转与优先级

在原参照仍有效、尚未真实反色时，以前一完成根实际DIF为P：gate=abs(P)*1.0/100，delta=s*(D−P)。必须保留原float计算顺序；不按参照DIF求1%，不累计多根小变化，不跳过零柱去找上一根有色柱。

| 进入本根前的状态 | 条件 | 当根结果 |
|---|---|---|
| DULL | P!=0，delta<0且−delta>=gate | STRUCTURE/dif_turn，进入结构形成考核期 |
| STRUCTURE | P!=0，delta>0且delta>=gate | 顶底统一DULL/dif_return，原活动参照继续有效 |
| DULL/STRUCTURE | 没到门槛、方向不符或P=0 | 原状态保持；P=0仅关闭这条1%途径，不关闭真实反色途径 |
| STRUCTURE | 原参照DIF本根严格被突破 | 直接CANCEL，不先产生DULL、不进入等待 |

达到原float运算得到的1%门槛包含等于，低于门槛保持。形成结构当天以及结构回转当天，都不重新要求C超过历史价格：它们基于已有钝化关系。顶部结构DIF向上回转、底部结构DIF向下回转达到1%，直接退回钝化；无论当根收盘是否还在首次价格门槛之外。价格单独突破本次结构所在段的高/低点，不能另外撤销尚未首次反色结构。

当前普通关系的处理顺序固定：先原参照DIF失效，再1%转折/回转。已有DULL的B→A检查在取消前；已有STRUCTURE不切远。当前普通关系当根产生CANCEL后，不能清空ref再落入首次激活分支，在同根补一条新DULL。§3.7旧结构价格消失属于另一份关系，不阻止当前新关系首次钝化或形成结构；两者同根事件全部保留，不事后删事件来凑终态；后端仅依§5.3设置显示标志。

### 3.7 首次反色起逐根比价及有效同色段结束

首次反色根仍先按原规则检查原DIF参照：严格突破则只按dif_break_on_flip消失，不建立FOLLOWING、不另加价格消失。未破时原STRUCTURE进入FOLLOWING，或原DULL按color_flip形成且FOLLOWING。复制反色前完整old_wave，反色根不进入originWave的任何极值。

**新进入FOLLOWING的记录在首次反色当根也执行一次价格检查。**所有仍有效跟踪根，不论柱色，TOP检查close>originWave.price，BOTTOM检查close<originWave.price；相等不触发，不加1%或原参照DIF条件。记录跟踪全程同方向收盘极值/日期；突破时CANCEL/structure_price_break和DISAPPEARED当根产生、清槽。不能为了保住新形成事实而拖到下一根检查。

每个方向的当前nextSameColorStart/count：真实同色首次出现设bar.time/1；同色续根count+1；零保持；真实反色且此前count=1，清None/0继续跟踪，并在该反色根照常比价。单根段不删除、不合并，仍正常进入普通历史池。真实反色且此前count>=structure_follow_min_bars(2)，先FINISHED并清槽，终止根在有效跟踪范围之外，不更新跟踪价格、不检查该根价格、不产生CANCEL。之后任何价格/远参照身份均不重开。

原段内1%考核、近远选择和当前普通state均不被旧结构修改。旧消失不能提前return或清新状态。新DULL/activation是否成立继续用同一根C/D、既定根数、双价格门槛及本轮参照未破；同根旧价格CANCEL+新同方向activation都保留，只在§5.3投影为旧事件不画、新钝化绘制。新钝化不成立则旧消失正常显示。

### 3.8 必须删除的现有实现及同步范围

底部STRUCTURE回转不再调用_qualifies_bottom_close/_start_rearm；正常计算不再创建WAITING、REACTIVATED、INVALIDATED或SEGMENT_ENDED等待记录，不存在“收盘重新低于旧谷才重新激活”的业务分支。

实现时须按引用清单成套清理等待专属类型、字段、snapshot解析、查询投影、预测条件、TS解码/说明及旧测试，不能只隐藏页面。只移除旧无限跨段historical_price_break途径；以§3.7有限范围的structure_price_break替代。原色段考核期仍不按价格单独撤销，禁止同时保留两套历史撤销政策；不删除通用恢复安全检查、完整原始数字校验、历史设计、原图和旧运行记录。

目标字段及身份已在§2、§4—7确定，后续按§11同批迁移正式类型、计算进度、查询/DTO/前端消费者、Spec/hash和缓存；禁止编码时另起同义字段。旧等待快照/旧规则缓存不能按新规则恢复，也不能加新旧双策略兼容。此前P3第1步仅完成修改前的识别及内部结果；本次有限跟踪和配套仍须落实。公开合同和消费者尚未迁完，不表示产品可上线。

### 3.9 保留规则、TODO与测试入口

保留：真实完成根；源收盘而非high/low；原始DIF而非柱高；相邻1%及前值0保护；零中性；最近两个历史同色段；首次同根只DULL；原参照和事件ID/时间关联；因果前缀/asOf/独立内存恢复；不改源SQL、数据库、Lake或鉴权。

TODO仅两项，等本需求完成后研究：①历史参照是否也必须至少两根；②首次TOP是否必须本根DIF>0。当前继续允许历史单根、保留TOP正DIF限制；不因这两个疑问扩大本轮规则变更。

§14逐条设计识别规则测试。正式实现前必须完成本节到§14的覆盖检查；任何算法输出或原截图均不能自动生成expected。人工规则样本与软件观察分开；本步实际执行结果及公开验收边界见§15。

### 3.10 编码方法及互斥执行顺序

| 方法 | 确定职责 |
|---|---|
| _start_structure / _finish_structure | 原形成事实及首次反色冻结；初始化count=0、跟踪极值None；进入FOLLOWING后由下面同一函数处理首次反色根，不另写比价公式 |
| _advance_followed_structure(bar, record) | 新增单记录纯推进函数，输入只读，返回最终深副本、至多一个价格CANCEL和实际检查记录；全部根数、正常结束、跟踪极值及严格比价只在此处实现 |
| _advance_followed_structures | 对根前两槽各调用单记录函数一次，将终态移槽；返回事件/结构更新，不碰普通状态。预测继续复用这一入口，不调用普通选峰 |
| _select_eligible_reference / _current_reference_qualifies / _rescue_dull_reference | 原B后A/近峰价格/正常首次及同根救援完整保留 |
| _validate_step / _publish | 校验根前旧跟踪及本根新进入FOLLOWING的记录都实际推进一次；核全部事件/最终记录和新计数字段后一次发布，错误不污染旧对象 |

固定执行顺序：

1. 校验完成根、时间升序和原数字，深复制有界进度，保存根前wave/state/ref/active，建立观察上下文。
2. 先推进根前旧跟踪：若当前候选已至少2根且本根真实反色，FINISHED、保留原起点/根数/极值并清槽，跳过价格检查。否则按本根颜色更新候选起点/根数（单根结束可清空），随后更新跟踪极值，严格比原段价格；突破则DISAPPEARED/CANCEL清槽，不突破保留。TOP/BOTTOM独立。
3. 按原顺序处理当前普通关系。真实反色时先原ref严格突破；未破则原STRUCTURE转FOLLOWING或原DULL按color_flip创建。每份本根刚进入FOLLOWING的记录，立即调用同一单记录函数一次：firstOppositeAt==bar.time，候选仍None/0，但跟踪极值首次取本根C并做价格检查。若形成与价格消失同根，先形成事件再价格CANCEL，结构仅保留最终DISAPPEARED；不得为此重复形成或发两份同id记录。
4. 同色/零按原规则更新wave并执行原参照破、DULL救A及1%转折/回转，NONE才按正常资格首次DULL；首次DULL不继续同根形成结构。本轮不改这些分支。
5. 按顺序合并全部事件：根前旧跟踪事件在前，当前普通关系事件及其本根新FOLLOWING价格事件在后。同根结构更新按id收敛为最终值；若新FOLLOWING仍有效才装入已清的方向空槽，不覆盖活旧槽。旧跟踪事件不清当前新state。
6. 更新previous/processed；完整校验普通关系、跟踪槽、事件、结构、极值/根数和真实编号，再一次_publish；finally清观察上下文。异常只丢候选work，不修改self、来件、已返回对象或已发布entry。

本轮跟踪记录可每根因根数或极值变化产生更新；这不增加业务事件。原priceExtreme/At、originWave及firstOppositeAt已经确定后不可改；nextSameColorStart/count可以按单根跳过规则重置，不能沿用“一经设置永不改变”的旧校验。

#### 3.10.1 完整step校验及同根事件次序

_validate_step先从根前followed两槽推导旧组的预期事件/最终更新，并逐项验证前缀；不能将所有structure_price_break一律剔除后按“普通最多一个”通过。剩余当前关系分成原普通状态事件（至多一项）和本根首次反色后的价格CANCEL（至多一项）。额外价格CANCEL只允许关联根前active结构或本根color_flip新形成结构，必须首次反色==本根、原参照未破、实际收盘严格突破originWave最终价格，并精确对应同id DISAPPEARED终态。其他额外事件、错id、未突破、重复CANCEL或漏最终记录均拒绝。

顺序固定为：根前旧跟踪产生的价格事件（按TOP/BOTTOM既定顺序），随后原普通状态事件，最后本根刚首次反色的结构价格事件。RC105必须接受STRUCTURE/color_flip→CANCEL/structure_price_break，不能被现有“所有价格事件必须在普通事件之前”的内部响应检查拦截。已有STRUCTURE首次反色直接破价时，当前组只有价格CANCEL，无需伪造新形成事件。当前关系的fromState仍按根前普通状态核；本根价格CANCEL的fromState=STRUCTURE描述结构对象，不受根前DULL/NONE的限制。

result.structures按id只保留本根最终记录。允许新color_flip直接返回最终DISAPPEARED，但形成事实必须由其STRUCTURE事件及完整原段证实；不能先放一份FOLLOWING再放同id DISAPPEARED。旧结构更新、新结构更新及最终槽分别核验，不以完整集合len==1替代。原形成事实不可改，允许推进字段明确包括status/originWave/firstOppositeAt/nextSameColorStart/nextSameColorCount/trackingPriceExtreme/trackingPriceExtremeAt/trackingEndedAt/disappearedAt/disappearanceReason，并逐字段依§3.7和§4验证真实推进；不能仅把它们放入白名单便跳过规则。


### 3.11 独立跟踪分支完整性

| FOLLOWING根前进度/本根 | 结果 |
|---|---|
| start=None/count0，反色或0 | 不启动同色候选，但检查价格；可能当根消失 |
| start=None/count0，真实同色 | 设置start/1，检查价格；第一根即可消失 |
| start非空，当前同色或0 | 同色增count、零不增；检查价格 |
| count1后真实反色 | 清start/count为None/0，继续跟踪且本根比价；不能FINISHED |
| count>=2后真实反色 | 正常FINISHED，本根不更新跟踪极值/不比价，不报消失 |
| 本根刚首次反色并进入FOLLOWING | count0/startNone，首次记录跟踪极值并检查价格；原ref已破者不进入这条分支 |
| FINISHED/DISAPPEARED | 槽已清，不复开、不重复消失，不因画面隐藏继续保留 |

普通结构回转对应原记录ASSESSING→DISAPPEARED/dif_return、普通状态回DULL，不产生WAIT。本显示特例只匹配后续价格CANCEL+新activation，不能把所有DULL或所有CANCEL都隐藏。

### 3.12 识别核心开发的强制检查

逐条核对§2—4与§14：不借前根价格首次；原段曾破DIF不恢复；1%原运算不改；反色根排除旧极值；首次反色起在有效跟踪范围逐根按完整原Wave价格撤销；单根段不停止，首个有效同色段结束正常停止不报消失；一根即可撤销与新钝化至少两根不得混淆；零柱起止正确；旧新事件可同根独立；只有FINISHED/DISAPPEARED为终态。禁止保留“首次反色后永久不可消失”的隐含断言。

恢复/查询/schema/预测必须同批满足本规则，不能仅改step让后续聚合仍拒绝FOLLOWING→DISAPPEARED。本次前两步的内部类型/恢复/聚合/预测消费者和双Spec须先完成修正，并通过回归/专项对比review，才进入P3第3步；公开模型和HTTP在第3步迁移，TS及必要调用在第4步迁移。全部消费者迁完并验收前禁止发布，不能把第3、4步的工作倒写成第3步开工前置。

## 4. 计算进度、结构结果、历史查询与缓存

### 4.1 快照与先校验后替换

snapshot根字段仍specHash/tsCode/period/sourceIdentity/processed/wave/history/state/reference/previous/activeStructure/followedStructures；两槽每项None或§2.3完整FOLLOWING新记录，无历史全集/磁盘恢复。旧身份、缺新增字段、额外旧字段均拒绝，不补值兼容。先独立解析→共享完整校验→一次替换self；失败来件/self/旧输出不变。

通用数字/日期/历史池/活动参照校验保持，跟踪校验在普通NONE/DULL提前返回之前：

- ASSESSING没有firstOpposite/originWave/跟踪价格，start=None/count0；两followed槽只允许FOLLOWING，无终态、无重复id、无与active同id。
- originWave与方向/原段/形成事实一致、end<firstOppositeAt，已经冻结不得改。**不再要求它必须是当前同向历史池最后一段。**后续单根段照常进入最多两段历史池，原段可更远或已被淘汰，不因此拒绝合法跟踪；不增加候选池容量或复制全部经过的单根段。
- 当前同色候选start非空时，必须等于当前wave.start、方向相同、count==wave.count且>0；startNone时count恰0、当前wave为相反方向。零沿已知逻辑wave。start晚于firstOpposite；跳过单根后允许重新填写。保留的已结束同向Wave若在原段之后且有色根数>=2，则旧记录不应仍FOLLOWING，拒绝。
- 能由当前/最近已保存Wave核对的firstOpposite时点、方向和原段必须精确相符；原始分隔段尚在池中时，不能把其第二根伪造为首次反色。其已被合法淘汰时，以冻结originWave/首次反色及新跟踪字段的日期/方向关系校验，不能为补历史重新读源或误拒正常进度。
- trackingPriceExtreme及日期在FOLLOWING必须均非空、有限正价、firstOppositeAt<=发生位置<=previous.time；TOP不得低于当前close，BOTTOM不得高于当前close；若发生于previous.time须与close相等。TOP要求极值<=originWave.price，BOTTOM要求>=，严格越过即表明曾应消失，不得因末根回撤恢复。**分隔反色段和零柱同样适用此检查，不能用当前反色Wave的另一方向极值代替全程同方向跟踪极值。**等号合法。
- id/完整字段/严格int（bool拒绝）、未来日期、错原Wave、错方向和坏数值均按同一共享校验拒绝；合法单根跳过、原段淘汰、普通NONE仍有旧跟踪等正例必须通过。新字段同样进入clone、step最终发布前及内部模型校验。

### 4.2 结构校验、聚合与asOf

validate_structure_facts、validate_structure_record和InternalXxmStructureDto共用§2.3形状/生命周期检查，编号仍由真实身份核验，不用伪id函数。原参照六字段、形成极值、最终原Wave及日期保持原严格规则。

- FINISHED必须有首个有效同色段start、count>=2、结束时点晚于该start，跟踪极值日期严格早于正常结束根、极值未破门槛，无消失字段。
- DISAPPEARED的结束=消失时点。原段内dif_return/reference_dif_break仍无首次反色、原Wave或跟踪极值，startNone/count0。structure_price_break有首次反色/originWave/跟踪极值，极值严格越门槛且发生于消失根；**允许startNone/count0**，因为可以在分隔段、首次反色根或其零柱消失。
- color_flip形成根==firstOppositeAt，原段所有日期严格在此前；若同根价格突破，允许formedAt==disappearedAt==trackingEndedAt，原因必须structure_price_break。dif_turn原段形成仍不得同根消失，不放宽其他非法时间关系。

_merge_structure_updates新签名为(entry, step: XxmStep, *, bar: XxmBar)，调用方传同次step及实际bar，不再只传updates/through字符串；函数读取step.structures/events，不重跑核心，在候选entry内按§3.10核变化：形成字段/已冻结origin/firstOpposite固定；候选根数同色+1、零不动、仅count1且真实反色可清起点/根数；count>=2且反色只FINISHED。跟踪价格按同方向极值单调推进，新的极值日期只能bar.time，相等保留首次日期。首次进入跟踪写本根C；正常FINISHED不纳入结束根C。每根同id至多一份最终记录，终态不可更新；color_flip同根形成并价格消失允许新id直接最终DISAPPEARED，但须有对应形成/CANCEL两事件。根前与当前计算字段不能由聚合猜测。失败整个候选entry丢弃，旧缓存不变。

**历史asOf改为先取得一次真实前缀进度，再投影，不能只抹除最新记录的未来日期。**因为单根起点可以重置、计数及跟踪极值会推进，光清空未来字段不能恢复过去的值。_response先算end_index，再只调用一次entry.calculator_at(end_index, check)，由当时active_structure及followed_structures建立id映射；_project_structure(record, through, prefix_records)按下表取值，不逐结构或逐天重放、不增加日志/检查点频率/源读取。

| 最新聚合记录与through关系 | 返回依据 |
|---|---|
| formedAt>through | 不返回 |
| 终结时间为空或晚于through | 必须在当时前缀的active/followed映射中有同id，用其整份记录深副本，包含当时起点/count/跟踪极值；缺失即失败，不从最新值填猜 |
| 终结时间<=through | 使用已冻结终态深副本，所有事实已在through前发生 |

在窗口过滤之前校验全部投影记录及id集合，与同一次前缀active/followed精确一致，再按引用、窗口内变化或有效时间覆盖窗口筛选。保留§4.2.1，无事件窗口、正常结束当天、形成与消失同根均不能遗漏；空窗口不隐藏错误，过期无关记录不全量附带。普通不序列化结构集合，debug才返回。先前返回对象、形成事实和同源较早查询不被后续更新改变。

### 4.2.1 响应窗口与结构集合

选择points和events只看真实响应窗口，事件全集不因显示隐藏而删。结构先按§4.2取得真实through投影，再保留：窗口内point/event引用、形成/首次反色/当前同色起点/结束/消失时点落窗内、或其有效存续时间覆盖窗口的记录。正常结束根有debug结构但无假消失，之后无引用/无变化的过期结构不附带；无事件FOLLOWING窄窗口也需可查。第3步普通/debug投影和第4步TS关联均按RC93及新增RC103/104的独立预期验收。

### 4.3 来源、缓存与预算

同一次来源读取供识别/预测/普通/debug复用，禁止为有限跟踪再次读行情或查库补极值；最终原Wave由该次逐根计算已有事实提供。当前规则新hash和预测新hash必须同时进入身份/缓存键，修补前识别v0.3/预测v0.5及其他旧身份的缓存/内存副本拒绝并从同源重算，无兼容开关。

来源修订时从空重建完整entry；不能将修订后的形成/原Wave合并进旧entry，也不能因旧终态不可改写而拒绝合法新来源。正常追加在候选副本里推进calculator、聚合所有结构、校验完整模型，全部成功才一次替换；失败不污染已有entry和早先返回对象。只保持有界进度加查询结果，不新增持久化或恢复文件。资源沿§9，同一400ms产品预测预算必须包含最多两份旧结构的检查/求解/验证，不拿专项1GiB/100MiB替代产品预算。

## 5. HTTP、内部模型及普通/debug响应的完整交接

### 5.1 文件、方法和调用顺序

修改既有`src/biz/schemas/wealth/market/index_detail_xxm.py`及`index_detail_xxm_forecast.py`，保留通用数值/时间/引用/表达式检查，等待专属部分按§3.8清退并改为结构考核/首次反色事实检查；完整模型统一改名为`InternalXxm*`和`InternalForecast*`，不把已有模型先删成公开最小字段。特别是query当前按`XxmPointDto.model_fields`挑字段，必须同步改用内部类型，否则历史ID会在完整校验之前丢失。

在`src/biz/services/wealth/market/index_detail_xxm/response_projection.py`新增两个纯函数：

- `project_xxm_response(internal: InternalXxmResponseDto, *, debug: bool) -> XxmResponseDto | XxmDebugResponseDto`。
- `project_forecast_response(internal: InternalForecastResponseDto, *, debug: bool) -> ForecastResponseDto | ForecastDebugResponseDto`。

每个公开嵌套类型均封闭字段集合，Pydantic沿现`extra='forbid', allow_inf_nan=False`；数值字段在解析前检查`type(value) in (int, float)`（整数计数严格int），拒绝bool/字符串数字/NaN/无穷，同时允许101这样的合法int价格；禁止用`Any`、任意dict透传内部结果。普通模型没有`debug`字段；debug扩展模型的`debug`必填且非None。根模型使用两种模型的联合，不用`exclude_none=True`省略全部None，因为合法必有的空时间、空方向和参照空值仍须返回。

识别query `build(session, *, period, start_date, end_date, limit, debug=False, now=None) -> bytes`；预判query `build`保留现业务参数，新增同样`debug=False`，也返回bytes。按§11第3—4步同步运行时直接调用方、直接读取DTO字段的消费者及本批API/验收测试，接口发送bytes，测试按新公开模型解析；不留旧DTO返回兼容。§11.2.6列明的P4保留工具在P3不运行、不作为通过依据，P4使用前按§11.2.3—4整体迁移；P5待删旧运行器不因本次返回变化提前修改或清退。流程固定：

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

[日线合同§10](index-detail-api-contract-v1.md)、[分钟合同§8](index-detail-minutes-api-contract-v1.md)和[预测目标§36](index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md)已同步本目标入口。完整字段唯一由本节规定，实施必须同步所有消费者；文书一致不能替代运行模型与HTTP验收。**任何字段、版本、空值或错误语义不一致，必须先修正文档再编码，不允许在实现中任选一套。**

### 5.3 识别内部、普通与debug字段（新目标完整集合）

`InternalXxmResponseDto`根为tsCode/period/algorithmVersion/specHash/source/points/events/structures/meta/dataStatus。source保留内部inputId，其余沿普通source。内部point、event及Structure字段精确见§2.3；普通/debug都先校验这个完整内部模型，再投影。新schema不接受旧历史或等待字段，不按现旧`XxmPointDto.model_fields`过滤内部点。

| 类型 | 必有字段及类型 |
|---|---|
| XxmResponseDto | tsCode='000001.SH'；period=day/m60/m90/m120；algorithmVersion='xxm-direction-v0.4-r4'；specHash=新MAIN_SPEC真实hash；source/points/events/meta/dataStatus |
| XxmSourceDto | kind=daily_factor/minute_gold；startTime/computedThrough为本周期time或None；initialHistoryIncomplete严格boolean；indicatorVersion严格int或None（日线None）；无inputId |
| XxmPointDto | time；close正有限number；dif/dea/hist有限number；ordinaryState=NONE/DULL/STRUCTURE；ordinaryDirection=TOP/BOTTOM/None |
| XxmEventDto | id非空string；time；direction=TOP/BOTTOM；type=DULL/STRUCTURE/CANCEL；displayOnChart必填严格boolean（无默认值） |
| XxmMetaDto | count严格int>=0；responseStart/responseEnd为time或None |
| XxmDataStatusDto | status=READY/DELAYED/EMPTY；message=string或None；asOf=time或None |
| XxmDebugResponseDto | 上述全部普通字段，加必填非None的debug |
| XxmDebugDto | sourceInputId:string；points[]；events[]；structures[]；无完整decision |
| debug.points[] | time；activeReference=Reference或None；activeStructureId=string或None |
| debug.events[] | id；route；fromState=NONE/DULL/STRUCTURE；eventReference=Reference；relatedStructureId=string或None |
| Reference | startTime/endTime；price正有限number；dif有限number；priceAt/difAt为段内time；六字段全部必有 |
| debug.structures[] | §2.3完整记录，含原形成极值、originWave最终极值、首次反色/下一同色段/结束日期；originWave公开类型为XxmWaveDto或None；不格式化、不补值 |
| XxmWaveDto | 精确sign/start/end/count/price/dif/priceAt/difAt八字段；sign为±1严格int，count为正严格int，price正有限、dif有限，极值日期位于start至end；时间遵循本周期 |

route允许activation/dif_turn/dif_return/color_flip/dif_break/dif_break_on_flip/structure_price_break，按§2.3匹配类型及关联。普通事件仍仅DULL/STRUCTURE/CANCEL；不恢复旧RESEARCH_HISTORICAL_WITHDRAWAL或底部等待。CANCEL/structure_price_break必须关联有效跟踪范围内的旧结构，允许尚无下一同色起点、首次反色当根或color_flip形成同根；fromState=STRUCTURE对应旧对象，不以本根ordinaryState作唯一校验。原有当前关系事件仍按原状态校验。

内部originWave沿XxmWaveFacts原八字段，其中price_at/dif_at用于Python内存及内部模型；公开debug投影显式映射成XxmWaveDto的priceAt/difAt，其余六字段原值复制。识别debug.structures及预测debug.structureFollowConditions共用这一映射，不在公开对象同时返回两种拼写，也不直接透传dataclass/asdict。

严格身份/数值/日期/source/meta检查后，分别验证普通关系、根前旧结构事件和本根首次反色的价格事件，再核六字段参照与双向关联。事件先后按§3.10.1，不能保留“所有价格事件必须先于普通事件”的旧断言。debug.events与普通events逐项同序且全部保留，同根多个不同id合法。结构按formedAt/id唯一排序，最新状态与查询asOf一致；普通仍不带debug，不用空辅助集合假装未加载。历史引用及未来字段规则严格按§4.2。前端只消费事实，不自己用价格重算旧结构是否消失。


#### 5.3.1 同根显示选择与完整事实

在已计划response_projection.py增加纯函数event_display_flags(events)->dict[id,bool]，输入是已经完整内部校验的所有事件，不读取行情、不重跑计算器。先收集route=activation且type=DULL的(time,direction)；仅CANCEL/structure_price_break且同键有新activation者标False，其余均True。不能把DULL/dif_return当新首次钝化，也不能把不同方向/日期或普通dif_break取消吞掉。

project_xxm_response将该结果作为每项普通event的displayOnChart；debug根包含同一events和标志，debug.events仍逐id保留全部route/关联。完整事件顺序、编号、旧结构DISAPPEARED和当根清槽不变。normal/debug对相同内部结果的全部公共字段一致；false不表示事件没发生，下一根不得补报。

公开模型校验displayOnChart必须严格bool，不能省略、null、0/1或字符串；False只能用于type=CANCEL且同time/direction存在可显示DULL的项。debug再凭完整route复核精确规则；正常投影生成前已由内部事件作同一校验。前端不通过猜route补标志、不自行从计算事件删除记录。

该标志仅用于图表标记和普通当根事件列表；debug事实详情仍可列明旧结构已结束。它不进入内部step、snapshot或预测数学条件，不改变事件id，也不新增用户开关。第3步加入正式公开合同及测试，第4步同步全部TS消费者；不能在旧前端协议里临时塞字段。

### 5.4 下一根预测目标合同（待实施）

本节与§6同批实施。沿既有预测URL、标的/周期/asOf/鉴权和debug请求规则，不新增预测入口。目标只下一根；旧20步、等待和结构形成即停算格式不兼容。以下明确的是待实现目标，不是当前运行响应。

`InternalForecastResponseDto`完整根为下文全部普通根字段，加sourceInputId/calendarInputId/precisionPolicy/references/selectedReference/nearestDecision/farEvaluated/conditions/precisionRanges/structureFollowConditions十项内部事实；内部不加debug嵌套。`project_forecast_response`先校验此完整集合，普通显式复制公共字段，debug再把这十项组为debug对象；只生成一次display和forecastId。缓存保存这个完整内部对象，不保存普通删减结果。

#### 5.4.1 普通响应完整字段

普通根字段精确为下表；`debug`缺省不存在，不返回null或空对象。普通card只消费后端生成的最终display，不自行反求边界或组合debug条件。

| 字段 | 类型/固定值 | 空值与校验 |
|---|---|---|
| tsCode | `000001.SH` | 不可空 |
| period | day/m60/m90/m120 | 不可空 |
| forecastVersion | `xxm-key-point-forecast-v0.6-r4` | 不接受旧r2或20步版本 |
| forecastSpecHash | 实际FORECAST_SPEC hash | 与当次正式构建一致，不手编 |
| detectorSpecHash | 修订后`xxm-direction-v0.4-r4` Spec hash | 必须与实际识别结果身份一致 |
| computedThrough | 当前正式来源前缀最后完成时点 | EMPTY为null，其余必须有；日线日期/分钟+08:00同原规则 |
| requestedAsOf | 请求的已完成时点或null | LATEST为null，REPLAY必须合法且不晚于可完成时点 |
| mode | LATEST/REPLAY | 与requestedAsOf对应 |
| dataStatus | READY/DELAYED/EMPTY | 来源事实，与预测是否有条件分开 |
| ordinaryState | NONE/DULL/STRUCTURE或null | EMPTY为null；其余为当前真实r4状态，不是下一根假设终态 |
| direction | TOP/BOTTOM或null | 从当前逻辑色段；开头全零/EMPTY为null，逻辑零日不清方向 |
| targetEndpoint | 唯一下一个本周期交易端点或null | 尚未进入求解、校准失败、EMPTY/DELAYED/静态无可能时为null；进入求解后无论有解/真无解/精度未决均保留此实际端点 |
| barsAhead | `1`或null | targetEndpoint非null只能1，否则null；不允许2—20 |
| status | READY/NO_CANDIDATE/PRECISION_PENDING/DELAYED/EMPTY | 关系见下表 |
| reasonCode | null或既有适用原因 | 见下表，不返回NO_CONFIRMATION_IN_HORIZON或NON_FINITE_PROJECTION |
| forecastId | 稳定结果身份 | 来自规则、来源前缀、周期/asOf、日历及完整内部求解事实；不包含debug开关，同前缀普通/debug相同 |
| display | 固定4字符串字段 | statusLabel/targetText/conditionsText/asOfText；沿现`ForecastDisplayDto`字段名，不另造conditionLines |
| applicabilityText | 非空中文字符串 | 说明只适用下一根完成收盘、原EMA每步有限、近远计算范围；必要限定不藏debug |
| invalidationText | 非空中文字符串 | 新完成数据后重算；零不自动使条件失效，旧结构在首次反色起至首个有效同色段结束的范围内继续判断，单根段不终止；B未算A不能写成总体钝化消失 |
| refreshAfterMs | 60000 | 原刷新规则 |

旧`confirmedAt/confirmedDirection/rearmContext/nextBarOutcomes/activation/assumption/targetEntryRanges/targetEntryExclusions/relations/commonConditions/examples/precisionPolicy/sourceInputId/calendarInputId`均不再为普通字段。仍需要的来源、精度、数学和条件信息只在下述debug固定集合；删旧字段的Python/TS/adapter/fixtures同步，不以null或空数组保兼容。

#### 5.4.2 status、reason及显示关系

| status | 必须满足 | reasonCode | 普通显示 |
|---|---|---|---|
| EMPTY | dataStatus=EMPTY，状态/方向/target/barsAhead为null | SOURCE_EMPTY | 暂无完成行情，不显示假设点位 |
| DELAYED | dataStatus=DELAYED，保留实际computedThrough/状态，target/barsAhead为null | SOURCE_DELAYED | 来源滞后，不用旧行情冒充最新预判 |
| NO_CANDIDATE | dataStatus=READY；当前普通关系和全部有效旧结构均静态无可能，或已完整求解且两类都没有确定范围和未决价段，具体限定见下文 | ZERO_WAVE/NO_REFERENCE/NO_ENTRY_RANGE | 后端说明具体无可能原因；不能用今天价格没创新低作为明天无可能依据 |
| PRECISION_PENDING | dataStatus=READY；校准失败，或没有任何确定可用条件范围、仅剩来源/原运算未决段 | CALIBRATION_FAILED/ROUNDING_BOUNDARY | 明确条件尚不能确定；不能把未决范围写成无解或确定标签 |
| READY | dataStatus=READY；至少有一个确定可用条件范围；target非null/barsAhead=1。允许另有窄临界未决段，但不得影响已给范围的成立或近优先选择 | null或ROUNDING_BOUNDARY | 只展示已证明范围；另有未决段必须在必要文字说明，不将未决段算无解；既有结构不是直接CONFIRMED |

`NO_CANDIDATE`静态结束时没有target；已进入求解后真无解仍保留target和barsAhead=1。校准在未来端点读取前失败时target为null；边界求解未决时target非null。无合法整数不是数学未知或无解：有确定范围时status仍READY、reason按是否另有未决段为null或ROUNDING_BOUNDARY，普通写“已算出条件范围，暂未生成可用整数点位”，debug保留精确范围。不能因无整数启用A。

近远资格仍未确定时，仅已证明某些价格会让B失效，不能据此把普通关系升级READY；若另有§6.12独立旧结构确定条件，可仅凭该独立条件READY并保留普通关系未决说明。没有旧结构确定条件时不能据此把整个结果升级READY：如果B是否还有有效关系仅剩未决，则保持PRECISION_PENDING且A不算。已有STRUCTURE固定参照，不存在这项近远选择未决；其明确保持、回钝化、消失或首次反色条件均可正常READY。

上述“没有范围”只限定NONE的首次搜索，以及DULL/B已确认没有有效延续、转求A救援的调度。后者若A不存在、已被本轮DIF突破，或已求A而救援范围确定为空且无未决，则NO_CANDIDATE/NO_ENTRY_RANGE，普通关系conditions和precisionRanges为空；仍须计算§6.12旧结构独立条件，再合成最终status，不能提前NO_CANDIDATE；已求解的target/barsAhead保留，nearestDecision及selectedReference/farEvaluated按实际执行填写。普通文字明确“近参照没有有效延续范围；远参照不存在/已失效/没有救援范围”，不能解释为当前真实钝化已经消失，也不把B失效范围拼回A条件。**活动参照本来就是A、或当前已有STRUCTURE时不适用这个退出口径**：固定原参照的明确消失条件也是可用结果，不能因无保持范围而抹掉。

普通display由同一个内部结果一次生成。已有DULL/B且B有解时，A完全不算；B突破的条件必须写“近参照失效，远参照本次未计算，真实收盘按r4同根规则检查”，不得输出“钝化必定消失”。STRUCTURE/R原参照突破则可明确结构直接消失；活动A被突破可明确钝化消失。必要限定不能仅依赖debug字段。

#### 5.4.3 debug精确字段及条件事实

`debug=1`在相同普通根字段外恰好增加debug对象：

| 字段 | 类型及含义 |
|---|---|
| sourceInputId | 当前正式来源前缀指纹或null；EMPTY为null |
| calendarInputId | 本次实际下一端点日历身份或null；未请求未来日历时null |
| precisionPolicy | day=`rounded3_guarded`，分钟=`full_float` |
| references | `{nearest: Reference\|null, farther: Reference\|null}`；完整参照沿统一Reference字段，含priceAt/difAt，来自当前逻辑方向历史池；不造第三个 |
| selectedReference | `NEAR`/`FAR`或null；实际进入某参照求解才填，静态/校准前结束null；已有活动A只能FAR |
| nearestDecision | `{status, reason}`；status为NOT_EVALUATED/UNAVAILABLE/HAS_RANGE/NO_RANGE/UNCERTAIN；reason为后端非空中文或null，描述实际执行检查，不把没算写成无解 |
| farEvaluated | bool；仅实际执行A条件求解时true。B有确定有效关系范围或未决关系段必须false；不存在A或静态拦截不能写true |
| conditions | 下列Condition数组；未求解/无条件则[]；按固定outcome顺序输出，同一种普通关系outcome仅一项、其范围升序不重叠；旧结构条件按独立集合关联对象，不与普通关系合并 |
| precisionRanges | `[{priceRange, reason}]`；其中priceRange恰为lower/upper/lowerInclusive/upperInclusive四字段，不给未决段生成display整数；reason沿ROUNDING_BOUNDARY；只保留未决临界段，不能声称这是全正价格空间的最终状态分割。无未决则[] |
| structureFollowConditions | 旧结构下一根价格失效条件数组；完整字段及排序见§6.12。普通响应不带此集合，debug和内部必有，未产生条件时[] |

`Condition`精确字段为`{id, outcome, referenceRole, priceRanges, predicates}`。referenceRole为NEAR/FAR且与selectedReference相同。priceRanges使用`{lower,upper,lowerInclusive,upperInclusive,displayLower,displayUpper}`：内部lower有限且>=0、upper有限或null（无有限上界）；C=0永远排除；displayLower/Upper为合法整数或null，无整数时两者null；已有无上界范围的displayUpper=null、displayLower为合法整数，这不等于无整数。不能用显示值代替内部开闭。

`outcome`固定为：DULL_FORMED、DULL_HELD、STRUCTURE_FORMED、STRUCTURE_HELD、RETURNED_TO_DULL、STRUCTURE_FORMED_AND_FOLLOWING、STRUCTURE_FOLLOWING、STRUCTURE_PRICE_DISAPPEARED、SIGNAL_DISAPPEARED、REFERENCE_INVALIDATED。这是下一根“在给定收盘条件下发生什么”的debug事实，不新增ordinaryState或普通事件类型。

- NONE只允许DULL_FORMED，不允许首次同根STRUCTURE。
- DULL允许保持、形成、形成并首次反色；原参照A破可SIGNAL_DISAPPEARED。原参照B破且A未计算时仅REFERENCE_INVALIDATED；真实翻色B破不救远，可SIGNAL_DISAPPEARED。
- STRUCTURE允许保持、RETURNED_TO_DULL、首次反色、SIGNAL_DISAPPEARED；不走远救援。
- 旧结构不作为普通conditions的reference；其下一根价格失效条件必须放入独立structureFollowConditions，按原结构id关联，不能省略或混入NEAR/FAR。

`predicates`是同一参照范围的必要比较数组，复用现ConditionDto的left/op/right表达式语义，但MACD表达式收敛到固定一步`{op:'macd',e12,e26,dea,field}`；field仅dif/hist，原运算顺序固定，不接受prefixBars/prefixClose/target及变量P。其余仅允许现affine的两种固定形式：常数{pCoefficient:0,cCoefficient:0,constant:k}和当根价格C{pCoefficient:0,cCoefficient:1,constant:0}，以及round3/sub/scale/abs。必须拒绝非零pCoefficient、其他cCoefficient及多步MACD字段；不另造literal节点，不由前端推算C条件。相同来源绑定必须一致。条件是完整规则的数学说明，前端只校验/展示，不负责判别或求界。

普通Condition id由同次forecastId和outcome生成；旧结构条件id另含relatedStructureId，见§6.12。两者均不依赖debug、窗口或显示小数位。forecastId先由不含debug及所有条件id的完整内部事实生成，再映射各条件id，避免相互引用生成身份。所有数字有限、引用与当前参照一致、日期/周期一致；限定窗口需更早参照仍完整带齐。内部/公开范围共用校验：lower有限>=0且0必开，upper有限或None，None必开；有限单点必须正数且两端闭合，倒置/空范围拒绝。每项priceRanges升序不重叠；同一普通关系的确定区间与自身precisionRanges不得重叠；同一旧结构的确定区间与该项precisionRanges也不得重叠。不同对象的区间允许重叠，例如同价位既可让旧结构消失又可让新钝化形成；不得跨普通关系/不同relatedStructureId套互斥检查。普通关系内部不同outcome互斥性按§6.4完整条件核验，不要求所有正float都被覆盖。总响应仍≤32KiB，超限整份失败，不截断条件或关联。

#### 5.4.4 可人工核算的一步数学样本

以下只验证求解/识别数学，不冒充recover_projection对真实源的250根校准。每组计算器从空输入固定(C,D,H)，DEA按D−H/2字面给定；ProjectionState也独立字面给定。日期使用§14固定t1…t7，不使用旧测试中的非交易日日期。

**M1：底部已钝化，下一根合法零和结构。**

输入：`(100,−60,−2);(110,0,2);(90,−50,−2);(100,0,2);(89,−15,−30);(88,−14,−28)`。t6已有底部钝化，近B价90/D−50，远A价100/D−60，当前count=2，P=−14、DEA=0。独立投影字面`e12=13,e26=27,dea=0`。

原一步：D(C)理想式=`−14+28*C/351`；H(C)=1.6*D(C)。C=175.5时原计算两EMA均38，D=0、DEA=0、H=0；count不加、未反色、原参照未破，相邻DIF−14→0达到1%，故t7形成尚未首次反色底部结构。不能因零柱RESET或反根偏移排除该点。

分钟理想结构形成下界D>=−13.86，故C>=1.755；同色/零要求D<=0，故C<=175.5；即理想闭范围[1.755,175.5]，实际范围以原顺序/误差证明确定边界，不把理想式直接当原float证明。C=1.75不足1%，C=2明显超过1%应结构；C=176真实翻红且有效，应形成且首次反色。显示整数端点须原step复核。

**M2：顶部镜像合法零。**

按(C,D,H)→(200−C,−D,−H)变换M1，得到完整6根`(100,60,2);(90,0,−2);(110,50,2);(100,0,−2);(111,15,30);(112,14,28)`，ProjectionState=`(187,173,0)`。t6顶部钝化，B价110/D50，P=14；C24.5时两EMA均162、D/H均0，t7走相邻1%形成尚未首次反色顶部结构；C24真实翻绿则形成并首次反色。两组仅是有限原运算正反例，不从运行输出生成expected。

**M3：下一根首次钝化，不继续猜第二根结构。**

完整输入`(70,10,2);(90,0,−2);(100,2,8)`，t3当前红count1、无钝化，B价70/D10。ProjectionState=`(102,100,−2)`；下一根D理想式`(28*C−2206)/351`，首次要求C>70、0<D<10以及H>=0。H=1.6*(D+2)，D>0已保证正红，下一根count2。因此理想首次范围`(1103/14,1429/7)`，C100原计算可明确首次钝化；即使相邻转折另有情况，本根只DULL，不能报告未来第二根结构或旧CONDITIONAL_ENTRY。日线使用各自source_options后重定临界归属，不照搬分钟开闭。

**M4：近仍可能则不算远。**

取M1前缀和投影，B的正常结构范围已非空。将A求解替身设置为一调用即抛错；求解仍正常给B条件。即使存在某些假设使B失效，本次也不能因此触发A；REFERENCE_INVALIDATED限定文字要与真实完成K线可能当根救A同时成立。

**M5：回转与直接失效的纯规则核验。**

顶部从§14 `TS`完整输入开始，P=99、当前尚未首次反色结构B价100/D200；独立ProjectionState=`(10099,10000,98)`，与前DIF99/DEA98相符。理想D(C)=`(28*C−250597)/351`。分别用三个独立整数C：10204得到D=35115/351≈100.0427，向上回转超过0.99且未破200，应回钝化；10197得到D=34919/351≈99.4843，回转小于0.99，应保持结构；11470得到D=70563/351≈201.0342，严格破200，应结构直接消失。H=1.6*(D−98)均正，不走反色。

底部从§14 `BS`完整输入开始，P=−99、结构B价100/D−200；独立ProjectionState=`(9901,10000,−98)`。理想D(C)=`(28*C−309403)/351`。C9796得到−35115/351，应回钝化；C9803得到−34919/351，应保持结构；C8530得到−70563/351，应直接消失。H=1.6*(D+98)均负，不走反色。所有C均有限且正，价格不再限制已有结构回转。分钟以原投影验证上述远离边界的期望；日线三位来源后分类相同。精确1%和临界开闭另由RC46/47及PF门槛测试证明，不用这些非临界数冒充等号覆盖。

### 5.5 最小样例、错误及迁移对账

新fixture用§14独立输入/预期构造，身份参数必须显式传入同次实际生成的hash，禁止用旧JSON换hash冒充新模型。普通READY有事件/无事件、EMPTY、DELAYED及debug同公共字段各准备字面样本；debug含同段反复结构、同根翻色首次反色、窗口外形成/窗口内失效、历史point引用如今已首次反色记录和早asOf还原样本。

EMPTY识别points/events为空、meta.count=0及首末None；debug对应数组为空，无伪造历史。DELAYED保留真实可用根和截至时间，不能补行情。前三条API非法debug/日期400、不支持标的404、源/模型或一般查询失败500、预算503沿现异常登记；生产未注册路由由框架404且不读来源。错误不转EMPTY，客户端保留普通K线但清除本次失效标签及辅助资料。

旧格式拒绝、新格式正常接收、合法int数值、显式None、事件多种真实route、日期不同但数值相同、结构终态时间晚于查询截止等均须正反测试。普通/debug对同一内部结果的全部公共字段和字节解码值相同，只有debug部分不同；debug失败不得退回普通成功。真实HTTP分别验普通和debug，不拿内部模型通过替代API验收。

## 6. 下一根预测编码设计（本次有限跟踪配套待修正）

本节规定最新识别规则对应的单根预测；必须先完成§2—4的本次修正，再实施本节，不引入第二个识别器。本次三项修正后的纯内核仍待实施；不读取真实行情。§16—17是修改前成绩，不证明本节新条件或完整请求性能已经通过。

### 6.1 本步范围、输入和代码交接

P3第2步完成纯计算：前提检查、一个实际未来端点的条件、有限边界、原点核验、整数显示、固定FORECAST_SPEC及纯文字。第3步再接查询/日历/缓存/完整模型/投影/API，第4步迁TS调用。本步不得为了跑通旧公开DTO提前改query/API，也不得为保留旧工具留下可运行旧求解器。

输入直接使用本次修正后P3第1步的`SeriesEntry.calculator_at(n, check)`独立副本。只读`period/source_identity/spec/previous/processed/wave/history/state/reference/active_structure/followed_structures`；`STRUCTURE`必须对应同方向、同参照的`ASSESSING`活动结构。首次反色后的有效旧结构位于有界followed_structures，不再位于active_structure；无需复制`SeriesEntry.structure_records`全集。不得从末根H符号、窗口中的最后一条STRUCTURE事件或旧pending字段反推当前状态。

| 方法及位置 | 固定输入/返回/职责 |
|---|---|
| `forecast.py:precheck_next_bar(c, check)` | 返回`ForecastPrecheck`；只检查真实进度与静态可能性，不校准EMA、不读日历、不尝试假设收盘 |
| `forecast.py:forecast(c, projection, endpoint, check, *, prepared)` | endpoint必须是单个时间字符串，不再接受端点序列；prepared为同次前提检查。校验仍是同一真实进度后编排B/A或固定参照，返回`ForecastKernelResult` |
| `forecast_entry.py:solve_first_dull(c, projection, endpoint, reference, role, check)` | 仅NONE、仅给定一个参照的首次钝化范围；不在内部偷偷选择A或推第二根 |
| `forecast_next.py:solve_active_reference(c, projection, endpoint, reference, role, check)`（新增文件） | DULL/STRUCTURE的一个实际参照；DULL/B被证实无有效关系后，才允许单独求A的救援范围 |
| `forecast_next.py:solve_followed_structure(c, projection, endpoint, structure, check)` | 仅给定的一份FOLLOWING旧结构，按§6.12求下一根价格失效条件；不选择近远，不改变当前普通状态 |
| `forecast_math.py:solve_comparison(left, op, right, domain, *, projection, period, check)` | 返回`ComparisonRanges`，直接求有限根及可确认成立/不成立/临界未决范围；不取区间中点或遍历价格 |
| `forecast_detector.py:evaluate_next_at_price(c, projection, C, endpoint, role, check)` | 对有限必要边界点/整数进行同一原投影和所有来源组合核验；真正标签以唯一r4的clone+一次step判定 |
| `forecast_detector.py:evaluate_structure_follow_at_price(c, projection, C, endpoint, related_structure_id, check)` | 对指定旧结构使用相同possible_bars来源组合；在独立副本上调用唯一核心的_advance_followed_structures核验，按旧id匹配实际CANCEL/记录。不得调用普通选峰/救援/完整step，不读取或发布新进度 |
| `forecast_detector.py:verify_reference_invalidation(c, bar, reference)` | 只核近B同色/零时严格突破的参照事实，使用原`_reference_was_broken`及独立的本根DIF极值副本；不调用完整step、不检查A资格 |
| `forecast_text.py:make_display(result, *, prepared, period, through, mode, check)` | 读取同次prepared的真实state/direction、新结果及已核合法整数，生成原四字符串；不再取历史分位数、裁掉范围或重新求价 |

以下内部类型放在现`types.py`，不改既有`XxmBar/Wave/XxmStep/XxmStructureRecord`的含义。采用明确字段的不可变外层记录，集合用tuple；包含的参照/快照/表达式必须独立复制，不能与输入或缓存共享可变对象。它们不作为新HTTP字段透传：

| 内部类型 | 完整字段 |
|---|---|
| `ForecastPrecheck` | `snapshot`（根前有界进度副本，仅RAM）、`direction`、`references`（nearest/farther六字段参照或None）、`active_role`（NEAR/FAR/None）、`nearest_decision`、`stop_reason`（仅当前普通关系的静态退出原因或None）、`following_structures`（按direction/id排序、最多两份FOLLOWING独立深副本的tuple） |
| `ComparisonRanges` | `certain_true`、`certain_false`、`undecided`，均为升序不重叠的Interval元组；在传入domain内互不重叠且并集等于domain |
| `ForecastConditionDraft` | `outcome`、`reference_role`、`price_ranges`、`predicates`；与§5.4.3对应，但没有尚未生成的Condition id |
| `StructureFollowConditionDraft` | `outcome=SIGNAL_DISAPPEARED`、`related_structure_id`、`direction`、`origin_wave`、`next_same_color_start`、`next_same_color_count`、`price_ranges`、`precision_ranges`、`predicates`；不含尚未生成的id，不使用reference_role。第3步按§6.12生成完整内部/debug项 |
| `ReferenceForecast` | `conditions`、`relationship_ranges`、`relationship_precision_ranges`、`precision_ranges`；relationship两项只统计§6.3有效关系的确定/未决价段；precision_ranges保留该参照全部适用outcome的未决价段，不能混用这两个未决集合 |
| `ForecastKernelResult` | `status`、`reason_code`、`target_endpoint`、`bars_ahead`、`references`、`selected_reference`、`nearest_decision`、`far_evaluated`、`conditions`、`precision_ranges`、`structure_follow_conditions`（上述旧结构Draft的tuple，未产生条件则空） |

`ForecastKernelResult`还没有forecastId/Condition id、来源/日历身份、普通display及HTTP外层字段。第3步按§5.4组装完整内部模型。prepared只可用于产生它的同一根前snapshot；不匹配立即失败，不能套用另一个asOf或源修订之前的前提。所有假设失败均丢弃本次对象，真实c及既有结果保持不变。

`make_display`只处理dataStatus=READY的本节结果；EMPTY/DELAYED由第3步query按§5.4来源状态生成四字段文字，不为文字构造计算器或prepared。through与prepared.snapshot.previous.time核对；不存在previous的静态输入只允许through=None，不直接访问空对象。

### 6.2 原一步EMA、来源选项与校准

继续沿`ProjectionState.advance`的实际顺序：

```text
e12 = e12_previous * 11 / 13 + C * 2 / 13
e26 = e26_previous * 25 / 27 + C * 2 / 27
D_raw = e12 - e26
DEA_raw = .8 * dea_previous + .2 * D_raw
H_raw = 2 * (D_raw - DEA_raw)
```

不得用展开式替代实际核验。`recover_projection(bars, period, check)`的bars必须是同次已校验的完整真实前缀：从首close初始化并递推全部前缀，**只有最后250根用于逐字段误差校准，不是只拿250根重新初始化EMA**。保留日线0.0005/分钟1e-8校准容差；不另读行情、不改初值、不跳过源差异。该全前缀递推开销也计入400ms。

`possible_bars`对每个被核验的C先check，再调用一次advance并检查所有原中间结果有限；分钟D/H/DEA使用原float，日线D_raw/H_raw各自调用一次原`source_options`，DEA按原三位表示。每个D选项与H选项绑定成同一XxmBar，最多2×2组合；不能用已三位D重算H。同一组合的参照突破、1%、柱色和全部谓词共用同一D/H绑定。**不能调用`ProjectionState.project(guard=True)`把所有临界点提前抛成未知。**

每个C/来源组合都从同一根前进度独立clone并至多step一次；不把上一组合子状态传给下一组合，不写回c、entry、检查点、指纹或结构全集。允许源值不同，只要所有组合的语义结果及实际参照一致即可确认；不能只选一个能形成的组合。组合语义不同则该未认证点仍未决；若它原已被宣布确定或作为显示整数，按§6.6整次失败。

C必须正且有限，实际EMA、来源乘1000及必要比较操作必须可计算。必要反根/原核验发生溢出或非有限值时走失败，不新增NON_FINITE_PROJECTION、不当作确定无解。无上界范围只适用于这些原运算有限的正收盘域，不为覆盖不可计算的float尾部恢复全域遍历。

### 6.3 前提检查、先近后远及字段赋值

EMPTY/DELAYED由查询层先处理，不构造计算器、不校准、不取未来日历。仅READY进入本节。

| 当前事实 | precheck必须做什么 | 明确禁止 |
|---|---|---|
| 无逻辑wave（开头全零） | ZERO_WAVE，直接结束 | 借下一根颜色补前段、先跑校准/日历 |
| NONE且无B | stop_reason=NO_REFERENCE，仅停止普通关系搜索；仍保留有效following_structures | 虚构A或第三个，或跳过旧结构条件 |
| NONE且`wave.count+1<2`，或全部现有参照本轮已严格突破 | stop_reason=NO_ENTRY_RANGE，仅停止普通关系搜索；仍保留有效following_structures | 用今天未过价格/今天DIF不正作为明天无解理由，或跳过旧结构条件 |
| NONE且至少一个参照仍可能 | 继续；按下一根H区分count是否增加 | 历史单根过滤、把零算成第二根 |
| DULL | 沿实际活动参照；活动B先B，活动A固定A | 每天重选最强、回切B或重查首次价 |
| STRUCTURE | 核active_structure为ASSESSING，固定其原参照继续考核 | 直接CONFIRMED停算、救A保结构 |
| 上根已首次反色，当前是新段NONE | 普通关系按当前wave/count/history判断；旧结构另按following_structures逐份判断 | 停止整个请求，或将旧结构当当前普通参照、无限延长旧结构范围 |

实际调度固定为：

```text
prepared = precheck_next_bar(c, check)
if prepared.stop_reason and not prepared.following_structures:
    返回静态NO_CANDIDATE，target=None
进入一次校准和单一未来端点（§6.8）；两类条件共用
if not prepared.stop_reason:
    if c.state == STRUCTURE or c的活动参照为A:
        仅求这个固定参照
    else:
        B静态已破时标UNAVAILABLE；否则先完整求B
        B.relationship_ranges非空：停止普通选峰，A不调用
        B.relationship_ranges为空且relationship_precision_ranges非空：保留普通未决，A不调用
        B上述两个关系集合均为空：才审A是否存在、是否本轮已破
        A仍可能时单独求A；不合并B失效范围和A范围
对prepared.following_structures逐份执行solve_followed_structure
按§5.4.2/§6.12合成最终status、reason、display，不从普通分支提前返回
```

有效关系只统计：NONE的DULL_FORMED；DULL的DULL_HELD、STRUCTURE_FORMED、STRUCTURE_FORMED_AND_FOLLOWING。失效事实和未决价段不冒充有效关系；“没有结构形成范围”不等于近处钝化无可能。已有STRUCTURE不做这项近远调度，其保持/回钝化/首次反色/消失范围均按固定原参照返回。

关系已确定无解时，不能因旁侧失效分类尚未确定就阻止审A。例如B严格被突破已证实，仅H临界使REFERENCE_INVALIDATED与翻色SIGNAL_DISAPPEARED之间未决，并不意味着B还可能保持钝化。调度只读relationship_precision_ranges；最终precision_ranges只沿实际所选参照全部适用outcome输出，不把被舍弃B的失效分类未决拼进A结果。此字段仅内部计算使用，不新增HTTP字段。

DULL/B转求A的条件还必须包含：**下一根同色或零、下一根严格突破B、A本轮未破、当根C同时越过B及A价格、D严格背离A、既定根数和TOP正DIF资格。**仅沿A保持DULL，不追加activation或1%结构。B真无关系时不代表A自动合格；没有A或A也已破就不调用A求解。NONE转A仍是首次资格，不能套用这个救援动作。

`solve_active_reference`必须用prepared.active_role及参照完整身份区分“原活动B，现单独求A救援”和“原活动就是A”。不能仅因传入role=FAR便套救援条件：前者仅求上述DULL_HELD，后者必须完整求保持、形成、翻色和消失。B和A救援都确定无关系且无未决时，按§5.4.2返回明确的NO_CANDIDATE，不保留两套条件；固定活动A/STRUCTURE则按其全部outcome条件决定READY，不只检查relationship_ranges。

| 执行路径 | nearestDecision.status | selectedReference / farEvaluated |
|---|---|---|
| 来源未就绪、校准前静态退出尚未检查参照 | NOT_EVALUATED | None / False |
| 无B或B本轮已破 | UNAVAILABLE | 尚未求A时None/False，确实求A后FAR/True |
| 已求B且有效关系非空 | HAS_RANGE | NEAR / False |
| 已求B只剩未决关系 | UNCERTAIN | NEAR / False |
| 已求B且关系确定为空 | NO_RANGE | 没求A时NEAR/False；进入A后FAR/True |
| 活动A或STRUCTURE固定原参照 | NOT_EVALUATED，注明沿已选原参照 | 按实际角色NEAR/FAR；只有实际求A时True |

不能把未执行写成NO_RANGE。无合法整数不改变关系是否有解；B有解但无可显示整数也不触发A。普通关系仅剩未决时，不能借其旁侧近参照失效范围升级READY；但独立旧结构有确定条件时，最终可READY并保留普通未决说明，A仍不调用。只有两类都无确定条件且仍有未决才PRECISION_PENDING。

### 6.4 可编码条件及唯一r4结果核对

s为旧逻辑方向（顶+1、底−1），R为实际选中参照，Pr/Dr为其价格/DIF，PB为近B价，P为上一真实DIF。先按原float顺序算`g=abs(P)*1.0/100`，再对同一个源D计算`delta=s*(D-P)`。对参照的“本轮已破”读根前wave.dif；候选下一根破与当根资格分别进入下表。

| 前态/条件 | 完整必要谓词 | outcome |
|---|---|---|
| NONE/R首次 | 同色或零，`count+int(H!=0)>=2`，R根前未破；`s*(C-PB)>0`且`s*(C-Pr)>0`；`s*(D-Dr)<0`；TOP额外D>0 | DULL_FORMED |
| DULL/R翻色且破R | `s*H<0`且`s*(D-Dr)>0` | SIGNAL_DISAPPEARED |
| DULL/R翻色且R有效、未破原段价 | `s*H<0`且`s*(D-Dr)<=0`且`s*(C-wave.price)<=0` | STRUCTURE_FORMED_AND_FOLLOWING |
| DULL/R翻色且R有效、当根破原段价 | 上述翻色/ref有效且`s*(C-wave.price)>0` | STRUCTURE_PRICE_DISAPPEARED，先形成后同根价格消失 |
| DULL/R同色或零形成 | `s*H>=0`且未破R；P!=0，delta<0且−delta>=g | STRUCTURE_FORMED |
| DULL/R同色或零保持 | `s*H>=0`且未破R；上述1%形成不成立 | DULL_HELD |
| DULL/B同色或零破B、A未计算 | `s*H>=0`且B本根严格破 | REFERENCE_INVALIDATED，仅说明近处失效 |
| DULL/A同色或零破A | `s*H>=0`且A本根严格破 | SIGNAL_DISAPPEARED |
| DULL/B已确定无关系，单独求A救援 | §6.3完整救援条件，不再检查1%形成 | DULL_HELD，实际活动参照A |
| STRUCTURE/R严格破R | 先检查`s*(D-Dr)>0`，不论柱色 | SIGNAL_DISAPPEARED |
| STRUCTURE/R有效且翻色、未破原段价 | 未破R，`s*H<0`且`s*(C-wave.price)<=0` | STRUCTURE_FOLLOWING |
| STRUCTURE/R有效且翻色、当根破原段价 | 未破R，`s*H<0`且`s*(C-wave.price)>0` | STRUCTURE_PRICE_DISAPPEARED |
| STRUCTURE/R有效且同色/零回转 | 未破R，`s*H>=0`，P!=0，delta>0且delta>=g | RETURNED_TO_DULL |
| STRUCTURE/R有效且同色/零保持 | 未破R，`s*H>=0`，回转不成立 | STRUCTURE_HELD |

首次反色当根的价格消失是§3.7逐根规则的配套，不新增识别条件：内部/预测debug增加结果分类STRUCTURE_PRICE_DISAPPEARED，不增加普通状态或页面入口。OUTCOME_ORDER固定在STRUCTURE_FOLLOWING之后、SIGNAL_DISAPPEARED之前，所有Outcome字面类型/schema/TS及文本同步；DULL前态文字说明“结构当根形成后因价格突破消失”，STRUCTURE前态说明“结构首次反色当根因价格突破消失”。它不计有效relationship_ranges，不误称仍FOLLOWING，也不当成原参照DIF突破。价格破/未破以严格>0/<=0互补，原1%/EMA不变，不增加OR表达式或全域搜索。

_actual_outcome不能无差别滤掉所有structure_price_break：只把根前followed槽中无关旧id排除在当前对象匹配外，完整step仍保留。当前active结构或本根color_flip新结构的价格CANCEL，要与同id DISAPPEARED精确配对并判上述分类；不能误认成无关旧事件、仍跟踪或合同错误。PF13增加T/TS/B/BS四个独立前态：手写EMA分别(200,100,99)/(199,100,98)/(100,200,-99)/(100,199,-98)，C分别103/104/97/96，原投影分别翻绿/翻绿/翻红/翻红且突破原段102/103/98/97，应STRUCTURE_PRICE_DISAPPEARED；安全价格101/102/99/98则进入对应未破价FOLLOWING。逐原source_options核验，不拿理想式替原EMA。

每次只生成本态适用的条件。保持谓词不必新增OR表达式：P!=0且g>0时，DULL保持的1%部分写`−delta<g`，STRUCTURE保持写`delta<g`；g==0时分别写`delta>=0`、`delta<=0`；P==0则不生成1%形成/回转条件。**P非0不保证g非0，极小float下溢仍须保留严格方向。**这些只化简已计算delta/g的逻辑，不把D±g替代原运算，不改变条件AST合同。

NONE单独核验B时，先用同一正式首次资格函数核本根B。B不合格即返回未首次形成，不运行会顺带选择A的完整step；B合格才克隆并调用唯一step核完整语义。这样即使某个必要候选价落在B不合格的一侧，也不能借点核验提前执行A资格。DULL/B只核B失效的路径同样使用限定原语，禁止完整step顺带救A。

`evaluate_next_at_price`必须核完整语义。下表的“事件/记录”均限定于本次当前普通关系：先按route/relatedStructureId区分旧结构价格事件及其更新，旧结构事实单独核验、完整保留，不能让其进入下面的“无新事件/无结构记录”计数。不得再对完整step断言len(events)==1或len(structures)==1，也不得直接取首项：

`_actual_outcome`先取根前followed_structures中的旧id集合：其中同id的结构更新、以及CANCEL/structure_price_break且relatedStructureId在该集合的事件，属于旧关系；当前新形成或active_structure对应的记录属于普通关系。先校验旧组确实符合§3.7，再从完整结果的只读视图取普通组核下表；不能仅因route看似旧事件就忽略错id、错方向或缺失更新。FINISHED只有旧记录更新而无事件，同样须从普通组计数中分开。不得修改原step、删除事件或丢掉任何合法结果。

| outcome | 唯一step结果必须同时满足 |
|---|---|
| DULL_FORMED | DULL/activation、fromState NONE、实际参照R，根末DULL，无结构记录 |
| DULL_HELD | 原DULL关系保持且无新普通事件；A救援时实际参照为A，原事件不改 |
| STRUCTURE_FORMED | STRUCTURE/dif_turn，关联新ASSESSING记录，根末STRUCTURE及同id活动记录 |
| STRUCTURE_HELD | 无新事件/更新，原同id活动结构继续ASSESSING |
| RETURNED_TO_DULL | DULL/dif_return，原结构同id DISAPPEARED/dif_return，根末DULL且ref仍R |
| STRUCTURE_FORMED_AND_FOLLOWING | STRUCTURE/color_flip，新同id FOLLOWING且formedAt==firstOppositeAt，未价格消失，根末新段NONE |
| STRUCTURE_FOLLOWING | 原活动结构同id FOLLOWING，无新STRUCTURE事件，未价格消失，根末新段NONE |
| STRUCTURE_PRICE_DISAPPEARED | 原ref有效、首次反色当根价格消失；STRUCTURE前态原同id DISAPPEARED，DULL前态另有color_flip形成事件；价格CANCEL必须关联该当前对象，不能混根前另一旧对象 |
| SIGNAL_DISAPPEARED | CANCEL及实际dif_break或dif_break_on_flip；旧STRUCTURE须同时输出同id DISAPPEARED/reference_dif_break；旧DULL无结构更新 |

不能只看根末NONE就当消失；真实反色的旧事件方向及原色段从根前wave取，不能用新段point方向反推。

**REFERENCE_INVALIDATED不是最终标签，必须单独核验。**在B已证明有关系、A未计算的请求中，B同色/零突破的C只检查原来源组合及B突破原语，既不要求最终NONE，也不运行会自动检查A的完整step。`evaluate_next_at_price`遇这一分支直接返回参照事实；其余真正标签才运行clone+step。A资格与A求解均不得因此被调用，farEvaluated仍False；普通限定文字明确真实完成收盘仍按r4同根检查远参照。

### 6.5 有限边界、来源误差与点核验

#### 6.5.1 原运算的直接反根

本次只有未知C。保留现`Interval/intersect/merge/subtract`的开闭语义；`ComparisonRanges`在domain内分为确定True、确定False、未决，不以几个样本填满范围。AND条件的确定True取各True交集，确定False取任一原谓词可确认False的并集，剩余为未决；同一来源绑定重复出现时仍是同一变量，不拼接不同D选项冒充共同成立。

`forecast_expression.py:one_step_macd_envelope(projection, field)`只执行一次advance的运算结构，复用`_AffineEnvelope/_envelope_binary/_envelope_scaled/_rounded_envelope/_outward_float`；p系数固定0，得到`a*C+b ± (e*C+f)`。实际float常量以`Fraction.from_float`保留，整数/比值用Fraction；每个乘、除、加、减都按原顺序增加误差，不把K浮点常数或D理想式当精确原运算。

`solve_comparison`对必要门槛的上下误差线直接求根。对f(C)与0比较：f的下界>0才确认gt，下界>=0才确认ge，上界<=0才确认gt为False，上界<0才确认ge为False；lt/le镜像。eq只有两界均为0可整段确认；某一侧严格隔开0才确认不等；其余未决。零斜率按常量处理，负斜率翻转不等号，不能假设误差线总递增。根用Fraction解后定向转float；同参照候选切点仅来自本态使用的价格门槛、参照D、TOP正D、H=0及完整1%比较。

Interval表示原计算可接收的有限float收盘集合，不新增分币过滤。对Fraction根r，`ceil_float(r)`为不小于r的最小有限float，`floor_float(r)`为不大于r的最大有限float：先转最近float，再按Fraction精确比较，至多用一次nextafter纠正方向，不循环走价格。`C>r`用ceil_float；恰等r则开、不等则闭；`C>=r`用ceil_float且闭；`C<r`用floor_float，恰等r则开、不等则闭；`C<=r`用floor_float且闭。确定False的半域同样处理，未决取domain减去已确定两组。根无法有限表示时按§6.8失败，不以inf冒充有限端点。

每次交/差/合并后做有限空集检查：开下界的第一个候选为nextafter(lower,+inf)，开上界的最后一个候选为nextafter(upper,−inf)，闭界使用自身；再排除0和非有限候选。首候选大于末候选即空，不能留下两个相邻float之间不存在收盘值的开区间，误报近处有解或精度未决。无上界None不参与有限根转换，空集检查以最大有限float为末候选；该检查只判断是否有可表示价格，不把原区间端点/开闭挪成首末候选、不遍历中间价格。

`delta=s*(D-P)`和`g=abs(P)*1.0/100`始终按原比较证明。g先用原float算好作为固定常数；完整sub/scale包络覆盖delta的原减法与符号运算。D±g只用于定位候选点，不决定开闭。P=−99、D=−98.01原差不足0.99，−98.009才通过，不能被理想代数门槛改写。

#### 6.5.2 日线source_options的保守范围证明

保留原`source_options`；保留通用`_expression_envelope(round3)->None`保护，不把任何round3节点统一认证为“原值±0.0005”。新增专用`one_step_source_envelope`，只接受与同次projection完全一致的单步D/H节点；其他多步/混来源/嵌套任意round3拒绝。证明范围而不是修改源值，不能将下列误差当识别epsilon。

令u=2^-53、eta=2^-1074，均为binary64最近舍入的固定证明常量。原v*1000及相关原运算须有限。`source_options`的guard分支返回`fl((floor(fl(1000*v))+j)/1000)`，j为0或1；其误差可保守界为：

```text
E_floor(v) = (2*u + u*u)*abs(v) + (1+u)*(1+eta)/1000 + eta
E_round(v) = u*abs(v) + (1+u)/2000 + eta
```

第一式包含乘1000舍入、floor至多1及最后除1000的表示误差；第二式包含round到最近0.001倍数、再表示为float的误差。E_floor逐项覆盖E_round，因此实现统一使用E_floor，无需按C选择分支或遍历三位刻度。证明只假定可能走任一原分支，故guard计算本身的表示偏差也不会漏掉返回选项。Python原round语义依据[官方说明](https://docs.python.org/3.13/library/functions.html#round)，不是新增四舍五入策略。

若原D/H包络为`a*C+b ± (e*C+f)`，令`k=2*u+u*u`、`t=(1+u)*(1+eta)/1000+eta`，则日线源值包络固定为：

```text
e_source = e + k*(abs(a)+e)
f_source = f + k*(abs(b)+f) + t
```

系数全程Fraction，再继续按原sub/scale/abs比较构造误差线并反根。正常量级保留约0.001源值附近的临界未决带；大数时绝对值项会变宽，不能漏掉PF16的额外返回选项后认证为False。分钟不套日线源误差，只使用原float运算包络。该专用证明以当前binary64环境为前提，实施测试核对环境事实，不新增环境配置、识别容差或安装项。

此保守实现不要求找到每个真实round台阶的精确前像，也不把未决当无解。若未来需要缩窄未决带，另有独立证明及评审，不能在本步临时改源取数或用抽样认证。

#### 6.5.3 有限点与范围不能混为一谈

每个实际门槛只生成误差上下线的直接根、理想主线`a*C+b=0`的直接根、这些根定向转float涉及的相邻值、已有有限区间端点及显示整数，不递归细分、不移动步长、不遍历正float。理想主线根是有限候选点，不是区间中点，也不是整段认证依据；H=0的175.5/24.5即使位于未决带内部也必须进入点核验，不能只收误差带两端和整数。原点核验对一个C只advance一次，全部来源组合按§6.2/6.4执行；本次可在RAM复用同C的原投影，核验结果另按根前进度、参照完整身份及实际核验分支区分，不能把B失效原语结果当成A标签或另一状态的结果；不建全局价格缓存。

上述复用由`forecast_detector.next_bar_evaluations()`管理本次内存：ContextVar默认None，进入时建立本次字典，finally恢复token；仅同一次forecast中的B/A及有限点复用。独立调用单参照solver也须建立局部上下文，不把结果留给后续调用。原投影按实际projection/C复用，语义核验再区分根前snapshot、参照和分支；异常也清理，不增加共享持久缓存或配置。

原先未决的候选点，全部来源组合语义一致时可单独记为闭合单点，并从未决带中剔除；不能据该点扩张邻域。M1/M2的175.5/24.5必须这样保留合法零，不因误差带覆盖0而丢掉。若来源组合结论不同，继续未决。已经宣称确定的点或显示整数若核验不一致，必须整次失败，不能退回未决来掩盖证明错误。

只合并同参照、同outcome、同route/谓词和同精度含义的相邻区间；不同条件不得平均价格再算。不同outcome互斥，但不要求用条件覆盖全部正float；对某个原谓词三组范围的完备要求，不得误解成全标签全域划分。

### 6.6 精确范围、整数和文字

保留内部原边界和开闭。对每个确定区间直接计算合法最小/最大整数：闭下界取ceil，开下界整数时再+1；闭上界取floor，开上界整数时再−1。例开4135.78→4136，开4136→4137，开4140.2→4140，开4140→4139；闭整数可用。不得把边界先格式化再取整、互换上下界或向外移动。

对每个显示整数候选n，先得到实际计算使用的`C=float(n)`，确认C有限且`int(C)==n`，再用这个C执行`Interval.contains`及§6.4原语/唯一r4核验，保留原投影的全部来源绑定。不得先用Python整数的精确比较通过范围检查，再把转换后已经变值的float交给投影。转换溢出、非有限、不能保持同一整数或原核验不一致，均按§6.8失败。**不一致即ValueError向上失败，不缓存、不挪价、不跳点、不换epsilon、不返回半份READY。**未决点不生成整数，不拿一个已证实单点填补两个确定区间之间的未决空隙。

例：开下界9007199254740992，候选整数n=9007199254740993虽在整数比较中大于下界，但转float后变为9007199254740992，必须拒绝，不能输出这个点位或自动跳到另一个整数。闭下界9007199254740992本身可精确表示，转换检查应允许继续核验；正常指数整数4136同样允许，不能把安全检查变成新的分币或数值范围过滤。

无整数时priceRanges仍保留精确非空范围、displayLower/Upper均None，状态仍依数学关系可READY；不能据此查A。无上界的确定区间可有displayLower而displayUpper=None。纯单点只描述该点，不能写成从该点开始的连续不低于/不高于范围。

文字只读取新结果及显式传入的同次prepared。当前状态读取prepared.snapshot的state，顶底方向读取prepared.direction；核对period与snapshot.period、through与snapshot.previous.time一致，不从DIF正负、条件是否为空或某个outcome猜方向。NONE重点说明首次钝化范围；DULL优先结构形成/形成首次反色与失效限定，再列保持；STRUCTURE优先直接消失/回钝化，再列首次反色/保持。完整条件不得被历史分位数或示例选择裁掉；同outcome多段按已有顺序列出，不凭前端合并。B未算A的失效限定必须出现在普通文字，不藏debug。display仍为原四字段，不增加页面功能。

### 6.7 逐文件处理及第3步接口准备

| 位置 | 第2步必须处理 | 后续责任 |
|---|---|---|
| `forecast.py` | 替换20端点foreach、旧inactive字段和STRUCTURE早停；只保留本节两个入口及新结果组装 | 第3步query改为单endpoint和prepared调用，不保留旧序列签名兼容 |
| `forecast_entry.py` | 旧entry_partition/entry_cuts/stable_reference_on_band/reason_for/solve_entry_ranges整体换为单参照首次条件，去pending_rearm和旧全域入口 | 旧工具专属调用按P4/P5处理，本步不运行 |
| `forecast_next.py` | 新增DULL/STRUCTURE单参照条件、救A限定及结果组装 | 不复制step、不另建识别策略 |
| `forecast_detector.py` | 保留clone；possible_bars补前后check/原有限性；增加单根语义映射和近失效原语核验；移除event_options/activation_signature/confirmed_options旧多步/等待路径 | 有用旧工具使用前迁唯一正式入口，不留旧函数转发 |
| `forecast_math.py` | 保留Interval/intersect/merge/subtract/const/condition/scaled/difference/as_interval；复用types.py的ComparisonRanges实现比较求解、直接反根及0位整数，不另定义同名类型 | 删除float_bits/bits_float/positive_float_span/span_intervals、Affine的P维度、project_affine_prefix及仅旧路径使用的小函数；不保留备用全float求解 |
| `forecast_expression.py` | MACD节点只e12/e26/dea/field；移除prefixBars/prefixClose/target和P变量；保留原运算/同源绑定及包络小函数，新增单步原值/源值专用包络 | 第3步Python/TS表达式合同同次迁，不由旧JSON换字段充新fixture |
| `forecast_joint.py/forecast_paths.py` | 正式多步、多变量、全float路径实现移除；必要纯Interval能力已在forecast_math，原核验在forecast_detector，不复制两个求解器 | 先查全部活动引用；P4/P5旧runner明确未迁、未执行，不为保持其可运行而留下旧算法 |
| `forecast_text.py` | 删除reference_band/build_display_context/select_display及旧relations/activation/WAIT文案；替换为§6.6纯文字 | 第3步query移除这些旧导入，不再扫描历史60样本/95%分位数裁价 |
| `forecast_spec.py` | §6.9完整固定字段和类型；生成实际v0.5-r4 hash | 第3步模型/API和第4步TS登记同次hash，不伪造旧hash |
| `forecast_query_service.py`、预测schema/API | 第2步不编码、不验旧公开入口；本节已固定新输入/结果与下一端点交接 | 第3步按下列唯一顺序整体迁，移除_active_confirmation、rearmContext、20步及旧DTO |

第2步移除正式旧求解路径，不删除P5专属研究/报告执行器或原材料。依赖它们的未迁工具留明确停点，不能当新预测验收。生产/页面不发布中间版本，识别核心及其Spec/记录格式不得为了适配预测而改回旧规则。

`test_xxm_calculator.py`的七个当前核心节点仅需clone；其中activation_signature/solve_entry_ranges的顶层导入移到仍待后续处理的旧预测节点内部，避免收集当前核心时加载已删除函数。`test_xxm_r4_observation.py`同理：旧观察执行器仅由末尾两个P4工具节点局部导入，当前识别观察节点直接使用唯一产品类。旧节点的输入/expected保持且不执行，不增加skip或旧函数转发，不改工作区旧执行器。两个本步预测测试文件按M/PF人工样本整体迁移；P4/P5工具专属文件仍不作为本步执行范围。

第3步完整内部根继续为§5.4集合。query加入来源/日历、真实状态、规则身份和asOf；forecastId先由包含旧结构Draft、但不含debug/任何条件id/自身forecastId的内部事实规范生成，再按该forecastId+outcome生成普通Condition id，按§6.12增加relatedStructureId生成旧结构条件id。**Draft没有id是纯计算阶段的确定合同，不是公开响应允许空id；完整内部模型生成前必须全部填好并校验。**普通display同一次生成，正常/debug只投影，不另算标签或条件。

### 6.8 同一预算、异常与开发顺序

400ms仍包含calculator_at/恢复、前提检查、完整前缀EMA校准、日历/缓存处理、求界、全部来源组合及必要step、文字、模型、投影、一次编码、缓存复制/大小统计/锁等待和最后检查。有效截止=min(原4秒请求截止，本次计算或缓存处理开始+0.4秒)。缓存命中也在同一截止中，不能命中后再开400ms或读取完成后另加4秒。

第3步query采用以下简单固定顺序，不新增缓存索引或另一套恢复机制：

1. 通过同次`load_entry`取得已校验真实前缀；EMPTY/DELAYED直接按来源状态生成结果，不进calculator_at/校准/未来日历。
2. READY在calculator_at、前提检查及任何预测缓存处理之前建立同一400ms截止。只有当前普通关系静态无可能、且following_structures为空时，才直接生成静态结果，不校准、不读未来日历；存在有效旧结构必须继续。
3. 仍可能时recover_projection只用同次完整前缀一次；校准失败形成PRECISION_PENDING/CALIBRATION_FAILED，target及日历身份为None，不读未来日历。
4. 校准成功才沿现SSE日历搜索最多90自然日，实际只取严格晚于through的一个本周期端点，得到本次calendarInputId；不读20端点，不重复查日历。
5. 以连接/Lake/周期、detector+forecast hash、真实前缀指纹、expected/asOf及calendarInputId的完整key查预测缓存。为保持单路径，命中也完成了前述一次校准，不另建跨阶段缓存；命中后不再求界、step或生成文字，仅独立复制完整内部结果并做本次投影/校验/编码。
6. 未命中才调用单根forecast，生成完整内部身份、Condition id及文字，完整模型校验→本次正常/debug显式投影→公开校验→一次编码→32KiB检查。准备独立缓存副本、计算大小；这些都在同一截止内。
7. 缓存锁内、修改前最后check；成功后一次发布并返回已准备bytes，发布后不得再做可能失败的复制/构造/校验。失败只丢弃本次预测候选，保留既有有效预测缓存；load_entry此前已合法发布的来源SeriesEntry仍保持有效，不因后续预测失败回滚。debug错误不降级普通成功。

每参照/比较/反根/来源组合/整数及最终编码前后共用check；无自动重试、后台任务、落盘恢复或价格跨度相关循环。第2步只把传入check贯穿纯计算，用M1—M5记录数学耗时；**完整400ms必须第3/5步把校准/模型/query/编码接齐后验，P4另验真实来源。**超限就停止说明，不以全未知、漏条件或放宽预算冒充完成。

| 情况 | 必须处理 |
|---|---|
| recover_projection明确CALIBRATION_FAILED | 仅该已知失败可转PRECISION_PENDING；未读日历不造target |
| 有保守临界段无法认证 | 在结果precision_ranges保留，不抛成NO_ENTRY_RANGE、不启用A |
| 确定范围/显示整数与原核验不同 | 整次失败，禁止降级未决或静默删价段 |
| 非法输入/状态/表达式、非有限必要原运算/反根 | ValueError向上传递；第3步按现源/内部合同或查询错误映射，不能捕获成成功 |
| deadline、取消、外部check异常 | 原异常向上传递，释放本次RAM；不以finally失败覆盖原错，不缓存 |

本次第2步顺序：已修正核心/clone→内部类型及precheck→原数学/来源包络复用→当前普通B/A条件→旧结构独立条件及唯一核心函数核验→普通完整step的多事件匹配→精度/status/显示合成→固定新Spec→独立PF测试与审计。每一项先有相应独立字面预期，不能先接旧公开DTO跑通再倒改字段。

### 6.9 FORECAST_SPEC与有限工作量

| 字段 | 固定值 |
|---|---|
| forecast_version | `xxm-key-point-forecast-v0.6-r4` |
| scenario_policy / target_selection / max_future_bars | `next_completed_bar / near_range_before_far / 1` |
| calibration_tail_bars | 250 |
| daily_calibration_abs_tol / minute_calibration_abs_tol | 0.0005 / 1e-8，仅校准 |
| daily_rounding_guard | 1e-10，沿现source_options |
| display_policy / structure_text_places | `valid_integer_boundaries / 0` |
| forecast_compute_budget_ms / max_response_bytes | 400 / 32768 |
| future_calendar_days / refresh_after_ms | 90 / 60000 |

删除旧price_display_places/price_boundary_places/explanation_sample_count/display_move_samples/display_move_quantile和多步政策，不加可选算法/源误差参数。`__post_init__`按MAIN_SPEC方式逐字段严格验证类型和固定值，拒bool冒充数字。预测hash继续由自身全部字段按现`json.dumps(asdict(spec), sort_keys=True).encode()`规范生成，不手填hash、不混用detector的序列化约定。本表是本轮目标Spec；当前运行仍为修补前v0.5，§16—17只记录此前基线。新增条件和新版本实施后再生成真实hash，公开模型/消费者同批同步。

普通关系最多求两个实际参照：B有关系或有未决关系时A为0次。另最多两份旧结构独立条件按§6.12处理，不增加普通候选数，也不跳过其预算统计。每个参照只生成适用谓词的有限根及相关邻点/整数；一个C至多一次advance、至多4组来源核验。记录实际参照数、谓词数、反根数、点核验及step次数；同状态/门槛个数相同，价格尺度扩大不得按跨度增加循环。无96/192等未经依据的额外次数上限；400ms仍为计算时限，不通过增加源码保护或全float搜索达成证明。

### 6.10 预测测试设计与识别规则对应

§16记录的是此前纯内核154项基线，本轮有限跟踪纯内核配套及PF21—34内部部分的实际成绩见§17.4；第3—5步的完整请求/合同/预算和P4真实来源部分尚未执行，不得拿P3第1步成绩代替。新数学测试放现主题`test_xxm_p3_forecast_math.py`及必要`test_xxm_key_point_forecast.py`，不创建新研究项目。业务expected来自§14字面事实，数学expected来自M1—M5/Fraction或明确原运算，不能由待测forecast生成。

| 编号 | 独立样本/明确操作 | 必须证明 |
|---|---|---|
| PF01 | M1/M2，C175.5/24.5；直接给ProjectionState，不校准 | 合法零成尚未首次反色结构，闭合单点可从未决带取出；邻域仍按独立证明，不调用guard=True提前丢点 |
| PF02 | 无wave、无B、count+1不足、B/A均曾破；正常当前价没过/当前TOP DIF<=0但下一根有可能 | 静态拦截且校准/未来日历0调用；不得用今天条件排除明天，正常变化可继续 |
| PF03 | M4近有确定范围/A更强；A求解及A资格helper一调用即失败 | A零调用；近只剩结构或只剩保持也算关系，不误称无解 |
| PF04 | NONE的B已破/A未破；B数学关系全False且无未决/A合格；反例A价未过或A已破；DULL/B无延续且A不存在/已破/救援确定为空 | 才求A且双价格门槛；DULL/B救A另断言下一根B严格破、同色/零、无新DULL事件；无救援按§5.4.2说明并保留target和实际选择记录，不把B失效拼回A、不声称当前真实标签已消失 |
| PF05 | B关系只有未决；另组B有宽确定范围+窄未决；B有非空窄范围但无整数；B关系确定为空、仅失效分类未决且A尚可能 | 前组PRECISION_PENDING/A零调用；有关系范围组READY、保留未决/无整数说明且不启A；最后一组按relationship_precision_ranges为空继续审A，不被全部precision_ranges误拦；最终未决不混近远 |
| PF06 | RC26新增A已破/B有效 | B正常求范围，A失效不连带B；来源/波段日期不同但数值相同不误认同一参照 |
| PF07 | M3及RC25；下一根首次同时出现相邻1%反向转折 | 仅DULL_FORMED，不同根结构、不推19根；当前一根有色+下一根零仍不足，两根有色后零可首次 |
| PF08 | P=±99到±98.01/±98.009形成边界、到±99.99/±99.991回转边界；P=0及P为最小正/负subnormal使g=0 | 原delta/g次序、严格方向和等号；形成/保持/回转谓词与唯一step相同，不累计、不跳零、不D±g改判 |
| PF09 | DULL/B正常有解且某C破B、真实r4本可救A；令A资格及求解被调用就失败 | 只核REFERENCE_INVALIDATED原语，不完整step顺带救远；普通不能写必然消失，farEvaluated=False |
| PF10 | 当前活动A，B在某C又合格；活动A仅有确定消失条件 | 始终沿A、B不重求；nearestDecision=NOT_EVALUATED，实际A求解才farEvaluated=True；不套B→A救援限定，有确定消失范围仍READY |
| PF11 | M5顶底三个整数；RC47价101回DULL及结构保持/回转/直接破 | 新记录的ASSESSING→DISAPPEARED关联正确，无WAIT，无CONFIRMED早停，无重复首次价 |
| PF12 | STRUCTURE/B破但A仍有效，A helper禁止调用 | 结构直接消失，关联旧id/reference_dif_break；不换A、不插入DULL |
| PF13 | RC53—58/65及RC97/105/106；DULL翻色、STRUCTURE翻色及同根原参照破；H=0 | 读完整events+structures辨别同根形成首次反色、首次反色价格消失STRUCTURE_PRICE_DISAPPEARED及原ref直接消失；安全未破价才FOLLOWING，新段NONE不等于取消；零不构成首次反色 |
| PF14 | RC63两轮；从首次反色根后的calculator_at进度开始 | 按新wave/count/history判断新轮，并按snapshot中最多两份旧结构求其有限失效条件；不读取完整历史、不复开已结束记录 |
| PF15 | 开4135.78/4136、开上界4140/4140.2、闭整数、单点、无整数窄段；Fraction根落相邻float之间及相邻float开区间；开下界9007199254740992的候选整数9007199254740993、闭下界9007199254740992和正常整数4136；故意让已证实点/整数核验不符 | 定向转换及开闭正确，无可表示C的区间必须为空、合法闭单点保留；整数候选先转实际有限float，变值者在原核验前拒绝，另两项不误拦并继续核验；合法整数与原点一致，不扩大单点/跨未知合并；不一致整次失败且无候选缓存，不挪价/降级掩盖 |
| PF16 | 正/负/0/subnormal及原大数−8796093022207.98；Fraction独立算Ef/Er及源输出误差；M1/M3正常整数 | 包络覆盖全部原source_options选项，含大数额外值；_expression_envelope通用round3仍拒认证；普通正常范围不得全未知 |
| PF17 | 非有限state/C/原中间结果/源乘1000、非法反根/坏prepared/错误活动结构；纯计算时文件及网络入口一调用即失败 | 明确失败不当无解或ROUNDING_BOUNDARY；输入/既有结果不变，check原异常不吞；正常人工求解不触发读取或写入，数据库边界另用依赖检查验证 |
| PF18 | 同C有2×2源组合：源值不同但语义相同/语义或参照不同；失败/开关debug/缓存命中 | 一次advance、组合各自独立clone和一次step、同源谓词绑定；一致可确认，分歧未决；失败不污染源进度。第3步再验普通/debug同ID/同display及同截止 |
| PF19 | M1/M2四周期数学计时及等数量门槛的价格尺度变化；第3/5步含完整前缀校准/日历/模型/编码/缓存复制与锁等待 | 记录调用数及数学耗时；完整400ms分层验收，发布前最后check、冷/热/异常不重复读或返回半成功。真实源留P4 |
| PF20 | 旧20步/P变量/WAIT/prefix字段/旧版本fixture；新单endpoint及内部Draft→完整模型/id；BOTTOM但DIF为正、空条件及错误period/through的文字输入 | 第2步内核拒旧收新、不回退旧求解；文字只读显式prepared，不猜状态方向，错进度拒绝；第3/4步再验HTTP/TS完整合同，不能用换hash或空旧字段兼容 |

### 6.11 本轮文档核对与开工条件

本节是新目标，不把§16旧预测验收当本次通过。开工前先完成新核心/结构进度/恢复/内部聚合，确认§2—4与§14.15字段及边界一致；再按§6.12补旧条件及当前条件配合。M1—M5/PF01—20原正确数学与安全目的继续保留，PF14按新范围调整，新增PF21—34。

完整Spec、同次projection复用及两类核验入口、旧新条件字段、精度及status/display必须同次明确；不新增源读取、额外下一根端点、普通卡片或超过400ms的办法。若实际编码需要变更用户已定规则/公开字段集合/源表示/预算，按原要求先停报，不临时改算法。

### 6.12 旧结构下一根消失条件（本次三项修正配套）

先完成§2—4核心/恢复/聚合，再修改本节。继续只下一完成根、先前提后有限边界，复用同次MACD/原EMA/源选项/校准/端点，无中点/价格遍历/新读取；原400ms含全部检查及最终输出。

输入为同次真实前缀snapshot中最多两份合法FOLLOWING，包含start/count及跟踪极值。已FINISHED/DISAPPEARED无旧条件。令s=旧方向、P0=originWave.price，C/H来自同一次下一根表达式，根前计数n=nextSameColorCount：

| 根前进度 | 下一根旧结构消失的完整条件 | 原因 |
|---|---|---|
| startNone/count0 | s*(C-P0)>0，**不限制H** | 分隔反色、零及新同色第一根都必须比价 |
| start非空/count1 | s*(C-P0)>0，**不限制H** | 下一根反色只跳过单根段而不终止；同色/零也比价 |
| start非空/count>=2 | s*H>=0 且 s*(C-P0)>0 | 下一根真实反色将先正常FINISHED，不应算消失；同色或零仍有效 |

不额外加两根触发要求、1%或原参照DIF条件；有效段的至少两根只决定何时正常结束，不能错误变成价格消失前提。当前普通关系/已选近远的求解仍独立，近B有解不能略过旧结构。

StructureFollowConditionDraft在既有字段间增加next_same_color_count（严格int），第3步完整内部/debug项增加nextSameColorCount，其余为id/outcome=SIGNAL_DISAPPEARED/relatedStructureId/direction/originWave/nextSameColorStart/priceRanges/precisionRanges/predicates。初始None/0与单根1都可能有条件；条件id仍由forecastId、旧id、outcome生成，不加新用户参数。forecastId仍包含完整计算事实，debug开关和图上显隐不参与；同根图上隐藏旧消失，不能从数学条件或内部结果删掉它。

types.py、precheck、forecast_next.solve_followed_structure、forecast_detector.evaluate_structure_follow_at_price、forecast/forecast_text、forecast_spec及内部模型同时迁新字段。solve只按上表构造1或2条谓词，不遍历色段/全部历史。旧结构点核验仍复用唯一核心_advance_followed_structures，对完整进度副本逐个原source_options检查对应旧id的CANCEL及DISAPPEARED；不得调用完整step/选峰/救援导致偷算未评估A。首次反色当根才形成的新跟踪不属于根前旧对象，当前普通关系完整step需按§3.10识别其形成及可能同根价格消失，不能只取首事件。

同一C共用evaluation_scope中的advance/source_options及原候选点；两类检查结果分开缓存并finally释放，键包含完整新进度/源选项/C/端点/求值种类及旧id。普通完整step保留所有事件，普通结果匹配排除无关旧事件但不修改原step。不存在旧事实时用专用旧跟踪检查，不为复用而运行A资格。任何已证明端点或整数与唯一核心不符整次失败，不能删价段降级掩盖。

普通status/display的两类合成、近有解停止远求解、静态退出但旧条件仍有效、精度未决及合法整数规则保持§5.4/§6.3。当前普通事件和旧结构条件分别描述，不合并近远范围。显示选择只作用于已完成真实事件，不能删除下一根预判的旧结构范围或增算后续19根。

本节PF21改为不等待翻红，PF22—28补根数/字段/反色边界断言，新增PF29—34见§14.17。完整请求、模型/一次编码及TS仍在P3第3—4步，不拿本节人工数学层证明真实接入或400ms整链通过。

## 7. 离线观察与debug的配合

### 7.1 唯一step可选记录

保留`record_decisions: bool=False`及`XxmStep.decision`，step签名不变。默认关闭的正式query、历史复制和预测clone不采集完整过程，不在HTTP/SeriesEntry/snapshot增加decision数组。只有手动离线观察显式开启；真/假两种模式除decision外的所有结果和快照必须完全相同。

XxmDecision删除rearm及waiting分支；referenceChecks对每个参照分别增加`referenceBroken: bool|None`以记录真实已执行的曾击穿检查，`difPassed`只表示本根DIF严格资格，不能兼任曾击穿结果。未执行写None，不推断True/False。turn保留previous/current/threshold/refBroken/checked；增加结构动作字段`structureId/structureStatus`（可空）即可表述本根确认、回转、取消、首次反色，无需复制完整历史。before保存activeStructureId；观察只记录实际条件值，不再运行选择器来补解释。record_decisions=False路径不分配观察对象；观察True/False所得全部业务step完全相同。

### 7.2 观察字段与资源边界

XxmDecision的structureFollowChecks按实际顺序记录根前旧槽及本根新首次反色的检查，每个旧id本根最多一次；字段为relatedStructureId、direction、originWave（仅price/price_at）、firstOppositeAt、nextSameColorStartBefore/After、nextSameColorCountBefore/After、checked、pricePassed(bool或None)、action(KEEP/START/SKIP_SINGLE/DISAPPEAR/FINISH)、reason。正常有效段结束checked=False/pricePassed=None；单根段结束仍checked=True，若当根破价action=DISAPPEAR，否则SKIP_SINGLE。不得沿用最多两项假设丢掉本根新进入跟踪的真实检查。未进入价格检查必须None，不伪造通过。当前referenceChecks/turn仍只描述当前普通关系，旧动作不改变其含义；默认record_decisions=False不计算辅助记录。

`XxmDecision`完整字段为time/rawSign/before/wave/referenceAfter/referenceChecks/selectionCalls/turn/switched/structureId/structureStatus/structureFollowChecks/branch/reason。before在现state/reference/wave/previousDif上加activeStructureId；referenceChecks保留现stage/candidate/wave/checked/pricePassed/difPassed/reason并加referenceBroken，未执行的bool字段均None；selectionCalls保留实际stage/selected；turn保持previousDif/currentDif/threshold/referenceBroken/checked/reason。结构动作字段只用于离线观察，不是event关联字段别名。

无普通事件时branch只允许leading_zero/reference_switch/segment_changed/structure_following/retained/no_activation；普通事件时使用实际route。当前普通结构首次反色而无普通事件时记录structure_following。旧结构每根的KEEP/START/FINISH/DISAPPEAR分别写structureFollowChecks，不覆盖当前普通分支；旧消失与当前普通事件并存时不能用一个branch冒充全部事件。无rearm/waiting/historical_price_break观察路径。只保存真实执行结果，不重新调用选择器、不从终态反推未执行条件。

保留`history_disappearance_screen.py:observe_rows(bars, *, period, source_identity, check)`作为纯内存单组观察；最多1000根、20秒/256MiB/16MiB，逐根及最终复制前后检查，失败不返回部分成功，无文件/数据库/网络读取，无新CLI模式。正式query普通/debug两种模式均断言decision=None；外改观察返回值不能改计算器。页面debug只展示§5真实辅助事实，没有完整过程就不能声称“本根未检查A”，必要时说明当前页面未提供该项检查记录。

## 8. Wealth页面、请求和研究工具

本节保留环境/debug延迟加载、普通图、四种三角和1000根等既定边界。涉及等待记录、历史撤销展示、结构一形成就停预测的旧迁移要求已由§3/§6替代；后续必须以新正式结果同步消费者，不能仅隐藏事件来冒充后端规则已修正。本轮不修改页面。

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
| `features/index-detail/debug/types.ts`（新，纯类型） | P3建立页面与debug组件的props、扩展快照、动态模块导出和解码函数签名；只用import type、禁止运行时初始化/import副作用；P4再接页面动态装配 |
| `features/index-detail/debug/useIndexDebugModule.ts`（新） | 仅enabled时动态import `./IndexRecognitionDebug`；管理idle/loading/ready/error、加载序号及retry，不执行行情计算 |
| `features/index-detail/debug/IndexRecognitionDebug.tsx`（新） | 动态模块入口，导出debug控制组件、识别/预测debug解码器及详情renderer；独占波段hooks、研究primitive和研究UI运行时导入 |
| `features/index-detail/debug/xxmDebugContract.ts`（新） | P3迁入现adapter中参照/历史/等待/事件关联纯校验，按本文DTO的debug对象校验；不重算算法；P4由动态模块导出/注入，普通路径不静态导入 |
| `features/index-detail/debug/forecastDebugContract.ts`（新） | P3迁入现预判公式/区间/参照转换/历史关联纯校验，并按r4迁移；不调用预判求解器；P4由动态模块导出/注入，普通路径不静态导入 |
| `features/index-detail/debug/ForecastDebugDetails.tsx`（新） | 仅debug的预测精度、参照/路径及区间详情；由卡片注入的renderer调用，不求价 |
| `features/index-detail/debug/XxmDebugDetails.tsx`（新） | 将现XxmResearchDetails改为参照、结构考核/首次反色/消失说明；依据debug对象，不前端推测原因 |
| `features/index-detail/chart/indexChartPointAdapter.ts`（新） | 原日线toDetailChartPoint原样迁出为纯函数，普通图与debug图共用；不改值、不格式化后比较 |
| `features/index-detail/chart/IndexChartWorkspace.tsx` | P3先把悬停改为只读普通字段的XxmSignalDetails及必要调用；P4去除daily-wave运行时import及hooks/primitive创建，保持同一组件位置，接可选debug扩展和renderer；本地r4正常识别继续存在 |
| `features/index-detail/chart/IndexMinuteChartWorkspace.tsx` | P3同步正常简要悬停及必要调用；P4传本地enabled/debug模式和解码器、接可选debug详情；不加分钟波段功能 |
| `features/index-detail/xxm/{types,adapter,apiClient,useIndexXxmLayer,XxmLayerUi}.ts[x]` | P3完成r4身份、正常/debug DTO、纯解码、客户端返回和原截止时间的Hook交接、普通字段view model/绘图及XxmSignalDetails；P4接页面环境资格、模式及动态注入，XxmLayerUi不静态导入辅助详情 |
| `features/index-detail/xxm-forecast/{types,adapter,apiClient,useXxmForecast}.ts` | P3完成r4身份、正常/debug DTO和纯解码、客户端返回与原截止时间的Hook交接；正常卡只消费display等普通字段；P4接enabled/effectiveDebug、模式切换与动态注入 |
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

- 普通XxmResponse根包含tsCode/period/algorithmVersion/specHash/source/points/events/meta/dataStatus；正常source不含inputId；正常points不含活动参照和activeStructureId；正常events为id/time/direction/type/displayOnChart，标志必填严格boolean。
- debug响应的必有debug对象包含sourceInputId、同time的debug.points、同id的debug.events、structures。普通请求不允许出现该对象；debug请求要求符合本文各状态对应的对象形状。
- 保留XxmPeriod四种；事件仅DULL/STRUCTURE/CANCEL，旧RESEARCH_HISTORICAL_WITHDRAWAL/STRUCTURE_DISAPPEARED必须被新decoder拒绝，不在绘图层隐藏或改名兼容。
- XxmMarker只依赖正常event的id/time/type/direction和源DIF；markerGeometry/XxmMacdPrimitive不得强读debug route/history。完整events保留，只有displayOnChart=true生成marker，同根共同锚定真实时刻和源DIF，沿现有避让/拥挤汇总规则绘制；不按time合并或删事件。悬停模型的events数组必须完整保留同根全部事件；普通渲染只读displayEvents，debug渲染才读完整events，不能把“模型保留”误写为普通悬停全部显示。
- XxmViewModel.byTime正常只关联point和events；增加可空debugDetail只在通过debug解码时构造。模式1的debugDetail.structures为必有数组：以time对应debug.points、以普通event.id对应debug.events，保留该时刻辅助点的activeStructureId及同根辅助事件relatedStructureId引用的记录；普通point/event不存在这些辅助字段，不得直接读取。同时保留formedAt<=point.time且trackingEndedAt为None或>=point.time的响应结构；按id去重、formedAt/id排序。由已校验debug.structures关联，不依赖本根有事件，不只寻找activeStructureId，不重新用价格/DIF算状态。模式0不创建辅助对象。正常按ordinaryState/direction显示真实当前状态。新业务没有等待，普通或debug均不能继续生成“待重新钝化”；首次反色记录在debug说明，正常标记仍由真实形成事件驱动。

#### 8.4.2 正常与debug解码分开

`decodeXxmResponse(raw, {tsCode, period, debug, decodeDebug?, check})`新增在现adapter.ts：接unknown，不直接类型断言为成功。检查根和嵌套字段集合、值类型、正式r4版本/hash、period/标的、合法时刻、数值有限/正收盘、state-direction关系、meta范围/count、source/dataStatus及EMPTY约束。points按time严格升序唯一；events按time非递减、id唯一，同时间不同id必须接收并保留后端顺序，不能按time去重或只保留末事件。displayOnChart严格检查、不补默认；False项仍留response.events/byTime.events及debug关联，仅markers和byTime.displayEvents按True筛选；普通renderer读displayEvents，debug读完整events。前端不根据类型/当前状态另猜显隐。普通没有历史ID，不能要求不存在的历史数组为[]，也不能跳过正常检查。

`buildXxmViewModel`消费已解码的正常数据和真实DetailChartPoint，保留现逐时刻close/dif/dea/hist严格相等及indicatorVersion校验。不得用显示精度比较、容差、重算、补值。

当debug=1：要求decodeDebug已由动态模块提供；先完成正常检查，再调用`decodeXxmDebug`检查辅助对象，按time/id与正常points/events精确配对，补齐本窗口引用的更早历史。按§5.3迁结构考核/首次反色/消失及恢复前后记录关系检查，不要求所有历史形成事件都在可见窗口，但被引用的记录必须存在。错参照、悬挂ID、重复ID、越过computedThrough、错方向、错结束原因均拒绝整份识别结果，不保留旧三角或把失败当EMPTY。普通/debug任一不合格仍保留正常K线。

`XxmLayerUi`正常导出XxmLayerStatus与XxmSignalDetails。简要详情含“顶底识别·r4”、当前状态、当根displayOnChart=true事件和对应时间；被隐藏旧消失只在debug事实详情核对，不在普通悬停再显示。debug详情renderer仅在debug模块已加载且该响应有合格debugDetail时追加；即使本根events为空、activeStructureId=None，只要debugDetail.structures非空，也须展示已有结构事实。形成/首次反色/下一同色段/正常停止或消失时间均用后端字段，正常停止不画消失marker。结构记录状态截至response.source.computedThrough；悬停较早K线时，不能用该记录后来终态替换该point.ordinaryState。可列明“截至请求时点的记录”及实际日期，不自行推断悬停当根的未提供状态或原因。

#### 8.4.3 hook和请求生命周期

`useIndexXxmLayer`参数新增：`enabled:boolean`、`debug:0|1`、`decodeDebug?`。资格必须同时满足`enabled && import.meta.env.DEV && 上证 && 四周期`。生产即使调用者误传enabled也不发请求；production返回unsupported且primitive=null、macdPrimitives=[]。不再保留day无需DEV的例外。

请求key完整包含：正式algorithmVersion/specHash、tsCode、period、真实首末时刻、points.length、indicatorVersion、effectiveDebug（传给hook的debug参数）。缓存只在同key同身份复用；模式变化先失效旧序号、abort并清空旧辅助结果。不能把debug对象删字段后复用为普通对象。

数据不完整按原loading/error分支。URL开启debug但decoder尚未加载时，传给hook的debug=0，正常请求继续；不得先发模式1后临时静态import validator。普通数据仍按现图表状态可用，加载期间不展示旧辅助信息。

fetchXxm保留现scheduler的xxm通道、5秒和外部abort，截止时间交接及返回结果严格按§8.3.5；finally清timer和abort listener；params加debug?:1，普通省略、debug显式1；路径、日期、limit不改。模式变化等于新一次请求，不自动重试。所有apply/catch必须匹配请求序号、key且未abort。

primitive只有资格成立时创建，按标的/周期稳定；结果更新调用setMarkers，失败/关闭清空；正常的debug显隐不重建图。label布局/颜色/圆点规则不修改。

### 8.5. 关键高低点预判

#### 8.5.1 正常类型和显示

ForecastResponse改为§5.4普通字段；把源输入、精度策略、所选参照、下一根条件和精确区间移入debug对象；删除旧等待和多步字段。display/applicabilityText/invalidationText等必要条件仍正常返回，不因隐藏公式删掉真实适用条件。XxmForecastCard继续仅消费正常display、status、截至时间和重试，不在前端求价或改边界。

`adaptForecast(raw, {period,asOf,debug,decodeDebug?,check})`检查正常键、正式forecastVersion/forecastSpecHash/detectorSpecHash、四周期、requestedAsOf/mode、status/state/direction/唯一target/barsAhead/null关系、refreshAfterMs与display字符串。不能继续要求正常响应必须有relations/sourceInputId等已移走的字段。

`decodeForecastDebug`按§5.4固定字段校验所选B/A、每参照突破依据、下一根条件及其精确区间、未决精度区、一步EMA和六字段参照。已有DULL/B且A未算时，普通conditions只接受“近参照失效”的条件事实，不接受“总体钝化必定消失”；STRUCTURE原参照破则直接失效。另独立解码structureFollowConditions：允许与当前方向不同，以relatedStructureId及完整originWave核字段/时间/区间/表达式，不得套用普通selectedReference或当前state的允许outcome集合。删除旧P/C关系树、20步表达式、等待、仅BOTTOM的NextBarOutcomes和ZERO_RESET校验，不能把旧数组留空作兼容。前端不求价、选参照或从几条记录推断规则，普通card只消费后端最终display及必要适用/失效文字。

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

本表列最终交付要求，不把P4条件提前算成P3已实现：P3执行§11.4第4步的身份/普通及debug纯解析/客户端返回/同一deadline/普通悬停及必要调用测试；本表的DEV禁用、URL与模块加载、动态注入、辅助详情、波段及环境页面专项在P4实施验收。同一测试文件含两类节点时逐节点登记归属，不用整文件排除掩盖P3应通过的用例。

| 测试位置/新增组 | 必须断言 |
|---|---|
| `model/indexRecognitionAvailability.test.ts`（新） | DEV true/false、上证/其他、无debug/0/1/其他；生产debug=1仍正式和debug都false；没有任何Lake依赖 |
| `debug/useIndexDebugModule.test.tsx`（新） | false不import；true才import；退出前迟到resolve/reject不发布；重试不算波段；模块对象不存业务数据 |
| `xxm/adapter.test.tsx` | 正常/EMPTY/DELAYED独立新合同；旧r2身份/错hash/混合源/重复日期或ID/NaN/state方向非法拒绝；正常strict原值对图，模式字段越界拒绝；普通无历史字段仍通过 |
| `debug/xxmDebugContract.test.ts`（新） | 正常time/id和debug双向对应；悬挂/重复/错期/错原参照/结构关联/旧等待拒绝/窗口前形成记录/根末NONE但仍有事件，合法及非法均覆盖 |
| `xxm/useIndexXxmLayer.test.tsx` | day生产也无请求/primitive；本地day与三分钟仅支持集合；模式/indicatorVersion/key隔离、取消、迟到、失败清旧标记；debug decoder未ready不发请求 |
| `xxm/apiClient.test.ts` | 普通省略debug、debug明确1，原路径/日期/limit不变；5秒、scheduler、外部abort、失败finally清理 |
| `xxm/markerGeometry.test.ts` | 正常最小event含必填displayOnChart；True生成标记，False保留事实而不画，不依赖debug字段；不改变原颜色/位置/连线/拥挤规则 |
| `xxm-forecast/forecast.test.tsx`、identity测试 | 正常公共DTO可用；debug解码只在显式模式；r4双身份、旧/混合hash拒绝；各状态必要display与空值；不拿r2输出当预期 |
| `debug/forecastDebugContract.test.ts`（新） | 新下一根所选参照/条件/未决区间及六字段参照；近有解A未调用，近失效不等于总体消失；旧entry/等待/20步/CONFIRMED/ZERO_RESET格式全部拒绝 |
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
| 预测 | 原总请求4秒内，计算/缓存处理另受400ms更早截止约束；32KiB；只取1个未来端点/原90自然日日历搜索上限；250根校准；刷新60000ms | clone/恢复/有限边界求解/全部实际涉及的源精度组合/必要step核验/文本/模型/编码都在400ms；缓存命中的本次投影编码也计时 |
| 日线研究 | `index_detail_daily_wave.spec`业务读取开始8秒，内存256MiB，响应2MiB；主范围800、历史补查500、总1300；输入1MiB/日历2000行；连接2秒/查询3秒/锁1秒/清理0.5秒 | 范围仍2023-10-24—2026-10-21及来源实际可用截止；不补行，前段不完整真实标记；前端手动start至核对提交整链10秒 |
| 普通K线 | 本机20次有界样本P95对既定800ms；指数日线请求1000 | 真不足1000如实报告，不能补数据；数量变更与本轮无关 |
| 前端识别/预测 | 原scheduler及5秒取消 | 每次异步返回及最终提交前验有效序号/模式/时间；不能只有网络timer，解码超时也不显示迟到结果 |
| 单组测试 | 每组最多60秒 | 超时立即停止查因；无后台任务/恢复文件，不捕获旧算法作expected |

这些是验收上限，不是当前已测成绩。源20000/5000来自现本地分钟reader常量，LLD只登记，不复制成新配置；日线已有读取边界保持其当前实现，不为凑表限制再改SQL。缓存失效或失败重试仍从本次完整输入重算并遵守各自预算；失败不发布半份结果、不静默截断引用或提高限额、不落盘续跑。

错误沿现登记：识别`XXM_REQUEST_INVALID`400、`XXM_NOT_SUPPORTED`404、`XXM_SOURCE_CONTRACT_INVALID`500、`XXM_BUDGET_EXCEEDED`503、`XXM_QUERY_FAILED`一般500（下述现有缺reader分支例外）；来源未就绪沿现200的EMPTY/DELAYED状态，并非捕获所有错误。预测使用现XXMF对应映射；波段沿`DAILY_WAVE_INVALID_REQUEST`422、`DAILY_WAVE_SOURCE_INVALID`503、`DAILY_WAVE_CALCULATION_FAILED`503、`DAILY_WAVE_BUDGET_EXCEEDED`503。当前`query_service.load_entry`缺本地分钟reader时显式以XXM_QUERY_FAILED/503抛出，与登记中的一般查询失败500不同。此处记录并保留该现有状态，不顺手改API行为；正常本地分钟装配/预测资格应先拒不支持，此分支仍用直接query调用反例覆盖。必须保持一般失败与缺reader这两个现有分支的状态码，不把所有QUERY_FAILED统一改503或500。实际错误码以[异常登记](../../system/exception-code-registry.md)及现处理器核对，不能临时增加。生产未注册路径由原框架404，不进入来源或计算。

服务端保留现只读源和会话管理，取消向上传递、finally释放信号量/连接/共享加载订阅；不因一个请求取消就修改另一请求已发布结果。新的SeriesEntry/完整预测缓存只在全部校验成功后发布。不能捕获CancelledError转成功或缓存异常为空结果。debug文字不得返回凭据、SQL或本机绝对路径。

本轮不触发数据读取。实施时涉及真实源的最小核验先限定标的/周期/日期、原字段和上限；复用仍有效证据。若需全数据集明细读取须另按根AGENTS取得明确范围批准；“只读”不是全局读取的自动许可。

## 10. 清退清单与有效能力迁移

本节是P5逐文件及函数处理范围。有效人工样本必须先迁到唯一r4，活动引用清零后才删代码。不得因清退扩大为删除报告目录、原始行情、截图或其他工作区修改；不迁移旧算法结果生成器和旧执行协议。

### 10.1. 清退顺序与硬边界

1. 新规则按§2—7和§14独立预期实现并验收；不读取旧源码、不捕获旧结果、不启动新旧双组对账。
2. 迁移所有查询新建、历史位置复制、增量计算、预测clone、类型/解码/缓存身份；不保留r2模式、参数、回退或执行入口。
3. 保留工具先解除对旧算法源码、旧SHA和旧结果读取器的依赖；纯行情/日历/原图继续按明确来源核验，不能把来源校验一起删除。
4. 所有调用迁完、唯一r4和保留工具通过后，才删除本清单内旧实现、专属执行器和专属测试。旧模块的生成缓存只按对应模块清理，禁止删共享解释器环境或用户其他数据。
5. 删除前检查本清单各文件当前git状态。未跟踪文件也在清单核查范围；出现清单外调用方或他人正在修改的冲突，先停止并说明，不擅删、加兼容层或移到.txt/Markdown代码块伪封存。
6. 源码清退不得删除原CSV/JSON/图片或重写Git历史；仍有价值的独立研究结论按其用途保存，当前开发文档中的废弃要求必须直接删除。CLI和README中对应活动命令清零，不为死链恢复旧代码。

### 10.2. 研究主目录逐文件处理

本节路径前缀统一为 `scripts/research/index_market/xxm/`，每行都是一个实际文件。表中“迁出”只指仍被当前r4验证需要的既有能力，不为旧试验增加新框架或新运行模式。

| 文件 | 最终处理与保留边界 |
|---|---|
| `__init__.py` | 保留主题包；更新说明，不从中注册旧实现。 |
| `r4_reference_trial.py` | 新规则按§14及P3/P4独立验收、有用观察能力迁出及引用清零后，在P5，删除研究识别类、复制step、研究Spec和包装恢复。不是把它改成继承正式r4的第二份实现。 |
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
| `rearm_discrimination.py` | 删除旧A1基线对账和模拟runner；仍适用的原价格/DIF边界字面样本迁新回转/首次反色测试，旧等待结果只用于拒绝反例。 |
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

### 10.4. 主题测试逐文件处理

前缀统一为 `scripts/research/index_market/tests/`。删除旧专属测试前，已批准且仍适用的反例先迁当前r4单组测试；删除不是跳过错误或降低覆盖。

| 文件 | 处理 |
|---|---|
| `test_xxm_calculator.py` | 迁当前正式r4；保留独立人工核心、1%、翻色、原参照和恢复安全；历史生命周期按§14重写，旧等待仅作拒绝反例；移除旧r2零切段/最强选峰专属预期和旧frozen账本相等测试。 |
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
| `test_xxm_top_activation_real_math.py` | 仅保留meet/minus/interval纯数学预期；删entry_domains/proof及旧报告身份测试。r4选峰/求价另用§14及§5.4.4独立字面预期，不沿用最强排序oracle。 |
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
| `test_xxm_rearm_discrimination.py` | 旧A1对账suite删除；当根收盘/原DIF边界迁新r4；等待结果改为新回转/首次反色用例或旧输入拒绝用例。 |
| `test_xxm_history_disappearance_screen.py` | 保留dif_diagnostics/history_record/event_signature的独立字面测试，补§7 observe_rows及合法B→A后原DULL/结构不同参照；删旧runner/保护/frozen/候选排序测试。 |
| `test_xxm_history_replacement_screen.py` | 仅保留ordinary_index的时刻/唯一性/方向反例；删除local_followup和旧延长历史/runner测试，不将旧替换政策迁r4。 |
| `test_xxm_confirmed_cases.py` | 保留来源明确的作者截图观察及其原预期，迁正式r4；如真实观察不符应报告，不改原预期凑通过。 |
| `test_xxm_key_point_forecast.py` | 保留独立求价/精度/区间/禁止中点概括等有效测试，按唯一r4和全部路径修正；不依赖旧算法生成expected。 |
| `test_xxm_forecast_reference_paths.py` | 迁正式r4顶底B→A/零日路径，删除研究候选路径类及旧排序预期。 |
| `test_xxm_forecast_display.py` | 保留当前正式r4文本和条件显示，解除经key_point_forecast.frozen间接导入旧账本。 |

#### 10.4.1 跨层现存夹具消费者必须迁移

| 当前消费者 | 要求 |
|---|---|
| `tests/web/test_wealth_index_detail_xxm_api.py` | 唯一r4请求/来源/DTO/恢复、普通与debug投影及本地/生产门禁。旧API JSON不作新金样本。 |
| `tests/web/test_wealth_index_detail_xxm_forecast_api.py` | 第239/268/587附近读取r2 API夹具、301及594/625附近读A1/R1旧响应的测试分开处理：新r4金样本用独立输入/手写期待；旧响应只用于明确“旧版本必须拒绝”的反例，不能改几个身份字段后声称当前完整合同。 |
| `tests/web/test_xxm_shared_loads.py` | 保留并核普通/debug及识别/预测共用读取不串模式，不借清退删除并发/取消测试。 |
| `wealth/src/features/index-detail/xxm-forecast/identity.test.tsx` | 新r4身份/旧r2拒绝；不再把r2报告目录读成current()。 |
| `wealth/src/features/index-detail/xxm-forecast/forecast.test.tsx` | 原第132附近报告JSON消费者改独立r4当前合同，不能仅换version/hash。 |
| `wealth/src/features/index-detail/xxm-forecast/r1Contract.test.tsx` | 旧多步路径/等待成功样本撤销，按§5.4/§6迁下一根条件与拒旧测试；旧r1/r2 JSON只保留拒绝反例。 |
| `wealth/src/features/index-detail/xxm/rearmContract.test.tsx` | 统一结构记录/悬挂引用用独立字面fixture，旧等待只验拒绝；旧报告不伪装当前。 |
| `wealth/src/features/index-detail/xxm/useIndexXxmLayer.test.tsx` | 当前身份迁r4，补本地普通/debug与生产无请求；不再expect r2。 |
| `wealth/src/features/index-detail/xxm/xxmFixtures.test-support.ts` | 独立明确构造普通/debug不同投影，输入/expected不依赖待测adapter生成。 |
| `wealth/src/features/index-detail/xxm/types.ts` | 唯一r4识别身份，配套adapter拒绝旧身份，无r2选项。 |
| `wealth/src/features/index-detail/xxm-forecast/types.ts` | 唯一r4预测身份；识别器身份/hash与正式r4一致，无r2回退。 |

`tests/test_index_detail_daily_wave*.py`、`tests/web/test_wealth_index_detail_daily_wave_api.py`、`tests/test_index_detail_daily_wave_connection.py`及前端daily-wave测试全部保留；只按本地/生产/debug新门禁调整输入和调用，不改变四种三角、极值/色段/价格候选定义、真实1000根限制或原始数据精度。

### 10.5. 独立验收矩阵与删后引用检查

| 断言 | 独立输入与必须抓住的反例 | 落点 |
|---|---|---|
| 两位纯算术保留 | 40.057→40、−8.086→−8.0、41.01→41、40.99→40、41.9与41.4同41、0/±小数/数量级及bool/NaN拒绝；expected字面给定 | 最小化near_first_review与其人工测试；不得构造产品计算器或读源码/数据 |
| 旧依赖已解除 | 在临时目录中只提供已声明原始CSV/JSON/图像，不提供top_reference_priority/top_return_reference/旧r2源码；保留工具可运行。篡改原始数据SHA仍拒绝 | local_extrema_study和纯取窗/量图测试 |
| 无第二套识别 | 页面debug指向真实r4活动参照、离线观察只记实际分支；保留工具不能调用choose_reference/inspect_prefix/advance_bottom/display_events产生新标签或遮事件 | 产品debug tests及静态导入/符号检查 |
| 当根切换与历史 | 人工A/B价与DIF、零日/缺A/等号/晚合格/结构考核/首次反色边界，原DULL事件B保持、activeA；旧结构从首次反色起比价、单根不结束、首个有效同色段结束正常停止，正常结束不报消失 | 唯一正式calculator人工测试，从原r4-v2 R4-18—24迁移 |
| 身份与内存复制 | r2/研究v1/研究v2旧快照不能作为正式r4进度；坏输入拒绝后正常输入仍成功；旧API JSON仅拒绝反例 | 恢复、真实调用方及前后端合同测试 |
| 新规则完整结果 | §14逐根事件/状态/参照/结构、连续/恢复/历史asOf；不能只数标签或要求等同旧v2 | 唯一新r4及独立预期，不运行旧等价进程 |
| 默认不触发研究 | 本地普通URL和生产任何URL不得加载辅助研究包/请求/三角；本地debug=1且点击波段核对才计算；生产日线也无r4请求/信息 | 页面/API/浏览器真实验收；不能只用mock声称整个环境门禁通过 |
| 删后仍工作 | 删除清单中的旧模块和已知生成缓存后，当前核心/预测/API/debug/峰谷工具的定向测试通过，原市场数据/历史报告字节未改 | 全部迁移完成后再执行，不拿删前成绩充数 |

#### 10.5.1 静态和动态引用清零

1. 使用当前AST列所有活动Python的Import/ImportFrom及明确动态import路径；核`.mjs/.ts/.tsx/.sh`中的模块/命令和生成Notebook字符串。以清单中每个旧模块路径、旧类名、旧CLI模块名检查，不能只搜r2字串。
2. 必须为零的运行引用包括：TwoDigitTurnCalculator、ObservedR2Calculator、BottomDullRescueCalculator、ReferenceGateCalculator、TopCurrentCloseCalculator、PriceBeforeSelectionCalculator、NearFirstCalculator、ReturnReferenceCalculator、旧研究R4Calculator，以及旧replay/candidate动态加载入口。
3. 历史Markdown中的叙述或旧JSON的版本身份不算运行引用，不能为了让rg无结果删除有效事实。测试中的旧version/hash可出现，但必须是“拒绝旧身份”的明确反例；不能仍有旧版本成功路径、实例化或产生旧算法结果。
4. 扫描旧研究MODULE.main/argparse入口、README活动命令、`runpy`/`spec_from_file_location`、Notebook code cells。只删Python源文件但保留可执行Notebook或动态复制源码，不算清退。
5. 对已清退模块精确删除对应__pycache__项，不做整个repo/环境缓存清空；检查无软链接、转发文件、`.py.txt`、兼容别名或r2算法选择。Git历史不动。
6. 删除后从干净新Python进程导入所有现入口，按现pytest发现配置收集目标测试；不skip失败、不把旧测试仅移出testpaths。保留测试/工具在旧文件缺席时必须真实执行到原始材料校验。
7. 根三份架构、研究依赖方向、必要后端/Wealth测试、类型/构建及文档链接检查按本文相关章节统一执行。本章节不另造数据库/外部源验收，也不授权重跑922根。

## 11. 后续开发顺序、前置条件与上下游交接

新规则并入重新安排后的P3，先修识别，再预测，再HTTP与必要前端，P3整批独立验收后才进入P4。普通/debug、生产禁用和最终旧代码清退的既定范围不变。本次三项修正尚未开发，§15—17均只记录此前基线。先依§18修核心/内部及预测，限定验收后按专项迁工具、受控对比并review，再继续P3第3步，不用旧成绩代替当前验收。

### 11.1 保留能力的明确落点

§10出现的“迁移有效能力”按下面落点执行，不能临时增加通用框架或保留旧容器转发：

| 旧能力 | 唯一落点/不迁的部分 |
|---|---|
| 研究r4真实选峰/救援/转折观察 | §7唯一step的可选内存记录及history_disappearance_screen.observe_rows；不入SeriesEntry/HTTP，不保留Observed类/第二份判别 |
| 两位算术 | 最小化`near_first_review.decimal_value/quantize_dif`和`test_xxm_near_first_review.py`；完整类/重放不迁 |
| 人工首次、1%、同根切换、结构考核/首次反色和取消边界 | 现`test_xxm_calculator.py`及恢复/输入tests；研究wrapper/旧Spec测试不迁 |
| 独立有理数/求价/源精度案例 | 现`top_activation_math.py`、`forecast_expectations.py`及现`test_xxm_key_point_forecast.py`；不得import产品来生成expected |
| 纯数值窗口/来源/日历/截图 | 最小化现`saved_minute_window.py`、`local_extrema_study.py`、`peak_image_measurement.py`、纯事实`reference_window_review.py`；不在这些工具继续输出selected/eligible/标签 |
| 正式来源/路由/显示核验 | 现`daily_window_precheck.py`、`xxm_page_request_audit.py/.mjs`、`xxm_forecast_display_audit.py`，只有唯一r4原路由，无candidate模块参数 |
| 旧compare ID/记录完整性中的有效反例 | `test_xxm_snapshot_validation.py`、当前web合同及debug合同tests的独立字面输入；旧r2/r4配对、原因猜测、完整runner不迁 |
| 旧report复制预测/候选实现 | 不迁实现；仍适用的字面数学反例迁上述现预测tests，原材料/结论保留；无新r4通用框架 |
| 同根双报后隐藏`display_events` | 删除而不迁；r4必须取消前换A，正式events是真实结果，不允许事后抹事件 |

没有在上述落点和§10名单内的能力不因“也许有用”新增开发。实施时新发现真实调用或多人改动冲突先说明，不能随意扩删。

### 11.2 保留工具的逐函数交接及仅内存要求

以下是§10各行的唯一细化，当前只静态核对，均待后续获准实施。不新增验证框架、算法副本、HTTP接口或结果目录。

#### 11.2.1 旧输入读取器与独立数学

| 现文件/函数 | 固定处理及真实依据 |
|---|---|
| `scripts/research/index_market/xxm/frozen_inputs.py` | 整文件删除。`expected_unit/expected_steps/assert_expected_recognition/forecast_inventory`属于旧账本；`load_frozen_inputs`第35—37行缺DEA时按DIF/柱反算，不能继续构造新r4输入。原CSV、JSON、manifest和作者观察不删、不重写。 |
| `xxm/acceptance.py` | 只留`sha/load_source/collect_readouts`。`load_source`沿原CSV字段读取真实DEA并验证原数据SHA；`collect_readouts`保留27条作者数值事实及图片出处。删`replay/main`、产品计算器/Spec及`load_frozen_inputs`导入、旧baseline/软件对照结果写入和CLI。 |
| `xxm/top_activation_math.py` | `pair/daily_options`和独立Fraction公式保留；`expectations`只迁仍适用的独立算术字面例，删除多步入口/目标结果生成；合法零及相邻1%按§5.4.4和PF08手算，不复用旧门槛预期。 |
| `xxm/top_activation_real_math.py` | 只留`meet/minus/interval`纯区间数学及必要`pair`依赖。删`entry_domains/proof/main`、旧报告路径/版本常量及来源、日历、保存模块导入。`entry_domains`当前第53行按DIF强弱排序，是旧选择政策，不可换身份后作为r4预期。 |
| `xxm/forecast_expectations.py` | 删除未使用的`expected_unit`导入，解除旧冻结模块依赖。保留`fraction/contains/regions/assert_partition/coefficients`。删除`verify_changed_forecast`及MATH_KEYS：它硬编码dif_turn目标hist>0、无transitions/prefix等旧断言，唯一消费者reference_rescue_acceptance也将删除，不能继续当r4 oracle。 |

独立算术样本只迁当前单步目标仍需要的部分。当前求解预期必须使用§5.4.4 M1—M5及§6.10 PF01—34，不能调用正式预测器生成expected，也不能复用多步入口/目标关系作为当前答案。`coefficients`等纯函数若仍被保留测试使用，必须限定其数学前提；不能作为一般负值/跨零求解器。

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
其`request`必须验证HTTP状态、真实目标DTO、字节与时限，区分normal/debug；只按本次已声明的有限周期和asOf核验，不自动跑全部日期或周期。
20次性能采样、冷热及并发检查仍遵守原预算；只运行本轮已明确授权的范围，不由一次入口默认展开所有历史窗口。

两个Python入口的执行参数在本轮固定为：`--periods`必须显式给出day/m60/m90/m120的非空去重子集；`--as-of`可省略表示latest，非空仅接受YYYY-MM-DD，日线用该日，分钟映射该日15:00:00+08:00且必须已完成；`--mode`为normal/debug/both，默认normal；`--samples`为1或20，默认1，20仅在获准性能验收时显式使用。--candidate/--output均不再接受；README和所有调用同次迁移，不留忽略参数的兼容壳。mjs由父进程传base及相同周期/模式/时点，不接output位置参数，也不偷偷补默认全周期。

单周期/单模式采样为一个≤60秒的有界组，超时即停止报告，finally含关闭server/socket和恢复patch，不在后台继续下一组。latest记录实际完成截止，不把所有分钟末根强断为当日15点；显式asOf非法仍按原API错误处理。原鉴权、真实源和原请求预算均不放宽。

`xxm_page_request_audit.mjs`固定要求：

1. 删除`output`参数、`writeFile/resolve/persist`及所有完整response/VM保存；requests/rounds只在内存，错误body不写文件。
2. 继续现Node/esbuild、`bundle:true/write:false`及内存data-URL模块，不安装依赖；显式采用本地开发客户端所需的编译环境；只导入pure decoder/客户端，不把React图层及CSS带进Node执行。该工具不替代真实production build。
3. 编译入口导入现`INDEX_DAILY_HISTORY_LIMIT`供日线K线/九转使用，不再硬编码300；分钟500不变。
4. 普通请求没有debug对象；debug只允许新structures/参照/单步条件集合并由动态decoder核验。旧rearmContext/bottomHistories/pendingRearmId在普通和debug两种模式均拒绝，不能以“辅助字段”继续接收旧格式。
5. 两种模式公共字段/标签ID/显示文本在同一固定输入下相等；来源变更/日期切换时按原规则终止本次比较，不硬配。
6. 指定周期不可用时如实报告；不得丢掉失败周期后说四周期通过。该Node客户端工具不是实际浏览器或生产构建验收。

#### 11.2.5 身份与测试交付的当前要求

新P3的完整Spec、模型、普通/debug字段已在§2—6确定；按§11.3先同步原合同文书，再按§11.4第1—4步迁内部与公开消费者。测试hash显式来自对应完整Spec，不预填r2、旧r4或占位身份；业务expected独立手写，不随实现结果重生成。

P3同时完成§11.4中的纯debug类型/两种解析器、客户端返回和同一deadline的Hook交接、普通悬停及其日分钟调用和受影响fixture；P4接动态模块和完整页面。P4保留工具及其尚未迁移的专属执行测试在P3不运行、不计通过；P5旧runner保持既定清退归属。按节点列清未执行原因，不删除/改低预期、不以skip/xfail或整文件过滤掩盖本属P3的失败；通用核心/恢复/输入/源精度及P3消费者测试仍须通过。
清退后测试收集须覆盖新数学、纯窗口、离线观察、普通/debug HTTP、工具RAM及异常清理；静态检查不能替代真实入口执行。
针对工具补负例：缺旧模块仍可import；禁止旧动态candidate加载；不创建结果目录或写完整body；启动/请求/Node失败后清理及包装恢复。
真实分钟不可用时保留该周期“未验收”并说明原因；不得把日线或人工替身抵充。P4按已声明四周期完成条件判断，缺必要真实证据不能宣称整批通过或据此进入P5。
若管理员后续批准暂缓某周期，先同步产品/方案/LLD的验收范围再继续；本轮不默认得到这种批准，也不重问已确认算法。
上述均为工程细化，无新增算法、产品开关或需要重新拍板的规则；先补进原方案/LLD，再编码。

### 11.2.6 直接调用方的确定迁移清单

下表是实施时必须逐一迁移的真实调用位置，不是可选范围。P3迁运行时/本批测试，P4工具在首次使用前整体迁移，P5删除明确旧执行器；不得只改API而漏掉直接调用query的Python消费者。

| 当前文件/调用 | 处理要求 |
|---|---|
| `src/biz/api/wealth/market/index_detail_xxm.py` | P3日线build增加debug；发送同一已校验bytes，不二次编码 |
| `src/biz/api/wealth/market/index_detail_minute_xxm.py` | P3同合同，保留分钟来源/权限；P4按本地能力装配 |
| `src/biz/api/wealth/market/index_detail_xxm_forecast.py` | P3预测build的debug和bytes，P4同Settings传入reader |
| `src/biz/queries/wealth/market/index_detail_xxm/forecast_query_service.py` | 内部持识别query、使用load_entry而非另跑一份算法；新P3第1步先迁共享识别进度，本文件/预测身份及完整结果按第2—3步迁移 |
| `tests/web/test_wealth_index_detail_xxm_api.py` | P3直接build和_response断言改按目标合同；保留来源、恢复、历史及失败反例，不只替换hash |
| `tests/web/test_wealth_index_detail_xxm_forecast_api.py` | P3直接build结果解析bytes；旧r2/A1/R1响应只留明确拒绝反例，P4环境验收 |
| `scripts/research/index_market/tests/test_xxm_snapshot_consumers.py` | P3第1步验真实query/恢复；第3步受影响响应按bytes |
| `scripts/research/index_market/xxm/daily_window_precheck.py` | P4仅保留§11.2.3的窗口/隔离客户端，使用前完成bytes/模式及相关测试迁移；P3不执行或用作验收；旧build计时/check/capture包装随旧runner清退 |
| `scripts/research/index_market/xxm_page_request_audit.py` | P4保留原真实只读/鉴权计时，适配bytes和模式，finally恢复、不写响应文件；P3不执行或用作验收 |
| `scripts/research/index_market/xxm_page_request_audit.mjs` | P4与Python父入口同次迁新客户端返回及普通/debug解析，去落盘；P3不执行，不静态导入辅助实现充当普通模式 |
| `scripts/research/index_market/xxm_forecast_display_audit.py` | P4使用前同步新公开模型和模式，移除candidate/旧display替换及落盘；使用唯一正式r4；P3不执行或用作验收 |
| `scripts/research/index_market/xxm/bottom_history_acceptance.py` | P5删除旧build/_response计时及来源runner；有效独立样例先迁出 |
| `scripts/research/index_market/xxm/reference_rescue_acceptance.py` | P5删除旧build包装及比较；不让它继续当正式r4入口 |
| `reports/xxm_bottom_history_precheck_20261016/run_budget.py` | 已在§10.3.2具体删除名单；P5清退旧query/预算运行器，保留原报告 |
| `reports/xxm_forecast_range_precheck_20261014/http_precheck.py` | 同上，旧query直接调用随文件清退 |
| `reports/xxm_forecast_range_implementation_20261014/http_acceptance.py` | 同上，旧forecast build替换随文件清退 |
| `reports/xxm_minute_reader_optimization_20261014/http_precheck.py` | 同上，旧build包装随文件清退 |

`query_service.py`内部_response/历史投影互调与SeriesEntry聚合在同一实现中一起更新。`tests/web/test_xxm_shared_loads.py`保留并发/取消/共享来源，受影响字段按P3第3步同步。Wealth直接调用为`xxm/apiClient.ts→adapter.ts→useIndexXxmLayer.ts→日/分钟工作区`及`xxm-forecast/apiClient.ts→adapter.ts→useXxmForecast.ts→页面/右栏`；P3第4步必须整条迁移，不能把新外层返回结构留到P4处理。daily-wave原合同/算法不变，仅P4调整环境/debug生命周期。

### 11.3 P3开工前置检查

1. 核对日线合同§10、分钟合同§8和预测方案§36的目标入口与本文§2—7一致。本轮已同步这些文书；实施日必须重新核验没有字段/版本/空值分歧。发现分歧必须先修文档，禁止边编码边选择口径。
2. 核实施当日calculator/types/snapshot/query/预测/schema/API/客户端/decoder/Hook/工作区/离线工具的全量引用与dirty文件边界；本轮CodeGraph及源码依据在§0.2，不代替实施时引用清单。
3. 依§14及§6.10先确认独立预期和测试落点；旧正确安全检查保留，旧底部等待、跨根借价首次及无限跨段撤销预期不再是验收答案；首次反色/分隔/零柱价格失效、单根跳过/有效段结束及同根显示均须覆盖。新身份、解析与恢复拒旧必须有正常变化的反例证明不过度拦截。
4. 必须获得对应P3执行授权；按下一节顺序实施，中间只验对应内部能力、不发布混合版本，不擅自进入P4/P5。此前通过结论不能替代本次新规则验收。

### 11.4 P3五步及P4/P5交接

#### 当前代码依据

1. 当前SeriesEntry保存points/events/structure_records，calculator_at通过有界检查点还原一次真实前缀；本次新计数/跟踪极值、单根起点重置和asOf投影尚未实施，按§4及§18同步。不能继续声称§17.4旧成绩已经验收这些修正。
2. 当前识别v0.3-r4、预测v0.5-r4，首两步修改前实现已存在；本次目标v0.4/v0.6，先修首两步再继续下表第3步。公开API仍待一次校验/编码迁移，TS仍消费旧合同；已完成的内部基线不等于整批可发布。
3. 内部真实来源、共享读取、原MACD/1%/EMA和预算保持；前三项修补的源码/测试文件见§18.3，图上显隐留第3—4步实施。

#### P3实施步骤、前置与停点

| 顺序 | 开始前必须具备 | 本步必须完成 | 本步验收与下一步交付 |
|---|---|---|---|
| 1 新识别核心及内部结果 | §3代码顺序、§4恢复格式、§5内部记录和§14用例已经review；目标文件引用清单已核 | 原位置替换首次C/D、逐参照曾击穿、同根B→A、顶底1%回转、首次反色起比价、单根跳过及首个有效段结束；同步`types/snapshot_validation/spec`、统一`XxmStructureRecord`、`XxmStep.structures`、`SeriesEntry/_load_series/calculator_at`及完整内部模型；清理底部WAIT及旧无限跨段撤销，落实§3.7有限价格途径。完整Spec确定后生成`xxm-direction-v0.4-r4`的新detector hash | 全部识别case逐根通过；连续/增量/历史前缀/复制/恢复相同；已有正确安全检查不退化。此时仅证明内部识别，不能把旧预测或公开DTO不兼容当作新规则错误，更不能称页面可用 |
| 2 下一根预测内核 | 第1步新识别状态、结构首次反色记录、参照资格和clone已经稳定；§6数学及失败语义固定 | 撤销20根与全浮点细分、横盘前缀/中点代表；按§6先前提后边界，先B有解即停止，确无解再A。已有DULL和尚未首次反色STRUCTURE各自求下一根结果；首次反色后同时处理新循环和仍有效的旧结构有限跟踪。严格按§6.1/6.7的函数、内部类型和逐文件去向实施，包括forecast_next.py、单根核验/表达式及纯文字；移除正式旧多步/全float路径，不保留备用入口 | 独立数学/业务边界、零柱、来源精度、整数及取消/超时测试通过，记录数学部分耗时；完整400ms含校准/模型/query/编码须在第3/5步接齐后验收，P4另验真实来源。不能用数学样本提前声称完整预算通过 |
| 3 Python模型、投影、query/API和身份 | 前两步修正、独立回归及§17专项对比review已通过；内部事实、下一根结果字段及双Spec内容已固定 | 完整内部/普通/debug模型和`response_projection.py`；query共享一次读取结果，迁缓存/forecastId/display/日历下一端点；三个识别/预测API接受既定debug参数并发送一次编码bytes；移除等待字段与旧多根表达式字段；同步直接Python DTO消费者及新合同人工fixture | 普通/debug公共字段、标签ID、预测文本相等；旧/混配身份拒绝，窗口外关联带齐、asOf不泄漏未来首次反色；4秒/400ms/1MiB/32KiB预算包括校验编码；未完成这一项之前，不用旧web通过结论证明新HTTP |
| 4 前端必要合同调用 | 第3步实际双hash和完整正常/debug合同已产生 | 纯TS类型→两个纯debug decoder→普通decoder/adapter→两个apiClient返回`{response,deadline}`→两个Hook读取和最终显示检查→普通悬停与日/分钟工作区调用；同次改受影响fixture。普通路径不静态加载辅助实现 | 类型检查、定向合同/API client/Hook/UI回归、Wealth测试和build；普通无debug字段也可展示。debug模块ready联动、正式本地/生产资格、辅助renderer及研究工具仍留P4，不用固定true或假decoder代替未接入功能 |
| 5 P3整批独立验收并停止 | 前四步全部完成，所有直接消费者同一合同 | 按新§14逐项对账、预测下一根用例、API模型/一次编码/共享读取/输入恢复/前端必要调用/架构及文档检查；记录真实实现hash、数量、耗时和未覆盖内容 | M1—M5/PF01—34及识别独立用例全部对账。未执行P4真实来源/浏览器和保留工具、P5清退的部分逐项列明，不宣称整体产品完成。停止等独立验收，不自动进P4 |

第1—4项“按顺序实施”不允许阶段结束仍保留另一个可运行旧r4策略。开发中间状态不作为可发布产品，不给普通请求添加过渡开关。第3项需要的公开模型草稿必须在第1步修改内部字段之前已经写入本文，不能等编码时自由选字段。若执行中发现新业务边界或§6数学预算无法成立，先停止并说明，不依赖旧模型吞错或原20根路径兜底。

#### P4六步（P3整批通过后）

| 步骤 | 动作与前置 | 结束证据 |
|---|---|---|
| 1 本地/生产装配 | 用既有显式dev/local策略装配三条r4与daily-wave路由，分钟另受原reader可用性；前端资格同步，不把日线绑到分钟Lake | 缺环境/生产/未知值相关API不进入source和算法，显式本地无分钟Lake仍可日线；生产debug不能绕过 |
| 2 页面请求模式 | 在P3纯类型/decoder/client之上接`enabled/effectiveDebug`、动态模块ready和失败；普通路径不import研究执行代码；debug模块失败仍普通请求 | 模块加载中/失败/重试/关闭/切周期/离开和迟到结果反例；普通/debug缓存和序号隔离且同源公共结果相同 |
| 3 辅助详情与核对图 | 按§8接首次反色/考核依据、参照和编号；波段核对仍手动开启、独立日期/九转/趋势、四种三角及44px留白 | 默认无研究请求和图层；原数据与右栏日期不被研究时间覆盖；不把故障一起藏进debug |
| 4 保留工具成套迁移 | 首次运行前按§10—11清单迁`daily_window_precheck`、页面请求与预测显示工具，正常/debug、bytes、原deadline、明确周期/asOf/samples、纯内存、finally释放全部一次完成 | 缺旧运行器仍可用；无candidate/源码SHA/结果落盘；失败、取消、Node异常清理；不只改版本后运行旧报告入口 |
| 5 真实来源与预算 | 先获所需只读范围授权，使用既有隔离App/原路由鉴权；日线及实际可用60/90/120分别验源字段/时间/连续性/根数、普通/debug字节和冷/热耗时。仅在已声明20次性能验收时使用samples=20 | 4秒/400ms/研究8秒整链10秒、原字节上限；正常日线1000和20次K线P95预算；不足/缺周期如实未验收。不得复用旧日线922根替代分钟 |
| 6 页面与独立验收 | 用户完成浏览器review；自动验收保留当前1600/1440/1280、45/180根、拖过301根等既定场景及生产构建反例 | 本地普通/debug、生产无功能、正常行情/右栏/同步和研究图均通过。必要分钟证据未齐不能进入P5，除非管理员另行改变范围 |

#### P5四步（P4通过后）

1. 按原逐文件/函数清单重新查引用，确认有用人工样本、两位独立取数及基础波段工具已迁出；r2及旧研究/报告可执行算法无有效消费者。
2. 删除清单内旧执行器、比较器、研究r4副本和专属测试/生成缓存；保留原图、报告、设计和Git历史。不改清单外dirty文件，不恢复旧实现兼容层。
3. 在旧模块确实不存在时回归正式唯一r4、预测、普通/debug、保留工具及必要架构；清退前通过不能替代删后回归。
4. 更新原索引/命令/历史定位，逐要求记录代码/测试/真实证据/未覆盖；停止交付。提交、部署和生产开放均按后续明确指令，不自动执行。

#### 原合同文书同步入口

下列目标入口已经与本LLD同步；实施时必须同时迁移模型和全部消费者，文书同步不等于运行合同已经改变：

- `index-detail-api-contract-v1.md`日线r4识别合同（原§10）：字段、事件/结构引用、窗口与正常/debug对象、版本/新hash、错误及一次编码。
- `index-detail-minutes-api-contract-v1.md`原§8分钟识别r4目标合同：同上四周期同语义，分钟精确时间与来源限制保留。
- `index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md`原§36预测合同：只下一根、新状态/条件、删除等待和多根假设、400ms、整数显示、普通/debug对象及双hash。
- `wealth/docs/system/exception-code-registry.md`仅在新设计确需改变现有错误码时同步；不得私自添加错误码。精度不确定沿现PRECISION_PENDING含义，不能伪装确定无解。

每个入口只能有一个当前目标字段集合。运行合同尚未迁完时不得声称目标API已可用；不得恢复已删除的目标段或增加旧格式兼容。


## 12. 测试、真实验收和完成标准

### 12.1 独立预期与实施测试文件

| 层次及落点 | 必须执行的设计 | 负向及正常变化反例 |
|---|---|---|
| `scripts/research/index_market/tests/test_xxm_calculator.py`、现有`test_xxm_r4_rules.py`及`test_xxm_r4_following.py` | §14的RC01—69及RC74—110业务/记录序列，依§18.3分配现有文件；按case参数化四周期。保留仍正确测试，三项修正规则按独立字面输入与expected改写；不复制计算器生成预期 | 当根C/D、逐参照曾破、A破B有效、零柱、严格等号、B/A/第三个、1%/前0/不累计、首次反色当根比价、单根不终止及首个有效段结束、多轮结构 |
| `test_xxm_snapshot_validation.py/test_xxm_snapshot_consumers.py` | RC70—72、RC89—92、RC95、RC98—103/105/109及§4所有字段/引用，包括§14.16全部恢复/asOf子样本；from-empty、append、calculator_at、clone都经过真实恢复 | 旧身份/WAIT/NaN/bool/未来日期/终态冒充active拒绝且来件/self不变；合法早前缀、等号/当前价格回升仍能继续 |
| `test_xxm_r4_observation.py` | §7真实执行观察及默认关闭；True/False完整业务结果一致 | 未查A不当失败、原事件参照不改、before/after不混、翻色旧事件方向正确、重复选择和对象共享 |
| `test_xxm_p3_forecast_math.py`及`test_xxm_key_point_forecast.py` | §5.4.4 M1—M5和§6.10 PF01—34；独立Fraction/手算，不由forecast helper生成expected | 合法零/整数边界、近有解A零调用、无解与未决区分、已成结构继续考核、首次反色后有限跟踪与新轮并行、失败无半结果及400ms |
| `tests/web/test_wealth_index_detail_xxm_api.py`、`test_wealth_index_detail_xxm_forecast_api.py`、`test_xxm_shared_loads.py` | RC73/93/104/107及§14.16全部窄窗口子样本、新普通/debug字面合同、同时间多事件、一次编码/同次来源只读一次、真实query调用/缓存/取消及身份 | 拒旧JSON而非改hash；历史point引用终态record合法；旧asOf不泄未来；不重复读、不二次编码、不吞错EMPTY |
| Wealth现识别/预测`types/adapter/apiClient/Hook`测试、工作区/页面测试 | §8合同/迟到/截止时间、普通无debug可展示、同源公共值相同；P3先验必要调用，P4再验动态模式/生产资格 | 不静态加载辅助、不以false诊断隐藏真错、关闭清理、研究日期不影响右栏/预测、生产任何debug不请求r4 |
| 依赖边界/清退/工具 | 根三份架构、Biz不导入research/App/QTF、§10逐文件清退及§11保留工具 | 无旧算法/父类/动态副本/源码SHA保护；保留工具在旧模块缺席时正常人工输入可运行 |

全部字段/分支到case对账见§14.12。人工来源样本只证明对应规则，真实来源核验按下一节；不拿设计数量、mock或旧成绩冒充已执行。M1/M2的175.5/24.5合法零必须纳入回归；不得仅改max_future_bars、扩大时限或删复杂路径来冒充数学正确。

### 12.2 有界真实核验（实施阶段，当前未执行）

- 使用已有隔离本地App办法、原路由和原鉴权、只读来源；不重启共享服务，不通过mock声称真实接入通过。
- 先选择单上证有限日期/已有可用分钟的各周期，记录真实源字段/时区、读取范围、实际根数、响应字节、冷/热/历史/增量耗时及source ID，不补缺值或计算实际MACD。若正式服务需要更长历史，事先注明有界上限和来源，不把报告区间当计算起点。
- 新规则用§14、M1—M5及PF01—34独立预期；不再捕获旧v2或重建双组产品。真实来源另按唯一新r4及有界源字段/日期核验，不把人工测试冒充真实来源证据。
- 本地普通/debug对同固定前缀公共结果一致；分钟不可用时单列未验收，不能拿日线922根或人工替身抵充。
- 真实生产构建仅在本机preview验证，无r4 DOM/请求/辅助chunk预载；后端以生产设置构建隔离路由验无源调用。本项不部署到生产。
- 浏览器1600/1440/1280宽、45/180根、拖至301根以后，记录普通/debug的请求、控制台及图层/图表创建次数；退出研究恢复普通日期，标签/条件与真实API一致。页面最终交用户review。
- 每个测试组超过60秒停止查因；性能不满足400ms/4秒/8秒/10秒或字节限额时报告实际输入、路径数和耗时，先补方案，不放宽上限或退r2。

### 12.3 命令和交付对账

使用现有环境，不安装。实施时先确认测试路径存在，再分组执行：

- `.venv/bin/python -m pytest`选本模块人工/恢复/预测/投影及web路径；不得整组触发旧冻结数据回放或未授权真实读取。
- 根三份架构：`tests/architecture/test_subsystem_dependency_matrix.py`、`test_platform_legacy_guardrails.py`、`test_operations_legacy_guardrails.py`，另核Biz不导入research/App/QTF。
- Wealth定向/全量`npm --prefix wealth run test`、`typecheck`、`build`；真实preview单独登记。每组有界，不用skip/吞错过关。
- `python3 scripts/check_docs_integrity.py`和本组相对链接/标题/字段覆盖检查；它们只能证明文档完整性，不能证明新算法或接口已经通过。

每批交付按R01—R22、RC01—110及实际执行的PF01—34逐条记录“代码点/测试/真实证据/未覆盖”，不是只报测试数量。最终完成还须P5删后验证、全部消费者同合同、用户页面review；未完成来源或性能不得宣称整体产品已验收。

## 13. 内嵌编码门禁

以下逐项映射[模块交付通用清单](../../system/module-delivery-checklist-v1.md)的18条。适用范围为已接真实API的指数详情，不恢复市场总览mock/real切换，也不借此修改策略配置中心或其他页面。

| 通用清单 | 本模块适用性及明确要求 | 代码/验收 |
|---|---|---|
| 2.1 交付事实链 | 适用；产品/技术v1→本文→原API合同→实现→测试/页面review；现页面/用户四种画法为视觉事实 | §0、5、8、11—12；不重做Figma、不用历史图覆盖当前界面 |
| 2.2 后端事实归一 | 适用；源原MACD、唯一r4、内部完整后投影 | §2—7；前端不自行选峰/算结构 |
| 2.3 状态机 | 适用；NONE/DULL/STRUCTURE、结构ASSESSING/FOLLOWING/FINISHED/DISAPPEARED及研究区间closed分别表达；新流程没有WAITING | §2—5、8、14.15；旧等待仅作清退和拒绝旧输入反例，另验加载/EMPTY/DELAYED/错误 |
| 2.4 显示与数据语义 | 适用；正常正式信息、debug原依据、生产无功能 | §5、8；普通故障可见、原值不格式化比较 |
| 2.5 过程测试 | 适用；重试/取消/迟到/切周期/卸载/进度恢复 | §4、8、12；不能只快照DOM |
| 2.6 文档同轮 | 适用；方案/LLD/合同/索引和实际状态同步 | P3/P4/P5逐步交付对账 |
| 2.7 渐进替换 | 适用；§11重新安排P3五步→P4六步→P5四步；不发布混合识别/预测版本 | §11；最终无双轨/兼容r2 |
| 2.8 契约消费者 | 适用；query字节、公开模型、API、TS、decoder、fixture全迁 | §4—5、8、10；旧JSON仅反例 |
| 2.9 图坐标/文案 | 适用；事件原日期，三角仅原认可画法/避让 | §8；范围外/空间不足不捏造点 |
| 2.10 统计/传输 | 适用；后端完整算，普通不传debug；响应上限 | §4—5、9；不裁断关联凑限额 |
| 2.11 策略中心 | 不适用新增策略配置；本功能不消费/修改策略中心 | 既有env/Spec审计§1—2，无数据库配置或用户算法开关 |
| 2.12 映射矩阵 | 适用，本表覆盖18项，每项注明实施/测试 | 新P3开工前复核，交付逐项对账 |
| 2.13 例外白名单 | 无新增例外；生产暂不开放是产品范围，不用mock或r2兜底 | 本节白名单表；开发真实/生产无请求反例 |
| 2.14 参数优先级 | 适用；图配置不改真实日期/标签/方向；研究44px只影响画法 | §8；共享默认、1000及缩放回归 |
| 2.15 双图对齐/避让 | 本轮无新增并排图；现四窗坐标/九转及三角避让适用 | §8既有尺寸和占位；301根后/宽度/高度回归 |
| 2.16 卡片文案 | 适用；正常预测沿现display和单行/长度约束；复杂公式仅debug | §5—6、8；中文有限容器/溢出不改语义，无新卡片 |
| 2.17 真实API+显示 | 适用；独立合同样例+真实最小来源链+真实build/页面 | §12.2；当前文档检查不替代 |
| 2.18 八原则 | 适用，见下一表 | 全链审计，不能只填“通过” |

| 八原则 | 明确落点/反例 |
|---|---|
| 事实源单一 | 源原值、唯一r4、debug取实际输出，离线过程只记真实分支，禁止产品import研究及新MACD补算 |
| 契约先行冻结 | §5新字段/None/类型/错误/单次编码；§11.3核对已同步合同后再编码全部消费者 |
| 配置一致 | §1最终Settings与显式来源、前端DEV、固定Spec、1000和原预算唯一来源 |
| 默认行为显式 | 普通正式/无辅助、debug手动研究、生产全部r4禁用、不回r2 |
| 排序筛选确定 | 仅B/A时间序、严格比较/相等、固定窗口和历史投影，禁止最强排序 |
| 预算前置 | §9含缓存命中/恢复/精度分支/序列化/失败重做/最终验收 |
| 异常标准化 | 原注册错误/状态、真实错普通可见、取消释放、不把错误当空 |
| 用户结果中心 | 标签/文本/依据同源、三角/1000/原图、真实浏览器和用户review |

例外白名单：**无新增条目**。本模块没有为绕过通用门禁引入mock、公开配置、独立聚合接口、特殊展示算法或持久化。通用清单仅限homepage的mock切换不适用于这个已经真实接入的指数页，属于适用范围说明，不是假设获准的例外。

编码前确认项：本LLD/原方案一致、§11.3新目标API合同回写/独立样例及实施当日引用清单完成、明确该批执行授权；其后按每批验收。LLD写完不等于已经授权删除或整体开发。

## 14. r4识别规则测试case设计及实施覆盖

本节是本次目标识别及配套用例目录。RC01—96修改前成绩仅证明当时版本，历史证据见§15—17；本次调整相关预期并新增RC97—110，全部须按新规则重新验收，不能声称调整后的预期已经执行通过。公开HTTP/前端分属P3后续步骤，真实来源及页面仍依P4。本轮不运行行情、对比或测试代码；PF21—28已修订，PF29—34新增，同样待重新实施验收。

### 14.1 人工输入、结果和覆盖方式

每条输入写为`(C,D,H)`：C为当根收盘，D为当根原始DIF，H为源MACD柱值；正红、负绿、0中性。DEA固定写入独立人工夹具，按`DEA=D−H/2`使柱恒等式自洽，不能由待测识别器生成。以下输入专门验证判别条件，不宣称能由同一段真实收盘的EMA递推得到；真实来源/EMA一致性仍由原接入验收负责。

`t1、t2……`是当前用例的顺序完成K线。实现测试时使用固定字面交易日期`2023-01-03、04、05、06、09、10、11、12、13、16、17、18`依次对应；更长序列日期见§14.17；日线时间为日期，60/90/120分钟人工算术样本分别使用这些日期的`15:00:00+08:00`。这些分钟样本只验证相同业务内核，不冒充覆盖每个盘中端点的完整性验收。

每个业务case均在day/m60/m90/m120四个周期核对同一识别语义。测试预期采用本节独立字面值及手算不等式，禁止先运行计算器、旧r2或新r4再把输出当expected。本文“事件”描述业务事实，不提前发明公开API枚举；编码时必须映射到同次已确认的事件/事实格式。

每根都断言：本根业务事件、普通状态和方向、活动参照、当前色段及有色根数；出现结构时还断言结构发生根、首次反色根或失效根及关联。无事件不等于未检查；首次反色不等于新色段仍保留旧普通STRUCTURE。明确禁止重复首次钝化、先取消后删事件、伪造首次反色、当前普通关系取消后同根又首次钝化、旧结构在首个有效同色段已经结束后被错误撤销。旧结构价格CANCEL与另一份当前关系的新DULL/STRUCTURE同根属于合法正例，必须全部保留。

相等有两种不同含义，不能合成一个检查：首次价格/DIF仍严格比较；`D==参照DIF`不满足当根首次背离，但也不是“曾严格击穿”。因此后续恢复严格背离仍可首次钝化。只有真正严格突破才使该参照在当前逻辑色段永久失效；已经钝化时等于参照不因突破规则消失。

### 14.2 公共人工前缀（均从空状态逐根输入）

前缀是为减少表格重复，不能把一个带待测函数输出的snapshot当作初始夹具。

| 前缀 | 完整字面输入顺序 | 独立预期 |
|---|---|---|
| `T` | `(100,200,2);(90,0,-2);(101,100,2);(102,100,2)` | t1旧红段B仅1根，允许成为历史；t2真实反色。t3当前红段1根无钝化；t4当前红段2根、C102>100、D100<200，首次顶部钝化B。 |
| `B` | `(100,-200,-2);(110,0,2);(99,-100,-2);(98,-100,-2)` | t3当前绿段1根无钝化；t4首次底部钝化，旧谷B价100/D−200。 |
| `TS` | `T;(103,99,2)` | t5相邻DIF100→99，差1恰为1%，顶部结构形成，尚未首次反色。 |
| `BS` | `B;(97,-99,-2)` | t5相邻DIF−100→−99，回升1恰为1%，底部结构形成，尚未首次反色。 |
| `ABT` | `(100,300,2);(90,0,-2);(120,200,2);(110,0,-2)` | 已结束旧红段远A价100/D300、近B价120/D200；当前是分隔绿段。 |
| `ABB` | `(100,-300,-2);(110,0,2);(80,-200,-2);(90,0,2)` | 已结束旧绿段远A价100/D−300、近B价80/D−200；当前是分隔红段。 |
| `ABTD` | `ABT;(130,100,2);(131,100,2)` | t6首次顶部钝化选近B，不能因远A的DIF更高而选A。 |
| `ABBD` | `ABB;(70,-100,-2);(69,-100,-2)` | t6首次底部钝化选近B。 |

本节顶底双方都列出具体数值，不用“底部镜像待补”代替预期。若测试实现额外使用镜像生成输入，仅可对所有C均在(0,200)内、且没有非对称资格冲突的指定样本使用`C'=200−C、D'=−D、H'=−H`；RC-10等越界样本禁止自动镜像，按表中独立顶底字面值输入。expected仍以表中已手写方向、参照及事实为准，不由被测函数生成。该变换不用于改变“首次顶部当根DIF>0、底部不要求DIF<0”的非对称既定条件。

### 14.3 色段、零柱和历史极值（01—10）

| case | 前缀/完整追加输入 | 逐根结果及必须排除的错误 |
|---|---|---|
| RC-01 开头零柱 | 从空：`(100,0,0);(101,1,0);(102,2,2)` | t1/t2为NONE且无色段、无历史；t3新红段count=1，不把前两根补成红柱，不钝化。 |
| RC-02 红零红 | 从空：`(100,10,2);(105,11,0);(104,10,2)` | 同一红段t1—t3，count=2；价格极值105在t2，DIF极值11在t2；没有历史红段，不能首次钝化。零根不能变成第三根有色柱。 |
| RC-03 红零绿 | `T;(103,100,0);(90,99,-2)` | t5仍顶部钝化、红段count=2；t6真实翻绿才结束旧红段，旧段end=t5、不含t6；同根确认顶部结构并首次反色，新绿段count=1。 |
| RC-04 绿零红 | `B;(97,-100,0);(110,-99,2)` | t5仍底部钝化、绿段count=2；t6确认底部结构并首次反色；旧绿段end=t5，新红段count=1。不能将零视为提前反色。 |
| RC-05 已够根数后零日首次 | 顶：`(100,200,2);(90,0,-2);(99,100,2);(99,100,2);(101,100,0)`；底：`(100,-200,-2);(110,0,2);(101,-100,-2);(101,-100,-2);(99,-100,0)` | 双方t4已有两根有色柱但当根价格不合格；t5零日价格合格，当天仅首次钝化B，count仍2，不追加结构、不首次反色。 |
| RC-06 一根有色后连续零 | 顶：`(100,200,2);(90,0,-2);(101,100,2);(102,100,0);(103,100,0)`；底：`(100,-200,-2);(110,0,2);(99,-100,-2);(98,-100,0);(97,-100,0)` | t3—t5有色count始终1，均不首次钝化。下一根若为同色实柱且其他条件仍合格，才在该根首次钝化。 |
| RC-07 历史红段极值分日 | 从空：`(100,200,2);(105,190,2);(104,210,2);(90,0,-2);(106,100,2);(107,101,2)` | t6顶部钝化参照价105@t2、DIF210@t3；历史极值日期不能强绑。当前首次资格使用t6的107/101。 |
| RC-08 历史绿段极值分日 | 从空：`(100,-200,-2);(95,-190,-2);(96,-210,-2);(110,0,2);(94,-100,-2);(93,-101,-2)` | t6底部钝化参照价95@t2、DIF−210@t3；不能把DIF日期t3的价格96替换最低收盘95。 |
| RC-09 并列极值保留发生位置 | 顶：`(100,200,2);(100,200,2);(90,0,-2)`；底：`(100,-200,-2);(100,-200,-2);(110,0,2)` | 旧段有色count=2、end=t2；并列价格/DIF按既有Wave口径保留首次发生t1，不因后续相等改写成t2。没有局部小峰过滤。 |
| RC-10 反色首根不能污染旧段 | 顶：`(100,200,2);(500,500,-2)`；底：`(100,-200,-2);(50,-500,2)` | 旧红/绿段仍仅t1，价100、DIF±200；t2所有值属于新段，旧段不取500/−500，颜色只看H，不能按DIF正负分段。 |

### 14.4 首次钝化及本轮参照失效（11—25）

| case | 前缀/完整追加输入 | 逐根结果及必须排除的错误 |
|---|---|---|
| RC-11 第二根红柱当天首次 | `T` | t3不钝化，t4首次顶部钝化B；不能多等第三根。 |
| RC-12 第二根绿柱当天首次 | `B` | t3不钝化，t4首次底部钝化B；不能将“等两根”误作钝化以后再等两根。 |
| RC-13 不借此前高价 | 从空：`(100,200,2);(90,0,-2);(101,100,2);(99,100,2)` | t3仅1根；t4虽已有两根，C99不高于100，不钝化；不得借t3的101。 |
| RC-14 不借此前低价 | 从空：`(100,-200,-2);(110,0,2);(99,-100,-2);(101,-100,-2)` | t4的C101不低于100，不钝化；不得借t3的99。 |
| RC-15 当前DIF必须严格背离 | 顶：`(100,200,2);(90,0,-2);(101,100,2);(102,200,2)`；底：`(100,-200,-2);(110,0,2);(99,-100,-2);(98,-200,-2)` | t4价格合格、根数够，但DIF等于旧峰/谷，不首次钝化；以前的较弱DIF不能代替当根。 |
| RC-16 曾击穿旧谷不可恢复 | 从空：`(100,-200,-2);(110,0,2);(99,-201,-2);(98,-100,-2);(97,-99,-2)` | t3严格击穿B，虽然当时还只有1根绿柱，本轮B已失效；t4/t5均不能因DIF回升而首次使用B。不报先有钝化再消失的伪事件。 |
| RC-17 曾突破旧峰不可恢复 | 从空：`(100,200,2);(90,0,-2);(101,201,2);(102,100,2);(103,99,2)` | 与RC-16对应，t3使B本轮失效，t4/t5不能回用B。不得只有已钝化以后才记录突破。 |
| RC-18 首次价格等号不合格 | 顶：`(100,200,2);(90,0,-2);(100,100,2);(100,100,2)`；底：`(100,-200,-2);(110,0,2);(100,-100,-2);(100,-100,-2)` | t4均NONE；价格必须严格创新高/低。下一根顶C100.01/D100/H2或底C99.99/D−100/H−2才首次钝化。 |
| RC-19 首次DIF等号不合格 | 顶：`(100,200,2);(90,0,-2);(101,200,2);(102,200,2)`；底：`(100,-200,-2);(110,0,2);(99,-200,-2);(98,-200,-2)` | t3/t4均不首次；但B不得标为已严格击穿。 |
| RC-20 曾相等但未击穿可后续首次 | RC-19顶追加`(103,199.999,2)`，底追加`(97,-199.999,-2)` | t5首次钝化B；DIF仅较旧极值弱0.001也已严格背离，不需1%峰间差、不取两位。区别“过去曾相等”和“过去曾严格突破”：不能沿用累计极值必须始终严格背离的旧拒绝条件。 |
| RC-21 首次顶部看当根正DIF | 从空：`(100,200,2);(90,0,-2);(101,1,2);(102,0,2);(103,-1,2);(104,0.001,2)` | t3只有1根；t4当根D0不首次，t5负值不首次；t6当根转正且其他资格满足才首次。过去D曾为正不能替代当根，H为正不能证明D为正。 |
| RC-22 底部不新增负DIF要求 | 从空：`(100,-200,-2);(110,0,2);(99,5,-2);(98,6,-2)` | t4首次底部钝化B，当前DIF正值仍高于旧谷−200；不能擅自加入D<0过滤。 |
| RC-23 没有历史同色参照 | 从空顶：`(100,100,2);(101,101,2)`；底：`(100,-100,-2);(99,-101,-2)` | 当前虽两根且方向明确，但没有已结束同色段，不能首次钝化或虚构A/B。 |
| RC-24 历史单根允许；B当根相等仍可查A | 顶`ABT;(131,200,2);(132,200,2)`；底`ABB;(69,-200,-2);(68,-200,-2)` | 历史A/B都只有一根，仍可作为候选。t6的B当根DIF等于B，不满足首次严格背离但也没有击穿B；A自身及B价格门槛都通过、DIF严格背离A，因此首次钝化选A。不能把预测的“B还有未来价格解就不算A”套到这根真实K线。 |
| RC-25 首次当天不追加结构 | 顶：`(100,200,2);(90,0,-2);(101,100,2);(102,99,2)`；底：`(100,-200,-2);(110,0,2);(99,-100,-2);(98,-99,-2)` | t4虽相邻DIF已有恰1%反向转折，但进入本根前尚未钝化，t4仅首次钝化，不在同根追加结构。下一根才按已有钝化处理。 |

### 14.5 近B、远A及当根切换（26—37）

以下是实际完成K线的识别选择，不是预测中“近处有价格解便停止”的求解调度。识别仍保留已确认的最近B价格门槛；A必须同时通过B及自身价格门槛。

| case | 前缀/完整追加输入 | 逐根结果及必须排除的错误 |
|---|---|---|
| RC-26 近处优先，远处失效不连带近处 | 原组`ABTD`和`ABBD`。新增顶从空`(100,150,2);(90,0,-2);(120,200,2);(110,0,-2);(130,180,2);(131,180,2)`；底从空`(100,-150,-2);(110,0,2);(80,-200,-2);(90,0,2);(70,-180,-2);(69,-180,-2)` | 原组t6分别顶部/底部钝化选B，A更强不构成改选理由。新增组t5已严格突破A的DIF±150，但B的DIF±200没有被突破；t6当前价格和DIF完整合格，仍首次钝化B。每个参照分别检查，不能把“A失效”扩大为B/A全部失效，也不能假定历史DIF必然按时间变弱。 |
| RC-27 近处已破而远处合格 | 顶`ABT;(131,250,2);(132,250,2)`；底`ABB;(69,-250,-2);(68,-250,-2)` | 当前第一根就使B本轮失效，但A未破；t6首次钝化选A。顶132>120且>100，D250<300；底68<80且<100，D−250>−300。 |
| RC-28 B价格门槛不能绕过 | 顶`ABT;(119,100,2);(119,100,2)`；底`ABB;(81,-100,-2);(81,-100,-2)` | A自身价格/DIF会合格，但B价格未突破，t6均NONE，不越过B门槛直接选A。 |
| RC-29 A自身价格也必须通过 | 顶从空`(130,300,2);(90,0,-2);(120,200,2);(110,0,-2);(125,250,2);(129,250,2)`；底`(70,-300,-2);(110,0,2);(80,-200,-2);(90,0,2);(75,-250,-2);(71,-250,-2)` | B本轮已破，当前价已过B但未过A，t6均无钝化。只通过B价格不等于A合格。 |
| RC-30 最多两个历史段 | 顶从空`(90,400,2);(80,0,-2);(100,300,2);(90,0,-2);(120,200,2);(110,0,-2);(130,350,2);(131,350,2)`；底`(110,-400,-2);(120,0,2);(100,-300,-2);(110,0,2);(80,-200,-2);(90,0,2);(70,-350,-2);(69,-350,-2)` | t8最近B/A都已破，第三个更早段虽有能力支持背离也不搜索，不首次钝化。池截取依实际结束顺序，不按DIF强弱。 |
| RC-31 已有顶部钝化当根换A | `ABTD;(132,201,2)` | t7突破B200，A300仍合格且当根价132通过两门槛；活动参照当根改A、保持顶部钝化，不增一组消失/首次钝化；原t6首次事件参照仍B。 |
| RC-32 已有底部钝化当根换A | `ABBD;(68,-201,-2)` | t7跌破B−200，A−300仍合格；当根换A保持底钝化，不等下一根，不改原事件参照。 |
| RC-33 换远不得借旧价格 | 顶`ABTD;(119,201,2)`；底`ABBD;(81,-201,-2)` | 近参照当根已破，但当根价未过B门槛，虽此前131/69过价，不能支持新A；t7取消钝化，不切A，不用累计价格偷过门槛。 |
| RC-34 两个参照都破则取消 | 顶`ABTD;(132,301,2)`；底`ABBD;(68,-301,-2)` | t7直接取消，B和A本轮均失效，不回切/不查第三个。当前仍有两根以上不改变结论。 |
| RC-35 A晚一根才合格 | 顶用RC-29前4根，加`(125,100,2);(126,100,2);(129,201,2);(131,201,2)`；底用RC-29底前4根，加`(75,-100,-2);(74,-100,-2);(71,-201,-2);(69,-201,-2)` | t6先钝化B；t7近破但A价格不够，保留取消；t8A当根价格够才新钝化A。不能抹去t7取消，也不能t7先清空后同根重入。 |
| RC-36 已选A不回B | 顶RC-27前缀后追加`(133,190,2)`；底RC-27底前缀后追加`(67,-190,-2)` | t7B虽从当根值看较弱，但它此前已破，本轮不可复活；沿A按大幅DIF反向转折形成结构A，不改B、不重报首次钝化。 另测B未曾击穿的固定参照：RC-24顶序列后追加`(133,199,2)`，底后追加`(67,-199,-2)`；t7相邻变化1小于前值200的1%门槛2，仍为DULL/A。B虽本根恢复严格合格，也不回切B、不产生新首次事件。 |
| RC-37 已有结构不换远维持 | 顶`ABTD;(132,99,2);(133,201,2)`；底`ABBD;(68,-99,-2);(67,-201,-2)` | t7结构B；t8原B被突破，直接取消结构。A虽然仍可支持背离，已有结构不走DULL救援，不先回钝化、不在该根报新DULL。再追加顶`(134,201,2)`、底`(66,-201,-2)`：下一根A完整合格则首次DULL/A；禁止的是取消当根重入，不能永久阻止后续合法A。 |

### 14.6 已有钝化、结构考核与回转（38—52）

| case | 前缀/完整追加输入 | 逐根结果及必须排除的错误 |
|---|---|---|
| RC-38 已有钝化不重查价格 | 顶`T;(99,100,2)`；底`B;(101,-100,-2)` | t5仍保持原参照钝化，虽然当根价已回到首次门槛另一侧；不取消、不重新首次、不进入等待。 |
| RC-39 顶部恰1%形成 | `TS` | t5的100→99差1、基数100，恰1%，形成顶部结构；不能误写成必须严格大于1%。 |
| RC-40 底部恰1%形成 | `BS` | t5的−100→−99回升1、基数绝对值100，形成底部结构。负数门槛不能用带负号基数。 |
| RC-41 不足1%仍钝化且不累计 | 顶`T;(103,99.5,2);(104,99.1,2)`；底`B;(97,-99.5,-2);(96,-99.1,-2)` | t5变化0.5%，t6变化0.4、门槛0.995，两根都保持钝化、不形成结构。每根与上一根比较，不能将多根变化累计。 |
| RC-42 结构形成不重查价格 | 顶`T;(99,99,2)`；底`B;(101,-99,-2)` | t5原钝化仍有效，DIF达到反向1%，均形成结构；当天C99/101不满足首次价格门槛，不阻碍形成结构。 |
| RC-43 前DIF为0不触发1% | 形成反例：从空`(100,-200,-2);(110,0,2);(99,-1,-2);(98,0,-2);(97,1,-2)`。回转反例：顶`T;(103,0,2);(104,1,2)`；底`B;(97,0,-2);(96,-1,-2)` | 形成反例t4首次底钝化，t5前值0不触发1%结构，仍钝化。回转反例t5先形成结构、其DIF为0；t6以前值0为基数，不触发1%回转，仍结构。不能把门槛0当任意差都成立；颜色由H判断，不由DIF正负决定。 正常变化对照：取本行“形成反例”前4根，再追加`(110,0,2)`；t5虽前DIF=0，但真实翻红独立确认底部结构并当根首次反色，不能把前值0保护误用到真实反色。 |
| RC-44 相邻根含零柱，不跳根 | 从空`(100,-200,-2);(110,0,2);(99,-100,-2);(98,-100,-2);(98,-100.5,0);(97,-99.4,-2)` | t5零根仍钝化；t6必须比较−100.5→−99.4，回升1.1≥1.005，形成结构。若错误跳过零根取−100→−99.4仅0.6，会漏报。 |
| RC-45 活动参照等号与突破 | 顶`T;(103,200,2);(104,200.01,2)`；底`B;(97,-200,-2);(96,-200.01,-2)` | t5等于原参照仍保留钝化，不换A不取消；t6严格突破才取消。本轮不可再回用该参照。 再加双参照保持对照：顶`ABTD;(132,200,2)`、底`ABBD;(68,-200,-2)`，t7仍DULL/B，无新事件、不切A；与RC-24首次B等号选A不同，不能在已有钝化时重走首次选参照。 |
| RC-46 顶部结构回转恰1% | 从空`(100,200,2);(90,0,-2);(101,102,2);(102,102,2);(103,100,2);(99,101,2)` | t4首次顶钝化；t5结构；t6D100→101恰1%，退回顶部钝化，保持原参照；当天价格99不阻碍。原结构不再作为有效尚未首次反色结构，不产生等待。 |
| RC-47 底部回转不再等待价低 | 从空`(100,-200,-2);(110,0,2);(99,-102,-2);(98,-102,-2);(97,-100,-2);(101,-101,-2)` | t4底钝化；t5结构；t6D−100→−101回落恰1%，直接退回底钝化；虽然C101>100，不生成WAIT/重新激活记录，不清空原参照。 |
| RC-48 不足1%回转仍结构 | 顶`TS;(104,99.5,2)`；底`BS;(96,-99.5,-2)` | t6反向变化0.5<0.99，结构保持且尚未首次反色，不能用价格新高/新低单独撤销。 回转也不能累计：顶`TS;(104,99.6,2);(105,100.1,2)`，底`BS;(96,-99.6,-2);(95,-100.1,-2)`；t6变化0.6<0.99，t7变化0.5<0.996，仍保持STRUCTURE。虽然与t5相比累计变化1.1已超过0.99，也不能回钝化。 |
| RC-49 同段反复结构与钝化 | 顶`T;(103,99,2);(99,100,2);(104,99,2);(98,100,2)`；底`B;(97,-99,-2);(101,-100,-2);(96,-99,-2);(102,-100,-2)` | t5结构→t6钝化→t7结构→t8钝化，均原参照；每次以前一根实际DIF为基数，不重新要求价格突破，不反复首次activation，不把仍未反色的任一次结构当首次反色。 |
| RC-50 已有结构直接击穿 | 顶`TS;(104,201,2)`；底`BS;(96,-201,-2)` | t6先判断原参照被严格突破，直接从结构取消；不先退钝化、不生成中间DULL，不先建立等待后再取消。 |
| RC-51 双参照失效后回升也无用 | 顶RC-34后加`(133,100,2);(134,99,2)`；底RC-34底后加`(67,-100,-2);(66,-99,-2)` | 新增两根均NONE，没有新钝化；当前看似价格/DIF好转，不复活本段已失效的B/A，不用第三段。 |
| RC-52 零柱可转折和回转但不首次反色 | 顶`T;(103,99,0);(99,100,0)`；底`B;(97,-99,0);(101,-100,0)` | t5零日形成结构，t6零日达到1%回转直接回钝化；有色count保持2，均尚未首次反色、未分段，无WAIT。 |

### 14.7 结构首次反色与下一轮参照（53—64）

首次反色的是当根仍有效或当根刚确认的结构，不能复活已经消失的旧结构。首次反色事实必须具有可核对的发生根和首次反色根；字段/编码形式遵循本轮后续实现LLD，不在测试设计中伪造公开枚举。新反色根属于新色段。

| case | 前缀/完整追加输入 | 逐根结果及必须排除的错误 |
|---|---|---|
| RC-53 翻绿当根形成并首次反色顶部 | `T;(90,100,-2)` | t5相邻DIF没有反向变化，但真实翻绿独立确认顶部结构，并在同一根首次反色；仅一条结构形成事实，不再等第二次翻色或补1%条件；新绿段count=1。 |
| RC-54 翻红当根形成并首次反色底部 | `B;(110,-100,2)` | t5同根确认底部结构并首次反色；新红段count=1；旧绿段极值不含C110。 |
| RC-55 先成结构后安全翻绿 | `TS;(90,98,-2)` | t5形成；t6首次反色，原ref未破且C90未破原价103，FOLLOWING，不重复形成、不因新段NONE抹掉旧事实。顺序反例`TS;(90,100,-2)`虽相邻回转已达1%，仍先真实反色，不先退DULL；首次反色破价的独立预期见RC97。 |
| RC-56 先成结构后安全翻红 | `BS;(110,-98,2)` | t5形成；t6首次反色，C110未破原价97，FOLLOWING。顺序反例`BS;(110,-100,2)`仍先真实翻红、不先回钝化；首次反色根收盘低于97则依RC97当根价格消失，不能沿用旧“不撤销”断言。 |
| RC-57 翻色同根参照破则不首次反色 | 顶`TS;(104,201,-2)`；底`BS;(96,-201,2)` | t6优先原参照突破，直接取消；不首次反色、不补color_flip结构。与RC-55/56形成正反对照。 |
| RC-58 结构后持续零不首次反色 | 顶`TS;(104,99,0);(105,99,0)`；底`BS;(96,-99,0);(95,-99,0)` | t6/t7仍为原逻辑段、结构保持尚未首次反色；不能因新收盘高低价或零柱误首次反色/撤销。 |
| RC-59 顶部考核期价格破不单独撤销 | `TS;(104,98.5,2)` | t6价格104高于结构时段最高103，但DIF继续向下、未破旧峰200、未反色，仍维持尚未首次反色顶部结构；不报历史价格撤销。 |
| RC-60 底部考核期价格破不单独撤销 | `BS;(96,-98.5,-2)` | t6价格96低于结构时段最低97，但DIF继续上升，保持尚未首次反色底部结构；不因收盘新低撤销。 |
| RC-61 分隔反色段逐根比价 | 顶`TS;(90,98,-2);(104,97,-2)`；底`BS;(110,-98,2);(96,-97,2)` | t6合法FOLLOWING，t7仍反色段但收盘严格突破原103/97，当根旧价格消失，startNone/count0；不能等待下一同色段。 |
| RC-62 后续不延续原DIF考核 | 顶`TS;(90,98,-2);(100,201,-2)`；底`BS;(110,-98,2);(100,-201,2)` | t6已首次反色；t7原ref DIF虽被突破，但当根价未破103/97，旧结构仍FOLLOWING，不因跨色原ref失效撤销。选择安全价格以隔离本目的，不能再用150/50混入价格消失。 |
| RC-63 原段成为近参照且旧新事件独立 | 顶`TS;(90,0,-2);(110,95,2);(111,96,2);(112,95,2);(100,94,-2)`；底`BS;(110,0,2);(90,-95,-2);(89,-96,-2);(88,-95,-2);(100,-94,2)` | t6旧结构FOLLOWING；t7下一同色第一根价格突破原103/97，旧结构消失且新段count1，不新钝化；t8新段count2首次DULL，参照为刚结束原段103/D100或97/D−100；t9新STRUCTURE；t10首次反色进入新FOLLOWING。原t5形成/t7消失与t9形成/t10反色各自记录，不能覆盖或复活。 |
| RC-64 已失效结构不复活；新段可新判断 | 顶`TS;(104,100,2);(105,201,2);(90,100,-2);(106,100,2);(107,99,2)`；底`BS;(96,-100,-2);(95,-201,-2);(110,-100,2);(94,-100,-2);(93,-99,-2)` | t6先回钝化，t7原参照破而取消；t8虽真实翻色，但没有当时有效旧结构/钝化可确认，不首次反色或复活t5旧结构。t9再翻回，t10依新完成同色段作近B而首次新钝化：顶B价105/D201，底B价95/D−201。本轮失效记忆不能跨到新逻辑段阻止新判断；历史t5形成、t6失去结构、t7钝化消失事实保留。 |

### 14.8 反色优先级、已选远参照和零柱失效（65—69）

| case | 前缀/完整追加输入 | 逐根结果及必须排除的错误 |
|---|---|---|
| RC-65 已钝化翻色同根击穿 | 顶`T;(90,201,-2)`；底`B;(110,-201,2)` | t5进入本根前为钝化；本根既真实反色又严格突破原B，必须先取消原钝化，不产生color_flip结构、不首次反色。新反色段count=1；不得因首次反色优先首次反色已失效对象。 |
| RC-66 已选A后A被击穿 | 顶RC-27顶序列后追加`(133,301,2);(134,190,2)`；底RC-27底序列后追加`(67,-301,-2);(66,-190,-2)` | t6活动参照A；t7突破A，直接取消、不救援第三个；t8虽价格仍越过B/A、DIF回到可背离的范围，但两个参照本轮都已被严格突破，不能回B或A、不重新钝化。原t6首次事件参照仍A。 |
| RC-67 零柱原参照破也处理 | 单参照顶`T;(103,201,0)`，底`B;(97,-201,0)`；两参照顶`ABTD;(132,201,0)`，底`ABBD;(68,-201,0)` | 单参照t5取消钝化；两参照t7当根B失效、A完整合格，切A保持钝化且不新增消失/首次钝化事件。四个变体均不增加有色count（仍2）、不分段、不首次反色。零柱不代表跳过DIF突破。 |
| RC-68 未够两根时零柱击穿也记忆 | 顶从空`(100,200,2);(90,0,-2);(101,100,2);(102,201,0);(103,100,2)`；底`(100,-200,-2);(110,0,2);(99,-100,-2);(98,-201,0);(97,-100,-2)` | t3当前有色count=1；t4零柱使B本轮失效，但此前尚未钝化，不伪造取消事件、count仍1；t5才有两根有色柱，DIF虽回升/回落到合格范围也不能首次使用B。不能等根数满2后才开始记录参照击穿。 |
| RC-69 已钝化价格恰等门槛仍保持 | 顶`T;(100,100,2)`；底`B;(100,-100,-2)` | t5已有钝化，当前价格恰等B价格100，DIF未破且没有相邻转折，保持原参照钝化，无新事件；与RC-18首次价格等号不合格明确区分。 |

### 14.9 输入、内存与消费者配套回归（70—73）

这些是识别规则的工程保护，不新增识别算法或触发源。不以模拟输入替代源接入、API/页面或性能验收。

| case | 独立输入与操作 | 必须断言 |
|---|---|---|
| RC-70 输入拒绝与正常反例 | 对`T`的t5分别给completed=false、重复/逆序时间、C0/负数、C/D/DEA/H为NaN/Infinity、bool冒充数值、缺失字段；另给正常有限微小数值及合法相等DIF | 非法根在更新前拒绝，原对象、之前返回事件和首次反色事实不变；正常小值/相等值不误拦。日期校验与真实日历完整性分属输入和源接入，不能用周末人工根证明交易日完整。 首次反色后的错误输入另以RC-55或RC-61为前缀逐项重复，核对已有形成/首次反色时间与原参照不变，不能仅在T尚无首次反色记录时作空断言。 |
| RC-71 连续与恢复一致 | 用RC-49和RC-63分别在首次钝化、尚未首次反色结构、首次反色根前后分割；在新独立实例恢复合法内存副本继续；另分别破坏参照身份、首次反色先后关系、NaN、记录关联 | 连续与恢复的每根业务事实、参照、时间一致，实例不共享可变对象；错误副本全部验证完之前不替换旧对象，失败不污染原状态。恢复后必须按本次首次反色起比价、跳过单根段及首个有效段结束的完整范围判断，不能提前停也不能延长；失效参照记忆在恢复后仍存在。无磁盘恢复文件。 失效记忆必须使用真实含击穿的人工前缀验证：RC-16/17在t3严格突破后切开恢复，再输入t4/t5恢复一侧的DIF，仍不得钝化；RC-66在t7远参照也突破后恢复，再输入t8仍NONE，不能恢复后丢失B/A本轮失效事实。 |
| RC-72 前缀与历史查看无未来信息 | 用RC-55、RC-61、RC-63分别截至形成根、首次反色前一根、首次反色根、新轮钝化根查看；再追加未来输入；窗口左边裁去旧参照，但保持同一完整前缀来源 | 形成时不能预知未来首次反色；历史截至首次反色前仍呈尚未首次反色，首次反色后事实不变。已返回旧结果不被追加原地修改；历史查看用该前缀状态，不能读末尾首次反色信息。页面窗口起点不改事件、参照或编号。 |
| RC-73 新事实合同与显示一致 | 用RC49/50/55和RC74/77/80/88的独立字面事实走后续真实序列化/解码/显示，旧WAIT和错误身份作反例 | 普通CANCEL与debug旧结构id正确关联；同根旧消失与新事件都显示，事件数组按time允许同时间不同id，唯一性只按id检查，正常FINISHED不显示消失；保留首次反色时间。前端不以当前NONE或相反方向丢事件，不重算条件。 |

### 14.10 规则到case的对账表

| 已确认规则 | 必须覆盖的case |
|---|---|
| 只用完成根/有限合法值/日期顺序 | RC-70，另沿原源接入测试 |
| 真实反色分段、零中性/不计根、不借未来颜色 | RC-01—06、RC-10、RC-44、RC-52、RC-58、RC-65、RC-67—68 |
| 历史极值独立日期、并列保持、反色首根不进旧段 | RC-02、RC-07—10、RC-63、RC78—79、RC97 |
| 首次同根C/D、严格等号、第二有色根可首次 | RC-05—06、RC-11—15、RC-18—20 |
| 本轮严格击穿使该参照永久不可回用 | RC-16—17、RC-20、RC-27、RC-34、RC-36、RC-45、RC-51、RC-66—68、RC-71 |
| TOP正DIF、BOTTOM不加负号、历史单根保留 | RC-21—24 |
| 最近B优先、A备选、两段上限及双价格门槛 | RC-24、RC-26—30、RC-35—37、RC-63 |
| 已钝化B失效当根切A、原事件参照不改 | RC-31—36、RC-66—67 |
| 既有钝化保持不再要求首次价格门槛 | RC-38、RC-42、RC-45、RC-49、RC-69 |
| 相邻实际DIF1%、含等号、不累计、前值0和前零根 | RC-25、RC-39—44、RC-46—49、RC-52 |
| 顶底结构回转统一回DULL，无WAIT/再激活 | RC-46—49、RC-52、RC-73 |
| 原参照破优先于回转/首次反色，STRUCTURE不救援 | RC-37、RC-50、RC-57、RC-65—67 |
| 首次反色有效者首次反色，同根形成也可首次反色 | RC-03—04、RC-53—57 |
| 原色段不按价格撤销；首次反色起逐根比价、单根不终止及同根显示 | RC48/55—62、RC74—110；预测PF21—34；公开投影/TS RC104/107 |
| 下一轮近峰谷推进、旧结构不能复活 | RC-63—64、RC85—87、RC98—101 |
| 内存恢复、因果、消费者一致且不落盘 | RC-70—73 |

### 14.11 实施时的验收要求与本轮停点

1. RC01—96及本次补充RC97—110共同构成当前规则目录，不等于实际测试数量。已实现用例逐case引用编号并保留独立输入/预期；§15仅记录修改前执行覆盖；本次目标用例仍须重新执行，公开部分按P3后续步骤验收。
2. 将每条case实际执行的所有追加根都纳入断言，不能只比较最后状态。失败时报告case、根位置、参照、C/D/H及实际事件；不得把旧r4/r2结果自动写成新expected。
3. 首次钝化、同根切远、结构形成/回转/直接失效、首次反色及新轮参照分别有正反例。任何规则若改动，必须能指出本节哪条应通过、哪条必须拒绝，不以“已有测试总数很多”替代覆盖。
4. 原始案例与旧报告保留为历史，不重写旧运行结果。旧测试中跨根借价格首次、永久不失效/无限跨段撤销、底部等待的expected必须按本轮确认逐项替换；有限窗口内撤销是本次必要正例，不能把这些旧expected继续当新验收标准；原有限值/恢复不污染/取消清理等正确工程目的仍保留。
5. 本次修正前P3第1/2步及整体有限跟踪的历史验收见§15—17。公开API/前端、清退、真实行情、整链性能和浏览器验收仍未完成；本轮不提交/部署，不自动进入第3步。


### 14.12 编码分支、函数和用例逐项对应

| 执行位置 | 必须对应的既有case | 必须断言的禁止项 |
|---|---|---|
| 输入、开头零、首次非零建段 | RC01、06、10、70 | 不借未来颜色、不改变旧对象、不在新方向首根首次钝化 |
| 同色/零更新各自极值与计数 | RC02、05—10、44、52、58、67—68 | 零不计数/首次反色，日期并列不漂移，反色根不进旧段 |
| 首次资格与每个ref曾破 | RC11—25、27—30、51、66、68、69 | 不借旧C、当前D不能替代曾破记忆，等号不当严格破 |
| B先A后/仅两个 | RC24、26—30、35—37及下列新增样本 | 不按强弱、不查第三个、一个ref破不使另一个失效 |
| DULL保持/救援/取消 | RC31—38、42、45、49、66—69 | A次根才合格不抹前根取消；STRUCTURE/翻色不救援；不改原事件 |
| 1%形成/回转 | RC25、39—44、46—49、52 | 当根首次只DULL、不复查C、不累计、不跳零、不WAIT |
| STRUCTURE原ref破优先 | RC37、50、57、65 | 直接CANCEL，不中间DULL，不同根再首次 |
| 真实反色与首次反色 | RC03—04、43、53—65、97/105/106 | 先原ref破、再转FOLLOWING；已有结构不重复形成；旧死结构不复活 |
| 结构终态、新轮ref推进 | RC49、55—64、71—73、98—103/109 | FOLLOWING按有限规则推进；FINISHED/DISAPPEARED不复活；第二轮有新id/记录 |
| 恢复/增量/asOf/消费者 | RC70—73、89—93、98—109 | 无未来终态、无共享对象、错副本不污染、正常早前缀不误拒 |

上述方法对应§3.10。每个business case四周期逐根执行，必须覆盖当前状态NONE/DULL/STRUCTURE与同色/零/反色三种柱情况；不可达状态由恢复/输入反例拒绝，不凭空补一条业务分支。

| 旧状态/柱 | 必查事实与互斥结果 | 必须抓住的反例 |
|---|---|---|
| 开头无段/零 | 仅previous/processed推进，无未来方向 | RC01/70 |
| 首次非零 | 新段count1，NONE | RC06/10/11/12 |
| NONE/同色或零 | count、TOP正D、近价、B后A当根C/D及曾破；仅首次DULL | RC05/06/11—30/51/66/68 |
| NONE/反色 | 旧段归档，新段count1；不复活旧结构 | RC10/23/64 |
| DULL/同色或零 | 未破→1%形成或保持；B破→当根A完整资格或取消；A破→取消 | RC31—45/52/66—69 |
| DULL/反色 | 原参照破→取消；未破→color_flip形成且首次反色，再当根检查原段价格；无远救援 | RC03/04/43/53/54/65/105/106 |
| STRUCTURE/同色或零 | 原参照破→直接取消；未破→1%回DULL或保持 | RC37/46—52/58—60 |
| STRUCTURE/反色 | 原参照破→取消、不进入FOLLOWING；未破→原结构首次反色并当根比价，可直接最终DISAPPEARED、不重复形成 | RC55—57/97/106 |
| FOLLOWING旧结构/每根 | 依§3.11推进有界跟踪、排除单根结束；正常结束无事件，价格失效有独立关联 | RC61—64/74—110 |

### 14.13 新记录、恢复、查询与前端配套断言

以下作为RC70—73的明确子样本，不改变原编号或声称新增测试已执行：

- RC70：输入拒绝必须发生在修改任何本根进度前；分别从空、DULL、STRUCTURE及已存在首次反色历史的结果开始验证。不能只测空对象“未变化”。再在本根事件/结构已构造后、step发布前故意触发内部校验失败，必须证明整个self进度、根前记录及此前输出未变化，不能只验证输入早拒。
- RC71：在RC16/17首次前已破、RC19/20首次仅相等后再严格背离、RC66远处也破之后分别snapshot→restore→追加表中恢复价/D；应分别保持本轮失效、允许合法严格背离、两个均不可回用。另从RC45的t5等号保持状态恢复，追加其t6严格突破根必须CANCEL，不能误判“恢复背离”。快照旧pending/WAIT或lockedAt额外字段、history缺键/含"0"或"2"/使用整数键、缺六字段参照日期、FOLLOWING/DISAPPEARED伪装activeStructure、错形成事件/id/参照/时点均拒绝。合法历史单根/零日/当前收盘已回历史价内侧、更早前缀仍可恢复，不误拦。
- RC71连续/恢复完整结果：保留分割前已取得steps及结构聚合，恢复后追加steps，和从空连续算逐项一致；不要求有界snapshot凭空重建全部旧事件。主动把同id FINISHED/DISAPPEARED改回ASSESSING、改其形成/首次反色时间或原参照必须在聚合层失败。
- RC72：分别以RC55/56首次反色根前后和RC47回转根前后为asOf，早根投影为ASSESSING且无未来终态时间，晚根应按对应时点为FOLLOWING或DISAPPEARED，不能把FOLLOWING当终态。此前已经返回的对象不变；最新缓存不能改变较早calculator_at。RC63两轮结构均保留，不能仅存最后一条。另固定RC55/56的来源修订反例：顶仅把t5收盘103改104，DIF99/H2不变，新结构priceExtreme必须104、旧返回记录仍103；底仅把t5收盘97改96，DIF−99/H−2不变，新极值96、旧仍97。标签及形成/首次反色时间不变，新entry必须从空重建，不受旧终态限制、不混用旧结构记录，旧entry和已返回对象保持不变。再在候选calculator成功step之后故意让结构聚合/完整校验失败，必须丢弃候选entry、缓存仍指旧entry且无半份返回；不得错误要求已丢弃的局部calculator回滚。
- RC73：普通无debug的合法结构事件、debug完整结构及全部关联均有字面样本。历史point.activeStructureId可引用截至查询时已FOLLOWING/DISAPPEARED的record，只要在该point发生时仍考核；不能因record当前已首次反色而拒绝合法历史point。当前活动结构因回转、参照破或首次反色离开考核期后，本根activeStructureId为None，color_flip同根形成首次反色也为None。独立旧结构FINISHED/价格消失不清空另一个仍有效的当前activeStructureId，按RC88/96核对应关系。窗口外形成、窗口内终结仍带记录；反向悬挂/未来日期/错方向/重复形成关联/旧字段拒绝。
- RC73前端仅显示普通事件DULL/STRUCTURE/CANCEL与源DIF；旧RESEARCH_HISTORICAL_WITHDRAWAL作为拒绝反例，新CANCEL/structure_price_break是必须支持的正例；不从计算/响应事件全集删事件；仅按后端displayOnChart选择图表与普通说明，debug仍保留全部关联。debug渲染使用六字段参照原日期及结构终态；普通未提供debug信息时照常展示正常状态/事件/时间，不推断等待。

### 14.14 本轮交付边界

§15—16仅保留修改前两步成绩。本次先按当前三项修正修P3第1步及内部配套，再同步第2步旧结构预测，按RC01—110/PF01—34分层验收；当前三项尚未实施，§17.4仅记录修改前基线。RC73及RC93的公开HTTP/前端和完整请求验收仍依后续步骤，不自动进入第3步或部署。

### 14.15 旧结构跟踪及同根显示的修订用例（RC74—96，修改后待重新验收）

沿§14.2从空状态输入T/B/TS/BS，不用待测函数生成expected。TF=`TS;(90,98,-2)`，BF=`BS;(110,-98,2)`：t6首次反色，旧TOP/BOTTOM为FOLLOWING，originWave价格103/97，当前startNone/count0，trackingPriceExtreme为90/110、日期t6。TN=`TF;(102,97,2);(103,96,2)`，BN=`BF;(98,-97,-2);(97,-96,-2)`：t7/t8当前同色段count1/2、start=t7，均未严格突破原价格，跟踪极值103/97首次于t8。

以下旧编号继续保留，但修改后的输入/预期不能引用§17旧通过数量。core输出完整事件；displayOnChart只在公开投影/前端层断言。

| case | 顶部及底部字面输入/操作 | 独立预期 |
|---|---|---|
| RC74 第一根价格消失 | `TF;(104,97,2)`；`BF;(96,-97,-2)` | t7旧CANCEL/structure_price_break及DISAPPEARED；start=t7/count1，跟踪极值104/96@t7；新色段仅1根无DULL。旧消失应显示。 |
| RC75 分隔反色段也检查价格 | `TF;(104,97,-2)`；`BF;(96,-97,2)` | t7立即旧价格消失，startNone/count0，极值104/96@t7；不能延至下一同色柱。 |
| RC76 严格等号 | `TF;(103,97,2);(103,96,2);(104,95,2)`；`BF;(97,-97,-2);(97,-96,-2);(96,-95,-2)` | t7/t8等于103/97，旧FOLLOWING、无新钝化；t9旧CANCEL与新DULL均保留，仅新activation绘制。相等极值日期不漂移。 |
| RC77 同根旧消失与新钝化 | `TF;(102,97,2);(104,96,2)`；`BF;(98,-97,-2);(96,-96,-2)` | t8先旧CANCEL、后DULL/activation，旧结构DISAPPEARED、普通DULL；内部2项，公开events仍2项且旧displayOnChart=False、新True，markers及普通当根说明仅DULL，debug可查2项。 |
| RC78 原段最终高点 | `TS;(105,98.5,2);(100,98,-2);(104,97,2);(106,96,2)` | 形成t5极值103固定，t6原段最终105；t7首绿C100不入原段且未破105；t8红C104不撤销，t9C106旧消失+新DULL。将t6H2改H0，最终高105仍有效、原有色count减1。首绿不能再用C110，否则新规则在t7就应消失。 |
| RC79 最终低点镜像 | `BS;(95,-98.5,-2);(100,-98,2);(96,-97,-2);(94,-96,-2)` | 形成极值97，原绿最终95；首红100排除且未破95，t8C96保留、t9C94消失+新DULL。将t6H-2改0，最终95仍参与。 |
| RC80 有效同色段结束 | `TN;(120,95,-2);(121,94,2)`；`BN;(80,-95,2);(79,-94,-2)` | t9因根前有效段count2已结束，先FINISHED，不能用t9突破价造旧消失，跟踪极值仍103/97@t8；t10不复开。另测color_flip形成路线。 |
| RC81 DIF拐头不结束 | `TN;(102,98,2);(104,97,2)`；`BN;(98,-98,-2);(96,-97,-2)` | t9同色仍跟踪，t10严格价破才旧CANCEL+新DULL，显示只DULL。 |
| RC82 分隔段零柱比价 | `TF;(110,97,0);(104,96,2)`；`BF;(90,-97,0);(96,-96,-2)` | t7零未开始同色段，但已价格消失，startNone/count0；t8不重复补旧消失。 |
| RC83 单根同色后零价破 | `TF;(102,97,2);(104,96,0)`；`BF;(98,-97,-2);(96,-96,0)` | t8零不增count，仍1；旧结构价格消失，新DULL根数不足，消失须显示。 |
| RC84 同色零同色 | `TN;(102,95,0);(102,94,2)`；`BN;(98,-95,0);(98,-94,-2)` | t9零count仍2，t10实柱count3；start仍t7，未破价仍FOLLOWING，无FINISHED。 |
| RC85 消失不复活 | `TF;(104,97,2);(102,96,2);(104,95,2)`；`BF;(96,-97,-2);(98,-96,-2);(96,-95,-2)` | t7旧消失仅一次；t8价回不恢复；t9可独立新DULL，不重复旧消失。不因后来钝化改写t7显隐。 |
| RC86 回转旧结构不复活 | `TS;(104,100,2);(90,99,-2);(105,98,2)`；`BS;(96,-100,-2);(110,-99,2);(95,-98,-2)` | t6原t5结构dif_return消失、普通DULL；t7color_flip形成新id并FOLLOWING；t8只对t7结构价格消失，不能再次撤销t5。 |
| RC87 原段用作远参照 | `TN;(102,95,-2);(103,98,2);(104,99,2)`；`BN;(98,-95,2);(97,-98,-2);(96,-99,-2)` | t9旧FINISHED，t10/11可按原规则选参照；不复开t5。单根段仅影响跟踪结束资格，不修改正常候选池。 |
| RC88 不同方向同根 | 顶`(100,200,2);(90,-200,-2);(101,100,2);(102,100,2);(103,99,2);(89,-100,-2);(88,-100,-2);(87,-101,-2);(104,90,2)`；底`(100,-200,-2);(110,200,2);(99,-100,-2);(98,-100,-2);(97,-99,-2);(111,100,2);(112,100,2);(113,101,2);(96,-90,-2)` | t9旧TOP/BOTTOM价格CANCEL与相反方向color_flip结构各自关联、均绘制；不能套用同方向新activation隐藏规则。 |
| RC89 恢复安全 | TF/BF及新增RC98/101合法进度；分别改终态、NaN、未来start、bool/count、方向、originWave、跟踪极值或firstOpposite | 坏副本在普通NONE也拒绝，self/来件不变；正常单根已跳过及原段已淘汰不能误拒。原始分隔段仍可核时，伪firstOpposite为其第二根必须拒绝。另见§14.16及RC102。 |
| RC90 连续/分批/复制 | RC74/77/78/80/88/98/101/105于形成、首次反色、单根结束、下一同色起点、消失/正常结束前后分割 | 四周期事件/记录/全部新字段、参照和id逐根一致，无共享、无落盘。合并分割前已得steps，不要求snapshot复制旧全集。 |
| RC91 历史asOf | RC78各t5—t9及RC103跳过单根序列；追加未来后再查同asOf | 形成极值103固定；t7才有origin105和跟踪100；t8start/count为t8/1、跟踪104；t9消失/极值106。未来重查不改过去起点/根数/极值。 |
| RC92 来源修订 | RC78仅把t6C105改106 | 新源最终原价106，t9C106等号无消失/新DULL；旧源仍t9消失；形成103与t5不变，按新源从空重建，不混旧缓存。 |
| RC93 聚合/公开/TS | RC77/88/98/103/105完整字面预期，经真实内部模型/query，再按阶段经公开投影及TS/renderer；错原id/方向/字段/显隐 | 同id单根重置可合并，终态不重开；asOf不泄未来。public事件标志必填且完整事件不丢；普通无structures，debug字段/关联齐全；不同方向及其他事件不能隐藏。 |
| RC94 5月机制样本 | `(3285.6705,41.186,2);(3200,0,-2);(3393.3312,28.215,2);(3380,28.215,2);(3301.2575,22.901,2);(3275.413,16.415,-2);(3395.0036,14.006,2);(3357.6707,15.217,2);(3319.1506,12.920,2)` | t5结构、t6首次反色；t7旧消失而新根数不足，显示消失；t8/9当根价格不足，无新DULL/STRUCTURE。不冒称完整真实EMA，真实922根另专项。 |
| RC95 故障不半发布 | 对TF/BF及RC77/98，在跟踪、普通分支和候选聚合构造后注入验证失败，正常同输入对照 | 核心校验失败self不变；聚合失败丢弃候选entry，已发布旧entry/缓存及旧返回对象不变，不要求已丢弃的局部calculator回滚。无半份消失/新DULL，正常路径通过，最后发布前仍查取消。 |
| RC96 两槽独立 | RC88顶部最后104改102，再`(102,91,2);(86,-90,-2)`；底最后96改98，再`(98,-91,-2);(114,90,2)` | t9可有两槽，t11一个已完成有效同色段正常FINISHED、另一个价格破DISAPPEARED；新字段/事件按对应方向分别处理，第三槽/重复id拒绝。 |

预测既有编号修订：

| case | 独立输入/数学预期 | 必须验证 |
|---|---|---|
| PF21 分隔反色段的顶部价格条件 | TF；手写EMA(198,100,99)，D(C)=(28C+26306)/351，H红界8443/28；C104仍绿却>103 | 旧结构价格范围只C>103，无H谓词；显示最小整数104（不再是302）。103等号不触发，104原EMA/source_options核验True。 |
| PF22 底部镜像 | BF；EMA(200,298,-99)，D(C)=(28C-37450)/351 | 旧范围只0<C<97，最大整数96；不要求新绿柱或两根，不额外比较DIF。 |
| PF23 有效同色段结束边界 | TN/BN，count2；顶EMA(196,100,95)，D(C)=(28C+25712)/351，红/零界7633/28 | C104翻绿，旧正常结束而非消失；C273仍红且>103，旧消失。count2时H约束仍必要，零不结束。底BN手写EMA(100,196,-95)，D=(28C-34000)/351，绿/零界655/28；C96翻红正常结束、C23仍绿且<97旧消失，合法整数上界23。 |
| PF24 普通与旧条件独立 | TN/PF23；C273普通B有效，C400旧价格消失但普通完整step可能查A；把未评估A资格/救援/求解设为调用即失败 | 近B有解不算A；旧核验只用唯一旧跟踪函数、不偷选A。同根完整事件保留，数学条件不因图上displayOnChart=False而删除。 |
| PF25 终态不预测 | RC74消失后、RC80正常结束后，与TF/BF/RC98单根已跳过的合法旧跟踪对照 | 终态无旧条件，合法FOLLOWING仍求；不以全空替身掩盖问题。 |
| PF26 普通静态退出仍求旧条件 | 顶TS追加(90,-1,-2)，手写EMA(100,101,0)，D=(28C-3125)/351；底BS追加(110,1,2)，EMA(101,100,0)，D=(28C-2503)/351 | 顶C104虽不必翻红仍旧价格消失；底C96同理。普通确定无解仍校准一次/一个端点求旧条件，可READY且不造参照。原两类合成确定/未决/无解字面草稿保留，不能把未决说无解。 |
| PF27 关联及整数 | PF21—23原EMA必要价点、合法整数；故意改relatedStructureId/价格等号/错误count或省略新增字段 | 正常C104/96与对应根数路径可认证，等号/错目标/错计数拒绝；原证明或整数不符整次失败，不因新H无约束而放松原数值检查。 |
| PF28 预算/取消/同源 | RC96两槽+普通关系；取消在旧核验后和输出前；普通/debug同一前缀 | 无新读源、历史复制或额外端点；同ID/同内部条件，原400ms含新字段校验与投影/最终输出，人工数学不代替整链。 |

PF21—23等是隔离人工EMA/源选项数学，不声称价格来自同一完整市场EMA史；四周期分别走原精度和核验流程。修订预期不得引用修改前已通过数量，新增PF29—34见§14.17。

### 14.16 恢复、聚合、窗口和显示的明确子样本（修订后待实施）

| 父case | 独立操作与预期 |
|---|---|
| RC89/102 破价回撤恢复 | 分隔段`TF;(104,97,-2);(102,96,-2)`及底`BF;(96,-97,2);(98,-96,2)`在t7已消失；伪装FOLLOWING时保留跟踪极值104/96@t7必须拒绝。零段同理。正常`TF;(103,97,-2);(102,96,-2)`及底97/98等号未破，恢复通过。不得再把分隔段104/96越过列为合法反例。 |
| RC80 color_flip正常结束 | 顶`T;(90,100,-2);(101,99,2);(102,98,2);(120,97,-2);(121,96,2)`；底`B;(110,-100,2);(99,-99,-2);(98,-98,-2);(80,-97,2);(79,-96,-2)`。t5形成并首次反色，原价102/98；t6/7同色count1/2且未破，t8先FINISHED、跟踪极值不纳入120/80，t9不复开。 |
| RC90 连续/恢复 | 上一行t4/5/6/7/8/9及RC101单根跳过处切开恢复；同根形成并消失的RC105也切开。snapshot不带已终结全集，已有steps的完整聚合与连续字面预期一致。 |
| RC91/103 asOf | 上述color_flip序列各根：t4未形成，t5直接FOLLOWING、原价102/98且跟踪90/110，t6/7当前同色计数1/2，t8 FINISHED且无CANCEL。RC103逐根查单根起点重置/重新填写与跟踪极值，不能仅把最新记录日期清空。 |
| RC93 分隔段无事件窗口 | `TF;(90,97,-2)`、`BF;(110,-97,2)`只查t7、limit1：point一条、无事件，debug仍有旧FOLLOWING，startNone/count0，跟踪极值及日期正确；普通不带structures，不为可查看造事件。 |
| RC93 同色及正常结束窄窗口 | TN/BN只查t8，旧形成/首次反色/start都在窗外仍有FOLLOWING/count2；RC80只查结束根有FINISHED、无消失marker，次根无引用/变化不附带。当前结构普通状态不被旧记录后来终态覆盖。 |
| RC93/104 同根显示真实消费者 | RC77内部两事件→后端公开投影→严格decoder→buildXxmViewModel→普通/注入debug renderer：response.events仍2，markers与displayEvents仅DULL；debug完整关联可见旧DISAPPEARED。旧消失不能在下一根补画。不能用预先手删CANCEL的fixture冒充通过。 |
| RC93 窗口/asOf/错误 | 改limit/startDate仍保留同一根及through时，所有同根事件/标志/id相同；空窗口数组空、source/dataStatus仍真实。先做全记录/前缀校验再过滤，非法跟踪不能靠小窗口隐藏。 |

### 14.17 本次三项修正新增覆盖（RC97—110、PF29—34）

长序列继续§14.1字面日期：t13=2023-01-19、t14=01-20、t15=01-30、t16=01-31，之后02-01、02、03、06、07、08、09、10依次使用；分钟仍各日15:00+08:00。本节是独立设计，未运行计算器生成预期。

| case | 完整追加字面输入/操作 | 独立预期 |
|---|---|---|
| RC97 首次反色当根就破价 | `TS;(104,98,-2)`；`BS;(96,-98,2)` | t6原ref未破、有效结构首次反色且当根价格破；旧t5记录最终DISAPPEARED，firstOppositeAt=t6、startNone/count0、跟踪极值104/96@t6，只有一次价格CANCEL；originWave价仍103/97，排除t6。 |
| RC98 单根结束后反色段破价 | `TF;(102,97,2);(102,96,-2);(104,95,-2)`；`BF;(98,-97,-2);(98,-96,2);(96,-95,2)` | t7候选count1；t8单根结束清None/0但仍FOLLOWING并比价；t9分隔段价格消失。不得t8 FINISHED或拖到再翻同色。 |
| RC99 单根夹零不凑两根 | `TF;(102,97,2);(103,96,0);(102,95,0);(102,94,-2);(104,93,2)`；`BF;(98,-97,-2);(97,-96,0);(98,-95,0);(98,-94,2);(96,-93,-2)` | t7—9有色count1，t8等号不破；t10真实反色清候选继续；t11第一根下一同色价格破。零不结束、不增加根数。 |
| RC100 有效段结束根不再比价 | `TN;(104,95,-2);(105,94,2)`；`BN;(96,-95,2);(95,-94,-2)` | t9根前有效段count2，先正常FINISHED，虽价越原门槛也无旧CANCEL；t10不复开。对照RC98单根结束根仍比价，不能把两条混用。 |
| RC101 多个单根、原段被池淘汰 | `TF;(102,97,2);(102,96,-2);(102,95,2);(102,94,-2);(102,93,2);(102,92,-2);(102,91,2);(102,90,2);(104,89,-2);(105,88,2)`；底`BF;(98,-97,-2);(98,-96,2);(98,-95,-2);(98,-94,2);(98,-93,-2);(98,-92,2);(98,-91,-2);(98,-90,-2);(96,-89,2);(95,-88,-2)` | t7/9/11均单根，t8/10/12不结束；t12原段可已被两候选池淘汰，旧记录仍合法有界；t13/14首个有效段count2，t15正常结束，极值仍102/98首次t7，结束根104/96不纳入；t16不复开。不得增加普通候选池或保存无限段列表。 |
| RC102 全程极值拒绝回撤伪造 | §14.16分隔段/零柱破后回撤，伪FOLLOWING保留跟踪极值与实际原来件副本；正常等号/未破对照 | 末根未越价仍拒绝曾破极值；当前反色Wave的相反方向极值不能替代该检查；非法来件/self均不被改，正常值通过。 |
| RC103 重置起点的历史查询 | RC101算完后依次查t6/7/8/9/12/13/14/15，再追加t16重查 | start/count分别None0、t7/1、None0、t9/1、None0、t13/1、t13/2、t13/2且FINISHED；跟踪极值t6是90/110，t7以后102/98@t7，t15不包含104/96。每次_response只calculator_at一次，不能每记录回放；旧对象不变。 |
| RC104 同根只画新钝化 | RC77及RC76最后根的完整真实内部结果，经公开投影/TS/renderer | 旧CANCEL False、新activation True，2个事实/id/关联不变、1个钝化marker，普通说明只钝化，debug可查2项；下一根不补画旧消失。公开缺标志/null/数字/字符串或DULL被标False拒绝。 |
| RC105 color_flip形成同根破价 | `T;(103,100,-2)`；`B;(97,-100,2)` | t5有效DULL先color_flip形成结构，origin价102/98，再当根价格破；事件STRUCTURE/color_flip后CANCEL/structure_price_break，两项均显示（无activation）；只一份最终DISAPPEARED，形成=首次反色=消失=t5，count0，原段极值日期<t5。查询/聚合/恢复接受合法终态，不能伪FOLLOWING。 |
| RC106 首次反色原DIF破优先 | `TS;(104,201,-2)`；`BS;(96,-201,2)` | t6只CANCEL/dif_break_on_flip、reference_dif_break；不进入FOLLOWING、不重复价格CANCEL，firstOpposite/origin/跟踪极值均None，候选count0。 |
| RC107 显示不误隐藏 | RC88不同方向完整序列；纯event_display_flags字面反例将新DULL的route改dif_return或改日期/方向，另单独价格CANCEL | 不同方向/日期、DULL/dif_return、STRUCTURE及普通dif_break均True；无新activation时旧价格CANCEL也True。纯函数反例只验证显示范围，不冒充该组合为真实核心可达行情。 |
| RC108 近峰价格门槛保护 | 顶`(4165.287,60.557,2);(4100,0,-2);(4182.5909,30,2);(4100,0,-2);(4170,47.343,2);(4170,47.343,2);(4225.0207,47.343,2)`；底`(100,-300,-2);(110,0,2);(80,-200,-2);(90,0,2);(90,-250,-2);(90,-250,-2);(70,-250,-2)` | t6根数够且远DIF可用、价只过远未过近，均不DULL；t7价同时过近远，选A首次DULL。顶4182.5909整数显示4183，现有规则保留，不为贴图改选峰。 |
| RC109 新字段/合并/故障 | RC98/101/105正常完整结果，分别省count、填bool/负数、start/count不配、非单根清起点、极值逆向/日期未来、终态伪恢复；RC105另造漏取消、取消早于形成、重复同id结构、错关联和未破价却取消；正常对照 | 真实类型/恢复/聚合/schema边界拒错且不半发布，正常单根清空、有效根数增长及同根形成消失均通过；不能删安全检查以放行新逻辑。 |
| RC110 视频差异与历史报告 | 后续专项复用同源922根与§28截图/稿件；在工具支持新身份和字段后才执行 | 对照01-08/07-23/08-22日期、2025-10-24单根跳过、04-14及2026-05-11计算两项/显示一项；分别报告计算事件和显示标签，不重写旧报告，不提前声称逐值复现原软件。 |

| case | 独立输入/数学预期 | 必须验证 |
|---|---|---|
| PF29 单根结束后仍可价格消失 | 顶`TF;(102,97,2)`，EMA(197,100,96)，D=(28C+26009)/351；C104会翻绿且>103。底`BF;(98,-97,-2)`，EMA(100,197,-96)，D=(28C-34325)/351，C96翻红且<97 | count1无H限制，104/96旧价格消失，不是正常FINISHED；显示边界顶最小整数104、底最大96，近远求解不参与旧检查。 |
| PF30 分隔零柱精确合法 | 顶`TF;(90,98,0)`，EMA(198,100,98)，C289原EMA得快212/慢114、D98/DEA98/H0；底`BF;(110,-98,0)`，EMA(100,198,-98)，C9得86/184、D-98/H0 | startNone/count0且H恰0仍价格消失；旧严格H>0限制必须能被此反例抓住，原数值/零不重置规则保持。 |
| PF31 已有效段的正常结束仍排除 | TN及PF23；C104反色且价破，与PF29同C但根前count2对照 | count2应正常结束无旧消失，count1应价格消失；不能为了修等待而去掉所有H约束。源临界保留未决，不拿理想H零直接认证全部选项。 |
| PF32 单根跳过后恢复求解 | RC98截至t8手写顶EMA(196,100,97)/底(100,196,-97)，RC101截至t12顶(192,100,93)/底(100,192,-93)，分别用各自下一端点；每个前缀连续计算与恢复计算使用相同EMA/endpoint/check，顶C104/底C96可旧价格消失 | 都仍预检出旧id，不因origin不在最近历史池或startNone提前退出；结果/范围/ID一致，无额外来源/日历读取、无复制历史全集。 |
| PF33 显示优先不删预测事实 | PF24普通B有解且旧结构价破有范围；实际候选完整step同时旧CANCEL与新activation | 数学旧范围、内部完整step和条件关联保留；图表标志只用于完成行情的展示，不为下一根预判求旧范围减新范围，也不合并近远范围。 |
| PF34 预算/取消/新身份 | 两槽新字段/单根跳过/源选项未决、旧v0.3识别或v0.5预测混入、check于原核验及最终构造失败，正常对照 | 新身份/新字段正常，旧混配拒绝；prepared/c不变，缓存候选不发布，finally释放；原400ms含校验、最多两份旧条件、最终输出，不以数学层计时代替整链验收。 |

## 15. 历史基线：P3第1步实施与独立验收（2026-10-30）

本节只保留本次有限跟踪修正前v0.2-r4实际实施与验收事实；其中旧LOCKED及不再撤销的行为不作为当前开发要求。最新规则与新增验收依§2—4及§14.15，当前实现和成绩另见§17.4。

**结论：新识别核心及完整内部结果已完成本步限定验收，独立审计通过。**本轮停止在§11.4第1步，不进入下一根预测、公开投影/API、前端、环境装配或P5清退。没有提交、部署、安装依赖、启动服务或读取真实行情；不能把本步结果解释为页面或完整产品已可用。

### 15.1 硬要求、代码及测试对账

| 本步要求 | 实际落点 | 独立预期与验证 |
|---|---|---|
| R01/R04/R06：唯一正式核心、完成根原值、首次同根C/D | `calculator.py:step/_current_reference_qualifies`、`types.py:XxmBar/Wave` | `test_xxm_r4_rules.py`逐根字面RC01—69；RC13/14禁止借旧价，RC15/19/20区分当根等号与曾突破；输入测试原值/日期/未完成/非法值反例 |
| R05/R07/R08：真实反色、零中性、两根、B后A最多两个、取消前当根切远 | `step/_reference_was_broken/_select_eligible_reference/_rescue_dull_reference` | RC01—10/16—37/65—69；包括A已破而B仍有效、A晚一根才合格、已有STRUCTURE/反色不救援；原首次事件参照不改 |
| R09/R10：原1%运算、统一回转、锁死终态 | `step/_start_structure/_finish_structure` | RC38—64；原float临界−99→−98.01不形成而−98.009形成；前0/零根/不累计；锁死后价格和DIF突破均不撤销，两轮结构分别保留 |
| 有界进度、拒旧及失败原样 | `types.py:XxmStructureRecord/XxmStep`、`snapshot_validation.py`、`calculator.py:_progress/_validate_step/restore` | RC70/71；合法历史单根、价格回门槛内侧、DIF仅曾相等及更早前缀可恢复；旧身份/旧字段/非法结构/数值/时点拒绝且self不变；构造后坏结果、错误终态或漏事件/结构也先拒绝后发布 |
| R12：观察不改变业务，未执行条件不伪造 | `calculator.py:_begin_decision/_finish_step`、`types.py:XxmDecision` | `test_xxm_r4_observation.py`125组字面变体×四周期，开/关观察的完整业务结果和快照相同；同根切远记录真实B突破、不再检查相邻转折，未查A为None；默认不分配观察对象 |
| 内部聚合、复制、历史前缀与源修订 | `query_service.py:SeriesEntry/_load_series/_merge_structure_updates/_response`、`InternalXxm*`模型 | RC72及RC73内部部分；从空/追加/真实1000根检查点/历史位置/现有clone一致；早asOf无未来终态，窗口外关联带齐；源修订新entry从空重建、旧终态及旧返回对象不变 |
| R19/R20/R21：无源码保护、无额外读取、沿原预算发布 | 新MAIN_SPEC、完整内部校验及`XxmCache.put(check=remaining)` | Spec固定完整字段及规范hash；缓存大小计算结束后、取得锁后修改前都检查同一截止；候选step成功后聚合失败、内部模型失败、统计/等锁超时都不替换旧缓存。普通/公开消费者迁移未在本步验收 |
| R22：依赖与交付范围 | CodeGraph调用影响面、根三架构、模块静态依赖检查 | 新核心仅标准库和本目录；不反向导入research/App/QTF；不修改源SQL、源指标、数据库/Lake、鉴权、API路由、预测求解或前端 |

新识别身份为`xxm-direction-v0.2-r4`，完整固定Spec生成的实际hash为`1c02c0d865689ba390da058cd377cd5b0b8509a46ec9b089d09985d12e8d928a`。该值是规则身份，不是源码SHA；本轮没有旧源码保护、旧算法捕获或双组重放。

实际源码修改为`calculator.py/spec.py/types.py/snapshot_validation.py`、`queries/.../query_service.py`及`schemas/.../index_detail_xxm.py`六份。`forecast_detector.clone`现有实现本来就通过同一个正式类和snapshot/restore复制，已以新进度验收，无须修改预测算法。新增三个测试文件`test_xxm_r4_rules.py/test_xxm_r4_restore.py/test_xxm_r4_internal_results.py`，并迁移五份既有当前核心/输入/观察/恢复/消费者测试。

### 15.2 已执行的有界测试

全部使用现有`.venv/bin/python -m pytest`，单组均低于60秒，没有安装依赖、skip或xfail。以下人工/隔离输入只证明本步内核和内部交接，不证明真实行情接入、软件一致性或HTTP/页面可用。

| 测试组 | 实际命令范围 | 最终结果 |
|---|---|---|
| 全部RC01—69、构造/恢复、输入与完整Spec | `test_xxm_r4_rules.py test_xxm_r4_restore.py test_xxm_input_validation.py` | 889项通过，1.08秒；其中规则504、新恢复285、输入100 |
| 内部结果、既有消费者、计算器观察 | `test_xxm_r4_internal_results.py test_xxm_snapshot_consumers.py test_xxm_r4_observation.py -k 'not observe_rows'` | 573项通过，2.02秒；其中内部39、消费者21、观察513。2个旧`observe_rows`工具节点属于P4，明确未执行、未计通过 |
| 通用快照验证 | `test_xxm_snapshot_validation.py` | 249项通过，0.85秒；独立字面合同、非法/正常变化、合法回退和四周期逐切点恢复 |
| 原核心人工节点 | `test_xxm_calculator.py`内`CURRENT_CORE_NODES`列出的7个节点，显式逐节点执行 | 19项通过，0.11秒；过时累计价、等待和跨色撤销expected已替换为当前独立规则 |
| 根目录三份架构检查 | `tests/architecture/test_subsystem_dependency_matrix.py test_platform_legacy_guardrails.py test_operations_legacy_guardrails.py`（后两份也位于同目录） | 16项通过，12.45秒 |

本步业务及内部回归共1730项通过，架构另16项；不得把参数展开后的数量当成1730条不同业务规则。主规则文件仍逐编号对应69组业务及其125个字面变体，RC70—72工程要求分布在恢复/内部结果测试中。RC73仅验完整内部事实及关联，真实HTTP序列化/TS解码/页面展示须P3第3—4步继续完成。

旧`test_xxm_calculator.py`的三个后续节点`test_entire_frozen_ordinary_and_historical_baseline`、`test_entry_partition_uses_current_price_and_keeps_waiting_copy`、`test_full_four_period_top_oracle_and_first_activation_are_preserved`保留原函数/装饰器及原材料，未执行、未用作本步证据；它们依赖后续旧runner清退或预测迁移，不能为跑绿本步而修改旧oracle。观察文件的两个工具节点同理按P4使用前整体迁移。当前通用输入、内存恢复、查询消费者和计算器观察均已按新规则执行，不以旧工具停点排除本属核心的失败。

### 15.3 独立审计、修复及停止位置

未编写对应实现的审阅者分别核对识别分支/Spec、恢复与构造后失败、内部query/schema及测试真实性。审计发现并修复了以下实际缺口，修复后又由非实现者复核源码及反例到达位置：

1. 完整step可能放过构造后被改坏的观察值、bool冒充数字、错误LOCKED终态或丢失整条事件/结构。现按真实工作进度、实际检查记录、状态变化和结构动作逐项校验后才发布；已有“失败不污染”要求没有放宽，新增反例包含修复前失败、修复后通过的证据。
2. 缓存内存统计和取得锁的耗时原先处在最后预算检查之后。现两处都沿原remaining检查且发生在修改entries之前；超时保留旧缓存，正常候选仍可发布。
3. 内部模型对锁死/极值时间、事件与同根point的状态/方向/参照/结构关联校验不够。现与进度及实际事实保持一致；窗口外形成的结构、真实反色根的新段NONE及合法无事件保持均有正例，不靠可见前根或其他校验碰巧拒错。

已使用`codegraph_explore`与`codegraph_impact`核对计算器、step/snapshot/restore、SeriesEntry/calculator_at、clone、内部模型以及API/预测/Wealth消费者影响面，并执行索引同步。普通API仍处于后续迁移前的中间状态，不执行旧HTTP或旧预测来声称新产品通过，不加旧格式兼容。源码及文档差异检查、文档完整性与相对链接检查随本步交付执行。

**当前无需要管理员重新拍板的识别规则或本步阻断。**下一步仍为§11.4第2步下一根预测，但本轮不自动推进。真实日线/分钟来源、完整400ms/4秒请求、API投影与一次编码、Wealth测试/构建/浏览器、生产禁用和P5清退均未验收。其他工作区修改保持原样，本步不自动提交或部署。


## 16. 历史基线：P3第2步实施与独立验收（2026-10-30）

本节只保留本次修正前v0.4-r4单根预测验收；尚未包含旧结构有限失效条件，不能作为§6.12已完成证据。

**此前结论（v0.4-r4基线）：单根预测纯计算、固定Spec及限定测试已完成，独立审计通过。**只证明当时内核基线，不覆盖本次§6.12有限跟踪，也不表示公开预测接口、页面或完整400ms请求已可用。当时没有提交、部署、安装、启动服务或读取真实行情；当前内部成绩见§17.4，第3步及后续仍未执行。

### 16.1 硬要求、实现及验收对应

实现均在`src/biz/services/wealth/market/index_detail_xxm/`，不新增产品实现目录。

| 要求 | 实际实现 | 独立用例与结果 |
|---|---|---|
| 真实进度先检查，只下一根 | types的五个内部结果类型；forecast的precheck_next_bar及单endpoint入口；拒不匹配prepared | PF02、17、20：静态退出不需投影/未来端点；合法当前条件可继续；旧序列入口、坏进度拒绝 |
| B有关系或关系未决，A均零调用 | forecast分开relationship_ranges/relationship_precision_ranges；固定A或STRUCTURE单独沿原参照 | PF03—06、09—10：A求解/资格调用即失败仍通过；无整数不冒充无解；关系已无解不被旁侧失效分类未决误拦 |
| NONE首次、已有DULL及STRUCTURE分别处理 | forecast_entry的solve_first_dull；forecast_next的solve_active_reference；复用唯一正式类/资格函数和恢复校验 | M1—M5及PF07—14：首次不在同根追加结构；零不补根数；B失效原语不顺带救A；已有结构不换A；锁死后按新段进入下一轮 |
| 原EMA/源值/1%次序不变 | projection未修改；forecast_expression保留实际有序运算、同源绑定及单步误差上下界；forecast_math的source_options与HEAD函数AST相同 | PF08、16、18：独立Fraction、字面有序EMA、原大数/零/最小数、来源分歧、同源谓词及2×2独立核验 |
| 直接反求有限边界，不取中点、步长或全float搜索 | solve_comparison/solve_predicates；三个直接线性根及相邻float候选；确定/不成立/未决三组范围 | PF01、08、15—16、19：跨float边界、相邻float空区间、有限零点与正常宽范围；同一门槛从10放大到1e12，线性边界求解仍各2次 |
| 必要点使用原规则核完整语义 | forecast_detector的evaluate_next_at_price、B失效原语；按事件及结构记录核状态、关联与锁死 | PF01、09、11—14、18：不能只看根末NONE；来源不同而语义相同可确认，语义分歧保留未决 |
| 整数只在合法范围内取，先转换再核验 | display_range及原点核验；不能精确保留整数、确定点或显示整数不一致均ValueError | PF15：开闭端、单点、无整数、9007199254740993转换变值、正常4136、只让显示整数失败的独立负例 |
| 真实进度与本次内存分离，失败清理 | clone/恢复同产品类；next_bar_evaluations与evaluation_scope仅同次复用，finally恢复上下文；输出深复制 | PF17—18：取消在子step后发生仍原异常退出；快照不变；重复调用互不污染；极大整数/有限数相减溢出拒绝，不误报消失 |
| 普通文字与固定规则身份 | forecast_text的make_display显式接同次prepared；forecast_spec为14个固定字段 | PF09、20：B局部失效不说整体消失；结构优先消失/回钝化；全部范围及单点保留；底部但DIF为正不误称顶部；旧Spec拒绝 |
| 纯计算和最小依赖 | 八个现存forecast文件及types共九个文件，仅标准库/本目录；无数据库、文件、网络或研究目录调用 | PF17阻断文件/网络入口后正常样本仍通过；静态依赖检查及根三份架构通过 |
| 清除正式旧求解路径，后续消费者不提前迁 | 删除forecast_joint/forecast_paths；entry/detector/math/text移除旧多步函数，无转发兼容 | 先核调用方；本步不执行P4/P5旧runner及旧预测专属节点；仅将两份混合测试文件的旧工具导入移到其专属节点，不修改其expected或增加skip |

识别`calculator.py/spec.py/snapshot_validation.py`及原`projection.py`与本轮开始版本无差异。本步新增ForecastPrecheck、ComparisonRanges、ForecastConditionDraft、ReferenceForecast、ForecastKernelResult，不改变既有识别字段。正式预测旧函数的消费者还包括第3步query和P4/P5工具；它们尚未迁移，不保留旧签名来维持中间版本运行，不能发布当前混合状态。

本次固定预测Spec实际生成hash为`dd3a41247c43414e89d80d671c5f91e3799f0e20cc03d923724ea8c94759c0b7`；检测Spec仍为§15登记的`1c02c0d865689ba390da058cd377cd5b0b8509a46ec9b089d09985d12e8d928a`。两者均来自自身完整规则序列化，不是源码保护；第3—4步必须同步模型及消费者，不能只换字符串适配旧结果。

### 16.2 实际测试与未执行范围

均使用现有`.venv/bin/python`，每组少于60秒，无安装、真实行情、旧算法重放或产品请求。

| 组 | 实际执行范围 | 结果 |
|---|---|---|
| 新预测 | test_xxm_key_point_forecast及test_xxm_p3_forecast_math；独立M/PF人工输入、Fraction及手写调度替身 | 154通过，1.05秒；替身仅验证调度，数学另由字面样本证明 |
| 识别及输入 | test_xxm_r4_rules、test_xxm_r4_restore、test_xxm_input_validation | 889通过，1.14秒 |
| 内部结果及观察 | test_xxm_r4_internal_results、test_xxm_snapshot_consumers、test_xxm_r4_observation；不选其中两个observe_rows工具节点 | 573通过，2个P4节点未执行，2.10秒 |
| 通用恢复 | test_xxm_snapshot_validation | 249通过，0.90秒 |
| 现核心七个节点 | test_xxm_calculator中当前首次/近远/1%/回转/锁死/恢复/固定身份节点 | 19通过，0.13秒 |
| 根架构 | subsystem_dependency_matrix、platform_legacy_guardrails、operations_legacy_guardrails | 16通过，13.25秒 |

本步154项加既有1730项业务回归，共1884项通过；另16项架构通过，不把未执行节点计入。没有运行研究测试全目录、旧预测/工具整文件、公开query/API、真实完整前缀/日历/缓存、Wealth或浏览器测试，也未认证完整400ms/4秒预算。

首轮核对纠正了一处人工测试预期：锁死后新绿段仍有更早已结束绿段可作近谷，不能写成无历史。按§3/§14修正独立字面预期，未修改识别实现。独立审计另发现极大整数转数值及有限DIF相减可能产生非有限值，已按§6.8补明确失败及负例，不改变正常规则。

### 16.3 人工样本的计算量和耗时

对M1、M2分别在day/m60/m90/m120调用纯内核；临时计数替身只记录调用，不改运算或结果。下列计时包含本步precheck和有限核验，不含完整前缀读取/校准、日历、模型、公开投影和编码。

| 样本 | 本次实际参照数/A次数 | 谓词/线性边界求解 | 原EMA advance/唯一step | 四周期实际耗时范围 |
|---|---|---|---|---|
| M1 | 1/0 | 13/26 | 25/25 | 21.139—22.617ms |
| M2 | 1/0 | 13/26 | 43/39 | 26.466—26.978ms |

两组各有5个适用outcome。按outcome生成的直接根及邻点，在跨组去重前分别66、117个候选点；最终同C只advance一次，显示整数也复用同次投影。部分点直接核B失效，无须完整step，因此M2的step次数少于advance。另有独立PF18把源选项替为2×2，证明同C一次advance、4个独立子实例及4次step；不把正常样本仅一组来源当作四组已验。

这些是本机人工样本观测，不是生产P95，也不证明完整400ms已通过；第3/5步须在原预算下补全读取、校准、日历、模型、编码、缓存复制与锁等待及最后检查。

### 16.4 独立审计及交接

按非本人编写部分交叉审计：数学实现/测试、状态核验/近远调度、Spec/文字/类型分别由其他实现者逐项核§6，再由主审核对源差异、正常/负向测试和未执行边界。结论通过，未发现需要新增业务口径或管理员拍板的阻断。

CodeGraph使用codegraph_explore和codegraph_impact核对原forecast调用及测试影响面，开发后codegraph sync/status已完成；继续以当前源码核query、API和Wealth消费者，不能把图索引代替真实代码。新模块未跨Biz边界；来源、API、前端及清退责任仍按§11不倒置。

本轮停止在§11.4第2步。下一步为第3步完整模型/query/API、唯一未来端点、完整缓存身份和一次编码；须继续沿§6.7—6.8及§11.4执行。识别规则和原EMA不得为接接口而改写，正常/debug不得重复计算，完整预算不得凭本节数学耗时提前宣布通过。

2026-10-30接续授权：管理员要求提交第2步改动并重新梳理后续计划。本次仅提交本节实现、测试及配套文档；不包含其他工作区改动，不推送或部署，不自动开始第3步。

## 17. 历史：有限跟踪修正的执行范围与开发停点（2026-10-31）

本轮按已批准的整体修复批次修改唯一识别核心、结构/Spec类型、内存恢复、内部模型/query、单根预测及对应测试，状态同步原产品/技术方案/本LLD；没有真实源读取、历史重跑、公开HTTP/TS变更、清退、提交或部署。已确认顶底镜像、完整原色段最终极值、下一同色段第一根即可失效、零中性、正常结束不报消失及消失不恢复。

设计及开工前审计后，管理员已批准并完成下列①—③的内部实现；④仍须后续提交固定源码及授权：①唯一核心/结构类型、followedStructures、恢复与完整内部模型/聚合/asOf；②旧结构下一根条件及同源预算、普通/debug设计；③RC74—96/PF21—28及原回归、前后规则对账；④修正源码提交确定后更新专项固定CURRENT及记录解析，再按专项授权一次重跑。以上结束并review前，不推进P3第3步、P4或P5，不提前改正式HTTP/前端运行行为。

MAIN_SPEC已实现v0.3-r4，FORECAST_SPEC已实现v0.5-r4；真实hash由完整Spec生成，见§17.4，不在代码中硬编码。原日线/分钟/预测目标章节同步新身份和条件，内部运行代码已用新身份，公开运行链后续迁移；不用只改字符串伪装已完成公开集成。既有§15/16及历史922根报告均不改当时结果，不作为本次新验收；当前专项固定c6a845fe3只复现旧核心，不能拿它证明本轮规则已生效。

检查范围包括core→snapshot→query/internal models→forecast math/record matching→HTTP投影/TS解码及既有测试。CodeGraph已覆盖validate_structure_record、ParsedXxmSnapshot和直接调用方，结合实际源码核当前FOLLOWING目标与旧LOCKED行为的差异。新规则不恢复r2永久历史列表或旧底部价格等待，普通/debug环境限制、波段研究工具、1000根、1%/近远/TODO和既有真实来源不变。产品400ms及日线/分钟原预算不放宽，专项仍20秒/1GiB/100MiB，两者不混用。

### 17.1 开发前文档审计及测试设计修正记录（2026-10-31）

核对范围为原产品、技术方案、本文和直接配套日线/分钟/预测目标合同；本地工作区历史专项§22交接草案一并复核，§21原成绩不改；这两份专项文档含另一批尚未提交的执行报告/预算变更，本次只提交六份识别方案与合同，专项另随对应代码提交。当时CodeGraph及calculator/query/forecast_detector、Wealth adapter/primitive确认：运行代码仍是旧终态、预测仍限制单普通事件，不能用文档改完宣称代码已支持。该文档阶段仅修文档，未运行识别、行情重放、API或测试代码。

| 发现的矛盾或遗漏 | 修正位置和必须验的用例 |
|---|---|
| 普通无候选就返回，会漏掉有效旧结构条件 | §5.4、§6.1/6.3/6.8统一两类前提；PF26给顶底合法已破普通参照但旧条件仍有解的字面样本，另有两类均无可能的正常退出反例 |
| 旧结构核验若跑完整step，会顺带查本次未求解的A | §6.1/6.4/6.12复用唯一核心的_advance_followed_structures，不复制算法；PF24以C273/C400证明近处有解时旧条件也能独立核验且A零调用 |
| 完整step的单事件/单记录要求、按时间去重会漏同根事实 | §2.3/§5.3/§6.4/§8.4按根前旧id分组，完整事实不删除；RC73/77/88/93/96覆盖后端关联及后续TS/悬停 |
| 内部返回未列旧条件、Draft与完整条件混用id、极值字段投影不清 | §5.3/§5.4/§6.1/§6.12固定内部与公开字段、先forecastId后条件id、XxmWaveDto日期映射；RC93、PF20/24/26/28逐层验收 |
| 只核时间先后会接受错误分隔段；零日最终极值覆盖不足 | §4.1绑定真实分隔Wave起点；RC78/79补零日极值，RC89补两阶段伪首次反色时间及正常恢复 |
| 旧完成状态、旧不撤销要求、分钟旧版本及步骤/章节引用不一致 | 原技术方案§10—14、本文§11—14及两份目标合同原位置替换；修改后RC01—96/PF01—28重新验收，旧成绩仅留§15—16 |

规则仍按已确认口径：原结构仅在紧接下一同色段内按原段最终收盘极值判断，第一根可触发，零不开始/结束范围，结束或消失即停止，顶底镜像；首次同根C/D、曾破记忆、B后A、1%及两项暂缓TODO均未变。本次范围内没有新增需要管理员决定的业务口径。

文档验证：本组89个Markdown文件链接均存在，主章节编号无重复，RC01—96及PF01—28条目齐全且唯一；PF24/26四个手写价点用独立分数算术核对DIF及柱色，非程序回归。仓库文档完整性和diff空白检查通过。上述检查只证明文档与手算设计，完整实现、产品预算及真实来源仍待按§17顺序开发和验收。


### 17.2 三处审计补齐及本次文档提交范围（2026-10-31）

管理员已批准补齐后提交，再独立审计；当时只改原产品/技术方案/本文及日线目标合同，日线合同仅提交§10，本文件外其他未提交工作保留。当时没有执行业务代码、测试代码、行情、预测及回测；该文档提交不等于识别修正已实现，不进入P3第3步。

- §4.1共用恢复/最终发布检查下一同色段整段价格极值，拒绝“此前已突破却仍FOLLOWING”；RC89新增普通根和零根突破后回撤的非法副本，同时有分隔段突破/同色等号/真实已清槽进度正常通过。
- §4.2.1固定窗口结构集合，先按through投影/全记录核对，再取本窗引用、变化或有效时间覆盖窗口的记录；无事件、正常结束当根、结束次根及空窗口均有RC93独立预期，不增加假事件或改变普通投影。
- color_flip形成后正常结束、恢复及历史查看以§14.16的完整顶底序列补入RC80/90/91/93；原RC01—96和PF01—28编号保持，不以新增子样本数冒充已执行测试。

这些是已确认业务规则的编码/测试细化，不改变1%、首次资格、近远顺序、有限跟踪或两个暂缓TODO。开发时必须执行§14.16的全部子样本，不能只运行父case原来的一条序列就声称已覆盖。


### 17.3 提交后三处补齐的独立复核（2026-10-31）

三处补齐文档提交0400e4ff6时，业务/测试代码未改。随后独立复核又明确两项上下游说明：§3.12只以前两步内部迁移及review作为第3步前置，公开/TS消费者分别在第3/4步迁移、发布前全部通过；§8.4将无事件旧结构按后端时间字段关联至debugDetail.structures，保留普通point状态，RC93补真实adapter/renderer展示子样本。另把普通状态回DULL与结构记录DISAPPEARED区分写清，避免混用枚举。这些修正不改变业务条件、公开字段集合或阶段范围，不增加接口/页面入口/算法模式。

本轮覆盖复核按普通NONE/DULL/STRUCTURE、同色/零/反色、旧跟踪未开始/已开始/已结束/已消失交叉检查，并核对应case中的不可达状态用恢复反例拒绝。RC01—96/PF01—28及§14.16子样本是已确认规则的设计覆盖，不是已执行成绩；根数和条目计数不能证明实现无误。既有源码事实、源/接口/性能及页面验收仍按各阶段另行执行，本轮不运行算法或回测。


### 17.4 本轮整体修复批次执行与独立审计（2026-10-31）

管理员已批准按既定步骤实施。本轮依次完成唯一核心与结构类型、内存副本校验、内部聚合/asOf及查询窗口、单根预测和必要回归；不迁移公开HTTP/TS/页面，不清退旧版本，不读真实行情或运行历史对比，不提交或部署。失败只丢弃本根工作副本，不返回半份结果、不落盘，取消和中断检查沿用同一预算。本轮实现、限定回归与独立代码审计已完成；实际成绩及未覆盖边界见下文。

| 已定要求 | 实现位置 | 验证依据 |
|---|---|---|
| 原段最终极值、下一同色段有限跟踪、同根多事件、终态不恢复 | calculator/types/spec | RC74—88、94—96及原RC01—73独立字面回归 |
| 最多顶底各一条跟踪、曾突破后回撤不得伪造有效状态 | snapshot_validation | RC89—90、§14.16恢复子样本及错误副本原子拒绝 |
| 内部记录聚合、按当时日期投影、无事件窗口仍可查看有效结构 | query_service及内部schema | RC91—93、§14.16窗口子样本 |
| 旧结构条件独立、只算下一根、不因核验旧结构调用远参照 | forecast/forecast_next/forecast_detector/types | PF21—28、原M1—M5和PF01—20 |
| 业务结果不受观察开关影响、无文件或网络副作用 | calculator及本地人工测试 | 开关同序列、故障注入、架构检查 |

400ms仍为完整预测请求预算，本轮只测预测内核，不能以此宣称后续公开接口性能验收通过。RC93的公开投影/真实renderer子样本及HTTP/TS验收保留在后续P3第3—4步，不计入本批完成项。


#### 实现与验收对账

| 实现内容 | 实际代码与测试证据 |
|---|---|
| 单一核心、最终原段事实和有限范围 | `calculator.py:_start_structure/_finish_structure/_advance_followed_structures/step/_validate_step`；`types.py`新记录及两个固定方向槽。RC74—88/94—96在`test_xxm_r4_following.py`逐根检查起点、原段最终值、终态、全部事件；同根旧CANCEL与新DULL/color_flip均保留。RC94在`test_xxm_r4_following_query.py`使用§14.15原九根字面数值，不冒充真实EMA重放。 |
| 保持原判断规则 | `test_xxm_r4_rules.py`原RC01—69字面序列仍逐根核对原值、当根首次、曾破、两根柱、零柱、B/A先后、救援、1%及转折优先；只按本次已批准状态扩展结构预期。`test_xxm_calculator.py`仅执行CURRENT_CORE_NODES七个完整函数名，不运行旧冻结重放节点。 |
| 有界恢复和原子拒绝 | `snapshot_validation.py:validate_structure_facts/validate_structure_record/validate_xxm_progress/parse_xxm_snapshot`；快照仅activeStructure和TOP/BOTTOM两份followedStructures。RC89包括假终态、NaN、未来/错分隔起点、远段冒充、额外槽、重复id、旧字段、曾突破后回撤（实柱/零柱）；合法等号、分隔段越价、已被历史池淘汰的原远参照均正常恢复。空进度/开头零柱的槽必须精确None，0/False/空字典/空列表拒绝。RC90每个切点连续/恢复/观察开关一致，RC95构造后故障不改self或旧输出。 |
| 完整内部模型、聚合/asOf/窗口 | `query_service.py:_merge_structure_updates/_project_structure/_response`及仅InternalXxm*模型；RC91—93在旧测试及`test_xxm_r4_following_query.py`核未来字段、最终极值不倒写、合法历史引用、无事件有效窗口、结束当根/次根和空窗、双方向/多事件、窗口外错误不被过滤、只取一次calculator_at及终态不可重开。没有改源读取/SQL、公开DTO或HTTP。 |
| 单根预测与相同计算依据 | `forecast.py:precheck_next_bar/forecast`及`forecast_next.py:solve_followed_structure`、`forecast_detector.py:evaluate_structure_follow_at_price`。旧结构核验只运行同一核心的有限跟踪方法，不运行完整普通step；旧范围与普通范围分开，不跨对象删精度范围。PF21—28位于`test_xxm_r4_following_forecast.py`，包含四周期字面EMA/原运算、真实H=0、普通静态退出仍返回旧条件、手写草稿状态合成、整次请求A资格/救援/求解零调用、同一候选价的advance复用、错误目标/证据冲突、旧step后及最终构造后的超时退出。原M1—M5/PF01—20继续通过。 |
| 说明、观察、身份和边界 | `forecast_text.py`仍四字符串，说明旧结构适用段、临界未决及正常停止，不说锁死后永不消失。`record_decisions=False`仍默认，旧检查写独立structureFollowChecks，不覆盖普通branch。Spec为v0.3-r4/v0.5-r4，仅规则身份变化；无新配置/依赖/开关/源码SHA保护。纯核心IO拒绝测试和架构检查通过。 |

实际Spec hash（由完整Spec生成，不用于源码保护）：

- MAIN_SPEC：`3576235a25d6e308cfa34e7df4d168c8303059c37e4c4c538cf6c2799bb878ce`。
- FORECAST_SPEC：`0f93850843d9be9dfb64baae5aef6e4477fa04ba5a8d35e2a8c67acc8e3d9467`。

#### 限定测试执行结果

各组均使用现有`.venv`，执行器单组60秒上限，无安装或来源读取。以下是参数展开项数，不是业务case数量，也不能替代真实数据/完整接口验收。

| 组 | 选择范围 | 结果 |
|---|---|---|
| 核心/恢复/输入/有限跟踪 | `test_xxm_r4_rules.py`、`test_xxm_r4_restore.py`、`test_xxm_input_validation.py`、`test_xxm_r4_following.py` | 1249通过，最后整组5.34秒 |
| 内部查询/消费/恢复 | `test_xxm_r4_internal_results.py`、`test_xxm_snapshot_consumers.py`、`test_xxm_snapshot_validation.py`、`test_xxm_r4_following_query.py` | 332通过，最后整组2.01秒 |
| 单根数学/文本/旧结构预测 | `test_xxm_key_point_forecast.py`、`test_xxm_p3_forecast_math.py`、`test_xxm_r4_following_forecast.py` | 189通过（最终构造后超时回归包含在内） |
| 正式核心观察 | `test_xxm_r4_observation.py -k 'not observe_rows'` | 513通过；2个旧研究入口明确不纳入本轮验收 |
| 原人工核心节点 | `test_xxm_calculator.py`的CURRENT_CORE_NODES七个完整`::函数名` | 19通过，约0.2秒 |
| 根要求三份架构测试 | `test_subsystem_dependency_matrix.py`、`test_platform_legacy_guardrails.py`、`test_operations_legacy_guardrails.py` | 16通过，12.66秒 |

五组定向测试合计2302项；架构16项另计。开发时试跑曾误选两个旧observe_rows节点和旧完整oracle的三个参数项，均在旧`bottom_history_acceptance.py`导入不存在的`inactive_result`时失败，未进入其来源读取或重放。核对开发前Git版本已无该函数；该runner在§10/11已列后续清退。本轮没有添加兼容函数、修改旧入口、skip失败或把它们算成通过；最终按既定人工节点范围验收。今后原核心必须用CURRENT_CORE_NODES完整函数名，不能用first_activation关键词误选旧oracle。

本机额外使用两方向跟踪并存的人工前缀运行20次纯计算、四字符串说明和临时JSON编码：P95为35.89ms、最大36.431ms，样本编码6274字节，两份旧结构条件均保留。此值只证明这一隔离样本，不含真实来源校准/查询、公开模型、真实HTTP编码及浏览器，不能宣布完整400ms产品预算通过；产品预算未放宽。

#### 独立审计及未覆盖项

开发后重新按§2—4、§6.12、§7和§14逐条查看真实代码、调用方与测试，不以测试数量代替规则判断。重点复核：原段最终值和形成值不混用、反色根不计旧段、第一根新同色可失效、零柱延续、正常结束不造事件、失效不重开、同根旧新事件均校验、原参照被池淘汰不误拦、过去窗口不泄漏未来事实、旧价格条件不调用A、只有真正末次构造后check通过才返回、失败不发布。审计发现并修复空槽假空值以及最终结果构造后未再次检查时限的遗漏，并补正反例。未发现本批未处理的规则歧义或阻碍。

已用CodeGraph的explore/node/impact核对XxmCalculator、ParsedXxmSnapshot、校验函数、query消费者、forecast匹配及其测试；开发后sync/status复核索引。没有新增跨子系统依赖；字段/生命周期检查在biz内部共用。HTTP投影、公开模型与TS调用方仍是后续迁移边界，不声称它们已支持新结构集合。

保留未执行：RC73/RC93公开投影、真实adapter/renderer和TS；PF28完整请求编码/普通debug一致性、真实来源及400ms全链预算；专项固定源码后历史重跑。日线/分钟源读取、250根校准、SQL、数据库/Lake、公开API/页面、r2/旧研究清退均未改；没有运行922根行情、比较报告或软件截图回放。工作停在本批交付，未提交、推送、部署或自动进入下一阶段。


提交交接：管理员本轮已明确批准提交这次整体修复。开发阶段“不自动提交”的停止条件至此解除，仅限本批26个文件；其他未提交工作保留。实际版本以本次Git提交为准，下一次专项须登记该真实提交后再适配记录解析和开展受控对比。本轮只提交并提出后续顺序供review，不读取行情、不运行历史对比、不推进公开接口/页面、清退或部署。

## 18. 三项截图修正的执行交接与文档独立审计（2026-10-31）

### 18.1 已确认要求、代码点和验收对应

本节依据专项回测方案§29及管理员确认，不新增业务规则。当前代码仍为识别v0.3/预测v0.5；目标v0.4/v0.6及字段/算法见活动§2—6。当前只完成文档与测试设计，没有运行下列开发或测试。

| 要求 | 开发位置 | 独立验收设计 |
|---|---|---|
| 首次反色起逐根比价，反色/零也可消失 | calculator单记录推进、step首次反色分支；structure字段与内部schema | RC55—62、75、82、97、102、105—106；顶底严格价格与原ref优先分别覆盖 |
| 单根段不终止，首个有效同色段结束正常停止 | nextSameColorCount、起点重置；snapshot/shared validation；query合并/asOf | RC98—103、109，原段从两候选池淘汰仍合法，不能靠增加池容量或历史遍历解决 |
| 同根旧价格消失与新同向activation只画钝化 | 内部完整事件保留；response_projection.event_display_flags及必填displayOnChart；TS markers/普通详情与debug事实分开 | RC77、104、107及实际04-14/2026-05-11；独立消失及不同方向不隐藏，下一根不补报 |
| 下一根预测同步真实范围 | precheck新字段、solve_followed_structure、evaluate_structure_follow_at_price及FORECAST_SPEC | PF21—34，start无/单根不限制H，有效段结束仍有H边界；原EMA、源选项、零及整数照常认证 |
| 近峰价格门槛保持 | 既有select/current_reference_qualifies，不改识别规则 | RC108及原近远用例；4170只过远价仍拒，4225.0207过近远可选远峰DIF |

### 18.2 内部推进顺序及停止条件

1. **核心及内部配套批次**：先冻结完整MAIN_SPEC与新结构字段，改唯一推进/首次反色当根及共享校验，再改内部schema/聚合/asOf和对应字面测试。先内部模型，不提前迁公开HTTP。失败原对象/候选entry不发布。完成限定审计后停止交付，不假称页面已改。
2. **单根预测配套批次**：只在新核心与恢复通过后改新计数路径、Draft和原核验、新FORECAST_SPEC及PF用例；普通近远调度/原数学不动。400ms不放宽，校验/取消/finally均计入。不读真实行情，不先接旧公开DTO。
3. **修补后专项对比**：在实际修补提交固定、工具按其真实身份和字段迁完后，另按专项方案/LLD受控执行922根。只复用原有来源方法及预算，不虚构未来提交/hash。完整事件与应显示标签分列，旧报告保留。未经本轮后续授权不自动重放。
4. **继续原P3第3—4步**：对比review通过后，迁完整公开模型、显示标志、query一次编码、API及直接消费者；再TS类型/decoder/adapter/普通详情与必要debug renderer。普通/debug同一标志，保留完整事件，不发布混配版本。P3整批验收后才进P4/P5。

本轮只设计，不包含上述任何一步的开发或执行授权。现有来源、鉴权、环境、1000根、三角画法、debug按需加载、预算、保留工具和清退边界保持。

### 18.3 后续测试文件必须怎样改

这里只规定后续代码修改，不在本轮修改测试源码。关键预期均来自§14字面值，禁止跑新/旧计算器生成expected或只换hash让旧fixture过关。

| 文件/测试组 | 后续明确改动 |
|---|---|
| scripts/research/index_market/tests/test_xxm_r4_rules.py | 本文件才是RC01—69的现行正式核心执行测试：同步RC55/56安全首反色价格、RC61分隔段撤销、RC62隔离DIF目的。现有expected_ledger循环自己推演旧跟踪规则，后续必须改为本LLD独立字面逐根事件/关键字段预期，不得再复制新推进算法生成expected；原正确数值/id计算断言保留 |
| test_xxm_r4_following.py | 改原CASES中RC75/78/79/82/89的输入/时点预期；补RC97—102/105—106/109。逐根断全部新字段、同根完整事件及不复开；原故障注入/四周期/所有切点恢复继续 |
| test_xxm_snapshot_validation.py、test_xxm_r4_records.py、test_xxm_r4_internal_results.py | 新字段和终态关系，首次反色当根、color_flip同根形成消失、单根跳过/原段淘汰、分隔段破价回撤、bool/NaN/坏恢复拒绝及正常反例。内部结果的TOP/BOTTOM共用前缀若目的是测试合法FOLLOWING，将首反色C104/96改为安全90/110；原突破价的目的独立保留于RC97，不把不再合法的FOLLOWING夹具硬放行 |
| test_xxm_r4_following_query.py | 更新RC78/79安全首反色价格和RC92修订样本；补真实_merge的起点清空/根数推进、calculator_at一次的RC103及窗口/asOf；不能只抹最新字段或用mock结果替代真实query/schema |
| test_xxm_r4_following_forecast.py、test_xxm_p3_forecast_math.py | PF21最小整数由302改104；PF22取消不必要H约束、PF23有效段边界保留；原exact_zero测试改为分隔零也可消失；PF13补当前对象首次反色价破分类与同根关联；补PF29—34及Draft计数、原预算/故障/不偷算A；M1—M5正确数学与全部源组合保护继续 |
| tests/web中现有wealth_market_index_xxm日线/分钟及预测API测试 | P3第3步按新公开模型解析bytes；事件显隐严格bool且普通/debug共同、源只读一次、公开不漏/吞事实；内部通过不能冒称HTTP通过 |
| wealth/src/features/index-detail/xxm/adapter.test.tsx、apiClient.test.ts、useIndexXxmLayer.test.tsx及xxmFixtures.test-support.ts | P3第4步迁新身份/字段；旧CANCEL false保留events及debug但无marker/普通说明，新DULL true；完整同根字面fixture不能预先删除消失，测试普通/debug同图、不同时段/方向不误隐藏、迟到与清理保持 |
| wealth/src/features/index-detail/xxm-forecast各合同/identity/expression测试及API夹具 | 同步新detector/forecast身份、新旧结构Draft count和有效范围；普通精确四字符串/无辅助信息的合同不扩展，原整数及原表达式反例保持 |
| 专项test_xxm_r4_history_records.py、test_xxm_r4_history_worker.py、test_xxm_r4_history_comparison.py | 另按专项LLD迁真实固定修补提交/完整新Spec、新字段及单根重置的逐根记录检查；旧基准不换预期，新增显隐比较作为独立派生结果，不把图上未画当计算事件缺失 |

旧P1字面材料xxm_product_v1_cases.py及其静态材料测试不是上述现行RC执行器，不得因文件名相似就整份重写或拿其旧等待/一次终结预期验新核心；仅当前仍有正式消费者且与本轮规则直接冲突的字面片段按真实引用调整，历史材料与清退边界仍依§10，不能替代现行规则测试的迁移。

所有实施测试按现有环境有界分组，单组超过60秒先停查原因，无安装/无限等待。源码依赖检查及根三份架构测试保留；正式HTTP/真实来源/页面依原阶段单独验收，本轮不以文档检查代替。

### 18.4 独立文档审计结论与证据范围

按专项§29三条逐项反查产品§4.1、技术方案§4.4、本文§2—6/§14及上表。审计必须另核以下互斥边界：原段内不单凭价格撤销；首次反色先原ref破，未破才当根价格检查；单根结束仍比价而有效段结束根不比；完整计算两项与显示一项分开；正常新钝化不放宽；近峰价格已正确不另改。

已将旧“分隔段不检查”“起点永不重置”“任何下一同色段结束即停”“PF21必须翻红/302”等活动指导替换，RC55/56/61/62及RC75/78/79/82的相关输入/预期同步修改。历史§15—17原成绩保留且明确历史，不当成新预期。字段、状态、Spec及前端显隐合同统一，配套接口目标文书和专项待改清单同步。

本次独立复核还补正了三处容易误导编码的配套说明：内部完整step必须接受color_flip形成后同根价格消失的两事件及一份最终记录；测试总表/方法表必须覆盖RC97—110，不能只停留在旧RC96；普通悬停只展示displayEvents，模型的完整events与debug事实仍全部保留。已有相关字面正反例及后续修改文件已同步，不新增业务判断。

本轮文档检查结果：check_docs_integrity三项通过；八份涉及文档的本地文件链接、表格列数及RC01—110/PF01—34逐条设计入口检查通过；限定路径git diff --check通过。API/预测文档在本轮开始前已有的其他未提交变更保留，不将其计为本轮实现，也不为本次任务重写范围外合同。已使用CodeGraph explore核核心/恢复/预测/聚合入口及其调用影响，并以当前内部schema和前端消费者源码补查返回字段、事件顺序和显示路径，未以旧文档代替代码事实。

本轮只做文档校验、引用/差异及上述语义对账；未改业务或测试代码，未执行自动业务测试、真实行情、HTTP、页面、400ms或922根对比。编码完成和原软件全部数值/参照复现均未得到本轮证明。后续发现设计外行为或预算不满足时，按既有规则停下解释，不临时扩大范围。
