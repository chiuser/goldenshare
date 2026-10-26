# 股票技术因子第三批开发与验收记录

依据：技术方案§13.5、LLD§5.1/5.4/6/8/9/11/16及管理员批准的七步执行计划。当前工作区为dev-interface。以下记录隔离开发证据，不表示已完成正式接入或执行。

## 本批范围与执行约束

仅实现本数据集的历史合同、规划、完整历史下载、候选、纯检查与逐日两层发布；不接入Prod bootstrap、正式PG读取、覆盖evaluator、job/repair、sensor、catalog或历史事件补录，不修改公共下载器、源字段契约、已有数据集或运行配置。

| 顺序 | 必须实现并证明 | 禁止及失败边界 | 代码落点与验收 |
| --- | --- | --- | --- |
| 1 | 冻结类型；规范业务摘要；plan/ranges/manifest/source记录交叉读回 | 拒绝错类型、缺/多字段、越界/符号链接、错run、错摘要；helper不创建连接 | run_contracts/stk_factor_pro.py、io/stk_factor_pro_history.py；类型与记录正反测试 |
| 2 | 可信最早日期；T/P完整对应；合入原未完范围；持久完整名单 | 不默认上市日；不裁短可信边界；不因因子回等删除未完；未知留存 | io/stk_factor_pro_history.py；一次有界MIN、缺T/P、新股与未知样本 |
| 3 | 从完整名单判定实际expected_units；原T Raw齐备、Silver有效；三处再核输入 | 不把全名单数量当unit数；未知时零历史请求；无工作不建零unit任务 | 同一历史模块及下载/发布入口；输入变化与独立成功范围反例 |
| 4 | 原生BY_OBJECT_RANGE；完整unit保存、读回、释放；全部session成功后才源完成 | 半unit、错股、超范围、关闭失败、旧run源不得发布；不重试业务写入 | io/stk_factor_pro_download.py；真实planner身份、关闭与保存故障测试 |
| 5 | 全部源完成后按20个交易日物化批源；逐日Raw→Silver | 只发布d<T；不逐日回读全部历史源；不改变无关股票；所有退出清表 | candidates/publication/checks；1/20/21/41/45日、节假日与提前关闭 |
| 6 | 仅按本次expected_units计算未刷新旧键；保存差集；最终再核后范围完成 | 缺旧键保留旧行和有效新行但不能完整成功；无文件不造check；物理完成不等于run成功 | 同一发布记录与检查；缺键、skip和完整范围结果测试 |
| 7 | 前两批回归、独立审计、真实保存样本及有界成本记录 | 不新增真实源请求，不跑全市场/17股全历史/内存压测，不推进第四批 | 本报告逐项列明通过及未覆盖边界 |

每步实现、测试与代码核实通过后才推进下一步。发现设计冲突先停止受影响步骤，交管理员review；不能靠另开连接、删校验或新增依赖绕过。

## 已批准的接口补充

历史源verify新增必填connection，下载完成及发布前均使用调用方现有的同一主要连接；实际读取manifest及源Parquet核schema、行数、代码、日期和SHA。方案§13.5与LLD§5.4.1已同步。

plan writer负责新ranges文件实际SHA，以replace生成并返回最终冻结plan；业务摘要必须预先匹配，不改写旧plan/ranges。该写入职责与既有返回类型已在LLD§5.4.1说明。

## 成本与验证上界

正常下载C股各完整范围，网络unit数为C；保存C个完整261列源文件及一个manifest。设发布日期D，批源查询固定ceil(D/20)，每批最多20日、40个日期/层目标；Python只持当前unit及小型记录，旧全市场关系只持当前日期。SHA/完整核验的额外读回单独计数，不包装成全程序只读一次。

故障后新run重新下载原完整范围；原源文件保留作证据，不作为新输入。最终读回、SHA、候选、原子替换、记录写入、临时关系清理与峰值空间均需计成本。性能样本为一股至多20个交易日，加一份接近全市场宽度的日期文件；边界批次采用小型样本。复用第一批保存的一股五日真实响应，不新增Tushare请求。

## 当前验收状态

