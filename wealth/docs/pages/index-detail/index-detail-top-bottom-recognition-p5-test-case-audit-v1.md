# 顶底识别P5测试用例审计与清理记录 v1

日期：2026-11-03，状态校正：2026-11-04。性质：**审计依据及已授权清理交付记录。**§1—6为初次审计的发现/保留边界，旧位置和函数名指清理前；当前逐项结果及独立复核见§7—8。清理代码与对应文档已在dev-interface提交`5129f1452`，未部署；清理仅修改测试与对应文档，未改产品运行代码、配置或数据。

当前P5第三步整体回归及最终审计已完成，见§10及LLD§22.16.6；§9保留首次静态检查停点，问题已经修正。此前1570/1与清理阶段2740/74仅保留原阶段身份，不与本次3193/332混加。

## 1. 范围与依据

范围为原LLD§22.10明确的35个Python单元和28个前端测试文件，合计63项；组织检查只包含指定节点。另核直接使用的fixture、当前Spec、计算器/恢复/预测、后端表达式schema、前端请求/decoder/Hook及原LLD。范围外交易助手TODO、其他研究测试和生产性能采样不纳入。

[逐文件检查清单](index-detail-top-bottom-recognition-p5-test-case-audit-v1.csv)记录63项的实际范围、问题编号、检查方式和限制。全清单做静态结构、参数、旧字段/预期及替身入口筛查；下列问题进一步读相关正文并与生产者/调用路径核对。**这不是逐个参数化节点的运行验收，也不是对全部变体逐根手算。**没有问题编号只表示本轮未列新增清理项，不能解释为该文件已经通过。

CSV的`disposition`表示当前处理状态，`cleanup_result`和`verification_result`分别记录具体处理和已验证范围；初次审计的发现及原建议保留在本文§1—6，不以“待清理”表示已经完成的事项。

依据顺序：管理员已经拍板的业务规则；现行方案/LLD的规则章节；当前真实生产者、schema和消费者；独立人工预期。三者矛盾须登记，不能为迎合旧测试改现行产品。已通过测试也必须接受本次审计。

使用了CodeGraph sync/status、codegraph_explore，核对后端恢复与schema消费者、前端预测Hook/decoder的调用关系；具体判断继续读取当前源码，未用图谱结果替代业务分析。静态检查仅解析/读取文件，未import测试模块或启动应用。

当前事实：识别为v0.4-r4，预测为v0.6-r4；只预判下一根；正常首次反色进入跟踪时同时有原Wave；原段内DIF回转退钝化不进入FOLLOWING；单根同色段不结束旧结构跟踪，但该根照常检查价格。两个暂缓TODO——历史参照至少几根、首次顶部DIF是否必须为正——本轮不重新裁决。

## 2. 原问题及采用的处理方向

| 编号 | 原问题 | 原审计分类 | 原建议（实际处置见§7） |
|---|---|---|---|
| F01 | 识别Spec独立预期仍为v0.3 | 确定过时，前次首错 | 按已批准v0.4修正字面预期，保留规则核对 |
| F02 | 整份表达式测试仍接受旧多步合同，LLD又误称其现行合法 | 确定错误，优先处理 | 按单根schema重写相关输入/预期，删旧多步正例，修LLD |
| F03 | 强改计算器自产结果再要求其拒绝 | 低价值内部造错，建议清理 | 建议删除所列15项扩展，保留真实序列与必要失败隔离 |
| F04 | 同类内部失败隔离在多处重复展开 | 防御重复，待review | 合并相同目的；保留真正不同的源读取/取消/缓存发布边界 |
| F05 | 下溢极小数、1e308等与行情无关的极值 | 缺少实际行情或故障依据，待review | 清退极端变体；保留正常量级精度、1%及NaN/inf检查 |
| F06 | 为JSON接口手造循环对象 | 接口真实输入不可达，待review | 删除自引用循环场景；保留真实嵌套JSON合同 |
| F07 | 字段缺失检查机械展开周期×方向 | 重复覆盖，待review | 公共形状检查收敛，周期/方向业务验证继续保留 |
| F08 | 同一整数边界校验展开144项 | 重复覆盖，待review | 保留18类边界和两类入口，减少无关周期交叉 |
| F09 | 锁死import个数、完整语句而非禁止依赖 | 实现约束过重，待review | 保留依赖隔离目的，去掉无关格式/数量要求 |
| F10 | 用“对象不含list/dict/set”代表内存有界 | 判断依据不准确 | 不把容器类型当内存增长；保留必要状态/结果验证 |
| F11 | 临时日历每次从2020/2023生成到真实今天 | 测试范围随时间无界增长 | 按测试请求有界造数，latest场景单列 |
| F12 | 普通数学单测以机器实测400ms作为硬通过条件 | 与正式性能验收混用 | 真实计时另记，保持预算/取消验证，不放宽产品400ms |
| F13 | 锁死、七字段等旧名称/说明仍残留 | 说法过期或覆盖描述不准 | 按当前有限跟踪和实际字段改名，不删真实业务测试 |
| F14 | 测试标题宣称检查历史不轮询、换模式等，正文未覆盖 | 用例说明与实际断言不符 | 改准说明；必要真实交互另列最小用例 |

