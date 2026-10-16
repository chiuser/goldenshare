# Goldenshare Documentation Garden Report — B组代码级LLD（2026-10-16）

## Scope

用户要求审计当前计算内核并落档到代码级LLD。本次目标是将已确认的B组历史结构消失规则细化为可以逐函数实施、逐项验收的设计；未授权或执行产品编码。只更新原识别LLD、算法方案、预测方案和研究记录四份文档，不新增主方案体系。

主要成果：[原识别LLD新增§17.1—§17.12](/Users/congming/github/goldenshare/wealth/docs/pages/index-detail/index-detail-xxm-implementation-and-low-level-design-v0.1.md#xxm-bottom-history-code-lld)。规则B0已确认；新代码细化设计待用户Review，产品仍未实现，原页面三漏未修复。

## Authority and Evidence

- 当前源码：62个已审计文件的SHA清单见audit_before.json；没有以旧文档或研究wrapper代替产品实现。
- 已确认规则：原算法方案§12.10、识别LLD§16和预测方案§22。A组7/10同段循环及顶部疑报不在本轮。
- 历史预检：原B1的39747根、五处映射、356组预测和160次研究预算原样保留，不冒充本轮新验收。
- CodeGraph：search定位XxmCalculator／XxmResponseDto，explore核当前内核和schema，impact depth=2返回68个符号；含历史研究与测试，并非68个生产修改文件。继续核真实query／全部消费者，避免用模糊结果推断调用链。
- 人工边界：未确认的软件附加DIF、精确零柱／OHLC和寿命仍未知；本轮仅将已接受工作规则具体化，不称原软件公式已还原。

## Findings

### G1：原LLD模块级清单不足以直接指导逐函数编码

- Document：识别LLD§16。
- Evidence checked：types.py的三字段XxmStep、calculator的step／snapshot／restore、query的SeriesEntry及两处位置参数构造。
- Finding：未明确插入位置、类型命名、旧状态隔离和原构造方如何迁移。
- Impact：复制研究wrapper可能留下第二套引擎，或只修冷路径、漏掉增量和恢复。
- Suggested action：已在§17.2—§17.5规定内部bottom_histories、四字段step、私有方法签名、原普通／TOP先执行、底部优先级及创建顺序、先校验再赋值、两处关键字构造及容器复制；不修改产品。
- Human confirmation required：B组工作规则已确认；本次代码级设计待Review。

### G1：底部历史需在查询、响应和过去时点形成完整关联

- Document：识别LLD§16.4—§16.5。
- Evidence checked：_response、calculator_at、XxmResponseDto及前端byTime。
- Finding：响应末尾ENDED的记录仍可能被窗口前一根pending point合法引用；只看最终status会误拒绝。
- Impact：回看过去会泄漏未来，或原结构在窗口外时出现悬空ID、丢失绿字。
- Suggested action：§17.5—§17.6给出投影／选择helper签名、完整源柱龄公式、窗口并集、先前point时点引用条件及严格DTO拒绝规则；T06—T10覆盖。
- Human confirmation required：设计待Review，无新增业务规则。

### G1：当前前端只支持顶部历史，不能仅让后端多发BOTTOM事件

- Document：识别LLD§16.2及图层消费设计。
- Evidence checked：xxm/types.ts、adapter.ts、XxmLayerUi.tsx、primitive／geometry、两Workspace与hook。
- Finding：历史事件必须relatedTopHistoryId非空、eventLabel断言TOP；机械删“底”会将“底部结构消失”变成“部结构消失”。
- Impact：新事件会被当前adapter拒绝或显示错误文字。
- Suggested action：§17.8按方向分离集合及详情；新增BOTTOM历史专用图上“消失”，保留TOP原文字和已确认视觉；两个Workspace继续共用原hook。
- Human confirmation required：原视觉不变，新设计待Review；页面仍由用户验收。

### G1：原冻结测试把全部历史消失当成TOP统计

- Document：识别LLD测试门禁。
- Evidence checked：test_entire_frozen_ordinary_and_historical_baseline的旧manifest对照及末尾sum断言。
- Finding：新增BOTTOM事件后总数不再是旧TOP数量，不能改旧manifest合计来“通过”。
- Impact：既可能错误失败，也可能因放宽断言失去顶部回归保护。
- Suggested action：§17.10保留原普通及TOP断言，只给TOP统计增加方向限定；BOTTOM另核95条时点／原结构／低点，已有五处软件映射与其他90条无真值明确分开。
- Human confirmation required：无新业务决策；按T01—T16实施后仍需运行验证。

### G1：整页实际验收入口日期固定，且缺少底部真实adapter校验

- Document：识别LLD预算／混合门禁。
- Evidence checked：scripts/research/index_market/xxm_page_request_audit.py/.mjs及原xxm_request_reuse报告。
- Finding：当前mjs endDate固定2026-10-14；清单确为日线12／分钟13请求、16组306请求，已有真实TS客户端／调度和正式Reader，无需重造混合runner。
- Impact：新一轮可能因日期错位失败，或只证明HTTP成功而没证明底部数据可消费。
- Suggested action：§17.11规定受原鉴权保护的隔离审计上下文、每轮业务日期、真实图表输入和buildXxmViewModel、保留原306清单及最大耗时／共享缓存计量。仅为计划，不在本轮启动审计服务。
- Human confirmation required：新验收脚本设计待Review；不要求重配登录或读取其他进程密钥。

### G2：预测的“严格版本校验”需要按当前真实代码描述

- Document：预测方案§22、识别LLD消费清单。
- Evidence checked：forecast adapter rootKeys／forecastVersion／HASH校验和后端ForecastResponseDto。
- Finding：预测adapter固定v0.2及字段，但detectorSpecHash仅验证格式；精确新检测器身份需由API测试核实，不是已有的前端hash白名单。
- Impact：会误以为消费者已自动阻断所有旧检测器身份，或新增散落的硬编码配置。
- Suggested action：§17.1／§17.7和预测方案同步澄清；保持预测合同和数学，真实API断言返回新MAIN_SPEC，识别adapter使用唯一h1版本。
- Human confirmation required：不新增预测合同／配置；设计待Review。

## Checks Run

- 本次按源码审计全部相关生产／测试／验收入口，计划列出T01—T16的正反例与命令。
- 只读核对328份既有B1底部记录，拟定快照“原参照结束早于原段开始”不变量全部相容；不是重跑算法。
- 四份文档本轮差异、必需设计章节、14字段清单、所有本地链接／新锚点、V0.1末行C7、文档完整性及保护哈希结果见validation.json。

## Checks Not Run

未修改／运行新内核、API／前端测试、B2正式接口、预算、混合／双标签或页面。未安装、提交、推送、部署、启动服务或读写正式DB／Lake；旧B1成绩不作为本轮新结果。

## Maintenance Suggestions

Review重点为§17.4每根执行顺序、§17.5过去窗口引用、§17.6关联拒绝和§17.11新验收入口。通过后再按C1→C4完成唯一内核和全消费者原子迁移；新TOP／普通／预测差异或预算失败应回评审，不按日期打补丁。

## Residual Risk

原软件唯一公式仍未确认，7/10同段及顶部疑报未解决；60分钟B1首冷3.895秒余量较小。真实新DTO、共享LRU、正常鉴权HTTP、混合负载及用户页面必须实施后重新验收。架构仍Biz只读Foundation／Wealth经HTTP消费，无依赖矩阵变化。
