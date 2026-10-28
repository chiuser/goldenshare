# 徐小明r4算法优化LLD v0.1

日期：2026-10-28。状态：**B1及修复已提交ea90f7f2/faaaa6b5，B2已提交fbfb6b72；§10—14保留研究v1的实现和验收事实。当前新增决定为已有钝化近参照失效而远参照合格时，当根完成B→A并保持钝化；研究v2当根切换及人工验收/独立审计已完成，证据见§15.7；真实922根v2对照未运行，r2产品与C不动。**对应[方案](../../../../docs/product/xxm-r4-implementation-plan-v0.1.md)。

阅读顺序：§1—8及§15为当前设计，§15明确研究v2相对已提交v1的变更；§10—14为历史执行记录。当前研究源码已为v2，人工/代码验收见§15.7；§13的真实对照仍属于v1，不能混为v2真实通过。

## 1. 固定范围

r4改变：历史同色段B优先、A备选、最多两个；零柱不分段、不作反色、不计有色根数；已有DULL的B被严格突破而A完整合格时，当根切A保持钝化，取消前完成，不等下一根。最后一项为研究v2新增顶部处理，底部保留原取消前换参照。零日允许符合条件的首次钝化、底部等待重新钝化及同逻辑段切换。保持原始float、累计收盘价/DIF极值、相邻1%、首次TOP当根DIF>0、真实换色独立确认及STRUCTURE/历史/等待的其余政策，具体边界见§5.3/§15。

当前r2判别规则与两位/日线独立成果保持。此前共享安全检查例外为产品目录`src/biz/services/wealth/market/index_detail_xxm/`中的`types.py:XxmBar.validate`、`snapshot_validation.py`、`calculator.py:XxmCalculator.restore`及恢复状态检查（含§11编号补核）和对应测试；§3.2/§3.3/§5.4保留其要求。本次当根切换只设计研究计算器和观察/比较配合，不再修改产品共享安全代码、MAIN_SPEC、页面、API或封存原件，不安装、启动服务或保存结果。B1/B2完成事实见历史记录；本轮已按§15.6完成编码及人工测试，不读真实行情、不跑真实对比。后续计算仍不得隐藏读行情/源码或新增源码SHA保护，生产模块不得导入研究目录。

## 2. 已核源码及依赖

| 位置 | 开工前处理 | r4落点 |
|---|---|---|
| `src/biz/services/wealth/market/index_detail_xxm/calculator.py:step` | hist正负零分别切段；累积价格/DIF；1%状态转换 | B阶段在独立研究类复制该step并限定修改；C阶段才替换产品 |
| 同文件`_select_eligible_reference` | 最近价门槛后按DIF强弱排序 | B→A固定时间顺序 |
| 同文件`_rescue_bottom_dull_reference` | 产品r2仅底DULL在取消前检查替代；已提交研究v1也仅底部 | 研究v2以`R4Calculator._rescue_dull_reference`统一同段顶/底DULL的B→A检查，替换研究类旧底部方法及step调用；r2方法不改，见§15 |
| 同文件`_advance_rearm/_advance_bottom_history/_start_bottom_history` | hist>=0会结束底部原段/等待 | 零不结束；符合条件的零日重新钝化；真实红柱才退出原绿段；原DIF/当根收盘规则和关联保留 |
| 同文件`snapshot/restore/_validate_rearm_snapshot` | restore已先解析后赋值；Wave、普通参照和顶部历史检查不全，等待要求previous.hist<0 | 补共用安全检查，保持副本字段/签名；r2保留独立零段，r4允许原绿逻辑段末根为零；研究身份独立 |
| `src/biz/queries/wealth/market/index_detail_xxm/query_service.py:SeriesEntry.calculator_at/_load_series` | 最新复制和历史位置分别在calculator_at调用restore；追加行情前_load_series也恢复旧进度 | B1前按§7.1用人工输入直接验现查询调用，不改查询、缓存、API；C阶段的r4身份迁移另行实施 |
| `types.py:Wave/XxmBar` | 色段方向、首末/count、价/DIF及位置；完成K线校验未明确排除bool数字和真值完成标志 | Wave不新增字段；XxmBar共享安全校验按§3.2收紧，r2/r4共同使用；count在r4只数有色柱 |
| `spec.py:MAIN_SPEC` | `xxm-direction-v0.1-r2`，1%，max_refs=2，min_bars=2 | B阶段保持真实父Spec；新增研究Spec，不伪造产品Spec |
| `forecast_entry.py:stable_reference_on_band` | 合格性证明含DIF排序 | C阶段按B→A顺序证明，不能由r2校验r4 |
| `forecast_paths.py:_prefix_signature/_flat_cannot_switch/_outcome` | 最强池、零停止、最强优先快路、ZERO_RESET | C阶段必须改；具体反例见§8 |
| `forecast_joint.py` | DIF转折目标要求严格原色 | C阶段允许同逻辑段的真实零；真实反色仍单独检查 |
| `forecast_query_service.py`及schema/Wealth adapter | direction由最后hist推导；零退出和版本有硬校验 | C阶段从计算状态取方向，枚举/版本同步 |

已用CodeGraph `impact(_select_eligible_reference)`核调用影响，并对索引未覆盖的产品与预测文件补读。旧研究`top_reference_priority.NearFirstCalculator`只改TOP且使用当根收盘；r4使用当前段累计价格、顶底均改，不能直接作为r4。

## 3. B阶段文件和身份

本轮文件和后续批次职责（实际完成见§10）：

| 批次 | 文件/符号 | 职责和停点 |
|---|---|---|
| B1前共享检查 | 产品目录`types.py:XxmBar.validate`、`snapshot_validation.py:ParsedXxmSnapshot/parse_xxm_snapshot`、`calculator.py:restore/_validate_restored_state`；主题`tests/test_xxm_input_validation.py`、`test_xxm_snapshot_validation.py`、`test_xxm_snapshot_consumers.py` | 按§3.2/§3.3/§5.4统一检查，完成R4-16A及R4-17：验正常r2继续/预测复制/现查询恢复、坏副本拒绝、失败不改原对象及§3.1规则审计；不以前置执行r4测试、源码SHA或封存试验代替验收 |
| B1 | `scripts/research/index_market/xxm/r4_reference_trial.py:R4TrialSpec/R4Calculator` | 不可变研究规则、B→A选择、零日处理、独立编号和快照；共同输入调用同一XxmBar.validate；按规则登记交付审计，不开发源码指纹检查 |
| B1 | 主题`tests/test_xxm_r4_reference_trial.py` | 选择、零日、历史/等待、快照/编号的独立人工序列，含R4-16B的r4合法/错误副本；不运行双组行情重放 |
| B2 | 同目录`r4_comparison.py:compare_r4` | 接收已验证同源XxmBar元组，以两个独立对象计算逐根结果和差异；不自己取行情，来源接入另按本步合同 |
| B2 | 主题`tests/test_xxm_r4_comparison.py` | 先手写记录检比较，再按本步授权验同源输入、逐根差异、关联、预算和隔离 |
| 各批收尾 | 主题README | 仅记录已完成批次和当前停点，不提前发布下一批运行命令或恢复封存模块 |

B1前完成共用检查、现r2的R4-16A及现查询的R4-17，不要求r4测试通过；随后B1实现r4计算器并完成R4-16B等人工验收，停止汇报。比较器代码和真实对照均归B2，不在B1提前实现或运行。B2前先完成实际来源、字段转换及只读保护交接，日期范围沿§6.1已定决定，不再重复询问。

`R4TrialSpec`在研究v2集中定义：`research_version='xxm-research-r4-v2'`、新增固定`active_reference_policy='same_bar_near_to_far_on_dull_break'`、保留`reference_policy='nearest_then_farther_two'`、`zero_policy='neutral_real_opposite'`、`allow_zero_activation=True`、`allow_zero_reactivation=True`、`dif_turn_pct=1.0`、`max_refs=2`、`min_colored_bars=2`及`max_input_bars=1000`、`deadline_seconds=20.0`、`max_memory_bytes=256*1024**2`、`max_result_bytes=16*1024**2`。已提交B2代码为v1；本轮未提交工作区已升级v2并增加该字段。活动参照字段及两个allow_zero字段只登记已确认规则，固定值进入规范序列化/hash，不是调用方可切换参数。唯一来源为此不可变研究Spec，消费者为研究计算、编号/恢复、观察/比较及测试；无env、Settings、数据库、磁盘或页面配置，规则变化不得静默复用v1身份。

研究hash只包含研究版本、完整r4规则（包括两个固定True的零日决定）及父MAIN_SPEC描述的规则身份，不包含源码文件路径、字节或SHA。该值只用于区分内存中的计算版本/事件和拒绝跨组恢复，不读取源码，也不证明代码是否被修改。父MAIN_SPEC仍使用现行真实r2，不伪造产品Spec。r2代码是否仍符合原业务规则，按§3.1登记、测试和开发后审计确认；本设计删除源码SHA清单，不再要求为r4固定新的文件指纹。

`R4Calculator(*, period, source_identity, ts_code='000001.SH', trial_spec=R4_TRIAL_SPEC)`继承真实r2类及未变方法，父`spec`仍为MAIN_SPEC。原始输入身份保存在`input_identity`；父source_identity固定组合`r4|研究hash|period|input_identity`，不允许调用者传任意父Spec。研究`_id`将研究hash与父编号组合，日期筛选不参与规则身份。`snapshot()`包含研究版本/hash、原始输入身份及父状态，`restore()`先完整校研究身份、来源、字段和状态，在临时对象完成父恢复及r4检查，最后才替换目标状态，具体见§5.4；错误或跨组快照不得改变已有对象。r2对象不能接受r4包装快照，r4不能接受r2或两位快照。

不把零hist改成极小值后调用父step；不调用父step再删事件。研究step以当前r2流程为基础，只改变§4—5/§15批准的规则。研究v2使用`step/_select_eligible_reference/_rescue_dull_reference/_qualifies_bottom_close/_advance_rearm/_advance_bottom_history/_start_bottom_history/_validate_rearm_snapshot/_validate_restored_state`及身份包装；其中`_rescue_dull_reference`替换研究v1的底部专用方法，不保留研究旧名转发或调用两遍。r2原底部方法和观察不动，未变方法继续继承。恢复共用§3.3解析，不复制通用检查，不改价格窗口、1%或历史价格退出条件。

### 3.1 r2规则登记与开发后审计（2026-10-28已确认）

r2核心事实直接采用[当前代码总结v0.5第1—4节](../../../../docs/product/xxm-direction-algorithm-plan-v0.5.md)，本轮已按当前calculator.py/spec.py/types.py复核；不在多个文档另造不同的r2版本。r4获准变化在本方案及§4—5维护，不能反写为r2当前事实。

| 登记范围 | 开发后应核对的内容及代码位置 |
|---|---|
| v0.5 §1输入/周期 | 上证及四周期分别计算，使用源close/DIF/DEA/柱，不重算EMA、不取两位；MAIN_SPEC仍1%。核types.py/spec.py及step入口 |
| v0.5 §2分段/极值/池 | r2仍按原正负零切段、整段累计收盘/DIF极值、每向最多两个旧段；r4只按批准改真实反色/零中性，窗口及数量不扩。核step及Wave更新 |
| v0.5 §2首次/选参照 | r2最近价格门槛后选DIF最强合格者、至少两根、TOP当根DIF>0、严格价/DIF；r4仅改B→A及已够根数的零日资格。核选择函数及首次入口 |
| v0.5 §3转折/取消/翻色 | 相邻实际DIF的1%与前值0保护、原值突破优先、首次单事件、真实翻色独立形成；不得借r4改成两位或扩大取消。核step事件顺序 |
| v0.5 §3.3底部救援 | r2仍仅既有同段底DULL取消前救援；研究v2按§15补齐顶DULL当根B→A、保留底部处理。不每根重选，不扩大STRUCTURE/WAITING/真实翻色 |
| v0.5 §4历史/等待 | 结构形成冻结原极值、顶底历史不同退出、无固定到期；等待沿保存参照和当根收盘。r4零日离段及重激活差别按§5，不新增其他价格窗口或事件 |
| 共享安全检查及编号 | 只允许§3.2/§3.3/§5.4收紧非法行情/进度副本；正常r2业务输出、副本字段、编号和关联保持，r4使用独立研究身份。核共享validate、恢复解析、最后赋值和事件构造 |

每项交付列出：登记规则、真实实现函数、实际变化、独立人工预期/回归测试、执行结果和未覆盖项。完成后独立阅读代码，检查是否符合登记及批准范围，发现误改先解释修正，不用修改登记来迎合错误实现。此为开发/评审工作，不让运行中的计算器读取源码、校验源码SHA、比较AST正文或动态证明代码未变。

不落盘仍表示行情、结果和恢复文件不写磁盘；算法不隐藏读取旧标签、旧结果或额外行情。正常程序导入和开发审计的源码阅读不在此限制内。版本、MAIN_SPEC/spec_hash、研究规则身份、标的、周期和input_identity的内存校验继续保留，目的在于避免拿错数据或把r2进度交给r4，不作源码保护。

