# 股票分钟前复权与MACD/KDJ写入修正方案和LLD

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

从`lake_console/orchestrator`使用现有`.venv/bin/python -B -m pytest -q --tb=short`执行以下15个文件，最终**263 passed、70 subtests passed，21.97秒**。[完整日志](../../reports/datasets_recovery_20261022_20261024/qfq-staging-code-tests.log)：

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

2026-10-24 15:41:41（北京时间），按§6.1执行[有界核验脚本](../../reports/datasets_recovery_20261022_20261024/qfq-staging-real-sample.py.txt)。[结果](../../reports/datasets_recovery_20261022_20261024/qfq-staging-real-sample-verified.json)、[日志](../../reports/datasets_recovery_20261022_20261024/qfq-staging-real-sample.log)：

- `600000.SH`、60分钟，20日4行QFQ、21日4行QFQ、20日1行state作为输入；独立比对正式21日4行指标和1行state，共14行有界事实。
- 真实源schema与当前合同一致；改后QFQ保留20日并合入21日，记录完全一致；MACD/KDJ和state与已有正式21日结果的最大绝对差均为0。
- 相同身份再次执行，隔离输出inode/mtime不变。4个正式来源文件合计577,907字节，stat前后未变化；计算及写出0.140秒，隔离输出小于16MiB。
- 所有输出只在`/private/tmp/dg_qfq_staging_real_sample_sq68mnk8`，没有正式Lake、Prod或Dagster写入，也没有数据库/instance连接。这是边界验收，不代表22日全市场已经补齐。

### 8.4 补齐预检及当前停点

随后按既定批次1做必要预检，[报告](../../reports/datasets_recovery_20261022_20261024/index-daily-raw-preflight.json)：目标4个文件及同日物化均缺失，分区已注册、相关job无活动run、daemon未运行、staging同设备且扩展已安装。但Prod `core_serving.index_daily_serving`在22日、DG登记820代码范围内为0行，820个代码都缺失，Raw不能通过当前完整性门禁。

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

可复核证据：[汇总](../../reports/datasets_recovery_20261022_20261024/qfq_read_optimization_20261025/validation-summary.json)、[综合测试](../../reports/datasets_recovery_20261022_20261024/qfq_read_optimization_20261025/regression-final.txt)、[受保护门禁](../../reports/datasets_recovery_20261022_20261024/qfq_read_optimization_20261025/static-gates.txt)。三份新增测试为`test_stk_mins_qfq_read_optimization.py`、`test_stk_mins_qfq_check_read_reuse.py`、`test_stk_mins_qfq_publication_single_digest.py`；既有staging测试只同步返回行数的spy和隔离路径/子进程临时目录。

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

结果为0/7频率完成、0/28检查执行、0年度SHA/提升。运行0.839秒仅代表失败前阶段；读按全文件计费并加Fr预留为33.042MiB，写约1.354MiB，均未超额度。源12文件5字段stat不变、无正式写入或instance/job/event；连接退出后整个独占临时父目录已删除，并由主流程再次确认不存在且无运行进程。小型结果见[测量说明](../../reports/datasets_recovery_20261022_20261024/qfq_real_performance_20261025/README.md)和[result.json](../../reports/datasets_recovery_20261022_20261024/qfq_real_performance_20261025/result.json)。

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

12.2规定的纯对象回归已完成17项并清除其临时目录，复现旧异常，验证9类真实MetadataValue、真实AssetCheckResult成功/失败、JSON写出读回及排他创建。未读取正式数据或创建instance，不算七频性能通过。结果详见[a2说明](../../reports/datasets_recovery_20261022_20261024/qfq_real_performance_20261025/retry-summary.md)、[a2原始结果](../../reports/datasets_recovery_20261022_20261024/qfq_real_performance_20261025/result-retry.json)与[纯对象回归](../../reports/datasets_recovery_20261022_20261024/qfq_real_performance_20261025/reporter-offline-validation.json)。

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

