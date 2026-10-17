# 25股修复LLD v1：R3验收记录与R4正式修复设计

更新：2026-10-17。R3代码及隔离验收提交ddea22236，事实与证据保留在§1—§13。§14—§22是本次补齐的R4实现及正式执行设计，待review、未开发、未正式执行；不能把设计写成现有能力。本轮仅改原方案和本文，不写正式staging/Lake、不freeze、不操作事件、sensor、Prod或serving，旧现场/hash保留。

## 1. 整改前实现、根因与消费者

| 代码 | 整改前已核实行为 | R3落点 |
| --- | --- | --- |
| bootstrap/stock_adj_factor_history_repair.py | FactorRepairScope、approved_repair_asset_keys、repair_price_dates、指纹闭包与冻结合同 | 业务范围/公式不改；新runtime纳入实现闭包，验证结论及索引交给上下文复用 |
| _execution.py:load_repair_plan/execute_repair_candidates | 每阶段重新加载/全输入hash，逐重放/文件批次启动worker；轮询和COPY调用全目录扫描 | 一次准入、顺序长驻worker、增量计量和真实取消 |
| _candidates.py:RepairCandidateInputs/read_repair_candidate_record/build_repair_target_candidate | 每target重建输入字典、重复hash/投影校验；已有完成文件仍跑业务SQL，audit构造replacement重新计算 | 共享身份/投影索引；先验证完成证据，复用后不再算价/扫描完整候选 |
| _indicators.py:replay_indicator_task/_persist_fragment | 先计算公式，后看receipt；完成片段再执行query双向EXCEPT；候选构建反复遍历所有task | 先恢复有效片段/任务，再算未完成后缀；结果/state共用重放、目标反向索引 |
| _cli.py | inspect会请求源并做完整库存；build/audit按既有phase/selection执行 | 本轮不运行inspect/freezer；公开动作/参数不改，audit改用已封存证据而非第二次重算 |

CodeGraph callers/impact已核对协调器、重放及直接测试，合同与候选链另以当前源码核对；图中动态import/路径调用缺项由源码补核。前一轮正式只读assetNodes确认31资产均已加载，范围外消费者仅prod_core_stock_daily_qfq_nineturn。没有前端/API或跨子系统代码变更。

旧profile实测：指标525个worker，目录清点17,340次/7,817.42秒，占worker时间92.2%；SQL94.21秒、fsync1.68秒。停止后单次目录扫描约0.65—0.72秒、计划加载约0.73—0.75秒。旧指标阶段9,212.99秒是历史夹具实测，不是正式市场ETA；不再用旧双全链或简单百分比外推作为验收目标。

<a id="indicator-repair-audit-20261012"></a>
## 2. 本次固定业务范围和真实输入

对象及2,489键逐股日期唯一沿总方案§2；31资产精确为：

| asset key | 数量/路径布局 | 写入边界 |
| --- | --- | --- |
| raw_tushare_adj_factor、silver_adj_factor | 2；按trade_date共享文件 | 只替换批准因子键，Silver沿当前CNY/list_status=L和合法上市区间 |
| gold_stock_daily_qfq | 1；按trade_date共享文件 | 七价字段；实际因子影响日及实际后继行，量额不变；688689从2021-01-27统一日线基准 |
| gold_stk_mins_qfq_{1,5,15,30,60,90,120}m | 7；freq/ts_code/year | 仅该股实际因子影响日期，标准K线输入映射不改 |
| gold_stock_daily_trend_channel、gold_stock_daily_trend_channel_state | 2；按trade_date共享文件 | 原核、上市初始化/停牌carry、真实上一expected state，至独立已有末端 |
| gold_stock_daily_qfq_nineturn | 1；按trade_date共享文件 | 完整历史九转及4根close context，输出受影响范围 |
| gold_stk_mins_qfq_macd_kdj_{1,5,15,30,60,90,120}m及对应_state_资产 | 14；结果按股/年，state按日共享 | 原参数、上一expected日seed、8根context、1024-bar核，结果/state分开裁输出 |
| gold_stk_mins_qfq_nineturn_{30,60,90,120}m | 4；freq/trade_date共享 | 完整历史计数，不从截断窗口重新起算、计数可超过9 |

路径和schema沿LAKE_ASSET_CATALOG、defs/paths.py和现行run_contracts/asset_column_schemas.py，不重定义一套。正式只读依赖为silver_stock_daily、silver_stk_mins_1/5/30/60m、silver_stock_basic、silver_stock_lifecycle、silver_trade_calendar，以及必要的旧价格/seed/context。范围外输入不成为写入目标；候选优先或已验证no-op，禁止退回旧正式价格。

25股均当前CNY上市；775个股票/资产组合当前末端已核实：日线及日指标/state为2026-10-16；分钟行情/结果及state最后行情为当天15:00。依然分别记录29下游的725个端点，禁止默认把price tail当result/state tail，或补原不存在键。

688689早期日线基准1.054、当前1.0597，保留其日线全历史扩展；其余24股100有效样本基准一致，仅支持不新增扩围，不升级为全历史正确结论。R3不重做这两项审计，也不因21个预选日期没有行情追加完整性排查。

周/月Raw、Silver、未复权行情和基础事实均不改。prod_core_stock_daily_qfq_nineturn的sensor当前RUNNING，只监听gold_stock_daily_qfq_nineturn_update_job成功；R3不调用这个job、不伪造普通repair成功run、不写事件或serving。

## 3. 一次准入与运行上下文

以2026-10-17休市、正式输入稳定且截至10月16日为本轮已确认事实。复用总方案§6现有证据，不再请求源、追最新端点、重审基准/上市池/日历、遍历正式库存或周期性hash正式数据。代码变化只影响对应实现与隔离验收证据，不触发对不变正式数据重新审计。

新增本专项内部stock_adj_factor_history_repair_runtime.py，承载一个运行上下文，不建全局服务、数据库表或长期账本。身份键为plan_hash、实现指纹闭包、规则版本及本次selection；派生缓存还带原件/候选/no-op模式、overlay、seed/context及前序receipt。启动时校验计划/范围/请求，建立source/target/unit/task反向索引。新runtime纳入repair_implementation_files，旧hash不改。

runtime只依赖专项合同及现有纯IO/身份能力，由execution/candidates/indicators调用；不能反向import这三个调用模块。业务证明由原候选/指标模块生成并交给上下文管理，避免为共享缓存引入循环依赖或移动公式核。

输入只在本次隔离执行首次实际使用时取得与计划一致的FileIdentity强证据，之后运行内直接复用，不按target/轮询/phase重复核验。未使用的全市场校验输入不预先全量hash；确属原blocking必要输入时按批次首次使用并缓存。已有合法封存证据可以直接建立其输入/输出绑定，不靠一个validated布尔值放行。

同一协调器内factor→price→indicator共享上下文；阶段切换不重做范围、库存或已完成输入核验。CLI另起进程时只恢复指定计划和其已有记录，不重新审计市场；局部必需输出身份按恢复表验证一次。禁止在计划加载、子进程入口、每target三处分别做相同全量验证。

父进程的准入结论绑定原plan/hash、实现闭包和selection，随init携带有界摘要；worker不再自行执行完整load_repair_plan校验链。跨phase需要的已核实输入/投影/候选由原封存record和receipt恢复为本地索引：验证其完整摘要和计划绑定，不重读已稳定的正式原件。worker只检查本次work涉及的证明闭包，不能每批重建全部记录索引。首次使用且尚无强证据的隔离输入仍验证一次；不为传缓存复制全plan或建立独立缓存库。

## 4. Worker和连接复用

保留现有父进程监护、继承plan锁和顺序执行，默认每个phase复用一个worker与一条configured DuckDB连接；月/年逻辑批次仍是工作单元，不再意味着新建进程。结果/state共用单股/频率重放。活跃股/频率切换后释放其大表/计算缓存，不能把全部历史长期留在Python或DuckDB临时表里。

内部_worker改用有界JSON消息：init绑定plan_path/expected_hash/phase/coordinator_pid/plan_lock_fd；work沿原unit_index/targets或replay_task_index；finish结束该phase。每条消息沿用当前16KiB门禁，工作按既有批次分发，不把全plan/全文件清单塞进消息。子进程解码计划和建本地索引一次，仅核请求子集及父绑定，不重复正式库存和全输入hash。正常回应ready/batch_done/finished为有界摘要；错误沿有界stderr及退出状态交给父进程处理，不另造错误消息协议，也不在stdout累积全量记录。

父进程按每条消息读取输出，不把整个worker生命周期的多条消息累计成16KiB。进度继续沿既有active/checkpoint，不另建状态框架。公开CLI build/audit、--phase、--full、--sample-target及其范围和完成语义保持；生产入口、所有内部worker/test launcher一次迁移，不能保留旧协议或旧扫描路径兜底。

正常的同phase批次共享worker内索引、已核实身份和连接；另一phase新worker从原封存记录接续缓存证据，不重复数据审计。stderr只保留有界诊断，不能随长驻时间无界累积。init就绪、每批结果和finish必须分别确认；EOF/错误/父退出后停止分发，保留已完成记录，不能把缺消息当成功。

进程复用是本次设计选择；小样本应测启动、加载、内存和取消。若实际需要更改此选择，先回写本两文档并说明实测依据，不以资源隔离为由恢复逐文件重复加载。

## 5. 增量空间计量与预留

