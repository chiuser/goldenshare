# 工程风险登记簿

状态：当前生效  
更新时间：2026-05-24
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
| RISK-2026-04-26-003 | P1 | 主数据/快照类 `not_applicable` 数据集被伪装成业务日期 freshness，或为修正该问题新增重复状态表/字段，导致状态口径膨胀和一致性风险 | `stock_basic`、`index_basic`、`ths_member`、`ths_index`、`etf_basic`、`etf_index`、`hk_basic`、`us_basic` 等主数据/快照类，以及 Ops freshness/status 页面 | Closed | [Ops Freshness Policy 显式映射方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-freshness-policy-explicit-mapping-plan-v1.md)、[数据集日期模型消费指南 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md) |
| RISK-2026-04-26-004 | P1 | 旧同步状态模型若未在 Date Model Freshness 收口中彻底退场，会继续制造状态口径分裂和旧语义回流 | Ops freshness/status 页面、数据集卡片状态、状态重建命令、旧同步状态对账服务 | Closed | [Ops 新鲜度按 Date Model 收口方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-date-model-freshness-alignment-plan-v1.md) |
| RISK-2026-05-05-005 | P1 | `cadence` 作为低价值节奏标签仍残留在 Ops freshness/status/card 链路和前端展示中，容易制造语义误导，并阻碍 `date_model` 成为唯一时间事实源 | `DatasetDefinition.domain`、Ops freshness/status snapshot、数据源卡片 API、前端数据源页、相关报表导出 | Closed | [`cadence` 退场清单 v1](/Users/congming/github/goldenshare/docs/governance/cadence-deprecation-checklist-v1.md)、[Ops Freshness Policy 显式映射方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-freshness-policy-explicit-mapping-plan-v1.md) |
| RISK-2026-05-08-006 | P1 | 指数日线存在双表并行语义（`core.index_daily_bar` 遗留表 与 `core_serving.index_daily_serving` 现行表），易被误读/误用，导致查询口径漂移、页面数据不一致和后续扩展错接表 | Wealth 市场总览（主要指数）、Biz 指数查询、Ops review/状态核查、文档与开发认知 | Closed | [市场总览数据对象与 API 设计 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-overview-api-model-design-v1.md)、[index series 定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py) |
| RISK-2026-05-11-007 | P0 | Lake `stk_mins` 旧单股票补数路径曾整分区替换 `raw_tushare/stk_mins_by_date/freq=*/trade_date=*`，已确认 `freq=1` 大面积 raw 分区被覆盖为单股票数据，`freq=5` 局部受损 | 本地 Lake `raw_tushare/stk_mins_by_date`，重点 `freq=1`、`freq=5`；后续 MACD/研究层计算依赖的分钟线事实 | Closed | [stk_mins Parquet Lake 方案](/Users/congming/github/goldenshare/docs/datasets/stk-mins-parquet-lake-plan-v1.md)、[Local Lake 持久备份与恢复管理方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-write-recovery-management-plan-v1.md) |
| RISK-2026-05-12-008 | P0 | Lake `stk_mins` clean 层 schema 错误：缺失源业务字段 `exchange/vwap`，并额外物理保存冗余 `trade_date`，导致 clean/derived/research/indicator 后续链路可能基于错误事实层继续生成 | 本地 Lake `research/stk_mins_by_date_clean`，以及依赖 clean 的 `derived/stk_mins_by_date`、`research/stk_mins_by_symbol_month`、分钟技术指标 | Closed | [stk_mins clean 2024-10-30 多频率混入 1min 专项修复方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-clean-20241030-multifreq-repair-plan-v1.md)、[股票历史分钟行情 Parquet Lake 方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-parquet-lake-plan-v1.md) |
| RISK-2026-05-17-009 | P1 | `dc_member` 的板块代码展开依赖 `dc_index`；历史实现曾在 planner 阶段远程 fallback，且依赖来源藏在 `dc_index_board_codes` selector 中 | `dc_member.maintain`、`dc_index` 前置维护、DatasetActionResolver、板块成分数据完整性 | Closed | [Dataset Universe 模型收口方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-universe-model-refactor-plan-v1.md)、[board_hotspot 定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/board_hotspot.py) |
| RISK-2026-05-17-010 | P1 | `ths_member` 的板块代码展开依赖本地 `ths_index`；历史实现中依赖来源、字段和空池失败语义藏在 `ths_index_board_codes` selector 中 | `ths_member.maintain`、`ths_index` 前置维护、DatasetActionResolver、同花顺板块成分数据完整性 | Closed | [Dataset Universe 模型收口方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-universe-model-refactor-plan-v1.md)、[board_hotspot 定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/board_hotspot.py) |
| RISK-2026-05-24-011 | P0 | Dagster dynamic partition 范围扩展先于生产消费者切换，导致股票链路误跑指数历史范围交易日 | Dagster orchestrator、本地新湖股票 raw/silver/gold 分区、Dagster run/event/check 观测记录 | Closed | [Dagster Phase 3 主要指数方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-phase-3-major-indices-design.html)、[Dagster Phase 3 LLD](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-phase-3-major-indices-low-level-design.html)、[数据资产接入模板](/Users/congming/github/goldenshare/lake_console/docs/templates/dagster-dataset-onboarding-template.html) |

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

