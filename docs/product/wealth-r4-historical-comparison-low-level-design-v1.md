# 修订后r4历史识别对比专项LLD v1

更新：2026-10-30。状态：第一批已提交0434dd06；首次第二批PG读取失败见§13。本地DG Silver读取修正已开发并验收，设计及实际证据见§3.1、§14—15；本轮未启动三组正式比较。第一批证据见§11，本次失败证据见§13。

第一批执行对账：已按授权完成下列硬口径、人工验收和独立代码审计；该批停止在第二批真实数据读取与对比之前，未调用真实run_historical_comparison入口、修改产品/旧研究实现及现有测试预期，未自动提交。第一批证据见§11，后续提交及第二批授权/执行见§12—13。

| 硬口径 | 实现位置 | 验证 |
|---|---|---|
| 固定版本/模块及纯内存隔离，现有核心不改 | comparison的Spec/Git/启动，worker装载 | HC01/09/19，核心四文件Git差异 |
| 本地一次六列行情/三列日历、922根及原float，拒绝补值重算 | comparison.read_input | HC02/03及HC20—24，真实临时Parquet与一次限定本地真实读取 |
| 三管道分块且完整消息不插帧，全部成功才返回 | comparison._pump_process、worker发送 | HC04/05/06 |
| 共享20秒及清理预留，父子合计256MiB，全部结果16MiB | ResearchBudget、两侧检查及回收 | HC07—12/18 |
| 旧基准先核，新旧关联/参照日期和结构含义如实呈现 | records三入口及comparison编排 | HC13—17、手写预期及真实小字面进程 |
| 失败取消完成本次进程回收，不重试或落盘 | comparison清理，worker失败 | HC06/10/11/19 |

本批人工规模验收在新的独立父进程使用922根合成值，预算包含源码读取、两次worker、比较、编码及回收；不调用正式真实入口或把合成源计为真实SSE通过。旧真实基准仅设计检查及手写反例，本批不声称复现。

依据：[专项方案](wealth-r4-historical-comparison-plan-v1.md)、[当前正式规则及测试](../../wealth/docs/pages/index-detail/index-detail-top-bottom-recognition-low-level-design-v1.md)。本文件只规定一次性识别核验工具，不改变正式r4、P3停点、产品接口或后续P4/P5顺序。

## 1. 目标、现代码和保护范围

固定000001.SH日线2023-01-03—2026-10-27，922根，历史r2/历史r4-v2/修订后r4各从空状态算一次。管理员已确认行情不变；不再以源修订为待确认问题，但仍拒绝错范围、缺交易日或错字段。

| 当前依据 | 本专项使用方式 |
|---|---|
| DG paths/idx_factor_pro Silver合同及纯类型转换writer、本地物理文件 | 固定正式本地Silver范围和六/三列原值；新读取进程使用现有根环境DuckDB，不import DG、不调用PG/Settings/App |
| 专项固定字段/日历薄校验与纯日线calculator的`_points` | 本专项只按已核实六/三列合同验证原生类型、15点完成及逐日日历；_points保留0.0021指标关系，实际计算仍为原float。不得导入query_service，其模型依赖会间接进入Settings |
| 历史`compare_r4` | 只在固定历史模块进程内运行；已有check、记录关联及旧双组比较保持原样 |
| 当前`XxmCalculator` | 在另一个固定版本进程内调用，开启record_decisions；只识别、不预测、不调用服务缓存 |

源代码检查与CodeGraph已覆盖读取、会话、校验、核心及旧比较调用链。不得把历史研究类接到当前父类上，不为兼容旧结果修改产品types或Spec。

现有`src/**`、`wealth/src/**`、旧研究实现/测试和正式P3文档均为保护范围。本次仅修改本专项§2列明的研究文件及对应测试，并新增固定本地读取文件和对应人工测试，主题README只加本专项入口；更新专项方案/本LLD执行记录，不提交。不创建分支/worktree、不安装、不恢复Git文件、不提交他人改动、不部署。

## 2. 文件、入口及固定参数

位置均在`scripts/research/index_market/`，不建立通用多版本框架。

| 文件 | 固定入口及职责 |
|---|---|
| `xxm/r4_history_comparison.py` | 不可变HistoryComparisonSpec；`run_historical_comparison(*, check_cancelled=None)`真实入口；`read_input`、`read_git_sources`、`run_worker`、ResearchBudget及受控管道；只返回成功结果，不增加CLI/API |
| `xxm/r4_history_lake.py` | LocalLakeSpec单一来源约定；reader_main固定只读子进程；discover_files/read_tables核路径、footer及原生值，不计算算法 |
| `xxm/r4_history_worker.py` | 仅标准库的内部子进程程序；`worker_main()`接一次内存请求，加载固定模块并计算；无命令行业务参数，不读行情文件/数据库 |
| `xxm/r4_history_records.py` | `validate_baseline`、`compare_fact_groups`、`format_report`；组内关联/旧日期映射、逐日比较和文字；不调用识别器 |
| `tests/test_xxm_r4_history_{comparison,lake,worker,records}.py` | 独立字面输入/手写结果、实际子进程的人工小样本、资源与失败退出；不得修改现有测试预期 |

函数交接固定：`read_input(budget)`返回§3输入对象；`read_git_sources(budget)`返回按OLD_PAIR/CURRENT分开的固定模块元组；`run_worker(bundle, rows, sources, budget)`返回该组已验证事实。内部`_pump_process(proc, request_bytes, *, protocol, budget)`只处理已创建且登记的本次Popen，protocol仅GIT_BLOBS/LOCAL_INPUT/WORKER，不接受任意用户命令。人工管道测试可直接给这个内部函数专用测试进程；真实run_worker的解释器/入口路径不可注入替换。

