# 技术指标计算内核 D1/D2 落地审计

2026-10-23。当前结论：**D1符合已确认要求；D2完成本阶段剩余有界验收，两处本轮发现的问题已修复，无未关闭的D1/D2实现问题。D2及本轮文档随本次提交归档，提交号以Git记录为准。** 本结论只覆盖基础合同和读取/复权/共享/控制，不表示指标算法、完整calculate、生产API或整页性能已可用。

## 本轮结果

- 正确临时样本为`/private/tmp/indicator_lld_probe_20261022/fixture.parquet`：32768行、386178B。误选的262144行文件在创建数据Reader前拒绝；不通过截取/过滤把它当正确样本。
- 正确样本只读一轮，同一连接依次处理四批8192行；源位置i与内部seq两侧均检查，无重读/漏行。SQL逻辑处理98304行，输入交接约24.59ms，清理错误0。
- 按原范围仅读600000.SH四个真实文件：2026-10-15日线/因子、2026-10-16周线、2026-10月线，合计935239B；目标计数各1行，读取前已核不超过3行。实际Lake prepare_basis/prepare_factors已执行，日线复权1次，周月直接读取已有qfq列、转换0次，文件唯一计数正确，全部清理成功。
- 真实日线close=9.64，周线qfq close=9.73，月线qfq close=9.76；基准日期2026-10-15/因子17.3774如实交接。hfq方法也在同一指定因子文件执行，展示end=2020-01-01未改变该输入行的选择。**只验证这份指定因子文件的交接，完整历史的全局最新/最早选择依据静态代码审计，不声称做了正式全历史验收。**
- 本轮诊断总约299.30ms；没有新建Parquet或修改正式数据。进程观测峰值173.11 MiB、相比诊断开始的进程历史峰值增加37.72 MiB；这是D2小样本进程观测值，不能替代D4真实并发/原生缓冲/整页256MiB目标验收。

完整逐阶段记录：[acceptance.json](acceptance.json)。上轮误选、超量、累计6份小夹具及暂停事实继续保留在[progress.json](progress.json)，没有改成通过。

## 发现与修复

