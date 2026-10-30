# 财势乾坤顶底识别低层设计 v1

更新：2026-10-30。状态：P3第1步已验收，证据见§15；本轮只完善第2步单根预测LLD，细节见§6，预测代码/测试及后续API/页面未开发或验收。

依据：[产品文档](../../../../docs/product/wealth-top-bottom-recognition-product-v1.md)、[技术方案](index-detail-top-bottom-recognition-technical-design-v1.md)。本文件只规定当前目标、代码迁移位置、开发顺序和验收，不包含已废弃的开发流程。实施必须使用本文规则和独立用例，不得从旧实验或旧输出推导当前预期。

## 0. 本轮产物、后续实施范围和硬要求

本轮只按已落地第1步完善第2步单根预测编码设计，修改§6及直接配套说明，不修改代码、测试代码、运行Spec、API或页面，不运行预测、真实行情、性能或浏览器验收。后续开发在当前dev-interface工作区按§11推进，不创建分支/worktree、不安装、不提交或部署，保留清单外修改。

目标范围是唯一r4识别、下一根预测、本地普通/debug与生产禁用，最后按P5清退旧执行代码。输入/进度/结果只在内存，不增加数据库或Lake写入、结果文件、恢复文件、后台任务、用户算法开关和浏览器持久缓存。

### 0.1 逐项对账入口

| 编号 | 方案硬要求 | 本文编码要求 | 验收归属 |
|---|---|---|---|
| R01 | 唯一正式r4；原r2最终清退 | §2—3唯一`XxmCalculator`，§10逐文件处理 | 核心人工/删后引用/迁移对账 |
| R02 | 本地四周期上证；生产日线也禁用 | §1路由和前端同时限制，§8环境交接 | 本地无Lake日线成功、生产直接API和页面反例 |
| R03 | 不新增env或用户开关 | §1、§2配置登记及完整Spec | 缺配置/未知环境关闭，正常显式dev/local可用 |
| R04 | 真实完成根和原指标，不补算 | §2输入、§4来源/历史前段 | 非法输入拒绝、原值和连续性 |
| R05 | 真实反色，零中性且不计根 | §3.2、§3.4、§3.7及§14 | 红零红/红零绿/全零/零日首次；零不锁死 |
| R06 | 历史极值独立记录，首次使用当根C/D，记住本轮曾击穿 | §3.2—3.4及§14 | 禁止借旧价格；击穿后不回用；仅相等不算击穿 |
| R07 | B优先、A备选，最多两个 | §3首次选择及固定候选集合 | B价未过/等号/第三个更强都不能绕过 |
| R08 | 已钝化同根B→A、取消前处理 | §3救援次序、§6预测路径 | 当根连续/晚一根失败/无回切或第三个 |
| R09 | 1%相邻实际DIF及前值0保护 | §3转折/回转/真实翻色优先 | 恰1%/不足/前根零柱/首次只DULL |
| R10 | 未锁死按1%考核，锁死后不可撤销；取消价格等待 | §3.6—3.8、§14 | 顶底统一回钝化、锁死不撤销、旧等待不得重入；恢复/asOf不改事实 |
| R11 | 预测整体迁r4，不能只改显示 | §5.4/§6单步、先前提后有限边界、近处有解停止 | PF01—20、M1—M5，旧多步/中点/全float路径清退 |
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

正式`XxmCalculator`已在原位置落实§2—4的新规则，MAIN_SPEC为xxm-direction-v0.2-r4。首次当根C/D、统一结构记录、直接回钝化和首次真实反色锁死均已实现；本步限定验收见§15，不重做父类迁移。

`SeriesEntry`、snapshot恢复、历史calculator_at和forecast clone都消费同一产品类；必须同步新结构记录、关联、身份和缓存。现预测Spec仍xxm-key-point-forecast-v0.3-r2，公开预测模型和Wealth身份/字段尚未迁目标；按§11整批推进，不能发布中间混合版本。

已用CodeGraph codegraph_explore定位计算器/查询/复制/共享加载及消费者，并读取当前实现补查。Biz只依赖自身及允许的Foundation；App负责装配；Wealth只消费HTTP；研究工具可以调用正式类，反向导入禁止，QTF不参与。实施日仍须核对当前引用与工作区状态。

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

`calculator.py:step`现按§3执行，`types.py:XxmStep`、`snapshot_validation.py`、`SeriesEntry/_response`和新增`InternalXxm*`模型已经同步统一结构记录。旧等待分支和跨色价格撤销已从识别核心及内部聚合移除；公开schema/API/预测/前端仍待§11后续步骤，不将本步当可发布产品。

继续使用原位置唯一`XxmCalculator`、`XxmBar`、`Wave`，不导入研究目录或独立日线价格候选。实际MACD仍用源值，原始float及1%计算顺序不改。`MAIN_SPEC.algorithm_version`改为`xxm-direction-v0.2-r4`；删除旧等待和历史撤销政策字段，增加明确登记的首次当根价/DIF、参照曾突破及结构锁死政策字段。hash仅由完整新Spec生成，不硬写摘要、不保留旧身份兼容。1%、2个候选、当前段2根、历史单根及首次TOP正DIF限制保持。

只在`src/biz/services/wealth/market/index_detail_xxm/`内维护唯一识别器。`types.py`负责输入、色段、参照、结构及step输出；`snapshot_validation.py`负责先校验再恢复；`calculator.py`执行§3。`query_service.py`聚合完整事实，`schemas/wealth/market/index_detail_xxm.py`校验内部与公开模型，前端只消费后端事实。不引入第二个算法、兼容父类或独立日线价格候选。

### 2.2 MAIN_SPEC目标字段（完整集合）

| 字段 | 固定值 |
|---|---|
| algorithm_version | `xxm-direction-v0.2-r4` |
| dif_turn_pct / max_refs / min_bars | `1.0 / 2 / 2` |
| reference_policy | `nearest_then_farther_two` |
| active_reference_policy | `same_bar_near_to_far_on_dull_break` |
| zero_policy / allow_zero_activation | `neutral_real_opposite / True` |
| activation_policy | `current_close_and_current_dif` |
| reference_break_policy | `strict_break_within_current_segment` |
| structure_return_policy | `adjacent_one_percent_to_dull` |
| structure_lock_policy | `first_valid_opposite_color` |
| historical_min_bars / top_activation_requires_positive_dif | `1 / True`（两个已暂缓TODO保持现状） |
| macd_parameters / histogram_multiplier | `(12,26,9) / 2` |
| color_flip / flip_requires_turn | `True / False` |

删除`allow_zero_reactivation/historical_price_only/fixed_expiry/bottom_history_policy/same_segment_bottom_policy`等旧等待/撤销或无作用字段，不留旧值别名。`__post_init__`逐字段精确检查类型及默认值，bool不能冒充int。`spec_hash`保持asdict、sort_keys及现固定分隔符的规范序列化后SHA256；这是规则身份，不读取源码或核源码SHA。

新预测Spec完整集合见§6；版本固定`xxm-key-point-forecast-v0.4-r4`。两项hash只在对应完整Spec、模型和消费者同次迁移时真实生成；文档不预填假hash。旧r2、旧r4-v2/正式v0.1-r4和混配快照/缓存/响应均拒绝，按同源重算；不设运行时切换。

### 2.3 统一结构记录与事件

这里的代码字段是本次编码设计的确定选择，不是新增普通页面标签。顶底使用同一种`XxmStructureRecord`，替代现`pending`、`pending_bottom_history`及它们的跨色历史退出方法。字段固定：

| 字段 | 类型与准确含义 |
|---|---|
| id | 非空string；`_id("structure", structureEventId)`；一条形成事件唯一对应一条结构记录 |
| direction | TOP或BOTTOM |
| structureEventId | 当次STRUCTURE事件id；不能指向先前已经回转/失效的结构 |
| formedAt | 该STRUCTURE实际发生时间 |
| formationRoute | dif_turn或color_flip |
| originSegmentStart | 形成这次结构的红/绿逻辑段起始时间；color_flip形成时仍指旧段，不指反色根的新段 |
| originalReference | 新Reference固定startTime/endTime/price/dif/priceAt/difAt；priceAt/difAt直接来自所选Wave的price_at/dif_at，不由前端查找。结构形成时深复制并固定，不随后来选择/池淘汰改写 |
| priceExtreme / priceExtremeAt | 结构形成时原逻辑段的方向性最高/最低收盘及其发生时间；只作事实说明，不作今后价格撤销条件。反色确认时使用反色前已结束的旧段，不能纳入反色根价格 |
| status | ASSESSING（尚在考核）、LOCKED（已经锁死）、DISAPPEARED（本次结构已经失效） |
| lockedAt | LOCKED时为第一次有效反色根时间，其余为None |
| disappearedAt | DISAPPEARED时为回转或原参照突破根时间，其余为None |
| disappearanceReason | DISAPPEARED时只允许dif_return或reference_dif_break；其余None |

形成本根创建一次记录；既有结构保持时不反复输出记录；回转/失效输出这个id的最终记录；锁死输出这个id的最终记录。`color_flip`确认直接输出LOCKED，`formedAt==lockedAt`。同段再次形成结构有新的形成时间/事件/id，不能把之前DISAPPEARED改回ASSESSING。记录最终LOCKED或DISAPPEARED后，计算器不再保留它为可修改活动对象。

计算器只保留`active_structure: XxmStructureRecord | None`，非None时必须ASSESSING且state==STRUCTURE；stateNONE或DULL时为None。已锁死/失效的完整记录归`SeriesEntry.structure_records: dict[id, record]`，不放进每个计算进度副本，避免预测clone重复复制全历史。`XxmStep`改为`point/events/structures/decision`，`structures`只含本根创建或最终改变的记录深副本；删除旧histories/bottom_histories/rearm_records三组输出。SeriesEntry在接入时按id更新记录，只允许不存在→ASSESSING/LOCKED、ASSESSING→LOCKED/DISAPPEARED；原终态不允许被另一条step覆盖，任何内容不同均失败。

普通事件保留三类DULL/STRUCTURE/CANCEL。DULL的route只activation/dif_return；STRUCTURE只dif_turn/color_flip；CANCEL只dif_break/dif_break_on_flip。删除RESEARCH_HISTORICAL_WITHDRAWAL、STRUCTURE_DISAPPEARED及historical_price_break/reactivation。回转本根的普通事件仍是DULL/dif_return，关联该次失效结构记录；直接从结构失效的CANCEL同样关联该记录。锁死已有结构不另造普通事件；color_flip首次确认则有一条STRUCTURE并关联同根锁死记录。

内部point为原数值/时间/普通状态/方向，加activeReference与activeStructureId（其余旧pendingTop/Bottom/Rearm字段删除）。内部event为原id/time/direction/type/route/fromState/eventReference，加relatedStructureId（旧三种related字段删除）。activation及从DULL取消时relatedStructureId=None；形成、从STRUCTURE回转/失效时是对应记录id。结构记录可早于页面窗口，其形成事件不在本窗口不算悬挂；记录自身id、structureEventId、方向和formedAt可按原_id函数重新核验。

所有活动参照、事件参照及结构originalReference统一采用六字段Reference。`Wave.reference()`一次新增priceAt/difAt；对应Python/TS解析均严格要求两日期位于startTime..endTime之间，原值和各自日期一起深复制。不按当前段日期替代参照日期，不把确认时间当极值发生时间。

事件id沿原`_id(time,event_type,sign,reference.start)`结构，新Spec纳入_id；结构id按上述统一公式。debug、窗口起点、asOf筛选不进入id。首次DULL事件保存原B，即使后来活动参照改A也不能改旧事件。STRUCTURE记录保存实际形成时的活动参照。

上文`XxmStep`的Python字段固定为`point/events/structures/decision`；`SeriesEntry`存储字段固定为`structure_records`，不是另一个业务集合。HTTP debug集合为`structures`，事件关联字段统一`relatedStructureId`；不得另外引入`structureId`同义别名。

## 3. r4识别规则

本节是唯一识别规则。当前实现必须按本节修正，测试预期只来自已确认规则和§14独立人工样本。规则测试必须独立手算预期，不能拿旧算法输出当答案。

### 3.1 阶段含义和本周期边界

| 管理员定义的阶段 | 进入前提 | 应判断的结果 |
|---|---|---|
| 钝化评估期 | 尚未钝化，已知历史同色峰谷，下一根存在可行钝化价格范围 | 当根是否首次钝化；没有形成就继续按实际条件评估，不能把预测有解当成实际钝化 |
| 结构评估期 | 已有有效钝化 | 保持钝化、形成结构、钝化消失；保持和形成结构不再重复要求当根突破历史价格 |
| 结构形成考核期 | 结构已形成，但尚未首次真实反色 | 保持结构、按1%回转退回钝化、原参照DIF被突破而直接消失；退回后可再次形成结构 |
| 结构锁死点 | 首次真实反色的完成K线到达，原结构仍有效，或本根按真实反色首次确认结构 | 同根锁死这个有效结构，开始新的色段；以后不能追溯撤销它 |

这些是业务阶段，不要求全部变成普通页面的新标签或HTTP枚举。必须能核对一个结构的形成时间、是否在考核、锁死时间及所属色段/原参照。锁死点以该次钝化所属色段为基准：底部绿转红，顶部红转绿；零柱不是反色。已经消失的旧结构不能因后来反色复活。结构先消失再重新形成时，锁死的是当时有效的新结构。

### 3.2 数值、色段和历史参照

只使用完成K线的源收盘价C、源DIF值D和源MACD柱H；不重算实际指标、不改用high/low，不取两位有效数字，不增加epsilon或额外百分比筛峰。日线和60/90/120分钟采用同一识别规则，仅时间格式和实际来源不同。

- H>0红柱、H<0绿柱、H=0中性。真实反色才结束色段；红→零→红仍同段；红→零→绿到绿根才结束旧红段。零不增加有色柱根数，但它的C和D属于尚未结束的原段；开头全零不借后面的颜色补建历史。
- 红段保存最高收盘及最高DIF，绿段保存最低收盘及最低DIF，价格和DIF日期各自独立。Wave.price/dif分别表示这个方向的极值，不是每段额外保存另一方向的全部极值；独立日线基础工具仍保留自己的完整记录。相等保留原极值发生日期。这里的累计极值用于结束后作为历史参照，以及检查本轮是否曾突破某参照DIF，不能用累计价格代替当根首次钝化价格。
- 首次真实反色根属于新段，不能计入旧段根数、旧段价格或DIF极值。旧段end为前一根（可为零）。同一根可以对旧结构完成锁死，又作为新段第1根。
- 每方向只保留最近两个已结束同色段：最近B、较远A，按时间确定，不按DIF强弱排序；不查第三个。历史单根段仍保留并可作参照，不新增历史至少两根过滤。
- 反弹红段正在运行时，之前结束的绿段是近谷，其左侧旧红段是近峰；反弹红段结束后，它成为新的近峰。锁死结构的历史事实与色段极值分开保留，新一轮不继续沿旧结构作失效跟踪。

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

