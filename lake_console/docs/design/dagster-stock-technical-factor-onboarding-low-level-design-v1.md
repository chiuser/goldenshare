# 股票技术因子 DG 数据集接入 LLD v1

日期：2026-10-23。状态：设计草案，尚未开发。本文落实已确认的前一交易日补一次、股票复权因子数据集先就绪、下载前完整名单、日先历史后、因子差异只诊断、全天停牌无T行可回刷、手动历史repair入口，以及20交易日合并批次、5000行bootstrap、sensor间隔、既有资源复用和精简验证安排。业务决定与仍需验证的编码细节集中在§12；本文不构成开发放行或正式执行授权。

依据：[原技术方案](dagster-stock-technical-factor-onboarding-plan-v1.md)、[DG接入模板](../templates/dagster-dataset-onboarding-template.html)、[性能治理规范](dagster-data-pipeline-performance-governance.md)、[Prod审计报告](../../reports/stock_factor_pro_prod_audit_20261021/README.md)。下载器依据[组件LLD](dagster-tushare-download-component-low-level-design-v1.html)与[业务使用文档](../architecture/tushare-download-component-usage-v1.html)，不在本数据集重做。两份接入设计中的原最近7日策略、因子未就绪仍启动、下载后才计算回刷名单等口径均已撤回，不得从旧审查记录恢复。

## 1. 范围、日期与已经拍板的规则

本文所称股票复权因子数据集，是现有 Tushare `adj_factor`（DG Raw资产`raw_tushare_adj_factor`）；技术因子数据集`stk_factor_pro`中另有同名`adj_factor`字段。前者是变化名单、历史回刷和输入修订的依据；后者保持源业务值，仅记录差异，不作为历史启用的等值门槛。不增加新的因子概念或数据集，也不将技术因子行的1改成股票复权因子数据集的2。

本轮只修改设计（包括已批准手动repair的具体接口）；未改代码、登记契约、运行任务、注册分区、写Lake/数据库/正式事件或启用sensor。历史从Prod bootstrap，完成物理验收并另获启用批准后，DG直接从Tushare日更和获取必要历史；不把每日来源改回Prod，不迁移其他数据集。

| 日期名称 | 精确定义 |
| --- | --- |
| 执行日D | 本次自动更新安排所在的上海自然日期。19:00～23:30固定时点属于D，午夜截止是D+1的00:00。 |
| 今天 | D本身是SSE开市日时的业务日期；不能把休市自然日当成新的交易分区。 |
| 昨天/上个交易日Q | 严格小于D的最近一个SSE开市日。例如周一的昨天是周五，不是周日。只在开市执行日安排自动补Q，休市日不自动补，见§12.3。 |
| 目标日T | 一个job只处理一个目标日，T可以是Q，也可以是今天。 |
| 前交易日P | 严格小于T的最近一个SSE开市日。补Q时使用Q及Q的前交易日，不能错误地用今天及Q。 |

已经确认：

1. 每个开市执行日对Q至多自动补一次；Q已经满足日处理要求则不为消耗次数而再跑。Q确实开始业务下载后仍缺股票，或日阶段失败且不能证明已补齐，当天不再补Q，也不推进今天。Q日阶段已完成且代码已齐、仅后续历史失败时可以推进今天，历史pending另保留；不能仅按run FAILED一刀切。上游未就绪、尚未实际开始的等待不消耗机会；分页与组件同页重试不另算一次。实际开始证据和未开始的重新发起见§3.4。
2. 北京时间19:00、19:30、20:00、20:30、21:00、21:30、22:00、22:30、23:00、23:30，共10个计划时点；已有本数据集排队/运行/取消中任务则跳过，不积压。Q占用某时点时该时点不再排一份今天的任务，不能保证今天一定执行10次。
3. 午夜停止新尝试，排队任务实际开跑时再次核对截止时间；午夜前已开始执行的任务允许正常结束。午夜不是取消指令，不强杀线程或打断发布。
4. **股票复权因子数据集在目标T及其前交易日P的Raw已就绪，是sensor提交job前的硬条件；job开始再确认一次。**这是两个因子输入的就绪条件，不是要求股票技术因子已全市场覆盖。不能因为本轮只返回部分技术因子而挡住有效数据发布。
5. job在技术因子网络下载前读取`adj_factor`数据集的T/P因子、生成并完整保存T的变化股票及历史范围清单。sensor只编排，不计算名单；名单不能按本轮技术因子返回了多少股票来缩小。
6. 每轮取得的完整有效数据先发布日Raw、Silver，业务即可读；然后在同一个自动job处理必要历史。历史失败保留日数据，管理员可通过§4.1额外的手动repair job只恢复原T历史，不重跑日阶段；无自动repair sensor。没有覆盖率、最低股票数、全历史完成或跨文件快照门槛。
7. 只从应有集合排除全天停牌，盘中停牌仍应有。Raw不据应有集合过滤来源合法行。Silver本期完整保留字段及对应行，归一化日期；后续新增清洗不作为本期前置，不自行过滤/填值。
8. 只自动管理今天和Q；更早分区保留，旧洞报告管理员，不自动扩大为7日或全历史恢复，也不把更早旧洞自行变成今天永远不能执行的条件。

完整unit仍指本次接口查询全部页已取全，不代表源端所有应有股票已发布。合法少股票可处理，网络只完成一部分页不可交付半unit。管理员手动repair是额外人工入口，不是增加自动调度链；原“没有独立repair入口”的旧描述撤回。当前正式CONTRACTS/BINDINGS仍为空、名称后缀校验仍待改；本文资产、定义及记录均为拟新增，组件已有隔离验收不代表本数据集已实现。

## 2. 定义、代码结构与接口

### 2.1 Dagster定义

| 对象 | 固定名称与职责 |
| --- | --- |
| 源契约 | `stk_factor_pro`、独立`version="1"`；261个完整源业务字段；固定HTTP；使用BY_POINT与BY_OBJECT_RANGE。 |
| 两个资产 | `raw_tushare_stk_factor_pro`、`silver_stock_factor_pro`；日数据依次发布，后续历史仍写这两个资产的旧日期，不新增清单/完成状态资产。 |
| 分区 | `cn_a_stock_factor_pro_trade_days`；两资产及两项check共用；只日常新增今天和Q，旧键不删除。 |
| 自动日更job | `raw_tushare_stk_factor_pro_update_job`；单T、单轮，仍包含名单、日发布和历史处理；不为传名单新建自动历史job/sensor。 |
| 管理员手动历史job | `raw_tushare_stk_factor_pro_repair_job`；只恢复原目标日、原批名单/范围的历史，复用同套历史函数，不发T全市场BY_POINT日请求、不执行T日发布；无自动sensor，精确输入见§4.1。 |
| 注册sensor | `stock_factor_pro_trade_day_sensor`；按日历新增今天及Q，不下载，不等Tushare或因子就绪。默认STOPPED。 |
| 更新sensor | `raw_tushare_stk_factor_pro_update_job_sensor`；按Q一次优先、时间、活动run、因子门槛和结果提交；默认STOPPED。 |
| Raw综合check | `raw_tushare_stk_factor_pro_file_contract_check`；文件/字段/主键/日期、完整unit保存及合并对账，不查全市场数量门槛。 |
| Silver综合check | `silver_stock_factor_pro_file_contract_check`；对应Raw、DATE/主键、完整261字段及逐行对账；本期不增加清洗过滤，后续新增规则不是前置。 |

采用一个`@dg.multi_asset`定义两个资产，在一个同步生成器内明确执行日Raw→Raw检查→日Silver→Silver检查→历史。不能保留“Raw资产函数等待所有历史结束才返回，Silver才有机会开始”的旧组织。两个`AssetSpec`可声明`skippable=True`以表达首次合法0行时不伪造物化，`can_subset=False`保证正常入口总是按完整链路运行；不是允许业务任意挑选字段或只更新一层。

`check_specs`恰好两个，使用`AssetCheckSpec(..., blocking=True, partitions_def=cn_a_stock_factor_pro_trade_days)`。日检查用`AssetCheckResult`，severity为ERROR；**同一multi_asset内失败后，业务必须显式停止后续步骤**，不能只设置blocking就继续写Silver或历史。候选提升前先用同组必要校验，发布后check不能代替撤销错误写入。

### 2.2 拟新增/调整的文件

路径相对`lake_console/orchestrator/src/orchestrator/`。

| 文件 | 责任、接口和禁止项 |
| --- | --- |
| `tushare_download/contracts/stk_factor_pro.py` | 一份完整源字段、参数、模式、分页；其他消费者引用，不抄261字段。 |
| `tushare_download/contract_registry.py`、`dataset_transport_mapping.py` | 解除`@version`名称绑定、登记契约和HTTP；无旧名别名，不迁移其他消费者。 |
| `defs/run_contracts/stk_factor_pro.py` | 本数据集资产/check身份、执行日/目标日/轮次、输入和业务记录结构，以及§10单处维护的时点、sensor间隔、20日合并/5000行导出参数和验收目标；不请求网络、不复制既有DuckDB默认。 |
| `defs/run_contracts/asset_column_schemas.py` | 从源字段维护Raw日期VARCHAR、Silver日期DATE及259个可空DOUBLE的本地映射，不把存储类型回写源合同。 |
| `defs/paths.py`、`partitions.py` | 正式/候选路径与专属分区，不使用旧Lake、任意路径或新的配置入口。 |
| `defs/sensors/stock_factor_pro_trade_day_sensor.py` | 只注册今天和Q；停止使用最近7日参数。 |
| `defs/sensors/raw_tushare_stk_factor_pro_update_job_sensor.py` | 读取有界运行事实、因子就绪、Q一次条件和当前轮次；不计算完整变化股票或写Parquet。 |
| `defs/asset_guards/stk_factor_pro_readiness.py` | 输入就绪、已发布可读、缺股票、历史未完成分别判断；复用因子Raw的真实就绪语义，不用文件存在代替。 |
| `defs/io/stk_factor_pro_history.py` | 技术因子下载前的完整名单；下载后的可回刷集合；历史前输入再核对、窗口和完整发布依据。 |
| `defs/io/stk_factor_pro_download.py` | 完整unit消费、源候选/读回、组件通知适配；不重试业务写入，不把实际开始记录藏在进度回调。 |
| `defs/io/stk_factor_pro_candidates.py`、`stk_factor_pro_publication.py` | 按日期批量合并、必要校验、同文件系统提升与逐文件记录；T日唯一来自日阶段，历史只合并d<T。 |
| `defs/checks/stk_factor_pro.py` | 两项检查的规格及纯校验，multi_asset内调用；不另定义同名check形成重复注册。 |
| `defs/assets/stk_factor_pro.py`、`jobs/stk_factor_pro.py` | multi_asset及唯一自动日更job；不创建线程、子进程、异步历史任务或新平台。 |
| `defs/ops/stk_factor_pro_history_repair.py`、`defs/jobs/stk_factor_pro_history_repair.py` | `repair_stk_factor_pro_history` op的4项必填配置/预检/历史复用与手动repair job装配；不注册自动sensor，不调用日下载/发布函数。 |
| `defs/bootstrap/stk_factor_pro_history.py` | 按§10.1对获准Prod范围分自然月导出；复用Prod只读事务和服务端named cursor，引用统一5000行批量转换保存/释放，不累积整月、不经下载器。当前未获真实范围/源截止及正式执行批准，不生成可越界执行入口。 |
| `defs/catalog/lake_assets.py`及定义装载入口 | 两资产事实登记；现有catalog不是动态生成所有运行定义的引擎。 |

依赖：装配→sensor/资产/check→本数据集业务函数→组件/既有DuckDB和路径。不得跨工程import Prod定义或Ops入口，不替换其他数据集配置/下载/写入。token和地址直接用组件现有配置单元读取。

### 2.3 业务函数的数据输入与输出

以下名称是待实现的本数据集内部函数，不是新增公共平台API；参数传dataclass/不可变记录，Parquet内容不放进sensor cursor。

