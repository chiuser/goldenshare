# 第三批提交后的独立审计

日期：2026-10-26。首次审计提交：`d1564587`（33个本需求文件，未push）。下文保留缺陷发现时的审计记录，原656项是提交时的验收事实；管理员批准后的修复、回归及再次独立审计结论见末尾“修复收尾”。本轮修正已按原方案及LLD§16.5落实。

首次审计结论：主业务链与第三批范围一致；确认一项P2清理缺陷，涉及同一个历史模块的4处finally。建议先修复并补双故障回归，再确认第三批完全收口。不扩大到第四批或正式执行。

## 审计依据与范围

依据[技术方案§13.5](../../docs/design/dagster-stock-technical-factor-onboarding-plan-v1.md)、[LLD§5.1/5.4/6/8/9/16](../../docs/design/dagster-stock-technical-factor-onboarding-low-level-design-v1.md)和管理员批准的七步计划，分别复核名单与范围、下载与记录、历史发布，并单独核测试依据和成本记录。

使用CodeGraph explore/callers/status核依赖；调用索引对两个新增入口返回无调用方，因此进一步以当前源码及测试确认：本批入口尚无正式asset/job/sensor消费者，测试有真实调用，不能把索引的“无调用方”当成“无测试”。历史源接口文档、3列Raw复权因子及10列生命周期生产者schema、保存的261字段响应与夹具已核。没有跨工程import、新PG结果读取器、配置、连接、线程或公共下载器变更。

## P2：清理失败会盖住最初错误，并跳过剩余清理

最小例子：保存历史范围的COPY先报本地写入失败，程序随后解除DataFrame注册也失败。现在最外层抛出的是解除注册错误，删除临时表根本没有执行，`stk_factor_pro_record_rows`仍留在当前连接中。原写入错误仍在异常链内，但没有按LLD要求作为最初业务错误继续抛出；排障和后续错误分类会先看到次要清理错误。

以下属于同一根因，不算四个独立设计问题：

| 位置 | 实际发生的偏差 | 隔离证据 |
| --- | --- | --- |
| [历史记录writer:289](../../orchestrator/src/orchestrator/defs/io/stk_factor_pro_history.py:289) | unregister失败后不执行DROP，次要异常替代COPY写入错误；影响plan/ranges和manifest共用writer | 经正式plan writer和完整12列范围输入进入COPY，确认COPY调用1次、DROP调用0次、临时表残留1张 |
| [源核验:510](../../orchestrator/src/orchestrator/defs/io/stk_factor_pro_history.py:510) | DROP VIEW失败会替代源字段不符的ValueError | 261字段合同的缺列反例被发现后，注入DROP VIEW错误；顶层变清理错误，核验view残留1个 |
| [名单规划:1125](../../orchestrator/src/orchestrator/defs/io/stk_factor_pro_history.py:1125) | 第一个DROP失败，不再尝试第二个，并替代取消错误 | 保留原取消异常于context，实际仅尝试删T表，T/P两表残留 |
| [输入再核:1431](../../orchestrator/src/orchestrator/defs/io/stk_factor_pro_history.py:1431) | 第一个DROP失败，后续清理跳过，替代因子变化错误 | 目标股因子由2改3，本应报告该变化；实际顶层为DROP错误，只尝试删T表 |

复现均使用真实临时DuckDB连接，只在要验证的清理或写入位置注入错误；没有使用正式数据。本问题不导致坏源被放行，也没有证明正式数据受损，但不符合LLD§16.2、§16.3要求的逐项释放和保留最初业务错误。既有下载unit及历史发布已有相应处理，历史记录模块未完整落实。

建议的修正范围与验收：

1. 先在原LLD写清同一模块四处的清理办法，再修改`io/stk_factor_pro_history.py`，逐项尝试unregister/DROP。已有主错误时继续抛主错误、附清理错误；仅清理失败时明确报告清理失败。
2. 补四处的“主步骤失败＋清理失败”反例，并确认一项清理失败后仍尝试剩余项；保留普通成功、仅清理失败和正常取消分支。不能通过吞掉清理异常使测试通过，也不要求无法成功的DROP最终一定成功。
3. 回归记录、规划、再核、源检查，以及已落实同一规则的下载/发布清理；无需重跑45日或请求真实Tushare。字段、名单、20日批次、源重下、正式文件保留规则均不改变，不新增机制或配置。

完整输出见[independent-audit-evidence.json](independent-audit-evidence.json)。本轮未实施上述修正。

## 其余逐项结论