`validate_baseline(old_result, *, input_rows, check)`返回检查项；`compare_fact_groups(old_result, new_result, *, input_rows, check)`返回summary/differenceDays；`format_report(result, *, check)`只返回文本。各函数不保存、不打印、不自动重读或重算；最外层在全部成功后才展示本次完整报告。

HistoryComparisonSpec集中保存下表的唯一值，严格校验类型和值，拒bool冒充数值；不增加env、Settings、数据库配置、用户开关或可选算法。它只由本专项四个实现及对应tests消费，不改变产品Spec。参数均是代码内固定约束，无持久化，修改需先改方案/本LLD并review。

| 参数 | 值 |
|---|---|
| 历史提交 | `da4a97eeffd4840191fcb9f95283d6be97bb8d28` |
| 当前提交 | `c6a845fe3e8f13258b3c12f3ecfa843bce544f85` |
| 对象/周期/起止/真实根数 | 000001.SH / day / 2023-01-03—2026-10-27 / 922 |
| 行情/日历上限 | 1000/2000，查询各加一探测；真实日历1394自然日/922开市日 |
| 总时间/清理预留 | 20.0秒 / 0.5秒；只用一个单调时钟起点 |
| 本地读取 | 8秒含启动/元数据/查询/关闭/通信/父校验，预留0.5秒收尾；footer、行情、日历各最多3秒，父监督。无PG连接/锁预算 |
| 本地文件及SQL | 固定正式Silver，最多1000行情文件/32MiB、日历单文件128KiB；1次批量footer+1次行情SELECT+1次日历SELECT；1001/2001探测；读取RESULT最多1MiB |
| DuckDB | 现有根.venv，:memory:，128MiB、1线程、max_temp_directory_size=0B、扩展自动加载/安装false；不创建目录/写文件 |
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

专项在新的独立父进程执行，不借用Web、Notebook或长期pytest进程的资源计数。父进程不同时拥有两个活动子进程；Git、本地读取及计算进程均不产生后代。旧进程彻底回收后才可启动新进程。

1. 建立`t0=monotonic()`、`deadline=t0+20`、`work_deadline=deadline-0.5`，所有后续操作和最终检查使用它们。检查取消及本机环境；在下一项仓库模式拒绝检查完成前，不运行涉及固定提交对象的diff/cat-file，防止先触发自动补对象。记录分支/暂存和保护文件差异在拒绝检查后进行，只记录事实，不恢复文件。只核正式4个核心文件相对固定提交的差异，不要求HEAD等于c6a845fe3，也不要求清空其他dirty文件；纯文档提交不得误拦，正式核心已变化则停止review。
2. 确认Git不是partial/promisor仓库，无replace引用/grafts；不继承GIT_*变量，不运行hook或网络命令。配置查询返回1且正文为空表示未设置，属正常；promisor显式false也允许，其他非法值/查询失败拒绝。refs/replace空列表正常，存在替换引用或非空grafts拒绝。检查固定提交/路径，不存在即失败，不fetch。
3. 用§4固定名单从Git对象读源码至RAM并回收Git进程，核源码总量与资源；之后不再启动Git与计算进程并行。
4. 按§3.1启动并回收唯一LOCAL_INPUT读取进程，读取一次六列行情及一次SSE日历。只在父校验装配`replace(DEFAULT_SPEC, requested_start='2023-01-03', requested_end='2026-10-27', absolute_start='2023-01-03', max_main_points=1000, max_context_points=0, max_total_points=1000)`，其他已有源校验不变；不改DEFAULT_SPEC，不调用DailyWaveQuery/DailyWaveReadSession。读取进程关闭DuckDB并退出回收后继续，不把连接传给算法子进程。
5. 一次捕获带上海时区的calculated_at，按本专项六列合同逐行核原生类型及收盘完成；SSE日历按固定自然日逐日连续、开市日期列表与本次行情完全相同。对七字段规范结果调用`_points(..., as_of='2026-10-27', spec=专项读取Spec, guard=同次读取budget)`核原Decimal H关系。完成读取及这些校验总计仍受同次8秒及外层work_deadline约束。禁止调用build_review、峰谷扫描或候选划分。
6. 从原始六列构造`tuple[(time,close,dif,dea,hist,completed),...]`，其中time为YYYY-MM-DD、四个数值为源float、completed为True。normalize/_points所得Decimal或字符串不替换这些数值。必须恰922行、首末准确、无额外日期，且与SSE开市日逐日一致。
7. 调旧进程，成功回收、解析及validate_baseline通过后，才调新进程。两次请求的标量行完全相同，各自建立本版本XxmBar，均从空进度开始。旧基准不通过就不算新组。
8. 新组也成功回收后，验证全部关联并比较；生成报告正文和资源摘要，核总结果大小、内存、原截止及保护范围后才返回成功。不得先返回部分差异，再补检查。

`read_input`返回仅RAM对象：`{rows, calendarCount, openCount, requestedStart, requestedEnd, actualStart, actualEnd, sourceDescription}`。sourceDescription含固定local-dg-silver身份、Lake根/两个来源路径、六列/三列及类型、文件数/字节、3类读取次数、实际日期/行数；不再返回远程table身份，不含SQL正文或凭据。不另查近/远参照窗口，不补更早行情，不重算MACD。

### 3.1 本地读取的代码交接（当前唯一读取方式）

**必须删除本专项_read_input_async及对App/PG会话的依赖，不能保留旧读取分支或失败兜底。**产品原Query/Session不修改；父进程只复用纯DailyWaveBudget/DEFAULT_SPEC/_points；六/三列输入按本节固定合同直接校验。禁止导入query_service、Query、ORM或registry，避免间接进入Settings；不是仅禁止显式连接。