| 函数 | 主要输入 | 输出与必须保证的行为 |
| --- | --- | --- |
| `select_stk_factor_pro_request(...)` | D、时点、日历、今天/Q结果、已存在run/实际开始事实、对应因子就绪 | 一个目标T及轮次或明确不执行原因；先Q后今天，Q日阶段失败未证实已齐、仍缺/未知则当天不继续；仅历史失败不挡今天。 |
| `require_stk_factor_pro_inputs(...)` | T、P、对应股票复权因子Raw因子路径及其真实就绪结果 | 已核对的T/P输入身份/指纹；不足就不下载，不能返回“没有变化”。 |
| `build_stk_factor_pro_history_plan(...)` | T/P完整因子、可信历史范围、T既有完整名单/待处理事实 | 在任何技术因子请求前保存完整名单；相同输入复用，输入修订重建并合入原未完成范围；T/P重比相等不抹掉旧待处理，仅有生命周期证明本无历史时记录明确原因。 |
| `download_stk_factor_pro_day(...)` | T、轮次、已持久化的开始事实 | 完整日unit及已保存候选；源少股票不缩减原变化名单，网络半unit不返回成功。 |
| `publish_stk_factor_pro_day(...)` | 本轮源候选、T已发布文件及目标预期 | Raw、Silver依次候选/校验/提升/读回的结果；按主键更新补入、旧未返回行保留。 |
| `select_stk_factor_pro_history_codes(...)` | 完整变化名单、T日技术行存在性、已确认全天停牌事实、`adj_factor`数据集T/P及既有完整历史发布记录 | 有T行，或无T行但已确认全天停牌的变化股，可进入本轮可回刷范围；两接口因子数值差异只诊断。无T非全天/停牌未知保留pending，不缩小完整名单。 |
| `download_stk_factor_pro_history(...)` | 可回刷代码/范围、下载前再次核对的股票复权因子数据集 | 下载前已保存实际scope的正式目标基础清单；全部约定历史unit候选及完整保存事实引用该清单，失败不逐只续传、不假造整批完成。 |
| `publish_stk_factor_pro_history(...)` | 完整历史源、名单/基准、现有d<T文件 | 仅更新d<T；历史响应的T仍完整留在源候选并用于核对，不覆盖日阶段T。 |
| `summarize_stk_factor_pro_result(...)` | 文件读回、两层checks、覆盖、完整名单/历史结果、错误 | 分别说明可读数据、缺股票、待回刷、两接口差异和本轮终态；不增加覆盖状态资产。 |
| `repair_stk_factor_pro_history(...)` | 手动配置指向的原T、原完整名单/可执行范围和原批次 | 不重新计算扩大授权范围；核对输入后复用同套下载/历史候选/发布/检查函数，只d<T，无BY_POINT或T提升。 |

## 3. 分区、时点与前日一次机会

### 3.1 分区注册

bootstrap先批准范围、核实SSE日历，再注册范围内开市日；文件写入及历史事件分别授权。部分Prod股票已有2017年历史，不能沿用旧2020年起点。

日常注册仅处理今天（若开市）和Q，注册与就绪分开：不等源或因子，不删除已注册旧历史，不注册未来/休市日期。没有有效日历不能用自然日减一。更新sensor只选已注册目标。

股票复权因子数据集的分区属于其现有资产和分区定义；sensor使用现行`raw_tushare_adj_factor_ready_for_trade_date(instance, T/P)`分别核对两个分区的就绪，不拿本数据集的分区登记代替上游就绪。补Q所需P可能早于本数据集的两日管理范围，不因此扩大技术因子自动管理窗口或替其他资产注册分区。

### 3.2 sensor按轻重顺序作决定

1. 校验正式根可用、Asia/Shanghai执行日期、有效日历的开市标志及19:00～午夜窗口；执行日休市直接跳过，不发起下载或消耗补Q机会。窗口前不做重扫描。
2. 确定今天/Q、当前已到达的固定半小时时点；先查同数据集活动run，有则跳过该时点，不积压。
3. 若Q应有代码仍缺、覆盖不能判断或日阶段失败且不能证实已齐，先检查是否已实际使用D补Q的一次机会。已使用且仍有这些问题则本执行日停止自动推进，不能改选今天；仅历史阶段失败不等于Q日覆盖失败。
4. Q需要补且机会未用，检查Q及其P股票复权因子Raw因子真实就绪；未就绪只等待，不能下载Q，也不能绕过Q去今天。Q日阶段满足条件后可以考虑今天，不能仅因历史pending重新补Q日数据；原目标日pending通过§4.1手动入口处理，不把它显示成代码覆盖不足。
5. 今天的候选同样先核T/P因子；尚缺股票、覆盖未知或本目标T明确历史待处理，可进入后续时点。代码已齐、必要处理/历史已完成且股票复权因子数据集输入未修订时停止下载，但sensor继续轻量时点评估输入身份；输入修订则重新提交本job，不无条件持续取源。不能用股票已齐抹掉历史未完成。
6. 构造一个T的RunRequest，写计划日期/时点、用途为补Q或更新今天、前日业务attempt固定为1；sensor不取技术因子、不保存变化清单。

更早旧洞只保留诊断，不因最近7日旧逻辑继续全扫、自动补或阻断。例：周一补周五仍缺，周一不做当天；周二只自动核周一，周五已变成更早旧洞，报告管理员而不是继续自动补周五。不能偷偷把它改成“任何历史旧洞永远挡住新日”。

### 3.3 固定时点、去重与午夜

每时点至多一个目标job；19:00给Q补采占用后，不在其结束时立即补排同一19:00的今天任务，而等下一个可用时点。长任务跨过19:30则该时点跳过，不能20:00前连续追补几轮。上海本地时间位于`[19:00, D+1 00:00)`时，取`slot=floor((local_now - D日19:00)/30分钟)`，只允许0～9，计划时点为`D日19:00+slot×30分钟`；只考虑当前slot，不遍历补发更早slot。活动任务导致跳过时把D/slot记入小型cursor状态，相同时点已有持久run则不再提交；重启后仍只算当前slot并核对持久run，不从0回放。cursor不是前日机会或实际执行的事实源；更新sensor使用§10的60秒最小评估间隔，注册sensor为600秒；它们不等于业务30分钟。评估可能因daemon负载延后，不承诺恰好每60秒执行，也不为延后补发过往slot。

今日正常轮次使用`build_asset_update_run_key(subject=..., unit_id=执行日+目标日+固定时点)`，同轮去重，新时点新key。前日一次不能改用不断变化的时点key或业务attempt=2：使用`build_repair_attempt_run_key(subject=..., repair_scope_id=Q, attempt=1, attempt_scope=执行日D+提交序号)`区分§3.4中获准的预检未开始重新发起，业务attempt始终为1。现有builder只是字符串组合，不会自动执行次数规则；还必须核对持久化的实际开始事实。提交序号不是下载重试次数，也不是额外业务机会。

到D+1的00:00不提交新run。排队run真正开始时再查截止：过期不进入源下载/发布；午夜前已实际开始执行的run可正常结束。历史前校验输入与用户取消仍执行，不能因允许越午夜完成就忽略输入已变。sensor重启或cursor重置不能重置前日次数与已用轮次。

### 3.4 什么算已经用过前日一次

“有run”与“业务下载已开始”分开：创建/排队只占位，预检因上游不就绪退出且未开始技术因子下载，不消耗一次。日历、T/P因子复核、完整名单保存均属于网络下载前准备。组件内部页/重试仍是同一次业务下载。

在**第一个技术因子网络请求前**，先持久化本run的“开始下载”事实，包含D、T=Q、用途、业务attempt=1、run_id、计划时点和完整名单摘要；保存失败就不联网。写成后进程退出、请求是否发出不明时，保守视为已使用，不能自动再赌一次。这里不承诺精确捕捉真实网络报文发出的瞬间。

使用现有Dagster事件/运行事实，不新建额度表、锁或平台。multi_asset生成器先`yield AssetObservation(...)`；恢复后按当前run/目标和观察身份**显式读回确认该开始事实已经持久化**，确认成功才调用网络。不能只从生成器恢复推断保存成功，也不能只调用`context.log_event(...)`后立即请求，因为本机实现先放入事件缓冲，调用返回不等于已落库。读回失败不联网；写后退出仍保守已用。相应实现后须隔离证明事件保存/读取失败均不发网络、不同执行器下顺序有效、写后退出不重用机会；本轮没有运行此验证。

前日未开始后的重新发起采用以下具体规则，不靠重发已用key：

1. 每固定时点最多提交一个run；读取本job、本执行日D、前日目标Q和用途的持久run/事件事实，至多取11条以检测超过当日10时点的异常。使用受支持的原生job/时间/分区过滤，再核对run_config中的D、T、用途和slot，不能假设Dagster提供任意run_config SQL过滤；过滤与预算须隔离验证。
2. 任何active run先占位。任何匹配的持久“开始下载”即表明业务一次已用，无论run最终状态和cursor内容，都不再自动补Q。不能遍历全量run历史。
3. 只有全部既有terminal发起都明确记录`PRECHECK_NO_DOWNLOAD`、且没有开始事实时，才允许在下一未用时点再次发起。证据缺失、进程失联或无法确认是否下载一律不猜0次，报告人工处理。
4. `submission_no`按已有持久发起单调+1，至多10；业务`attempt=1`不变，key的`attempt_scope`使用D加提交序号。同slot不重发，不使用随机key、业务attempt=2或每次tick自增；cursor不是序号和机会的权威。
5. job预检确认上游未就绪时，生成器yield含`PRECHECK_NO_DOWNLOAD`、D/Q/slot/submission_no的观察并正常结束，不产生数据可用物化。写不成该结果的终态不得当成明确未用。正式实现以隔离测试证明事件持久顺序和重启恢复。

这只区分同一次业务机会前的未开始发起，不新增任务恢复平台、额度管理或下载重试能力。


## 4. job内的严格顺序与Dagster编码组织

```text
sensor：日历/时点/前日一次规则 → 股票复权因子Raw T/P就绪 → 提交单T job
  ↓
job开头：截止与唯一写入 → 再核T/P就绪
  → 读取T/P并比较 → 完整保存T回刷名单/待处理原因
  → 持久化本轮开始下载事实
  ↓
下载T日全部页 → 保存完整日unit → 必要字段/主键/日期检查
  → 与T已发布文件按主键更新/补入
  → 发布日Raw并读回/check → 发布日Silver并读回/check
  → 已发布日数据可供业务读取（不等覆盖和全部历史完成）
  ↓
从完整T名单核T技术行存在，或已确认全天停牌
  → adj_factor数据集T/P为回刷依据；技术行因子差异只诊断
  → 已完整发布的同基准/范围历史不重复
  → 记录尚不能回刷股票，名单不丢、不按返回集合缩小
  → 历史前再次核对股票复权因子数据集输入
  → 下载本轮可执行股票全部约定历史窗口并完整保存
  → 按日期批量合并/校验/发布d<T的Raw和Silver
  ↓
分别报告日数据可读、代码覆盖、完整名单与历史完成/待处理
```

此处“日数据先发布、历史后处理”已确认，不再列待拍板。股票复权因子数据集T/P未就绪就停在job预检，不允许按旧建议继续日下载。两接口因子值不同按§12.1已确认规则只诊断，不阻断该股日Raw/Silver或历史，也不改源值。这不证明返回的指标结果已按新基准修正，只证明按规定adj_factor输入完成了本次下载/发布。

编码组织采用两个`AssetSpec`和两个`AssetCheckSpec`的multi_asset，job的selection包含该定义的两个资产及两项check；选择同一个`cn_a_stock_factor_pro_trade_days`。同步函数依次调用§2.3业务函数；没有下载线程/进程或IPC职责下沉组件。

日阶段每资产最多产生一次输出：Raw已通过候选验收并完成提升/读回后，`yield MaterializeResult(asset_key=Raw, ...)`，再yield Raw检查结果；失败显式退出后续。然后同样处理Silver及其check。合法0新增但存在旧文件时只核真实结果；首次空结果不造空文件或虚假可用物化，使用skippable处理并记录原因。源少股票但有有效行不走“检查失败”。

日更和手动repair均沿用原对象历史窗口，结束日期可以是原T；这不是全市场BY_POINT日更。完整保留该对象请求的T行用于来源和差异诊断，正式历史只改d<T，因此不重复yield日阶段同一个资产输出。历史日期采用显式`AssetMaterialization(asset_key, partition=d, metadata=...)`；对应check使用本机已有的`AssetCheckEvaluation(partition=d, blocking=True, ...)`并关联该次物化。当前`AssetCheckResult`没有partition参数，禁止自造。事件要按正常run写入，不把日常更新变成runless补记。

历史事件应在文件读回后真实产生，并批量读取本run本批已产生的物化记录，构造`target_materialization_data`再记录历史检查；不能每日期深扫全部event history。`context.log_event`的缓冲与生成器事件实际处理时点须在隔离instance验证。相应API依据与当前实现见§9，尚未声称定义装载/事件关联已验收。

历史下载/处理失败时，已发布的日Raw/Silver不回滚、不删除，不要求业务等待跨文件快照。run可失败且历史pending，与日文件及对应检查真实通过同时存在。不得通过把失败run整体当作“没有任何可用数据”抹掉先前发布。

### 4.1 管理员手动历史repair入口

管理员已确认新增`raw_tushare_stk_factor_pro_repair_job`。它是手动op job，不是另一个自动日更，不注册schedule/sensor；正常自动job继续包含自己的历史步骤。入口只恢复**原目标T完整名单与原始起止范围内**的历史，不发T全市场BY_POINT日请求、不执行T日发布，不改成今天，不追加名单外股票或延长历史范围，不修复日阶段失败。

