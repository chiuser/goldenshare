# 股票复权周/月交付恢复：开发与隔离验收

2026-10-28，dev-interface。设计基线提交 **befd282e0**，只含三份原设计文档，未推送。**本轮开发和隔离验收完成；未部署、未修正式状态、未补数。** 代码、测试及实施结果回写纳入本次开发提交；独立复核在提交后另行记录。

## 依据与范围

对应[总方案第10节](../../docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#period-delivery-recovery-plan)、[共享LLD第12节](../../docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-delivery-recovery-lld)、[月线LLD第9节](../../docs/design/dagster-stock-monthly-raw-onboarding-low-level-design-v1.md#monthly-delivery-recovery)。

修复三个检查选择入口、旧交付确认、共享待办顺序及原有调用入口。字段/源参数/价格/21列/选择规则、asset/job/check/sensor身份、19:30、run key、正式路径和policy未改变。没有新增正式job、sensor、输入字段、运行配置、自定义tag、数据库表或依赖。没有修改Prod、其他数据集或API/前端。

## 实现

| 位置（相对orchestrator/src/orchestrator/defs） | 实际行为 |
| --- | --- |
| asset_guards/stock_period_check_evidence.py | 按实际evaluation事件选最新terminal；先排名再双left join，缺事件/NULL/重复/正文索引不符拒绝；不按检查表ID回找成功 |
| stock_period_update.py::report_file_events | 写任何业务事件前检查已有失败/晚错绑/非blocking；只读未完成返回false；合法前像只用于补缺，不能算本次检查完成 |
| asset_guards/stock_period_silver_readiness.py、bootstrap/stock_period_silver_cli.py::report_file | 两个Silver入口复用同一选择和拒绝规则，首次补报不再用新通过覆盖失败；保留两条集合SQL及现行前像规则 |
| stock_period_update.py::confirm_period_delivery | 原身份/hash/完整清单与实际历史Mat/check/通知绑定；旧文件已正常替换时核完整前像链；已闭合旧批只作历史，不重读旧行情 |
| stock_period_update.py::acknowledge_period_delivery | 原锁内补原CP→原通知回执→phase→精确匹配且已消费的pending；中断逐步续跑，水位/身份/hash不倒退；入口自身复核根/目录/设备 |
| bootstrap/stock_period_history.py | 分离原清单验证与当前版本校验；所有新写入口先处理旧待办；初次纯文件完成不查询尚未发生的原生事件；恢复仍经过共同确认 |
| stock_period_update.py::_execute_daily_locked、deliver_asset | 按原日期/开始时间恢复；原意图未完成先返回原生anchor等待真实检查，不规划下一意图；新日期不能代办旧anchor；历史结果不生成当前物化；日期和分区先核对 |
| io/stock_period_raw.py::assemble | 已选目标在完整旧行读取/COPY前及缓存复用时核归属；未知版本、登记文件丢失拒绝；新分区/同意图已提交文件正常恢复；不改计算 |
| bootstrap/stock_period_history_cli.py、ops/stock_weekly_bootstrap_checks.py | events/快路径/handoff及周线限定补报接共同确认；纯文件已完成resume指向events，不自动取得instance；周线动作不补月线 |
| 原生重执行 | 复用安装版GraphQL FROM_FAILURE，保留原配置/日期/分区/父子关系；不创建另一种业务key或自动重跑策略 |

实现复核中发现并按原硬口径细化后修正：目标前像仅捕获stat不能证明归属；未闭合批次逐文件查库；共享receipt重复读取；ack逐CP重扫所有controls；候选清单逐CP重复读取。细节先回写LLD再实现，未扩业务范围。共享清单及候选清单只读一次，缓存仍核版本；CP收尾与控制核验保持线性。

原范围索引失效的定位列查询保持既有实现，必须由未来正式执行预算覆盖；新守卫在受影响分区完整业务行读取/COPY前拒绝未知目标，不声称它消除了原定位查询。未开展正式历史读取。

## 测试结果与原始轮次

**411个去重用例最终验证通过，0失败、0跳过。** 这是固定生产代码上的完整回归及必要定向复验合并结果，不是宣称一次pytest全部通过。

| 轮次 | 实际结果 | 说明 |
| --- | --- | --- |
| 完整周/月相关回归 | 405项，404通过、1失败；102.227秒 | 显式启用隔离PG；实际Raw/Silver业务集成、源/取消/恢复及既有不变项均纳入。失败是旧memory测试末次CLI resume期望 |
| memory合同复验 | 25项通过；1.123秒 | 按已批准LLD12.5将“文件已完成仍resume成功”改为events_required。首次中断恢复、原身份、6GiB覆盖、价格及零重复下载/文件不变断言全部保留；未改生产实现 |
| Raw实际补报负例 | 3项通过；3.588秒 | 实际SDK job证明FAILED、晚绑旧Mat、非blocking均失败，新增业务Mat/check为0；只读路径也不完成 |
| 多文件/连续后继补证 | 3项通过；2.966秒 | 两频中一频缺检查/通知不能关整批；两个连续合法后继仍准确确认旧交付且当前文件不回写 |

[results.json](results.json)记录轮次、源文件指纹和生产代码在完整回归开始前已冻结的mtime证据。[最新用例集合](latest-results.xml)按每个用例的最后一次实际执行合并；保留[原完整轮次](pytest.xml)、[memory复验](memory-contract-recheck.xml)、[Raw补报负例](raw-report-recheck.xml)、[多文件复验](multi-delivery-recheck.xml)，未删失败记录或用skip隐藏失败。所有生产代码在完整回归后未修改。

首次隔离HTTP调用因沙箱不允许监听回环端口未进入业务；改用工具规定的本机权限运行同一隔离测试后通过。PG验证准备阶段纠正了测试repository未完整登记资产/check、临时队列未配执行器的夹具问题；未修改正式配置。未安装依赖。

## LLD逐项对账

以下函数名是实际测试落点；组合边界分开说明，不用测试数量代替真实性。

| 要求 | 实现点 | 独立测试/证据 | 结果 |
| --- | --- | --- | --- |
| A1 实际完成顺序 | shared query/decoder、三入口 | check_evidence::batch_uses_late_result_despite_lower_planned_row_id；PG actual_check_query | 通过 |
| A2 两频/两层及PLANNED | shared query、Raw/Silver读取 | both_frequencies_and_layers_use_actual_completion_order；原recovery PLANNED各例 | 通过 |
| A3 失败/错绑不补绿 | Raw report、Silver require/CLI | daily_delivery::raw_report_does_not_replace_real_bad_checks三例；Silver原FAILED/错绑反例 | 通过 |
| A4 坏索引/缺实际事件 | decoder双left join | corrupt_latest_evidence_is_not_hidden_by_join_or_history；NULL/重复/错类型/副本错误 | 通过 |
| A5 集合/空范围 | readiness、current_evidence | empty_scope_does_not_connect；exact_asset_partition_pairs；Silver容量两查询 | 通过 |
| A6 合法早前像/晚错绑 | report/require_recoverable/confirmation | legal_preimage_is_missing_current_check_but_late_wrong_binding_is_refused；earlier_true_preimage_checks | 通过 |
| A7 首次Silver补报 | silver_cli.report_file | 原never_accepts_planned_or_misbound_checks改正坏→绿旧期望，真实坏结果拒绝且0新业务事件 | 通过 |
| A8 真实原生检查续跑 | 原job/check合同、无自动重试 | PG真实GraphQL子run只重跑失败check；事件补报负例仍拒绝 | 通过 |
| B1 当前故障状态 | confirm/ack | old_real_delivery_closes_without_rewriting_new_file_or_business_events | 通过 |
| B2 多文件缺项 | 整批确认/ack前置 | two_frequency_delivery_cannot_close_with_one_frequency_missing两例；限定频率/不完整回调 | 通过 |
| B3 未知版本/断链/多段 | successor chain、target guard | replaced_old_file_cannot_close_without_its_exact_history各反例；two_explicit_successors；未知目标/外根 | 通过 |
| B4 闭合旧批 | receipt/closed branch | receipt_validation_does_not_require_old_file_to_stay_current；confirmed_historical_delivery_skips_current_files；缺CP拒绝 | 通过 |
| B5 每步中断 | atomic CP→phase→pending | ack_after_each_atomic_write_can_resume_without_new_events_or_source四处；control漂移拒绝 | 通过 |
| B6 当前anchor | deliver/fallback所有权 | historical_result_is_excluded_from_native_anchor；unknown_current_anchor_is_rejected_before_file_audit | 通过 |
| C1 待办顺序 | ordered_pending_work/daily | pending_order_uses_original_dates_instead_of_json_key_order；新意图被旧待办挡住 | 通过 |
| C2 原生先后 | run_period/daily/asset | original_intent_returns_for_native_checks_without_replanning；实际Raw/Silver job隔离集成 | 通过 |
| C3 原意图重执行 | 既有GraphQL+SDK | PG真实sensor、父run失败、FROM_FAILURE子run成功，asset仅1次/子run仅1项check | 通过 |
| C4 连续更新/两频交接 | 原Raw→通知→Silver链 | cli_worker_cancel_events_handoff_and_actual_daily_jobs；two_frequency_history_chain_and_native_anchor_completion | 通过 |
| C5 日期冻结 | _daily_intent_date | explicit_intent_date_never_uses_execution_clock；manual None跨日拒绝/同日及首次默认；partition错配拒绝 | 通过 |
| C6 key不吞当日更新 | 原sensor和原生reexecution | PG同key迭代不新增run但原run可明确续跑；两Raw sensor既有直接用例 | 通过 |
| D1 无额外业务动作 | events/confirm | 真实小producer后以业务SQL/hash/源哨兵确认只补状态；CLI正常/恢复/纯文件拒绝 | 通过 |
| D2 中断/取消/RSS | 原source/IO/执行器 | 原handoff_memory、memory_resume、storage/candidate取消退出用例，6GiB独立覆盖不变 | 通过 |
| D3 业务合同不变 | 原21列/Raw IO/Silver选择 | 原contracts/projection/jobs及精确Decimal/NULL/日期/上市边界金样本；未知未选文件不误拦 | 通过 |
| D4 隔离/清理 | 临时根/instance/PG | 临时PG受控关闭并删；所有测试显式临时Lake，未访问正式环境；见cleanup.json | 通过 |

## 成本与真实性边界

- 当前同版确认：**2文件与100文件均3条SQL**（单频通知1+物化集合1+检查集合1）；两频exact pair为4条。100项最新失败也在同样查询数内拒绝。
- 相同后继manifest/complete与原complete均实际读取一次；同频候选清单在2/100个metadata目标时都只读一次，总JSON读取N+2。缓存后文件身份变化拒绝。
- ack在2/100项、CP存在/缺失四种场景验证线性stat界；入口/phase/pending提交前仍做完整控制核验，逐项补写只核相关控制和目标/后继。
- 100项容量测试使用明确声明的合成metadata及stat替身，**不声称验收100份实际行情内容**；所有SQL/真实结果事件/排序/坏结果拒绝在真实临时SQLite上执行。真实文件/身份/后继/中断证明另用1股、两频少数小文件的实际Raw producer。
- 隔离PG18.4验证共享SQL及SDK/GraphQL/sensor重执行合同；PG job是最小业务夹具。实际Raw下载/控制链与Silver链另在真实临时文件/SDK及localhost假源集成中验收。没有声称在正式319run或正式Lake上试跑通过。
- 正式数据读取、Tushare/Prod请求、正式状态修复、补数、重载/部署、正式sensor/cursor操作均未执行。未来正式补数仍须按实际变更清单核定并批准历史读写范围。
- 现有SDK弃用/preview及隔离workspace清理警告仍出现在原测试日志，未通过过滤警告改变断言；未因此升级依赖。

## 独立复核与下一步

使用CodeGraph status/search/impact、sync及当前源码核入口/调用方/测试，无跨Prod/API/前端迁移。独立审查发现的集合查询、共享清单读取、线性stat、ack根/设备和日期/分区绑定问题已逐项修正并加反例；固定生产版本验证后未留下已知阻塞实现项。

默认Ruff（本次全部Python文件）、src/tests致命错误基线、文档/新增链接、git diff检查通过；这些只证明各自范围，不代替正式执行。

按管理员要求停在开发交付：**本轮不执行共享LLD12.11正式旧待办收尾，也不执行12.12真实补数。** 后续若获准，先做原events动作的精确预核与收尾，再沿原失败job/原日期继续，不重置cursor、不删除pending、不重做bootstrap。