一次性读取本run既有文件/receipt建立计量，覆盖候选、片段、inputs、JSON及temp；新执行和同一进程内阶段切换只建一次。逐文件记录已包含的路径/字节可直接归并，不为每个缓存/worker重扫目录。已有checkpoint可恢复总量和未结预留；崩溃后只核未结路径，账目缺失/对不上时才允许对本run做一次重建扫描。收尾把完整文件清单和计量合并为一次对账。

写入前预留本unit所需空间，按当前剩余候选额度设置原RLIMIT_FSIZE，按剩余spill额度设置DuckDB max_temp_directory_size；完成后按实际字节结算，失败/取消退回未使用预留并保存已完成记录。候选/临时文件在rename前后只调整所有权和实际增量，不能双计或漏计。小型JSON使用已知payload字节及落盘stat计量。

COPY前保留轻量disk_usage和本unit预留判断，不递归目录；worker轮询只读进度和合并后的RSS，不能调用repair_storage_totals。spill由DuckDB额度约束，不能为了观测spill每秒walk。唯一写者由原plan锁及父监护保证，不新增锁服务或监听器。

总量重建/收尾扫描仍拒绝symlink、目录权限/I/O错误；只容忍已列举文件在原子rename后的lstat FileNotFoundError。未知归属文件或计量不符停止，不删除现场。该保护检查本任务实际产物，不用于假想网络更新或反复确认休市数据未变。

## 6. 完成成果先识别，业务只验证一次

| 状态/边界 | 应做的必要工作 | 不能再做 |
| --- | --- | --- |
| 新片段 | 使用已解析输入、原kernel计算一次，COPY/读回/强身份封存一次 | 为核对行数再次执行完整公式query |
| 已完成片段/任务 | 验plan/task/窗口、seed/context、前序receipt及所绑定输出，恢复其state后跳过 | 先跑kernel再读receipt；已完成query双向重算 |
| 部分完成 | 保留已封存前缀，从最后完成state继续未完成后缀；九转计数/4根context不断 | 从首窗口或年初重新计算 |
| 新完整候选 | 同目标汇集所有25股修改，一次COPY；一次schema/键/范围/保留行及原blocking语义，保存业务证明和record_hash | 按股票分别重写同一共享文件；再算一遍公式证明输出 |
| 已封存候选/no-op | 身份、完整业务证明及覆盖绑定适用时直接复用；no-op保持原件 | 再执行validate_repair_business_file或构造replacement |
| 最终audit | 用既有proof、receipt、输出身份和目标集合汇总完整性；缺证明明确未通过 | 重跑prepare_repair_replacement、指标kernel、COPY或整批业务SQL |

“验证一次”覆盖完整输入/输出与现行blocking语义，不是删check。schema/唯一键/合法范围、源键覆盖、范围外双向EXCEPT ALL、量额不变和文件持久化均有独立意义；对每个新候选或同批集合只做一次。公式、递推、跨年和首期正确性由独立金样本证明。运行记录保存各项结论及绑定，不让validated=true替代完整证明。

完整业务证明写入原record/receipt并纳入record_hash，至少绑定证明版本、plan/实现/规则、asset/unit/目标原件、输出强身份、批准键集合、输入/overlay/seed/context/前序receipt摘要，以及实际schema/键/范围/保留行/原blocking检查结果。缺项或检查不通过不能封存；旧record不得只补一个成功字段升级。行数和变化计数取本次实际物化结果/选行事实，不能再次执行完整公式query来计算expected。

缓存的强证据在同一运行上下文内复用。进程重启只对本次要复用的输出/receipt强身份验证一次并缓存；未知文件、损坏/不完整receipt、错误归属/依赖或未完成记录不能当成功。只重做真正未完成部分，不借“恢复”发起市场或历史完整性重审。旧实现/不同范围的证据不能套用到新计划。

## 7. 持久化、取消和资源边界

正式Lake唯一/Volumes/datasource/data_lake，正式staging唯一/Volumes/datasource/data_lake_staging；R3只用/private/tmp专属临时Lake/run与隔离instance，禁止网络和正式资源访问。保留旧现场，不改旧plan/hash。候选→校验→fsync→原子rename→目录同步→逐文件完成记录沿原实现边界，不引入备份/快照，也不声称多文件整体原子。

复用现有receipt/checkpoints/active/checkpoint.json；必要计量摘要及未结预留写入原checkpoint，不新建长期状态表、缓存库或新的运行账本文件。提交产物在记录前中断时，以已绑定候选/输出身份补记；未知残留拒绝，不重新算已经完成的文件。缺失业务证明不能靠补一个成功标志修复。

这条恢复要求在原逐文件record内落地：候选校验、fsync后，先持久化包含输出强身份、范围及输入依赖的transfer_proof/transfer_hash和commit_pending，再原子rename并补记提交状态。价格候选同时已有完整业务证明；指标候选先保留真实的business_pending，恢复时复用已写文件，只完成尚无持久化证据的blocking校验。批次业务证明必须绑定各目标输出hash；若部分文件已完成登记，同批剩余文件可复用这份完整证明，不能再COPY或重算。没有保存成功证明的检查仍须执行，不补造通过；旧格式或未知残留不能冒充这一状态。不新增记录文件、表或公开动作。

取消在消息/批次、SQL/片段/文件提交边界检查，取消后不领新work。父TERM/KILL后本任务worker退出、锁释放；已完成文件/receipt保留。按实际最后emit时间提前调度，真实可见更新间隔≤30秒；完成量只在封存后增加，不能伪造业务进度。SQL可中断，ETA不可靠就明确不估算。

## 8. 现有配置审计与性能预算

不新增配置。所有工程额度由stock_adj_factor_history_repair.py的RepairBudget或REPAIR_PLAN_MAX_BYTES给出，冻结到新隔离plan；不是env/Settings/业务API参数，运行进度/结案报告展示实际采用值。不得暗套共享DuckDB 16GB默认或周/月Raw临时6GiB。

| 名称/现值 | 消费者及失败处理 |
| --- | --- |
| plan192MiB | load/freeze编码与请求绑定；真实超限拒绝，不静默截断 |
| memory_limit=2GiB、threads=2 | configured DuckDB；所有SQL/COPY显式使用专项settings |
| max_rss=4GiB | 父子合并RSS及worker退出；实测超限受控停止、保留成果 |
| max_spill=2GiB | 增量计量及DuckDB temp上限；不能省门禁或每秒扫temp |
| max_candidate_bytes=10GiB | 写入预留、RLIMIT_FSIZE及完成结算；超限拒绝 |
| max_stock_batch_rows=100000 | 既有单股片段，含8/4根context；不扩成全历史常驻内存 |
| progress_interval=30秒 | 取消/业务进度上限，按实际最后emit提前调度，不放宽 |
| 既有工作批次≤64、消息16KiB | 只约束逻辑批次/单条内部消息，不强制一批一进程或限制整股历史 |

这些额度/批次是已有工程选择，不新增更紧限制。需要调整时给出当前样本/资源测量并回写两文档，不能改旧plan。本轮无新配置来源或运维开关。

本轮开工复用：25股、31资产、725个下游端点、325组单股/族/频率重放意图；实际候选文件数由新隔离夹具目标并集确定，不套用旧1778记录或“328164输入/15743目标”的历史容量测算。正式目标清单及真实全市场体积不在R3启动时重测。

性能验收记录计划解析/校验次数、强hash文件/字节、目录遍历、源扫描/业务验证次数、kernel/COPY、worker/连接数、RSS/spill/实际输出。进程内阶段切换及轮询的目录扫描增量必须0；完成成果恢复的kernel/COPY/业务SQL必须0。新文件只有一次完整验证和一次合并提交；没有新实测前不承诺正式耗时。

## 9. 开发步骤、文件与影响面

| 步骤 | 文件白名单/落地 | 对应小样本与失败边界 |
| --- | --- | --- |
| A 上下文及计量 | 新_runtime.py；_execution.py；合同.py仅实现闭包/上下文验证接入 | 现有plan范围/实现绑定、唯一写者；累积目录只一次建账、预留/结算/崩溃恢复及超额拒绝。问题只定位本unit，不重审正式数据 |
| B 成果复用 | _candidates.py、_indicators.py接统一上下文，移动完成识别、共享投影/依赖索引和证明 | 完成片段/候选0重算；部分完成续后缀；损坏、缺证明、错seed/context/overlay拒绝，不放宽业务结果 |
| C 进程复用 | _execution.py的内部_worker请求、父监护/消息与连接生命周期；直接测试launcher同步 | 同phase多批共用worker/连接，OOM/SQL取消/TERM/KILL无残留，消息仍有界；不能加入公开CLI动作或旧协议兜底 |
| D 验收收尾 | 现有6份专项测试及原两文档，必要直接消费者回归 | 小样本模型通过后固定版本，单条25股链内取消/重启/续跑/汇总；失败只修受影响项，不先重跑完整链 |

现有测试文件为tests/test_stock_adj_factor_history_repair.py、_candidates.py、_execution.py、_indicators.py、_replay.py、_full_chain.py；可新增test_stock_adj_factor_history_repair_runtime.py集中验证运行上下文/计量，不新建长期CLI或治理框架。_cli.py只有实际调用受内部签名迁移影响时才改适配，参数/请求源口径不改。现有公式核、assets/jobs/checks/sensors、catalog/schema/paths、AGENTS、Prod/API/前端均不改。

先用CodeGraph及当前源码核对所有内部request/receipt/函数消费者，同步迁移上述测试；不恢复已清退的源码逐文件权限登记。改动在当前dev-interface，保留原R3未提交改动及其他任务内容，不新建分支/worktree。共享文件差异不明时先报告，不能整文件回滚或整仓提交。

