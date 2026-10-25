# DatasetExecutionPlan 执行计划与可靠执行

更新时间：2026-10-25（新增第 9 节区间维护修复方案与 LLD）。状态：现行模型与执行约束说明。原重构主案和 M-1～M8 索引中的有效规则归入本文；历史步骤不是当前实施计划。本文区分代码事实与尚须按需求验证的可靠性目标。

## 1. 主链与职责

```text
手动 / Schedule / Workflow 意图
  -> Ops TaskRun 编排
  -> DatasetActionRequest
  -> DatasetActionResolver（读取 DatasetDefinition、校验、规划 units）
  -> DatasetExecutionPlan
  -> IngestionExecutor（拉取、归一化、校验、写入和提交）
  -> 结构化进度与结果 -> Ops TaskRun 观测
```

- Definition 是静态事实源；Plan 是本次请求的执行投影，不是第二份配置。
- Ops 负责触发、领取、停止、重试、任务状态和页面投影，不重新解释底层日期模型。
- Resolver/planner 属于 Foundation；request builder 只将已归一化的值映射为源接口参数。
- 执行器入口是 `IngestionExecutor`，不是旧草案中的 `DatasetPlanExecutor`。旧 sync/backfill/history 路由不得重新成为长期业务模型。
- 子系统目标边界与已知差距见 [架构基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)，不以本图证明下层反向依赖已全部清零。

