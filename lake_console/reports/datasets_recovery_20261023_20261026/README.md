# 2026-10-23数据集补齐分批方案

## 报告附件清理（2026-11-01）

管理员已明确要求删除无用过程材料。本目录由309个文件精简为9个，删除300个；只保留本文及下列最终审计/必要结果。过程附件、重复状态/配置、旧脚本、测试输出和逐文件清单已删除，不另打包保存。本文原章节及当时操作结论保留；已删除附件的链接转到本节，不能再据旧裸路径要求恢复文件或重新补数。此次没有读取行情或数据库、触发任务、更改sensor或删除正式Lake/staging记录。

- [final-reconciliation.json](final-reconciliation.json)
- [batch9/final.json](batch9/final.json)
- [batch10/final.json](batch10/final.json)
- [batch11/final-verified.json](batch11/final-verified.json)
- [operational-closeout-20261027/sensor-restoration-summary.json](operational-closeout-20261027/sensor-restoration-summary.json)
- [ths-recovery-20261030/execution-summary.json](ths-recovery-20261030/execution-summary.json)
- [ths-recovery-20261030/final-state.json](ths-recovery-20261030/final-state.json)
- [ths-recovery-20261030/2026-10-27-raw-verified.json](ths-recovery-20261030/2026-10-27-raw-verified.json)