达到原float运算得到的1%门槛包含等于，低于门槛保持。形成结构当天以及结构回转当天，都不重新要求C超过历史价格：它们基于已有钝化关系。顶部结构DIF向上回转、底部结构DIF向下回转达到1%，直接退回钝化；无论当根收盘是否还在首次价格门槛之外。价格单独突破本次结构所在段的高/低点，不能另外撤销未锁死结构。

处理顺序固定：先原参照DIF失效，再1%转折/回转。已有DULL的B→A检查在取消前；已有STRUCTURE不切远。一旦当根产生CANCEL，不能清空ref后落入首次激活分支，在同根补一条新DULL。保持原始事件次序，不事后删事件来凑终态。

### 3.7 首次反色和结构锁死

真实反色根先判断旧段原参照是否有效；严格突破则CANCEL且不锁死。未突破时：

- 旧段已有STRUCTURE：本根锁死已有结构，不重复产生第二条STRUCTURE。
- 旧段已有DULL：按现行独立翻色规则产生STRUCTURE/color_flip，并在同一根锁死该结构，不再等第二次反色或额外1%。
- 旧段NONE或结构先前已消失且本根没有新确认：不恢复旧结构、不凭翻色生成锁死。

然后结束旧色段、建立新色段。锁死时间和形成时间分别保留；根末新段状态可能为NONE，不能据此否认本根旧结构确认/锁死。锁死之后，后续价格再创新低/高、DIF突破旧参照、出现新同方向信号或更多次翻色，都不能撤销已锁死结构、移动其形成点或锁死点。新信号属于新循环。

结构在考核期退回DULL后，先前那次结构未锁死且已经结束；随后再次转折形成新的STRUCTURE，应有自己的事件时间和编号，不能复活旧结构记录。最终锁死的是当时仍有效的那次结构。已返回的历史事件是当时事实，后来的新状态不允许原地改写先前返回对象。

### 3.8 必须删除的现有实现及同步范围

底部STRUCTURE回转不再调用_qualifies_bottom_close/_start_rearm；正常计算不再创建WAITING、REACTIVATED、INVALIDATED或SEGMENT_ENDED等待记录，不存在“收盘重新低于旧谷才重新激活”的业务分支。

正式代码中_start_rearm目前只有底部回转这一处生产入口。实现时须按引用清单成套清理等待专属类型、字段、snapshot解析、查询投影、预测条件、TS解码/说明及旧测试，不能只隐藏页面。移除historical_price_break对未锁死/已锁死结构的价格撤销途径，禁止保留另一条绕过锁死的撤销路径；不删除通用恢复安全检查、完整原始数字校验、历史设计、原图和旧运行记录。

目标字段及身份已在§2、§4—7确定，后续按§11同批迁移正式类型、计算进度、查询/DTO/前端消费者、Spec/hash和缓存；禁止编码时另起同义字段。旧等待快照/旧规则缓存不能按新规则恢复，也不能加新旧双策略兼容。P3第1步已落实识别及内部结果；公开合同和消费者尚未迁完，不表示产品可上线。

### 3.9 保留规则、TODO与测试入口

保留：真实完成根；源收盘而非high/low；原始DIF而非柱高；相邻1%及前值0保护；零中性；最近两个历史同色段；首次同根只DULL；原参照和事件ID/时间关联；因果前缀/asOf/独立内存恢复；不改源SQL、数据库、Lake或鉴权。

TODO仅两项，等本需求完成后研究：①历史参照是否也必须至少两根；②首次TOP是否必须本根DIF>0。当前继续允许历史单根、保留TOP正DIF限制；不因这两个疑问扩大本轮规则变更。

§14逐条设计识别规则测试。正式实现前必须完成本节到§14的覆盖检查；任何算法输出或原截图均不能自动生成expected。人工规则样本与软件观察分开；本步实际执行结果及公开验收边界见§15。

### 3.10 编码方法、不等式及互斥执行顺序

| 方法 | 输入、结果与固定语义 |
|---|---|
| `_reference_was_broken(wave, ref)` | `wave.sign*(wave.dif-ref.dif)>0`。wave.dif已经包含本根及先前同段零柱的方向极值。相等返回False；分别对B、A计算，不能共享“任一破则全破”标志 |
| `_current_reference_qualifies(bar, wave, ref, nearest)` | 已知同色段、count>=2、TOP当根D>0、当根C同时严格突破nearest.price与ref.price、当根D严格弱于ref.dif、未曾破ref。只用bar.close/bar.dif作本根资格；wave.price不能代替bar.close |
| `_select_eligible_reference(bar, wave, history)` | 取逆时间最多B、A；先过当前B价格门槛；B本根完整合格即返回，未选才查A。无B/未过B价/两者不合格返回None；无DIF强弱排序 |
| `_rescue_dull_reference(bar, wave, reference, history)` | 仅旧stateDULL、同段/零、活动ref按完整Wave字段/时间属于B（不是对象地址相同）且B本根严格破时调用。只用_current_reference_qualifies检查A；合格返回深复制A，否则None。不能返回B、第三个或在STRUCTURE/真实反色中调用 |
| `_point(bar, work)` | 显式读取work的根末state/wave/reference/active_structure生成point；不得读取尚未发布的self旧状态，不修改work |
| `_event(bar, event_type, route, sign, event_ref, from_state, related_structure_id)` | 方向、参照和fromState均由实际分支显式传入；返回深复制事件，除固定身份_id外不得从self推断新旧状态 |
| `_start_structure(bar, origin_wave, ref, route)` | 构造一条STRUCTURE事件及上述记录；形成时旧active_structure必须None；dif_turn为ASSESSING，color_flip为LOCKED |
| `_finish_structure(record, bar, status, reason)` | 仅接收ASSESSING，返回新记录，LOCKED填lockedAt；DISAPPEARED填disappearedAt/reason。原输入和以前返回对象不变 |

首次选择与救援可复用同一资格函数，但状态许可由调用分支控制。不能让通用helper自己从STRUCTURE救援，不能在CANCEL后再调用首次选择。

**必须先验证输入，再在独立工作副本上执行本根，最后一次发布。**根前事实old_wave/old_reference/old_structure只能读取；工作wave/history/reference/active_structure必须与根前对象及self隔离。所有业务helper只返回新值，不得提前写self业务进度或修改传入记录。work复用ParsedXxmSnapshot的内部进度类型，由当前业务字段deepcopy构造；不得每根重复snapshot→restore做序列化/解析，身份仍由实例固定。不得照搬现代码`old_wave=self.wave`后原地更新同一对象的做法。

工作副本只含wave、最多4个历史段、reference、active_structure及本根事件/更新，不复制SeriesEntry全集。本根任一步骤（包括事件或结构已构造后的校验）失败，self、根前事实、来件、此前输出及已发布缓存必须完全不变；不得推进previous/processed或返回部分成功。观察context在finally清理，不能把错误吞成NONE。

```text
raw = sign(bar.hist)
old_wave / old_state / old_reference / old_structure = 只读根前事实
work = 独立工作进度；以下所有更新只写work，不写self

if old_wave is None and raw == 0:
    work保持NONE、无历史/参照/结构；仅在work准备previous/processed，仍进入共同构造/校验/发布步骤
elif old_wave is None:
    建立第一个非零段，count=1，C/D极值取本根；不首次钝化
elif raw == -old_wave.sign:                 # 真实反色
    old_sign = old_wave.sign
    if old_reference is not None and old_sign*(bar.dif-old_reference.dif) > 0:
        CANCEL/dif_break_on_flip
        若old_state==STRUCTURE，终结old_structure为DISAPPEARED/reference_dif_break
    elif old_state == STRUCTURE:
        终结old_structure为LOCKED；不另造STRUCTURE事件
    elif old_state == DULL:
        用old_wave/old_reference创建STRUCTURE/color_flip并同根LOCKED
    else:
        无旧结构确认、无锁死、不得复活旧记录
    将旧段深复制入旧方向历史池，仅保留最近2段
    建立新段：start=end=本根，count=1，C/D取本根
    新普通状态NONE、reference=None、active_structure=None
    不在新段第1根继续首次激活；反色根不进旧段极值
else:                                     # 同色或零
    s = old_wave.sign
    更新当前段end、C/D极值（相等不移动日期），仅raw!=0才count+1
    if old_state == DULL:
        if 活动参照本轮严格被突破:
            若ref为B，按本根完整资格尝试A
            A合格：替换活动ref，保持DULL，无普通事件
            否则：CANCEL/dif_break，清ref；不在本根再首次激活
        elif previous.dif != 0 且反向delta达到原1%门槛:
            STRUCTURE/dif_turn，创建ASSESSING记录
        else:
            保持DULL；不重新要求当前价格突破
    elif old_state == STRUCTURE:
        if 原参照严格被突破:
            CANCEL/dif_break；终结结构为DISAPPEARED/reference_dif_break；清ref/active_structure
        elif previous.dif != 0 且同向delta达到原1%门槛:
            DULL/dif_return；终结结构为DISAPPEARED/dif_return
            保留活动ref，active_structure=None；不检查当根价格、不等待
        else:
            保持STRUCTURE/active_structure
    else:
        只按首次资格选B后A
        选中：DULL/activation；本根不再追加结构
        未选中：NONE

所有分支禁止早返回绕过共同发布。
在work中设置previous=bar、processed+1；先构造并深复制完整XxmStep（含可选decision），完成全部本根校验；全部成功后一次替换self业务进度，再返回已准备好的XxmStep。发布以后不得再做可能失败的构造、复制或校验
```

`P=previous.dif; delta=s*(bar.dif-P); gate=abs(P)*self.spec.dif_turn_pct/100`，顺序保持当前代码；DULL形成须`P!=0 and delta<0 and -delta>=gate`，STRUCTURE回转须`P!=0 and delta>0 and delta>=gate`。不累计、不跳过零柱、不与ref作1%比较。结构形成/回转不设价格门槛。真实反色分支先处理，百分比分支不能在同根再运行。真实反色中旧事件的direction/id和结构originSegmentStart均取old_wave，不能用新wave方向生成旧事件；根末point才取新段。不同方向的真实反色根至多1个普通事件，新方向第1根不首次钝化。B→A当天若成功，保持DULL，不再在本根追加其他普通事件。

`wave.dif`既保留历史峰谷又提供曾击穿证明，不另设会忘记清零或混淆B/A的缓存布尔。反色时只有完成旧段后新wave重新累积；原段击穿不会永久封禁新段中的新参照。开头零不归未来色段。A自身曾破但B有效时，B照常可用。

### 3.11 分支完整性

状态仅NONE/DULL/STRUCTURE；柱相对原逻辑段仅同色/零/真实反色；活动参照仅无/B/A；DIF资格分别为严格突破/等于/未突破；相邻转折分别为前值0/方向不符/不足1%/达到1%。按§3.10先排输入和开头零，再区分真实反色与同色/零，再按旧状态互斥，最后才允许首次选择。任何合法组合必有一个分支；不适用组合通过§4状态关系拒绝，不能落入默认成功。

逐分支及正反例映射见§14.12；每个分支不仅断言最终标签，还须核活动参照、源数值、结构记录、计数及关联。真实反色锁死和同根B→A均先于新段首次选择；CANCEL后不能在同根重入首次。锁死不是普通状态保持STRUCTURE，不得用新段NONE撤销旧结构。

### 3.12 识别核心开发的强制检查

以下任一项不满足即不得验收，不能用标签总数相同或最终状态相同替代：

1. **首次必须同根C/D同时合格；保持/形成/回转不得重复首次价格门槛。**例如旧谷100/−20，已钝化后收101仍可保持或形成结构；不能重新等待收盘跌回100。
2. **逐个参照记住本段曾严格突破。**B已破不能恢复；A已破不能连带使B失效；仅相等不能当严格突破。检查必须从新段第1根开始，不能等满两根或首次钝化后才记忆。
3. **已有DULL的B突破必须取消前当根查A。**A本根完整合格就保持原钝化、不新增消失/首次事件；不合格就当根取消。禁止延迟一天补查。已有STRUCTURE及真实反色不得套用该救援。
4. **一根只走一个普通事件分支。**首次不追加结构；CANCEL当根不重入首次；下一根仍须正常判断合法A，不能把“当根禁止”写成永久禁止。
5. **1%必须使用上一根实际DIF及原float语句顺序。**`P=previous.dif; delta=s*(D-P); gate=abs(P)*1.0/100`。禁止改成`abs(P)*0.01`、累计多根、跳过零柱、取两位或用`P±gate`代替实际比较；P=0只禁这条百分比路径。
6. **反色处理旧关系，根末point处理新段。**事件方向/id/原色段必须取old_wave；先核原参照，再锁死或确认并锁死；反色根不能进入旧段极值。新段NONE不能撤销已锁死结构。
7. **锁死和消失均为该结构记录的不可逆终态。**同来源正常追加不得改其时间、原参照或重开记录；新结构必须新id。源修订则创建新entry从空重建，禁止修改旧entry或误拦重建。
8. **按各自发布步骤保证失败不污染。**step/restore失败时，该计算器self、来件、根前事实及此前输出必须原样；严禁提前改self再回滚。query聚合或完整校验失败时，必须丢弃整个本次候选entry，已发布的旧entry/旧calculator/缓存及已返回对象必须原样；不要求回滚将被丢弃的候选calculator。任何一层都不得吞异常返回NONE/EMPTY或半份结果。

对应逐根正反例见§14.12—14.13；恢复/源修订和构造后失败必须覆盖真实执行位置，不能用mock提前返回绕过。

## 4. 计算进度、结构结果、历史查询与缓存

### 4.1 快照与先校验后替换

计算器快照字段固定：`specHash/tsCode/period/sourceIdentity/processed/wave/history/state/reference/previous/activeStructure`。删除pending/pendingBottomHistory/pendingRearm；结构结果全集在SeriesEntry结果中，不增加磁盘文件，也不新增计算器历史全集副本。ParsedXxmSnapshot对应同样字段。当前hash错误、额外旧字段、漏字段均拒绝，不补None迁就旧格式。

顺序：独立解析所有字段→验证数字/时间/关系/编号→构造全新进度→一次替换self；失败来件、self、此前输出全不变。record_decisions不入snapshot，成功恢复清临时context但保持本实例开关。

固定检查：

1. 身份精确等于当前新Spec/对象/周期/来源；processed严格非负int，拒bool；所有数值有限、价格正；时点按周期校验且不晚于previous。
2. processed=0必须previous/wave/reference/activeStructure均None，stateNONE，两个历史池空。processed>0必须有previous。
3. wave=None只允许开头全零：stateNONE、ref/activeStructure为空、历史空、previous.hist==0。不能用未来颜色补wave。
4. wave非空sign仅±1，count严格1..processed，start<=end==previous.time，price_at/dif_at在段内；previous柱色只能0或wave.sign。
5. snapshot的history严格两个字符串键"1"/"-1"，解析后内部dict才用整数±1；每池最多2条，方向正确、时间唯一升序，历史end<wave.start；历史1根合法。历史极值发生日期各自合法。活动ref与同向历史某一项完整Wave值一致，不能因只比较价格/DIF相同就混淆两个日期不同的段。
6. stateNONE必须ref/activeStructure均None。DULL或STRUCTURE必须count>=2、ref存在，当前wave方向极值未严格破ref；累计价格至少曾严格突破所选ref和近B门槛。不能错误要求当前previous.close仍突破，或要求wave.dif严格背离（历史相等合法）。
7. DULL必须activeStructureNone；STRUCTURE必须activeStructure为ASSESSING、方向等于wave方向、originSegmentStart==wave.start、originalReference==ref.reference()、formedAt<=previous.time、formationRoute==dif_turn，lockedAt/disappearedAt/reason均None。color_flip形成必已锁死，不可能留在活动快照里。结构id及structureEventId按当前规则函数精确重算。
8. active结构priceExtreme正、priceExtremeAt在origin段起点至formedAt之间；形成时记录不会跟着后来wave极值变化而被强制相等。原ref.end<origin.start；Reference的priceAt/difAt各自在其startTime/endTime内，允许两者不同且相等极值保留首次日期；formedAt不可早于origin.start。错误身份/NaN/引用/未来日期/LOCKED冒充活动、DISAPPEARED恢复STRUCTURE全部拒绝。
9. 合法更早前缀可恢复到新实例/原对象，不因processed比当前小而误拦；但SeriesEntry中既有锁死历史不会被一次恢复删除或重开。恢复计算器是继续计算所需进度，不能用来替换完整结果账本。

