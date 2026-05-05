# 工程风险登记簿

状态：当前生效  
更新时间：2026-05-05
适用范围：代码改动前评估、提交前检查、P0/P1 风险收口。

---

## 1. 使用规则

1. 发现 P0 风险时，必须登记到本文件。
2. 存在未关闭 P0 风险时，不允许提交新的业务代码改动；只允许提交风险止血、验证、文档澄清或经明确评审批准的修复。
3. 风险关闭前，相关方案必须有文档依据、测试门禁和回归命令。
4. 关闭 P0 风险时，必须补充关闭依据、修复提交、验证结果和剩余风险。

---

## 2. 风险等级

| 等级 | 定义 | 处理要求 |
|---|---|---|
| P0 | 可能导致数据丢失、长任务白跑、线上不可用、不可恢复污染 | 立即止血，冻结相关大范围改动，先方案后代码 |
| P1 | 可能导致局部数据错误、明显性能/内存风险 | 进入近期计划，必须有门禁 |
| P2 | 可控缺陷或治理债务 | 排期处理，避免继续扩大 |

---

## 3. 当前未关闭风险

| ID | 等级 | 风险 | 影响范围 | 状态 | 依据 |
|---|---|---|---|---|---|
| RISK-2026-04-25-001 | P0 | 数据维护执行层若采用任务级最终提交，状态写入失败可导致已执行写入整体回滚 | `stk_mins`、`stk_factor_pro`、`dc_member`、`index_daily`、`index_weight` 等 P0/P1 数据集 | Closed | [DatasetExecutionPlan 执行计划模型重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md) |
| RISK-2026-04-25-002 | P0 | 数据维护请求链存在 `__ALL__` 哨兵值，可能进入请求参数、query 上下文或落库字段，造成主键碰撞和数据污染 | `dc_hot`、`ths_hot`、`kpl_list`、`limit_list_ths` 及所有使用 enum fanout / query context 的数据集 | Closed | [DatasetExecutionPlan 执行计划模型重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md) |
| RISK-2026-04-26-003 | P1 | 主数据/快照类 `not_applicable` 数据集被伪装成业务日期 freshness，或为修正该问题新增重复状态表/字段，导致状态口径膨胀和一致性风险 | `stock_basic`、`index_basic`、`ths_member`、`ths_index`、`etf_basic`、`etf_index`、`hk_basic`、`us_basic` 等主数据/快照类，以及 Ops freshness/status 页面 | Open | [Ops 新鲜度按 Date Model 收口方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-date-model-freshness-alignment-plan-v1.md)、[数据集日期模型消费指南 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md) |
| RISK-2026-04-26-004 | P1 | 旧同步状态模型若未在 Date Model Freshness 收口中彻底退场，会继续制造状态口径分裂和旧语义回流 | Ops freshness/status 页面、数据集卡片状态、状态重建命令、旧同步状态对账服务 | Closed | [Ops 新鲜度按 Date Model 收口方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-date-model-freshness-alignment-plan-v1.md) |
| RISK-2026-05-05-005 | P1 | `cadence` 作为低价值节奏标签仍残留在 Ops freshness/status/card 链路和前端展示中，容易制造语义误导，并阻碍 `date_model` 成为唯一时间事实源 | `DatasetDefinition.domain`、Ops freshness/status snapshot、数据源卡片 API、前端数据源页、相关报表导出 | Open | [`cadence` 退场清单 v1](/Users/congming/github/goldenshare/docs/governance/cadence-deprecation-checklist-v1.md) |

---

## 4. RISK-2026-04-25-001 处理要求

立即止血：

1. 开发时必须评估单个事务的写入量，做真实的计算。
2. 必须做真实评估。
3. UI/进度文案不得把未提交的 `written` 表述成已落库。

正式修复：

1. 在 DatasetExecutionPlan 单一模型中正式表达 data transaction policy。
2. 执行层拆分 data transaction 与 ops state transaction。
3. 只做 `per_unit` data transaction，不引入分页级提交策略。
4. 开发时必须评估单个事务的写入量，做真实的计算。
5. 单事务写入量评估必须有真实计算依据，不允许用分页或批量大小替代事务边界评估。
6. 删除主链分裂状态写入，改为单一成功状态写入接口。
7. 旧运行日志与旧同步状态必须退出主链，状态失败不得回滚业务数据。
8. 所有 Ops 状态写入必须与业务数据表读写和提交隔离；状态失败不得阻塞业务数据提交，也不得污染已提交业务数据。