上述建议现已获管理员授权实施。F01—F14的实际处置、不同边界的保留理由及验证见§7—8；不把原分类中的“待review”当成尚有未决产品规则。

## 3. 逐项依据与清理边界

### F01：独立规则字典未跟随已批准版本更新

- 位置：[test_xxm_input_validation.py](../../../../scripts/research/index_market/tests/test_xxm_input_validation.py)，`test_formal_spec_contains_every_approved_rule_and_hashes_canonical_content`，119—140行。
- 旧预期是`xxm-direction-v0.3-r4`、`next_same_color_close_break`，漏`structure_follow_min_bars`。现[spec.py](../../../../src/biz/services/wealth/market/index_detail_xxm/spec.py)及LLD§2.2为`v0.4-r4`、`price_until_first_valid_same_color_end`、严格整数2，其余17项相同。
- 应修上述字面预期；完整字段/规则hash/类型及拒旧检查仍有价值。不得从`asdict(MAIN_SPEC)`直接生成expected，也不得把正式规则改回v0.3。此项已按§7修复。

### F02：表达式测试和执行LLD还在维护旧多步合同

- 位置：[test_xxm_forecast_expression_contract.py](../../../../scripts/research/index_market/tests/test_xxm_forecast_expression_contract.py)，16—123行；原LLD§22.10.5的4.4行、§22.10.7末段。
- 当前[ForecastExpression schema](../../../../src/biz/schemas/wealth/market/index_detail_xxm_forecast.py)只有`affine/scale/abs/sub/macd/round3`六种；`MacdExpressionDto`只有op/e12/e26/dea/field五字段，额外字段禁止。当前计算器表达式和前端decoder也没有20步前缀合同。
- 测试MACD公共样本却带`prefixBars/prefixClose/target`；13个“应接受”正例中，至少9个含旧节点/字段，包括`add/div`、19/20步。`test_twenty_step_compact_node_stays_small_and_round_trips`也明确要求接受20步。这是静态合同冲突，本轮没有运行它们，也不虚报新增失败数。
- 反向用例还存在“从错误样本起步”的问题：例如`add`的5个参数数量反例、`div`的8个除数反例、10个prefix/target反例、8个prefixClose数值反例，共35个变体本身就不属于当前表达式合同。它们即使抛ValidationError，也不能证明标题所说的长度/除数/多步前缀规则被验证。MACD数字反例同样须先换成当前合法五字段样本，防止额外旧字段掩盖目标错误。
- 清理方向：保留当前六种节点、正常嵌套及原始数字/缺键/坏字段的正反例；重建合法MACD基底；删除“旧多步应接受”、旧add/div数值能力和20步体积验证。旧字段若保留，只能作为明确拒旧的少量反例。
- **必须同步修原LLD把legacy节点写成合法合同的错误。**它会诱使后续开发恢复旧能力，不是仅改测试名字即可。前端`r1Contract.test.tsx`实际在拒绝旧合同，不属于本项删除对象。

