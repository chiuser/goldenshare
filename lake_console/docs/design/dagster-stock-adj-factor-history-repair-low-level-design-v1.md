# 25股修复LLD v1：R3执行优化、隔离验收与开工边界

更新：2026-10-17。本轮依据原[总方案](dagster-stock-adj-factor-history-repair-plan-v1.md)及最新休市稳定输入要求修订。R1/R2已提交；旧R3未最终验收、代码/现场保留。本文规定后续R3开发，不表示新运行上下文或增量计量已经实现，也不授权正式freeze、候选/提升、事件、serving或sensor操作。

## 1. 当前实现、根因与消费者

| 当前代码 | 已核实行为 | R3落点 |
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

内部_worker改用有界JSON消息：init绑定plan_path/expected_hash/phase/coordinator_pid/plan_lock_fd；work沿原unit_index/targets或replay_task_index；finish结束该phase。每条消息沿用当前16KiB门禁，工作按既有批次分发，不把全plan/全文件清单塞进消息。子进程解码计划和建本地索引一次，仅核请求子集及父绑定，不重复正式库存和全输入hash。回应ready/batch_done/finished/error仍为有界摘要，不在stdout累积全量记录。

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
| 环境与授权 | 现有orchestrator .venv与隔离测试框架此前可用，当前dev-interface；四个原R3脏文件保留。本轮仅文档，不借测试安装套件或操作正式资源 |
| 重复动作 | 计划/输入缓存、预算计量、完成识别、一次业务验证和单条完整链均有具体落点；不会以休市数据可能变化追加审计 |

**结论：可以进入R3代码整改与隔离验收；没有需要先重做市场/因子/基准/完整性审计的前置项。** 当前旧实现的重复开销与未完成验收属于A—D开发内容，不是新的开工阻塞。进入耗时完整链前须先通过小样本成本/恢复测试；正式freeze/候选/提升/事件/serving仍未获本轮授权。文档通过不代表代码或正式修复完成。

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
