# Tushare 请求策略与 Sync V2 对齐方案 v1（归档）

- 版本：v1
- 日期：2026-04-22
- 状态：已归档（后续以执行口径与简化方案为准）
- 范围：`Tushare` 数据集请求编排与 `sync_v2` 技术架构对齐（不含 Biying）

> 说明：本文件保留为过渡期设计记录；当前实施请优先参考：
> 1. [Tushare 全量数据集请求执行口径 v1（仅 Tushare）](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)
> 2. [Sync V2 数据集策略简化方案 v1（全量 47 个 V2 数据集）](/Users/congming/github/goldenshare/docs/architecture/sync-v2-dataset-strategy-simplification-plan-v1.md)

---

## 1. 背景与目标

本轮我们已经把“接口应该如何请求”逐条澄清完成，核心结论在：

1. [Tushare 全量数据集请求执行口径 v1（仅 Tushare）](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)
2. [数据集接口请求策略重审 v1（逐数据集）](/Users/congming/github/goldenshare/docs/ops/dataset-request-strategy-reassessment-v1.md)

当前任务目标是：基于现有代码真实实现，给出后续改造的技术方案，确保请求策略能稳定、可测试、可迁移地落地到 Sync V2。

---

## 2. 代码现状快照（已审计）

审计依据（代码）：

1. `src/foundation/services/sync/registry.py`
2. `src/foundation/services/sync_v2/contracts.py`
3. `src/foundation/services/sync_v2/validator.py`
4. `src/foundation/services/sync_v2/planner.py`
5. `src/foundation/services/sync_v2/worker_client.py`
6. `src/foundation/services/sync_v2/registry_parts/contracts/*.py`
7. `src/foundation/services/sync_v2/registry_parts/common/param_policies.py`
8. `src/cli.py` 与 `src/cli_parts/sync_handlers.py`

现状结论：

1. 全量同步资源 `56` 个，`sync_v2` 已覆盖 `47` 个，未迁移 `9` 个。  
2. `sync_v2` 已具备合同校验、锚点/窗口规划、分页拉取、归一化、写入等主链路能力。  
3. 但“请求策略”在代码层仍存在结构性问题：部分策略散落在 `planner + param_policies + 合同局部约定`，缺少统一的策略对象与门禁。

---

## 3. 现状与已拍板策略的主要差距

### 3.1 请求策略语义分散

当前问题：

1. `anchor_type/window_policy` 在合同里有定义，但“默认枚举扇出、全选折叠、分页阈值、是否需要 universe fanout”等语义分散在多个层。  
2. `__ALL__` 折叠语义主要靠参数构造函数隐式处理，非统一策略能力。  

影响：

1. 同类数据集容易出现“同口径不同实现”。  
2. 新增数据集时难以一眼判断是否符合请求策略基线。

### 3.2 Planner 角色过重

当前问题：

1. `SyncV2Planner` 同时负责锚点展开、枚举组合、证券池加载、部分 source fallback（如 `dc_index` 兜底读取）。  
2. 规划职责和数据源读取职责耦合，扩展复杂策略时改动风险高。  

影响：

1. 规划逻辑不易独立测试。  
2. 出现慢任务/挂起时定位粒度不够清晰（锚点、枚举、池加载、分页难拆开观测）。

### 3.3 板块族关键数据集默认策略与目标口径存在偏差

本轮已拍板的口径（仅这 4 个数据集）：

1. `dc_member`：不按板块代码扇出；以时间参数为核心分页请求。  
2. `ths_member`：无时间参数；默认单窗分页请求。  
3. `dc_daily`：不按板块代码扇出；按 `trade_date` 或 `start/end -> 交易日枚举` 分页请求。  
4. `ths_daily`：不按板块代码扇出；按 `trade_date` 或 `start/end -> 交易日枚举` 分页请求。  

当前 `sync_v2` 中，这 4 个数据集仍有默认 `universe_policy` 驱动板块池扇出路径，和上述口径不一致。  
另外，这 4 个数据集的分页 `limit` 应按各自文档上限执行（取值不同），不能用同一默认值覆盖。

### 3.4 CLI 触发语义与 run_profile 语义仍需进一步解耦

当前问题：

1. `sync-daily` 固定按 `trade_date` 驱动，天然偏 `point_incremental`。  
2. 月键/快照/区间类数据集虽可通过 `sync-history` 跑通，但入口语义还不够“策略化”。  

影响：

1. 容易在执行时误用命令（尤其是非 trade_date 主锚点的数据集）。  
2. 未来持续迁移时，命令层语义和合同语义会继续拉扯。

---

## 4. 目标架构（请求策略一等公民）

## 4.1 合同层新增“请求策略对象”（Request Strategy）

在 `DatasetSyncContract` 体系中补足“请求策略能力对象”，不再依赖隐式散点逻辑。

建议新增（或等价表达）：

1. `anchor_type`（已存在，继续沿用）
2. `window_policy`（已存在，继续沿用）
3. `sync_mode`（`point_incremental | range_rebuild | snapshot_refresh`，作为合同可见约束）
4. `fanout_policy`
5. `fold_policy`（全选折叠规则）
6. `pagination_policy`（页大小、终止条件）
7. `universe_policy`（证券池来源与触发条件）

其中关键点：

1. “用户显式多值 + 全选折叠”必须成为统一策略，不再靠个别参数函数临时判断。  
2. “默认是否扇出”必须显式配置（不是靠是否填 `enum_fanout_defaults` 猜测）。