拟新增`defs/jobs/stk_factor_pro_history_repair.py`采用现行repair模式：`@dg.job(name="raw_tushare_stk_factor_pro_repair_job")`内仅调用`repair_stk_factor_pro_history()`；该op定义在`defs/ops/stk_factor_pro_history_repair.py`，使用`@dg.op(name="repair_stk_factor_pro_history", out={}, required_resource_keys={"lake_root", "duckdb"}, config_schema=...)`，从`context.op_config`读取以下封闭配置。该op是只产观察/物化/check事件的生成器，`out={}`明确无普通数据输出，不能保留默认required result却不yield Output，导致写完历史后才因缺输出失败；本机decorator及生成器输出推断代码已核对，仍须隔离定义/事件测试。job本身不设交易日分区；目标T显式在配置，历史事件按实际d指定partition，不伪造“本job只物化T”。

| 配置 | 类型、必填/默认与校验 | 含义和消费者 |
| --- | --- | --- |
| `target_trade_date` | 必填str，合法规范`YYYY-MM-DD`，须等于原记录T并是日历开市日。 | 定位原目标；不是新范围或当前日期。原P从日历/原记录核对，不允许任意传入。 |
| `source_run_id` | 必填str，合法Dagster run身份；所属job仅允许本数据集自动job或此repair job，原记录T必须相同。 | 读取原批次受控metadata中的完整plan/ranges及历史源/发布记录；可指向上次repair，使再次恢复使用其完整候选。 |
| `expected_history_plan_digest` | 必填str，64位SHA-256标准十六进制。 | 与原完整plan内容摘要精确匹配，非只比版本或数量；不接收人工拼股票清单。 |
| `expected_history_ranges_digest` | 必填str，64位SHA-256标准十六进制。 | 锚定原完整`history-ranges.parquet`解析后、按代码/起止排序的完整范围摘要（不把当前因子数值放入这个范围摘要），而不是旧run可执行16股子集；原17股中后来满足条件者仍可在原范围处理。 |
| `reuse_complete_source` | bool，默认`true`。 | true允许复用本次实际范围完全匹配的有效历史完整源及已发布事实；false明确要求重取本次可执行原范围的历史源，忽略旧下载候选和历史完成去重。不会绕过资格/输入/目标冲突检查，不追加范围。 |

这些是本job的运行输入，来源及持久化是本次Dagster run_config；没有新增env/配置表/页面开关。仅repair op及同套历史业务函数消费，单run生效、不热变更。metadata展示原T、实际repair执行日、当前context.run_id、source_run_id、两个原授权摘要、当前输入摘要、reuse模式、缺T原对象单日确认次数/候选及实际历史范围/请求数，不展示token；自动slot/提交序号/补Q attempt留None。配置默认、错误输入和true/false分支均须测试。

开发完成后的操作入口是Dagster该job的Launchpad，提供如下准确层级；尖括号值须从原批次metadata复制真实值，当前没有本数据集正式run，以下不是现在可执行的任务或执行授权：

```yaml
ops:
  repair_stk_factor_pro_history:
    config:
      target_trade_date: "2026-10-21"
      source_run_id: "<原批次或上次repair的真实run_id>"
      expected_history_plan_digest: "<原完整plan的64位SHA-256>"
      expected_history_ranges_digest: "<原完整代码及范围的64位SHA-256>"
      reuse_complete_source: true
```

不必填自动job的执行日、slot、submission_no、补Q次数，也不从run_key解析执行参数；repair是管理员明确发起的历史维护，不消耗或重置自动补Q的一次机会。19:00～午夜、开市执行日限制约束自动提交；手动repair依本次明确授权的维护窗口执行，可恢复更早已登记原T，不擅自注册新分区或启用自动化。

repair的具体顺序：

1. 读取源run及其已持久化的名单/范围/历史记录引用；只在该run有界事件中定位，不按“最新成功”猜，也不全扫staging。实际路径必须解析到本数据集正式staging根、同T，拒绝外部路径、符号链接逃逸、缺记录或错job。source_run_id指向repair时直接核对其保存的原完整plan/ranges引用及原日更run身份，不把repair自己某轮小范围替换原17股授权范围。由已验证source_run、T和paths.py计算唯一的源完成/目标基础/逐文件发布记录位置；初始名单观察已给出该受控staging位置，不要求阶段结束事件存在，不递归猜最新任务或全扫目录。
2. 校验两项expected摘要、字段/合同版本、T/P日历与原完整范围，读取当前已就绪的`adj_factor`数据集原T/P实际值。**仅原范围内因子数值后来修订、名单/起止/契约未变时，在本repair run记录新依据和旧新差异，并按本次依据判断旧源/完成是否失效；不要求管理员再发一次或先重跑日阶段。**当前T/P重比成0变化也不抹掉原未完历史意图。不相关股票补入导致整文件hash变化仅记录，不使原16股无条件重下。原记录/摘要不符、P日历身份改变、源契约或处理规则变化、需追加股票/延长范围、原T/P未就绪或关键股缺权威值时明确停止，说明需修正哪项，不默用旧候选或扩大授权，也不承诺重发旧摘要即可解决。
3. 在原完整名单/原起止内重新核对未完成和可执行集合，不因当前T/P数值恢复相同就自动删掉原待修复对象。先查正式或原完整候选的目标T行；有行即可按普通路径，技术行因子数值差异只诊断。没有T行但已确认全天停牌无需补查，允许历史。对仍缺T且没有确认全天停牌的原名单股票，调用现有下载器`BY_OBJECT_RANGE`，原对象、`start_date=T, end_date=T`，每股一次完整unit查询；同一task可传多个缺T对象由组件扇开。只确认原T来源行现在是否已到，不发全市场BY_POINT、不提升T、不把今天行当原T行。若返回合法T行即可进入原历史范围；无行仍pending，盘中停牌不享受全天例外，停牌未知也不能当成全天。
   每个手动run对这类股票至多一次完整unit查询，分页/有限重试按契约；不在单run轮询等到有行。完整261字段结果只保存到本repair staging的`source/target-day-confirmation/`，另记该类unit/返回行/候选摘要，作为资格证据，不混入主历史source-complete的预期unit集合。metadata显示查询股票/次数/行数和候选位置；即使技术因子数值仍不同也不阻断。有此窄查询才不会永久锁死旧16股，但不得查询原完整名单之外对象或扩大原日期。
4. `reuse_complete_source=true`时，先按稳定输入跳过此前**整批完整发布有效**的历史范围；再对本次剩余可执行集合计算实际scope_digest。只有与本次范围完全一致、契约/因子输入有效、全部历史unit及读回都通过的source-complete才复用后续。旧16股源不能假充新17股完整：缺完整证明时本次可执行scope全批重下，不逐只拿旧下载片段补缝。此前16股已经整批发布则可跳过，后来可执行第17股独立形成此次实际范围，这不是部分下载续传。
5. `reuse_complete_source=false`时忽略旧源完整候选及已发布去重，重新下载原完整范围内本次具备资格的全部代码/窗口；不因已发布过就不请求源。用于管理员主动取得后来修订的来源结果；仍须T/P/contract有效，不等于允许绕过输入失效。false不伪造缺T或把pending例外扩大。
6. 复用`download_stk_factor_pro_history`、`publish_stk_factor_pro_history`及同组validator/check。历史查询原窗口可包含T、完整源原文保留T，但只合并/发布d<T的两层；不得调用`download_stk_factor_pro_day`或`publish_stk_factor_pro_day`。若本次无可执行范围，说明已完成或哪些仍pending，不伪造原完整名单全完成。
7. 新历史源、scope、提升意图、checkpoint及完成结果写在`.../trade_date=<T>/run_id=<本repair run>/`，保留原完整plan/ranges的路径、两个授权摘要及source_run引用，不覆盖原run。当前repair的`history-plan.json`记录原授权引用、当前T/P因子依据、数值修订和本次范围；metadata将原完整名单/范围摘要与本次输入/可执行scope分开。本run首次名单保存及观察必须在步骤2核对完成后、步骤3任何目标T确认请求之前执行，给出下次完整repair配置：source_run_id=本repair run，两个expected摘要仍是原完整授权摘要，默认reuse_complete_source=true；后续在本步骤补充实际范围和文件结果，不把首次观察推迟到全部下载后。真实源/发布完成仍由文件读回决定，不能靠这份配置伪造完成。要复用R1保存的候选，下一次必须引用R1；继续引用原R0不会自动找到R1，不能承诺旧配置零网络恢复。不能拿当前repair的16股小范围或新依据摘要替换原完整17股授权摘要。部分正式文件已写时按自身提升记录/读回继续；外部目标冲突停止，不覆盖未知新数据。
8. 按实际d<T发出两资产物化与原有两项check的分区事件；不为repair增加check定义、不物化或重发T检查。原T仅可有摘要观察用于说明历史状态，不能把它显示成T重新下载/发布成功。成功、失败、取消均说明原完整名单与本次范围，已发布数据保留可读。

不配置op/job外层自动重试；组件同页有限重试继续适用。新手动run使用false即主动重取本次可执行原范围，不能承诺同false配置再次发起零网络；当前run已保存完整源后，后续合并/发布处理不再重复下载。若R1完整取源后退出，下一次要省网络须复制R1给出的配置，以source_run_id=R1、reuse_complete_source=true读取其候选；继续false发R2则再次请求。重复执行不重复删数据或扩大范围，幂等不等于所有配置均无网络；不提供分页/逐股续传。

### 4.2 自动、手动与bootstrap的写入互斥

更新sensor的活动任务判断必须同时覆盖`raw_tushare_stk_factor_pro_update_job`及`raw_tushare_stk_factor_pro_repair_job`，不能repair运行时照常发日更新。repair入口也要检查本数据集其他活动写入并排除自身；只看自动job不足以防两个人工repair冲突。

正式手动repair在明确维护窗口下进行：先暂停本数据集自动发起、确认没有排队/运行中的日更或另一repair、确认bootstrap未执行，再启动获准repair；处理期间不同时启动其他写入，完成后按运营安排恢复自动化。本轮不执行暂停/恢复、不新增全机锁或下载器协调；现行Dagster运行约束和维护流程是否真实覆盖手动/队列竞争，编码前须核对当前配置/调用链及设计，实现在隔离环境后验证，不能声称一次sensor查询足以解决并发竞态。发现冲突就停止/等待，不写文件。

bootstrap也必须处于互斥维护窗口；它可能不是Dagster run，不能只查两job就断言bootstrap未写。所有写入继续使用候选、目标指纹、完整校验及逐文件提升，意外外部变化停下；这些要求不增加快照或多文件事务承诺。

## 5. 完整回刷名单与本轮候选记录

### 5.1 先名单，后技术因子下载

每次同T的job开头都用本次`adj_factor`数据集的T/P重新核对输入。输入和契约/范围一致时复用**完整名单**，不是复用上一轮的可回刷子集；输入修订则写新修订并合入原未完成范围，保留旧待处理的出处和解释。自动与手动一致：即使修订后T/P相等也不删除旧未完历史，仅生命周期证明该股本无待刷历史时记录依据和排除原因。不能因本轮源少了一只、源超时、股票暂时无T行就把它从变化名单删除。

比较以T/P的`FULL OUTER JOIN`按代码显式对应，再并入本数据集可信既有历史/同一目标T旧pending中明确应核对的有界代码范围；不能只以T为左边，也不能inner join后漏掉P有T无旧股。至少区分两日都有且变化/不变、T有P无、P有T无、以及既有范围/旧pending证明应核对但两日都缺。后两类没有生命周期或其他明确解释时保留无法判断，不写“0变化”；证明退市也要留下解释，不能静默删除待处理。生命周期可证明的真新股不造上市前历史，单列新股结论；旧股票缺P保留原因。这是本数据集有界对象比较，不新增全市场覆盖发布门槛。没有变化必须能证明输入已检查；股票复权因子Raw文件就绪不意味着每只股票都必有两日值。

只比较股票复权因子数据集值，不新增任意浮点阈值。需要更新历史的变化股从可信既有最早日期到T；无既有历史时解释新上市或异常。最早日期取初始化验收/可信范围或有界聚合，不在sensor逐tick扫描全湖。修订后的因子恢复旧值不取消原未完回刷；下载和发布仍应完成原范围，不能把“写了新清单”当成旧任务自动完成。

### 5.2 下载后确定可回刷集合，全天停牌可无T行

