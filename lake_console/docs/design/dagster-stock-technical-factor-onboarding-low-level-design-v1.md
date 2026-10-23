# 股票技术因子 DG 数据集接入 LLD v1

日期：2026-10-23。状态：设计草案，尚未开发。自动日更先发布日Raw→Silver，再检查原目标日Raw是否齐备；只有齐备后才处理历史。手动repair先检查原目标日Raw齐备，再核T/P复权因子及原历史范围；不执行日更新，也不要求原目标日Silver齐备。Raw缺失、不齐或无法确认时直接报“原日期数据缺失”。Tushare日更或历史任务失败、取消、异常退出后，获准重执行均重新下载所需原完整范围，不复用失败任务的源或候选；已发布正式数据、完整名单、授权范围和失败证据保留。参数、编码和验收要求分别见§10～12；本文不构成开发放行或正式执行授权。

依据：[原技术方案](dagster-stock-technical-factor-onboarding-plan-v1.md)、[DG接入模板](../templates/dagster-dataset-onboarding-template.html)、[性能治理规范](dagster-data-pipeline-performance-governance.md)、[Prod审计报告](../../reports/stock_factor_pro_prod_audit_20261021/README.md)。下载器依据[组件LLD](dagster-tushare-download-component-low-level-design-v1.html)与[业务使用文档](../architecture/tushare-download-component-usage-v1.html)，不在本数据集重做。

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
6. 每轮取得的完整有效数据先发布日Raw、Silver，业务即可读；然后仅在原T已发布合并Raw覆盖齐备、日阶段通过时，在同一个自动job处理必要历史。历史失败保留日数据，管理员可通过§4.1额外的手动repair job只恢复原T历史，不重跑日阶段；无自动repair sensor。日数据发布没有覆盖率、最低股票数、全历史完成或跨文件快照门槛；历史另有原T Raw齐备硬条件。
7. 只从应有集合排除全天停牌，盘中停牌仍应有。Raw不据应有集合过滤来源合法行。Silver本期完整保留字段及对应行，归一化日期；后续新增清洗不作为本期前置，不自行过滤/填值。
8. 只自动管理今天和Q；更早分区保留，更早缺口报告管理员；不自动补更早日期，也不把它作为今天能否执行的条件。

失败后无论下载/候选/发布哪一步退出，下次均重新下载；丢弃候选不等于删除正式数据、名单或失败证据。完整unit仍指本次接口查询全部页已取全，不代表源端所有应有股票已发布。合法少股票可处理，网络只完成一部分页不可交付半unit。管理员手动repair为额外人工入口，不增加自动调度链。当前正式CONTRACTS/BINDINGS仍为空、名称后缀校验仍待改；本文资产、定义及记录均为拟新增，组件已有隔离验收不代表本数据集已实现。

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

采用一个`@dg.multi_asset`定义两个资产，在一个同步生成器内明确执行日Raw→Raw检查→日Silver→Silver检查→原T Raw齐备判断→历史。两个`AssetSpec`可声明`skippable=True`以表达首次合法0行时不伪造物化，`can_subset=False`保证正常入口总是按完整链路运行；不是允许业务任意挑选字段或只更新一层。

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
| `defs/io/stk_factor_pro_history.py` | 技术因子下载前的完整名单；原T Raw齐备后完整历史范围；历史前输入再核对、窗口和完整发布依据。 |
| `defs/io/stk_factor_pro_download.py` | 完整unit消费、源候选/读回、组件通知适配；不重试业务写入，不把实际开始记录藏在进度回调。 |
| `defs/io/stk_factor_pro_candidates.py`、`stk_factor_pro_publication.py` | 按日期批量合并、必要校验、同文件系统提升与逐文件记录；T日唯一来自日阶段，历史只合并d<T。 |
| `defs/checks/stk_factor_pro.py` | 两项检查的规格及纯校验，multi_asset内调用；不另定义同名check形成重复注册。 |
| `defs/assets/stk_factor_pro.py`、`jobs/stk_factor_pro.py` | multi_asset及唯一自动日更job；不创建线程、子进程、异步历史任务或新平台。 |
| `defs/ops/stk_factor_pro_history_repair.py`、`defs/jobs/stk_factor_pro_history_repair.py` | `repair_stk_factor_pro_history` op的4项必填配置/预检/历史新下载与手动repair job装配；不注册自动sensor，不调用日下载/发布函数。 |
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
| `require_stk_factor_pro_history_raw(...)` | 仅§5.2原T Raw覆盖结果 | 不为True就抛约定Failure；自动调用方先分支等待，repair直接调用。完整名单/范围由各自后续流程另核。 |
| `download_stk_factor_pro_history(...)` | 原T Raw齐备、完整原失败范围、再次核对的权威T/P | 当前run全部unit全新下载/保存/读回；失败新run不复用旧source-complete。 |
| `publish_stk_factor_pro_history(...)` | 完整历史源、名单/基准、现有d<T文件 | 仅更新d<T；历史响应的T仍完整留在源候选并用于核对，不覆盖日阶段T。 |
| `summarize_stk_factor_pro_result(...)` | 文件读回、两层checks、覆盖、完整名单/历史结果、错误 | 分别说明可读数据、缺股票、待回刷、两接口差异和本轮终态；不增加覆盖状态资产。 |
| `repair_stk_factor_pro_history(...)` | 手动配置指向的原T、原完整名单/范围和原批次 | 不重新计算扩大授权范围；核原T Raw齐备后重新下载完整原失败范围，复用同套业务函数，只d<T，无BY_POINT或T提升。 |

### 2.4 自动入口的封闭配置与重新执行来源

`defs/assets/stk_factor_pro.py`固定使用`@dg.multi_asset(name="stk_factor_pro", specs=..., check_specs=..., can_subset=False, config_schema=STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA)`。配置位于`ops.stk_factor_pro.config`，不能把资产key当作op配置名。`STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA`和解析后的`StkFactorProRunInput`均在`defs/run_contracts/stk_factor_pro.py`维护；asset通过`context.op_execution_context.op_config`读取。未知配置键拒绝，不增加fields、分页、token、地址、路径或处理版本的运行覆盖项。

| 配置字段 | 配置类型、必填及解析后类型 | 精确校验 |
| --- | --- | --- |
| `execution_day` | 必填str→`datetime.date` | 严格`YYYY-MM-DD`、SSE开市日；是计划执行日D，不是T。 |
| `target_trade_date` | 必填str→`datetime.date` | 严格日格式、已注册开市日；必须等于`context.partition_key`。 |
| `purpose` | 必填str | 仅`today`或`previous_day`。today要求T=D；previous_day要求T=日历中D的前交易日Q。不接受manual_repair。 |
| `scheduled_slot` | 必填int→int | `type(value) is int`且0～9；计划时点由D日19:00加slot×30分钟派生，不接受bool、独立时间文本或任意时点。 |
| `submission_no` | 可空int，默认None | today必须None；previous_day必须1～10，业务attempt由用途派生为1，不让运营另传attempt。 |

正常日更请求示例：`build_run_request(run_key=build_asset_update_run_key(subject="raw_tushare_stk_factor_pro", unit_id="2026-10-23:2026-10-23:0"), partition_key="2026-10-23", run_config={"ops":{"stk_factor_pro":{"config":{"execution_day":"2026-10-23","target_trade_date":"2026-10-23","purpose":"today","scheduled_slot":0,"submission_no":None}}}})`。前日示例在同一配置层填D=`2026-10-23`、T=`2026-10-22`、purpose=`previous_day`、slot=0、submission_no=1，并用§3.3的前日key。日期必须由实际日历验证，示例不授权执行。多字段身份关系不一致时，在任何源请求、文件提升及“开始下载”事实前拒绝。

内部函数签名固定为：

```python
def parse_stk_factor_pro_run_input(config: Mapping[str, object],
                              partition_key: str,
                              calendar: tuple[date, ...]) -> StkFactorProRunInput: ...
def resolve_stk_factor_pro_source_run(instance, current_run,
                                 run_input: StkFactorProRunInput) -> StkFactorProSourceRun | None: ...
```

`calendar`是已校验、严格升序去重的SSE开市日期tuple，覆盖D/T及所需前交易日。`StkFactorProRunInput`为frozen dataclass，五字段依上表。`StkFactorProSourceRun`仅保存已验证原run_id、原D/T/用途/slot、完整plan/ranges引用和失败阶段，**不含可用于本次发布的旧源或旧候选引用**；source指原任务业务意图，不指可复用网络数据。

“重新执行”指管理员对失败run明确重新执行后产生新run，不是原进程暂停后自行继续。本期采用统一规则：原任务失败、取消或异常退出，无论是否已下载完整、是否已建候选或已发布部分文件，下一次执行都重新下载，不使用失败run的源或候选。

1. 没有parent的正常新轮总是新下载T。存在`context.run.parent_run_id`时，通过`instance.get_run_by_id()`核对直接parent及必要root，同update job、相同五字段和T分区；只读取原完整名单/范围、原意图及失败结果。不能扫描目录或把旧source-complete当新源。
2. 新run先核原意图和当前T/P，保存本run完整名单，再重新请求原T完整日unit；若历史前置满足，重新请求原失败历史范围的全部unit。旧run中的下载Parquet、最终候选及部分checkpoint不参与本次下载去重。
3. 本run source-complete只证明当前run刚取得的阶段数据已保存完整，供当前运行从下载进入处理，不是跨失败run的恢复授权。新事实只写当前run目录；旧记录保留排障，已发布正式文件保留供新合并，不删除、不回滚。
4. 前日一次规则只限制sensor自动提交。管理员处理问题后明确重新执行、parent/root及五字段身份核验通过时，允许重新下载原Q，不因该自动机会已用而拒绝；仍受原D截止、分区和唯一写入要求。人工重执行不恢复Q自动机会、不增加外层自动重试。更早日期历史使用手动repair；过期日更新不借此增加未经批准入口。

`select_stk_factor_pro_request`只返回`StkFactorProRunInput | None`及一个既有cursor摘要；`build_run_request()`只透传配置，五字段的构造、解析和关系校验不能省略。测试必须有周一补周五的独立日历样本、错D/T、错分区、bool冒充slot、today错误携带提交序号、复制配置无parent、parent/root错身份，以及失败旧日/历史源均不可用于新run、阶段完整也必须重下的反例。

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
5. 今天的候选同样先核T/P因子；尚缺股票、覆盖未知或本目标T明确历史待处理，可按§6.1失败矩阵进入后续时点；历史永久失败不能仅因pending而继续请求。代码已齐、必要处理/历史已完成且股票复权因子数据集输入未修订时停止下载，但sensor继续轻量时点评估输入身份；输入修订则重新提交本job，不无条件持续取源。不能用股票已齐抹掉历史未完成。
6. 构造一个T的RunRequest，写计划日期/时点、用途为补Q或更新今天、前日业务attempt固定为1；sensor不取技术因子、不保存变化清单。

更早日期缺口只保留诊断，不自动补采或阻断当前日期。例：周一补周五仍缺，周一不做当天；周二只自动核周一，周五已变成更早旧洞，报告管理员而不是继续自动补周五。不能偷偷把它改成“任何历史旧洞永远挡住新日”。

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

最小隔离测试：19:30活动占用→SKIPPED持久→清cursor→19:45原run已结束仍不发；首次19:00允许；同slot上游后来就绪允许；坏记录只关闭当前slot、下一slot可正常选；同名不同location不混；读取失败和保留期不足不重复提交。至少用临时instance真实保存/读取tick一次，不能只mock返回列表；本轮不执行该测试或改正式保留配置。

## 4. job内的严格顺序与Dagster编码组织

```text
sensor：日历/时点/前日一次规则 → 股票复权因子Raw T/P就绪 → 提交单T job
  ↓
job开头：截止与唯一写入 → 再核T/P就绪
  → 读取T/P并比较 → 完整保存T回刷名单/待处理原因
  → 持久化本轮开始下载事实
  ↓
下载T日全部页 → 保存完整日unit → 正常关闭session并核最终summary → 必要字段/主键/日期检查
  → 与T已发布文件按主键更新/补入
  → 发布日Raw并读回/check → 发布日Silver并读回/check
  → 已发布日数据可供业务读取（不等覆盖和全部历史完成）
  ↓
先核原T已发布合并Raw的应有代码集合齐备，否则历史等待
  → adj_factor数据集T/P为回刷依据；技术行因子差异只诊断
  → 仅整范围成功且仍有效的同基准历史不重复
  → 完整变化/原失败名单不按本轮返回集合缩小
  → 历史前再次核对股票复权因子数据集输入
  → 重新下载本轮完整待处理范围的全部股票/窗口并完整保存
  → 按日期批量合并/校验/发布d<T的Raw和Silver
  ↓
分别报告日数据可读、代码覆盖、完整名单与历史完成/待处理
```