1. `cadence` 对用户价值很低，历史上曾以字段形式进入后端投影、snapshot、API 和前端页面。
2. freshness/status 链路曾保留部分基于 `cadence` 的兜底逻辑，导致 `date_model` 尚未成为唯一时间事实源。
3. 该风险已通过 `freshness_policy` 显式映射和 `cadence` 字段退场关闭。

处理要求：

1. 已完成 `DatasetDomain.cadence` 和 `cadence_display_name` 退场。
2. 已完成 API、前端类型、数据源页、数据状态页和报表中的 `cadence` 字段退场。
3. 已通过 `ops.dataset_status_snapshot.cadence` 迁移删除缓存列。
4. freshness、expected observed date、lag 判断改为依赖 `date_model + freshness_policy + 真实业务表观测 + TaskRun`。
5. 未新增新的节奏镜像字段、影子表或兼容层。

关闭门禁：

1. 前端页面不再显示 `cadence / cadence_display_name`。
2. freshness / snapshot / dataset card API 不再返回 `cadence`。
3. `ops.dataset_status_snapshot` 不再保存 `cadence`。
4. `DatasetDefinition.domain` 不再包含 `cadence`。
5. `rg "\\bcadence\\b" src frontend docs tests` 只允许命中历史归档文档或本专项退场文档。

---

## 9. RISK-2026-05-08-006 处理要求

风险说明：

1. 历史上 `index_daily` 曾先落 `core.index_daily_bar`，后迁入 `core_serving.index_daily_serving`，迁移后旧表仍保留。
2. 代码与文档层如果未显式收口“唯一事实表”，开发者容易把遗留表当现行表使用。
3. 当页面、查询、巡检、对账跨模块取数时，一旦有人误连旧表，会出现“同一交易日数值不一致/更新时刻不一致/缺字段映射不一致”。
4. 该风险不是立即数据损坏，但会持续制造认知混乱与口径漂移，属于高概率治理性故障源（P1）。

立即止血（文档与认知层）：

1. 全部实现文档明确：`index_daily` 现行事实表为 `core_serving.index_daily_serving`，`core.index_daily_bar` 为 legacy。
2. Wealth/Biz/Ops 新增功能涉及指数日线时，评审清单必须显式写出“取数表名”。
3. 禁止新增任何以 `core.index_daily_bar` 为源的页面查询或新 API。

正式收口（代码与门禁层）：

1. 全量审计当前仓库是否仍有 runtime 读取 `core.index_daily_bar`（非 Alembic 历史迁移脚本除外）。
2. 若存在运行态消费者，逐项切换到 `core_serving.index_daily_serving` 并补回归。
3. 清理 `DAOFactory` 等易误用入口中的 `index_daily_bar` 直接暴露（若仍未被运行态使用）。
4. 增加架构门禁：
   - 业务运行代码不得新增对 `src.foundation.models.core.index_daily_bar.IndexDailyBar` 的依赖；
   - 允许清单仅保留 Alembic 历史迁移与历史归档文档。
5. 完成后在方案文档中回写“旧表状态（保留/下线）与生效时间”。

2026-05-17 第一阶段收口状态：

1. 已确认当前运行链路写入事实为 `raw_tushare.index_daily -> core_serving.index_daily_serving`，Biz/Ops/App 查询侧未发现运行态读取 `core.index_daily_bar`。
2. 已移除 `DAOFactory.index_daily_bar` 运行入口，避免后续新代码通过 DAO 误连旧表。
3. 已新增架构门禁，禁止运行代码重新导入 `IndexDailyBar` 或引用 `core.index_daily_bar / index_daily_bar`。
4. 第一阶段未执行物理表退场，第二阶段单独处理旧 ORM model 与旧表删除。

关闭记录（2026-05-17）：

