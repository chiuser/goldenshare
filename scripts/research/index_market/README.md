# 指数大势研究：统一代码入口

2026-10-30修订后r4历史对比专项第一批：[专项方案](../../../docs/product/wealth-r4-historical-comparison-plan-v1.md)、[专项LLD](../../../docs/product/wealth-r4-historical-comparison-low-level-design-v1.md)。仅新增`xxm/r4_history_comparison.py`、`r4_history_worker.py`、`r4_history_records.py`及三个对应人工测试文件；历史r2/历史r4只从固定Git对象进入短期进程内存，现有正式r4识别、预测、API及页面不改。真实函数`run_historical_comparison`会读取数据库，第二批获准前不得调用；没有新CLI或自动执行入口。行情、源码、完整账本不落盘。

本批安全测试命令（仅人工源、小字面计算及922根合成规模，不读取真实行情）：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider scripts/research/index_market/tests/test_xxm_r4_history_comparison.py scripts/research/index_market/tests/test_xxm_r4_history_worker.py scripts/research/index_market/tests/test_xxm_r4_history_records.py
```

本批状态及独立审计证据在专项LLD执行记录；真实922根旧基准复现及三组差异报告留第二批。下列旧r2/r4研究成绩按当时记录保留，不作为当前正式r4或本专项的新验收结果。

2026-10-28当前r4研究v2：[方案§15](../../../docs/product/xxm-r4-implementation-plan-v0.1.md)、[LLD§15](../../../wealth/docs/pages/index-detail/index-detail-xxm-r4-low-level-design-v0.1.md)。近B失效而远A价格/DIF全合格时，当根切A延续钝化，不新增消失或再次钝化；仅已有DULL同段，原1%/结构/等待/真实翻色规则不扩大。实现、人工验收及独立代码审计已完成；相关七文件398项、原r2人工62项、架构16项通过。旧v1副本不接受；无新产品开关、读取入口或结果落盘。开发交付时真实922根v2对照尚未运行，页面继续r2；随后管理员已授权按方案/LLD§16先提交本轮再重跑，结果待执行。

2026-10-28此前B2（研究v1历史）：[r4方案§12—13](../../../docs/product/xxm-r4-implementation-plan-v0.1.md)、[r4 LLD§12—13](../../../wealth/docs/pages/index-detail/index-detail-xxm-r4-low-level-design-v0.1.md)。独立比较器r4_comparison.py及只读观察/记录比较已完成，B2人工74项通过，实际922根2023-01-03—2026-10-27同源日线比较完成；28日未收盘未补入。253个日期有某类字段差异，普通状态只有1天不同，不能当253天标签变化。完整实际成本与限制见原方案，现产品继续r2。无新reader/CLI或落盘结果，不自动进入C。B1及修复已提交ea90f7f2/faaaa6b5，管理员已授权提交本次B2，随后按方案/LLD§14提取视频核对候选。

当前r4研究人工测试（无真实读取）：`.venv/bin/python -B -m pytest -q -p no:cacheprovider scripts/research/index_market/tests/test_xxm_r4_observation.py scripts/research/index_market/tests/test_xxm_r4_records.py scripts/research/index_market/tests/test_xxm_r4_comparison.py`。这条命令只用人工输入；真实比较依LLD的一次性只读装配，不调用旧两位入口或读取旧标签。

2026-10-28此前B1开发：[r4方案](../../../docs/product/xxm-r4-implementation-plan-v0.1.md)、[r4 LLD](../../../wealth/docs/pages/index-detail/index-detail-xxm-r4-low-level-design-v0.1.md)。B1前共享安全检查及B1独立r4计算已实现并完成定向人工验收。研究计算先近B后远A、最多两个，真实反色、零柱中性，保留1%及原历史/等待政策；现产品仍r2，仅共用输入/内存副本安全检查收紧，页面和预测未替换。停在B1，不运行双组对照或恢复封存实验。

本轮新增[独立计算器](xxm/r4_reference_trial.py)及四个主题人工测试文件：test_xxm_input_validation.py、test_xxm_snapshot_validation.py、test_xxm_snapshot_consumers.py、test_xxm_r4_reference_trial.py；没有新CLI或compare_r4入口。共用恢复位于产品snapshot_validation.py与calculator.restore，正常字段/编号和各自零柱规则保持，错误副本在赋值前拒绝。

当前可运行的限定人工验收（259项，无来源读取）：

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider scripts/research/index_market/tests/test_xxm_input_validation.py scripts/research/index_market/tests/test_xxm_snapshot_validation.py scripts/research/index_market/tests/test_xxm_snapshot_consumers.py scripts/research/index_market/tests/test_xxm_r4_reference_trial.py
```

本轮另显式选择原r2人工节点62项，与新测试合并321 passed/0.55秒；三份架构检查16 passed/11.26秒。没有整文件执行旧冻结重放。R4-16A及现查询R4-17已在B1前验，R4-16B在B1验，具体实现与独立证据见LLD§10。不能把这些人工成绩当作真实行情/原软件相容性通过。

下一步B2比较器、同源真实日线及完整双组规模预算尚未执行；须在本批review后按后续指令推进。C的产品/缓存/预测/页面迁移仍后置。旧r3产品正文已删除；下列旧徐小明首批和运行命令只保留历史，封存两位与独立日线模块不恢复。两位旧来源/源码校验和历史报告保持原样，本轮没有重跑或修改。