股票复权因子数据集T/P未就绪就停在job预检，不进入日下载。两接口因子值不同按§12.1已确认规则只诊断，不阻断该股日Raw/Silver或历史，也不改源值。这不证明返回的指标结果已按新基准修正，只证明按规定adj_factor输入完成了本次下载/发布。

编码组织采用两个`AssetSpec`和两个`AssetCheckSpec`的multi_asset，job的selection包含该定义的两个资产及两项check；选择同一个`cn_a_stock_factor_pro_trade_days`。同步函数依次调用§2.3业务函数；没有下载线程/进程或IPC职责下沉组件。

日阶段每资产最多产生一次输出：Raw已通过候选验收并完成提升/读回后，`yield MaterializeResult(asset_key=Raw, ...)`，再yield Raw检查结果；失败显式退出后续。然后同样处理Silver及其check。合法0新增但存在旧文件时只核真实结果；首次空结果不造空文件或虚假可用物化，使用skippable处理并记录原因。源少股票但有有效行不走“检查失败”。

预检明确未下载、或首次合法空且没有正式文件时，只yield相应观察/阶段说明，不输出该未物化资产的check评估。本定义沿用本机Dagster默认输出校验，不调用`set_requires_typed_event_stream`；检查输出虽为required Nothing，默认执行器允许隐式Nothing结束，不能为满足输出数而伪造绿色检查。对应临时instance回归必须断言run正常结束、观察持久且无虚假物化/check，不能只检查装饰器属性。

日更和手动repair均沿用原对象历史窗口，结束日期可以是原T；这不是全市场BY_POINT日更。完整保留该对象请求的T行用于来源和差异诊断，正式历史只改d<T，因此不重复yield日阶段同一个资产输出。历史日期采用显式`AssetMaterialization(asset_key, partition=d, metadata=...)`；对应check使用本机已有的`AssetCheckEvaluation(partition=d, blocking=True, ...)`并关联该次物化。当前`AssetCheckResult`没有partition参数，禁止自造。事件要按正常run写入，不把日常更新变成runless补记。

历史事件固定通过生成器yield：文件读回后yield本批各日期/层的`AssetMaterialization`，生成器恢复后按当前run有界批量读取这些已保存的物化，再构造并yield各自`AssetCheckEvaluation`。只按本批已发布的资产/日期/文件身份匹配真实记录，缺记录或身份不符停止，不猜storage_id；`target_materialization_data`绑定该真实物化。不得先`context.log_event`后立即读取尚在缓冲的记录，也不能每日期深扫全部event history。相应API依据与当前实现见§9，仍须在临时instance验证顺序、持久化及分区关联。

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

### 4.1 管理员手动历史repair入口

`raw_tushare_stk_factor_pro_repair_job`仍为手动op job，无自动sensor。`repair_stk_factor_pro_history`使用`out={}`和既有`lake_root`、`duckdb`资源；配置层级固定为`ops.repair_stk_factor_pro_history.config`。本入口只处理原目标日T完整名单、原起止范围内的d<T历史；不发全市场T日请求，不进行对象T日确认查询，不发布T，不嵌套调用任何日更新函数。

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

本配置持久化于当前Dagster run_config，不新增env、表或页面开关。实际执行日只用于metadata和维护记录，不能替换T/P。配置源run是前一次repair时，读取它保存的原完整授权引用，仍直接核对原T和完整原范围，不把前一次repair实际处理范围当成新授权。所有新记录只写当前run的受控staging目录；旧run只读，不递归扫staging、不猜“最新成功任务”。

严格顺序如下：

1. 校验配置、source_run身份、同T、两项完整授权摘要和受控路径；验证维护窗口、无其他活动写入及bootstrap未运行。任意错误在网络和正式提升前停止。
2. 核对日历T/P和原完整范围，不下载历史；先进入下面原T Raw检查。这样原T Raw缺失时优先给出约定的日数据缺失提示，不先被其他来源错误掩盖。
3. 调用§5.2统一Raw齐备检查，读取**原T当前正式、合并后的Raw文件**；不能从旧下载候选、今天Raw、旧绿色check或一份有相同行数的文件判断原T齐备。
4. 若原T文件缺失、必要字段/check不通过、应有代码缺失，或生命周期/停牌输入不足以确认覆盖，立即抛`dg.Failure(..., allow_retries=False)`。主提示固定为`原日期数据缺失：<T>；请管理员处理原日期数据后重试历史repair。`，metadata补充具体原因。此分支零技术因子请求、零历史提升、零T写入；管理员另外处理原日期数据。本repair绝不代办，不让外层重试策略把这个报错变成重复执行。
5. Raw齐备后，读取当前`adj_factor`原T/P就绪及实际因子，核关键因子/可信范围；不足明确停止，不伪造0变化。只允许原范围内因子值修订，保存当前依据和差异；T/P重新相等不能删除原未完成历史意图，不追加股票、延长范围或更换T。完整保留原授权名单及原范围。按§5.4核对**此前独立整范围成功且仍有效**的事实，确定本次原失败范围；失败run部分或全部物理完成均不能用于缩小它。若已无待处理历史，保存真实`no_action`结果后结束，零技术请求、零正式提升，不伪造本run新完成历史。存在待处理历史则完整保存当前请求范围；不能因失败run只下载了部分股票而缩减该失败范围。全天停牌股票可无T技术行，不额外请求T。缺关键因子或可信范围时明确停止，不能挑一部分先回刷再宣称完整。
6. **每次重新执行，都从头下载该原失败范围的全部历史unit。**不读取失败run的`source/history`文件作为本次源，不复用其source-complete，不因失败run曾发布部分日期而跳过对应历史请求；只有当前run刚下载、保存、读回完整的历史源可用于当前run后续处理。组件单页有限重试仍适用，不增加op/job外层自动重试。
7. 当前历史全部源完整后，按原20交易日批次和日期升序，逐日期Raw合并/校验/提升/读回→从这份Raw生成Silver并校验/提升/读回。仅d<T。已经发布的文件不删除、不回滚；本次新下载结果与当前正式文件按既定主键规则合并，不使用旧失败run候选覆盖。当前run文件提升前后仍写既有intent/checkpoint；这是本次文件发布依据，不是跨失败run省下载的理由。
8. 仅在全部当前请求范围通过检查和物理读回后记录历史完成。失败/取消/异常退出保留正式已发布文件和原完整未完成意图；下一次repair仍全新下载原失败范围，不从页、股票或日期下载断点继续。成功/失败均在metadata说明原T、来源授权、当前新下载行数和实际发布范围。

原T Raw齐备是自动job和手动repair共同的硬条件；手动入口没有豁免。手动repair不消耗或重置自动补Q一次机会，历史完成只解除原T历史失败，不能解除日阶段失败。正式历史只d<T；T行即使出现在完整历史响应中也只留源证据，不发布T。

### 4.2 自动、手动与bootstrap的写入互斥

更新sensor的活动任务判断必须同时覆盖`raw_tushare_stk_factor_pro_update_job`及`raw_tushare_stk_factor_pro_repair_job`，不能repair运行时照常发日更新。repair入口也要检查本数据集其他活动写入并排除自身；只看自动job不足以防两个人工repair冲突。

正式手动repair在明确维护窗口下进行：先暂停本数据集自动发起、确认没有排队/运行中的日更或另一repair、确认bootstrap未执行，再启动获准repair；处理期间不同时启动其他写入，完成后按运营安排恢复自动化。本轮不执行暂停/恢复、不新增全机锁或下载器协调；现行Dagster运行约束和维护流程是否真实覆盖手动/队列竞争，编码前须核对当前配置/调用链及设计，实现在隔离环境后验证，不能声称一次sensor查询足以解决并发竞态。发现冲突就停止/等待，不写文件。

bootstrap也必须处于互斥维护窗口；它可能不是Dagster run，不能只查两job就断言bootstrap未写。所有写入继续使用候选、目标指纹、完整校验及逐文件提升，意外外部变化停下；这些要求不增加快照或多文件事务承诺。

## 5. 完整回刷名单与本轮候选记录

### 5.1 先名单，后技术因子下载

每次同T的自动job开头都用本次`adj_factor`数据集的T/P重新核对输入；手动repair严格按§4.1先查原T Raw齐备，之后才核T/P。输入和契约/范围一致时复用**完整名单**；输入修订则写新修订并合入原未完成范围，保留旧待处理的出处和解释。两入口保留未完意图的规则一致：即使修订后T/P相等也不删除旧未完历史，仅生命周期证明该股本无待刷历史时记录依据和排除原因。不能因本轮源少了一只、源超时、股票暂时无T行就把它从变化名单删除。

比较以T/P的`FULL OUTER JOIN`按代码显式对应，再并入本数据集可信既有历史/同一目标T旧pending中明确应核对的有界代码范围；不能只以T为左边，也不能inner join后漏掉P有T无旧股。至少区分两日都有且变化/不变、T有P无、P有T无、以及既有范围/旧pending证明应核对但两日都缺。后两类没有生命周期或其他明确解释时保留无法判断，不写“0变化”；证明退市也要留下解释，不能静默删除待处理。生命周期可证明的真新股不造上市前历史，单列新股结论；旧股票缺P保留原因。这是本数据集有界对象比较，不新增全市场覆盖发布门槛。没有变化必须能证明输入已检查；股票复权因子Raw文件就绪不意味着每只股票都必有两日值。

只比较股票复权因子数据集值，不新增任意浮点阈值。需要更新历史的变化股从可信既有最早日期到T；无既有历史时解释新上市或异常。最早日期取初始化验收/可信范围或有界聚合，不在sensor逐tick扫描全湖。修订后的因子恢复旧值不取消原未完回刷；下载和发布仍应完成原范围，不能把“写了新清单”当成旧任务自动完成。

### 5.2 原目标日Raw齐备后才允许历史处理

完整变化名单在任何技术因子下载前依据`adj_factor`原T/P生成并保存；日Raw/Silver可少股票发布。只有**当前正式Raw T包含全部应有股票、且必要文件校验/check通过**，才允许该T开始任何历史下载或历史发布。缺股票或覆盖无法确认都不回刷。Raw齐备不是分页完成、总行数达到某值，也不是要求每个上市股票都必有T行。

应有代码按现有语义构成：

1. 使用已就绪且实际schema有效的`silver_stock_lifecycle`，取人民币A股中`list_date <= T AND (delist_date IS NULL OR T < delist_date)`的代码。新股只从真实上市日起计算，不用当前list_status代替历史有效期。
2. 先调用现行`defs/sensors/readiness.py::suspend_d_ready_for_trade_date(instance, T.isoformat())`核对T停牌数据必要事件/check，再核正式`silver_stock_suspend_daily_path(lake_root, T.isoformat())`的日期、`ts_code/trade_date/suspend_type/suspend_timing`及实际文件身份。只有`suspend_type='S' AND suspend_timing IS NULL`可从上市集合扣除；非NULL盘中停牌仍在应有集合。
3. 从正式Raw T严格筛选`trade_date=源格式YYYYMMDD(T)`、取非空唯一`ts_code`，按代码集合执行`expected EXCEPT actual`。缺失数=0才可说明应有股票已覆盖；额外合法源行保留，不能因为含全天停牌源行就删除或判成缺失。
4. 生命周期不就绪、日期范围不能覆盖T、停牌依据未知、Raw结构/主键/日期/check无法确认时，结果为未知或不通过；不把缺停牌文件解释成无停牌，不用Raw自身代码反推应有集合。

不新增第三项blocking check，不让覆盖不足阻止日有效数据发布。自动job在日Raw/Silver都已发布并通过各自必要检查后执行本节检查；不通过时记录历史等待并正常结束已有日发布。手动repair在任何历史网络前执行本节检查，不通过则按§4.1明确报错。Raw齐备后再核权威T/P和完整原范围，全部原待修复范围才可进入历史请求。确认全天停牌股无T行不影响齐备及其d<T历史回刷，技术因子接口的同名adj_factor不同仍只诊断。

#### 5.2.1 内部接口与结果

以下为本数据集内部接口，放在既定`defs/asset_guards/stk_factor_pro_readiness.py`，记录类型在既定`defs/run_contracts/stk_factor_pro.py`，不新增平台、表、锁或独立状态资产。