1. 已新增 Alembic 迁移 `20260517_000112_drop_legacy_index_daily_bar`，用于删除旧物理表 `core.index_daily_bar`。
2. 已删除旧 ORM model `src.foundation.models.core.index_daily_bar.IndexDailyBar`，并从 foundation model registry 中移除。
3. 运行态仅保留 `core_serving.index_daily_serving` 作为指数日线服务事实表；`raw_tushare.index_daily` 继续作为 raw 源站事实层。
4. 架构门禁已覆盖运行代码和 foundation models，防止旧 `IndexDailyBar / core.index_daily_bar / index_daily_bar` 重新进入主链。

关闭门禁：

1. `rg "index_daily_bar" src/biz src/ops src/app wealth/src` 仅允许 0 命中（或仅历史注释白名单命中）。
2. 主要指数查询与市场总览统一由 `core_serving.index_daily_serving` 提供事实数据。
3. 文档中不再把 `index_daily_bar` 作为现行数据源描述。
4. 新增查询/接口评审模板包含“事实表唯一性确认”项。

建议最小验收：

1. `pytest -q tests/architecture/test_subsystem_dependency_matrix.py`
2. `pytest -q tests/web/test_health_api.py tests/web/test_ops_pages.py tests/web/test_platform_check_page.py`
3. Wealth 侧契约与 mock smoke（如有）：`cd wealth && npm run typecheck && npm run test && npm run build`

---

## 10. RISK-2026-05-11-007 处理要求

风险说明：

1. 旧 `lake-console sync-stk-mins-range --ts-code ... --freq ...` 单股票区间补数路径曾复用整分区替换写入。
2. 该路径会把目标 `raw_tushare/stk_mins_by_date/freq=*/trade_date=*` 分区替换成单股票数据，而不是合并进原有全市场分区。
3. 已只读确认本地 Lake 中 `freq=1` 有大量交易日分区只剩 `300114.SZ`，`freq=5` 有局部同类损坏；`research/stk_mins_by_symbol_month` 仍保留可用于恢复的全市场数据。
4. 在完成审计与恢复前，继续运行分钟线同步、派生、research 重排或指标计算，可能扩大损坏范围或覆盖可恢复证据。

立即止血：

1. 暂停所有 `stk_mins` 写入、派生、research 重排和指标计算命令。
2. 只允许开发和执行只读审计命令、dry-run 恢复预演命令，以及经明确评审后的恢复命令。
3. 禁止清理 `_tmp`、`_recovery`、raw 损坏分区和 research 层，直到恢复方案完成并通过校验。
4. 单股票补数路径不得再使用整分区替换；任何修复必须证明不会删除同分区其他股票。

正式修复：

1. 新增 `audit-stk-mins-raw-integrity` 只读命令，按 `freq/trade_date` 统计 raw 行数、缺失分区、严重低行数分区和 research 可恢复行数。
2. 历史上新增 raw 恢复 dry-run 命令，只生成恢复计划，不写 `_tmp` 或正式分区；该命令已在事故恢复完成后下线。
3. dry-run 必须明确：哪些分区可从 research 恢复、哪些分区缺少 research 源、会合并多少 patch `ts_code` 行、预计恢复后的行数。
4. 历史 raw 恢复 apply 曾作为 `stk_mins` 单点恢复能力落地；事故恢复完成后该入口已下线。后续不得继续复制新的 ad-hoc apply 路径；恢复 apply 必须重新评审，并并轨到通用持久 backup、统一恢复账本和前端 Recovery 管理体系。
5. 恢复后必须补充 raw/research 双向校验，确认受损日期不再只有单股票行。
6. 所有正式 Lake replace 写入必须统一接入持久 backup 机制，成功后不得立即删除旧版本。
7. 必须新增 `manifest/write_recovery_log.jsonl` 作为恢复主索引，并允许从 `_recovery/**/metadata.json` 重建。
8. Lake 管理台前端必须新增 Recovery / Write Safety 页面，能查询恢复记录、backup 路径、before/after 行数和 restore dry-run 结果。
9. `stk_mins` 的专项恢复能力后续必须并轨到通用恢复账本与前端管理体系，不再长期维持独立恢复孤岛。

关闭门禁：

1. `audit-stk-mins-raw-integrity` 能稳定列出 `freq=1`、`freq=5` 的损坏分区和损失估算。
2. 历史 raw 恢复 dry-run 曾能对样本日期生成可恢复计划，且不写入任何 Parquet、`_tmp` 或 manifest；当前该入口已下线。
3. 单股票补数路径已有测试证明不会覆盖同分区其他股票。
4. 恢复 apply 命令完成并通过样本日期、整月和全量损坏区间校验。
5. 风险关闭时必须记录恢复命令、恢复分区数量、恢复前后行数对比和剩余风险。