`Reference`固定六字段`startTime/endTime/price/dif/priceAt/difAt`，极值日期分别在其段内。底层Wave保留原八字段，比较活动ref属于历史池时比较完整Wave身份和值，而非只比较两个数。新的ParsedXxmSnapshot不读取SeriesEntry历史、不补旧pending字段。

### 4.2 SeriesEntry、asOf与不可变结果

`SeriesEntry`改为points/events/structure_records/fingerprints/checkpoints及原来源字段，删除histories/bottom_histories/rearm_records。初建、增量复制、calculator_at、forecast clone同时迁移。沿当前分批检查/缓存预算，不新增全历史读取。缓存键包括新MAIN_SPEC.spec_hash，旧缓存失效从同源重建。

快照只存继续计算的有界进度；完整结构历史由逐根XxmStep汇入结果。连续与恢复一致的测试应把分割前已经取得的step结果保留，再与恢复后的step结果合并比较，不能要求空计算器从一份有界进度凭空还原全部旧输出。

`calculator_at(count)`继续使用真实前缀、1000批量检查点及不足一批的真实重放，不引用最新最终结构记录来改变早期计算器。`_response`用actual through筛point/event，然后新建结构投影，禁止原地改entry：

- formedAt>through：该结构完全不出现；
- lockedAt存在但>through：投影ASSESSING、lockedAt=None；
- disappearedAt存在但>through：投影ASSESSING、disappearedAt/reason=None；
- 最终时点<=through：保留对应终态；结构形成时同根LOCKED的记录在该根就是LOCKED；
- 某条结构在当前前缀仍ASSESSING，则其方向/段/参照与calculator_at(end_index)的activeStructure一致；两者不同是合同失败，不靠选择最后一条掩盖；
- 只返回可见point.activeStructureId、可见event.relatedStructureId所引用的记录，以及形成/锁死/失效时间落在可见窗口的结构；按formedAt/id升序去重。普通模式仍只返回正式point/event公共字段；debug才返回structures。引用形成在窗口外的记录时带齐该记录，不强求其形成事件出现在当前events窗口；
- 记录与事件以当前身份重新核对一对一关系。两个普通事件不得用同一结构id表达两次形成；锁死没有第二个形成事件。

结构终态记录在全局SeriesEntry中只允许终结一次。追加未来行情不能改已返回的point/event/结构对象，也不能修改已LOCKED或DISAPPEARED记录；底部后来跌破旧价、旧ref DIF或出现新信号只进入新循环。新段进入同色历史池不依赖旧结构是否曾形成，不能只把有结构的段归档。

### 4.3 来源、缓存与预算

保持当前`load_entry`一次读取及共享加载、源字段/完成端点/日历完整性检查；同一请求的识别、预测及普通/debug使用这同一已校验前缀，不额外读一遍行情。初始加载/追加/源修订重建/历史位置/预测clone全使用唯一新r4。来源修订以真实前缀和现fingerprint比较触发重建，不改源SQL或重算真实MACD。**终态不可改写只约束同一来源前缀的正常追加。来源已修订时必须从空计算器重建整个SeriesEntry及全部结构结果，不能把修订结果更新进旧entry或旧终态记录，也不能因旧记录已锁死而拒绝合法重建。旧entry及此前返回对象仍保持原样；新entry完整校验成功后一次替换缓存。**

缓存键继续包含来源、标的、周期和完整detector hash；预测另含forecast hash、真实前缀/asOf和日历身份。只缓存完整内部结果，不缓存半份投影。预算沿§9，内存结果和检查点不落盘；缓存未命中或进程退出重新计算。增量先复制容器及计算器进度，在新对象聚合并校验成功后一次替换缓存；失败不污染已发布entry，结构终态记录不得原地修改。普通/debug投影分别新建对象，debug参数不改变事件/结构/forecastId。

## 5. HTTP、内部模型及普通/debug响应的完整交接

### 5.1 文件、方法和调用顺序

修改既有`src/biz/schemas/wealth/market/index_detail_xxm.py`及`index_detail_xxm_forecast.py`，保留通用数值/时间/引用/表达式检查，等待专属部分按§3.8清退并改为结构考核/锁死事实检查；完整模型统一改名为`InternalXxm*`和`InternalForecast*`，不把已有模型先删成公开最小字段。特别是query当前按`XxmPointDto.model_fields`挑字段，必须同步改用内部类型，否则历史ID会在完整校验之前丢失。

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
| XxmResponseDto | tsCode='000001.SH'；period=day/m60/m90/m120；algorithmVersion='xxm-direction-v0.2-r4'；specHash=新MAIN_SPEC真实hash；source/points/events/meta/dataStatus |
| XxmSourceDto | kind=daily_factor/minute_gold；startTime/computedThrough为本周期time或None；initialHistoryIncomplete严格boolean；indicatorVersion严格int或None（日线None）；无inputId |
| XxmPointDto | time；close正有限number；dif/dea/hist有限number；ordinaryState=NONE/DULL/STRUCTURE；ordinaryDirection=TOP/BOTTOM/None |
| XxmEventDto | id非空string；time；direction=TOP/BOTTOM；type=DULL/STRUCTURE/CANCEL |
| XxmMetaDto | count严格int>=0；responseStart/responseEnd为time或None |
| XxmDataStatusDto | status=READY/DELAYED/EMPTY；message=string或None；asOf=time或None |
| XxmDebugResponseDto | 上述全部普通字段，加必填非None的debug |
| XxmDebugDto | sourceInputId:string；points[]；events[]；structures[]；无完整decision |
| debug.points[] | time；activeReference=Reference或None；activeStructureId=string或None |
| debug.events[] | id；route；fromState=NONE/DULL/STRUCTURE；eventReference=Reference；relatedStructureId=string或None |
| Reference | startTime/endTime；price正有限number；dif有限number；priceAt/difAt为段内time；六字段全部必有 |
| debug.structures[] | §2.3完整XxmStructureRecord；原始价格/DIF及日期不格式化、不补值 |

route只有activation/dif_turn/dif_return/color_flip/dif_break/dif_break_on_flip。DULL对应activation或dif_return；STRUCTURE对应dif_turn或color_flip；CANCEL对应dif_break或dif_break_on_flip。fromState、方向、源数值和关联按真实执行核对：首次activation的fromState=NONE且relatedStructureId=None；STRUCTURE来自DULL且必须关联本次结构；dif_return来自STRUCTURE且关联本次已失效结构；CANCEL来自DULL/STRUCTURE，只有后者关联结构。不得继续输出RESEARCH_HISTORICAL_WITHDRAWAL、STRUCTURE_DISAPPEARED、historical_price_break、reactivation或旧等待status。

严格校验顺序：身份/字段/原数字/时间→source/meta/EMPTY→point状态方向→event类型/route/fromState→六字段参照及结构事实→双向引用。debug.points.time和events.id分别与普通数组逐项同序一致；结构按formedAt/id排序唯一，终态和空时间关系按§2.3。普通响应完全没有debug，不用空数组冒充未加载。

历史point的activeStructureId表达该point发生时的考核状态，不等于查询截至时的结构终态。逐point按`formedAt<=point.time<lockedAt或disappearedAt`核有效区间；记录在查询截止时已LOCKED/DISAPPEARED，仍可由更早point引用。只对最后实际前缀的stateSTRUCTURE要求对应截至当时的ASSESSING记录。窗口外形成、窗口内回转/锁死时带齐引用的结构记录，不强求形成event也在窗口；按id算法及record形成字段核验。asOf投影先按§4还原当时终态，再做上述关系检查，不把未来锁死塞回旧point。

### 5.4 下一根预测目标合同（待实施）

本节与§6同批实施。沿既有预测URL、标的/周期/asOf/鉴权和debug请求规则，不新增预测入口。目标只下一根；旧20步、等待和结构形成即停算格式不兼容。以下明确的是待实现目标，不是当前运行响应。

`InternalForecastResponseDto`完整根为下文全部普通根字段，加sourceInputId/calendarInputId/precisionPolicy/references/selectedReference/nearestDecision/farEvaluated/conditions/precisionRanges九项内部事实；内部不加debug嵌套。`project_forecast_response`先校验此完整集合，普通显式复制公共字段，debug再把这九项组为debug对象；只生成一次display和forecastId。缓存保存这个完整内部对象，不保存普通删减结果。

#### 5.4.1 普通响应完整字段

普通根字段精确为下表；`debug`缺省不存在，不返回null或空对象。普通card只消费后端生成的最终display，不自行反求边界或组合debug条件。

| 字段 | 类型/固定值 | 空值与校验 |
|---|---|---|
| tsCode | `000001.SH` | 不可空 |
| period | day/m60/m90/m120 | 不可空 |
| forecastVersion | `xxm-key-point-forecast-v0.4-r4` | 不接受旧r2或20步版本 |
| forecastSpecHash | 实际FORECAST_SPEC hash | 与当次正式构建一致，不手编 |
| detectorSpecHash | 修订后`xxm-direction-v0.2-r4` Spec hash | 必须与实际识别结果身份一致 |
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
| invalidationText | 非空中文字符串 | 新完成数据后重算；零不自动使条件失效，锁死旧结构不再考核；B未算A不能写成总体钝化消失 |
| refreshAfterMs | 60000 | 原刷新规则 |

旧`confirmedAt/confirmedDirection/rearmContext/nextBarOutcomes/activation/assumption/targetEntryRanges/targetEntryExclusions/relations/commonConditions/examples/precisionPolicy/sourceInputId/calendarInputId`均不再为普通字段。仍需要的来源、精度、数学和条件信息只在下述debug固定集合；删旧字段的Python/TS/adapter/fixtures同步，不以null或空数组保兼容。

#### 5.4.2 status、reason及显示关系

| status | 必须满足 | reasonCode | 普通显示 |
|---|---|---|---|
| EMPTY | dataStatus=EMPTY，状态/方向/target/barsAhead为null | SOURCE_EMPTY | 暂无完成行情，不显示假设点位 |
| DELAYED | dataStatus=DELAYED，保留实际computedThrough/状态，target/barsAhead为null | SOURCE_DELAYED | 来源滞后，不用旧行情冒充最新预判 |
| NO_CANDIDATE | dataStatus=READY；静态无可能，或已完整求解证明本次近优先流程选中的首次/延续/救援关系没有范围且没有未决价段，具体限定见下文 | ZERO_WAVE/NO_REFERENCE/NO_ENTRY_RANGE | 后端说明具体无可能原因；不能用今天价格没创新低作为明天无可能依据 |
| PRECISION_PENDING | dataStatus=READY；校准失败，或没有任何确定可用条件范围、仅剩来源/原运算未决段 | CALIBRATION_FAILED/ROUNDING_BOUNDARY | 明确条件尚不能确定；不能把未决范围写成无解或确定标签 |
| READY | dataStatus=READY；至少有一个确定可用条件范围；target非null/barsAhead=1。允许另有窄临界未决段，但不得影响已给范围的成立或近优先选择 | null或ROUNDING_BOUNDARY | 只展示已证明范围；另有未决段必须在必要文字说明，不将未决段算无解；既有结构不是直接CONFIRMED |

`NO_CANDIDATE`静态结束时没有target；已进入求解后真无解仍保留target和barsAhead=1。校准在未来端点读取前失败时target为null；边界求解未决时target非null。无合法整数不是数学未知或无解：有确定范围时status仍READY、reason按是否另有未决段为null或ROUNDING_BOUNDARY，普通写“已算出条件范围，暂未生成可用整数点位”，debug保留精确范围。不能因无整数启用A。

近远资格仍未确定时，仅已证明某些价格会让B失效，不能据此把整个结果升级READY：如果B是否还有有效关系仅剩未决，则保持PRECISION_PENDING且A不算。已有STRUCTURE固定参照，不存在这项近远选择未决；其明确保持、回钝化、消失或锁死条件均可正常READY。

上述“没有范围”只限定NONE的首次搜索，以及DULL/B已确认没有有效延续、转求A救援的调度。后者若A不存在、已被本轮DIF突破，或已求A而救援范围确定为空且无未决，则NO_CANDIDATE/NO_ENTRY_RANGE，conditions和precisionRanges均为空；已求解的target/barsAhead保留，nearestDecision及selectedReference/farEvaluated按实际执行填写。普通文字明确“近参照没有有效延续范围；远参照不存在/已失效/没有救援范围”，不能解释为当前真实钝化已经消失，也不把B失效范围拼回A条件。**活动参照本来就是A、或当前已有STRUCTURE时不适用这个退出口径**：固定原参照的明确消失条件也是可用结果，不能因无保持范围而抹掉。

普通display由同一个内部结果一次生成。已有DULL/B且B有解时，A完全不算；B突破的条件必须写“近参照失效，远参照本次未计算，真实收盘按r4同根规则检查”，不得输出“钝化必定消失”。STRUCTURE/R原参照突破则可明确结构直接消失；活动A被突破可明确钝化消失。必要限定不能仅依赖debug字段。

#### 5.4.3 debug精确字段及条件事实

`debug=1`在相同普通根字段外恰好增加debug对象：

| 字段 | 类型及含义 |
|---|---|
| sourceInputId | 当前正式来源前缀指纹或null；EMPTY为null |
| calendarInputId | 本次实际下一端点日历身份或null；未请求未来日历时null |
| precisionPolicy | day=`rounded3_guarded`，分钟=`full_float` |
| references | `{nearest: Reference|null, farther: Reference|null}`；完整参照沿统一Reference字段，含priceAt/difAt，来自当前逻辑方向历史池；不造第三个 |
| selectedReference | `NEAR`/`FAR`或null；实际进入某参照求解才填，静态/校准前结束null；已有活动A只能FAR |
| nearestDecision | `{status, reason}`；status为NOT_EVALUATED/UNAVAILABLE/HAS_RANGE/NO_RANGE/UNCERTAIN；reason为后端非空中文或null，描述实际执行检查，不把没算写成无解 |
| farEvaluated | bool；仅实际执行A条件求解时true。B有确定有效关系范围或未决关系段必须false；不存在A或静态拦截不能写true |
| conditions | 下列Condition数组；未求解/无条件则[]；按固定outcome顺序输出，同一种outcome仅一项、其范围升序不重叠 |
| precisionRanges | `[{priceRange, reason}]`；其中priceRange恰为lower/upper/lowerInclusive/upperInclusive四字段，不给未决段生成display整数；reason沿ROUNDING_BOUNDARY；只保留未决临界段，不能声称这是全正价格空间的最终状态分割。无未决则[] |