### F03：计算器自产结果被测试强行篡改

- 位置：[test_xxm_r4_restore.py](../../../../scripts/research/index_market/tests/test_xxm_r4_restore.py)：`test_rc70_corrupt_constructed_decision_is_rejected_before_publication`（10项）、`test_rc70_missing_complete_structure_result_is_rejected_before_publication`（2项）、`test_rc70_missing_cancellation_event_is_rejected_before_publication`（1项）、`test_rc70_constructed_decision_wave_count_rejects_bool_for_integer_one`（1项）、`test_rc70_constructed_event_reference_rejects_bool_for_price_one`（1项）。合计15项，460—564行。
- 这些用例替换`_finish_step`，把正式代码刚生成的事件/结构清空，或把其count/price改成bool，再要求后面的检查发现错误。正常K线或调用参数不会这样改程序的自产结果；没有列出对应的真实输入、既有缺陷或外部入口。
- 建议删除这组过度扩展，不把每个可能写错的内部字段都做一个“故意把程序写错”的测试。真实K线逐根预期、关联/历史及必要失败不污染状态继续保留；不删外部输入/restore接收坏副本的验证，不改正式校验函数。
- 原LLD RC70和构造后拒错的扩展要求也要随最终review结论收敛，不能删测试却留下要求另一轮再造回去的文字。

### F04：必要的失败隔离被重复验证

- 位置：恢复文件`test_rc70_failure_after_event_and_structure_construction_keeps_self_and_outputs`的4周期×2方向；跟踪文件`test_rc95_failure_after_old_updates_leaves_all_inputs_and_outputs_unchanged`；观察文件`test_copies_restore_mode_and_failed_final_construction_are_isolated`；内部结果文件`test_rc72_post_step_failure_discards_candidate_preserves_published_cache`；snapshot消费者文件`test_increment_failure_after_real_step_preserves_old_entry`。
- 其中模拟校验/整理失败后丢弃本次候选，是已确认的安全要求；但同一纯内存失败点与周期/方向无关，不必反复全部交叉展开。观察开关也不需要重新证明相同失败隔离的全部矩阵。
- 建议按实际失败位置合并代表：计算进度失败、查询源读取/缓存发布失败分别保留；空对象与已有结构、真实取消与超时、对外恢复坏副本不能随便合成一种。特别保留真实步骤已执行后旧缓存/此前输出仍不变的关键断言。此项不是要求删除所有异常模拟。

### F05：缺少本产品依据的浮点极值

- [test_xxm_key_point_forecast.py](../../../../scripts/research/index_market/tests/test_xxm_key_point_forecast.py)：`test_pf08_gate_underflow_keeps_strict_direction`用`nextafter(0,+inf)`（约5e-324）作为上一根DIF，展开8项；`test_pf17_reference_comparison_overflow_is_rejected_before_forecast`、`test_pf17_selected_far_difference_overflow_is_not_a_disappearance`和`test_pf17_structure_finite_dif_must_not_overflow_turn_or_reference`使用1e308一类DIF/EMA，共4项。
- 同文件`test_pf17_nonfinite_original_projection_rejected`中的`10**400`变体，以及数学文件`test_pf16_original_large_source_options_are_not_trimmed`、`test_pf16_independent_fraction_source_error_encloses_all_original_choices`的万亿/机器下溢变体、`test_pf17_nonfinite_original_operations_fail_instead_of_certifying_false`的1e308操作，也应列为精简候选。
- 这些测试在追逐浮点数的极限，不是在验证上证行情已知故障。本轮没有找到对应行情、输入合同或真实问题作为此产品验收的依据；这不等于宣称数学结论错误。
- 建议退出本轮产品回归的极端变体，保留正常量级的1%边界、原EMA顺序、三位精度、开闭区间、相邻可表示价格、NaN/inf/bool及正价检查。**不能把真实精度边界和机器极值一起删掉，也不能顺势更改求界算法或精度预算。**LLD的相关PF08/PF16/PF17极值扩展要一起review。