第1步通过。类型/摘要28项、独立记录边界27项、记录IO25项，加相关基础/候选/发布146项，合计226项通过（25.09秒）。两个生产文件及对应新增测试默认Ruff通过。独立审查修正了记录SQL依赖物理顺序的问题，现按ts_code/unit_key显式排序；plan/source完整执行身份交叉检查、当前registry合同、12列ranges/17列manifest、合法零行schema、实际文件错字段/代码/日期/主键/数值/行数及符号链接反例均已验证。

第2步通过。起点13项、名单规划24项及独立规划边界9项通过；连同第1步合计126项通过（3.01秒），Ruff通过。根代理逐项阅读规划实现，核对FULL OUTER对应、原pending因子回等仍保留、repair原授权不扩大及revision规则。

起点测试证明只对缺依据代码执行一次批准日期范围内MIN；可信更早日期保持，缺批准文件/坏日期拒绝，查无行保持未知。规划核真实Raw因子3列及非空/正值/日期/唯一键/行数/SHA。新股夹具曾将整个P文件设为空，违反现行Raw因子blocking check；已依据真实生产者检查改为保留非空旁股，目标股仍P缺失，未放宽业务断言。可信start=T有上市证明可为原因6，start<T不得认作无历史。

第3步通过。完整8个history测试文件合计175项通过（4.59秒）。独立范围测试覆盖原A/B完整成功后新增C、A/B任一输入改变则整组重刷、未知项不可过滤、原因6免unit，以及坏成功字节引用/业务摘要拒绝；旧unit/manifest/candidate读取设双护栏。资格只消费已核冻结Raw/Silver事实，本批不查PG。

第4步通过。历史下载36项及根代理补充3项完整性/路径/清理测试合计39项通过（11.71秒）；纯历史源校验32项通过。相关history+日下载离线合并263项通过（14.37秒，明确排除一项localhost测试），该既有localhost假HTTP测试随后使用获准端口权限单独补验通过（2.01秒）：只用假token及127.0.0.1服务，真实Tushare请求为0。独立审查核原生mode5身份、关闭/summary顺序、全字段保存对账、逐unit释放及零网络拒绝，无新的确证问题。

清理故障回归先在修复前失败：DROP VIEW错误后未再尝试删表/解除注册；修复后39项通过，清理逐项尝试并保留最初业务错误。另反例证明同schema/行数/SHA生成流程不能掩盖保存值改变，交付时创建source父目录符号链接仍写前拒绝。

第5步通过。原日candidate/pub78项通过；新历史候选11项通过（1.12秒），显式d、B−K+U、无关股票261字段、内部关系名/DATE及路径正反例已核。独立批次10项首轮通过（84.39秒），清理实现调整后的受影响D1/close/fault5项复测通过（13.50秒）；自有发布15项通过（9.64秒），原日pub25项通过（23.06秒）。批源查询按1/20/21/41/45日分别为1/1/2/3/3次，45日按20/20/5处理；完整源核验和SHA读取另计。全部退出分支逐项释放临时关系，Raw交付后再处理Silver。

第6步通过。完整范围及独立边界、既有历史发布共30项针对性测试通过；补充PublishedTarget交叉约束及缺失计数说明后，受影响19项通过（22.52秒）。skip项不能带未刷新记录，scope_rows不能超过file_rows，零scope使用空内容SHA。仅核本次expected_units，原A/B已独立成功而本次只下载C时，不把A/B计入缺失。漏旧键仍保留旧行和有效新行、两层文件可通过自身检查，但最终抛可重试失败且没有publication-complete；Raw/Silver合计N是两层物理记录数，不是股票数。

物理范围完成前复核当前正式文件的实际SHA、逐文件记录、差集引用、当前源/名单元信息和第三次输入；不重复全源或全字段扫描，不自行写run成功。新run不得读旧源或旧候选，当前失败文件/名单保留作证据。第五批仍须根据DG最终producer成功事实决定哪些独立范围可跳过，并在捕获本批Failure后保存waiting观察。