| 问题 | 原因与影响 | 本轮修复与证据 |
| --- | --- | --- |
| D2取消时产生假的清理失败 | Session先记自己拥有名称，executor却先检查取消、之后才登记；基准/因子还可能在文件检查阶段就取消。收尾把本请求尚未创建的资源当陌生名字拒绝 | executor.declare_table与Session._own_table同步先声明；known与live区分未开始/已开始，陌生名仍拒绝。两个修复前反例确实失败，七类失败及basis/factor两个位置修复后8测试通过，无假清理错误或残留live记录 |
| D2 SQL模板未显式随包交付 | 当前Path会从安装位置读取3个SQL，原package-data只声明公告包；源码可读不能证明安装包有文件 | pyproject仅增加sources包sql/*.sql，精确包含stage_input/adjust_price/retain_history；静态检查修复前失败、修复后1项通过。没有改变读取方式、依赖版本，没有build/安装验证，不能称wheel安装验收通过 |
| 上轮验收未在读前核对样本数量 | 用错large.parquet，读到最后才检查批数 | 新有界诊断入口先核footer精确行数/大小/选中列块，之后才创建Reader；交付前再核单批/剩余额度/实际源位置；每阶段持久化证据，失败不丢之前阶段结果。10项保护测试通过 |

修订均先同步原方案与LLD后落代码；没有新增业务参数、任意周期限制、数据质量/日历校验、预取、第二连接、独立计算进程或兼容入口。

## D1逐项对账

| 已确认要求 | 实际实现 | 验收/审计证据 |
| --- | --- | --- |
| 一个目标复权，省略默认qfq；一证券/周期多实例 | contracts.CalculationRequest，严格日期与时区；容量从KernelConfig取 | test_contracts正反例、16/17实例与10000/10001边界 |
| 对象/参数不可变，外部列表不影响已创建对象 | MappingProxyType、tuple及两层参数复制，SourceDescription新增计划也复制 | 不可变容器、SQL bindings及来源清单反例 |
| 所有实例先校验，再创建计算对象 | dependencies.expand_dependencies先归一全部实例 | factory调用计数与非法后续实例反例 |
| 固定顺序、依赖去重/循环/版本冲突、保留输出身份 | registry/dependencies，同一请求复用键含参数/版本/初始化 | test_registry_dependencies、无算法名中心分支 |
| 发现与执行共用定义，来源能力如实声明 | discovery/catalog只读同一Definition及显式来源清单 | 无源为false、发现不调用factory/不读文件 |
| 配置唯一初值与已解析不可变对象 | Settings19字段，KernelConfig.from_settings不另读env | test_configuration及原配置优先级精确回归，未改现行get_settings |
| Foundation无上层/旧DG实现反依赖 | 新包及local_lake仅依自身/Foundation | 依赖AST、legacy规则与实际imports；CodeGraph辅助 |

当前五个内置指标在D1仅真实静态定义，没有虚假计算入口；算法与完整calculate按既定D3实施，不冒充D1/D2交付。

## D2逐项对账

| 已确认要求 | 实际实现 | 验收/审计证据 |
| --- | --- | --- |
| 同一服务创建并关闭私有内存连接 | service._open_execution/_close_execution | 连接配置、初始化失败、异常与清理顺序；DuckDB1.5.5、SQL1线程、128MiB、禁spill/扩展 |
| 一请求一个中断监控，停止后先等业务返回/解绑/join再清理关闭 | execution_control.py与executor执行前后检查 | 原29控制项有通过证据，重复中断/正常结束join/A与B隔离；不重跑旧1000万中断SQL |
| 来源沿冻结清单逐文件推进，无预取或反复扫描 | SourceDescription计划、_LakePriceStream单Arrow Reader | 原三文件2/0/3目标行及跨年、空目标文件继续；本轮32768源位置/同连接交错 |
| 单批Arrow先注销/释放，共享目标SQL表留到全部使用方完成 | PriceInputSession.next_batch/retain_required_history/finish_batch | 原同批两使用方不再读源、独立目标历史与seq边界；本轮register/unregister异常及取消反例 |
| 基准/当批因子复用同一来源预算和SQL连接 | SourceReadContext、prepare_basis/prepare_factors | 实际4文件最小接入，独立qfq5/6及hfq20/24字面预期；无因子1/INNER JOIN丢行 |
| 周月只选已有列，拒绝未结束周期的后来版本 | source_projection与Session阶段请求语义检查 | 原5组周月正反例、本轮真实周/月DATE/量额/qfq字段交接 |
| 信任外部质量，不加逐根扫描或审计 | 只做schema、资源与请求语义/类型转换 | 当前代码未import日历/停牌/质量模块，无价格有限值扫描 |
| 每请求只计一次新价格行，文件角色复用不重计 | SourceReadContext与SourceBatch累计快照 | 原150万/5000边界与不同请求隔离；本轮日线/因子两文件、周/月各1文件 |
| 失败不返回空成功，不留下资源；清理失败仍失败 | 保留原异常、统一finally、known/live声明、close失败保留句柄 | 读取/open/register/unregister/cancel等小故障注入；之前close回归及本次新增取消间隙复验 |

## 测试与预算

本轮有效通过证据覆盖265项：230项D1/相关回归（含1个旧executor精确节点）、16项架构、10项数量保护、8项异常收尾、1项SQL资源声明。修复前2个预期失败另行保留，不算最终失败未处理或被删除。上轮未受影响的控制/来源/复权证据复用，没有整组重跑、没有新增Parquet夹具。详情见[test_results.json](test_results.json)及[evidence](evidence/)。

- 本轮新增control：2个修复前反例+9个修复后异常输入+4个有界诊断+1个旧执行器节点=16；累计66/原72。
- 本轮临时数据读取恰32768行1轮；新建Parquet0。正式范围固定4个文件/1证券，目标每份1行；只统计该证券，不全市场明细读取。
- CodeGraph使用status/sync、explore及impact辅助核入口/消费者；实际源码手工核对新协议仅本模块消费者、没有API/前端接入。最终再次sync/status以更新新诊断/测试。
- 普通源码与文档检查不代表build、部署或页面性能验收。

## 已知限制与下一步

1. **范围外既有依赖差异：** 原pyproject已声明pypinyin==0.55.0而原uv.lock缺失。本轮只保留批准的PyArrow锁增量，原61个已装包版本未变；未安装/升级pypinyin，未做无关修复。因此不宣称整个项目的锁文件一致性或全新安装已通过。该项是独立依赖维护问题，后续要限定范围处理；不是本次源计算/资源协议仍有缺陷。
2. **D3尚未实施：** 内置指标实际SQL/engine、完整calculate、独立输出/字节编码及数值矩阵尚无实现，下一阶段必须按LLD逐项推进并单独验收。
3. **D4尚未实施：** App有限等待、并发及完整资源/取消/HTTP生命周期留在D4；本轮不切现行API/页面、不迁移XXM、不停DG。
4. **提交状态：** D1提交9e15ac73d；D2与本轮变更随本次提交归档，提交号以Git记录为准；未推送、未部署。工作区其它项目改动未纳入本次修改或测试范围。