## 10. 正反测试与最终验收

测试以真实生产者/schema及已核对的小样本合同为依据，预期使用独立字面值；故障样本明确标注。禁止访问正式Lake、staging、instance、token/网络/Prod。以下按受影响路径隔离验证，不每个用例请求真实源：

| 检查 | 正向 | 反向/拒绝 |
| --- | --- | --- |
| 范围和端点 | 25股/31资产、688689日线起2021-01-27、末端10月16日/15:00，结果/state分别裁范围 | 空对象变全市场、非25股、无依据扩其他24股全历史、超已有端点/增加原不存在键 |
| 价格与指标 | 原七价/量额、Silver七频映射、正确seed/context、趋势carry、九转连续与跨年字面金样本 | 机械上一交易日、回退旧价格、错seed/缺依赖、截断九转或从年初重置state |
| 一次验证 | 同一完整目标汇集多股只COPY/业务验证一次，范围外保留行相同 | 不可用证据/no-op/半成品冒充成功、篡改其他股票/量额或缺实际blocking条件 |
| 输入/缓存 | 首次强校验后稳定输入及投影/索引复用；后续阶段不重审正式输入 | 第一次准入时错plan/实现/规则/原件、输出同大小/还原mtime篡改、错overlay/前序receipt拒绝；这些故障注入不变成正常流程重复扫描 |
| 预算和目录 | 建账→预留→结算与实际相同，轮询/COPY不全扫；空余预留释放 | 真超额、free-space不足、未知文件、symlink/权限/I/O/记账失配拒绝；原子rename瞬时消失可容忍 |
| 恢复 | 全完成及部分完成后重启，已封存输出身份不变、kernel/COPY/业务SQL=0，只续未完成后缀 | 损坏或不完整receipt、错误归属/候选/seed绑定不能复用，不把旧R3记录接到新hash |
| 进程与取消 | 顺序多批复用worker/连接；新消息协议、真实进度、取消后保留成果/释放锁 | 子进程脱离父进程、取消后领新work、超内存/消息超额/SQL不可取消仍继续均拒绝 |
| audit与收尾 | 复用完整业务证明，目标覆盖/文件事实/预算一次汇总，无新kernel/COPY | 缺目标/缺证明/坏输出不能通过；不靠同一公式第二次全量计算刷绿 |

小样本选最长1m、共享日文件多股、跨年、累计目录与部分完成；可合并在同一夹具中，计数器证明成本模型，不另造全市场数据。修改期间只跑受影响用例；固定实现后一次必要直接回归及相关Ruff，禁止全仓/历史bootstrap默认回归。

最终只跑一条25股全链，在其中中断/重启/续跑；原临时产物保留，通过逐文件proof和字面金样本及未改行证据对账，不再克隆第二份完整正常链或再次重放audit。完成后同ID空操作恢复验证只读证据、0重算。不要求先完成全部R3测试才允许开发A/B/C；缺陷是本阶段要解决的工作。

## 11. 本轮开工审计结论

| 前置项 | 本轮核对结论 |
| --- | --- |
| 目标/边界 | 只做R3代码整改和隔离验收，正式写入、事件/serving、sensor及周/月建设全部排除 |
| 范围/当前端点 | 已有最新只读审计确认25股仍上市、31资产及775组合到10月16日；直接复用，不再查询 |
| 基准范围 | 24股100有效样本未新增混基准证据、688689阳性对照命中；抽样边界明确，不新增“全历史排除一切错误”的开工审计 |
| 消费者与实现落点 | 当前入口/函数及测试已定位；CodeGraph缺项由源码和已有正式依赖图补核，无未确认业务契约/新配置/公开CLI变更 |
| 旧现场和版本 | 两现场仍在，plan hash未改，末端10月13日；正常链749/749但audited/all_chain_ready未通过，取消链130/749；新实现建新隔离plan，不强续 |
| 环境与授权 | 开工审计时现有orchestrator .venv与隔离测试框架可用，当前dev-interface；四个原R3脏文件保留。随后获准执行A—D；未安装套件或操作正式资源 |
| 重复动作 | 计划/输入缓存、预算计量、完成识别、一次业务验证和单条完整链均有具体落点；不会以休市数据可能变化追加审计 |

**开工时结论：可以进入R3代码整改与隔离验收，没有需要先重做市场/因子/基准/完整性审计的前置项。** 原重复开销与未完成验收属于A—D开发内容。后续已先完成小样本成本/恢复验证，再执行一次固定版本全链，结果见§13；正式操作仍未获本轮授权。

<a id="r1-candidate-development-20261014"></a>
<a id="r1-acceptance-fixes-20261014"></a>
<a id="r3-nonredundant-execution-20261015"></a>
<a id="history-repair-execution-design"></a>
<a id="adj-factor-current-listed-migration"></a>
<a id="r0-readonly-audit-20261012"></a>
<a id="r0-source-provenance-20261012"></a>
## 12. 已完成历史与保留现场

R1提交75e86447，R2提交5ef585f9e9abe053db13e214b572a96e0c2ee909；原合同/独立公式/恢复测试保留，历史通过只证明其当时版本，不升级为新runtime验收。2026-10-13因子Silver上市规则迁移已完成，Raw未改，不重复执行；与本25股数值修正分开。原R0的2,489个非舍入差异为本批范围依据，本轮未请求源重审。

旧隔离根/private/tmp/r2-tests-ff4463b7-6810-4070-9847-baf1832e5f84/test_full_25_stock_chain_cance0/，run_id分别0cf90e14-b2d0-407c-b7b7-813595b57bc4和3b98a680-9f5f-4ec2-a48f-ad8188b1026b，plan hash分别1ac8d8238786276c6f2930d994f7f034f5c59ae1419a186828a2c11792a5fd87和94073ce777fcfc6a33cbc1dbf761743212289b9b7845822fed4c57a3f1167240。正常链1,778封存记录/1,491候选，取消链1,159封存/877候选，receipt各1,874；这些仅为保留现场数量，不作为新目标数量。

暂停证据/private/tmp/r3_safe_pause_summary_20261015.json、r3_pause_evidence_20261015.json、r3_pause_preserved_manifest_20261015.json、r3_pause_profile_20261015.json和旧日志保留。暂停时2,848原输入无漂移、进程退出和锁释放；10月17日已核对旧计划/现场仍在及本任务进程0，不再重hash该输入集。本轮新范围和基准证据唯一见总方案§6；临时文件都不是日常/生产依赖。

## 13. 本轮实现与隔离验收对账（2026-10-17）

### 13.1 实现范围与逐项结果

代码白名单为§9的合同、runtime、execution、candidates、indicators共5文件，以及原6份专项测试和新增runtime测试共7文件。合同仅把runtime加入实现指纹闭包；未修改公式、RepairBudget、字段、CLI、assets/jobs/checks/sensors、catalog/schema/paths或Prod消费者。新协议已迁移内部worker及所有直接测试launcher；没有旧协议兜底。

| 已确认要求 | 实现位置 | 正反测试与实际结果 |
| --- | --- | --- |
| 范围、末端及合同不扩大 | execution.load_repair_plan、candidates.repair_target_scope及原合同 | 本轮66项合同测试通过；错误范围、缺目标/依赖、实现漂移、消息超界拒绝；25股链到10月16日/15:00，不改周/月 |
| 首次验证后复用输入/投影 | runtime.RepairRuntime、candidates.RepairCandidateInputs及prepare_repair_replacement | 强hash首次执行、热缓存不重复探测路径，锚点/日期索引每股一次；错误原件、缺依赖、错overlay及同大小/还原mtime损坏在新上下文拒绝；最后缓存调整后12项定向复测通过 |
| 计量不反复扫描 | runtime.RepairStorageLedger、execution.check_repair_storage/bounded_repair_copy | 累积目录预留/实际结算、失败写入/JSON临时文件恢复；空间不足、真超额、symlink、权限/I/O、未知文件（含0字节）拒绝。全链扫描2次，均限本run；文件归属来自计划及task/receipt清单，不靠字节总量掩盖未知产物 |
| 完成成果0重算 | candidates.read_repair_candidate_record/build_repair_target_candidate、indicators.replay_indicator_task/read_indicator_task | 先读完整proof再执行SQL；完成任务不跑kernel，片段数字顺序恢复，部分任务只续后缀；缺证明、坏receipt/候选、错seed/context拒绝；整链证据audit和全完成续跑业务SQL/kernel/COPY=0 |
| 文件提交中断可恢复 | candidates.resume_repair_candidate_transfer、indicators.seal_indicator_batch及原record | rename前/后中断、批次部分登记均复用已写文件；价格0 SQL/COPY补记，指标只完成未封存检查或复用已有完整批次证明。只读reader/audit仍拒绝commit_pending，不能替执行器做写恢复 |
| worker/连接顺序复用 | execution.serve_repair_worker/run_repair_candidate_worker/execute_repair_candidates | 多批次一worker/连接；原父监护、锁和真实RSS拒绝保留。父TERM/KILL、子进程提前退出、OOM/SQL取消、超额输出均隔离验证；取消后worker退出、锁释放，成果保留 |
| 原业务语义及范围外保留 | candidates.validate_repair_business_file、indicators.audit_indicator_batch及原kernel | 七频独立字面金样本、跨年、停牌carry、九转连续、result/state独立末端通过；范围外股票/量额损坏、错前序行/未冻结输入/缺实际检查仍拒绝；未用同一公式第二次全量重算 |
| 单条隔离链与正式边界 | tests/test_stock_adj_factor_history_repair_full_chain.py | 一份新plan内三阶段取消续跑，之后只做proof审计和全完成续跑；隔离guard禁止网络、正式Lake/staging/instance及输入写入，正式操作0，不启动正常日更job或触发serving |

