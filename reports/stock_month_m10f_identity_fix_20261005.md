# 月线更新身份误阻断修复验收

2026-10-05，Asia/Shanghai。原月线身份阻断已解除：代码修复、隔离回归及正式2026-09只读门禁验收通过。管理员随后确认已加载修复代码，并要求提交修改。本轮由助手执行的范围不含正式更新job、code location reload、事件/cursor写入或调度启用，不能据此宣布M10.F整体完成。本报告随修复提交，未推送。

## 目标、依据与改动

管理员明确批准“按照你的建议做，主要是要把之前的阻断项解决掉”。沿原月线LLD§4，先同步LLD，再只修改source_readiness/stock_monthly.py及test_stock_monthly_update.py；同时在原周线方案/LLD记录关联状态。不增加T前缀专项接入/补录，不修改周线、Prod、历史身份、Raw业务值、入口参数、配置、原因码或分层依赖。退市历史保留口径仅限Raw周/月线，未来Silver规则未决定。

根因是月线消费者对完整历史身份表附加六位数字代码限制。合法历史自映射T600018.SH虽未被当月日线引用，仍阻断整个更新。不能删除身份行或将它归并到600018.SH消除症状。修改后全表保留结构与安全检查，格式限制仅用于实际引用的身份关系。

CodeGraph impact覆盖freeze_month_references→月线point _deliver/deliver_month_intent及定义测试；此前explore已追到身份生成、源请求、Raw写入与完成检查。两个月线asset的手动/自动更新共用该point路径。没有API/UI字段、DatasetDefinition、registry/asset图或跨子系统依赖变化。

## 硬口径逐项对账

| 已批准口径 | 实现 | 验证 |
|---|---|---|
| 无关历史代码不阻断、不改写 | freeze全表只查非空/唯一/预算，canonical仍保留原值 | 两源完整交付保留T600018.SH及600018.SH自映射，身份字节不变，Raw原代码不变 |
| 实际日线映射有效且confirmed | daily→identity join检查source/latest格式和confidence | 实际T代码、目标T/坏格式、inferred/NULL、缺失映射都在请求源前拒绝 |
| 实际返回的额外源对象也要校验 | verify_month_completion在source→canonical join检查两侧格式；canonical未确认映射为NULL | 无日线的000002.SZ若返回且目标T/未确认仍拒绝，不生成正式文件 |
| 全表结构安全不放宽 | trim非空、原唯一性、LIMIT max_codes+1及预算 | 全表NULL/空白、无关重复、超预算均拒绝 |
| 完整证据仍绑定 | 全文件hash/upstream blocking bindings/前后重复核对保持 | 无关身份行变化使整个参考hash失效；无上游binding仍拒绝；真实文件和事件绑定稳定 |
| Raw代码合同和周线保持 | 不修改Raw validator、weekly或身份资产 | 实际源T前缀仍由原Raw入口拒绝，周线无修改或补录 |
| 保持性能预算 | 向量化join增加格式谓词，没有新增查询或逐股循环 | 21文件/116588参考行/5571期望代码/6163身份键，真实只读完成0.522秒 |

## 验证结果

- 从orchestrator目录使用现有.venv：月线更新66项，定义/sensor22项，共88项通过。
- 原受保护启动器执行完整test_run_contract_static_gates.py：113项、15个批次全部通过，没有过滤失败项或扩大文件权限。
- 修改的两个Python文件完整Ruff，以及全src/tests致命基线E9/F63/F7/F82通过。
- docs integrity和git diff --check通过。
- 最初本地测试有新预算fixture未同步prod_code_batch及错误cwd造成的子进程tests导入失败；已修fixture并按目录规则运行，完整66项通过。首次受保护检查因外层沙箱禁止sandbox_apply而未启动；按工具提权方式从本机运行原启动器，它继续在子进程禁止正式文件及网络，全113项通过。没有安装依赖、改正式资源或放宽隔离策略。

## 正式只读证据

使用既有open_weekly_event_instance：固定DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home，禁用自动建表/启动器；仅查询已有upstream/check状态。Lake只读范围为完整身份文件、交易日历、2026-09的21个日线文件及两份当月Raw目标。DuckDB使用现行512MiB/2线程入口，Python只取有界身份/期望汇总，不逐分区扫描历史事件。

freeze_month_references真实返回116588日线行、5571期望代码、6163身份键；T600018.SH仍自映射但不在expected中。完整参考hash及上游materialization/check绑定前后稳定，原monthly_identity_invalid_or_over_budget不再出现。

两源2026-10-04已捕获全市场CSV各5571行，与真实9月参考执行verify_month_completion均ready。没有新源调用；这是已有源快照对当前正式参考的完成校验，不是2026-10-05实时下载或正式job验收。两源正式monthly_period_status仍ready。

身份文件SHA前后均03d4d4a8e17b9108696b124cb6fdc9174f012fde86b15e41c205563bc17c0dfb；两份正式Raw目标SHA前后不变。所有报告仅写仓库reports，正式Lake/instance写入0。精确数值、源CSV SHA、全部参考及上游绑定见[只读JSON](stock_month_m10f_identity_fix_preflight_20261005.json)。

## 剩余阶段

本轮按管理员要求在dev-interface提交修复、测试、原方案/LLD和审计证据，不推送；代码加载状态依据管理员本次“我已经加载了修复代码”的确认，助手不重复reload。M10.F后续仍需运行两源完整月job、核验源/正式目标及checks，再按原门禁启用19:30 sensor。此次加载确认不等于真实更新job或调度启用验收。M9周线正式更新验收仍单列，本次没有改变它。
