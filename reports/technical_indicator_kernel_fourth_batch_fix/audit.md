# 第四批-修复开发：已完成并通过固定验收

依据原方案及LLD19.32/19.33，初次暂停、单独来源起点修复均按当时事实保留。管理员已再次授权完成剩余工作；现已完成本批开发、固定验收和独立只读对账。以下历史段落不作为当前未完成状态。

## 初次暂停时的修改与限制（历史）

- 历史需求合同、两份预热SQL、计算模块交接和三处控制查询登记已写入，未运行。
- 来源selection合同、共用时间条件、读取会话和服务/输出数量交接已写入，未集成完成。
- 一部分既有消费者已迁移；来源/复权/字节计量/诊断迁移未完成。
- 定位对象只有初稿，原source工厂和价格流未接通。新增8函数未编写，不能运行当前混合状态。

## 本次停止原因

LakePriceLocator._select在已找到足够目标和前置后，仅以path_index==0且index==0决定origin。一个最老行组有4000根、只需1500根时，它会错误设置origin=true，随后wanted=rows变成4000。找到最老数据块与选定范围从第一根开始是两件不同的事。

原LLD已明确区分，不需要新增业务决策。建议按选定下界是否到最早实际记录判断；组内裁剪时保持false，完整来源确实耗尽且需要全部历史时才沿原起点初始化。当前没有自行续改、测试或重跑。

## 验证和资源

本轮只有CodeGraph、源码/文档和官方Arrow文档只读核对，无SQL、pytest、指标计算或正式数据读取。计算/参考/夹具输入0，逻辑SQL0，定位键0，新增真实Control0。无连接、Reader、控制线程或临时行情夹具需要清理。全部验收预算保留，详progress.json。

## 影响面与依据

CodeGraph explore检索TechnicalIndicatorService/HistoryRequirement等；通用词混入无关符号后，直接核实本库真实service、source/session、指标与测试消费者。修改仍在Foundation本库及既定局部测试/文档，未触及API、页面、XXM、DG或原D4 App。原D3报告未改。当前文件指纹已记录，恢复只继续未完成工作，不重跑旧组。

## 来源起点判定修正及有界验证

只修改LakePriceLocator._select：候选是否正常耗尽与最终选定范围是否到起点分别记录。有限预热先取min(rows,R+B)；只有requires_source_origin或R+B超容量时才尝试rows。最后以候选已确证耗尽且wanted==rows确定reached_source_origin。没有修改接口、配置、预热公式或其他生产代码，尚未接通的source工厂和价格流仍未接通。

origin_selection_regression.py以独立的抽象有序来源计数代替元数据和键读取，执行真实_select及PriceReadSelection。7项有限检查全部通过；4000取1500、容量2000不误拒、start目标50取550这三项在修正前实际方法中复现错误，修正后正确。另核1600首1500、最早600全部保留、长预热1600真实起点以及容量不足时拒绝。抽象序号仅检查边界选择，不生成行情行、不检验交易日，不得据此声称实际Parquet、SQL、指标精度或服务集成通过。

仅运行一次，无自动重试。数据输入、SQL、定位键和真实Control均0；实际程序耗时已写入progress.json并计原300秒额度。Python语法及差异空白检查通过，独立代理只读复核确认该处符合LLD。CodeGraph node精确核_select及describe调用；没有改变Foundation边界。原8函数及静态测试节点仍未运行，不提前消耗或挪用其场景。

两份原文档已同步修正状态，保留此前错误记录；本轮没有继续其他开发、执行正式数据操作或提交。

## 本次恢复完成的内容

