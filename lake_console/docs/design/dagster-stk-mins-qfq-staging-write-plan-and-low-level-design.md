# 股票分钟前复权与MACD/KDJ写入修正方案和LLD

<a id="report-attachment-cleanup-20261103"></a>

> 2026-11-03附件清理：相关恢复请求/响应、轮询、旧脚本和测试输出等过程附件已删除；下文旧附件清单、数量、命令和裸路径保留为当时记录，不表示文件仍存在，也不要求重跑任务。保留说明及最终结果，具体范围见[清理LLD20.17](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#2017-其余恢复过程附件的清理2026-11-03)。


> 2026-11-03恢复完成：11月2日股票分钟链及直接下游37项、八个原job和117项原检查全部通过，两次repair完整门槛ready，八条sensor已按原状态恢复。完整结果见21.13；较早“准备时/执行中”段落保留当时事实。

> 2026-11-03文档准备时：第21节是11月2日分钟链恢复执行LLD，对应MACD/KDJ方案第18节。状态为方案准备、待审阅和具体执行授权；本轮未改代码、未触发job、未调整sensor、未读取历史行情正文。下方10月各次完成记录保留当时事实。

> 2026-11-01附件精简：本页所引恢复过程附件已按管理员指令删除，相关链接转到对应README的清理说明；原数量、操作和历史结论保留，旧裸路径不表示文件仍存在。

> 2026-11-01报告精简：按管理员明确指令，五个恢复报告目录仅留必要最终结果和说明，过程附件删除，不再压缩另存。历史附件路径描述当时执行，已删除附件的链接改为对应README的清理说明。具体保留范围和验收见20.16；不因附件删除重跑补数、检查或审计。

> 2026-11-01收尾：30日股票分钟链37项和两次repair完成，五条sensor已恢复；普通指数日线剩余5项随后自动补齐。10月31日22:18的一次完整审计为180项中164项通过、16项按规则排除，无缺失、更新滞后或未核实。收尾只复用这些证据，不重新补数、审计或更改开关，执行和提交范围见20.15。下方29日和更早执行记录保留当时事实。

> 2026-10-30最新状态：MACD/KDJ读取修正方案`4a4a689e`及实现`5a0b13401`已提交，315项测试及23子测试通过（19.12）。原job只恢复29日1m的run`63c25bed-bdc8-4fee-9af8-0321b5b13ac7`SUCCESS，两物化/四检查通过，154.728秒（19.14），其他六频日更未重跑。随后按19.15新批准完成原2股七频历史repair，run`86d8b492-c056-412d-b9cc-551462e3188e`SUCCESS，14项completion通过，281.185秒；sensor已恢复RUNNING、原光标保留，无重复repair（19.16）。本轮不再改代码、不重算其他股票指标。第3—8节为早期背景，摘要次数以第9—10节和当前publication为准；第13—18节旧批准不覆盖新日期恢复。

日期：2026-10-24；读取优化及正式执行：2026-10-25。最新状态：22日七频QFQ及原28检查已完成（第13节）；因子repair读取/续跑身份修正完成，26项隔离回归通过，随后获准正常执行一次26股历史修复，七条真实检查及消费者门槛ready（第14.8节）。不再做性能样本或全局复审。此前样本失败及297项回归证据保留，不用旧阶段结论替代本次正式结果。

## 1. 目标、依据和边界

2026-10-24改造前，QFQ年度文件、MACD/KDJ年度文件及state文件都在正式目标旁写固定名称的临时文件，校验后替换。Git追溯分别保留自`b6d4125de`（6月2日）和`4ba74ece7`（6月7日），没有发现先改为staging后又回退的记录。该历史阶段修正的是写入安全与继续执行，不改公式、前复权因子日期、字段、频率、目标布局、日期选择、生产checks或调度策略。

依据：现行AGENTS、[性能治理§6.3](dagster-data-pipeline-performance-governance.md#63-批量写入必须有原子性和审计)、[QFQ治理LLD](dagster-stk-mins-qfq-validation-governance-low-level-design.md)、[MACD/KDJ方案](dagster-stk-mins-qfq-macd-kdj-indicators-plan.md)、[原股票分钟设计](dagster-stk-mins-asset-design.html)及[22日恢复说明](../../reports/datasets_recovery_20261022_20261024/README.md)。

硬口径：候选与完成记录只能放staging；本次调用的全部候选通过原有检查后才开始逐文件替换；同设备替换；保留失败现场；不删除正式数据、不备份、不用Kopia；已替换文件可核对后继续；存在冲突先停止，不自动覆盖；不能声称多个文件一起原子提交。

## 2. 当前代码和影响面

CodeGraph `explore`及两个`impact`已覆盖：

| 范围 | 当前落点 | 本次处理 |
| --- | --- | --- |
| QFQ写入 | `defs/stk_mins_qfq.py::write_gold_stk_mins_qfq_rows_to_year_files`及年度writer | 接入统一候选、校验、提升和逐文件记录，移除目标旁临时文件 |
| MACD/KDJ写入 | `defs/stk_mins_qfq_macd_kdj.py::write_gold_stk_mins_qfq_macd_kdj_rows`、年度与state writer | 同上；同次调用指标和state候选全部准备好后再提升 |
| 日常资产 | `defs/assets/stk_mins.py`、`defs/assets/stk_mins_qfq_macd_kdj.py` | 将当前run的身份传入写入层；重新执行沿用root run身份，同一输入才能续跑 |
| 其他调用方 | QFQ因子修复、QFQ history/derived/canonical history、MACD/KDJ repair/history、北交所recursive candidates | 均经同一写入层；旧参数调用仍可用，每次生成独立身份和持久记录；显式传相同身份才能复用该次完成记录，不自动接管别的运行 |
| 新内部文件 | `defs/io/stk_mins_qfq_publication.py` | 只负责这两类文件的staging、锁、输入绑定、逐文件记录和提升，不创建新资产、数据库表或服务 |
| 下游和外部 | 九转、资产checks、readiness、catalog、sensor；无Web/API直接调用writer | 保留原数据与返回值合同；原正式checks仍须执行，候选检查不代替它们 |

已有板块候选helper只有路径与同设备检查，没有本次所需的输入绑定、逐文件记录、替换后退出核对；资金流helper绑定其专用数据集和合同。北交所恢复使用独立候选根及其自身专项清单；不能将它的对象限定和恢复授权套给日常全市场。因此不直接套用这些入口，也不另造一条计算链；只在两条共用writer之下增加本次所需的文件处理。

## 3. LLD：输入、目录和并发

1. 底层两个公共写入函数增加内部可选`publication_id`；原调用参数、返回数据、job/CLI输入不改。日常native、derived及MACD/KDJ wrapper传递同一run身份；根run身份只作文件继续执行依据，不进入run key或业务日期。
2. 正式目标仍在`/Volumes/datasource/data_lake/gold`，执行目录位于`/Volumes/datasource/data_lake_staging/stk_mins_qfq/<family>/.../run_id=<身份摘要>/scope=<频率和日期摘要>`。路径不直接拼入外部身份文本。针对staging内已有专项候选根，候选和本次记录继续留在staging，不提升到正式Lake之外的目标；测试只允许系统临时目录，禁止任意移动盘根。
3. 不新增环境变量、Settings、数据库或运营配置。复用`paths.py`两个正式根。临时测试根使用同级独立staging；禁止符号链接和路径逃逸，正式根/staging须已存在，不私自创建挂载根。
4. 同目标根、资产族、频率共用一个非阻塞文件锁，覆盖不同日期的年度文件写入；不在正式Lake放锁。不自动等待或删除别人的锁文件。锁随进程退出释放。已有未改造进程须在正式执行前确认不活动。
5. QFQ先沿用原SQL生成replacement表并做原日期、频率、重复键检查；MACD/KDJ沿用原公式生成指标/state replacement表。用DuckDB按稳定主键排序将这些表冻结到本次staging，计算文件摘要；不把明细拉进Python。相同身份重试时输入摘要、目标集合、范围和版本必须一致，否则在写正式文件前停止。每次冻结使用独立attempt目录，保留失败文件。

## 4. LLD：文件生成、提升和继续

1. 先登记本次完整目标集合；年度目标按原SQL保留非本次日期的记录，state scoped repair继续保留未受影响股票，禁止改变现行日期/对象合并逻辑。
2. 每个文件开始前记下正式目标的设备、inode、大小、mtime/ctime；生成独立候选，沿用现行候选validator、schema投影与行数核对。候选失败保留，不再由validator自动删除。
3. 逐文件JSON记录`building/validated/promoting/promoted`、目标、候选、原目标身份、候选摘要/大小/行数。记录先写本次独立临时JSON，再原子替换并flush；候选与正式目标提升前确认同设备，候选文件flush。
4. 首次正式替换前，确认本次所有目标都有已校验候选或已核实的完成记录；核对候选摘要、原目标未变化及同设备。任何一项失败，尚未开始提升的这次调用不得修改正式文件。
5. 逐文件先保存`promoting`，再`os.replace(candidate,target)`，读回目标文件摘要并保存`promoted`。已替换文件不因后续失败回滚；不能声称全批原子。每个文件替换前再次核对目标与候选身份。
6. 继续执行时，`promoted`须核对实际目标摘要；若退出在替换与完成记录之间，只有`promoting`且目标摘要等于已校验候选时才能确认已完成。否则原目标必须仍匹配，候选完整且匹配时才继续；目标被外部改写、候选损坏、记录不完整或输入变化一律拒绝。已有完成文件复用记录中的行数，不重写年度文件。
7. 新run不自动接管另一身份。日常重新执行沿用root run，但输入变了仍会拒绝；需要重算新输入时使用新的独立run，先查清旧次部分完成事实。不自动清理候选、记录或历史临时文件，不补runless绿事件。
8. 写入层记录候选完成量、目标总量、提升完成量、当前目标和执行目录；按实际文件完成量输出阶段进度，最长约30秒更新一次（单文件不可分割操作除外），阶段开始/结束强制输出。不用心跳冒充业务进度，不估造ETA。

## 5. 性能和读写预算

代码开发只用隔离夹具；本步真实来源请求、Prod访问、正式Lake数据扫描与写入均为0。夹具限定2只股票、2年、少量日期与分钟，覆盖7频公式金样本；新增故障测试单次不超过4个正式目标，临时资源小于64MiB。

| 项目 | 开发/正式执行前约束 |
| --- | --- |
| 日期/对象/频率 | 代码支持原调用范围，不扩大；22日正式补齐按7/14项分开且逐频率，真实代码/文件数由该批预检补齐 |
| 来源 | 不新增HTTP/SQL请求，不改来源；21日已保存参考：1m当天1,341,888行、5,568代码，只作规模参考，不作为22日必须相等的数字 |
| 明细内存 | 沿用DuckDB表/列式COPY；Python只保留目标清单、计数、路径、摘要与逐文件记录，不承载行情明细 |
| 新增扫描/写入 | 每次调用额外冻结replacement表一次；年度候选仍合并对应旧年度文件；候选哈希、提升前校验与目标读回均计入预算，不重算公式检查 |
| 候选空间 | 本次调用所有受影响年度候选及state需同时保留；正式执行前统计受影响文件大小，并预留旧目标合计+新增行估算+冻结输入+20%余量，不只按单日文件估计。写入层以待重新生成目标大小及输入冻结大小的120%加64MiB保留量检查，逐文件仍保留64MiB；继续时已有候选或已提升文件不再按整年重复预留空间。此为内部安全检查，没有新增运营配置；不足停止并保留现场 |
| checkpoint | 每文件一份JSON，避免每完成一个文件重写整批大清单；完整目标清单仅写一次；每文件原子替换与fsync |
| 中断继续 | 重新冻结本次输入，核对摘要；完成文件各读回摘要一次，未完成候选只按对应记录验证，已完成年度文件不COPY；不重新审计全库 |
| 最后验收 | 复用正式checks，只对本次目标汇总计数/日期覆盖；非22日记录保留由SQL合并及独立夹具证明，必要物理对账限受影响年度文件一次，列明成本后执行 |
| 耗时和拒绝 | 不凭旧样本承诺全市场耗时。隔离正确性测试预期分钟级，正式每频率先测真实有界样本，再据实际文件/字节数填预算；未测清、空间不足、候选冲突或存在活动writer时不启动全市场 |

本轮不获准全历史明细读取。正式22日计算所需受影响年度文件读取与重写必须按已批准单日目标说明精确范围和成本；若构成数据集全局读取，依根AGENTS单独取得批准，不能拆成频率批次绕过。

## 6. 测试与验收对应

| 硬口径 | 代码点 | 必须有的独立验证 |
| --- | --- | --- |
| 不写正式旁临时文件 | publication路径、两类writer | 捕获COPY目标均在隔离staging，静态阻止旧临时路径回流；实际原writer集成调用 |
| 全候选通过再开始替换 | 完整目标集合+提升预检 | 第2个候选失败时第1个正式目标仍不变，失败候选保留 |
| 同设备、路径与单writer | 路径校验+flock+提升检查 | 链接、越界、跨设备、并发写入反例；合法staging候选根正例 |
| 只改指定日期/股票 | 原SQL+不变的schema与公式 | 独立字面样本验证其他日期、其他股票state不变；原QFQ与MACD金样本回归 |
| 中断后继续 | 逐文件记录+实际摘要 | 完成1文件后异常、替换后记录前异常、进程退出释放锁；继续不改已完成文件mtime/inode |
| 冲突拒绝且正常重试可行 | 输入绑定+目标/候选核对 | 输入变化、外部目标变化、候选损坏、记录篡改反例；同输入幂等正例 |
| 原调用方语义不变 | 两个公共函数与资产wrapper | native/derived资产、因子repair、MACD scoped repair/history与BSE候选调用的相关隔离回归；不弱化或过滤失败 |

先执行新增测试、两类金样本、年度合并、native/derived与MACD写入测试，再跑受影响repair/history与静态门禁；全部通过后按本次授权进入数据恢复，不把隔离通过写成正式验收。任何真实合同冲突先停止说明。

### 6.1 真实只读样本与隔离写出验收

隔离回归通过后，补一次真实字段和既有结果核对：只读`600000.SH`、60分钟、2026年QFQ文件中10月20/21日各最多10行、20/21日state同代码各最多2行、21日MACD/KDJ同代码最多10行。使用当前schema显式投影，源文件仅4个，每个不超过32MiB；先核对字段类型和计数，超限停止。最多34行进入隔离输出，不扫描其他代码或年份，不连接数据库、Dagster instance或源接口。

将20日QFQ和state的上述记录复制到`/private/tmp`独立目录，调用改后的原QFQ writer合入21日；再调用改后的MACD/KDJ writer生成21日指标/state。只在临时目录写文件、候选及完成记录，复用统一DuckDB连接，内存128MiB、单线程、临时目录同样隔离；预期少于60秒，输出预算16MiB，源文件stat前后应一致。

验收以正式已保存的20/21日QFQ及21日指标/state为独立依据：QFQ非替换日和新增日记录完全相等，指标/state分别核对字段、主键、行数和数值（浮点绝对容差1e-10、相对容差1e-12）；相同身份重放后输出文件inode/mtime不变。原公式金样本仍必须通过。此项证明真实生产者字段与新写入链衔接，不作为22日全市场正式执行通过。

## 7. 数据恢复衔接和授权

两条代码修正通过后，仍沿用22日说明第13节的11批顺序。本次管理员“先修复这两条，然后再进行数据补齐”已授权按该范围继续，不因人为分批重复请求同一授权；每批仍需完整代码审计、当前前提、具体命令、性能预算和验收记录，不能从本方案直接跳到全市场运行。已有主要指数39项不重跑；只在对应批次读写22日范围，Prod写入按既定目标，不扩大。新的全局明细读取、数据删除、装包和额外代码修正仍不在本次授权内。

## 8. 执行与验收记录

### 2026-10-25 正式股票链恢复的执行前范围校准

股票Raw/Silver十项已通过原35项checks，下一步仍沿原批次先成交额再QFQ。成交额只读22日6文件，具体Prod五行事务写入、重复读取预算和执行卡在[22日恢复说明第31节](../../reports/datasets_recovery_20261022_20261024/README.md#31-成交额gold及prod发布方案lld和执行卡)。它不改本文件两条writer。

该时点曾提出39144份/7.518GiB目录统计及三次SHA的粗预算，但未证明逐遍必要性，也没有完整计入其他查询；这一申请现已撤回，不可作为执行依据。管理员暂停修复后要求先审计整链，并确定正常只保留一次年度SHA；详见第9节。实际目标尚未冻结，目录统计不等于正式目标清单。没有批准2025 QFQ、历史factor或任何年度全局内容读取。

MACD的2025+2026源及2026指标年度合并、分钟九转两年源及可能所有年份fallback另行审批；尤其九转当前LAG在目标日过滤前运行，不能用其他日线路径的20日常量替代实际读取范围。此次仅补方案/LLD和执行预算，不新增或修改正式Python、配置或公式。

### 8.1 代码与约束对账

- 新增`defs/io/stk_mins_qfq_publication.py`；两个原公共writer接入，三个私有年度/state writer只生成并校验候选，统一完成后再逐文件提升。旧`_temp_path_for`和候选失败自动删除已移除。
- `defs/assets/stk_mins.py`的native/derived writer及`defs/assets/stk_mins_qfq_macd_kdj.py`传入`context.run.root_run_id or context.run.run_id`。已核对现有Dagster1.13.26本地实现及Context7文档，使用当前`context.run`属性，不新增run config、run key或用户开关。
- 第6节硬口径均有新增正反测试；原非目标日期保留、scoped state合并、公式、因子repair、history/derived/BSE入口保持原回归。CodeGraph explore/impact覆盖共享调用方与下游；修改后完成`codegraph sync`和`status`，未涉及跨子系统依赖或前端/API契约修改。
- 候选路径、完成记录、锁、冻结输入都只在staging（隔离验收为临时目录）；正式Gold布局、asset/job/check名称、字段与业务计算不变。没有修改Prod定义/执行器或源合同。

### 8.2 隔离测试

从`lake_console/orchestrator`使用现有`.venv/bin/python -B -m pytest -q --tb=short`执行以下15个文件，最终**263 passed、70 subtests passed，21.97秒**。[完整日志（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)：

```text
tests/test_stk_mins_qfq_staging_publication.py
tests/test_stk_mins_qfq_m8a_assets.py
tests/test_stk_mins_qfq_m11_derived_assets.py
tests/test_stk_mins_qfq_m12_macd_kdj.py
tests/test_stk_mins_qfq_formula_golden_contracts.py
tests/test_stk_mins_qfq_macd_kdj_formula_golden_contracts.py
tests/test_stk_mins_qfq_partition_rewrite.py
tests/test_stk_mins_qfq_m9c_factor_repair.py
tests/test_stk_mins_qfq_macd_kdj_repair_op_contracts.py
tests/test_stk_mins_qfq_m8c_history.py
tests/test_stk_mins_qfq_m11f_derived_history.py
tests/test_stk_mins_bse_recursive_recovery.py
tests/test_run_contract_static_gates.py
tests/test_stk_mins_qfq_macd_kdj_check_contracts.py
tests/test_stk_mins_qfq_m9a_job_contracts.py
```

包括真实子进程在替换后`os._exit(17)`、锁释放、前后两个中断位置、完整候选门禁、同身份幂等、输入/目标/候选冲突、跨设备、符号链接、空间不足、完成后不重复预留年度副本，以及真实两个writer的Parquet合并与MACD/state配套生成。设备故障测试仅替换设备观察，公式/Parquet集成没有替身。

初次新增测试有两处验证代码错误，已按独立依据纠正：指标表应查询`trade_date/macd_dif_qfq`，不能沿用行情表的`close`；常量收盘价的DIF理论为0，但DOUBLE递推允许1e-12舍入误差。未修改生产公式、既有金样本、跳过或过滤失败。最终完整回归重新执行通过，不能引用早先失败运行作为通过证据。

新增写入文件、两个核心writer及新增测试的默认Ruff通过；全`src/tests`致命错误基线通过。两个修改的asset文件默认Ruff仍有原有7项和2项问题，逐项与HEAD比较一致，没有新增；本次不夹带时间解析等无关修改。`git diff --check`和仓库文档完整性检查通过。无安装、无新分支/worktree、无提交。

### 8.3 真实只读样本与隔离写出

2026-10-24 15:41:41（北京时间），按§6.1执行[有界核验脚本（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)。[结果（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)、[日志（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)：

- `600000.SH`、60分钟，20日4行QFQ、21日4行QFQ、20日1行state作为输入；独立比对正式21日4行指标和1行state，共14行有界事实。
- 真实源schema与当前合同一致；改后QFQ保留20日并合入21日，记录完全一致；MACD/KDJ和state与已有正式21日结果的最大绝对差均为0。
- 相同身份再次执行，隔离输出inode/mtime不变。4个正式来源文件合计577,907字节，stat前后未变化；计算及写出0.140秒，隔离输出小于16MiB。
- 所有输出只在`/private/tmp/dg_qfq_staging_real_sample_sq68mnk8`，没有正式Lake、Prod或Dagster写入，也没有数据库/instance连接。这是边界验收，不代表22日全市场已经补齐。

### 8.4 补齐预检及当前停点

随后按既定批次1做必要预检，[报告（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)：目标4个文件及同日物化均缺失，分区已注册、相关job无活动run、daemon未运行、staging同设备且扩展已安装。但Prod `core_serving.index_daily_serving`在22日、DG登记820代码范围内为0行，820个代码都缺失，Raw不能通过当前完整性门禁。

静态审计同时确认`defs/assets/index_daily.py::_replace_parquet_from_query`（Silver入口）和`defs/assets/market_major_indices.py::_replace_parquet_from_query`（主要指数日线Gold入口）仍在正式目标旁生成`.tmp`。它们不属于本次获准修正的两条股票写入链，没有擅自扩大修改。

因此本轮未启动任何补数job/check、sensor、backfill或runless event，未修改Prod/Lake正式数据。按AGENTS“发现计划与当前实现/真实数据冲突先说明、等待确认”停下；不是把隔离通过当作整个批次可执行。来源补齐与两处日线写入的后续建议见[恢复说明第14节](../../reports/datasets_recovery_20261022_20261024/README.md#14-两条股票写入修正结果与补齐预检停点)。

## 9. 前复权整链读取审计与优化方案（2026-10-25）

### 9.1 授权、范围与证据

前一轮已完成代码和已有证据审计；正常完整年度SHA保留1次，另2次不批准。管理员随后指令“按照方案推进吧，先完成开发，然后做测试”，本轮据此实施本节全部读取合并及共用publication修正，并用隔离人工数据测试。禁止读取正式Lake/数据库/instance作测试，禁止正式job/check、候选/正式数据写入及补数。旧的三遍摘要年度读取申请已撤回；年度内容读取和真实样本仍需后续单独审批。

范围是`stock_mins_qfq_daily_update_job[2026-10-22]`的7个QFQ资产与28个blocking结果：当日输入→诊断/因子覆盖→生成replacement→旧年度合并→候选校验→摘要与提升→正式检查→中断继续。公式、字段、因子日期、窗口、股票集合、文件布局、名称、check语义和调度入口不变。MACD/九转年度数据不在执行范围。

入口边界也纳入审计：`jobs/stock_mins_qfq_daily_update.py:6–15`的手动job不调用daily sensor、readiness、factor repair或history；这些入口若单独运行，会产生自己的读取，不能含糊并入本次预算。尤其`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py:454–457`监听本job成功，可能在独立sensor评估后请求MACD下游。不能只因是手动启动就承诺没有后续自动任务；本轮未读正式instance，旧预检daemon未运行只代表当时。

后续补数前必须只读核清相关daemon/sensor及活动run，确认成功后不会越权启动未批准的MACD/其他链；若需暂停或恢复自动化，先获得该具体状态变更授权，不能自行启停。日常sensor/readiness的窗口巡检、factor repair和history不得为本次验收额外调用；若要执行，应独立列范围/次数/预算。共用SQL builder的这些消费者须回归语义，本方案不顺便改它们的读取策略。

| 独立入口及代码依据 | 已审计的读取范围/触发 | 本次如何处理 |
| --- | --- | --- |
| QFQ daily sensor，`stock_mins_qfq_daily_sensor.py:524–611` | 19:30后最近5个预期交易日的Silver→factor→Gold readiness | 不执行；tick次数和日期集合另计，不能算进一次job |
| batch readiness，`stk_mins_lake_readiness.py:1196/1662/2437/3123–3229` | 调用方日期集合的来源、factor、股票年度Gold；跨年会加年份 | 有独立SQL，不自动享受check合并。接口和逐交易日factor匹配保留，不改`match_as_of_by_trade_date=True` |
| factor repair sensor，`:527–574`及`stk_mins_qfq_factor_repair.py:108–349` | 最近10日门禁；因子变化后可读变化股票自历史起点至目标日的来源/factor/多个年度 | 不启动修复；仅回归共用writer，真实修复另列对象/历史范围/预算 |
| native/derived history，`bootstrap/stk_mins_qfq_history.py:161–255`、`stk_mins_qfq_derived_history.py:278–329/721–741` | 指定历史日期/年份；默认起点2014-01-01，不能当单日自动补缺 | 不运行；不得用“初始化”绕过现有目标冲突与历史审批 |
| MACD run-status sensor，`:200–225/454–457`；九转sensor，`stk_mins_qfq_nineturn_sensor.py:416` | 可独立做目标日/专用批量readiness，并在满足条件后请求下游 | 只登记影响面；当前启用状态未实查，执行前必须核清 |

单日readiness还直接消费checks中的expected paths/schema/Parquet/row-count helper和两个minute_qfq SQL。应保留这些接口及原含义，新check只在内部复用准备好的关系；若实施需要改签名/删除，先补全部消费者迁移和回归，不能让批量readiness偷换成单日算法。34/9只针对已定义的手动单日job；以上额外入口未获执行授权，不能声称已优化或无需成本。

代码依据：`assets/stk_mins.py:2330–2714`；`stk_mins_qfq.py:170/260/373/1302–1653`；`io/stk_mins_qfq_publication.py:20–379`；`checks/stk_mins_checks.py:357–570/1076–1418`；`stock_factor_price_checks.py:193–316`；`duckdb_connection.py:48–146`及相关真实writer/公式/恢复测试。CodeGraph explore/impact已追到日常入口、共用writer、SQL builder、publication和checks；构造调用再由源码确认QFQ与MACD两处，不能把CodeGraph未列出调用者解释成不存在消费者。

已有证据只支持：

- `resume_20261025/annual-file-metadata-budget.json`是目录/stat统计，未读内容、未按本次股票过滤：每频5592份旧2026文件，七频39144份，8072911121字节，即7.518484GiB。它是背景预算，不是实际受影响S，也不是候选C。
- `stock_resume_20261025/batch7-final.json`及`turnover-preflight.json`证明22日五份Silver文件去重总31019357字节。当前`CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET`为1←1、5←1、15←5、30←5、60←30、90←30、120←60；每个asset独立读取来源，七频单阶段须按重复来源计57243552字节（54.59MiB），不能用去重文件总量或只补90/120的32996152字节替代。原生五目标的来源合计55266757字节。每份Silver均5570代码，但最终QFQ目标仍由现行replacement/身份SQL确定，不能据数量猜目标名单。
- 先前`qfq-staging-real-sample-verified.json`只覆盖600000.SH/60分钟极小隔离样本。没有全量候选体积、列压缩字节或实际扫描量，不能用0.140秒外推全市场，也不能按11列中的几列直接等比例打折。

### 9.2 逐项裁定

| 步骤与当前代码 | 必须保留的含义 | 本轮方案 |
| --- | --- | --- |
| 日来源多次查询；因子分子/分母两路参数实际同一路径 | 原日期/频率/时刻/值域/重复键诊断、同日因子覆盖、关联行数和两种因子计算 | 每个asset单连接分别读来源与因子各1次到TEMP；所有诊断与计算复用。不得先过滤坏行，也不得把倍率擅自简化为1 |
| `_canonical_qfq_source_audit`另执行完整select求generated count，writer又执行同select | 窗口完整性及生成数量 | replacement只算1次；generated count从实际replacement取得；诊断、metadata及拒绝条件不变 |
| `_validate_replacement_rows`多次查询 | 非空、空键、频率、允许日期、重复键 | 保留，在已存在TEMP上合并聚合；不回读来源 |
| `publication.bind`冻结当日replacement并算摘要 | 同输入/范围/目标才能续跑 | 保留一次小型冻结与摘要；它不是年度SHA，单独记P，不省略预算 |
| 旧年度3列范围检查后，又全11列合并读取 | 在删旧22日前发现freq/code/year错误；保留其他日期原值 | 每次只载入一个股票年度TEMP一次，先按原规则校验，再从同表过滤旧22日并COPY；不直接删除检查 |
| 候选范围检查、全年duplicate、独立count分开读文件 | 实际候选可读、范围正确、全年无重复、实际行数 | 候选4列一次读取到TEMP，所有计数复用；不以计划行数冒充候选行数 |
| `validated()`首次年度SHA | 为跨进程复用保存内容依据，不证明公式正确 | 正常保留1次；摘要前后核同一文件身份 |
| `_verify_candidate()`在正常提升前再SHA | 检查等待期间变化 | 删除完整内容重读；把候选身份核对放入全体预检，并保留逐文件核对 |
| `os.replace()`后再SHA | 核正式路径对应候选 | 删除完整内容重读；核同设备、文件号、大小、mtime连续，允许rename引起ctime合法变化 |
| 正式28检查分别求年度counts、日identity及失败样本 | 当前正式文件与当前来源一致，独立运行检查仍有效 | 保留7个multi-check各4结果；每个check内部复用年度读取与日TEMP，不复用asset内存或写前结果 |
| 成功后再次跑全局物理/公式审计 | 本轮没有这样的额外需求 | 不加入方案；复用原28检查，仅核本run/目标清单/完成记录和小型汇总 |
| 中断时同文件先在candidate中SHA，promote中又SHA | 跨进程确认实际复用内容 | 仅对选定复用路径SHA一次；本进程以后只核身份，重建文件按正常一次SHA处理 |

年度合并仍读取其他日期的原记录并重写该年度文件；不重算其他日期前复权。减少校验读取不会把7.5GiB年度文件变成单日大小。

### 9.3 实现落点与连接生命周期

1. 日常asset的来源、因子、replacement使用同一个DuckDB连接。当前公开路径型SQL builder委托同一套内部关系型SQL生成逻辑，路径入口仍可用；不得在asset里用字符串替换SQL路径，不另写一套公式。内部接受TEMP关系时保留生产者schema/CAST/NULL/重复行语义。现有history/repair调用继续复用同一核心，不能因重构丢失已完成的staging修正。
   共用writer必须保留原加锁边界：先归一化并检查freq/日期、取得同频率publication锁，才执行replacement SQL。部分历史/修复入口的replacement会读取正式QFQ，不能先读后拿锁。日常来源诊断仍先于replacement计算；generated count改取实际表，不改变原异常先后顺序。内部写入函数接收当前持锁的publication和连接，不再自行创建另一份publication。
2. 旧年度每次只保留一个股票年度表；不能一次载入全频/全年全市场。旧范围校验在过滤任何替换日之前执行，包含将被替换的旧22日；合并继续使用原11列、日期和排序规则。应核对预加载/CAST时机，不得提前过滤非法数据或掩盖旧错误。
3. 候选一次载入`freq/ts_code/trade_date/trade_time`，在该TEMP上求范围、全年dup和count，完成后释放。所有校验须作用于真正写出的候选，不以写入前TEMP替代。
4. 正式multi-check独立连接：当日Silver/因子各读1次，来源期望只生成1次；按已确认expected paths逐个载入正式年度所需列和原filename。每个年度只读1次，计算非目标日路径错误，并将目标日完整检查所需行追加到本check日TEMP，随即释放年度表；日TEMP上求全局重复键、价格、行数、identity/交易所及样本。不能逐文件求日dup再相加，否则漏掉跨文件重复。
5. 全年路径错误与目标日错误必须按原OR条件每行只计一次：非目标日部分与日TEMP部分分开统计，NULL按原SQL三值逻辑处理，不重复加总。path样本仍按`filename/trade_date/trade_time`排序取全局前5；dup/price样本保留原排序/列/限制。失败样本来自本轮TEMP，不再为LIMIT5重扫年度文件。
6. 原schema helper及失败分支保留。现行数据关系是`union_by_name=true,filename=true`，schema检查是`union_by_name=false`；逐文件投影须先按原联合schema语义处理缺列/类型提升/NULL。独立异构schema夹具若不能证明等价，该优化不得上线，不能把异常改成跳过或不同计数。
7. 不跨asset/check传TEMP、缓存或写前检查结果；不新增summary资产、状态表、运营开关或持久化检查事实。输入前后stat、现有replacement摘要和本run目标绑定继续核对，不能只因缓存命中就放行。

### 9.4 正常一次摘要和继续执行LLD

正常路径：候选业务校验→一次SHA（前后完整identity不变）→保存原receipt→全体候选/已完成项核对→逐文件核对及同盘replace→正式路径身份核对→保存promoted。identity仍为dev/inode/size/mtime_ns/ctime_ns；rename后稳定对应dev/inode/size/mtime，ctime允许合法改变并记录本进程的新身份。目标文件系统是否提供该身份保证，必须用以后获准的隔离小文件测试验证，不能凭平台名假定。

跨进程继续先核receipt路径、status、字段、输入摘要及目标清单；选择唯一复用路径，再SHA一次，前后完整identity须稳定：

| 状态 | 继续规则 |
| --- | --- |
| building | 未完成候选不复用；原目标仍匹配before才重建，失败现场保留 |
| validated | 目标仍为before、候选匹配原身份，选候选一次SHA |
| promoting | 候选仍在且目标仍为before，选候选；候选不在且正式目标稳定4字段对应原候选，选正式目标。不能唯一判断就停，不先读旧目标再试候选 |
| promoted | 只读实际正式目标一次SHA；本进程后续用其已验证身份，不再次SHA |

本进程复用记录须同时绑定target、实际path、sha256、row_count、candidate_identity、before、完整当前identity；重读小JSON时内容须匹配，由本进程推动的status变化同步更新。不能只缓存target→identity。全体预检必须涵盖所有候选和已完成项，最后一个候选有问题时第一个正式目标仍不能被修改。

沿用现有receipt字段和目录，无须新增版本、promoted_identity或迁移旧receipt；旧receipt按同一规则校验，不能换新scope目录忽略旧半完成操作。损坏/缺关键字段/路径冲突/未知状态均停止；receipt丢失而无法证明尚未开始时需现场核查，本方案不宣称解决任意完成记录丢失。一次继续不自动接管其他root_run_id。

`StkMinsQfqPublication`也被MACD年度/state使用。采用一个统一的减重复读取机制，不添加“QFQ一遍、MACD旧三遍”的分支；因此通用提升/恢复代码和MACD相关隔离测试也属于影响面。MACD公式、源读取与业务writer不改，不因此取得MACD数据读取/重算授权。后续实施须明确承接这个共享影响面。

### 9.5 临时数据和现有连接策略审计

TEMP并不天然免费。为使本次按日QFQ预算不藏入未知spill，拟在本次日常asset/check连接显式复用现有`temp_policy="existing_no_spill"`，仅内存TEMP；每次最多保留一个股票年度/候选和本频当日表。若内存不足即失败并保留现场，禁止自动改回managed或扩大临时空间。

| 配置/策略 | 当前来源与默认 | 本方案作用范围与生效 | 边界/验收 |
| --- | --- | --- | --- |
| temp_policy | `duckdb_connection.py`函数参数，默认managed；不持久化、不来自env/DB | 仅重构后的按日QFQ asset/check连接显式选既有existing_no_spill | 不改全局默认；历史/repair连接不随意切换 |
| max_temp_directory_size | Settings默认512GB，既有no-spill策略覆盖0B | 本次QFQ连接0B，现有设置验证函数核对 | 512GB是容量，不是获准I/O预算；不得把它暗算进总量 |
| memory_limit/threads | 现有Settings的16GB/4 | 保持字面设置；单频单连接、年度逐文件释放 | 隔离年度样本证明工作集可承受；OOM不能忽略 |
| temp_directory及扩展 | 既有卷路径；no-spill要求目录已在且无符号链接，并禁自动装载/安装扩展 | 不新建/换根，不安装依赖 | 仍允许获准的显式候选COPY；不是只读开关 |

该策略已被资金流候选/检查/续跑、股票周期、停牌/因子/daily_basic历史工具使用；本轮不改这些消费者或连接helper。这里只计划增加QFQ两个连接使用点，不新增配置项。若需要改Settings、默认值或其他消费者，超出本方案，应先停下另做配置与影响面审计。

### 9.6 正常总读取、写入和空间测算

以下是“每个独立文件读取步骤最多按完整文件大小计一次”的保守文件预算；不按投影列数比例、不按缓存折扣。它不是已经测得的硬盘字节，系统预读/文件系统内部写放大也不能靠代码算成精确值。

- S：本次实际受影响的旧年度文件总大小；新目标无旧文件时该项为0。
- C：本次完整新年度候选总大小；目前未知。
- D：按当前七目标→来源映射、重复计入各asset输入，共57243552字节；D5为五个原生目标的55266757字节。去重五Silver总量31019357字节只作背景，不代替D。
- A：单份22日因子文件大小；P：七频冻结replacement合计。
- Fr/Fw：额外footer/schema/receipt/操作记录/日志等读写预留；Tr/Tw：引擎临时文件读写。

按上述方案，不跨步骤隐藏读取：

```text
当前正常读取预算 = 2S + 8C + 7D + D5 + 70A + P + Fr + Tr
优化正常读取预算 = S + 3C + 2D + 14A + P + Fr + Tr
显式文件写入预算 = C + P + Fw + Tw
```

当前式将各独立查询/两路factor文件入口分别计费，CTE/列裁剪可能减少实际读取，但不用于打折。优化式的S是旧年度校验/合并共用一次；3C分别是候选一次投影检查、年度一次完整SHA、正式一次投影检查；2D和14A分别为7个asset及7个正式multi-check独立加载。P含一次冻结后摘要读取。rename不再写一遍C。新设计选no-spill后Tr/Tw必须为0，否则不能使用本预算。

已有材料缺少实际S/C/A/P及列压缩字节，不能给出“实测总量”。可以给出可核算、尚待样本验证的执行预算条件：

| 项目 | 本次讨论预算条件 | 证据/性质 |
| --- | --- | --- |
| S | 暂用7.518484GiB | 旧目录统计；执行前按实际目标/stat重算，不作当前精确值 |
| C | 暂预留8GiB | 估算条件，非实测；超过就重算/重新审议，不自动扩大 |
| A | 单因子文件预留16MiB，14次共224MiB | 未取得实际字节，采用明确预算额度，前置stat校准 |
| P | 七频冻结合计预留128MiB | 未生成；不是用极小旧样本外推的结论 |
| Fr/Fw | 累计额外读取1GiB、写入512MiB | 为数万footer及四次逐文件receipt写入留量；不能把receipt只按最后保留一份计累计写入 |
| Tr/Tw | 0 | 仅在no-spill实现及隔离验证通过时成立 |

代入：读取32.968859GiB，写入8.625GiB；向上留量为**正常一轮34GiB读取、9GiB写入，额外空闲空间12GiB**。12GiB包含候选/P/记录及20%余量，不包含早已占用的正式旧文件。若以C≈S作规模参考，则相同额外预留下约31.524GiB读取、8.143GiB写入；这仍是保守测算，不是实测预计I/O。初步来源估算曾只重复计90/120，漏掉5/15/30/60规范化来源复用，已在本节按实际映射纠正；不能用向上取整掩盖漏项。

仅年度大文件部分，在S≈C≈7.518GiB时，现代码按独立查询计费约75.185GiB（2S+8C），拟优化后约30.074GiB（S+3C）。其中SHA从3C降C，约22.555→7.518GiB；其余节省来自合并重复读取。不能把“合并+一次SHA”约15GiB当整链总量，也不能把34GiB与旧22.6GiB直接比较，旧22.6只包含摘要。

这些预算尚未成为配置或代码硬门禁，也不是读取授权。后续实现必须证明读取次数、no-spill、文件/记录预算可观察并能在下一频率/提升前停止；若实际S/C/A/P/元数据超过条件，先暂停重新算，不沿用34/9/12数字执行。仅有当前三遍代码时禁止用优化预算申请或运行。

### 9.7 中断、继续与最后验收的预算

设R为本次实际复用的完整候选/正式文件合计，Sb/Cb为需要重新生成部分的旧/新年度大小，Ca为最终需要检查的全部年度输出：

```text
一次继续的年度读取 = Sb + 2Cb + R + Ca
                       = Sb + Cb + 2Ca （当Ca=Cb+R）
一次继续的年度写入 = Cb
```

再加本次来源/因子/冻结P、Fr/Fw；Tr/Tw仍须0。R每文件仅一次SHA，不能读一次候选再读一次目标；building重建仍包括合并、候选检查和首次SHA。入口重新生成和冻结当日输入的成本保留，checkpoint不是完全免算。

正常一次+最坏全部重建继续一次，暂按**累计68GiB读/18GiB写**预留；这是两轮的保守测算，不是允许丢弃receipt后全范围重跑，更不是正常必须读两轮。实际只能按Sb/Cb/R处理确实未完成或可复用文件。若失败候选保留且building重建新增完整一份，峰值空间须按旧失败现场+新候选/P/记录重算；取两轮P和记录/日志均保留的保守式`(2C+2P+2Fw)×1.2`，同一估算条件下为20.7GiB，向上预留22GiB。这是本次操作新增空间，其他run既有staging占用另计。若只复用validated/promoted，通常不新增年度副本，不默认申请22GiB；继续前按receipt/stat列清现场，连续失败不无限重试。

若只重跑正式28检查，不重算/合并/生成候选，读取预算为Ca+D+7A+Fr；按上述额度约9.16GiB，向上10GiB，只有小型检查事件/日志写入。它不是正常验收额外必做一轮：正常34GiB已包含一次正式检查，不能再自动加一次。

最终验收复用该次28检查、7资产的物化和逐文件完成记录，保存目标数/日期/行数小汇总，不额外重算公式、重扫所有历史/已完成日期；如确有独立对账必要，必须先列明原因和增量成本。真实环境仍只允许按当次明确授权执行。

### 9.8 必须通过的实现与测试对账

| 硬口径 | 代码落点 | 必须新增/保留的独立验证 |
| --- | --- | --- |
| 来源各读1次，不先丢坏行 | asset单连接、共用SQL关系实现 | 捕获真实reader入口次数；错日期/频率/重复因子/NULL/混交易所反例；正常变化不误拦 |
| replacement只生成1次 | source audit与writer | 原公式金样本及窗口数量不变，metadata所有计数与独立字面预期一致 |
| 旧范围先校验、只读一次旧年 | 年度writer | 旧22日错code/freq/year仍拒绝，不能被替换隐藏；非目标日期原值保留 |
| 候选全年校验只读一次 | 候选TEMP/聚合 | 非22日重复键仍拒绝；row_count来自真实候选；不能靠正式D日检查替代 |
| 正式28语义与结果不变 | 两个multi-check及共用SQL | 全年路径错误、D日跨文件重复、缺/多identity、exchange、OHLC反例；计数按行不重复、样本排序/上限一致 |
| 联合schema行为不变 | 原schema helper、每文件投影 | 异构缺列/类型提升/空文件/不可读文件、缺路径等独立Parquet夹具；不能吞异常 |
| 正常年度SHA恰好1次 | publication四方法 | 区分小P摘要；最后一个坏候选导致第一目标未提升；摘要过程文件变化拒绝 |
| 恢复选定文件SHA仅1次 | candidate/verify/promote | validated、promoting两侧、promoted、真实进程退出；receipt改变/目标冲突/输入改变/缺完成记录停止；幂等不重COPY |
| rename后不再SHA | 提升及身份核对 | 允许合法ctime变化，其他身份变化拒绝；锁、同设备、路径与符号链接规则保留 |
| 无隐藏临时磁盘I/O | 本次连接策略与TEMP生命周期 | 现有no-spill实际值；人为低内存失败不自动切managed；TEMP最多一个年度、asset/check互不借缓存 |
| 无共享消费者回退 | QFQ/MACD共同publication及history/repair | 原两writer、MACD/state成组候选、repair/history/BSE隔离测试；不读取这些正式数据作测试 |

测试先用现有项目.venv与隔离人工数据，不安装依赖；涉及已纳入受保护启动器的套件必须用原入口。捕获`read_parquet/COPY/_digest`来源与字节、独立计数，不能只数函数调用或把引擎profile的cache命中当减少预算。单元/隔离通过和真实性能、正式补齐分别报告；旧263项通过不证明本次未实现优化已通过。

### 9.9 接下来按什么步骤推进

1. 代码/证据审计、原文档对账与纯算术核对已完成；本轮已获开发及隔离测试授权，正式数据读取和补数仍暂停。
2. 后续获得实施指令后，先改共用publication一次SHA及继续规则，补故障和次数测试，验证共享MACD/state消费者；通过后再改QFQ来源/年度/候选/正式检查合并，不同时扩展MACD计算或其他数据集。
3. 完成隔离公式/契约/恢复/读取次数/no-spill/异构schema及全部相关回归，逐条核上表；修正计划冲突后才能进入真实来源。测试输出和临时profile不得访问正式Lake或数据库。
4. 另列精确只读预检：按22日身份SQL确定目标，仅读目录/stat及必要同日身份，不进入会写staging的publication；冻结实际N/S/D/A、活动writer、root/卷/目标冲突。没有原生只PLAN模式，不能把调用完整writer叫只读计划。
5. 样本范围获准后，先每频1代码的7个年度文件真实有界性能样本，正式源只读，输出仅/private/tmp；先列路径/字节/必要输入及预算，不借小样本批准扩大。核候选压缩体积、footer、来源重复、峰值内存/无spill、fsync和耗时；小样本不冒充全市场验收。
6. 用实际清单/样本校准C/P/Fr/Fw及耗时，提交新版年度读取与写入范围申请。正常1次摘要已确定，但不等于开发或全局内容读取已批准；旧三遍申请不再使用。任何预算条件不成立先调整方案，不隐式扩大。
7. 精确执行卡与全局读取获准后，才运行现有7资产/28检查入口并观察逐频进度；不假定7频整体原子或固定顺序。任一失败先保留已完成文件和run/receipt，不推进下游，是否继续按原root与本节预算另核。最后只做已列一次验收。

GiB不能直接换算耗时：约3.9万文件的多次receipt/目录fsync也可能占主要时间。步骤5后必须记录每频文件数/字节/生成/校验/提升耗时，给正常与继续的数值时间预算；真实样本未测前不承诺全市场多少分钟。观察每30秒应有业务进度（现publication已有该日志），连续60秒无进展先查当前run/CPU/I/O，不能据此启动第二个run；达到样本校准后的阶段时间预算仍未完成，按安全中断规则保留现场，不延长超时盲跑。自动下游边界按9.1先核清，不能借QFQ成功启动未批准跨年读取。

本节是读取审计与实施约束；2026-10-25后续获准开发和隔离验证的实际结果见第10节。恢复记录中22日仍剩28项；本轮不启动正式前复权、MACD、九转或板块任务，也不提交Git。

## 10. 2026-10-25开发与隔离测试结果

管理员已批准“按方案推进，先完成开发，然后做测试”。本轮完成第9节代码优化及隔离测试，未读取正式Lake/数据库/instance，未补数、部署或提交。没有改变资产、job、sensor、分区、28项检查名称、schema、前复权公式或对象/日期范围。

### 10.1 实现与硬口径对账

| 第9节要求 | 已实现位置与结果 | 验证 |
| --- | --- | --- |
| 来源/因子每asset各1次，保留坏行 | `assets/stk_mins.py::_write_daily_gold_qfq_partition`原样CTAS，coverage/source audit/计算共用连接；生成前后核输入5字段stat | 七频真实人工Parquet reader次数；错日期/频率/NULL/重复/混交易所/输入变化反例 |
| replacement只生成1次，共用公式 | `stk_mins_qfq.py`路径builder委托关系builder；日常从实际replacement计generated count；prepared writer接收同一连接和publication | 七频独立字面量价格、时刻、数量；原history/repair/BSE回归 |
| 原锁及异常顺序不后移 | 公开writer先校验freq/日期、拿同频率锁，再开连接/执行replacement；日常source诊断先于生成 | 持锁冲突和非法范围均0 SQL/0输入读取；prepared核对持锁scope |
| 旧年度1次、先校验后合并 | 原始年度逐文件TEMP，先freq/code/year检查，再按原11列转换/合并；随即释放 | 旧目标日错路径仍拒绝、缺close且freq错仍先报路径错误、其他日期字面值保留 |
| 候选业务检查1次 | `_validate_written_year_file`读实际候选4列到TEMP，范围/全年dup/count复用，返回真实行数并释放 | 非目标日重复仍拒绝；实际reader次数、候选行数 |
| 正常/继续每年度1次SHA | 共用`StkMinsQfqPublication`只摘要实际选定路径；本进程复用验证记录 | 真实stream.read字节及次数；building/validated/promoting两侧/promoted和真实进程退出 |
| 全体检查后才开始提升 | bind保存receipt快照；全部receipt核对后再全部文件核对；逐文件仍复核 | 最后候选/receipt坏时首目标不写；摘要前后换inode或改receipt均拒绝 |
| rename后不再SHA | 5字段identity用于读取前后，rename后核稳定4字段并记录当前5字段 | 合法ctime变化允许，其他变化拒绝，锁/同盘/符号链接及幂等重放回归 |
| 正式28项独立检查 | `checks/stk_mins_checks.py`独立连接；来源/因子各一次、期望TEMP仅4身份列，正式年度逐文件一次读并释放 | 原28名称/blocking保留；全年路径、目标日全局dup/price/identity/样本、缺输入/schema分支 |
| 联合schema/转换行为保持 | 原schema helper/接口不动；全局联合类型只查元数据，每文件按联合类型补NULL，vol/amount不新增无用转换 | 缺列、类型提升、空文件、损坏文件和原SQL对照；保持BinderException/ConversionException |
| 无隐含spill | 仅日常QFQ asset/check显式`existing_no_spill`，全局16GB/4线程及history/repair默认不变 | 实际0B设置、临时目录无spill文件、低内存真实失败且无managed回退 |
| 预算可观察 | publication日志增加S/P/C的stat字节、输入/候选/正式SHA实际read字节 | 正常及恢复独立字面值断言；不把stat或SHA字节叫物理磁盘I/O |

全体预检和本进程记录同时绑定target/path/sha256/row_count/candidate_identity/before/当前identity与receipt内容。没有新增receipt字段、版本、表、配置项、备份或快照。缺receipt只允许实际writer顺序下可证明未开始的连续尾部；全缺、内部缺口、已有promoting/promoted记录时不猜测重建。

旧价格转换夹具的最初预期有误：以为将被替换的D日非法close可先过滤。用修改前源码与原始合并SQL真实执行后，D与非D非法close均抛ConversionException；已按该独立证据纠正夹具，并把原SQL保留在回归测试中，没有修改生产代码迎合预期。隔离步骤还修正了测试临时路径中的`/var`符号链接、MACD显式默认设置与子进程临时目录；没有放宽生产路径或no-spill校验。

### 10.2 验证结果及边界

- 最终20个相关套件：**297 passed、65 subtests passed，24.68秒**。新增publication 65、读取/writer 26、正式check 32例均包含在297内，不重复相加。
- 原受保护启动器运行契约静态门禁：**113 passed、5 subtests passed**。全项目`src/tests`致命Ruff基线通过；其余本次文件默认Ruff通过。`assets/stk_mins.py`默认Ruff的7条既有问题与修改前逐项code/message一致，没有扩大清理。
- CodeGraph使用explore/impact核对日常入口、共享writer、SQL builder及readiness/history/repair/BSE和MACD年度/state消费者；开发后sync/status正常。独立代码复核发现的锁后移、bind后首次摘要前receipt可变问题均已处理并有反例测试。
- 测试使用项目现有.venv、人工Parquet、内存DuckDB及临时Dagster目录；操作系统禁止网络和整个`/Volumes`访问。临时启动脚本仅把DuckDB temp目录改到隔离目录，不改变memory/threads、计算SQL或策略校验。正式源和目标均未用作测试。

可复核证据：[汇总（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)、[综合测试（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)、[受保护门禁（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)。三份新增测试为`test_stk_mins_qfq_read_optimization.py`、`test_stk_mins_qfq_check_read_reuse.py`、`test_stk_mins_qfq_publication_single_digest.py`；既有staging测试只同步返回行数的spy和隔离路径/子进程临时目录。

### 10.3 尚未进入的步骤

34GiB读/9GiB写/12GiB空间仍是第9.6节的有条件文件预算，不是实测或自动硬上限。元数据累计写入、真实候选C、全市场内存/耗时和正式卷原子rename尚未实测。不能将临时目录测试外推成正式年度执行验收。

下一步仍按9.9第4～6步：先冻结实际目标/stat及活动任务边界；另明确每频1代码真实性能样本的读取清单与额度并获准；据样本校准实际S/C/A/P、元数据、内存和耗时，取得精确年度读取/写入授权后才补7项QFQ及原28检查。MACD/九转/板块的正式数据执行继续另按原批次和读取授权处理。


## 11. 后续真实性能样本与清理要求（提交前说明，尚未执行）

本节标题与下文保留提交前的方案阶段。后续管理员已批准本节方案，实际唯一一轮结果以第12节为准；执行卡见11.5，不把样本授权当作正式补数授权。

### 11.1 样本及现有stat

先用同一证券`600000.SH`覆盖1/5/15/30/60/90/120七频，每频一份完整2026年度文件，共7份，不是7只股票。2026-10-25提交前仅stat确认7份均存在，字节分别915069/228958/93543/52626/31132/25355/18975，合计1365658B（约1.30MiB）；本次未读这些内容，也不读取2025年。

当日来源是22日Silver的1/5/30/60分钟四文件，分别21651947/5395387/1172089/804706B，合计29024129B（27.68MiB）；另22日因子文件55558B。总计12份不同正式输入文件，原文件总字节30445345B（29.03MiB）。按代码过滤输出不代表引擎仅读该代码的磁盘字节，因此四份日来源按整文件计预算。

### 11.2 测量步骤及范围

1. 在单个独占临时父目录中建立`lake/`、其同级`lake_staging/`、DuckDB临时目录和profile目录。只按证券代码提取四份日来源及因子，不能先过滤错误日期/频率、NULL、重复行或值域；复制该代码7份完整旧年度文件到临时Lake，保留原布局。日常wrapper无代码过滤参数，不能直接传正式Lake冒称只测一只。
2. 逐频调用本次真实daily writer和对应check evaluator，目标全部是临时Lake；保留原28结果，无Dagster instance/job/sensor/event或正式写入。正常一次，不另做重复全局审计。记录每频生成、候选检查、SHA、提升、正式检查耗时、读取次数/字节、候选大小及进程内存；不执行MACD/九转。
3. 健康完整日样本的来源行数预期241/49/9/5，七频replacement为241/48/16/8/4/3/2，共322行；实际差异须先解释，不能裁剪到预期。此样本只能证明所选代码的真实衔接和成本，不证明全市场数据齐备或16GB能承载全市场日TEMP。
4. `/private/tmp`写出测试用于核算法、文件体积和内存；其磁盘耗时不能直接外推正式卷。若要测试正式卷rename，另列staging内独占小文件范围及授权，结束删除该独占范围；本节不授权写正式Lake或共享staging目录。

### 11.3 有条件预算

设S为七份旧年度1.30MiB，C为七候选总量，U为四份正式日来源27.68MiB，A为正式因子，U_s/A_s为抽取后文件，D_s为按七目标映射重复计入的小来源，P为冻结输入。含复制准备和一次原28检查：

```text
读 = 2S + 3C + U + A + 2D_s + 14A_s + P + Fr
写 = S + U_s + A_s + C + P + Fw
```

样本先按C≤2MiB、U_s≤128KiB、A_s≤16KiB、P≤128KiB、Fr/Fw各4MiB预算；D_s≤2U_s。由现有stat和这些条件，读取约42MiB以内、写入约8MiB以内，向上预留**读取64MiB、临时写入16MiB、临时空间32MiB**。这是申请额度，不是已测I/O或现行自动硬上限；执行脚本须在准备/每频提升前累计检查，超限先停并清理，不自行扩大样本或重跑。含启动和记录的暂定整轮时间上限5分钟，单频无业务进展60秒先停查因；不能用1只股票的速度直接承诺数万文件全量耗时。

### 11.4 结束清理

管理员明确要求测试不留临时文件。正常、失败及可控中断都先关闭连接/释放锁，再删除本次整个独占父目录，涵盖复制输入、年度输出、candidate、receipt、锁文件、DuckDB临时文件、profile和临时日志，不能只删lake遗漏旁边staging。结束汇报前核对父目录及本次其他写出位置均不存在；清理失败须报具体残留，不能宣布清理完成。仅保存小型文字/JSON测量结论，不保留测试Parquet或原始数据副本。强杀/断电若打断清理，恢复后先按本次目录记录清理，再交付结果，不删除其他任务目录。

本轮提交隔离复验同样把pytest的`--basetemp`置于独占TemporaryDirectory内，避免pytest默认保留测试文件；该复验仍完全禁止正式卷和网络。

### 11.5 已批准样本的执行卡与脚本审计要求

管理员已明确批准第11节方案并要求严格执行。此次仅执行一次所列真实样本，正式补数/正式卷写入/同卷rename仍未授权。代码基线为`938344f8`；当前资产文件中另有未提交Raw/Silver修改，执行前须以AST确认全部QFQ函数与该提交一致，不能将并行修改纳入测试结论。

- 工作目录：`/Users/congming/github/goldenshare/lake_console/orchestrator`，使用已有`.venv/bin/python3 -B`，不安装依赖。临时独占父目录固定为`/private/tmp/qfq_perf_20261025_a1`，须原先不存在；脚本、sandbox规则、临时Lake和同级staging、DuckDB目录、profile均在此目录。持久结果仅写`lake_console/reports/datasets_recovery_20261022_20261024/qfq_real_performance_20261025/`小型JSON/说明。
- 启动方式：`/usr/bin/sandbox-exec -f /private/tmp/qfq_perf_20261025_a1/sandbox.sb .venv/bin/python3 -B /private/tmp/qfq_perf_20261025_a1/runner.py`。规则禁止网络和全部正式卷写入，正式卷内容读取只允许11.1固定12个文件；写入只允许本次独占父目录及小型结果目录。`DAGSTER_HOME`仅指向临时父目录，不初始化任何instance。
- 执行前只stat固定12个路径，检查普通文件、无符号链接和5字段身份/大小，与预算对应。准备阶段四Silver及因子各一次COPY，只按代码过滤，保留真实schema及坏行；7年度各复制一次，复制/提取前后及全程结束再核正式源stat。临时输入行数与11.2不符即报告并停止，不换股票、不裁剪、不继续或自动重试。
- 真正daily及check连接只重定向temp目录，保留原16GB/4线程/无spill0B设置。七频按1/5/15/30/60/90/120顺序，直接调用现有writer及原check evaluator；后者仅接收含partition_key的context和临时Lake资源，无job/instance/events。每频检查四项名称、数量和通过状态；全部完成应7输出、322条当日replacement、28项passed。
- 观测只包装现有调用，不替换SQL、公式、候选校验或原promote。捕获SQL耗时、read_parquet数据读取路径/次数及完整文件大小计费、COPY实际文件字节；DESCRIBE/footer及小JSON读单列Fr预留，不能称物理磁盘IO。摘要使用原read回调计实际字节，区分冻结P与年度C，不另算一遍hash。阶段耗时覆盖来源、诊断、生成、旧年度、合并COPY、候选校验、摘要、提升、正式检查；记录进程RSS高水位，不添加全量设备监控或重复查询。
- 在准备前、每次读取前和每频原promote前检查11.3总量及C/Us/As/P、Fr/Fw和空间额度；为后续检查留出文件读取预算。_save及小型日志/profile按累计实际编码字节计Fw，不仅看最终目录size。连接确认0B且临时目录无spill；记录当前正式输入实际字节与临时预算。5分钟整轮和60秒无进展超限，先interrupt当前SQL，再抛错进入清理。
- 正常/异常/SIGINT/SIGTERM均先退出所有连接和publication上下文、释放锁，核源stat，再由finally删除整个独占父目录并核不存在。源stat不变只证明本轮未检测到源变化，不额外全量hash。若任一检查/预算/清理失败，报告失败及已完成频率，不按成功处理，也不自动第二次读源。

脚本进入真实数据前须经静态编译、固定路径/预算/清理独立审查；运行后只复用本次28检查及字节/完成记录，不额外读取年度内容做逐值对账，不宣称已证明非D逐值一致或全市场性能。执行脚本本身也在结束时删除，仅保留其SHA与小型结果；结果记录源码基线和实际运行边界。


## 12. 首次真实样本结果与环境修正建议

管理员批准第11节方案后实际启动一次，未自动重跑。四Silver按代码抽取241/49/9/5行、因子1行，准备七个完整年度副本。1分钟writer完成来源/因子载入和诊断后，在publication构造调用`tempfile.gettempdir()`时退出：脚本只重定向DuckDB temp目录，遗漏系统TMPDIR/TEMP/TMP；隔离规则拒绝了默认系统目录写入。属本次测试环境准备遗漏，不能归因数据或算法，也不能据此宣告完整链路性能通过。

结果为0/7频率完成、0/28检查执行、0年度SHA/提升。运行0.839秒仅代表失败前阶段；读按全文件计费并加Fr预留为33.042MiB，写约1.354MiB，均未超额度。源12文件5字段stat不变、无正式写入或instance/job/event；连接退出后整个独占临时父目录已删除，并由主流程再次确认不存在且无运行进程。小型结果见[测量说明（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)和[result.json（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)。

下一轮建议先修测试环境：启动Python前将TMPDIR/TEMP/TMP指向新独占父目录内预建system_tmp，读取正式内容之前核对`tempfile.gettempdir()`及该目录小文件创建/删除。保留现有sandbox限制和原业务代码；不开放系统默认临时目录或修改DuckDB预算。当前只记录修正建议，未重新创建执行脚本或第二次读源。原11.5明确“失败不自动第二次读源”，故重测需明确授权同范围额外一次64MiB读取/16MiB临时写/32MiB空间，不能沿用失败前准备而绕过计量，也不能覆盖首轮失败证据。

### 12.1 环境修正及获准重测执行卡

管理员已批准“修正后继续测试”。本轮按第11节同一12文件、同一股票/年份/日期/七频及额外一次64MiB读、16MiB临时写、32MiB空间预算执行；首轮证据保留，不追加MACD/九转、正式卷rename或正式补数。若此次仍失败，保存结果并清理，不自动第三次读源。

临时独占父目录改为`/private/tmp/qfq_perf_20261025_a2`，须原先不存在；`system_tmp`在启动前创建。小型结果写原报告目录的`result-retry.json`，不覆盖`result.json`。工作目录、Python解释器、source白名单、逐频真实writer/check、阶段计量、预算/中断/清理规则全部复用11.5。

| 现有变量/设置 | 默认来源及消费者 | 本轮作用范围与生效 | 验收及清理 |
| --- | --- | --- | --- |
| TMPDIR / TEMP / TMP | 子进程继承的系统环境；Python tempfile选择并缓存目录，publication构造调用gettempdir | 仅本次启动命令在Python启动前全部设为a2/system_tmp；不改shell、配置文件或正式进程环境 | 先核三变量、gettempdir及默认目录小文件创建/删除；错误即0正式内容读取停止；随父目录清理 |
| DuckDB temp_directory | 原连接Settings；与上述系统变量不同 | 仍只改为a2/duckdb，保留16GB/4线程/无spill0B | 用现有连接校验；不得切managed |
| DAGSTER_HOME | 本脚本的子进程环境 | 仅设a2/dagster_unused，不创建instance | 对instance入口设拒绝断言；结束核该目录未创建 |

启动命令为`/usr/bin/env TMPDIR=/private/tmp/qfq_perf_20261025_a2/system_tmp TEMP=/private/tmp/qfq_perf_20261025_a2/system_tmp TMP=/private/tmp/qfq_perf_20261025_a2/system_tmp /usr/bin/sandbox-exec -f /private/tmp/qfq_perf_20261025_a2/sandbox.sb .venv/bin/python3 -B /private/tmp/qfq_perf_20261025_a2/runner.py`。sandbox继续禁止网络/全部正式卷写入，正式内容只允许12个literal路径，临时写入只允许本次父目录和小型报告目录。

正式内容读取前先验证：三个系统变量一致、tempfile.gettempdir()确为system_tmp、使用不指定dir的NamedTemporaryFile创建并写微量字节再删除，路径必须位于system_tmp且删除后不存在；只构造publication并核目录在a2/lake_staging，不enter/bind/promote、不读Lake内容。这样预检覆盖上轮出错位置，而不是只验证解释器能启动。探针/脚本/日志/JSON累计字节计Fw，system_tmp计空间并整目录清理。脚本静态编译与独立审查后才能进入本轮正式内容读取，最终不额外扫描年度文件。

### 12.2 a2结果记录错误与不读源修正验证

a2已通过系统临时目录预检、1分钟真实writer及check evaluator调用，但报告转换`TextMetadataValue`时退出：通用normalize先按tuple遍历，随后才检查`.value`；本机Dagster的record属于tuple结构却禁止迭代。此次错误在测试脚本的报告记录步骤，不在前复权生产计算；后续六频未执行，不能宣告28检查通过。a2临时父目录已全删、源stat不变，未第三次读源。

后续先做不访问正式数据的报告转换回归：使用本机真实MetadataValue与字面JSON/text/int/bool/float/path样本，先按MetadataValue取`.value`、再处理普通dict/list/tuple；对`.value`返回自身等尚未支持的复杂元数据明确拒绝，不吞异常。须证明原顺序会复现本次异常，修正后转换结果等于独立字面预期，并可记录真实AssetCheckResult的check_name/passed/metadata。该纯对象测试不创建instance、不运行check evaluator或读Lake，测试脚本和隔离临时目录结束删除，只保存小型验证结论。未来正式重测前应将该回归及完整报告写出/读回（正常/失败结果）都列为0正式读取的预检，不能再只覆盖环境。

当前不启动第三轮；如另获批准，仍按原单股票/七频/12文件及一次64/16/32额度执行，a1/a2失败记录均保留。


### 12.3 a2实际结果与后续边界

a2系统临时目录修正和预检通过。1分钟真实writer完成241条replacement，年度临时文件919587B，writer耗时0.161285秒；其check evaluator耗时0.109377秒并返回。随后报告normalize误将TextMetadataValue当tuple迭代退出，未完成四项pass/name断言，不能补记四项或28项通过；后六频未执行。

本轮年度候选实际SHA仅一次919587B，输入冻结摘要另一次7265B，提升后未再SHA。含Fr预留的文件读取计费36.560MiB，累计写约2.253MiB，均未超额度；启动至退出0.989秒只代表已执行阶段。12源stat不变、正式写入0；a2及a1目录均已清除。

12.2规定的纯对象回归已完成17项并清除其临时目录，复现旧异常，验证9类真实MetadataValue、真实AssetCheckResult成功/失败、JSON写出读回及排他创建。未读取正式数据或创建instance，不算七频性能通过。结果详见[a2说明（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)、[a2原始结果（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)与[纯对象回归（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)。

当前按12.1失败后不自动第三次读源；下一轮若获明确同范围/额度批准，先在0正式读取时通过环境与结果记录完整预检，再执行原七频/28项。首轮和本轮失败均保留；不扩大到其他证券、年份、MACD/九转或正式补数。


### 12.4 管理员停止性能测试，回到补数业务判断

管理员明确不再继续测试。已只读复核当前生产链：正式Lake命中publication固定staging分支，不调用样本路径中的gettempdir；正式checks直接构造/返回AssetCheckResult，没有临时runner中的normalize(e.metadata)。两处错误不需要修改生产补数代码，也不能据此将业务判定为失败。

现有297项回归包含七频独立公式金样本、因子/窗口语义、只替换目标日并保留其他日期、候选检查、同盘提升和中断恢复、原28检查语义；锁/receipt/CAST审计问题已经修正，真实1分钟writer也已完成241行。当前无已知QFQ补数业务阻断，可回到原正常补数入口；不再要求第三轮性能测试。正式补齐成功仍以实际补数run及原28项检查为准，不把代码判断写成已经执行成功。

本轮仅读代码/已有证据并同步停止决定，没有测试、正式内容读取、任务或数据写入。既有失败记录保留，所有已清理临时目录不恢复；后续执行继续按原核定范围和必要现场预检进行。

## 13. 正常补数的本轮范围

管理员要求开始推进并先列清范围。本轮首先处理**2026-10-22**的`gold_stk_mins_qfq_1m/5m/15m/30m/60m/90m/120m`共7项，使用原`stock_mins_qfq_daily_update_job`和其原28项检查。上游Raw/Silver不重跑，不恢复性能测试。年度文件只替换22日业务记录，保留其他日期，不执行历史从零重建。

读取对象为22日实际股票集合涉及的2026年度QFQ、22日Silver分钟及因子；读取全年仅为保留其他日期并合并22日，范围不含2025年、MACD/九转或板块历史。沿第9节正常一轮有条件预算：34GiB文件读取、9GiB写入、12GiB额外空间。含正式28检查，不另做成功后的全局审计；失败保留候选/记录并停止，不自动全范围重跑。该范围仍需按根AGENTS“数据集全局读取审批”明确授权，开始推进的一般指令不代替该项；可先做既有事实及元数据的必要预检，不先读年度内容。

原恢复记录剩28项：本批7项通过后为21项。后续同日MACD/KDJ指标7项和state7项、九转30/60/90/120共4项、板块技术Gold/本机CH/Prod CH共3项，分别按依赖和自身历史读取/写入范围推进，不把它们混入本次QFQ年度读取授权。

### 13.1 正式执行卡（管理员已明确批准）

管理员随后回复“批准，开始实施，实施完成后，向我汇报”，批准第13节七项补数及2026年度读写范围。此决定取代上文“仍需授权”的等待状态；不再做性能测试，不改业务代码。

- 当前代码依据：`938344f8`的QFQ writer、publication、原check及job；资产文件中无关Raw/Silver改动不在本job选择内。入口只选七QFQ及28检查，daily wrapper传当前root_run_id作为publication_id。
- 工作目录为`lake_console/orchestrator`。必要预检用现有`.venv/bin/python3 -B`，直接构造PostgresRunStorage/EventLogStorage/ScheduleStorage且`should_autocreate_tables=False`，通过PGOPTIONS限制只读和30秒查询；不初始化instance、不求值sensor、不查Prod、不重读上游明细。只核活动任务、分区、sensor状态、daemon、五个输入stat、挂载/同设备/权限/空间、年度文件stat上界。预检脚本与小型结果存本轮报告目录，不成为业务入口。
- 正式命令：`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job stock_mins_qfq_daily_update_job --partition 2026-10-22`。仅执行一次。沿现行配置16GB/4线程、existing_no_spill与既有临时目录，不安装、改配置、启停daemon/sensor或改分区。
- 正式数据只写`/Volumes/datasource/data_lake/gold/quote/stk_mins_qfq/freq={1,5,15,30,60,90,120}/ts_code=*/year=2026/part-000.parquet`中实际replacement涉及文件。候选及记录只在`/Volumes/datasource/data_lake_staging`。不读2025，不调用MACD/九转/板块链。自动下游sensor必须停止或保持源码默认停止；存在会消费本次success的RUNNING状态则先停止本次执行并说明，不自行改sensor状态。
- 预算按第9.6节：正常一次读34GiB、写9GiB、额外空间12GiB，含原28检查与小记录开销。预检只读stat及控制库小记录；正常执行复用现有业务进度、S/C/P/摘要实际读取字段观察成本，不为测量追加年度扫描。发现空间不足、输入变化、并发writer、预算假设不成立或业务报错即停止领取后续任务，保留已提升文件及候选/receipt，不删除业务数据，不自动重试。中断后的继续执行另核原root_run_id、剩余文件和预算；本次批准不等于再读一轮的批准。
- 最终验收只取本run事件，核SUCCESS、七个22日物化、28项blocking/passed且绑定本次物化storage_id；复用该run publication JSON/receipt及文件stat核逐文件提升闭合、输入stat未变。不得调用旧单日单文件final审计器，不重开年度Parquet、不重算SHA。保留正式恢复receipt/checkpoint；此前测试临时目录不恢复。结果落原恢复报告，剩余数按本批实际结果更新。

### 13.2 现场预检结果及自动下游边界

21:13（Asia/Shanghai）只读预检：无活动run，daemon无进程且心跳停在约45小时前；五份当日输入stat与既有证据一致、分区已登记、QFQ函数及核心文件匹配938344f8；正式Lake/staging同设备、无符号链接、可读写，空闲约2.65TiB。只stat的2026全目录上界仍为39144份/8072911121B，没有年度内容读取或正式数据写入。

实际控制库中的`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`与`gold_stk_mins_qfq_nineturn_update_job_sensor`均为RUNNING，重启daemon可能消费此次成功并触发范围外读取，当前不满足13.1边界，尚未启动补数。已请求额外明确批准将这两个状态改STOPPED并保持停止。另三个相关sensor不属于本次停用清单；MACD repair监听的是MACD daily，不直接监听本轮QFQ daily。

如获批准，仅用现有PostgresScheduleStorage的`update_instigator_state(state.with_status(InstigatorStatus.STOPPED))`修改上述两个精确名称/既有repository记录，保留原origin/selector/cursor/instigator_data，不创建新state，不启停daemon，不改变其他sensor。逐条记录原状态、身份、修改时间，并只读取回核STOPPED；中途失败保留已经停止的状态，停止正式任务，不自动恢复RUNNING。随后仅刷新活动run、两个sensor状态及空间即可启动原命令，不重做年度stat或内容审计。待本批验收后仍保持STOPPED，后续下游执行获批时再决定何时开启。此控制库状态写入不能改变任何业务表。

管理员已明确批准停用这两个sensor并继续补数，追加以下恢复条件，取代上段笼统的“再决定何时开启”：

- [x] **sensor恢复TODO已完成（2026-10-27）**：两项sensor已按管理员本次追加授权恢复并读回RUNNING，原身份、cursor和lastRunKey保留。23日股票链及repair已验收；THS两项独立未完成，不再作为本次恢复开关的等待条件。详见23日恢复报告第43—44节及`operational-closeout-20261027/sensor-restoration-summary.json`。

本轮先停止两个现有状态并读回，刷新无并发run/daemon、五输入stat和空间，再执行13.1原命令一次。沿用已完成年度stat，不再次列举年度文件，不再测试。状态修改及预启动结果写`qfq_recovery_20261025/sensor-stop-and-launch-preflight.json`，业务结果仍由原28项检查及publication记录验收。

2026-10-27补充授权：管理员明确要求收尾并恢复此前关闭的两项sensor。23日股票链及repair已验收，THS两项无本链输入依赖；本次按[23日报告第43节](../../reports/datasets_recovery_20261023_20261026/README.md#43-恢复自动任务及文件收尾方案与lld2026-10-27)的精确名称、原身份/cursor保留、原生GraphQL状态恢复及读回执行。此为对上方旧等待条件的最新授权，不代表THS已补齐；TODO只在两项实际RUNNING读回后关闭。

### 13.3 正式执行及验收结论

2026-10-25两项sensor已按13.2停止并读回，cursor及其他自动任务状态未变；按13.1原命令正常执行一次，run `78a6791a-a540-42b3-9ac3-e27abda235c6` SUCCESS，21:24:26～21:39:41，耗时914.629秒。7项22日物化及28项blocking检查全部通过，检查均绑定本run对应物化。每频5,570个目标，合计38,990份2026年度文件完成校验/原子提升；22日记录合计1,793,540行，五输入stat未变。没有重跑上游、性能测试、额外年度读取/摘要或启动下游。

原预算与现场对账：S=8,055,561,219B、C=8,094,696,789B、P=31,370,988B；候选年度SHA累计读取C一次，正式重复SHA为0。复用D=57,243,552B、A=55,558B，按9.6含元数据预留的读/写估算为31.255/8.068GiB，未超34/9GiB。这里的记录及预算不是物理磁盘IO实测；未为测量追加读数。最终receipt/stat校验与七频日志汇总一致，不再全量逐值审计其他日期。

沿恢复清单累计88项补齐、剩21项，不代表新全局审计。21:40读回两项sensor均STOPPED，无活动run/daemon；13.2的TODO继续保留，必须等23日数据补齐完成后再启用。执行命令、逐频行数、提升记录和开销见[原恢复报告第39节](../../reports/datasets_recovery_20261022_20261024/README.md#39-22日前复权七频正式恢复已完成并验收)及其`qfq_recovery_20261025`证据。操作脚本临时文件已清理，正式继续执行记录保留。

<a id="14-22日因子修复前置处理与读取修正方案待管理员确认未开发未执行"></a>

## 14. 22日因子修复前置处理与读取修正方案（已完成开发及正式执行）

管理员已明确批准“批准修正，验证后按此范围执行”：本节开发、必要隔离测试及正常一次26代码历史修复，读52GiB、写3GiB、额外空间4GiB；失败停止，不自动重跑。本节原“待确认/未获批准”描述保留其提案背景，执行状态以本段及后续实际结果为准。

### 14.1 已查事实、原因及影响

管理员要求先处理七条因子修复检查，再推进后续补数。现有`stock_mins_qfq_factor_repair_job`是独立非分区任务，typed配置只有`trade_date`。手动QFQ job不直接调用它；平时由独立sensor在前置ready后发起。本轮控制记录最新成功为21日，补22日时daemon没有运行；七条缺记录不能解释为repair曾运行失败，也不能归因为此前停用的MACD/九转两个sensor。

真实统计计数：22日因子5,576代码、21日5,575代码，非法因子0；26只已有股票因子变化、1只合法新增，无缺失旧因子。因而本次`can_execute_repair=true`且`repair_required=true`，不能采用“无变化、零行情写入、仅产生检查”的分支。2014-01-02至22日共有3,111个预期交易日，分区键已全登记。计数及26个有界代码名单、输入/目标stat见原恢复报告`factor_repair_20261022/`，本轮没有读取历史分钟或年度内容。

这项现行职责是将26只股票的历史QFQ按22日因子重新计算，完成后由原op生成七条真实check；它会阻止MACD日更及九转自动任务，板块无此依赖。QFQ原28检查只证明当日行情，不替代本项。修复写过历史后，MACD后续还须按现有流程完成相应代码的历史指标修复，不能把日更14项成功当作该历史修复已完成。

### 14.2 范围及禁止项

- 目标日期只取2026-10-22；变化代码固定为本次26只，名单保存在`scope-stat-summary.json`，1只新增股票不进入本次历史改写。
- 源日期为3,111个已核交易日，2014-01-02～2026-10-22；四个唯一Silver分钟来源1/5/30/60，各3,111文件，共12,444文件/47,307,734,197B；每日因子3,111文件/113,188,579B，另22日因子55,558B及小型Basic/日历计划输入。
- 七个目标频率1/5/15/30/60/90/120，实际只改26代码的相应2014～2026年度QFQ。已存在1,932份/464,280,822B；理论上界26×13×7=2,366份。上市前空年份不凭理论上界造数据。
- 只对上述代码/日期重算；保留其他代码及目标年度中范围外日期。不运行MACD、九转或板块任务，不开启daemon或sensor，不引入新数据集/配置/CLI参数或手工通过事件，不按旧QFQ34/9GiB授权执行。
- 源仍是全市场日文件。按26代码过滤不等于只从磁盘读这26只的字节，本方案按全部所涉文件大小保守计费；不得用26/全市场比例压低读取申请。

### 14.3 为什么不能直接运行现有任务

修正前每freq/year先读Silver诊断窗口，再读同一文件构造结果；同来源也被不同目标重复读取。令四唯一来源为H1/H5/H30/H60，则D=2H1+2H5+2H30+H60=93,435,471,399B；仅两遍2D约174.037GiB。加因子、旧年度等尚未计候选/冻结/临时文件即约175.212GiB。这是当前独立读取步骤按文件大小的保守测算，不是硬盘实测IO；其中重复源读取并非算法要求，不按此旧开销直接申请执行。

修正前repair的两处年度writer调用也没有传持久publication_id，每批使用随机身份。需要向下传原root_run_id，复用已有逐文件记录；不能把当前任务说成重启就只处理未完成文件。

### 14.4 具体实现及影响面

CodeGraph已覆盖`execute_gold_stk_mins_qfq_factor_repair`、op/job、SQL builder、调用及测试；新改动只落`defs/stk_mins_qfq_factor_repair.py`和`defs/ops/stock_mins_qfq_factor_repair.py`及相关隔离测试。复用现有核心接口，原则上不修改公共writer、原公式、检查名称/metadata或sensor状态。开发前若复用接口语义不满足以下约束，先更新本节，不新增旁路入口。

1. 维持原因子分类、交易日/登记门槛、允许频率及原七条结果口径。op向execute传`context.run.root_run_id or context.run_id`，再传给每freq/year公共writer；scope已有频率和日期，不增加新状态表。
2. 按年份组织处理，每次只保留一个年份和一个来源频率的26代码原始TEMP：1分钟供1/5目标，5分钟供15/30目标，30分钟供60/90目标，60分钟供120目标。七频原生/派生计算仍用原canonical公式，不依赖中间Gold结果生成派生。
3. 每year/source只载入一次原始源，保留原列类型及原诊断应抓的坏行；仅按本次代码范围限制，不提前清理坏频率、价格、NULL或重复。诊断使用`build_canonical_gold_stk_mins_qfq_diagnostics_sql_from_relation`，计算使用`build_canonical_gold_stk_mins_qfq_select_sql_from_relations`，两者读同一TEMP；诊断未过不能生成/提升该目标。
4. 每年历史因子只载一次，在七目标之间复用；22日as-of因子在run内复用。每年完成后释放年度因子；每来源完成后释放原始TEMP，不把13年明细同时放入内存。保留原空年份、来源完整性及26代码外不动的语义。
5. 每目标仍在既有publication锁内生成并校验replacement，调用`write_prepared_gold_stk_mins_qfq_rows_to_year_files`；保留原旧文件校验/单次载入、候选完整业务校验、一次候选SHA、同设备原子提升及逐文件记录。空replacement沿原allow_empty语义处理，不伪造目标。
6. 历史分钟载入、计算、候选写入的公共连接使用现有配置16GB/4线程和`existing_no_spill`，强制磁盘spill为0；不新增配置项、不改变其他任务策略。原计划分类helper保持其独立managed连接，只处理已核身份/总量不到1MiB且键唯一的两日因子和Basic三小输入，计入E及小记录预留，不读历史分钟或建立大型TEMP；不能声称该小连接也被强制no-spill。输入身份/规模变化先停。生成进度与已完成年份/频率/文件对应，继续复用publication字节及阶段日志。

开发硬口径落点：`execute`保持分类/登记/频率子集及65+26计数；共享来源和因子TEMP在core年度执行helper，原relation诊断及prepared writer保留；publication_id由原op传入。新增隔离测试覆盖读取次数/原列类型、七频字面结果、空年和子集、范围外文件不变、失败续跑和输入变化。无源码合同/配置/入口行为变更，不新增绕过门槛的路径。

### 14.5 预算、中断与验收

令H为四唯一来源47,307,734,197B，F为历史因子113,188,579B，A为22日因子55,558B，S为旧目标464,280,822B，C为候选，P为冻结replacement，E为小型计划输入，Fr/Fw为额外记录及schema等预留。拟实现正常读取公式为：

```text
读 = H + F + A + S + 2C + P + E + Fr
写 = C + P + Fw
```

候选的两次读取分别为业务投影校验和唯一SHA，不再另跑普通QFQ28检查；最后验收用本次七check/原生产者metadata、operation/receipt/stat。候选年度SHA正常仍只有一遍。暂按C≤1GiB、P≤1GiB、E≤2MiB、Fr≤1GiB、Fw≤512MiB、spill=0，读约48.60GiB、写约2.50GiB；申请上限为正常一次**读52GiB、写3GiB、额外空间4GiB**。这些是拟优化且带条件的额度，不是当前代码预算或已获批准。启动前重新核stat与本次范围；条件不成立先停，不能用旧175GiB开销启动或自行扩大代码/日期。

中断保留已提交文件和既有逐文件记录，失败不回滚业务数据、不写假成功，也不自动第二次全范围运行。原root身份续跑仍可能重新载H/F并重新计算冻结replacement，再复用已验证目标，不承诺免源读取。最坏再一轮追加52GiB读/3GiB写；两轮合计104/6GiB，保留旧候选/冻结时空间按8GiB另核。此项必须纳入中断后的实际范围申请，正常一次批准不自动覆盖续跑。

验收为原job SUCCESS、同run七项blocking/passed、partition=22日，metadata代码数26/名单hash/producer/upstream batch一致、failed_code_count=0、派生failed=0；真实登记历史改写量。只对本run目标/receipt/stat及控制记录收尾，不再次扫历史源或全市场年度。保持MACD/九转sensor STOPPED，不自动进入后续大范围指标修复。

### 14.6 必要隔离验证及执行顺序

设计获准后已完成下述必要隔离验证（最终26项通过，见14.8），不做真实全市场性能样本：复用现有factor分类/无变化/缺旧因子测试；增加同year/source只读取一次且诊断计算共用原始行的证据；用独立字面金样本核七频OHLC/窗口、空年/新股/跨年、坏源不能被过滤掩盖、26范围外文件不改；模拟中途失败、同root续跑不COPY已验证文件、输入改变拒绝继续。生产者字段以本轮四文件schema及现有Silver合同为依据，测试expected不调用待测helper生成。

按本节完成开发、最小回归和方案对账后，才可能在明确历史读写范围批准下运行原非分区job一次：工作目录`lake_console/orchestrator`，`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，命令`.venv/bin/dg launch --module-name orchestrator.definitions --job stock_mins_qfq_factor_repair_job --config <本报告内固定22日配置文件>`；配置仅为`ops.stock_mins_qfq_factor_repair_op.config.trade_date: 2026-10-22`。执行前复核本轮源身份/26代码、活动run、pool和sensor边界。失败停止并保存事实；只有七项实际通过后才推进MACD及其他补数。

### 14.7 获准执行卡及最小现场验收

只用本报告已固定的`factor_repair_20261022/run-config.json`，正式命令固定为：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job stock_mins_qfq_factor_repair_job --config /Users/congming/github/goldenshare/lake_console/reports/datasets_recovery_20261022_20261024/factor_repair_20261022/run-config.json
```

先完成14.6隔离回归及独立代码审查，修正发现的问题后记录源码SHA。隔离测试复用已有临时目录连接启动器，禁网络及整个正式卷；不安装依赖。结束删除本次临时父目录，仅保存文字结果。正式启动前只读控制库（禁止autocreate），核无活动run、共用pool及两个已停sensor状态，daemon必须仍无进程；只按已存manifest stat核源/factor/目标及Basic/日历身份不变、同设备、挂载与4GiB空闲，禁止再次glob所有年度或读取内容。另确认配置只含22日。

正常任务只运行一次，监控新年/来源载入日志与publication日志，不另做全局审计。按日志累计H/F/A和各operation最后completed快照的S/C/P，避免累计进度快照重复计费；若C/P或总预算前提不成立，先中断当前任务并保留结果，不继续下一批、不自动重跑。52GiB/3GiB包括最终小型JSON/stat验收；不为记录IO额外profile或SHA。

最终仅查精确run：SUCCESS，无step/pipeline failure，恰七项factor check，partition=22日、passed/blocking，producer_run_id为本run而publication使用root_run_id；metadata中26名单/hash、3111日期、native65/derived26及实际成功/失败改写量相符。此job无七项新materialization，不套用daily物化绑定验收。按本root各freq/year实际非空operation读JSON/receipt/stat核promoted，目标必须在26代码/七频/13年内，正式stat前4项匹配candidate_identity，输入stat五项全比；不得再读年度内容或重算摘要。空年份可没有operation。七项检查通过是解除前置，不从剩余21项中扣七。MACD/九转依旧停止，结束先汇报本项结果。

开发已完成：两执行文件和新增隔离测试；26项隔离回归通过，三Python文件默认Ruff/差异检查通过，CodeGraph explore/impact及sync/status已完成。独立实现审查未发现阻断。正式预检所有已冻结源/因子/目标身份相符，pool=1且空闲、两sensor停止、daemon无进程、空间满足要求。测试专属临时父目录已删除。启动原命令时仅另存当前shell PID后exec原CLI，便于预算/失败时对准确进程发SIGINT；这不替换任务入口或计算过程。正式结果随后单列，不以开发或预检通过代替执行成功。

### 14.8 实施、验证及正式结果

实际改动为`defs/stk_mins_qfq_factor_repair.py`、`defs/ops/stock_mins_qfq_factor_repair.py`及新增`tests/test_stk_mins_qfq_factor_repair_read_reuse.py`。公共writer/公式/检查事件schema/配置/任务入口未变。op日期观察值转为本地带时区表示，其本地日期值保持一致，并通过既有op测试；没有借本次修改自动日期策略。

| 硬口径 | 实现 | 验证证据 |
| --- | --- | --- |
| 同year/source只加载一次，诊断计算共用原始行 | `_execute_shared_source_repair`与`_load_repair_input`，年度/来源顺序，原列与坏行保留 | 真实DuckDB路径引用计数、三类坏源反例、七频字面结果；正式52次来源载入 |
| 原因子与日期、频率子集、空年口径 | 原planner/登记门槛；native原集合及旧derived选择；原allow_empty | 既有15项、空年/跨年及26外文件/新股保留；正式native65+derived26 |
| 原锁内生成、一次候选SHA、原子提升 | 原publication/prepared writer，TEMP逐批释放 | 真实os.replace故障与同root续跑测试；正式1932份receipt/stat全部匹配 |
| 输入变化拒绝、正常源身份不变 | 计划/每年factor/每来源的身份前后核对 | 同次运行诊断后改源及重入改源反例；正式收尾全部输入五字段stat不变 |
| 原运行身份及原七check | op传`context.run.root_run_id or context.run_id` | 原op隔离集成、正式7项同run事件与producer/batch/26名单hash核验 |
| 不额外大数据审计/测试残留 | 本run日志、JSON/receipt/stat收尾 | 无新增历史内容读取/额外SHA/性能样本，专属测试父目录与操作脚本已删除 |

既有15项和新增11项合并26项隔离测试全部通过（5.75秒），默认Ruff及差异检查通过。独立审查确认原始输入与金样本依据、子集/空年/锁和恢复行为，无阻断。测试明确禁止网络和整个正式卷，只用临时Parquet及隔离instance；环境先拒绝嵌套sandbox，测试未启动，改由工具授权在本机施加同一禁用规则后正常完成，未开放正式资源。

正式只运行一次：`f23ca4a2-b7c0-459f-9c55-764cb585db26`，SUCCESS，耗时112.514秒。26股历史改写native 1,380文件/20,202,727行，90/120派生552文件/318,655行，合计1,932文件/20,521,382行；1只新增股票未列入历史修复。七条blocking/passed均为本run、22日，producer/batch/代码hash一致，failed均0。现行消费者判断器实际查询这些控制记录后ready=true，七event ID为7726576～7726582。它同时表明历史已改写、后续MACD reconciliation仍需处理，未把ready解释为全部指标完成。

H/F/A日志与冻结清单相符：12,444源文件在52个year/source分组只载一次，历史因子每年一次；91个目标批次。S=464,280,822B、C=465,931,101B、P=453,330,654B，候选年度SHA累计读C一遍，正式重复SHA为0。按批准公式含预留，读46.889GiB、写1.356GiB，低于52/3GiB；不是硬盘实测IO。最后仅核本run事件、receipt/stat及输入身份，没有再扫历史。

原剩余21项不因这七条前置检查再扣七。两个下游sensor仍STOPPED，无活动run/daemon，等23日补齐后再启用的TODO不变。本轮未启动MACD、九转、板块或自动重跑。Git提交由后续提交阶段单独记录。详见[执行汇总](../../reports/datasets_recovery_20261022_20261024/factor_repair_20261022/summary.json)、[实际run与逐文件验收（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)和[消费者/控制状态（附件已清理）](../../reports/datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)。


## 15. 2026-10-22 MACD/KDJ日更及26股历史repair执行卡

### 15.1 目标、授权和现行依据

管理员明确要求“MACD/KDJ先推进，补数后也执行repair，使用现成job，做最小范围确认后开始补”。本轮只执行既有日更和历史repair，不改业务代码、公式、schema、配置定义、job、检查或sensor，不做真实性能样本和全局明细审计。日更14个资产与26股历史repair是一轮完整目标；不能只补当日状态就宣称历史指标已恢复。必要历史读取的准确范围及开销在最小确认后按根AGENTS单独记录批准；未获该范围批准前不读年度内容。

现行代码依据：`assets/stk_mins_qfq_macd_kdj.py`按前一交易日state计算；`stk_mins_qfq_macd_kdj.py`负责源读取、分段计算、年度文件按替换日期合并和state按代码合并；`checks/stk_mins_qfq_macd_kdj_checks.py`是原28个检查；`ops/gold_stk_mins_qfq_macd_kdj_repair.py`按因子repair的精确批次和26名单重算；`io/stk_mins_qfq_publication.py`保存候选及逐文件提升记录。既有MACD计划和R5 LLD的日更→scoped repair→completion顺序适用，但R5历史quarantine/备份、旧全公式审计及性能样本不作为本次执行步骤，统一遵守本文件现行staging规则。不是新增整链改造，重复读取合并仅为可选优化，不列为本轮前置。

### 15.2 最小确认结果及范围

证据目录为 `reports/datasets_recovery_20261022_20261024/macd_recovery_20261025`（跨零点沿用会话目录，JSON as_of为实际北京时间）。仅stat文件和只读控制记录，没有读取年度内容、重算指标或正式写入：

| 对象 | 文件/大小 | 范围和用途 |
| --- | --- | --- |
| 日更来源QFQ | 2025年38,241份/9,463,812,599B；2026年39,151份/8,112,813,903B，共16.3695GiB | 原daily source discovery的两年窗口；计算读取必要七列且日期不晚于22日 |
| 日更旧指标 | 2026年39,144份/18,441,797,624B，约17.175GiB | 原writer只替换22日行，保留其他日期；实际只写22日有行情的股票，预计38,990年度文件，不把旧目录代码数强制当当日对象数 |
| 前序state | 21日七份/1,754,990B | 全部存在，原writer继续按准确前序交易日校验 |
| repair来源QFQ | 固定26股2014～2026，1,932份/465,931,101B | 确认原discover会探测的2013年182条路径均不存在，不扩大到2013内容读取；上市前无年文件合法 |
| repair旧指标 | 固定26股1,932份/1,111,441,575B | 包含日更会更新的182份2026年度，执行前后以实际metadata修正预算 |
| repair目标state | 3,111交易日×7=21,777份；现有21,770份/3,837,207,000B | 只缺22日七份，由daily先生成；历史repair只替换26股行，保留同日其他股票 |

当前原factor status ready，来源run `f23ca4a2-b7c0-459f-9c55-764cb585db26`，batch `qfq_factor_repair:2026-10-22:1ecb794186a4`，26名单hash `41b905809024cb2d5d37c2feb4e3c3b9fb8c4a13919b19e4c8ffceea498da2d6`，范围2014-01-02至2026-10-22、3,111日。实际小输入身份与既有证据一致，3,111个动态分区已注册；两股票sensor STOPPED、daemon无进程、无活动run、共用writer pool=1且空闲。Lake/staging同设备，空闲约2,715GiB。不是读取因子和分钟全历史重新验证。

### 15.3 一次正常执行的预算及停止条件

预算是文件级保守模型，不是设备实际I/O。以Qd为两年QFQ文件大小、Id为2026旧指标、Cd为日更新候选指标、Sd为22日state、U为21日state、Pd为冻结日更输入；Qr/Ir/Cr/Sr/Pr分别为26股repair来源、旧指标、新指标、全state、冻结输入，B为旧历史state。正常一次：

- 日更读取上界按 `5Qd+U+2Id+4Cd+3Sd+Pd`，写入按 `Cd+Sd+Pd`，另加footer/记录及临时工作集。这里5Qd是便于预算的完整文件字节上界：一次计算读七列历史；另四次原检查读22日所需列/键，允许Parquet按日期裁剪，不能称为五次全列全历史明细读取，也不是新增四轮审计。
- repair读取按 `Qr+2Ir+B+2Cr+2Sr+Pr`，写入按 `Cr+Sr+Pr`；普通28检查不再跑第二次，结尾原14条completion不重扫历史。候选裸COUNT和schema/footer列为metadata，不虚算一遍完整文件。原publication的候选SHA正常一遍，正式文件不追加SHA。
- 为候选预留Cd≤20GiB、Sd≤4MiB、Pd≤0.5GiB；Cr≤1.25GiB、Sr≤4GiB、Pr≤2GiB；Ir_after暂以上界1.5GiB计，日更后只用26股182份当年receipt的大小差额更新Ir，B也加上七份新state实际大小。footer、stat、receipt、日志及最后验收另计读2GiB/写0.5GiB。
- DuckDB沿现有16GB内存、4线程和既有managed临时目录，不修改全局配置。临时I/O未实测，分别为daily和repair暂留读写各32GiB和4GiB，不设为0；这不是精准设备I/O保证。现场只观察原日志、候选/临时文件metadata和空间，不为测量额外读源；不能以512GB原配置上限作为本轮批准空间。

上述文件级合计约读254.223GiB、写64.254GiB，向上预留正常一次 **读272GiB、写72GiB、额外空间64GiB**，包含原检查、临时工作集预留和最后小型验收。actual Parquet读列/日期裁剪后通常小于该整文件模型，但本轮不追加性能样本来验证这一点。该预算不是自动硬限的承诺：原日志和candidate/frozen元数据表明模型前提不成立、临时工作集超额、空间不足或输入变化时，停止后续动作，不自行扩大。全轮暂留两小时观察窗口，长时间无业务进度先核阶段和进程，不凭日志为空重复启动。

失败停止，不自动第二次完整读取。日更可用原root身份及receipt核已提升部分；repair op当前没有传publication_id，不能承诺新run自动复用原receipt，也不把其恢复改进列作正常一次执行前的开发。中断后先仅用已有记录/stat明确已提交文件、剩余范围和开销，另确认继续；不得删正式数据、候选、恢复记录或做备份。正常执行范围批准不包含任意次数续跑。跨频/跨文件并非整体事务；每频完整候选检查后逐文件提升。

### 15.4 精确命令、顺序及配置

工作目录 `/Users/congming/github/goldenshare/lake_console/orchestrator`，DAGSTER_HOME固定 `/Users/congming/.goldenshare/dagster_home`，只用现有环境，不安装依赖。原job命令如下，第二条必须在第一条验收通过后启动：

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_stk_mins_qfq_macd_kdj_daily_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_stk_mins_qfq_macd_kdj_repair_job --config /Users/congming/github/goldenshare/lake_console/reports/datasets_recovery_20261022_20261024/macd_recovery_20261025/repair-run-config.json
```

repair配置完全复用现行sensor的结构，七项为qfq_factor_repair_trade_date=22日、start_trade_date=2014-01-02、完整七频、原26股票名单、reason=qfq_factor_repair:2026-10-22、上述hash与upstream_batch_id。结束日期由现行op从因子status推导22日，不加未知配置项、不传空名单触发全市场repair。

### 15.5 验收和完成量

1. daily：精确run SUCCESS，无失败事件，14项22日物化及28个原blocking check均通过，并绑定本run物化。不强制state行数等于5570；state可能合法carry-forward。允许26股暂待原历史repair，不把daily通过单独称最终恢复。
2. repair启动前：复用scope/status，确认daily已产生22日七state；其余历史state使用已冻结stat，不重新读内容。原op自己还会检查全部目标state存在，不以手工检查替代原门禁。输入文件来源/日期、26名单/hash/batch不变才执行一次。
3. repair：精确run SUCCESS，完整七频，原14条completion passed/blocking、partition=22日、covered起止与26名单/hash/source_upstream_batch_id一致；使用现成completion gate最终ready。repair不产生14项新materialization，不能套daily计数或手写绿事件。
4. 复用publication的真实记录/stat核已提升，source和范围外目标身份未变；不对年度内容再作全量读回或摘要、不重跑普通28检查、不跑check-refresh，不新增全历史分区事件。结束保存配置、run、check、数量、候选和预算结果。无测试临时资源；只读脚本归档后可移除本任务/tmp副本，正式候选/记录保留。
5. 两步完成才从原剩18项扣除MACD14项，剩九转4项。MACD/九转sensor仍STOPPED，待23日全部数据补齐后再启用的TODO不变；不因22日MACD完成而触发九转、Prod发布或23日补数。

当前状态：最小元数据确认已完成，业务代码未改、年度内容未读、正式job未启动。待本卡准确历史范围及预算获得明确批准后，正常执行一次。静态审查已核原job/op/sensor配置、writer和检查，不以旧文档名称推断入口。

### 15.6 获准启动记录

2026-10-26管理员已明确批准“批准，按此范围顺序执行”，覆盖15节具体日更/26股历史repair范围及读272GiB、写72GiB、额外空间64GiB一次正常执行。两位独立静态审查均确认原job顺序、七项配置、当前scope、预算公式和验收口径一致；没有业务代码修改或新测试。此前只读预检曾遗漏状态判断器所需event查询委托，修正只读包装后完成，年度内容及正式写入均为0，不涉及业务job失败/重跑。现在先启动daily，随后按15.5原验收推进。


### 15.7 本次中止结果与实际保留范围

2026-10-26原daily仅启动一次：run `b7b7a82f-cc07-4985-aa74-a0c3f1498936`，最终FAILURE，548.975秒。没有启动repair、没有新run或自动重读。正常执行卡的32GiB临时预留估低；00:16观察临时文件约57.705GiB，随后稳定在62,008,688,640B（57.7501GiB），已超过临时预留且接近整轮64GiB额外空间。此处只是TEMP文件大小/空间，不声称已测设备读写量，也不谎称272/72GiB总I/O额度已超。

1m此时已完成当日计算并冻结replacement，正在逐股票合并年度候选。第一次SIGINT使1m COPY以Query interrupted结束，但原job的独立30m步骤仍继续并完成；第二次SIGINT后5m在前置查询阶段中断，整run退出。这不是新run重试，也不是原28检查通过；实际停止方式已记录，后续不能假设一个子步骤失败会立即阻止所有独立步骤。

最终15/30/120三频各5,570份年度指标+一份22日state提升成功，共16,713文件、6个物化；对应原28项普通检查均未完成，26股历史repair尚未启动，所以本轮接受资产0、原剩18项仍待完成。1m有53份validated候选、1份building及5,517份未开始，未提升任何1m正式文件；候选和冻结输入、operation、receipt全部保留。5/60/90未写入本轮正式结果。

唯一收尾只读取receipt JSON及文件stat：三个completed operation的16,713份正式身份与candidate_identity前四项相符，原候选路径不存在；未提升目标身份未变，79,576条源路径/存在性记录身份均未变，无重新读取年度内容或SHA。原run已终态，pool active/pending均0，两个sensor保持STOPPED，无活动run。错误链均来自SIGINT，不据此声称计算公式错误或源数据不全。

进程退出后managed临时目录遗留20个本轮duckdb_temp_storage_*文件，总62,008,688,640B；启动前该目录为空，现无打开句柄。该清单是不可续跑的DuckDB工作文件，不是正式数据、候选、冻结输入或receipt。按lake_console/AGENTS.md第60行，已保存精确路径及五项stat并申请清理确认；在明确答复前不删除，清理结果随后追加。即使清理获准，也不因此重新启动job或repair。

本次未改业务代码、未新增性能样本/测试。下一次恢复先基于现有53候选/三个completed operation及失败步骤，明确可复用部分、剩余读取和临时空间；原一次正常授权不扩大为重跑授权。当前不编码优化、不扩大预算、不继续补数。证据见 `macd_recovery_20261025/summary.json`、`stop-reconciliation.json`、`daily-run-verified.json`、`spill-cleanup-plan.json`。


## 16. 原失败run清理和只补未完成步骤（2026-10-26已批准）

管理员明确批准清理20个DuckDB工作文件、保留正式结果和staging续跑记录、仅补未完成步骤；并明确不需要自行施加资源限制。本节覆盖当前恢复，旧15节额度和中断记录仅作为历史，不再据32GiB等人为阈值中断。本轮不改业务代码或原job配置，不新增性能样本、全局审计、备份、sensor或入口行为。

### 16.1 只清理20个已批准工作文件

目标仅为 `macd_recovery_20261025/spill-cleanup-plan.json`列出的20个精确绝对路径，原始合计62,008,688,640B，位于 `/Volumes/datasource/.goldenshare_duckdb_tmp`，均为本run新增duckdb_temp_storage_*文件。用途是已退出DuckDB连接的临时工作文件，不承担正式数据、候选、冻结输入或续跑职责。启动前空目录及无打开句柄证据已保存。

删除前一次性核全部普通文件/非符号链接/五项身份与清单一致、准确旧进程已退出、无活动run且无打开句柄；任何不符先停止清理并报告，不删除不在清单中的对象。仅逐文件unlink，不递归清空或删除目录；逐项把删除结果写入cleanup-result.json，中断后只对清单中尚存在且身份仍相符文件继续。旧清理计划和新批准、结果分别保留。不读取文件内容、不触碰Lake或staging任何文件。读写开销只为20次stat/unlink、小型JSON与lsof/控制查询，无Parquet读写，最多回收约57.7501GiB。验收为20路径不存在、目录和候选/receipt仍保留，记录实际空间变化。

### 16.2 续跑及验收的硬口径

原父run为 `b7b7a82f-cc07-4985-aa74-a0c3f1498936`，使用现行Dagster从失败恢复机制，只执行1/5/60/90频率及未完成原checks；daily阶段不重跑15/30/120，不为凑14物化而改写已完成文件。公共API重用原job定义、原配置/partition标签、父子关系及root publication身份，不手工计算或写Parquet。现有dg launch无从失败恢复参数，正式启动前按当前Dagster实现及官方说明核定最薄原job触发方式，细节随后补本节，不另造补数计算入口。

日更验收按父子两run合并：父run6个物化+续跑8个物化，原28检查均通过，分别绑定每项实际物化（已完成三频的父run、剩余四频的子run），不能继续套用“本run14物化”的首次执行断言。日更通过后才运行现成26股历史repair及原14条completion；repair按原批准26名单/2014-01-02至22日范围合并，其在三已完成频率中更新26股历史是此前明确repair需求，其他股票保留。daily“保持现状”不误解为取消历史repair。

不再自行设额外数值资源阈值、耗时阈值或据此发送中断信号；原job设置保持现状，记录正常业务进度、真实异常和最终结果。已有空间约2.6TiB，实际spill证据用于观察说明，不是新的人工限制。不存在新的性能测试/额外多轮全量检查授权。真实业务错误须据实际原因处理，不盲目重复整个job。所有已提升正式文件、候选、冻结输入和receipt保留，传递原root以按原实现复用候选；如出现身份/输入矛盾，先报告而不修改证据绕过。


### 16.3 清理完成与原job正式恢复入口

20条已批准路径均在删除前再次核对五项身份，无打开句柄、无原进程/活动run；逐文件unlink完成，目录保留，释放62,008,758,272B左右（文件合计62,008,688,640B，空闲差值含文件系统计费差异），无正式/staging文件删除。结果见 `cleanup-result.json`。

当前dg launch只提供新run执行，没有from-failure选项。为保持已完成三频不变，使用当前CLI同一 `recon_job_from_origin(parent.job_code_origin)` 还原原job，再调用Dagster公开 `execute_job(..., reexecution_options=ReexecutionOptions.from_failure(parent_id, instance), tags=dict(parent.tags))`。这是一层原job触发调用，不新增计算函数、writer、job定义或手工补数；run_config省略由公共API继承父配置，tags显式继承以保留22日partition，API自动继承parent/root关系。官方Context7说明及当前api.py、state.py已核：from_failure跳过成功steps，重执行失败/中断/未开始及必要下游。

独立只读审计继续使用noautocreate存储；本次已授权的正式启动阶段才按现CLI方式打开正式DagsterInstance。在执行原job之前，用其本身KnownExecutionState.build_resume_retry_reexecution检查恢复计划，必须恰4个写步骤（1/5/60/90）+28个原check，排除3个已成写步骤。此为获准范围校验，不是资源阈值；未通过时不调用execute_job，更不改检查绕过。执行函数raise_on_error=False保存真实终态，资源观察仅记录，不设人工中断条件。

父run原28checks均未执行，因此恢复计划应包含28项；子run只新增8物化，另6物化来自父run。子run28checks必须按12条绑定父run三频物化、16条绑定子run四频物化验收；producer/run/date/root均记录。日更期间原三频正式身份保持，原1m 53份validated和一份building交由原publication同root恢复逻辑判断，不手工删候选。重新准备/冻结同一1m输入属于原job恢复所需读取，已在管理员本轮“未完成补齐”指令内，不谎称完全不重读。其后原26股repair另行触发，按最后writer的receipt核正式身份，不拿repair后的合法26股变化否定daily保留验收。


### 16.4 日更恢复验收完成，进入原26股repair

恢复子run `31e25001-653a-40b8-8907-572891c30f95` SUCCESS，parent/root均指原b7 run、22日partition/config继承。只新增1/5/60/90的8物化，另6物化保留父run，28原checks全部passed/blocking、名称/日期及12父绑定+16子绑定核对通过。receipt/stat一次收尾通过：七频38,990年度+7份state共38,997目标均promoted、正式身份前四项匹配、候选路径不存在；15/30/120目录及字节与停止时记录一致，没有日更重写。

仅用receipt更新26股历史旧指标字节为1,111,895,691B、3,111日state字节为3,838,962,100B；没有内容重读、摘要或公式审计。此前20spill已删除；恢复期间仅记录正常资源进度，无自加阈值和人工中断。现在按15.4已批准原CLI/config启动一次26股全七频历史repair；原op校验scope和全目标state，写入后以14条原completion/现成gate及receipt/stat收尾，不重跑普通28checks。


### 16.5 全部执行与最终验收

20个原DuckDB工作文件已按精确清单清理；无正式/staging删除。原job from-failure子run `31e25001-653a-40b8-8907-572891c30f95` SUCCESS（593.289秒），原三频6项物化保留、只新增四频8项，28项原检查的名称/日期/producer/storage_id跨run绑定全部通过。七个daily operation、38,997个target的receipt/stat通过，保留三频目录和文件身份符合原记录；未重新materialize这些三频。

随后原repair run `b1be4dde-70ef-45b1-aff2-0c82686a79c5` SUCCESS（384.611秒），配置原26股/hash/batch/2014-01-02至22日/七频一致。14条completion全部passed/blocking、22日、显式26 scope及covered范围一致，现成completion gate ready且事件ID与本run14条一致。原7个随机operation通过本run日志定位，23,709份目标（1,932年度+21,777 state）receipt均promoted、正式身份前四项匹配且原候选路径不存在，无新SHA或数据正文读取。指标重算20,521,382行；state全文件写入85,106,077行含保留股票，并非全市场重新计算。

正常续跑阶段未设置额外资源阈值、未发送中断、未改业务代码/原配置、未做性能样本或全局审计。最终来源路径79,576条stat无变化，范围外595条目标无变化，无活动run、pool空闲、两个sensor STOPPED。DuckDB工作目录为空，新计算工作文件正常释放，所有staging恢复与审计资料保留。脚本归档后清除本轮/tmp副本，不清理正式staging。

本阶段接受14项，原剩18降为九转4项；completion14条不再次扣资产数。不启动九转或23日任务，待23日补齐再启用sensor的TODO仍在。原失败记录保留，最后结果以本节及恢复报告46.1为准。

## 17. 2026-10-28股票分钟链补齐：方案和执行LLD（2026-10-29）

### 17.1 目标、前序和授权边界

管理员在Silver因子修正提交`876cc6a8`后要求“继续推进分钟链补数，完成后向我汇报。并审计dg数据集在28日还有哪些有缺失”。本节只承接2026-10-28股票分钟链，以及最后一次该日DG物理完整性审计，不扩展到其他日期补数、Prod写入、读取优化开发或已完成周/月重跑。

因子前序已按[原修复LLD §25](dagster-stock-adj-factor-history-repair-low-level-design-v1.md#adj-factor-retired-retention-20261028)完成：九条指定旧因子已补回，28日Silver5,580行、40项原检查通过，Raw/生命周期不变。10月29日08:58只读运行核实，28日Raw run `a64e909f-cf02-4771-9504-6439d50c5584`及Silver run `ab9d6a45-3693-4729-9b31-edda681da85f`均SUCCESS；27日分钟链五阶段均完成，无活动run，五个分钟下游sensor仍STOPPED。复用这些产物，不重新下载或生成Raw/Silver，不重新检查27日历史行情。

补数动作已获本轮授权；本节列明的年度/历史全局读取仍须根AGENTS的具体范围批准，取得前不得启动业务job或开启这五个sensor。23日428GiB旧批准、因子小文件批准均不能替代28日范围批准。准备阶段只读当前代码、已有证据、控制记录及文件stat，未打开年度价格正文。

### 17.2 必须保留的顺序和名单来源

| 顺序 | 原job及目标 | 必须通过后才能继续的条件 |
| --- | --- | --- |
| 1 | `stock_mins_qfq_daily_update_job`，28日七频QFQ | SUCCESS、7物化、28项原检查，检查绑定各自真实物化；当日来源及2026年度合并通过原publication |
| 2 | `stock_mins_qfq_factor_repair_job`，只传`trade_date=2026-10-28` | 原job自动生成实际名单/起止/批次，7条真实完成check及现成factor guard ready，缺失/失败为0；无变化也由job形成完成依据 |
| 3 | `gold_stk_mins_qfq_macd_kdj_daily_update_job`，28日七频指标和state | 原factor guard通过后运行；14物化、28项原检查及真实绑定通过，当日state先生成 |
| 4 | 必要的`gold_stk_mins_qfq_macd_kdj_repair_job` | 只用现成decision/config函数承接步骤2实际产物，执行后14条completion及完整MACD repair gate ready；无历史改写时依原gate明确不需要，不向job传空名单或伪造完成check |
| 5 | `gold_stk_mins_qfq_nineturn_update_job`，28日四频九转 | 完整factor/MACD gate通过，必要前日seed及实际有界候选范围明确后运行；4物化、4原检查及真实绑定通过 |

日更对应25个资产：QFQ7、MACD/KDJ指标与state14、九转4。两个repair是额外依赖操作，不将其7/14条完成check当成新增数据集或要求不存在的物化。名单始终由原job生成，不把预估16股写进原因子job参数，不复制23日41股、27日6股或旧批次/hash。

本轮前序小因子只读证据得到28日16股因子变化、新上市0、无法判断0、缺前因子0；301139.SZ因28日退市，不进入当日repair。这只用于测算范围。若实际job产物改变，先核其输入身份及是否仍在批准范围，不人工删减名单或越范围读取。

### 17.3 当前实现依据和复用位置

复用§9/13/14/15/16已经实现并验证的writer、publication和恢复规则；业务代码本轮不改。日更job、`assets/stk_mins.py`、`assets/stk_mins_qfq_macd_kdj.py`、`ops/stock_mins_qfq_factor_repair.py`、`ops/gold_stk_mins_qfq_macd_kdj_repair.py`、两个repair guard、九转原planner及相应sensor为当前依据，因子对象口径沿`876cc6a8`。

真实配置及验收方法复用23日恢复报告`batch9/10/11/execution-card.md`和`readback.py.txt`，只替换业务日期、前序日27日、当前run/root、输出目录和真实产物；去掉旧固定股票数、日期数、文件数及旧run断言，保留原check/receipt/输入身份保护。已有readback不读Parquet内容、不计算价格或写事件。不能另写行情计算入口、把日线repair builder用于分钟因子job，或借本轮补数增加全量审计、性能测试和重复SHA。

两份23日readback还包含旧preflight/control/prepare入口，要求当时daemon停止、只核当时2个sensor并依赖41股的旧目录材料，与本轮DG继续运行、隔离5个sensor的事实不同。本轮不执行这些入口；临时验收模块只保留原daily/factor/repair的事件、guard、日志、receipt/stat验收函数及其依赖，保持函数业务断言不变，配置其28日和新报告根后用薄CLI调用。移除不再调用的旧准备入口不能连带删减验收保护。当前safe_to_launch及factor_gate必须来自本轮真实前序检查，不手写虚假的通过值；正式调用前先检查依赖闭包及语法，隔离静态结果不能冒充真实运行验收。

CodeGraph explore已核原job、repair消费者、同日daily/state前置和现成decision调用；GraphQL启动语义参考当前Dagster官方文档及前序已成功的`launchRun`。`dg launch`为本地进程执行，不用它替代当前正式webserver调度。观察器只负责提交原job、读取其事件/日志和receipt/stat，不加入数据计算。

### 17.4 必要历史范围、stat依据和预算

准备证据位于`/private/tmp/dg_minute_chain_20261028_20261029/history-stat-consumer.json`。28日QFQ来源按七频映射计D=56,815,263B；27日7份state1,755,431B、4份九转seed234,465B均存在。16股2014—2026年七频现有QFQ723份/148,790,838B，MACD723份/378,182,606B；原discover探测的2013年112条路径均不存在。

因子repair实际历史上界为2014-01-02至2026-10-28、3,115个交易日；四个唯一来源频率1/5/30/60的全市场Silver12,460文件47,423,932,430B，因子3,115份113,410,783B。不能按16股占全市场比例缩小共享日文件的读取成本。现有共享state21,798份3,844,228,112B，28日7份须先由MACD daily生成，repair合并时保留其他股票。

23日已存16.37GiB QFQ/17.27GiB指标只是旧参考，不能仅加28日差额就漏掉23/26/27三天变化。为避免逐批补读旧operation材料造成复杂拼接，本轮执行前对当前2025/2026七频QFQ、2026七频指标做一次文件路径/大小统计，不打开Parquet正文、不计算数据摘要；不重做已经有本轮stat的16股历史、Silver日来源或shared state统计。该一次metadata统计给出真实当前Qd/Id，后续仅按28日实际receipt的before→candidate差额增量更新，不能再次扫描整个年度目录。与沿所有旧批次补差额相比，此办法直接得到当前文件大小，且只是目录/stat，不是历史行情审计。

仍沿原Qd18GiB/Cd20GiB增长预留；16股年度部分小于23日41股，Silver历史及state增量仅约47MiB/5MiB，分项预算上界不增加。年度metadata统计约12万次文件stat、只保存按频/年汇总与必要控制身份，预计数秒至几十秒、内存为路径清单量级；不新增性能样本，不将文件大小当成实际设备I/O。后续预算由真实前序receipt更新。

| 阶段 | 本轮必要读取及写入 | 正常估读/写GiB | 额外空间GiB |
| --- | --- | --- | ---: |
| QFQ daily | 28日七频对应Silver/因子；合并实际股票2026年七频QFQ年度，保留其他日期，不读2025年QFQ | 34 / 9 | 12 |
| 因子repair | 原job实际名单的2014-01-02—28日七频历史；共享四频全市场Silver及相应因子、QFQ年度合并 | 52 / 3 | 4 |
| MACD daily | 2025/2026七频QFQ、27日state；合并2026指标年度并生成28日state | 280 / 88 | 96 |
| MACD repair | 实际因子产物对应股票2014—28日历史指标；3,115日七频共享state合并并保留其他股票 | 36 / 20 | 24 |
| 九转 | 2025/2026四频QFQ及27日seed；必要一次实际变化股票seed核验；更早历史仅限原有界候选实际代码、2014—2026年、合计≤1GiB，先stat再读 | 26 / 3 | 3 |

正常必要job各一次，合计保守估读428GiB、写123GiB、顺序额外空间128GiB。包括原job合并、计算、原检查、一次候选摘要、DuckDB工作文件及最后receipt/stat；不是额外428GiB审计，不是实际设备I/O测量，不新增运行限制或人工中止阈值。当前MACD两年装入是原实现开销，本轮没有进行读取优化，不能宣称算法必须读两年或已优化。

中断继续成本单列：最坏再计相应未完成阶段一次预算，仅供恢复前核定，不授权自动重跑。失败保留正式已提交结果及staging，先查原root/receipt/未完成unit及空间；不得另起root重放完整已完成阶段或手工回滚。原job资源、共享pool和锁保持现状，无套件安装、备份、Kopia、全历史事务或额外性能样本。

现行MACD历史repair op未向writer传publication_id，operation目录随机生成，不能承诺原生重执行会自动复用旧候选。若此步失败，必须先由原日志定位全部真实operation/receipt并核剩余范围，再制定具体继续办法；本轮正常一次授权不包含另起run盲重算。其他已传root身份的日更/因子/九转继续沿其原有恢复规则。

### 17.5 原生启动、配置和五步执行

工作目录为`/Users/congming/github/goldenshare/lake_console/orchestrator`，使用现有`.venv`；正式`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`。所有job通过现有`http://127.0.0.1:3000/graphql`的`launchRun(executionParams:...)`提交，selector固定`orchestrator/__repository__/<原job>`，等待真实run终态和本步验收后才提交下步。

步骤1/3/5的`runConfigData={}`、tag仅目标`dagster/partition=2026-10-28`及本轮审计标识；不改原job资源或业务配置。步骤2为非分区op-only，配置只有`{"ops":{"stock_mins_qfq_factor_repair_op":{"config":{"trade_date":"2026-10-28"}}}}`，不得传虚构partition或股票列表。步骤4从原`build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision`及`_run_config_for_repair_decision`取得完整实际配置，保存上游事件IDs、batch/hash、名单和日期后原样提交，不手拼repair名单。

临时触发器的审批、防重复提交及前序保护必须显式拒绝，不以Python优化模式可删除的assert承担。前序验收除通过标记外，还须核28日、对应mode/job、SUCCESS及run id等于本轮native-run记录；factor gate的producer/date必须绑定本轮原因子run。MACD repair配置须等于已保存的原builder输出，且日期、起点、七频、实际名单/hash和upstream batch与本轮factor gate一致，并与本轮MACD daily run及decision来源绑定。误放23日或其他run的合法配置/通过材料仍须在提交前拒绝，不能依赖原op替本次执行意图识别错日。启动前以纯临时材料验证拒绝路径，不能请求正式GraphQL作测试。

每步只读取精确run的有限事件和原日志，记录原job进度；观察请求超时只影响观察，不能擅自取消job或重交。原publication路径从真实日志/metadata定位，不根据样本URI猜整个年度产物。day28动态分区已随前序存在；若实际缺失或原guard拒绝，先说明而非绕过，不擅自注册全历史。

### 17.6 逐步验收、并发和sensor恢复

开始前复用08:58运行记录及必要增量状态核无同链活动writer、pool/空间及正式Lake/staging同设备；五个分钟sensor保持STOPPED直到五步完整通过，避免自动接续与手工提交重叠。不关闭DG/daemon或其他数据集，不清cursor或改调度参数。

九转sensor现行代码只等待QFQ、因子repair和前序九转，并不等待MACD历史repair；不能声称sensor天然保证本节五段顺序。本轮由逐job提交和五开关保持停止来保证先MACD repair、后九转。

日更核精确run、业务日期、资产/check名称、passing/blocking及目标物化storage id；两个repair按原guard核本批真实完成记录及一致的名单/范围/batch/hash，而非只看SUCCESS。逐频只核真实operation/receipt的promoted和正式目标stat前四项、候选已提升；不在repair合法覆盖后再用daily旧identity要求保持不变。完成后按最后writer的receipt核最终身份，原每日checks不为“再绿一次”重跑。

现行旧Raw/Silver、因子及普通日更检查有原生event partition为空的存量记录，23日原readback明确允许None，但必须准确绑定本次目标日期的真实物化。准备入口最初额外强制旧check原生partition非空，随后又错误地要求因子每条check都具备日期metadata；这两项额外假设均不符合原验收实现，在任何新年度/价格读取和job启动前已拒绝并纠正。原口径为：check passing/blocking、asset及target run/storage id对应28日物化、物化partition为28日；日期metadata或原生partition若实际提供，不能与28日冲突，缺失时由已强绑定的真实物化日期证明，不能填造日期。已取得三份精确run的完整39条check小型证据，后续复用，不反复读取。此处仅观察既有事实，不修改正式checks、补事件、放宽数据检查或重跑上游；事件原生分区缺失单独记录，不能宣称它已修复。

九转先检查原gate及27日seed是否可用。若实际factor repair改写历史，而现有receipt不能证明旧连续计数不变，仅对job实际变化股票×四频按原九转公式计算其必要历史，再筛27日末根，比较时间、up_count/down_count及两个九信号；无实际前史的新股不伪造seed。价格重定价和舍入后，旧checks绿色或文件stat一致不能证明旧连续计数仍然正确；原seed读取代码直接承接旧计数，候选函数也不校验这一点。该核验最多一次，沿23日batch11既有规则，不回写seed或重跑其他日期。出现差异立即停，明确影响与处理方案，不手改seed、硬算28日或虚构九转repair job。

准备先后固定为：先用原`_bounded_candidate_codes`取得真实候选（只读正常2025/2026来源及27日seed的必要键），再对原候选和实际因子变化股seed所需路径按原helper会枚举的全部`year=*`路径stat，按路径去重，核所有实际年份在2014—2026且更早历史合计≤1GiB；通过后才执行一次必要seed历史比较，最后形成允许启动九转的前置。不得先做seed完整历史读取后才知道候选合计超范围，也不能先过滤批准年份再让原planner发现范围外文件。16股当前2013缺失证据只用于这16股，不能代替原候选其他股票的年份核对。通过后才交原planner；不调用完整planner先读未知历史、复制旧候选或篡改名单。超出批准范围或前序身份冲突时停止，不能用填值、Raw兜底或手工绿色事件绕过。

本次1GiB范围按这些seed/候选会实际枚举的2014—2026全部文件去重合计，包括其中2025/2026文件，不能仅加总2025年前文件而放大候选读取。正常两年全市场来源另按原26GiB九转预算计费；这里的1GiB是已获准候选/seed读取范围核定，不是给正式job增加内存、时间或运行中断限制。

全部完成后恢复原本RUNNING的5项：`stock_mins_qfq_daily_sensor`、`stock_mins_qfq_factor_repair_sensor`、`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`、`gold_stk_mins_qfq_macd_kdj_repair_job_sensor`、`gold_stk_mins_qfq_nineturn_update_job_sensor`，只改这5个开关、不改cursor；只读确认恢复结果。THS等独立数据集缺口不作为继续关闭已完成分钟链sensor的理由。

### 17.7 最后一次28日DG物理完整性审计

用户明确要求分钟链补齐后列28日剩余缺口。沿`audit-dg-datasets-by-date`的当前catalog、路径分类和后端计数，只运行一次该日完整性审计；不以job绿色替代文件/数据库真实行数。

原skill脚本年度分支还计算distinct代码和时间min/max，本轮缺失判断只需计数，不为这些非必要输出扩大读取。复用原分类、直接分区及serving计数；年度分支临时入口仅`SELECT count(*) ... WHERE trade_date=DATE '2026-10-28'`，不取代码/时间/OHLC、不导出明细，不读2025年文件或其他日期。连接复用现行configured DuckDB的existing_no_spill，不隐式新建未知临时目录、不修改业务或skill源码。具体适配及夹具验证如下，验证通过前不执行正式审计。

具体入口：在本轮`/private/tmp/dg_minute_chain_20261028_20261029/`动态载入原skill脚本，复用`_load_catalog`、`_audit_trade_date`、直接Parquet分类和既有后端连接。仅替换该模块的年度汇总和CH汇总：年度对目标2026文件族只做带28日WHERE的`count(*)`，CH只对原两个白名单表做28日`count()`；不输出distinct/min/max、无效键统计或价格字段。PG原同日只读count保持不变。原模块局部`duckdb`引用改为连接工厂，工厂通过`connect_configured_duckdb(DuckDBConnectionSettings(temp_directory=Path('/private/tmp')), temp_policy='existing_no_spill')`取得连接，close退出原context；不得改真实duckdb模块的全局connect，以免递归或影响其他任务。该限制仅作用本次只读审计，不施加给业务job。

年度文件族无匹配路径才记缺日期行；有文件但查询失败、直接文件不可读或后端不可用都归未核实，不沿原汇总把unreadable说成缺失。生成最终统计前重整三类叶子状态，确保有数据、真实缺失、合法零行、未核实互不混淆，总数与catalog分类一致。目标分区文件只读count，真实零行与文件不存在分列；不把本审计当成质量/readiness验收。

临时入口编写后，使用独立字面小样本的临时Parquet验证目标日期count/不存在日期/缺文件/不可读；捕获年度和CH请求，断言只有count和28日过滤、未知表拒绝；证明模块局部替换不改变真实duckdb.connect及连接最终关闭。隔离测试不访问正式资源、不安装依赖，报告入口自身不留业务临时文件。测试及独立复核通过后才执行正式一次。

当前catalog静态分类为180项＝直接分区138＋年度族14＋Serving7＋明确排除21，正式审计仍以运行时catalog为准，不硬编码清单。年度14族为2026年QFQ及MACD，按已有全年文件总字节约25GiB作极保守读取上界，最终审计另预留读32GiB/写8MiB/空间16MiB；实际上只需日期列和Parquet元数据，不宣称读取完整文件全部字段。该计数开销与业务补数428GiB分列，不暗算成原job读写，也不为观察重复执行计数。

全部catalog必须被审计或明确排除；真正全量快照/健康资产列为非按交易日数据集，合法零行单列；数据库不可用列未核实，不说成缺失。两端CH及Prod PG均只读、限定28日，仅计数。此步骤受根AGENTS统计计数例外覆盖，不对全市场明细作额外比对；预算读写仅包含计数/目录/报告，年度行数查询不重复运行。报告保存时间、catalog/审计/排除/有数据/缺失/未核实/零行数量与缺失清单；不自动修复本次分钟链之外的缺口。

### 17.8 材料、清理及本步状态

本轮证据目录固定`lake_console/reports/datasets_recovery_20261028_20261029/`，正式启动请求/返回run id、每步验收、原repair产物及最终物理审计分开保存；准备阶段材料从本次/tmp目录逐字节归档。临时编排只触发原job、观察结果和stat，不计算或写Parquet。结束时仅精确删除本轮已归档的临时脚本和隔离夹具，保留正式结果、候选/receipt/恢复依据；不清共享工作目录或其他任务文件。

当前状态：用户已授权补数及最后审计；代码及只读准备已核，本节年度/历史具体范围尚待单独批准，未触发28日下游job。批准及实际执行结果随后逐项追加，不能预填完成。

### 17.9 准备验证记录（不是真实执行结果）

三类必要临时入口已经完成有界验证：计数入口14项隔离测试及root源码复核通过；原readback适配保留33个验收函数逐字节不变，20项静态/合成检查通过；薄触发器独立审计发现的assert及旧日期/批次误绑定问题已先补回§17.5并修正，普通Python与优化模式各32例通过。缺批准、错日期/job/run、factor producer、MACD批次/名单/hash/频率/起点或重复intent均在请求前拒绝；未知启动结果保留intent且不重交。

准备验证使用纯临时字面材料和模拟请求，真实网络、正式DB/Lake访问均0；夹具目录已清理。不能将这些结果宣称为原job、真实builder、repair或正式审计已通过。来源、适配diff、测试和当前等待批准状态见[本轮报告](../../reports/datasets_recovery_20261028_20261029/README.md)。业务代码未新增修改，现阶段原job启动0、最后计数审计0，具体历史范围审批仍待管理员回复。

### 17.10 具体范围批准及开始执行

管理员已回复本轮具体范围问题：“批准，按原job及repair顺序执行”。批准对象为§17.4的28日五阶段正常各一次、估读428GiB/写123GiB/额外128GiB及所列必要seed/有界历史范围；不扩大到其他日期补数，不自动重跑失败阶段。批准原文、问题身份及范围保存在本轮报告`history-approval.json`。§17.8—17.9的等待状态保留为准备阶段历史；现在先核必要增量控制及输入身份，通过后依次启动原job，后续逐项记录真实结果。

准备阶段08:58:31的一次完整年度metadata统计已从原exec session 95290追回，原命令终态exit0、统计18.648秒、正文读取0；没有再执行一次年度目录扫描。原始证据为本轮`recovered-metadata-stat.json`，保留其真实观测时间，不以归档时间替换。基线为2025/2026七频QFQ77,399份17,709,333,522B，其中2026年39,158份8,245,446,955B；2026指标39,158份18,830,843,744B。该统计发生在28日下游尚未启动且五sensor停止之后；正式前只核此后无同链新run即可复用。其后仍只用28日receipt增量，不重复stat整个年度目录。

### 17.11 前两步完成，MACD日更已启动

28日QFQ daily run `94384f7b-0b77-4317-998c-32da2a5e88dd` SUCCESS，耗时877.983秒；7物化及28条原检查全部通过、绑定正确，38,990份2026年度目标的原receipt/stat通过，候选合8,264,362,172B；原输入身份保持。只通过原job更新28日并合并年度，未重新下载Raw/Silver、未执行额外价格/SHA审计。

随后原因子repair run `816a0d01-a56f-4f06-bdb3-1a7e0c05a793` SUCCESS，7条真实完成check及原guard ready；原job实际选择16股，范围2014-01-02至2026-10-28、3,115个交易日。原生510份、派生208份年度改写，scope/hash/batch及输入身份核对通过，批次为`qfq_factor_repair:2026-10-28:3afb0b0b08f6`。名单未人工指定。源日志累计四频Silver读取文件stat合47,423,932,430B，与批准来源一致；不将stat字节称为实测设备I/O。

MACD前置用真实初始年度基线及这两步receipt净增，Qd变为17,748,649,275B；正常估读264.237GiB/写85.004GiB，仍在批准280/88GiB分项内。27日state原readiness通过，五sensor仍停止、pool空闲。10:00:43通过原job提交MACD daily run `13e1b027-22c4-4268-950d-aaac9b5be9d2`。其历史repair和九转尚未提交，后续结果继续追加；验收材料见本轮报告batch9/batch10。

### 17.12 MACD日更验收完成，指标repair启动

MACD daily run `13e1b027-22c4-4268-950d-aaac9b5be9d2` SUCCESS；14物化、28条原检查及对应storage id绑定全部通过，七频年度指标及28日7份state均完成原receipt/stat验收。日更后保存真实target身份，后续repair合法替换的目标按最后writer回执核，不重新要求daily旧身份保持。

通过原decision/config函数、真实factor batch及本次14物化readiness生成16股repair配置。必要历史预算估读28.427GiB/写16.5GiB，仍在批准36/20GiB分项内；QR150,264,957B、日更后旧指标378,461,902B、共享state3,845,983,660B均由原产物和必要stat得出，无额外价格读取或全目录扫描。10:20:19提交原repair run `44caf58c-a1d9-4e37-b525-b82cda3179b3`一次，待14条原完成记录及完整gate通过后才进入九转。未重跑daily、未手改名单，未添加资源或时间限制。

### 17.13 五阶段补齐完成、sensor恢复及最后单日计数

2026-10-29已按本节顺序完成2026-10-28股票分钟链。MACD/KDJ历史repair run `44caf58c-a1d9-4e37-b525-b82cda3179b3` SUCCESS，耗时300.672秒；14条原完成检查全部通过，completion和完整factor/MACD检查均ready，事件、起止日期、16股名单/hash及上游批次一致。实际发布723份指标年度文件，重算6,906,176行；合并21,805份共享state后共85,262,709行，包含保留的其他股票，不表示重新计算全市场。原operation/receipt与正式文件stat通过。证据：[指标repair验收（附件已清理）](../../reports/datasets_recovery_20261028_20261029/README.md#报告附件清理2026-11-01)。

随后先核27日九转原产物，再对本次实际变化16股的30/60/90/120分钟末根seed进行必要核验，64组全部匹配、差异0；有界查询所得候选历史52份、2,230,410B。候选及seed按路径去重合468份、17,922,588B，包含2025/2026年，按这一合计核对未超已批准的1GiB范围。原九转job run `a9f7bedc-5041-48ab-8171-20c388bff5ea` SUCCESS，耗时68.201秒；4物化、4条原检查及真实绑定通过，28日四文件共94,690行、241,902B，receipt/stat及输入身份验收通过。没有重跑27日九转。证据：[seed及候选范围（附件已清理）](../../reports/datasets_recovery_20261028_20261029/README.md#报告附件清理2026-11-01)、[九转验收（附件已清理）](../../reports/datasets_recovery_20261028_20261029/README.md#报告附件清理2026-11-01)。

本轮5个原job各执行一次、全部SUCCESS，无失败重跑或原生重执行。QFQ日更7项、MACD/KDJ指标及state14项、九转4项，共25个28日资产补齐；原检查合计81项全部通过：28条QFQ日更检查＋7条因子repair完成检查＋28条MACD日更检查＋14条指标repair完成检查＋4条九转检查。两个repair均消费原job自动确定的同一16股范围，没有人工指定名单，也未重复执行已完成的Raw/Silver或Silver因子修正。

10:40:16按批准恢复本节列出的5个分钟sensor，逐项读回均为RUNNING，未清理或重置cursor，未改其他sensor、daemon或资源设置。此前各节STOPPED是执行期间的历史状态，恢复待办已关闭。证据：[sensor恢复记录（附件已清理）](../../reports/datasets_recovery_20261028_20261029/README.md#报告附件清理2026-11-01)。

本轮39个`/tmp`中间文件合611,044B，已逐字节核对归档后删除，临时目录已移除；正式staging及其提交、恢复记录保留。精确清单和结果见[清理记录（附件已清理）](../../reports/datasets_recovery_20261028_20261029/README.md#报告附件清理2026-11-01)。

最后仅执行一次28日DG物理计数：catalog180项，实际审计159项、明确排除21项；157项有数据，缺失2项，未核实0、零行0。本轮分钟链25项均有数据；剩余缺失为`gold_major_index_daily_nineturn`和`prod_core_index_daily_nineturn`。计数原文单独保存在[最终物理审计](../../reports/datasets_recovery_20261028_20261029/final-physical-audit.json)，完整说明见[本轮报告](../../reports/datasets_recovery_20261028_20261029/README.md)，不以任务成功代替物理计数，也不在本轮自动补齐这两项独立缺口。

批准的估读428GiB、写123GiB和额外空间128GiB是执行前保守预算。上述文件数、行数和文件字节来自原产物、日志及receipt/stat，不是实测设备累计I/O；收尾未追加年度全文读取、普通检查重跑或数据SHA校验。

## 18. 2026-10-28剩余两项主要指数日线九转补齐方案和执行LLD

### 18.1 授权、目标和禁止项

管理员在§17分钟链完成及单次计数之后要求“将28日的两项补齐吧先”，随后要求继续推进。本步仅补`gold_major_index_daily_nineturn`和`prod_core_index_daily_nineturn`在2026-10-28的数据，沿本轮恢复报告继续记账；不改业务代码、不重跑上游Raw/Silver/主要指数日线Gold或股票分钟链、不补23/26/27日THS、不重复全目录审计，不修改sensor、cursor、并发、资源或daemon。

### 18.2 当前代码及有限来源

原`jobs/major_index_nineturn_update.py`只选择一个Gold日线九转及其聚合blocking check；`assets/major_index_nineturn.py`从`cn_a_index_trade_days`取上一注册交易日，使用`major_index_nineturn.py`选择截至28日最近20份`gold/market/major_indices_daily`日文件和27日九转结果延续计数。只写28日七列Gold九转。当前stat为20份来源合52,537B，范围2026-09-23至2026-10-28；27日九转文件存在，28日目标不存在。原28日物理计数已确认当日主要指数Gold11行，最后以原job实际N和原检查为准，不把11写成publisher硬上限。读取只投影原公式所需代码、日期、close以及原seed列，是本次job必要的有界历史上下文，不做全历史读取或额外历史明细审计。

Gold原writer在`data_lake_staging`生成独立候选，核schema、日期、键、行数、值域和来源身份，核对后`os.replace`提升单文件；该writer没有股票QFQ式publication JSON或跨run checkpoint，不能虚构回执或承诺失败后自动续跑。原finally会清理自身剩余候选，本步不改变此行为或额外删除现场；正式目标已替换时保留现状，先查真实步骤和物化/check事实，禁止盲目整链重跑。

原`jobs/index_daily_nineturn_prod_core_sync.py`独立选择Prod资产及一个check。`assets/index_daily_nineturn_prod_core.py`先按原六项Gold完整性规则核同日源，再显式取七业务列；`prod_db/index_daily_nineturn.py`在同一事务内只替换`core_serving.index_nineturn_daily`的28日行，读取同日业务内容hash一致才提交。原Prod check再只读同日比对业务内容；published_at不进业务hash，INSERT page_size100不是业务行数上限。不会清表或改其他日期。CodeGraph explore已核原两job及Gold消费者，publisher实现及22/23日原执行证据另作静态独立核对；无接口、契约或前端改动。

### 18.3 执行前只读核验及唯一触发方

复用23日`batch2-3-index/execution-readback.py.txt`和22日`batch5-index-nineturn-prod-readback.py.txt`的精确run验收语义，但不整份运行：旧脚本要求daemon停止、全五步日线链及旧邻日、固定行数，与本轮不符。本步薄观察入口只处理这两个job、28日及必要前序，使用现有orchestrator `.venv/bin/python3 -B`；正式storage设置只读和`should_autocreate_tables=False`，不初始化instance。

先核动态分区已注册、上一日27日、28日主要指数Gold和27日九转的最新物化及原blocking checks准确绑定、必要21个输入文件stat、正式Lake/staging同设备与空间、同日同链活动run、两条相关sensor实际状态；另对Prod27/28/29日只做一次分组count保存基线。只需已有上游证据和必要stat，不重算公式、不重跑原checks。运行中上游或seed身份变化即停止后续提交。

`prod_core_index_daily_nineturn_sync_job_sensor`默认STOPPED不能证明实际停止。当前若RUNNING，则Gold通过后优先跟踪其唯一自动Prod run，不再手工重复提交；若STOPPED，才手工提交Prod。Gold本身若已有同日活动run则跟踪原run，已有有效成功及绑定检查则复用。若Gold自动sensor当前RUNNING，先核其最近真实tick：有同日活动/提交则跟踪；当前因29日尚未注册而在整窗检查处SKIPPED、29日仍未注册且28日无活动run时，可以手工精确提交28日，不为此登记29日或停用sensor。该例外在提交前再次只读确认；不与能够自动提交28日的评估并行。目标已有但没有可核验的成功记录、同日多个活动run或输入冲突时停止说明；不停止整个DG或其他任务。原失败run不自动重试，本次若复用的来源已修复，允许按本次意图运行原job正常一轮，失败仍即停。

### 18.4 原生提交、验收与收尾

工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，正式GraphQL `http://127.0.0.1:3000/graphql`，selector固定`orchestrator/__repository__`。以现有`.venv/bin/dagster-graphql --remote http://127.0.0.1:3000 --file <launch.graphql> --variables "<本步JSON文件的完整JSON文本>"`执行原`launchRun`，runConfigData空对象，tag只含`dagster/partition=2026-10-28`及本轮标识；先Gold job验收，再Prod job，不直接调用writer或手写数据库补数。

启动前保存唯一intent和完整请求，返回run id立即归档；响应未知先只读查同日同job，禁止重复提交。观察请求超时不取消业务run或重交。每个精确run按有界事件核SUCCESS、准确资产、28日物化、原check passing/blocking、target run/storage id一致；有原生partition时必须为28日，不补造事件。Gold原六项规则全部通过、来源身份保持后才进入Prod；Prod核`row_count=read_back_row_count=N`和原check的expected/observed内容hash一致。最终只对28日Gold文件和Prod同日做count核实际N，同时复核27/29日目标stat/Prod计数与基线一致；不再次全目录审计、不额外全表或历史hash。

Prod事务失败回滚；若提交成功后事件或check失败，不当作未写入，保存原状态并先核28日事实，不自动回滚、覆盖或重跑Gold。正式结果、staging及失败原日志保留。执行材料固定在本轮报告`index-daily-nineturn/`；辅助观察脚本只存本轮精确`/private/tmp/dg-index-nine-20261028-20261029/`目录，完成后逐字归档为文本并删除本轮临时文件，不清共享目录。

### 18.5 性能预算与验收边界

范围是20份小型日线文件、1份前序九转、目标1日/11个物理seed指数，源请求0。原Gold正常一次预计数秒，Prod原22/23日执行约6秒，队列和解释器加载另计；不做性能测试。正常连原计算、原检查、精确事件、最后同日计数及报告保守预算读8MiB、写1MiB、额外空间8MiB；中断后的必要状态确认和未完成部分另预留相同额度，仅用于恢复前判断，不授权自动再跑。现有资源配置不改变，不新增运行中断限制。

本步不开发业务代码，原公式与publisher测试及既有22/23日真实成功证据复用；只做临时观察入口的语法/静态范围核验，不拿正式环境试跑测试。真实验收是本次两job原检查和限定两项物理计数，不宣称重新审计159项或历史THS已齐。若两个缺口均完成，可以把10:40计数的157/159按本次两项后续证据更新为28日159/159，但必须明确是原计数加本次两项收尾推导，没有再次全目录审计；原JSON保留不改。

执行前实际状态：两sensor均RUNNING、28日两job尚无run；Gold最近两tick因29日缺注册跳过。预检21份输入合53,860B，上游28日Gold及27日九转的原检查均已验收，Prod27日11行、28/29日0行。采用上述精确28日Gold手工触发、Prod原sensor唯一自动接续；自动Prod必须以原build_batch_id/build_upstream_triggered_run_key产生的dagster/run_key、sensor名、job和日期对应本次Gold run，不能只取最新同日run。

### 18.6 两项正式完成及必要收尾

2026-10-29 12:23已完成。实际两sensor均RUNNING；原Gold sensor最近两tick在整窗注册检查因29日未注册跳过，28日自身注册、来源及前序检查完整。提交前再次核这个事实、无28日活动run且Gold目标缺失后，只手工提交一次Gold原job，run `d4c794f5-4939-482e-a93c-4ba70d3eadd7` SUCCESS，4.845秒，11行及一项原blocking check通过。未注册29日、未改sensor或cursor。

随后由原Prod run-status sensor自动提交run `22dbd172-3a3c-4c51-bb1f-075eb31256bf`，SUCCESS，5.369秒，11行及一项原check通过，read_back_row_count与Gold一致，expected/observed业务hash相等。验收以本次Gold计算的原upstream batch/run_key及sensor名、job、日期绑定，未额外手工提交Prod。

最终只count这两项：Gold与Prod均11行。必要21份输入stat、27/29日Gold目标stat及Prod邻日计数保持；原两sensor仍RUNNING。本步没有业务代码变更、正式job重跑、资源限制、全目录重复计数或额外历史明细比对。原10:40计数157/159加本次2项恢复，得28日159/159按日资产有数据、缺失0；原计数JSON不改，后续证据单存[两项最终收尾](../../reports/datasets_recovery_20261028_20261029/index-daily-nineturn/final.json)。该结论仅针对28日；23/26/27日THS历史缺口仍未处理。临时辅助材料先归档后精确清理，正式结果及staging保留，详见本轮报告第7节。

## 19. MACD/KDJ日更读取修正LLD（2026-10-30）

### 19.1 本步目标、状态和证据

业务要求逐条对应[MACD/KDJ方案第17节](dagster-stk-mins-qfq-macd-kdj-indicators-plan.md#17-macdkdj日更读取修正方案2026-10-30)。本节目标只限七频正常日更的数据准备与等价共用代码提取；历史repair的日期/代码/计算组织、history/bootstrap及其他数据集本轮不优化。以下为编码前确认的设计约束；设计文档提交后管理员已授权开发与隔离验收，实际实现、验证及未覆盖边界见第19.12节，不能仅凭设计条目存在就认定通过。

证据及其适用范围：

| 证据 | 结论/限制 |
| --- | --- |
| 当前`defs/stk_mins_qfq_macd_kdj.py`的discover、source preparation、segment、replacement和writer | 目标年/上一年发现；全历史临时表后排名；公式只对目标行递推；完整结果之后才bind |
| 当前`assets/stk_mins_qfq_macd_kdj.py`与连续性guard | 原qfq/factor-repair门禁、exact previous expected state、root run身份和multi_asset保持 |
| 当前`ops/gold_stk_mins_qfq_macd_kdj_repair.py`与history helper | repair按实际名单读取，每频传完整repair日期范围；history另按频率/年调用；均不能误切到新日更准备函数 |
| 当前`io/stk_mins_qfq_publication.py`和staging隔离测试 | 完整冻结文件SHA及targets精确匹配、逐文件记录、同设备提升、冲突拒绝，不支持每股单独bind后拼接 |
| 当前`src/foundation/clients/local_lake/stock_mins_reader.py`、`StockMinuteQueryService`、股票详情API和页面 | 本资产有真实只读消费者；页面按时间对应行情与六项指标。保留原路径/12列schema/键/数值/版本/分页，不能宣称没有API消费者；本轮未核该能力的运行态开关 |
| 29日run `98f3d25c-1380-47da-b079-b15701bdbbce`的已有日志 | 1m在准备计算表时失败，六频12物化及24检查已成功；不能推定30日实时状态，也不能确定DuckDB内部4GB对象的调用方 |
| 本文第17节及[年度metadata基线（附件已清理）](../../reports/datasets_recovery_20261028_20261029/README.md#报告附件清理2026-11-01) | 2026-10-29 08:58、28日QFQ更新前：七频2026 QFQ 8,245,446,955B，2025 QFQ 9,463,886,567B，2026指标18,830,843,744B；旧stat不是新执行的精确目标大小 |
| 原方案第8.5节 | 历史全市场benchmark确实存在，但不是当前日更读取范围、内存或4GB异常验收 |

本轮CodeGraph explore/impact覆盖主writer和wrapper；decorated repair入口及bootstrap消费者由源码补齐。依据优先级为当前代码/合同、来源明确的历史记录、未来设计；不能只凭CodeGraph未显示调用方就删改公共函数。

### 19.2 输入、输出与禁止项

- 输入仍为单个`partition_key=D`、一个原频率、原discover得到的`Y/Y-1`现存文件、原exact previous expected state以及原root publication身份。
- 源字段读取显式投影`ts_code/freq/trade_date/trade_time/high/low/close`。QFQ生产者的DATE/TIMESTAMP及stock-year合同来自`run_contracts/asset_column_schemas.py`和`stk_mins_qfq.py`，不是从待写SQL反推夹具。`hive_partitioning=false`，不把目录推导列当文件内部合同。
- 输出仍为`StkMinsQfqMacdKdjReplacementTables`对应的当日indicator替换表、完整当日state替换表和原整体初始化标记；wrapper原返回类型/字段、资产metadata和checks不改。
- 不扩读`Y-2`，不引入Raw/Silver/Prod/Tushare替代来源，不新增正式LIST/JSON字段；不修改EMA/KDJ公式、参数、1024根分段、前日选择、schema、paths、版本、run key和repair时序。
- 不新增不足8根失败条件或股票数量限制。原集合1—7根仍使用实际条数；不存在早期行时仍按原seed规则处理，不能声称因此已经核实真实上市日期。
- 不把每股或每64股变成新job、publication、正式提交或恢复单元；不改现有候选/摘要/receipt，不用新入口绕过它们。
- 不因本次读取优化重算已完成历史、重建历史state、迁移API/前端、清理历史DG事件或重跑已完成repair批次。若新计算结果、state或原消费者不能兼容，停止并修正本轮实现，不通过重刷历史消除差异；原数值容差不得提高。正常上游因子变化已要求的repair范围/去重不因本条改变。

### 19.3 函数分工与共用代码提取

仅在`defs/stk_mins_qfq_macd_kdj.py`内按下表拆分职责；不新增对外CLI/job或跨工程依赖。私有名字表达长期职责，不带阶段编号。

| 原代码 | 私有职责（实现对账见19.12） | 保持方式 |
| --- | --- | --- |
| `_create_macd_kdj_source_tables`末尾创建work表 | 提取`_create_macd_kdj_indicator_work_table(connection)` | 原历史准备仍在同一时机调用，DDL/schema原样；日更仅在批次前创建一次 |
| `prepare_stk_mins_qfq_macd_kdj_replacement_tables`中从work生成indicator/state的部分 | 提取`_build_macd_kdj_replacement_tables_from_work(...)` | 继续使用原排序和state合并SQL，初始化标记由调用方传入；不重写历史state关联 |
| 原公共writer中prepare返回之后的空结果、分组、bind、年度/state候选和promote | 提取`_publish_macd_kdj_replacement_tables(...)` | 接收已打开的connection/publication、原日期/股票/flags及replacement结果；原分支、返回值及调用顺序原样迁入。私有`before_promote`回调仅供daily检查输入文件身份，默认None，公共writer和repair/history不传入 |
| 日更资产wrapper原来调用公共历史writer | 新增`_prepare_daily_macd_kdj_replacement_tables(...)`并明确调用上述共用发布函数 | 在wrapper中用原family/root/freq/dates打开publication和原配置连接，先准备完整日更结果再发布 |
| 原`write_gold_stk_mins_qfq_macd_kdj_rows` | 签名、默认值和返回不变 | 仍打开同一publication/connection → 原历史prepare → 共用发布函数；repair/history/direct tests仍走此链 |

不能通过“目标日期只有一个”猜测daily模式：历史/repair也可能只有一天。新日更准备只由日更资产wrapper明确选择，原公共prepare及writer不能自动改道；不加运营mode或新公共参数。daily与history只分开**输入准备**，公式与发布仍共用，不能复制一套candidate、锁或状态机。

调用关系应是：

```text
日更原asset wrapper
  原门禁、discover、exact previous state
  原publication锁 + 原DuckDB连接
    新日更prepare：有限输入 → 原segment公式 → 当日完整replacement
    共用publish：一次bind → 原候选/校验/逐文件提升

repair/history原调用方
  原公共writer（签名和默认值不变）
    原publication锁 + 原DuckDB连接
      原history prepare → 原segment公式 → 原范围replacement
      同一个共用publish
```

### 19.4 日更准备算法及SQL边界

**A. 完整前日state及批次规划**

1. 完整前日state只读一次，继续使用原投影、频率过滤和每股最新行选择SQL，保留全部股票。整体`initialized_without_previous_state`仍为这张表是否为空；不在新股分支重新赋值。
2. 路径按原stock/year布局分组，只保存`code → Y/Y-1路径`和稳定代码序列，按64只切成互不重叠的批次；不修改discover实现及其repair消费者。路径分组建立在现行QFQ文件/分区合同上，原上游checks和日期/字段合同不取消。
3. 创建一次原work表。每批覆盖临时`macd_kdj_calculation_rows`及少量选择表，原work表只追加目标日结果；不能在下一批开始清空已完成股票结果。Python不接收价格明细，只接收最多64个代码和小型分组计数。
4. 来源一致性继续依赖`GOLD_STK_MINS_QFQ_WRITER_POOL`的真实串行设置；QFQ日更、因子repair和MACD原资产已共用该pool。MACD publication锁按family隔离，不阻止QFQ写入，不能把它当跨来源锁。未来正式执行前只读核对pool实际并发为1及无不受该pool控制的来源writer；本轮不查运行态、不改pool配置。
5. 新日更私有`_assert_daily_macd_kdj_source_files_unchanged`只比较实际读取文件的`(st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns)`：前日state读前/读后各一次；本批来源首次读前/该批全部SQL读完各一次；全频结果完成bind前及所有候选生成后promote前，再统一核对已记录的实际输入。这使每个实际文件最多四次stat，不在每个股票批次重复核对整张前日state或此前所有路径。后读到的上一年文件加入同一映射；从未读取的上一年文件不为本检查做stat。首次缺文件沿用原来源读取失败，不进行重试；身份变化则抛错并按19.6停在下一次bind/提升之前。mtime以ns比较，不使用atime；正常只读及其他无关文件变化不能误拦。该检查不新增行情读取、SHA、来源副本或全局目录扫描，其元数据成本计Fr。它只验证可观察到的文件变化，不能替代共享pool及“无脱管writer”的执行前提。

**B. 当日行与前序至多8根**

1. 对批内当前年现存路径先执行`trade_date = DATE D AND freq = f`并投影七列，得到当日表；保留原行，不DISTINCT、不填值，不把错误输入清洗成通过。没有当日行的代码不参与历史尾部读取，完整前日state仍保留它们。
2. 对有当日行的代码，在**当年**文件上直接执行`trade_date < DATE D`，按股聚合最近至多8根。采用下面的有界聚合形态，不能先创建全部历史临时表或完整窗口排名：

```sql
SELECT ts_code, freq,
       arg_max(
         struct_pack(trade_date := trade_date, trade_time := trade_time,
                     high := high, low := low, close := close),
         trade_time, 8
       ) AS prior_bars
FROM read_parquet(<本批有当日行情代码的当年现存文件>,
                  hive_partitioning=false, union_by_name=true)
WHERE freq = <原频率> AND trade_date < DATE <目标日>
GROUP BY ts_code, freq;
```

上式是待编码SQL形态，参数与路径沿现有安全builder生成，不把占位符原样执行。临时STRUCT保留完整一根K线，不能用若干彼此独立的`max(high)/last(low)`拼成不存在的K线。`arg_max`在val为NULL时会忽略该行，因此其使用前提是QFQ生产者的有效非空时间/唯一键：`stk_mins_qfq.py::_validate_replacement_rows`拒绝NULL业务键`ts_code/trade_date/trade_time`及重复`ts_code+trade_time`。该生产者拒绝边界不等于MACD prepare全面校验所有NULL/缺列，不能为满足笼统测试而新增daily业务guard。开发时按19.8分别验收生产者合同和有效来源的日更选择，不安装或升级版本。

3. 当年最近条数不足8的代码，包括当年此前0行的代码，才查它们**原集合内**上一年现存文件；仍按每股取最近至多8根。无上一年路径时按空集合处理，不能由DuckDB读取空路径列表引发新错误。
4. 每股两路至多16根，合并后再按时间保留最近8根，展开并升序排列。上一年充足且当年已有数根时必须合并后取8，不能取每年8根合计16根直接计算。目标日未来行一律不进入prefix或递推。
5. 当年已有8根时不读取该股上一年文件；完全无当日行情的批次不发历史SQL。当前年与上一年的读取次数分别记录，不能把“查询只返回8根”写成“硬盘只读取8行”。

**C. 原业务检查与递推**

1. 原候选集合中有目标日前行情的代码，必在prefix中至少有1根；使用这份存在性证据与完整前日state检查原缺state老股票错误。不得裁剪历史后只检查当日表而绕过原错误，也不追加更早年份的存在性扫描。
2. prefix与当日表合并后按`ts_code/freq/trade_time`计算原9根HHV/LLV和RSV，再筛仅当日行，生成原`calculation_row_number/segment_index/segment_row_number`。
3. 调用原`_populate_macd_kdj_indicator_work_rows`及`_insert_macd_kdj_segment_rows`。prefix只影响RSV；不能给prefix生成indicator、推进state，或把它的close作为新的递推起点覆盖前日seed。
4. 原work表可以保留前面批次的**当日**结果；每批代码不重叠，segment的previous_work联接必须仍按`ts_code/freq`，不能把另一股/另一批结果当seed。分段长度仍为1024，不因64股票批次改成64根K线。
5. 每批结束记录实际完成股票数、当日行数、prefix行数、已用当年/上一年路径数和耗时，再释放批内选择/计算表。记录实际进度，不新增心跳或伪造ETA；保留原`source_file_count`字段的原discover候选数量含义，实际读过的路径数量用另名日志字段，不改返回合同。

**D. 完整结果与state**

全部批次完成后，从累计当日work调用共用replacement builder，使用原SQL统一生成当日indicator和完整state。无当日行情的旧股票仍保留，`last_trade_time`不改成今日；新股加入state；当日全空仍触发原空结果错误。一个频率只保留当日work/indicator/state、完整前日state及当前小批输入，不保留前面批次的历史输入。

### 19.5 内部批量和现有配置审计

| 项 | 值、来源与持久化 | 消费者、作用与生效 | 验收 |
| --- | --- | --- | --- |
| `MACD_KDJ_DAILY_STOCK_BATCH_SIZE`（本轮实现的内部算法常量） | 64，定义在原MACD模块；不来自env/Settings/DB/run config，不持久化、不暴露运营输入 | 仅新日更批次规划及其测试读取该定义；随代码部署生效，无其他消费者。每批最多64股，不限制总股数 | 65股跨批次正例；1/64/65股完整覆盖，无截断；history/repair不读取此常量 |
| 公式、KDJ历史条数及分段 | 原12/26/9、9/3/3、8根前序和1024分段 | 原公式函数；不得将股票批量当K线分段 | 独立字面金样本、跨批次seed、前序第9根极值反例 |
| DuckDB设置 | 原`DEFAULT_DUCKDB_CONNECTION_SETTINGS`，16GB/4线程、managed及既有512GB临时容量 | 新日更复用原默认；history自有设置及其他消费者不改 | 不新增timeout、内存/临时容量限制，不套用QFQ的no-spill策略 |
| 目录与并发 | 原formal/staging根、writer pool、publication同family/freq文件锁 | 从准备输入到统一提升覆盖整个频率；不按64股释放重拿 | 并发拒绝、全部候选准备后提升、锁随进程退出释放 |
| 实际输入文件身份（非配置） | 日更内存映射，仅stat五项身份；不持久化源行情，不新增参数或跨工程能力 | 仅新日更准备及私有发布前回调消费，repair/history不增加新检查；最多每个实际来源及前日state四次stat | 原pool串行、正常读取不误拦；批内/候选生成期间来源替换均在正式提升前停止 |

64用于使每批当日与prefix输入有界：以合同内1m每股最多241根、64股计，窗口输入至多`64×(241+8)=15,936`根；不是实测最优批量，也不是新运行拒绝阈值。全频当日结果仍需累计，规模为当日行数，不能声称整个进程内存只等于15,936行。若以后改批量、设置来源或公开输入，应重新审计本表全部消费者，不散落另一组默认值。

### 19.6 完整绑定、失败、中断与续跑

1. 与原writer一致，在计算前获得publication锁并打开原连接；计算失败退出并保留其已有staging目录。计算尚未完成时不得调用bind、创建年度候选或替换正式目标。原pool的串行状态和无脱管来源writer是正式执行前提，不能靠MACD文件锁或冻结结果替代。
2. 指标及state全部准备完成，按原顺序生成完整目标集合和稳定排序的两份冻结输入，再调用一次原`publication.bind`。common publish内的空结果、`allow_empty_replacement`、`fail_if_target_exists`及scoped state分支原样保留；daily不引入这些参数的新外部入口。
3. 年度文件按原SQL保留非目标日，今日共享state由完整替换表写出。全部候选经现行校验、一次完整摘要及原预检后才开始逐文件提升；不重新引入每文件三遍SHA、不新增公式审计或全局比对。
4. 发布前失败不改正式目标；提升过程中失败保留已替换文件，不回滚，不删除异常现场。只有原`validated/promoting/promoted`记录、真实文件身份及输入摘要满足原规则才可续跑；冲突继续拒绝。
5. 本轮不增加批次checkpoint。计算中断需要重建当日替换输入，开销单列；已完成候选/正式目标仍由原receipt判断，不能因为计算批次完成就宣称年度文件已提交。
6. 新旧prepare虽应产生语义等价结果，浮点尾数、行组或Parquet编码可能导致冻结SHA不一致。不能承诺新代码自动接管旧root operation；禁止修改摘要算法、放宽比较、删除operation/receipt或换root掩盖部分正式结果。新实现自身同输入重放也必须验证稳定冻结和幂等。
7. 29日1m历史日志显示失败在prepare，仅在正式恢复前有界确认该频率确实未bind、无旧候选/receipt且来源仍匹配时，才可另列原生恢复办法；不能仅凭run失败推定。六频成功结果不因本轮文档或未来开发被重跑，repair之后仍按原job产物和原顺序推进。
8. 日更来源/前日state身份变化：bind前发现则不产生年度候选；候选生成期间变化由私有`before_promote`再次核对，失败保留完整候选但不调用promote、不写正式目标。发布后已替换部分的恢复仍按原receipt，不增加自动回滚。冻结输入只是replacement/state输出，不能声明源行情已做快照；即使更改后价格相同或文件大小相同，inode/mtime/ctime变化也不能静默忽略。
9. 旧候选冻结摘要冲突只属于该次未完成发布的恢复问题，不构成历史业务数据失效证据。先保留既有正式结果和原记录，仅在核定的未完成日期/频率内另列恢复办法；不能重刷历史、删原记录或重跑全job绕过。原年度合并仍只替换目标日，非目标日记录原样保留；API reader不消费publication冻结SHA，不能把文件摘要差异推断成下游必须迁移或重建。

### 19.7 正常、续跑与收尾的读写预算

**开发前文档阶段**：当时正式Parquet内容读取、价格计算、网络源请求、数据库及Lake写入均为0，只读源码、测试、原文档和已有metadata报告。随后开发使用人工临时文件，未重做正式年度stat、计数审计、性能样本或正式运行。下列仍是未来正式执行的成本模型，不是读取批准或实际设备I/O；本轮隔离成本另见19.12。

按每个独立文件步骤最多计一次完整文件大小，不按列比例、缓存或row group裁剪打折：

- `Qy`：当前年候选QFQ总大小；`Qp`：上一年原候选总大小；`L≤Qp`：当年不足8根而确需读取的上一年子集。没有当日行情的股票不计入L。
- `I`：实际受影响旧指标年度文件总大小；`C`：新指标年度候选和当日state合计；`V`：完整前日state。
- `P`：两份冻结输入文件大小；`Fr/Fw`：footer/schema/记录/日志等读写留量；`Tr/Tw`：现有managed连接的引擎临时读写，不能默认为0。

| 步骤 | 保守文件读取/写入 | 保留理由 |
| --- | --- | --- |
| 日更输入选择 | 读`2Qy+L+V` | 当日行和当年历史各一个查询；上一年按需一次；前日state一次。没有全历史临时表，不等于只扫描一次文件 |
| 当日窗口与递推 | DuckDB当日/小批工作表；spill计Tr/Tw | 不另读正式QFQ；Python不承载明细；存在中间表实现差异应记录，不能用函数名代替预算 |
| 冻结输入 | 写P，读P一次SHA | 原完整bind；不冻结前序历史 |
| 年度候选 | 读`2I+2C`，写C | 原旧年度分区校验及合并各一次；候选投影校验一次及原一次SHA；count/footer计Fr，不额外加一次SHA |
| 原四项checks/每频 | 读上界`4(Qy+Qp)+2C`，另计Fr | 三处`_indicator_expected_paths`来源发现查询，加source coverage一次来源查询；指标行数及state覆盖各一次目标读取。schema/footer不当成零成本，也不因此改checks |
| 来源稳定性及最后收尾 | 仅实际来源/前日state最多四次stat计Fr；复用原物化/28checks、receipt及必要stat小汇总 | 不追加一次来源SHA、全量公式或年度内容审计；不触碰未使用年份 |

合计：

```text
正常R = 6Qy + 4Qp + L + 2I + 4C + P + V + Fr + Tr
正常W = C + P + Fw + Tw
正常新增空间按候选/冻结/记录/峰值引擎临时文件另留20%余量
```

同一频率的source和目标查询可能因过滤/缓存实际少读，本模型仍按独立查询完整文件大小保守计费。旧年度2I及原checks的重复发现本轮没有优化；不得沿用QFQ第9节的`I+3C`口径冒充MACD已实现相同优化。

基于19.1历史metadata，给出供未来执行前核定的七频条件：`Qy≤8.5GiB、Qp≤9GiB、L≤Qp、I≤20GiB、C≤22GiB、P≤128MiB、V≤2MiB、Fr/Fw各≤1GiB、Tr/Tw各暂留8GiB`。代入正常读取约233.13GiB，向上预留**240GiB读、32GiB写、40GiB新增空间**。这些是估算条件，C/P/临时读写未实测；8GiB是预算留量，不写成DuckDB配额、限制或额外批准。不能把此数当实际耗时、实际硬盘I/O或“优化一定节省到该值”的结论。若目标只剩1m，必须按该频变量重新核定，不能照七频全跑；若旧stats或条件不适用，先修预算及执行卡，不以运行限流/超时截断任务。

一次必要续跑必须重新准备当日输入及冻结P，不能假定只从第65只股票继续。按真实记录分别计：未生成目标的旧文件校验/合并、重建候选校验与一次摘要；已validated/promoted文件只做原恢复核验，不重写。全部未完成时，正常一次加一次最坏重建参考上界为**480GiB读、64GiB写**；失败现场与新候选并存时，按`(2C+2P+2Fw+两次峰值临时占用)×1.2`保守预留至**80GiB新增空间**。这是恢复前核定的成本，不授权第二遍全范围执行或自动重试；实际应扣除已经完成且可复用部分，其他run遗留文件另计。

原28checks已经包含在正常R，正常结束不再加一轮。若只重跑checks，其读上界为`4(Qy+Qp)+2C+Fr`，无年度COPY；条件示例约115GiB，非正常必做。最后汇报只汇总原结果、receipt与必要stat；只有确有缺失证据且另列增量成本时才追加明细查询。

耗时边界：未来上述隔离夹具预计数分钟完成，不设置新的正式job超时或内存/临时容量限制。当前没有新算法的真实耗时和spill测量，不能凭旧152秒benchmark承诺29/30日全市场时长；这不阻止先开发和隔离验证，但正式执行卡必须使用当时未完成频率及已有运行日志补齐预估，不能将本节条件预算直接当作可执行批准，也不为填时长数字另跑全市场性能测试。

### 19.8 测试、独立依据及验收条件

本节是编码前确认的验收清单，实际执行结果见19.12。开发使用orchestrator现有`.venv`、隔离临时Lake/staging/temp，不初始化正式instance、不访问正式凭据或安装依赖。普通夹具不超过2股、2年和少量K线；批次边界用65股各少量行，临时文件目标预算64MiB。64股阈值是批量边界，不能改成测试过滤掉超出股票。

| 要求 | 代码点 | 正例与反例/独立expected |
| --- | --- | --- |
| 七频数值与前日seed | 新daily prepare → 原segment | 原字面金样本六指标及EMA/K/D；MACD柱倍数、平价HHV=LLV、J超界；prefix只影响RSV，不能重复推进state |
| 真正最近至多8根 | 当年Top8＋上一年补足 | 当年≥8不打开上一年；当年0/3根与上一年8根正确拼接；第9根极值不影响；跨多日停牌不按自然日截断 |
| 保持原来源和部分窗口 | 路径分组及prefix | 仅1—7根不新增失败；Y-2极值文件设置禁止读取，结果不受影响；无上一年路径不执行空read_parquet |
| 不把旧股当新股 | prefix存在性与完整state | 其他股有state、本股新股无prefix可原seed；本股有prefix却无state必须原错误；整体初始化标记不能被单股分支改写 |
| 连续性与停牌state | wrapper guard＋共用state SQL | exact前日文件正常；缺前日不得更早回退；无当日行情代码保留旧state/last_trade_time；全频当日空结果仍失败 |
| 64股批次无丢失/串值 | 新日更planner/全日work | 1、64、65股计数及集合完整；新批不清前批结果，不把前批另一股当seed；批次顺序固定，分段仍1024 |
| 不再全市场历史排名 | 输入SQL/隔离查询观察 | SQLspy＋隔离小型EXPLAIN/行数证明只对有限输入做窗口，不创建`macd_kdj_source_all_rows`；不能用仅有函数调用次数或新函数自制expected证明 |
| 输入合同真实性 | 原QFQ schema/producer、新日更输入投影 | 夹具注明源合同；隔离调用原`_validate_replacement_rows`证明NULL业务键及重复键拒绝；新daily在有效来源上保持七列投影/类型，不用其自身生成expected。不得笼统断言MACD会拒绝所有NULL/缺列；多文件`union_by_name=true`缺列可能补NULL的原行为不在本轮新增guard或变更 |
| 年度与共享state保持 | 共用publish/两类writer | 原真实隔离writer链证明其他日期、无行情股state和返回合同不变；不能mock掉待验收的候选/合并边界 |
| 一次完整publication | bind、candidate、promote | 65股也只bind完整inputs一次；第2候选失败不提升第1；完成1文件/replace后receipt前故障，原恢复仍核验、已完成文件不重写 |
| 同输入稳定及旧输入冲突 | 冻结和输入SHA | 新路径同输入重复运行稳定且幂等；旧operation冻结不同必须拒绝，不能用浮点容差放宽文件SHA |
| 来源分批读取一致 | 日更五项文件身份＋原pool依赖 | 批内源被替换、候选生成时源/前日state被替换，均在相应bind/提升前拒绝；相同大小不同inode也拒绝；正常只读/atime变化、未使用年份及无关文件变化不误拦；原pool元数据及装饰器仍保留，共用发布默认回调为None不改变repair/history |
| repair/history不改道 | 原公共writer与调用方 | 单日期repair仍走原prepare；多日期history仍完整递推；old flags、scope、完整state预检及14 completion门禁不变 |
| 原数据及真实下游兼容 | 原年度合并、完整state、`StockMinsLakeReader`与股票详情指标API | 隔离小文件证明非目标日期/股票业务值不变、前日state不重写；新目标结果可由原reader按原列/类型/键读回并按日期时间与行情对应，版本/参数/分页不改；既有已完成repair不重复触发。测试经临时文件交接并各用本工程现有环境，不在DG运行时import `src.foundation`或主工程API |

复用测试为：`test_stk_mins_qfq_macd_kdj_formula_golden_contracts.py`、`test_stk_mins_qfq_m12_macd_kdj.py`、`test_stk_mins_qfq_macd_kdj_repair_op_contracts.py`、`test_stk_mins_qfq_macd_kdj_repair_gate.py`、`test_stk_mins_qfq_staging_publication.py`、`test_stk_mins_qfq_publication_single_digest.py`和原运行契约静态门禁。新增日更测试已放入`tests/test_stk_mins_qfq_macd_kdj_daily_read.py`；原staging测试新增日更发布回归，未删减既有用例。

expected以原已核实公式和独立字面小样本为准，不能调用新daily或同一选择helper生成。与旧prepare做有界结果对账仅作补充。保留原浮点容差（绝对1e-10、相对1e-12）、类型、行数、代码/日期集合及其他日期不变断言；不能只靠放宽容差通过。受保护套件走原测试启动器，单元、隔离集成、既有真实合同证据和未来正式执行分别报告。现有§6.1真实小样本/当前producer合同可作接入依据；缺证据时只补有界字段样本并单独说明，不能顺便重跑全市场或性能测试。

真实消费者的已有隔离测试包括仓库根`tests/test_stock_mins_reader.py`和`tests/web/test_stock_detail_minutes_api.py`；本轮已在其现有环境运行15项，并补新daily临时文件到原reader/API的实际交接，详见19.12。未访问正式Lake；API认证/数据库依赖在测试中隔离，不宣称验收真实认证或数据库。

开发完成验收应逐条对账：业务方案17.2的9条要求 → 上表代码点 → 正/反测试 → 实际证据。源码正确性通过不等于4GB错误已被实际复现并消除；正式run是否成功只能由其真实结果证明。

### 19.9 下一步及正式执行边界

1. 已完成原设计、代码及消费者审计和方案/LLD独立复核，文档以`4a4a689e`提交；旧sensor收尾改动没有混入该提交。
2. 已获准并完成私有等价提取及明确daily有限输入，原repair/history不改道，不扩展配置或源年份；实现遵守方案17.9及19.11。
3. 已完成19.8隔离验证和19.11逐项交付对账，证据见19.12；正式恢复仍需下一项单独核定。测试没有使用正式行情，没有安排全市场性能测试，不能将隔离结论扩大为正式4GB场景已验收。
4. 本轮停在此处：未来正式恢复前只读核实当时缺口、来源/前日state、root operation、receipt和活动writer，按实际未完成频率列原生job恢复入口、具体读写预算、失败及收尾安排；另按根规则取得必要执行/年度读取批准。已有29日六频成功记录不要求重跑。
5. 日更恢复后，历史repair仍按原上游产物及daily→repair顺序推进；若其规模或运行事实暴露新问题，停止并另行完善repair方案。不得用本轮日更测试替代repair性能验收或擅自重跑已经完成的历史。

### 19.10 本轮文档审计及未完成项

本节以下内容为开发前文档阶段的记录，其中“未开发/未测试”只描述当时状态。后续已获准实施的最新结果统一见19.12；本轮始终未正式补数。

已核清业务方案原第1/6.2/12节的读取意图与代码差异，修正“上一交易日之前”的歧义；旧benchmark仍保留为历史证据。R5为repair范围硬化和7月恢复依据，不作为本轮日更LLD；其中旧备份/quarantine操作不执行，现行写入只使用本文件和当前publication。

本轮写入范围仅两份原文档；本文件第13.2节已有sensor收尾改动保持，不纳入本次设计改写。实现、业务测试、正式29/30日状态修复、补数、sensor变更及repair优化均未执行。文档检查、独立复核及其发现的修改在本节末记录，不能预填开发或正式验收通过。

本节SQL与读取能力另参考DuckDB官方[每组最近N条聚合](https://duckdb.org/docs/current/sql/functions/aggregates.html#arg_maxarg-val-n)和[Parquet部分读取](https://duckdb.org/docs/current/data/parquet/overview.html#partial-reading)。前者支持有限候选聚合，后者说明列裁剪、过滤下推及统计条件下的row group跳过；二者均不证明本轮真实设备读取量或4GB异常的具体内部原因。

2026-10-30独立审文结果：

| 初审发现 | 已落修正 | 复审结论 |
| --- | --- | --- |
| NULL/缺列测试笼统要求MACD全面拒绝，超出现有拒绝边界 | 19.4B/19.8明确原QFQ生产者的NULL业务键/重复键验证及各层证据，不增加daily业务guard | 未发现原拒绝口径被扩大或由mock绕过 |
| 原方案`last_trade_time`描述与停牌状态承接矛盾 | 方案6.2按“截至state日期”解释，17.2/19.4D保留旧时间 | 方案/LLD及现代码一致 |
| 分批多次读取未说清来源稳定性 | 方案17.2/17.3/17.7与19.3—19.8明确原pool、实际文件五项身份、四次stat及bind/提升前停止 | 私有回调默认None，不改变repair/history；不把结果冻结当源快照 |

两位独立审查者在上述修正后复核，均未发现本轮方案/LLD仍有必须先修的阻断矛盾。根代理另核了Top8与两年来源、64股边界、仅目标日递推、全state、共用发布、正常/一次续跑/原检查预算及文档状态。只审代码和已有证据，没有正式行情重读或业务测试。

文档验证：`python3 scripts/check_docs_integrity.py`三组检查通过；两份文件`git diff --check`通过；另单独核对新增段落和文首跨文档相对链接及锚点（统一脚本不覆盖本目录全部相对链接）。这些只证明文档结构/链接，不证明未来代码数值、性能或正式数据完整性。当前剩余工作是19.9的获准开发、隔离验证及实现对账，正式恢复另列执行卡；没有以未测事项冒充通过，也没有留下待决定的新数据口径或公开配置。

2026-10-30按管理员“不接受由本次优化导致历史重刷”的补充要求，再核实际消费者：分钟指标年度文件→`StockMinsLakeReader`→`StockMinuteQueryService`→股票详情API/页面；九转实际读取QFQ而不是MACD/KDJ。该次补查修正了原影响面表未逐一列出API/前端消费者的问题，并在方案17.2第9项及本节加入不重刷已完成历史、原reader兼容及既有repair去重验收。本轮仍未改业务代码、运行测试或核正式运行态。

### 19.11 开发必须提交的等价与不重刷历史验收

对应[业务方案17.9](dagster-stk-mins-qfq-macd-kdj-indicators-plan.md#179-讨论收口计算等价与不重刷历史是交付条件)。以下为编码前确定的交付标准，实际逐项证据见19.12；不改变19.8的独立expected、隔离资源和必要读取边界，不能仅凭条目存在就认定通过。

| 讨论要求 | 必须落到的实现约束 | 必须提交的隔离证据 |
| --- | --- | --- |
| 改取数，不改算法或结果 | 新daily只准备有限输入；原`_insert_macd_kdj_segment_rows`公式/seed/1024分段及参数版本原样复用；原公共prepare不改道 | 七频独立金样本＋原prepare有界补充对账。键/类型/行数/参数/版本精确一致，六项指标及EMA/DEA/K/D按原容差一致；不得修改expected或提高容差迎合新实现 |
| KDJ仍需要历史迭代 | prefix只供9根HHV/LLV计算RSV，K/D从正确前日state逐根递推，MACD从原EMA/DEA递推 | 使用非初始50的字面K/D及非首价EMA/DEA作为前日state；独立核算目标日前几根，证明没有重新初始化或将prefix重复递推。第9根更早极值不影响目标窗口 |
| 原state可直接承接，无需历史初始化 | 保持旧state的schema、params/version、所有递推值与`last_trade_time`语义 | 在临时目录放置原合同的前日state直接计算D，再把新D state用于D+1；与独立连续样本及原算法结果对账。D以前state文件内容和文件身份不变，不先重建它们 |
| 年度写出不等于重算旧记录 | 年度merge仅替换D，其余日期从原表直接保留；不写D之外state或更早指标年份 | 隔离年度文件同时包含D之前、D及D之后的字面记录，验证仅D替换、其他记录字段/键/类型/数量不变。捕获实际写入目标集合，禁止出现未授权日期state和更早年份 |
| 旧候选冲突不扩成历史修复 | 原publication的输入SHA/targets比较不放宽；旧正式数据保持可读；未完成范围另列恢复卡 | 构造旧operation冻结摘要冲突，仍应拒绝且不写正式目标、不删记录；原正式历史及前日state仍能由原reader/新daily使用。不能因冲突自动重刷历史或换root掩盖已提交结果 |
| DG及真实消费者保持兼容 | asset/分区/check/schema/path/版本/run key不改；API/前端不迁移；九转仍读QFQ | 保留原定义/契约静态门禁。用临时结果交接给原reader验证字段、日期时间关联和历史查询；复用原API隔离测试。无正式event补录/历史分区重登记，无DG运行时代码跨工程import |
| 原repair仍按原上游范围及完成去重 | 不新增优化专用repair，不把文件编码/SHA变化作为factor repair理由 | 原因子repair无历史变化则不提交MACD repair；确需repair时日期/名单/hash/upstream身份不变，已完成批次仍跳过；单日期repair也不进入新daily准备 |
| 64股仅是组织方式，不是数据截断 | 每股只属于一批；保留所有批次结果及完整停牌state，不改源年份/不足8根行为 | 1/64/65股集合与计数全覆盖；跨年、停牌、原集合不足8根、无当日行情和无上一年路径均按19.8通过；实际来源选择和SQL证明没有全市场历史排名 |
| 小结果不冒充小物理读取 | 当年两次选择、上一年按需、年度合并/原checks及来源stat均计预算 | 隔离记录查询及文件集合、输入/中间表行数和COPY/摘要次数；不凭返回8行声称只读8行，不加一次全量审计、重复SHA或正式性能样本 |

验收结论必须把“方案已审计”“实现已通过隔离验证”“正式job已成功”分开。**不重刷已完成历史数据是本轮修改的交付硬条件，不是以后再争取的优化目标。** 任何必须重算历史、清空state、改下游或补历史事件才能继续的实现均不合格，应停在正式数据写入之前修正代码；不能将历史重刷改名为初始化、迁移、校准或恢复来绕过。若正式执行已按原原子提升提交了部分目标，仍按原记录保护已提交结果，不回滚或扩大范围。

开发完成报告须列出上表每项对应的代码位置、测试名、预期依据、实际结果及未覆盖边界；存在未通过项时不申请部署/补数，不把其他测试数量或文档检查通过当作替代。正常因子变化原先就要求的repair仍保留，这与本次优化不得新增历史重刷的约束分别对账。

本节最初作为文档增补完成两位独立审查，并随设计提交`4a4a689e`。之后管理员另行批准开发与隔离验收，实际证据见19.12。第19.7节正式预算和第19.9节阶段授权边界不变，不能因测试已完成自动进入正式恢复。

### 19.12 开发、隔离测试与实现对账（2026-10-30）

**状态与范围。** 先按要求提交设计文档`4a4a689e`，仅两份本轮文档；第13.2节原sensor收尾改动未混入提交。随后按本节LLD完成开发、隔离测试和独立实现审计，**代码、测试及本次验收记录随本次实现提交归档，正式补数未执行**。没有触发或重载正式job，没有改sensor/pool/run key/动态分区，也没有读取正式Lake、instance或Prod数据。本轮未安装或升级依赖。

证据统一归档至[开发验收报告](../../reports/macd_kdj_daily_read_20261030/README.md)；[总汇总](../../reports/macd_kdj_daily_read_20261030/validation-summary.json)记录生产文件SHA、设计提交、测试计数与未覆盖范围。正式路径只作为代码合同读取，没有拿正式数据做夹具。

**实际文件。**

| 文件 | 已完成内容 |
| --- | --- |
| `defs/stk_mins_qfq_macd_kdj.py` | 按19.3提取work/replacement/publish私有职责；daily明确走64股有限准备、当年Top8/上一年按需补足、实际输入身份核对；原公共writer继续history/repair原prepare |
| `tests/test_stk_mins_qfq_macd_kdj_daily_read.py` | 新增35项：七频独立字面值、两年及0—8根窗口、原state连续D→D+1、65股批次、原异常、输入SQL/EXPLAIN及原QFQ producer负例 |
| `tests/test_stk_mins_qfq_staging_publication.py` | 原20项保留，新增11项daily发布/恢复/来源变化测试；autouse fixture只将两个真实连接入口的设置改到临时目录，不替换计算、校验或文件发布逻辑 |
| 两份原方案/LLD | 同步本轮状态、逐条实现/测试对账、未验收边界；无其他产品或数据合同变更 |

CodeGraph `explore/impact`已覆盖主writer与wrapper，并按源码补查其索引未完整识别的repair/history及真实reader/API/前端消费者；代码完成后执行`codegraph sync`及`status`，索引正常、无待同步提示。原八项来源发现、公式及年度/state writer的AST与设计提交完全一致，三个公开函数的参数/默认值/返回注解保持，见[AST对账](../../reports/macd_kdj_daily_read_20261030/ast-compatibility.json)。原work DDL和replacement/state SQL为等价提取；公共发布除增加默认None的私有提升前回调外，仅SQL缩进变化，已由独立审查逐句核对。

**19.11逐项对账。**

| 硬要求 | 实现位置 | 实际证据与结论 |
| --- | --- | --- |
| 取数变化、公式/结果等价 | `_prepare_daily_macd_kdj_replacement_tables`复用原`_insert_macd_kdj_segment_rows`与`_populate_macd_kdj_indicator_work_rows` | 七频非初始seed的字面有理数预期及旧prepare补充对账通过；原公式AST相同、原容差未提高 |
| 前8根只供RSV，state直接承接 | `_create_daily_macd_kdj_calculation_rows`、原segment/state生成SQL | `test_daily_keeps_literal_noninitial_state_and_original_formula`、`test_new_state_continues_next_day_without_rebuilding_old_state`及实际跨环境D→D+1文件交接通过，没有重建前日state |
| 不重刷历史与年度保留 | 原`_write_indicator_group_to_year_file`、`_write_state_partition_file`原样复用 | 发布测试和handoff验证非D前后记录原值保留，旧state文件SHA/身份不变，无关股票和停牌state保留；测试写入均为临时文件 |
| 旧候选冲突不扩大恢复 | `_publish_macd_kdj_replacement_tables`调用原publication | `test_daily_old_frozen_input_conflict_does_not_invalidate_formal_history`及replace前后中断续跑通过；已完成文件不重写，冲突不删记录/不重刷历史 |
| DG及真实下游兼容 | 原定义/paths/schema不变；新输出仍为原12列指标和原state | 原受保护113项门禁、原reader/API15项、DG DuckDB1.5.2→原reader/API DuckDB1.5.5真实临时文件交接通过；字段、时间键、分页、params/version兼容 |
| 不影响repair/history及原去重 | 原公共writer继续原prepare，私有回调默认None；原repair/sensor文件未改 | 原MACD/history/golden/repair op/gate/sensor/single-digest相关6套完整回归121项及18子测试通过；单日期repair不误入daily、原已完成batch仍跳过 |
| 两年Top8与全部股票分批 | `_daily_macd_kdj_prior_bars_sql`、daily prepare | 当年足8不读上一年、跨年/长停牌/原集合0—7根、Y-2不读、1/64/65股完整集合和不串seed通过；SQL及EXPLAIN证明原始历史使用Top8聚合而非全市场历史排名 |
| 整频一次发布与来源一致性 | 原锁覆盖prepare→publish；五项身份读前后/bind前/promote前检查 | 65股仍只bind一套完整目标；第2候选失败不提升第1、同大小不同inode、候选期源/前state变动均拒绝；正常读取、atime及未用年份变化不误拦 |
| 读取成本如实记录、无额外全局审计 | 输入选择及原checks/年度发布保留，源身份只stat | 无来源SHA、额外公式审计或性能试跑；19.7正式预算未当作已实测/授权。本轮只对少量人工数据执行SQL |

**验证数量和边界。**

| 验证 | 结果 | 资源隔离与说明 |
| --- | --- | --- |
| 新日更＋原staging发布完整两文件 | **66 passed**（35＋31），10.07秒 | 同一次最终运行；真实DuckDB/SQL/publication，连接仅绑定临时资源；临时1,352文件、10,133,658B，退出已清理 |
| 原6套MACD/history/repair相关回归 | **121 passed，18 subtests passed**，6.38秒 | 原测试不筛选、不改expected；59次统一连接仅重定向temp，OS策略拒绝正式Lake/instance/凭据/网络，原子进程同受保护 |
| 原`test_run_contract_static_gates.py` | **113 passed，5 subtests passed** | 原受保护启动器15批完整执行；不以普通pytest绕开其资源保护 |
| 原reader/API两文件 | **15 passed**，0.93秒 | 主工程现有环境、独立FastAPI/TestClient和临时配置；不是正式HTTP/认证/数据库验收 |
| 新daily→原reader/API真实文件交接 | **通过**，不另计pytest数量 | 1股非初始state、D两行与D+1一行，独立有理数预期；原reader读5条历史及分页，原API两日200/READY，字段与K线键对应；停牌股state也保留 |
| 静态检查 | **通过** | 项目src/tests致命Ruff基线、本次三个Python文件默认Ruff、源码/新测试格式、`git diff --check`；文档检查与新增相对链接单列复核 |

合计**315项测试、23项子测试通过**；不重复累计前面单跑或失败重试。新daily第一次有一例测试把原前日缺state的`dg.Failure`误写为普通异常，按现行guard精确校正；新增发布测试曾把fixture producer的operation误当MACD operation，按真实family边界修正断言。两项均未改生产逻辑、放宽数值或取消拒绝。原6套隔离runner启动时的OS/收集参数错误均在进入业务测试前失败，随后复用原保护方式及完整收集参数通过，见清理记录；没有改原测试来消除失败。

最终66项的资源保护记录了一次本地`socket.bind`拒绝，未记录`socket.connect`或正式文件请求，保护未解除；不能把它写成“没有任何尝试”。原consumer和实际handoff未有拒绝请求。所有正式数据源/DB/instance调用均未进入；API认证/数据库依赖在该测试中隔离为None，不扩张验收结论。

**独立审计、清理及停点。** 独立审查者按已提交方案/LLD检查实际代码和两份测试，确认公式、旧prepare、共享state、公开合同、完整publication及原repair路径保持，未发现阻断，见[独立报告](../../reports/macd_kdj_daily_read_20261030/independent-review.md)。原guard、candidate校验、正式checks均未削弱；不重刷历史的硬条件在本轮隔离范围内满足。

证据归档后，只清理本任务确认的临时根、夹具、staging和runner，未删除正式Lake/staging或其他任务pytest目录。最终66项、旧回归和consumer夹具均已清理；另移除957个本轮暂存证据/脚本及早期夹具文件、1,925,218B，保留本报告必要证据，详见[清理账](../../reports/macd_kdj_daily_read_20261030/cleanup.json)。没有清理共享依赖或环境。

本轮**没有正式补数、没有部署/重载、没有全市场性能测试，也没有真实复现原4GB异常**。实际市场规模、当时未完成频率、旧root/receipt及具体正式预算仍须依19.9第4项单独核实；不能把以上隔离通过当正式29/30日数据完整性或原异常已经消失的证明。管理员已要求提交本轮修改；下一步正式恢复仍须按19.9第4项完成核实及取得必要批准，不自动重跑任何日期、频率或repair。

### 19.13 29日1分钟正式恢复执行方案（已获专项批准）

**目标、证据及审计状态。** 对应业务方案17.10。当前实现提交`5a0b13401`，生产模块SHA仍为`615fb452a137107e0cc330963d6216e0e5a3995877144cbc0926e604b272a76f`。三条独立只读审计未发现阻断；计算、公开合同、原repair/history、年度保留及逐文件继续规则与19.2—19.11一致。未重复执行315项隔离测试、未做性能样本。65股不同活跃状态用例可增强，相关原公式按股票/频率关联且AST未变，属于证据限制，没有发现计算错误；详见[提交后审计](../../reports/macd_kdj_daily_read_20261030/post_commit_audit_20261030.md)。

**本次只读核定。** 2026-10-30 02:37（Asia/Shanghai）附近，通过正式DG GraphQL只读查询原run、四条股票链job各最近4条、活动run最多40条、原run步骤、一个现有pool及三个相关sensor；只对目标1m的年度文件做一次metadata/stat，没有读Parquet内容。证据在[本步目录](../../reports/macd_kdj_daily_read_20261030/recovery_20261029_1m/)。

| 核定项 | 当前事实及限制 |
| --- | --- |
| 正式入口 | `http://127.0.0.1:3000/graphql`，Dagster1.13.26，location=`orchestrator`、repository=`__repository__`，对应正式`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`；不初始化instance |
| 原run/缺口 | `98f3d25c-1380-47da-b079-b15701bdbbce`、2026-10-29，只有`gold_stk_mins_qfq_macd_kdj_1m_assets`失败；六频资产步骤及24项检查成功；没有更新的MACD日更run |
| 输入及完成状态 | 29日QFQ原job成功，29日原因子repair原run`536c3220-7817-483a-9b6e-b69a05beb5fe`的7项检查通过；1m的28日state存在且250,790B，29日state不存在，六个已完成频率的29日state均存在；这不是重新验收全部行情内容 |
| 旧1m现场 | 原root下精确1m operation目录存在且没有文件，无bind、冻结输入、候选或receipt；没有新旧摘要混用问题，也不删除或换root |
| 并发及目录 | 无活动run；`gold_stk_mins_qfq_writer` limit=1、active=0、pending=0；进程有界检查未发现脱管股票分钟写入者。formal/staging同设备，约2.64TiB空闲；同用户实际可写。工具隔离环境中`os.access=False`未当作正式权限错误 |
| 已加载代码 | location已加载，但加载时间为2026-10-29 08:15，早于本次修改；正式恢复前需要原生reload，不把磁盘源码提交当作代码服务已刷新 |
| 自动衔接 | MACD daily/repair、九转三个sensor当前均RUNNING。29日原因子repair实际生成2股、2014-01-02至2026-10-29的历史范围；本次1m成功后MACD repair sensor可能自动发任务，必须在其历史范围批准前暂缓触发 |

**只恢复的内容及禁止项。** 29日`gold_stk_mins_qfq_macd_kdj_1m`及`gold_stk_mins_qfq_macd_kdj_state_1m`，连同原四项blocking checks。指标只合入29日并保留其他日期；共享state按原完整生成规则处理。保持原job、partition、run config、公开参数、writer pool与DuckDB设置，不增加超时、内存或临时容量限制；不重跑已完成六频、28日、源QFQ、原因子repair或历史MACD repair，不做全局完整性审计、不造runless事件、不删旧operation/receipt。

**年度读取必要性及预算。** 依据本次1m stat，Qy=5,537,980,413B（5,595文件，5.158GiB）、Qp=6,271,310,456B（5,463文件，5.841GiB）、I=14,064,513,302B（5,594文件，13.099GiB）。I用全频率1m现存2026指标文件作为保守上界；实际仅改有29日行情的股票。前日state为V，L仍只限当年不足8根的实际上一年子集。全部文件都很小，不是单个4GiB数据文件。

复用19.7原公式，取L≤Qp、C≤15GiB的候选估算、P≤0.128GiB、Fr/Fw各1GiB、Tr/Tw各8GiB：

```text
正常读 = 6Qy + 4Qp + L + 2I + 4C + P + V + Fr + Tr < 156GiB
正常写 = C + P + Fw + Tw < 25GiB
新增空间 = (C + P + Fw + Tw) × 1.2 < 29GiB
申请向上留量：读160GiB、写26GiB、额外空间32GiB。
```

该预算包含当日选择、原年度合并、一次候选摘要、原四项检查、必要metadata收尾和原DuckDB临时读写留量；没有新增行情审计或性能测试。8GiB、15GiB都是成本估算条件，**不是新增运行限制**；不按设备缓存、列裁剪效果折扣，也不是已发生I/O。正常只执行一次，失败即停、无自动重跑。中断后重新准备的最坏增量另需约160GiB读/26GiB写，两次候选及临时占用按64GiB空间估算；本次不预先批准该第二次执行，必须按原receipt扣除已完成部分后另核定。旧六频及其候选不在预算也不重读。

原29日整run约572秒，同时包含六频成功及1m准备失败，不能用它承诺新1m耗时。没有同规模新实现实测，暂无法可靠估计完成时间；正式运行按原批次/文件进度观察，不另做全市场性能测试填时长。160/26预算不包含2股历史repair或其他日期。

**批准后执行顺序。** 制定本段时尚无正式状态写入；管理员随后已批准，实际执行结果记入19.14：

1. 取得根AGENTS要求的上述具体年度读取批准，同时明确暂缓MACD repair sensor自动历史读取。启动前仅刷新原run/活动writer/pool/关键state及空operation的小型事实；若scope、代码、原现场或并发条件改变，停下核定，不自行扩大范围。
2. 保存MACD repair sensor原`id/status/lastCursor/lastRunKey`，仅使用原生`stopSensor`停止这一项并读回STOPPED，核对cursor/lastRunKey保留；其他sensor和pool不改。若历史repair已经启动则停止本步并汇报，不并发再发一个。
3. 用原生`reloadRepositoryLocation(repositoryLocationName: "orchestrator")`刷新并读回LOADED及新versionKey；reload失败不触发run，不重启其他服务、不安装依赖。
4. 用原job的原生`launchRunReexecution(reexecutionParams: {parentRunId: "98f3d25c-1380-47da-b079-b15701bdbbce", strategy: FROM_FAILURE})`提交一次。当前1.13.26的原生实现从parent构建重跑，并保留run group/root；不能改成ALL_STEPS、重发完整七频或换一个自造写入入口。正式请求保存为本步目录的`launch-request.json`，响应保存`launch-response.json`。命令工作目录为`/Users/congming/github/goldenshare/lake_console/orchestrator`：

   ```bash
   curl --silent --show-error --fail --max-time 20 --header 'Content-Type: application/json' --data-binary @/Users/congming/github/goldenshare/lake_console/reports/macd_kdj_daily_read_20261030/recovery_20261029_1m/launch-request.json --output /Users/congming/github/goldenshare/lake_console/reports/macd_kdj_daily_read_20261030/recovery_20261029_1m/launch-response.json http://127.0.0.1:3000/graphql
   ```

   HTTP请求20秒只限制提交请求的等待，不限制正式job运行时间。响应若不明确成功，不重发；按原parent/root及最近run查明是否已创建，避免重复任务。返回后核对`rootRunId/parentRunId/partition/stepKeysToExecute`，预期只有1m资产步骤及其四项检查。原四检查分别为indicator contract/source coverage、state schema/latest coverage；若范围超出，不继续计算，按原生取消并保留现场。
5. 复用原job实际写入、原四项checks及publication receipt验收；保存run成功、两项物化、四项检查、实际文件/完成记录小汇总。不追加一轮年度扫描/摘要或公式重算；失败立即停止，保留已完成正式结果和staging，不自动重试或回滚。
6. 报告1m结果并核定后续2股repair的真实历史读写范围。**TODO：该历史范围明确批准后，按原repair job实际产物推进并恢复本次暂缓的MACD repair sensor，核对原cursor/lastRunKey及RUNNING。** 未批准前不能为“恢复开关”而启动未批准历史任务；停用状态及原值必须在本步报告明确交接，不留下无记录的开关变化。不能将本轮日更优化当作历史repair优化已经完成。

**批准前停点。** 先完成代码/方案独立审计及必要metadata预检，未做年度内容读取、停sensor、reload、提交重跑或正式补数。根AGENTS规定一般继续推进授权不能替代具体全局读取批准，因此先提出精确申请；管理员随后明确回复“确认，批准”，授权范围及实际结果见19.14。

### 19.14 29日1分钟恢复执行记录

管理员已明确批准19.13的正常一次恢复：读160GiB、写26GiB、额外空间32GiB，包含原四项检查和收尾，先暂缓MACD repair sensor，不自动重跑、不执行2股历史repair。

启动前已刷新原run、近两条MACD日更、活动run、原pool、前日/目标state及精确operation，范围未变；源码SHA仍与已验收提交一致。`repair-sensor-before.json`保存原身份、RUNNING状态、cursor及lastRunKey。另完整有界读取原run191条事件（hasMore=False），确认没有STEP_SKIPPED；四项1m checks从未启动，FROM_FAILURE会选择失败1m资产及这四项未启动检查，不套用“已标跳过步骤不再选”的情形。此项仅metadata，不重复读取行情；证据在本步目录的`approved-preflight-*`及`parent-skips-*`。

正式状态动作和job结果在下方按实际发生追加；此刻只完成获批范围记录和启动前核对，未把计划预填为成功。

按批准顺序已停止唯一MACD repair sensor并读回STOPPED，原id/cursor/lastRunKey逐值一致；随后原生reload返回LOADED且versionKey改变，刷新后再次确认sensor仍STOPPED、pool=1且空闲、无活动run。09:06通过原生FROM_FAILURE只提交一次恢复run`63c25bed-bdc8-4fee-9af8-0321b5b13ac7`，返回root/parent均为`98f3d25c-1380-47da-b079-b15701bdbbce`，`stepKeysToExecute`精确为1m资产及四检查共5步。09:06已进入STARTED，日志捕获键`vlkrlovg`；没有启动其他六频或历史repair。结果仍在执行，不能提前记为成功；原生请求/回执及首次观察已保存到本步目录。

**最终结果：SUCCESS。** 原run group内本次恢复09:06:14.256243开始，09:08:48.984675结束，154.728432秒，恰好5步均成功。只产生29日1m indicator/state两项物化和原四项成功检查；5,570份年度指标文件合入当日1,342,370行，当日state5,595行。与原已完成六频及24项检查合计，29日MACD/KDJ七频日更已齐备；原失败run仍保留其历史失败状态，不修改旧状态掩盖原因。

原报4GB错误的prepare阶段实际完成5,595个候选来源股票的全部批次，进入完整publication；全部5,571候选通过后逐文件发布。最终operation含5,571 targets、5,571份完成记录，candidates目录0文件，目标state实体250,842B。必要operation/receipt及2份冻结输入64,894,667B保留用于原续跑；没有清理正式结果或恢复依据，没有遗留测试文件。这里只读metadata/完成记录及原日志，没有追加Parquet内容审计、年度摘要或公式重算。

本次原writer日志记录：受影响旧年度文件stat合计14,024,558,618B，生成候选/正式文件14,097,349,030B，冻结输入64,894,667B；冻结输入SHA读取64,894,667B、候选SHA读取14,097,349,030B，未额外读取正式SHA。这些是对应文件大小和原摘要计数，**不是实际设备总I/O**；原输入选择、年度合并、checks及引擎临时I/O仍按批准模型计，未另做设备性能测量。候选13.13GiB在15GiB估算条件内，未添加配额、超时或额外审计。

收尾一次原生读回证明两物化与四checks均绑定本恢复run和29日分区；repair sensor仍STOPPED且身份/cursor/lastRunKey与保存值一致，无新MACD历史repair run、无活动run，原pool仍limit=1/active=0/pending=0。**TODO仍待后续处理：2股2014-01-02至2026-10-29的原MACD repair按实际产物核定历史读写范围、另获批准后用原job推进，再恢复本次暂缓的repair sensor并读回RUNNING。** 本轮不自动启动该历史任务，也不把七频日更齐备表述为repair已完成。

最终证据：[结果对账](../../reports/macd_kdj_daily_read_20261030/recovery_20261029_1m/final-verified.json)、[原生输出/检查/开关读回（附件已清理）](../../reports/macd_kdj_daily_read_20261030/README.md#report-attachment-cleanup-20261103)、[publication元数据（附件已清理）](../../reports/macd_kdj_daily_read_20261030/README.md#report-attachment-cleanup-20261103)。本阶段仅更新原方案、LLD和执行证据，没有再改实现或重跑测试，尚未提交这些收尾文档。

本节描述1m结束时点，随后已随`78a5ad31d`提交。该时点尚待的2股repair和sensor恢复TODO，现已按19.15新批准在19.16完成；当前sensor为RUNNING，不再按本节旧停点保持暂停。

### 19.15 29日2股历史repair执行方案与LLD

**目标及授权。** 承接业务方案17.11和管理员“继续推进repair执行、完成修补、提交修改”的要求。本步只通过现成`gold_stk_mins_qfq_macd_kdj_repair_job`完成29日原因子repair产物对应的历史指标/state；随后恢复本次暂停的repair sensor，再按明确文件清单提交本轮文档/证据。没有修改业务代码、配置默认值、公式、schema、repair名单生成或新读写入口的需求。具体历史读取预算未曾包含在1m日更批准内，启动前另按根AGENTS核准下列精确范围。

**当前代码和独立审计。** CodeGraph及源码核过`jobs/gold_stk_mins_qfq_macd_kdj_repair.py`、`ops/gold_stk_mins_qfq_macd_kdj_repair.py:377—650`、原公共writer/prepare/publication和repair sensor。两条独立审查分别核读写次数/成本及原job合同/开关去重，没有发现正常一次执行需要改代码的阻断。现成op先校验scope、日历/已注册日期和全部目标state，再七频顺序计算/发布，最后为14资产写completion；它不向新的daily prepare改道。复用已通过的原repair/历史相关隔离证据，不新跑性能样本、全套测试或正式试算。

**上游事实和配置。** 原因子run`536c3220-7817-483a-9b6e-b69a05beb5fe`在29日已成功，7项因子完成检查通过；沿本轮已保存原metadata取得：

| 项 | 原产物/原job取值 |
| --- | --- |
| `qfq_factor_repair_trade_date` | `2026-10-29` |
| `start_trade_date` | `2014-01-02` |
| 终点 | 原op从产物派生`2026-10-29`，不新增或传入不存在的end配置 |
| `freqs` | 固定顺序`[1,5,15,30,60,90,120]`，不能缩频 |
| `stock_codes` | 原名单`["000878.SZ","688563.SH"]`，不能空名单触发全市场 |
| `repair_required_codes_hash` | `e53fc5c69277b27eb383eb4bc5eacae92b02dfe39bd779947d7779b5874af198` |
| `upstream_batch_id` | `qfq_factor_repair:2026-10-29:633a5dece517` |
| `reason` | `qfq_factor_repair:2026-10-29` |

正常启动的runConfigData为`ops.gold_stk_mins_qfq_macd_kdj_repair_op.config`对应上表七个实际配置项（终点只派生）。实际创建请求优先调用现成decision/config纯函数从保存的原metadata生成，再与本表完整核对；不拷贝旧26/41/16股配置。正式入口是现有本机GraphQL的原生`launchRun`，selector为`orchestrator / __repository__ / gold_stk_mins_qfq_macd_kdj_repair_job`。不调用自行计算/写湖脚本，不执行本地in-process `dg launch`替代正式服务，也不恢复旧CLI/Kopia。

**读写范围和不变项。**

- QFQ只discover原2股、七频、2013—2026候选年（2013仅探测，当前无实际文件），实读现存2014—2026年文件的`ts_code/freq/trade_date/trade_time/high/low/close`一次；目标仅2014-01-02至29日。既有SSE Silver日历只读`trade_date/exchange/is_open`，按原helper筛baseline至执行当天，再取截至29日的目标日期；不是写30日数据。
- 原start是expected calendar首日时V=0；否则按现成exact前日guard取必要state，不任意回退。原op依据日历确定target_dates、核对原动态分区登记，再预检整个范围×七频state存在；本次只读stat显示每频3,116份，完整性以原op守卫为准，不新写动态分区。
- 指标只合并原2股现存受影响年度文件，非目标记录按原SQL保留。七频3,116日共享state合并时保留其他股票及原last_trade_time；读取共享文件不代表重算全市场其他股票。
- 原job的14项completion是末尾原生检查事件，不是14轮全历史审计，也不是14个新数据集/普通物化；不补普通历史materialization/check事件，不重跑29日日更或已完成原因子repair。
- 正式Lake及staging根、原16GB/4线程等连接设置、writer pool和原publication不变；不加超时、内存或临时目录限制。现场文件和逐文件记录沿原staging保留，不备份、不Kopia、不删除正式数据。

**metadata基线和预算。** 09:25只对精确2股候选年及目标七频state做一次stat，未读Parquet内容，见[metadata（附件已清理）](../../reports/macd_kdj_daily_read_20261030/recovery_20261029_repair/README.md#report-attachment-cleanup-20261103)及[预算模型（附件已清理）](../../reports/macd_kdj_daily_read_20261030/recovery_20261029_repair/README.md#report-attachment-cleanup-20261103)。Q=119份28,812,168B（0.0268GiB），I=119份65,863,089B（0.0613GiB），S=21,812份3,847,741,455B（3.5835GiB）。2013没有实际文件；当前无活动run、pool=1空闲，repair sensor仍STOPPED，没有同批次近期repair run。

```text
Q：2股七频QFQ来源；V：必要起点前state，本次预计0
I：2股旧指标年度；S：目标日期七频旧共享state
C=Ci+Cs：两类候选；P：冻结的两股指标和scoped state
Fr/Fw：footer、manifest、receipt、日志等留量；Tr/Tw：原DuckDB临时读写

正常读 R = Q + V + 2I + S + 2C + P + Fr + Tr
正常写 W = C + P + Fw + Tw
保守新增空间 = (C + P + Fw + Tw) × 1.2
```

旧指标两读分别为原年度合法性校验及合并；旧state一读保留其他股票；候选两读分别为原投影校验和一次SHA，promote只核身份和receipt，不追加全文SHA。源QFQ一次七列读取，COUNT/footer计入Fr。14 completion及收尾只复用原结果/控制记录，不再扫全史行情。

取C≤5GiB、P≤0.25GiB、Fr/Fw各1GiB、Tr/Tw各2GiB，正常读模型16.983GiB、写8.25GiB、新增空间9.9GiB；申请向上预留**读20GiB、写10GiB、额外空间12GiB**。这是正常一次含原校验、临时读写及收尾的估算，不是实际设备I/O或新运行配额。候选空间保守按全七频合计留，实际原job逐频发布；不以2股占市场比例缩小共享state成本，也不写临时读写为0。

本次不自动重试。一次中断后重新执行的最坏增量另按20GiB读/10GiB写、现场并存24GiB空间核算，须扣除真实已完成范围后另行确认，不能自动动用第二次范围。既有22日26股同类repair及约3,111日共享state正式耗时384.611秒；本次股票更少、共享state近似，只作数分钟至十几分钟的规划参考，不能保证时长或据此中断，不新做性能测试。

**失败、中断及重复执行边界。** 原repair op本身没有已完成batch跳过分支，手工launch前必须核定同batch未完成且无活动重复run。原op每频调用公共writer时未传固定publication_id，沿现成独立operation语义；正常一次可用，但**新启动整个job不保证复用此前operation或跳过完成频率**。失败保留已完成正式频率及全部现场，停止后另按具体operation/receipt制定恢复办法，不照抄日更FROM_FAILURE的root承诺、不删记录、不自动重跑。不在本次顺手改repair代码。

**执行、验收和恢复开关。**

1. 取得以上具体历史范围及20/10/12GiB预算批准后，仅刷新最新因子产物身份、同batch完成记录/近期run、活动writer/pool及本次保存sensor原状态；范围变动先停止核定。repair sensor继续STOPPED，阻止同时自动发同一任务。既有日更成功及state实体直接复用，不重做日更或额外行情审计。
2. 原14项同batch completion如果已经齐备，则不再启动job，直接核定恢复sensor；如果尚未完成且没有同批活动任务，使用完整上表config，通过原生`launchRun`只提交一次，保存`launch-request.json/launch-response.json`。工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，正式服务仍为`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`对应`http://127.0.0.1:3000/graphql`：

   ```bash
   curl --silent --show-error --fail --max-time 20 --header 'Content-Type: application/json' --data-binary @/Users/congming/github/goldenshare/lake_console/reports/macd_kdj_daily_read_20261030/recovery_20261029_repair/launch-request.json --output /Users/congming/github/goldenshare/lake_console/reports/macd_kdj_daily_read_20261030/recovery_20261029_repair/launch-response.json http://127.0.0.1:3000/graphql
   ```

   20秒只限提交HTTP请求，不限job运行。响应不明确时查run/config/batch是否已经创建，不盲目重发、不改用另一个job。观察只读本run原日志和事件进度，无额外行情读取；失败停止，不恢复可能自动再发的sensor。
3. 成功后一次读回本run的14个`gold_stk_mins_qfq_macd_kdj_repair_completed_check`，均passed且partition=29日、资产集合完整、原op设置blocking=True。14行共同scope必须逐行符合start=2014-01-02/end=29日、七频、explicit、两项代码数都为2、原hash及source_upstream_batch_id；不能只看run SUCCESS。结合原完成门禁一致性、日志中的七个operation及必要receipt/stat收尾，不读取全量价格或再算指标，不补报自造通过事件。
4. 只有14项完成事实通过才用原生`startSensor(sensorSelector:{repositoryLocationName:"orchestrator",repositoryName:"__repository__",sensorName:"gold_stk_mins_qfq_macd_kdj_repair_job_sensor"})`恢复本次一项sensor。返回时核RUNNING、id/cursor/lastRunKey与暂停前保存值一致。原start会更新启动时刻但保留这些字段；之后daemon正常tick允许推进cursor，不把正常推进误报成丢失。原sensor先检查该batch14项完成事实，ready就skip，手工job不依赖sensor run key去重。没有其他sensor监听本repair成功，因此不借恢复此开关新发另一历史任务。
5. 保存最终run/14completion/sensor原生读回、七频publication完成及候选清理状态、小型计数汇总。保留必要冻结输入和receipt，不清理正式staging恢复依据；仅清理本轮明确临时观察副本。更新原方案和本LLD最终状态/TODO，白名单提交两份原文档及本轮报告，不混入LLD13.2旧sensor收尾或工作区其他改动，不push。

批准前只完成代码/方案审计、现成产物复用和stat预检，没有读取历史行情、启动repair或恢复sensor；两条独立审查结果及预算依据保存本步报告。方案与1m收尾已提交`78a5ad31d`，随后管理员对本节精确历史范围和20/10/12GiB预算明确回复“批准”，执行事实见19.16。

**提交安排。** 管理员同时要求提交修改；若具体历史读取批准尚待答复，先白名单提交已完成1m收尾、提交后审计、2股repair方案/LLD及metadata依据，不把待执行repair标为完成。批准后原job执行、恢复sensor和最终结果再按本节追加并提交，原任务持续待办；不因等待读取批准留下已经完成但未提交的授权工作。

### 19.16 29日2股repair执行与sensor恢复记录

管理员已明确批准19.15的2股七频2014-01-02至2026-10-29历史repair、20GiB读/10GiB写/12GiB额外空间、正常一次、不自动重试，成功后恢复原sensor并提交。启动前原生小查询再次确认14项29日completion均不存在、同batch近期无repair、无活动run、pool=1且active/pending=0；原sensor仍STOPPED、最新因子run和原scope未变，源码SHA仍与已验收实现一致。没有重做年度stat或读取行情。

完整runConfig由原decision/config纯函数从保存的因子metadata生成，启动前再次逐字段核对名单、七频顺序、起点、hash和batch，未增删名单。`approval.json`记录本次精确批准，`launch-request.json`仅准备原生原job提交；正式结果按实际发生继续追加，不预填成功。

09:39通过原生`launchRun`仅提交一次现成repair，run`86d8b492-c056-412d-b9cc-551462e3188e`；返回runConfig与原helper产物逐值一致，已进入STARTED，只有原repair op一个执行步骤，stdout键`kjcvicba`。尚未恢复sensor或填写最终完成结果；不重跑1m日更、原因子job或任何已完成其他batch。

**最终结果：SUCCESS。** 09:39:15.610584开始、09:43:56.795943结束，281.185359秒。原job仅运行一次、没有中断/重试/新运行限制；完整runConfig与批准scope相同。原14个`gold_stk_mins_qfq_macd_kdj_repair_completed_check`全部成功、29日分区、资产集合完整；14行逐项验证covered起止2014-01-02/2026-10-29、全七频、explicit、两个代码数字段均2、原hash和batch相同。原op以blocking=True写这些事件，不伪造或补报检查。没有新增普通历史物化，也没有重跑日更/原因子任务。

实际2股指标重算1,209,754行，119份指标年度文件；21,812份共享state合并写回85,301,874行，包含原样保留的其他股票，不能把该行数表述为全市场重新计算。七个operation各3,133个目标/完成记录，总21,931，全部发布，candidate文件总0；没有额外读取Parquet正文、再算指标或补全局审计。冻结输入总66,943,799B及原operation/receipt保留用于原继续规则，没有删除正式数据或恢复依据，也没有本轮测试文件待清理。

原日志候选SHA累计读取3,913,605,514B、冻结输入66,943,799B；候选/正式文件大小合计3,913,605,514B，formal SHA额外读取0。候选与冻结大小低于预算估算条件；这些计数不是设备总I/O，未将缓存、投影或未测的临时I/O冒称实测节省，也没有因预算数字施加配额或中断。

14项scope验收后，原生startSensor恢复原`gold_stk_mins_qfq_macd_kdj_repair_job_sensor`为RUNNING；响应id、完整cursor及lastRunKey与1m暂停前保存值严格相同。随后只读收尾确认同batch仅本次一条SUCCESS、没有活动run、pool仍limit=1/active=0/pending=0；最新恢复后tick为SKIPPED、runIds为空，cursor随后正常推进，不误报成光标丢失。**19.13—19.14中暂缓该sensor的TODO已完成**，其他开关未改，不留暂停等待项。

独立审查仅使用本次原生结果、完成记录和恢复响应逐项对账通过，没有新增网络/Lake读取。证据：[最终对账](../../reports/macd_kdj_daily_read_20261030/recovery_20261029_repair/final-verified.json)、[原14completion（附件已清理）](../../reports/macd_kdj_daily_read_20261030/recovery_20261029_repair/README.md#report-attachment-cleanup-20261103)、[开关恢复响应（附件已清理）](../../reports/macd_kdj_daily_read_20261030/recovery_20261029_repair/README.md#report-attachment-cleanup-20261103)、[运行/去重收尾（附件已清理）](../../reports/macd_kdj_daily_read_20261030/recovery_20261029_repair/README.md#report-attachment-cleanup-20261103)、[publication收尾（附件已清理）](../../reports/macd_kdj_daily_read_20261030/recovery_20261029_repair/README.md#report-attachment-cleanup-20261103)。本轮仅提交这些执行记录及原方案/LLD状态，没有业务代码修改，不push、不混入其他工作区改动。


## 20. 2026-10-30股票分钟链及成交额恢复：方案与执行LLD（2026-10-31）

### 20.1 目标、范围、授权与前序

管理员确认已补齐Prod源后要求辅助推进30日分钟链及全部下游。本节只补2026-10-30的37项：Raw五频5、Silver五频5、QFQ七频7、MACD/KDJ七频7、state七频7、九转四频4，以及成交额Gold/Prod2。两次repair是必经的依赖操作，不另计数据集。30日普通指数日线链的5项不属于股票分钟线下游，本节不处理；不重跑已完成的29日、周/月、公告、THS等对象。

Prod任务成功表示其既定同步单元执行完成，不承担“当日全部股票代码已齐备”的保证。DG仍按现行TaskRun终态和代码覆盖两项独立判断。12:50指定日计数确认五频各5,577个代码，原缺的000010.SZ、000039.SZ各有5条60分钟记录；此计数不是全部分钟质量检查，也不替代正式冻结reference。当前没有活动run，30日Raw分区已注册，Silver分区未注册，22个直接目标均缺失。原29日QFQ、两次repair及九转成功证据复用，不读回29日价格重做验收。

**准备阶段记录：当时仅完成只读准备，尚未获得本次具体全局/年度/历史读取批准，也未触发job、切换sensor或登记分区；随后批准与执行分别见20.6—20.8。** 管理员的补齐指令授权本轮业务目标；根AGENTS要求以下具体读取范围另行批准，28/29日批准不覆盖30日。取得批准后才执行20.4，不用先开启自动sensor绕过批准。证据及预算保存于`lake_console/reports/datasets_recovery_20261030_20261031/`，准备统计不作为正式完成结论。

### 20.2 当前实现依据、配置和影响面

首次执行不改业务代码、公式、数据合同、部署、配置默认值、并发、内存或时间限制。Raw/Silver沿`defs/jobs/stock_mins_raw_update.py`、`stock_mins_silver_update.py`及`assets/stk_mins.py`的原job；reference由`asset_guards/stk_mins_prod_readiness.py`和`run_contracts/configs.py`生成。目标为空时复用原job的`reuse_existing`行为，不调用替换已有Raw的离线恢复工具。确有已生成目标、活动run或来源变化时先停下核实，不强行覆盖。20.8失败后已出现此情况，后续以20.9—20.12的待确认修正为准，不能按本段默认行为重触job代替修复。

QFQ与factor沿本LLD9/14/17及`ops/stock_mins_qfq_factor_repair.py`；MACD日更沿19节已提交的分批读取实现，不回退旧DuckDB超大字符串SQL；MACD repair沿原op、guard、`gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py`的现成decision/config函数。九转沿`assets/qfq_nineturn.py`、`jobs/stk_mins_qfq_nineturn_update.py`。成交额沿`jobs/gold_wealth_market_turnover_update.py`，其selection已含Gold与Prod同步资产，按真实依赖执行，不重复另造Prod发布入口。

CodeGraph已核原Raw入口、来源门禁和历史替换工具的差异，当前源码再核上述job selection和消费者。原业务入口只读Prod分钟源九列和必要的现行基础参考；仅成交额原Prod asset写`core_serving.wealth_market_turnover_snapshot`的30日。操作辅助入口只提交原GraphQL请求并读取原run/check/receipt，不计算行情、改repair名单或直接写Parquet。当前webserver/code location维持运行，不重启DG。

### 20.3 必要读取、预算与失败成本

只读准备已对当前年度和相关历史做一次文件路径/大小统计，未打开年度或分钟行情正文。QFQ2025年38,241份/8.8143GiB，2026年39,165份/7.7528GiB，MACD2026年39,165份/17.7187GiB。现有四频历史Silver12,464份/44.1939GiB，30日生成后为12,468份；历史因子3,117份/0.1057GiB。共享state已有21,812份/3.5835GiB，30日日更后为21,819份。

原factor识别SQL仅对29/30日因子和现行生命周期做必要计数：factor_changed=11，其他变化原因0。为了核定这11股历史文件成本，后续只取该条件下最多12个代码作metadata预算；所得11股历史QFQ770份/0.1741GiB、指标770份/0.4076GiB，2013探测路径无实际文件。这是预算用预估，不是正式名单；factor job仍只传日期，自行生成真实名单和hash/batch，MACD repair只承接其产物。若实际产物与已批准范围不符，先停下核实，不人工删减。

读取范围：①Raw只读Prod30日五频、当日股票范围、九个业务字段，生成同日Raw；Silver只读同日Raw及原Basic、identity、lifecycle、停牌和日线等既有必要参考。②QFQ七频只合并2026年度，不读取2025年QFQ。③factor repair七频2014-01-02至2026-10-30，3,117交易日；分钟来源实际按全市场四频日文件读取，不能按11股比例缩小共享来源成本。④MACD日更按当前代码只读实际需要的2026及必要2025 QFQ、29日state，并合并2026年度指标；本轮不重复优化原checks。⑤MACD repair按原factor实际名单读取必要2014—2026七频QFQ/指标，合并3,117日七频共享state、保留其他股票；2013只stat，已有预算没有2013正文。⑥九转限2025/2026四频、29日seed及原有界查询实际候选所需的2014—2026文件，早年候选合计≤1GiB、先stat；不手工重写29日seed。⑦成交额仅30日五频Silver及原Prod单日发布。当前原job依赖的完整Basic/lifecycle/identity/日历等小型参考也包含本次必要读取，不创建另一套股票池。

| 原阶段 | 正常读GiB | 正常写GiB | 阶段额外空间GiB |
| --- | ---: | ---: | ---: |
| Raw/Silver及成交额 | 4 | 1 | 2 |
| QFQ日更 | 40 | 10 | 16 |
| factor repair | 56 | 4 | 8 |
| MACD/KDJ日更及state | 248 | 36 | 48 |
| MACD/KDJ repair | 40 | 20 | 24 |
| 四频分钟九转 | 28 | 4 | 8 |

合计正常416GiB读、75GiB写，审批预留至**读420GiB、写80GiB、额外空间128GiB**。当前可用空间约2,700GiB。MACD日更按19.7原模型，Qy≤8.5、Qp≤9.25、L≤9.25、I≤20、候选C估≤22、P估≤0.125、V≤0.002GiB，footer/目录读写各1GiB和引擎临时读写各8GiB留量代入后低于248GiB读/36GiB写。候选和临时量是保守预算，文件stat字节不是实测设备I/O，不据预算新增限流、超时、配额或性能试跑。

预算含原检查、一次候选摘要、原临时工作、最终37项限定计数与receipt/stat收尾；不追加一次年度全文审计或重复SHA。失败即停、不自动重跑；保留已提升正式文件及staging、冻结输入、checkpoint和回执。中断后仅查本run/operation已完成与未完成清单，先核身份和剩余成本，再取得具体继续范围授权。最坏同范围再做一次的参考另计420GiB读/80GiB写、候选共存空间上界256GiB，这只是失败成本说明，不是第二次执行许可。正常耗时参考旧QFQ约15分钟、旧七频MACD约14分钟、既有repair约1—5分钟；11股及新分批读取场景未测，不承诺固定完成时刻，不为测时另跑样本。

### 20.4 原生执行顺序与逐步验收

工作目录固定`/Users/congming/github/goldenshare/lake_console/orchestrator`，现有`.venv`，`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`；经现有`http://127.0.0.1:3000/graphql`的`launchRun`启动，selector为`orchestrator/__repository__/<原job>`。正式命令形状为`.venv/bin/python3 -B <本轮原入口薄调用文件>`；它只传以下真实config并保存请求、响应和精确run ID。每次提交前再看本阶段同日活动/成功run，存在即跟踪/验收复用，网络响应不明时按已保存意图查原run，不盲重发。GraphQL请求只提交一次，不以另一个行情计算脚本补数。

1. 取得20.3精确批准后，保存当前五条下游sensor的原selector/id、开关、cursor和lastRunKey；通过原生stop只暂停`stock_mins_qfq_daily_sensor`、`stock_mins_qfq_factor_repair_sensor`、`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`、`gold_stk_mins_qfq_macd_kdj_repair_job_sensor`、`gold_stk_mins_qfq_nineturn_update_job_sensor`。不清cursor，不停daemon，不影响其他数据集。这样避免未经顺序验收便自动运行repair或重复提交。
2. 复用原正式股票集合函数和Prod门禁，冻结新的30日`ProdStkMinsCompletionReference`，必须五频对实际预期代码集合全部ready；计数一致不能代替该步骤。既有全市场17542仍可用，后续子集补跑不替代它。参考文件发生变化先核实，不用旧reference硬跑。Raw目标仍为空、Raw分区已注册时，用`build_stock_mins_raw_update_job_run_config(source='prod_db',prod_completion_reference=<真实reference>)`提交`stock_mins_raw_update_from_prod_job`，tag为`dagster/partition=2026-10-30`。等SUCCESS、五物化及15项原check绑定本次物化通过。
3. 只在Raw验收后补登记`cn_a_stock_mins_silver_trade_days`的30日一个缺失键；若原注册sensor已完成则不重复写。Silver及九转、QFQ、MACD、成交额共享这个实际partition definition，**不登记另一个九转分区集合**。初始只读预检中额外查询的不存在九转集合名不作为执行依据。已有Silver活动run由原sensor启动时只跟踪，否则用空config、30日partition触发原`stock_mins_silver_update_job`。SUCCESS、五物化及20项原check完整绑定后继续。
4. 运行`stock_mins_qfq_daily_update_job`，空config、30日partition；七物化及28项原check全部通过，并核原publication/输入身份回执后进入factor。
5. 运行`stock_mins_qfq_factor_repair_job`，仅`{"ops":{"stock_mins_qfq_factor_repair_op":{"config":{"trade_date":"2026-10-30"}}}}`，不传股票或虚构partition。七条原completion、真实名单/起止/hash/batch及原factor guard必须ready；无变化仍由原job形成依据。
6. 运行`gold_stk_mins_qfq_macd_kdj_daily_update_job`，空config、30日partition；14物化、28项原check及当日state通过后继续。不能把日更成功当成历史repair完成。
7. 按现成`build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision`和`_run_config_for_repair_decision`，承接步骤5实际scope和步骤6日更事实，启动原`gold_stk_mins_qfq_macd_kdj_repair_job`。七频和股票列表、start、hash、upstream_batch_id必须来自原产物；end由原op派生30日，不能新增不存在的end参数。验证14条completion的起止、名单/hash、批次一致及完整repair guard。原decision说明不需要repair时保留其明确证据，不传空名单伪造完成。
8. 两次repair gate都满足后运行`gold_stk_mins_qfq_nineturn_update_job`，空config、30日partition；四物化及四项原check通过。实际候选和前日seed若需要额外核验，只做原有界候选，禁止额外全市场历史比对。
9. 成交额Gold/Prod原job在Silver就绪后具备独立执行条件，允许由原sensor自动接续；没有成功或活动run时手工提交一次`gold_wealth_market_turnover_update_job`。其selection已含两资产，按原Gold检查和发布核验30日5频成交额，不能在成功后重复另跑Prod。
10. 最后只对本轮37项复用既有JSON、精确run物化/check、publication完成回执、必要stat及一次指定日计数收尾，不重跑180项目录审计。repair对年度/shared state的后写入按最新实际回执衔接，不把daily旧stat当成修复后的最终身份。确认同scope无重复/活动run后恢复本次暂停的五条sensor至原RUNNING状态，保留cursor/lastRunKey，并查看一次有界原生读回。若失败仍有受保护的依赖未完成，保留暂停状态、明确TODO和原因，不让自动链越过失败步骤。

### 20.5 验收、清理与记录边界

首次执行无需新的开发或性能测试；20.8失败后的必要入口修正、隔离测试另见20.9—20.12，不追溯修改首次执行事实。触发/读回辅助文件先按已有28/29日代码核对日期、job、config、资产/检查集合、原生分区与物化storage ID绑定，不能删掉旧修正或按“最新run”猜身份；只做其必要语法/静态核验，不新增全局数据检查。正常全部步骤原检查合计117项（Raw15、Silver20、QFQ28、factor7、MACD28、MACD repair14、九转4、成交额1），若原decision明确无需repair则按真实需要项计数并说明。

正式写入仅本节明确目标和必要历史repair，候选/staging只在`/Volumes/datasource/data_lake_staging`，正式只在`/Volumes/datasource/data_lake/raw|silver|gold`；不备份、不调用Kopia、不引入其他Lake根。完成后删除本轮无用的/tmp调用文件和重复中间材料，保留必要源请求/响应、原检查、scope/预算、异常证据和正式staging恢复依据，不删除业务临时库或活动日志。结果、具体日期、run ID、检查数量、sensor恢复及清理只在实际完成后追加；此处不预填成功。


### 20.6 具体范围已批准（2026-10-31）

管理员已对20.3具体范围明确回复“批准，按原job和repair顺序执行”。批准原文及预算保存为本轮`history-approval.json`。该批准覆盖本节37项、两次原因子产物repair、小型参考和正常各一次原job，不包含失败后自动重跑。后续辅助脚本只负责原job提交、状态/证据读回与必要sensor/单键登记，不另写行情计算或直接补Parquet。正式结果随后按真实run追加。


### 20.7 首阶段执行及只读预检调用纠正

30日原Raw run`53c3aace-d999-490b-9370-973191cb885d`成功，五物化/15检查；仅登记Silver30日一个缺键后，原Silver run`ae0067a5-e040-449d-a6ac-0f32b943788f`成功，五物化/20检查。原成交额Gold/Prod组合run`e0e9c922-6f01-4dff-8357-9130f846c347`成功，两物化/1检查，原日志Prod同日写入/读回5行。五个历史下游sensor暂停，cursor保留。

QFQ启动前只读辅助脚本误把DagsterInstance的方法get_run_by_id用于PostgresRunStorage，元数据读取报AttributeError；没有触发QFQ job、写湖或重复已成功阶段。纠正为原验收器已经使用的get_run_records(RunsFilter(run_ids=[rid]),limit=1)，再读dagster_run.status；仍是精确ID、一行只读查询，不改业务门禁、运行资源、批准范围或原job。纠正后只继续未启动的QFQ步骤，不重跑前三run。


### 20.8 实际失败停止：60分钟日内缺根（2026-10-31）

原QFQ run`df08f87b-2316-4368-a9f1-6771bd9c17fd`在13:11:32的120频步骤被原窗口检查拒绝，整个run于13:25结束为FAILURE，耗时865.686秒；其他6频已物化且24项原检查通过。120频错误为应有11,142窗口、实际11,097，少45窗口；失败发生在write_prepared_gold_stk_mins_qfq_rows_to_year_files之前，未写30日120频年度结果。没有重启或重跑原job，没有触发任何后续repair/MACD/九转，也没有执行最终37项计数。

仅对60频做必要聚合追因：Raw和Silver均有28股不足现行窗口所需5根、共短74根。随后仅对同28股查询Prod该日60频计数，逐股与Raw一致；代码列表及每股根数保存source60-missing-rows.csv。000010.SZ/000039.SZ两只已各补到5根，本次28股是另一种“代码存在、日内K线不齐”的问题。TaskRun终态和代码存在性通过不代表根数完整；此前12项原任务成功检查的结论保留，但撤回将其中60频Raw/Silver及其成交额视作完整的判断。

成交额Gold/Prod原组合job已经发布5行，每频由对应Silver独立汇总，故60频行/points也受缺根源影响，需补源后更新。六个已写QFQ中的60频同样承接部分源；保留所有已写正式数据和staging，不回滚、不删表、不拿其他频度现场合成或放宽120频检查。最终为4个原run：3成功、1失败、0重跑；18项已有输出、60项原检查通过，不能表述为37项完整。

五条受保护下游sensor仍STOPPED、cursor保留，当前无活动run；其他数据集及sensor不变。**TODO：先补Prod28股30日60分钟缺根，再按当前受控入口核定受影响Raw/Silver60、QFQ60/120、成交额的最小修复范围及继续身份；完成原两次repair和其余下游后，恢复这五条原sensor。** 原Raw日更reuse_existing不会重新下载已有文件，不能直接重触整个job当成修复；本节失败停止授权不包含自动第二轮。新的具体恢复步骤需先对齐本方案/LLD，保留其余已完成频度，禁止绕过检查或自行引入备用计算。

本轮没有修改业务代码，没有安装、改公式/合同/并发/内存/运行限制，没有重复180项审计。只读验收及异常证据见本轮报告README和execution-summary.json；仅本轮操作辅助文件可归档后精确清理，业务staging及原日志继续保留。

### 20.9 Prod补源通过，但原job不能替换已有分区：显式替换修正

**当前事实与状态。** 管理员已补Prod并要求核验后继续。14:04:19单日计数显示60分钟5,577股、27,885行；原28股各5根，现行120分钟来源合同的09:30/10:30/11:30/14:00/15:00五个时间齐备，异常代码数和额外时间行数为0。本轮没有读价格明细、扫描历史或触发正式job。证据为`reports/datasets_recovery_20261030_20261031/resume_140419/prod60-count-time-audit.json`。DG仍保留20.8旧文件及运行事实；不能把源端通过写成DG已补齐。

**不能直接重复触发的代码依据。**

| 当前代码 | 当前行为及本轮影响 |
| --- | --- |
| `assets/stk_mins.py::write_raw_stk_mins_partition_from_prod_db` | 目标已存在就调用`_reuse_existing_raw_stk_mins_partition`，没有重新读Prod；旧60分钟缺根保留 |
| `_materialize_silver_stk_mins_partition` | 默认`write_new`未传overwrite；目标存在时公共writer抛FileExistsError |
| `write_silver_stk_mins_partition` | 已有`overwrite=False`参数；受控替换能力存在于writer，尚未由原job config暴露 |
| `_write_raw_stk_mins_rows_from_prod_db_source` | 已使用`MinutePartitionPublication(overwrite=True)`；只需让明确替换模式走到原路径，不另写抽取算法 |
| `bootstrap/stk_mins_raw_replace_from_prod_cli.py` | 非active原job，固定五频；本次仅60频，不替代为该离线入口 |
| `bootstrap/stk_mins_silver_replace_from_raw.py::_staging_root/_quarantine_root`及apply | 在正式Lake内建临时目录并移动旧文件作备份，与根规则冲突；本次禁止运行，也不扩展为重写旧工具 |

CodeGraph已查两项parse函数的调用方均为`assets/stk_mins.py`相应materialize入口，结合源码核对`configs.py`、Raw/Silver jobs、Raw/Silver sensors、config builder和相关测试。两项schema为股票分钟线五频共用，其他数据集使用各自schema；本次不改共享publication实现、Prod程序、指数/ETF、schema、公式或repair。官方依据为[asset selection](https://docs.dagster.io/api/dagster/assets)及[GraphQL launchRun](https://docs.dagster.io/api/graphql)；本机实际1.13.26的`dagster_graphql/schema/inputs.py::GrapheneJobOrPipelineSelector`同时提供`assetSelection`和`assetCheckSelection`，不是新建job才能选择子集。

**设计确认边界。** 本节至20.12最初作为待确认方案提交，未先行编码或写入。新增显式运行模式属于入口合同扩展；依根AGENTS第9/13项及orchestrator AGENTS“用户明确确认设计方案前，禁止修改正式Python代码……或运行入口”，先完成方案/LLD及源核验，再取得20.10记载的明确批准，随后才完成20.13的实现和隔离验证。既有历史批准范围不扩大，批准、测试通过和正式补数完成是分别记录的事实。

### 20.10 最小代码改动、配置与发布规则

管理员已对20.9—20.12明确回复“批准修正、验证后继续补齐”，包括新增显式模式、隔离验证、限定受影响范围和382/67/128GiB继续预算。后续才进入开发，原日期/历史范围和失败停止规则不变；不是批准重跑整条链或绕过原检查。执行及实现结果在取得真实证据后追加。

1. **`run_contracts/configs.py`。** Raw/Silver两项write mode Literal、Dagster Selector及对应parse各增`replace_existing: {}`。默认Raw=`reuse_existing`、Silver=`write_new`保持原样。Raw新增分支仅支持`source=prod_db`，仍要求真实`prod_completion_reference`，拒绝Tushare替换；原`merge_repair`的Tushare子集语义不变。parse对选择多个分支继续拒绝，不将错误配置回退成默认。不要把正常合法的已有文件或源补齐变化当作错误；显式替换正是本次应支持的路径。
2. **Raw公共writer。** `write_raw_stk_mins_partition_from_prod_db`新增keyword-only `overwrite: bool=False`；只有`target.exists() and not overwrite`才提前复用。其余仍使用原九列投影、当日/频度/股票过滤、Prod只读resource、原SQL、候选校验及publication；不改源完成reference的判断口径，不加入第二套分钟质量算法。Raw materialize完成原reference校验后，仅当新模式显式选中才传`overwrite=True`；其余调用点保持默认，不改正常sensor发出的config。
3. **Silver原asset入口。** `reuse_existing`分支维持只读；其余分支调用原`write_silver_stk_mins_partition`，仅新模式传`overwrite=True`。沿原停牌过滤、身份映射、价格/量额规则和粗频1m来源处理，原`_preserve_frozen_silver_stk_mins_rows`继续从正式旧分区保留已批准冻结股票记录；当前冻结名单600355.SH/300344.SZ/300391.SZ与这28股不重合。不能借重新生成丢掉冻结记录，不增加手工合并逻辑。
4. **运行结果说明。** 明确替换模式在materialize入口用`dataclasses.replace`将write result的`write_mode`设为`replace_existing`，再生成原metadata/日志。Raw原字段保持；Silver `materialization_extra_metadata`、`_silver_stk_mins_human_metadata`及完成日志中原来仅对`write_new`展示生成统计的分支，改为同时接受`replace_existing`。只有`reuse_existing`才标记`reused_existing_partition=True`及“未改写Parquet”；替换应展示源行数、过滤/保留/重算等原统计，不能显示为只读复核。无需新状态表、summary资产或额外控制文件。
5. **配置审计。** 配置名仍为每个股票分钟asset的`write_mode`，新增值无默认生效；来源为人工单次run config，持久化于Dagster原run配置和物化metadata，作用域为本次选定的日期/资产。不是env、数据库全局设置或DuckDB资源参数。消费者仅上述parse/materialize、schema和测试；`build_stock_mins_raw_update_job_run_config`、`build_stock_mins_silver_reuse_existing_run_config`及两sensor保持原输出，不自动选新模式。不新增UI/外部API、并发/超时/内存参数，也不修改其他dataset配置。
6. **候选、原子替换与恢复。** Raw/Silver继续调用原`defs/io/minute_partition_writer.py::MinutePartitionPublication`，候选与receipt只在正式外staging；校验后原`os.replace`逐文件替换，不移动/删除旧文件、不备份/Kopia。新补源必须使用新的run root：旧目标/上游已变，不能沿旧已完成receipt伪造续跑。新run内部中断后的人工续跑才可沿相同root/原receipt；源身份及目标未变时复用已完成文件，发生变化就保留现场停止，不能绕过校验。源行数/内容发生外部变更的风险仍按原resource和现场核验处理，不声称本次增加了跨Prod修改的自动识别能力。
7. **互斥和加载。** 启动前查有无同日同频Raw/Silver及QFQ writer活动；原逐目标锁与QFQ pool保持，不新增并发锁或限额。五条下游sensor继续按20.8保持暂停，保留cursor，不暂停其他数据集。隔离验证通过后通过正式code location重新加载并读回schema/代码位置状态；不重启整个DG、重置daemon或清cursor。若有活动冲突则先停下汇报，不取消他人任务。

### 20.11 隔离验证与实现对账

只用orchestrator现有`.venv`和临时资源，不访问正式instance/Lake/Prod做测试，不安装依赖或做性能样本。新增测试建议文件`tests/test_stk_mins_replace_existing.py`；已有配置/Raw/Silver/publisher测试按下表最小必要范围复用，先核对实际夹具，不能凭消费者反推真实合同。

| 必须证明的口径 | 实现位置与测试要求 |
| --- | --- |
| 默认不变且仅显式替换 | configs两schema/parse；Raw默认reuse、Silver默认write_new、显式replace通过、多个分支拒绝；Raw替换Tushare或缺reference拒绝；原builders仍不产生新模式 |
| 原Raw job真正重新取得补齐来源 | 临时旧分区缺根，按现行Prod九列和物理类型构造修复后来源；走真实Raw writer及publication，断言新根写入、原值/精度正确；默认路径不调用源builder、旧文件不变。Prod网络层替身须明确，不把隔离结果称作Prod接入验收 |
| 原Silver job确实替换且算法不变 | 合同来源为原Raw生产者/schema及现有Silver夹具；临时1m/60m、identity/日线/停牌输入走真实Silver转换和writer；独立字面断言目标时间/值/单位，冻结股票旧记录保留；默认write_new仍拒绝、reuse仍不改文件 |
| 替换失败不污染正式目标 | 隔离候选不合法/提升前失败，旧目标字节不变；保留receipt后沿同root续跑；提升后回执中断可正确识别完成，不重复源抽取；源身份变化会停止，合法补齐用新root可以替换。复用现行publisher相关测试，不改共享publisher来迎合新模式 |
| 原job只执行所选资产和检查 | 在隔离Definitions/instance构造与原GraphQL相同子集，Raw仅60及3检查、Silver仅60及4检查、QFQ仅60/120及8检查；未选频度/上游不得执行。资产路径、partition和check目标物化绑定必须验证，不能只断言run SUCCESS |
| metadata如实说明替换 | replace显示真实写入统计、不标“未改写”；原reuse只读描述仍正确；默认说明和其他dataset元数据不变 |
| repair和下游不因本修正改变 | 现有factor/MACD repair配置、名单生成及schema不改；静态调用/差异和相关最小合同回归核对。QFQ子集只变恢复选择，不改公式、年度合并及历史保留 |

测试后做致命错误基线与本次修改文件Ruff、文档完整性检查；逐条记录代码/测试/证据映射，未覆盖边界明确说明。正式Prod14:04计数只证明本次缺口覆盖已好，不替代上述隔离验证或正式job验收；没有必要再次读取全市场历史来证明模式开关。不因本轮测试重跑已完成补数。清理本轮隔离临时资源，保留必要报告；现行正式staging不在测试清理范围。

### 20.12 获准后的最小补数、预算与最终验收

**资产和原job选择。** 沿20.4正式服务、工作目录、DAGSTER_HOME和`launchRun`入口，selector增加原生`assetSelection`及对应`assetCheckSelection`；check names取当前Definitions，不能手写新检查或省略。新运行partition tag仍为30日。config仅含被选op，不能继续使用全五op config制造子集歧义；Raw可复用原builder生成真实reference配置后取60m一项，再明确替换`write_mode`，不改builder默认行为。执行前用隔离验证及正式只读schema/执行计划确认选择；服务验证若不能限定，则停止，不改成整个job或离线直写。

| 顺序 | 原job及仅选资产 | 必要结果 |
| --- | --- | --- |
| 1 | `stock_mins_raw_update_from_prod_job`：`raw_stk_mins_60m`，Prod source、原reference、replace_existing | 一份30日Raw60替换，1物化/3原检查，验证新源27,885行与原统计；不重写Raw其他四频 |
| 2 | `stock_mins_silver_update_job`：`silver_stk_mins_60m`，replace_existing | 一份Silver60替换，1物化/4原检查；行数以原过滤/冻结/重算统计为准，不把Raw27,885硬套Silver；不重写Silver其他四频 |
| 3 | `stock_mins_qfq_daily_update_job`：`gold_stk_mins_qfq_60m`、`gold_stk_mins_qfq_120m`，原空业务config | 新root读修复后Silver60，合并2026年度；2物化/8检查，120完整窗口仍用原检查；不复用失败根的旧冻结输入 |
| 4 | `gold_wealth_market_turnover_update_job`原Gold/Prod组合 | 由新Silver更新30日五频汇总/Prod五行，2物化/1检查；保留其他日期，不另造单频发布入口 |
| 5—8 | 原因子repair→MACD日更/state→原MACD repair→九转 | 完全沿20.4步骤5—8的真实产物、原job和检查；此次均尚未启动，不人工填写11股预算名单 |

**复用已有成功步骤。** 旧QFQ run`df08f87b-2316-4368-a9f1-6771bd9c17fd`整体仍是FAILURE；只复用其1/5/15/30/90五个成功asset及各4项原检查。旧60物化/检查不作为当前结果；120原本无物化，必须新生成。新的60/120来自新run，两者与旧五频逐资产绑定实际物化storage ID、30日partition、同run检查目标，合计7频/28项有效检查，不要求同一run，也不能谎称旧run已成功。原factor物理readiness按频度/日期读取来源，不要求七频来自同一run；不因此改guard。后续repair写入按其实际publication覆盖最终物理身份，不拿日更旧stat当最终身份。

**计数和预算依据。** [本次受影响文件stat（附件已清理）](../../reports/datasets_recovery_20261030_20261031/README.md#报告附件清理2026-11-01)仅读取路径和大小：Raw60=1,005,189B，Silver60=791,951B，必要1m Raw=31,712,927B；两个QFQ频度2026年各5,595份现存年度文件，共295,973,169B（约0.276GiB），包括不一定写入的其他身份，只作保守存量上界。实际新目标由原job生成，沿当前5,571有效股票预计每频5,571份，不能用stat5,595冒充30日应有股票数。此次不读2025年QFQ来做日更，也不额外重审其余五频年度文件。

| 本次继续阶段 | 读GiB预算 | 写GiB预算 | 额外空间GiB预算 |
| --- | ---: | ---: | ---: |
| 受影响Raw/Silver60及成交额，含原检查/摘要 | 4 | 1 | 2 |
| QFQ60/120合并2026及8原检查/单次候选摘要 | 6 | 2 | 4 |
| 尚未启动factor repair，原范围 | 56 | 4 | 8 |
| 尚未启动MACD日更/state，原范围 | 248 | 36 | 48 |
| 尚未启动MACD repair，原范围 | 40 | 20 | 24 |
| 尚未启动九转，原范围 | 28 | 4 | 8 |

此次继续正常一次预留**读382GiB、写67GiB、额外空间128GiB**，含原必要参考、检查、候选/引擎工作和最终37项限定收尾；其中此次新增重做为10/3/6GiB，主要余量仍是原先尚未执行的历史步骤。QFQ两个频度旧年度约0.276GiB，源/候选扫描、年度保留/合并、原checks和临时工作均计入6/2/4，不能只以源文件大小宣称总I/O。此前已执行部分另保留原证据；没有设备累计计量，不声称此次预算加之前实际I/O仍在最初420GiB内。历史读取范围仍是20.3获准内容，没有增加2025日更来源、更早年份、股票名单或全局审计。预算是估计而非新运行限额，不加超时、并发、内存或硬磁盘配额。

同一job内的原publication完成复用以实际receipt为准；失败或中断即停，不自动重跑。最坏全部剩余范围重做的增量另为382GiB读/67GiB写、两轮候选并存空间上界256GiB，仅说明失败成本，不是第二次授权；实际发生时先按未完成范围重新核定。原Raw/Silver及两QFQ频度预计比首次全七频更短，后续仍参考20.3分钟级至十几分钟级原耗时，不承诺固定总时长、不进行新性能测试。

**最终收尾。** 每步复用原run/check/receipt及必要stat，不在每阶段做全目录审计。最后只做一次30日本轮37项物理计数，按最新实际结果覆盖117项逻辑检查（Raw15、Silver20、QFQ28、factor7、MACD28、repair14、九转4、成交额1）；重复产生的旧检查只留历史，不能叠加冒充有效覆盖。成功后沿原保存selector/id恢复五条sensor并保留cursor/lastRunKey，核对一次原生读回；失败则保留现场和暂停，明确停点。原异常报告、正式文件、必要receipt和冻结输入保留；只删除本轮确认无用的调用/观察副本和隔离测试临时文件，不清除正式恢复依据。

### 20.13 显式替换模式实现与隔离验收（2026-10-31）

取得20.10所记明确批准后，仅修改`run_contracts/configs.py`及`assets/stk_mins.py`的指定位置，并增加`tests/test_stk_mins_replace_existing.py`。两个schema/parse、Prod限定与reference要求、Raw默认overwrite=False、Silver显式传overwrite、结果mode及生成统计均按20.10实现；原默认config builders的AST与HEAD逐函数一致。共享publication、公式、历史repair、其他数据集、原job selection和sensor源码未改。

必要隔离回归54项通过，报告`resume_140419/isolation-tests.xml`。其中本轮14项实际覆盖：原Prod九列临时源→真实Raw转换/候选/替换；缺根补齐、默认复用、坏候选保留原文件；提升前/后中断沿同root恢复且不重复抽取、来源身份变化拒绝；真实Silver转换/替换及三只冻结政策中的600355.SH原值保留、默认拒绝与reuse只读；原Raw/Silver job分别只执行60频并由原3/4项检查验证，target materialization run绑定和30日分区正确。QFQ只验证原job60/120及8项检查选择合同，没有在隔离测试重跑其未改算法。Prod网络、完成探测和挂载检查由明确替身隔离，不把这些测试说成正式Prod端到端验收；真实源覆盖依据仍为14:04聚合，正式运行尚待下一步。

全src/tests致命Ruff基线及新增测试文件完整Ruff通过。对两个既有修改文件执行完整Ruff，另存18项既有语句上的风格/异常类型等问题，未放宽规则或夹带清理；不能宣称这两个文件完整Ruff无告警。实现映射、默认builder比对和测试中更正的两处Dagster取值方式，见`resume_140419/implementation-reconciliation.json`及`ruff-existing-findings.json`。没有测试访问正式Lake/instance/Prod，没有新装依赖、性能试跑或业务数据写入。随后才允许按20.12加载code location、最小正式预检和原job逐步推进；此处不预填补数成功。

**正式只读收尾的查询调整。** MACD repair已SUCCESS后，原只读guard为补查事件storage ID，在每个检查上重复调用`asset_check_record_event_storage_id`，对同一两秒时间窗反复查询`event_logs`。活动查询证据`resume_140419/readback-query-status.json`显示等待为IO，不是repair仍在计算。此处只调整本轮观察脚本，不修改正式guard、sensor、数据库索引或业务job：沿已保存的真实因子/repair producer run ID，各用`get_records_for_run`一次取回原ASSET_CHECK_EVALUATION（上限100且必须has_more=false），用真实记录的时间戳、类型及原filter取出该窗口记录，再交回原guard逐项检查run、资产、检查名、分区及metadata、storage ID；原最新检查查询仍由正式storage执行，不自造通过或事件编号。未绑定已验收producer或窗口内没有真实事件就停止，不能回退成全事件扫描。九转及最终同批gate核验复用这批真实事件，避免再次扫描同一窗口。

该调整只改变有界元数据读取方式，不增加数据读取/写入或新的业务执行。先以独立字面小样本验证类型、开闭时间边界和排序，并将真实run记录与已保存factor事件编号对账；仅在此后停掉本轮自己的旧只读观察进程并按相同原run重新验收，不取消或重跑已成功job，不改运行限制、不清现场。原逐文件receipt/stat验证继续保留。


### 20.14 30日实际恢复、两次repair与收尾结果（2026-10-31）

20.10具体批准后已按20.12顺序完成。此次8个原job均SUCCESS：

| 阶段 | 原run | 原检查 | 耗时秒 |
| --- | --- | ---: | ---: |
| Raw60 | `cb411608-38ea-471f-85e1-9ba50db8dcf2` | 3 | 2.884 |
| Silver60 | `31570610-c418-4eb6-bc8d-7e24d058e284` | 4 | 2.969 |
| QFQ60/120 | `500eac06-3717-442f-9bc0-559f322d0b21` | 8 | 150.052 |
| 成交额Gold/Prod | `19e4687b-43d6-49cf-a1ce-b3b2d5eee2dc` | 1 | 1.668 |
| 因子repair | `ec3436f3-6a4d-42ab-b696-7db9972563ab` | 7 | 80.070 |
| MACD/KDJ日更/state | `c92dc571-0be1-42ce-a000-50efe526d4b9` | 28 | 857.234 |
| MACD/KDJ repair | `390bc1d3-4db8-4f23-ba9b-bf6058b0a14c` | 14 | 382.736 |
| 四频九转 | `00a689cb-d7e2-4ac6-b4b7-3700edf9f221` | 4 | 70.392 |

本轮37项一次限定计数全部有数据，缺失0；117项逻辑原检查覆盖按实际资产/日期/物化ID汇总，不叠加旧重复检查。QFQ旧失败run保持FAILURE，只复用1/5/15/30/90五个成功步骤及20检查，新的60/120为2物化/8检查；原Raw/Silver其他四频未重跑。Raw60为27,885、Silver60按原停牌规则保留27,855，QFQ120恢复11,142完整窗口。

两次原repair的实际名单均为上游产生的11股、2014-01-02至30日、3,117日。MACD repair更新该11股770年度文件及七频21,819共享state，保留其他股票，14项完成检查及同一upstream batch/hash均通过。实际修复后才推进四频九转，原4检查及发布通过；seed/candidate合并历史18,972,200B，2025年前14,895,834B，均在批准范围。最后计数36项Lake只COUNT，Prod1项复用其原job当日5行写入/读回证据，未重复全局审计。

五条本轮暂停sensor已恢复RUNNING，恢复返回时身份/cursor/lastRunKey保持，cursor修改0；随后一次读回无活动分钟链run。隔离测试临时目录和本轮调用目录已清，正式结果、必要staging/冻结输入/回执及原日志保留。恢复与清理没有更改业务算法、并发/内存/超时、Prod部署或其他数据集。

慢查询调整没有造成业务重跑：旧MACD repair只读验收在切换前已经成功，未终止该进程或重做验收；后续九转/最终gate使用真实producer的21条检查事件缓存，已与独立保存的事件编号核对。原正式guard及MACD repair sensor同类时间窗查询仍为性能TODO，另行方案处理，不借本次扩改。

[最终结果](../../reports/datasets_recovery_20261030_20261031/resume_140419/final-result.json)、[计数](../../reports/datasets_recovery_20261030_20261031/resume_140419/final37-physical-count.json)、[恢复sensor（附件已清理）](../../reports/datasets_recovery_20261030_20261031/README.md#报告附件清理2026-11-01)、[清理（附件已清理）](../../reports/datasets_recovery_20261030_20261031/README.md#报告附件清理2026-11-01)及报告README为实际依据；预算不等于实测设备I/O。本轮代码、文档和报告随20.15限定范围提交归档，其他工作区改动不纳入。

### 20.15 30日全部补齐后的记录、清理和限定范围提交（2026-11-01）

**本步目标和授权。** 管理员已要求10月30日补数收尾、更新执行记录、清理本轮无用临时文件并只提交相关修改。本步不新增开发、正式数据读取、检查执行、job、sensor操作、数据库或Lake写入。最后一次完整审计于10月31日22:18完成，164项通过；收尾只读取已保存JSON和代码，不将历史观察时间改写为11月1日。

**记录和依据。** 原37项、117项逻辑检查覆盖和两次11股repair见20.14，保留旧失败run与首次停止记录。Prod补齐两只指数后，Raw指数日线→Silver→主要指数Gold→日线九转→Prod发布由原sensor依次自动运行成功，12项原检查通过；四个Lake文件分别820/820/11/11行，Prod九转11行。归档原job、检查及计数证据为报告目录`index-daily/final-verification.json`，最终完整审计为`date-audit-20261030-final.json`。完整目录的物理完整性/更新日期审计和原job检查是不同证据，不能把164项有数据说成全市场字段质量逐项验收。

**代码和提交边界。** 本轮入口扩展只有`run_contracts/configs.py`、`assets/stk_mins.py`和`tests/test_stk_mins_replace_existing.py`。检查Git基线发现，股票Raw/Silver候选写入接入及`io/minute_partition_writer.py`早先已获准实现、测试并实际使用，但尚未提交；显式替换依赖该完整提交过程，不能只提交调用却遗漏模块。因此本次纳入该模块及股票接入，不把它描述为本步新开发，不修改其实现。普通指数分钟线接入、ETF、资金流、其他日期文档和其他工作区修改不提交。两份本方案/LLD只提交本步及第20节/方案17.12以后30日相关内容，保留LLD此前23日sensor等未提交段落在工作区；不按整个目录或全部脏文件暂存。

**清理顺序和禁止项。** 先把必要源端阻断证据、五个原job最终检查、补齐后计数及最终完整审计原样归档；按明确文件清单校验归档摘要后，才删除本轮不再使用的临时副本。重复检查JSON若已完整包含在最终核验JSON中，先核对内容一致再删除。历史审计JSON及聊天已链接的报告保留；不遍历清理共享临时目录，不删除正式Parquet、staging候选/receipt/冻结输入、Dagster日志或其他任务文件。前次调用目录和三处隔离测试目录已删除，本步只确认其仍不存在，不再次操作。

**大型执行元数据归档。** 收尾盘点发现本轮报告内`macd_kdj/daily-target-identities.json`、`macd_kdj/repair-target-identities.json`和`nineturn/metadata-preflight.json`（均位于`resume_140419/`）合计69,023,175字节，属于已完成操作的身份/stat核对清单，不是行情或正式staging回执。保留其完整原始内容，以标准gzip归档到同目录`.json.gz`，写出时流式计算原字节SHA-256，再解压校验摘要和字节数后才删除未压缩副本；失败保留原文，不覆盖现有不同归档。压缩映射和摘要保存`closeout-metadata-archives.json`，查阅时可解压，静态helper中的历史路径不改写成新执行入口。其余JSON和聊天已链接历史报告不压缩，不处理正式Lake或staging。

提交检查另发现已执行源码留存`resume_140419/helper-final-sources/nineturn_readback.py.txt`末尾有原始空行；不改写执行源码字节，也按上述办法原样gzip保存并记录映射。`source60-missing-rows.csv`只把CRLF换行为LF，逐单元格比较前后相同，并记录原/新摘要；README去掉末尾多余空行。这些只处理报告格式，不改变源清单、执行源码、业务实现或历史运行结论。

**成本、中断与验收。** 正式行情/数据库读取和业务写入均为0，仅操作本轮报告、执行元数据和代码；含上述压缩校验、一次中断后同范围继续及收尾，元数据读取按256MiB、写入32MiB、额外空间64MiB预留，不把它称为行情I/O。正常一次，不自动重新审计或执行补数；中断后以已归档文件及清理清单为依据核对，只继续未完成的文件操作，不删尚未验证的副本。复用已通过54项及3条独立事件读取测试；本步不改代码，补做与实际提交依赖相关的32项必要隔离回归，临时根限定本轮专用`/private/tmp`目录，测试结束归档小型结果后删除夹具。运行文档完整性检查、相对链接核验、暂存差异检查；提交前逐项比对白名单，确认未暂存其他文件或LLD旧日期段落。在当前`dev-interface`提交，不新建分支/worktree，不推送、不部署。实际清理及验证结果记报告README和`closeout-cleanup.json`，不预填未执行结果。

### 20.16 五个恢复报告目录的精简（2026-11-01）

**目标、授权和依据。** 管理员认为恢复报告过多，已明确要求删除无用材料。本步只清理`lake_console/reports/`中下表五个目录，不删除整个reports。当前共921个文件、121,765,332字节；正式DG/src/scripts及原日期审计工具中未发现读取这些目录的执行依赖，只有股票分钟任务日期测试的说明引用22日一份真实任务样本，故保留。正式Lake、staging、checkpoint/receipt、instance日志、代码、测试及其他报告目录均不删除或改写。不另存整套备份、压缩包或逐文件清理报告。

**按目录保留的精确清单。** 下列路径均相对于各自目录，除此之外的文件删除；README保留原操作记录和章节锚点，只加清理说明及修正附件链接。

| 目录 | 保留文件 |
| --- | --- |
| `datasets_recovery_20261021_20261024` | `README.md`、`final-verified.json` |
| `datasets_recovery_20261022_20261024` | `README.md`、`major-index-final-verified.json`、`stock_resume_20261025/summary.json`、`qfq_recovery_20261025/summary.json`、`factor_repair_20261022/summary.json`、`macd_recovery_20261025/summary.json`、`nineturn_recovery_20261026/summary.json`、`resume_20261025/prod-stock-task-evidence.txt` |
| `datasets_recovery_20261023_20261026` | `README.md`、`final-reconciliation.json`、`batch9/final.json`、`batch10/final.json`、`batch11/final-verified.json`、`operational-closeout-20261027/sensor-restoration-summary.json`、`ths-recovery-20261030/execution-summary.json`、`ths-recovery-20261030/final-state.json`、`ths-recovery-20261030/2026-10-27-raw-verified.json` |
| `datasets_recovery_20261028_20261029` | `README.md`、`execution-summary.json`、`final-physical-audit.json`、`index-daily-nineturn/final.json` |
| `datasets_recovery_20261030_20261031` | `README.md`、`date-audit-20261030-final.json`、`resume_140419/final-result.json`、`resume_140419/final37-physical-count.json`、`index-daily/final-verification.json`、`closeout-validation.json` |

共保留29个文件。删除重复状态/配置、过程探测、历史辅助脚本留存、测试输出、逐文件身份/stat和旧压缩包。23日后续THS记录显示23/26日已成功、27日当时仍失败，原样保留该结果和错误原因，不把附件清理说成业务修复，也不查询当前源或DG状态刷新结论。既有保留JSON不重写其历史路径或时间。

**引用处理和影响面。** 只修改这五份README及其直接引用它们的Markdown/HTML文档。指向被删附件的超链接转到所属目录README的“报告附件清理（2026-11-01）”，说明文件已删除、原操作结论在原章节；保留文件及README原章节锚点继续有效，不伪装原详细日志仍在。文档中的历史命令和裸路径只描述当时操作，不要求恢复附件或重跑。其他报告中的归档JSON或源码留存不为改路径而重写；实际执行代码和测试均不修改。

**执行、中断和预算。** 先冻结保留/删除清单，再按准确路径逐文件删除并去掉因此产生的空目录；目标必须属于上述五个真实目录，路径、大小或修改时间与清单不符就停下核对，不使用全reports的递归删除。无用且未提交的附件同样在本次删除授权内，不假定均可从Git恢复；保留文件不得删除。中断后按同一清单只核对剩余文件，已删项不重建；不自动审计或补数。只读本轮小型报告和代码/文档，元数据/文本读取预算16MiB、写入2MiB，待删文件合计不超过122MiB；删除大清单不读取其正文。一次中断和最终文件清点仍限同一范围，不新增备份或正式业务I/O。

**验收。** 确认保留29文件均存在、原样JSON/真实任务样本内容未改、被删文件无残留、无指向被删附件的活动Markdown/HTML链接；保持五份README章节不变，运行文档完整性和差异检查。业务代码/测试未改，不重新执行原job、数据检查或全局审计，不新增测试夹具。本轮只删除和修正文档，当前指令未要求新的Git提交，保持其他工作区改动和空暂存区；结果和实际文件/字节数记五份README的清理说明，不再生成一批过程报告。

**实际结果。** 已删除892个文件、121,079,255字节及30个空子目录；五个目录由921文件/121,765,332字节变为29文件/696,647字节。各目录分别保留2、8、9、4、6文件，24份非README结果/样本的字节摘要与清理前一致。原章节和历史事实保留，273处已删除附件链接改为对应清理说明；修改范围为五份README及七份直接关联设计文档。文档完整性、范围内差异检查和剩余链接检查通过，无指向已删附件的活动链接；暂存区为空，没有新增Git提交。临时删除清单在完成核验后删除，不保留另一套过程材料。正式数据/运行记录、staging、代码和测试操作均为0。

**后续限定范围提交。** 管理员随后明确要求只提交本次报告清理与引用修正。提交仅包含五个报告目录的删减和必要保留文件、已跟踪文档中的本次清理说明/引用改动；报告22日README、任务日期LLD和本LLD的其他旧改动留在工作区，不整文件带入。`dagster-index-daily-staging-write-plan-and-low-level-design.md`、`dagster-minute-raw-silver-staging-write-plan-and-low-level-design.md`原本未跟踪，无法只提交其中引用改动而不带入整份旧方案，因此两份文件留在工作区，不新增到本次提交。提交前核对逐文件名称与状态、文档逐段差异、保留文件及引用目标；当前`dev-interface`提交，不推送，不改代码或正式资源。上段“暂存区为空、没有提交”保留为清理完成时的历史状态。

提交格式检查发现所保留的真实任务样本文本第3行表头末尾有空格；只去掉这一处尾空格，任务数据行及JSON保持原样，不修改夹具值或测试预期。前述24份原字节一致为删除完成时的核对结果；此处另记提交前的格式整理，不以此声称重新核验了Prod。


### 20.17 其余恢复过程附件的清理（2026-11-03）

**目标、授权与范围。** 管理员明确指`lake_console/reports`并要求将上述recovery临时文件清理。本步承接20.16，只处理当前该目录中路径含`recovery`的605份文件、14,249,238字节，覆盖18个目录或单文件名称；不是删除整个reports，也不处理根`reports`。按准确清单删除539份过程附件、12,969,561字节；保留66份说明/最终结果及测试来源。被保留的原JSON和样本不改正文；历史README/分析说明保留，补充附件已清理的说明，避免把旧路径当成再次执行要求。未跟踪或ignored过程附件同属授权范围，不假定它们都能从Git恢复。

**代码和影响面依据。** 逐项搜索这些名称在正式src、orchestrator、scripts、tests及配置中的引用，未发现固定读取这些目录的正式调度依赖。`moneyflow_continuation/submission.py::validate_new_output`只允许运营显式指定reports作为输出位置，不固定消费本轮旧文件；正式控制记录另存，不在删除清单。`tests/test_stk_mins_task_run_dates.py`说明引用22日报告里的TaskRun 16729真实来源，故保留该样本。通用审计工具的其他默认报告目录不属于本轮。业务代码、测试、配置、安装环境、Git暂存区及其他已有工作区修改均不改；不连接数据库、DG、Lake或源接口，不触发job/check/sensor，不改正式staging、冻结输入、receipt或日志。

**精确保留规则。** 下表路径相对`lake_console/reports`；除表列保留项外，仅删除本步冻结的605份清单内文件，不按新出现的名称自动扩张。保留的Markdown以冻结清单为准，不保留脚本`.py.txt`、请求/响应、轮询、日志/XML、旧计划/预检、逐文件stat或压缩包副本。

| 范围 | 保留内容 | 数量 |
| --- | --- | ---: |
| 20.16五个`datasets_recovery_*`目录 | 20.16已列的29份，包括TaskRun来源样本，本次不再次删减 | 29 |
| `anns_d_recovery_20261027` | README、execution-summary.json、nine-native-events-verified.json | 3 |
| `etf_mins_recovery_20261024` | README、final-verified.json、execution-summary.json | 3 |
| `index_global_recovery_20261026` | README、raw-run-verified.json、final-state-readback.json | 3 |
| `index_nineturn_recovery_20261029_20261030` | 原有两份Markdown；final.json、gold-verified.json、prod-verified.json | 5 |
| `dg_stock_period_delivery_recovery_20261028` | 原有13份Markdown；`recovery_20261029_30_execution_20261031/rss8_resume/final-verified.json` | 14 |
| `macd_kdj_daily_read_20261030` | repair目录原有两份Markdown、final-verified.json、completion-verified.json；另保留`recovery_20261029_1m/final-verified.json`。父目录其他非recovery文件不属于本轮 | 5 |
| `moneyflow_p4_continuation_recovery_20261017` | formal_recovery/49-final-acceptance.json、formal_recovery/closeout.json | 2 |
| DC根目录结果 | dc_recovery_online_acceptance_20261011.json、dc_recovery_implementation_reconciliation_20261011.json | 2 |

根目录三份DC预检/开发准备JSON及`moneyflow_p4_environment_recovery_market_sample_evidence_20261017.json`属于旧阶段过程材料，删除；当时结论已在各自原方案/LLD中保留，不据此撤回后续完成事实。

**引用修正与历史证据。** 删除前核对Markdown/HTML中的直接链接：被删附件及删除后空目录的活动链接转到所属现存README的清理说明，并明确标注附件已清理；没有README的资金流/DC单文件则转到各自原LLD的清理说明。保留文件链接不改。历史命令、裸路径和JSON内部的原始时间/路径保留为历史记录，不修改成可以重放旧任务的入口；说明这些过程文件已删除，不得据旧路径要求恢复附件或再次补数。只修改准确清单中的说明及直接引用它们的文档，不修其他历史死链或改写业务方案。文档原有未提交段落保留。

**执行顺序、中断和预算。** 先完成本节与原方案对齐、引用/依赖审计，再以临时清单中的准确路径、原大小/mtime核对删除，路径必须是reports内普通文件，遇符号链接或文件变化停止核对；不使用整个reports的递归删除。剩余非Markdown保留文件逐份SHA-256对比，不能因修链接改动原JSON/真实样本。只删除本轮导致的空子目录，保留report根和其他文件。中断后依同一清单跳过已删除项，只处理未完成项，不重建旧过程文件，不自动补数；无法恢复的未跟踪临时文件不另建副本。文本/元数据处理保守预算含正常、一次中断继续及收尾：读256MiB、写8MiB、额外空间16MiB，正式行情I/O为0。不新增报告目录、备份包或压缩归档；临时清单只在`/private/tmp`，验收后删除。

**验收和交付。** 核对539个删除目标无残留、66个保留目标均存在、非Markdown字节摘要不变，新增/其他文件未删；复查直接链接不存在指向本轮已删附件的活动引用。运行既有`scripts/check_docs_integrity.py`及本轮差异检查，确认代码、测试、正式数据和暂存区未改，不为报告清理执行业务回归或正式审计。本次未要求提交Git，故不自动暂存、提交或推送。最终数量及检查结果写回本节，不再生成一批清理报告。

**实际结果。** 已按准确清单删除539份文件、12,969,561B及9个空子目录；本轮相关文件由605份变为66份、1,293,694B（包括清理说明文字），保留的41份非Markdown结果/真实样本SHA-256全部与清理前一致。29份直接关联文档修正157处附件链接，另在原方案补入本次清理状态，共涉及30份说明/设计文档。157处新链接均指向实际存在的清理说明，未残留指向本轮已删附件的活动链接；文档完整性和本轮`git diff --check`均通过，其他已有状态与暂存区保持不变。只处理报告及引用，无代码/测试/配置改动，没有访问正式服务、读写正式数据或重新审计/补数，没有新增备份包、Git提交或推送。临时清单与辅助脚本在完成上述核对后清理，不在reports新增另一套清理附件。

**随后批准的提交范围。** 管理员随后要求提交。本次仅提交准确路径内已跟踪过程附件的删除、清理说明和必要引用修正；公告/ETF/国际指数保留的9份原未跟踪说明与最终结果一并纳入，以免新增清理链接指向未入Git的文件。两个范围外旧文档仍留工作区，相关报告的两处链接改为历史文字，不将整份旧方案或其他过程材料带入。对混有旧改动的方案/LLD只暂存本步段落及HEAD已有内容中的附件链接修正；此前补数、11月2日执行记录和未提交源码不混入。提交前校验准确白名单、暂存差异及文档链接，不推送或部署，保留其他原有工作区改动。

<a id="recovery-20261102-lld"></a>

## 21. 2026-11-02股票分钟链恢复执行LLD（2026-11-03准备）

对应[MACD/KDJ原方案第18节](dagster-stk-mins-qfq-macd-kdj-indicators-plan.md#recovery-20261102-plan)。本节定义后续操作，不表示已经执行或已获本日历史读写批准；第20节只保留10月30日事实。

### 21.1 本日已核实的事实

| 事实 | 已有证据及含义 |
| --- | --- |
| Prod补源 | 2026-11-03 00:18:07 +08只读核验`raw_tushare.stk_mins`的`ts_code/freq/trade_time`；按单日、五频和5,577个预期代码的索引范围查询，没有导出OHLC或读取历史分钟正文 |
| 股票范围 | 使用现有`load_current_listed_stock_codes_for_stk_mins`的上市日期/CNY范围；6只全天停牌为000831.SZ、002129.SZ、002717.SZ、601326.SH、688121.SH、688496.SH；Raw代码覆盖仍核5,577只，盘中时间点按5,571只有效股票核对 |
| 五频时间点 | 每只股票1/5/15/30/60m分别241/49/17/9/5个时间点，含09:30；盘中记录分别1,342,611/272,979/94,707/50,139/27,855，缺口和重复均0。15:00后至15:30另计；这不是价格或成交质量通过结论 |
| Prod全日计数 | 五频分别1,354,677/275,397/95,517/50,547/28,239，合计1,804,377；包括停牌结构行及收盘后记录，不能直接作为Silver行数 |
| 旧Raw/Silver | Raw `67ae61e1-87f0-466b-9760-17c980c0a11c`、Silver `9b35a759-c5a3-4839-9396-8dfd829e54cb`为SUCCESS，但导入的是旧的不完整来源；两层五频均需替换 |
| 旧QFQ | `16acde55-cf25-4e36-afb8-cb2d11f602a5`于11月2日22:17:14—22:17:17失败；七频均在`_validate_canonical_qfq_windows`处、年度writer调用前失败，没有本run的正式Gold替换 |
| 成交额 | `b890f7f4-55fb-4278-b7ab-88fc3cb6cdc6`在Gold步骤报`bse_close_point_missing: freq=1, invalid_code_count=38`；必须在Silver新来源完整后恢复，不能复用其失败为已发布事实 |
| 运行只读快照 | 11月3日准备阶段读取最近180条run元数据，本日上述两成功、两失败可见；范围内未发现活动run或本日两次repair/MACD/九转成功记录。它是有界快照，不证明未来无并发，正式提交前再按本日/本job核对 |

现有源检查的边界：Prod门禁证明成功任务与代码存在，Silver原检查也不检查整日所有应有时间点。因此本节明确复用已经完成的本日Prod时间点审计，并在新Raw/Silver产物做必要计数；不修改正式check语义、不把一次审计结果写成新门禁或新状态实体。

### 21.2 范围、禁止项和执行权限

仅更新本日37项及原job实际识别的必要历史repair。前一交易日是2026-10-30；日历确认2014-01-02至2026-11-02共有3,118个交易日。本轮不触发11月3日，不重跑已完成10月30日及更早日更，不重建其他股票历史state或重算无关历史指标。年度文件合并保留非本日记录；repair仅替换原产物指定股票，合并共享state时保留其他股票。

编写第21节时，授权只覆盖方案/LLD和必要只读准备；后续具体执行授权记在21.12。正式操作必须具有本日执行及21.7具体年度/历史读取范围批准；旧日期审批、一般继续指令或Prod下载完成不能替代。文档准备阶段不运行job、sensor evaluation、check执行、分区写入、runless事件，不启停sensor或重启DG。

### 21.3 当前实现位置和影响面

| 现有位置（均相对`orchestrator/src/orchestrator/`） | 本次真实职责及边界 |
| --- | --- |
| `defs/run_contracts/configs.py` | Raw的`source=prod_db`、`write_mode.replace_existing`及完整`prod_completion_reference`；Silver同名替换selector；默认与builder行为不改 |
| `defs/assets/stk_mins.py` | 两层五频替换、QFQ日更和原检查前的业务校验；Raw/Silver显式替换向原writer传`overwrite=True`；新来源不走默认复用 |
| `defs/io/minute_partition_writer.py` | Raw/Silver候选、输入/目标身份、receipt及逐文件提升；正常路径是两次候选SHA和一次正式文件SHA读回，不能误写成年度publisher的单次摘要；不新写目录旁临时文件 |
| `defs/run_contracts/stk_mins_silver_policy.py`及Silver原转换 | 保留600355.SH、300344.SZ、300391.SZ冻结规则及原过滤/重算；准备阶段仅核这3股在本日五份旧Silver中的计数，均0，本日无须解除冻结或改写旧历史 |
| `defs/asset_guards/stk_mins_prod_readiness.py`、`defs/prod_db/stk_mins_task_run.py` | 先按覆盖目标日筛任务，再取最多20候选，验证成功/全单元/全市场/五频等原条件；冻结和写前验证真实reference，不手填旧任务身份 |
| `defs/stk_mins_qfq_factor_repair.py`、`defs/ops/stock_mins_qfq_factor_repair.py` | 仅传本日，原job识别变化并产生真实scope；按年份加载四频共享Silver来源再限定股票，七频修复 |
| `defs/stk_mins_qfq_macd_kdj.py::_prepare_daily_macd_kdj_replacement_tables`及对应assets | 前一交易日state、日更读取和年度合并；沿第19节既有实现，不改公式，不重刷其他日期 |
| `defs/sensors/gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py`、对应repair op | 原decision及`_run_config_for_repair_decision`生成显式scope；op再与因子repair产物逐项核对；不得虚构`end_trade_date`参数 |
| `defs/assets/qfq_nineturn.py`、`defs/assets/wealth_market_turnover.py`及Prod发布asset | 原四频九转、成交额Gold/Prod更新；不新增外部消费者或发布方式 |

本次CodeGraph `codegraph_explore`覆盖Raw/Silver writer、两个repair op和指标repair config调用链，随后补看真实SQL、配置、原job selection及冻结规则。CodeGraph关于测试覆盖的推断不作为无测试结论；既有替换回归见`tests/test_stk_mins_replace_existing.py`。无架构或共享contract修改，不涉及Prod同步执行器、API/前端修改。正式加载版本和当前业务状态属于执行前运行核验，文档与代码存在不能代替它们。

### 21.4 执行前准备与原生提交

1. 工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，现有`.venv/bin/python3 -B`，正式`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`。提交使用现有本机`http://127.0.0.1:3000/graphql`原生`launchRun`，selector为`orchestrator/__repository__/<下表原job>`；不是Dagster Plus CLI，不运行可能同步安装依赖的命令。
2. 只读核对code location公开的Raw/Silver配置确有`replace_existing`，当前源码和正式运行加载版本一致，原job/资产/check集合存在。若不一致，停止汇报，不能在本轮文档任务中自行部署、重启或临时改代码。
3. 核对本日Raw分区`cn_a_stock_mins_trade_days`、Silver及下游分区`cn_a_stock_mins_silver_trade_days`，以及股票日线/因子/生命周期/停牌/身份参考的本日就绪事实。只核精确目标和前交易日，不全历史逐分区审计。通常已有分区无需写入；若本日某键确实缺失，只有获准正式操作后补该缺失键并读回，不新建九转分区集合。
4. 保存八条sensor原selector/id、开关、cursor、lastRunKey：`stock_mins_raw_sensor`、`stock_mins_silver_sensor`、`stock_mins_qfq_daily_sensor`、`stock_mins_qfq_factor_repair_sensor`、`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`、`gold_stk_mins_qfq_macd_kdj_repair_job_sensor`、`gold_stk_mins_qfq_nineturn_update_job_sensor`、`gold_wealth_market_turnover_update_job_sensor`。获准后只暂停其中原来RUNNING者，不动登记分区的sensor、其他数据集或daemon。
5. 停sensor不会停止已有run。按目标日/原job和共用年度文件writer核对活动、queued及新成功run；有冲突先等待核实，不杀任务、不抢锁。Nov2准备快照不代替本步。
6. 挂载、正式根/staging存在、同设备、可用空间和原锁无冲突后，冻结本次小型执行记录。正式Lake仅`/Volumes/datasource/data_lake/raw|silver|gold`，候选/冻结/receipt仅`/Volumes/datasource/data_lake_staging`。不备份、不调用Kopia、不用旧Lake或改路径配置。
7. 提交调用只保存本次意图、日期、配置、响应和精确run ID，不承载行情计算。已有触发方式可用时直接复用；如需整理薄调用文件，须先按本节固定配置核对，不能扩展为手工补数脚本。请求只发一次，响应不明时按已保存意图和原生run事实查找，禁止盲重发。

### 21.5 job顺序、配置与阶段验收

每个步骤等待SUCCESS及原检查绑定本次物化后再进入下一步；SUCCESS而检查/receipt缺失不能当作通过。不按“最新run”或仅资产历史绿灯代替精确本次事实。

| 步骤 | job及必须传入的配置 | 必须验收 |
| --- | --- | --- |
| A | `stock_mins_raw_update_from_prod_job`，partition=2026-11-02。使用原`build_stock_mins_raw_update_job_run_config(source='prod_db', prod_completion_reference=reference)`，仅将五个`raw_stk_mins_{1,5,15,30,60}m`配置的`write_mode`改为`{'replace_existing': {}}` | 五物化、15原check；来源仍为Prod九字段，五份候选/正式receipt完整，逐频与21.1源行数对应 |
| B | `stock_mins_silver_update_job`，partition同日。`ops`仅五个`silver_stk_mins_{1,5,15,30,60}m`，各`config={'write_mode': {'replace_existing': {}}}` | 五物化、20原check；原过滤/重算/冻结统计及receipt成立，不能简单让Silver行数等于Raw |
| C | `gold_wealth_market_turnover_update_job`，partition同日，空config | Gold和Prod两物化、原Gold检查及发布结果通过；原先BSE收盘缺口消失，不再另跑Prod发布job |
| D | `stock_mins_qfq_daily_update_job`，partition同日，空config，新独立run | 七物化及28原check、publication完成；不能FROM_FAILURE旧`16acde55`，因为来源已经变化 |
| E | `stock_mins_qfq_factor_repair_job`，非分区op job：`ops.stock_mins_qfq_factor_repair_op.config={'trade_date':'2026-11-02'}` | 七条原completion/原factor guard通过；真实名单、起止、codes hash、batch和producer身份完整；不传手工股票列表 |
| F | `gold_stk_mins_qfq_macd_kdj_daily_update_job`，partition同日，空config | 14物化、28原check，七频当日state和精确前交易日state关系成立；因子repair必须先通过 |
| G | 先用`build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision`，按`_run_config_for_repair_decision`产出配置后提交`gold_stk_mins_qfq_macd_kdj_repair_job` | 只承接E产物和F事实，配置字段见21.6；有repair则14条completion及完整repair guard通过；无repair须有原decision依据，不传空名单强跑 |
| H | `gold_stk_mins_qfq_nineturn_update_job`，partition同日，空config | 因子repair和指标repair均满足门槛后，四物化/四原check及receipt通过 |

**reference。** A之前使用原Prod门禁选择覆盖11月2日的合法全市场成功任务，继续保留原全部成功、完成单元、五频、代码覆盖条件，生成新的`ProdStkMinsCompletionReference`并保存其原字段。不能将管理员下载完成口述、00:18计数或旧Raw的reference当作新reference；代码不会因此自动验证整日分钟时间点，21.1有界证据须独立保留。准备/审计的临时SQL访问仍走仓库指定`psql-remote.sh`，不另写数据库连接；正式job仍使用其已存在的Prod resource。

**Raw/Silver额外计数只做一次。** A、B各自产物完成后，分别对当天五份新文件做一次按股票/频率的预期时间点聚合，与21.1的同一口径核对，仅读代码/频率/时间字段、返回计数和必要缺口样本，不读行情值、不扫描其他日期。它补充原检查未覆盖的盘中完整性，不能省略为“代码都在”。同一阶段已有原产物明确给出等价计数时复用，不重复查。发生来源、身份或处理统计变化先查明，不把不一致静默归零。B按原全天停牌过滤核对5,571只；冻结规则三股本日无行，不要求解除规则。

**D的预计计数。** 当前股票范围和处理规则不变时，每频5,571只，七频目标日K线分别1,342,611/267,408/89,136/44,568/22,284/16,713/11,142；总1,793,862条，至多38,997个受影响股票/频率年度目标。它们用于对照原metadata/窗口检查，不作为强行删行或修值的指令。原目标年度含其他日期/股票时仍按原writer保留。

### 21.6 repair产物交接与不重刷边界

11月3日00:25准备阶段复用`build_adj_factor_changed_codes_sql`比较10月30日、11月2日两个小型因子文件和原生命周期范围，结果仅`factor_changed=3`，其他原因0。预算识别为001393.SZ、301536.SZ、688548.SH；这些代码只用于56份历史QFQ/56份指标文件stat，不进入正式手填参数。E仍在执行时重新产生原产物；若实际变化原因、名单规模或日期超出本节预算依据，停下重新核定，不能人工删成3只继续。

E覆盖原日历起点2014-01-02至2026-11-02的3,118日、七频，只重写原产物指定股票。共享Silver来源是四频全市场日文件；不能擅自减少源频率、缩短范围、另建stock-only中间数据或绕过原diagnostics。

G配置来自原decision：`qfq_factor_repair_trade_date`、`start_trade_date`、固定全七频`freqs`、`stock_codes`、`reason`、`repair_required_codes_hash`、`upstream_batch_id`。end由原op从E产物派生，不添加不存在的参数。原op再次逐项核对scope，不跳过；不把“日更成功”当成历史repair完成。F先生成本日七份state，G随后才有完整3,118日×7频=21,826份共享state目标；写入时只替换受影响股票并保留其他股票。E明确无需repair时，F仍正常日更，G只复用原无须repair决策，H仍检查对应依赖。

本次源修复不构成全市场历史重刷授权。年度合并保留其他日期，原本因复权变化需要的3只预估股票历史repair属于E/G，不能扩大到其他股票或10月已完成批次。2013年准备stat无这3股QFQ文件，未读其正文；若原入口实际需要超出批准年份的文件，先停止核清。

### 21.7 必要读取来源及测量依据

准备只读统计时间为2026-11-03 00:25:55 +08。年度数据只列路径并stat，没有打开其Parquet正文或计算SHA；小型日期/因子依据只用于预算，不形成正式repair完成事实。

| stat范围 | 文件数 | GiB |
| --- | ---: | ---: |
| 2025七频QFQ | 38,241 | 8.814355 |
| 2026七频QFQ | 39,165 | 7.796705 |
| 2026七频指标 | 39,165 | 17.809291 |
| 3只预算股票2014—2026 QFQ | 56 | 0.012333 |
| 3只预算股票2014—2026指标 | 56 | 0.024793 |
| 3,118日四频Silver（1/5/30/60m） | 12,472 | 44.240539 |
| 同期Silver因子 | 3,118 | 0.105777 |
| 已存在的历史七频共享state（截至10月30日） | 21,819 | 3.585124 |
| 10月30日七份前日state | 7 | 0.001635 |

当时Lake可用约2,697.21GiB。F之后共享state应增加7份为21,826；旧Nov2 Silver替换后的总字节小幅变化应通过本日新文件stat记入，不重新枚举所有历史文件测量。上表只是文件大小，不等于每个SQL的实际设备读取量。

后续拟批准范围逐项如下：

- A：Prod `raw_tushare.stk_mins`，11月2日五频、原5,577代码范围、九字段`ts_code/freq/trade_time/open/high/low/close/vol/amount`，沿原09:00—19:00日内边界；不发Tushare请求。原TaskRun窄门禁只读其现行白名单身份/状态/进度/日期与过滤字段，不扩展Ops其他表。
- B/C：本日五频Raw/Silver，原小型Basic/identity/lifecycle/停牌/日线等必要参考。C的唯一Prod写入表为`core_serving.wealth_market_turnover_snapshot`，仅`type='stock'、market='CN_A'、trade_date='2026-11-02'`五频5行，使用现有`ProdPostgresWriteResource`和原事务内删除该日范围、插入、读回比对的发布方法；异常沿原事务回滚，不改其他日期/市场或Prod行情表。正式执行批准必须覆盖这次单日发布，不能拿只读审计授权执行。
- D：本日Silver及因子，合并受影响2026七频QFQ年度文件；不读取2025 QFQ来做当日前复权，不重算其他日期。
- E：原产物指定股票、2014-01-02至2026-11-02七频QFQ历史；来源按原实现读取同期四频全市场Silver和每日因子。四频来源加载约44.24GiB，不能按3股比例折扣；其余年份/股票不写。
- F：当前实现需要的2026七频QFQ及必要2025来源、10月30日精确state，合并2026指标年度及本日state；保留第19节最近至多8根历史K线加前日递推state的原算法和原检查。只取8根不是取消MACD/KDJ历史迭代。
- G：E实际名单的2014—2026七频QFQ和指标，3,118日七频共享state及原确需的前序state依据；只改名单内股票，其余股票state仍按原合并保留。没有历史指标全市场重算。
- H：2025/2026四频QFQ、10月30日九转seed和原有界查询选中的更早实际候选，早年正文限2014—2026且合计不超过1GiB、先stat；预算不授权随意扩大早年扫描或人工重建前日seed。

### 21.8 正常、失败恢复和最后收尾预算

与方案18.4一致，包含当前job原checks、原完整候选校验、现行摘要读写、原引擎临时读写及精确run/receipt/stat收尾。QFQ/指标年度publisher只做现行单次摘要，不恢复旧三遍年度摘要。Raw/Silver的`MinutePartitionPublication.run`目前在生成后及提升前各读一次候选SHA，替换后再读一次正式文件SHA；这三次小型日文件读取都计入A/B/C的4GiB预算，不宣称本轮已优化为一遍，也不新增第四遍。本轮不改该提交器、不做独立全年度审计。

| 阶段 | 正常读GiB | 正常写GiB | 阶段额外空间GiB | 估算依据 |
| --- | ---: | ---: | ---: | --- |
| A/B/C | 4 | 1 | 2 | Prod本日1,804,377行、10个当日文件、原转换/检查/时间点计数及单日发布；含小型参考和临时留量 |
| D | 40 | 10 | 16 | 旧年度约7.80GiB、候选估≤9.25GiB，沿原旧年度合并、候选校验与单次摘要模型；另含本日输入冻结和原28检查 |
| E | 50 | 2 | 4 | 共享来源44.24GiB、历史因子0.106GiB，受影响年度/冻结/摘要及完成检查；文件较小不抵扣共享来源 |
| F | 248 | 36 | 48 | 沿19.7的现行读取模型；条件与计算见下文 |
| G | 24 | 12 | 16 | 3股QFQ约0.0124GiB、指标约0.0248GiB、共享state约3.59GiB，包含state保留/合并、原校验/摘要/completion和引擎留量 |
| H | 28 | 4 | 8 | 四频两年必要来源、seed与≤1GiB早年实际候选、原检查及临时留量 |

合计正常读394GiB、写65GiB，拟申请**读400GiB、写70GiB、额外空间128GiB**。阶段串行，空间按候选、冻结、临时与保留失败现场预留，不等于把空间改成运行配额；不改现有16GB内存、线程、spill、并发、超时、限流或SQL设置。准备时没有性能样本；历史耗时只说明可能为分钟至数十分钟级，不承诺固定完成时间，repair涉及大量小文件可能更久。

F继续采用19.7：`R=6Qy+4Qp+L+2I+4C+P+V+Fr+Tr`、`W=C+P+Fw+Tw`。本次估算条件为`Qy≤8.5GiB、Qp≤9.25GiB、L≤9.25GiB、I≤20GiB、C≤22GiB、P≤0.125GiB、V≤0.002GiB`，`Fr/Fw`各1GiB、`Tr/Tw`各8GiB留量；保守代入读约234.38GiB、写约31.13GiB，在248/36预算内。原检查中的年度来源查询仍包含在预算，没有把它们删成“一遍”，也不另加一次checks-only全频复审。候选SHA沿已实现单次摘要，不恢复过去三次完整摘要做法。

**中断后的成本。** 正常各job只运行一次，失败停止。全部范围最坏再执行一次的额外参考为读400GiB、写70GiB；与首轮合计最坏800/140GiB，失败现场和新候选共存空间参考上界256GiB。该数字没有授权重跑。实际恢复必须先按原receipt/completion和目标身份扣除可复用部分；已经完成的job不重算，其余只在核定原入口、剩余历史范围、开销及授权后继续。若实测来源/名单/候选规模明显超出依据，先记录并报告，不能以新加内存或时间限制强行截断任务。

**最后收尾。** 默认只复用本次37项物化、原检查、repair completion、目标receipt与必要stat，不额外跑一次37项物理全文计数，更不跑180项目录审计。A/B的本日必要时间点计数已计在4GiB阶段预算。若某项完成证据不足，只针对该项补最小计数，先列增量开销，不把收尾变成额外全市场年度读取。

### 21.9 新run身份、失败及继续方式

- 本次A、B、D使用新独立root run；来源已变，不能沿旧Raw/Silver成功run或`16acde55`的root接旧候选。新root并不授权删除旧日志或现场。
- 同一次新Raw/Silver执行中断时，依原`MinutePartitionPublication`校验输入/源码/范围/目标和receipt。只有原实现能认定的validated/promoting/promoted事实才可继续；Prod补源再次变化时不能复用旧候选声称已导入新源。
- D和F、E分别按现行publication/root及真实输入绑定处理，已经提升文件保持现状，不回滚、不备份、不修改记录绕过冲突。
- G的op当前调用共用writer时没有传整个run的`publication_id`，不能承诺原生FROM_FAILURE会按该run自动复用每频文件receipt。若G中断，必须先逐频核对原内部publication与completion、state已合并范围及剩余成本，再明确原入口能否安全完成；不能在方案中虚构通用自动续跑能力，也不能擅自开发新入口。正常一次执行不受此恢复边界影响。
- C/H同样只按其原writer可证明的状态处理，不将新root、SUCCESS或候选存在作为完整提交依据。任一失败后不继续后续job，不自动清理尚承担恢复用途的staging，不把失败run改绿。

### 21.10 验收、开关恢复及清理

预期原检查总117项：A15、B20、C1、D28、E7、F28、G14、H4；无repair时记录原决策和实际完成项，不空跑G来凑数。每次检查须绑定对应本次物化/repair产物，repair写后的最终文件身份采用最终receipt，不能用日更时的旧stat证明历史repair后的文件。

完成判据为37项本日结果及必需repair全部满足原门槛、无同范围活动/重复run、运行记录与物理提交回执一致。之后恢复21.4中本次暂停的sensor到原状态，cursor/lastRunKey原样保留，并做一次只读状态回查，不触发evaluation。若失败，明确记录已完成/未完成、剩余原sensor状态及对后续日期的影响，向管理员汇报后停止；不能一边保留失败又恢复会越过依赖的自动链。

清理只删除本次调用/查询产生且不再使用的临时文件；保留正式数据、原日志、候选/冻结输入/receipt中仍用于继续执行的内容，不整目录删除staging。文档准备的临时预算/前后版本文件在本次复审完成后删除，必要计数与stat摘要已写入本节，不另建大量恢复报告附件。

### 21.11 文档对账与待执行事项

本节文档准备阶段不新增代码、不改配置、不触发job、不启停sensor、不安装依赖；当时没有正式补数或隔离测试结果可宣称。方案18.1—18.5与本节事实、范围、八步顺序、两次repair来源、400/70/128预算、恢复边界和收尾要求一一对应。

正式执行前仍须取得本日具体批准，并在21.4按实际运行状态完成一次有界准备；真实reference、精确新run ID、原job产生的repair名单/hash/batch和最终receipt都是执行时产物，不在准备阶段捏造。3股只是预算预估，不要求管理员手工提供名单。未发现本轮正常执行所必需的新开发；如运行核验发现版本、来源或原入口不满足本节，不先写临时补丁，停下说明具体差异。

**2026-11-03独立复审记录。** 初稿完成后重新按当前schema/parse、实际writer及job selection对照复审，纠正了日更准备函数的实际模块位置，以及Raw/Silver小文件提交器和年度publisher的摘要次数差异；补明成交额唯一Prod目标表、5行单日事务及写入授权边界。方案和LLD现已按同一口径表述，没有把这些既有行为误写成本轮新增开发。逐条核对37项范围、八步先后、两次repair交接、原117检查、3,118日/21,826份state、394/65分项与400/70/128预留、失败停止及原状态恢复，未发现本轮正常执行方案的阻断矛盾。仓库文档完整性、两份文档相互链接/显式锚点、相关代码路径、预算和计数算术核验及定向差异格式检查均通过；原文与本轮前已有修改完整保留。此结论只验收文档准备，正式加载版本、reference及job结果仍按21.4—21.5执行时核验，不宣称正式补数已验收。


### 21.12 11月3日执行授权、命令和阶段记录

**授权依据。** 管理员在收到本节对应方案和明确预算后要求“按照方案，开始推进补数吧，完成后向我汇报进展”。本次以此执行21.2、21.5、21.7—21.8已明示的11月2日范围、必要年度/历史读取及400/70/128GiB预算，不沿用旧日期批准，不自动重跑。21.1、21.11及文首“准备时”状态保留当时事实；只有本节后续实际结果才代表正式进度。

**原生调用命令。** 工作目录、解释器、DAGSTER_HOME及GraphQL地址仍按21.4。调用文件为`/private/tmp/dg_20261102_execute_20261103/control.py`，只封装原生查询/提交，原resource门禁、原config builder和原job执行实际业务，不含行情计算或数据文件写入代码。用现有`.venv/bin/python3 -B /private/tmp/dg_20261102_execute_20261103/control.py <动作> [阶段]`执行：

| 动作 | 读写与条件 |
| --- | --- |
| `preflight` | 只读加载中的Raw/Silver配置schema、八sensor原状态/cursor/lastRunKey、活动run、十个目标stat及空间，不执行check或eval |
| `pause` | 按已保存selector/id原生stop八条原RUNNING sensor，读回STOPPED、保存停后cursor/lastRunKey；不重置、不操作其他sensor |
| `reference` | 原Prod完成门禁及5,577代码覆盖，生成真实reference和A/B/E原job配置，其余空config；不查询OHLC |
| `launch A`至`launch H` | 每次只提交21.5对应原job一次；G配置须在E/F完成后由原decision生成，当前不得提前手填；无G需求按原decision跳过 |
| `inspect A`至`inspect H` | 按已保存精确run ID、增量event cursor读取状态/物化/原check/异常，不扫描其他资产或行情历史 |
| `restore` | 全部验收后确认无活动冲突，核停后cursor/lastRunKey，原生start恢复本次原RUNNING者；不触发evaluation |

调用文件已在不访问正式资源的情况下做语法核对；这不是业务测试或性能样本。不对job加运行超时、内存或并发限制。GraphQL客户端只设置连接响应等待，响应不明保存原意图并查精确run，不盲重发。

开始时DG原生只读查询确认无STARTED/STARTING/QUEUED/CANCELING run，八sensor全部RUNNING；预检与后续实际run结果依次追加。正式候选、冻结输入和receipt仍由原writer只写正式staging；本调用目录只保存控制请求和元数据，完成后清理。


**A/B/C已完成，D执行中。** Raw新run `8614e7ff-fe31-4c30-b62f-ae4be99223f8` SUCCESS，82.700秒、5物化/15检查；Silver新run `8075253a-a59b-4d84-90cf-703e056fde74` SUCCESS，14.514秒、5物化/20检查。两层各自一次本日代码/时间点计数完成，均无缺口/重复，与21.1来源及原停牌过滤口径相符。成交额新run `5d22f6bd-0f03-4b7b-aa1d-259e07c9653b` SUCCESS，1.501秒、2物化/1检查，Prod当天stock/CN_A五频5行读回通过。QFQ新run `6d9d48a8-d029-4538-8c26-8d72fdaea49b`已启动，此时尚未验收完成，不先触发E。

**操作读回处理。** 初次stop八条均返回STOPPED，但立即读回时指标repair sensor仍为RUNNING；只读确认其近期tick均SKIPPED、无活动run，再单独原生stop该条并读回八条全STOPPED，未重置cursor。辅助检查最初误要求普通check的`partition`非NULL；真实Dagster事件中该字段合法为NULL，而`targetMaterialization`明确绑定本次run及物化storage ID。依据真实合同改为核对绑定的物化日期和run，未改正式checks、未重跑A；两层计数只在此核对通过后各执行一次。

**E/G原状态读取和配置来源补充。** 因子与指标repair验收复用现有`gold_stk_mins_qfq_factor_repair_status`和`gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status`。读取已有DG事件库时只实例化现有`PostgresEventLogStorage`读取对象，使用正式dagster.yaml中的既有连接、显式`should_autocreate_tables=False`，不创建DagsterInstance、不建表/升级、不修改配置文件；只查询本日七/十四个原check键及必要event ID。原读取对象接给上述现成函数，不合成通过状态或另一份名单。G配置只由原`build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision`及`_run_config_for_repair_decision`生成，原G op再做完整产物核验。此补充只是21.5既定门槛的只读调用方式，不增加数据范围或新计算入口。


**D完成、E启动。** QFQ run `6d9d48a8-d029-4538-8c26-8d72fdaea49b` SUCCESS，耗时1,040.777秒，七物化/28原检查及其本次物化绑定均通过。本日七频1,793,862条、每频5,571年度目标，合计38,997份完成；未读取额外年度正文做收尾。随后原因子repair run `65aaf3ed-4f77-46c2-a433-80930e7e0b71`启动，只传11月2日，实际名单和完成范围等待其原产物。


**E已完成，F启动。** 因子repair run `65aaf3ed-4f77-46c2-a433-80930e7e0b71` SUCCESS，32.820秒、七completion通过。原状态函数读回ready，producer为本run；实际名单001393.SZ、301536.SZ、688548.SH，范围2014-01-02至2026-11-02、3,118日，与预算一致。原生年度改写40份/481,840条，派生改写16份/7,600条；批次`qfq_factor_repair:2026-11-02:c11563f5bbd0`，代码hash `c83f443401391c396ef57acf0864c59f42e5ab7d8cd1182093379e226bf0b2ad`，七条completion event ID为7846222—7846228。F仅在此原门槛通过后启动，尚未提前运行G或H。


**G配置准备复用已核实证据。** E原状态函数已完整核对七条check、producer、event ID、名单/hash/batch；F自身仍执行其原写前门槛。八条sensor暂停、无其他E执行的本轮内，G配置准备直接从保存的E原`to_payload()`还原同一现有状态类型并逐字段回读相等，调用原decision/config函数；不重复一次相同E状态查询，不合成ready或名单。G op仍按真实事件库重新核验其原上游；G完成后的完整repair guard另正常读取一次，未降低正式门槛。若本轮出现新的E/来源身份变化，则此复用不成立，先停止核实。


**F完成、G启动。** MACD/KDJ日更run `52e5b57c-4174-422f-a49e-62b5a974c5a4` SUCCESS，742.138秒，14物化/28原检查及对应本次物化绑定通过。本日指标七频合计1,793,862条，每频5,571份指标年度目标；每频state为5,595行，沿原无当日行情股票状态保留规则，不把指标当日5,571代码数硬套state。G配置由原decision/config函数根据E原产物和F成功事实生成，未人工编辑名单/hash/batch。原指标repair run `078154e8-151d-40f6-8982-c5418763f937`已提交；此时H尚未启动，继续等待G的14条completion和原完整repair guard。


**H早年读取范围的执行前核定。** G完成后，H启动前复用`qfq_nineturn.py::_minute_nineturn_source_paths`和`_bounded_candidate_codes`，仅对2025/2026四频来源及10月30日seed做原有界代码/日期计数，取得与原planner相同的候选股票；不调用会先读早年正文的完整planner。随后仅列举这些实际候选的历史路径并stat，确认年份2014—2026且早于2025的文件合计≤1GiB；此时不读取早年正文。结果写入本次临时控制记录并汇总至此处。H原job随后仍自行使用原planner，不向job手填fallback股票或另传过滤参数；本次候选范围核定属于21.7—21.8已有H预算，不扩大范围、不增加运行限制。若候选路径或范围不符，先停止，不启动越界读取。


**G完成、完整门槛ready、H启动。** G run `078154e8-151d-40f6-8982-c5418763f937` SUCCESS，283.209秒、14completion通过；实际3股、3,118日、指标年度56份和共享state21,826份。原完整repair guard随后读回ready，因子与指标修复的名单/hash/batch/2014-01-02至2026-11-02范围及七频完全一致；指标completion event ID为7846487—7846500，不再做全历史内容比对。

H前置原候选计数四频均选择002827.SZ、605258.SH；每频18个历史候选文件，早于2025的文件共56份/2,212,164B（约2.11MiB），已只stat确认年份和≤1GiB，未提前读取这些早年正文。与因子repair的3股是不同用途，不能互相当作修复名单。随后H原job run `a2a564f4-88b9-499d-9772-df9ad1275137`启动，原planner自行决定fallback并仅输出本日九转，未手填这两股参数。


<a id="recovery-20261102-complete"></a>

### 21.13 11月2日分钟链正式完成及收尾（2026-11-03）

**最终结果：本轮37项本日物化齐备，八个原job均SUCCESS，117项原检查/repair completion全部通过，两次repair完整门槛ready。** 下表时间均为11月3日北京时间；耗时是每个run自身执行时间，不能当成端到端墙钟耗时。

| 步骤 | 原job | 精确run ID | 北京时间 | 耗时秒 | 物化 / 通过检查 |
| --- | --- | --- | --- | ---: | ---: |
| A | `stock_mins_raw_update_from_prod_job` | `8614e7ff-fe31-4c30-b62f-ae4be99223f8` | 01:21:44—01:23:07 | 82.700 | 5 / 15 |
| B | `stock_mins_silver_update_job` | `8075253a-a59b-4d84-90cf-703e056fde74` | 01:25:29—01:25:44 | 14.514 | 5 / 20 |
| C | `gold_wealth_market_turnover_update_job` | `5d22f6bd-0f03-4b7b-aa1d-259e07c9653b` | 01:27:27—01:27:28 | 1.501 | 2 / 1 |
| D | `stock_mins_qfq_daily_update_job` | `6d9d48a8-d029-4538-8c26-8d72fdaea49b` | 01:28:03—01:45:23 | 1040.777 | 7 / 28 |
| E | `stock_mins_qfq_factor_repair_job` | `65aaf3ed-4f77-46c2-a433-80930e7e0b71` | 01:46:01—01:46:34 | 32.820 | 0 / 7 |
| F | `gold_stk_mins_qfq_macd_kdj_daily_update_job` | `52e5b57c-4174-422f-a49e-62b5a974c5a4` | 01:49:20—02:01:42 | 742.138 | 14 / 28 |
| G | `gold_stk_mins_qfq_macd_kdj_repair_job` | `078154e8-151d-40f6-8982-c5418763f937` | 02:03:11—02:07:55 | 283.209 | 0 / 14 |
| H | `gold_stk_mins_qfq_nineturn_update_job` | `a2a564f4-88b9-499d-9772-df9ad1275137` | 02:11:23—02:12:32 | 69.137 | 4 / 4 |

**本日数据。** Raw/Silver五频显式替换完成，新Raw分别1,354,677/275,397/95,517/50,547/28,239行，五频均5,577代码；扣除6只全天停牌后，Silver分别1,342,611/272,979/94,707/50,139/27,855行，均5,571代码。两层各做了一次本日必要时间点计数，没有缺口或重复。前复权及MACD指标七频各1,793,862条；九转30/60/90/120m分别44,568/22,284/16,713/11,142条，四项原检查绑定本次物化通过。成交额Gold和Prod同日五频5行已发布且原读回一致。没有把Raw含停牌/盘后记录的行数硬套Silver，也没有把当天指标代码数硬套应保留状态的state。

**必要历史repair。** 只对原job识别的001393.SZ、301536.SZ、688548.SH执行两次原repair，覆盖2014-01-02至2026-11-02的3,118日、七频。因子repair改写40份原生及16份派生年度文件；指标repair完成56份指标年度文件及21,826份共享state文件合并，保留其他股票。原完整guard确认producer、名单/hash、batch、日期和频率一致；不是全市场历史重刷。九转另有原候选002827.SZ/605258.SH的早年读取，56份约2.11MiB的stat范围已在21.12记录；没有手改fallback名单或重写前日seed。

**最后验收和开关。** 只汇总八个精确run、37个不同资产物化、117项原检查、原repair门槛、回执/既有日志，并对本日Raw/Silver、state、九转及成交额共22份文件做stat，均存在且非空。未追加年度正文/SHA、全历史公式比对、checks-only重跑或180项目录审计。最终八条本轮暂停sensor均按原状态恢复RUNNING，原cursor/lastRunKey在启用时保留；随后一次有界只读回查无本链活动或恢复后重复run，不运行evaluation。

**执行边界。** 全部业务计算和写入均由上述原job完成，调用文件只负责配置、提交和读取结果；未修改业务代码/公式/schema、默认配置、内存/线程/spill/并发/超时/限流，没有性能测试、自动重跑或补runless通过事件。本日各阶段正常执行一次。400GiB读/70GiB写/128GiB额外空间为批准预算，未采集设备I/O实测，不能把预算写成实际设备读写量。旧失败run `16acde55`及成交额旧失败run保留为历史，不改状态；本次完成以新run和原检查为准。

**清理已完成。** 本次临时控制目录中的79个调用/查询/元数据文件（1,125,881B，约1.07MiB）及空目录已删除；必要计数、run、修复范围及开关结论已写入本文。正式Lake结果、Dagster原日志和正式staging/冻结输入/receipt保留，没有另建恢复报告目录。
