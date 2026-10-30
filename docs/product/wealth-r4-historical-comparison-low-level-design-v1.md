# 修订后r4历史识别对比专项LLD v1

更新：2026-10-30。状态：专项编码设计及提交后独立审计已完成，审计补充已定向复核；未开发、未读取行情、未执行对比。开发及真实执行另等指令。

依据：[专项方案](wealth-r4-historical-comparison-plan-v1.md)、[当前正式规则及测试](../../wealth/docs/pages/index-detail/index-detail-top-bottom-recognition-low-level-design-v1.md)。本文件只规定一次性识别核验工具，不改变正式r4、P3停点、产品接口或后续P4/P5顺序。

## 1. 目标、现代码和保护范围

固定000001.SH日线2023-01-03—2026-10-27，922根，历史r2/历史r4-v2/修订后r4各从空状态算一次。管理员已确认行情不变；不再以源修订为待确认问题，但仍拒绝错范围、缺交易日或错字段。

| 当前依据 | 本专项使用方式 |
|---|---|
| `DailyWaveQuery.load_main_window/load_calendar` | 仅父进程复用六列行情/三列SSE有界查询，不调用build_review、不另写SQL |
| `DailyWaveReadSession` | 专用只读REPEATABLE READ、无池，关闭后才启动计算进程，不启动App |
| `normalize_source_row/validate_calendar`和日线calculator的`_points` | 校验真实字段、完成日期、交易日及原0.0021指标关系；转换结果仅用于校验，实际计算继续使用原始float |
| 历史`compare_r4` | 只在固定历史模块进程内运行；已有check、记录关联及旧双组比较保持原样 |
| 当前`XxmCalculator` | 在另一个固定版本进程内调用，开启record_decisions；只识别、不预测、不调用服务缓存 |

源代码检查与CodeGraph已覆盖读取、会话、校验、核心及旧比较调用链。不得把历史研究类接到当前父类上，不为兼容旧结果修改产品types或Spec。

现有`src/**`、`wealth/src/**`、旧研究实现/测试和正式P3文档均为保护范围。将来只新增§2列明的三个研究文件及对应测试，主题README只加本专项入口；本轮只提交专项方案/本LLD及docs索引相关条目。不创建分支/worktree、不安装、不改Git工作区、不提交他人改动、不部署。

## 2. 文件、入口及固定参数

位置均在`scripts/research/index_market/`，不建立通用多版本框架。

| 文件 | 固定入口及职责 |
|---|---|
| `xxm/r4_history_comparison.py` | 不可变HistoryComparisonSpec；`run_historical_comparison(*, check_cancelled=None)`真实入口；`read_input`、`read_git_sources`、`run_worker`、ResearchBudget及受控管道；只返回成功结果，不增加CLI/API |
| `xxm/r4_history_worker.py` | 仅标准库的内部子进程程序；`worker_main()`接一次内存请求，加载固定模块并计算；无命令行业务参数，不读行情文件/数据库 |
| `xxm/r4_history_records.py` | `validate_baseline`、`compare_fact_groups`、`format_report`；组内关联/旧日期映射、逐日比较和文字；不调用识别器 |
| `tests/test_xxm_r4_history_{comparison,worker,records}.py` | 独立字面输入/手写结果、真实小样本进程、资源与失败退出；不得修改现有测试预期 |

函数交接固定：`read_input(budget)`返回§3输入对象；`read_git_sources(budget)`返回按OLD_PAIR/CURRENT分开的固定模块元组；`run_worker(bundle, rows, sources, budget)`返回该组已验证事实。内部`_pump_process(proc, request_bytes, *, protocol, budget)`只处理已创建且登记的本次Popen，protocol仅GIT_BLOBS/WORKER，不接受任意用户命令。人工管道测试可直接给这个内部函数专用测试进程；真实run_worker的解释器/入口路径不可注入替换。

`validate_baseline(old_result, *, input_rows, check)`返回检查项；`compare_fact_groups(old_result, new_result, *, input_rows, check)`返回summary/differenceDays；`format_report(result, *, check)`只返回文本。各函数不保存、不打印、不自动重读或重算；最外层在全部成功后才展示本次完整报告。

HistoryComparisonSpec集中保存下表的唯一值，严格校验类型和值，拒bool冒充数值；不增加env、Settings、数据库配置、用户开关或可选算法。它只由本专项三个实现及对应tests消费，不改变产品Spec。参数均是代码内固定约束，无持久化，修改需先改方案/本LLD并review。