- 读取源已从旧describe迁移为无资源create_locator；读取会话先持有定位对象，成功或异常均有清理负责人。
- 元数据检查仅保护选定行组；价格流同时按证券代码、选定行组和read_start/read_end读取，保留原8192合批、紧凑复制、余量不重计和关闭逻辑。
- 周/月物理标签边界通过固定SQL沿现有period_end公式转换；周二截止不与周五标签直接比较，source_as_of仍单独检查。
- 剩余测试及诊断合同同次迁移；旧统计字段、旧历史开关、旧来源调用及旧Session构造搜索清零，没有新增兼容入口。
- 原8个新函数和1项既有纯静态检查一次通过，不重跑旧D2/D3整组；此前7项选择逻辑回归也未重跑。

## 要求、实现和证据对账

| 要求 | 实现位置 | 对应验证 |
| --- | --- | --- |
| 业务只提供输出范围及指标参数，不提供预热、SQL或基准 | contracts.py、calculation/history.py及各指标声明 | 新函数1、2、7；既有静态资源节点 |
| 参数准备一次后解析动态需求，多指标取最大 | calculation/engine.py、history.py | 函数1、2读取实际控制结果；默认500、自定义1163/1235，组合输入2235 |
| 固定窗口N−1与递推预热分别声明 | MA/BOLL及window_mean/window_range；MACD/KDJ input_requirement | 函数1、2、5、7；KDJ恒等周期返回8 |
| DuckDB计算误差与有限求根，Python不计算指标值 | macd_warmup.sql、kdj_warmup.sql、smoothing_parameters.sql | 函数1、2、4、7；原独立HUGEINT结果对照 |
| 两预热文件和三处控制查询固定登记，严格BOOLEAN/NULL | sql_templates.py、engine.py、CalculationSession、executor.py | 函数7及1项静态资源节点，精确9计算/3输出文件 |
| 每请求定位及参数表独立，不能业务替换SQL | source factory、LakePriceLocator及指标所有者 | 函数7拒绝未登记步骤、文件和删除借用表；正常真实SQL路径保留 |
| 键列定位、最多两边界且同组第二遍一次，实际缩小价格读取 | technical_indicator_price_locator.py | 默认两页价格各1500，定位分别8000/6000；重复键读取计入29053 |
| 找到最老组不能扩大选定范围 | _select中先wanted再判断origin | 原7项选择逻辑回归保留；函数1、3、4以真实临时Parquet复核 |
| 一批不超过8192先读齐；跨文件合批 | _LakePriceStream.next_batch原实现及选定范围入口 | 函数1/2的1500/2235单批；函数5的21文件合一批；8192以上原D2证据不重跑 |
| 复权基准不随页变，已有qfq不重复转换 | source.prepare_basis、Session/PriceAdjustmentCalculation | 函数1分钟转换0；函数5两请求各转换1次、同一最新基准2，旧价5/新价6 |
| 本次选定范围结束不等于原始历史结束，容量不得裁短B或目标 | _select、PriceInputSession._validate_selection | 函数3的1000/600/空；函数4真实1600完整历史及错误交接拒绝 |
| 源代码/标签/截止语义保持，当前周参与计算 | technical_indicator_contracts.py、time_range.py、source.open | 函数6两个日期更新当前周、后来版本明确拒绝、首次空成功 |
| 输出保持独立说明和实际范围，不依赖计算计划 | service._describe_output_instances、output/collector.py、result.py | 函数3/6空与非空说明；静态输出依赖检查 |
| 日期数量NULL严格；不足窗口保留NULL，不能用NULL掩盖缺行 | OutputCollector逐批核对、最终expected_rows检查 | 函数1/3/5与独立参考；第8函数删行/删表反例 |
| 定位数量与真实交付数量分别核对，不返回部分结果 | Session._check_delivered_count及Collector.build_result | 函数8三数量反例分别在selection_count_mismatch、final_query拒绝，真实COUNT/fetch未替换 |
| 无额外一根、无has_more/next_before、无额外探测请求 | 来源选择、输出范围、既定before过滤 | 函数3正常第三请求成功空；静态禁止字段节点 |
| 同一服务创建关闭唯一连接，先登记后创建，正常清理失败不得成功 | service、Session、locator及Engine/Collector清理 | 21次真实连接均关闭，表/Arrow清空，各Locator/Stream关闭；函数8故意清理失败返回错误 |
| 输出字节限额、完整取回、原SQL/公式状态不变 | 原编码/读取及递推实现；只加目标R核对 | 当前函数1/2/3/5完整数值/日期比较；原D3字节/最终fetch证据保留，消费者合同和41行新计量同步但旧节点未重跑 |
| 版本和统计迁移全部消费者 | kernel/MACD/KDJ2.0.0，其余算法1.0.0；locator_rows | 新结果断言、静态AST和旧字段/旧入口搜索；诊断保留原有界文件范围 |
| 只在本批预算内验收，不新增真实控制对象或扩大业务范围 | 本批plan/progress与测试私有State | execution_resume_01，22630输入/399477逻辑/29053键/0真实Control |

