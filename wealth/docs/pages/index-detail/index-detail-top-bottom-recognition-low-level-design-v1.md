# 财势乾坤顶底识别低层设计 v1

**当前状态（2026-11-04）：P5第三步整体回归完成。**后端35单元3193项、前端28文件332项及类型/构建通过（含已明确登记的完整证据复用），最终引用、资料、文档及结果/退出审计通过。临时检查漏导入已修正并重验；P5第四步尚未开始，未推送或部署。完整结果与边界见LLD§22.16.6。

更新：2026-11-04（Asia/Shanghai）。**P4已完成并验收收尾。**管理员明确确认“页面验收通过了”，第6步据此登记通过；第1—5步沿用已完成的工程及真实只读证据，不重新采样。工具/测试及验收记录已提交c7c606e81；最终对账见LLD§21.14.14，详细自动结果见§21.14.13。P5第一步静态审计、编码设计及两项审计修正见§22；P5第二步现已按授权完成：先交接后清退，61个代码/测试文件及3282份无用产物已删，221份资料已收敛；879项定向交接通过，删后14个保留模块/工具导入及3583项主题收集通过。第二步已提交f057cefaa；第三步整体回归及最终审计已完成：3193后端、332前端及类型/构建通过，详见LLD§22.16.6。早期1570/1与首错记录仅保留历史身份，不覆盖当前完成状态。本轮不部署或开放生产r4。

P4六步现已全部完成：本地/生产装配、debug动态加载、辅助详情及手动波段核对、保留工具迁移、真实来源/性能验收、管理员页面验收。60/90/120分钟固定清单42组、540业务及126私有请求，96对普通/debug公共结果一致；日线复用原适用证据。204项限定测试是P4已提交证据；P5第二步交接结果独立登记§22.9，没有新增真实请求。性能优化第4—7批及交易助手日期问题继续作为TODO，不转入P5。
依据：[产品文档](../../../../docs/product/wealth-top-bottom-recognition-product-v1.md)、[技术方案](index-detail-top-bottom-recognition-technical-design-v1.md)。本文件只规定当前目标、代码迁移位置、开发顺序和验收，不包含已废弃的开发流程。实施必须使用本文规则和独立用例，不得从旧实验或旧输出推导当前预期。

此前优化批次和阶段停点的历史记录如下；其中“未执行/待验收/本轮”仅描述当时，不覆盖上述最终收尾状态。当前P5范围见产品§11、技术方案§8及LLD§20.4；原失败记录和未覆盖范围仍据实保留。

P4耗时优化专项的静态调查、8方向修改计划和缓存测量方案见[专项方案](../../../../docs/product/wealth-top-bottom-recognition-p4-performance-optimization-plan-v1.md)。管理员已确定先完成容易、明确的精简，再做测量和复杂改造，编码及交接顺序见§0.3。第1批已提交5084ef939，证据见§0.4.7；第2批编码设计及两批文档联合审计见§0.5，开发及438例回归已随70659f763提交；第三批编码设计和开发交付见§0.6，610例限定回归及独立审计见§0.6.10，代码已随4debb8eb3提交；此前第三批测试轮首错停止，见§0.7.9。暂缓优化将来重新启动时仍须先补对应细节并review；当前正式P4剩余设计统一见§21.14，不以新增计时/复杂改造为前置。原失败记录保留，简单结构复算保持；本轮只设计，不重启采样。

## 0. 本轮产物、后续实施范围和硬要求

本文规定r4识别、单根预测及产品接入。三项截图修正、核心/恢复/预测及专项对比已完成并由管理员验收；公开API、必要前端及提交后修复已完成限定工程验收，代码为bebe6f403、11271531c，实际证据见§19—20。原软件内部怎样保存事件仍未被证实，不影响本产品已定规则。

P4第1—4步代码及定向工程验证已完成，e2844c6f7后的工具审计修正继续生效，证据见§21.10。第5步先前日线真实证据及后续三分钟周期固定自动验收均已完成，当前结果见§21.14.13，先前失败仍保留于§21.13.4；管理员本轮已明确确认第6步页面验收通过，P4最终对账见§21.14.14；P5第二步已完成，整批删后回归尚未执行，见§22.9。耗时优化第1批已提交5084ef939，第二批已开发及独立审计，证据见§0.5.10；整批顺序以§0.3及专项§6为准。§21保留原P4实现及后续正式续验要求，不作为重新开发第1—4步或立即恢复采样的指令。P3既有实现直接复用，不重复开发或重跑专项。设计及文档检查不能代替实现、性能或真实验收；§15—17修改前成绩只保留历史用途。

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

当前唯一计算器为v0.4-r4、预测为v0.6-r4，已验收证据见§19。已用CodeGraph codegraph_explore核对XxmCalculator、snapshot_validation及调用关系，再用当前源码补核query_service、forecast_next/forecast_detector、内部schema、前端adapter和专项对比。CodeGraph对通用query_service名称匹配到无关域的结果未作为依据，已回到明确的xxm路径核实。

_advance_followed_structures、forecast_next、snapshot_validation及内部聚合已按§19完成逐根比价、单根段不终止和可重置候选起点修正。本批不重做这些实现；forecast_query_service和Wealth已按§5/§8/§20完成当前公开合同迁移，证据见§20.7；不得恢复旧字段或已删除函数。

Biz仍只依赖自身及允许Foundation；App组合，Wealth消费HTTP；研究工具可调用正式类，业务反向依赖研究、App或QTF均禁止。本次不改变这些边界。接口和TS目标文书同步见§5/§8，但运行消费者仍按原阶段实施，不提前发布混配版本。

### 0.3 P4耗时优化专项的执行顺序（先完成明确精简）

本节约定后续批次的依赖及验收要求。第1批已提交5084ef939，交付证据见§0.4.7；第2批已按§0.5完成编码、定向回归及独立审计，证据见§0.5.10。第3批已按§0.6完成开发、限定回归及独立审计，实际证据见§0.6.10，随后第三批测试轮首错停止见§0.7.9；第4批以后仍按专项§4及本文要求逐批补齐、替换对应旧工程条款后再编码，不能把全部批次当成已具备开工条件。第4—7批现按管理员决定转为§0.11的TODO，暂不开发或测量，不追加真实请求。

| 批次 | 实现范围和先后关系 | 完成要求及后续交接 |
|---|---|---|
| 1 局部精简 | 方向2A：`response_projection.py`移除同次已验证内部结果的dump后重建，缓存交接先完成一次原有完整验证；方向5：`MajorIndexMinsLakeReader._read_complete_history`复用同次prepared清单，不重复逐文件/父目录链接检查 | 公开模型及缓存交接验证、首次文件检查和无prepared直接读取保留；正常/debug、缓存坏对象拒绝、原子替换/首次链接检查的必要回归通过。只删除明确重复工作，不开发计时工具、不做收益采样 |
| 2 目标读取和检查统一 | 方向6/7/8共享`_query_rows`及目标行处理一次完整迁移，删除完整DESCRIBE、其他指数验收和重复SQL聚合；目标实际必需字段/身份/顺序检查在同批完成 | 每次SQL结果按降序检查，分页及完整历史交给调用方时均保持升序，分页limit+1及最早时间游标不变。r4少字段和分钟主图/指标完整字段的全部实际消费者同批回归；不得交付“旧检查已删、必要目标检查未实现”的半套状态。不依赖缓存策略实验 |
| 3 分钟日历缩范围 | 方向3在第2批目标输入上安排日历范围，先取得实际分钟输入再查询适用日期；这是已完成第三批的历史执行顺序 | 保留当时实际前缀、空输入/完成端点、缺行情/休市及早期asOf语义；日线此批不改。测试及诊断后已按§0.9完成第三轮优化读取轮及提交/审计；§0.10.9限定复测已通过；管理员已将第四至第七批暂缓为§0.11的TODO |
| 第三批测试轮 | 插在第三批开发和第四批之间；只复用已有隔离App/计时，普通latest的上证60分钟识别首次/再次及预测首次/再次，最多4次HTTP | 两组各自新App/空产品缓存，首错停止整轮。不得套用旧混合CLI或20次入口。精确调用、观测和退出按§0.7；本轮结果交管理员review后再决定第四批，不自动推进 |
| 第三轮优化读取轮 | 接§0.7—8结果，按§0.9将分钟请求改为N+1000，默认1500，识别/预测/文件/SQL/缓存及历史截止一并迁移 | 开发、限定回归及独立审计已完成并提交4debb8eb3，实际证据见§0.9.10；§0.10.9复测已完成且通过；后续第4—7批按§0.11暂缓；原第四至第八批编号保持 |
| 读取优化后的复测 | §0.9提交/审计后，按§0.10准备上证m60识别首次/再次及独立空缓存预测首次/再次，最多4次，每次前缀≤1500 | 准备及授权执行已完成，4次限定请求通过；结果见§0.10.9，管理员已决定第4—7批暂缓为TODO，见§0.11 |
| 4 测量准备（TODO，暂不推进） | 在包含第三轮优化读取轮的同一实现上补计时位置、通信和退出合同，并实现测量专用观察与人工样本 | 观察不得额外读行情、重复step或恢复已删检查；原预算、进程回收及有界输出要求生效。此批不直接运行真实测量 |
| 5 有界测量（TODO，暂不推进） | m60剩余阶段、方向4两层缓存A/B、方向2B完整历史包装成本；以执行时正式查询实际加载的最新业务日期/完成端点为范围，原2026-10-30只作故障记录 | 两侧共用前三批及第三轮优化读取轮完成后的实现；区分实际计算窗口和返回窗口/asOf范围，同组参数、实际输入/完成端点一致，预测层还核同一目标及日历身份，不为核对另读源。第4批先补原路由及参数，不改N+1000范围或冻结业务时钟。按专项次数执行，首次性能/来源/合同/退出错误停止；只产出结论，不自动修改缓存策略 |
| 6 复杂改造设计（TODO，暂不推进） | 仅对实测证实值得改的方向2B/4补齐最终方案、编码及必要回归；刷新窗口/修订生效策略改变先review | 只有确认同源重算更快才设计取消相应缓存层；差异与波动相当则保持当前策略、不自动取消或扩测。不为完成清单强改缓存或完整事实校验；无须复杂改造时说明依据后跳过第7批 |
| 7 复杂改造实现（TODO，暂不推进） | 只执行第6批已确认方案，逐项回归、独立审计 | 不复制另一套r4，不留兼容旁路，不删完整事实约束，方向1简单结构复算保留 |
| 8 正式P4第5步（已完成，结果§21.14.13） | 不依赖TODO第4—7批；先补现有工具的分钟1500根验收检查、限定测试及审计，再复用已适用日线证据，按m60→m90→m120逐周期执行固定4条命令 | 每周期14组/180次业务请求上限，另42次私有控制请求；首错停止，不自动补测。第6步由管理员页面review，P4通过后才讨论P5 |

第1—3批开发的收益依据是已核实的多余操作被去掉，不要求先专门开发性能测试或提供前后毫秒对照才允许完成。必要正确性回归及原调用次数断言仍用于证明输入/输出/合同/错误处理未跑偏。此前第三批测试轮及单次诊断已按§0.7—8结束；读取优化后4次限定复测已按§0.10.9完成，不补发旧轮、不扩成历史重放或缓存A/B，不声称未经测量的加速幅度。当前正式P4剩余安排统一见§21.14。第4批详细测量准备不作为该小范围复测的前置；正式P4最终预算仍须通过第8批验证，不能以局部精简或本轮少量样本代替整体验收。

上述顺序只授权按批次推进。第1批之外的工程实现描述，在对应批次尚未细化及实施前仍是现状依据，不能因本节排定顺序就宣称已经完成迁移；后续不得同时保留互相冲突的编码要求。

### 0.4 耗时优化第1批：已完成的编码设计与交付记录

本节依据专项§4.2的2A、§4.5及§6第1批，只落实两项已确定精简。第一批已提交5084ef939，2026-11-01开发、定向回归及独立审计结果见§0.4.7。以下“本批保留/不改SQL/schema”等要求只限定已完成的第一批，第二批共享读取正式按§0.5迁移，不要求永远保留旧整表检查。其他第一批保障继续有效；未测量或恢复正式P4验收。

#### 0.4.1 目标、改动清单和边界

| 文件/当前位置 | 本批动作 | 明确保留 |
|---|---|---|
| `src/biz/services/wealth/market/index_detail_xxm/response_projection.py`：两个project函数 | 各删一处对同次内部结果的`model_dump → Internal*Dto.model_validate`重建；增加相应内部模型的轻量类型检查，输入约定写入函数说明 | 原签名、严格bool debug、字段投影、事件显示、编号/display、公开模型验证、返回类型 |
| `src/foundation/clients/local_lake/major_index_mins_reader.py:_read_complete_history` | 只删除取得prepared清单后的第二轮链接检查elif及其异常分支 | 原key/pop、首次枚举检查、参数/数量限制、SQL/schema、升序交付、超时中断及finally关闭 |
| `tests/web/test_wealth_index_detail_xxm_api.py` | 增加识别投影不直接重建内部模型及输入类型反例，复用原合法窗口/事件样本 | 当前普通/debug、同根事件和历史窗口的独立预期 |
| `tests/web/test_wealth_index_detail_xxm_forecast_validation.py` | 增加预测投影不重建和输入类型反例；迁移原F04被修改嵌套对象的检查位置 | 原编号/Wave/范围及四周期合法样本 |
| `tests/web/test_wealth_index_detail_xxm_forecast_api.py` | 扩展实际缓存读取后拒坏对象、两模式及完整验证次数的定向样本 | 原400ms、一次编码、退出检查后发布及异常传播 |
| `tests/test_major_index_mins_reader.py` | 用清单复用的正常/空/不同key用例替换第二轮链接政策用例；补首次检查及消费后重枚举 | 原字段合同、原SQL错误处理、分页/预算及并发读取回归 |

`query_service.py`、`forecast_query_service.py`和两份schema本批不需要修改：当前`_response`已通过构造器验证识别完整模型，`_assemble`已验证预测新模型，预测build命中分支已对缓存副本完整验证。不能为“保留一次验证”再新增一次。`_load_series`的完整历史`_response`属于2B，不能在本批删除。

无新生产文件、helper、配置、参数、开关或依赖；不改r4/Spec、快照、历史查询、价格解、SQL/完整schema验收、日历、数据来源、缓存策略和公开HTTP/TS合同。第二批才改的“其他指数坏行使本次失败”等测试，本批保持原预期。两处精简不改变Biz/Foundation依赖方向，不直接改主图、指标、九转、股票或Wealth代码。

#### 0.4.2 完整验证在哪一步完成

| 路径 | 已有完整验证的位置 | 然后怎样交付 |
|---|---|---|
| 识别普通/debug | `_response`末尾构造`InternalXxmResponseDto(...)` | build原样交project；不在二者之间修改字段，project只投影并验证公开模型 |
| 预测未命中，包括EMPTY/DELAYED/静态结果 | `_assemble`生成全部id/display后`InternalForecastResponseDto.model_validate(payload)` | 原check后交project，不重算id/文字或重复验证内部对象 |
| 预测命中 | `get_forecast`先深复制；build原有`InternalForecastResponseDto.model_validate(cached.model_dump())`完整重验 | 保留这行及其前后check；未通过不得进入project、重新求解或发布替代缓存 |

两个project入口均先保留`type(debug) is bool`检查，再用`isinstance(internal, 对应Internal*ResponseDto)`拒绝dict、公开模型及其他类型，抛ValueError；函数签名不加trusted/skip_validation之类参数。类型检查只核输入种类，不证明嵌套值正确。合法调用方必须在上表位置完成完整验证，不使用`model_construct`、带未经验证update的`model_copy`或修改完的旧模型来伪装验证结果；不另写通用解析入口，也不通过标志关闭校验。

实际删除仅为project函数中直接执行的以下两行，各自删一行，其余公开构造逻辑保持：

```python
internal = InternalXxmResponseDto.model_validate(internal.model_dump())
internal = InternalForecastResponseDto.model_validate(internal.model_dump())
```

**不得把这项改动扩大为删除公开debug验证。**当前`XxmDebugResponseDto.complete_debug`会把公开字段和debug字段还原后调用`InternalXxmResponseDto.model_validate(raw)`，用于验证公开返回的关联；这个调用仍保留。预测公开debug的`_validate_details`同样保留。因此测试只能断言两处project直接重建被移除，不能要求整条debug请求从此只验证一次。

固定计数口径：在合法内部对象已构造好之后，仅包住一次project调用，识别普通对`InternalXxmResponseDto.model_validate`调用0次，识别debug仍1次（来自公开debug校验）；预测两模式对`InternalForecastResponseDto.model_validate`均0次。另对实际预测query的缓存命中路径单独计数：完整内部model_validate恰1次，不能用project计数替代。测试用包装原方法的调用计数，不禁用真实公开验证、不增加生产计时器。

当前环境为Pydantic 2.13.4，已用Context7核对[该版本模型文档](https://github.com/pydantic/pydantic/blob/v2.13.4/docs/concepts/models.md)：传入既有实例默认不能证明全部嵌套字段已重新验证，`model_construct`不验证。缓存路径保留dump成dict后的完整重验，不能改成`model_validate(cached)`或仅检查类型；不改全局revalidate_instances/validate_assignment配置。普通输出不含debug字段，不能指望普通公开验证发现被隐藏的坏原始Wave。

#### 0.4.3 文件清单的具体修改

`history_source_signature`已经调用`_enumerate_partitions(..., file_stats=...)`，复用同次非跟随链接的stat结果生成签名，并按`(dataset, freq, start_date, end_date)`保存至多两份prepared清单；这些均不重写。`_read_complete_history`保持：

```python
parts = self._prepared_history_partitions.pop(prepared_key, None)
if parts is None:
    parts = _enumerate_partitions(...)  # 仍走当前唯一枚举实现
# 后续数量检查、空结果、DuckDB、SQL和资源释放原样保留
```

仅删现`elif parts and (_contains_symlink(...) or any(...is_symlink...))`及对应raise。空清单`()`是有效的已准备结果，不能用`if not parts`或`parts or enumerate`触发第二次发现。`_contains_symlink`仍被首次枚举使用，不能删函数、放宽首次链接检查或改固定根。直接调用没有prepared时仍枚举一次。dataset/freq/起止范围不同不得复用；原pop只消费一次，下一次无准备的调用重新枚举，不能新增跨请求可信清单缓存。

首次枚举拒绝指向根外或根内其他位置的链接，合法普通文件和正常原子替换仍允许。两次API动作之间若外部替换成链接，不再承诺由第二轮检查专门识别；这是已确定的保证变化，不新增读后检查或备用安全读取补回来。不可读文件、原字段/SQL错误继续按现异常失败，不静默跳过。已pop清单后读取失败，不补回清单、不重试；下一次获准调用重新枚举。计时起点、Timer/interrupt、线程池等待和连接释放顺序不变。

#### 0.4.4 调用方及两条旧测试的迁移

CodeGraph explore/callers/impact与源码核对：正式调用方只有识别query.build和预测query.build；直接投影测试见0.4.1。`xxm_page_request_audit.py:_observe`还动态包装project函数，是静态调用图之外的消费者；保留名称/签名/返回模型/输入不变，现包装读取事实后返回同一个公开结果，本批不改工具。

reader的`read_complete_history`及`read_complete_history_pair`都走同一`_read_complete_history`；source.read_minutes依赖pair，研究`xxm_history_projection_audit.py`依赖完整历史入口。主图/指标分页仍走原`_read`，本批不改其SQL或发现流程；九转独立读取器不改。历史研究CLI只做引用审计，不实际运行。

1. 原`test_f04_identity_recheck_does_not_trust_mutated_nested_model_instances`不能继续要求project接收已被外部改坏的对象并负责重验；把这一保障迁到实际预测缓存交接。用合法`following_payload`构造并保存完整缓存，再把缓存内`originWave.count`改为0，分别请求普通/debug，断言build在project前以`XXM_SOURCE_CONTRACT_INVALID`拒绝、无求解/替代发布。原F04其他合法编号和事实测试保留；迁移后删除旧函数的过时投影断言，不skip、不把坏值改合法来迎合实现。
2. 原`test_prepared_history_rechecks_file_links_before_parquet_read`整条测试专门要求第二轮拦截，随保证变更替换为prepared复用测试，不保留制造第二轮链接替换的旧预期。首次枚举拒链接的两条既有测试继续保留，并为完整历史有prepared/无prepared的首次发现路径补正常及拒绝对照。

#### 0.4.5 规则、实现和必要回归逐项对应

以下为本批回归设计，已按§0.4.7实现及执行。新节点统一使用`test_p4_batch1_`前缀，落在0.4.1的现有测试文件，不新建测试框架；预期来自原RC77/93、F02/F04、M1及现Gold字段合同和人工Parquet样本，不由被测函数生成。

| 用例 | 人工输入及检查位置 | 独立预期/实现对应 |
|---|---|---|
| 1 只去直接重建 | 既有合法识别窗口、M1完整预测模型，分别调用两project的普通/debug并包装原Internal.model_validate | 严格按0.4.2的0/1次数；公开验证实际运行，原函数修正前会多一次，不能以mock直接返回成功 |
| 2 输入约定和字段保持 | 两project传dict、错误模型、非bool debug；合法样本配对 | 错类型ValueError；合法普通字段与debug剔除debug后的字段逐项相等，源对象dump前后相等；不新增字段/改值或重新生成编号 |
| 3 隐藏事件与历史 | 原`test_current_public_window_full_events_and_no_future_structure`及公开模型反例 | 同根CANCEL/DULL两事件保留，显隐仍False/True，旧结构及更早asOf无未来终态；损坏公开关联仍被公开debug拒绝 |
| 4 缓存只重验一次 | 先正常M1请求生成合法缓存，再正常命中，两模式各单独用新cache构造场景 | 命中时完整内部model_validate一次，project不再多一次；forecast不再次调用，单次编码及forecastId不变 |
| 5 缓存改坏仍拒绝 | 原numeric/result_id/condition_id坏缓存扩为两模式，另用合法following缓存后改Wave.count=0 | query完整重验拒绝，不走project/求解，不覆盖或删旧条目；业务内容及计量不因失败重写，原LRU策略保持；相应未损坏样本正常命中 |
| 6 原退出及预算 | 原with退出失败、最终JSON超预算、复制/发布失败和取消样本 | 原check/异常优先级和退出后发布保持；不因移除重建提前发布或吞异常。用既有人工时钟故障，不测真实耗时 |
| 7 同次prepared只消费一次 | `tmp_path`内`_write_gold_bars/_write_gold`合法文件；先signature再完整读取，包原枚举/链接检查 | 首次只发现一次；复用阶段不再枚举、调用额外_contains_symlink或逐Path.is_symlink；返回与字面输入一致且升序。旧实现因第二轮调用失败，新实现应通过 |
| 8 空清单和不同key | 空目录先signature；另分别改变dataset/freq/start/end，使用合同合法fixture | 空prepared不重新枚举且不建DuckDB连接；不同key走首次枚举；不能用一次枚举结果包办不同请求 |
| 9 成功或失败后再调用 | 两个独立场景：同一reader成功消费prepared后再次直接读取；另用合法临时文件先signature，在实际_read_complete_history已pop并打开连接后，令第一次_query_rows抛指定IndexMinuteSourceContractError，再恢复该函数并再次直接读取，不补做signature；合法原子替换仍单列正常对照 | 两场景的第二次调用均重新枚举。失败场景按下段固定断言验证无重试、清单不补回及资源关闭，再验证下一次正常读取；替换正常，原signature更新和忽略staging保持。计数只包原方法，不为计数另读文件 |
| 10 首次链接仍拒绝 | 临时fixture在首次发现前已是指向根内/根外的文件或分区目录链接，分别从signature/无prepared完整入口进入 | 仍为来源合同错误；合法普通路径对照成功。全部造错只在tmp_path，不触碰正式Lake |
| 11 原reader合同不变 | 原完整历史投影/超限、分页游标、双源资源和失败等待用例 | max_rows超限拒绝、原字段/NULL/顺序保持；其他指数坏行仍按旧政策拒绝到第2批，不提前改预期；超时仍关闭连接 |
| 12 工具包装仍可用 | 在现投影测试文件新增batch1节点：用合法内部模型进入原`_observe`，分别经其包装后的projection模块识别函数和forecast_query_service模块预测函数调用两模式；另跑原工具缓存方法一次、共享加载及部分包装失败清理节点 | 真实project结果字段与独立原样本一致，退出恢复原函数；该人工样本无请求身份，不冒充真实采样/collector配对验收。三个原工具节点验证各自缓存/共享/清理保障，不能用它们代替新增的project包装调用；不启动页面采样或Node全组 |

文件夹具沿`major_index_mins_contract.py`的GOLD_*_COLUMN_SPECS及现`_write_gold_bars/_write_gold`生产临时Parquet。常量用来核对字段合同；结果独立断言bars三个时点及收盘10.2/10.4/10.6、指标默认时点和DIF0.1/DEA0.2/柱−0.2、合法MA空值，不调用reader生成expected。仅在原默认合法日期使用这些helper，不能因helper有日期参数就假定内部所有日期已随之变化。

用例9的失败场景必须实际进入`_read_complete_history`，不能像现有双源错误等待测试那样替换整个方法。先用合法fixture调用signature并记录枚举次数；仅在_query_rows注入第一次来源合同错误，保留真实连接、schema检查和finally路径。该次读取应原样抛出指定异常，_query_rows只调用1次，pop掉的prepared_key仍不存在，且该次Timer.cancel和connection.close各执行1次；用调用原方法的包装记录，不跳过真实关闭。本次错误之后函数已经返回，测试再显式发起独立的第二次调用，这不是程序内部自动重试。恢复_query_rows正常实现、保持同一reader且不再调用signature，枚举次数必须比上次失败后增加1，返回仍与字面fixture一致、升序；第二次调用自己的Timer/连接也正常释放。signature、失败读取和再次读取的次数分别记录，不把准备时的枚举算成失败时重新发现；所有对象/文件仅在临时fixture内，不改正式来源或在生产代码新增恢复逻辑。

#### 0.4.6 编码顺序、验收和失败处理

1. 先限定工作区和本批文件，保留其他修改；核对上述当前调用方仍成立。先补用例1和7，分别证明原代码存在额外内部重建/第二轮链接检查；这只是必要回归，不新增性能实验。
2. 先改两project及其调用方约定/迁移F04测试，验证合法输出和坏缓存；不动已正确的两个query或公开schema。若新增调用方不能证明已验证输入，停止说明，不能把重验挪到所有调用方制造另一轮重复。
3. 再删reader指定elif，迁移旧第二轮测试，完成prepared/直接/空/key/首次链接，以及用例9真实读取失败退出后再次调用的原合同回归。无SQL/日历或其他方向的顺带修改。
4. 最后做交接及架构复核，逐条用0.4.5对账，原方案/专项和本LLD登记已实现、未覆盖范围；未经管理员review不推进第2批，不自动提交或部署。

后续测试使用现有`.venv/bin/python -B -m pytest -q`，分以下有界组：①预测validation文件和新增投影节点；②reader文件（迁移上述旧测试后完整运行，均为临时文件）；③识别API只选新增batch1、current_public_window、public_and_debug_contracts节点，预测API只选新增batch1、full_m1、bad_cached_full_model、with_exit_failure、final_encoding_and_copy、final_json_encoding及F06/F07节点；④following_query的RC93相关人工节点、P4工具的original_cache_methods/shared_actual_result/partial_observation_setup三个节点；⑤根目录三份架构测试。不要整文件运行含290根计时样本的预测API测试，不跑Wealth全量、真实路由采样、研究CLI、正式数据库或Lake。每组超过60秒停止查因，不无限等待或安装依赖。具体执行节点与参数须在交付记录中逐项列明，不能只给-k通过数冒充全部验证。

本批不新增性能门槛或真实测量，原4秒识别/总预测、400ms预测处理、5秒客户端、64MiB/16条缓存及源20000根/5000分区等预算不变；没有改计时起点，必要校验、编码和退出继续算入原时限。正常/异常/取消沿原finally及锁/连接/线程清理，无结果落盘或中断恢复文件。开发或测试失败保留工作区供排查，不交付半套成功；重新测试从新的临时fixture/cache开始，不续用失败候选，不改预算或旧有效数据。

文档完整性、相对链接、限定diff和引用检查最后执行。此批只能证明减少明确多余操作且相关正确性不退化，不能宣布60分钟已满足4秒或P4第5步通过；正式来源及性能仍留第8批。

开发前文档复审已补齐用例9的失败退出及新调用链路，动态包装入口统一为实际_observe，删除成功响应头未实现的旧描述，并同步专项§9及技术方案§16。开发后的独立审计与实际执行证据如下，设计复审本身不替代这些成绩。

#### 0.4.7 第1批开发交付与独立审计（2026-11-01）

生产改动仅§0.4.1的两个文件：两project删除直接重建、增加内部模型类型检查及函数说明；reader仅删除prepared分支的三行第二轮链接检查。两query、schema、计算器、Spec、SQL、日历、签名生成及缓存策略未改。测试改动仅原定四文件；F04迁到实际缓存交接，旧第二轮链接测试替换为清单复用测试，首次发现链接仍拒绝。

先加入用例1和7再运行原生产代码，共6个参数化样本均因预期问题失败：识别普通/debug内部model_validate分别为1/2次，预测两模式各1次；bars及indicators均再次调用链接检查。修改后这6个样本全部通过。这里验证的是多余操作确已消除，不是性能采样。

| §0.4.5用例 | 实际测试与独立审计结果 |
|---|---|
| 1 只去直接重建 | `test_p4_batch1_signal_projection_validates_only_public_result`普通/debug为0/1次；`test_p4_batch1_forecast_projection_does_not_rebuild_internal`两模式均0次，包装原验证函数实际执行 |
| 2 输入/字段保持 | 两文件的`test_p4_batch1_*_projection_requires_internal_model_and_strict_debug`：dict、公开模型、其他类型均拒绝；0/1/None/文本debug拒绝且先检查debug；合法公共字段相同。用例1和12另核内部对象前后不变 |
| 3 隐藏事件/历史 | `test_current_public_window_full_events_and_no_future_structure`四周期×两方向、`test_public_and_debug_contracts_reject_legacy_bad_types_and_links`及RC93节点通过；同根两事件、False/True显示和历史无未来信息保持 |
| 4 缓存一次完整重验 | `test_p4_batch1_actual_forecast_cache_hit_validates_once`两模式：内部完整验证1次、最终编码1次、不重新求解或发布，结果及缓存事实/计量不变 |
| 5 坏缓存拒绝 | `test_bad_cached_full_model_is_refused_without_solving_again`的numeric/result_id/condition_id×两模式；`test_p4_batch1_f04_cached_nested_model_is_revalidated`的合法/坏Wave×两模式通过；坏值在project前拒绝，未调用solver/put_forecast，条目对象和计量不重写 |
| 6 原退出/预算 | 下表预测组所列退出、编码、F06/F07节点通过，保留人工时钟、取消和错误优先级验证；没有真实计时实验 |
| 7 清单一次消费 | `test_p4_batch1_prepared_history_skips_second_discovery_and_link_checks`的bars/indicators通过：首次枚举1次，读取无第二轮枚举或链接检查；字面时点、收盘及DIF/DEA/柱/NULL均匹配 |
| 8 空清单/不同key | `test_p4_batch1_empty_prepared_history_does_not_rediscover_or_connect`两数据集、`test_p4_batch1_prepared_history_is_bound_to_original_key`的dataset/freq/start_date/end_date通过；空prepared不连接，不同key重新枚举且不消费原key |
| 9 再次调用 | `test_p4_batch1_prepared_history_success_is_consumed_once`及`test_p4_batch1_prepared_history_failure_cleans_up_and_next_call_rediscovers`通过；失败进入真实连接/schema/finally，仅_query_rows抛错，无内部重试，Timer.cancel/connection.close各1次；下一次显式调用无signature仍重新枚举、升序返回且再次正常关闭。原子替换及signature更新既有节点通过 |
| 10 首次链接 | `test_p4_batch1_first_history_discovery_still_rejects_links`的signature/direct×inside/outside×file/partition共8例通过，分别配合法普通文件；原两条分页首次链接测试保持 |
| 11 原reader合同 | reader整文件通过：原SQL/schema、其他指数坏行拒绝、游标、数量/预算、原子替换、双源资源及错误等待不变；本批没有提前采用第2批政策 |
| 12 动态工具 | 两个`test_p4_batch1_*_projection_keeps_dynamic_audit_wrapper`×两模式通过：真实_observe包装调用原project、结果正确且退出恢复函数；无请求身份，不声称collector配对或真实采样通过。另三条原工具节点通过 |

实际执行使用现有`.venv/bin/python -B -m pytest -q`，各组均低于60秒；以下最终组共226例通过，没有skip，没有新安装：

| 组/文件 | 精确选择及参数 | 成绩 |
|---|---|---|
| 投影/合同 | `test_wealth_index_detail_xxm_forecast_validation.py`整文件；`test_wealth_index_detail_xxm_api.py`的`test_p4_batch1_signal_projection_validates_only_public_result`（False/0、True/1）、`test_p4_batch1_signal_projection_requires_internal_model_and_strict_debug`及`test_p4_batch1_signal_projection_keeps_dynamic_audit_wrapper`（各False/True）、`test_current_public_window_full_events_and_no_future_structure`（day/m60/m90/m120×1/−1）、`test_public_and_debug_contracts_reject_legacy_bad_types_and_links` | 62通过，2.90秒 |
| reader | `tests/test_major_index_mins_reader.py`整文件，包括所有原有及上述新增参数 | 111通过，3.51秒 |
| 预测API | `test_wealth_index_detail_xxm_forecast_api.py`：`test_full_m1_normal_debug_cache_and_exact_single_target`；`test_bad_cached_full_model_is_refused_without_solving_again`（numeric/result_id/condition_id×False/True）；`test_p4_batch1_actual_forecast_cache_hit_validates_once`（False/True）；`test_with_exit_failure_never_publishes_forecast`；`test_final_encoding_and_copy_share_original_budget`；`test_final_json_encoding_cannot_exceed_original_budget_or_publish`；`test_f06_unexpected_failure_returns_forecast_error_and_keeps_old_cache`（inside/exit/publish）；`test_f07_final_publication_preserves_known_timeout_and_cancel_errors`（timeout/async_cancel/future_cancel/known）；`test_f06_actual_cache_candidate_failure_releases_lock_and_keeps_members`；`test_f07_real_load_exit_does_not_replace_original_error_with_a_later_timeout`（query/source/async_cancel/future_cancel）；`test_f07_cancellation_inside_cache_lock_is_atomic_and_unlocks`（async_cancel/future_cancel） | 26通过，1.82秒；未选择其余26例，未运行290根计时样本 |
| 历史及工具 | `test_xxm_r4_following_query.py`的`test_rc91_93_all_phases_projection_windows_no_future_fields`（sign±1×flip False/True）、`test_rc93_full_internal_model_preserves_multiple_events_and_original_refs`（sign±1）、`test_rc93_window_does_not_hide_invalid_following_or_rebuild_per_record`；`test_xxm_p4_audit_tools.py`的`test_original_cache_methods_once_and_no_context_passthrough`、`test_shared_actual_result_or_exception_keeps_one_load_and_cache_lookup`（fail False/True）、`test_partial_observation_setup_restores_already_registered_patches` | 11通过，0.35秒 |
| 架构 | `tests/architecture/test_subsystem_dependency_matrix.py`、`test_platform_legacy_guardrails.py`、`test_operations_legacy_guardrails.py`整文件 | 16通过，12.94秒 |

独立审计重新阅读两处生产diff及真实调用方，逐条核对本节12项。CodeGraph explore/callers/impact覆盖query、两project、reader、测试；再用源码补核静态图未完整列出的query导入调用、_observe动态包装及source.read_minutes→pair、历史研究工具消费者。没有新增运行依赖、配置或公开合同变化；首次枚举和缓存交接的完整验证、公开debug关联校验、原check/finally均保留。未发现本批未落地项或需新增拍板的问题。

文档完整性三组检查通过，四文档31处本地Markdown链接目标存在，限定diff空白检查通过；CodeGraph sync/status完成，索引状态为最新。这些检查不代替上述业务回归。

本批仅证明局部精简及上述正确性回归。未访问正式数据库/Lake、未运行研究CLI、全量回测、Wealth全量或页面采样；未测量加速幅度，不能宣布60分钟满足4秒或P4第5步通过。开发结束时停在第2批之前，未自动提交、部署或推进后续批次。管理员随后明确授权提交本批10个文件（2个生产文件、4个测试文件、4份配套文档）；其他工作区修改保留，不推送或部署。第二批本轮只作只读梳理，不编码。

### 0.5 耗时优化第2批：目标读取和必要检查的具体编码设计

本节承接已提交的第1批`5084ef939`，对应专项§4.6—4.8及§10。当前已按本节完成开发及独立审计，实际438例限定回归与两批交接结果见§0.5.10；未读正式源或测量。**三个方向在同一批完整迁移：删除整表检查、只读取目标、补齐必要检查及其调用方，不能分开交付。**第1批§0.4是该批交付记录，其中“保留原SQL/schema”限定第一批；第二批正式以本节迁移共享读取。第1批的投影、缓存完整验证、首次文件检查、prepared一次消费及资源释放继续生效。

#### 0.5.1 目标、文件与不得扩大范围

| 文件 | 本批具体修改 | 原样保留 |
|---|---|---|
| `src/foundation/clients/local_lake/major_index_mins_reader.py` | 两读取入口删除`_validate_combined_schema`调用并删除其唯一实现；重写同一个`_query_rows`，增加本文件私有`_validate_target_rows`；用已执行查询的列元数据检查所用列 | 公共方法签名、请求/page/cursor、字段常量、数量限制、文件发现/signature/prepared、DuckDB资源、Timer/finally及并发等待 |
| `src/biz/queries/wealth/market/index_detail_xxm/source.py` | `read_minutes`在一次循环中对应两源并构造bar；`assert_continuous`删除单独的`sorted(set(actual))`检查 | `read_daily`、日历SQL及参数、`expected_through`、ENDPOINTS、原生bar验证、源范围、完成时点和数据来源 |
| `tests/test_major_index_mins_reader.py` | 增加本节用例；迁移“其他指数坏行必须失败”的旧测试；补必需字段和不同读取用途的成对样本 | 第一批prepared/链接/失败再调用，原分页、原子替换、资源及数量回归 |
| `tests/web/test_index_detail_minutes_api.py` | 用真实临时Gold验证主图、完整指标及原错误码、空结果和返回字段 | 鉴权、环境挂载、支持标的、七种频率及5MiB响应限制 |
| `tests/web/test_wealth_index_detail_xxm_api.py` | 增加两源对应、日历完整性、实际r4少字段链路及日线回归 | 四周期、普通/debug、标签/事件/编号及第一批投影保障 |

生产改动仅上表两个文件，测试仅上表三个现有文件，不新增生产文件、通用解析框架、配置、参数或开关。不要修改计算器、Spec、快照、预测公式、query缓存/发布、公开DTO/TS、前端、股票分钟、九转或成交额独立读取器。`GOLD_*_COLUMN_SPECS`、源指标版本和params_key常量仍是原完整合同，不删除/修改；本批只改变请求中使用哪些字段及如何检查。没有正式数据库/Lake写入、结果落盘、安装、部署或新后台任务。

已核对真实交接：`/minutes`和`/minute-indicators`→`IndexDetailMinutesQueryService`→reader分页；r4识别及下一根预测共用query加载→`source.read_minutes`→reader双源完整历史。`xxm_history_projection_audit.py`和P4观察工具消费原入口/行结构，不改签名或增加字段；本批不运行历史CLI或真实采样。CodeGraph的同名股票/成交额函数不能当作本模块调用方；本批无需让这些独立读取器一起迁移。

#### 0.5.2 输出列、额外列及值检查的逐项约定

`_history_columns`继续验证value_columns白名单、唯一性和四个键，保留原返回顺序。`_query_rows(columns=None)`仍表示该数据集原全部输出列：bars为`GOLD_BAR_COLUMN_SPECS`去掉vwap的11列，indicators为原23列；非None使用现有已检查的columns。不向原入口增加第二种请求模式。

查询内部计算`output_columns`与`read_columns`两个tuple：前者是原调用方应收到的列；后者在前者后按顺序追加尚未存在的必要检查列。indicators始终需要`params_key/indicator_version`，bars不额外读取其他价格列；另读取`filename AS _source_filename`定位行。用原顺序去重，不对字段排序，不SELECT源文件全部列，不用CAST把实际业务列转换成“正确类型”。这些都是本函数局部变量，不能变成分散配置。少字段入口虽允许其他value_columns组合，本批不新增组合或参数；相同字段规则按dataset及实际output_columns应用，不写只认r4四个值的特例。

| 字段/用途 | 查询元数据类型 | NULL和值的具体要求及负责位置 |
|---|---|---|
| 四个键：ts_code/freq/trade_date/trade_time | VARCHAR；bars INTEGER/indicators SMALLINT；DATE；TIMESTAMP（沿原`_normalize_duckdb_type`归一化） | reader目标循环要求非空，代码严格等于已归一化请求，freq严格等于请求；date必须对应所选文件，timestamp日期必须等于date。保留现有时分秒上限15:00:00、非1分钟不接受09:30:00，不新增早盘下限、午休或其他整点限制 |
| bars实际读取的open/high/low/close/vol/amount | DOUBLE | reader仅对output_columns中出现的这些列检查非空及有限；不新增高低价相对关系、涨跌幅或成交量正值要求。r4只读close，不能为了检查未使用open而额外读取它 |
| bars实际读取的exchange | VARCHAR | 仅在output_columns含它时要求非空且不等于空串；不增加交易所枚举或strip规则 |
| indicators的params_key/indicator_version | VARCHAR/INTEGER | 非空，严格等于原`GOLD_PARAMS_KEY/GOLD_INDICATOR_VERSION`；少字段读取也检查，之后若非原输出字段则删除 |
| 完整指标API的observation_count | INTEGER | 原非空且至少1；仅本接口/显式投影需要它时读取检查，不为r4额外读取 |
| MA/BOLL/MACD/KDJ数值列 | DOUBLE | 完整指标API保留原float或None合同及暖机NULL，不在本批新增原接口没有的取值范围限制。r4用到的DIF/DEA/柱值仍由source中的`XxmBar.validate`拒绝None、非有限值，close还必须大于0；不得因精简删此检查 |
| 内部_source_filename | VARCHAR | 非空且能在本次`{str(part.path): part.trade_date}`映射中找到；仅字符串查表，不新增resolve/stat/is_symlink。不进入返回行、DTO、sourceInputId或缓存身份 |

元数据只检查read_columns及内部filename的实际输出名称、顺序、逻辑类型，期望类型依据原合同逐字段取出；不比整张源表的列顺序。**类型保证仅针对本次查询输出，不保证每个原文件的物理列类型都相同。**`_normalize_duckdb_type(str(description[i][1]))`复用原实现，不另造类型映射。TIMESTAMP归一化沿旧函数；本批不增加全局时区政策，r4原有“源timestamp无时区、构造后+08:00”的检查保留。若本次查询实际报告DECIMAL/VARCHAR/BOOLEAN/INTEGER，而该字段期望DOUBLE，必须拒绝；应用层不得先CAST或float(value)把结果转换成DOUBLE后再通过类型检查。

多文件的合并与类型转换由现有DuckDB及输入路径顺序决定。DuckDB若已把后续文件的文本、Decimal或布尔值转换为DOUBLE，cursor.description只会报告DOUBLE，读取器按这个实际输出类型及后续值规则检查，不再猜测原始类型。不能据此宣布逐文件源合同已经通过，也不能为追溯原类型新增文件头/逐文件schema读取、DESCRIBE、额外查询或改用union_by_name。本批不调整原路径顺序来选择有利类型，不新增类型统一/修复步骤；不能转换的源值仍按原错误分类失败。后续source的float构造发生在查询结果类型通过之后，仅沿用原XxmBar输入构造，不得拿它弥补未通过的类型检查。

当前环境DuckDB 1.5.5；已用Context7核对[Python结果列元数据实现](https://github.com/duckdb/duckdb-python/blob/main/src/pyresult.cpp)及[Parquet选列与多文件说明](https://duckdb.org/docs/current/data/parquet/overview.html)。description在空结果时仍用于检查本次实际查询列。它表达本次查询的逻辑类型，不承诺逐个物理文件全schema已验收；不能为这种额外承诺恢复DESCRIBE或逐文件预读。

#### 0.5.3 同一个_query_rows的SQL、参数与错误处理

保留原函数签名。在原读取入口已完成请求/字段/分区准备后，按以下顺序执行：构造output_columns/read_columns及本次文件日期映射→一次参数化目标查询→检查description→fetch结果并转成原dict→一次`_validate_target_rows`→返回。空文件清单仍在原入口直接返回，不连接DuckDB。存在文件但目标无行，仍检查实际投影元数据，再返回真正的[]；不得返回一行NULL占位。

SQL固定采用以下结构；花括号内容仅由原字段白名单生成，代码、路径、游标及数量全部作为参数：

```sql
WITH target AS (
    SELECT {read_columns}, filename AS _source_filename,
           CAST(regexp_extract(filename,
               'trade_date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1) AS DATE) AS _partition_date
    FROM read_parquet(?, filename=true, hive_partitioning=false)
    WHERE ts_code = ?
)
SELECT {read_columns}, _source_filename
FROM target
{optional_cursor_where}
ORDER BY _partition_date DESC, trade_time DESC NULLS FIRST
LIMIT ?
```

1. `paths`仅来自原枚举选中的文件；不能扩大日期/代码/频率范围。start/end已经限定文件日期，不再按行中可能写错的trade_date执行WHERE过滤，否则会把本应报错的目标行藏掉。_partition_date只由已发现路径取出，用于排序及游标，不作为替换真实trade_date的值；真实行的date由目标循环对照文件映射检查。正常数据的排序与返回范围和原实现一致。
2. 无cursor时optional_cursor_where为空，参数精确为`[paths, request.ts_code, request.limit + 1]`。有cursor时使用下式，参数精确为`[paths, request.ts_code, before_date, before_date, before_stamp, request.limit + 1]`，before值来自原_decode_cursor及原归一化校验，不新增cursor版本或字段。

仅在decoded_cursor非None且已通过原归一化校验后，精确沿用现代码构造两个变量：

```python
before_date = decoded_cursor["beforeTradeDate"]
before_stamp = f"{before_date} {decoded_cursor['beforeTradeTime']}"
```

before_date是游标保存的日期文本，before_stamp是日期、一个空格及游标原时间文本；不是只有时分秒，也不使用当前日期。保留原时间文本中的秒和微秒，不截断、不重新格式化或添加/转换时区。SQL仍按已有CAST绑定日期及完整时间，不更改cursor编码/解码和身份范围校验。没有cursor时不读取这些字段，也不添加其参数。

```sql
WHERE _partition_date < CAST(? AS DATE)
   OR (_partition_date = CAST(? AS DATE) AND (
       trade_time < CAST(? AS TIMESTAMP)
       OR trade_time IS NULL
       OR CAST(trade_time AS DATE) <> _partition_date
   ))
```

3. cursor仍严格排除游标当根。NULL或日期与所属文件不一致的timestamp不能借比较结果被丢掉，交给目标循环报错；最后两项只防游标掩盖这些定位错误，不做额外统计或第二轮校验。不属于本次cursor窗口的正常行不再全文件验收；错freq、错版本、坏价格不能放入WHERE先过滤。无cursor时NULLS FIRST保证NULL时间行不会因默认排序沉到探测范围外。
4. 输出列显式列出read_columns及_source_filename；_partition_date不进入输出。regex文本应单独放入普通字符串后插入SQL，或正确转义Python f-string花括号，不得误把`{4}`当格式表达式。保持read_parquet原默认union_by_name=false，不开启会为缺列填NULL的模式，不引入TRY_CAST、补列、补值、UNION或DISTINCT。
5. 去掉原source全量MATERIALIZED、contract全指数invalid_count、integrity的count/count DISTINCT、交叉连接及NULL占位处理。一次正常读取只执行这一条业务SELECT，description来自同一cursor，不另执行schema SQL。分页按原规则扩大分区时允许重新执行新范围的SELECT，每份返回只检查一次，不能承诺分页永远只有一次SQL。

代码过滤的含义必须一致：ts_code值为其他代码、NULL或无法匹配请求的行，不视为本次目标，不能为了检查它们写`OR ts_code IS NULL`。但ts_code这列缺失/类型不符属于本次共同必需列错误，仍拒绝。下文“目标NULL键”指已经按代码匹配的行里freq/date/time为NULL，不要求读取器猜一个无代码行原来属于哪个指数。

执行及fetch异常继续在本函数翻译成原Reader异常，必须按具体类型区分：

| 异常 | 固定处理 |
|---|---|
| 已有IndexMinuteReaderError | 原样抛出 |
| DuckDB BinderException、ConversionException、IOException | 抛IndexMinuteSourceContractError，保留cause；必需列缺失、读到错误类型/不能解析的源文件不能变成空结果 |
| DuckDB InvalidInputException | 仅消息含`schema mismatch`且含`column`，或含`parquet`且含`too small`/`magic`时按来源合同错误；这是当前1.5.5缺列/坏文件的实际错误形态。其他InvalidInputException继续IndexMinuteQueryError，不能把错误参数数量/内部调用错误全部说成来源坏数据 |
| 其他普通查询异常，包括未到时限的中断错误 | 保留原IndexMinuteQueryError及cause，不按字符串一概归来源错误 |

description不符和目标行检查失败都为IndexMinuteSourceContractError。完整历史外层仍根据原elapsed/timeout把到期Reader错误转为IndexMinuteHistoryBudgetError，并执行原finally；不修改超时优先级、异常吞吐或增加重试。分页HTTP仍由现有_raise_http_error映射IM_SOURCE_CONTRACT_INVALID/IM_QUERY_FAILED；r4仍由load_entry映射XXM_SOURCE_CONTRACT_INVALID/XXM_QUERY_FAILED。无需修改API或错误码注册。

#### 0.5.4 一次目标行循环及两个读取入口

新增本文件私有函数：

```python
def _validate_target_rows(rows: list[dict[str, Any]], *, dataset: IndexMinuteDataset,
                          request: IndexMinuteReadRequest,
                          output_columns: tuple[str, ...],
                          partition_dates: dict[str, date]) -> list[dict[str, Any]]:
    ...
```

输入为本次SQL原顺序dict列表，不由这个函数再查询或检查文件。初始化previous=None，逐行依次：

1. 按§0.5.2验证真实四键和文件定位；timestamp的时分秒判断沿原SQL的`%H:%M:%S`口径，不自行增加毫秒截止规则。文件日期只查本次映射，不重新从磁盘取信息，不用行内date代替文件日期。
2. 按dataset及output_columns检查当前用途的值；indicators的额外参数/版本始终检查，计数仅在实际需要时检查。原SQL没有的行情逻辑判断不能自行新增。
3. `current=(row['trade_date'], row['trade_time'])`，previous存在时必须`current < previous`，相等或上升立即拒绝；不得排序修正、去重、过滤错行或再造整份key集合。SQL的文件日期排序在合法行上与此真实键一致；非法date已在第1项拒绝。
4. 删除_source_filename及非output_columns的额外参数/版本，保留原输出字段及顺序；不得修改来自已发布缓存的对象，这里只处理本次新查询的dict。整份循环成功才返回rows，失败不返回前半份结果。

`_read`与`_read_complete_history`同时删除原DESCRIBE调用；引用清零后删除本文件的_validate_combined_schema，保留仍用于元数据的_normalize_duckdb_type。不能删除同名的股票、成交额或其他模块函数。

分页保持原分区扩展、limit+1、has_more、本页切片、`page_rows.reverse()`及以本页最早时间生成next_cursor；完整历史保持max_rows+1探测、超限拒绝而非截取、`rows.reverse()`。**SQL内部检查降序，两入口向调用方均交升序。**探测的额外一根同样检查，分页边界上的重复不能漏掉；正常窗口以外更老数据不为了本请求额外全量扫描。count/observedStart/End/scanned_file_count的原含义保持。

第1批的key/pop、空prepared不枚举/不连接、无prepared发现一次、失败不放回清单/不自动重试保持。删除DESCRIBE不是绕过首次链接检查；调用方既不重做第二轮链接检查，也不能新增“严格模式”恢复旧整表查询。

#### 0.5.5 两源对应、日历完整性与后续批次交接

`read_minutes`仍调用一次read_complete_history_pair，value_columns固定close及DIF/DEA/柱；不拆成两次签名/两次加载。先用两rows的len作O(1)比较，长度不同立即XxmSourceError。然后一个zip(strict=True)循环，对当前两行的`(ts_code,freq,trade_date,trade_time)`逐个对应，错位立即同类错误，再按原方法构造XxmBar并调用bar.validate。不再提前为两源各生成整份key tuple；不重做reader已完成的全段排序/去重或字段类型扫描。原无时区检查、+08:00构造、价格为正/指标有限、原错误处理保留。

`assert_continuous`只删单独的`actual != tuple(sorted(set(actual)))`及对应raise；保留actual原顺序、首末日期、同一份SSE日历/ENDPOINTS生成expected和`expected != actual`拒绝。这个逐项相等本身仍会拒绝缺根、重复和乱序，日线也必须有这些正常/错误对照，不能因为分钟reader已查顺序就让日线漏检。函数签名、日历SQL范围、完成时点和query调用顺序均不改；缩日历是第3批，不在本批提前实施。

query仍在源通过、完成根筛选、日历核对和完整计算校验之后才发布entry。预测继续复用该entry，保留第一批的缓存深复制/完整重验/一次投影。r4标签、编号、输入指纹和下一根条件在同一正常输入下应与第1批基线完全相同；不因隐藏字段多读了版本而把它们传入bar或指纹。后续第3批接收的仍是同样的升序XxmBar，不能要求它先开发才能完成本批。

已有合法entry被原缓存策略复用时，可以不进入reader，也就没有本次SQL/description/行循环；不能为了证明检查发生而强制再读。下文SQL次数只针对实际进入reader的读取，不把合法缓存零SQL判成漏检，不新增cache复用检查或签名字段。

#### 0.5.6 独立样本和旧测试迁移

新节点使用`test_p4_batch2_`，只落§0.5.1三文件。临时Parquet依据现Gold合同与`_write_gold_bars/_write_gold`构造；不能调用reader生成expected。默认bars字面预期仍为2026-08-11的09:35/09:40/09:45及close 10.2/10.4/10.6；指标默认0.1/0.2/−0.2、ma_250=None。这些helper的指标内部日期固定，跨日期/频率边界须显式生成独立合法记录，不能只改路径或照抄消费者假设。

旧`test_complete_history_checks_contract_of_other_indices`必须迁移并改成表中成对预期，不再要求其他指数坏行使上证失败：其他代码的坏OHLC/金额/版本/计数/时间等既有13种参数×60/90/120均核对。其原“目标不存在也应因别人错误失败”断言改为真实空结果；其他指数共享文件不可解析或缺共同必需列并不在这种忽略范围。旧test_reader_rejects_invalid_schema_and_request仍保留请求错误/必需列缺失的拒绝，不能只删除它或让Binder错误变成通用500。第一批prepared和输出投影测试不改成相反预期。

| 用例 | 独立输入与成对预期 | 落点 |
|---|---|---|
| 1 无多余SQL | 合法单次分页/完整历史各包原execute与目标循环；只有一次SELECT，无DESCRIBE、全指数contract/count DISTINCT；双源两SELECT。强制原分页分区扩展时两次SQL允许，但每次结果只进目标循环一次 | reader |
| 2 列顺序/增减 | 原文件、列倒序、新增未消费列、去掉未消费MA/open四类；两文件不同排列、缺未消费列时，交换路径先后均按字面结果成功；完整API所需列缺失则失败 | reader及分钟API |
| 3 必需列/类型 | 分别缺四键/close/MACD、指标参数版本必须拒绝；单文件查询实际报告INTEGER/BOOLEAN/VARCHAR/DECIMAL而字段期望DOUBLE时拒绝，不能应用层CAST补救；合法DOUBLE/DATE/TIMESTAMP作对照。多文件同一列混合类型按下表逐项核实际输出类型及值，不再断言仅凭description拒绝所有原始错类型文件 | reader |
| 4 错误翻译 | 首个文件缺列→BinderException、后续文件缺所需列→InvalidInputException、过小/错误magic的Parquet、数值转换错误分别按§0.5.3验证来源错误；另注入非schema InvalidInputException和普通异常仍为查询错误；正常输入配对。未知形式的文件解析异常也必须失败，不吞成空结果，不超出错误分类表强行认作来源错误 | reader及两个API错误码 |
| 5 真实空结果 | 无文件不连接；有合法文件但无目标/零行→真实[]且完成列元数据核对；无目标但别人坏值仍空；共同必需列缺失仍失败。不能用提前空返回绕过真实绑定 | reader、分钟/r4API |
| 6 其他指数错误 | 上述13类旧错误只在399001.SZ时，上证bars/indicators的完整与少字段均与字面输入一致；换为上证实际用到字段错误必须失败。含坏值的一方不影响另一份独立数据集读取 | reader、分钟API |
| 7 用途不同 | 上证open=NaN或缺open，close正常：r4少字段成功、分钟主图拒绝；缺MA或observation_count=0：r4指标少字段不读不查，完整指标API拒绝。两者正常输入均成功 | reader、实际r4两源、分钟API |
| 8 NULL归属 | 暖机MA/BOLL/MACD/KDJ的合法NULL按完整API原合同交付；计数/版本为空拒绝。r4的close/DIF/DEA/柱为None/NaN/Inf时由原bar检查拒绝，合法0指标及正close通过；不新增指标值域政策 | reader、分钟/r4API |
| 9 定位错误 | 已匹配代码的目标错freq、trade_date与文件日不符、timestamp日不符、freq/date/time为空、15:01及非1分钟09:30仍拒绝；原1分钟09:30和原合法时点通过。分别放文件首尾及start=end日期边界，不能因WHERE被藏掉；ts_code值为NULL的行不匹配目标，不据此阻断已有合法上证行 | reader |
| 10 cursor不掩盖错误 | 先取得合法cursor；游标当日文件放NULL时间、错误timestamp日期或错误行date，按§0.5.3进入检查并拒绝；当根及更新的正常行排除，跨代码/频率/dataset/范围cursor原拒绝保持。另按下段核游标日期/完整timestamp、微秒及无cursor参数，不允许开发者自选拼接/截断规则 | reader |
| 11 严格顺序 | 单源重复、只一源重复、首尾/limit与limit+1处重复均拒绝；直接给目标循环乱序dict亦拒绝而非修正。合法三根按原SQL降序检查，交付仍升序 | reader |
| 12 分页范围 | 09:35/40/45三根limit=2→返回09:40/45、has_more=True、cursor=09:40；下一页只09:35。正常窗口更老坏值不做额外全文件验收；探测额外根若坏必须拒绝。扩大分区、空页及不足limit不补齐 | reader及分钟API |
| 13 完整历史限额 | 三根max_rows=2必须拒绝，不截成两根；max_rows=3升序全部返回。错误/重复分别放max_rows+1与日期边界，不能借LIMIT回避；不为测试实际生成20000根或采样 | reader |
| 14 两源逐根对应 | 合法三根；长度不同；长度相同但中间时点/代码/freq/date一项不同；一边空；两边空。对等空返回()，其他错位XxmSourceError；用真实reader的两源错位样本补充替身单元例 | r4API文件 |
| 15 完整性/完成时点 | m60/m90/m120独立原端点表，缺中间端点/缺交易日拒绝，周末空档合法；未完成尾部按原completed筛掉。日线重复、逆序、缺日拒绝且正常连续通过；原asOf/空来源语义保持 | r4API文件 |
| 16 隐藏字段 | 少字段返回恰四键+所需值；主图11列/完整指标23列保持，无_source_filename/_partition_date或非输出检查列；sourceInputId/普通debug与合法独立例一致 | reader、分钟/r4API |
| 17 第一批保障 | 原prepared两数据集、空清单、四种key、首次根内/外链接、原子替换、失败pop后无自动重试且下一调用重新枚举全部保留；缓存坏对象/输出次数及事件显示原用例保持 | 第一批既有节点 |
| 18 失败与退出 | 新字段/行检查分别在真实读取函数中失败，Timer取消、连接关闭各一次；双源一边失败仍等待另一边清理，原超时错误优先级和取消传播不改。临时错误后新调用成功、不复用失败清单或发布半个entry | reader、r4API及既有工具 |
| 19 公开接入 | 真实临时Gold→原reader→原QueryService→原HTTP路由，主图/指标七频率、r4三分钟周期的正常与新来源错误均核对字段/行数/日期/错误码；生产挂载及不支持标的原行为保持 | 分钟API、r4API |

用例3的多文件补充必须使用同一实际所需数值列，其余身份/日期字段合法；分别构造以下文件顺序。表中数值是类型样本的值集合，行交付顺序仍按各自日期升序独立断言。预期为当前DuckDB 1.5.5已核实行为，不调用待测reader或类型helper生成expected：

| 传入read_parquet的先后顺序 | 查询实际输出类型与值 | 字段期望DOUBLE时的预期 |
|---|---|---|
| DOUBLE 10.2 → VARCHAR文本10.4 | DOUBLE，数值10.2及10.4 | 类型通过，再按原有限值/身份等规则检查 |
| VARCHAR文本10.4 → DOUBLE 10.2 | VARCHAR，文本10.4及10.2 | 类型拒绝，不转成数值重试 |
| DOUBLE 10.2 → DECIMAL(10,2) 10.6 | DOUBLE，数值10.2及10.6 | 类型通过，再检查实际值 |
| DECIMAL(10,2) 10.6 → DOUBLE 10.2 | DECIMAL(10,2)，Decimal值10.6及10.2 | 类型拒绝，不转成DOUBLE |
| DOUBLE 10.2 → BOOLEAN true | DOUBLE，数值10.2及1.0 | 类型通过，再检查实际值，不把通过解释为原文件BOOLEAN合同合格 |
| BOOLEAN true → DOUBLE 10.2 | BOOLEAN，两个true | 类型拒绝，不在应用层转换 |

reader测试通过不同日期文件的物理类型安排，覆盖原枚举先后；不得为了得到上表某一结果修改生产的文件排序。再补DOUBLE文件之后文本`not-a-number`的样本，实际转换失败仍为来源合同错误，没有“结果必然可转换”的兜底。原第一批读入的合法同类型Gold预期、r4取值和算法不变。

用例10的独立字面预期：cursor保存`beforeTradeDate='2026-08-11'`、`beforeTradeTime='09:40:00.123456'`，应绑定两次日期文本及完整`before_stamp='2026-08-11 09:40:00.123456'`，总参数仍6个。合法同日记录的时间分别为09:39:59.999999、09:40:00.123456、09:40:00.123457时，下一页只保留第一根；等于游标和更新的两根排除。另核普通无微秒游标沿原格式成功、跨日期沿原门槛，以及无cursor仍只有paths/ts_code/limit+1三个参数。用包装原execute的方式断言绑定值并实际执行，不能只比较自行拼出的字符串。

用例3/4/5必须实际调用DuckDB，不能用伪造description替代“缺列被拒绝”的主要证据；用例11的直接乱序列表只验证私有循环，不冒充真实SQL排序验收。用例14可用替身专门造两份合法键集合错位，但至少用临时Gold完成一次真实两源错误链；用例18不能只替换整个读取函数。观察SQL次数和字段时包装原方法，不跳过执行，也不以旧实现生成expected。用例17的旧“schema保留”仅是第一批历史成绩，第二批该边界已由本表2—10取代，不恢复已删除函数来让旧文字成立。

#### 0.5.7 编码顺序、预算及失败边界

1. 先核对5084ef939及本批路径、调用方、已安装DuckDB/原字段合同，保留其他工作区修改；把本表用例1—10先落测试，使旧全表/其他指数政策及重复SQL能被独立样本抓住，不改预期迎合旧行为。
2. 在reader同批完成SQL、元数据、目标循环及两入口迁移；清零本文件_validate_combined_schema引用并删除，不保留旧严格/新快速双轨。此步必须连同必要检查全部完成后才作为可交付实现，不只提交删除检查。
3. 接着修改source的两源对应和assert_continuous；day/m60/m90/m120共同回归，保持日历范围及加载顺序。预测query和计算核心不改。
4. 完成用例11—19与旧政策测试迁移，再分组回归、独立对照本节及第一批审计；实际完成后更新原四份文档，停在第3批之前，不自动提交、测量或恢复正式P4验收。

原读取上限不变：分页1—10000根、完整历史≤20000根、分区≤5000；一次SQL最多取limit+1或max_rows+1。原单读512MB/2线程，双源各256MB/1线程；两源仍共享原截止时间而非各重新给足时限，线程退出仍等待finally完成。原识别4秒、预测总4秒/处理400ms、客户端5秒及原响应/缓存上限不变。列检查、行循环、编码、失败清理和最终验收开销都在原处理时限内，不挪起点、不新增预热或延长时限。

失败不返回部分行，不跳过坏目标、不回退旧SQL、不额外重新读取或自动重试，不发布失败entry/预测。取消和已知异常沿原finally/锁/线程清理，下一次获准请求从新调用开始，已消费prepared不恢复。仅人工fixture/cache可用于复测，无业务结果/恢复文件。发现库行为或真实合同与本节冲突时停止并说明，不安装新版或添加隐式补值兼容。

#### 0.5.8 后续开发验收的有界分组

均使用现有`.venv/bin/python -B -m pytest -q`；每组超过60秒停止查因，不安装依赖。开发时按此明确选择，交付登记完整实际节点和参数，不用-k通过数冒充全量：

1. `tests/test_major_index_mins_reader.py`整文件，含新19组相关参数和迁移后的旧测试。
2. `tests/web/test_index_detail_minutes_api.py`整文件，只用其临时Gold及独立人工合同；不启动正式App服务。
3. `tests/web/test_wealth_index_detail_xxm_api.py`整文件，覆盖现日线/三分钟周期、缺口/完成时点、普通debug、第一批投影及新增两源用例；这些均是人工SQLite/Parquet，不读取正式源。
4. `tests/web/test_wealth_index_detail_xxm_forecast_validation.py`整文件；forecast_api仅第一批§0.4.7的26例原选择（含两模式缓存重验、F06/F07及退出/编码），不整文件触发290根计时样本。source交接变化不能使预测回退或绕过坏来源。
5. following_query的第一批RC93三个节点及P4工具的original_cache_methods/shared_actual_result/partial_observation_setup三个节点，参数同§0.4.7；根目录三份架构测试，另静态核两个生产文件无新增反向依赖。
6. 文档完整性、本轮四文档链接、限定diff、旧函数引用清零及SQL语句检查。新SQL不可含整表DESCRIBE/contract聚合/count DISTINCT，Source不得保留两整份key tuple或sorted(set(actual))；常量/请求白名单、必要bar.validate不能跟着删除。

分组2/3须包含真实生产读取器和HTTP的最小隔离链路，核对请求参数、实际行数和错误码；仅mock不能作为接入证据。本批不读正式Gold/Prod、冻结行情CSV，不跑Wealth全量、回测CLI、P4真实采样或毫秒收益对照。临时人工SQL接入通过不能宣称正式来源或4秒性能已验收；这些仍留第8批。

#### 0.5.9 开发前第一批与第二批的独立文档审计（2026-11-01）

| 交接项 | 核对及最终口径 |
|---|---|
| 开发前两批状态 | 当时第一批提交5084ef939、226例成绩保留，第二批仅设计；第二批后续开发的独立证据见§0.5.10，不能借第一批成绩证明新SQL |
| 第一批保留旧SQL与第二批删除旧检查 | §0.4明确为第一批记录；第二批统一由本节接管reader/schema检查，既不要求永远保留旧检查，也不删除首次发现/缓存完整验证 |
| 输出重建与读取行检查 | 两project及query缓存重验保持第一批实现；新目标行检查只针对本次源行，不把整份内部结果再重建一遍 |
| 字段减少与完整API | r4只读所需值及指标版本；主图/完整指标仍检查各自字段，类型/NULL和计数职责按§0.5.2，不共用r4少字段规则放过主图错误 |
| 类型检查能力 | 按本次查询实际输出类型和值验收；多文件由DuckDB发生的转换不等于应用层CAST补救，也不能据description宣称逐文件原类型已通过。混合类型及交换先后有独立预期，不恢复逐文件检查 |
| SQL过滤与坏数据 | 只提前限定目标代码及枚举的文件范围；真实date/freq/版本不作为消除错行的WHERE，cursor定位错误明确保留到检查，不恢复全指数验收 |
| 游标参数 | 日期和原时间精确拼成完整timestamp，原秒/微秒及编码保持；有cursor六个参数、无cursor三个，不能只绑定时分秒或自行改变时区 |
| 顺序、分页与源交付 | 每份SQL结果一次严格降序检查，分页/完整历史均升序；两源一次对应，日历仍负责缺根，日线的逐项完整性对照保留 |
| prepared及错误清理 | 复用第一批清单，无第二轮链接检查；删除schema SQL后Timer/finally仍包住目标查询及循环，失败不补清单/不重试，第二次独立调用重新发现 |
| 先后依赖及后续边界 | reader的删除/必要检查同批；然后source交接；最后真实临时API及回归。不依赖第3批日历或第4批测量，预算不放宽，源/算法/前端不扩大 |

审计依据为当前reader/source、分钟QueryService及DTO、API错误映射、旧测试及动态工具调用，CodeGraph explore/impact与源码补核共同完成；同名独立读取器不作本模块证据。已通过Context7核对所用DuckDB API，并用自动删除的临时人工identity/value表核验1.5.5的元数据、交换多文件顺序、未消费列缺失/改序及必需列缺失的两种异常；另核过小Parquet的实际异常类型，并直接取本文SQL在临时人工表核对无cursor/有cursor的3/6个参数、NULL时间保留及排序。此为文档可实现性的库行为核验，没有业务代码/测试文件改动、真实行情读取或性能测量，不替代§0.5.6—8开发验收。

提交1867e883e后的独立审计另发现两处需补齐：类型检查不能兑现拒绝所有原始错类型文件的承诺，以及before_stamp缺少精确构造。管理员已批准按建议修正，本轮已直接统一§0.5.2/3与用例3/10，并同步专项§4.6/§10、技术方案§17及产品说明；没有恢复整表/逐文件检查，没有改变cursor或算法。前轮其余交接设计及19组用例保持。当前两项已落实为明确的编码要求和独立预期，没有未决口径；检查成绩以本轮文档校验和限定库行为核验为准，不把第一批成绩当成第二批实现验收。

本轮限定核验使用自动删除的临时人工文件：六种混合类型先后顺序、不可转换文本、带/不带微秒的完整cursor及无cursor绑定均与修正后的字面预期相符。该核验只确认DuckDB行为和本文SQL/参数，不是第二批reader/API已经开发或回归通过。

上述2026-11-01文档修正已提交da53fb3f4；当时未编码或执行第二批业务测试。管理员随后授权按本节开发，实际结果见§0.5.10。第三批的后续结果见§0.6.10，性能测量仍未启动。

#### 0.5.10 第2批开发交付及独立审计（2026-11-02）

管理员授权后严格按§0.5.7实施。生产只修改原reader和source，测试只修改§0.5.1三个既有文件，配套原四文档同步状态；其他工作区修改保留。本轮没有提交、安装、部署、正式源读取、行情重放或性能测量。

先加入用例1—10的相关样本，再修改生产代码：旧实现对其他指数的NaN open、Infinity close两个样本仍报来源错误，证明旧全文件政策会错误阻断目标请求；新增一次行检查样本也因旧实现缺少该步骤失败。完成reader整体迁移后再改source，随后补齐其余用例和接入回归。新增人工文件改写helper的参数绑定及API夹具行数/错误状态预期在测试开发中发现并修正：原分钟指标夹具只有1根，且现来源合同错误HTTP为500；没有为让测试通过修改生产HTTP状态或补造数据。

**实现及19组逐项对账。**表中所有`test_p4_batch2_`节点都位于本节三个测试文件；简写仅省此前缀，节点完整名称可按原后缀定位。人工值和预期独立于reader计算，SQL观察均包装真实execute，没有伪造description。

| §0.5.6组 | 生产实现及实际测试 | 独立复核结果 |
|---|---|---|
| 1 SQL次数 | reader两入口删原schema调用，_query_rows同次查询/description/一次循环；`one_select_and_one_check_per_read`（page/history/pair）、`partition_expansion_checks_each_query_once` | 单读1 SELECT、双源2 SELECT；分页扩大分区2次查询/2次检查；无DESCRIBE/全指数聚合/占位 |
| 2 未使用列 | output_columns/read_columns按原用途生成；`selected_columns_ignore_unused_schema`（reverse/extra/drop_open/drop_vwap×先后位置）、分钟API unused_schema | 两文件改序/增减未使用列不阻断；完整API所需字段仍不能缺 |
| 3 字段和类型 | 同次description检查真实列名/顺序/逻辑类型；`missing_consumed_column_rejected`8类、`wrong_query_output_type_rejected`4类型、`identity_query_types_rejected`4键、`multifile_result_types`7例 | 六种混合顺序核对实际元数据和字面值；不可转换文本失败；没有应用层CAST补救或逐文件类型承诺 |
| 4 错误分类 | _query_rows按原类别翻译；`actual_parquet_failures_keep_source_error`（tiny/magic/later_missing）、缺列节点、`other_query_errors_not_reclassified`3类 | 实际首文件Binder/后文件InvalidInput、坏Parquet和Conversion分别失败；非schema错误保留查询错误/cause；HTTP原500及错误码保持 |
| 5 空来源 | 两入口原无文件短路保留；`empty_target_still_checks_actual_columns`（无目标/零行/NULL代码）、原空prepared节点及两API empty | 真正空集合；有文件仍绑定所需列，无目标也不能掩盖缺列；无文件不连接 |
| 6 其他代码 | 只按ts_code过滤；旧节点迁为`foreign_errors_do_not_block_target`（13类×60/90/120） | 完整/少字段和目标不存在均符合字面预期；把相同坏值放回目标且实际消费时仍拒绝，不恢复全指数验收 |
| 7 用途区分 | 值检查只针对output_columns，指标参数版本额外读取后删除；`partial_checks_only_consumed_fields`4类、r4真实API unused_bad/unused_missing | r4不读坏open/缺MA/无效未消费计数；完整主图和指标继续拒绝这些所需字段错误 |
| 8 NULL/有限值 | reader保留指标暖机NULL；source原bar.validate保留；`full_indicator_warmup_nulls_remain_nullable`、`bar_validation_still_rejects_required_values`（4字段×None/NaN/Inf）、原行情有限值节点 | 指标NULL按原API交付；r4必需值仍拒绝，合法零指标和正close通过 |
| 9 定位/时点 | _validate_target_rows核四键/文件日期/原时分秒规则；`bad_target_fields_not_filtered`11类、原日期/NULL节点、`original_time_policy_not_strengthened` | 不借freq/date WHERE隐藏坏行；NULL代码不冒认目标；1分钟09:30及原午间/15:00微秒处理不新增限制 |
| 10 cursor | 原_decode/encode保持；_query_rows绑定原完整before_stamp；`cursor_does_not_hide_location_errors`3类、`cursor_binding_and_exact_boundary`带/不带微秒及原cursor身份节点 | 有cursor6参数/无cursor3参数；日期完整且微秒不截断，等号及更新正常行排除，定位错误仍拒绝 |
| 11 顺序 | reader一次严格降序检查，入口仍reverse；`direct_checker_rejects_out_of_order`、`probe_and_full_history_limit`及原重复时间节点、实际r4 duplicate | 不排序修复/去重；同源或单边重复都失败，正常输出升序 |
| 12 分页 | 原limit+1/扩分区/游标保持；`cursor_cross_date_and_page_probe`及扩分区节点、原分页节点 | 字面三根limit2、跨日下一页及不足数量保持；更老范围外错误不全扫，探测根错误拒绝 |
| 13 限额 | 完整历史原max_rows+1及超限拒绝保留；`probe_and_full_history_limit`两例、原超限节点 | 3根max_rows2拒绝/max_rows3完整交付；坏/重复探测根不能绕过 |
| 14 两源 | source先len再同一zip逐根对应/构造；`two_streams_match_in_one_pass`9类及真实r4 misaligned | 长度/四键错位、一边空拒绝；两边空返回()；pair调用一次、原字段和剩余时限不变 |
| 15 连续性 | source仅删独立sorted(set)，保留expected逐项比较；`calendar_still_rejects_gaps_duplicates_and_order`（day/m60/m90/m120×5类）及原完成时点API | 缺日/缺端点/重复/逆序均拒绝、周末合法；原20点切换和完成根筛选不改 |
| 16 交付字段 | reader剔除隐藏列，source仍原bar；投影字段既有节点、分钟API及r4 partial API | 完整11/23列、少字段原顺序保持；隐藏列不传bar/指纹；实际r4普通/debug公共事实及no-store一致 |
| 17 第一批 | 第一批project/query/cache文件本批未修改；原prepared/链接/失败再调用、投影次数/坏缓存及RC93/工具节点重跑 | 清单一次消费、无第二链接检查、首次发现拒链接、缓存一次完整验证均保持，无衔接冲突 |
| 18 失败退出 | Timer/finally及pair等待代码原样；`actual_validation_failure_closes_and_rediscovers`（type/value）、`real_pair_error_waits_for_both_connections`及原错误等待/预算节点 | 真实字段/行失败后cancel和close各一次，两源退出均释放；清单不恢复，无自动重试；新调用重新枚举；HTTP失败不发布entry |
| 19 原HTTP | 原reader→QueryService→HTTP；`real_minute_api_contract`（七频率×4类）、`real_xxm_partial_reader_and_http`（三频率×8类）及原路由/鉴权/环境测试 | 主图、完整指标和r4少字段真实临时Gold接入通过；原不支持标的、prod不挂载、5MiB限制和错误码保持 |

**实际回归。**使用现有`.venv/bin/python -B -m pytest -q`，最终有界分组共438例通过，无skip；每组均小于60秒。秒数是回归组执行时间，不是性能收益证据。

| 组 | 精确执行范围 | 通过/耗时 |
|---|---|---|
| reader | `tests/test_major_index_mins_reader.py`整文件，含上述所有reader参数和原第一批节点 | 184 / 6.15秒 |
| 分钟API | `tests/web/test_index_detail_minutes_api.py`整文件 | 48 / 5.41秒 |
| r4 API/source | `tests/web/test_wealth_index_detail_xxm_api.py`整文件 | 106 / 3.66秒 |
| 预测验证 | `tests/web/test_wealth_index_detail_xxm_forecast_validation.py`整文件 | 47 / 2.67秒 |
| 预测API | §0.4.7“预测API”行所列11个完整节点及全部相同参数（含6个坏缓存、F06/F07及两模式缓存检查）；未选其余26例/290根计时样本 | 26 / 1.67秒 |
| 历史与工具 | §0.4.7“历史及工具”行所列6节点及全部相同参数：RC91_93四例、RC93完整两例和窗口一例、原缓存一次/共享结果异常两例/观察设置恢复一例 | 11 / 0.33秒 |
| 架构 | 根目录要求的三份architecture文件，与§0.4.7同名整文件 | 16 / 13.32秒 |

独立审计在回归后重新读取两生产diff及实际调用方，按上表逐项核对：删除完整schema查询没有删必要所用列检查，其他指数错误政策没有转移到Python，source没有再次造两份完整键集合；首次文件检查/签名/prepared、Timer/finally、双源资源和等待均未改。公开模型、r4/Spec/状态推进、预测公式/价格范围、缓存发布/完整验证、日历SQL及加载顺序均未改。CodeGraph explore/impact覆盖reader/source、分钟QueryService及测试/研究调用方，源码补核HTTP异常映射、动态工具与预测共用来源；sync/status已完成，没有新增反向依赖。未发现偏离LLD、未落实的本批规则或与第一批的冲突。

文档完整性三组、四文档32处本地链接、新交付表格列数及九个限定文件的git diff --check均通过。静态核对旧schema函数零引用、_query_rows仅一个execute、source无两份完整键集合或sorted(set)，签名及双源资源/截止时间函数与开发前一致。测试环境仅有既有Starlette/httpx弃用提醒，无新增依赖。

本批结论只覆盖上述临时Parquet/SQLite和真实原读取器/路由的隔离链路，不是正式Lake/Prod验收；没有运行Wealth全量、研究CLI、冻结行情、浏览器或毫秒收益对照。60分钟是否满足4秒仍待后续测量及第8批正式续验，不能据此宣布P4第5步通过。第二批交付时停在第三批前，随后管理员授权提交70659f763；其余工作区变更保留。第三批后续已按§0.6完成，实际证据见§0.6.10；日线原范围保持，正式采样仍未恢复。

### 0.6 耗时优化第3批：分钟交易日历范围的具体编码设计

本节落实专项§4.3/§6第3批，承接第一批5084ef939、第二批70659f763及§0.4.7/§0.5.10。**当前已按本节完成第三批开发、610例限定回归及独立审计，实际逐项对账见§0.6.10；已随4debb8eb3提交。**本批只改变分钟日历的适用范围及必要调用配合；第一、二批仍是已实现基础，不回退任何已确认精简。未读取正式源、未测量，停在第4批之前。

#### 0.6.1 目标、当前依据、文件及禁止项

目标：每次分钟加载按本次真实raw首日和业务日确定日历范围，保留完成端点、缺行情检查、缓存复用、历史识别及预测的原结果。每次load_entry仍建立原最新前缀，endDate/asOf只选择结果；不得把历史请求日期或主图500根作为原始行情加载范围。

开工前70659f763的代码依据：source.calendar_dates无条件从1990查至end，仅检查结果非空及最后日期等于end，再返回开市日期；query_service._load_series先查日历，再取缓存/分钟签名和raw；forecast_query_service.build以open_dates校验显式asOf。MarketPageContextQuery在此前独立解析业务日和上海时间，包含20点切换及自身SQL；本批不修改它，也不能把其SQL计作calendar_dates重复查询。future_calendar是预测下一端点的另一项必要查询，与本节历史日历职责分开。

| 文件 | 本批限定改动 | 必须保持 |
|---|---|---|
| `src/biz/queries/wealth/market/index_detail_xxm/source.py` | calendar_dates增加必填start；新增本模块内部使用的is_open_date单日查询 | 原SSE源/模型/Session、expected_through/ENDPOINTS、read_daily/read_minutes/assert_continuous、第二批逐根交接 |
| `src/biz/queries/wealth/market/index_detail_xxm/query_service.py` | 仅_load_series的日线显式起点及分钟“取raw→日历→completed”顺序、范围和原remaining检查 | build/load_entry接口、上下文/共享flight/key、文件签名和prepared、计算/编号/指纹、恢复/完整校验/发布、SeriesEntry字段及缓存政策 |
| `src/biz/queries/wealth/market/index_detail_xxm/forecast_query_service.py` | 导入is_open_date；显式分钟asOf早于日历范围时一次单日补查和原资格判断 | API解析、未来日历、400ms起点、源前缀/校准/求界、结果和缓存身份、投影/编码、with退出及发布顺序 |
| `tests/web/test_wealth_index_detail_xxm_api.py` | 新增第三批范围/次数、完成根、缓存、失败及日线对照 | 第一、二批既有预期及真实临时Gold→reader→query→HTTP |
| `tests/web/test_wealth_index_detail_xxm_forecast_api.py` | 新增历史asOf/单日查询、身份、失败和真实分钟接入；测试api helper可接可选临时lake_root，原默认None保持 | 原鉴权/拒旧/预测缓存/F06/F07断言；不整文件触发290根计时节点 |
| `scripts/research/index_market/tests/test_xxm_snapshot_consumers.py`、`test_xxm_r4_internal_results.py` | 仅迁移4处calendar替身签名和范围过滤；已有人工预期不改 | 真实识别/快照/历史/修订及失败安全断言，不改研究执行代码 |

生产只限前三文件，测试只限四个既有文件；不新增生产文件、公共结果字段、配置、开关、日历缓存或通用查询框架。不修改reader/Gold合同、任何模型或数据库/Lake结构、连接目标、正式HTTP/CLI/TS/前端、calculator/Spec/EMA/下一根价格解。研究、App、QTF不得成为Biz运行依赖。无真实源读取、正式写入、测量工具、恢复文件、安装、部署或自动提交。

#### 0.6.2 两个日历函数的字段、SQL和错误

原TradeCalendar合同为core_serving.trade_calendar，主键(exchange,trade_date)，日期DATE→Python date，is_open为非空Boolean→bool；pretrade_date不是本步所需列，不读取。测试依模型和现SQLite夹具构造，不能据消费者猜字段。

`calendar_dates(session: Session, *, start: date, end: date) -> tuple[date, ...]`：start必填，无默认1990或可选兼容路径。保留原select(date,is_open)，where精确为exchange=='SSE'、trade_date>=start及<=end，order_by日期升序，只execute一次并复用返回行；不加逐日查询、计数SQL或补全日历。start>end先抛XxmSourceError且不发SQL；其余保留原“无行或最后行日期不等于end→XxmSourceError”和原开市过滤，不借本次优化另建全量日历字段/完整自然日扫描。所有调用方必须传明范围，不能在函数内部自行判断日线/分钟。

`is_open_date(session: Session, day: date) -> bool`：本模块内部辅助，由forecast_query_service显式导入，非新API/运营参数。一次select(TradeCalendar.trade_date, TradeCalendar.is_open)，where仅SSE和trade_date==day，使用原Session的execute(...).all()；不加宽范围、额外count、连接、事务或重试。结果必须恰一行，返回日期等于day且type(is_open) is bool；否则XxmSourceError。False仅表示记录明确写着休市，不能将无记录、NULL、重复或错误字段当False。检查对象是现SQLAlchemy解码后的行，不声称追溯DB原始物理类型。

范围查询在_load_series内用原remaining前后检查；单日查询在forecast build内用同一个remaining前后检查，仅成功返回后再做后置检查，不能放到finally覆盖原异常。函数自身不新建计时器或延长时限。XxmSourceError仍由原load_entry映射XXM_SOURCE_CONTRACT_INVALID/500，预测HTTP沿原规则改前缀XXMF_；确认为休市/非法端点仍XXMF_REQUEST_INVALID/400；数据库普通异常、超时、取消沿既有映射和优先级，不吞成EMPTY。

当前旧范围函数不能区分范围中间“没有那天记录”和明确休市；本步不扩大修复该函数的全部历史校验。新单日查询已经能区分两者，按专项“缺日历不得当休市”要求明确失败；不能用旧弱检查要求新函数返回False。未来日历的连续自然日和严格bool检查保持原实现，不挪到这两个函数重复执行。

#### 0.6.3 _load_series分支、范围和交接顺序

业务日business_date仍来自原MarketPageContextQuery，日历end固定now.date()，now已由load_entry转上海时间。minute_request仍为原(freq,business_date,start=None)，不改变原始行情范围。只取已经按第二批核验、升序交付的raw[0]日期，不扫描文件找更早起点或重新读行情。

日线分支保持原顺序：calendar_dates(session,start=date(1990,1,1),end=now.date())→原expected_through→原cache.get→read_daily(completed)→signature=()。仅显式化原起点及沿原截止时间补阶段检查，不缩日线、不改变完成日。

分钟分支按以下唯一顺序写入现_load_series，不另造加载入口：

```python
remaining()
assert self.reader is not None
previous_entry = self.cache.get(key)  # 仍一次
freq = int(period[1:])
request = minute_request(freq, business_date)  # start仍None
signatures = []
for dataset in ("bars", "indicators"):
    remaining()
    signatures.append(self.reader.history_source_signature(request, dataset=dataset))
    remaining()
signature = tuple(signatures)
raw = (previous_entry.raw
       if previous_entry is not None and signature == previous_entry.signature
       else read_minutes(self.reader, freq=freq, end=business_date, deadline=remaining))
remaining()
calendar_start = min(date.fromisoformat(raw[0].time[:10]), business_date) if raw else business_date
open_dates = calendar_dates(session, start=calendar_start, end=now.date())
remaining()
completed = expected_through(period, open_dates, now, business_date)
```

此前仍保留原reader非None检查；分支进入使用原remaining，且**bars、indicators各自调用签名前检查一次、成功返回后检查一次**。bars返回时预算已耗尽，必须在其后置检查退出，indicators不得调用；indicators返回时耗尽，则不得继续复用/读取raw或查询日历。不得把两次签名藏在只有整体后置检查的tuple/generator中。成功路径仍仅按bars→indicators各查一次，request、签名内容及prepared交接不变；本步只是补齐原4秒检查点，不增加文件检查或独立时限。签名自身抛错/取消时直接保留原异常，不在finally检查时间覆盖它。上式只定义需要迁移的片段，不替换后续整函数。**先确认本次raw，再定日历范围，再求completed；不先猜日历范围，也不为了算start增加一次读。**raw为空只查business_date至now.date()；保留当日或上个业务日完成状态的判断，不随意取今天作为start。start=end合法，周末的end仍需原日历记录；不擅自补周末。

两分支结束后继续原缓存复用条件（previous_entry/signature/raw/completed/open_dates）、processed完成根过滤、assert_continuous、origin/revised、既有状态推进/指纹/完整校验及cache.put。不能把范围比较加进revised、源指纹、flight_key、forecast key或Spec。SeriesEntry仍仅保存原open_dates开市tuple，不新增范围、版本或完整日历副本。

正常热请求仍执行原两份签名和一次适用日历查询；签名未变则直接复用raw，不进入reader/pair，不为消费prepared强制重读/清空清单。prepared创建/覆盖/一次消费继续第一批原规则。日历中的无关旧日期被排除后不再导致每次重建；不增加一套“旧全范围/新短范围”运行分支。

若测试构造一份含原长open_dates的合法旧内存entry，第一次返回范围变短可按现路径复制候选、更新open_dates；processed/origin相同则不能认作源修订或从空step，指纹/标签保持，旧对象不改。之后相同请求应直接命中同一新entry。真实进程未新增跨版本持久化/恢复迁移。实际覆盖范围内开市标志变更、来源新增/修订、完成端点推进仍走原核验及候选发布，不得为保缓存忽略缺行情。

#### 0.6.4 历史识别和显式预测的资格交接

识别build接口不改：endDate早于raw首日时，按已有_response得到EMPTY；不为识别窗口补单日查询。较晚窗口仍只裁响应，不裁load_entry实际前缀。expected_through继续使用唯一ENDPOINTS，不另写时间表或推算假K线。

预测build在取得原四元组(entry,context,open_dates,remaining)后，仍计算upper=min(请求日期或context.trade_date,context.trade_date)。仅将用于本次请求资格判断的开市日期设为局部request_open_dates；不写回entry.open_dates，也不改变load_entry四元组或共享返回对象。

```python
request_open_dates = open_dates
if as_of is not None and period != "day":
    requested_day = date.fromisoformat(as_of[:10])
    if requested_day < date(1990, 1, 1):
        raise XxmQueryError("XXM_REQUEST_INVALID", "asOf 必须是已完成的开市端点。", 400)
    calendar_start = (min(date.fromisoformat(entry.raw[0].time[:10]), context.trade_date)
                      if entry.raw else context.trade_date)
    if requested_day < calendar_start:
        remaining()
        opened = is_open_date(session, requested_day)
        remaining()
        request_open_dates = (requested_day,) if opened else ()
expected = expected_through(period, request_open_dates, context.generated_at, upper)
# 仅as_of非None时继续原判断：expected为None、as_of>expected、upper不在request_open_dates即400；
# 合法显式asOf仍令expected=as_of，再按原bisect/EMPTY/DELAYED/READY分支执行。
```

1990下界来自旧calendar_dates的实际查询范围，仅保留原历史预测资格，不新增配置或把分钟范围拉回1990。单日查询只发生于“分钟、显式asOf、1990及以后、早于本次范围起点”；范围内日子即使休市也不得再查，直接用已有open_dates判断。未来日期、未来端点、非法频率/端点/时区仍由原参数解析和原比较拒绝，不新增补查。latest和日线不调用is_open_date。

| 场景 | 单日查询 | 固定结果 |
|---|---|---|
| 分钟asOf在本次范围内且合法 | 0 | 原READY/DELAYED/EMPTY及计算路径 |
| 分钟asOf在范围内休市，或请求未来端点 | 0 | 原400，不借补查放行 |
| 分钟asOf早于raw首日，且早于本次范围起点、SSE明确开市 | 1 | 按原完成端点校验后EMPTY；sourceInputId/calendarInputId/targetEndpoint为None，不校准/求解/读预测缓存 |
| 空raw，asOf早于business_date，SSE明确开市 | 1 | 同上EMPTY，不把raw空直接当请求非法 |
| 前述范围外单日明确休市 | 1 | 400；没有行情不等于任意日期都可请求 |
| 前述范围外单日无记录/NULL等坏字段 | 1 | 来源合同错误500，不冒充休市或EMPTY |
| 分钟asOf早于1990，即使临时表写有开市记录 | 0 | 原400，资格不扩大 |
| 日线或未传asOf | 0 | 原行为保持 |

如requested_day在已取范围内、但早于第一根已完成processed（例如raw含当日未完成根），不需要补查；用原open_dates和bisect得到原EMPTY。不能以processed首日替代raw首日计算范围。

未来日历future_calendar只在原READY→校准成功路径读取，继续生成一个严格晚于through的端点和原calendarInputId；不和范围查询/单日资格查询合并，不把其未来日期插入entry.open_dates。相同有效行情/asOf的sourceInputId、calendarInputId、forecastId/条件编号及普通/debug字段必须相同；新范围和额外资格查询不进入任何结果身份。

#### 0.6.5 预算、查询次数、失败与恢复

不改计时起点：load_entry原4秒覆盖上下文、文件发现/签名、实际读源、范围日历、验证/计算/发布和原退出检查；预测显式asOf补查在同一原4秒内，不能给它单独追加时限。原READY路径的400ms仍在calculator_at/校准/缓存处理前建立，不提前/延后或重开；真正READY请求不需范围外补查。预测32KiB、识别1MiB、客户端5秒及reader20000根/5000分区/双源内存/并发上限均保持。

查询次数按实际职责登记：每次成功执行_load_series恰有一次calendar_dates；若签名/raw阶段已失败或取消，则不补发日历查询。日线仍原范围，分钟为本节短范围。范围外显式预测最多加一次is_open_date；正常范围内/日线/latest为0。MarketPageContextQuery原上下文SQL和future_calendar原未来查询分别计数，不能误写成“整个HTTP总共只能一次SQL”。相同flight真正重叠的识别/预测共享原一次源加载和范围查询；先后两个独立HTTP允许各查一次适用日历，不新增跨请求缓存，也不先关闭现SharedLoads。两源明细在实际未命中时仍一次pair，热raw复用时为0；不要为了数行/确认身份再执行SQL。

_load_series内的签名/raw/范围日历失败或截止到期：不返回半份entry、不put本次候选、不恢复prepared、不重读/自动重试；原已发布entry的事实和早先响应不改。两份签名各有原remaining前/后检查，第一份已超时不得做第二份，第二份已超时不得进入raw/日历。检查不能中途打断一个正在执行的签名调用；成功返回时立即检查，阻止后续工作，不另建线程、Timer或延长预算。原锁、请求槽、SharedLoads完成/异常传播和取消清理继续原finally，不持有时间更长的事务。

单日资格查询发生在合法源加载之后：源entry可能已由原load_entry成功发布，单日查询失败不得回滚这个合法源。必须拒绝预测结果、不调用put_forecast；不能把“所有预测失败都不得留下source entry”作为新增错误断言。with异常退出保留原错误，不在finally再检查时间覆盖来源错误/取消。范围/单日的成功返回后均执行原remaining；超限不返回成功。进程退出只丢内存，下次从原入口新请求计算，无恢复文件或后台续跑。

#### 0.6.6 测试设计：字面输入、预期及落点

新节点前缀test_p4_batch3_，仅落0.6.1四个测试文件。主要新增用例在两个web文件；研究测试仅迁签名/范围，不改expected。生产源合同以TradeCalendar及第二批Gold为依据，使用临时SQLite/Parquet；正常/反向日期和端点全部手写。fixture不得调用calendar_dates/expected_through生成expected。

统一人工示例：NOW=2023-01-10 20:00:00+08:00，business_date=2023-01-10；日历包含2023-01-03至10的自然日，7/8休市、6/9/10开市。raw首日10号时范围精确[10,10]；首日6号、now为10号时范围[6,10]、返回3个开市日；空raw仍[10,10]。三分钟端点独立字面表为m60的10:30/11:30/14:00/15:00，m90的11:00/14:00/15:00，m120的11:30/15:00；生产仍只用原ENDPOINTS，测试表是独立预期。

三周期全零Gold夹具固定只含6/9/10号开市日：每个标准端点一根，四键按原Gold类型，close/open/high/low=100.0、vol=1.0、amount=100.0、exchange='SSE'；指标macd_dif/macd_dea/macd=0.0、observation_count=1、params_key使用原GOLD_PARAMS_KEY、indicator_version=1；MA/BOLL/KDJ字段全部为合法暖机NULL，bars的vwap=100.0。三周期最终根数字面预期分别12/9/6，最后完成根均10号15:00，events=[]、每根ordinaryState='NONE'；日历[6,10]只返回6/9/10三个开市日。缺字段/坏值用例在这份独立夹具上显式改一处，不能由被测reader或calculator生成预期。首尾/单根用例显式裁这份人工输入，并按原端点/窗口手写预期。**全零只覆盖范围、静态及失败分支；它使precheck_next_bar返回ZERO_WAVE，不会进入校准、future_calendar或预测缓存，不能据此声称READY交接通过。**

新真实HTTP测试可用测试内datetime子类仅覆盖query_service.datetime.now，返回上述NOW；保留原解析/Session/reader/load_entry/计算路径，不替换它们的结果。已有测试api helper可传临时lake_root供分钟路由，使用全新XxmCache隔离测试，不修改生产配置。来源为空/资格反例不应触发校准。

**用例14/19另建非零M1分钟夹具，三周期分别写入真实临时Gold，再走真实SQLite/reader/_load_series/load_entry/原HTTP。**六根数值按现预测API文件M1的独立人工输入展开，DEA也使用下表字面值，不调用被测函数生成；各时间均为2023年、上海+08:00，写Gold时沿原合同保存本地datetime。除四键及本表数值外，字段沿全零夹具；每根open/high/low/close/vwap均取该行close，amount取close、vol=1。MA/BOLL/KDJ仍合法NULL，不重算MACD。

| 根序 | close | DIF | DEA | 柱 | m60时间 | m90时间 | m120时间 |
|---|---|---|---|---|---|---|---|
| 1 | 100 | -60 | -59 | -2 | 01-09 14:00 | 01-09 11:00 | 01-06 11:30 |
| 2 | 110 | 0 | -1 | 2 | 01-09 15:00 | 01-09 14:00 | 01-06 15:00 |
| 3 | 90 | -50 | -49 | -2 | 01-10 10:30 | 01-09 15:00 | 01-09 11:30 |
| 4 | 100 | 0 | -1 | 2 | 01-10 11:30 | 01-10 11:00 | 01-09 15:00 |
| 5 | 89 | -15 | 0 | -30 | 01-10 14:00 | 01-10 14:00 | 01-10 11:30 |
| 6 | 88 | -14 | 0 | -28 | 01-10 15:00 | 01-10 15:00 | 01-10 15:00 |

三周期均只含上述六根，不向m60首日补前半日；首日至末日之间的标准端点已经连续。READY样本的SSE日历明确扩至01-11，3/4/5/6/9/10/11开市、7/8休市；历史范围仍截至10号，future_calendar实际读取10/11号并选出下一端点。其余全零用例保持原日历，不让新增未来记录改变既有预期。

| 周期 | 历史日历范围 | 完成根数/最后根 | 手写下一端点 |
|---|---|---|---|
| m60 | [2023-01-09,2023-01-10] | 6 / 2023-01-10T15:00:00+08:00 | 2023-01-11T10:30:00+08:00 |
| m90 | [2023-01-09,2023-01-10] | 6 / 2023-01-10T15:00:00+08:00 | 2023-01-11T11:00:00+08:00 |
| m120 | [2023-01-06,2023-01-10] | 6 / 2023-01-10T15:00:00+08:00 | 2023-01-11T11:30:00+08:00 |

这组人工MACD不声称由六个收盘按EMA生成。除前述时钟、临时Session/lake_root和全新cache隔离外，业务计算仅将forecast_query_service.recover_projection替为返回独立给定ProjectionState(13,27,0)，其13-27=-14、DEA=0与末根一致；不替换reader、_load_series、load_entry、precheck_next_bar、future_calendar、forecast、get_forecast/put_forecast或响应。现有m1 fixture还替换日线load_entry，**不得整套复用**；只沿用上表人工数值及独立投影状态。计数包装必须调用原函数。这是校准隔离下的真实分钟接入测试，不是EMA精度或正式来源性能验收。

逐项字面预期：末根ordinaryState='DULL'、direction='BOTTOM'，在第6根满足当前绿段两根后首次激活；近谷是第3根close=90/DIF=-50，不能提前因第5根价格较低就激活。预测status='READY'、barsAhead=1、selectedReference='NEAR'、farEvaluated=False、结构形成条件非空，下一端点按上表。sourceInputId/calendarInputId和条件id只在原debug位置断言，普通响应不新增字段；普通/debug公共字段完全一致。

每周期先发普通冷请求，再发同一period/asOf/mode及NOW的debug热请求：两次源加载各bars/indicators签名一次、各历史范围查询一次；pair合计1，第二次0且不重新step。recover_projection和future_calendar各两次；get_forecast两次，第一次未命中、第二次命中真实InternalForecastResponseDto，forecast与put_forecast合计各1。不能把热缓存写成跳过校准或未来日历。两次forecastId相同；第一请求发布的真实InternalForecastResponseDto与第二次debug的sourceInputId/calendarInputId/条件id逐项相同，只观察已有缓存字段，不额外查询或调用计算helper生成expected。latest与显式REPLAY是不同身份，不跨mode要求forecastId相同。缩范围前后身份另沿用用例5的合法长open_dates entry和同一实际prefix/asOf比较，不另造旧算法分支；相同来源及未来日历内容的全部结果身份必须保持。

用例17的签名故障点逐项固定：进入首签名前已超时，两签名均0；bars成功返回时超时，调用仅bars一次；indicators成功返回时超时，两签名各1。三种均raw/pair、范围日历、step和本次cache.put为0。另设bars调用中抛原来源错误或取消且人工时钟同时过期，原错误/取消仍保留、indicators为0，不能被后置时间检查覆盖；正常对照两签名各1、raw复用及读取次数沿用例3/4。现有raw/范围日历/单日成功后过期、旧对象保护和预测发布检查继续保留。计时全部用人工时钟，不sleep、不测真实性能。

| 用例 | 输入及必须断言 | 主要测试落点 |
|---|---|---|
| 1 范围函数合同 | start/end双端包含，start=end，范围内自然日含周末；包装原execute，绑定SSE/start/end、只2列/1查询，开市返回[6,9,10]。start>end零SQL拒绝；末日缺失/无行拒绝；正常同范围通过 | 识别API文件 |
| 2 单日合同 | 临时SSE开市True/休市False各1查询、精确日过滤；无记录/NULL/重复及替身错误date/bool拒绝，SZSE同日记录不替SSE。不得读其他日期或pretrade_date | 预测API文件 |
| 3 三分钟冷加载 | 三周期实际临时Gold首日6、当前10，按字面端点和日历构造；顺序为两签名→一次pair→范围[6,10]→完成过滤，目标行/字段检查真实执行，最终事实与手写样本一致 | 识别API文件 |
| 4 热raw复用 | 同源/同业务日/同日历第二次调用：各签名保持原次数，pair=0，范围查询=1，返回原同一entry；raw、标签、指纹、旧响应不改。不能为了缩日历再读一次 | 识别API文件 |
| 5 日历变窄不是源修订 | 构造合法已发布entry且open_dates含6号以前开市日；新查询只返回实际范围，原raw/processed相同。允许一次候选更新open_dates，step=0、源id/事实不变、旧对象不改；第三次同请求复用新entry | 识别API文件 |
| 6 空/首尾/未完成 | 空raw、单根、首日只后半日、尾日缺最后完成根、当前尚无完成端点分别覆盖三周期；范围从raw/业务日计算，原EMPTY/DELAYED/完成筛选保持，不填根、不把raw改processed | 识别API文件 |
| 7 20点及休市 | 10号19:59业务日仍9号、20:00切10号，周末业务日回前一开市日；原context真实查询及flight隔离保持。范围end是上海自然日，start按实际raw/业务日 | 识别API文件 |
| 8 行情缺口 | 缺范围内开市行情/中间端点、重复/乱序、真实两源错位仍失败；周末无行情正常。保留第二批expected逐项核对，禁止恢复sorted(set)或重复reader检查 | 识别API文件，复用第二批节点 |
| 9 范围外历史开市 | 首根为10号，显式6号合法标准端点→补查一次、EMPTY、无target/条件/source/calendar身份；普通/debug公共事实相同，forecaster/校准/future_calendar/get_forecast/put_forecast零调用 | 预测API文件，三周期 |
| 10 范围外休市/缺记录 | asOf7号补查一次→400；6号行被删除或NULL→500来源错误；不能返回False/EMPTY。配6号正常True对照 | 预测API文件，三周期 |
| 11 范围内资格 | raw首日6号，asOf6号合法和7号休市，is_open_date均0；首日边界恰相等不补查。7号400；合法已有前缀按原状态，日历错误不另补一次掩盖 | 预测API文件，三周期 |
| 12 空raw早期请求 | raw=()且业务日10号，asOf6号开市→一次补查、EMPTY；asOf10号范围内→零补查、EMPTY；不先断言empty就跳过资格。识别endDate早于首根另得EMPTY、零单日查询 | 两API文件 |
| 13 原下界/未来端点 | 人工表额外加入1989-12-29开市，分钟asOf仍400且0补查；11号未来日期仍400且0补查；未来端点另用10号10:00的人工now（原context业务日为9号），请求10号10:30/11:00/11:30分别400且0补查。格式/时区/非标准端点由原HTTP解析在源前拒绝 | 预测API文件 |
| 14 身份/未来日历 | 三周期分别使用上述非零M1真实分钟夹具，断言6根/DULL/BOTTOM/NEAR/READY及手写下一端点；同一prefix/asOf/mode普通冷→debug热，真实future_calendar/预测缓存确实执行，按上文分层次数检查。缩范围前后身份不变；原跨周末及缺未来记录拒绝另保留，不加历史日期进入未来digest | 预测API文件，独立M1分钟夹具；不得使用全零或替换load_entry |
| 15 追加/真实修订/日历变更 | 新完成根只追加step；源旧数值修订仍从空算；有效范围内开市标志变化仍重新核对/缺行情拒绝，范围外旧日变化不使有效entry失效。旧对象及旧响应保持 | 识别API文件及既有研究人工节点 |
| 16 共享与次数 | 原重叠flight由一leader实际加载一次pair/范围查询，waiter共享结果，失败两侧一致、后续新调用可成功。先后HTTP各一次范围查询合法，不构造跨请求日历缓存 | 识别API文件及原shared_loads回归 |
| 17 失败/截止/取消 | 按上文首签名前/bars后/indicators后分别到期，签名调用次数分别0/1/2，首份到期不得继续第二份；原错误/取消与到期同时发生仍保留原异常。另覆盖raw后、范围查询成功后、单日查询成功后过期，逐步停止。范围失败保留旧entry；单日失败可保留合法源entry但无预测发布；原Async/Future取消和F06/F07优先级保持 | 两API文件 |
| 18 日线及旧调用方 | day查询绑定1990至原now，读源/完成日/预测及普通debug事实保持；4处研究替身必填start并按[start,end]过滤，旧快照/历史/修订人工预期通过；不加默认兼容参数 | 两API文件及两个研究测试文件 |
| 19 前两批及真实接入 | reader全套、投影次数/坏缓存/资源清理、分钟主图全字段/少字段保持。两API走实际临时Gold/SQLite及原路由；预测成功必须使用用例14非零六根，证明到达校准/未来日历/预测缓存，不以全零NO_CANDIDATE代替。另验EMPTY/400/来源500及根数/范围/SQL次数 | 原第一、二批节点，新增两API最小真实隔离链 |

所有时钟/取消故障使用人工时钟或替身，不靠耗时超过4秒制造超时。SQL次数包装真实execute，不再查COUNT取行数；返回范围由同次结果观察。断言源码SHA、读取源码验证未改、真实行情重放、全市场/全历史读取均不是本批测试办法。

4处替身分别是snapshot_consumers的source_boundary.calendar、daily_source.calendar、test_historical_prefix_and_zero_return_to_dull_clone_in_every_period内的lambda，以及r4_internal_results的source.calendar。统一改为必填`(session, *, start, end)`并以`start <= day <= end`过滤原人工日期，保留原session断言和业务expected。不能用`**kwargs`吞掉start，也不能让替身忽略start后冒充范围已验收；真实SQL范围由用例1/3/19另外证明。

#### 0.6.7 编码顺序、分组验收及第四批交接

1. 开工先复核70659f763及本节实际调用方/其他dirty文件，更新新增硬口径→代码/测试对账。先加用例1/3/9的人工样本，使原1990查询和早期asOf配合缺口可被抓住；旧实现的合法早期asOf本来可用，不能写成“旧版早期asOf已经错了”。
2. 先实现source两个函数及所有显式参数调用，在同一开发批次同步query日线/分钟分支和4处测试替身，不交付缺start的中间状态；不留兼容重载。
3. 接着接入forecast范围外一次单日资格判断和原下界，保留未来日历、400ms及退出发布，完成19组相关正反例。
4. 分组回归，独立按本节及§0.4/0.5联合审计，逐条记录实现/测试/参数/行数/未覆盖边界。原四文档同步已实现与未执行，开发结束停在第三批测试轮执行前；之后只按另行确认的§0.7复测，不自动提交、启动第四批或恢复P4采样。

开发验收统一用现有`.venv/bin/python -B -m pytest -q`，每组超过60秒停止查因，不安装依赖；固定分组如下，实际执行成绩见§0.6.10：

| 分组 | 精确范围 | 禁止扩大 |
|---|---|---|
| 来源/识别 | `tests/web/test_wealth_index_detail_xxm_api.py`整文件，含新batch3参数 | 临时来源，不接正式库/Lake |
| 历史预测 | `tests/web/test_wealth_index_detail_xxm_forecast_api.py`新增全部test_p4_batch3_；§0.4.7原26例，加`test_real_route_source_empty_static_and_delayed_no_fake_conditions`、`test_single_calendar_endpoint_and_used_prefix_identity`全4参数、`test_future_calendar_gap_and_non_boolean_refused`、`test_calibration_failure_does_not_read_future_calendar_or_cache` | 不整文件触发test_actual_source_calibration_solver_models_and_encoding_share_budget的290根计时样本；不以校准替身宣称真实精度 |
| 研究内部消费者 | `test_xxm_r4_internal_results.py`整文件；snapshot_consumers仅使用source_boundary/daily_source或直接calendar替身的节点，完整清单见下段 | 人工输入，不运行研究CLI/冻结文件 |
| reader及公开分钟 | `tests/test_major_index_mins_reader.py`、`tests/web/test_index_detail_minutes_api.py`各整文件，分开执行 | 不修改第一、二批reader/主图规则 |
| 公共保障 | forecast_validation整文件，§0.4.7 RC93三个节点及P4工具三个节点，`tests/web/test_xxm_shared_loads.py`整文件 | 不重复跑全部研究或Wealth |
| 架构/文档 | 根三份架构文件；四文档完整性/链接/限定diff/旧签名调用检查 | 不把结构检查当性能或业务通过 |

snapshot_consumers精确节点：test_product_latest_snapshot_copy_stays_independent、test_product_history_checkpoint_restore_stays_independent、test_product_incremental_load_uses_validated_snapshot、test_product_invalid_snapshot_does_not_replace_cached_result、test_count_zero_returns_new_empty_state_without_snapshot_or_checkpoint（两参数）、test_real_thousand_bar_checkpoint_boundaries（4参数）、test_past_prefix_and_empty_response_do_not_use_future_confirmation、test_increment_failure_after_real_step_preserves_old_entry、test_source_revision_rebuilds_without_restoring_old_progress（两参数）、test_load_entry_cache_separates_rule_connection_and_source_identity、test_clone_restores_formal_identity_and_isolates_mutable_state、test_clone_rejects_wrong_source_snapshot_without_changing_parent、test_historical_prefix_and_zero_return_to_dull_clone_in_every_period（四周期）。这些既有大根数人工边界只做原必要回归，不作为性能样本；如组超60秒，停止分析后按节点拆组，不skip或改expected。

前三批交付唯一精简后的真实加载实现、升序raw/processed、原entry/结果合同及明确的范围/单日/未来日历职责，先供第三批测试轮复用。其结果交管理员review后再确定第四批；第四批的观察仍须分别包裹实际调用一次，不能恢复原1990分钟查询/完整DESCRIBE/其他指数验收，也不能复制计算器或为测量再查数据。本开发批不承诺4秒已达标，少量复测也不能替代第8批正式验收。


#### 0.6.8 第三批开发前独立文档审计（2026-11-02）

本节为开工前的文档审计记录，不作为已实现证明；当前开发及回归事实见§0.6.10。

在完成草稿后另轮重读§0.6全部编码片段、矩阵和原三个生产文件/实际消费者，未以第一、二批通过代替本批设计核验。CodeGraph explore/callers用于加载及预测影响面；calendar_dates同名聚合结果混有交易助手函数，已用当前源码引用和AST补核：产品仅本query调用，研究测试确有4处替身，交易助手不改。核对TradeCalendar模型、现HTTP参数/异常映射、MarketPageContextQuery、future_calendar、缓存发布和人工测试，没有读取正式库/Lake。

| 检查项 | 本轮处理及结论 |
|---|---|
| 方案到代码是否完整 | 目标/三个生产文件/四测试文件、必填start SQL、单日函数、分钟与日线分支、资格检查、失败/预算和19组用例均有明确落点；无新增配置或公共结果字段 |
| 是否只是缩日期却漏调用方 | forecast显式早期asOf、空raw、原1990资格、研究4处替身均纳入；不保留无start兼容入口，不误改同名交易助手函数 |
| 日线和加载历史是否被误改 | day保留原1990起点/顺序，分钟仍实际完整raw、原minute_request及业务日，结果窗口/asOf不冒充加载截止；原SSE/端点/20点切换保持 |
| 是否把查询次数写得过强 | 已改为每次成功_load_series一次范围查询，读源前失败不补发；上下文、单日资格和未来日历分开计，先后HTTP不要求跨请求缓存 |
| 缓存与结果身份 | 正常热请求复用raw，范围收缩不设revised、不改fingerprint/key/Spec；来源未变时仅首次规范内存open_dates可候选更新。正常追加、真正修订、有效日历变更仍走原检查 |
| 失败保存是否相互矛盾 | 源阶段失败无候选发布；源成功后单日资格失败允许合法源entry保留但无预测结果。此次补齐每一份签名的原remaining前/后检查，bars成功后超时即停止，不能再做indicators；原错误/取消不被时间检查覆盖。无新预算、文件校验、线程或恢复文件 |
| 用例能否指导开发 | 19组均写输入、正反预期和文件；用例17明确两签名0/1/2次的故障断言。用例14/19另列三周期非零六根M1及时间、DEA、下一端点和冷热次数，只隔离校准，真实分钟读取/日历/预测缓存继续执行；全零只证明静态分支，不整套复用替换load_entry的日线m1。保留原clone/未来端点独立时钟及模型合同依据 |
| 当前是否可宣称实现/性能通过 | 不可；本轮只有设计、静态源码核对及文档检查。业务回归、查询参数/次数的实际断言、正式源及性能均未执行，不用前两批438例冒充第三批验收 |

本轮文档完整性三组、四文档32处本地链接、第三批新表格列数及限定diff检查通过；两个编码片段解析通过，19组用例编号完整，既有回归节点存在，13个受影响snapshot测试调用方和4处替身逐项核对。没有执行这些业务节点。

后续独立联合审计发现的两处设计缺口已在本轮补齐：逐份签名之间的截止检查，以及真正到达预测缓存的非零分钟样本。当前执行要求以修正后的§0.6.3/5/6为准，复核结论见§0.6.9；不再以原草稿审计概括代替这两处具体断言。本轮未改代码/测试，也未提交或推进第四批。

#### 0.6.9 开发前的前三批联合文档审计（2026-11-02）

本节记录编码授权前的联合文档复核；本批实现、测试和开发后独立审计统一见§0.6.10。

| 上下游交接 | 联合核对及约定 |
|---|---|
| 已完成与拟开发分开 | 第一批5084ef939、第二批70659f763及各自成绩保留；第三批仅§0.6设计。四文档文首与对应章节同步这一停点，不让旧“第二批未提交”误导后续 |
| 第一批响应投影/缓存完整重验 | 第三批不改project、schema、get_forecast/put_forecast或响应整理；原识别0/1次直接验证、预测投影0次重建、缓存交接1次完整验证由原节点继续守护 |
| 第一批清单/signature/prepared | 日历start不是minute_request.start_date；请求仍原None及业务日，prepared key/覆盖/pop/首次链接/失败后新请求保持。热复用raw不强迫reader为消费清单而重读，不重新引入第二轮文件检查 |
| 第二批目标SQL与必要检查 | 第三批不改reader，继续一次目标SELECT/元数据/行检查及原错误码；不以日历为理由恢复完整DESCRIBE、其他指数验收或未消费字段检查 |
| 第二批升序及两源对应 | 第三批直接使用已验证raw[0]确定日期，read_minutes保持一次pair/一次逐根构造；不另造整份键、排序修复或重复扫描来源 |
| 完整性分工 | reader管目标字段和顺序，source管两源/原生bar，assert_continuous管本次开市日及端点；第三批只改变日历的适用范围，仍逐项expected核对，日线及分钟缺口/重复拒绝保持 |
| 先后顺序和编号 | 第二批先提供完整升序raw，第三批才定日历和completed，之后原processed/状态/指纹/发布继续；不先猜日期、不裁前缀、不把日历范围加入编号。合法旧缓存首次更新范围不等于从头识别 |
| 预测和历史窗口 | 同次源/上下文交接不变，仅范围外早期asOf按一次单日资格补查；不增加第二次范围查询，不更改未来日历身份、EMA或有限价格解，合法EMPTY和原请求边界明确 |
| 资源/失败/预算 | 第一、二批reader Timer/连接/双源等待仍先按原finally清理；第三批每份签名及日历/资格查询使用原截止。首份签名耗尽4秒后不做第二份；错误/取消保留。无新线程/事务/保存，源/预测候选分阶段，原退出后检查/锁内检查继续生效 |
| 正向预测是否实际到达 | 非零六根M1在真实分钟加载后形成DULL，三周期下一端点逐项列明。仅校准隔离，真实future_calendar/forecast/缓存继续运行；普通冷与debug热分别核调用次数及身份。全零与旧日线m1不能替代这项证据，不把此隔离测试写成真实EMA精度或性能验收 |
| 第四批依赖 | 第三批需先完成独立及前三批回归，第四批才设计观察/测量准备；观察不得额外读取或复算，不恢复已清除工作；原P4真实性能和管理员页面验收继续单独保留 |

本轮补齐上述两处后，重新从调用顺序、每步截止、两类夹具实际到达位置、冷热次数/身份及前三批交接进行独立复核，并对照原专项§4.3/§6/§11、技术方案§18和产品说明。复核未发现新的本批未决规则、前后顺序倒置、前两批保障被撤销或方案/LLD冲突。当前第三批设计可供开工review；实际编码及19组测试仍待另行授权执行，不能据此宣称实现或性能通过。本轮只改四份原文档，正式运行实现仍是第二批提交，未运行第三批业务测试或性能采样。

补齐后的静态检查通过：两个文档Python片段可解析；仅用内存替身执行文档加载片段，验证签名前到期、bars成功后到期、indicators成功后到期、bars原错误与到期同时发生、正常返回五种情况，实际签名次数及后续raw/日历是否执行均符合本节。三套六根字面样本逐项核对DIF/DEA/柱关系、标准端点连续性和下一端点；19组矩阵、既有回归节点、表格列数及四文档32处本地链接检查通过。文档完整性三组及限定diff空白检查通过。这些只验证设计片段及文档，不是执行第三批业务回归，也没有测量正式性能。


#### 0.6.10 第三批开发交付及独立审计（2026-11-02）

管理员已明确授权第三批编码。本轮生产仅修改source.py、query_service.py、forecast_query_service.py；测试仅两个原web文件和两个研究测试文件，后两者仅迁移4处calendar替身的必填start及范围过滤。其他工作区修改保留，没有提交、推送或部署。

先完善临时Gold/SQLite夹具，再在原生产实现上确认7个定向参数样本能抓住旧签名、旧加载顺序和缺少单日补查的问题；随后按§0.6.2—4实现，原7例通过。合法早期asOf在旧实现本来就是EMPTY，回归捕获的是缩日历后必须保留的一次单日资格交接，不能把它记成旧版本业务结果错误。

| §0.6.6组 | 实际代码及测试落点 | 实际结果 |
|---|---|---|
| 1 范围函数 | source.calendar_dates；test_p4_batch3_calendar_range_sql_and_errors | SSE、两列、双端日期绑定及一次execute，单日/周末合法；反向范围零SQL，空/缺末日拒绝 |
| 2 单日函数 | source.is_open_date；test_p4_batch3_single_day_real_sql_contract、single_day_rejects_invalid_facts | 真开市/休市返回bool；缺行/NULL/重复/错日/错bool/SZSE替代均拒绝；只执行同日两列查询 |
| 3 分钟冷加载 | query._load_series；real_minute_cold_order_range_and_hot_reuse三周期 | 两签名→一次pair→[01-06,01-10]；完整根数12/9/6，最后01-10 15:00，NONE/空事件符合手写预期 |
| 4 热raw | 同上第二次真实加载 | 签名各1、范围查询1、pair和step为0，返回同一entry，旧状态不改 |
| 5 范围收缩 | narrow_calendar_is_not_revision及真实M1分钟预测 | 合法长open_dates仅更新候选日历，step=0、原指纹/标签不变；随后复用新entry；旧对象不改 |
| 6 空/首尾/未完成 | raw_bounds_and_original_completion，三周期×五场景 | 空、单根、首日部分、缺尾及未完成根保持原完成状态；使用raw首日而非processed，无补根 |
| 7 业务日/休市 | real_context_cutover_and_weekend | 19:59业务日01-09、20:00变01-10；周末01-15业务日01-13，日历end仍自然日，无上下文替身 |
| 8 完整性 | real_range_still_rejects_gaps及原batch2完整性/真实错位节点 | 三周期缺整日/中间端点拒绝；原重复、乱序、两源错位仍拒绝，未恢复多余扫描 |
| 9 早期合法asOf | forecast早期开市单日测试及early_asof_http_contract | 三周期每请求补查1次，EMPTY；普通/debug公共事实一致，无校准/未来日历/预测缓存调用 |
| 10 休市及坏单日 | early_asof_http_contract三周期×四情形 | 明确休市400，缺行/NULL来源500，开市200/EMPTY；失败允许已合法源entry保留，无预测发布 |
| 11 范围内资格 | qualification_bounds_and_empty | 合法范围内/首日零补查，休市400，不用单日补查掩盖范围错误 |
| 12 空来源及识别窗口 | qualification_bounds_and_empty、signal_http_window_never_cuts_loaded_prefix | 空raw的早期合法asOf补查1次后EMPTY、当前零补查；识别早期窗口EMPTY，实际raw/processed仍完整12根 |
| 13 原下界/未来/格式 | qualification_bounds_and_empty及invalid_endpoint_rejected_before_source | 1989记录不扩大原资格；未来日/未来完成点400且零补查；非标准端点/无时区/错误时区在真实HTTP加载前拒绝 |
| 14 身份/未来日历 | real_minute_ready_cache_identity_and_next_endpoint三周期及原未来日历节点 | 六根DULL/BOTTOM/NEAR，下一日分别10:30/11:00/11:30，READY且结构条件非空；冷热及缩范围前后全部身份保持 |
| 15 追加/修订/日历 | append_revision_and_calendar_failure_keep_old_facts三周期 | 追加仅step新根，旧值修订重算；范围外旧日变更复用，范围内错误拒绝且旧对象/缓存事实不改 |
| 16 共享次数 | overlapping_loads_share_actual_range_and_recover及shared_loads原回归 | 真重叠两侧只加载一次pair/范围，成功同对象、失败同异常；随后显式新请求成功，无跨请求日历缓存 |
| 17 截止/失败/取消 | deadline_stops_at_each_stage、signature_error_preserves_priority、single_day_failure_keeps_published_source_and_priority及原F06/F07 | 签名前/首份后/第二份后分别0/1/2份，停止后续；raw/范围/单日后到期拒绝。原来源/查询错误及两类取消不被超时覆盖，无半份发布 |
| 18 日线/消费者 | day_keeps_original_range_order_and_values、day_and_latest_do_not_use_single_day及21个snapshot/39个internal样本 | 日线仍1990起、原先后和字段；day/latest不补查；4处替身同步迁移，原研究人工expected未改 |
| 19 前两批/真实接入 | 两API新增真实临时链及reader/公开分钟/投影/缓存/工具原回归 | 原reader与输出/坏缓存/资源保障保持；分钟预测未替换load_entry，只隔离校准，实际进入future_calendar、solver和缓存 |

表中省略前缀的新增测试名称，实际均带test_p4_batch3_前缀，位于本节两个web测试文件；原回归节点按§0.6.7和§0.4.7精确选择。没有修改研究执行代码、reader、计算器、Spec、预测数学、公共schema/API、配置或前端。

三周期M1的实际冷热次数：每请求bars/indicators签名各1、历史范围查询1；两请求pair合计1，recover_projection/future_calendar/get_forecast各2，forecast/put_forecast各1。缓存校准隔离状态仍为独立ProjectionState(13,27,0)，没有用它宣称实际EMA校准通过。主图完整指标及r4少字段继续经原reader，不新增文件验收或为了缩日历重读行情。

使用原`.venv/bin/python -B -m pytest -q --tb=short`，临时外层仅用subprocess的60秒上限防止组失控；不改产品时钟/预算。以下九组共610例通过，没有skip；先前定向运行不重复计入：

| 分组 | 精确选择 | 最终成绩 |
|---|---|---|
| 识别API | 原test_wealth_index_detail_xxm_api.py整文件 | 152通过，5.43秒 |
| 新预测 | 原forecast_api文件全部test_p4_batch3_ | 56通过，2.83秒，52个范围外原节点未选 |
| 既有预测 | §0.4.7原26例，加§0.6.7规定的real_route静态、single_calendar全4参数、未来日历错误及校准错误节点 | 33通过，1.92秒 |
| 内部结果 | test_xxm_r4_internal_results.py整文件 | 39通过，0.44秒 |
| 内存进度/历史 | §0.6.7列出的13个snapshot节点及全部参数 | 21通过，0.85秒 |
| reader | tests/test_major_index_mins_reader.py整文件 | 184通过，6.07秒 |
| 公开分钟 | tests/web/test_index_detail_minutes_api.py整文件 | 48通过，5.32秒 |
| 公共保障 | forecast_validation、shared_loads整文件，RC93三个及P4工具三个原节点及全部参数 | 61通过，2.91秒 |
| 架构 | 根三份架构检查整文件 | 16通过，13.68秒 |

上述耗时只是隔离回归运行时间，不是正式请求性能。预测文件的290根计时节点、正式数据库/Lake、研究CLI/行情回测、Wealth全量和页面采样均未运行。既有TestClient依赖弃用提示保留，未安装或升级任何依赖。

开发后独立审计重新核对三个生产diff、原读取/缓存/发布/with退出、实际HTTP消费者及4处替身，按本节19组逐项对账。CodeGraph explore用于加载影响面，同名日历结果不完整的部分由实际源码/引用补核；sync/status已完成且索引最新。生产新增逻辑与§0.6.2—4一致，来源指纹、forecast key/条件id、400ms和4秒起点、第一批prepared/完整重验、第二批目标字段/升序及一次两源对应都未改。未发现本批未落地要求、越界或前三批冲突。

四份原文档已同步本次停点；文档完整性三组、32处本地链接、第三批表格/19组矩阵及限定diff空白检查通过。当前第三批开发和上述限定验收完成、已随4debb8eb3提交；仍停在第四批之前。真实收益、正式P4来源/4秒性能及管理员页面验收仍待后续阶段，不能用本批610例宣称通过。

### 0.7 第三批测试轮：第三批开发后、第四批前的小范围复测（首错停止）

本节落实专项§12及管理员最新决定。第三批开发及610例隔离回归保留§0.6.10的事实；本节独立观察现在实际需要多久，不把正确性成绩当性能。第三批测试轮不占原第四批编号，不修改产品/工具/测试/配置文件，不新增仓库入口或维护脚本。设计文档先提交04ff91ad8，再按管理员授权执行本节。已执行首个真实请求并失败停止，实际证据及限制见§0.7.9；本节执行合同和§0.7.8准备审计仍保留。

#### 0.7.1 目标、当前依据和开跑条件

已核对现source/query/forecast、正式两个路由、xxm_page_request_audit.py的原隔离App/观察函数/计数合同，以及现Settings来源。原CLI样本只1/20；page的samples=1会混入主图、指标、九转和双页组，不能原封不动套用。当前_observe已记录源加载、series缓存、forecast缓存及computeSeconds，后者从原READY处理的第一个perf_counter开始，到原预测build含复制/编码/退出/发布完成；无须修改产品或新加计时包装。

执行前仅确认下表已具备，不先发健康检查、预热、探测SQL、图请求或额外来源读取。原参数和数据校验由首个真实请求执行；连通/数据失败立即停，不预读一遍再正式测。

| 条件 | 固定要求及当前证据 |
|---|---|
| 当前代码 | dev-interface当前工作区已经包含第三批实现，610例成绩见§0.6.10；读取当前文件的新子进程，不依赖管理员8000服务是否重载，也不重启/patch现有服务 |
| 最终Settings | 子进程显式使用现GOLDENSHARE_ENV_FILE=.env.web.local；app_env须显式local/dev、原分钟开关开启、鉴权沿原配置。父子仅比原_settings_identity，不输出连接凭据，不覆写文件或改目标 |
| 来源边界 | prod现连接仅用于SSE日历；分钟仅/Volumes/datasource/data_lake正式Gold的000001.SH、freq=60；bars仍四键+close，indicators仍四键+DIF/DEA/柱及原参数/版本必要检查。SSE日历只沿原上下文、实际分钟范围及未来端点查询，不提前全表预读。按正式load_entry的latest完整前缀/完成根；limit=500不是读取截止。保留20000根/5000分区及原读取/并发预算 |
| 本机条件 | 已有Python虚拟环境、HTTPX 0.28.1、SQLAlchemy/uvicorn/DuckDB可用；最近只读检查确认m60两目录存在。只查配置/目录元数据，尚未证明DB连通或物理行情齐备；首个请求失败按原错误登记 |
| 执行授权 | 管理员已明确要求先提交文档、再执行第三批测试轮；工具本机/网络执行权限已按规则取得，不把它当作切源或额外业务开发 |
| 正式执行边界 | 不安装、不改env/连接/源码/预算，不启动或重启原服务，不访问其他标的/周期，不做写库/写湖/备份/恢复，不落盘业务正文、结果或恢复文件 |

#### 0.7.2 固定两组、四次上限和请求参数

| 次序 | 独立进程/App | 实际业务GET与参数 | 条件 |
|---|---|---|---|
| 1 | 识别组新进程、新isolated_app及空XxmCache | /api/v1/wealth/market/index-detail/minute-xxm-signals；tsCode=000001.SH、freq=60、limit=500 | 首次请求，不预热；无debug/startDate/endDate/asOf |
| 2 | 仍用识别组同一App、缓存和HTTP客户端 | 与第1次完全相同 | 第1次来源/时限/观测全部合格且已无活动请求后才发；不清缓存，不假定命中 |
| 3 | 识别组退出且回收干净后，预测组另起新进程/App、空XxmCache | /api/v1/wealth/market/index-detail/xxm-key-point-forecast；tsCode=000001.SH、period=m60 | 预测首次，源和预测缓存均不继承识别组；不传asOf/debug/价格参数 |
| 4 | 仍用预测组同一App、缓存和HTTP客户端 | 与第3次完全相同 | 第3次合格、活动请求结束后才发；按实际访问记录缓存，不强迫求解/写缓存 |

四次是全成功时的上限。任何请求失败，整轮停止，包括本组剩余请求及后续预测组；不补齐、不重试、不换日期。两组最多各2次，顺序串行，不并发。每次均为当前真实latest；同组首/末时点、完成根/数量或身份变更则不可比，立即停止，不冻结业务时钟。两个组之间来源可能正常更新，只如实分组登记，不能按不同接口的digest相等判断来源，更不能将两组拼成缓存A/B。

“首次/再次”是请求顺序；只有原记录实际hit才写命中。新产品进程也不会清OS、磁盘或prod数据库缓存。再次请求沿原签名/日历/校准/缓存政策执行；尤其预测命中前仍可能校准/查未来日历，不增加跳过逻辑。无缓存或无候选时如实记录，不能手工塞缓存、改旧行情或增发请求来取得热结果。

#### 0.7.3 一次性调用与现有工具合同的衔接

只在/private/tmp准备一个可删的一次性调用片段，父模式监督、worker模式复用现有isolated_app；固定从仓库根用当前.venv/bin/python -B运行。父/worker属于同一临时片段，不新建仓库脚本、测试、参数或通用框架。执行前已完成片段语法、请求清单/次数、通信与退出路径静态核查，再发首个真实请求；不额外运行业务样本。

**仅复用原工具的下列能力，不调用其正式任务清单：**parse_args/_new_group/_group_from_json/_settings_identity、isolated_app及其自动进入的_observe、collector.metrics。父进程以原参数构造合法上下文：periods=[m60]、mode=normal、samples=1、as_of=None、tool=page、scenario=mixed_single。父子各按原_group_from_json核验，绝不将samples改成2或发明新scenario绕原合同。这个对象只承载现有观察上下文，不代表执行原混合页面组。

一次性片段另有固定的requestKind，只允许signals或forecast，由上表顺序决定，映射到本节两条常量路径；每组真实发送循环严格为2次。两个请求头X-Request-ID精确为`{groupId}:mixed_single:1:1:1`和`{groupId}:mixed_single:1:1:2`：round仍1、tab仍1、sequence递增，符合原samples=1的观察合同，不能写成round=2。父进程只在上一组完整成功和清理回收后生成下一groupId。

**不调用main/run/run_audit_group/_run_audit_group_worker/_run_node或mjs，不触发/__audit__/context、reset、metrics等私有HTTP。**原mixed_single完整组应有5个业务请求；本轮每组2次不能通过原validate_summary，也不得修改/patch它、添加假记录或把计数放宽。仅用collector.metrics(cache)直接取得已有内存观察，以本节独立白名单摘要报告“第三批测试轮”，不输出原P4通过标志。这里改变的是一次性执行安排，原CLI和正式验收合同完全保留。

isolated_app仍使用原正式路由、本地开关、require_quote_access及只读Session、原缓存/资源清理，lifespan关闭，绑定自己的127.0.0.1:0，不碰8000。除工具已有的_observe外，不替换source、load_entry、reader、calculator、recover_projection、forecast、公开模型或返回结果；不新增业务计时字段。worker当前进程内的缓存隔离不影响管理员服务。

#### 0.7.4 一次HTTP收取、计时和资源关闭

每个worker仅建一个现有HTTPX AsyncClient供其最多2次顺序请求：trust_env=False、follow_redirects=False、原生AsyncHTTPTransport显式retries=0，不使用ASGITransport/MockTransport；只能访问本App的本节路径。不跟代理/重定向，不做自动重试。客户端配置是临时调用参数，不新增Settings。HTTPX现有环境版本0.28.1已核对，不安装或升级。

单次外层用asyncio的5秒总截止覆盖请求发出、所有正文流读取及流关闭；HTTPX本身timeout=5只约束各阶段，不能拿它冒充总时限。5秒到期触发取消，不保证取消收尾本身瞬间结束；后续关闭仍计入本组50/60秒，不能写成请求在5秒内成功。复用同一个原始HTTP响应，`async with client.stream(...)`里用aiter_raw读取，Accept-Encoding=identity，遇非identity编码、意外跳转或响应X-Request-ID不等于本次请求id即停止；每段累加前检查识别1MiB/预测32KiB上限，超限不再收取。正文只在内存解析一次，不用response.clone、再次fetch、追加读端点或重新构造整份内部模型。每个响应和组末AsyncClient均在上下文退出时关闭，取消/错误也关闭。

HTTP计时t0在实际client.stream调用前、t1在最后一个正文段读完后；HTTP时间=t1-t0，使用同一worker的perf_counter。它包括真实本机网络、服务端来源读取、计算和最终编码/发送，排除App启动、读完后的JSON解析/观测整理及最后清理；后几项另计入本组50/60秒预算。若没有收完正文，t1和完整HTTP耗时为null，只记截至失败的elapsed与错误，不能把它当成功计算时长。

预测处理时间只取原_observe的computeSeconds×1000，不另包计时、不从HTTP减去读源反推；和HTTP分列，不能相加或跨进程相减。原首次READY处理前的4秒读取与内部400ms预算仍生效。缺预测computeSeconds时不填0、不算400ms通过；先结合dataStatus/异常说明该路径未完成或未进入。

首个响应收完后先检查HTTP/字节/最小身份和预算，再等待原collector.active/workers/_entries/_flights/_pair_owners均清空，才直接取collector.metrics(q._CACHE)的一次快照；等待用原工作截止，不为看状态再发HTTP/读源或调用cache.get。之后核对本请求恰1条观察记录、loadIds真实存在且没有新业务请求，才决定是否发第二次。原metrics中的httpSeconds/clientSeconds可能未由Node填充，保持原样；本轮另存自己的HTTP时间，clientSeconds不伪填为TypeScript客户端耗时。

上述资源和timeout语义已用Context7及本机版本核对，参考[HTTPX异步流与关闭](https://github.com/encode/httpx/blob/0.28.1/docs/async.md)、[分阶段超时](https://github.com/encode/httpx/blob/0.28.1/docs/advanced/timeouts.md)。本轮不声称执行了原TS解码/调度/前端5秒或页面验收，不调用Node，也不新增相应测试。

#### 0.7.5 同一结果的观察、比较和输出

仅从已收取一次的普通JSON及原collector记录取下列白名单，不额外读取：

| 对象 | 固定记录及来源 |
|---|---|
| 请求 | groupId、requestKind、sequence、固定params、HTTP状态/错误码、实际字节、httpSeconds或失败elapsed；识别dataStatus取JSON.dataStatus.status，预测取JSON.dataStatus并另记JSON.status/reasonCode。识别没有预测的根status，不得访问错字段；JSON只解析一次 |
| 识别实际输入 | JSON source.startTime/computedThrough/indicatorVersion、meta窗口首末/行数；原观察sourceInputId和prefixRows。source.startTime是计算前缀起点，不用500根首点替代 |
| 预测实际输入 | 原观察windowStart/windowEnd（该处是实际前缀）、computedThrough/prefixRows/sourceInputId/calendarInputId；JSON forecastId、targetEndpoint/barsAhead及原版本。普通JSON没有内部源id，不补进公共返回 |
| 缓存/读源 | 原request/loadIds及对应load的seriesCacheRead/次数、两份signatureChecks、pairCalls/barsCalls/indicatorCalls、forecastCacheRead/Write及次数、原cacheBytes/entries。只读同次观察，不为计数再调用被观察函数 |
| 结果一致性 | 同组比较原publicDigest、源/完成根/前缀数量/起止/窗口；预测另比calendarInputId/forecastId/targetEndpoint。正常文本/条件事实变化则不再算同源冷热比较，不选掉慢样本 |
| 退出和覆盖 | 实际尝试/服务端记录数量、剩余未发请求、错误阶段、cleanupSeconds/状态、进程是否回收。未返回或被强杀导致实际送达不明时写“未确认”，不猜0次 |

每组观察应最多2个request、2个load，载入失败时按实际更少；正式实现的共享/热缓存逻辑决定load记录数，不造缺失记录。单load原cache读取/pair/bars/indicators均不得多于1；预测单请求cache get/put均不得多于1。signatureChecks按实际登记，不新增文件身份检查。cacheBytes≤原64MiB、条目≤16；不清理真实业务数据或为了保留缓存改限制。

版本对照当前正式Spec，不复制已过时的版本常量：识别algorithmVersion/specHash对MAIN_SPEC，预测forecastVersion/forecastSpecHash对FORECAST_SPEC、detectorSpecHash对MAIN_SPEC；两者tsCode/period均须为000001.SH/m60。来源状态READY下该路径应提供的源身份、完成根、前缀数量须有真实值；但NO_CANDIDATE/PRECISION_PENDING下未进入的calendarInputId/targetEndpoint等合法null应保留，不能一概按“观测缺失”拒绝或补假值。computeSeconds按是否完成原处理记录，不将null当0。

同组第二次若与第一次来源/完成根/输入数量/日历或结果身份不一致，立刻记不可比并停止整轮，不按更新后数据重跑；两个新App之间只记录各自真实范围/来源是否一致，不要求识别与预测的publicDigest或接口字段机械相同。不同请求的HTTP与处理时间不混算平均或P95。

forecast结果合法NO_CANDIDATE/PRECISION_PENDING按原状态报告，同时将“实际求界/结果缓存是否走到”列为覆盖说明；不把快速前提拒绝或校准失败说成完整求界/热预测验收。只要HTTP和dataStatus正常且预算/观察合格，可以完成本组原定第二次；不改日期或额外增加样本去凑READY/命中。dataStatus!=READY则来源条件不满足，保留耗时并停止整轮，不据此认定当前完整行情性能合格。

#### 0.7.6 预算、失败与父子进程退出

每次HTTP和预测处理分别≤4秒/≤400ms，识别/预测正文≤1MiB/≤32KiB；临时HTTP总截止5秒用于取消，不能扩大原4秒通过线。原源、缓存、并发等预算全部保留。本轮没有新增阶段性能门槛，只有一次性输出总量≤64KiB、输入≤4KiB的通信限额，用于避免正文或日志无限留内存。

父进程每次只启动一个自己的worker，用当前解释器-B和该临时片段固定worker分支，Popen(shell=False,start_new_session=True,close_fds=True)。输入只含requestKind、原合法group和settingsIdentity摘要，不传凭据/任意URL/模块或源码SHA。父子各核对白名单、group及_settings_identity后再创建App；父进程不建App、不连DB/读Lake。父子同机的原monotonic只用于50/60秒退出控制，HTTP/compute耗时均在各自原进程内计算。

子进程stdout仅输出逐行JSON：started、request_started、request_finished、cleanup_started、finished；最多1+2+2+1+1=7帧，每帧带groupId/requestKind，相应请求帧带sequence及原requestId。started的pid/进程组必须与父实际启动的Popen.pid一致；只发自己的状态，不接收外部pid。request_started只证明准备尝试，不能冒充服务端收到；request_finished带本节有界白名单，错误也先报告已知证据。finished仅在HTTP客户端、隔离App和原finally都退出、活动/工作/关联表清空后产生。

父进程用非阻塞管道/selector逐段读取stdout与stderr，合计上限64KiB，单帧也不得越界；不使用无界capture/communicate保存日志。管道/解析/超量/错group/错pid/多发请求均失败，只保留有界已知摘要，不打印原stderr、凭据、traceback正文、完整行情或响应。父进程应核对每组实际业务上限2及固定路径/顺序，任何未知消息拒绝，不因子进程exit=0跳过验证。

沿原每组50秒工作、60秒含准备/最终检查/清理：50秒若worker仍在工作且未发cleanup_started，父进程向自己启动的该进程组发SIGINT，worker沿asyncio取消/KeyboardInterrupt退出请求循环、设置本App.stopRequested，进入关闭HTTP客户端及原App finally；不得吞取消后继续第二次。若已发cleanup_started，只等待原finally，不再发SIGINT中断正常关闭。cleanup_started在退出HTTP客户端和App前只发一次；其后不得产生新请求。58秒仍未退出向自己创建的进程组TERM，59秒仍存活KILL，60秒前回收和关闭管道。原临时App退出等待原请求/同步线程，随后释放监听/连接池、还原_observe；不得抢先恢复包装让旧线程继续运行。任何超时/取消/清理失败均记失败，不发本组第二次或下一组；父进程不能为了凑摘要继续占用进程。强杀后数据送达/完成未知须明确，禁止自动重试。

进程/HTTP状态只在RAM及白名单终端摘要；无数据库/Lake写入、业务结果/行情/恢复文件。运行中断没有续跑文件，本轮停止交管理员；任何后续重新执行需要单独确认，不能从中断位置自行补测。现有服务、8000端口、管理员会话和其他进程不受清理影响。

#### 0.7.7 停止判断、准备审核与交付

请求必须严格按以下顺序判断，前一项不合格即停止，不能先发下一次再汇总：

1. 原固定路径及参数、单对象/周期、序号/请求id、无重定向/重试、单次收取和字节上限。
2. HTTP200、合法一次JSON及原版本/period；状态、错误码和实际完成端点/前缀观测齐全，dataStatus=READY。错误时保留已知耗时，不补默认字段。
3. HTTP≤4秒；预测computeSeconds有限且≤0.4，原5秒收取截止和组50/60秒未超。未完成时间为null，不用失败elapsed替代。
4. 原观察与收到的同一响应对应，cache/读取次数及资源未超；再次请求的实际输入/身份一致，覆盖范围如实说明。
5. 活动/线程结束后才发下一请求；识别组finished、退出码及清理回收均合格后才创建预测组。全部4次或首次停止结果只交管理员review，不自动进入第四批。

一次性片段在正式读取前只做语法、固定请求清单/循环上限、输入输出白名单及退出路径的静态审查；0真实业务请求，不新建一轮采样/回归或修改仓库测试。本节的准备核对表必须能证明以下情况：

| 静态核对案例 | 固定预期 |
|---|---|
| 全正常 | 恰signals×2，识别清理后再forecast×2；两组各空产品缓存，无其他业务或私有HTTP |
| 第1/2/3次不合格 | 各自之后均无新请求；最大尝试数分别1/2/3，服务端实际收到数量按观察证据登记，送达未确认不猜0，也不补齐4次 |
| 同组来源变化/缓存未命中 | 来源变化停止；合法未命中只按真实记录，不强制预热/写缓存或变更策略 |
| 空/滞后/无候选/校准待定 | 空/滞后停止且不报完整行情性能通过；合法无候选/校准待定记录未覆盖路径，不伪称求界或预测缓存通过 |
| 旧CLI/原计数合同 | 不调用正式任务清单/validator，不改samples=2/旧计数，不伪造3个缺失请求；部分观察只报告本轮，不记完整P4通过 |
| 错误/取消/管道超限/退出不干净 | 原错误优先、响应/客户端关闭、只清本组进程，记录已知/未知，父回收后停止整轮 |

最后报告实际4次以内逐请求表、组内来源是否一致、实际缓存访问、当前是否在预算内、未走到的路径及退出结果。无第4批详细耗时拆解、旧/新A/B或P95结论；没有旧完整基线，不能据原4.174秒超时精确计算加速比例，也不能凭4次就取消后续正式验收。

第三批开发/610例、准备核对、本轮真实复测及完整P4分别记状态，不能互相代替。准备核对见§0.7.8；已获准执行的本轮真实复测见§0.7.9，首错停止后不再补测或自行进入第四批。管理员review结果后再决定第四批及后续范围。

#### 0.7.8 准备后的独立审计（2026-11-02，零业务请求）

本节完成后另轮从当前代码和原方案重审，未用第三批610例代替本轮真实耗时。CodeGraph explore核对isolated_app/AuditGroupSpec/AuditCollector，源码补核实际路由、普通投影字段、原compute计时、group校验、原CLI和完整组validator；不把同名函数或文档计划当作现状。审计中已明确SIGINT取消的实际传递、识别/预测不同状态字段、当前Spec对照和合法null，防止执行片段据模糊说法自行处理。

| 审计项 | 核验结论 |
|---|---|
| 阶段先后 | 专项§6/§12、LLD§0.3/§0.7、技术方案§19及产品说明均明确第三批开发→第三批测试轮→管理员review→再决定第四批，后续原编号保持；不以前置第四批开发阻塞本轮 |
| 目标/范围/次数 | 两个固定路径/参数，只有m60/上证/normal/latest，识别最多2次后清理回收，再预测最多2次；无图/九转/其他周期/私有HTTP，无额外预读 |
| 原工具是否真能复用 | 零业务内存核对用原parse_args/_new_group/_group_from_json得到合法mixed_single上下文；两种路径分别以sequence=1/2、round=1、tab=1通过原collector.start。原samples=2仍拒绝，expected_requests仍5；不改工具或把2条记录送原5条validator |
| 冷热及来源 | 每组原_observe新XxmCache，跨组新进程/App；无清OS/DB缓存承诺。同组输入/完成根/身份变更停止，未命中按事实记录，不强制缓存、不改变加载前缀 |
| HTTP和计算计时 | 原computeSeconds复用；HTTP单次收取，4秒/400ms分列；5秒总取消截止区别于HTTPX分阶段超时。现HTTPX 0.28.1支持所列流式/transport选项，未创建客户端或实际请求 |
| 正常状态不误拦 | 识别dataStatus.status与预测dataStatus分别取值；无候选/校准待定保留合法null并标未覆盖求界/缓存，不冒充完整预测通过，也不改旧日期凑覆盖 |
| 失败/取消/退出 | 首错停止整轮、原错误优先；5秒取消/流关闭、50秒SIGINT、58/59秒TERM/KILL及60秒回收均明确；只有自己子进程组，清理失败不启动下一组；送达不明不伪报零读取 |
| 输出/依赖/代码边界 | 只用已有来源/依赖/工具，片段限/private/tmp，无仓库代码或配置修改；输入4KiB/输出64KiB，正文只在RAM一次解析，摘要/管道有界，未新增维护入口或公共合同 |

独立审计未发现尚需拍板的规则、前后矛盾或需修改业务/工具代码的条件。文档完整性三组、四文档32处本地链接、新节8个子节/表格列数/四次固定清单及限定diff空白检查通过；这些不证明实际性能。当前具备按本节准备一次性调用并在获得执行授权后复测的文档条件；DB连通和实际行情合同仍交首个请求原检查，未提前登记为通过。当前只修改四份原文档，未写临时片段、创建App或做任何真实HTTP/数据库/Lake读取。

#### 0.7.9 实际执行、失败证据及独立核对（2026-11-02）

管理员要求先提交文档再执行；四份设计文档已提交`04ff91ad8`，未夹带第三批生产/测试代码或其他工作区修改。随后仅在`/private/tmp/xxm_batch3_test_round_20261102.py`准备一次性父/worker片段，按§0.7静态检查后运行；未修改仓库业务、工具、测试或配置。执行用当前`.venv/bin/python -B`及`GOLDENSHARE_ENV_FILE=.env.web.local`，通过原isolated_app和真实HTTP读取原prod SSE日历/本机正式Lake，未切源、预热或探测读取。

| 固定次序 | 实际结果 | 完整HTTP时间 | 预测处理时间 |
|---|---|---|---|
| m60识别首次，000001.SH/freq=60/limit=500 | HTTP503，XXM_BUDGET_EXCEEDED；137字节完整错误正文，超过4秒通过线 | 4.839964583981782秒 | 不适用 |
| m60识别再次 | 首错停止，未发送 | 无 | 不适用 |
| 独立空缓存App的m60预测首次 | 整轮停止，未启动该组或发送请求 | 无 | 未执行，不能填0或判400ms通过 |
| m60预测再次 | 整轮停止，未发送 | 无 | 未执行 |

唯一请求的`groupId=fa7d3c0bac7f4c5b99ebfff704d13954`、`requestId=fa7d3c0bac7f4c5b99ebfff704d13954:mixed_single:1:1:1`。父记录尝试1次，原collector记录服务端收到1次；没有重试、第二次识别、预测或私有HTTP。普通模式、latest、固定路径/参数及X-Request-ID相符，原观察字段`httpSeconds/clientSeconds`保持null，本轮4.839965秒来自一次性HTTP收取，不冒充TypeScript耗时。

| 同次原观察 | 实际证据与解释边界 |
|---|---|
| 服务端本请求 | startedMs=2583.0194167792797，finishedMs=7418.905667029321，terminal=error，errorCode=XXM_BUDGET_EXCEEDED；相对本组起点的时间，差约4.835886秒，不与HTTP相加 |
| load-1 | startedMs=3342.6873749122024，finishedMs=7408.683917019516，terminal=error；跨度4.065996542107314秒。原包装覆盖_load_series，其中包括签名、来源读取、日历、逐根识别和候选检查/发布等可能步骤；本轮没有阶段观察，不能说全是DuckDB、磁盘、日历、计算或校验耗时，也不能判断具体在哪一行到期 |
| 缓存及读源次数 | seriesCacheRead=miss，seriesCacheReadCalls=1；signatureChecks=2，pairCalls=1、barsCalls=1、indicatorCalls=1。计数仅证明已进入这些原函数，不证明两源读取完整成功；未发现同load重复调用 |
| 失败发布与可知数据 | cacheBytes=0、cacheEntries=0；无成功投影，实际前缀首末/根数、computedThrough/sourceInputId/publicDigest等均未取得，不能拿limit=500冒充已加载根数或认定来源READY。forecast cache为not_applicable、调用0次 |
| 退出与通信 | 原App/HTTP客户端关闭完成，cleanupStatus=cleaned，cleanupSeconds=0.11503804102540016；worker退出码1、已回收；含准备/核对/清理的组耗时8.103849541861564秒，管道合计2984字节。未触发50/58/59秒强制信号，未启动预测进程 |

**判断：本轮按首错停止要求完成，当前m60首次识别仍不能满足4秒门槛。**4.839965秒是失败错误响应完成时间，不是完整成功识别所需时间；未知完整成功耗时。前三批精简尚不足以让这次首次请求通过；不能将本次与此前4.174313秒直接计算加速/退化比例，既没有同源成功基线，也未做A/B或阶段拆解。未获得再次请求/缓存净收益、预测400ms、求界/热缓存、P95或完整P4通过证据。

执行后独立核对：先文档提交再静态准备、只发固定第1次、原来源/开关/预算/校准保持、一次收取/解析及原metrics一次快照、错误优先、余3次不发、只清本组进程、原观察finally完成后回收，均符合§0.7。当前仅将摘要同步四份原文档，未保存行情/完整响应/恢复文件，未新增仓库脚本、安装、部署或自动进入第四批。第四批仍须按原顺序细化并获准后推进；本轮不为解释失败而追加测量或临时修复。

### 0.8 首次60分钟完整耗时的一次诊断

依据专项§13及管理员“低成本测一个成功时大概多久”的指令。与§0.7的4秒失败分开登记，只执行一次首次识别，不继续该轮余3次、不推进第四批。正式4秒通过线保持；本节只允许下表所列一次性执行差异，§0.7的其他范围/读写/通信/清理/身份规则继续生效。

| 项目 | 固定实现及边界 |
|---|---|
| 入口与影响面 | 复用/private/tmp原一次性父/worker片段、原parse_args/group校验/isolated_app/_observe/metrics；不改仓库执行工具、API或业务文件。CodeGraph explore及源码核对load_entry→remaining→read_minutes→reader双源读取，时限向下传递，不存在需改另一套固定4秒读取器的前置 |
| 唯一业务请求 | parent仅signals一组，worker循环仅sequence=1；固定原m60普通latest识别路径及tsCode/freq/limit，无额外HTTP、预读、热请求、预测或重试。原合法mixed_single上下文/expected_requests=5保持，不送原整组validator |
| 临时服务端时限 | worker创建App前保存q.BUDGET，用dataclasses.replace(q.BUDGET, request_deadline_seconds=40.0)，with patch.object(q,'BUDGET',副本)包围原isolated_app完整生命周期；仅这一个字段变化，原对象及runtime/source/工具模块预算不改。所有remaining检查、reader Timer、原错误/取消仍执行；App/同步线程退出后才结束patch，随后确认q.BUDGET is 原对象 |
| HTTP及父监督 | AsyncClient分阶段timeout及asyncio总收取截止均45秒；4秒通过判断仅对本次诊断改为记录是否超标，不提前阻止成功结果。请求仍原生真实HTTP、0重试/无代理重定向、一次正文收取/解析；1MiB正文、4KiB输入/64KiB管道、50秒工作/58秒TERM/59秒KILL/60秒回收保持，不得无限等待 |
| 不变部分 | 新worker/空缓存、真实鉴权及只读Session、原prod SSE日历/正式Lake000001.SH m60必要字段/完整latest前缀、20000根/5000分区、64MiB/16条缓存、r4规则/Spec/编号/投影校验/计时起点均不变；不做源修订、DB/Lake写入或恢复文件 |
| 独立结果检查 | 父子均按单次上限核对；成功finished要求attempts=observedRequests=requestResults=1且原退出cleaned。HTTP200/READY、当前版本/period、前缀/窗口/来源及读取次数沿§0.7，唯HTTP不再按4秒阻断；结果同时输出withinOriginalBudget=(完整HTTP≤4秒)，超过4秒不能宣称正式验收通过 |
| 失败及覆盖 | 任意非时间错误/来源未就绪、40秒服务端到期、45秒客户端未完成或清理失败，停止并保留已知/未知；不自行重试、继续加时、改asOf或补热样本。未完成不能将超时时间当成功耗时。一次成功仅说明该次空产品缓存的完整HTTP；不代表OS/DB冷、P95/稳定耗时、热收益或预测400ms |

执行准备的静态核对：固定signals一组×sequence=1；仅q.BUDGET副本时限40秒，全部其他字段相同；客户端两处均45秒；所有成功计数父子由2改为1，无后续组；原取消/清理/还原及有界管道不变。只做语法/AST和差异静态核对，不加一次业务请求来“试入口”。正文、进度和观察只在内存/有界终端；结束后只回填原文档摘要。当前原§0.7失败证据保持，不能被本次诊断覆盖。

#### 0.8.1 单次诊断结果及独立核对（2026-11-02）

按§0.8先完成原方案/LLD补充及片段静态核对，再执行一次，无预热、预读或额外业务请求。只在临时worker中使用q.BUDGET的40秒副本，原runtime/Settings/Spec及全部其他字段不变；原代码的remaining和reader时限仍正常执行。一次性片段通过语法/AST检查：signals仅一组、sequence仅1、客户端两处均45秒、父子成功数量均1、patch包围原App完整生命周期并在结束后确认原对象还原；50/60秒监督、有界管道及原合同检查保持。

| 结果项 | 同次真实证据 |
|---|---|
| 唯一请求 | groupId=611d92e0d01442bf892b15786df9d9b1；requestId=611d92e0d01442bf892b15786df9d9b1:mixed_single:1:1:1；路径/参数仍原m60普通latest识别、000001.SH/freq=60/limit=500，尝试/服务端观察均1次 |
| 完整成功耗时 | HTTP200，dataStatus=READY；httpSeconds=7.03135637473315，自发出到93458字节完整正文收完，不含App启动/事后整理/清理；withinOriginalBudget=false，不能记正式4秒通过 |
| 识别版本 | algorithmVersion=xxm-direction-v0.4-r4，specHash=db435b39a3d198c126bfff567dfbe66faf74ff9299005578ec6b49bf065fd110，与当前MAIN_SPEC一致；indicatorVersion=1 |
| 完整计算前缀 | prefixRows=17312；source.startTime=2009-01-05T10:30:00+08:00；computedThrough=2026-10-30T15:00:00+08:00，不是只算500根 |
| 返回窗口 | responseRows=500；2026-04-27T10:30:00+08:00至2026-10-30T15:00:00+08:00 |
| 原始观察身份 | sourceInputId=bdd8ba9b3b8d2da8c7f947b0dfd986333f36930039bb9ee4a3126a0ac6499deb；publicDigest=5dd9a632da972d3c961a641a2dce2d9f14741ed1caeb39ce02b743379ff348dd；只记录本次，不据此宣称与上轮未知输入相同 |
| 请求/加载跨度 | 原请求startedMs=2455.232166685164、finishedMs=9482.483916915953，跨度约7.027252秒；load-1 startedMs=2928.683999925852、finishedMs=9438.632708974183、terminal=success，跨度约6.509949秒。均为相对本组起点的原观察，不与HTTP相加，也不把load当纯DuckDB或纯step时间 |
| 缓存/读源 | 新App开始为空，seriesCacheRead=miss/calls=1；signatureChecks=2、pairCalls=barsCalls=indicatorCalls=1，最终cacheBytes=17199474、cacheEntries=1。forecast cache为not_applicable；未发第二次来证明热收益，不保证OS/磁盘/DB缓存冷 |
| 退出 | cleanupStatus=cleaned、cleanupSeconds=0.10856754099950194，原预算对象还原；worker退出码0、已回收，管道3428字节，整组含启动/整理/清理10.256029749754816秒。没有触发强制信号、第二请求或预测 |

结论：本次空产品缓存首次完整识别约需7.03秒；4.84秒旧值是前一轮错误响应，不是成功完成时间。本次仅为单样本诊断；当前正式4秒线仍未通过，未证明稳定耗时、冷热净收益、预测400ms或完整P4。执行后独立核对临时时限唯一差异、原来源/范围/Spec、一次收取/一次metrics和原缓存/关联检查、原退出后还原、1次上限均符合§0.8；仓库业务/工具/测试/配置未改，未安装、写库/写湖、保存完整正文或自动推进第四批。结果只回填原文档。

### 0.9 第三轮优化读取轮：请求返回根数额外加1000（开发限定测试完成，后续复测见§0.10.9）

本节依据专项§14及管理员最新决定，文档补齐已提交944ab8088，管理员于2026-11-02授权后已按本节完成开发、限定测试和独立审计，逐项证据见§0.9.10。排在§0.7—8实际测试之后、第四批之前；仅上证r4分钟识别60/90/120及共用分钟预测，日线及普通图/指标/九转、独立研究/DG数据写入不改。已提交4debb8eb3，未真实复测、推进第四批或部署；本轮仅准备§0.10。§0.6保留第三批日历改动的历史记录；本轮分钟顺序及范围以本节为准，不再从数据最早年份构建进度。

#### 0.9.1 固定根数、配置登记和边界

设识别请求limit=N，`R=N+BUDGET.source_extra_rows`，新增单一内部固定字段`source_extra_rows: int=1000`。N继续原严格整数1—2000；默认N=原response_default_minute=500，故R=1500，最大R=3000。分钟预测不加HTTP参数，以原默认N=500调用相同加载链。数据实际少于R则按真实数量处理，不填值、不扩大窗口追满R；正常完整输入时读取和step根数都不得超过R。公开输出仍按原startDate/limit筛最后N根，额外部分只建立状态；不是无条件先丢掉1000根。N=500、实际仅400根且无startDate过滤时，应返回400根，不能返回空；实际1000根时返回最后500根。

| 配置/消费者 | 唯一值、来源和生效 | 约束/测试 |
|---|---|---|
| runtime.py:XxmRuntimeBudget.source_extra_rows | 代码中固定1000，沿原BUDGET实例和冻结dataclass；无env/Settings/DB/文件配置，无API或页面选项；新进程加载后生效 | query/source范围计划使用同一字段；测试不在其他生产文件另存1000。source_batch_rows仍1000的原批次/检查点含义，两者不能混用；不得改变MAIN_SPEC或FORECAST_SPEC来登记工程取数策略 |
| response_default_minute/max_response_rows | 现500/2000保持 | 识别显式N，预测默认N；R不能一律写死1500，也不复用另一个N的缓存 |

公开DTO/参数、r4核心、恢复校验、EMA公式/容差及所有正式预算不改。source.startTime及指纹必须记录实际选中窗口；source.initialHistoryIncomplete沿原True，不声称窗口之前历史已计算。事件/结构编号继续基于实际事实生成，不以窗口序号重编号。不能将旧全量进度/EMA状态偷渡进新空窗口以制造表面一致。

#### 0.9.2 开工依据、修改清单及消费者

CodeGraph codegraph_explore已核Reader的signature/pair及source→query→forecast影响面，补核API、load_entry显式调用、原观察包装、schema及普通分钟消费者。开工时read_minutes默认start=None，Reader按日期枚举至业务日，_load_series从空遍历全部raw，_response最后才裁limit，这是17312根计算/500根返回的原因；本轮已按下表改为显式有界窗口，实际结果见§0.9.10，不再保留该全量r4分钟调用。

| 原文件/入口 | 本轮修改 | 明确保留 |
|---|---|---|
| services/.../runtime.py | 新增上表固定字段 | 其余预算、Spec、无外部配置 |
| queries/.../source.py | 增加分钟范围计划；minute_request/read_minutes显式消费该计划，传首尾日期/时间及R | ENDPOINTS、SSE、20点上下文、原两源字段/对应、bar转换及连续性；read_daily/日线不改 |
| queries/.../query_service.py | build将limit/end_date交原load_entry；分钟load_entry/_load_series按新范围读取；缓存/flight纳入N及截止 | 单一原加载入口、原slots/截止/发布、完整状态/模型验证、窗口输出；日线原分支及key不变 |
| queries/.../forecast_query_service.py | 仅分钟调用load_entry时传默认500及asOf截止，沿同一窗口；迁显式早期asOf资格处理 | precheck/先近后远、recover_projection/容差、未来日历、400ms起点、求界/缓存/一次编码与退出 |
| foundation/.../major_index_mins_reader.py | 原完整读取方法增加可选time_window参数，传至_query_rows，限制已选日期内的首尾时间 | 公共分页请求/游标及默认无time_window的其他真实历史消费者；原pair/Timer/prepared/异常和必要目标检查，不新增第二套读取器 |
| 既有测试/工具消费者 | source显式参数、load_entry调用及替身同批迁移；原_observe的*a/**kw应可直接透传，新范围下继续实际计数 | 不改原工具samples/scenario/5请求计数、鉴权/隔离App、普通页面/API；不新建测量入口 |

source.minute_request/read_minutes仅有当前query和直接测试消费者，全部转成显式范围，不保留生产“没传范围就读全量”的后门。Foundation的通用time_window=None仍服务已存在的非本轮历史用途，并非保留另一套r4路径；r4分钟生产调用必须传窗口，测试要证明不会漏传。

#### 0.9.3 先确定有界端点，再选文件

在source.py定义内部`MinuteSourceWindow`，仅持`output_rows/read_rows/start_time/end_time/open_dates`，时间为上海带+08:00、可空首尾；无独立持久化/公共DTO。增加`normalize_minute_end(*, period, requested_end, context, now)`及`plan_minute_window(session, *, period, output_rows, requested_end, context, now, check)`：前者只用已有上下文和ENDPOINTS归一化请求截止，不发SQL；后者只接受该归一化结果datetime或None，在共享load内部查询一次范围日历并确定实际首尾。调用必须显式传`requested_end=归一化结果`，planner中的None仅表示无已完成上界，不能再次解释为latest。不新增另一套缓存或读取入口，固定流程如下：

1. N/R按§0.9.1，K=len(ENDPOINTS[freq])分别4/3/2。归一化前的requested_end仅来自已解析endDate或asOf。先用原`expected_through(period, (context.trade_date,), now, context.trade_date)`得到业务完成上界并解析为上海datetime；原None取该上界，原date取该日最后一个ENDPOINTS端点并与业务完成上界取小值，原datetime先转换为上海时间，再与业务完成上界取小值。实现必须先判datetime、再判date，避免datetime作为date的子类而丢失日内时间。返回统一的datetime或None，作为日历选择的截止和共享加载依据。业务完成上界为空时，latest/识别返回空计划；显式预测asOf按未完成请求400拒绝。**forecast须保留原始asOf，先拒绝早于1990、非法端点、晚于原业务完成上界的请求，不能用取小值把非法请求改成成功。**早期asOf由forecast build在load_entry前拒绝；未来/未完成datetime由load_entry取得原context后、加入共享load前拒绝，不为forecast另查一次context。识别endDate的未来日期仍沿原取小值语义，不新增400。
2. 合法识别endDate早于1990-01-01时，直接形成空计划：start_time/end_time=None、open_dates=()、read_rows仍为R；不查询该早期范围日历、不做签名或分钟读取，最终走原EMPTY包装。此处只复用现有1990资格边界区分业务支持起点，不增加识别参数下限，不查询全表最早日期。其余请求一次SSE有界日历查询：先在同一SQL的CTE中选归一化截止日以前最近`ceil(R/K)+1`个开市日期，再从其中最早日期至截止日返回trade_date/is_open，升序。CTE只投影日期、按exchange='SSE'/is_open=True/日期上界过滤并倒序LIMIT；外层仍只查SSE及该日期范围。无开市日时外层起点取截止日。1990及以后应覆盖的日历为空、截止日缺失或字段异常仍报原来源错误，不吞为EMPTY；有合法日历而无行情才是EMPTY。不另查1990至今、不逐日发SQL或再调用calendar_dates读同一区间。该SQL不包含MarketPageContextQuery的原SQL或预测未来日历。
3. 复用唯一ENDPOINTS按开市日生成至真实完成截止的端点，取最后R个，确定start_time/end_time。候选开市日多1天只用于当日完成根不足、R不整除K的边界，不能转成额外读源。无已完成端点则空窗口，不调用分钟Reader；合法不足R保留实际范围，不补造开市日或K线。日期/端点生成也使用同一check。
4. 由两端时间的date生成IndexMinuteReadRequest，字段选择仍bars四键+close、indicators四键+DIF/DEA/柱及原参数/版本必要检查；limit/max_rows显式R。两份signature和prepared清单仅覆盖两端日期之间的文件，两份签名前/成功后仍check一次；首份超时不得继续第二份。
5. 日期分区先过滤，只有范围内文件进入stat/链接检查、签名和DuckDB paths。现os.scandir可仍浏览频率根目录的目录名以筛日期，不能写成已完全不枚举旧目录名；不为此新增DG清单、Lake文件或第二轮检查。范围外旧文件内容和元数据不访问，不为确认根数先读一遍行情。

这是本轮必要的因果顺序变化：需要先知道最近多少个交易端点，才能给行情读取设置开始日期；不再先取全部raw后推日历起点。只缩日历的第三批代码/测试记录保留，但新生产分钟路径不再执行那一套旧顺序。日线仍按原§0.6日线分支，不使用本计划。

#### 0.9.4 Reader的单次双源范围读取

在read_complete_history_pair/read_complete_history/_read_complete_history增加内部可选`time_window: tuple[datetime,datetime]|None=None`；非None须成对、有序、无时区（正式Gold为上海本地datetime），日期落在request.start_date/end_date内。Biz只在传入Foundation前将已确认+08:00的边界去时区，不做UTC换算或日期截断。原其他调用默认None，公共IndexMinuteReadRequest/游标不增字段。

pair仍仅两流，原timeout_seconds由同一remaining传入，各自_Timer/连接finally关闭。_read_complete_history消费同次prepared一次，原_query_rows复用；给_query_rows增加同名内部参数，原公共分页路径不传，原SQL/limit+1/游标不变。本轮r4传max_rows=R；query_request.limit=R，多取1仅用于发现意外超量，若返回R+1则拒绝，不截掉多行冒充成功。

_query_rows继续先ts_code过滤，参数化路径列表仍仅所选日期文件。在target之后、原排序/LIMIT之前增加窗口条件，语义固定为：

```text
time_window为None：沿原条件，不添加新参数。
time_window非None：
  WHERE trade_time BETWEEN :start_time AND :end_time
     OR trade_time IS NULL
     OR CAST(trade_time AS DATE) <> _partition_date
```

坏时间NULL/日期错位不能被范围WHERE提前隐藏，仍交原_validate_target_rows拒绝；合法但正常范围外的首尾日行不消费、不追加全文件内容验收。time_window路径不允许decoded_cursor非None，避免与公共翻页边界混用。保持目标字段description、频率/日期/版本/数值和一次降序唯一检查，随后仍升序交给source。两流按完整四键逐根对应及assert_continuous负责实际覆盖首尾之间的缺口；不额外查询其他指数或先SQL聚合再重复Python去重。

数据少于R，沿原真实数量/初始历史不完整口径返回；两源不齐或实际首尾内缺根仍失败；末端落后则原DELAYED。不得为了凑够R跨过缺口向更早文件补量。所有raw/processed均限窗口内，前1000根也正常执行唯一核心，不能只算500根而忽略预备状态。

#### 0.9.5 load_entry、缓存、历史及发布

load_entry沿原方法增加内部关键词`window_rows: int|None=None, requested_end: date|datetime|None=None`；分钟None采用默认500，build传实际N，分钟forecast传500及解析后的asOf；日线保持原调用与全量分支，不借本轮迁移日线范围。原四元组(entry,context,open_dates,remaining)不变。显式直接调用/测试替身必须接受真实新增参数，原_observe使用*a/**kw透传，不将整个load_entry换成假结果来证明接入。

分钟先在共享load之前调用不访问来源的normalize_minute_end，再在共享load内部做一次范围计划，随后签名/复用或读取raw。基础key仍为原连接/来源/周期/MAIN_SPEC身份。flight_key固定为`(基础key各项, N, 归一化截止, context.trade_date, now.date(), 原业务完成上界)`；不加入原始requested_end的类型/文本、startDate、debug、HTTP入口或LATEST/REPLAY。这样真实页面的`endDate=context.trade_date, limit=500`与预测`asOf=None`会归为同一截止，重叠请求共用同一个loader及一次范围日历，顺序请求仍按原政策查签名。历史识别某开市日endDate与该日15:00的合法asOf也归为同一截止；同日较早asOf保持独立，不拿当天15:00结果冒充。20点前后仍遵守原业务日切换及完成上界，不能提前读到次日范围。

进入loader、计划完成后，`open_dates=plan.open_dates`，`completed=plan.end_time.isoformat()`（空计划为None），再构造实际源缓存key`(基础key各项, N, R, plan.start_time, plan.end_time)`，只调用cache.get一次。**分钟processed过滤及entry.validated_through必须使用这个completed，不能再只用business_date/整日日历重算为15:00，否则历史11:30请求会被错误标成尚未更新至15:00。**不再把原始请求类型、文本或归一化前的截止混入源缓存key。不同自然日的识别截止若因休市落在同一完成端点，可复用已发布的同窗口源entry；本轮不增加跨日期flight合并或第二层索引。500与2000、实际首尾不同的历史/最新窗口不能共用不相符entry；原始参数不同而实际窗口相同，不应人为拆分已发布源缓存。每次计划和调用者的日期资格检查均不可因命中缓存而跳过。

缓存及增量分支必须按以下顺序实现，不搜索上一个窗口的key：

| 本次情况 | 读取、计算及发布 |
|---|---|
| 实际计划首尾或N/R改变 | 新key，重新读取并从空计算本窗口最多R根；即使来源未满R、实际首根没变，也不跨key恢复旧进度 |
| 计划首尾、N/R相同，signature/raw/completed/open_dates也相同 | 沿原命中逻辑复用entry，不重新step |
| 同一计划窗口，来源晚到而追加了末尾，已缓存processed仍是新processed的完整前缀、实际首根及origin未变 | 原安全增量逻辑可恢复该key的旧进度，只step追加部分；这是同一计划内补到行情，不是完成端点推进 |
| 同一计划窗口，但已有行情修订、前缀变化、实际首根或origin改变 | 沿原revised判断，从空重建本窗口；不能追加到旧状态 |

例如同日文件签名未变，完成端点11:30推进到14:00时，plan.end_time改变，必须重新读取并有限重建，不能复用11:30的raw。origin仍按实际首根/周期/原指标版本生成，指纹仍按实际输入计算；不能把旧窗口的wave/history/active_structure/followed_structures强行接上新首根，也不能一边沿用旧17年entry一边声称只处理1500。

_validate_entry、完整内部_response、cache.put/_deep_size和请求窗口_response均保留，但处理的entry仅本窗口；完整包装是否另做2B迁移仍留后续测量，不借缩范围删检查。失败不得发布新候选或覆盖合法旧entry；窗口不同使用不同key时错误结果不得占用缓存，原64MiB/16条淘汰不变。事件和引用由原核心产生，响应仍保存当前窗口内需要的关联结构，不能先删1000根预备事实再构造关联模型。

分钟asOf早于1990-01-01须在forecast build进入load_entry之前按原400拒绝；取得原业务上界后、加入共享load前拒绝未来/未完成asOf，非法格式/非端点继续由原解析拒绝。其余开市资格由forecast取回同批open_dates后独立验证原asOf，不能另发单日重复查询，也不能因为另一个识别调用共享了来源就免检。共享loader不根据某个调用者是否REPLAY返回400，避免休市asOf与合法识别endDate重叠时互相改变返回状态。合法历史请求围绕其截止加载；asOf合法但早于可用行情为EMPTY，休市为400，应覆盖的日历缺失或来源异常仍原错误。识别端点前的合法早期endDate按§0.9.3的空计划返回EMPTY，不套用预测的1990参数拒绝。startDate只筛响应，不改读取起点或R；不足N按实际结果返回。

#### 0.9.6 预测、身份及阶段衔接

分钟forecast从该同一1500根entry恢复原calculator，沿原precheck→必要时recover_projection→未来日历/结果缓存→求界/模型/编码/发布。recover_projection当前从传入首根初始化并推进全部bars，仅末250根做容差校验，本轮不改其实现或容差；它现在接收最多1500根。不能把“校验250根”当成只读250，也不从旧全历史缓存保留EMA来绕新输入。返回状态的先后顺序必须保持：

1. EMPTY/DELAYED先沿原来源状态返回，不进入READY计算段。
2. READY时先恢复calculator并precheck；`prepared.stop_reason`存在且没有`following_structures`，返回NO_CANDIDATE，不调用recover_projection，即使来源少于250根也不能改报精度失败。
3. 仅普通候选或仍需计算的旧结构跟踪存在时才调用recover_projection；该路径少于250根或实际校准不通过，沿原CALIBRATION_FAILED/PRECISION_PENDING。普通候选没有可能但仍有following_structures时，不能用第2步提前退出而漏掉跟踪。
4. 校准成功后才查未来日历、查询预测结果缓存、求界并包装。所有分支仍按原400ms起点及最终退出检查，不为提高性能改成READY、改容差或跳过校准。

共用的是来源entry，不是预测公开响应。forecast保留原始requestedAsOf、LATEST/REPLAY、forecastId以及结果缓存key中的as_of；显式asOf与无asOf即使源窗口相同，也按各自模式构造和校验响应，不能串用整份预测结果。

固定窗口起点改变时sourceInputId及forecastId可能依法改变；这与修改事件编号算法不同。核验应分开：实际窗口/指纹忠实于新输入，普通/debug同输入业务事实一致；展示500根内标签、参照事实/日期、结构/事件关系及下一根条件用独立预期或有效旧证据比较。不能要求新source.startTime仍为2009，也不能以“只是ID变化”掩盖实际漏标签/漏结构。出现业务差异停下报告，不临时扩大1000、用全量补算或改r4规则。

本轮完工及独立审计后先交管理员review，不自动开始第四批/真实复测。原第四/第五批的A/B均以本轮之后相同N/截止/范围为共同基线，不能把“缩范围”混入某一个缓存变体；同源比较分别记录计算窗口和返回窗口。§0.7—8的17312根/失败/7.03秒继续是当时真实记录，不当成新范围的当前性能；§0.8临时40/45秒诊断授权已经结束，本轮正式仍4秒/400ms/5秒。

#### 0.9.7 对应测试设计（限定实现及成绩见§0.9.10）

新增用例只放现有相关测试文件，输入/预期由固定口径、独立字面样本或独立数学依据给定，不用待测范围helper生成expected。临时SQLite表/Gold schema沿当前真实生产者和第二批已核字段；所有业务函数/读取器尽量使用真实实现，计数包装必须调用原函数。范围外坏文件用于证明不访问，不能先替换Reader绕过范围选择。

| 编号 | 人工场景与独立预期 | 代码/测试落点 |
|---|---|---|
| 1 | N=1/500/2000，R严格1001/1500/3000；非法N沿原拒绝；runtime唯一1000与source_batch_rows含义独立 | runtime/source；现xxm API测试 |
| 2 | 三周期用手写交易日/末端点，分别检K=4/3/2、R不整除K、首尾处于日内、上午/午间/闭市/周末。历史m60的asOf=11:30必须仍为11:30，不能因datetime先当date处理而变15:00；无业务完成上界的None空计划不能被planner重置为latest。预期端点字面列出 | source范围计划；xxm API测试 |
| 3 | 正常计划范围日历仅1条SQL，CTE LIMIT=ceil(R/K)+1，日期不回1990；例如默认m60为376、m90为501、m120为751。应覆盖的日历为空、截止日缺失/字段异常拒绝，不吞成EMPTY；真实少量来源不为不足R误拦。无业务完成端点时空计划，不读行情 | SQLite真实SQL绑定；xxm API测试 |
| 4 | 旧请求早于latest1500首根，仍围绕其合法截止取R根；历史11:30的源plan.end_time、processed末端、validated_through及forecast expected均为11:30，完整来源不能因当前已过15:00而误报DELAYED。识别endDate=1989-12-29返回200/EMPTY，范围日历/签名/pair均0次；预测asOf=1989-12-29T15:00:00+08:00在load_entry前400；1990以后应有日历却缺失仍原来源错误；有合法开市日历而无行情为EMPTY。识别休市endDate取此前完成端点、未来endDate沿原取小值；预测休市/未来/未完成/非法端点400，不能混为同一拒绝规则 | query/forecast实际HTTP；三类早期边界及原资格反例 |
| 5 | 多于1500根临时Gold，默认返回500、raw/processed/step=1500；N=2000时3000。旧日期目录里放不可读/坏文件，断言其未stat/打开/进入SQL paths；不是先全量读再裁 | reader/source/query；reader及xxm API测试 |
| 6 | 刚好R、少于R、空、只有未完成根、末端滞后；按实际数量/EMPTY/DELAYED。N=500且无startDate过滤，实际400根返回400，实际1000根返回最后500；不是先扣掉1000再输出。不补值、不扩文件重试 | source/query实际链 |
| 7 | selected日期内time_window之外的正常首尾行不进入；范围内NULL/错日期/非有限/错误参数版本仍拒绝；R+1意外行及重复时间失败，不截断掩盖 | Reader小字面Gold，原_query_rows |
| 8 | bars/indicators四键不同、缺交易日/端点/重复/源序错；两源各一次SQL，原不同职责检查保持，不查询其他指数 | reader/source实际链 |
| 9 | 最后500根第一根所需参照、正在钝化/结构及跨窗旧结构形成点均在前1000根；零柱、当根切远、单根同色段后继续跟踪等按已确认字面结果 | 原核心不改；xxm API/内部结果样本 |
| 10 | 固定context.trade_date=2026-10-30且当日15:00已完成：识别显式endDate=2026-10-30/limit=500（含真实页面的startDate）与预测asOf=None及显式asOf=2026-10-30T15:00:00+08:00，归一化截止字面等于该15:00。相同normal/debug源key一致：顺序请求pair总1次，重叠请求只1个loader/1条范围日历/1次pair；顺序请求的签名/日历仍按原政策执行。预测结果分别保留LATEST/REPLAY、requestedAsOf及各自forecastId/结果缓存key，不复用另一模式的公开响应 | 真实临时Gold/SQLite，原load/cache/HTTP及观察；不能只测识别不传endDate的假页面路径 |
| 11 | N从500到2000再500、latest/历史及同flight请求真正重叠；key隔离，不因先请求小N污染大N。休市endDate识别与该日15:00预测可共享通用来源，但前者按原返回、后者独立400，互不污染；非法预测不能把合法识别的共享loader置为400。不同自然日只复用已发布同窗口entry，不新增跨日期flight合并 | query/SharedLoads实际调用 |
| 12 | 计划末端从11:30推进14:00，或N/计划起点改变：新key、重新读取并从空重建，即使来源未满R且实际首根相同也不restore旧key。同一计划首尾不变，迟到行情补齐末尾且旧processed仍为完整前缀：只step追加部分；同计划已有值修订或首根改变：从空重建。同日文件签名不变但完成端点推进不能假命中；范围外旧文件变化不触发本窗口签名修订 | cache/snapshot消费者原测试；断言具体key、pair/step/restore次数 |
| 13 | 窗口内坏缓存/坏关联，即使位于预备1000而不在输出500也拒绝；旧窗口被保留时不能混入新窗口；失败保留旧结果且不发布半份 | query完整验证及缓存故障样本 |
| 14 | 分钟projection以1500根独立EMA样本恢复，末250字面/独立高精度预期匹配；直接调用projection少于250根及实际误差超原1e-8，均原CALIBRATION_FAILED。该函数级结果不能推导为所有短来源HTTP必报PRECISION_PENDING；不改容差 | projection原数学测试，独立生成依据须先审计 |
| 15 | 两份READY来源均少于250根：无普通候选且无跟踪时NO_CANDIDATE、projection调用0次；有普通候选或只有有效旧结构跟踪时才调用projection并返回PRECISION_PENDING。EMPTY/DELAYED均不进入校准。真正READY/求界/缓存冷热沿原非零M1临时分钟样本；校准隔离与真实EMA测试分开登记，不能用mock宣称校准接入通过 | 现forecast API测试；独立手写状态分别覆盖无候选、有候选、仅跟踪及两类来源非READY |
| 16 | load_entry新增参数所有直接调用/替身/原_observe透传；窗口字段/真实prefixRows/首末正确，原工具合法1/20及完整5请求计数不变 | 原web/研究消费者及P4工具测试 |
| 17 | Reader的非窗口完整读取、普通分钟主图/完整指标分页/limit+1/游标不变；日线分支、真实现行字段合同及既有20点切换不变 | 原Reader/分钟API/日线消费者必要节点 |
| 18 | 日历、逐份签名、两源读取、step/模型/计内存/发布前超时或取消，原错误优先、不再领取后续步骤；Timer/连接/锁/slots/flight清理、旧entry不被污染 | 分层故障注入，原退出/资源测试 |

同一行情下的历史长序列/短窗口对照仅限独立人工序列及既有有效报告，比较最后N根业务事实，不要求窗口metadata相同。不新增真实17年回放作预期；尚无真实逐根证据的部分明确未验证。1000为固定实施决定，不用复杂动态追溯替代。若人工极端用例暴露超过1000才成立的旧依赖，应报告具体差异并停下讨论，不偷偷增加读取量。

#### 0.9.8 开发顺序、预算和停止条件

1. 先实现runtime固定字段与source范围计划及字面用例，随后原Reader时间边界和单次双源读取；不要先删原全量加载而留下不能读的中间交付。
2. 同批迁query的N/截止/缓存/flight/起点滑动和source明确窗口，再迁分钟forecast/历史资格及全部调用/观察消费者；不交付识别已缩范围、预测仍读17年的半套结果。
3. 按上表分组运行必要本地回归，每组超过60秒停止查因；随后根架构三项、研究依赖及文档检查。无正式源、安装、配置或真实测量副作用。独立审计逐条对照本节/专项§14，并与前三批文件/检查/日历及原P3规则联合核验。
4. 交管理员review并停止；本轮开发授权不包含真实复测。后续最小m60真实复测沿原工具/只读来源/4秒首错停止，必须在执行前明确请求安排，不自行复用§0.8的放宽时限或再拉旧17年基线。

正式4秒包含范围日历、文件选择/签名、SQL/转换、最多R根step及检查/编码/发布和最后退出检查；预测同一400ms及客户端5秒保持。原源20000根/5000分区是外层保护，不是本轮可读满的目标；本轮实际R≤3000，response/缓存/双源内存、并发及原组50/60秒退出保持。错误不重试、不扩大1000、不保存恢复文件；进程退出只丢该内存，下次按同一有界入口重新算。性能改善只在实测后登记，不从91.34%根数下降推断毫秒成绩。

#### 0.9.9 开发前文档审计记录（2026-11-02，仅静态；开发结果见§0.9.10）

首次文档提交3e97077a6之后的独立审计发现缓存归一化、跨窗口增量、短来源预测状态、早期EMPTY四处缺失及产品旧口径。本次按批准建议补齐，并重新对照原方案§14、产品说明、技术方案§20及当前source/query/forecast/Reader/runtime、SharedLoads、context和前端实际调用者。以下是补齐后的静态结论，不把尚未开发的目标当作代码已具备的能力。

| 审计项 | 本轮核对结论 |
|---|---|
| 用户根数与范围 | 唯一口径N+1000，默认1500、最大3000；不是总计1000，也不是再动态增加前置历史。仅r4分钟及共用预测，日线/图/九转不扩改 |
| 读取前限定 | 先有限日历/完成端点，后分区签名和带时间边界的SQL；原R+1只作失败检测，不先取17年再裁。允许浏览目录名与只对范围内文件stat/打开已明确区分 |
| 先后和共享 | 不发SQL的截止归一化先于flight，范围日历留在loader内；真实页面显式endDate与预测None可共享。源key只含实际范围及N/R，预测响应仍区分原始asOf/模式。不同自然日不新增跨日期flight合并 |
| 缓存重建和增量 | 任何计划首尾变化均新key并重建有限范围，未满R也不例外；只有同一计划中迟到行情追加且原前缀不变时走既有增量，不引入上一key搜索 |
| 历史和失败顺序 | 识别早于1990返回EMPTY且不查该范围日历；预测早于1990在load_entry前400。支持日期内缺日历仍来源错误；合法日历无行情才EMPTY；休市识别与预测各守原语义，共享loader不混入单个调用者资格 |
| 识别/预测完整性 | 核心/Spec不动，额外部分保留关联，实际不足1000也不先丢弃。预测先precheck，只有需要时才校准；NO_CANDIDATE、PRECISION_PENDING、EMPTY/DELAYED逐层区分，旧结构跟踪不会因普通无候选而漏算 |
| 前三批/第四批 | 第三批全raw后日历仅作交付记录，当前工程范围要求已改；第一、二批去重/目标字段/升序与prepared仍保持。第四批A/B共同基线包含新轮，不恢复旧全量或原多余检查 |
| 当时测试/开工界限 | 开发前18组设计已补实际页面参数、三类早期边界、跨/同计划增量对照、短来源分支及实际不足1000的输出，当时尚未执行。之后的实际测试见§0.9.10，仍不宣称1500根性能/真实逐根一致 |

本轮还核对并补清容易漏掉的交接：归一化不另查context/日历；datetime先于date判断，planner的None不重新解释为latest；源completed/validated_through跟随实际计划末端，不能把历史11:30扩成15:00；共享源entry不合并LATEST/REPLAY响应；无业务完成端点返回空计划；未来识别endDate与未来预测asOf不混用拒绝规则；实际不足R不先删1000；time_window不进入公共分页游标。专项缓存测量的追加/重建分组及阶段表也已同步到新窗口，未遗留“完成端点变了仍跨key增量”的要求。未发现尚需管理员拍板的规则或未处理的本轮文档阻塞。后续只能在取得开发授权后按§0.9.8开工；1000是否覆盖真实案例仍须限定验收，差异按本节停下报告。文档检查仅证明完整性与静态对账，不代表代码、性能或来源验收通过。

#### 0.9.10 实施对账、限定测试与开发后独立审计（2026-11-02）

依据944ab8088及管理员明确开发授权，实际仅修改5个生产文件：`runtime.py`、`source.py`、`query_service.py`、`forecast_query_service.py`、`major_index_mins_reader.py`；测试落在既有Reader、识别API、预测API、snapshot_consumers和p3_forecast_math五份文件。既有第三批及其他工作区改动保留，不恢复旧实现、不新增测量入口，不提交或部署。

下表的序号对应§0.9.7。`API测试`为`tests/web/test_wealth_index_detail_xxm_api.py`，`预测测试`为同目录`test_wealth_index_detail_xxm_forecast_api.py`；`Reader测试`为`tests/test_major_index_mins_reader.py`，研究测试均在既有主题目录。函数名列出可直接定位的节点，不把手写输入当真实行情。

| 序号 | 实际编码与测试证据 |
|---|---|
| 1 | runtime唯一`source_extra_rows=1000`；query严格N/source计划R。API的`bounded_plan_uses_one_limited_sql_and_fixed_extra`和`bounded_plan_rejects_bad_count_without_query`验证N=1/500/2000、1001/1500/3000及0/负数/布尔/小数/超限拒绝 |
| 2 | source的normalize先判datetime；旧三周期完成、20点切换/周末节点保留，`bounded_normalization_keeps_intraday_cutoff_without_sql`、`bounded_history_intraday_and_early_empty`验证11:30不变成15:00及None空上界；大范围N=1用例验证首日只选中15:00这一根 |
| 3 | plan在shared loader内执行1条带最近开市日LIMIT的CTE；API计划测试明确376/501/751/252及日期绑定；`bounded_calendar_errors_are_not_empty`拒绝缺日、NULL、重复和缺截止。未恢复1990至今查询 |
| 4 | build/load传原截止；分钟completed/validated_through采用计划末端。API历史/早期EMPTY测试、预测`bounded_early_and_future_forecast_refused_before_source`及原qualification/early_asof测试验证历史、1990、休市/未来、合法空源和来源错误分别处理 |
| 5 | Reader枚举先按日期筛，SQL用time_window再LIMIT；API的`bounded_real_gold_limits_files_sql_steps_and_output`用5组实际临时Gold核N=1/500/2000和三周期，断言1001/1500/3000根raw/processed/step、2次双源SQL、paths/参数首尾及返回1/500/2000。1999范围外坏文件不得stat/进入SQL |
| 6 | `bounded_raw_bounds_and_original_completion`覆盖空/首日不齐/滞后/未完成；`bounded_short_real_source_returns_last_n_without_dropping_extra`实际400根返回400、1000根返回500，不先扣1000、不重试补量 |
| 7 | Reader的`bounded_history_filters_time_before_limit_without_changing_paging`与`bounded_history_does_not_hide_target_errors`验证首尾时间、正常外部行不消费、NULL/错日期不被WHERE隐藏、重复/坏close、R+1拒绝；无文件时非法时间范围也拒绝 |
| 8 | 原`two_streams_match_in_one_pass`、必需值和真实Gold双源HTTP反例已迁新参数，完整四键/缺根/坏版本/非有限值/目标过滤仍验；原第二批Reader反例继续通过，不验其他指数 |
| 9 | API的`bounded_visible_event_keeps_structure_from_extra_prefix`以RC47/52七根字面数据验证输出一根时仍保留前置形成的结构及回转关联；原r4_rules/following/following_query/internal_results共1007例验证零柱、当根换远和单根段等规则不变 |
| 10 | 预测测试的`bounded_real_page_enddate_and_forecasts_share_source_keep_modes`经真实临时HTTP/SQLite/Gold验证页面显式start/end、normal/debug、无asOf及显式asOf四请求仅1次pair，4次正常范围计划；LATEST/REPLAY、requestedAsOf和forecastId分别保留 |
| 11 | `bounded_counts_and_historical_endpoints_have_separate_entries`验证500→2000→500及历史key；预测`bounded_overlapping_signal_forecast_use_same_flight`验证重叠识别/预测只有1次pair，休市预测400不污染合法识别，共享pending最终清空 |
| 12 | 实际源key含N/R/首尾；`bounded_changed_plan_rebuilds_even_with_same_actual_first`验证未满R但截止变化时重读并完整重建12根，不restore旧窗口至新主计算器；原append_revision测试验证同计划迟到追加才增量、来源修订重建、旧对象不变。范围外文件变化不在新签名paths内 |
| 13 | 原完整_validate_entry/_response/cache.put保留，只处理本窗口；API的`bounded_window_does_not_hide_corrupt_cached_old_structure`实际验证公开窗口不含旧结构时，旧缓存记录的NaN仍被拒绝，未被过滤隐藏且原合法对象不变；r4内部结果/RC93及snapshot进一步验证关联和恢复隔离，计划/来源失败不发布半份 |
| 14 | `test_xxm_p3_forecast_math.py`新增`bounded_projection_recovers_1500_from_independent_decimal_history`：独立70位Decimal EMA先生成1524根，再取1500根交原recover_projection；末端状态按独立预期吻合。249根及末DIF增加2e-8均原CALIBRATION_FAILED；未调用被测advance生成expected，不改1e-8 |
| 15 | 预测`bounded_short_source_precheck_precedes_real_calibration`以真实短Gold分别验证NO_CANDIDATE/0次校准、有候选/1次校准、仅旧结构跟踪/1次校准；后两者原PRECISION_PENDING。`bounded_nonready_source_does_not_calibrate`确认EMPTY/DELAYED不校准；原非零M1 READY/缓存测试仍通过，M1替代校准与Decimal实际恢复分开登记 |
| 16 | 新load/source参数直接消费者与替身已迁移；原_observe的*a/**kw无需改实现，flight基础项仍保留period在原位置。P4工具110例通过，1/20、完整请求计数、真实包装一次、取消/回收及有界通信规则未改 |
| 17 | Reader的None路径、公共分页/游标和普通分钟/九转原行为通过；日线分支/key原样，原day/qualification/快照和API回归通过。无前端、产品API参数、日线来源或DG配置改动 |
| 18 | 识别`bounded_deadline_stops_at_each_stage`及signature_error验证计划/签名前后/读取超时即停止；预测`bounded_plan_failure_keeps_published_source_and_priority`覆盖timeout/source/query/两类取消，验证原错误优先和旧结果不变；原Reader pair Timer/连接、SharedLoads及P4工具退出测试继续通过 |

旧测试迁移依据：第三批原先要求“raw→日历”、首日由raw决定，及早期asOf另查一次单日日历；本轮明确改成“范围日历→文件→双源”，所以原调用次序、范围参数和单日查询计数按新规则更新。窗口变更不再跨key增量；同计划补到行情仍验证增量。没有删除缺行情、坏值、来源错误、取消、旧缓存保护或非零求界覆盖，没有skip或放宽预算。snapshot的隔离替身同步提供显式计划/范围内bars，仅用于恢复验证，不冒充SQL接入。

限定测试分组（每组均少于60秒，未运行真实复测）：

| 测试组 | 实际结果 |
|---|---|
| Reader、预测API、snapshot_consumers、p3_forecast_math | 393例通过（195+117+81）；后续snapshot/math再核81例通过 |
| 完整识别API文件，含5组1001/1500/3000根真实临时Gold范围验证 | 187例通过，最后一组执行23.10秒；是自动测试整组耗时，不是正式请求性能成绩 |
| 普通分钟主图/指标、分钟九转、SharedLoads | 61例通过 |
| 原P4观察/通信/退出工具 | 110例通过 |
| 原r4_rules、following、following_query、internal_results | 1007例通过 |
| 根三份架构护栏 | 16例通过 |
| 研究组织/入口检查 | 14例通过；另对Biz/Foundation当前源码AST核查，无scripts.research导入 |

上述不重复计数共1788例。使用现有SQLAlchemy 2.0.50/DuckDB 1.5.5；Context7已核[SQLAlchemy CTE/标量子查询](https://docs.sqlalchemy.org/en/20/core/selectable.html)及[DuckDB参数绑定](https://duckdb.org/docs/current/guides/python/execute_sql.html)，未安装依赖。临时Gold使用现合同及既有生产者夹具，SQLite代替prod日历；没有访问prod、正式Lake、DG或真实行情，没有重放旧17年基线，不能据此声称真实逐根结论或4秒/400ms性能已验收。

开发后独立审计再次按§0.9.1—8、专项§14及前三批检查：N/R贯穿日历、文件、SQL、计算和缓存；真实页面参数归一化与历史日内截止一致；数据不足不先删1000；仅同计划增量，原始asOf资格与共享源分开；预测保留precheck/校准/跟踪/退出的原先后顺序；公开字段/预算/Spec及业务核心不改。CodeGraph explore/impact核调用方，修改后sync/status确认索引最新；正式Reader源码及消费者单独核实，不依赖同名研究函数的误匹配。逐文件与开工时文本对照确认calculator、Spec、恢复校验、projection等核心未变；无运行时源码SHA保护。

当前未发现本轮LLD偏离、与前三批冲突或尚待处理的落地问题。**本节开发及限定测试已完成；后续限定m60真实来源/耗时复测见§0.10.9，完整P4和真实500根业务事实一致性仍未验收。后续优化按§0.11暂缓为TODO，不进入第四批或部署。**1000根依赖是否覆盖实际案例仍按§0.9.6的后续限定验收处理，不临时扩量或改规则。

### 0.10 第三轮优化读取后的复测（准备及实际执行完成）

#### 0.10.1 准备阶段条件与范围（实际执行另见§0.10.9）

依据专项§15、§0.9及管理员本轮指令，仅补复测安排并准备一次性调用。读取优化已提交4debb8eb3；提交后独立审计及580例相关回归通过，真实耗时和真实500根业务一致性尚未验收。旧§0.7首错和§0.8单次诊断为历史；不得补发旧轮或继承40/45秒放宽。本轮不启动App/子进程/真实请求，不读取数据库或行情，不改仓库业务/工具/测试、配置、Spec或预算，不提交或部署。

§0.7的隔离App、只读来源、HTTP单次收取、原观察、通信/退出能力继续使用；本次运行身份、1500根和正式预算以本节为准。先完成本文/专项设计，再写临时片段，再独立静态审核；准备完成只交管理员review，后续获得真实执行授权后才允许调用。不是第四批测量，不以详细阶段观察/A/B开发为前置。

#### 0.10.2 请求、范围及来源的固定值

| 顺序 | 进程与固定请求 | 条件 |
|---|---|---|
| 1 | 识别组新进程/isolated_app/空XxmCache；GET /api/v1/wealth/market/index-detail/minute-xxm-signals；tsCode=000001.SH、freq=60、limit=500 | 无预热/其他HTTP |
| 2 | 识别组同App/客户端/缓存，同第1次参数 | 第1次全部合格且collector已无活动/线程/关联，才继续 |
| 3 | 识别组finished/成功退出且回收后，预测组另起新进程/App/空源与预测缓存；GET /api/v1/wealth/market/index-detail/xxm-key-point-forecast；tsCode=000001.SH、period=m60 | 不继承识别缓存 |
| 4 | 预测组同App/客户端/缓存，同第3次参数 | 第3次全部合格、活动清空才继续 |

两路径均normal/latest，不传debug/startDate/endDate/asOf，不发图/指标/九转/daily-waves/私有HTTP；不扩周期或次数。每组最多2次，整轮最多4次，顺序串行；错误即停整轮，不预热/重试/选日期/冻结业务时钟。原group仅观察上下文：tool=page、scenario=mixed_single、period=m60、mode=normal、samples=1、requestedAsOf=None；requestKind另限signals/forecast，sequence只1/2，round/tab均1。原samples=2仍非法、完整组expected_requests仍5，不使用其validate_summary验收本轮2条记录。

实际源范围两接口均N=500、R=1500。正常结果prefixRows为严格正整数且≤1500，识别responseRows为正整数且≤500。额外1000不是输出前先删除；实际不足按真实值，不补量/不回退全量。首末与sourceInputId取同一次投影观察；prefixRows是原collector对实际processed前缀的计数，本轮不另包raw/step或新增读取。源码和隔离用例已证明SQL/文件/step范围，真实运行只核同次已有证据，不冒充重新验证全部SQL细节。

继续GOLDENSHARE_ENV_FILE=.env.web.local及其原prod只读SSE日历、本机/Volumes/datasource/data_lake的m60 bars（gold/quote/major_index_mins/freq=60）和indicators（gold/indicator/major_index_mins_technical/freq=60），由当前source.plan_minute_window选实际截止和范围。准备只核配置/依赖/目录；不打印连接凭据、先查行情/日历或手工凑齐。首请求原来源校验负责连通及完整性；非READY保留证据、整轮停止。20点业务日切换仍由原代码决定。

#### 0.10.3 临时片段的实现与旧诊断隔离

新文件固定/private/tmp/xxm_bounded_read_retest_20261102.py，父/worker同一文件，从仓库根用现.venv/bin/python -B；不是维护入口，不新增仓库脚本或开关。不覆盖/导入/执行旧/private/tmp/xxm_batch3_test_round_20261102.py：它后来用于§0.8，现有40/45秒、单组单次、1条load/5帧等限制不适用本轮。

沿原已核片段的HTTP/管道监督写法迁移，不另写来源/计算器或改原audit模块。具体函数要求：

1. parent只加载原settings、构造原合法group，按signals再forecast调用supervise；前组success且cleaned/reaped/退出码0才建下一group。两组全成功且attempts=4才报限定轮完成，否则列明尝试/已收/未执行。没有自动重发或从中断续跑。
2. worker只接受requestKind/group/settingsIdentity三字段≤4KiB，原_group_from_json和_settings_identity核对；不接收凭据/任意URL/外部pid。进入App前核原query BUDGET的4秒/默认500/额外1000及FORECAST_SPEC的400ms，**只读断言，禁止replace、patch或赋值改预算**。调用原isolated_app；每组新cache，原观察包装负责恢复和清理。退出后还须确认q._CACHE恢复进入App前的原对象；不能只因活动计数归零就把观察恢复失败写成cleaned。
3. requests只建一个原生AsyncHTTPTransport(retries=0)/AsyncClient，trust_env=False、follow_redirects=False、timeout=5；固定循环(1,2)，每次成功和idle之后才下一次，任何异常设置stop并退出。本轮唯一请求路径来自§0.10.2常量表，不允许参数扩展。
4. basic_check检查HTTP200、原当前Spec身份、000001.SH/m60、dataStatus=READY及完整HTTP≤4；complete_check再核原观察、1500根、字节、缓存/两源次数、预测compute≤0.4及再次同源/同结果。失败不进入下一次。parent对收到的成功row再次执行同一核对，不能只凭子退出0报成功。
5. observed_fields从每次唯一collector.metrics快照取本次request/load记录；累计请求数应等于当前sequence，累计loads≤sequence（第2次正常命中仍可能产生第2条load记录，不能照搬旧诊断≤1），每次本身关联恰一条原load。每load的seriesCacheReadCalls=1，pair/bars/indicators各≤1，signatureChecks=2；预测cache get/put各≤1。命中与否按原记录，不强行要求第二次hit。完整字段白名单沿原_REQUEST_FIELDS/_LOAD_FIELDS；响应只解析一次，不重建整份DTO。
6. supervise沿原父子管道，单组最多7帧（started、两次各request_started/finished、cleanup_started、finished），request顺序≤2。finished成功必须attempts=requestResults=observedRequests=2、两row无failure、cleaned且退出0；部分失败时保留已有证据，不将未收到当0。父最后只输出白名单摘要，不输出正文、凭据或原stderr。

#### 0.10.4 计时、正式预算与覆盖边界

完整HTTP≤4秒；预测computeSeconds≤0.4秒，来自原_observe开始READY计算至原build退出，保持校准/未来日历/模型/编码/发布和最后检查。两值分列，不相加、不从HTTP减去读源反推。产品内4秒及400ms仍真实生效，不patch源/预测/校准或增加分阶段计时。

每次asyncio.timeout(5)覆盖client.stream、aiter_raw及response关闭；HTTPX timeout=5仍是分阶段超时，不能代替总截止。t0在stream调用前，t1最后正文段读完后；未收完httpSeconds=null、只记elapsed，收完但退出/关闭失败仍是失败。Accept-Encoding=identity、响应requestId一致、无重定向；识别1MiB/预测32KiB逐段先验，JSON只解析一次。客户端及App关闭、摘要验证均计入每组50/60秒，不算到成功HTTP成绩里，也不能漏计总退出。

源外层20000根/5000分区保护、缓存64MiB/16条、原Reader双流并发与内存保持；本轮实际前缀≤1500。原HTTPX 0.28.1的stream/自动关闭、transport显式重试和分阶段超时已由Context7核对：[异步流](https://github.com/encode/httpx/blob/0.28.1/docs/async.md)、[超时](https://github.com/encode/httpx/blob/0.28.1/docs/advanced/timeouts.md)。本轮不安装依赖、不验证TS客户端/浏览器5秒，不做P95或详细阶段A/B。

#### 0.10.5 摘要、同源判断与状态顺序

复用§0.7.5的白名单、识别dataStatus.status/预测dataStatus及status/reasonCode的区别；固定增加实际前缀≤1500检查，不把普通响应补成debug。每次同一结果记录：固定请求/序号、HTTP状态/错误、实际字节、完整HTTP/失败elapsed、computedThrough、prefixStart/prefixRows、识别输出首末/数量、原Spec、sourceInputId及publicDigest；预测另记forecastId/calendarInputId/targetEndpoint/barsAhead/computeSeconds。原load/cache次数和内存、清理/回收、剩余未执行项均分列。

每组第二次对照第一次的来源身份、实际首末/根数、完成根、结果digest/版本，预测再比预测/日历/目标身份。任一变化停止，不重跑或挑慢样本；跨两个新App仅如实记录来源，不强求不同接口digest相等。合法NO_CANDIDATE/PRECISION_PENDING允许原calendar/target等null，记清未走到的校准/求界/预测结果缓存，不按null误拦，也不据此说完整求界/热缓存通过。源EMPTY/DELAYED或缺必要观察则停止。

#### 0.10.6 失败、通信、取消与退出

通信沿§0.7.6：输入≤4KiB、stdout/stderr累计≤64KiB、最多7帧；父核group/kind、启动pid/进程组等于自己Popen.pid、白名单、序号和前后顺序，拒未知/多发/cleanup后请求。不使用无界capture，不打印stderr或行情。超限/格式错立即停止并回收自己的worker，不能继续后组。

每组50秒工作、60秒含准备/验证/退出；50秒工作未结束且未进入cleanup发SIGINT，已cleanup则等待原finally；58秒TERM、59秒KILL、60秒前回收关闭管道。只清Popen新建进程组，绝不碰8000、现有服务/管理员会话；观察包装在真实线程退出后才恢复。HTTP5秒取消/KeyboardInterrupt/其他错误均设置stop、关闭response/client/App，不发本组余下请求或下一组。清理失败即整轮失败。被强杀/缺记录时送达数量写未确认，不自动重试；无DB/Lake/行情/恢复文件写入，进程退出只丢本组RAM。

#### 0.10.7 零业务准备核对与正式执行入口

准备只做AST/语法及纯内存摘要核对，不运行parent/worker/requests/supervise、真实HTTP、App或子进程；不连接prod、不打开Parquet。相关自检使用固定字面摘要，不生成性能成绩或冒充集成测试。至少核以下情形：

| 核对项 | 固定预期 |
|---|---|
| 正式配置 | 4/0.4/5、N=500/R=1500，无40/45、replace/patch预算；当前Spec由正式对象取值 |
| 全正常 | 两组各2次、最大4次、正常第2次可有2条累计load；两组独立、识别清理成功后预测 |
| 数量 | prefixRows=1500及实际更少合法；1501/非整数拒绝，识别输出501拒绝，不用20000作本轮通过线 |
| 状态 | NO_CANDIDATE/PRECISION_PENDING原合法null可通过；EMPTY/DELAYED停止，未覆盖求界照实说明 |
| 时限 | HTTP>4或预测compute>0.4拒绝；未收完为null，不按elapsed冒充通过；总截止5 |
| 再次与来源 | 第2次同源、同结果合法，源/完成根/digest变化拒绝；不要求缓存必须命中 |
| 首错停止 | 第1/2/3次不合格后，后续请求数均0；取消/清理失败不进后组，无自动重试 |
| 消息和回收 | 最多7帧/2个request_started；第3次或cleanup后新请求拒绝；成功必须2次均有观察且回收；50/58/59/60与原父子退出一致 |
| 原工具合同 | 合法samples=1/mixed_single可构造，samples=2仍拒绝/完整计数仍5；不调用原main/run/validator或私有HTTP |
| 无副作用 | 仓库仅四份原文档；调用和零业务检查片段限/private/tmp，产品/工具/测试、旧诊断片段和其他修改不动；零真实请求 |

正式执行另获授权后，唯一拟用命令（本轮不执行）：从仓库根`GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -B /private/tmp/xxm_bounded_read_retest_20261102.py`。按当时工具网络/本机服务权限申请，不改变业务来源。结束输出4次以内表及覆盖/失败/未执行，交review；不自动进入第四批、90/120、20次正式P4或新增基线，不以根数变化推算耗时或真实标签一致性。

#### 0.10.8 准备后的独立审计

已按本节在/private/tmp/xxm_bounded_read_retest_20261102.py准备新片段。旧诊断文件保持原样；新片段没有40/45秒、预算replace/patch或只发1次的残留。实际只变更四份原方案文档及/private/tmp准备材料，产品/工具/测试/配置未改，未提交或部署。

独立核对了专项§15、本文§0.3/§0.7—10、技术方案§21和产品说明，并从当前CodeGraph及源码核对isolated_app/collector/原_observe、两份runtime/Spec预算、分钟source→query→forecast和真实路由消费者。范围始终1500，原group samples=1/完整计数5不变，2次临时安排不冒充完整P4；首次与再次可有两条累计load，每条仍只一次两源读取。旧第三批“尚未提交”的现行状态和阶段表已同步4debb8eb3及本轮准备位置，原4.84秒失败/7.03秒诊断成绩未重写。

静态及纯内存检查实际结果：

| 检查 | 结果及证据边界 |
|---|---|
| 新片段语法/AST | 通过；固定signals→forecast、各(1,2)，4/0.4/5及1500；无业务预算替换、无原main/run/validator调用；最多7帧/2次和50/58/59/60退出规则均核实 |
| 字面摘要检查 | 29项通过：1500/400根、两组正常第二次及2条累计load、NO_CANDIDATE/PRECISION_PENDING合法null；1501/非整数/501输出、HTTP/compute超限、空/滞后、来源/结果变化及重复读取均拒绝。仅调用摘要核对函数，不是HTTP/集成或性能成绩 |
| 首错/取消/退出 | 从控制流独立核对：请求失败退出循环、设置stop、关闭client/App；父收到不成功组即break，不建后组；只回收自己的进程组。成功需两条观察及退出0；q._CACHE须恢复原对象后才计cleaned，强杀/缺记录保留未知 |
| 来源和静态环境 | 沿用上一轮已核的显式local/分钟开启、原prod连接配置/正式Gold两目录及依赖；本轮未连接数据库、打开Parquet或复测可用性，真实连通/完整性留首请求原检查 |
| 文档与范围 | 四文档本地链接、文档完整性三组及限定diff空白检查通过；仓库业务/工具/测试和既有其他修改未被本任务改动 |

准备未发现尚需管理员拍板或必须修改产品代码的阻碍；已具备在后续明确执行授权后运行本节小范围复测的准备条件。**本轮真实请求/App/子进程/DB查询/Lake行情读取均为0；仍无1500根真实性能成绩，不进入第四批。**准备检查不升级既有580例为真实性能或逐根标签验收。


#### 0.10.9 本次真实执行授权与结果登记（2026-11-02）

管理员已明确授权启动并汇报测试结果；本次仅执行§0.10.2—7准备好的最多4次请求。§0.10.1/7/8中零请求和“只准备”是上一轮的实际停点，本次解除不执行限制，不改变其余预算、1500根、来源、首错/退出和不推进第四批的要求。临时片段静态自检29项仍通过，未改真实执行片段或业务代码，不重复预读。

实际命令使用§0.10.7；受限网络/本机服务按工具权限申请，不先在沙箱试探。数据库白名单仅prod core_serving.trade_calendar：SSE、trade_date/is_open/pretrade_date及原context聚合；范围查询最多376个开市日形成有限日历跨度，必要未来日历最多91行/90自然日。分钟来源仅正式Gold上证m60四键+close及四键+macd_dif/macd_dea/macd/原版本参数检查；时间与日期由本次计划确定，最多1500根。无数据写入/导出/全局读取、完整响应保存或附加请求。首次/再次4秒、预测400ms、客户端5秒及50/60秒退出保持。

本次实际以既定命令执行一次，退出码0。发送/原collector实际收到均为4次，两个group各2次；没有重试、其他HTTP或追加读取。当前HEAD为13d4559e0（其他文档提交），此前4debb8eb3之后本任务产品/工具路径没有提交差异或工作区改动；未替换实现、预算、Spec、来源或校准。未保存完整响应/行情/恢复文件，以下是白名单摘要。

| 顺序 | HTTP/来源/字节 | 完整HTTP秒 | computeSeconds（预测处理秒） | 实际前缀/输出 |
|---|---|---|---|---|
| 识别首次 | 200/READY/93467 | 1.8188335420563817 | 不适用 | 1500/500 |
| 识别再次 | 200/READY/93467 | 0.09553233394399285 | 不适用 | 1500/500 |
| 独立空缓存预测首次 | 200/READY/1240；NO_CANDIDATE，NO_ENTRY_RANGE | 1.165508707985282 | 0.01819474995136261 | 1500；不是识别500根输出 |
| 预测再次 | 200/READY/1240；NO_CANDIDATE，NO_ENTRY_RANGE | 0.10064004175364971 | 0.012084458023309708 | 1500；同上 |

所有实际输入均为2025-04-16T10:30:00+08:00至2026-11-02T15:00:00+08:00，来源身份相同，未冻结旧业务日期。识别输出2026-04-28T10:30:00+08:00至2026-11-02T15:00:00+08:00。以下身份只用于本次同源/同结果核对，不是源码保护SHA：

| 事实 | 同次原观察值 |
|---|---|
| sourceInputId，四次相同 | acdb15972a5cf134da2e07572d318461c66abb2179771b15b2a74b852b9d5cd5 |
| 识别publicDigest，两次相同 | f1a3b8f24d7225e0f54254908859c900fff6b5e3e7470e177fc97a2ee06514f7 |
| 预测publicDigest，两次相同 | efbe40c3b29e77a95cce00434fdb7e1d42077ea845452ef48c6d9f39899caf30 |
| forecastId，两次相同 | 54b40e31bd877b86af4452bc224e92dd9c80cffe9229b1d791e75ad36396cabe |
| calendarInputId，两次相同 | 17b6f788cfda85fd47277908ad53909465b08a321e5444b6d3087dc6e88c5036 |
| 预测下一端点/barsAhead | 2026-11-03T10:30:00+08:00 / 1 |
| 识别身份 | xxm-direction-v0.4-r4，db435b39a3d198c126bfff567dfbe66faf74ff9299005578ec6b49bf065fd110 |
| 预测身份 | xxm-key-point-forecast-v0.6-r4，9994790178d64757462643fc37eba9e0945b118e91f1fdb85223db81db2a7b12；detectorSpecHash同上 |

| 观察/退出 | 实际结果 |
|---|---|
| 识别group | 0a537efe199f42d986d645b601c0e665；requestId后缀mixed_single:1:1:1及:2 |
| 预测group | 08c9ea72a9394f31bc174693e68b1ede；同样两序号，新进程/空源及预测缓存 |
| 每组源加载 | load-1源miss，pair/bars/indicators各1次；load-2源hit，三者均0；每load均seriesCacheReadCalls=1、signatureChecks=2。无同load重复读取 |
| 预测结果缓存 | 首次get miss/put stored各1次；再次get hit 1次、put 0。不是只走无候选前置返回的“缓存未验收”情况 |
| load跨度 | 识别1.189883083/0.039998667秒，预测0.803632333/0.042133334秒；原load含范围日历/签名/读取/计算/检查等，不当作纯磁盘耗时，也不与HTTP相加 |
| 缓存占用 | 识别1463879字节/1条；预测1472109字节/2条，均低于64MiB/16条 |
| 识别退出 | 清理0.19091658294200897秒；含准备/核对/清理整组5.339590709190816秒；pipe6417字节，returncode=0，cleaned/reaped=true |
| 预测退出 | 清理0.11732249986380339秒；整组4.204021584242582秒；pipe7075字节，returncode=0，cleaned/reaped=true |
| 整轮 | attempts=4、observed=4、两组成功、pendingRequests=0；无50/58/59秒信号、重试、额外请求或未完成项 |

预测覆盖说明：当前query只有recover_projection成功后才取得future_calendar、读预测缓存并调用forecast（miss时）。本次有目标/日历身份、首次miss+写入和再次hit，据此确认已实际通过EMA校准、进入预测生成及结果缓存；不是PRECISION_PENDING或无目标的快速前提拒绝。最终NO_CANDIDATE/NO_ENTRY_RANGE表示当前行情没有可用触发范围，不冒充有解或所有复杂结构分支已验证。原computeSeconds已包含本次处理至build退出，仍与完整HTTP分列；工具httpSeconds/clientSeconds原null不改填，本表HTTP来自唯一临时调用实际收取。

执行后独立核对原输出：四次HTTP200/READY、前缀1500、识别输出500、身份/结果组内一致、正式4秒及0.4秒、字节/缓存/次数、原group两次sequence及退出均符合§0.10.2—7；两组首次空缓存且预测未继承识别缓存，后次命中真实发生。该核对仅解析既有内存摘要，没有再次HTTP/查库/读取Lake或计算。

**本次限定m60复测通过，已交管理员review。**1500根的新范围成功完成且首次识别1.819秒低于4秒；没有按旧17312根/7.03秒计算精确加速比。未执行m90/m120、debug/双页/历史/20次P95、TS/浏览器或真实长短窗标签对照，不能据此宣称正式P4全部完成。未推进第四批、改代码/预算/配置、提交或部署。

### 0.11 后续性能优化TODO及本次停止位置（2026-11-02）

管理员已根据§0.10.9的4次m60真实请求通过，明确暂不做后续优化，完整保留为未来可能的TODO。原第4—7批尚未实施，现暂停其开发、详细观察、A/B及复杂改造；§0.3的技术顺序只保留将来重新启动时的依赖，不是下一轮自动执行计划。唯一完整调查/待做清单在[专项方案§16](../../../../docs/product/wealth-top-bottom-recognition-p4-performance-optimization-plan-v1.md#16-后续优化todo与暂缓决定2026-11-02)，不另建并行文档。

| 后续项 | 当前代码与不变点 | 将来设计/实施必须满足 |
|---|---|---|
| 第4批详细观察 | 现有原_observe、HTTP及computeSeconds继续使用；没有新增分阶段工具 | 覆盖context/范围日历、签名/文件、并行双源/SQL、转换、step、结果包装/缓存和退出；先补观察字段/自身开销/通信/取消设计，不额外读或重复算 |
| 第5批两层缓存A/B | XxmCache/SeriesEntry、预测结果缓存及SharedLoads均保持，命中前签名/日历/必要校准仍保留 | 分开测来源进度与最终预测结果，按专项§16的相同N/截止/源/目标及原预算安排；禁止只清空cache却保留专用签名来冒充“不缓存”，也不能用RAM替代真实读源。实际计划仍须重新核验并落LLD后获准执行 |
| 方向2B及第6批完整事实验证设计 | _load_series仍_validate_entry+完整_response，再由build生成窗口；cache.put/_deep_size及完整隐藏关联检查保持 | 先量成本；确有收益后才细化原result_validation.py方向及全部跨记录条件/反例，不能直接删完整_response、校准或坏缓存拒绝。尚未创建或批准该新文件 |
| 第6批缓存刷新/取消设计 | 无新的TTL、DG联动或持久缓存；当前64MiB/16条和原刷新政策不变 | 净收益证据明确才分层取舍；刷新先核实际两源更新/历史修订及可见性，再做配置/消费者审计与review；无明确收益保持，不为了TODO强改 |
| 第7批复杂改造及复测 | 不存在已确认可开工的复杂方案，没有相关代码变更 | 依第6批具体确认后才实施；不复制r4或恢复旧检查；沿原RC/PF、普通/debug/编号/历史、错误/取消/发布/退出核验，最后独立审计和限定真实复测 |

当前4秒/400ms/5秒、N+1000（默认1500）、Spec/规则/EMA、已精简Reader/日历/投影及简单结构复算全部保持。不安装、切源、配置更新或再次读取行情；本轮只登记TODO并提交四份原文档。已通过的m60限定复测不重新测试或作缓存净收益结论。

重新启动只在管理员另行安排后进行：依据原正式验收或实际产品的具体慢请求/超时、来源规模/用法变化或管理员明确要求，先核当前代码和证据，更新原方案/LLD，再按观察→有限测量→设计/review→必要实施推进。触发问题不等于授权自动试验，不能直接调用旧3对采样或40/45秒诊断。没有明确收益就保留现状。

正式P4第5步周期/模式/历史/单双页/20次性能已按§21.14.13完成，日线适用证据复用；页面第6步仍待管理员验收。本次未覆盖的复杂有解分支及真实业务一致性继续如实说明，不据此额外增加全分支真实重放或全历史测试。暂缓第4—7批不取消这些验收，也不作为恢复正式第5步必须先完成的前置。恢复验收须另行安排、沿现实现/原预算和首错停止；发生性能问题后再决定是否重开TODO，不能临时改代码绕过。P5/部署不推进。

本次文档核对：专项§3/§4.2/§4.4/§5/§6/§16、本文§0.3/§0.10/§0.11及技术方案、产品当前状态已统一为“本次小范围通过，后续优化暂缓为TODO，正式P4仍有未验收项”；保留原调查/条件性设计/失败记录和4次真实成绩，不把未做优化标成完成。

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

现有唯一XxmCalculator、XxmBar、Wave及原数字校验继续复用；识别v0.3-r4、预测v0.5-r4仅是本次修补前基线。首次当根价格/DIF、近B后远A、相邻1%原浮点顺序和曾突破记忆没有新增变更；不得因此恢复r2、独立日线候选或两位判断。

当前识别身份为`xxm-direction-v0.4-r4`，预测为`xxm-key-point-forecast-v0.6-r4`。完整Spec/跟踪字段、真实hash、恢复及预测内部配套已按§19验收；第3步复核该产物后迁查询缓存、完整内部预测模型和公开投影，第4步迁前端；旧身份和缺新字段一律拒绝并由同源重算，不添加兼容分支。不得硬写假hash或读取源码SHA。

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

新预测Spec完整集合见§6；版本固定`xxm-key-point-forecast-v0.6-r4`；已与识别v0.4一同限定验收并固定于50b0f22bb，实际证据见§19。两项真实hash已确定，第3—4步模型/API/缓存/TS消费这些实际身份，不重新生成另一套规则或用旧响应换hash。旧r2、旧r4-v2/正式v0.1-r4和混配快照/缓存/响应均拒绝，按同源重算；不设运行时切换。

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

目标字段及身份已在§2、§4—7确定，正式类型、计算进度、查询/DTO/前端消费者、Spec/hash和缓存已按§19—20完成迁移及限定验收；P4直接复用，不另起同义字段。旧等待快照/旧规则缓存不能按新规则恢复，也不能加新旧双策略兼容。环境装配、动态挂载和真实来源/页面验收仍属§21，不能据P3工程成绩宣称产品可上线。

### 3.9 保留规则、TODO与测试入口

保留：真实完成根；源收盘而非high/low；原始DIF而非柱高；相邻1%及前值0保护；零中性；最近两个历史同色段；首次同根只DULL；原参照和事件ID/时间关联；因果前缀/asOf/独立内存恢复；本节业务规则修正不改源SQL、数据库、Lake或鉴权。工程取数范围另按第三轮优化读取轮§0.9，不能将本句解释为禁止已确认的范围SQL修改。

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

来源修订时从空重建完整entry；不能将修订后的形成/原Wave合并进旧entry，也不能因旧终态不可改写而拒绝合法新来源。正常追加在候选副本里推进calculator、聚合所有结构、校验完整模型，全部成功才一次替换；失败不污染已有entry和早先返回对象。只保持有界进度加查询结果，不新增持久化或恢复文件。资源沿§9，同一400ms产品预测预算必须包含最多两份旧结构的检查/求解/验证，不拿专项1GiB/100MiB替代产品预算。分钟历史日历范围及预测早期asOf配合在耗时优化第三批按§0.6迁移；此前仍是现代码，日线1990起点保持，不新增日历缓存。

## 5. HTTP、内部模型及普通/debug响应的完整交接

### 5.1 文件、方法和调用顺序

在既有两份schema文件内保留已经实现的InternalXxm*完整字段、严格校验和query内部_response合同；第3步新增/迁移独立公开Xxm*投影及InternalForecast*/公开Forecast*。当前query已使用InternalXxmResponseDto，不再登记为按旧XxmPointDto过滤。禁止为了缩减普通字段先删内部关联；预测旧等待/多步专属模型按本批新合同整体迁移，通用数值/时间/引用检查保留。

在`src/biz/services/wealth/market/index_detail_xxm/response_projection.py`新增两个纯函数：

- `project_xxm_response(internal: InternalXxmResponseDto, *, debug: bool) -> XxmResponseDto | XxmDebugResponseDto`。
- `project_forecast_response(internal: InternalForecastResponseDto, *, debug: bool) -> ForecastResponseDto | ForecastDebugResponseDto`。

barsAhead在字段解析前只接受None或type(value) is int且值恰1；拒绝True/False、1.0和字符串，不依赖Literal转换后的检查。原生InternalXxmWaveDto与公开XxmWaveDto复用本schema的一处波段事实检查：sign严格±1、count严格正整数（合法1根保留）、price正有限、dif有限、start≤price_at/priceAt≤end且start≤dif_at/difAt≤end。原生字段名不变，根模型继续检查周期及来源时间范围。不能仅debug投影才检查这些事实。

每个公开嵌套类型均封闭字段集合，Pydantic沿现`extra='forbid', allow_inf_nan=False`；数值字段在解析前检查`type(value) in (int, float)`（整数计数严格int），拒绝bool/字符串数字/NaN/无穷，同时允许101这样的合法int价格；禁止用`Any`、任意dict透传内部结果。普通模型没有`debug`字段；debug扩展模型的`debug`必填且非None。根模型使用两种模型的联合，不用`exclude_none=True`省略全部None，因为合法必有的空时间、空方向和参照空值仍须返回。

识别query `build(session, *, period, start_date, end_date, limit, debug=False, now=None) -> bytes`；预判query `build`保留现业务参数，新增同样`debug=False`，也返回bytes。按§11第3—4步同步运行时直接调用方、直接读取DTO字段的消费者及本批API/验收测试，接口发送bytes，测试按新公开模型解析；不留旧DTO返回兼容。§11.2.6列明的P4保留工具在P3不运行、不作为通过依据，P4使用前按§11.2.3—4整体迁移；P5待删旧运行器不因本次返回变化提前修改或清退。流程固定，识别与预测不能颠倒“生成必填字段”和“校验完整模型”的顺序：

1. 识别由query._response构造InternalXxmResponseDto时验证全部记录/关联，再交project；project不再直接dump后重建同次内部对象，具体边界见§0.4。预测先验证prepared/KernelResult及原来源事实，不能把尚无forecastId/条件id/display的候选送进完整InternalForecastResponseDto。
2. 预测未命中缓存时，先按§6.8.1生成forecastId、条件id和同次display/必要说明，再验证完整InternalForecastResponseDto。命中则独立复制已完整的内部对象并重新验证全部字段/关联，不重新生成id或文字。
3. 显式逐字段新建公开dict→对应公开模型校验；普通投影不为输出debug而复制或格式化辅助数组、不生成debug字段，这不包括上游必要的完整事实/缓存验证及普通事件显隐计算，不能据此删除其检查。两个project只接受调用方已验证的相应内部模型，不重复直接重建；公开debug为了验证输出关联而进行的事实检查仍保留，不按“整条请求只许一次验证”删减。debug错误整份失败。
4. 一次model_dump_json().encode('utf-8')，检查最终字节及同一截止；预测仍先按§6.8.2退出load_entry并检查，再发布缓存，最后返回已准备bytes。
5. 三条API保持公开联合response_model供文书，实际返回Response(content=body, media_type='application/json', headers={'Cache-Control':'no-store'})，不再返回DTO或调用JSONResponse重编正文。直接Response不会替开发者做模型校验，必须以第1—4项为前置。日线识别、分钟识别及预测三个成功处理器已经设置no-store，本批保留现有响应头和发送行为，不新增API修改。错误响应保持现error_factory/处理器的状态、正文及header，不因本次另改全局错误处理；daily-waves既有成功/错误no-store不变。

直接Response的框架行为已用Context7核对[FastAPI自定义响应](https://fastapi.tiangolo.com/advanced/custom-response/)及[响应头](https://fastapi.tiangolo.com/advanced/response-headers/)：返回Response时不会替本批执行响应模型校验/序列化。因此第1—4项不能省略，OpenAPI仍显式描述公开模型，HTTP测试须核同一bytes和成功header。

预测缓存仅保存已完整校验的内部结果，读取深复制、按本请求重新投影/公开校验/编码；正常和debug不各算一遍，也不把普通删减结果放回完整缓存。debug投影失败即本请求失败，不回退普通成功；反过来也不得直接透出未校验内部对象。

### 5.2 请求参数

| 路由（均在现index-detail前缀） | 保留参数与新增参数 | 行为 |
|---|---|---|
| `xxm-signals` | 原`tsCode,period,startDate,endDate,limit` + `debug` | period仍只day，原默认日线300，上限2000 |
| `minute-xxm-signals` | 原`tsCode,freq,startDate,endDate,limit` + `debug` | freq仍60/90/120，默认500，上限2000 |
| `xxm-key-point-forecast` | 原`tsCode,period,asOf` + `debug` | day/m60/m90/m120，保留LATEST/REPLAY和完成时刻检查 |
| `daily-waves` | **仅**原唯一`tsCode=000001.SH` | 不新增debug参数；本地环境注册+前端debug手动请求控制；原严格422不变 |

前三个参数解析器继续拒未知参数、重复参数和非法空值。`debug`缺省或文本`0`→False，文本`1`→True，空/true/01/2及重复均原请求错误400。不使用Python字符串truthiness。普通客户端省略debug；debug明确传1。日线/分钟识别沿现trim+upper后判定；预测保留现原串格式检查，不新增trim或大小写容错。三条均仅上证，非法格式400、其他合法标的404；不得把识别的归一化顺手扩展到预测。鉴权与日期范围原语义保持，无另一个r4接口/算法参数。

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

### 5.4 下一根预测公开目标合同（P3第3步实施）

§6内核及本节完整公开模型/投影已在P3第3步实施，TS已在第4步迁移，并完成§20.8修复。P4沿既有预测URL、标的/周期/asOf/鉴权和debug请求规则，不新增预测入口。目标只下一根；旧20步、等待和结构形成即停算格式不兼容。以下为现行目标合同，真实来源与页面仍待P4验收。

`InternalForecastResponseDto`完整根为下文全部普通根字段，加sourceInputId/calendarInputId/precisionPolicy/references/selectedReference/nearestDecision/farEvaluated/conditions/precisionRanges/structureFollowConditions十项内部事实；内部不加debug嵌套。完整集合由query在_assemble或缓存命中交接处先验证，随后`project_forecast_response`仅做相应模型类型检查及公开字段整理，不再直接dump后重建同次内部对象，见§0.4。普通显式复制公共字段，debug再把这十项组为debug对象；对应公开模型的完整检查保留，只复用组装阶段已经生成的display和forecastId，投影不得重新生成。缓存保存这个完整内部对象，不保存普通删减结果。

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

## 6. 下一根预测编码设计（内核及公开合同已实现，真实来源待P4验收）

本节规定最新识别规则对应的单根预测；必须先完成§2—4的本次修正，再实施本节，不引入第二个识别器。本次三项修正后的纯内核已按§19.2限定验收，P3第3—5步接公开查询及完整预算；不读取真实行情。§16—17是修改前成绩，不证明本节新条件或完整请求性能已经通过。

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

系数全程Fraction，再继续按原sub/scale/abs比较构造误差线并反根。正常量级保留约0.001源值附近的临界未决带；绝对值误差项须随原值变化，不能把原source_options允许的选项遗漏后认证为False。PF16以正常量级独立Fraction验证此证明，不要求机器极值样本。分钟不套日线源误差，只使用原float运算包络。该专用证明以当前binary64环境为前提，实施测试核对环境事实，不新增环境配置、识别容差或安装项。

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

### 6.7 第2步已验收实现及第3步接口交接

| 位置 | 第2步已限定验收的要求 | 第3步及后续责任 |
|---|---|---|
| `forecast.py` | 替换20端点foreach、旧inactive字段和STRUCTURE早停；只保留本节两个入口及新结果组装 | 第3步query改为单endpoint和prepared调用，不保留旧序列签名兼容 |
| `forecast_entry.py` | 旧entry_partition/entry_cuts/stable_reference_on_band/reason_for/solve_entry_ranges整体换为单参照首次条件，去pending_rearm和旧全域入口 | 旧工具专属调用按P4/P5处理，本步不运行 |
| `forecast_next.py` | 新增DULL/STRUCTURE单参照条件、救A限定及结果组装 | 不复制step、不另建识别策略 |
| `forecast_detector.py` | 保留clone；possible_bars补前后check/原有限性；增加单根语义映射和近失效原语核验；移除event_options/activation_signature/confirmed_options旧多步/等待路径 | 有用旧工具使用前迁唯一正式入口，不留旧函数转发 |
| `forecast_math.py` | 保留Interval/intersect/merge/subtract/const/condition/scaled/difference/as_interval；复用types.py的ComparisonRanges实现比较求解、直接反根及0位整数，不另定义同名类型 | 删除float_bits/bits_float/positive_float_span/span_intervals、Affine的P维度、project_affine_prefix及仅旧路径使用的小函数；不保留备用全float求解 |
| `forecast_expression.py` | MACD节点只e12/e26/dea/field；移除prefixBars/prefixClose/target和P变量；保留原运算/同源绑定及包络小函数，新增单步原值/源值专用包络 | 第3步Python/TS表达式合同同次迁，不由旧JSON换字段充新fixture |
| `forecast_joint.py/forecast_paths.py` | 正式多步、多变量、全float路径实现移除；必要纯Interval能力已在forecast_math，原核验在forecast_detector，不复制两个求解器 | 先查全部活动引用；P4/P5旧runner明确未迁、未执行，不为保持其可运行而留下旧算法 |
| `forecast_text.py` | 删除reference_band/build_display_context/select_display及旧relations/activation/WAIT文案；替换为§6.6纯文字 | 第3步query移除这些旧导入，不再扫描历史60样本/95%分位数裁价 |
| `forecast_spec.py` | §6.9完整固定字段和类型；v0.6-r4及真实hash已由第2步验收固定 | 第3步模型/API和第4步TS登记同次hash，不伪造旧hash |
| `forecast_query_service.py`、预测schema/API | 第2步不编码、不验旧公开入口；本节已固定新输入/结果与下一端点交接 | 第3步按下列唯一顺序整体迁，移除_active_confirmation、rearmContext、20步及旧DTO |

第2步移除正式旧求解路径，不删除P5专属研究/报告执行器或原材料。依赖它们的未迁工具留明确停点，不能当新预测验收。生产/页面不发布中间版本，识别核心及其Spec/记录格式不得为了适配预测而改回旧规则。

`test_xxm_calculator.py`的七个当前核心节点仅需clone；其中activation_signature/solve_entry_ranges的顶层导入移到仍待后续处理的旧预测节点内部，避免收集当前核心时加载已删除函数。`test_xxm_r4_observation.py`同理：旧观察执行器仅由末尾两个P4工具节点局部导入，当前识别观察节点直接使用唯一产品类。旧节点的输入/expected保持且不执行，不增加skip或旧函数转发，不改工作区旧执行器。两个本步预测测试文件按M/PF人工样本整体迁移；P4/P5工具专属文件仍不作为本步执行范围。

第3步完整内部根继续为§5.4集合。query加入来源/日历、真实状态、规则身份和asOf；forecastId先由包含旧结构Draft、但不含debug/任何条件id/自身forecastId的内部事实规范生成，再按该forecastId+outcome生成普通Condition id，按§6.12增加relatedStructureId生成旧结构条件id。**Draft没有id是纯计算阶段的确定合同，不是公开响应允许空id；完整内部模型生成前必须全部填好并校验。**普通display同一次生成，正常/debug只投影，不另算标签或条件。

### 6.8 同一预算、异常与开发顺序

400ms仍包含calculator_at/恢复、前提检查、完整前缀EMA校准、日历/缓存处理、求界、全部来源组合及必要step、文字、模型、投影、一次编码、缓存复制/大小统计/锁等待和最后检查。有效截止=min(原4秒请求截止，本次计算或缓存处理开始+0.4秒)。缓存命中也在同一截止中，不能命中后再开400ms或读取完成后另加4秒。

第3步query采用以下唯一顺序；函数落点为现forecast_query_service.py的digest、future_calendar、build和query_service.py的XxmCache.get_forecast/put_forecast。删除_active_confirmation、旧inactive_result导入、等待/多端点路径；不恢复旧函数或另建查询入口：

1. 在原load_entry中取得已校验真实前缀。显式asOf先沿原资格检查；耗时优化第三批按§0.6.4补分钟范围外单日判断，仅用原4秒remaining，不另开时限；日线、范围内和latest不增加查询。然后EMPTY/DELAYED按§5.4生成完整来源状态结果，不进calculator_at/校准/未来日历/预测缓存。
2. READY在calculator_at、前提检查和任何预测缓存处理前建立同一400ms截止，check同时检查原4秒与该截止。用真实calculator_at和precheck_next_bar判断；仅普通关系静态无可能且无following_structures才生成静态结果，不校准、不读未来日历、不访问预测缓存。
3. 仍可能则recover_projection只用同次完整前缀一次。明确校准失败生成PRECISION_PENDING/CALIBRATION_FAILED，target/calendar身份为None，不读未来日历、不访问预测缓存；其他异常不降级。
4. 校准成功按§6.8.3从SSE日历得到严格晚于through的单个endpoint字符串及calendarInputId，不返回/构造20端点序列，不重复读日历。
5. 以现连接/Lake/period、detector+forecast hash、行情前缀指纹、expected/asOf和calendarInputId完整key查询缓存。命中也已经完成上述一次校准/日历核对；独立复制、完整内部重验、本次投影/公开校验/一次编码，不求界、step、编号或文字。
6. 未命中调用同次prepared的单根forecast，再依§6.8.1组装、校验、投影、公开校验、一次编码并检查32KiB；准备独立完整缓存副本和大小。已实际求解的NO_CANDIDATE、PRECISION_PENDING/ROUNDING_BOUNDARY及仅旧结构条件READY都按完整结果缓存，不能按status粗略跳过。
7. with块内只准备结果/body及可选缓存候选，禁止发布预测缓存或return。先正常退出load_entry，执行其现有yield后remaining()；再在with外执行同一check。只有上述全部成功才按§6.8.2锁内最后检查并发布，随后唯一return已准备body。命中和未求解的来源/静态/校准失败结果不写缓存，但退出和最终时限检查仍必须完成。

外层build的异常映射覆盖with内、上下文退出和with外发布：XxmQueryError原code/status保持；TimeoutError仍按503预算错误；ValueError/TypeError仍按来源/结果合同错误；其他普通Exception（包括缓存候选构造/发布的RuntimeError）转现XXM_QUERY_FAILED/500和中文“下一根预判查询失败，请重试”，API仍映射XXMF_QUERY_FAILED，不改全局处理器。asyncio.CancelledError、concurrent.futures.CancelledError明确原样抛出，其他BaseException不捕获。load_entry也须在通用Exception处理前原样抛出两类取消，并删除通用异常处理中的remaining()，防止错误发生后再查时间遮住原因。正常/出口的既定remaining检查保留，finally只释放资源，不发布。

外层build的异常映射覆盖with内、上下文退出和with外发布；已有XxmQueryError按原code/status重抛，取消和外部check异常向上传递，其他错误按§9既有映射。错误处理中不得再用一次时限检查把原来源/内部错误盖成超时。load_entry已经合法发布的来源SeriesEntry不因预测失败回滚；失败不发布本次预测候选，不污染原有效预测缓存。禁止发布后再做模型构造、复制、编码、大小统计或可能失败的检查。

每参照/比较/反根/来源组合/整数及最终编码前后共用check；无自动重试、后台任务、落盘恢复或价格跨度相关循环。第2步只把传入check贯穿纯计算，用M1—M5记录数学耗时；**完整400ms必须第3/5步把校准/模型/query/编码接齐后验，P4另验真实来源。**超限就停止说明，不以全未知、漏条件或放宽预算冒充完成。

| 情况 | 必须处理 |
|---|---|
| recover_projection明确CALIBRATION_FAILED | 仅该已知失败可转PRECISION_PENDING；未读日历不造target |
| 有保守临界段无法认证 | 在结果precision_ranges保留，不抛成NO_ENTRY_RANGE、不启用A |
| 确定范围/显示整数与原核验不同 | 整次失败，禁止降级未决或静默删价段 |
| 非法输入/状态/表达式、非有限必要原运算/反根 | ValueError向上传递；第3步按现源/内部合同或查询错误映射，不能捕获成成功 |
| deadline、取消、外部check异常 | 原异常向上传递，释放本次RAM；不以finally失败覆盖原错，不缓存 |

第2步已按以下顺序完成限定验收：已修正核心/clone→内部类型及precheck→原数学/来源包络复用→当前普通B/A条件→旧结构独立条件及唯一核心函数核验→普通完整step的多事件匹配→精度/status/显示合成→固定新Spec→独立PF测试与审计。每一项先有相应独立字面预期，不能先接旧公开DTO跑通再倒改字段。

#### 6.8.1 预测编号与完整模型的生成

沿现digest的sort_keys/固定分隔符/ensure_ascii=False规范序列化。未命中只生成一次forecastId；事实对象固定为tsCode/period/forecastVersion/forecastSpecHash/detectorSpecHash/computedThrough/requestedAsOf/mode/dataStatus/ordinaryState/direction/targetEndpoint/barsAhead/status/reasonCode，加§5.4十项内部事实。普通conditions和structureFollowConditions此时不含id；priceRanges规范身份只使用lower/upper及两端开闭。originWave在内部仍按price_at/dif_at拼写，公开投影才转camelCase。事实不得包含forecastId自身、任何条件id、debug/displayOnChart、display文本、适用/失效说明、refreshAfterMs、显示整数栏或请求计时，避免循环和显示变化改号。

forecastId=digest(上述事实)；普通条件id=digest({'forecastId':forecastId,'outcome':outcome})；旧结构条件id=digest({'forecastId':forecastId,'outcome':outcome,'relatedStructureId':旧id})。所有id和下列显示字段补齐后才构造完整InternalForecastResponseDto：

- dataStatus=READY且实际求解：同次KernelResult及真实prepared调用现make_display一次，取得四字符串；适用/失效两字段由query按§5.4一次生成，make_display不新增参数或负责它们。
- READY但静态退出或明确CALIBRATION_FAILED：已有真实prepared，按该退出原因构造诚实的ForecastKernelResult，target/barsAhead/selected=None、far=False、条件/未决数组为空，nearestDecision/references保留真实precheck事实；静态状态NO_CANDIDATE、校准失败状态PRECISION_PENDING。它仅表示未求解退出，不调用forecast/日历。仍用真实make_display生成四字符串，不能为此伪造已经求过价格范围。
- EMPTY/DELAYED：不构造prepared或KernelResult，query按§5.4.2的来源状态文字生成四字符串及必要说明；方向/状态/target等空值遵循§5.4。编号仍取同一规范事实，但无源/无参照如实为空。

编号生成与核验共用新增services/wealth/market/index_detail_xxm/forecast_identity.py的forecast_result_id(payload)及forecast_condition_id(forecast_id,outcome,related_structure_id=None)。身份事实仅显式列出的15项根事实及10项辅助事实；Root字段清单沿本节，不包含展示内容。该纯函数只依赖标准库，不依赖query/schema/研究/App，不读取数据。query用它先生成id；完整内部模型及完整debug模型在字段/关联合格后用它复核结果id和每个条件id。普通模型没有完整事实，只核forecastId长度恰64且为小写十六进制（含尾随换行在内的额外字符一律拒绝），不让前端补造或推算id。普通和旧结构条件id也须64位小写十六进制；关联旧结构id不改既有格式。

数值规范只作用于生成摘要的独立事实副本，不修改DIF、EMA、价格范围或任何模型原值：price/dif/lower/upper/e12/e26/dea/pCoefficient/cCoefficient/constant/factor/guard按原有限float统一表示，合法int数值先转同值float，±0统一0.0；bool/非有限值拒绝。barsAhead、sign、count、nextSameColorCount保留严格整数，开闭/farEvaluated保留bool，None和文本不变。已生成事实中的displayLower/Upper、条件id、display等仍排除。debug的originWave在核验副本上明确映射回price_at/dif_at，不兼容旧字段。这样合法101与101.0经过模型转换仍有同一编号；篡改64位有效外形的结果id、条件id或事实均拒绝，不能只验长度或非空。原错误生成的编号不兼容、不在缓存命中时重写，内存失败不发布；后续同源新计算按此唯一规范生成。规则Spec及算法版本不变，此修复只纠正结果身份与事实核验，不改变标签/价格解。

缓存命中保留已生成的编号/文字，必须重验完整对象；普通/debug及显示格式不改业务编号。列明的display/适用/失效纯显示文本不参加规范求解事实；nearestDecision.reason仍在既定十项事实中，本修复不另改字段集合。不读取历史样本或重新计算条件。

#### 6.8.2 缓存方法与退出后发布

预测缓存继续使用同一XxmCache.entries、现有('forecast', *key)前缀和总64MiB/16项限制，不新增索引、持久化或第二个缓存。entries类型改为SeriesEntry|InternalForecastResponseDto；识别get/put、_load_series及load_entry现有出口remaining检查保持业务路径。

- get_forecast(key, *, check)返回InternalForecastResponseDto独立深副本或None。锁等待、取值及复制前后检查同一预算；读取副本仍须在build中按完整模型字段/关联重新验证，不能把model_copy当校验。命中可沿原LRU更新访问顺序；失败保护针对已有条目内容、成员及字节计量，不承诺访问顺序从未变化。
- build在with内已准备完整独立副本，并用现_deep_size统计大小，全部计入原截止。put_forecast(key, prepared, size, *, check)只接该完整候选及已算大小，禁止内部再复制或编码。非法size/超缓存限额在改旧状态前拒绝并按预算失败；不得先pop旧项再决定能否保存。
- put_forecast以check提供的剩余时间有界等待同一锁，锁内从现entries浅复制最多16项的OrderedDict候选，替换本key、按原LRU及总字节上限淘汰候选；不复制其他SeriesEntry业务对象。全部构造/计量后最后check，才一次替换self.entries；finally仅释放锁。超时/取消/候选构造失败不改变原成员或有效内容。成功后不再触发来源出口检查或其他可失败动作，build只返回已准备bytes。
- check在query实现中返回min(原请求剩余,400ms剩余)的正秒数，非正立即按现预算异常退出；数学helper仍只需调用它，不另建时限。不得无界锁等待后才宣称满足400ms。

内部_response测试继续消费InternalXxmResponseDto，不机械改成bytes；只有build/API及其直接消费者按公开bytes迁移。旧P1/P2响应夹具中的WAIT/多步字段必须按独立新输入整体改为当前正例，或明确作为拒旧反例，不能只换hash复用。

#### 6.8.3 单个下一端点与日历身份

future_calendar保留现位置，目标签名future_calendar(session, period, through, check)->tuple[str,str]，恰为(endpoint, calendarInputId)。用现SSE模型有界查through日期起最多90自然日，逐日校验日期连续、唯一、升序及is_open严格bool。按唯一source.ENDPOINTS枚举本周期时刻，只取第一个严格晚于through的端点：同日有下一分钟端点则不跳次日；15:00末根及日线跨到下一开市日，周末/节假日照日历跳过。无覆盖、缺日期或非法开市标志按既有源合同错误失败，不当作无解。

anchor固定为through按现源时区确定的业务日期；calendarInputId沿digest，只包含从anchor到选中端点所在日实际使用的逐日(date,is_open)事实；不把未使用未来日期混入身份。搜索截止仍计90日上限，响应只返回1个端点；calendar身份进入现缓存key，合法日历变化必须导致缓存不命中。不得为取身份第二次查日历、用SSE缺少另一个交易所日历当阻碍，或把分钟端点统一改成15:00。

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

删除旧price_display_places/price_boundary_places/explanation_sample_count/display_move_samples/display_move_quantile和多步政策，不加可选算法/源误差参数。`__post_init__`按MAIN_SPEC方式逐字段严格验证类型和固定值，拒bool冒充数字。预测hash继续由自身全部字段按现`json.dumps(asdict(spec), sort_keys=True).encode()`规范生成，不手填hash、不混用detector的序列化约定。本表Spec已在50b0f22bb实现为v0.6-r4并限定验收，真实hash见§19.2；§16—17仅为此前基线。第3—4步只迁公开模型/消费者，不重做内核或改规则。

普通关系最多求两个实际参照：B有关系或有未决关系时A为0次。另最多两份旧结构独立条件按§6.12处理，不增加普通候选数，也不跳过其预算统计。每个参照只生成适用谓词的有限根及相关邻点/整数；一个C至多一次advance、至多4组来源核验。记录实际参照数、谓词数、反根数、点核验及step次数；同状态/门槛个数相同，价格尺度扩大不得按跨度增加循环。无96/192等未经依据的额外次数上限；400ms仍为计算时限，不通过增加源码保护或全float搜索达成证明。

### 6.10 预测测试设计与识别规则对应

§16—17只为修改前基线，本次内核及PF21—34内部成绩见§19.2；P3第3—5步完整请求/合同/限定预算验收及后续修复见§20.7—20.8。P4四周期真实来源和页面尚未验收，不得用人工或旧成绩代替。新数学测试放现主题`test_xxm_p3_forecast_math.py`及必要`test_xxm_key_point_forecast.py`，不创建新研究项目。业务expected来自§14字面事实，数学expected来自M1—M5/Fraction或明确原运算，不能由待测forecast生成。

| 编号 | 独立样本/明确操作 | 必须证明 |
|---|---|---|
| PF01 | M1/M2，C175.5/24.5；直接给ProjectionState，不校准 | 合法零成尚未首次反色结构，闭合单点可从未决带取出；邻域仍按独立证明，不调用guard=True提前丢点 |
| PF02 | 无wave、无B、count+1不足、B/A均曾破；正常当前价没过/当前TOP DIF<=0但下一根有可能 | 静态拦截且校准/未来日历0调用；不得用今天条件排除明天，正常变化可继续 |
| PF03 | M4近有确定范围/A更强；A求解及A资格helper一调用即失败 | A零调用；近只剩结构或只剩保持也算关系，不误称无解 |
| PF04 | NONE的B已破/A未破；B数学关系全False且无未决/A合格；反例A价未过或A已破；DULL/B无延续且A不存在/已破/救援确定为空 | 才求A且双价格门槛；DULL/B救A另断言下一根B严格破、同色/零、无新DULL事件；无救援按§5.4.2说明并保留target和实际选择记录，不把B失效拼回A、不声称当前真实标签已消失 |
| PF05 | B关系只有未决；另组B有宽确定范围+窄未决；B有非空窄范围但无整数；B关系确定为空、仅失效分类未决且A尚可能 | 前组PRECISION_PENDING/A零调用；有关系范围组READY、保留未决/无整数说明且不启A；最后一组按relationship_precision_ranges为空继续审A，不被全部precision_ranges误拦；最终未决不混近远 |
| PF06 | RC26新增A已破/B有效 | B正常求范围，A失效不连带B；来源/波段日期不同但数值相同不误认同一参照 |
| PF07 | M3及RC25；下一根首次同时出现相邻1%反向转折 | 仅DULL_FORMED，不同根结构、不推19根；当前一根有色+下一根零仍不足，两根有色后零可首次 |
| PF08 | P=±99到±98.01/±98.009形成边界、到±99.99/±99.991回转边界；P=0 | 原delta/g次序、严格方向和等号；形成/保持/回转谓词与唯一step相同，不累计、不跳零、不D±g改判 |
| PF09 | DULL/B正常有解且某C破B、真实r4本可救A；令A资格及求解被调用就失败 | 只核REFERENCE_INVALIDATED原语，不完整step顺带救远；普通不能写必然消失，farEvaluated=False |
| PF10 | 当前活动A，B在某C又合格；活动A仅有确定消失条件 | 始终沿A、B不重求；nearestDecision=NOT_EVALUATED，实际A求解才farEvaluated=True；不套B→A救援限定，有确定消失范围仍READY |
| PF11 | M5顶底三个整数；RC47价101回DULL及结构保持/回转/直接破 | 新记录的ASSESSING→DISAPPEARED关联正确，无WAIT，无CONFIRMED早停，无重复首次价 |
| PF12 | STRUCTURE/B破但A仍有效，A helper禁止调用 | 结构直接消失，关联旧id/reference_dif_break；不换A、不插入DULL |
| PF13 | RC53—58/65及RC97/105/106；DULL翻色、STRUCTURE翻色及同根原参照破；H=0 | 读完整events+structures辨别同根形成首次反色、首次反色价格消失STRUCTURE_PRICE_DISAPPEARED及原ref直接消失；安全未破价才FOLLOWING，新段NONE不等于取消；零不构成首次反色 |
| PF14 | RC63两轮；从首次反色根后的calculator_at进度开始 | 按新wave/count/history判断新轮，并按snapshot中最多两份旧结构求其有限失效条件；不读取完整历史、不复开已结束记录 |
| PF15 | 开4135.78/4136、开上界4140/4140.2、闭整数、单点、无整数窄段；Fraction根落相邻float之间及相邻float开区间；开下界9007199254740992的候选整数9007199254740993、闭下界9007199254740992和正常整数4136；故意让已证实点/整数核验不符 | 定向转换及开闭正确，无可表示C的区间必须为空、合法闭单点保留；整数候选先转实际有限float，变值者在原核验前拒绝，另两项不误拦并继续核验；合法整数与原点一致，不扩大单点/跨未知合并；不一致整次失败且无候选缓存，不挪价/降级掩盖 |
| PF16 | 正常量级正/负/0及三位源值；Fraction独立算Ef/Er及源输出误差；M1/M3正常整数 | 包络覆盖正常量级的原source_options选项；_expression_envelope通用round3仍拒认证；普通正常范围不得全未知 |
| PF17 | 非有限或错类型state/C、非法反根/坏prepared/错误活动结构；纯计算时文件及网络入口一调用即失败；不为浮点溢出另造1e308或10**400行情 | 明确失败不当无解或ROUNDING_BOUNDARY；输入/既有结果不变，check原异常不吞；正常人工求解不触发读取或写入，数据库边界另用依赖检查验证 |
| PF18 | 同C有2×2源组合：源值不同但语义相同/语义或参照不同；失败/开关debug/缓存命中 | 一次advance、组合各自独立clone和一次step、同源谓词绑定；一致可确认，分歧未决；失败不污染源进度。第3步再验普通/debug同ID/同display及同截止 |
| PF19 | M1/M2四周期结果独立性及等数量门槛的价格尺度变化；单元可记录数学计时但不用实机400ms断言；正式验收含完整前缀校准/日历/模型/编码/缓存复制与锁等待 | 记录调用数及数学耗时；完整400ms分层验收，发布前最后check、冷/热/异常不重复读或返回半成功。真实源留P4 |
| PF20 | 旧20步/P变量/WAIT/prefix字段/旧版本fixture；新单endpoint及内部Draft→完整模型/id；BOTTOM但DIF为正、空条件及错误period/through的文字输入 | 第2步内核拒旧收新、不回退旧求解；文字只读显式prepared，不猜状态方向，错进度拒绝；第3/4步再验HTTP/TS完整合同，不能用换hash或空旧字段兼容 |

#### PF28完整请求子样本的固定归属（P3第3—5步）

在现test_wealth_index_detail_xxm_forecast_api.py增加独立完整模型/HTTP样本，test_xxm_shared_loads.py保留共享加载并增加必要缓存边界；内部_response用例仍验内部DTO：

| 独立前置/反例 | 通过要求 |
|---|---|
| 先生成forecastId/条件id/display再完整模型；去任一必填id | 正常完整模型通过，缺失拒绝；不同debug/显示文字不改编号，实际来源/规则/日历/求解事实变更改号 |
| 同源普通/debug、两次命中及旧结构独立条件 | 公共字段及id/文字一致，真实校准/日历各按一次路径；命中零求界/step/文字，完整副本重验而非只copy；修改返回不污染缓存 |
| SOURCE_EMPTY/DELAYED、静态结束、CALIBRATION_FAILED | 不访问未来日历/预测缓存；按分支target和空值正确；只明确校准失败能PRECISION_PENDING |
| 实际求解后的NO_CANDIDATE、ROUNDING_BOUNDARY或仅旧结构READY | 保留实际target/选择事实并可缓存，不因status标签跳过完整模型/预算 |
| 编码、深复制、大小统计、get锁等待、put锁等待超限 | 全部在原400ms，失败不发布候选、不删原有效内容；正常近截止路径也应通过，不能过度拦截 |
| load_entry正常yield后出口检查跨4秒/400ms，或外部取消 | with内未发布；退出失败无响应/无新预测缓存，原已合法SeriesEntry仍在；不得删出口检查或发布后再return触发它 |
| put锁内最后check失败、候选构造失败、非法/过大size | 原缓存成员/内容/字节计量不变；正常提交后仅返回准备bytes，后面不再构造或验证 |
| 日线次交易日、m60/m90/m120同日下一时刻及末根跨日 | 只1个str端点且严格晚于through，m90保留11:00/14:00/15:00，周末/节假日依SSE；无覆盖/缺日/坏bool源错误 |
| 日历合法变更、仅未用远期变化 | 参与实际端点搜索的事实变化导致新calendarInputId和不命中；未用远期不混入id，不第二次读日历 |
| 三条xxm成功响应和错误分支 | 成功返回同一已编码bytes且Cache-Control:no-store；请求400/标的404/源或查询500/预算503及原鉴权正文/header保持；daily-waves策略不变 |
| tsCode规范串、大小写/空格、其他合法代码 | 日/分钟识别保留trim+upper，预测保持原串严格校验；不因共同debug解析扩大预测容错 |

### 6.11 预测配套的验收范围与后续边界

核心/结构进度/恢复/内部聚合及§6.12旧条件配合已按§19完成限定验收；完整查询、公开模型、HTTP/TS及PF28完整请求子样本已按§20完成。M1—M5/PF01—34中已验收的数学与安全目的保持；不拿§16旧成绩代替新证据。P4只补真实来源/页面与性能证据，不重复开发内核或重放专项。未经新发现及确认，不回改已验收规则。

完整Spec、同次projection复用、两类核验入口、精度及status/display均沿本章已实现合同；不得新增源读取、额外下一根端点、普通卡片或超过400ms的办法。若P4编码需要变更用户已定规则/公开字段集合/源表示/预算，按原要求先停报，不临时改算法。

### 6.12 旧结构下一根消失条件（本次三项修正配套）

本节内核已按§19.2限定验收；第3步复用真实prepared和本节结果，接公开查询，不重新设计求解。继续只下一完成根、先前提后有限边界，复用同次MACD/原EMA/源选项/校准/端点，无中点/价格遍历/新读取；原400ms含全部检查及最终输出。

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
- debugEnabled只取§8.3.1唯一resolveIndexRecognitionAvailability的结果，同时满足DEV、上证及URL精确debug=1；不再另写漏标的条件的公式，无页面开关或持久化，开发环境不自动开启。
- 波段工具仅上证日线，进入debug只加载工具代码；用户点击“波段核对”才开始计算。r4计算周期仍只上证day/m60/m90/m120，分钟行情沿已有配置与能力，不扩大生产分钟或其他标的。
- debug只增加本次r4结果的辅助字段与呈现，不另跑识别器。正常/debug公共字段、事件编号和预判文本一致。

### 8.2. 文件与职责清单

以下新文件名为本次LLD固定实现位置。不得改成另一套页面或复制识别算法。

| 文件（wealth/src下） | 改动/新增及唯一职责 |
|---|---|
| `pages/index-detail/IndexDetailPage.tsx` | P3接真实资格、普通模式参数及可选扩展交接，移除研究运行时import/hooks；P4接同一模块的动态加载、ready联动及挂载，不重新实现页面或控制器 |
| `features/index-detail/model/indexRecognitionAvailability.ts`（新） | P3第4步建立纯函数，集中返回本地正式能力和debug能力；输入DEV布尔、tsCode、search；不读env文件、不设置配置、不判断Lake目录 |
| `features/index-detail/debug/types.ts`（新，纯类型） | P3建立页面与debug组件的props、扩展快照、动态模块导出和解码函数签名；只用import type、禁止运行时初始化/import副作用；P4再接页面动态装配 |
| `features/index-detail/debug/useIndexDebugModule.ts`（新） | 仅enabled时动态import `./IndexRecognitionDebug`；管理idle/loading/ready/error、加载序号及retry，不执行行情计算 |
| `features/index-detail/debug/IndexRecognitionDebug.tsx`（新） | P3真实提取控制组件和固定五项导出，独占研究hooks/UI/primitive；P4才从页面动态加载并挂载同一模块，不留占位组件 |
| `features/index-detail/debug/xxmDebugContract.ts`（新） | P3迁入现adapter中参照/历史/等待/事件关联纯校验，按本文DTO的debug对象校验；不重算算法；P3由模块真实导出，P4动态注入，普通路径不静态导入 |
| `features/index-detail/debug/forecastDebugContract.ts`（新） | P3迁入现预判公式/区间/参照转换/历史关联纯校验，并按r4迁移；不调用预判求解器；P3由模块真实导出，P4动态注入，普通路径不静态导入 |
| `features/index-detail/debug/ForecastDebugDetails.tsx`（新） | P3实现并独立测试真实预测详情renderer；P4动态注入，正常卡不静态导入或求价 |
| `features/index-detail/debug/XxmDebugDetails.tsx`（新） | P3实现并以RC93/104独立测试真实关联/显示；P4动态注入，依据debug事实不推测原因 |
| `features/index-detail/chart/indexChartPointAdapter.ts`（P4新增） | 已按§21.4将工作区内toDetailChartPoint原样迁出，普通图与debug图直接共用，不留旧导出转发；字段、overlay、空值和原小数的字面测试通过 |
| `features/index-detail/chart/IndexChartWorkspace.tsx` | P3改普通悬停、传真实资格和模式，移除daily-wave运行时import/hooks/primitive创建并接好类型化可选扩展及renderer；保持同一组件位置；P4仅动态提供已有扩展和renderer；本地r4正常识别继续存在 |
| `features/index-detail/chart/IndexMinuteChartWorkspace.tsx` | P3接正常悬停、新recognition参数及可选decoder/renderer；P4从已加载模块提供同一参数，不再改Hook签名；不加分钟波段功能 |
| `features/index-detail/xxm/{types,adapter,apiClient,useIndexXxmLayer,XxmLayerUi}.ts[x]` | P3完成r4身份、正常/debug DTO、纯解码、客户端返回和原截止时间的Hook交接、普通字段view model/绘图及XxmSignalDetails；P3接页面真实资格和普通模式，P4只接模块ready模式变化及动态注入，XxmLayerUi不静态导入辅助详情 |
| `features/index-detail/xxm-forecast/{types,adapter,apiClient,useXxmForecast}.ts` | P3完成r4身份、正常/debug DTO和纯解码、客户端返回与原截止时间的Hook交接；正常卡只消费display等普通字段；P3必须接enabled及普通debug=0，P4接effectiveDebug随模块ready变化及动态注入 |
| `features/index-detail/sidebar/{IndexInfoRail,IndexTechnicalTab}.tsx`及预测卡 | P3接好forecast可选值及renderDebugDetails逐层透传，普通页面省略renderer、无资格传undefined；P4才注入已加载的真实renderer |
| `features/index-detail/daily-wave/*` | P3将调用整体迁入真实debug控制组件，保留算法/合同/1000根/几何，补enabled保护及稳定重试回调；P4只动态挂载，不二次改研究行为 |
| `features/nine-turn/ui/NineTurnLayerStatus.tsx` | 新增可选`showAlignmentDiagnostics?: boolean`，默认true；指数详情显式传debugEnabled；真实故障不受该参数隐藏；股票等调用不变 |
| `features/index-detail/model/indexDetailConstants.ts` | 保持唯一`INDEX_DAILY_HISTORY_LIMIT=1000`，不新增同值副本 |

生产无r4信息并不要求删除常规MACD的DIF/DEA/柱值。XxmMacdPrimitive和markerGeometry属于正常识别绘图；daily-wave三角与研究趋势primitive属于仅debug加载。

### 8.3. 页面props、延迟模块与稳定工作区

#### 8.3.0 P3提取完成与P4挂载的精确分界

P3第4步先完成以下最终代码，不建立临时兼容入口：纯资格函数→纯类型/两个debug解码器→正常decoder/adapter/client→两个Hook→页面/工作区及右栏全部新参数→实际两个详情renderer/研究控制组件与扩展→对应测试。普通Page/Workspace不得静态import debug组件、decoder、研究hooks/UI/primitive；只允许import type。原Page的waveReview/waveLayers调用、旧工作区review参数和研究对象构造同次移除，不留双路径。

P3页面是正式普通请求模式：依据真实DEV/标的算recognitionEnabled；日/分钟工作区传recognition={recognitionEnabled,debug:0}，Hook将它映射为enabled；useXxmForecast同时传enabled=recognitionEnabled、debug=0及现active/日期/分钟能力。右栏仅有资格时给forecast，否则undefined。debug=0就是普通合同取值，P4的模块idle/loading/error也继续使用这条普通分支；不能伪造enabled=true、decoder、renderer或module-ready让测试通过，不能把普通阶段当作debug页面已实现。

P3第4步必须建立IndexRecognitionDebug.tsx的5个真实命名导出：IndexRecognitionDebug、decodeXxmDebug、decodeForecastDebug、renderXxmDetails、renderForecastDetails；它们实际满足§8.3.4模块类型。两个renderer无Hook，由真实辅助组件渲染；研究hooks只在真实控制组件内调用。P3独立测试直接import该模块属于测试入口，不得反向把它引入普通页面的运行时依赖。

P4新增useIndexDebugModule及页面ready挂载/模式选择：动态import同一模块、传同一组已存在props，将已有普通debug=0分支扩展为§8.3.1的effectiveDebug；不再改公共协议、Hook签名、控制组件或图表数据交接，也不重写另一套renderer。另按§21.4将实际仍在工作区内的toDetailChartPoint原样迁到已规划的纯adapter，完成提取收尾，不改任何转换值。正常/辅助切换反例在P3用真实解码器/组件独立验证，真实页面动态流程在P4验收。

#### 8.3.1 页面内唯一能力计算

`resolveIndexRecognitionAvailability({development, tsCode, search})`返回：

- `recognitionEnabled = development && tsCode === '000001.SH'`。
- `debugEnabled = recognitionEnabled && debug参数精确等于1`。

该函数的development由调用方传`import.meta.env.DEV`；不是新的产品开关。周期资格仍由识别hook精确限制四种。其他指数保持不请求识别；现URL debug与page-init/权重等既有诊断能力不因本次额外扩大。

P3必须先完成资格、普通请求及以下props交接。P4接动态模块后，`IndexDetailPage`始终调用`useIndexDebugModule(debugEnabled)`、`useXxmForecast`等hooks，不放在条件分支。debug组件仅在模块ready、debugEnabled且当前页面存在可用行情时挂载。不是用CSS隐藏。

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

controller通过effect发布useMemo稳定的extension；所有函数useCallback稳定。useDailyWaveReview返回的外层对象和useDailyWaveCompanionLayers返回的外层对象不作为memo依赖；显式依赖实际阶段/数据/owner和稳定callback。现retryNineTurn等新建箭头须在提取时改为useCallback，相同业务数据/owner不重复发布，避免onChange更新父组件后形成循环。页面只接收ownerKey等于当前owner的扩展，且渲染时再检查debugEnabled及owner一致。旧控制器清理回调也携带ownerKey，不得清掉新实例的结果。扩展为null时普通工作区立即只消费普通数据。ownerKey始终取普通asOf；普通Page/controller/右栏/forecast的日期和数据不受研究覆盖。工作区只在owner匹配且chartOverride非空时，整组使用该override的candles/dataKey/九转/趋势/状态/两种重试/primitive/padding，不得只换K线而保留普通九转/趋势。清空override立即恢复普通整组。

开启debug但波段未开启：chartOverride=null。URL debug变化沿现useIndexDetailController的search身份重请求，短暂显示加载状态，允许重建普通图、重置缩放/拖动位置和右栏回到基本行情。URL未变化时模块loading/error/ready及同数据扩展更新不主动请求普通行情，现points/dataKey及primitive按原生命周期保持稳定。波段ready后允许切换现研究dataKey；关闭波段或退出debug按原生命周期恢复普通dataKey，允许必要重建，不留旧研究实例。

#### 8.3.4 P3固定导出/props与P4动态使用

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
- P3实现延迟模块内`ForecastDebugDetails.tsx`及独立测试，P4动态提供renderer；只在合法debug响应时由卡片该周期行末呈现“计算依据”的debug详情，展示已返回的精度、参照/路径和区间条件；不另请求、不求价、不改普通display文字或行状态。普通/生产不传renderer，也没有该详情DOM。源代码/绝对路径不得显示。
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

primitive只有资格成立时创建，按标的/周期稳定；结果更新调用setMarkers，失败/关闭清空；URL debug变化允许随普通行情重载重建；同一批数据的辅助模块状态变化和setMarkers不单独重建图。label布局/颜色/圆点规则不修改。

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

共享DetailChartWorkspace不新增r4/debug知识。通过现mainPrimitives/macdPrimitives/renderTooltip/renderPanelHeader/mainPriceScalePaddingPx扩展即可。正常mainPrimitives引用需稳定；不将模块phase或扩展对象直接加入重建依赖；URL debug变化导致原行情重载时允许按现生命周期重建。共享缩放、拖动、四窗同步、九转绘制和高度变化规则不改。

### 8.8. 自动测试与验收清单

所有新合同样本手写并按本文后端DTO核验，不能把旧r2 JSON改hash后作r4真值。允许读取原报告作历史证据，当前有效测试改为r4独立字面样本。

本表列最终交付要求，不把P4条件提前算成P3已实现：P3执行§11.4第4步的身份/普通及debug纯解析/客户端返回/同一deadline/普通悬停及必要调用测试；本表纯DEV资格/必要参数、真实辅助renderer/控制组件、扩展交接及静态依赖拆分在P3独立实施验收；URL动态模块加载/ready注入、页面生命周期及真实生产构建/本机静态页面在P4实施验收。同一测试文件含两类节点时逐节点登记归属，不用整文件排除掩盖P3应通过的用例。

| 测试位置/新增组 | 必须断言 |
|---|---|
| `model/indexRecognitionAvailability.test.ts`（新） | DEV true/false、上证/其他、无debug/0/1/其他；生产debug=1仍正式和debug都false；没有任何Lake依赖 |
| `debug/useIndexDebugModule.test.tsx`（新） | false不import；true才import；退出前迟到resolve/reject不发布；重试不算波段；模块对象不存业务数据 |
| `xxm/adapter.test.tsx` | 正常/EMPTY/DELAYED独立新合同；旧r2身份/错hash/混合源/重复日期或ID/NaN/state方向非法拒绝；正常strict原值对图，模式字段越界拒绝；普通无历史字段仍通过 |
| `debug/xxmDebugContract.test.ts`（新） | 正常time/id和debug双向对应；悬挂/重复/错期/错原参照/结构关联/旧等待拒绝/窗口前形成记录/根末NONE但仍有事件，合法及非法均覆盖 |
| `xxm/useIndexXxmLayer.test.tsx` | day生产也无请求/primitive；本地day与三分钟仅支持集合；模式/indicatorVersion/key隔离、取消、迟到、失败清旧标记；debug decoder未ready不发辅助请求，普通请求继续 |
| `xxm/apiClient.test.ts` | 普通省略debug、debug明确1，原路径/日期/limit不变；5秒、scheduler、外部abort、失败finally清理 |
| `xxm/markerGeometry.test.ts` | 正常最小event含必填displayOnChart；True生成标记，False保留事实而不画，不依赖debug字段；不改变原颜色/位置/连线/拥挤规则 |
| `xxm-forecast/forecast.test.tsx`、identity测试 | 正常公共DTO可用；debug解码只在显式模式；r4双身份、旧/混合hash拒绝；各状态必要display与空值；不拿r2输出当预期 |
| `debug/forecastDebugContract.test.ts`（新） | 新下一根所选参照/条件/未决区间及六字段参照；近有解A未调用，近失效不等于总体消失；旧entry/等待/20步/CONFIRMED/ZERO_RESET格式全部拒绝 |
| `xxm-forecast/useXxmForecast.test.tsx`（新） | disabled/生产无请求/监听/刷新；技术面激活、四周期按能力、同模式重试、模式变化取消、历史不刷新、迟到不覆盖、研究日期不进入预测 |
| `pages/index-detail/IndexDetailDailyWave.test.tsx`及新`debug/IndexRecognitionDebug.test.tsx` | P3将原4个依赖普通URL按钮的行为样本迁至真实控制组件+真实工作区的测试内Harness，完整保留手动start/retry、日期隔离/1000/不匹配/超时/迟到/研究退出覆盖；页面文件P3验证普通URL无研究入口/请求，P4再加真实debug动态挂载/退出场景，不skip或整文件排除 |
| `pages/index-detail/IndexDetailPage.test.tsx` | P3验纯资格、普通新参数/简要悬停及生产前端无请求/卡片，P4验实际动态模块和生产本机静态页面；不能用P3模拟替代P4真实构建/浏览器 |
| 现daily-wave所有单测 | 人工数值、适配、几何、共享三角、开放尾段、无起点说明、键盘、空间不足及44px全部保留；新增enabled=false误调用start/retry仍无请求 |
| NineTurnLayerStatus及共享回归 | 指数普通hide诊断但真实错源/权限/错误可见；debug显示数量；股票默认不变；指数/股票日/分钟共享图无缩放拖动退化 |

P3还须在IndexChartWorkspace.test.tsx中将旧review prop样本迁为唯一debugExtension；真实两个renderer分别放debug/XxmDebugDetails.test.tsx、debug/ForecastDebugDetails.test.tsx覆盖。测试内Harness只负责将真实控制组件onChange返回值交给真实工作区，不新增产品中转组件；网络/来源可明确mock，但控制组件、扩展、解码、renderer和工作区必须真实。P3迁移前列原节点→新节点映射，原逻辑输入和独立预期保留；禁止删除覆盖、skip、空壳组件或整文件排除来凑全量Wealth通过。P4页面节点是新动态集成证据，不能替代P3保留下来的独立行为覆盖。

生产构建不能只靠jsdom模拟DEV=false验收。P4必须完成真实生产构建/本机静态页面，在不部署、不改共享服务下确认无r4 DOM、相关请求或debug模块预载；本地开发真实路由另验功能正常。记录normal/debug Network、控制台及图层/图表创建次数；build chunk检查仅辅助，不能代替浏览器请求证据。后端生产路由禁用由本文另验，不以此处浏览器通过替代。

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

## 10. P5当前清退清单、资料收敛与验收

本节已按2026-11-03当前代码重新审计，不再把P3/P4已经完成的迁移列为待开发。P5第一步当时只审计和编码设计，未迁移/删除或执行测试；第二步现已按本节设计实施完成，结果见§22.9。先迁出保留能力及消费者、定向交接合格后才清退旧执行链；当前完整删后回归仍留第三步，不加兼容层。

逐文件明细是本节附件：[代码与测试103文件清单](index-detail-top-bottom-recognition-p5-code-audit-v1.csv)、[reports的3503文件清单](index-detail-top-bottom-recognition-p5-reports-audit-v1.csv)。CSV是供人review的设计附件，不是产品配置、自动删除脚本或运行时读取要求；第二步已逐项补执行结果，代码附件另列执行后保留定义。原行号/状态/大小仍指第一步审计时点，不能当当前文件存在的证明。清单外文件不因名称相似自动纳入。

### 10.1. 范围、顺序与硬边界

1. 正式`src/biz/services/wealth/market/index_detail_xxm/**`、queries/schemas/API、App本地装配、Wealth页面和独立daily-wave算法均已完成P3/P4；它们不是旧r2目录，不删除、不重新迁移，不改变规则、Spec、输入来源、公开字段或配置。
2. 本次审计允许静态阅读现有旧源码确认用途；**不从Git加载执行旧算法、不捕获旧结果、不运行r2/r4或两位双组比较、不读取源码SHA证明产品未改**。已存在的原始数据/图片身份核验与源码保护分开处理，不能一并删掉。
3. `xxm/`开工审计41文件为30个整文件清退、7个局部精简、4个保留；加主题测试/人工材料和4个现工具，共103个代码或测试文件逐行列明处理。旧函数没有真实保留用途时不因“它是纯函数”机械留下；有效数学和输入仍按下列明确落点保留。
4. 本需求reports开工清单共112个目录、3503文件、744135468字节；其他行业、DG、指标内核和其他主题的reports不在本轮。**原先“reports/所有CSV/JSON/README一律保留”的要求取消。**无用中间结果、过时假说/错误解释、旧API响应、测试日志、重复账本、源码ZIP和文本源码副本按附件删除；原图/原讲稿/必要输入、有效结论及r2设计开发历史保留或收敛。
5. 删除和迁移均按附件具体路径进行，不按扩展名或父目录批删。执行前复核当前Git状态和消费者；出现新的活动调用方、清单外文件或他人冲突时停止说明，不能擅改清单或覆盖未提交内容。
6. 不增加清理框架、配置、用户参数、网络、数据库/Lake写入、后台任务或备份源码；不恢复旧类/模块别名，不把旧算法装进ZIP、`.txt`、Notebook或文档代码块留存。Git历史不重写。
7. 资料收敛和测试交接先完成，同次明确改动验收后才删原文件。中断只按已完成文件与当前Git差异说明，不自动续跑、恢复旧执行器或新建备份；恢复工作先核对目标/源两侧，再继续未完成项。

### 10.2. 研究代码的最终处理

路径前缀为`scripts/research/index_market/xxm/`，全部定义及当前行号、消费者已在代码附件登记。

| 保留文件 | 固定边界 |
|---|---|
| `__init__.py` | 只留主题包说明，不注册旧实现 |
| `daily_window_precheck.py` | P4已仅保留`validate_window/read_window/isolated_client`并接正式装配；本次不重复开发、不改日期/来源/预算 |
| `saved_minute_window.py` | 保留原90分钟CSV有限定位/原字段校验；只在调用方同步资料路径，不新增识别或写入 |
| `peak_image_measurement.py` | 保留原像素量取、尺寸/颜色/遮挡限制及字面测试；不作为真实DIF或正式标签 |

| 局部精简文件 | 保留和必须移除的代码 |
|---|---|
| `acceptance.py` | 只留`sha/load_source/collect_readouts`；去`replay/main`、产品计算器/Spec、frozen导入和所有写报告路径。27条作者数值事实改读现有`software_readouts.json`，不再依赖5份混合旧模型报告，细节见§11.2.1 |
| `history_disappearance_screen.py` | 只留当前`observe_rows`及必要导入；去旧常量/读取/选日期/runner/源码保护，连同旧`dif_diagnostics/history_record/event_signature`删除。后三者只被旧formatter/tests使用，且仍按`histories/relatedTopHistoryId`旧合同关联；当前完整性由正式记录/恢复/HTTP tests覆盖，不为它们新增新格式化层 |
| `local_extrema_study.py` | 保留`SavedCase/CASES/sha/validate_rows/read_case/series_turns/summarize_case/literal_anchor_checks/benchmark`；限定原材料保护，删除`PREVIOUS`递归保护、`save_new/main`及`exec`。`notebook(out)`只组装未执行字典，见§11.2.2 |
| `near_first_review.py` | 只留`decimal_value/quantize_dif`及Decimal/ROUND_DOWN/number依赖；删除Spec/Reference/选峰/合并/重放/文件保护/CLI。没有两位识别模式 |
| `reference_window_review.py` | 只留`sign/build_references`的原始色段、日期、转折、价格窗口；删除`qdif`字段和两位导入，以及资格/选峰/生命周期/运行/落盘。它是独立研究事实工具，不是r4参照选择器 |
| `top_activation_math.py` | 只留`pair/daily_options`；整个`expectations`旧多门槛、第二根目标和20根结果生成删除。单步预期使用现M1—M5/PF独立样本，不保留旧业务答案 |
| `top_activation_real_math.py` | 只留`meet/minus/interval`及Fraction/pair；删除最强排序`entry_domains`、`proof/main`及旧读取/日历/保存导入。纯开闭区间数学有独立用途，其余旧业务不迁 |

另外30文件全部清退，完整名单见附件，包括旧r2候选/研究r4/两位计算器、双组配对、旧等待/多步预测和旧frozen输入。`forecast_expectations.py`的唯一真实消费者是待退的R1验收；其剩余通用helper没有当前消费者，表达式前提还是旧双价格协议，故整文件删除，不再为“保留纯函数”留下无用框架。

**补齐原清单遗漏：**`r4_history_comparison.py/r4_history_lake.py/r4_history_records.py/r4_history_worker.py`全部清退。它们是已完成922根历史对比的固定版本、Git源码加载、专属数据读取/通信/配对执行链，不是正式r4或正式分钟Reader；有用最终报告已在原方案/专项LLD，不保留执行重放能力。

#### 10.2.1 主题级工具与正式业务

`xxm_page_request_audit.py/.mjs`、`xxm_forecast_display_audit.py`已完成P4仅内存/真实路由/1500根范围迁移和验收，本次原样保留。`xxm_history_projection_audit.py`只做来源字段投影比对、无旧算法，也保留；它的既有全历史读源和输出行为不因清退改写，但不得自动作为P5验收运行。

本轮核对正式query/clone/API、Wealth的xxm/forecast/debug/页面消费者，没有导入上述待删研究模块。正式功能不依赖reports资料；资料迁移仅影响明确离线工具/测试和文档导航。保留所有daily-wave生产实现及其前后端测试。

### 10.3. reports逐文件审计与收敛

附件每行都有原路径、Git状态、字节数、内容用途、处理、唯一目标及先完成的交接。**原目录是否叫reports、文件是否是JSON或Markdown，都不构成保留理由。**记录是审计时数量，不冒称已释放磁盘或已经删除。

| 处理 | 原文件数 | 原字节数 | 范围 |
|---|---:|---:|---|
| 删除 | 3282 | 588580476 | 无用过程产物、旧执行脚本/预期/响应、错误或过时假说、重复事实和源码包 |
| 原事实/有效结论原字节收敛保留 | 207 | 155476195 | 原图、讲稿、必要来源/观察、日期纠正及独立峰谷结果 |
| 仅整理链接、历史范围与失效命令后收敛 | 6 | 57672 | 有效历史交付README；成绩、日期和事实不改，不宣称文件字节不变 |
| 仅抽取列明事实字段后删原 | 7 | 16775 | 混有旧模型解释的观察/来源JSON；根字段及必要的嵌套字段白名单见附件和§10.3.3.1 |
| 修改路径和未执行代码单元后收敛 | 1 | 4350 | 独立峰谷`review.ipynb` |
| 合计 | 3503 | 744135468 | 112个本需求旧目录；不触及其他主题 |

收敛目标只使用`reports/xxm/sources/`、`observations/`、`conclusions/`和`local-extrema/`四类，具体文件目标由附件固定。原路径下的目录名保留作出处，收敛后不再散放112个顶层目录；没有剩余文件的本次旧目录才删除。新增`reports/xxm/README.md`不计入221份原资料迁移数，只做资料导航及现行规则入口，不复制算法、现方案或重新写旧成绩；没有运行代码放进reports。

#### 10.3.1 旧执行代码及隐藏源码

67个报告`.py`、1个`.cjs`均清退；原清单45+18个旧执行器及4个“纯数值脚本”现在全部覆盖。4个数值脚本已无当前消费者，其SQL/模拟/EMA诊断不迁；已有数值事实及现源精度tests承担必要用途。

以下4个源码ZIP必须删除：`xxm_same_segment_a1_implementation_20261016/h1_research_source.zip`、`xxm_reference_rescue_r1_implementation_20261017/baseline_source.zip`、`xxm_research_freeze_20261024_01/research_before_first_batch.zip`、`xxm_top_reference_priority_20261021_01/test_source_before_gate_review.zip`。已只读核包目录：分别95/46/315/1项，含93/46/110/1个代码文件；非代码成员在当前工作区均有原文件，不需要从包中恢复资料。旧版本差异不作为再次保存旧源码的理由。

`xxm_rearm_discrimination_20261016_01/diagnostic_v1_source.txt`实际为Python源码，同样删除；报告里的旧源码diff、前版整篇方案拷贝和多步算法生成结果不因扩展名豁免。讲稿和管理员原话中的代码样式文字不是执行器，不按关键词删除。

#### 10.3.2 不保留的中间产物

- 旧API响应/浏览器DOM、完整事件账本、`.complete.json`续跑校验、失败/测试/构建/CodeGraph日志、gzip预期流、筛日期队列、派生事件CSV及旧截图中间版本均按具体行删除。
- 旧两位/合峰/最强选峰/等待/先取消后换峰等研究方案与中间解释删除；有效作者图、讲稿和原始观察另存，不能连同错误解释保留为当前开发依据。
- 原r2设计与开发主文档仍保留在docs/wealth历史入口；其中仍有价值的阶段交付报告按附件9份保留。保留历史实际成绩不等于恢复其旧运行指令。
- 两份saved_comparison.json混有旧本地选峰/模型结果，保留工具已无消费者，原始行情/图/讲稿另有保留，故删除而不以“原始片段”名义留存。同样的52条观察有多份字节相同拷贝，只保留附件指定的一份；`confidence=mapped`不能变成精确时刻金样本。27条数值摘录与52条标签观察独立保存，不合成成绩。

#### 10.3.3 资料交接、原字节和证据限制

1. 3个`local_extrema_study.CASES`窗口、量图原图、真实DEA的源CSV和必要SSE日历保留；7个混合JSON只抽取附件及§10.3.3.1明确的字段，禁止带回被删除的模型结论。抽取文件与原图/讲稿的“原字节保留”分别验，不能混称全部原文件不变。
2. 对保留的普通文件，移动前后逐字节相同；数据/图片既有SHA不变。仅路径迁移不能重新计算MACD、补列/值或修改原CSV/讲稿。源码不新增SHA保护。
3. 对7个抽取件，目标JSON根字段恰为附件白名单；原5件保留字段值逐项等于原字段。另2件必须继续按§10.3.3.1投影嵌套对象，不能直接复制整个根字段。没有再次投影的叶值逐项等于原文，数组长度/顺序不变；不增加推断字段，不将null补为确定状态。先确认字段和引用迁移，再删混合原件。
4. 27条数值摘录中11条原图原路径为已不存在的Downloads文件，当前reports亦无同字节副本。本次只确认这些路径已失效，不重新核图、不联网补图。摘录及其既有图片身份保留为历史事实，`collect_readouts`不得将“文件可读”冒称图证重新通过；目录README明确缺图条目，见§22.4。该旧限制不改变P4验收，不要求为P5补视频。
5. 资料目标当前尚不存在。实施时先检查精确目标无占用再移动保留项；逐个确认新位置及内容，同步全部活动消费者和链接，才能删无用原件。目标存在或原件变化即停止，不覆盖、合并猜测或自动加后缀。
6. 中断时记录哪些文件已移动/抽取、哪些消费者已改及剩余项；只核这些路径继续，不重新读正式源或重算结果，不把两份不完整目录当成功。没有持久化业务任务、恢复数据库或后台清理器。

#### 10.3.3.1 两份混合来源JSON的明确抽取设计

以下原文件均在`reports/xxm_macd_structure_20261011/sources/`；目标仍是附件列明的`reports/xxm/sources/xxm_macd_structure_20261011/sources/`下同名文件。本轮只补设计，不改原JSON，也不运行其记载的旧预测、找图或联网任务。

| 原文件 | 目标根字段 | 嵌套保留字段 | 必须移除 |
|---|---|---|---|
| `correction_context_20261012.json` | `research_date,existing_sources,new_public_sources,fetch_limits` | `existing_sources[]`仅保留`date,file,sha256,video_url,text_field,locator,excerpts`；`new_public_sources[]`仅保留原对象已有的`url,retrieval,purpose,title,publication,event_date,paraphrase`；`excerpts`和`fetch_limits`原值保留 | 根`analysis/software_labels_added/next_request`；`new_public_sources[].comparison`。原文字出处保留，不带旧模型相容性判断或后续找图要求 |
| `post_june9_author_check_20261012.json` | `research_date,sources,source_limits` | `sources[]`仅保留`id,url,title,page_publication,event_date,retrieval,paraphrases`；`paraphrases`和`source_limits`原值保留 | 根`scope/definitions_file/prediction_file/prediction_sha256/next_material/protected_previous_research_files/software_labels_added`及每个`sources[].comparison`。不带旧预测身份、比较结果或后续任务 |

后续编码逐文件写明确的字典/列表字段投影，不新增通用清理器或配置。固定根字段用原键直接取值；嵌套对象按表中字段顺序，仅复制该对象原来已有的键，不把可选缺键补成null。`existing_sources[].excerpts`、`sources[].paraphrases`等保留值独立复制，不改原对象、原中文、日期、出处、获取状态或限制。`file`中的旧绝对路径只作为出处，由新资料README映射新位置，不拿它自动读取旧目录。

验收必须逐项核：两份文件的目标根键集合准确；每个嵌套对象的键集合恰为“原对象键与对应白名单的交集”；两层数组长度和顺序不变，保留叶值与原文一致。仅检查根键不合格：必须用含`comparison`的原对象抓住嵌套旧解释漏出，并用保留了`purpose`的来源项、无`purpose`但有`title/paraphrase`的另一来源项证明正常差异不会被误拒或补值。旧分析和找图要求不得复制到新README、另存JSON或文档附录。

对应长期回归落在精简后的`test_xxm_acceptance_scope.py`：新增`test_retained_source_summaries_match_independent_literals`，按两文件参数化，直接读取迁后固定目标并断言作者摘要/出处/获取限制；完整预期在编码前按本轮已读取原文逐项核成测试内字面值，不调用投影过程生成expected。新增`test_retained_source_summaries_exclude_model_comparisons_and_tasks`检查准确根/嵌套键及禁止字段；同时保留上述两种合法可选字段差异，不把来源不足改成“已验证”。测试不读已删混合原件、旧预测文件或模型输出；迁移当次另在删原件前逐值对账7件抽取，删后回归使用独立字面预期，不因旧原件缺席跳过检查。

7件抽取、207件原样保留、6件历史说明及1件Notebook仍对应221个原文件目标；源文件总数3503及3282件直接删除项不变。新增两件抽取的原字节共8398，从原样保留移入抽取统计，不把抽取后目标大小冒称为原文件大小。

### 10.4. 测试清退与当前覆盖

103文件附件将源码和测试分开列出。当前r4规则、following、restore、internal_results、query、单根预测、输入/快照、P4工具和源/合同tests保留，不按名字含r4、r1或legacy删除。

- `test_xxm_calculator.py`保留CURRENT_CORE_NODES及7个现函数/22参数用例；删尾部3个legacy oracle/等待节点、专属helpers和导入，不能整文件删除。
- 3个P1迁移执行helper及`test_xxm_product_v1_migration.py`清退；旧response工厂和自测文件清退。它们能捕获旧Git源码或构造旧合同，正式消费者已经迁移完毕。
- `xxm_product_v1_cases.py`仍被当前snapshot_validation使用，**37组222根人工输入必须保留**。保留DATES/PERIODS、最小Case(name, values)和inputs时间映射；去旧Reference/Check、rules/checks/facts及等待/旧寿命/多步expected，不复制成第二份样本。原数值逐组在§22.3登记，不能由被测核心生成。
- `test_xxm_product_v1_cases.py`仅保留纯输入/不可变/时间映射/无运行依赖验证；旧37组业务expected删除。`test_xxm_snapshot_validation.py`仍使用全部37×4输入在各截断处恢复并继续；不能减少这一覆盖或改为永不运行的样本。
- `test_xxm_r4_observation.py`当前已经直接测试正式类及`observe_rows`，整文件保留；旧`r4_observation.py`研究包装文件才删除。
- `test_xxm_confirmed_cases.py`保留原10份依据及3例作者观察，去旧load_bars/失效validate_capture_identity，改直接读明确原源。只改当前记录字段/派生标记关联，不继承“new_top_DULL结束旧历史”旧解释，具体断言见§22.5。
- 原forecast_display与acceptance_scope不是可直接保留的现行suite：分别迁当前独立显示边界及原输入事实读取测试，删除旧多步/等待/旧CLI/旧结果oracle。不能去掉导入后仍拿旧响应充当前r4。
- 其余旧候选/双组/配对/历史专项执行suite按附件删除；当前RC/PF、恢复/查询及P4工具中对应覆盖须逐项核对，不为删旧协议复制一套通用通信框架。

#### 10.4.1 已完成迁移的跨层消费者

当前`tests/web/test_wealth_index_detail_xxm_api.py`、forecast_api、`test_xxm_shared_loads.py`及Wealth的`xxm/xxm-forecast/debug`fixtures/合同/Hook均已是P3/P4当前实现，本次静态核对未读取待删旧API报告作成功基线。保留它们，不再按旧文档第239/268等行号重复迁移。`r1Contract.test.tsx`、`rearmContract.test.tsx`当前名称不能作为删除理由，必须保留其中当前合同或拒旧断言。

`test_xxm_forecast_expression_contract.py`只验证当前六类单根表达式；不接受add/div或prefixBars/prefixClose/target。旧多步仅作少量明确拒绝输入，不能作为合法样本；测试清理按§22.15，不改schema或API。普通/debug字段与开关、客户端deadline、生产禁用、daily-wave四种三角/1000根均保持。

### 10.5. 删后验收与禁止误删

P5只做单组当前r4回归，不重开双组对比。新增/迁移用例按§22.5逐项设计，测试预期来自原规则、原始事实或手写数学，不来自旧/new同一算法输出。

1. 先跑迁移后的纯输入、算术、取窗、量图、Notebook和观察测试，再删旧实现；删除后的新进程再收集并执行保留测试，不能靠旧module缓存/pyc通过。
2. 规则/记录/恢复/查询/预测、API和实际受影响前端、根三份架构、研究依赖/组织及文档检查均按§22.6执行。单组超过60秒或首次失败先停查因；交易助手已知日期TODO不混入修复，不伪称全部前端通过。
3. 静态引用核对覆盖AST import、明确动态加载、CLI/README、Notebook code cells、报告代码/文本/ZIP。必须清零的是附件旧执行模块、类和Git加载入口；历史文字、原sourceRecord以及明确拒绝旧身份的字面值可出现，不为让rg全空删除有效事实。
4. 旧代码缺席后，正式r4、保留工具和全部已声明资料应独立可用。资料新路径及原字段/字节检查是明确边界；不能只看测试数量或r4标签数。
5. 本次清退不改变正式业务、路由和读源设计，P4有效真实证据直接复用；不自动重跑540次、922根或读取全历史。若未来实现发现必须修改正式代码或真实边界证据不再适用，先停止并补具体最小验证方案再review，不能临时增加真实请求。
6. 文档、引用和清单检查通过只证明本轮审计/设计一致，不证明已经清退、回归或释放空间。

#### 10.5.1 清退后的交付清单

报告必须给出每个附件行的实际处理、仍有消费者的阻塞及测试节点；已保留资料与目标一一对应，不能“整目录拷贝后再慢慢挑”。当前命令只保留正式r4及保留工具入口；全部无用目录空后再删除空目录。保留Git历史和有效主文档，不留旧执行代码副本或兼容层。最终交付仍须管理员review，提交/推送/部署按各自明确授权；本轮不执行。


## 11. 开发顺序、前置条件与上下游交接

P3/P4及P5第一至三步均已完成；第二步提交f057cefaa，结果见§22.9；第三步整体回归及最终审计见§22.16.6。不再从§20.2重做产品集成，也不再迁移或删除一次。§11.1—11.2为已实施设计，第三步已经完成核对；旧收集数量及首错只保留历史身份。当前等待第四步最终交付的执行安排，不自动开始第四步或重跑第三步。

### 11.1 保留能力的唯一落点

| 能力 | 当前落点和P5处理 |
|---|---|
| 唯一r4识别/预测、恢复、记录、来源和公开模型 | 当前src正式实现；不改规则/Spec/取价/邻峰或预测数学，不依赖研究包 |
| 真实分支观察 | 正式`record_decisions`及`history_disappearance_screen.observe_rows`已经可用；后者只精简导入和旧执行段，不复制step |
| 两位算术 | 原`near_first_review.decimal_value/quantize_dif`和最小人工测试；不留完整类/旧策略或另起模式 |
| 独立有理数 | `top_activation_math.pair/daily_options`、`top_activation_real_math.meet/minus/interval`及独立字面测试；当前单步预期已有M1—M5/PF，不迁旧两步oracle |
| 原始数据/作者事实 | 精简`acceptance`、独立取窗、原CSV/日历/27数值与52标签事实；文件按§10.3附件收敛，不产生策略事件 |
| 独立峰谷/量图/原始窗口 | 当前daily_wave扫描器、local_extrema_study、reference_window_review及peak_image_measurement；不成为r4依赖或选峰政策 |
| 路由/来源/客户端核验 | P4已经完成的daily_window、page_request及forecast_display现工具；保留原行为和预算，不重做迁移 |
| 手写恢复输入 | 原`xxm_product_v1_cases`的37组输入仍在原文件精简保留，当前snapshot_validation继续消费；旧预期和Git捕获执行链删除 |

### 11.2 P5逐函数编码与资料交接

#### 11.2.1 原输入读取与纯数学

`acceptance.load_source(root, period)`仍只接受已明确的原CSV目录，沿原`manifest.files`定位本文件数据SHA及原字段读取真实DEA。收敛后的源目录仍与CSV/manifest成组；不递归验证manifest里历史代码或已退文件，不补算缺DEA，也不从prod/DG重新下载。day 912根原材料、day_2020 1643根材料和三分钟原CSV是不同已存文件，不互相替代；它们是离线材料，不把全CSV输入恢复到产品请求。

`collect_readouts(root)`删除现有5份混合旧模型报告读取，固定读传入目录的既有`software_readouts.json`；目标为附件指定observations下`xxm_implementation_20261013`目录。根必须是27项list，每项必要键为`period/time/image/imageSha256/sourceRecord/software/source/softwareMinusSource/sameDisplayedValue`，这些键已核真实生产者全部27项共有；保留每项原字段，不重新产生差值/同显示判断，不把缺原图当作新图证通过。原image/sourceRecord字符串仅作历史出处，不作加载地址；新资料README按附件给16条可用原图的新位置和11条缺图。返回对象独立复制，连续两次调用不共享可变字典；不计算标签/EMA、读DB或写文件。27项及其`period/time/software`人工抽样预期直接用已存事实，不能调用待测函数生成expected。

`frozen_inputs.py`整文件清退，尤其不迁其`dea = dif-hist/2`兜底。`forecast_expectations.py`、top_activation_expectations及R1专属执行链不再是数学预期入口。`top_activation_math`只留`pair/daily_options`；`top_activation_real_math`只留3个区间函数及所需Fraction/pair，其他import及常量清零。daily_options只描述既有来源三位小数精度，不是两位策略四舍五入，不进入正式标签。独立测试直接写分数端点、正负.001舍入和开闭结果，不调用正式solver生成预期。

#### 11.2.2 独立峰谷、取窗、量图和Notebook

1. `CASES`3个源路径按reports附件分别同步，rows/frequency/SHA和原值不变。`read_case/validate_rows`仍按真实原字段校验；`summarize_case`不改转折、平台、尾部、段和价格窗口定义。
2. `protected_files()`只返回3个CASES和原量图图片的明确资料身份，`assert_protected`只检查这4份材料；删`PREVIOUS/run.json`及目录全扫，不再让算法源码、旧protected链或待删报告成为使用前置。
3. `save_new/main`删除，去argparse/writer/旧目录/`exec`等专属导入；`notebook(out)`返回字典，不执行代码单元、不写文件。out只用作已保留独立结果目录说明，不创建目录。
4. 现有`review.ipynb`移到`reports/xxm/local-extrema/`，同步source及读取路径；code cells保留正常纯工具导入，全部`execution_count=None/outputs=[]`，不保留生成器执行时的旧终端输出。测试只查结构/导入/路径和无副作用，不运行Notebook。
5. 3个旧峰谷结果JSON原字节保留，其`source`是原路径；新`CASES.path`为目标路径。Notebook对比必须先分别断言saved.source等于附件原路径、current.source等于其唯一目标，再用副本去掉这一个路径字段比较其余全部结果。不得宽泛删除数值、时间、count、尾部或SHA字段来凑一致。
6. `reference_window_review`去qdif与资格判断后，只返回原有phases/assignments/references/censored/raw_turns事实；每条reference保留原dif、price及其窗口/确认时间。不得新增selected/eligible或用其峰谷替换正式r4参照。
7. `saved_minute_window`保留现有行/字节/定位/时间/原始数值约束；source显式传新位置，existing SHA是原数据身份。它不是正式分钟Reader，原数据检查不能接入普通请求；P5不借此开启性能优化。
8. `peak_image_measurement`保持原算法与PIL延迟导入，原图片尺寸/颜色/遮挡/像素限制不变；仅调用处路径迁移，不重绘或补图。

#### 11.2.3 日线窗口及隔离客户端

当前文件114行已仅有`validate_window/read_window/isolated_client`，已使用正式本地装配和当前bytes合同。原LLD曾要求删除的capture/replay_checks/validate_capture_identity及旧b/MATH_KEYS/semantic导入实际已经不存在；不再重复实施，也不恢复它们供旧load_bars使用。

保留现START/MAX_ROWS/MAX_CALENDAR、真实字段/SSE连续性和finally恢复内存缓存/时钟/SQLite；不接新配置，不改日期范围或完整性规则。该SQLite工具只用于隔离合同验证，不能冒称正式源或性能通过。`test_xxm_confirmed_cases`读取交接已在第二步完成，见§22.9；第三步只按§22.10.6运行迁后文件，不恢复旧load_bars或修改此已验收工具补旧接口。

#### 11.2.4 P4三个路由核验入口及投影工具

page_request.py/.mjs及forecast_display.py现已符合§21.5/§21.14：正式装配、鉴权/只读、仅内存、独立受监督子进程、1500根、normal/debug和原期限均已验收。本次保持原文件，不增加--output/--candidate、写完整body或动态旧算法加载。

现`xxm_history_projection_audit.py`无旧算法；保留，但不把其全历史字段比对拿来当P5新增任务。P5只静态确认工具导入和其定向隔离tests；真实证据复用P4。若开发触碰本段正式工具行为，先停下补方案而不是扩大清退。

#### 11.2.5 当前测试与身份

正式Spec仍为§2及§19已验收身份，前后端类型/解码器/bytes/共享加载均按当前合同保留。旧version/hash仅可用于明确拒绝输入或历史事实，不恢复旧版本成功模式。r1Contract/rearmContract中的旧字段用于明确拒旧，继续保留；表达式只接受当前六种单根节点，不能把旧多步字段作为成功样本。

旧业务expected与有用原始输入分开：37组人工输入按§22.3保留，旧等待、旧寿命、多步条件预期删除。现RC01—110/PF01—34及其内部/公开分工不降级。删除r4_history及P1一次性迁移通信suite只撤销旧执行协议测试，现正式工具的预算、取消、通信和清理回归原样保留。

#### 11.2.6 活动消费者与资料路径同步

1. 正式src/API/App/Wealth不导入待删研究类或读取旧reports API成功样本，当前不需改运行时代码。保留当前路由、共享load、Spec、普通/debug和前端资格/deadline，不按旧阶段行号重做。
2. `local_extrema_study.CASES/protected_files`、Notebook代码单元、`acceptance.collect_readouts`及`test_xxm_confirmed_cases`、各纯输入/图像测试同步附件资料路径。原数值和原图的SHA保持，7个抽取件另以根/嵌套字段白名单验证；6份历史说明单列导航/失效命令整理，不将这些文件都称原字节不变。
3. `test_xxm_calculator`3个旧节点、`test_xxm_forecast_display`旧报告/frozen import、`test_xxm_acceptance_scope`旧预算/CLI/续跑路径、旧r4_records/forecast_expectations/研究包装消费者按附件清退或迁有效用例；全部测试收集必须覆盖迁后现入口。
4. 研究README的活动旧CLI、旧SHA运行前提及已删报告链接清零；只更新本需求相关条目，不重排其他研究主题。r2历史主文档保留，失效当前命令从主文档移除；不留一段“错但还能选”的并行说明。
5. 保留的历史交付报告按附件6份单独整理导航和显式历史适用范围，不改写旧成绩；旧文件路径可作为来源原文存在，但不能再是运行指令或点击死链。主索引和新资料README全部指向本次唯一目标。删除前核全部Markdown实际链接：保留资料的链接改为附件新目标；删除项的活动条目清除，必要历史出处改为非链接旧路径并注明当前入口。禁止留死链或为通过检查恢复旧文件。


### 11.3 各批开工前置检查

1. 核对日线合同§10、分钟合同§8和预测方案§36的目标入口与本文§2—7一致。本轮已同步这些文书；实施日必须重新核验没有字段/版本/空值分歧。发现分歧必须先修文档，禁止边编码边选择口径。
2. 核实施当日calculator/types/snapshot/query/预测/schema/API/客户端/decoder/Hook/工作区/离线工具的全量引用与dirty文件边界；本轮CodeGraph及源码依据在§0.2，不代替实施时引用清单。
3. 依§14及§6.10先确认独立预期和测试落点；旧正确安全检查保留，旧底部等待、跨根借价首次及无限跨段撤销预期不再是验收答案；首次反色/分隔/零柱价格失效、单根跳过/有效段结束及同根显示均须覆盖。新身份、解析与恢复拒旧必须有正常变化的反例证明不过度拦截。
4. 必须获得对应批次执行授权；P3、P4均已完成，P4最终验收见§21.14.14。P5第一至三步已完成，第三步实际3193/332、复用依据及最终审计见§22.16.6，不再按旧3298/3320或历史首错启动。第四步最终交付尚未执行；既有证据只在原适用范围内复用，不扩展为新真实源、性能或软件全匹配验收。

### 11.4 P3五步及P4/P5交接

#### 当前代码依据

1. 当前SeriesEntry保存points/events/structure_records，calculator_at有界还原真实前缀；新计数/跟踪极值、单根起点重置和asOf投影已完成本次限定验收，见§19.1。§17.4仍只为旧成绩，不代替本次证据。
2. 当前识别v0.4-r4、预测v0.6-r4，核心/预测提交50b0f22bb，专项工具及结果提交ec37c69ea，管理员已验收该范围。公开API完整模型/投影/一次编码及TS消费者已按下表第3—5步完成，工程证据见§20.7；P4真实装配、来源/性能及管理员页面验收均已完成，见§21.14.14。验收不等于部署或开放生产r4。
3. 内部真实来源、共享读取、原MACD/1%/EMA和预算保持；修补文件及内部证据分别见§18.3、§19，公开显隐和全部P3消费者已按§20.7—20.8完成。P4工具、环境、动态挂载及真实/页面验收不再列为待开发或待补证据；P5保持其行为和已验收边界，只按§10/§11.2/§22迁出有效能力、清退及回归。

#### P3实施步骤、前置与停点

| 顺序 | 开始前必须具备 | 本步必须完成 | 本步验收与下一步交付 |
|---|---|---|---|
| 1 新识别核心及内部结果 | §3代码顺序、§4恢复格式、§5内部记录和§14用例已经review；目标文件引用清单已核 | 原位置替换首次C/D、逐参照曾击穿、同根B→A、顶底1%回转、首次反色起比价、单根跳过及首个有效段结束；同步`types/snapshot_validation/spec`、统一`XxmStructureRecord`、`XxmStep.structures`、`SeriesEntry/_load_series/calculator_at`及完整内部模型；清理底部WAIT及旧无限跨段撤销，落实§3.7有限价格途径。完整Spec确定后生成`xxm-direction-v0.4-r4`的新detector hash | 全部识别case逐根通过；连续/增量/历史前缀/复制/恢复相同；已有正确安全检查不退化。此时仅证明内部识别，不能把旧预测或公开DTO不兼容当作新规则错误，更不能称页面可用 |
| 2 下一根预测内核 | 第1步新识别状态、结构首次反色记录、参照资格和clone已经稳定；§6数学及失败语义固定 | 撤销20根与全浮点细分、横盘前缀/中点代表；按§6先前提后边界，先B有解即停止，确无解再A。已有DULL和尚未首次反色STRUCTURE各自求下一根结果；首次反色后同时处理新循环和仍有效的旧结构有限跟踪。严格按§6.1/6.7的函数、内部类型和逐文件去向实施，包括forecast_next.py、单根核验/表达式及纯文字；移除正式旧多步/全float路径，不保留备用入口 | 独立数学/业务边界、零柱、来源精度、整数及取消/超时测试通过，记录数学部分耗时；完整400ms含校准/模型/query/编码须在第3/5步接齐后验收，P4另验真实来源。不能用数学样本提前声称完整预算通过 |
| 3 Python模型、投影、query/API和身份 | 前两步修正、独立回归及本次§19.3/§20.1专项对比review已通过；内部事实、下一根结果字段及双Spec内容已固定 | 完整内部/普通/debug模型和`response_projection.py`；query共享一次读取结果，迁缓存/forecastId/display/日历下一端点；三个识别/预测API接受既定debug参数并发送一次编码bytes；移除等待字段与旧多根表达式字段；同步直接Python DTO消费者及新合同人工fixture | 普通/debug公共字段、标签ID、预测文本相等；旧/混配身份拒绝，窗口外关联带齐、asOf不泄漏未来首次反色；4秒/400ms/1MiB/32KiB预算包括校验编码；未完成这一项之前，不用旧web通过结论证明新HTTP |
| 4 前端必要合同调用 | 第3步实际双hash和完整正常/debug合同已产生 | 纯TS类型→两个纯debug decoder→普通decoder/adapter→两个apiClient返回`{response,deadline}`→两个Hook读取和最终显示检查→普通悬停与日/分钟工作区调用；同次改受影响fixture。P3完成纯资格/页面及工作区必需参数、真实辅助renderer/研究控制组件提取及静态依赖拆分；普通请求用debug=0 | 类型检查、真实decoder/组件/扩展定向回归、全量Wealth和build；普通无debug字段可展示，研究旧样本迁独立测试保留。P4只接App环境装配、动态模块ready及真实页面/来源，不用固定true或假decoder |
| 5 P3整批独立验收并停止 | 前四步全部完成，所有直接消费者同一合同 | 按新§14逐项对账、预测下一根用例、API模型/一次编码/共享读取/输入恢复/前端必要调用/架构及文档检查；记录真实实现hash、数量、耗时和未覆盖内容 | M1—M5/PF01—34及识别独立用例全部对账。未执行P4真实来源/浏览器和保留工具、P5清退的部分逐项列明，不宣称整体产品完成。停止等独立验收，不自动进P4 |

第1—4项“按顺序实施”不允许阶段结束仍保留另一个可运行旧r4策略。开发中间状态不作为可发布产品，不给普通请求添加过渡开关。第3项需要的公开模型草稿必须在第1步修改内部字段之前已经写入本文，不能等编码时自由选字段。若执行中发现新业务边界或§6数学预算无法成立，先停止并说明，不依赖旧模型吞错或原20根路径兜底。

#### P4六步（P3整批通过后）

逐步编码、文件清单、配置交接、失败释放、性能测量和独立测试统一细化于§21；下表只保留顺序。现成的§1/§8/§9/§11.2要求继续适用，不能仅按本表六行编码。

| 步骤 | 动作与前置 | 结束证据 |
|---|---|---|
| 1 本地/生产装配 | 用既有显式dev/local策略装配三条r4与daily-wave路由，分钟另受原reader可用性；前端资格同步，不把日线绑到分钟Lake | 缺环境/生产/未知值相关API不进入source和算法，显式本地无分钟Lake仍可日线；生产debug不能绕过 |
| 2 页面请求模式 | 在P3已经存在的资格/props/decoder/client/控制组件之上，只接动态模块和effectiveDebug ready/失败/挂载；idle/loading/error沿同一普通debug=0分支 | 模块加载中/失败/重试/关闭/切周期/离开和迟到结果反例；普通/debug缓存和序号隔离且同源公共结果相同 |
| 3 辅助详情与核对图 | 动态提供P3已完成的真实renderer、控制组件及extension，接页面实际可用数据；不重写关联、图表交接或研究算法；仍手动核对及独立日期/九转/趋势/既定三角留白 | 默认无研究请求和图层；原数据与右栏日期不被研究时间覆盖；不把故障一起藏进debug |
| 4 保留工具成套迁移 | 首次运行前按§10—11清单迁`daily_window_precheck`、页面请求与预测显示工具，正常/debug、bytes、原deadline、明确周期/asOf/samples、纯内存、finally释放全部一次完成 | 缺旧运行器仍可用；无candidate/源码SHA/结果落盘；失败、取消、Node异常清理；不只改版本后运行旧报告入口 |
| 5 真实来源与预算 | 先获所需只读范围授权，使用既有隔离App/原路由鉴权；日线及实际可用60/90/120分别验源字段/时间/连续性/根数、普通/debug字节和冷/热耗时。仅在已声明20次性能验收时使用samples=20 | 4秒/400ms/研究8秒整链10秒、原字节上限；正常日线1000和20次K线P95预算；不足/缺周期如实未验收。不得复用旧日线922根替代分钟 |
| 6 页面与独立验收 | 管理员完成浏览器review；自动验收保留当前1600/1440/1280、45/180根、拖过301根等既定场景及生产构建反例 | 本地普通/debug、生产无功能、正常行情/右栏/同步和研究图均通过。必要分钟证据未齐不能进入P5，除非管理员另行改变范围 |

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
| Wealth现识别/预测`types/adapter/apiClient/Hook`测试、工作区/页面测试 | §8合同/迟到/截止时间、普通无debug可展示、同源公共值相同；P3验纯资格/必要props、真实辅助组件及依赖拆分，P4验动态页面和真实生产构建/本机静态页面 | 不静态加载辅助、不以false诊断隐藏真错、关闭清理、研究日期不影响右栏/预测、生产任何debug不请求r4 |
| 依赖边界/清退/工具 | 根三份架构、Biz不导入research/App/QTF、§10逐文件清退及§11保留工具 | 无旧算法/父类/动态副本/源码SHA保护；保留工具在旧模块缺席时正常人工输入可运行 |

全部字段/分支到case对账见§14.12。人工来源样本只证明对应规则，真实来源核验按下一节；不拿设计数量、mock或旧成绩冒充已执行。M1/M2的175.5/24.5合法零必须纳入回归；不得仅改max_future_bars、扩大时限或删复杂路径来冒充数学正确。

### 12.2 有界真实核验（实施阶段，当前未执行）

- 使用已有隔离本地App办法、原路由和原鉴权、只读来源；不重启共享服务，不通过mock声称真实接入通过。
- 先选择单上证有限日期/已有可用分钟的各周期，记录真实源字段/时区、读取范围、实际根数、响应字节、冷/热/历史/增量耗时及source ID，不补缺值或计算实际MACD。若正式服务需要更长历史，事先注明有界上限和来源，不把报告区间当计算起点。
- 新规则用§14、M1—M5及PF01—34独立预期；不再捕获旧v2或重建双组产品。真实来源另按唯一新r4及有界源字段/日期核验，不把人工测试冒充真实来源证据。
- 本地普通/debug对同固定前缀公共结果一致；分钟不可用时单列未验收，不能拿日线922根或人工替身抵充。
- 真实生产构建仅在本机既有App的/wealth静态入口验证，无r4 DOM/请求/辅助chunk预载；后端以生产设置构建隔离路由验无源调用。本项不部署到生产。
- 浏览器1600/1440/1280宽、45/180根、拖至301根以后，记录普通/debug的请求、控制台及图层/图表创建次数；退出研究恢复普通日期，标签/条件与真实API一致。页面最终交用户review。
- 每个测试组超过60秒停止查因；性能不满足400ms/4秒/8秒/10秒或字节限额时报告实际输入、路径数和耗时，先补方案，不放宽上限或退r2。

### 12.3 命令和交付对账

使用现有环境，不安装。实施时先确认测试路径存在，再分组执行：

- `.venv/bin/python -m pytest`选本模块人工/恢复/预测/投影及web路径；不得整组触发旧冻结数据回放或未授权真实读取。
- 根三份架构：`tests/architecture/test_subsystem_dependency_matrix.py`、`test_platform_legacy_guardrails.py`、`test_operations_legacy_guardrails.py`，另核Biz不导入research/App/QTF。
- Wealth定向/全量`npm --prefix wealth run test`、`typecheck`、`build`；真实本机静态页面单独登记。每组有界，不用skip/吞错过关。
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

本节是当前识别及配套用例目录。RC01—110及PF01—34的核心/恢复/内部查询/预测部分已按§19限定验收，具体文件、选择范围和成绩以§19为准；不把整个目录都标成未执行，也不把内部成绩扩大为公开验收。RC73/RC93的公开投影和前端、PF28完整请求子样本以及本批新增HTTP/TS边界，须在P3第3—5步验证；真实来源和页面仍依P4。§15—17只证明修改前版本。本轮只修文档，不运行行情、对比或业务测试。

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
| RC-73 新事实合同与显示一致 | 用RC49/50/55和RC74/77/80/88的独立字面事实走后续真实序列化/解码/显示，旧WAIT和错误身份作反例 | 普通CANCEL与debug旧结构id正确关联；同根完整计算事件均保留；仅同根同方向旧价格消失加首次DULL/activation时只画新钝化，异方向、dif_return或单独消失不得误藏。事件数组按time允许同时间不同id，唯一性只按id检查，正常FINISHED不显示消失；保留首次反色时间。前端不以当前NONE或相反方向丢事件，不重算条件。 |

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

- RC70：输入拒绝必须发生在修改任何本根进度前；分别从空、DULL、STRUCTURE及已存在首次反色历史的结果开始验证。不能只测空对象“未变化”。再在本根事件/结构已构造后、step发布前故意触发内部校验失败，必须证明整个self进度、根前记录及此前输出未变化，不能只验证输入早拒；按§22.15仅保留不同发布位置的代表样本，不逐字段篡改自产结果来扩展故障矩阵。
- RC71：在RC16/17首次前已破、RC19/20首次仅相等后再严格背离、RC66远处也破之后分别snapshot→restore→追加表中恢复价/D；应分别保持本轮失效、允许合法严格背离、两个均不可回用。另从RC45的t5等号保持状态恢复，追加其t6严格突破根必须CANCEL，不能误判“恢复背离”。快照旧pending/WAIT或lockedAt额外字段、history缺键/含"0"或"2"/使用整数键、缺六字段参照日期、FOLLOWING/DISAPPEARED伪装activeStructure、错形成事件/id/参照/时点均拒绝。合法历史单根/零日/当前收盘已回历史价内侧、更早前缀仍可恢复，不误拦。
- RC71连续/恢复完整结果：保留分割前已取得steps及结构聚合，恢复后追加steps，和从空连续算逐项一致；不要求有界snapshot凭空重建全部旧事件。主动把同id FINISHED/DISAPPEARED改回ASSESSING、改其形成/首次反色时间或原参照必须在聚合层失败。
- RC72：分别以RC55/56首次反色根前后和RC47回转根前后为asOf，早根投影为ASSESSING且无未来终态时间，晚根应按对应时点为FOLLOWING或DISAPPEARED，不能把FOLLOWING当终态。此前已经返回的对象不变；最新缓存不能改变较早calculator_at。RC63两轮结构均保留，不能仅存最后一条。另固定RC55/56的来源修订反例：顶仅把t5收盘103改104，DIF99/H2不变，新结构priceExtreme必须104、旧返回记录仍103；底仅把t5收盘97改96，DIF−99/H−2不变，新极值96、旧仍97。标签及形成/首次反色时间不变，新entry必须从空重建，不受旧终态限制、不混用旧结构记录，旧entry和已返回对象保持不变。再在候选calculator成功step之后故意让结构聚合/完整校验失败，必须丢弃候选entry、缓存仍指旧entry且无半份返回；不得错误要求已丢弃的局部calculator回滚。
- RC73：普通无debug的合法结构事件、debug完整结构及全部关联均有字面样本。历史point.activeStructureId可引用截至查询时已FOLLOWING/DISAPPEARED的record，只要在该point发生时仍考核；不能因record当前已首次反色而拒绝合法历史point。当前活动结构因回转、参照破或首次反色离开考核期后，本根activeStructureId为None，color_flip同根形成首次反色也为None。独立旧结构FINISHED/价格消失不清空另一个仍有效的当前activeStructureId，按RC88/96核对应关系。窗口外形成、窗口内终结仍带记录；反向悬挂/未来日期/错方向/重复形成关联/旧字段拒绝。
- RC73前端仅显示普通事件DULL/STRUCTURE/CANCEL与源DIF；旧RESEARCH_HISTORICAL_WITHDRAWAL作为拒绝反例，新CANCEL/structure_price_break是必须支持的正例；不从计算/响应事件全集删事件；仅按后端displayOnChart选择图表与普通说明，debug仍保留全部关联。debug渲染使用六字段参照原日期及结构终态；普通未提供debug信息时照常展示正常状态/事件/时间，不推断等待。

### 14.14 本轮交付边界

§15—17仅保留修改前成绩。三项核心/内部配套和第2步预测已按§19验收；本批继续P3第3—5步公开查询、接口和前端，按RC01—110/PF01—34的实际归属保留已有证据、补新增路径，不重做内核或专项重放。RC73及RC93的公开HTTP/前端和完整请求验收仍依后续步骤，不自动进入第3步或部署。

### 14.15 旧结构跟踪及同根显示的修订用例（RC74—96，当前内部已限定验收，公开部分按P3第3—5步验收）

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

### 14.16 恢复、聚合、窗口和显示的明确子样本（内核已验收，公开交接按P3第3—5步实施）

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

## 18. 历史设计交接：三项截图修正及文档独立审计（2026-10-31）

### 18.1 已确认要求、代码点和验收对应

本节依据专项回测方案§29及管理员确认，不新增业务规则。本节登记设计冻结时的目标v0.4/v0.6，字段/算法见活动§2—6；实际执行进度及证据以§19为准，不将设计表当测试成绩。

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
4. **继续原P3第3—4步**：对比review通过后，迁完整公开模型、显示标志、query一次编码、API及直接消费者；再TS类型/decoder/adapter/普通详情及纯debug类型/解码、真实辅助renderer及控制组件提取；只把动态装配/ready联动和真实页面留P4。普通/debug同一标志，保留完整事件，不发布混配版本。P3整批验收后才进P4/P5。

上述为当时设计及批准顺序的历史记录，执行结果见§19；当前剩余步骤唯一以§20.2为准。来源、鉴权、环境、1000根、三角画法、debug按需加载、预算、保留工具和清退边界保持。

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

## 19. 三项修补本轮执行计划（2026-10-31）

管理员已授权按§18.2第1—3项顺序实施。硬要求及代码/用例逐项映射继续使用§18.1/§18.3，不另造规则或第二套识别器。每项先完成定向测试和独立代码审计，再进入下一项；发现设计外行为或预算不满足即停止说明。

1. 核心/记录/恢复/内部schema/聚合及asOf：按§2—4及§3.10.1实施，同根最终记录、完整事件及失败不发布必须同时成立；按RC01—110中对应内部用例分组验收，公开显隐RC104留后续HTTP/TS步骤，当前只验完整事实。
2. 单根预测：按§6.4/§6.12同步count路径、当前首次反色价破分类和新Spec，保留原EMA、近优先、有限边界、独立旧条件、取消与400ms预算；按PF01—34对应数学/内部用例验收。
3. 工具及真实对比：仅在前两项通过、实际修补提交已固定后按专项LLD§28适配原worker/records/comparison，保留工作区原有本专项改动、旧56项基准及全部读取保护。执行前人工测试和审计通过，只运行原922根本地同源输入；20秒、1GiB、100MiB含通信/回收/最终输出不变，失败不自动再跑、无部分成功。完整对象仅内存，人工可读报告写回原专项方案/LLD。

本轮不含公开投影/HTTP/TS/页面迁移、清退、生产操作、安装或写业务数据。代码提交权限与执行权限分开；第3项需要固定真实提交，未获得对应提交授权时不得伪造CURRENT或改用工作区源码绕过。当前阶段完成情况及实际测试证据在本节后逐步登记，不引用旧成绩证明新实现。

### 19.1 第一项：核心、恢复及历史查询实施与独立审计

识别实际版本xxm-direction-v0.4-r4，完整MAIN_SPEC hash=db435b39a3d198c126bfff567dfbe66faf74ff9299005578ec6b49bf065fd110。新增字段、单记录推进、首次反色当根比价、单根清起点/计数、首个有效段结束均依§2—4实施；全部真实事件仍保留，同根形成并消失只一份最终记录。原近B后A、双价格门槛、首次资格、1%顺序及来源未改。

内部schema/聚合支持新字段和同根事件次序；历史查询仅calculator_at一次，按真实前缀投影；同时核最新完整记录与末次计算进度，避免未来字段或坏记录被窄窗口掩盖。恢复保留有界两槽、原段被池淘汰仍可跟踪、全程价格极值拒绝曾破后回撤伪造，失败不改原来件/对象/缓存。没有公开HTTP/前端改动。

定向验收：rules/following/following_query/internal_results共1007项通过，8.21秒；snapshot_validation/r4_records/observation/snapshot_consumers的本阶段节点809项通过、两个observe_rows的P4节点未选，3.68秒；calculator当前核心完整函数节点22项通过，0.19秒；根三份架构16项通过，13.82秒。各组少于60秒，无实际行情或数据库/Lake读取。预期按§14字面值，已删除rules测试里自己推演跟踪的expected_ledger循环，用明确RC61/62/63行预期及新增RC97—109逐根事实替代。

独立审计使用CodeGraph explore/sync/status及当前源码/消费者逐项对账：核心只有一份价格推进，原参照优先不变；单根结束仍比价、有效段结束不比；记录/事件不遗漏；asOf因果、终态不复开、空窗口不能隐藏坏记录均有正反例。未发现第一项遗留阻碍，进入第二项。

试跑误选过两个旧observe_rows节点，因现有工作区旧研究入口的导入链引用已移除inactive_result而失败；此问题及P4归属已经在§17.4登记，未进入读取/回放。没有恢复兼容函数、改旧入口、skip或计入通过。最终按既定阶段节点验收；相关原未提交改动保留。

### 19.2 第二项：下一根预测配套实施与独立审计

预测实际身份xxm-key-point-forecast-v0.6-r4，完整FORECAST_SPEC hash=9994790178d64757462643fc37eba9e0945b118e91f1fdb85223db81db2a7b12。forecast_next/forecast_detector、StructureFollowConditionDraft及forecast_text同步新计数；count0/1只用严格价格突破，count>=2保留H方向限制，使真实反色正常结束。旧条件仍复用核心旧结构推进核验，不调用完整普通step，不增加A资格/救援或来源读取。

当前关系真实首次反色当根价破使用STRUCTURE_PRICE_DISAPPEARED，严格区分color_flip形成后消失和已有结构首次反色消失；其形成/消失关联仍完整，不能计入有效关系范围。保持/结构/原参照突破的原谓词及1%运算不变。文本不再说必须等待下一同色段；草稿count与准备副本严格一致且bool不能冒充int。显示规则不删预测的旧价格范围。

三份定向预测测试following_forecast/p3_forecast_math/key_point_forecast共247项通过，2.79秒；涵盖PF13/21—34、M1—M5、四周期、源选项、恰零、合法整数与无整数的窄区间、近处有解不算远处、单根跳过后的恢复、同根双事实、取消/finally及本机四周期数学400ms断言。修订测试预期直接使用§14的手写EMA及条件，未生成新expected去迎合结果。完整接口400ms仍须后续HTTP阶段验收，不用这次数学耗时代替。

独立按§6.4/§6.12及真实调用方审计：原ProjectionState/forecast_math/forecast_expression未改；本次只增加必要有限价格边界和结果分类，未回到中点、逐价扫描、多根推演或近远合并。原输入/准备副本不变、旧终态不预测、真实来源/预算/普通公开四字符串合同未放宽。未发现第二项遗留阻碍，按专项固定提交后才能进入第3项。

### 19.3 第三项：工具适配、唯一一次真实对比与独立审阅

正式核心及预测限定修补固定于50b0f22bb；专项工具CURRENT读取该提交四核心、xxm-direction-v0.4-r4及完整真实Spec。worker固定身份、records新计数/跟踪极值/逐日关联及派生显示报告已适配；父编排、旧56项基准和本地来源读取保持。三份专项287项、lake人工43项通过，共330；架构16项通过。CodeGraph核研究调用影响，正式四核心相对固定提交无差异，旧基准/归一等4函数AST与原提交一致。

只运行一次922根2023-01-03—2026-10-27本地DG Silver上证日线，SSE日历1394/922，3组各922次step，旧56/56通过。完整调用2.794937秒，保守父子峰350126080字节，全部结果18491201字节，全部进程回收，预算未放宽。当前DULL29/STRUCTURE16/CANCEL21，显示CANCEL19；相对历史r2、历史r4完整事件差11日、应显示标签均差9日，普通状态差2日。9次价格消失、2次同根计算双事件/显示单标签及10月17日单根跳过均只读同次结果独立审阅，无二次step或读取。

完整人工可读报告、全部差异日期、各组参照/DIF日期、数量/资源及限制见[专项方案§32](../../../../docs/product/wealth-r4-historical-comparison-plan-v1.md)，工具验收见[专项LLD§29—30](../../../../docs/product/wealth-r4-historical-comparison-low-level-design-v1.md)。工程及日期/标签对齐不代表已逐值复现原软件。该次专项不包含公开投影/必要前端/P3整链400ms或P5；随后P3的实现及限定验收见§20.7—20.8，P4真实来源与P5仍未执行。

## 20. 已验收范围、P3交付证据及后续依赖（2026-10-31）

### 20.1 已验收范围及固定证据

管理员已明确确认本轮验收通过。识别核心、记录/恢复、历史查询、下一根预测配套和工具适配/唯一一次922根真实对比据此收尾；内部代码提交50b0f22bb，工具/测试/报告提交ec37c69ea。§19与[专项方案§32—33](../../../../docs/product/wealth-r4-historical-comparison-plan-v1.md)保留实际证据，不重新查询、回放或改写成绩。

§19的内部及专项验收不等于整个产品验收：公开模型/API、TS、普通/debug投影和完整请求截止检查现已由§20.7补齐；本地四周期真实来源、页面与P5清退仍未被这些成绩覆盖。不能用922根日线重放代替这些验收，也不重新打开已经确认的三项规则。P1/P2既有正确基础不重复开发；其旧WAIT/多步响应夹具按§10.4.1迁为独立新正例或明确拒旧材料，不以“已验收基础”为由保留旧字段成功路径。

### 20.2 P3第3—5步实施范围（已完成开发与限定验收，见§20.7）

本节登记P3已完成范围及当时的实施顺序：A1复核→A2内部/公开模型与纯投影→查询/单日历端点/缓存候选→API及直接Python消费者→后端定向验收→A3纯资格/类型/两个debug解码器→正常adapter/client→Hook→页面与两工作区/右栏参数→真实renderer/研究控制组件和静态依赖拆分→前端全部本批测试/typecheck/build→A4整批独立审计。实际代码及证据见§20.7—20.8；不重新开工或发布前后端混合版本。当前P4执行顺序唯一见§21。

| 顺序 | 工作内容及真实代码位置 | 必须交付及验收 |
|---|---|---|
| A1 开工核对 | §11.3、三份既定合同和§11.2.6调用方；固定MAIN_SPEC/FORECAST_SPEC真实身份，列清文件、硬口径及独立测试映射 | 当时发现的旧查询/API/TS返回方式已在A2/A3迁完；P4不得恢复旧函数或旧DTO兜底 |
| A2 P3第3步：Python模型、投影、查询/API | §5完整内部/普通/debug模型，response_projection.py；query_service.py和forecast_query_service.py；三个识别/预测API；缓存和forecastId；§11.2.6所有本批直接Python消费者 | 同一次来源结果复用，不重新读或重算识别；统一新结构/单根预测合同，日历只求下一端点；完整关联先校验，再按模式投影并只编码一次。两种模式公共标签/编号/预测文字相同；同根显隐由后端displayOnChart给出，完整计算事件不删；拒旧/混配身份，历史asOf不泄未来 |
| A3 P3第4步：前端必要迁移 | §8和§11.4：TS类型、纯debug decoder、普通decoder/adapter、两个apiClient、两个Hook，再普通悬停及日/分钟工作区必要调用 | 按{response,deadline}传递同一截止时间，迟到/关闭/重试不残留；普通没有debug字段也可展示，不静态加载辅助实现。严格使用后端displayOnChart；纯debug解码和真实renderer保留完整事件；P3完成控制组件提取和普通静态依赖拆分，P4才动态挂载。完成定向/完整Wealth测试、typecheck和build，不自行重算规则 |
| A4 P3第5步：整批独立审计与交付 | 依§12和§14对规则/分支/内部和公开合同、API、全部本批消费者、一次读取/一次编码、缓存/asOf/取消和架构逐项对账 | 已有定向成绩只复用其适用部分，补新公开与前端证据；按原口径验识别4秒、预测400ms及1MiB/32KiB响应上限，最终校验/编码不得漏算。明确P4真实来源/页面和P5尚未覆盖。交管理员验收后才进入下一批 |

本批不重新设计取价、选峰、1%或近远规则，不恢复两位/多步/中点预测，不读远程或重跑922根专项，不提前清退旧执行器、不改生产开放范围、不部署。普通/debug新模型必须同时迁移全部本批消费者，不增加过渡开关或旧模型兼容层。公开接口失败、取消、错误和精度未决语义均沿§1/§5—6，不能吞成EMPTY。

### 20.3 P4产品装配、保留工具与真实页面

仅在P3整批验收后按§11.4的原6步实施，顺序不变：

1. 本地/生产同时装配。沿既有显式dev/local策略；本地日线不以分钟Lake可用为前提；生产的日线/分钟r4、预判及核对路由均关闭，debug不能绕过；正常生产日线不受影响。
2. 复用P3既有enabled资格及全部props，只接effectiveDebug随真实模块变化和动态生命周期。普通不下载辅助模块；URL debug=1才加载辅助信息，关闭/切换/离开及迟到请求正确清理，辅助加载失败仍保留普通能力与错误提示。
3. 动态挂载P3已真实提取的辅助详情和手动波段核对图，不重新实现组件或图表交接。保持1000根、四种三角、留白、独立研究日期/九转/趋势；进入debug不自动运行三年核对。
4. 保留核验工具在首次使用前按§10—11整体迁移到新bytes/普通-debug/原截止时间和纯内存结果，先补正确反例及finally清理；不运行旧工具再修它。
5. 按已有授权和明确的有界周期/日期做真实只读验收。复用既有隔离App、原路由/鉴权，不重启共享服务。日线和实际可用60/90/120分别登记来源、完成根、连续性、普通/debug字节与冷/热耗时；K线按原20次P95口径验，不拿922日线代替分钟，也不增加全局数据读取。
6. 页面与独立验收。自动检查原1600/1440/1280宽度、45/180根、拖过301根等场景；页面由管理员review，独立审计后交付，验收通过再进入P5。缺数据/周期如实登记，预算失败先停，不放宽限额。

P4不修改识别规则，不清退P5文件，不新增下载、后台任务、结果/恢复文件、浏览器持久缓存或用户算法开关。

### 20.4 最后批次：P5旧实现清退与总交付

1. 先按§10/§22完成当前引用、代码/测试及reports逐文件审计，明确有用能力落点、资料收敛、测试和失败交接，补齐原方案/LLD供review。本轮只完成这一准备，不迁移或删除。
2. 获准开发后先迁出有用工具/人工输入/数学及资料和消费者，验证交接后再依附件清退旧r2/研究识别副本/比较运行器/专属测试/源码包与无用中间报告；只清对应生成缓存。有效原图/讲稿/输入/结论收敛保留，独立两位算术不接识别。
3. 在旧模块确实缺席的情况下做引用清零、r4及保留工具回归、API/前端/架构和必要本地核验，证明没有动态回退、别名或磁盘源码副本依赖。
4. 完成文档索引、运行命令、唯一版本及保留/清退逐项对账，给出全部测试和未覆盖限制，交管理员做最终验收。提交、推送、部署仍按各自明确指令。

### 20.5 执行节奏与本轮停点

P3开发及修复已提交，P4整批实施、独立审计及管理员页面验收现已完成，证据见§21.14.14。后续依次为P5当前引用/能力迁出审计与原LLD逐项对账→按获准范围迁移→清退旧执行代码→删后回归→文档和最终验收；详细四步计划见产品§11。每批内的步骤是依赖顺序，不允许跳过或把未完成的上游留给后续自由发挥；每批开工前按对应原方案/LLD复核，不重复造方案。遇到未定义行为、文档冲突或真实预算无法满足时，先停下说明上下文和建议。

P3第3—5步及提交后修复已完成，证据见§20.7—20.8；P4已验收收尾。P4最终对账已完成；本轮完成P5当前代码/资料/测试审计和原方案/LLD补齐，不开始P5编码、迁移或删除，不运行业务测试、读取行情或自动提交。§10/§11.2仍为清退设计依据，须在P5开工前逐项复核当前实现；其中已在P4完成的迁移不重复实施，不能把旧设计时的缺口当成当前仍缺失。


### 20.6 P3开工前文档补齐与独立审计记录

本次只补文档，不改业务/测试代码，不读取行情、重放对比、运行HTTP或提交。四项已批准的补齐位置及后续验收如下；不另开一套实施路线，编码顺序唯一沿§20.2。

| 已补齐事项 | 唯一细节位置 | 编码后必须证明 |
|---|---|---|
| 当前身份及已验收范围 | §0.2、§6.9—6.12、§11、§14及§19—20；产品§2/7、技术方案§1/5/10同步 | 复用v0.4/v0.6和已验收内核；公开查询/API/TS及完整预算单独验，不能以旧成绩代替，也不重放专项 |
| P3真实资格和全部必要参数 | §8.3.0—8.3.1/8.3.4、§11.4 | 本地上证普通模式按真实资格传debug=0，生产/其他标的无请求、卡片或图层；P4只扩展真实模块ready模式 |
| P3真实辅助组件及测试 | §8.2—8.4/8.8、§11.4 | 两个真实renderer、研究控制组件及五项导出独立通过；原研究行为测试迁移保留，不用假组件、skip或删断言换通过 |
| P3普通路径去除辅助静态依赖 | §8.3.0/8.3.3、§8.6/8.8 | Page/两工作区没有辅助运行时依赖；扩展含整组图表数据、日期、图层和重试，回调稳定且清理不污染新owner；P4加载同一已有模块，不重写交接 |

配套后端先后关系已明确：必填编号和显示内容先生成，随后完整内部校验、公开投影及一次编码；退出共享读取并通过其出口检查之后，才可在同一截止时间内发布预测缓存，发布后只返回已准备正文。失败不得删除旧有效内容。单个下一端点、同次日历身份、静态/校准失败/实际求解结果及对应PF28完整请求反例均见§6.8.1—6.10。三个成功响应显式no-store，原错误处理和路由参数规范化边界保持，配套三合同已同步。

该次独立复核覆盖后端顺序/预算、前端P3到P4交接、三合同及原方案一致性；当时的开发已按§20.2完成，实际证据见§20.7—20.8。历史§15—18只留当时真实成绩和设计交接；当前优化第4—7批暂缓，正式P4剩余按§21.14推进，不以完成这些TODO为前置。

本轮文档完整性检查、git diff --check均通过，六份文档相关章节18处本地链接均存在。后端、前端和接口合同三项独立复核已完成；该检查不替代后续业务测试。

该次P3开工前结论已由§20.7—20.8的开发和限定验收承接，不再作为当前开工指令。§3.9两项研究TODO继续保持现行规则，不作为P4前置；P4第1—4步已完成定向工程验证，第5步先前在60分钟超时停止的记录保留于§21.13.4，后续读取优化及正式续验已完成，当前证据见§21.14.13；页面验收和P5清退尚未执行。

### 20.7 P3第3—5步执行登记（2026-10-31）

管理员已授权本批编码，依据文档提交9dfa29da3。按§20.2依次推进：先schema/response_projection、query/cache/calendar及三个API和直接消费者，再TS合同/解码/client/Hook/资格及必要页面参数、真实辅助组件提取和静态拆分，最后独立审计。硬口径分别以§5普通/debug精确字段、§6.8编号/缓存发布/原截止时间、§8.3组件及props、§8.8原测试迁移、§12分层验收为准；每项配正例及拒旧、超时、取消、迟到、错误关联反例。现有工作区修改按开工清单保留，已有数值安全检查迁入新合同，不能为迁移删除正确检查。失败不发布半份结果、不落盘、不自动重试。预算不放宽，不重跑专项，不进入P4/P5，不自动提交或部署。本批已完成开发、限定工程验收与独立审计，以下登记实际证据及尚未执行范围。

#### 本批实现与逐项对账

| 硬口径 | 实际代码 | 本批证据 |
|---|---|---|
| 唯一v0.4/v0.6、识别与EMA规则不改 | 原calculator/spec/snapshot_validation/projection、forecast/forecast_next/forecast_detector/forecast_spec无本批改动 | 对这些路径核Git差异为空；`test_xxm_r4_rules.py`、`test_xxm_r4_following.py`、`test_xxm_r4_following_forecast.py`、`test_xxm_p3_forecast_math.py`独立字面回归1093项通过，8.06秒 |
| 内部完整校验后显式公开投影，不泄辅助字段、不删计算事件 | `schemas/wealth/market/index_detail_xxm*.py`、新增`services/.../response_projection.py`；同根同方向旧价格消失仅在新activation存在时False | 新API与内部/asOf/恢复消费者回归156项通过，4.16秒；普通/debug公共字段相同；RC77/93/104/107窗口、历史关联、未来字段、拒旧/混配及错误引用反例 |
| 三API参数及一次编码成功bytes | 三个index_detail_xxm/分钟/forecast API、两个query | 日线/分钟临时真实reader及HTTP成功no-store；非法debug/重复参数在来源前拒绝；测试捕获model_dump_json正文与HTTP正文逐字节相同、每请求仅一次；原鉴权、错误映射不变 |
| 下一端点、缓存身份/退出顺序及原400ms | `forecast_query_service.py:future_calendar/_assemble/build`、`query_service.py:XxmCache` | 四周期只交付下一端点；未使用日历尾部变化不改身份；同源normal/debug缓存命中不再求解；坏缓存完整模型拒绝；with退出失败、编码/深复制超时及发布前取消不发布，原缓存不变；成功正常变化可发布 |
| 普通解码和辅助解码分开，截止不重置 | `xxm`和`xxm-forecast`类型/adapter/client/Hook；`debug/xxmDebugContract.ts`及`forecastDebugContract.ts` | 原值、严格字段/空值、六字段参照、统一结构生命周期/首次反色形成、同根完整事件和显隐；请求4990ms返回后在4999ms完成可用、5001ms解码完成拒绝；Hook最终截止、生产/disabled、模式/序号/标的和取消反例 |
| 普通路径没有研究实现静态依赖，真实组件已提取 | `model/indexRecognitionAvailability.ts`、Page、两工作区、侧栏；`debug/IndexRecognitionDebug.tsx`五项导出和两个真实renderer | P3普通页面固定传实际资格和debug=0；研究原行为移至真实控制组件测试，未删断言/skip/假控制器。手动开启、K线核对失败、普通/研究日期及右栏隔离、1000根、失败独立重试、迟到和关闭、异步趋势不替换primitive/图层数组均通过 |
| 说明正常可用，辅助不混入普通详情 | `XxmLayerUi`、`XxmForecastCard`、两真实debug renderer、NineTurnLayerStatus | 普通只显示状态/应显示事件/时间及后端预测文字；debug完整参照/关联、无事件旧结构、未决区及公式可查看；普通九转不显示匹配统计，真实错误与重试不隐藏；其他消费者默认行为保留 |

P1/P2中与本批直接合同冲突的web/Wealth等待、多步和旧身份正例已按§10.4.1迁移为独立当前样本或拒旧反例；`xxm/rearmContract.ts`在运行引用清零后删除，因为它只解析已移除的等待字段。此删除属于本批合同迁移；未借此推进P5旧算法/执行器清退。P4保留工具、P5旧runner及其专属历史材料测试未执行，仍按原归属迁移或清退，不声称它们已通过。

#### 完整链路、构建与审计结论

- 隔离接入：临时SQLite和临时Parquet采用真实reader、原路由与现鉴权/异常处理器；不访问正式DB、Lake或网络。另用独立EMA算术生成的290根人工日线，实际走来源读取、识别进度恢复、250根校准、下一端点、真实求解、完整模型、公开投影及编码。一次本机记录冷请求58.50ms、缓存命中5.22ms、debug正文8926bytes，均含最后校验/编码，未放宽400ms及32KiB。该人工日线成绩不证明真实四周期性能，也未开展20次真实采样。
- Wealth完整回归：182个文件、1392项通过，26.15秒；随后新增普通入口无辅助运行时导入检查1项通过；typecheck及生产build通过。构建仍有已有的大包体积提示，未改配置或扩大本批。一次前轮全量运行中非本需求PriceVolumeWorkspace测试出现异步请求数量波动；原测试单独15项通过，最终全量也通过，未改该测试或代码凑通过。
- 架构：根规则三份测试16项通过，12.98秒；未引入Biz对研究/App/QTF依赖。开工已用CodeGraph核入口、调用链及消费者；完成后`codegraph sync`/`codegraph status`显示索引最新，并补看query→模型/投影→API、TS client→Hook→工作区/侧栏、研究控制器→扩展交接的当前源码。
- 独立代码复核：重新核对完整字段生成先于完整校验、显示标志不改计算事件、原截止传递、单来源和单下一端点、with退出检查先于预测缓存发布、失败无半份成功、研究日期不污染普通日期、辅助无事件记录关联及普通静态依赖。测试发现的研究趋势图层重建及首次反色形成记录的解码问题已修复，保留对应回归。后续提交bebe6f403后的独立审计已复现完整预测检查及退出后错误映射两类遗漏；本段初轮审计不能作为全部符合LLD的依据，修复见§20.8。
- 文档：产品、技术方案及本文状态已对齐；本批三文档链接和改动差异单独核对。全库`check_docs_integrity.py`有两条与本需求无关的失效链接，分别在行业景气度方法/研究方案中引用缺失的`reports/a_share_industry_prosperity_2026q3_coverage_20261031/scope-2024-and-workload.md`；未擅自改动这些文档，不能把全库检查写成通过。

**本节初轮交付后的独立审计未通过；两类问题现已由§20.8修复及复审，最新结论见该节。**没有提交、部署、重启服务、安装依赖、重放实际行情或保存业务结果。P4的App显式本地/生产注册、动态debug模块ready/挂载、保留工具、四周期真实来源/预算及浏览器review均尚未执行；P5清退也未执行，不能据此宣称产品已经可发布或生产门禁已完整生效。

提交交接：管理员已批准提交本批P3第3—5步改动。只提交本批明确文件及必要的同文件代码改动，其他工作区修改保留；不推送、部署或推进P4/P5。随后按当前方案和LLD对这次提交重新独立审计，审计结论另行汇报。本次提交前重新执行全库文档完整性检查，已全部通过，上一轮两处无关失效链接已不再出现；上文保留其当时真实检查结果。

### 20.8 P3提交后两类遗漏的修复（2026-10-31）

管理员已授权先补LLD缺失再修复及复审。依据bebe6f403及其独立审计：严格类型/统一波段及通用失败映射原原则已明确，本轮补实§5.1解析前检查、§6.8完整退出错误分类及§6.8.1唯一编号生成/核验和数值表示。目标只修结果安全检查与失败返回；不改核心calculator/spec/snapshot_validation、单根预测规则、EMA、取价/选峰、预算、来源SQL/范围、鉴权或HTTP字段。无新配置、持久化、网络、实际行情重放、安装或服务重启。不进入P4/P5，不自动提交/部署。

编码顺序：①一处原生/公开Wave事实检查、barsAhead输入检查；②纯编号函数及query/schema双方调用、前端只验编号格式；③forecast外层及共享load_entry错误/取消原样处理；④逐项反例与正例、完整接口/缓存验收；⑤独立复核同类遗漏并回写实际结果。每一步直接沿本节编码，不恢复旧字段、旧编号分支或第二识别实现。新helper不增加schema对query的反向依赖。

| 编号 | 独立输入与错误反例 | 必须结果及对应代码 |
|---|---|---|
| F01 | 合法单根目标1/None；True、False、1.0、字符串1、0/2 | schema在解析前拒非法类型，合法1和合法空目标通过；HTTP/缓存完整结果同检查 |
| F02 | 既有手写旧结构originWave，合法1根；0/负数/bool/小数，错误sign、非正价格、非有限DIF及极值日期落段外、起止倒置 | 内部和debug都在公共输出前拒错；普通/debug一致，合法1根不得被误拦，也不改历史至少1根口径 |
| F03 | 独立字面身份事实/规范JSON及预先可核对SHA；整数/float同数值、±0、中文、dict键顺序变化 | 单一helper稳定编号，合法数据重验不误拒；时间、真实价格/参照/源身份变化改号，debug/文字/显示整数变化不改号 |
| F04 | 实际M1完整结果；改结果id、条件id为错误字符串或另一64位hash，改事实而不改id；旧结构relatedStructureId改而不改其条件id | 完整内部及debug模型均拒绝；坏缓存不重新求解、不静默改号、不发布候选，原成员/内容不变；正常缓存命中保持编号和公共文字 |
| F05 | 单独普通响应因无完整辅助事实，仅错误格式id（含64位之后多一个换行）；前端同样错误格式/True目标 | 仅做格式/类型检查，不由普通端或前端推算hash；普通合法DTO仍可用 |
| F06 | 退出前、退出时、退出后发布RuntimeError；HTTP实际异常处理器 | 一般失败500/XXMF_QUERY_FAILED及中文，不泄内部异常文本；已知XxmQueryError原code/status；失败后旧缓存内容/成员保持，正常发布仍成功 |
| F07 | TimeoutError、两种CancelledError，以及错误发生同时已过时限 | 超时按503；取消原样传递，旧缓存不改且锁/请求资源释放；原来源/查询错误不被错误处理的新时间检查覆盖；成功超时仍须被正常出口/最终检查拒绝 |
| F08 | 原M1/旧结构条件、四周期/asOf、真假空结果、一次编码、正常/debug共用缓存 | 原有正例保持；完整预测400ms/32KiB、识别4秒及原缓存总量保持。额外核验人工290根冷/热链路，不能拿其替代P4真实数据 |

测试落点：新增tests/web/test_wealth_index_detail_xxm_forecast_validation.py存字面模型和编号反例；现test_wealth_index_detail_xxm_forecast_api.py补真实query/HTTP、缓存及取消/错误优先级；test_xxm_shared_loads.py或现源fixture补load_entry释放；Wealth现forecast合同测试补编号格式，定向测试、typecheck/build和根三份架构检查。输入expected不能由新helper生成；独立字面JSON与标准SHA可作依据。每组限60秒，现环境执行，不安装。失败仅丢弃本次内存副本，重新调用从头读取/计算，不能自动重试或保存恢复文件。代码完成后独立重看所有直接消费者、已校验缓存及普通/debug路径，记录未覆盖边界后停止。

#### 20.8.1 修复完成及独立复审

已按本节顺序完成，未改变核心/Spec/EMA/求价规则，原预算不变；只修改本轮明确的13个文件；管理员已授权提交，本轮仅提交这些文件，未部署，保留其他工作区修改。

| 已定要求 | 实际落点与验证 |
|---|---|
| F01解析前严格整数 | ForecastResponseDto.original_bar_count；True/False/1.0/字符串/0/2拒绝，合法1及原空目标正例通过。不再依赖Literal转换后的无效类型检查 |
| F02原生与公开Wave同一检查 | index_detail_xxm.py:_validate_wave_facts同时被两个Wave模型调用；正根数、方向、正有限价格/DIF及段内发生时间一致。测试以匹配编号的非法Wave证明拒绝源于事实错误，合法单根、顶底及四周期保持 |
| F03—F05编号事实一致 | 新forecast_identity.py纯函数；query生成、完整内部/公开debug复核共用；标准库SHA对独立字面JSON验证、101与101.0/±0/键顺序/中文、真实事实变化及显示内容不入号。篡改64位有效外形的编号、关系或原事实均拒绝。普通与TS只核恰64位小写十六进制，不在前端生成编号；尾随换行反例也拒绝 |
| F04坏缓存不兜底 | 已有预测API测试扩展为非有限数、错误结果id和错误条件id；命中后重验拒绝，不调用求解、不静默改号；model_copy不是校验。此保障继续保留，耗时优化第1批的具体检查位置及原嵌套对象测试迁移见§0.4 |
| F06一般失败的接口一致性 | forecast_query_service外层包含退出后通用Exception到XXM_QUERY_FAILED；真实API及异常处理器验证内部/退出/发布500/XXMF_QUERY_FAILED和中文，不泄故障注入文本；实际缓存候选copy失败后，旧字典对象/条目保持，另一线程能重新拿锁 |
| F07取消、错误优先级与释放 | 预测和load_entry原样传播两种CancelledError；一般错误处理不重新调用remaining。已过预算同时出现真实错误时保留其原因；正常超限仍拒绝。实际锁内取消后原缓存不变、锁释放、下一次正常发布成功；源共享加载无残留且后续正常请求可用 |
| F08旧行为/资源边界 | 原字面业务、恢复/asOf、HTTP单次编码、普通/debug缓存、静态/校准失败、目标下一端点及前端请求/组件回归保留；不重复跑实际行情对比 |

最新验证（参数展开后的测试项数，分组均少于60秒）：

- 后端公开API/模型/共享加载、内部/asOf/恢复消费者：210项通过，6.78秒。其中新增编号/模型文件38项及接口故障/取消扩展，与原suite共同验证本轮反例及正常变化；不使用旧算法输出作预期。
- 核心规则及单根数学回归：1093项通过，10.69秒。核心calculator/spec/snapshot_validation/projection/forecast/forecast_next/forecast_detector/forecast_spec的Git差异为空。模型层Wave事实检查修复不改变合法识别状态。
- Wealth全量：183文件1394项通过，14.77秒；typecheck和生产build通过。只有编号格式解码及测试变更，没有页面布局、路由、数据加载或动态装配变更，未新增浏览器验收。
- 根三份架构检查：16项通过，13.45秒。新身份函数只依赖标准库；未新增Biz对query上层、研究/App/QTF依赖。CodeGraph开工核上下游，完成后sync/status显示最新，并按源码复核直接消费者和缓存发布流程。
- 隔离临时来源的人工290根完整请求：冷66.52ms、热5.75ms、debug正文8926bytes；包含真实reader、校准、求解、模型/身份复核和编码。仍在原400ms/32KiB内，不代表P4真实四周期性能已验收。

独立复审重新核对：完整模型校验先于普通/debug分流；原生与公开Wave合法性相同；编号生成与复核字段/数值规范同源；缓存命中不重算/改号；with正常退出及最终check后才发布；所有错误路径保留旧缓存，取消/锁释放正确；错误处理不掩盖原因；前端不生成编号。本次复审另补齐编号尾随换行检查，未发现本修复范围内其他未处理阻碍。P3可重新交管理员review；P4环境/动态模块/真实来源/浏览器及P5清退仍未执行，不能视为产品可发布。


## 21. P4整体编码设计、执行顺序与验收

本节把§11.4六步落实到编码及验收。产品§10和技术方案§15为原范围依据；引用§1/§8/§9/§11.2已定合同，不另设算法或配置。第1—4步已完成，§21.1—5保留其实现要求和工具合同，不是重复开工清单。第5步已完成三分钟正式清单并复用适用日线证据，实际结果见§21.14.13；第6步仍待管理员页面review，不部署、不进入P5。

### 21.1 编码起点、硬边界及文件清单

代码起点为P3提交bebe6f403及审计修复11271531c。现唯一识别v0.4-r4/预判v0.6-r4及真实Spec hash保持。F01—F08修复必须继续生效：原始类型严格校验、原生/公开Wave一致、完整预测编号复核、取消原样传递、异常退出不覆盖原错误、不发布半份缓存。

本次已用CodeGraph codegraph_explore核对Page→工作区→useIndexXxmLayer、Page→useXxmForecast→client、query.load_entry→_load_series→read_minutes→read_complete_history_pair，以及本地分钟配置；直接补核App路由、Settings、辅助组件、工具和测试。CodeGraph查到的无关同名符号不作证据。第1—4步的当时依据与实际交付见技术方案§15.1及本文§21.10；图表转换函数已经迁至indexChartPointAdapter，不能再列作待迁移。下表保留原已实现职责，当前未来代码范围只按§21.14.1的两文件白名单。

| 原步骤（1—4已完成） | 已实现位置/原登记范围 | 固定职责 |
|---|---|---|
| 1 | src/app/api/v1/router.py | §1两私有装配函数、Settings/root交接、移除旧注册及两处旧root函数 |
| 2 | wealth/src/features/index-detail/debug/useIndexDebugModule.ts（新增）；pages/index-detail/IndexDetailPage.tsx | 模块加载及页面编排；沿现纯资格函数，不重写资格或解码器 |
| 2—3 | pages/index-detail/index-detail-page.css | 只给稳定左图容器/辅助加载错误状态定位置，不改右栏/原三角/图表尺寸规则 |
| 3 | features/index-detail/chart/indexChartPointAdapter.ts（新增）、IndexChartWorkspace.tsx、debug/IndexRecognitionDebug.tsx | 原样迁toDetailChartPoint并清零旧导入/导出；现真实工作区/控制器挂载，最小必要接线 |
| 3 | chart/IndexMinuteChartWorkspace.tsx、sidebar/IndexInfoRail.tsx/IndexTechnicalTab.tsx、xxm-forecast/XxmForecastCard.tsx | 现props已具备，原则上不需再改；只核既有参数完整传递，不能重做合同或增加字段 |
| 4 | scripts/research/index_market/xxm/daily_window_precheck.py、xxm_page_request_audit.py/.mjs、xxm_forecast_display_audit.py及主题README | §11.2.3—4成套迁移；原路径保留，不新增替代运行器 |
| 5—6 | 原产品/技术方案/本LLD及耗时优化专项四份文档 | 当前安排见§21.14，实际执行后只登记有界摘要，无行情/完整结果/恢复文件 |

测试文件另见§21.8。禁止改calculator、snapshot_validation、Spec、forecast求界/EMA、实际源SQL/Reader、数据库结构、已有共享配置默认值、鉴权及P5专属清退文件；本表明确安排P4迁移的工具和旧函数删除按§11.2实施，不扩大为P5模块清退。若实际编码必须超此清单，先说明具体代码证据并修原文档，不借“配套”自行扩大。不新增依赖、分支/worktree、后台任务、生产开关或另一份r4。应用内展示不使用工具统计拼装识别事实。

### 21.2 第1步：正式App与隔离工具共用环境装配

按§1实现_xxm_local_environment_enabled(settings)、_include_local_xxm_routers(target_router, settings)，不复制为第二处判断。正式router在现聚合层取得get_settings()的最终对象并调用后者；函数只有路由/依赖接线，无业务计算。

固定顺序：

1. 先判断app_env是否显式设置且规范后为dev/local；false立即return，不调用分钟capability、不构造Biz service、不读取会话或Lake。
2. true时日线识别、预测、daily-waves可注册；resolve_index_minute_capability只对传入的同一Settings解析一次，捕获可用lake_root或None供分钟相关闭包使用。该闭包不再调用get_settings。
3. 将xxm-signals、xxm-key-point-forecast、daily-waves的原无条件include移到此函数；minute-xxm-signals只在同次capability可用时include。从原_include_local_minute_router移除minute-xxm重复include，其余普通分钟/九转策略不改。四路径实际URL仍为/api/v1/wealth/market/index-detail/对应后缀，各只注册一次。
4. 删除旧_index_xxm_lake_root、_forecast_lake_root前查实际调用，全部迁到同次捕获闭包后删除；不得留下再取全局配置的旧入口。
5. 日线识别/预测不调用lake_dependency获取分钟root。分钟未启用或来源未就绪时，日线仍正常；分钟预测沿现XXMF_NOT_SUPPORTED/404，分钟识别未注册。明确开启却根非法/依赖不具备时保留现LocalMinuteCapabilityError，不吞错伪装可用。
6. 正式路由保留原get_db_session、require_quote_access、WebAppError及daily_wave_session_factory。辅助参数不承担环境权限；生产/缺环境/未知值直接路径404，OpenAPI无对应项，不返回假EMPTY或回退r2。

配置仍为§1.2已登记来源。测试APP_ENV显式dev/local、含空白大小写、缺失/空串/未知/prod，以及现env文件优先于同名进程变量；不改变全局默认dev或优先级。配置改变按原App启动时生效，实施不自动重启共享服务。既有web测试APP_ENV=test不能为方便全局改成dev；新增隔离App只为本用例传明确Settings，测试后恢复。

第1步结束交付：装配真实路由的正反例通过，普通生产日线仍可访问；工具可在后续复用同函数。单独build_router测试只能证明Biz合同，不能代替生产不注册的验收。

### 21.3 第2步：动态模块与页面请求模式

useIndexDebugModule(enabled)固定返回phase（idle/loading/ready/error）、module（ready时五项真实导出，否则null）、errorMessage、稳定retry。仅动态import('./IndexRecognitionDebug')，禁止静态运行时import、全局预加载或从普通桶文件再导出辅助实现。返回模块类型用现debug/types.ts，不改五项导出或伪造decoder。

- false：对外同步呈现idle/null，无import和错误DOM；清理使当前加载序号失效。
- true及一次有效加载尝试：loading/null/error清空；effect捕获本次序号及已清理标志。then/catch均先检查未清理、enabled仍有效及同序号，再提交ready或error。ready不是依赖module存在的猜测状态。
- retry只在enabled且error时开始新尝试；清旧模块、使旧序号失效，不自动重试，不触发daily-waves。卸载/关闭后失败也不得弹出旧错误。
- effect清理不虚称取消import网络；旧Promise即使成功也不重新挂载。开发StrictMode的setup→cleanup→setup必须无残留监听/结果，重复的语言级import可由模块缓存处理，不人为改变React规则。无浏览器持久缓存。
- 官方异步清理依据：React useEffect文档 https://react.dev/reference/react/useEffect 及 https://react.dev/learn/synchronizing-with-effects；已用Context7核对迟到结果的清理原则，具体仍按本模块序号/owner实现。

IndexDetailPage在所有loading/error/empty早返回之前始终调用加载Hook。复用resolveIndexRecognitionAvailability，调用useIndexDebugModule(debugEnabled)。只定义一次effectiveDebug = debugEnabled && phase为ready ? 1 : 0，及可空readyModule；工作区、forecast、renderer必须用这一份值。

| URL/模块 | 请求及显示 | 禁止 |
|---|---|---|
| 无debug、其他标的、生产 | 普通有效本地上证请求0；其他/生产enabled=false；无辅助模块/DOM | 不能因URL带1绕过标的/环境 |
| 本地上证debug，loading/error | r4正式识别/预判仍0；只有辅助加载状态/重试 | 不因无decoder停普通功能，不先请求1 |
| 同上且ready | 新请求1，传同模块decoder/renderer；旧0结果不能填新1身份 | 不另跑第二套计算或另造请求通道 |
| 去掉debug/模块重试 | 当次渲染立即0，renderer及扩展无效；Hook取消旧1、清辅助 | 不从旧1对象删字段充当0缓存 |
| 合法1请求但响应合同坏 | 本次识别/预判报错，K线保留 | 不偷偷当普通成功 |

识别工作区传现IndexRecognitionProps；forecast传现enabled/debug/decodeDebug；右栏经现renderDebugDetails链透传renderForecastDetails。预判active仍为recognitionEnabled && technical页签 && hasData；minutes仍取现本地分钟能力。卡片保持原四行、刷新60秒、历史不刷新、只重试选中行和页面scheduler优先级，不能把主图activePeriod当预判行筛选器。生产/其他标的关闭整项；本地上证主图切到m5/m15/m30等非识别周期时，仅停止该图识别，技术面四行仍按各自资格请求；debug模块仍可为这些合法预判行提供依据，不得按P4-10误关。

模块加载状态放在左图区域，不塞右栏或裁剪的指标标签内：Page在有行情时使用始终存在的index-detail-chart-region容器包住原日/分钟工作区；在普通行情已加载时保持容器和工作区的位置，不人为用debug给组件追加key；URL debug切换仍沿普通加载器进入loading并卸载图表，加载后重建，不为保留原图另存旧行情。容器min-width/min-height为0、position:relative、占原单一网格列。仅debug loading/error在其右下、底部指标栏上方显示index-debug-module-status（absolute，right:12px，bottom:42px，宽度受左图区限制，中文可换行）；文案“核验工具加载中”或“核验工具加载失败 · 重试”，按钮type=button、键盘可达。ready或无debug无此DOM，不占高度、不挤右栏；已有行情/识别错误提示仍各自显示。该状态只是原已定失败反馈，不增加调试开关。

### 21.4 第3步：复用辅助组件并完成图表交接

先将IndexChartWorkspace.tsx内toDetailChartPoint原样迁入chart/indexChartPointAdapter.ts。新文件只用类型导入，无React/组件/图层运行时依赖。工作区和IndexRecognitionDebug直接import该纯函数；仓库查所有直接消费者同次迁移，不保留旧导出/转发。所有字段、overlays、null及原数字不改，以独立字面IndexCandlePoint对输出关键字段和原对象不变作断言。

随后接现模块：

1. ownerKey恰按现约定由normalizedTsCode、activePeriod、普通viewModel.asOfTradeDate组成；无普通可用行情不挂控制组件。ready组件作为工作区兄弟控制器，使用现IndexRecognitionDebugProps，不能用debug条件替换整棵普通工作区。
2. Page用稳定useCallback接onChange。接收及渲染两处都要求当前debug ready且owner一致；旧owner的extension/null不得覆盖新owner。退出、切周期/标的/普通日期或离开立即停止使用旧扩展，组件卸载释放请求/监听；不等远程请求返回才清图。
3. 日线控制器只复用现DailyWaveController/useDailyWaveReview/useDailyWaveCompanionLayers。未点按钮只有closed状态和按钮，daily-waves调用为0。点击后沿既有10秒链；empty不请求K线，失败不画三角，真实K线不匹配仅留已过合同的事实说明。
4. ready研究图的K线/dataKey/九转/趋势/重试/primitive/44px留白整组使用chartOverride；关闭恢复普通整组。普通controller、右栏、forecast日期始终不被research覆盖；研究重试只用研究实际日期，普通重试仍用普通日期。
5. 日/分钟识别详情使用模块renderXxmDetails；预判卡使用renderForecastDetails，均只消费已校验的debug对象，不再求价/选峰。分钟即使模块ready，也不挂日线波段控制器或三角，不发daily-waves。
6. 保留四种三角、共享位置、说明列表、8×6px/原侧避让40px/最高240px列表等§8现合同。URL debug切换允许现普通行情重请求及图表重建；已开的研究关闭且须重新手动开启；URL不变时模块phase/扩展更新不另行重刷；开启/关闭研究允许现dataKey所需重建。primitive内容更新不得因避让反复重建图。
7. r4简要状态和真正加载错误始终普通可见；九转“无对应K线”的辅助对齐诊断按debug显示，但请求失败/超时不随之隐藏。不改股票或普通分钟九转默认。

第2—3步不改公开字段、客户端返回类型、Hook签名或renderer合同；异常是缺陷应追到真实已有逻辑，不新增兼容字段。仅上述纯转换迁出及明确页面布局接线属于P3提取收尾；不得复制一份核对算法来“更方便挂载”。

### 21.5 第4步：工具迁移、逐请求记录及有界退出

先按§11.2.3—4迁完工具及测试，随后才能以其验收。旧DTO/对象返回、candidate/rearm路径、200ms断言和全部新结果落盘同次移除；不只换版本或预算数字。所有新增私有函数、数据类型、进程管理和观测代码都放原xxm_page_request_audit.py，显示工具复用；mjs只保留客户端执行，不新增文件、CLI入口、配置、公开HTTP合同或通用执行框架。

daily_window_precheck仍只留validate_window/read_window/isolated_client，无CLI。read_window保持原2020起有限窗口的独立核验用途，不替换正式源，本批不自动读取。isolated_client使用显式本地Settings和正式装配，临时SQLite/鉴权替身只证明其声明的隔离合同，不算正式来源或生产鉴权通过。

#### 21.5.1 参数与分组职责

两Python入口沿既定四项参数：--periods必填、非空、去重且只day/m60/m90/m120；--as-of省略表示latest，非空严格YYYY-MM-DD，分钟映射该日15:00:00+08:00；--mode为normal/debug/both默认normal；--samples只1或20默认1。格式/集合/重复/旧candidate或output在启动App/读源前拒绝；开市及端点完成性仍交正式API。只遍历显式周期，both顺序拆为normal/debug组，不形成四周期的笛卡尔组合，不自动重试。

main按下表产生封闭的任务清单，再逐组执行。组内period/mode/请求种类固定；计数不包括已列明的私有context/reset/metrics调用，后者单独登记。samples没有“重复整套页面20遍”的含义：

| 入口/参数 | 本周期本模式内执行内容 | 业务请求次数及缓存 |
|---|---|---|
| xxm_forecast_display_audit，samples=1 | 只该周期forecast一次 | 共1次冷请求；不据此宣称热缓存验收完成 |
| 同入口，samples=20 | 只该周期forecast连续20次 | 共20次，第1次从空产品缓存开始，后19次为重复请求；实际行情/预测缓存访问按§21.5.3记录，不按轮次假定命中；不追加并发/其他周期 |
| xxm_page_request_audit，samples=1，单tab组 | 该周期图数据、该周期九转、该周期识别及该周期forecast各1轮，沿该tab真实scheduler | day共4次；分钟价格/指标各1加九转/识别/forecast，共5次；组首空缓存 |
| 同入口同参数，双tab组 | 两个独立客户端realm同时执行上行选定周期组合各1轮 | day共8次、分钟共10次；两个tab各有scheduler，服务端共用本组缓存；不附加热轮或放大为20轮 |
| xxm_page_request_audit，samples=20且day | 只fetchIndexDetailKline的1000根日线接口20次 | 不混入九转/识别/forecast；第1次为本组首次请求，19次重复请求；不得宣称清掉了数据库/OS缓存 |
| 同入口samples=20且分钟 | 价格接口20次、指标接口20次，分成两个独立组 | 每组20次、limit仍500；仅报告各接口耗时，不套用日线800ms验收线 |

两个samples=1的页面组均为必做，顺序为单tab组→双tab组，各自≤60秒、各自新Python子进程和空产品缓存。两个tab只是被选周期的真实客户端组合核验，不能冒称覆盖页面完整四周期预判；完整四行由§21.7页面review及P4-18/31证明。以原indexDetailRequests调度，不能为方便共享加载跳过scheduler。九转仅所选周期，不自动请求15/30等未选周期。预测显示工具不再附加旧160次或固定其他日期/并发矩阵。

成功组依次GET context、GET reset，然后执行表中业务请求并等待全部完成，最后GET metrics；私有请求恰3次。表中业务次数也只约束完整成功组。失败/取消组只记录已实际发出的请求及阶段，停止新请求并按§21.5.6清理，不为凑满业务或私有次数继续执行。reset只能在无活动请求时执行。samples=20逐样本记录，不每样本清空缓存；“首次/重复”与“缓存是否命中”分开，不能按第2—20次直接标热命中，也不伪造数据库磁盘冷启动。缺真实预测命中时只登记该路径未验收，不改日期、额外预热、重跑或强制写缓存。

HTTP及计算的单次预算逐次判断，不能用P95掩盖一次失败。只有20次该接口真实成功样本齐全时才计算排序第19项的P95；中途失败/缺样本仅报告实际数量和原因，不补值、不沿旧样本拼凑，不输出通过结论。samples=1不声称完成20次性能或预测缓存命中验收。

latest请求仍不传asOf，普通/debug若中途出现不同完成根则对照无效，不偷偷补成历史请求。明确asOf则各组使用同一端点。both比较以请求实际截止和§21.5.3身份为准；组末只保留有界摘要/公共值摘要供下一组核对，不跨组保留完整响应、SeriesEntry或恢复副本。

**混合单/双tab组的取参及依赖顺序固定如下，不能沿用旧mjs先发识别、再等K线的写法：**

1. 每个tab只有自己的原indexDetailRequests实例。该tab在同一轮先登记该周期forecast、该周期九转及图数据任务；保留调度器原优先级，不直接调用底层HTTP绕过排队。日线K线显式经过一次run('chart',...)；分钟价格/指标client、九转loader、fetchForecast、fetchXxm本身已入队，外层不再重复run，以免互相等待。
2. 图数据endDate取明确--as-of日期，否则取本组context.businessDate；不传固定startDate，limit日线为唯一1000常量、分钟500，传本tab取消signal。分钟价格和指标分别1次，先共同返回并通过真实buildIndexMinuteChartViewModel的身份/时间对应检查，不能只等价格。日线从真实bars取tradeDate、close、factors.macd的dif/dea/macd；分钟取上述真实view model的time/fullDate、close/dif/dea/macd及indicatorVersion。仅构造核对需要的原值，不生成整页模型、不补值或格式化数值。
3. 得到非空、升序唯一且原close/DIF/DEA/MACD均有限的实际图点后，才调用一次fetchXxm。startDate=首点fullDate.slice(0,10)，endDate=末点fullDate.slice(0,10)，limit=实际points.length；分钟period与indicatorVersion取当前图，取参方式与现useIndexXxmLayer一致。不能用1990-01-01、context日期、请求的1000/500或下一预测端点替代实际首末/根数；图不足1000/500时原数使用。
4. 日线/分钟图滞后但有合法原值时，识别沿实际图日期核对，不虚报图已更新；记录请求日期和实际窗口的差异，该组不能因此宣称最新行情齐备。九转仍用第2条页面日期和原限制，forecast仍用原明确asOf或latest，不把它们改成识别的滞后日期；不要求图、预判机械拥有相同截止。
5. 空图、非法close/指标、日分钟身份错或分钟价格/指标不匹配时，不发该图识别；取消本tab及本组尚未完成任务，记录实际请求数及未验收/失败原因，停止该次CLI剩余组。HTTP成功但无有效图不作四周期验收通过，不能构造假图点来凑4/5次。真实合同允许的空值仍由原client处理，本工具不改产品的EMPTY/DELAYED含义。
6. fetchXxm一返回就沿其原deadline完成buildXxmViewModel及最终check；forecast同样立即完成自身最后check和摘要。不等其他请求全部完成才处理它们，否则会把无关等待算到已返回请求。之后才收齐本组摘要和metrics。正常完成时单tab day4次/分钟5次，双tab分别8/10次；异步依赖不增加请求或重新取K线。

#### 21.5.2 同一正式装配、明确返回和执行位置

同文件isolated_app(settings, *, group)仅由本次组子进程调用；group是下面固定AuditGroupSpec。正式_include_local_xxm_routers仍只有(target_router, settings)，不增加公共可选参数。临时App创建APIRouter(prefix='/api/v1')，调用正式本地装配后挂到该App；普通K线/分钟/九转沿原路由。依赖覆盖只把get_db_session替为原只读会话，保留require_quote_access、原异常处理及正式daily_wave_session_factory。lifespan关闭，仅绑定127.0.0.1:0，不启动后台。子进程在建App前核自身最终Settings的app_env显式性、分钟配置/root及database_url与父进程传入值相同，比较不输出凭据；不一致即失败，不静默覆写配置。新Python子进程不继承父数据库池；本组所有get_db_session和daily_wave_session_factory仍使用该已核同源配置。管理员的现有服务不受任何patch。

上下文yield本文件私有AuditApp对象，字段固定app、baseUrl、collector、stopRequested；baseUrl是真实绑定地址，collector仅为本组记录器，stopRequested只停止本组新任务，不修改产品计算器。退出规则见§21.5.6。原本地Settings使用最终配置，不硬编码dev绕环境；日线group不手动调用研究session_factory，daily-waves真实操作留管理员页面review。

mjs接收baseUrl及groupId、period、mode、asOf、samples、scenario这些父进程已经校验的值，不再接受输出目录或自行增加周期。scenario只是原CLI参数导出的内部任务种类，不是新增用户参数。只用既有esbuild/write:false/内存模块与pure client/decoder及唯一1000常量，不import React控制器、CSS或图层。client返回按{response,deadline}拆取；buildXxmViewModel显式传同一deadline的check，适配前后和立即提交本请求摘要给组汇总前检查，所有产品请求继续原deadline/取消检查。已按期完成的请求不因后来等待其他请求/metrics被重新开启或延长5秒。

参数事实以现生产者/消费者为准：get_index_detail_kline和fetchIndexDetailKline已经接受可选debug，服务端省略等价0、显式0/1仍合法。本次工具对K线固定省略，不随normal/debug切换；分钟价格、分钟指标和九转也不传debug。仅signals/forecast按本组模式传入1或省略为0。不得删除K线既有参数、修改TS签名/解析器、把K线debug=1改判非法，或给其他接口新增参数。逐请求debug字段记录的是实际URL中是否传入；省略为None，不伪造为本组模式，r4有效模式由group.mode及解码选项核对。

#### 21.5.3 逐请求记录、共享加载和同源证明

记录只属于隔离工具，不加到产品API、页面DTO或正式日志。请求头复用已有X-Request-ID：mjs在各自realm的fetch包装中，为白名单业务请求构造groupId:scenario:round:tabId:sequence，组内唯一；保留原URL、其他header、认证及取消signal，不改产品client签名。服务端原样回传。缺失/重复/不属本组的编号只在隔离核验路由拒绝；私有context/reset/metrics不混进业务记录。

mjs每个客户端realm仍只用原indexDetailRequests。该调度器保存work回调后统一执行，不能假定AsyncLocalStorage自动保留每个任务的归属；工具只在该realm的run入口捕获本次store，将传给原run的work包装为context.run(store, work)。原run恰调用一次，kind/signal/优先级/并发/执行体和返回Promise保持，不加第二次入队、不改产品调度器。真实客户端混合单/双tab必须证明识别、图数据、九转、预判各自编号不串。

本文件私有纯ASGI观测中间件把已校验requestId写入ContextVar，finally reset；原requestId中间件仍保留。同步endpoint进入AnyIO线程时ContextVar会复制，记录器使用锁保护的dict[requestId]，不能用一个全局“最后请求”变量。此传播已按AnyIO官方threads文档核对；测试还须走实际ASGI→同步endpoint，不能仅直接调用包装函数证明关联。

AuditRequestRecord字段固定如下，None不等于0，不从HTTP 200猜测已做计算：

| 字段 | 真实来源/约束 |
|---|---|
| groupId/requestId/tabId/sequence/round | 本组任务及现请求头；round为严格正整数，连续采样1—samples，混合组恰1，各tab各自sequence唯一。round只表达第几次，不表达冷热或命中；重复编号拒绝 |
| endpointKind/period/debug/requestedAsOf | 当前真实URL参数及本组白名单；endpointKind仅kline/indicators/nineTurn/signals/forecast；debug实际传0/1记该整数、省略为None。本次K线/指标/九转固定None，normal的r4也省略，debug的r4传1；模式校验把r4省略解释为有效0，不把其他接口None改成模式1。requestedAsOf取forecast的asOf或其他接口的endDate原值，未传则None，不伪造已传参数 |
| startedMs/finishedMs/httpStatus/bodyBytes | 服务端纯ASGI开始至最后body发送的单调钟偏移、真实状态与完整body字节；不混用Node的performance.now起点 |
| httpSeconds | Node由实际nativeFetch发出至完整arrayBuffer接收的单调钟差，单位秒；不是服务器ASGI耗时，也不包含后续JSON解码/适配。未完整收正文时None并保留失败，不用收到header或失败时长代替完整传输 |
| clientSeconds | 仅r4成功返回{response,deadline}时，从deadline−XXM_TIMEOUT_MS至本次适配/最终check完成，单位秒，包含HTTP/解码/适配、不含原scheduler排队。普通数据接口及未取得deadline的失败记None，不能冒充适用5秒合同或记0通过；原check仍按相同绝对deadline执行 |
| computedThrough/dataStatus/responseRows | signals取source.computedThrough、dataStatus.status、meta.count；forecast取computedThrough、dataStatus字符串，responseRows=None（不是K线数组）。其他数据接口取实际已解码的最后时点/行数，未提供dataStatus则None。失败尚无结果时None，不借另一请求补齐 |
| sourceInputId/calendarInputId/indicatorVersion | signals公开投影前的internal.source.inputId、forecast投影前的internal.sourceInputId/calendarInputId及原指标版本；非适用接口为None |
| prefixRows/windowStart/windowEnd | signals前缀根数由entry和实际computedThrough定位，窗口取meta.responseStart/responseEnd；forecast同次真实前缀根数及其首末时点，不把下一目标端点算入。非r4接口无算法前缀，prefixRows=None，窗口取实际返回首末。空窗口为None，不重读行情/重新step |
| computeSeconds/publicDigest | 仅本次真实400ms段；已校验公共DTO的规范JSON摘要，普通/debug比较时debug对象不参与 |
| forecastCacheRead/forecastCacheReadCalls | forecast初始not_called/0；原get_forecast返回None记miss，返回对象记hit，抛错记error，调用前计数+1。非forecast固定not_applicable/0；不能从第几次请求或内存条目数推断 |
| forecastCacheWrite/forecastCacheWriteCalls | forecast初始not_called/0；原put_forecast正常返回记stored，抛错记error，调用前计数+1。非forecast固定not_applicable/0；只在原发布真正完成后记stored |
| loadIds/errorCode/terminal | 实际关联的加载编号、现业务错误码；terminal仅success/error/cancelled，未结束不能输出成功 |

观察点固定：项目内部project_xxm_response的入参以及forecast_query_service持有的project_forecast_response入参，取得真实内层身份；包装必须原样调用原函数一次并返回原结果，不删除错误或改字段。signals的query在调用处现为局部import，patch真实response_projection模块的该符号；forecast已import到query命名空间，patch其实际持有符号，不能只改未被调用的另一处。prefixRows使用本次load_entry实际yield的entry，仅在原with期间关联到requestId；包装仍在原with内yield、原出口检查照常执行，退出即释放引用，不追加calculator_at或step。普通客户端不具备源ID不构成缺陷，不为工具改变公开合同。

LoadRecord以loadId为键，字段固定flightKeyDigest、period、startedMs、finishedMs、terminal、pairCalls、barsCalls、indicatorCalls、signatureChecks、seriesCacheRead、seriesCacheReadCalls；flightKeyDigest仅对现共享加载key做摘要，不输出其中路径、连接对象或凭据。seriesCacheRead初始not_called，观察本load原XxmCache.get：返回None为miss、返回对象为hit、抛错为error，调用前计数+1。这里hit只表示找到旧SeriesEntry，不表示源验证通过、不表示零重读；仍核pair/明细读取和来源修订事实。

包装现SharedLoads.load的loader：仅真正执行loader时生成loadId；对返回同一对象的订阅者关联同一loadId，已结束加载不能当后续请求的TTL命中，不改SharedLoads本身。外层包装用锁记录每个key尚未返回的调用数；结果对象与loadId的关联保留真实对象引用，最后一个调用退出即释放该key的关联，不只保存可能被复用的裸id，不跨20个顺序样本积累来源对象。loader失败时同样以实际异常对象关联收到同一异常的调用；等待超时且未取得结果/异常关联时，记本请求失败和loadIds为空，不能猜给最后一次加载。失败记录不被后续成功覆盖。

缓存观察只在隔离子进程包装上述三个真实方法及原loader；wrapped loader进入时设置本loadId上下文、finally恢复，XxmCache.get据此登记到本LoadRecord；get_forecast/put_forecast按当前requestId登记。仅观察本组q._CACHE实例，其他实例或无本组上下文的调用原样透传、不归到最后一条记录。原函数恰调用一次、原结果/异常/check原样转发，不读取entries补判断，不提前查缓存、不加缓存、不改get/put或求解策略。每个正常forecast原本最多get_forecast一次、put_forecast一次，每个正常load最多get一次；实际超出时保留真实计数并使工具核验失败，不能截断为1。共享等待者只引用同一loadId的行情查找事实，不复制为自己的再次查找；预测缓存事实仍逐请求独立。

以下分支必须原样保留并解释：SOURCE_EMPTY/DELAYED、静态NO_CANDIDATE及CALIBRATION_FAILED路径的预测缓存均为not_called；静态结果虽然dataStatus可为READY，也不能当cache miss或命中。实际到get_forecast后返回None才是miss；之后求解有target且原发布正常完成才记stored。get返回hit但后续完整校验/编码失败仍是本次失败，不能声称命中路径验收通过。

报告逐次列轮次、实际行情查找及预测缓存状态/次数、来源身份和耗时。先按真实事实划分“未访问/未命中/命中”，再在有成功样本时分别统计耗时；20次接口P95仍按全部20个成功样本计算，不只挑命中样本。需要预测缓存命中证据却没有实际hit时，记录“该路径未验收”，不能宣称完整冷热验收通过；若请求/合同/预算均成功，可继续原清单内已授权的其他独立组，但不另选日期或增加请求。单轮samples=1本来不要求命中，不因没有hit将合法单轮误报失败；不能把它提升为完整冷热验收。任何真实请求、合同或预算失败仍按§21.5.6停止整个CLI。

分钟pair内部的两个标准ThreadPoolExecutor线程不会自动继承上述请求ContextVar。pair观测包装在调用前登记(id(reader),freq,start,end)→loadId，锁保护；两个_read_complete_history包装依此关联bars/indicators计数，结束后finally移除；若同键出现重叠归属或无归属即本组核验失败，不能猜给最近请求。原pair函数仍只调用一次，绝不为传播上下文改Reader、另包一层执行器或重复读取。指纹stat计signatureChecks，不计明细重读。

现私有接口的返回形状在本轮固定：

- context：groupId、period、mode、requestedAsOf、businessDate、generatedAt、实际detector/forecast版本及hash。
- reset：只在本组无活动请求时允许，清本组缓存/计数后返回groupId和ok；有活动请求必须拒绝，不清他人缓存。
- metrics：groupId、requests（按requestId排序的上述记录）、loads（按loadId排序）、activeRequests、cacheBytes/cacheEntries、cleanupStatus。只调用一次；正文已经送达但服务端依赖清理尚未结束时，该调用在原workDeadline内等待本组activeRequests/workers归零，再取记录，不额外轮询HTTP、不另开时限。服务器不掌握httpSeconds/clientSeconds及普通数据接口的客户端解码统计，这些字段在metrics为None；mjs收到metrics后按requestId与本地已校验记录一一合并为最终摘要，不追加HTTP，不把缺记录猜成0。正常成功传输必须有httpSeconds，r4成功返回必须有clientSeconds，不能因服务端原为None就漏掉合并。此时App尚在运行，cleanupStatus固定pending；完成清理后result摘要才可改为cleaned，失败为failed，不能从activeRequests=0推断整个进程已清理。无完整响应、输入数组、SQL、源码路径、认证信息。

客户端按requestId一一配对，缺记录/重号/周期或模式不符即失败。normal/debug的r4对照只针对signals/forecast，且只有同endpoint、同period、同requestedAsOf、同computedThrough、同实际sourceInputId（forecast还须同calendarInputId）以及同可比窗口时比较publicDigest。指标版本也相同。不同模式不能用“最后一条记录”对齐；并发两个tab都必须保留。来源在未用到的未来区间改变而本次前缀ID相同，不误判本次结果变化；已用前缀改变则对照无效，原样报告，不强配或重跑。

合并时保留服务器真实httpStatus/字节/ASGI时间及缓存事实；最终terminal只有服务器和客户端均通过才为success。HTTP200但Node解码、适配或最后check失败时仍为error，取消为cancelled，publicDigest不作为成功证据；不能拿服务器success覆盖客户端失败。没有产品错误码的客户端错误记errorCode=None并按工具失败阶段说明，不新增业务错误码。失败请求仍参加已发生请求的对账，但不计入成功P95或成功命中覆盖。

真实组未实际重叠加载时，只登记“本次未测到并发共享”，不能强断重复读取或将共享观察填为verified；共享实现仍由原Event门控人工样本验证。真实请求不人为延迟源来凑重叠；此类未触发仅保留观察记录，不单独阻塞本周期或整批验收，按§21.14.6继续。日线顺序独立请求的必要来源核对仍允许，不能把所有HTTP总SQL数统一断言为1。

#### 21.5.4 计时及结果内存边界

400ms起点仍为forecast_query_service.build创建deadline的那一次真实perf_counter返回值，终点为build最后返回，包含复制/预检/校准/日历/求界或缓存复核/身份/投影/编码/发布。隔离进程只包装forecast_query_service.time模块引用和build，时钟原值转发；不修改标准库时钟、不改check，不从recover_projection或future_calendar之后才计。用threading.local区分请求时钟，再以ContextVar requestId归档；未建立计算deadline的路径记computeSeconds=None及原因，不报0或通过。

计时点和验收指标逐项固定，不能在编码时选择更好看的一个：

| 记录/预算 | 起止与实际验证 |
|---|---|
| httpSeconds；日线K线20次P95≤0.8秒 | 复用原mjs的fetch包装：t0=调用nativeFetch前的performance.now()，t1=完整response.arrayBuffer()返回后，同一Node时钟差/1000。日线K线只用此值求P95，含传输、不含后来JSON解码；不拿ASGI时间或clientSeconds代替 |
| httpSeconds；r4工具原HTTP≤4秒 | signals/forecast逐次按上述正文收全耗时核4秒，不改原工具口径。服务端query原4秒截止同时保持，由其原remaining/check执行，工具不重置或绕过。两者是不同观察范围，不能用服务器快来抵消网络超时 |
| clientSeconds；r4原客户端5秒 | 正常取得{response,deadline}后，起点恰deadline−XXM_TIMEOUT_MS（原5000ms），终点为本请求适配和最后check通过后。原check在now>=deadline时拒绝，不能因测量舍入而允许恰5秒；不把排队计入原5秒，也不在取到正文后再开5秒 |
| computeSeconds；预测计算/缓存≤400ms | 沿上文真实后台计算deadline起点直到build返回，含完整处理/缓存及编码。未创建计算deadline时None且标不适用，不能记0通过；真实截止仍由原check执行，测量不能减少实际时间 |
| startedMs/finishedMs；服务器ASGI拆解 | 两者只在Python单调钟内相减，含服务器实际处理直到最后body发送。用于说明时间花在哪里，不替代客户端HTTP、5秒或预测400ms，也不与Node的绝对时间相减 |
| 分钟图/指标/九转及普通K线单次 | 全部记录真实httpSeconds/字节和成功状态；保持各自现接口/Reader与组期限，不额外套日线800ms、r4客户端5秒或预测400ms。K线样本中任何真实失败仍不作P95成功样本 |
| 研究8秒/10秒；本组50秒/60秒 | daily-waves不在工具业务清单，原预算由页面验；组50秒工作、60秒含退出覆盖原scheduler排队/启动/运行/清理，不能拿组时限延长单请求预算 |

fetch包装只收正文一次，并用同一buffer及原status/statusText/headers构造Response交给原client.json()解码；不额外fetch、clone后再读或第二次解析来生成统计。保留原AbortSignal，headers先到但正文未完时不能填httpSeconds；失败/取消保留httpStatus和实际已知字节，未收全记None及原错误，不填耗时0或通过。各接口的完整body字节仍与原响应上限核对，错误正文不在摘要透传。

signals一返回立即用同一deadline给buildXxmViewModel/check，forecast一返回立即完成最后check，不等本组其他请求。生成本请求的有界摘要后再作原check并记录终点、clientSeconds，交给组汇总；该段全部在原5秒，不能只把摘要前的较短时间报作最终耗时。后续等待其他请求/metrics、合并服务器统计不重新检验这根已按期完成的客户端deadline，也不能修改已记录耗时。若client在返回deadline前就失败，clientSeconds=None、terminal=error/cancelled，沿原HTTP/预算异常，不猜起点或生成新deadline。普通K线/指标/九转没有统一5秒客户端返回合同，其clientSeconds为None，不因此少记httpSeconds。服务器metrics中的两个Node耗时字段由客户端最终一一合并，不能被None覆盖。

观测本身的开销保留在实际计时内，不扣除、不把httpSeconds与clientSeconds相减后验收。P95先用完整未舍入的秒数排序/比较，显示时才格式化；没有20个该接口成功样本不生成P95通过。逐请求校验之后才产生publicDigest，不调用同一业务函数生成expected。

业务响应只在子进程本组内保留到校验/摘要完成；samples循环不累积20份正文。父进程只接收context、记录表、摘要和退出状态；通信摘要总字节复用BUDGET.max_response_bytes上限，超限整组失败，不截断记录。单组业务请求数严格由§21.5.1表给出，私有控制请求单列；记录数也不得超过实际发出的白名单请求数。不落盘、无浏览器持久缓存、无恢复文件；跨组只保留同源比较所需有界摘要。

#### 21.5.5 外层监督与仅内存通信

两个CLI的main只解析参数/读取既有最终Settings、生成任务清单、监督本组子进程并收摘要；不创建App、不patch产品对象、不读行情。run_audit_group(group, settings)及无参数_run_audit_group_worker放原xxm_page_request_audit.py，显示工具复用。父进程用subprocess.Popen，shell=False、start_new_session=True、close_fds=True；命令固定为当前sys.executable以-B/-c正常import该模块并调用这一私有worker函数，不从参数选择模块/版本、不读源码SHA，不新增用户CLI参数或独立运行器。

AuditGroupSpec恰含groupId、tool、scenario、period、mode、requestedAsOf、samples、startedAt、workDeadline、deadline；后两者恰为组开始+50秒、+60秒，包括Popen/导入/启动及清理，不在子进程重新计60秒。scenario仅表中mixed_single/mixed_two/forecast_series/kline_series/indicator_series。子进程一次只执行这一组，不领取后续组。

父进程只经stdin发送一份有界JSON，恰为group及settingsIdentity；后者是父最终配置中app_env的值/显式性、分钟flag/root、database_url的规范摘要，仅作本地一致核对，不输出凭据或配置原文。子进程用原get_settings及现优先级取得自身配置，先验证摘要再创建App，不一致即失败；不通过stdin覆盖全局配置。输入限4096字节，无行情、缓存或恢复对象。父进程以非阻塞stdin写入并关闭，子进程读至EOF且限同样大小，写入过程也受原截止约束。

stdout只传三种JSON行：started（groupId、pid、processGroupId）、result（groupId及有界摘要）、failed（groupId、stage、errorType、errorCode、cleanupStatus、summary）。failed的summary仅含已实际发生的请求/加载有界记录与计数，尚未取得的客户端耗时为None，不含正文或异常原文，不生成成功P95；初始化失败尚无App时为None。Node错误stderr仅含stage/errorType/sentRequests/requests，requests只保留同一fetch/execute已记录的requestId、httpSeconds/clientSeconds、terminal、httpStatus/bodyBytes、computedThrough/responseRows/windowStart/windowEnd；取消后未完成的请求标cancelled，已经失败的保留error。Python严格检查字段、编号、有限数值和数量，再按requestId与本组服务端事实合并；解码失败的HTTP200必须保留error，已知耗时不能在失败时丢失。类型/数量不合法则记工具通信失败，不透传原文。若Node已成功返回而最终预算检查失败，使用同一已返回摘要合并，不丢弃其客户端事实、不重新请求metrics。正常失败先按原期限清理，再取得本组记录；父进程验证失败摘要组号、数量不超过所选成功组上限、只含固定字段后才能输出，随后停止剩余组。通信破损或仍有进程时不得信任已收到的failed摘要，仍按清理失败退出。started恰一次且在终态消息前，必须pid=processGroupId=父进程创建的child.pid，因为start_new_session已在执行Python前建立本组；result/failed二选一且恰一次。导入或配置检查失败可能来不及发started，父进程仍按自己持有的child.pid清理并报告失败。收到result不表示成功；必须等正常清理、子进程退出0、通信正常结束及所有记录检查通过。子进程不传异常原文、完整HTTP/body/源行；Node stdout也不直接转印。Node保持在本组进程组，不另建session或后台脱离。

父进程用selectors与非阻塞stdin/stdout/stderr，每次按剩余期限读取有限块，逐次检查总字节及50/58/59/60秒时间。stdout与stderr累计缓冲合计不得超过原BUDGET.max_response_bytes；半行、超大行、子进程不结束、管道出错都不能让读取阻塞或无限积累，不能用无界readline/recv或先join等退出再收满管道。完整行经字段/类型/组号校验后处理，EOF有未结束JSON即失败。stderr只累计受限字节数供失败定位，不在终端打印可能含连接信息的原文；不能仅有一般警告就篡改业务结论。超过大小限额立即走失败退出。父进程自己的输出只给已验证的数量/日期/字节/耗时及结论，不透传worker原文。全程无临时结果文件。

#### 21.5.6 失败、卡住线程与最终退出

组业务阶段最多到50秒，父进程在该点向本组进程组发SIGINT，触发worker既定BaseException清理及Node退出；子进程自身也按workDeadline停止新请求/采样，不依赖信号回调才检查。所有正常失败、Node失败、取消及BaseException进入同一清理：

1. 停止客户端及采样，取消其HTTP，停止Node并有界回收；server.should_exit，停止接受新请求。
2. 等本组活动HTTP和服务线程实际结束，关闭本次socket/会话，并释放子进程本次建立的数据库engine；不调用会吞掉错误的清理包装来伪造通过。只有确认activeRequests=0、服务线程/Node均结束，才逆序恢复观测包装、时钟引用、临时覆盖及原_CACHE；每项patch后立即登记清理，支持初始化中途失败。
3. 业务线程未结束时禁止先恢复包装、清缓存或进入下一组。子进程记录失败阶段并继续在清理期限内等退出，不打印PASS。若到组开始+58秒仍未完成，父进程向由Popen创建且已知等于child.pid的本组进程组发送SIGTERM，不能拿worker消息中的任意pid当目标。到+59秒仍存活则对同组SIGKILL并回收直接子进程，最终不得超过+60秒继续工作。直接子进程退出后仍须检查本组是否有遗留成员（只检查已知进程组的存活）；Node残留也走同一终止期限，不能只看child.returncode为0就放行。只操作本次创建的进程/组，不按端口或名称杀现有服务。
4. 被强制结束的子进程不要求继续运行Python finally去“恢复”自身已销毁的内存；父进程从未装这些包装，现有服务不受影响。不得把强制退出写成优雅清理成功；该组为失败，停止整个CLI剩余任务。
5. 正常清理失败、残留进程、管道坏消息或收到成功摘要后子进程非零同样失败。收到合法failed表示业务已失败、子进程正在结束，不立即再发SIGINT；仍收完管道、等退出并检查本组残留，原50/58/59/60秒监督继续有效。failed后还有半行或坏消息仍是通信失败，不能被此前failed标记盖掉。进程查询或发信号返回权限错误不能当作“已无进程”；视为尚不能证明清理完成，仍受原期限约束并记录失败。若内核异常导致SIGKILL后仍不可回收，最多等到原60秒即记录清理失败并停止，不宣称无残留或重复杀其他进程，交管理员处理；不得静默留后台任务继续验收。

Ctrl-C沿同一停止及回收过程；不恢复执行、不自动重试。下一次获准重跑是全新组及新缓存，不从磁盘恢复。人工故障测试须造真正不退出的服务线程/Node，证明父进程能结束整个本组；不能用空清理函数或仅mock join成功代替。


### 21.6 第5步：真实来源与性能验收范围

此处定义执行方法，不把尚未读取的物理数据登记成“齐备”。实施前先复核当前正式配置和已有证据，登记不含凭据的来源工程/连接目标或正式Lake根、单上证、周期、截止、实际计算前缀、字段投影及原上限。日线仍正式IndexFactorPro的close/macd_dif_bfq/macd_dea_bfq/macd_bfq及SSE日历；分钟仍正式/Volumes/datasource/data_lake下当前bars/indicators，禁止退役根、临时报告输入或另行采样重算实际指标。

分钟按已完成的§0.9实现读取和计算：请求N根使用截止时点之前最多N+1000根完成K线；本节正式工具请求默认500，实际计算前缀必须为正整数且≤1500，识别输出≤500，不足按真实数量，不向前补量。历史请求以该历史截止重新计划有限窗口，不从latest窗口硬截。日线仍沿原来源前缀及20000根保护上限，不把页面1000根当作计算上限；5000分区等原保护不放宽，也不能替代分钟1500根的实际验收要求。验收不再修改SQL/Reader或核心来改变这一已生效口径。若将扩为某数据集全局明细读取，仍须依根规则另获批准；保存样本和日线窗口工具不能替代正式接口来源。

本批直接沿用现有.env.web.local。APP_ENV=local只控制本地r4功能开放，DATABASE_URL继续连接现有prod数据库152.136.106.251:5432/goldenshare；日线读取该库的core_serving.index_factor_pro和原SSE日历。分钟仍按同一配置读取本机/Volumes/datasource/data_lake的正式bars/indicators。get_settings按现优先级读取配置，src/db.py使用其database_url创建会话，隔离工具保留原鉴权和只读事务；不修改.env、连接目标、SQL或Reader。程序在本地运行不意味着日线数据库必须位于本机，沿用现有prod连接不属于切源，无需重新确认或另找本机日线库。

此前历史回测限定只读本地DG，仅适用于该回测专项，不能套用为P4正式产品验收的来源限制。只有实际更换现有数据库目标、Lake根或扩大已批准读取范围时，才按原规则另行确认；例行核对当前配置与上述来源一致仍须执行。这次仅删除错误的来源阻塞，不把尚未执行的真实读取/性能登记为通过，也不开放生产环境r4。

| 周期 | 完成端点（上海时间） | 核验目标 |
|---|---|---|
| day | 开市日15:00后完成 | 主图请求1000、识别同真实日线窗口、下一根日线预判 |
| m60 | 10:30/11:30/14:00/15:00 | 原500根分钟图、60分钟标签和下一端点 |
| m90 | 11:00/14:00/15:00 | 原500根分钟图、90分钟标签和下一端点 |
| m120 | 11:30/15:00 | 原500根分钟图、120分钟标签和下一端点 |

以source.ENDPOINTS为唯一代码表，不在工具复制第二份时刻常量。日线图窗1000、分钟图窗500与实际计算前缀分列；分钟前缀按N+1000而非全历史，正式工具最高1500，日线前缀保持原范围。明确asOf严格使用完成根；latest白天按各周期实际完成截止，不假定均为当天15点。日线不足1000、分钟不足500均如实报告。

每周期至少包括：正常/辅助同源字段一致；真实主图close/DIF/DEA/柱逐时点严格相等；已完成根/日历连续性和元数据；冷/热请求及字节；历史asOf不含未来记录；模式/周期切换、既有隔离样本的共享功能验证及真实组的读取/缓存复用记录。真实组不强求实际发生加载重叠，未测到并发共享不单独阻塞，按§21.14.6如实记录；source修订/取消等危险反例仍用隔离人工来源验证，不改真实数据制造故障。

沿§9上限：识别4秒/1MiB，预判总4秒且计算及缓存处理400ms/32KiB，页面识别/预判5秒；研究业务8秒/2MiB、前端链10秒；仅日线K线20次P95≤800ms，分钟价格/指标及预测不套此800ms。缓存64MiB/16系列、源数量/并发/研究内存等原上限均不变。记录实际参数、完成根数、前缀根数、响应字节、冷/热及取消清理耗时；任一超限停止说明输入与阶段，不裁掉引用、提高预算或回退旧版本。

四周期真实证据必须逐行有状态和原因：已适用证据/通过/失败/未验收。当前逐周期执行顺序及硬停点以§21.14为准：任一真实失败立即停止所有尚未开始的命令和周期，不能因为另一个周期可用而继续；请求成功但其他必需覆盖未验证时，依§21.14.6在当前固定命令结束后停止后续命令，不自行追加；仅真实组加载未重叠而未测到共享不属于该停止条件。整批不得在缺证据时通过或进入P5，不能删周期、填人工结果或拿922日线代替。改变范围先经管理员确认并同步原四文档。

### 21.7 第6步：自动核验与管理员页面review的明确交接

第5步临时App仅用于自动有界读取/客户端验收，组结束必须关闭；绝不把该临时端口交管理员长期看页面。第6步的真实页面使用管理员维护的本地开发服务，与采样组是两个独立生命周期，但必须核对同一产品版本和来源。人工review不是一个持续HTTP请求，不受“自动采样组60秒”限制；每次页面实际业务请求仍受原4秒/400ms/5秒及研究8秒/10秒限制。

固定交接：

1. Codex完成代码和自动测试后，列本轮实际提交或未提交文件状态、正式算法/预测身份、工具实际源范围/截止及配置要求，交管理员。Codex不重启/替换现有服务、不抢占8000端口。
2. 管理员负责将本批代码加载到现本地后端127.0.0.1:8000，显式APP_ENV=dev/local，分钟沿既有配置，并启动/更新本地Wealth开发服务器。前端按当前wealth/vite.config.ts把/api转到8000；前端实际端口按其启动输出记录，不猜5173，不新增proxy环境变量或改配置去追临时端口。
3. 页面入口使用当前buildIndexDetailPath('000001.SH')产生的真实路由，分别无debug及debug=1；登记完整浏览器origin和实际/api目标。浏览器请求必须确实到8000这批后端，普通/辅助响应身份及完成截止须与同次核验一致。若代码/配置未加载、端口不符或来源不同，页面review记未执行，不能沿旧页面验收，也不能静默改为别的端口。
4. 自动采样结束到人工review间市场可能新增完成K线；不要求几天后的latest与旧摘要机械相等。用同一明确历史tradeDate重核可比公共结果（分钟沿该日完成端点）；看latest时另记当前完成截止，保持同一规则/来源合同，不能拿时间更新当算法差异。需要重做有界采样时另列范围，不自动扩跑。
5. 真实页面API响应→标签/悬停/卡片的展示检查由管理员浏览器review完成并登记。自动组件测试是其独立部分，Node真实客户端只证明请求/解码/数值，不能替代DOM/布局/网络和控制台。管理员确认的页面结果是进入P5的前置。
6. 生产前端构建由管理员从既有App的/wealth静态入口查看，须先确认WEALTH_DIST_DIR指向本批构建产物，记录实际URL；静态页面与正常/API同源使用本机8000，不新增临时proxy配置；即使后端为local，前端production仍不得显示/请求r4或下载辅助chunk。服务端生产/缺环境门禁另用正式完整/api→/v1聚合链的隔离App测试404/OpenAPI缺席/零源调用，不能用本地后端可调用代替生产关闭证明。构建及本机静态页面核验均不部署生产。

管理员操作清单必须包含：

- 1600/1440/1280宽，45/180根可视，拖到301根之后；真实r4标记/同根显隐/悬停与同窗口API对应。
- 日线及可用60/90/120分钟各自识别；主图切到5分钟等不支持识别周期时，该图无r4标签/识别请求，但技术面四行合法预判仍按原active及分钟能力工作。
- 无debug无辅助下载/DOM；debug加载中/失败仍有普通功能；未开波段零daily-waves请求、无三角；URL debug切换允许重刷及图表重建，只有模块phase变化不得另行重刷。
- 手动研究、关闭、切周期/标的/日期、离开和迟到：研究日期/图层/九转/趋势/重试整组恢复；右栏和forecast不倒退；说明面板240px和键盘行为保持。
- 原行情、九转、趋势真错误仍可见；只有辅助对齐诊断受debug控制。
- 生产构建普通/debug两URL均无r4 DOM/请求/辅助预载，原日线K线/九转/趋势正常。

P4四周期真实证据齐备而管理员页面尚未review，只能写“自动工程及真实客户端核验完成，待真实页面review”；不能写整批验收通过或推进P5。服务由管理员维护，采样工具仅清理自己创建的进程，不接管人工review服务。


### 21.8 独立用例设计与测试落点

预期来自本节及§1/8/9和独立字面合同；不得让工具/页面自己生成expected证明自己。沿P3手写r4夹具和实际API，不改旧输出的hash当新样本。故障注入要进入真实检查分支；正常正例必须证明不会误拦。下表是P4新增/扩展覆盖，RC/PF/F系列继续回归但不重跑实际双组行情。

| 用例 | 独立输入/动作 | 必须断言 | 位置 |
|---|---|---|---|
| P4-01 | 显式dev/local；缺app_env、prod/test/未知/空串 | 本地三基础能力及可用分钟各仅注册一次；其他四路径404且OpenAPI缺席、源/算法零调用 | 新tests/web/test_wealth_index_detail_xxm_local_routes.py |
| P4-02 | 同一Settings分钟off/未就绪/合法on；明确on非法root | 无分钟时日线真实query成功、分钟不支持；合法on分钟可用；非法配置保留现错，不绕过 | 同上及原test_local_minute_capability.py |
| P4-03 | env文件/进程冲突及未显式默认dev | 按现优先级，不能缺配置误开启；临时env和get_settings缓存复原 | 同上，使用临时文件而非真实.env |
| P4-04 | 本地未授权/403，生产debug=1；正常生产日线 | 原鉴权保留；生产r4不可达但正常日线仍按原合同成功 | 同上及现日线API集成 |
| P4-05 | loader false/true→ready | false零import；true五项真实导出，只有ready返回module | 新debug/useIndexDebugModule.test.tsx |
| P4-06 | true加载后关闭/卸载/再次打开；旧Promise晚成功或晚失败 | 旧序号不显示模块/错误，不挂旧控制器 | 同上 |
| P4-07 | import失败→手动retry；StrictMode清理重建 | 独立错误、重试仅enabled/error有效，无自动研究或残留监听/循环 | 同上 |
| P4-08 | Page普通、debug loading/error/ready/关闭 | effectiveDebug依次0/0/0/1/0；真实decoder/renderer只在ready；普通功能不断 | 现IndexDetailPage.test.tsx及availability测试 |
| P4-09 | 模块切换时0/1响应逆序，HTTP4990ms后解码跨5000ms；正常未超时 | 无串模式/迟到ready；沿同deadline拒超时，正常通过 | 现xxm/useIndexXxmLayer及forecast/client测试 |
| P4-10 | 前端production或其他指数，误传enabled；四周期识别Hook收到非法period | production/其他指数整项关闭r4；非法period只拒该图识别，不产生其primitive/请求。不能据主图不支持就停右栏，另验P4-31 | 页面/日分钟工作区及真实生产build/静态页面检查 |
| P4-11 | debug1根字段错/编号错/悬挂关系；普通合法 | debug整份报错不降级；普通合法仍展示；P3 F系列不退化 | 现decoder及r1Contract测试 |
| P4-12 | 独立字面CandlePoint及overlays、null、原小数 | 转换字段逐项正确、不改输入；消费者不再从组件导入纯函数 | 新chart/indexChartPointAdapter.test.ts及导入检查 |
| P4-13 | owner A扩展→B后A晚null；退出debug | 旧扩展和清理不清B；渲染时owner与ready双检查，无旧研究图 | 现Page及IndexRecognitionDebug.test.tsx |
| P4-14 | debug日线刚ready、分钟ready；未点击/手动点击/empty | 未点零daily-waves；分钟始终零日线研究；empty不取研究K线 | 现debug及daily-wave请求测试 |
| P4-15 | 普通日期晚于研究，普通/研究各自重试，研究关闭 | 两组日期/九转/趋势/重试/primitive完整对应，右栏和forecast不倒退 | 页面/工作区/companion原测试 |
| P4-16 | 无研究的debug进入退出；研究ready后关闭；同数据重发扩展 | URL debug变化重请求/加载/重建，旧请求取消且迟到不覆盖，右栏回基本行情、研究关闭不自动重算；URL不变仅模块phase/扩展变化不主动重刷，扩展无渲染循环；研究仍按dataKey切换 | 工作区及debug组件测试 |
| P4-17 | 四三角/共享位置/开放尾段/空间不足、1001行、原股票/分钟 | 原画法/说明/1000截取及诊断不变，股票300/分钟500不变；真错误可见 | 原daily-wave/九转/工作区测试 |
| P4-18 | 技术页签四行、图周期切换、单行retry、历史日期、visibility | 原四行和active策略不改；next目标各自周期；单行重试/历史无刷新/退出取消 | 现forecast及Page测试 |
| P4-19 | 两CLI帮助/非法period/重复/缺period/samples非法、旧candidate/output | 在任何App/源调用前拒绝；合法单period参数正常；README同参数 | 新主题tests/test_xxm_p4_audit_tools.py |
| P4-20 | daily_window人工输入、缺交易日/DEA、正常有限窗口 | 真实字段严格校验；隔离App走正式装配/当前bytes，不借旧acceptance和writer | 现test_xxm_daily_window_precheck.py |
| P4-21 | Node当前真实client，手写普通/debug HTTP及错误状态/超时 | 正确拆response/deadline；拒旧字段，失败非零；无结果文件/全body输出 | P4工具测试及Node隔离入口 |
| P4-22 | 400ms完整计时，令calculator_at/precheck/校准/编码/缓存命中分别变慢；未建立deadline的失败；正常例 | 每段都入计时，冷热不计0；无计算段记None，不伪报通过；真实时间/check/错误/取消身份保持且时钟引用复原 | P4工具测试+原forecast API/F06—08 |
| P4-23 | 隔离样本的两tab同前缀冷并发、热缓存及签名修订；真实组自然调度记录 | 隔离样本必须验证同源并发合并，每loader/pair/dataset一次；热签名不变0pair，修订不误用旧结果。真实组未发生加载重叠只记未测到，不阻塞或凑命中；实际重复读取仍失败 | 原test_xxm_shared_loads.py及工具计数测试 |
| P4-24 | Node失败/启动失败/请求错/取消/清理期间超时，在第一个patch后抛错 | 活动请求结束后才恢复包装；正常退出资源释放。任何失败停止该次CLI后续组，不自动恢复；另一次显式合法运行不受污染。卡住路径另验P4-35 | P4工具测试 |
| P4-25 | 禁止结果write/mkdir/candidate加载；正常只读及临时SQLite | 旧结果落盘和动态源码路径不可执行；纯RAM正常通过；源校验保留 | P4工具测试+静态依赖检查 |
| P4-26 | 固定asOf normal/debug同源；新完成根/源修订夹在两组之间 | 相同公共字段/标签ID/display；变化明确本组无效，不能硬配 | 工具独立样本及真实有界场景 |
| P4-27 | samples1/20、业务50秒截止、58/59秒终止、P95手写20值 | 严格按21.5.1业务/私有请求次数；20不含隐藏预热或混合重复；父时限含创建子进程/退出≤60秒，失败不PASS，P95取19项 | P4工具测试 |
| P4-28 | 四周期真实只读及实际API/窗口/历史/bytes/预算 | 分周期真实证据，不补缺；400ms/4秒/5秒，K线20次P95≤800ms | 适配后原工具，非mock |
| P4-29 | 研究真实start→K线匹配→图，关闭/错误；生产build/本机静态入口 | 原8秒/10秒与2MiB保持；默认无研究，生产无功能及相关下载/请求 | 真实API驱动页面和管理员浏览器review |
| P4-30 | 缺某周期、预算失败、页面review未完成、P5旧模块仍在 | 对账标失败/未验收，不能宣称P4通过、自动清退或部署 | 本三文档交付对账 |
| P4-31 | 本地上证technical激活，主图day→m5→m90，分别debug0/1及分钟能力off | m5无图上识别；合法四行按原资格继续请求/显示，minute off只禁分钟行，day不受影响；切回m90恢复该图识别 | Page、日分钟工作区和forecast测试 |
| P4-32 | 两CLI、四周期、两模式、samples1/20及内部scenario手写请求清单 | 成功组次数及K线→实际取参→识别顺序与21.5.1相等；失败组记录实际数、不补请求；独立组无缓存串入，不跑未选周期/旧矩阵；错误参数启动前拒绝 | 主题P4工具测试及Node隔离入口 |
| P4-33 | 两tab同周期响应逆序/重号/缺记录；真实ASGI同步线程和分钟pair子线程 | requestId唯一关联；每请求时间/源/摘要不串；pair子线程按显式loadId归属；重复或无归属拒绝，不用最后一条记录兜底 | 工具ASGI集成及原shared_loads测试 |
| P4-34 | 临时采样端口已关闭；人工开发页/API8000；静态生产页；旧服务或错误端口 | 人工地址不指向临时App，不改Vite代理；版本/来源未确认不得验收；生产静态页无r4请求。用户review未完成维持未验收 | 静态调用检查、真实页面交接及管理员review |
| P4-35 | 真实卡住的服务线程或Node、started缺失/重号/错pid、result后不退出或子进程已退出但Node残留、半行/超量stdout或stderr、管道断开、Ctrl-C | 线程未完不能恢复包装；消息次序/终态唯一，清理前不报cleaned；父进程仅终止本组，58/59秒升级，60秒内停止并报告失败，无后续组/PASS；主服务和父进程包装从未被改 | 工具进程集成，人工阻塞不读真实源 |
| P4-36 | normal/debug同前缀；已用前缀变更；只在未用未来区间变化；窗口不同 | 同源同窗口公共摘要相等；已用前缀或日历变更对照无效；未来无关变化不误拦；窗口不同不能强配，不重算来造一致 | 工具独立字面样本及受控ASGI集成 |
| P4-37 | K线延迟返回、滞后/不足/空数据，分钟指标更晚或错位；每tab独立 | 图未合法返回前识别0次；实际首末日期/根数/版本入参准确，不代用请求数量或context；右栏日期不被改；空/坏图取消且不凑请求 | P4工具测试及Node独立字面HTTP |
| P4-38 | r4 normal/debug两组；日线K线既有debug省略/0/1；非法值 | 工具只让r4按模式切换，K线等固定省略；原K线0/1合法和非法值拒绝均保持；记录实际参数None/1而非虚构传0，匹配有效模式正确 | P4工具测试及既有日线API参数测试 |
| P4-39 | 行情查到但预测未访问、真实miss/store/hit、source修订及坏缓存；共享等待者 | 状态/次数来自原方法一次调用；不按round猜命中、不额外get/put；正常不访问不误拦，失败命中不算验收；缺hit覆盖如实未验收，无额外运行 | P4工具测试+现forecast API/SharedLoads人工样本 |
| P4-40 | 独立HTTP/客户端/后台时钟，完整正文晚到、解码/适配跨限；20次及不足样本 | httpSeconds/clientSeconds/computeSeconds各用真实起止，800ms/4秒/5秒/400ms逐项对应；不混时钟、不重开/相减、无完整值不记0；P95准确且无补样本 | P4工具测试、Node隔离入口及原P4-09/22/27扩展 |


新增测试路径以表为准，先核目录存在后创建在对应域；研究工具测试不散落根tests。现web模块测试继续保留，不为环境门禁改掉所有fixture。生产反例必须走正式App装配及前端production构建；只mock development=false不足以证明构建无辅助加载。无结果落盘测试拦的是本轮工具writer，不能拦模块导入/原材料读取后把无读取误当通过。

#### 21.8.1 四项补齐的独立字面预期

以下只设计测试，不在文档轮执行或编写测试代码。HTTP夹具沿已核的K线生产者字段及P3合法r4字面DTO构造；错误样本明确故意用于反向测试，不用待测工具/算法输出生成expected。

- **P4-37取参和顺序：**context日期2023-01-05，日线实际仅2023-01-03、01-04两根合法K线；请求limit1000。应在K线返回后恰发一次识别，startDate=2023-01-03、endDate=2023-01-04、limit=2；forecast latest仍无asOf、九转仍endDate=2023-01-05。明确历史asOf则forecast仍使用该请求日而非图上较早末日。另用分钟两根同日10:30/11:30合法价格/指标、请求500：指标Promise未完成时识别0次，完成后limit=2且版本取真实返回。指标缺一根、时间错位、DIF非有限、空bars分别不发识别且取消剩余任务，不能按成功组硬补4/5次；合法不足根数和合法滞后均不能误当合同错误。两个tab分别从自身返回值取参，不借另一tab窗口。
- **P4-38参数：**对同一组合法输入分别执行normal/debug，工具K线URL均无debug，signals/forecast分别省略或传1；记录debug相应为None/1，有效普通模式仍按0解码。另在原真实K线路由参数测试中验证省略、0、1继续成功，2/重复键仍拒绝；该测试不追加到真实采样组。不能通过删除K线debug签名来满足“工具不传”。
- **P4-39缓存：**借用现静态ZERO_WAVE和CALIBRATION_FAILED独立样本，行情已有条目且其验证合法；预测get/put均0、状态not_called，轮次即使20也不是预测hit。正常可缓存样本首根read=miss/1且write=stored/1，下一相同输入read=hit/1、write=not_called/0；值和原异常相同，观察不能再查一次。源修订后旧行情get可为hit，但分钟pair按原流程重读、预测新身份为miss，不能凭行情hit断言零重读。共享两请求只有一个真实load和一次行情get，两个request引用同loadId，不能算两次行情get。坏预测缓存虽get返回对象而记hit，后续完整校验必须失败且不求解兜底；报告不得计为成功命中验收。没有任何hit的20次合法静态组应保留合法响应及预算结果、将命中覆盖标未验收，而非误判接口错或偷偷加第21次。
- **P4-40计时：**手写20个HTTP0.70秒，JSON/适配合计加0.20秒；K线P95应仍0.70，不用0.90验800ms。另18个0.70、2个0.81，第19项0.81使P95不通过，19个样本不输出P95通过。r4正文4.01秒即使服务器只1秒也不通过HTTP4秒；headers先到不算正文已完。返回deadline=6000ms、原客户端起点1000ms，最终5999ms正常，6000ms必须由原check拒绝；不能从收到正文时重新计5秒。计算段390ms正常、410ms失败；Node和Python绝对时钟起点故意不同，仍只各自做差。正文取消、未返回deadline、未建立计算段分别为对应None和实际状态，不能填0通过。HTTP200但解码失败最终必须error，不能按服务器success计样本。某请求已完成摘要后另一个请求较晚结束，不重新将前者判超时；前者自身适配超限仍必须拒绝。

### 21.9 执行、独立审计及交付停点

执行顺序固定：第1步路由→第2步加载/请求→第3步组件/纯转换→第4步工具→第5步真实源/预算→第6步页面/独立审计。每步先做对应定向正反例；完整Wealth、typecheck/build、相关web与共享加载、根三架构及文档/链接检查在交付前执行。不整目录重跑旧研究或实际双组回测；各测试/验收组含退出开销≤60秒，现环境缺依赖先说明，不安装。

开发后独立从当前代码重查以下顺序，不只核测试数量：Settings→唯一路由注册→页面资格→模块ready→effectiveDebug→同一客户端/截止时间→公开合同/图表→研究整组交接→工具实际计时/读取→finally清理。用实际源码/测试和真实范围填写：

| 步骤 | 实际代码/测试 | 真实证据与未覆盖 |
|---|---|---|
| 1—4 | 已完成代码、定向回归及独立代码审计，详见§21.10 | 人工HTTP、SQLite和受控故障只证明对应工程边界，不代替真实来源；完整Wealth有范围外失败 |
| 5 day/m60/m90/m120 | 日线已有真实证据；m60优化后4次小范围复测通过，完整分钟清单仍待正式续验 | 历史失败及日线续验见§21.11—13，小范围见§0.10.9；当前剩余设计和验收范围见§21.14，不混算为已通过 |
| 6 | 实际API驱动、build/本机静态页面及管理员review | 当前未执行，不能用Node代浏览器 |

#### 开工前四项补齐及独立文档审计记录（2026-11-01）

本轮依据e2844c6f7后的审计，只补工具取参/请求顺序、K线既有debug合同、缓存真实使用记录及计时指标；前六项环境/页面/分组/来源/清理修正继续保持。原开工判断由本次整体复核替代，不保留与当前设计不一致的执行指令。

| 四项问题 | 本次唯一要求 | 设计覆盖 |
|---|---|---|
| 取参和顺序不完整 | §21.5.1先合法图点、再真实首末/根数识别；分钟先匹配价格/指标，失败不凑次数；预判/九转日期保持 | P4-32/37 |
| K线debug合同事实错误 | §21.5.2保留K线原0/1能力；工具仅省略，不按r4模式改变；记录实际URL及有效模式各自含义 | P4-38及原参数测试 |
| 按轮次假设热命中 | §21.5.3真实观察原get/get_forecast/put_forecast，不额外查询；正常不访问、源修订、坏命中与共享者各自明确 | P4-23/39 |
| 计时指标不对应 | §21.5.3—4分开HTTP/客户端/后台/ASGI时间；实际正文和原deadline各自计时，固定预算表及失败None | P4-09/22/27/40 |

独立复核重新从当前代码核对：useIndexXxmLayer实际首末日期及根数、分钟图价格/指标匹配、K线真实路由与TS参数、客户端和scheduler的deadline开始点、预测静态/校准/缓存分支、XxmCache三个真实方法及原mjs正文接收计时。CodeGraph codegraph_explore核相关入口/消费者/缓存影响；同名API方法不代替缓存实现证据。再按本节正反场景检查数据滞后/不足/空值、共享/源修订、合法不访问预测缓存、错误命中、不同计时和组退出的上下游配合。

复核中同步消除了成功组次数对失败组的误约束、轮次与缓存状态混用、实际参数None与有效模式0混用、已完成请求被其他请求等待重新判超时，以及HTTP200掩盖客户端失败的歧义。P4六步顺序、原四周期/普通-debug合同、只读/纯内存/60秒退出、r4算法及所有既定预算保持；不增加产品参数或另起执行入口。

仓库文档完整性、三文件git diff --check及14处本地链接检查通过；P4-01—40编号连续无重复，新增四项均有独立正反例和代码落点。仅另核对文档中P95字面算例，不执行产品测试或实际采样。40项设计不代表40项测试已经执行；未修改代码、配置，未读行情、运行工具、提交或部署。

结论：本轮四项补齐及与前六项的衔接已完成，当前审计范围内未发现仍未处理的方案/LLD冲突、需新增拍板的口径或缺失交接，具备进入P4开发的文档条件。本轮停在文档交付；真实四周期、性能、管理员页面review仍须实施后逐项验收，P5继续以P4验收通过为前置。

本轮执行登记（2026-11-01）：管理员已授权按LLD§21顺序实施P4第1—5步；第1—4步代码及定向工程测试已完成，详见§21.10；第5步已执行部分日线核验并因客户端错误停止，分钟未执行，第6步由管理员执行。本轮不提交、不部署、不进入P5。

P4继续实施口径（2026-11-01，管理员已确认）：保留现有debug切换引起的普通行情重请求，不修改useIndexDetailController，不从普通行情参数中删除debug。允许短暂加载、图表重建及缩放/拖动位置重置、右栏回到基本行情。旧研究控制器卸载时取消请求、清定时器和内存；重新进入debug仅恢复手动入口，不自动重新计算波段。仅辅助模块加载成功/失败/手动重试或同数据扩展更新、不改变URL时，不额外触发普通行情加载。
此调整只改变P4第2—3步及对应测试/第6步页面预期；第1步环境隔离、第4步工具封闭请求组、第5步各次HTTP/计算预算及正常/debug同源一致性均不放宽。工具不新增模拟URL切换或整页重刷轮次；同次请求仍不得重复读取、旧回包不得覆盖新状态。模块加载中/失败时，有行情且资格成立的r4请求使用普通0模式；整个页面正处于原加载状态时不为凑普通请求额外发送识别或预测。模块ready后才可发送1。
第4步工具定向回归已完成；第5步沿现有prod日线连接开展真实只读核验后，已按首次失败停止。已测HTTP/计算耗时未超限，失败发生在2026-10-27日线debug预测的客户端处理，具体校验点尚未定位；不重试、不自行提高阈值或修改代码。分钟未执行，第6步由管理员执行，P5未推进；本轮未提交或部署。

### 21.10 P4开发及限定工程验证记录（2026-11-01）

本节登记本次实际工作。第1—4步工程结果不能扩大为第5步真实来源或第6步页面验收通过。工作区其他既有修改保留，未提交、推送、部署、安装、重启服务或进入P5。

| 约定/用例 | 实际实现及测试 | 结果与证据范围 |
|---|---|---|
| 第1步，P4-01—04/38 | src/app/api/v1/router.py的_xxm_local_environment_enabled/_include_local_xxm_routers；tests/web/test_wealth_index_detail_xxm_local_routes.py | 显式dev/local才注册四项能力；同一Settings解析分钟root、无重复注册。正式/api→/v1聚合生产404/OpenAPI无能力且零源调用；分钟关闭时真实日线query仍可用，原401/403和普通K线debug省略/0/1及非法/重复参数保持。SQLite是按真实ORM的人工来源，不是正式行情 |
| 第2步，P4-05—11/16 | debug/useIndexDebugModule.ts及测试，Page/现client、Hook/decoder测试 | 仅资格成立时动态import，loading/error保持0，ready统一1；序号/卸载/StrictMode及重试防迟到。URL debug切换保留普通行情重请求、加载及图表重建，右栏回基本行情；同URL仅模块状态变化不另重刷。合同错不降级 |
| 第3步，P4-12—18/31 | chart/indexChartPointAdapter.ts及字面测试、IndexDetailPage.tsx及测试、IndexRecognitionDebug.test.tsx、dependencyBoundary.test.ts | 纯转换唯一；研究owner匹配、普通日期独立；离开debug取消旧研究，重新打开仍须手动。主图m5/m90不改变合法四行预判资格。原四种三角、1000根及图表/九转回归继续执行；布局与浏览器网络留第6步 |
| 第4步，P4-19—27/32—40 | 原xxm_page_request_audit.py/.mjs及xxm_forecast_display_audit.py，主题test_xxm_p4_audit_tools.py；daily_window_precheck.py及原测试 | CLI只四参数；真实TS client/decoder/adapter和原scheduler，用人工运输层验证四周期、两模式、单/双页与20次计数；实际ASGI→同步线程、SharedLoads、原缓存方法和分钟pair子线程验证编号/一次调用。无旧candidate/output/采集CLI，无业务结果写盘 |
| 工具计时和失败退出，P4-22/24/27/33—35/39—40 | 同一主题工具测试、既有forecast API和SharedLoads测试 | 真实400ms起点观察保持原check；失败保留已知耗时、HTTP200解码错仍error、无成功P95。started/终态/EOF/超限/错编号反例；真实临时HTTP服务线程和Node卡住，由外层原50/58/59/60秒规则结束自己的进程组，测试加速监督时钟但不mock清理成功；部分初始化失败恢复已登记包装。权限错误不当作无残留 |
| 第5步，P4-26/28/39真实部分 | 来源已明确；部分day已执行，结果见§21.11 | day因历史debug预测客户端失败未整体验收，m60/m90/m120未执行。已有数量/耗时只记录实际日线结果，不替代失败或未执行项；未重新请求、改阈值或修改代码 |
| 第6步，P4-29/30 | 由管理员更新既有服务并按§21.7检查 | 待管理员浏览器验收；生产build通过不等于静态页面网络已核验。未调用浏览器代验，未把临时端口当交付服务 |

本次执行命令与结果：

- `.venv/bin/python -m pytest scripts/research/index_market/tests/test_xxm_p4_audit_tools.py scripts/research/index_market/tests/test_xxm_daily_window_precheck.py -q --disable-warnings`：121通过。人工来源、真实TS客户端及受控本地HTTP/线程/进程；不读正式DB/Lake、不重跑历史对比。
- `.venv/bin/python -m pytest tests/web/test_wealth_index_detail_xxm_local_routes.py tests/web/test_wealth_index_detail_xxm_api.py tests/web/test_wealth_index_detail_xxm_forecast_api.py tests/web/test_wealth_index_detail_api.py::test_kline_1000_limit_returns_latest_ordered_rows_preserves_overlap_and_default tests/web/test_wealth_index_detail_api.py::test_all_index_detail_request_errors_use_frozen_400_code tests/web/test_index_detail_minutes_api.py tests/web/test_wealth_index_minute_nine_turn_api.py -q --disable-warnings`：初轮133通过；新增K线debug合同节点后单独重跑test_wealth_index_detail_xxm_local_routes.py，14通过。真实API装配及人工ORM/分钟来源，不是正式来源时延成绩。
- `npm --prefix wealth run test -- --reporter=dot`：185文件，1405通过、1失败；失败为trading-assistant/model/useRecords.test.ts:35。2026-11-01默认筛选的开始/结束均为11月1日，测试把开始改为结束仍是同一筛选，却要求清页码；该文件及模块不属本批且无本批改动。已单独复现，未改预期、未skip、未算全绿；P4页面及相关定向测试通过。
- `npm --prefix wealth run typecheck`、`npm --prefix wealth run build`通过；生产构建未生成IndexRecognitionDebug独立块。真实生产静态页是否无DOM/请求仍由第6步验证。
- `.venv/bin/python -m pytest tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_platform_legacy_guardrails.py tests/architecture/test_operations_legacy_guardrails.py -q`：16通过；原test_xxm_shared_loads.py定向3通过。本次修复未改变业务层/来源模块，未重复扩跑。check_docs_integrity三项、限定改动git diff --check及四份文档146处本地文件链接检查通过；CodeGraph sync/status确认索引已更新。不运行旧研究整目录，不安装依赖。

独立代码审计已沿Settings→正式注册→页面资格→模块ready/effectiveDebug→原client/deadline→普通/研究日期与owner→工具真实观察→退出逐项重查；CodeGraph codegraph_explore用于页面加载/预测/控制器、App路由及相关消费者，并直接读当前实现补足图谱未索引的测试。未改变识别/预测规则、源SQL、Reader、公开合同或普通行情controller。监督发现的退出竞争和失败记录遗漏在同一LLD约定下修复并补回归；未以删检查或改预算消除失败。

结论：第1—4步代码及限定工程验证完成；第5步真实验收未通过、第6步页面验收未执行，故P4整批尚未验收通过，不能进入P5。完整前端回归的范围外失败按§21.10.1暂记TODO，不作为第5步开工前置，也不改写为完整回归已通过。第5步沿现有prod日线连接及本机正式Lake继续使用本节既定工具和预算，不再等待来源拍板，不新增执行入口或自动重放；当前按§21.11停在首次客户端失败，未重试或修改代码。

提交交接（2026-11-01）：管理员已授权提交本轮P4第1—4步代码、测试及配套文档。仅提交本轮明确内容，同文件中既有的其他未提交改动保留；不推送、部署或进入P5。第5步真实来源及性能验收、第6步管理员页面验收及范围外前端测试失败的状态不因提交而改变。

#### 21.10.1 范围外前端测试TODO（2026-11-01，管理员决定暂缓）

发现于2026-11-01完成P4第1—4步后的首次完整Wealth回归，随后单独复现；最终完整回归为1405通过、1失败，原成绩保留。对应wealth/src/features/trading-assistant/model/useRecords.test.ts:35，不是本轮来源纠正新增的问题。用例从defaultRecordFilter()取当月日期，再把start改成end以测试日期改变后页码归零；11月1日默认start/end同为11月1日，实际筛选没有改变，却要求页码归零，因而失败。

管理员已决定暂记TODO，本轮不修业务或测试代码，不改预期、不skip，不宣称完整回归全绿。该项不属于r4识别、预测、核验工具或其来源，不作为P4第5步的开工前置；后续单独安排处理，本节不提前规定修法。第5步的四周期真实来源、性能、读取次数及失败退出仍须按原LLD验收，第6步仍由管理员进行页面review，不能用本TODO替代这些要求。

### 21.11 P4第5步执行登记（2026-11-01）

管理员已授权按本LLD执行第5步，并明确要求性能指标首次不合格即停止汇报，由管理员决定是否调整阈值。沿用现有.env.web.local及§21.6来源，不改代码、配置、SQL、Reader、预算或其他TODO；不执行第6步浏览器、不提交或进入P5。

首个实际入口为xxm_page_request_audit --periods day --mode both --samples 1，省略as-of保持latest；按§21.5.1正常顺序执行普通单页、普通双页、辅助单页、辅助双页，每组新子进程/空产品缓存。全部成功时该CLI恰24次业务和12次私有请求；失败组保留实际数量，不补齐、不重试，整次后续任务停止。实际执行结果见下表；已在首个失败组停止。

首组成功后，按day→m60→m90→m120逐周期继续：同周期forecast工具samples=20/both；页面工具samples=20/both；显式as-of=2026-10-27的页面samples=1/both历史核验。分钟每周期先执行latest页面samples=1/both，价格/指标20次仍分组。每条命令只遍历其显式周期，不另加预热、旧矩阵或实际算法回测。一个性能/来源/合同/通信/清理失败即停止所有尚未执行的命令，不以另一日期或成功样本抵消。

来源白名单：core_serving.index_factor_pro只000001.SH，r4投影trade_date/close/macd_dif_bfq/macd_dea_bfq/macd_bfq，原批1000/前缀最多20000根；主图仍使用IndexDetailQuery.KLINE_COLUMNS已有OHLC、量额、MA/BOLL/MACD/KDJ列，limit1000。core_serving.index_nineturn_daily只同代码和窗口，读取close/up_count/down_count/nine_up_turn/nine_down_turn/formula_version，原分页多取1根探测；core_serving.index_basic只同代码的名称/市场/发布者/类别；core_serving.index_daily_serving只同代码最新日期聚合；core_serving.trade_calendar只SSE原日期/开市标记/前交易日及必要日期聚合。分钟仅正式根的该代码bars/indicators和原九转所需投影，原20000根/5000分区上限不变。没有跨代码明细读取、导出或补算源MACD。

所有SQL沿原只读事务，临时App关闭lifespan，仅本组临时端口和进程。父子核同一Settings，原4秒请求/400ms计算/5秒客户端、日线20次P95≤800ms、组50秒工作/60秒含清理保持。真实网络/进程操作使用获准权限；不在受限环境盲试或安装依赖。工具摘要只经内存和终端传递，不保存行情、完整结果、恢复文件或业务响应；文档仅登记参数、实际日期/行数/字节/耗时、读取次数和结论。

#### 第5步本次实际结果：日线客户端失败，后续全部停止

四条命令均使用现有.env.web.local、同一已提交工具和原阈值，未加包装入口、预热或重试；合计11组、119次业务请求，10组完成、1组失败。

| 顺序 | 已执行命令参数（模块名省略共同前缀scripts.research.index_market） | 实际结果 |
|---|---|---|
| 1 | xxm_page_request_audit --periods day --mode both --samples 1 | 4组/24次业务请求完成；普通/辅助单页及双页均通过，公共结果6对相等，双页共享加载两组验证通过 |
| 2 | xxm_forecast_display_audit --periods day --mode both --samples 20 | 普通/辅助各20次，共40次完成；公共结果20对相等；HTTP P95分别638.521ms/1024.198ms，此接口不使用K线800ms预算。预测缓存命中路径未验收 |
| 3 | xxm_page_request_audit --periods day --mode both --samples 20 | K线普通/辅助各20次，共40次完成；P95分别255.598ms/225.082ms，均低于800ms |
| 4 | xxm_page_request_audit --periods day --as-of 2026-10-27 --mode both --samples 1 | 普通单页4次、普通双页8次完成；辅助单页实际发3次后forecast客户端错误，该组未发送signals，辅助双页未开始。整条命令非零退出，后续所有命令取消 |

实际latest截至2026-10-30：图上1000根，窗口2022-09-09—2026-10-30；r4前缀4084根，2010-01-04—2026-10-30。历史普通组截至2026-10-27：图上1000根，窗口2022-09-06—2026-10-27；r4前缀4081根。主图和识别通过真实TS适配的原值逐根匹配；不据此宣称历史辅助预测已通过。原HTTP/计算/缓存及响应上限未改；已取得r4完整HTTP最大1.311705秒，已取得客户端完成耗时最大1.313441秒，预测计算最大113.515ms，最大本组缓存3340569字节，均未超过对应上限。失败请求的客户端完成耗时未知，不能填0或列为成功。

首个失败发生在2026-10-27日线forecast、debug=1：groupId=fddf322945ba4f218cd142ae405c0dec，requestId=fddf322945ba4f218cd142ae405c0dec:mixed_single:1:1:3。HTTP200，正文8749字节，完整正文HTTP1.217690秒，计算61.696ms；内部dataStatus=READY，预测缓存read=miss/1、write=stored/1，但客户端terminal=error、clientSeconds=None。这些已测值未超4秒/400ms/32KiB；尚无客户端完成结果，不能宣布该路径5秒合同通过。Node只返回stage=client/errorType=Error，未保留具体异常文本或业务正文，暂不能确定是哪条客户端校验失败，也不能认定调整性能阈值会解决。

该请求sourceInputId=bdd86f562c5eac15b6cd770dacc5ac6d29956e8335fe9d96c6d88fd21c93f8c6，calendarInputId=58c6e39a993d7b2aaa8b4935bad7100b11ed3d102c73b7655e7887a4c4edfb57，仅保留来源身份供后续核对，不保存行情、完整响应或恢复文件。工具已等本组请求/线程结束并回收本组进程，活动请求0后以失败退出；未把cleanupStatus=failed误写成成功，亦未据此声称后台计算或HTTP超时。

| 周期 | 本次验收状态 | 实际证据与未覆盖 |
|---|---|---|
| day | 未通过，首次客户端失败后停止 | latest单/双页及两个20次组已完成；历史辅助forecast失败，历史辅助signals/双页未执行；尚无成功预测缓存hit，不冒充冷热路径完整验收 |
| m60 | 未验收 | 因上述失败未启动，没有真实请求或Lake读取 |
| m90 | 未验收 | 同上 |
| m120 | 未验收 | 同上 |

停止结论：本次没有已确认的性能超限，实际阻断为历史日线debug预测客户端处理错误；未经管理员review，不重发该请求、不重跑采样、不改阈值、不修代码。后续建议先限定排查该响应与客户端校验的交接，查清具体错误后再决定修复及恢复验收。第6步页面review及P5均未推进；范围外交易助手日期测试TODO保持暂缓。

### 21.12 首次客户端失败的限定诊断（2026-11-01）

管理员已授权“先排查问题，看看到底什么原因”。本步仅定位§21.11失败原因，不修业务、不恢复第5步采样、不改阈值、不推进分钟/页面/P5，不提交。原119次采样和失败记录保持；本次单独登记为诊断，不能补成原失败组成功。

1. 当前代码依据：xxm_page_request_audit.mjs的失败摘要只输出stage/errorType，未保留异常文本/栈或原响应，故现有记录不能确定adaptForecast/decodeForecastDebug的哪项检查失败。daily_window_precheck.isolated_client会替换存储、时钟和鉴权，不能用于本次真实来源定位。不得为诊断改产品检查、吞异常或伪造错误字段。
2. 一次读取：仅000001.SH、period=day、asOf=2026-10-27、debug=1的xxm-key-point-forecast；使用原.env.web.local和xxm_page_request_audit.isolated_app，保留正式路由/鉴权/只读会话/原观察计数/临时App清理。继续使用§21.6/§21.11白名单：index_factor_pro仅trade_date/close/macd_dif_bfq/macd_dea_bfq/macd_bfq，SSE日历原字段；本次前缀预计4081根、日期2010-01-04—2026-10-27，原20000根/1000批次上限不变。无K线、九转、signals、分钟或额外日期读取，不替换来源，不预热、不重试。
3. 临时诊断代码只放/private/tmp，不新增维护入口或参数。后端直接复用原隔离App；Node使用现有esbuild的write:false编译真实fetchForecast及decodeForecastDebug，执行原调度和5秒客户端检查。只在fetch观察层保存同一次HTTP正文于内存；异常时从栈取函数/编译行及相邻源码注释定位真实文件。仅输出白名单摘要：HTTP状态/bytes、异常类型/合同消息/相对代码位置、预测状态、选峰信息、价格范围及需要解释错误的有限字段。不得输出完整响应、编译data URL、凭据或连接字符串。
4. 父进程以独立进程组运行诊断worker，沿原50秒工作/60秒含退出预算；超50秒仅中断本组、58秒TERM、59秒KILL、60秒前回收。子进程/输出管道有界，输出最多64KiB；异常或超限停止，不重试。App退出等待原请求/线程，释放原连接池/监听；失败不遗留服务，不影响现有服务。原4秒HTTP/400ms计算/5秒客户端和32KiB响应限制不放宽；本步不测P95或宣称性能验收完成。
5. 原响应只在内存传递，不落盘行情、正文、结果或恢复文件；已捕获同一正文可离线复核原校验及生产端，不再读DB。真实诊断前核对临时代码、语法与边界，诊断后追到生产字段/客户端断言/现LLD和测试，分别说明根因、影响及建议，不直接修复。只将必要错误证据记回本节和原方案，完成文档完整性及限定差异检查。

诊断过程限定调整：首个临时worker非零退出，未返回有效摘要，无法据此确认是否已请求到业务正文，不能计为成功或零读取。随后完成零业务请求的App装配检查及人工替身下的实际客户端编译/错误定位检查。静态发现无上限范围的前端空值递减错误；为确认原失败是否触发此项，最多追加一次相同预测读取，先输出有界错误证据，再收指标和清理结果，失败停止。仍不恢复原采样或修业务，诊断不并入原119次采样。

#### 21.12.1 已定位原因及影响（仅排查，未修复）

确认读取groupId=2f551cbc74b140d2ad0aaa3c524689ef，唯一业务请求为day/asOf=2026-10-27/debug=1的forecast。HTTP200、8749字节、完整正文1.504168秒，后端计算62.417ms；读取前缀4081根，起止2010-01-04—2026-10-27。sourceInputId、calendarInputId及publicDigest均与§21.11原失败请求相同。HTTP及后台计算有成功记录，但实际TS客户端仍报“顶底识别数据与合同不一致”，不将HTTP成功记作客户端通过。活动请求0，本组App/连接池/进程已关闭；没有额外日期或分钟读取，也没有正文/结果文件。首个临时诊断进程未取到读取证据，保留其未知状态，不虚构精确累计读取数。

实际错误位置：debug/forecastDebugContract.ts的range()显示整数检查（第53—57行）。后端真实条件STRUCTURE_FORMED_AND_FOLLOWING的一段为lower=3779.307688860061、upper=null、lowerInclusive=true、upperInclusive=false、displayLower=3780、displayUpper=null。这正是§5.4及§6.6允许的无上界确定范围，含义是收盘不低于该下界，整数展示从3780开始，没有有限上限；并非“范围内没有整数”。该字段只用于定位本次校验错误，不能把单独这一段摘出作为完整下一根判断建议。

错误过程：前端先令hi=null表示无上界，随后仅判断hi===raw.upper且上界不包含，漏了hi非空检查。两者都是null、upperInclusive=false时也进入递减；TypeScript中的hi!不是运行时空值保护，编译后是hi--，JavaScript把null减1得到−1。于是lo=3780大于hi=−1，错误进入“没有合法整数”的分支，要求displayLower和displayUpper都为null；后端正确给出的3780被拒绝。实际异常栈已确认range→ranges→decodeForecastDebug→adaptForecast→sendForecast，与上述分支一致。

生产端forecast_math.py:display_range已在递减前检查high is not None，人工同边界输入独立核对得到displayLower=3780/displayUpper=None，与源响应及本LLD一致。问题位于前端辅助预测解码，不是数据库来源、EMA、r4识别/预测范围计算或性能超限。普通debug=0不进入该解码；debug=1一旦出现无上界的确定范围就可能整行报错，而不仅是隐藏辅助详情。日线和60/90/120分钟共用该函数；本次未读分钟源，已用人工合法范围在四周期实际解码中复现相同拒绝。

漏测原因已核对当前测试：forecastFixtures.test-support.ts的正常辅助样本仅有闭范围[2,175]；r1Contract/apiClient测试及P4工具受控HTTP测试复用这个样本，已有错误字段/超时反例没有覆盖合法upper=null的正例。离线以现有真实解码器检查四周期：原有界样本4项接受，手写合法无上界范围4项均被错误拒绝；这只证明共同校验缺陷，不算分钟真实来源验收。

建议后续最小修复：只在前端上界递减前明确要求hi!==null，空值始终保留无上限含义；有限开/闭边界的整数取整及原拒绝规则保持。补独立字面用例覆盖无上限（小数/整数下界及开/闭）、有限上界开/闭、范围无整数、合法单点和错误展示整数；同时覆盖普通条件及structureFollowConditions复用路径、四周期和真实fetchForecast消费。不要改后端价格范围、选峰/标签、Spec/版本、缓存、来源或超时来绕过。

本轮到此停止：仅诊断和文档登记，没有修改产品或维护工具代码，没有恢复第5步采样。后续须先把获准修法及测试落点补成执行要求，再编码并针对性验证，随后再安排原失败路径及剩余P4验收；不把本轮诊断当作修复或整体验收通过。

### 21.13 历史：无上界前端校验修复、提交与2026-11-01续验

管理员已批准“修复，然后提交，继续推进P4第五步”。本步依§21.12.1根因修复，完成修复提交后再恢复真实验收。只在当前dev-interface工作区；不改后端/算法/预测点位/Spec/DTO/缓存/配置/SQL/Reader，不安装，不动范围外交易助手日期TODO、不推送部署、不进入第6步或P5。上一轮失败和诊断保留为执行事实，不用成功覆盖。

#### 21.13.1 代码要求及测试先后

唯一产品改动：debug/forecastDebugContract.ts:range()将上界递减条件明确为hi!==null && hi===raw.upper && !raw.upperInclusive；执行hi-=1。只有真实有限且恰为整数的开上界才减1；upper=null时hi持续null，沿原合法整数检查。其余字段、开闭、精确范围、排序/重叠/引用/表达式/时限检查全部保持；禁止放宽校验、改后端值或重算范围。普通conditions与structureFollowConditions仍共用该函数，不复制算法。

新增debug/forecastDebugContract.test.ts，复用已核实合同样本的身份/时间外壳，输入边界与期望全部写字面数值，不调用被测函数或后端取整函数生成预期。跨day/m60/m90/m120及普通条件/旧结构跟踪条件各自运行：

| 类别 | 独立输入与预期 |
|---|---|
| 实际缺陷 | [3779.307688860061,+∞)，upper=null、upperInclusive=false；displayLower=3780、displayUpper=null，必须接受 |
| 无上界下限 | [4000,+∞)→4000/null；(4000,+∞)→4001/null；(4000.2,+∞)→4001/null |
| 有限边界 | [2,175]→2/175；(2,175)→3/174；(2.2,175.8)→3/175 |
| 无整数/单点/零 | [2.2,2.8]→null/null；[3,3]→3/3；(0,2]→1/2 |
| 错误值必须拒绝 | 无上界却给有限displayUpper或把两显示值都置空；upper=null且upperInclusive=true；开整数下界未加1/上界未减1；有整数却置空、无整数却给数字、缺展示字段 |

旧结构样本独立给出合法originWave/日期/原结构编号，不能通过只测普通conditions冒充共享路径覆盖。apiClient.test.ts补四周期fetchForecast→adaptForecast→decodeForecastDebug的无上界样本，真实调用本地客户端与解码器、只替代HTTP正文，断言3780/null被保留，不重置5秒截止。

先只新增测试，运行实际缺陷对应节点，记录修复前拒绝合法样本；再改上述唯一条件。执行新边界全组、原forecast/debug相关组、现有P4工具回归及Wealth typecheck/build，单组最多60秒，超过先停止查因。完整前端范围外TODO不修改、不重复扩大测试，也不声称全量Wealth通过。独立审计对账：一处产品修正、字面正反例/两共享路径/四周期/客户端交接、原校验未放宽、无后端和来源改动。文档完整性、链接和限定diff通过后提交明确文件，包括本轮原三文档及诊断记录；不夹带其他工作区改动。

#### 21.13.2 当时续验的执行归属

本节7bf8eb823修复后的2026-11-01续验已实际执行，命令、源范围、64次日线成功及首个m60失败统一保留在§21.13.4。该历史流程已结束，不是新的执行入口；此前全历史分钟范围及缺命中自动补20次的指令删除。当前续验只依§21.14的N+1000范围、固定请求清单和首错停止，不补发历史失败轮的余量，不重跑已适用日线样本。

#### 21.13.3 修复完成与提交前独立审计

唯一产品变更已落在forecastDebugContract.ts:range：显式排除hi=null后才递减；无上界值不变，原有限开/闭边界及其余合同校验未改。新增forecastDebugContract.test.ts的18组独立边界跨两路径/四周期共144项；apiClient.test.ts新增四周期真实客户端解码回归。原r4后端、工具、Spec、来源及缓存代码无改动。

验证事实：先仅新增测试并定向选实际失败样本，修复前8项均因同一合同错误失败，其他136项仅因定向选择未运行；修复后执行forecast/debug全组，10文件182项全部通过（含新增144项及原客户端共7项），无跳过。原P4工具及daily_window_precheck共121项通过；Wealth typecheck/build均通过，构建保留既有大包提示，不在本任务调整构建。文档完整性3项与限定diff检查通过。上述客户端/工具测试以人工HTTP/受控来源隔离，不当作真实源验收；原完整Wealth的范围外日期TODO不改，未宣称完整回归全绿。

CodeGraph explore已核对fetchForecast→adaptForecast→decodeForecastDebug→range、普通/旧结构条件及后端display_range边界；人工检查两共享入口仍调用同一函数，测试正例能通过、错误展示及开闭仍拒绝，未改API字段或依赖方向。配置只读复核仍为显式local、原prod日线、正式本机Lake及分钟启用，没有改.env。结论：修复及限定工程验证符合§21.13.1，可按管理员授权提交六个明确文件，再执行§21.13.2真实续验；截至本条登记尚未恢复采样，不把即将执行登记为已通过。

#### 21.13.4 提交与续验实际结果：60分钟识别首次超时后停止

修复及原三文档/诊断记录已按明确六文件提交7bf8eb823（fix(wealth): accept unbounded forecast debug ranges），未推送或部署。其后仅使用原两CLI继续本节已批准顺序，现有.env.web.local来源未变，没有重跑已适用的latest日线采样。新执行3条命令、7组、68次业务请求，6组完成、1组失败；与§21.11原119次及§21.12诊断分开登记，以下数字不含临时诊断。

| 顺序/原模块命令参数 | 组/请求与实际结果 |
|---|---|
| xxm_page_request_audit --periods day --as-of 2026-10-27 --mode both --samples 1 | 4组24请求全部成功，原历史debug失败路径已通过；普通/辅助公共字段6对equal，两个双页组sharedLoadCoverage=verified，组均cleaned/activeRequests=0 |
| xxm_forecast_display_audit --periods day --as-of 2026-10-27 --mode both --samples 20 | 2组40请求全部成功；两模式各1次miss+stored、19次hit且不重复写缓存；20对公共结果equal。HTTP P95普通1.316020秒、辅助1.112785秒，预测不套日线K线800ms |
| xxm_page_request_audit --periods m60 --mode both --samples 1 | 第一组普通单页实际发4请求后signals超时，命令exit=1；预测请求未实际发送，后续普通双页/debug组均未开始。全部尚未开始的命令停止，无重试 |

本次day图窗仍1000根/2022-09-06—2026-10-27，识别/预测前缀4081根/2010-01-04—2026-10-27。sourceInputId、calendarInputId及公共摘要与原失败诊断一致；预测普通正文1846字节、辅助8749字节。64次日线请求最大HTTP1.446828秒、已有客户端完成最大1.447032秒、预测计算最大214.519ms，均在原预算内；缓存峰值3340569字节。原latest日线K线20次P95/800ms已通过的证据沿用，不重复请求或混为本次历史预测P95。

首个失败groupId=87ffbe47da7f4565b5a09018f40af12e，requestId=87ffbe47da7f4565b5a09018f40af12e:mixed_single:1:1:4，周期m60、普通模式、latest实际目标2026-10-30。此前同组主图和指标均返回500根，窗口2026-04-27T10:30:00+08:00—2026-10-30T15:00:00+08:00；主图HTTP0.810835秒/113683字节、指标1.441110秒/316653字节、九转0.885822秒/56911字节，均HTTP200。分钟这些耗时按原合同记录，不以日线800ms否定。

失败signals实际HTTP503，正文137字节，完整HTTP4.174313秒，errorCode=XXM_BUDGET_EXCEEDED；后台对应load-1耗时4.120946秒并以error结束，seriesCacheRead=miss/1、pairCalls=1、barsCalls=1、indicatorCalls=1、signatureChecks=2，活动请求0、缓存0。工具已完成本组请求/线程及自有进程清理后非零退出，没有仍运行的采样组。客户端错误类型DOMException与真实503/错误码分别保留，不用客户端类型代替后端预算错误。

准确边界：load-1包围query_service._load_series整段，包含日历/来源读取、校验、逐根建立识别状态及发布前检查，不仅是磁盘读取。现有摘要未把这些内部阶段分别计时，因此只能确定“建立该分钟周期历史计算进度时超出识别4秒”，不能认定全是Lake慢或已完整算完。4.174313秒是失败响应耗时，不是完整成功耗时；本次没有成功识别前缀/条数/来源身份及预测计算耗时，不补写估算或0。该load内记录到的一次pair及各一次bars/indicators未显示重复调用，不据此宣称全部分钟链已验收。

| 周期 | 续验状态与剩余 |
|---|---|
| day | 原失败修复已通过，历史混合及预测冷热已补齐；原latest/K线证据沿用。浏览器仍未验收 |
| m60 | 未通过，首个普通单页signals4秒超时。其余单/双页/debug、预测20次、价格/指标20次及历史组均未执行 |
| m90 | 未验收，因首次超时未启动 |
| m120 | 未验收，同上 |

停止结论：修复已提交，日线真实失败路径及冷热回归通过；P4第5步整体尚未通过。按管理员要求首次性能失败即停止，未放宽4秒或400ms、未优化/重试、未换来源、未保存业务结果；新实际验收记录只同步回原三文档，留作未提交交接。下一步需管理员review分钟识别4秒限制或另行限定诊断；不得未经确认自动继续。第6步仍由管理员执行，P5未推进，范围外日期TODO未变。

### 21.14 当前P4剩余计划：工具检查、正式续验、页面review及收尾（2026-11-02）

本节是当前P4第5—6步的唯一剩余执行安排，依据产品§10.6、技术方案§23、专项§17。第1—4步已完成，不重新实施；性能优化第4—7批按§0.11暂缓，不作为本节前置。本节为执行设计；工具补齐已按§21.14.10完成，正式命令和页面的实际结果只按该条后续记录，不提前登记通过。§0.10.9仅是4次m60正常latest的限定成功，不能抵扣本节真实TS客户端、双页、debug、历史及20次样本。P5不在本节开发/执行授权内。

#### 21.14.1 先后步骤、范围及交接

| 顺序 | 目标与具体产出 | 后一步进入条件/停止位置 |
|---|---|---|
| 1 设计及开工审计 | 原四文档统一N+1000/预算/既有日线证据/固定命令/失败停止，审计现有工具记录能否核新范围 | 本节及专项§17已review，后续取得工具编码授权；本轮停在文档交付 |
| 2 工具范围检查补齐 | 仅按§21.14.2改原Python验收器及原测试文件，限定回归和独立审计 | 1501根反例能失败、合法短源/合法预测可通过；参数/字段/任务数/产品实现不变，才能准备真实续验 |
| 3 续验准备 | 按§21.14.4核当前代码、配置、依赖和证据适用性，明确首个周期m60及4条固定命令 | 无未处理问题，取得该周期真实执行授权；没有准备性行情请求 |
| 4 正式第5步 | m60→m90→m120，各按§21.14.5四命令顺序；每周期独立报告 | 一个周期全部合格后向管理员交结果，再按后续授权进入下一周期；真实失败或其他必需覆盖不足停在本周期；仅未发生并发共享不阻塞。未获整批授权时不自动跑三个周期 |
| 5 第6步管理员页面review | 三分钟周期与日线证据对账齐备，按§21.7及§21.14.8交真实本地页面验收 | 管理员review通过且最后独立审计通过，才能登记P4完成；不能用自动工具代替页面 |
| 6 收尾 | 更新原四文档：周期证据、规则/预算、已覆盖/未覆盖、TODO和实际提交状态 | 交管理员review并停止。P5引用审计/删除、部署和生产开放仍需后续计划及指令 |

本轮第2步代码白名单仅`scripts/research/index_market/xxm_page_request_audit.py`与同目录`tests/test_xxm_p4_audit_tools.py`。两个CLI、原mjs、API/DTO、source/query/Reader、r4核心/Spec/EMA/缓存及页面不改。不新增统计字段、运行器、配置、用户参数、预热、后台任务、结果/恢复文件、源码SHA检查或源文件扫描。若实施发现需要扩大白名单，先说明原因并更新原方案/LLD，不能自行改。

#### 21.14.2 现有工具缺口及代码级修正

当前`AuditCollector.projected`已从实际`SeriesEntry.processed`与`computedThrough`取得`prefixRows`；`_observe`已观察实际loader/两源/缓存/400ms时钟；mjs已执行真实TS client、解码、主图逐点适配和最后deadline检查。问题仅在`validate_summary`未把分钟实际1500根作为成功前提：即使记录1501根，原验收器也可能判通过。不能只看响应500根，不能用20000根保护替代1500。复用这些已有记录，不再读数据、复制计算或增加观测。

在原Python模块新增私有纯函数`_validate_minute_r4_prefix(row)`，由`validate_summary`在原字段集合、身份、HTTP/terminal和r4字节/时限检查之后、组通过之前调用。确定逻辑如下：

1. `row.period`不是m60/m90/m120，或`endpointKind`不是signals/forecast，直接返回；普通K线/指标/九转及日线不新增此限制。
2. 当前正式分钟验收要求`dataStatus == 'READY'`；EMPTY/DELAYED虽可能是合法产品响应，本轮目标未验到，抛`ValueError`停止，不改产品返回或伪造READY。
3. `prefixRows`必须`type(value) is int`、`0 < value <= BUDGET.response_default_minute + BUDGET.source_extra_rows`，当前即1500；拒绝bool、None、字符串、零、负数、浮点和超限。`sourceInputId`、`computedThrough`必须为非空字符串，用既有字段证明成功来自真实已完成输入，不另查源。
4. signals的`responseRows`必须严格正整数且≤`BUDGET.response_default_minute`（500），同时≤`prefixRows`；允许不足500/1500，不强求恰500或恰1500。`windowStart/windowEnd`仍是返回窗口，不改成整个计算前缀。
5. forecast的`responseRows`保持合法None，不当作缺失K线；READY分支在当前`forecast_query_service.build`必创建计算deadline，因此`computeSeconds`必须是非bool的int/float、有限且`0 <= value <= .4`。已有§21.5.4起终点不改；缺值不能当作400ms已验收。NO_CANDIDATE或PRECISION_PENDING可以合法通过，不要求非空target/calendar、不要求一定有普通价格解；缓存和校准覆盖另记。
6. 只抛无凭据/无正文的短`ValueError`，不静默修值、截断记录或重试。沿原worker失败摘要和监督退出；失败记录中1501根等真实值保留用于说明，不能在`_validate_failure`再按成功门槛把证据删掉。现有逐请求/组错误、P95和最终cleanup校验继续执行，不放宽其他合同。

不根据`responseRows + 1000`反推本次准确读取上限：signals返回数可能因startDate等筛选少于请求limit；当前正式工具只请求≤500，统一核≤1500即可。N=1/500/2000、实际raw/step/文件/SQL范围已由§0.9.7/10隔离测试证明；本步不重复引入字段或再次读取来验同件事。预测默认N=500，页面signals的limit来自真实主图points数量，不能强改为500去造共享命中。

#### 21.14.3 工具限定测试设计及独立审计

所有新增/调整用例放原`test_xxm_p4_audit_tools.py`；小样本和预期写字面值，依据runtime预算、当前collector生产字段及§0.9已核实际合同，不由新校验函数生成expected。区分“正常产品状态合法”与“本轮已完成性能验收”。新增私有函数可直接测，但关键样本还必须进`validate_summary`的完整合法任务摘要，不能因组请求数/早先错误提前失败而假称抓住1501根。

| 用例编号 | 输入/实际边界 | 独立预期及落点 |
|---|---|---|
| P4-R01 | 三分钟周期×normal/debug，signals前缀1500、返回500；forecast前缀1500、READY、compute .4 | 全部接受；实际完整请求/组形状不变 |
| P4-R02 | 同一合法摘要仅prefixRows改1501，返回仍500 | 原工具可接受该摘要，新工具必须因前缀超限拒绝；先记录修复前失败，再实现修正 |
| P4-R03 | 前缀400、signals返回400，或前缀1001、返回1 | 接受短源；不能错误强制1500或把返回1当作最多1001的通用证据 |
| P4-R04 | prefixRows为None/True/0/−1/1500.0/'1500' | 全部拒绝；与正整数1/1500对照，不误拦合法变化 |
| P4-R05 | sourceInputId/computedThrough缺失或空串 | 在READY完整摘要中拒绝；不调用读源函数补字段 |
| P4-R06 | signals返回501/0/None/True/浮点，或返回数大于前缀 | 拒绝；1/500和小于前缀正常接受 |
| P4-R07 | 分钟r4的EMPTY/DELAYED响应 | 本轮未验收，工具失败并停止；产品状态及原API测试不改 |
| P4-R08 | READY forecast，responseRows=None，NO_CANDIDATE无普通范围；或PRECISION_PENDING无target/calendar | 计算耗时有限合格时接受；不要求目标/缓存hit、不伪造0 |
| P4-R09 | READY forecast compute=None/True/NaN/Inf/负数/.400001 | 全部拒绝；0/.4接受；原HTTP4秒及client<5秒独立边界仍测 |
| P4-R10 | 日线前缀4084，合法无计算deadline路径compute=None；分钟普通图/指标/九转prefixRows=None | 原行为不变，不误套1500或400ms。日线K线20次P95仍仅核800ms |
| P4-R11 | mixed_single/双页、series20、两模式、三周期 | 沿原`test_exact_explicit_task_lists`固定5/10及20条，完整摘要缺/多一条仍拒绝；新增校验不增加请求 |
| P4-R12 | source entry实际前缀2、返回1；另一普通/辅助实例相同来源 | 调真实`AuditCollector.projected`与公开投影记录后再校验；prefixRows独立断言为2、signal窗口仍只1；同源公共摘要相等。只造最小合法内存对象，不复算正式行情 |
| P4-R13 | loader/两源及预测get/put观察，实际分钟子线程 | 沿原`test_actual_minute_pair_child_threads_keep_one_load_without_extra_reads`与真实缓存方法用例，原函数恰1次，隔离共享样本的等待者引用同一load；新增校验只用摘要、不新增调用。真实组无加载重叠时记录not_verified且不停止；实际重复读取仍失败 |
| P4-R14 | 某组前缀失败/原HTTP失败、通信坏消息、假cleaned或子进程卡住 | 原首错停止/受监督退出测试继续通过；整CLI后续组不启动，失败原始数字保留，无后台/落盘；只结束测试自建进程 |
| P4-R15 | 相同来源两模式digest不同；或来源/截止/窗口不同 | 前者失败；后者not_comparable且不重读/补样本。缓存not_called不等于hit，样本1不生成P95，20次只对该接口排序取第19个 |

编码后的限定验证清单如下；本次实际执行结果见§21.14.10。各行独立运行，不合并成研究目录全跑；先核节点存在，任何一组超过60秒停止查因，不继续后组。统一使用现有`.venv/bin/python -B -m pytest -q`，不安装或隐式同步依赖。

| 顺序 | 具体文件/节点 | 覆盖和禁止项 |
|---|---|---|
| T1 缺陷先证 | 原`test_xxm_p4_audit_tools.py`新增R02节点 | 只跑该节点，证明合法任务摘要仅1501根时旧工具漏拦；不以其他字段失败冒充 |
| T2 工具完整 | `scripts/research/index_market/tests/test_xxm_p4_audit_tools.py`整文件 | 新R01—15及原真实TS/ASGI/子线程/监督退出；仅人工HTTP/本次自建进程，零正式源 |
| T3 有限来源交接 | `tests/web/test_wealth_index_detail_xxm_api.py`的`test_p4_bounded_real_gold_limits_files_sql_steps_and_output`及`test_p4_bounded_short_real_source_returns_last_n_without_dropping_extra` | 既有临时Gold/SQLite，证明计数字段所依的读取/step合同未变；不新增或读取正式文件 |
| T4 预测/共享交接 | `tests/web/test_wealth_index_detail_xxm_forecast_api.py`的`test_p4_bounded_short_source_precheck_precedes_real_calibration`、`test_p4_bounded_nonready_source_does_not_calibrate`、`test_p4_bounded_real_page_enddate_and_forecasts_share_source_keep_modes` | 原人工状态/临时Gold边界、合法空目标和共享，不整文件触发290根计时节点或真实回放 |
| T5 根架构 | `tests/architecture/test_subsystem_dependency_matrix.py`、`test_platform_legacy_guardrails.py`、`test_operations_legacy_guardrails.py`（后两份同目录） | 依赖方向和legacy边界；不因研究工具调用产品而引入Biz→research/App/QTF |
| T6 组织及文档 | `scripts/research/index_market/tests/test_research_layout.py::test_single_location_roots_and_pytest_discovery`；`python3 scripts/check_docs_integrity.py`与限定`git diff --check` | 原主题/入口位置及文档链接；不跑历史源码捕获、旧r2执行器或冻结行情 |

用例R12仅证明生产collector取数与新校验相接，不声称真实来源集成已通过；真实TS与ASGI关联等沿原工具测试复用。现有`row()`默认day的样本保留；分钟新样本须显式READY/source/实际时间/合法client与compute，普通接口合法None保留，不将所有旧夹具一律填成READY/0来迎合新检查。

后续编码验证顺序：只新增R02先证实旧工具漏拦→实现私有检查并补其余R01—15→跑原工具文件→跑原来源范围/预测API定向回归→按根规则三份架构检查、研究组织检查及文档检查。测试入口先核实际存在，单组60秒上限，超时或失败停止查因、不skip、不扩大到真实回放。独立审计逐项对账新检查、真实collector/Node/两个CLI/失败传播及普通接口不受影响；产品代码和mjs未改、无新源调用后，交管理员报告，未获正式续验授权不发真实请求。

#### 21.14.4 续验准备、来源和已有证据复用

先只读核当前分支/明确改动、原工具两CLI和mjs/依赖可用、最终Settings显式dev/local、分钟启用、原prod连接及正式Lake根正确；不打印凭据、不安装、不切源、不改env。配置及依赖核验不建App、不提前连库/打开Parquet/HTTP预热；每组原context/reset/metrics三次私有请求已包含必要上下文，不另发健康检查或预读行情。准备完成不等于执行授权，正式请求另按管理员安排。

| 已有证据 | 可复用内容 | 不能据此声称/本次安排 |
|---|---|---|
| §21.11日线latest混合普通/debug单/双页24次及预测40、K线40 | 当时正式API/真实TS、字段/身份/公共结果、共享加载及日线K线20样本P95通过 | 是2026-11-01历史成绩，不是当前latest或新的毫秒值；不再重跑原119次 |
| §21.13.4日线历史2026-10-27混合24次、预测40次 | 修复无上界解码，普通/debug一致；预测各模式1次miss/store+19hit及预算/退出 | 原失败仍保留；静态latest的not_called由该历史冷热证据补齐，不因进入分钟验收重复64次 |
| §0.9.10读取实现及限定回归、§0.10.9 m60四次实测 | N+1000文件/SQL/raw/step边界及当前m60正常首次/再次性能成立 | 四次不是正式TS/两模式/双页/历史或20样本，不能抵扣下面四命令 |

适用性按当前代码及消费者审计判断，不以读源码SHA、mtime、扫全历史或重查数据库证明旧报告正确。当前已核7bf8eb823之后实际客户端/解码/正式工具未改；forecast query新增窗口参数只在period!='day'分支，日线该调用保持；读取优化/前三批涉及的公共服务已做限定回归。保留上述日线来源/代码边界说明，不宣称数据库当前内容与旧日完全相同。

若执行前发现本轮以后又有改动影响日线合同/解码/装配或旧证据有效性，先停止准备，列出受影响的最小日线复验清单并补原方案/LLD，经review再执行；不得自动重跑119/64次，也不临时换日期。仅时间向后推进不使历史成功能力失效，不为了更新计时而重复日线。范围外交易助手月初日期TODO保留，不修改、不skip、不作为P4阻塞。

真实数据白名单：仅000001.SH，day沿原core_serving.index_factor_pro的close/macd_dif_bfq/macd_dea_bfq/macd_bfq，分钟沿正式Lake的gold/quote/major_index_mins/freq={60,90,120}及gold/indicator/major_index_mins_technical/freq=...。四键、close与macd_dif/macd_dea/macd及原参数/版本合同同§21.11/§0.9；日历沿原prod core_serving.trade_calendar，exchange=SSE。默认500时分钟历史日历计划最多ceil(1500/该周期每日端点数)+1个开市日及其自然日行，未来日历若实际走到仍最多90个自然日/91行。普通图/指标/九转仍各自500，不强塞r4的前缀身份。只读事务、鉴权、单组临时127.0.0.1:0及lifespan关闭保持，不使用DG数据库/CSV或退役Lake，不写正式数据。

#### 21.14.5 每周期固定命令、数量与串行顺序

从仓库根使用现有`.venv/bin/python -B -m scripts.research.index_market.<模块>`，沿`GOLDENSHARE_ENV_FILE=.env.web.local`；只用已有`--periods/--as-of/--mode/--samples`四参数。下表P依次为获准的m60、m90、m120，每条命令只选一个周期，依次执行，不能并发命令或合成一次多周期自动运行。各CLI内部仍按`planned_groups`的normal→debug及原scenario顺序执行；每组新进程/空源和预测缓存，组间不预热、不手动清系统缓存。

| 周期内次序 | 模块和原参数 | 固定成功组及业务请求 | 私有控制请求 |
|---|---|---|---|
| A latest页面 | xxm_page_request_audit --periods P --mode both --samples 1 | normal单页5/双页10，debug单页5/双页10：4组30次 | 4×3=12 |
| B latest预测 | xxm_forecast_display_audit --periods P --mode both --samples 20 | normal20、debug20：2组40次，仅forecast | 2×3=6 |
| C latest价格/指标 | xxm_page_request_audit --periods P --mode both --samples 20 | normal价格20/指标20，debug价格20/指标20：4组80次，无signals/forecast/九转 | 4×3=12 |
| D 历史页面 | xxm_page_request_audit --periods P --as-of 2026-10-27 --mode both --samples 1 | 四混合组，共30次；分钟forecast asOf为该日15:00+08:00 | 4×3=12 |
| 单周期成功上限 | 以上四命令各执行一次 | 14组，180次业务 | 42次私有；合计222次HTTP |
| 三周期全部成功上限 | 按周期分别review/获准后执行 | 42组，540次业务 | 126次私有；合计666次HTTP，不含已完成的旧轮及管理员浏览器 |

私有请求恰context/reset/metrics各1次/成功组，不读作业务样本或P95；失败组可能少于上限，只记实际发出，不为凑次数补发。A/D单页5次分别是价格、指标、九转、signals、forecast；双页各自同样五接口并发按原scheduler调度，不是两次顺序单页。signals待主图/指标成功后，沿真实points数、start/end及indicatorVersion适配，逐点close/DIF/DEA/柱相等；不另写行情对照计算。

latest不传asOf，由原context取得当时业务日期/完成端点，不能冻结旧2026-10-30或强填当天15点。D沿固定历史截止重新计划≤1500根，确认来源/结果未带入该日以后终态。20次P95只在B/C各自同接口组内计算，不跨组或用4次小测试凑20。C的分钟价格/指标只报告P95，不套日线800ms。B即使20次静态not_called，仍只执行本表既定40次，不追加历史forecast20、不换日期、不增加warm-up。

A/D同源比较按真实endpoint/period/requestedAsOf/computedThrough/sourceInputId/calendarInputId/indicatorVersion/windowStart/windowEnd/round/tabId匹配；只有唯一对应才核公共digest，来源变化记not_comparable，不强行配对。只比较已有摘要，不再次HTTP或重放。B首次是否miss、后续是否hit必须依据实际get/put记录，序号1不能自称冷计算已成功经过校准。

#### 21.14.6 成功条件、覆盖不足及首错停止

每条命令返回后先核结果与退出，再决定下一条：

1. HTTP/来源状态/字段/身份/范围/逐点适配、每次4秒HTTP/400ms计算/5秒客户端、字节/缓存/次数、通信或清理任一失败，沿原CLI立即停止本命令剩余组，外层不启动任何后续命令或周期。不得加诊断请求、重新测一次、放宽阈值、切源/日期或当场优化；报告真实输入与已有阶段，由管理员决定后续。
2. 请求全成功仍要核覆盖：A/D普通与debug的signals/forecast公共比较均为equal，mixed_two两模式均记录sharedLoadCoverage，但不要求两模式每次都自然出现并发共享，具体按本节第6条；B两模式均完成20次并逐轮公共结果equal；C每组20条合格，记录独立P95。source加载与forecast get/put计数原上限保持。所有成功r4分钟记录都须READY、0<prefixRows≤1500，signals 0<responseRows≤500；三周期不互相借成绩。
3. forecast实际缓存hit覆盖按真实B输出登记，不能将not_called、not_verified或HTTP200记hit。P4已通过日线历史两模式实证证明动态预测缓存，本次m60小范围亦已实证；若某分钟B静态分支未访问预测缓存，合法状态和性能可通过，但该周期缓存hit单项仍为“未覆盖（静态路径）”，不能声称全部冷热已验收。**当前固定清单不为造hit追加请求；存在该预测缓存必需覆盖或同源比较缺口，当前命令安全结束后暂停后续命令，交管理员review后再决定是否接受相应既有证据或安排独立补验；仅未出现加载重叠的共享not_verified不触发此停止条件。未经确认不把该周期或P4写成全部通过。**这不是临时调规则，正常产品可返回NO_CANDIDATE/PRECISION_PENDING，工具如实记录。
4. 有限精度未决、无普通解或只有旧结构条件分别报告实际结果及是否进入校准/未来日历/缓存；未走到的分支只写未覆盖，不自动新增“全部业务分支真实重放”。真实长短窗口标签全量一致也不在本清单，原规则以已验收独立RC/PF样本和有界来源测试为依据。
5. 每周期四条全合格、必需覆盖齐备、无遗留活动请求/进程后，产出§21.14.7摘要交review。若只执行A或B便停，不将未开始C/D或其他周期称为通过；数量按实际记，不用本表成功上限代替。
6. **真实并发共享按实际观察记录，不强求每周期、每模式或每个双页组都碰到两个请求等待同一份加载。**未发生加载重叠且请求/结果/预算/读取正常时，sharedLoadCoverage=not_verified只表示该组未测到这个时序，不判失败、不停止后续固定命令、不再要求管理员逐次确认，也不为凑verified重跑、延时、改调度或追加请求；不得将原not_verified改成verified。共享功能继续由原隔离样本验证，已有真实共享证据也保留。若记录显示违反原共享/读取规则的不必要读源或历史重算、同源结果不同、超时、协议或退出失败，仍按第1条立即停止，不能借“未测到”忽略实际异常。其他必需覆盖继续按本节要求处理。

工具代码不增加自动续跑器或新的覆盖枚举；沿原输出字段区分failed/not_comparable/not_verified，人工执行步骤在每条CLI结束后检查这些已有值。若一条CLI内部有多组，仅因加载未重叠的共享not_verified可以正常收尾并继续原计划后续命令；预测缓存和同源比较等其他必需覆盖仍按第3条。真实错误仍立即中断。该差别不得在编码时改成“忽略一切继续所有周期”。

#### 21.14.7 预算、通信、退出和结果交接

| 项目 | 固定要求 |
|---|---|
| r4单次HTTP/实际计算 | signals≤4秒/1MiB；forecast≤4秒/32KiB且计算/缓存处理≤400ms；TS从原deadline至解码/适配/提交<5秒，原check不变 |
| 来源、缓存及并发 | 分钟本清单最多1500完成根，返回最多500；缓存64MiB/16条，原源并发/数量/内存保护保持，不增加复制或整段验收 |
| 一组总期限 | 50秒工作、60秒含启动/取结果/最终校验/关闭/回收；各组独立计，不把14组合成60秒，也不把单次4秒延长为组期限 |
| 通信/退出 | 原§21.5.5—6的单份有界stdin、started+result/failed、固定字段/原1MiB累计管道限制及Node有界输出不变；50秒SIGINT、58秒TERM、59秒KILL、60秒回收，仅自身已知进程组；结果消息收到不等于清理成功 |
| 中断与再次执行 | Ctrl-C/超时/首错同样停止所有新任务，既有失败/完成摘要保留；不保留恢复文件、不自动续跑。管理员以后允许再跑时，明确从哪条未验收命令开始，重新核配置/适用性，新组/新缓存；不补已完成合格命令，不将旧组半份摘要拼成20成功样本 |
| 研究/页面 | 原8秒/2MiB及前端10秒由第6步保持，daily-waves不加入自动180次清单；日线K线800ms只复用其适用历史20样本 |

每组正常退出须activeRequests=0、cacheBytes/entries合格、worker/Node/线程/自有socket/engine已关闭、无自身残留；强制终止、权限不足无法证明退出或坏通信均失败，不报cleaned。原观测函数/时钟在请求线程实际结束后恢复，不能提前拆包装，不能重启/杀管理员服务。只有结果、有限计时及退出摘要回写原文档，禁止保存完整行情/响应或新结果文件。

结果逐周期、逐命令登记：当前代码/工具状态与实际命令、每组groupId和实际请求数/私有次数、真实来源工程/周期/请求截止与computedThrough、前缀根数及已记录的起止、返回根数/图窗、普通/debug公共比较、逐次HTTP/compute及20组P95、字节、源读取/签名/缓存命中与并发共享、未覆盖原因、退出/取消及首错后未开始清单。signals的windowStart/End是返回窗口，不冒充前缀首日；只有forecast/已有来源事实记录到的前缀首末可报告，缺值不靠第二次读取补齐。来源身份是已用业务前缀身份，不是源码SHA。

日线已有证据与新分钟执行分表，不把历史119/68、四次限定复测、新540上限和浏览器混计。可展示正常或失败样本的短参数/错误码，不输出数据库连接凭据或完整异常正文。不因已通过而自动提交、部署或进入下一阶段；实际提交按管理员指令另做明确白名单。

#### 21.14.8 第6步交接及P4完成判定

正式第5步三分钟周期、已适用日线证据与工程定向回归对账通过后，按§21.7交管理员维护的本地开发页面和/wealth生产构建。交接单固定含：实际代码状态/识别与预测版本、final Settings来源边界（无凭据）、后端8000/前端实际origin与代理目标、已验周期/历史截止/来源身份、当前剩余TODO及以下勾选表。临时采样App已结束，不能作为页面长期服务；Codex本节不代启动或重启共享服务。

| 管理员页面项目 | 正向及反向验收要点 |
|---|---|
| 本地普通四周期 | 000001.SH日线、60/90/120逐一与相同完成截止API标签/当根事件/发生时间和预判对应；普通界面不出现参照细节。无数据/精度未决如实展示，不补成信号 |
| 真实图层及布局 | 1600/1440/1280宽，45/180可见根、拖过301根；悬停、同根隐藏/保留、四种三角、1000日线不退回300；不同日期来源不机械要求与旧latest相同 |
| debug加载与切换 | 无debug零辅助chunk/DOM/daily-waves/三角；明确debug=1才加载，加载中/失败保持有资格的普通功能，失败可重试。URL切换允许行情重请求和图重建；仅模块phase变化不增加重刷。关闭/迟到不能覆盖新周期/日期 |
| 手动研究 | 仅日线且点击才请求；研究日期与普通右栏/预测分开，关闭/离开/切标的、周期、日期后取消并恢复；分钟不出现研究图/三角；原240px说明及键盘行为保持 |
| 周期及功能资格 | 日线/60/90/120识别各自工作；5/15/30主图不发r4识别，合法技术面四行预测不被误关闭；其他标的无r4；行情/九转/趋势真实错误仍可见 |
| 生产关闭 | 既有/wealth production构建普通/debug两URL均无r4DOM/请求/辅助预载，日线K线/九转/趋势正常，生产分钟继续不可用。后端prod/缺环境404、OpenAPI缺席和零来源调用复用正式装配隔离测试，不通过开放真实prod r4来验 |
| 浏览器证据 | 记录管理员实际URL/origin、代码与来源/截止、console/network、通过/失败/未测及必要截图；自动Node不是布局验收，代码/配置未加载则未验收 |

管理员验收发现问题先界定具体输入和失败步骤；涉及修复时先核原方案/LLD并补受影响设计、回归后再review，不当场改变规则或删已通过检查。P4最后独立审计须覆盖P3→环境装配→debug加载→工具→真实来源/预算→管理员页面的完整交接，保留范围外日期TODO及性能优化TODO，不要求先修无关问题。只有管理员页面通过且所有必需验收证据齐备，才可写P4完成。

P4完成后的下一件事是单独准备P5：重审旧r2/旧候选/完整两位实验和双组执行代码的引用与有用能力迁出，再依§20.4四步实施；本节不执行删除。原材料/报告/历史设计、独立峰谷波段工具、独立两位取数函数与人工算术测试保留，清退依据实际依赖而非文件名。P4验收通过也不等于部署或生产r4开放。

#### 21.14.9 本轮文档交付及独立审计（2026-11-02）

本轮仅修改产品§10.6、技术方案§23、优化专项§17及本文§21.14，并同步原当前状态、§0.3、§21.6/§21.9与历史续验入口；保留原真实失败/成功和暂停优化调查。删除旧“分钟按20000前缀验收”“无命中自动补20次”等已失效执行指令，将第1—4步文件表标清已实现，不把曾经的差距当作当前任务。没有修改产品或工具代码、配置、行情/数据库/Lake、部署或执行正式请求，未提交。

独立审计再次对照实际`AuditCollector.projected`、`validate_summary`、`planned_groups/expected_requests`、`_supervise/run_audit_group`及两CLI/Node消费者，核对新检查范围、合法None/短源、失败传播、固定请求及清理边界。CodeGraph explore覆盖工具校验→监督执行链，图中无关同名候选不作证据；直接源码补核动态观测、实际TS调用和旧日线证据适用条件。没有新增跨层依赖或API/CLI合同。

静态提取原planned_groups/expected_requests函数（不import业务模块、不建App），独立计算三个周期的四命令结果均为4/30/12、2/40/6、4/80/12、4/30/12（组/业务/私有），每周期14/180/42、三周期42/540/126，与原四文档一致。已核未来T3/T4/T6引用的6个既有测试节点均存在；P4-R01—15、T1—6是未来设计，未编写测试代码、未运行这些业务测试，不计为通过成绩。

文档完整性三项通过，限定diff无空白错误；四文档36处本地文件链接、2处新增锚点有效。工具四文件与本轮开始的文本逐一比较未变；工作区其他已有修改及并行产生的无关报告未触碰。核对本轮硬口径与编码点/测试设计/阶段交接，未发现需新增产品拍板或阻碍下一步工具补齐设计的歧义；当前只完成设计，可以在review及后续授权后进入工具补齐，尚不能跳过它直接宣称正式验收通过。复杂优化TODO、范围外日期TODO及P5边界保持。


#### 21.14.10 工具补齐、限定验证与本次正式续验授权（2026-11-03）

管理员已要求“严格按照方案和LLD，推进完成P4”。本次覆盖本节工具补齐、准备、按m60→m90→m120固定清单的自动真实续验和结果对账；每周期先报告实际结果，在本次整批授权内仅全部合格后进入后续周期。§21.14.1/5中“未获整批授权不得自动跑三周期”的限制本次已满足，不因此重复询问业务许可；首次失败/必需覆盖不足仍依§21.14.6硬停。第6步仍按既有决定由管理员完成，不代签页面验收；不进入P5、不自动提交或部署。旧§21.14.9为上一轮设计交付事实，未编码/未执行描述不覆盖本条新进度。

代码严格只修改原xxm_page_request_audit.py和test_xxm_p4_audit_tools.py。新增私有_validate_minute_r4_prefix，在原成功检查中调用，按§21.14.2核READY/真实前缀/来源/返回数及400ms；两个CLI、mjs、观测及记录字段/原计时、读源/核心/Spec/EMA/缓存/页面均未改。先加R02，旧工具三分钟周期3项均因未抛前缀错误失败，证明原漏拦；随后实现检查并完成R01—15。中间新混合夹具误用了day九转地址，导致46项在到达新检查前失败；已按真实nineTurnApiClient的minute-nine-turn/freq及其他实际分钟路径纠正新夹具，没有改变旧day样本或放宽生产检查。该中间结果不计通过成绩。

| 验证顺序 | 实际结果 | 覆盖边界 |
|---|---|---|
| T1 修复前R02 | 3项预期失败，0.35秒 | 完整合法forecast组只把实际前缀改1501，旧工具漏拦 |
| T2 原工具整文件 | 174通过，6.61秒 | 新增64项；R02现覆盖signals/forecast×三周期，真实collector、TS人工HTTP、ASGI/子线程/原缓存/失败协议/自有进程清理；零正式源 |
| T3 两个指定来源节点 | 7通过，17.62秒 | 临时Gold/SQLite，N+1000/raw/step/输出及短源；没有正式Lake |
| T4 三个指定预测节点 | 6通过，0.82秒 | 人工/临时来源的前提、合法空结果、非READY不校准、页面与预测共享 |
| T5 三份根架构 | 16通过，13.76秒 | 既定依赖方向和legacy边界 |
| T6 主题发现/文档 | 1通过，0.40秒；文档三项及限定diff通过 | 主题位置/入口及文档；不跑旧研究或全量Wealth |

共204项最终限定测试通过，各组未超60秒；既有Starlette TestClient依赖弃用提示保留，不安装或升级。R01/02为三周期/两模式及实际1501反例；R03—10覆盖短源、严格类型/缺来源、返回根数/READY、合法空目标/400ms与日线/普通分钟隔离；R11—15复用原分组/缓存/子线程/比较/监督用例并补真实collector的2根前缀/1根输出和worker失败保留1501。关键断言使用独立字面值，不从新函数生成expected，未将mock成绩视作真实接入。

开发后独立审计对照§21.14.2逐句重读唯一新增函数及调用位置，复核collector.projected→真实processed/through、worker成功验证→failed摘要→supervisor→CLI首错停止链，旧失败验证不按成功上限删证据；没有新源调用或更改记录/任务数。CodeGraph explore覆盖校验/监督/双CLI影响面，sync/status已完成；原mjs/显示CLI逐字未变。当前工作区其他dirty代码只在直接链核界：RequestIdMiddleware的新增分支仅stock-detail/kline，指数路径仍原处理；App装配/识别及预测客户端和query目标代码未变。本次不修改这些其他任务文件。

准备核验只读取最终Settings、依赖和目录能力：显式APP_ENV=local，.env.web.local仍原prod数据库152.136.106.251:5432/goldenshare；分钟仍正式/Volumes/datasource/data_lake，指数分钟/分钟九转能力启用，现有Node可用。未输出凭据、不连接库、不打开Parquet、不建App或预热。日线旧证据按§21.14.4保留适用边界，不自动重跑119/64次，不说是当前latest性能。

接下来只用§21.14.5原两CLI，先m60-A，每周期固定四命令/14组/180业务+42私有上限，三周期540业务+126私有上限。读取仅000001.SH，图/指标/九转各500，r4输入≤1500；prod日历SSE按有限窗口及必要上下文聚合、index_basic同代码必要信息和index_daily_serving最新日期聚合沿§21.11白名单，分钟Gold bars/indicators/九转沿原字段/版本。m60日历最多376、m90最多501、m120最多751个开市日及所需自然日期，未来日历仅实际进入时最多90自然日/91行；没有全局明细/导出、第二次对照读取或业务落盘。只读会话、原鉴权、单组隔离进程/临时端口、50/60秒、4秒/400ms/5秒和原字节/缓存上限保持。任何真实失败或必需覆盖缺口按原流程停止后续命令；实际执行另在本条后追加，当前尚无本轮正式HTTP成绩。

#### 21.14.11 m60-A正式结果与当时的覆盖不足停止（2026-11-03）

仅执行原命令GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -B -m scripts.research.index_market.xxm_page_request_audit --periods m60 --mode both --samples 1，无包装入口、预热、重试、固定旧时钟或额外请求。4组30次业务均HTTP200/terminal=success，原context/reset/metrics每组3次，合计12私有；CLI正常exit=0，四组cleaned/activeRequests=0且监督确认自有进程退出。当时核覆盖发现debug双页sharedLoadCoverage=not_verified，依当时要求在该命令结束后停止，未启动B/C/D或其他周期。管理员随后已取消强求真实加载重叠的要求，当前按§21.14.6/12继续，原not_verified事实保留，m60-A无需重跑。实际没有业务失败、超时或重复读源；其余命令未执行，不能把该CLI成功当作整批通过。

| 组/模式 | groupId | 业务数 | r4完整HTTP最大/预测处理最大 | 共享加载覆盖 |
|---|---|---|---|---|
| 单页normal | b8f0ec551eb24d028f777f0a5ff75fc4 | 5 | 0.760173375秒 / 18.044917ms | not_required |
| 双页normal | d9b0866a1973480fa80f2472781b357a | 10 | 0.546828250秒 / 31.623875ms | verified |
| 单页debug | b43c295df964408b90494690e91fe500 | 5 | 0.637759834秒 / 19.866833ms | not_required |
| 双页debug | dc336ec64b4e4829a8dec9d038c15a16 | 10 | 0.534846375秒 / 16.510833ms | not_verified |

四组原context的generatedAt依次为2026-11-03T00:38:15.096542/00:38:21.186773/00:38:28.204946/00:38:33.850016+08:00，businessDate均2026-11-02。真实截止均2026-11-02T15:00:00+08:00；当时尚无11月3日完成K线，READY合法，不是冻结旧日期。12次r4请求前缀均1500，真实前缀2025-04-16T10:30:00+08:00至上述截止；signals均返回500，图窗2026-04-28T10:30:00+08:00至截止，主图close/DIF/DEA/柱真实适配通过。indicatorVersion=1；sourceInputId统一acdb15972a5cf134da2e07572d318461c66abb2179771b15b2a74b852b9d5cd5，实际预测calendarInputId为17b6f788cfda85fd47277908ad53909465b08a321e5444b6d3087dc6e88c5036；signals该字段合法None。

普通/debug公共比较单页2对、双页4对均equal。识别身份xxm-direction-v0.4-r4 / db435b39a3d198c126bfff567dfbe66faf74ff9299005578ec6b49bf065fd110，预测xxm-key-point-forecast-v0.6-r4 / 9994790178d64757462643fc37eba9e0945b118e91f1fdb85223db81db2a7b12，与原已验收身份相同。r4最大客户端完整处理0.761932042秒，最大HTTP0.760173375秒，最大预测处理31.623875ms，均远低于原预算；30业务中所有接口最大HTTP1.434913959秒，该值不套日线800ms。每组samples=1，P95为None，不宣称20次性能已验收。最大响应字节：signals155101、forecast2159、价格113680、指标316724、九转56910；缓存峰值1472109字节/2条，原上限未触发。

各组独立空产品缓存：每组pair/bars/indicators内容均各读取1次，四组总计各4次，无单load重复读取。单页两模式各2个load（1次miss+1次hit）；普通双页2个load且至少两个请求引用同一loadId，实际共享已证明；debug双页4个load（1次miss+3次hit），各请求引用不同loadId。两双页预测均实测miss/store→hit，未追加预测20次来凑命中。

本次覆盖不足的具体依据：debug双页4个r4请求虽然部分HTTP期间重叠，真实source loader却串行；load-1从组起点4966.024417ms到5432.710583ms，load-2实际开始5461.375833ms，随后load-3/4亦各自执行，后3次seriesCacheRead=hit且pair/bars/indicators均0。只能证明内容只读一次及缓存复用，不能把它写成“本组实际并发共用了同一个load”。不能为了凑verified制造延时、放宽断言或重跑同一命令。普通双页真实共享及原隔离测试继续作为已有证据保留；本次debug未碰到加载重叠只如实记录，按管理员已确认的新要求不再阻塞或重复请求确认。

本轮执行后的独立核对仅解析原内存摘要：30业务、12私有、4组退出0/cleaned、r4 1500根/READY、6对公共相同、原时限/字节/缓存/每load一次及停止位置均符合LLD；没有再次HTTP/读库/读Lake/重算。结果和工具输出未落盘，仅本条记录有界摘要。m60-B预测20×两模式、C价格/指标20×两模式、D历史，以及m90/m120全部未启动；页面第6步仍待管理员。当前P4未完成，未提交、部署、清退P5或重开优化TODO。

#### 21.14.12 真实并发共享不作为必须触发的时序（2026-11-03）

管理员明确确认：不需要强行要求真实验收一定碰到同时共享加载，调整LLD即可。本次仅修正验收完成判断和停止流程，源读取/计算规则、共享功能、计数、缓存、请求数量、预算及原测试代码均不改。当前工具validate_summary本来就如实返回sharedLoadCoverage而不会单因not_verified报错，因此无需改工具或伪造verified；此前停止来自旧LLD要求，现已同步删除该要求，并同步产品§10.6、技术方案§23及专项§17。本次不取消或误判原已保留的简单结构复算、必要验证及合法来源修订后的重建；只按原有读取和共享规则判断是否发生了多余工作。

现行流程统一按§21.14.6第6条：normal/debug、latest/历史及m60/m90/m120真实双页组都不要求强行触发加载重叠。无重叠、各次请求正确且读取/预算/清理正常时，not_verified仅记录“本组未测到并发共享”，不会阻塞周期或P4验收；不新增请求、不重跑、改时钟、延时、改调度或逐次要求确认。违反原共享/读取规则的不必要读源或历史重算、同源结果不同、超时和协议/退出失败继续硬停；同源比较及预测缓存等其他验收要求未因本项调整取消。

测试设计同步细化：P4-23/P4-R13中隔离并发样本仍必须证明共享同一真实load且内容不重复读，不能把它也改成可忽略；正式自然请求分三种情况核对：①同源请求实际引用同loadId，记录verified；②加载无重叠且首次真实读、随后合法缓存复用，保留not_verified并可继续；③记录显示违反原共享/读取规则的不必要读源、历史重算或其他异常，仍失败停止。第②类不需要新增测试代码或测量场次，当前m60-A的debug双页就是已有实证；用它核对执行流程，不为证明新要求再发请求。

本次m60-A的30业务/12私有成功、1500根、6对公共一致、正常双页shared verified及debug合法缓存复用，按新要求不再有共享观察阻塞；保留原§21.14.11的实际数据和当时停止事实，原debug未验证记录不改写。后续继续从m60-B，再C/D、m90/m120，沿原固定清单；不重跑A，P4和管理员第6步页面尚未验收不提前宣布完成。本轮只修改原四文档和独立核对，没有改任何代码或执行测试/真实请求，未提交或部署。

本轮文档独立审计：已对齐§21.5.3、§21.6、§21.8的P4-23、§21.14.1/3/6及原三份方案中的相同停止要求；保留当时暂停事实，当前状态不再写作等待共享确认。正常/反向三种场景与工具现有返回行为一致，代码与原测试文件逐字未变。文档完整性三项、36处本地文件链接及限定diff检查通过；未重跑204项旧测试，也未重新读取正式行情或执行任何后续命令，不将文档核对登记为新业务测试通过。

#### 21.14.13 本次继续执行与真实验收结果（2026-11-03）

管理员要求继续推进后，严格从m60-B执行C/D，再m90与m120各A/B/C/D；既有m60-A不重跑，204项限定工程测试不重复运行。只用原xxm_page_request_audit及xxm_forecast_display_audit两CLI、原四参数、真实TS client/decoder/adapter/原调度器；没有临时替代入口、预热、改日期补样本、人工延时、阈值放宽或切源。真实并发未重叠按§21.14.12仅保留观察，其他失败仍首错停止。

**以下为第5步自动验收交付时的实际记录，当时尚待第6步；管理员随后已确认页面通过，P4最终收尾见§21.14.14。**以下全部是已完成实际记录，不是计划上限。完整分钟清单42组、540业务+126私有，分三周期各14组/180业务/42私有；其中m60-A的4组30/12来自此前已完成轮，本次实际新执行11条命令、38组、510业务+114私有。旧日线119/68及旧四次小范围复测不加入此计数。所有12条命令exit=0，42组cleaned/activeRequests=0，原监督器确认自有worker/Node/线程/进程组退出；没有仍在运行的采样任务。

##### 固定命令逐项对账

A/D仍是两模式的单/双页混合，B每模式只预测20次，C每模式只对价格/指标各20次。D统一as-of=2026-10-27；latest不传asOf、不冻结时钟。每组context/reset/metrics恰3次。没有新增daily-waves、浏览器或其他标的请求。

| 命令 | 完成组 | 业务请求 | 私有请求 | 公共结果相同对数 | 结果 |
|---|---|---|---|---|---|
| m60-A | 4 | 30 | 12 | 6 | 通过 |
| m60-B | 2 | 40 | 6 | 20 | 通过 |
| m60-C | 4 | 80 | 12 | 0 | 通过 |
| m60-D | 4 | 30 | 12 | 6 | 通过 |
| m90-A | 4 | 30 | 12 | 6 | 通过 |
| m90-B | 2 | 40 | 6 | 20 | 通过 |
| m90-C | 4 | 80 | 12 | 0 | 通过 |
| m90-D | 4 | 30 | 12 | 6 | 通过 |
| m120-A | 4 | 30 | 12 | 6 | 通过 |
| m120-B | 2 | 40 | 6 | 20 | 通过 |
| m120-C | 4 | 80 | 12 | 0 | 通过 |
| m120-D | 4 | 30 | 12 | 6 | 通过 |

##### 来源、范围、结果和预算

配置仍为显式APP_ENV=local、原.env.web.local/prod日历及业务上下文和本机/Volumes/datasource/data_lake正式Gold，仅000001.SH及既有bars/indicators/九转投影；只读事务/原鉴权、lifespan关闭和临时127.0.0.1:0保持。没有数据库/Lake写入、DG任务/事件、全局明细读取、安装、共享服务重启或源MACD重算。

192次r4请求全部HTTP200、READY，实际已处理前缀均1500；36次signals均返回500根，156次forecast保持合法responseRows=None。主图与识别逐点close/DIF/DEA/MACD匹配由原真实TS适配通过。每周期普通/debug公共结果32对相同（A6+B20+D6），合计96对equal、0对not_comparable、0个合同/解码错误。三周期indicatorVersion均1；识别xxm-direction-v0.4-r4及Spec db435b39a3d198c126bfff567dfbe66faf74ff9299005578ec6b49bf065fd110，预测xxm-key-point-forecast-v0.6-r4及Spec 9994790178d64757462643fc37eba9e0945b118e91f1fdb85223db81db2a7b12均保持原身份。

| 周期 | 组数 | 业务/私有 | r4完整HTTP最大（秒） | 预测处理最大（ms） | r4客户端最大（秒） | 公共一致对数 | 缓存峰值字节/条 | 结果 |
|---|---|---|---|---|---|---|---|---|
| m60 | 14 | 180/42 | 1.105568 | 100.416750 | 1.109445 | 32 | 1472109/2 | 通过 |
| m90 | 14 | 180/42 | 0.988716 | 100.098250 | 0.991727 | 32 | 1608792/2 | 通过 |
| m120 | 14 | 180/42 | 1.316199 | 153.720041 | 1.324371 | 32 | 1878491/2 | 通过 |

以上r4HTTP逐次≤4秒、预测处理≤400ms、TS解码/适配/最终检查<5秒，signals≤1MiB、forecast≤32KiB，缓存≤64MiB/16条；所有组原50秒工作/60秒含准备/收尾要求通过。单次普通价格/指标/九转沿原各自合同和组时限，不套日线800ms。各分钟周期全部业务接口的最大HTTP分别为m60 1.434913959秒、m90 1.977533125秒、m120 2.644484750秒；这些不冒充预测计算耗时或日线P95。这里是本次分钟成绩，不能与旧日线数字拼成同一轮总体最大值。

| 周期 | 模式 | 预测20样本P95（秒） | 价格20样本P95（秒） | 指标20样本P95（秒） | B组真实预测缓存 |
|---|---|---|---|---|---|
| m60 | normal | 0.194311 | 0.287318 | 0.337947 | 1 miss / 1 stored / 19 hit |
| m60 | debug | 0.407479 | 0.365646 | 0.345573 | 1 miss / 1 stored / 19 hit |
| m90 | normal | 0.344667 | 0.308135 | 0.315201 | 1 miss / 1 stored / 19 hit |
| m90 | debug | 0.345741 | 0.311437 | 0.329870 | 1 miss / 1 stored / 19 hit |
| m120 | normal | 0.382322 | 0.334824 | 0.323821 | 1 miss / 1 stored / 19 hit |
| m120 | debug | 0.333666 | 0.298267 | 0.326234 | 1 miss / 1 stored / 19 hit |

每个P95都来自对应接口/模式的恰20个成功样本，按原工具第19个排序值；A/D samples=1只记录单次，不生成P95。分钟上述P95仅报告，不套日线800ms。B六组都真实1次miss/写入+19次hit，证明当前这些动态路径已进入必要校准/未来日历/预测生成及结果缓存；不按序号猜命中，也不为静态路径追加样本。m60-D的预测未访问结果缓存、calendarInputId=None，如实记录该历史分支未访问，不能说它有hit；本周期B已独立补齐缓存覆盖。未声称所有真实有解/复杂跟踪分支都跑到。

所有30个包含r4的组中，每组历史bars/indicators内容各读1次、r4 pair调用1次；各load的源cache/pair/bars/indicators及各请求forecast get/put均未重复调用。六个B组都源首次miss、后续复用，未重新读内容。C只执行普通价格/指标接口，没有r4源load；其r4 pair计数0不代表没有读取行情。签名/来源修订检查沿原规则，不要求所有顺序独立HTTP总SQL数为1。

12个双页真实组中10个记录shared verified，m60-A debug及m60-D normal的两个组仅未碰到加载重叠，保留not_verified；实际每组内容仍各读1次，没有以重新读取替代共享。按管理员已拍板要求不因此阻塞，不重跑/延时凑verified；原确定性隔离共享测试继续保留。

latest实际截止均2026-11-02T15:00:00+08:00，原context是在11月3日尚无新完成K线时取得，业务日11月2日合法；历史截止均2026-10-27T15:00:00+08:00。以下start仅用forecast摘要记录的真实前缀首时点，不把signals返回窗口起点当作完整前缀。

| 周期/类型 | 真实1500根前缀首时点 | 实际截止 | sourceInputId | calendarInputId |
|---|---|---|---|---|
| m60/latest | 2025-04-16T10:30:00+08:00 | 2026-11-02T15:00:00+08:00 | acdb15972a5cf134da2e07572d318461c66abb2179771b15b2a74b852b9d5cd5 | 17b6f788cfda85fd47277908ad53909465b08a321e5444b6d3087dc6e88c5036 |
| m60/history | 2025-04-10T10:30:00+08:00 | 2026-10-27T15:00:00+08:00 | 325d46f980a8ca18e4b4b3d0aed67598c93f08f79b4a79f04d9911d183c0c5fa | None（本次未访问未来日历） |
| m90/latest | 2024-10-11T11:00:00+08:00 | 2026-11-02T15:00:00+08:00 | d3084d98ee54fc7a3e5f8de4b9bddeb56d87800b2b4bd515c4e3685939bd6280 | 17b6f788cfda85fd47277908ad53909465b08a321e5444b6d3087dc6e88c5036 |
| m90/history | 2024-09-30T11:00:00+08:00 | 2026-10-27T15:00:00+08:00 | 8e1ed7588fd095606ac55a2658e6fc910e29b92cb1fb729d23a5c0924a126838 | 58c6e39a993d7b2aaa8b4935bad7100b11ed3d102c73b7655e7887a4c4edfb57 |
| m120/latest | 2023-09-21T11:30:00+08:00 | 2026-11-02T15:00:00+08:00 | 767411c00f5c7477b937e7ff196b8b6a9b42ead7206db62ccd3ebc1b6ded5a71 | 17b6f788cfda85fd47277908ad53909465b08a321e5444b6d3087dc6e88c5036 |
| m120/history | 2023-09-15T11:30:00+08:00 | 2026-10-27T15:00:00+08:00 | 60e8c58f51f4c26ba2201f6713769553d8847807eb014b544d2ab4712fd31694 | 58c6e39a993d7b2aaa8b4935bad7100b11ed3d102c73b7655e7887a4c4edfb57 |

##### 逐组可核对摘要

计时单位分别为秒/ms；不适用保持不适用。source pair只指r4历史加载，公共比较/帧数/有界管道等沿原工具合同。全部原始工具摘要只留内存，本表不保存行情或完整HTTP正文。

| 命令 | 模式/场景 | groupId | 业务/私有 | r4HTTP最大秒 | 预测最大ms | P95秒 | r4 pair总数 | 共享观察 | 退出 |
|---|---|---|---|---|---|---|---|---|---|
| m60-A | normal / mixed_single | b8f0ec551eb24d028f777f0a5ff75fc4 | 5/3 | 0.760173 | 18.044917 | 不适用 | 1 | not_required | cleaned |
| m60-A | normal / mixed_two | d9b0866a1973480fa80f2472781b357a | 10/3 | 0.546828 | 31.623875 | 不适用 | 1 | verified | cleaned |
| m60-A | debug / mixed_single | b43c295df964408b90494690e91fe500 | 5/3 | 0.637760 | 19.866833 | 不适用 | 1 | not_required | cleaned |
| m60-A | debug / mixed_two | dc336ec64b4e4829a8dec9d038c15a16 | 10/3 | 0.534846 | 16.510833 | 不适用 | 1 | not_verified | cleaned |
| m60-B | normal / forecast_series | aa1d9390893d49c6ba404ce291026300 | 20/3 | 1.105568 | 100.416750 | 0.194311 | 1 | not_required | cleaned |
| m60-B | debug / forecast_series | 5848f8ffe2824899b5b1feb569a82a52 | 20/3 | 0.797526 | 79.225459 | 0.407479 | 1 | not_required | cleaned |
| m60-C | normal / kline_series | eb4e7ba650174718b72be4555c43bc3f | 20/3 | 不适用 | 不适用 | 0.287318 | 0 | not_required | cleaned |
| m60-C | normal / indicator_series | 5d9ef2a30eb34816bf800b249903442d | 20/3 | 不适用 | 不适用 | 0.337947 | 0 | not_required | cleaned |
| m60-C | debug / kline_series | 333365bad18b473f922e59cc68bdde2f | 20/3 | 不适用 | 不适用 | 0.365646 | 0 | not_required | cleaned |
| m60-C | debug / indicator_series | c3c8e57a7753432fa3e8a4b18d36aca6 | 20/3 | 不适用 | 不适用 | 0.345573 | 0 | not_required | cleaned |
| m60-D | normal / mixed_single | ec34d028c8c84aa6a89156c2f03fcb51 | 5/3 | 0.720102 | 0.967125 | 不适用 | 1 | not_required | cleaned |
| m60-D | normal / mixed_two | 5a8c7535d2d541349879045389686964 | 10/3 | 0.539344 | 1.104833 | 不适用 | 1 | not_verified | cleaned |
| m60-D | debug / mixed_single | fc0430ac83f34bdf9573720f984a325c | 5/3 | 0.639902 | 0.878375 | 不适用 | 1 | not_required | cleaned |
| m60-D | debug / mixed_two | fa2a33825b6b4c4bb32cea65c1dbd93d | 10/3 | 0.722178 | 1.055125 | 不适用 | 1 | verified | cleaned |
| m90-A | normal / mixed_single | e6dab036440b41b2a9c0fbb4f86a9b64 | 5/3 | 0.770298 | 25.206708 | 不适用 | 1 | not_required | cleaned |
| m90-A | normal / mixed_two | 0b92304492c4460ab21f9df10bfe24db | 10/3 | 0.590625 | 24.023125 | 不适用 | 1 | verified | cleaned |
| m90-A | debug / mixed_single | 0bb46697c08440ccb0eac7884ee7361b | 5/3 | 0.674261 | 23.941792 | 不适用 | 1 | not_required | cleaned |
| m90-A | debug / mixed_two | df91f91ab789450d9accd08143737cc9 | 10/3 | 0.655781 | 38.661875 | 不适用 | 1 | verified | cleaned |
| m90-B | normal / forecast_series | 2fe157325cdc41c39712210918129299 | 20/3 | 0.950241 | 98.420125 | 0.344667 | 1 | not_required | cleaned |
| m90-B | debug / forecast_series | 5c8ecc8d5ae64fd2b57eeff580a5abb0 | 20/3 | 0.988716 | 100.098250 | 0.345741 | 1 | not_required | cleaned |
| m90-C | normal / kline_series | 82c1709014554369a986c76ddbedd70d | 20/3 | 不适用 | 不适用 | 0.308135 | 0 | not_required | cleaned |
| m90-C | normal / indicator_series | 27cda004673045ebb572ae617eab662e | 20/3 | 不适用 | 不适用 | 0.315201 | 0 | not_required | cleaned |
| m90-C | debug / kline_series | 81fd38cf685c46fa8d4288119ceb6a0e | 20/3 | 不适用 | 不适用 | 0.311437 | 0 | not_required | cleaned |
| m90-C | debug / indicator_series | 46b9f48a5ad84029be4fe7eec4396a46 | 20/3 | 不适用 | 不适用 | 0.329870 | 0 | not_required | cleaned |
| m90-D | normal / mixed_single | d022ac486c464098b11b5bbba26749a8 | 5/3 | 0.797088 | 20.079250 | 不适用 | 1 | not_required | cleaned |
| m90-D | normal / mixed_two | 870d5e4a84bf4862af4ea6678c5da1f1 | 10/3 | 0.764170 | 19.812958 | 不适用 | 1 | verified | cleaned |
| m90-D | debug / mixed_single | 6d4ce1471541436cbe1b96e2d7a2ba05 | 5/3 | 0.795570 | 34.976708 | 不适用 | 1 | not_required | cleaned |
| m90-D | debug / mixed_two | 10e4b646dbc6409192e41ab4b9a34bfc | 10/3 | 0.886701 | 23.796291 | 不适用 | 1 | verified | cleaned |
| m120-A | normal / mixed_single | 265bd511873a44b8ae902fda918e4856 | 5/3 | 1.316199 | 21.238375 | 不适用 | 1 | not_required | cleaned |
| m120-A | normal / mixed_two | 4ec65f15daad49298a29f86fb441b2a7 | 10/3 | 0.884384 | 18.776958 | 不适用 | 1 | verified | cleaned |
| m120-A | debug / mixed_single | a646c179303f4680ad7a84bd5d31ade8 | 5/3 | 0.820116 | 17.338750 | 不适用 | 1 | not_required | cleaned |
| m120-A | debug / mixed_two | a04819766a4f444386b35fc3ec2c2e3a | 10/3 | 0.862670 | 52.260417 | 不适用 | 1 | verified | cleaned |
| m120-B | normal / forecast_series | aabc2439ae334b2da31d93138ed130cb | 20/3 | 1.167024 | 153.720041 | 0.382322 | 1 | not_required | cleaned |
| m120-B | debug / forecast_series | 8c3d4b394fa24fb8a07752f6b71bbcfa | 20/3 | 0.951336 | 89.372834 | 0.333666 | 1 | not_required | cleaned |
| m120-C | normal / kline_series | f943c91bf3b246a999394ca25c014312 | 20/3 | 不适用 | 不适用 | 0.334824 | 0 | not_required | cleaned |
| m120-C | normal / indicator_series | bbbe88ddd019436485c698da522a8600 | 20/3 | 不适用 | 不适用 | 0.323821 | 0 | not_required | cleaned |
| m120-C | debug / kline_series | 9ee5154325144d7491e64ffb45a9e8ce | 20/3 | 不适用 | 不适用 | 0.298267 | 0 | not_required | cleaned |
| m120-C | debug / indicator_series | 7b0e8b958f584138ad8d122a9d9632a6 | 20/3 | 不适用 | 不适用 | 0.326234 | 0 | not_required | cleaned |
| m120-D | normal / mixed_single | 8711a3863d3641f1b76955b28921e22d | 5/3 | 0.928723 | 36.911834 | 不适用 | 1 | not_required | cleaned |
| m120-D | normal / mixed_two | e3795cf089d547d387429a926901cc0c | 10/3 | 0.691774 | 37.138125 | 不适用 | 1 | verified | cleaned |
| m120-D | debug / mixed_single | 9ee963d6a2ac46b895e5bc701a7da5a0 | 5/3 | 0.806044 | 34.468209 | 不适用 | 1 | not_required | cleaned |
| m120-D | debug / mixed_two | 1c3851fc061942dc941575e2262a7f05 | 10/3 | 0.718735 | 35.369000 | 不适用 | 1 | verified | cleaned |

##### 第5步完成及第6步交接

| P4项目 | 当前结果 | 证据/边界 |
|---|---|---|
| 第1—4步工程实现 | 已完成并沿用 | §21.10，工具本次补齐及204项限定验证见§21.14.10；本次没有代码变更 |
| 第5步day | 已有适用真实证据，复用 | §21.11/§21.13.4的latest、历史、K线20次P95及历史预测冷热，不重新请求119/64次，不称今日实测 |
| 第5步m60/m90/m120 | 本节固定清单全部通过 | 每周期180业务/42私有；实际输入/公共结果/性能/缓存/读取/退出均符合当前LLD |
| 第6步管理员页面 | 待管理员review | 自动Node证明真实请求/解码/数值，不替代DOM/布局/console/network及生产构建页面 |
| P4整批 | 待第6步及最终确认 | 不提前写整批已验收，不启动P5或部署 |

管理员交接使用其维护的后端8000和当前Wealth前端实际地址；前端origin按实际启动输出记录、不猜5173，确认/api仍指向本批本地后端及相同识别/预测身份。工具临时App已关闭，不交作长期页面，不由Codex接管或重启共享服务。当前仍dev-interface；管理员现已批准将本需求工具/测试及原四文档一并提交，实际版本以本次Git记录为准。旧3a7bb7760仅为本次开发前基线，不代表已包含当前工具补齐。第6步页面仍待管理员验收，提交不构成部署或P5授权。

第6步按§21.7/§21.14.8检查：①日线及60/90/120的标签、当根事件、时间、预判与同完成截止API相符；②1600/1440/1280宽、45/180可见根及301根之后、悬停/三角/1000日线；③无debug无辅助下载，debug按需加载/失败重试，URL切换允许行情重请求，模块状态变化不额外重刷；④日线波段手动启动，关闭/切换/离开取消及迟到丢弃、普通/研究日期分开、说明240px及键盘；⑤不支持识别周期仍保留合法四行预测，真实行情/九转/趋势错误可见；⑥production构建普通/debug均无r4/辅助请求与DOM、正常日线保持，生产分钟仍不支持。后台生产/缺环境404及零源调用沿正式装配隔离证据，不为验收开放真实prod r4。

人工review不要求后来latest与旧摘要永久相等；优先用固定2026-10-27同截止材料比较，latest另记当时完成截止，发现实际来源修订按原规则处理。需要整改先明确失败步骤并补方案/LLD，不改规则或扩大范围绕过。页面通过后再做P4最终对账，由管理员确认收尾；P5引用审计/有用能力迁出/删旧代码/删后回归及部署均另行安排。

##### 本次执行后独立审计

只解析既有内存摘要，独立核12命令/42组/540业务/126私有及本次新增510/114，192次r4全READY/1500，36次signals返回500，156次forecast合法计时，96对公共一致和六组1miss/store+19hit；全部实际时限/字节/缓存/调用次数/退出满足原合同。没有再次请求、读取Lake/DB或用同一算法复算作expected。执行前重新核原工具、mjs、显示CLI和最终Settings；执行后再次核代码无改动、其他工作区修改保留，文档/链接及限定diff按实际检查登记。没有安装、提交、推送、部署、自动启动优化TODO、P5或管理员页面review。未覆盖的全历史等价/全部真实预测分支及原软件逐图匹配不新增到本轮任务，也不冒充已验收。

最终交付检查：原四文档当前状态已同步为“第5步自动通过、待管理员第6步”，旧失败及限定复测保留历史用途；36处本地文件链接和4处锚点经逐项检查有效（已更新改名后的专项§17锚点）。工具/测试/mjs及显示CLI与续验前逐字相同，无新增代码；暂存区为空。文档完整性三项及限定diff通过。上述为执行后静态核对，不额外发请求或增加测试成绩。

提交交接：管理员已明确批准提交本批六文件，仅原xxm_page_request_audit.py、test_xxm_p4_audit_tools.py及原产品/技术/专项/LLD四文档；其他工作区修改保留。本次提交包含204项限定验证和三分钟固定540业务/126私有的记录，不重跑已通过测试，不提前登记第6步通过，不推送或部署。实际版本由本次Git提交记录确认。


#### 21.14.14 P4最终对账与验收收尾（2026-11-03）

**P4六步已完成并验收收尾。**管理员本轮原话为“页面验收通过了”，这是第6步人工页面验收的确认依据；本轮不另造浏览器地址、截图、DOM、console或network检查记录，也不将Node请求结果冒称人工页面操作。

| 步骤 | 完成依据与当前结论 |
|---|---|
| 1 本地/生产装配 | 复用§21.10的实际代码/定向工程验证；本地四周期按配置可用，生产r4仍关闭，未部署或开放生产 |
| 2 debug动态加载及请求模式 | 复用§21.10及当前页面实现；无debug不加载辅助模块，URL切换允许既有重请求/图表重建；模块阶段变化不额外重刷 |
| 3 辅助详情和手动波段核对 | 复用§21.10；仅debug动态挂载，日线研究仍需手动开启，独立峰谷/波段工具保留；管理员页面验收已通过 |
| 4 保留工具 | 原工具迁移和限定回归见§21.10及§21.14.10；1500根校验补齐及204项限定测试已提交c7c606e81 |
| 5 真实来源/性能 | 日线复用§21.11/§21.13.4已适用证据；分钟实际结果见§21.14.13，42组540业务/126私有、96对公共相同、192次r4全READY且1500根；不重新请求或采样 |
| 6 管理员页面及最终对账 | 管理员本轮明确确认页面验收通过；本条同步原四文档当前状态，收尾完成，不再保留当前“待第6步”阻塞 |

真实记录的540业务请求包含36次signals、156次forecast和其他行情/指标/九转；此前m60-A计入完整清单，本次不重复执行。所有已记预算、缓存、读取及退出结论沿§21.14.13的实际范围，日线历史性能不改称今日latest。自然双页未出现加载重叠的两组not_verified保留原结论，不造verified、不补请求；隔离共享测试及真实异常停止规则继续有效。

正式唯一识别`xxm-direction-v0.4-r4`和预测`xxm-key-point-forecast-v0.6-r4`及其Spec不变；默认分钟500根输出、最多1500根计算、4秒完整HTTP/400ms预测/<5秒客户端预算与当前来源/缓存政策不变。P4完成不表示生产r4开放、分钟生产支持、部署完成、全历史等价或作者全部视频已匹配。

**保留但不阻塞P4/P5的事项：**性能优化第4—7批继续按专项§16/本文§0.11作为后续TODO；无关交易助手日期测试问题继续单列TODO，未修复且不登记全部前端回归通过。未覆盖的完整历史等价、全部真实预测分支等边界沿原证据，不转成未经确认的新验收任务。

**交接：**P4工具/测试及自动证据已提交c7c606e81；本次将原产品/技术/LLD/优化专项的收尾与P5设计一并提交。P5第一步当前代码/资料/测试审计及编码设计已完成，见§22；实际迁移与删除尚未开始。下一步按§20.4和§22.6先迁有用能力及资料、完成交接，再删旧执行链；取得该步执行授权后重新核当日文件状态，不能跳过交接或重做P4验收。历史材料、独立波段工具及最小两位算术保留。

本轮独立核对使用CodeGraph codegraph_explore及当前正式query/计算器引用、研究副本/两位函数和原P5清单；证实正式查询使用唯一产品类、旧研究及完整两位执行链仍待清退，不把典型文件核对冒充P5全量引用审计。本次没有修改代码、读行情、运行新业务测试、清理缓存、提交、推送、部署或改变其他工作区内容。文档差异、原文档链接及完整性检查另按本轮实际结果登记。

收尾检查结果：原四文档当前状态及P5四步顺序一致；36处本地文件链接、4处锚点和文档完整性三项均通过，限定diff无空白错误。当前分支仍为dev-interface，HEAD为c7c606e81；正式识别/查询、P4工具及测试相对HEAD无修改。上述仅为本轮文档和静态核对，不计新增业务测试或真实来源验收。


## 22. P5审计、编码设计及开工对账（2026-11-03）

§22.1—22.8记录第一步审计/设计及当时未执行的事实；第二步结果见§22.9，第三步最终完成结果见§22.16.6。下文带“本轮只审计/待review/暂停/首错停止”的旧时点记录仅解释历史，不能覆盖当前完成状态，也不是重新执行已完成步骤的指令。

### 22.1 本轮目标、依据与结论边界

依据产品§11、技术方案§8/§24及本文§10/§11.2/§20.4。管理员本轮要求只审计和补LLD，并明确无用中间报告/错误解释不留、有用资料收敛；本节落实这一口径。P4已通过，不能为清退再改规则或重做产品集成。

本轮静态核103个代码/测试文件，AST解析当前定义/导入、动态Git加载、写文件及Notebook代码单元；需要保留的取数、量图、算术、观察、恢复输入逐函数核当前实现。reports清单覆盖112目录3503文件，JSON全部实际解析、代码实际AST解析、讲稿/报告正文和来源关系核对；4个ZIP只读核目录及非代码成员是否已有原件，不解包执行。其他主题reports只列边界，不冒称已审核其内容。该工作判断代码/资料的保留用途和依赖，**不重新验证旧算法成绩或新视频事实，不冒称旧文件已删、测试已过或221份资料已经移好**。

CodeGraph已使用`codegraph_explore`核quantize/旧研究/正式类、load/clone/API/前端Hook等入口，`codegraph_impact`核两位函数18个符号及历史对比入口影响；再用当前AST/源码补动态加载、测试和报告中未由索引完整覆盖的引用。当前正式运行链无待退研究导入；数据资料引用主要在离线工具/测试/历史导航。

### 22.2 本轮纠正的旧设计及确定决策

| 发现 | 当前代码事实与固定修正 |
|---|---|
| 原清退表遗漏后增历史执行链 | 4个r4_history模块及4份专属测试整退；已完成专项最终报告留原文档，不保留Git复活旧算法入口 |
| 一次性P1/P2迁移工具还会加载旧源码 | migration/capture/worker三helper及专属test清退；response工厂及自测旧合同亦清退。37组原始输入仍被当前恢复tests用到，单独保留，不整包删 |
| 多处LLD还要求重做P3/P4迁移 | daily_window现已114行纯工具，Web/TS fixtures及3个真实路由工具已迁好；§10/§11改成当前事实，只复核、不重复开发 |
| 按“纯函数”保留无消费者旧代码 | 旧history formatter/ordinary_index/forecast_expectations去掉；它们只服务旧合同或旧执行链，当前独立记录/数学/工具tests已承接有用覆盖 |
| 两位/数学样本中夹着旧业务答案 | 只留2个两位函数、纯有理数/区间与手写输入；多步/horizon20/最强排序/等待期待不能当当前预期 |
| reports笼统保留导致大量过程产物和隐藏源码遗留 | 3503行逐项分类，3282删除、207原件收敛、6份历史说明整理、7字段抽取、1Notebook整理；4源码ZIP和diagnostic文本源码不豁免，混合来源摘要中的嵌套旧比较同样去掉 |
| 资料移动会破坏CASES、Notebook和原始观察测试 | 精确新旧路径/字段白名单/使用方已登记附件，源码/测试与资料同批交接；源字节、路径元数据、抽取内容分别检查 |
| 27条旧摘录并非27张仍可用原图 | 11条Downloads原图已经不存在，reports无同字节副本；保留数字摘录及限制，不伪造核图通过、不因此新增下载/视频任务 |

以上是管理与工程清退，不改变已经确认的r4业务规则。没有新增需要管理员决定的算法口径；资料缺图只限制历史证据，不作为P4或清退设计的新阻塞。

### 22.3 人工输入不能误删

#### 22.3.1 原样本精简的编码规则

`xxm_product_v1_cases.py`改为仅标准库和纯输入材料：固定DATES/PERIODS、不可变`Case(name, values)`及`inputs(period)`。按原DATES给day或该日15:00:00+08:00，不调用产品求DEA或结果；close/DIF/DEA/hist四项均采用原字面值。旧名称仅是输入标识，不再暗示旧规则正确。删除Reference/Check和所有rules/why/checks/facts/FORECAST_MATH业务预期后，逐组数量/顺序/数值须与下表完全一致，不能仅数37组。

当前snapshot_validation的`test_handwritten_input_prefixes_restore_and_continue_in_all_four_periods`继续消费全部37×4，并在每个截断点恢复/继续；旧business expected不再导入。`test_xxm_product_v1_cases`只验材料/独立性，不继续自证旧等待或多步规则。正式RC/PF手写预期另有当前测试，不被本材料替代。

#### 22.3.2 37组、222根原始输入登记

下表只登记输入，不含算法预期；每个元组顺序是(close, DIF, DEA, hist)。由现文件纯字面AST展开常量/拼接/切片取得，没有import或执行旧算法。

| 原输入标识 | 根数 | 原四项数值 |
|---|---:|---|
| `no_completed_same_color_reference` | 2 | `((100, 10, 9, 2), (101, 11, 10, 2))` |
| `one_nonzero_colored_bar_is_insufficient` | 3 | `((100, 50, 49, 2), (90, 0, 1, -2), (101, 40, 39, 2))` |
| `nearest_before_stronger_far` | 6 | `((130, 30, 29, 2), (90, 0, 1, -2), (120, 20, 19, 2), (90, 0, 1, -2), (131, 15, 14, 2), (132, 16, 15, 2))` |
| `far_only_after_near_fails` | 6 | `((130, 30, 29, 2), (90, 0, 1, -2), (120, 20, 19, 2), (90, 0, 1, -2), (131, 25, 24, 2), (132, 26, 25, 2))` |
| `near_price_gate_blocks_far` | 6 | `((100, 30, 29, 2), (90, 0, 1, -2), (120, 20, 19, 2), (90, 0, 1, -2), (119, 10, 9, 2), (119, 10, 9, 2))` |
| `first_price_equality_rejected` | 6 | `((130, 30, 29, 2), (90, 0, 1, -2), (120, 20, 19, 2), (90, 0, 1, -2), (120, 10, 9, 2), (120, 10, 9, 2))` |
| `first_dif_equality_rejected` | 6 | `((130, 30, 29, 2), (90, 0, 1, -2), (120, 20, 19, 2), (90, 0, 1, -2), (131, 30, 29, 2), (132, 30, 29, 2))` |
| `third_candidate_not_searched` | 8 | `((150, 60, 59, 2), (90, 0, 1, -2), (130, 30, 29, 2), (90, 0, 1, -2), (120, 20, 19, 2), (90, 0, 1, -2), (160, 40, 39, 2), (161, 40, 39, 2))` |
| `same_color_zero_is_not_opposite` | 3 | `((100, 50, 49, 2), (101, 30, 30, 0), (102, 31, 30, 2))` |
| `zero_does_not_supply_second_colored_bar` | 5 | `((100, 50, 49, 2), (90, 0, 1, -2), (98, 5, 4, 2), (101, 5, 5, 0), (102, 5, 4, 2))` |
| `zero_day_first_activation` | 5 | `((100, 50, 49, 2), (90, 0, 1, -2), (98, 5, 4, 2), (99, 6, 5, 2), (101, 6, 6, 0))` |
| `opening_zero_not_backfilled` | 3 | `((100, 1, 1, 0), (99, -1, -1, 0), (100, 2, 1, 2))` |
| `first_entry_is_not_same_bar_structure` | 4 | `((100, 50, 49, 2), (90, 0, 1, -2), (102, 41, 40, 2), (103, 40, 39, 2))` |
| `exact_one_percent_zero_target` | 5 | `((100, 200, 199, 2), (90, 0, 1, -2), (101, 90, 89, 2), (102, 100, 99, 2), (102, 99, 99, 0))` |
| `less_than_one_percent_remains_dull` | 5 | `((100, 200, 199, 2), (90, 0, 1, -2), (101, 90, 89, 2), (102, 100, 99, 2), (102, 99.1, 99.1, 0))` |
| `previous_zero_dif_is_not_skipped` | 6 | `((100, 10, 9, 2), (90, 0, 1, -2), (101, 1, 0, 2), (102, 0.5, -0.5, 2), (102, 0, 0, 0), (102, -1, -2, 2))` |
| `previous_zero_bar_dif_is_adjacent_basis` | 7 | `((100, 50, 49, 2), (90, 0, 1, -2), (101, 40, 39, 2), (102, 41, 40, 2), (102, 40, 39, 2), (102, 39.9, 39.9, 0), (102, 40.35, 39.35, 2))` |
| `true_flip_confirms_without_one_percent` | 6 | `((100, 50, 49, 2), (90, 0, 1, -2), (101, 40, 39, 2), (102, 41, 40, 2), (102, 41, 41, 0), (999, 40.9, 41.9, -2))` |
| `true_flip_break_precedes_confirmation` | 5 | `((100, 50, 49, 2), (90, 0, 1, -2), (101, 40, 39, 2), (102, 41, 40, 2), (999, 51, 52, -2))` |
| `same_bar_near_to_far_switch` | 9 | `((100, 41.186, 40.186, 2), (90, 0, 1, -2), (120, 24.935, 23.935, 2), (90, 0, 1, -2), (130, 17.649, 16.649, 2), (131, 17.649, 16.649, 2), (132, 26.754, 26.754, 0), (131, 27.89, 26.89, 2), (131, 27.4, 26.4, 2))` |
| `true_flip_never_rescues_with_eligible_a` | 7 | `((100, 41.186, 40.186, 2), (90, 0, 1, -2), (120, 24.935, 23.935, 2), (90, 0, 1, -2), (130, 17.649, 16.649, 2), (131, 17.649, 16.649, 2), (132, 26.754, 27.754, -2))` |
| `far_qualifies_only_next_bar` | 8 | `((140, 41.186, 40.186, 2), (90, 0, 1, -2), (120, 24.935, 23.935, 2), (90, 0, 1, -2), (130, 17.649, 16.649, 2), (131, 17.649, 16.649, 2), (132, 26.754, 25.754, 2), (141, 27.89, 26.89, 2))` |
| `structure_does_not_use_dull_switch` | 8 | `((100, 41.186, 40.186, 2), (90, 0, 1, -2), (120, 24.935, 23.935, 2), (90, 0, 1, -2), (130, 17.649, 16.649, 2), (131, 17.649, 16.649, 2), (131, 17, 16, 2), (132, 26.754, 26.754, 0))` |
| `equal_active_reference_does_not_switch` | 7 | `((100, 41.186, 40.186, 2), (90, 0, 1, -2), (120, 24.935, 23.935, 2), (90, 0, 1, -2), (130, 17.649, 16.649, 2), (131, 17.649, 16.649, 2), (132, 24.935, 23.935, 2))` |
| `bottom_same_bar_switch` | 9 | `((100, -41.186, -40.186, -2), (110, 0, -1, 2), (80, -24.935, -23.935, -2), (110, 0, -1, 2), (70, -17.649, -16.649, -2), (69, -17.649, -16.649, -2), (68, -26.754, -26.754, 0), (69, -27.89, -26.89, -2), (69, -27.4, -26.4, -2))` |
| `bottom_has_no_negative_current_dif_gate` | 4 | `((100, -1, 0, -2), (110, 1, 0, 2), (99, 0, 1, -2), (98, 1, 2, -2))` |
| `bottom_current_close_starts_waiting` | 7 | `((100, -10, -9, -2), (99, -11, -10, -2), (105, -5, -6, 2), (98, -9, -8, -2), (97, -9.2, -8.2, -2), (98, -8.8, -7.8, -2), (100, -9, -9, 0))` |
| `zero_day_bottom_reactivation` | 8 | `((100, -10, -9, -2), (99, -11, -10, -2), (105, -5, -6, 2), (98, -9, -8, -2), (97, -9.2, -8.2, -2), (98, -8.8, -7.8, -2), (100, -9, -9, 0), (98.5, -9.2, -9.2, 0))` |
| `waiting_price_equality_not_reactivated` | 8 | `((100, -10, -9, -2), (99, -11, -10, -2), (105, -5, -6, 2), (98, -9, -8, -2), (97, -9.2, -8.2, -2), (98, -8.8, -7.8, -2), (100, -9, -9, 0), (99, -9.2, -9.2, 0))` |
| `waiting_reference_break_invalidates` | 8 | `((100, -10, -9, -2), (99, -11, -10, -2), (105, -5, -6, 2), (98, -9, -8, -2), (97, -9.2, -8.2, -2), (98, -8.8, -7.8, -2), (100, -9, -9, 0), (98.5, -11.1, -11.1, 0))` |
| `waiting_true_red_ends_segment` | 8 | `((100, -10, -9, -2), (99, -11, -10, -2), (105, -5, -6, 2), (98, -9, -8, -2), (97, -9.2, -8.2, -2), (98, -8.8, -7.8, -2), (100, -9, -9, 0), (100, -9, -10, 2))` |
| `historical_top_price_withdrawal` | 7 | `((100, 50, 49, 2), (90, 0, 1, -2), (101, 40, 39, 2), (102, 41, 40, 2), (102, 40, 39, 2), (103, 39.9, 38.9, 2), (104, 39.8, 38.8, 2))` |
| `bottom_history_withdraws_only_after_real_red` | 8 | `((100, -10, -9, -2), (99, -11, -10, -2), (105, -5, -6, 2), (98, -9, -8, -2), (97, -9.2, -8.2, -2), (98, -8.8, -7.8, -2), (105, -8.8, -9.8, 2), (96, -8, -7, -2))` |
| `cumulative_close_and_separate_dif_dates` | 4 | `((120, 50, 49, 2), (110, 0, 1, -2), (125, 20, 19, 2), (119, 25, 24, 2))` |
| `first_top_requires_positive_current_dif` | 4 | `((120, 20, 19, 2), (110, 0, 1, -2), (131, 1, 0, 2), (132, 0, -1, 2))` |
| `active_reference_equality_then_strict_break` | 6 | `((100, 50, 49, 2), (90, 0, 1, -2), (101, 40, 39, 2), (102, 41, 40, 2), (102, 50, 49, 2), (102, 50.01, 49.01, 2))` |
| `price_fall_alone_does_not_cancel_existing_dull` | 5 | `((100, 50, 49, 2), (90, 0, 1, -2), (101, 40, 39, 2), (102, 41, 40, 2), (99, 41, 40, 2))` |

### 22.4 资料路径、抽取和历史限制

reports附件中221个有目标的原文件分别映射唯一目标，目标没有冲突；其余3282原文件明确删除。新资料README按sources/observations/conclusions/local-extrema列用途、旧路径、新路径和当前文档入口，不另建研究方案、算法实现或完整结果库。

27条数值摘录完整保留，52条标签观察只保留一份。11条缺原图记录如下，仅表示当前无法重新看原图，不能删除其已存摘录或自动填补：

| 周期 | 时间 | 已失效的原图文件名 |
|---|---|---|
| m120 | 2025-08-08T15:00:00+08:00 | `IMG_0318.PNG` |
| m120 | 2025-08-12T15:00:00+08:00 | `IMG_0358.PNG` |
| m120 | 2026-05-07T15:00:00+08:00 | `IMG_0310.PNG` |
| m120 | 2026-09-01T15:00:00+08:00 | `IMG_0360.PNG` |
| m90 | 2025-08-06T15:00:00+08:00 | `IMG_0374.PNG` |
| m90 | 2025-08-12T15:00:00+08:00 | `IMG_0359.PNG` |
| m90 | 2025-08-14T15:00:00+08:00 | `IMG_0315.PNG` |
| m90 | 2026-01-13T15:00:00+08:00 | `IMG_0369.PNG` |
| m60 | 2026-01-13T15:00:00+08:00 | `IMG_0370.PNG` |
| m60 | 2026-04-07T15:00:00+08:00 | `IMG_0366.PNG` |
| m60 | 2026-04-20T15:00:00+08:00 | `IMG_0361.PNG` |

资料变更按以下固定顺序，不能颠倒：

1. 按精确清单核源文件和目标无占用，准备消费者修改及独立测试；代码与资料同步在当前工作区处理，不发布半成品。
2. 移动207份普通保留件，逐字节核对；7份抽取件按附件根字段及§10.3.3.1嵌套白名单逐值核原文，目标先完整成立，才删除混合原件；6份历史README单独整理链接/历史范围/失效活动命令，不更改原成绩/日期；Notebook按§11.2.2改未执行代码单元/路径。不能递归复制整份旧目录后把不需要的继续留下。
3. 更新CASES、collect_readouts、保留测试和Notebook/文档入口；数据/原图/讲稿SHA不变，7份抽取件以原字段值/明确原文检验，不把它们当原字节文件。Notebook只对source路径作明确对账，不宽泛归一化业务字段。
4. 原材料/纯工具/测试交接通过后，才删除3282份无用产物及旧执行链、已知对应pyc；确认旧目录无其他文件再删空目录。遇到变更、新用途/目标冲突即停，不吞错或改目标后缀。
5. 删除后新进程核引用和当前运行入口，再做§22.5/§22.6回归；未完成的文件如实列剩余，不称“基本清干净”。

### 22.5 对应编码的规则与清退测试设计

本节是后续测试设计，本轮不写测试代码、不执行业务测试。除明确只验证隔离/原材料边界外，预期均为独立字面；不调用待测函数生成expected。

| 编号 | 代码/资料位置与输入 | 正向独立预期 | 必须抓住的错误/反例 |
|---|---|---|---|
| P5-01 | 103代码清单、静态import/动态字符串/Notebook/README | 正式r4和全部保留入口不依赖待删模块；旧模块缺席新进程仍能正常导入 | 静态import、Git blob执行、别名/转发、.pyc、ZIP/文本源码仍可复活旧类，任一种都失败；不能只搜r2 |
| P5-02 | near_first纯两位取数 | 40.057→40；−8.086→−8.0；41.01→41，40.99→40；41.9/41.4均41；0、±0.008086、99.999、100.1字面结果 | bool、NaN、±inf拒绝；测试不得构造计算器/读代码或行情；不能用Q自身生成expected |
| P5-03 | 37人工输入、222根、4周期 | 每组name/顺序/四项值与§22.3一致；时间仅按原格式变化，Case和返回输入互不污染 | 丢一组、丢/改一根DEA、把旧checks/facts重新当当前expected或由产品生成材料均抓住 |
| P5-04 | 当前snapshot_validation及37×4每截断 | restore后继续与同输入连续结果一致，坏恢复不污染原对象；当前独立快照字面测试照常保留 | 只保留37组材料却不运行恢复、减少周期/截断、为旧waiting成功而加状态兼容均失败 |
| P5-05 | acceptance.load_source临时真实字段CSV/manifest | day的trade_date/close/macd_*_bfq及分钟原字段/真实DEA按原值交付，data SHA不变；两个合法源目录独立 | 缺DEA或改文件直接失败；时间/非有限数值沿消费者的bar.validate校验，不给load_source另加新协议或兜底；不能读取不存在的旧源码或递归旧manifest.protected |
| P5-06 | collect_readouts已有27条、两次调用 | 行数27且period/time唯一，原software/source/sourceRecord及数据不变；改一次返回不影响另一次 | 旧5份算法报告缺席仍工作；不能重新跑模型算差值、把11缺图报作已核图或补猜值 |
| P5-07 | 52条重复观察 | 只保留指定一份，原confidence/source/endpoint不变 | mapped升级精确时刻、与27数值或别的13条直接合成独立样本数、保留多份相同旧JSON都不合格 |
| P5-08 | 207原件、6历史说明、7抽取文件、1Notebook；新增两份真实来源摘要见§10.3.3.1 | 普通件字节一一相同；6份说明仅导航/历史范围/失效活动命令变化，旧成绩/日期/事实不变；7件抽取根键准确，新增两件的每个来源对象嵌套键恰为原键与白名单交集，数组顺序及保留叶值等原文；可选purpose/title/paraphrase原本有无均如实保留；Notebook仅明确路径/未执行单元变更 | 仅筛根键却带出嵌套comparison、残留旧预测文件/身份/analysis/后续找图任务，少保留有效原文或补缺键为null，均失败；其他旧interpretation/legacy_model_difference/工作规则同样不得带回；不另存旧解释 |
| P5-09 | local_extrema 3真实小窗口/人工峰谷 | 72+63+63原行、原SHA/时间/数值不变；局部峰谷/平台/未确认尾部/量图边界及4个原时间锚点保持 | 旧run.json/源码缺席不能阻塞；坏数据仍拒绝，不因搬目录取消数据身份检查 |
| P5-10 | Notebook组装及已有Notebook | 纯返回字典，所有执行计数为空、无outputs，引用纯扫描/新资料路径；旧结果与新计算仅source字段路径明确一对一，其余结果不删字段 | exec/写文件、绝对旧目录、旧candidate import、为凑比较删除峰谷/日期/数量字段均失败；测试不运行Notebook |
| P5-11 | reference_window原始事实人工值 | 平台−10/−10先后确认和首反色窗口，原DIF/price及日期保持；调用前后输入不变 | qdif/eligible/selected重新出现、把该工具接入正式r4、把不同色段边界当r4选峰结论都失败 |
| P5-12 | saved_minute_window与量图原字面tests | 原90分钟行/字节/定位/时点、H恒等式和有限数值、边界邻行行为不变；遮挡不补像素 | 缺列、逆序、超限、坏SHA、错尺寸/遮挡不应被资料移动或清退放宽；源检查不进入产品请求 |
| P5-13 | top_activation_math及real_math纯分数 | pair(1/3)=[1,3]；daily_options在±0.0005及±2×10^-10两侧、恰tie保留原选项；meet/minus开闭、单点手写结果 | import旧expectations/proof、最强排序、2步目标/20根oracle重新出现或不当作闭边界，失败 |
| P5-14 | test_xxm_calculator现CURRENT_CORE_NODES | 7个现函数/22参数用例及RC01—110现有业务断言全部保留 | 只删文件尾部却删掉当前函数、改1%/零中性/B→A/当前价/结构寿命或恢复拒错来迎合旧测试，失败 |
| P5-15 | 当前r4_observation/observe_rows | 正式类record_decisions实际分支及无记录模式业务相同；1000/1001根、20秒、256MiB、16MiB及copy/失败不共享照原独立例 | 恢复旧Observed类/抄step，或因删旧formatter把现观察测试一起删掉，失败 |
| P5-16 | forecast_display迁当前_range_text，独立范围 | [10,20]且display10/20→“收盘不低于10点且不高于20点”；单点12→“收盘等于12点”；(10.2,∞)且display11/None→“收盘不低于11点”；(10.2,10.3)无整数→现无整数说明；原精确区间不变 | display为float/bool、非正数、上无界却有displayUpper、单点不闭/不等、半份整数边界均拒绝；不能再次根据中点/旧报告求价；8组分别覆盖正常/单点/无上界/无整数/坏类型/坏单点/半字段/不改输入 |
| P5-17 | confirmed_cases原观察3例、原源文件 | 保留2024-03-11 m120上午11:30绿色消失、2025-06-12 m90 14:00结构而非15:00、2023-04-14钝化及17/18无可见旧消失的原确认；值3052.2827/3401.2473等独立原值不变 | 不再断言new_top_DULL自动结束旧历史；用当前structures/relatedStructureId及正式派生标记核身份。改字段不能改作者日期；与当前r4真实结果不符必须停review，不能改图证/skip/改规则凑过 |
| P5-18 | 3例既有离线源读取交接 | case_windows直接load_source，day仍核原calendar/manifest行数和validate_window；minute逐根validate及时间唯一升序；只留3例需要结果窗口 | 不能恢复load_bars/validate_capture_identity旧接口，不能缺DEA补算。源CSV最大按已知912/1643/17260/12945/8630根及合计8MiB上限，按3个原终点停止；组60秒且只保留原3例结果窗口，不新增RSS检查/全步骤缓存，不能接正式库或新增全区间比较 |
| P5-19 | r4_records/历史配对旧反例 | 有效悬挂引用/错方向/重复事件/未来记录反例由现snapshot_validation/r4_restore/r4_internal_results及Web/debug合同保持；旧五字段配对不留 | 删除旧suite后又同时减少当前拒错覆盖，或把旧r2组改名r4作对照expected，失败 |
| P5-20 | 4个现工具和Web/TS当前合同 | P4已验收只读/参数/仅内存/首错/退出/1500/缓存/双模式行为不变；现r1/rearm命名合同tests及表达式联合保留 | 借清退改--output/--candidate、注册生产r4、隐藏原错误、放宽预算或删合法当前表达式，都超范围停下 |
| P5-21 | 资料目录/空目录/其他工作区 | 221个明确目标逐项存在且可解释；3282删除行均已清引用；清单外文件不动 | 整目录批删、遇到目标已存在就覆盖、拷整个旧包/旧ZIP或伪装TXT、丢原图/原稿均失败 |
| P5-22 | 中断/文件已移动但引用未改 | 按实际完成文件续做明确交接，不从头重复覆盖；已过的文件内容不变，未过项不报成功 | 自动全量重跑、默默补不存在源文件、创建后台/恢复库或用旧执行器兜底，失败 |

P5-17/18是已有三例离线材料的当前单组回归，非新双组回测；不通过observe_rows绕过其1000根上限，也不改变默认分钟产品1500根预算。只保留原case_windows的有限结果，按原3个终点结束，不新增截图日期或调阈值。当前规则不允许保留的旧内部寿命解释已明确删除，但作者原始标签/日期不能改写；实际开发核对若有剩余业务差异须汇报，不把本轮静态设计说成已经验证匹配。

### 22.6 实施顺序、测试分组、失败与完成条件

本节规定P5第一步确定的整体实施与验收边界；第1、2项已由第二步完成（§22.9），不再执行迁移/删除。第3项的第三步精确顺序、文件及退出要求为§22.10；本轮已获授权执行，在3.4首错停止，当前实际结果及未完成范围见§22.11。

1. 第一阶段开发先精简保留工具和人工材料、迁221份有用资料及其路径/字段消费者，补本节对应独立测试；正式r4/App/API/前端/Reader/Spec不动。旧执行链此时尚未删除，工具必须已解除其依赖，不能靠旧导入碰巧通过。
2. 迁出能力的定向测试合格后，按两份附件删除旧执行代码/专属tests/3282无用产物、ZIP及明确pyc，清活动命令和相关空目录；不得删其他主题或未登记内容。
3. 在旧文件物理缺席的新进程做测试收集和以下分组回归；每组60秒截止含退出/报告，失败或超时首次出现即停查因，不自动续下一组、不安装依赖。按既有命令习惯禁用插件自动加载/bytecode/pytest缓存，不改产品配置。

| 组 | 明确覆盖 | 输入与执行边界 |
|---|---|---|
| 收集/引用 | 现pytest testpaths、主题完整收集、AST/动态入口/Notebook/README清单；保留模块新进程import | 不运行被删除旧suite，不通过移动testpaths或skip藏错；其他主题只收集不执行研究 |
| 纯工具/资料 | near_first、saved_minute_window、local_extrema、local_extrema_study、reference_window、top_activation_real_math、acceptance_scope、纯输入材料tests | 临时合成/明确本地原材料；无真源/正式写入/新报告；3小窗口和量图仅现独立测试 |
| 核心/恢复/观察 | calculator、r4_rules/following/restore/internal_results、input/snapshot_validation/snapshot_consumers、r4_observation及following_query | 当前人工RC预期；37×4恢复输入；无旧算法；大文件按文件继续分组但不得漏掉迁后节点 |
| 预测/文本 | key_point_forecast、p3_forecast_math、r4_following_forecast、forecast_expression_contract、精简forecast_display | 当前单步/PF/原EMA/有限边界/无上界与整数；不跑旧horizon20、多门槛oracle |
| 原图事实3例 | confirmed_cases迁后全文件 | 明确原文件/源身份，P5-18根数/8MiB/60秒及有限结果窗口；不连DB/Lake，不新增业务区间 |
| 路由/工具 | 当前Web识别/预测、shared_loads、daily_window_precheck和完整p4_audit_tools | 原人工SQLite/临时Gold/隔离服务样本；不启动真实CLI，不发P4正式请求 |
| 必要前端 | 当前xxm、xxm-forecast、debug、daily-wave及页面相关定向tests；现typecheck/build | 若未来实现未改前端，核其现消费者仍不依赖旧报告；不修无关交易助手日期TODO，不声称全前端全部通过 |
| 架构/组织/文档 | 根三份架构、研究依赖方向和test_research_layout::test_single_location_roots_and_pytest_discovery、check_docs_integrity、两CSV完整性和本批链接/diff | 不跑其他主题历史归档/回测；链接新旧出处与活动入口分清 |

4. 正式业务未改时复用P4四周期真实证据，不加真实API采样、完整历史字段比对或全量读取。若发现必须修改正式逻辑或资料不能按本设计迁移，先停下明确范围/影响并补方案LLD，不能临时扩大开发和测试。
5. 交付原三文档/索引、两附件逐项处理结果、测试节点/结果及未覆盖；原r2设计开发文档、有效历史成绩、原图/讲稿/输入、独立波段工具保留。暂缓性能4—7批及交易助手日期TODO保持，不变相纳入清退。
6. 独立审计确认当前唯一r4/预测/页面行为及P4已验收边界不变、没有活动旧执行器/源码包/隐藏回退、保留资料均可定位后停止，交管理员验收。提交/推送/部署另按明确指令。

### 22.7 本轮审计交付记录

本次仅修改原方案/LLD及其两个逐文件设计附件和必要索引，保留上一轮P4收尾未提交内容。没有移动/删除源文件或报告，没有更改业务/测试代码、执行测试/回测/真实读源、安装、提交或部署；临时审计只读本地文件、静态AST/JSON和ZIP目录，不导入执行待退模块。

独立复核包括：103代码和3503报告路径全部存在、分类无遗漏/重复、221目标唯一、7个抽取白名单及新增两件的嵌套字段确实存在、37组222输入只作输入保留；原字节文件、6份历史说明、抽取件及Notebook的验收不混用，P4已完成项不重复开发，后续步骤依赖先迁后删。实际文档/链接/差异检查结果在末尾据实登记。这里的“第一步完成”只指审计和设计准备，不表示有效能力已迁出或旧文件可立即绕过review删除。

原第一步已核103代码/测试Git状态、3503报告原路径/文件数量/字节、221唯一目标及37组222根原始输入，实际源文件未改。两项独立审计修正后的统计以§10.3当前表为准，7件抽取与嵌套字段、22组测试设计及本轮文档检查见§22.8；静态检查不计业务测试通过。本次将本需求P4收尾、P5设计及两项审计修正一并提交，索引仅提交本需求改动，其他已有修改保留；没有迁移或删除源代码/资料。

### 22.8 两项独立审计修正及第二步交接（2026-11-03）

管理员本轮要求先补齐已发现问题、提交，再审计是否能推进下一步；不是第二步清退执行授权。本次仅修改本需求方案/LLD、两个设计附件及必要索引，并一并提交尚未提交的P4收尾文档；不改代码/测试、原报告或原图/讲稿，不进行行情读取、测量、回测、迁移、删除、部署或生产开放。

| 修正 | 当前明确口径及后续交接 |
|---|---|
| P4状态残留 | §11.3/§11.4与原技术方案当前状态统一为P3/P4已完成，P4最终证据只引§21.14.14。保留有日期的失败和当时交付记录，不再要求重做真实/页面验收；P5当前准备与实施顺序只按§10/§11.2/§22 |
| 两份来源摘要混入旧解释 | 按§10.3.3.1和附件精确根/嵌套字段抽取，原文件本轮未动。207件原样保留、7件抽取、6件说明和1件Notebook共221目标；3503总数和3282件直接删除项不变，大小统计使用原字节 |
| 配套测试 | P5-08及`test_xxm_acceptance_scope.py`清单同步两份独立字面/禁止嵌套比较回归，合法可选字段有无均保留。删原件前逐值核对，删后不再读取混合原件生成expected；不新增长期清理框架、旧源码或第二套预期库 |
| 下一步范围 | 第二步先精简有用函数和37组人工输入、迁221份资料及代码/测试/Notebook路径，定向交接通过后才删旧执行链和无用报告；第三步在旧文件物理缺席的新进程回归。103文件处理边界与P4已验收正式运行链不变 |

本轮文档检查实际通过：根文档完整性3项；103代码/测试路径、Git状态与清单一致；3503原报告路径/原大小未改；分类及744135468总原字节对齐；221目标唯一且均未创建；7件根字段及新增两件的嵌套真实字段已核；22组P5测试设计均存在。另以本批链接/差异检查核本需求文档，不将其计为业务回归通过。

提交后开工审计按以下条件判断，不能再把“P4尚未验收”作为阻塞，也不能把本轮静态通过当作第二步已经完成：正式运行链与保留函数不依赖待退代码；人工输入及原作者事实未丢失；资料目标/字段及代码消费者先迁后删；定向与删后回归的独立预期、分组、60秒及首错退出要求已明确。任一新调用方、源变化、目标占用或必须修改正式规则/接口的事实出现，停止并说明，不临时扩大范围或恢复旧算法。当前未发现需要管理员重新选择的算法口径。

### 22.9 P5第二步执行及独立审计（2026-11-03，已完成）

管理员已明确授权按方案/LLD推进第二步。开工版本e402b1820，分支dev-interface；103代码/测试原状态与附件一致，3503报告均存在且大小未变，221目标尚无占用。本轮先精简保留能力及人工输入、迁资料和消费者，完成§22.5定向交接后，才按精确清单删除旧执行链/专属测试和无用报告，清除活动命令及对应已知生成文件；不得整目录或按扩展名批删。

硬口径对账：正式src、App/API、Wealth代码及4个已验收主题工具不改；37组222根输入及7个当前核心节点保留；207原件逐字节、7抽取逐字段、6历史说明仅导航/适用范围、1Notebook仅路径与未执行单元分别验；27数值/52标签事实及缺图限制保留。测试使用现环境，禁用自动插件、bytecode和pytest缓存，每组60秒，首错或超时停止查因；原图3例若与当前r4不符停止交管理员review，禁止改规则或图证凑过。

第二步完成后只做必要的新进程导入/收集、引用/资料对账和独立审计；P5第三步整批核心/恢复/预测/Web/前端等删后回归另行推进，不把本轮定向交接记为整批回归完成。无真实源、网络、双组回测、性能重测、安装、提交、推送或部署；其他工作区改动保留。实际进展与结果在本节续记，不预先登记通过。

#### 22.9.1 代码、资料和测试交接对账

| 硬要求/设计 | 实际落点及证据 |
|---|---|
| P5-01/21/22：严格范围、先迁后删 | 开工先核103代码状态、3503原文件/原大小和221目标未占用；7模块及输入/消费者先迁、所有交接测试通过才逐项删61代码/测试及3503原目录文件，不整目录批删。清54个明确对应的生成缓存、219空目录；其他主题不动。临时进度仅记已完成路径及验证，不保存旧源码/算法或恢复库 |
| P5-02/13：最小算术保留 | near_first_review仅decimal_value/quantize_dif；top_activation_math仅pair/daily_options；real_math仅meet/minus/interval。正负、0、数量级、41.01/40.99、41.9/41.4、三位显示tie及两侧、开闭/单点均用字面预期 |
| P5-03/04/14：有效输入及当前核心不丢 | xxm_product_v1_cases仅37组222根原字面输入及时间适配；删除旧rules/checks/facts和多步oracle。test_calculator保留7函数/22参数用例及helpers；37×4在每截断点恢复继续，当前观察515参数与该组共685项通过 |
| P5-05/06/08/18：来源/摘录 | acceptance仅sha/load_source/collect_readouts，读取真实原DEA和manifest.files数据SHA，不递归旧protected源码。27原摘录唯一/独立返回；两个来源摘要用完整独立字面字典检验根与嵌套白名单，无comparison/旧任务。原三例直接load_source、有限根数/8MiB/60秒及按各终点结束 |
| P5-07/08/21：资料逐项 | 207件迁前逐字节一致；7件根及嵌套字段逐值一致且不补缺键；6历史说明仅改链接/历史范围/失效活动命令；1Notebook保留8单元、未执行/无输出。221目标全部唯一存在，附[资料索引](../../../../reports/xxm/README.md)；52观察仅指定一份，27数值不与52合计，11原图缺失限制照原保留 |
| P5-09/10/11/12：独立峰谷等能力 | local_extrema三原窗口72/63/63根、原SHA和4时间锚点保留；4份data/image身份独立于源码检查。Notebook纯返回不exec/写文件，仅明确source路径一对一比较；reference_window只保留原始局部转折/平台/价格窗口，不保留qdif/eligible/selected；saved_minute_window/量图代码原样 |
| P5-15/16/17：观察/显示/图证 | observe_rows仅使用正式r4，原1000根/20秒/256MiB/16MiB和独立复制保持；forecast_display迁当前_range_text的8组正常/错误样本；3例图证13项通过，使用当前structures/relatedStructureId和显示标记，不改作者日期/价格或保留旧new_top_DULL寿命解释 |
| P5-19/20：正式消费者和P4边界 | 旧配对/response/迁移/Git捕获专属代码已退；当前snapshot/r4_internal_results/r4_restore等及4个原工具保留。本步没有改正式src/Wealth/Spec/API/来源/缓存/预算；剩余正式分组回归属于第三步，不以本行静态核对冒称通过 |

全部221保留资料目标及3503原文件、103代码/测试的实际结果已回填两个原附件。207原件/7抽取/6说明/1Notebook分别验证，不用同一检查冒充；原代码定义/行号/状态和报告大小留作开工事实，实际文件存在/删除以执行列及当前目录为准。

#### 22.9.2 定向交接与删后新进程结果

使用现有.venv，禁插件自动加载/bytecode/pytest缓存，每组55秒工作+3秒退出+1秒强退，合计不超过原60秒；无后台任务/结果落盘。

| 组 | 实际覆盖 | 最终结果 |
|---|---|---|
| 原图事实3例 | test_xxm_confirmed_cases全文件，原CSV/图证身份及有限窗口；2024-03-11 m120上午11:30消失、2023-04-14钝化及17/18无可见旧消失、2025-06-12 m90 14:00结构 | 13 passed；组4.613秒 |
| 算术/窗口/显示/输入/来源摘录 | near_first_review、top_activation_real_math、reference_window_review、forecast_display、product_v1_cases、acceptance_scope六文件 | 87 passed；组0.274秒 |
| 局部峰谷/Notebook/分钟窗口 | local_extrema、local_extrema_study、saved_minute_window三文件 | 94 passed；组0.330秒；未执行Notebook |
| 当前核心/观察/输入恢复 | calculator、r4_observation全文件及snapshot_validation的37×4所有截断恢复节点 | 685 passed；组2.817秒 |
| 删后新进程导入 | 11个xxm保留模块及3个Python主题工具 | 14导入通过，61待退代码路径均物理缺席 |
| 删后研究主题收集 | 原testpaths静态不改，index_market/tests整目录collect-only | 3583项收集通过；组1.705秒，未执行其他主题研究 |

最终定向交接为879项，不把收集3583计作测试通过数，也不把删前交接冒称完整删后回归。首次算术/窗口组在test_multiple_raw_valleys_are_not_selected_or_hidden停止：独立手写样本包含index8的−1<0>−6，工具正确保留TOP=0，而新测试漏列这一个原始峰。逐值核对后仅补该独立expected，算法不改，再单独重跑该组87项通过后才进入后续组；失败38 passed/1 failed不计额外通过或隐去。无超时、自动重试或放宽预算。

#### 22.9.3 删后独立审计及下一步边界

开工使用CodeGraph codegraph_impact核quantize_dif的18符号影响面，结合已有explore覆盖正式计算器/查询/API/前端和保留工具；批量变更后codegraph sync/status通过，无重建索引。当前AST解析3699个保留Python文件（排除待删代码及旧reports源码），保留代码无待退模块的静态导入或动态路径；原3503路径、61代码及已登记54生成文件物理缺席，11保留模块定义与§10.2逐函数清单一致，没有旧识别step副本、Git blob执行入口、源码ZIP/文本备份或旧CLI可运行。

历史设计/开发/最终对比成绩仍在原文档，活动命令和链接改为当前保留入口/资料；旧路径仅作出处，不能当加载地址。原材料、独立波段/峰谷、最小两位算术和有效安全检查未丢；当前正式r4/下一根预测/页面/P4已验收行为均未修改。其余工作区变更保留，本步没有提交、推送、部署、安装、真实读源、旧算法/双组重放、性能重测或修无关日期TODO。

**第二步完成，停在第三步整批删后回归之前。**第三步继续按§22.6各分组验证完整核心/恢复/预测/Web/前端及架构，复用P4有效真实证据；本轮仅已完成的必要导入/收集/静态文档检查不替代该步骤。当前未发现必须改正式业务或重新拍板的阻塞。最终链接/文档/diff检查另在本节据实补记。

最终静态检查：103代码和3503原文件逐项执行结果与当前目录一致；221精确资料目标加1导航README共222文件，保留资料155556796字节（148.351MiB，不含导航README），原112目录共744135468字节（709.663MiB）。54个已知生成文件和61旧代码路径均不存在；17个保留数学/读取/扫描定义及全部现calculator测试/helpers的AST与开工基线一致。根文档完整性3项、本批28文档的971处本地链接/163锚点及限定diff检查通过。暂存区为空；没有提交或推进第三步。文档/引用/收集的通过不扩展为整批业务、真实来源或性能验收。


### 22.10 P5第三步整批删后回归执行设计（2026-11-03，执行结果见§22.11）

#### 22.10.1 目标、授权与固定顺序

本节落实产品§11.3及技术方案§24.2，不新增算法/接口/配置。目标是：在旧代码和原无用产物物理缺席的条件下，独立验证唯一正式r4的识别、结构有限跟踪、记录/恢复、历史asOf、下一根预测、普通/debug合同、前端和保留核验能力仍完整可用。前一轮只完成本文设计和3298项准备收集，未正式执行；本轮已获授权按下列清单执行，实际停点见§22.11。准备收集不能写成通过；第二步879项交接也不能代替本步删后结果。

| 顺序 | 目标 | 固定范围 | 完成本步的判断 |
|---|---|---|---|
| 1 | 确认基线、引用和收集 | 记录实际HEAD及相关已有差异，确认61旧代码缺席、221材料可定位；核保留模块/动态入口、收集全部主题而只执行本清单 | 明确测试针对的代码状态和完整清单；不运行其他研究 |
| 2 | 纯工具与保留资料 | 8个文件，独立取数/区间/峰谷/量图/取窗、37组输入、27摘录及来源摘要 | 保留能力正常可用，坏输入仍拒绝，旧执行链不再是前提 |
| 3 | 识别核心、记录、恢复和观察 | 10个文件，四周期RC规则、有限结构跟踪、历史前缀、关联/终态/复制及37×4恢复 | 唯一正式r4可独立工作；现规则和正确安全检查未丢失 |
| 4 | 下一根预测与文本 | 5个文件，先前提后边界、近处有解停止、原EMA精度、表达式和整数文本 | 单根预判及其错误/无解语义保持，未恢复中点或多步预测 |
| 5 | 原图三例 | 1个文件，原日期/价格/当前事件字段及有限离线前缀 | 删后仍满足原13项事实检查，不改作者确认或扩展为新回测 |
| 6 | API、共享加载和P4工具 | 2个主题文件和5个Web文件，临时SQLite/Gold、实际路由/客户端及自有子进程 | 普通/debug、鉴权、生产关闭、1500根/预算和退出边界保持 |
| 7 | 前端定向、类型和构建 | 28个完整文件逐个执行，再单独typecheck、build | 识别/预判/debug/波段及页面接线可用；不宣称全前端测试通过 |
| 8 | 架构、文档和独立审计 | 3份架构测试、1个组织节点、活动引用/资料/链接/结果对账 | 本需求必需回归无失败/遗漏，其他修改保留，交第四步最终交付review |

第三步只按以上顺序；全部通过并完成第8项审计才能登记本步完成。发现错误按§22.10.4停止，不将后续组作为“顺手继续”的动作。第4步P5最终交付及管理员验收仍另行交接；提交、推送、部署和生产开放不包含在本节。

#### 22.10.2 执行时登记实际代码状态，保留已有修改

- 第二步提交为f057cefaa；正式执行必须记**实际HEAD、当前dev-interface及相关已有未提交差异**。本轮文档若先提交，HEAD正常改变不代表代码异常；重新登记即可，不增加源码SHA/mtime保护或临时分支/worktree。
- 依据当前源码，`query_service._load_series`日线调用`calendar_dates(session, start=date(1990,1,1), end=now.date())`。现`test_xxm_r4_internal_results.source`的日历替身已接受`start,end`并按两端筛选；这项适配在P5开工前已存在、尚未提交，不是本轮新增规则。保留该适配执行，记录39项对应的工作区状态；禁止改回只收end、修改正式调用迁就旧替身或将其暗算作P5本轮修复。
- 以下是当前已核的相关差异，执行时再以实际文件和消费者补齐。归属仍是此前工作，**本步不提交/回退/重写它们**，也不要求清空工作区：

| 已有差异 | 当前核对到的位置 | 本步处理 |
|---|---|---|
| 日历测试替身 | `scripts/research/index_market/tests/test_xxm_r4_internal_results.py` | 上述start/end适配，作为明确测试基线，不改预期/数值 |
| 默认测试发现范围 | `pyproject.toml`增加`industry_financial/tests` | 只读核对，不改testpaths；禁止无路径默认测试带入行业研究 |
| 共享Web装配/隔离fixture | `src/app/web/app.py`、`lifespan.py`、`middleware/access_log.py`、`middleware/request_id.py`、`tests/web/conftest.py`；新stock_daily依赖/middleware及其stock_detail API/query/service消费者 | 保留现状。现Web fixture只用临时SQLite，替换交易助手和股票指标lifespan；执行前再确认不会启动正式数据任务/连接真实源。关联导入或隔离出错即停，不扩大修复其他需求 |
| 指数页面已有变更 | `wealth/src/features/index-detail/model/indexDetailState.ts`、`sidebar/IndexInfoRail.tsx`、`state/IndexDetailState.test.tsx`、`wealth/src/pages/index-detail/IndexDetailPage.test.tsx`、`index-detail-page.css` | 保留现状，纳入当前页面/构建结果的基线说明；不为P5改变其他需求文案或样本。未列入本步的state测试不被默默扩大为必跑 |

当前正式calculator/types/snapshot/query/forecast/schema、分钟Reader/合同及4个保留主题工具相对第二步提交未改，是本次准备审计事实，不保证未来永久不变。执行前发现本需求文件/共享消费者新增变化，先读当前差异确认范围和隔离；未确认则停止受影响步骤，不强行用旧准备成绩代替。报告只能写“实际HEAD加所列已有差异的工作区回归”，不能声称仅f057cefaa提交独立通过，也不能把其他任务的问题当作P5改坏。

本节使用当前原源码和CodeGraph核对查询/来源、普通识别Hook、页面debug加载及图表消费者；索引中TS测试关联缺边已由现测试正文核对。既有修改文件只读取，不新增跨工程依赖。

#### 22.10.3 范围、来源、临时产物和命令

**唯一实际测试清单是§22.10.5—9。**后端26主题文件、5Web文件、3架构文件及1组织节点共35单元；前端28完整文件，另2个类型/构建单元。每行一个新进程、顺序执行；不把多个文件拼成大组，不以`-k`/行号/skip缩减整文件。只有组织检查明确只选一个节点。

步骤1先复核两个附件及当前活动引用：61旧代码/专属tests路径不在，原报告路径不再被当加载地址，221指定目标与资料索引可定位；允许历史文档/原素材字符串保存出处。核正式src/wealth的导入/动态导入没有研究运行时依赖，11保留模块及3个Python根工具能导入，不存在旧类/step、别名、Git blob执行或旧源码ZIP/文本运行副本。旧pyc只核61待退路径所对应的明确缓存和旧报告目录；**不清产品/业务缓存或共享环境，不因合法新文件/正常文档提交而误判。**新出现的资料/他人修改只列明归属，本步不再删除报告。

收集使用现`.venv/bin/python -B -m pytest --collect-only -q -p no:cacheprovider`，并设置`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`PYTHONDONTWRITEBYTECODE=1`。显式传入`scripts/research/index_market/tests`主题整目录和表中5个Web、3个架构完整路径；同命令不要再重复添加已包含的主题文件或组织节点。全主题只做收集，其中其他统计/缠论测试不执行。将实际节点按本节35单元归属，先前准备收集的选定3298项只作核对参考；总主题节点可因其他研究正常增减，不能凑数或据此删除/skip。若本需求出现新增/缺失节点，先看具体差异并更新登记，不能静默减少覆盖。收集失败或导入触发真实源/执行旧算法，立即停止。

正式收集的完整单条命令如下，环境和60秒监督同其他单元；本轮实际收集结果见§22.11：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest --collect-only -q -p no:cacheprovider \
  scripts/research/index_market/tests \
  tests/web/test_wealth_index_detail_xxm_api.py \
  tests/web/test_wealth_index_detail_xxm_forecast_api.py \
  tests/web/test_wealth_index_detail_xxm_forecast_validation.py \
  tests/web/test_wealth_index_detail_xxm_local_routes.py \
  tests/web/test_xxm_shared_loads.py \
  tests/architecture/test_subsystem_dependency_matrix.py \
  tests/architecture/test_platform_legacy_guardrails.py \
  tests/architecture/test_operations_legacy_guardrails.py
```

每个Python测试单元在仓库根、现环境执行。下面完整命令对应步骤2第一行；后续仅将末尾替换为表中当前这一行的完整文件路径（组织检查用已列的完整节点），其他参数保持：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -q -x -p no:cacheprovider scripts/research/index_market/tests/test_xxm_acceptance_scope.py
```

输入只允许：现独立人工值、测试自己创建的临时SQLite/Gold/文件和既有被明确保留的本地材料。测试可验证真实路由/ASGI、原Reader/query/schema和实际TS客户端，但源/鉴权替换到现隔离夹具；**不连接Prod/DG/Lake正式数据，不调用采集/完整比较/投影工具的合法真实入口。**不启停或重配管理员8000服务、Wealth开发服务、DG/数据库，不改.env/Settings/鉴权。P4工具测试自己的临时loopback端口/子进程属于隔离测试，按工具权限运行；结束后关闭，不能冒称真实来源或生产性能验收。

不安装/升级依赖，不自动下载浏览器或执行npm install/npx下载。现Python、Node、npm、vitest/tsc/vite/esbuild/Pillow/PyArrow等由既有环境供给；执行前核可用，缺失即报缺项，不能让`if node`分支悄悄少执行。保留材料只由实际消费者按既有边界读取，不再次扫155MiB全部资料或重跑benchmark。Notebook只检查结构/导入/无执行输出，不运行单元。

临时夹具仅用测试原tmp_path/隔离SQLite；允许既有前端测试缓存及`wealth/dist`、`wealth/tsconfig.tsbuildinfo`等被忽略的构建产物，不改构建配置，也不把这些提交。测试摘要优先终端/原三文档；如需临时监督片段或诊断日志，仅放`/private/tmp`或系统tmp，限本次测试进程/退出和必要错误信息，**不保存市场响应、旧源码副本、业务恢复文件或新reports目录**。上一轮只编写执行设计，未创建这些脚本/日志；本轮临时监督和结果位置登记§22.11。

#### 22.10.4 每单元60秒、首次失败、中断和清理

1. 所有收集、Python整文件/明确节点、前端整文件、typecheck、build以及最后静态检查都分别作为单元。父进程在启动前记录monotonic；启动、import、收集、测试、模型/退出及摘要均计时。正常工作最多55秒，退出/清理/摘要共最多5秒，**60秒硬上限不扩大**；总轮次耗时是实际各单元之和，不能当4秒HTTP或400ms预测成绩。
2. 沿用前批临时监督方式，不新增长期runner/配置。需要的临时片段必须满足：`Popen(start_new_session=True)`；只启动当前表一行；原测试参数/fixture/内置超时保持；记录测试父PID及本次拥有的进程组。Python用`-x`，前端用`--bail=1`，收到首次失败/非零退出立即进入清理，不再领取后续行。无测试、意外skip/xfail或执行了清单外文件均不能报通过，不用passWithNoTests/retry/watch/only或更新快照绕过。
3. **不能只终止pytest/npm父进程。**P4工具会另开进程组，Vitest/Node也有后代。临时监督必须在父进程仍在时以PID/PPID/PGID建立本次后代关系并保留已见的自有组；临时监督以不超过50ms间隔维护本次PID/PPID/PGID关系，包含另开会话的子组；若自有进程树无法完整确认，不能靠只杀父进程继续本轮。55秒到期或收到取消/失败先停止调度，对本次拥有的全部存活组发TERM，最多等3秒；仍在的发KILL并最多等1秒，剩余不超过1秒完成wait/reap及摘要。祖先已知但退出后重挂的自有组仍属于清理范围；不得用进程名/全系统pkill、共享端口或无关PGID扩张目标。只观察本次pid后代，不巡查/清理别的任务。
4. 子进程返回0后仍需在同一60秒内确认本次拥有的组/自有临时服务已退出、临时连接/fixture已释放，且结果数量与选定文件一致。tmp_path物理文件沿pytest原保留/清理方式，不要求结束时目录立即消失，也不额外清共享临时目录。仅父进程结束不算干净退出。60秒内仍无法回收或权限不足以确认时，单元失败并停止，报告精确自有PID/PGID和原因，不将未验证当成功，不延长预算或恢复后续组。
5. 监督片段的独立分组/所有权来自本次Popen和其实际后代，不替换P4工具原50秒工作/60秒清理合同、虚拟时钟或产品预算；测试里故意模拟失败/超时并被正确断言的是正常用例，不把它当整轮外层失败。外层只根据测试进程退出、统计、截止和自有资源状态判定。
6. 发现失败或超时只先读错误/当前实现定位，明确是P5清退、先前未提交适配、其他需求、环境限制还是尚不确定。保留首次失败，不自动重跑或继续后续文件，不放宽阈值、不补缺数据、不改作者事实/独立expected或增加兼容。若需修改正式业务/测试/配置，先按真实原因补原方案/LLD和对应验收，涉及本步范围变化或不明确处停止讨论，不能借回归扩大开发。
7. 中断后只登记已完成行、实际代码状态、未完成/失败行及退出情况，不创建业务checkpoint/恢复文件。后续获准继续时先比对相关实际差异：代码/输入未变且证据仍适用的已通过行可复用，从未完成行继续；失败修复后只补受影响行和必要关联。若不能证明适用，明确受影响集合再决定，不默认从头整轮重跑、不跳过失败。

#### 22.10.5 步骤2—4的后端逐文件顺序

下表主题文件前缀统一是`scripts/research/index_market/tests/`；每行必须用完整前缀执行。准备数量来自2026-11-03上一轮`--collect-only`，不是本轮运行结果或强制凑齐的expected。当前26主题文件全部在表中，没有使用通配符自动扩大执行；38/1等旧失败也不累加成绩。

##### 步骤2：纯工具与保留资料

| 顺序 | 主题测试文件 | 准备收集项数 | 目标/独立依据与边界 |
|---|---|---:|---|
| 2.1 | `test_xxm_acceptance_scope.py` | 16 | 原CSV/manifest真实字段与DEA、27摘录独立返回、混合来源摘要的根/嵌套白名单；不读旧源码保护链 |
| 2.2 | `test_xxm_near_first_review.py` | 24 | 纯两位算术：正负、0、数量级、相等、非法数及两类反例；不构造策略 |
| 2.3 | `test_xxm_top_activation_real_math.py` | 12 | pair/daily_options与meet/minus/interval：分数、三位来源精度、开闭及单点；无旧多步oracle |
| 2.4 | `test_xxm_reference_window_review.py` | 9 | 原始峰谷、平台、未闭合窗口、零柱及价格/时间；不输出参照选择或资格 |
| 2.5 | `test_xxm_product_v1_cases.py` | 11 | 37组222根原字面输入、时间适配、不可变和独立返回；旧业务预期不恢复 |
| 2.6 | `test_xxm_local_extrema.py` | 47 | 扫描器、确认/尾部、原三个小窗口和量图字面边界；不执行benchmark |
| 2.7 | `test_xxm_local_extrema_study.py` | 6 | 原字段/时间/数值、4份数据/图片身份、8单元Notebook结构及纯返回；不执行Notebook |
| 2.8 | `test_xxm_saved_minute_window.py` | 41 | 原90分钟临时CSV的列、字节/行/定位、顺序、SHA及数值边界 |

##### 步骤3：识别核心、记录、恢复和观察

| 顺序 | 主题测试文件 | 准备收集项数 | 目标/独立依据与边界 |
|---|---|---:|---|
| 3.1 | `test_xxm_calculator.py` | 22 | 保留7函数/22参数当前核心：首次当根价、B→A、1%、零、突破优先及复制/恢复 |
| 3.2 | `test_xxm_r4_rules.py` | 504 | 当前RC规则全序列及顶底镜像、四周期、近远选择、曾击穿、结构与消失优先级 |
| 3.3 | `test_xxm_r4_following.py` | 437 | 首次反色起逐根比价、零/分隔/单根段、首个有效段结束、当根新钝化遮旧消失 |
| 3.4 | `test_xxm_r4_restore.py` | 285 | 当前结构/跟踪/终态全字段、连续与恢复、拒旧及坏副本不污染原对象；285为首轮准备数，补样本及24个缺字段反例后的续做数量见§22.12 |
| 3.5 | `test_xxm_r4_internal_results.py` | 39 | 内部结构聚合/历史前缀/窗口关联/拒坏结果；采用已登记start/end日历替身 |
| 3.6 | `test_xxm_input_validation.py` | 101 | 真实类型、有限数值、完成根、时间/周期及合法正常变化不误拦 |
| 3.7 | `test_xxm_snapshot_validation.py` | 249 | 当前快照字段/身份/引用；全部37×4人工输入的每截断点恢复继续 |
| 3.8 | `test_xxm_snapshot_consumers.py` | 21 | clone/查询/预测等真实恢复消费者和失败隔离；不造旧兼容入口 |
| 3.9 | `test_xxm_r4_observation.py` | 515 | 正式record_decisions分支及有/无观察业务相同、1000/1001根、20秒/256MiB/16MiB和独立复制 |
| 3.10 | `test_xxm_r4_following_query.py` | 27 | 跟踪与历史asOf、普通/debug引用及窗口；为后续预测/API提供同一事实 |

##### 步骤4：下一根预测与文本

| 顺序 | 主题测试文件 | 准备收集项数 | 目标/独立依据与边界 |
|---|---|---:|---|
| 4.1 | `test_xxm_key_point_forecast.py` | 95 | 当前单根前提、近处有解停止/无解再远、边界极值、校准与无解语义 |
| 4.2 | `test_xxm_p3_forecast_math.py` | 60 | 原EMA逐步运算及有限边界、精度/严格等号/无界；不使用中点或全float遍历 |
| 4.3 | `test_xxm_r4_following_forecast.py` | 93 | 考核期/首次反色后有限跟踪的下一根变化、价格门槛及单根段情况 |
| 4.4 | `test_xxm_forecast_expression_contract.py` | 86 | 现闭合六类单根表达式、类型/非有限/缺键拒绝；旧多步只作拒绝反例，清理见§22.15 |
| 4.5 | `test_xxm_forecast_display.py` | 15 | 当前_range_text的整数范围、单点、无上界/无整数及坏字段；不重新求价 |

#### 22.10.6 步骤5：三例原图事实与既有离线源边界

只执行主题整文件`test_xxm_confirmed_cases.py`（准备收集13项），保留其9项原文件字节检查、1项抽取事实及3个已确认案例。路径全部为`reports/xxm/`收敛后的现目标，由现测试中的DAILY/MINUTES/PINNED_FILES明确给出，不恢复旧目录或Git算法。

| 周期/源 | 原CSV根数/其他范围 | 只保留的观察窗口与停止端点 | 必须保持的独立事实 |
|---|---|---|---|
| day，`sources/xxm_reference_rescue_r1_implementation_20261017/daily_2020_source_01/` | daily_source.csv1643根；manifest、calendar.json2571行及其原数据身份 | 原首根空状态推进，到2023-04-21停止，只存2023-03-07—04-21窗口 | 3/7结构原价3328.3927/参照DIF41.186；4/14钝化；17/18无可见旧消失；4/21新结构与旧ID不同 |
| m120，`sources/xxm_source_audit_20261013_213852/` | minute_120_source.csv8630根及原manifest | 原首根推进，到2024-03-11 15:00停止，只存3/6 15:00—3/11 15:00 | 3/11上午11:30出现原顶部结构价格消失；3052.2827>3051.3457，DIF仍较前根下降；原图不是证明唯一软件公式 |
| m90，同上述MINUTES目录 | minute_90_source.csv12945根及原manifest | 原首根推进，到2025-06-12 15:00停止，只存6/12 11:00—15:00 | 新结构在14:00、收盘3401.2473，15:00不重复；沿管理员原时间更正 |

现case_windows的六个源/manifest/日历文件合计8MiB上限和每根标准校验/升序唯一保持；测试原内部60秒guard不改，外层仍先按55秒停止工作、清理到60秒。只是既有单组事实回归，不做新策略结果对比；CSV全读取及其有限前缀计算是已批准测试的原做法，不新增第二组/新日期或保存全历史结果。

这三例离线输入与普通分钟接口1500根是不同入口。保留案例既有前史，不能把它随意裁成1500使事实变化，也不能据案例允许产品接口恢复上万根读取。原MACD/DEA/柱值直接使用，禁止补算缺DEA、改图证/日期或用当前算法生成expected。字节检查只核原材料身份，不核产品源码SHA。11条其他历史原图缺失限制继续如实保留，不扩成找图任务。

#### 22.10.7 步骤6：原窗口、P4工具和API

##### 步骤6前半：原窗口和P4核验工具

| 顺序 | 主题测试文件 | 准备收集项数 | 目标/独立依据与边界 |
|---|---|---:|---|
| 6.1 | `test_xxm_daily_window_precheck.py` | 11 | 纯窗口/SSE/原DEA和隔离客户端的正常/错误路径及finally恢复 |
| 6.2 | `test_xxm_p4_audit_tools.py` | 174 | 原工具完整人工合同、1500根/计数/缓存/客户端、真实本机隔离通信及子进程退出；不调用正式CLI |

步骤6后半按下表顺序，每行整文件，前缀为`tests/web/`。原Web共享conftest会创建其临时SQLite表和隔离lifespan，不能删autouse fixture或导入替身来躲开真实请求路径。临时Gold按现生产者字段合同，不能按消费者猜列；不把临时数据通过当正式Lake接入新验收。

| 顺序 | Web测试文件 | 准备收集项数 | 目标/边界 |
|---|---|---:|---|
| 6.3 | `test_wealth_index_detail_xxm_api.py` | 187 | 真实路由/query/普通和debug、鉴权/拒参、窗口/时间/引用、临时两源与读取界限 |
| 6.4 | `test_wealth_index_detail_xxm_forecast_api.py` | 117 | 完整单根普通/debug、原EMA/范围/预算/缓存、临时SQLite/Gold及错误退出 |
| 6.5 | `test_wealth_index_detail_xxm_forecast_validation.py` | 47 | 完整响应模型、身份、表达式、引用与非法/正常变化 |
| 6.6 | `test_wealth_index_detail_xxm_local_routes.py` | 14 | 显式本地/生产/缺配置注册、缺分钟时日线/鉴权、原K线debug合同；生产反例禁止源调用 |
| 6.7 | `test_xxm_shared_loads.py` | 3 | 共享一次加载、取消/失败不污染其他请求，不把完成加载误当长期TTL |

步骤3保留RC01—110业务规则覆盖，37×4恢复每个截断点不缩减；内部造错和公共检查的重复矩阵按§22.15清理。步骤4只验单根预测；旧多步表达式不再作为接受合同，r1Contract等明确拒旧用例保留，不能仅按名字删除。步骤6保留P4真实客户端/ASGI/通信/取消/清理正反例，但不重复P4真实来源请求；自然并发未重叠的历史not_verified不改成新阻塞。

#### 22.10.8 步骤7：28个前端文件、类型检查和构建

工作目录仍仓库根；npm使用现`wealth/package.json`（test=`vitest run`，typecheck=`tsc --noEmit`，build=`tsc -b && vite build`）。当前安装Vitest3.2.4，文件过滤使用包含匹配，因此下表传`src/`起的完整唯一文件路径，执行前核没有第二个路径包含该完整文本，输出必须正好选中这一文件。每行独立进程，沿§22.10.4截止/清理；不合并目录跑默认全Wealth，不添加`.only`、更新快照或隐藏不适用合同。

```bash
npm --prefix wealth run test -- src/features/index-detail/xxm/apiClient.test.ts --bail=1
```

`vitest run`禁watch，`--bail=1`首次失败停止；不使用retry/passWithNoTests。CLI过滤/非watch按Vitest3.2.4官方文档及已安装CLI定义核对（Context7库`/vitest-dev/vitest/v3_2_4`，[官方过滤说明](https://github.com/vitest-dev/vitest/blob/v3.2.4/docs/guide/filtering.md)、本地`node_modules/vitest/dist/chunks/cac.*.js`的bail定义），不安装新版本或引入新配置。

以上完整命令对应下表第一行；后续仅替换为当前这一行文件。下表所有路径均从`wealth/`开始，相应命令参数去掉最前面的`wealth/`，即保留`src/...`。顺序跨五类连续：

| 顺序 | 类别 | 完整前端文件 |
|---|---|---|
| 7.1 | 识别 | `wealth/src/features/index-detail/xxm/apiClient.test.ts` |
| 7.2 | 识别 | `wealth/src/features/index-detail/xxm/adapter.test.tsx` |
| 7.3 | 识别 | `wealth/src/features/index-detail/xxm/rearmContract.test.tsx` |
| 7.4 | 识别 | `wealth/src/features/index-detail/xxm/markerGeometry.test.ts` |
| 7.5 | 识别 | `wealth/src/features/index-detail/xxm/useIndexXxmLayer.test.tsx` |
| 7.6 | 预测 | `wealth/src/features/index-detail/xxm-forecast/apiClient.test.ts` |
| 7.7 | 预测 | `wealth/src/features/index-detail/xxm-forecast/expressionContract.test.ts` |
| 7.8 | 预测 | `wealth/src/features/index-detail/xxm-forecast/identity.test.tsx` |
| 7.9 | 预测 | `wealth/src/features/index-detail/xxm-forecast/r1Contract.test.tsx` |
| 7.10 | 预测 | `wealth/src/features/index-detail/xxm-forecast/forecast.test.tsx` |
| 7.11 | debug | `wealth/src/features/index-detail/debug/dependencyBoundary.test.ts` |
| 7.12 | debug | `wealth/src/features/index-detail/debug/useIndexDebugModule.test.tsx` |
| 7.13 | debug | `wealth/src/features/index-detail/debug/xxmDebugContract.test.ts` |
| 7.14 | debug | `wealth/src/features/index-detail/debug/forecastDebugContract.test.ts` |
| 7.15 | debug | `wealth/src/features/index-detail/debug/IndexRecognitionDebug.test.tsx` |
| 7.16 | 独立波段 | `wealth/src/features/index-detail/daily-wave/apiClient.test.ts` |
| 7.17 | 独立波段 | `wealth/src/features/index-detail/daily-wave/adapter.test.ts` |
| 7.18 | 独立波段 | `wealth/src/features/index-detail/daily-wave/markerGeometry.test.ts` |
| 7.19 | 独立波段 | `wealth/src/features/index-detail/daily-wave/presentation.test.ts` |
| 7.20 | 独立波段 | `wealth/src/features/index-detail/daily-wave/DailyWavePrimitive.test.ts` |
| 7.21 | 独立波段 | `wealth/src/features/index-detail/daily-wave/DailyWaveLayerUi.test.tsx` |
| 7.22 | 独立波段 | `wealth/src/features/index-detail/daily-wave/useDailyWaveReview.test.tsx` |
| 7.23 | 页面与图表接线 | `wealth/src/features/index-detail/model/indexRecognitionAvailability.test.ts` |
| 7.24 | 页面与图表接线 | `wealth/src/features/index-detail/api/indexDetailRequestScheduler.test.ts` |
| 7.25 | 页面与图表接线 | `wealth/src/features/index-detail/chart/IndexChartWorkspace.test.tsx` |
| 7.26 | 页面与图表接线 | `wealth/src/features/index-detail/chart/IndexMinuteChartWorkspace.test.tsx` |
| 7.27 | 页面与图表接线 | `wealth/src/pages/index-detail/IndexDetailDailyWave.test.tsx` |
| 7.28 | 页面与图表接线 | `wealth/src/pages/index-detail/IndexDetailPage.test.tsx` |

识别/预测合同及Hook文件验证实际解码/请求/状态；debug组验证普通入口不加载辅助实现、URL切换允许既有重请求、模块ready不额外重刷、手动波段/取消/迟到；波段组验证原峰谷/层展示。图表接线两文件现使用共享图表/识别Hook替身，覆盖props/原曲线稳定，不把它们单独称真实图表或完整识别端到端；由真实Hook/适配器和页面文件共同覆盖。页面整文件含其当前其他需求样本，保留原样，失败说明归属，不为P5改成分缺行情或无关日期。

28文件通过后依次执行两个独立单元，每个仍完整60秒预算。下列两行分别启动，第一行通过且清理成功才允许启动第二行；不得放进同一个未检查首条退出码的shell脚本连续执行：

```bash
npm --prefix wealth run typecheck
npm --prefix wealth run build
```

typecheck/build按现tsconfig检查整个Wealth源码并生成现构建产物，这是既有编译边界，不等于执行全Wealth测试。若无关代码导致类型/构建失败，同样停止并报告具体文件/原因，不能忽略、回退他人修改或宣称本步完成。构建原有大包提示只记录，不启动打包优化。交易助手日期TODO不修、不skip，不对外声称“全部前端测试通过”。本轮页面行为不改，复用P4管理员页面验收，不重启浏览器或服务强行增加人工轮次；若发现清退确实影响页面，先补受影响方案再决定最小复验。

#### 22.10.9 步骤8：架构、组织、文档及执行结果对账

以下4行分别执行，命令形式沿§22.10.3；组织只选明确节点，不执行其同文件旧历史归档/回测测试。

| 顺序 | 完整测试文件/节点 | 准备收集项数 | 目标 |
|---|---|---:|---|
| 8.1 | `tests/architecture/test_subsystem_dependency_matrix.py` | 4 | 当前依赖方向/研究依赖约束及QTF边界 |
| 8.2 | `tests/architecture/test_platform_legacy_guardrails.py` | 3 | 防止旧platform包/主实现回流 |
| 8.3 | `tests/architecture/test_operations_legacy_guardrails.py` | 9 | 防止旧operations运行链/规格/状态实现回流 |
| 8.4 | `scripts/research/index_market/tests/test_research_layout.py::test_single_location_roots_and_pytest_discovery` | 1 | 只运行该节点：主题唯一位置/迁移清单/现testpaths；不运行同文件旧归档/其他研究验证 |

之后把如下静态检查分别作为≤60秒单元，不混入其他业务测试：

1. 再核正式src/wealth、11保留模块、CLI/动态入口/Notebook/研究README及实际消费者；不新增或恢复旧r2/研究r4/完整两位算法。真实数据检查/峰谷工具与正式识别依赖仍分开，不用源码SHA作保护。两CSV的103代码结果/3503原文件处置和221目标全部能解释，其他主题不处理。
2. 复用第二步迁前207件逐字节/7件逐字段交接事实；本步核221指定目标和实际消费者所需数据身份/字段，不再次全读155MiB所有原件。7个抽取件按附件批准根键及两个摘要的嵌套白名单检查，现独立字面tests继续核保留值；不恢复原混合模型解释当expected。6历史说明只保留历史事实，新Notebook8单元未执行；52观察只指定一份、27数值/11缺图限制不变，不把材料数量相加当独立样本。
3. 执行现`.venv/bin/python -B scripts/check_docs_integrity.py`，核原三文档及实际改动的资料/导航本地链接和锚点、限定diff。全仓其他需求diff不作为本步修改；遇到本任务外文档问题列归属，不能随手修。历史原件自带EOF空行不格式化，保持数据字节身份；本步新写的方案/LLD/摘要按正常空白检查。
4. 复核本次所有测试自有进程/临时服务退出、既有共享服务未操作、原材料/业务/测试/配置未被本轮修改、暂存区不夹带其他工作。代码或输入已变的成绩标明失效/需复验集合，不能把变化前后成绩拼成同一基线的“全过”。

报告至少包含：实际分支/HEAD和相关已有差异；35后端行和28前端行、typecheck/build的实际选择/数量/pass/fail/skip/耗时/退出；静态检查；P5-01—22覆盖与未覆盖；中断/失败/续做明细；证据类型和复用范围。所有参数化节点必须完整执行，准备3298和前端文件数只用于找漏，不替代逐项业务结论。先前收集3583/3298和第二步879均单列，不能累加为本步新增通过。

**全部明确单元通过、没有未解释的失败/意外跳过/退出残留、独立审计与实际范围一致**时才登记“P5第三步回归完成”；否则保留已通过行并明确未完成。第三步只向P5第四步交付这些结果，P5整体最终验收、提交/部署/生产开放均不自动完成。真实来源/性能/页面继续沿P4已验收边界，不声称本步再次实测或新增全部视频一致性。

#### 22.10.10 前一轮文档交付及独立审计

本轮仅补原产品/技术方案/LLD，清除P5当前章节仍要求“先做第二步/confirmed读取尚未迁”的残留，保留有日期的真实历史记录。当前第三步清单/工作区基线/数据与子进程界限已明确，未改任何业务/测试/配置或材料，没有运行上述回归/新收集、安装、读真实源、重放、执行Notebook、提交或部署。前一轮35项路径收集3298用例、第二步13图证/879交接与3583主题收集仅作准备/历史证据；本次不将其提升为正式回归通过。

逐条对照产品8步、本文逐文件清单、当前代码/fixture/前端消费者和测试发现；完整文件存在/唯一、26主题无遗漏、35后端准备数量之和3298、28前端及两编译单元互不重复。当前唯一r4/单根/原EMA/1%/来源和预算不变，原材料9字节身份+抽取事实+3例的13项及有限前缀保持，P4工具隔离退出与实际工作区归属已区分；没有新的业务规则需要拍板。本节交管理员review，之后获准才执行；实际文档检查在下面据实登记。

本次独立文档检查结果：原三文档的8步目标表逐行一致；LLD的10个子节及实际步骤5→6→7→8的正文顺序一致；35后端单元路径/节点存在且无重复，包含全部26个现XXM主题文件，准备数量相加3298；28前端文件路径存在且按Vitest包含过滤均唯一，另列typecheck/build两个单元；所选文件未发现skip/xfail/only/todo标记。根文档完整性3项、同需求28文档971处本地链接及163锚点、原三文档限定diff检查通过。上述只验证文档、实际落点和执行安排，不执行测试或升级既有成绩；本轮仅三份原文档有本任务新增改动，待管理员review。


### 22.11 P5第三步执行登记（2026-11-03，首错停止、未完成）

管理员本次已明确授权按第三步方案/LLD完成回归。§22.10.10记录上一轮准备时点，本次执行结果以下文为准。当前分支dev-interface，实际开工HEAD=ea9fa3fd6（行业研究提交），第二步P5提交仍f057cefaa；当前正式r4/预测/Reader/4个主题工具相对第二步未改。日历测试start/end适配及共享Web、页面等此前未提交差异沿§22.10.2单列，既有三份方案/LLD准备修改保留；本轮不清空工作区或代提交其他需求。

执行约束逐项对账：35后端单元/28前端文件/类型检查及构建，严格按步骤1—8顺序；每行新进程、55秒工作+5秒清理/摘要，首次失败或超时停止；真实路由/客户端只使用原隔离SQLite/临时Gold或明确原材料，三例沿原根数/8MiB/终点；不读正式源、不回测、不改规则/独立预期、不执行Notebook/benchmark、不安装、不提交/部署。临时监督仅按§22.10.4掌握本次PID/PPID/PGID及后代，清理自有组、不影响共享服务。

本次已核当前引用/61旧代码缺席/221目标、环境、原隔离fixture及正式代码相对第二步无变更；实际收集和逐文件结果如下。前一轮3298项收集、第二步879交接及P4真实证据不累加为本轮通过。原三文档在首次正式单元前同步本次授权和停点，不预先写成功。

#### 22.11.1 步骤1实际核对与收集

- 对正式src及保留代码/测试共1390份Python文本核静态引用，61个待退源码/测试及其对应旧pyc均缺席；221指定资料目标存在，7件抽取根键及嵌套白名单保持。14个保留模块/工具在新进程导入成功。该静态/导入单元2.541秒，不是1390项测试通过，也没有执行Notebook、量图benchmark或真实行情工具入口。
- CodeGraph已sync，返回Already up to date；explore核`IndexDetailXxmQueryService/_load_series/calendar_dates/useIndexXxmLayer/useIndexDebugModule`的来源与页面消费者，TS测试缺边沿当前正文补核。正式核心/预测/Reader及4个根工具相对f057cefaa无diff，不用源码SHA作保护。
- 按§22.10.3完整命令正式收集3967项，归入35个实际Python单元的仍为3298项；2.156398秒，退出0、无自有残留。其余669项仅收集，不执行，不加入通过数。当前Web fixture使用临时SQLite，交易助手/股票指标lifespan已被隔离，尚未进入Web执行。

#### 22.11.2 逐文件实际结果与首错停点

以下秒数是各新进程从启动到退出/检查完成的完整耗时，包含导入/收集；不是产品4秒识别或400ms预测的性能结果。文件均位于`scripts/research/index_market/tests/`，原参数`-q -x -p no:cacheprovider`及插件/字节码关闭不变。

| 单元 | 测试文件 | 本轮通过 | 本轮失败 | 完整耗时（秒） | 退出/自有资源 |
|---|---|---:|---:|---:|---|
| 2.1 | `test_xxm_acceptance_scope.py` | 16 | 0 | 0.267126 | 0，已退出 |
| 2.2 | `test_xxm_near_first_review.py` | 24 | 0 | 0.212206 | 0，已退出 |
| 2.3 | `test_xxm_top_activation_real_math.py` | 12 | 0 | 0.214313 | 0，已退出 |
| 2.4 | `test_xxm_reference_window_review.py` | 9 | 0 | 0.216562 | 0，已退出 |
| 2.5 | `test_xxm_product_v1_cases.py` | 11 | 0 | 0.217227 | 0，已退出 |
| 2.6 | `test_xxm_local_extrema.py` | 47 | 0 | 0.296119 | 0，已退出 |
| 2.7 | `test_xxm_local_extrema_study.py` | 6 | 0 | 0.246702 | 0，已退出 |
| 2.8 | `test_xxm_saved_minute_window.py` | 41 | 0 | 0.253547 | 0，已退出 |
| 3.1 | `test_xxm_calculator.py` | 22 | 0 | 0.374979 | 0，已退出 |
| 3.2 | `test_xxm_r4_rules.py` | 504 | 0 | 0.904975 | 0，已退出 |
| 3.3 | `test_xxm_r4_following.py` | 437 | 0 | 6.261496 | 0，已退出 |
| 3.4 | `test_xxm_r4_restore.py`（未跑完） | 16 | 1 | 0.263352 | 1，首错停止，已退出 |

步骤2共166项；步骤3前三文件共963项，恢复文件先通过16项再失败。**实际合计1145 passed、1 failed、0 skip/xfail/xpass；11个文件完整通过，1个文件部分执行。**失败文件准备285项，本次仅执行17项，余268项未运行。其后53个测试/编译单元均未启动；Python选定总数中仍有2152项未运行，不把收集或前批成绩当本轮通过。

首错为`test_xxm_r4_restore.py::test_rc71_literal_progress_restores_exactly[1-STRUCTURE-day]`。pytest原摘要为`1 failed, 16 passed in 0.07s`，恢复调用抛`ValueError: Invalid structure snapshot fields`；该0.07秒为pytest自身统计，与上表完整进程耗时分别保留。本次临时监督位于`/private/tmp/p5_step3_run.py`，实际结果为`/private/tmp/p5-step3-20261103-_59q13t7/results.json`，状态failed、failedUnit=3.4；只保存进程/错误摘要，不含行情响应或旧源码。所有已启动单元均clean=true、residualGroups为空；失败组PGID=3346已退出，没有继续调度或操作共享服务。

#### 22.11.3 只读原因定位及修复边界

已使用CodeGraph explore核`literal_snapshot/validate_structure_facts/_STRUCTURE_FIELDS`，并读当前实际生产者、类型及手写样本：

| 当前依据 | 已核事实 |
|---|---|
| `src/biz/services/wealth/market/index_detail_xxm/types.py::XxmStructureRecord`、本文§2.3 | 统一结构记录19个字段，含后续同色柱根数和跟踪价格极值/日期 |
| 同目录`calculator.py::_start_structure` | 本例尚未首次反色，实际生产者初始化`nextSameColorCount=0`、`trackingPriceExtreme=None`、`trackingPriceExtremeAt=None` |
| 同目录`snapshot_validation.py::validate_structure_facts` | 按上述19字段精确检查，不接收缺字段旧记录；已有§2.3明确不补缺省兼容旧副本 |
| `test_xxm_r4_restore.py::literal_snapshot`的STRUCTURE分支 | 只有16个字段，无多余字段，恰缺上述3个；在进入业务恢复前就被字段检查拒绝 |

通俗地说：测试手工写了一份“已经形成结构的计算进度”，但漏写了后续同色柱数量、跟踪中的价格及发生日期三个栏目。正式程序本来就会填写这些栏目，恢复检查要求它们齐全，缺栏目的测试样本因此失败。本例尚未进入后续跟踪，这三个值应为0、空、空，不需要猜价格或改识别规则。

该手写测试最后修改为a183d6753，正式类型最后修改为50b0f22bb；当前测试/类型/恢复/计算器相对P5第二步f057cefaa均无diff。因此首个失败属于先前测试样本未跟随正式字段更新，不是本轮清退改了恢复行为。这里只解释已发生的首个错误，不能推断补3字段后其余268项或其他测试一定通过。

本轮按§22.10.4只定位并记录，**没有修改业务代码、测试样本、expected、恢复校验或Spec；没有重跑或跳过失败。**后续修复须先在原方案/LLD落实对该手写样本及其实际消费者的检查和验收安排，按正式生产者/§2.3独立补齐字面字段，不能把计算器输出直接当expected，也不能给恢复检查增加缺省兜底。获准修复后复验受影响完整文件及必要关联，再按实际差异决定复用已通过行、接续未执行行；不擅自整轮重跑。

#### 22.11.4 P5-01—22覆盖、未覆盖及独立审计结论

| 设计项 | 本轮证据与限制 |
|---|---|
| P5-01 | 当前静态/动态入口和14导入完成；正式/研究运行时不依赖已退代码。完整API/前端仍未运行 |
| P5-02、03、05、06、09、10、11、12、13 | 步骤2对应8文件166项通过；独立数值、37组材料、原输入读取/摘录、峰谷、Notebook静态、量图及纯算术按原样本检查。没有执行Notebook或新回测 |
| P5-04 | 恢复文件首错，37×4每截断恢复所在文件尚未运行，不能报恢复整体验收通过 |
| P5-07、08、21 | 指定221目标/抽取键及身份定位完成，迁前逐字节/叶值复用第二步适用证据；52观察去重和资料处置不再重做，也不升级为本轮全部测试通过 |
| P5-14 | 22核心及504规则/437跟踪用例通过；RC恢复部分仍受首错阻塞，不把整批RC或结构恢复写成全过 |
| P5-15、16 | 正式观察及预测文本文件均未执行 |
| P5-17、18 | 原图三例13项及其离线读取本轮未执行；第二步13项仅历史证据 |
| P5-19 | 记录/恢复/查询/Web拒错覆盖未完成，不用旧suite或先前成绩替代 |
| P5-20 | 四工具代码及消费者静态核对完成，实际工具/API/前端合同均未执行 |
| P5-22 | 本次首次失败立即停止、保留已完成结果和实际基线、自有进程退出已验证；修复后的续做尚未发生 |

本轮独立对账：执行清单沿原设计，步骤1→2→3.4顺序未倒置；没有少选失败节点、继续下一组、提高预算、补值或改标签预期。步骤3.5—3.10、步骤4—8所有测试及前端编译尚未执行；本次收尾只核本文结果和本任务文档差异，不冒充第8步整批审计完成。其他工作区修改保留，未重新读正式源、对照r2、执行Notebook/benchmark、安装、提交、推送或部署。

**结论：P5第三步未完成，停在3.4首个失败；P5第四步及整体收尾不得提前开始。**产品§11.7、技术方案§24.2及本文当前停点同步。文档静态核对只验证这份执行登记，不替代未执行的业务回归。

本次执行登记的收尾静态核对：原三文档8步目标表一致，LLD§22.10的35后端/28前端及两个编译单元完整且唯一、依赖顺序保持；根文档完整性3项、同需求28文档971本地链接/163锚点及原三文档限定diff空白检查通过。该核对没有执行更多测试、收集或重试，不计入1145项通过数。本轮仅原三份方案/LLD有本任务新增改动；先前准备改动及其他工作区修改继续保留，暂存区为空。

### 22.12 P5第三步样本修复与续做设计（2026-11-03，实际结果见§22.12.3）

管理员已明确要求“先补齐测试样本，然后续跑剩余回归”。本节先于测试修改和续做落实，只修`test_xxm_r4_restore.py`手写记录缺项及同文件相关样本，继续§22.10固定顺序/范围/预算/首错退出；不改正式识别、恢复检查、预测、API/前端、Spec、来源或配置，不启动P5第四步。§22.11保留首次失败原事实，本次修复和续做独立登记，不覆盖首错或把其已过16项重复加进新合计。

#### 22.12.1 当前代码依据和具体改动

当前dev-interface/HEAD仍ea9fa3fd6，正式XXM目录及该恢复测试相对f057cefaa尚无diff；原三份文档和其他工作区差异保持。CodeGraph explore核parse/validate及正式schema消费者，当前§2.3、`types.XxmStructureRecord`的19字段和`calculator._start_structure`一致。`literal_snapshot`只在本文件使用；不修改正式校验来接收16字段。逐项改动如下：

1. `literal_snapshot`的STRUCTURE分支补独立字面`nextSameColorCount=0`、`trackingPriceExtreme=None`、`trackingPriceExtremeAt=None`。本例尚未首次反色，无后续同色段，不存在跟踪价格；顶底及日/60/90/120分钟共用该准确含义，不调用计算器/校验器生成expected。
2. `test_structure_record_validator_checks_both_live_and_terminal_contract`中的FOLLOWING样本已首次反色，跟踪价格不能仍None。明确反色根收盘100，`trackingPriceExtreme=100`、`trackingPriceExtremeAt=firstOppositeAt`；dif_turn为t5、原段高点103，color_flip为t4、原段高点102。两者尚无后续同色段，count=0；ASSESSING及首次反色前的DISAPPEARED仍沿None。保持原四种status/route及全部已有断言。
3. `test_terminal_structure_invalid_transitions_are_rejected`的共同合法FOLLOWING前置样本同样填t5收盘100/日期t5，并在注入各项错误之前先用当前validator确认原样本合法，防止“本来缺字段”掩盖待测转换错误。故意退回首次反色前的old_reason/color_flip_unlocked反例同时把跟踪极值/日期还原None，使失败来自其旧原因/错误route，不被无关残留跟踪事实抢先拒绝。其他故意坏样本不自动补值。
4. 同文件新增缺三字段的反向恢复用例：3字段×2方向×4周期=24项。先用完整字面样本恢复并留存现对象；只删除当前待测字段，要求`ValueError`且原对象和输入仍原样。这样合法样本可接受、缺项仍拒绝都有独立依据，不仅修一个成功路径；不得弱化旧断言、加skip、换快照或接受缺省。

测试输入/预期值的修正依据是当前真实生产者、正式类型及§2.3，不是根据失败输出来猜值。原`test_rc71_literal_structure_is_the_actual_kernel_contract`继续走真实step并与手写记录逐字段相等，原clone/拒错/每截断/深复制检查保持。285旧准备项保留且只新增24项，本次3.4预期收集309项；35后端单元、28前端文件和两个编译单元不变，后端选定总数相应为3322。3298/285及首次1145 passed、1 failed均仅原轮次事实，不能改写。

#### 22.12.2 修复验收和续做顺序

1. 先对本节与产品/技术方案作独立静态核对，再改上述唯一测试文件。当前只有该文件需要修复；其他正式代码/测试的新增问题不随本节获得修复授权。
2. 只收集改变的恢复整文件，沿原环境和独立60秒单元，命令为`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest --collect-only -q -p no:cacheprovider scripts/research/index_market/tests/test_xxm_r4_restore.py`；应为309项。未改的其余34单元沿用首轮逐节点收集记录，不再次收集整个主题/其他研究。
3. 正式从3.4完整文件309项重跑，不能只跑前次失败节点或略去其已过16项；之后按3.5—3.10→4→5→6→7→8逐行推进。上一轮2.1—2.8及3.1—3.3共11完整文件1129项，在正式实现、输入和这些测试均未变且没有import本次literal helper的条件下复用，不重跑。当前39项日历适配及Web/页面差异仍单列；本次只改恢复文件，不能冒称提交本身无其他修改。
4. 临时监督沿用`/private/tmp/p5_step3_run.py`的55秒工作+5秒退出/摘要、实际后代进程组识别和首次失败停止。只为本次明确授权加入续做分支：保留旧results原样，另建临时结果目录，明确记录前次11行复用与新的执行行；已失败行不复用成功、收集只更新该文件数量；调度3.x跳过的只能是已核可复用完整通过行。没有业务恢复文件、长期runner、自动重试、后台续做或新配置。
5. 全部完成后按§22.10.9完成静态、引用/材料、文档及独立审计；最终统计1129复用+本次新通过项，恢复文件旧16项不重复计数，前端另记文件/测试数。若再次失败，立即清理并停止整批，只读定位原因、更新原三文档和未执行范围，不能自行修改别的样本/业务规则或继续下一行。

读写/失败/中断、隔离fixture和材料身份继续完整遵守§22.10.2—4；不连接正式DB/Lake、不做新回测/Notebook/benchmark、不安装、不操作共享服务、不提交/推送/部署。单元完整60秒包含启动、运行、停止与摘要；最后静态审计也按原独立60秒单元。复用证据只作原范围交接，不把本轮隔离测试升级为新的真实来源/性能/视频或页面验收。

#### 22.12.3 本轮实际修复、续做及第二次停止

本节设计先于编码写入原三文档，随后仅修改`test_xxm_r4_restore.py`：补齐STRUCTURE三字段、FOLLOWING正反例的真实跟踪事实和错误注入前合法检查，新增24个缺字段拒绝恢复用例。CodeGraph explore及当前源码核对了正式类型/恢复/schema消费者；正式XXM目录相对f057cefaa仍无diff，未改规则、校验、Spec、业务输入或API。未发现其他测试import该文件的helper，故原11完整文件1129项继续适用。其他工作区修改保持，未提交。

| 本轮单元 | 范围/选择 | 实际结果 | 完整耗时（秒） | 退出与自有进程 |
|---|---|---|---:|---|
| 局部收集 | 只收集改变的恢复整文件 | 309项，与原285+新增24一致；其他收集记录复用 | 0.290070 | 0，PGID52574已退出 |
| 3.4 | 完整恢复文件，`-x`首错停止 | 301 passed、1 failed，余7项未执行；24个新反例均已通过 | 0.912522 | 1，PGID53358已退出，无残留 |

pytest自身摘要为`1 failed, 301 passed in 0.65s`，与完整单元耗时分别保留。新结果目录`/private/tmp/p5-step3-resume-20261103-_y4u4z4d/results.json`明确保存previousRun、1129复用及新执行行，status=failed、failedUnit=3.4；原首轮失败结果原样保留。没有重跑前11完整文件，原失败文件的16项不重复计数。当前证据合计**1129复用+301本次=1430 passed、1 failed**；选定后端3322项尚有1891项未执行（含本文件7项），后续53个测试/编译单元未启动。零skip/xfail/xpass、零超时，已启动资源全部退出；仍不能登记第三步完成。

新首错节点为`test_rc70_turn_return_cannot_publish_a_locked_structure_record[1]`。它不是已修复的缺字段样本；原失败的字面恢复、真实step逐字段核对、clone和新增缺项拒绝已在本轮到达该节点前通过。当前故意错误测试替换`_finish_structure`：实际DIF回转本应生成DISAPPEARED，它却改成FOLLOWING并填firstOppositeAt，原originWave仍None。当前step会先把本根新FOLLOWING交给`_advance_followed_structure`检查当根价格，随后才调用`_finish_step→_validate_step→_publish`；因此在取`originWave['price']`时先抛`TypeError: 'NoneType' object is not subscriptable`，未到测试预期的最终`ValueError`校验，断言也未继续验证原对象/旧输出。

只读判断：本例的造错位置仍按旧推进顺序设置，和当前“首次反色立即检查价格”的顺序不匹配。不能把本次错误当作真实K线的结构标签算错，也不能据此直接修改正式推进/给原Wave补值。该状态来自替换内部函数，正常K线不会产生；管理员现已批准删除，当前按§22.13执行，不移动造错位置或增加产品防御。原失败仅作历史事实，删除不等于该例通过。

**本轮按再次首错停止：没有修改此新失败测试或正式代码、没有重跑3.4、没有执行3.5及以后单元。**此前§22.11保留原轮次1145/1记录，当前状态以本节1430/1为准。P5-04/14/19的完整恢复/拒错仍未完成，P5-15—18/20及前端/编译/架构未执行范围保持；P5-22仅证实本次授权续做的复用、局部收集、从失败整文件重跑及再次退出，不代表全部回归完成。原三文档同步此停点，P5第四步不进入。

本轮修复独立审计：§22.12.1四项均只落在指定恢复测试，原输入/业务断言保留；正常完整记录、真实step对应、跟踪样本及24缺项反例已在301项中通过。此次新失败仍原样保留，未为通过而改异常断言或正式实现。收尾静态检查：原三文档8步表、35/28/2文件范围及原3298准备记录一致，当前局部309与选定3322另按续做记录核对；根文档完整性3项、28文档971本地链接/163锚点、限定diff空白检查通过。没有继续业务测试/重试，不把这些静态检查或旧16项加入通过数。当前本任务仅修改一个测试文件及原三文档，其他工作区修改保留，暂存区为空；第三步仍未完成。

### 22.13 删除无现实依据用例并续做第三步（2026-11-03，已获授权）

管理员已明确批准删除上述case并续跑；本节先于删除/正式执行写入。当前dev-interface/HEAD509f796a9，较前次ea9fa3fd6仅新增Lake文档/历史产物清理提交，本需求src/主题/Wealth/tests/config无提交差异；原三份文档、恢复测试修复、日历start/end及共享Web/页面已有未提交修改仍保留。CodeGraph已sync并explore正式_start/_finish/step及跟踪调用；正式FOLLOWING总是同时携带原Wave，回转消失不进入FOLLOWING，外部恢复缺原Wave也被原检查拒绝。

1. **唯一代码修改：**删除`test_xxm_r4_restore.py::test_rc70_turn_return_cannot_publish_a_locked_structure_record`完整函数及其sign参数装饰器，恰2项；不加skip/xfail、不捕获或放宽异常、不换造错位置、不加替代测试或生产防御。原24缺字段反例、字面恢复/跟踪样本、其他函数和断言不变。
2. **真实覆盖保留：**`test_xxm_r4_rules.py::test_lld_rc_rule_sequence`的R/dif_return及镜像四周期、`test_xxm_r4_following.py::test_rc86_new_color_flip_id_is_the_only_future_target`等真实step序列仍验证回转退钝化、旧结构消失和后续新结构/引用；当前正式原Wave/恢复合同不变。删除依据为真实不可达的内部篡改组合缺少本需求价值，不是让现实失败变绿；不将其原失败改记成功。
3. **执行清单/数量：**唯一变化是3.4由309减2为307，后端选定3322减2为3320；§22.10的285/3298、§22.12的309/3322均各自当时事实。先用§22.12.2原局部收集命令核307，再整文件3.4→3.5—3.10→4→5→6→7→8，不按-k/节点绕开其他用例；35后端、28前端及两个编译单元保持。
4. **复用/退出：**未改的原11完整文件1129项和其他34文件收集记录复用，原失败文件301项不作完整通过、不重复加总。临时监督沿原脚本另建本次结果目录，从previous.reusedResults和本次已完整通过行中取可复用记录；保留旧失败，登记实际新HEAD及无执行代码提交变化，不因正常文档提交要求源码SHA保护。仅将局部收集预期改307，顺序调度、55秒工作+5秒退出/摘要、≤50ms后代识别及首次失败停止不变；再次失败只读定位，不自动修复或再执行。
5. **最终验收/边界：**所有明确单元及§22.10.9静态核对完成后，按3320后端唯一节点、前端逐文件/测试数、typecheck/build分别记结果与耗时，独立审计P5-01—22和材料/引用边界；旧失败/删除2项/复用1129单列。不把本轮隔离回归当新真实源/性能/视频验收；P4证据只原范围复用。仅测试与原三文档可改，正式代码/配置/数据及其他工作区差异不动；不读正式DB/Lake、不回测/执行Notebook/benchmark、不安装、不操作共享服务、不提交/推送/部署，不进入P5第四步。

开工前独立核对：用户授权、真实生产者/恢复及现业务序列与删除范围一致；该函数只有本地pytest发现，无其他代码消费者。删去的两个节点不是输入边界或真实业务序列，其他已有测试不变。当前执行范围、预算、失败/续做及已有差异已明确，按本节实施；执行结果随后据实登记。

#### 22.13.1 实际删除、续做及输入规则预期停点

已按本节删除指定函数及2个参数用例，未移动造错位置、增加其他测试、放宽断言或修改产品代码。局部收集307项，说明仅原309中减少批准的2项；此前样本修复及24缺字段反例保留。当前真实回转/镜像四周期及结构跟踪序列仍在原文件；CodeGraph与git当前差异核正式XXM/Spec相对f057cefaa未改。本次11完整文件1129项复用，实际代码状态为509f796a9加已登记工作区差异。

| 本轮单元 | 实际结果 | 完整耗时（秒） | 退出/自有资源 |
|---|---|---:|---|
| 局部收集恢复整文件 | 307 collected | 0.308704 | 0，PGID28222已退出 |
| 3.4 `test_xxm_r4_restore.py` | 307 passed，完整通过 | 0.840420 | 0，PGID28561已退出 |
| 3.5 `test_xxm_r4_internal_results.py` | 39 passed，完整通过；原start/end适配保留 | 0.767867 | 0，PGID28589已退出 |
| 3.6 `test_xxm_input_validation.py` | 95 passed、1 failed、余5项未执行，首错停止 | 0.250479 | 1，PGID28614已退出 |

本次新通过441项（307+39+95），复用1129，当前**1570 passed、1 failed**；13个文件完整通过，1个部分执行。两个删除项独立登记，不报它们通过；原失败文件旧301/16项不累加。选定后端3320项中1749项未执行，后续51个测试/编译单元未启动，无skip/xfail/xpass或超时，自有组全部clean=true/residualGroups=[]。实际临时结果为`/private/tmp/p5-step3-resume-20261103-yrnaxyux/results.json`，status=failed、failedUnit=3.6，原两轮失败证据不覆盖。

当前失败节点`test_formal_spec_contains_every_approved_rule_and_hashes_canonical_content`；pytest原摘要`1 failed, 95 passed in 0.06s`，与完整耗时分别记录。只读对照发现，该测试声称按LLD§2.2手写的expected仍为旧规则：

| 字段 | 测试旧预期 | 当前已批准LLD§2.2及正式Spec |
|---|---|---|
| algorithm_version | xxm-direction-v0.3-r4 | xxm-direction-v0.4-r4 |
| structure_follow_policy | next_same_color_close_break | price_until_first_valid_same_color_end |
| structure_follow_min_bars | 缺字段 | 严格整数2 |

其余17项相同。产品当前已验收身份及当前`spec.py`与LLD§2.2一致；本轮未修改该测试或Spec。因此此失败是先前测试的规则字典未同步正式v0.4，不是此次删除两个用例改变算法，也不是另一条应删除的不可达内部造错样本。规则身份/完整字段的独立检查应保留，后续只按已批准文档同步上述三处字面预期，不用asdict(MAIN_SPEC)生成expected、不把旧规则改回正式实现、不放宽完整相等/规则hash或拒旧检查。

本次限定搜索同类旧字符串，另一个`next_same_color_close_break`出现在`test_xxm_calculator`明确要求拒绝旧规则的反例，属于有用覆盖，必须保留；不能据字符串批删测试。未执行部分的其他正确性不由该搜索推断。

本轮首错后只读定位和补执行登记，**未修复3.6或重跑、未执行3.7—8、不进入P5第四步**。已有样本修复和本次批准删除均通过完整3.4验证；P5-04的37×4每截断测试及P5-15—20相关预测/图证/API/前端仍未完成。后续需先明确/同步这处旧测试预期的修复安排，再从受影响完整文件接续，按实际代码/输入决定复用13个完整通过文件1475项，不默认从头重跑，不把3.6部分通过95项再加一遍。

本轮独立审计及收尾静态检查：删除仅限管理员明确批准的2项，恢复/内部结果完整文件通过，原真实业务序列和正式实现未变；旧规则预期失败保留，不更改错误结论或继续后续组。实际3320选定节点、1570通过/1失败/1749未执行与临时原摘要独立核算一致。原三文档8步/35后端/28前端/两编译单元清单及原准备记录一致；根文档完整性3项、28文档971本地链接/163锚点和限定diff空白检查通过。静态检查不加入通过数、不代替第8步尚未执行的整批审计。当前本任务仍只改一个测试文件和原三文档，其他工作区差异保留，暂存为空，未提交/部署。


## 22.14 测试用例审计与暂停交接（2026-11-03，仅审计）

本轮按管理员要求，只读审计原35个Python单元和28个前端文件及直接相关生产者/消费者，形成[待清理记录](index-detail-top-bottom-recognition-p5-test-case-audit-v1.md)及其63项检查清单。登记F01—F14，其中F01是未同步v0.4的独立Spec预期，F02是旧多步表达式测试与本LLD保护旧合同的错误；其余涉及内部造错、极值、重复矩阵、实现细节约束、过期说明与覆盖不足，逐项列出依据及必须保留的边界。没有问题编号的文件不因此宣布正确。

本轮未修改业务/测试/配置代码，也未收集、运行或重试测试，未实施删除或合并，未访问正式数据源、回测、提交或部署。原执行成绩和三次停点保留为历史事实，不能把删除建议记为通过。原续做安排当前暂停；尤其不得按§22.10所保护的旧多步测试恢复旧产品能力。

后续先由管理员review待清理记录，再把确定的处理范围同步到原方案和LLD，明确每项保留、修改、删除或合并，以及受影响的证据/数量和恢复回归条件；本轮记录不自动授权实施或进入P5第四步。有效r4规则、真实输入/恢复/取消/缓存边界及架构隔离仍须保留。


## 22.15 按待清理记录修改测试（2026-11-03，已获授权）

### 22.15.1 目标、范围及硬约束

管理员已要求按F01—F14清理并独立复核。本轮只改下列测试及这组三份原文档、审计记录/CSV和两处索引；不改src生产代码、Wealth运行代码、schema/Spec、配置、数据或正式工具。P5整批回归继续暂停，本轮只跑受影响的完整测试文件和必要关联验证，不能顺势续做剩余单元或宣布P5第三步完成。已批准删除的两个不可达用例不恢复；既有工作区修改按原样保留。

已用CodeGraph query核ForecastExpression、validateExpression和useXxmForecast的位置/消费者，结合当前生产者、schema、原literal fixture及Hook正文核对；更早explore提供的恢复/查询上下游仍沿当前源码复核。未改变架构、依赖方向或产品合同。测试新增TypeScript AST读取只用现有typescript依赖，查其5.9声明；不安装包，不在运行模块增加解析器。

所有预期保持独立字面依据；合法样本先符合当前合同，再分别构造反例。不得用待测Spec/算法生成expected，不skip/xfail/吞错误；不能把删掉的用例记为通过。字段缺失、类型/NaN/inf、真实日期/周期、真实1%边界、近远切换、逐根比价、单根段、有效段结束、历史关联和37×4截断恢复均保留。没有更改来源/预算/读写边界，400ms正式预测预算不变。

### 22.15.2 逐项编码和保留覆盖

| 项 | 实现文件/动作 | 明确保留/验收 |
|---|---|---|
| F01 | input_validation的独立字典仅改v0.4、跟踪policy和min_bars=2三处 | 全字段相等、独立hash、类型及拒旧；不动MAIN_SPEC |
| F02 | forecast_expression_contract以六种节点和MACD五字段重写；删除旧多步接受、add/div能力/20步体积和prefix数值矩阵 | 六类正例/合法嵌套JSON往返；sub两个参数；每个MACD数值/field/必需键、affine变量限制、round3正guard、额外字段拒绝；旧op/旧prefix只作少量拒绝 |
| F03 | r4_restore删除审计列出的五个强改_finish_step输出函数，共15个原变体 | 不删真实K线/事件/结构/历史及对外坏副本恢复；正式内部检查不改 |
| F04 | r4_restore的构造后失败8项收为day/TOP代表1项，空对象零柱失败独立保留；r4_following保留跟踪前/已开始两种prefix，去无关sign交叉；observation删重复_finish_step抛错段，保留副本/restore模式/默认关闭 | internal_results的聚合与模型失败、snapshot_consumers的推进后缓存失败属不同发布位置，原样保留；取消/时间和旧输出不变仍验 |
| F05 | key_point_forecast删除8个极小DIF和4个极大DIF变体、10**400状态；p3_forecast_math删除下溢/大数选项/溢出测试，Fraction源包络只留正常正负/零状态 | 正常量级1%原运算、真实三位精度、开闭/相邻可表示数、非有限/布尔拒绝仍保留；不改数学函数或输入合同 |
| F06 | 后端旧循环函数随F02退出；前端expressionContract删除自引用/共享对象身份用例 | 新六类JSON正例和真正可传入的坏嵌套、缺键及错类型仍验；不删正式循环保护 |
| F07 | r4_restore三缺字段24项收为day/TOP三项；BAD_PATHS的公共字段只在day逐项，两个日期字段另保留三个分钟周期，24+6=30 | 每种坏字段不丢；四周期/镜像合法恢复与时间测试、37×4截断不缩减。snapshot_validation直接parser检查和restore对象不变分别留在各自边界，不重复机械扩展 |
| F08 | forecastDebugContract的18类范围在day的两种入口全部保留；每个分钟周期/两入口只留一个合法无上界及一个非法范围，144收为48 | 真实2026-10-27 upper=null及HTTP客户端回归不动；不减少两种入口或周期接入验证 |
| F09 | product_v1_cases静态校验改为禁止产品/研究等非标准库导入，允许typing等标准库，不限数量；保留open/exec/eval/__import__禁用。前端dependencyBoundary用TS AST读取静态/动态及type-only导入，按路径判断辅助依赖；只允许页面静态引入debug loader，loader须动态引入IndexRecognitionDebug，不能静态引入辅助实现 | 加正常typing/多行/单引号/纯helper正例和真实违规依赖反例，证明不误拦。无源码SHA/固定完整import语句/固定react导入个数 |
| F10 | local_extrema_study去vars类型禁令及无用time导入，改准测试名 | 10,000输入、3999极值及processed计数保留；不声称已测内存有界，不运行benchmark |
| F11 | 两个Web source_db仅生成固定需求日历：识别2020-01-01至01-10；预测2023-01-03至01-31。共享测试helper包装原load_entry，仅在调用没有now时分别传场景2020-01-10 20:00和原NOW=2023-01-10 20:00；显式now原样传递，仍返回原load_entry的context manager | 读取模块要求日历覆盖now.date，固定场景时间与临时数据一致；不替换读取/校验/预算。既有latest、下一交易日、休市/缺日及SQL/Gold链路保持；不改生产时钟/正式读取 |
| F12 | key_point_forecast的PF19保留计时记录、重复结果/副本独立性，去elapsed<.4 | 正式P4性能证据及可控预算/取消不变；不以本轮测试宣称性能达标，不提高阈值 |
| F13 | key_point_forecast的首次反色/后续新轮、snapshot_validation的进度副本、internal_results跟踪变量、restore非法首次反色参数改准名称/说明 | 只把结构语境的lock改following/first_opposite，线程锁不改；PF14补原TOP已因104突破103消失及原因/关联字面断言；副本测试覆盖followed_structures独立性 |
| F14 | forecast Hook测试将生产/禁用拆为两个独立前提；改准停用/最新轮询标题，历史场景推进60秒且保留手动重试；补实际换指数和debug模式的旧请求取消/迟到不写入 | 同一Hook/真实effects，替身只替HTTP客户端；新debug请求完成前保持空，旧返回不污染；不修改Hook/页面，不开浏览器复验 |

当前预计只改13个Python文件和4个前端测试文件。最终文件/删除/参数数以相对本轮开始的实际差异和限定收集为准，不凑旧3320节点。原历史成绩不重算；既有helper调用方的传参及fixture对外名称保持；forecast source_db仅增加monkeypatch这个测试依赖参数，r4_restore的literal_snapshot不改，前轮样本修复保留。

### 22.15.3 验证顺序、失败及退出

1. 文档和当前生产者核对完成后，再改测试。逐项记录F01—F14的旧用例/新用例或保留理由，确认删除函数无外部import消费者。
2. 修改后仅收集13个改变的Python完整文件，记录实际数量、不含全研究目录；不以旧数量作强制expected。先跑这13个文件，再跑必要关联：calculator、r4_rules、snapshot_consumers、r4_following_forecast。前端跑4个改变文件，另跑真实apiClient和r1拒旧文件；这不是原P5步骤3—8的续跑。
3. 前端typecheck和build按现有工程执行；依赖检查跑原8.4指定节点及根三份架构检查。测试本地人工/已有冻结材料/临时SQLite和Gold，禁止正式数据库/Lake/网络/全历史重放、Notebook或benchmark，不启停共享服务或安装依赖。只有构建写原ignored产物。
4. 复用已验临时监督的execute/进程组回收，不使用其旧3298/307收集断言、续做分组或总数。新调用清单明确路径；每文件仍55秒工作+5秒回收/记录，含准备/取消/最后验收，整单元上限60秒，首次失败停止后续。取消后不领新单元，结束只清本次自有进程/临时输出，不操作他人进程。临时记录只存摘要/数量/错误，不存行情响应。
5. 发现测试错误先对照本节/真实合同，不能临时改产品/放宽断言。若需超出本节处理，保留首错并报告；不同执行阶段不得将部分通过与旧成绩混加。已完成单元仅在代码/输入未再变且明确无依赖影响时复用，补改后只重验受影响单元。
6. 最后独立逐项复核：删除/参数调整均可映射F项，未批准节点/原字面输入/真实预期未动，六种表达式可接受及旧字段拒绝都确有相应断言；坏样本从合法基础只改目标字段。当前125业务变体/37×4及关键关联测试仍在；63清单仅登记本轮实际处置，不把未重跑者登记通过。核CodeGraph sync/status、文档链接及差异，报告通过/失败/未执行和遗留风险后停止，不提交/部署或恢复整批回归。


#### 22.15.3.1 定向验证的F11夹具纠正

首次13文件限定收集2083项；前11文件1779项完整通过。第12文件识别API首例失败（HTTP500），按首错停下，第13及其他验证未执行，自有资源退出。只读代码定位：query_service.load_entry默认取真实今天，日线_load_series调用calendar_dates(end=now.date)，该函数要求末行正好覆盖end。仅截短日历使固定2020样本缺真实今天，不是识别规则故障。

先同步F11设计，再在识别测试文件加共享_source_clock：保留原load_entry，在now为空时补传场景时间，显式now不改；预测source_db复用此helper并用原NOW。生产方法/SQL/期望/覆盖均不改，不靠增加远处假日历行过关。原失败结果保留于本轮verification/results.json；只有这两份Web测试再变动，前11文件及其依赖未变，1779项可复用，不再次累加。另建verification-2目录，收集并完整重验两Web文件，再接本节其余必要验证；任何新失败仍按原首错边界处理。本次不恢复整批P5。


#### 22.15.3.2 长校准样本与后续日历变更的明确范围

F11补充直接消费者核对：识别API187完整通过；预测文件28通过后，带250根预热的完整校准例在日历覆盖处首错，原verification-2证据保留，不算整文件通过。这一例自己构造290根跨年行情并显式传末日now，故只在该例临时SQLite中补2023-02-01至末根之后首个周一至周五日期的日历行；普通source_db仍截止01-31，不把跨年数据生成扩散到其他116个用例。原校准/价格/DIF/解/预算预期都不改，next target仍通过真实future_calendar查询。

同文件test_single_calendar_endpoint_and_used_prefix_identity原UPDATE的是2023-04-01（周六，原来已经is_open=0），即使有该行也没有实际改变值。改为本fixture中确定存在、尚未被各参数的target使用的2023-01-31：只UPDATE is_open=1的行到0，断言rowcount=1，再验证原endpoint/identity不变。这是修正F11范围关联及原无效变化，不新增产品规则或放宽断言。已查本fixture其他日期调用，未再发现跨01-31需求；其他独立batch3 fixture不改。

本次只再改变预测API一个文件；识别API与前11文件的代码/输入/依赖未变，1966项完整通过可复用。另建verification-3记录，只完整收集/执行预测API117项后接必要关联及前端；原部分28项不重复计数。其余退出/首错/60秒要求不变。


#### 22.15.3.3 F09测试辅助函数的包名处理

前端首个文件在loader正例处停止：新AST辅助函数把react当相对路径，解析成debug/react，发生误拦。仅修本测试target函数：以点开头的模块才相对当前文件解析；bare包名保持包名，绝对路径保持绝对路径，再判断是否位于本地debug/daily-wave目录。原正常React/helper/type-only/引号格式正例及违规本地依赖反例全部保留，loader仍要求动态引入IndexRecognitionDebug，不放宽真正的静态辅助依赖限制。

原verification-3保存该首错（1通过、1失败，另2未执行），不计作完整文件通过。Python21文件/节点共2740项代码/依赖未变，可复用；另建verification-4只从受影响前端完整文件开始，沿既定6文件→类型/构建验证。没有新产品改动或预算变化。


### 22.15.4 清理完成、独立复核及后续交接

本轮已按F01—F14完成13个Python/4个前端测试文件的修改，未改r4/预测/读取/schema/配置或其他运行代码。独立复核确认仅5个指定内部造错函数被删除，原业务字面值、37×4截断恢复、顶底/周期及不同发布/恢复边界保留；过时表达式接受口径及PF08/16/17/19测试设计已同步纠正。详细逐项处置、63清单及证据见[测试用例清理记录](index-detail-top-bottom-recognition-p5-test-case-audit-v1.md)§7—8。

有效定向验证去重：13改变文件2083 Python项、8关联文件/节点657项，共2740；前端4改变文件64项加2合同/客户端10项，共74；Wealth类型检查/构建通过。根架构16和研究节点1已在上述657内，不重复计数。单元最长20.357719秒，所有自有进程清理完成，无skip/xfail或超时。F11两次夹具首错及F09测试辅助函数首错保留，均先核依据/补LLD再仅修测试，完整受影响文件已通过，旧部分成绩不相加。

本轮清理交付完成，P5整批回归仍暂停，未自动进入第四步、提交或部署。当前保留35个Python选择单元及28前端文件边界，但旧3298/3320只作当时收集事实，不可再作当前硬断言。下次获准恢复时先根据当前文件收集/登记实际数量，按实际依赖复用有效完整通过行，补其余未覆盖单元；本轮限定结果不能替代整批、真实源或浏览器验收。

103份代码/测试审计CSV的原symbols/post_move_symbols及execution_result记录的是P5第二步迁移/清退时的事实，不覆盖本轮测试函数清理；这些历史列不作为当前节点执行命令。当前处理和验证以本轮63项测试清单及本节结果为准，其他资料清退历史不重写。

本轮最终静态检查：文档完整性3项、6份Markdown的446本地链接/22锚点、63清单路径/状态、限定差异/新文件空白均通过；CodeGraph sync/status为最新。末尾空行整理的AST完全不变，已有运行证据仍适用；没有新增测试数或产品结论。

### 22.16 清理后继续第三步整批回归（2026-11-04，已获授权）

#### 22.16.1 本次范围、准备事实与证据复用

管理员已明确继续P5第三步整体回归；§22.14—15的暂停限制属于之前两轮，只约束当时执行，当前按本节及§22.10八步续做。35个Python单元、28个前端完整文件、两个编译单元与§22.10逐行相同，不新增测试、修改预期或回退F01—F14。本次只可修改原三文档、审计记录/CSV的结果登记和/private/tmp临时监督，不改业务、测试、配置、源材料、其他任务内容或共享服务。

初始工作区为dev-interface，HEAD `2a81ce1a4b61a3b79230042137d92ff02e0e5385`。清理代码提交`5129f1452`之后的相关变化是指数成分缺行情处理：page/weights query、exception builder、indexDetailState及整页测试，另有既存IndexInfoRail/CSS/页面测试修改；这些是当前页面/编译基线，本轮保留。Web共享fixture仍为临时SQLite，替换交易助手/股票指标lifespan并覆盖DB依赖；XXM正式核心、查询、表达式schema、预测Hook/客户端、研究工具和本轮15个纯Python测试无相关差异。CodeGraph explore及实际diff核入口和消费者，图谱中TS测试缺边用现测试正文补核，不把缺边当未覆盖或通过证据。

准备只读核对：103代码清单中61待退文件及对应明确pyc均不存在；3503旧报告路径不存在；221唯一指定目标全部存在。仅核目标路径和现消费者，复用第二步迁前207逐字节/7逐字段事实，不再次读取155MiB全部原件，不清理新出现的其他资料。旧清单定义列是历史，不作为当前执行节点。

复用证据为`/private/tmp/p5-case-cleanup-_hbyfk0q/verification-4/results.json`中已有完整有效行，包括其reusedResults。按实际路径映射原顺序号：

| 类型 | 仅可复用的原顺序号 | 已通过数量与条件 |
|---|---|---|
| Python | 2.5、2.7、3.1—3.9、4.1—4.4 | 15个完整文件，共2419项；与当前相关代码/输入/依赖和本次收集数一致才采用 |
| 前端 | 7.6、7.7、7.9、7.10、7.11、7.14 | 6个完整文件，共74项；测试/生产者/依赖/当前选取边界未变，原进程退出干净 |

两份Web API即使上轮通过，因共享App导入的指数模块已有变化，本次仍重跑；三架构、组织节点读取当前树，也重跑。类型/构建覆盖当前整个Wealth，同样重跑。旧1570/1及部分文件通过数不采用；旧总3298/3320不作新断言。任何未能确认仍适用的复用行先明确受影响集合，不默默算通过。

#### 22.16.2 临时调用、实际收集和续做顺序

1. 使用现有环境，Python关闭自动plugin加载/写pyc/cacheprovider；前端沿原vitest run/bail命令；不安装或下载。先按§22.10.3显式收集主题整目录及5Web/3架构，主题其他研究只收集、不执行。用当前35个单元映射实际唯一节点，不能采用旧runner的3298、307、固定HEAD或固定首错停点检查；数量变化按F01—F14及当前文件逐项解释、登记后再执行。
2. 临时目录`/private/tmp/p5-step3-complete-20261104-k1fr1ts6`，只记选择/数量/耗时/退出及必要错误，不存行情、源码副本或业务恢复数据。复用原临时`p5_step3_run.py`中execute的Popen/monotonic/进程所有权/55秒停止工作和60秒完整回收函数；临时适配只替换当前清单、收集数和摘要状态，不执行旧specs/init/resume分支，不继承旧307检查。不新增工程文件、长期测试框架或配置。进程关系只跟踪本次PID/PPID/PGID，不能按名称终止共享服务。
3. 收集成功后，按§22.10原步骤2→3→4→5→6→7→8继续；遇复用行登记原完整证据，不再运行或加第二次。其余20个Python单元、22个前端完整文件及两个编译单元每行新进程，单元55秒工作加最多5秒清理/摘要。只执行表内路径/唯一明确组织节点；前端包含过滤必须恰好选中对应一文件，不能全Wealth默认运行。
4. 三例原图仍执行原13项，离线CSV/日历/原MACD/有限前缀及8MiB边界保持，不扩大日期或比较组。API/工具仅用原临时SQLite/Gold/loopback/子进程；原临时鉴权和读取合同不替换成正式源，不操作管理员8000/前端/DG。
5. 每行通过数须与本轮实际收集/完整文件匹配，禁止skip/xfail/only、重试或更新快照；首次失败/超时/退出不净立即停止全部后续单元，保留首错，先只读定位并汇报，不自动修代码或调阈值。中断按已完成行及实际工作区续做，禁止默认从头重跑。
6. 测试完成后执行§22.10.9四项静态审计，各自≤60秒：当前活动引用/11保留模块及3工具导入、221材料及两个抽取摘要边界、根文档/修改文档链接锚点/diff、结果唯一性/进程退出/已有改动不受影响。正式环境/测试数据/配置和材料不得被本轮改变；仅既有ignored构建产物允许写入。
7. 最终逐行登记35后端/28前端/类型构建的执行或复用、实际数量/耗时/退出，给出P5-01—22覆盖与证据类型，和旧失败分开。全部明确单元及静态检查通过才记第三步完成；不据此新增真实源/性能/视频验收结论，不自动进入P5第四步、提交、推送或部署。

本节执行准备和既有证据核对不等于测试通过；本次实际结果另记下节。

#### 22.16.3 当前实际收集及执行登记

本次收集3862个节点，归入原35个Python单元的唯一节点3193个；其他669个只收集、不运行。收集耗时2.567168秒，退出0、自有进程已退出。相对最初3298，变化只在已批准清理的6行：2.5为16（原11），3.3为435（原437），3.4为198（原285），4.1为82（原95），4.2为57（原60），4.4为81（原86）；合计减少105。恢复文件的307是中途历史数，不与最初285或当前198混用。其余29行数量未变，35个目标无缺失/重复。

15个纯Python完整证据的2419项与当前收集逐行相符，6个前端完整文件的74项仍在原独立范围。本次待执行20个Python单元774项、22个前端完整文件及两个编译单元；完成结果在下文据实登记，不能提前记通过。

#### 22.16.4 测试结果及首次静态审计停点（历史，最终完成见§22.16.6）


本次测试部分已完成：35个Python单元3193项（本次20单元774项，复用15单元2419项），28个前端完整文件332项（本次22文件258项，复用6文件74项），类型检查及构建均通过。测试无失败、skip/xfail或超时，自有进程均干净退出；本次最长测试19.820993秒，类型4.903735秒、构建5.940516秒。复用次数不另加，旧1570/1不并入。

最后静态审计的首个引用检查未完成：临时`references.py`仅import importlib，却访问importlib.util.resolve_name，标准库子模块未显式导入，0.255767秒以AttributeError退出。错误在临时检查脚本中，不是产品代码/测试失败；本轮未修该脚本或重试，未继续其余最终静态检查。按LLD首错停止，P5第三步仍未完成，不能交第四步。后续只需先明确临时脚本修正，再补最终引用、资料、文档及结果审计；已经有效通过的测试不默认重跑。本轮未改业务/测试/配置/数据，未提交、推送或部署。


下表为本次实际完整选择范围；“复用”耗时为原有效执行耗时，不计为本轮新执行时间。每行均通过、无意外跳过且退出干净；表外最终引用检查失败另列，不能用这65行通过代替整批完成。

| 顺序 | 文件/单元 | 结果 | 证据来源 | 秒数（含退出） |
|---|---|---:|---|---:|
| 2.1 | `scripts/research/index_market/tests/test_xxm_acceptance_scope.py` | 16 passed | 本次执行 | 1.160946 |
| 2.2 | `scripts/research/index_market/tests/test_xxm_near_first_review.py` | 24 passed | 本次执行 | 0.205351 |
| 2.3 | `scripts/research/index_market/tests/test_xxm_top_activation_real_math.py` | 12 passed | 本次执行 | 0.204624 |
| 2.4 | `scripts/research/index_market/tests/test_xxm_reference_window_review.py` | 9 passed | 本次执行 | 0.204649 |
| 2.5 | `scripts/research/index_market/tests/test_xxm_product_v1_cases.py` | 16 passed | 复用清理阶段完整证据 | 0.191748 |
| 2.6 | `scripts/research/index_market/tests/test_xxm_local_extrema.py` | 47 passed | 本次执行 | 0.278767 |
| 2.7 | `scripts/research/index_market/tests/test_xxm_local_extrema_study.py` | 6 passed | 复用清理阶段完整证据 | 0.232730 |
| 2.8 | `scripts/research/index_market/tests/test_xxm_saved_minute_window.py` | 41 passed | 本次执行 | 0.316416 |
| 3.1 | `scripts/research/index_market/tests/test_xxm_calculator.py` | 22 passed | 复用清理阶段完整证据 | 0.331353 |
| 3.2 | `scripts/research/index_market/tests/test_xxm_r4_rules.py` | 504 passed | 复用清理阶段完整证据 | 0.850240 |
| 3.3 | `scripts/research/index_market/tests/test_xxm_r4_following.py` | 435 passed | 复用清理阶段完整证据 | 6.260020 |
| 3.4 | `scripts/research/index_market/tests/test_xxm_r4_restore.py` | 198 passed | 复用清理阶段完整证据 | 0.778312 |
| 3.5 | `scripts/research/index_market/tests/test_xxm_r4_internal_results.py` | 39 passed | 复用清理阶段完整证据 | 0.634157 |
| 3.6 | `scripts/research/index_market/tests/test_xxm_input_validation.py` | 101 passed | 复用清理阶段完整证据 | 0.226145 |
| 3.7 | `scripts/research/index_market/tests/test_xxm_snapshot_validation.py` | 249 passed | 复用清理阶段完整证据 | 1.351846 |
| 3.8 | `scripts/research/index_market/tests/test_xxm_snapshot_consumers.py` | 21 passed | 复用清理阶段完整证据 | 0.978347 |
| 3.9 | `scripts/research/index_market/tests/test_xxm_r4_observation.py` | 515 passed | 复用清理阶段完整证据 | 1.863209 |
| 3.10 | `scripts/research/index_market/tests/test_xxm_r4_following_query.py` | 27 passed | 本次执行 | 0.891364 |
| 4.1 | `scripts/research/index_market/tests/test_xxm_key_point_forecast.py` | 82 passed | 复用清理阶段完整证据 | 1.505505 |
| 4.2 | `scripts/research/index_market/tests/test_xxm_p3_forecast_math.py` | 57 passed | 复用清理阶段完整证据 | 0.260541 |
| 4.3 | `scripts/research/index_market/tests/test_xxm_r4_following_forecast.py` | 93 passed | 复用清理阶段完整证据 | 1.462520 |
| 4.4 | `scripts/research/index_market/tests/test_xxm_forecast_expression_contract.py` | 81 passed | 复用清理阶段完整证据 | 0.305306 |
| 4.5 | `scripts/research/index_market/tests/test_xxm_forecast_display.py` | 15 passed | 本次执行 | 0.250229 |
| 5.1 | `scripts/research/index_market/tests/test_xxm_confirmed_cases.py` | 13 passed | 本次执行 | 4.654878 |
| 6.1 | `scripts/research/index_market/tests/test_xxm_daily_window_precheck.py` | 11 passed | 本次执行 | 3.926701 |
| 6.2 | `scripts/research/index_market/tests/test_xxm_p4_audit_tools.py` | 174 passed | 本次执行 | 9.163218 |
| 6.3 | `tests/web/test_wealth_index_detail_xxm_api.py` | 187 passed | 本次执行 | 19.820993 |
| 6.4 | `tests/web/test_wealth_index_detail_xxm_forecast_api.py` | 117 passed | 本次执行 | 5.773790 |
| 6.5 | `tests/web/test_wealth_index_detail_xxm_forecast_validation.py` | 47 passed | 本次执行 | 3.415553 |
| 6.6 | `tests/web/test_wealth_index_detail_xxm_local_routes.py` | 14 passed | 本次执行 | 6.612380 |
| 6.7 | `tests/web/test_xxm_shared_loads.py` | 3 passed | 本次执行 | 0.924564 |
| 7.1 | `wealth/src/features/index-detail/xxm/apiClient.test.ts` | 6 passed | 本次执行 | 1.214391 |
| 7.2 | `wealth/src/features/index-detail/xxm/adapter.test.tsx` | 5 passed | 本次执行 | 0.959294 |
| 7.3 | `wealth/src/features/index-detail/xxm/rearmContract.test.tsx` | 1 passed | 本次执行 | 0.923950 |
| 7.4 | `wealth/src/features/index-detail/xxm/markerGeometry.test.ts` | 10 passed | 本次执行 | 1.020140 |
| 7.5 | `wealth/src/features/index-detail/xxm/useIndexXxmLayer.test.tsx` | 6 passed | 本次执行 | 1.151791 |
| 7.6 | `wealth/src/features/index-detail/xxm-forecast/apiClient.test.ts` | 7 passed | 复用清理阶段完整证据 | 0.904294 |
| 7.7 | `wealth/src/features/index-detail/xxm-forecast/expressionContract.test.ts` | 2 passed | 复用清理阶段完整证据 | 0.885000 |
| 7.8 | `wealth/src/features/index-detail/xxm-forecast/identity.test.tsx` | 2 passed | 本次执行 | 0.885199 |
| 7.9 | `wealth/src/features/index-detail/xxm-forecast/r1Contract.test.tsx` | 3 passed | 复用清理阶段完整证据 | 0.894967 |
| 7.10 | `wealth/src/features/index-detail/xxm-forecast/forecast.test.tsx` | 10 passed | 复用清理阶段完整证据 | 1.196883 |
| 7.11 | `wealth/src/features/index-detail/debug/dependencyBoundary.test.ts` | 4 passed | 复用清理阶段完整证据 | 1.381212 |
| 7.12 | `wealth/src/features/index-detail/debug/useIndexDebugModule.test.tsx` | 5 passed | 本次执行 | 1.738358 |
| 7.13 | `wealth/src/features/index-detail/debug/xxmDebugContract.test.ts` | 4 passed | 本次执行 | 0.982207 |
| 7.14 | `wealth/src/features/index-detail/debug/forecastDebugContract.test.ts` | 48 passed | 复用清理阶段完整证据 | 0.891560 |
| 7.15 | `wealth/src/features/index-detail/debug/IndexRecognitionDebug.test.tsx` | 6 passed | 本次执行 | 1.494416 |
| 7.16 | `wealth/src/features/index-detail/daily-wave/apiClient.test.ts` | 9 passed | 本次执行 | 0.935734 |
| 7.17 | `wealth/src/features/index-detail/daily-wave/adapter.test.ts` | 78 passed | 本次执行 | 0.952240 |
| 7.18 | `wealth/src/features/index-detail/daily-wave/markerGeometry.test.ts` | 9 passed | 本次执行 | 0.861030 |
| 7.19 | `wealth/src/features/index-detail/daily-wave/presentation.test.ts` | 21 passed | 本次执行 | 0.995026 |
| 7.20 | `wealth/src/features/index-detail/daily-wave/DailyWavePrimitive.test.ts` | 15 passed | 本次执行 | 0.990571 |
| 7.21 | `wealth/src/features/index-detail/daily-wave/DailyWaveLayerUi.test.tsx` | 13 passed | 本次执行 | 1.093739 |
| 7.22 | `wealth/src/features/index-detail/daily-wave/useDailyWaveReview.test.tsx` | 21 passed | 本次执行 | 1.088163 |
| 7.23 | `wealth/src/features/index-detail/model/indexRecognitionAvailability.test.ts` | 1 passed | 本次执行 | 0.912269 |
| 7.24 | `wealth/src/features/index-detail/api/indexDetailRequestScheduler.test.ts` | 4 passed | 本次执行 | 0.935723 |
| 7.25 | `wealth/src/features/index-detail/chart/IndexChartWorkspace.test.tsx` | 3 passed | 本次执行 | 0.984266 |
| 7.26 | `wealth/src/features/index-detail/chart/IndexMinuteChartWorkspace.test.tsx` | 2 passed | 本次执行 | 0.976891 |
| 7.27 | `wealth/src/pages/index-detail/IndexDetailDailyWave.test.tsx` | 1 passed | 本次执行 | 1.240174 |
| 7.28 | `wealth/src/pages/index-detail/IndexDetailPage.test.tsx` | 36 passed | 本次执行 | 2.106812 |
| 7.29 | `wealth` | 通过 | 本次执行 | 4.903735 |
| 7.30 | `wealth` | 通过 | 本次执行 | 5.940516 |
| 8.1 | `tests/architecture/test_subsystem_dependency_matrix.py` | 4 passed | 本次执行 | 1.539103 |
| 8.2 | `tests/architecture/test_platform_legacy_guardrails.py` | 3 passed | 本次执行 | 2.623019 |
| 8.3 | `tests/architecture/test_operations_legacy_guardrails.py` | 9 passed | 本次执行 | 9.289665 |
| 8.4 | `scripts/research/index_market/tests/test_research_layout.py::test_single_location_roots_and_pytest_discovery` | 1 passed | 本次执行 | 0.591151 |

执行摘要在`/private/tmp/p5-step3-complete-20261104-k1fr1ts6/results.json`。独立只读复核：65个测试/编译单元与原清单一一对应；其中21个明确复用、44个本次执行，测试计数与当前收集一致，无部分成绩或已删除用例累加。新测试/编译累计107.133996秒；含本次收集、14导入及失败静态检查累计110.545412秒，均为各单元之和，不是接口性能成绩。全部已启动单元都记录clean=true、residualGroups为空；临时引用检查也已退出。P4真实源/页面、资料迁前交接和11原图缺失限制未升级。

| P5要求 | 本次覆盖/证据边界 |
|---|---|
| P5-01 | 步骤1确认61旧代码及对应pyc缺席、14保留入口导入成功，CodeGraph/当前依赖差异已核；最终全量活动引用检查因临时脚本缺导入未完成，不能报本项整体通过 |
| P5-02、03、05、06、09、10、11、12、13 | 步骤2八完整文件171项采用当前独立字面输入、资料与纯工具合同，未执行Notebook或benchmark |
| P5-04、14、15、19 | 核心/规则/跟踪/记录/恢复/观察完整文件含37×4每截断，结合本次历史查询和API/debug合同；F01—F14清理后的覆盖未回退 |
| P5-07、08、21 | 221目标及3503旧路径准备核对完成；迁前原字节/叶值交接只复用原范围；两个摘要的长期16项acceptance通过，最终七件抽取/资料审计未执行，不登记整项完成 |
| P5-16、17、18 | 单根预测/整数文本与原图三例13项均通过，3例沿原离线源及端点单组执行，不代表新图核验或双组全历史对比 |
| P5-20 | P4工具、5Web、28前端、类型和构建完成；临时SQLite/Gold/loopback及真实客户端/ASGI边界，不新增正式源/性能验收 |
| P5-22 | 复用明确未变完整单元、只补其余；临时静态检查首错停止，不修产品/改预期/自动重试或继续后续检查；保留停点，未进入第四步 |

剩余仅最终静态审计：修正并重验临时引用检查、资料和抽取边界、文档链接/锚点/diff及本轮结果/工作区/退出对账。正式测试已有效通过的行在相关代码/输入未变时复用，不因临时脚本错误自动整轮重跑。未取得后续续做确认前不执行或将P5第三步标成完成。

#### 22.16.5 临时引用检查修复与最终审计续做（2026-11-04，已获授权）

管理员已明确要求立即修正并完成第三步。本次只在原临时`references.py`第一行增加显式`importlib.util`导入，原引用判断、范围、断言和14个导入检查保持；不改业务/测试/配置或材料。不增加长期检查框架，不安装依赖。当前HEAD仍为`2a81ce1a4b61a3b79230042137d92ff02e0e5385`；先核相关代码/输入相对上一轮无新增变化，再复用§22.16.4的65个完整测试/编译单元及原收集，不重复执行、收集或加通过数。

续做顺序：

1. 修正前先核临时引用检查其余逻辑与§22.10.9一致；仅补标准库导入。原失败摘要保留，修复后用独立结果ID `8.static.references_after_import_fix`执行原`references.py`，避免覆盖首次失败。原临时监督只增加该结果ID到同名原脚本的对应关系，execute和55秒工作/60秒完整退出预算不改。
2. 引用检查通过后才运行已准备且未执行的`materials.py`：核3503原路径/221目标、7抽取根键/两个嵌套白名单及8单元Notebook未执行；复用迁前原字节和叶值交接，不重读全部155MiB、不运行Notebook。
3. 再运行原文档完整性和本组三文档/审计记录/CSV的本地链接、锚点、空白和状态检查；复用已核过的链接检查方式，只把结果写入本任务临时目录。文档先登记事实，最后以真实检查结果更新完成状态，再针对最终文本复核一次，不增加测试执行。
4. 最后逐行对账65个测试/编译单元与原清单、数量/完整通过/复用、当前相关代码及已有修改、所有本次自有进程/临时服务退出。只查询已记录的自有PID/PGID，不按名称操作其他进程。旧引用检查失败只有在本次同范围修正后通过才转为历史已解决；不能删掉失败或用旧通过代替本次检查。此阶段各单元仍≤60秒，含取消/回收及最后验收；如出现新失败，继续按原首错规则停止并报告。
5. 全部通过后，将原三文档、审计记录及CSV同步为“P5第三步回归完成”，明确3193/332中原复用与本次测试数量、修正后的静态结果及证据边界；P5-01—22逐项对齐。旧首错和当时停点保留历史身份，当前执行口径不再指向已解决问题。仅完成第三步并汇报，不进入第四步、不提交/推送/部署、不重做P4真实源/页面验收。

临时摘要仍在`/private/tmp/p5-step3-complete-20261104-k1fr1ts6`；原65行结果逐字保留，新增独立静态结果。结果状态可以恢复为running并记录本次授权/修正，旧失败行不得删除或改成通过。

#### 22.16.6 第三步最终完成与交接（2026-11-04）

本次已完成P5第三步整体回归及最终独立审计：35个Python单元3193项、28个前端完整文件332项、类型检查和构建通过。3193=本次执行774+明确复用2419；332=本次执行258+明确复用74，65个测试/编译单元无缺失、重复、测试失败、意外跳过或超时。复用仅来自代码/输入/依赖未变的完整有效证据，不把早期部分通过或删除项算入成绩。

临时引用脚本仅补显式importlib.util导入，原首次失败保留；同范围修正后检查2.187603秒通过。随后资料0.166654秒、文档0.283145秒、结果/工作区/退出0.459565秒分别通过。61旧代码/对应pyc缺席，221目标及7抽取合同、两个嵌套白名单和未执行Notebook有效；全部65行与63项测试清单相符、记录的54个自有进程组均已退出，其他工作区状态和资料未受影响。根文档完整性3项、本次4份Markdown的47个本地链接/4锚点及CSV63行通过，差异空白通过。同步完成状态后还按同一方法复核最终文本和结果。

本轮续做只修临时检查并同步原三文档、审计记录/CSV，没有修改产品/测试/配置/数据，没有重跑已通过测试，也未新增正式源、性能、浏览器或视频验收结论。P4真实来源/页面及迁前原字节/叶值交接继续只复用原范围；11条缺原图限制、暂缓优化及范围外日期TODO保持。P5第四步最终交付尚未开始，未提交、推送、部署或开放生产r4。

| P5要求 | 当前完成依据及限制 |
|---|---|
| P5-01 | 103代码清单、61旧路径/pyc缺席、14保留模块/工具导入及活动import/动态字面引用/旧执行入口核对；临时漏导入已修正，最终引用检查通过 |
| P5-02、03、05、06、09、10、11、12、13 | 步骤2八文件171项覆盖纯取数/区间、37组222根原字面输入、真实DEA/27摘录及独立峰谷/量图/Notebook静态合同；未运行Notebook/benchmark |
| P5-04、14、15、19 | 当前识别/跟踪/记录/历史查询/恢复/观察与API/debug合同全部有完整通过行；37×4每截断覆盖保持，正式1%/零中性/近远切换/逐根价格与显示规则未改 |
| P5-07、08、21 | 3503旧路径、3282删除项和221目标逐项可解释，7抽取根键与两个摘要的嵌套白名单通过、8单元Notebook无执行输出；207原字节/7逐字段迁前交接在原范围复用，没有重复全读148MiB资料 |
| P5-16、17、18 | 单根预测与整数文本、三例原图13项离线单组回归通过；只沿原材料/端点/8MiB边界，不构造新视频一致性或双组回测结论 |
| P5-20 | P4工具、5个Web文件、28前端、类型/构建及根三份架构/组织节点全部完成；临时SQLite/Gold/loopback、原真实客户端/ASGI边界，无生产r4开放或预算变更 |
| P5-22 | 前次首错保留，获本次明确授权后仅修临时脚本并补静态审计；65个原有效完整结果复用，未重收集/重跑业务，进程已退出、暂存区为空、范围外修改保留 |

完整逐行结果保留于§22.16.4，最终四项静态结果追加在原临时results.json；原8.static.references失败只有在8.static.references_after_import_fix同范围通过后登记为历史已解决，原行未删改。有效测试与静态证据分别对账，临时脚本错误不算作产品失败，也不抹去其实际发生/当时停止。当前证据足以完成本次第三步，后续只等待第四步最终交付安排。
