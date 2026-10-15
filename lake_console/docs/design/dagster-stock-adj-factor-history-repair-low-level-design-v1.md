# 25股修复LLD v1：已实现合同、暂停现场与后续优化

更新：2026-10-15。状态：R1/R2已验收提交；R3未最终通过、已安全暂停、未提交。管理员要求先完成[周/月主线](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)，本专项后置；本文不是恢复、正式freeze或写入许可。

## 1. 代码事实与复用边界

defs/bootstrap/stock_adj_factor_history_repair.py承载合同、范围、逐资产端点、指纹闭包与规划；_cli.py提供inspect/freeze及手动阶段入口；_candidates.py负责因子/价格投影、合并和完成记录；_indicators.py负责单股片段、状态重放、原blocking批量校验；_execution.py负责计划加载、worker、锁、预算、进度及退出。

原daily_qfq、stk_mins_qfq、trend_channel、MACD/KDJ、nineturn纯核由日常writer与专项共用，不复制算法、不调用会直接提升正式文件的普通全市场历史执行器。configured DuckDB显式传专项settings，不能误用共享16GB默认。普通相邻日factor repair不能识别同一历史日期的新版本，不复用其入口。

<a id="indicator-repair-audit-20261012"></a>
## 2. 必须保持的业务合同

| 范围/语义 | 当前落点与约束 |
| --- | --- |
| 对象 | 上位方案25股/2,489精确因子键，不允许空代码变全市场；纯舍入/格式差异拒绝进入范围 |
| 扩展 | 仅688689日线基准从2021-01-27核验；不新增其他股票全历史修复 |
| 因子 | Raw保留源历史、Silver沿当前CNY/list_status=L及合法上市区间；不以Raw兜底缺Silver |
| 日价 | 原七价字段、冻结基准及上一实际源行；只改批准差异和实际后继pre_close，不取机械上一交易日 |
| 分钟 | 七频沿现行标准K线和Silver映射，量额不改；Gold1/5/15/30/60/90/120对应Silver1/1/5/5/30/30/60，不改普通生成逻辑 |
| 下游输入 | 必须用本次价格候选或已验证no-op，禁止回退旧Gold；检查所需范围外输入只读不扩修 |
| 日趋势 | 原公式、上一expected state及source、上市首日初始化、停牌carry；缺seed不能擅自初始化 |
| MACD/KDJ | 原参数版本、精确上一expected日seed和8根context，原1024-bar核、跨年state接续 |
| 九转 | 原完整历史核、4根close context及direction/count，不能裁历史后从零计数，计数可超过9 |
| 端点 | 价格、每个result、每个state分别冻结，互不替代，不新增原不存在日期/键；重放可到最晚端点，输出各自过滤 |
| 完整文件 | scope合并、schema、重复键、身份/分区/源覆盖、范围外双向EXCEPT ALL；每结果/state独立no-op |
| 质量 | 保留原正式blocking规则的真实语义；金样本验证公式，运行不靠同公式第二次全量重算 |

## 3. 执行合同、预算与持久化

scope显式包含股票、因子区间、as_of和允许末端；plan包含run/hash、完整scope、各基准anchor、逐资产真实末端、输入FileIdentity、目标原件、units、预算和实现指纹闭包。FileIdentity包含规范路径、size、mtime_ns和SHA256，不能只用mtime或validated标志。逐股/频率的seed/context及前序片段身份纳入计划/receipt，参数变化必须新计划。

单位按资产/月或资产/年及有界单股片段组织，完成候选记录绑定plan/unit/目标原件/候选/变化行/范围/依赖及业务验证。source或依赖缺项、库存漂移、符号链接、越界、未知归属、源摘要错误、旧实现均拒绝。相同文件只合并一次；范围外保留行不被单股输出覆盖。

当前预算来源为唯一RepairBudget及REPAIR_PLAN_MAX_BYTES，写入plan，无新env/Settings/日常job参数：192MiB计划、DuckDB2GiB、父子RSS4GiB、threads2、spill2GiB、候选10GiB、单股片段100,000行（含8/4根context）、可见进度≤30秒。工程参数可基于实测重评，不擅自收紧或修改旧plan。

候选、片段、投影只在本run内，强所有权和完整依赖校验后封存。COPY/fsync/replace/目录同步/checkpoint遵循逐文件边界，replace后未写checkpoint可读回识别候选补完成；第三方修改和未知残留拒绝，不删除已完成文件。进程取消不领取新unit，业务完成量仅在真实封存后增加，计算行数与封存量分开。