2026-10-26当前：[两位确认开发范围及结果](../../../docs/product/xxm-next-implementation-plan-v0.6.md#xxm-confirmation-development-result)、[LLD实现与限定验收](../../../wealth/docs/pages/index-detail/index-detail-xxm-next-implementation-low-level-design-v0.6.md#xxm-confirmation-development-acceptance)。`xxm/confirmation_only_trial.py`、`xxm/confirmation_comparison.py`及两个对应主题测试已完成。当前仅开发及限定测试通过，停在启动r2对比之前；r2源码/Spec/产品保持原样。两位人工70项、输入/日期/手写记录比较及帮助/非法参数117项、原r2人工回归116项、架构16项均通过，尚未执行任何双组行情重放或实际差异报告。

本轮帮助入口：`.venv/bin/python -B -m scripts.research.index_market.xxm.confirmation_comparison --help`。合法日期入口已实现，仅有`--start-date`/`--end-date`，默认2023-10-24至2026-10-13；正常运行会读取固定本地日线并启动双组重放，必须等管理员后续指令，本轮不运行。没有原视频/软件观察、页面、API、导出或结果落盘。合法入口集成、912根真实材料、双组1000根/完整20秒性能及实际差异解释仍未执行，不据限定测试声称完整实验通过。下文原首批1、2、9和旧运行命令仅保留此前历史，不由本次恢复执行。

限定测试：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider scripts/research/index_market/tests/test_xxm_confirmation_only_trial.py scripts/research/index_market/tests/test_xxm_confirmation_comparison.py`。预期为独立人工值；比较测试阻止两个计算器/重放函数启动，不以替身执行完整入口冒充对比验收。

2026-10-25第一阶段第一批：原始峰谷扫描器由`xxm/local_extrema.py`原样迁至`src/biz/services/wealth/market/index_detail_daily_wave/local_extrema.py`，迁移前后SHA256均为`ed1d71519ed3bd8f0e4ca3d6abccdec7b3c6878ec97bdd1b5ffd7b9253602c7c`。研究调用方与新生成Notebook统一引用新位置；原研究命令及算法不变，不留旧路径转发。历史报告、已存Notebook及其中源码SHA保持原样；当前批次仅作隔离迁移测试，不重跑历史研究。

2026-10-24再次审计：[研究冻结与接续](../../../docs/product/xxm-research-handoff-20261024.md)保存首批开发前315文件、全部任务编号、最新两案的条件与限制，以及后续研究顺序；旧件不删。[首批LLD审计](../../../reports/xxm_first_batch_lld_audit_20261024_01/README.md)发现预测分片保留、同route两种柱色、闭端点显示、逐案输入清单和工作量准备共五项需补。原方案/LLD本轮未改，尚不据此进入编码；没有运行新算法或正式数据验证。以下为此前进展。

2026-10-24当前：管理员选定首批1、2、9项，详见[原方案§11全部任务/§12首批](../../../docs/product/xxm-next-implementation-plan-v0.6.md#xxm-first-batch-plan)及[原LLD§13](../../../wealth/docs/pages/index-detail/index-detail-xxm-next-implementation-low-level-design-v0.6.md#xxm-first-batch-lld)。本轮仅文档；首批只改两位形成/未换色纠错、取消独立换色确认及必要预测/身份/接口集成，3—8及研究继续保留。换色有/无转折、零值、预测分段与三位来源、版本/缓存/恢复和验收已写定；首批未开发、未跑新算法验证，不能复用此前102项宣称完成。v0.5仍描述当前产品r2。

2026-10-24此前：[同根钝化内部事件与显示核验](../../../reports/xxm_same_bar_dull_review_20261024_01/README.md)。纯计算入口`xxm.same_bar_dull_review.advance_bottom/display_events`；只到首次结构，拒绝继续补猜结构纠错。12月16日11:00近谷结束、远谷新钝化同根，内部事件保留而不多画绿黄；7月日线13黄15绿17黄20绿也相容。两案条件初始化，不称完整算法；三张90分钟末根收盘显示相同，DIF差异仍在。45项新测试加原57项，共102项通过；没有产品变更。设计与结果为下一阶段方案§10/§10.1、LLD§12/§12.1；来源和实际调用范围见报告，不调用旧全CSV入口重跑。

2026-10-24此前：[19日后续结构及旧谷范围核算](../../../reports/xxm_december_structure_review_20261024_01/README.md)。沿用同套DIF延长到19日135根，前126根完全一致；若16日固定远谷，17日14:00首次两位上转，18日11:00才翻红。16/19旧谷范围变化与讲稿相容，软件精确时点、内部换谷及文字保留仍未证实，19日截图指标与源值仍有差异。只复用现有函数，未新增算法入口或改产品；57项原隔离测试复验通过。执行前设计为下一阶段方案§9/LLD§11，实际结果§9.1/§11.1；[结构级别原话另存](../../../reports/xxm_structure_strength_lesson_20261024_01/README.md)，不进入识别条件。以下为此前研究记录。

2026-10-23当前：[12月15—16日条件选峰与固定参照诊断](../../../reports/xxm_december_reference_review_20261023_01/README.md)。入口`.venv/bin/python -B -m scripts.research.index_market.xxm.reference_window_review --help`，源与日期固定在下一阶段方案§8/LLD§10；只读126根同源窗口，不重算指标。57项隔离测试通过，但12/5近谷仍优先、16日上午仍突破，尚未解释软件文字差异。完整新生命周期、产品集成未实现。以下按日期保留旧研究，不用旧两峰/合并试验覆盖当前规则。

2026-10-21接续：[04批次条件回放及合并对照](../../../reports/xxm_near_first_review_20261021_04/README.md)。管理员已确认DIF最高及补图；near_first_review.py在212根上新增全部同色多于2峰取DIF极值的宽松对照，原始输出保留，不检查起伏幅度，不输出完整技术事件。候选32→16对，仍3对超过反向上限；85项隔离/直接回归通过。最高不再待确认，原02未合并结果保留；原方案§12.93.2—3/LLD§71.5—6。

2026-10-21最新：[先近后远有界回放](../../../reports/xxm_near_first_review_20261021_02/README.md)。新入口near_first_review.py只回放12个既存参考点并检查212根柱形/反向峰数，最多两参考、每根重检；最高峰合并待定义，未生成完整结构事件。81项隔离/直接局部回归通过，旧结果保持；方案§12.93/LLD§71。复现入口：`.venv/bin/python -B -m scripts.research.index_market.xxm.near_first_review --output reports/xxm_near_first_review_<新批次>`，拒绝覆盖，不读取全历史或正式数据。

2026-10-21局部找峰：[试验结果](../../../reports/xxm_local_extrema_trial_20261021_01/README.md)，研究§8.151。新入口`.venv/bin/python -B -m scripts.research.index_market.xxm.local_extrema_study --help`；完整图片试验用已有桌面Python（报告给完整命令，含Pillow），输出必须新`reports/xxm_local_extrema_trial_<批次>`。52测试/3,280组数学定义、198根/402前缀/4字面峰通过；三像素口径均对应三圈且蓝>红>橙，只证明形状，不称原始数值或全峰序复现。全部额外峰保留，下一核原值/两位DIF及对应价格，不先加过滤。三个模块local_extrema.py/local_extrema_study.py/peak_image_measurement.py只供离线研究；两个新主题测试，无产品/A/B/C/API变化，312保护/旧结果保持，旧125未重跑。算法§12.92/LLD§70。

2026-10-21基础找峰候选：研究§8.150。盘口柱从变长转为变短记录局部峰，同色回收后再次放大也保留；平台合并、发生/确认时间分开，实时尾部只作候选。先不加过滤参数，拟核全部候选与三圈及额外峰，再核对应价格。仅方案，无新入口、原图自动识别、数值模型/测试或产品变化；算法§12.91/LLD§69，暂不索图。

2026-10-21比较位置澄清：研究§8.149.1。当前没有反例证明同色柱内已辨认的两次下跌不能分别供后续比较，先保留并在允许近/隔范围逐对判断，不另加未经证实的资格门槛。下一缺口是自动辨认下跌边界及取对应价格/柱峰；不是先证明这些位置是否能参与。仅原文档澄清，无新报告/入口/模型/测试或产品变化；算法§12.90.1/LLD§68.1。

2026-10-21三峰确认：[管理员圈图及解释修正](../../../reports/xxm_peak_annotation_confirmation_20261021_01/README.md)，研究§8.149。蓝橙两个旧位置可在同段绿柱内，但当前与近/隔峰之间有红柱；不把旧峰彼此未换色误作比较两端未换色。位置请求结束，修正三峰必须各属独立色段的概括，不把本例直接迁为DIF规则。下一先核价格波段怎样取峰，近对不成立仍检查隔峰。无新入口/模型/算术/测试或产品变化，301保护及旧结果保持；算法§12.90/LLD§68。

2026-10-21盘口课两图：[原图及比较位置](../../../reports/xxm_peak_comparison_images_20261021_01/README.md)，研究§8.148。原两屏已齐；第一图支持“只能隔一个”并提醒无异色分隔仍单峰，第二图三个比较位置待核。若位置正确，近对是价更低但绿柱更长而不背离；隔峰旧柱被手绘遮挡，远对仍引原话。只核已有第二图位置，不索新图/DIF，问后停止；293保护/旧结果保持，无新入口、模型/算术/测试或产品变化。算法§12.89/LLD§67。

2026-10-21盘口两课：[比较范围和隔峰实例](../../../reports/xxm_peak_comparison_lessons_20261021_01/README.md)，研究§8.147。可隔一个但只能隔一个、近峰不成立仍可用隔峰给范围新依据；盘口与DIF共享原理但数值不互换，形态/级别/是否报点分开。现待第一课36:31—36:50和第二课23:25—23:57两屏，提出后停止；284保护/旧四周期/52及13保持，无新入口/模型/测试或产品变化。算法§12.88/LLD§66。

2026-10-21新课：[结构对应关系原稿与三图](../../../reports/xxm_structure_correspondence_lesson_20261021_01/README.md)，研究§8.146。上升大顶→半周期底、下降大底→半周期顶、震荡同周期；环境定义/90对应未给，不能拿半周期解释DIF选峰或旧峰期限。三图为教学示意，不作软件金样本；无新运行入口/模型或测试、产品不改，暂不索材。算法§12.87/LLD§65，前两项学习成果仍见研究§8.145。

2026-10-21学习成果整理：统一摘要见[研究主文档§8.145](../../../docs/product/xxm-macd-structure-research-v1.md)。两项成果为钝化/结构/纠错关系和DIF保留前两位的比较方式，核心标准有原课及截图支持；选峰等边界继续待资料。管理员本轮只要求整理，不接续下方待开发事项，无新运行入口/候选/模型或测试执行；产品、材料及旧成绩保持。算法§12.86/LLD§64。

2026-10-21课程两图：[DIF截取两位的数值模型](../../../reports/xxm_two_digit_dif_images_20261021_01/README.md)。-8.086按8.0/80讲支持截取而非四舍五入，40.057对应40、前根41.xxx未知；原截图请求结束。19字面例/4反例说明与固定1%不等价，但既存十根/20次近远峰比较保持，6月选峰仍未解。261保护/四周期sealed/52及13保持，无新入口/检测器/125测试重跑或产品变更；下一准备DIF比较落点设计，暂不需材料。算法§12.85/LLD§63。

2026-10-21系统课建模：[两段课程、判别模型与取数缺口](../../../reports/xxm_quantitative_structure_lesson_20261021_01/README.md)。异色一根分隔/新同色至少两根、DIF转折可在换色前确认及前后不同纠错已有课程支持；DIF左起非零两位的具体取法待图，不能直接等同当前1%。仅待第二课2015/3/11的13:18—13:28和21:10—21:30截图；不再核第一课确认含义。无新运行入口/计算器/模型或125测试重跑，252保护/四周期sealed及原52/13保持；算法§12.84/12.84.1、LLD§62/62.1。

2026-10-21原词确认：[6/24两处均为隔峰](../../../reports/xxm_jun24_gefeng_confirmation_20261021_01/README.md)。120/90当天已允许隔峰比较，不能只由6/25越近峰后的换峰或后来结构回转解释；A合看6/25图稿更相容，精确首次软件参照/资格/排序仍未知。245保护/四周期sealed及原52/13保持，仅投影十根旧窗口，无新模型/测试/产品变化，原词问题结束；算法§12.83/LLD§61。

2026-10-21补6/25 120原图：[DIFF与旧段资格/原词核对](../../../reports/xxm_jun25_m120_image_evidence_20261021_01/README.md)。读值12.048/4.513/15.069与本地差<0.001，末端黄及5月手绘峰支持远峰参与，完整软件输入/初始唯一选择未证。6月近14根、8月远12根使单一最少根数无法同时排前留后；不新造过滤器。回查6/24原稿15:09—15:35“格峰/隔风”原词未核，只请该时间段核听后停止；不再索6/25图/DIFF。237保护/四sealed保持，无模型或测试重跑、原52/13/产品不变，算法§12.82/LLD§60。

2026-10-21收到6/25 120字序答复：[左绿右黄与限定解释](../../../reports/xxm_jun25_m120_confirmation_20261021_01/README.md)。问题结束，DIFF未知不重复索；三组都有本地先旧绿后新黄，故本条并不唯一判A，也不认左绿为25日新钝化取消。结合约26口述A更相容，C仍不足，初始峰/旧段资格未证。231保护/四sealed保持，只核六行旧窗口，无模型或测试新跑/产品变化，原52/13保持；算法§12.81/LLD§59。

2026-10-21结构回转重选三组：[完整结果与6月待核画面](../../../reports/xxm_top_return_reference_20261021_01/README.md)。当前命令`.venv/bin/python -B -m scripts.research.index_market.xxm.top_return_reference --output reports/xxm_top_return_reference_<新批次>`，测试`tests/test_xxm_top_return_reference.py`，仅新目录/失败保留。原110+15共125通过，40,478行/214保护、A/B旧sealed及分段/底部/C恢复保持。C解释8月下午取消，但6/25 m120仍提前取消、6/26上午重黄；原52 A52/B49/C51，13旧范围相容，不改预期。当前仅待核6/25视频07:05—09:59的120右端最新黄/绿及可读DIFF，问后停止等答；已有90图/全文不重索。算法§12.80/LLD§58，产品未迁。

2026-10-21收到8/7图稿并核价格：[新材料、旧价格与DIF峰对照](../../../reports/xxm_aug07_price_reference_evidence_20261021_01/README.md)。无新维护入口或模型执行；8/7请求结束，稿只确认120新钝化，未给初始参照/消失价。两旧段14行重算显示价格高低与DIF高低排序相反，8/7—15复用14行持续过两旧价，不能用后来价格达标解释假定换峰。8/15原稿“重新钝化”使结构回到钝化是否重选成为下一待验解释，尚未开发/计算。199保护/4完成marker保持，不重跑110/40,478或改原52/13；当前算法§12.79/LLD§57。本轮先不继续索仅有黄色的普通图，其他价格定义仍未知。

2026-10-21完整参照次序比较：[两组完整过程与旧8月证据](../../../reports/xxm_top_reference_priority_20261021_02/README.md)。入口`.venv/bin/python -B -m scripts.research.index_market.xxm.top_reference_priority --output reports/xxm_top_reference_priority_<新批次>`，仅新目录，失败保留后新批次重算；测试`tests/test_xxm_top_reference_priority.py`。110测试、40,478行、180保护保持；强组原sealed相等，近组原52为49（1 direct/2 mapped不符），原13按旧范围均相容。6/25 m90虽可先近后远，但8/15门槛与8/18末根绿限制必须取消后才换的具体方案；未取消前换/资格仍未知，产品不改。下一只缺8/7当日120讲稿初始旧峰/消失价，不重索8/18或6/25；当前算法§12.78/LLD§56。

2026-10-21收到6/25图稿：[原图、全文及选峰边界](../../../reports/xxm_jun25_reference_evidence_20261021_01/README.md)。无新维护入口/模型执行/产品变化；90明确收盘钝化，120口述旧峰26支持远峰方向，仍未排除先近后远；日线23不搬作90峰确认，24不加固定失效。169旧保护、9行旧投影/已存三组事件/独立算术保持，原52/13不改、101测试未重跑。6/25请求结束，不重问模糊字位，当前算法§12.77/LLD§55。

2026-10-21近期取材调整：[近期日期与已有图交叉核查](../../../reports/xxm_recent_reference_crosscheck_20261021_01/README.md)。无新维护入口、算法或产品变更；固定40,478行三组账本对上次sealed一致，156旧保护保持，101旧工程测试无改未重跑。2017/2015资料不可得不再索，优先2025/6/25上证90分钟图/稿，用近期长段及后续先越近峰核参照，120同视频可顺带核；备选2026/1/27 m60仅核当根价条件。4/18旧图和2/25跨周期相容有帮助但不新增独立验证，当前算法§12.76/LLD§54。

2026-10-21首次TOP选峰顺序：[2/25新反例与三组结果](../../../reports/xxm_top_current_close_selection_20261021_01/README.md)。旧候选先选远峰再拒绝而当天无黄，新候选先按当根价格逐个筛资格后选强峰，解释近期峰方向；只作研究，软件首字/精确身份未证。入口`.venv/bin/python -B -m scripts.research.index_market.xxm.top_current_close_selection --output reports/xxm_top_current_close_selection_<新批次>`，仅新目录、失败保留后新批次重算；测试`tests/test_xxm_top_current_close_selection.py`。原52保持、后来13项相容、101工程测试/139保护保持；旧候选代码/结果保留，产品未迁。方案§12.75/LLD§53；下一有区分力材料2017/3/28上证90分钟，暂无则未知。

2026-10-21 120画面紫字已确认：[字样、真实收盘与边界](../../../reports/xxm_may9_m120_time_price_audit_20261021_01/screen_confirmation_20261021/README.md)。紫色“结构形成”与本地结构方向相容，本例不再作已确认无结构反例，不重复问同屏；最终固定状态与1%未独立验收。125旧保护、产品/候选不变；当前算法§12.74/LLD§52。

2026-10-21 120分钟时点/价格核查：[固定条件区间与待核画面](../../../reports/xxm_may9_m120_time_price_audit_20261021_01/README.md)。无新入口或模型执行，固定1%算术可有90成立120未成立的价位区间；3356.95时本地两者都成立，不能用0.72价差直接结案。已请核原视频03:33的120文字与价格，软件最终状态未知；117保护/产品/候选保持，算法§12.73/LLD§51。

2026-10-20新增5/10及120闪烁核听：[补图及撤回范围](../../../reports/xxm_top_current_close_20261020_01/may10_and_flash_clarification_20261020/README.md)。5/10日线未见新紫，与5/9无黄一并支持首次价格候选；120讲解当时尚无结构，撤回此前收盘已确认说法，最终时点保留未知/本地待核差异。109旧保护、产品/候选保持，无新模型执行；当前算法§12.72/LLD§50。

2026-10-20新增5/9日线证据：[图稿核对及限制](../../../reports/xxm_top_current_close_20261020_01/may9_evidence_20261020/README.md)。管理员确认此图没有新钝化，与原样候选相容，5/10未证；90分钟14/15结构讲解与既有结果相容，120“闪烁”时点待核。只读13行及已存结果，原96保护/产品保持，不重跑模型；当前接续方案§12.71/LLD§49。

2026-10-20首次顶部当根价格候选：[完整结果与反证日期](../../../reports/xxm_top_current_close_20261020_01/README.md)。仅离线研究，产品保持。入口`.venv/bin/python -m scripts.research.index_market.xxm.top_current_close --output reports/xxm_top_current_close_<新批次>`，要求新目录，失败保留后新建批次重算；测试`tests/test_xxm_top_current_close.py`。原始起点40478条、原52观察保持，120分钟目标差异相容，尚不认定软件原公式；下一资料为2023/5/9—10上证日线新钝化/结构有无。方案§12.70/LLD§48为当前口径。

2026-10-19徐小明线程交接：[当前进度和接手步骤](../../../docs/product/xxm-research-handoff-20261019.md)。4/18上证日线已收到并保存，尚待核对；下方“需4/17图/停在取证处”是材料到达前状态，不重复请求同图。当前只整理交接，没有新内核改动或新图通过结论。

2026-10-19新钝化接替旧结构：[阶段结果和最小找图请求](../../../reports/xxm_history_replacement_screen_20261019_01/README.md)。只读四周期冻结结果、固定普通事件作后续价格对照，不改产品；入口`.venv/bin/python -B -m scripts.research.index_market.xxm.history_replacement_screen --output reports/xxm_history_replacement_screen_<新批次>`，测试`tests/test_xxm_history_replacement_screen.py`。完整事件与原r2一致；现需2023/4/17上证日线，研究停在取证处，未证软件通用接替规则。下方旧找图建议按当时材料状态保留。

2026-10-19历史结构消失找图：[候选日期和研究结果](../../../reports/xxm_history_disappearance_screen_20261019_01/README.md)。仅当前r2及封存输入的事件核对，不访问正式源或修改产品；运行`.venv/bin/python -B -m scripts.research.index_market.xxm.history_disappearance_screen --output reports/xxm_history_disappearance_screen_<新批次>`。同身份已有目录只读完成单元后继续，身份或完成文件变化拒绝。隔离测试为`tests/test_xxm_history_disappearance_screen.py`；新图尚未取得，不称软件验证通过。

2026-10-19当前徐小明验收：**唯一产品已升级r2，当前结果见[交付报告](../../../reports/xxm_top_activation_r2_implementation_20261019/README.md)。沿用`xxm.reference_rescue_acceptance`／共用`bottom_history_acceptance`入口；frozen读取开发前117文件及获准18项更正，不能再用旧a1／r1预期验收新版。下方a1、R1运行成绩与命令按其日期保留为历史。原研究候选和旧`xxm.acceptance`／`same_segment_acceptance`不作为r2成功验收入口，不应重跑覆盖旧报告。**

```sh
.venv/bin/python -B -m scripts.research.index_market.xxm.reference_rescue_acceptance --mode frozen --source reports/xxm_source_audit_20261013_213852 --output reports/xxm_r2_frozen_NEW
.venv/bin/python -B -m scripts.research.index_market.xxm.reference_rescue_acceptance --mode api --source reports/xxm_source_audit_20261013_213852 --output reports/xxm_r2_api_NEW
.venv/bin/python -B -m scripts.research.index_market.xxm.daily_window_precheck --source reports/xxm_reference_rescue_r1_implementation_20261017/daily_2020_source_01 --output reports/xxm_r2_day_2020_NEW
```

这些模式仅读现有封存源／日历和隔离SQLite，拒绝覆盖输出；日线源的旧采集身份只在原SHA／文件／范围全部校验后复用，当前计算身份仍r2。完成单元分别保存及核SHA，内部读回拒绝不同代码／来源／预期；CLI仍不接受已存在的目录，不新增resume参数。正式`--mode budget|replay-budget --formal-source`、显式分钟periods和page audit参数未变，但仍须按原方案完成本次正式只读验收授权／范围核对；本轮未执行。page audit核双Spec并运行实际TS adapter，不能用本地夹具成绩充当正式页面成绩。

目录整理日期：2026-09-09。规则见[研究目录 AGENTS](/Users/congming/github/goldenshare/scripts/research/AGENTS.md)。这里是离线研究，不接入产品或生产运行时。

2026-10-16徐小明同段循环：用户确认LLD §21后，已按[实施报告](../../../reports/xxm_same_segment_a1_implementation_20261016/README.md)迁入唯一a1内核。原[条件分流研究](../../../reports/xxm_same_segment_precheck_20261016_04/README.md)和[失败报告](../../../reports/xxm_same_segment_precheck_20261016_02/README.md)保留；临时候选、动态源码注入及旧runner已清退，原文与依赖SHA封存在实施报告ZIP中。当前入口只运行产品类并读取冻结输出对账，不导入历史候选；四周期、范围、全部校验及预算保持。

## 目录

2026-10-16钝化取消后重启研究：[报告](../../../reports/xxm_cancellation_restart_20261016_01/README.md)。仅复放MAIN_SPEC及已冻结M0源，不访问DB／Lake、不改产品。运行：`.venv/bin/python -B -m scripts.research.index_market.xxm.cancellation_restart_audit --output reports/xxm_cancellation_restart_20261016_01/run_<新批次>`；父目录须已存在，输出目录拒绝覆盖。隔离测试：`scripts/research/index_market/tests/test_xxm_cancellation_restart_audit.py`。

同项[时序与用价续查](../../../reports/xxm_cancellation_restart_20261016_02/README.md)：`.venv/bin/python -B -m scripts.research.index_market.xxm.cancellation_restart_detail --output reports/xxm_cancellation_restart_20261016_02/run_<新批次>`。沿用第一轮run_03病例／保护SHA，只回溯资格时点、不跑第二套事件引擎；旧12/16的90分钟补图请求保持暂停。新增隔离测试`tests/test_xxm_cancellation_restart_detail.py`。

后续用户已给[12/16的90分钟原图](../../../reports/xxm_software_case_20251216_m90_20261016/README.md)，确认四条文字；与当前六步模型链尚未逐柱对齐，更新原方案§12.16，不计作重选规则验证通过。本次只新增观察报告，未加候选或修改研究runner。

同项[重入资格诊断](../../../reports/xxm_rearm_discrimination_20261016_01/README.md)：`.venv/bin/python -B -m scripts.research.index_market.xxm.rearm_discrimination --output reports/xxm_rearm_discrimination_20261016_01/run_<新批次>`。只读冻结源并核对a1事件；区分当根DIF与累计段底，记录价格／DIF余量，不实现候选状态机或调参。run_01及run_02的定义差异保留，测试`tests/test_xxm_rearm_discrimination.py`；H2b仍待软件证据，不可迁入产品。

2026-10-17[12/15收盘新图](../../../reports/xxm_software_case_20251215_m90_20261016/README.md)已确认当天有消失后重新钝化，H2b作为本例必要条件撤下，停止补同图／稿。当前原图入账与12354根前缀核查只更新观察；后续单独研究16日参照切换与取消顺序，未新增候选运行器或改产品。上一段的run记录保留历史定义。

同日完成[R1参照切换隔离研究（历史）](../../../reports/xxm_reference_rescue_20261017_01/README.md)及[预测预检](../../../reports/xxm_reference_rescue_forecast_precheck_20261017_01/run_02/summary.json)，随后获准迁入唯一产品类。旧研究原件已封存在[基线档案](../../../reports/xxm_reference_rescue_r1_implementation_20261017/baseline_source.zip)，不再以`reference_rescue.py`／`reference_rescue_forecast.py`运行当前产品验收；工作树原型清退待正式收尾。当前入口为`.venv/bin/python -B -m scripts.research.index_market.xxm.reference_rescue_acceptance --mode frozen|api|budget --source reports/xxm_source_audit_20261013_213852 --output reports/<新的批次>`，budget另需`--formal-source`。三门槛1215组及45恢复通过；正式四周期因日线历史缺口暂停，未声明预算／整页／页面通过，见[当前开发态报告](../../../reports/xxm_reference_rescue_r1_implementation_20261017/README.md)。

```text
index_market/
  statistics/                 四轮统计研究及来源校验
  chan/                       缠论教学、M0事件账本与独立复核
  tests/                      本主题全部隔离测试
  migration_20260909.json      旧/新路径、代码哈希与历史结果清单
  README.md                   当前运行方法
```

主方案、教材留在 `docs/product/`，历史输出留在 `reports/`；这里不复制报告和数据，也不另建产品配置。

## 当前研究状态

2026-10-13 徐小明方向识别：[研究主文档](../../../docs/product/xxm-macd-structure-research-v1.md)当前进展为 §8.49。用户已批准 [V0.1 算法方案](../../../docs/product/xxm-direction-algorithm-plan-v0.1.md)、Figma、完整历史扫描调整及仅指数详情页的响应式修正；上证日线和 60／90／120 分钟开发态已实现并完成技术验收，等用户验收，未部署。内核在 biz；本目录只放冻结来源加载与验收入口，生产模块不依赖旧报告脚本。旧 3161 根分钟在三组门槛下回归通过，新完整源共 39747 根，2615 次事件／生命周期前缀重放及已有 26＋1 个读数对账见[实施报告](../../../reports/xxm_implementation_20261013/README.md)。未确认的软件公式、数值偏差与长历史寿命保留；原报告和失败版本不改写。

2026-10-15 近期关键条件展示：规则与参数统一见[预测方案§18](../../../wealth/docs/pages/index-detail/index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#18-近期关键条件的简明展示2026-10-15)，当前证据见[实施报告](../../../reports/xxm_forecast_display_implementation_20261015/README.md)。四周期只读HTTP预算入口：`.venv/bin/python -m scripts.research.index_market.xxm_forecast_display_audit --output reports/xxm_display_audit_NEW`；product模式使用正常产品代码，每次拒绝覆盖输出目录。`--candidate <本机文件>`仅用于已授权的候选预检，不被产品导入；读取正常只读DB／正式Gold并使用临时端口，无应用后台任务、页面自动化或正式数据写入。语义测试位于`tests/test_xxm_forecast_display.py`；用户自行页面验收，评分后置。

2026-09-14 P0市值来源追加核验：[方案34.12](../../../docs/product/stock-chan-share-position-backtest-plan-v1.md#3412-p0追加历史市值来源已找到停牌口径待确认2026-09-14)。Tushare基准日市值覆盖4276/4279股，另外3股均有全天停牌证据，未排除或填充。未入旧案例名单的4037股中4034股当日有市值；12层容量示意最小107股，但尚未冻结层边界或抽样。新reports仅一份查询证据JSON；复算：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_market_cap_source_audit reports/stock_market_cap_source_20260914/evidence.json`，纯离线，不访问API/Lake。市值补充来源、停牌取值规则及扩大样本复核定位待确认，仍不进入P1；下文34.10的DG缺口为当轮历史事实，本轮未补写DG或计算新收益。本轮变更未提交。

2026-09-14提交与清理：用户已批准本研究代码/文档和有用reports一并提交。第28—34节七组正式证据保留，共29文件约12.0MiB；下文“仅本地/暂不提交”为各轮当时状态，已由本次要求替代。源码缺失预检`stock_signal_chain_audit_20260913`的3文件已执行移入废纸篓，受系统读取限制未验证恢复；其30次机会/6笔案例由最终serial报告覆盖，旧阻塞经过仍见方案28.9。删除清单、保留理由和恢复位置见[方案34.11](../../../docs/product/stock-chan-share-position-backtest-plan-v1.md#3411-本研究提交与报告清理2026-09-14)。旧Store/历史归档与七组正式报告字节未改；P0门禁不变，未进入新回测。

2026-09-14 P0完成、停止于设计门禁：原股数方案34.10，本地`reports/stock_expansion_p0_20260914/report.md`（暂不提交）。58次B3回踩低点与旧冻结低位全部相同，不再重复跑收益。现存快照中4279只符合五年前上市的沪深存续口径，其中4037只未进入旧案例/对照名单，但4279只均参加过早期全市场排名，不能称完全未使用的数据；历史个股市值缺失，12层抽样无法执行。60日成交额缺行290股日均由全日停牌解释，未知缺行0；年度分钟文件仅000670.SZ缺2021年两频度文件，原因未核实，其余仅证明文件存在。2.897秒、四文件约197KiB、655项主题测试通过。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_expansion_feasibility --output reports/stock_expansion_p0_NEW`。没有抽股、读新分钟明细或计算收益；先决定市值来源与扩大样本复核定位，再讨论P1。下文34节方案制定时记录保留，最新结论以34.10为准。

2026-09-14后续计划已重整：[原股数方案第34节](../../../docs/product/stock-chan-share-position-backtest-plan-v1.md#34-后续计划重整先排除重复试验再扩大独立股票样本)为下一步执行入口，取代下文各历史轮次的“下一步建议”。原10股及其他已查看结果的股票只作开发/案例集；建议另取分层240股，开发/封存验证各120股，但尚未抽样或运行。当前代码已在第22节实现冻结买点低位退出，须先核对与第33节回踩低点的差异，不能改名再试；新机会池须移除共同闭合及按实际退出筛非重叠的事后选择。下一步仅P0方法去重与样本可行性，不算新收益。具体主对照、封版、相关性处理和停止条件见第34节；跨股票封存不等于未见市场时间。本轮仅更新方案及本README，代码、历史成绩与reports未改。

2026-09-14 B3来源追溯完成：原股数方案第33节，本地报告`reports/stock_b3_origin_audit_20260914/report.md`（暂不提交）。原八股133次机会中的58次B3全部唯一追溯到真实3a/3b生成中枢；55次中枢未标记确认，此标记与段状态有关，不等于假买点。3a确认价到中枢上沿/回踩低点中位距离6.21%/1.67%，3b为5.57%/2.36%；两条失效线必须分开。62.08秒、4文件约180KiB，317条原事件及8次截断/8次未来扰动一致，632项主题测试通过。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_b3_origin_audit --output reports/stock_b3_origin_NEW`。直接读取Store，不依赖未提交reports，不改算法/执行，不计算新退出收益。下一步仅建议检验固定原回踩低点失效，不同时搜索其他止损线；阶段结论及停止条件见33.5。

2026-09-13退出结构审阅完成：原股数方案第32节，本地报告`reports/stock_exit_structure_review_20260913/report.md`（暂不提交）。八股133次原对照摘要精确一致，47次收益改变对应40个不同卖点，固定6个完整案例。卖点笔均确认，但父线段25次未确认、22次尾笔尚未归入段；各类状态在改善和卖早两侧均存在，尚无可靠区分规则。317条原事件、46个当时截面、8次截断/8次未来扰动通过；26.76秒、四文件约145KiB，616项主题测试通过。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_exit_structure_review --output reports/stock_exit_structure_review_NEW`。直接从Store重建并验证第31节逐笔摘要，不依赖未提交reports；不改识别或退出规则、不读Lake。下一步仅建议先定义买入结构失效，不自动启动新策略。

2026-09-13原10股取消编号配对扩批完成：本地结果`reports/stock_any_sell_cohort_20260913/report.md`（暂不提交），原股数方案第31节。原A不变，主要观察其余八股133次：毛收益均值5.27%→5.71%，5股改善/3股下降；后期增量-0.57pp、非重叠后期-0.85pp，未过预设阶段稳定性初筛。全10股163次旧执行、374条原事件一致，20次事件截断/10次未来扰动通过；运行37.97秒，四文件约213KiB，595项主题测试通过。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_any_sell_cohort --output reports/stock_any_sell_cohort_NEW`。每股独立进程串行，直接读原Store，不依赖未提交的两股结果、不读Lake，不改旧两股入口；到此停止扩池与参数搜索，未提交。

2026-09-13取消卖点编号配对验证完成：两股结果（仅本地、暂未提交：`reports/stock_any_sell_20260913/report.md`），原股数方案第30节。保持原A完整配置和57条原事件不变；30次机会3次改善、27次不变，均值-0.49%→-0.08%，实际卖点退出1→3。全部改善来自四川美丰的B3→S2退出；濮耐股份不变，跨股票可靠性未建立。运行5.58秒、4文件约48.5KiB，571项主题测试通过。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_any_sell_study --output reports/stock_any_sell_NEW`；不读取Lake、不叠加第29节参数、不运行分仓账户。原10股同口径复核仅为下一步建议，尚未执行。

2026-09-13三卖关联单变量验证完成：两股结果（仅本地、暂未提交：`reports/stock_sell_linkage_20260913/report.md`），原股数方案第29节。只将笔级卖方`bsp3_follow_1`改为False；新增14个S3，固定30次机会只改变5次退出（3好2差），毛收益均值增量+0.14个百分点，去掉最佳增量后转负，未过扩批筛查。运行7.54秒，仅4文件约53KiB，无新行情副本；550项主题测试通过。复现：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_sell_linkage_study --output reports/stock_sell_linkage_NEW`；只读封存输入，保留原编号配对，不运行分仓账户、不读取Lake。后续取消编号配对须独立授权，不能与本轮变量叠加。

2026-09-13识别链审计完成：两股报告（仅本地、暂未提交：`reports/stock_signal_chain_audit_20260913_serial/report.md`）及六笔案例（仅本地、暂未提交：`reports/stock_signal_chain_audit_20260913_serial/cases.html`），对应单股方案28.11节。冻结源码恢复并核验64文件；30次机会、57条原事件和原执行零差异，18个截断前缀/未来扰动通过。27个无卖点窗口中，23个包含早先已入账身份，1个出现被1p/2s映射排除的确认候选，27个都观测到三卖前置一卖限制的拒绝分支；这些标签可重叠，不等于放开限制就有收益增量。最终运行约234秒、526项主题测试通过。新入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_signal_chain_audit --output reports/stock_signal_chain_audit_NEW`，只读封存输入、每股独立进程串行，不自动下载依赖。最终5文件，失败尝试并入同一证据包。此前源码缺失预检（仅本地、暂未提交：`reports/stock_signal_chain_audit_20260913/report.md`）保留历史，阻塞已解除；未运行新策略。

2026-09-13资料清理：[旧实验统一归档](../../../reports/index_market_history_20260913/README.md)。四类旧实验668份原件已封存为四个ZIP，33份原Markdown合并供阅读，教材两张图保留。旧目录移出，仅A目录保留现行source_gate仍需的manifest；下文旧实验的运行/复核命令须先按归档库存恢复完整来源链，不是当前可直接运行的入口。当前十股六轮仍直接读StockResearchStore，无解压或旧路径回退；算法及历史成绩未改。

当前十股资料已统一到[一个目录入口](../../../reports/stock_chan_research_20260912/README.md)：六轮621个散文件收敛为15个文件，人读结论/案例单列，机器证据单包去重。五个依赖入口已改为StockResearchStore直接读取；旧六目录已移入废纸篓，无旧路径回退。旧目录缺失不代表数据缺失，后续从统一入口读取，不重新复制行情。

2026-09-12卖点漏用审计：[诊断报告及六笔案例](../../../reports/stock_chan_research_20260912/sell_usage.md)。原134次到期中100次无任何账本卖点，34次其他类型被配对过滤且可执行；成交受限/记录异常0，163笔独立重建一致。只诊断，不运行任意卖点策略；优先核查无卖点识别链，尚未执行。入口`python -B -m scripts.research.index_market.chan.stock_sell_usage_audit --output reports/stock_chan_sell_usage_NEW`，只读封存资料，设计见原方案第24节。

2026-09-12退出对照最新结果：[固定买点退出报告](../../../reports/stock_chan_research_20260912/exits.md)。固定10股/60分钟，163个共同机会，对应卖点均值4.83%，固定60日4.85%；只有29笔实际卖点退出，134笔到期，未证明卖点增益。结构退出均值1.02%、平均MAE -3.25%，降低不利波动但未提高收益。470项测试通过；不是股数账户回测。设计见原股数方案第22节，复现入口为`python -B -m scripts.research.index_market.chan.stock_exit_study --output reports/stock_chan_exit_study_NEW`，只读封存输入，不访问DG。以下记录保留各轮历史口径。

2026-09-12最新：按用户纠正的**统一前复权、不额外处理分红送股**口径，已完成[蔚蓝锂芯002245.SZ五年30分钟策略回测](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_qfq_002245_30m_20260912--report-md)。主模型累计24.34%、最大回撤36.43%，同股买入持有75.12%/69.09%；6轮已完成、53笔成交、另有未平仓，五类信号检查通过。不是券商账户仿真，成本/成交假设及代码入口见主方案第14节。旧P0公司行为/原始价阻塞不再适用于这轮。

历史实现记录：[P0只读核验](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_share_002245_p0_20260912--report-md)与[P1合成金样本](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_share_p1_synthetic_20260912_verified--report-md)保留当时事实，不再作为当前前复权模型的阻塞项。B1/B2/B3买20%/30%/50%，S1/S2/S3卖50%/30%/20%，比例按固定股数基准；不使用指数窗口。原指数共振研究暂停扩批，下列旧记录和命令保留供复核，不自动启动原下一批。

2026-09-12最新：[首批等价提速](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_parallel_first10_20260912--report-md)完成：1/2/4进程125.5/66.4/39.8秒，4进程快3.15倍，231项全字段结果比较一致，五项检验全部保留。[原首批10只个股回放](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_g2b_first10_20260912--report-md)完成11席，真实暂停恢复通过；仅中国天楹有两笔提前买点。全量2189文件超过原2000上限，剩余279只未执行；约59分钟是优化前串行估算，不是当前运行状态。[首只试跑](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_g2a_replay_20260912--report-md)和[沪深未退市股票排名](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_shsz_r1_surviving_20260912--report-md)保留；三段对照50/48/50，排除已退市者及北交所，存续池有幸存者偏差。以下旧运行和清理记录是历史，不代表当前仍暂停在G1。

- [个股缠论独立方案](/Users/congming/github/goldenshare/docs/product/stock-chan-index-window-research-plan-v1.md)：沪深A股、最近五年的市场背景共振研究，不研究指数成员关系。[G1修正后报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_shsz_r1_source5_20260910--report-md)已完成8月窗口5203只排名与50对50匹配，2月/4月存在未解释数据缺口，G2未执行。用户正在处理缺数，研究暂停；本轮仅做[废弃代码与报告清理](../../../reports/research_cleanup_20260910/report.md)。
- [四轮统计研究方案及历史结论](/Users/congming/github/goldenshare/docs/product/index-next-day-probability-backtest-plan-v1.md)：代码已运行过，方法结论以原报告为准。
- [缠论教学](/Users/congming/github/goldenshare/docs/product/chan-theory-csi300-teaching-guide-v1.md)：只完成结构回放，不是盈利回测。
- [买点预判与买卖盈利实验方案](/Users/congming/github/goldenshare/docs/product/chan-signal-prediction-and-profit-experiment-plan-v1.md)：分钟基准、A、F1、S1、C1、C2及第20节B0闭环可行性检查已完成。C2未证明次日增益；B0的18个组合全部不足30笔自然退出，按停止条件收尾。不进入产品、不继续调参，正式账户回测未实施。此前[M0交付复核](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_m0_csi300_20260909--review-md)为日线历史工程记录，不代表方法有效。

## 无真实数据访问的验证

从仓库根执行，使用现有 `.venv`，不自动安装依赖：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider scripts/research/index_market/tests
.venv/bin/python -B -m scripts.research.index_market.statistics.index_probability_backtest --help
.venv/bin/python -B -m scripts.research.index_market.chan.build_cases --help
.venv/bin/python -B -m scripts.research.index_market.chan.stock_share_synthetic --help
```

根 `pyproject.toml` 的 pytest `testpaths` 已纳入本主题测试；默认发现不会因搬离根 `tests/` 而遗漏它们。

股数账户的入口只接受固定合成样本，不接受股票代码或真实行情输入；不会读Lake或产生订单。复现使用全新报告目录：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_share_synthetic --output reports/stock_share_synthetic_NEW
.venv/bin/python -B -m scripts.research.index_market.chan.stock_share_synthetic --verify reports/stock_share_synthetic_NEW
```

`--verify`除校验代码/文件哈希，还重算固定样本并逐字段比较。当前有效验收目录是`stock_share_p1_synthetic_20260912_verified`；不带`_verified`的首轮重复副本已在[中间产物清理](../../../reports/research_cleanup_20260912/report.md)中移出，CLI序列化失败原因仍保留于原方案。

## 实验入口（需要另有执行授权）

当前前复权入口固定蔚蓝锂芯30分钟、五年、A配置与股数策略，只接受新输出目录；不访问原始价格或公司行为，不写Lake：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_qfq_run --help
.venv/bin/python -B -m scripts.research.index_market.chan.stock_qfq_run --output reports/stock_qfq_002245_reproduction_NEW
```

输出全部信号、四种模型账户、年度统计、信号/账户检查和manifest。当前结果目录为`reports/stock_qfq_002245_30m_20260912`，不可覆盖。

首批等价提速测量只消费已封存的G2b输入及其暂停目录引用，不重读Lake；固定1/2/4进程，保留五项检验，不能改股票池或缠论参数。设计及预算见个股方案第13节：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_parallel --help
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_parallel --output reports/stock_chan_parallel_reproduction_NEW
```

输出逐股等价哈希回执、三组耗时和最终manifest。完整旧事件继续引用G2b报告，不复制三套相同大文件。此入口是首批性能实验，不是全量调度器；只完成本轮测量也不等于剩余279只获得执行授权。

G2b仅固定首批10只，不能通过CLI改批次或选股；恢复总是写新目录并校验前序封存结果：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_batch --output reports/stock_chan_g2b_pause_NEW --pause-after-first-unit
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_batch --output reports/stock_chan_g2b_resume_NEW --resume-from reports/stock_chan_g2b_pause_NEW
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_batch_audit --report reports/stock_chan_g2b_first10_20260912
```

个股G2a试跑及只读产物复核（参数固定、不会启动289只批量）：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_replay --output reports/stock_chan_g2a_NEW
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_replay_audit --report reports/stock_chan_g2a_replay_20260912
```

四个统计模块分别为：

```text
scripts.research.index_market.statistics.index_probability_backtest
scripts.research.index_market.statistics.index_condition_statistics
scripts.research.index_market.statistics.index_single_condition_backtest
scripts.research.index_market.statistics.index_risk_baseline_backtest
```

授权后用 `python -B -m <完整模块名> --output reports/<全新目录>`。参数、数据窗口和预算仍以原方案为准，不能因为目录整理而调参。

缠论教学脚本同样只接受新输出目录：

```bash
python3 -B -m scripts.research.index_market.chan.build_cases --chan-source /absolute/path/to/frozen/chan.py --output reports/chan_teaching_reproduction_NEW
```

实际计算/绘图需已有 DuckDB CLI、Python与Pillow及固定提交的第三方源码；`--help` 不要求这些外部计算资源。研究脚本不会下载或安装它们。教学输入窗口、结构参数和图片算法未改；原报告目录不能作为新输出。

## 本次整理与历史来源

以下为目录整理当时的记录；之后新增的M0见本页当前研究状态，不改写原迁移哈希。

- 原 `scripts/research/index_*.py` 四文件移至 `statistics/`。
- 原根 `tests/test_index_*` 中本研究的四文件移至 `tests/`，未动其他业务测试。
- 原 `reports/chan_theory_csi300_teaching_20260908/build_cases.py` 移至 `chan/`。
- 旧位置不留转发脚本、模块别名或双份实现；使用上面的新命令。
- 历史报告、数字、参数、输入清单和代码哈希保持原样。历史报告中旧命令代表当时入口，不能直接用于当前目录；以本页为当前复现入口。
- 后几轮原本要求当前依赖脚本的字节哈希等于旧报告哈希。搬目录修改了导入与路径，因此增加精确的迁移来源映射：仅登记的旧哈希、新哈希、目标路径组合被接受；任何未登记代码变化仍拒绝。新运行另保存 `prior_source_checks`，不篡改旧报告。
- `migration_20260909.json` 是一次目录迁移的证据，不是通用哈希豁免。不要为了让以后代码通过而重新生成此记录；算法改变必须按新的实验版本处理。

## 影响面与核验

整理前使用 CodeGraph explore/impact 检查研究入口、`safe_output` 调用与测试；再逐项核对内部导入、根路径计算、后续实验的哈希依赖、文档和pytest配置。图谱结果需结合当前文件判断，不代表已完成统计有效性验证。

核验包括：原62项隔离测试；新增目录、入口帮助、输出保护与来源校验测试；核心计算函数/Spec的AST迁移前后比对；历史结果逐文件哈希检查；文档检查。实际运行结果见主方案的目录整理记录。

只改变离线工具组织、当前命令及相应来源记录，无架构依赖矩阵、API、服务、DG或Lake变更。不重跑历史实验，不产生新策略成绩，不提交推送。其他主题的研究脚本保持原样。

## 个股缠论当前入口（G1已复核，G2未执行）

### 当前沪深G1排名入口

新实现为`chan/stock_chan_rank.py`，测试为`tests/test_stock_chan_rank.py`。范围和参数见独立方案；固定Gold30，源端点依据正式Silver5归并合同核对。只做排名和事前成交额匹配，不运行个股引擎。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_rank --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_rank --output reports/stock_chan_shsz_r1_reproduction_NEW
```

CLI只接受新报告目录。当前版本固定验证日2026-09-12排除已退市股，其余参数见方案；真实运行读取正式Lake，测试不读取。`blocked_data_quality`不等于程序崩溃或方法无效；`rank_complete`也不保证50个对照都齐备，应查看paired和缺席原因。禁止按结果自动删股或混源兜底，不自动进入G2。

G0废弃入口及成员/市值门禁已清理。当前排名仍需的B0认证和时间窗口选择原样保留在`chan/stock_chan_reference.py`，测试在`tests/test_stock_chan_reference.py`；读取白名单反例由现用排名连接的测试覆盖。不留旧入口转发，不修改历史manifest。

## 买卖闭环可行性B0入口（2026-09-10）

已完成，见[B0报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_roundtrip_b0_20260910--report-md)，固定设计与验收在原方案第20节。新增`chan/minute_roundtrip.py`及主题内`tests/test_chan_roundtrip.py`；复用A原始首次事件，不使用C2次日去重样本，不改旧入口或信号。只检查B1/B2/B3分别入场、首个新S1/S2/S3退出的可行性，不计算正式账户或退出对照。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_roundtrip --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_roundtrip --output reports/chan_minute_roundtrip_b0_reproduction_NEW
```

CLI只接收新输出目录。结果含六组数量表、18组完整买点处置/持仓账本、七个事前按时间选定案例、独立事件配对/SQL路径核验及来源哈希。所有组合未过样本门槛，不自动进入账户回测；不读写正式Lake/DB/DG、不联网/安装/提交/部署。

## 次日非重叠取样C2入口（2026-09-10）

已完成，见[C2报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_nonoverlap_c2_20260910--report-md)，固定设计与验收在原方案第19节。新增`chan/minute_nonoverlap.py`与`tests/test_chan_nonoverlap.py`，复用并认证C1/A保存证据和未改动的评分/验证模块。唯一变化为次日观察不重叠，不改信号、背景或统计门槛。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_nonoverlap --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_nonoverlap --output reports/chan_minute_nonoverlap_c2_reproduction_NEW
```

参数全部冻结，只接受新输出目录；旧C1的20日冷却仍保留为历史对照。输出包含原始/C1/C2统计、入选/重叠账本、身份变化、共同支持与区块缺失、年度/删除敏感性、独立SQL取样/评分核验。新结果称`nonoverlap`，不是改写旧`cooldown`；不访问正式Lake/DB/DG、第三方引擎或网络，不安装/部署/提交。

## 简单形态与三买C1对照入口（2026-09-09）

已完成，见[C1报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_comparison_c1_20260909--report-md)，固定规则与验收在原方案第18节。新增`chan/minute_comparison.py`，独立DuckDB/候选核验为`chan/verify_comparison.py`；合成测试为`tests/test_chan_comparison.py`。只读已认证A保存投影和事件，不访问正式Lake/DG或第三方引擎，不应用F1/S1，不改原冷却与评分。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_comparison --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_comparison --output reports/chan_minute_comparison_c1_reproduction_NEW
```

输出必须为新目录；不接受窗口/容差/匹配阈值调参。保存候选、全部事件、背景/标签、共同支持、区块缺失率、年度/日期敏感性、邻近配对和核验。旧A基线字段不直接拿来当新背景基线；统计问题未解决不等于工程未完成，也不授权继续自动优化。

## 上层结构S1验证入口（2026-09-09）

已完成，见[S1报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_structure_s1_20260909--report-md)，固定口径与验收在原方案第17节。`chan/minute_structure.py`使用A固定源码/配置及保存行情，重放全部事件并在B3触发时保存同频率上层结构值快照；不是跨周期过滤器，也不应用F1。测试为 `tests/test_chan_structure.py`。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_structure --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_structure --chan-source /absolute/path/to/frozen/chan.py --output reports/chan_minute_structure_s1_reproduction_NEW
```

需要既有隔离源码，拒绝版本/哈希/配置差异，不自动下载或安装。全事件必须等于A，快照端点不得超过当前柱；新目录保存事件、结构分类、前缀核验和manifest。代码不修改原回放/评分及第三方文件，不访问正式数据或服务。

## 背景过滤F1入口（2026-09-09）

已完成，见[F1报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_background_f1_20260909--report-md)，固定规则/验收在原方案第16节。`chan/minute_background.py`只在原A事件上增加“距近期高点超过2倍前20日平均TR则跳过”，不重画信号、不改变冷却次序；测试为 `tests/test_chan_background.py`。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_background --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_background --output reports/chan_minute_background_f1_reproduction_NEW
```

新目录保存全部柱背景、保留/跳过事件、原始/冷却对照、同背景基线、完整交易日区块区间和manifest。事件文件中的baseline/lift仍保留原A字段，新背景基线成绩在`metrics.json`的`modes.*.after`。只读固定研究证据，不访问正式数据或第三方引擎；CLI不开放其它阈值。

## A后续诊断入口（2026-09-09）

已完成收益集中与高位失败诊断，见[诊断报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_diagnostics_20260909--report-md)。固定方法与执行记录在原缠论实验方案第15节。新增 `chan/minute_diagnostics.py`，隔离测试 `tests/test_chan_diagnostics.py`；只消费固定A报告，不重放信号、不读湖、不挑过滤阈值。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_diagnostics --help
.venv/bin/python -B -m scripts.research.index_market.chan.minute_diagnostics --output reports/chan_minute_diagnostics_reproduction_NEW
```

输出必须为新目录。`events.json`保存四项当时可知特征及原评分，`diagnostics.json`保存六组原始/冷却统计与日期聚类，`validation.json`保存无未来输入和独立复算证据，`manifest.json`固定来源与代码；人工解读报告后追加，不重写计算manifest。诊断发现尚不构成新策略有效性证据。

## 单变量试验A入口（2026-09-09）

已完成，见[A复核报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_variant_a_20260909--review-md)和[原版/A对照](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_variant_a_20260909--comparison-md)。仅取消买入侧三买的前置关联；使用第13节保存投影及固定manifest，禁止更改时间/对象/其它参数或覆盖基准。原运行器只增加显式校验器/输入加载器注入，默认入口不变；新模块 `chan/minute_variant_a.py` 管理配置、单变量完整对账、基准重放和结果对比，测试为 `tests/test_chan_variant_a.py`。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_variant_a --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_variant_a --chan-source /absolute/path/to/frozen/chan.py --output reports/chan_minute_variant_a_reproduction_NEW
```

输出的`comparison.md`是原版与A的对照入口，`comparison_manifest.json`记录基准重放、单变量来源及新旧输入一致性；`manifest.json`仍记录核心分钟运行产物。仅研究文件读写，不重新访问DG/Lake或源API，不自动安装依赖。

## 分钟基准入口（2026-09-09）

用户已停止日线方向，改测五年30/60分钟。当前范围、初始化和评分以原方案第13节为准；分钟A预判测试已跑完，结果见[五年分钟复核报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_5y_20260909--review-md)。未完成B账户盈利测试。

代码仍在 `chan/`：`minute_data.py` 冻结配置及只读Gold输入，`minute_replay.py`逐根分钟事件，`minute_score.py`交易日标签与基线/区块统计，`run_minute.py`六组入口，`verify_minute.py`从保存变化独立重建事件。测试在 `tests/test_chan_minute.py`。日线M0源文件及历史结果不变。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.run_minute --help
.venv/bin/python -B -m scripts.research.index_market.chan.verify_minute --report reports/chan_minute_5y_20260909
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.run_minute --chan-source /absolute/path/to/frozen/chan.py --output reports/chan_minute_reproduction_NEW
```

最后一条会执行获准范围的真实只读研究；输出必须为新目录。两个线程环境变量仅限制现有数值库并行度，不是信号参数或产品配置。无需安装、启动DG或写湖。

## M0入口（日线历史，2026-09-09新增）

实现：`chan/m0_data.py`管理固定Spec和只读输入；`chan/event_ledger.py`管理首次事件及变化；`chan/run_m0.py`执行核验；`chan/verify_m0.py`用另一条第三方迭代入口对保存的结果独立复核。隔离测试为 `tests/test_chan_m0.py`，默认不依赖真实Lake或第三方源码。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.run_m0 --help
.venv/bin/python -B -m scripts.research.index_market.chan.verify_m0 --report reports/chan_m0_csi300_20260909 --chan-source /absolute/path/to/frozen/chan.py
```

重新执行M0须按获准范围使用`run_m0 --chan-source <已核对源码> --output reports/<全新目录>`；仍为固定三指数输入核验与沪深300回放，不接受日期或信号参数开关。M0不是预测评分，不能将其事件数或测试通过解释成策略有效。
# 买点机会评估补充（2026-09-12）

60分钟对照已完成：[最终审计报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_opportunity_002245_60m_20260912_audited--report-md)，原方案第17节。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_timeframe_opportunity --output reports/stock_timeframe_reproduction_NEW`。只聚合封存30分钟行情并重做60分钟信号。

DG现有90分钟已直接回放：[结果报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_opportunity_002245_90m_dg_20260912--report-md)，原方案第18节。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_dg90_opportunity --output reports/stock_dg90_reproduction_NEW`。只读六个指定年度Gold文件，不重采样，不改行情，未显示比60分钟更好的效果。

四组过滤实验已按原方案第16节完成：[过滤对照报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_opportunity_filters_002245_30m_20260912--report-md)。顺势无改善，不追高小幅表面改善但未通过非重叠稳定性检查。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_opportunity_filters --output reports/stock_opportunity_filters_reproduction_NEW`；固定配置，不覆盖历史、不读取Lake。

蔚蓝锂芯30分钟买点的5/10/20日表现与大涨区间早期覆盖见[机会报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_opportunity_002245_30m_20260912--report-md)。口径见原股数回测方案第15节，不改历史识别及账户代码。

复现：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_opportunity --output reports/stock_opportunity_reproduction_NEW`。只读已封存研究报告，拒绝覆盖输出；不读Lake，不调参。配置集中在该模块不可变OpportunitySpec，实际值保存在manifest。

固定随机10股60分钟第一轮：[报告](../../../reports/stock_chan_research_20260912/initial.md)。5股完成，5股待停牌/零成交语义核对，禁止将结果称为10股全完成。入口：`.venv/bin/python -m scripts.research.index_market.chan.stock_random10 --output reports/stock_random10_reproduction_NEW`；只读固定名单30/60分钟年度文件，规则及名单不调优。

后续已按市场日历正常处理停牌，原10股全部完成：[完整报告](../../../reports/stock_chan_research_20260912/calendar.md)。当前入口：`.venv/bin/python -m scripts.research.index_market.chan.stock_calendar_run --output reports/stock_calendar_reproduction_NEW`。不填价格、不压缩停牌日期，零成交端点不假设成交；依赖第一轮封存材料，未改旧报告。结果仍未显示稳定优势。

核心买侧参数单变量实验：[优化报告](../../../reports/stock_chan_research_20260912/parameters.md)。基线、背驰0.8、回撤0.6、MACD面积法共40单元完成，三个新参数均未过预设可靠性筛查。入口：`.venv/bin/python -m scripts.research.index_market.chan.stock_parameter_study --output reports/stock_parameter_reproduction_NEW`；只读封存材料，不读DG、不修改旧参数入口，按原方案第20节执行。

类型与确认滞后实验：[结果](../../../reports/stock_chan_research_20260912/timing.md)。全部/B1/B2/B3/滞后<=4/<=8六组未找到可靠候选；类型表现有阶段反转，简单过滤长滞后没有稳定改善。入口：`.venv/bin/python -m scripts.research.index_market.chan.stock_signal_timing --output reports/stock_timing_reproduction_NEW`，仅读封存材料，原方案第21节。


XXM 初版历史验收入口（非r2验收入口；原命令记录保留）：

```bash
.venv/bin/python -B -m scripts.research.index_market.xxm.acceptance --source reports/xxm_source_audit_20261013_213852 --research reports/xxm_macd_structure_20261011 --output reports/xxm_implementation_20261013
```

旧复算入口可能写回原报告，不应为本轮验收直接重跑。新入口会校验原 CSV／图片哈希，使用产品同一内核及来源身份，输出连续基线、软件末端读数、前缀与恢复检查和真实 API 对照。

2026-10-15 请求调度、共享加载与读取投影：唯一设计见[预测方案§20](../../../wealth/docs/pages/index-detail/index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#20-整页请求调度与共享加载2026-10-15已授权实施)，执行／历史失败见[报告](../../../reports/xxm_request_reuse_20261015/README.md)。四周期原预算沿用上述`xxm_forecast_display_audit`入口；整页混合与单／双标签页使用`.venv/bin/python -m scripts.research.index_market.xxm_page_request_audit --output <新报告目录>`，运行实际TS客户端／调度器与原只读HTTP链，不自动操作页面。完整历史、投影及配对读取对照使用`.venv/bin/python -m scripts.research.index_market.xxm_history_projection_audit --through 2026-10-14 --output <新报告目录>`；只读正式Gold、拒绝覆盖旧结果，不是产品预计算或正式数据发布。

2026-10-17 日线下载期间的R1分钟分验：当前`xxm.reference_rescue_acceptance`（或其共用入口`xxm.bottom_history_acceptance`）的`--mode budget --formal-source`以及上述page audit均支持显式`--periods m60 m90 m120`，默认仍四周期、不裁剪产品历史。`--mode replay-budget --formal-source`重验已保存的路由历史场景，沿用同样周期选择；只读原鉴权／正式来源，不冒充软件真值。严格20真冷／20真暖、13历史场景和12组混合通过，命令及全部新旧记录见[分钟验收](../../../reports/xxm_reference_rescue_r1_implementation_20261017/minutes_acceptance.md)。日线及完整四周期整页待用户通知，页面仍由用户验收。

2026-10-17 用户选择先做2020起日线隔离预检：新增`xxm.daily_window_precheck`，只在研究输入中固定2020下界，不改产品全历史读取。显式采集阶段使用只读一致快照和真实ORM字段投影；检查阶段完全本地，临时SQLite／固定采集时钟／鉴权替身，仍走原路由／唯一内核／DTO及数据保护。必须使用新目录：

```sh
.venv/bin/python -B -m scripts.research.index_market.xxm.daily_window_precheck --capture-source --output reports/xxm_daily_2020_source_NEW
.venv/bin/python -B -m scripts.research.index_market.xxm.daily_window_precheck --source reports/xxm_daily_2020_source_NEW --output reports/xxm_daily_2020_check_NEW
```

1643端点、97前缀／恢复、四截图事件及20冷暖隔离通过，保留442份校准保护；[结果与边界](../../../reports/xxm_reference_rescue_r1_implementation_20261017/daily_2020_precheck.md)。原通用预算工具另纠正日线暖核验：日线允许完整SQL投影核源，但不得内核重算；分钟暖仍不得完整读源。更早历史及全历史正式接口／四周期整页见[延期记录](../../../reports/xxm_reference_rescue_r1_implementation_20261017/before_2020_pending.md)，等用户通知后再做，隔离计时不能代替正式PG／网络／页面成绩。

2026-10-17 顶部9/24—25疑点：离线入口`.venv/bin/python -B -m scripts.research.index_market.xxm.top_daily_ambiguity --output <全新目录>`，只读本地冻结四源／旧52观察，不访问数据库、Lake或网络。五模式仅在研究子类改变参照资格，不注册产品；保留原两段池及短段占位、当前两根、排序和状态机。事前方案／LLD、四候选结果及现有材料的辨别边界见[本轮研究](../../../reports/xxm_top_daily_ambiguity_20261017_01/README.md)，没有将静态图未见文字设成软件NONE金样本，不因旧52全过就迁移产品。12字面测试为`tests/test_xxm_top_daily_ambiguity.py`。


2026-10-20旧结构有效期首阶段：只整理已有237条完成记录和两组94行有界源，不新增CLI/状态机或重跑识别。69根120分钟与23根90分钟候选及既有图片待确认处见[本步报告](../../../reports/xxm_history_lifetime_review_20261020_01/README.md)，依据原算法§12.58/LLD§36。软件通用有效期未证，当前不加期限、不改产品，也不重复索取已提供图。

同日6/12新图与全文接续见[补证报告](../../../reports/xxm_history_lifetime_review_20261020_01/jun12_followup_20261020/README.md)：当天二次结构已核，准确14/15点待现图首字确认；至6/24 11:00为条件23/22根，未登记软件有效期下限。“30周期”是钝化按速度估算，不是固定期限。仅补三行，无模型重跑或新CLI，原首阶段文件保留。

6/24全文及本例22/24计数见[讲稿核对](../../../reports/xxm_history_lifetime_review_20261020_01/jun24_transcript_20261020/README.md)。管理员已澄清24是具体行情的对应数字，撤回由本稿延伸的固定24根到期研究分支，以[更正说明](../../../reports/xxm_history_lifetime_review_20261020_01/interpretation_clarification_20261020.md)为准；无新实验或产品改动。

6/12时间经管理员重看原图后更正为14:00，与原模型一致，撤回“模型早一根”。到6/24 11为23根，不强行与讲稿22/24绑定；旧15:00答复留作历史，以[最新时间更正](../../../reports/xxm_history_lifetime_review_20261020_01/jun12_time_correction_20261020.md)为准，无重跑或参数修改。

2026-10-20新确认案例已加入现有pytest：`scripts/research/index_market/tests/test_xxm_confirmed_cases.py`，13项与原68项内核回归通过，未修改算法或旧预期。[阶段结果](../../../reports/xxm_confirmed_case_regression_20261020_01/README.md)对应算法§12.59/LLD§37；无需新CLI。

## a1内核历史验收（保留B组五处保护，非r2验收入口）

已确认规则见算法方案§12.12及识别LLD§21；当前交付见[实施报告](../../../reports/xxm_same_segment_a1_implementation_20261016/README.md)。脚本仅验证正式唯一内核，不导入历史研究候选。每次OUT必须新建，预算／对象／周期不可改成更宽门槛。

```sh
.venv/bin/python -m scripts.research.index_market.xxm.same_segment_acceptance --mode frozen --source reports/xxm_source_audit_20261013_213852 --output reports/xxm_same_segment_a1_frozen_<新批次>
.venv/bin/python -m scripts.research.index_market.xxm.same_segment_acceptance --mode api --source reports/xxm_source_audit_20261013_213852 --output reports/xxm_same_segment_a1_api_<新批次>
.venv/bin/python -m scripts.research.index_market.xxm.same_segment_acceptance --mode budget --formal-source --source reports/xxm_source_audit_20261013_213852 --output reports/xxm_same_segment_a1_budget_<新批次>
.venv/bin/python -m scripts.research.index_market.xxm_page_request_audit --output reports/xxm_same_segment_a1_page_<新批次>
```

frozen校验来源SHA与封存源码，对照完整39747根×三门槛、研究逐事件／参照账本、14次同段消失／7次重入、93条底部历史绿、45个前缀恢复和369组预测，保留五处B组软件观察。api使用隔离SQLite／冻结字段fixture，调用真实三路由／query／DTO并覆盖拒绝鉴权，不冒充正式服务。budget仅显式formal-source时通过应用正常依赖及READ ONLY事务读取白名单日历／上证因子与正式Lake；160轮预测和配对识别，另4次LATEST及四周期识别／预测两并发。mixed仍用实际TS客户端／调度器的306请求、统一业务日期及真实图表原值adapter，不操作浏览器。完整来源／原4秒／200ms及缓存预算保持；页面由用户验收，脚本不安装依赖或修改鉴权。

2026-10-18 两个深市指数的日线研究：`xxm.cross_index_daily`只读生产视图指定两代码、2020/1/1—2024/8/30六列及沪深共用SSE日历，视频候选限2022/9/13—2024/8/30。复用原三组条件，不改产品内核；读取前须按原方案§12.33／LLD§25.14完成有界只读审计。使用新目录，只有同设置、代码、文件校验一致的已完成文件才可继续：

```bash
.venv/bin/python -B -m scripts.research.index_market.xxm.cross_index_daily --output reports/xxm_cross_index_daily_NEW
.venv/bin/python -B -m scripts.research.index_market.xxm.cross_index_daily --output reports/xxm_cross_index_daily_NEW --resume
```

输入与分类隔离测试为`tests/test_xxm_cross_index_daily.py`。本次真实采集、比较及无区分日期的结果见[研究报告](../../../reports/xxm_cross_index_daily_20261018_01/README.md)。未验证原软件的新指数标签，不以程序一致性证明公式正确。

2026-10-20已完成[本地实际页面阶段验收](../../../reports/xxm_page_acceptance_20261020_01/README.md)：四周期/三历史案例/局部重试通过，提示遮挡已修复，完整1191项前端测试与类型/构建通过；算法不变，未部署。当前取证下一步只需[2026/1/6上证120分钟图](../../../reports/xxm_history_lifetime_review_20261020_01/m120_next_case_20261020/README.md)，用于核模型69根旧结构；不是软件已验证寿命公式。文首4/18等待属于原交接状态。

2026-10-20最新图文取证见[2/21三周期材料](../../../reports/xxm_feb21_three_period_evidence_20261020_01/README.md)：120当天消失且仅一根红柱未新钝化，60/90已有钝化；次日正常走的预计不作次日软件确认。旧峰比较原词待核听，不据3/1缺字反推2/22从未出黄。此前1/6分钟图管理员未找到，不重复索取，69根案例仍未证。当前算法§12.65/LLD§43/研究§8.123及交接文首接续此前等待状态；只整理原件和已有输出，内核/参数不变。

2026-10-20原词已确认邻峰、画图指1/30附近，红角线就是红柱线；[参照补充](../../../reports/xxm_feb21_three_period_evidence_20261020_01/neighbor_confirmation_20261020/README.md)接续上一段待核。2/21参照与1/30本地值相容，次日模型新120钝化另用2/1—2/2，需核中间正柱/分段和选峰；尚非3/1差异根因已定。27行/35保护保持，无新模型或产品变更；当前算法§12.66/LLD§44/研究§8.124。

2026-10-20 [120分钟逐项核查](../../../reports/xxm_m120_reference_trace_20261020_01/README.md)已解释1/30段在2/16下午退出、2/22为何从两合格段选DIF更高的2/1—2/2；旧结构仍沿用保存参照，并非同次钝化改峰。72行/36开市日/43保护保持，无新模型或产品变化。现有120图2/1上午短负柱的辨认仍待管理员答复；不把程序原因当软件规则已证，当前算法§12.67/LLD§45/研究§8.125。

2026-10-20 [短负柱确认](../../../reports/xxm_m120_reference_trace_20261020_01/image_confirmation_20261020/README.md)结束上述待答：管理员看见短负柱隔开，软件与本地柱色相容；不由此证明软件内部同样分段/只留两段。后续核选峰等规则，不再追问本柱；算法§12.67.2/LLD§45.2/研究§8.126，产品不变。

2026-10-20 [短负柱假说核查](../../../reports/xxm_short_negative_bar_hypotheses_20261020_01/README.md)：120讲解指1/30的新图已归档；单独换旧参照不能消掉原3/1链。当根价格条件的五段资格表有区分性，但尚非完整候选/旧52验收；沿用原峰与当根资格分开待证，82/72行/32重叠核一致，无产品变更。当前算法§12.68/LLD§46/研究§8.127。

2026-10-20 [旧首次标记审计](../../../reports/xxm_current_close_old_case_audit_20261020_01/README.md)接续研究：更正负柱不导致正柱的因果表述；原52中10首次TOP当根均满足新增价格条件，1 direct/9 mapped，未发现当根反例但不宣称完整新候选/52通过。494来源行/76保护保持，无产品变更；算法§12.69/LLD§47/研究§8.128。