### 4.2 Planner 分层（能力化，而非堆步骤）

将现有 Planner 拆成能力链（可在同文件先内聚，再分文件）：

1. `AnchorPlanner`：锚点日期/月键/快照基准计算  
2. `WindowPlanner`：point/range 窗口展开  
3. `FanoutPlanner`：枚举多值与笛卡尔组合  
4. `UniversePlanner`：证券池/指数池加载  
5. `PaginationPlanner`：分页 unit 生成策略  
6. `UnitAssembler`：最终 unit 组装与上限保护

这样每层都可独立加门禁测试。

### 4.3 参数生成统一化（Parameter Composer）

将 `param_policies.py` 中“参数透传 + 规范化 + 折叠”抽象为统一的组合器能力：

1. 统一处理日期字段格式化（`YYYYMMDD` / `YYYYMM`）  
2. 统一处理 list/multi-select 的 fanout 与 fold  
3. 统一处理固定参数注入（例如 `freq=daily`）  
4. 统一处理“未传不补”与“默认值注入”的边界

数据集只保留“最小特例函数”。

### 4.4 Universe Provider 外置（按新口径收敛）

将板块池/指数池读取能力从主 Planner 主体中解耦为 provider：

1. `index_active_codes` provider  
2. `dc_index_board_codes` provider（不再作为 `dc_member/dc_daily` 默认主路径）  
3. `ths_index_board_codes` provider（不再作为 `ths_member/ths_daily` 默认主路径）  

对这 4 个数据集，默认主路径改为“时间驱动分页（或 ths_member 单窗分页）”，而不是代码池扇出。

并给 provider 增加：

1. 可观测统计（命中数、空池、回退来源）  
2. 超时/失败错误语义（结构化错误码）

### 4.5 错误语义与观测增强

新增请求策略相关错误码（示例）：

1. `fanout_explosion_guard_hit`
2. `invalid_multi_select_combination`
3. `fold_policy_conflict`
4. `pagination_config_invalid`
5. `universe_provider_empty`

并上报到 execution/progress 日志中，便于 ops 直接定位请求层问题。

---

## 5. 数据集落地分组（面向 Tushare）

本轮以 Tushare 为主，按请求形态分组落地（不含 Biying）：

1. `trade_date 点式主导组`
2. `trade_date + 枚举扇出组`
3. `月键组（month_key_yyyymm）`
4. `自然月区间组（month_range_natural）`
5. `低频事件组（natural_date_range/event-date）`
6. `快照组（none）`
7. `周期锚点组（week_end_trade_date/month_end_trade_date）`

每组内统一一个策略模板，数据集只覆盖差异项，避免再出现“一表一套写法”。

---

## 6. 分期改造计划（仅技术方案）

### Phase A（策略骨架，不改外部行为）

1. 引入 `request_strategy` 结构与兼容转换层。  
2. 现有合同先自动映射到新结构，行为保持不变。  
3. 扩展 linter：校验 fanout/fold/pagination/universe 的一致性。  

### Phase B（Planner 与 Param Composer 收口）

1. Planner 能力分层实现，保持最终 unit 等价。  
2. 参数组合统一入口落地，逐步下沉 `param_policies` 特例。  
3. 补齐策略级错误码与进度日志。  

### Phase C（按组迁移 Tushare 数据集）

1. 先完成 `dc_member/ths_member/dc_daily/ths_daily` 的“去代码池扇出 + 时间/单窗分页”改造。  
2. 再低频事件与月键组。  
3. 再专项（`index_weight`, `stk_factor_pro` 等）。  

### Phase D（CLI 语义收口）

1. 保持现有命令兼容。  
2. 在内部路由上将 `sync-daily/sync-history` 显式映射到 `run_profile`，避免“命令语义与合同语义漂移”。  
3. 文档与 runbook 同步更新。

---

## 7. 门禁与回归（建议纳入执行基线）

最低门禁：

1. `tests/test_sync_v2_validator.py`
2. `tests/test_sync_v2_planner.py`
3. `tests/test_sync_v2_worker_client.py`
4. `tests/test_sync_v2_linter.py`
5. `tests/architecture/test_sync_v2_registry_guardrails.py`
6. 板块/热榜/资金流相关集成或冒烟命令（按 runbook 数据集批次）

新增建议门禁：

1. “全选折叠”策略测试（多字段多值场景）  
2. “枚举笛卡尔组合上限”保护测试  
3. “provider 空池/回退”错误语义测试  
4. “分页终止条件”一致性测试

---

## 8. 风险与控制

主要风险：

1. 策略收口期间行为漂移导致请求量激增或漏数。  
2. Planner 解耦过程中 unit 生成顺序变化影响对账节奏。  
3. CLI 入口语义调整引发运维误用。  

控制措施：

1. 分组迁移 + 单数据集切换 + 切后对账。  
2. 每次只迁一组，不跨组并行。  
3. （已更新）不再依赖 `USE_SYNC_V2_DATASETS`；回滚按提交粒度执行。  
4. runbook 强制执行“切换前后计数对账 + 样例抽检”。

---

## 9. 本文结论

1. 目前请求策略已经在业务口径上澄清，但代码层仍是“能力在、语义散”。  
2. 下一步不应继续“数据集级补丁”，应先把请求策略升格为合同一等能力。  
3. 在该技术方案下推进，能够在不破坏现网节奏的前提下，逐步把 Tushare 全量数据集收敛到统一、可审计、可扩展的 V2 请求体系。