关闭门禁：

1. 第 N 个 unit 失败时，前 N-1 个 unit 已提交且可观测。
2. ops state 写入失败时，业务数据不回滚。
3. 单个事务写入量评估必须有真实计算依据。
4. point/range/none 成功只写一次资源状态，且不得丢失业务日期。
5. 任务详情只把已提交数据展示为最终处理结果。
6. 测试必须模拟 Ops 状态写入失败，并证明业务数据表写入已提交、可读取、未被回滚。

处理记录（2026-05-04）：

1. 数据维护执行主链已按 unit 提交业务数据；第 N 个 unit 失败时只回滚当前未提交事务，已提交 unit 不再被后续状态写入回滚。
2. Ops 进度、TaskRun、snapshot/freshness 等状态写入与业务数据事务隔离；状态写入失败只影响观测状态，不影响业务提交。
3. 旧同步状态表、旧运行日志表、旧执行观测表不再作为主链事实源；远程库只保留 TaskRun 三表作为任务观测主线。
4. 已补回归测试 `test_ops_progress_failure_does_not_rollback_committed_business_rows`，模拟 Ops progress 写入失败，验证业务行已提交、未 rollback。
5. 本地验证：
   - `pytest -q tests/test_dataset_progress.py`
   - `pytest -q tests/web/test_ops_runtime.py tests/web/test_ops_task_run_api.py tests/architecture/test_dataset_maintenance_refactor_guardrails.py tests/architecture/test_subsystem_dependency_matrix.py`
   - `GOLDENSHARE_ENV_FILE=.env.web.local python3 -m src.cli ingestion-lint-definitions`

---

## 5. RISK-2026-04-25-002 处理要求

立即止血：

1. `dc_hot`、`ths_hot`、`kpl_list`、`limit_list_ths` 不允许再把 `__ALL__` 作为默认筛选值、请求参数值或 query 上下文字段值。
2. 全选必须在 planner 阶段展开为真实业务枚举值；不得传一个模糊的 `__ALL__` 到 source adapter、normalizer、writer 或落库行。
3. 如果 planner 无法枚举真实业务值，必须拒绝执行或进入 dry-run/preview，不得使用 `__ALL__` 兜底。
4. 已知会写出 `query_market/query_hot_type/query_is_new/query_limit_type` 的数据集，必须保证这些字段来自真实请求上下文，而不是 `__ALL__`。

正式修复：

1. 删除数据维护主链中 `__ALL__` 作为业务哨兵的逻辑。
2. `enum_fanout_defaults` 只能配置真实业务枚举集合，不能配置 `("__ALL__",)`。
3. `param_format`、`param_policies` 不再把 `__ALL__` 解释成“跳过筛选项”。
4. Source adapter 不再给 `query_*` 字段注入 `__ALL__`。
5. `row_transforms` 不再以 `__ALL__` 兜底 query context。
6. 补架构测试，禁止 `__ALL__` 出现在数据维护主链代码、plan unit request params、normalized rows 和落库 query 字段中。

关闭门禁：

1. `dc_hot` 缺省筛选时会显式扇出真实 `market + hot_type + is_new` 组合。
2. `ths_hot` 缺省筛选时会显式扇出真实 `market + is_new` 组合。
3. `kpl_list` 缺省筛选时要么显式扇出真实 `tag`，要么不传 `tag` 且不写 `__ALL__`。
4. `limit_list_ths` 缺省筛选时要么显式扇出真实 `limit_type + market`，要么不传对应筛选且不写 `__ALL__`。
5. `rg "__ALL__" src/foundation src/ops tests frontend/src/pages/ops-v21-task-manual-tab.test.tsx` 不得发现业务哨兵残留；如保留测试说明，必须有明确 allowlist 和关闭日期。
6. 远程/本地验证至少覆盖 `dc_hot` 一次默认提交，落库结果不得出现任何 `query_*='__ALL__'`。

处理记录（2026-04-26）：

1. 远程库审计入口：`bash scripts/psql-remote.sh`。
2. 精确 `__ALL__` 与模糊 `%ALL%` 审计结果一致；`dc_hot`、`kpl_list` 未发现脏行。
3. 已删除远程库中的 `__ALL__` 脏行，并在删除后复查 `%ALL%` 命中数为 0。