### F06：JSON入口不存在自引用循环

- 位置：前端[expressionContract.test.ts](../../../../wealth/src/features/index-detail/xxm-forecast/expressionContract.test.ts)的`rejects cycles but accepts a shared acyclic expression leaf`；后端表达式合同文件`test_recursive_cycle_is_rejected_but_shared_legal_children_are_accepted`。
- 测试把对象的arg指回对象自身。实际前端路径是HTTP正文→`http.json()`→adaptForecast→debug decoder；JSON不能表达对象自引用，反复引用同一个JS对象也不是JSON保留的对象关系。后端该用例的正半部还用了当前已不支持的add节点，亦受F02影响。
- 建议删除这些循环/共享对象身份场景，保留真实JSON可以表达的合法嵌套、未知节点、缺字段/错类型。不是要求本轮删生产代码的循环保护，更不新增一套防御来满足人为循环。

### F07：同一字段形状反复交叉验证

- 恢复文件`test_rc71_missing_tracking_field_is_rejected_without_defaulting`把3个缺键检查展开为3×2方向×4周期=24项；BAD_PATHS又有24类×4周期=96项，另有snapshot_validation对相同通用形状的检查。
- 实际公共`_fields`按键集合检查，不依赖方向/周期。建议缺键保留逐字段反例，减少无关交叉；身份、日期格式、顶底业务、周期端点及合法样本继续分开覆盖。
- 不得机械删完96项，也不借此取消既定37×4每截断恢复序列。字段缺失合并与真正的日期/状态差异是两回事；要先做去重对应，再改LLD清单/数量。

### F08：整数范围的144项重复矩阵

- 位置：[forecastDebugContract.test.ts](../../../../wealth/src/features/index-detail/debug/forecastDebugContract.test.ts)，10类合法、8类非法范围×4周期×2种条件入口=144项。
- 整数上下界/开闭逻辑是同一个与周期无关的range函数；两种入口确实都需经过，但完整18类没有必要在每种时间格式上重复。
- 建议18类在代表周期和两种入口中保留，其余周期保留少量接线/时间正反例；不删真实2026-10-27的`upper=null`回归，保留通过实际HTTP客户端消费该边界的测试。这里不声称已经测得144项的时间收益。

### F09：测试约束到了import格式和数量

- [test_xxm_product_v1_cases.py](../../../../scripts/research/index_market/tests/test_xxm_product_v1_cases.py)的`test_input_material_only_imports_its_dataclass`要求恰一个import且只能dataclass。防止人工材料调用被测实现生成expected有依据；禁止增加合法typing等无执行副作用的导入没有同等依据。
- [dependencyBoundary.test.ts](../../../../wealth/src/features/index-detail/debug/dependencyBoundary.test.ts)将页面例外写成一整条固定import字符串，又要求debug loader恰一个运行时import且必须react。合法引号/格式变化，或增加无关纯工具导入，也可能被当成违约。
- 建议保留“普通入口不默认载入debug/研究/波段实现、材料不反向生成预期”的依赖约束；删除与这些目标无关的格式/数量锁定。不把依赖隔离测试本身删除，也不新增源码SHA保护。

### F10：没有容器不等于内存有界

- 位置：[test_xxm_local_extrema_study.py](../../../../scripts/research/index_market/tests/test_xxm_local_extrema_study.py)，`test_generated_performance_input_has_bounded_scanner_state`。
- 10,000个输入后的3999个极值是明确结果；但`vars(scanner)`中不得出现list/dict/set，不能证明内存有界：固定长度容器也有界，换成其他容器也未必有界。这条断言把一种实现方式误当需求。
- 建议清掉禁止容器类型的断言，保留结果正确/状态不随历史无限积累的目标；当前不写新的测量器或为了证明有界改扫描器。独立峰谷工具仍保留。

### F11：每个临时数据库都造数到真实今天