```python
@dataclass(frozen=True)
class StkFactorProRawCoverage:
    target_trade_date: date
    complete: bool | None
    raw_check_passed: bool
    raw_file_sha256: str | None
    lifecycle_file_sha256: str | None
    suspend_file_sha256: str | None
    expected_count: int | None
    actual_count: int | None
    missing_count: int | None
    missing_sample_codes: tuple[str, ...]
    reason: str

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
```

`complete=True`仅允许全部必要输入已确认、Raw本文件check已通过、且missing_count=0；`False`表示已确定Raw缺文件/行/必要结构不满足，`None`表示现有证据不足或读回无法确认。未知计数为None，不能伪造0；sample按code升序至多20项，完整缺失清单复用已有本run诊断记录。`reason`仅用中文解释已存在的失败类别和位置，不成为新的可解析错误码；分支只读`complete`、check和已验证记录身份。

日阶段调用时通过`verified_raw_audit`传入已对当前Raw读回得到的结果，核其passed、trade_date=T、layer=raw、path为正式T路径、file_sha256等于当前文件实际sha，才复用261字段全对账结果；身份不符就对当前文件重新校验，不能沿旧check放行。repair不传该参数，使用既有Raw综合check的纯校验函数核当前正式Raw，再核已有必要检查事实与文件身份；缺任何部分不能按旧绿色放行。覆盖只读T一份技术Raw、一份生命周期及一份停牌Silver；不查全历史，不读技术Silver判股票是否存在，不重新下载来源。

`require_stk_factor_pro_history_raw`仅在coverage.complete is True且raw_check_passed为True时返回；其他结果一律按§5.2.2抛固定Failure。自动调用方先判断coverage：不足或未知时写历史waiting并结束，不调用require；仅True时调用require后继续核完整名单/范围。repair调用方直接调用require，不能把失败转成等待或执行日更新。

本结果保存到原本已有的本轮历史判断记录，文件固定为`history-eligibility.json`，结构为record_version=1、当前RunIdentity、当前完整plan/ranges摘要、raw_coverage对象（逐字段对应上述结果）、evaluated_at。记录只保存整日覆盖结果；两接口因子差异另留诊断。该记录不作为下一失败任务复用旧下载数据的依据。

开始历史下载前、完整历史源结束后首次历史提升前、历史最终完成前，各核对原T Raw/生命周期/停牌引用仍是本次已确认文件；未变可复用本run覆盖结果，不逐页/逐历史文件重扫全市场。改变时只对T重新计算覆盖；结果不为True则停止后续历史步骤，已正式提升历史不回滚。唯一写入维护规则不因此放宽。

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

### 5.3 文件与结构

本run候选/业务记录位于`/Volumes/datasource/data_lake_staging/stk_factor_pro/trade_date=<T>/run_id=<当前run>/`，路径只由paths.py生成。失败后不删除旧证据，但新run不读取旧下载/发布候选作业务输入；原完整名单和范围授权可读回，避免丢失待修复意图。

| 文件/记录 | 当前用途 |
| --- | --- |
| `history-plan.json`、`history-ranges.parquet` | 技术下载前保存完整变化/原未完名单、权威T/P、可信范围和授权来源；不按本轮返回代码缩小。 |
| `history-eligibility.json` | 本轮原T Raw覆盖判断及输入身份。 |
| `source/day/`、`source/history/`及各自`source-files.parquet` | 仅当前run新下载的完整261字段unit，逐unit保存/读回/释放。 |
| 两阶段`source-complete.json` | 只供当前运行在相应全部预期unit完成后进入处理；日阶段不等历史源，历史阶段必须完整范围全部源就绪。失败后下一run不得沿用。 |
| `publication/<phase>/<d>/<layer>/` | 当前run候选、intent、逐文件checkpoint及缺原键诊断；仅供当前run发布。 |
| `publication/<phase>/publication-complete.json` | 当前完整范围物理发布读回事实；历史去重还须来源run最终成功，失败run部分或全部文件事实不免除新下载。 |

完整plan保存并读回后，先yield AssetObservation记录T/P、D/轮次、当前run、plan/ranges位置及摘要、受控staging目录，再写开始下载观察并读回，成功才联网。阶段完成和失败结果仍走已有事件metadata；source-complete不替代文件验收，run SUCCESS也不代替完整范围事实。只按已验证run和固定路径读取记录，不全扫staging。

### 5.4 现有记录的封闭结构与摘要

本节为唯一字段结构。记录类型/字段顺序/有限原因集中在`defs/run_contracts/stk_factor_pro.py`，读写在既定io模块；不新增数据库或记录平台。

#### 5.4.1 公共类型、身份与读写

| 类型 | 固定要求 |
| --- | --- |
| Date / Instant | Date为Python date、JSON YYYY-MM-DD、Parquet DATE；Instant为aware datetime、JSON固定微秒和+08:00。时间不参与业务输入摘要。 |
| Digest / Count | Digest为64位小写十六进制SHA-256；Count为非负精确int，不能是bool。 |
| Double | 经§9.1转换的有限float，Parquet DOUBLE；NULL按源字段可空合同，不用NULL冒充0。 |
| RecordRef | `{creator_run_id:str,relative_path:str,file_sha256:Digest}`；路径必须在已验证run的staging根内，不接受绝对路径、..或符号链接越界。 |
| ContractIdentity | `{contract_name:str,contract_version:str,contract_content_digest:Digest,processing_version:str}`，本期源名stk_factor_pro、独立version和processing_version均为1。 |
| RunIdentity | `{creator_run_id:str,source_run_id:str|null,execution_day:Date,target_trade_date:Date,previous_trade_date:Date,purpose:str,scheduled_slot:int|null,submission_no:int|null,business_attempt:int|null}`；source_run仅指原名单/范围授权。 |
| phase / purpose / layer | phase只day/history；purpose只today/previous_day/manual_repair；layer只raw/silver，固定Literal值统一校验，不另加枚举映射。 |
| record_version | 精确int=1；未知/缺失字段、错类型或错版本拒绝，不能猜默认。 |

自动身份按§2.4；manual_repair实际执行日为当前上海日期，T/P仍为原日期，slot/submission/attempt均null。自动previous_day的attempt=1、submission=1～10；today二者均null。新run只写自己目录，不修改旧run。

HistoryPlanReason为集中有限IntEnum：1=本次T/P变化，2=原T失败/未完范围保留，3=缺P，4=缺T，5=两日因子都缺，6=生命周期证明无原历史。每股原因去重升序；它是名单解释，不是下载器错误码。

统一写入：校验完整结构/交叉条件→受控临时文件→flush/fsync→os.replace→fsync父目录→最终路径读回。旧下载文件可保留排障，读取原记录时只取业务意图/授权/失败或已成功事实，不把其Parquet当本run源。接口：

```python
def read_stk_factor_pro_history_plan(root: Path, *, expected_target: date,
    expected_run_id: str) -> HistoryPlanRecord: ...
def write_stk_factor_pro_history_plan(root: Path, record: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...]) -> HistoryPlanRecord: ...
def verify_stk_factor_pro_current_source(root: Path, record: SourceCompleteRecord,
    *, current_run_id: str, expected_units: tuple[UnitProjection, ...]) -> VerifiedSource: ...
```

VerifiedSource只保存当前run文件引用/统计。verify必须要求record.identity.creator_run_id==current_run_id，错run即拒绝，不能通过原run有效而放行旧源。失败阶段不触发业务源自动重试；下次新执行全新下载。

#### 5.4.2 摘要投影

复用现有`contract_registry.content_digest`；业务调用为`content_digest({"record_kind":kind,"record_version":1,"value":projection})`。日期先为ISO文本；DOUBLE因子为有限float.hex()，数值0统一0.0.hex()；投影不直接含float/date/Decimal。1、1.0、1.00归一化后相同，不引入容差。源contract_digest仍直接采用组件原算法。

| 摘要 / kind | 精确投影 |
| --- | --- |
| history_ranges_digest / stk_factor_pro.history_ranges | 按代码/起止排序的`[{ts_code,start_date,end_date}]`；未知范围保留null行，不删原完整名单对象。 |
| history_plan_digest / stk_factor_pro.history_plan | T/P、ContractIdentity、history_ranges_digest及按code排序entries；每项code、t_present/p_present、t_value_hex/p_value_hex、plan_reasons、去重升序origin_target_dates、earliest_basis(kind/date)。 |
| scope_digest / stk_factor_pro.scope | phase、T及排序units；UnitProjection固定`mode:int,object_code:str|null,point:Date|null,start_date:Date|null,end_date:Date|null`。day只有mode2/point=T，history是每原范围code一项mode5/start/end，不能按下载到几只缩范围。 |
| history_input_digest / stk_factor_pro.history_input | T/P、ContractIdentity、scope_digest及该完整请求范围内按code排序的权威t_value_hex/p_value_hex。不含范围外股票或整份因子文件sha。 |
| files_manifest_digest / stk_factor_pro.source_files | scope_digest及按unit_key排序的unit业务投影、源/保存行数、file_sha256/file_rows/schema_content_digest。不含当前路径/run/时间。 |
| schema_content_digest / stk_factor_pro.local_schema | 契约字段顺序的`[{name,type}]`，本地类型只VARCHAR/DATE/DOUBLE，不取DataFrame dtype展示文本。 |

上述业务摘要不含run_id、追溯路径、slot/提交序号、诊断、完整因子文件sha或20日批次参数。每个RecordRef另外核文件字节sha；业务摘要不能代替文件读回。unit_key为UnitProjection的同一规范摘要，不能用ordinal/run作身份。plan和ranges写成后不可原地修改；同T新run输入未变沿原revision，变更则原revision+1，首次1；处理中输入再变停止，不改已被引用的计划。

业务内容摘要只用于本次候选/正式文件等价比较、成功结果核对及bootstrap片段校验，算法见§8.1；不再以此建立跨失败run旧源续发授权。

#### 5.4.3 各现有文件

**history-plan.json**：`record_version,identity:RunIdentity,contract:ContractIdentity,revision:int>=1,created_at:Instant,history_plan_digest,history_ranges_digest,ranges_ref:RecordRef,full_code_count:Count,factor_t_ref:FactorFileRef,factor_p_ref:FactorFileRef,revision_of:RecordRef|null,origin_plan_ref:RecordRef|null,origin_history_plan_digest:Digest|null,origin_history_ranges_digest:Digest|null`。

FactorFileRef固定`trade_date:Date,asset_key:str=raw_tushare_adj_factor,file_sha256:Digest,rows:Count`；路径按正式paths复算。自动首次origin三项null，repair全有。repair始终保留原完整授权引用，不把本次新权威值摘要替换原授权。full_code_count等于ranges唯一代码数。

**history-ranges.parquet**：`ts_code VARCHAR NOT NULL,t_present BOOLEAN NOT NULL,p_present BOOLEAN NOT NULL,t_value DOUBLE NULL,p_value DOUBLE NULL,start_date DATE NULL,end_date DATE NULL,plan_reasons INTEGER[] NOT NULL,origin_target_dates DATE[] NOT NULL,origin_record_refs VARCHAR NOT NULL,earliest_basis_kind INTEGER NULL,earliest_basis_date DATE NULL`。唯一键ts_code；origin_record_refs是固定字段T/run/relative_path/file_sha的规范JSON数组，仅追溯。present=false必须value=NULL；有效历史请求因子/范围必须已判明、start<=end、end=T；范围未知不猜起点。earliest_basis_kind只1=可信现有最早日期、2=已批准bootstrap事实。缺关键因子/范围保留未判定并明确停止对应历史，不用技术行相等作门槛。

**history-eligibility.json**：`record_version,identity:RunIdentity,history_plan_digest,history_ranges_digest,raw_coverage:StkFactorProRawCoverage,evaluated_at:Instant`。覆盖结构和True/False/未知交叉条件见§5.2；技术因子同名adj_factor差异另放原诊断摘要，不参与放行。

**source/<phase>/source-files.parquet**：`phase VARCHAR,unit_key VARCHAR,component_unit_id VARCHAR,ordinal BIGINT,mode INTEGER,object_code VARCHAR NULL,point DATE NULL,start_date DATE NULL,end_date DATE NULL,source_row_count BIGINT,saved_row_count BIGINT,file_relative_path VARCHAR,file_sha256 VARCHAR,file_rows BIGINT,schema_content_digest VARCHAR,contract_content_digest VARCHAR,verified_at TIMESTAMPTZ`，除明确NULL列外均NOT NULL。唯一键(phase,unit_key)，每完整unit一个261列文件（合法0行也保存明确schema文件）。day mode2/point=T，其余对象范围null；history mode5/code/start/end全有且end=T，point=null。ordinal仅当前任务内序号；component_unit_id保留组件原值。statistics.row_count==len(records)==saved_row_count==file_rows；逐项字段/范围/身份必须对应，不能只比unit数。