| 数据集 | 表 | 删除行数 | 需要重新同步的日期 |
| --- | --- | ---: | --- |
| `limit_list_ths` | `raw_tushare.limit_list_ths` | 5485 | 2026-01-05, 2026-01-06, 2026-01-07, 2026-01-08, 2026-01-09, 2026-01-12, 2026-01-13, 2026-01-14, 2026-01-15, 2026-01-16, 2026-01-19, 2026-01-20, 2026-01-21, 2026-01-22, 2026-01-23, 2026-01-26, 2026-01-27, 2026-01-28, 2026-01-29, 2026-01-30, 2026-02-02, 2026-02-03, 2026-02-04, 2026-02-05, 2026-02-06, 2026-02-09, 2026-02-10, 2026-02-11, 2026-02-12, 2026-02-13, 2026-02-24, 2026-02-25, 2026-02-26, 2026-02-27, 2026-03-02, 2026-03-03, 2026-03-04, 2026-03-05, 2026-03-06, 2026-03-09, 2026-03-10, 2026-03-11, 2026-03-12, 2026-03-13, 2026-03-16, 2026-03-17, 2026-03-18, 2026-03-19, 2026-03-20, 2026-03-23, 2026-03-24, 2026-03-25, 2026-03-26, 2026-03-27, 2026-03-30, 2026-03-31, 2026-04-01, 2026-04-02, 2026-04-03, 2026-04-07, 2026-04-08, 2026-04-09, 2026-04-10, 2026-04-13, 2026-04-14, 2026-04-15, 2026-04-16, 2026-04-17, 2026-04-20 |
| `limit_list_ths` | `core_serving.limit_list_ths` | 5485 | 同上 |
| `ths_hot` | `raw_tushare.ths_hot` | 2664 | 2026-04-10, 2026-04-17 |
| `ths_hot` | `core_serving.ths_hot` | 2664 | 同上 |

关闭记录（2026-05-04）：

1. 活跃代码中不再存在业务哨兵 `__ALL__`；唯一命中是 `tests/test_dataset_request_validator.py` 中的拒绝输入测试。
2. `dc_hot`、`ths_hot`、`kpl_list`、`limit_list_ths` 的缺省筛选均通过 `enum_fanout_defaults` 展开为真实业务枚举值。
3. planner、plan unit request params、normalizer、writer 均有禁用哨兵拦截。
4. 远程库复查 `raw_tushare` 与 `core_serving` 中相关 `query_* / tag` 字段，精确 `__ALL__` 与模糊 `%ALL%` 命中数均为 0。
5. 本地验证：
   - `pytest -q tests/test_dataset_action_resolver.py tests/test_dataset_request_validator.py tests/test_dataset_definition_registry.py tests/architecture/test_dataset_runtime_registry_guardrails.py tests/architecture/test_dataset_maintenance_refactor_guardrails.py`

---

## 6. RISK-2026-04-26-003 处理要求

风险说明：

1. `date_model.bucket_rule=not_applicable` 的主数据/快照类没有连续业务日期 bucket，不应被包装成“业务日期新鲜度”。
2. 不能为了修这个问题新增一组重复的状态表、策略表或影子字段，把同一份状态在多个地方复制。
3. DatasetDefinition 只保存数据集静态事实，不放 Ops 健康判断状态，也不放会随运行变化的派生结果。

处理要求：

1. 当前 date model freshness 收口只处理日期型 bucket 规则，不扩展主数据/快照类健康模型。
2. 如后续处理主数据/快照类，只能基于单一事实源现场计算，或复用唯一的可重建 Ops 投影；不得新增并行状态副本。
3. 任何新增表、字段或策略配置前，必须先单独出方案评审，说明为什么现有事实源和现有投影无法满足。
4. `not_applicable` 数据集不得伪造 `expected_business_date / lag_days` 来表达健康状态。

关闭门禁：

1. Ops 页面不再把主数据/快照类展示为业务日期滞后。
2. 不新增重复状态表或重复字段；如确需 schema 变更，必须有独立评审文档和迁移方案。
3. `DatasetDefinition` 保持无状态，只表达数据集事实和能力，不承载 Ops 运行状态。