正式Lake固定/Volumes/datasource/data_lake，正式run staging固定/Volumes/datasource/data_lake_staging；当前仅保留已有/private/tmp隔离现场。正式提升须独占窗口，因子→价格→指标/state逐文件，不声称多文件原子。事件/serving独立阶段，不能以普通repair成功run伪装本次结果；事件失败不回滚数据。

<a id="r1-candidate-development-20261014"></a>
<a id="r1-acceptance-fixes-20261014"></a>
## 4. R1/R2完成事实与保留测试

R1提交75e86447；七项补齐：原因子分区状态纯核共用、完整冻结合同/库存、分钟全市场blocking语义、未封存产物所有权、真实进度/取消、完整实现指纹闭包、独立fixture及证据绑定。其后合同/候选102项、case独立进程16项、原消费者73项/42子测试及静态/治理/readiness回归通过；重叠不累加。25股1m年度样本25目标、241变化行、候选53,687字节、build15.20秒、父子峰值485,687,296字节，只是隔离样本。

R2提交5ef585f9e9abe053db13e214b572a96e0c2ee909；完成21指标资产/525条指标范围合同、175组精确seed/1,400根context核验、原公式/业务纯核消费者迁移、片段恢复及分result/state端点。最后子进程样本5.15秒/RSS794,279,936字节/候选107,235字节/spill0；完整市场检查库存容量328,164输入、15,743目标的占位编码测算138.6MiB，不是正式可执行plan或全链速度。192MiB plan正反门禁、真实进程及完整文件业务复核通过。

关键测试仍在tests/test_stock_adj_factor_history_repair.py、_candidates.py、_execution.py、_indicators.py、_replay.py及test_stk_mins_qfq_macd_kdj_rules.py；原trend、nineturn、MACD和readiness消费者回归保留。不是删除测试或用历史报告替代新实现验证。

## 5. R3已改代码、停止位置与现场

R3未提交文件：execution.py、test_stock_adj_factor_history_repair_execution.py、test_stock_adj_factor_history_repair_indicators.py，新增未跟踪test_stock_adj_factor_history_repair_full_chain.py，及两份专项文档。其他任务改动不能回滚/加入提交。

已补：TERM取消及worker父进程监护/继承plan锁；仅容忍列举后文件lstat的FileNotFoundError；加载阶段取消和真实进度；单次扫描统计复用；按实际emit时间25秒提前调度保留30秒上限；隔离夹具18个QFQ依赖；os.walk目录枚举异常重新抛出。目录门禁相关回归76项通过、113静态门禁、12治理/185子测试，均不等于最终全链通过。

| 暂停现场 | 实际状态 |
| --- | --- |
| 正常隔离链 | 因子740/740、价格289/289、重放325/325、指标749/749；最终正常/恢复验等及全链audit未完成 |
| 取消续跑链 | CANCELLED，重放325/325、指标130/749；reason=repair_coordinator_terminated，all_chain_ready=false |
| 退出/锁 | 只对身份核实的本任务协调器发送TERM，原协议清理worker；全部退出、两个plan锁可获取，没有碰其他服务 |
| 原输入 | 2,848文件/7,737,308字节，size/mtime/SHA无漂移 |
| 保留物 | 正常链1,778封存记录、1,491候选、1,874片段receipt；恢复链1,159封存、877候选、1,874 receipt；任务marker各325 |

现场根/private/tmp/r2-tests-ff4463b7-6810-4070-9847-baf1832e5f84/test_full_25_stock_chain_cance0/，下属run_id=0cf90e14-b2d0-407c-b7b7-813595b57bc4与3b98a680-9f5f-4ec2-a48f-ad8188b1026b。plan hash分别1ac8d8238786276c6f2930d994f7f034f5c59ae1419a186828a2c11792a5fd87、94073ce777fcfc6a33cbc1dbf761743212289b9b7845822fed4c57a3f1167240，不修改它们来强接新实现。

暂停和manifest证据为/private/tmp/r3_safe_pause_summary_20261015.json、r3_pause_evidence_20261015.json、r3_pause_preserved_manifest_20261015.json；全链日志r3_full_chain_directory_gate_final.log；目录门禁专项/回归日志r3_directory_gate_tests.log及r3_directory_gate_regression.log。临时路径只是保留现场，不是生产或未来恢复必须永久存在的事实源。

<a id="r3-nonredundant-execution-20261015"></a>
<a id="history-repair-execution-design"></a>
## 6. 未实施优化：非必要不重复