1. `r4_history_lake.py`仅在reader_main执行时惰性import duckdb。`LocalLakeSpec`集中固定来源：根`/Volumes/datasource/data_lake`；行情`silver/index/index_factor_pro/trade_date=YYYY-MM-DD/part-000.parquet`；日历`silver/calendar/trade_calendar/full/part-000.parquet`；对象/日期/数量及字段类型、文件/正文/SQL预算。HistoryComparisonSpec对应默认值从该Spec引用；不读env/Settings，不跨工程import orchestrator，不加载Dagster或创建新资源配置。
2. `discover_files`只检查指定1394个日期路径，文件不存在先保留为缺口，日历完整性校验最终拒绝缺开市日；不访问范围外日期/其他代码/Raw。目录及文件lstat拒绝符号链接和非普通文件；发现后记路径及(dev,ino,size,mtime_ns)。最多1000行情文件/32MiB，日历1文件/128KiB；拒绝空集合、缺日历和越限。查询后再次发现并比较集合/元数据，任何替换、修改、新增/消失均失败，无重试。此检查不声称拥有PG事务快照，也不是源码SHA保护。
3. 创建唯一内存DuckDB连接：memory_limit=128MiB、threads=1、max_temp_directory_size=0B、autoinstall_known_extensions=false、autoload_known_extensions=false。仅使用SELECT，不扩展加载、临时目录创建、数据库文件或COPY输出，不改变DG配置。按文件表单执行`parquet_schema(?)`一次，仅取目标六/三列元数据；核每个文件完整且无重名、原生VARCHAR/DATE/DOUBLE/BOOLEAN（拒绝文本日期/整数/DECIMAL/时间戳）。禁止让多文件自动类型合并或CAST吞掉错类型。
4. 第二条SQL一次读取全部目标行情文件：六列+仅用于校验的filename，hive_partitioning=false、union_by_name=false；过滤ts_code及固定日期、升序、LIMIT 1001。核内部日期与该文件分区日期一致、原生float有限及正收盘，再把DATE编码成ISO文本、数值原样传输。第三条SQL仅SSE同范围三列，升序LIMIT 2001，不补齐、不静默去重。存在错误对象的源文件不扩展读取其他标的；返回合同只允许目标代码。
5. `reader_main`以`[现有解释器,'-I','-B',本主题读取文件绝对路径]`、env={}、shell=False、close_fds=True和三管道启动；与两算法worker串行。-S仅对算法worker使用，读取进程需要当前已安装DuckDB，禁止隐式安装。父不预先import DuckDB，模块导入无数据读取。
6. 请求使用8字节长度+严格JSON，仅`kind='READ_INPUT',protocolVersion=1,source='local-dg-silver',readDeadline,maxWorkerMemoryBytes`。readDeadline=min(读取开始+8,原work_deadline)，读取业务截止为readDeadline-0.5，不重设全局20秒；maxWorkerMemoryBytes为256MiB减父峰。固定来源不由请求提供路径或日期。读取进程拒绝额外字段/NaN/重复键/bool计数。
7. READ返回独立消息，不冒用OLD/CURRENT或算法提交。共同字段kind/protocolVersion/source/pid。顺序严格为HELLO(peakMemoryBytes)→三对QUERY_START/QUERY_DONE(query依次SCHEMA/MARKET/CALENDAR，均含peakMemoryBytes)→RESULT(payload)→DONE(peakMemoryBytes)；失败可ERROR(exceptionType/errorKind)，不带原异常正文/SQL/路径外数据。schemaReads/marketReads/calendarReads仅在QUERY_START按实际尝试计数，成功metadata来源说明记录三项计数；metrics保留原marketReads/calendarReads，不改既有报告结构，不能把footer核验算成额外行情读取。每条控制≤4KiB、累计≤256KiB/1024条，RESULT≤1MiB。原完整帧不可插入消息的要求仍适用。
8. `_LakeFrames`复用原_pump_process的非阻塞读写/关闭/回收，protocol新增固定LOCAL_INPUT。收到QUERY_START父将process_deadline=min(读取业务截止,now+3)；QUERY_DONE后恢复读取业务截止。子进程每条SQL前后也检查原期限和自身峰值；同步C查询阻塞由父超时/取消后terminate/kill/wait保障，不新增线程。收到RESULT不算成功，必须唯一DONE、EOF、rc0、已wait及峰值通过。
9. DuckDB在finally逐项关闭，关闭成功、文件前后核对和查询全部成功后才发RESULT；关闭失败保留原错、整轮失败。payload固定为marketRows/calendarRows/fileCount/fileBytes/calendarBytes/connectionClosed，rows分别是六/三项标量行，日期ISO、其他值原类型、connectionClosed严格True。父以日期严格ISO往返恢复date，再做专项固定字段/日历校验及纯_points；检查922/1394/922、日期/15点完成时间及H≤0.0021，原float（含负零）不变。所有读取、成功通信及父校验必须沿同一readWorkDeadline=min(readDeadline-0.5,原work_deadline)；readDeadline最后0.5秒只供关闭/终止/回收，不在该时段继续业务校验，也不另开8秒。父入/出均预算检查，错误或取消不进入任何算法。
10. 读取进程与Git、两算法worker共用原合计峰值与清理。连接/业务行只RAM，不保存恢复文件；失败不自动重试、不走PG或其他来源。完整正式比较仍须另外执行，本轮仅一次read_input真实验收。

## 4. 固定版本模块与进程启动

### 4.1 原源码取数与装载

历史模块全名按顺序为：产品包内types→spec→snapshot_validation→calculator，再研究包内r4_reference_trial→r4_observation→r4_comparison_records→r4_comparison。当前只取当前提交的前4个产品模块。

产品包全名为`src.biz.services.wealth.market.index_detail_xxm`；研究包为`scripts.research.index_market.xxm`。名单由Spec提供，不接受外部路径/提交参数。通过一个受控`git cat-file --batch`按12个固定`提交:路径`读取；解析blob类型、声明长度、结束换行及总量，missing/非blob/非法UTF-8/多余正文均拒绝。Git协议中对象编号仅用于解析，不作源码SHA保护。读取/回收遵守§5—6同一管道和资源规则，不解压旧目录。