第7步通过。最终本数据集530项、受保护启动器Definitions 1项/资产治理12项/运行合同静态门禁113项，合计656项通过，没有未解释失败。合并回归先得到527通过、2项在127.0.0.1假HTTP服务绑定时被沙箱拦住、1项既有localhost用例明确排除；获准本机端口后这3项均通过，断言未改，不跳过失败。完整输出见[final-regression.txt](final-regression.txt)、[localhost-regression.txt](localhost-regression.txt)，去重结论和代码SHA见[final-regression.json](final-regression.json)，保护门禁及测试SHA见[protected-regression.json](protected-regression.json)。合并回归168.95秒，包含所有小型批次边界用例；这个测试总耗时不当作正式业务耗时。18条既有Dagster preview/deprecation提示未影响断言。此前各步定向通过存在重复，不与656相加。


## 编码落点与正反验收对账

以下均位于本工程src/orchestrator/defs，测试位于tests；冻结资格输入与既有成功事实是本批测试边界，正式读取和run终态核验由第五批装配。

| 硬约束 | 实际实现位置 | 正反验收文件 |
| --- | --- | --- |
| 闭合历史记录/摘要、当前run路径、同一连接Parquet | run_contracts/stk_factor_pro.py::parse_stk_factor_pro_record及历史dataclass；io/stk_factor_pro_history.py::write/read/verify_* | history_contracts、history_contract_boundaries、history_records |
| 可信最早日期不裁短、缺依据一次批量MIN；完整T/P及旧未完 | history.py::resolve_stk_factor_pro_history_starts、build_stk_factor_pro_history_plan | history_starts、history_plan、history_plan_boundaries；未知B留名单且后续零请求 |
| 实际请求与完整名单分开、原T两层资格、三次输入再核 | history.py::resolve_stk_factor_pro_history_units、require_stk_factor_pro_history_eligibility、recheck_stk_factor_pro_history_inputs | history_scope、history_scope_boundaries；独立成功AB/新增C、任一成员修订、错误引用、未知整体拒绝 |
| 原生mode5、逐unit保存核全部字段及释放；完整关闭后才source-complete | download.py::download_stk_factor_pro_history、_save_stk_factor_pro_history_unit；checks/stk_factor_pro.py::require_factor_history_relation | history_download、history_download_integrity、history_source_checks；错unit/code/date、半unit、保存/关闭/清理错误、符号链接、旧run |
| 完整源后20日实物表、逐日Raw→Silver、T不覆盖 | publication.py::publish_stk_factor_pro_history、_load_stk_factor_pro_history_batch；candidates.py::build_stk_factor_pro_raw_candidate_from_relation | history_candidates、history_publication、history_publication_batches；1/20/21/41/45日、无关行、错日历、两层失败及提前close |
| 只计实际unit缺旧键；缺键保留文件但最终失败；skip无audit；完整物理事实不伪runSUCCESS | publication.py::_verify_history_published_targets、_finish_stk_factor_pro_history_publication；run_contracts::PublishedTarget/PublicationCompleteRecord | history_completion、history_completion_boundaries、history_completion_model；AB旧完整成功而只计C、单层缺旧键、元数据/目标变动、物理完成但producer失败 |
| 失败新进程重新下载原完整范围，无旧源/候选输入 | history_integration.py::test_real_process_exit_then_new_process_redownloads_complete_original_scope | 真实os._exit(17)及新OS进程，Python Path.open与SQL双护栏；完整五日1unit/5行重新请求 |

日分支由原contracts/foundations/download/candidates/publication/coverage/dagster_events测试回归；day/history字段互斥、日期源字符串/Silver DATE、合法NULL/负值及失败新下载未放宽。没有扩充公共源字段契约。

## 有界实际链路与成本

正常链使用第一批保存的000001.SZ、2026-10-12至16日5行261字段响应；目标T为16日，实际历史发布日期4天、两层8目标。实际组件的registry、planner、DownloadSession、重试和标准通知执行，只有HTTP transport由离线ScriptTransport代替，未接真实Tushare。一次1203错误后成功，2次transport调用、1个完整unit；RETRY_SCHEDULED/PAGE_COMPLETED/UNIT_COMPLETED均真实产生，普通observer异常一次被隔离，不用回调保存数据。