阶段性处理记录（2026-05-11）：

1. 已新增只读审计命令 `audit-stk-mins-raw-integrity`，并完成本地 Lake 全量事故窗口复审：
   - 范围：`2009-01-01 ~ 2026-05-08`
   - 频度：`1,5,15,30,60`
   - 结果：`severely_low_partitions=0`，`recoverable_issue_partitions=0`
2. 历史 raw 恢复入口曾用于事故恢复，恢复逻辑为：
   - 以 `research/stk_mins_by_symbol_month` 的当日全市场数据为主体；
   - 合并当前 raw 中 `patch_ts_code=300114.SZ` 的补数行；
   - 按 `(ts_code, freq, trade_time)` 去重；
   - 写入前备份旧 raw 分区与 patch 行到 `_recovery/<run_id>/...`。
3. 已完成实际恢复：
   - `freq=5`：恢复 `2010-08-27 ~ 2011-08-05` 中 227 个严重低行数分区。
   - `freq=1`：恢复 `2010-08-27 ~ 2025-02-14` 中 3508 个严重低行数分区。
   - 合计恢复严重低行数分区：3735 个。
4. 已逐段复审通过：
   - `freq=5` 事故窗口复审：`severe=0`、`missing=0`。
   - `freq=1` 已按年度复审，2010、2011、2012、2013、2014、2016、2017、2018、2019、2020、2021、2022、2023、2024 以及 `2025-01-01 ~ 2025-02-14` 均为 `severe=0`、`missing=0`。
   - `freq=1` 的 2015 年仍存在 `underfilled=136`，但已确认不属于本次单股票覆盖整分区事故恢复对象。
5. 全量复审剩余风险：
   - `2026-05-08` 在 `freq=1,5,15,30,60` 均为 missing，且 research 也无当日数据，不能通过本恢复命令修复；应作为后续普通补数任务处理。
   - 若干历史 `underfilled` 分区仍存在，属于数据完整性审计议题，不得用本次事故恢复工具硬修。
   - 通用持久 backup、统一恢复账本、前端 Recovery / Write Safety 页面尚未完成，已拆分为后续治理议题；本 P0 按表格状态关闭，不再保留单点恢复命令。
6. 已通过本地代码门禁：
   - `lake_console/.venv/bin/python -m py_compile lake_console/backend/app/services/stk_mins_raw_recovery_service.py lake_console/backend/app/cli/commands/stk_mins.py lake_console/backend/app/services/tushare_stk_mins_sync_service.py`
   - `lake_console/.venv/bin/python -m pytest -q lake_console/backend/tests/test_stk_mins_raw_recovery_service.py lake_console/backend/tests/test_tushare_stk_mins_sync_service.py`
   - `python3 scripts/check_docs_integrity.py`
   - `git diff --check`

补充处理记录（2026-05-11）：

1. 已确认 `300114.SZ` 历史分钟线补数后仅剩 `freq=5 trade_date=2010-09-02` 无源端返回数据。
2. 该日期 `freq=1` 已存在完整 `300114.SZ` 1 分钟事实，因此历史上采用白名单 1min 修补入口的单股票 merge 模式修补。
3. 单股票 merge 模式只允许白名单 source gap 日期，且目标分区必须已存在；写入时只替换指定 `ts_code` 行，保留同分区其他股票。
4. 当时已补测试证明单股票 merge 模式不会覆盖同分区其他股票；该历史修补入口现已下线。

补充处理记录（2026-05-11，clean 层收口启动）：

1. 历史上曾新增错误 clean 初始化入口，用于把 `raw_tushare/stk_mins_by_date` 受控初始化到 `research/stk_mins_by_date_clean`。该入口对应错误 clean 口径，后续已下线。
2. 已新增 `build-stk-mins-security-identity-map --dry-run/--apply`，用于生成 clean 层使用的 `manifest/security_identity/security_identity_map.parquet`。当前规则覆盖 `stock_basic`、`bse_mapping` 与可唯一推断的 `namechange` 重叠映射。
3. 历史上曾新增错误 clean 只读审计与 dry-run rebuild 入口，用于预演 raw -> clean 真正清洗后的保留/过滤统计；这些入口对应错误 clean 口径，后续已下线。
4. 已用真实 Lake 小窗口验证：
   - 错误 clean 初始化 dry-run 小窗口
   - `build-stk-mins-security-identity-map --dry-run --sample-limit 5`
   - 错误 clean rebuild dry-run 小窗口