`Condition`精确字段为`{id, outcome, referenceRole, priceRanges, predicates}`。referenceRole为NEAR/FAR且与selectedReference相同。priceRanges使用`{lower,upper,lowerInclusive,upperInclusive,displayLower,displayUpper}`：内部lower有限且>=0、upper有限或null（无有限上界）；C=0永远排除；displayLower/Upper为合法整数或null，无整数时两者null；已有无上界范围的displayUpper=null、displayLower为合法整数，这不等于无整数。不能用显示值代替内部开闭。

`outcome`固定为：DULL_FORMED、DULL_HELD、STRUCTURE_FORMED、STRUCTURE_HELD、RETURNED_TO_DULL、STRUCTURE_FORMED_AND_LOCKED、STRUCTURE_LOCKED、SIGNAL_DISAPPEARED、REFERENCE_INVALIDATED。这是下一根“在给定收盘条件下发生什么”的debug事实，不新增ordinaryState或普通事件类型。

- NONE只允许DULL_FORMED，不允许首次同根STRUCTURE。
- DULL允许保持、形成、形成并锁死；原参照A破可SIGNAL_DISAPPEARED。原参照B破且A未计算时仅REFERENCE_INVALIDATED；真实翻色B破不救远，可SIGNAL_DISAPPEARED。
- STRUCTURE允许保持、RETURNED_TO_DULL、锁死、SIGNAL_DISAPPEARED；不走远救援。
- 已锁死历史不作为本次条件reference，不产生撤销旧锁死记录的条件。

`predicates`是同一参照范围的必要比较数组，复用现ConditionDto的left/op/right表达式语义，但MACD表达式收敛到固定一步`{op:'macd',e12,e26,dea,field}`；field仅dif/hist，原运算顺序固定，不接受prefixBars/prefixClose/target及变量P。其余仅允许现affine的两种固定形式：常数{pCoefficient:0,cCoefficient:0,constant:k}和当根价格C{pCoefficient:0,cCoefficient:1,constant:0}，以及round3/sub/scale/abs。必须拒绝非零pCoefficient、其他cCoefficient及多步MACD字段；不另造literal节点，不由前端推算C条件。相同来源绑定必须一致。条件是完整规则的数学说明，前端只校验/展示，不负责判别或求界。

Condition id由同次forecastId和outcome生成；不依赖debug、窗口或显示小数位。普通forecastId先由不含debug的内部事实生成，再映射Condition id，避免相互引用生成身份。所有数字有限、引用与当前参照一致、日期/周期一致；限定窗口需更早参照仍完整带齐。内部/公开范围共用校验：lower有限>=0且0必开，upper有限或None，None必开；有限单点必须正数且两端闭合，倒置/空范围拒绝。每项priceRanges升序不重叠；确定区间与precisionRanges不得重叠，不能同时声称确定和未知。不同outcome互斥性按§6.4完整条件核验，不要求所有正float都被覆盖。总响应仍≤32KiB，超限整份失败，不截断条件或关联。

#### 5.4.4 可人工核算的一步数学样本

以下只验证求解/识别数学，不冒充recover_projection对真实源的250根校准。每组计算器从空输入固定(C,D,H)，DEA按D−H/2字面给定；ProjectionState也独立字面给定。日期使用§14固定t1…t7，不使用旧测试中的非交易日日期。

**M1：底部已钝化，下一根合法零和结构。**

输入：`(100,−60,−2);(110,0,2);(90,−50,−2);(100,0,2);(89,−15,−30);(88,−14,−28)`。t6已有底部钝化，近B价90/D−50，远A价100/D−60，当前count=2，P=−14、DEA=0。独立投影字面`e12=13,e26=27,dea=0`。

原一步：D(C)理想式=`−14+28*C/351`；H(C)=1.6*D(C)。C=175.5时原计算两EMA均38，D=0、DEA=0、H=0；count不加、未反色、原参照未破，相邻DIF−14→0达到1%，故t7形成未锁死底部结构。不能因零柱RESET或反根偏移排除该点。

分钟理想结构形成下界D>=−13.86，故C>=1.755；同色/零要求D<=0，故C<=175.5；即理想闭范围[1.755,175.5]，实际范围以原顺序/误差证明确定边界，不把理想式直接当原float证明。C=1.75不足1%，C=2明显超过1%应结构；C=176真实翻红且有效，应形成且锁死。显示整数端点须原step复核。

**M2：顶部镜像合法零。**

按(C,D,H)→(200−C,−D,−H)变换M1，得到完整6根`(100,60,2);(90,0,−2);(110,50,2);(100,0,−2);(111,15,30);(112,14,28)`，ProjectionState=`(187,173,0)`。t6顶部钝化，B价110/D50，P=14；C24.5时两EMA均162、D/H均0，t7走相邻1%形成未锁死顶部结构；C24真实翻绿则形成并锁死。两组仅是有限原运算正反例，不从运行输出生成expected。

**M3：下一根首次钝化，不继续猜第二根结构。**

完整输入`(70,10,2);(90,0,−2);(100,2,8)`，t3当前红count1、无钝化，B价70/D10。ProjectionState=`(102,100,−2)`；下一根D理想式`(28*C−2206)/351`，首次要求C>70、0<D<10以及H>=0。H=1.6*(D+2)，D>0已保证正红，下一根count2。因此理想首次范围`(1103/14,1429/7)`，C100原计算可明确首次钝化；即使相邻转折另有情况，本根只DULL，不能报告未来第二根结构或旧CONDITIONAL_ENTRY。日线使用各自source_options后重定临界归属，不照搬分钟开闭。

**M4：近仍可能则不算远。**

取M1前缀和投影，B的正常结构范围已非空。将A求解替身设置为一调用即抛错；求解仍正常给B条件。即使存在某些假设使B失效，本次也不能因此触发A；REFERENCE_INVALIDATED限定文字要与真实完成K线可能当根救A同时成立。

**M5：回转与直接失效的纯规则核验。**

顶部从§14 `TS`完整输入开始，P=99、当前未锁死结构B价100/D200；独立ProjectionState=`(10099,10000,98)`，与前DIF99/DEA98相符。理想D(C)=`(28*C−250597)/351`。分别用三个独立整数C：10204得到D=35115/351≈100.0427，向上回转超过0.99且未破200，应回钝化；10197得到D=34919/351≈99.4843，回转小于0.99，应保持结构；11470得到D=70563/351≈201.0342，严格破200，应结构直接消失。H=1.6*(D−98)均正，不走反色。

底部从§14 `BS`完整输入开始，P=−99、结构B价100/D−200；独立ProjectionState=`(9901,10000,−98)`。理想D(C)=`(28*C−309403)/351`。C9796得到−35115/351，应回钝化；C9803得到−34919/351，应保持结构；C8530得到−70563/351，应直接消失。H=1.6*(D+98)均负，不走反色。所有C均有限且正，价格不再限制已有结构回转。分钟以原投影验证上述远离边界的期望；日线三位来源后分类相同。精确1%和临界开闭另由RC46/47及PF门槛测试证明，不用这些非临界数冒充等号覆盖。

### 5.5 最小样例、错误及迁移对账

新fixture用§14独立输入/预期构造，身份参数必须显式传入同次实际生成的hash，禁止用旧JSON换hash冒充新模型。普通READY有事件/无事件、EMPTY、DELAYED及debug同公共字段各准备字面样本；debug含同段反复结构、同根翻色锁死、窗口外形成/窗口内失效、历史point引用如今已锁死记录和早asOf还原样本。

EMPTY识别points/events为空、meta.count=0及首末None；debug对应数组为空，无伪造历史。DELAYED保留真实可用根和截至时间，不能补行情。前三条API非法debug/日期400、不支持标的404、源/模型或一般查询失败500、预算503沿现异常登记；生产未注册路由由框架404且不读来源。错误不转EMPTY，客户端保留普通K线但清除本次失效标签及辅助资料。

旧格式拒绝、新格式正常接收、合法int数值、显式None、事件多种真实route、日期不同但数值相同、结构终态时间晚于查询截止等均须正反测试。普通/debug对同一内部结果的全部公共字段和字节解码值相同，只有debug部分不同；debug失败不得退回普通成功。真实HTTP分别验普通和debug，不拿内部模型通过替代API验收。

## 6. 下一根预测编码设计（已按P3第1步对齐，尚未开发）

本节只细化既定单根预测，不修改§3已验收识别规则，不引入第二个识别器。开工前先按§6.11核对；本轮只完善文档，没有修改预测代码、测试代码或运行Spec，没有运行预测、真实行情或性能验收。

### 6.1 本步范围、输入和代码交接

P3第2步完成纯计算：前提检查、一个实际未来端点的条件、有限边界、原点核验、整数显示、固定FORECAST_SPEC及纯文字。第3步再接查询/日历/缓存/完整模型/投影/API，第4步迁TS调用。本步不得为了跑通旧公开DTO提前改query/API，也不得为保留旧工具留下可运行旧求解器。

输入直接使用P3第1步的`SeriesEntry.calculator_at(n, check)`独立副本。只读`period/source_identity/spec/previous/processed/wave/history/state/reference/active_structure`；`STRUCTURE`必须对应同方向、同参照的`ASSESSING`活动结构。已经锁死的结构不在计算器活动进度里，无需复制`SeriesEntry.structure_records`全集。不得从末根H符号、窗口中的最后一条STRUCTURE事件或旧pending字段反推当前状态。

| 方法及位置 | 固定输入/返回/职责 |
|---|---|
| `forecast.py:precheck_next_bar(c, check)` | 返回`ForecastPrecheck`；只检查真实进度与静态可能性，不校准EMA、不读日历、不尝试假设收盘 |
| `forecast.py:forecast(c, projection, endpoint, check, *, prepared)` | endpoint必须是单个时间字符串，不再接受端点序列；prepared为同次前提检查。校验仍是同一真实进度后编排B/A或固定参照，返回`ForecastKernelResult` |
| `forecast_entry.py:solve_first_dull(c, projection, endpoint, reference, role, check)` | 仅NONE、仅给定一个参照的首次钝化范围；不在内部偷偷选择A或推第二根 |
| `forecast_next.py:solve_active_reference(c, projection, endpoint, reference, role, check)`（新增文件） | DULL/STRUCTURE的一个实际参照；DULL/B被证实无有效关系后，才允许单独求A的救援范围 |
| `forecast_math.py:solve_comparison(left, op, right, domain, *, projection, period, check)` | 返回`ComparisonRanges`，直接求有限根及可确认成立/不成立/临界未决范围；不取区间中点或遍历价格 |
| `forecast_detector.py:evaluate_next_at_price(c, projection, C, endpoint, role, check)` | 对有限必要边界点/整数进行同一原投影和所有来源组合核验；真正标签以唯一r4的clone+一次step判定 |
| `forecast_detector.py:verify_reference_invalidation(c, bar, reference)` | 只核近B同色/零时严格突破的参照事实，使用原`_reference_was_broken`及独立的本根DIF极值副本；不调用完整step、不检查A资格 |
| `forecast_text.py:make_display(result, *, prepared, period, through, mode, check)` | 读取同次prepared的真实state/direction、新结果及已核合法整数，生成原四字符串；不再取历史分位数、裁掉范围或重新求价 |

以下内部类型放在现`types.py`，不改既有`XxmBar/Wave/XxmStep/XxmStructureRecord`的含义。采用明确字段的不可变外层记录，集合用tuple；包含的参照/快照/表达式必须独立复制，不能与输入或缓存共享可变对象。它们不作为新HTTP字段透传：

| 内部类型 | 完整字段 |
|---|---|
| `ForecastPrecheck` | `snapshot`（根前有界进度副本，仅RAM）、`direction`、`references`（nearest/farther六字段参照或None）、`active_role`（NEAR/FAR/None）、`nearest_decision`、`stop_reason`（既有原因或None） |
| `ComparisonRanges` | `certain_true`、`certain_false`、`undecided`，均为升序不重叠的Interval元组；在传入domain内互不重叠且并集等于domain |
| `ForecastConditionDraft` | `outcome`、`reference_role`、`price_ranges`、`predicates`；与§5.4.3对应，但没有尚未生成的Condition id |
| `ReferenceForecast` | `conditions`、`relationship_ranges`、`relationship_precision_ranges`、`precision_ranges`；relationship两项只统计§6.3有效关系的确定/未决价段；precision_ranges保留该参照全部适用outcome的未决价段，不能混用这两个未决集合 |
| `ForecastKernelResult` | `status`、`reason_code`、`target_endpoint`、`bars_ahead`、`references`、`selected_reference`、`nearest_decision`、`far_evaluated`、`conditions`、`precision_ranges` |

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
| NONE且无B | NO_REFERENCE，结束 | 虚构A或第三个 |
| NONE且`wave.count+1<2`，或全部现有参照本轮已严格突破 | NO_ENTRY_RANGE，结束 | 用今天未过价格/今天DIF不正作为明天无解理由 |
| NONE且至少一个参照仍可能 | 继续；按下一根H区分count是否增加 | 历史单根过滤、把零算成第二根 |
| DULL | 沿实际活动参照；活动B先B，活动A固定A | 每天重选最强、回切B或重查首次价 |
| STRUCTURE | 核active_structure为ASSESSING，固定其原参照继续考核 | 直接CONFIRMED停算、救A保结构 |
| 上根已锁死，当前是新段NONE | 按当前wave/count及当前方向历史池重新判断 | 因旧结构已锁死而停止整个请求，或再预测撤销旧结构 |

实际调度固定为：

```text
prepared = precheck_next_bar(c, check)
if prepared.stop_reason: 返回静态NO_CANDIDATE，target=None
if c.state == STRUCTURE or c的活动参照为A:
    仅求这个固定参照
else:
    B静态已破时标UNAVAILABLE；否则先完整求B
    B.relationship_ranges非空：停止，A求解/资格/核验均不调用
    B.relationship_ranges为空但relationship_precision_ranges非空：PRECISION_PENDING，不调用A
    B上述两个关系集合均为空：才审A是否存在、是否本轮已破
    A仍可能时单独求A；不把B失效范围与A范围合成两套标签
```

有效关系只统计：NONE的DULL_FORMED；DULL的DULL_HELD、STRUCTURE_FORMED、STRUCTURE_FORMED_AND_LOCKED。失效事实和未决价段不冒充有效关系；“没有结构形成范围”不等于近处钝化无可能。已有STRUCTURE不做这项近远调度，其保持/回钝化/锁死/消失范围均按固定原参照返回。

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

不能把未执行写成NO_RANGE。无合法整数不改变关系是否有解；B有解但无可显示整数也不触发A。状态、target及原因继续按§5.4.2，不因为旁侧失效条件有范围就把只剩关系未决的请求升级READY。

### 6.4 可编码条件及唯一r4结果核对