完整变化名单以现有`adj_factor`数据集T/P为依据，并合入同一原T尚未完成的历史范围；修订后重新相等不抹掉原待处理。对尚无有效完整历史发布事实的变化股票：有目标T技术行，或者虽然没有T行但最终停牌事实已确认全天停牌，均可进入本轮回刷。技术行`adj_factor`与股票复权因子数据集数值不同只记录股票/T/两值/来源批次及输入身份，不作为等值门槛，不使check失败，也不反复等待相等。

全天停牌资格与当日覆盖共用同一份已核对输入：先用现行suspend_d_ready_for_trade_date(instance, T)确认T的必要物化/检查事件ready，再核对最终silver_stock_suspend_daily文件实际日期、ts_code/trade_date/suspend_type/suspend_timing必需字段及文件指纹，保存本次使用依据；不另读confirmed事实叠加。仅最终行suspend_type=S且suspend_timing为NULL表示全天；时段非空为盘中。无T行且非全天停牌（包括盘中停牌）仍等待补T；事件未就绪、文件不匹配或字段不足均记停牌输入未知，只使无T例外不成立及覆盖未知，不能挡住已有T行股票的历史或有效日数据发布。全天停牌例外只允许原约定d<T历史处理，不伪造T，不替其他缺T对象放宽。两日缺因子、旧股无P等不能比较的问题仍按§5.1明确保留，不以技术行差异代替这些判断。

例：完整名单17只，19:00有16只T行，剩1只无T且不是确认全天，则执行16并保留1；19:30仍复用完整17重新核最后1，不能只取前轮16。若最后1已确认全天停牌，则原范围可全部执行17，不等待其本来就可能没有的T行。前轮16整批完整发布可复用；第10只失败不属于完整发布，不能跳过前9只续传。

每次日更job及手动repair均以`adj_factor`数据集输入核对范围、修订及复用。Raw和本期Silver保留各自取得的技术因子源业务值，仅Silver转换日期；不会把源1改成股票复权因子数据集的2、按比例改价格或本地重算指标。这不构成源指标已经按新基准重新计算正确的证明；保留差异供排障，不另加未经批准的阻断检查。

### 5.3 文件与结构

日更本轮候选和业务记录位于`/Volumes/datasource/data_lake_staging/stk_factor_pro/trade_date=<T>/run_id=<创建run>/`，统一由`defs/paths.py`生成。新run引用旧记录须核对同T、合法根和身份；自动新轮仍重新取当日源，不把旧source当成新请求；手动repair按§4.1只处理原历史，不进入日下载。

| 文件/记录 | 必须包含和边界 |
| --- | --- |
| `history-plan.json` | 格式版本、T/P、契约名/独立version/content_digest、完整因子输入指纹、完整名单文件路径/摘要、修订前记录位置、变更原因、代码数、可信最早日期依据。下载前完整保存并读回。 |
| `history-ranges.parquet` | 全部变化/待判定代码、T/P因子值及是否存在、起止、来源目标日/原待处理出处；不截断前N个。新股与缺P原因明确。 |
| 本轮可回刷记录 | 完整名单摘要、本轮T行存在/已确认全天停牌依据、可执行代码、无T非全天/停牌未知/已完成原因及两接口因子差异诊断；与完整名单分开，不能拿它替代下轮完整名单。 |
| `source/`、`source-files.parquet` | 完整261字段日/历史unit源候选，逐unit保存/读回/释放；全unit范围、身份、路径、指纹、源与保存行数。历史unit中的T行仍完整保留。 |
| `source/day/source-complete.json`、`source/history/source-complete.json` | 相对本轮staging目录；两阶段各自完整记录，不共享一张日加全部历史门槛。字段见下文。日阶段保存完整即可进入日发布，不等历史源；历史阶段只有本轮可执行股票的全部窗口完整才生成。它不表示全市场已齐，也不表示完整变化名单已全部处理。 |
| `publication/` | 按日/历史阶段、日期/层保存原目标、候选、提升意图和读回结果；历史下载前先保存target-basis.parquet及其清单摘要，逐文件结构和恢复顺序见§8.1。日T与历史d<T不混，自身已提交与外部冲突分开。 |
| `publication-complete.json` | 对明确阶段和范围的完整物理发布事实；历史须本轮可执行集合全部约定原键已刷新、文件已发布读回才可形成，保存各date/layer该scope发布后内容摘要/数量及算法版本。源完整但漏原键仍pending，不生成整scope发布完成。其余待处理仍保留在完整名单记录。 |
| 既有事件metadata和本轮诊断清单 | 显示日可读、应有/本轮返回/已发布集合摘要、完整缺失清单位置、历史状态、前日一次开始事实；不新建覆盖状态资产、额度表或第二个统一平台。 |

两份`source-complete.json`采用相同结构：`record_version`、`phase(day/history)`、`execution_day`、`target_trade_date`、`previous_trade_date`、`purpose(previous_day/today/manual_repair)`、`scheduled_slot`、`submission_no`、`creator_run_id`、`contract_name/version/content_digest`、`history_plan_path/digest/revision`、原授权`origin_history_plan_digest/origin_history_ranges_digest`（repair必填）、稳定`history_input_digest`（历史阶段必填）、本阶段`scope_digest`、`expected_units`及其完整范围摘要、`files_manifest_path/digest`、`target_basis_manifest_path/digest`（history必填，下载前持久化）、`completed_unit_count`、`verified_at`。日阶段expected_units为T全市场这一个完整unit；历史阶段为本轮可回刷股票×已约定窗口，不能拿完整变化17只与本轮可执行16只混为同一范围。只有全部预期unit与文件内容/身份/范围对应、源/保存计数及读回通过后，才原子写该阶段完成记录；不能仅凭unit数相等验收。

手动repair只生成本run的`source/history/source-complete.json`，不创建假的日阶段完整记录。其`purpose=manual_repair`，`execution_day`为本次repair真正开始的上海日期，`target_trade_date=T`仍取原目标；`scheduled_slot`、`submission_no`及自动业务attempt均为`None`，不伪造19点或补Q机会。`creator_run_id`取当前context.run_id，`source_run_id`取五字段配置指定的原run，原P/完整plan/ranges及原授权摘要从受控记录派生；其他身份不增加为第六个手动配置。自动记录的execution_day仍为原计划D，跨午夜完成不改D；`verified_at`记录实际带时区的验证时间。

完整名单保存/读回后，在开始下载观察之前先`yield AssetObservation`记录当前Raw资产T的`history_plan_path/digest/revision`、T/P、D/轮次、创建run、输入摘要和paths.py生成的受控staging目录及约定记录相对位置；恢复后按身份读回确认。由已验证run身份计算唯一source-complete/target-basis/publication路径，再读回核对，源完成落盘后尚未写结束事件也能恢复；不依赖最新成功物化或结束事件，不全扫目录。这样下载失败也能从同T有界观察/运行事实找回完整名单，不依赖成功物化。自动job首次名单观察与下载开始观察是至多两条起始观察，后续阶段另计预算；不能把它们藏在零成本描述里。具体事件查询接口/上界和修订关联仍须隔离验证，不许无界遍历staging或全历史run。源/发布完成记录是业务恢复事实，不拿观察写成功代替物理读回。手动repair的名单/开始/完成观察均使用manual_repair用途和当前context.run_id，不将它们计入更新sensor只针对自动job+previous_day的机会统计。

历史阶段稳定`history_input_digest`仅由**该完成记录实际scope内**的原T/P日期、按代码排序的当前权威T/P值和代码/起止、源契约内容及处理版本生成，不包含原完整名单中本scope以外股票的值，不含新run_id、诊断样本或新manifest路径。原完整17股的授权摘要另存，不能混成旧16股完成依据。原expected完整plan/ranges摘要锚定授权记录，稳定输入摘要判断源候选是否有效，当前文件路径/创建run只供追溯；不能因为新repair的manifest不同就无条件重下。

跨轮历史复用按股票代码、对应因子值、历史范围、源契约/清洗版本及此前**整批完整发布**事实核对；整份T/P文件sha只用于追溯，补新股改变其sha不能使原17只全部重下。日T文件正常增加股票也不能让d<T历史失效。每轮新run_id只标识本轮，现有`build_batch_id`强制含producer_run_id，不能把它的不同digest当成稳定业务输入已改变。已完成范围当前整文件sha未变走快路；变了按§8.1只核该范围全部业务值和数量，其他股票合法增改不令原完成失效，该范围内容不明变化则停止，不拿旧源重盖。

metadata/cursor只放摘要和位置；cursor按UTF-8计，常态目标2KiB、复杂3KiB、硬上限8KiB。不能靠清空cursor重新获得前日一次。完整名单/诊断原文不塞cursor；超出上限应缩小摘要，不截断真实业务范围。

## 6. 下载契约、线程、进度、错误与取消

完整契约名`stk_factor_pro`，独立version，不加来源前缀或`@1`。完整261业务字段含ts_code/trade_date及259数值；本地辅助列不进入接口fields。普通单日`DownloadTask(..., mode=BY_POINT, points=(T,))`，历史`BY_OBJECT_RANGE`；代码扇开在组件内，业务规划范围/窗口。相同代码多窗口分次任务，同任务重复object_code被1102拒绝。

分页暂定limit10000、offset从0步进10000、短页/空页结束、满页继续；属于源契约，不让业务传fields/limit/offset/token/地址。仍须有界真实核验，不能称已实测。每unit全部页取全后交业务一次，业务必要校验、候选落盘/读回后释放，不积累全历史内存。

`TushareDownloader.load()`和`with downloader.download(...) as session`沿用现接口；创建、使用、回调、关闭同线程。DG执行进程直接在执行线程调用，页面业务另开下载线程；跨线程/进程通信由业务接入层负责。组件不创建线程/子进程、锁、额度或全机限频，连接配置直接复用现有读取方法。

PAGE_COMPLETED/RETRY_SCHEDULED/UNIT_COMPLETED只传摘要，业务不在通知中写数据。UNIT_COMPLETED在交付前，100%不等于保存、日发布或历史全完。普通观察回调异常由组件隔离；业务校验/保存异常停止消费并关闭session，不交给组件重试业务写入。

组件错误码保持现有1001配置、1101契约、1102输入、1201权限/参数、1202限频、1203临时源、1204无有效响应、1205协议、1302容量、1304清理/关闭、1401取消、1501未分类源错误。业务原因集中登记，不随意扩展组件错误码。组件同页有限重试不消耗新的前日机会；一次已开始的前日日阶段失败且不能证明已齐，或仍缺/未知，则当天不自动补第二次或推进今天；仅历史失败而Q日阶段已齐不阻止今天。今天的临时源错误可等后续计划时点，永久输入/契约/权限、业务结构或目标冲突先报告停下，不盲重试。

分页/退避取消不交付半unit；完成通知时取消仍交完整当前unit再停，末unit可正常下载完成。业务取消后不领下一unit或提升新文件；replace前检查取消，当前文件一旦已经替换则尽力完成本文件fsync/读回/checkpoint后停止下一文件，失败保留intent供恢复，不回滚已发布内容。网络可能等返回/超时，不强杀线程。with/finally关闭资源，已发布文件保留；午夜允许已运行任务结束，不模拟用户取消。历史前输入变了则停历史并留待处理，不能额外自动启动新任务或把它写成全部完成。

## 7. 同轮恢复、下一轮与前日一次限制

| 场景 | 行为 |
| --- | --- |
| 技术下载前上游未就绪 | 无网络、不耗前日机会；保留明确PRECHECK_NO_DOWNLOAD结果。已创建run的重新发起按§3.4只在证明确实未下载时产生新提交序号，不能伪称同key会重跑。 |
| 日源unit未完整保存 | 同轮获准重执行从完整日下载开始，不能拿前几页发布；已开始的前日自动机会不会因此恢复。 |
| 日源完整、日发布失败 | 同轮核对后复用日源候选，逐文件继续；不强迫重下已有完整源。前日不得自动追加一次重执行来突破一次规则；手动处理须明确授权。 |
| 日已发布、部分历史源失败 | 日文件保留可读；历史本轮约定可执行集合从完整下载范围重做，不逐页/逐股接续。完整名单和剩余原因保留。 |
| 历史源完整、后续发布失败 | 核对本轮身份/股票复权因子数据集/范围/全部源及目标后继续历史合并发布，网络可为0；这是同轮恢复，不代表下一轮无需当日新请求。 |
| 同T下一固定时点 | 仅今天且仍允许继续时重新取日源；重新核本T完整名单及本轮T行，不把前一目标Q的历史转成今天任务。已完整发布历史按稳定依据复用，不能用前轮可回刷16只替代完整17只。 |
| 前日日阶段已开始后失败且不能证明已齐、仍缺或覆盖未知 | 本D不自动第二次补Q，不改轮次key重发，不继续今天；已有数据仍可读。若仅历史失败而Q日阶段/覆盖有效已齐，则可推进今天并保留历史pending，不能仅按run终态判断。 |
| 目标/因子在恢复前变化 | 先用旧intent认清自身是否已实际提交，只补该旧依据的物理事实，再核本次权威输入/范围；输入修订保留原未完范围并令不匹配源失效，旧基准完成不是新依据完成。正式scope内容已被更晚同股或未知写入改变则停止，不重登记当前hash放行旧源。 |
| 文件已提升但记录失败 | 依据提升意图、目标/候选指纹及读回确认，补记录，不再盲覆盖；状态/事件失败不回滚业务数据。 |