| 七步要求 | 本轮重新核验结论 |
| --- | --- |
| 类型、摘要、记录及连接 | 结构、路径、摘要、当前run和同一连接符合；异常清理按上述P2处理 |
| 可信起点与完整名单 | 不裁短已有可信边界；只对缺依据对象一次有界MIN；T/P完整对应、缺项及旧未完保留；repair不扩大原授权 |
| 实际unit与资格 | 不把完整名单数量当unit数；未知整范围零请求；只排除已证独立完整成功范围；Raw/Silver冻结资格及三次输入再核符合 |
| 完整历史源 | 原生BY_OBJECT_RANGE、代码/闭区间/261字段、逐unit保存读回释放、全部session关闭及summary后才交VerifiedSource符合；业务保存不重试 |
| 20日及两层发布 | 每批一次实际物化，逐日Raw后Silver，只处理d<T；B−K+U、无关股票、日期/分区写前拒绝符合；无文件audit=None |
| 未刷新与整范围 | 仅按实际expected_units求差集；保留旧行和有效新行后最终失败；目标SHA/输入再核和完整物理事实不冒充run成功符合 |
| 重入、成本与边界 | 保存真实响应及实际新进程重下证据与当前代码SHA一致；未用旧源/候选续跑。小样本成本未冒充全历史、真实满页或正式PG事件验收 |

## 实际验证与证据边界

Root本轮针对性60项通过（12.87秒）；独立分工分别95项（3.75秒）、62项（1.84秒）、11项（6.21秒）通过。分组有重叠，不能相加，也不与原656项相加。这些通过没有覆盖上述双故障路径；新增复现补充了这一缺口，不能继续只引用测试总数宣称全部约束完成。

提交前已核原验收中记录的代码/测试SHA与当前字节一致，文档完整性及33文件暂存区空白检查通过。提交检查只清除了pytest日志原有行尾空格，未改变任何测试结果。审计期间上述33文件与提交仍一致，其他任务修改保留。

未访问正式Dagster、PG、Prod或Lake，未新增Tushare请求、运行正式任务或推进第四批。完整自动入口、PG事实读取和事件装配仍属于后批，不能因本次文件链审计当作已完成。


## 修复收尾：P2已关闭，继续独立审计未发现新问题

管理员批准后，先补原方案§13.5和LLD§16.5，再新增16项真实临时资源反例。修前同一测试文件8失败/8通过（1.51秒），修后原样16通过（1.29秒）；未通过修改断言或旧夹具消除失败。完整结果见[cleanup-before.txt](cleanup-before.txt)、[cleanup-after.txt](cleanup-after.txt)。

生产改动只在`io/stk_factor_pro_history.py`：新增私有`_history_resource_cleanup`，四处均在创建所用资源前进入同一with。主体BaseException继续抛同一个原错误对象；每项DuckDBError收集后继续，原错误存在时附notes，没有原错误时抛首个清理错误。finally不提前return，T/P两条lambda明确绑定各自关系，不产生循环变量晚绑定；不用生成器.close的专有规则改变普通同步入口。不能成功的清理仍真实报错，不声称失败的DROP已成功。

| 审计位置（修前提交行号） | 修后位置及验证 |
| --- | --- |
| 记录writer289 | 当前`_write_rows`使用同一helper；COPY主错误保留，unregister失败后DROP仍执行并核表已删除 |
| 源核验510 | 当前`_verify_source_unit`保留实际字段错误对象，DROP失败附note；源文件字节不改，不返回伪造VerifiedSource |
| 名单规划1125 | 当前`build_stk_factor_pro_history_plan`保留KeyboardInterrupt对象，首DROP失败仍尝试第二项；P表成功删除 |
| 因子再核1431 | 当前`recheck_stk_factor_pro_history_inputs`保留真实因子变化错误；正常范围外T/P修订不误拦，两张真实表均进入清理 |

17个相关历史测试文件共307项通过（46.01秒，已包含新增16项）；没有重跑1/20/21/41/45长批边界。修复未改变任何业务SQL、字段、范围、路径、摘要和发布方法；正常清理操作数不变，出错时只补做先前遗漏的剩余动作，不重试任何请求/清理，不增连接/锁/线程/状态/文件读取。

另复用现成保存响应的两个完整断言链，将输出重定向至本轮独立证据，未覆盖原验收JSON：一股五日正常下载及4日8目标Raw/Silver发布、5,567只无关股全部业务值不变、T不覆盖；真实进程退出后新进程重新请求完整原范围，旧source/candidates读取0。两条链合计8.497秒，正常SQL仍371条、批源查询1次。完整查询/SHA/空间及耗时见[cleanup-chain-evidence.json](cleanup-chain-evidence.json)，合并回归及当前源/测试SHA见[cleanup-regression.json](cleanup-regression.json)。此样本不证明全历史性能或正式事件验收。

两路独立只读复核最终diff和完整源→下载/发布交接，未发现新确定问题；另用独立小探针验证多项清理同时失败、原取消与DuckDB清理中断同时发生，均继续尝试剩余清理并保留正确异常对象。其余finally仅关闭单一文件描述符，不在本轮DuckDB问题范围内。CodeGraph修改前explore及实际导入审计、修改后sync/status完成；默认/致命Ruff、文档完整性和空白检查通过。

本P2已关闭，第三批维持隔离验收通过，具备制定第四批详细计划的条件。本轮未自动提交、未推进第四批或正式执行；原批准范围、正式数据保留、失败新run完整重下的约定未变。