---

## 7. RISK-2026-04-26-004 处理要求

风险说明：

1. 旧同步状态模型以任务名维度记录最近成功日期、成功时间、游标和全量标记。
2. 该模型与当前 DatasetDefinition、Date Model、TaskRun 运行观测主线不一致。
3. 如果 Date Model Freshness 收口后仍保留它作为事实源，会让数据集卡片、新鲜度状态、任务结果和资源状态继续出现多套口径。
4. 全量标记和游标这类旧语义容易重新引入旧状态判断，造成后续架构回流。

处理要求：

1. 本轮 TaskRun/current object 运行观测重置中，旧同步状态表只能清空，不得新增依赖。
2. TaskRun 详情、当前对象、问题诊断、任务结果不允许读取旧同步状态表。
3. Date Model Freshness 收口必须审计所有旧同步状态 ORM、service、CLI、测试和文档引用。
4. 数据集新鲜度与资源状态必须基于 DatasetDefinition Date Model 和真实业务表观测结果，不再基于历史任务名状态行。
5. 删除旧同步状态 ORM 与仅服务旧状态表的 reconciliation/service 代码。
6. 删除旧同步状态数据库表。
7. 更新 docs/AGENTS 或相关基线文档，禁止新代码重新引入旧同步状态模型。

关闭门禁：

1. 当前主链不再引用旧同步状态模型；历史归档文档如保留，必须明确标注历史背景。
2. 线上数据库不存在旧同步状态表。
3. 数据集卡片状态和 freshness API 不读取旧同步状态表。
4. 状态重建命令不写旧同步状态表。
5. 运行一个小范围数据集维护任务后，TaskRun 详情、数据集卡片、freshness 状态均能从新事实源得到一致结果。

处理记录（2026-04-26）：

1. 已删除旧同步状态 ORM、旧 reconciliation service 与旧 DAO。
2. 已删除旧同步状态对账 CLI，并移除相关旧对账调用。
3. 已把 freshness/status 主链改为只读 `真实业务表 + TaskRun / TaskRunNode / TaskRunIssue`。
4. 已删除数据集状态快照与 freshness API 中的旧状态字段。
5. 已新增 Alembic 迁移，用于删除旧同步状态表并删除快照旧列。
6. 本地验证已通过：
   - `pytest -q tests/web/test_ops_freshness_api.py tests/web/test_ops_overview_api.py tests/test_ops_freshness_snapshot_query_service.py tests/test_dataset_status_snapshot_service.py tests/test_cli_ops_runtime.py tests/test_base_sync_service_snapshot_refresh.py`
   - `pytest -q tests/architecture/test_subsystem_dependency_matrix.py`
   - `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare ingestion-lint-definitions`
   - `cd frontend && npm test -- --run src/pages/ops-v21-source-page.test.tsx src/pages/ops-v21-dataset-detail-page.test.tsx`

---

## 8. RISK-2026-05-05-005 处理要求

风险说明：

1. `cadence` 对用户价值很低，但当前仍以字段形式进入后端投影、snapshot、API 和前端页面。
2. freshness/status 链路仍保留部分基于 `cadence` 的兜底逻辑，导致 `date_model` 尚未成为唯一时间事实源。
3. 如果继续放任 `cadence` 存在，后续新数据集接入或前端展示容易继续误用这类“抽象节奏标签”。

处理要求：

1. 先完成当前 5 个新数据集接入，再单独推进 `cadence` 退场。
2. 退场方案必须以 [`cadence` 退场清单 v1](/Users/congming/github/goldenshare/docs/governance/cadence-deprecation-checklist-v1.md) 为唯一执行依据。
3. 退场时不得新增新的节奏镜像字段、影子表或兼容层。
4. freshness、expected business date、lag 判断必须最终完全收口到 `date_model`。
5. 前端用户界面必须移除 `cadence` 可见展示。

关闭门禁：

1. 前端页面不再显示 `cadence / cadence_display_name`。
2. freshness / snapshot / dataset card API 不再返回 `cadence`。
3. `ops.dataset_status_snapshot` 不再保存 `cadence`。
4. `DatasetDefinition.domain` 不再包含 `cadence`。
5. `rg "\\bcadence\\b" src frontend docs tests` 只允许命中历史归档文档或本专项退场文档。