“未完整从头、完整可复用”现在按日/历史明确阶段适用，不能继续使用一张“日加全部历史都下载完”记录阻挡先发布日数据。下载进度不创建完成事实；自动前日次数与业务候选能否复用是两个判断，不能拿后者绕过前者。

## 8. 合并与逐文件发布

Raw正式路径`/Volumes/datasource/data_lake/raw/tushare/stk_factor_pro/trade_date=<d>/data.parquet`；Silver为`/Volumes/datasource/data_lake/silver/stock_factor_pro/trade_date=<d>/data.parquet`；候选仅正式staging根。无旧Lake、Kopia、备份或跨文件快照。

日T以已有合法文件为基础，按`(ts_code, trade_date)`更新补入。源后轮缺旧键、合法空结果、停牌集合变化都不授权删除旧行；首次无旧文件以空基础开始。B基础行、U新唯一键、交集K，最终`B-K+U`。例：旧4000，本轮4800但漏回旧50，最终4850；数字是说明，不是门槛。输入重复键或非法日期仍拒绝，不靠随意去重/删行通过。

日Raw保存源日期字符串，Silver日期DATE，其余业务字段及对应行按原规则完整保留，后续新增清洗不是前置。合法NULL/负指标不误拒绝，非法日期不静默补NULL。Raw不按上市/停牌覆盖集合过滤来源额外合法行。清洗改变行数须批准的原因及样本对账。

T是日阶段的唯一正式更新来源。历史查询仍为完整起始日至T，全部源记录包括T保留在候选；T行保留来源/差异诊断，未返回T但已确认全天停牌不阻断；历史正式合并只取d<T。此处排除的是重复写入职责，不删除历史源原文、不少请求字段/缩短原约定源范围。历史行不要求adj_factor全部等于T因子，按其对应历史日期语义核验。以下载前目标基础清单对应的既有主键作为本scope应重取依据；完整网络源合法0行或漏原键时，已有有效源行仍可按主键更新/补入，未返回旧键保留，明确报告哪些未刷新，不删除旧数据、不新增blocking门槛，也不记整个scope已刷新完成。这是原历史范围/传输对账，不要求指标值一定改变、不要求技术行adj_factor相等，不增加第三项check。

目标基础清单的内容摘要不能反推出主键明细。生成候选前，先确认当前本scope仍符合已保存基础，再以该正式范围与完整源做主键差集；若已是受控自身提交，则读回该次已保存的差集结果。差集以`layer VARCHAR/ts_code VARCHAR/trade_date DATE`保存到本run的`publication/history/<d>/<layer>/unrefreshed-keys.parquet`，每日期/层独立、被intent引用后不可覆盖，不能用一个不断改写的文件令早先摘要失效。Raw源日期仅在差集关联时按已校验规则显式转换，不改变Raw源文。零缺项也保存明确零行及摘要；历史逐文件intent保存`unrefreshed_keys_path/digest/count`后才提升，日阶段三项为None。它是本批缺项诊断，不复制全部业务列或另建状态资产；源完整但有缺项可继续有效行合并，缺项未解决前不生成整个范围完成记录。恢复不能仅凭行数或范围内容摘要猜测哪些原键已刷新。

每日期每层按明确阶段合并一次，不每只股票就重写全市场全年文件。历史先完整保存约定源，再批量按日期合并Raw、对应Silver及检查；所有未更新股票保持相同。本scope权威T/P输入在下载前、完整源处理后首次历史提升前、写历史publication-complete前各有界核对一次，不逐页/逐文件重扫整份因子。启动时同原范围数值修订可在本run记录新依据；处理中再变则停止新提升，保留已经提交的事实和原未完范围，下次按新依据重入，不将旧完成套为新依据完成。

这里的历史合并专指自动日更的历史回刷阶段和手动repair历史发布阶段：按股票下载的结果进入按日期保存的既有全市场文件，更新该股历史并保留其他股票。正常日下载只合并T日文件，首次bootstrap没有旧文件时直接生成日期文件。**每批20个交易日已经确认**，是本地合并批次，不是下载unit、对象窗口或提交事务。

具体编码顺序：从本次完整历史范围和已核对SSE日历生成`d<T`的计划开市日期并集，去重、升序，按`STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS`切片；末批可以只有1～20日，不补足20日、不按20自然日切割。先检查所需历史分区已在获准初始化范围内登记；缺分区明确停下，不在repair或20日循环中擅自新增分区。日历日期属于规划范围，不意味着该股每天必须有数据；某日两层无旧文件、也无本批合法源行时跳过并说明，不造空文件/假物化。不存在旧文件但有合法源行时，以空基础构建并执行同样候选校验。

只有本轮可执行scope全部约定股票/窗口的源候选已完整保存，才进入第一批20日；不能边下载一只就改整年文件。每批一次规划至多40个Raw/Silver旧文件和对应源日期过滤，使用同一主要DuckDB连接做列式合并及校验，不在Python装全市场行或为每股重复写同一日期。Raw/Silver按日期逐文件提升，仍是每文件intent/checkpoint，不把20日当成整体原子事务。处理/记录完当前批次再取下一批，释放临时关系及已不需的批内对象；不要预先生成所有年份的最终候选后才发布。

20日参数、批次序号和日期范围只帮助本地计算组织及观察，不进入源unit/scope身份或业务内容版本；后续只改本地批次大小，不能据此宣布旧完整源失效或触发全历史重下。恢复权威仍是完整源、下载前目标依据及逐文件记录。源未完整则本次scope全部重下，20日边界不成为下载断点；源完整后合并/发布失败，核验后跳过自身已确认文件、继续未完成文件，末尾仍做整scope完成核对。已完成19日、第20日失败不重下历史源，也不把前19日回滚。

文件步骤：挂载、同文件系统、剩余空间、目标预期和唯一写入→完整候选必要校验→持久化提升意图→`os.replace()`→读回→逐文件完成。自身先前提交与外部合法修改分开；冲突停止不覆盖。Raw/Silver或多日期不是整体事务；每个job结束后当前已发布文件可读，后续失败不回滚、不要求读者切换一套跨文件快照。历史完成事实只说明按adj_factor数据集输入下载/发布的范围，不额外证明源指标已按新基准计算正确；不能把日可读等同全历史一致。

### 8.1 下载前目标依据、逐文件记录与恢复顺序

本节在现有stk_factor_pro候选/发布模块和run-scoped文件内实现，不增加平台、备份、锁或逐股下载断点。参考当前moneyflow_update_publication的intent/complete及stock_period_silver的rename后恢复，仅复用经过核对的算法，不带入资金流字段、阈值或writer锁。

**历史下载前保存目标依据。**本次实际可执行scope确定后，先按其已批准窗口及历史d<T日期，在publication/target-basis.parquet记录两层目标的路径、date/layer、是否存在、整文件sha256/行数，以及只含该scope代码/日期范围的主键数量、完整261业务列内容sha和algorithm_version；清单内容摘要在下载前原子保存并读回。记录缺文件和零行也要明确，不能略去；不复制261列数据或整个正式文件。历史source-complete必须引用这份清单及摘要，没有它不能宣称旧完整源可安全复用。该依据早于取源，因此源完整但尚未建提升意图时退出，后来同股被更新也不会无依据覆盖。

内容sha采用当前etf_daily_raw_content_hash_sql的形式：按契约固定字段顺序struct_pack，再to_json；以(ts_code, trade_date)排序、用换行string_agg后sha256，空集合计算sha256空串，另比数量和存在标志。Raw保留其日期源文，Silver按DATE等本层schema序列化；NULL按真实值编码，不能靠填值或舍入消差。记录固定算法版本及合同/处理版本；不同算法不能只看hash相同就混用。按日期/层有界批量聚合，不拼全历史字符串、不用Python逐行计算、不每股新建连接；单日期聚合和暂存开销计入§10。

| 记录 | 必备字段与写入时间 |
| --- | --- |
| target-basis清单 | record_version、creator/source_run、原T、实际scope_digest和history_input_digest、contract/processing版本；逐date/layer的受控target、exists、file_sha256/rows、scope_rows/content_sha256及algorithm_version。下载前完成；source-complete存其路径/摘要。 |
| 逐文件checkpoint | record_version、creator/source_run、phase、原T、实际d、layer、scope_digest、history_input_digest、contract/processing版本、source_manifest_digest、target-basis引用；target/candidate路径、prior_sha256（原不存在为NULL）、candidate_sha256/rows、expected_published_sha256、prior_scope_rows/content_sha256、expected_scope_rows/content_sha256及algorithm_version（分别由原基础和候选按相同scope计算）、mode(reuse/replace)、stage(intent/complete)及读回数量/摘要。候选校验后先保存intent，再replace，读回后complete。 |
| publication-complete | 完整实际scope及输入/来源摘要、全部预期日期/层、逐文件记录摘要和读回结果、各date/layer的scope发布后数量/content_sha256及algorithm_version；确认所有约定原键已刷新后才生成。网络完整记录不代替它。 |

记录临时文件flush/fsync后原子替换，并fsync父目录；候选文件也在replace前fsync，replace后fsync正式父目录。新run只在自己的目录追加已验证source_run的恢复结果及引用，不修改原run；无记录、摘要不符或路径越界不猜完成。已持久化intent的判断顺序如下，必须先认清自身提交，再判断输入是否仍能复用：

| 实际情况 | 编码处理 |
| --- | --- |
| 正式目标sha等于expected_published_sha256 | 无论candidate是否因rename消失，先核身份和必要读回，再补本run完成事实，不再次覆盖；旧输入的实际提交只按旧输入记事实，不据此宣布新输入已完成。 |
| 目标仍等于prior_sha256（含原不存在）、stage=intent，且候选身份/摘要有效 | replace前再次核目标、同文件系统、空间和取消，随后replace/fsync/读回/complete；不因下载进度100%跳过。候选缺失或变动停止说明，可从有效完整源重新构建但必须重验并写新的intent，不能沿旧候选摘要放行。 |
| 目标是第三种整文件内容，或complete后整文件变化 | 不沿旧intent替换。先按相同scope和算法核数量/内容sha：等于intent预计发布后scope时，只读回当前文件并在本run记录范围等价复用，不重放旧候选、不声称整文件字节仍相同；等于下载前基础scope时，从当前正式文件重建新候选和新intent保留其他股票。其余先核受控source_run链自身提交，无法解释或更晚同股改写则停止；候选错或身份错同样停止。 |

没有提升意图时也必须核对下载前target-basis：整文件未变可按原基础合并；整文件变了但本scope内容sha/数量仍相同，说明可能是其他股票合法更新，可以从当前正式文件重新构建候选、保留那些新行并记录本次实际prior，再走新intent。旧intent遇到第三种整文件内容同样不得直接replace：scope等于其expected_scope时只读回并记录本run范围等价复用，记录实际整文件sha及旧引用；scope等于prior_scope/下载前基础时重新构建候选并建立新intent。两条路径均保留旧intent，不改原run、不假称旧整文件完成记录仍精确匹配。除此之外scope改变且不能由已核验source_run链自身提交解释就停止，不能把当前hash重新登记为旧源依据。管理员明确false重新取源时，另行以当前正式目标建立下载前依据，不把它伪装成旧源复用。

跨轮跳过**此前整批完整发布**范围时，整文件sha未变复用其原读回事实；整文件变了则按相同算法批量核原完成范围的主键/全部业务值与数量。例：A/B已完成，后轮C更新同一历史文件，只要A/B范围内容未变就可复用；A/B行改变或缺失且不能由受控自身提交解释就停止说明。该核验不是逐股下载续传，不新增check定义或全湖扫描。所有检查均用实际范围和保存的基础/完成依据，不能在恢复时临时改变范围使其碰巧匹配。

## 9. 两个综合checks与事件