| 参数 | 值 |
|---|---|
| 历史提交 | `da4a97eeffd4840191fcb9f95283d6be97bb8d28` |
| 当前提交 | `c6a845fe3e8f13258b3c12f3ecfa843bce544f85` |
| 对象/周期/起止/真实根数 | 000001.SH / day / 2023-01-03—2026-10-27 / 922 |
| 行情/日历上限 | 1000/2000，查询各加一探测；真实日历1394自然日/922开市日 |
| 总时间/清理预留 | 20.0秒 / 0.5秒；只用一个单调时钟起点 |
| 读取 | 8秒，连接2秒/SQL3秒/锁1秒/清理0.5秒，沿既有只读会话 |
| 合计内存/完整结果 | 256MiB / 16MiB，1MiB=1048576字节 |
| 全部固定算法源码/请求正文 | 1MiB / 每次2MiB；已核固定源码总156,027字节 |
| 控制消息/累计控制消息/条数 | 每条4KiB / 每次256KiB / 每次1024条 |
| stderr/单次管道读写 | 每次64KiB / 最多64KiB，不将stderr原文输出给用户 |
| 父进程轮询/资源报告间隔 | 最多0.05秒 / 峰值改变时最多每0.05秒一条；单次增长达到1MiB或阶段边界立即报告 |
| 单次Git命令 | 最多2秒，并受原work_deadline约束；不连接网络、不自动fetch |
| 最终字节核对 | 最多5轮，沿旧比较器的有限核对方式；开销计入总20秒，不适用于产品API一次编码要求 |
| 运行环境 | 本机现有Python3.13及Darwin；不为其他平台增加适配，本机Git为`/usr/bin/git` |

内部辅助函数可用少量人工行测试进程和比较，最长1000行；只有真实入口负责922根/SSE和历史摘要。不得新增test模式、隐藏CLI或用短样本绕过真实入口的922根检查。

## 3. 总顺序与同一次输入

专项在新的独立父进程执行，不借用Web、Notebook或长期pytest进程的资源计数。父进程不同时拥有两个活动子进程；Git及计算进程均不产生后代。旧进程彻底回收后才可启动新进程。

1. 建立`t0=monotonic()`、`deadline=t0+20`、`work_deadline=deadline-0.5`，所有后续操作和最终检查使用它们。检查取消及本机环境、分支、保护文件/暂存差异；只记录事实，不自动恢复文件。只核正式4个核心文件相对固定提交的差异，不要求HEAD等于c6a845fe3，也不要求清空其他dirty文件；纯文档提交不得误拦，正式核心已变化则停止review。
2. 确认Git不是partial/promisor仓库，无replace引用/grafts；不继承GIT_*变量，不运行hook或网络命令。配置查询返回1且正文为空表示未设置，属正常；promisor显式false也允许，其他非法值/查询失败拒绝。refs/replace空列表正常，存在替换引用或非空grafts拒绝。检查固定提交/路径，不存在即失败，不fetch。
3. 用§4固定名单从Git对象读源码至RAM并回收Git进程，核源码总量与资源；之后不再启动Git与计算进程并行。
4. 读取一次六列行情、一次SSE日历。只在专项装配`replace(DEFAULT_SPEC, requested_start='2023-01-03', requested_end='2026-10-27', absolute_start='2023-01-03', max_main_points=1000, max_context_points=0, max_total_points=1000)`，其他已有源校验/读取预算不变；不改DEFAULT_SPEC。只读上下文结束后继续，不把连接传给子进程。
5. 一次捕获带上海时区的calculated_at，逐行调用normalize_source_row；以`DateRange('2023-01-03','2026-10-27')`及本次日期集合调用validate_calendar。对七字段规范结果调用`_points(..., as_of='2026-10-27', spec=专项读取Spec, guard=同次读取budget)`核原Decimal H关系。完成读取及这些校验总计仍受同次8秒及外层work_deadline约束。禁止调用build_review、峰谷扫描或候选划分。
6. 从原始六列构造`tuple[(time,close,dif,dea,hist,completed),...]`，其中time为YYYY-MM-DD、四个数值为源float、completed为True。normalize/_points所得Decimal或字符串不替换这些数值。必须恰922行、首末准确、无额外日期，且与SSE开市日逐日一致。
7. 调旧进程，成功回收、解析及validate_baseline通过后，才调新进程。两次请求的标量行完全相同，各自建立本版本XxmBar，均从空进度开始。旧基准不通过就不算新组。
8. 新组也成功回收后，验证全部关联并比较；生成报告正文和资源摘要，核总结果大小、内存、原截止及保护范围后才返回成功。不得先返回部分差异，再补检查。