**source/<phase>/source-complete.json**：`record_version,identity:RunIdentity,phase,contract:ContractIdentity,history_plan_ref:RecordRef,history_plan_digest,history_plan_revision:int,origin_history_plan_digest:Digest|null,origin_history_ranges_digest:Digest|null,history_input_digest:Digest|null,scope_digest:Digest,expected_units:list[UnitProjection],files_manifest_ref:RecordRef,files_manifest_digest:Digest,completed_unit_count:Count,verified_at:Instant`。历史input非null、日为null；repair原授权非null。仅在§6会话正常退出、最终summary通过后，全部expected_units与manifest身份/计数/读回一一对应，且全部属于当前run才写成。空历史名单直接跳过，不伪造下载完成。任何新run都不得以此省去失败任务的重下载。

**publication/<phase>/<d>/<layer>/intent.json及complete.json**：同一当前run固定结构`record_version,identity,phase,trade_date:Date,layer,contract,scope_digest,history_input_digest:Digest|null,source_manifest_digest:Digest,target_path:str,candidate_relative_path:str,prior_sha256:Digest|null,candidate_sha256:Digest,candidate_rows:Count,expected_published_sha256:Digest,mode:Literal["reuse","replace"],stage:Literal["intent","complete"],unrefreshed_keys_ref:RecordRef|null,unrefreshed_count:Count|null,verified_at:Instant|null,actual_sha256:Digest|null,actual_rows:Count|null`。target按T/d/layer复算并核对；prior仅当前候选构建时的正式文件sha，缺文件为null。reuse指当前正式内容已与**本次新下载生成的候选**等价、无需replace，不指旧源复用；其expected=prior，replace的expected=candidate。intent末三项null、complete全有；历史缺原键引用/计数全有（0行差集也明确），日二者null。

**publication/<phase>/publication-complete.json**：`record_version,identity,phase,contract,history_plan_digest,history_ranges_digest,scope_digest,history_input_digest:Digest|null,source_complete_ref:RecordRef,source_manifest_digest,targets:list[PublishedTarget],verified_at:Instant`。PublishedTarget固定`trade_date:Date,layer,skip_no_file:bool,file_sha256:Digest|null,file_rows:Count,checkpoint_ref:RecordRef|null,unrefreshed_count:Count,scope_rows:Count|null,scope_content_sha256:Digest|null,scope_content_version:int|null`；无旧无源日期明确skip=true、hash/ref=null/数量0，不假物化；有文件则skip=false、hash/ref齐全。历史scope三项全有，记录该完整成功范围在本日期/层的行数、业务内容摘要及版本1，空范围为0及空串SHA；day三项全null。全部预期日期/层去重升序无遗漏，历史所有unrefreshed_count=0才可完整。正式完成后还须同producer run最终成功才可成为后续正常轮次的历史免重刷依据。失败run即使此文件存在也不能复用其源/候选或部分checkpoint跳过重下载。

后续同T正常轮次以**原来独立成功的整个范围**逐批核对：原T、该范围全部代码/起止、对应权威T/P值及契约/处理版本一致，且必要正式内容/检查仍有效，才整体不重复历史。不要求新全名单的plan/ranges摘要与旧全名单相同，新增无关股票不能推翻旧完整成功范围；完整原授权仍各自验证，不把原范围拆成逐股成功片段。整文件sha未变可沿既有校验事实；仅其他股票改动整文件时，按该原成功范围在本日期筛选正式行，用§8.1相同算法核scope_rows和scope_content_sha256，全部匹配才保留成功。失败run绝不进入这条判断，不读取其旧下载Parquet，也不能按页/股票/日期领取失败任务的部分成果。

#### 5.4.4 小样本门禁

必须用独立字面样本证明：换run/路径不改业务输入摘要，改code/边界/权威值必须变；未知范围null不可删；source记录错run拒绝；0行合法完整unit可保存，缺列/计数不符拒绝；所有record必填/类型/未知字段校验生效。失败run即使source-complete及全部候选存在，新run仍有实际新网络请求，测试必须让旧Parquet一旦被当新输入读取就失败，不能只检查配置flag。bootstrap使用自身独立合同，不套本节失败重下规则。

## 6. 下载契约、线程、进度、错误与取消

完整契约名`stk_factor_pro`，独立version，不加来源前缀或`@1`。完整261业务字段含ts_code/trade_date及259数值；本地辅助列不进入接口fields。普通单日`DownloadTask(..., mode=DownloadMode.BY_POINT, points=(T.isoformat(),))`，历史`BY_OBJECT_RANGE`；代码扇开在组件内，业务规划范围/窗口。相同代码多窗口分次任务，同任务重复object_code被1102拒绝。

本文T、起止日期为本地`datetime.date`；进入组件前显式转为ISO字符串。历史统一使用`TimeRange(start.isoformat(), end.isoformat())`；各股范围不同则`ObjectTimeRange(code, TimeRange(start.isoformat(), end.isoformat()))`，不得把date直接传入组件。写本地unit记录时，组件scope中的ISO文本按本地Date合同显式解析，不把HTTP源行的YYYYMMDD与scope日期混用。`component_unit_id=result.unit.unit_id`，`ContractIdentity.contract_content_digest=result.unit.content_digest`；不按本地记录字段名猜组件属性。

分页暂定limit10000、offset从0步进10000、短页/空页结束、满页继续；属于源契约，不让业务传fields/limit/offset/token/地址。仍须有界真实核验，不能称已实测。每unit全部页取全后交业务一次，业务必要校验、候选落盘/读回后释放，不积累全历史内存。

日源和历史源均采用固定收尾顺序：with内逐完整UnitResult校验、保存源片段并读回，仅写staging；正常退出with后取得`summary=session.summary`。每个DownloadTask必须同时满足`summary.status == DownloadStatus.SUCCEEDED`、`summary.download_complete is True`、total_units/completed_units/delivered_units均等于该任务已规划unit数，summary.row_count/completed_row_count均与该任务已保存manifest行数之和相等。多窗口分次调用时逐session核对各自子范围；仅本阶段全部任务成功关闭、manifest完整覆盖阶段expected_units且行数对账通过，才写阶段source-complete并进入正式候选合并/提升。空历史名单直接走无待处理分支，不创建零unit下载任务。

session关闭可能在全部unit交付后抛1304，或最终为STOPPED/CANCELLED/FAILED；这些分支均不得写source-complete或进入正式发布，已有staging仅保留证据。UNIT_COMPLETED/100%或download_complete单独为True不能放行。组件最后一个unit完成回调取消但最终SUCCEEDED的既有行为仍按上述最终summary判断，不自行改组件取消语义。

`TushareDownloader.load()`和`with downloader.download(...) as session`沿用现接口；创建、使用、回调、关闭同线程。DG执行进程直接在执行线程调用，页面业务另开下载线程；跨线程/进程通信由业务接入层负责。组件不创建线程/子进程、锁、额度或全机限频，连接配置直接复用现有读取方法。

PAGE_COMPLETED/RETRY_SCHEDULED/UNIT_COMPLETED只传摘要，业务不在通知中写数据。UNIT_COMPLETED在交付前，100%不等于保存、日发布或历史全完。普通观察回调异常由组件隔离；业务校验/保存异常停止消费并关闭session，不交给组件重试业务写入。

组件错误码保持现有1001配置、1101契约、1102输入、1201权限/参数、1202限频、1203临时源、1204无有效响应、1205协议、1302容量、1304清理/关闭、1401取消、1501未分类源错误。业务原因集中登记，不随意扩展组件错误码。组件同页有限重试不消耗新的前日机会；一次已开始的前日日阶段失败且不能证明已齐，或仍缺/未知，则当天不自动补第二次或推进今天；仅历史失败而Q日阶段已齐不阻止今天。今天的临时源错误可等后续计划时点，永久输入/契约/权限、业务结构或目标冲突先报告停下，不盲重试。

分页/退避取消不交付半unit；完成通知时取消仍交完整当前unit再停，末unit可正常下载完成。业务取消后不领下一unit或提升新文件；replace前检查取消，当前文件一旦已经替换则尽力完成本文件fsync/读回/checkpoint后停止下一文件，失败保留intent排障，新run仍重新下载，不回滚已发布内容。网络可能等返回/超时，不强杀线程。with/finally关闭资源，已发布文件保留；午夜允许已运行任务结束，不模拟用户取消。历史前输入或Raw覆盖变了则停历史并留待处理，不能额外自动启动新任务或把它写成全部完成。

### 6.1 失败结果如何决定下一轮，以及管理员修复后如何解除

本节落实管理员已确认的“永久错误停下，人工修复并重新执行成功后解除”，不新增开关、错误表、状态资产或下载器错误码。单个失败的结果写入现有`dg.Failure(metadata=...)`，最外层按`precheck/day/history`记录发生阶段；历史抛错前仍保留真实日发布事实。未知异常只记安全摘要，不把token、响应全文或连接串写入metadata。

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
| 组件1202/1203/1204在有限同页尝试后仍失败 | true | 今天可以等下一固定slot；前日已开始仍受一次规则，不能再发。 |
| 1001/1101/1102/1201/1205/1302/1304/1501，或字段结构/日期/主键错误、目标冲突、本地读写失败、未知异常 | false | 停止对应T/阶段的自动重试，等待管理员；不拿换slot或清cursor当作解除。容量或磁盘问题不靠重新下载解决。 |
| 1401或业务取消 | false | 保留已提交事实，不自动取消后重发。 |
| 上游未就绪且明确PRECHECK_NO_DOWNLOAD | 不写失败标识 | 按§3.4等待后续未用slot，不消耗前日机会。 |
| 合法少股票、原T Raw覆盖不足或停牌输入未知等非执行异常 | 不伪造STEP_FAILURE | 保留覆盖/历史待处理；按已确认规则继续或等待，不增加blocking check。 |

`read_stk_factor_pro_failure(instance, run_id)`仅对已验证本数据集run调用`event_log_storage.get_records_for_run(run_id, of_type=STEP_FAILURE, limit=1, ascending=False)`，从`step_failure_data.user_failure_data.metadata`读取上述字段，严格检查类型和目标身份。缺记录、缺retryable、错类型、run异常退出或取消但原因未知均按不可自动重试处理，不默认true。直接参考现有`moneyflow_failure_retryable()`的读取方法，不改资金流代码。

更新sensor在§3.2选择目标后、构造RunRequest前，先读取该T最近有界run结果和本批阶段结果；不得只因代码仍缺就重发。机会统计使用`get_run_records(RunsFilter(job_name=update_job, tags={"dagster/partition":T}, created_after=D零点, created_before=D+1零点), limit=11, order_by="create_timestamp", ascending=False)`，逐条核对五字段。失败判断另对同job/同T、不加创建日过滤、最多11条读取，忽略明确的PRECHECK_NO_DOWNLOAD和未执行阶段；不能到新执行日就遗忘原T永久失败。第11条仍不能确定、配置身份混杂或证据不足时停止并说明。取得失败或人工重新执行的引用后，通过已知run_id精确查找关联事实，不全扫历史。

每个实际经过的阶段以现有AssetObservation保存固定摘要：`phase_result_version=1, target_trade_date, phase, result(completed/waiting/no_action), producer_run_id, recovery_of_run_id|null, unresolved_failure_run_id|null, source_complete_digest|null, publication_complete_digest|null`。未执行或等待的阶段不能制造成功，已有未解除失败须沿已验证引用继续保存；新日发布不能清除旧历史失败。观察只存摘要/引用，完整文件仍按原路径保存。读取每个已验证run的阶段摘要使用`get_records_for_run(..., of_type=ASSET_OBSERVATION, limit=16, ascending=False)`，只接收本Raw资产、同T、上述版本的阶段摘要；超过边界或找不到必要引用不得猜完成。这个16条上界来自本run的名单/开始/日结果/历史结果及失败收尾，分页通知不写这类观察；不得在循环里增加无界观察再放宽读取。

Q与今天各自判断。day/precheck的永久失败阻止对应T的自动job；history永久失败只停止该T历史自动重试：日数据仍缺时可以按正常slot更新日阶段，但历史步骤保留失败引用并跳过请求，日已齐且输入未变时不为该历史失败反复启动job。Q日已齐且仅history失败仍可选今天；原Q历史交原T手动repair，不扩成全数据集永久停止。临时历史失败可在今天后续slot按原完整scope规则重试；Q一次限制不变。