5. 已执行完整 clean bootstrap：
   - 历史错误 clean 初始化 apply 曾写入全量错误 clean 副本
   - 结果：写入 `research/stk_mins_by_date_clean` 共 `21045` 个分区、`21637` 个文件、`4576237808` 行。
   - 说明：该动作只是 raw 到 clean 的完整副本初始化，不做清洗，不修改 raw。
6. 已执行 `build-stk-mins-security-identity-map --apply --sample-limit 5`：
   - 写入 `manifest/security_identity/security_identity_map.parquet` 共 `6089` 条 source code 映射、`5837` 个 identity。
   - 当前无 identity 冲突；规则覆盖 `stock_basic`、`bse_mapping` 与可唯一推断的 `namechange` 映射。
7. 已执行 clean 层只读样本审计与 dry-run rebuild：
   - `2010-07-30 freq=1`：当前 clean 副本审计结果为 `needs_rebuild`，原因 `invalid_price=241`；dry-run rebuild 预计保留 `455731` 行、过滤 `241` 行。
   - `2026-04-24 freq=1`：dry-run rebuild 预计保留 `1326946` 行、过滤 `0` 行。
8. 该记录属于 clean 层收口启动背景，不关闭 `RISK-2026-05-12-008`。当前 clean 物理 schema 已确认存在缺陷，后续必须按 `RISK-2026-05-12-008` 的两阶段策略处理。

---

## 11. RISK-2026-05-12-008 处理要求

风险说明：

1. 当前 `research/stk_mins_by_date_clean` 是一份已经完成大量清洗动作、但物理 schema 错误的 clean 数据集。
2. 错误点包括：缺失源业务字段 `exchange/vwap`，并额外写入物理列 `trade_date`。
3. 因为 schema 已错，这份 clean 不能作为最终正式 clean 数据集，也不能直接作为 derived/research/indicator 的长期可信基准。
4. 但这份 clean 已经承载了大量清洗排查、专项修复和问题分类工作，仍可作为“清洗流程演练与规则沉淀对象”继续收尾。

当前决策（2026-05-12）：

1. 第一阶段先继续把当前这份错误 schema 的 clean 数据集，按照既有清洗记录中的遗留项清理完。
2. 第一阶段目标不是让这份 clean 成为最终正式数据，而是把完整清洗流程跑通并沉淀规则，包括问题发现、分类、专项修复、复查和文档记录。
3. 第一阶段仍不得进入 derived/research/indicator 的正式重建链路；它只服务于清洗动作验证与规则沉淀。
4. 第一阶段完成后，第二阶段再考虑从 `raw_tushare/stk_mins_by_date` 重新生成正式 clean。
5. 第二阶段正式 clean 必须修正 schema：保留 `exchange/vwap`，不写物理 `trade_date`，并复用第一阶段已经验证过的清洗规则。

第一阶段剩余清洗项：

1. 高频缺 `09:30:00` bar：用同日同股票 clean `1min 09:30:00` 恢复 `5/15/30/60` 缺失 bar。
2. `2024-10-30` 多频率混入 `1min`：仅处理问题清单中的股票、日期和频率，用 schema 口径已明确的 `1min` 修复源重新生成 `5/15/30/60`。
3. `2022` 年北交所 `30min` 原始缺失：用同日 clean `15min` 合成缺失的 `30min`。

第一阶段硬约束：

1. 不修改 raw。
2. 不重建 derived/research/indicator。
3. 不把当前错误 schema clean 误标为最终可用版本。
4. 每个专项必须先 dry-run，再由用户确认是否 apply。
5. 每个专项完成后必须回写排查记录和复查结果。

第二阶段前置条件：

1. 第一阶段三个遗留清洗项全部执行并复查完成。
2. `stk_mins` clean 清洗规则文档齐备，且明确哪些规则来自源事实、哪些来自清洗账本。
3. 正式 raw -> clean 重建方案重新评审通过。
4. 正式 clean 重建必须使用正确 schema：
   - `ts_code`
   - `freq`
   - `trade_time`
   - `open`
   - `close`
   - `high`
   - `low`
   - `vol`
   - `amount`
   - `exchange`
   - `vwap`
5. 正式 clean 禁止写入物理列：
   - `trade_date`
   - `identity_id`
   - `source_ts_code`

关闭门禁：

1. 当前错误 schema clean 的清洗遗留项已全部处理并形成记录。
2. 正式 raw -> clean 重建方案已评审通过。
3. 正式 clean 已按正确 schema 重建并通过 schema、行数守恒、去重冲突、字段保真和完备性审计。
4. derived/research/indicator 只基于正式 clean 重建，不再基于错误 schema clean。

关闭记录（2026-05-13）：

