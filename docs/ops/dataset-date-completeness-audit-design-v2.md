# 日期完整性与日期对象矩阵审计说明

- 状态：现行代码机制说明；不是生产验收结论。
- 核对日期：2026-09-09。
- 范围：Ops 审查中心的数据集审计；不涉及 DG Lake 审计。
- 本文合并原日期桶方案、对象矩阵方案及性能专项，保留原主文档路径。内容去向及历史恢复方式见[整合记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-date-completeness-consolidation-20260909)。

## 1. 查什么，事实从哪里来

| 审计类型 | 回答的问题 | 规则和读取来源 |
|---|---|---|
| `date_bucket` | 指定范围应有的日期桶是否都有数据 | `DatasetDefinition.date_model` 规划日期；`storage.target_table/row_identity_filters` 和 `observed_field` 确定目标记录 |
| `date_subject_matrix` | 每个期望日期、每个期望对象是否都有记录 | 在日期规则之上，按 `DatasetDefinition.completeness` 读取对象池并与目标表比对 |
| Freshness（另一能力） | 最新数据是否滞后 | 见 [Freshness 契约](/Users/congming/github/goldenshare/docs/ops/ops-freshness-policy-explicit-mapping-plan-v1.md)，不能替代范围缺口检查 |

审计不检查字段值是否正确，也不证明数据源本身完整。不适用的数据集只在规则列表显示原因，正常提交入口拒绝创建 run。日期输入语义、预期日期和 freshness 不能混为一谈，基础定义见[日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。

“独立审计”指审计 run 和结果使用自己的模型，不是禁止与其他 Ops 能力交互：

- 规则列表从 `ops.dataset_status_snapshot` 获取已观测范围用于展示；这不是本次审计通过与否的证据，也不是 Kopia 备份。
- 审计执行器只读业务目标表，写审计状态和缺口表，不主动刷新 freshness 或 snapshot。
- worker 完成审计后存在指数补漏后处理，可创建标准维护 TaskRun；详见[指数日线完整性、补漏与激活池说明](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-reconciliation-plan-v2.md)。不能把整条 worker 链路称为“纯只读、绝不创建维护任务”。

截至核对日，注册表有 94 个数据集，52 个声明日期审计适用、42 个不适用，其中 6 个配置对象矩阵。数字是代码盘点，不是新增数据集准入条件；实际清单由注册表和规则 API 提供，不维护第二份全量名单。

## 2. 日期桶规则

实现入口：[ExpectedBucketPlanner、ActualBucketReader、GapDetector](/Users/congming/github/goldenshare/src/ops/services/date_completeness_audit_service.py)。

| `date_axis` | 支持的 `bucket_rule` | 含义 |
|---|---|---|
| `trade_open_day` | `every_open_day` | 范围内各开市日 |
| `trade_open_day` | `week_last_open_day` / `month_last_open_day` | 输入范围内按周／月分组的最后一个开市日 |
| `natural_day` | `every_natural_day` | 范围内每个自然日 |
| `natural_day` | `week_friday` / `month_last_calendar_day` | 自然周五／自然月末，不是最后交易日 |
| `month_key` | `every_natural_month` | 范围所覆盖的月份，标签为 YYYYMM |
| `month_window` | `month_window_has_data` | 范围所覆盖的月份，窗口内有记录即覆盖 |
| `none` 或 `not_applicable` | 不生成期望桶 | 正常创建入口还会检查 `audit_applicable` 和观测字段；不能据此推出“不支持时间输入” |

重要边界：

1. 周／月范围不完整时，交易日分组只在输入范围内取最后一天，不自动承诺完整自然周／月的末交易日。
2. `bucket_window_rule=iso_week/natural_month` 配合 `requires_open_trade_day_in_bucket`，会用完整周／月日历判断是否可产出；没有开市日的候选桶记为排除，原因 `bucket_has_no_open_trade_day`，不是缺口。
3. 股票周／月线及复权周／月线通过 Definition 的频率过滤区分共用表。不能丢掉 `row_identity_filters`，也不能用节假日白名单掩盖缺失。
4. 实际记录按请求起止范围读取；`month_key` 按 YYYYMM 比较，`month_window` 则把范围内读到的日期归入月份。后者不会自动扩大目标表读取范围到整月。
5. 日期缺口按“期望桶序列中的连续位置”压缩，不按自然日相邻压缩；区间样本最多 20 个。额外日期不导致当前日期桶审计失败，也不等于已完成异常日期集合审计。

目标标识符校验、参数绑定及行身份过滤由读取器处理，运营输入不能自行指定表名、SQL 或规则。

## 3. 对象矩阵与计数

当前六项配置如下；五个股票数据集共用执行方式，指数使用独立对象池，不能用 `ts_code` 同名推导池语义。

| 数据集 | 当前审计目标表 | 对象池策略 |
|---|---|---|
| `adj_factor` | `core.equity_adj_factor` | `stock_basic_active_lifecycle` |
| `daily` | `core_serving.equity_daily_bar` | 同上 |
| `daily_basic` | `core_serving.equity_daily_basic` | 同上 |
| `stk_factor_pro` | `core_serving.equity_factor_pro` | 同上 |
| `stk_limit` | `raw_tushare.stk_limit` | 同上 |
| `index_daily` | `core_serving.index_daily_serving` | `ops_index_series_active` |

- 股票池从现行证券基础表按配置状态筛选，再按每桶的上市／退市日期判断。当前配置为上市状态 L；生命周期边界允许为空，非空时要求上市日不晚于桶日期、退市日不早于桶日期。这是“当前池加生命周期”，不是历史时点全市场池。
- 指数池取 `index_daily` 当前激活对象；不套用股票上市状态和生命周期。请求池、Serving 激活池及补漏选择区别见指数专题。
- 当前只支持单字段对象键和上述两种策略。事件表不能因为有对象代码就启用矩阵；ETF、基金、板块、复合键需要分别确认对象池及产出语义。
- 股票矩阵没有自动排除停牌、源端不产出、上市首日等例外。发现缺口后要区分数据缺失与规则适配问题，不能直接认定必须补写业务数据。

SQL 按单个日期桶连接期望对象与目标表去重对象，返回该桶的检查行；Python 汇总覆盖与缺失计数，不构造全范围日期×对象笛卡尔积。跨桶仍保留受影响对象集合，内存不是绝对常量。

计数含义：

- `expected_cell_count`：各桶期望对象数之和；`actual_cell_count`：这些期望对象中已覆盖的数量，不是目标表总行数；`missing_cell_count`：两者差。
- `affected_bucket_count/affected_subject_count`：有缺对象的桶数／全范围去重缺失对象数；`actual_bucket_count`：至少覆盖一个期望对象的桶数。
- 当前矩阵结果按缺失 cell 判定；日期桶缺失数和日期缺口区间数写 0，不再独立跑一次日期桶缺口判断。因此期望对象池为空也可能 passed，不能把它解释成目标表已有数据。

对象明细包含日期、对象键／名称、目标键、生命周期、目标表及 `missing_subject_bucket` 原因。全 run 最多持久化 5,000 条明细，无独立“每桶明细上限”；完整缺失计数不受此预算截断。桶摘要样本最多 20 个，但取自剩余明细预算：预算耗尽后的桶仍有缺失计数，样本可以为空。`detail_truncated` 只表示服务端明细截断，不代表页面已显示全部已存明细。

## 4. 执行、进度与安全限制

入口为[创建服务](/Users/congming/github/goldenshare/src/ops/services/date_completeness_run_service.py)和[审计执行器／worker](/Users/congming/github/goldenshare/src/ops/services/date_completeness_audit_service.py)。

正常过程：创建 queued → worker 取队列 → running、规划日期 → 日期桶读取或逐桶矩阵 → 保存结果。审计状态与数据结论是两层：

| `run_status / result_status` | 解释 |
|---|---|
| `queued或running / null` | 尚未形成最终结论 |
| `succeeded / passed` | 执行完成，按该审计口径未发现缺口 |
| `succeeded / failed` | 执行完成，发现缺口，不是程序执行失败 |
| `failed / error` | 执行异常，不能把已写部分结果当完整结论 |

当前保护措施及其边界：

1. 矩阵上限为 **400 个期望日期桶**，不适用于普通日期桶审计。手动创建时先检查；调度／系统创建不在入队前执行同一范围门禁，但执行器会在读取目标数据前检查。400 不是 cell 数、总耗时或内存上限。
2. 矩阵在每桶开始时提交当前桶、已完成量和心跳，在每桶完成时提交缺口、累计计数、进度和心跳；不是每 5–10 桶才提交。单条 SQL 内没有持续心跳线程。
3. PostgreSQL 矩阵每桶使用事务局部 `statement_timeout='60s'`；其他数据库分支不设置。它限制单条语句，不承诺整个桶／整个任务在 60 秒内结束。
4. 普通异常走回滚当前事务、记录 failed/error 的路径；已提交桶保留。业务读取与审计写入使用同一个 Session，不能写成“完全不占用数据库事务”；审计不写业务表，也不撤销同步任务已经提交的数据。
5. 创建 run 保存日期规则、目标表、行过滤、审计 scope 等，但执行矩阵时仍读取当前 Definition 的 completeness 和当前对象池；不是所有规则和池的不可变快照，也不是整个审计期间冻结业务数据。并发同步或配置变化可能影响跨桶一致性。
6. **未实现可靠取消／断点续跑。** 模型允许 canceled 不代表已有取消 API；强杀进程不保证进入终态。worker 只领取 queued，不自动接管遗留 running；再次直接执行同一 run 会清理旧结果重算，不是从已完成桶接着跑。
7. queued 领取没有原子抢占／排他领取保证，不能因存在独立 worker 就默认允许多实例并发消费同一队列。

第 5–7 项是当前限制，不是批准的目标设计。本文不把它们写成“已解决”，也不借文档整理实施改造；若后续改执行机制，需另行确认方案并遵守根规则中的长任务门禁。

## 5. API、持久化与调度

[路由](/Users/congming/github/goldenshare/src/ops/api/date_completeness.py)统一位于 `/api/v1/ops/review/date-completeness`，要求管理员权限；完整字段以[请求／响应模型](/Users/congming/github/goldenshare/src/ops/schemas/date_completeness.py)为准，不再复制整份 DDL。

| 接口（省略前缀） | 有效输入／响应要点 |
|---|---|
| GET `/rules` | 分组规则、支持原因和已观测范围 |
| POST `/runs` | `dataset_key/start_date/end_date`；创建响应为 `id/run_status/dataset_key/display_name/start_date/end_date/requested_at`，不是 `run_id` |
| GET `/runs` | 可筛 `dataset_key/run_status/result_status`；`limit=20`、最大 200，`offset=0`；没有日期过滤或 `page/page_size` |
| GET `/runs/{run_id}` | 单次运行、汇总、进度、错误信息 |
| GET `/runs/{run_id}/gaps或exclusions或subject-gaps或subject-gap-details` | 四个独立子资源；`limit=200`、最大 500，`offset=0` |
| GET／POST `/schedules` | 列表／创建；列表筛 `status/dataset_key`，`limit=50`、最大 200，`offset=0` |
| GET／PATCH／DELETE `/schedules/{schedule_id}` | 查询／修改／删除自动审计配置 |
| POST `/schedules/{schedule_id}/pause或resume` | 两个独立操作；不取消已入队或运行中的审计 |
| POST `/schedules/tick` | `limit=100`、最大 1,000；响应 `scheduled/run_ids` |

持久化在 `ops` 下的六张专用表：`dataset_date_completeness_run` 保存运行，`dataset_date_completeness_gap` 保存日期缺口区间，`dataset_date_completeness_exclusion` 保存排除日期，`dataset_subject_completeness_gap` 保存每桶对象缺口摘要，`dataset_subject_completeness_gap_detail` 保存对象明细，`dataset_date_completeness_schedule` 保存自动审计配置。

自动审计配置是现行专用对象，**不等于数据维护的 `ops.schedule`**。其[服务实现](/Users/congming/github/goldenshare/src/ops/services/date_completeness_schedule_service.py)支持：

- 固定范围：按 cron 重复审计相同起止日期。
- 滚动范围：正整数 `lookback_count` 配合 `calendar_day/open_day/month`；按调度时区计算当天，月窗口覆盖整月，末月可包含当天之后日期。
- 当前只接受 `default_cn_market/cn_a_share`，且 `calendar_exchange` 必须为空，使用设置中的默认交易所。底层虽有 custom_exchange 分支，正常创建／更新入口会拒绝它，不能宣传支持自定义交易所。
- tick 计算窗口、查询必要日历并入队，不读取目标数据表。它已接入常规 OperationsScheduler，不需要另造一套调度进程。index_daily 的当天开市单日约束及系统再审计由指数专题说明。

CLI 保持现行入口，命令都不是只读预览：

| `goldenshare` 子命令 | 默认参数与作用 |
|---|---|
| `ops-date-completeness-worker-run` | `--limit 1`，消费队列 |
| `ops-date-completeness-scheduler-tick` | `--limit 100`，到期配置入队 |
| `ops-date-completeness-worker-serve` | 每轮 `--limit 5`、`--sleep-seconds 10`；可用 `--max-cycles` 限制轮数 |

参数定义见 [CLI](/Users/congming/github/goldenshare/src/cli.py)。`--limit 1` 不是按某个 run 隔离测试，会领取队列中的任务；执行前必须确认环境、队列及业务授权。已有 [systemd 单元](/Users/congming/github/goldenshare/scripts/goldenshare-date-completeness-worker.service)只是部署入口证据，不证明当前服务器已经部署或正在运行；进程自动重启也不等于业务断点恢复。

## 6. 页面现状

入口：审查中心 → 数据集审计；[页面实现](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-dataset-audit-page.tsx)有“审计数据集、审计记录、自动审计”三个 Tab。规则分组、审计类型、时间范围、汇总和缺口都消费后端口径，不在页面复制对象池或日期规划规则。

当前展示边界：

- 审计记录只请求最近 50 条；这批记录中有 queued/running 时每 3 秒刷新列表。
- 打开的详情保存的是点击时选中的记录；缺口按所选 run 加载，未配置轮询。列表轮询不会同步更新已选记录；查询库可能触发缺口重新请求，也不能据此承诺抽屉持续展示最新汇总。
- 缺口接口支持分页，但当前详情每类只请求首批 200 条，没有完整翻页加载；不能因 `detail_truncated=false` 就认为画面展示了全部明细。
- 心跳超过 5 分钟的 running 记录会显示警告，不会自动清理运行态或恢复任务；没有可信 ETA 承诺。
- 页面“额外日期”取 `max(actual_bucket_count - expected_bucket_count, 0)`，不是实际桶减期望桶的集合。它不能完整识别“同时有额外日期和缺失日期”的情况。
- 当前表单初始日期是固定的 2026-04-20 至 2026-04-24，不是自动取今天或已采纳的滚动默认窗口；执行前应核对实际选择范围。

原[页面设计](/Users/congming/github/goldenshare/docs/frontend/frontend-date-completeness-audit-page-design-v1.md)保留第一期交互历史，不能再用其“只查日期桶”或刷新承诺代替以上事实。

## 7. 历史证据与后续验收边界

以下是从原文迁入的**历史记录，未在本轮连接数据库重验**；原文全文可从合并前提交 `1fa6dd1a` 追溯。

| 日期／记录 | 当时证据 | 不能据此推出什么 |
|---|---|---|
| 2026-05-03，原日期桶 M7 | 记录了本地手动、worker、自动配置／tick、股票周月长假排除验证；原 M8 远程验证待做 | 不能推定远程验收已完成 |
| 2026-05-17，run 27 | 本地代码连接远程 DB，stk_limit 审计 2026-05-15；期望 5,517、覆盖 5,517、缺失 0，passed | 池外额外对象不参与该缺失判断；不是当前 Raw 目标的性能实测 |
| 2026-05-17，run 28 | 同样环境，stk_factor_pro 审计 2026-05-15；期望 5,517、覆盖 5,493、缺失 24，明细未截断 | 未解释完缺口原因；不是源端必定应产出 24 行的证据 |
| 2026-05-17，run 29 | stk_factor_pro 范围 2025-01-02 至 2026-05-15，328 个交易日，估计 1,778,629 cell、目标范围 1,823,978 行；运行超过 77 分钟后取消数据库 SQL，终态 failed/error、QueryCanceled | 这是旧大矩阵事故，不是当前逐桶实现耗时，也不是正常取消 API 验收 |

原方案从重复计算全范围矩阵改为逐桶计算，临时 30 桶门禁现为 400 桶。原性能专项文首写“M4 待评审”，正文却写“M4 本轮落地”；本轮以代码确认 400 桶机制已存在，但原文未提供可独立确认的改造后年度全流程耗时，不能补写已验收。

原 M3 在 2026-05-17 对 2026-05-15 单桶执行生产只读 EXPLAIN 的记录如下；均为当时 trade_date 索引加 heap 的访问路径，不是本轮测量：

| 数据集 | 当时表大小 | 单表对象读取 | 单桶矩阵查询 |
|---|---:|---:|---:|
| adj_factor | 2,028 MB | 3.237 ms | 16.431 ms |
| daily | 3,468 MB | 3.399 ms | 16.517 ms |
| daily_basic | 4,320 MB | 3.543 ms | 16.885 ms |
| stk_limit（旧 `core_serving.equity_stk_limit`） | 541 MB | 5.081 ms | 18.782 ms |
| stk_factor_pro | 5,131 MB | 6.460 ms | 19.529 ms |

当时未新增索引；stk_factor_pro 读取涉及 2,077 个 heap block，覆盖索引只是候选。当前 stk_limit 的审计目标已是 Raw，不能把旧 Serving 表的测量改名复用。原“年度 1–5 分钟”是优化目标，不是已经实现的 SLA 或本轮新增门禁。

若后续重启性能／可靠性改造，应先解释 run 28 类缺口的池与源端语义，再做受控代表性范围运行和年度测量；不直接扩大队列。只有实测需要时才评估覆盖索引／物化对象池：前者需单独审批、核对迁移 head、空间和非阻塞建索引方式，后者是未实施备选，不是现行事实源。本轮不创建新性能指标、不批准执行或索引变更。

## 8. 核对入口与回归重点

代码依据：前述服务、API 和页面，以及[规则查询](/Users/congming/github/goldenshare/src/ops/queries/date_completeness_query_service.py)、[结果查询](/Users/congming/github/goldenshare/src/ops/queries/date_completeness_run_query_service.py)、[注册表](/Users/congming/github/goldenshare/src/foundation/datasets/registry.py)。

现有测试入口：

- [规划器与缺口测试](/Users/congming/github/goldenshare/tests/test_date_completeness_audit_service.py)：开市日／自然日／月桶、范围边界、长假排除、缺口压缩。
- [模型测试](/Users/congming/github/goldenshare/tests/test_date_completeness_models.py)：独立审计模型及约束。
- [API 与执行测试](/Users/congming/github/goldenshare/tests/web/test_ops_date_completeness_api.py)：创建／查询／调度、矩阵／计数／明细／范围保护，覆盖程度以实际测试为准。

后续改造还应核验当前 Definition 目标和过滤、空池／生命周期边界、实际单桶查询、5,000 条预算后的摘要、400 桶创建与执行边界、异常后部分结果以及页面刷新。存在模型字段或替身测试不能证明取消、强杀续跑、多 worker 抢占和生产运行安全已经实现。

本次治理仅合并并纠正文档；验证文档结构、链接、引用和静态代码口径，不执行审计 worker、调度、业务同步、数据库写入或部署，也不把文档检查作为生产验收。