`read_input`返回仅RAM对象：`{rows, calendarCount, openCount, requestedStart, requestedEnd, actualStart, actualEnd, sourceDescription}`。sourceDescription只含对象、列、来源类型及实际日期/行数，不带DSN、SQL正文或凭据。不另查近/远参照窗口，不补更早行情，不重算MACD。

## 4. 固定版本模块与进程启动

### 4.1 原源码取数与装载

历史模块全名按顺序为：产品包内types→spec→snapshot_validation→calculator，再研究包内r4_reference_trial→r4_observation→r4_comparison_records→r4_comparison。当前只取当前提交的前4个产品模块。

产品包全名为`src.biz.services.wealth.market.index_detail_xxm`；研究包为`scripts.research.index_market.xxm`。名单由Spec提供，不接受外部路径/提交参数。通过一个受控`git cat-file --batch`按12个固定`提交:路径`读取；解析blob类型、声明长度、结束换行及总量，missing/非blob/非法UTF-8/多余正文均拒绝。Git协议中对象编号仅用于解析，不作源码SHA保护。读取/回收遵守§5—6同一管道和资源规则，不解压旧目录。

`run_worker`只启动`[现有解释器, '-I', '-S', '-B', 专项r4_history_worker.py绝对路径]`，shell=False、二进制三管道、bufsize=0、close_fds=True、env={}。worker仅导入标准库；-I不从当前目录/用户包找代码，-S不执行site，-B不写pyc。获准的新worker文件及解释器/标准库的启动读取允许，固定旧/新算法源码只经请求传入RAM。

先建立有限空包，`__path__=[]`，不执行真实仓库__init__；按名单建立ModuleType并先登记sys.modules，再按固定顺序执行原源码，设置原完整__name__/__package__和只用于定位的虚拟__file__。不重写import、不修改源码、不临时补旧types。名单外src/scripts业务模块若被导入必须失败，不退回工作区。当前types的TYPE_CHECKING不触发forecast_math运行时导入。

装载后检查实际MAIN_SPEC版本：旧为xxm-direction-v0.1-r2，新为xxm-direction-v0.2-r4；旧R4_TRIAL_SPEC必须xxm-research-r4-v2。实际规则Spec及其自身生成的规则hash回报metadata，不伪造hash，不以源码摘要检验“代码未变”。父进程核本次固定提交、组和实际规则身份一致。

### 4.2 两次计算的限定动作

旧worker只调用一次原compare_r4，period=day、相同input_identity、固定报告区间及外层work_deadline。为了报告活进程内存，**仅在旧worker中**允许给`r4_comparison._memory_bytes`附加读数包装：调用原函数→检查本worker预算/必要时发RESOURCE→原整数原样返回；finally恢复原函数。不改原check、Spec、calculator方法、观察/比较政策或源码。正常预算下包装开关不能改变业务事实；资源和时间元信息不要求字节相同。

旧返回字段为metadata/rows/differences/idPairs/summary。原compare已完成组内/跨组关联验证；外层保留rows及summary、必要metadata后释放differences/idPairs和原完整返回容器，不将两份重复账本都传出。rows保持time、input、r2/r4的point/events/histories/bottomHistories/rearmRecords/decision原事实。

新worker建立唯一正式XxmCalculator(record_decisions=True)，逐根一次step；每根前后check，记录`{time, point, events, structures, decision}`。记录来自实际返回，不运行第二只计算器补解释，不恢复旧waiting字段。两worker内部都不传数据库连接、Settings或凭据，不调用查询、App、API、预测、缓存或文件输出。

## 5. 通信合同与防止互相等待

### 5.1 请求与消息格式

消息均为8字节无符号大端正文长度＋严格UTF-8 JSON正文。先检查长度再分配正文；拒绝重复JSON键、NaN/Infinity、bool冒充计数/数值、非法UTF-8、多余字段或额外消息。