1. 已构建正式 clean candidate：`research/stk_mins_by_date_clean_next`。
2. `clean_next` 物理 schema 已确认为正式 11 列：
   `ts_code,freq,trade_time,open,close,high,low,vol,amount,exchange,vwap`。
3. `clean_next` 已完成全量基础审计，`issue_count=0`。
4. `clean_next` 已完成全量完备性审计，覆盖 `freq=1,5,15,30,60` 共 `21,045` 个分区，`issue_count=0`。
5. 两个已知专项均已修复并复查通过：
   - `2024-10-30` 多频率混入 `1min`；
   - `2022-07-15~2022-12-30` 北交所 `30min bar_count=6`。
6. `clean_next` 完备性问题账本已按最终审计结果清空，路径：
   `/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet`。
7. 旧错误 schema clean 已按用户决策删除：
   `/Volumes/datasource/goldenshare-tushare-lake/research/stk_mins_by_date_clean`。
8. 后续 derived、symbol-month、indicator 只能基于 `research/stk_mins_by_date_clean_next` 继续推进，不得再引用已删除的错误 clean。

---

## 12. RISK-2026-05-17-009 处理要求

风险说明：

1. `dc_member` 历史实现使用 `universe_policy="dc_index_board_codes"`。
2. 默认不传板块代码时，planner 会先按交易日或日期范围从本地 `DcIndex` 表读取板块代码，再按每个板块代码生成 `dc_member` 请求。
3. 历史实现中，单日场景如果本地 `DcIndex` 没有板块代码，planner 还会在规划阶段请求 Tushare `dc_index` 接口作为 fallback。
4. 这不是简单对象池，而是“先找板块清单，再拉板块成分”的两段式依赖；历史实现中，依赖关系只藏在 `dc_index_board_codes` 字符串和 planner 分支中。
5. planner 阶段发起外部请求会放大执行规划成本和失败面，后续开发者容易误以为 `dc_member` 只是普通 active pool 展开。

当前决策：

1. `dc_member` 默认维护不得在 planner 阶段临时拉取 `dc_index`。
2. 默认不传板块代码时，planner 只能读取本地已维护的 `DcIndex` 板块清单。
3. 如果本地 `DcIndex` 在指定交易日或日期范围内没有板块代码，任务必须规划失败，并提示先维护 `dc_index` 东方财富板块列表数据。
4. 显式传入 `ts_code` 或 `con_code` 时，继续按显式输入规划，不依赖默认板块清单。
5. 任何包含默认 `dc_member` 维护步骤的工作流，都必须先执行 `dc_index`，再执行 `dc_member`。

处理要求：

1. 取消 planner 远程 fallback，明确 `dc_index` 是 `dc_member` 默认维护前置条件。
2. 当本地板块池为空时直接返回可读的规划错误，禁止继续悄悄请求 `dc_index`。
3. 后续继续把板块池来源、字段和空池失败语义显式写入 Definition 或专用 plan 规则。
4. 不得继续新增类似 `*_board_codes` 的历史 selector 字符串；新方案应向 `universe_policy="pool"` 与显式对象池来源收口，或形成单独评审过的依赖型 planner 规则。
5. 补充 planner 测试，覆盖本地 `dc_index` 命中、按日期范围取板块、空池失败，以及显式 `ts_code/con_code` 维护。
6. 补充工作流顺序测试，防止 `dc_member` 被排到 `dc_index` 之前。

关闭门禁：

1. Definition 或专用 plan 配置中能直接看出 `dc_member` 的板块代码来源、字段和来源顺序。
2. `dc_member` 默认维护不再依赖难以察觉的 `dc_index_board_codes` 隐式分支。
3. planner 阶段是否允许远程请求已有明确结论，并有测试锁住。
4. 文档说明 `dc_member` 与 `dc_index` 的前置关系，运营侧能理解为什么需要先准备板块清单。
5. 定向测试覆盖 `dc_member` 默认维护和显式 `ts_code/con_code` 维护。

关闭记录（2026-05-17）：

1. `dc_member` 已迁移为 `universe_policy="pool"`，并在 `planning.universe` 中显式声明来源：
   `core_dc_index_by_trade_date / dc_index`。
2. `dc_member` 已改为专用 `build_dc_member_units`，默认维护只读取本地 `DcIndex`，不再在 planner 阶段请求 Tushare `dc_index`。
3. 本地 `DcIndex` 没有对应日期或日期范围板块代码时，planner 直接失败，并提示先维护 `dc_index` 东方财富板块列表数据。
4. 工作流顺序测试已锁住：任何包含 `dc_member` 的工作流必须先执行 `dc_index`。
5. 定向测试覆盖本地命中、日期范围逐日展开、空池失败、显式 `ts_code` 与显式 `con_code`。