封存两位及某些历史运行仍有其原有源码SHA检查，历史原件和成绩保留，不删除或改成r4新检查。共享types.py或恢复实现修改后，它们可能拒绝当前源码，须如实说明，不能改旧SHA/历史manifest或skip冒充通过。本轮不运行这些封存重放/专用测试，不把其恢复或通过列为共享安全检查/B1前置；以后专门复现历史时，另定原版本环境。当前定向验收只声称覆盖本轮明确执行的r2人工回归和新测试，不冒称全仓或封存实验全部通过。

### 3.2 共享单根行情输入安全检查（方向已确认）

统一实现落在现`XxmBar.validate(period)`，不在r4单写另一份。r2现step首行已调用它，r4复制step也须在任何状态变更前调用；恢复中的previous字段仍调用同一方法。方法签名和正常返回保持，不能借安全修正更改1%、取价、选峰、换色、救援、历史/等待、事件编号或MAIN_SPEC。

| 检查项 | 开工前r2事实 | 本轮统一要求 |
|---|---|---|
| close/dif/dea/hist类型 | 仅按数值运算和math.isfinite检查，bool可能作为0/1通过 | 接受正常int/float，先排除bool及None/字符串/其他非法类型，再检查有限性；不隐式转数字或补值 |
| completed | 仅按真值判断，1等也能通过 | 必须`completed is True`，False、0、1、字符串等均拒绝 |
| 非有限值/收盘正值 | 已拒NaN/无穷及close<=0 | 保留；DIF/DEA/柱允许合法0或负值，不新增符号门槛 |
| time类型/日期/时区 | 已有日线规范日期和分钟+08:00检查，非法类型可能先抛TypeError | 先核time为非空字符串，保留原日线日期和分钟时区含义；非法字段明确ValueError，不静默规范化或修补 |
| 日期升序唯一 | r2.step在状态更新前已检查 | 两组保留该顺序，不把此检查搬到更新之后 |
| 交易日/分钟端点完整性 | 产品`queries/wealth/market/index_detail_xxm/source.py:assert_continuous`已有来源核验 | 留B2来源层按实际合同核验，不在单根检查中猜日历，也不误称r2完全缺失 |

本节单根输入改动只落types.py及相应测试，恢复改动另按§3.3/§5.4。非法输入在任何状态变更前拒绝，统一抛ValueError；拒绝后原计算器不变，合法下一根仍能继续。正例包括普通int/float、日线合法日期、合法分钟时区和零值指标；反例包括True/False数值、完成标志1或字符串、None、字符串数字、NaN/无穷、非法时间类型和逆序/重复输入。有效r2人工序列的point、事件、原参照和历史/等待关联必须与修改前独立预期完全一致；不拿重新计算出的结果生成expected。本节已由§10的定向人工验收覆盖，不据此声称真实来源或产品整链通过。

### 3.3 共享内存进度副本检查（2026-10-28已确认）

改动前r2.restore已先在局部变量中解析检查、最后才替换自身；本轮保留顺序并补齐Wave、普通reference及顶部pending等检查。`snapshot()`的字段、`restore(snapshot)->None`签名、规则身份、事件编号及现预测的`restore(snapshot())`调用保持；不新增副本格式版本、保存文件、恢复入口或配置项，不改step判别。坏副本被更明确地拒绝，正常副本继续计算结果不变。

通用实现放在同产品目录`snapshot_validation.py`，只依赖标准库及本目录types；不导入研究、App、QTF，不读取源码/行情/文件或访问网络/数据库。定义仅供内部使用的`ParsedXxmSnapshot`，保存恢复所需的九项进度；定义`parse_xxm_snapshot(snapshot, *, expected_identity, period, max_refs)->ParsedXxmSnapshot`。expected_identity为调用者已有的`specHash/tsCode/period/sourceIdentity`，不从来件接受新身份。先核固定字段和容器数量，再解析为独立对象；具体字段及关系检查见§5.4，不调用step重算历史或补缺值。

`XxmCalculator.restore`复用该解析，随后动态调用现`_validate_bottom_history_snapshot`、`_validate_rearm_snapshot`及新增`_validate_restored_state(parsed)`。前两者保留原r2业务关系要求，r4只覆盖已批准的零日差异；最后一个方法分别核本算法的wave/previous/零段关系。r4包装检查研究身份后，使用同一父restore处理临时r4对象，不另写通用数值/字段检查，也不在共享模块加入r4模式开关。只有全部成功才发布九项进度。

恢复不要求来件比目标更新，允许在已使用对象上回到更早的合法前缀。不能要求历史结构保存的原参照一直存在于最近两段池；仅当前活动reference、WAITING保存的referenceWave按现有关系核池。正常r2零段及前缀样本、失败不改对象、预测复制和现查询恢复均是B1前的定向验收；r4合法零日副本归B1，不以源码SHA或整段真实重放证明安全。

## 4. 选择函数的具体要求

历史池仍按完成时间正序保存，最多两条。设`pool=list(reversed(history))[:2]`，第0条是B，第1条是A。每条必须来自经过真实反色结束的同色段；零日不入池。

定义方向`s=1`顶部，`s=-1`底部：

```python
def select_reference(wave, history):
    if wave.count < 2 or not history:
        return None
    pool = list(reversed(history))[:2]  # B，然后A
    if wave.sign * (wave.price - pool[0].price) <= 0:
        return None
    for ref in pool:
        if (wave.sign * (wave.price - ref.price) > 0
                and wave.sign * (wave.dif - ref.dif) < 0):
            return ref
    return None
```

`wave.price/dif`是截至本根的逻辑色段累计极值。顶部取最大值，底部取最小值，不需要同一日期。B价未突破，不得返回A；B完整合格即停，不考虑A更强。B失败后A仍独立校自己的价格/DIF。A不存在/不合格直接None，没有第三条搜索或“取全历史最强”的兜底。

例顶部B(price=120,DIF=20)、A(price=130,DIF=30)：

| C累计价/DIF | 应选 | 理由 |
|---|---|---|
| 119/10 | 无 | 未突破B |
| 120/10 | 无 | 等于B不是突破 |
| 131/15 | B | 两者都合格，近者优先 |
| 125/25 | 无 | B的DIF失败，A价格失败 |
| 131/25 | A | B的DIF失败，A独立合格 |
| 131/30 | 无 | A的DIF相等不合格 |

此函数不替代TOP正DIF、至少两根及等待资格。普通首次要求已有非零逻辑方向，`raw_sign in (0, wave.sign)`、有色count>=2且无更高优先事件/等待阻断；最新完成K线为零也可调用，零不增加count。TOP仍要求`bar.dif>0`，底部不新增正负号限制。完整首次步骤见§5.2。已有DULL只在§15规定的B严格失效时调用该函数检查A，不每根随意重选；已选A不回切B，也不扩第三个。

## 5. 色段与零日的逐根处理

### 5.1 原始色和逻辑段方向

`raw_sign=(bar.hist>0)-(bar.hist<0)`保留真实源值；`logical_sign`是当前Wave.sign。没有当前段且raw_sign=0时不创建Wave；raw_sign非零才建立第一段。已有段遇零时logical_sign保持，不执行历史入池、换色事件或state/reference重置。

只有`raw_sign == -old_wave.sign`才完成真实反色：按r2顺序检查旧方向事件、保存旧段并截池至两条，建立新段。旧段可包含尾部零日，end是最后一根零日；第一根反色不加入旧段。首个源段可能左侧不完整，仍保持r2源首日空状态的限制，不伪造更早历史。

每根完成K线都更新previous/processed；存在逻辑段时更新其end及价格、DIF极值，零不增加Wave.count，有色才加1。极值方向必须取`wave.sign`，不能用零日的raw_sign=0，否则§5.5的100.5175新高会被漏掉。存在Wave时的更新要求如下，price_at/dif_at分别记录真实发生日期，不强行同日：

```python
wave.end = bar.time
wave.count += int(raw_sign != 0)
if wave.sign * (bar.close - wave.price) > 0:
    wave.price, wave.price_at = bar.close, bar.time
if wave.sign * (bar.dif - wave.dif) > 0:
    wave.dif, wave.dif_at = bar.dif, bar.time
```

新建/真实翻色的Wave仍从count=0开始，首根有色更新后为1；无Wave的开头零不执行以上代码。相等极值保留原r2先前位置。最长柱、全部局部峰谷等不是r4新要求，不为此接入独立日线模块。

### 5.2 零日允许什么

2026-10-28管理员按§5.5两个数值场景确认：已有至少两根对应有色柱、其余资格满足时，允许零柱日首次钝化；底部等待时，零柱日收盘重新合格且原参照有效，则当天重新钝化。原“零日不首次/不重新激活”建议已撤回，不保留双策略。此为本轮试验口径，后续须补其他案例；没有声称作者课程或软件已经验证本规则。已有DULL/STRUCTURE零日照常检查的决定继续有效。

2026-10-27只读检查已有`daily_source.csv`的912根日线（2023-01-03—2026-10-13），源MACD柱值恰好为0的记录为0；这不是截至当日全部来源的结论，也不能用接近0或显示为0的柱冒充真实零柱案例。演示输入必须注明人工或模拟，不得声称真实历史已出现。

| 本根进入前状态 | 零日的处理 |
|---|---|
| 无Wave | 返回NONE、无方向/事件，保留previous和processed |
| NONE且无等待 | 更新段极值后按完整首次资格检查；有色count>=2且价格/DIF等全部合格则当日DULL/activation，否则无首次事件；已有历史观察仍正常推进 |
| DULL | 保留逻辑方向；先按§15同段B→A当根检查，再对有效参照检查突破和相邻1%转折；A不合格才按原取消 |
| STRUCTURE | 原参照有效时按原1%回转进入纠错；底部按当前收盘和原DIF资格决定回到DULL或消失/等待，零日仍属原逻辑绿段，不仅因hist=0强制消失 |
| 底部WAITING | 不因零结束；原参照DIF严格突破先INVALIDATED；原绿段内、晚于消失当天且当前收盘和DIF/根数重新合格则当日REACTIVATED，并产生DULL/reactivation；其余继续WAITING |

零日DULL可以形成STRUCTURE，也可因原参照被突破而取消；不能继续写成零必NONE。相邻比较仍使用紧邻前一根实际完成DIF，保留`basis != 0`原保护；不跳过连续零日。真实flip仍独立形成，零本身不是color_flip。

零日首次入口的编码顺序固定为：①已有Wave且`wave.sign`为±1；②本根属于该段，已完成且`raw_sign in (0, wave.sign)`；③本根没有更高优先事件、无等待阻断、state=NONE且reference=None；④完成§5.1累计极值更新后，非零同色count>=2；⑤TOP当根DIF>0；⑥用§4的同一个B→A函数校最近价格门槛及各参照严格价格/DIF。全部通过才deepcopy所选参照，state=DULL，产生一条`type='DULL', route='activation'`，方向取wave.sign；当根不再走1%结构分支。无Wave/仅一根有色柱/价格或DIF相等/参照不存在等仍无首次事件。底部首次以逻辑绿段镜像执行，不因为零柱临时创建新段。

### 5.3 事件顺序、历史及等待

研究v2顺序：完成真实换色及旧方向事件→更新当前段→推进等待→已有同段DULL的B→A当根检查→有效参照突破→已有DULL/STRUCTURE的1%分支→无活动时首次资格→历史更新→返回point。切换发生在取消之前，不先产生CANCEL再删事件，也不先清空再走activation。普通事件仍最多一条；切换本身不是普通事件，不新增首次钝化/结构同根双事件。

已有状态的原参照突破、1%差值及事件方向同样使用`wave.sign`，零日不能因raw_sign=0跳过这些分支；raw_sign继续用于真实翻色、有色根数及红/绿/零历史统计。先出现的事件或等待阻断仍阻止本根后续首次检查，不因零日放开资格就删除原优先级。

`R4Calculator._rescue_dull_reference`要求进入本根前及当前均为DULL、`wave is old_wave`、无等待且未产生更优先事件；原参照为最近B，`wave.sign*(wave.dif-B.dif)>0`才检查A。真实零仍属原段，可检查；真实反色、STRUCTURE、WAITING不进入。A须按§4同时满足累计收盘和DIF的严格条件；合格时deepcopy A替换活动reference，保持DULL，随后同一根使用A检查突破及原1%。失败保留B交给原取消分支，不扩候选或放宽等号。详细代码步骤与观察交接见§15。

`_qualifies_bottom_close`用于已有结构纠错及等待重新激活，二者都接受原逻辑绿段中的绿柱或零柱，即`wave.sign == -1 and raw_sign in (-1, 0)`；仍要求有色count>=2、`bar.close < min(reference.price, nearest_price)`及`wave.dif > reference.dif`。结构纠错合格则按原分支回DULL，不合格则消失并等待；不能只因hist=0强制消失。首次底部资格仍调用§4累计极值选择，不能拿此处当根收盘门槛替代首次选峰的价格口径。

`_advance_rearm`的本根顺序固定为：①真实红柱到达或`wave.start != record.segmentStart`时，按原SEGMENT_ENDED结束等待；零柱不在此结束；②`bar.dif < saved_reference.dif`则INVALIDATED，不能先重新激活；③仍在原绿段且`bar.time > record.disappearedAt`，用上述函数检查当根收盘、原参照/保存的nearestPriceGate、累计DIF及至少两根；成功时恢复保存的原参照和state=DULL，等待记录REACTIVATED/price_requalified，产生原`DULL/reactivation`事件。事件的relatedRearmId关联原等待，等待记录的bottomHistoryId/structureEventId继续关联原历史和结构；保留原r2字段和值，不额外给事件补写原来为null的relatedBottomHistoryId。条件不足只更新observedThrough，保持WAITING。