父→worker只有一个REQUEST，然后关闭stdin。顶层字段固定：`kind, protocolVersion, bundle, commit, tsCode, period, startDate, endDate, inputIdentity, inputCount, rows, modules, workDeadline, maxWorkerMemoryBytes, maxResultBytes`；kind=REQUEST、protocolVersion=1、bundle仅OLD_PAIR或CURRENT。modules是按固定名单排列的`{name,path,source}`；不传任意执行函数、文件路径输入或pickle。

rows的每行严格六项及原类型。编码前和解码后逐项比较日期、type及原值，零额外核math.copysign；不把float变Decimal/两位值，不合并-0.0。worker的inputCount与实际行数相同，≤1000；真实入口仍在§3恰922，不在worker添加可变业务模式。

worker→父进程只允许以下JSON消息；每条都有`kind, protocolVersion, bundle, commit, pid`，pid须等于本次Popen.pid；phase仅OLD或CURRENT，与bundle对应。计数/字节必须非负整数且非bool，峰值单调不减。错误exceptionType为至多128字符的类型名，errorKind仅INPUT/VERSION/MODULE/PROTOCOL/TIMEOUT/MEMORY/SIZE/INTERNAL，属于内部诊断，不是新API错误码：

| kind | 额外字段及顺序 |
|---|---|
| HELLO | peakMemoryBytes；恰一次，开始计算前 |
| RESOURCE | phase、peakMemoryBytes；可出现在HELLO后、DONE前，含RESULT之后 |
| RESULT | payload；恰一次。OLD_PAIR为metadata/rows/summary，CURRENT为identity/rows；不在本帧伪装整体成功 |
| DONE | peakMemoryBytes、processedCounts；恰一次且在RESULT后，旧两组各实际inputCount，新组实际inputCount |
| ERROR | phase、exceptionType、errorKind；失败时使用，不带源数据、凭据、SQL或完整traceback，不允许随后DONE |

控制消息受4KiB/256KiB/1024条限制，RESULT受分配给本次worker的剩余结果上限；请求≤2MiB。stderr不用于业务协议，累计≤64KiB；任意非空stderr都按异常退出处理，不显示原文。

成功条件必须同时具备：合法唯一HELLO/RESULT/DONE、身份及计数正确、stdout/stderr完成EOF、无协议外字节、子进程退出码0、已wait回收、资源/内容/截止检查通过。仅收到RESULT或退出码0均不够；旧结果只是本次私有候选，不在新组及最终检查前发布。

worker先验证REQUEST基础身份再发HELLO；基础身份尚不能建立时，非法输入直接非零退出，不伪造一份bundle/commit发ERROR。已建立身份后，计算/装载失败可发送对应身份ERROR并退出1。父进程在两种失败下均不得接受结果，不以没有ERROR消息视为成功。

### 5.2 有界读写

Popen后对stdin/stdout/stderr设置非阻塞，以selectors.DefaultSelector同时处理写入和两个读取口；每次最多64KiB。输入完全写出才关闭stdin，不能先阻塞write完大请求再读输出，也不能先wait再读管道。部分header/正文保留接收状态，读到EOF但消息不完整即失败；BlockingIOError只让出本轮，不自动重试整个任务。

每轮select最多0.05秒且不超过原work_deadline剩余时间；前后及每个分块都检查取消、时间、父内存、已知合计内存及累计字节。正文长度超限在扩容前拒绝，重复RESULT/错误顺序/未知kind/不完整EOF直接失败。正文收齐后的json.loads前后都check，不把解析/复制开销排除预算。

**每条消息的header和正文必须连续发送，不能插入另一条消息。**此约束适用于所有kind：header发出首字节后，直到正文全部发完，RESOURCE和ERROR也不得插入。发送中仍检查取消、时间、内存及字节；资源变化只合并记录最新待报告峰值，不递归调用发送。当前消息完整后才补RESOURCE，且只能在HELLO后、DONE前补发；RESULT完整后先补RESOURCE再发DONE，DONE或ERROR后不再补消息。内存增加≥1MiB或阶段变化的立即报告要求也服从该发送顺序，不能破坏正在发送的正文。