---

## 13. RISK-2026-05-17-010 处理要求

风险说明：

1. `ths_member` 历史实现使用 `universe_policy="ths_index_board_codes"`。
2. 默认不传板块代码时，planner 从本地 `ThsIndex` 表读取所有同花顺板块 `ts_code`，再逐个生成 `ths_member` 请求。
3. `ths_member` 没有日期输入，也没有远程 fallback；如果 `ThsIndex` 为空或过旧，默认维护会失败或漏板块。
4. 历史实现中，依赖关系只藏在 `ths_index_board_codes` 字符串和 planner 分支中，Definition 里看不出来源表、字段和空池失败语义。
5. 这个风险比 `dc_member` 轻，但同样会造成后续开发者误判默认维护对象池来源。

当前决策：

1. `ths_member` 默认维护不得绕开本地 `ThsIndex` 板块清单。
2. 默认不传板块代码时，planner 只能读取本地已维护的 `ThsIndex` 板块清单。
3. 如果本地 `ThsIndex` 没有板块代码，任务必须规划失败，并提示先维护 `ths_index` 同花顺板块列表数据。
4. 显式传入 `ts_code` 或 `con_code` 时，继续按显式输入规划，不依赖默认板块清单。
5. 任何包含默认 `ths_member` 维护步骤的工作流，都必须先执行 `ths_index`，再执行 `ths_member`。

处理要求：

1. 单独评审 `ths_member` 对 `ths_index` 的依赖模型，明确 `ths_index` 是否是默认维护的强前置数据集。
2. 将默认板块池来源、字段和空池失败语义显式收口到 Definition 或专用 plan 规则。
3. 不得继续新增类似 `ths_index_board_codes` 的历史 selector 字符串；新方案应向 `universe_policy="pool"` 与显式对象池来源收口，或形成单独评审过的依赖型 planner 规则。
4. 补充 planner 测试，覆盖本地 `ths_index` 命中、显式 `ts_code/con_code` 绕过默认池、空池失败。
5. 更新 `ths_member` 数据集开发文档或相关架构文档，说明它依赖 `ths_index` 提供板块清单。

关闭门禁：

1. Definition 或专用 plan 配置中能直接看出 `ths_member` 的板块代码来源和字段。
2. `ths_member` 默认维护不再依赖难以察觉的 `ths_index_board_codes` 隐式分支。
3. 空池失败文案能明确提示需要先维护 `ths_index`。
4. 定向测试覆盖 `ths_member` 默认维护和显式 `ts_code/con_code` 维护。

关闭记录（2026-05-17）：

1. `ths_member` 已迁移为 `universe_policy="pool"`，并在 `planning.universe` 中显式声明来源：
   `core_ths_index_snapshot / ths_index`。
2. `ths_member` 已改为专用 `build_ths_member_units`，默认维护只读取本地 `ThsIndex`，不再依赖 `ths_index_board_codes` 历史 selector。
3. 本地 `ThsIndex` 没有板块代码时，planner 直接失败，并提示先维护 `ths_index` 同花顺板块列表数据。
4. 工作流顺序测试已锁住：任何包含 `ths_member` 的工作流必须先执行 `ths_index`。
5. 定向测试覆盖本地命中、空池失败、显式 `ts_code` 与显式 `con_code`。

---

## 14. RISK-2026-05-24-011 处理要求

风险说明：

1. Dagster Phase 3 Slice 3.2.2 拆分股票与指数资产族分区时，先把全局备份分区 `cn_a_trade_days` 扩展到更早历史范围。
2. 当时股票生产资产、股票 sensors、market breadth automation 等消费者尚未全部切换到 `cn_a_stock_trade_days`。
3. 扩展后的 `cn_a_trade_days` 被仍然绑定在旧分区集合上的生产消费者读取，导致 `suspend_d`、`stock_daily`、`gold_market_breadth_daily` 等股票链路错误看到 2014 年以前或未来日期。
4. 部分 sensor / automation 在错误分区集合上提交 run request，造成 Dagster run/event/check 记录污染，并在本地新湖生成了非法股票资产分区文件。
5. 事故暴露的问题不是单个 asset 计算逻辑错误，而是迁移顺序错误：共享 dynamic partition 的范围变更先于全量消费者审计、切换和自动化隔离。

事故经过：

