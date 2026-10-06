# M9 共享源异常分类修订验收

2026-10-07纠偏说明：本报告保留历史结论；搬运/审计中间数据文件已按管理员要求清理，不再是正式检查或调度依赖。现行口径为 bootstrap 完整对账一次即结束、日常只检查当前新增周期。详见[清理记录](stock_period_reports_cleanup_20261003.md#2026-10-07运行依赖纠偏及清理)。

2026-10-06，Asia/Shanghai。管理员确认“先补齐异常分类”，依据[上轮排查](stock_week_m9_failure_diagnosis_20261005.md)和[周线LLD已确认修订](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)。本轮完成分类开发和隔离验收；原正式 run 的具体失败原因仍无法追溯，M9正式更新、取消恢复和19:30启用未完成。

## 结果与代码落点

- `defs/stock_weekly_source.py`：共享监督子进程只传固定分类，区分代理、TLS、网络超时/连接、请求错误、响应解码/结构、依赖/类型/值错误及未知；父进程EOF、退出、监督超时和终止失败另有固定分类。`source_failed/source_timeout`等外层reason不变，通过`source_diagnostic=<category>`异常note补充诊断。
- 子进程IPC统一迁移为reason/frame/category三元组，唯一父进程接收点已同步；不保留旧IPC分支。没有转发异常原文、任意类名、URL、token或密码；SDK通用业务Exception仍归unknown，不根据敏感字符串猜测权限/限流。响应结构异常使用当前资源已声明的类型，诊断本身不重复导入失败的资源模块。
- `defs/stock_monthly_point.py`：转换为月线错误或同次执行重试耗尽时，仅复制经验证的安全分类。不同页不继承旧页失败。进程退出后旧账本没有分类时不伪造、不增加请求；原预算和账本格式保持现行语义。
- 周线point和备用capture原样抛出最后一次共享错误，已由测试确认note保留；不新增旁路拉取或独立状态实体。

改动文件为上述两个实现、`tests/stock_weekly_capture_test_support.py`及三个source/weekly-update/monthly-update测试文件；同步周线方案、周线LLD及月线LLD，新增本验收报告及真实只读JSON证据。没有修改asset/resource/check/job/sensor/partition定义、配置、Raw字段/文件路径、src依赖矩阵。CodeGraph explore覆盖capture→监督请求链；实际引用核对补齐以默认fetch函数注入的周/月point，未涉及前端/API消费者。

## 验证及性能对账

| 验证 | 实际结果 |
| --- | --- |
| 共享source、周线更新、月线更新 | 127项通过，35.48秒 |
| 新增资源导入失败分类反例、相邻capture/history/definitions | 41项通过，5.15秒 |
| 原OS隔离启动器完整test_run_contract_static_gates.py | 113项、15批全部通过，无过滤或扩大文件/网络权限 |
| 修改的6个Python文件完整Ruff；全src/tests致命错误基线 | 通过 |
| 单页真实只读源审计 | 00:15当前资源配置+实际监督worker，stk_weekly_monthly返回5565行完整13列 |

隔离测试验证真实spawn、EOF/退出和超时终止、取消、成功空响应、结构/行数拒绝、三类消费者、重试与续跑预算、未知业务错误及恶意消息/URL/自定义类名泄露防护。Dagster的SerializableErrorInfo实测可见分类note，合成凭据不进入序列化失败信息；未用正式instance/token作为测试用例。首次定向测试发现requests解码异常使用当前环境的JSON类型，已显式覆盖requests与stdlib两种JSONDecodeError后通过，未删除断言。

静态门禁使用现有项目.venv及原受保护启动器；外层沙箱不支持嵌套sandbox-exec，按工具权限提权启动，子进程仍禁止网络和正式资源。既有Pydantic弃用、partitioned-check预览、context.run_id弃用警告不是本轮故障。

分类增量为失败时常数次类型判断与一个有界短字符串，不额外读取响应body、不新增DataFrame/SQL/文件扫描或spill，原请求、限流、事务、候选提升及checkpoint不变。开发/隔离阶段正式请求及写入为0；真实源审计仅1页、limit6000/offset0，未产生任何正式写入。详见真实源只读证据（历史中间文件已清理）。

## 剩余事项

本轮未重跑正式job、注册分区、写正式事件/cursor、清理或提高原账本预算，也未启用19:30 sensor。代码尚未提交、未推送，未要求reload code location。下次正式执行前应确认加载当前修订，并明确合法执行意图、已耗尽账本的处理口径和精确执行清单；不能靠更换意图绕过失败预算。源仍成功意味着原错误未复现，不能把分类落地当作原故障已根治。

管理员随后要求提交，并确认已经重新加载新代码。上述开发结果及10月5日预检/失败记录一并按明确文件清单提交；不再次reload，不推送。随后继续同一周两主源交付前，刷新只读预检并记录实际10月6日每日意图和精确命令；旧10月5日账本保留，不重置。