182项必要回归分组通过（runtime/execution/candidates 55；indicators/replay 15；合同66；进程/目录/加载等46）。最后仅调整输入索引复用后，针对受影响路径重跑12项，含2项新增；最终全链再通过1项，去重合计185项。182项不能写成“最终版本重新跑过182项”：未变组件复用本轮证据，末次变更由12项定向复测和最终全链覆盖。Ruff致命错误基线、本次12份Python默认规则、文档完整性及diff空白检查均通过。没有全仓pytest、历史bootstrap或第二条计算链。

CodeGraph已用explore、callers/impact及CLI sync/status核验协调器→worker→候选/重放→runtime和直接测试消费者；动态调用缺项以源码补核。改动只在orchestrator内部，无跨子系统依赖方向、API/前端或正式资产定义变化。图索引已同步；它不代替实际代码与隔离证据。

### 13.2 最终单条25股链与性能实测

最终实现闭包32文件的SHA256映射保存在final-implementation.json，排序JSON的SHA256为1499172645789273c32d3db2a5b912bf05bbff6efe88f6bca333ee9a2ef4d0d4，最终测试后复核未变。新隔离run_id为1c3bcd35-b0d5-4271-8c81-83ecdcf38923，plan_hash为93f85d83c5321c5a629ec0ae4aad8a379c0858711c827887228e7b3705cdf61e；旧计划未改。

夹具使用25目标股和1只保留行对照股，2,847个冻结输入，31资产、1,778目标、325个重放任务。因子2×2,489=4,978行变更；价格326行、指标104,423行是本夹具结果，不是正式Lake变更统计。实际1,492候选、286 no-op（价格279、指标7），不强凑旧记录数量。

| 阶段 | 完成目标 | 续跑阶段实测秒数 | proof audit秒数 | 全完成续跑秒数 |
| --- | ---: | ---: | ---: | ---: |
| 因子 | 740/740 | 23.248 | 6.466 | 6.327 |
| 价格 | 289/289 | 18.238 | 6.217 | 6.050 |
| 指标/state | 749/749；重放325/325 | 128.635 | 70.435 | 68.323 |

全测试351.485秒包含夹具/计划构建、三阶段取消及上表三种执行，不是170.122秒的续跑阶段合计。取消延迟因子0.135秒、价格0.020秒、指标0.056秒；最大真实可见进度间隔1.903秒。成功退出的worker共9个，另3个在阶段取消时退出；每阶段各一次已取消worker及一次续跑worker，之后audit和全完成续跑各3个。audit不建DuckDB连接；全完成续跑仅连接配置，不在工作unit执行SQL/COPY/kernel。

峰值父子RSS1,192,247,296字节（约1.11GiB），峰值staging 65,864,975字节（约62.81MiB），最终候选5,925,006字节、input投影22,771,098字节，spill为0。沿§8原预算，无额度调整。目录扫描恰好2次：首次建账及最终归属/计量对账，扫描限本任务临时run，不是全局数据扫描；两次之间7,333次轻量存储门禁合计约1.260秒。正常完成worker记录SQL/COPY/hash/fsync等明细供定位，取消worker未写最终profile，不能用汇总冒充包含取消过程的精确总量。

小样本先验证累计计量、最长1m、共享文件及跨年/恢复路径，再跑上述一次完整链。旧profile和新夹具/版本不同，只能证明重复目录扫描从调用链退出，不能直接给出同比提速百分比或正式市场ETA。proof审计和全完成续跑仍需验证本次使用的record/输出强身份，耗时已分别列出；没有隐藏为0耗时，也未再次计算公式。

### 13.3 证据位置与阶段结论

证据均保留在/private/tmp：

- /private/tmp/dg_r3_implementation_20261017/：final-implementation.json及fixed-a.xml、fixed-b.xml、fixed-c.xml、fixed-d.xml、input-reuse-r2.xml、full-chain.xml。full-chain.xml记录1项通过、0错误/失败。
- /private/tmp/dg-r3-final-chain-20261017/test_full_25_stock_chain_cance0/staging/stock_adj_factor_history_repair/run_id=1c3bcd35-b0d5-4271-8c81-83ecdcf38923：新plan、候选、projection、record、receipt、checkpoint和日志，未清理或改指纹。
- 同级r3-evidence/run_id=1c3bcd35-b0d5-4271-8c81-83ecdcf38923/：r3-isolated-acceptance.json、r3-progress.jsonl、r3-worker-metrics.jsonl、r3-full-chain.jsonl、r3-directory-scans.jsonl。观测日志在run目录外，避免测试自身污染计量。

**结论：R3 A—D代码及隔离验收通过；正式25股修复未执行，不推进R4。** 所有正式操作为0；没有请求源、扫描正式数据、写正式Lake或移动盘staging、重载定义、写事件、启停sensor、重置水位或动Prod/serving，其他任务改动保留。

边界仍需明确：现有CLI inspect包含完整库存收集，属于未修改、未执行的后续正式规划入口。R3隔离通过不能授权其全量读法；后续如推进正式冻结/候选/提升，须先按25股范围和现行全局读取规则另行评审，不直接启动inspect，也不把这一范围外改造混入本轮。

## 14. R4目标、当前依据、改动文件与消费者（待review）

### 14.1 本步目标和禁止项

本步实现并验收正式25股候选→正式文件的安全提交。范围唯一沿总方案§2及本文§2，不重新审计另外24股是否混基准，不重新验证周/月，不创建原来没有的行情/指标键。正式末端固定2026-10-16，分钟为15:00；更早seed/context只读。31资产、25股、2,489批准因子键、688689日线2021-01-27例外不变。

R3证明了候选计算和隔离恢复；它没有实现R4正式提升。R4完成文件修复后，DG materialization/check事件仍待R5，不发布serving、不伪造日更job成功、不启停或重置sensor/schedule，不重载定义。不新增配置中心项、业务API、数据集或长期状态服务，不安装依赖、不新建分支/worktree，不引入备份/快照。

### 14.2 已核实代码事实

| 当前实现 | 核实的缺口 | R4修正落点 |
| --- | --- | --- |
| _cli.main仅inspect/freeze/build/audit；execute_repair_candidates始终按单phase候选返回 | 无正式提升入口，无完整正式提交状态 | 新_promotion模块和promote动作；单phase完成不能代替全链通过 |
| _cli._collect_profiles对所有ts_code/year做glob及全市场身份查询 | validation_paths把无关年度文件纳入冻结、hash和检查 | 新_planning模块按25股、实际键和有限依赖闭包收敛，旧全市场实现退出 |
| freeze_stock_factor_repair要求run_root尚不存在，输入逐个hash | 无法承接有界准备阶段已保存的同run成果；prepare和freeze容易重复 | 只允许接手同版、同请求的本run准备记录；合并一次、原子冻结，不接受未知目录 |
| inspect_repair_writers以所有相关触发器STOPPED作为idle条件 | 把RUNNING状态直接等同于冲突写入 | 分离实际在途/排队任务、手工写者、窗口有效性和调度状态，不自动停触发器 |
| read_repair_candidate_record绑定原件旧hash且要求候选仍在staging | 正式os.replace后候选已移走，不能继续按“未提升候选”读取 | 候选证明保持不变；正式恢复用专属逐文件提交记录与正式输出身份，不绕过reader的原件保护 |
| 原checkpoint写方以phase摘要覆盖payload | 新的准备/全链/提升区块可能被后续写方覆盖 | 所有直接写方迁移到同一专项checkpoint合并规则，保留计量及其他区块，不建通用状态框架 |

CodeGraph已核对freeze、writer_guard、候选执行/读取链及直接测试；inspect_repair_writers静态调用图主要命中自身与测试，CLI动态调用已以源码补核。R4合同消费者清单包括freeze/validate_plan、validate_price/indicator_units、load_plan、RepairRuntime及proof、候选/指标批次验证、CLI worker/launcher和7份专项测试。实施前沿这些现行符号再次检查变更影响，不能只改planner输出而漏掉验证和恢复消费者；不重新审计市场数据。

### 14.3 开发文件白名单

以下路径均相对lake_console/orchestrator，表中的新函数名是拟实施接口，当前并不存在。

| 文件 | 具体内容 |
| --- | --- |
| src/orchestrator/defs/bootstrap/stock_adj_factor_history_repair.py | 新版计划/修复证明合同，精确validation_paths约束，freeze承接本run准备记录，writer检查拆分，新增模块纳入实现闭包 |
| 同目录stock_adj_factor_history_repair_cli.py | inspect/freeze接唯一有界planner，promote参数路由；不保留旧全市场准备分支 |
| 同目录stock_adj_factor_history_repair_planning.py（新增） | prepare_scoped_repair_inputs、collect_scoped_profiles、seal_preparation等专项规划/准备函数，负责输入去重、准备checkpoint及真实容量汇总 |
| 同目录stock_adj_factor_history_repair_promotion.py（新增） | audit_repair_chain_for_promotion、seal_repair_candidate_chain、promote_repair_files及逐文件恢复；唯一正式写入模块 |
| 同目录stock_adj_factor_history_repair_execution.py | 新合同准入、窗口/锁接入、准备进度取消复用、完整indicator结束时封存整链证明；提升开始后禁止再build/audit |
| 同目录stock_adj_factor_history_repair_runtime.py | 新版proof/索引及身份复用；checkpoint区块合并；准备/提升产物归属与本run计量；不新增业务公式 |
| 同目录stock_adj_factor_history_repair_candidates.py | 受影响键/保留行证明接新合同；候选reader保持严格，不把正式恢复强塞到候选半成品恢复 |
| 同目录stock_adj_factor_history_repair_indicators.py | 准确裁剪跨文件校验关系和声明证明范围，复用原谓词和原kernel，退出全市场价格/指标库存依赖 |
| tests/test_stock_adj_factor_history_repair_planning.py、test_stock_adj_factor_history_repair_promotion.py（新增） | 有界准备、真实临时文件提升、故障/退出/恢复及无正式资源访问 |
| 原7份test_stock_adj_factor_history_repair*.py及原两文档 | 按实际合同变更迁移直接消费者及断言；R3证据标明旧版本，不整包默认重跑 |