s为旧逻辑方向（顶+1、底−1），R为实际选中参照，Pr/Dr为其价格/DIF，PB为近B价，P为上一真实DIF。先按原float顺序算`g=abs(P)*1.0/100`，再对同一个源D计算`delta=s*(D-P)`。对参照的“本轮已破”读根前wave.dif；候选下一根破与当根资格分别进入下表。

| 前态/条件 | 完整必要谓词 | outcome |
|---|---|---|
| NONE/R首次 | 同色或零，`count+int(H!=0)>=2`，R根前未破；`s*(C-PB)>0`且`s*(C-Pr)>0`；`s*(D-Dr)<0`；TOP额外D>0 | DULL_FORMED |
| DULL/R翻色且破R | `s*H<0`且`s*(D-Dr)>0` | SIGNAL_DISAPPEARED |
| DULL/R翻色且R有效 | `s*H<0`且`s*(D-Dr)<=0` | STRUCTURE_FORMED_AND_LOCKED |
| DULL/R同色或零形成 | `s*H>=0`且未破R；P!=0，delta<0且−delta>=g | STRUCTURE_FORMED |
| DULL/R同色或零保持 | `s*H>=0`且未破R；上述1%形成不成立 | DULL_HELD |
| DULL/B同色或零破B、A未计算 | `s*H>=0`且B本根严格破 | REFERENCE_INVALIDATED，仅说明近处失效 |
| DULL/A同色或零破A | `s*H>=0`且A本根严格破 | SIGNAL_DISAPPEARED |
| DULL/B已确定无关系，单独求A救援 | §6.3完整救援条件，不再检查1%形成 | DULL_HELD，实际活动参照A |
| STRUCTURE/R严格破R | 先检查`s*(D-Dr)>0`，不论柱色 | SIGNAL_DISAPPEARED |
| STRUCTURE/R有效且翻色 | 未破R，`s*H<0` | STRUCTURE_LOCKED |
| STRUCTURE/R有效且同色/零回转 | 未破R，`s*H>=0`，P!=0，delta>0且delta>=g | RETURNED_TO_DULL |
| STRUCTURE/R有效且同色/零保持 | 未破R，`s*H>=0`，回转不成立 | STRUCTURE_HELD |

每次只生成本态适用的条件。保持谓词不必新增OR表达式：P!=0且g>0时，DULL保持的1%部分写`−delta<g`，STRUCTURE保持写`delta<g`；g==0时分别写`delta>=0`、`delta<=0`；P==0则不生成1%形成/回转条件。**P非0不保证g非0，极小float下溢仍须保留严格方向。**这些只化简已计算delta/g的逻辑，不把D±g替代原运算，不改变条件AST合同。

`evaluate_next_at_price`必须核完整语义：

| outcome | 唯一step结果必须同时满足 |
|---|---|
| DULL_FORMED | DULL/activation、fromState NONE、实际参照R，根末DULL，无结构记录 |
| DULL_HELD | 原DULL关系保持且无新普通事件；A救援时实际参照为A，原事件不改 |
| STRUCTURE_FORMED | STRUCTURE/dif_turn，关联新ASSESSING记录，根末STRUCTURE及同id活动记录 |
| STRUCTURE_HELD | 无新事件/更新，原同id活动结构继续ASSESSING |
| RETURNED_TO_DULL | DULL/dif_return，原结构同id DISAPPEARED/dif_return，根末DULL且ref仍R |
| STRUCTURE_FORMED_AND_LOCKED | STRUCTURE/color_flip，新同id结构formedAt==lockedAt，根末新段NONE |
| STRUCTURE_LOCKED | 原活动结构同id LOCKED，无新STRUCTURE事件，根末新段NONE |
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

原先未决的候选点，全部来源组合语义一致时可单独记为闭合单点，并从未决带中剔除；不能据该点扩张邻域。M1/M2的175.5/24.5必须这样保留合法零，不因误差带覆盖0而丢掉。若来源组合结论不同，继续未决。已经宣称确定的点或显示整数若核验不一致，必须整次失败，不能退回未决来掩盖证明错误。

只合并同参照、同outcome、同route/谓词和同精度含义的相邻区间；不同条件不得平均价格再算。不同outcome互斥，但不要求用条件覆盖全部正float；对某个原谓词三组范围的完备要求，不得误解成全标签全域划分。

### 6.6 精确范围、整数和文字

保留内部原边界和开闭。对每个确定区间直接计算合法最小/最大整数：闭下界取ceil，开下界整数时再+1；闭上界取floor，开上界整数时再−1。例开4135.78→4136，开4136→4137，开4140.2→4140，开4140→4139；闭整数可用。不得把边界先格式化再取整、互换上下界或向外移动。

对有限整数端点用`Interval.contains`及§6.4原语/唯一r4再核验，保留原投影的全部来源绑定。**不一致即ValueError向上失败，不缓存、不挪价、不跳点、不换epsilon、不返回半份READY。**未决点不生成整数，不拿一个已证实单点填补两个确定区间之间的未决空隙。

无整数时priceRanges仍保留精确非空范围、displayLower/Upper均None，状态仍依数学关系可READY；不能据此查A。无上界的确定区间可有displayLower而displayUpper=None。纯单点只描述该点，不能写成从该点开始的连续不低于/不高于范围。

文字只读取新结果及显式传入的同次prepared。当前状态读取prepared.snapshot的state，顶底方向读取prepared.direction；核对period与snapshot.period、through与snapshot.previous.time一致，不从DIF正负、条件是否为空或某个outcome猜方向。NONE重点说明首次钝化范围；DULL优先结构形成/形成锁死与失效限定，再列保持；STRUCTURE优先直接消失/回钝化，再列锁死/保持。完整条件不得被历史分位数或示例选择裁掉；同outcome多段按已有顺序列出，不凭前端合并。B未算A的失效限定必须出现在普通文字，不藏debug。display仍为原四字段，不增加页面功能。

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
| `forecast_spec.py` | §6.9完整固定字段和类型；生成实际v0.4-r4 hash | 第3步模型/API和第4步TS登记同次hash，不伪造旧hash |
| `forecast_query_service.py`、预测schema/API | 第2步不编码、不验旧公开入口；本节已固定新输入/结果与下一端点交接 | 第3步按下列唯一顺序整体迁，移除_active_confirmation、rearmContext、20步及旧DTO |

第2步移除正式旧求解路径，不删除P5专属研究/报告执行器或原材料。依赖它们的未迁工具留明确停点，不能当新预测验收。生产/页面不发布中间版本，识别核心及其Spec/记录格式不得为了适配预测而改回旧规则。

第3步完整内部根继续为§5.4集合。query加入来源/日历、真实状态、规则身份和asOf；forecastId先由不含debug/Condition id/自身forecastId的内部事实规范生成，再按该forecastId+outcome生成Condition id。**Draft没有id是纯计算阶段的确定合同，不是公开响应允许空id；完整内部模型生成前必须全部填好并校验。**普通display同一次生成，正常/debug只投影，不另算标签或条件。

### 6.8 同一预算、异常与开发顺序

400ms仍包含calculator_at/恢复、前提检查、完整前缀EMA校准、日历/缓存处理、求界、全部来源组合及必要step、文字、模型、投影、一次编码、缓存复制/大小统计/锁等待和最后检查。有效截止=min(原4秒请求截止，本次计算或缓存处理开始+0.4秒)。缓存命中也在同一截止中，不能命中后再开400ms或读取完成后另加4秒。

第3步query采用以下简单固定顺序，不新增缓存索引或另一套恢复机制：

1. 通过同次`load_entry`取得已校验真实前缀；EMPTY/DELAYED直接按来源状态生成结果，不进calculator_at/校准/未来日历。
2. READY在calculator_at、前提检查及任何预测缓存处理之前建立同一400ms截止。precheck静态无可能立即生成静态结果，不校准、不读未来日历。
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

第2步顺序固定：已验收核心/clone→内部类型及precheck→原值/日线源包络与ComparisonRanges→NONE条件→DULL/STRUCTURE与结果映射→B/A调度→有限点和整数→纯文字/固定Spec→独立PF测试与审计。每一项先有相应独立字面预期，不能先接旧公开DTO跑通再倒改字段。

### 6.9 FORECAST_SPEC与有限工作量

| 字段 | 固定值 |
|---|---|
| forecast_version | `xxm-key-point-forecast-v0.4-r4` |
| scenario_policy / target_selection / max_future_bars | `next_completed_bar / near_range_before_far / 1` |
| calibration_tail_bars | 250 |
| daily_calibration_abs_tol / minute_calibration_abs_tol | 0.0005 / 1e-8，仅校准 |
| daily_rounding_guard | 1e-10，沿现source_options |
| display_policy / structure_text_places | `valid_integer_boundaries / 0` |
| forecast_compute_budget_ms / max_response_bytes | 400 / 32768 |
| future_calendar_days / refresh_after_ms | 90 / 60000 |

删除旧price_display_places/price_boundary_places/explanation_sample_count/display_move_samples/display_move_quantile和多步政策，不加可选算法/源误差参数。`__post_init__`按MAIN_SPEC方式逐字段严格验证类型和固定值，拒bool冒充数字。预测hash继续由自身全部字段按现`json.dumps(asdict(spec), sort_keys=True).encode()`规范生成，不手填hash、不混用detector的序列化约定。本轮未修改运行Spec。

最多求两个实际参照：B有关系或有未决关系时A为0次。每个参照只生成适用谓词的有限根及相关邻点/整数；一个C至多一次advance、至多4组来源核验。记录实际参照数、谓词数、反根数、点核验及step次数；同状态/门槛个数相同，价格尺度扩大不得按跨度增加循环。无96/192等未经依据的额外次数上限；400ms仍为计算时限，不通过增加源码保护或全float搜索达成证明。

### 6.10 预测测试设计与识别规则对应

本轮只补测试设计，以下均未编码/执行；不得拿P3第1步1730项成绩当本节通过。新数学测试放现主题`test_xxm_p3_forecast_math.py`及必要`test_xxm_key_point_forecast.py`，不创建新研究项目。业务expected来自§14字面事实，数学expected来自M1—M5/Fraction或明确原运算，不能由待测forecast生成。

| 编号 | 独立样本/明确操作 | 必须证明 |
|---|---|---|
| PF01 | M1/M2，C175.5/24.5；直接给ProjectionState，不校准 | 合法零成未锁死结构，闭合单点可从未决带取出；邻域仍按独立证明，不调用guard=True提前丢点 |
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
| PF13 | RC53—58/65；DULL翻色、STRUCTURE翻色及同根原参照破；H=0 | 读events+structures辨别同根形成锁死/旧结构锁死/直接消失；新段NONE不是取消；零不锁 |
| PF14 | RC63两轮；从锁死根后的calculator_at进度开始 | 按新wave/count/history判断下一轮，不读完整旧structures重开锁死记录 |
| PF15 | 开4135.78/4136、开上界4140/4140.2、闭整数、单点、无整数窄段；Fraction根落相邻float之间及相邻float开区间；故意让已证实点/整数核验不符 | 定向转换及开闭正确，无可表示C的区间必须为空、合法闭单点保留；合法整数与原点一致，不扩大单点/跨未知合并；不一致整次失败且无候选缓存，不挪价/降级掩盖 |
| PF16 | 正/负/0/subnormal及原大数−8796093022207.98；Fraction独立算Ef/Er及源输出误差；M1/M3正常整数 | 包络覆盖全部原source_options选项，含大数额外值；_expression_envelope通用round3仍拒认证；普通正常范围不得全未知 |
| PF17 | 非有限state/C/原中间结果/源乘1000、非法反根/坏prepared/错误活动结构 | 明确失败不当无解或ROUNDING_BOUNDARY；输入/既有结果不变，check原异常不吞 |
| PF18 | 同C有2×2源组合：源值不同但语义相同/语义或参照不同；失败/开关debug/缓存命中 | 一次advance、组合各自独立clone和一次step、同源谓词绑定；一致可确认，分歧未决；失败不污染源进度。第3步再验普通/debug同ID/同display及同截止 |
| PF19 | M1/M2四周期数学计时及等数量门槛的价格尺度变化；第3/5步含完整前缀校准/日历/模型/编码/缓存复制与锁等待 | 记录调用数及数学耗时；完整400ms分层验收，发布前最后check、冷/热/异常不重复读或返回半成功。真实源留P4 |
| PF20 | 旧20步/P变量/WAIT/prefix字段/旧版本fixture；新单endpoint及内部Draft→完整模型/id；BOTTOM但DIF为正、空条件及错误period/through的文字输入 | 第2步内核拒旧收新、不回退旧求解；文字只读显式prepared，不猜状态方向，错进度拒绝；第3/4步再验HTTP/TS完整合同，不能用换hash或空旧字段兼容 |

### 6.11 本轮文档核对与开工条件

已对照P3第1步实际`calculator/types/spec/snapshot/SeriesEntry/InternalXxm*`和现预测源码核对本节，并独立审核状态映射、有限误差证明及第2/3步交接。没有新增识别规则、公开字段、预算或需要重新拍板的产品决策。接口字段仍以§5.4为唯一集合。

第2步开工前必须核对：本节签名/内部字段和文件去向、P3第1步规则回归仍成立、M1—M5/PF01—20独立expected及静态无可能/固定参照/源分歧/原点失败负例、旧正式多步调用清单、dirty文件边界。任何需要改变原识别、源值表示或400ms才能推进的问题必须先停报，不临时换办法。本轮没有开发或执行这些测试，不声称数学性能或产品预测已通过。

## 7. 离线观察与debug的配合

### 7.1 唯一step可选记录

保留`record_decisions: bool=False`及`XxmStep.decision`，step签名不变。默认关闭的正式query、历史复制和预测clone不采集完整过程，不在HTTP/SeriesEntry/snapshot增加decision数组。只有手动离线观察显式开启；真/假两种模式除decision外的所有结果和快照必须完全相同。

XxmDecision删除rearm及waiting分支；referenceChecks对每个参照分别增加`referenceBroken: bool|None`以记录真实已执行的曾击穿检查，`difPassed`只表示本根DIF严格资格，不能兼任曾击穿结果。未执行写None，不推断True/False。turn保留previous/current/threshold/refBroken/checked；增加结构动作字段`structureId/structureStatus`（可空）即可表述本根确认、回转、取消、锁死，无需复制完整历史。before保存activeStructureId；观察只记录实际条件值，不再运行选择器来补解释。record_decisions=False路径不分配观察对象；观察True/False所得全部业务step完全相同。

### 7.2 观察字段与资源边界

`XxmDecision`完整字段为time/rawSign/before/wave/referenceAfter/referenceChecks/selectionCalls/turn/switched/structureId/structureStatus/branch/reason。before在现state/reference/wave/previousDif上加activeStructureId；referenceChecks保留现stage/candidate/wave/checked/pricePassed/difPassed/reason并加referenceBroken，未执行的bool字段均None；selectionCalls保留实际stage/selected；turn保持previousDif/currentDif/threshold/referenceBroken/checked/reason。结构动作字段只用于离线观察，不是event关联字段别名。

