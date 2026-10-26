# 股票技术因子第四批验收

更新：2026-10-27。依据：原方案§13.6、LLD§9～11及§17.8。范围：Prod bootstrap与本地缺口统计的隔离开发及五项修复，不是正式导出验收。当前结论：第四批五项修复已完成并通过隔离验收；40个普通文件868项、受保护门禁126项，共994项不同用例通过。正式Prod导出、写湖、分区、事件及自动化未执行；第五批未推进。

## 实现与交接

统一入口为`defs/bootstrap/stk_factor_pro_history.py`，按records/source/publication/coverage四个同目录模块分工。公共类型仍在原run_contracts、路径仍在原paths；复用现有来源转换、完整字段检查、Raw候选、Silver生成及代码覆盖纯函数。日更和历史的下载/失败重新下载行为不变。

本批实现完整批准输入、来源身份及计数核验、自然月named cursor、5000行批次、完整日回调、忠实Raw→Silver、逐文件恢复、全量缺失/额外代码与summary、补数后当前记录更新、最小活动检查及bootstrap分区注册能力。真实DG完成事实读取、授权及日更/repair接线仍属第五批。bootstrap内部已核当前发布输入不是运营参数；没有真实凭据不能用JSON事件编号猜检查通过。

## 硬要求逐项对账

| 要求 | 实现 | 验收证据 |
| --- | --- | --- |
| 完整批准/来源类型、关闭输入及摘要 | run_contracts bootstrap冻结类型；records read_json/write_json；source._approved_inputs | bootstrap_contracts、records：未知/缺字段、类型、日期、跨引用、摘要、批准边界反例 |
| 原实际全量首尾，不按当前股票池/2020裁切 | source.plan/validate及固定投影SQL | source：首尾裁切、漏月、多月、退市/早日期、count/schema/sample变化 |
| 每月只读named cursor、5000、R+1 | source.export/preflight；现有ProdPostgresResource | source：4999/5000/5001、只读协议、禁止fetchall/OFFSET、R−1/R/R+1先拒当前批 |
| 完整片段保存读回再释放 | candidates.write_stk_factor_pro_raw_fragment；records.fragment_from_relation | source/records：真实261列Parquet、主键/NULL/值/行数读回，跨批重复/逆序拒绝 |
| 完整日而非单批发布 | source._complete_day及同步callback | 同日跨批、同批多日；看到下一日期或EOF才关闭；0日只能EOF，半日不发布 |
| 原始导入忠实保存、Silver来自最终Raw | BOOTSTRAP_DAY_SOURCE强制prior=None；publication | publication/coverage：DATE/源字符串、负值/NULL、原少行合法导入、不同目标拒绝 |
| bootstrap独立恢复 | publication intent/complete，source-complete | 完整日复用、半日整日重读、Raw成Silver败、replace后checkpoint失败、旧源不覆盖外部变化 |
| 空源不造文件/事件 | SourceComplete.source_empty及process分支 | 源0开市/休市/未知，合法空事实、跨operation空源拒绝 |
| 两层发布及Silver绑定Raw | publication._publication_identity/_publish_layer | audit_regressions：错误Raw SHA首次/恢复拒绝，正确旧Raw等价复用通过 |
| 真实schema与四类依据 | coverage.prepare及必要物理规则 | coverage：日历单日未知、生命周期/身份/停牌坏输入、合法0停牌与缺文件分开 |
| 应有股票集合，不能只比数量 | 复用build_stk_factor_pro_coverage_keys | A/B对A/C仍缺B；别名/self有效期、上市/退市、北交所、全天/日内停牌 |
| 原传输与当前覆盖分开 | SourceComplete/PublicationComplete不变；DateCoverage/Summary当前字段 | 原2→当前3、原0且两旁各1→当前5，原源/原导入JSON逐字节不变 |
| 明细完整、未知不是0 | coverage.evaluate/write/summarize | 完整missing/extra引用；未知计数None；原源4800/导入4799不当缺股 |
| 原子记录与失败重入 | records.atomic_promote/write_json；coverage | 日期结果或summary失败保留业务文件；重试不累加；坏旧引用不放行 |
| 唯一operation和安全路径 | paths的bootstrap函数及records.operation_path | records/publication：绝对/..、双斜杠、符号链接、其他operation、候选越界反例 |
| 活动任务保护 | readiness两job五状态、每job limit2 | bootstrap：队列/运行/取消中拒绝、仅自身排除、读取异常零源请求；每次入口/首次提升最多4查询 |
| bootstrap只注册已确认开市日 | 主入口使用既定动态分区名称 | 全链临时依赖确认源0开市可注册、不删除已有键、不注册未知；Definitions正式图无提前装配 |
| 清理不能掩盖原错误 | records.resource_cleanup/context；source退出；共享audit finally | source/coverage/audit_regressions：主体错/仅关闭错/双错/KeyboardInterrupt，尝试所有释放 |
| 单连接、月/批内存与成本 | 借用连接；月finally释放；输入身份TEMP缓存 | source批量断言、coverage重复读取/重算计数及process成本记录 |
| 未变结果复用 | coverage.evaluate先核身份再复用，write同结果不替换 | 首次1次集合，未变replay 0集合/0result替换；三份全局文件不重复全文SHA |
| 真进程退出恢复 | bootstrap_process真实独立解释器 | Raw完成前后SHA/mtime；新进程0明细重读；窗口过期无凭据只本地统计 |
| 后批边界 | 可信CurrentPublication+两层audit纯内核 | 不实现PG事件reader、不装配job/sensor/catalog、不补事件、不执行正式数据操作 |