本节永久失败禁发规则仅由自动sensor使用；管理员明确重新执行原失败任务，核原任务身份、现有时间边界和唯一写入条件后，可以实际进入原失败阶段。不能在人工入口先套sensor的“未解除永久失败”分支，否则管理员永远无法取得用来解除的成功事实。

管理员解除不写“已修复=true”或清cursor：对原失败run明确重新执行；原T/阶段获得真实成功处理结果后，以新run的阶段观察保存`recovery_of_run_id`（取已验证parent/root；手动历史repair取配置source_run_id）及成功阶段。sensor核对关联、文件读回和必要checks后，只解除对应失败阶段。单纯run SUCCESS但该阶段未执行/只等待/无实际修复结果，不能解除。日阶段解除不要求全市场代码齐，但必须证明该阶段处理通过；历史阶段解除必须先通过原T Raw齐备条件并完成原失败历史范围；已消耗的Q机会依旧保留。历史repair成功只解除原T历史失败，不能解除日失败；日成功也不能把旧历史失败改成完成。相关失败run、成功run和文件事实的引用由本轮阶段观察持久保存，不新建状态表。

测试分别覆盖1201后下一slot零提交、1203允许今天下轮、缺失败metadata保守停、日已齐历史失败仍推进今天、人工无操作SUCCESS不解除、真正修复仅解除原T/阶段、清cursor无效、解除后Q机会不重获。原先§11的“错误不盲重试”必须调用这条真实读取分支验证，不能只测试错误码分类。

## 7. 失败后一律重新下载，以及前日一次边界

以下规则适用Tushare技术因子日更新和历史repair；不修改组件运行中的同页有限重试，也不改变Prod bootstrap独立恢复办法。

| 场景 | 新执行的固定行为 |
| --- | --- |
| 日源未完整，或完整后校验/候选/Raw/Silver发布失败 | 重新下载原T完整日源，不读旧source或待发布候选；与当前正式Raw合并，再生成Silver。 |
| 日阶段成功、历史下载失败 | 正式日文件保留；获准重执行自动job仍重新下载原T日源，Raw齐备且日阶段通过后，完整原失败历史范围全新下载。使用手动repair则不下载日源，只在原T Raw齐备后重新下载完整原失败历史。 |
| 历史源完整但任何后处理失败，或只有部分历史文件已发布 | 完整原失败历史范围重新下载；不按已完成页/股/日期续接，也不因source-complete存在省网络。正式已发布文件留作新合并基础，不能删除或回滚。 |
| 历史全部物理发布、最后事件或收尾导致run失败/取消/异常退出 | 仍按失败任务处理，下次重新下载原失败历史范围，不以局部或全部物理完成记录绕过本规则。 |
| 原目标T Raw缺失、不齐或覆盖未知 | 自动job保留已取得日数据，历史等待；manual repair直接报“原日期数据缺失”，不请求技术因子、不更新T、不提升历史。 |
| 已有历史整范围成功且业务输入仍匹配 | 正常后续同T轮次无需无故重复回刷；必须有完整范围成功事实与producer最终成功，不能使用失败任务记录冒充。 |
| 当前run在单文件replace后收到取消/读回失败 | 尽力记录当前文件真实状态后终止，不领下一文件；下一run仍新下载，不继续使用本run旧候选。 |
| 前日Q已实际使用机会后失败或仍缺 | 不自动补第二次、不推进今天；明确人工重执行不恢复自动机会。Q日已齐且只历史失败，按既定规则可推进今天，原Q历史人工repair。 |

失败候选不作为新执行输入；原完整名单、范围、失败原因与发布证据保留排障，正式数据不丢弃。新run只用自己新下载和验证过的数据构建候选，并与当前正式文件按主键合并。隐式自动重试业务写入仍禁止。

## 8. 合并与逐文件发布

Raw正式路径`/Volumes/datasource/data_lake/raw/tushare/stk_factor_pro/trade_date=<d>/data.parquet`，Silver为`/Volumes/datasource/data_lake/silver/stock_factor_pro/trade_date=<d>/data.parquet`；本run候选仅正式staging根。没有旧Lake、Kopia、备份或跨文件快照。

### 8.0 日数据与历史的Raw/Silver顺序

1. 日T：当前run新下载完整日unit→与当前合法Raw按主键合并→校验/发布/读回Raw T→从这份完整Raw仅转换日期生成Silver T→校验/发布/读回Silver T。旧未返回行保留；首次合法空不造文件，已有文件不清空。“完整Raw”只指该日期合并结果，不表示全市场齐或全历史完。
2. 两层日阶段完成后核§5.2的原T Raw覆盖；不足或未知时本轮历史零请求、零提升，保留完整名单等待补齐。Raw/Silver已经有效发布的日数据可供业务读取，不被历史门槛撤销。
3. 原T Raw齐备、权威T/P及完整待处理范围确认后，下载该范围的全部历史unit；全部在当前run保存/读回才进入历史合并。
4. 历史按日期d<T逐个Raw合并/校验/发布/读回→从这份Raw生成Silver d并校验/发布/读回。两层都刷新；不等全部历史Raw发布后才开始Silver。完整历史响应中T原文保留，但正式T只归日阶段写，不由历史覆盖。

每日期合并以当前正式B与当前新源唯一键U为输入，交集K，目标行数B-K+U；未返回旧键保留，重复键/非法日期拒绝而不去重掩盖。例旧4000、本轮4800且漏回旧50，最终4850；数字不是门槛。Raw源日期字符串，Silver DATE，259数值/代码/合法NULL与负数保持对应；额外合法来源行不按覆盖集合过滤。

### 8.1 当前run的候选、提升意图和逐文件记录

复用现有连接与发布算法，不直接带入moneyflow字段、阈值或锁。所有输入来自当前run的新下载；本轮开始已按既定唯一写入/维护流程排除其他任务。对每个日期/层固定执行：

1. 读取并校验当前正式目标B，记录本次构建时整文件sha（无文件为null）。从本run完整源生成候选；保留未更新股票，先完成§9的字段/主键/日期/全行对账。历史源缺原键以当前B的本范围键EXCEPT本run新U计算，保存当前run的unrefreshed-keys.parquet。
2. 候选fsync、读回并记录candidate_sha/行数；若与当前目标完整业务内容等价，mode=reuse且不重复replace，否则mode=replace。这里reuse是保留**当前正式文件**，不是复用失败下载数据。
3. 原子持久当前run intent（结构§5.4），包括本次prior/candidate/expected摘要、范围/合同/源身份；replace前再核正式目标仍等于prior，同文件系统、空间和取消检查通过才`os.replace()`。任何不明目标变化停止，不重登记实际hash绕过冲突。
4. fsync正式父目录、必要读回、写当前run complete，完成后才输出对应物化/check事件。即使状态/事件写失败也不撤销已经提交的业务文件；本run终止后，下次只重新下载和构建，不沿旧intent继续替换。
5. 当前文件replace后取消尽力完成该文件fsync/读回/checkpoint，停止下一文件。原intent保留用于说明已经发生什么，不成为新run使用旧候选的授权。

历史缺原键清单固定列`layer VARCHAR,ts_code VARCHAR,trade_date DATE`，每d/层独立，0缺也保存明确零行结果。缺旧键时有效新行仍可发布，旧键保留，但不记录整历史范围全部刷新；不另加第三blocking check。

完整业务内容等价/摘要沿现有ETF形式：261字段固定顺序struct_pack→to_json，按(ts_code,trade_date)升序换行string_agg→sha256，空集为sha256空串，数量另比。Raw和Silver使用各自日期schema，NULL真实编码，不填值或舍入；算法版本1。历史成功范围的scope_rows/scope_content_sha256只统计该范围各code的start_date<=d<=end_date且d<T的正式行，同日期多个范围以唯一代码/日期筛选、不重复计行；版本同为1。仅当前日期/层有界计算，用于本轮候选、已成功事实或bootstrap核验，不用于跨失败run续写旧源。

### 8.2 历史20交易日批次与整范围成功

从完整请求范围和已核SSE日历生成d<T开市日期并集，去重升序，每20个交易日切批，尾批1～20日直接处理，不凑自然日。先核历史分区已批准登记，缺分区停止，repair不自动注册。无旧无源日期不造空文件/假物化，存在源则以空基础生成。

每批至多40个日期/层文件，同任务一个主要DuckDB连接做列式合并与校验；当前日期Raw→Silver完成后再处理后续日期，批内逐文件checkpoint，不是20日事务。当前run完整历史源先保存，不能边下载一股边改全年。批次大小/序号不进入源unit或业务输入身份。

只有当前完整范围所有必要文件/check/读回及原键刷新核对通过，才写publication-complete；producer run最终成功后才成为后续同T轮次可跳过历史的依据。失败后已完成19日、第20日失败也不能跨run领取前19日为下载断点：重取原失败完整范围，再与当前文件合并，已提交不回滚。成功的其他独立完整范围不混入本次失败范围。

bootstrap按§10独立合同恢复。

## 9. 两个综合checks与事件

| 结果 | 合同与不能混淆的边界 |
| --- | --- |
| 输入就绪 | 股票复权因子Raw T/P完整复刻现有Raw因子必要check语义，sensor及job预检均必需；不用非空文件或Raw技术因子市场覆盖替代。 |
| Raw综合check | 可读/源字段类型/非空唯一主键/日期范围、完整unit源保存和B-K+U；股票未补齐不失败。 |
| Silver综合check | DATE、主键、对应Raw范围、完整业务字段/合法值及逐行对账；本期无新增过滤或填值，无数量比例门槛。 |
| 日可读/覆盖 | 文件及必要检查通过即可用；应有集合是T日上市人民币股票减全天停牌，盘中仍应有，按代码求差。上游覆盖依据未知不宣告补齐、不清空正式数据。本期Silver不额外过滤，成功生成后与Raw主键/行数对应；Raw源缺口与两层处理失败分别记录。 |
| 历史完成 | 原T Raw全市场应有代码已齐，完整名单、adj_factor数据集T/P、本轮完整范围及全部已发布事实对应；缺关键因子或覆盖未知不伪装0变化。producer最终成功后才可供后续轮次跳过历史；失败run的物理完成不免除重新下载。两接口因子差异只诊断，不宣称源指标数学正确性已经证明。 |

生命周期采用`list_date <= T AND (delist_date IS NULL OR T < delist_date)`。全日停牌按§5.2先核suspend_d_ready_for_trade_date(T)及最终silver_stock_suspend_daily文件身份，再使用其`suspend_type='S' AND suspend_timing IS NULL`，时段非空是盘中；不能因为停牌输入未产生便认定没有停牌，不读取confirmed数据自行合成。该集合用于判日补采和历史前Raw齐备，不过滤Raw；T/P股票复权因子数据集硬门槛与其覆盖参考缺失不是同一个条件。

sensor与job复核均使用现行`raw_tushare_adj_factor_ready_for_trade_date(instance, trade_date)`，只针对T/P读取Raw因子物化及其3项检查事实，共2分区×3项check；它不是全市场股票覆盖证明。job再对实际两份Raw文件执行字段/日期/唯一性/正值等必要业务校验并比较。不得改用`batch_raw_adj_factor_lake_readiness`然后声称只扫两份Raw：当前实现即使layer=raw仍构造Silver路径、校验Silver并进入含生命周期的聚合，隐藏读写范围和成本不符合本次边界。本需求不修改该已有helper；sensor不算全名单，job显式处理无P与旧待处理。

每天检查定义始终两个，不按股票/字段/窗口新增。日阶段两资产各一个输出/check；历史涉及D个d<T日期时最多另有2D个物化和2D个检查结果。内容未变不重复替换，事件如实标注保留当前文件并通过本轮校验，不能宣称文件内容发生变化。十个计划时点包含前日补采占用，不能预算成10次今天另加1次Q；此外还需计预检记录、下载开始/名单观察及历史事件，整晚不只两条事件。

已用Context7及本地安装代码核对`multi_asset(specs, check_specs, partitions_def)`、`AssetCheckSpec(blocking, partitions_def)`；同一步内阻断由业务显式执行。`AssetCheckResult`没有partition；历史`AssetCheckEvaluation`及`target_materialization_data`参考现行repair/资金流事件代码。相应实现后隔离验证：日物化后历史失败仍可读、检查真实绑定正确partition/run/materialization、重复输出不产生异常、观察持久化时点、历史批量取事件而非逐日深扫。静态代码核对不等于事件API运行验收。