- 位置：[识别API测试](../../../../tests/web/test_wealth_index_detail_xxm_api.py)和[预测API测试](../../../../tests/web/test_wealth_index_detail_xxm_forecast_api.py)的`source_db`。识别测试从2020-01-01铺到`datetime.now(ZONE).date()`；预测测试从2023-01-03到`max(起点+120天, datetime.now(...).date())`。
- 测试主要使用固定的2020/2023请求、人工K线，日历却随年月增长，并在函数级fixture中重复生成。这里是测试自己生成多余数据，不是读取Prod；本轮未测耗时，不能给出毫秒收益。
- 建议按每组请求实际需要的前后日期范围构造固定小日历，真正验证latest随日期变化的场景单独保留。不能缩掉必要下一交易日/休市/缺日例，也不把真实P4验收改成冻结时钟。

### F12：普通单元回归混入机器实测性能门槛

- 位置：预测文件`test_pf19_mathematical_time_and_repeat_leave_no_shared_results`，四周期每项直接要求`elapsed < 0.4`。
- 同一机器有其他任务时，这一单元可因负载失败；它只测数学片段，既不是API完整400ms计算预算，也不是P4真实端到端验收。重复执行与结果不共享仍是有用断言。
- 建议将实机耗时记录与功能回归分开，保留预算到期/中断的可控测试和已定义的正式性能验收。**产品400ms不变，本轮不提高阈值、不做测量。**删除此硬断言须同步PF19及执行方案，不能绕过真实性能要求。

### F13：旧的锁死和七字段说法会误导后续维护

- 位置：`test_pf13_lock_has_no_new_structure_event_and_none_is_not_cancel`、`test_pf14_locked_history_starts_new_loop`，snapshot解析测试`test_parse_returns_seven_independent_progress_fields`，部分内部结果测试的locked变量/lock参数说明。
- 当前首次反色只是开始有限跟踪，后面仍会因价格消失；ParsedXxmSnapshot已有followed_structures共8项。上述测试名和说明仍沿旧术语。尤其PF14用反色根close104，已高于原TOP价103，却只检查新循环，没有据该名称证明“旧结构锁死”。
- 建议改准名称/说明，必要时用该真实序列补已有终态断言；不删除正确的新循环/历史关联验证，不把旧“锁死后永不消失”重新写进规则。snapshot字面输入也不因名称旧就清退。

### F14：标题承诺的真实交互没有全部发生

- 位置：[forecast.test.tsx](../../../../wealth/src/features/index-detail/xxm-forecast/forecast.test.tsx)，14—19行。
- `never registers requests in production or when disabled`只设置了生产环境，没走开发环境enabled=false。
- `aborts ... owner or mode changes`实际只改active=false，没有换指数或debug模式。
- `polls latest ... and has no historical timer`只挂载latest后停用，没有挂载历史日期再推进时钟。历史重试那个测试也没推进60秒来验证不自动轮询。
- 当前Hook源码确有对应条件，不能据此说产品已经坏了；但这些标题不能充当分支覆盖证据。建议改准现有说明，并按已确认需求列最少的历史不轮询、实际换模式/指数或停用场景；避免再展开所有条件的组合。页面已有装配验证可复用，但它mock了Hook，不能代替Hook自身的异步迟到行为验证。

## 4. 已处理历史问题，不列为再次清理任务

| 历史项 | 现状态 | 本轮处理 |
|---|---|---|
| 手写STRUCTURE少3字段、FOLLOWING样本未补跟踪事实 | 前轮已补齐，恢复307项完整通过 | 只记录原因，不重改，不把24项反例扩为更多交叉组合 |
| 强把DISAPPEARED改FOLLOWING却缺原Wave的顶底2项 | 管理员已批准并删除 | 不恢复、也不挪动造错位置；原失败保留历史，删除不记成功 |

## 5. 明确保留，防止清理时误删