若一条消息已经发出部分字节，此时取消、超时、超内存或写入失败，直接非零退出并关闭管道，禁止在未完成正文后追加ERROR；父进程按不完整EOF/非零退出拒绝整轮结果。当前消息尚未发送任何字节且已建立身份时，才可发送完整ERROR；身份未建立沿§5.1直接失败。

禁止以无界communicate或`read()`收完整结果后才查上限；禁止线程池、后台读取线程、临时输入/输出文件和新套件。Git的batch协议另按其ASCII header＋原blob正文解析，但使用同一有界读写循环和截止；cat-file非零退出、stderr、协议异常或单次2秒超时均失败，只有§3明确的可选配置查询未设置例外。

## 6. 内存检查、时间和退出

### 6.1 合计内存口径

本机Darwin的resource ru_maxrss沿当前`_memory_bytes`口径直接为字节，不乘1024；不支持的平台在读数据前拒绝。新父进程只拥有登记过的Git/计算子进程，任意时刻最多一个活动子进程且无后代，不在同进程兼做其他任务。

外层维护单调不减的`parentPeak`、`waitedPeak`和本次活worker的`reportedPeak`：

```text
parentPeak = max(既有值, getrusage(RUSAGE_SELF).ru_maxrss)
waitedPeak = max(既有值, getrusage(RUSAGE_CHILDREN).ru_maxrss)
knownChildPeak = max(waitedPeak, 所有已收到的worker峰值)
combinedPeakUpper = parentPeak + knownChildPeak
```

任一单进程峰值或combinedPeakUpper超过256MiB即失败。由于子进程不重叠，父自身峰值加最高子峰值是保守上界；它可能多计，不能用当前RSS替换峰值绕过失败。RUSAGE_CHILDREN只有终止并完成wait后才补齐，不能靠它监测活worker，也不能把旧程序自己的256MiB检查当合计通过。

worker在解码、每个模块加载前后、计算检查点、结果编码前后及最终DONE前读自身峰值；峰值变化按§2节流发送RESOURCE，单次增加≥1MiB及阶段边界立即发送。旧计算检查点通过§4.2读数包装观察，新计算每根前后直接check。自身超过请求maxWorkerMemoryBytes立即ERROR并失败。该额度为启动时`256MiB-parentPeak`，父进程仍以自身增长后的实际保守合计检查，额度不是额外内存。

父进程在每个管道块、消息、JSON解析/复制/比较、结果编码前后读取自身峰值，结合最新RESOURCE检查；每个子进程wait后及最终返回前补读CHILDREN，包含Git、正常和异常退出。Git短过程不提供活峰值，读取量/2秒受控，回收后必须补核系统峰值；核完才进入下一阶段。

这是检查点监测和最终保守峰值验收，不宣称拥有操作系统硬内存隔离或能禁止任何瞬时超额分配。任一超限都不能宣称成功，也不能通过删记录、换统计方式或单独跑各组来凑预算。

### 6.2 字节与副本

父进程记录旧RESULT字节、新RESULT字节和最终报告/比较结果字节，合计≤16MiB；没有结果的一组不以0冒充已执行。为下一worker传`maxResultBytes=16MiB-已保留正文大小`，父接收长度也按同一剩余额度检查。最终报告再占用剩余部分，不足即失败，不省略差异日期。

旧组解析后释放接收bytearray和旧重复容器；新请求源码/序列化缓冲用完即释放。所有实际JSON解码/编码副本仍计合计内存。不得建立三份全量标准化账本再复制差异；比较按922根顺序使用原事实，仅对差异日建立输出。最终成功结果不再附完整三组rows。

### 6.3 失败、取消和回收顺序

check在源读取、Git、启动、每行/消息/分块、比较、编码以及返回前使用同一个work_deadline和取消回调；回调抛出的原异常不吞。阶段名固定为PRECHECK/GIT/READ/OLD/CURRENT/COMPARE/REPORT/CLEANUP，不新增产品状态或API错误码。

| 触发 | 必须退出方式 |
|---|---|
| 源合同、日期/行数、输入/版本/协议或关联错误 | ValueError或既有源异常向上；不算下一组，不修字段 |
| Git/worker不存在、非零退出、stderr或未知错误 | RuntimeError，报告阶段和异常类型，不输出原stderr/SQL/凭据 |
| 总时限、Git时限或最后check过期 | TimeoutError；不重新给20秒 |
| 单进程/保守合计内存超限 | MemoryError；丢弃本次所有候选 |
| 源码、请求、控制或结果字节超限 | OverflowError；不截断、不改为部分成功 |
| 外部取消 | 原取消异常或既有DailyWaveCancelled；不启动下一子进程 |
| 基准不复现 | ValueError并列摘要差异，尚未计算新组；不改旧expected |