| 旧实现根因 | 必须保留的风险检查 | 后续设计 |
| --- | --- | --- |
| 每秒、COPY前后、逐片段/逐记录扫描全部累积目录 | 空间/配额/路径异常及真实写入量 | 开工/恢复和收尾总量对账；唯一写者预留/增量结算，活跃路径及轻量free-space门禁 |
| 每worker重新解析/校验整个plan和全部索引 | 计划、实现、库存/范围一致 | 已验证工作包、运行上下文、按股/频率/目标索引，强身份绑定及明确失效 |
| 公式执行之后才判断片段完成，恢复/audit重复计算 | 损坏、旧seed/context、旧实现或错误归属 | 先验证完整完成证据再返回；已完成kernel/COPY=0，部分完成仅续后缀 |
| 每目标重新读取相同依赖/整批业务核 | 原blocking语义、范围外保留与源覆盖 | 相同强身份批内复用，首次候选完整验证，规则/输入/输出绑定证据 |
| 大量短进程及每轮两个ps | RSS/退出/锁/真实取消 | 样本决定进程粒度，合并RSS读取，不先自行禁止批量/并发选择 |

缓存键必须包含plan/实现/规则/范围、输入强身份与解析模式（原件/候选/no-op）、overlay、seed/context、前序receipt及输出，不信路径/mtime或validated=true。重启重建账本和必要身份；外部writer、无归属文件、计量失配、实现或内容变化使复用失效。账本不能实时发现外部任意改写已关闭目录，因此必须有独占稳定窗口及边界对账，不能虚称实时全目录保护。

优先复用既有receipt/checkpoint和可重建运行上下文，不默认新增永久表；持久索引如有收益可再评估。fsync/原子提交不是瓶颈，不省；30秒真实进度/取消不放宽，不伪造完成量。

拟改execution/candidates/indicators/合同指纹闭包并新增stock_adj_factor_history_repair_runtime.py；迁移内部request/receipt和所有测试启动器，不改普通CLI/公式/asset/check/sensor。先小样本模型，再固定版本一条25股链并在途中取消恢复；旧完整结果只作基线。当前不开发或重跑。

## 7. 性能证据与恢复后验收

旧正常链因子333.99秒、价格281.11秒、指标9,212.99秒。指标525个worker中全目录清点17,340次/7,817.42秒，占worker时间92.2%；SQL94.21秒，fsync1.68秒。停后单次总目录扫描约0.65—0.72秒、plan加载约0.73—0.75秒。单纯减少90%/99%记录的worker清点成本，指标阶段算术外推36.3/24.6分钟，仅模型不承诺；合成1,778目标/~5.8MB远小于当时真实目标库存，不能当生产速度。

恢复后正向须证明完成文件/片段复用，kernel/COPY=0、完成身份不变、未完成续算、扫描次数不随轮询增长，独立金样本正确。反向覆盖plan/实现/规则/源/overlay/seed/context/前序receipt/输出篡改（含同大小且还原mtime）、缺输入、越界、权限/symlink、稳定超额/空间不足、记账丢失和外部写者。取消点覆盖预检、预留、COPY、replace后未确认及封存间，TERM/KILL无残留、锁释放、幂等读回、真实进度≤30秒。实际正式候选/提升/事件仍各自审批。

<a id="adj-factor-current-listed-migration"></a>
## 8. 已完成的因子Silver规则迁移

2026-10-13只改因子Silver为当前CNY上市合法区间，Raw源历史全部保留。正式4,267文件移除14只退市股票45,997行，48文件不变，最终4,315文件/14,416,884行；4,267新物化/真实成功run、17,068检查准确绑定，Raw4,315指纹未变。候选91.34秒/489.4MiB，提升及一次对账102.94秒/759.8MiB，事件3,048.89秒/678.2MiB。不是本25股因子数值修正，不重复执行。

<a id="r0-readonly-audit-20261012"></a>
<a id="r0-source-provenance-20261012"></a>
## 9. 保留的R0审计结论

25股旧因子Raw/Silver相等且与当前源2,489键存在非舍入差异；仅精度变化不修。分钟选源旧文档曾错误写Gold30/60派生90/120，Git溯源确认现代码早已统一Silver标准K线，管理员选择保留代码并纠正文档。

2026-10-13逐资产端点快照31资产/725端点、325重放任务，175组seed/1,400根context存在；不证明新源修正后指标已正确。首次短窗口数据量、旧预算和旧“688689无需修日线指标”结论已被后续实际基准核验替代，不再作为当前计划；恢复时只核本次真实需要，不重跑过时执行卡。