第一历史日预置5,568行列式Raw，只改目标股；5,567只其他股票在Raw及Silver全部261字段双向差异为0。T源行保留在源文件，正式T Raw/Silver哨兵SHA保持不变。批源最大4行、当前unit5行，旧Raw/expected最大5,568行；结束后临时关系全部清空。

| 场景 | transport请求/完整unit/源行 | 候选/正式替换 | 批源查询 | 实际墙钟秒 |
| --- | --- | --- | --- | --- |
| 正常宽日期链 | 2/1/5 | 8/8 | 1 | 3.7591 |
| 真实进程退出前 | 1/1/5 | 1/1 | 1 | 0.6764 |
| 新进程完整重下载 | 1/1/5 | 8/7 | 1 | 2.5806 |

正常链合计371条SQL、87次含Parquet查询、242次字节SHA（119,494,504字节输入）、20次JSON记录写入。查询次数不是底层IO次数；规划、下载、发布和独立测试读回分开记在JSON，另有30次仅用于测临时表规模的计数。测空间的遍历耗时约0.1393秒，也明确记录。

最终范围收尾单列2条SQL、43次SHA（10,915,317字节）、1次完整记录写入，约0.0334秒；其中正式数据文件只各追加一次字节SHA，其余是小记录引用，不重新读取全部历史unit或再次261字段JOIN。写入边界采样的正常总磁盘峰值11,003,789字节；staging/lake各自峰值发生时刻可能不同，不能将两者直接相加冒充同一时刻峰值。未采RSS，未做内存压测。

退出进程在source-complete和首Raw完成后以17退出，故意绕过finally；新进程使用新连接、run和内存状态，重新请求原股票2026-10-12至16日的完整范围，旧源和候选读取次数0。旧已发布Raw SHA保持，故新轮8份候选中该Raw等价不替换、其余7份正式替换。失败进程和重下载各自全部查询、SHA、空间与耗时均保留，不能只引用正常耗时。原始成本见[integration-evidence.json](integration-evidence.json)。

## 独立审计、文档及后续边界

两名独立审计代理只读复核七步合同→实际代码→正反例→证据，未发现剩余确证缺陷或需管理员拍板的业务项。实现前使用CodeGraph explore/impact/callers核入口、共用类型及发布依赖；构造函数调用索引不完整处另用全仓rg/实际源码确认。实现后codegraph sync/status显示根索引为最新。人工核验当前新增历史入口没有正式assets/jobs/sensors消费者，后续装配仍是独立批次；既有取消适配的get_run_by_id未改，不能把“本批未新增正式PG结果读取器”扩大解释为整个工程不存在PG调用。

本批修改的六个Python生产文件及全部新增历史测试默认Ruff通过；全src/tests致命Ruff、原方案/LLD文档检查和差异空白通过。已补connection签名、调用方finally关闭/保留主错误，以及实际计数和两文档当前状态。

结论：第三批通过隔离验收，具备制定第四批详细计划的条件。本轮未自动推进第四批、未提交或push，其他任务的工作区改动保持。正式Prod bootstrap、PG结果读取/evaluator、job/repair/sensor/catalog、动态分区、历史事件和自动化均未实施；真实10,000满页、17股全历史和正式PG事件未据本批证据宣称通过。后续实施仍按原方案的独立批准和验收顺序。


## d1564587提交后的清理修复与再审计

上文保留第三批原验收记录；之后独立审计发现历史记录模块4处清理的同一P2，按管理员批准先补方案及LLD§16.5，再修代码及回归。新增16项修前8失败/8通过、修后原样16通过；相关307项通过。只有一份生产文件修改，不改业务SQL、字段、范围、摘要、路径或下载/发布方式。

保存响应的正常链及真实进程退出后完整重下再次验证通过，正常SQL仍371条、批源查询1次，旧源/候选读取0；两路独立复核未发现新确定问题，清理P2关闭，第三批通过隔离验收。完整过程见[独立审计及修复收尾](independent-audit.md)、[本轮回归](cleanup-regression.json)、[本轮链路](cleanup-chain-evidence.json)。本轮修改尚未提交，不自动推进第四批或正式执行。