重新激活不重新按B→A选参照，不用过去累计最低收盘代替当根收盘；价格等于任一实际约束门槛不合格。WAITING成功后保留r2原event_type/blocked顺序，当根不追加首次activation或STRUCTURE；新建等待的同根也不得重新激活。连续零日若已重新DULL，后续按已有DULL的保持/结构/取消处理，不重复生成reactivation。等待可由零日创建，校验与恢复不得因previous.hist=0拒绝合法WAITING、DULL或STRUCTURE。

底部历史`leftOriginAt`只在真实红柱到达时写入；零日不离开原逻辑绿段。零日DIF转折创建的底部历史`leftOriginAt=None`，真实flip创建的按原r2填写翻色时点。严格原参照突破、新底部事件、真实离开后跌破原最低收盘等结束规则和优先级保留。

顶部历史`ageBars/negativeBars/zeroBars`仍分别按真实输入统计；`colorChanges`在r4按真实非零反色计数，红→零→红不加、红→零→绿加1。snapshot/逐根结果明确这些含义，不能只在展示层改。

point的`hist`永远是真实源值；活动状态的`ordinaryDirection`取逻辑段方向，不从当日hist=0推成空或BOTTOM。无活动状态仍按原合同返回空方向，不新增point字段。

### 5.4 恢复的具体检查

本节共用安全检查及分别检查算法差异的改动已由管理员2026-10-28确认。r2.restore按§3.3补齐通用检查，r4继承复用；逐根判别分支及各自业务政策不变。不新增恢复文件、数据库记录、后台任务或恢复命令。

这里的`snapshot/restore`只负责**内存中的一份计算进度副本**：例如算到6月30日，复制当前段、原参照、钝化/结构及等待状态，再从7月1日继续；用于检验分批与连续计算是否一致，不是保存行情或做磁盘断点续跑。每次正式对照仍从2023-01-03空状态开始，不能从旧算法结果接算。

用人话说，计算器读到一根K线时，除了当日数字，还记着“已算到哪根、正在红段还是绿段、当前钝化或结构、比较哪个旧峰谷、上一根DIF和等待情况”。把这些当前进度复制到另一份内存里，让另一份接着算，就是这里的恢复。只列关键字段的演示：原进度为底部钝化、旧谷DIF−8、上一根DIF−6；下一根DIF−5.9且其他条件仍有效时，副本应与原进度继续计算一样，按1%得到结构。若副本漏掉旧谷，程序就无法检查原参照突破；若把DIF写成NaN，大小比较也不可靠，应拒绝副本，不补猜参照、不改原进度。

它有两个已有用途：测试“连续算100根”与“先算60根、复制进度再算40根”是否一致；现r2的`forecast_detector.clone`会复制当前进度再试算假设价格，避免改到真实行情已经算出的状态。后者是现r2用途说明，本轮不因此开发r4预测。整段r2/r4对照仍各自从头计算，不依赖恢复文件或人工保存；进程退出后本轮内存释放，下次重算，不承诺跨进程恢复。r2副本不能交给r4，两组也不能共用一份可变进度。

**共用解析的检查清单如下。**检查的对象是当前副本，不能读取完整行情来验证这些值是否真是历史极值，也不能重新判断首次钝化、改选参照或补算事件。

| 对象 | 明确检查及空值含义 |
|---|---|
| 最外层字段及身份 | 字段严格为现snapshot的`specHash/tsCode/period/sourceIdentity/processed/wave/history/state/reference/previous/pending/pendingBottomHistory/pendingRearm`；身份等于目标对象；缺列/多列/错类型拒绝，不读文件计算身份 |
| processed、state、previous | processed为非布尔整数且≥0；state为NONE/DULL/STRUCTURE；previous按现XxmBar完整字段解析并复用validate。processed=0只允许原始空进度；processed>0必须有previous，不与目标当前processed比较新旧 |
| Wave和history | Wave字段严格对应现dataclass，空只能用None，不能把空字典当None。sign为非布尔整数，通用解析允许−1/0/1；count为1至processed的整数；price有限且>0，DIF有限，bool/字符串数字/NaN/无穷拒绝。start≤price_at/dif_at≤end≤previous.time，当前wave.end=previous.time。history保留原snapshot的字符串键`1/-1`，每池列表≤max_refs；池内方向正确、发生顺序严格、区间不重叠，结束早于当前段开始 |
| 活动reference | 完整Wave；DULL/STRUCTURE必须有同方向的非零wave及reference，reference等于对应池中的一条旧段；NONE不得带活动reference。缺失不能改成NONE或猜一个旧峰谷；不重新检查当前收盘是否仍满足首次门槛 |
| 顶部pending | 严格保留现字段`id/confirmedAt/confirmationRoute/pricePeak/pricePeakAt/originalReference/status/endedAt/endReason/observedThrough/ageBars/negativeBars/zeroBars/colorChanges`；只接受PENDING且endedAt/endReason为None；冻结价格正且有限，原参照严格四字段`startTime/endTime/price/dif`并校数字和日期。pricePeakAt≤confirmedAt≤observedThrough=previous.time，原参照结束早于confirmedAt；各计数为0至processed的整数，negativeBars+zeroBars≤ageBars，colorChanges≤ageBars。不能因普通状态为NONE就删掉仍在观察的历史 |
| 底部历史及等待 | 字段分别严格对应现XxmBottomHistory/XxmRearmRecord；内部价格均正且有限，DIF均有限，计数非布尔整数且有界，日期按本周期且无未来。活动历史为PENDING、等待为WAITING，结束字段为None；observedThrough=previous.time。普通状态仍为BOTTOM STRUCTURE时，必须有同一当前绿段、尚未离段、confirmationRoute=dif_turn且originalReference与活动reference一致的底部历史，以便下根按原规则纠错；缺失/不匹配须在恢复赋值前拒绝。TOP STRUCTURE不要求顶部历史仍在，因其历史可能已按原价格规则退出。继续调用现底部历史/等待方法核具体日期、编号和关联，不放宽原要求 |
| 所有时间和关联 | 时间复用本周期格式检查，不改写或补齐；编号须非空，关联用当前对象的_id核验。顶部历史id按现`_id('history',confirmedAt,confirmationRoute,originalReference.startTime)`检查；底部历史同时核实`structureEventId == _id(confirmedAt, 'STRUCTURE', -1, originalReference.startTime)`及`id == _id('bottom-history', structureEventId)`，两项均在赋值前完成，两编号一起改错也拒绝，dif_turn/color_flip使用同一生成公式；等待沿原方法。历史原参照可已离开最近两段池，不能统一拒绝；活动/等待参照则核现有池关系 |

共用解析只生成独立的`ParsedXxmSnapshot`，不持有来件的可变字典/列表，不调用目标对象赋值。无活动记录时对应字段为None；history始终是两个列表。所有日期关系及计数均相对于副本自身previous/processed，合法回退不能被误拒。没有全量行情时无法证明极值计算本身正确，这项正确性由独立人工序列及连续/分批对账验证，不冒称恢复检查已证明。

**不同规则分别检查。**`XxmCalculator._validate_restored_state(parsed)`要求r2在processed>0时有wave，wave.sign等于previous柱符号；独立sign=0段及其原有历史状态合法，不能强制±1。r4覆盖该方法：wave仅±1；末根previous可为零，非零时须同向；开头全零可wave=None，但无历史池、活动/历史或等待。r4的WAITING允许previous.hist=0，仍须是原逻辑绿段且无活动reference/旧bottom history；r2原等待仍要求真实绿柱。两者原DIF突破的等待都不能恢复有效。不得增加“当前状态须重新满足首次价格门槛”等业务要求。

**赋值顺序固定如下：**

1. r2.restore调用`parse_xxm_snapshot`，先核字段集合/容器数量和身份，再复制、解析所有数值和日期为独立临时进度；不修改self或来件。字段和原有池数量有界，不复制完整行情或事件账本。
2. 对临时进度调用原底部历史/等待校验，核顶部历史编号，并动态调用`_validate_restored_state`；r4调用时实际执行其覆盖方法，不能先强行通过r2零段规则。原底部业务条件和已有编号生成不改。
3. r2全部检查成功后，最后仅替换`wave/history/state/reference/previous/pending/pending_bottom_history/pending_rearm/processed`九项；固定身份不从来件覆盖。明确拒绝统一抛ValueError，字段解析的KeyError/TypeError/AttributeError/OverflowError按原模式转成ValueError；不能吞掉未知程序错误或返回半份成功。
4. r4.restore先核外层研究版本/hash/对象/周期/来源及父字段集合，建立同身份临时r4对象candidate，显式调用`XxmCalculator.restore(candidate,parent_state)`复用上面检查，不递归调用candidate.restore；成功后才将candidate的九项进度替换到实际r4对象。不能先调用目标的父restore再回滚，也不允许r2副本绕过外层包装交给r4。

任何一步失败，目标对象、来件及此前返回记录均不变；随后恢复合法副本仍可成功。连续、任意分批、合法回退、零日前后复制再继续的逐根结果必须一致。既有r2预测clone不改调用方式，须用合法假设K线验证未误拒；不因此开发r4预测。

上述复制/检查和最后验收都纳入研究既定20秒、256MiB及现产品识别4秒/预测200ms预算，不另放宽；B1前使用有界人工序列定向验收，B2再验两组1000根总体预算，C再验真实产品整链。进程中断只释放内存，下次重算，无恢复文件或中断续跑成本。

### 5.5 两个零日场景及已确认预期（2026-10-28）

以下不是已找到的市场案例；原先按EMA12/26、DEA9逐根做算术核对，本轮已由R4单组人工测试验证对应标签，见§10。标准递推是EMA12＝前值×11/13＋收盘×2/13，EMA26＝前值×25/27＋收盘×2/27，DIF＝EMA12−EMA26，DEA＝前DEA×0.8＋DIF×0.2，柱值＝2×(DIF−DEA)。表中非零小数省略显示，零日按精确关系计算，不把四舍五入得到的0当真零。

**场景一：已有两根红柱，零柱日才首次价格合格。**人工给定更早的旧红段B最高收盘100、DIF峰6，B与当前红段之间已有真实绿柱；当前红段此前没有收盘超过100。

| 顺序 | 收盘 | DIF | DEA | MACD柱 | 目前条件 |
|---|---:|---:|---:|---:|---|
| 红柱日1 | 98 | 5.094545… | 4.9875 | 0.214090… | 价格未过100 |
| 红柱日2 | 99 | 5 | 4.99 | 0.02 | 红柱已有两根，价格仍未过100 |
| 零柱日 | 100.5175 | 4.99 | 4.99 | 精确0 | 首次价格过100，累计DIF峰仍为5.094545…，小于6 |

可复核的EMA状态：红柱日1 EMA12＝95.454545…（1050/11）、EMA26＝90.36；随后收盘99得到96和91；再收盘100.5175得到96.695和91.705，因此零日DIF与DEA都为4.99。**本轮预期：前两日无首次钝化，零日累计最高收盘更新为100.5175，有色count仍为2，DIF峰仍为5.094545…，当天首次顶部DULL/activation，参照B；不追加STRUCTURE。**管理员已选此处理，原草稿“零日仍不首次”不再作为有效候选。不宣称课程已给出零日答案。

**场景二：底部结构消失后等待，零柱日价格重新合格。**人工给定旧绿段B最低收盘100、DIF谷−8，经过真实红柱后进入当前绿段；当前绿段已有至少两根绿柱，累计DIF始终高于−8。以下记录依保留r2条件所做的原人工推演，本轮已纳入R4人工测试，不是市场样本或双组对照成绩。

| 顺序 | 收盘 | DIF | DEA | MACD柱 | 本轮预期状态 |
|---|---:|---:|---:|---:|---|
| 日1 | 99 | −5.980363636… | −4.99875 | −1.963227… | 价格低于100，DIF未破−8，具备底部钝化条件 |
| 日2 | 111 | −5 | −4.999 | −0.002 | DIF回升超过1%，形成底部结构；收盘回升不单独取消钝化 |
| 日3 | 100 | −5.052421652… | −5.009684330… | −0.085474644… | DIF回落约1.048%，达到纠错；收盘等于100，不满足严格低于，结构消失后等待 |
| 日4 | 100 | −5.035915293… | −5.014930523… | −0.041969540… | 价格仍等于100，继续等待 |
| 日5 | 99.3815265787… | −5.014930523… | −5.014930523… | 精确0 | 价格重新低于100，DIF没有跌破−8，当天重新底部DULL/reactivation |

日1 EMA12＝104.263636…（57345/550）、EMA26＝110.244；日2递推得到105.3和110.3。其后逐根递推；日5的精确模拟收盘为`(前DEA−11/13×前EMA12＋25/27×前EMA26)/(2/13−2/27)`，表中99.3815265787…仅为简写。**本轮预期：日3等待、日4继续等待，日5原等待结束为REACTIVATED，原参照B不变，普通事件仅DULL/reactivation，保留原结构及等待关联，不记activation或同根STRUCTURE。**原草稿“零日继续等待”已撤回。

两例的R4人工断言已通过，但不构成市场样本覆盖、原软件相容或双组对照结论。§7补齐有色根数不足、价格等于门槛、原参照突破、连续零柱、底部镜像及恢复等反例；后续新case如需改变口径，先回到方案/LLD说明并review，不临时修改既定expected。

