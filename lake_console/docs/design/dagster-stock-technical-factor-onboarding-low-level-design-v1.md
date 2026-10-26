# 股票技术因子 DG 数据集接入 LLD v1

日期：2026-10-27。状态：第一至第四批已开发并通过各自隔离验收，见§14.6、§15.10、§16.4及§17.7；本轮五项修复见§17.8和第四批当前验收记录，994项不同用例通过。第五批及以后、整个数据集尚未完成，正式bootstrap及自动化未执行。以下为已确认业务规则，正式编排由后续批次装配：自动日更先发布日Raw→Silver，再检查原目标日Raw是否齐备；只有齐备后才处理历史。手动repair先检查原目标日Raw齐备，再确认原目标日Silver存在、已有检查通过且对应当前Raw，之后核T/P复权因子及原历史范围；不执行日更新。Raw缺失、不齐或无法确认时直接报“原日期数据缺失”；Silver缺失、无有效检查或不对应当前Raw时直接报“原日期Silver不可用”，交管理员处理，不代补当天Raw/Silver。Tushare日更或历史任务失败、取消、异常退出后，获准重执行均重新下载所需原完整范围，不复用失败任务的源或候选；已发布正式数据、完整名单、授权范围和失败证据保留。参数、编码和验收要求分别见§10～12；正式读取、写入、历史事件及自动化启用仍分别授权。

依据：[原技术方案](dagster-stock-technical-factor-onboarding-plan-v1.md)、[DG接入模板](../templates/dagster-dataset-onboarding-template.html)、[性能治理规范](dagster-data-pipeline-performance-governance.md)、[Prod审计报告](../../reports/stock_factor_pro_prod_audit_20261021/README.md)。下载器依据[组件LLD](dagster-tushare-download-component-low-level-design-v1.html)与[业务使用文档](../architecture/tushare-download-component-usage-v1.html)，不在本数据集重做。

## 1. 范围、日期与已经拍板的规则

本文所称股票复权因子数据集，是现有 Tushare `adj_factor`（DG Raw资产`raw_tushare_adj_factor`）；技术因子数据集`stk_factor_pro`中另有同名`adj_factor`字段。前者是变化名单、历史回刷和输入修订的依据；后者保持源业务值，仅记录差异，不作为历史启用的等值门槛。

历史从Prod bootstrap，缺口在导入过程中按§10.5利用本地数据统计，不以前置Prod全历史覆盖审计放行；范围已确定为正式开始时在来源维护窗口内确认的`raw_tushare.stk_factor_pro`全部现有业务数据，包含全部股票（含退市股票）、全部日期及261业务字段，不按固定年份或当前上市名单裁剪。先完成物理导入及完整性审计，数据完整后才能补历史事件；历史事件全部补齐、核对通过并另获启用批准后，DG直接从Tushare日更和获取必要历史。合法已导入文件可读，不等于初始化已通过；不把每日来源改回Prod，不迁移其他数据集。

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
5. 每次日更job（含人工重新执行）在技术因子网络下载前读取当前`adj_factor`数据集的T/P因子，重新生成并完整保存T的变化股票及历史范围清单，并保留DG已记录的同T尚未完成历史回刷的股票和起止日期。sensor只编排，不计算名单；名单不能按本轮技术因子返回了多少股票来缩小。前次任务如果在名单生成前已经失败，本次直接根据当前T/P重新计算，不要求读取一份并不存在的名单。保留的历史回刷范围不是日下载缓存，也不是页、股票或文件的下载进度。
6. 每轮取得的完整有效数据先发布日Raw、Silver，业务即可读；然后仅在原T已发布合并Raw覆盖齐备、日阶段通过时，在同一个自动job处理必要历史。历史失败保留日数据，管理员可通过§4.1额外的手动repair job只恢复原T历史，不重跑日阶段；无自动repair sensor。日数据发布没有覆盖率、最低股票数、全历史完成或跨文件快照门槛；历史另有原T Raw齐备硬条件。
7. 只从应有集合排除全天停牌，盘中停牌仍应有。Raw不据应有集合过滤来源合法行。Silver本期完整保留字段及对应行，归一化日期；后续新增清洗不作为本期前置，不自行过滤/填值。
8. 只自动管理今天和Q；更早分区保留，不自动补更早日期或以它阻断今天。管理员可按§2.4重新执行真实原日更run，也可按§10.7以bootstrap批准及缺口日期首次提交同一job的bootstrap_supplement，无需旧run。两种人工路径均完整新下载T，日Raw齐且Silver通过后同job处理必要历史；bootstrap关联的日/历史发布按§10.5.6及时更新原operation逐日统计和summary。

失败后无论下载/候选/发布哪一步退出，下次均重新下载；丢弃候选不等于删除正式数据、历史回刷名单或失败证据。日下载数据只留在当前调用内存，不写日下载中间文件、日下载manifest或日source-complete；只在正常关闭下载会话并核最终summary后，构造本次原子发布必需的唯一Raw候选。该候选不是缓存，失败后的新任务不得读取它。完整unit仍指本次接口查询全部页已取全，不代表源端所有应有股票已发布。合法少股票可处理，网络只完成一部分页不可交付半unit。管理员手动repair为额外人工入口，不增加自动调度链。第一批已登记唯一正式CONTRACTS/BINDINGS为`stk_factor_pro`、独立版本1及固定HTTP；基础schema、输入/结果类型、路径和专属动态分区定义已实现。本文日发布、历史、bootstrap、正式资产/job/sensor装配仍按后续批次实施，不能因契约可下载就宣称整个数据集已接入。

## 2. 定义、代码结构与接口

### 2.1 Dagster定义

| 对象 | 固定名称与职责 |
| --- | --- |
| 源契约 | `stk_factor_pro`、独立`version="1"`；261个完整源业务字段；固定HTTP；使用BY_POINT与BY_OBJECT_RANGE。 |
| 两个资产 | `raw_tushare_stk_factor_pro`、`silver_stock_factor_pro`；日数据依次发布，后续历史仍写这两个资产的旧日期，不新增清单/完成状态资产。 |
| 分区 | `cn_a_stock_factor_pro_trade_days`；两资产及两项check共用；只日常新增今天和Q，旧键不删除。 |
| 日更job | `raw_tushare_stk_factor_pro_update_job`；自动单T/单轮、原生日更重新执行、bootstrap_supplement首次人工补数共用；均包含名单、日发布和必要历史。bootstrap用途不由sensor生成，收尾更新原operation当前记录；不另建补日job或自动历史job/sensor。 |
| 管理员手动历史job | `raw_tushare_stk_factor_pro_repair_job`；只恢复原目标日、原批名单/范围的历史，复用同套历史函数，不发T全市场BY_POINT日请求、不执行T日发布；无自动sensor，精确输入见§4.1。 |
| 注册sensor | `stock_factor_pro_trade_day_sensor`；按日历新增今天及Q，不下载，不等Tushare或因子就绪。默认STOPPED。 |
| 更新sensor | `raw_tushare_stk_factor_pro_update_job_sensor`；按Q一次优先、时间、活动run、因子门槛和结果提交；默认STOPPED。 |
| Raw综合check | `raw_tushare_stk_factor_pro_file_contract_check`；文件/字段/主键/日期、完整unit到本次U及合并对账；历史另核源文件保存/读回。股票少一部分不阻止有效数据发布。 |
| Silver综合check | `silver_stock_factor_pro_file_contract_check`；对应Raw、DATE/主键、完整261字段及逐行对账；本期不增加清洗过滤，后续新增规则不是前置。 |

采用一个`@dg.multi_asset`定义两个资产，在一个同步生成器内明确执行日Raw→Raw检查→日Silver→Silver检查→原T Raw齐备判断→历史。两个`AssetSpec`均声明`skippable=True`，`can_subset=True`让没有实际文件的分支能够省略物化和检查输出。业务入口仍必须完整选择两个资产及两个检查；job固定完整selection，asset函数在任何预检、下载或写入前按本节规则再次核对，不能只选Raw、只选Silver或漏掉检查。

固定期望集合为`{dg.AssetKey("raw_tushare_stk_factor_pro"), dg.AssetKey("silver_stock_factor_pro")}`及对应两个`dg.AssetCheckKey(asset_key, check_name)`。asset开头精确比较`context.selected_asset_keys`、`context.selected_asset_check_keys`与这两个集合；任何缺项、额外项或只选检查均抛`dg.Failure(..., allow_retries=False)`，按§6.1输入/契约错误记录`failure_phase=precheck,retryable=False,source_error_code=None`，零技术请求、零业务文件写入、零物化/check。不得自动补选、忽略选项或以`can_subset=True`为由开放业务局部更新。完整selection通过后，实际分支仍可能因预检等待或无可用日数据而没有文件输出；其终态分别按§4和§4.0.1判断。

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
| `defs/sensors/stock_factor_pro_trade_day_sensor.py` | 只注册今天和Q。 |
| `defs/sensors/raw_tushare_stk_factor_pro_update_job_sensor.py` | 读取有界运行事实、因子就绪、Q一次条件和当前轮次；不计算完整变化股票或写Parquet。 |
| `defs/asset_guards/stk_factor_pro_readiness.py` | 输入就绪、已发布可读、覆盖及历史未完分别判断；纯代码集合函数供日更/bootstrap统计共用，但不带入含instance日更前置。提供活动任务检查、原run/PG观察身份读取及§6.2结果读取；不import bootstrap模块。 |
| `defs/io/stk_factor_pro_history.py` | 技术因子下载前的完整名单；原T Raw齐备后完整历史范围；历史前输入再核对、窗口和完整发布依据。 |
| `defs/io/stk_factor_pro_download.py` | 日完整unit及最终summary仅在当前调用内存核验；历史完整unit逐个保存/读回，全部会话成功后才形成历史源完整记录；适配组件通知。不保存日下载中间文件，不重试业务写入，不把实际开始记录藏在进度回调。 |
| `defs/io/stk_factor_pro_candidates.py`、`stk_factor_pro_publication.py` | 按日期批量合并、必要校验、同文件系统提升与逐文件记录；T日唯一来自日阶段，历史只合并d<T。 |
| `defs/checks/stk_factor_pro.py` | 两项检查的规格及纯校验，multi_asset内调用；不另定义同名check形成重复注册。 |
| `defs/assets/stk_factor_pro.py`、`jobs/stk_factor_pro.py` | 同一multi_asset/job的八字段分支装配、bootstrap首次/重新执行授权、完整日更和必要历史、按阶段/批次更新统计；不建线程、子进程或额外job。 |
| `defs/ops/stk_factor_pro_history_repair.py`、`defs/jobs/stk_factor_pro_history_repair.py` | `repair_stk_factor_pro_history` op的4项必填配置/预检/历史新下载与手动repair job装配；不注册自动sensor，不调用日下载/发布函数。 |
| `defs/bootstrap/stk_factor_pro_history.py` | 原operation批准/源/导入记录、按月5000行服务端导出及覆盖；§10.7 bootstrap授权resolver编排，调用readiness已有PG身份/纯集合函数；§10.5.6补数后统计更新。asset/op组合调用本模块，不从readiness反向import本模块。不累积整月、不经下载器导出Prod、不做Prod全历史覆盖预审；正式执行另批。 |
| `defs/catalog/lake_assets.py`及定义装载入口 | 两资产事实登记；现有catalog不是动态生成所有运行定义的引擎。 |

依赖：装配→sensor/资产/check→本数据集业务函数→组件/既有DuckDB和路径。不得跨工程import Prod定义或Ops入口，不替换其他数据集配置/下载/写入。token和地址直接用组件现有配置单元读取。

### 2.3 业务函数的数据输入与输出

以下定义本数据集内部函数接口；参数传dataclass/不可变记录，Parquet内容不放进sensor cursor。第三批历史规划、下载和发布的完整签名、输入与批次边界以§16.2为准，不能把本表的(...)当成允许任意参数的实现。

| 函数 | 主要输入 | 输出与必须保证的行为 |
| --- | --- | --- |
| `select_stk_factor_pro_request(...)` | D、时点、日历、今天/Q结果、已存在run/实际开始事实、对应因子就绪 | 一个目标T及轮次或明确不执行原因；先Q后今天，Q日阶段失败未证实已齐、仍缺/未知则当天不继续；仅历史失败不挡今天。 |
| `read_stk_factor_pro_other_active_runs(instance, *, own_run_id=None)` | 同一正式instance、可选当前run_id；固定两job及五种活动状态 | 返回至多4个其他活动任务的原生DagsterRun对象；每job一次limit=2查询，不按目标日期过滤，查询失败不得伪装为空。详见§4.2。 |
| `require_stk_factor_pro_no_other_active_runs(instance, *, own_run_id=None)` | 上述同一读取接口 | 无其他任务才返回；有冲突或读不到事实则立即Failure、allow_retries=False，给出任务身份及下一动作；不循环等队列。 |
| `require_stk_factor_pro_inputs(...)` | T、P、对应股票复权因子Raw因子路径及其真实就绪结果 | 已核对的T/P输入身份/指纹；不足就不下载，不能返回“没有变化”。 |
| `build_stk_factor_pro_history_plan(...)` | 当前T/P完整因子、可信历史范围、DG记录定位的同T未完成/成功事实 | 每次日更新重新比较并在技术因子请求前保存本run完整名单；合入已有原未完成范围，输入未变时业务摘要可相同，但不把旧plan直接当本run新计划或下载完成。T/P重比相等不抹掉旧待处理；原下载前未生成计划不妨碍重新规划。 |
| `download_stk_factor_pro_day(...)` | T、轮次、已持久化的开始事实 | `VerifiedDaySource`：当前内存中的唯一完整日`UnitResult`、已成功关闭的最终summary及本次身份/摘要；不写文件，源少股票不缩减原变化名单，网络半unit不返回成功。 |
| `publish_stk_factor_pro_day(...)` | 本次`VerifiedDaySource`、T已发布文件及目标预期 | 从当前内存U与正式B直接构造唯一Raw发布候选，校验/提升/读回后从Raw生成Silver候选及发布结果；按主键更新补入、旧未返回行保留。不先写另一份日源Parquet。 |
| `require_stk_factor_pro_history_raw(...)` | 仅§5.2原T Raw覆盖结果 | 不为True就抛约定Failure；自动调用方先分支等待，repair直接调用。完整名单/范围由各自后续流程另核。 |
| `download_stk_factor_pro_history(...)` | 原T Raw齐备、target_silver.ready=True、完整原失败范围、再次核对的权威T/P | 当前run全部unit全新下载/保存/读回；失败新run不复用旧source-complete。 |
| `publish_stk_factor_pro_history(...)` | 完整历史源、名单/基准、现有d<T文件 | 仅更新d<T；历史响应的T仍完整留在源候选并用于核对，不覆盖日阶段T。 |
| `summarize_stk_factor_pro_result(...)` | 文件读回、两层checks、覆盖、完整名单/历史结果、错误 | 分别说明可读数据、缺股票、待回刷、两接口差异和本轮终态；不增加覆盖状态资产。 |
| `repair_stk_factor_pro_history(...)` | 手动配置指向的原T、原完整名单/范围和原批次 | 不重新计算扩大授权范围；核原T Raw齐备及原T Silver有效且对应当前Raw后，重新下载完整原失败范围，复用同套业务函数，只d<T，无BY_POINT或T提升。 |

### 2.4 日更入口的封闭配置与人工重新执行

`defs/assets/stk_factor_pro.py`固定使用`@dg.multi_asset(name="stk_factor_pro", specs=..., check_specs=..., can_subset=True, config_schema=STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA)`，并在函数首部执行§2.1完整selection核对。配置位于`ops.stk_factor_pro.config`，不能把资产key当作op配置名。`STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA`和解析后的`StkFactorProRunInput`均在`defs/run_contracts/stk_factor_pro.py`维护；asset通过`context.op_execution_context.op_config`读取。未知配置键拒绝，不增加fields、分页、token、地址、路径或处理版本的运行覆盖项。

| 配置字段 | 配置类型、必填及解析后类型 | 精确校验 |
| --- | --- | --- |
| `execution_day` | 必填str→`datetime.date` | 严格`YYYY-MM-DD`。today/previous_day为原计划开市日D；bootstrap_supplement首次为实际上海日期，可为休市日，原生重执行保留原D，本次实际开始时间另记。 |
| `target_trade_date` | 必填str→`datetime.date` | 严格日格式、已注册开市日；必须等于`context.partition_key`。 |
| `purpose` | 必填str | 仅today、previous_day、bootstrap_supplement。前两者仍要求T=D或D的前交易日Q；bootstrap_supplement按§10.7核bootstrap批准及缺口日期，不能用它提交任意旧日。不接受manual_repair。 |
| `scheduled_slot` | 必填int或None | today/previous_day必须精确int且0～9，计划时点仍由D日19:00加slot×30分钟派生；bootstrap_supplement必须None。不接受bool、独立时间文本或任意时点。 |
| `submission_no` | 可空int，默认None | today必须None；previous_day必须1～10，业务attempt由用途派生为1，不让运营另传attempt。 |
| `bootstrap_operation_id` | 可空str，默认None | bootstrap_supplement必填，按§10.2受控安全标识核固定operation；其余用途必须None。不接受路径或自动发现其他operation。 |
| `expected_bootstrap_approval_digest` | 可空str，默认None | bootstrap_supplement必填64位小写SHA-256，与固定operation批准记录精确匹配；其他用途必须None。它限定原初始化范围，不替代本次管理员明确执行授权。 |
| `expected_bootstrap_date_result_digest` | 可空str，默认None | bootstrap_supplement必填，首次取原T当前coverage/result.json的文件字节SHA；原生重执行保留同一值并核既有授权观察，不因当前result已被合法更新而重新要求相同；其他用途必须None。 |

bootstrap_supplement的submission_no和派生business_attempt均为None，不占自动时点/补Q机会。新增三项只持久化在该job既有run_config及阶段观察中，无env、配置表、任意文件路径或热更新。配置schema只定义这八项；自动sensor仍只构造原两种用途，并把新增三项保持None。人工首次和重执行的完整样例及授权步骤见§10.7。

正常日更请求示例：`build_run_request(run_key=build_asset_update_run_key(subject="raw_tushare_stk_factor_pro", unit_id="2026-10-23:2026-10-23:0"), partition_key="2026-10-23", run_config={"ops":{"stk_factor_pro":{"config":{"execution_day":"2026-10-23","target_trade_date":"2026-10-23","purpose":"today","scheduled_slot":0,"submission_no":None}}}})`。前日示例在同一配置层填D=`2026-10-23`、T=`2026-10-22`、purpose=`previous_day`、slot=0、submission_no=1，并用§3.3的前日key。日期必须由实际日历验证，示例不授权执行。多字段身份关系不一致时，在任何源请求、文件提升及“开始下载”事实前拒绝。

内部函数签名固定为：

```python
def parse_stk_factor_pro_run_input(config: Mapping[str, object],
                              partition_key: str,
                              calendar: tuple[date, ...]) -> StkFactorProRunInput: ...
def resolve_stk_factor_pro_source_run(instance, current_run,
                                 run_input: StkFactorProRunInput) -> StkFactorProSourceRun | None: ...
```

`calendar`是已校验、严格升序去重的SSE开市日期tuple，覆盖T/P；today/previous_day另覆盖原D/Q，bootstrap_supplement不要求实际执行日为开市。`StkFactorProRunInput`是frozen dataclass，八字段按上表解析，purpose使用上述有限Literal值，三个新增字段为str|None，slot/submission为int|None，其余日期为date。`StkFactorProSourceRun`保存已验证parent_run_id、root_run_id、原八字段、原终态、可空的完整plan/ranges引用及已核bootstrap_context；引用缺失与坏文件区分。它不含可用于本次发布的旧源或旧候选引用；source只指原任务意图及授权。

“重新执行”指管理员对原日更run明确发起原生重新执行后产生新run，原run可为FAILURE、CANCELED，或SUCCESS但数据未齐/仍有处理需要；不重新创建job定义。管理员须先执行§4.2维护步骤，仍通过同一队列。自动sensor永不创建带parent/root的重新执行，也不提供跨午夜特权参数。本期采用统一规则：人工新run从头执行整个日更步骤，不能只选失败步骤跳过日下载；无论原任务是否已下载完整、是否已建候选或已发布部分文件，均重新下载，不使用原run源或候选。

1. 无parent的today/previous_day仍按原D自动时点及午夜执行；无parent的bootstrap_supplement只走§10.7首次人工授权分支。原生重执行用get_run_by_id精确核直接parent及必要root（最多两条不同run），同update job、终态、相同八字段和T分区；字段缺省统一None后比较，不拿新增缺省误拒正常自动配置。bootstrap补数另核原授权观察，必要时再读它明确引用的一个authorization_run_id，合计最多三个不同run，不沿祖先无限查找。人工重执行保留原八字段，不把T或D改成本次实际日期；实际时间另记。普通旧配置无合法parent/root不得获得跨午夜例外，新bootstrap用途不能借此绕过§10.7。
2. 新run核当前原T/P，重新计算、保存本run完整名单，再请求原T完整日unit；Raw齐备且日阶段通过时，在同一run立即重新请求原待处理历史完整范围。只通过§6.2既有DG记录读取原未完意图和成功事实，不扫描旧下载目录。确认原任务在下载前失败且未形成完整plan时，允许仅按当前T/P和可信范围重新规划；若已有开始下载/计划引用却记录损坏或无法确定原未完范围，停止并说明，不能猜为空。日更新重新执行不要求无中生有的旧plan；独立历史repair仍按§4.1的原完整授权执行。
3. 本run source-complete只证明当前run刚取得的阶段数据已保存完整，供当前运行从下载进入处理，不是跨失败run的恢复授权。新事实只写当前run目录；旧记录保留排障，已发布正式文件保留供新合并，不删除、不回滚。
4. 前日一次和19:00～午夜仅限制自动发起；人工重新执行及明确授权的bootstrap_supplement不受该窗口/实际执行日开休市/Q次数限制，但均核T已登记开市、原T/P、唯一写入和维护批准。人工补齐后同job继续必要历史，历史不足保留日文件并按§6.1失败。无原日更run只允许§10.7的bootstrap授权，不开放其他任意日期/股票输入；不恢复Q机会、不补发slot、不加外层自动重试。

`select_stk_factor_pro_request`只返回自动两用途的StkFactorProRunInput|None及既有cursor摘要，不生成bootstrap用途；build_run_request只透传配置，八字段构造/解析/关系校验由本数据集完成。测试含周一补周五、错D/T/分区、bool冒充slot、自动携带bootstrap字段拒绝、普通无parent旧配置拒绝、bootstrap无parent但授权正确通过、parent/root八字段不符拒绝，以及失败旧日/历史源均不可用于新run。

## 3. 分区、时点与前日一次机会

### 3.1 分区注册

bootstrap先核实来源维护窗口内Prod全表实际最早至最晚日期，按SSE日历注册其中可确认的开市日；不能将旧2020起点、当前2017起点或当前上市名单作为过滤。已确认休市而Prod有源行时报告并停止该错误；日历缺失或不可判断不当成休市，合法源行照原DATE忠实导入，覆盖记未知，不伪造开市、分区或事件。原有缺日如实记录、不造文件，完整自然日期分类及统计见§10.5。文件写入及历史事件分别授权，全量业务范围不再作为等待选择的事项。

日常注册仅处理今天（若开市）和Q，注册与就绪分开：不等源或因子，不删除已注册旧历史，不注册未来/休市日期。没有有效日历不能用自然日减一。更新sensor只选已注册目标。

股票复权因子数据集的分区属于其现有资产和分区定义；sensor使用现行`raw_tushare_adj_factor_ready_for_trade_date(instance, T/P)`分别核对两个分区的就绪，不拿本数据集的分区登记代替上游就绪。补Q所需P可能早于本数据集的两日管理范围，不因此扩大技术因子自动管理窗口或替其他资产注册分区。

### 3.2 sensor按轻重顺序作决定

1. 校验正式根可用、Asia/Shanghai执行日期、有效日历的开市标志及19:00～午夜窗口；执行日休市直接跳过，不发起下载或消耗补Q机会。窗口前不做重扫描。
2. 确定今天/Q、当前已到达的固定半小时时点；按§4.2调用同一读取函数查询本数据集活动run，有则跳过该时点，不积压。这是本次评估唯一的活动任务查询，结果在本次评估中复用，构造RunRequest前不重复查。查询失败按§3.5不能确认当前slot处理，关闭当前slot但不消耗Q实际下载机会。
3. 若Q应有代码仍缺、覆盖不能判断或日阶段失败且不能证实已齐，先检查是否已实际使用D补Q的一次机会。已使用且仍有这些问题则本执行日停止自动推进，不能改选今天；仅历史阶段失败不等于Q日覆盖失败。
4. Q需要补且机会未用，检查Q及其P股票复权因子Raw因子真实就绪；未就绪只等待，不能下载Q，也不能绕过Q去今天。Q日阶段满足条件后可以考虑今天，不能仅因历史pending重新补Q日数据；原目标日pending通过§4.1手动入口处理，不把它显示成代码覆盖不足。
5. 今天的候选同样先核T/P因子；尚缺股票、覆盖未知或本目标T明确历史待处理，可按§6.1失败矩阵进入后续时点；历史永久失败不能仅因pending而继续请求。代码已齐、必要处理/历史已完成且股票复权因子数据集输入未修订时停止下载，但sensor继续轻量时点评估输入身份；输入修订则重新提交本job，不无条件持续取源。不能用股票已齐抹掉历史未完成。
6. 构造一个T的RunRequest，写计划日期/时点、用途为补Q或更新今天、前日业务attempt固定为1；sensor不取技术因子、不保存变化清单。

更早日期缺口只保留诊断，不自动补采或阻断当前日期。例：周一补周五仍缺，周一不做当天；周二只自动核周一，周五已变成更早旧洞，报告管理员而不是继续自动补周五。不能偷偷把它改成“任何历史旧洞永远挡住新日”。

### 3.3 固定时点、去重与午夜

每时点至多一个目标job；19:00给Q补采占用后，不在其结束时立即补排同一19:00的今天任务，而等下一个可用时点。长任务跨过19:30则该时点跳过，不能20:00前连续追补几轮。上海本地时间位于`[19:00, D+1 00:00)`时，取`slot=floor((local_now - D日19:00)/30分钟)`，只允许0～9，计划时点为`D日19:00+slot×30分钟`；只考虑当前slot，不遍历补发更早slot。活动任务导致跳过时把D/slot记入小型cursor状态，相同时点已有持久run则不再提交；重启后仍只算当前slot并核对持久run，不从0回放。cursor不是前日机会或实际执行的事实源；更新sensor使用§10的60秒最小评估间隔，注册sensor为600秒；它们不等于业务30分钟。评估可能因daemon负载延后，不承诺恰好每60秒执行，也不为延后补发过往slot。

今日正常轮次使用`build_asset_update_run_key(subject=..., unit_id=执行日+目标日+固定时点)`，同轮去重，新时点新key。前日一次不能改用不断变化的时点key或业务attempt=2：使用`build_repair_attempt_run_key(subject=..., repair_scope_id=Q, attempt=1, attempt_scope=执行日D+提交序号)`区分§3.4中获准的预检未开始重新发起，业务attempt始终为1。现有builder只是字符串组合，不会自动执行次数规则；还必须核对持久化的实际开始事实。提交序号不是下载重试次数，也不是额外业务机会。

自动发起到D+1的00:00截止。自动排队run实际开始再查截止，过期不下载/发布；午夜前已实际开始可正常结束。§2.4已验证人工重新执行及§10.7 bootstrap_supplement首次人工用途不受自动窗口约束，不增加自动例外。历史前校验及取消仍执行；sensor重启/cursor重置不重置Q次数与已用slot。

### 3.4 什么算已经用过前日一次

“有run”与“业务下载已开始”分开：创建/排队只占位，预检因上游不就绪退出且未开始技术因子下载，不消耗一次。日历、T/P因子复核、完整名单保存均属于网络下载前准备。组件内部页/重试仍是同一次业务下载。

在**第一个技术因子网络请求前**，先持久化本run的“开始下载”事实，包含D、T=Q、用途、业务attempt=1、run_id、计划时点和完整名单摘要；保存失败就不联网。写成后进程退出、请求是否发出不明时，保守视为已使用，不能自动再赌一次。这里不承诺精确捕捉真实网络报文发出的瞬间。

使用现有Dagster事件/运行事实，不新建额度表、锁或平台。multi_asset生成器先`yield AssetObservation(...)`；恢复后按当前run/目标和观察身份**显式读回确认该开始事实已经持久化**，确认成功才调用网络。不能只从生成器恢复推断保存成功，也不能只调用`context.log_event(...)`后立即请求，因为本机实现先放入事件缓冲，调用返回不等于已落库。读回失败不联网；写后退出仍保守已用。相应实现后须隔离证明事件保存/读取失败均不发网络、不同执行器下顺序有效、写后退出不重用机会。

所有日更用途的真正开始观察统一保存固定metadata键goldenshare/download_started=True，每run至多一条，T/D/用途按当前八字段；bootstrap用途还含完整Context。名单观察、阶段结果和PRECHECK_NO_DOWNLOAD不得写此True。首次授权及自动机会读取以该标记、真实run/T和配置共同匹配，不把后续重复保存Context的阶段结果误当成第二份授权。

前日未开始后的重新发起采用以下具体规则，不靠重发已用key：

1. 每固定时点最多提交一个自动run；读取本job、本执行日D、前日目标Q的自动发起事实，至多11条检测超过10时点异常。RunsFilter使用job/时间及原生tags：PARTITION_NAME_TAG=Q.isoformat()、SENSOR_NAME_TAG=raw_tushare_stk_factor_pro_update_job_sensor，常量从dagster._core.storage.tags导入。Dagster的sensor创建run流程自动写入该sensor标签，本数据集不新增自定义tag。再核配置D/T/purpose/slot及parent/root；bootstrap_supplement和其人工重执行无此sensor标签，不能挤掉11条内的自动事实。普通日更的人工重新执行即使继承sensor标签，也不计新submission/机会；超过上界不能确认时保守停止，不猜开始次数为0。活动任务及最新同T结果查询不加sensor过滤，仍必须看见所有人工run。不能用任意run_config SQL过滤，具体查询见§6.1。
2. 任何active run先占位。任何匹配的持久“开始下载”即表明业务一次已用，无论run最终状态和cursor内容，都不再自动补Q。不能遍历全量run历史。
3. 只有全部既有terminal发起都明确记录`PRECHECK_NO_DOWNLOAD`、且没有开始事实时，才允许在下一未用时点再次发起。证据缺失、进程失联或无法确认是否下载一律不猜0次，报告人工处理。
4. `submission_no`按已有持久发起单调+1，至多10；业务`attempt=1`不变，key的`attempt_scope`使用D加提交序号。同slot不重发，不使用随机key、业务attempt=2或每次tick自增；cursor不是序号和机会的权威。
5. job预检确认上游未就绪时，生成器yield含`PRECHECK_NO_DOWNLOAD`、D/Q/slot/submission_no的观察并正常结束，不产生数据可用物化。写不成该结果的终态不得当成明确未用。正式实现以隔离测试证明事件持久顺序和重启恢复。

### 3.5 用既有持久tick保留跳过决定

只复用Dagster原生sensor评估记录；不新建表、文件、锁，不调用create_tick/update_tick。沿现有`build_sensor_cursor/build_cursor_details`，在`details.runtime_state`携带`slot_decision_version:int=1, execution_day:ISO日期, closed_slots:list[int]`。closed_slots去重升序、至多10项、每项精确int且0～9；现有builder会移除空集合，合法同日/版本下缺closed_slots按空清单解析。中文SkipReason仅供展示，不能解析中文决定是否再发。

本机Dagster普通sensor会把SensorResult的cursor同时保存到其已完成tick，清空当前sensor cursor不删除旧tick。每次评估均携带当天已关闭slot的并集，以下原生接口集中在本数据集sensor内的`restore_stk_factor_pro_slots(context, execution_day:date, slot:int, now:datetime)`；返回`tuple[frozenset[int], bool]`，第二项表示当前slot可以继续选择，false仍须正常返回SensorResult以持久当前决定。

```python
from dagster._core.definitions.run_request import InstigatorType
from dagster._core.remote_origin import RemoteRepositoryOrigin
from dagster._core.scheduler.instigation import TickStatus
from dagster._serdes import create_snapshot_id

origin = RemoteRepositoryOrigin(
    context.code_location_origin, context.repository_name,
).get_instigator_origin(context.sensor_name)
ticks = context.instance.get_ticks(
    origin.get_id(), create_snapshot_id(origin.get_selector()),
    after=day_start.timestamp(), before=now.timestamp(), limit=1,
    statuses=[TickStatus.SUCCESS, TickStatus.SKIPPED],
)
```

`day_start`为D日00:00的Asia/Shanghai aware datetime，now同一时区；context真实location/repository/sensor身份必须齐全，不能虚构context.selector_id或只按同名sensor全实例查询。上述内部导入和属性已对照本机源码，集中使用并做版本边界测试，不扩成通用适配平台。

判定顺序固定：

1. 正常解析当前cursor的同日集合；用`get_tick_retention_settings(InstigatorType.SENSOR)`确认SUCCESS/SKIPPED有效保留期至少1日或-1，再按上例只读最近一条已完成tick。当前STARTED不在查询状态中，不读取第二条绕过最近坏记录。
2. 最近tick为本数据集、本版本、同D时，与当前cursor集合取并集；窗口前记录携带前一日集合可丢弃。窗口内却日期不符、缺版本、结构坏或计数越界，视为当前slot不能确认。
3. 本日没有旧完成tick且`context.last_tick_completion_time`也不在D日19:00之后，是首次合法窗口评估，允许正常选择；不能因cursor为空就拒绝首次运行。若已有窗口内完成时间却查不到记录，则不能猜当前slot未关闭。
4. 身份/读取/保留期故障，或上述不能确认时，只把当前slot加入一个本版合法同日cursor，并正常return SKIPPED说明原因；不能反复raise使修正后的cursor始终无法落库。以后同slot仍关闭，下一slot可读到合法新记录继续判断；存储持续不可读时继续保守跳过。不得把一条旧坏记录永久当成全日故障。
5. 集合已含当前slot，或同slot已有持久run，直接跳过。活动run占用本数据集时把当前slot加入集合，跳过后同slot不再开放。已实际提交RunRequest也将当前slot加入集合；原生run_key和持久run仍负责提交去重。
6. 只是上游尚未就绪、尚未提交且无活动占用时，不关闭当前slot，允许同slot内以后评估继续等待。所有分支均用现有cursor factory保存合法同日小集合；过去slot不回放，补Q机会仍以run/开始事实为准。

最小隔离测试：19:30活动占用→SKIPPED持久→清cursor→19:45原run已结束仍不发；首次19:00允许；同slot上游后来就绪允许；坏记录只关闭当前slot、下一slot可正常选；同名不同location不混；读取失败和保留期不足不重复提交。至少用临时instance真实保存/读取tick一次，不能只mock返回列表。

## 4. job内的严格顺序与Dagster编码组织

```text
sensor：日历/时点/前日一次规则 → 股票复权因子Raw T/P就绪 → 提交单T job
  ↓
job开头：唯一写入/八字段 → 自动截止或人工重新执行/bootstrap授权 → 再核原T/P就绪
  → 读取T/P并比较 → 完整保存T回刷名单/待处理原因
  → 持久化本轮开始下载事实
  ↓
下载T日全部页 → 只在当前内存持有完整日unit → 正常关闭session并核最终summary
  → 校验内存U的必要字段/主键/日期 → 与T已发布文件按主键更新/补入，直接构造唯一Raw发布候选
  → 发布日Raw并读回/check → 发布日Silver并读回/check
  → 有bootstrap_context时：立即更新T的result及summary，再进入历史判断
  → 已发布日数据可供业务读取（不等覆盖和全部历史完成）
  ↓
先核原T已发布合并Raw的应有代码集合齐备，否则历史等待
  → 按§5.2.3确认原T Silver有效且对应当前Raw
  → adj_factor数据集T/P为回刷依据；技术行因子差异只诊断
  → 仅整范围成功且仍有效的同基准历史不重复
  → 完整变化/原失败名单不按本轮返回集合缩小
  → 历史前再次核对股票复权因子数据集输入
  → 重新下载本轮完整待处理范围的全部股票/窗口并完整保存
  → 按日期批量合并/校验/发布d<T的Raw和Silver
  → 有bootstrap_context时：每批已完成日期更新result/summary，失败亦保留真实日结果
  ↓
分别报告日数据可读、代码覆盖、完整名单与历史完成/待处理
```

股票复权因子数据集T/P未就绪就停在job预检，不进入日下载。两接口因子值不同按§12.1已确认规则只诊断，不阻断该股日Raw/Silver或历史，也不改源值。这不证明返回的指标结果已按新基准修正，只证明按规定adj_factor输入完成了本次下载/发布。

编码组织采用两个`AssetSpec`和两个`AssetCheckSpec`的multi_asset，job的selection包含该定义的两个资产及两项check；选择同一个`cn_a_stock_factor_pro_trade_days`。`can_subset=True`及开头完整selection拒绝规则严格按§2.1执行。同步函数依次调用§2.3业务函数；没有下载线程/进程或IPC职责下沉组件。

日阶段每资产最多产生一次输出：Raw已通过候选验收并完成提升/读回后，`yield MaterializeResult(asset_key=Raw, ...)`，再yield Raw检查结果；失败显式退出后续。然后同样处理Silver及其check。物化及检查metadata均保存实际file_sha256、contract_content_digest和processing_version，日Raw检查另保存本轮scope_digest、day_source_digest及必要合并对账计数；日source_manifest_digest为null，因为不保存日下载文件。Silver物化及check都保存raw_sha256，值为生成该Silver的已验证正式Raw字节SHA；同时保存对应Raw物化/文件身份，供§5.2.3直接复用。这些是后续直接读取已通过检查的依据，不要求消费方重造B/U。合法0新增但存在旧文件时只核真实结果；首次空结果不造空文件或虚假可用物化，使用skippable处理并记录原因。源少股票但有有效行不走“检查失败”。

预检明确未下载时，先yield包含`PRECHECK_NO_DOWNLOAD`的真实观察，恢复后正常结束，run为SUCCESS；没有物化及check评估，不消耗前日业务下载机会。已经下载但没有可用日数据的分支按§4.0.1记录业务失败，不能标为PRECHECK_NO_DOWNLOAD。本定义不调用`set_requires_typed_event_stream`，使用`can_subset=True`允许省略实际未执行的输出，不补造`Output(None)`或绿色检查来凑输出数。对应临时instance回归必须分别断言这两种终态、观察持久以及没有虚假物化/check，不能只检查装饰器属性。框架输出组织与业务是否更新成功是两个判断；允许省略检查并不表示业务必须SUCCESS。

日更和手动repair均沿用原对象历史窗口，结束日期可以是原T；这不是全市场BY_POINT日更。完整保留该对象请求的T行用于来源和差异诊断，正式历史只改d<T，因此不重复yield日阶段同一个资产输出。历史日期采用显式`AssetMaterialization(asset_key, partition=d, metadata=...)`；对应check使用本机已有的`AssetCheckEvaluation(partition=d, blocking=True, ...)`并关联该次物化。当前`AssetCheckResult`没有partition参数，禁止自造。事件要按正常run写入，不把日常更新变成runless补记。

历史事件固定通过生成器yield：文件读回后yield本批各日期/层的`AssetMaterialization`，生成器恢复后按当前run有界批量读取这些已保存的物化，再构造并yield各自`AssetCheckEvaluation`。只按本批已发布的资产/日期/文件身份匹配真实记录，缺记录或身份不符停止，不猜storage_id；`target_materialization_data`绑定该真实物化。不得先`context.log_event`后立即读取尚在缓冲的记录，也不能每日期深扫全部event history。相应API依据与当前实现见§9，仍须在临时instance验证顺序、持久化及分区关联。

批次处理保存当前run实际已发布且读回通过的目标及audit列表，每文件完成才加入，不把候选或未确认提升加入。正常批末flush；可捕获的普通业务异常先保留原异常，再对已经完成的目标flush同样的物化/check事件及§10.5.6统计，最后重新抛原异常；尾部只有Raw也只发真实Raw事件。若flush再失败，作为附加原因记录，不能覆盖最初错误。不能在GeneratorExit/强制进程退出时依赖finally里yield；此时只关闭资源、保留文件/intent，旧统计身份不匹配便不可用，下次原生重执行仍全新下载，不承诺硬退出时一定补完事件或统计。取消可安全收尾时仅处理已经完成的目标，不领新文件。

批读固定使用`instance.get_records_for_run(context.run_id, of_type=dg.DagsterEventType.ASSET_MATERIALIZATION, limit=N, ascending=False).records`，N为本批实际已yield的物化数量，最多40；N=0不查询。本数据集同run由单个执行线程产生这些物化，读取后按本批预期的(asset_key, partition_key)一一对应，数量、重复、当前run或物化metadata的`file_sha256`不符均停止。检查构造引用当前已保存的EventLogRecord：

```python
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation, AssetCheckEvaluationTargetMaterializationData,
)

target = AssetCheckEvaluationTargetMaterializationData(
    storage_id=record.storage_id,
    run_id=record.event_log_entry.run_id,
    timestamp=record.timestamp,
)
yield AssetCheckEvaluation(
    asset_key=record.asset_key,
    check_name=expected_check_name,
    passed=audit.passed,
    metadata=check_metadata,
    target_materialization_data=target,
    severity=dg.AssetCheckSeverity.ERROR,
    blocking=True,
    partition=record.partition_key,
)
```

`expected_check_name`按已核本批目标的层取§2.1固定check名，check_metadata复用该目标读回校验结果。timestamp来自真实物化，不取当前时间；构造方式参考现行`defs/bootstrap/moneyflow_history_events.py::_evaluation`及`defs/checks/stock_suspend_confirmed_checks.py`，不调用其业务或runless流程。已存在且内容等价的正式文件不重复replace，但如实产生本轮验证事件、metadata标记`mode=reuse`及真实file_sha256；无正式文件的空日期不造事件。

历史下载/处理失败时，已发布的日Raw/Silver不回滚、不删除，不要求业务等待跨文件快照。run可失败且历史pending，与日文件及对应检查真实通过同时存在。不得通过把失败run整体当作“没有任何可用数据”抹掉先前发布。

### 4.0.1 请求成功但没有可用日数据时的业务失败

日更的三种事实分别记录：组件请求是否成功、实际文件是否发布并检查通过、原T股票是否齐备。组件`DownloadSummary.status=SUCCEEDED`且完整unit为0行是合法请求结果，不改下载器错误码；业务仍须按本节判断这轮是否更新到数据。不能仅凭`len(records)==0`让job失败，也不能仅凭组件成功让job变绿。

本节新增失败条件精确为：当前完整日unit及会话最终summary已验证成功、源行数为0，原T尚无既有日Raw/Silver文件（因而没有可合并发布的旧日数据），且按既有日历/生命周期/最终停牌/身份映射核实原T应有集合非空。已有Raw结构无效或与已有记录冲突时，先按原文件/合同错误停止，不把损坏目标当作首次无数据来覆盖。只有旧Silver而没有可用Raw属于原两层状态异常，不用旧Silver推断Raw已齐备。

编码位置与顺序：在`defs/assets/stk_factor_pro.py`同步生成器内，完整下载/verify成功后、首次Raw候选及正式提升前判断上述分支；使用`defs/asset_guards/stk_factor_pro_readiness.py`既有纯集合函数，将无旧数据/无新行的实际侧表示为同连接内明确schema的空代码关系，核应有、实际及缺失集合。源/候选不另落盘，不执行261列文件对账来证明一份不存在的文件。

1. 保留并引用请求前已经保存的唯一开始事实，只追加已经验证的成功0行请求摘要；不能在此再次写`download_started=True`。既有下载/阶段摘要写明“请求成功，源返回0行”，`day_source_digest`仍只来自本次成功内存结果。按§5.2返回`complete=False,raw_check_passed=False,actual_count=0`及真实expected/missing；没有Raw时`raw_file_sha256`、Raw物化/check id均为None。不得将None编造成文件SHA或检查id。
2. 通过§5.2既有缺失清单写函数保存并读回完整差集，再保存相应RawCoverage；缺失数量为N时，真实完整清单应有N项，样本仍最多20项。它是诊断，不是日下载缓存。
3. bootstrap_supplement须先按§10.5.6保存当前零实际集合/缺口的result及summary；原source/import事实保持不变，无虚假CurrentPublication。普通日更不创建bootstrap记录。任何诊断/统计写入失败按原本地读写失败处理，不宣称保存成功、不回滚正式数据，也不将该错误伪装成可以盲重试的源缺数据。
4. yield本run日阶段`AssetObservation(result="waiting", raw_coverage=上述结果)`，按§6.1已有阶段结构保存真实名单/授权引用，并用既有`goldenshare/summary`写明请求成功但日数据未取得；生成器恢复后抛`dg.Failure(..., allow_retries=False)`。主提示固定为`目标日尚无可用技术因子数据：<T>；应有<N>只，实际0只。`，Failure metadata为`goldenshare/failure_phase="day"`、`goldenshare/retryable=True`、`goldenshare/source_error_code=None`，并给出既定下一步。等待观察不是run成功，最终run为FAILURE。
5. 此分支不生成Raw/Silver空文件、发布候选、物化、AssetCheckResult或历史请求；不写日/历史completed，不解除原日失败。已保存开始观察仍算实际开始，不能补写PRECHECK_NO_DOWNLOAD收回机会。正常/finally仍释放本次UnitResult/U。

后续动作：目标是今天时由sensor在下一允许slot创建新run、重新下载，午夜及活动任务规则不变；目标是Q时一次机会已用，不自动第二次、不推进今天，由管理员处理；bootstrap人工补数失败后由管理员处理并再次执行，不由sensor提交，不因该run失败清空原operation统计。`retryable=True`只表示自动今天后续slot可重试，不启用当前op重试、repair自动重试或新的下载循环。

以下分支不扩成本节失败：取得4000/5000等有效部分日数据时，照原规则发布Raw→Silver及文件检查，记录覆盖False；在没有其他执行或历史失败时run仍可SUCCESS，后续按slot补齐。新源0行但旧Raw有效时，按B-K+U保留旧行并从当前最终Raw生成/核验Silver，再据当前正式代码集合判断覆盖，不能因本轮0新增就报“实际0”。应有集合无法确认时记录覆盖None及具体缺失依据，不能声称缺N只或覆盖齐备；确认为空时按原无操作/等待事实结束，不伪造文件或绿色检查。这些分支均不借请求成功扩大历史资格，历史仍要求§5.2及§5.2.3全部成立。

### 4.1 管理员手动历史repair入口

`raw_tushare_stk_factor_pro_repair_job`仍为手动op job，无自动sensor。`repair_stk_factor_pro_history`使用`out={}`、同步生成器和既有`lake_root`、`duckdb`资源；配置层级固定为`ops.repair_stk_factor_pro_history.config`。观察/物化/历史检查直接yield，失败前阶段观察须先yield落入原生事件流，不只写log_event缓冲。本入口只处理原目标日T完整名单、原起止范围内的d<T历史；不发全市场T日请求，不进行对象T日确认查询，不发布T，不嵌套调用任何日更新函数。

配置固定为以下四项，全部必填；其他字段一律在配置校验时拒绝，不能忽略或增加兼容分支。

| 字段 | 类型及校验 | 消费者和含义 |
| --- | --- | --- |
| `target_trade_date` | 严格ISO日期str，解析为date；SSE开市日，已登记；必须与原记录T相同。 | 当前运行的历史所属日期，不是实际执行日。 |
| `source_run_id` | 已核实的本数据集update或repair run_id；记录必须属于相同原T。 | 只定位原完整plan/ranges授权、未完成历史意图和原失败引用；不得读取其下载文件作为当前网络结果。 |
| `expected_history_plan_digest` | 64位小写SHA-256，精确匹配原完整plan。 | 防止复制错误任务或用部分股票名单代替原完整授权。 |
| `expected_history_ranges_digest` | 64位小写SHA-256，精确匹配原完整代码/起止范围。 | 不接受管理员另传股票、年份或文件路径扩大范围。 |

```yaml
ops:
  repair_stk_factor_pro_history:
    config:
      target_trade_date: "2026-10-21"
      source_run_id: "<原自动任务或上次repair的真实run_id>"
      expected_history_plan_digest: "<原完整plan摘要>"
      expected_history_ranges_digest: "<原完整范围摘要>"
```

本配置持久化于当前Dagster run_config，不新增env、表或页面开关。实际执行日只用于metadata和维护记录，不能替换T/P。配置源run是前一次repair时，读取它保存的原完整授权引用，仍直接核对原T和完整原范围，不把前一次repair实际处理范围当成新授权。所有新记录只写当前run的受控staging目录；只按已验证的source_run_id和固定授权引用读取原记录。

source_run属于bootstrap_supplement或继承其上下文的repair时，另从该精确run的开始/阶段观察读取已核bootstrap_context，核原operation/approval/T及§10.7原授权观察；四项repair配置不增加字段。当前repair在首个历史请求前将同一Context随自身开始观察保存并读回，历史发布后按§10.5.6更新该operation相应日期result/summary。不能从同T任意run猜operation，也不重新要求当前T缺口>0；repair本来就要求T Raw齐且Silver有效。原授权或引用坏时停，不借此扩大历史plan/ranges或触发T日更新。

严格顺序如下：

1. 校验配置、source_run身份、同T、两项完整授权摘要和受控路径；验证维护窗口、无其他活动写入及bootstrap未运行。任意错误在网络和正式提升前停止。
2. 核对日历T/P和原完整范围，不下载历史；先进入下面原T Raw检查。这样原T Raw缺失时优先给出约定的日数据缺失提示，不先被其他来源错误掩盖。
3. 调用§5.2统一Raw齐备检查，读取**原T当前正式、合并后的Raw文件**；不能从旧下载候选、今天Raw、旧绿色check或一份有相同行数的文件判断原T齐备。
4. 若原T文件缺失、必要字段/check不通过、应有代码缺失，或生命周期/停牌输入不足以确认覆盖，立即抛`dg.Failure(..., allow_retries=False)`。主提示固定为`原日期数据缺失：<T>；请管理员处理原日期数据后重试历史repair。`，metadata补充具体原因。此分支零技术因子请求、零历史提升、零T写入；管理员另外处理原日期数据。本repair绝不代办，不让外层重试策略把这个报错变成重复执行。Raw齐备后紧接着执行§5.2.3的原T Silver检查：已有正式文件、最新有效物化及绑定通过check、对应当前Raw。失败直接按该节固定提示退出，同样零技术请求/零正式提升，不补当天Silver。
5. 原T Raw齐备且Silver有效后，读取当前`adj_factor`原T/P就绪及实际因子，核关键因子/可信范围；不足明确停止，不伪造0变化。只允许原范围内因子值修订，保存当前依据和差异；T/P重新相等不能删除原未完成历史意图，不追加股票、延长范围或更换T。完整保留原授权名单及原范围。按§5.4核对**此前独立整范围成功且仍有效**的事实，确定本次原失败范围；失败run部分或全部物理完成均不能用于缩小它。若已无待处理历史，保存真实`no_action`结果后结束，零技术请求、零正式提升，不伪造本run新完成历史。存在待处理历史则完整保存当前请求范围；不能因失败run只下载了部分股票而缩减该失败范围。全天停牌股票可无T技术行，不额外请求T。缺关键因子或可信范围时明确停止，不能挑一部分先回刷再宣称完整。
6. **每次重新执行，都从头下载该原失败范围的全部历史unit。**不读取失败run的`source/history`文件作为本次源，不复用其source-complete，不因失败run曾发布部分日期而跳过对应历史请求；只有当前run刚下载、保存、读回完整的历史源可用于当前run后续处理。组件单页有限重试仍适用，不增加op/job外层自动重试。
7. 当前历史全部源完整后，按原20交易日批次和日期升序，逐日期Raw合并/校验/提升/读回→从这份Raw生成Silver并校验/提升/读回。仅d<T。已经发布的文件不删除、不回滚；本次新下载结果与当前正式文件按既定主键规则合并，不使用旧失败run候选覆盖。当前run文件提升前后仍写既有intent/checkpoint；这是本次文件发布依据，不是跨失败run省下载的理由。
8. 仅在全部当前请求范围通过检查和物理读回后记录历史完成。失败/取消/异常退出保留正式已发布文件和原完整未完成意图；下一次repair仍全新下载原失败范围，不从页、股票或日期下载断点继续。成功/失败均在metadata说明原T、来源授权、当前新下载行数和实际发布范围。

原T Raw齐备且原T Silver有效并对应当前Raw，是自动job和手动repair进入历史的共同条件。日更通过当轮发布及检查建立事实，手动repair只读取已有有效DG凭据，不重新全字段对账。手动repair不消耗或重置自动补Q一次机会，历史完成只解除原T历史失败，不能解除日阶段失败。正式历史只d<T；T行即使出现在完整历史响应中也只留源证据，不发布T。不得要求所有待回刷历史日的Silver预先存在：某历史d缺Silver时，应从本轮刷新后的Raw d生成并检查。

### 4.2 自动、手动与bootstrap的写入互斥

本节只保证本数据集的业务写入安排，不改变下载器。沿用既有Dagster队列、入口预检及运营维护步骤，不新增锁、线程、进程管理、维护表、维护状态文件或repair运行开关。

#### 4.2.1 既有队列与适用范围

2026-10-23已只读核对本机正式`dagster.yaml`：使用`QueuedRunCoordinator`，`concurrency.runs.max_concurrent_runs=1`。正常经同一队列提交的日更及手动repair串行启动；正式repair和人工重执行仍通过该队列提交，不用`execute_in_process()`或直接调用资产函数绕过队列。运行前由运营核对该配置仍成立；若已改变，先停止本次手动执行并复核安排，程序不自行修改配置。队列行为依据[Dagster运行队列说明](https://docs.dagster.io/guides/operate/managing-concurrency/run-queue-limits)。

bootstrap是直接文件写入，不受该队列的单任务数量限制。例如19:30日更已经排队，管理员在终端直接执行bootstrap，稍后日更出队就可能同时改同一日期文件。停止更新sensor只停止后续自动提交，不会取消已排队任务，也不会停止正在执行的任务。

检查固定覆盖`raw_tushare_stk_factor_pro_update_job`和`raw_tushare_stk_factor_pro_repair_job`，不按T或分区过滤：不同目标T的两次历史回刷也可能改同一个旧日期文件。活动状态固定为`NOT_STARTED/QUEUED/STARTING/STARTED/CANCELING`；取消中仍算活动，必须等到终态。查询当前run时仅按run_id排除自身，不能把同job其他任务一并排除。

#### 4.2.2 运营在提交手动任务前完成的步骤

1. 记录更新sensor原本的RUNNING/STOPPED状态，在Dagster原生界面停止`raw_tushare_stk_factor_pro_update_job_sensor`并确认已停；分区注册sensor不下载、不写业务文件，不因本操作新增停启要求。不改cursor、run_key或前日机会记录，不暂停其他数据集。
2. 在同一instance查看本数据集上述两个job的全部活动任务。等待它们正常结束；确需取消时由管理员明确操作，取消后仍等终态。停止sensor时已在进行的评估仍可能提交任务，因此提交手动操作前必须重新查询，不能只凭刚点了停止判断已经清空。
3. 确认没有另一手动repair或终端bootstrap正在写本数据集；维护期间由运营保证不启动第二个直接写入。bootstrap没有Dagster run，活动run查询无法发现它；不增加进程扫描、锁或维护登记来假称程序能证明这一点。
4. 完成这些步骤后，才提交获准repair，或启动获准bootstrap。repair继续只用§4.1四项配置，不增加`maintenance=true`、跳过检查或任意覆盖参数。bootstrap继续使用§10批准输入，来源维护窗口与DG写入维护步骤都须满足。
5. 运行中保持更新sensor停止，不再提交本数据集其他写入。程序不接管sensor停启，不自动取消队列中任务。

这里的“等待任务结束”发生在手动任务提交之前，由运营处理。**手动任务已启动后发现其他活动任务，立即拒绝；禁止在占有唯一运行名额时循环等待排队任务结束。**否则repair占着名额，后面的任务无法启动，两边会一直等。

#### 4.2.3 编码落点、调用顺序和失败处理

在既有拟新增文件`defs/asset_guards/stk_factor_pro_readiness.py`内实现§2.3的两个函数；固定两job名称和活动状态在`defs/run_contracts/stk_factor_pro.py`单处维护。读取方式沿用现行`asset_guards/dc_board_run_recovery.py::read_dc_run_history`的有界活动查询语义，不调用其东财业务恢复逻辑，也不迁移旧消费者：

```python
def read_stk_factor_pro_other_active_runs(instance, *, own_run_id=None):
    active = []
    for job_name in STK_FACTOR_PRO_WRITE_JOB_NAMES:
        records = instance.get_run_records(
            filters=dg.RunsFilter(
                job_name=job_name,
                statuses=STK_FACTOR_PRO_ACTIVE_RUN_STATUSES,
            ),
            limit=2,
        )
        active.extend(
            record.dagster_run for record in records
            if record.dagster_run.run_id != own_run_id
        )
    return tuple(sorted(active, key=lambda run: (run.job_name, run.run_id)))
```

`STK_FACTOR_PRO_WRITE_JOB_NAMES`为上述两job组成的tuple；`STK_FACTOR_PRO_ACTIVE_RUN_STATUSES`为上述五个`dg.DagsterRunStatus`值组成的tuple。每job取2条可避免“首条是自身、第二条是其他任务”被漏掉；最多返回4条，只用于确认冲突和提示，不当成运营需处理的完整清单。不遍历历史run或event，不扫描Lake，不加日期过滤。`own_run_id`只由当前执行context提供，不从业务配置或原失败run读取；bootstrap固定None。查询异常向调用方传递，不能`except`后返回空tuple。

| 调用点 | 查询及有冲突/读不到事实时的动作 |
| --- | --- |
| 更新sensor §3.2第2步，本次评估唯一活动任务查询 | 不传自身run_id，结果在本次评估中复用；有其他活动任务则SkipReason。查询失败按§3.5关闭当前slot并持久跳过，不反复raise；不消耗尚未开始的Q下载机会，不新增排队任务。 |
| 自动job开始、任何技术因子请求前 | 传`context.run_id`排除自身，再查一次；冲突或证据不可读则走已有`PRECHECK_NO_DOWNLOAD`分支，不下载、不写开始下载事实、不产生物化。 |
| 手动repair入口、历史网络请求前 | 传`context.run_id`；调用require函数，有冲突或查询失败立即`dg.Failure(..., allow_retries=False)`，不下载、不提升，不在job内等待或外层自动重试。 |
| bootstrap入口、首次Prod明细读取前 | 使用调用方提供的既有instance进行只读查询，`own_run_id=None`；不初始化instance、不创建run。冲突或查询失败立即终止，不读取明细、不提升文件。 |
| 每次执行的首次正式文件提升前 | 再调用同一require函数；每次正常运行或重新执行各一次，不按每页、每股票、每日期反复查队列。冲突即停止后续处理；已经取得的候选按原失败规则保留证据，不把它记为“未下载”。 |

require函数复用读取函数，空tuple正常返回，冲突或读取失败抛上述Failure；提示“存在其他股票技术因子任务”或“无法确认股票技术因子任务状态”，给出安全的run_id/job_name/status样本及“保持自动更新停止，处理完活动任务后重新发起”的下一动作。不新增源请求错误码，不将任务冲突送入下载器重试。每次检查至多2个有界查询；执行入口及首次提升前合计最多4个，sensor单次另外2个，不增加按历史日期数量增长的队列读取。

一次查询不是锁，无法阻止查询结束后有人绕过维护要求启动另一终端bootstrap。程序预检与运营保证共同成立才可执行；正式替换前仍逐文件核对已有目标指纹，发现意外改写立即停止，不覆盖未知结果。保持候选完整校验、逐文件提升和失败后重新下载规则，不承诺多个文件整体原子提交。

#### 4.2.4 收尾和恢复自动化

手动任务结束后，运营确认对应run已到终态或直接bootstrap进程已经退出，并查看已发布文件、未完成范围和错误。正常完成且允许恢复时，仅将原本RUNNING的更新sensor恢复为RUNNING；原本STOPPED的继续保持STOPPED，首次bootstrap也不会顺带启用尚未获准的自动化。

失败、取消、进程状态不明或恢复操作失败时，先保持sensor停止，由运营确认处理后再明确恢复；不能在`finally`里无条件启动sensor。恢复失败只影响后续自动调度，不回滚已发布文件，不改写手动任务的业务结果，不恢复Q机会、不清cursor，也不补发已经过去的半小时时点。后续仍按原19:00～23:30、午夜截止和前日一次规则运行。

本节新入口与队列行为在实现后使用临时instance验证；当前仅有配置、现行代码与设计依据，未执行新入口测试，也未操作正式sensor或队列。

## 5. 完整回刷名单与本轮候选记录

### 5.1 先名单，后技术因子下载

本节日更入口包括bootstrap_supplement的首次人工补数及其原生重执行；它们同样在T/P就绪后、技术因子请求前生成完整名单，不绕过本节规则。

每次同T的日更job（自动或人工重新执行）都用当前`adj_factor`数据集原T/P重新比较、重新保存本run完整名单。通过§6.2直接读取DG已有观察中的同T未完成范围和成功事实；业务输入未变时内容摘要可以相同，不复用失败run的下载源、候选或部分下载进度。手动历史repair严格按§4.1先查原T Raw齐备，之后才核T/P及原完整授权，不重新扩大授权。两入口都保留已知未完意图：修订后T/P相等也不删除旧未完历史，仅生命周期证明该股本无待刷历史时记录依据和排除原因。不能因本轮源少了一只、源超时、股票暂时无T行就把它从已知变化名单删除。

例如前次任务在生成名单时失败，还没有保存`history-plan.json`：本次日更新直接读取当前T/P重新计算，不尝试读取不存在的文件。若DG已经明确记录了原历史回刷名单，则读取其中哪些股票、哪些起止日期尚未刷完；该记录损坏时报告具体引用，不能把原待回刷股票当成空集合。这里保存的是历史工作范围，不是日下载数据。日数据每次都重新下载，历史失败后的完整原范围也重新下载；只有正式已发布业务文件保留供合并。

比较以T/P的`FULL OUTER JOIN`按代码显式对应，再并入本数据集可信既有历史/同一目标T旧pending中明确应核对的有界代码范围；不能只以T为左边，也不能inner join后漏掉P有T无旧股。至少区分两日都有且变化/不变、T有P无、P有T无、以及既有范围/旧pending证明应核对但两日都缺。后两类没有生命周期或其他明确解释时保留无法判断，不写“0变化”；证明退市也要留下解释，不能静默删除待处理。生命周期可证明的真新股不造上市前历史，单列新股结论；旧股票缺P保留原因。这是本数据集有界对象比较，不新增全市场覆盖发布门槛。没有变化必须能证明输入已检查；股票复权因子Raw文件就绪不意味着每只股票都必有两日值。

只比较股票复权因子数据集值，不新增任意浮点阈值。需要更新历史的变化股从可信既有最早日期到T；无既有历史时解释新上市或异常。最早日期取初始化验收/可信范围或有界聚合，不在sensor逐tick扫描全湖。修订后的因子恢复旧值不取消原未完回刷；下载和发布仍应完成原范围，不能把“写了新清单”当成旧任务自动完成。


#### 5.1.1 历史起点的统一规则（所有历史入口必读）

**历史起点固定指：这只股票在本数据集中已有且可信的最早技术因子日期。它是既定规则，不是待管理员重新定义的参数。普通日更、人工日更、bootstrap后的补数及手动历史repair都采用本节。**原§10.7.2第5项已有的取得办法在这里集中说明，该处引用本节，避免只阅读历史规划时漏看。

1. 优先复用已验证的初始化/原范围记录中该股最早日期；有多个有效依据时保留最早的可信边界，不因当前入口、当前批次或较窄日期窗口裁短。这里只读业务函数已经核实的记录，不新建起点配置、文件或PG表。
2. 没有现成边界的股票，由本数据集业务函数使用同一主要DuckDB连接，对本次需核的代码集合、已批准且可信的现有Raw日期集合，显式投影ts_code/trade_date，执行一次按代码的MIN(trade_date)批量聚合。路径由既有Raw路径函数按日期复算；先验证日期表示和既有文件依据，得到Python DATE。不能对每股分别扫文件，不能在sensor每tick扫描全湖，也不能把一个未证明覆盖完整历史的窄日期窗口当作最早日期的依据。没有找到行时返回该股未知，结合生命周期区分真新股和异常，不默认为上市日或T。
3. 取得的日期、依据种类和依据日期通过本节内部冻结记录传入规划函数，按§5.4写入原history-ranges。函数检查代码、精确date类型、start<=T以及kind/date对应；调用方负责根据已核事实生成，不能用新增run_config或任意passed=True绕过。数据集最早日期的含义不依赖PG或bootstrap是否已经开发。
4. DG的PG读取只负责找到旧完整名单、未完/成功范围及其引用，属于第五批；bootstrap导入及其已核范围可以提供已有依据，属于第四批。第三批通过明确输入消费这些事实，不import bootstrap执行模块、不访问Prod，不为了取日期提前实现第四/第五批。内部函数参数不是管理员新增配置项。
5. 必须回刷的旧股票仍不能确定起点时，保留原对象和NULL依据，按§5.1.2停止本轮历史，不能删掉该股后声明全范围完成。生命周期已证明没有原历史的新股另走原因6，不拿“没查到日期”冒充这个证明。

例如：A已有技术因子最早为2015-01-05，本次就从该日请求至原T；即使上市更早或当前某个文件只包含2020年以后，也不能把起点改为上市日或2020年。这里是对既有规则的强调，无新增业务门槛。

#### 5.1.2 完整名单到本次下载unit的逐项判定

`full_code_count`始终等于history-ranges的唯一股票数；`expected_units`只描述本次确实需要新下载的完整范围，两者不能强制相等。先保存完整plan/ranges及其业务摘要，再按以下表确定是否能进入下载。处理结论由既有字段和成功引用推导，不新增可由业务随意填写的状态列或字符串枚举。

| 对象/范围的实际情况 | 完整名单和依据 | 是否进入本次expected_units |
| --- | --- | --- |
| T/P没有变化、没有旧未完意图 | 已核比较说明确无新工作；可为空名单，不伪造源完成 | 不进入，不建立0-unit下载任务 |
| 本次变化，或已知原未完；关键T/P及完整起止已知 | 保留完整原范围；当前T/P重新相等不抹掉旧意图 | 每个仍需刷代码一项mode5完整范围，不按20日切短 |
| 该独立完整范围已有成功且输入仍匹配 | 保留原成功记录引用；严格核§5.4.3的producer SUCCESS、原T/代码/起止/T/P/合同及后续影响 | 仅该已证明成功的完整范围免刷；失败run的部分成果不进入此分支 |
| 生命周期及已有记录已证明没有原历史 | 保留原因6及依据；不造上市前范围 | 不进入，不能把“起点查不到”当作原因6 |
| 必须回刷但关键因子或起点尚未判明 | 原对象、NULL范围/值、原意图仍留在ranges及plan摘要 | 整个本轮待请求范围不可执行；历史请求/提升0，不能先过滤未知行再称完整 |

未知分支由正常日更编排保留有效日发布、记录历史waiting及具体对象/原因，不生成历史source-complete或publication-complete；手动repair按既有前置规则停止并提示。若内部代码越过判断而调用下载函数，函数必须在网络前拒绝不完整输入，按§6.1输入合同错误处理，不能默默缩小范围。第三批落实这个零网络的输入保护，第五批负责把判断接到正式阶段观察及入口；不增加自动补数或断点能力。

原完整待请求范围无未判明项后，排除有完整成功证明或原因6的对象，按code/start/end排序生成唯一expected_units；其scope_digest及后续manifest精确描述这份已判明的完整请求范围。plan摘要仍包含所有保留对象和未知行，不能只摘要实际下载子集。原成功范围、无历史解释和本次完成结果一同供后续整体判断，不能用本次unit数代表全名单完成。

例如：完整名单A/B，B必须回刷但起点未知，本轮不能只下载A并记录“历史完整”。若B是有依据证明没有旧历史的真新股，则保留原因6后，A的完整范围可以形成实际下载清单。

### 5.2 原目标日Raw齐备后才允许历史处理

完整变化名单在任何技术因子下载前依据`adj_factor`原T/P生成并保存；日Raw/Silver可少股票发布。只有**当前正式Raw T包含全部应有股票、且必要文件校验/check通过**，才允许该T开始任何历史下载或历史发布。缺股票或覆盖无法确认都不回刷。Raw齐备不是分页完成、总行数达到某值，也不是要求每个上市股票都必有T行。

应有代码按现有语义构成：

1. 使用已就绪且实际schema有效的`silver_stock_lifecycle`，取人民币A股中`list_date <= T AND (delist_date IS NULL OR T < delist_date)`的代码。新股只从真实上市日起计算，不用当前list_status代替历史有效期。
2. 先调用现行`defs/sensors/readiness.py::suspend_d_ready_for_trade_date(instance, T.isoformat())`核对T停牌数据必要事件/check，再核正式`silver_stock_suspend_daily_path(lake_root, T.isoformat())`的日期、`ts_code/trade_date/suspend_type/suspend_timing`及实际文件身份。只有`suspend_type='S' AND suspend_timing IS NULL`可从上市集合扣除；非NULL盘中停牌仍在应有集合。
3. 从正式Raw T严格筛trade_date=YYYYMMDD(T)，取原ts_code与DATE业务日期。上市、全天停牌及实际三侧均用正式silver_stock_identity_map按source_ts_code、valid_from<=T<valid_to（开放端为NULL）统一为latest_ts_code后去重；self映射同样检查，不无条件兜底。按统一身份集合求expected EXCEPT actual，缺失0才齐备；额外合法源行保留。身份统一只用于覆盖，不修改Raw/Silver值、物理主键或历史下载对象。
4. 生命周期/停牌/身份依据未知、日期区间不覆盖T、三侧代码映射0条/多条，或Raw结构/主键/日期/check无法确认时，覆盖未知或不通过；不能INNER JOIN静默丢代码、把缺停牌文件当无停牌或以Raw自己反推应有集合。所有本数据集覆盖入口使用下述同一纯集合规则，避免bootstrap统计已齐而历史门槛因旧新代码不同仍报缺失。

不新增第三项blocking check，不让覆盖不足阻止日有效数据发布。自动job在日Raw/Silver都已发布并通过各自必要检查后执行本节检查；不通过时记录历史等待并正常结束已有日发布。手动repair在任何历史网络前先核本节Raw覆盖，再按§5.2.3确认原T Silver有效，不通过按§4.1明确报错。两项通过后再核权威T/P和完整原范围，全部原待修复范围才可进入历史请求。确认全天停牌股无T行不影响齐备及其d<T历史回刷，技术因子接口的同名adj_factor不同仍只诊断。

#### 5.2.1 内部接口与结果

以下evaluate/require读取判断接口放在既定`defs/asset_guards/stk_factor_pro_readiness.py`；write_stk_factor_pro_missing_codes诊断写入放在既定`defs/io/stk_factor_pro_history.py`，由job/repair编排调用。记录类型在既定`defs/run_contracts/stk_factor_pro.py`；读取判断模块不反向调用写入，不新增平台、数据库表、锁或独立状态资产。

```python
@dataclass(frozen=True)
class StkFactorProRawCoverage:
    target_trade_date: date
    complete: bool | None
    raw_check_passed: bool
    raw_file_sha256: str | None
    lifecycle_file_sha256: str | None
    suspend_file_sha256: str | None
    identity_file_sha256: str | None
    expected_count: int | None
    actual_count: int | None
    missing_count: int | None
    missing_sample_codes: tuple[str, ...]
    reason: str
    raw_materialization_storage_id: int | None
    raw_check_storage_id: int | None
    missing_codes_ref: RecordRef | None

def evaluate_stk_factor_pro_raw_coverage(
    instance: dg.DagsterInstance,
    connection,
    *,
    lake_root: Path,
    target_trade_date: date,
    verified_raw_audit: StkFactorProFileAudit | None = None,
) -> StkFactorProRawCoverage: ...

def require_stk_factor_pro_history_raw(
    coverage: StkFactorProRawCoverage,
) -> None: ...

def write_stk_factor_pro_missing_codes(
    connection, *, staging_root: Path, identity: RunIdentity,
    coverage: StkFactorProRawCoverage,
) -> StkFactorProRawCoverage: ...
```

同一readiness模块提供纯函数build_stk_factor_pro_coverage_keys(connection, *, target_trade_date:date, listed_relation:str, full_suspend_relation:str, actual_relation:str, identity_relation:str)。四个relation名只能来自本调用已验证的内部临时关系，前三者列为trade_date DATE、ts_code VARCHAR，identity列引用现行身份schema；不得来自run_config/任意SQL。返回固定计数结构StkFactorProCoverageCounts，字段为expected_count/actual_count/matched_count/missing_count/extra_count、identity_unmapped_count/identity_ambiguous_count（均int|None）、identity_unmapped_sample_codes/identity_ambiguous_sample_codes（均tuple[str,...]，升序最多20项）及reason:str。它只在现有连接计算，不读取instance、不读路径、不写文件。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProCoverageCounts:
    expected_count: int | None
    actual_count: int | None
    matched_count: int | None
    missing_count: int | None
    extra_count: int | None
    identity_unmapped_count: int | None
    identity_ambiguous_count: int | None
    identity_unmapped_sample_codes: tuple[str, ...]
    identity_ambiguous_sample_codes: tuple[str, ...]
    reason: str

def build_stk_factor_pro_coverage_keys(
    connection: DuckDBPyConnection, *, target_trade_date: date,
    listed_relation: str, full_suspend_relation: str,
    actual_relation: str, identity_relation: str,
) -> StkFactorProCoverageCounts: ...
```

纯函数对参与三侧的原代码/日期去重并集先核每项恰一有效映射，再按§10.5.3两项集合等式生成统一身份的expected/actual/missing/extra；缺失与额外临时关系固定stk_factor_pro_coverage_missing/extra（两列trade_date DATE、ts_code VARCHAR）。映射不能确认时所有业务覆盖计数为None，保留映射异常计数/样本；不能返回缺0。正常日更/repair调用方完成自身PG/check及文件前置后调用；§4.0.1无旧文件的0行分支是明确例外：调用方先核实日历/生命周期/最终停牌/身份依据及当前成功空unit，给actual_relation传本连接内明确schema的空代码集合，不要求不存在的Raw文件或通过check，也不调用普通原T Raw就绪门槛伪造检查；输出用于真实缺失记录和业务失败，不能标记文件可用。bootstrap按§10.5完成本地物理前置及当月关系后也调用同一纯函数，不调用含instance的日更evaluator，也不从readiness反向import bootstrap。§10.5.3的SQL即该函数实现依据，避免另写两套；当前RawCoverage.actual_count为统一后唯一身份数，不是Raw物理行数。日更writer从该纯函数missing关系构造原stk_factor_pro_raw_coverage_missing供既有诊断写入；完整缺失清单使用统一身份码，不改业务行。

identity_file_sha256来自已核正式身份文件，与Raw/生命周期/最终停牌SHA一起参与覆盖复用及失效。该文件不变且新物化等价时不重算集合；只改身份文件也必须失效重算。history-eligibility和PG阶段观察按RawCoverage完整结构保存该字段，§6.2读取同样核验，不只给bootstrap用途加特例，不修改其他数据集现行readiness。

`complete=True`仅允许全部必要输入已确认、Raw本文件check已通过、且missing_count=0；`False`表示已确定Raw缺文件/行/必要结构不满足，`None`表示现有证据不足或读回无法确认。raw_check_passed=True时两项storage_id必须是实际有效记录id；未能确认则相应id为None且不能通过。未知计数为None，不能伪造0；sample按code升序至多20项。`reason`仅用中文解释已存在的失败类别和位置，不成为新的可解析错误码；分支只读`complete`、check和已验证记录身份。

完整缺失清单固定写当前run目录的`diagnostics/day-missing-codes.parquet`，schema为`ts_code VARCHAR NOT NULL,trade_date DATE NOT NULL`，唯一键(ts_code,trade_date)、trade_date全部为原T，代码升序，行数精确等于missing_count。它只保存缺失股票及日期，不保存下载指标，不是日下载缓存。**写入eligibility/阶段观察等持久记录时**，missing_count>0必须有有效missing_codes_ref，sample是完整清单前至多20个代码；缺失0或计数未知时ref=None、sample为空，不制造空指标文件。先原子保存并读回清单，再保存引用它的eligibility/阶段观察；PG只存计数、样本和引用，不塞1000只股票全文。

计算与保存职责分开：evaluate只读取DG/文件并执行必要代码集合SQL，不写staging。发生新计算时，在传入连接建立固定临时表`stk_factor_pro_raw_coverage_missing(ts_code,trade_date)`保存本次完整差集，并先返回missing_codes_ref=None的内存结果；此结果不能直接冒充已持久化记录。job/repair紧接着调用write_stk_factor_pro_missing_codes，使用当前可信RunIdentity和已核staging根，核目标T、连接内差集行数/主键/日期与coverage一致，再用COPY原子保存、读回，返回填入RecordRef的新不可变结果。内部根路径不是新增运营配置。

sensor只读已有有效coverage；需要时可以计算上述临时摘要，但**不调用写清单函数、不保存eligibility/阶段事实**，不把无引用的内存摘要当作已保存结果。业务job保存日阶段结果或历史判断前必须完成清单保存。复用覆盖结论时保留原有效引用；引用丢失/损坏，只对原T重算必要代码及差集，job重新保存诊断，不重新下载、不重做261字段对账。输入未变且原引用有效时，不创建临时表或重写清单。

DG PostgreSQL中的物化、check和阶段结果是直接使用的凭据，不能把查询这些结果写成“每次重跑完整审计”。日阶段通过`verified_raw_audit`传入刚完成的当前Raw读回结果，核passed、T、layer、正式路径及文件sha后直接复用，不重做261字段对账。`raw_materialization_storage_id`和`raw_check_storage_id`保存实际已持久化记录id；只能通过本次yield后读回的真实记录填入，不能猜id。

repair或sensor没有本次B/U时，**不调用Raw合并对账函数、不读取旧下载数据来重做B+U、不用Raw与自身比较填全零**。按现行`readiness.py::_latest_materialization`、`asset_readiness_status`的资产/分区过滤与`target_materialization_data.storage_id`关联方式，读取原T Raw最新物化和对应Raw综合check；确认检查通过、blocking、契约/处理版本匹配、检查指向该物化，正式路径及当前文件sha与两项metadata一致，直接接受该文件生产时已经通过的字段/主键/日期/源保存/合并对账结论。例：原日run因历史失败而终态FAILED，不能否定此前Raw真实通过的检查。仅缺检查/绑定错误/文件身份变化时不得沿旧结果放行，报告管理员处理；本repair不替原日补做来源对账。

覆盖也复用已有结果：先核DG日阶段raw_coverage关联Raw物化/check真实有效，再按T、Raw SHA、契约/处理版本、生命周期、最终停牌及identity_file_sha256判断适用。全部不变直接用原计数/complete，不重算集合；新等价Raw物化/check只在核真实绑定后换记录id，不能仅因事件id变化重算或把新id填进未经核验的旧结果。

原日无覆盖，或Raw/生命周期/停牌/身份映射改变时，才对原T必要代码列重算；Raw不匹配有效生产检查时先拒绝。一次sensor/job复用同次身份/结果，不重复核文件、不查技术全历史、不重新下载。覆盖本身不读技术Silver，repair另按§5.2.3核原T Silver身份及DG记录，不重做261列；阶段观察按RawCoverage完整结构保存，无新表/check。

日更和repair的固定串联为evaluate→write_stk_factor_pro_missing_codes（有效旧引用/0缺失/未知时直接返回，无额外文件）→保存本次coverage→判断历史资格。`require_stk_factor_pro_history_raw`仅在coverage.complete is True且raw_check_passed为True时返回；其他结果一律按§5.2.2抛固定Failure。自动调用方不足或未知时写历史waiting并结束，不调用require；仅True时调用require，再核原T Silver及完整名单/范围。repair调用方保存实际coverage后直接调用require，不能把失败转成等待或执行日更新。sensor不走保存串联。

本结果保存到本轮历史判断记录，文件固定为`history-eligibility.json`，结构为record_version=1、当前RunIdentity、当前完整plan/ranges摘要、raw_coverage对象（逐字段对应上述结果）、target_silver:StkFactorProTargetSilver|None、evaluated_at。target_silver仅在按§5.2.3完成核验后填入，Raw前置未过或尚未进入该步时为None；不能把None当Silver通过。两接口因子差异另留诊断。该记录不作为下一失败任务复用旧下载数据的依据。

开始历史下载前、完整历史源结束后首次历史提升前、历史最终完成前，各核对原T Raw/生命周期/停牌及原T Silver仍是已确认输入，且Silver仍对应当前Raw。未变复用本run结果，不逐页/逐历史文件重扫全市场。Raw/覆盖依据改变时仅重算原T必要代码集合；Silver身份变化时仅重取原T最新物化/check及核文件身份，不重做全字段对账。覆盖不为True或Silver不能确认有效则停止后续历史，已提升文件不回滚。唯一写入维护规则不因此放宽。

#### 5.2.2 repair不通过时的失败与metadata

直接使用本数据集已规划的`dg.Failure(..., allow_retries=False)`及§6.1既有字段，不给下载器新增错误码：

```text
description/summary = 原日期数据缺失：2026-10-21；请管理员处理原日期数据后重试历史repair。
goldenshare/retryable = false
goldenshare/failure_phase = history
goldenshare/target_trade_date = 原T的ISO文本
goldenshare/source_error_code = None
goldenshare/summary = 上述固定主提示
goldenshare/next_action = 说明Raw文件缺失/缺哪些代码/输入未知；先由管理员另行处理原T，本job不嵌套日更新。
```

同一失败metadata附`raw_coverage_complete`（bool或None）、`raw_check_passed`（bool）、expected/actual/missing计数（未知为None）、至多20个缺失代码及本次已确认文件sha。只放统计和受控文件位置，不包含token。原T不能替换成repair实际执行日，错误不能被捕获后继续历史请求，也不能生成“原T日数据已更新”的物化事件。

#### 5.2.3 原目标日Silver的有效性

原T Raw覆盖通过后，日更与手动repair均调用本节evaluate及require，取得并记录target_silver.ready=True后才下载历史；日更前面的T日Silver发布/check已经完成，不重复做全字段校验，只读取该次已保存的凭据。两入口在历史下载前、首次提升前和完成前使用同样条件；同run输入未变直接复用上次结果。实现仍在`defs/asset_guards/stk_factor_pro_readiness.py`，类型在既定run_contracts，不新增检查定义或资产。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProTargetSilver:
    target_trade_date: date
    ready: bool
    silver_file_sha256: str | None
    current_raw_file_sha256: str
    source_raw_file_sha256: str | None
    silver_materialization_storage_id: int | None
    silver_check_execution_id: int | None
    reason: str

def evaluate_stk_factor_pro_target_silver(
    instance: dg.DagsterInstance, *, lake_root: Path,
    raw_coverage: StkFactorProRawCoverage,
) -> StkFactorProTargetSilver: ...

def require_stk_factor_pro_history_silver(
    result: StkFactorProTargetSilver,
) -> None: ...
```

调用前raw_coverage必须complete=True、raw_check_passed=True且Raw文件身份有效；复用已取得的Raw身份，不再查一次Raw或重新比较股票集合。固定步骤：

1. 用`instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=Silver, asset_partitions=[T.isoformat()]), limit=1)`取得原T最新Silver物化；没有记录不扫旧历史寻找绿色结果。check_key固定`silver_stock_factor_pro_file_contract_check`，沿现行`partition_dataset_readiness_status_from_latest_checks`调用`get_latest_asset_check_execution_by_key((check_key,), partition_filter=PartitionKeyFilter(key=T.isoformat()))`取得该分区最新检查；PartitionKeyFilter按现行readiness.py同一模块导入。没有物化时不再查询check。只读既有记录，不调用被装饰的asset/check执行函数，不改通用readiness消费者。
2. 核物化、check均是原T的Silver；check状态SUCCEEDED、passed=True、blocking=True，target_materialization_data的storage_id/run_id/timestamp均与这份物化对应。silver_materialization_storage_id取真实物化record.storage_id，silver_check_execution_id取返回检查记录的id，不能将检查执行id当成物化storage_id。核契约、处理版本和固定正式路径。生产run不必与本repair相同，也不能仅因原生产run后来历史失败而否定已通过的Silver检查。
3. 固定正式Silver文件须存在、无越界符号链接，其当前字节SHA与物化/check metadata中的file_sha256相同；该SHA在本次调用中只计算一次。Silver物化及check必须同时保存`raw_sha256`，两者一致且等于已确认的当前Raw文件SHA。日更Silver发布时写入此字段，不能由repair猜测补齐。Raw后来等价重物化、事件id变而文件SHA未变时仍可通过；不要求两层生产run相同，不用Raw事件id变化误判Silver过期。
4. 全部满足才ready=True；此时两项Silver记录id及所有文件SHA全有。缺文件、缺物化、缺check、绑定错误、旧Raw SHA、当前文件变化或读取失败均ready=False并写明原因；可缺的信息为None，不自行重建Silver或重做261列对账。一次检查最多1次物化查询+1次分区check查询+原T一份Silver文件身份核对；同run输入未变直接复用，不按历史日期增加。

require仅在ready=True时返回，否则抛`dg.Failure(..., allow_retries=False)`，主提示固定为`原日期Silver不可用：<T>；请管理员先处理原日期Silver后重试历史repair。`。failure_phase=history、retryable=False、source_error_code=None，metadata附Silver结果、原T、受控正式路径、当前Raw SHA及已有记录id；管理员看到具体缺失/不匹配原因。此分支零技术因子请求、零历史提升、零原T写入，不嵌套调用日更新/生成Silver。该提示与§5.2.2的Raw缺失提示分开，先Raw、后Silver，不能混淆原因。

本节检查的是**原目标日T**的Silver；不要求每个待回刷历史d的Silver预先存在。历史d缺Silver时，由本次刷新后的Raw d生成并检查，仍只发布d<T。日更、历史回刷及bootstrap历史事件补记产生的Silver物化/check均维护同一个raw_sha256字段，不能不同入口各用一个名字。target_silver结果写入已有history-eligibility及历史阶段观察的同名字段；失败前先yield包含实际检查结果的阶段观察，再抛Failure，不制造新的T物化或绿色check。

### 5.3 文件与结构

本run候选/业务记录位于`/Volumes/datasource/data_lake_staging/stk_factor_pro/trade_date=<T>/run_id=<当前run>/`，路径只由paths.py生成。失败后不删除旧证据，但新run不读取旧下载/发布候选作业务输入；原完整名单和范围授权可读回，避免丢失待修复意图。

| 文件/记录 | 当前用途 |
| --- | --- |
| `history-plan.json`、`history-ranges.parquet` | 技术下载前保存完整变化/原未完名单、权威T/P、可信范围和授权来源；不按本轮返回代码缩小。 |
| `history-eligibility.json` | 本轮原T Raw覆盖判断及输入身份。 |
| `source/history/`及其`source-files.parquet` | 仅当前run新下载的完整历史261字段unit，逐unit保存/读回/释放；不创建`source/day/`。 |
| `source/history/source-complete.json` | 只供当前运行在全部预期历史unit及全部会话成功后进入处理；失败后下一run不得沿用。日下载的完成凭据是当前内存`VerifiedDaySource`，不保存日source-complete、日manifest或另一份日源Parquet。 |
| `publication/<phase>/<d>/<layer>/` | 当前run原子发布必需的候选、intent、逐文件checkpoint及历史缺原键诊断；仅供当前run发布。day只构造一份Raw发布候选，随后从已发布Raw构造一份Silver候选，不能把日unit另存为下载中间文件。失败任务的候选不再被新任务读取。 |
| `publication/<phase>/publication-complete.json` | 当前完整范围物理发布读回事实；历史去重还须来源run最终成功，失败run部分或全部文件事实不免除新下载。 |

完整plan保存并读回后，先yield AssetObservation记录T/P、D/轮次、当前run、plan/ranges位置及摘要、受控staging目录，再写开始下载观察并读回，成功才联网。阶段完成和失败结果仍走已有事件metadata；历史source-complete不替代文件验收，run SUCCESS也不代替完整范围事实。日阶段没有保存下载中间文件或复用下载结果的分支。只按已验证run和固定路径读取历史工作范围/发布记录，不全扫staging。

### 5.4 现有记录的封闭结构与摘要

本节限定Tushare日更及历史处理记录的字段结构；bootstrap批准/源记录及覆盖附件分别以§10.2～10.5为准。记录类型/字段顺序/有限原因集中在`defs/run_contracts/stk_factor_pro.py`，读写在既定io模块；不新增数据库或记录平台。

#### 5.4.1 公共类型、身份与读写

| 类型 | 固定要求 |
| --- | --- |
| Date / Instant | Date为Python date、JSON YYYY-MM-DD、Parquet DATE；Instant为aware datetime、JSON固定微秒和+08:00。时间不参与业务输入摘要。 |
| Digest / Count | Digest为64位小写十六进制SHA-256；Count为非负精确int，不能是bool。 |
| Double | 经§9.1转换的有限float，Parquet DOUBLE；NULL按源字段可空合同，不用NULL冒充0。 |
| RecordRef | `{creator_run_id:str,relative_path:str,file_sha256:Digest}`；路径必须在已验证run的staging根内，不接受绝对路径、..或符号链接越界。 |
| ContractIdentity | `{contract_name:str,contract_version:str,contract_content_digest:Digest,processing_version:str}`，本期源名stk_factor_pro、独立version和processing_version均为1。 |
| RunIdentity | `{creator_run_id:str,source_run_id:str|null,execution_day:Date,target_trade_date:Date,previous_trade_date:Date,purpose:str,scheduled_slot:int|null,submission_no:int|null,business_attempt:int|null}`；source_run仅指原名单/范围授权。 |
| phase / purpose / layer | phase只day/history；purpose只today/previous_day/bootstrap_supplement/manual_repair；layer只raw/silver，固定Literal统一校验，不另加枚举映射。 |
| record_version | 精确int=1；未知/缺失字段、错类型或错版本拒绝，不能猜默认。 |

自动身份按§2.4；manual_repair实际执行日为当前上海日期，T/P仍原日期。bootstrap_supplement首次D为实际上海日期，重新执行仍保留原D。两人工用途slot/submission/attempt均null；自动previous_day的attempt=1、submission=1～10，today后两者null。source_run_id仅原意图/名单引用，bootstrap首次为null，不伪造旧run；bootstrap授权在Context中独立保存。新run只写自己目录，不修改旧run。

HistoryPlanReason为集中有限IntEnum：1=本次T/P变化，2=原T失败/未完范围保留，3=缺P，4=缺T，5=两日因子都缺，6=生命周期证明无原历史。每股原因去重升序；它是名单解释，不是下载器错误码。

统一写入：校验完整结构/交叉条件→受控临时文件→flush/fsync→os.replace→fsync父目录→最终路径读回。旧历史下载文件可保留排障，日下载没有单独保存的中间文件。读取原记录时只取历史工作范围/授权/失败或已成功事实，不把旧历史Parquet当本run源。接口：

```python
def read_stk_factor_pro_history_plan(root: Path, *, expected_target: date,
    expected_run_id: str) -> HistoryPlanRecord: ...
def write_stk_factor_pro_history_plan(root: Path, record: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...], *,
    connection: DuckDBPyConnection) -> HistoryPlanRecord: ...
def read_stk_factor_pro_history_ranges(
    connection: DuckDBPyConnection, *, root: Path, plan: HistoryPlanRecord,
) -> tuple[HistoryRange, ...]: ...
def verify_stk_factor_pro_current_source(root: Path, record: SourceCompleteRecord,
    *, connection: DuckDBPyConnection, current_run_id: str,
    expected_units: tuple[UnitProjection, ...]) -> VerifiedSource: ...
```

`read_stk_factor_pro_history_ranges`在既定io/stk_factor_pro_history.py内与plan写入共用schema/摘要验证：root绑定plan.identity，ranges_ref绑定同run固定history-ranges.parquet，先核安全路径及文件SHA，再核完整schema、唯一代码、字段NULL/日期/原因规则、唯一代码数等于full_code_count、history_ranges_digest对应，返回冻结tuple。`build`返回plan后，调用方只通过该函数取得传给download的ranges，不能自行解析或删未知行；写/读Parquet都使用传入主要连接，不在helper新开连接。

`write_stk_factor_pro_history_plan`负责新ranges文件的物理引用：输入record的身份、固定相对路径及两个业务摘要先严格核对；写成并读回新Parquet后，以实际文件字节SHA构造最终ranges_ref，使用dataclasses.replace生成最终冻结plan，再原子保存JSON并读回返回。输入record仅作本次新计划的构造值，其ranges_ref SHA不能被调用方当成已落盘凭据；调用方必须使用函数返回的plan。已有ranges或plan一律拒绝覆盖，不用此方法修补旧记录；业务摘要不被writer改写。

`verify_stk_factor_pro_current_source`的`connection`是必填关键字参数，由历史下载及历史发布调用方传入其正在使用的同一个主要DuckDB连接。函数用该连接读取manifest及当前run源Parquet，核真实schema、行数、股票、日期范围和记录对应关系，同时核文件SHA；不能只核SHA而省略内容检查。函数不创建或关闭连接，不使用DuckDB隐式默认连接，不新增Parquet依赖。历史下载在全部session正常退出后调用，历史发布在消费源之前再次调用；两处均显式传`connection=connection`，所有临时关系在核验结束或失败时清理。

`SourceCompleteRecord`及`VerifiedSource`只用于phase=history，保存当前run历史文件引用/统计。verify必须要求record.phase==history且record.identity.creator_run_id==current_run_id，错阶段/错run即拒绝，不能通过原run有效而放行旧源。日阶段使用以下仅存内存的类型和接口，不执行JSON序列化、Parquet写入或RecordRef生成：

```python
@dataclass(frozen=True, slots=True)
class VerifiedDaySource:
    identity: RunIdentity
    contract: ContractIdentity
    unit_result: UnitResult
    summary: DownloadSummary
    raw_relation: str
    scope_digest: str
    day_source_digest: str

def verify_stk_factor_pro_day_source(
    connection: DuckDBPyConnection, *, identity: RunIdentity, result: UnitResult,
    summary: DownloadSummary, contract: ContractIdentity,
) -> VerifiedDaySource: ...
```

`verify_stk_factor_pro_day_source`只在下载session成功退出后调用。校验当前run/T/契约、单一BY_POINT unit及scope、全部scope完成的termination、observed_field_sets、统计与最终summary，精确要求total/completed/delivered unit均为1、两项summary行数均等于len(result.records)及unit统计。随后按§9.1从本次records按列构造当前U，在本任务主要连接执行`CREATE TEMP TABLE stk_factor_pro_day_source AS SELECT <显式261列转换> FROM current_batch`；校验字段/日期/主键/数值和完整业务内容后按§5.4.2计算day_source_digest。必须是独立临时表，不能用解除DataFrame注册后即失效的view；转换DataFrame注册可解除，临时U保留至日发布完成，finally执行DROP TABLE并释放对象。不COPY出日源文件。raw_relation只能是此内部固定名，不接受配置SQL或外部名称。类型是调用内部传递数据，不能来自读取旧文件，构造器不得接受外部传入passed或摘要来绕过计算。

组件`UnitResult.records`为已交付tuple；`DownloadSession`关闭释放自己的引用，不修改调用者仍持有的tuple，因此可在with成功退出后处理本次结果。不得把它存入全局缓存、其他run或序列化为日源文件。日Raw正式读回和Silver发布/读回结束后立即释放result、VerifiedDaySource及其持有的unit_result、当前U及转换对象；失败路径在finally同样释放。日阶段调用方用同一个try/finally包住下载、verify和publish，不能只清局部result却继续让VerifiedDaySource持有它，或带着它进入历史阶段。日发布函数只返回§5.4的文件/计数/摘要事实，不在发布结果、进度闭包或阶段记录中夹带UnitResult/行集合。原始tuple、当前转换列和DuckDB关系的同时存活须计入§10，不额外复制一份完整Python行列表。失败阶段不触发业务源自动重试；下次新执行全新下载。

#### 5.4.2 摘要投影

复用现有`contract_registry.content_digest`；业务调用为`content_digest({"record_kind":kind,"record_version":1,"value":projection})`。日期先为ISO文本；DOUBLE因子为有限float.hex()，数值0统一0.0.hex()；投影不直接含float/date/Decimal。1、1.0、1.00归一化后相同，不引入容差。源contract_digest仍直接采用组件原算法。

| 摘要 / kind | 精确投影 |
| --- | --- |
| history_ranges_digest / stk_factor_pro.history_ranges | 按代码/起止排序的`[{ts_code,start_date,end_date}]`；未知范围保留null行，不删原完整名单对象。 |
| history_plan_digest / stk_factor_pro.history_plan | T/P、ContractIdentity、history_ranges_digest及按code排序entries；每项code、t_present/p_present、t_value_hex/p_value_hex、plan_reasons、去重升序origin_target_dates、earliest_basis(kind/date)。 |
| unit_key / stk_factor_pro.unit | 单个UnitProjection，固定字段mode/object_code/point/start_date/end_date；mode为整数，日期先转ISO文本，null显式保留。精确公式为content_digest({"record_kind":"stk_factor_pro.unit","record_version":1,"value":projection})，不含run、ordinal、文件路径或20日批号。 |
| scope_digest / stk_factor_pro.scope | phase、T及排序units；UnitProjection固定`mode:int,object_code:str|null,point:Date|null,start_date:Date|null,end_date:Date|null`。day只有mode2/point=T，history按§5.1.2取已判明、尚需本次新下载的完整请求范围，每code一项mode5/start/end；已证明独立成功及原因6对象保留在完整plan中但不进入本次units，不能按实际返回几只再缩请求范围。 |
| history_input_digest / stk_factor_pro.history_input | T/P、ContractIdentity、scope_digest及该完整请求范围内按code排序的权威t_value_hex/p_value_hex。不含范围外股票或整份因子文件sha。 |
| day_source_digest / stk_factor_pro.day_source | 仅日阶段：ContractIdentity、scope_digest、当前单unit的UnitProjection、source_row_count=len(records)、完整U的row_count、schema_content_digest及§8.1算法计算的Raw表示content_sha256；不含文件路径、manifest、run或时间。由当前内存U计算，不生成日下载完整记录文件。 |
| files_manifest_digest / stk_factor_pro.source_files | 仅历史阶段：scope_digest及按unit_key排序的unit业务投影、源/保存行数、file_sha256/file_rows/schema_content_digest。不含当前路径/run/时间。 |
| schema_content_digest / stk_factor_pro.local_schema | 契约字段顺序的`[{name,type}]`，本地类型只VARCHAR/DATE/DOUBLE，不取DataFrame dtype展示文本。 |

上述业务摘要不含run_id、追溯路径、slot/提交序号、诊断、完整因子文件sha或20日批次参数。每个RecordRef另外核文件字节sha；业务摘要不能代替文件读回。unit_key为UnitProjection的同一规范摘要，不能用ordinal/run作身份。plan和ranges写成后不可原地修改；同T新run输入未变沿原revision，变更则原revision+1，首次1；处理中输入再变停止，不改已被引用的计划。

业务内容摘要用于本次候选/正式文件等价比较、成功结果核对及bootstrap片段校验，算法见§8.1。失败run的源及候选不得作为新run的业务输入。

#### 5.4.3 各现有文件

**history-plan.json**：`record_version,identity:RunIdentity,contract:ContractIdentity,revision:int>=1,created_at:Instant,history_plan_digest,history_ranges_digest,ranges_ref:RecordRef,full_code_count:Count,factor_t_ref:FactorFileRef,factor_p_ref:FactorFileRef,revision_of:RecordRef|null,origin_plan_ref:RecordRef|null,origin_history_plan_digest:Digest|null,origin_history_ranges_digest:Digest|null`。

FactorFileRef固定`trade_date:Date,asset_key:str=raw_tushare_adj_factor,file_sha256:Digest,rows:Count`；路径按正式paths复算。自动首次origin三项null，repair全有。repair始终保留原完整授权引用，不把本次新权威值摘要替换原授权。full_code_count等于ranges唯一代码数。

**history-ranges.parquet**：`ts_code VARCHAR NOT NULL,t_present BOOLEAN NOT NULL,p_present BOOLEAN NOT NULL,t_value DOUBLE NULL,p_value DOUBLE NULL,start_date DATE NULL,end_date DATE NULL,plan_reasons INTEGER[] NOT NULL,origin_target_dates DATE[] NOT NULL,origin_record_refs VARCHAR NOT NULL,earliest_basis_kind INTEGER NULL,earliest_basis_date DATE NULL`。唯一键ts_code；origin_record_refs是固定字段T/run/relative_path/file_sha的规范JSON数组，仅追溯。present=false必须value=NULL；有效历史请求因子/范围必须已判明、start<=end、end=T；范围未知不猜起点。earliest_basis_kind只1=可信现有最早日期、2=已批准bootstrap事实。缺关键因子/范围保留未判定并明确停止对应历史，不用技术行相等作门槛。

**history-eligibility.json**：`record_version,identity:RunIdentity,history_plan_digest,history_ranges_digest,raw_coverage:StkFactorProRawCoverage,target_silver:StkFactorProTargetSilver|null,evaluated_at:Instant`。覆盖结构及完整缺失清单引用见§5.2.1；原T Silver有效性独立保存，未执行该步为null，不把Raw齐备改写成Silver有效。技术因子同名adj_factor差异另放原诊断摘要，不参与放行。

**source/history/source-files.parquet**：`phase VARCHAR,unit_key VARCHAR,component_unit_id VARCHAR,ordinal BIGINT,mode INTEGER,object_code VARCHAR NULL,point DATE NULL,start_date DATE NULL,end_date DATE NULL,source_row_count BIGINT,saved_row_count BIGINT,file_relative_path VARCHAR,file_sha256 VARCHAR,file_rows BIGINT,schema_content_digest VARCHAR,contract_content_digest VARCHAR,verified_at TIMESTAMPTZ`，除明确NULL列外均NOT NULL。phase只能history，唯一键(phase,unit_key)，每完整历史unit一个261列文件（合法0行也保存明确schema文件）。mode5/code/start/end全有且end=T，point=null。ordinal仅当前任务内序号；component_unit_id保留组件原值。statistics.row_count==len(records)==saved_row_count==file_rows；逐项字段/范围/身份必须对应，不能只比unit数。日阶段无该文件及引用。每个unit源文件固定为当前run下`source/history/units/<unit_key>.parquet`，manifest的file_relative_path从当前run根表达为同一路径；合法0行也写完整schema文件。只由unit_key函数生成文件名，写前核safe_path和source/history归属、拒绝已有文件，不能套用仅允许candidates目录的检查或放宽候选目录规则。

**source/history/source-complete.json**：`record_version,identity:RunIdentity,phase:Literal["history"],contract:ContractIdentity,history_plan_ref:RecordRef,history_plan_digest,history_plan_revision:int,origin_history_plan_digest:Digest|null,origin_history_ranges_digest:Digest|null,history_input_digest:Digest,scope_digest:Digest,expected_units:list[UnitProjection],files_manifest_ref:RecordRef,files_manifest_digest:Digest,completed_unit_count:Count,verified_at:Instant`。历史input必填；repair原授权非null。仅在§6全部历史会话正常退出、最终summary通过后，全部expected_units与manifest身份/计数/读回一一对应，且全部属于当前run才写成。空历史名单直接跳过，不伪造下载完成。任何新run都不得以此省去失败任务的重下载。不存在日阶段source-complete。

**publication/<phase>/<d>/<layer>/intent.json及complete.json**：同一当前run固定结构`record_version,identity,phase,trade_date:Date,layer,contract,scope_digest,history_input_digest:Digest|null,day_source_digest:Digest|null,source_manifest_digest:Digest|null,target_path:str,candidate_relative_path:str,prior_sha256:Digest|null,candidate_sha256:Digest,candidate_rows:Count,expected_published_sha256:Digest,mode:Literal["reuse","replace"],stage:Literal["intent","complete"],unrefreshed_keys_ref:RecordRef|null,unrefreshed_count:Count|null,verified_at:Instant|null,actual_sha256:Digest|null,actual_rows:Count|null`。day必须day_source_digest非空、source_manifest_digest及history_input_digest为null；history反过来，day_source_digest为null、两项历史摘要必填。day候选固定candidates/day/<layer>/data.parquet，history候选固定candidates/history/<d>/<layer>/data.parquet；历史缺原键附件固定publication/history/<d>/<layer>/unrefreshed-keys.parquet。路径都相对当前run，d必须小于原T；日分支仍只能T，不改变既有日候选路径。target按T/d/layer复算并核对；prior仅当前候选构建时的正式文件sha，缺文件为null。reuse指当前正式内容已与**本次新下载生成的候选**等价、无需replace，不指旧源复用；其expected=prior，replace的expected=candidate。intent末三项null、complete全有；历史缺原键引用/计数全有（0行差集也明确），日二者null。

**publication/<phase>/publication-complete.json**：`record_version,identity,phase,contract,history_plan_digest,history_ranges_digest,scope_digest,history_input_digest:Digest|null,source_complete_ref:RecordRef|null,day_source_digest:Digest|null,source_manifest_digest:Digest|null,targets:list[PublishedTarget],verified_at:Instant`。day的source_complete_ref、source_manifest_digest、history_input_digest均为null，day_source_digest必填且来自本次内存U；history的上述三项必填、day_source_digest为null。不能为满足结构而生成日下载文件或虚构其引用。PublishedTarget固定`trade_date:Date,layer,skip_no_file:bool,file_sha256:Digest|null,file_rows:Count,checkpoint_ref:RecordRef|null,unrefreshed_count:Count,scope_rows:Count|null,scope_content_sha256:Digest|null,scope_content_version:int|null`；无旧无源日期明确skip=true、hash/ref=null/数量0，不假物化；有文件则skip=false、hash/ref齐全。历史scope三项全有，记录该完整成功范围在本日期/层的行数、业务内容摘要及版本1，空范围为0及空串SHA；day三项全null。全部预期日期/层去重升序无遗漏，历史所有unrefreshed_count=0才可完整。正式完成后还须同producer run最终成功才可成为后续正常轮次的历史免重刷依据。失败run即使此文件存在也不能复用其源/候选或部分checkpoint跳过重下载。

后续同T正常轮次通过§6.2直接读取**原来独立成功的整个范围**的DG阶段记录、原完整授权和publication-complete引用。原T、全部代码/起止、对应权威T/P及契约/处理版本匹配，且DG没有后来使该范围失效的发布事实时，直接复用成功结论，不让sensor逐文件扫描历史、重新做全范围字段对账。新全名单新增无关股票不推翻原范围成功，不能以新旧全名单摘要不同要求全量重刷。

正式写入均通过本数据集受控发布并记录影响日期/代码及文件身份；日更和repair已经保证唯一写入。人工外部修改须按维护流程撤销相应完成依据、处理后重新验收，不能一边绕过管理直接改文件，一边承诺PG旧结果始终有效。job确知原成功范围的文件被后续发布改动时，仅对受影响日期按该范围筛正式行、核scope_rows/scope_content_sha256；不影响的结果直接复用，不在每次sensor评估做物理全历史核验。失败run绝不进入成功复用判断，不读取其旧下载Parquet，也不按页/股票/日期领取失败任务的部分成果。

#### 5.4.4 小样本门禁

必须用独立字面样本证明：换run/路径不改业务输入摘要，改code/边界/权威值必须变；未知范围null不可删；历史source记录错run拒绝；日0行合法完整unit只留内存、历史0行完整unit可保存，缺列/计数不符拒绝；所有record必填/类型/未知字段校验生效。日阶段不得创建source/day、日source-files/source-complete或另一份日源Parquet；完整UnitResult须在with退出后仍可转成本次U，最终summary不成功则Raw候选及正式提升均0。day/history来源摘要与引用的互斥条件必须有反向测试。失败run即使历史source-complete及全部候选存在，新run仍有实际新网络请求，测试必须让旧Parquet一旦被当新输入读取就失败，不能只检查配置flag。bootstrap使用自身独立合同，不套本节失败重下规则。

## 6. 下载契约、线程、进度、错误与取消

完整契约名`stk_factor_pro`，独立version，不加来源前缀或`@1`。完整261业务字段含ts_code/trade_date及259数值；本地辅助列不进入接口fields。普通单日`DownloadTask(..., mode=DownloadMode.BY_POINT, points=(T.isoformat(),))`，历史`BY_OBJECT_RANGE`；代码扇开在组件内，业务规划范围/窗口。相同代码多窗口分次任务，同任务重复object_code被1102拒绝。

本文T、起止日期为本地`datetime.date`；进入组件前显式转为ISO字符串。历史统一使用`TimeRange(start.isoformat(), end.isoformat())`；各股范围不同则`ObjectTimeRange(code, TimeRange(start.isoformat(), end.isoformat()))`，不得把date直接传入组件。写本地unit记录时，组件scope中的ISO文本按本地Date合同显式解析，不把HTTP源行的YYYYMMDD与scope日期混用。`component_unit_id=result.unit.unit_id`，`ContractIdentity.contract_content_digest=result.unit.content_digest`；不按本地记录字段名猜组件属性。

分页暂定limit10000、offset从0步进10000、短页/空页结束、满页继续；属于源契约，不让业务传fields/limit/offset/token/地址。第一批已验证一股五日的小页offset和固定HTTP，真实10000满页边界仍未验证；不得将二者混同。每unit全部页取全后交业务一次。日阶段只留当前一个完整unit；历史必要校验、当前unit落盘/读回后释放，不积累全历史内存。

日下载固定一个BY_POINT任务、一个T、一个unit。with内只接收并保留该UnitResult，不建日下载文件，不创建Raw发布候选；若收到第二个unit立即失败。须正常消费至StopIteration并成功退出with，之后取得`summary=session.summary`。精确要求`summary.status == DownloadStatus.SUCCEEDED`、download_complete为True、total_units/completed_units/delivered_units均为1，summary.row_count/completed_row_count均与唯一unit统计及len(records)相等；然后强制check_cancel，再调用§5.4.1的verify函数构造当前内存U及VerifiedDaySource，交日发布函数。session退出、summary校验或此取消检查失败时直接释放结果，本次不得构造Raw候选或提升。不要在with内先写源、先提升、再等关闭结果。

历史仍采用with内逐完整UnitResult校验、保存历史源片段并读回；正常退出with后核最终summary。每个历史DownloadTask须同样SUCCEEDED、download_complete为True，total/completed/delivered均等于该任务规划unit数，summary两项行数等于该任务manifest行数之和。多窗口分次调用逐session核各自子范围；只有全部历史任务成功关闭、manifest完整覆盖expected_units且行数/身份读回一致，才保存`source/history/source-complete.json`并进入历史合并/提升。空历史名单直接跳过，不创建零unit下载任务。

session关闭可能在全部unit交付后抛1304，或最终为STOPPED/CANCELLED/FAILED；日分支释放当前内存、不构造Raw候选，历史分支不写source-complete，两者均不进入正式发布。已有历史staging仅保留证据。UNIT_COMPLETED/100%或download_complete单独为True不能放行。组件最后一个unit完成回调取消但最终SUCCEEDED的既有行为仍按上述最终summary判断，不自行改组件取消语义。

`TushareDownloader.load()`和`with downloader.download(...) as session`沿用现接口；创建、使用、回调、关闭同线程。DG执行进程直接在执行线程调用，页面业务另开下载线程；跨线程/进程通信由业务接入层负责。组件不创建线程/子进程、锁、额度或全机限频，连接配置直接复用现有读取方法。

PAGE_COMPLETED/RETRY_SCHEDULED/UNIT_COMPLETED只传摘要，业务不在通知中写数据。UNIT_COMPLETED在交付前，100%不等于保存、日发布或历史全完。普通观察回调异常由组件隔离；业务校验/保存异常停止消费并关闭session，不交给组件重试业务写入。

组件错误码保持现有1001配置、1101契约、1102输入、1201权限/参数、1202限频、1203临时源、1204无有效响应、1205协议、1302容量、1304清理/关闭、1401取消、1501未分类源错误。业务原因集中登记，不随意扩展组件错误码。组件同页有限重试不消耗新的前日机会；一次已开始的前日日阶段失败且不能证明已齐，或仍缺/未知，则当天不自动补第二次或推进今天；仅历史失败而Q日阶段已齐不阻止今天。今天的临时源错误可等后续计划时点，永久输入/契约/权限、业务结构或目标冲突先报告停下，不盲重试。

分页/退避取消不交付半unit；完成通知时取消仍交完整当前unit再停，末unit可正常下载完成。业务取消后不领下一unit或提升新文件；replace前检查取消，当前文件一旦已经替换则尽力完成本文件fsync/读回/checkpoint后停止下一文件，失败保留intent排障，新run仍重新下载，不回滚已发布内容。网络可能等返回/超时，不强杀线程。with/finally关闭资源，已发布文件保留；午夜允许已运行任务结束，不模拟用户取消。历史前输入或Raw覆盖变了则停历史并留待处理，不能额外自动启动新任务或把它写成全部完成。

取消适配固定在`defs/io/stk_factor_pro_download.py`，日更和repair共用，不直接把现有moneyflow的`_check_cancel(context)`传给组件：该函数返回None/抛错，而组件`DownloadControl.is_cancelled`要求精确bool。

```python
def build_stk_factor_pro_run_control(
    instance: dg.DagsterInstance, *, identity: RunIdentity,
    phase: Literal["day", "history"], monotonic: Callable[[], float],
) -> tuple[DownloadControl, Callable[[], None]]: ...
```

返回第一个对象传给`downloader.download(control=...)`，第二个`check_cancel`交源保存、候选及发布函数。内部用同线程闭包保存最近一次已核run状态及monotonic时刻：首次必须`get_run_by_id(identity.creator_run_id)`，之后组件的普通取消检查至多每1秒读一次，其余调用只读该局部值；已确认取消永远保持True。`check_cancel`在每个业务unit保存前后、历史合并批前、每文件replace前强制刷新，不受1秒复用限制，取消即抛`dg.Failure(..., allow_retries=False)`并按§6.1记录当前phase及retryable=False。不为每行/每个数值/排序比较查询PG；同一阶段所有下载session和发布步骤复用这对对象，不每页重建。

run_id必须等于当前执行身份；CANCELING/CANCELED返回True，STARTING/STARTED返回False。查不到run、读状态异常或执行中出现其他不匹配状态，直接报业务状态读取错误并停止，不能返回False，也不映射成源端临时错误重试。组件`SessionControl`对控制函数异常直接传播，该适配不放到可吞普通异常的进度回调中；Dagster原生中断同样沿with/finally清理，不吞中断、不强行改成下载成功。只在已有请求/排序/退避等取消检查点读取，不增加后台线程、锁、IPC或定时任务；网络仍可能等当前调用返回/超时。1秒只控制取消状态读取成本，不承诺1秒内终止网络调用。

### 6.1 失败结果如何决定下一轮，以及管理员修复后如何解除

单个失败的结果写入现有`dg.Failure(metadata=...)`，最外层按`precheck/day/history`记录发生阶段；历史抛错前仍保留真实日发布事实。未知异常只记安全摘要，不把token、响应全文或连接串写入metadata。

| 失败metadata键 | 类型/取值 | 消费者 |
| --- | --- | --- |
| `goldenshare/retryable` | bool | sensor判断是否可在**后续新slot**继续；不是组件同页重试开关。 |
| `goldenshare/failure_phase` | str，仅precheck/day/history | 分清Q日阶段未完和仅历史失败，不能按run FAILURE一刀切。 |
| `goldenshare/target_trade_date` | ISO日期str | 与run_config、分区及原T交叉核对。 |
| `goldenshare/source_error_code` | 可空int | 原样保留组件已有错误码；业务错误为None，不冒充组件错误。 |
| `goldenshare/summary`、`goldenshare/next_action` | 非空str | 中文说明哪一步失败、保留了什么、下一步如何处理。 |

业务失败只在本数据集run_contracts集中使用有限类别：输入/契约、字段或数据、目标冲突、本地读写、取消、未分类；类别用于定位，不另造一套公共错误编号。类型、异常映射和本节允许的阶段在同模块集中校验；禁止用自由异常文本决定是否重试。

| 实际结果 | retryable | 后续安排 |
| --- | --- | --- |
| §4.0.1完整请求成功但0行、无可用旧日数据、已知应有股票非空 | true，failure_phase=day、source_error_code=None | 先保存真实缺失/阶段事实，bootstrap关联时先更新原统计，再主动Failure且allow_retries=False。今天下一允许slot重新下载；Q机会已耗且不推进今天；人工补数由管理员再次执行。不造文件、物化或绿check。 |
| 组件1202/1203/1204在有限同页尝试后仍失败 | true | 今天可以等下一固定slot；前日已开始仍受一次规则，不能再发。 |
| 历史请求正常完成但原范围仍有旧键未刷新 | true，failure_phase=history、source_error_code=None | 保存完整原未完成范围及缺失清单，yield历史waiting后抛Failure，run为FAILURE。今天自动sensor下一允许slot重新下载整个范围；Q已用机会不自动第二次，日已齐时仍可推进今天。手动repair同样失败，但不由sensor自动新建repair。 |
| 1001/1101/1102/1201/1205/1302/1304/1501，或字段结构/日期/主键错误、目标冲突、本地读写失败、未知异常 | false | 停止对应T/阶段的自动重试，等待管理员；不拿换slot或清cursor当作解除。容量或磁盘问题不靠重新下载解决。 |
| 1401或业务取消 | false | 保留已提交事实，不自动取消后重发。 |
| 上游未就绪且明确PRECHECK_NO_DOWNLOAD | 不写失败标识 | 按§3.4等待后续未用slot，不消耗前日机会。 |
| 已有有效日数据的合法部分发布、原T Raw覆盖不足或停牌输入未知等非执行异常 | 不伪造STEP_FAILURE | 保留覆盖/历史待处理；按已确认规则继续或等待，不增加blocking check。§4.0.1无可用日数据的明确业务失败单独处理，不能将4000/5000也改成Failure。 |

`read_stk_factor_pro_failure(instance, run_id)`仅对已验证本数据集run调用`event_log_storage.get_records_for_run(run_id, of_type=STEP_FAILURE, limit=1, ascending=False)`，从`step_failure_data.user_failure_data.metadata`读取上述字段，严格检查类型和目标身份。缺记录、缺retryable、错类型、run异常退出或取消但原因未知均按不可自动重试处理，不默认true。直接参考现有`moneyflow_failure_retryable()`的读取方法，不改资金流代码。

更新sensor选择T后先调用§6.2读取同T阶段结果。自动机会查询固定get_run_records(RunsFilter(job_name=update_job, tags={PARTITION_NAME_TAG:T.isoformat(), SENSOR_NAME_TAG:update_sensor_name}, created_after=D零点, created_before=D+1零点), limit=11, order_by="create_timestamp", ascending=False)，update_sensor_name为§2.1固定名。逐条按八字段解析并仅统计自动用途，额外bootstrap字段必须None；原生人工重新执行不增加自动机会。bootstrap人工run不带sensor身份，不挤占11条；标签不能单独授权。此查询不代替看全部活动/最新同T任务，后两者不能加sensor过滤。失败解除沿精确run引用读取，不到新D就忘旧T失败或扫描全史。

每个实际经过的阶段以`AssetObservation(asset_key=Raw, partition=T, metadata=...)`保存固定摘要：`phase_result_version=1, target_trade_date, phase, result(completed/waiting/no_action), producer_run_id, recovery_of_run_id|null, unresolved_failure_run_id|null, day_source_digest|null, source_complete_digest|null, publication_complete_digest|null, history_plan_ref:RecordRef|null, history_ranges_ref:RecordRef|null, raw_coverage:StkFactorProRawCoverage|null, target_silver:StkFactorProTargetSilver|null, bootstrap_context:StkFactorProBootstrapContext|null, bootstrap_coverage_refs:tuple[tuple[Date,str,Digest],...], bootstrap_summary_ref:{relative_path:str,file_sha256:Digest}|null, prior_day_result:{run_id,storage_id}|null, prior_history_result:{run_id,storage_id}|null`。字段全有，可空值显式null；record_version/日期/计数按§5.4，storage_id是正精确int。bootstrap_context按§10.5.6核验，无bootstrap关联时为null，不因此获得首次补数入口权限。日阶段source_complete_digest始终null，day_source_digest仅在本次会话及当前U通过后填写；它是摘要，不包含日下载行或日下载文件引用。历史day_source_digest始终null、完整源形成后才填source_complete_digest。日阶段观察保存本run完整计划引用和实际覆盖结果；repair观察保留原授权及当前原T覆盖。失败未形成新计划时引用为null并说明失败阶段，不能伪造计划。

target_silver字段在尚未核原T Silver时为null，核过则完整保存§5.2.3结果；历史completed必须ready=True，失败则保存实际false及原因。raw_coverage仍只表达股票覆盖，Raw齐但Silver坏时保持complete=True，不能改写成股票缺失。完整缺失清单的引用随raw_coverage同时存入PG和eligibility；清单明细不是日下载数据。

bootstrap_coverage_refs保存本阶段实际已更新日期的(date,operation相对result路径,文件字节SHA)，升序唯一；bootstrap_summary_ref只保存本次确已刷新并读回的summary相对路径/SHA，未完成为None。无Context时前者为空tuple、后者None。有Context时路径必须在该operation固定coverage目录、无..或符号链接越界，不能套用指向run目录的RecordRef；不要把记录了一个路径当成写入已成功。每日/历史批次收尾把真实值写入阶段观察，历史失败仍保留已完成日引用。

未执行或等待不能写completed，未解除失败及此前独立成功范围沿已验证引用继续保存；新日发布不清除旧历史失败。`prior_day_result`和`prior_history_result`仅指已持久化的同T相应阶段观察，沿用同一run结果时可为null；它们让下一run直接定位既有PG事实，不扫描staging。自动资产及out={}的repair op均用同步生成器yield观察；历史未刷新全范围时，**先yield waiting，恢复执行后再抛Failure**。禁止`context.log_event()`后立即抛错而把尚未持久化的观察丢在缓冲中。没有完成历史不能写publication-complete。

Q与今天各自判断。day/precheck的永久失败阻止对应T的自动job；history永久失败只停止该T历史自动重试：日数据仍缺时可以按正常slot更新日阶段，但历史步骤保留失败引用并跳过请求，日已齐且输入未变时不为该历史失败反复启动job。Q日已齐且仅history失败仍可选今天；原Q历史交原T手动repair，不扩成全数据集永久停止。临时历史失败可在今天后续slot按原完整scope规则重试；Q一次限制不变。

本节永久失败禁发规则仅由自动sensor使用；管理员明确重新执行原任务，核原身份、§2.4人工时间例外和唯一写入条件后，可以实际进入原失败阶段。不能在人工入口先套sensor的“未解除永久失败”分支，否则管理员永远无法取得用来解除的成功事实。

管理员解除不写“已修复=true”或清cursor。真实成功阶段观察保存recovery_of_run_id：普通重新执行取已核parent/root，历史repair取配置source_run_id；无parent的新bootstrap授权run可从§6.2已有结果选同operation/同T/同阶段的明确未解除失败引用，精确核身份后使用，不另加输入。只有该阶段真实完成才解除，不因SUCCESS但未执行/waiting而解除；日解除不要求股票全齐，历史解除要求原T齐及完整历史范围成功。其他T/operation不可解除，Q机会不恢复，repair不解除日失败，日成功不抹历史失败。

测试分别覆盖1201后下一slot零提交、1203允许今天下轮、缺失败metadata保守停、日已齐历史失败仍推进今天、人工无操作SUCCESS不解除、真正修复仅解除原T/阶段、清cursor无效、解除后Q机会不重获。上述测试必须经过实际失败metadata读取分支，不能只测试错误码分类。

### 6.2 直接读取DG已有结果

实现仅在既定`defs/asset_guards/stk_factor_pro_readiness.py`集中查询，引用`run_contracts/stk_factor_pro.py`固定类型；不增加表、状态资产或独立审计流程，不修改现行readiness及其存量消费者。DG保存run配置/状态/parent/root、物化及绑定物化的check，本数据集将股票覆盖和历史完成另存为上述小型阶段观察，业务直接读取这些现有记录。单独run SUCCESS不代替股票覆盖或历史完成；失败run中已经通过的日文件检查仍可使用。

接口固定read_stk_factor_pro_recorded_results(instance, *, target_trade_date:date, exclude_run_id:str|None=None)->StkFactorProRecordedResults。结果是frozen dataclass，字段target_trade_date、day_result_ref/history_result_ref（{run_id,storage_id}|None）、history_plan_ref/history_ranges_ref（RecordRef|None）、raw_coverage（StkFactorProRawCoverage|None）、bootstrap_context（StkFactorProBootstrapContext|None）、pending_plan_refs/successful_publication_refs（tuple[RecordRef,...]）、unresolved_day_failure_run_id/unresolved_history_failure_run_id（str|None）。显式返回经核bootstrap上下文供重新执行/repair继承，不能只保存却漏读。普通两用途Context为None，bootstrap及继承它的repair核§10.7首次授权；同T有多operation时按原run引用核，不混为同一授权。只返回意图/凭据，无下载行或旧候选。

此reader只核PG内Context结构、原run配置和真实开始授权观察；operation批准/当前缺口文件及本地依据由asset/op调用bootstrap resolver完成，readiness不import bootstrap。共享类型从run_contracts读，不通过bootstrap模块转发，避免身份解析与纯覆盖形成反向依赖。

固定读取方式：

```python
records = instance.fetch_observations(
    dg.AssetRecordsFilter(
        asset_key=dg.AssetKey("raw_tushare_stk_factor_pro"),
        asset_partitions=[target_trade_date.isoformat()],
    ),
    limit=16,
    ascending=False,
).records
```

1. 按观察storage_id倒序查本T的阶段结果，核版本/字段类型、记录本身run_id与producer_run_id一致；用`get_run_by_id()`精确核属于既定日更或repair job及配置原T。repair是无分区op job，但观察有显式partition=T，因此可自然发现，不为查询额外写系统分区tag。自动日更原生partition与配置仍需对应。当前run按exclude_run_id排除，不能从尚未完成的自身记录推导旧成功。
   同时查本T最新日更run，固定get_run_records(RunsFilter(job_name=update_job,tags={PARTITION_NAME_TAG:T.isoformat()}),limit=2,ascending=False)，不加sensor或purpose过滤；自动机会查询因已过滤人工，不能据此断言已取得全部用途的最新run。按原生storage_id排除自身取最新其他run，识别三用途，避免人工补数首条观察前退出被旧绿色掩盖。最新失败/取消无可解释事实时自动保守停止，不重审文件；§2.4原生重执行或§10.7已核bootstrap新授权不被此自动停止规则阻止，但只按真实阶段完成解除失败。
2. 最新阶段记录已经保存所需引用时直接使用；只有另一阶段/原未完/恢复关系需要核实，才沿上述prior/plan引用精确读取。已知run观察使用`get_records_for_run(..., of_type=ASSET_OBSERVATION, limit=16, ascending=False)`，按引用的storage_id匹配，核同资产/同T/阶段，producer最终状态由run记录读取。每个run同一调用只读一次；一次最多精确读取11个不同引用run，遇循环、缺引用、超界或读不到事实停止并说明，不扩大为全实例扫描。首次无旧记录可从当前T/P新建名单；不能把“存在引用但读不到”当首次无记录。
3. repair完成观察与原失败引用一致、producer SUCCESS且完整范围完成时，直接解除原历史失败并保留成功范围。正常新轮无parent也能发现；仅成功的其他独立范围可省历史重下。失败producer的下载/候选/物理部分完成记录永不成为免下载依据。文件失效处理按§5.2、§5.4，不因读取成功事实就重复审计全部历史。
4. 这是元数据读取，不做Raw/Silver全字段SQL、不读完整历史或联网。覆盖引用与当前Raw/生命周期/最终停牌/身份映射一致则使用，只在必要输入变更时重比原T代码；同次局部缓存复用，无跨进程缓存或新存储。授权读取按§10.7至多三条精确run，业务阶段引用仍沿本节11条上界，两类读取共享同次已取得记录。

临时instance回归至少证明：无分区repair产生partition=T观察可被此查询找到；repair成功解除旧失败；少股票SUCCESS不被读成覆盖已齐；日成功历史失败仍保留日完成；原计划未形成的新日更能重建；旧下载路径一旦被读取作新源即测试失败；记录未变时全字段/全历史重审函数调用次数为0；引用损坏不假装首次运行。

## 7. 失败后一律重新下载，以及前日一次边界

以下规则适用Tushare技术因子日更新和历史repair；不修改组件运行中的同页有限重试，也不改变Prod bootstrap独立恢复办法。

| 场景 | 新执行的固定行为 |
| --- | --- |
| 日unit未完整，或内存结果完整后校验/候选/Raw/Silver发布失败 | 重新下载原T完整日unit，不读旧下载结果或待发布候选；与当前正式Raw合并，再生成Silver。不创建日下载中间文件。 |
| 日阶段成功、历史下载失败 | 正式日文件保留；获准重执行自动job仍重新下载原T日源，Raw齐备且日阶段通过后，完整原失败历史范围全新下载。使用手动repair则不下载日源，只在原T Raw齐备、原T Silver有效且对应当前Raw后重新下载完整原失败历史。 |
| 历史源完整但任何后处理失败，或只有部分历史文件已发布 | 完整原失败历史范围重新下载；不按已完成页/股/日期续接，也不因source-complete存在省网络。正式已发布文件留作新合并基础，不能删除或回滚。 |
| 历史全部物理发布、最后事件或收尾导致run失败/取消/异常退出 | 仍按失败任务处理，下次重新下载原失败历史范围，不以局部或全部物理完成记录绕过本规则。 |
| 原目标T Raw缺失、不齐或覆盖未知 | 自动job保留已取得日数据，历史等待；manual repair直接报“原日期数据缺失”，不请求技术因子、不更新T、不提升历史。 |
| 已有历史整范围成功且业务输入仍匹配 | 正常后续同T轮次无需无故重复回刷；必须有完整范围成功事实与producer最终成功，不能使用失败任务记录冒充。 |
| 当前run在单文件replace后收到取消/读回失败 | 尽力记录当前文件真实状态后终止，不领下一文件；下一run仍新下载，不继续使用本run旧候选。 |
| 前日Q已实际使用机会后失败或仍缺 | 不自动补第二次、不推进今天；明确人工重执行不恢复自动机会。Q日已齐且只历史失败，按既定规则可推进今天，原Q历史人工repair。 |

失败候选不作为新执行输入；记录并保留的是历史回刷的股票代码/起止日期、失败原因与发布证据，不是当日数据下载中间文件或待续传位置，正式数据不丢弃。日新run只用本次内存结果，历史新run只用自己重新下载和验证过的源，构建候选并与当前正式文件按主键合并。隐式自动重试业务写入仍禁止。

## 8. 合并与逐文件发布

Raw正式路径`/Volumes/datasource/data_lake/raw/tushare/stk_factor_pro/trade_date=<d>/data.parquet`，Silver为`/Volumes/datasource/data_lake/silver/stock_factor_pro/trade_date=<d>/data.parquet`；本run候选仅正式staging根。没有旧Lake、Kopia、备份或跨文件快照。

### 8.0 日数据与历史的Raw/Silver顺序

1. 日T：当前run新下载完整日unit仅保留内存→session正常退出并核summary→先判断§4.0.1无可用日数据分支；适用时先保存缺口/必要统计再主动业务Failure，不构造文件或历史。其余有可发布结果的分支，由本次内存U与当前合法Raw直接构造唯一Raw发布候选→校验/发布/读回Raw T→从这份完整Raw仅转换日期生成Silver T候选→校验/发布/读回Silver T→释放本次unit/U。不存在日源Parquet、日manifest或日source-complete。旧未返回行保留；首次合法空不造文件，已有文件不清空。“完整Raw”只指该日期合并结果，不表示全市场齐或全历史完。
2. 两层日阶段完成后核§5.2的原T Raw覆盖；不足或未知时本轮历史零请求、零提升，保留完整名单等待补齐。Raw/Silver已经有效发布的日数据可供业务读取，不被历史门槛撤销。
3. 原T Raw齐备、权威T/P及完整待处理范围确认后，下载该范围的全部历史unit；全部在当前run保存/读回才进入历史合并。
4. 历史按日期d<T逐个Raw合并/校验/发布/读回→从这份Raw生成Silver d并校验/发布/读回。两层都刷新；不等全部历史Raw发布后才开始Silver。完整历史响应中T原文保留，但正式T只归日阶段写，不由历史覆盖。

每日期合并以当前正式B与当前新源唯一键U为输入，交集K，目标行数B-K+U；未返回旧键保留，重复键/非法日期拒绝而不去重掩盖。例旧4000、本轮4800且漏回旧50，最终4850；数字不是门槛。Raw源日期字符串，Silver DATE，259数值/代码/合法NULL与负数保持对应；额外合法来源行不按覆盖集合过滤。

### 8.1 当前run的候选、提升意图和逐文件记录

复用现有连接与发布算法，不直接带入moneyflow字段、阈值或锁。所有输入来自当前run的新下载；本轮开始已按既定唯一写入/维护流程排除其他任务。对每个日期/层固定执行：

1. 读取并校验当前正式目标B，记录本次构建时整文件sha（无文件为null）。日Raw直接使用本次VerifiedDaySource中的内存U，历史Raw使用本run已完整落盘的历史源U；保留未更新股票，先完成§9的字段/主键/日期/全行对账。Silver始终从本日期已核验的正式Raw生成，不能再从下载结果独立合并。历史源缺原键以当前B的本范围键EXCEPT本run新U计算，保存当前run的unrefreshed-keys.parquet。
2. 候选fsync、读回并记录candidate_sha/行数；若与当前目标完整业务内容等价，mode=reuse且不重复replace，否则mode=replace。这里reuse是保留**当前正式文件**，不是复用失败下载数据。
3. 原子持久当前run intent（结构§5.4），包括本次prior/candidate/expected摘要、范围/合同/源身份；replace前再核正式目标仍等于prior，同文件系统、空间和取消检查通过才`os.replace()`。任何不明目标变化停止，不重登记实际hash绕过冲突。
4. fsync正式父目录、必要读回、写当前run complete，完成后才输出对应物化/check事件。即使状态/事件写失败也不撤销已经提交的业务文件；本run终止后，下次只重新下载和构建，不沿旧intent继续替换。
5. 当前文件replace后取消尽力完成该文件fsync/读回/checkpoint，停止下一文件。原intent保留用于说明已经发生什么，不成为新run使用旧候选的授权。

历史缺原键清单固定列`layer VARCHAR,ts_code VARCHAR,trade_date DATE`，每d/层独立，0缺也保存明确零行结果。缺旧键时有效新行仍可发布，旧键保留，不另加第三blocking check。所有本轮合法文件处理后汇总该差集；非零时不得写历史publication-complete，先yield历史waiting及完整原未完成范围/数量/清单，再抛`dg.Failure(..., allow_retries=False)`，`goldenshare/retryable=True`、`failure_phase=history`、`source_error_code=None`。run显示FAILURE，主提示`历史修复未完成：<T>；Raw/Silver合计<N>条记录未刷新。`。N按层统计物理记录，同股同日两层各缺1条时合计2条，不是缺2只股票。waiting只是业务未完成状态，不是run成功状态；纯发布迭代器只抛上述Failure，编排调用方捕获后先yield waiting再重新抛出，不在纯写入函数制造Dagster事件。

自动今天下一可用固定slot可重下原完整范围，仍核午夜、活动任务、因子与Raw齐备；自动补Q仍不增加第二次机会，Q日已齐仅历史失败不挡今天。手动repair失败后，由管理员查看缺失清单、修正问题并再次手动执行；sensor不会提交repair任务，job自身也不会循环重新执行。`allow_retries=False`禁止同run/op自动重试，与sensor下一slot创建新的自动日更run的retryable=True分别生效，不能混为一项开关。

完整业务内容等价/摘要沿现有ETF形式：261字段固定顺序struct_pack→to_json，按(ts_code,trade_date)升序换行string_agg→sha256，空集为sha256空串，数量另比。Raw和Silver使用各自日期schema，NULL真实编码，不填值或舍入；算法版本1。历史成功范围的scope_rows/scope_content_sha256只统计该范围各code的start_date<=d<=end_date且d<T的正式行，同日期多个范围以唯一代码/日期筛选、不重复计行；版本同为1。仅当前日期/层有界计算，用于本轮候选、已成功事实或bootstrap核验，不用于跨失败run续写旧源。

### 8.2 历史20交易日批次与整范围成功

**本节的本次完整请求范围精确取自已验证source-complete.expected_units；完整plan/ranges作为授权上界保留所有对象。**发布前将expected_units与manifest逐项核对，并确认均属于原授权，不用完整名单中的已成功/原因6对象扩大本次U或缺原键差集。

从完整请求范围和已核SSE日历生成d<T开市日期并集，去重升序，每20个交易日切批，尾批1～20日直接处理，不凑自然日。先核历史分区已批准登记，缺分区停止，repair不自动注册。无旧无源日期不造空文件/假物化，存在源则以空基础生成。

全部历史源保存并核source-complete后、首次历史提升前，使用同一DuckDB连接一次聚合当前源的日期及不属于批准股票/日期范围的行数：每条历史源行的代码和日期须属于其原unit及当前批准范围；其中d<T的所有源日期必须包含在上述已核SSE开市日期并集，且每个日期的本数据集分区已登记。日历缺日期/状态未知、已确认休市却有源行、或源日期未进入发布计划时直接失败，说明股票/日期及计数，历史提升0次；不能过滤这些行后宣称范围完整。源中的T行只作既定诊断保留，不进入d<T清单；请求范围外日期包括T之后的行在源适配阶段已拒绝。用聚合日期集合核对计划，不逐行发起日历或分区查询。

每批至多40个日期/层文件，同任务一个主要DuckDB连接做列式合并与校验；当前日期Raw→Silver完成后再处理后续日期，批内逐文件checkpoint，不是20日事务。当前run完整历史源先保存，不能边下载一股边改全年。批次大小/序号不进入源unit或业务输入身份。

只有当前完整范围所有必要文件/check/读回及原键刷新核对通过，才写publication-complete；producer run最终成功后才成为后续同T轮次可跳过历史的依据。失败后已完成19日、第20日失败也不能跨run领取前19日为下载断点：重取原失败完整范围，再与当前文件合并，已提交不回滚。成功的其他独立完整范围不混入本次失败范围。

bootstrap按§10独立合同恢复。

#### 8.2.1 完整历史先下载，再按20个交易日分批处理

本节是第三批历史处理的实现约束，代码及隔离验收见§16和[第三批记录](../../reports/stock_factor_pro_batch3_20261026/README.md)。“一轮完整下载”覆盖本轮原完整历史范围，可以包含多个股票unit、会话和分页；不能理解为只发一个HTTP请求。所有unit仍按股票及其完整日期范围组织，每个完整unit保存、读回、释放后继续下个；全部会话成功退出且§6最终summary、manifest和当前run源核验通过后，才允许开始本节。20日只用于本地合并，不把网络请求切成20日范围。

**调用位置与输入。**`publish_stk_factor_pro_history(...)`在调用方传入的同一个主要DuckDB连接上执行；输入使用本run已验证的完整历史源及manifest、原名单/范围、已核SSE日历和已登记分区。只从本run manifest取历史源文件清单，不扫描staging找文件，不读取失败run源；全部源范围/日期/分区检查按§8.2在首次提升前完成。普通候选仍受§15.9路径规则保护。`DAY_SOURCE`及日来源的`source.identity.target_trade_date`只服务日T；历史从本批表按处理日建立`HISTORY_DAY_SOURCE`，交§16.1同一Raw候选构造，不能把一股多年数据直接传给日入口。

**固定处理步骤。**

1. 从已核请求范围生成升序、去重的`d<T`开市日期清单，按`STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS=20`切批。每批保存当前日期tuple、批序号/总批数；尾批不足20日直接处理。日期清单与下载unit身份分开，批次不进入业务输入摘要。
2. 进入一批前检查取消，使用manifest列出的当前run历史源文件清单执行**一次批量源读取查询**：显式投影261个Raw字段，`hive_partitioning=false`，只取本批日期集合内的源行；源日期用已验证的`YYYYMMDD`字符串对应本批DATE日期。通过`CREATE TEMP TABLE ... AS SELECT ...`实际物化为当前连接的`stk_factor_pro_history_batch_source`，不使用会在逐日查询时重新读取Parquet的VIEW。不得在Python累计全部历史行，也不另COPY一份每批下载文件。
3. 对本批每个日期升序处理：从上述临时表按该日期筛出U，保留原股票代码和完整261字段；U只包含本轮需刷股票。读取当天当前正式Raw全市场B，按主键计算交集K，生成B−K+U并核对，保留其他股票和源未返旧键；历史缺原键另按§8.1保存差集。无旧且无源的日期沿既定skip规则，不造文件。
4. 对当天Raw候选做完整校验、安全提升、正式读回和complete记录，再输出该层真实结果。从这份已读回的正式Raw生成当天Silver，校验、提升、读回和记录后输出Silver结果。当前日期Raw→Silver完成后再进入下一日期，不先发布20天Raw再补20天Silver。复用§8.1/§9的合并与校验语义，扩展现有day-only记录时保留日分支的严格条件，不另造发布平台。
5. 每个日期结束即释放该日期旧B、U筛选关系、Raw/Silver expected及其他构造临时关系；本批源临时表保留给下一日期。批末在`finally`执行DROP，释放`stk_factor_pro_history_batch_source`及尚存的当日关系；下一批重新建立同名表。没有“所有批次完成后才统一释放”的路径，也不让跨日期VIEW持有即将被替换的正式文件。
6. 所有批次及原键刷新核对通过后，才按§5.4.3形成完整范围的publication-complete；来源run最终成功才成为后续免重复历史的依据。批次数量、已完成日期数或最后一批结束本身不能代替完整范围检查。

**读取、内存及写入成本。**设历史发布日期数为D、本轮历史源文件数为C，批数为`ceil(D/20)`。在既有完整源核验和发布前全范围校验之外，生成批源临时表的查询次数固定为批数，每批至多读取manifest中的C份当前源文件；日期内的U筛选只读该临时表，不再次打开全部历史源Parquet。这里“一次读取”指一次批量源查询，不宣称底层只发生一次磁盘IO。每批常驻新源数据仅为需刷股票在本批至多20个日期的行；旧全市场B及候选所需关系按当前日期持有，不累计20天全市场旧文件。临时表沿现有连接内存及受控spill设置，不新建连接/配置。每批最多40个日期/层目标，逐文件提交；等价内容可按原规则不replace。完整性所需SHA/读回仍执行，成本分别记录，不能为凑一次读取而跳过核验。

**中断与释放。**批源读取、日期处理、文件读回或业务接收结果失败时，停止后续日期/批次；当前迭代器关闭或取消同样进入finally释放关系。已经发布的Raw/Silver及逐文件证据保留，不回滚；不删除本run历史源排障证据。获准新run仍重新下载原失败完整范围，不复用旧源、批临时表或候选，不从失败的第几个日期/批次接续。20日不是事务或下载恢复边界。

**例子及验收。**A/B两股本轮需回刷45个交易日：先完成两股完整历史下载，再按20/20/5处理；每批先物化本批A/B新行，逐日更新全市场Raw及对应Silver，批末释放。隔离测试独立构造1/20/21/41/45交易日及节假日样本，验证批数1/1/2/3/3、尾批、日期顺序、T不被历史覆盖、无关股票不变、40文件上界；记录批源读取查询次数分别为1/1/2/3/3，禁止逐日回源文件扫描。分别在批读取、Raw完成后Silver失败、跨批和业务提前关闭注入异常，断言临时关系清空、已发布文件保留，以及新run确实重下完整范围。隔离测试及保存真实响应的链路已按上述要求验证；真实请求、正式PG事件和全范围操作不以这些结果代替。

DuckDB临时表的连接作用域、物化及可受控spill行为依据[CREATE TABLE官方文档](https://duckdb.org/docs/current/sql/statements/create_table.html)；多个明确Parquet文件作为同一查询输入见[多文件读取官方文档](https://duckdb.org/docs/current/data/multiple_files/overview.html)。

## 9. 两个综合checks与事件

| 结果 | 合同与不能混淆的边界 |
| --- | --- |
| 输入就绪 | 股票复权因子Raw T/P完整复刻现有Raw因子必要check语义，sensor及job预检均必需；不用非空文件或Raw技术因子市场覆盖替代。 |
| Raw综合check | 可读/源字段类型/非空唯一主键/日期范围及B-K+U。日U来自本次完整内存unit；历史U另外要求当前run完整源保存及读回通过。股票未补齐不使文件正确性检查失败。 |
| Silver综合check | DATE、主键、对应Raw范围、完整业务字段/合法值及逐行对账；本期无新增过滤或填值，无数量比例门槛。 |
| 日可读/覆盖 | 文件及必要检查通过即可用；应有集合是T日上市人民币股票减全天停牌，盘中仍应有，按代码求差。上游覆盖依据未知不宣告补齐、不清空正式数据。本期Silver不额外过滤，成功生成后与Raw主键/行数对应；Raw源缺口与两层处理失败分别记录。§4.0.1已知应有非空却没有可用日数据时run业务失败；已有有效部分数据不因此改判文件check失败或停止发布。 |
| 历史完成 | 原T Raw应有代码已齐、原T Silver有效且对应当前Raw，完整名单、adj_factor数据集T/P、本轮完整范围及全部已发布事实对应；缺关键因子/覆盖未知/Silver无效不能伪装完成。producer最终成功后才可供后续轮次跳过历史；失败run的物理完成不免除重新下载。两接口因子差异只诊断，不宣称源指标数学正确性已经证明。 |

生命周期采用`list_date <= T AND (delist_date IS NULL OR T < delist_date)`。全日停牌按§5.2先核suspend_d_ready_for_trade_date(T)及最终silver_stock_suspend_daily文件身份，再使用其`suspend_type='S' AND suspend_timing IS NULL`，时段非空是盘中；不能因为停牌输入未产生便认定没有停牌，不读取confirmed数据自行合成。该集合用于判日补采和历史前Raw齐备，不过滤Raw；T/P股票复权因子数据集硬门槛与其覆盖参考缺失不是同一个条件。

sensor与job复核均使用现行`raw_tushare_adj_factor_ready_for_trade_date(instance, trade_date)`，只针对T/P读取Raw因子物化及其3项检查事实，共2分区×3项check；它不是全市场股票覆盖证明。job再对实际两份Raw文件执行字段/日期/唯一性/正值等必要业务校验并比较。不得改用`batch_raw_adj_factor_lake_readiness`然后声称只扫两份Raw：当前实现即使layer=raw仍构造Silver路径、校验Silver并进入含生命周期的聚合，隐藏读写范围和成本不符合本次边界。本需求不修改该已有helper；sensor不算全名单，job显式处理无P与旧待处理。

每天检查定义始终两个，不按股票/字段/窗口新增。日阶段两资产各一个输出/check；历史涉及D个d<T日期时最多另有2D个物化和2D个检查结果。内容未变不重复替换，事件如实标注保留当前文件并通过本轮校验，不能宣称文件内容发生变化。十个计划时点包含前日补采占用，不能预算成10次今天另加1次Q；此外还需计预检记录、下载开始/名单观察及历史事件，整晚不只两条事件。

采用`multi_asset(specs, check_specs, partitions_def)`及`AssetCheckSpec(blocking, partitions_def)`；同一步内阻断由业务显式执行。`AssetCheckResult`没有partition；历史`AssetCheckEvaluation`及`target_materialization_data`参考现行repair/资金流事件代码。相应实现后隔离验证：日物化后历史失败仍可读、检查真实绑定正确partition/run/materialization、重复输出不产生异常、观察持久化时点、历史批量取事件而非逐日深扫。静态代码核对不等于事件API运行验收。

发布前、读回与checks复用纯校验及本批聚合证据，文件改变不沿旧绿色。sensor只看今天/Q的有界结果及必要输入，不全湖或全事件扫描；超过100历史分区或分区×check数超过1000按治理批量聚合。覆盖诊断和历史待处理不新增状态资产，cursor不是事实源。

每次Silver更新的检查分两步使用同一套规则：候选提升前，核DATE、261列类型/顺序、主键非空且唯一、日期属于本分区、259数值有限或合法NULL，以及与对应已发布Raw逐行全字段一致；不通过就不提升。提升后核正式文件身份、读回结果和对应Raw身份，成功才保存绑定本次Silver物化的综合check。它证明“这份Silver忠实保存了当前Raw”，不承诺Tushare已经提供当天全部股票。

当日股票是否齐备也必须检查并保存到DG：日Silver检查通过后执行§5.2的应有代码集合比较，把expected/actual/missing及完整性三态存入§6.1日阶段观察；该记录与Raw物化/check及生命周期/停牌依据绑定。因管理员允许少股票的数据先供业务使用，missing>0不把Silver文件正确性检查改判为失败，但明确记录覆盖未齐并禁止该T历史回刷。后续sensor和repair直接读取这些PG记录，身份未变就不重做检查；不能只读run SUCCESS或只读Silver检查passed就声称覆盖齐备。只有输入变了、检查缺失或绑定不符时，按§5.2处理，不否定DG有效记录的用途。

### 9.1 来源输入到本地列的确定转换

编码落点：源值检查及分批转换放 `defs/io/stk_factor_pro_candidates.py`；源合同字段名只引用 `tushare_download/contracts/stk_factor_pro.py`；两层 schema 由既定 `defs/run_contracts/asset_column_schemas.py` 映射，不抄写259个字段名。普通 HTTP 入口固定传内部来源 `http`，bootstrap 固定传 `prod_postgres`，业务不选择 transport。

```python
def stk_factor_pro_raw_trade_date(value: object, *, source: Literal["http", "prod_postgres"]) -> str: ...
def stk_factor_pro_double(value: object, *, source: Literal["http", "prod_postgres"]) -> float | None: ...
def stk_factor_pro_http_rows(
    result: UnitResult, contract_fields: tuple[str, ...],
) -> Iterator[tuple[object, ...]]: ...
def build_stk_factor_pro_raw_batch(
    *, rows: Iterable[Sequence[object]], source_fields: tuple[str, ...],
    source: Literal["http", "prod_postgres"], expected_dates: tuple[date, ...],
) -> pandas.DataFrame: ...
def write_stk_factor_pro_raw_fragment(
    *, connection: DuckDBPyConnection, frame: pandas.DataFrame,
    candidate_path: Path, expected_row_count: int,
) -> StkFactorProFragment: ...
def build_stk_factor_pro_silver_candidate(
    *, connection: DuckDBPyConnection, verified_raw_path: Path,
    target_trade_date: date, candidate_path: Path, run_root: Path,
) -> StkFactorProFileAudit: ...
```

HTTP实际fields必须与完整源契约字段集合一致、无重名，每行值数与实际fields一致；依实际fields建立位置映射，再显式投影为契约的固定顺序。仅顺序不同不丢行、不错位；缺列、多列或重复列明确拒绝，不借zip截断或补None兜底。bootstrap的SELECT本身按白名单排序，游标description须与该完整投影顺序一致。

HTTP适配必须接真实`UnitResult`：先确认termination全部scope完成、statistics.row_count与len(records)一致，核`observed_field_sets`（包括合法空结果的字段集）；逐个SourceRecord用它自己的fields映射自己的values。同unit跨页列顺序不同也不能用第一页位置套所有行。`stk_factor_pro_http_rows`按契约顺序惰性产生值tuple给公共批转换函数，不先复制整个unit为第二份行列表。比较日期时，源YYYYMMDD按本节严格解析为date，unit的ISO point/time_range按§6解析为date，再作日期比较，不能直接比较两种文本。日BY_POINT逐行日期须等于result.unit.point对应日期；历史BY_OBJECT_RANGE逐行ts_code须精确等于result.unit.object_code且日期落在result.unit.time_range闭区间，T诊断行也遵守对象限制。请求000001.SZ却返回600000.SH时直接报源业务数据不符，不静默过滤、不写入别股；全市场日请求不套单一股票限制。unit的对象/point/time_range还须与本任务规划值一致，不能仅凭返回unit自证范围。Prod则用cursor.description的列名核顺序，直接把本批tuple rows交同一转换函数；公共函数不直接接受SourceRecord，也不猜其结构。

`StkFactorProFragment`是frozen dataclass，固定`relative_path:str,file_sha256:str,content_sha256:str,schema_content_digest:str,row_count:int,observed_schema:tuple[tuple[str,str],...],min_trade_date:date|None,max_trade_date:date|None,first_code:str|None,last_code:str|None`。路径、摘要和计数按§5.4校验；零行时日期/首尾代码全None，非零时日期/首尾代码全有且有序。它只描述当前已保存片段，不放业务行；历史HTTP一个完整unit对应一个文件，bootstrap各5000批对应各自片段。日HTTP不调用片段写函数、不产生Fragment或源文件引用。

| 字段/来源 | 接受值 | 明确拒绝/禁止 |
| --- | --- | --- |
| `ts_code` 两来源 | `type(value) is str`，精确匹配本数据集股票代码合同，当前A股为六位数字加 `.SH/.SZ/.BJ`；保留原字符串 | NULL、空白、前后空白、整数、任意对象转str；不自动trim/补前缀/改代码 |
| `trade_date` HTTP | `type(value) is str`，ASCII八位数字；先核正则 `[0-9]{8}`，再按年月日构造 `date`，最后 `%Y%m%d` 回写必须与原文一致；该日期须处于本unit约定日期范围 | 空、NULL、`2026-10-21`、整数20261021、`20260230`、多余空白、日期越界；不使用宽松自动推断、不静默转NULL |
| `trade_date` Prod | `type(value) is datetime.date`（不接受子类datetime），源 schema 核为DATE后，显式 `value.strftime('%Y%m%d')`；检查本批准窗口/本次选中日期 | timestamp/date字符串/NULL；源 schema 变化须先停下核合同，不临时兼容 |
| 259数值 HTTP | `None`、精确 `int`（不含bool）、精确 `Decimal`；符合有限DOUBLE范围后显式一次转 `float` | bool、str、float（当前HTTP合同不交付float）、NaN/Infinity的Decimal、转换溢出；不把字符串数字、空字符串当合法数 |
| 259数值 Prod | `None`、精确 `float`；以当前Float(53)真实合同为依据 | Decimal、str、bool、NaN/Infinity；遇见不同真实源类型先报源合同不符，不隐式容纳 |

数值标量规则：先检测来源精确类型，None直接保留NULL；Decimal先 `is_finite()`，其他可接受数值使用 `float(value)`，捕获 `OverflowError/ValueError`，再 `math.isfinite(result)`。负数、0、极小但DOUBLE仍可表示的有限数、合法NULL均通过，不按价格正数或指标合理区间过滤。若有限非零输入转换成0，报无法无损表示该非零数，不能静默消失；一般十进制->IEEE754 DOUBLE的舍入属于已声明存储映射，不逐位要求Decimal精确相等。正负0按数值等价比较；不新增容差。

HTTP unit 已完整交付后，只处理当前一个unit并创建其列数组；bootstrap则仅处理当前5000行批次。5000不是下载器参数，不为HTTP新增一个同值配置，也不能自行把分页当完整unit。数值明确 `pandas.array(..., dtype="Float64")`，缺失使用 `pd.NA`；不先让DataFrame推断把None与源NaN混为一谈。`stk_factor_pro_double`是标量语义和小样本测试依据；实际批内按列构建，禁止构造全历史Python行集合。批内必要类型/范围校验不执行任何逐行数据库写入。

注册当前批DataFrame到本任务既有DuckDB连接，SQL以显式`CAST(... AS VARCHAR/DOUBLE)`建立当前批临时关系，并校验转换前后NULL数量/行数一致。

- 日HTTP：只在内存建立固定临时U，保留当前完整UnitResult至日两层完成。直接对`B-K+U`执行一次COPY生成唯一Raw发布候选；不对U另做一次COPY、不调用write_stk_factor_pro_raw_fragment。Raw候选及正式读回的expected始终来自本次内存U与本次B，不读取日源文件。Silver仅从已核验正式Raw生成。最后解除注册、DROP当前U、释放result/列数组/frame，finally同样清理。DuckDB如按既有资源策略发生临时spill，只是本次计算临时文件，不是日下载缓存，下一run不能读取或复用。
- 历史HTTP及bootstrap：按既定当前unit或5000行批次执行`COPY (SELECT <261白名单列> FROM current_batch ORDER BY trade_date, ts_code) TO <受控片段> (FORMAT PARQUET)`，写后读回schema、行数、主键/日期和当前批完整业务值；最后unregister、清临时关系、释放rows/列数组/frame，才取下一批。

仅当前unit/批次来源对象和必要转换对象共存；不使用executemany，不额外构造无用SDK DataFrame，不新装依赖。

### 9.2 两项综合check的共同校验结构与SQL

固定内部输出（定义在 `defs/run_contracts/stk_factor_pro.py`）：

```python
@dataclass(frozen=True, slots=True)
class StkFactorProComparison:
    expected_rows: int
    actual_rows: int
    missing_key_count: int
    unexpected_key_count: int
    changed_row_count: int
    changed_field_counts: tuple[tuple[str, int], ...]  # 固定字段顺序，零项可保留

@dataclass(frozen=True, slots=True)
class StkFactorProFileAudit:
    trade_date: date
    layer: Literal["raw", "silver"]
    path: Path
    file_sha256: str  # 本次实际文件读回得到的字节摘要；不是另一份持久化记录
    observed_schema: tuple[tuple[str, str], ...]
    row_count: int
    invalid_key_count: int
    duplicate_key_count: int
    invalid_date_count: int
    invalid_numeric_count: int
    comparison: StkFactorProComparison
    passed: bool
    diagnostics_path: Path | None  # 本run受控路径，仅错误样本/摘要
```

`file_sha256`使用本次实际读回文件的SHA-256，校验前后文件身份改变则停止，不把另一份文件的校验结果与当前sha拼成通过。`passed`由必需项目全部为0且schema精确一致计算；不得由业务传入true。列名/顺序/类型比较精确，Raw `ts_code/trade_date=VARCHAR`，Silver日期DATE，其余259列DOUBLE。NULL唯一合法来源为合同允许的缺失，不要求所有259列非空。主键NULL、重复或非法日期即失败；先核主键唯一性才能用主键JOIN作逐行比较。合法少股票不参与该失败判定。

为每日期构造有明确来源的两份关系：

- 源片段保存对账：仅历史HTTP与bootstrap，expected为本批按上述规则转换后的261列，actual为读回片段；两者统一Raw表示。日HTTP无片段及该对账分支。
- Raw合并对账：B为本次构建时已验证的旧Raw；日U为本次完整内存UnitResult转换的临时关系，历史U为当前run完整保存并读回的历史源。两者均须当前日期完整、主键唯一。expected关系为 `SELECT B.<261列> FROM B WHERE NOT EXISTS (SELECT 1 FROM U WHERE U.ts_code=B.ts_code AND U.trade_date=B.trade_date) UNION ALL SELECT U.<261列> FROM U`；actual为候选/已发布读回Raw。日check的expected不读取下载中间文件，源行数与保存条数的核对在内存U计数及B-K+U最终行数中完成；不能用正式Raw与自身比较。
- Silver对账：expected直接从本日期核验后的Raw显式投影，`CAST(strptime(trade_date, '%Y%m%d') AS DATE)`，actual为Silver候选/读回文件；不存在旧Silver独立合并分支。

所有输入类型/日期验证先于转换 SQL；不使用TRY_CAST把非法值悄悄变NULL。SQL中 relation/列名只从静态白名单生成；文件路径由paths.py生成并验证后传入，不接受配置SQL片段。核心比较如下，`mismatch`是对259数值列逐列生成的 `e.<field> IS DISTINCT FROM a.<field>` 的OR，代码与日期通过主键等值JOIN：

```sql
WITH joined AS (
  SELECT e.ts_code AS expected_code, a.ts_code AS actual_code,
         e.trade_date AS expected_date, a.trade_date AS actual_date,
         (<mismatch>) AS value_diff
  FROM expected e FULL OUTER JOIN actual a
    ON e.ts_code = a.ts_code AND e.trade_date = a.trade_date
)
SELECT
  count(*) FILTER (WHERE expected_code IS NOT NULL AND actual_code IS NULL) AS missing,
  count(*) FILTER (WHERE expected_code IS NULL AND actual_code IS NOT NULL) AS unexpected,
  count(*) FILTER (WHERE expected_code IS NOT NULL AND actual_code IS NOT NULL AND value_diff) AS changed
FROM joined;
```

逐列变化计数使用同一次有明确唯一主键的JOIN聚合259个 `count(*) FILTER (WHERE e.field IS DISTINCT FROM a.field)`，仅统计两边均有键的行。NULL对NULL相等，NULL对数值不同；负数正常，0.1的HTTP Decimal与DB float均先得到同一个DOUBLE表示再比较。禁止只比行数、只比主键、只比sha、任意epsilon或用普通 `<>` 漏掉NULL差异。主键双向差异和全部259数值差异共同覆盖全部261业务字段。

不把历史源U缺少旧键直接塞进上述 `missing_key_count`：期望合并关系本来保留那些B行，所以合并对账可以通过；另按既定 `unrefreshed-keys.parquet`记录哪些原scope旧键没有被U刷新。其非零不新增第三项blocking check、不删除旧键，却阻止谎称整个历史scope已全部刷新。合并公式的K是B/U键交集数量，最终行数还须等于 `B_rows-K+U_rows`。

候选完成前校验和正式两项check复用上述内部结果，发布后确认实际目标对应已校验候选，再输出同一结果；不能为了复用而跳过目标已变的核对。metadata放汇总、样本位置/摘要、对应Raw身份；完整错误样本固定最多20行，错误总数必须全量计入本次有界日期关系，不截前20行就算通过。历史20日按日期批量构造SQL，不全历史回读。

## 10. 配置、规模与性能门禁

不新增下载器频率/账号额度/线程/锁配置。组件现有2GiB单unit工作空间、64MiB响应、5/30/45秒超时、最多4次同页尝试及1/2/4秒退避沿用；工作空间不是进程总内存承诺，不重测用户拍板值。业务调度控制请求频率。

本数据集运行合同在拟新增`defs/run_contracts/stk_factor_pro.py`单处维护，随代码加载。sensor装饰器、历史planner、bootstrap和验收代码均import相应常量，禁止在入口、脚本、测试之外另写一套业务默认。没有新增env、配置表、页面开关、任意run参数或运行中热更；修改常量须同步方案/LLD和消费者测试，代码重新加载后对新执行生效，既有run记录仍保留当时取值。

| 参数名/规则 | 已确认默认与来源/持久化 | 作用范围、消费者、生效与运维可见性 | 必须测试 |
| --- | --- | --- | --- |
| 首轮/后续/截止 | 管理员：只在开市执行日，19:00、固定30分钟、D+1 00:00，最后23:30，Asia/Shanghai；run_contracts单处代码规则。 | sensor选时点、run身份及job开跑复核；D/T/slot写run_config及metadata，不支持任意运行覆盖。 | 18:59/19:00/23:30/00:00、延迟与活动跨时点；使用模拟时钟。 |
| 管理日期/前日机会 | 今天及严格前交易日Q；每执行日1次业务下载，依持久实际开始事实；管理员决定。 | 注册、sensor、开始记录和恢复；metadata分别显示Q日覆盖、历史和机会，不因历史失败抹掉日完成。 | 仅今天/Q；未就绪未耗、已耗不重获、仅历史失败不挡今天。 |
| `STK_FACTOR_PRO_UPDATE_SENSOR_INTERVAL_SECONDS` | `60`秒；run_contracts代码常量。 | 更新sensor的`minimum_interval_seconds`；代码加载生效，定义可见并记录于评估摘要。只限评估频度，不改半小时slot、重启去重或午夜。 | 定义取统一常量；模拟多次tick不能一分钟下载一次或补发旧slot。 |
| `STK_FACTOR_PRO_PARTITION_SENSOR_INTERVAL_SECONDS` | `600`秒；同上。 | 注册sensor的`minimum_interval_seconds`；默认STOPPED，不等数据就绪；定义/评估摘要可见。 | 间隔与更新sensor分开，只注册真实今天/Q、不删除旧键、不造未来。 |
| `STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS` | `20`个交易日；同上，管理员确认。 | 自动历史和手动repair共用§8升序切批；run metadata记录取值、当前批日期/序号、完成文件与耗时。完整源后才合并，逐文件生效。 | 1/20/21/41日、节假日、无行日、末批和批间失败；不改变unit/历史范围，不新增分区。 |
| 对象历史下载窗口 | 每股可信最早已有日期至原T，一次完整unit；依已批准可信范围和run_contracts的规划规则，不默认按年切。 | history planner和下载函数，范围/digest保存到原完整plan/ranges；下载器扇开代码，分页按源契约。 | 未截短历史；20日合并不切请求；无法证明最早日期时停止，并说明缺少的依据。 |
| `STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS` | `5000`行；run_contracts代码常量。 | §10.1 planner/服务端cursor的itersize和fetchmany共用；bootstrap metadata记录月份、批数、保存行数及实际取值，单批落盘释放。 | 0/4999/5000/5001行、同一天跨批、月边界、日未完整重取；不得普通cursor/fetchall/累计整月。 |
| DuckDB资源 | **引用现有**`DEFAULT_DUCKDB_CONNECTION_SETTINGS`：16GB、4线程、临时目录`/Volumes/datasource/.goldenshare_duckdb_tmp`、512GB临时空间上限；事实源为`defs/duckdb_connection.py`，非本数据集新默认。 | asset/op通过既有`DuckDBResource.connect()`；离线bootstrap通过同一`connect_configured_duckdb()`；同任务同时只保留1个主要计算连接，传给本批函数复用并finally关闭。metadata从实际settings记录，不写死第二套值；不改其他调用者。4线程是SQL计算，不是4个下载对象。 | 替身证明同批不嵌套创建主要连接；隔离读取实际settings与原设置相符，关闭后释放；临时目录与run候选路径不能混用。 |
| 下载器容量/批内存估算 | 继续组件既有2GiB unit、64MiB响应；单日结果150～220MiB、处理峰值约0.5～1GiB，按约1GiB处理余量规划；bootstrap128MiB工作空间估算/256MiB余量分别见下文。 | 组件限制只对Tushare；估算不是新硬限、无新配置，也不是整个进程或DuckDB总内存承诺。512GB是spill上限而非预占，实际需核剩余空间。 | 不将数据库5000行float估算套到HTTP Decimal；无隐式截断/缩字段；不为估算另拉数据压测。 |
| bootstrap人工入口八字段 | §2.4及§10.7的本job配置，原自动字段维持原口径，三项bootstrap字段自动默认None、人工必填；单处run_contracts schema。 | run_config持久化、按用途解析/parent/root和授权核验、RunIdentity、开始/阶段观察、记录读取及repair继承；仅该run生效，无env/配置表/热更新，不修改通用RunRequest。 | 自动不生成新用途、错字段/摘要/日期拒绝；无parent首次及gap归0后原生重执行均有正反例。 |
| 取消状态读取间隔 | 内部常量`STK_FACTOR_PRO_CANCEL_STATUS_POLL_SECONDS=1`秒，在run_contracts单处维护；无env/run_config覆盖。 | §6同线程控制闭包，普通组件检查按monotonic节流，业务保存/replace等边界强制刷新；加载后生效，进度摘要记录实际状态读取次数。它不是下载频率或线程调度参数，不改组件。 | 模拟时钟及假instance证明密集检查每秒至多1次读取、首次必读、强制边界必读、取消保持、读取失败停止。 |
| 输入gate | T/P股票复权因子Raw就绪且job复核；管理员决定。 | sensor及job使用现行Raw helper；缺因子不网络，不把市场未全齐当成日发布门槛。 | 缺T/P均不下载；少股票仍允许合法日发布。 |
| 性能验收目标 | 同run_contracts单处`STK_FACTOR_PRO_SENSOR_TARGET_SECONDS=5`、`STK_FACTOR_PRO_DAY_UPDATE_TARGET_SECONDS=120`、`STK_FACTOR_PRO_HISTORY_REFERENCE_TARGET_SECONDS=1200`；管理员接受的初值。 | 分别用于sensor一次评估、无历史正常日更，以及类似17股原完整历史的成本外推比较；测试/验收报告记录样本、推算和目标，**不是运行超时、kill或任务请求预算**，不写入下载器限制。 | 模拟负载/隔离小批计时与独立报告；超目标先定位原因，不删除数据或强杀，也不据外推冒充全范围实测。 |

`DuckDBResource.connect()`直接调用`connect_configured_duckdb()`，该函数在contextmanager中校验并关闭连接。在本数据集函数间传递连接，避免helper自行再开连接令16GB看似单份实为多份；传感器只在必要有界核验期间短暂持有连接。资源设置以原模块为准，本数据集记录实际使用值。

| 场景 | 可确定的成本模型 | 验证项目（未实测） |
| --- | --- | --- |
| 每轮预检/名单 | sensor直接读候选T/P和已有DG结果；job读两因子文件重新生成本run完整名单，保留旧未完意图，不复用失败run下载数据。 | §6.2一次原T观察查询至多16条，必要引用最多11个run、各run观察最多16条且同次只读一次；这些只读PG元数据，不是历史文件扫描。Raw因子两日期三项check查询；Raw/生命周期/停牌身份未变复用原覆盖，改变才重算原T必要代码列，不逐tick重做261字段/全部历史对账。 |
| 单轮日源 | 有界样本5568行×261字段，暂定10000页大小约1次正常请求，恰满须继续。 | 完整HTTP字节/耗时；当前唯一UnitResult、列转换与DuckDB临时U短暂共存的内存；唯一Raw候选及后续Silver候选读写、T旧文件与两层必要checks/覆盖成本。无日源文件、manifest、source-complete或重复Raw源落盘成本。 |
| 晚间与前日 | 今天理论至多10固定时点，Q实际一次会占时点；无并发/积压。重试、分页、预检未开始再发及手动处理另计。 | 整晚源/合并/事件/候选留存峰值；不是下载组件请求总上限。 |
| 复权历史 | C代码、W窗口、D历史日期，完整原范围正常请求`sum(floor(H_i/10000)+1)`；同页最多另加3倍尝试；原T Raw不齐时0历史请求，整范围成功且输入未变才不重复。 | 完整历史源保留T但只发布d<T；20日/最多40文件局部合并，当前正式B与新源U字段/主键对账、缺旧键记录、空间与事件批量读取。 |
| 失败后重新执行 | 无论失败在下载、候选、Raw/Silver发布或事件收尾，重新执行均计入整阶段新下载请求；完整旧源不省网络，Q不重获自动机会。 | 当前正式文件读回/合并/校验、全部原失败范围重新下载、当前run候选与intent、最终读回和保留失败证据的空间；不计旧候选续接收益。 |
| 手动repair | 先核原T Raw完整，再核原T Silver有效且对应当前Raw；不通过0技术因子请求/0提升，不代补T。两项通过后完整原失败范围全部新下载，只d<T合并/事件。 | 原run有界授权定位、4字段/两摘要校验、原T覆盖及Silver已有凭据复用。新增Silver核验最多2次PG查询及T一份Silver身份检查，同run身份未变复用；不加261字段或全历史审计。计入T/P因子、完整新下载/20日批次/最终读回，无T资格窄查询，不计自动时点/Q机会。 |
| bootstrap人工首次/重新执行 | 同日更单T日源及必要历史请求；首次原导入小记录最多一遍、当前T缺口/依据有界校验，重执行至多三条精确身份run及有界观察；无Prod请求。 | 当日统计在两层/check后即保存；历史每20日批次更新已完成日期和summary，普通异常也收尾已完成事实；每次summary一遍原范围小记录，不能只计最后一次。旧新代码覆盖共用纯函数，必要主键集合运算及身份读回计入，不重算指标。失败后仍计T及原失败历史全部网络重取。 |
| bootstrap | 获准Prod范围显式261字段，按自然月及5000行服务端流式批量；单月约`ceil(月行数/5000)`次取批、非每日期新连；逐文件候选/发布，事件另授权。 | 当前准确范围/源截止与月计数、来源维护窗口、只读事务/超时、峰值磁盘，以及未完成日期重取、完整日源复用、逐文件继续和最后对账成本。 |

容量不足、范围超批准或候选不完整停止并说明，不减少字段/股票或缩短历史造完成。禁止无界导出、全历史长事务、Python逐行大合并、每日期新连远程库的未经测量默认。参数与验收目标已确认，尚无对应来源/性能运行验收结论；不因写了目标就宣称已经达标，也不将尚未实现的完整链路运行验收错置为现在必须通过。

**单日内存估算及编码约束：**

| 项目 | 估算方法与范围 |
| --- | --- |
| 规模依据 | 既有有界来源样本5,568行；按5,600～6,000行、261列规划，包含259个数值列。不请求新的来源样本、不跑内存压测。 |
| 净数值 | `N×259×8`字节，约11～12MiB，仅表示转换成DOUBLE后的数值载荷，不是Python结果或Parquet文件体积。 |
| 下载结果 | 当前`source_response.parse_http()`以`int/Decimal`解析，`SourceRecord`保存fields和值tuple。按64位CPython常见Decimal约104字节、tuple引用8字节，259列全部非空且按Decimal计算约144～154MiB；再计行、值元组、代码/日期及分配余量，完整日UnitResult按150～220MiB估算。fields元组按页/合同共用，不逐行复制字段名；int/NULL比例与数值长度会改变实际量。 |
| 阶段峰值 | 下载时计响应字节/JSON解析及`UnitMemory`统计对象，转换合并时计UnitResult、列数组/frame、临时U、当天旧Raw和候选计算缓冲；按各阶段较高值估计约0.5～1GiB，先按约1GiB处理余量规划。不把这些本不同时存在的对象全部长期保留。 |
| 既有边界 | 2GiB是组件单unit工作空间，64MiB是响应限制；二者沿用，不预占内存、不改为整个进程上限。解析预留计数仍服从现有算法，估算不能保证任意64MiB响应均可通过。DuckDB16GB限制不代表预占16GB，也不限制全部Python内存。 |

本估算依据当前`download_models.SourceRecord/UnitResult`、`source_response.parse_http()`、`unit_memory.UnitMemory`和`unit_output.UnitOutput.finish_unit()`，以及§9.1的本次列转换和临时表流程；不是bootstrap5000行float批次的估算，也不是多股票全历史同时常驻的预算。没有新增内存配置或自动扩容，实际容量错误按既定停止规则处理。

取消状态读取另计入PG预算：设同一阶段经历t秒并实际执行C次普通取消检查，普通状态读取不超过`min(C, floor(t)+1)`次，另加F次业务边界的强制读取；无检查点的等待期间不产生后台查询。记录实际调用次数供小样本核对，不把259列或行数乘进PG请求量；这些只读本run，不扫描历史事件。

编码必须让生命周期可核对：会话正常关闭并核summary前不创建Raw候选；仅持有本次一个结果，不先复制完整行列表；转换注册只在构造临时U期间保留，完成后解除注册并释放列/frame，保留独立临时U及原结果供日校验；日Raw/Silver发布及读回完成后，DROP临时U并清除本次结果引用，异常/取消finally也执行相同清理。不得把结果放入全局、下一轮或失败记录；发布候选不是可复用下载缓存。内存释放表示不再持有对象引用，不要求RSS立即回落，也不为此调用强制GC或增加后台清理线程。§11用小夹具验证释放路径、旧数据不被复用和多轮不累计引用，不靠大范围跑数证明估算。

bootstrap的5,000行估算依据是当前`RawStkFactorPro`和261字段契约：代码按9字节ASCII、Prod DATE净值4字节、259个Float(53)按8字节，全非空净值`5000×(9+4+259×8)=10,425,000`字节，约9.94MiB；不是PG整行或Parquet文件大小。常见文本数值平均8～12字节时，计每列4字节长度及每行协议头约15～20MiB，数值按24字节估算约35MiB；格式、NULL及驱动改变会影响实际量，不把它当绝对协议上限。64位CPython基本tuple/float/date/code对象约40MiB，另有libpq缓冲和列式转换；本批工作空间先按128MiB估算、256MiB留余量，不新增硬限制，也不声称进程峰值。仅取261列，不读raw_payload等辅助列；实现采用服务端named cursor，不得以普通cursor.fetchmany冒充流式。上一批保存并释放后才领下一批，不能在Python累计整月。Tushare的64MiB响应/2GiB unit限制不用于Prod数据库导出，DuckDB的16GB也不是Python/libpq总内存上限。正式导出前复用已有schema证据核准实际字段类型；不为大小估算另拉5,000行压测。

### 10.1 bootstrap自然月规划、5000行流式和恢复

`defs/bootstrap/stk_factor_pro_history.py`的正式入口先按§4.2执行只读活动任务检查，再核原operation的批准及完整日期/发布记录。由这些记录机械区分“还需来源读取或业务文件恢复”和“全部业务文件已完成、仅本地统计”，不增加模式参数或独立入口；两种分支的维护及来源边界见§10.2。首次正式文件提升前再检查活动任务。由调用方传入既有instance，不在入口初始化instance、创建run或停启sensor。月导出/恢复函数只由该已检查入口调用，不能将单月函数另作绕过维护步骤的正式入口。

初始化业务范围固定为Prod来源表全部现有业务数据。正式开始时在约定来源维护窗口内取得全表实际最早/最晚日期及按日计数，保存到既有批准记录；起止是实际范围记录，不是可自行缩小的过滤参数。2026-10-23 23:56只读核验为`2017-01-03～2026-10-21`、估计10,338,305行、表及索引31,262,990,336字节；精确总计数30秒超时后停止，未取得精确全表行数。详细边界见方案§3.2，执行时不写死该范围或估计值。来源维护窗口、每月上界/超时、资源开销及正式执行仍需执行前核准。

planner将实际最早至最晚日期完整拆为相邻自然月窗口，记录闭开边界`[month_start, next_month_start)`，首末月仅裁到源实际范围；不漏月、不加股票过滤。显式投影261业务字段并按`trade_date, ts_code`稳定排序，不select *或读取raw_payload等辅助列。通过既有`ProdPostgresResource.connect_readonly_transaction()`每月建立独立只读事务、`connection.cursor(name=受控唯一名称)`及统一`itersize/fetchmany`批量；不能一条完整历史长事务，也不能每天重复建远程连接。Prod原有缺股/缺日只登记现状，不阻止其余合法已有行导入，不为解释旧数量差异而另拉全部源历史；导出漏行、字段/日期错误、来源变化或目标冲突仍须停止。

准备批准记录时，对上述每个相邻自然月使用只读事务、语句超时及绑定边界，执行以下计数SQL，仅返回每日计数：

```sql
SELECT trade_date, COUNT(*) AS row_count
FROM raw_tushare.stk_factor_pro
WHERE trade_date >= %s AND trade_date < %s
GROUP BY trade_date
ORDER BY trade_date
```

在源实际首尾间的自然日序列补明确0行日期，汇总所有月得到源总行数；这份计数只用于来源传输核对，不计算市场应有股票，也不要求先完成Prod覆盖预审。缺月、边界不符或任一月查询失败就不能形成完整计数依据，不用估计值补齐。不要求另跑全表`COUNT(*)`；导出前的当前计数复核也限定当前月及其selected_dates。

每次取至多5000行，按已核对源类型进行列式转换，保存为该run该月staging下连续编号的Parquet片段，读回核对源/保存条数和必要字段后释放rows及转换对象，才取下一批；日边界可以跨多个5000行批次，不能当成多份正式日文件或只保留最后一批。禁止fetchall、客户端普通cursor冒充服务端流式、Python逐行大表写入及把整月累积到列表。查询按`trade_date, ts_code`有序，看到下一日期或游标EOF才确认前一日期已收齐，保存其完整日源清单后，由同一主要DuckDB连接生成该日Raw/Silver候选并逐文件发布；不要求整月源完成才发布已完整日期，也不在每5000行时覆盖正式日文件。本入口仅支持首次无目标、与本次来源结果内容等价，或同operation沿原intent恢复；已有不同内容目标一律停止，不执行没有对应批准结构的合并/覆盖，交管理员另行处理。

自然月仅是远程查询窗口，不新增月级完整门槛或恢复平台。游标中断时，当日未收齐的源片段不发布；已完整保存/发布的日期按既有日源完整事实和逐文件intent/checkpoint核验后保留或复用，完整日源存在但发布失败不强迫重读数据库。获准重执行时对本月尚未完成的日期做有界查询，整日重新读取，不按OFFSET、5000行批号或最后一行继续；没有明确完整事实的日期不能猜已经完成。需要来源读取/业务文件恢复时发现源范围或截止修订即停止，不原地改批准或把旧源假作新依据完整；仅本地统计沿已批准原范围报告，不探测Prod是否又增加数据。正式事件补录仍独立授权，物理阶段不借机运行正式Dagster。

### 10.2 bootstrap批准输入的封闭结构

bootstrap继续是单独获准的直接文件写入，不接入日常job或下载器。唯一来源固定 `ProdPostgresResource` + `raw_tushare.stk_factor_pro`；261字段来自唯一源合同。以下是执行前审核并保存的业务输入，不是env、页面配置或任意SQL入口；普通调用不得自行生成一份“批准”记录。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapApproval:
    record_version: int                 # 固定1
    operation_id: str                   # 受控安全标识，非路径
    start_trade_date: date              # 维护窗口内源表实际MIN，非可剪裁输入
    end_trade_date: date                # 同次源表实际MAX，闭区间
    source_cutoff_trade_date: date      # 必须等于end，不能截掉已有日期
    source_maintenance_start: datetime  # 有Asia/Shanghai偏移
    source_maintenance_end: datetime
    source_identity_digest: str         # 非秘密来源定位+表+schema白名单摘要
    contract_content_digest: str
    approved_daily_counts_ref: str      # 受控staging相对路径
    approved_daily_counts_digest: str
    approved_source_evidence_ref: str   # 源全量实际边界/计数合计/维护约定/固定样本证据
    approved_source_evidence_digest: str
    month_limits: tuple[StkFactorProBootstrapMonthLimit, ...]
    source_statement_timeout_ms: int    # 正整数，正式数值执行前批准

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapMonthLimit:
    month_start: date                   # 按源全量实际首尾裁切后闭边界
    month_end_exclusive: date
    row_upper_bound: int                # >=此月批准日计数之和，非5000
```

JSON读取拒绝未知字段、缺字段、重复键、非标准日期/无时区时间、bool冒充int、非正timeout、负上界、月份重叠/缺月、首末月未按源实际范围裁切、cutoff不等于end、引用越界/符号链接、摘要不符。维护窗口的先后关系及有时区类型总要核验，是否仍在窗口内则按下文实际工作分支判断。既有`approved_source_evidence`必须记录同次全表实际MIN/MAX和按日计数合计；校验start/end与该证据一致，需来源读取时执行预检，再核当前源边界及按日计数，来源变化就停止，不静默缩小范围或自动改批准记录。零行月可上界0；5000/20日/DuckDB参数不放此输入供覆盖。`approved_daily_counts`是Parquet固定 `trade_date DATE,row_count BIGINT`，源实际首尾间每个日历日期一行，0明确记录；范围外不得混入，计数不得负数/NULL/重复，其合计必须与来源证据一致。已确认休市而源非空的日历冲突与字段/类型错误不得静默跳过；日历缺失或未知不冒充已确认休市，按§10.5保留未知并忠实导入合法已有行。原有缺日单独报告，不阻止其余合法已有行导入。

来源身份摘要在首次批准及实际来源读取时从resource解析出的非秘密主机/端口/数据库定位、固定schema/table、获准源列名/源类型和合同生成，不包含口令、完整DSN或token。实际数据库表的schema核验属于来源读取分支的执行预检，不能跨工程import Prod ORM充当真实schema证明。仅本地统计时从已验摘要的批准来源证据解析原身份，不创建resource连接、不访问远程schema/计数/样本，也不要求Prod连接凭据继续存在。维护约定和固定有界样本核验不等于逐行证明整个来源从未变化；来源读取及业务文件恢复必须明确依赖已获准维护窗口，发现违反维护约定/样本或计数变化即停止。

同一入口的分支顺序固定为：读回并验证不可变approval及批准计数/来源证据→按批准自然日期逐个核完整日源及两层完成事实→确定实际剩余工作→执行以下条件。不允许调用者传一个布尔值绕过条件，也不因现存summary自称完成而跳过文件核验。

| 实际工作 | 来源条件与允许动作 |
| --- | --- |
| 任一日期源未完整，或任一业务文件尚需生成/提升/恢复 | 必须仍在原Prod维护窗口，来源读取前核当前resource/实际schema/范围及本月计数；完整日源恢复业务文件也须原维护约定仍适用。过期即停，另行取得明确执行批准，不能自动延长原approval或改源摘要。 |
| 批准范围的业务文件已完成并按§10.4读回，仅补缺失/失效覆盖统计或汇总 | 原operation、approval、原导入证据/合同照常核验；尚未补数的当前文件核原完成记录，已有§10.5.6合法补数的当前文件核补数发布/check及当前SHA，不要求仍等于原导入SHA。不要求Prod维护窗口仍有效，不连接Prod、不下载、不重建或提升业务文件。继续满足DG维护及唯一写入要求，缺口/未知只影响统计及§10.6门槛。 |
| 本地统计过程中发现业务文件缺失、无合法补数凭据的改写或完成事实无效 | 停止相应日期的有效结论并报告；不自动切换来源读取/业务恢复，不把当前文件登记成原导入。合法补数凭据对应当前两层时走§10.5.6当前结果分支；凭据不全或文件不匹配时列当前不可核验，不回退Prod覆盖，交管理员处理。 |

所有批准记录、来源片段、日期完成记录和候选位于 `/Volumes/datasource/data_lake_staging/stk_factor_pro/bootstrap/operation_id=<id>/`下，由paths.py生成；正式路径仍使用既定Raw/Silver路径。调用者不得传Lake根、staging根、表名、字段清单、SQL、过滤片段或任意文件路径。读回引用按规范相对路径限定本operation或明确引用的旧operation，拒绝`..`、绝对路径与符号链接穿越。

```python
def validate_stk_factor_pro_bootstrap_approval(
    *, approval: StkFactorProBootstrapApproval, now: datetime,
    source_identity: StkFactorProSourceIdentity,
) -> tuple[StkFactorProBootstrapMonthLimit, ...]: ...
def require_stk_factor_pro_bootstrap_source_window(
    *, approval: StkFactorProBootstrapApproval, now: datetime,
) -> None: ...
def export_stk_factor_pro_bootstrap_month(
    *, prod_postgres: ProdPostgresResource, connection: DuckDBPyConnection,
    approval: StkFactorProBootstrapApproval, month: StkFactorProBootstrapMonthLimit,
    selected_dates: tuple[date, ...],
    on_complete_date: Callable[
        [StkFactorProBootstrapSourceComplete], StkFactorProBootstrapDateResult
    ],
) -> StkFactorProBootstrapMonthResult: ...
```

`StkFactorProSourceIdentity`为frozen dataclass：全部字段按`host:str,port:int,database:str,schema:str,table:str,columns:tuple[tuple[str,str,bool],...],contract_content_digest:str`声明，不在有默认字段之后声明必填字段；schema/table分别校验为固定raw_tushare/stk_factor_pro，不是调用参数默认。columns按261字段白名单顺序保存真实源列名、数据库源类型及nullable，来源摘要使用§10.3的规范投影，禁止含密码/DSN。端口1～65535，身份文本不得空，schema/table不能由输入任意替换。本节相互引用的类型在同一run_contracts模块定义并使用未来注解，不能为声明先后问题引入跨工程导入。

validate只做完整结构、引用、摘要及source_identity与批准证据的一致性核验；不会访问网络，也不以当前时间拒绝仅本地统计。require_source_window固定要求`source_maintenance_start <= now < source_maintenance_end`，由已分类的主入口在实际来源预检前、每月查询前、每次业务文件提升前调用；窗口过期不领取下一日期，不开始新提升，已完成文件保留。该内部职责拆分不是允许运营选择跳过校验。

`approved_source_evidence`固定保存`record_version=1,operation_id,source_identity:StkFactorProSourceIdentity,source_identity_digest,contract_content_digest,min_trade_date,max_trade_date,total_rows,approved_daily_counts_ref,approved_daily_counts_digest,source_maintenance_start,source_maintenance_end,maintenance_statement:str,verified_at,source_sample_ref:str,source_sample_file_sha256`。maintenance_statement须非空并记录批准的来源静止条件；样本ref仅引用原有获准有界核验结果，不增加每次统计的网络抽样。source_sample记录固定`record_version=1,operation_id,source_identity_digest,contract_content_digest,sample_date:date,sample_codes:tuple[str,...],row_limit:int,request_columns:tuple[str,...],returned_rows:int,observed_source_schema:tuple[tuple[str,str,bool],...],passed:bool,verified_at:datetime`；参数必须与已批准样本一致、row_limit精确正整数、returned_rows不超上限、request_columns严格261字段白名单且passed为实际核对结果。不保存任意SQL、DSN或口令。来源证据、批准计数及approval各自文件字节SHA核引用，source_identity_digest按§10.3规范投影计算；相互记录的范围/计数/窗口/合同必须一致。不可变approval.json的`approval_digest`统一为保存文件实际字节SHA-256，后续引用绝不另算“去掉时间后的批准摘要”。

`StkFactorProBootstrapMonthResult`为frozen dataclass：`month:StkFactorProBootstrapMonthLimit,attempt_id:str,source_rows:int,fragments:tuple[StkFactorProFragment,...],complete_dates:tuple[date,...],pending_dates:tuple[date,...],file_audits:tuple[StkFactorProFileAudit,...]`。fragments按保存顺序、日期集合去重升序。该结果不是恢复事实源，完整日期和文件仍须有固定路径记录读回。逐日覆盖统计另按§10.5保存，不在此结果内增加全历史业务行。

`StkFactorProBootstrapDateResult`为frozen dataclass，固定`trade_date:date,source_complete_digest:str,raw_audit:StkFactorProFileAudit|None,silver_audit:StkFactorProFileAudit|None,coverage:StkFactorProBootstrapDateCoverage|None`。有源行时两份audit全有且passed，coverage全有；源0且无旧文件时两份audit为None，开市/日历未知仍有coverage，已知休市0行才可coverage=None。返回值不含业务行。export校验返回日期、摘要和上述交叉条件，再把两份audit汇入MonthResult；不能因回调仅正常return就假定发布成功。

bootstrap重执行沿用原批准`operation_id`及该根的不可变`approval.json`，不增加“自动找旧operation”功能。开始时按批准日期清单逐个计算固定日完成记录位置；有效完整日直接读回复用，缺完整事实的日期整日重读。每次实际导出内部生成一个32位小写hex的attempt_id，源片段放在该operation的`source/month=<YYYY-MM>/attempt_id=<id>/fragment-<连续编号>.parquet`，避免重读时覆盖已被其他完整日期引用的跨日片段；attempt_id不进入业务输入摘要，也不是下载断点。新的operation_id代表另一份明确批准的执行，不扫描其他operation复用。批准/来源依据变更时停止，不能原地改approval继续。

### 10.3 bootstrap SQL、上限检测与分批源文件

每月一个 `connect_readonly_transaction()`；不改resource，不跨月持有事务、不上表锁、不新增隔离级别。先用普通控制cursor执行：

```python
control.execute("SELECT set_config('statement_timeout', %s, true)",
                (str(approval.source_statement_timeout_ms),))
```

这是事务内 `SET LOCAL statement_timeout`的可绑定参数实现，事务退出现有resource会rollback并关闭连接。它约束每次数据库语句执行，不等同整个bootstrap/网络传输的总超时；现有10秒connect_timeout仍只约束建连。超时后立即关闭named cursor、退出只读事务，不把当前日标完整、不自动重发查询。

使用 `psycopg2.sql.SQL` + 固定 `sql.Identifier('raw_tushare', 'stk_factor_pro')` 和白名单列Identifier生成：

```sql
SELECT <261业务字段>
FROM raw_tushare.stk_factor_pro
WHERE trade_date >= %s AND trade_date < %s
  AND trade_date = ANY(%s::date[])
ORDER BY trade_date, ts_code
LIMIT %s
```

绑定值为本月裁切边界、已批准且尚需重新读取的日期数组、`R+1`。R取该月已批准 `row_upper_bound`；selected_dates由planner从该月完整日期集合中，仅扣除同operation已有有效完整源记录且复核通过的日期后生成，不能由调用者任意筛选。首次全无完成记录时必须覆盖全部源日期，不能漏掉某天或某只股票。日期数组全在本月和源实际范围内、升序去重；空则无需开连接。SQL永远不加OFFSET或股票过滤；表名/列名不取用户字符串，也不拼接日期。普通控制cursor只做SET/schema/有界计数/固定样本核验；261字段明细只通过 `connection.cursor(name=受控唯一名, scrollable=False, withhold=False)` 的单条SELECT读取。`itersize=STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS=5000`，每次 `fetchmany(min(5000, R+1-seen))`，不得fetchall。

预检批准的日计数和当前按日计数一致，selected_dates计数之和<=R；导出最终又按每日期实际行数核批准计数。R+1是运行中的截断防护，不是正常数据分页大小。**先检测是否收到了第R+1行，再把该行当“后一天已经开始”的依据。**触及R+1立即停止，不保存额外行，也不把当前未关闭日期记完整；此前已经完整发布的日期保留。恰好R行且真正EOF、日计数/主键/日期等均核对通过时才允许完成最后日期，不能把LIMIT造成的返回结束误当来源本来就没有更多行。

每批先核完整261字段、类型/日期范围和排序。跨批维持上一批最后 `(trade_date, ts_code)`，键必须严格升序；同日跨批重复/逆序即停，不能去重。当前批转换成Raw表示后存 `source/month=<YYYY-MM>/attempt_id=<id>/fragment-<至少六位从000001起的连续编号>.parquet`，原子保存并按§9读回为StkFactorProFragment，才释放本批rows/列式转换对象。片段first_code/last_code对应源排序中第一行/最后一行代码，首尾完整键为(min_trade_date,first_code)/(max_trade_date,last_code)，跨日时不能额外要求first_code<=last_code。只保留片段的小型描述和本日累计行数，不保留本日业务行列表。

以下完整记录类型统一放`defs/run_contracts/stk_factor_pro.py`，读写/验证复用该模块的封闭结构校验及原子JSON办法。不是另一套通用状态平台；路径只由既有`defs/paths.py`扩展受控函数生成，实际读取/发布仍在`defs/bootstrap/stk_factor_pro_history.py`。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapFragmentRef:
    fragment_no: int                    # 精确int>=1；attempt内连续
    attempt_id: str                     # 32位小写hex
    fragment: StkFactorProFragment      # §9完整结构，文件在本operation

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapSourceComplete:
    record_version: int                 # 固定1
    operation_id: str
    approval_digest: str                # approval.json字节SHA
    source_identity_digest: str
    contract_content_digest: str
    source_cutoff_trade_date: date
    month_start: date
    month_end_exclusive: date
    attempt_id: str
    query_scope_digest: str
    selected_dates: tuple[date, ...]
    row_upper_bound: int
    trade_date: date
    approved_rows: int
    actual_rows: int
    fragments: tuple[StkFactorProBootstrapFragmentRef, ...]
    fragments_manifest_digest: str
    schema_content_digest: str           # Raw schema
    date_content_sha256: str             # 筛本日后261列业务内容SHA
    date_content_version: int            # 固定1，即§8.1算法
    close_reason: Literal["next_date", "eof"]
    next_trade_date: date | None
    source_empty: bool
    source_complete_digest: str
    completed_at: datetime               # §5.4 aware Instant
```

同一片段可含多个日期。已保存批内出现新日期时，只关闭其前一个日期；批末日期暂不关闭，等下一批新日期或真正EOF。完整日期记录的固定路径为`source/dates/<YYYY-MM-DD>/source-complete.json`。按trade_date筛选完整fragments集合后，实际行数必须等于approved_rows，主键唯一/字段/日期/内容对账全部通过；按原子JSON流程保存并读回验证摘要后，才向后续发布传出。fragments按fragment_no升序，无重复且全属同attempt、本月及本operation；每个片段的min/max必须覆盖本日，且实际筛本日行数大于0，禁止仅凭min/max混入无本日行的片段。非零日期fragments非空，approved_rows=actual_rows>0、source_empty=False；next_date须满足next_trade_date>trade_date且在selected_dates，eof则next_trade_date=None。记录只允许固定本日过滤，不增加字符串SQL字段。

源0日期要求approved_rows=actual_rows=0、fragments=空、source_empty=True、close_reason=eof、next_trade_date=None，date_content_sha256为SHA256空串；只有本次selected_dates明确包含该日期、正常EOF、源计数复核为0且未触R+1时才能写。EOF还须核seen等于selected_dates批准计数之和，逐日实际计数（未出现日期补0）与批准计数完全一致；以最多31项计数字典处理，不生成全月业务行集合。正计数日完全未返回必须报导出漏行，不能在处理0源日期时跳过。已知休市且源0只形成这份完整空源事实，不制造业务文件或假事件；开市/日历未知源0仍依§10.5形成可解释覆盖结果。异常退出的空白、半日或LIMIT截断绝不生成空源事实。

本节的文件字节摘要与字段内容摘要分工固定：

| 摘要 | 统一算法及精确投影 |
| --- | --- |
| 所有`file_sha256`、approval_digest、JSON引用摘要 | 对最终保存的文件字节计算SHA-256。JSON采用UTF-8、ensure_ascii=False、sort_keys=True、separators=(",", ":")、allow_nan=False，末尾一个换行；日期/时间先按§5.4转换。不是对反序列化对象再次序列化后核字节。 |
| source_identity_digest / kind=stk_factor_pro.bootstrap_source_identity | 同§5.4.2的content_digest外层；value固定host、port、database、schema、table、columns及contract_content_digest；columns保持白名单顺序，每项name/type/nullable，不自动把不同数据库源类型当同一类型。 |
| query_scope_digest / kind=stk_factor_pro.bootstrap_query | value固定approval_digest、source_identity_digest、contract_content_digest、source_cutoff_trade_date、month_start、month_end_exclusive、selected_dates、row_upper_bound；日期ISO，selected_dates升序去重。不得含attempt/时间或随意减少日期。 |
| fragments_manifest_digest / kind=stk_factor_pro.bootstrap_fragments | value为fragment_no升序数组；每项含fragment_no、attempt_id及fragment的§9全部固定字段，observed_schema按列顺序。这里是文件追溯，路径/attempt必须参与，不能套业务范围摘要的“忽略路径”规则。 |
| source_complete_digest / kind=stk_factor_pro.bootstrap_source_complete | value为SourceComplete除source_complete_digest和completed_at外全部字段，fragments以fragments_manifest_digest代替；其他计数、范围、close_reason/next_trade_date均保留。日期ISO；内容中不直接出现float。 |
| fragment.content_sha256、date_content_sha256、候选/正式业务内容SHA | 严格采用§8.1版本1：固定261字段顺序、当前层日期表示、按(ts_code,trade_date)升序序列化行并计算SHA。片段算整个片段，完整日算筛出的本日；空集为空串SHA。两者不因都叫content而互相比。 |

以上kind统一调用现有`contract_registry.content_digest`，不能另造json/hash helper改变算法。SourceComplete的schema_content_digest必须等于既定Raw schema；读取记录时核固定路径、完整结构、operation/批准/来源/合同及记录摘要。完整源实际用于候选重建或业务文件恢复时，才进一步核引用片段字节、261列及本日行数/内容。两层业务文件已完成、仅补统计时，依据原完整源记录、两层完成事实和当前正式文件身份，不重复读取源片段261列；缺失或不匹配仍须停止，不能只因文件存在就相信。首次原子写入后不原地改写已有效日源记录；同operation发现相同路径已有不同内容即停止，不能覆盖后悄悄改变被引用事实。

#### 10.3.1 完整日同步回调与资源收尾

on_complete_date由正式主入口在当前调用线程创建并传入，内部闭包持有已经核验的approval、当月coverage inputs及同一个主要DuckDB连接，不再创建线程、进程、队列、连接或业务配置。它是bootstrap内部的逐日处理接口，与下载组件的进度通知回调不同；异常不能吞掉继续导出。

固定调用顺序为：保存/读回当前批片段→判定完整日期→保存/读回SourceComplete→同步调用on_complete_date(source_complete)→函数逐日处理并返回DateResult→验证返回值→才继续下一完整日期或下一批fetch。回调负责：完整日源核验→本日Raw候选及校验→Raw逐文件提升/读回→从这份最终Raw生成Silver候选及校验→Silver提升/读回→§10.5 evaluate/write覆盖结果。两层源0且无旧目标的分支不生成空业务文件，照前述DateResult规则返回。批内可有多个完整日期，必须按日期从早到晚逐个调用；末日期未关闭不回调。export返回的complete_dates仅表示日源已完整保存，正式导入完成还必须取得DateResult及两层事实，不能混为一谈。

逐日处理函数固定为以下内部接口，闭包只完成依赖绑定，不再实现第二份发布流程；所有根路径是主入口已核验的内部依赖，不是运营输入。

```python
def process_stk_factor_pro_bootstrap_complete_date(
    connection: DuckDBPyConnection, *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    source_complete: StkFactorProBootstrapSourceComplete,
    inputs: StkFactorProBootstrapCoverageInputs,
) -> StkFactorProBootstrapDateResult: ...

def read_stk_factor_pro_bootstrap_source_complete(
    connection: DuckDBPyConnection, *, staging_root: Path,
    approval: StkFactorProBootstrapApproval, trade_date: date,
) -> StkFactorProBootstrapSourceComplete | None: ...

def write_stk_factor_pro_bootstrap_source_complete(
    connection: DuckDBPyConnection, *, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    record: StkFactorProBootstrapSourceComplete,
) -> StkFactorProBootstrapSourceComplete: ...
```

source读函数仅固定路径不存在时返回None；已有记录缺字段/坏摘要/引用结构损坏必须抛错，不得伪装成未下载；读固定记录不隐式对全部片段做261列对账。写函数首次保存前按已保存片段和本日关系核验完整结构与内容，再原子写入并调用同一读函数返回，不使用“写成功即可信”的捷径。process只处理原导入/原恢复，确需候选重建或业务文件恢复时显式核完整源内容；同连接、同operation且稳定文件身份下，按§17.8.3复用整片段已通过的完整核验；每日本日过滤、行数及内容仍检查，成本纳入§10.4。主入口对尚未合法补数的已完整日源调用该process；原两层完成记录与正式文件一致时仅核事实/身份并补统计，不重读261列。已有合法current_publication的日期仅走§10.5.6当前结果/本地复算，不能重新交给process或沿旧Prod源重建候选。正常全新导出时回调仍持有当前月只读事务，导出与本地发布不并行；预算包含事务内本日转换/校验/发布等待。依现有[psycopg2游标合同](https://github.com/psycopg/psycopg2/blob/master/doc/src/usage.rst)，named cursor固定without hold；不为回调提交事务、改withhold或引入来源锁。

覆盖准备发现按合同可判定的输入无效时，按§10.5.2、§17.8.4记录对应依据未知并正常返回，继续合法导入；不能把这一分支抛成统计异常。除此之外，真实回调/转换/写入/统计异常立即停止领取下一日期和fetch，不自动重试数据库、不把本地写失败当源错误重发。try/finally先关闭named cursor及控制cursor，再由既有connect_readonly_transaction执行rollback和close；本地主要DuckDB连接由唯一主入口finally关闭。清理阶段的异常不得覆盖最初业务异常，应作为附加错误记录；若本来正常而关闭失败，整体按失败结束。已经落盘的完整日源和已发布文件保留，统计失败不回滚业务文件；下一次按§10.2实际剩余工作分类处理。中断在半日时不回调半日，中断在Raw/Silver之间只保留已完成层。所有JSON/明细文件按临时文件、fsync、同文件系统replace、父目录fsync、读回顺序，不写半个最终记录。

例：片段1含A日5000行；片段2含A日500行+B日4500行；两片段保存并读回后，A完整记录同时引用片段1、2，仅筛A日得到5500行。B须等后续片段见到C或真实EOF才能关闭，不能只因片段2已存便发布B。完整A可立即进入本日候选/Raw/Silver逐文件发布，不要求B或整月完整。批准0行日期只保存明确空源结论，不制造正式空文件/假物化，也不借此删除原有文件。

### 10.4 bootstrap中断、目标冲突与最小验收

完整日源用于候选重建或业务文件恢复时，必须核原批准输入/来源身份/合同及源截止、维护约定仍适用、引用片段全部存在且指纹内容匹配、日行数和完整业务字段读回通过。随后从其Raw源重建候选并沿既有逐文件意图恢复；事件写成功与否不是完整源成立条件。仅本地统计按§10.2不要求Prod窗口继续有效，核不可变原导入事实及当前文件对应的原导入或合法补数依据；无依据或不匹配则不产生当前有效结论，不为每日期重新读取源片段或复做261列对账。已合法补数的日期只准更新当前统计，不再进入旧Prod源恢复/提升分支。同operation重执行不得改写已被完整日期引用的旧attempt片段，原完整日记录不可变；当前attempt只写新片段和此前未完成日期的完成记录。新的operation不得扫描或悄悄接用旧operation。

当前日未关闭、查询超限、超时、schema/类型/计数变化或游标断开：不发布该未完整日期；获准再执行时在对应批准月内按尚需日期数组整日重读。不能按最后code、OFFSET、fragment编号接读，不因已读了某股而跳过；已完整日源即使尚未发布可直接核验复用。已经提升Raw而未完成Silver，按照§8.0从核验后的正式Raw生成Silver。

首次bootstrap没有旧文件直接生成；已有目标仅可确认内容等价而不覆盖。已有不同目标一律停止，交管理员单独获准的修复步骤；本bootstrap入口不支持覆盖不同目标，不能给执行参数增加任意overwrite开关。恢复时自身已提升、意图尚未记完成的情况照既有目标/候选指纹读回补事实；旧完整源不得覆盖后来合法修改的正式文件。

bootstrap恢复沿同一获准operation的逐文件记录，独立于§8的Tushare失败重下规则。以下两类记录为frozen dataclass，读写位置固定`publication/<YYYY-MM-DD>/<raw|silver>/intent.json`及`complete.json`，候选位置固定`candidates/<YYYY-MM-DD>/<raw|silver>/part-000.parquet`；相对路径均在原operation内，正式目标由日期/层按paths复算，不接受记录任意指定目标。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapPublicationIntent:
    record_version: int                 # 固定1
    operation_id: str
    approval_digest: str
    trade_date: date
    layer: Literal["raw", "silver"]
    source_complete_digest: str
    raw_file_sha256: str | None         # Silver绑定生成它的最终Raw；Raw为None
    mode: Literal["reuse", "replace"]
    prior_file_sha256: str | None
    candidate: StkFactorProFragment
    expected_file_sha256: str
    intent_digest: str
    created_at: datetime

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapPublicationComplete:
    record_version: int                 # 固定1
    operation_id: str
    approval_digest: str
    trade_date: date
    layer: Literal["raw", "silver"]
    source_complete_digest: str
    intent_relative_path: str
    intent_file_sha256: str
    intent_digest: str
    actual_file_sha256: str
    actual_rows: int
    schema_content_digest: str
    content_sha256: str
    content_version: int                # 固定1
    audit: StkFactorProFileAudit
    verified_at: datetime
```

audit持久化时显式序列化§9.2全部字段；path必须等于按日期/层复算的正式路径，observed_schema保持261字段顺序，comparison的完整结构和changed_field_counts按合同字段顺序保存，不把对象repr或passed=True当成完整审计。diagnostics_path为None或本operation受控相对路径；读回转回内部Path，拒绝旧run/任意路径。complete必须actual_file_sha256=expected，actual_rows=audit.row_count，audit.file_sha256=actual，audit.passed=True，schema/content与本次实际读回一致。Silver意图中的raw_file_sha256必须与该日当前Raw完成事实/实际文件一致，防止由旧Raw生成的Silver被当成最新。

intent_digest统一为kind=stk_factor_pro.bootstrap_publication_intent的content_digest，value固定operation_id、approval_digest、trade_date、layer、source_complete_digest、raw_file_sha256、mode、prior_file_sha256、candidate的全部§9字段、expected_file_sha256；时间及intent_digest自身不参与。候选内容/字节摘要仍为§10.3统一算法，不用intent摘要冒充候选SHA。reuse只在正式文件已通过完整业务对账且与本次源生成候选内容等价时使用，prior非空且expected=prior；replace则expected=candidate.file_sha256=candidate_audit.file_sha256；其中candidate_audit必须是原完整检查的不可变结果，不能在描述候选时把变化后的文件SHA重新认作已校验SHA。reuse的candidate仍绑定原候选检查SHA，expected/prior则绑定已通过完整检查的正式目标SHA，二者可以因Parquet表示不同而不同。首次创建intent时，replace必须prior=None且目标不存在；已有不同目标一律停止，批准结构不支持覆盖开关或口头批准分支。恢复只接受原intent的prior/expected状态，不能补写新prior授权覆盖。

固定持久化顺序为：候选完整保存并校验，冻结原candidate_audit.file_sha256→描述候选并确认描述SHA仍等于原检查SHA→核当前目标prior及批准/活动任务/维护条件→保存intent前再核原候选SHA及目标身份→原子保存并读回intent→提升前再次核候选SHA、目标身份及空间→同文件系统replace或等价reuse→正式文件完整读回→原子保存并读回complete。任一候选身份变化必须在正式替换前停止，不得以正式读回失败代替写入前拒绝；准确分支及恢复见§17.8.1。intent一旦落定不可原地修改，新候选不得覆盖已被该意图引用的文件；意图/完成记录的文件字节SHA用§10.3标准JSON规则计算。源0且无两层文件时不造这两类记录，由SourceComplete明确证明空导入。

读写方法同样在既定bootstrap模块，接口如下；写函数必须先验证记录与当前实际文件/校验事实匹配，保存后调用读方法核相同摘要。read返回None只表示对应固定文件确实不存在，记录存在却损坏一律抛错；有complete却无intent也抛错。它们均不连接Prod，不因一个不存在记录自动写入另一个记录。

```python
def read_stk_factor_pro_bootstrap_publication(
    *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    trade_date: date, layer: Literal["raw", "silver"],
) -> tuple[StkFactorProBootstrapPublicationIntent | None,
           StkFactorProBootstrapPublicationComplete | None]: ...

def write_stk_factor_pro_bootstrap_publication_intent(
    *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    record: StkFactorProBootstrapPublicationIntent,
) -> StkFactorProBootstrapPublicationIntent: ...

def write_stk_factor_pro_bootstrap_publication_complete(
    *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    record: StkFactorProBootstrapPublicationComplete,
) -> StkFactorProBootstrapPublicationComplete: ...
```

恢复先核批准/完整日源/受控路径/意图摘要。正式目标已经等于expected时，按源或当前最终Raw重建必要expected关系并重新读回§9对账，再补complete；候选已被replace移走不构成失败。正式目标仍等于prior、候选仍存在且等于expected时，才可沿原意图继续提升、fsync、读回和complete。目标既不是prior也不是expected、原记录不明或完整日源已失效时停止；不能登记新的prior绕过外部改写。两层已有有效complete且正式身份未变时复用完整对账事实，不重复从Prod读取，且不对Raw自身比较填零值；首次恢复或实际文件身份变化按上述分支重新核验。Raw已完成而Silver未完，核当前合法Raw身份后由它生成Silver，继续同样规则。这里只恢复独立bootstrap，不授权任何Tushare失败run复用下载源。

预算继续复用已确认5000行估算（约9.94MiB净字段、128MiB工作空间/256MiB余量），不把估算当进程硬限制；一批源对象、显式列数组和写入缓冲的短暂共存纳入估算。每月事先给出批准日计数之和、R、261字段行宽估算、预期5000批次、日/两层文件数量、单语句超时和剩余空间。按§17.8.2的纯内部预算、设备归并及强制检查时点执行；明细SELECT前必须确认能容纳尚需保留的源、当前日期两层候选和DuckDB临时开销，中断续跑及最终统计也在预算内，不只算最终文件。保留完整日源所需空间随批准范围变化，不自动删除旧源来腾空间。

测试落点：`test_stk_factor_pro_candidates.py`、`test_stk_factor_pro_checks.py`、`test_stk_factor_pro_bootstrap.py`。均临时文件/隔离DuckDB及假Prod游标，无真实批量读库。

| 必须证明的边界 | 独立小样本与断言 |
| --- | --- |
| 类型/日期 | HTTP Decimal('0.1')、int、None、负指标正常；Prod float/date正常；bool、字符串数字、datetime、YYYY-MM-DD源日期、20260230、NaN、Inf、overflow及非零下溢各自明确拒绝，不能变NULL继续 |
| 精确对账 | 0.1转换后通过；NULL/NULL通过，NULL/0及任一末尾业务字段变化失败；缺键与多键同数量抵消仍失败；重复键失败；不因合法负数或少股票失败 |
| Prod全量范围 | 早于2020的日期、退市股票均规划/导入；人为缩窄源实际首尾、漏月或首次漏源日期均拒绝；cutoff不能截掉已有日期。源原有缺日/缺股只记录，不误报为导出漏行，不触发Tushare历史补采；实际导出行数少于来源计数仍失败。 |
| Silver来源 | Raw5000/Silver4800、本轮U4800，期望Silver5000；历史一天两股中只刷新一股，另一股261字段不变；不等待其他历史日期完成 |
| 5000与完整日 | 5000+500跨批同日，第二片段另含下一日；本日完整记录引用全部片段并按日筛选；未关闭日期绝不发布；0行不造文件 |
| R+1 | R-1、R、R+1行；R行真实EOF才正常，R+1触限先停止，不能用超限行关闭当前日；批准计数不符即停；此前完整日期保留 |
| SQL安全/只读 | 字段/表固定；日期/数组/limit/timeout值绑定；named cursor、5000、关闭/rollback；反例抓fetchall、OFFSET、普通cursor明细、系统字段/任意路径/未知输入参数 |
| 失败恢复 | 完整日源后退出可0次远程明细重读；半日片段须整日重读；Raw已提升Silver未成从当前合法Raw生成；仍需来源/业务文件恢复而窗口过期、片段损坏/正式目标后改均停，不旧源覆盖；全部文件已完成仅本地统计不因Prod窗口过期拒绝，也不得发schema/计数/样本请求 |
| 完整日回调及持久记录 | 同批多日期按早到晚回调；半日不回调；完整日记录含全部片段，字节SHA/内容SHA混用会失败；同operation已完整记录不得改写。回调在Raw后、Silver后、统计写入分别抛错，均不继续fetch，游标关闭/事务rollback/连接关闭，保留已成文件并可按相应事实重入；清理异常不能掩盖原始失败 |
| 性能与真实边界 | 复用批准小响应/既有schema证据作最小来源交接；不为5000行估算去读5000行或全历史；批次1/5000/跨日边界用小夹具替换批量常量测试；记录正常/恢复/最后对账的读写和SQL数量 |

### 10.5 在bootstrap中利用本地数据统计缺口

本节是已确认的实施方式：不再把Prod全历史股票覆盖审计作为bootstrap前置；在忠实导入过程中，用已经落地的数据和DG本地依据计算缺口。§10.1～10.4的来源边界、按月按日源计数、261字段/主键对账、R+1、5000行、来源维护、目标冲突和恢复规则继续有效。必要源计数证明有没有导出漏行，不计算市场应有股票；不能以取消覆盖预审为由删除传输校验，也不能再在Prod联表扫描全部技术因子、生命周期和停牌来预先计算缺口。正式补数完成后，按§10.5.6更新同一operation的当前覆盖结果和汇总；原Prod源完成、原导入完成记录保持不变，不另建修复后审计入口。

#### 10.5.1 编码位置、调用时机与复用边界

实现放在既定 defs/bootstrap/stk_factor_pro_history.py；记录类型在 defs/run_contracts/stk_factor_pro.py，受控路径在 defs/paths.py，测试扩展既定 test_stk_factor_pro_bootstrap.py。不新增资产、check、sensor、数据库表、配置项、远程接口或独立审计入口，不改日更/repair的放行条件。

| 既有能力 | 本节具体用法 |
| --- | --- |
| 正式日历、生命周期、身份和停牌路径及schema | 使用 paths.py 的 silver_trade_calendar_path、silver_stock_lifecycle_path、silver_stock_identity_map_path、silver_stock_suspend_daily_path，以及 asset_column_schemas.py 对应定义；不允许调用者传任意路径。 |
| duckdb_sql.py::silver_cny_stock_lifecycle_select(path) | 先验证原始生命周期文件，再取人民币股票历史区间；不能让该SQL对空键/空上市日期的过滤掩盖坏输入。 |
| 现行日线覆盖规则 | 复用上市区间、北交所开市边界、全天停牌及代码差集语义；不调用 _expected_tradable_universe_metadata 整函数，其日线文字、20条样本和重复查询不适用完整缺口清单。 |
| §5.2覆盖与就绪接口 | 本节不逐日调用 evaluate_stk_factor_pro_raw_coverage 或 suspend_d_ready_for_trade_date，不扫描全历史事件。它们继续只用于日更/repair；bootstrap按本节进行纯本地分批核验。 |
| §9、§10.3～10.4的实际文件读回 | 正常导入复用同次验证的正式Raw主键关系、行数和文件身份，不再为覆盖读取261指标列。恢复补算时只投影该日期Raw的代码、日期；正式文件本身的完整性仍按§10.4核验。 |

§5.2.1的build_stk_factor_pro_coverage_keys是本数据集两类调用共用的纯SQL函数；bootstrap准备当月原代码/DATE关系后按日期调用，不引入日更的instance/check前置。函数内部执行本节映射及集合SQL，外层不再复制一套实现或把已统一的身份码再映射一次；同一日需要两类包装时复用当前关系，至多两次有界主键集合运算，预算不能把它写成零成本或重复扫描261指标。

内部接口固定如下；均使用传入的同一个主要DuckDB连接，禁止函数内部新建连接、联网、写正式上游文件或创建Dagster事件：

~~~python
def prepare_stk_factor_pro_bootstrap_coverage_month(
    connection: DuckDBPyConnection, *,
    lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    month: StkFactorProBootstrapMonthLimit,
) -> StkFactorProBootstrapCoverageInputs: ...

def evaluate_stk_factor_pro_bootstrap_coverage_date(
    connection: DuckDBPyConnection, *,
    lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    inputs: StkFactorProBootstrapCoverageInputs, trade_date: date,
    source_complete: StkFactorProBootstrapSourceComplete,
    raw_audit: StkFactorProFileAudit | None,
    silver_audit: StkFactorProFileAudit | None,
    current_publication: StkFactorProBootstrapCurrentPublication | None,
) -> StkFactorProBootstrapDateCoverage: ...

def write_stk_factor_pro_bootstrap_coverage_date(
    connection: DuckDBPyConnection, *,
    lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    result: StkFactorProBootstrapDateCoverage,
) -> StkFactorProBootstrapDateCoverage: ...

def summarize_stk_factor_pro_bootstrap_coverage(
    *, lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    verified_import_dates: tuple[date, ...],
    verified_current_dates: tuple[date, ...],
    inputs: tuple[StkFactorProBootstrapCoverageInputs, ...],
) -> StkFactorProBootstrapCoverageSummary: ...
~~~

lake_root与staging_root是主入口在原有路径/挂载核验后解析的内部依赖，正式值来自LakeRootResource及paths.py的DEFAULT_LAKE_ROOT、DEFAULT_LAKE_STAGING_ROOT，不加入批准JSON、命令参数或运行配置；正式入口不接受任意根。隔离测试通过临时resource/内部路径注入临时目录，不修改正式默认或写正式根。这是内部函数依赖传递，不改变§10.2的运营输入禁令。

source_complete必须先按§10.3的完整日记录解析、读回引用并核身份，不能传未经验证的普通字典制造完成。初次导入传current_publication=None，两份audit必须是该日当前正式路径、passed=True，且与§10.4该日的逐文件完成事实一致；函数再次核文件身份。原源0行且尚无补数时按下文无文件分支判定，不伪造audit。正式补数后，传§10.5.6从真实物化/check及本轮发布结果核出的current_publication，两份audit须与这次发布匹配，不再要求当前文件等于原Prod导入文件；后续仅本地复算时复用其已保存的发布audit及绑定通过check，不重新计算261列，也不自行构造passed=True。原导入未完成或本次有业务文件却缺任一层有效audit时，不能制造当前完整结果。evaluate在同连接内生成差集并保存下文的明细文件，返回已含有效明细引用的完整结果；write负责校验并原子保存JSON，不接收尚不存在文件的引用。

自然月只用于复用输入与限制本地计算范围，不是新增“整月完成才发布”的门槛。每个有源数据的日期在Raw、Silver都正式提升/等价确认并读回后立即评估并保存一次本日统计；不在5000行批次边界评估。Raw已提升、Silver失败，或候选已完整但尚未发布，只保留原阶段事实；统计中的导入日期仍未完成，不能据此推算Prod缺口。

主入口的固定顺序为：§4.2维护/冲突检查与§10.2批准静态核验→逐日核原完成事实以区分实际剩余工作→prepare本月本地依据→先拒绝“已确认休市且批准源计数非0”的已知冲突。仍需来源读取/业务恢复时，再核来源窗口及必要当前源证据→构造selected_dates→按§10.3导出，并由完整日同步回调完成本日两层发布/读回、evaluate/write→月正常EOF后回调处理本月源0日期。仅本地统计时不运行导出函数、不形成selected_dates网络请求，直接对已验证两层日期evaluate/write。两分支最终均按§10.5.5检查缺失/失效结果并summarize。selected_dates须包含尚未形成完整空源事实的0行日期，不能只以正行数选择日期；已完整日期沿原规则复用，不为统计重复导出。确认休市且源0只记录空源完成，不另写覆盖结果或业务文件。

#### 10.5.2 本地依据、日期范围与无法判断的条件

StkFactorProBootstrapCoverageInputs是frozen dataclass，固定字段为 operation_id:str、month:StkFactorProBootstrapMonthLimit、natural_dates:tuple[date,...]、open_dates:tuple[date,...]、closed_dates:tuple[date,...]、calendar_unknown_dates:tuple[date,...]、basis_files:tuple[StkFactorProBootstrapBasisFile,...]、unknown_by_date:tuple[tuple[date,tuple[str,...],str],...]、input_digest:str。每个日期集合升序去重；open_dates、closed_dates、calendar_unknown_dates互斥，三者并集等于natural_dates。这里只保存小型身份、日期及问题摘要，业务行保存在同连接的受控临时关系中，不放进Python对象或JSON。

StkFactorProBootstrapBasisFile固定 kind:Literal["calendar","lifecycle","identity","suspend"]、trade_date:date|None、file_sha256:str|None、schema_content_digest:str|None、row_count:int|None、valid:bool。前三类trade_date为None，停牌为对应日期；路径从kind/日期按正式paths复算，不从记录读取任意路径。缺文件时摘要/行数为None且valid=False；有文件但校验失败不能记录valid=True。unknown_by_date中的kind只取上述四值、去重升序，末项中文原因仅作说明，不用可增长的原因字符串驱动程序分支。

每月输入准备只读取本月裁切范围内的本地文件。日历、生命周期及身份小表在同一执行内文件身份未变时读入连接临时表后复用；最终停牌文件按本月日期一次规划，最多一个自然月，不逐股票、逐日期查询Dagster事件。每月结束释放该月临时关系；全局小表可继续复用。各输入读前后核文件身份，改变则本次受影响日期不能使用旧结论；只在本地重新准备，不重新导出Prod。

| 输入 | 必须执行的实际核验及判定 |
| --- | --- |
| 日历 | 正式Silver schema含exchange VARCHAR、trade_date DATE、is_open BOOLEAN、pretrade_date DATE；只采用SSE。以批准源首尾之间的完整自然日期序列为主表，检查每日恰好一行、日期可解析及is_open非NULL，再分类开市/休市/未知。缺日期、重复或冲突标志对应日期记未知，不能从“没有因子行”反推休市。完整日历不可得时保留整段未知，不能把工作日当交易日。 |
| 生命周期 | 固定正式silver_stock_lifecycle文件可读、现行完整schema及必需字段非空、代码唯一、curr_type='CNY'且is_cny_stock为True、DATE上市/退市及非倒置区间等必要物理规则通过，且读前后身份一致时，接受这份正式历史事实作为本次统计依据，再使用现行人民币股票select。不按当前list_status或日线自己的最早日期裁剪，不允许用silver_stock_basic等当前上市快照替代。文件缺失、为空、schema或必要规则失败则受影响日期未知；不附加未定义的人工审批或事件检查。该资产没有“全部历史证券已收录”的覆盖起止字段，不能虚构该字段，或仅凭min(list_date)/schema通过宣称绝对全市场完整；报告固定说明按本次DG正式生命周期事实统计，而非独立证明来源从未遗漏某只历史证券。 |
| 身份映射 | 使用正式silver_stock_identity_map；核现行schema、source_ts_code全局唯一、latest_ts_code存在于生命周期、valid_from非空及valid_to区间合法等现行必要规则。按source_ts_code及业务日期匹配，条件为 d>=valid_from AND (valid_to IS NULL OR d<valid_to)。self与旧码映射完全同样处理，不无条件self兜底。参与比较的原始代码日期匹配0条或多条，对应日期记未知并记录数量/至多20个原代码样本，不取第一条、不临时读取Prod映射。 |
| 最终停牌 | 只读silver_stock_suspend_daily的正式日文件，不另读confirmed或Raw自行合成。固定正式文件可读、现行完整4列schema、非空代码、DATE恰为本日，业务键(ts_code,trade_date,suspend_type,COALESCE(suspend_timing,''))唯一，suspend_type非空且仅S/R，按现行停牌时段规则校验，通过且读前后身份一致时接受该正式最终停牌事实；合法时段非空仍是日内停牌。符合这些条件的0行文件表示没有停牌，不附加未定义的生成证明或逐日事件门槛；缺文件、无法读回、坏schema或日期错位不能当0停牌。不调用写入/修正停牌函数，也不声称本次另外核实了源端全部历史停牌。 |

代码合法性也是准备阶段的必要规则：生命周期ts_code、身份source_ts_code/latest_ts_code及最终停牌ts_code均复用本数据集现行`[0-9]{6}\.(SH|SZ|BJ)`合同，不只检查非空。错误归入实际出现问题的lifecycle/identity/suspend依据；影响日期、依赖传播及异常界限按§17.8.4处理。不得删除无效代码后继续宣称该依据有效。

schema必须直接引用SILVER_TRADE_CALENDAR_SCHEMA、SILVER_STOCK_LIFECYCLE_SCHEMA、SILVER_STOCK_IDENTITY_MAP_SCHEMA、SILVER_STOCK_SUSPEND_DAILY_SCHEMA，不重新维护另一份列定义。必要物理SQL逐项对照checks/calendar_checks.py、stock_lifecycle_checks.py、stock_identity_map_checks.py、suspend_d_checks.py中的同名资产现行检查，移到本连接本月关系上执行；不调用这些会自行创建连接的Dagster装饰函数，不因本节只列摘要而漏掉其主键、必需非空及域规则。涉及其他资产、全历史事件或来源重新下载的步骤均不进入本节。

输入只作为覆盖依据，不是传输成功门槛。已确认休市而Prod有本日源行，属于原规则中的已知日期冲突，停止处理，不能把它归为覆盖未知后发布。日历缺失或尚不可判断不等于已确认休市：源DATE、范围及传输校验有效的行可忠实导入，覆盖记“是否开市无法判断”；不伪造开市标志、动态分区或物化事件。分区注册只针对已确认开市日期，未确认部分保持未确认，正式事件补记仍另行授权。

自然日期范围严格为approval.start_trade_date至end_trade_date，不默认从2017开始，也不扩展至执行当天。该范围内源计数0的开市日同样进入统计；首尾以外例如22、23日可说明不在本次范围，但不能混入已判定缺口总数或自行追加远程查询。已确认休市且源0的日期只在日历分类中汇总，不制造股票覆盖结果或正式空文件。

#### 10.5.3 两种差异的判定及集合SQL

先完成“来源确实导入”的核对，再判断“应有股票是否齐备”，二者分别记录：

- 本期首次导入或等价复用的完整日期，源批准计数、当前源复核计数、实际导出/片段读回行数、正式Raw行数及Silver行数必须一致；同时通过§9.2完整字段/主键双向对账，不能只比数量。任一导出漏行、重复、值错或目标身份冲突都停止当前流程，不用市场缺口解释同步错误。
- 上述导入核对通过后，以实际正式Raw的唯一物理代码/日期为输入，只为本地覆盖统一身份。Raw及Silver本身的源代码、业务值和行数不因统计而改写或去重。一个身份有两个源别名时，物理行数/物理代码数可以大于实际身份数，必须分别保留。
- 确认全部应有依据有效后，上市集合按 list_date<=d AND (delist_date IS NULL OR d<delist_date)，北交所不早于2021-11-15；在同一有效身份规则下统一上市、停牌及实际三侧，去重后仅扣除S且suspend_timing为NULL的全天停牌，日内停牌仍应有。

连接中的输入临时关系为listed_keys(trade_date DATE,ts_code VARCHAR)、full_suspend_keys/actual_keys（同列），代码保持各自产生者原值。listed先按生命周期与北交所日期过滤，再由§5.2.1纯函数对三侧按本日映射一次；未匹配/歧义不得INNER JOIN静默丢行。以下SQL中的listed/full_suspend/actual是该函数已统一身份后的内部关系，不再交回输入映射第二次。任何一侧不足时不运行已知覆盖分支；函数把missing/extra结果登记为§5.2.1固定关系供调用方保存明细。

对当前日期的这些小关系，以DuckDB SQL一次生成受控临时expected、missing、extra关系，后续数量和明细从同一结果读取，不为输出三个计数重算全套输入：

~~~sql
-- 三侧均已限定当前日期、统一身份并去重。
CREATE TEMP TABLE stk_factor_bootstrap_expected AS
SELECT trade_date, ts_code FROM listed_keys
EXCEPT
SELECT trade_date, ts_code FROM full_suspend_keys;

CREATE TEMP TABLE stk_factor_bootstrap_missing AS
SELECT trade_date, ts_code FROM stk_factor_bootstrap_expected
EXCEPT
SELECT trade_date, ts_code FROM actual_keys;

CREATE TEMP TABLE stk_factor_bootstrap_extra AS
SELECT trade_date, ts_code FROM actual_keys
EXCEPT
SELECT trade_date, ts_code FROM stk_factor_bootstrap_expected;
~~~

关系名均为代码固定内部标识，日期/文件引用按既有绑定和路径白名单生成；处理下一日期前删除本连接的上述临时表，不创建持久数据库表。missing/extra完整明细用COPY显式投影trade_date、ts_code，ORDER BY trade_date,ts_code写本地Parquet，不用fetchall拿回全市场历史。集合去重语义及COPY写法核对[DuckDB集合运算](https://duckdb.org/docs/stable/sql/query_syntax/setops.html)与[COPY查询结果](https://duckdb.org/docs/stable/sql/statements/copy.html)，具体字段和业务预期仍以上述本地合同及独立样本为准。

计数定义唯一：expected_count=expected行数；actual_count=统一后actual唯一身份数；matched_count=expected与actual交集数；missing_count=missing行数；extra_count=extra行数。必须同时满足 expected_count=matched_count+missing_count、actual_count=matched_count+extra_count。源物理行数和Raw物理代码数另列，不能代替matched_count，也不能拿extra抵消missing。应有A/B、实际A/C的独立样本必须得expected=2、actual=2、matched=1、missing=1、extra=1。

上述A/B/C仅是说明用简称，测试Raw代码必须符合源合同。独立夹具可固定A=000001.SZ、B=600000.SH、C=000002.SZ，三者生命周期/有效映射完整，其中C有本日全天停牌事实；来源及DG都含A/C，故应有A/B、缺B、额外C。预期代码和数量用字面值独立指定，不能调用待测覆盖函数生成expected。该夹具证明集合规则，不声称这些股票现实中某日发生了这一情况。

首次导入且current_publication=None时，源0行日期只有在对应查询已正常EOF、未触R+1、所选日期包含该日、源批准/当前计数均为0且来源条件仍有效时，才能按§10.3保存无片段的完整空源事实。正式Raw/Silver均不存在时，actual关系明确为空，不生成两层空文件：开市且依据有效时应有N个身份即缺N个；日历未知时可确认原源空/导入完成，但覆盖仍未知；确认休市时只作日历分类。该首次分支已有任一目标文件时先按§10.4处理冲突，不删文件或拿旧目标冒充原源。后续正式补数已有合法current_publication时，原source_rows=0不再要求当前无文件；按§10.5.6核当前两层并计算实际集合，原空源记录保留，不能继续报“本日实际0”。月游标中断、来源变化或未取得完整空源事实仍是原导入未完成，不得伪造原源空证明。

覆盖依据未知（含准备阶段已分类的非法代码）时，不进入要求合法三侧的已知覆盖计算分支，也不调用该分支后笼统捕获ValueError。source_rows、raw_rows、silver_rows及物理代码数仍可来自已经完成的传输核对；expected/actual身份数/matched/missing/extra及coverage_complete统一为None，不猜0。记录具体缺少或无效的输入种类。缺股票、额外合法源行和覆盖未知不新增blocking check、不阻止其余合法日期导入，不自动调用Tushare补采，也不自动修复本地上游。

#### 10.5.4 逐日记录、文件与最终汇总

StkFactorProBootstrapDateCoverage及Summary按以下完整类型读写；record_version固定1，日期/计数/摘要遵守§5.4公共标量规则，未知键拒绝。不是新平台状态表，所有记录是本次既有bootstrap operation目录内的审计附件；bootstrap物理阶段没有可替代它的正式物化事件，源完成记录也不能代替正式文件已导入的结论。

~~~python
CoverageInputKind = Literal["calendar", "lifecycle", "identity", "suspend"]

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapCodesRef:
    relative_path: str
    file_sha256: str
    row_count: int

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapContext:
    operation_id: str
    approval_digest: str
    target_trade_date: date
    authorized_date_result_digest: str
    authorized_gap_input_digest: str
    authorized_missing_count: int
    authorized_missing_codes_ref: StkFactorProBootstrapCodesRef
    authorization_run_id: str

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapCurrentPublication:
    run_id: str
    trade_date: date
    raw_materialization_storage_id: int
    raw_check_event_storage_id: int
    silver_materialization_storage_id: int
    silver_check_event_storage_id: int
    raw_file_sha256: str
    silver_file_sha256: str
    silver_source_raw_sha256: str
    contract_content_digest: str
    processing_version: str

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapPublicationBatch:
    publications: tuple[StkFactorProBootstrapCurrentPublication, ...]
    incomplete_dates: tuple[date, ...]
    unchanged_dates: tuple[date, ...]

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapDateCoverage:
    record_version: int
    operation_id: str
    approval_digest: str
    trade_date: date
    source_rows: int
    raw_rows: int
    silver_rows: int
    raw_physical_code_count: int
    source_complete_digest: str
    raw_file_sha256: str | None
    silver_file_sha256: str | None
    import_complete: bool
    source_empty: bool
    current_publication: StkFactorProBootstrapCurrentPublication | None
    is_open: bool | None
    basis_files: tuple[StkFactorProBootstrapBasisFile, ...]
    unknown_input_kinds: tuple[CoverageInputKind, ...]
    input_digest: str
    identity_unmapped_count: int | None
    identity_ambiguous_count: int | None
    identity_unmapped_sample_codes: tuple[str, ...]
    identity_ambiguous_sample_codes: tuple[str, ...]
    expected_count: int | None
    actual_count: int | None
    matched_count: int | None
    missing_count: int | None
    extra_count: int | None
    coverage_complete: bool | None
    reason: str
    missing_codes_ref: StkFactorProBootstrapCodesRef | None
    extra_codes_ref: StkFactorProBootstrapCodesRef | None
    missing_sample_codes: tuple[str, ...]
    extra_sample_codes: tuple[str, ...]
    evaluated_at: datetime

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapCoverageSummary:
    record_version: int
    operation_id: str
    approval_digest: str
    start_trade_date: date
    end_trade_date: date
    evaluated_at: datetime
    known_open_dates: tuple[date, ...]
    known_closed_dates: tuple[date, ...]
    calendar_unknown_dates: tuple[date, ...]
    imported_dates: tuple[date, ...]
    source_empty_dates: tuple[date, ...]
    import_pending_dates: tuple[date, ...]
    known_coverage_dates: tuple[date, ...]
    coverage_unknown_dates: tuple[
        tuple[date, tuple[CoverageInputKind, ...], str], ...
    ]
    gap_dates: tuple[date, ...]
    verified_source_rows: int
    verified_raw_rows: int
    verified_silver_rows: int
    current_raw_rows: int | None
    current_silver_rows: int | None
    current_files_unverified_dates: tuple[date, ...]
    date_result_digests: tuple[tuple[date, str], ...]
    expected_count_known_dates: int
    actual_count_known_dates: int
    matched_count_known_dates: int
    missing_count_known_dates: int
    extra_count_known_dates: int
    all_coverage_determined: bool
    total_missing_count: int | None
    all_expected_present: bool | None
~~~

| 字段 | 固定合同 |
| --- | --- |
| record_version、operation_id、approval_digest、trade_date | 固定版本、本operation及其不可变批准摘要、本日DATE；所有引用均核同operation和日期。 |
| source_rows、raw_rows、silver_rows、raw_physical_code_count | 非负精确int。source_rows始终取原Prod完整日源计数；后三项取最近一次已核验的当前正式两层及Raw物理代码数量。current_publication=None的初次忠实导入要求source_rows=raw_rows=silver_rows；有有效补数发布依据时只要求当前Raw/Silver行及主键对应，不要求再等于source_rows。旧结果身份失效时不得当成当前数量。 |
| source_complete_digest、raw_file_sha256、silver_file_sha256 | 完整原日源记录摘要必填且不改写；后两项是当前正式两层SHA，不是原导入文件SHA。原空源且尚无补数时可均None；正式补数后即使source_rows=0，两项也必须非空且对应current_publication；不能用候选摘要冒充正式目标。 |
| import_complete、source_empty、is_open | import_complete固定True，表达原忠实导入已完成，不因后来补数失败抹去；source_empty仅代表原Prod已核验0源，补数后仍保留True，不再推出当前没有文件。is_open为True或None。确认休市且0源不产生此记录，休市有源是冲突。原导入未完成日期不能由补数记录伪造完成，由汇总明确列出。 |
| current_publication | 初次导入为None；正式补数后保存上面完整类型。run_id来自真实获准补数任务；四个id均为对应真实事件记录的正精确storage_id，两个check字段不是check执行id、不是目标物化id；各check的target_materialization_data须绑定本类型对应的物化。实际文件SHA、Silver来源Raw SHA、契约及处理版本必须匹配。类型不能从运营传入的passed=True或随意id构造，核验步骤见§10.5.6。 |
| basis_files、unknown_input_kinds、input_digest | 月Inputs包含本月全部必要文件；逐日result只保留日历/生命周期/身份三份全局引用及本日停牌引用，不能复制其他日期停牌引用。有限输入种类不作为下载器错误码。摘要投影见下文，不含时间或attempt计数。 |
| identity_unmapped_count、identity_ambiguous_count及各自sample_codes | 对本日上市/停牌/实际三侧参与代码日期的去重并集统计映射0条/多条数量，样本按原代码升序最多20条；映射文件本身无法核验时数量None、样本空并记identity未知，能核验时0必须明确。已知覆盖结果要求两数均0；无映射不能当0股票。 |
| expected_count、actual_count、matched_count、missing_count、extra_count | 已知覆盖时全部非负int并满足上述两项算术；未知时全部None，不混合拼接来自旧输入的数值。 |
| coverage_complete、reason | True仅表示本日已确认开市、依据齐全且missing=0；False表示依据齐全但missing>0；None表示日历或其他依据不足。reason为中文说明，不用字符串分支，不把extra>0自动改成缺失或删除源行。 |
| missing_codes_ref、extra_codes_ref、missing_sample_codes、extra_sample_codes | 已知非零差集保存本日完整明细引用；引用固定relative_path/file_sha256/row_count。0差集不创建文件、ref=None，样本代码升序最多20项；未知时引用None、样本空，靠nullable计数区分未知与0。 |
| evaluated_at | aware datetime，JSON固定+08:00；不进入input_digest。 |

BootstrapContext八字段均必填且拒绝未知键：operation_id/authorization_run_id为已核安全标识/真实run_id，target_trade_date为原T；三个digest均为64位小写SHA-256，authorized_missing_count是正精确int，authorized_missing_codes_ref按本operation受控路径核schema/行数/摘要且row_count等于该正缺失数。authorization_run_id始终指首次持久化有效开始授权观察的run，读回可在原run或后续获准重执行核实，不随历史d或retry更换；核既有授权不要求读已被更新的旧result。PublicationBatch三组日期升序唯一且互斥：publications为本批两层/check完成；incomplete_dates为当前两层已知无效、或触及发布后无法确认；unchanged_dates为未触及或目标未变且原依据仍有效的日期。未触及但发现原事实已失效时仍列incomplete，不能宣告有效；三组共同解释原批准交集内需文件日期，不能将仅未执行等同文件失效。

本节补充§5.4.2的bootstrap专属摘要，统一调用同一content_digest的外层record_kind/record_version/value，不另写算法：月摘要kind固定stk_factor_pro.bootstrap_month_basis，value按字段顺序包含operation_id、approval_digest、month_start/month_end_exclusive、natural/open/closed/calendar_unknown日期数组，以及按kind、trade_date排序的全月basis_files；日期摘要kind固定stk_factor_pro.bootstrap_date_coverage，value包含operation_id、approval_digest、trade_date、is_open、source_complete_digest、source_rows、raw_file_sha256、silver_file_sha256、source_empty及排序的本日basis_files。日期先转ISO文本，None保留null；BasisFile全部六字段参与，不能把月input_digest直接当逐日input_digest。同一日停牌改变只影响本日；全局依据改变才影响引用它的多个日期。

路径全部由paths.py从已批准operation和日期派生：coverage/<YYYY-MM-DD>/result.json；非零差集位于coverage/<YYYY-MM-DD>/input=<input_digest>/missing-codes.parquet与extra-codes.parquet，两列固定trade_date DATE NOT NULL、ts_code VARCHAR NOT NULL，主键两列，完整缺失行数必须等于missing_count，额外行数必须等于extra_count。不得在source/dates的不可变完整源记录内追加或改写覆盖结果，也不把字段加进261列业务文件。

写入顺序：核当前输入身份→临时明细COPY/读回数量和键→同文件系统原子保存明细→校验完整result结构及引用→按§5.4临时JSON/fsync/replace/父目录fsync/读回，最后使result成为当前日期的唯一结果。非零明细先于JSON，输入摘要区分复算版本；绝不先覆盖旧明细让旧JSON引用新内容。写失败不回滚已发布Raw/Silver，也不能谎称该日期统计成功；下次可在本地补算。结果只在同operation同日期替换，不能按批次/恢复次数累加。

最终summarize函数以批准首尾的完整自然日期范围和传入inputs中的已验证日历分类为主表；inputs必须逐月、无缺月地对应approval.month_limits、全部同operation，且月摘要核验通过。按固定日期路径读取当前结果、原源计数及原两层完成事实，不靠glob发现有文件日期。verified_import_dates由控制层核不可变原日源及原导入完成记录后收集；已合法补数的日期不再要求当前文件仍等于原导入SHA，也不为核原导入事实重读全部原源。verified_current_dates另外表达已核当前文件及其原导入/补数发布依据的日期；原空源且仍无文件可作为明确0行，未知或文件不匹配不得加入。正常同一执行复用§4.2唯一写入期间已取得的校验事实，不为汇总再次扫描全部指标或逐日查询事件；新执行只核必要身份与依据。两数组升序去重，均须原批准范围内、当前日期为原已完成导入日期的子集；不能以一个普通日期数组替代实际控制层核验。StkFactorProBootstrapCoverageSummary固定保存：

- record_version、operation_id、approval_digest、start_trade_date、end_trade_date、evaluated_at；
- known_open_dates、known_closed_dates、calendar_unknown_dates三个升序日期数组；完整自然日期范围必须无遗漏。日历全段不可确认时，前两数组可空但未知日期不能丢。
- imported_dates、source_empty_dates、import_pending_dates表达原导入事实；imported只能取verified_import_dates，包含已证明源0且日历未知的日期；source_empty_dates取原源0的已导入日期，后来补出行也不删除该历史事实。设C0为已确认休市且原批准源计数0的日期，固定import_pending_dates=完整自然日期集合-C0-imported_dates，防止正常休市日被算成未完成；休市有源仍是冲突。原导入未完成不能用补数覆盖结果冒充完成。
- known_coverage_dates、coverage_unknown_dates、gap_dates；known只能取verified_current_dates中当前result有效、日历及其他依据齐全的日期；不能仅因旧JSON有数值就纳入。unknown保留每日期原因；只是当前文件不可核验时，其unknown_input_kinds可为空tuple并明确文件/发布原因，不另造第五种上游输入。gap_dates必须是known且missing>0。
- verified_source_rows、verified_raw_rows、verified_silver_rows只从原完整日源及原两层PublicationComplete的行数汇总；原源0且原两层未造文件时，按已核空源事实三项取0，不要求不存在的PublicationComplete。三项相等是原忠实导入的传输证明；不能从已被补数改为5000的当前coverage.raw_rows取原导入合计，也不将它们改写成5000。
- current_raw_rows、current_silver_rows是当前正式两层的全范围合计，只在所有需导入日期原导入完成且当前文件均可核验时给出非负int，否则均为None；不把部分已知数量叫作全范围当前总数。两者按本期完整字段/不增删行规则相等，但允许不同于verified_source_rows。current_files_unverified_dates明确列出已原导入但当前文件缺失、改写无凭据、补数两层未完成等日期；这些日期归入coverage_unknown_dates，不抹去imported_dates。
- date_result_digests保存本次实际读到的每个result的(trade_date,文件字节SHA)，升序去重，绑定本次summary的逐日输入；不存在的结果由未完成/未知数组说明。使用summary作完整性或事件依据前核对应result仍相同，并核当前正式文件身份；不能仅凭旧summary中的all_expected_present=True放行。
- expected_count_known_dates、actual_count_known_dates、matched_count_known_dates、missing_count_known_dates、extra_count_known_dates：只汇总known_coverage_dates，满足两项集合算术；不能把unknown日期实际行数掺入这些分母。
- all_coverage_determined:bool、total_missing_count:int|None、all_expected_present:bool|None。仅批准范围内所有日期已确认开休市、所有需导入日期原导入完成、current_files_unverified_dates为空且所有开市日当前覆盖可判定时all_coverage_determined=True，此时total_missing_count=missing_count_known_dates，all_expected_present=(total_missing_count==0)。其他情形后二者为None，但保留已判定范围及已知缺口数，不能把部分结果命名为全范围精确总数。

summary固定写coverage/summary.json，复用上述原子JSON规则。所有日期数组升序去重；coverage_unknown_dates每项明确日期、有限输入种类及中文原因，不能只存日期而丢原因。一次最终汇总对批准范围小型记录至多扫描一遍，重试重新从现有逐日结果求和，不在旧总数上加本次增量。摘要中缺失数量是“股票＋交易日”条数，不是全范围去重股票数；本期不另做去重股票统计。若首次导入未完成，仍可形成明确标注范围/未完成日期的部分报告，不写成bootstrap已经全部完成或全历史已齐备。

#### 10.5.5 失败、恢复、输入修订与成本

| 位置/条件 | 固定动作 |
| --- | --- |
| 源游标未完整、片段/两层对账失败 | 继续原§10.3～10.4停止/重读规则；当前日不生成最终覆盖记录，不把半日算成Prod缺口。此前合法文件保留。 |
| 日源完整但候选/一层尚未发布 | 沿既有bootstrap逐文件记录恢复；两层均完成前不形成正式逐日覆盖。完整日源可复用，不为覆盖重读远程。 |
| 原导入两层完成而覆盖未保存/明细或JSON写失败 | 核当前正式文件及原日源身份后，仅本地补算并原子保存；不重新导出该完整日期，不回滚已提升文件。Tushare补数任务失败后的重新执行仍按§10.5.6全新下载，不把本行当作失败补数续用源的例外。 |
| 本日统计、源和目标及本地依据身份均匹配 | 复用本日期结果；不重算、不累加。仍在最后汇总中计一次。 |
| 只本地依据修订或原统计为未知且现有依据已可判断 | 旧覆盖结果失效，在本地重新准备输入并重算；不下载Prod或Tushare，不把旧None/0保留成新结论。没有适用依据仍返回未知。 |
| 当前正式文件因§10.5.6获准补数发生变化 | 核补数两层发布/check及当前身份，更新同一result及summary的当前部分；原导入记录/计数不变，不再要求当前行数等于原来源，也不重启旧Prod恢复。 |
| 正式目标无合法补数凭据地变化，或源批准/来源身份变化 | 先执行§10.4冲突停止规则；不能用“统计复算”绕过文件冲突，不能重设prior或更改approval。原已完成导入事实保留，当前文件无法核验时进入current_files_unverified_dates。 |
| 已确认日期有缺口或仍无法判断 | 已导入合法文件继续保留和可读，报告缺失/未知；不新增最低覆盖率，不启动补采、停牌重建、跨工程契约修改或日更任务。 |

输入读取身份变化时，当前受影响日期不保存旧结论；未完成日停止当前本地评估、重新准备该月输入后计算。全局日历/生命周期/身份文件变更使此前使用其旧身份的覆盖结果失效。主入口在最终汇总前逐月prepare，对已核当前文件日期中缺失/失效的统计调用evaluate/write；原导入分支传current_publication=None，已合法补数分支传已核实际发布引用及对应audit。然后把分别核实的verified_import_dates、verified_current_dates和逐月inputs传给summarize，不能仍只传原导入日期。不能在summarize内暗开连接、重新导出或全历史复算。summary按去重路径核依据当前身份；又有变化时将相应日期列coverage_unknown_dates、all_coverage_determined=False，日历变化则相应范围归calendar_unknown。当前文件不可核验日期排除出known_coverage_dates。下一次获准执行再局部复算，不循环到稳定，不拼新旧依据为全范围精确总数，不为各结果重复读取同一全局文件全文。

新增成本在执行前随原预算记录，且不得隐藏在“顺便统计”中：

| 成本 | 上界与拒绝/退回规则 |
| --- | --- |
| 正常本地读取 | 本月自然日期至多31；一次准备生命周期/身份/日历必要列及本月最终停牌文件。实际代码用同次Raw读回关系，统计不再读261列；不逐行Python计算、不逐日event深扫、不新增Prod查询。 |
| SQL及内存 | 设本月导入R行、生命周期L行、停牌S行，所有代码关系至多O(R+31L+S)；逐日差集只对当前d计算，不能对每个日期重新拼整月历史。沿同一DuckDB设置及临时目录，不新建全历史Python集合或新内存配置。 |
| 持久文件 | 需要统计的日期N，每日1个result，非零缺失/额外至多各1个明细，另1个summary；最终当前版本最多3N+1文件，复算历史证据另计。单日明细不超过相应应有/实际唯一身份数，不能把全部261列复制成诊断。 |
| 中断后继续 | 已有效结果仅核身份；缺失/失效统计只投影对应完整日Raw主键并读取受影响依据，预算包括本地明细重写。来源未完整的日期远程重读成本仍属原bootstrap，不因覆盖统计而省略。 |
| 最后验收 | 只读完整日期规划、源计数和逐日小记录作一遍汇总，检查两个集合算术、引用行数及未知/未完成范围；不再次扫描全部指标或跑Prod全历史缺口SQL。 |
| 预算无法满足 | 在执行前按真实日期/行数/文件及可用空间列开销，结合原源超时/R/空间上界检查；不能满足则停止或缩小本地计算批次，业务批准范围不变。不能静默丢日期、只存20条样本冒充完整缺口、以扩大Prod扫描来规避本地设计，也不自行增设资源参数。 |

精简验收仅用现有合同构造小型临时文件和独立字面预期，覆盖：A/B对A/C；应有5000、源4800且DG4800与源4800却DG4799的两类差异；同日跨5000批；合法0行停牌与缺停牌文件；已确认开市源0/半日中断/日历未知/已知休市有源；日期首尾及范围外22/23；合法负值/NULL原样保留；双别名同身份不重复；self/alias日期边界、缺映射/同source多映射；Raw已发布Silver失败不统计成功；结果写失败、重入不累加、依据改变只本地复算、统计完成不再重扫。不得为证明这些分支重跑全历史或另读5000行生产样本。实现后的最小真实来源交接与正式执行授权继续按§11.1办理，隔离用例不能宣称正式bootstrap已经通过。

#### 10.5.6 正式补数结束后更新原导入记录的当前结果

这是已确认的记录更新要求：正式补数功能在自己的收尾流程更新原operation的`coverage/<d>/result.json`及`coverage/summary.json`，不建立另一套审计入口、job、状态表或全历史数据扫描。补数的下载/合并/发布仍遵守本数据集原规则；本节只负责接收已经真实发布并通过检查的两层结果，不下载、不提升业务文件，不替代补数授权。原bootstrap SourceComplete和PublicationComplete始终不改，bootstrap恢复也不得用旧Prod源覆盖补数结果。

**调用关系和内部接口。**代码仍放在`defs/bootstrap/stk_factor_pro_history.py`，类型引用§10.5.4的Context和CurrentPublication；发布层通过内部参数传入已核bootstrap上下文，不接受运营直接传路径、计数、passed或事件id。补数控制层在维护检查后读固定operation的approval并核approval_digest、原全范围物理导入已完成及本日原SourceComplete/两层导入完成记录；不要求旧覆盖已经齐备，也不要求历史事件已经补齐。首次补数按§10.7解析八字段及bootstrap授权；原生日更重新执行沿已核Context，历史repair从精确source_run继承Context而不增加四项配置。不得扫描staging猜operation或伪造parent。

具体调用者为asset/op控制层：它持有Context，在通用本数据集IO候选/发布函数返回audit且事件持久化后调用下列统计函数。IO候选/发布模块不import bootstrap；bootstrap原导入仍可复用这些IO函数，不形成bootstrap→publication→bootstrap循环。Context是内部传参/PG意图，不是让IO自行发现operation或另开线程执行统计。

```python
def read_stk_factor_pro_bootstrap_current_publications(
    instance: dg.DagsterInstance, *, context: StkFactorProBootstrapContext,
    run_id: str, audits: tuple[StkFactorProFileAudit, ...],
    expected_file_dates: tuple[date, ...],
    attempted_dates: tuple[date, ...],
) -> StkFactorProBootstrapPublicationBatch: ...

def update_stk_factor_pro_bootstrap_after_publication(
    connection: DuckDBPyConnection, *,
    lake_root: Path, staging_root: Path,
    approval: StkFactorProBootstrapApproval,
    inputs: StkFactorProBootstrapCoverageInputs,
    publication: StkFactorProBootstrapCurrentPublication,
    raw_audit: StkFactorProFileAudit,
    silver_audit: StkFactorProFileAudit,
) -> StkFactorProBootstrapDateCoverage: ...
```

第一个函数只核事件/运行身份，不写文件；第二个复用prepare/evaluate/write，不查询事件或新建连接。context和approval同operation/摘要，context.target_trade_date等于该run原T；首次/重新执行/repair继承按§10.7及§4.1核验。正常无关联的阶段观察Context显式null，有关联者在开始观察保存并读回；不能将其误写成DagsterRun有任意metadata属性，也不能从任意同T run猜授权。发布日期可以为T或已核原plan范围内的d<T，Context里的原T不随历史日期改写。

事件读取接收整批实际完成audits（含Raw-only尾日）、本批需文件计划expected_file_dates（skip_no_file不加入）及真正进入文件发布边界的attempted_dates。后者在写intent/replace前记录，不能用整个未执行计划代替；未触及日期沿原有效事实核验。先匹配全部实际事件，再求原批准交集；publications只含本日两层/check俱全，incomplete_dates只含已改变/无法确认当前两层的日期。attempted但核目标仍未变且原依据有效可归unchanged_dates，不能因尾日失败丢前19日，也不能把未执行的后18日一律标无效。N按整批实际yield事件数，至多40，N=0不查；不匹配/伪造/坏授权报错。调用方更新完整凭据、保留unchanged_dates的有效结果，仅incomplete_dates排除verified_current_dates；历史任务仍整范围未完成，不能以统计状态缩减下次网络范围。

固定时序：

1. 补数取得完整新源，按既有流程发布Raw、由最终Raw生成Silver，完成两层读回及对应物化/check的持久化；日结果继续只留本次内存，历史失败范围继续重新下载。本节不会为了更新记录保存日下载副本。
2. 在已有生成器yield恢复并核事件已落库后，复用本批真实事件映射构造CurrentPublication。对日补数为1个日期/2层；历史发布为当前至多20日期/40层文件。必要时按§4同样的`get_records_for_run`分别读取本批ASSET_MATERIALIZATION及ASSET_CHECK_EVALUATION各一次、limit为本批实际对应事件数且至多40；按(asset_key,partition)精确配对，不逐日扫事件、不猜id。已有本批映射则不重复读取。每个check须passed=True、severity/阻断及合同符合§9，target_materialization_data绑定对应真实物化；物化/check必须同获准run和本日，文件SHA及Silver的raw_sha256与当前两层audit匹配。不能仅凭run SUCCESS或文件存在放行，也不因本run随后历史失败而否定此前真实通过的日文件。
3. 同一主要DuckDB连接复用本日/本月已核日历、生命周期、身份和最终停牌依据。若当前Raw/Silver SHA及依据与旧result相同，复用旧代码差集/计数，仅更新确有变化的发布引用；引用也相同时直接返回原result，不重写。否则从本日已读回Raw主键关系计算完整差集；关系已释放时只再读该日代码/日期，不重做261字段或全历史对账。继续使用bootstrap历史身份映射规则，不把普通日更的计数未经核对直接抄过来。
4. `coverage.source_rows`固定取原SourceComplete.actual_rows，并核actual_rows==approved_rows；source_complete_digest取原同名字段，source_empty取原空源标志，原导入完成事实保留。SourceComplete没有source_rows属性，不能按覆盖记录字段名反推源记录接口。evaluate传本次CurrentPublication和当前两层audit，得到当前raw_rows/silver_rows、两层SHA、当前覆盖及差集。原4800/当前5000合法，当前Raw/Silver仍须互相对应；原源0而本次补出行时，source_rows仍0、source_empty仍True，当前两层非空并保存新SHA。原源到原导入少保存一行仍属于传输错误，不能借新分支解释成合法补数。
5. 差集明细先按新input_digest完整保存，再按既有JSON/fsync/replace/读回规则原子替换本日result；current_publication必须和本次实际文件一致。前后再次核输入及文件身份，发现变更停止，不写过期结论。result只反映已经通过两层发布/检查的当前状态；覆盖未知照实记None，不能将“补数命令成功”写成股票必齐。
6. 日T两层/check已持久后立即更新T result并调用summarize刷新summary，之后才判断/下载历史；不能等整job成功。历史每20日批末（含尾批及普通异常的部分批）对完整日期逐个更新result，再刷新一次summary。控制层分别提供verified_import_dates和verified_current_dates，后者排除本批未配齐或身份无效日期。只重算本次影响日期主键，其余有效小记录复用；每次summary至多读原范围小记录一遍，不扫全部指标/Prod，不在旧总量加增量。异常安全收尾尽力汇总已保存result，保留最初错误；强制退出未能收尾时旧summary仍须核身份后才能用。
7. 在本run已有阶段观察/结果metadata中记录operation、受影响日期、当前result/summary的受控相对路径及字节SHA、当前缺口及下一动作。原源0且新请求仍合法空、当前两层均无文件时，不构造虚假CurrentPublication或check；复用原空源及当前无文件事实按零实际集合保留缺口/更新本地统计，并保存本次合法空请求结果。已知应有集合非空时，必须先完成本步result/summary保存及读回，再按§4.0.1 yield日waiting并主动业务Failure；不能因为要失败而跳过统计，也不能因统计写成就将run记SUCCESS。记录写入失败按原本地读写错误处理，不能伪称缺口记录已刷新。原导入SourceComplete/PublicationComplete及其源行数仍不修改。已有业务文件的日期必须完成两层/check分支。最终事件补录只补仍缺少或失效的事件，已有补数事件不重复写。

**失败及再次执行。**Raw已发布而Silver/check未完成时不调用本更新函数，不把本日记为齐备；旧result只保留上次已核验事实，因文件身份不同已不能证明当前有效。result已更新但summary写失败时，旧summary与date_result_digests不符，不能作为放行依据；业务文件和已保存逐日结果保留，不回滚。记录写入错误向控制层抛出并显示具体文件及阶段，不伪装成源错误，不自动重发网络。同一次仍在运行的控制流程不得忽略错误继续宣告完成；获准重执行补数任务仍按既定规则全新下载其原失败范围，随后用本次已验证发布结果更新记录，不复用失败源。日历/生命周期/停牌/身份改变按原局部失效规则处理；补数事件引用、文件身份或授权损坏时报告并停止，不自行补造绿色。

使用者读取当前result/summary时，核其引用及当前正式文件身份；已改变的文件不能借旧绿色结果通过。补数时已有DG记录直接作为发布/check凭据；读取方不再完整重算源到Raw、Raw到Silver，只核已有结果与文件对应。summary的原导入计数不能阻止合法补数后的当前数量通过，当前代码缺失、文件/依据未知仍阻止历史事件补录及启用。旧summary或单个run SUCCESS不能替代这些条件。

**成本与最小回归。**设本次影响K个原范围日期，新增计算只读K份Raw主键及受影响月份的必要依据；每个重算日期至多1份result及2份非零差集文件，另1份summary。本批物化/check读取至多2次有界查询（包括仅完成Raw的尾部事件，统计到PublicationBatch）；run及授权观察同次已有映射直接复用，否则另按§6.2各读取一次并缓存至本run调用结束，不对每日期重复。无新来源请求、无新增261列扫描、无全历史事件审计。summary只扫已有小记录并明确最终身份核验开销，不能把缓存当未经核验的当前事实。小夹具至少覆盖：原4800→当前5000且缺口归0；原源0→补出数据但source_empty保持True；A/B应有而A/C仍缺B；仅Raw完成不能更新齐备；记录/summary任一步写失败不回滚文件且旧结论不可放行；重复同发布不累加；等价新物化只换引用不重算集合；错operation/授权/日期/合同/check绑定拒绝；本run后续历史失败但本日已通过两层仍可保存真实日状态；已产生合法事件不重复补录；批次同时含原范围内外日期时不因limit缩小漏事件。原SourceComplete及PublicationComplete在所有用例中逐字节保持不变。

### 10.6 从物理bootstrap到历史事件、自动化启用的先后条件

完整顺序固定为：忠实导入并记录缺口→完成批准范围物理及覆盖审计→管理员批准历史事件补录→补录并读回核对所有应有历史事件→管理员批准启用本数据集自动化。前一项未完成，不进入后一项；物理bootstrap函数不调用事件写入或sensor启用接口。这里把阶段衔接接上，不把后续正式事件/启用执行授权并入bootstrap批准。

| 阶段 | 必须已有的输入与通过条件 | 未通过时的动作 |
| --- | --- | --- |
| 物理bootstrap | 沿§10.1～10.5忠实导入；来源完整性、源到Raw及Raw到Silver261字段核对均有完整事实；合法Prod原缺口不阻止其余日期导入。 | 传输/文件错误按原规则停；市场缺口/依据未知记录在既有逐日统计和summary，合法已导入文件保留且可读。不因缺口删文件或自动补采。 |
| 批准范围完整性审计 | 同operation原导入事实完整；当前result/summary、文件/依据身份匹配，所有缺口/未知/当前不可核验日期为空且total_missing_count=0。原导入对账及当前两层check有效，允许当前数量不同于原source_rows；extra已解释。另核本operation已产生的必要历史计划无未完成范围/未解除失败，完成或确实无历史的阶段事实有效。 | 缺失/未知/两层未完成、当前身份不符或必要历史未完均不放行。即使T已补齐、summary缺口0，后续历史失败仍阻止补绿/启用；复用已有阶段/plan/完整发布事实，不重算全历史。补数收尾更新现有统计，覆盖绿灯不冒充历史完成。 |
| 历史事件补录 | 引用上述同范围最新有效result/summary及当前正式文件身份；先做只读事件计划，列资产/分区、已存在、应补、冲突及精确写入上界，管理员另批后写入。补数任务已产生且与当前文件绑定的物化/check直接使用，只补仍缺失的合法事件；先物化后check。原源0但已补出数据的日期按当前文件处理，仍无文件日期不造事件。 | 有缺口/未知不补绿色；旧失败、旧文件或metadata冲突不能覆盖掩盖为通过，也不能因原source_rows少于当前数量而拒绝合法补数。写入失败保留已成功事件，按已核缺失清单继续并读回，不重导业务文件、不自动启用。 |
| 自动化启用 | 当前数据、同operation必要历史完成及事件补录三类依据都仍有效，全部应补事件已关联核对、无活动修复/发布；管理员按§4.2明确启用分区/日更sensor。 | 任一事件缺失/失败/绑定不明或补数必要历史pending/失败，均STOPPED；不能只凭文件存在、缺口0、run结束或summary已保存启用。 |

事件阶段沿现有[性能治理§7](dagster-data-pipeline-performance-governance.md#7-dagster-event-与-runless-event-规则)使用有界批量读取/补录和写后核验；不在日常sensor逐日扫描历史。它的正式写入实现和执行清单必须在进入该阶段前完成独立审查和批准，物理bootstrap交付只输出可接用的文件及审计事实，不自行增加事件job、状态表或启用配置。事件补录及启用的必要验证为：物理导入成功但仍缺一股/有一个未知日期时均禁止补绿及启用；审计已过但少一个历史check时仍禁止启用；两者范围/身份均匹配且事件已完整读回后才可按批准启用。

管理员已确认：原来源及忠实导入4,800条、应有5,000条时，原导入证明继续记录4,800条；正式补数后当前Raw/Silver各5,000条、缺口0，由补数入口按§10.5.6直接更新同一operation当前结果及汇总。最终事件/启用条件读取这一最新有效结果，不再要求当前数量与原Prod来源相等；无需另外创建修复后审计入口。文件变化必须有合法发布/check依据，不能把任意改文件登记成补数。

最终只读事件计划须同时列出本operation关联的补数原T、已核授权/最近日与历史阶段引用及必要历史完成/未完状态。沿§6.2同Context记录和原plan/publication-complete核验；只有真实整范围成功及producer成功，或已检查输入且明确no_action，才可标历史已处理。没有发生补数的原导入不因此重算全历史因子；已知pending/失败/引用不明则停止。这里使用既有元数据，不增加状态表或审计入口；超过治理阈值时按授权run/阶段引用批量读取，避免每个历史分区重做readiness/数据扫描。具体事件写入实现仍按本节既有独立阶段方案/LLD批准，不将其混入本次物理导入函数。

### 10.7 bootstrap后的首次人工补数及重新执行

本节为管理员已确认的设计。复用同一个raw_tushare_stk_factor_pro_update_job、同一multi_asset和§2.4八字段配置，purpose=bootstrap_supplement；不另建job、sensor、命令平台、审批表或下载缓存。一次处理一个原bootstrap批准范围内的缺口交易日T，首次无需旧日更run，仍走完整日更新及必要复权历史。管理员按§4.2先停自动sensor、清空本数据集活动队列、明确批准本次执行；bootstrap批准记录用于限定来源和日期，不能替代本次正式网络/写湖授权。

#### 10.7.1 配置、日期与入口解析

```yaml
ops:
  stk_factor_pro:
    config:
      execution_day: "2026-10-25"
      target_trade_date: "2026-10-21"
      purpose: bootstrap_supplement
      scheduled_slot: null
      submission_no: null
      bootstrap_operation_id: "<已完成物理导入的operation标识>"
      expected_bootstrap_approval_digest: "<approval.json文件字节SHA-256>"
      expected_bootstrap_date_result_digest: "<coverage/2026-10-21/result.json文件字节SHA-256>"
```

执行时选择T对应分区。首次execution_day必须等于本次上海日期，允许周末；实际T仍必须是已确认且已注册的SSE开市日，P仍取T的严格前交易日。原生重执行保留原execution_day，不因已经隔日拒绝；本次实际开始时间另记。operation_id及两个摘要是本用途三项必填，自动用途全部None，类型/未知字段按§2.4封闭校验。示例不构成执行批准，不伪造原parent/root，也不将source_run_id或股票/日期数组加进此入口。

resolve_stk_factor_pro_bootstrap_context固定在既定defs/bootstrap/stk_factor_pro_history.py，复用本模块原operation/日期result读取，并调用readiness已有PG身份/原运行观察核验及纯覆盖函数。asset/op分别组合这两模块；依赖为asset/op→bootstrap→readiness→run_contracts，readiness不得import bootstrap，不能用局部import掩盖循环。纯统计函数仍不读instance；本授权resolver仅作有界PG元数据及本地记录读取，不改通用RunRequest或其他数据集。接口：

```python
def resolve_stk_factor_pro_bootstrap_context(
    instance: dg.DagsterInstance, connection: DuckDBPyConnection, *,
    lake_root: Path, staging_root: Path, current_run: dg.DagsterRun,
    run_input: StkFactorProRunInput, calendar: tuple[date, ...],
) -> StkFactorProBootstrapContext | None: ...
```

普通两用途仅确认bootstrap三字段为None并返回None；本用途按以下首次/重执行分支返回经核Context。asset先完成§4.2活动任务检查与配置解析，再调用此函数；无效身份或依据在名单保存、开始下载及任何正式写入前拒绝。不在helper里初始化instance、创建run、注册分区或更改approval。

#### 10.7.2 首次无parent的授权校验

1. 按paths.py生成固定operation根，核安全标识、approval文件字节SHA、完整结构和本数据集合同；只读原批准/原源与导入完成事实，不探测Prod、不要求原Prod维护窗口继续有效。原物理导入须全范围完成，含已证明源0日，import_pending_dates为空；当前市场仍有缺口是本入口用途，不要求all_expected_present=True或历史事件已补完。全范围原导入事实复用有效批准/汇总及原完成记录，只读小记录，不扫描全部261列或每个日期的事件。
2. T必须在原批准闭区间且有明确原导入完成事实；原源0日接受SourceComplete.actual_rows=approved_rows=0、原无文件的完整证明，不要求原本存在Raw/Silver。原导入半日/漏行/字段对账失败先按bootstrap原恢复处理，不能由补数伪造完成。
3. 读取固定coverage/<T>/result.json，字节SHA必须等于配置expected_bootstrap_date_result_digest；核operation/approval/T、原source_complete_digest、原导入事实。按§10.5核当前正式文件的原导入或合法补数依据、当前本地日历/生命周期/身份/停牌及完整缺失清单。必须coverage_complete=False、missing_count为正精确int、代码差集依据已知且清单行数/键/日期/摘要匹配；不能只看数量，不能拿未知或文件损坏冒充缺股票。
4. 结果已齐、依据过期/未知、摘要变化、错operation/日期或文件无有效依据均停止，给管理员具体文件/原因及“先刷新现有统计或处理依据，再按新摘要提交”的动作；不自动改配置、不就地换成另一份缺口授权。若日已齐但原补数历史/记录失败，提示重新执行原补数任务，而非伪造新的首次缺口。
5. 核原T/P股票复权因子Raw就绪及当前维护/唯一写入；按§5.1比较并保存完整变化名单。历史起点严格采用§5.1.1的统一规则及§5.1.2的完整范围判断：优先复用已有可信边界，无现成依据时对本次代码和已批准可信Raw日期作一次批量最早日期聚合，不截短、不猜起点。该规则同样适用于普通日更和repair，不只用于本入口。
6. 第一条技术因子网络请求前，把Context随既有“开始下载”AssetObservation保存并按§3.4读回；必须匹配当前run/T及以下完整字段。首次预检未通过时保存明确PRECHECK_NO_DOWNLOAD，不能写已经授权并开始。

StkFactorProBootstrapContext的完整字段以§10.5.4为准：operation_id、approval_digest、target_trade_date、authorized_date_result_digest、authorized_gap_input_digest、authorized_missing_count、authorized_missing_codes_ref、authorization_run_id。首次后三个依据从已核缺口result取得，authorization_run_id为本次实际保存首次授权观察的run_id；不存全部下载行，不复制日源或另建授权文件。开始观察本身的storage_id在保存后从真实记录取得，不放入自身payload形成循环引用；后续阶段观察完整保留同一Context。

#### 10.7.3 原生重执行及授权保留

直接parent和必要root必须同update job、终态、同T分区及解析后的相同八字段；首次root可以是bootstrap人工run，不要求自动日更run。先从parent开始/阶段观察读取Context，再按authorization_run_id精确读取首次授权观察；仅匹配goldenshare/download_started=True、producer run等于authorization_run_id且同T的唯一一条，后续带同Context的阶段观察不算。核原operation/approval/T、两个摘要、正缺失数及原缺失清单引用，该授权run还须同job/八字段。已缓存记录复用，最多核parent/root/明确授权run三条不同运行；原授权ASSET_OBSERVATION升序limit=8，超界不扫全实例猜测。

有有效授权后，当前missing_count可以已为0，当前result字节SHA也可以因合法补数改变；不再将它们与首次配置SHA强行比较，不读一份已被替换的旧result作为本次源。仍核原approval、当前文件/依据、原T/P及同T未完成历史意图，保留已知完整原失败范围。每次完整重新下载T，历史符合门槛后重新下载所需原失败范围；只复用原授权/工作意图和已正式发布文件，不复用失败源或候选。

重新执行前不要求当前Raw/Silver已配齐或旧current_publication/result仍匹配，否则Raw已提升而Silver/记录失败会被错误拦截。按§7核本数据集已发布文件、原run的intent/完成或物化事实与当前SHA，合法单层提交也作为当前基础；replace后checkpoint未完成可用已核intent.expected身份确认已发生的写入，只读其元数据，不读取旧源/候选作新U。仍先做当前B必要物理校验，无法解释的外部改写拒绝；完整两层/check及新统计要求在本次重下T后重新建立。测试必须证明Raw完Silver失败、两层完统计失败后都确实进入新网络，而非在预检要求旧结果已齐。

若原run在授权保存前即以明确PRECHECK_NO_DOWNLOAD终止，允许当前run重核首次缺口/批准条件，authorization_run_id由真正首次保存者确定；parent/root及原八字段不变，即使隔日也不重新要求原execution_day等于现在，不将此原生重执行误当无parent的新申请。预检Context只表达意图，无download_started=True观察不算授权持久化；须区分明确未下载与已有开始标记却授权损坏。授权本应存在却缺失/损坏、是否下载无法判断或首次依据已变时停止，不猜作首次。管理员处理原因并取得有效新缺口后可明确新建首次请求，但仍完整满足§10.7.2，不领取旧失败部分下载进度。

#### 10.7.4 完整业务及统计收尾的固定时序

```text
维护/队列清空 → 八字段及首次/重执行授权 → 原T/P就绪
  → 生成/保存本run完整回刷名单 → 开始观察含授权持久化并读回
  → 全新下载单T完整unit，仅本次内存 → session成功关闭并核summary
  → 日Raw候选/发布/读回/check → 最终Raw生成日Silver/发布/读回/check
  → 核两层事件已保存 → 更新原operation的T日result → 刷新summary
  → 原T Raw齐备且Silver有效：重新核权威因子/完整范围 → 必要历史全新下载
  → 每批至多20历史日，逐d<T的Raw→Silver → 批事件/完整日期result → summary
  → 分别记录日可读、当前缺口、历史完成/失败、统计结果
```

日仍缺股票时保留已发布行及最新统计、历史零请求，不因“完整下载unit”伪称市场已齐。日两层已完成就更新T统计，再进入历史，不能等历史全成功。历史按本批已通过两层/check的日期更新，异常处理见§4及§10.5.6；只Raw完成的日期不构造完整发布凭据，summary列当前不可核验。若后续历史失败，已完成的日统计保留。记录更新异常不回滚业务数据、不自动重发网络，不忽略后宣称完成；新run从T日下载开始，沿原授权处理原失败历史并更新统计。

首次补数仍为0行且两层无文件、已知应有非空时，不进入上图日候选/发布分支；按§10.5.6第7步先如实更新原operation零实际及缺口统计，再保存日waiting并按§4.0.1报业务失败，历史零请求。管理员再次原生执行仍沿已核授权、全新下载，不复用0行结果，也不把已用的开始事实改成PRECHECK_NO_DOWNLOAD。

本用途不受自动19:00/午夜、执行日开休市及Q一次限制，不消耗自动slot、submission或business_attempt；所有活动写入检查仍包含它。自动sensor不得生成或自动重试该用途，手动失败后由管理员处理并再次原生执行。已有此run及完整plan/ranges后，手动历史repair可按§4.1引用，只重下历史并继承Context更新相应历史统计，不能借repair代补T。bootstrap原SourceComplete/PublicationComplete和源行数不改，当前result/summary如实反映补数后数据；已有合法事件在最终补录时直接使用。

#### 10.7.5 配置消费者、成本与验收

八字段均由run_contracts单处维护并持久化run_config，消费者为asset解析、source/Context核验、RunIdentity、开始/阶段观察、§6.2记录读取及repair继承；三项bootstrap字段无其他默认或运行时热改。Dagster原生parent/root/传感器身份沿原能力，不新增自定义run tags。开始观察保存小型授权计数和引用，PG不塞全部缺失代码或业务数据；原缺失清单仍在受控operation目录，当前缺失诊断按原run路径维护。

首次授权只核原完成小记录及T日文件/主键依据；原范围小记录遍历最多一次、本地输入同次按月复用。重执行额外至多三条精确run及各一次有界授权/阶段观察读取，不遍历运行史。日及历史下载请求、内存、磁盘/失败全范围重下、20日合并仍按§10原预算；追加的是当前日期主键统计、阶段/每批summary小记录和已产生事件配对，不能将这些省略为“零成本”。无不确定代码范围的全湖扫描、无Prod再审计、无新任务总请求预算。

最小隔离验收包括：无parent合法首次通过；错operation/approval/result SHA/T、0缺口/未知、原导入未成、未登记日期、自动用途携带bootstrap字段均在网络前拒绝；周末首次/隔日重执行通过；授权观察保存或读回失败零网络；首次授权后退出、Raw完Silver失败、日齐历史失败、result/summary失败均能沿同八字段原授权重执行并实际新下载，不要求旧两层已齐。T两层后立即记统计、历史失败不抹日事实；20日批第2日Raw内容已改变后失败时d1统计更新、d2当前不可核验、未触及d3～20原事实仍有效，整个历史仍失败并全范围重下。覆盖全0缺但必要历史失败时禁止最终补绿/启用；repair继承Context；普通旧配置无parent拒绝；人工不占Q自动机会但占活动写入；原4800→当前5000、原源0补出数据、重复不累加及已有事件不重复。均为隔离小样本，不构成正式执行批准。

## 11. 测试与验收要求

以下为日发布、历史、repair、bootstrap及sensor等后续批次的完整业务验收要求；第一批契约/基础结构、来源及框架API的实际结果单列§14，不能替代本节尚未实现的业务链路。夹具来自现行生产者/合同和有界样本；expected为独立字面小样本，网络替身不能声称真实接入通过。新增/调整测试文件在现有tests下按对象分为`test_stk_factor_pro_sensors.py`、`test_stk_factor_pro_history.py`、`test_stk_factor_pro_repair.py`、`test_stk_factor_pro_publication.py`，转换/检查/bootstrap沿§10.4列出的文件。

| 主题 | 必须证明的正反例 |
| --- | --- |
| 交易日与自动边界 | 周一Q为周五、P再前一交易日；只今天/Q；19:00～23:30固定slot，活动占用跳过、午夜排队拒绝/已开始可结束，不改前日一次。 |
| 人工重执行与自动保护 | 自动Q已用仍零自动提交，普通人工须真实parent/root才可重执行原Q且不恢复机会；无parent的普通旧配置拒绝，完整bootstrap授权的无parent首次通过。新授权仅解除同operation/T真实完成阶段的失败，waiting/其他operation不解除。 |
| bootstrap八字段及授权重入 | §10.7所有正反例；周末首次、隔日重执行、原始0源日、首次授权未保存且明确未下载的重核、授权后gap已0但历史/记录失败仍重下。parent/root错八字段、观察损坏、旧配置无parent、0缺口或未知首次均拒绝。sensor过滤下10条自动+多条人工仍准确核Q机会；最新同T与活动任务必须看见人工。 |
| 覆盖身份语义一致 | 旧代码A经有效日期映射到标准B时，日更/repair/bootstrap两类包装均缺0，Raw/Silver原值不变；映射缺失/过期/歧义均未知。仅identity SHA改变也重算；正常等价物化不重算。拒绝把统一身份码再当原码映射第二次，不因旧新码差异出现统计已齐而历史门槛仍缺。 |
| 人工跨午夜及同job历史 | 原T任务FAILURE或SUCCESS但缺股，管理员获准在原D午夜后/休市实际执行日重新执行，核原T/P并新下载；Raw齐、日Silver通过后，同run即发必要历史请求。自动无parent旧配置仍拒绝、自动午夜截止不变、人工不恢复Q机会、不新增历史自动job。 |
| 名单形成前失败 | 上次任务在生成回刷名单前失败，这次重新比较原T/P并生成本次名单；不读取一份当时没有保存出来的名单。已记录原待回刷股票/起止日期时保留它们，原授权损坏时报具体引用，不能用空集合掩盖；旧下载读取作新源即测试失败。 |
| 前日机会与原生tick | PRECHECK_NO_DOWNLOAD不耗、开始事实写后crash保守耗、清cursor不复活；19:30活动跳过后清cursor仍不补发，首次合法slot可发；临时instance实存tick。 |
| 输入与完整名单 | T/P Raw未就绪不提交/不联网，job二次核；完整变化名单先于技术网络保存，不按本轮源少股缩小。缺P/缺T/两日缺必须保留未知，因子改回相等不抹掉原失败范围。 |
| 原T Raw齐备 | 五股应有、Raw只有四股：日Raw/Silver可发布，历史请求和提升均0；第五股补齐后全名单一起历史。不能只看行数/字段check绿/某次unit完成。 |
| 集合与停牌 | 五股中一股确认全天停牌，另四股Raw齐即覆盖完整，停牌变化股也可刷d<T；盘中不扣除。停牌未知或文件日期/身份错不能认齐，重复一股缺另一股同数量仍拒绝。额外合法源行不删。 |
| 手动入口四字段 | 四项必填、准确ops层级；错T/job/原plan/ranges/越根路径拒绝；未知配置字段拒绝。source_run只定位原授权。 |
| 手动原T缺失直接报错 | D和原T不同，只看原T Raw；缺文件/缺代码/结构错/覆盖未知均抛固定“原日期数据缺失”提示，retryable=false，技术网络/日更新/历史提升/T事件全部0；今天齐不能替原T。 |
| 手动原T Silver前置 | Raw覆盖True但原T Silver缺文件/缺物化/缺check/失败/绑定其他物化/文件被改/对应旧Raw SHA，各自报“原日期Silver不可用”、retryable=false且网络/历史提升/T写入0。RawCoverage仍True，不伪改为股票缺失。当前文件及check有效、来源Raw SHA相同则通过；等价Raw新物化id不能误拦。不重做261列，repair不代补原T。待刷历史d的Silver不存在仍能由本轮Raw生成，不能因新增T前置阻断历史补齐。 |
| 覆盖结果保存和复用 | 应有5000/实际4000时两项文件check可绿，coverage=False且missing=1000，完整清单恰1000条、sample最多20、PG与eligibility引用同一清单。缺0/未知清单引用为null；未知不伪0。evaluate及sensor写文件0次；job/repair用同连接完整差集、可信身份写清单后才持久保存，拒绝missing>0却无引用的持久记录。Raw内容和依据未变但新物化/check id不同，集合SQL0次，核绑定后保存本轮id；内容/依据改变或清单损坏才局部重算原T代码，不读261指标、不重下载。 |
| 直接使用DG检查凭据 | 有效Raw物化+绑定check+同文件身份时直接使用，Raw结构/源保存/B+U全字段重做次数0；旧绿色绑定其他物化、文件sha变化或check未落库均拒绝。原生产run仅历史失败时日Raw检查仍有效，不能因run FAILED否认日数据。覆盖输入未变时集合重算0，改变才核原T代码集合。 |
| repair结果的发现 | 无分区repair op写Raw资产partition=T阶段观察；正常新日更通过fetch_observations找到成功结果、解除原历史失败，不需parent、不加系统分区tag或新表；其他T/其他job/错producer/坏引用均不沿用，超界不扩全历史扫描。最新日更在首条观察前退出/取消时，原生最新run查询必须仍能发现并保守停止，不能被旧绿色观察掩盖。 |
| 手动不代办日更新 | 对BY_POINT、原对象T确认及日发布函数设调用即失败的替身；Raw齐后只完整原名单/原范围历史，不能加股/延边界/改T，不发T确认窄查询。 |
| 日期与下载会话终态 | 本地date转ISO后接入真实组件输入校验；直接传date拒绝。全部unit已交付但关闭抛1304、或summary为STOPPED/CANCELLED/FAILED时，日不构造Raw候选、历史不写source-complete，两者正式提升均0；仅最终成功并unit/行数对账一致才放行。 |
| 日下载只保留本次内存 | 一个T任务只收到1个完整unit，with内不创建日文件/Raw候选，with成功退出后原tuple仍能构造当前U；DataFrame解除注册后临时U仍可用，日两层完成/finally后DROP并释放result/列/frame引用，跨轮不累计结果。不以RSS立即下降作断言。拦截source/day、日manifest/source-complete及日源片段写入，调用即测试失败；只允许唯一Raw发布候选及后续Silver候选。日publication来源引用为null、day_source_digest非空，反向混入历史ref拒绝；历史反向规则同测。 |
| 历史源对象及日期进入计划 | 请求000001.SZ返回600000.SH、错unit身份、时间越界均在源适配拒绝，不过滤后继续；日全市场多代码正常通过。历史源全部保存后，已确认休市源行、日历缺一日、分区未登记均在首次历史提升前拒绝；正常多股/跨月/末批及T诊断行通过，所有d<T源日期恰被发布计划覆盖，不因20日切批漏日。 |
| 取消适配及收尾 | DownloadControl函数精确bool，STARTED/STARTING正常、CANCELING/CANCELED取消且保持；run缺失/读取失败/错误终态不伪False。模拟密集排序检查不产生逐行PG读取，保存/replace强制刷新。进度观察异常仍不阻断，控制读取错误不能被进度异常隔离吞掉；网络/关闭/发布时中断均清理本次对象，已发布文件保留，新run完整新下载。 |
| 失败阶段全新下载 | 分别在日unit未完、日结果仍在内存但未发布、Raw完Silver失败、历史源完未发布、历史部分已发布、全部物理写完事件失败处退出；新run所有所需unit均重新网络获取，不读取旧源/候选、不得按页/股/日期跳请求。 |
| 新数据确实覆盖旧候选 | 固定旧候选值10、当前正式值11、新网络值12；重执行必须得到12，且保留正式中源未返的合法旧键。旧source路径若被当新输入读取则测试主动失败。 |
| 正式已发布保留 | 失败/取消后当前已发布文件仍在；新历史请求全范围后基于这些当前文件合并，不删、不回滚、不重放旧候选。成功的其他独立完整范围不无故并入失败范围。 |
| 完整成功免重复 | 仅producer最终成功且整范围publication-complete/输入/范围有效可避免后续同T重复历史；全名单新增一股不使原独立成功范围重下，其他股改同日文件时核scope行数/内容摘要仍有效，原范围任一业务值改变则不沿旧完成。repair核实已无待处理历史时返回真实no_action，零技术请求/零正式提升，不伪造本run新完成历史。producer失败即使有完整源及物理记录仍重下。 |
| 当前run安全发布 | 候选必要校验→intent→再核prior→replace/fsync→读回/complete；目标变动拒绝，事件失败不回滚。当前正式内容与新候选等价可不replace，但必须已经本次新下载。 |
| Raw→Silver与T边界 | 每日期从最终Raw生成Silver；Raw5000/旧Silver4800/本轮只返4800，Silver必须5000；历史只d<T，源T保留但不覆盖正式T。 |
| 历史完整和漏原键 | 全部当前run约定源完整才首批20日；源少旧键时保留旧行、有效行可发布、原键缺项诊断非0不假称整范围刷新，不新增第三check。 |
| 历史未全刷的失败终态 | 旧100条、本次99条：先保存waiting/原完整范围/缺1条清单并yield持久，再抛Failure，run为FAILURE且retryable=true、phase=history、无源错误码。自动今天下一允许slot重下100条所属原完整范围，补Q不获第二次；手动repair失败后只能由管理员修正并再次手动执行，sensor不得提交repair。已发布99条及旧1条均保留，不能写publication-complete或以waiting返回SUCCESS。 |
| 无输出与事件持久顺序 | 完整selection下PRECHECK_NO_DOWNLOAD只观察且SUCCESS、没有开始下载；首次合法空且无可用旧数据/应有非空时先保存完整缺失及日waiting、bootstrap关联先刷新统计，再以day/retryable=True的业务Failure结束，两分支均无假物化/绿check。已有有效部分日数据仍发布并可SUCCESS；旧Raw有效但新源0不误判实际0。历史先yield物化再读本批真实记录并yield关联检查，不能拿未处理的log_event缓冲作完成依据；测试存储及绑定验收按§14.3。 |
| 20日与性能 | §8.2.1的1/20/21/41/45交易日、假日/末批/无行日；每批一次源查询并物化、逐日只读批临时表，查询次数与批数对应；逐日期Raw→Silver、不按20日事务；正常/失败/取消/关闭均释放批和当日关系；失败下次全范围重下而不按已完成19日续源。 |
| 错误/取消/事件 | 1201等永久错误不下轮盲重试；1203允许今天下一slot但仍新下载；阶段正确解除，不恢复Q机会。out={}、历史显式partition/check关联、标准通知不写业务数据、取消不领下一unit/文件。 |
| bootstrap独立边界 | 5000流式、月R+1及SQL超时/跨日完整证明；沿其独立批准operation的完整日期恢复，不被本次Tushare失败规则误改。覆盖统计复用本地数据，完整源/Raw/Silver及统计分别记事实，不做Prod全历史覆盖预审。 |
| bootstrap本地覆盖 | 取消Prod覆盖预审且保留源传输核对；A/B对A/C仍缺B；合法全天停牌空文件与缺文件不同；整日0源需完整空源事实，半日/一层未成不计成功；身份别名去重但不改Raw，未知不当0。 |
| 补数后更新现有记录 | §10.5.6：原4800/当前5000、原源0后补出数据均合法；原source/import记录逐字节不改，当前两层/覆盖/事件引用更新，summary原传输合计与当前合计分开。Raw-only及summary写失败不能沿旧绿色放行；重复执行不累加、等价新事件不重算集合、错授权/事件绑定拒绝；混合范围内外日期批次不漏事件，已有合法事件不重复补记。 |
| bootstrap统计恢复与汇总 | 同operation/日期替换而不累计；明细先于JSON，写失败不回滚文件；输入改变仅本地复算；正常休市0源不算pending；日历未知0源可导入但覆盖未知，最终全范围total_missing为None。 |
| bootstrap回调与记录交接 | 月流看到新日期/正常EOF确认完整日后，同步回调发布Raw/Silver及保存覆盖；异常关闭named cursor/只读事务，完整日期保留。片段/日源/intent/complete都按§10唯一结构读写，字节sha与规范内容摘要不混、日期/时间规范化，不能各处自解普通字典。 |
| 本地统计与初始化启用 | 原Prod维护窗口已过但文件已完整，仅本地复算时Prod连接/远程schema/明细读取/正式文件写入均0；仍需读源或恢复正式文件时窗口过期拒绝。有一股缺失、一个未知日期或源目标对账未完均禁止历史补绿；审计通过但少一个历史check仍禁止启用；全部历史事件读回完成且获准后才可启用。 |
| 写入互斥与自身排除 | 两job和五状态逐项覆盖；只有自身放行，自身为首条且第二条为他run仍拒绝；不同T的repair也拦，CANCELING未终结仍拦；每次2查询，不按历史日期增加。 |
| 手动前清空队列 | sensor已停但旧日更仍QUEUED或STARTING时，repair/bootstrap入口零下载、零提升；冲突立即退出，不sleep、不等唯一名额后的queued任务，不自行取消其他任务；实际入队的repair和日更最大同时运行数为1。 |
| 查询失败与提升前复核 | 入口查询抛错不得放行；入口通过、首次提升前出现他run时阻止提升；后者不得标成未下载；自身run_id错传也不能假作清空队列。 |
| 自动化恢复 | 运营步骤用检查清单验收，不在代码中增加自动恢复功能；原STOPPED保持停止，异常/取消/状态未知不自动启动；恢复失败不回滚文件、不改业务结果、不重置Q/slot；bootstrap无run不能被宣称已由run查询证明唯一。 |

用一套临时文件/instance和小样本覆盖上述分支；至少一次真实子进程退出后由新进程按新规则重新下载。不得通过skip、mock字段兜底或调用待测计算生成expected掩盖错误。

### 11.1 已确认的最小验证安排

管理员已确认§10参数及以下精简验证安排。尽可能复用仍适用证据，用小样本证明关键边界；不以大范围反复跑数代替边界验证，不为5000行大小估算另读生产样本。参数拍板不表示测试或真实验收已经完成。

| 时机/内容 | 最小范围与证据要求 |
| --- | --- |
| 开发前来源确认 | 261字段、本地源文档及已有审计继续复用；第一批已按§14.4限定的一股五日、4次实际HTTP请求验证公开load及小页offset，固定HTTP交接的字段/参数证据已具备。后续优先复用保存的同一响应，不重复来源跑数；真实10000满页边界与全市场范围仍须区分。出现新差异先列额外最小范围、请求数和必要性，不自动扩大或把小页改成业务契约。 |
| 实现后日更读写/性能 | 重用同份获准真实响应，隔离做正常日更及同日补入各1次；分别记录正常/补入的两层读写、检查和最终对账成本。无历史正常日更与120秒目标比较；sensor单次评估与5秒目标比较。十个时点、60/600秒定义、去重、活动任务跳过使用模拟时钟/运行事实测试，不要求十次真实网络或十轮完整文件重写。 |
| 实现后历史读写/性能 | 一只股票、一个不超过20个交易日的临时样本批次，保留接近真实全市场宽度的日期文件，核无关股票不变；记录本批扫描/SQL/写入/峰值空间、失败后完整范围重新下载、当前正式合并及最后读回成本。结合可信日期/文件规模估算类似17股原完整历史，比较1200秒目标并明确外推局限；不默认跑17股完整历史，不把外推当成正式全范围已验收。批次1/20/21/41日等边界用小人工计划/临时数据，不为此扩真实历史范围。 |
| 实现后事件/恢复 | 同一套临时文件和独立临时instance，事件存储明确为§14.3的ConsolidatedSqliteEventLogStorage，目标T加两个历史日期核物化/check关联；网络可替换，事件真实落库并重开核持久。源未完整、源完整未发布、替换后未记完成、事件失败四个位置做有针对性恢复验证；至少一次真实进程退出后由新进程恢复，其他细分位置用有依据的隔离错误注入，不要求每点重复真实进程/来源跑数，不对真实源制造故障。验证完整源也重下、当前正式已提交保留、新源覆盖而旧候选绝不参与、repair原T缺失零网络及事件失败不回滚。该测试不证明正式PG的锁、队列及性能。 |
| 扩大范围的条件 | 小范围出现性能或语义差异，先说明具体问题及已有证据，提出额外最小验证范围；不自行扫描全湖、导出全历史或重复全量压测。正常、恢复、最终读回的成本分别记录，已有仍适用证据不反复重跑。 |

开工前明确范围、参数、成本及必要来源证据；业务完整发布/事件/恢复的运行验收在相应实现后隔离进行。不能要求尚未编码的完整链路现在已经运行通过，也不能因此省掉开工前设计/性能门禁。第一批来源和框架API验证见§14；本节完整业务读写、进程退出恢复及性能目标尚未验收，后续正式初始化及全范围验收仍须对应批准。

## 12. 已确认业务边界与工程核验

### 12.1 权威因子和源值

变化、原T/P修订及历史依据以`raw_tushare_adj_factor`为准；技术行同名值不同只诊断。Raw/Silver保持技术源业务值、不改成权威值、不缩放或重算。历史完成只证明按输入下载/检查/发布，不冒称所有源指标数学正确。权威因子缺必要值或范围不明时保留原因并停止对应历史，不当0变化。

### 12.2 原T Raw齐备及Silver有效是历史共同前置

以原T当前正式合并Raw覆盖原T上市A股扣确认全天停牌的应有代码集合为准。全天停牌可无T行仍刷其d<T；盘中或非停牌缺行、停牌/生命周期未知都不能认齐。Raw文件check通过不等于覆盖全齐。两入口还要求原T Silver文件及有效检查对应当前Raw：日更由本轮发布建立，repair按§5.2.3直接读既有DG凭据。自动日数据少股票仍正常发布，历史零请求；手动Raw不齐报“原日期数据缺失”，Raw齐但Silver无效报“原日期Silver不可用”，均交管理员，不代办日更新或T窄查询。Raw覆盖与Silver有效性分别记录，不将两种结论合并成一个字段。

Q日已齐仅历史失败可推进今天；原Q失败历史完整名单和范围保留，人工repair始终原T/原P，不以今天行或今天零变化抹掉旧意图。原范围内权威值修订可保存新依据，但不追加股票/延边界。历史失败重执行全新下载。

### 12.3 时间、Silver和重试范围

仅SSE开市日自动，19:00～23:30固定slot、午夜截止，前日实际业务一次；休市不新增自动机会。§2.4管理员已验证重新执行可跨原午夜，仍原T/P、全新下载并在同job继续必要历史；不放开自动窗口/次数。Silver本期261字段和对应行，仅日期DATE，每日期来自最终Raw，未来清洗不阻塞本期。Tushare失败/取消/退出后新下载，不删除正式数据；日下载只保留本次内存，无日下载中间文件或缓存复用。历史名单保存需要回刷的股票及起止日期，不是下载断点。历史漏原键为失败，自动日更可在下一允许slot重取原完整范围；手动repair失败后由管理员修正并再次手动执行，sensor不提交repair。下载器当前运行内同页有限重试与Prod bootstrap独立恢复不变。

### 12.4 编码与验收仍须逐项核验

| 落点 | 必须核验 |
| --- | --- |
| 自动配置/原任务 | §2.4八字段用途分支、parent/root及bootstrap授权只取意图、错run源拒绝；任何失败阶段新run均实际新下载。 |
| Raw历史前置 | §5.2覆盖结果三态/原T文件/check/生命周期/停牌身份；自动等待、repair固定失败消息及零网络/零嵌套。 |
| 原T Silver前置 | §4.1、§5.2.3：最新Silver物化/分区check绑定、正式文件/当前Raw SHA、契约处理版本；直接使用DG结果，Raw等价重物化可通过，不做全字段；失败固定提示/零网络/零提升，不能要求全部历史Silver先存在。 |
| repair四字段 | §4.1四项封闭配置、原完整授权、只d<T、缺日零网络、失败源再完整也重下。 |
| 发布与新执行 | §7～8只当前run新源/候选、当前正式B-K+U、逐文件intent/replace/fsync/readback、正式不回滚及缺原键诊断。 |
| sensor/事件 | §3的11条/原生tick有界读取、观察先持久后网络、失败阶段metadata；日物化后历史失败仍可读、历史check真实partition关联。 |
| bootstrap覆盖统计 | §10.5：函数/记录/SQL/读写时点、可信本地输入的机械核验、源0/日历未知、两层完成、代码差集、身份异常、摘要失效/重入和最终未知总数；不新增Prod审计或修复入口。 |
| 正式补数后的记录更新 | §10.5.4/§10.5.6：原传输事实与当前状态区分，真实物化/check事件storage_id、原空源补数、result/summary原子更新及不一致拒绝；仅重算受影响日期主键，原bootstrap恢复不覆盖补数结果。首次补数明确走§10.7的bootstrap_supplement授权分支，原生重执行及历史repair按已核Context继承。 |
| DG凭据与人工补日 | §2.4、§5.2、§6.2：原T人工跨午夜重执行、日齐后同job历史；直接读取绑定物化/check和阶段结果，输入未变不重复全字段/全历史对账；上次在生成回刷名单前失败，这次重新比较原T/P并生成本次名单。 |
| 历史失败和初始化顺序 | §6.1、§8.1、§10.6：历史少旧键waiting后抛Failure、自动下slot及手动不自动重试；完整性审计通过后历史事件，事件全部核对后才可另批准启用。 |
| 配置/性能 | §10单处常量和原资源；成本包括失败后全范围网络重取、当前正式文件合并/最终验收。bootstrap明确例外。 |

按§11.1分阶段补充验证证据；正式运行和写入另行取得批准。

## 13. 开发对账清单

| 管理员决定 | 方案与LLD落点 |
| --- | --- |
| 允许省略未执行输出但禁止局部调用 | §2.1/2.4/§4及§14.3：can_subset=True、两个skippable资产，固定job及入口精确核两资产/两检查；漏选下载前拒绝。PRECHECK_NO_DOWNLOAD只观察且SUCCESS，不伪造物化/check。 |
| 请求成功而无可用日数据仍可业务失败 | §4.0.1、§6.1、§8.0、§10.5.6～10.7及§11：无旧日文件、完整请求0行、已知应有非空，先存缺口/必要统计再主动day Failure；今天下slot、Q机会不恢复、人工管理员重执行。有效部分发布和新源空但旧Raw有效保持原规则。 |
| SQLite测试存储及证据边界 | §14.3：临时instance只覆盖ConsolidatedSqliteEventLogStorage，真实事件绑定及重开持久；不改PG、不混run/index id或弱化断言；原5 failed保留，本轮未改测试或重跑。 |
| 原失败任务不论阶段均重新下载 | §2.4、§5.3～5.4、§7～8、§11；不复用失败run旧源/候选，不按页/股/日期断点。 |
| 单日内存估算及对象释放 | 方案§10.1、LLD§5.4.1/§9.1/§10～11；完整日结果150～220MiB、阶段峰值约0.5～1GiB，先按约1GiB余量，不新增硬限；保留组件2GiB，当前结果/列/frame/U在正常和finally释放，不以RSS立即下降验收。 |
| 当日日下载不保存或复用中间文件 | §2.3、§4、§5.3～5.4、§6、§8～11；唯一完整日unit只在本次内存，最终summary成功后直接构造Raw发布候选；无source/day、日manifest/source-complete，日来源引用为null；历史及bootstrap各沿自身合同。 |
| 正式文件和证据保留 | §5.3、§7～8；当前正式文件是新合并基础，名单/授权/失败记录保留。 |
| 原T Raw齐备后才历史 | §4、§5.2、§8、§9、§11；应有代码集合判断；自动日发布不设全齐门槛，历史按完整待处理范围执行。 |
| 原T Silver有效后才手动回刷 | §4.1、§5.2.3、§9、§11：原T Silver存在、有绑定通过check并对应当前Raw；失败提示管理员，不代补T数据；历史d可从刷新Raw生成缺失Silver。 |
| repair同门槛且缺日直接报错 | §4.1、§5.2、§11；原T缺/不齐/未知立即“原日期数据缺失”，无日下载/T窄查询/日发布调用。 |
| repair四必填 | §4.1；T/source_run/完整plan与ranges摘要；未知字段拒绝。 |
| 完整名单先于技术下载 | §1、§4～5；保留旧未完范围，T/P改回相同也不抹掉原意图。 |
| 日先历史后、两层逐日期更新 | §4、§8；先日Raw→Silver，再经齐备前置，历史逐d Raw→Silver，T不被历史写。 |
| 成功历史避免无故重复 | §5.4、§7；仅整范围成功、producer成功且输入有效，失败物理部分完成不冒充。 |
| 日期、前日一次与运行时点 | §1、§3、§6～7；19:00～23:30、午夜、只今天/Q、实际开始机会、不以人工重新执行复活自动次数。 |
| 合并、导出、资源及精简验证 | §8、§10～11；20日只合并组织，bootstrap5000独立；60/600秒sensor，16GB/4线程等原资源及5/120/1200秒目标保留。 |
| bootstrap过程中统计缺口 | 方案§7.3、LLD§10.5及§11：直接忠实导入后比较DG本地应有/实际集合；源原缺口不挡合法导入，同步漏行失败；全缺日、未知依据、按日期恢复及精确范围均记录。 |
| 补数收尾更新当前状态 | 方案§7.2～7.3、LLD§10.5.4～10.5.6及§10.6；原source/import保留，当前两层/覆盖/发布引用由正式补数更新，当前5000不必等于原4800；无独立修复后审计入口。 |
| 本轮已确认衔接 | §2.4、§5.2、§6.1～6.2、§8.1、§10.2～10.6、§11：人工原T日齐且日Silver检查通过即同job回刷；DG已有凭据直接读；上次在生成回刷名单前失败，这次重新比较原T/P并生成本次名单，失败下载仍全新；历史未全刷为FAILURE；月完整日同步交付及唯一记录；纯本地统计免Prod窗口；完整审计→全部历史事件→批准启用。 |

## 14. 第一批：契约与基础结构的编码及验收清单

本批按原方案§13.1的第一批实施，不将后续日发布、历史、bootstrap或自动化提前开工。目标是交付可以直接由第二批调用的真实契约、schema、输入解析和基础类型；不是建立空的下载/发布入口。本批完成前不得标记整个数据集已经接入。

### 14.1 依据、影响面与顺序

开工读取根、lake_console及orchestrator的AGENTS、CODING_STANDARDS、schema合同与性能治理规范，以CodeGraph核契约校验/登记/mapping、下载器入口、任务规划、source transport、现有测试和文档消费者，再对未覆盖细节读当前代码。源依据固定为`docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md`、Prod当前261字段定义及§3已有真实字段证据；Prod定义只读参考，不能在DG运行时import。源字段以本地文档核名称/顺序/类型/中文含义，不能从Prod辅助列或消费者查询反推。

顺序固定：先将已批准批次及本清单写回原方案/LLD→核当前消费者和测试基线→提前验证本节Dagster API→调整命名并登记完整契约/HTTP→落本地schema、输入/基础类型、路径及分区定义→隔离正反回归→获准固定范围的真实HTTP核验→代码与计划逐项对账。任一步发现实质冲突先停下报告，不改成未讨论的新方案。

### 14.2 硬约束、代码落点与本批测试

| 硬约束 | 本批编码内容与边界 | 必须核实及测试 |
| --- | --- | --- |
| 名称不带版本，版本独立 | 调整`contract_registry.validate_contract`，仅解除名称的`@version`格式要求；保留非空/唯一/完整内容校验。同步受影响组件测试和示例，不增旧名解析或别名。 | `stk_factor_pro`配独立`version="1"`能登记/查找；重复名、空版本、坏内容仍拒绝；组件已有重试/取消/容量/关闭回归不退化。名称修改不改变业务内容摘要算法。 |
| 完整261字段唯一源定义 | 新增`contracts/stk_factor_pro.py`，在既有CONTRACTS显式登记；`contract_name/dataset_id/source_api_name`均为`stk_factor_pro`。两字符串身份字段及259可空源数值字段、中文含义和完整顺序只维护此处。 | 独立本地源文档/已有字段证据逐项比对，不只断言261，也不从待测契约自身生成expected。不得混入api_name/fetched_at/raw_payload；fields必须完整，无字段子契约。 |
| 两模式及分页属于契约 | 仅BY_POINT、BY_OBJECT_RANGE；ISO输入转源YYYYMMDD；trade_date升序、日级闭区间；offset策略2、limit10000、offset起点0/步长10000、短/空页终止、满页继续，无可靠total/next声明。 | 日请求只用point，历史用组件对象扇开/范围；对象与时间参数位置正确；不足页、恰满再空、同页重试不重复交付；不支持模式/业务传fields或limit/offset应拒绝。真实分页证据按§14.4限定。 |
| HTTP方式固定 | `dataset_transport_mapping.BINDINGS`登记相同dataset_id/source_api_name，kind=1、adapter_key=http_pro、version=1、`http_path_rule="base"`；不新建SDK适配或失败自动切SDK。 | 显式请求地址采用现有基础地址，不拼API后缀；请求api_name为stk_factor_pro；mapping与契约不一致拒绝。token/地址复用组件既有配置读取，无新增env或业务覆盖。 |
| 本地类型与源类型分开 | 在`asset_column_schemas.py`从该契约构造两层ColumnContract；名称/顺序/描述引用同源，ts_code VARCHAR，Raw trade_date VARCHAR，Silver trade_date DATE，其余259列DOUBLE并保留可空规则。 | 两层字段261且只日期目标类型不同；中文说明齐全，未复制另一套字段表；不把SQL类型写回源合同，不增加Gold或辅助业务列。实际转换和文件check执行留第二批。 |
| 八字段封闭输入及基础身份 | 新增`run_contracts/stk_factor_pro.py`，实现§2.4配置schema、frozen RunInput与纯解析；定义§5.4.1的ContractIdentity/RunIdentity/RecordRef及阶段/用途/层有限类型、HistoryPlanReason有限IntEnum，集中维护§10常量。 | 未知键/非法ISO/错误日期关系/错分区/空或坏摘要拒绝；bool不能冒充slot/submission；today与previous_day不得携带bootstrap三字段；bootstrap须三字段、slot/submission为None，允许执行日休市、T仍须有效开市日。解析只消费已核calendar，不查PG/文件以伪装授权已通过。 |
| 日结果类型承接第二批 | 同一run_contracts定义VerifiedDaySource及Comparison/FileAudit、RawCoverage/CoverageCounts/TargetSilver等已确定字段；用未来注解及已知组件类型表达。只有纯结构/值校验，不能提前生成passed、当前文件可用或下载完成事实。 | 构造及类型关系与§5.2/5.4/9一致；合法NULL/负指标不被泛化拒绝，未知覆盖不伪0；VerifiedDaySource可持有UnitResult但不得被序列化为日源缓存。业务计算、验证工厂及持久记录读写在相应后批实现。 |
| 纯路径及专属分区定义 | 仅在paths.py添加正式Raw/Silver、当前run staging及受控RecordRef定位函数和后续catalog可引用的路径模板；在partitions.py定义`cn_a_stock_factor_pro_trade_days`。路径函数只返回Path，不mkdir；不生成source/day或日manifest/source-complete路径。bootstrap operation路径随第四批实现。 | 正式/候选根正确，日期固定ISO、文件名data.parquet；安全标识、绝对/相对路径、..及符号链接越界按当前安全规则拒绝；返回路径和导入模块不得联网、开库、写目录或调用add_dynamic_partitions。 |
| 当前定义不可提前运行 | 不新增本数据集正式assets/jobs/sensors/check装配，不登记active catalog；不把尚未实现的业务函数写成pass/NotImplemented后装载。 | 当前正式definitions仍能加载且没有本数据集可执行入口；纯动态分区定义并非注册分区。第二批可import基础能力，正式装配留第五/六批。 |

本批不实现历史plan/manifest/发布记录完整读写、历史规划/下载/发布、bootstrap批准/游标/统计、Context业务授权、PG事实读取、repair执行或sensor调度。这些按照原方案第三～六批落地；本批的八字段解析不能取代后续业务授权。未完成类型不以任意dict或不验证的passed参数兜底。

### 14.3 提前验证Dagster API及隔离回归

先核已有安装版本及Context7官方依据，使用测试内定义、临时文件和独立临时instance验证§2.1、§4、§4.0.1及本节要求；不连接或重载正在运行的正式code location，不连接正式DAGSTER_HOME/PG，不使用真实token，不写正式分区或Lake。只模拟业务源/文件处理，Dagster执行、事件落库和读回必须真实，不能用mock制造storage_id或检查绑定。

§14.2的“当前Definitions仍能加载”另以`tests/test_stk_factor_pro_definitions.py`单个unittest方法验收：在现有`tests/stock_suspend_confirmed_test_runner.py`的固定consumer清单中增加该文件及精确用例数1，复用其启动顺序、源码只读、临时资源、网络及正式路径拒绝，不新增启动器或改其他suite。Dagster加载当前工程时会向父目录发现配置，因此仅本新增suite额外允许本项目`pyproject.toml`文件只读，以及本项目`dg.toml`、`src/dg.toml`和`src/pyproject.toml`是否存在的metadata探测；不得把PROJECT整目录、env、正式资源或网络加入权限。由原runner执行`--scope regression --suite test_stk_factor_pro_definitions.py`，子进程调用当前`project_defs()`及`Definitions.validate_loadable()`，核本数据集两个资产/check、两个job、两个sensor及active catalog均未登记。这里只构造并校验当前源码中的定义对象，不执行job/sensor、初始化正式instance或重载正式服务。已有governance/AST测试不能替代这项真实加载验证。

#### 14.3.1 隔离事件存储的固定选择

本机Dagster 1.13.26的默认`SqliteEventLogStorage`先将事件写到run分库，再将资产/检查事件写到index库，两库的storage_id各自递增。例如同一物化在run查询中是13、自动AssetCheckResult却引用资产索引中的7；run_id和timestamp仍可相同。不能因此把数字13硬填成7、忽略storage_id比较，或要求正式PG增加SQLite分库兼容分支。

本组测试明确使用现有内置`ConsolidatedSqliteEventLogStorage`：其run_connection和index_connection访问同一临时事件库，符合本数据集正式PG单一事件表中物化id的读取/关联方式。仅覆盖临时instance的event_log_storage，run_storage及其他存储继续使用该临时instance自身默认，不更改仓库/用户dagster.yaml或正式PG。第一批已按以下配置完成隔离验证，结果见§14.3.3：

```python
instance_overrides = {
    "telemetry": {"enabled": False},
    "event_log_storage": {
        "module": "dagster._core.storage.event_log",
        "class": "ConsolidatedSqliteEventLogStorage",
        "config": {"base_dir": str(tmp_path / "event_log")},
    },
}
with dg.DagsterInstance.local_temp(
    str(tmp_path / "instance"), overrides=instance_overrides,
) as instance:
    assert type(instance.event_log_storage).__name__ == "ConsolidatedSqliteEventLogStorage"
    # 只构造本测试的Definitions、注册临时分区并执行测试job。
```

创建后断言实际storage类及数据库路径均在本测试临时根下；不得连接正式实例，也不能默认选成内存storage。关闭instance后用相同临时根和相同overrides重开，复查run、物化、检查执行记录及绑定，不能通过再执行job生成一批新事件来假装持久化通过。此内置类仅用于隔离测试，不作为生产存储替代、依赖安装或数据库迁移。

#### 14.3.2 最小验证步骤和断言

固定一个目标T及两个历史日期，两资产、两个check，与§2.1相同的分区及输出组织。`tests/test_stk_factor_pro_dagster_events.py`按以下步骤验证；每例使用独立临时instance，单例最多6次物化及6次检查评估，异常分支可以更少，不重复跑真实来源。

| 场景 | 真实执行及必须断言 |
| --- | --- |
| 完整调用与禁止局部调用 | 完整两资产/两checks可进入业务；仅Raw、仅Silver、仅check、漏任一check在入口失败，零下载/发布替身调用。正常路径继续执行，用正例证明没有误拦完整selection。 |
| 预检未下载 | yield PRECHECK_NO_DOWNLOAD后return；run SUCCESS，观察实际持久，download_started事实/物化/ASSET_CHECK_EVALUATION均0。不把框架可能保存的检查计划或跳过记录当成passed。 |
| 请求成功但没有可用日数据 | 显式成功的0行来源替身、无旧文件及非空应有集合；观察包含真实0实际和完整缺失引用，bootstrap关联时统计先保存，再主动抛业务Failure。run FAILURE；STEP_FAILURE包含day、retryable=True、source_error_code=None、allow_retries=False对应行为；无缺必需输出异常，无物化/检查评估/历史调用。 |
| 部分发布及空源保留旧数据 | 用可人工核算的小应有/实际集合代表4000/5000，文件处理/check成功、覆盖False且在无其他失败时run SUCCESS；新源0而旧Raw有效时保留旧实际集合，不误报当天实际0。应有未知不得伪0或假齐备。只替代源/文件处理，不替代DG事件库。 |
| 日T及两个历史日期事件 | 日MaterializeResult/AssetCheckResult逐层产生；历史按§4先yield四个物化、恢复后一次get_records_for_run(limit=4)读本批，再yield四个绑定的AssetCheckEvaluation。最后有6物化/6评估；不逐日期深扫事件、不自造partition参数或id。 |
| 分区和绑定 | 每个评估的asset_key/check_name/partition、passed、blocking及severity均核对；target_materialization_data.storage_id/run_id/timestamp须精确指向同资产/日期真实物化。另查asset_check_executions确认各自partition和状态，不把检查执行id当事件storage_id；文件/Raw SHA使用独立字面样本。 |
| 失败顺序和持久化 | Raw检查失败后显式结束，Silver/历史事件0；日两层完成后历史主动失败，保留日物化和通过check且run FAILURE。读取原run失败事实，不拿新run SUCCESS覆盖。重开临时instance后上述既有事实仍在。 |

事件读取仍保留§4所定批次上限；测试不得改为全量事件fetchall，也不因SQLite差异放宽正式PG算法或断言。上述验证只证明本机版本的事件顺序、分区、关联及临时SQLite持久化；不证明正式PG权限、并发、锁、队列或性能。正式环境继续按原阶段取得相应验证与执行批准，不能为本轮测试操作正式PG。

#### 14.3.3 已发现问题和后续验收状态

2026-10-26首次隔离运行`tests/test_stk_factor_pro_dagster_events.py`得到5 failed，分别涉及缺失必需check输出及默认SQLite两库id的断言差异，不解释为五个独立业务缺陷或正式数据故障。原失败证据保留；管理员确认修订方案后，本批已修改测试内multi_asset与完整selection核对、采用§14.3.1存储并补齐正反分支，14项全部通过。

本次真实框架测试分别证明预检SUCCESS、成功请求0行但无可用日数据的业务FAILURE、部分发布、空源保留旧数据、未知覆盖、检查失败顺序、历史失败保留日事实，以及重开同一临时instance后物化/check仍严格绑定。没有放宽storage_id/run/timestamp/partition断言，没有skip、吞异常或伪造绿色check。框架小样本只替代源和文件处理，不提前实施日发布/历史业务算法，也不冒充正式PG验收。命令、输出与证据范围见[第一批验收记录](../../reports/stock_factor_pro_batch1_20261026/README.md)。

其余本批单元/合同测试仍覆盖§14.2正反例，执行现有下载器整组回归及受影响schema/path/partition/definition门禁；使用既有环境、不隐式安装依赖。文档执行`python3 scripts/check_docs_integrity.py`，提交前检查diff及显式获准文件清单。所有结果分清“设计已更新”“测试已通过”和“正式执行已验收”。

### 14.4 固定来源验证及性能、失败边界

优先复用已有字段证据。本批新增真实请求固定一只`000001.SZ`、`20261012～20261016`、全部261字段，共四次正常请求：组件按正式契约发一次BY_OBJECT_RANGE（本范围预期单页）；另以受控原始HTTP按limit=2、offset=0/2/4各一次核分页。组件沿用既有单页最多4次尝试，不增加重试覆盖；组件成功在第四次尝试时加后三次小页请求，最坏7次实际发送。组件最终失败便停止，不做后三次；响应结构/数量冲突或需要新增页时也停止，不扩大对象/日期/页数或使用备用方式重复跑数。小页仅用于核源行为，不回写正式10000分页、不暴露运营配置。保存各次实际参数、发送/尝试次数、响应字段/主键/数量及HTTP路径方式证据，不保存token。

预期正常响应5行，小页2/2/1行，比较完整主键并集、各页无重叠及字段/业务值；以独立既有样本核合法源合同，不将本次数量假设当强制修改结果的理由。真实核验只证明这个对象/范围及小页offset，不证明全市场、10000满页边界或日更新已完成；满页/空终点用隔离测试补足，正式大边界证据留真实接入验收说明。

本批不读Prod明细、不扫描Lake、不写正式文件/分区/事件。四次正常请求、最多7次实际发送，每次只持本响应；契约/schema固定261项，纯配置/路径为常量规模，临时事件仅上述小样本。组件本次运行内有限重试沿现行规则；最终失败后不另起验证重拉或复用为业务源。最后验收复用已获响应和小型证据，不重复真实跑数。单日150～220MiB、0.5～1GiB估算及2GiB组件限制保持§10，不能把本批五行样本峰值冒充全市场内存验收。

### 14.5 本批收尾判定

代码核实与测试逐条对§14.2记录实现位置、独立依据、正反样本和实际通过结论；有界来源核验单列实际请求数、观察字段/主键及未证明范围。确认无正式资源操作、无Prod改动、无未完成入口装载及旧名兼容。可修正的实现错误在本批修正并回归；需要变更源合同、业务范围、框架顺序或已确认边界时停下提交建议，不擅自迁就测试。

以上全通过，才可判定第一批通过且具备申请第二批的条件；不自动推进第二批。若真实来源证据或框架API验证缺失，明确缺项并不得将第一批标为完整验收通过；整个数据集、正式bootstrap、历史事件和自动化仍不算完成。

### 14.6 2026-10-26第一批实际验收

§14.2硬约束已逐项核实并记录[实现及证据对账](../../reports/stock_factor_pro_batch1_20261026/README.md)。定向合并回归281项通过（契约/既有下载器199、基础结构68、框架14），既有受影响回归159项主测试及513项子测试通过；受保护Definitions加载1项通过，真实调用project_defs/validate_loadable且无本数据集可执行入口。Python默认Ruff、本工程致命错误门禁及文档完整性通过。

框架按修订设计真实验证预检正常结束与成功请求0行但无日数据的业务失败，不伪造文件/check；分区、物化storage_id/run/timestamp及绑定检查均严格核对，关闭后重开同一临时instance仍成立。最终复核修正两处基础类型计数一致性：对账匹配/缺失/额外/变化须符合实际集合数量关系，诊断样本不能超过已知数量；只增加纯结构校验和回归，没有提前实现后批集合计算或PG读取。

§14.4固定来源范围实际4次发送、0重试：组件完整请求5行、261字段，小页2/2/1，主键并集无重叠且全部业务值一致；证据已保存，收尾不再次请求。真实10000行满页、全市场性能/内存、正式PG及业务发布链路未在本批验证；这些仍按对应后批完成。测试第一次遇到沙箱本机监听权限拒绝，核明原因后按获准权限运行同一组并通过，未修改断言或skip。

结论：第一批通过。其后第二批已另获批准并按§15完成验收；第三批、正式bootstrap、历史事件和自动化均未启动。第一批没有新增需要管理员拍板的业务设计问题。

## 15. 第二批：日下载、校验与发布的编码约束

### 15.1 范围、依据、顺序及禁止项

本节落实管理员批准的第二批计划，第一批提交0daf0b5e。读本需求§5.2/5.4/6/8/9/11、当前组件模型/registry/planner/API、统一连接、现行身份生产者及moneyflow/ETF发布实现；CodeGraph核契约/下载链和现行发布函数消费者。现行资金流发布带namespace锁、dataset限制和跨次checkpoint恢复，不调用或更改它，按本节实现本数据集当前run流程；ETF内容摘要算法可参考，不带其筛股规则。

编码顺序：先日类型/源验证与取消→按列转换及内存U→纯checks→Raw/Silver候选→逐文件发布→纯覆盖→隔离集成/回归。代码落点沿§2.2：run_contracts/stk_factor_pro.py、io/stk_factor_pro_download.py、io/stk_factor_pro_candidates.py、io/stk_factor_pro_publication.py、checks/stk_factor_pro.py、asset_guards/stk_factor_pro_readiness.py。checks只含纯函数，不定义或注册正式checks。

不实现历史plan/manifest/下载、Prod导出/统计、含instance的覆盖evaluator、PG观察读取、bootstrap授权、正式assets/jobs/sensors/catalog或历史事件；不新增共享锁、线程、源配置、兼容入口、字段子契约或失败源缓存。仅临时测试资源可写。

### 15.2 内部接口、结果及对象生命周期

日下载函数`download_stk_factor_pro_day(connection, *, identity, contract, downloader=None, control=None, check_cancel, on_progress=None) -> VerifiedDaySource`；默认创建公开load下载器，替身仅用于隔离测试。固定DownloadTask(BY_POINT, points=(T.isoformat(),))。with内接单一结果、消费至结束并正常关闭；退出后核§6最终summary，再强制check_cancel，再调用已有规定的verify_stk_factor_pro_day_source。verify以当前登记契约content_digest而非外部自称摘要核身份；unit还须等于当前公开planner为该任务生成的唯一unit，拒绝伪造unit_id、point、filters/enum及范围。summary task_id须为本次session实际task_id（组件生成），不把run_id当组件task_id；同函数中的session身份另核，独立verify按native summary及唯一unit核结构。

verify创建固定临时U；字段顺序和源值按§9.1核，schema/day_source/scope摘要按§5.4.2与§8.1。来源0行仍有完整261字段U，合法source验证不把市场缺股变协议失败。使用者以同一try/finally覆盖下载与发布：失败函数自行清已建表；成功返回后由调用方在日两层完成/失败/取消后调用`release_stk_factor_pro_day_source(connection)`清固定U/expected/prior关系，并解除对VerifiedDaySource/result的引用。发布结果不含行或UnitResult。不能把临时view当独立U。

`publish_stk_factor_pro_day(connection, *, source:VerifiedDaySource, lake_root:Path, staging_root:Path, check_cancel) -> Iterator[tuple[PublishedTarget, StkFactorProFileAudit]]`固定Raw后Silver，每完成一层读回及complete后yield一次。两层都无数据/文件时迭代0项，不生成假文件/check。调用方第五批每次取到结果后先yield对应物化/check，再继续迭代；不得先list(iterator)使Silver失败丢掉Raw交接时点。Raw/Silver实际文件已发布、事件失败不回滚；关闭迭代器只收资源，不在finally中yield。

PublishedTarget沿§5.4.3固定结构，日scope三项均None、unrefreshed_count=0；checkpoint_ref精确指当前run本层complete记录。per-file PublicationRecord的字段完全采用§5.4.3现有intent/complete结构，本批只允许phase=day，history输入/ref混入拒绝。新增frozen StkFactorProPublicationRecord集中规范JSON/解析/交叉校验，未知/缺字段拒绝。intent末三项为None，complete全有；day来源只有本次day_source_digest，历史两摘要为空。禁止让这些记录保存本轮日源行。phase publication-complete与历史plan/ranges衔接在第五批编排，不由第二批造假plan摘要。

### 15.3 转换、对账及候选

HTTP实际UnitResult/每记录fields与values按§9.1处理，不复制整份行列表；两来源标量类型检查及build_stk_factor_pro_raw_batch实现共享转换，Prod片段写函数留第四批。本批只构造当前日DataFrame列和临时U，不写源片段。

Raw候选函数`build_stk_factor_pro_raw_candidate(connection, *, source, prior_path:Path|None, candidate_path:Path, run_root:Path) -> StkFactorProFileAudit`。先将合法旧B物化到本连接独立临时表，不能留下指向即将被替换文件的view；U主键唯一后生成固定expected临时表B−K+U，COPY一次Raw候选。expected在正式读回前保持不变，不能提升后从新Raw反推expected。

Silver函数沿§9.1签名，只从verified_raw_path显式转换日期建立固定expected临时表，COPY本层候选；没有旧Silver独立合并。无旧Raw且U空不COPY；有旧Raw而U空保留B，可由最终Raw重建缺失Silver。

checks提供`audit_stk_factor_pro_file(connection, *, path, expected_relation, target_trade_date, layer, diagnostics_path=None)`及内部关系结构/业务内容校验。relation为内部已创建表名，标识符验证，不接受任意SQL。schema/键/日期/数值不合法立即拒绝，不能继续JOIN制造伪计数；有效唯一键关系再按§9.2一次FULL JOIN聚合缺失/额外/变化及各字段变化，产出实际FileAudit。错误样本最多20行，完整计数仍来自整个当前日期关系；数值差异不加epsilon。来源/候选/正式读回共用转换后的目标表示，Raw摘要与Silver摘要各按本层类型计算。checks不自行开连接，正式业务路径无duckdb.connect或executemany。

### 15.4 发布安全与空结果边界

根目录在业务函数内只允许既定正式根/正式staging或隔离测试一对绝对独立目录；拒绝退役路径、任意Volumes根、符号链接、重叠/跨设备；正式Volumes根额外要求数据卷已挂载。candidate和记录必须在当前RunIdentity的run目录；构造候选前取得目标prior字节SHA，构造完成及replace前都核同一prior。候选SHA、内容、schema及计数验收→fsync→原子intent→目标/候选/取消/空间/设备复核→replace→父目录fsync→按固定expected读回→complete。

Silver构造及提升同时核对应正式Raw SHA未变；不能从变化后的Raw生成却保留旧Raw身份。内容等价的mode=reuse只保留当前正式文件，仍核本次expected和目标身份；不读取已有intent/候选当本次输入，同run发现已有日候选或日发布记录也拒绝作为续跑入口；前序步骤已写history-plan等非日发布记录不阻断日阶段。完整JSON原子写用flush/fsync/replace/父目录fsync，读回结构与字节SHA，语义与文件SHA分开。check/记录失败不删除已经发布文件；replace后取消尽力补完该文件收尾，下一文件前停止。

首次0行且无旧文件只交无文件事实，本批不提前抛day业务Failure，不保存日缓存；第五批按§4.0.1先保存缺失/统计及waiting再Failure。有效部分文件正常发布，旧Raw有效但新源0不清空。上述分支不伪造绿色。

### 15.5 纯覆盖与后续交接

实现§5.2.1 build_stk_factor_pro_coverage_keys，四个表名只来自调用方已验证内部关系；listed/full_suspend/actual每行类型DATE/VARCHAR、限定T，identity引用现行SILVER_STOCK_IDENTITY_MAP_SCHEMA的source_ts_code/latest_ts_code/valid_from/valid_to。纯函数不负责读取文件、PG前置、生命周期筛选或生成最终停牌；调用者先按§5.2及10.5准备上市/全天停牌关系，本批测试按真实生产者schema构造。

三侧原code/date先去重并集，对source_ts_code和有效期作LEFT JOIN，0映射/多映射返回全业务计数None并保留异常样本；有效后按latest_ts_code三侧统一且去重，expected=listed EXCEPT full_suspend，missing=expected EXCEPT actual，extra=actual EXCEPT expected，matched为交集。固定stk_factor_pro_coverage_missing/extra临时表保留同一结果供调用者后续COPY；每次调用先清自己旧关系，未知分支也清旧结果，避免沿旧空差集误判齐备。原业务代码/Raw/Silver不改。

### 15.6 测试、性能与收尾

新增tests/test_stk_factor_pro_candidates.py、test_stk_factor_pro_download.py、test_stk_factor_pro_publication.py、test_stk_factor_pro_coverage.py；复用来源明确的第一批5行261列保存响应和独立doc328字段校验，不重新Tushare请求、不读正式Lake/PG/Prod。隔离连接走现行connect_configured_duckdb并将temp_directory限定本测试目录、关闭扩展自动安装；规范正式默认16GB/4线程不改。

测试覆盖单一完整unit/关闭1304/summary异常/取消/字段换序；非法值/NULL负数/极小数；B−K+U、Raw→Silver及原值保持；目标/候选变动、跨设备、等价不replace、Raw成Silver失败及取消后保留；失败新run真实新调用与旧候选读取禁用；临时U解除注册后可读、finally释放及无source/day/manifest/片段写入；覆盖A/B对A/C、全天/盘中由正确上游关系区分、身份别名/缺失/过期/歧义/未知清旧差集；0新源的三类结果。标准进度只摘要，控制错误不能被回调异常隔离吞掉。

性能正常/同日补入各一次小型全链，记录行数、候选/正式/状态文件写入数、SQL/字节与耗时；保留150～220MiB日结果、0.5～1GiB峰值估算，不压测内存。每次只T、2个正式目标、1个主要DuckDB连接；源请求一日通常1页、满页继续且组件同页最多4尝试，失败新run全新，现有64MiB/2GiB边界不改。本批对真实Tushare发送0、正式IO0；公开load适配另外用假token向本机HTTP替身发送2次验证重试和标准通知；最终读回与失败完整重做成本包含在记录中，不把五行样本宣称全市场120秒已达标。

执行第一批相关/下载器回归、受影响治理/Definitions门禁、Ruff与文档检查；结果逐项映射本节硬口径。第二批验收通过再独立确认第三批，不自动推进或开展正式执行。

### 15.7 2026-10-26第二批实际验收

本批已完成并通过：定向合并373项（第一批及既有组件281、本批新增92）、既有受影响159项及Definitions加载1项，共533项主测试；另518项子测试通过。默认Ruff、src/tests致命错误门禁及文档检查通过。实现位置、独立输入依据及正反例逐项见[第二批验收记录](../../reports/stock_factor_pro_batch2_20261026/README.md)。

公开load→本机HTTP→503后重试→日适配实际经过组件代码，三类标准通知及普通回调异常隔离验证通过，假token、2次本机请求、真实Tushare请求0。第一批五日已存响应按目标T筛出10月16日1行261字段，做正常及等价更新各一次，两层全部业务值逐项对应；成本原始记录列明SQL/逻辑文件读取/字节SHA读取、候选/原子写入、最终读回及清理，不能据此宣称全市场120秒或内存峰值达标。

正常两轮unit引用数回到基线，U及转换临时关系均已释放；失败/取消清表，不以RSS回落或强制GC作证明。独立子进程在Raw已发布后退出，新进程实际重新调用下载且最终Silver为新值，未接旧候选。原T旧未返行保留、Raw先交结果后才处理Silver、等价不replace、源成功0行不造文件、已发布不回滚及覆盖未知不伪0均已验证。发布后以相同实际字节/schema/行数复用候选完整audit，避免重复整套259列JOIN；记录日期/层/run物理路径、+08时刻、候选固定位置及挂载门槛有反向测试。

首次0源的完整缺失/阶段观察后业务Failure，含instance的readiness/覆盖复用及PG事件，仍由第五批落实；第三批、第四批当前完成状态见§16.4、§17.7，正式装配尚未实施。本批不存在新增需管理员拍板的业务设计问题，具备申请第三批条件，不自动推进。

### 15.8 提交后的独立审计（2026-10-26）

第二批已提交`5edb6409`，未push。发现§15.4的符号链接拒绝检查未在候选生成前落实：run目录下candidates子目录可指向外部，COPY先写出候选，发布函数随后才报错。1行临时样本已复现，正式文件未替换。本轮91项隔离回归通过，但既有根目录符号链接测试未覆盖该分支。暂停§15.7的第三批推进条件，先修候选写入前的路径检查、补Raw/Silver反例及正常run交接回归，再重新验收；不改变业务设计，不增加锁。本轮未修代码。完整依据与建议见[独立审计](../../reports/stock_factor_pro_batch2_20261026/independent-audit.md)。

### 15.9 第二批候选路径修复方案（2026-10-26，已批准）

目标是修正§15.8已复现的写入顺序错误：Raw/Silver候选的完整路径在首次目录创建和COPY之前就必须被拒绝，不能先写到符号链接指向的位置再报错。本轮只修改`io/stk_factor_pro_candidates.py`、`io/stk_factor_pro_publication.py`及对应候选/发布测试，报告同步原方案与本LLD；不改字段、下载模式、源配置、正式资产/任务或其他数据集，不开发第三批。

**依据及依赖：**CodeGraph与全仓引用搜索确认两个候选构造函数当前各只有日发布函数这个正式调用方，另有隔离测试替身；未装配PG/正式资产。现行`_safe`已有绝对路径、父级遍历、任意祖先符号链接及退役根拒绝规则，只需把它移为候选模块内`require_stk_factor_pro_safe_path(path:Path)->None`并由发布模块引用同一函数，不复制规则、不反向import发布模块、不新增通用平台或配置。

**内部接口及调用顺序：**

1. 新增`require_stk_factor_pro_candidate_path(*, candidate_path:Path, run_root:Path)->None`，对run_root及完整candidate_path使用上述同一安全函数，并要求candidate严格位于`run_root/candidates/`下、不是该目录本身；现存候选文件拒绝覆盖。日发布仍固定生成`candidates/day/raw/data.parquet`和`candidates/day/silver/data.parquet`，run_root只由当前RunIdentity及既定staging路径函数产生。这里不改变日目标和候选命名，也不通过resolve把非法链接转换为合法路径。
2. `build_stk_factor_pro_raw_candidate`与`build_stk_factor_pro_silver_candidate`均增加必填`run_root:Path`关键字参数，唯一正式调用方同步传当前run目录，不保留旧签名或缺省兜底。两个构造函数在执行候选SQL前先检查路径；已有计算完成后、mkdir前重检，mkdir后、COPY前再检。任何检查失败立即抛ValueError，不能继续COPY或记录intent。
3. 日发布入口在旧候选存在性判断前对两层固定候选路径作预检查；Raw交付后进入Silver时，候选构造函数仍独立重检，覆盖业务处理Raw结果期间出现的错误子目录。后续发布前的候选/目标校验、prior SHA、设备/空间及原子替换流程保留。
4. 允许先前步骤已经写入`history-plan`的普通run目录；拒绝越界、相对路径、`..`、存在或悬空的符号链接及旧日候选。检查只在当前任务路径上读取目录元信息，不扫描其他任务或全湖。

**读写、失败及性能边界：**正常仍只有T日内存源、两个候选/两个正式目标及既有逐文件记录，网络/SQL/数据行/候选数/正式写入数不增加；新增成本只是有限路径深度的元信息检查，单日固定两层。非法路径在候选写入前结束，预存Raw/Silver及前序名单不删不改；若Raw已经发布后才发现Silver路径异常，则保留Raw及其完成记录，Silver不生成，调用方finally清理内存。获准的新run按原规则重新下载，失败候选不复用；不引入锁、线程或并发修改目录的对抗性机制，不声称重复路径检查能提供多进程安全。最终验收复用1行261字段样本，失败重做与最终读回沿§15.6，无正式IO、无全量跑数。

**硬口径与验收映射：**

| 约束 | 代码落点 | 正向/反向验证 |
| --- | --- | --- |
| 首次候选mkdir/COPY前拒绝链接 | 共用路径检查及两候选函数 | 原复现：run下candidates指向外部空目录；报错且外部目录没有任何新增子目录/文件、正式测试目标0文件 |
| Raw/Silver均由构造函数保护，不只依赖入口 | 两候选函数必填run_root | 直接调用两函数，候选叶文件、层目录的已存在/悬空链接均在写前拒绝；外部文件内容保持不变 |
| 绑定当前run，禁止越界及旧候选 | candidate_path精确归属检查、发布固定路径 | 相对路径、`..`、其他run路径、已有候选拒绝，断言COPY未执行 |
| Raw先交付后Silver路径仍复核 | 日发布与Silver构造入口 | Raw yield后设置Silver子目录链接；下一次迭代拒绝，Raw内容及complete保留，链接指向处没有新增 |
| 正常目录不误拦 | 原run目录及日发布 | 存在history-plan仍正常生成两层，名单内容不改；既有合并、等价发布及失败新下载回归保留 |

先增加能在修复前暴露真实越界写入的反例并确认失败，再实施修复；本批四个离线测试文件（仅排除本机HTTP适配测试）及修改文件Ruff、全src/tests致命错误门禁、文档完整性执行一次。HTTP/组件协议未变，本轮不重复源请求；独立审计继续覆盖源生命周期、取消/清理、Raw→Silver、失败新下载、纯覆盖。通过后回填实际结果，未通过不恢复第三批条件。

### 15.10 路径修复后的验收与独立复核（2026-10-26）

§15.9已落实到两个候选/发布模块及两份测试，所有正式调用方同步必填run_root。原布局4项在修复前实际失败、修复后通过；18项直接builder反例明确先于任何SQL拒绝，1项history-plan普通目录正例保留，针对性合计23项通过。第二批四文件离线回归113项通过、1项本机HTTP适配明确未重复、23.22秒；默认Ruff、全src/tests致命错误及文档检查通过。没有新增skip、未改HTTP测试断言，HTTP代码及组件未变。

1行261字段读回仍正确，正常/等价更新0.5057/0.8806秒，52/70条SQL、候选各2份、正式替换2/0次，没有增加数据IO或源请求，不把该样本当全市场预算验收。修复前后完整输出与成本见[独立审计](../../reports/stock_factor_pro_batch2_20261026/independent-audit.md)及[path-fix-results.json](../../reports/stock_factor_pro_batch2_20261026/path-fix-results.json)。失败不写外部位置，Raw已完成而Silver失败仍保留Raw和complete；重试新run重新下载的原规则不变。

修复后独立只读复核全部调用方与写前检查，并复核本批源生命周期、取消/清理、两层合并发布、失败新下载及纯覆盖，未发现新的确证问题。CodeGraph修改前explore、修改后sync/status完成。§15.8的路径缺陷及验收暂停关闭，第二批具备申请第三批条件；本轮未提交、未push，没有正式执行，不自动推进第三批。

## 16. 第三批：历史回刷的编码约定与开工核验

### 16.1 目标、范围与现有代码依据

第三批只完成方案§13.1的复权变化名单、原完整范围、当前run完整历史源、20交易日合并及d<T的两层发布/完整范围依据。第一批契约及基础身份、第二批日转换/纯检查/取消/逐文件发布和路径修复直接复用；本节约定已按批准计划实现，实际验收见§16.4和[第三批记录](../../reports/stock_factor_pro_batch3_20261026/README.md)。接口调用和影响面已通过CodeGraph及实际源码核对。

`stk_factor_pro_http_rows`与`build_stk_factor_pro_raw_batch`复用完整261字段和标量转换；历史层另核任务规划的unit/code/start/end，不能仅凭result.unit自证。Raw候选在本数据集内抽出“已核单日关系＋实际处理日期”的共用构造，日入口仍接VerifiedDaySource，历史入口接本批临时表中的日期U；关系名由内部固定生成，不接受配置SQL。Silver候选复用verified_raw_path/target_trade_date/run_root，逐日期处理并清理expected关系。发布记录/解析器已按§5.4.3在同一实现扩phase/history和实际d，保留所有day字段互斥与路径反例，不复制另一套writer。

该共用构造固定为`build_stk_factor_pro_raw_candidate_from_relation(connection, *, source_relation, target_trade_date, prior_path, candidate_path, run_root)`。source_relation只允许本模块固定的DAY_SOURCE或HISTORY_DAY_SOURCE（stk_factor_pro_history_day_source），处理日期必须为精确DATE；同用DAY_PRIOR、RAW_EXPECTED临时表和既有B−K+U/候选核验。日wrapper继续校验VerifiedDaySource，传入DAY_SOURCE和原T；历史调用者先从本批源表物化当日HISTORY_DAY_SOURCE，再显式传d。不接收外部SQL、任意关系名或较宽日期集合，候选写前路径检查保持不变。

不在本批实现bootstrap批准/导出/统计、正式PG结果读取、覆盖evaluator、job/repair装配、sensor/catalog/历史事件或正式执行；不修改公共下载器、Prod、已有数据集、配置来源，不新增状态平台、锁或线程。只为本批在原指定模块落实类型、函数与隔离测试。

### 16.2 完整接口、内部记录与后批分工

以下均为本数据集内部接口，不新增管理员输入。类型集中在`defs/run_contracts/stk_factor_pro.py`；已有RecordRef、RunIdentity、ContractIdentity、HistoryPlanReason、StkFactorProRawCoverage、StkFactorProTargetSilver、PublishedTarget直接复用。HistoryRange/HistoryPlanRecord/FactorFileRef/SourceCompleteRecord严格按§5.4闭合结构落实为冻结dataclass，不另维护一套字段表。新增的起点参数记录和历史资格记录只封装已有信息：

```python
@dataclass(frozen=True, slots=True)
class StkFactorProHistoryStart:
    ts_code: str
    start_date: date | None
    earliest_basis_kind: int | None  # 仅1/2，规则见§5.4.3
    earliest_basis_date: date | None

# HistoryEligibilityRecord精确对应§5.4.3 history-eligibility.json：
# record_version, identity, history_plan_digest, history_ranges_digest,
# raw_coverage, target_silver, evaluated_at。
# VerifiedSource是当前run实际核验的结果，只包含以下引用/身份，不放下载行：
@dataclass(frozen=True, slots=True)
class VerifiedSource:
    identity: RunIdentity
    contract: ContractIdentity
    source_complete: SourceCompleteRecord
    source_complete_ref: RecordRef
```

StkFactorProHistoryStart来自§5.1.1真实记录读取/批量聚合，不新增存储；known start的三个日期/种类字段全有，start_date等于earliest_basis_date且不晚于T，未知时全None。重复代码、非法日期/kind或输入窄范围裁短原可信边界均拒绝。bootstrap读取/批准核验仍由第四/第五批完成，它提供已核内部记录；不通过跨模块import读取尚未实现的bootstrap执行器。

```python
def resolve_stk_factor_pro_history_starts(
    connection, *, lake_root: Path, target_trade_date: date,
    codes: tuple[str, ...], known_starts: tuple[StkFactorProHistoryStart, ...],
    approved_raw_dates: tuple[date, ...], check_cancel: Callable[[], None],
) -> tuple[StkFactorProHistoryStart, ...]: ...

def build_stk_factor_pro_history_plan(
    connection, *, identity: RunIdentity, contract: ContractIdentity,
    lake_root: Path, staging_root: Path,
    factor_t: FactorFileRef, factor_p: FactorFileRef,
    prior_results: StkFactorProRecordedResults,
    history_starts: tuple[StkFactorProHistoryStart, ...],
    check_cancel: Callable[[], None],
) -> HistoryPlanRecord: ...

def download_stk_factor_pro_history(
    connection, *, identity: RunIdentity, contract: ContractIdentity,
    plan: HistoryPlanRecord, ranges: tuple[HistoryRange, ...],
    prior_results: StkFactorProRecordedResults,
    eligibility: HistoryEligibilityRecord,
    lake_root: Path, staging_root: Path,
    recheck_inputs: Callable[[], tuple[
        FactorFileRef, FactorFileRef,
        StkFactorProRawCoverage, StkFactorProTargetSilver,
    ]],
    downloader=None, control=None, check_cancel: Callable[[], None],
    on_progress=None,
) -> VerifiedSource: ...

def publish_stk_factor_pro_history(
    connection, *, source: VerifiedSource,
    plan: HistoryPlanRecord, ranges: tuple[HistoryRange, ...],
    lake_root: Path, staging_root: Path,
    calendar: tuple[date, ...], registered_dates: tuple[date, ...],
    recheck_inputs: Callable[[], tuple[
        FactorFileRef, FactorFileRef,
        StkFactorProRawCoverage, StkFactorProTargetSilver,
    ]],
    check_cancel: Callable[[], None],
) -> Iterator[tuple[PublishedTarget, StkFactorProFileAudit | None]]: ...
```

`resolve...`只对known_starts不能解决的代码做一次§5.1.1批量聚合，approved_raw_dates是已有授权/可信文件范围的内部日期tuple，须已覆盖需确认的可信既有历史；不能由空值默认扩成全湖或由当前20日批次生成。没有来源/日期范围证明时返回对应未知，交§5.1.2处理，不猜值。普通日更与首次补数共用同一方法，repair原授权起点仍保留，不重新扩大授权。

`build...`按固定路径核T/P文件的日期、schema、键、有限值和传入SHA（前后身份一致），重新比较并写读回本runplan/ranges。需要判定原因6或解释缺T/P时，只读既有silver_stock_lifecycle_path指向的正式生命周期文件，按现行schema/人民币股票和DATE上市退市区间核本次对象，读前后文件身份稳定；缺失或不明就保留未知，不调用PG或用当前上市快照替代。prior_results严格采用§6.2完整冻结类型。确认无旧事实时传全None/空tuple的合法结果，查询失败或坏引用不能伪装为空。规划阶段允许保留未知行；下载阶段的入口核完整原待请求范围，未知或无实际工作不得启动session。正常编排按§5.1.2等待/no_action；若误调用下载函数则作为输入合同错误拒绝，不能返回伪造VerifiedSource。

`recheck_inputs`由第五批编排装配，第三批只消费其四个实际冻结结果；不能用常量True或调用方passed参数替代。它在历史下载前、首次历史提升前、完整发布记录形成前分别调用，校验原T/P、原T Raw complete/check及Silver ready/对应当前Raw。T/P文件字节变化时按§5.4.2重新核本请求范围的业务因子投影；范围外其他股票变化不推翻本范围，实际业务输入变化则停止，不重写原计划。该回调不放在可隔离异常的进度通知里，不查询每行/每历史日期；第三批不import instance读取器，隔离样本按真实合同提供结果。

`download...`必须核plan/ranges/eligibility属于当前run和原T、摘要相互匹配、Raw/Silver资格为真；从整份完整ranges及已有独立成功引用按§5.1.2生成expected_units，逐项核实际unit/股票/闭区间。每unit完整落盘/读回/释放，全部session成功退出、manifest逐项核验后写source-complete并调用§5.4.1 verify得到VerifiedSource。manifest的unit_key/file_relative_path精确采用§5.4.2/5.4.3，不依赖下载序号猜范围。一次失败不构造可交付的VerifiedSource，不隐式重试业务保存。

历史unit在同一连接的固定`stk_factor_pro_history_current_unit`临时表中完成源转换，复用现有HTTP完整字段投影和`build_stk_factor_pro_raw_batch`，不复制整份Python行列表。`checks/stk_factor_pro.py::require_factor_history_relation(connection, relation, *, object_code, start_date, end_date)`集中校验完整Raw schema、该股、闭区间内合法源日期、唯一键及有限数值，返回行数/schema；保存前及当前run源文件读回使用同一规则，日检查仍保持严格单日期语义。保存后还按全部业务字段与本次转换关系对账，不能只凭行数/SHA相符认为没有传输差异。新源文件位于固定source/history命名空间，按既有安全路径和原子写入办法保存；每unit完成后解除DataFrame注册、DROP临时表并释放UnitResult，再领取下一unit。全部会话关闭及summary核验前不生成完整manifest/source-complete；失败仅保留当前run已写证据。进度回调只转发组件标准摘要，不承担保存动作。

unit收尾逐项尝试删除读回view、删除当前unit表和解除DataFrame注册；一项失败不能跳过后两项。已有业务主错误时，将清理错误附到主错误后继续抛出主错误；正常收尾发生清理失败时则报告清理失败，不生成可发布的完整源结果。

`publish...`重新核当前run源记录及引用、T/P/资格和calendar/registered_dates。本次股票/日期范围、unrefreshed差集与scope摘要只从source.source_complete.expected_units复算，并与manifest逐项核对；完整plan/ranges用于原授权和摘要上界，不把其中已独立成功或原因6对象计入本次缺失。然后按§8.2.1只处理d<T；每层完成实际读回及complete后yield。无旧无源日期返回skip_no_file=True的PublishedTarget及audit=None，checkpoint_ref/hash为None；无实际文件就不构造FileAudit或事件。实际文件项必须audit非None且通过，调用方依据skip_no_file分支，不能把无文件项当有文件物化。全部实际目标和skip事实按日期/层有序写publication/history/publication-complete.json，调用方按固定路径读回；任一旧键未刷新时按§8.1保留差集、缺少完整发布记录并失败。第五批负责在各yield点绑定真实DG事件、保存waiting/完成观察及run终态，不能list迭代器等全部结束后才交付Raw。

调用方必须在finally中明确关闭该迭代器，包含业务处理某个yield结果时抛错、取消或提前结束；不能等待垃圾回收。以下是第五批装配须遵守的控制结构，results为上述接口返回的迭代器，handle_result为业务逐层处理位置。若业务错误与close清理错误同时发生，继续抛最初业务错误，把清理错误附在其后；只有清理错误时才直接报告清理错误。普通contextlib.closing不能单独保证这一点。

```python
primary = None
try:
    for target, audit in results:
        handle_result(target, audit)
except BaseException as error:
    primary = error
    raise
finally:
    try:
        results.close()
    except BaseException as cleanup:
        if primary is None:
            raise
        primary.add_note(f"历史发布关闭同时失败：{type(cleanup).__name__}")
```

| 输入事实 | 第三批职责 | 对应后批职责 |
| --- | --- | --- |
| 权威T/P文件、可信每股起点 | 按现有schema/日期/范围和引用验证，比较/规划；缺依据保持未知 | 第四批可产生初始化依据，第五批从既有正式入口取得并准备输入，不改变起点规则 |
| 同T旧未完/完整成功事实 | 消费StkFactorProRecordedResults及精确引用，核原范围，不读失败源 | 第五批实现§6.2的有界PG读取与最终producer状态核验 |
| 原T Raw/Silver资格、开始事实及运行互斥 | 按类型/日期/指纹和现有require规则保护下载/发布 | 第五批正式evaluator/开始观察/互斥及事件装配；本批不加PG查询 |
| 日历与已登记日期 | 接受明确tuple，核源日期及d<T计划，不自动注册 | 第四/六批各自获准的注册流程，不因本批测试声明正式已注册 |

### 16.3 编码顺序、失败及资源边界

1. 在run_contracts落实上述历史类型、§5.4摘要和闭合读写验证；unit_key由同一函数供manifest写入及核验使用。
2. 在既定io/stk_factor_pro_history.py实现起点取得、T/P比较、原未完/成功范围核对及plan/ranges读写。未知、真新股、已有成功分别按§5.1.2，不用WHERE start_date IS NOT NULL掩盖未知。
3. 在既定io/stk_factor_pro_download.py实现当前run历史保存及VerifiedSource；源/manifest只位于本run/source/history，使用同一safe_path和该namespace归属规则，写目录/文件前检查，不能放宽candidates保护。
4. 在既定candidates/publication/checks模块内复用字段和合并/原子发布算法，按显式日期适配历史，落实§8.2.1批关系。原day入口仍只接VerifiedDaySource，原日路径/类型/0行及失败重下回归保留。
5. 实现范围publication-complete及原键差集汇总；文件完成事实只说明当前物理结果，producer最终成功由第五批使用DG事实确认。不提前伪造run成功。
6. 用小型真实schema夹具覆盖本节和§11；对照所有硬约束给代码、正反例和性能证据，第三批通过后才独立确认第四批，不开展正式执行。

沿§10现有连接和容量默认，不新增配置或请求预算。设需新下载C股、各H_i行、历史D个交易日，正常请求按§10的sum(floor(H_i/10000)+1)，失败新run同范围重下；本批同页重试沿组件，20日不改变请求数。当前run保存C个完整源unit及manifest，批源查询ceil(D/20)次、每批最多40个日期/层目标，当前日期B/U及两个候选之外不持有全部历史Python行；完整源、失败证据、批临时关系/受控spill、当前候选、读回和最终验收均计空间与耗时。源0行保留schema；半unit不交付。受控路径/空间/设备或输入无法确认时先停，不截字段/股票/日期，不静默删除旧源腾空间。

任何下载、保存、候选、文件或业务接收异常都关闭session/迭代器并在finally清表；Raw已发布Silver失败仍保留Raw，后续新run重新下载原完整失败范围，不能从第几个unit/日期/批次接续。取消前后行为继续按§6，replace后尽力收尾当前文件，下一文件前停止；错误定位使用既有业务类别及组件错误码，不新增随意字符串枚举。正式DG/PG/Prod/Lake操作及全局读取仍分别批准，本节的实现和隔离验收不替代正式执行授权。

### 16.4 启动条件和本批验收对账

| 启动/验收项 | 明确落点及必须证明的行为 |
| --- | --- |
| 前两批基础与路径修复 | 第一批0daf0b5e、第二批5edb6409及修复0e8b5baa；复用已提交证据，未改变时不重复真实来源跑数 |
| 历史起点没有新业务决策 | §5.1.1与§10.7.2同一规则；原可信更早边界不裁短、一次代码/日期有界MIN、未知不默认；所有入口适用 |
| 跨批输入可独立编码 | §16.2；第三批不依赖尚未实现的PG/导出执行器，已核冻结输入按现行schema夹具验证；查询失败不能由空输入代替 |
| 完整名单与下载范围 | §5.1.2；无变化、旧pending且因子回等、匹配独立成功、原因6、关键未知各有独立小样本；A/B有B未知时源请求/历史提升0，plan仍有B |
| 摘要/文件/记录生产者消费者一致 | unit_key准确封装、固定unit源路径、manifest逐项范围及字节SHA；换run/路径不改业务摘要，改code/边界/值必变；day/history来源互斥反例保留 |
| 当前源完整与关闭 | 每完整unit读回及释放；全部会话summary/关闭通过才形成当前runVerifiedSource，1304/错unit/错股票/超范围/旧run文件均零提升 |
| 按20日处理并保持其他数据 | §8.2.1与§11；1/20/21/41/45边界及源读取查询数、T边界、无关股票全部业务值不变、临时关系释放、Raw后Silver失败保留 |
| 缺原键及重入 | 先保存真实缺失，原键非0不得写完整记录；新run实际重下整个失败范围，旧源一旦作为输入读取测试立即失败 |
| 性能与证据范围 | §11.1规定的一股至多20日有界样本、宽日期文件与成本记录；复用已有来源响应，不做全市场/17股全历史压测；全市场/10000真实满页和正式PG事件验收未执行不写成通过 |

2026-10-26第三批已按管理员批准的七步顺序完成：历史类型和统一记录、起点/完整名单、实际unit与资格、完整源下载、20日逐日两层发布、缺旧键及范围完成、最终回归与独立审计。历史源verify已按批准补充必传connection，始终复用调用方连接；未修改公共下载器、源契约或其他数据集，未新增运行配置、连接、线程或正式入口。

本数据集530项及受保护Definitions/治理门禁126项，共656项通过。合并回归中两项因沙箱不能绑定本机假HTTP端口而失败，获得对应端口权限后，与另一个既有localhost用例合计3项补验通过；断言未删改，未遗留失败。Ruff默认及致命规则、文档完整性、差异空白和CodeGraph sync/status通过。独立审计未发现本批待拍板业务问题；逐条实现/正反测试及原始输出见[第三批验收记录](../../reports/stock_factor_pro_batch3_20261026/README.md)。

保存的真实5行261字段响应经过实际组件registry/planner/session、历史保存和4个d<T的8个两层目标；一份5,568行旧Raw中的5,567只无关股票在两层全部业务字段保持一致，T文件不变。真实子进程在完整源及首Raw后退出，新进程重新请求原完整五日范围，旧源/候选读取护栏为0。源边界为已有响应和离线transport，资格为按真实结构构造的冻结输入；没有真实Tushare请求、正式PG查询或正式资源操作。

正常、真实退出、重新下载、最终读回的查询/SHA/文件/空间与耗时分阶段见[integration-evidence.json](../../reports/stock_factor_pro_batch3_20261026/integration-evidence.json)。最终范围收尾对实际存在的目标文件各补一次字节SHA（至多2D次）及小记录引用核验，不重读所有unit或再做261字段JOIN；清理调用责任按§16.2明确。查询数不等同物理IO，磁盘峰值仅在写入边界采样，未测RSS、17股全历史或真实10,000满页，不能据此宣称全历史性能和正式事件验收通过。

第三批通过隔离验收，具备制定第四批详细计划的条件；不自动推进第四批。bootstrap仍按§10独立批准、导出和恢复合同实施，不能套用Tushare失败重新下载规则或把本批固定单日期关系当作Prod导出入口。正式执行及自动化启用仍另行授权。

### 16.5 提交后4处清理修正（2026-10-26，已批准）

**目标及范围。**提交`d1564587`后的独立审计已用真实临时DuckDB复现：记录写入、源字段核验、名单规划取消或因子变化已经失败，随后清理也失败时，最外层错误被替代，部分清理不再执行。这里只修`io/stk_factor_pro_history.py`的4处finally，并新增`tests/test_stk_factor_pro_history_cleanup.py`；原方案、报告同步结果。不改已通过的下载unit/历史发布清理，不改业务字段、范围、摘要、记录结构、接口、配置或正式入口，不推进第四批。

**当前代码与依赖。**CodeGraph及实际源码确认：记录writer供ranges/manifest共用，源核验用于下载后和发布前，名单规划及三次输入再核仍用同一主要连接。download和publication已经依赖history；history不能为复用清理而反向import它们，否则形成循环依赖。只在本模块定义一个私有contextmanager，四处使用同一规则，不移动已有实现、不新增公共平台。

**私有接口及错误规则。**固定为`_history_resource_cleanup(*releases: Callable[[], object]) -> Iterator[None]`，由contextmanager装饰。releases仅由本模块以下固定unregister/DROP动作构成，不接受运营配置、任意SQL或外部业务回调。

1. 在进入主体前令primary=None；主体任意BaseException（包括取消/退出）均保存原对象并原样raise。
2. finally按给定顺序逐项调用清理。每项DuckDBError单独收集后继续，不因第一项失败跳过第二项。DuckDB的IOException、InterruptException、InvalidInputException均在此范围；不新增错误码或把清理失败转换为空结果。
3. 有primary时，在同一原异常对象的notes中附每项清理错误的类型，不用后续异常替代原错误。没有primary但有清理错误时，抛第一个清理错误对象，附完整清理错误类型；没有错误时正常返回。清理错误不得静默吞掉，不重新执行COPY、请求或清理。
4. 四个入口保持普通同步函数，不改为生成器；内部contextmanager的yield仅用于管理with范围，不套用publication生成器.close对GeneratorExit的专有处理。成功或失败清理只释放本函数使用的临时关系/注册，不关闭调用方连接、不回滚或删除任何文件。

| 入口 | 进入with的位置 | 固定清理顺序及约束 |
| --- | --- | --- |
| `_write_rows` | DataFrame注册/临时表构造前，包住原写入及读回全过程 | unregister(`stk_factor_pro_record_frame`)；DROP TABLE IF EXISTS `stk_factor_pro_record_rows`。合法0行同样适用，不改变12/17列schema或固定排序 |
| `_verify_source_unit` | CREATE TEMP VIEW前 | DROP VIEW IF EXISTS `stk_factor_pro_verified_source_unit`；源字段、代码、日期、行数及SHA检查保持不变 |
| `build_stk_factor_pro_history_plan` | T/P读取和比较前 | DROP TABLE IF EXISTS `stk_factor_pro_history_factor_t`，再DROP同名`factor_p`；保存名单后的失败仍报告失败，已写证据保留 |
| `recheck_stk_factor_pro_history_inputs` | 实际因子临时关系可能创建前 | DROP TABLE IF EXISTS `stk_factor_pro_history_recheck_t`，再DROP同名`recheck_p`；范围外因子变化仍允许，范围内变化仍停止 |

**测试与验收。**先写4入口×4模式共16项：正常、仅主体失败、仅首项清理失败、主体与首项清理同时失败。必须在修复前确认能暴露原缺陷，再实施修复；不得改变旧夹具/预期迎合实现。

- writer走正式plan writer及完整12列真实范围夹具，确认COPY实际进入后才注入本地写入错误；首项unregister再失败，必须仍尝试DROP并核实际表已删除。
- 源核验使用已登记完整合同的缺列文件，让真实字段检查报错；清理再失败时，仍抛同一个字段错误对象。失败的DROP不要求最终成功，不伪造资源已清空。
- 规划在T/P两表均已创建后由原check_cancel抛同一个取消对象；首DROP失败后仍尝试第二张表，正常/仅清理失败也核表的实际状态。
- 再核的主体失败用目标股因子由2变3触发真实检查；正常/仅清理失败则只修订范围外股票的T/P值，让两张临时表都实际建立，证明合法变化不误拦，第二个DROP真实执行。
- 主体失败断言异常对象身份保持；双故障另断言清理notes；仅清理失败断言首个清理错误对象可见并尝试剩余项。原错误仍可定位，不能只比较报错文本。

回归覆盖原记录/源核验/起点/规划/实际unit/再核及既有下载、发布清理测试，另做小型正常历史发布。没有更改批次/合并算法，不重复1/20/21/41/45全套或真实请求，不重跑正式Definitions/事件写入；既有保护门禁证据只覆盖未改变的装配边界。执行项目默认及致命Ruff、文档/空白检查，并独立复核四处调用与剩余finally。

**资源与失败开销。**不增加对象、日期、unit、分页、业务SQL、COPY、SHA、候选或正式写入。正常清理次数不变：writer2项、源核验1项、规划2项、再核2项；发生首项清理失败时最多补做原本被跳过的1项。只保存至多2个清理异常引用，不加锁、线程、连接、持久状态或清理重试。新增16项故障回归仅用临时资源、一股源1行261列或两股T/P小文件；正常及进程退出后的链路复用既有一股五日响应和一份宽日期文件，不扩大原有界验证范围。故障后重做及最终验收沿原完整新下载与文件保留规则，不读失败缓存，不做全历史跑数。

**本次修复验收结果。**上述同一16项测试修前8失败/8通过（1.51秒），修后16通过（1.29秒），未调整断言消除失败。包含新测试的17文件相关回归307项通过（46.01秒）；独立复核又验证多项清理同时失败和取消保持，未发现新确定问题。已核四处都在创建自身资源前进入同一helper、finally没有吞错的return、T/P动作各自固定绑定；仅清理失败不能返回计划/事实或可发布源。

复用保存响应重新验证正常链和真实进程退出后全范围重下，共8.497秒；新run仍1个完整unit/5行、8历史目标、旧source/candidates读取0。正常链SQL371条、批源CTAS1次，与修前相同；T不覆盖、无关5,567股261字段不变、临时关系清空。证据单独保存，不覆盖原验收JSON，见[修复后链路](../../reports/stock_factor_pro_batch3_20261026/cleanup-chain-evidence.json)及[修复回归](../../reports/stock_factor_pro_batch3_20261026/cleanup-regression.json)。没有据此扩大真实源/正式事件或全历史性能结论。

默认Ruff、全src/tests致命规则、CodeGraph sync/status、文档及差异空白检查通过；4处清理P2关闭，第三批恢复完整的隔离验收结论。该次仅单模块生产修正及新增测试/文档；第四批当前完成状态见§17.7，正式执行未进行；完整发现及修复过程见[独立审计](../../reports/stock_factor_pro_batch3_20261026/independent-audit.md)。

## 17. 第四批编码约束与逐步验收

2026-10-26管理员批准方案§13.6的八步开发。本节保留该批编码约束及已有实现依据；主体实现及§17.8五项修复现均已实现并完成隔离验收，正式操作未执行。§9～11全部合同继续生效；不修改公共下载器、261字段源契约、Prod实现或其他数据集。

### 17.1 代码结构与依赖

对外接口保持在`defs/bootstrap/stk_factor_pro_history.py`，负责唯一入口、依赖绑定及重导出§10既定函数。同目录私有实现按稳定职责分为`stk_factor_pro_bootstrap_records.py`（批准/路径引用/记录与摘要）、`stk_factor_pro_bootstrap_source.py`（月规划、来源预检、游标及完整日）、`stk_factor_pro_bootstrap_publication.py`（候选/逐文件恢复）、`stk_factor_pro_bootstrap_coverage.py`（本地依据、日期统计、summary和补数更新）。它们不是新增运行入口；不新增子目录、CLI、job、sensor、check或配置。公共冻结类型仍统一在run_contracts/stk_factor_pro.py，受控路径统一在paths.py。依赖单向：入口调用各实现；source/publication/coverage可依赖records和既有纯IO/check/contract；records不得反向导入入口或后三模块。日更/历史IO不得import bootstrap。

新增固定内部单日关系`BOOTSTRAP_DAY_SOURCE`供共用Raw候选构造使用；该来源必须prior_path=None，只生成完整源U，不做正式旧文件合并。DAY_SOURCE/HISTORY_DAY_SOURCE现行行为不变，日入口仍要求VerifiedDaySource。首次候选创建继续使用既有禁止覆盖检查；bootstrap恢复自行核既存候选及原intent，不能放宽公共候选保护。

### 17.2 合同、路径与读写

严格落实§10所有frozen类型及已有类型复用。完整FileAudit的Path显式转文本再读回Path；正式path由日期/层复算，diagnostics仅允许本operation受控位置。不可变approval/source-complete/intent/complete写入相同内容可读回，不同内容拒绝；result/summary按§10原子替换。JSON拒绝重复键、未知/缺字段、bool冒充计数、非法ISO日期/时区、坏摘要及引用。不存在固定记录才返回None，损坏不伪装成未完成。文件字节SHA、业务内容SHA与各kind摘要按原精确投影计算，不新造hash算法，不将operation伪装成run。

### 17.3 顺序、来源读取与失败

主流程只接受受控operation标识及现有resource/instance内部依赖，读取固定approval；不接受根目录、表、字段、SQL、overwrite、模式开关或运营传入的passed/event id。正式根由现有资源/默认路径解析；隔离测试通过内部依赖使用临时目录。入口拥有唯一主要DuckDB连接，helper只借用并释放自身关系。

1. 入口先核§4.2活动任务，再读回批准、计数、来源证据与日完成事实；核实际剩余工作，不按summary自称完成跳过核验。
2. 月规划完整覆盖批准源首尾全部自然日期，含0源日、退市股票及2020前数据；selected_dates仅扣同operation已核完整日期。
3. 本批实现§4.2.3最小活动reader/require及固定五状态，两个job每个limit=2。入口和首次提升前各一次；bootstrap own_run_id=None，失败立即停止，不等待/取消/重试。真实物化/check和完成结果reader仍第五批实现。
4. bootstrap注册原批准范围中已确认SSE开市日，包括源0开市日；只新增，不删除，不注册休市/未知。这不是第六批日常注册sensor，正式分区写入仍独立批准。
5. 每月借现有只读事务，control cursor设置绑定timeout，named cursor固定without hold及5000批量；显式261列、闭开月范围、DATE数组及R+1。不fetchall、不offset、不普通cursor取明细、不累计整月，不更改resource。
6. 每批先核R+1/字段/日期/严格键序，保存并读回完整片段后释放；只有下一日期或真实EOF关闭日期。遇R+1的当前批在写片段及回调前拒绝，此前完整日期保留。EOF复核selected各日及合计计数，源0也必须有EOF证明。
7. 完整日记录保存/读回后，同线程同连接同步process；真实回调异常立即停止fetch；已分类的坏覆盖依据正常返回未知，不属于异常。Raw/Silver完成后才统计；半日不发布，0源无旧文件不造空业务文件。
8. 收尾逐个尝试关闭named/control cursor及事务，再释放主要DuckDB；保留业务/取消原始异常，关闭异常作为附注；仅关闭失败时任务失败。现有resource退出若另抛异常，由本数据集局部包装保留原异常，不改公共resource。

### 17.4 发布与恢复的准确分支

完整源→候选→完整检查并冻结原SHA→描述候选且核原SHA→核维护/活动及目标→保存意图前再核原SHA→保存读回intent→提升前核原SHA/目标/空间→原子replace或等价reuse→正式读回→保存读回complete。SHA取值和两种模式按§10.4、§17.8.1，不能将重算出的变化文件SHA写成新expected。首次无目标才replace；等价目标reuse；不同目标拒绝。已有候选无intent时按固定路径/完整源/全部字段核验，合法才继续首次意图，非法保留证据并停止。intent一旦存在不得改prior/expected。

目标等于expected时可由源/最终Raw重建必要期望关系并核正式文件后补complete，不要求已被移走的候选仍存在；目标等于prior且候选完整时沿原intent继续；两者都不符则停止。Raw完整Silver未完时从当前已核Raw继续。两层complete与身份未变时复用检查事实，不再扫源261列。

半日失败整日重读；完整日源可复用；记录不得覆盖旧attempt片段。需要来源或业务文件恢复时核原维护窗口；仅统计不访问Prod，窗口过期不阻拦。未知改写、缺文件或缺合法补数凭据时停止，不自动改为旧Prod恢复。统计失败不回滚已发布文件。上述仅bootstrap适用，Tushare日更/历史失败始终新下载。

### 17.5 覆盖、补数及后批交接

prepare/evaluate/write/summarize按§10.5接口实现，复用build_stk_factor_pro_coverage_keys，三侧原代码只映射一次。全局依据文件身份未变复用，月停牌一次规划；先核原完整schema/物理规则，再筛CNY上市区间、北交所边界、仅全天停牌。未知依据按§17.8.4记录对应kind并返回未知计数；非法代码在准备阶段完成分类，不在evaluate中变成未处理异常；休市有源停止；源4800导入4800为传输成功、覆盖另算，导入4799为传输失败。

完整明细先写、JSON后写，summary从全批准自然日期和当前有效小记录求和，不累加、不因未知给出全范围0缺口。原源/原导入计数与当前补数状态分别核，result/summary写失败不回滚文件；最后重新prepare检查引用失效，至多局部复算，不循环直到稳定。

第四批实现update_after_publication纯内核及结构/SHA/Raw→Silver/audit交叉核验。可信输入固定为CurrentPublication、raw_audit、silver_audit；主流程内部按日期接收不可变tuple，不成为运营配置。DateCoverage仅保存CurrentPublication引用，完整audit由第五批真实DG读取交接，不从JSON id猜passed，不新增audit状态文件或空reader。本地复算已补数日期要求可信发布与已保存引用一致；本轮补数更新接收新发布，允许run/id/SHA变化，不要求等同旧result。缺可信三项时须在Prod读取、旧源恢复、候选提升前拒绝。第四批测试用真实临时文件audit及来源明确的发布输入验证内核，不宣称已验收正式DG事件读取。

### 17.6 逐步验收与成本

按方案八步分别测试后继续。合同/路径/摘要先验收；再测月规划和活动/分区；再测游标；再测两层恢复；再测覆盖/补数；最后串联及独立审计。每项硬口径对账代码、正反测试及证据。测试覆盖§10.4/10.5.5/10.5.6全表，并包括0/4999/5000/5001、跨批同日/同批多日、R−1/R/R+1、未知/合法0停牌、原源0补出、重复补数、统计失败、窗口过期、目标改写、双重清理异常。至少一次真实子进程退出后同operation恢复；已完整日期零重复远程明细，半日整日重读。

资源沿原5000行约9.94MiB净字段、128MiB估算/256MiB余量及单主要DuckDB设置，无新硬限。分别计正常、半日重读、完整源复用、本地统计及最终验收的查询、Parquet/SHA读取、记录/候选/提升数量、临时关系、峰值空间及耗时；月计数/EOF也计入，不能宣称全程序只读一次。汇总一遍小记录，不为统计重扫261列。Prod类型复用既有schema/有界证据，HTTP样本不冒充PG游标实测，不新增真实源请求或5000行压测。

只用临时文件、隔离DuckDB/instance及模拟Prod；受保护测试走既有runner。默认Ruff、本项目致命规则、文档/空白检查及CodeGraph核验通过后独立审计。正式PG、全量bootstrap、分区写入、事件补录均未执行；第四批通过不自动推进第五批。

§17编码补充：export/preflight的staging_root是主入口传入的内部依赖，正式入口不暴露根路径；正常export在同月事务内完成预检，不由入口重复开连接。日历BasisFile.valid只表达文件级可读/schema/身份稳定及不可归属坏行检查；可归属某日的缺失、重复或空开市标志按unknown_by_date仅使对应日未知，不能把无关日期一起置未知。其他三类依据仍执行完整物理规则。全局三类依据的已载入身份允许保存在同连接TEMP小表以复用，随连接释放，不持久化或新增配置。最终停牌非空timing按现行producer保留为盘中，不新增时间格式正则；producer本应转为NULL的空白最终timing列依据异常未知，不推定全天停牌。

§17来源与校验补充：非零日期随游标确认完整后即时处理；源0日期只能真实EOF后确认，因此EOF阶段把待处理末非零日与零日合并升序，不承诺含源0月份的全月回调绝对升序。bootstrap只核四类正式输入文件的消费物理规则；identity producer的seed_latest_code_explainable检查的是仓库种子最新码是否出现在生命周期，不检查本次映射行，本批不引入种子作为第五类统计依据、不修改该正式上游check。

§17清理审计补充：第四批复用的audit_stk_factor_pro_file原finally直接DROP VIEW，若主体字段检查已失败且DROP也失败会掩盖原始错误。本批在同一本数据集纯检查函数保留主体异常并附注清理错误，仅清理失败时仍失败；增加真实临时缺列文件与DROP失败的回归，不变更检查规则或其他数据集。


### 17.7 第四批实际验收与后批条件

2026-10-27当前验收：五项修复完成；40个明确列出的普通测试文件868项、原受保护入口126项（Definitions 1、资产治理12、静态合同113）通过，合计994项不同用例。最后的空间月份索引调整后，空间/日志28项再测通过，与前述重叠不累计；Ruff默认与全src/tests致命规则、CodeGraph sync/status、文档和差异检查通过。新增136项为SHA16、空间纯预算58、空间接线12、片段复用16、覆盖依据18、日志16。逐项代码/反例/成本及未覆盖范围见[当前验收](../../reports/stock_factor_pro_batch4_20261026/README.md)、[修复验证](../../reports/stock_factor_pro_batch4_20261026/fixes-verification.json)。

以下保留2026-10-26原主体测试证据，不作为五项修复的当前结论。

2026-10-26原八步主体开发已提交。以下是五项独立审计修正前的历史测试结果，不证明§17.8修复已完成：最终明确文件清单的整批回归731项通过；新增真实临时DagsterInstance分区注册用例通过（入口文件9项重测通过，其中8项已含整批），独立不同数据集用例共732项。受保护Definitions/资产治理/静态合同仍走原runner，分别1/12/113项通过，合计858项不同用例。没有通过skip/修改预期绕过错误；初次批量命令错误包含受保护Definitions，已按正确入口重测，原执行记录保留。

真实进程在Raw完成、Silver前退出后，新进程同operation恢复：Prod仅5条控制查询、0明细SELECT/0fetch，原完整源和Raw的SHA/mtime不变；第三进程在来源窗口到期、无Prod凭据时，仅本地统计通过。真实临时instance验证只新增已知开市日（含源0），不删除旧键、不注册未知，重复执行键集合不变。纯覆盖计数证明首次日期集合1次、未变重执行0次，result不替换；summary只重写自身，不累加。

独立审计与14项专项反例已核发布Raw绑定、空源身份、诊断相对路径、complete业务摘要/行数和共享audit双异常。月份关系finally释放，全局身份缓存不随批准历史扩大；这些是该次既有修复的证据。随后独立审计发现的§17.8五项问题已于2026-10-27修复并完成针对性回归和独立复核；不能用原858项替代当前验收。完整成本/测试/逐项对账见[第四批验收](../../reports/stock_factor_pro_batch4_20261026/README.md)。报告明确SQL/SHA与真实物理扫描的区别、小样本观测空间与估算边界，不能外推为全源性能已通过。

2026-10-27五项修复、针对性回归及独立对账完成，第四批通过隔离验收；未推进第五批，不将本轮验收视作正式执行授权。第五批须落实真实DG物化/check及完成结果读取、开始授权/BootstrapContext、日更和历史repair装配、首次人工补数及事件持久后调用统计更新。第四批没有空reader占位，也没有提前接正式Definitions；正式Prod范围/窗口/月R/timeout和磁盘、正式写入/分区/事件仍各自批准。本批提交不包含正式执行，不自动推进第五批。

### 17.8 五项审计修正的编码与验收要求

本节五项已获管理员批准，并于2026-10-27按顺序完成实现、回归及独立复核，是§10及§17相应步骤的现行约束。原批准结构、JSON版本/摘要算法、5000行批量、单主要连接及既有资源参数保持不变。不新增CLI、配置、状态表、跨进程缓存、线程或锁；不改公共下载器及其他数据集。修复时先核以下对应的当前代码，再按本节修改并逐项测试。

#### 17.8.1 发布只接受原检查通过的候选

**位置及原因。**`stk_factor_pro_bootstrap_publication.py`的`_publish_layer`在候选完整检查后调用`fragment_from_relation`或`_silver_fragment`；两者会重新取得当前文件SHA。修复前未确认它仍等于原candidate_audit.file_sha256，曾可在隔离反例中给改写候选保存意图，先写入错误文件再读回报错；现已按以下规则在正式替换前拒绝。修复复用`io/stk_factor_pro_publication.py::_publish_file`已有的原检查摘要绑定规则，不复用其Tushare失败恢复入口，也不增加另一份记录。

固定执行规则：

1. 候选构造/既存候选完整读回检查通过后，保存该不可变audit及`validated_candidate_sha = candidate_audit.file_sha256`；必须非空，audit的层、日期、路径和passed均符合当前处理对象。这个值不得被后续计算覆盖。
2. 构造fragment描述后，要求`fragment.file_sha256 == validated_candidate_sha`，字段schema、行数、日期及内容描述也必须与原audit/期望关系对应。描述函数不构成新的发布授权。描述SHA与原检查SHA不一致，或随后保存意图/提升前的实际SHA不一致，即停止；不得重算新SHA后继续。
3. `before_publish()`完成活动/维护等检查后，在写intent前重新核候选SHA。首次replace还须确认目标不存在；reuse须核正式目标仍等于其完整检查的SHA、业务内容与候选等价。replace的expected与candidate SHA均取原候选SHA；reuse的expected/prior取原正式目标SHA，候选仍绑定原候选SHA。保存并读回intent后，不得更改这些值。
4. `atomic_promote`前再次核原intent、候选SHA、目标prior、Silver所绑定Raw及§17.8.2空间。摘要冲突时零正式替换，不把“提升后再检查”当作安全措施。reuse也核原正式目标身份，不能因为不执行replace而跳过；候选未改且内容等价但字节不同的正常reuse必须通过。
5. 已有intent时，其candidate/expected就是此前已检查对象的固定依据；恢复过程不能用变化后的候选重写意图。正式目标已等于expected的分支允许候选已被移走，沿§10.4核正式内容、Silver绑定和原意图后补complete。否则候选必须仍存在且等于原意图SHA。目标不符或候选改变则停止，保留证据。

不增加备份、回滚、文件锁或覆盖不同目标的权限。摘要检查防止本流程已能观察到的文件变化，不承诺消除外部进程在最后检查与replace之间恶意改写的竞争；正式写入仍须原有维护与禁止并发要求。正式读回保留，不能因增加写前核验而删除。

验收在临时Raw、Silver分别注入三处改写：检查后/意图保存前/提升前。断言候选内容10改为99后失败、正式替换次数0、原正式文件不变；正常首次、字节不同而业务等价的reuse、原intent恢复及目标已expected但候选已移走均通过。另测reuse目标在检查后改变时停止，不能只测候选。

#### 17.8.2 空间预算、检查时点及中断处理

**位置及接口。**`stk_factor_pro_history.py`入口负责依据批准日计数和当前已核完成事实准备剩余工作；在本数据集既有bootstrap模块内提供纯内部`estimate_bootstrap_space(...)`及`require_bootstrap_space(...)`，不暴露新运营参数、不改变approval。前者返回按用途区分的字节估算，后者只读路径元信息/`shutil.disk_usage`，按设备核free，不创建测试文件测容量。 临时目录只读当前主要连接的`SELECT current_setting('temp_directory')`，不执行SET、不硬编码另一条路径；API依据[DuckDB配置读取](https://duckdb.org/docs/current/configuration/overview.html)。source、publication及统计写入借用入口绑定的同一空间检查函数；直接调用这些内部写入口的测试也必须提供检查依赖，不能绕过检查。

估算输入固定为：批准记录及已核按日计数、当前operation/attempt、实际剩余日期、已保存且可复用的源引用、当前待写批行数、本日Raw/Silver预计行数、当前步骤及正式/staging/DuckDB临时路径。行数只能来自批准计数、已核片段或当前连接关系的已得计数，不能为估算重读Prod明细或扫描正式全历史。每月`sum(selected_date_counts) <= R`仍独立核验，R不是磁盘字节数。 候选新增量在入口按未满足文件数和总行数维护递增/递减计数，传纯预算函数计算同一公式，不在每次边界重遍历全范围日期；JSON已占字节按日期分组增量维护，只有最终重开统计范围时一次汇总。 入口一次建立月份日期索引，无指定单日的批次检查仅遍历本月最多31日；只在入口和最终统计等少数时点取全范围最大工作量。它们只替代重复的元信息遍历，不改变S/C_new/C_work/T/J算法，不持久化、不增加配置。

初值按以下固定内部算法估算，集中在上述纯函数中维护并用字面小样本核算；这些是保守空间估算，不是新增配置、Parquet大小上限或能够保证外部磁盘永不被占用的承诺：

- Prod净行宽仍为`9 + 4 + 259*8 = 2085 B`，5000行约9.94MiB。落盘Raw日期为8字符，按较大值`W = 9 + 8 + 259*8 = 2089 B`同时估计两层。单个新文件估算`P(n) = 2*W*n + 4 MiB`（n>0）；确认不生成文件时为0。系数2与每文件4MiB用于编码、页和元数据余量，不假定压缩节省；不得把2085 B当成实际Parquet行宽或内存对象大小。
- 新增保留源预算S：对批准范围内全部仍需导出的日期，按其所在月合计n，分为5000行片段，累加每片`P(min(5000, remaining_rows))`。当前attempt以其开始时固定selected_dates的批准计数减该attempt已读回保存的行数计算尚需行数，已核完整日期只在确定selected_dates时排除一次；若按动态剩余日期重新计算，则只能减这些日期对应的已保存行，禁止再减整个attempt行数。例如A/B各5000行，A已排除后n=5000，不能再减A的5000行。尚未开始月份只排除已核完整日期；换attempt重读半日时，旧半日片段不可复用，不从新attempt尚需行数中扣减，旧文件仍占用磁盘，不删除腾空间。尚未执行的后续月份也计入S，避免只给当前批留空间而忽略源文件一直保留。
- 尚需留存的候选/正式数据预算C_new：对全部剩余日期、两层逐项累加尚需新增的`P(rows)`。首次无目标时候选replace只是同设备改名，这份候选/最终文件只算一次；已有可复用候选覆盖其对应最终文件需求时也只算一次，不能既扣候选又扣目标。正式文件或可复用候选已落盘的对应需求只扣一次且不小于0，不按路径存在便扣减；同一条需求已由现有文件满足后不再进入剩余项。reuse分支若仍须新建候选而正式目标已存在，另计新候选且不减旧目标占用。已有不同内容目标/坏候选仍按冲突规则停止，不删除重建。全部剩余日期的最终文件会累积，不能用“最大一日候选”代替其新增总量。
- 临时计算预算T：先独立计算本日工作量`C_work=P(raw_rows)+P(silver_rows)`，月开始尚未选本日时取待处理日期中最大值，不因文件已落盘而扣减；再取`T=4*(P(min(5000,本月尚需新读行数))+C_work)`，覆盖当前批转换、单日关系、两层读回及覆盖差集余量。完整源恢复无新批时首项为0，但仍要核两层读回工作量。只有本地统计时不新增两层数据文件，C_new=0，T按待统计日最大`4*P(raw_rows)`估算。不能将C_new=0误认为无需临时计算空间，不把整月业务行物化，也不把512GB spill上限当可用或必须预留512GB。无法由既有计数确定工作量时停止说明缺少哪项依据，不能当0。
- 小记录/最终统计预算J：按尚待更新的日期数与1份summary，合计`1 MiB * (remaining_date_count + 1)`；仅单日收尾则按1日加summary计算。另为本次实际使用的每个设备保留16MiB余量。J及每文件余量同样是内部估算；实际文件超出估算时必须以实际字节重算后续预算，不静默沿用偏小估算或把超出直接当数据错误。业务JSON保存读回后的record_saved仅观察真实大小并更新预算，不把已写字节再当未来写入；下一读写边界仍检查实际free。

空间检查把S、C_new、J放到staging/正式所在设备，把T放到既有DuckDB临时目录所在设备；根据`st_dev`合并同一设备，仅核一次`free >= 该设备尚需新增量 + 16 MiB`。目标目录未创建时取受控根/最近已存在父目录，不借此创建新正式目录；根/路径/同文件系统安全检查仍先执行。同设备不能各项单独比较free后同时通过，不同设备不能用一处空闲抵另一处不足。已落盘文件本身已从free扣除，不再次当新增量扣除；估算的是从当前时点到剩余工作完成还需的空间。

必须执行的边界依次为：

1. 入口只读核批准/计数/已完成事实后、首次远端明细SELECT前；每月开始按当前实际剩余工作重算。控制/schema/计数查询不等于明细SELECT，不靠拉样本才能算预算。
2. 每批片段保存前、每日Raw候选及Silver候选构造前、每次正式提升前；覆盖明细和result/summary写入前也核小记录/本日临时量。复用源或只做本地统计仍执行对应边界，不能因零Prod请求跳过空间检查。
3. 每批保存/候选生成后以实际文件大小更新估算依据，下一边界重读free；若实际空间增长超过初值，使用二者较大值重算后续量。此修正只读取本次文件stat和已得计数，不重扫业务字段。正式执行前预算及运行摘要须同时说明初始估算与实际观测的差异，不宣称初值是物理硬上界。

不足、无法读容量或无法确定所需设备时，抛出包含operation、阶段、设备、required/free及下一动作的明确错误，停止新fetch和后续写入，按原finally收尾。初始不足必须零明细SELECT；途中不足保留已完成源、正式文件和记录，不回滚、不删除旧源、不改R或偷偷缩范围。外部占用导致实际写入ENOSPC仍按写入失败处理，不重试Prod/Tushare请求。中断后重入先核剩余工作并重新预算，完整日期仍可复用；最终只补统计也须核J/T，不能只预算正常首次运行。

验收使用临时目录和假容量：初始不足/正好满足/有余量，途中容量下降，同设备合并/不同设备不足，旧半日保留加新attempt整日重读，10日正式文件累计保留，A日排除后不重复扣A保存行，完整源/已有候选复用仍有C_work及仅统计模式，实际尺寸高于初估后的重算。独立断言预算字节数及零明细SELECT/正式替换，覆盖正常小幅增加仍能通过，不能只证明拒绝路径。不安装依赖、不做正式磁盘压力测试或全量数据读取。

#### 17.8.3 同一源片段的完整检查只做必要次数

**位置与生命周期。**在`stk_factor_pro_bootstrap_records.py::load_complete_source`及写SourceComplete的共用片段核验路径实现复用。入口持有显式的内部验证上下文，固定绑定当前主要DuckDB连接和operation；由主流程传给source/records/publication，禁止模块全局字典、持久缓存或另开连接。当前月结束及操作finally清空；因异常退出也释放，不随全历史月份累计。已有全局小表依据缓存不因此扩大。

每个缓存项只保存已成功校验的元信息，不保存业务行或整月表。上下文绑定当前连接身份、operation_id、approval_digest和月份；条目以规范受控路径定位，比较完整冻结fragment描述（含schema/行数/日期/字节及内容SHA）和`st_dev/st_ino/st_size/st_mtime_ns/st_ctime_ns`。attempt/fragment编号由受控路径及逐次引用核对保证；比较完整描述，不仅比较字段数或版本，也不另造一份持久摘要。来自当前SourceComplete的路径、归属、批准/来源/查询/记录摘要每次仍解析核验，不能命中缓存便跳过损坏记录。

处理顺序：

1. 拒绝符号链接/越界及缺失文件，获取文件stat；无完全相同缓存项时，执行原文件字节SHA、261列schema/类型、主键、日期范围、行数及整片段业务内容核验。结束再次stat，身份改变或任何检查失败都不登记成功；不得缓存异常或部分通过结果。
2. 首次保存片段若已经从真实落盘Parquet完成同样的完整核验，可以登记；仅用写前内存关系生成期望描述不能登记。保存/读回和以后加载必须走同一个核验方法，避免“写时一次、读时再一次”各自全验。
3. 命中且使用前stat仍相同时，复用整片段检查结果，不再重算该片段SHA/全部业务内容。文件变化使旧项失效，重新按预期完整检查；预期字节不符则停止，不能更新manifest来迎合变化。新连接、新operation、新批准、不同描述或新月份均重新验证。
4. 对每一完整日期仍核其引用片段确含本日、按日期过滤、过滤后行数、本日完整业务内容摘要以及SourceComplete绑定。每日本日关系仍是有界单日，不用缓存保存整月业务数据。正式Raw/Silver候选检查、正式文件读回和意图摘要核验不属于源片段缓存，照常执行。
5. 检查和实际取本日数据前后都核stat稳定；变动时拒绝继续使用旧结论。使用前后的stat核验是同operation维护条件下的文件身份检查，不引入锁或不可靠的“全工程永不改变”承诺。

验收用一个真实临时片段含3日、每日至少1行，串联片段保存、三日SourceComplete及两层发布，断言同连接/operation内整片段全验恰好1次（含可登记的首次落盘读回），三日本日过滤/行数/内容照常核验。分别测只改mtime/替换inode/同大小改内容/描述损坏/跨连接或operation/跨月清理；变化不能复用，损坏不能转为成功。额外记录Parquet查询与SHA次数，不能把“全验1次”说成只有1次物理读文件，也不能省略必要的单日读取。

#### 17.8.4 准备阶段识别坏覆盖依据，合法导入继续

**位置与合同。**在`stk_factor_pro_bootstrap_coverage.py`准备月依据时补齐生命周期、身份及最终停牌的代码格式检查，复用`asset_guards/stk_factor_pro_readiness.py::build_stk_factor_pro_coverage_keys`当前`[0-9]{6}\.(SH|SZ|BJ)`要求及§10.5.2实际生产者schema。在本数据集既有文件内抽出同一谓词复用，不在两个位置各维护不同规则，不改变其他数据集或上游正式check。Raw源本身不因统计而改码、删行或补映射。

归类固定使用原CoverageInputKind四值，不新增可无限增长的错误枚举：

| 实际不合约的位置 | 记录和后续动作 |
| --- | --- |
| 生命周期ts_code | lifecycle.valid=False；其依赖的当月覆盖不能确定，受影响日期记录lifecycle未知。不把合法的生命周期行单独留下后宣称全市场齐备。 |
| 身份source_ts_code或latest_ts_code | identity.valid=False；当月依赖该文件的日期记录identity未知。若因生命周期已无效而不能检查引用，只记录原lifecycle未知，不把“未执行引用检查”伪装成另一个身份错误；若身份自身代码也错则两类均如实记录。 |
| 最终停牌ts_code | 对应日期suspend.valid=False，只使该日覆盖未知；不得把坏停牌行丢掉当作没有停牌。其他合法日期继续正常统计。 |
| 可归属单日的日历问题 | 继续原unknown_by_date仅标受影响日，文件级问题沿原规则，不将无关日期一起改成未知。 |

已分类问题写入原BasisFile/unknown_by_date及现有result；中文原因包括依据种类、非法数量及至多20个代码样本，不增加状态文件或逐坏行日志。unknown_by_date已有原因字符串只用于解释，分支仍看固定kind/valid。空值/schema/区间/重复等原规则同样适用，不只修这一次代码格式。

生命周期无效时，身份自身检查仍执行；自身通过可标identity自身文件规则有效，但不代表已完成生命周期引用核验，整体覆盖仍因lifecycle未知而不能放行。生命周期恢复有效后，原依赖缓存身份改变，必须重新核引用。只有依据全部有效才调用已知覆盖计算；无效时直接走§10.5.3未知结果，源/Raw/Silver物理计数继续记录，expected/身份actual/matched/missing/extra及coverage_complete为None。完整日合法源及两层仍处理，后续日期继续，不伪造绿check或0缺口。准备期间文件缺失、不可读、坏schema/坏字段等可识别输入问题按已有输入分类返回未知；连接执行错误、程序类型错误、意外SQL错误、源/候选/正式文件读写错误、计数不符等仍传播并停止，不用`except Exception/ValueError: unknown`掩盖。

已确认休市而源有行仍是原停止条件；源本身非法代码属于源合同错误，不能混成覆盖输入未知放行。统计写失败仍失败并保留已发布数据，不把文件系统故障改成“依据未知”。

验收以真实schema的两日合法源和`INVALID`生命周期/身份代码分别测试：两日Raw/Silver都忠实发布，原源计数不变，相应日期unknown且kind准确，未宣称缺口0。另测坏停牌代码仅影响本日、正常A/B/C差集继续正确、生命周期错误但身份本身合法不误报身份自身代码坏；不属于覆盖输入缺失/不可读分类的意外SQL错误，以及源/候选/正式/统计文件I/O错误及休市有源仍停止。夹具错误只在反例中故意引入，不能复制当前消费者的遗漏来生成expected。

#### 17.8.5 运行摘要与失败说明

**位置与方式。**bootstrap入口、source及完整日处理沿现有模块的`logging.getLogger(__name__)`方式输出；使用一个本数据集内部摘要方法统一字段和计数，不新增日志文件入口、运营回调配置、状态表、监控线程或固定间隔心跳。它与on_complete_date业务处理回调不同，日志不能授权发布或代替持久完成记录。

固定事件及触发点：

| 事件 | 输出时点与事实 |
| --- | --- |
| month_started | 批准/空间检查通过、本月处理开始前；需要远端明细时必须在SELECT前；说明selected日期数、批准行数、R、5000行批量及恢复模式。 |
| batch_saved | 完整片段保存、必要读回及源检查通过后；说明本批和本attempt已保存源行数、批次号、当前日期，不能在仅fetch成功时增加saved_rows。 |
| date_completed | 该日两层发布/读回及覆盖result写入均完成后；说明Raw/Silver行数、该日源行数、覆盖complete/incomplete/unknown、已完成日期数。不把Raw已完成但Silver失败记成日期成功。源0且无两层文件时明确说明合法无文件结果，不伪造发布数量。 |
| operation_finished / operation_failed | 最后summary保存读回且资源关闭结果已知后报完成；任一业务/容量/关闭异常报失败，包含出错阶段、已持久完成量及下一动作。失败日志不把未保存的内存行计为完成。 |

字段固定包含operation_id、attempt_id（尚未创建则None）、month（操作级可None）、stage、event、batch_no、batch_rows、saved_rows、completed_dates、total_dates、trade_date、raw_rows、silver_rows、coverage_state、reused_source_rows、elapsed_seconds、updated_at及outcome。无该事实用None，不填0冒充结果；stage使用现有阶段的清晰中文说明。耗时由同进程monotonic计算，updated_at为带Asia/Shanghai时区的当前时间；不承诺ETA或请求阻塞期间定时更新。失败原因及next_action用中文，不打印token、密码、DSN、整行业务数据或完整缺失列表。

saved_rows指本attempt真正保存并读回的源行数；operation内复用的旧完整日另以reused_source_rows说明，不混成新导出行数。completed_dates按同operation已核日期处理完成的唯一集合计算：有数据日期要求两层完成及覆盖记录；合法源0且无文件的日期要求完整空源事实及覆盖/日历分类结果，不能要求不存在的两层complete。恢复时先使用已读且与当前文件一致的日期结果恢复基数；已确认休市且具有合法完整空源、无业务文件的日期，月准备后恢复其分类基数。本轮成功日期只新增一次，不因重复执行累加。完整日两层及统计记录保存并核实后，先更新完成量并通知，再执行容量后检；后检失败不能把已完成事实显示成0。total_dates为批准范围内纳入当前operation日期处理的日期数，包含合法源0日；确认休市无源可完成日历分类，不能伪装成资产物化。已保存源行数或日期进度100%不表示市场覆盖齐备，coverage_state必须分别展示。

日志普通Exception仅影响观察：用有限的标准错误提示说明日志失败，不递归调用同一坏handler；不停止合法业务、不重发网络/Prod请求、不重复保存或发布、不回滚文件。KeyboardInterrupt/SystemExit、取消异常和主体业务异常继续传播；不能因捕获日志错误把主体错误吞掉，失败收尾保留原始原因。此规则只针对日志输出，业务on_complete_date、记录写入或校验失败仍按原停止规则执行。

测试用日志捕获和会抛普通异常的handler，验证月→批→完整日→最终顺序、同attempt保存量和operation完成日单调且不重复；跨月/新attempt的saved_rows允许从0重新开始，operation源总量只从唯一已核持久引用求和，不累加日志；验证Raw后失败不出现date_completed、原业务错误不被日志错误替换。取消继续传播，零新增源请求/重复replace；只用一月两日小样本，不新增真实源请求或长跑压测。

内部调用关系固定为：正式bootstrap入口自动绑定check_space和进度对象，每月创建verification；业务不配置这些参数。source/export、完整日处理、publication及coverage写入口必须收到同一check_space；直接内部测试显式使用临时容量依赖，缺参在写入前拒绝。verification是可选的内部性能依赖，不传时仍执行同一完整核验，不能因为没有缓存而跳过检查。进度对象由正式入口持有，source只在同线程调用；借用连接的内部入口不伪造最终关闭成功。

| 内部对象/函数 | 输入与输出约定 |
| --- | --- |
| BootstrapSpaceEstimate | 冻结的source_bytes/candidate_bytes/temp_bytes/record_bytes四个非负整数字节值，不持久化。 |
| estimate_bootstrap_space | 接收已核各月尚需源行数、逐文件行数或互斥的remaining_layer_totals=(总行数,非空文件数)、本日两层工作行数、当前批行数、尚需日期数及实际观测余量，返回上述预算。参数只来自本次计划/已核事实，不能成为运营配置。 |
| check_space | 入口内部闭包，接收中文stage、受控path及已核日期/层/行数和有限事件；source_saved按本attempt减源，candidate_verified只减C_new，publication_verified才解除对应未完成层，date_completed减剩余日期，final_statistics重开全范围统计且清月份限制，record_saved只观察实际大小。返回预算仅用于观测，不作为发布授权。 |
| BootstrapFragmentVerification | 连接/staging/approval/month固定；verify对记录及引用核验，返回(path,文件身份)；remember_saved仅接受writer真实落盘读回后的登记；close清空并拒绝后用。 |
| 运行摘要 | 标准INFO logging；固定字段见§17.8.5，另含月批准行数/R/批量/selected_date_count。调用环境沿用现有日志配置接收INFO，不由组件安装handler或修改全局日志设置。 |

#### 17.8.6 修复顺序及对账完成条件

先完成发布SHA绑定和空间检查，再完成片段复用及覆盖分类，最后补运行摘要；每步先定向正反例再进入下一步。五项分别对账当前实现位置、正常/失败测试与成本；旧858项仅作既有回归基线，不能用测试总数代替本节反例。最终分别报告单元、隔离串联、既有真实有界证据及未执行的正式操作。五项修复与独立审计现已完成，已同步§17.7、原方案和验收报告状态。第四批通过隔离验收，不自动授权第五批或正式执行。