外层持有唯一活动Popen及打开管道/只读上下文；只操作本次创建的句柄/PID，不按进程名查杀、不碰其他服务。任何失败先停止新工作、关闭stdin；若活动进程尚未退出，terminate后至多等`min(0.1秒, 剩余清理时间)`，仍未退出则kill并在原deadline内wait。同时关闭/注销本次管道、回收子进程、补核峰值，释放私有输入/结果。正常路径也必须wait完成，确认旧进程已回收才能启动新组。

**清理阶段不得再次调用check_cancelled或会调用它的业务check。**外层进入finally后只读取时钟、进程状态及资源，不让重复取消异常打断terminate/kill/wait。每次等待使用`max(0, deadline-now)`，不得传负超时；剩余时间为0时不再等待优雅退出，直接kill并尝试非阻塞wait。尚不能确认回收时，按下段规则记为失败并继续只处理本次句柄；不能返回成功、启动下一组或以重抛取消跳过回收。首次取消/业务异常始终保留，清理异常仅作为附注。

读取阶段异常先沿DailyWaveReadSession原finally关闭连接并停止计算，不能绕过其0.5秒收尾；其他阶段只读会话已关闭，不再占连接。work_deadline后不再启动业务，原deadline的最后0.5秒只供清理；不把清理开销留到成功返回之后。

保留首个业务/取消异常；清理异常只附固定阶段和异常类型，不用finally的新异常覆盖原错。不能确认回收或清理超时属于本轮失败，报告超限及退出未确认，继续仅对本次句柄做终止/回收处理，不放行新工作、不声称20秒验收通过。不自动重试，不返回旧组结果充新组，不留下恢复文件/长期进程。专项不得使用hook保证退出。

## 7. 原事实校验、日期映射和比较

### 7.1 组内合同

旧每行保持`time/input/r2/r4`，每组严格包含point/events/histories/bottomHistories/rearmRecords/decision；新每行包含time/point/events/structures/decision。父进程核输入点的time/close/dif/dea/hist逐行与本次源严格相等，行数/升序/身份正确。底部旧等待、旧PENDING/ENDED和新ASSESSING/LOCKED/DISAPPEARED不得互相改名。

每组先建id索引并核引用类型、首次出现日、形成事件及原结构关联；旧组已有完整关联检查也不能代替父进程对传输结果的核验。新结构更新同id只允许原形成事实不变、后续终态不回退；point只能引用当时仍有效的结构。锁死后未来价格不能改写早前形成/考核事实。保留全部922根前缀，不只查差异当天。

旧极值日期映射键为`(group,sign,start,end,price,dif)`，来源仅该组实际`decision.referenceChecks[].wave`，其price_at/dif_at须是区间内已出现日期，值与对应输入行相等。同键反复出现日期必须一致。按时间先登记本根检查，再核当前及此前的point/event/history原参照；丢出历史池的映射不删除。缺失/冲突/错误值拒绝，不借别组日期、不补查询、不重新找峰谷。新组六字段参照直接读取，也核区间/原值/日期。

### 7.2 基准与差异

`validate_baseline`只用于真实922根：旧两组各DULL30/STRUCTURE17/CANCEL12/历史价格撤销7，逐日标签type/direction/route及根末普通状态相同；活动参照差异24日、事件记录差异13日、任意字段差异254日，且原方案§16的候选日期/参照和三次B→A保持。编码字节、耗时和进程峰值不是历史相等要求。人工短样本使用独立手写预期，不套这些真实计数。

主要对比CURRENT与历史r4，另列历史r2。分别比较共同业务含义的事件序列、根末状态/方向、实际参照、真实判断条件和结构后续事实；原始说明句子、计时/内存和纯编号差异不算业务标签变化。旧/新专属结构字段分别展示，不因字段名不同就报新标签，不因无对应列就抹掉旧等待/撤销或新锁死。

编号仅用于各组自身关联；跨组普通事件先按同日同方向类型/route序列核标签，再核参照及关联。不存在唯一同日对应时保留两侧，不强配多个候选，不跨日期自动断言提前/推后。形成并锁死根即使根末NONE也保留当根结构事件；无新事件的B→A列为参照变化。