表中“同目录”均指src/orchestrator/defs/bootstrap/。不改现行计算核、共享普通check、assets/jobs/sensors、catalog/schema/paths、Dagster库、AGENTS、Prod及前端。若发现必须改这些范围外内容，先给具体冲突和证据，不能顺手扩围。

## 15. R4内部合同、证明范围及CLI

### 15.1 统一新版合同，不接旧计划续写

R4新执行统一使用plan.version=2、runtime.PROOF_VERSION=2，准备及正式提交记录也带version=2；kind和25股业务范围沿原合同。新增字段的目的是声明有界依赖、修复校验范围和正式提交依据，不改变价格/指标公式或日常Dataset合同。实现完成后所有本专项生产者、验证者和测试消费者统一迁移；新入口拒绝旧version或缺少新字段，不加兼容兜底。现有v1计划、R3证据及原hash只作历史，既不重写为v2，也不接入正式修复。

| 冻结内容 | 要求与消费者 |
| --- | --- |
| 原scope/source_rows/anchors/endpoints/units/target_preimages | 保留精确对象、日期、结果/state端点及原件强身份；仍验证31资产完整、目标唯一归属 |
| dependency_scope | 声明25股、每资产实际输入日期/年度、seed/context、前序实际行、必要完整历史范围和每条依赖用途；targets与只读依赖分开 |
| validation_scope | 明确repair_scoped_v2、受影响股票/键/日期、完整文件结构检查及范围外行守恒；不得仅存validated=true |
| validation_paths及source_inventory_paths | 只含上述闭包需要的真实路径；年度行情/结果路径的ts_code必须属于25股；共享日期文件按需要的日期并集列出，无全市场年度扩展 |
| source_fingerprints和implementation_fingerprints | 去重文件强身份及当前完整实现闭包；包含新planning/promotion模块。一次建立，同版稳定窗口复用，不逐phase重复hash |
| preparation_binding及maintenance_window | 绑定run_id、请求、实现、准备记录摘要及初始维护安排/边界；初始窗口是冻结时证据，后续有效执行窗口另记checkpoint.execution_window，不修改业务plan/hash，不能以一句“确认了”替代实际冲突写者核对 |

source_inventory_paths的“完整”指完成本25股逻辑范围所需的源文件，不再指该数据集全市场库存。所有验证器同时改成依据dependency_scope验证精确闭包；缺目标所需前序行、seed、片段或源键仍拒绝，不能借收敛范围漏掉真实依赖。

### 15.2 修复证明的准确含义

1. 每个完整候选仍检查全文件schema、主键/NULL及原行数，按现行规则检查文件自身的字段、日期、频度等合法性；按批准键替换，未选行只做一次双向EXCEPT ALL，量额不变。
2. 跨文件source/result/state覆盖、lifecycle、停牌carry及前序state的业务谓词沿原纯SQL，关系输入统一过滤为该批真实受影响股票/键，相关源和结果必须以相同对象范围比较；不能只过滤一边或跳过原错误条件。年度单股文件本来只属于目标股，共享文件的非目标行不参与重新审计其全历史依赖。
3. proof同时记下受影响键原blocking谓词的实际结果、完整文件结构检查、批准键集合、范围外行守恒、输入/overlay/seed/context/receipt摘要及输出强身份。缺项或失败不能封存；不能因“不想扫描”把失败改成通过。
4. 证明是“本次25股修复符合业务规则，其他行未被改动”，不是“全市场所有旧数据重新审计通过”。R4不产生普通Dagster绿色check事件，也不替R5决定补录口径。若某个谓词无法在本次精确闭包内等价校验，停下报告具体check和依赖，不能退回全市场扫描或静默删除该check。
5. 同一文件汇集所有命中股票后只COPY、验证、提交一次；完整证明封存后，收尾/恢复只核绑定和实际文件身份，不再做业务SQL或重放公式。v1全市场proof不能改个标志就变成v2。

若现有正式check包装函数只接收文件路径，专项适配器使用它下层的同版纯SQL规则与准确关系投影，不修改普通check接口。尤其不能把只含25股的lifecycle直接交给检查全文件所有股票的包装器，造成非目标行“身份缺失”，再靠删条件放行；目标关系、lifecycle/source/result/state必须同范围，完整文件的结构和未改行守恒另行保留。该边界须有真实schema小样本反测。

### 15.3 拟新增CLI及保持的行为

原inspect/freeze/build/audit及其scope、as-of/end、phase、full/sample参数保留。inspect/freeze的读取范围修正为上述合同；inspect仍不创建run/候选/事件，freeze仍须显式维护确认才可冻结。正式流程不先inspect再freeze重复准备；freeze内部完成一次准备并保存成果。新promote仅接完整计划，不支持sample-target或只提升某个phase。

```text
python -B -m orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli promote \
  --plan <正式run的plan.json> --expected-plan-hash <新hash> --dry-run

python -B -m orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli promote \
  --plan <同一plan.json> --expected-plan-hash <同一hash> --maintenance-confirmed
```

实际命令中的python必须是本项目现有.venv/bin/python3；正式执行单填写绝对工作目录、正式根、run_id和DAGSTER_HOME，不使用上面的占位符直接执行。dry-run与maintenance-confirmed互斥；前者仅stdout返回清单/摘要，不写checkpoint或修补不完整记录。实际提升必须有维护确认和对应正式授权，不能把此前开发或dry-run授权当写入授权。没有新增env/Settings/配置文件项。

## 16. 一次有界准备、冻结及真实候选

### 16.1 准备输入与去重模型

复用总方案§6的范围/末端/基准证据。完整数值源优先复用本run已有、参数/字段/覆盖键/hash完整的同版成功片段；没有可用片段时才用现有DG TushareResource和fetch_current_factor_rows读取批准区间与10月16日锚点。每股区间远小于既有6000单页，预计25区间请求加25锚点请求共50个基础请求；不改接口参数/字段/分页规则，不重新请求行情，不为相同证据再测连通。缺页、空值、数量不符或范围变化停止相应单元，保留成功片段，不扩大到全市场。

| 输入族 | 规划与读取方式 | 必须退出的旧动作 |
| --- | --- | --- |
| 因子/锚点 | 25股批准键日期并集；Raw/Silver目标精确路径；当前lifecycle只投影25股必要列 | 用源差异重选股票，重做全市场因子差异或身份审计 |
| 日线及其前序行 | 按已知端点、各股实际行情及688689例外提取日期索引，上一行取实际源行；同一历史扫描同时产出需要的profile/九转计数 | 每股、每资产重复读全部共享历史，先全市场枚举再过滤 |
| 分钟价格/结果 | 仅25股、实际freq/year并集；Silver选源仍1/1/5/5/30/30/60，对共享日期源做25股必要列投影并缓存 | ts_code=*/year=*全市场年度glob，收集其他股票年度行情/结果作validation_paths |
| 递推结果/state | 精确上一expected日seed、8/4根context及各自已有末端；九转必要历史只提取目标股键/价格 | 把seed只读范围变成输出，截断计数，按自然日猜前序，重新核全市场覆盖 |
| 共享目标文件 | 用明确日期路径读原文件，候选合并及一次保留行校验必须处理完整文件 | 因文件含其他股票而审计那些股票全历史或另外枚举其年度文件 |
| 容量和身份 | 上述唯一文件清单一次footer/stat和强身份；每个输入记录用途，可被多个资产复用 | 每phase全目录库存、每worker再次完整输入hash |

读共享文件以生成/保全目标文件是本次必要I/O，不等于有权读取该数据集全市场历史明细。DuckDB关系必须显式投影列、过滤股票/时间；整个数据集的全局读取不属于本设计。九转等算法确实需要目标股完整历史时，范围就是这些股票至固定末端，不替换为任意短lookback，也不读取其他股票明细作审计。

### 16.2 准备的持久化与取消

新run只在批准的正式staging专项父目录下创建，正式根不放临时文件。尚未freeze时保存不可执行的准备记录，包含run_id、version、scope/参数hash、实现hash、源单元、已完成profile/库存单元及各自文件身份/摘要；位置为本run的checkpoints/preparation/，总checkpoint只存阶段和摘要。业务分片沿既有日期/月/股年及批次≤64，不新增更紧限制。

准备按输入族/日期或股年去重，完成独立单元即持久化；同版、同参数、同有效稳定窗口恢复时，只检查该单元记录和对应文件版本，复用已完成来源/投影/计量，不重跑它的SQL或请求。未知文件、错误归属、实现或参数变化不接手；实现变化需新run，不能改旧hash强续。