| 结果 | 合同与不能混淆的边界 |
| --- | --- |
| 输入就绪 | 股票复权因子Raw T/P完整复刻现有Raw因子必要check语义，sensor及job预检均必需；不用非空文件或Raw技术因子市场覆盖替代。 |
| Raw综合check | 可读/源字段类型/非空唯一主键/日期范围、完整unit源保存和B-K+U；股票未补齐不失败。 |
| Silver综合check | DATE、主键、对应Raw范围、完整业务字段/合法值及逐行对账；本期无新增过滤或填值，无数量比例门槛。 |
| 日可读/覆盖 | 文件及必要检查通过即可用；应有集合是T日上市人民币股票减全天停牌，盘中仍应有，按代码求差。上游覆盖依据未知不宣告补齐、不清空正式数据。本期Silver不额外过滤，成功生成后与Raw主键/行数对应；Raw源缺口与两层处理失败分别记录。 |
| 历史完成 | 完整名单、adj_factor数据集T/P、本轮范围及全部已发布事实对应；无T非全天/停牌未知/缺P不可伪装0变化。两接口因子差异不阻断历史完成，但诊断保留，不宣称源指标数学正确性已经证明。 |

生命周期采用`list_date <= T AND (delist_date IS NULL OR T < delist_date)`。全日停牌按§5.2先核suspend_d_ready_for_trade_date(T)及最终silver_stock_suspend_daily文件身份，再使用其`suspend_type='S' AND suspend_timing IS NULL`，时段非空是盘中；不能因为停牌输入未产生便认定没有停牌，不读取confirmed数据自行合成。该集合只判补采，不过滤Raw；T/P股票复权因子数据集硬门槛与其覆盖参考缺失不是同一个条件。

sensor与job复核均使用现行`raw_tushare_adj_factor_ready_for_trade_date(instance, trade_date)`，只针对T/P读取Raw因子物化及其3项检查事实，共2分区×3项check；它不是全市场股票覆盖证明。job再对实际两份Raw文件执行字段/日期/唯一性/正值等必要业务校验并比较。不得改用`batch_raw_adj_factor_lake_readiness`然后声称只扫两份Raw：当前实现即使layer=raw仍构造Silver路径、校验Silver并进入含生命周期的聚合，隐藏读写范围和成本不符合本次边界。本需求不修改该已有helper；sensor不算全名单，job显式处理无P与旧待处理。

每天检查定义始终两个，不按股票/字段/窗口新增。日阶段两资产各一个输出/check；历史涉及D个d<T日期时最多另有2D个物化和2D个检查结果，内容未变不伪造新内容。十个计划时点包含前日补采占用，不能预算成10次今天另加1次Q；此外还需计预检记录、下载开始/名单观察及历史事件，整晚不只两条事件。

已用Context7及本地安装代码核对`multi_asset(specs, check_specs, partitions_def)`、`AssetCheckSpec(blocking, partitions_def)`；同一步内阻断由业务显式执行。`AssetCheckResult`没有partition；历史`AssetCheckEvaluation`及`target_materialization_data`参考现行repair/资金流事件代码。相应实现后隔离验证：日物化后历史失败仍可读、检查真实绑定正确partition/run/materialization、重复输出不产生异常、观察持久化时点、历史批量取事件而非逐日深扫。静态代码核对不等于事件API运行验收。

发布前、读回与checks复用纯校验及本批聚合证据，文件改变不沿旧绿色。sensor只看今天/Q的有界结果及必要输入，不全湖或全事件扫描；超过100历史分区或分区×check数超过1000按治理批量聚合。覆盖诊断和历史待处理不新增状态资产，cursor不是事实源。

## 10. 配置、规模与性能门禁

不新增下载器频率/账号额度/线程/锁配置。组件现有2GiB单unit工作空间、64MiB响应、5/30/45秒超时、最多4次同页尝试及1/2/4秒退避沿用；工作空间不是进程总内存承诺，不重测用户拍板值。业务调度控制请求频率。

本数据集运行合同在拟新增`defs/run_contracts/stk_factor_pro.py`单处维护，随代码加载；以下数值已由管理员确认，不再写作“待拍板”。sensor装饰器、历史planner、bootstrap和验收代码均import相应常量，禁止在入口、脚本、测试之外另写一套业务默认。没有新增env、配置表、页面开关、任意run参数或运行中热更；修改常量须同步方案/LLD和消费者测试，代码重新加载后对新执行生效，既有run记录仍保留当时取值。

| 参数名/规则 | 已确认默认与来源/持久化 | 作用范围、消费者、生效与运维可见性 | 必须测试 |
| --- | --- | --- | --- |
| 首轮/后续/截止 | 管理员：只在开市执行日，19:00、固定30分钟、D+1 00:00，最后23:30，Asia/Shanghai；run_contracts单处代码规则。 | sensor选时点、run身份及job开跑复核；D/T/slot写run_config及metadata，不支持任意运行覆盖。 | 18:59/19:00/23:30/00:00、延迟与活动跨时点；使用模拟时钟。 |
| 管理日期/前日机会 | 今天及严格前交易日Q；每执行日1次业务下载，依持久实际开始事实；管理员决定。 | 注册、sensor、开始记录和恢复；metadata分别显示Q日覆盖、历史和机会，不因历史失败抹掉日完成。 | 仅今天/Q、无7日；未就绪未耗、已耗不重获、仅历史失败不挡今天。 |
| `STK_FACTOR_PRO_UPDATE_SENSOR_INTERVAL_SECONDS` | `60`秒；run_contracts代码常量。 | 更新sensor的`minimum_interval_seconds`；代码加载生效，定义可见并记录于评估摘要。只限评估频度，不改半小时slot、重启去重或午夜。 | 定义取统一常量；模拟多次tick不能一分钟下载一次或补发旧slot。 |
| `STK_FACTOR_PRO_PARTITION_SENSOR_INTERVAL_SECONDS` | `600`秒；同上。 | 注册sensor的`minimum_interval_seconds`；默认STOPPED，不等数据就绪；定义/评估摘要可见。 | 间隔与更新sensor分开，只注册真实今天/Q、不删除旧键、不造未来。 |
| `STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS` | `20`个交易日；同上，管理员确认。 | 自动历史和手动repair共用§8升序切批；run metadata记录取值、当前批日期/序号、完成文件与耗时。完整源后才合并，逐文件生效。 | 1/20/21/41日、节假日、无行日、末批和批间失败；不改变unit/历史范围，不新增分区。 |
| 对象历史下载窗口 | 每股可信最早已有日期至原T，一次完整unit；依已批准可信范围和run_contracts的规划规则，不默认按年切。 | history planner和下载函数，范围/digest保存到原完整plan/ranges；下载器扇开代码，分页按源契约。 | 未截短历史；20日合并不切请求；无法证明最早日期时不猜2017或2020。 |
| `STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS` | `5000`行；run_contracts代码常量。 | §10.1 planner/服务端cursor的itersize和fetchmany共用；bootstrap metadata记录月份、批数、保存行数及实际取值，单批落盘释放。 | 0/4999/5000/5001行、同一天跨批、月边界、日未完整重取；不得普通cursor/fetchall/累计整月。 |
| DuckDB资源 | **引用现有**`DEFAULT_DUCKDB_CONNECTION_SETTINGS`：16GB、4线程、临时目录`/Volumes/datasource/.goldenshare_duckdb_tmp`、512GB临时空间上限；事实源为`defs/duckdb_connection.py`，非本数据集新默认。 | asset/op通过既有`DuckDBResource.connect()`；离线bootstrap通过同一`connect_configured_duckdb()`；同任务同时只保留1个主要计算连接，传给本批函数复用并finally关闭。metadata从实际settings记录，不写死第二套值；不改其他调用者。4线程是SQL计算，不是4个下载对象。 | 替身证明同批不嵌套创建主要连接；隔离读取实际settings与原设置相符，关闭后释放；临时目录与run候选路径不能混用。 |
| 下载器容量/批内存估算 | 继续组件既有2GiB unit、64MiB响应；bootstrap128MiB工作空间估算/256MiB余量见下文。 | 组件限制只对Tushare；bootstrap估算不是新硬限、无新配置，也不是整个进程或DuckDB总内存承诺。512GB是spill上限而非预占，实际需核剩余空间。 | 不将数据库5000行套到Tushare容量；无隐式截断/缩字段；不为估算另拉5000行压测。 |
| 输入gate | T/P股票复权因子Raw就绪且job复核；管理员决定。 | sensor及job使用现行Raw helper；缺因子不网络，不把市场未全齐当成日发布门槛。 | 缺T/P均不下载；少股票仍允许合法日发布。 |
| 性能验收目标 | 同run_contracts单处`STK_FACTOR_PRO_SENSOR_TARGET_SECONDS=5`、`STK_FACTOR_PRO_DAY_UPDATE_TARGET_SECONDS=120`、`STK_FACTOR_PRO_HISTORY_REFERENCE_TARGET_SECONDS=1200`；管理员接受的初值。 | 分别用于sensor一次评估、无历史正常日更，以及类似17股原完整历史的成本外推比较；测试/验收报告记录样本、推算和目标，**不是运行超时、kill或任务请求预算**，不写入下载器限制。 | 模拟负载/隔离小批计时与独立报告；超目标先定位原因，不删除数据或强杀，也不据外推冒充全范围实测。 |

已核对当前`DuckDBResource.connect()`直接调用`connect_configured_duckdb()`，该函数在contextmanager中校验并关闭连接。使用本数据集原函数间传递连接，避免helper自行再开连接令16GB看似单份实为多份；传感器只在必要有界核验期间短暂持有连接，不与job计算连接放进一个全机额度设计。资源设置将来若在原模块获准统一改变，本数据集沿用原配置并记录实际值；本轮不修改它或其他数据集消费者。

| 场景 | 可确定的成本模型 | 仍需有界核验 |
| --- | --- | --- |
| 每轮预检/名单 | sensor只查候选T/P和已有状态；job读两因子文件并比较、保存完整名单，复用时仍重核输入。 | Raw事件gate的两日期三项check查询、job两Raw文件校验/比较、名单修订及前日机会证据定位成本；历史下载前/首次提升前/整scope完成前三次本scope权威输入核验，停牌ready与最终Silver输入一次共用；不能逐tick重做名单或逐文件重扫因子。 |
| 单轮日源 | 有界样本5568行×261字段，暂定10000页大小约1次正常请求，恰满须继续。 | 完整HTTP字节/耗时、候选读写、T旧文件与两层必要checks/覆盖成本。 |
| 晚间与前日 | 今天理论至多10固定时点，Q实际一次会占时点；无并发/积压。重试、分页、预检未开始再发及手动处理另计。 | 整晚源/合并/事件/候选留存峰值；不是下载组件请求总上限。 |
| 复权历史 | C代码、W窗口、D历史日期，正常请求`sum(floor(H_i/10000)+1)`；同页最多另加3倍尝试；稳定完整发布不重复。 | 完整名单与匹配子集、历史源T保留但d<T发布、下载前最多2D个date/layer基础行/哈希聚合；scope内容变更核验、旧全市场文件扫描/聚合、空间与事件批量读取。 |
| 同轮失败/完整候选 | 约定阶段未完整从头，完整可省网络但仍核输入/源/下载前target-basis；前日不能因此自动再用机会。 | 整阶段重下、历史失效重做、最多2D文件指纹及范围内容聚合、intent后退出与跨run引用读回、最后验收；无关股票改写后的重建/有界聚合也计入，不仅估正常成功。 |
| 手动repair | 原完整17范围内本次可执行scope；true复用/false重取；最多另对M个缺T且非确认全天的原名单股票各1个对象T单日完整unit，M不超过原完整代码数，重试/分页另计；只d<T合并/事件。 | 原run有界记录定位、5字段/摘要/权威值核验，旧源失效/主动重取的请求和空间、逐文件重入/最终对账、两job/维护互斥的验证；不计为自动10时点或补Q机会。 |
| bootstrap | 获准Prod范围显式261字段，按自然月及5000行服务端流式批量；单月约`ceil(月行数/5000)`次取批、非每日期新连；逐文件候选/发布，事件另授权。 | 当前准确范围/源截止与月计数、来源维护窗口、只读事务/超时、峰值磁盘，以及未完成日期重取、完整日源复用、逐文件继续和最后对账成本。 |

容量不足、范围超批准或候选不完整停止并说明，不减少字段/股票或缩短历史造完成。禁止无界导出、全历史长事务、Python逐行大合并、每日期新连远程库的未经测量默认。参数与验收目标已确认，尚无对应来源/性能运行验收结论；不因写了目标就宣称已经达标，也不将尚未实现的完整链路运行验收错置为现在必须通过。