1. 设计目标是保留 `cn_a_trade_days` 作为全量 SSE open day 备份分区，同时新增 `cn_a_stock_trade_days` 和 `cn_a_index_trade_days`。
2. 实施时先扩展了 `cn_a_trade_days`，但没有先确认所有股票生产资产、checks、jobs、sensors、automation condition sensors、history/backfill 入口和 readiness helper 已经脱离旧分区集合。
3. `market_breadth_automation_sensor` 和股票相关 sensors 在未完全隔离的状态下读取到扩展后的分区范围。
4. 用户发现 `market breadth` 开始跑 2014 年以前数据，并手动停止运行、关闭所有 sensors。
5. 事故后执行清理：停止所有 sensors，删除异常 active/failed run 与 failed backfill 记录，清理非法湖目录，删除未来备份分区 key，并复查股票 raw/silver/gold 文件范围与 materialization 状态。

根因：

1. 把“备份分区扩展”误认为无害元数据动作，没有把 dynamic partition 视为会驱动 sensors、automation、jobs 和 asset selection 的生产事实。
2. 没有在扩展共享分区前做全量消费者审计，遗漏了仍然绑定旧分区集合的自动化消费者。
3. 迁移顺序错误：应该先关闭自动化、切换生产消费者到资产族分区、验证 preview / definitions / 小范围结果，再扩展备份分区。
4. 文档和执行步骤没有把“先切换生产链路，再扩展备份集合”写成硬门禁。
5. 当时缺少股票资产族分区合法性的正式 blocking asset checks，导致质量门禁不够显式。

当前决策：

1. 股票生产资产统一使用 `cn_a_stock_trade_days`，指数生产资产统一使用 `cn_a_index_trade_days`。
2. `cn_a_trade_days` 只作为全量 SSE open day 备份和对照分区集合，不再作为正式生产资产、sensor、automation 或 history backfill 的分区来源。
3. 分区范围、日期边界、资产族归属这类质量门禁必须实现为正式 blocking asset checks，不在业务 asset 写入函数中混入定制化写前 guard。
4. 扩展任何 dynamic partition 范围前，必须先关闭相关 sensors / automation，并完成生产消费者审计与切换。
5. 新增或改造日频资产时，必须在数据资产接入模板中明确选择资产族分区，禁止默认复用全局分区。

处理要求：

1. 所有生产资产必须按资产族绑定 partition definition；禁止新增生产 asset 依赖 `cn_a_trade_days`。
2. 扩展分区范围前必须审计并列清消费者，至少覆盖 assets、asset checks、jobs、sensors、automation condition sensors、history/backfill 入口和 readiness helper。
3. 分区迁移必须按顺序执行：关闭自动化 -> 切换生产消费者 -> `dg check defs` -> preview 验证 -> 小范围只读审计 -> 注册新范围 -> 小范围生产验证。
4. 如果某个变更会扩大 partition key 范围，必须先评估是否会触发 missing/on_missing、sensor pending 判断、history backfill 或任何自动化补跑。
5. 事故类清理必须同时覆盖 Dagster instance 记录与物理湖文件；只清一边不算完成。
6. 数据资产接入模板必须把资产族 partition、消费者审计、自动化隔离和 blocking partition checks 作为必填项。

关闭门禁：

1. 股票资产、股票 sensors、stock daily readiness 和 market breadth automation 已改读 `cn_a_stock_trade_days`。
2. 指数资产、index basic freshness、index daily history backfill 已改读 `cn_a_index_trade_days`。
3. `cn_a_trade_days` 保留为备份和对照分区集合，不进入生产资产分区定义。
4. 已补 `stock_partition_checks.py`，用正式 blocking asset checks 验证股票资产族分区合法性。
5. 已清理事故期间产生的异常 run/backfill 记录、非法湖目录和未来备份 partition keys。
6. 已将事故原则写入 `lake_console/orchestrator/AGENTS.md` 和 `lake_console/docs/templates/dagster-dataset-onboarding-template.html`。

关闭记录（2026-05-24）：

1. 事故后验证 `FAILED_RUNS=0`、`ACTIVE_RUNS=0`、`FAILED_BACKFILLS=0`。
2. 所有 Dagster sensors 已停用后再恢复到默认受控状态，避免继续提交异常 run request。
3. 股票相关物理文件范围复查通过：`raw_tushare_stock_daily`、`raw_tushare_suspend_d`、`silver_stock_daily`、`silver_stock_suspend_daily`、`gold_market_breadth_daily` 均保持 `2014-01-02` 至 `2026-05-22` 范围，无 2014 年以前或未来分区。
4. 代码层已补充 `cn_a_stock_trade_days`、`cn_a_index_trade_days`，并把股票与指数生产链路从全局分区中拆出。
5. 文档层已同步 Phase 2、Phase 3、stock daily 迁移文档、asset/job topology 和数据资产接入模板。