source查询、文件批次、SQL和写准备记录前后检查取消。复用既有父进程监护、RSS/空间预算和可中断SQL；父进程不得用无进度的communicate等待整段准备结束。按实际工作报告已完成源单元/已规划文件/已核字节，实际最后emit≤30秒；ETA不可靠时明示未知。取消后不领新单元，worker退出、锁释放，已成功片段保留。

### 16.3 冻结与身份复用

freeze允许本run已经存在自己的合法准备记录，但拒绝已有不同plan、未知目录或无对应plan的候选/正式提交痕迹。冻结前合并成功单元一次，验证25股/31资产/输入闭包/目标唯一归属、原预算及窗口，原子生成唯一plan.json。不得先造能执行的残缺plan再补字段。

若plan已原子冻结但命令在返回前中断，重进相同run/request/实现时只读校验并返回原plan/hash，不再规划、请求源或重写计划。若此run已开始正式提升，返回实际状态并引导promote恢复，不能清空、重新freeze或回到build。不同请求/实现仍拒绝。

源/原件强身份按唯一文件首次建立一次；同版准备中已有完整强证据且stat版本仍一致时可复用，不能只信存在或mtime。plan绑定这些真实身份和准备摘要。运行内/后续阶段通过有效稳定窗口、同一文件版本及plan绑定复用已核身份，不能freeze已hash一遍，worker又把同一输入全部hash一遍。真正首次使用且没有强证据的文件仍校验一次；复用的输出在重启时按对应范围验证，不hash未使用的潜在库存。

维护窗口失效、真实内容/版本冲突或新实现出现时，停止并报告，不通过stat/缓存掩盖已知变化。休市稳定输入是本次已确认前提，不周期性查网络或扫描数据证明它仍成立。

### 16.4 候选计算与全链封存

沿现有factor→price→indicator顺序，复用R3同phase worker/连接、输入投影、逐文件/片段记录和单run计量。31资产的每个目标必须有完整候选或合法no-op；结果/state分别覆盖到各自端点，实际未改行/量额保持。取消或崩溃只续未完成后缀，不重新请求数值源。

最后一个完整indicator阶段结束后，seal_repair_candidate_chain汇总本计划全部record/receipt与目标集合一次，验证三阶段齐全、无sample/待提交/缺证明、输出身份及预算。它不再执行业务SQL或公式；成功在原checkpoint.candidate_chain保存绑定摘要、31资产覆盖、完整/候选/no-op数量、实际字节和封存时间。后续dry-run读取此证据，不另跑三个audit来重复计算。

每phase摘要继续只表示本phase完成。全链提升准入由专门汇总结果表达，不能把某phase的completed或all_chain_ready字段手工改真。候选封存后保持不变；正式提升开始后拒绝重新build/audit，明确引导使用同plan的promote恢复，避免对已替换原件重新算旧候选。

## 17. 无冲突窗口、唯一写者与读写边界

### 17.1 不以RUNNING状态代替实际写者判断

inspect_repair_writers返回相关资产/job/触发器、实际在途/排队任务及检查范围；RUNNING/STOPPED只作事实摘要，不再决定idle。scope外任务不阻塞本专项；涉及目标或输入文件的真实写者、即将执行的冲突任务才是拒绝依据。不得通过试跑sensor evaluator获取结论，因为它可能写cursor或提交任务。

准备开始及正式提升开始这两个边界，各做一次有界只读检查：当前定义中的相关写job、对应活动/排队run、已核实的手工写进程、现行调度时间/交易日条件与管理员维护安排。复用已经核对的同窗口证据，不轮询全instance或深扫tick历史。不得运行或终止其他任务；无法确认某写者的身份/范围时报告具体对象。

接受相关sensor保持RUNNING，需要同时满足：管理员确认的休市稳定窗口；没有实际冲突写者/待执行冲突run；现行调度条件在该窗口不会发起冲突写入。窗口结束边界来自现行调度和维护安排，写在正式执行单及计划中，不自行设“30分钟”等紧时限。若无法证明或确实存在冲突，则停在写入前报告原因，不能自动停sensor、改cursor或给普通job加新开关。

### 17.2 锁能保证什么

复用fcntl.flock，在专项正式staging父目录使用一个固定writer.lock约束本专项正式协调器，同时保留原plan锁和父进程监护；隔离测试使用自己的临时父目录。锁文件不存业务状态，退出后内核释放，不能靠删除锁文件解锁。此锁不约束普通Dagster job，所以不能用“拿到锁”替代上一节的窗口事实。

正式命令必须明确run_id，候选/提升还须完整plan；冻结前的准备记录只作为本run不可执行草稿。同专项竞争写者拒绝，不开第二协调器。窗口到期在下一个单元前停止，不领取新目标；一个已经进入原子替换临界段的文件完成fsync/状态记录后再退出。仍需写入的恢复先核窗口与自身锁，再读本run提交记录；不重新核市场、上市池、末端或基准。

维护窗口是本次执行许可，不是业务计算输入。初次冻结保留当时证据；若之后过期，经明确批准的新窗口只在checkpoint.execution_window记录plan_hash、原/新窗口、批准依据、当前有界写者检查及有效边界，不改plan/hash、候选proof或数值截止日期，不为续窗口重新计算。没有新窗口授权或发现真实输入变化则停止；不能自动延长窗口，也不能因为原窗口到期就强迫重做全部候选。只读dry-run不创建或续写此记录。

### 17.3 路径和观测边界

正式Lake只允许/Volumes/datasource/data_lake，候选/准备/提交记录只允许/Volumes/datasource/data_lake_staging的本run。新run形如stock_adj_factor_history_repair/run_id=<新UUID>，不能用R3临时根或旧run。冻结/提升边界核对挂载、同文件系统、目标归属、symlink和可用空间；不能在正式目标旁创建临时文件。

DAGSTER_HOME仅用于读取现有instance状态/已有分区事实；配置读取及数据库查询继续只读，不初始化instance或写探测记录。CLI不import或执行asset job来写文件；不改数据库、分区、事件、sensor/schedule/cursor，不向Prod或serving发布。sensor状态/水位若本轮需要对账，使用开始时的有界只读摘要与结束摘要，不重置它们。

RUNNING的sensor可正常tick并自然推进cursor；验收要求本专项对调度/水位写入为0，不要求两次全局状态快照逐字相同，不把其他任务的合法推进回滚或当作本任务失败。

## 18. 全链准入与逐文件正式提升

### 18.1 全链准入，不能只看到一个文件成功

audit_repair_chain_for_promotion只沿plan.units/target_preimages及其record/receipt建立索引，不glob正式Lake或重放业务SQL。必须同时满足：

1. plan/hash、version、实现闭包、25股/31资产、批准日期及固定端点完整；来源和目标路径属于批准根。
2. 冻结目标集合与成功候选/no-op记录集合完全一致，目标只能有一个owner；每条记录有新版完整proof，非sample，无commit_pending/business_pending；三个phase各自覆盖本phase目标，其并集覆盖本计划全部目标。
3. 每条record_hash、proof的plan/实现/规则/范围/依赖摘要、overlay、seed/context和receipt链均匹配；输出hash/实际字节与持久化文件事实一致。缺一条目标或证明即未就绪，不能补造成功。
4. 全链封存摘要绑定排序后的目标/record_hash/输出hash集合、变更行数、候选/no-op数量与字节；没有使用全市场库存或旧v1证明升级。
5. 对实际提升还须满足维护窗口、专项锁、路径/同文件系统和空间条件。文件计算通过与“现在允许写”分别返回，dry-run不能替代正式授权。

candidate_chain封存是现有checkpoint中的一段证据，不是新的Dagster资产或数据库状态。promote --dry-run只读取它及必要绑定，输出plan_hash、整链是否齐全、按资产汇总的将替换/no-op/已完成/待完成数量、字节、完整目标清单引用、停止原因和窗口摘要，不默认向stdout倾倒全部文件记录，不重新执行validator/kernel/COPY，也不修复缺失封存。

候选输出的强身份由生成/读回时取得；同版同窗口的有效证据复用。新进程只验证这次要使用的输出/提交记录，建立一次缓存；同一次命令内预览、逐文件提交、最终对账共用，不对同一稳定文件反复hash。第一次正式提交之前，全链必须齐全，不能先提升因子再等待指标候选补齐。

### 18.2 正式逐文件checkpoint

在已有checkpoints树新增promotions/<sha256(target_relative_path)>.json，只有plan内目标可以创建。它是本次正式提交的逐文件checkpoint，不是新长期账本；候选record及业务proof保持原样。每条至少保存：

| 字段组 | 内容 |
| --- | --- |
| 归属 | version、run_id、plan_hash、implementation_binding、asset_key、unit_id、target_relative_path |
| 原证据 | candidate_record_hash、candidate_chain摘要、preimage_sha256、candidate_sha256、candidate_relative_path、candidate_bytes、no_op |
| 提交状态 | PREPARED/COMMITTED/SKIPPED；准备/完成时间；本文件操作前后实际路径和身份 |
| 持久化与计量 | 源/目标同文件系统信息、rename及目录同步事实、输出身份读回证据、候选字节扣减归属 |
| 完整性 | 本条checkpoint_hash，绑定上述字段；不能以exists/size或一个成功布尔值代替 |

总checkpoint保留preparation、execution_window、candidate_chain、promotion和storage_accounting等明确区块；各写方只合并自己的区块，不丢弃另一区块。不在总JSON中每提交一文件重写全部文件明细，详细进度来自上述独立记录，避免O(目标数²)元数据写入。