| 应保留的覆盖 | 原因 |
|---|---|
| 当前价/DIF、近B后远A、当根切换、真实反色/零、1%及曾突破不恢复 | 直接对应已确认r4识别规则；独立字面序列不是胡编内部状态 |
| 单根段不终止、各柱色逐根查价、首个有效段结束、旧CANCEL与新DULL显示规则 | 已由截图review/当前规则确定；顶底镜像和四周期有真实业务差异 |
| 原图3例与来源/端点身份 | 保留管理员确认的事实，不为当前代码改日期、点位或补值 |
| 输入类型/NaN/inf、缺行情、真实休市、坏副本原状态不变 | 是明确输入/恢复边界；不等于任意替换计算器自产结果 |
| 单根预测、近处有解不算远处、EMA原顺序、正常量级精度/无界区间 | 是现需求，不因清理极值而回到中点/逐分扫描或多步推演 |
| 真实取消/超时、共享加载、异常不污染缓存、自有子进程清理 | 有明确故障/资源边界，不能因为用了替身就删除 |
| normal/debug公共一致、生产关闭、辅助按需加载、主图不变 | 是已拍板的产品边界；真实HTTP/SQL/临时Gold及TS客户端用例仍保留 |
| 保留材料数据SHA、独立取数/峰谷/图像、架构/退役目录约束 | 数据身份和架构检查有依据；不是用户否决的产品源码SHA保护 |
| r1/rearm/旧规则字符串用于明确拒旧、37组旧材料只作INPUT | 旧名字不等于旧行为仍被接受；不能按关键词删除 |

普通接口的1500根限制与离线原图案例的既有前史不是同一个入口。不能为了缩短测试把原图前史裁成1500，也不能反过来允许产品恢复全历史读取。人工核心序列无需由自身短段收盘重算EMA，实际来源/校准测试另有真实生产者合同；不要把组件隔离测试误判为必须一律接真实数据。

## 6. 审计结论、后续交接和限制

此前review重点核了清单/收集/执行退出，却没有把独立预期、造错入口和当前生产合同逐项对齐，才会连续在旧样本、不可达内部状态和旧Spec预期处停止。F02进一步证明还有整组错误合同被LLD当作合法测试保护；不能继续用“先跑起来，遇一个改一个”代替本轮审计。

已按管理员授权先补LLD§22.15，再实施F01—F14并完成限定验证及独立复核，见§7—8。完整P5回归没有恢复；不承诺未重跑文件必过。

尚未做到逐参数实际执行/手算，其他语义问题仍可能存在；静态未发现新问题的文件不登记“正确”。首次静态审计没有产生测试成绩；本次限定验证的范围见§8，没有新增性能改善或生产结论。所有本轮范围外的既有未提交修改保留。

首次审计的文档/清单检查只证明当时记录可定位，没有代替运行验证。本次清理和验证结果见下节，当前CSV已增加逐行处理及验证状态。

## 7. 已授权清理的逐项结果（2026-11-03）

管理员已要求按本记录修改并复核，编码/验证设计先落原方案与LLD§22.15，再修改17个测试文件（13 Python、4前端）。本节是当前处置；§1—6保留首次审计依据，其中位置/旧函数名指清理前版本。没有据旧预期修改正式产品，也没有续跑P5整批。