无普通事件时branch只允许leading_zero/reference_switch/segment_changed/structure_locked/retained/no_activation；普通事件时使用实际route。反色锁死没有普通事件仍记录真实structure_locked。无rearm/waiting/historical_price_break观察路径。只保存真实执行结果，不重新调用选择器、不从终态反推未执行条件。

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
| `features/index-detail/debug/XxmDebugDetails.tsx`（新） | 将现XxmResearchDetails改为参照、结构考核/锁死/消失说明；依据debug对象，不前端推测原因 |
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

- 普通XxmResponse根包含tsCode/period/algorithmVersion/specHash/source/points/events/meta/dataStatus；正常source不含inputId；正常points不含活动参照和activeStructureId；正常events仅id/time/direction/type。
- debug响应的必有debug对象包含sourceInputId、同time的debug.points、同id的debug.events、structures。普通请求不允许出现该对象；debug请求要求符合本文各状态对应的对象形状。
- 保留XxmPeriod四种；事件仅DULL/STRUCTURE/CANCEL，旧RESEARCH_HISTORICAL_WITHDRAWAL/STRUCTURE_DISAPPEARED必须被新decoder拒绝，不在绘图层隐藏或改名兼容。
- XxmMarker只依赖正常event的id/time/type/direction和源DIF；markerGeometry/XxmMacdPrimitive不得强读debug route/history。
- XxmViewModel.byTime正常只关联point和events；增加可空debugDetail只在通过debug解码时构造。正常按ordinaryState/direction显示真实当前状态。新业务没有等待，普通或debug均不能继续生成“待重新钝化”；锁死记录在debug说明，正常标记仍由真实形成事件驱动。

#### 8.4.2 正常与debug解码分开

`decodeXxmResponse(raw, {tsCode, period, debug, decodeDebug?, check})`新增在现adapter.ts：接unknown，不直接类型断言为成功。检查根和嵌套字段集合、值类型、正式r4版本/hash、period/标的、合法时刻、排序唯一、数值有限/正收盘、state-direction关系、meta范围/count、source/dataStatus及EMPTY约束。普通没有历史ID，不能要求不存在的历史数组为[]，也不能跳过正常检查。

`buildXxmViewModel`消费已解码的正常数据和真实DetailChartPoint，保留现逐时刻close/dif/dea/hist严格相等及indicatorVersion校验。不得用显示精度比较、容差、重算、补值。

当debug=1：要求decodeDebug已由动态模块提供；先完成正常检查，再调用`decodeXxmDebug`检查辅助对象，按time/id与正常points/events精确配对，补齐本窗口引用的更早历史。按§5.3迁结构考核/锁死/消失及恢复前后记录关系检查，不要求所有历史形成事件都在可见窗口，但被引用的记录必须存在。错参照、悬挂ID、重复ID、越过computedThrough、错方向、错结束原因均拒绝整份识别结果，不保留旧三角或把失败当EMPTY。普通/debug任一不合格仍保留正常K线。

`XxmLayerUi`正常导出XxmLayerStatus与XxmSignalDetails。简要详情含“顶底识别·r4”、当前状态、当根事件和对应时间。debug详情renderer仅在debug模块已加载且该响应有合格debugDetail时追加；不补推断原因。

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

`decodeForecastDebug`按§5.4固定字段校验所选B/A、每参照突破依据、下一根条件及其精确区间、未决精度区、一步EMA和六字段参照。已有DULL/B且A未算时，只接受“近参照失效”的条件事实，不接受“总体钝化必定消失”；STRUCTURE原参照破则直接失效。删除旧P/C关系树、20步表达式、等待、仅BOTTOM的NextBarOutcomes和ZERO_RESET校验，不能把旧数组留空作兼容。前端不求价、选参照或从几条记录推断规则，普通card只消费后端最终display及必要适用/失效文字。

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
| `xxm/markerGeometry.test.ts` | 正常最小event即可绘所有事件，不依赖debug字段；不改变原颜色/位置/连线/拥挤规则 |
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
| `rearm_discrimination.py` | 删除旧A1基线对账和模拟runner；仍适用的原价格/DIF边界字面样本迁新回转/锁死测试，旧等待结果只用于拒绝反例。 |
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
| `test_xxm_rearm_discrimination.py` | 旧A1对账suite删除；当根收盘/原DIF边界迁新r4；等待结果改为新回转/锁死用例或旧输入拒绝用例。 |
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
| 当根切换与历史 | 人工A/B价与DIF、零日/缺A/等号/晚合格/结构考核/锁死边界，原DULL事件B保持、activeA；旧锁死结构不撤销 | 唯一正式calculator人工测试，从原r4-v2 R4-18—24迁移 |
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

新规则并入重新安排后的P3，先修识别，再预测，再HTTP与必要前端，P3整批独立验收后才进入P4。普通/debug、生产禁用和最终旧代码清退的既定范围不变。本轮仅完成第1步，后续步骤未执行，准确停点见§15。

### 11.1 保留能力的明确落点

§10出现的“迁移有效能力”按下面落点执行，不能临时增加通用框架或保留旧容器转发：

| 旧能力 | 唯一落点/不迁的部分 |
|---|---|
| 研究r4真实选峰/救援/转折观察 | §7唯一step的可选内存记录及history_disappearance_screen.observe_rows；不入SeriesEntry/HTTP，不保留Observed类/第二份判别 |
| 两位算术 | 最小化`near_first_review.decimal_value/quantize_dif`和`test_xxm_near_first_review.py`；完整类/重放不迁 |
| 人工首次、1%、同根切换、结构考核/锁死和取消边界 | 现`test_xxm_calculator.py`及恢复/输入tests；研究wrapper/旧Spec测试不迁 |
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

独立算术样本只迁当前单步目标仍需要的部分。当前求解预期必须使用§5.4.4 M1—M5及§6.10 PF01—20，不能调用正式预测器生成expected，也不能复用多步入口/目标关系作为当前答案。`coefficients`等纯函数若仍被保留测试使用，必须限定其数学前提；不能作为一般负值/跨零求解器。

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
3. 依§14及§6.10先确认独立预期和测试落点；旧正确安全检查保留，旧等待/累计价格/锁死后撤销预期不再是验收答案。新身份、解析与恢复拒旧必须有正常变化的反例证明不过度拦截。
4. 必须获得对应P3执行授权；按下一节顺序实施，中间只验对应内部能力、不发布混合版本，不擅自进入P4/P5。此前通过结论不能替代本次新规则验收。

### 11.4 P3五步及P4/P5交接

#### 当前代码依据

1. `query_service.py:SeriesEntry`现保存`points/events/structure_records`，`_load_series`聚合新`XxmStep`，`calculator_at`经新snapshot/restore返回截至指定根的独立计算器。第1步已迁完整内部结果、聚合、复制和asOf投影，并移除等待聚合；失败不发布和历史前缀已验收。
2. 当前`IndexDetailXxmQueryService.build`在第1步返回`InternalXxmResponseDto`，先`model_dump_json`计字节；日线和分钟路由再通过FastAPI的`response_model`编码。目标是内部完整模型→正常/debug投影→公开校验→一次编码后返回bytes；不能拿旧完整DTO当新普通响应，或计完一份后再让框架重编码第二份。
3. 当前预测query还从`pendingTopHistoryId/pendingBottomHistoryId`找结构，并把结构一形成直接当`CONFIRMED`、跳过未来日历和预测；也按原hist符号把零柱当无方向。新规则要从同次恢复的有效未锁死结构及逻辑色段取状态；锁死后的普通新段可以NONE，不能据旧STRUCTURE事件跳过新循环。`rearmContext`及其失效文案一起删除，不能只改文字。
4. 当前预测模型同时校验`MAIN_SPEC`和`FORECAST_SPEC`，Python与TS仍有旧20根、等待及固定r2身份。识别hash变更后不能先让预测旧模型或TS旧decoder接收混配结果。两项真实hash和正常/debug目标模型在同一P3完成，再填入前端常量和明确身份的fixture；hash来自完整固定Spec，不是源码SHA，也不由旧响应换几个字段生成新expected。
5. 当前两个TS客户端返回响应对象，两个Hook直接读取它。目标返回`{response, deadline}`时，客户端、Hook、普通adapter/悬停及两个图表工作区同次迁移；不能先换客户端外层返回再等P4改Hook。

#### P3实施步骤、前置与停点

| 顺序 | 开始前必须具备 | 本步必须完成 | 本步验收与下一步交付 |
|---|---|---|---|
| 1 新识别核心及内部结果 | §3代码顺序、§4恢复格式、§5内部记录和§14用例已经review；目标文件引用清单已核 | 原位置替换首次C/D、逐参照曾击穿、同根B→A、顶底1%回转、反色锁死；同步`types/snapshot_validation/spec`、统一`XxmStructureRecord`、`XxmStep.structures`、`SeriesEntry/_load_series/calculator_at`及完整内部模型；清理WAIT及跨色价格撤销。完整Spec确定后生成`xxm-direction-v0.2-r4`的新detector hash | 全部识别case逐根通过；连续/增量/历史前缀/复制/恢复相同；已有正确安全检查不退化。此时仅证明内部识别，不能把旧预测或公开DTO不兼容当作新规则错误，更不能称页面可用 |
| 2 下一根预测内核 | 第1步新识别状态、结构锁死记录、参照资格和clone已经稳定；§6数学及失败语义固定 | 撤销20根与全浮点细分、横盘前缀/中点代表；按§6先前提后边界，先B有解即停止，确无解再A。已有DULL和未锁死STRUCTURE各自求下一根结果；锁死后只进入新循环。严格按§6.1/6.7的函数、内部类型和逐文件去向实施，包括forecast_next.py、单根核验/表达式及纯文字；移除正式旧多步/全float路径，不保留备用入口 | 独立数学/业务边界、零柱、来源精度、整数及取消/超时测试通过，记录数学部分耗时；完整400ms含校准/模型/query/编码须在第3/5步接齐后验收，P4另验真实来源。不能用数学样本提前声称完整预算通过 |
| 3 Python模型、投影、query/API和身份 | 前两步内部事实、下一根结果字段及双Spec内容已固定 | 完整内部/普通/debug模型和`response_projection.py`；query共享一次读取结果，迁缓存/forecastId/display/日历下一端点；三个识别/预测API接受既定debug参数并发送一次编码bytes；移除等待字段与旧多根表达式字段；同步直接Python DTO消费者及新合同人工fixture | 普通/debug公共字段、标签ID、预测文本相等；旧/混配身份拒绝，窗口外关联带齐、asOf不泄漏未来锁死；4秒/400ms/1MiB/32KiB预算包括校验编码；未完成这一项之前，不用旧web通过结论证明新HTTP |
| 4 前端必要合同调用 | 第3步实际双hash和完整正常/debug合同已产生 | 纯TS类型→两个纯debug decoder→普通decoder/adapter→两个apiClient返回`{response,deadline}`→两个Hook读取和最终显示检查→普通悬停与日/分钟工作区调用；同次改受影响fixture。普通路径不静态加载辅助实现 | 类型检查、定向合同/API client/Hook/UI回归、Wealth测试和build；普通无debug字段也可展示。debug模块ready联动、正式本地/生产资格、辅助renderer及研究工具仍留P4，不用固定true或假decoder代替未接入功能 |
| 5 P3整批独立验收并停止 | 前四步全部完成，所有直接消费者同一合同 | 按新§14逐项对账、预测下一根用例、API模型/一次编码/共享读取/输入恢复/前端必要调用/架构及文档检查；记录真实实现hash、数量、耗时和未覆盖内容 | M1—M5/PF01—20及识别独立用例全部对账。未执行P4真实来源/浏览器和保留工具、P5清退的部分逐项列明，不宣称整体产品完成。停止等独立验收，不自动进P4 |

第1—4项“按顺序实施”不允许阶段结束仍保留另一个可运行旧r4策略。开发中间状态不作为可发布产品，不给普通请求添加过渡开关。第3项需要的公开模型草稿必须在第1步修改内部字段之前已经写入本文，不能等编码时自由选字段。若执行中发现新业务边界或§6数学预算无法成立，先停止并说明，不依赖旧模型吞错或原20根路径兜底。

#### P4六步（P3整批通过后）

| 步骤 | 动作与前置 | 结束证据 |
|---|---|---|
| 1 本地/生产装配 | 用既有显式dev/local策略装配三条r4与daily-wave路由，分钟另受原reader可用性；前端资格同步，不把日线绑到分钟Lake | 缺环境/生产/未知值相关API不进入source和算法，显式本地无分钟Lake仍可日线；生产debug不能绕过 |
| 2 页面请求模式 | 在P3纯类型/decoder/client之上接`enabled/effectiveDebug`、动态模块ready和失败；普通路径不import研究执行代码；debug模块失败仍普通请求 | 模块加载中/失败/重试/关闭/切周期/离开和迟到结果反例；普通/debug缓存和序号隔离且同源公共结果相同 |
| 3 辅助详情与核对图 | 按§8接锁死/考核依据、参照和编号；波段核对仍手动开启、独立日期/九转/趋势、四种三角及44px留白 | 默认无研究请求和图层；原数据与右栏日期不被研究时间覆盖；不把故障一起藏进debug |
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
| `scripts/research/index_market/tests/test_xxm_calculator.py`及同主题新的`test_xxm_r4_rules.py` | §14的RC01—69完整逐根业务序列；按case参数化四周期。已有文件保留仍正确测试，新规则按逐项输入与expected改写；不复制计算器生成预期 | 当根C/D、逐参照曾破、A破B有效、零柱、严格等号、B/A/第三个、1%/前0/不累计、反色锁死、多轮结构 |
| `test_xxm_snapshot_validation.py/test_xxm_snapshot_consumers.py` | RC70—72及§4所有字段/引用；from-empty、append、calculator_at、clone都经过真实恢复 | 旧身份/WAIT/NaN/bool/未来日期/终态冒充active拒绝且来件/self不变；合法早前缀、等号/当前价格回升仍能继续 |
| `test_xxm_r4_observation.py` | §7真实执行观察及默认关闭；True/False完整业务结果一致 | 未查A不当失败、原事件参照不改、before/after不混、翻色旧事件方向正确、重复选择和对象共享 |
| `test_xxm_p3_forecast_math.py`及`test_xxm_key_point_forecast.py` | §5.4.4 M1—M5和§6.10 PF01—20；独立Fraction/手算，不由forecast helper生成expected | 合法零/整数边界、近有解A零调用、无解与未决区分、已成结构继续考核、锁后新轮、失败无半结果及400ms |
| `tests/web/test_wealth_index_detail_xxm_api.py`、`test_wealth_index_detail_xxm_forecast_api.py`、`test_xxm_shared_loads.py` | RC73、新普通/debug字面合同、一次编码/同次来源只读一次、真实query调用/缓存/取消及身份 | 拒旧JSON而非改hash；历史point引用终态record合法；旧asOf不泄未来；不重复读、不二次编码、不吞错EMPTY |
| Wealth现识别/预测`types/adapter/apiClient/Hook`测试、工作区/页面测试 | §8合同/迟到/截止时间、普通无debug可展示、同源公共值相同；P3先验必要调用，P4再验动态模式/生产资格 | 不静态加载辅助、不以false诊断隐藏真错、关闭清理、研究日期不影响右栏/预测、生产任何debug不请求r4 |
| 依赖边界/清退/工具 | 根三份架构、Biz不导入research/App/QTF、§10逐文件清退及§11保留工具 | 无旧算法/父类/动态副本/源码SHA保护；保留工具在旧模块缺席时正常人工输入可运行 |