bootstrap的5,000行估算依据是当前`RawStkFactorPro`和261字段契约：代码按9字节ASCII、Prod DATE净值4字节、259个Float(53)按8字节，全非空净值`5000×(9+4+259×8)=10,425,000`字节，约9.94MiB；不是PG整行或Parquet文件大小。常见文本数值平均8～12字节时，计每列4字节长度及每行协议头约15～20MiB，数值按24字节估算约35MiB；格式、NULL及驱动改变会影响实际量，不把它当绝对协议上限。64位CPython基本tuple/float/date/code对象约40MiB，另有libpq缓冲和列式转换；本批工作空间先按128MiB估算、256MiB留余量，不新增硬限制，也不声称进程峰值。仅取261列，不读raw_payload等辅助列；实现采用服务端named cursor，不得以普通cursor.fetchmany冒充流式。上一批保存并释放后才领下一批，不能在Python累计整月。Tushare的64MiB响应/2GiB unit限制不用于Prod数据库导出，DuckDB的16GB也不是Python/libpq总内存上限。正式导出前复用已有schema证据核准实际字段类型；不为大小估算另拉5,000行压测。

### 10.1 bootstrap自然月规划、5000行流式和恢复

初始化准确起止、源截止、来源维护窗口及正式执行仍须按原批准范围另行核准；本节固定实现办法，不把2017年样本起点套给所有股票。planner按批准起止截取自然月，记录闭开查询边界`[month_start, next_month_start)`，首末月裁到批准范围；显式投影261业务字段并按`trade_date, ts_code`稳定排序，不select *或读取raw_payload等辅助列。通过既有`ProdPostgresResource.connect_readonly_transaction()`每月建立独立只读事务、`connection.cursor(name=受控唯一名称)`及统一`itersize/fetchmany`批量；不能一条完整历史长事务，也不能每天重复建远程连接。

每次取至多5000行，按已核对源类型进行列式转换，保存为该run该月staging下连续编号的Parquet片段，读回核对源/保存条数和必要字段后释放rows及转换对象，才取下一批；日边界可以跨多个5000行批次，不能当成多份正式日文件或只保留最后一批。禁止fetchall、客户端普通cursor冒充服务端流式、Python逐行大表写入及把整月累积到列表。查询按`trade_date, ts_code`有序，看到下一日期或游标EOF才确认前一日期已收齐，保存其完整日源清单后，由同一主要DuckDB连接生成该日Raw/Silver候选并逐文件发布；不要求整月源完成才发布已完整日期，也不在每5000行时覆盖正式日文件。存在既有正式目标须按初始化批准的冲突策略停下或执行获准合并，不自行覆盖；首次无旧文件直接生成日期候选。

自然月仅是远程查询窗口，不新增月级完整门槛或恢复平台。游标中断时，当日未收齐的源片段不发布；已完整保存/发布的日期按既有日源完整事实和逐文件intent/checkpoint核验后保留或复用，完整日源存在但发布失败不强迫重读数据库。获准重执行时对本月尚未完成的日期做有界查询，整日重新读取，不按OFFSET、5000行批号或最后一行继续；没有明确完整事实的日期不能猜已经完成。源范围/截止修订则核对相关旧源是否仍适用，不能假作新依据完整。正式事件补录仍独立授权，物理阶段不借机运行正式Dagster。

## 11. 测试与验收要求

以下为待实现要求，不是已有通过结果。夹具依据真实生产者、源合同和有界样本，expected用独立可核算小样本；单元mock不替代真实接入边界。

| 主题 | 正向和必须抓住的反例 |
| --- | --- |
| 交易日含义 | 周一Q为周五，补Q的P再前一交易日；不能自然日减1、把今天/Q错作所有任务T/P。注册只今天/Q，旧历史键保留，不暗中7日。 |
| 前日一次 | Q19:00实际开始后日阶段失败且未证实齐全、仍缺/未知，后续不再Q、不跑今天；仅历史失败而日阶段已齐则可今天。未就绪未下载不耗、页重试仍一次、重启/清cursor不重获；标记写后crash保守已耗。 |
| 未开始再发 | 创建/排队只占位；所有已有终态均明确PRECHECK_NO_DOWNLOAD且无开始事实，才可下一未用时点发起提交序号+1，业务attempt仍1；未知/crash不猜未用。相同slot不重发、查询上限11条越限人工。 |
| 时点/截止 | 固定19～23:30，不按结束滚动；活动跨时点不追排；午夜排队开跑拒绝，已执行可结束；午夜不触发取消；Q占时点不额外排今日。 |
| 因子硬gate | sensor缺T或P就不提交；提交后job复核变缺则不下载、不造名单0变化；完整Raw输入就绪与技术因子4000/5000市场覆盖分开。 |
| 全齐后的输入修订 | 今天代码/历史已完成且输入未变时不再取源；后续固定时点仍评估输入，因子修订能启动同job；历史pending不能被全齐状态覆盖，Q一次不因修订而额外增加。 |
| 名单先于下载 | 任何技术因子网络前完整T名单已落盘/读回；17变化而源只返回16，名单仍17；下一轮重新匹配第17。相同输入复用完整名单，修订不静默抹掉旧pending。 |
| 无P/缺T/新股 | 真新股无P有生命周期结论且不造上市前历史；旧股无P、P有T无和可信旧pending对象两日都缺均保留无法判断；inner join或仅T-left漏行的反例必须抓住，不能假写0变化。 |
| 可回刷与稳定复用 | adj_factor数据集指示变化，有T行或确认全天停牌无T即可历史；技术行因子不同不阻断、Raw/Silver保持源值；无T盘中/非全天或停牌未知仍pending。此前16整批已发布可复用，第10股失败不能跳过前9；新股改变sha或runid不同不重下旧17。 |
| 历史前输入变化 | 下载前、完整源处理后首次提升前、写publication-complete前分别修订T/P；不继续新提升或把旧提交算新依据完成，保留已提交及原pending；不逐页/文件重扫、不额外自动重试、前日一次不复活。 |
| 发布顺序与失败 | 日Raw→check→Silver→check先于历史；multi_asset同一步check失败显式不执行下游；历史失败日文件/物化仍真实可读、无覆盖或跨文件快照门槛。 |
| T与历史职责 | 完整历史源含T，正式只改d<T；不会历史响应覆盖已发布T或同asset重复yield；历史行因子按历史日期而非全等T。 |
| 少股票/完整unit | 完整响应4000可用；第二页失败不可发布前页；满页继续；合法空不清旧数据、不伪造首次可用；字段/日期/主键错误仍拒绝。 |
| 集合及停牌 | 目标日上市有效区间、扣全天S+NULL、盘中仍应有；同数量不同股票仍缺；覆盖基于已发布合并集合；Raw额外合法行保留。 |
| 合并与checks | B-K+U、未返回旧键保留、合法NULL/负数通过；check定义始终2，历史分区/check真实绑定物化；旧绿色不能证明新文件。 |
| 事件持久与恢复 | 下载开始观察先持久化再网络；观察失败不联网；日已物化历史失败仍在；历史事件按run/批次批量关联，无全历史深扫。 |
| 恢复/错误/取消 | 日历史分阶段未完整从头、完整复用；外部目标变化拒绝；提升后记录失败读回；用户取消不领新unit/提升，观察失败不回滚；权限/结构/目标冲突非盲重试。 |
| 更早旧洞边界 | 周一补周五的日阶段失败未证齐或仍缺会挡周一，只有历史失败则不挡；周二只核周一，周五更早缺口仅诊断；不得删历史、扩大7日或让任意旧洞永久堵住后续。 |
| 手动配置与入口 | 仅5字段，默认reuse=true；错T/错source_run/job/错原plan或完整ranges摘要/任意越根路径拒绝；source_run可为上次repair但仍沿原17范围；Launchpad为ops.repair_stk_factor_pro_history.config，不要求自动slot。 |
| 手动范围和两种模式 | 原17中旧run仅16可执行、最后1后来具备资格仍可在原范围处理；不能加第18/延长起止/改T。true只复用完全匹配实际scope/输入的完整源；旧16源不可假充新17，缺完整则本次scope全下；false忽略旧源与已发布去重重新取源，但不放宽无T非全天资格。 |
| 手动权威数值修订 | 原T/P值后来修订、原名单/范围/契约不变时在本repair记录新依据，旧source或完成失配则本次scope全下；当前重比0变化不能抹掉原未完意图。原run不改；关键股缺权威值/contract变化/需扩范围停止，而不是重发旧摘要碰运气。 |
| 手动不重跑日阶段 | BY_POINT日下载与日发布函数均不得调用，T文件指纹和物化事件不变；对象范围请求可含T且源候选保留，但仅d<T提升与分区checks。两接口因子不等仍可执行并客观记发布完成，不造永久pending。 |
| 手动第17股窄查询 | 正式/原候选缺T、非确认全天时，只对原名单对象查询BY_OBJECT_RANGE的T,T一次完整unit，返回T行即可原历史；空仍pending、不同因子仍可执行。确认全天不额外查；未知停牌无行不得伪装全天。不发T全市场BY_POINT、不提升T，确认候选与历史expected units分开。 |
| 历史源空/漏原键 | 按下载前基础核应重取的已存键；缺失时有效新行仍合并、缺旧键保留且报告pending，网络完整不生成整scope发布完成；不要求指标值改变或因子等值，不加blocking或第三check。 |
| 事件op输出 | out={}的repair事件生成器可完成观察/历史物化/check而不要求默认result；无伪造普通Output或额外资产，失败/取消后的已发布事实仍可读。 |
| 手动恢复与取消 | 第10股下载失败后本次全scope重下，不跳前9；R1完整源后退出，引用R1且true才复用，引用旧R0不得暗找R1；新run的false再次取源，当前run后处理不反复取源。replace前取消不提升，replace后完成本文件记录再停下一文件；已发布可读、无op/job自动重提。 |
| 两job及bootstrap互斥 | 自动sensor识别repair活动、repair识别日更/另一repair，bootstrap维护窗口不并发；排队/手动冲突不能靠清cursor解决。缺少现行互斥证据不得声称已可正式执行。 |
| 源落盘与事件缺失 | 首次名单观察含受控staging位置；source-complete写成但完成事件前退出，按已验证run与唯一路径仍可找到并验完整；无初始可信记录不假造完成，不全扫目录。 |
| 逐文件三分支 | intent写后/replace后/读回后各退出；target=expected且candidate消失可补事实，target=prior且candidate有效才提升，第三整文件内容先核scope：等expected只读等价复用、等prior重建新intent、其他未知同股或候选错拒绝；原run不改、当前run保留引用。输入修订先认旧实际提交但不算新依据已完成。 |
| 下载前目标变化 | 源完整、尚无intent时，后轮同股更新必须停止，不重新登记当前hash放行旧源；只有名单外C变而scope内容未变可从当前文件重建保留C。已存在旧intent则先三分支，必要时保留旧记录并建新intent。 |
| 完整发布跨轮核验 | A/B整批完成后C更新同文件，按A/B完整字段内容与数量仍可跳过A/B；第三整文件但原scope=expected时只读记等价、不重放旧候选，scope=prior时保留C重建；A被改/删且不符两者不得沿旧绿色；第17股因子修订不使无关16股scope输入摘要失效。 |
| 停牌输入未知 | ready事件缺、最终文件错日期/缺必需字段/指纹变化时不认全天，覆盖未知；已有T行仍可历史、有效日源仍发布，无T不得假装全天，不读confirmed叠加。 |
| 自动因子改回相等 | T原变化历史未完后因子修订为T=P，自动新轮仍带原范围；人工同样，不因0变化删除。真新股本无历史有独立生命周期依据，不造上市前历史。 |
| 最小真实验收 | 按§11.1固定约5次来源小清单及缺失HTTP交接最小补核，记录261字段、分页、源/保存/归一化/拒绝/目标数量及样本；不临时扩量。日更正常/补入各一次、历史一股至多20日、临时事件与四故障点；时点用模拟时钟、资源用隔离settings核验，当前无已通过结论。 |

§12已确认决定均须有独立样本及工程验收，不能靠skip、mock字段兜底或自造expected把它们声称已经覆盖。

### 11.1 已确认的最小验证安排

管理员已确认§10参数及以下精简验证安排。尽可能复用仍适用证据，用小样本证明关键边界；不以大范围反复跑数代替边界验证，不为5000行大小估算另读生产样本。参数拍板不表示测试或真实验收已经完成。

