# Phase 2：引擎与契约层（P0）

- 版本：v1.0
- 日期：2026-04-21
- 状态：已执行（归档）
- 关联文档：
  - [V2 主方案](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [Phase 1：执行域与事件模型](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-1-execution-domain.md)

---

## 1. 本期目标与范围

### 1.1 本期目标

1. 建立 V2 同步引擎能力边界：校验、参数生成、调用、归一化、写入、观测、进度、错误语义。  
2. 建立 `DatasetSyncContract` 统一契约，替代“每个数据集各写各的”隐式逻辑。  
3. 建立 Source Adapter（ACL）层，彻底隔离 vendor 字段与协议。  
4. 设计 V1 -> V2 平稳兼容路径，支持分数据集迁移。  

### 1.2 本期范围（只做这些）

1. 引擎契约与标准数据结构定义。  
2. V2 运行主链模块设计（不要求一次性替换全部 sync 服务）。  
3. Contract Lint 规则与门禁设计。  
4. ACL 设计与数据源适配约束。  

### 1.3 本期不做

1. 不做全量数据集迁移。  
2. 不改业务 API 返回契约。  
3. 不改 ops 页面交互（仅补后端能力）。  

---

## 2. 引擎能力模型（能力视角，而非步骤口号）

## 2.1 核心能力组件

| 能力 | 职责 | 输入 | 输出 | 禁止事项 |
|---|---|---|---|---|
| Validator | 参数/语义/契约校验 | `RunRequest + Contract` | `ValidatedRunRequest` | 直接访问数据库写入 |
| Planner | 生成 unit 计划 | `ValidatedRunRequest + Contract` | `PlanBundle` | 直接调用外部接口 |
| WorkerClient | 调用控制（限流/重试） | `PlanUnit + Adapter` | `FetchResult` | 暴露 vendor 字段到上游 |
| Normalizer | 标准化 | `FetchResult.rows + NormalizeSpec` | `NormalizedBatch` | 自定义落库行为 |
| Writer | 幂等写入 | `NormalizedBatch + WritePolicy` | `WriteResult` | 回写运行状态 |
| Observer | 事件/审计上报 | 各阶段上下文 | `EventEnvelope` | 吞掉错误不报告 |
| ProgressReporter | 进度上报 | unit 统计 | `ProgressEvent` | 直接拼 UI 文案 |
| ErrorSemanticMapper | 错误标准化 | 原始异常 | `StructuredError` | 返回裸异常字符串 |

## 2.2 建议模块落位（实施目标）

1. `src/foundation/services/sync_v2/engine.py`  
2. `src/foundation/services/sync_v2/contracts.py`  
3. `src/foundation/services/sync_v2/validator.py`  
4. `src/foundation/services/sync_v2/planner.py`  
5. `src/foundation/services/sync_v2/worker_client.py`  
6. `src/foundation/services/sync_v2/normalizer.py`  
7. `src/foundation/services/sync_v2/writer.py`  
8. `src/foundation/services/sync_v2/observer.py`  
9. `src/foundation/services/sync_v2/error_mapper.py`  
10. `src/foundation/services/sync_v2/registry.py`  

说明：

1. 该目录为 V2 新链路，不替换 `src/foundation/services/sync/*.py` 现有实现。  
2. 迁移期由分数据集开关路由（见第 7 节）。  

---

## 3. 契约模型详细设计（字段级）

### 3.0 约束判定口径（本期统一）

1. **硬约束**：运行前必须满足；不满足直接失败（`validation_error`），不进入 planner。  
2. **软约束**：允许为空或回退默认值；由 contract default / global default 补齐。  
3. **可空策略**：
   - `不可空`：字段必须存在且值非空。  
   - `可空-条件必填`：默认可空，但在特定 `run_profile`/上下文下必须填写。  
   - `可空-透传`：可缺省，允许原样透传到下游。  
   - `可空-仅回显`：仅用于链路追踪或审计展示，不参与运行决策。  

## 3.1 RunRequest（统一请求模型）

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|
| `request_id` | `str` | 是 | 生成 | 硬约束 | 不可空 | 本次请求唯一 ID |
| `execution_id` | `int` | 否 | `null` | 软约束 | 可空-仅回显 | 对应 ops 执行实例 |
| `dataset_key` | `str` | 是 | 无 | 硬约束 | 不可空 | 目标数据集 |
| `source_key` | `str` | 否 | `null` | 软约束 | 可空-透传 | 指定数据源 |
| `run_profile` | `str` | 是 | 无 | 硬约束 | 不可空 | `point_incremental/range_rebuild/snapshot_refresh` |
| `trade_date` | `date` | 条件 | `null` | 硬约束 | 可空-条件必填 | 交易日锚点（仅适用于交易日语义） |
| `start_date` | `date` | 条件 | `null` | 硬约束 | 可空-条件必填 | 区间起始（交易日或自然日） |
| `end_date` | `date` | 条件 | `null` | 硬约束 | 可空-条件必填 | 区间结束（交易日或自然日） |
| `month` | `str` | 条件 | `null` | 硬约束 | 可空-条件必填 | 月键（`YYYYMM`） |
| `params` | `dict[str,Any]` | 是 | `{}` | 硬约束 | 不可空 | 数据集自定义参数 |
| `trigger_source` | `str` | 是 | 无 | 硬约束 | 不可空 | `manual/scheduled/probe/workflow` |
| `correlation_id` | `str` | 是 | 生成 | 硬约束 | 不可空 | 链路 ID |
| `rerun_id` | `str` | 否 | `null` | 软约束 | 可空-仅回显 | 续跑 ID |

不变量：

1. `run_profile=point_incremental` 时，必须满足该数据集 contract 声明的锚点输入（如 `trade_date` 或 `month`）。  
2. `run_profile=range_rebuild` 时，仅当该数据集 `window_policy` 支持区间才允许执行；且必须满足 `start_date<=end_date`。  
3. `run_profile=snapshot_refresh` 默认不接受时间参数，除非 contract 显式声明。  
4. `date_anchor_policy=week_end_trade_date/month_end_trade_date` 时，`trade_date` 必须通过交易日历锚点校验。  
5. `date_anchor_policy=month_range_natural` 时，`start_date/end_date` 必须是同月自然月首日/末日。  

## 3.2 DatasetSyncContract（每数据集必备）

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|
| `dataset_key` | `str` | 是 | 无 | 硬约束 | 不可空 | 数据集主键 |
| `display_name` | `str` | 是 | 无 | 硬约束 | 不可空 | 展示名 |
| `run_profiles_supported` | `tuple[str,...]` | 是 | 无 | 硬约束 | 不可空 | 支持的运行语义 |
| `input_schema` | `InputSchema` | 是 | 无 | 硬约束 | 不可空 | 参数定义 |
| `planning_spec` | `PlanningSpec` | 是 | 无 | 硬约束 | 不可空 | 扇开/锚点策略 |
| `source_adapter_key` | `str` | 是 | 无 | 硬约束 | 不可空 | ACL 适配器键 |
| `normalization_spec` | `NormalizationSpec` | 是 | 无 | 硬约束 | 不可空 | 字段映射规则 |
| `write_spec` | `WriteSpec` | 是 | 无 | 硬约束 | 不可空 | 写入策略 |
| `observe_spec` | `ObserveSpec` | 是 | 无 | 硬约束 | 不可空 | 观测与进度配置 |
| `rate_limit_spec` | `RateLimitSpec` | 否 | 全局默认 | 软约束 | 可空-透传 | 限流控制 |
| `pagination_spec` | `PaginationSpec` | 否 | `none` | 软约束 | 可空-透传 | 分页策略 |

## 3.3 InputSchema

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|
| `fields` | `list[InputField]` | 是 | 无 | 硬约束 | 不可空 | 参数字段定义 |
| `required_groups` | `list[list[str]]` | 否 | `[]` | 软约束 | 可空-透传 | 至少满足一组必填 |
| `mutually_exclusive_groups` | `list[list[str]]` | 否 | `[]` | 软约束 | 可空-透传 | 互斥组 |
| `dependencies` | `list[DependencyRule]` | 否 | `[]` | 软约束 | 可空-透传 | 依赖规则 |

`InputField` 字段字典：

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|
| `name` | `str` | 是 | 无 | 硬约束 | 不可空 | 参数名 |
| `type` | `str` | 是 | 无 | 硬约束 | 不可空 | `string/date/int/bool/enum/list` |
| `required` | `bool` | 是 | `false` | 硬约束 | 不可空 | 是否必填 |
| `default` | `Any` | 否 | `null` | 软约束 | 可空-透传 | 默认值 |
| `enum_values` | `list[str]` | 否 | `[]` | 软约束 | 可空-透传 | 枚举可选值 |
| `allow_empty` | `bool` | 是 | `false` | 硬约束 | 不可空 | 是否允许空字符串/空列表 |
| `description` | `str` | 是 | 无 | 硬约束 | 不可空 | 字段描述 |

## 3.4 PlanningSpec

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|
| `date_anchor_policy` | `str` | 是 | 无 | 硬约束 | 不可空 | `trade_date/week_end_trade_date/month_end_trade_date/month_range_natural/month_key_yyyymm/natural_date_range/none` |
| `window_policy` | `str` | 是 | 无 | 硬约束 | 不可空 | `point/range/point_or_range/none` |
| `universe_policy` | `str` | 是 | 无 | 硬约束 | 不可空 | `none/security_pool/index_pool/fund_pool` |
| `anchor_required_fields` | `list[str]` | 是 | 无 | 硬约束 | 不可空 | 当前语义必须满足的锚点字段（如 `trade_date/month/start_date,end_date`） |
| `source_time_param_policy` | `str` | 是 | 无 | 硬约束 | 不可空 | `trade_date/start_end/month_key/ann_date_window/none` |
| `enum_fanout_fields` | `list[str]` | 否 | `[]` | 软约束 | 可空-透传 | 需要枚举扇开的参数字段 |
| `pagination_policy` | `str` | 是 | `none` | 硬约束 | 不可空 | `none/offset_limit/page_no/cursor` |
| `chunk_size` | `int` | 否 | `null` | 软约束 | 可空-透传 | 区间切块大小 |
| `max_units_per_execution` | `int` | 否 | `null` | 软约束 | 可空-透传 | 单 execution 最大 unit |

## 3.5 PlanUnit（最小执行单元）

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|
| `unit_id` | `str` | 是 | 生成 | 硬约束 | 不可空 | 单元唯一键 |
| `dataset_key` | `str` | 是 | 无 | 硬约束 | 不可空 | 所属数据集 |
| `source_key` | `str` | 否 | `null` | 软约束 | 可空-透传 | 来源 |
| `trade_date` | `date` | 否 | `null` | 软约束 | 可空-透传 | 业务日锚点 |
| `request_params` | `dict[str,Any]` | 是 | `{}` | 硬约束 | 不可空 | 实际请求参数 |
| `pagination_cursor` | `str` | 否 | `null` | 软约束 | 可空-透传 | 分页游标 |
| `attempt` | `int` | 是 | `0` | 硬约束 | 不可空 | 尝试次数 |
| `priority` | `int` | 是 | `0` | 硬约束 | 不可空 | 优先级 |

## 3.6 FetchResult / NormalizedBatch / WriteResult

`FetchResult` 字段字典：

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|
| `unit_id` | `str` | 是 | 无 | 硬约束 | 不可空 | 对应计划单元 |
| `request_count` | `int` | 是 | `1` | 硬约束 | 不可空 | 实际请求次数 |
| `retry_count` | `int` | 是 | `0` | 硬约束 | 不可空 | 重试次数 |
| `latency_ms` | `int` | 是 | `0` | 硬约束 | 不可空 | 调用耗时 |
| `rows_raw` | `list[dict]` | 是 | `[]` | 硬约束 | 不可空 | 原始行列表 |
| `next_cursor` | `str` | 否 | `null` | 软约束 | 可空-透传 | 下一页游标 |
| `source_http_status` | `int` | 否 | `null` | 软约束 | 可空-仅回显 | 源响应状态码 |

`NormalizedBatch` 字段字典：

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|
| `unit_id` | `str` | 是 | 无 | 硬约束 | 不可空 | 对应计划单元 |
| `rows_normalized` | `list[dict]` | 是 | `[]` | 硬约束 | 不可空 | 通过标准化的行 |
| `rows_rejected` | `int` | 是 | `0` | 硬约束 | 不可空 | 拒绝行数 |
| `rejected_reasons` | `dict[str,int]` | 是 | `{}` | 硬约束 | 不可空 | 拒绝原因聚合 |

`WriteResult` 字段字典：

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|
| `unit_id` | `str` | 是 | 无 | 硬约束 | 不可空 | 对应计划单元 |
| `rows_written` | `int` | 是 | `0` | 硬约束 | 不可空 | 写入总行数 |
| `rows_upserted` | `int` | 是 | `0` | 硬约束 | 不可空 | upsert 行数 |
| `rows_skipped` | `int` | 是 | `0` | 硬约束 | 不可空 | 跳过行数 |
| `target_table` | `str` | 是 | 无 | 硬约束 | 不可空 | 写入目标表 |
| `conflict_strategy` | `str` | 是 | 无 | 硬约束 | 不可空 | 冲突策略标识 |

---

## 4. ACL（Source Adapter）设计

## 4.1 适配器接口

建议接口：

1. `build_request(unit: PlanUnit, contract: DatasetSyncContract) -> SourceRequest`
2. `execute(request: SourceRequest) -> SourceResponse`
3. `decode(response: SourceResponse) -> list[dict]`

约束：

1. vendor 参数名只存在于 adapter 内。  
2. adapter 输出必须是标准字段（我方命名）。  

## 4.2 适配器注册

建议文件：

1. `src/foundation/services/sync_v2/adapters/base.py`
2. `src/foundation/services/sync_v2/adapters/tushare.py`
3. `src/foundation/services/sync_v2/adapters/biying.py`
4. `src/foundation/services/sync_v2/adapters/registry.py`

## 4.3 错误归一（ACL 层）

| 原始错误 | 映射 error_code | retryable |
|---|---|---|
| HTTP 429 | `source_rate_limited` | `true` |
| HTTP 5xx | `source_server_error` | `true` |
| 超时 | `source_timeout` | `true` |
| 认证失败 | `source_auth_error` | `false` |
| 响应结构不合法 | `source_payload_invalid` | `false` |

---

## 5. 观测、进度、错误语义模型

## 5.1 StructuredError（统一错误类型）

| 字段 | 类型 | 必填 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|
| `error_code` | `str` | 是 | 硬约束 | 不可空 | 稳定错误码 |
| `error_type` | `str` | 是 | 硬约束 | 不可空 | `validation/planning/source/normalize/write/internal` |
| `phase` | `str` | 是 | 硬约束 | 不可空 | 发生阶段 |
| `message` | `str` | 是 | 硬约束 | 不可空 | 简明错误描述 |
| `retryable` | `bool` | 是 | 硬约束 | 不可空 | 是否可重试 |
| `unit_id` | `str` | 否 | 软约束 | 可空-仅回显 | 对应 unit |
| `details` | `dict` | 否 | 软约束 | 可空-透传 | 扩展信息 |

## 5.2 ProgressSnapshot（统一进度）

| 字段 | 类型 | 必填 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|
| `execution_id` | `int` | 是 | 硬约束 | 不可空 | 执行实例 |
| `dataset_key` | `str` | 是 | 硬约束 | 不可空 | 数据集 |
| `step_key` | `str` | 否 | 软约束 | 可空-透传 | 工作流步骤 |
| `unit_total` | `int` | 是 | 硬约束 | 不可空 | 总单元 |
| `unit_done` | `int` | 是 | 硬约束 | 不可空 | 成功单元 |
| `unit_failed` | `int` | 是 | 硬约束 | 不可空 | 失败单元 |
| `rows_fetched` | `int` | 是 | 硬约束 | 不可空 | 拉取行数累计 |
| `rows_written` | `int` | 是 | 硬约束 | 不可空 | 写入行数累计 |
| `updated_at` | `datetime` | 是 | 硬约束 | 不可空 | 更新时间 |

---

## 6. 与现有代码衔接（非破坏迁移）

## 6.1 现有入口

当前入口仍来自：

1. `src/ops/runtime/dispatcher.py` -> `build_sync_service(...)`
2. `src/foundation/services/sync/registry.py` -> 各 `Sync*Service`

## 6.2 V2 路由开关设计

新增开关（建议）：

1. `USE_SYNC_V2_DATASETS`：集合型，存 `dataset_key` 列表  
2. `SYNC_V2_STRICT_CONTRACT`：是否启用严格契约检查  

路由规则：

1. dataset 在 `USE_SYNC_V2_DATASETS` 中：走 `sync_v2.engine`。  
2. 不在集合中：继续走 V1 `build_sync_service`。  

## 6.3 兼容要求

1. `sync_daily/sync_history/backfill_*` CLI 与任务规格保持可用。  
2. 对外执行状态结构（execution list/detail）不破坏。  
3. V2 错误码新增不影响 V1 读取。  

---

## 7. 分数据集迁移策略（本期输出）

建议迁移顺序（先易后难）：

1. P2-A：`trade_cal`（无复杂扇开）  
2. P2-B：`stk_limit`（trade_date 扇开，单日上限明确）  
3. P2-C：`margin`（交易所扇开 + 日期维）  
4. P2-D：`moneyflow_ind_dc`（枚举扇开 + 分页）  

每个数据集迁移必须提交：

1. `DatasetSyncContract` 定义。  
2. 适配器映射说明（输入/输出字段对照）。  
3. 请求次数估算与限流策略。  
4. 与 V1 并行对账结果。  

---

## 8. 测试门禁与验收标准

## 8.1 Contract Lint（必须新增）

检查项：

1. `run_profiles_supported` 非空。  
2. `input_schema` 与 `planning_spec` 一致（如 `anchor_required_fields` 要求 `month` 但 input 未声明则失败）。  
3. `date_anchor_policy` 与 `window_policy` 组合合法（如 `none + point_or_range` 非法）。  
4. `source_time_param_policy` 与 adapter 能力匹配。  
5. pagination 策略与 adapter 能力匹配。  
6. write_spec 必填（含幂等键）。  

## 8.2 引擎集成测试

至少覆盖：

1. 参数非法 -> `validation_error`  
2. source 429 -> 可重试 + backoff  
3. normalize reject -> 统计与事件正确  
4. write 冲突 -> 幂等不重复计数  
5. cancel 请求 -> unit 边界停止  

## 8.3 迁移验收指标

1. 同 dataset 同窗口下：V1/V2 `rows_written` 差异 <= 0.1%。  
2. 请求次数：V2 不高于 V1（允许 <=5% 试点抖动）。  
3. 单执行失败可定位到 `unit_id + error_code`。  

---

## 9. 风险与回滚

主要风险：

1. 契约定义不全导致运行期才失败。  
2. ACL 映射不完整导致字段漂移。  
3. 并行双链路造成状态统计不一致。  

回滚策略：

1. 关闭 `USE_SYNC_V2_DATASETS` 对应数据集开关，秒级回 V1。  
2. 保留 V1 同步链路与 DAO，不在本期删除。  
3. 对于正在运行 execution，只终止 V2 新入队，不强制中断已运行任务。  