测试文件均在`lake_console/orchestrator/tests/`，名称为`test_stk_factor_pro_bootstrap*.py`。独立预期取自本地261字段源文档、现行上游schema/真实producer和LLD；模拟Prod只代替远程数据库，真实临时Parquet、转换、摘要、记录和原子提升照常执行。源码字段类型复用已获准证据，不把模拟named cursor当作真实Prod运行。

## 独立审计与修正

审计使用CodeGraph explore/impact核原共用候选的日更/历史调用方，实施后sync/status核索引，人工追读全部bootstrap链及真实上游schema/check。

修正并用14项真实临时文件回归复核：Silver意图/恢复的Raw绑定；空源分支统一核来源身份；诊断路径持久化为operation内相对路径；完成记录绑定候选业务摘要/行数；共享audit的主体错误与DROP错误同时发生时保留主体错误。另修正未变化日期最终统计重复计算，完整37项coverage测试含计数反例；月处理finally释放本月和逐日关系，缓存只保留三份全局输入。

上述为2026-10-26的既有修复记录。随后复审发现五项缺口，已按当前方案/LLD于2026-10-27处理，不能再引用原858项宣称这些问题当时已解决。当前独立复核未再发现确定问题，详见下节。没有新增业务口径、恢复平台、运行配置、锁或线程。


## 2026-10-27 五项修复当前验收

| 要求 | 当前实现及验收 |
| --- | --- |
| 原检查SHA绑定 | publication冻结原audit SHA，描述后、保存意图前、提升前均核；reuse另绑定原目标SHA。新增16项，Raw/Silver三个时点篡改零replace，字节不同等价及候选已移走恢复正常；旧源码内存对照能抓原缺陷。 |
| 空间先核、边界重核 | records纯预算和按设备free检查，主入口显式向source/publication/coverage绑定同一回调；新增58项纯预算、12项接线。覆盖初始不足零明细、途中保留、半日完整重取、全部剩余文件累积、C_new/C_work独立、原0补5、JSON实际增长/已占字节去重、两月最终最大工作量。元信息计数增减维护，本月批次最多31日，不按边界反复扫全日期计划。 |
| 片段检查复用 | records上下文绑定连接/operation/批准/月，source→records→publication显式传递，月finally清空；writer仅一次真实Parquet完整描述，原子改名核身份后登记。新增16项；真实三日单片段主链完整描述1次、每日本日检查仍保留，两层值和日期类型正确。不能据此声称全程序只读文件一次，字节SHA和本日查询另计。 |
| 坏依据准确分类 | readiness单处代码规则复用；准备阶段核life/identity/suspend，已知坏文件/字段记对应未知；意外SQL/程序错误传播。新增18项加原37项通过，合法两日均导入、坏停牌只影响本日、仅life坏不误标identity；旧源码内存对照可重现原错误。 |
| 标准运行摘要 | main同步进度对象+标准logging，source保存后通知，完整日两层/统计核实后计数，正式owner关闭资源后才finished；普通日志异常不改变业务，取消/主体异常保留。新增16项含关闭失败无假成功、空源分类/重入基数、跨attempt、日志失败不重复请求/提升、容量后检失败仍如实记录已完成日。 |

本轮使用CodeGraph explore/impact核入口、source/records/publication/coverage及readiness调用方，改后sync/status通过；人工核实际SQL、生产者schema和测试边界，没有引入跨工程依赖或前端/API消费者变更。真实Prod来源行为与正式DG读取继续在后续获准阶段核验。

当前完整普通回归868项通过（351.25秒），受保护原runner 1+12+113=126项通过且正式连接数0，合计994项不同用例。最后仅空间元信息月份索引调整后，空间12+日志16=28项重测通过（38.25秒）；它们已经在868项内，不重复累计。原858项是修复前2026-10-26基线；新增136项与原732项普通用例合计868，未将重叠的单步测试相加。

默认Ruff与全src/tests致命规则、CodeGraph sync/status、文档完整性、局部链接及diff检查均通过。测试未skip，既有Pydantic/Dagster preview/时间API与JUnit record_property提示保留，不以升级依赖或屏蔽检查解决。