| 项 | 已落实的处理与保留覆盖 |
|---|---|
| F01 | 独立expected同步v0.4/policy/min_bars三处，完整规则/hash及拒旧不变；101项通过 |
| F02 | MACD合法基底改为五字段；六种单根节点及JSON往返、数值/缺键/额外字段和真实嵌套反例81项通过；旧add/div/prefix只拒绝，清掉多步接受/20步体积；原LLD三处错误保护已修正 |
| F03 | 删除审计指定5函数、15原变体，无外部import消费者；未增产品防御或移动造错位置；恢复文件198项通过 |
| F04 | 构造后失败8收1，跟踪前/后两prefix仍验、去方向交叉，观察文件去重复故障段；空对象、聚合与模型、推进后缓存分别保留，21项恢复消费者及39项内部结果通过 |
| F05 | 清掉机器下溢/1e308/10**400及大数专属变体，原无绑定投影正常拒绝保留；普通1%/三位来源/正负零Fraction/开闭及NaN/inf/bool保持；数学57及预测82通过 |
| F06 | 删除不能通过JSON传入的循环/共享对象身份场景；合法JSON和嵌套坏节点继续验，前端2及后端81通过；运行代码循环保护未改 |
| F07 | 三缺字段24收3；公共坏字段96收30（两个日期字段保留分钟差异）；37×4所有截断、顶底/周期真实恢复、直接parser和对象不变各边界保留 |
| F08 | 144项范围矩阵收为48：18类day×两入口，以及每分钟周期/两入口的一正一反；原upper=null与HTTP客户端回归保留 |
| F09 | 不再锁import数量/完整语句；Python允许标准库且拒产品/研究依赖，前端AST识别type-only/动态/路径，bare包名不当本地路径；16项材料与4项边界测试通过 |
| F10 | 去“不准list/dict/set”和无用time；保留10000/3999真实序列结果，不再声称证明有界内存；6项通过 |
| F11 | 两临时日历按场景固定，并只通过原now参数补默认时间；显式now不覆盖、原读取/校验完整。长校准例独立补290根所需日历及下一交易日；后续日历实际变更断言rowcount=1。两API187/117项通过 |
| F12 | 去数学单测实机400ms断言，保留计时记录/结果独立性与可控超时/取消；正式预算和P4证据不改，不宣称新性能达标 |
| F13 | 改准首次反色/有限跟踪/副本名称，不改线程锁；PF14明确104突破原103即消失，核id/原因/日期/事件，仍可进入新循环；followed_structures副本独立性也验 |
| F14 | 补两个独立门禁、历史60秒不轮询/手动重试、实际换指数与切debug的取消/迟到隔离；只替HTTP客户端，真实Hook执行；10项通过 |

F04/F07没有把不同发布/恢复边界一并删掉：internal_results两个故障点、snapshot_consumers推进后失败以及直接parser坏副本仍保留。这是按原记录的保留边界收敛，相关CSV逐行登记理由，不是漏改。

## 8. 独立复核、验证及当前停点

- 对照本轮开始时保存的文本差异，实际只改上述17个测试文件；所有原模块级字面业务输入/预期（重建的表达式合同除外）、37组输入及69组/125业务变体未改。r4_restore的literal_snapshot和其他既有helper参数、恢复每个cut循环不改；snapshot_validation的37×4函数与其依赖不变。
- 删除的5个F03函数无当前代码消费者，其他坏输入/恢复/原状态不变测试保留。正式XXM核心、查询、schema/Spec无git差异；本轮未改Wealth运行代码、配置或API，其他工作区改动保留。CodeGraph query/sync/status与源码复核相互核对，无新增跨层依赖或需管理员重新决定的产品边界。
- Python：改变的13个完整文件2083项，8个必要关联文件/指定节点657项，合计2740 passed。前端：改变的4文件64项，另2个现有客户端/拒旧合同10项，合计74 passed。Wealth typecheck/build均通过；根架构16项与研究指定节点1项已含在Python数内，不重复累加。没有skip/xfail、超时或未退出自有进程，单元最大20.357719秒，小于60秒上限。
- 验证中保留三次首错原记录：F11短日历缺场景时钟、长校准例缺跨年日历，以及新F09测试将react误作相对路径。均先按当前代码定位并补LLD，再仅修测试，受影响完整文件重验通过；未改变预期或正式实现。部分通过不累加，无关且依赖未变的完整通过文件复用。初次进程状态读取被工具权限阻止时没有启动测试，后按工具授权执行监督。
- 原始摘要分目录保留在`/private/tmp/p5-case-cleanup-_hbyfk0q/verification`至`verification-4/results.json`；当前结论只来自完整有效行的去重集合。它不是原P5成绩的更新，不能与旧1570通过/1失败相加。临时摘要不代替这里的持久记录。
- 当前只完成用例清理及限定验证。P5整批回归、未重跑文件、真实数据源/性能/浏览器验收没有新增结论；不自动提交、部署或进入P5第四步。后续恢复P5须按实际35/28清单重新确定当前收集数和受影响证据，不能沿用旧3298/3320作为硬断言。