## 实际执行与计量

唯一程序执行原定9个明确节点：`9 passed in 5.60s`，外层程序5.919301499612629秒；含此前来源起点单元回归的累计6.1212099166586995秒，单程序30秒、累计300秒门槛均满足。没有失败重跑、没有扩大参数矩阵。

- 实际价格读取8983根；夹具（含21因子及2周线）5647根，新自定义参考8000根，共22630。
- 逻辑SQL399477＝服务调用369804＋夹具/参考29647＋21次关闭拒绝探针保守计量＋直接参数控制SQL5。
- 定位键29053；第二遍读取重复键如实计入，文件大小统计不冒充实际磁盘读取字节。
- 默认两页各1500；三套参数共2235；1600历史依次返回1000、600、空；长参数真实起点1600允许。
- 误差门槛为abs(actual-reference)≤1e−8＋1e−10×abs(reference)；日期、数量、NULL精确，首输入MACD严格0，近0单独记录。没有把初值误差预算冒充总体浮点保证。

`calls.root`记录run函数的root参数；显式config覆盖时实际来源由该config决定，例如长参数调用使用short目录。不能只凭该参数标签判断实际来源，实际1600源和选择结果已由相应用例断言。

临时目录已删除；真实计算连接关闭、执行器表/Arrow清单为空、定位和读取句柄关闭。故意注入清理错误的调用不报告成功；没有创建真实ExecutionControl、没有真实中断线程验收。

49份原D3报告和独立参考文件指纹保持；52份执行时源码/SQL/新测试指纹在运行前后相同。旧报告中关于1.0.0、38行SQL等保留为当时事实；当前消费者新计量41由原38加三个单行定位stage独立推导，不能把旧测试说成本轮重跑通过。

## 独立复核和边界

源码与测试经过两路独立只读复核，未发现本批剩余明确实现错误、验收遗漏或新增业务拍板项。CodeGraph精确核了读取_open_file及本请求服务/合同调用；实际源码确认Foundation边界未改变，没有正式App/Biz/XXM消费者迁移，没有安装、升级、配置初值或正式数据写入。

本批结论是临时Parquet、真实Arrow/DuckDB及完整库调用的有限正确性验收。原D4的并发/RSS/真实interrupt、正式Lake/API/页面接入、XXM和DG退出均未执行；当前5.92秒是整组验收程序耗时，不是单次生产请求延迟或整页性能承诺。下一步先按原LLD独立审计D4实施条件，本批不自动进入。管理员随后已要求提交；本批完成改动按明确文件清单提交，提交号以Git记录为准，不包含其他任务的改动。

## 末次静态核对

文档完整性、两HTML锚点与本批报告链接、60份Python语法、差异空白及49份旧D3/52份执行源码指纹核对通过。CodeGraph sync/status完成。仅静态核对和索引同步，未重跑任何产品用例。计入索引同步及本次末次核对后，累计程序时间6.653039秒，剩余293.346961秒；详细值见final_static_checks.json。