全部字段/分支到case对账见§14.12。人工来源样本只证明对应规则，真实来源核验按下一节；不拿设计数量、mock或旧成绩冒充已执行。M1/M2的175.5/24.5合法零必须纳入回归；不得仅改max_future_bars、扩大时限或删复杂路径来冒充数学正确。

### 12.2 有界真实核验（实施阶段，当前未执行）

- 使用已有隔离本地App办法、原路由和原鉴权、只读来源；不重启共享服务，不通过mock声称真实接入通过。
- 先选择单上证有限日期/已有可用分钟的各周期，记录真实源字段/时区、读取范围、实际根数、响应字节、冷/热/历史/增量耗时及source ID，不补缺值或计算实际MACD。若正式服务需要更长历史，事先注明有界上限和来源，不把报告区间当计算起点。
- 新规则用§14、M1—M5及PF01—20独立预期；不再捕获旧v2或重建双组产品。真实来源另按唯一新r4及有界源字段/日期核验，不把人工测试冒充真实来源证据。
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

每批交付按R01—R22、RC01—73及实际执行的PF01—20逐条记录“代码点/测试/真实证据/未覆盖”，不是只报测试数量。最终完成还须P5删后验证、全部消费者同合同、用户页面review；未完成来源或性能不得宣称整体产品已验收。

## 13. 内嵌编码门禁

以下逐项映射[模块交付通用清单](../../system/module-delivery-checklist-v1.md)的18条。适用范围为已接真实API的指数详情，不恢复市场总览mock/real切换，也不借此修改策略配置中心或其他页面。

| 通用清单 | 本模块适用性及明确要求 | 代码/验收 |
|---|---|---|
| 2.1 交付事实链 | 适用；产品/技术v1→本文→原API合同→实现→测试/页面review；现页面/用户四种画法为视觉事实 | §0、5、8、11—12；不重做Figma、不用历史图覆盖当前界面 |
| 2.2 后端事实归一 | 适用；源原MACD、唯一r4、内部完整后投影 | §2—7；前端不自行选峰/算结构 |
| 2.3 状态机 | 适用；NONE/DULL/STRUCTURE、未锁死/已锁死/已消失结构及研究区间closed分别表达；新流程没有WAITING | §3—5、8、22；旧等待仅作清退和拒绝旧输入反例，另验加载/EMPTY/DELAYED/错误 |
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

本节定义已确认的r4识别规则用例；RC01—69业务序列及RC70—72内部工程验证已实现并执行，RC73只完成内部模型部分，公开HTTP/前端留后续。准确成绩见§15，不以本节设计数量替代执行证据。没有运行真实行情、r2对照、预测器或收益/软件准确率验证。预测的下一根求边界、400ms预算及页面接入另按其章节实施。

### 14.1 人工输入、结果和覆盖方式

每条输入写为`(C,D,H)`：C为当根收盘，D为当根原始DIF，H为源MACD柱值；正红、负绿、0中性。DEA固定写入独立人工夹具，按`DEA=D−H/2`使柱恒等式自洽，不能由待测识别器生成。以下输入专门验证判别条件，不宣称能由同一段真实收盘的EMA递推得到；真实来源/EMA一致性仍由原接入验收负责。

`t1、t2……`是当前用例的顺序完成K线。实现测试时使用固定字面交易日期`2023-01-03、04、05、06、09、10、11、12、13、16、17、18`依次对应；日线时间为日期，60/90/120分钟人工算术样本分别使用这些日期的`15:00:00+08:00`。这些分钟样本只验证相同业务内核，不冒充覆盖每个盘中端点的完整性验收。

每个业务case均在day/m60/m90/m120四个周期核对同一识别语义。测试预期采用本节独立字面值及手算不等式，禁止先运行计算器、旧r2或新r4再把输出当expected。本文“事件”描述业务事实，不提前发明公开API枚举；编码时必须映射到同次已确认的事件/事实格式。

每根都断言：本根业务事件、普通状态和方向、活动参照、当前色段及有色根数；出现结构时还断言结构发生根、锁死根或失效根及关联。无事件不等于未检查；锁死不等于新色段仍保留旧普通STRUCTURE。明确禁止重复首次钝化、先取消后删事件、伪造锁死、取消后同根又首次钝化、旧结构在锁死后被撤销。

相等有两种不同含义，不能合成一个检查：首次价格/DIF仍严格比较；`D==参照DIF`不满足当根首次背离，但也不是“曾严格击穿”。因此后续恢复严格背离仍可首次钝化。只有真正严格突破才使该参照在当前逻辑色段永久失效；已经钝化时等于参照不因突破规则消失。

### 14.2 公共人工前缀（均从空状态逐根输入）

前缀是为减少表格重复，不能把一个带待测函数输出的snapshot当作初始夹具。

| 前缀 | 完整字面输入顺序 | 独立预期 |
|---|---|---|
| `T` | `(100,200,2);(90,0,-2);(101,100,2);(102,100,2)` | t1旧红段B仅1根，允许成为历史；t2真实反色。t3当前红段1根无钝化；t4当前红段2根、C102>100、D100<200，首次顶部钝化B。 |
| `B` | `(100,-200,-2);(110,0,2);(99,-100,-2);(98,-100,-2)` | t3当前绿段1根无钝化；t4首次底部钝化，旧谷B价100/D−200。 |
| `TS` | `T;(103,99,2)` | t5相邻DIF100→99，差1恰为1%，顶部结构形成，未锁死。 |
| `BS` | `B;(97,-99,-2)` | t5相邻DIF−100→−99，回升1恰为1%，底部结构形成，未锁死。 |
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
| RC-03 红零绿 | `T;(103,100,0);(90,99,-2)` | t5仍顶部钝化、红段count=2；t6真实翻绿才结束旧红段，旧段end=t5、不含t6；同根确认顶部结构并锁死，新绿段count=1。 |
| RC-04 绿零红 | `B;(97,-100,0);(110,-99,2)` | t5仍底部钝化、绿段count=2；t6确认底部结构并锁死；旧绿段end=t5，新红段count=1。不能将零视为提前反色。 |
| RC-05 已够根数后零日首次 | 顶：`(100,200,2);(90,0,-2);(99,100,2);(99,100,2);(101,100,0)`；底：`(100,-200,-2);(110,0,2);(101,-100,-2);(101,-100,-2);(99,-100,0)` | 双方t4已有两根有色柱但当根价格不合格；t5零日价格合格，当天仅首次钝化B，count仍2，不追加结构、不锁死。 |
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
| RC-43 前DIF为0不触发1% | 形成反例：从空`(100,-200,-2);(110,0,2);(99,-1,-2);(98,0,-2);(97,1,-2)`。回转反例：顶`T;(103,0,2);(104,1,2)`；底`B;(97,0,-2);(96,-1,-2)` | 形成反例t4首次底钝化，t5前值0不触发1%结构，仍钝化。回转反例t5先形成结构、其DIF为0；t6以前值0为基数，不触发1%回转，仍结构。不能把门槛0当任意差都成立；颜色由H判断，不由DIF正负决定。 正常变化对照：取本行“形成反例”前4根，再追加`(110,0,2)`；t5虽前DIF=0，但真实翻红独立确认底部结构并当根锁死，不能把前值0保护误用到真实反色。 |
| RC-44 相邻根含零柱，不跳根 | 从空`(100,-200,-2);(110,0,2);(99,-100,-2);(98,-100,-2);(98,-100.5,0);(97,-99.4,-2)` | t5零根仍钝化；t6必须比较−100.5→−99.4，回升1.1≥1.005，形成结构。若错误跳过零根取−100→−99.4仅0.6，会漏报。 |
| RC-45 活动参照等号与突破 | 顶`T;(103,200,2);(104,200.01,2)`；底`B;(97,-200,-2);(96,-200.01,-2)` | t5等于原参照仍保留钝化，不换A不取消；t6严格突破才取消。本轮不可再回用该参照。 再加双参照保持对照：顶`ABTD;(132,200,2)`、底`ABBD;(68,-200,-2)`，t7仍DULL/B，无新事件、不切A；与RC-24首次B等号选A不同，不能在已有钝化时重走首次选参照。 |
| RC-46 顶部结构回转恰1% | 从空`(100,200,2);(90,0,-2);(101,102,2);(102,102,2);(103,100,2);(99,101,2)` | t4首次顶钝化；t5结构；t6D100→101恰1%，退回顶部钝化，保持原参照；当天价格99不阻碍。原结构不再作为有效未锁死结构，不产生等待。 |
| RC-47 底部回转不再等待价低 | 从空`(100,-200,-2);(110,0,2);(99,-102,-2);(98,-102,-2);(97,-100,-2);(101,-101,-2)` | t4底钝化；t5结构；t6D−100→−101回落恰1%，直接退回底钝化；虽然C101>100，不生成WAIT/重新激活记录，不清空原参照。 |
| RC-48 不足1%回转仍结构 | 顶`TS;(104,99.5,2)`；底`BS;(96,-99.5,-2)` | t6反向变化0.5<0.99，结构保持且未锁死，不能用价格新高/新低单独撤销。 回转也不能累计：顶`TS;(104,99.6,2);(105,100.1,2)`，底`BS;(96,-99.6,-2);(95,-100.1,-2)`；t6变化0.6<0.99，t7变化0.5<0.996，仍保持STRUCTURE。虽然与t5相比累计变化1.1已超过0.99，也不能回钝化。 |
| RC-49 同段反复结构与钝化 | 顶`T;(103,99,2);(99,100,2);(104,99,2);(98,100,2)`；底`B;(97,-99,-2);(101,-100,-2);(96,-99,-2);(102,-100,-2)` | t5结构→t6钝化→t7结构→t8钝化，均原参照；每次以前一根实际DIF为基数，不重新要求价格突破，不反复首次activation，不把仍未反色的任一次结构当锁死。 |
| RC-50 已有结构直接击穿 | 顶`TS;(104,201,2)`；底`BS;(96,-201,-2)` | t6先判断原参照被严格突破，直接从结构取消；不先退钝化、不生成中间DULL，不先建立等待后再取消。 |
| RC-51 双参照失效后回升也无用 | 顶RC-34后加`(133,100,2);(134,99,2)`；底RC-34底后加`(67,-100,-2);(66,-99,-2)` | 新增两根均NONE，没有新钝化；当前看似价格/DIF好转，不复活本段已失效的B/A，不用第三段。 |
| RC-52 零柱可转折和回转但不锁死 | 顶`T;(103,99,0);(99,100,0)`；底`B;(97,-99,0);(101,-100,0)` | t5零日形成结构，t6零日达到1%回转直接回钝化；有色count保持2，均未锁死、未分段，无WAIT。 |

### 14.7 结构锁死与下一轮参照（53—64）

锁死的是当根仍有效或当根刚确认的结构，不能复活已经消失的旧结构。锁死事实必须具有可核对的发生根和锁死根；字段/编码形式遵循本轮后续实现LLD，不在测试设计中伪造公开枚举。新反色根属于新色段。

| case | 前缀/完整追加输入 | 逐根结果及必须排除的错误 |
|---|---|---|
| RC-53 翻绿当根形成并锁死顶部 | `T;(90,100,-2)` | t5相邻DIF没有反向变化，但真实翻绿独立确认顶部结构，并在同一根锁死；仅一条结构形成事实，不再等第二次翻色或补1%条件；新绿段count=1。 |
| RC-54 翻红当根形成并锁死底部 | `B;(110,-100,2)` | t5同根确认底部结构并锁死；新红段count=1；旧绿段极值不含C110。 |
| RC-55 先成结构后翻绿锁死 | `TS;(104,98,-2)` | t5形成未锁死；t6第一次真实翻绿且原参照未破，锁死t5结构。t6不重复形成一条顶部结构，不让新段NONE抹掉锁死事实。 同根顺序反例：另用`TS;(104,100,-2)`，t6相邻DIF向上1已达到回转门槛0.99，但真实反色且未破原参照，仍应锁死t5结构，不先退DULL。 |
| RC-56 先成结构后翻红锁死 | `BS;(96,-98,2)` | t5结构；t6锁死。尽管反色根C96低于旧结构段最低C97，也不能使用已取消的价格撤销规则否定当根有效结构；先按DIF/结构既定条件确认有效，再锁死。 同根顺序反例：另用`BS;(96,-100,2)`，t6向下1已达到回转门槛0.99，仍优先真实翻红锁死，不先退DULL。 |
| RC-57 翻色同根参照破则不锁死 | 顶`TS;(104,201,-2)`；底`BS;(96,-201,2)` | t6优先原参照突破，直接取消；不锁死、不补color_flip结构。与RC-55/56形成正反对照。 |
| RC-58 结构后持续零不锁死 | 顶`TS;(104,99,0);(105,99,0)`；底`BS;(96,-99,0);(95,-99,0)` | t6/t7仍为原逻辑段、结构保持未锁死；不能因新收盘高低价或零柱误锁死/撤销。 |
| RC-59 顶部考核期价格破不单独撤销 | `TS;(104,98.5,2)` | t6价格104高于结构时段最高103，但DIF继续向下、未破旧峰200、未反色，仍维持未锁死顶部结构；不报历史价格撤销。 |
| RC-60 底部考核期价格破不单独撤销 | `BS;(96,-98.5,-2)` | t6价格96低于结构时段最低97，但DIF继续上升，保持未锁死底部结构；不因收盘新低撤销。 |
| RC-61 锁死后再破价格不撤销 | 顶`TS;(104,98,-2);(105,97,-2)`；底`BS;(96,-98,2);(95,-97,2)` | t6锁死旧结构；t7价格继续突破旧结构极值，也不生成旧结构消失/历史撤销。旧锁死根和原参照不得变化。 |
| RC-62 锁死后旧参照DIF突破不撤销 | 顶`TS;(104,98,-2);(150,201,-2)`；底`BS;(96,-98,2);(50,-201,2)` | t6已锁死，t7即使DIF越过旧结构参照±200，也不能撤销旧结构或改其锁死时点。新段按自己的参照独立判断；本样本新方向没有合格首次价格条件。 |
| RC-63 旧段成为新近参照 | 顶`TS;(90,0,-2);(110,95,2);(111,96,2)`；底`BS;(110,0,2);(90,-95,-2);(89,-96,-2)` | t6锁死旧结构并开始反色段；t7再翻色时，刚结束的原结构色段已是最近同色B。顶B价103/D100，底B价97/D−100；t8首次新钝化引用这个B，不再引用更早价100/D±200。旧结构锁死事实仍保留。 继续完成第二轮：顶再追加`(112,95,2);(100,94,-2)`，底再追加`(88,-95,-2);(100,-94,2)`；t9相邻变化1>=0.96形成第二轮结构，t10首次反色锁死第二轮。两轮形成/锁死时间、事件ID和原参照都保留，不能只存最后一个锁死结构或覆盖第一轮。 |
| RC-64 已失效结构不复活；新段可新判断 | 顶`TS;(104,100,2);(105,201,2);(90,100,-2);(106,100,2);(107,99,2)`；底`BS;(96,-100,-2);(95,-201,-2);(110,-100,2);(94,-100,-2);(93,-99,-2)` | t6先回钝化，t7原参照破而取消；t8虽真实翻色，但没有当时有效旧结构/钝化可确认，不锁死或复活t5旧结构。t9再翻回，t10依新完成同色段作近B而首次新钝化：顶B价105/D201，底B价95/D−201。本轮失效记忆不能跨到新逻辑段阻止新判断；历史t5形成、t6失去结构、t7钝化消失事实保留。 |