`run_worker`只启动`[现有解释器, '-I', '-S', '-B', 专项r4_history_worker.py绝对路径]`，shell=False、二进制三管道、bufsize=0、close_fds=True、env={}。worker仅导入标准库；-I不从当前目录/用户包找代码，-S不执行site，-B不写pyc。获准的新worker文件及解释器/标准库的启动读取允许，固定旧/新算法源码只经请求传入RAM。

上述-I -S -B及空环境用于计算worker；本地读取进程按§3.1使用-I -B及空环境。Git使用固定`/usr/bin/git`，环境只从当前进程继承已有的`HOME/TMPDIR/PATH`三项，不传`GIT_*`、数据库凭据或其余变量；不新设配置、不改Git路径和2秒限制。Apple的Git入口在完全空环境下可能调用开发工具并警告，禁止把worker的空环境额外套用到Git。该最小环境仍须通过无异常stderr、预算和无后代检查，否则停止，不消音警告或自行更换路径。

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

本机Darwin的resource ru_maxrss沿当前`_memory_bytes`口径直接为字节，不乘1024；不支持的平台在读数据前拒绝。新父进程只拥有登记过的Git/本地读取/计算子进程，任意时刻最多一个活动子进程且无后代，不在同进程兼做其他任务。

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

读取阶段异常由父终止并回收本次LOCAL_INPUT进程，正常读取由其finally关闭DuckDB；均不得绕过0.5秒收尾，其他阶段无活动读取连接。work_deadline后不再启动业务，原deadline的最后0.5秒只供清理；不把清理开销留到成功返回之后。

保留首个业务/取消异常；清理异常只附固定阶段和异常类型，不用finally的新异常覆盖原错。不能确认回收或清理超时属于本轮失败，报告超限及退出未确认，继续仅对本次句柄做终止/回收处理，不放行新工作、不声称20秒验收通过。不自动重试，不返回旧组结果充新组，不留下恢复文件/长期进程。专项不得使用hook保证退出。

关闭stdin、终止/等待进程、关闭其余各管道及登记回收必须分别尝试；任一close抛错都不能跳过后续动作。内部管道入口对已登记进程的错误协议或请求检查也必须位于同一finally保护内，不能因错误输入发生得早就漏回收。本地读取进程的清理截止为min(readDeadline,原deadline)，其0.5秒预留不能扩成原总时限剩余全部时间；回收后恢复总预算，父输入校验仍受readWorkDeadline约束。

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

metrics记录唯一t0后的各阶段耗时、parentPeak、最高子峰值、最终combinedPeakUpper、三组step数、读取次数、两次worker正文及报告字节、所有子进程已回收。结果和reportText一起测最终字节，reportText已含于JSON时不能又重复相加；旧/新worker正文另计。资源字段更新使最终候选大小变化时，最多5轮核字节和峰值。每轮完整编码、上限及资源检查后，以最新实测parentPeak/highestChildPeak/combinedPeakUpper及size回填metrics；这四项均是非负整数，只有逐项十进制位数与本轮编码时相同，才证明回填不改变严格JSON的字节数并可返回。位数变化必须继续原有限轮次，5轮仍无法证明则失败。不能要求重复编码前后峰值数值完全不增长，也不能保留过期峰值或省略预算检查。结果和报告先准备并check，最后一次校验后只返回已准备对象，不在返回后再编码或清理可能失败的资源。

报告正文只生成一次；先完成一次完整候选编码并检查内存，再记录elapsedSeconds（截至该准备完成时的实测耗时）。后续最多5轮只回填结果字节及新增峰值，不逐轮重写计时或生成整份报告，避免检查对象持续变化；这些最终编码/核验开销仍受同一20秒截止约束，不从预算中排除。读取计数来自实际调用次数，合成规模未调用读取器时必须为0，不能写死为1冒充真实读取。

## 8. 逐项测试设计与验收

四份专项tests分别对comparison/lake/worker/records负责，输入及预期独立于待测实现。源码真实生产者为两个固定提交；普通小样本的实际进程测试与替身测试分别报告，替身不冒充进程隔离通过。

| 编号 | 输入/故意错误 | 必须断言 |
|---|---|---|
| HC01 | 固定8/4模块、工作区同名模块会报错；纯文档新提交/无promisor配置；缺模块/错误版本/核心变化/额外业务import | 正常提交及未设置配置不误拦；正确小样本实际进程成功；不执行工作区模块/包__init__；错误明确拒绝，不补兼容 |
| HC02 | 有限float、-0.0经请求往返；NaN/重复键/bool/错行/重复日期 | 原类型/值/零符号不变；错误拒绝；正常源值不误拦 |
| HC03 | 非法对象/未完成/缺日历日/缺开市行情/1001探测；922合成源 | 六列DATE/DOUBLE、三列BOOLEAN依DG真实生产者合同造临时Parquet；行情及日历各一次、footer另一次；不补值不截断。合成日历不冒充真实SSE验收 |
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
| HC20 | 临时人工Parquet：六列DATE/DOUBLE及日历DATE/BOOLEAN，两个分区含其他指数、额外合法指标列、负零 | 实际DuckDB一次footer+两SELECT成功，只返回目标六/三列，文件内部日期正确，float类型/原值/负零保留；不读真实Lake |
| HC21 | 某一分区日期VARCHAR、close整数/DECIMAL，缺列、重复字段、分区日期不一致、缺文件/日历、符号链接、超文件数/字节 | 批量footer和路径检查实际拒绝；不能被多文件隐式CAST掩盖，无远程/Raw兜底，正常额外指标列允许 |
| HC22 | 查询期间替换/修改/新增/删除输入文件；DuckDB查询失败/关闭失败 | 文件集合及前后元数据变化拒绝，不返回部分结果；正常稳定文件通过，关闭发生在RESULT之前 |
| HC23 | READ单独消息：错误身份/PID/次序/超限/缺DONE/rc非0；SQL阻塞、结果后不退出、反复取消 | 原3秒/8秒/20秒各自沿用；父及时终止并回收，只处理本次PID，峰值计入合计，错误不启动算法 |
| HC24 | import/父进程PG Settings App访问失败探针；独立临时Parquet内部读取和本轮真实read_input | 导入无读取，不进入PG/App/DG，不安装/写文件/新CLI；真实只核922/1394/922、来源/耗时/峰值/退出，未调用算法，不声称三组或旧基准通过 |
| HC25 | 每轮编码后峰值增长、指标十进制位数变化、持续五轮变化及原超限/过期 | 同位数回填的最终字节长度与独立JSON编码相等、峰值为最后检查读数；跨位数必须再核，仍最多5轮，不绕时间/256MiB/16MiB |
| HC26 | 全新进程拒绝App/Settings/PG/DG导入后运行完整父校验；未完成日线 | 修前抓住query_service的真实间接依赖，修后原六/三列人工完整输入正常；未收盘仍拒绝，不预导入禁用模块 |