最终文档静态核对通过：根文档完整性3项，6份Markdown的446个本地链接/22个锚点，63项CSV的路径/处置/验证状态，17个测试及7份文档/索引/CSV的限定差异与空白检查。CodeGraph最终sync/status为最新。删除后的文件尾空行已清理并确认AST不变，无需重跑测试；这些检查不计入通过数。

2026-11-04提交后复核发现，CSV的18行虽然已有处理结果和限定验证记录，`disposition`仍写为待清理。现统一修正为“已按记录清理并完成限定验证”，其余45行状态及全部处理、验证字段保持不变。本次只校正文档状态，不重跑测试、不增加通过数量；P5整批回归仍暂停。

## 9. 第三步首次静态审计停点（2026-11-04历史记录，完成见§10）

本次测试部分已完成：35个Python单元3193项（本次20单元774项，复用15单元2419项），28个前端完整文件332项（本次22文件258项，复用6文件74项），类型检查及构建均通过。测试无失败、skip/xfail或超时，自有进程均干净退出；本次最长测试19.820993秒，类型4.903735秒、构建5.940516秒。复用次数不另加，旧1570/1不并入。

最后静态审计的首个引用检查未完成：临时`references.py`仅import importlib，却访问importlib.util.resolve_name，标准库子模块未显式导入，0.255767秒以AttributeError退出。错误在临时检查脚本中，不是产品代码/测试失败；本轮未修该脚本或重试，未继续其余最终静态检查。按LLD首错停止，P5第三步仍未完成，不能交第四步。后续只需先明确临时脚本修正，再补最终引用、资料、文档及结果审计；已经有效通过的测试不默认重跑。本轮未改业务/测试/配置/数据，未提交、推送或部署。

CSV的verification_result保留原清理阶段说明，并逐行补上本次第三步的完整执行或明确复用、数量/耗时/退出。63行对应35个Python单元和28个前端文件；不能将65个测试/编译单元全通过误当最终静态审计已经完成。当前停点、逐行结果与P5-01—22覆盖以LLD§22.16.4为准。

## 10. P5第三步整体回归与最终审计完成（2026-11-04）

本次已完成P5第三步整体回归及最终独立审计：35个Python单元3193项、28个前端完整文件332项、类型检查和构建通过。3193=本次执行774+明确复用2419；332=本次执行258+明确复用74，65个测试/编译单元无缺失、重复、测试失败、意外跳过或超时。复用仅来自代码/输入/依赖未变的完整有效证据，不把早期部分通过或删除项算入成绩。

临时引用脚本仅补显式importlib.util导入，原首次失败保留；同范围修正后检查2.187603秒通过。随后资料0.166654秒、文档0.283145秒、结果/工作区/退出0.459565秒分别通过。61旧代码/对应pyc缺席，221目标及7抽取合同、两个嵌套白名单和未执行Notebook有效；全部65行与63项测试清单相符、记录的54个自有进程组均已退出，其他工作区状态和资料未受影响。根文档完整性3项、本次4份Markdown的47个本地链接/4锚点及CSV63行通过，差异空白通过。同步完成状态后还按同一方法复核最终文本和结果。

本轮续做只修临时检查并同步原三文档、审计记录/CSV，没有修改产品/测试/配置/数据，没有重跑已通过测试，也未新增正式源、性能、浏览器或视频验收结论。P4真实来源/页面及迁前原字节/叶值交接继续只复用原范围；11条缺原图限制、暂缓优化及范围外日期TODO保持。P5第四步最终交付尚未开始，未提交、推送、部署或开放生产r4。

CSV逐行保留清理阶段和本次第三步的证据来源、数量/耗时；63行现已同步第三步回归完成和最终审计通过。当前执行状态以本节/LLD§22.16.6为准，§1—9中的早期未完成状态不作为后续执行指令。