runtime.owns_artifact必须按plan目标派生这些路径，并登记合法的准备记录、最终清单和临时JSON；不放宽成任意前缀都可信。未知归属、symlink或真实计量不符仍拒绝，包含0字节未知文件。

### 18.3 一文件的实际提交顺序

以批准的固定排序处理：Raw因子、Silver因子、日线/分钟价格、指标结果、对应state；同一资产内部按逻辑日期/股年及路径排序。目标范围在提交前已冻结，执行期间不发现新目标、不随文件是否存在改变清单。

1. 检查取消、窗口和本文件归属。验证已有正式提交记录；若已COMMITTED/SKIPPED且对应输出事实一致，直接计入完成，不重写。
2. 对待处理目标，核对冻结原件版本/旧hash，以及已验收候选强身份。有效稳定上下文内直接复用已核身份；不能接受第三种内容。no-op要求候选hash等于旧hash且没有候选文件，记录SKIPPED即可，不改正式文件。
3. 写入PREPARED checkpoint并fsync其文件及目录，绑定本条不可变候选record和旧/新hash。这个记录必须在rename前成功；失败不替换。
4. 通过现有存储预留机制持久化“候选源路径即将移出staging”的未结计量，保持最多一个当前文件。候选文件已完整校验/fsync；再核对路径/设备及该文件版本，持有必要文件描述符，调用一次os.replace(candidate, formal_target)。禁止跨卷copy兜底，禁止在正式目标旁写临时文件。
5. fsync正式目标父目录及候选原目录，完成正式输出身份读回。可将已强校验候选hash经同设备/同inode、大小及实际原子rename证据绑定到正式路径；不能仅凭size/mtime继承，也不要求再跑一次Parquet业务SQL。若这些物理证据不足，才对该文件读取一次强身份。
6. 结算候选/staging实际减少的字节，保存COMMITTED及读回证据。若此时状态写失败，不回滚文件、不重新COPY；如实停止并从PREPARED恢复。
7. 发出真实进度，包含阶段、asset/路径、已提交/跳过/剩余数量、实际字节、最后更新时间和已耗时。只有文件持久化并登记后才增加完成量；取消到达原子替换临界段时先完成本文件状态收尾，再退出，不领取下一个。

移动发生在同一文件系统，正式文件内容来自原已验收候选。对已提交的下游依赖，_promotion的只读定位器使用其正式目标作为同一输出hash的所在地；不能再调用要求候选仍在staging的旧reader来判错，也不能把这个定位器用于候选计算、回退到未修原件或绕过proof。源码/plan不匹配仍停止，不能改实现hash续跑。

## 19. 取消、崩溃及恢复状态表

恢复先验同plan/实现和提交记录归属，仍需继续写入才要求有效窗口，再按下表处理本文件。全完成后的只读结果核验不要求重新取得维护窗口。只检查当前未结路径及准备复用的输出，不重新枚举Lake、请求源或计算指标。

| 提交记录与文件事实 | 恢复动作 | 禁止动作 |
| --- | --- | --- |
| 无提升记录；正式目标仍为旧hash；候选及全链proof完整 | 正常进入PREPARED并提交 | 未封存全链就先写正式文件 |
| PREPARED；目标旧hash；候选新hash仍在 | 继续同一提交，复用校验/输入/输出 | 重下来源、重建候选或重算原检查 |
| PREPARED；目标新hash；候选已移走 | 验证正式新输出与原提交绑定，补目录同步、计量及COMMITTED | 把目标当input_drift后另造计划，或再次替换 |
| COMMITTED；目标新hash；候选已移走 | 保留成果，计入已完成并跳过 | 重新计算或覆盖同文件 |
| 合法no-op/SKIPPED；目标旧hash=新hash | 只核身份/记录绑定，保持正式文件不动 | 为凑文件数生成/提升空变化候选 |
| 原窗口过期，输入/实现及已完成成果仍合法，另获新窗口授权 | 核对新窗口的实际写者并更新执行许可区块，沿原plan/hash续剩余 | 改业务截止日期/指纹、自动延期，或为换窗口重算已完成成果 |
| 目标第三种hash、输出缺失、错归属/错record_hash、未知候选 | 停止，报告具体文件/预期/实际，保留现场 | 删除残留、认领未知文件、吞错误或改hash |
| 非no-op候选缺失且目标仍旧hash，或新目标与残留候选同时出现且无一致提交事实 | 停止并报告不一致；不自动重新生成 | 在已部分提升的混合输入上重新跑build |
| 替换前/后checkpoint写入或fsync失败 | 保留实际文件，报告该边界；下次按PREPARED/目标事实恢复 | 声称全链完成或回滚已替换业务文件 |

候选阶段与正式阶段是不同恢复边界：候选commit_pending表示临时文件提交；本节PREPARED表示正式文件提交，二者不能混用。所有记录保留原plan/hash，不通过改指纹迁移旧成果。

取消及TERM/KILL测试只处理身份已核实的本任务父/子进程。沿R3父监护、进程组、锁和SQL中断能力；父退出后worker退出，锁自动释放。已COMMITTED文件及候选片段不删除。实际最后emit沿原≤30秒门禁，hash/SQL/批次使用现有可取消检查点，不设置新的更紧额度。

计量恢复沿原checkpoint.storage_accounting及未结源路径处理：候选已移出则扣减一次，仍在则不扣；JSON临时文件仅清理本预留拥有的确切路径。不得因为候选搬到正式目录就继续计入staging，也不得重复扣减。账目缺失或实际对不上时才允许对本run重建一次，不默认重扫所有目录。

完成后的重复promote只读本plan及逐文件提交证据并返回幂等完成；不重新执行业务SQL、kernel、COPY或os.replace，不重新取源。数据丢失/真实损坏如实失败，不能把幂等误写成无条件返回成功。

## 20. 一次收尾、性能模型与拒绝策略

### 20.1 正式文件收尾

逐文件身份读回已经在提交时完成。最终一次收尾将冻结目标集合与COMMITTED/SKIPPED集合做集合对账，确认覆盖、唯一归属、正式路径/输出身份及实际变更数量；检查失败/未完成为0，再汇总已有读回及候选业务/保留行证据。正常流程不再逐文件重新跑业务SQL、重放公式或第二次整文件hash；只在某条读回缺失/不一致时定位该文件。

生成本run的reports/promotion_manifest.csv与必要的failures.csv：包含asset、目标、状态、旧/新hash、是否实际替换、候选record引用、实际变更行数、批准修改范围、提交/读回时间、reason_code。变更行数和批准范围使用候选阶段已保存的实际事实，不能为导出CSV再扫描行情、重算公式或新做逐行差异计算。无错误时failures可仅含表头；不隐去不一致记录。

本run初次建账、最终归属/计量对账各一次递归扫描；准备/phase切换/预览/轮询/COPY不新增walk。最后一次扫描只覆盖本run产物，已移出的候选由正式提交证据解释，正式Lake不递归扫描。结束报告明确“正式文件已完成、DG事件待R5”，不伪造绿灯，不触发消费者验证job。

### 20.2 性能预算和量测依据

沿§8现有RepairBudget：plan192MiB、DuckDB2GiB、RSS4GiB、线程2、spill2GiB、候选10GiB、单股片段100000行、消息16KiB及逻辑批次≤64。它们是已采用工程参数，不新增配置源；若实际不能满足，提交具体测量和建议后再调整，禁止暗套6GiB或共享默认值。

以下F为精确只读依赖文件数，T为唯一目标文件数，C为实际候选数，N为no-op数，T=C+N。正式数量尚未测量，本轮不扫湖来填表。

| 成本 | 预算/读取模型 | 如何取得依据 |
| --- | --- | --- |
| 对象/日期/资产 | 25股、31资产、2,489因子键，逐股范围及固定末端 | 直接复用原范围及审计；日期索引只为真实规划读取一次 |
| 数值源 | 已有合格片段0重复请求；首次无片段预计50基础请求；分页/原错误处理不变 | 按单元记录实际请求/页/行及来源，不用连通性单行耗时推算 |
| 规划/指纹 | F/T唯一清单一次；共享历史必要列/股票关系按输入族复用；强身份按唯一文件一次 | 准备checkpoint统计SQL数、路径数、读入字节、hash字节及耗时 |
| 候选生成 | 原kernel真实所需行，T目标各合并/验证一次；C次文件COPY，N不写 | 实际R3式profile和记录；COPY片段与候选分别计数，不混成目标文件数 |
| staging峰值 | 实际候选、必要投影/重放片段、metadata及受控spill；无备份/源文件全量复制 | footer原体积+小样本压缩/投影实测+增量计量；预留沿原安全系数，读源本身体积不当作必须复制的空间 |
| 正式提升 | C次同卷os.replace和目录同步；JSON/身份读回；无COPY/公式/重放 | 有界临时样本测提交/状态/fsync吞吐；现场按实际字节/文件更新估计 |
| 最终对账 | 目标/提交记录集合一次归并；本run归属/计量一次扫描 | 复用每文件读回和保留行证明；不重扫正式数据集 |

space_required_bytes改按实际需要落盘的候选/投影/片段/metadata及spill测算，保留现行安全系数；不再把全市场只读年度输入体积重复预留。已完成staging成果从剩余需求中扣除。每次COPY前保留轻量disk_usage、预留/RLIMIT及spill配额，不walk；正式rename不复制整文件，计量随候选移出减少。