当前实现入口：[execution_plan.py](/Users/congming/github/goldenshare/src/foundation/ingestion/execution_plan.py)、[resolver.py](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)、[unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[executor.py](/Users/congming/github/goldenshare/src/foundation/ingestion/executor.py)、[TaskRun dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)。

## 2. 请求与解析

`DatasetActionRequest` 承载 `dataset_key/action/time_input/filters` 及触发、请求人、schedule/workflow/run 上下文；当前 Resolver 维护动作是 `maintain`。

`DatasetTimeInput` 使用 `mode` 和相应日期/月字段：`trade_date/ann_date/start_date/end_date/month/start_month/end_month/date_field`。哪些组合合法由 Definition、动作能力及 validator 决定，不因为模型中存在字段就全部开放。

| 请求模式 | 内部 run_profile | 说明 |
| --- | --- | --- |
| `point` | `point_incremental` | 单点；可能是日期或月份键，不等于最后交易日 |
| `range` | `range_rebuild` | 日期/月份范围；名称不代表一定清空目标表 |
| `none` | `snapshot_refresh` | 无时间意图；名称不代表每种 writer 都整体替换 |

Resolver 先归一化并校验请求，再生成 units。月份键、自然月窗口和日期锚点的准确规则见 [日期指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。禁止把股票与指数周/月线都归一化为最后交易日。

`plan_id` 按 dataset、action、run profile、校验后参数和 unit IDs 生成；它不是数据库行主键或断点记录。当前 `plan.filters` 保存的是校验后参数，可能包含归一化日期等执行参数，不能误当成用户原始筛选条件。

## 3. Plan 字段与 unit

完整字段以模型为准，以下只说明容易混淆的投影：

| 部分 | 主要内容与限制 |
| --- | --- |
| `time_scope` | 本次输入范围、模式、标签，不是完整日期模型 |
| `source` | 来源、adapter、API、源字段 |
| `planning` | `universe_policy`、`enum_fanout_fields/defaults`、`request_variant_fields/defaults`、分页策略、规模限制、拉取并发、unit 数量、分页处理模式 |
| `writing` | DAO、目标表、冲突键、write path、Serving 冲突策略、observation/stage、替换范围 |
| `quality` | 拒绝策略、空结果策略、写前校验器 |
| `transaction` | `commit_policy/idempotent_write_required/write_volume_assessment` |
| `observability` | 进度标签、取自 Definition 日期模型的 `observed_field/audit_applicable` |
| `units` | 本次展开后的 `PlanUnitSnapshot` 序列 |

Plan 没有 `planning.universe`、`enum_fanout` 或 `enum_defaults` 字段。对象池声明在 Definition，planner 使用后把具体对象写入 units；不要按旧文档补出另一份 Plan 配置。

一个 unit 保存 `unit_id`、dataset/source、日期、实际 `request_params`、`progress_context`，以及分页、请求变体等执行信息。`page_limit` 存在于 Definition planning 和 unit，而不是当前 PlanPlanning 的字段。

### 如何理解展开

日期/窗口、对象池、枚举组合与请求变体是不同维度：

- 对象池来源、优先级、显式代码限制见 [Definition 对象池合同](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md#universe-contract)。
- 枚举组合生成独立 unit；同一 unit 的 request variants 不能当作独立完成量。
- `index_daily` 的按代码窗口请求不改变其交易日观测语义；请求池与 Serving 筛选池不能合并。
- `index_weight` 的自然月窗口由 Resolver 归一化，planner 按代码和窗口构造请求。
- 全选必须是实际枚举集合，禁止 `__ALL__` 哨兵进入请求或数据。

不要只按 `unit_builder_key` 的名字判断粒度。修改 unit 之前必须核验 request builder、写入身份、进度、测试及实际规模。

## 4. 分页、内存与并发

| 模式 | 当前含义 |
| --- | --- |
| `buffer_all` | 默认聚合一个 unit 的分页结果后归一化、写入；不等于整个任务所有 unit 一起缓冲 |
| `staged_stream` | 显式选择逐页归一化并持久化到非服务 stage，完整 unit 校验后发布 Serving |

`staged_stream` 不是“每页业务数据都可以对外可见”。它受当前 [Definition linter](/Users/congming/github/goldenshare/src/foundation/ingestion/linter.py)的 stage DAO/table、write path、offset 分页、单并发和 `commit_policy=unit` 组合门禁约束；不能只切换一个字符串。

`pagination_policy=offset_limit` 表示通用 offset/limit 分页；`none` 表示不使用该通用分页策略，不保证单请求一定覆盖全集。结束条件、上限和分页一致性须按 source client 与数据集合同验证。

<a id="fetch-concurrency"></a>

### 4.1 源端拉取并发：现行实现

`DatasetPlanningDefinition.fetch_concurrency` 默认 1，并投影到 Plan。2026-09-10 核对：`stk_mins`、`etf_mins` 均显式配置 2；linter 的总范围为 1～4，`staged_stream`、Basic 完整快照等专用路径另有单并发限制。新增适用数据集仍需单独评估，不自动全仓开启。

[executor](/Users/congming/github/goldenshare/src/foundation/ingestion/executor.py) 先判断 staged-stream；普通缓冲路径只有多 unit 且并发值>1 才进入 `_run_units_with_concurrent_fetch()`：

| 环节 | 当前执行边界 |
| --- | --- |
| 提交 | 按 unit 序列提交，in-flight 数不超过并发值；提交新 fetch 前检查取消 |
| Fetch | 线程池只调用 source client；connector 在源端拉取调用内创建，不共享 DB Session |
| 消费结果 | `FIRST_COMPLETED` 返回已完成集合；主线程逐个 normalize/write/commit/report，再补入任务 |
| 顺序 | 不强制原 unit 顺序，也不保证同批完成集合内部按精确完成时间排序 |
| 失败 | 停止补入任务、回滚当前未提交事务，尽力取消未启动 future；既有业务提交保留 |
| 取消限制 | 运行中的 fetch 不能被 `Future.cancel()` 强制终止，线程池退出可能等待它结束；不承诺立即/逐页取消或 30 秒内退出 |

[Tushare client](/Users/congming/github/goldenshare/src/foundation/clients/tushare_client.py) 对共享 limiter 初始化字典加锁，limiter 自身也保护请求间隔。它是**进程内**共享，不是跨进程配额协调；不能靠增加 Worker 进程绕开限流。并发不改变源参数、unit 粒度、writer 事务、API 或 UI，也不提高源端额度。

维护时使用现有环境运行 [并发与线程测试](/Users/congming/github/goldenshare/tests/test_dataset_progress.py)、[linter 测试](/Users/congming/github/goldenshare/tests/test_ingestion_linter.py)、[共享 limiter 测试](/Users/congming/github/goldenshare/tests/test_tushare_client.py)，并补 registry/resolver/source-client 和实际数据集回归。不要因旧命令使用 `uv run` 而自动下载或同步依赖。

### 4.2 首期性能记录（2026-06-04，非当前生产验收）

原并发专题的 D1–D4 确认：首期只给 stk_mins 配 2、总范围 1～4、投影到 Plan、优先消费已完成结果。首期代码及 fake-source/线程/失败/限速器回归已完成；ETF 分钟的后续启用不是当时 D1 的一部分。

| 当时 TaskRun | units | 耗时 | 原文估算请求速率 |
| --- | ---: | ---: | ---: |
| 1880 | 29,250 | 约 153 分钟 | 约 191 次/分钟 |
| 1797 | 29,250 | 约 108 分钟 | 约 271 次/分钟 |
| 1704 | 29,250 | 约 135 分钟 | 约 217 次/分钟 |

当时配置额度为 500 次/分钟，计划目标为单日约 60～80 分钟；**配置和上述估算不足以证明当前源端配额、瓶颈原因或已实现生产加速**。原 M6 还要求比对 unit、请求参数、写入行数、reject、限速错误、耗时及 TaskRun 进度；现有专题记录未提供 M6 完成证据，本次不补跑生产或自动关闭它。

若获准的生产验收不符合预期，原回退策略是将对应 Definition 的并发改回 1，不清表、不迁移、不改 TaskRun 数据。本节是保留的处理依据，不是本轮执行授权。

## 5. 提交、幂等与取消

### 当前可用提交策略

| `commit_policy` | 边界 |
| --- | --- |
| `unit` | 按 planned unit 完成业务提交；隔离 stage 的页持久化不是业务发布 |
| `raw_then_serving` | 仅 `fund_daily` 专用两阶段 write path；先提交 Raw，再提交 Serving，Serving 失败不能回滚已提交 Raw |

当前合同没有 `data_commit_policy/ops_state_policy`，也没有 `per_unit/per_execution` 取值。不得据旧示例创建无效配置，或恢复任务末尾统一提交的大事务。

### 必须维持的安全要求

1. 数据提交与 Ops 状态观察分离。TaskRun、freshness、snapshot 等状态失败不得回滚、阻塞或污染已获准的业务写入。
2. DAO 的 batch size 只是 SQL 分批，不是事务分段。writer 写入成功、业务 commit 成功、TaskRun 状态成功是三件事。
3. 行级幂等由真实冲突键、替换范围和 writer 决定；unit_id/plan_id 不能替代行身份。
4. 后续 unit 失败或取消，不得回滚之前已提交 unit；不把部分处理的 unit 标为已完成。
5. 逐 unit/页取消检查、内存上限、持久化续跑、进度与终态一致按 [根 AGENTS 的 Prod 长任务门禁](/Users/congming/github/goldenshare/AGENTS.md#prod-数据集长任务可恢复性与可观测性门禁)和 [模板 §0.3.5](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)评审及验收。DG/Lake 使用自己的规则，不套用本合同。
6. 不因已有 unit commit 就声称通用“进程退出后可靠续跑”已经完成；必须证明续跑依据持久化、重放幂等和真实取消—续跑结果。
7. 迁移工具的按表事务、大表重建与日常 ingestion 不是同一条链；迁移需单独授权和规模评估，不自动继承安全结论。

### 历史事故保留的原因

2026-04 原重构记录记载：一次 `stk_mins` 约 1.2 亿行任务，把数据与两个状态创建动作放在最终同一事务提交；状态唯一键冲突导致业务成果回滚。这是历史记录，不是本轮重新测量或当前仍存在该旧服务的结论。

必须保留的教训是：按业务单元提交、状态幂等且与业务隔离、提交后才报告完成量。原停机清空、重新 seed、旧服务删除的施工步骤不再作为当前指令。风险跟踪继续看 [工程风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md)，不在本文重复维护另一份状态账本。

## 6. 进度与状态：当前事实和目标分开

当前 [ProgressSnapshot](/Users/congming/github/goldenshare/src/foundation/ingestion/progress.py)提供结构化进度；`IngestionExecutor._build_progress_message()` 仍生成中文 message。因此不能写“Foundation 当前只上报结构化数据、不生成文案”。

原“文案统一由 Ops 格式化”保留为架构方向，不是本次已完成事项，也不在文档整理中启动代码改造。

展示必须分清：

- `rows_fetched`：源端读取量。
- `rows_written`：写入执行量，不单独证明事务提交。
- `rows_committed`：已提交业务量；stage 行数不能冒充 Serving 已发布量。
- 拒绝量与原因、当前阶段、当前 unit、完成/总量和更新时间；心跳不能替代业务进度。

中文字段标签优先取 Definition/display label，错误和原因须进入 [codebook.py](/Users/congming/github/goldenshare/src/foundation/ingestion/codebook.py)，不让前端猜机器 token。TaskRun/node 终态、部分提交和状态失败的实际呈现按 [TaskRun 观测专题](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)核验。

原草案的 `record_execution_outcome(...)`、`coverage_status`、状态对账队列等名称不作为现行字段/API 承诺；状态隔离和可对账的要求仍保留，不能凭目标名称宣布实现完成。

## 7. Workflow、Schedule 与接口

Workflow step 引用 dataset action，Schedule 绑定动作或 workflow；二者表达触发/业务意图，不恢复旧 job/spec 路由。流程可包含其他现行维护动作，不能把全部 workflow step 强制改成数据集同步。

时间形状、默认时间制度与数据集锚点的区别统一见 [日期指南的 Workflow 说明](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md#workflow-time)。实际接口与 TaskRun 字段看 [Ops 当前契约](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)，不使用旧方案中拟建的 execution API 作为实现参考。

## 8. 验证入口与本轮边界

代码改动按 [数据集模板 §8](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)选择 registry、resolver、writer/executor、Ops/API、前端与真实最小验收；只创建 TaskRun 或通过静态 lint，不证明请求范围、目标行数或恢复行为正确。

当前关键证据入口：

- [registry 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)。
- [fund_daily 两阶段执行测试](/Users/congming/github/goldenshare/tests/test_ingestion_executor_fund_daily_two_phase.py)。
- [维护模型护栏](/Users/congming/github/goldenshare/tests/architecture/test_dataset_maintenance_refactor_guardrails.py)、[codebook 护栏](/Users/congming/github/goldenshare/tests/architecture/test_dataset_codebook_guardrails.py)。
- 旧执行模型防回流、依赖边界与通用验证入口见 [子系统架构基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md#architecture-guardrails)。

2026-09-10 的文档整合只合并文档、纠正现状描述，不新增字段、状态机、Worker、迁移或生产动作，也不宣称完成未验收的长任务与运行态治理目标。2026-10-25 获准的修复范围单列如下。

## 9. 2026-10-25：涨跌停区间维护修复方案与 LLD

### 9.1 目标、依据与授权边界

管理员要求先查原开发文档、补修复方案，再修复区间任务。当前未找到独立的 `limit_list_d` Prod 开发说明；Git 历史中的 `limit-list-d-prod-raw-db-lake-export-plan.md` 只覆盖生产 Raw 到 Lake 的导出，已退役，不恢复。本次在本执行主案记录方案和 LLD，不改 Lake。

目标：对包含开市日的每日涨跌停名单区间，按现有交易日历和源接口枚举生成实际请求，消除有交易日却生成零执行单元的问题。范围仅为 Foundation 日期展开代码、回归测试及本节；不改变 DatasetDefinition、输入字段、API/CLI、源参数、表结构、写入和 TaskRun 状态合同，不部署、不提交补数任务、不修改历史成功记录。其他数据集只做受影响路径回归。

事实依据：

- 修复前 22:50 的只读记录：生产任务 `16801` 输入为 2026-10-21—23，筛选为 `limit_type=[U,D,Z]`、`exchange=[SH,SZ,BJ]`；计划中的 `unit_count=0`，获取和写入都是 0，却显示成功。当时 10 月 22 日涨跌停 Raw、Serving 均为 0 行；21、23 日分别已有 74、100 行。管理员随后已通过单日任务补数，这些行数仅作事故时点证据。
- 生产 SSE 日历的 21、22、23 日均为开市日。10 月 22 日源接口只筛 `limit_type=U` 返回 33 行，增加 `exchange=SH` 返回 19 行；指定 `600192.SH` 的默认字段请求返回 1 行，并含 `trade_date/ts_code/limit`。本次复用同会话的有界只读证据，不重取全历史。
- 源合同见 doc_id 298：[涨跌停列表（新）](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/打板专题数据/0298_涨跌停列表（新）.md)。`exchange=SH/SZ/BJ` 是源接口筛选；平台日历的 `exchange=SSE` 是日期依据，两者不能互相代用。

### 9.2 当前代码与影响面审计

`DatasetRequestValidator` 会把省略的源接口交易所补成 `[SH,SZ,BJ]`。`DatasetUnitPlanner._resolve_anchors()` 原先将 `request.params.exchange` 转为字符串传给 `TradeCalendarDAO.get_open_dates()`，实际查询的名称成为 `['SH', 'SZ', 'BJ']`，没有匹配日历，所以没有进入请求构造和下载。清空页面筛选不能修复此问题，因为 validator 会补回默认集合。

CodeGraph 已使用 `codegraph_search`、`codegraph_callers`、`codegraph_impact`，覆盖 `_resolve_anchors`、`DatasetUnitPlanner` 及 resolver 调用方；再核对当前实现和全部 Definition。直接调用日期展开的路径包括 generic、`dc_member`、`ths_member`、`stk_factor_pro`、`etf_share_size`；后两者有专用路径，按现有测试回归。当前带 `exchange` 输入的五个数据集中，只有 `limit_list_d` 使用这段按开市日展开的区间逻辑；`stock_basic/stock_company/ths_index` 为无时间模型，`trade_cal` 为自然日模型。

入口和消费者为：手动任务页面 `frontend/src/pages/ops-v21-task-manual-tab.tsx` → `/api/v1/ops/manual-actions` → `ManualActionCommandService` 预检 → `DatasetActionResolver`；实际运行由 `TaskRunDispatcher` 再构建计划，Schedule、Workflow 和 CLI 也复用该链。修复只发生在 Foundation，不新增跨层依赖。前端继续提交相同日期及筛选集合，无需修改控件。板块热度是下游消费者，不修改其零行检查，也不把零执行单元任务当成源已完成的证明。

### 9.3 实现设计、配置与读写边界

1. `_resolve_anchors()` 的开市日区间查询直接使用 `self.settings.default_exchange`；不再读取源筛选中的 `exchange`。不增加按数据集名称判断的分支。
2. `default_exchange` 是现有 Settings 配置，默认 `SSE`，环境变量名为 `DEFAULT_EXCHANGE`；由 `get_settings()` 读取现有环境及 `GOLDENSHARE_ENV_FILE` 指定的文件（默认 `.env`）。来源、持久化及加载方式保持现状；本次只统一该日期查询与已有指数月历等路径的用法，不新增配置或持久化位置。
3. 日期取出后仍由现有枚举展开和 `_limit_list_params()` 生成请求。3 个开市日 × 3 种类型 × 3 个交易所必须生成 27 个 unit；指定 SZ、U 时为 3 个 unit。每个请求的 `exchange` 必须是 SH、SZ 或 BJ 单值，业务日期传给 Tushare 时仍为 `YYYYMMDD`。
4. 单日直接使用指定日期，仍为 9 个默认 unit；不进入区间日历查询。周线区间继续按当前周末规则压缩；自然日及无时间路径不受此处修改影响。
5. 只含休市日的区间继续允许生成空计划。本次不增加全局空计划错误，不改变其状态行为；对真实包含开市日的本次样本，用准确日期和 unit 数量证明不会再次形成空任务。
6. 规划只读日历，不调用 Tushare、不写 Raw/Serving 或 Ops。正式执行的按 unit 提交、幂等键和取消流程均复用现有实现。本次真实验收只读取有界日历后在本地生成计划，不执行 writer。

### 9.4 失败、中断、续跑与性能预算

本修复不新增执行器、状态、并发或续跑机制。规划失败不产生业务写入；在相同意图下重新规划只重复一次日历读取和枚举展开。正式同步已提交 unit 的保留、取消和重复执行边界沿用第 5 节，不宣称本次补全了尚未验收的通用长任务恢复能力。

验收固定为 2026-10-21—25：最多 5 行日历、3 个开市日和 27 个 unit；每次只读 SQL 超时 15 秒。中断后重做只重复上述范围；最终验收同样不扩大范围。内存只新增最多 27 个现有 PlanUnitSnapshot，不读取涨跌停全量明细，不发下载请求。正式补数的请求量仍按日期 × 类型 × 交易所及现有分页计算，单页 2500 行、串行拉取与 unit 提交配置均不改变；本次不开展大范围同步或扩展长任务能力。

### 9.5 硬口径、测试与验收

下表为开发前的验收约束；实现及验证完成后在原表更新结果，不能仅以 TaskRun 成功作为通过依据。

| 硬口径 | 实现位置 | 正向与反向验证 | 状态 |
| --- | --- | --- | --- |
| 日历取现有配置；源交易所不得参与日历名称选择 | `unit_planner.py::_resolve_anchors` | 使用真实 ORM 和隔离日历，默认及显式 SH/SZ/BJ 集合都得到 21、22、23 日；SZ/U 子集仍读取 SSE 日历 | 已实现、隔离及真实日历验证通过 |
| 源参数及默认全选不变，不漏日期和枚举 | 现有 validator、enum 展开、`_limit_list_params` | 独立字面日期/类型/交易所组合核对完整 27 个请求；子集 3 个请求，不能扩成全选 | 已验证 |
| 单日、休市及其他日期模型保持现行行为 | 现有 point/natural-day/week 路径 | 单日 9 个；24—25 日休市范围 0 个；普通 A 股日线、指数周线、自然日与无时间回归 | 本次用例及现有 resolver/API 回归通过；既有月末 helper 测试失败另记下文 |
| 回归必须能抓住原始缺陷 | 新增 `tests/test_limit_list_range_planning.py` | 改实现前先运行新测试，确认含交易日区间因 0 unit 失败；修复后相同夹具和预期通过 | 修复前 5 失败、5 通过；修复后新增 10 项均通过 |
| 与入口消费者和真实日历一致 | resolver、现有 Ops API/runtime 测试 | 现有 resolver/planner/API/runtime 回归；通过规定脚本读取最多 5 行生产日历，本地生成计划核对 27 个请求，不提交任务 | 已验证本地规划；未部署、未执行生产下载 |

隔离测试日历依据：23:03:19（北京时间）通过 `bash scripts/psql-remote.sh`、READ ONLY 事务及 15 秒 SQL 超时，读取生产 `core_serving.trade_calendar` 的 `exchange/trade_date/is_open`，日期仅 21—25 日、最多 5 行；实际为 21—23 日开市，24—25 日休市。使用真实 `TradeCalendar` schema 和独立字面预期；不会把 DAO 固定成不论交易所参数都返回同一组日期的替身，否则原始错误也会通过。将这 5 行装入本地隔离内存库、调用当前 resolver，验证默认 27、SZ/U 子集 3、单日 9、纯休市范围 0 个请求；没有调用下载或 writer，也没有创建 TaskRun。

### 9.6 本轮验证记录与交付边界

- 新增回归 [test_limit_list_range_planning.py](/Users/congming/github/goldenshare/tests/test_limit_list_range_planning.py) 的 10 项用例覆盖完整组合、子集、单日、休市、非法源交易所、既有日历配置、普通日线和指数周线。修复前 5 项因空计划失败，修复后 10 项通过；保留同一组独立预期。
- 新增回归、现有 unit planner、resolver、registry 合跑：198 通过，1 项既有失败。失败为 `test_planner_compresses_trade_dates_to_month_end` 调用已移除的 `_compress_to_month_end`；核对修改前 HEAD，方法已经不存在而测试仍在引用。本次不恢复旧 helper，也不修改该测试以掩盖失败。
- `tests/web/test_ops_manual_actions_api.py`、`tests/web/test_ops_runtime.py`：112 通过，均为隔离测试。
- 子系统依赖、dataset runtime registry、codebook 三项架构测试文件：11 通过。`ingestion-lint-definitions`、文档完整性检查和 `git diff --check` 通过。
- 临时真实验收证据为 `/private/tmp/limit_list_range_calendar_acceptance.json` 和 `/private/tmp/limit_list_range_real_acceptance_20261025.json`，后者记录日历、27 个源请求参数及本轮源码 SHA-256。它们是本轮本地审计文件，不是生产数据或长期仓库事实源。
- 本轮只修改本主案、Foundation 一处日期查询及新增回归文件；未变更 contract、页面、配置值或依赖方向，未进行生产写入、历史状态修补、部署或补数。CodeGraph 影响面已记录于 9.2；本次规划修复无待确认的实现边界，生产应用和正式下载验收尚未执行。

单元/隔离集成不替代正式下载验收；本次仅声称修复规划路径，生产发版与补数另行授权。