## 6. 输入、比较和资源

### 6.1 已确认的日线范围与同源输入

首次B2明确只执行`ts_code='000001.SH'`、`period='day'`，从**2023-01-03**空状态计算至执行时最新已完成交易日。本轮文档更新日为**2026-10-28**，请求截止日按实际执行日确定，不锁定10月27日。记录请求截止日与来源实际截止日；当天未收盘、休市或来源尚未更新分别说明，不填造当天数据，也不把10月13日旧CSV或10月26日旧对照截止日当成新上限。两组使用同一批已完成日线和原始指标，不能分别选择不同来源或起算日。尚无当天实际输入完整性核验结论。

`compare_r4(bars: tuple[XxmBar,...], *, period: XxmPeriod, source_identity, start_date, end_date, deadline)`归B2，接收内存输入。period显式接受day/m60/m90/m120，统一传给两组计算器、输入校验、快照恢复及报告，不从时间猜周期。每次只接受一种周期和上证对象；逐根复用§3.2共享校验，再检查日期时间升序唯一，不另设r4专用类型口径。start_date/end_date均为上海自然日YYYY-MM-DD且含两端，日线按time、分钟按time[:10]筛选；分钟端点仍按对应周期校验，禁止直接比较日期字符串与完整分钟时间。两组从相同输入首根空状态计算，开始日期只筛报告，截止以后不参与计算或差异归因。算法不自行取行情或读取源码文件，r2实现保持情况由§3.1交付审计确认，不在比较入口动态检查文件SHA。

必须先由实际来源合同验证交易日/分钟端点完整性；比较入口不能把缺失当休市。首轮日线范围已定，无需再问日期；B2执行前仍须写明实际来源、到`XxmBar`的字段转换、只读连接及统一时限、实际覆盖与校验方式。本轮不新建reader/CLI或调用封存的两位reader。优先复用已核同源输入/既有读取保护，不重新计算MACD、不从截图回填原值、不继承旧状态。来源首日前段不足明确披露；分钟的类型支持不代表本次获准执行分钟对照。

创建采用同一共享输入校验的r2与R4Calculator两个独立对象，输入共用不可变XxmBar序列，状态、快照和结果不共享。运行前按已登记的规则/周期/来源身份检查内存参数，再验证输入后顺序计算，每根前后检查共同deadline，最后再核源/规则身份、引用、结果大小和总耗时；不读取或校验源码。开发完成按§3.1独立审计及交付，对照r2原判别政策而非已封存两位组；不改r2判别分支来消除结果差异。

### 6.2 比较返回字段及判断依据

研究返回`R4ComparisonResult`，仅在内存中交给报告输出，不修改产品point/API。顶层字段固定为`metadata`、`rows`、`differences`、`idPairs`、`summary`；逐根记录包括计算前缀，报告按请求日期筛选，不能丢掉开始日前的关联。

| 字段 | 必须保留的内容 |
|---|---|
| `metadata` | tsCode、period、sourceIdentity、来源/字段精度说明、请求起止日、实际输入起止日、计算起点、计算/报告根数、r2版本与规则身份、r4研究身份、实际耗时和截止原因；来源摘要若已有则沿用，不能伪造。不生成或要求源码SHA字段 |
| `rows[].time/input` | 日期、当根原始close/dif/dea/hist及completed，两组共用；源文本有则保留，无则按实际float披露，不补造更多精度 |
| `rows[].r2`、`rows[].r4` | 各自原样point、events、histories、bottomHistories、rearmRecords，以及下述`decision`。原ID和原关联完整保留，不能只留屏幕标签 |
| `rows[].<group>.decision` | 进入本根前状态/原参照、本根原始柱色、逻辑段方向及首末、实际count及含义、累计收盘与DIF极值及各自日期；`referenceChecks`、`selectedReference`和`reason`；已有状态另记相邻DIF前/今值、1%门槛、原参照突破及实际走到的分支。r2零段也计数而r4只数原色非零柱，分别按实际记录，不能用r4含义改写r2 |
| `decision.referenceChecks[]` | 按实际检查顺序记录步骤（最近价格门槛、首次完整资格或顶/底DULL当根切换）、B或A、对应段首末、count、价格/DIF极值及日期，`pricePassed`、`difPassed`、`checked`和`reason`。未检查填null而不是false；区分未突破B、B已选中、沿用原参照、B失效而A合格/不合格。没有A不伪造记录，详见§15 |
| `decision.selectedReference` | 根末真实活动参照及原字段；无参照为null。注明首次、已有DULL当根换参照、等待重用或沿用；切换日startedAt更新为A开始使用日，不改原DULL事件日期/原B，原等待关联按原实际值保留 |
| `differences[]` | 日期、具体不同字段、r2值、r4值、两侧decision中的依据、直接由本日规则产生或由此前哪个差异传递；尚不能解释时明确未知，不编原因 |
| `idPairs[]` | 两组原ID、记录类型/方向及来源段等对应依据；不能仅凭编号不同认定业务差异。不能唯一对应时保留单侧或多候选原因，不强配 |
| `summary` | 两组各事件类型数量、差异日期及数量、首次差异、参照变化/普通状态事件/历史等待变化的分别统计；同日多差异不冒充多天。标签相同但参照或依据不同必须列入，原ID前缀不同本身不计差异 |

`decision`在研究包装层取得实际调用，不看最后标签猜理由；r2只读观测及其排序、原底部方法调用保持。r4首次及允许切换时按B→A，不给r2套上r4的解释。无选择调用记录未检查；已有参照持续、1%转折、取消及顶/底当根切换分别写清，切换前B在before.reference、切换后A在selectedReference.reference，普通事件可为空。观察方法、实际调用次数和原因见§15。

保存组内完整关联；跨组识别业务记录时使用方向、类型、日期及来源段等字段，不删关联来消除差异。跨日期不自动强配“提前/推后”，先列实际日期结果，再解释首次差异及后续传递。原软件另行建立独立预期，不由r2推断；本次仅比较r2/r4，不写r4更准确或已还原作者规则。

### 6.3 限额与失败

限额来自R4TrialSpec：1000根、20秒、进程256MiB、结果16MiB；包括输入检查、计算、对比及最后验收。失败不返回半份成功，不重试、不落盘，下次重新输入从头。只读已有来源也不因纯计算函数获得新的数据库/全局数据读取授权。

## 7. B阶段测试及对账

所有关键expected为独立字面值或人工可算序列；禁止调用选择函数或r2生成expected。B1前先完成§3.2/§3.3共享安全检查、R4-16A、R4-17及r2正常人工回归，按§3.1核登记规则；此时不要求r4尚未存在的测试通过。随后B1覆盖R4-01—10、12—15中的r4计算/恢复要求及R4-16B；B2承担R4-11比较逻辑及完整同源输入/双组预算。R4-12/13按各自代码所在批次验收：B1前验r2/共用检查，B1再补r4，不能把后者倒置为前置。R4-13不做源码SHA或正文匹配。零日首次及等待重新激活的expected按管理员2026-10-28决定和§5.5固定，原“零日禁止”草稿不再保留。下表持续作为验收要求；历史v1人工及B2实际结果分别见§10/§13，C未执行；新增v2实现及人工/代码验收见§15.7，真实对照尚未执行，不引用旧通过数冒充新验收。

| 编号 | 正反样本 | 必须断言 |
|---|---|---|
| R4-01 | §4表全部六行及底部镜像 | B优先、A备选、自身价/DIF、等号、缺A及不找第三个 |
| R4-02 | B/A均合格且A更强，B合格日期不同于价极值日 | 不按强弱排序；保留累计收盘及独立极值日期 |
| R4-03 | 当前真实色柱1根、2根，末根为同色或零；TOP当根DIF负/零/正；历史段只有1根 | 首次按逻辑段允许零，但零不凑够两根；TOP正DIF及历史不新增根数门槛不误改 |
| R4-04 | 开头零、红零红、红零绿、多个零；绿对称 | 不建伪段；非零count、零极值、真实分隔及入池时间 |
| R4-05 | DULL前DIF41，零日40；DULL前40，零日同值；零日越B且A分别合格/不合格 | 形成、保持、当根切A或取消及顺序，输入hist仍为0；切换新增覆盖依§15 |
| R4-06 | 已有顶部结构，DIF40→39.9→40.35，中间根为零；另测前DIF为0 | 最后一根相对39.9回升超过1%，相对40不足1%，必须按紧邻实际根回转；保留原0保护，不偷换两位规则 |
| R4-07 | STRUCTURE零日回转，底部当根价格分别合格/不合格 | 前者回DULL，后者STRUCTURE_DISAPPEARED并WAITING；历史关联完整，不仅因零强制消失 |
| R4-08 | WAITING零日价格未过/等于/严格低于门槛，原参照DIF突破，后续真绿重新合格，真红结束 | 零柱本身不结束；完整合格则当天DULL/reactivation，等于门槛仍WAITING，原DIF突破优先INVALIDATED，真实反色仍结束 |
| R4-09 | 底B(price100,DIF−10)、A(price110,DIF−20)，当前价90，先DIF−9后−12 | 首选B；−12当根换A，不产生取消或再次钝化，不提前选A、不丢后续历史关联；研究v2统一方法后仍须保持 |
| R4-10 | 连续、分批、任意日期截断，零日首次DULL/重新DULL/STRUCTURE/WAITING恢复；跨组、身份正确但Wave/参照含NaN或无穷、DULL或STRUCTURE缺参照、日期/关联错误；正常状态副本 | 无未来信息、结果不共享、合法恢复一致；坏来件在替换前拒绝，原对象/来件/已返回结果不变；失败后再恢复合法件仍能成功，不补猜参照 |
| R4-11 | 手写两侧账本：相同、标签相同但参照B/A不同、日期不同、历史关联不同、B或A未检查 | §6.2字段齐全；逐项列出各自参照和条件，未检查为null不冒充失败；比较结果独立可核，不因ID不同误报，不丢关系 |
| R4-12 | 两组共用单根检查：布尔数字、completed=1/字符串、None/字符串数值、非法时间类型、非有限值；日期重复/逆序/未完成/错误时区及超限；正常int/float和零指标 | 两组在修改状态前同样拒绝非法单根，失败后原状态不变且正常下一根仍能成功；原r2合法输入业务输出不变；整体规模预算归B2 |
| R4-13 | 算法不隐藏读取行情/源码或写文件，不访问网络/DB；对照v0.5登记的r2核心规则及r4批准变化审计代码/回归 | 只有获准安全检查例外，其余r2判别/Spec保持，封存原件不动；交付说明逐项列实现及测试，不新增源码SHA、AST正文相等检查或借skip冒充旧试验通过 |
| R4-14 | §5.5场景一完整独立人工序列及底部镜像；另测只有1根有色柱后连续零、开头全零、严格价/DIF相等、无历史参照、TOP当根DIF<=0 | 场景一零日更新价格到100.5175、count=2、峰DIF不变，当天仅DULL/activation且选B；反例不首次钝化，不把零计色或当反色；下一根按已有DULL而非重复activation处理 |
| R4-15 | §5.5场景二完整独立人工序列；等于价格门槛、有色根数不足、原参照突破、同根新建等待、连续零日及重新钝化前后恢复 | 日3/4 WAITING，日5仅DULL/reactivation、REACTIVATED，原参照/relatedRearmId及等待的历史/结构关联完整；不重新选峰、不加activation或同根STRUCTURE，不以此前累计最低价代替当根，不重复激活；非法状态件拒绝 |
| R4-16A（B1前） | 共用解析及现r2：Wave、池、普通参照、顶部pending、底部/等待内部的非有限值/布尔数字/缺列/错日期/错关联；DULL/STRUCTURE缺参照、NONE带活动参照、跨对象/周期/来源。正例含原始空进度、合法回退、r2独立零段、换色后历史仍在且旧参照已离池、预测clone | 赋值前拒绝坏副本，原对象/来件/已返回记录不变，随后正常输入或合法恢复仍成功；正常r2字段/编号/point/事件及连续/分批结果符合独立预期；不要求来件比目标更新或所有历史原参照仍在池。本批不创建r4对象 |
| R4-16B（B1） | r4计算器完成后复用上述共用反例，再验开头全零、段内零、零日DULL/STRUCTURE/WAITING的合法副本及r2/r4双向跨组拒绝 | 合法零日副本恢复后继续计算与连续计算符合独立预期；跨组/坏副本失败不改状态，不把r4零规则用于r2。仅在B1执行，不作为B1前验收条件 |
| R4-17（B1前） | §7.1现r2查询方法的最新复制、历史恢复、追加行情继续计算，以及坏副本不得替换缓存中的原结果 | 真实调用calculator_at和_load_series，实际执行共用restore；人工来源只替代输入读取，恢复函数和共享检查不得被mock；原进度/已返回记录不变，无真实数据读取或查询/缓存/API政策修改 |