证据：[当前完整回归](fixes-full-tests.xml)、[最后边界重测](fixes-final-boundaries.xml)、[计数、受保护门禁及文件SHA](fixes-verification.json)。独立审计复核了五项原反例及最后的月份/进度边界，未发现新的确定代码问题。没有修改下载组件、261字段源契约、其他数据集、正式入口配置或Prod实现。

执行范围仍为临时文件、模拟Prod、既有真实schema/已保存小响应及测试localhost；没有新Tushare请求、真实Prod读取、正式Lake/分区/事件写入、任务/sensor操作或依赖安装。不以模拟游标冒充真实PG验收，不对正式已bootstrap数据做全量扫描。正式窗口/准确范围/R/timeout/磁盘和正式执行继续按既定流程单独批准。

## 2026-10-26 原主体测试与执行边界（历史证据）

- 合同及已有相关回归226项通过；source 30项、coverage 37项、发布/记录/入口及独立审计回归分别通过，数量存在交集，不能直接相加。
- 默认Ruff、全src/tests致命规则、文档完整性、差异空白检查通过；CodeGraph索引已同步。
- 受保护Definitions、资产治理、静态合同分别使用原runner通过（1/12/113项），未扩大runner能力清单。
- 初次整批命令将Definitions显式文件与`--ignore`同时传入，仍执行该文件并在导入隔离支持模块前失败；其余731项通过。保留原结果，不将此命令记成全部通过。按明确文件清单排除该文件重跑，最终731项全部通过（267.76秒）；Definitions另由正确隔离runner完成。
- 有限localhost HTTP测试在允许绑定本地临时端口的工具权限下执行；受保护runner在允许创建其严格sandbox-exec子沙箱的工具权限下执行。无正式源或网络地址被替换为测试目标。
- 未执行真实Prod导出、Tushare请求、正式Lake写入、正式分区注册、事件补录、job或sensor；没有安装/升级依赖，没有自动推进第五批。

## 成本与未覆盖范围

1股1日、261列的真实进程退出/恢复/本地统计成本由`test_stk_factor_pro_bootstrap_process.py`生成三份JSON。SQL中的read_parquet计数不是物理文件扫描次数；SHA计数包含小JSON引用多次读回，不能视为同样数量的大指标文件扫描。

覆盖计数断言：首次处理每日期1次集合运算，三份全局输入各全文SHA1次；同连接未变再次执行为0次集合、0次result替换、0次全局全文SHA。summary无连接，按唯一文件去重，并在末尾再核一次，每份全局输入合计2次SHA。

原5000行9.94MiB净字段、128MiB工作空间/256MiB余量及既有DuckDB设置保留为估算；本批未做内存压测，不能声称真实全源内存或耗时已经验证。正式源的维护窗口、准确全范围、每月R/timeout、磁盘与性能仍须正式执行前核准；真实DG事件读取与发布授权第五批接入。


## 2026-10-26 原主体结果与复跑（历史证据）

当次不同测试合计858项通过：数据集732项（整批731项，加真实临时instance注册1项）、受保护门禁126项。新增入口用例所在文件9项全部重测通过；其中8项已经在731项内，不重复计数。JUnit与门禁摘要保存在本目录full_tests.xml、entry_tests.xml、verification.json。

完整普通回归必须先生成文件清单，排除test_stk_factor_pro_definitions.py，再传给本项目pytest；不能把显式该文件与--ignore同时传入。受保护三套分别执行原stock_suspend_confirmed_test_runner.py --scope regression --suite <上述文件>，不得裸跑或放宽隔离。全量普通回归包含localhost测试，需有临时本地端口权限；受保护runner需要能创建其sandbox-exec子沙箱。

bounded-cost.json记录1股1日完整261列的正常、Silver失败后恢复、仅本地重执行、最后读回。正常约1.54秒，失败加恢复约1.55秒，未变本地重执行约0.26～0.29秒；仅代表本次有界合成场景。原子保存边界观测最大留存空间约182KB（含测试上游和批准/记录），不宣称OS瞬时峰值或进程内存峰值。真实独立进程crash/recover/local三份cost JSON另列控制查询、明细、fetch、DuckDB SQL、COPY和SHA调用，不能把大量小JSON核验混称大指标文件反复扫描。

初次临时成本脚本最终读回忘记hive_partitioning=false，Raw路径分区名覆盖源日期表示导致断言失败；改用项目既定显式false后全部通过。正式实现本就显式禁用Hive日期覆盖，没有修改业务数据或放宽日期断言。

仍未执行真实Prod bootstrap、正式Lake/分区/事件操作或正式PG完成事实读取；没有安装依赖、创建分支/worktree或修改Prod契约。paths.py原有其他数据集的未提交修改完整保留，本任务只追加本数据集路径函数。本次按本批清单逐项暂存该文件的股票技术因子新增函数，其他任务的修改留在工作区。
