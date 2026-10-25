# 股票分钟前复权与MACD/KDJ写入修正方案和LLD

日期：2026-10-24；读取优化实施：2026-10-25。当前状态：第9节读取优化已开发并通过第10节隔离测试，正常及续跑年度摘要均每实际文件1遍，另2遍已删除。尚未进行正式补数；34/9预算仍待实际样本校准和年度读取单独批准。后续真实性能样本及清理要求见第11节，本轮只说明范围，不运行该真实样本。

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

本次指令批准提交已完成代码，并说明后续样本量；没有启动真实样本。以下范围用于后续执行卡，真实数据内容读取/临时写出仍在执行前核准，不把本节或前次开发测试授权当作正式补数授权。

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