同时保留正式识别/恢复/输入及P3第2步定向回归，不运行旧研究全目录或待清退runner。不用旧结果生成新规则expected，不改现有测试预期或增加skip/xfail。根三份架构和新研究依赖/文档检查必跑；每组60秒，超时停止，不安装。

## 9. 实施门禁与本轮停点

开发前先审计本LLD及方案的一致性，核当前固定提交、模块、保护文件和工作区差异；必须取得专项开发授权。先实现独立字面验证和进程/失败路径，再做922合成规模及独立代码审计，最后获得明确执行授权后只读一次真实区间。不能因文档提交或人工通过而自动重放。

真实成功验收必须含：三组输入相同、旧基准复现、关联/差异完整、资源/回收及保护范围证据；独立审阅者只审同次返回，不重复读Lake/重算。算法待核项保留交管理员review，不自动改产品。源行情/源码/完整账本只RAM，文档可记录摘要和差异说明，不生成结果目录、JSON或恢复文件。

第一批只完成专项工具、人工测试和独立代码审计；交付时P3第3步、真实对比、产品400ms/浏览器及P5清退均未执行。人工验收不能记成真实旧基准已复现，第二批实际执行另见§13。

## 10. 资料与证据边界

已使用CodeGraph核读取/会话/校验/计算调用；对固定Git源码补核加载顺序、旧Wave及旧/新记录合同。使用现有Python3.13.5和本机Git；本批只在人工输入下装载算法，未读取真实行情。