全部五个目录的范围与执行规则见[原LLD20.16](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#2016-五个恢复报告目录的精简2026-11-01)。

截至保留的10月30日执行记录，23/26日THS Raw/Silver已成功，27日当时仍失败；下方10月27日状态为历史阶段，不能替代后续结果。本次清理不查询当前源或更新业务状态。

状态（2026-10-27，最新）：23日原112项仍完成110项，THS Raw/Silver两项未完成。12:44原三股空字段已补上；按管理员新授权先补23日再26日，23日Raw原job一次失败，报错样本换为另外三股源字段为空/采集值NaN，未发布正式数据，Silver及26日均未执行，见第45—46节。两股票sensor此前已恢复RUNNING；收尾和历史31个成功job/253条检查结论保留，不将本次失败当成功或自动重跑。

## 1. 目标与依据

补齐2026-10-23物理审计中的112项缺失，复用现成job和原检查。当前未发现必须新增开发的阻断，不安排新功能、性能测试或手工补数程序；这不表示尚未核验的23日来源、分区及前序状态已经就绪。

基线审计时间为2026-10-26 08:43:58北京时间：目录180项，审计159项，排除21项；47项有数据，112项缺失。其中94项文件不存在、14项年度文件没有23日记录、4项serving没有23日记录，无无法核实后端、读取错误或零行文件。原JSON完整保存在[物理基线（附件已清理）](README.md#报告附件清理2026-11-01)，本轮没有再次执行全局审计。

执行方式对齐[22日补齐记录](../datasets_recovery_20261022_20261024/README.md)，具体写入、检查和续跑方式沿用各数据集现行方案及LLD。完整资产清单、精确job顺序和依赖见[分批清单（附件已清理）](README.md#报告附件清理2026-11-01)。该文件覆盖112项且每项只出现一次；repair完成记录不重复算作新增缺失项。

本稿供确认分批顺序。正式执行前，在本文件追加当批执行卡：确认目标、配置、来源/前序依据、读写范围、预计开销（含中断继续和最后验收）、命令及验收条件；已有LLD直接复用。未取得具体历史读取批准前不执行相应年度/更早历史读取，22日的批准不自动扩大到23日。

## 2. 批次顺序

统一规则：先完成本批内上游job及原检查，再启动下游job；本批通过后推进下一批。表中的“前置”是业务依赖，串行序号也用于降低并发写入和排查成本，并不表示独立链互为依赖。

| 批次 | 目标 | 新补齐项 | 业务前置 | 累计完成 / 剩余 |
| --- | --- | ---: | --- | --- |
| 0 | 必要只读预检 | 0 | 本方案确认后 | 0 / 112 |
| 1 | 主要指数分钟完整链 | 39 | 23日专用分区、22日前序及有限历史可用 | 39 / 73 |
| 2 | 指数日线、九转及Prod发布 | 5 | Prod23日日线计数/注册代码覆盖、22日九转前序可用 | 44 / 68 |
| 3 | 普通指数分钟Raw/Silver/Gold | 19 | 批准的指数对象池及Prod23日五频覆盖 | 63 / 49 |
| 4 | 板块分类、成分、行情Raw/Silver | 6 | 23日新来源确认依据 | 69 / 43 |
| 5 | 板块指标Gold→本机CH→Prod CH | 3 | 批次4、必要Silver历史范围 | 72 / 40 |
| 6 | THS个股资金流及全球指数Silver | 3 | 各自来源、全球指数23日Raw及原检查 | 75 / 37 |
| 7 | 股票分钟Raw→Silver五频 | 10 | Prod覆盖23日的成功任务、五频/代码覆盖及Silver注册条件 | 85 / 27 |
| 8 | 市场成交额Gold及Prod发布 | 2 | 批次7与23日股票日线 | 87 / 25 |
| 9 | 股票七频前复权及因子repair | 7 | 批次7、22/23日因子和真实变化名单 | 94 / 18 |
| 10 | 股票七频MACD/KDJ及state，必要时repair | 14 | 批次9完成及22日state | 108 / 4 |
| 11 | 股票30/60/90/120分钟九转 | 4 | 批次9、22日seed和实际候选历史范围；执行顺序上待批次10通过 | 112 / 0 |

正常补齐job共31次，另运行一次因子repair job；若23日因子repair确实重写历史，再运行一次MACD repair job。即计划32次，条件满足时33次，不包含失败续跑或分区登记；不自动重跑。批次6的两个业务链独立，任一失败单独记录，不伪装成另一条链失败。

## 3. 各批具体job及条件

### 批次0：预检

不重新审计159项。不读全市场历史行情。仅核本批目标路径stat、所需动态分区、22日已有物化/原检查绑定、必要来源计数/覆盖、活动run及writer pool、挂载和空间。复用22日成功证据，不重跑同一套计算。

分区缺失只记录精确日期和注册条件，正式补齐授权后按原流程登记；不批量回建日期、不评价sensor。当前没有查询正式instance，因此不预填23日已注册或sensor当前状态。执行前核对本批相关代码与22日验证版本及当前在用版本，避免并行修改期间启动。

### 批次1：主要指数分钟39项

`raw_major_index_mins_update_job` → `silver_major_index_mins_update_job` → `gold_major_index_mins_update_job` → `gold_major_index_mins_nineturn_update_job` → `gold_major_index_mins_technical_daily_update_job`。

依次新增Raw 5、Silver 7、Gold 7、九转6、技术指标及state 14。Raw直接从Tushare `idx_mins`采集，不从Prod复制。90/120分钟由现行派生逻辑生成；技术指标及state由同一multi_asset成对生成，不拆开执行。

先复用22日95项原检查及其文件身份依据，确认前序没有变化。九转读取截至23日最多20份相关Gold历史，技术指标最长126个交易日窗口并使用22日前序；不是只读23日。只写23日39项。当前入口没有新增必需run config。

代码依据：`jobs/major_index_mins.py`、`major_index_mins_gold.py`、`major_index_nineturn_update.py`、`gold_major_index_mins_technical_daily_update.py`；`assets/major_index_mins_raw.py`；`major_index_nineturn.py`；`io/major_index_mins_technical_writer.py`。

### 批次2：指数日线5项

`raw_index_daily_update_job` → `silver_index_daily_update_job` → `market_major_indices_daily_update_job` → `gold_major_index_daily_nineturn_update_job` → `prod_core_index_daily_nineturn_sync_job`。

Raw从Prod `core_serving.index_daily_serving`读取23日，按当前注册指数集合验覆盖，不照抄22日代码数。先验收Lake四项再发布Prod一项；Prod九转实际来源是主要指数日线九转。九转需要有限历史及22日前序。只补23日，不重写其他日线日期。

代码依据：`assets/index_daily.py`、`assets/index_daily_nineturn_prod_core.py`、`assets/major_index_nineturn.py`及同名job。

### 批次3：普通指数分钟19项

`raw_index_mins_update_job` → `silver_index_mins_update_job` → `gold_index_mins_update_job`。

新增Raw 5、Silver 7、Gold 7。Raw从Prod当前已批准active_pool取数，先核23日五频计数/覆盖及`silver_index_basic`；不把主要指数的10个对象或50次Tushare请求预算套过来。沿用22日已验证的候选、逐文件提升及原检查，不新增入口。

代码依据：`assets/index_mins_raw.py`、`assets/index_mins_silver.py`、`assets/index_mins_gold.py`及对应job。

### 批次4：板块Raw/Silver六项

`raw_tushare_dc_index_update_job` → `silver_dc_index_update_job` → `raw_tushare_dc_member_update_job` → `silver_dc_member_update_job` → `raw_tushare_dc_daily_update_job` → `silver_dc_daily_update_job`。

通过现行来源流程取得23日新`source_proof`，不复制22日proof。板块Raw仍从Tushare采集，Prod提供完成参照。member和daily依赖同日Raw index；各Silver依赖对应Raw，不强制三者代码集合相等。

手动原job允许`recovery_identity=None`，不伪造自动重试身份。过去日且来源与Prod内容相符、分类与行情无缺口时可一次确认；有差集或内容差异才按原流程两次观察，间隔至少300秒。只在差集非空时按真实代码限定历史覆盖查询，不默认扫历史。

代码依据：`assets/dc_board_raw.py`、`assets/dc_board_silver.py`、`assets/dc_board.py`、`run_contracts/configs.py`、`asset_guards/dc_board_source_freeze.py`、`asset_guards/dc_board_run_recovery.py`。

### 批次5：板块指标及两处CH发布三项

`gold_dc_daily_technical_update_job` → `ch_dc_daily_technical_update_job` → `prod_ch_dc_daily_technical_sync_job`。

每一步原检查通过才继续。Gold原writer需要2024-01-02至23日Silver行情，不是只读当天。以22日677文件/37,590,608B证据为基础，只补stat确认23日新增文件及实际范围；确认这段历史读取后正常运行一次。两处CH分别使用各自resource，不跳过本机直接发布Prod。

代码依据：`assets/dc_daily_technical.py`、`jobs/dc_daily_technical_serving.py`及Prod同步job；现成证据见[22日板块汇总（附件已清理）](../datasets_recovery_20261022_20261024/README.md#报告附件清理2026-11-01)。

### 批次6：两条独立小链三项

资金流：`raw_tushare_moneyflow_ths_update_job` → `silver_moneyflow_ths_update_job`，补两项。Raw自己执行两轮源采集，间隔60秒；还会读取最近五个已物化Raw日期的小文件作合同、计数和SHA基线，预算包含这些输入，不新做年度审计。原上限为每轮2万行；两轮共用64请求及Raw采集/提交前300秒原预算，沿用现行配置，不新增限制。

全球指数：`silver_index_global_update_job`补一项，复用已存在的23日Raw。使用现有`build_index_global_silver_run_config(trade_date="2026-10-23", attempt=0)`；不重拉Raw，也不改其源日期语义。

代码依据：`assets/moneyflow_ths.py`、`asset_guards/moneyflow_row_count.py`、`run_contracts/moneyflow.py`；`assets/index_global_silver.py`、`run_contracts/index_global.py`。

### 批次7：股票分钟Raw/Silver十项

`stock_mins_raw_update_from_prod_job` → `stock_mins_silver_update_job`。

先核覆盖23日的Prod成功任务及五频/预期代码覆盖，用同一份`prod_completion_reference`传入Raw五资产，`source=prod_db`；覆盖23日的区间任务可由已修正的日期识别处理，不能只看任务status。Silver前还要核日线、最终停牌Silver、身份映射和专用动态分区条件。

只补23日五频Raw和五频Silver。Raw及Silver逐项原检查通过后，再推进成交额、QFQ。基线中的股票日线有数据只能作为粗筛，不能代替执行前读取现有原检查状态。

代码依据：`jobs/stock_mins_raw_update.py`、`stock_mins_silver_update.py`，`asset_guards/stk_mins_prod_readiness.py`，`sensors/stock_mins_silver_trade_day_sensor.py`及现行分钟合同。

### 批次8：成交额两项

仅一次`gold_wealth_market_turnover_update_job`，内部选中Gold及Prod两个资产，先Gold及blocking check，再Prod。

依赖批次7五频Silver及同日`silver_stock_daily`，不必等待QFQ/MACD/九转。只读同日数据并生成市场汇总；原writer包含多次同日聚合，不能预算成只读一遍。不得另找一个不存在的Prod成交额独立job。

代码依据：`jobs/gold_wealth_market_turnover_update.py`、`assets/wealth_market_turnover.py`、`assets/wealth_market_turnover_prod_core.py`。

### 批次9：七频前复权及因子repair

先`stock_mins_qfq_daily_update_job`补七项并通过原28项检查，再`stock_mins_qfq_factor_repair_job`完成七频repair记录。

日更合并2026年度文件、保留其他日期；只保留现行一次候选摘要校验，不添加重复年度审计。factor job配置目标日23日，真实名单来自22/23日因子及当前Basic：无因子变化也要完成job及七频完成记录，此时不重写历史；存在真实变化才按实际名单执行历史repair；前因子缺失必须停止。

不能复用22日固定26股名单，也不能把新增代码直接当成历史因子变化。先取得真实名单，再stat必要历史来源/目标，明确历史日期、读写与续跑开销并批准后执行相应历史读取；不先跑大范围再补预算。

factor job还要求2014起至23日的expected dates登记完整。复用22日已经验证的历史注册依据，只增量核23日及必要身份，不为此重扫历史行情。

代码依据：`jobs/stock_mins_qfq_daily_update.py`、`stock_mins_qfq_factor_repair.py`，`stk_mins_qfq.py`的`build_gold_stk_mins_qfq_factor_repair_plan`，`ops/stock_mins_qfq_factor_repair.py`及原LLD。

### 批次10：MACD/KDJ十四项及条件repair

先`gold_stk_mins_qfq_macd_kdj_daily_update_job`补七频指标和七频23日state；读取22日state，合并年度指标，保留其他股票/日期。

只有23日因子repair实际重写历史时，再`gold_stk_mins_qfq_macd_kdj_repair_job`。它要求23日指标及state已经存在，所以不能排在日更前。参数中的代码、历史起止、代码hash、上游批次身份取自23日factor metadata，完整七频；不能照抄22日26股或2014—2026的旧配置。不需要历史repair时跳过该job，不伪造记录。

日更和repair分别核预算；特别是repair合并共享state时保留其他股票，不能只计算26股大小却漏掉共享state的读写。沿现行job/续跑能力，不使用手写计算、额外进程中断器或新资源上限。

现行MACD repair从metadata自动推导名单的上限为500只；若超过自动推导上限、名单截断或metadata不全，停止核清具体范围，不改成全市场repair。这是现有参数检查，不新增运行限制。

代码依据：`jobs/gold_stk_mins_qfq_macd_kdj_daily_update.py`、`gold_stk_mins_qfq_macd_kdj_repair.py`，`asset_guards/stk_mins_qfq_macd_kdj.py`、`ops/gold_stk_mins_qfq_macd_kdj_repair.py`及原LLD。

### 批次11：股票分钟九转四项

一次`gold_stk_mins_qfq_nineturn_update_job`补30/60/90/120分钟，四条原检查通过。

前序注册日必须得到22日。复用22日刚通过的seed、check和receipt，不重复104项旧种子历史审计。只有23日factor repair改变历史且已有实现/receipt不能证明比较关系不变时，才对23日实际变化股票限定核验22日seed。

原planner先读正常2025/2026来源键，再得到真实候选及其更早历史。候选范围按23日重新限定，不照抄`002388.SZ`或44文件。补齐具体历史范围和批准后再正常运行一次；只写23日四文件，保留恢复依据。

代码依据：`jobs/stk_mins_qfq_nineturn_update.py`、`assets/qfq_nineturn.py`、`qfq_nineturn.py`及[原LLD第22节](../../docs/design/dagster-stock-qfq-nineturn-dataset-low-level-design.md#22-2026-10-22分钟九转写入修正与补齐lld)。

## 4. 成本、失败和续跑

以下是22日已有证据的量级参考，不是23日实测或已获批范围；不为了重新估时做性能样本。正式前优先stat与复用证据，准确范围不能确定时不启动大读取。

| 步骤 | 22日已有证据 | 23日正式前补充 |
| --- | --- | --- |
| 主要指数39项 | 原生job合计34.987秒；含装载/串行验收275.469秒，940,069B输出；原方案输出/候选预算64MiB | 对象数、有限历史stat、正常请求数、22日前序；含原checks和一次收尾 |
| 板块指标三项 | 原范围677文件、约35.85MiB；预算读256MiB/写32MiB/额外64MiB | 加23日后的真实范围及一次检查/验收，失败现场和继续所需空间 |
| 股票Raw/Silver | 原生job约91.58秒/16.08秒 | 23日代码数、五频行数、来源/候选大小及空间 |
| QFQ日更 | 38,990份年度文件；含预留估读31.255GiB/写8.068GiB，耗时914.629秒 | 23日七频实际来源和2026目标stat，正常/中断继续/最后验收分别估算 |
| 因子repair | 22日26股执行112.51秒；旧读52GiB/写3GiB预算不沿用 | 23日真实变化名单、历史来源和年度目标stat；无变化不重写历史 |
| MACD日更/repair | 22日恢复593.29秒、旧26股repair384.61秒 | 分开核日更两年来源/2026目标与真实变化代码历史/shared state范围，不套272GiB旧批准 |
| 股票九转 | 原job68.84秒，四文件233,592B | 22日seed身份、23日真实候选历史；旧16/3/3GiB只是参考，不自动批准 |

其他单日链沿现行投影、过滤、请求限制和逐文件写入。预算包含原checks、唯一收尾以及中断后继续的开销；没有新设硬中断阈值。正式目录只用`/Volumes/datasource/data_lake/{raw,silver,gold}`，候选只用`/Volumes/datasource/data_lake_staging`；不引入备份或Kopia。

job自然失败时停止该批和依赖它的后续步骤，保留已正式提升的文件及staging、checkpoint、receipt，不自动回滚、删工作文件或重跑整批。先用本run记录及stat定位未完成单元，再依原LLD限定同范围续跑成本和方式；失败续跑不包含在“正常32/33次”中。不擅自重跑已经验收成功的文件或改代码绕过检查。

## 5. 验收与sensor待办

每个job结束只核本run、目标23日物化、原checks与其物化绑定、receipt/文件身份和必要单日计数；serving按23日目标表计数/合同核对。不能只看job绿色或文件存在，也不额外重算已经由原checks验证的公式。

每批记录run id、时间、实际读写证据、结果、剩余项、失败/续跑以及临时目录情况；没有测得的设备I/O不写成实测。最后按本清单112项及逐批验收记录核销，不重跑159项全局审计，47项原有资产不为凑齐清单而重复执行。

原sensor恢复TODO已于2026-10-27按管理员追加授权完成，状态均RUNNING，见第43—44节；23日股票链及repair已验收，THS两项独立未完成。以下两项为本次恢复范围，原review阶段不启用的约束保留为历史，不再作为当前开关状态：

- `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`
- `gold_stk_mins_qfq_nineturn_update_job_sensor`

本轮依据：当前job及资产源码、CodeGraph上下文分析、22日逐批正式成功证据。Dagster官方[AssetSelection文档](https://dagster.io/docs/api/dagster/assets)经Context7核对：选择资产同时包含其关联checks；本方案仍逐一核对当前job的真实selection，不假定选下游就会重跑所有上游。当前无代码/配置/契约变更，因此不新增单元测试，只验证文档、链接和112项分配完整性。

## 6. 第一批正式执行卡与LLD补充（2026-10-26）

管理员授权：“先执行第一批吧。按前后顺序，依次通过job补数。非必要，不做额外的数据审计。”本轮仅2026-10-23主要指数分钟39项；完成即停，不推进批次2，不写Prod，不启停sensor/daemon，不改业务代码或资源配置，不做性能样本和全局审计。

### 6.1 实现与操作范围

复用22日已成功的五个job及95项原检查，当前job/资产/writer与分区合同按第3节所列代码核验。技术指标/state仍由multi_asset成对生成。原writer行为沿22日执行说明：Gold和成对指标会拒绝已有目标；九转可能替换已有目标，因此首次及每个job前必须只stat确认本步目标全部不存在。出现目标或并发运行即停，不能盲目覆盖。

复用22日`execution-readback.py.txt`作为只读核验入口，只做本步必要适配：日期23、前序22、当前报告目录、真实run id、本日有限输入清单。删除最终count/schema/SHA读取；行数取本次物化metadata，正确性依原blocking checks，不照抄22日13,790行硬编码。脚本只查询已有Postgres storage并保存报告，`should_autocreate_tables=False`和只读事务选项，不创建instance，不承担任务启动或业务写入。

执行前只读：确认23日专用分区已注册、五job无活动run、daemon无并发运行、目标39路径缺失、Lake/staging同设备且可用；复用22日20项必要前序的原检查/物化绑定，仅核当前最新物化id及文件stat仍一致。有限技术指标日期用现行selector从交易日期依据选取，最长126个交易日；九转按截至23日末20份Gold路径规则列出。只读必要日期信息和stat，不读取历史行情正文、不调用会读正文的九转planner。目标23日Gold路径先标记待生成，后续由Gold job补上。

### 6.2 读写及成本

范围固定为当前名单10个指数、1日、5个Raw频率，正常50次源请求，沿原分页/请求策略；不另做50个源端样本。九转六频各最多20个日期，技术指标七频最长126个交易日及22日前序；正式计算和原checks允许在这一有限集合内按现行实现多次读取，不扩大为全历史。具体路径数/大小保存预检JSON，优先复用22日已明确的日期范围再增量核23日。

预估正常执行含原checks、日志和最终stat：读取128MiB、写入及临时预留64MiB、额外空间64MiB，正常墙钟3～8分钟，依据22日同链275秒、约0.90MiB正式输出及少量有限历史。此为量级估计而非设备I/O实测或新增运行上限；10分钟仅人工查看进度，不发送中断信号、不改变16GB/4线程等原资源配置。最后验收不读行情正文和新SHA，只读本次有界事件/metadata/stat。中断后同范围剩余步骤按不超过一轮128MiB读/64MiB写另计保守预留；不自动续跑，先依实际已发布文件限定尚未完成范围及操作方式，必要时补充本节。

正式写入只限23日39目标和其原Dagster物化/check记录，候选按现有writer进入`data_lake_staging`；22日和邻日目标及有限历史输入只读。原实现可能在异常时自行清理候选，本轮不额外清理、备份、回滚正式结果或使用Kopia。

### 6.3 完整命令与顺序

工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，正式`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`。使用项目已有`.venv/bin/dg`，已核本机`launch --help`；不安装依赖、不经uv同步。显式加载现行`orchestrator.definitions`，与22日后续已成功任务相同。下面每条独立执行，只有前条及其原检查通过才启动下一条，不放入无条件连续脚本：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job raw_major_index_mins_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job silver_major_index_mins_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_major_index_mins_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_major_index_mins_nineturn_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_major_index_mins_technical_daily_update_job --partition 2026-10-23
```

### 6.4 通过、停止与继续规则

每个job记录真实run id、完整原日志、状态和耗时，限定最多500条本run事件。核输出集合依次5/7/7/6/14，目标分区23日、uri和文件stat相符，所有要求的原blocking checks通过并绑定本次物化。技术指标以metadata的`goldenshare/source_trade_dates`及`goldenshare/previous_expected_trade_date`与预检范围核对；九转原metadata只有`goldenshare/source_file_count`，该数量包含20份Gold及一份22日九转seed，共21份，以该数量、现行路径选择规则和输入stat对账，不假称它返回完整日期清单，不另跑同一套计算。

本机原CLI可能成功退出但不输出stdout/stderr。若CLI未返回run id，只读查询该job、23日、启动记录时间之后唯一新增的run（最多3条候选），确认唯一后取其精确run id验收并归档原instance事件日志；不能把空日志当成未执行而重跑，也不能不加时间条件猜最新run。出现多个候选或没有run则停止核清。

job或检查失败即停止后续步骤。Raw/Silver可否复用已成功目标以当前writer为准；Gold拒绝已有目标、九转可能替换、技术指标/state分别提升且可能只完成其中一个，因此禁止整job无条件重跑。本轮授权不含失败后的额外覆盖/删除；先保留事实并报告、补充具体续跑范围和预算。

最后仅汇总五run及95项要求检查、39文件stat，核有限历史与22/24日范围外路径身份不变，不读回count/schema/SHA、不重复159项全局审计。按112项基线销账39项，余73项；不据此宣布其他批次通过。操作和结果保存`batch1-major-index/`，纯只读辅助脚本归档为文本，临时执行脚本完成后移除，不动业务staging。

执行中只读核验问题：九转run已SUCCESS且6条原检查通过后，辅助脚本误用未加`goldenshare/`的字段名，并把来源数量当成只含Gold的20份，导致附加断言失败。当前producer的`build_materialization_metadata`会加命名空间，九转writer把seed也计入来源；22日已有metadata同样为21份。纠正本节及只读核验脚本后仅重新读取本run事件/stat，不重跑job、不改业务代码或正式数据。该错误也同步纠正了尚未执行的技术指标核验字段；原错误版本和说明保留在报告中。

## 7. 第一批执行结果：39项全部完成

完成时间：2026-10-26 09:17:03北京时间。严格按Raw→Silver→Gold→九转→技术指标/state执行，每个job原检查通过后才启动下一步，五个job均只执行一次：

| job | run id | 新补齐项 | 原检查 | 本次物化行数 |
| --- | --- | ---: | ---: | ---: |
| `raw_major_index_mins_update_job` | `b0fe2063-2b48-4a0b-b388-91ed528d9eda` | 5 | 5通过 | 3,210 |
| `silver_major_index_mins_update_job` | `48432f74-1ca6-4203-b922-f274a6d95067` | 7 | 7通过 | 3,260 |
| `gold_major_index_mins_update_job` | `f35f0dcc-df9c-4657-8f4d-73fef388238a` | 7 | 7通过 | 3,220 |
| `gold_major_index_mins_nineturn_update_job` | `05ddccee-8d09-4654-a21c-e16cfa636953` | 6 | 6通过 | 810 |
| `gold_major_index_mins_technical_daily_update_job` | `7023c623-0eea-48f4-8234-c06f6f72d0b9` | 14 | 70通过 | 3,290 |
| 合计 | 五run SUCCESS | **39** | **95通过** | **13,790** |

39个正式文件共944,931B。技术指标七频与state七频成对完成，真实来源日期匹配预检有限窗口，前序为22日。Raw原metadata记录50次正式源请求、0重试，无额外收盘样本请求。

预检只stat了有限历史与日历344个文件、1,997,636B，并复用20个22日前序检查/物化依据；日历仅查询2026年截至23日的SSE开市日期。五个run的原检查均绑定本次相应物化。最后只核39目标、22/24日78个范围外路径及有限输入stat，均未变化；没有再读行情正文、重算公式、做新SHA或重跑全局审计。95项原检查没有重执行。

原生job时间合计38.319秒；从预检完成至最终对账约599秒，含CLI装载、工具调用、串行核验和一次辅助核验纠正，高于原3～8分钟参考，不混写成原生计算耗时。没有增加资源限制或中断job。四份CLI日志为空，九转CLI有完成消息；各run完整原instance事件另已归档，最多415条，均未截断。Raw空日志时先确认实际run成功后继续，未重复提交。

第6节所记辅助metadata断言错误已纠正，仅重新读取同一个九转run的事件/stat，没有影响业务计算或正式文件。正式job失败0、重跑0。当前五个相关job无活动run，daemon未运行；未操作sensor、分区或服务，未写Prod。临时只读执行脚本已归档为文本并移除，业务staging及正式数据删除0。

按原112项缺失清单已销账39项，**剩余73项**；这是逐批验收销账，不是新的全局审计。本轮到此停止，批次2—11仍未执行，23日全部补齐后再启用两sensor的TODO保留。

证据：[执行汇总（附件已清理）](README.md#报告附件清理2026-11-01)、[最终stat及检查对账（附件已清理）](README.md#报告附件清理2026-11-01)、[必要预检（附件已清理）](README.md#报告附件清理2026-11-01)、[辅助核验纠正记录（附件已清理）](README.md#报告附件清理2026-11-01)。每个job的`*-verified.json`、`*-native-events.json`和原CLI日志保存在同目录。

## 8. 第二、第三批执行卡与LLD补充（2026-10-26）

管理员授权：“继续执行第二和第三批吧。按前后顺序，依次通过job补数。非必要，不做额外的数据审计。完成后向我汇报进展。”本轮范围仅2026-10-23第二批5项、第三批19项，共24项。第二批全通过后才进入第三批，完成后停止；不启动批次4—11，不改代码/配置/契约，不做性能样本、不安装依赖、不调整sensor/daemon，不重复全局审计。

### 8.1 现行实现、必需参数及写入边界

第二批使用原5个job：`raw_index_daily_update_job` → `silver_index_daily_update_job` → `market_major_indices_daily_update_job` → `gold_major_index_daily_nineturn_update_job` → `prod_core_index_daily_nineturn_sync_job`。各补1项，原检查数依次2/4/4/1/1，共12。Raw配置可由现行keyword-only函数`build_raw_index_daily_update_job_run_config(partition_key="2026-10-23")`生成，仅设置现行默认`write_mode=replace`，不新增配置；其余job无额外必需config。

Raw/Silver/主要指数Gold复用`io/index_daily_writer.py`的staging及publication/receipt；日线九转复用原有限历史writer。Prod发布实际读取同日九转Gold和主要指数日线Gold，目标仅`core_serving.index_nineturn_daily`的23日，原事务删除当日→插入→完整业务hash读回，异常rollback。该Prod写属于本次第二批授权；不改其它日期、其它表、角色或schema。原Prod blocking check再次核同日内容，末尾不另做全量hash比对。

第三批使用原3个job：`raw_index_mins_update_job` → `silver_index_mins_update_job` → `gold_index_mins_update_job`，补5/7/7项及原5/7/7条检查，共19。无必需run config。Raw每频从当前批准的Prod对象池导出本日，明细固定为`raw_tushare.index_mins`、五频、`[2026-10-23 00:00,2026-10-24 00:00)`、当前池代码、现行11业务列，不读取年度或其它日期。90/120分钟由Silver现行派生逻辑生成。

分钟Raw/Silver继续使用现行`MinutePartitionPublication`，receipt和候选只支持对应原root身份，不将新launch冒充续跑；Gold仍拒绝已有目标。Lake目标、staging和DuckDB资源保持原配置，不引入新运行上限或中断器。

代码依据：`assets/index_daily.py`、`io/index_daily_writer.py`、`assets/market_major_indices.py`、`assets/major_index_nineturn.py`、`assets/index_daily_nineturn_prod_core.py`、`prod_db/index_daily_nineturn.py`；`assets/index_mins_raw.py`、`assets/index_mins.py`、`assets/index_mins_silver.py`、`assets/index_mins_gold.py`、`prod_db/index_mins.py`及各job。相关方案/LLD和22日真实成功证据直接复用，不重新开发。

### 8.2 必要预检与只读范围

只读脚本复用第一批已纠正的事件/metadata/stat核验方式及22日两批预检，不承担业务计算、写湖或启动job。正式storage指定现有DAGSTER_HOME、`should_autocreate_tables=False`、只读事务，不创建instance。

第二批：核`cn_a_index_trade_days`已登记23日且前序为22日，取得当前`cn_a_index_ts_codes`注册集合。通过已批准`ProdPostgresResource.connect_readonly_transaction()`对`core_serving.index_daily_serving`仅23日及该集合做一次计数/代码覆盖聚合；缺失时仅取最多5个缺码。源行数、返回代码数和注册数相等，重复/缺码为0才推进，不照抄820。Gold主要指数名单由本日`active_major_indices_seed_rows`确定，当前纯合同为11，不把分钟前10个代码套给日线。

Prod目标预检仅用`ProdPostgresWriteResource.connect_readonly()`查询23日`count(*)`，不使用没有该表权限的普通source账号；首次及发布前确认仍无目标记录。九转只枚举截至23日最近20份Gold路径，其中23日标为待生成，并复用22日九转文件stat及已有检查/物化绑定。前序未变则不重算22日。必要历史只有19份既有Gold与一份seed，不调用会读正文的planner。

第三批进入前再核`cn_a_index_mins_trade_days`23日分区、`silver_index_basic`文件stat、当前Prod池。调用现成`load_prod_index_mins_active_pool`读取`ops.index_series_active(resource='index_mins')`的代码列表，再用`probe_prod_index_mins_source_dates(trade_dates=["2026-10-23"], effective_codes=pool.codes)`一次五频聚合；只返回计数、代码数、不同主键数、时间范围及ready，不拉行情样本，不重复五条probe。原job执行中仍会按现行实现自行读池和导出；核本次Raw的`goldenshare/active_pool_hash`与预检一致。

两批预检均确认本批job无活动run、daemon无并发运行、对应目标缺失、挂载/权限/同设备/空间可用，仅stat22/24日邻日及必要输入。每个job前再确认其目标仍不存在。只执行`LOAD postgres`验证现有DuckDB扩展，不执行INSTALL；当前Raw的LOAD失败有INSTALL回退，因此预检LOAD失败必须停止，不启动job触发回退。项目`.venv`和CLI指向同一现有环境，不修环境或下载组件。

### 8.3 数量、开销、失败与继续

日线来源按本次注册集合及聚合结果冻结，九转现有输入参考22日约51KiB、含新目标保守按256KiB。正常含原checks/日志/收尾估读64MiB、写及记录72MiB、额外空间72MiB；依据22日四步64MiB候选/日志预算加Prod8MiB记录。若中断后同范围剩余步骤必须继续，另按最多同一轮64MiB读/72MiB写预留，再依实际receipt/未完成项缩小；不自动续跑。

分钟参考22日当前池530代码、五频170,130行、19文件22,207,465B，Raw/Silver/Gold原生耗时114.844/2.895/2.930秒；不是23日已确认数量。本次聚合后保存实际池/行数及范围，再核预算。正常五次单日导出及原checks/收尾保守估读512MiB、写及候选/记录256MiB、额外空间256MiB；失败继续另按最多一轮同额预留，按未完成单元实际限定。没有年度/全历史行情读取。以上是量级预估、不是设备I/O或新硬限，3～10分钟仅参考，不据此强杀job。

任何job或原检查失败即停止本批和后续批次，保留已提升正式结果与原staging/receipt。Raw/Silver/日线Gold需核原publication身份及已完成单元后再定继续方式；分钟Gold拒绝已有目标、九转会替换目标，均不得盲目整job重放。Prod事件失败不能当成事务未提交，先限定到同日记录及原事务依据核清；本轮不自动重发、清理、回滚成功结果或补runless绿事件。

### 8.4 执行命令与验收

工作目录和正式DAGSTER_HOME同第6节，使用现有`.venv/bin/dg`，不经uv同步。各命令独立执行并存原日志；前一步及原检查通过才执行下一步。默认配置已覆盖本次参数，不额外传入手工配置：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job raw_index_daily_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job silver_index_daily_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job market_major_indices_daily_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_major_index_daily_nineturn_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job prod_core_index_daily_nineturn_sync_job --partition 2026-10-23
# 第二批五步全部验收后，才执行下面三步。
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job raw_index_mins_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job silver_index_mins_update_job --partition 2026-10-23
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_index_mins_update_job --partition 2026-10-23
```

按各次启动时间唯一确定run或使用精确run id，原日志和事件归档。每个run最多500条物化/check/失败事件，核SUCCESS、精确目标集合、23日分区、metadata行数和catalog路径对应文件stat，以及每项原check绑定本次物化。仅对现行producer承诺发布URI的资产核对URI；`silver_index_daily`及`gold_market_major_indices_daily`的现行合同不发布URI，按catalog路径、原检查与实际stat验收，不额外要求补字段。额外metadata只按当前producer已有字段使用`goldenshare/`命名，不自行猜别名：Prod验`goldenshare/read_back_row_count`及原内容检查，分钟Raw验`goldenshare/active_pool_hash`。不增加无必要的附加业务断言。

每批最后仅汇总已成功run、原checks和目标/必要输入/邻日stat，不重新读count/schema/SHA或重算公式；Prod由原事务及原blocking check验证内容，不额外整表读回。记录到`batch2-3-index/`；临时只读脚本完成后归档移除，业务staging不清理。第二批预期新增5项/12checks后剩68项，第三批新增19项/19checks后剩49项，累计恢复63/112；不能在实际通过前预填完成。

### 8.5 第二批必要预检已通过

2026-10-26 09:29:54，只执行本批只读预检：23日注册指数820个，Prod当天820行/820代码、重复0、缺失0；主要指数日线本日合同11个。Prod九转目标23日0行。日线分区已注册且前序22日，22日九转文件与原物化/检查身份保持；19份既有Gold及seed共51,242B。四个Lake目标缺失、五job无活动run，现有postgres扩展LOAD通过，没有安装；两根目录同设备且空间满足本批预估。未执行源端明细抽样、历史行情读取或全局审计。证据：[第二批预检（附件已清理）](README.md#报告附件清理2026-11-01)。本批预算保持第8.3节，待各job逐步完成后登记正式结果。

本批辅助核验纠正：Silver原job已SUCCESS后，复用脚本把第一批通用URI断言错误套到日线Silver，读到不存在的`dagster/uri`而停止。当前Silver producer及22日成功证据均只发布标准行数，不承诺URI；日线Gold也相同。核清全部八个job现行metadata后，仅取消这两个资产不适用的URI要求，保留catalog路径/stat和全部原检查绑定。纠正后只重新查询原Silver run验收，不重跑job、不读行情正文、不改业务代码或文件。原错误版本与说明保存在本批报告中。

### 8.6 第三批必要预检已通过

第二批五步全部验收后才执行第三批预检。当前Prod池530个代码；一次五频聚合确认23日每频均覆盖530代码、主键无重复，Raw来源行数分别127,730/25,970/9,010/4,770/2,650，共170,130行。时间范围均为23日09:30—15:00，probe仅1个聚合SQL/1个连接，未导出明细。当前池hash已保存供原Raw物化metadata对账。

19个目标均不存在，23日专用分钟分区已注册，Basic文件存在，原postgres扩展LOAD成功，无相关活动run。行数与22日既有量级相同，继续采用第8.3节读512MiB/写及记录256MiB/额外空间256MiB估计，不做性能样本、年度读取或额外价格审计。证据：[第三批预检（附件已清理）](README.md#报告附件清理2026-11-01)。

## 9. 第二批完成：指数日线及Prod九转五项

2026-10-26 09:39:43完成逐步验收。五个原job各运行一次，5项物化、12条原检查及绑定通过：

| job | run id | 行数 | 原检查 |
| --- | --- | ---: | ---: |
| `raw_index_daily_update_job` | `f0f08606-26e3-440d-9ec5-5b439b34adae` | 820 | 2通过 |
| `silver_index_daily_update_job` | `6ca3bf56-8c1e-4eda-aaed-51a78fbf669b` | 820 | 4通过 |
| `market_major_indices_daily_update_job` | `dbd35fc9-49e9-4939-af01-219e2566676d` | 11 | 4通过 |
| `gold_major_index_daily_nineturn_update_job` | `2020720f-7080-4833-8535-cfc2c25a42bc` | 11 | 1通过 |
| `prod_core_index_daily_nineturn_sync_job` | `98bcf93f-c925-40d2-b090-f14e0f9ccd00` | 11 | 1通过 |

四个Lake文件共129,445B；Prod仅发布23日`core_serving.index_nineturn_daily`11行，事务读回与原内容检查通过。22/24日Lake路径和有限历史输入stat保持，末尾没有额外读正文、做SHA或全局审计；没有重跑正式job。辅助URI核验纠正详见第8.5节，不影响正式结果。原112项清单累计恢复44项、剩68项；第三批通过前不预填其19项。证据：[第二批精确验收（附件已清理）](README.md#报告附件清理2026-11-01)。

## 10. 第三批完成及本轮收尾

2026-10-26 09:47:14完成第三批。严格待第二批五步验收后，再按普通指数Raw→Silver→Gold推进，三个job各运行一次，19项物化、19条原检查及绑定通过：

| job | run id | 资产数 | 本次物化行数合计 | 原检查 |
| --- | --- | ---: | ---: | ---: |
| `raw_index_mins_update_job` | `b22393ec-b4f0-4ba8-8778-8b1d343e9e40` | 5 | 170,130 | 5通过 |
| `silver_index_mins_update_job` | `0ccbe74d-8898-4d23-bb4a-6368f9da64dc` | 7 | 172,780 | 7通过 |
| `gold_index_mins_update_job` | `35cfaa61-5fce-4f94-a478-0736b8c6520d` | 7 | 170,660 | 7通过 |

19个文件共22,332,810B。Raw五频使用同一本次530代码对象池，物化中的pool hash与预检一致；Silver增加90/120分钟派生，Gold按现行标准K线时段合同处理，因此三层合计行数合法不同，不要求机械相等。原生job分别耗时85.433/3.126/3.319秒，不含CLI装载与验收时间。

本轮第二、第三批共补齐24项（23份Lake文件及1项Prod serving），31条原检查通过，8个原job均SUCCESS、正式失败0、重跑0。含第二批在内原生job合计约121.977秒；从本轮预检至最终验收约1,041秒，含CLI装载、工具调用、逐步核验、文档记录及一次辅助URI核验纠正，不混写成计算耗时。日线来源仅一次计数覆盖，分钟来源仅一次五频聚合；没有行情明细样本、性能样本、年度/全历史读取或全局审计。正常补数和原检查之外，未额外读输出正文、count/schema/SHA或重算公式。Raw运行中仅有一次五目标stat用于查看进度。

22/24日邻日和必要历史/Basic输入stat未变。Prod改动仅第二批授权的23日日线九转11行，原事务读回及内容检查通过；没有其它Prod写入。五加三个相关job最终均无活动run，daemon保持未运行；没有调整sensor、分区、资源配置或安装依赖。辅助URI误判只影响只读收尾，已按真实合同纠正，不影响正式补数结果。

临时只读执行脚本已归档为文本并移除；原日志、原事件、逐job验收及纠正依据保留，正式数据和业务staging删除0。原112项清单累计已恢复**63项、剩49项**，第四批及以后未执行。本轮到此停止，两sensor仍按TODO待23日全部补齐后再处理。

证据：[本轮汇总（附件已清理）](README.md#报告附件清理2026-11-01)、[第三批精确验收（附件已清理）](README.md#报告附件清理2026-11-01)、[第二批精确验收（附件已清理）](README.md#报告附件清理2026-11-01)、[只读核验纠正（附件已清理）](README.md#报告附件清理2026-11-01)。各job原CLI日志、完整原instance事件及物化/check绑定记录均在同目录，无截断。

## 11. 已确认的repair顺序与完成条件

管理员review通过后要求将以下口径落入方案，并继续剩余批次。所有本轮更新的复权数据都必须完成对应的repair处理及验收；当天更新job成功不能代替历史修复完成。仅使用现成job，按当前代码真实能力执行，不依赖sensor自动接续。

股票分钟链固定顺序：**23日前复权日更 → 七频因子repair完成 → MACD/KDJ及state日更 → 必要的七频MACD/KDJ历史repair完成 → 九转更新**。

1. `stock_mins_qfq_daily_update_job`补23日七频并通过原28条检查后，必须运行`stock_mins_qfq_factor_repair_job`，目标日23日。真实因子变化时修复实际股票历史及90/120分钟派生频率；无变化也运行并形成七频完成记录，此时历史重写量为0。前因子缺失时停止。七频完成记录必须对应23日同一真实修复批次和范围，才能启动MACD。
2. 先`gold_stk_mins_qfq_macd_kdj_daily_update_job`生成23日七频指标及state，再按23日因子repair结果判断历史修复需求。若改写历史，必须执行`gold_stk_mins_qfq_macd_kdj_repair_job`；它要求修复区间含23日的state已存在，随后重算实际变化股票的历史指标及递推状态，覆盖到23日。此时日更成功只是中间结果，指标7项加state7项共14条repair完成记录及完整gate通过，才算本批完成。
3. MACD repair当前拒绝空股票名单，也明确拒绝“上游未改写历史”的空操作。无历史改写时，必须核定并记录现行gate“无需历史repair”，不机械启动一个必然报错的job，不制造未实际执行的repair成功记录。
4. repair对象、历史起止、七频范围、代码hash和上游批次全部来自23日实际结果，不照抄22日26股及旧配置；只更新受影响股票并保留其他股票。必须核job状态、七/十四条完成记录、范围和上游身份一致，而不是只看SUCCESS或某条check绿色。
   正式名单由现有日更/factor repair job生成，不由运维人工筛选或修改。因子repair只传目标日期；后续MACD repair通过现成配置函数承接实际因子repair产出的名单、日期和批次。第13节只读估算得到的41股仅用于读取范围/预算，不作为正式repair名单或绕过上游产物传参；不重复前置查询去干预job选择。
5. 当前没有股票分钟九转独立repair job。上述修复完成后，先确认22日seed与修正后历史可以衔接，再运行现成`gold_stk_mins_qfq_nineturn_update_job`补23日四频。仅有证据不足时限定到实际变化代码核seed，不重复旧104项核验；若seed不可用，停止并明确处理范围，不硬算、不虚构repair任务。

任一步失败停止依赖它的步骤，保留已发布正式结果和恢复记录，不自动换root重跑、不删除/覆盖已成功文件或补绿事件。两sensor仍按“23日全部补齐后再处理”TODO执行，本轮一般性的继续授权不用于绕过根AGENTS要求的具体全局历史读取范围批准。

当前代码依据：`ops/stock_mins_qfq_factor_repair.py`、`stk_mins_qfq_factor_repair.py`、`asset_guards/stk_mins_qfq_factor_repair.py`、`ops/gold_stk_mins_qfq_macd_kdj_repair.py`、`asset_guards/stk_mins_qfq_macd_kdj.py`、`assets/qfq_nineturn.py`及现有job。第9—11批的执行卡必须继续遵守本节，不能另写入口绕开。

## 12. 第四批执行卡：板块基础六项

目标仍为23日板块分类、成分、行情Raw/Silver六项，按第3节六个原job顺序逐一通过原check后推进。管理员本轮已授权继续剩余批次；本卡不授权新开发、全历史覆盖扫描、失败自动重跑、调整服务/sensor或覆盖已成功目标。

正式前复用现成`load_prod_dc_board_reference_snapshot`作三个目标日只读聚合：分类/行情身份、成员计数/重复数及板块代码集合，不读取Prod OHLC明细。再用现成`load_tushare_dc_index_daily_source_snapshot`及当前观察常量`DC_BOARD_SOURCE_OBSERVATION_MAX_REQUESTS`（16）取得23日分类/行情。先算分类减行情代码差集；无缺口才调用empty coverage并`confirm_dc_board_source`产生三个新proof。过去日且身份相符可一轮；否则按原合同等至少300秒再观察。有缺口则先保存差集，限定必要历史范围后再处理，不直接调用会自动读取未知历史的`observe_dc_board_source`。不复制22日proof、不伪造recovery identity。

三个Raw配置仅由原`build_raw_dc_board_update_job_run_config(asset_name=..., partition_key="2026-10-23", proof=..., recovery_identity=None)`生成；Silver无附加配置。Raw member依赖同日Raw index，分类先完成；daily同样以分类作覆盖依据。原writer、字段、分页、来源和检查均保持。22日member近10万行、1,052次请求、208秒，只作量级依据；本次用新proof/metadata实际数量，沿原请求策略，不另设限时/请求上限或中断器。

预检仅目标/22与24邻日stat、三个专用日期分区、六job冲突、挂载/空间；仅LOAD已安装postgres扩展。按22日同链规模估读128MiB、写及日志128MiB、额外空间256MiB，含原checks和一次最终stat；若失败继续，另暂留最多同一轮预算再按剩余单元限定，不自动续跑。原生请求重试保留，失败停止，保留已发布结果及实际staging，不删除/覆盖正式文件或重放整个job。

工作目录、DAGSTER_HOME、显式module和现有`.venv/bin/dg launch --job ... --partition 2026-10-23`同前批次。Raw增加`--config <本次proof配置JSON>`，每条独立执行，仅前一步真实run及原check通过后继续；命令及配置原文归档`batch4-8/`。

验收仅本次精确run、输出集合、23日物化、原check与本次物化绑定、catalog物理位置stat/receipt。取消对所有资产一律要求URI的附加条件：URI仅归档为producer观察字段，目标位置以catalog/path helper及原检查为准；CH两producer URI相同且catalog路径为空，不能据URI判断本机/Prod。合法空日资产按原检查处理，不一律添加正行数要求。每个run的验收事件限500；原事件日志按有界页归档，不读行情正文/count/schema/SHA。完成六项后原清单累计69项、余43项，仅实际通过后销账。

## 13. 后续必要历史读取的范围准备

为一次说清具体历史读取批准，先做以下有界只读准备，不执行年度计算、repair或历史价格审计：

- 板块指标：只stat 2024-01-02至23日既有Silver日文件，23日尚缺时标待第四批生成，复用22日677文件/37,590,608B证据。Gold正式仍读六业务列；完整范围和读256MiB/写32MiB/额外64MiB参考待实际stat后申请。
- 股票因子：复用现行`build_adj_factor_changed_codes_sql`（完整factor plan的同一底层SQL），一次按`change_reason`做count/list聚合，读取22/23两份小型Silver因子及Basic所需代码/上市身份，得到23日真实变化、新增、缺前因子名单；不额外运行完整plan后重复查询，不读历史行情，不运行repair或历史planner，不硬编码26、3111或LIMIT27。
- 年度/历史范围：只枚举stat QFQ与MACD的2025/2026年度路径、23日预期输入、实际变化股票的必要历史目标，以及共享state路径。历史Silver若有真实因子变化，按原job四个唯一来源频率1/5/30/60的实际日文件集合stat；不按变化股票占比缩小全市场日文件读取成本。不读取年度Parquet正文或执行历史指标计算。
- QFQ/MACD正常、repair、中断继续和最后验收预算按原LLD第9.6/14/15节公式及现行代码计算，正常只保留一次候选SHA，末尾仅receipt/stat；不增加性能样本或重复原checks。九转更早历史按实际候选限定，不能预先照抄22日002388/44文件。

本准备的输出仅实际名单、路径/stat和预算证据，保存本报告目录；前三小文件读取为日期限定、最小字段的必要对象范围查询。正式价格历史/年度读取必须先明确用途、数据集、日期/对象、方式和预计开销，取得具体范围批准；一般继续授权不替代根AGENTS该项要求。独立的第四批可在准备期间按顺序推进，不启动后续业务批次绕过前置。

## 14. 第五批执行卡：板块指标三步

第四批六项及原检查通过后，按`gold_dc_daily_technical_update_job` → `ch_dc_daily_technical_update_job` → `prod_ch_dc_daily_technical_sync_job`串行执行，分别验收1项物化及1条原check。工作目录、原CLI、module、DAGSTER_HOME同前批次，分区23日，无附加配置；逐步保存完整命令和run id。来源、公式和字段合同沿现行`assets/dc_daily_technical.py`及原writer/两个serving资源，不修改代码。

Gold要读取`silver_dc_daily`的2024-01-02至23日六列`ts_code, trade_date, close, high, low, category`，用于原MACD/KDJ计算的历史输入；只写23日Gold。已复用22日清单纯stat核实既有677文件37,590,608B且身份不变，23日一份待第四批生成，合678文件。只增量stat这份，不重复677份stat或任何正文审计。正常一次含原checks及收尾预算读256MiB、写32MiB、额外64MiB；若需同范围剩余重算再单列同额，保守两轮512/64/128MiB，但不自动重跑。历史读取取得本次具体批准前不启动Gold。

正式前只核Gold目标缺失、本机与Prod `goldenshare_serving.board_fact_technical_daily`的23日count为0、相关job空闲、分区/空间及来源stat；不再查schema/system metadata/EXPLAIN。复用已批准resource，通过只读、目标日计数查询确认两处CH，真实连接分别为clickhouse和prod_clickhouse。两个catalog path为None，两个producer的URI也相同，均不能当成文件路径或用来区分后端；保存原URI但不额外断言其等于猜测的catalog位置。

Gold原check通过后才发布本机，再本机原check通过后发布Prod。发布包含当日技术指标表原事务/读回，不改其他日期或表；最后仅核三run、三个原checks及本次物化绑定、metadata和Gold/来源/邻日stat，不重复完整业务比对或SHA。Gold成功后如CH失败，只核未完成CH，不重读历史；任何失败先停止并保留正式结果和原记录，不整批重放、清理或回滚。

本批完成后累计72/112，余40；不提前销账。范围及预算证据：[板块历史stat预算（附件已清理）](README.md#报告附件清理2026-11-01)。

## 15. 第六批执行卡：资金流两项及全球指数Silver

第五批完成后，先`raw_tushare_moneyflow_ths_update_job`→`silver_moneyflow_ths_update_job`，再`silver_index_global_update_job`。三项各1条原check，使用同一正式CLI/module/DAGSTER_HOME、分区23日，原日志与逐步记录仍放`batch4-8/`。THS无附加config；全球Silver仅用现成`build_index_global_silver_run_config(trade_date="2026-10-23", attempt=0)`，不另拉已有Raw。

当前代码依据为`assets/moneyflow_ths.py`、`io/moneyflow_daily_update.py`、`asset_guards/moneyflow_row_count.py`、`assets/index_global_silver.py`和`run_contracts/index_global.py`。THS原job自己两轮取数、间隔60秒，现行页大小2000、每轮最多2万行；两轮共用64请求及Raw采集/提交前300秒原预算不改（不等于整个job硬超时）；无需提前额外取源样本。它读取最近五个已物化且通过readiness的Raw小文件作基线，不足五个时按现行2026-09-30回退；不跳过缺少/不绿基线。全球Silver只消费23日Raw和原合同，合同允许合法空自然日，不给整个资产增加正行数附加要求；当前基线23日Raw有10行，仅作为已有证据。

正式前只stat三目标缺失、全球同日Raw/基线存在性、22/24邻日以及两个专用分区`cn_a_moneyflow_ths_trade_days`/`cn_global_index_trade_days`、job冲突和空间。全球writer会直接替换，所以目标出现即停核清。预算含原检查、日志及stat收尾：读64MiB、写32MiB、额外64MiB，失败继续另暂留同额后按实际未完成限定，不自动重跑；不涉及年度/全历史价格读取。失败保留正式结果与原记录、停止下游，不清理或补绿。验收沿本轮原run/check绑定/metadata/stat，无额外正文/SHA扫描。实际三项通过后累计75/112、剩37。

## 16. 第七批执行卡：股票分钟Raw与Silver

第六批通过后，先`stock_mins_raw_update_from_prod_job`补五频，再`stock_mins_silver_update_job`补五频。原检查分别15/20，共35；日级目标23日，不在本批生产QFQ或指标。现有Raw/Silver publication及同root继续方式不变，Gold尚不执行。

必要来源准备复用`stock_resume_20261025/dg22_stock_resume_preflight.py.txt`的股票部分：核当前Basic/身份/生命周期/23日日线及最终停牌Silver依赖，调用现行`load_current_listed_stock_codes_for_stk_mins`得到日期对象池；`stk_mins_prod_source_ready_for_trade_date`查询覆盖23日的Prod成功任务和五频/代码存在性，取得其真实completion_reference。不能硬编码16729、5576或把任务成功当覆盖成功；原修正支持合法区间任务。仅使用允许的ops.task_run字段以及分钟身份/时间聚合，不提前另读价格样本。通过后用现成`build_stock_mins_raw_update_job_run_config(source="prod_db", prod_completion_reference=...)`生成配置。

先只核Raw分区`cn_a_stock_mins_trade_days`23日已注册及Silver专用分区状态。若`cn_a_stock_mins_silver_trade_days`缺23日，在Raw五频及15原checks通过后，复用现行Silver注册readiness核日线/停牌/身份及五频；仅用原SDK精确登记23日，不启动sensor、批量回建其它日期或改历史注册。管理员本轮补齐授权覆盖这一必要的单日登记，实际前置/命令另记本节；没有通过readiness不能登记。

Source只导出23日、预期代码、既定字段及五频，正常5个日窗口；只LOAD已有扩展，不触发安装回退。先用source gate的聚合和22日量级冻结预算，23日实际行数/对象数在预检报告保存；22日原生Raw/Silver约91.58/16.08秒仅参考。正常含导出/原checks/候选/记录/收尾保守预算读4GiB、写1GiB、额外空间2GiB；失败继续另按最多同额预留再按未完成单元限定，不改现有资源上限、不据估时发信号。

各job前确认所属目标全缺失；原job写入/receipt方式不改。每步验收精确run、五物化、原15/20check绑定、完成依据metadata和实际stat。最后不重读价格/count/schema/SHA，核依赖/邻日身份保持，失败停止后续并保留已发布和staging，不新root盲重跑。35原checks通过且十项完成后累计85/112，余27；下一步先做成交额，再做QFQ及repair。

第七批操作细节：任务辅助脚本为`/private/tmp/dg23-stock-batches7-8.py`，归档`batch4-8/stock-batches7-8-readback.py.txt`；它只做预检、配置、事件核验、stat和上述精确单日登记，不计算/写入业务数据。Raw命令为原`dg launch --module-name orchestrator.definitions --job stock_mins_raw_update_from_prod_job --partition 2026-10-23 --config <本报告batch4-8/stock-raw-run-config.json>`，Silver同入口指定`stock_mins_silver_update_job`、无附加config。每个launch前保存时间窗口，按精确job/分区取得唯一新run，空CLI日志不作为失败或重跑依据。第六批THS链和全球Silver相互独立，亦均非股票链业务前置；THS失败时按第23节仅停止其Silver，全球通过后可继续第七批，不能把THS标为成功。

登记前复用`sensors/readiness.py`的`raw_stk_mins_ready_for_trade_date`、`stock_daily_ready_for_trade_date`、`suspend_d_ready_for_trade_date`及`silver_stock_identity_map_ready_for_trade_date`核最新物化/原检查绑定，再调用现有`build_stock_mins_silver_trade_day_registration_decision`。Raw五频物理语义已由刚完成的15条原检查验收，且文件stat未变，不再调用会重复读取五份正文的`batch_raw_stk_mins_lake_readiness`。若缺23日，仅在全部门禁通过后调用`DagsterInstance.add_dynamic_partitions("cn_a_stock_mins_silver_trade_days", ["2026-10-23"])`并读回这一键；不评价/启用sensor。实例只读核验直接使用禁止自动建表的storage，只有获准登记和原job执行使用正式SDK/CLI写入。

## 17. 第八批执行卡：市场成交额Gold与Prod

第七批五频Silver及23日日线通过后，仅执行一次`gold_wealth_market_turnover_update_job`，内部选择Gold→blocking check→Prod两个资产，不另找或创建Prod独立job。正式命令同前批次，分区23日，无额外config；代码依据`jobs/gold_wealth_market_turnover_update.py`、`wealth_market_turnover_contract.py`和`assets/wealth_market_turnover_prod_core.py`。

必要预检仅stat五频Silver和同日日线这六份输入、Gold目标缺失、相关job空闲，以及通过该发布链既有`ProdPostgresWriteResource.connect_readonly()`只读计数确认Prod `core_serving.wealth_market_turnover_snapshot`在`type=stock/market=CN_A/trade_date=23日`五频范围没有待覆盖记录。Gold现writer直接os.replace，目标出现即停；Prod原事务仅处理这一范围，原生逐14字段读回和points_json_hash验证，不能删其它日期/市场/类型。

以本次六输入stat校准22日31,283,049B量级；原writer至少三轮同日聚合加原check，不假称只读一遍。正常预算逻辑读取1GiB、候选/记录/日志64MiB、额外128MiB，含原检查和最后stat；失败继续另按最多同额再限定。无年度/全历史输入、无额外性能测试或重复14字段全文比对。

验收两物化，但只有Gold1条catalog blocking check；不能给Prod增加不存在的check。核Prod原`goldenshare/read_back_row_count`、`goldenshare/points_json_hash`、`goldenshare/prod_table`等实际metadata及事务结果，不把URI当数据库事实。Gold成功而Prod失败时保留Gold，先核事务是否提交再决定未完成步骤，不整job覆盖重放。两项通过后累计87/112、余25。之后严格进入第11节复权及repair顺序。

## 18. 股票历史读取的具体申请范围（已批准，见第20节）

本节只列原job正常更新/repair所需历史读取，不新增数据审计；尚未读取年度或历史价格正文。前置小查询和文件stat证据见[实际统计（附件已清理）](README.md#报告附件清理2026-11-01)、[分项测算（附件已清理）](README.md#报告附件清理2026-11-01)。预算中的41股仅用于估算，正式范围仍由job产物决定，不人工生成执行名单。

| 阶段 | 必要读取/合并范围 | 正常读/写GiB | 额外空间GiB |
| --- | --- | --- | ---: |
| 前复权日更 | 23日七频对应Silver/因子，合并受影响股票2026年七频QFQ年度文件；现目录上界39,151份、7.555GiB，新增上市文件按实际产物 | 34 / 9 | 12 |
| 因子repair | 原job确定的变化股票2014-01-02至23日七频历史；Silver为全市场日文件，四个唯一来源频率1/5/30/60既有约44.06GiB，读取不能按41股占比缩小；历史因子及相应QFQ年度合并 | 52 / 3 | 4 |
| MACD/KDJ日更及state | 2025/2026两年七频QFQ，合并2026年度指标并生成23日state；来源77,392文件约16.37GiB，现指标年度上界约17.27GiB | 280 / 88 | 96 |
| MACD/KDJ repair | 正式因子repair实际变化股票，2014-01-02至23日七频指标及共享state合并，保留其他股票；预估41股历史QFQ0.674GiB、旧指标1.577GiB、既有21,777份共享state3.575GiB，23日7份由日更生成 | 36 / 20 | 24 |
| 股票分钟九转 | 四频2025/2026 QFQ及22日seed；必要时一次实际变化股票seed核验；更早历史仅限原有界候选查询所得代码、2014—2026年、候选文件合计不超过1GiB，先stat确认再由原planner读取，不改候选名单 | 26 / 3 | 3 |

正常各一次，股票链总计估读428GiB、写123GiB，顺序执行额外空间128GiB。包含原job计算、年度合并、历史修复、原checks、候选一次SHA、DuckDB工作文件和最后receipt/stat；不是新增428GiB审计或新增123GiB正式结果，也不是实测设备I/O/运行限制。MACD日更临时读写各按64GiB预留，依据22日曾留下57.7501GiB工作文件，不能继续用偏低32GiB。41股旧指标实际1.577GiB超过22日1.5GiB假设，本次旧指标/候选各按2GiB预留。

中断后继续成本单列：最坏再计同阶段一次预算，先按实际未完成unit/原root/receipt核定，不申请自动重跑；保留工作文件时另核空间。正常预算不授权新增性能试验、第二遍普通checks、末尾价格比对或SHA。23日Silver、上游更新后的年度大小、实际repair名单/日期及九转候选在对应前序完成后以原产物和stat回填；若超过列明范围/假设，先报告，不人工缩减名单或让原planner先读未知范围。

原job执行顺序严格遵守第11节，每一步正式前仍补齐本步原LLD对账、精确命令/配置、前序和实际身份。特别是两个repair为op-only：因子产七频完成check，MACD产指标及state共14条完成check；不要求它们产生不存在的物化。QFQ和MACD指标为年度文件族，不能套用单份trade_date文件URI/stat断言，沿22日专用receipt/gate核验方法，只读本次必要记录。这里具体读取范围批准前，不启动第九批以后的价格年度/历史计算。

## 19. 第四批六项完成；等待具体历史读取批准

2026-10-26 10:48:10完成第四批。六个原job各运行一次，六物化及六条原检查/绑定通过：

| job | run id | 行数 |
| --- | --- | ---: |
| `raw_tushare_dc_index_update_job` | `1c334a03-1133-4627-af85-41af40032369` | 1,043 |
| `silver_dc_index_update_job` | `5feb093f-e65c-4d07-ba84-7d76b80cfd35` | 1,043 |
| `raw_tushare_dc_member_update_job` | `fb1bc790-018b-4084-9eba-867be003f1df` | 98,939 |
| `silver_dc_member_update_job` | `7bce61de-637f-4dc1-9067-72fd24a08a0b` | 98,939 |
| `raw_tushare_dc_daily_update_job` | `6499541e-c8a1-4f06-9424-5006452b3059` | 1,043 |
| `silver_dc_daily_update_job` | `cff7e673-a6c9-4133-9e0b-54c085794d95` | 1,043 |

六文件共1,098,192B；成员Raw原生耗时180.939秒。来源proof来自本轮23日Prod/Tushare确认，零代码缺口，无历史覆盖正文读取。末尾仅事件/metadata/stat，22/24邻日身份不变，正式job重跑0，未调整sensor/配置/业务代码。具体记录：[第四批验收（附件已清理）](README.md#报告附件清理2026-11-01)、[当前进度（附件已清理）](README.md#报告附件清理2026-11-01)。

第五批所需新增23日Silver身份直接复用刚完成的原job验收记录，未再次读文件正文或重stat旧677份。实际678份共37,649,855B，原256/32/64MiB预算不变，见[增量范围记录（附件已清理）](README.md#报告附件清理2026-11-01)。

根AGENTS规定具体全局历史读取需另行批准；已分别提出板块范围和股票范围申请，尚未收到对应批准，故不启动第五批Gold，不跨批执行后续业务job，也不打开年度/历史价格正文。预算估算名单不会作为执行名单，正式repair仍只消费job实际产物。当前累计69/112、余43；取得批准后从第五批接续。

## 20. 具体范围批准及执行口径

管理员在要求解释历史读取原因、确认repair名单应由job生成后，明确回复“批准，你的方案已经准备好了吗”。本次承接已提出的两项具体申请：第14节板块2024-01-02至2026-10-23历史六列，正常读256MiB、写32MiB、额外64MiB；第18节股票年度及历史范围，正常估读428GiB、写123GiB、顺序额外空间128GiB。均沿现有job正常运行一次，失败停止、保留已发布结果与staging，不自动重跑；不是对任意历史范围的授权。

这里的预算是现行实现的保守估算，不是算法不可减少的最低成本，也不是新加的进程限制。已向管理员说明以下区别：

- 23日前复权只计算当天；旧年度读取用于合并并保留同年其他日期。因子变化时，受影响股票的旧前复权和依赖它的指标需要一致修复，实际名单和范围由job产出。
- 因子repair当前从2014年起读取全市场Silver日文件后筛选实际股票，这是现行存储布局和重建方式的开销，不能按41股占全市场的比例缩小源文件读取量。
- MACD日更在完整22日state存在时，算法需要23日K线及最多8根先前K线；当前代码仍先装入2025/2026七频历史，再筛选计算输入。两年加载是现行实现的额外开销，本轮沿用该实现；读取优化尚未完成专门方案、LLD或开发，不能声称已优化。
- MACD历史repair重算实际变化股票；共享state合并时读取并保留其他股票，并不重算其他股票。板块Gold当前没有增量state，从固定2024年起读取历史。九转只按原planner实际候选补充必要历史。
- 预算已包含原检查、候选一次摘要及临时文件预留；不增加末尾全量价格比对、重复检查或摘要。MACD临时读写各64GiB是按22日工作文件量保守预留，不能当成已实测的每次设备I/O。

第五至第八批执行卡已在第14—17节；第九至十一批按第11/18节和原LLD，在各自前序完成后补入实际产物身份、原配置函数结果、精确命令及必要stat，不预填不存在的run、repair名单或通过结果。各批依次通过原检查后继续，最终只对112项清单做证据对账，不重复全局数据审计。

## 21. 第五批完成：板块技术指标三项

23日Gold、本机CH、Prod CH依次各执行一次，三项各1,043行、三条原检查与本次物化绑定全部通过；Gold文件151,650B。无正式job重跑、无额外正文/摘要/全局审计、无代码或sensor修改。仅stat核来源新增23日和22/24邻日不变，未重stat旧677份历史。

| job | run id | 结果 |
| --- | --- | --- |
| `gold_dc_daily_technical_update_job` | `3cd5af77-2257-4024-a994-4dc2de928dcd` | SUCCESS |
| `ch_dc_daily_technical_update_job` | `4264f427-0319-4af3-8983-32a9f577462b` | SUCCESS |
| `prod_ch_dc_daily_technical_sync_job` | `a6d8637d-8f26-4eb0-b94d-66299ef76637` | SUCCESS |

证据：[第五批验收（附件已清理）](README.md#报告附件清理2026-11-01)。累计72/112项，剩40项，接续第六批。

## 22. 第九批执行卡及原LLD对账

复用原QFQ staging写入LLD第9/13/14节；23日完整操作、日更与repair配置/命令、真实名单来源、预算、原28检查及7完成记录、receipt/stat、失败与继续口径见[第九批执行卡（附件已清理）](README.md#报告附件清理2026-11-01)。该卡已核当前代码，但第七/八批实际产物须在正式前通过preflight回填；不跳过前序，不提前启动年度读取。具体读取批准由第18/20节覆盖，没有新增开发或性能试验。repair后的最终事实采用实际repair receipt/gate，不要求合法改写目标保持daily阶段旧stat。

## 23. 第六批THS源合同失败及独立链继续规则

唯一THS Raw run `fb626ec4-e7b3-4fb2-ac5f-311ee1e8e7bd` 在4.36秒后失败，0物化、0原checks、0正式目标写入。原错误 `source_numeric_contract`：23日源返回688368.SH、300687.SZ、301448.SZ的 `net_d5_amount=NaN`，现行合同拒绝。源问题尚未修正；不重试、不转换/填补NaN、不改合同、不人工补绿。THS Raw/Silver两项仍缺失；原run staging保留，正式目标及22/24邻日未变，证据为[原失败收尾（附件已清理）](README.md#报告附件清理2026-11-01)。

第2节及第六批定义已说明THS和全球Silver是独立链；股票分钟也不消费THS。故只停止依赖失败Raw的THS Silver，后续按原序继续全球Silver，再进入第七批，不把整个第六批伪装成通过。这是已批准分批方案的失败隔离，业务job、读写范围、公式和预算均不变。THS补齐需源恢复或另行核清合同处理，不在此处擅自开发。

全球Silver仍仅原`silver_index_global_update_job`一次，使用已生成的日期23日/attempt0配置及第15节预检；它不需要THS产物。辅助事件核验只要求第五批已通过、全球本日Raw身份未变及全球目标缺失，不将失败THS作前置，也不重新执行THS请求或检查。全球结果独立保存`batch4-8/batch6-global-final.json`；保留原`batch6-final.json`失败证据，另存`batch6-progress.json`汇总“全球完成、THS两项阻塞”。

第七批依该独立全球结果接续，股票自身来源/readiness仍须完整通过；不能因为继续股票而销掉THS两项。最终对账允许明确记录这两项仍缺失，sensor继续停止，直至缺失实际解决。

## 24. 第十批执行卡及原LLD对账

原MACD/KDJ日更及必要历史repair的完整操作见[第十批执行卡（附件已清理）](README.md#报告附件清理2026-11-01)，与第11/18/20节及原LLD第15/16节对齐。正式前只承接真实因子status、两年QFQ必要增量stat和22日state身份；daily14物化/28原检查通过后，使用原sensor的decision/config函数生成实际repair配置。需要repair时还须14完成及完整gate；最终重叠目标按repair最新receipt核实。MACD指标URI只是一份样本年度路径，repair目录从本run原日志取得，不能猜root目录。当前前序尚未完成，不提前运行本批。

## 25. 第六批独立全球Silver完成

原`silver_index_global_update_job`在23日运行一次，run `8be9df8d-3565-4a0d-88ae-4c5f3857bcf0`，SUCCESS、10行、2,418B，1条原检查与本次物化绑定通过，耗时5.636秒。Raw及22/24邻日stat未变，无额外正文/SHA或Tushare请求。证据：[全球单独验收（附件已清理）](README.md#报告附件清理2026-11-01)、[第六批分链进度（附件已清理）](README.md#报告附件清理2026-11-01)。THS两项继续明确阻塞，原失败未覆盖；累计73/112、剩39，接续第七批。

## 26. 第十一批执行卡及必要候选范围核验

完整操作见[第十一批执行卡（附件已清理）](README.md#报告附件清理2026-11-01)，对齐原九转LLD第22节。先承接实际factor/MACD完整gate，必要时只对本轮实际变化股票四频核22日seed一次；然后只用原有界候选键查询取得实际名单，先stat年份/合计≤1GiB才运行原job。无旧104项重复审计、不调用完整planner先读未知历史、不改公式或资源。四原检查和最终receipt/stat通过才销账；THS两项仍按实际结果保留。

## 27. 第七批完成：股票分钟Raw/Silver十项

Prod覆盖23日的真实成功任务为16729，预期5,577股五频覆盖通过。原Raw run `4365769c-a69d-4a0d-a216-17ab2723afcc`（93.016秒）和Silver run `9f6b4a4c-f18b-4fc3-8ec7-f4b2aef79167`（16.917秒）各一次SUCCESS；十物化、35原检查与本次物化绑定通过，十文件77,333,392B。Raw检查通过及日线/停牌/身份readiness通过后，仅登记23日一个Silver分区。无额外价格/摘要/全局审计，来源和22/24邻日stat未变。证据：[第七批收尾（附件已清理）](README.md#报告附件清理2026-11-01)、[单日登记（附件已清理）](README.md#报告附件清理2026-11-01)。累计83/112、余29，THS两项继续阻塞；先成交额，再前复权及repair。

## 28. 第八批完成及第九批实际预检

原成交额job run `cae350fa-3c07-4d21-a62f-533d04e2a06c` 一次SUCCESS，1.709秒；Gold/Prod各5行，Gold原检查绑定通过，Prod原生read_back_row_count=5，points_json_hash及表名见原metadata。只stat六输入及邻日，无重复全文比对。累计85/112、余27，证据：[第八批验收（附件已清理）](README.md#报告附件清理2026-11-01)。

第九批只读预检通过：[预检（附件已清理）](README.md#报告附件清理2026-11-01)、[输入身份（附件已清理）](README.md#报告附件清理2026-11-01)。实际日更映射D=58,768,990B，原预算公式含预留估读32.791GiB/写8.625GiB，未超过已批准34/9GiB；Lake/staging空间充足、同设备，两个sensor仍STOPPED、writer空闲。无需重新读年度正文或做性能测试，按原日更命令运行一次，之后先因子repair再MACD。每个run的原compute stdout从已配置dagster_logs/<实际run>/compute_logs读取/归档，仅用于进度及receipt定位，不因空CLI日志重跑。

## 29. THS失败的进一步静态核验：尚不能认定源端错误

第23节记录的是原job实际拒绝NaN的事实，不足以认定Tushare原始响应一定错误。当前`run_contracts/asset_column_schemas.py:1124`明确net_d5_amount允许NULL和负值；`run_contracts/moneyflow_daily.py:84`允许JSON NULL，但拒绝非空NaN。现有THS测试分别用None证明合法空值通过、用字符串NaN证明非法文本拒绝。

真实取数经过安装版SDK的DataFrame构造，再由`resources.py:80–88`直接to_dict(records)，worker/writer直接JSON序列化，没有把DataFrame浮点缺失值还原为None。合法HTTP NULL因此可能变为浮点NaN再被本地拒绝；当前NULL测试直接给None，没有覆盖真实SDK转换。本次错误样本只保存SQL提取的NaN文本，没有JSON类型，不能区分源文本NaN和SDK浮点缺失，更不能用旧测试通过证明此链正确。

本轮到此仅做静态代码/已保存失败证据核验，没有新源请求、取样、测试、合同或业务代码修改。两项仍阻塞。后续最小确认应先对已有失败页只投影三代码/目标日/该字段及JSON类型，再用两行合法NULL混合数值的HTTP夹具经真实SDK作隔离复现；若证实本地误拒绝，修复应恢复可空字段NULL语义，同时继续拒绝文本NaN、无穷和非法数值，不能直接放宽SQL或填0。该开发/验证尚未实施，须先完成对应修复方案及影响审计；本轮原job补齐范围不用于擅自变更合同或扩大开发。

## 30. 第九批日更通过，原因子repair已启动

原QFQ日更 run `6db0d861-b521-4e32-b55f-100729614b1a` 一次SUCCESS，七物化及28原检查绑定通过，耗时946.458秒。仅从本run stdout、operation/receipt和stat验收，实际提升39004份2026年度文件；候选合8147244635B，冻结当日replacement合32166751B，未增加行情正文/摘要读取。完整记录：[日更验收（附件已清理）](README.md#报告附件清理2026-11-01)。

日更完整验收后，重新只读核无活动run、两个sensor停止、pool空闲；已按日期23日配置启动一次原因子repair。配置没有股票名单，正式名单和历史改写结果以该job产物为准。因子完成前不启动MACD，也不提前给第九批七项销账；既有已完成85/112，THS两项阻塞不变。

## 31. 第九批七项全部完成，包含原因子repair

原因子repair run `f9e95a68-8774-483f-a73c-97190614ad7d` 一次SUCCESS，耗时145.417秒；原job实际选择41股，区间2014-01-02至2026-10-23、3112交易日、完整七频。七条本次完成记录及原factor guard ready，producer/batch/hash/日期/名单一致，全部必要修复完成。没有使用预算名单构造执行配置。

日更提升39004份年度文件，repair另提升2975份（包括合法再次替换的当年目标，不能将两数相加当唯一文件数）。两个阶段均仅原job各一次，最后验收为本run日志、operation/receipt/stat，无历史正文/摘要重读、普通检查重跑。证据：[完整第九批结果](batch9/final.json)、[原因子验收及真实下游名单（附件已清理）](README.md#报告附件清理2026-11-01)。第九批七项销账后累计92/112、余20，先MACD日更及state，再消费实际因子产物执行必要MACD repair。

## 32. 第十批日更启动前核验

真实因子产物已通过，22日七份前序state身份一致，23日state仍缺失、writer/两个sensor/空间条件通过；两年来源量仅由原metadata和第九批receipt差额计算，没有重新glob或读取行情。原公式含预留估读263.139GiB、写85.004GiB，在已批准280/88GiB内。按原MACD日更job仅运行一次，正常生成23日14项/原28检查后，再由现有decision/config函数承接实际41股因子结果生成历史repair配置。

## 33. 股票历史范围的结构化批准补录

管理员对原股票链428GiB读/123GiB写/128GiB空间具体申请进一步回复“批准，按原job及repair顺序执行”（原问题call_485959afac464909b572388ef4639570）。范围、实际名单来源、日期和失败停止/不自动重跑与第18/20节一致，只补录批准证据，不重新启动已完成job、不申请额外一轮、不扩大任何年份或股票。当前QFQ日更及原因子已通过，MACD日更正在原run执行。

MACD日更实际run为`bae395a8-d840-4fdf-95d0-b428477c8967`，按第32节一次运行。运行中仅观察精确run原事件和原日志；日更尚未完整验收、必要repair尚未执行时，14项不提前销账。当前已完成92/112，THS两项阻塞单列。

## 34. 第十批日更通过，按实际产物启动指标repair

MACD日更 run `bae395a8-d840-4fdf-95d0-b428477c8967` 一次SUCCESS，耗时743.697秒；14物化、28原检查及本run receipt/stat完整通过。实际indicator URI仅样本文件，完整输出按operation targets核实。证据：[日更验收（附件已清理）](README.md#报告附件清理2026-11-01)。

原decision/config函数承接原因子batch `qfq_factor_repair:2026-10-23:48e264f2d598`，生成实际41股、2014-01-02至23日七频repair配置；没有人工预算名单拼装。当前真实指标/state差额后的公式含预留估读31.408GiB、写16.5GiB，处于已批准36/20GiB内。配置/门禁和预算见[原函数决策（附件已清理）](README.md#报告附件清理2026-11-01)。只启动一次原op-only repair、不传日期分区，成功后还须14完成记录及完整gate，才给本批14项销账。

MACD历史repair实际run为`9c3a3e7c-6dae-40eb-beea-afa3c0cef439`，正常只启动这一次。它是op-only job，不产生新物化；以原14条完成记录和完整gate验收。当前14项仍不提前销账。

## 35. 第十批十四项完成，包含必要历史repair

历史MACD/KDJ repair run `9c3a3e7c-6dae-40eb-beea-afa3c0cef439` 一次SUCCESS，479.321秒；实际41股、2014-01-02至23日、3,112交易日及七频，14条完成记录与因子批次/hash/日期一致，原completion gate及完整gate ready。日更run和repair run各一次，未重跑普通28检查。

最终记录按已验收JSON核对：repair共24,759目标，和daily重叠294个（287份当年指标及七份23日state），重叠目标使用repair最终身份；daily独有38,717个目标保留daily验收。没有末尾年度正文、SHA或重复目标stat，证据：[第十批完整结果](batch10/final.json)、[repair验收（附件已清理）](README.md#报告附件清理2026-11-01)。十四项销账后累计106/112、余6；九转四项继续，THS两项仍阻塞。

## 36. 第十一批九转四项完成

实际41股四频22日seed共164项一次比较全部一致，原候选查询分别得到2/2/3/3代码；候选历史58文件、2,042,644B，全部位于批准2014—2026范围内。未照抄22日旧候选名单，未调用完整planner先读取未知历史。原job run `5c7773fc-6fe9-4586-b250-528542881801` 一次SUCCESS，四物化及四原检查/绑定通过，输出94,724行、230,956B。最终仅receipt/stat和输入身份收尾，无行情正文/SHA重读。证据：[必要准备（附件已清理）](README.md#报告附件清理2026-11-01)、[九转验收](batch11/final-verified.json)。

## 37. 最终结果：110项完成，THS两项仍阻塞

本次目标日期为**2026-10-23**。原112项缺失按已确认分批依次推进，最终补齐110项；其中第六批全球Silver独立完成，THS两项明确未完成。最终逐项证据及31个成功run见[原112项最终对账](final-reconciliation.json)，不是再次全局审计。31个原job SUCCESS、一个THS Raw原job FAILURE，THS Silver未启动；没有重复正式job或另写数据补齐程序。原检查和repair完成记录合计253条通过。

| 数据链 | 补齐项 | 结果 |
| --- | ---: | --- |
| 主要指数分钟 | 39 | 原job及检查通过 |
| 指数日线/九转/Prod | 5 | 原job及检查通过 |
| 普通指数分钟 | 19 | 原job及检查通过 |
| 板块基础、技术指标及两处CH | 9 | 原job及检查通过 |
| 全球指数Silver | 1 | 原job及检查通过 |
| 股票分钟Raw/Silver | 10 | 原35检查通过 |
| 成交额Gold/Prod | 2 | 原检查及Prod事务读回通过 |
| 股票QFQ | 7 | 日更28检查、原因子七完成及guard通过 |
| 股票MACD/KDJ及state | 14 | 日更28检查、历史repair14完成及完整gate通过 |
| 股票分钟九转 | 4 | 原四检查通过；必要164项seed比较一致 |
| THS资金流Raw/Silver | 0/2 | NaN处理阻塞，未重试或放宽合同 |

两类历史repair均按原job真实产物覆盖41股、2014-01-02至2026-10-23、3,112交易日七频；共享state保留其他股票。只运行正常必要步骤及原检查，批准范围外历史读取0、全局数据审计重跑0、额外性能试验0。读写预算是文件级估算，不把预算当实际设备I/O，也未增加运行资源限制或中断器。

剩余`raw_tushare_moneyflow_ths`、`silver_moneyflow_ths`：原Raw run因三代码net_d5_amount=NaN被现行检查拒绝，正式Raw/Silver仍缺失。合同允许NULL，SDK转换是否把合法空值变为NaN尚需按第29节最小确认，不能断言源端一定错误；本轮没有修改代码、改合同、填0或人工补绿。后续处理只针对这条失败链，股票链不用重跑。

两个股票sensor仍STOPPED，原“23日全部补齐后再处理启用”TODO保留；尚余两项，不能宣布所有数据齐备。正式数据及业务staging/receipt保留。本轮操作辅助脚本清理和文档验证另记清理记录，不删除业务失败现场。

## 38. 辅助文件清理与文档验证

本轮最后四份任务辅助脚本均在确认与归档内容一致后从/private/tmp删除；此前各批辅助脚本也已按各批记录清理，当前/private/tmp下dg23前缀脚本为0。所有执行源码文本、命令、原日志、JSON验收记录保留报告内。DuckDB managed工作目录顶层仅原有共享index_daily_p3目录，未删除共享目录；没有本次直接工作文件遗留。正式Lake、业务staging/冻结输入/receipt/THS失败现场删除0。清理明细：[cleanup.json（附件已清理）](README.md#报告附件清理2026-11-01)。

仓库文档完整性三项检查通过；本报告目录Markdown本地链接检查通过，无缺失目标。只校验文档和已有结果，不重复数据审计；详情：[validation.json（附件已清理）](README.md#报告附件清理2026-11-01)。

## 39. tushareMCP定向源核验：三条记录存在，可空字段返回null

管理员要求先用tushareMCP读源后，仅对失败的688368.SH、300687.SZ、301448.SZ分别调用一次moneyflow_ths，trade_date=20261023，显式请求现有13字段。三次均成功、各1条，代码与日期一致；net_d5_amount在MCP结果中均为JSON null，net_amount等金额字段有数值，另外三个净流入占比字段也为null。没有全市场查询、分页全取或重跑job。

| 股票 | 源记录 | net_d5_amount | net_amount（万元） |
| --- | ---: | --- | ---: |
| 688368.SH 晶丰明源 | 1 | null | -839.03 |
| 300687.SZ 赛意信息 | 1 | null | 12500 |
| 301448.SZ 开创电气 | 1 | null | 1246.06 |

当前证据排除了这三只股票整条源记录不存在：MCP能返回记录及合法空值，DG合同也明确允许这些字段NULL。应优先核查DG的SDK/DataFrame及JSON序列化如何保留空值，不能以更新Prod或填0替代；MCP序列化结果不是原始HTTP报文，具体NaN产生环节还需最小复现确认。后续修复须覆盖所有相关可空字段，不能仅针对net_d5_amount一列。此次没有修改代码、合同或正式数据，两项仍未恢复，110/112结果不变。

原调用参数、三份完整MCP响应及时间记录：[定向源证据（附件已清理）](README.md#报告附件清理2026-11-01)。结论仅覆盖这三条样本，不代表该日全市场完整性已经重新审计。

## 40. 三只样本过去一个月源数据回查

管理员要求核前一个月是否也有缺值，本次按23日向前一个自然月限定2026-09-24至2026-10-23，仍只查询原三只失败股票。tushareMCP moneyflow_ths每股一次范围请求、现有13字段；另一次SSE交易日历范围请求核对开市日期。30个自然日中有16个交易日；三股各16条、合48条，交易日没有缺行或重复，未扩大至全市场。

| 股票 | 返回交易日 | net_d5_amount有值 | 空值日期 | 10月22日值（万元） |
| --- | ---: | ---: | --- | ---: |
| 688368.SH 晶丰明源 | 16 | 15 | 2026-10-23 | 704.29 |
| 300687.SZ 赛意信息 | 16 | 15 | 2026-10-23 | -1967.25 |
| 301448.SZ 开创电气 | 16 | 15 | 2026-10-23 | 65.87 |

三个净流入占比字段buy_lg_amount_rate、buy_md_amount_rate、buy_sm_amount_rate也完全相同：每股此前15个交易日有数值，只有23日为null。其余请求字段在这48条返回记录中未见null。故当前历史回查显示，这三只样本的部分指标缺值集中于23日，不是这个月持续缺，也不是整条源记录不存在。

结论仅适用于当前MCP返回的三只样本历史，不能扩大为全市场，也不能倒推出此前各日当时的发布状态；具体缺值原因、NaN生成环节尚未通过本次回查证明。只读调用共4次，没有取全市场数据、修改代码/合同或重跑job，原110/112补齐状态不变。独立复核48条原响应及日历，结论一致。完整请求、响应、逐字段空值日期：[月度源证据（附件已清理）](README.md#报告附件清理2026-11-01)。

## 41. 本轮暂停后的清理方案与LLD

管理员决定本轮补数暂停，等待后续源端情况，并明确要求清理本轮生成且无用的中间文件。本步只整理本报告目录，不改业务代码、不触发job或sensor、不查询源端、不读取行情正文、不做数据审计。正式Lake、全部业务staging、冻结输入、operation、receipt、checkpoint及THS失败现场保持现状；两个股票sensor仍停止。

清理前代码和文件核验已完成：四份CLI日志与各自compute.out逐字一致，三份构建片段原文完整包含在最终readback.py.txt，两个执行卡草稿已由正式执行卡取代且无报告链接引用，metadata-progress.json的全部内容包含于metadata-summary.json。18份日志为零字节。只删除这28份明确冗余文件，共572,183B；完整路径、删除依据和保留的替代文件记入[本步清理清单（附件已清理）](README.md#报告附件清理2026-11-01)，执行时按该清单逐项处理，不按通配符或目录递归删除。

三份大JSON不能当成无用文件删除：batch10/daily-target-identities.json与repair-target-identities.json保存正式文件提升后的完整身份，receipt不包含其中最终ctime；batch11/metadata-preflight.json保存执行前输入身份和seed证据。三份共71,410,110B，只作无损gzip归档，保留全部原内容和原路径映射，不重新采集数据。最终README、执行卡、对账、源核验、审批预算、非重复日志、失败证据和实际执行脚本归档均保留。

实现位置限定为本目录清单及一次性本地整理程序。先记录每个待处理文件的设备号、inode、尺寸、mtime和ctime，以及其余保留文件的SHA256；拒绝符号链接、清单外路径、身份变化或已存在的归档目标。压缩时流式读取原JSON并计算SHA256，先写同目录独占创建的临时归档；解压该归档核对原字节数和SHA256，重新确认原文件身份后，原子改名为.json.gz，再移除原JSON。保留原执行脚本和验收JSON中的历史路径，不改写当时的执行事实；清理结果记录原路径、归档路径、原尺寸和SHA256。恢复查看时可由gzip解压取得原JSON；重用历史辅助脚本前须先还原其依赖文件，本步不执行这些脚本。

删除前再次确认零日志仍为空、重复文件仍逐字相同、片段仍包含于归档脚本、进度仍被最终summary覆盖，且全部清单身份不变。原文件未通过归档校验前不得删除；中断保留原件，已验证归档和已完成清理记录保留，不自动重跑。发生异常立即停止，按逐项记录判断剩余动作，不能将业务staging作为清理对象。

性能预算仅涉及本报告约77.7MB的文本证据，含原件读取、压缩回读、保留文件前后摘要核验及最后文档验收：预计读取不超过256MiB、写入和额外空间各不超过80MiB。中断后如需继续，先核对逐项记录，未完成项和最后验收另预留相同上限；这不是新增行情读取或正式任务运行限制。无需性能测试。

验收条件：28份冗余文件按清单消失；三份gzip与原内容SHA256和字节数一致；其他保留文件摘要不变；报告Markdown本地链接有效；原110项完成、2项未完成的结果未修改；无本步临时归档和/private/tmp辅助脚本遗留。清理动作、压缩映射、清理前后尺寸及验收结果另存本步清理结果，不覆盖第38节历史记录。先完成本文和清单，再实施清理。

## 42. 暂停后的清理执行结果

按第41节及清单执行完成：删除28份冗余文件、572,183B；三份身份/输入证据原71,410,110B无损压缩为4,628,883B，压缩过程中逐份解压核对原字节数及SHA256完全相同，再移除未压缩副本。其他196份保留文件前后SHA256一致。压缩与删除共减少67,353,410B，约64.2MiB，新增清单和本节记录另计。

压缩后的证据：[MACD日更文件身份（附件已清理）](README.md#报告附件清理2026-11-01)、[MACD repair文件身份（附件已清理）](README.md#报告附件清理2026-11-01)、[九转输入身份（附件已清理）](README.md#报告附件清理2026-11-01)。历史验收JSON和执行脚本内的原文件名保留其历史含义，查看原JSON或重用归档脚本前，应先按映射解压还原；本步没有重跑脚本。完整原名、尺寸、SHA256和删除明细：[本步清理结果（附件已清理）](README.md#报告附件清理2026-11-01)。

正式Lake和全部业务staging、冻结输入、operation、receipt、checkpoint、THS失败现场均未修改或删除；最终对账、源核验及非重复执行日志保留。本轮补数保持暂停，结果仍为2026-10-23完成110项、THS Raw/Silver两项未完成，两个股票sensor仍停止。本步未触发job或sensor、未请求源端、未读取行情或重新审计数据。

清理后仓库文档完整性三项检查通过，本报告53个Markdown本地链接全部有效，最终对账文件摘要不变。28个删除路径已确认不存在，三份归档在位，无本步临时归档或/private/tmp下dg23辅助文件遗留。独立只读复核确认计划与结果清单、保留边界和归档映射一致；没有重复解压大证据或再次核查业务数据。


## 43. 恢复自动任务及文件收尾方案与LLD（2026-10-27）

管理员明确要求将之前补数工作收尾，清理无用临时文件并打开此前关闭的sensor。本节为本次正式状态修改和文件删除的执行依据。23日股票链及两类repair已由第31/35/36节验收；THS两项与它们无输入依赖，仍单列未完成。本次新授权允许恢复股票自动链，不再等待THS两项恢复；不能据此把110/112改成112/112，也不重做23日/26日全局审计或补数。

**精确状态范围。** 只恢复第5节和22日报告第39节曾停止的`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`、`gold_stk_mins_qfq_nineturn_update_job_sensor`，顺序为MACD状态恢复/读回，再九转状态恢复/读回。既有origin/selector必须分别匹配当时停用记录，类型必须SENSOR；已经RUNNING则只记录，不重复操作。其他STOPPED、schedule、daemon、资源和并发配置不变，不重置任何cursor或run_key。两条无THS输入；九转源码并不直接等待MACD，不把开关顺序说成新增业务依赖。

实现依据为当前两sensor、原事件/前序检查/factor gate及本机Dagster1.13.26的`GrapheneStartSensorMutation → start_sensor → instance.start_sensor`。已有SENSOR状态使用原`data.with_sensor_start_timestamp()`，保留原cursor/lastRunKey，只正常更新启用状态和启动时间；不创建新state、不写回旧cursor。启用后daemon可按现行策略处理积压或后续日期，此为恢复自动化的正常影响，本步不手工触发job、repair、sensor预演或重新执行。

**命令和核验。** 工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，正式服务`http://127.0.0.1:3000`，正式实例仍`/Users/congming/.goldenshare/dagster_home`。用现有`.venv/bin/dagster-graphql --remote ... --file ... --variables <JSON>`，只提交`startSensor(sensorSelector: $selector)`；selector固定`orchestrator/__repository__`及上述单个名称。请求文件存`/private/tmp/dg-backfill-closeout-20261027`，原状态及响应归档本报告的`operational-closeout-20261027/`。

先只读查询两状态的id/selectorId/instigationType/cursor/lastRunKey，再逐个start，立即保存返回状态并核原身份/原进度，最后只读查两项均RUNNING。CLI远端模式的stdout按实际Python字面结果解析保存为JSON，不能只传未生效的`--output`并引用不存在的文件。若响应不确定或第二项失败，先查已有状态，不盲重发、不停止已成功启用的项。daemon自然推进cursor与人为清空不同，出现变化先核正常tick，不把旧cursor写回覆盖。

**精确清理和归档。** 已核10个/private/tmp下dg22脚本/SQL与22日归档逐字相同，6个公告verify.out与保留JSON解析内容相同，合16项51,355B；按精确清单身份(dev/ino/size/mtime/ctime)与内容再次核对后删除，禁止通配删除。公告本轮两个只读辅助.py先逐字归档为.py.txt再列入清理；失败启动留下的空日志、空version.json和旧pid文件在确认非当前活动日志/进程记录且无引用后单列清单处理。最终删除以实际清单和结果为准，不自行扩至其他临时目录。

公告正式补数的已有验收JSON、请求/config及必要只读源码另存`lake_console/reports/anns_d_recovery_20261027/`作长期证据；当前DG活动`dg-start-session.log`及其工作会话保留，不能移动/删日志来干扰服务。此前引用但未实际落盘的CLI --output路径只修正文档为现存验收报告，不伪造原始响应。新补充归档先写独占目标，核小文件内容一致后才删对应临时脚本；已有执行事实不改写。

所有正式Lake、业务staging、冻结输入、operation/receipt/checkpoint/budget、THS失败现场、最新26日只读审计报告、唯一compute.out和其余有效报告保留。已核共享DuckDB临时目录顶层只有原有index_daily_p3且无本轮散落工作文件，不删除共享目录，不再次解压/读取大证据。清理不接触正在自动运行的新job现场。

本步没有行情/源端数据读取；控制查询和2次必要状态变更、小报告归档、重复小文本对比及收尾总预算读8MiB、写4MiB、额外空间4MiB，失败后余项和验收另预留同额。删除/归档逐项留记录，异常立即停该步，已删除项按已验证归档查看，不自动恢复业务文件或重跑数据。验收包括两状态读回、原身份/进度保留、精确删除路径不存在、归档可读、原TODO关闭、原结果/THS待办保留、文档完整性及本轮本地链接检查。无代码开发和额外数据测试；执行结果另记第44节。


## 44. 恢复开关与清理的执行结果（2026-10-27）

本节落实第43节，未进行数据补齐或行情审计。2026-10-27 12:21正式GraphQL读回两项原sensor均RUNNING：

| sensor | 操作前 | 操作后 | 原身份及启动时进度 |
| --- | --- | --- | --- |
| `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor` | STOPPED | RUNNING | 原id/selector、cursor、lastRunKey保留 |
| `gold_stk_mins_qfq_nineturn_update_job_sensor` | STOPPED | RUNNING | 原id/selector、cursor、lastRunKey保留 |

两项均使用原生startSensor逐项恢复并核响应，未新建状态或重置cursor；最后再次查询均RUNNING。其他开关/并发修改0、手工job/repair启动0。daemon此后可以按原策略处理历史成功事件和待补日期，正常推进cursor不是本次人为清空或回退，不承诺本轮开关恢复已自动完成26日缺失。证据：[开关汇总](operational-closeout-20261027/sensor-restoration-summary.json)、[操作前（附件已清理）](README.md#报告附件清理2026-11-01)、[MACD启动响应（附件已清理）](README.md#报告附件清理2026-11-01)、[九转启动响应（附件已清理）](README.md#报告附件清理2026-11-01)、[最终读回（附件已清理）](README.md#报告附件清理2026-11-01)。

12:23按[精确清单（附件已清理）](README.md#报告附件清理2026-11-01)删除21项、65,411B，全部目标已核不存在，详见[逐项结果（附件已清理）](README.md#报告附件清理2026-11-01)。其中10个dg22脚本/SQL与原归档逐字一致，6个公告verify.out与保留JSON解析内容一致，2个公告只读.py已逐字归档后删除；其余为失败初次启动遗留的两个空文件和旧pid文件。没有按通配符删除目录，没有删除有效请求/config/报告、唯一compute.out、共享DuckDB目录或正在运行DG的日志。

公告正式补数现存证据29份、68,200B已逐字复制到[公告长期归档](../anns_d_recovery_20261027/README.md)，两只读脚本以.py.txt保存。原临时目录中活动dg-start-session.log和有效历史报告仍保留；不会移动活动日志或伪造未落盘CLI响应。正式Lake、全部业务staging、receipt/checkpoint/budget、失败现场及三份原压缩身份证据保持，未再解压/重审。此前第42节的28项删除与约64.2MiB压缩清理仍为原历史事实，本次21项另记，不重复累计已删除文件。

23日最终仍为110/112，THS两项和NULL/NaN核验待办保留；本次只关闭sensor恢复待办及无用临时文件清理。原22日报告、QFQ LLD及九转方案/LLD的当前状态同步更新，历史STOPPED记录保留为当时事实。文档完整性、变更文件空白及本轮本地链接核验结果见`operational-closeout-20261027/validation.json`；不以文档验证代替数据检查。本轮收尾文档和证据未另行提交。


## 45. 源端字段更新后补23日、26日THS：方案与执行LLD（2026-10-27）

管理员最新批准“先补23日，再补26日”，承接上一轮THS三只股票字段源核验。本步范围仅同花顺个股资金流Raw/Silver，顺序固定`23日Raw → 23日Silver → 26日Raw → 26日Silver`，每步原job及原blocking check通过后才推进下一步；不包含26日股票MACD/KDJ、state、九转或其他数据集。无开发、配置定义/资源限制修改、测试、额外全市场源预审或全局数据审计。

**现存证据及代码。** 10-27 12:44三次定向MCP复核显示23日三股原12个NULL值现均有数值，13字段全部非空；这只证明三条源样本，原Raw job仍须验证当日全市场。12:50只读预检两日期`cn_a_moneyflow_ths_trade_days`均已注册，四目标均不存在，无活动资金流run，Lake/staging同设备/可写，空闲约2.90TB。旧23日/26日失败run和源页原样保留；这是源已更新后的新采集意图，使用新run，不能复用旧NaN候选或改写旧失败记录。

当前实现为`jobs/moneyflow_ths.py`、`assets/moneyflow_ths.py`、`io/moneyflow_daily_update.py`、当前collector、`asset_guards/moneyflow_row_count.py`、原Raw/Silver checks。已用CodeGraph和当前源码核实入口及调用链，无契约或业务逻辑变化。原上界为每轮20,000行、页大小2,000、两轮累计64请求，间隔至少60秒；两轮与Raw提交前共用300秒原预算，并非整个job超时。本节同步纠正旧§6/15容易被理解成“每轮64请求”的表述，不增加任何新限制。

每个Raw由原job完整分页两轮，13字段/主键/有限数值/两轮集合一致通过后才发布。它按严格早于目标日的最近五个已物化Raw日期检查原Mat/check/SHA/行数，不能跳过坏基线；不足五个才按原2026-09-30回退，中位数下降阈值20%保持。23日前五日为16/19/20/21/22，五文件stat约1.59MiB；23成功后26基线自然纳入23，不手拼或冻结旧五日名单。原始核验由job执行，不另做重复正文/SHA读取。已有正式文件由原协议比对后复用或原子替换，不改变writer行为。

Silver只消费同日刚通过原检查的Raw，绑定原物化SHA，将trade_date转DATE并逐字段对账；无源请求。两层各一个原job/一个原blocking check，共目标4条物化/4项原检查。没有股票复权计算或repair需求，不调用无关repair job。

**原job触发及状态。** 工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，正式DG `http://127.0.0.1:3000`及原`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`；通过现有`.venv/bin/dagster-graphql --remote ... --file <launch.graphql> --variables <JSON>`提交`launchPipelineExecution`至原队列。selector固定`orchestrator/__repository__`，job为`raw_tushare_moneyflow_ths_update_job`或`silver_moneyflow_ths_update_job`，runConfigData为空对象，executionMetadata仅`dagster/partition=目标日`，不生成额外source_proof或人工写入数据。完整请求及响应放`ths-recovery-20261027/`；远端CLI stdout显式捕获并解析保存JSON，不依赖未生效的--output。

每次提交前复核同日/同job是否已被自动执行；有活动run则跟踪，有本轮有效成功/原check则复用而不重复提交。当前THS sensor均按22:00窗口，实际启停/最近tick另作最小只读记录，不为人工任务改开关。共享moneyflow_tushare_writer pool及writer.lock保持，其他任务冲突等待或按原错误停止，不提升并发。

**读写及预算。** 仅两个目标日全市场13字段源数据、各自原最近五日Raw小基线和原检查；不读年度或全历史价格。依近期每个Raw约5,217行/0.32MiB，正常每日期两轮预计6次源请求，两日约12次；Raw原累计64次保护按各run独立，不将理论128次当作预计。预计每文件≤2MiB，正常四job含两轮、基线校验、原checks、日志和唯一收尾保守读128MiB、写64MiB、额外空间128MiB；如失败需限定剩余恢复，另预留同额，不能自动重跑。预算不是新进程/IO硬限制，不加外部timeout，不做性能测试；预计源端正常共数分钟加原队列等待。

仅正式目标为两日`raw/tushare/moneyflow_ths/trade_date=.../part-000.parquet`及`silver/moneyflow/moneyflow_ths/trade_date=.../part-000.parquet`。全部候选/两轮来源/proof/receipt/promotion CP在原`/Volumes/datasource/data_lake_staging/moneyflow`。先完成本节并核当前输入，再正式执行。任一失败立即停后续层及26日；保留已提升文件、原staging与事件，不填0/改NaN检查/删除旧现场，也不临时开发绕过。恢复前先按原root及receipt判断未完成范围和合法原生重执行方式，本次不默认第二轮整批采集。

**验收和收尾。** 每run仅核原生SUCCESS、一条本日物化、一项passed原检查及storage_id/run_id/timestamp绑定，复用metadata/原receipt统计及目标stat；不再读Parquet明细/重新计数或SHA。Raw receipt确认两轮稳定、原row_count_guard通过、实际基线/请求；Silver原逐字段对账通过且行数同本日Raw。本轮辅助程序只编排与只读收尾，不计算补数。完成后原23日112项按最后两项成功销账；26日只销本次两项，不据此宣布其他指标齐备。最终结果写§46，失败则明确日期/原reason、已写入和未执行步骤；新辅助临时文件归档后清理，不删除业务staging。


## 46. 23日THS首次新采集失败，按顺序停下（2026-10-27）

按第45节已提交且只执行一次`raw_tushare_moneyflow_ths_update_job`，目标2026-10-23，run `dc3610ed-1645-4ee4-8747-7986646bb2d5`，12:52:58—12:53:02原生终态FAILURE。失败发生于原数值合同校验`source_numeric_contract`，尚未形成候选发布/物化；零物化、零AssetCheckEvaluation。原错误为以下三个样本的net_d5_amount被识别为NaN，retryable=false；没有手工填0/改检查、修改代码、重新运行或用新root反复尝试。

| 本次报错股票样本 | 源MCP同日记录 | net_d5_amount | 三个净流入占比字段 |
| --- | --- | --- | --- |
| 301683.SZ 慧谷新材 | 存在，1条 | null | 均null |
| 603955.SH 大千生态 | 存在，1条 | null | 均null |
| 002403.SZ 爱仕达 | 存在，1条 | null | 均null |

12:54只对本次报错三股分别调用MCP一次，限定20261023及13字段，得到上表，未重查全市场。原三股688368.SH/300687.SZ/301448.SZ于12:44确有值的结论保留，但只能证明那三条样本，不能当作当日全市场字段齐备。代码`io/moneyflow_daily_raw_writer.py:129`明确错误样本采用LIMIT 3，所以每次报错只列三个样本，不能解释成全市场仅三只股票有问题。

本次MCP返回JSON null，当前Raw失败记录为NaN；现行数值合同`run_contracts/moneyflow_daily.py`明确允许JSON NULL，NULL与NaN不应混为同一值。具体在源SDK、DataFrame或序列化哪一步转换，尚未由本次三个MCP响应证明，不能把等待源站更新说成唯一解决办法。后续正式补数前，需先核清/处理这段空值传递，或确认源端所有受影响记录均已补全；本轮不临时开发、放宽合同或把NaN当0。

按既定顺序，23日Silver、26日Raw/Silver三步全部未启动。12:54精确stat确认两日期四个正式目标均不存在：本轮正式数据写入0，失败staging/源页及旧失败run全部保留。23日仍110/112；26日未补，亦未对其他数据集作新完整性判断。未改开关、cursor或并发，后台其他正常自动任务保持现状。

证据：[本次执行汇总（附件已清理）](README.md#报告附件清理2026-11-01)、[原生失败及原因（附件已清理）](README.md#报告附件清理2026-11-01)、[三股新源样本（附件已清理）](README.md#报告附件清理2026-11-01)、[四目标最终stat（附件已清理）](README.md#报告附件清理2026-11-01)、[原三股已补字段证据（附件已清理）](README.md#报告附件清理2026-11-01)。这些记录是本轮失败收尾，不把准备好的四份请求文件当作四次已执行。本轮没有临时执行脚本或测试数据；只读核验源码作为.py.txt保留本报告，不删除任何业务现场。文档及链接验证另记本目录validation.json，未另行提交。

## 47. 再次采集23日、26日、27日THS：方案和执行LLD（2026-10-28）

管理员本轮明确批准“先补23日，再补26日和27日，通过job按Raw、Silver顺序推进，不做不必要的全局审计”。本节复用第45节当前代码、原入口和验收方式，将精确顺序扩为：`2026-10-23 Raw → Silver → 2026-10-26 Raw → Silver → 2026-10-27 Raw → Silver`。目标仅两资产的三日分区、六个正式文件和六项原检查；不改代码、合同、配置、sensor、cursor、并发或其他数据集，不执行repair、runless event或额外全市场预审。

**输入依据和风险。** 10月28日14:17已通过MCP限定23日六只已知异常股票逐只核验：原三只及后续三只的13字段均有值。这只证明六个样本，不证明全市场无其他缺值。原第46节的NULL/NaN区别及旧失败事实保留；本轮以源已更新和管理员新授权提交新采集意图，不读取或复用旧失败源页。原job若仍因其他NaN或任何合同失败，立即停止后续步骤、保存原原因，不放宽检查、不人工补值、不自动重试。

**代码和影响面。** 已复核`defs/jobs/moneyflow_ths.py`两独立selection、`defs/assets/moneyflow_ths.py`及第45节的原writer/check链；每层只执行自身资产和一个blocking check。Raw仍完整采集两轮，使用原分页、稳定间隔、日期/字段/主键/有限数值和行数门禁；最近五日基线由原job自然选择，后续日期纳入本轮前日已通过Raw，不手工指定。Silver只读同日已通过Raw，标准化日期并逐字段对账，行数和Raw摘要绑定由原job/原check保证，无新增源请求。

**执行命令、身份和预检。** 工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，正式实例`/Users/congming/.goldenshare/dagster_home`，正式服务`http://127.0.0.1:3000`。先只读确认三日期在`cn_a_moneyflow_ths_trade_days`已注册、六目标现状、Lake/staging挂载可写且同文件系统/空间足够，并有界查询同日同job的活动/最新任务及原服务响应。已有活动任务跟踪原run；已有本轮有效成功及检查则验收复用，不重复提交。不创建或注册分区，不为补数改开关。若必要前置不满足，停止汇报。

实际启动沿用`.venv/bin/dagster-graphql --remote http://127.0.0.1:3000 --file <launch.graphql> --variables <对应JSON>`及原`launchPipelineExecution`，selector固定`orchestrator/__repository__`和`raw_tushare_moneyflow_ths_update_job`或`silver_moneyflow_ths_update_job`，`runConfigData={}`，执行tag仅`dagster/partition=目标日`。请求/响应逐步保存到本报告的`ths-recovery-20261028/`；不使用会在本地进程直接跑job的`dg launch`，不编写计算或写湖脚本。只读结果核验复用第45节核验程序，唯一范围调整是允许27日；只读查询正式数据库，不初始化instance。辅助脚本暂存`/private/tmp/dg-ths-recovery-20261028/`，最终逐字归档为`.py.txt`后删除本轮临时脚本。

**读写和性能预算。** 正式输入仅三日全市场13字段、各Raw原最近五个小基线及原检查；不读年度或全历史。按既有每日期约5,200行/Raw约0.32MiB，正常每日期两轮预计6次源请求，三日约18次；保留原单run累计64次及20,000行/轮门禁，不新增进程/内存/IO或超时限制。三日六job连同基线、原检查、日志和一次必要收尾保守预算读192MiB、写96MiB、额外空间192MiB，预计数分钟加原队列等待。若中断，先只读核已完成范围和原receipt，未完成范围恢复及最后验收另预留同额；该预留不授权自动重跑。共享writer pool和锁保持原样。

正式路径仅`/Volumes/datasource/data_lake/raw/tushare/moneyflow_ths/trade_date=<目标日>/part-000.parquet`和`/Volumes/datasource/data_lake/silver/moneyflow/moneyflow_ths/trade_date=<目标日>/part-000.parquet`；候选/源页/receipt/checkpoint仍由原job写`/Volumes/datasource/data_lake_staging/moneyflow`。失败保留正式已提交文件和全部业务staging，不删除旧失败现场、不回退已成功数据。响应不确定先查原run，禁止盲目再次提交。

**验收及结束条件。** 每步仅核原生SUCCESS、同日正确资产的一条物化、一项passed原check及其storage_id/run_id/timestamp绑定、目标stat和已有小receipt；Silver另核行数和Raw摘要匹配。复用原检查，不另读Parquet正文、重算计数、摘要或再做全局审计。每步通过才推进下一步。六步均通过则报告三日Raw/Silver行数、run和检查；失败则明确已完成/未执行范围及原原因。最终操作和结果追加本报告下一节，不据这六步重新宣称其他日期/其他数据集的完整性。

## 48. 三日THS恢复本轮执行结果：23日Raw失败，后续未启动（2026-10-28）

14:22只读预检确认三日分区已注册、六个正式目标均不存在、无活动THS任务，Lake与staging同文件系统且余量约2.90TB；正式DG版本响应为1.13.26。随后只通过原GraphQL入口提交一次23日Raw，run为`a5701719-9435-4d51-9150-c29b7d4590b8`，14:23:02—14:23:06原生终态FAILURE，错误为`source_numeric_contract`、retryable=false。未修改源请求、合同、代码或运行限制。

原错误样本为`605333.SH/net_d5_amount/NaN`、`603203.SH/net_d5_amount/NaN`、`300503.SZ/buy_lg_amount_rate/NaN`。只对这三个代码、23日和原13字段各追加一次MCP查询，未全市场预审：

| 23日报错样本 | 本次MCP仍为空的字段 |
| --- | --- |
| 605333.SH 沪光股份 | net_d5_amount及三个净流入占比字段，共4项 |
| 603203.SH 快克智能 | net_d5_amount及三个净流入占比字段，共4项 |
| 300503.SZ 昊志机电 | 三个净流入占比字段，共3项；net_d5_amount已有值 |

前次已知六只股票的字段已补全仍是有效的定向样本结论；它不能代表全市场已经无空值。当前三个错误同样仅是原`LIMIT 3`显示样本，不是全市场异常股票总数。源MCP为JSON NULL、本次正式job报NaN；原合同允许NULL而拒绝NaN，这两者不能混写成“所有空值非法”。从源到当前job在哪一步转换仍需单独核清，本次没有临时放宽合同或开发绕过。

| 日期 | Raw | Silver |
| --- | --- | --- |
| 2026-10-23 | 本轮执行一次，FAILURE | 未启动 |
| 2026-10-26 | 未启动 | 未启动 |
| 2026-10-27 | 未启动 | 未启动 |

14:24:41必要收尾只读确认该run物化0、检查事件0、六个正式目标仍不存在、无活动THS任务。故本轮正式Lake数据写入0；未将任何数据集标为补齐，未触发剩余五步、repair或全局审计。原失败staging/源页和全部旧失败现场保留，不自动重跑、不越过23日推进后续日期。六份variables只是预先准备的请求文件，不是六次执行。

证据：[执行汇总（附件已清理）](README.md#报告附件清理2026-11-01)、[执行前状态（附件已清理）](README.md#报告附件清理2026-11-01)、[实际启动响应（附件已清理）](README.md#报告附件清理2026-11-01)、[原生失败原因（附件已清理）](README.md#报告附件清理2026-11-01)、[三个报错样本的源响应（附件已清理）](README.md#报告附件清理2026-11-01)、[最终状态及零物化检查计数（附件已清理）](README.md#报告附件清理2026-11-01)、[前次六个已知样本已补字段（附件已清理）](README.md#报告附件清理2026-11-01)。本轮三份只读辅助源码归档为`.py.txt`后精确删除临时脚本，保留请求/响应及业务staging；清理和文档验证见本目录`cleanup-result.json`、`validation.json`。没有提交代码或部署。

## 49. 仅补23日、26日THS：本次方案和执行LLD（2026-10-29）

**授权与固定顺序。** 管理员明确要求“先补23日和26日，按日期依次通过原job执行Raw、Silver，27日先等源站修复；不要做不必要的全局审计，遇到新的问题就停下汇报”。本步严格为`2026-10-23 Raw → Silver → 2026-10-26 Raw → Silver`，每步原job SUCCESS、1物化及1项准确绑定的原blocking check通过才继续。27日不提交、不改开关；不改业务代码、契约、参数、并发或资源限制，不调用repair、runless event或直接写湖程序，不重跑全目录审计。

**来源依据。** 本日14:02—14:03的11次定向MCP核验显示，23日最后3条失败样本、26日原失败3条样本均13字段非空；27日森鹰窗业4字段仍NULL且三次一致。范围仅9个日期/股票样本，不能证明23/26日全市场无其他缺值。原请求、响应及26/27日原失败记录归档本次`ths-recovery-20261029/`，不再次全市场预审。当前是源更新后获准的新采集意图，使用本次新run，不复用旧失败来源页或覆盖旧失败状态。

**当前代码与复用。** 沿§45/47及本日CodeGraph、原代码/收据静态独立核验：`jobs/moneyflow_ths.py`各自只选本层和1个check；`assets/moneyflow_ths.py`、`io/moneyflow_daily_update.py`及原Raw/Silver检查不变。Raw仍完整两轮、间隔至少60秒、两轮合计最多64请求、每轮20,000行，以及原近五个已物化Raw基线/20%下降门禁；26日基线由原job自然纳入新23日，不人工拼基线。原writer空间门禁为64GiB，预检只确认当前实际余量满足它，不改限制。Silver只读同日已绿Raw，日期标准化并逐字段对账，其原物化SHA必须与本日Raw一致。正式源请求与价格/业务校验全由原job执行，辅助入口不重读Parquet正文或SHA。

**正式入口、唯一触发和预检。** 工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，既有`.venv`，`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，正式GraphQL `http://127.0.0.1:3000/graphql`。沿前次已成功提交的`.venv/bin/dagster-graphql --remote ... --file <launch.graphql> --variables "<变量文件的完整JSON文本>"`、`launchPipelineExecution`和原两个job，selector为`orchestrator/__repository__`，runConfigData空，tag仅本次目标`dagster/partition`。不使用`dg launch`本地另跑。请求/CLI原响应与解析JSON逐步保存在本次目录；提交前保存唯一intent，未知响应先查原run，不重交。

复用§47的只读预检，日期允许集缩为23/26，四目标stat、27日两邻目标stat、注册/同日同job最近及活动run、正式Lake/staging同设备/可写和64GiB余量；只读原数据库，不初始化instance。其他数据集正常运行不作为阻断，也不关闭daemon。当前两自动sensor源码均先判断上海22:00，提交前确认仍在窗口前并无本次目标活动run；若跨入自动窗口或目标出现，先跟踪已有run并核其成功，不盲目重复提交或擅自停sensor。

**观察和成功条件。** 复用前次`verify-run.py.txt`的精确run事件、原小收据及stat核验，只改本次报告目录、日期白名单为23/26，并显式要求原check blocking。查询本run有限物化/check记录，核本日、资产、URI、行数、target storage/run/timestamp绑定。Raw收据stage/dataset/date对应本次moneyflow_ths、原row_count_guard passed、请求/稳定间隔及scope计数符合原合同；Silver另核行数和Raw SHA一致。观察器的`in_progress`也可能exit0，必须看`verification == passed`才继续，不能把进程exit0当job通过。失败取本次原reason并停后续步骤，不查旧固定run；任务观察超时不取消业务run或自动重交。

**预算、失败和清理。** 正式只读两个目标日全市场13列与原各5个小基线；按既有每日期约5,200行、Raw约0.32MiB估计，每Raw两轮约6次源请求，两日约12次；正常四job含原检查、基线、观察/收尾读128MiB、写64MiB、额外空间128MiB，预计数分钟加原队列等待。中断后状态核查、未完成部分及最后验收另预留同额，不授权自动重跑或新增外部运行限制，不做性能测试。

任何新源问题、检查失败或身份冲突立即停止后续步骤，保留正式已完成结果和全部业务staging/旧失败源页；不放宽NULL/NaN合同、不填值、不当场开发绕过。若两日期四步完成，仅核本轮4物化/4原检查/4文件stat及27日stat不变，不再计数或hash全市场。四文件只位于正式Raw/Silver路径；候选、来源页、receipt/checkpoint保持原staging协议。辅助只读脚本在`/private/tmp/dg-ths-recovery-20261029/`，最终逐字归档文本后精确删除；不删除正式数据、共享目录或失败现场。实际结果按本次run逐项追加下一节，不能预填完成。

## 50. 本次23日Raw出现新字段错误，已停止后续（2026-10-29）

按§49只提交了一次23日Raw原job，run `de3942e7-ebc1-44d8-896f-f8f5e4f039d4`，14:14:44—14:14:50原生FAILURE，约5.69秒。原reason为`source_numeric_contract`，retryable=false；这是正式job的数值校验失败，不是观察器超时或新运行限制。

| 本次原错误样本 | 字段 | 观察值 |
| --- | --- | --- |
| 603102.SH | net_d5_amount（5日主力净额） | NaN |
| 688073.SH | net_d5_amount（5日主力净额） | NaN |
| 603102.SH | buy_lg_amount_rate（大单净流入占比） | NaN |

这里是3条字段错误、涉及2只股票，仅为原LIMIT 3样本，不能称为全市场异常总数。上次定向复查的23日3股恢复有值仍然成立，但不能覆盖这两个新样本，也不能证明整日源已齐。当前证据是原job看到NaN；本次没有追加MCP请求，因此不把它直接写成源HTTP原文为NaN或NULL。原合同允许NULL，原SDK/DataFrame/序列化链的NULL与NaN区别仍须独立处理；本轮不开发、不放宽校验、不填值。

| 本次计划步骤 | 实际结果 |
| --- | --- |
| 23日Raw | 执行一次，FAILURE |
| 23日Silver | 未启动 |
| 26日Raw | 未启动 |
| 26日Silver | 未启动 |
| 27日 | 按要求未触发、未修改 |

14:16:20只做必要只读收尾：本次run物化0、检查事件0；23/26日四个正式目标仍不存在，27日两目标stat与执行前一致，无活动THS run。因此本轮未发布或替换任何正式Raw/Silver文件；失败来源页、全部原staging和旧失败现场保留。不自动重试，不越过23日推进26日，不继续查源或进行全局审计。

证据：[本次执行汇总（附件已清理）](README.md#报告附件清理2026-11-01)、[原run失败详情（附件已清理）](README.md#报告附件清理2026-11-01)、[执行前核验（附件已清理）](README.md#报告附件清理2026-11-01)、[必要收尾（附件已清理）](README.md#报告附件清理2026-11-01)、[此前定向源样本（附件已清理）](README.md#报告附件清理2026-11-01)。辅助观察脚本和预备变量按精确清单归档后删除，保留所有业务staging；未执行的3份变量只是预备材料，不是3次执行。[清理记录（附件已清理）](README.md#报告附件清理2026-11-01)。未改业务代码、配置、sensor或并发，未另行提交。


## 51. 三日THS恢复：本次方案与执行LLD（2026-10-30）

**明确授权及顺序。** 管理员批准按23日、26日、27日，逐日通过原job执行Raw→Silver；遇到新问题停止，不做不必要的全局审计。顺序固定为`2026-10-23 Raw → Silver → 2026-10-26 Raw → Silver → 2026-10-27 Raw → Silver`。只更新六个目标，保留其他日期、历史失败现场及运行状态；不改业务代码、合同、参数、并发/资源限制，不调用repair或runless event，不直接计算写湖。

**本次输入证据。** 17:17—17:21的[定向源复查（附件已清理）](README.md#报告附件清理2026-11-01)共20次请求，覆盖17个已知异常股日：23日11条、26日3条、27日3条，13字段均非空、10数值字段均有限。23日最后两股及27日森鹰窗业各重复一次，完整结果一致。这只证明已知样本恢复，不代表全市场完整；由原Raw job两轮采集和原检查做当日门禁，失败不自动重试。

**现行实现与边界。** 复用§45/47/49的原jobs、assets、Raw/Silver writer及检查：Raw每轮上限20,000行、两轮累计64请求、稳定间隔至少60秒、原300秒来源及提交预算、最近五个已物化Raw基线和原行数门禁；Silver只读同日已绿Raw并逐字段核对、绑定其SHA。使用现行512MB/一线程连接和writer pool/锁、原64GiB空间门禁，不新增外部进程限制或性能测试。source_numeric_contract失败仍如实停止，不将NULL和NaN混写、填0或放宽合同。

**执行入口。** 工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，原`.venv`，`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`。使用原`.venv/bin/dagster-graphql --remote http://127.0.0.1:3000 --file <本次launch.graphql> --variables '<对应变量的完整JSON>'`，原`launchPipelineExecution`，selector=`orchestrator/__repository__`，job=`raw_tushare_moneyflow_ths_update_job`或`silver_moneyflow_ths_update_job`，runConfigData为空、tag仅本次`dagster/partition`。CLI stdout按当前安装版本为Python字面值，保存原文后解析成JSON；不用本地`dg launch`、不初始化instance、不reload或重启服务。

**执行前与逐步操作。** 本次请求、原响应、验收记录存`ths-recovery-20261030/`。先只读确认正式workspace可用、两个原sensor状态、六目标stat、三日期已注册、同日同job最近及活动任务、正式Lake/staging挂载同设备/可写及64GiB余量；28/29日四个既有文件仅stat作为邻日保护，不读正文。当前原Raw/Silver自动入口在上海22:00前返回before_window；每次提交前再次确认未跨窗口且目标无活动任务。已有活动run跟踪、已有有效成功及原检查则复用；不清cursor、改开关或重复提交。每步先保存唯一intent，提交后以实际runId观察，不把QUEUED或进程exit0当作成功，未知提交响应先查原run、不盲目重交。

**只读辅助复用细节。** 复用`ths-recovery-20261029/preflight.py.txt`和`verify-run.py.txt`，仅调整报告目录、日期白名单加27日；原27日邻日不变断言替换为28/29日邻文件stat保护。最终状态不复制旧脚本固定失败run/only_new_raw等结论，改为读取本次实际已提交及已验收记录。连接正式DG PostgreSQL只读事务且不初始化表；单run查询原物化/check最多100条。辅助只做观察与小收据读取，所有业务数据生产由原job完成，不自行采集、计算或发布。辅助脚本以报告内`.py.txt`留证据，无需在临时目录生成执行副本。

**每步验收。** 需同时满足原job SUCCESS、准确日期和资产的1条物化、1项passed/blocking原check及target storage/run/timestamp准确绑定、目标文件stat有效。Raw读取原小receipt（≤2MiB）核dataset/stage/date、row_count_guard、两轮请求/稳定间隔和scope计数；Silver核与本次已验收Raw行数和SHA一致。不另读Parquet明细、重新计数或重算摘要。前一步通过才允许下一步。

**预算及失败处理。** 原三个目标日全市场13列、各Raw原最近五个小基线及原检查；约每日期5,200行、Raw约0.32MiB，两轮约6次源请求，正常三日约18次请求。六job及原检查、观察收尾预算读192MiB、写96MiB、额外空间192MiB，含必要收尾；中断状态核实及另获准未完成部分继续另预留同额，不授权自动重跑。任一新问题停止后续日期/层，记录本次原reason、实际已完成与未执行范围，保留已成功正式结果及全部业务staging。收尾仅六目标stat、原事件/receipt及28/29邻stat，不重做全目录审计或查询其他数据集；正式结果追加下一节。


## 52. 三日THS本轮执行结果：23/26日完成，27日新错误后停止（2026-10-30）

按第51节实际提交五步：23日Raw `3a1a3f22`、Silver `edc2eab7`，26日Raw `d8bc85f3`、Silver `0f505b49`均SUCCESS，各5,218行。四项原blocking check通过并准确绑定，Raw原两轮来源/行数门禁通过，Silver行数及Raw SHA一致。没有重新计算这些检查或额外读正文。

27日Raw `2cfc3cb5-e9f0-4a85-878c-86832182d120`在17:44:47—17:44:51原生FAILURE，原`source_numeric_contract`观察到`600109.SH/net_d5_amount/NaN`、`300396.SZ/net_d5_amount/NaN`、`688301.SH/buy_lg_amount_rate/NaN`，retryable=false。这是三条字段错误样本，不是全市场缺失总数；此前17条已知样本恢复的源结论保持，不扩展为完整市场已齐，也不将原job的NaN直接等同源HTTP NULL。

已按要求停止，27日Silver未提交，没有重试、放宽校验或追加源查询。必要收尾确认27日物化0、检查事件0、两正式目标仍不存在；23/26日四个成功目标保持，28/29日四邻目标stat不变，全部业务staging保留。原sensor/并发未改，没有全局审计、直接写湖或runless事件。完整[本轮执行记录（附件已清理）](README.md#报告附件清理2026-11-01)、[汇总](ths-recovery-20261030/execution-summary.json)及[最终只读状态](ths-recovery-20261030/final-state.json)保留实际五个run和未执行边界；本轮未另行提交。