具体以剩余待落盘候选、投影/片段、metadata和计算阶段尚需spill之和乘原6/5系数，按字节向上取整；既有文件不再重复预留。进入纯提升阶段后不执行DuckDB、无需新spill，不再为已经结束的计算额外预留2GiB；只保留本阶段实际metadata需求及已有未结计量。候选10GiB/实际spill2GiB等原额度仍约束对应阶段，不通过预留模型调整偷偷放宽。测试须覆盖“提升无需再预留整批候选/计算spill”和真实空间不足仍拒绝。

R3实测351.485秒和约1.11GiB只作结构/隔离证据，不能推出正式ETA。开发先测小样本新增准备/提交路径，正式freeze用去重footer/输入行及已有吞吐给出区间估计；源等待、共享大文件和未知阶段明确不确定，运行中显示实际进度，不能伪造剩余时间。

不可接受条件包括：准备又回到全市场年度枚举；同一稳定输入按phase重复扫描/hash；已完成文件再次kernel/COPY/replace；完整文件按25股分别重写；无进度超过原门禁；真实超预算/空间不足/窗口失效。命中后停止并定位，不以增加无关审计、缩业务范围或吞异常通过。

## 21. R4隔离正反测试及证据要求

只使用项目现有环境、临时Lake/staging、替身及隔离instance；正式路径、网络/token、事件及调度写入均拦截。读取真实生产者/schema和已存在金样本确定夹具，不按消费者查询反推字段。故障输入明确标注；预期值独立于待测实现。

| 项目 | 正向验收 | 反向/必须拒绝 |
| --- | --- | --- |
| 合同/消费者 | v2生产者→准入→候选/指标→全链→提升字段一致；新模块在实现闭包 | v1、缺scope/依赖/证明、错plan/实现、少资产/目标、重归属、错端点；旧源码/计划不能直接执行 |
| 有界准备 | 临时目录放目标25股和无关股票/年度哨兵；所需共享文件正确投影/保留，源单元/库存/锚点去重 | 哨兵文件一旦被枚举为依赖、打开/强hash即失败；漏前序行/seed/context、缺所需源/结果键仍拒绝 |
| 修复校验范围 | 使用原SQL谓词和字面小样本校验目标股；完整文件结构/保留行守恒一次 | 仅过滤一边掩盖覆盖差、丢量额/其他股票、错seed/carry/九转、写出范围外键或冒充普通全市场check |
| 准备恢复 | 来源/准备单元完成后中断，同版恢复0重请求/0已完成SQL，未完成继续 | 未冻结草稿可执行、未知run被接手、改参数/实现后改hash强续、空源/缺页仍成功 |
| 窗口与写者 | sensor RUNNING但有效窗口且无冲突run时可继续，本专项无状态/水位写入；本专项锁互斥；获准换窗口沿原hash续跑 | 相关活动/排队/手工写者、窗口不能确认/已到期拒绝；未经授权自动延期、为换窗口重算均拒绝；无关任务不被终止，不调用sensor evaluator |
| 全链准入 | 每目标完整proof/no-op，三阶段集合齐全，纯汇总后才准入 | 只完成factor/price、sample、缺目标/receipt/业务项、第三种hash、手改all_chain_ready，任何一项都不能写正式文件 |
| 正式替换 | 真实临时候选经原子rename成为目标；同卷fsync/身份/计量/COMMITTED完整；no-op不写 | 错根/越界路径/symlink、跨卷、权限/空间不足、错误hash/归属拒绝；不得copy兜底或删现场 |
| 崩溃与取消 | PREPARED前、写后、rename前后、目录同步/COMMITTED前后分别注入；同plan仅续未完成 | 状态失败回滚业务文件、候选丢失后偷偷重算、父退出留worker、取消后领新文件、未持久化即报完成 |
| 幂等与依赖 | 两个以上关联文件部分提升后重启；已提交输出从正式路径按原hash解析；全完成再运行0 SQL/kernel/COPY/replace | 候选已移走误判缺输入、重复扣字节、丢candidate_chain/计量区块、把未提升旧原件当修复overlay |
| 收尾/事件边界 | T与提交/no-op集合、实际字节和CSV一致；正常流程目录扫描仅本run首尾，正式操作替身计数可核 | 旧proof冒充新实现验收、漏失败清单、重复全历史复算、触发普通job/DG事件/serving或操作sensor |

单文件提交/状态机用真实临时Parquet和进程故障测试；完整集合准入可用独立字面元数据夹具验证集合/绑定，并明确这只是元数据层测试，不把替身说成31资产真实计算。至少一条小链使用当前真实候选生产者输出接正式单文件提交器、退出/续跑和读回，独立断言具体价格/保留行/身份；不能用替身绕过被声称验收的文件边界。全31资产真实候选及正式根准入在获准正式执行阶段完成，不为开发测试再重跑完整R3计算链。

开发期间只重跑实际受影响用例。版本固定后跑必要直接回归、源码默认Ruff及致命错误基线、文档检查和diff检查；旧185项、旧32文件指纹及旧25股夹具作为历史，不冒充新v2验收。交付必须列“要求→代码→正/反测试→证据→通过/未完成”，区分静态、单元、隔离、正式事实。

## 22. 开发顺序、正式执行单及完成判定

### 22.1 开发阶段

| 步骤 | 必须落地 | 进入下一步的条件 |
| --- | --- | --- |
| D1 合同/有界准备 | §15—§16的v2合同及所有消费者、唯一planner、源/文件去重和准备续跑 | 缺依赖拒绝、无关股票年度哨兵不被读取、取消与准备复用小样本通过 |
| D2 窗口/锁/真实候选接线 | §17窗口事实和锁；原候选链接v2精确关系及同一proof；全链封存 | 不操作sensor，实际冲突拒绝；所有受影响键的原业务谓词和范围外行守恒正反测试通过 |
| D3 正式提升/恢复 | §18—§19的新模块/CLI、提交记录、字节扣减及已提升依赖定位 | 真实临时文件替换、取消/退出、状态失败、部分及全完成幂等通过 |
| D4 收尾与开发交付 | CSV、归属/计量、性能计数、白名单和文档对账 | 仅相关回归通过，未完成项/正式未执行明确列出；申请下一阶段正式范围 |

D1—D4只有本文review及开发授权后才实施。必要代码改完并隔离验收后，按届时白名单提交；不推送、不改变其他任务脏文件。无源码/字段依据或发生范围外依赖冲突时先报告，禁止带着严重错误进入正式阶段。

### 22.2 获准后的正式执行清单

每个正式步骤先核对该步授权，不把“可以审计”当“可以写”。一份执行单完整写明以下内容，不复制多个相互漂移的runbook：

1. 当前dev-interface固定实现/提交及完整指纹；25股、逐股日期、688689例外和10月16日末端；批准维护窗口及结束边界；实际工作目录和已有解释器；只读DAGSTER_HOME来源；正式Lake/staging绝对路径；新run_id；原预算。代码未验收或窗口不明确则不开始。
2. **正式准备/freeze。** 允许写入的仅为本run准备/staging和plan；命令包含25次--scope及现有--as-of 2026-10-16、--end 2026-10-16、--daily-basis-start 2021-01-27、--run-root及--maintenance-confirmed。不使用旧run/hash；不先跑一次完整inspect。源、profile、计量按§16保存/复用，输出新plan_path/hash、真实F/T、体积和估计。
3. **真实候选。** 同一plan/hash依次build --phase factor、price、indicator --full。正式目标不写；成功片段与文件直接复用。最后封存全链、准备预览清单，不再重复三次业务audit。任一阶段失败停在该处，不带缺口进入提升。
4. **提升预览。** promote --dry-run打印完整清单引用及按资产汇总的变更/跳过/待完成数量、实际字节、窗口和停止原因。若预览或容量需要调整执行范围，先确认，不自动推进；正常预览无正式写入、无状态修补。
5. **正式提升。** 在已有明确正式写入授权下，promote --maintenance-confirmed使用同plan/hash和同窗口。确认真实写者与自身锁，逐文件按§18提交。命令需要的动作仅来自冻结计划，不允许新增代码范围或目标。
6. **取消/失败恢复。** 保留日志、候选、提交记录、plan/hash和已替换文件；报告具体阶段、完成/未完成、当前文件、worker/锁退出及原因。同实现、同plan且窗口仍有效时，用同一promote命令只续剩余；窗口失效须先处理窗口，不能改截止日期/指纹强续。
7. **一次收尾。** 用已有逐文件读回证据与目标集合归并，核对实际修改范围、候选/no-op/提交和空间；输出manifest/失败CSV、耗时和峰值。其他正式数据、调度状态和水位不改，事件0、Prod/serving0；报告R4文件完成或明确未完成。

正式准备/候选与正式提升可分别授权；执行单须明确本次获准停在哪一步。未知实际文件数和耗时在准备完成后报告，不引用历史13,005/15,743或夹具1,778为本次事实。所有新意外先停下来定位，不用恢复/验收名义扩大数据读取或写入。

### 22.3 本轮文档交付状态

本轮已将R4四项审计缺口、开发文件、内部合同/CLI、读取模型、维护窗口、正式提交状态机、预算及正反验收落回原方案/LLD；这些均为设计，尚未实现。文档审查不代替代码或正式执行验收。

进入开发前需review确认本文设计，尤其是：promote入口、v2修复证明及消费者同步、运行中的sensor以窗口/实际写者判断、逐文件正式提交记录。它们用于完成已明确的R4目标；不会扩成全市场维护、普通调度改造或R5事件。无未处理设计冲突后才按D1—D4开发，本轮不提前动代码或数据。