回归只选择现r2中已核人工节点，覆盖1%、独立换色、原参照突破、底部救援/历史/等待、snapshot；不整文件触发旧冻结行情重放。恢复直接节点在主题`tests/test_xxm_calculator.py`：`test_bottom_snapshot_restore_atomic_strict_and_can_rewind`、`test_bottom_period_identity_and_step_snapshot_continuation`、`test_snapshot_clone_restore_and_failed_restore_are_isolated`、`test_rearm_restore_strict_atomic_and_original_pool_identity`、`test_rearm_period_specific_identity_restore_and_rewind`，新通用反例落`test_xxm_snapshot_validation.py`，含BOTTOM STRUCTURE缺原历史、已离段/错误route/原参照不匹配的坏副本，以及TOP STRUCTURE无活动顶部历史仍合法的正例。合法副本可由当前snapshot生产者提供，但字段和继续计算结果须有独立字面断言，不能只验证生产者与消费者互相一致。类型检查的直接消费者还包括产品日线/分钟读取与预测假设K线，应以合法输入定向测试证明未误拦，不为此扩大真实取数。封存两位的旧源码检查及专用测试不在本轮执行范围，也不修改其代码、默认收集或旧预期；不得称未执行项通过。根三份架构检查、研究不得反向被产品导入检查及文档检查必做；每组超过60秒先停查因，不安装依赖。B2真实对照另按批准区间最小核验并报告实际成本，不能引用单元测试证明软件相容。

### 7.1 B1前现r2查询调用方的定向验收

共享restore改变后，现`query_service.SeriesEntry.calculator_at`的最新复制/历史恢复，以及`IndexDetailXxmQueryService._load_series`的追加计算立即受到影响，因此R4-17属于B1前，不能等C阶段迁移r4身份才检查。新增主题`tests/test_xxm_snapshot_consumers.py`，只导入现r2查询/计算代码，使用人工可核算的日线、日期和真实SeriesEntry字段；不导入App、不连接数据库、不读冻结行情，也不通过新API或页面验收扩大范围。

| 已新增测试 | 真实调用及必须证明的结果 |
|---|---|
| `test_r2_latest_snapshot_copy_stays_independent` | 人工序列建立SeriesEntry，调用`calculator_at(len(entry.processed), check)`，实际走current.snapshot→child.restore。明确断言processed/previous、状态、原参照及已有历史/等待关联；修改返回对象再确认原entry及已返回记录未变 |
| `test_r2_history_checkpoint_restore_stays_independent` | 至少一个早于最新位置的count进入已有checkpoints恢复分支，随后补算到指定count；不能只测offset=0而实际未调用restore。核历史时点/状态/参照，不能带未来状态；返回对象不得与缓存进度或checkpoint共用可变对象 |
| `test_r2_incremental_load_uses_validated_snapshot` | 真实调用_load_series两次：先载入人工前段，再追加后续完成日线；两次使用相同对象、日线周期及来源起点。实际从旧进度snapshot→新计算器restore继续；旧entry不变，新entry只追加对应point/事件/历史/等待，字段及计数有独立预期，不重复累计旧结果 |
| `test_r2_invalid_snapshot_does_not_replace_cached_result` | 只在传给恢复的副本中构造缺参照或非有限值；实际restore应抛ValueError。查询不得把半份新entry放入缓存，原缓存内容及既有结果保持；移除错误副本后正常追加仍成功。不mock restore返回成功或吞错 |

小样本的历史恢复测试可仅在该测试内用`dataclasses.replace(BUDGET, source_batch_rows=3)`替换query_service所引用的预算对象，使5根人工输入即可覆盖count=4时先恢复第3根再补算第4根；测试结束恢复引用。此替身只缩小测试批次间隔，不修改产品runtime.py、生产1000根分批值或研究1000根上限，不代表真实规模性能验收。checkpoint由真实snapshot生产，必须独立断言其processed=3和previous为第3根，不能拿被测返回值生成expected。

_load_series测试只替代`calendar_dates/read_daily`的外部输入，返回人工开市日期及同一套XxmBar，冻结now和business_date；`expected_through/assert_continuous`、XxmCache、查询方法、snapshot/restore及共用检查均使用真实代码。fake reader要按completed参数给出人工前段，不能用不受日期约束的全量返回掩盖取值错误。这里仅证明内存输入接入后的查询恢复调用，不能声称真实数据库、路由或页面验收通过。

生产者输出可用于构造输入，但核心状态、参照、计数、事件类型及关联的预期须来自人工规则和字面断言；连续计算只作额外交叉检查。测试不重放r2/r4两组行情，不整文件运行已有冻结材料测试；与其余B1前人工测试共用单组60秒、进程256MiB限制，记录实际开销，不放宽现识别4秒/预测200ms预算。

## 8. C阶段产品影响与开工前条件

此节说明下游必须一起改，**不是本轮产品编码许可，也不是B阶段通过即自动开工**。C阶段须基于已review的r4结果，先补充具体产品改动/测试矩阵，再获准实施。不得恢复已删除的r3设计。

### 8.1 预测选择和路径

1. `forecast_entry.stable_reference_on_band`按B→A顺序证明资格；边界继续包含B和A价格/DIF、柱色及日线三位来源精度。不能按A/B强弱排序，不能拿一个价格代表不同条件。
2. `_prefix_signature`同步选择及救援顺序；遇零继续检查已有状态，不以`COLOR_OR_ZERO`无条件停止。真实反色仍按r2旧方向的取消/形成分支处理。
3. `_flat_cannot_switch`中“首次已选最强所以不会再换”的证明不适用于r4顶/底DULL。§7 R4-09底部样本及§15的04-18顶部样本都要求B失效、A合格时当根切换；未来顶底预测均须包含此路径。快路若保留须有独立成立条件及反例测试，不能为200ms忽略当根切换。
4. `forecast_joint.build_relation/close_bounds/target_lines`的1%目标允许同逻辑段零柱；`color_flip`仍严格真实反色。日线rounded3/source_options及不确定性保护保留，不能把精度不确定当真实零，或反过来。
5. `forecast_detector.clone/confirmed_options`必须克隆r4对象和r4快照，所有边界由同一r4识别器复核。既有1%目标及前缀相邻比较不改成两位，不能由旧r2验证r4结果。

### 8.2 下一根结果、方向及文案

真实零不再固定`ZERO_RESET`。已有状态按r4结果归为保持、结构形成、取消或顶/底DULL当根切A后的延续，切换不是先取消后再次钝化；无活动且完整首次资格满足的零日输出DULL/activation，原底部等待在零日重新合格则输出DULL/reactivation。后续预测集成须同步§5、§5.5及§15已确认规则和关联，不另定零日禁止策略，不仅为零另造一套标签；本轮不开发预测。

`forecast_query_service`取计算后的有效逻辑方向，不能按最后hist=0返回空方向；识别point与预测须一致。`forecast_text`和接口invalidationText删除“遇零原条件必结束”的当前含义。schema和前端adapter同步允许的结果、引用和状态；不把合法零日吞成EMPTY或精度待核。

### 8.3 身份及合同

拟版本为识别`xxm-direction-v0.1-r4`、预测`xxm-key-point-forecast-v0.3-r4`。未来产品Spec须完整登记近优先、零中性及DULL当根B→A，仍保留1%、max_refs=2、min_bars=2；hash从真实Spec生成。拟新增字段集中于Spec代码，仅内部只读，无env/DB/用户参数；消费者为识别/恢复、查询缓存、预测、后端schema、Wealth types/adapter及身份测试，同次迁移，不散落手写不同值。

同次审计并迁移`query_service.SeriesEntry/calculator_at`、识别/预测缓存键、snapshot恢复、两套schema及Wealth xxm/xxm-forecast身份；旧r2响应/快照不可被r4接受，必须从同源前段重算。这里指未来r4产品身份/规则迁移；现r2查询恢复在B1前就按§7.1验收，不能推迟。URL、请求字段、数值原值、图层布局不增加新的用户功能；前端不自行选峰或求价。r2只保留可追溯的离线基准，不新增产品双算法开关或兼容入口。

封存两位实验的旧源码SHA、AST检查和继承保持历史原样，不作为r4的新要求；共享安全修改使其拒绝新文件时如实说明，不能更新旧SHA或让封存实验悄悄继承r4后仍叫r2对照，也不作为B1开工前必须恢复的任务。C阶段真正替换产品算法前仍须核这些历史消费者及其运行方式；本轮不处理历史复现，不用skip或改旧预期冒充通过，不能据B阶段LLD宣称产品迁移已准备好。

### 8.4 产品验收要求

必须补真实识别/预测路由、共享源读取、零日有效方向、版本/缓存/恢复及四周期前端合同的验收；保护现识别4秒、预测200ms、响应大小和前端时限。旧r3新增两位求解、统一整数/编号改造不自动带入，本轮保留r2现有展示政策。若完整r4预测在原预算内不可行，先报告反例、调用量及耗时，再review设计，不能只改识别后发布或放宽预算。

## 9. 开工前文档审计记录（此前时点）

本轮只更新方案和本LLD并独立审计开工条件：R4-16拆为B1前的R4-16A和B1的R4-16B；新增现r2查询调用方的R4-17及§7.1实现/验收要求。r2规则登记、取消源码SHA保护、开发后代码审计、共用检查、零日决定、旧r3清理及封存边界保持。r4尚无代码或验证成绩。两文档的规则、批次交接、预算及产品边界须一致；文档/链接检查不能替代规则验证。

2026-10-28补齐后的独立审计已核当前calculator/spec/types、query_service/runtime/source及人工测试合同。R4-16A/16B顺序、R4-17真实恢复调用、共用检查与各自零柱规则、先检查后赋值，以及B1/B2/C边界一致；未发现阻碍B1前及B1开发的剩余缺项。此为设计开工结论，不是代码、真实来源或算法效果验收；本轮仅文档和静态核对，没有运行算法、行情对比或自动提交。

该次设计审计时B1开发尚待指令；后续已获得的B1前及B1授权见§10，B2实际计算与C产品集成仍分别另行指令。若实现与已登记r2规则或r4批准范围冲突、需要新增未明确行为，停止说明具体输入、旧行为、拟变化及影响，不临时改规则或扩大范围。

## 10. B1授权执行与验收对账（研究v1历史记录，2026-10-28）

本节记录随后已获得的B1前及B1开发授权；§9的文档审计为此前时点记录。开工前已核当前源码与AGENTS、CodeGraph影响面，按方案§10先共享检查、再独立r4。实现只使用现有环境；标准库及已安装依赖，不安装软件，不触发原研究重放。

| 硬要求 | 实现文件/函数 | 本轮证明方式 |
|---|---|---|
| 同一份单根检查、状态更新前拒错 | 产品types.py:XxmBar.validate；r2/r4 step入口 | 新test_xxm_input_validation.py人工正反例及原r2人工节点 |
| 共用副本解析、分别检查零规则、最后赋值 | 产品snapshot_validation.py、calculator.py:restore/_validate_restored_state；研究r4_reference_trial.py恢复包装 | test_xxm_snapshot_validation.py/R4-16A，B1再执行R4-16B；合法回退、错误拒绝且对象/来件不变 |
| 现查询、预测复制不受误拦 | 现query_service.py与forecast_detector.py不改 | 新test_xxm_snapshot_consumers.py按§7.1实际调用；原r2 clone人工回归 |
| 先近B后远A最多两个，零中性及已定事件顺序 | 研究r4_reference_trial.py:R4TrialSpec/R4Calculator | test_xxm_r4_reference_trial.py，按§7逐项人工断言；独立审阅对照r2登记 |
| 研究与产品身份/状态隔离，禁止项不发生 | 研究Spec、_id、snapshot/restore；无B2文件或产品入口变动 | 跨组/坏副本与无副作用测试，三份架构检查及研究依赖检查 |

共用解析返回`ParsedXxmSnapshot`九项Python属性为wave/history/state/reference/previous/pending/pending_bottom_history/pending_rearm/processed；expected_identity依次为(specHash,tsCode,period,sourceIdentity)四元组。保留原snapshot外部字段和编号，不添加配置开关。README仅追加本轮完成事实，不覆盖已有未提交研究记录。

研究限额四字段在B1只作不可变规则登记及hash输入；整体输入数量、时限和结果大小的执行检查归B2 compare_r4，不新增单根step的1000根或20秒失效政策，也不改产品预算。

B1编码的内部身份接口固定为`R4TrialSpec.research_hash`：对全部dataclass字段及`parentSpecHash=MAIN_SPEC.spec_hash`规范JSON序列化（sort_keys=True、separators=(",",":" )）后计算SHA-256；它是规则身份，不读取源码。研究事件编号取`SHA256(research_hash+"|"+父_id结果)`前24位。snapshot包装严格为researchVersion/researchHash/tsCode/period/inputIdentity/parentState六字段；parentState来自父snapshot，来源身份仍为§3的r4组合值。r4.restore在副本字段/身份全检后恢复临时candidate，再发布九项进度。此处只固定已定身份/隔离规则的编码格式，不改外部产品合同或Spec。

B1前与B1各自跑定向人工测试，单组超过60秒停止查因；两组行情对照和其完整规模预算不提前运行。恢复/最终核对开销计入原预算。根三份架构、无研究/App/QTF反向依赖、文档/差异检查及独立代码审阅完成后，把实际结果回写本节，再停止汇报。源码读取仅用于正常开发审计，不运行SHA或AST全文相等保护；不提交、推送、部署。

B1前阶段验收记录：共享实现及现r2调用方人工测试149项通过（0.36秒），其中底部结构缺原历史的四反例已证修前失败/修后拒绝，顶部历史正常退出不误拦；原r2恢复节点30项通过（0.06秒），其他已选人工规则节点32项通过（0.09秒），三份架构测试16项通过（11.26秒）。没有读取真实行情或运行两组比较；独立复核后继续B1。

