# 股票周/月交付恢复：提交后独立审计

**后续处理（2026-10-28）：** 下方是88de377ca原审计，位置/行号及“未修复”结论按当时版本保留。管理员随后批准五项开发，现已完成方案/LLD统一、代码修复、独立复核及隔离验收；最终528通过、0失败，2项既有PG实验未启用，详见[五项修复报告](followup_1_5.md)。原红证据没有删除，未部署、修正式状态或补数；本轮修复及证据随本次提交保存，提交号以Git记录为准；未推送。

2026-10-28。审计提交 **88de377ca**，分支 dev-interface，未推送。设计基线为 befd282e0。

**结论：尚未完全符合方案及LLD，不能据此前411项通过进入正式修复。确认2项P1、3项P2。** 本轮只审计和记录，没有修复这些问题，没有部署、正式状态修复、补数、sensor操作或正式数据读取。

**后续文档状态（仍未修复）：** 管理员随后要求先细化第3、4、5项，修正细节已补入[原共享LLD§12.16](../../docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-delivery-recovery-followup-345)，与总方案§10.8、月线LLD§9.4对应。第1、2项仅解释；本轮文档工作未运行测试或正式操作，不能将下述原复现与旧通过数算成新设计已验收。

审计依据为[总方案第10节](../../docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#period-delivery-recovery-plan)、[共享LLD第12节](../../docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-delivery-recovery-lld)及[月线LLD第9节](../../docs/design/dagster-stock-monthly-raw-onboarding-low-level-design-v1.md#monthly-delivery-recovery)。以当前源码和真实生产者合同核验；没有用实现对账表或测试通过数代替独立审查。

## 1. P1：文件已替换、提交回执未写成时，正常续跑被阻断

位置：[stock_period_history.py:463](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_history.py#L463)、[缓存候选恢复入口:910](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_history.py#L910)；被挡住的原有恢复能力在[stock_period_raw.py:1147](../../orchestrator/src/orchestrator/defs/io/stock_period_raw.py#L1147)。

原本应当：os.replace已经成功、随后committed JSON写失败，沿同一执行恢复时，核对冻结候选、目标版本及摘要，补写提交回执，不重写行情。

实际：新增validate_registered_targets只接受baseline版本或已有committed回执。此时目标已经是候选的新版本，回执尚不存在，因而先报period_target_unregistered_version，根本到不了publish原有的恢复分支。

隔离复现使用现有小型Raw producer，故意只在第一次写committed回执时抛OSError。确认候选已被移动、目标精确匹配提升版本、回执缺失；run_period续跑失败，而直接调用原publish可以保持目标版本不变、补成回执。主审另行运行同一最小复现，结果一致。

影响：一次正常的进程退出或磁盘写回执失败，可能留下已成功替换的行情，却不能用正常入口续跑。违反LLD§12.6保留原发布守卫和逐文件中断恢复、§12.13 D2。既有测试只分别覆盖“直接调用publish恢复”和“committed回执已经写成之后取消”，没有覆盖新增守卫与这段恢复的组合。

修正方向：先在原方案/LLD说明如何证明“本次候选已经成为目标”，保留原有精确版本和摘要核验，再补run_period实际入口的中断反例。不能简单放开未知版本。

证据：[复现脚本](audit_evidence/reproduce_replace_before_checkpoint.py)、[原输出](audit_evidence/reproduce_replace_before_checkpoint.out)。

## 2. P1：主动history没有进入共享待办，后续新写可越过未确认交付

位置：[ordered_pending_work:306](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_history.py#L306)、[新写前守卫:355](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_history.py#L355)、[history执行入口:834](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_history.py#L834)。当前生产代码只有[daily路径:488](../../orchestrator/src/orchestrator/defs/stock_period_update.py#L488)登记daily.pending_work。

原本应当：旧history文件已写好，但原生检查尚未完成时，下一次不同意图在源请求、历史读取或COPY前停止，先完成旧交付。LLD§12.6明确禁止“仅日更受保护、手动历史仍能覆盖未确认文件”；§12.7还规定无asof主动历史按started_at排序。

实际：守卫只遍历daily.pending_work，真实主动history从不登记进去。排序器可以处理人工放入队列的history记录，却发现不了实际入口产生的未确认history。

隔离复现：第一条history用真实Raw producer生成文件和回执，临时SQLite中登记真实物化/通知、保留检查缺失这一执行边界；confirm明确返回missing_checks，队列长度却是0。第二条不同request_id的history仍发1次假源请求、提交2文件，替换旧未确认目标；随后原交付确认报period_delivery_current_file_unknown。主审独立重跑，结果一致。

影响：先完成旧交付的保护并未覆盖全部获准入口，可能再次制造“旧检查未完成，文件已被后来任务替换”的状态。此复现覆盖真实producer、共享writer及SQLite事件，不冒称完整原生job端到端验收。

修正方向：在原设计中补清主动history的登记、完成和恢复方式，使真实入口产生的未完成交付能被共同守卫发现；不要通过扫描整个runs目录、手工删记录或新增另一套状态绕过。

证据：[复现脚本](audit_evidence/reproduce_manual_history_untracked.py)、[原输出](audit_evidence/reproduce_manual_history_untracked.out)。

## 3. P2：Silver补报可给真实检查会拒绝的物化写入三项通过

位置：[stock_period_silver_readiness.py:169](../../orchestrator/src/orchestrator/defs/asset_guards/stock_period_silver_readiness.py#L169)、[stock_period_silver_cli.py:78](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_silver_cli.py#L78)、[补报检查:109](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_silver_cli.py#L109)。真实检查要求在[stock_period_silver_checks.py:37](../../orchestrator/src/orchestrator/defs/checks/stock_period_silver_checks.py#L37)。

原本应当：只有物化的必要日期、范围和文件绑定符合原检查合同，才允许补缺；不能用补报通过代替真实检查会失败的情况。对应LLD§12.1、§12.4及性能规范完整检查语义要求。

实际：matches遗漏silver_asof；首次补报只以版本、路径、行数决定是否沿用物化，然后直接补三项passed=True。使用完整21列真实producer及silver.build生成6个小临时文件，周/月各取1文件，仅删除现有物化的goldenshare/silver_asof，其他元数据、文件和回执保持准确。两频均产生相反结论：

| 验证 | 周线 | 月线 |
| --- | --- | --- |
| 新增物化 | 0 | 0 |
| 新增通过的blocking检查 | 3 | 3 |
| require_checks | 接受 | 接受 |
| 原生evaluate检查同一物化 | silver_check_scope_missing | silver_check_scope_missing |

主审使用无PYTHONPATH的既有解释器重跑归档脚本，结果一致，临时文件已清理。现有反例只覆盖“已经有失败/错绑结果”，没有覆盖“检查尚缺，但物化本身不满足正式检查合同”。未核正式实例是否存在此类坏metadata，不能据此宣称生产数据已受影响。

修正方向：补报准入与原生检查共享必要的日期、范围及绑定规则；补缺不能绕过这些规则。须同时覆盖缺失和非法asof的拒绝，以及合法前像不会被误拦。

证据：[复现脚本](audit_evidence/silver_missing_asof.py)、[两频原结果](audit_evidence/silver_missing_asof.json)。

## 4. P2：周线限定补报不能补记已证明完成的局部历史

位置：[stock_period_history.py:567](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_history.py#L567)、[旧版本校验:581](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_history.py#L581)，实际入口[stock_weekly_bootstrap_checks.py:41](../../orchestrator/src/orchestrator/defs/ops/stock_weekly_bootstrap_checks.py#L41)。

LLD§12.5明确要求周线限定op只读/补记week的单文件和通知，month未确认时不关闭整批或移除pending。

隔离组合为两频files_complete旧批，周文件已有合法后继、原周线证据完整，月线仍未确认。week-only确认正确返回historical_only=True、整批未完成；但replay仅在phase已为events_complete时接受局部历史返回，随后要求旧周文件仍为当前版本，报period_committed_file_changed，缺失周线CP无法补记。

影响限局部历史补记；全频events仍可恢复，旧20日仅1个周文件的全频收尾不受这一组合阻断。修正应明确分开“允许频率的回执可补”和“整批不能关闭”，不能顺便补月线或提前移除pending。

证据：[复现脚本](audit_evidence/partial_week_history.py)、[正确启动方式的结果](audit_evidence/partial-week-history.json)。本次无源请求、无新业务事件，phase、pending、complete和当前文件保持。

## 5. P2：旧行情读取的拒绝顺序未达到LLD要求

位置：[stock_period_raw.py:712](../../orchestrator/src/orchestrator/defs/io/stock_period_raw.py#L712)、[守卫:740](../../orchestrator/src/orchestrator/defs/io/stock_period_raw.py#L740)。

LLD§12.6要求未知选中目标在“读取旧行情及COPY之前”拒绝。范围索引失效时，实际先执行locate_old_keys，对该频全部旧路径读取ts_code及日期列，之后才调用validate_targets。最小反例篡改已登记目标mtime，最终虽被正确拒绝，但此前已执行1次定位SQL；完整旧行合并和COPY均为0。

这不表示发生了全列行情读取或正式数据变更；说明读取边界不等于原承诺的“0旧行情读取”。实现报告虽然说明保留原定位查询，不能据此自行收窄LLD硬口径。需要先对齐范围定位与归属核验的顺序/必要读取，再按原文档约束开发或明确请求设计调整。现有反例只断言无COPY，漏了这项读取断言。

证据：[复现脚本](audit_evidence/reproduce_guard_after_old_read.py)、[SQL阶段计数](audit_evidence/reproduce_guard_after_old_read.out)。

## 6. 已核范围、证据边界与下一步

- 按当前源码重新核对三个检查选择入口、历史确认/后继链/ack、daily/history/CLI/handoff/周线op、原生日期/分区和测试落点。使用CodeGraph status/explore/search/callers/impact辅助，动态回调由源码补核；Context7和本地Dagster1.13.26 SDK用于检查/重执行合同。
- 实际evaluation事件排序、NULL/重复异常、双LEFT JOIN、已经存在的FAILED/非blocking/晚错绑拒绝、已消费旧批确认及多后继链，在此次审查范围内未发现其他确证问题。这不是全仓无缺陷保证。
- 原411项去重通过记录及原失败轮次保留。独立核对4份XML的最后一次逐用例结果，确为411项通过；当前8个生产文件与results.json指纹一致。但新增组合未被原套件覆盖，因此撤回“全部要求已通过、无已知阻塞项”的总体结论。
- 只补必要隔离复现和10个既有定向用例；正确启动轮次10通过/0失败/0跳过，6.47秒。使用本工程既有.venv/bin/python3 -B，不安装依赖，不重复整套回归。原10例及一次局部复现设置PYTHONPATH，违反启动规则，已明确撤回并保留为无效启动记录；去掉PYTHONPATH后重跑同范围，结果相同。见[有效定向记录](audit_evidence/receipt-targeted-checks-correct-launcher.json)。
- 所有业务文件、Lake/staging及SQLite实例均为临时隔离资源，已清理；没有访问正式DG、Lake、Tushare或Prod，没有启动正式job/sensor，没有改生产代码。只保留小脚本、JSON及必要输出。没有再次运行隔离PG或性能实验。

建议先补清前两项的真实恢复/登记方案，再按同一LLD补齐其余三项和正反测试，最后重新逐项对账。本轮停在审计，所有问题均未修复；正式旧待办收尾和补数继续不执行。此次审计及状态回写在开发提交之后形成，尚未另行提交。