解释必须给实际条件值及正式规则出处；条件不足以确定原因就标“待核”，不做反事实重放、不改阈值找解释。不能把“不同”当新算法错误或把“相同”当复现作者软件已证明。

### 7.3 成功返回

返回顶层固定为`metadata/baselineCheck/summary/differenceDays/metrics/reportText`，只有全部检查成功才返回。metadata包含三组提交/实际规则身份、源字段/实际起止/根数及左侧从空状态的限制；baselineCheck保留真实检查项与预期/实际；summary分别记录标签/状态/参照/结构/判断依据差异日期，零差异用0和None，不伪造首日。reportText在预算内预先生成，调用方只展示，不在返回后调用format_report重新生成。

differenceDays按日期严格升序，每日只放一次当根证据、三个组的必要事实及changes。changes各项固定字段为`category/field/comparedGroups/ruleSource/explanation/pendingReview`，后三项分别表示规则出处、中文说明和是否待核（bool）；不把字段处数混为日期数。保留全部差异日，文字可先展开首次/典型日，但不能静默删掉剩余日期。

metrics记录唯一t0后的各阶段耗时、parentPeak、最高子峰值、最终combinedPeakUpper、三组step数、读取次数、两次worker正文及报告字节、所有子进程已回收。结果和reportText一起测最终字节，reportText已含于JSON时不能又重复相加；旧/新worker正文另计。资源字段更新使最终候选大小变化时，最多5轮核字节和峰值，未稳定整轮失败。结果和报告先准备并check，最后一次校验后只返回已准备对象，不在返回后再编码或清理可能失败的资源。

## 8. 逐项测试设计与验收

三份新tests分别对comparison/worker/records负责，输入及预期独立于待测实现。源码真实生产者为两个固定提交；普通小样本的实际进程测试与替身测试分别报告，替身不冒充进程隔离通过。

| 编号 | 输入/故意错误 | 必须断言 |
|---|---|---|
| HC01 | 固定8/4模块、工作区同名模块会报错；纯文档新提交/无promisor配置；缺模块/错误版本/核心变化/额外业务import | 正常提交及未设置配置不误拦；正确小样本实际进程成功；不执行工作区模块/包__init__；错误明确拒绝，不补兼容 |
| HC02 | 有限float、-0.0经请求往返；NaN/重复键/bool/错行/重复日期 | 原类型/值/零符号不变；错误拒绝；正常源值不误拦 |
| HC03 | 非法对象/未完成/缺日历日/缺开市行情/1001探测；922合成源 | 六列DATE/float、三列bool依真实模型造夹具；读取恰各一次；不补值不截断。合成日历不冒充真实SSE验收 |
| HC04 | 专用人工管道测试进程在读完请求前先输出HELLO，且请求/输出均大于系统管道容量 | 父同时读写成功，不因先write或先wait死锁；不写临时文件。此替身只验父管道，不改变真实worker完整解析请求并验证基础身份后才发HELLO的顺序 |
| HC05 | header/正文分多块且中途资源增长；半帧取消/超时/内存失败；EOF少字节/长度超限/重复RESULT/DONE乱序/未知kind/假pid | 正常分块可完整解析，RESOURCE不插入正文；RESULT后补资源再DONE，DONE后无消息；半帧失败直接EOF且不插ERROR；非法在上限前拒绝，单RESULT不算完成 |
| HC06 | stderr非空、worker退出1、收到RESULT后取消/超时、Git missing或部分blob | 无成功返回，不运行下一组；仅输出阶段/类型，无源/凭据/SQL泄漏 |
| HC07 | 合成父150MiB+活worker120MiB，各自都低于256；父90+子80；依次子80/90 | 前组立即失败；正常组通过；顺序两子取最高，不把两子并发求和，也不只看父进程 |
| HC08 | 最后一次RESOURCE很低，子进程退出时CHILDREN给出更高峰值；Git回收峰值超限 | 最终拒绝，包含JSON编码及Git；不能按较早采样通过 |
| HC09 | 旧_memory_bytes原返回固定；包装开启/关闭 | 原值原类型不变，正常业务事实相同；仅资源/时间元信息可不同；无业务方法/Spec改写 |
| HC10 | 原20秒过期、各进程单独不足20秒但合计超时、复制/编码后过期 | 共享截止；清理也计时；已收到结果仍不可返回 |
| HC11 | terminate无响应→kill→wait；取消在输入发送中/输出半包/最后DONE后；取消回调每次调用都抛错、清理剩余时间为0 | 清理不再调用业务取消检查，不被第二次取消打断回收，不传负超时；只终止本次PID，所有句柄关闭、已wait、无后代/遗留；无法在限内回收就明确失败，原异常不被清理错覆盖 |
| HC12 | 总结果超过16MiB、控制消息累计超限、内存副本使峰值越线 | 整轮失败，不删日期/字段；正确有界结果仍通过 |
| HC13 | 手写相同标签异参照、仅ID变化、无事件切换、形成并锁死根末NONE | 分别归类，日期/原值/参照不丢，不把字段差异说成标签改变 |
| HC14 | 旧Wave同键不同发生日、缺失日期/数值不符、远参照已出历史池 | 冲突/缺失拒绝；完整前缀映射仍可查旧远参照，无补查/重选峰 |
| HC15 | 旧等待/撤销与新回钝化/锁死；悬挂结构id/未来引用/终态回退 | 保留不同含义，错误关联拒绝；不能伪造旧新一一等价 |
| HC16 | 同日多候选/跨日事件，解释措辞或版本号变化 | 多义不强配；跨日分列；仅措辞/版本不当业务差异 |
| HC17 | 人工小计数及一项错误；真实922基准一项错 | 两类预期分开；真实基准失败不启动新组，不用实现生成expected |
| HC18 | 922根人工规模，两次进程/管道/比较/编码/清理全走 | 专用外层进程实测20秒/合计256MiB/16MiB；不是pytest宿主单只计算器计时 |
| HC19 | 实际小字面序列三组执行；计算期文件/网络/数据库调用会失败 | 正常纯核心可用；不导入API/查询/预测/cache；正式文件/测试/Spec/暂存/分支前后未改 |