- [ ] **TODO：等2026-10-23的数据补齐完成后，再启用`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`和`gold_stk_mins_qfq_nineturn_update_job_sensor`。** 后续补数执行者在确认23日补齐结果后处理并记录启用时间及状态读回；本轮22日七频QFQ完成不满足启用条件，不能提前恢复RUNNING。

本轮先停止两个现有状态并读回，刷新无并发run/daemon、五输入stat和空间，再执行13.1原命令一次。沿用已完成年度stat，不再次列举年度文件，不再测试。状态修改及预启动结果写`qfq_recovery_20261025/sensor-stop-and-launch-preflight.json`，业务结果仍由原28项检查及publication记录验收。

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

原剩余21项不因这七条前置检查再扣七。两个下游sensor仍STOPPED，无活动run/daemon，等23日补齐后再启用的TODO不变。本轮未启动MACD、九转、板块或自动重跑。Git提交由后续提交阶段单独记录。详见[执行汇总](../../reports/datasets_recovery_20261022_20261024/factor_repair_20261022/summary.json)、[实际run与逐文件验收](../../reports/datasets_recovery_20261022_20261024/factor_repair_20261022/run-verified.json)和[消费者/控制状态](../../reports/datasets_recovery_20261022_20261024/factor_repair_20261022/final-control-status.json)。


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

2026-10-29已按本节顺序完成2026-10-28股票分钟链。MACD/KDJ历史repair run `44caf58c-a1d9-4e37-b525-b82cda3179b3` SUCCESS，耗时300.672秒；14条原完成检查全部通过，completion和完整factor/MACD检查均ready，事件、起止日期、16股名单/hash及上游批次一致。实际发布723份指标年度文件，重算6,906,176行；合并21,805份共享state后共85,262,709行，包含保留的其他股票，不表示重新计算全市场。原operation/receipt与正式文件stat通过。证据：[指标repair验收](../../reports/datasets_recovery_20261028_20261029/batch10/repair-run-verified.json)。

随后先核27日九转原产物，再对本次实际变化16股的30/60/90/120分钟末根seed进行必要核验，64组全部匹配、差异0；有界查询所得候选历史52份、2,230,410B。候选及seed按路径去重合468份、17,922,588B，包含2025/2026年，按这一合计核对未超已批准的1GiB范围。原九转job run `a9f7bedc-5041-48ab-8171-20c388bff5ea` SUCCESS，耗时68.201秒；4物化、4条原检查及真实绑定通过，28日四文件共94,690行、241,902B，receipt/stat及输入身份验收通过。没有重跑27日九转。证据：[seed及候选范围](../../reports/datasets_recovery_20261028_20261029/batch11/candidate-scope.json)、[九转验收](../../reports/datasets_recovery_20261028_20261029/batch11/final-verified.json)。

本轮5个原job各执行一次、全部SUCCESS，无失败重跑或原生重执行。QFQ日更7项、MACD/KDJ指标及state14项、九转4项，共25个28日资产补齐；原检查合计81项全部通过：28条QFQ日更检查＋7条因子repair完成检查＋28条MACD日更检查＋14条指标repair完成检查＋4条九转检查。两个repair均消费原job自动确定的同一16股范围，没有人工指定名单，也未重复执行已完成的Raw/Silver或Silver因子修正。

10:40:16按批准恢复本节列出的5个分钟sensor，逐项读回均为RUNNING，未清理或重置cursor，未改其他sensor、daemon或资源设置。此前各节STOPPED是执行期间的历史状态，恢复待办已关闭。证据：[sensor恢复记录](../../reports/datasets_recovery_20261028_20261029/sensor-restoration.json)。

本轮39个`/tmp`中间文件合611,044B，已逐字节核对归档后删除，临时目录已移除；正式staging及其提交、恢复记录保留。精确清单和结果见[清理记录](../../reports/datasets_recovery_20261028_20261029/cleanup-manifest.json)。

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