发布前、读回与checks复用纯校验及本批聚合证据，文件改变不沿旧绿色。sensor只看今天/Q的有界结果及必要输入，不全湖或全事件扫描；超过100历史分区或分区×check数超过1000按治理批量聚合。覆盖诊断和历史待处理不新增状态资产，cursor不是事实源。

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
    target_trade_date: date, candidate_path: Path,
) -> StkFactorProFileAudit: ...
```

HTTP实际fields必须与完整源契约字段集合一致、无重名，每行值数与实际fields一致；依实际fields建立位置映射，再显式投影为契约的固定顺序。仅顺序不同不丢行、不错位；缺列、多列或重复列明确拒绝，不借zip截断或补None兜底。bootstrap的SELECT本身按白名单排序，游标description须与该完整投影顺序一致。

HTTP适配必须接真实`UnitResult`：先确认termination全部scope完成、statistics.row_count与len(records)一致，核`observed_field_sets`（包括合法空结果的字段集）；逐个SourceRecord用它自己的fields映射自己的values。同unit跨页列顺序不同也不能用第一页位置套所有行。`stk_factor_pro_http_rows`按契约顺序惰性产生值tuple给公共批转换函数，不先复制整个unit为第二份行列表。Prod则用cursor.description的列名核顺序，直接把本批tuple rows交同一转换函数；公共函数不直接接受SourceRecord，也不猜其结构。

`StkFactorProFragment`是frozen dataclass，固定`relative_path:str,file_sha256:str,content_sha256:str,schema_content_digest:str,row_count:int,observed_schema:tuple[tuple[str,str],...],min_trade_date:date|None,max_trade_date:date|None,first_code:str|None,last_code:str|None`。路径、摘要和计数按§5.4校验；零行时日期/首尾代码全None，非零时日期/首尾代码全有且有序。它只描述当前已保存片段，不放业务行；HTTP一个完整unit对应一个文件，bootstrap各5000批对应各自片段。

| 字段/来源 | 接受值 | 明确拒绝/禁止 |
| --- | --- | --- |
| `ts_code` 两来源 | `type(value) is str`，精确匹配本数据集股票代码合同，当前A股为六位数字加 `.SH/.SZ/.BJ`；保留原字符串 | NULL、空白、前后空白、整数、任意对象转str；不自动trim/补前缀/改代码 |
| `trade_date` HTTP | `type(value) is str`，ASCII八位数字；先核正则 `[0-9]{8}`，再按年月日构造 `date`，最后 `%Y%m%d` 回写必须与原文一致；该日期须处于本unit约定日期范围 | 空、NULL、`2026-10-21`、整数20261021、`20260230`、多余空白、日期越界；不使用宽松自动推断、不静默转NULL |
| `trade_date` Prod | `type(value) is datetime.date`（不接受子类datetime），源 schema 核为DATE后，显式 `value.strftime('%Y%m%d')`；检查本批准窗口/本次选中日期 | timestamp/date字符串/NULL；源 schema 变化须先停下核合同，不临时兼容 |
| 259数值 HTTP | `None`、精确 `int`（不含bool）、精确 `Decimal`；符合有限DOUBLE范围后显式一次转 `float` | bool、str、float（当前HTTP合同不交付float）、NaN/Infinity的Decimal、转换溢出；不把字符串数字、空字符串当合法数 |
| 259数值 Prod | `None`、精确 `float`；以当前Float(53)真实合同为依据 | Decimal、str、bool、NaN/Infinity；遇见不同真实源类型先报源合同不符，不隐式容纳 |

数值标量规则：先检测来源精确类型，None直接保留NULL；Decimal先 `is_finite()`，其他可接受数值使用 `float(value)`，捕获 `OverflowError/ValueError`，再 `math.isfinite(result)`。负数、0、极小但DOUBLE仍可表示的有限数、合法NULL均通过，不按价格正数或指标合理区间过滤。若有限非零输入转换成0，报无法无损表示该非零数，不能静默消失；一般十进制->IEEE754 DOUBLE的舍入属于已声明存储映射，不逐位要求Decimal精确相等。正负0按数值等价比较；不新增容差。

HTTP unit 已完整交付后，只处理当前一个unit并创建其列数组；bootstrap则仅处理当前5000行批次。5000不是下载器参数，不为HTTP新增一个同值配置，也不能自行把分页当完整unit。数值明确 `pandas.array(..., dtype="Float64")`，缺失使用 `pd.NA`；不先让DataFrame推断把None与源NaN混为一谈。`stk_factor_pro_double`是标量语义和小样本测试依据；实际批内按列构建，禁止构造全历史Python行集合。批内必要类型/范围校验不执行任何逐行数据库写入。

注册当前批DataFrame到本任务既有DuckDB连接，SQL以显式 `CAST(... AS VARCHAR/DOUBLE)`建立当前批临时关系，并校验转换前后NULL数量/行数一致；`COPY (SELECT <261白名单列> FROM current_batch ORDER BY trade_date, ts_code) TO <受控候选> (FORMAT PARQUET)`。写后读回 schema、行数、主键/日期和当前批完整业务值；最后unregister、清临时关系、释放rows/列数组/frame，才取下一批。仅当前批来源对象和转换对象共存；不使用executemany，不额外构造无用SDK DataFrame，不新装依赖。

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

- 源片段保存对账：expected为本批按上述规则转换后的261列，actual为读回片段；两者统一Raw表示。
- Raw合并对账：B为已验证的旧Raw，U为本阶段本日期完整、唯一主键的新Raw源。expected关系为 `SELECT B.<261列> FROM B WHERE NOT EXISTS (SELECT 1 FROM U WHERE U.ts_code=B.ts_code AND U.trade_date=B.trade_date) UNION ALL SELECT U.<261列> FROM U`；actual为候选/已发布读回Raw。
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
| 每轮预检/名单 | sensor只查候选T/P和已有状态；job读两因子文件并比较、保存完整名单，复用的是名单意图，不是失败run下载数据。 | Raw因子两日期三项check查询、job两因子Raw文件校验/比较、名单修订及前日机会定位；原T技术Raw/生命周期/停牌各一份，历史三处只核引用，改变才重算T覆盖。不能逐tick重做名单或逐文件重扫因子。 |
| 单轮日源 | 有界样本5568行×261字段，暂定10000页大小约1次正常请求，恰满须继续。 | 完整HTTP字节/耗时、候选读写、T旧文件与两层必要checks/覆盖成本。 |
| 晚间与前日 | 今天理论至多10固定时点，Q实际一次会占时点；无并发/积压。重试、分页、预检未开始再发及手动处理另计。 | 整晚源/合并/事件/候选留存峰值；不是下载组件请求总上限。 |
| 复权历史 | C代码、W窗口、D历史日期，完整原范围正常请求`sum(floor(H_i/10000)+1)`；同页最多另加3倍尝试；原T Raw不齐时0历史请求，整范围成功且输入未变才不重复。 | 完整历史源保留T但只发布d<T；20日/最多40文件局部合并，当前正式B与新源U字段/主键对账、缺旧键记录、空间与事件批量读取。 |
| 失败后重新执行 | 无论失败在下载、候选、Raw/Silver发布或事件收尾，重新执行均计入整阶段新下载请求；完整旧源不省网络，Q不重获自动机会。 | 当前正式文件读回/合并/校验、全部原失败范围重新下载、当前run候选与intent、最终读回和保留失败证据的空间；不计旧候选续接收益。 |
| 手动repair | 先核原T Raw完整：不足/未知直接报错，0技术因子请求/0提升；通过后完整原失败范围全部重新下载，只d<T合并/事件。 | 原run有界授权定位、4字段/两摘要校验、原T覆盖三份文件读回、T/P权威因子、完整新下载及20日批次/最终对账；无对象T单日确认请求，不计为自动时点或Q机会。 |
| bootstrap | 获准Prod范围显式261字段，按自然月及5000行服务端流式批量；单月约`ceil(月行数/5000)`次取批、非每日期新连；逐文件候选/发布，事件另授权。 | 当前准确范围/源截止与月计数、来源维护窗口、只读事务/超时、峰值磁盘，以及未完成日期重取、完整日源复用、逐文件继续和最后对账成本。 |

容量不足、范围超批准或候选不完整停止并说明，不减少字段/股票或缩短历史造完成。禁止无界导出、全历史长事务、Python逐行大合并、每日期新连远程库的未经测量默认。参数与验收目标已确认，尚无对应来源/性能运行验收结论；不因写了目标就宣称已经达标，也不将尚未实现的完整链路运行验收错置为现在必须通过。

bootstrap的5,000行估算依据是当前`RawStkFactorPro`和261字段契约：代码按9字节ASCII、Prod DATE净值4字节、259个Float(53)按8字节，全非空净值`5000×(9+4+259×8)=10,425,000`字节，约9.94MiB；不是PG整行或Parquet文件大小。常见文本数值平均8～12字节时，计每列4字节长度及每行协议头约15～20MiB，数值按24字节估算约35MiB；格式、NULL及驱动改变会影响实际量，不把它当绝对协议上限。64位CPython基本tuple/float/date/code对象约40MiB，另有libpq缓冲和列式转换；本批工作空间先按128MiB估算、256MiB留余量，不新增硬限制，也不声称进程峰值。仅取261列，不读raw_payload等辅助列；实现采用服务端named cursor，不得以普通cursor.fetchmany冒充流式。上一批保存并释放后才领下一批，不能在Python累计整月。Tushare的64MiB响应/2GiB unit限制不用于Prod数据库导出，DuckDB的16GB也不是Python/libpq总内存上限。正式导出前复用已有schema证据核准实际字段类型；不为大小估算另拉5,000行压测。

### 10.1 bootstrap自然月规划、5000行流式和恢复

初始化准确起止、源截止、来源维护窗口及正式执行仍须按原批准范围另行核准；本节固定实现办法，不把2017年样本起点套给所有股票。planner按批准起止截取自然月，记录闭开查询边界`[month_start, next_month_start)`，首末月裁到批准范围；显式投影261业务字段并按`trade_date, ts_code`稳定排序，不select *或读取raw_payload等辅助列。通过既有`ProdPostgresResource.connect_readonly_transaction()`每月建立独立只读事务、`connection.cursor(name=受控唯一名称)`及统一`itersize/fetchmany`批量；不能一条完整历史长事务，也不能每天重复建远程连接。

每次取至多5000行，按已核对源类型进行列式转换，保存为该run该月staging下连续编号的Parquet片段，读回核对源/保存条数和必要字段后释放rows及转换对象，才取下一批；日边界可以跨多个5000行批次，不能当成多份正式日文件或只保留最后一批。禁止fetchall、客户端普通cursor冒充服务端流式、Python逐行大表写入及把整月累积到列表。查询按`trade_date, ts_code`有序，看到下一日期或游标EOF才确认前一日期已收齐，保存其完整日源清单后，由同一主要DuckDB连接生成该日Raw/Silver候选并逐文件发布；不要求整月源完成才发布已完整日期，也不在每5000行时覆盖正式日文件。存在既有正式目标须按初始化批准的冲突策略停下或执行获准合并，不自行覆盖；首次无旧文件直接生成日期候选。

自然月仅是远程查询窗口，不新增月级完整门槛或恢复平台。游标中断时，当日未收齐的源片段不发布；已完整保存/发布的日期按既有日源完整事实和逐文件intent/checkpoint核验后保留或复用，完整日源存在但发布失败不强迫重读数据库。获准重执行时对本月尚未完成的日期做有界查询，整日重新读取，不按OFFSET、5000行批号或最后一行继续；没有明确完整事实的日期不能猜已经完成。源范围/截止修订则核对相关旧源是否仍适用，不能假作新依据完整。正式事件补录仍独立授权，物理阶段不借机运行正式Dagster。

### 10.2 bootstrap批准输入的封闭结构

bootstrap继续是单独获准的直接文件写入，不接入日常job或下载器。唯一来源固定 `ProdPostgresResource` + `raw_tushare.stk_factor_pro`；261字段来自唯一源合同。以下是执行前审核并保存的业务输入，不是env、页面配置或任意SQL入口；普通调用不得自行生成一份“批准”记录。

```python
@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapApproval:
    record_version: int                 # 固定1
    operation_id: str                   # 受控安全标识，非路径
    start_trade_date: date              # 批准闭区间
    end_trade_date: date
    source_cutoff_trade_date: date      # end <= cutoff
    source_maintenance_start: datetime  # 有Asia/Shanghai偏移
    source_maintenance_end: datetime
    source_identity_digest: str         # 非秘密来源定位+表+schema白名单摘要
    contract_content_digest: str
    approved_daily_counts_ref: str      # 受控staging相对路径
    approved_daily_counts_digest: str
    approved_source_evidence_ref: str   # 已批准范围/维护约定/固定样本证据
    approved_source_evidence_digest: str
    month_limits: tuple[StkFactorProBootstrapMonthLimit, ...]
    source_statement_timeout_ms: int    # 正整数，正式数值执行前批准