通过Context7查阅[Python subprocess](https://github.com/python/cpython/blob/v3.13.9/Doc/library/subprocess.rst)、[selectors](https://github.com/python/cpython/blob/v3.13.9/Doc/library/selectors.rst)、[resource](https://github.com/python/cpython/blob/v3.13.9/Doc/library/resource.rst)官方资料。实际API语义仍以现解释器和有界人工测试核验；文档链接或静态审计不代替进程通信、预算或真实来源已通过。

文档阶段提交后按通信退出、资源预算、版本输入及结果含义分工独立审计。发现并补齐清理不能重复调用取消检查、完整消息之间才能发送资源/错误消息两处要求；同时明确HC04替身边界及changes字段名。修订通过后按本设计实施第一批，人工执行及代码审计证据见§11；真实资源及旧基准复现仍须第二批验收。

## 11. 第一批实现对账及独立验收（2026-10-30）

本节是工具及人工测试的实际证据。人工用例已按下表执行，真实922根基准及真实资源验收仍未执行。没有以人工旧计数替代真实30/17/12/7、24/13/254的复现。

### 11.1 硬口径与落地位置

| 要求 | 实际代码 | 对应测试证据 |
|---|---|---|
| 固定Spec、12段Git源码只在RAM、正式核心保护、先拒绝partial再取对象 | [comparison](../../scripts/research/index_market/xxm/r4_history_comparison.py)的HistoryComparisonSpec、_preflight_git、read_git_sources | comparison测试HC01，缺模块/错范围/不安全仓库正常与反例；worker真实固定模块字面样本 |
| 六列/三列真实查询合同、原float、922/1394/922、只读关闭、外层及原8秒 | comparison._read_input_async/read_input，复用原Query/Session/normalizer/_points | HC02/03以真实SQL投影及人工行检查各查询一次、正向原值、类型/日期/缺日/超限/H关系拒绝，错误时关闭 |
| 完整消息、并行读写三管道、先回收旧组、身份/Spec及自身规则hash核对 | comparison._pump_process/_WorkerFrames/run_worker，[worker](../../scripts/research/index_market/xxm/r4_history_worker.py)的validate_request/_Runtime | HC04/05/06；大于管道容量的独立测试进程、半包/错误消息/错PID/RESULT后取消；两实际worker人工联调 |
| 单一20秒、合计峰值、16MiB及最终核验；取消不打断清理 | ResearchBudget/_cleanup_process/_finish_result及worker资源报告 | HC07—12/18，分别低于256但合计超限、回收后更高峰、编码后过期、控制/结果超限、重复取消、close抛错、0秒清理反例 |
| 原算法不改，CURRENT单只逐根；旧资源观察原值及finally恢复 | worker._calculate/_observe_old_memory，固定源码原文装载 | HC09；开关包装业务事实不变、成功/失败原函数恢复；独立手写状态和事件预期 |
| 组内关联、旧Wave日期、新旧结构含义、日期差异和依据 | [records](../../scripts/research/index_market/xxm/r4_history_records.py)的validate_baseline/compare_fact_groups/format_report | HC13—17，旧WAITING、新回钝化、形成并锁死、同标签异参照、旧池移除仍查日期、同日多候选/跨日不强配、悬挂/未来/终态回退拒绝 |
| 无读取/算法/产品副作用，不落盘、不恢复旧文件、无新CLI | worker仅stdlib和固定模块；读取器惰性导入；入口无自动执行 | HC19源码/实际进程检查；测试探针对仓库内外文件读、写、socket、子进程、数据库使用不同拒绝类型，正常固定模块仍通过 |

测试只新增[test_xxm_r4_history_comparison.py](../../scripts/research/index_market/tests/test_xxm_r4_history_comparison.py)、[test_xxm_r4_history_worker.py](../../scripts/research/index_market/tests/test_xxm_r4_history_worker.py)、[test_xxm_r4_history_records.py](../../scripts/research/index_market/tests/test_xxm_r4_history_records.py)，没有修改既有测试预期。

### 11.2 实际执行与结果

全部使用现有解释器、禁用pytest自动插件和缓存、-B不写字节码；每组均未超过60秒：

| 分组 | 本次结果 |
|---|---|
| 三份专项人工测试，含922合成新父进程 | 138 passed / 3.40秒 |
| 正式规则/恢复/输入与通用恢复四文件 | 1138 passed / 1.87秒 |
| P3第2步预测与数学两文件 | 154 passed / 1.06秒 |
| 原calculator七个CURRENT_CORE_NODES，未运行旧冻结节点 | 19 passed / 0.08秒 |
| 根三份架构检查 | 16 passed / 12.72秒 |

HC18合成同一次结果：准备完成时0.473622秒；父峰75,710,464字节、最高子峰70,778,880字节、保守合计146,489,344字节。三组各922次step，旧/新worker正文1,886,422和652,118字节，最终对象含报告4,190,902字节，合计6,729,442字节。最终核验继续使用原deadline，所有本次进程已wait回收，实际行情/日历读取0次。仅证明本人工规模，未冒充真实SSE、真实读取或真实报告成绩。

### 11.3 审计发现与修复

独立审阅按未承担对应实现的范围分工：输入及保护/父退出、结果语义、worker装载与通信。发现的问题均已修正：

1. Git错误套用worker空环境，触发Apple工具警告：先细化原§4.1，再仅继承HOME/TMPDIR/PATH，固定路径/2秒不变；一次有界只读正常0.0208秒、rc0、stderr0，补两种环境的反例检查。
2. partial检查曾晚于固定对象diff；管道close错误会跳回收；内部早期错误请求会绕finally：三个独立反例先失败，再修正顺序及清理，最终专项组通过。
3. 最终每轮重建大报告和计时导致候选持续变化：报告仅一次、初次编码后冻结计时、最多5轮仅核字节和新增峰，仍共用原20秒；没有增轮、过滤记录或放宽预算。
4. 父返回身份补严bool计数、实际Spec与自身规则hash；规则hash核对不是源码SHA保护。
5. HC19原探针只拦仓库内读取，补齐外部读取及六个精确拒绝反例，未增加运行时安全框架或产品约束。

审计核对通过，未发现剩余第一批阻塞。254天基准使用固定旧比较器已计算的原summary，对照原§16独立预期；父不另复制旧比较政策重算。CodeGraph explore已覆盖原读取/校验/核心入口及消费者，开发后sync/status完成；新研究不进入任何产品调用链，不新增跨域依赖。

本轮未调用真实run_historical_comparison、未读DB/Lake/真实行情、未保存行情/旧源码/完整账本、未改正式四核心及Spec/预测/API/页面/已有测试，未创建分支/worktree、安装、提交、推送或部署。第二批仍须按§9独立获准后执行一次真实区间及旧基准检查，本批到此停止。

## 12. 第二批首次正式执行约定（历史记录，2026-10-30）

管理员已明确授权先提交第一批，再执行第二批并交完整报告。第一批9文件提交0434dd06，未推送。§11的未读取/未提交是第一批交付时点事实；第二批现按本节推进，不重复第一批测试，不改算法或入口。

执行目标、固定参数、代码依据、输入合同、工作区保护、配置/读写和失败预算均复用§1—9：新父进程仅调用一次run_historical_comparison，严格按§3顺序运行；网络只用于其已有专用只读会话的指定两次查询，不执行其他查询/全局读/写入，不启动App。源身份为core_serving.index_factor_pro六列及SSE三列；累计20秒/父子256MiB/16MiB均不放宽，清理在同次预算内。任一检查失败即停止本轮，不能自动重试或绕过旧基准开始新组。

调用完成后只读检查同次返回的metadata/baselineCheck/summary/differenceDays/metrics/reportText，不重建计算器、不调用format_report再生成报告，不重新读取行情。检查全部差异日期有序唯一、标签数量与参照差异分开、三组参照及各自DIF日期完整、旧等待/历史撤销与新锁死分开、具体条件和待核原因保留。独立审阅者只读这些同次结果；原完整结果只留RAM，结束释放，不存JSON/行情/账本或恢复文件。持久记录仅为本方案/本LLD中的人可读摘要和差异说明。

若失败，汇报首个失败阶段、异常类型和已执行范围，保留原错，不输出DSN/SQL/凭据，不把旧组或部分比较宣称成功；完成本次句柄回收后停止等待review。正式产品四核心、Spec、预测、API/前端及其他工作区修改须保持；后续产品任务不因本轮执行自动启动。

## 13. 第二批单次失败证据与停点（2026-10-30）

已按§12只调用一次真实入口，没有修改或替换读取/计算函数。失败证据如下，不包含源行情、SQL、凭据或任何部分成功结果：

| 字段 | 实际值 |
|---|---|
| status / errorType / stage | FAILED / DailyWaveBudgetExceeded / READ |
| 外层实测至失败 | 3.876177500002086秒 |
| marketReads / calendarReads | 1 / 0；前者是调用次数，不能解释为取得922根 |
| childrenReaped | true；新独立父进程随后退出1 |
| 历史/正式计算 | 均未开始；validate_baseline/compare_fact_groups/_finish_result未调用 |
| 成功结果及完整差异 | 未生成；不以§11人工样本或旧§16报告补成成功结果 |
| 实际时限 | 原query_seconds=3、calculation_seconds=8及外层20秒均未修改 |

异常调用位置已核对：`run_historical_comparison:685 → read_input:549 → _read_input_async:509 → DailyWaveQuery.load_main_window:33 → DailyWaveReadSession.execute_read:170 → await_read_io:101`。最后一处是当前时间超过操作deadline时抛出原异常，不是人工夹具、不涉及r4规则判断。execute_read:166—169的时限设置已完成，失败在170行实际SELECT及取回等待，不是尚未连接。

`await_read_io`异常分支调用原_abort，尝试原始连接关闭及任务取消/回收；只读上下文__aexit__继续逐项关闭/释放并进入closed。这里只核实际走到的异常路径和既有代码，不宣称另查活动连接验证过服务端状态；本轮没有增加任何诊断SQL。Git本次子进程均已回收，无旧/新计算子进程启动。

按§6.3及§12，失败后已停止、不自动重试、不重算或放宽预算；源数据、旧基准、实际合计内存/结果大小及三组差异验收均未完成。完整执行失败报告见专项方案§13。首次失败后未重试；管理员随后批准改本地读取，当前代码与验收依据为§3.1/§14；不再开展远程诊断，不改变算法。

未参与执行的审阅者已只读复核该异常调用路径、字段含义、提交范围及报告，确认无过度声称；未另读DB或运行计算。失败报告核对通过仅表示记录准确，不表示第二批执行或验收通过。

## 14. 本地读取修正执行边界（2026-10-30）

管理员已批准先全面修改本方案/LLD读取设计，再按§3.1实施；首批PG路径和§12—13保留为历史执行证据，不再指导新读取。仅专项comparison、读取新文件、对应测试、README及两文档可改；正式算法四核心、产品Query/Session/默认Spec、两个计算worker的规则、records比较含义及旧预期不变。

开发前已用CodeGraph追comparison→原Query/Session/normalize/validate_calendar/_points→worker/records，并核DG paths、idx_factor_pro合同及纯转换writer。正式本地物理核验已确认922行情文件16,996,418字节，日历89,590字节；DATE/DOUBLE/BOOLEAN及922/1394/922、日期集合及H关系齐备。当前根.venv已有DuckDB和PyArrow；不新增依赖，不启动DG，不import orchestrator；读取固定字段合同采用已核实本地副本。

先实现HC20—24真实临时Parquet/父进程监督测试，再保留HC01—19和根架构/正式核心定向回归，最后仅调用一次read_input做有界真实读取验收。不调用run_historical_comparison、run_worker、validate_baseline或三组算法；不生成对比报告、不提交/推送/部署。所有测试每组≤60秒，真实读取仍在原8秒内且合计20秒/256MiB，不放宽上限；失败即停止说明，不自动重试。

实施完成后在本节补实际代码/测试/真实读取/独立审计证据，明确未重跑三组对比；不把上一轮0.574秒只读核验当新实现成绩。

### 14.1 本轮验收发现的报告收尾问题及最小修正

HC18独立922根人工规模暴露既有问题：JSON字节已为4,190,900稳定，但每次完整编码会抬高父进程累计内存峰值，原_finish_result要求编码前后combinedPeakUpper相等，导致未超256MiB仍5轮失败。该问题在同一专项函数内修正，不涉及识别/源行情/算法worker或策略。

编码顺序保持：报告只生成一次→初次完整编码→固定准备耗时→最多5轮。每轮先把当前指标写入metrics、完整严格JSON编码得size→释放编码缓冲→预算/字节检查并读取最新峰值→对parentPeak/highestChildPeak/combinedPeakUpper/finalResultBytes计算更新值。仅在这四个非负整数的新旧十进制位数逐项相等时，回填后字节数必与刚编码相等，允许返回。否则回填并继续，不增加轮数。该证明只用于这四个无转义纯数字字段，不能用于文本、float或任意对象；各阶段耗时/业务事实不在循环改动。

对应新增HC25：模拟每次完整编码后峰值增长但未超限，旧函数5轮失败、新函数必须成功且metrics均为最新峰值、finalResultBytes与独立标准json编码长度一致；再测99999999→100000000的位数变化必须多检查一轮，超256MiB仍拒绝，5轮始终跨位数仍失败。不能为了此用例调预算、改原HC18或使用源码生成expected。

测试分两组进程运行：comparison/worker/records原三份（含原HC18），以及lake的真实临时Parquet测试。PyArrow/DuckDB在同一个pytest宿主中的累计峰值不能混作原进程预算的业务失败；分组不修改任何资源断言或排除失败测试。正式识别1138及根架构16已通过；全部最终成绩完成后再登记。

### 14.2 真实读取首次验收暴露的间接Settings依赖

首次本地验收的读取子进程已取得数据并退出，父校验时query_service→query→IndexFactorPro→Dataset registry→definitions._builder间接导入Settings，被新进程禁止导入检查拒绝；未发生远程查询、算法计算或成功返回。不能以只删除显式PG调用宣称通过。此处按原固定源合同修正，不修改产品query_service或扩大产品重构。

父校验只import纯DailyWaveBudget/DEFAULT_SPEC/_points。六列标量中对象必须000001.SH，ISO经严格往返还原DATE；四数必须type float、finite、close>0；同一次上海when核每根15:00已完成。以原float的str构成七字段验证输入供_points使用，H≤0.0021和日期升序/唯一/范围检查仍由_points完成；不得把该字符串/Decimal作为计算原值。日历每行严格三项、SSE、DATE、bool，按start至end逐日一项且无缺重复；open日期升序列表必须与行情日期列表全等。不补值、不按任意集合静默去重。

新增HC26：在全新进程中先拒绝import src.app、src.foundation.config、psycopg、orchestrator，再以独立人工六/三列payload运行完整父验证。修前须因上述间接Settings导入失败，修后成功；同步保留源类型/日期/H/缺日负例，不允许通过移除拦截器、预导入模块或放宽预期通过。

每个已修正读取版本只执行一次有界真实验收；未改代码的失败不能自动重试。第一次失败保留，修正完成且人工反例通过后补一次本地read_input验收，仍不运行三组比较。该补验属于管理员已授权的读取实现验收，不改变固定范围、原预算或算法，不把失败记录覆盖为成功。

## 15. 本地读取修正的实际交付及独立验收（2026-10-30）

### 15.1 代码与边界对账

| 硬口径 | 代码 | 证据 |
|---|---|---|
| 单一固定Silver来源、只投影六/三列、不走PG/Settings/App/DG | r4_history_lake.LocalLakeSpec/discover_files/read_tables；comparison._read_local_payload/_validate_local_input | HC20—24/26，实际源字段类型及全新父进程禁止导入检查 |
| 批量footer核每文件类型、原值/负零、分区日期和文件前后变化 | lake._validate_schemas/read_tables/discover_files | 41项真实临时Parquet测试；无隐式CAST或补值 |
| 同一8秒读取含父校验、每SQL3秒、20秒及0.5秒收尾，取消/异常回收 | comparison._LakeFrames/_pump_process/_cleanup_process/ResearchBudget | HC23真实人工管道阻塞/半帧/取消/迟退；原通信与回收反例保留 |
| 922/1394/922、上海15点已完成、日历逐日匹配及原H≤0.0021 | comparison._validate_local_input及纯_points | HC02/03/26人工正反例和本次真实只读验收 |
| 报告最后检查读数与字节准确，不要求峰值停止增长 | comparison._finish_result | HC25修前2失败1通过、修后3通过；原HC18未改并通过 |
| 识别规则、两算法worker及比较含义不改 | worker/records及正式四核心无改动 | 正式核心对c6a845fe3无差异；既有回归全部通过 |

### 15.2 测试与首次失败的如实记录

临时Parquet与原三份专项测试在两个新pytest进程分组运行，保留全部用例和原预算断言；不把PyArrow测试宿主的累计峰值混入原比较程序。最终结果：

| 分组 | 结果 |
|---|---|
| comparison/worker/records三份，含原HC18及HC25/26 | 191 passed / 7.08秒 |
| lake真实临时Parquet | 41 passed / 0.89秒 |
| 正式识别/恢复/输入及通用恢复 | 1138 passed / 1.92秒 |
| P3第2步及数学 | 154 passed / 1.08秒 |
| 原七个CURRENT_CORE_NODES | 19 passed / 0.08秒 |
| 根三份架构 | 16 passed / 13.12秒 |

首次合并人工验收出现2失败/225通过：原HC18错误要求峰值停止增长，以及临时Parquet导入抬高pytest宿主峰值；按§14.1修正前者并将两类测试分进程，未放宽资源限制/检查轮次或修改原HC18预期。首次真实本地验收在父query_service间接导入Settings时被禁止导入检查拒绝；子读取已结束，未发生远程查询或任何三组计算。新增HC26先复现该失败，再按§14.2去掉间接依赖，补验仅执行一次，结果如下。未把失败抹成首次通过。

### 15.3 最终真实只读验收

只调用read_input，未调用run_historical_comparison、read_git_sources、run_worker、旧基准或任何识别step。全新父进程禁止导入src.app、src.foundation、src.biz.queries、sqlalchemy、psycopg、orchestrator，实际通过；读取子进程自身只使用标准库和已安装DuckDB。source/行数、首末独立样本、float类型及全部退出检查通过。

| 项目 | 本次实测 |
|---|---|
| 来源 | local-dg-silver；唯一正式根/固定两个Silver位置，无远程/Raw兜底 |
| 范围/行情 | 000001.SH day，2023-01-03—2026-10-27，922根 |
| SSE日历 | 1394自然日、922开市日；与全部行情日期逐日一致 |
| 物理文件 | 行情922文件/16,996,418字节；日历1文件/89,590字节 |
| 查询尝试 | schemaReads=1，marketReads=1，calendarReads=1；没有重复行情/日历SELECT |
| 总读取及父校验耗时 | 1.125462秒，包含启动/发现文件/批量footer/两SELECT/前后检查/关闭/通信/父输入校验；在同一7.5秒业务截止及8秒读取内 |
| 父/最高子峰值 | 27,246,592 / 190,480,384字节 |
| 保守合计峰值 | 217,726,976字节（约207.64MiB），低于原256MiB；DuckDB内存参数128MiB不等于整个进程RSS上限 |
| 读取子进程/退出 | 1个，rc0、已wait回收，三管道均关闭，active为空 |
| 算法执行 | 0 step，未启动任何算法worker或三组比较，未复现真实旧基准 |
| 读写及保存 | 未访问远程、未写DB/Lake/DG、未安装/配置变更；行情/中间结果仅RAM，不保存恢复文件或完整账本 |

该成绩只证明新本地读取通过，不是完整真实三组比较的20秒/256MiB/16MiB验收，也不替代旧基准复现。后续真实比较必须继续原完整预算，不能以本节只读峰值或原合成规模推定完整链路通过。

### 15.4 独立审计与停点

已按未承担实现的范围独立核对本地来源、footer/分区/前后文件、原值及日历、父子时限/取消/通信/回收、合计内存及两处验收修正；最终无剩余阻塞。CodeGraph explore/impact覆盖专项读取→原Query/Session及纯校验→worker/records；同名read_input的其他主题结果逐项排除，实际产品入口无消费者变化。开发后sync完成，status及最终文档/差异检查在交付前核对。

本批限定修改两专项文档、README、comparison及其测试，新增lake及其测试，共7个文件；原工作区其他修改均保留，未暂存/提交/推送/部署。至此停止，未自动重跑正式三组对比、推进P3第3步或调整识别规则。