### B1最终对账及停点

| 要求 | 实际实现/证据 | 结论 |
|---|---|---|
| 共用输入及恢复、安全失败保护、现查询不误拦 | 产品types.py/snapshot_validation.py/calculator.restore与hook；test_xxm_input_validation/test_xxm_snapshot_validation/test_xxm_snapshot_consumers三文件149项 | 通过；包含错误恢复不改对象/来件、合法回退、r2零段、历史参照离池和真实query恢复路径 |
| B→A/零中性/原1%与历史等待配合 | 研究r4_reference_trial.py；test_xxm_r4_reference_trial.py共110项 | 通过；含R4-01—10、12—15和16B的本批部分；两例数值场景、零日/真实翻色、救援后的A结构关联及四周期恢复有独立预期 |
| 正常r2政策及编号/历史等待保持 | 原test_xxm_calculator.py明确选出的25个人工节点，参数化62项；独立读取实现和登记规则核对 | 通过；未执行该文件的两个冻结重放节点，不用源码SHA/AST全文相等作保护 |
| 层级及禁止项 | 三份根架构测试16项、研究和三个共享生产模块的导入边界测试、导入后拒绝外部访问的单组计算测试 | 通过；未改API/页面/来源查询/旧实验或增加配置 |
| 最终合并与检查 | 四个新文件259项+既有人工62项=321 passed/0.55秒；架构16 passed/11.26秒；文档/链接/差异检查 | 各组均小于60秒；无安装、真实取数或结果落盘 |

B1前发现的底部STRUCTURE原历史关联遗漏，按先补具体文档、再修共用检查、再补反例处理：修前4个反例均DID NOT RAISE，修后全部拒绝；TOP STRUCTURE历史提前结束的正例保持。R4-09救援后结构/原参照A关联及R4-15不足两根的资格也已补直接断言，没有修改既定判别政策。

CodeGraph使用impact(XxmCalculator)核上游/调用影响，node核calculator_at/_load_series，开发后已执行sync/status；新代码及索引未完整表达的动态分派以当前源码、消费者和独立测试核验。独立复核未发现本批遗留缺项。

未验/未开发：R4-11比较器、合法双组重放、真实日线接入、双组1000根整体20秒/256MiB/16MiB验收、C的识别/预测真实路由及页面/完整性能。现产品仍r2，仅已批准的共用安全检查例外生效。独立r4只供研究计算；开发交付时未提交，随后管理员已授权提交本批并独立审计B1。本次不推送、部署或推进B2。

人工进程资源补验：四个新增文件259 passed/0.55秒，含启动的壁钟0.83秒，子进程峰值RSS 98.56MiB，小于256MiB；没有运行双组1000根或把该结果当真实产品性能验收。

## 11. 底部历史结构事件编号的修复与验收（2026-10-28）

### 11.1 原因、范围和实现顺序

提交ea90f7f2之后独立审计复现：将pendingBottomHistory.structureEventId改成任意非空文本，并按它重算历史id，旧恢复函数仅核两者相互匹配而接受。下一根结构消失会把错关联带入WAITING；此后等待恢复按正确结构编号核验，反而拒绝。§10此前“未发现遗留缺项”是当时结论，本项现明确未通过；管理员已授权修复并提交，不推进B2。

现事件生产者在`XxmCalculator.step`和`R4Calculator.step`使用`self._id(bar.time, 'STRUCTURE', -1, event_ref.start)`；底部历史在`_start_bottom_history`中保存该structureEventId及`self._id('bottom-history', structureEventId)`。结构事件编号不含route，因此dif_turn和color_flip都应符合相同公式。本轮复用这一真实生产规则，不从当前历史池重新选峰，也不要求历史原参照仍在池内。

只在现`calculator.py:XxmCalculator._validate_bottom_history_snapshot`中，已核原参照字段和时间后、最终返回临时副本前，增加：

```python
expected_structure_id = self._id(raw['confirmedAt'], 'STRUCTURE', -1, ref['startTime'])
if raw['structureEventId'] != expected_structure_id:
    raise ValueError('Invalid BOTTOM structure event identity')
```

保留现历史id检查、日期/数值检查及所有业务关系。r4没有重写此方法，父restore在临时r4对象上动态使用其_id，自动得到r4编号；禁止用XxmCalculator._id强制生成r2编号，也不新增r4专用通用检查。仍在所有检查成功后才发布九项进度；失败不改目标、来件和此前返回记录，不补写正确编号来接受坏副本。正常snapshot字段、事件生成、MAIN_SPEC、取价/选峰/1%、零柱、历史和等待行为不变。

### 11.2 独立预期与验收

| 场景 | 输入依据和必须结果 |
|---|---|
| r2/r4底部结构两个编号配套改错 | 各组独立人工序列或字面副本；改structureEventId并按已登记公式配套改历史id，修前应暴露DID NOT RAISE，修后ValueError；目标、来件和已返回记录不变，随后合法恢复及继续计算仍通过 |
| 正常dif_turn历史 | 保留原形成日期/旧谷/编号，恢复后继续触发STRUCTURE_DISAPPEARED/WAITING；事件、底部历史和等待编号按独立公式断言，生成的WAITING再次恢复通过 |
| 正常color_flip历史 | 独立人工输入确认真实翻色生成BOTTOM STRUCTURE，根末普通状态NONE；恢复历史成功并继续观察，不能要求原谷仍在最近两段池 |

测试改动限现主题两个副本/r4测试文件；分别用独立编号公式断言，不调用被测验证函数或r2输出生成r4预期。四个B1人工文件及原r2相关人工节点回归，现查询恢复和预测clone测试继续执行；根三份架构、文档和差异检查保持。禁止整文件运行带冻结输入的旧计算测试，不真实读数、不双组重放、不增加API/页面/配置或源码SHA检查。

读写、失败、中断及预算沿§5.4和方案§11：纯内存，多一次固定字段编号计算，恢复/继续/最终对账计入原预算，单组测试超过60秒先停查因，不安装依赖。完成后记录修前/修后证据、实际回归和独立复核，再仅提交修复相关文件；不推送、部署或开始B2。

### 11.3 实际结果与停点

- 先补文档及15个独立人工测试；其中10个配套错编号反例在旧实现均DID NOT RAISE（r2两条形成路径2项，r4两条路径×四周期8项），证明测试确实命中原漏洞。
- 共同底部历史检查新增上述3行后，四个B1人工文件274 passed/0.59秒，包含全部新反例和正常恢复/等待继续正例；既有r2的25个人工节点参数化62 passed/0.12秒。没有整文件触发旧冻结输入测试。
- 根三份架构16 passed/11.57秒，文档完整性及差异检查通过，各组均小于60秒。CodeGraph核共同恢复、r4继承、现查询与预测复制的影响面；独立复核实现与样本通过，未发现本次修复遗留问题。
- r2/r4通过同一方法核各自结构身份，拒绝发生在赋值前；正常dif_turn/color_flip、原参照已离池和结构消失后WAITING恢复均有直接断言。未改step、编号生成、MAIN_SPEC、研究规则、查询或预测。

修复及针对性验收完成，准备按管理员授权仅提交五个修复相关文件。此结论不代表真实行情效果、双组比较或产品整链预算已验证；不推进B2/C，不推送、部署或保存计算结果。

## 12. B2比较器约定（研究v1已实施，v2观察扩展见§15）

### 12.1 实现位置与依赖

`xxm/r4_comparison.py`提供`compare_r4(bars, *, period, source_identity, start_date, end_date, deadline, source_metadata=None)`及`format_report(result)`；source_metadata仅允许已验证来源的说明/请求日、应完成日/尾部截止原因，空时如实注明调用方仅提供float，无源码摘要。其`R4ComparisonResult`为顶层metadata/rows/differences/idPairs/summary五字段的内存字典类型。`r4_observation.py`提供分别继承真实r2/r4的研究观察类；`r4_comparison_records.py`负责已给记录的关联验证、唯一配对、规范化比较和范围统计。纯模块只依赖标准库、现r2计算类型及研究r4，不导入App、数据库、封存两位或独立日线计算。三个主题测试文件分别检观察、记录、双组编排；没有新产品开关、reader、CLI、落盘或恢复机制。

### 12.2 只读观察必须保留什么

观察类的step调用真实父step一次；选择方法包装在调用前复制wave/history、记录调用背景（activation、bottom_rescue；研究v2另有top_rescue），原方法原样执行一次并返回原对象。记录条件时只根据这次实际输入、返回值及已核父方法的短路次序生成检查事实，不另选参照或修改父状态。实际未调用选择函数，则本根候选检查标checked=false、pricePassed/difPassed=null，注明已有参照/未达首次入口/等待阻断等；没有A不造A。调用过时先记最近B价格门槛，未过则各候选完整资格未检查；通过后r2按实际DIF排序、r4按B→A记录，选中后其余不检查，价格未过时DIF条件亦未检查（null）。v1已覆盖底部无事件救援；v2按§15补顶DULL当根切换观察，不能只按events推断调用。

最近B价格门槛未过时，原r2已在排序前返回；两组均按自然近B→远A列未检查项，不得事后替r2排序再当作实际顺序差异。只有门槛通过，才记录r2真正执行的DIF排序。人工反例须有两候选DIF强弱次序与远近不同、门槛失败，证明不会仅因未检查项的排列制造假差异。

decision具体字段固定为before（state/reference/wave/previous/pendingRearm）、rawSign、wave（根末逻辑段及count，r2原计数含义/r4有色计数含义另说明）、referenceChecks、selectedReference、turn、branch、reason。selectedReference为根末实际活动参照，包含reference/startedAt/action/rearmId；无活动则null。action为activation/rescue/reactivation/retained，开始日期在真实选择/救援/重新激活时更新，沿用不变。真实翻色事件仍在events保留eventReference，旧段/旧参照同时留before；不能因根末参照清空就抹去事件判断依据。turn记录实际上一根DIF/当前DIF/1%门槛/原参照突破及是否实际进入相邻转折分支；已发生取消、翻色、等待阻断或首次激活则不假报转折检查。无事件和未能确定的原因须直说保持/未到该分支/未知，不编决策。

### 12.3 编号关联和比较

先在全部计算前缀内建立两组各自记录索引，记录每个ID的类型和首次出现日期。任何点/事件/历史/等待引用须存在、类型正确且不早于记录首次出现；同一ID跨类型冲突拒绝，同一历史多次更新保留原编号。STRUCTURE事件与历史的互相关联以事件中relatedTopHistoryId/relatedBottomHistoryId及底部structureEventId核对。

跨组事件唯一条件为同日、direction/type/route及原参照startTime/endTime、实际来源色段；结构相关事件的源段用before或wave按事件方向/翻色路径确定。只有两侧各一条才配对，ID不同本身忽略。历史对应必须从已唯一对应的原STRUCTURE事件建立：顶部由STRUCTURE.relatedTopHistoryId，底部由structureEventId；等待对应必须从原结构对应及disappearedAt/segmentStart建立。撤销/重新激活/消失事件还须核其历史或等待所属关系，不得通过较晚撤销把原本不同的结构强行对应。多候选或缺失保留单侧ID及原因，不跨日期配成提前/推后。

比较时仅将ID及关联替换为已建立的同业务记录标识，原rows中的ID不改。未配对记录保持两侧独立，不通过删关联消除差异。逐根分别比较point/events/histories/bottomHistories/rearmRecords及decision中的实际wave/检查/选中参照/转折/分支；规则身份、count含义的描述文字不作为永久差异。referenceChecks顺序改变或标签相同但实际参照不同也报告。差异列time/field/r2/r4/两侧decision/effect/reason/previousDifferenceAt；分普通状态、事件、参照/依据、历史/等待统计。进入本根前已有业务状态差异时可注明此前首次差异的影响；只有本日实际选峰顺序或真实零处理不同且直接影响字段时注明本日规则，不能确定则unknown，不声称可靠解释全部变化。

rows保留从输入首根至end_date的全部计算前缀；differences和summary仅筛start_date至end_date（含端点），metadata/summary另存prefixFirstDifference和firstDifference，idPairs保留前缀关联。summary分别记录两组事件类型数量、不同日期去重数量、各类差异和实际日期列表，输入/计算/报告根数分开。开始日前结构在区间内结束时引用仍有效；截止日以后的根不参与计算、配对或归因。报告只描述相对r2差异，不比较原软件优劣。

format_report返回终端文字，除汇总外，按每个实际差异时点列两组普通状态/事件、实际参照的区间/收盘极值/DIF、真实候选检查顺序及未检查标识、实际相邻转折条件和不同字段；首条归因保留此前/当根/未知说明。不把253个“任意字段不同的日期”说成253天标签不同；原rows/differences的完整数值和关联仍保留内存，格式化不更改结果或另取数据。

### 12.4 输入、预算与失败

输入必须是同一不可变tuple[XxmBar,...]，1至1000根；每根调用共享validate(period)，先验日期时间升序唯一及day/m60/m90/m120，再截到end_date。start/end必须规范上海自然日且start<=end；开始日可晚于输入首日，只筛报告。source_identity非空字符串；两组各自新对象，统一真实MAIN_SPEC/r4研究Spec、同输入身份；禁止拿已有状态接算。比较前、中、后检查真实规则/来源身份与组内引用。