| 时机/内容 | 最小范围与证据要求 |
| --- | --- |
| 开发前来源确认 | 优先复用261字段、本地源文档及已有审计；仍缺的正常HTTP/offset证据先列固定日期、代码、全部字段、请求数，再做有界请求。可用旧日全市场完整响应1次及一只长历史股正常页1次/小页约3次比较；小页只用于来源核验，不改变业务契约。现有样本计数仅作估计，出现差异停止说明，不自动扩大。固定HTTP组件接入后的真实交接另作最小确认，不将MCP结果冒充该交接已验收。 |
| 实现后日更读写/性能 | 重用同份获准真实响应，隔离做正常日更及同日补入各1次；分别记录正常/补入的两层读写、检查和最终对账成本。无历史正常日更与120秒目标比较；sensor单次评估与5秒目标比较。十个时点、60/600秒定义、去重、活动任务跳过使用模拟时钟/运行事实测试，不要求十次真实网络或十轮完整文件重写。 |
| 实现后历史读写/性能 | 一只股票、一个不超过20个交易日的临时样本批次，保留接近真实全市场宽度的日期文件，核无关股票不变；记录本批扫描/SQL/写入/峰值空间、完整源复用与逐文件恢复及最后读回成本。结合可信日期/文件规模估算类似17股原完整历史，比较1200秒目标并明确外推局限；不默认跑17股完整历史，不把外推当成正式全范围已验收。批次1/20/21/41日等边界用小人工计划/临时数据，不为此扩真实历史范围。 |
| 实现后事件/恢复 | 同一套临时文件和独立临时instance，目标T加两个历史日期核物化/check关联；网络可替换，事件实际落入临时事件库。源未完整、源完整未发布、替换后未记完成、事件失败四个位置做有针对性恢复验证；至少一次真实进程退出后由新进程恢复，其他细分位置用有依据的隔离错误注入，不要求每点重复真实进程/来源跑数，不对真实源制造故障。验证完整源零重下、已提交保留、旧候选不盖后轮数据及事件失败不回滚。 |
| 扩大范围的条件 | 小范围出现性能或语义差异，先说明具体问题及已有证据，提出额外最小验证范围；不自行扫描全湖、导出全历史或重复全量压测。正常、恢复、最终读回的成本分别记录，已有仍适用证据不反复重跑。 |

开工前明确范围、参数、成本及必要来源证据；业务完整发布/事件/恢复的运行验收在相应实现后隔离进行。不能要求尚未编码的完整链路现在已经运行通过，也不能因此省掉开工前设计/性能门禁。当前未执行本节任何来源、性能或Dagster验证，后续正式初始化及全范围验收仍须对应批准。

## 12. 已确认业务边界与仍需工程验证的内容

本节均已获得管理员决定，不再将因子差异、全天停牌无T行、交易日自动执行、当前Silver或手动repair写成待批准。工程验证尚未完成，不因此宣称已能运行。

### 12.1 已确认：以adj_factor数据集为依据，技术行差异不阻断

变化、原T/P输入修订和历史依据以现有`raw_tushare_adj_factor`为准。假设其T因子为2，而`stk_factor_pro`行仍为1，记录差异即可，不阻断该股日数据或历史，不要求等待相等，也不把已经完成的历史一直留pending。Raw与本期Silver均保留源业务值1，仅Silver将日期转DATE；不把1改成2，不缩放价格或重算指标。源接口这种差异尚未做本轮真实场景验证，不声称已发现生产异常。

“历史完成”表示按本次权威输入与原范围执行的来源下载、保存、必要检查和发布完成；不额外宣称提供商所有指标已按新基准更正。差异诊断继续保留，管理员希望主动重取后来来源时使用手动repair的`reuse_complete_source=false`，不增加自动探测或等值阻断。

### 12.2 已确认：全天停牌无T可回刷；跨日未完走原T手动入口

完整名单内的变化股，无T技术行但最终停牌事实已确认全天停牌，允许按原范围回刷d<T，不补造T。无T且非全天（含盘中）仍需取得原T行，停牌输入未知不等于确认全天；手动repair允许§4.1的原对象T单日窄查询确认来源已到，不将查询结果发布到T。这些是明确资格规则，不是对来源已发生过该组合的断言。

Q日覆盖已齐而历史未完时可以推进今天；原Q完整名单/范围及未完事实保留。今天比较T/P零变化不抹掉Q意图，也不自动拿今天技术行/日期/基准取代Q。管理员用§4.1的手动repair读取原T=Q完整17股范围及原batch，原范围内后来具备条件的股票可处理；不能永久锁死在旧可执行16股。只处理原d<T，不发Q全市场BY_POINT、不重发Q日文件，不注册自动历史监控，不扩大今天/Q自动窗口。

手动repair在同一原名单/起止/契约内采用当前已就绪的原T/P因子数值，记录修订，旧源和完成不匹配则对本次整个执行scope重下；不修改原run、不因数值修订再加两步准备或要求先重跑日任务。真正摘要/契约/范围冲突及原T/P不就绪、关键股权威值缺失则停止说明，不能伪造完成或默改授权。

### 12.3 已确认：只在交易日自动执行

周末及其他休市日不自动日更或补Q。周五未齐，周六/周日不新增机会；周一按前交易日一次处理周五。注册只增加真实开市日期。sensor先看有效日历is_open，休市无请求、不耗机会；自动job复核原计划执行日。开市日午夜前已执行跨入休市可结束。手动repair不伪装成自动补Q，按另行授权维护窗口执行，不受自动slot限制但仍遵守原范围及互斥。

### 12.4 已确认：Silver本期完整字段和对应行，仅归一化日期

完整保留261业务字段和对应行，仅trade_date由YYYYMMDD文本归一化DATE，其余合法源值包括NULL/负指标及与权威因子不同的数值均保持。不新增删股、填值、重算或覆盖率门槛，后续新增清洗不是本期前置。字段/主键/日期/Raw→Silver逐行对账仍执行，非法值不能静默删除/补NULL或取消必要检查。

两层成功发布后主键/行数一一对应，覆盖按此一致代码集合计算；Raw5000而Silver失败仍4000，Raw保留可读但两层处理未完，不能仅Raw齐就停止剩余处理。技术行因子不同不再作为本条的待决特殊过滤例外；保持源值并诊断，未来变更另改方案/测试。

### 12.5 开发前工程细化与验收证据

| 项目 | 还需验证和补齐的编码证据 |
| --- | --- |
| 手动入口 | §4.1五字段封闭schema、Launchpad层级、原run/plan/ranges与唯一文件位置；首次观察及R1下次配置、true引用R1复用/新false重取、原17范围/当前scope、权威修订和真正冲突正反例，不得将文档配置当成已存在入口。 |
| 前日未开始重新发起 | §3.4提交序号/持久开始/PRECHECK_NO_DOWNLOAD及最多11条算法；核原生过滤/证据关联、读回后再网络、重启/取消边界，不把cursor当权威。 |
| 完整名单/修订 | 源记录结构、全外连接缺P/缺T/两日皆缺、同原T待处理出处和原范围不扩大；自动及manual因子改回相等仍保留原未完范围，仅生命周期证明本无历史才有解释。history_input_digest按实际scope而非原17全名单。 |
| multi_asset/op及事件 | 日先历史后、op不调用日下载/发布、历史物化/check真实关联partition/run，观察持久化后网络，源落盘无结束事件仍可定位，历史事件有界批量读取。静态API阅读不是隔离运行证明。 |
| 发布与恢复 | §8.1下载前target-basis、固定字段有序内容sha算法、完整源必需引用、intent三分支/原run只读、无关行重建与同股变动停止；源漏原键可发有效行但scope仍pending。隔离验收各崩溃点、取消及逐文件完成。 |
| 因子/资格 | Raw事件gate真实语义、实际T/P及历史范围；suspend_d_ready_for_trade_date(T)加最终Silver日期/字段/指纹，资格和覆盖共用一次，不叠加confirmed。未知不挡已有T/日有效发布，差异仅诊断；不能按技术行等值加新门槛。 |
| 唯一写入 | 两job活动判断+维护窗口+bootstrap互斥，以及同两个手动run竞争；无新锁/进程平台，现行调度约束不足先说明，不能拿一次查询宣称已经防竞态。 |
| 参数/性能/bootstrap | §10单处参数及既有资源引用已经确认；还需核准当前Prod准确范围/源截止/维护窗口和最小来源证据。§11.1规定的来源小清单先补缺，读写/性能/事件/恢复在实现后隔离验收；成本必须包含完整源复用、源未完整重下、范围聚合、候选重建、逐文件继续与最终读回，不默认扩大跑数。 |
| 配置/错误 | 手动五字段来源run_config、默认true、单run生效、metadata及测试；§10所有固定参数单处定义，DuckDB引用原设置而不复制。按该表核对消费者与实际生效值，业务失败与组件源错误分开，不扩成任意错误平台。 |

本轮参数和验证办法均已拍板，没有新增业务选择；设计已明确相应编码办法，仍须按§11.1在正确阶段补齐必要来源和实现后隔离证据，不能把文档检查当运行验收。本轮明确暂不开发。新范围或执行方式先同步两文档，正式写入和运行授权仍须另外获得。

## 13. 本轮对账

| 管理员决定 | 本文实现约束 |
| --- | --- |
| 昨天按交易日、每执行日补一次 | §1、§3、§7、§11；Q/P分开、实际开始标记、等待未耗、日失败且未齐/未知挡今天、仅历史失败不挡；重启不复活。 |
| 只今天/Q、不再7日 | §1～3、§9～11；注册与就绪分开、旧分区保留、更早洞报告，不自动扩范围。 |
| `adj_factor`数据集的T/P先就绪 | §1～4、§9、§11；sensor硬gate和job复核，无因子不下载，不偷换成市场覆盖全齐。 |
| 技术下载前完整名单 | §2～5、§11；独立比较、下载前保存、同T复核修订、17/16例子、缺P不内连接漏掉。 |
| 日先发、同job历史后做 | §2、§4、§8～9、§11；multi_asset两输出/check、T只日更新、历史d<T，历史失败不回滚日。 |
| 业务可读，无全齐/快照门槛 | §1、§4、§8～9；已发布文件可用，覆盖与历史完成分别报告，合法少股票不阻断。 |
| 仅排全天、盘中仍应有 | §1、§5.2、§9、§11～12；确认全天停牌无T行允许d<T历史，不伪造T；非全天/停牌未知无T仍pending。 |
| 完整候选恢复、稳定历史不重下 | §5～8.1；日/历史阶段、完整名单/实际scope分开，来源/目标基础/提升记录独立；按实际scope权威摘要及业务内容复用，不逐页/股续传，不由新runid或无关股票整文件sha变化误触全历史重下。 |
| 手动历史repair已确认 | §2、§4.1～4.2、§7～8.1、§11～12；精确5字段、原完整范围/原T；引用R1才能复用R1，下一次完整配置预先可见；true复用、false每新run重取，只d<T无自动repair sensor。 |
| adj_factor数据集权威、技术值不同只诊断 | §1、§5.2、§9、§11～12；Raw/Silver源值不改、不缩放/重算，不因不等卡历史，不冒充源指标重算正确性证明。 |
| 全天停牌无T行允许历史 | §5.2、§9、§11～12；事件ready加最终Silver实际文件核验、资格/覆盖共用；确认全天且权威数据指示变化可d<T、不补T，盘中/非全天无T或停牌未知仍pending，未知不挡已有T。 |
| Silver本期沿用原规则 | §9、§12.4；完整字段/对应行、日期DATE及必要检查不变，后续新增清洗不阻塞本期。 |
| 20交易日历史合并已确认 | §8、§10、§11；计划SSE开市日去重升序每20切、末批保留，不改变整股票窗口/完整scope源/逐文件checkpoint，缺分区不自动登记。 |
| 5000行bootstrap已确认 | §2、§10.1、§11；批准范围内自然月、named cursor/itersize/fetchmany同一5000常量，落盘释放；完整日源/逐文件事实复用、未完整日期重取，月仅查询窗口、不累计整月。 |
| sensor与资源已确认 | §3、§10、§11；更新60秒、注册600秒，半小时轮次不变；原16GB/4线程/512GB及临时目录经既有连接复用，同任务1主要连接，无新env/任意run参数。 |
| 精简验证与性能目标已确认 | §10～12；5/120/1200秒是验收/外推目标，不强杀；固定来源小清单、正常/补入各一次、一股至多20日、临时instance T加2日、四故障至少一次真实退出恢复，复用证据而不默认全量跑数。 |

API依据：[Dagster multi-assets](https://docs.dagster.io/guides/build/assets/defining-assets)、[AssetCheckSpec](https://docs.dagster.io/api/dagster/asset-checks)、[执行事件](https://docs.dagster.io/api/dagster/execution)、[RunRequest/SensorResult](https://docs.dagster.io/api/dagster/schedules-sensors)。本轮通过Context7核对multi_asset/check_specs及同一步blocking职责，并阅读本机已安装Dagster参数、事件缓冲及现行repair事件代码。未运行正式定义或隔离instance，不能把API阅读当成事件验收。

本轮通过CodeGraph核对run-key/batch身份及资金流sensor调用链，再查现行Raw因子readiness、配置/下载合同。本轮又以CodeGraph核对现行日线repair job/op，并通过Context7核对op config_schema/context.op_config及ops下配置层级。影响面仅本数据集设计及未来列出的DG本地实现；没有修改Prod、其他数据集、前端/API或运行配置。契约名称校验的所有实现方与消费者仍须在对应开发步骤完成审计，不把本文当作已修改代码的证据。