@dataclass(frozen=True, slots=True)
class StkFactorProBootstrapMonthLimit:
    month_start: date                   # 本批准范围裁切后闭边界
    month_end_exclusive: date
    row_upper_bound: int                # >=此月批准日计数之和，非5000
```

JSON读取拒绝未知字段、缺字段、重复键、非标准日期/无时区时间、bool冒充int、非正timeout、负上界、月份重叠/缺月、首末月未按总范围裁切、end>cutoff、维护窗口已过期、引用越界/符号链接、摘要不符。零行月可上界0；5000/20日/DuckDB参数不放此输入供覆盖。`approved_daily_counts`是Parquet固定 `trade_date DATE,row_count BIGINT`，批准范围每个日历日期一行，0明确记录；范围外不得混入，计数不得负数/NULL/重复。日历、缺日解释、源截止及批准日期分区另按原方案完整核对，不能用0行记录抹去应有缺日问题。

来源身份摘要仅从当前resource解析出的非秘密主机/端口/数据库定位及固定schema/table、实际获准源列名/源类型和合同生成，不包含口令、完整DSN或token。实际数据库表的schema核验属于执行预检，不能跨工程import Prod ORM充当真实schema证明。维护约定和固定有界样本核验不等于逐行证明整个来源从未变化；必须明确依赖已获准维护窗口，发现违反维护约定/样本或计数变化即停止。

所有批准记录、来源片段、日期完成记录和候选位于 `/Volumes/datasource/data_lake_staging/stk_factor_pro/bootstrap/operation_id=<id>/`下，由paths.py生成；正式路径仍使用既定Raw/Silver路径。调用者不得传Lake根、staging根、表名、字段清单、SQL、过滤片段或任意文件路径。读回引用按规范相对路径限定本operation或明确引用的旧operation，拒绝`..`、绝对路径与符号链接穿越。

```python
def validate_stk_factor_pro_bootstrap_approval(
    *, approval: StkFactorProBootstrapApproval, now: datetime,
    source_identity: StkFactorProSourceIdentity,
) -> tuple[StkFactorProBootstrapMonthLimit, ...]: ...
def export_stk_factor_pro_bootstrap_month(
    *, prod_postgres: ProdPostgresResource, connection: DuckDBPyConnection,
    approval: StkFactorProBootstrapApproval, month: StkFactorProBootstrapMonthLimit,
    selected_dates: tuple[date, ...],
) -> StkFactorProBootstrapMonthResult: ...
```

`StkFactorProSourceIdentity`为frozen dataclass：`host:str,port:int,database:str,schema:str="raw_tushare",table:str="stk_factor_pro",columns:tuple[tuple[str,str,bool],...],contract_content_digest:str`；columns按261字段白名单顺序保存真实源列名、数据库源类型及nullable，来源摘要使用§5.4的规范投影，禁止含密码/DSN。端口1～65535，身份文本不得空，schema/table不能由输入任意替换。

`StkFactorProBootstrapMonthResult`为frozen dataclass：`month:StkFactorProBootstrapMonthLimit,attempt_id:str,source_rows:int,fragments:tuple[StkFactorProFragment,...],complete_dates:tuple[date,...],pending_dates:tuple[date,...],file_audits:tuple[StkFactorProFileAudit,...]`。fragments按保存顺序、日期集合去重升序；不额外引入另一个Month类型。该结果不是恢复事实源，完整日期和文件仍须有固定路径记录读回。

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

绑定值为本月裁切边界、已批准且尚需重新读取的日期数组、`R+1`。R取该月已批准 `row_upper_bound`；selected_dates不能为空（空则无需开连接），全在本月和总批准范围内且升序去重。SQL永远不加OFFSET；表名/列名不取用户字符串，也不拼接日期。普通控制cursor只做SET/schema/有界计数/固定样本核验；261字段明细只通过 `connection.cursor(name=受控唯一名, scrollable=False, withhold=False)` 的单条SELECT读取。`itersize=STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS=5000`，每次 `fetchmany(min(5000, R+1-seen))`，不得fetchall。

预检批准的日计数和当前按日计数一致，selected_dates计数之和<=R；导出最终又按每日期实际行数核批准计数。R+1是运行中的截断防护，不是正常数据分页大小。**先检测是否收到了第R+1行，再把该行当“后一天已经开始”的依据。**触及R+1立即停止，不保存额外行，也不把当前未关闭日期记完整；此前已经完整发布的日期保留。恰好R行且真正EOF、日计数/主键/日期等均核对通过时才允许完成最后日期，不能把LIMIT造成的返回结束误当来源本来就没有更多行。

每批先核完整261字段、类型/日期范围和排序。跨批维持上一批最后 `(trade_date, ts_code)`，键必须严格升序；同日跨批重复/逆序即停，不能去重。当前批转换成Raw表示后存 `source/month=<YYYY-MM>/attempt_id=<id>/fragment-<连续编号>.parquet`，原子保存、读回，记录以下清单后才释放本批：

`fragment_no BIGINT, path VARCHAR, file_sha256 VARCHAR, content_sha256 VARCHAR, row_count BIGINT, min_trade_date DATE, max_trade_date DATE, first_code VARCHAR, last_code VARCHAR, approval_digest VARCHAR, source_identity_digest VARCHAR, contract_content_digest VARCHAR`。source kind固定Prod；path是本operation内相对路径；内容摘要仍按固定261列、Raw日期表示与既定DuckDB算法。

同一片段可含多个日期。已保存批内出现新日期时，只关闭其前一个日期；批末日期暂不关闭，等下一批新日期或真正EOF。每个完整日期形成 `source/dates/<YYYY-MM-DD>/source-complete.json`：格式版本、批准/来源/合同摘要、原operation、目标日期、本日期批准行数/实际行数、所引用片段及其指纹清单摘要、过滤条件固定 `trade_date=<本日YYYYMMDD>`、完整日期内容摘要、真实关闭原因（看到下一日期或正常EOF）、完成时间。整日行数、主键唯一、字段/日期全部核对通过才原子保存并读回；绝不能只记录“最后一个片段”。

例：片段1含A日5000行；片段2含A日500行+B日4500行；两片段保存并读回后，A完整记录同时引用片段1、2，仅筛A日得到5500行。B须等后续片段见到C或真实EOF才能关闭，不能只因片段2已存便发布B。完整A可立即进入本日候选/Raw/Silver逐文件发布，不要求B或整月完整。批准0行日期只保存明确空源结论，不制造正式空文件/假物化，也不借此删除原有文件。

### 10.4 bootstrap中断、目标冲突与最小验收

完整日源可复用时，必须核原批准输入/来源身份/合同及源截止、维护约定仍适用、引用片段全部存在且指纹内容匹配、日行数和完整业务字段读回通过。随后从其Raw源重建候选并沿既有逐文件意图恢复；事件写成功与否不是完整源成立条件。同operation重执行不得改写已被完整日期引用的旧attempt片段，原完整日记录不可变；当前attempt只写新片段和此前未完成日期的完成记录。新的operation不得扫描或悄悄接用旧operation。

当前日未关闭、查询超限、超时、schema/类型/计数变化或游标断开：不发布该未完整日期；获准再执行时在对应批准月内按尚需日期数组整日重读。不能按最后code、OFFSET、fragment编号接读，不因已读了某股而跳过；已完整日源即使尚未发布可直接核验复用。已经提升Raw而未完成Silver，按照§8.0从核验后的正式Raw生成Silver。

首次bootstrap没有旧文件直接生成；已有目标仅可确认内容等价而不覆盖。目标不同且原批准没有明确允许如何更新时必须停止，由管理员确认具体更新范围和处理方式；不能给执行参数增加任意overwrite开关。恢复时自身已提升、意图尚未记完成的情况照既有目标/候选指纹读回补事实；旧完整源不得覆盖后来合法修改的正式文件。

bootstrap恢复沿同一获准operation的逐文件记录，独立于§8的Tushare失败重下规则。记录本次日期/层、批准摘要、完整日源摘要、prior_file_sha256（原先无文件为None）、candidate相对路径及摘要、expected_file_sha256和完成阶段。先核批准/完整日源/受控路径；正式目标已经等于expected时，重新读回必要校验后补完成记录，候选已被replace移走不构成失败。正式目标仍等于prior、候选仍存在且等于expected时，才可沿原意图继续同文件系统提升、fsync、读回和完成记录。目标既不是prior也不是expected、原记录不明或完整日源已失效时停止；不能登记新的prior绕过外部改写。Raw已完成而Silver未完，核当前合法Raw身份后由它生成Silver，继续同样规则。这里只恢复独立bootstrap，不授权任何Tushare失败run复用下载源。

预算继续复用已确认5000行估算（约9.94MiB净字段、128MiB工作空间/256MiB余量），不把估算当进程硬限制；一批源对象、显式列数组和写入缓冲的短暂共存纳入估算。每月事先给出批准日计数之和、R、261字段行宽估算、预期5000批次、日/两层文件数量、单语句超时和剩余空间；空间需覆盖当前批片段、尚需保留的完整日源、当前日期两层候选及DuckDB临时开销，不只算最终文件。保留完整日源所需空间随批准范围变化，不自动删除旧源来腾空间。

测试落点：`test_stk_factor_pro_candidates.py`、`test_stk_factor_pro_checks.py`、`test_stk_factor_pro_bootstrap.py`。均临时文件/隔离DuckDB及假Prod游标，无真实批量读库。

| 必须证明的边界 | 独立小样本与断言 |
| --- | --- |
| 类型/日期 | HTTP Decimal('0.1')、int、None、负指标正常；Prod float/date正常；bool、字符串数字、datetime、YYYY-MM-DD源日期、20260230、NaN、Inf、overflow及非零下溢各自明确拒绝，不能变NULL继续 |
| 精确对账 | 0.1转换后通过；NULL/NULL通过，NULL/0及任一末尾业务字段变化失败；缺键与多键同数量抵消仍失败；重复键失败；不因合法负数或少股票失败 |
| Silver来源 | Raw5000/Silver4800、本轮U4800，期望Silver5000；历史一天两股中只刷新一股，另一股261字段不变；不等待其他历史日期完成 |
| 5000与完整日 | 5000+500跨批同日，第二片段另含下一日；本日完整记录引用全部片段并按日筛选；未关闭日期绝不发布；0行不造文件 |
| R+1 | R-1、R、R+1行；R行真实EOF才正常，R+1触限先停止，不能用超限行关闭当前日；批准计数不符即停；此前完整日期保留 |
| SQL安全/只读 | 字段/表固定；日期/数组/limit/timeout值绑定；named cursor、5000、关闭/rollback；反例抓fetchall、OFFSET、普通cursor明细、系统字段/任意路径/未知输入参数 |
| 失败恢复 | 完整日源后退出可0次远程明细重读；半日片段须整日重读；Raw已提升Silver未成从当前合法Raw生成；来源依据过期/片段损坏/正式目标后改均停，不旧源覆盖 |
| 性能与真实边界 | 复用批准小响应/既有schema证据作最小来源交接；不为5000行估算去读5000行或全历史；批次1/5000/跨日边界用小夹具替换批量常量测试；记录正常/恢复/最后对账的读写和SQL数量 |


## 11. 测试与验收要求

以下是待实现门禁，不是通过结果。夹具来自现行生产者/合同和有界样本；expected为独立字面小样本，网络替身不能声称真实接入通过。新增/调整测试文件在现有tests下按对象分为`test_stk_factor_pro_sensors.py`、`test_stk_factor_pro_history.py`、`test_stk_factor_pro_repair.py`、`test_stk_factor_pro_publication.py`，转换/检查/bootstrap沿§10.4列出的文件。

| 主题 | 必须证明的正反例 |
| --- | --- |
| 交易日与自动边界 | 周一Q为周五、P再前一交易日；只今天/Q；19:00～23:30固定slot，活动占用跳过、午夜排队拒绝/已开始可结束，不改前日一次。 |
| 人工重执行与自动保护 | 自动Q机会已用仍零自动提交；同D窗口内管理员明确重执行可重新下载Q，不恢复自动机会。永久失败修复后人工确实进入原失败阶段，真实成功才解除；无parent/身份不符仍拒绝。 |
| 前日机会与原生tick | PRECHECK_NO_DOWNLOAD不耗、开始事实写后crash保守耗、清cursor不复活；19:30活动跳过后清cursor仍不补发，首次合法slot可发；临时instance实存tick。 |
| 输入与完整名单 | T/P Raw未就绪不提交/不联网，job二次核；完整变化名单先于技术网络保存，不按本轮源少股缩小。缺P/缺T/两日缺必须保留未知，因子改回相等不抹掉原失败范围。 |
| 原T Raw齐备 | 五股应有、Raw只有四股：日Raw/Silver可发布，历史请求和提升均0；第五股补齐后全名单一起历史。不能只看行数/字段check绿/某次unit完成。 |
| 集合与停牌 | 五股中一股确认全天停牌，另四股Raw齐即覆盖完整，停牌变化股也可刷d<T；盘中不扣除。停牌未知或文件日期/身份错不能认齐，重复一股缺另一股同数量仍拒绝。额外合法源行不删。 |
| 手动入口四字段 | 四项必填、准确ops层级；错T/job/原plan/ranges/越根路径拒绝；未知配置字段拒绝。source_run只定位原授权。 |
| 手动原T缺失直接报错 | D和原T不同，只看原T Raw；缺文件/缺代码/结构错/覆盖未知均抛固定“原日期数据缺失”提示，retryable=false，技术网络/日更新/历史提升/T事件全部0；今天齐不能替原T。 |
| 手动不代办日更新 | 对BY_POINT、原对象T确认及日发布函数设调用即失败的替身；Raw齐后只完整原名单/原范围历史，不能加股/延边界/改T，不发T确认窄查询。 |
| 日期与下载会话终态 | 本地date转ISO后接入真实组件输入校验；直接传date拒绝。全部unit已交付但关闭抛1304、或summary为STOPPED/CANCELLED/FAILED时，不写source-complete且正式提升0；仅最终成功并unit/行数对账一致才放行。 |
| 失败阶段全新下载 | 分别在日源未完、源完未发布、Raw完Silver失败、历史源完未发布、历史部分已发布、全部物理写完事件失败处退出；新run所有所需unit均重新网络获取，不读取旧源/候选、不得按页/股/日期跳请求。 |
| 新数据确实覆盖旧候选 | 固定旧候选值10、当前正式值11、新网络值12；重执行必须得到12，且保留正式中源未返的合法旧键。旧source路径若被当新输入读取则测试主动失败。 |
| 正式已发布保留 | 失败/取消后当前已发布文件仍在；新历史请求全范围后基于这些当前文件合并，不删、不回滚、不重放旧候选。成功的其他独立完整范围不无故并入失败范围。 |
| 完整成功免重复 | 仅producer最终成功且整范围publication-complete/输入/范围有效可避免后续同T重复历史；全名单新增一股不使原独立成功范围重下，其他股改同日文件时核scope行数/内容摘要仍有效，原范围任一业务值改变则不沿旧完成。repair核实已无待处理历史时返回真实no_action，零技术请求/零正式提升，不伪造本run新完成历史。producer失败即使有完整源及物理记录仍重下。 |
| 当前run安全发布 | 候选必要校验→intent→再核prior→replace/fsync→读回/complete；目标变动拒绝，事件失败不回滚。当前正式内容与新候选等价可不replace，但必须已经本次新下载。 |
| Raw→Silver与T边界 | 每日期从最终Raw生成Silver；Raw5000/旧Silver4800/本轮只返4800，Silver必须5000；历史只d<T，源T保留但不覆盖正式T。 |
| 历史完整和漏原键 | 全部当前run约定源完整才首批20日；源少旧键时保留旧行、有效行可发布、原键缺项诊断非0不假称整范围刷新，不新增第三check。 |
| 无输出与事件持久顺序 | PRECHECK_NO_DOWNLOAD及首次合法空结果在临时instance正常结束、无伪造物化/check；历史先yield物化再读本批真实记录并yield关联检查，不能拿未处理的log_event缓冲作完成依据。 |
| 20日与性能 | 1/20/21/41交易日、假日/末批/无行日；当前run逐日期Raw→Silver、不按20日事务；失败下次全范围重下而不按已完成19日续源。 |
| 错误/取消/事件 | 1201等永久错误不下轮盲重试；1203允许今天下一slot但仍新下载；阶段正确解除，不恢复Q机会。out={}、历史显式partition/check关联、标准通知不写业务数据、取消不领下一unit/文件。 |
| bootstrap独立边界 | 5000流式、月R+1及SQL超时/跨日完整证明；沿其独立批准operation的完整日期恢复，不被本次Tushare失败规则误改。 |

用一套临时文件/instance和小样本覆盖上述分支；至少一次真实子进程退出后由新进程按新规则重新下载。不得通过skip、mock字段兜底或调用待测计算生成expected掩盖错误。

### 11.1 已确认的最小验证安排

管理员已确认§10参数及以下精简验证安排。尽可能复用仍适用证据，用小样本证明关键边界；不以大范围反复跑数代替边界验证，不为5000行大小估算另读生产样本。参数拍板不表示测试或真实验收已经完成。

| 时机/内容 | 最小范围与证据要求 |
| --- | --- |
| 开发前来源确认 | 优先复用261字段、本地源文档及已有审计；仍缺的正常HTTP/offset证据先列固定日期、代码、全部字段、请求数，再做有界请求。可用旧日全市场完整响应1次及一只长历史股正常页1次/小页约3次比较；小页只用于来源核验，不改变业务契约。现有样本计数仅作估计，出现差异停止说明，不自动扩大。固定HTTP组件接入后的真实交接另作最小确认，不将MCP结果冒充该交接已验收。 |
| 实现后日更读写/性能 | 重用同份获准真实响应，隔离做正常日更及同日补入各1次；分别记录正常/补入的两层读写、检查和最终对账成本。无历史正常日更与120秒目标比较；sensor单次评估与5秒目标比较。十个时点、60/600秒定义、去重、活动任务跳过使用模拟时钟/运行事实测试，不要求十次真实网络或十轮完整文件重写。 |
| 实现后历史读写/性能 | 一只股票、一个不超过20个交易日的临时样本批次，保留接近真实全市场宽度的日期文件，核无关股票不变；记录本批扫描/SQL/写入/峰值空间、失败后完整范围重新下载、当前正式合并及最后读回成本。结合可信日期/文件规模估算类似17股原完整历史，比较1200秒目标并明确外推局限；不默认跑17股完整历史，不把外推当成正式全范围已验收。批次1/20/21/41日等边界用小人工计划/临时数据，不为此扩真实历史范围。 |
| 实现后事件/恢复 | 同一套临时文件和独立临时instance，目标T加两个历史日期核物化/check关联；网络可替换，事件实际落入临时事件库。源未完整、源完整未发布、替换后未记完成、事件失败四个位置做有针对性恢复验证；至少一次真实进程退出后由新进程恢复，其他细分位置用有依据的隔离错误注入，不要求每点重复真实进程/来源跑数，不对真实源制造故障。验证完整源也重下、当前正式已提交保留、新源覆盖而旧候选绝不参与、repair原T缺失零网络及事件失败不回滚。 |
| 扩大范围的条件 | 小范围出现性能或语义差异，先说明具体问题及已有证据，提出额外最小验证范围；不自行扫描全湖、导出全历史或重复全量压测。正常、恢复、最终读回的成本分别记录，已有仍适用证据不反复重跑。 |

开工前明确范围、参数、成本及必要来源证据；业务完整发布/事件/恢复的运行验收在相应实现后隔离进行。不能要求尚未编码的完整链路现在已经运行通过，也不能因此省掉开工前设计/性能门禁。当前未执行本节任何来源、性能或Dagster验证，后续正式初始化及全范围验收仍须对应批准。

## 12. 已确认业务边界与工程核验

### 12.1 权威因子和源值

变化、原T/P修订及历史依据以`raw_tushare_adj_factor`为准；技术行同名值不同只诊断。Raw/Silver保持技术源业务值、不改成权威值、不缩放或重算。历史完成只证明按输入下载/检查/发布，不冒称所有源指标数学正确。权威因子缺必要值或范围不明时保留原因并停止对应历史，不当0变化。

### 12.2 Raw齐备是自动及手动历史共同前置

以原T当前正式合并Raw覆盖原T上市A股扣确认全天停牌的应有代码集合为准。全天停牌可无T行仍刷其d<T；盘中或非停牌缺行、停牌/生命周期未知都不能认齐。Raw文件check通过不等于覆盖全齐。自动日数据少股票仍正常发布，历史零请求；手动原T不齐直接失败提示管理员，不代办日更新或T窄查询。

Q日已齐仅历史失败可推进今天；原Q失败历史完整名单和范围保留，人工repair始终原T/原P，不以今天行或今天零变化抹掉旧意图。原范围内权威值修订可保存新依据，但不追加股票/延边界。历史失败重执行全新下载。

### 12.3 时间、Silver和重试范围

仅SSE开市日自动，19:00～23:30固定slot、午夜截止，前日实际业务一次；休市不新增机会。Silver本期261字段和对应行，仅日期DATE，每日期来自最终Raw，未来清洗不阻塞本期。Tushare失败/取消/退出后新下载，不删除正式数据。下载器当前运行内同页有限重试与Prod bootstrap独立恢复不变。

### 12.4 编码与验收仍须逐项核验

| 落点 | 必须核验 |
| --- | --- |
| 自动配置/原任务 | §2.4五字段日期关系、parent/root只取意图、错run源拒绝；任何失败阶段新run均实际新下载。 |
| Raw历史前置 | §5.2覆盖结果三态/原T文件/check/生命周期/停牌身份；自动等待、repair固定失败消息及零网络/零嵌套。 |
| repair四字段 | §4.1四项封闭配置、原完整授权、只d<T、缺日零网络、失败源再完整也重下。 |
| 发布与新执行 | §7～8只当前run新源/候选、当前正式B-K+U、逐文件intent/replace/fsync/readback、正式不回滚及缺原键诊断。 |
| sensor/事件 | §3的11条/原生tick有界读取、观察先持久后网络、失败阶段metadata；日物化后历史失败仍可读、历史check真实partition关联。 |
| 配置/性能 | §10单处常量和原资源；成本包括失败后全范围网络重取、当前正式文件合并/最终验收。bootstrap明确例外。 |

当前只改文档，尚未开发或运行验证；必须按§11.1精简方式在对应阶段补证据，不能以文档检查代替实现验收。正式运行和写入仍另须获准。

## 13. 最新决定对账

| 管理员决定 | 方案与LLD落点 |
| --- | --- |
| 原失败任务不论阶段均重新下载 | §2.4、§5.3～5.4、§7～8、§11；不复用失败run旧源/候选，不按页/股/日期断点。 |
| “丢弃数据”不删除正式文件/证据 | §5.3、§7～8；当前正式文件是新合并基础，名单/授权/失败记录保留。 |
| 原T Raw齐备后才历史 | §4、§5.2、§8、§9、§11；应有代码集合判断；自动日发布不设全齐门槛，历史按完整待处理范围执行。 |
| repair同门槛且缺日直接报错 | §4.1、§5.2、§11；原T缺/不齐/未知立即“原日期数据缺失”，无日下载/T窄查询/日发布调用。 |
| repair四必填 | §4.1；T/source_run/完整plan与ranges摘要；未知字段拒绝。 |
| 完整名单先于技术下载 | §1、§4～5；保留旧未完范围，T/P改回相同也不抹掉原意图。 |
| 日先历史后、两层逐日期更新 | §4、§8；先日Raw→Silver，再经齐备前置，历史逐d Raw→Silver，T不被历史写。 |
| 成功历史避免无故重复 | §5.4、§7；仅整范围成功、producer成功且输入有效，失败物理部分完成不冒充。 |
| 日期/前日一次/时点不变 | §1、§3、§6～7；19:00～23:30、午夜、只今天/Q、实际开始机会、不以人工重新执行复活自动次数。 |
| 20交易日/5000行及资源/精简验证不变 | §8、§10～11；20日只合并组织，bootstrap5000独立；60/600秒sensor，16GB/4线程等原资源及5/120/1200秒目标保留。 |

当前依据：CodeGraph核对原Raw停牌readiness及调用方，实读日线应有代码集合、现有发布intent、组件UnitResult及业务配置；通过Context7核对Dagster配置/Failure/check。只修改本数据集原方案和LLD，没有变更Prod、组件、其他数据集、前端/API或正式运行配置；真实来源、性能、事件与失败重执行验收均未执行。