deadline为有限monotonic时刻，实际截止为min(调用方deadline,本入口开始+20秒)。首次校验、每根两组计算前后、索引配对/逐根比较及最终JSON编码后都检查同一截止与进程RSS<=256MiB；最终严格JSON字节<=16MiB，非有限值/坏关联/超限统一失败，不返回部分结果，不重试/写文件。source_metadata也不能带非有限值或不可编码对象。无磁盘续跑；中断释放内存，下次从头，清理和最终验收纳入总预算。

### 12.5 实际来源装配及首次执行

纯比较器只接收内存输入；本次通过已有一次性装配复用`src/app/dependencies/daily_wave.py:DailyWaveReadSession`、`DailyWaveBudget`及`DailyWaveQuery.load_main_window/load_calendar`（旧LLD v0.6 §0.6.9有同类执行先例）。不新增reader/CLI、不改App/产品实现、不调用旧比较器/两位reader/build_review，不在纯比较模块导入App。

读取前冻结上海执行时刻与请求截止日，日线当日15点前截至前一自然日，15点后可包括当日；SSE逐日历核出应完成交易日。限定000001.SH、2023-01-03至上述日期，六列含ts_code及trade_date、四个已有bfq指标/收盘列，读取1001根探测1000限制；日历仅SSE、同自然日期范围，2001探测2000限制。字段DATE/Float(53)按现ORM和返回合同检查，日期文本仅输出isoformat，四值保留原float，不重算MACD或造更精细原文。日历每自然日连续、exchange固定、is_open严格bool；行情对象固定、升序唯一、首日必须2023-01-03，逐日对应开市日。内部缺口拒绝；尾部尚未更新可截至实际最新已有日执行，metadata同时报告请求截止/应完成/来源实际日期和滞后原因，不假称最新输入齐备。仅一次有界读取，不全历史扫描/外部Tushare/正式写入。

读取与比较共用调用方20秒deadline。只读连接沿现DailyWaveBudget的8秒上限及2秒连接/3秒SQL/1秒锁/0.5秒清理，不放宽；同一REPEATABLE READ事务启动即只读，无池，连接关闭后再比较。一次性装配的投影数量来自研究1000上限，日历2000及读取保护沿已有Spec，不新增env、配置或用户参数。记录字段映射、实际行数/首末/有限性/日历完整性、源尾部说明、结果编码字节及完整耗时；不得输出连接配置或秘密。

实际装配复用normalize_source_row、validate_calendar检查既有DATE/Float(53)及完整日历合同，另保留此前来源核验的`abs(macd_bfq - 2*(macd_dif_bfq - macd_dea_bfq)) <= DEFAULT_SPEC.source_equation_tolerance`（现0.0021），仅核源列相互一致，禁止改写柱值或重新计算EMA。该容差沿既有来源Spec，不作为r2/r4判别容差或新配置；纯比较器仍只按共享XxmBar校验，不假装独立知道数据库合同。

### 12.6 本批验收顺序与停点

1. 手写记录验证同结果、编号不同但业务相同、参照不同、多候选、悬挂/未来关联、历史与等待关系及跨start筛选；不从被测函数生成expected。
2. 人工观察验证原r2/r4方法被照常调用、无选择时null、r2实际DIF排序/r4B→A、无事件救援、真实翻色根末清参照及等待重新使用原参照。与直接计算的交叉核对只作附加证据，关键预期仍为字面。
3. 双组编排验证相同输入、四周期与单次仅一种周期、日期截断、状态隔离、身份/非法输入、超限/超时/无副作用；独立1000根样本实测总耗时、进程RSS及结果字节。根三份架构、B1及r2相关人工回归保持，不整文件触发旧冻结重放。
4. 独立复核通过后执行§12.5的真实日线比较，所有读取/执行受统一预算；输出差异报告及限制。超过预算或发现需改已定算法时停止说明，不临时调整规则。

文档先于本步代码/执行；各测试组60秒，使用现有依赖，不安装。仅在dev-interface当前工作区保留其他修改；B2完成后将实际结果回填方案/LLD/README并停下，不自动产品集成、提交、推送或部署。


## 13. B2研究v1实现与验收对账（历史记录，2026-10-28）

| 要求 | 实现与验收 | 结果/边界 |
|---|---|---|
| 真实方法只调用一次，记录实际参照检查 | r4_observation.py两个观察类；test_xxm_r4_observation.py 22项，含r2排序/r4近优先、未查null、无事件救援、等待和真实翻色 | 通过；不替换父结果，不改r2/r4规则 |
| 组内引用、唯一跨组对应、保留前缀 | r4_comparison_records.py:compare_records；test_xxm_r4_records.py 25项独立手写记录 | 通过；历史从原结构配，等待从原结构/消失日期配；不跨日期强配或从后来撤销绑定不同原结构 |
| 同源双组编排、四周期与日期、隔离、失败预算 | r4_comparison.py:compare_r4；test_xxm_r4_comparison.py 27项 | 通过；默认无reader/CLI，全部计算前缀保留，开始日只筛报告，截止后不计算；输出/身份/资源最后检查 |
| 1000根及正常/错误资源 | 独立1000根无历史红段人工样本，两个对象均字面NONE/无事件；1001根拒绝 | 约0.09485秒，峰54,476,800字节，结果2,291,050字节；为规模样本，不声称最坏行情或产品整链 |
| 原规则与依赖保护 | B1四文件274项+B2三文件74项最终348 passed/0.74秒；原r2已选人工节点62 passed/0.12秒；根三份架构16 passed/11.65秒 | 无真实旧冻结重放；生产计算器、MAIN_SPEC、r4规则及查询/预测无diff；没有产品反向依赖研究 |
| 实际来源和完整比较 | 依§12.5既有只读装配，一次读取922根及1395日日历；同一不可变输入交两组，从2023-01-03空状态到2026-10-27 | 请求截至28日，28日未收盘；actualThrough=expectedThrough=27日，内部无缺日；源H关系最大误差0.002<=0.0021，无补值/重算 |
| 实际预算 | 读/核约0.39677秒；计算/比较/编码读数约0.248秒；完整到最终检查0.76903秒 | 最终进程峰146,456,576字节、内存结果6,494,929字节，均低于既定上限；连接已关闭，未导出/落盘 |

独立审计抓到两处报告缺陷并修复后才读取真实输入：gate失败时原r2排序未发生，未检查候选按自然B→A；同日多分钟差异只计一个自然日。原错误均有修前失败证据，最终独立定向5项复核通过。最后补齐format_report逐差异时点的状态、事件、参照、实际检查与原因展示，以及metadata.leftContextNote首段可能截断说明，人工回归通过；这些展示补充没有改变真实对照计算或触发第二次读库，真实字节/成本为此前一次运行的实际记录。

真实结果摘要：两组DULL30/31、STRUCTURE17/17、CANCEL12/13、历史价格撤销7/7；253个日期有至少一种字段差异，首次2023-04-14。普通状态只在2023-04-18不同；活动参照25天不同、事件字段15天不同、历史/等待24处字段不同。检查过程或参照变化不能冒充当日标签变化。具体初始案例及原参照价/DIF见方案§13，不重写一份不同的报告。

本批交付的是独立研究比较器及一次当前来源验收；r4有效性/原软件匹配未作结论，现页面r2不替换。无新配置、source reader、CLI、API、导出或结果保存，未恢复封存模块、未安装。CodeGraph核既有计算/读取/调用链，开发后sync/status完成；未索引的新研究文件同时以当前源码/依赖及人工测试检查，不把索引状态当算法证明。文档/链接/差异核对完成后停在B2；交付时修改未提交，随后管理员已授权提交。C、推送与部署均未推进。


## 14. 提交后的典型标签提取（2026-10-28）

先提交§12—13已验的B2实现和文稿；随后依据方案§14，复用原装配和compare_r4在原922根范围内复算并提取候选，参数固定start_date=2023-01-03、end_date=2026-10-27，日线周期day、000001.SH，同源六列及SSE日历。采用同一外层20秒deadline及既有8秒读保护，完整性、H关系和内存/结果限额沿§12.5，失败停止，不重试或保存结果。不引入新的比较逻辑、API、reader、CLI、配置或源码SHA；现r2/r4规则保持。

按result.rows真实日期与differences中events字段提取，不按253个任意字段差异直接罗列。保留每组事件的type/direction/route/eventReference和普通状态；历史撤销要对应原结构，不能称为普通CANCEL。跨组事件类型/日期相同但参照不同，仅说明标签本身不能区分，需要对应视频连线/原话；同日仅ID身份不同不作候选。合并连续相邻的同一原因展示时，原每个日期与事件不得丢失，不把无事件写成无钝化状态。按日期升序报告，并明确优先核对的少量案例；不在未看视频时决定r4优劣或更改算法。

## 15. 已DULL的近参照失效时，当根完成B→A（实现及人工审计已完成）

### 15.1 依据、范围与当前实现差距

管理员2026-10-28提供2023-04-18/04-19日线截图并确认连续钝化、没有消失，随后明确要求切换必须在近参照失效当天完成。对应方案§15；这是本轮已确认的研究规则，不冒称截图唯一证明作者内部选峰方式。

已提交研究v1的`r4_reference_trial.py:step`在更新段极值后只调用`_rescue_bottom_dull_reference`；TOP的B被突破后直接CANCEL，该根不会再进入activation，下一根才检查A。`r4_observation.py`也只包装底部救援，无事件时默认解释为沿用。后续必须同时修这两处，不能只改最终显示。

上一轮仅落文档；本轮已获§15.6的开发与人工验收授权，不读取真实行情或运行真实重放。开发范围：研究`r4_reference_trial.py`的Spec、step、换参照方法；`r4_observation.py`；必要的`r4_comparison.py`文字展示及`r4_comparison_records.py`原因说明；对应三个B2主题测试和`test_xxm_r4_reference_trial.py`。比较器顶层五字段及产品合同不变；r2计算/观察、MAIN_SPEC、共享恢复/输入校验、封存模块、读取SQL、API、预测和页面不改。

### 15.2 触发与选择的代码要求

研究类用`_rescue_dull_reference(bar, old_wave, old_state)->None`替换原底部专用方法；只在`step`原取消之前的位置调用一次，不留研究旧方法转发或先调用父step再删事件。r2原底部方法继续存在于产品父类，r4不再调用它；底部既有合法路径须经回归证明行为保持。

进入条件全部满足才尝试选择：

1. `step`尚无普通事件、未被等待阻断、未发生本根重新激活；`old_state == self.state == 'DULL'`，`self.wave is old_wave`，reference非空，pending_rearm为空。
2. `s=wave.sign`为±1，`raw_sign in (0,s)`。即仍在同一逻辑段，零允许；真实反色不进入。进入本根前是STRUCTURE或NONE均不进入，不在首次DULL当根再调用。
3. `pool=list(reversed(self.history[s]))[:2]`，按时间为B、A。活动reference须与B的`reference()`四字段完全相同；A必须存在。原参照已为A时不回B、不找第三个；缺A交原取消流程。
4. 当前段累计DIF严格突破B：`s * (wave.dif - ref.dif) > 0`。相等保持B，不触发选择。这里不是相邻DIF，不用两位、四舍五入或1%决定是否突破。
5. 调用现`_select_eligible_reference(wave, self.history[s])`一次，保持§4最近价格门槛及每个候选严格价/DIF条件。B已被突破必不合格；只有返回A才能切换。A价格/DIF相等均不合格，不降低为“仅DIF未超过A”。
6. 返回A则`self.reference=deepcopy(A)`，state保持DULL；返回None则保留原B，让后面的原取消分支处理，不在此生成事件或伪造参照。

本根顺序明确为：更新累计极值→原等待处理→上述DULL切换检查→以切换后的有效reference检查突破→原相邻1%→无活动时首次入口→历史更新→返回。取消与首次入口继续互斥；失败时不能以当根再activation掩盖取消。

切换成功本身不产生CANCEL/DULL/STRUCTURE，不生成标签编号；完成后仍执行同一根原有1%检查，不人为跳过。若原规则确实触发结构，使用A生成这一条STRUCTURE及新历史；否则无新普通事件、根末DULL。真实翻色、进入本根前STRUCTURE的取消/回转、底部WAITING重激活及历史退出继续原顺序，不借本次改成全状态换峰。

旧DULL事件及其eventReference仍记录当初B，不倒改日期/编号/已返回对象；已有历史的originalReference、冻结价格和退出规则同样不改。切换后新形成结构使用A，二者不能混用。A后续被突破时按原规则取消，不继续找更远；A当根不合格、后来才合格时保留先取消后新DULL，不能回头抹事件。

### 15.3 研究身份、快照与观察交接