### 14.8 反色优先级、已选远参照和零柱失效（65—69）

| case | 前缀/完整追加输入 | 逐根结果及必须排除的错误 |
|---|---|---|
| RC-65 已钝化翻色同根击穿 | 顶`T;(90,201,-2)`；底`B;(110,-201,2)` | t5进入本根前为钝化；本根既真实反色又严格突破原B，必须先取消原钝化，不产生color_flip结构、不锁死。新反色段count=1；不得因首次反色优先锁死已失效对象。 |
| RC-66 已选A后A被击穿 | 顶RC-27顶序列后追加`(133,301,2);(134,190,2)`；底RC-27底序列后追加`(67,-301,-2);(66,-190,-2)` | t6活动参照A；t7突破A，直接取消、不救援第三个；t8虽价格仍越过B/A、DIF回到可背离的范围，但两个参照本轮都已被严格突破，不能回B或A、不重新钝化。原t6首次事件参照仍A。 |
| RC-67 零柱原参照破也处理 | 单参照顶`T;(103,201,0)`，底`B;(97,-201,0)`；两参照顶`ABTD;(132,201,0)`，底`ABBD;(68,-201,0)` | 单参照t5取消钝化；两参照t7当根B失效、A完整合格，切A保持钝化且不新增消失/首次钝化事件。四个变体均不增加有色count（仍2）、不分段、不锁死。零柱不代表跳过DIF突破。 |
| RC-68 未够两根时零柱击穿也记忆 | 顶从空`(100,200,2);(90,0,-2);(101,100,2);(102,201,0);(103,100,2)`；底`(100,-200,-2);(110,0,2);(99,-100,-2);(98,-201,0);(97,-100,-2)` | t3当前有色count=1；t4零柱使B本轮失效，但此前尚未钝化，不伪造取消事件、count仍1；t5才有两根有色柱，DIF虽回升/回落到合格范围也不能首次使用B。不能等根数满2后才开始记录参照击穿。 |
| RC-69 已钝化价格恰等门槛仍保持 | 顶`T;(100,100,2)`；底`B;(100,-100,-2)` | t5已有钝化，当前价格恰等B价格100，DIF未破且没有相邻转折，保持原参照钝化，无新事件；与RC-18首次价格等号不合格明确区分。 |

### 14.9 输入、内存与消费者配套回归（70—73）

这些是识别规则的工程保护，不新增识别算法或触发源。不以模拟输入替代源接入、API/页面或性能验收。

| case | 独立输入与操作 | 必须断言 |
|---|---|---|
| RC-70 输入拒绝与正常反例 | 对`T`的t5分别给completed=false、重复/逆序时间、C0/负数、C/D/DEA/H为NaN/Infinity、bool冒充数值、缺失字段；另给正常有限微小数值及合法相等DIF | 非法根在更新前拒绝，原对象、之前返回事件和锁死事实不变；正常小值/相等值不误拦。日期校验与真实日历完整性分属输入和源接入，不能用周末人工根证明交易日完整。 锁死后的错误输入另以RC-55或RC-61为前缀逐项重复，核对已有形成/锁死时间与原参照不变，不能仅在T尚无锁死记录时作空断言。 |
| RC-71 连续与恢复一致 | 用RC-49和RC-63分别在首次钝化、未锁死结构、锁死点前后分割；在新独立实例恢复合法内存副本继续；另分别破坏参照身份、锁死先后关系、NaN、记录关联 | 连续与恢复的每根业务事实、参照、时间一致，实例不共享可变对象；错误副本全部验证完之前不替换旧对象，失败不污染原状态。锁死后恢复不得重新允许旧结构撤销；失效参照记忆在恢复后仍存在。无磁盘恢复文件。 失效记忆必须使用真实含击穿的人工前缀验证：RC-16/17在t3严格突破后切开恢复，再输入t4/t5恢复一侧的DIF，仍不得钝化；RC-66在t7远参照也突破后恢复，再输入t8仍NONE，不能恢复后丢失B/A本轮失效事实。 |
| RC-72 前缀与历史查看无未来信息 | 用RC-55、RC-61、RC-63分别截至形成根、锁死前一根、锁死根、新轮钝化根查看；再追加未来输入；窗口左边裁去旧参照，但保持同一完整前缀来源 | 形成时不能预知未来锁死；历史截至锁死前仍呈未锁死，锁死后事实不变。已返回旧结果不被追加原地修改；历史查看用该前缀状态，不能读末尾锁死信息。页面窗口起点不改事件、参照或编号。 |
| RC-73 新事实的合同与显示一致 | 以RC-49、RC-50、RC-55、RC-61业务字面事实构造后续正式接口验证材料，再走真实序列化/解码/展示；加入旧WAIT/历史价格撤销的反例材料 | 形成与锁死时点可区分；结构回转显示回钝化，不显示等待；直接参照破不插入中间钝化；锁死后不显示旧结构消失。新旧规则身份/缓存不得混用，不以隐藏后端错误事件作修复。旧WAIT专属入口和字段按后续明确的新合同清退，通用安全校验保留。 |

### 14.10 规则到case的对账表

| 已确认规则 | 必须覆盖的case |
|---|---|
| 只用完成根/有限合法值/日期顺序 | RC-70，另沿原源接入测试 |
| 真实反色分段、零中性/不计根、不借未来颜色 | RC-01—06、RC-10、RC-44、RC-52、RC-58、RC-65、RC-67—68 |
| 历史极值独立日期、并列保持、反色首根不进旧段 | RC-02、RC-07—10、RC-63 |
| 首次同根C/D、严格等号、第二有色根可首次 | RC-05—06、RC-11—15、RC-18—20 |
| 本轮严格击穿使该参照永久不可回用 | RC-16—17、RC-20、RC-27、RC-34、RC-36、RC-45、RC-51、RC-66—68、RC-71 |
| TOP正DIF、BOTTOM不加负号、历史单根保留 | RC-21—24 |
| 最近B优先、A备选、两段上限及双价格门槛 | RC-24、RC-26—30、RC-35—37、RC-63 |
| 已钝化B失效当根切A、原事件参照不改 | RC-31—36、RC-66—67 |
| 既有钝化保持不再要求首次价格门槛 | RC-38、RC-42、RC-45、RC-49、RC-69 |
| 相邻实际DIF1%、含等号、不累计、前值0和前零根 | RC-25、RC-39—44、RC-46—49、RC-52 |
| 顶底结构回转统一回DULL，无WAIT/再激活 | RC-46—49、RC-52、RC-73 |
| 原参照破优先于回转/锁死，STRUCTURE不救援 | RC-37、RC-50、RC-57、RC-65—67 |
| 首次反色有效者锁死，同根形成也可锁死 | RC-03—04、RC-53—57 |
| 考核期不按价格单独撤销；锁死后不可追溯撤销 | RC-48、RC-58—62、RC-71—73 |
| 下一轮近峰谷推进、旧结构不能复活 | RC-63—64 |
| 内存恢复、因果、消费者一致且不落盘 | RC-70—73 |

### 14.11 实施时的验收要求与本轮停点

1. 本节73组case（69组业务、4组配套；RC26含A失效/B有效子样本）是规则目录，不等于实际测试数量。已实现用例逐case引用编号并保留独立输入/预期；当前执行覆盖和未验公开部分见§15。
2. 将每条case实际执行的所有追加根都纳入断言，不能只比较最后状态。失败时报告case、根位置、参照、C/D/H及实际事件；不得把旧r4/r2结果自动写成新expected。
3. 首次钝化、同根切远、结构形成/回转/直接失效、锁死及新轮参照分别有正反例。任何规则若改动，必须能指出本节哪条应通过、哪条必须拒绝，不以“已有测试总数很多”替代覆盖。
4. 原始案例与旧报告保留为历史，不重写旧运行结果。旧测试中跨根借价格、锁死后价格撤销、底部等待的expected必须按本轮确认逐项替换，不能把这些旧expected继续当新验收标准；原有限值/恢复不污染/取消清理等正确工程目的仍保留。
5. 本轮仅完成P3第1步识别核心、内存恢复及完整内部结果；人工用例和独立审计见§15。未开发预测、公开API/前端或清退，未运行真实行情、整链性能或浏览器验收；不提交/部署、不自动进入第2步。


### 14.12 编码分支、函数和用例逐项对应

| 执行位置 | 必须对应的既有case | 必须断言的禁止项 |
|---|---|---|
| 输入、开头零、首次非零建段 | RC01、06、10、70 | 不借未来颜色、不改变旧对象、不在新方向首根首次钝化 |
| 同色/零更新各自极值与计数 | RC02、05—10、44、52、58、67—68 | 零不计数/锁死，日期并列不漂移，反色根不进旧段 |
| 首次资格与每个ref曾破 | RC11—25、27—30、51、66、68、69 | 不借旧C、当前D不能替代曾破记忆，等号不当严格破 |
| B先A后/仅两个 | RC24、26—30、35—37及下列新增样本 | 不按强弱、不查第三个、一个ref破不使另一个失效 |
| DULL保持/救援/取消 | RC31—38、42、45、49、66—69 | A次根才合格不抹前根取消；STRUCTURE/翻色不救援；不改原事件 |
| 1%形成/回转 | RC25、39—44、46—49、52 | 当根首次只DULL、不复查C、不累计、不跳零、不WAIT |
| STRUCTURE原ref破优先 | RC37、50、57、65 | 直接CANCEL，不中间DULL，不同根再首次 |
| 真实反色与锁死 | RC03—04、43、53—65 | 先原ref破、再锁；已有结构不重复形成；旧死结构不复活 |
| 结构终态、新轮ref推进 | RC49、55—64、71—73 | 旧LOCKED/DISAPPEARED不会被覆盖；第二轮有新id/记录 |
| 恢复/增量/asOf/消费者 | RC70—73 | 无未来终态、无共享对象、错副本不污染、正常早前缀不误拒 |

上述方法对应§3.10。每个business case四周期逐根执行，必须覆盖当前状态NONE/DULL/STRUCTURE与同色/零/反色三种柱情况；不可达状态由恢复/输入反例拒绝，不凭空补一条业务分支。

| 旧状态/柱 | 必查事实与互斥结果 | 必须抓住的反例 |
|---|---|---|
| 开头无段/零 | 仅previous/processed推进，无未来方向 | RC01/70 |
| 首次非零 | 新段count1，NONE | RC06/10/11/12 |
| NONE/同色或零 | count、TOP正D、近价、B后A当根C/D及曾破；仅首次DULL | RC05/06/11—30/51/66/68 |
| NONE/反色 | 旧段归档，新段count1；不复活旧结构 | RC10/23/64 |
| DULL/同色或零 | 未破→1%形成或保持；B破→当根A完整资格或取消；A破→取消 | RC31—45/52/66—69 |
| DULL/反色 | 原参照破→取消；未破→color_flip形成且锁死；无远救援 | RC03/04/43/53/54/65 |
| STRUCTURE/同色或零 | 原参照破→直接取消；未破→1%回DULL或保持 | RC37/46—52/58—60 |
| STRUCTURE/反色 | 原参照破→取消不锁；未破→原结构锁死、不重复形成 | RC55—57 |
| 任一锁死历史/以后任意根 | 旧终态不可修改；新段按自己规则运行 | RC61—64/71—73 |

### 14.13 新记录、恢复、查询与前端配套断言

以下作为RC70—73的明确子样本，不改变原编号或声称新增测试已执行：

- RC70：输入拒绝必须发生在修改任何本根进度前；分别从空、DULL、STRUCTURE及已存在锁死历史的结果开始验证。不能只测空对象“未变化”。再在本根事件/结构已构造后、step发布前故意触发内部校验失败，必须证明整个self进度、根前记录及此前输出未变化，不能只验证输入早拒。
- RC71：在RC16/17首次前已破、RC19/20首次仅相等后再严格背离、RC66远处也破之后分别snapshot→restore→追加表中恢复价/D；应分别保持本轮失效、允许合法严格背离、两个均不可回用。另从RC45的t5等号保持状态恢复，追加其t6严格突破根必须CANCEL，不能误判“恢复背离”。快照旧pending/WAIT额外字段、history缺键/含"0"或"2"/使用整数键、缺六字段参照日期、LOCKED/DISAPPEARED伪装activeStructure、错形成事件/id/参照/时点均拒绝。合法历史单根/零日/当前收盘已回历史价内侧、更早前缀仍可恢复，不误拦。
- RC71连续/恢复完整结果：保留分割前已取得steps及结构聚合，恢复后追加steps，和从空连续算逐项一致；不要求有界snapshot凭空重建全部旧事件。主动把同id终态改回ASSESSING、改其形成/锁死时间或原参照必须在聚合层失败。
- RC72：分别以RC55/56锁死根前后和RC47回转根前后为asOf，早根投影为ASSESSING且无未来终态时间，晚根终态正确。此前已经返回的对象不变；最新缓存不能改变较早calculator_at。RC63两轮结构均保留，不能仅存最后一条。另固定RC55/56的来源修订反例：顶仅把t5收盘103改104，DIF99/H2不变，新结构priceExtreme必须104、旧返回记录仍103；底仅把t5收盘97改96，DIF−99/H−2不变，新极值96、旧仍97。标签及形成/锁死时间不变，新entry必须从空重建，不受旧终态限制、不混用旧结构记录，旧entry和已返回对象保持不变。再在候选calculator成功step之后故意让结构聚合/完整校验失败，必须丢弃候选entry、缓存仍指旧entry且无半份返回；不得错误要求已丢弃的局部calculator回滚。
- RC73：普通无debug的合法结构事件、debug完整结构及全部关联均有字面样本。历史point.activeStructureId可引用截至查询时已LOCKED/DISAPPEARED的record，只要在该point发生时仍考核；不能因record当前已锁死而拒绝合法历史point。终结根本身activeStructureId必须None，color_flip同根形成锁死也为None。窗口外形成、窗口内终结仍带记录；反向悬挂/未来日期/错方向/重复形成关联/旧字段拒绝。
- RC73前端仅显示普通事件DULL/STRUCTURE/CANCEL与源DIF，旧撤销事件作为拒绝反例；不在绘图层删事件掩盖后端错误。debug渲染使用六字段参照原日期及结构终态；普通未提供debug信息时照常展示正常状态/事件/时间，不推断等待。

### 14.14 本轮交付边界

识别用例已按P3第1步实施，准确覆盖见§15；RC73的公开HTTP/前端、§5.4.4五组预测数学样本及§6.10二十组预测设计仍待后续，不纳本步成绩。完成本步后停止交管理员review，不自动进入第2步或部署。

## 15. P3第1步实施与独立验收（2026-10-30）

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