同时保留正式识别/恢复/输入及P3第2步定向回归，不运行旧研究全目录或待清退runner。不用旧结果生成新规则expected，不改现有测试预期或增加skip/xfail。根三份架构和新研究依赖/文档检查必跑；每组60秒，超时停止，不安装。

## 9. 实施门禁与本轮停点

开发前先审计本LLD及方案的一致性，核当前固定提交、模块、保护文件和工作区差异；必须取得专项开发授权。先实现独立字面验证和进程/失败路径，再做922合成规模及独立代码审计，最后获得明确执行授权后只读一次真实区间。不能因文档提交或人工通过而自动重放。

真实成功验收必须含：三组输入相同、旧基准复现、关联/差异完整、资源/回收及保护范围证据；独立审阅者只审同次返回，不重复读DB/重算。算法待核项保留交管理员review，不自动改产品。源行情/源码/完整账本只RAM，文档可记录摘要和差异说明，不生成结果目录、JSON或恢复文件。

本轮只完成方案及专项LLD文档提交和独立审计；当前P3第3步、专项代码/测试、真实对比、产品400ms/浏览器及P5清退均未执行。文档审计通过不能记成实现验收。

## 10. 资料与证据边界

已使用CodeGraph核读取/会话/校验/计算调用；对固定Git源码补核加载顺序、旧Wave及旧/新记录合同。现有Python3.13.5和本机Git路径已只读确认，未导入算法或读取行情。

通过Context7查阅[Python subprocess](https://github.com/python/cpython/blob/v3.13.9/Doc/library/subprocess.rst)、[selectors](https://github.com/python/cpython/blob/v3.13.9/Doc/library/selectors.rst)、[resource](https://github.com/python/cpython/blob/v3.13.9/Doc/library/resource.rst)官方资料。实际API语义仍以现解释器和有界人工测试核验；文档链接或静态审计不代替进程通信、预算或真实来源已通过。

提交后按通信退出、资源预算、版本输入及结果含义分工独立审计。发现并补齐清理不能重复调用取消检查、完整消息之间才能发送资源/错误消息两处要求；同时明确HC04替身边界及changes字段名。修订已定向复核通过，方案与LLD一致，未发现需要新增业务决定的开工阻塞。HC01—19是后续测试设计，尚未执行；实际耗时、内存、字节及旧基准复现仍须后续验收。