- 按§3把研究版本升为`xxm-research-r4-v2`，增加固定`active_reference_policy='same_bar_near_to_far_on_dull_break'`，完整规则进入既有hash。它是不可变内部规则登记，不是用户开关；默认、来源、消费者和边界仅在§3统一定义。不修改父MAIN_SPEC，不新增配置文件/env/数据库项。
- 原snapshot包装六字段及Wave不增字段，仍由研究版本/hash隔离。v2拒绝v1副本，不迁移或沿旧进度继续；拒绝必须保持目标、来件和既有结果不变。v2在切换前后恢复再继续，与完整连续计算一致；A是现池内完整旧段，使用原共用检查，不为切换放宽恢复条件。v1源码可从Git追溯，不新建旧版兼容类或双产品实现。
- 观察器的r2包装保持原`_rescue_bottom_dull_reference`。`ObservedR4Calculator`包装新的`_rescue_dull_reference`，按wave.sign记录`top_rescue`或`bottom_rescue`；实际helper和选择函数各至多调用一次，不能为收集原因再次计算。复用共同记录逻辑时也须隔离两组，不让一次未执行的底部包装覆盖顶部切换事实。
- `decision.before.reference`记录进入本根前B；`referenceChecks`按实际B/A顺序记录门槛和原值；`selectedReference.reference`为当根使用的A，`action='rescue'`，`startedAt`为切换日期，原等待关联按既有语义为空。`startedAt`是本参照开始使用日，不是原钝化发生日；04-14 DULL事件仍留在04-14。
- 现观察内部`afterRescue`须保存换参照后的wave/reference，`turn.referenceBroken/checked`按A及真实分支填写；B已突破的事实保留在before和referenceChecks/reason，不用B给A的取消/转折做说明。切换无普通事件时，branch记`reference_switch`、reason明确“B已突破，A价格/DIF合格，当根切换并保持钝化”；若同根另有原结构事件，branch保持事件route，reason同时说明切换及形成依据。下一根沿用A，action恢复retained，不再次报切换。
- 不新增产品事件或比较器根字段；普通标签是否变化与内部参照是否变化分别统计。报告必须展示before中的B、selectedReference中的A、日期、严格价/DIF条件及没有取消/重报的原因。记录比较、终端输出和手写预期同步接入实际切换；不能只报告“没有新事件”而漏掉换峰。跨组事件/历史配对继续§12.3，编号变化本身不算业务变化。

### 15.4 独立预期与必须覆盖的反例

以下实际数值来自§13的既有计算及本轮截图；右列为新规则应满足的预期，不是v2运行成绩。完整行情重放不能用缺失中间日期的三行替代。

| 日线日期 | 已有事实/输入 | 研究v2预期 |
|---|---|---|
| 2023-04-14 | 顶钝化首次选B，B的DIF24.935；A的DIF41.186 | 保留原DULL事件及B，不提前选A |
| 2023-04-18 | DIF26.754，累计最高收盘3393.3312；已超过B价3328.3927及A价3285.6705 | `24.935 < 26.754 < 41.186`，当根切A，根末DULL，无CANCEL或新DULL；A.startedAt为04-18 |
| 2023-04-19 | DIF27.890，原累计价格门槛仍成立 | 沿用A，DULL连续，无再次activation或重复切换 |

新增测试沿现主题文件，expected独立手写，不由r2或选择函数生成。可人工设A(price100,DIF41.186)、B(price120,DIF24.935)，先C累计价130/DIF17.649形成DULL，再在后续完成根DIF26.754换A、下一根27.890保持；该小样本仅用于人工规则验证，不声称是真实行情。

| 验收项 | 必须断言 |
|---|---|
| R4-18 顶DULL当根切换及后续 | B有效前不调用A；B失效/A全合格当天直接切A，无CANCEL/新DULL；下一根不重复；原事件及此前已返回结果不变，历史原参照/冻结价不倒改，历史状态仍按原规则更新 |
| R4-19 失败及边界 | 缺A、A价格未过/等于、A的DIF等于/被突破均照旧当根取消；B的DIF相等则保持B；不找第三个，不回B；失败后A较晚才合格，保留先取消后钝化 |
| R4-20 状态/柱色/1% | 顶底镜像和零日同段；底部R4-09行为保持；STRUCTURE/WAITING/首次当天/真实反色不误切；切换后使用A继续原1%，不改变相邻前值0保护 |
| R4-21 恢复及身份 | 切换前后v2连续/恢复一致，活动A和结构历史引用正确；拒绝旧v1/跨组/坏副本且原对象不变，随后合法恢复成功；无共享对象 |
| R4-22 观察和报告 | 实际helper/selector调用次数正确；before B/after A/action/startedAt/branch/原因齐全，turn用A；无普通事件也报告参照变化；r2观察及手写既有记录不变 |
| R4-23 回归与预算 | 原r2登记/人工测试、B1+B2必要主题、根三份架构及依赖检查；独立1000根仍在20秒/256MiB/16MiB，1001拒绝；文档及差异检查 |
| R4-24 历史原参照及正常退出 | 自然序列STRUCTURE回DULL当天，原代码已按new_top_DULL结束旧顶历史，后来切A不得恢复/倒改它。另以恢复合同允许的人工DULL+PENDING组合检边界：切A当天旧历史仍按original_reference_break结束；不把旧历史改用A，不冻结状态、不补普通CANCEL，不改此前返回值。此人工组合不是声称自然回转会保留PENDING |

### 15.5 后续顺序、读写及停点

设计确认后按§15.6的本轮授权执行：先补人工失败样本证明v1漏当根切换，再改研究Spec/helper/step，随后同步观察/报告及测试，审计r2未被改变。使用现有环境，不安装；测试各组60秒，超时查因。独立审核通过后，真实重放仍须获执行授权；复用§12.5装配一次读取原922根范围2023-01-03—2026-10-27，结果以新研究身份输出，与原v1摘要和r2对账，不假称旧v1成绩属于v2。

仍只读取既有六列和SSE有界日历，不新增reader/CLI/SQL或补算MACD；读取8秒和整体20秒/256MiB/16MiB/1000根保护不放宽，清理和最终检查计入总预算。每根至多增加一次最多两候选检查，预算由1000根测试和获准真实运行验收。失败不返回半份结果、不自动重试或保存进度，中断后从头计算；结果仅内存/终端，文稿只记录摘要。若不满足规则或预算，停止说明，不临时扩候选/降精度/抹事件。页面、预测、C、提交、推送和部署均不因本节自动启动。


### 15.6 本轮实现及独立审计顺序（2026-10-28，已执行）

1. 按§15.4人工规则在现`test_xxm_r4_reference_trial.py`补切换日、后续保持及R4-19—21/24的独立预期；先选新正例证明旧v1错误取消，再修改实现。r2原人工节点单独回归，不运行含冻结行情的整个旧测试文件。
2. 在`r4_reference_trial.py`升级不可变规则身份、替换helper及单次step调用，按§15.2精确实现；`r4_observation.py`同步真实观察，`r4_comparison.py`明确显示切换前后及原因，记录比较仅在确有缺失时调整。对应观察、比较和记录主题测试覆盖R4-22，不修改产品点或事件合同。
3. 运行相关七个B1/B2人工测试文件、原r2已选人工回归、根要求的三份架构检查；1000人工根检完整预算与1001拒绝。每组60秒，使用现有`.venv`，不安装或连接数据库。以当前生产者/类型合同造人工夹具，源预期为LLD/用户已定规则，不用待测helper或r2输出生成expected。
4. 由未承担本轮实现的审阅者，按R4-18—24核实际代码、调用方、测试反例及作用范围；重点检查取消前当根切换、只B→A、严格条件、原结构/等待不扩展、已有历史正常退出、真实观察以及r2不变。代码问题须修正并定向补验；若发现需改变已定规则则停下说明并review。
5. 更新原两文档和主题README的完成事实，注明未执行真实922根及软件新对照；保留已有其他修改，不自动提交/部署/集成。文档检查、差异和链接核验通过后向管理员汇报。

文件分工不改变§15.1批准范围、研究纯内存边界和§15.5预算。失败无部分成功，中断后重新计算，现有源码和历史账本不作为运行时保护输入；无需新增配置、接口或保存任务。

开发中对R4-24的夹具核验：现`step`的`top_new`包含DULL/dif_return，因此自然回钝化时旧顶历史先按new_top_DULL结束，不能假设仍PENDING。原测试这种假设已撤回；验收拆为自然过程和显式人工恢复组合，后者须先经实际restore合同接受，再检下一根正常退出。不改生产者、恢复检查或历史政策来迎合测试；此为修正人工场景说明，不改变已确认的当根B→A规则。


### 15.7 按LLD交付对账及独立审计结论

| 要求 | 当前实现及人工证据 | 验收边界 |
|---|---|---|
| R4-18：当根B→A、无双报 | r4_reference_trial.py:step在取消前调用_rescue_dull_reference；test_dull_switches_on_break_bar_without_cancel_or_new_activation覆盖顶底、四周期和零/有色根；后续结构使用A | 原DULL日期/编号/B不改，不提前选A，不等下一根 |
| R4-19：完整严格条件 | helper核原参照确为B/存在A/累计DIF严格突破，复用原selector一次；对应strict_price_and_dif、equal_near、missing_far、later_far_price、never_searches_third测试 | 等号不放宽、失败当根取消、较晚合格仍新DULL；不查第三个或回B |
| R4-20：状态与1% | helper限定旧/今DULL及同一Wave，step保留原1%和真实翻色分支；顶结构/翻色、原底结构及等待、前值0和零日主题测试通过 | 不把STRUCTURE/WAITING当DULL切换，不改变原纠错/翻色政策 |
| R4-21：身份与恢复 | R4TrialSpec为v2并登记active_reference_policy；研究hash/编号使用既有公式，四周期切换前后恢复及旧v1原子拒绝测试通过 | parent MAIN_SPEC和共享恢复无改动，无旧版兼容类/配置开关 |
| R4-22：真实观察及报告 | ObservedR4Calculator包装新helper，实际调用一次；afterRescue/turn用A，before留B，action=rescue/startedAt/branch=reference_switch；format_report明确列前后及原因；观察31项、比较29项、记录26项通过 | r2底部观察分支不变；无新标签仍报告内部变化，原激活事件不被强配/倒改 |
| R4-23：回归与预算 | 七个相关人工文件398项/0.80秒；原r2选定25函数参数化62项/0.13秒；三份架构16项/12.10秒；1000人工根约0.09825秒、峰66,928,640字节、结果2,291,152字节，1001拒绝 | 无真实922根、旧冻结重放或产品性能结论；各组小于60秒，未安装 |
| R4-24：历史不倒改且照常退出 | 自然dif_return按new_top_DULL结束，后续切A不重开；显式人工副本经真实restore接受，切换日旧历史按B的original_reference_break结束 | 两种样本分别标明自然/人工，不改历史/恢复政策，不修改此前返回值 |

修前证据：核心顶部切换日3个定向周期样本实际产生CANCEL，旧v1副本也未拒绝；观察新增5个样本暴露TOP误取消/BOTTOM漏记切换/失败A未记，报告样本暴露缺少前后参照。修后均通过。R4-24最初假设自然回DULL仍PENDING的错误样本已明确撤回并纠正，不能把该失败当代码缺陷或更改历史政策的理由。

未参与实现的审阅者逐读三份研究实现和四份主题测试diff，核当前产品calculator/spec/types/shared恢复无本轮diff，另运行四份主题测试244 passed/0.36秒；审计结论通过，无尚待修正的逻辑偏差。CodeGraph探索用于继承/选择/观察/比较影响，开发后sync/status完成，语义同时以当前源码和独立样本核对。文档完整性、相对链接和差异检查通过。

开发交付仅修改上述研究文件、主题README及原两文档；截至该次交付未读真实行情、未跑v2真实922根、未接入产品、未提交/推送/部署。随后管理员已授权按§16先提交再真实对照，不用原v1标签数或人工成绩替代。


## 16. 已提交研究v2的原区间重放与候选提取（2026-10-28，已授权）

1. 先按方案§16提交明确十文件范围；README仅本轮新增状态/标题和人工测试说明，旧未提交段落保留工作区。核实际提交内容，保护无关暂存项，不创建分支/worktree，不推送/部署。
2. 提交后仅读000001.SH、2023-01-03—2026-10-27。既有DailyWaveReadSession/DailyWaveBudget执行只读REPEATABLE READ、无池、连接2秒/SQL3秒/锁1秒/读取8秒/清理0.5秒；用DailyWaveQuery.load_main_window六列和load_calendar三列，查询投影上限分别沿研究1000和已有日历2000取探测行。装配只在执行层，不改App/查询实现，不调用build_review或封存reader。
3. 复用normalize_source_row、validate_calendar：源DATE/Float(53)/bool、完整六列、标的/日期升序唯一、有限性及日线完成逐项核验。日历覆盖整个1394自然日，开市日须与行情严格对应；实际行数与预期922不同或内部缺口要说明/停止，不补值。原H关系0.0021来源容差保留；原float直接构造同一不可变XxmBar元组，r2/r4各自空对象，不能从旧计算进度接算。
4. 执行层从首次读取前开始统一20秒截止并传compare_r4；资源仍256MiB/16MiB/1000根，提取与最后验收计时包含在内。失败无部分结果、不自动重试，不写行情/账本/恢复文件；只在终端展示必要结果，原两文档允许回填摘要。
5. 从真实rows/events/decision提取04-14/18/19原参照与v2实际切换，核标签连续性；记录summary、各类差异日期、两组事件数和资源。先对(type,direction)判断可见事件差异；route不同但字样相同另外解释。事件同日同字且仅eventReference不同归参照核验；无事件的B→A也只归参照变化。按日期升序输出少量有区分力的案例，不把字段差异天数说成标签差异天数，不强行制造可找视频的新标签。
6. 未参与执行者只审阅实际提取结果与排序，不重复读DB或重跑；摘要回填原方案/LLD并汇报后停下。本轮授权不包含产品替换、新规则调整、推送或部署，也不自动提交执行后新增摘要。
