# `stk_factor_pro` 全链路重做技术方案（V2 优先）

- 版本：v1.0（评审稿）
- 日期：2026-04-21
- 状态：待实施
- 适用范围：`src/foundation`、`src/ops`、`src/biz`、`frontend`、远程 `ops/foundation/raw_tushare/core_serving` 数据库对象
- 关联基线：
  - [数据同步 V2 重设计方案（含平稳迁移）](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [Phase 2：引擎与契约层](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-2-engine-contracts.md)
  - [Phase 4：迁移切换与兼容收口](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-4-cutover-migration.md)
  - [Tushare 股票技术面因子（专业版）数据集开发说明](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-dataset-development.md)

---

## 0. 结论（先说结果）

1. `stk_factor_pro` 不再继续做 V1 补丁式修复，改为“全链路重做”。
2. 按当前业务状态采用“无冻结阶段”执行：直接清理旧链路数据与脏状态，再按新链路回灌。
3. 新实现以 V2 契约/引擎为主路径，避免再把复杂度堆在 V1。
4. 对外业务口径保持稳定：`dataset_key=stk_factor_pro`、`core_serving.equity_factor_pro`、现有查询 API 不改契约。

---

## 1. 为什么必须重做（而不是继续小修）

### 1.1 已识别的问题类型

1. 字段体系不一致风险：存在“文档口径字段”和“数据库实现字段”长期漂移的问题，导致排障和扩展成本持续增大。
2. 旧链路可维护性差：V1 同步服务在参数校验、字段语义、错误语义、进度语义上缺少统一契约约束，容易出现“跑得动但不可治理”。
3. Ops 侧状态污染：执行记录、快照、状态表、规则表残留较多历史数据，影响观测与判断，易造成误导性“看起来正常”。
4. 依赖链长且隐式：数据链路跨 `raw -> serving -> biz quote overlay -> ops 页面`，问题外显常在后端 API 或前端展示时才暴露。
5. 继续补丁收益极低：局部修补无法根治“字段口径 + 引擎语义 + 状态治理”三类耦合问题。

### 1.2 不重做的后果

1. 同类故障会反复出现，且每次定位范围更大。
2. V2 迁移收益无法在该数据集兑现，形成“长期遗留孤岛”。
3. Ops 运维视图与真实数据质量偏差进一步扩大。
4. 后续 MACD/KDJ 相关业务联调成本持续上升。

### 1.3 重做的核心收益

1. 将数据集纳入 V2 统一契约，参数/规划/写入/观测语义一致化。
2. 清理脏状态后重建“可解释”运维视图。
3. 在不改对上 API 契约前提下，提升可维护性与可回归性。
4. 为后续同类数据集迁移提供标准模板。

---

## 2. 目标与边界

### 2.1 目标

1. 完成 `stk_factor_pro` 从 V1 到 V2 的全链路重做。
2. 清空并重建该数据集相关的 raw/serving 数据与 ops/foundation 元数据状态。
3. 保持对上查询口径稳定，保证 K 线页 MACD/KDJ 叠加能力可用。
4. 形成可复用的“数据集重做模板”。

### 2.2 非目标

1. 不改对上 API 返回结构与字段命名。
2. 不在本次顺带重构其他数据集。
3. 不做跨系统大范围前端改版，仅处理本数据集相关展示与配置项。

---

## 3. 当前链路范围盘点（重做覆盖面）

### 3.1 数据面

1. `raw_tushare.stk_factor_pro`
2. `core_serving.equity_factor_pro`

### 3.2 foundation / sync

1. V1：`src/foundation/services/sync/sync_stk_factor_pro_service.py`
2. V2：`src/foundation/services/sync_v2/*`（需新增 `stk_factor_pro` 合同与注册）
3. 路由：`src/foundation/services/sync/registry.py`（`USE_SYNC_V2_DATASETS`）

### 3.3 ops 编排与状态

1. specs/registry 中 `sync_daily|sync_history|backfill_by_trade_date.stk_factor_pro`
2. 执行与状态表：`job_execution*`、`dataset_layer_snapshot_*`、`dataset_status_snapshot`、`sync_job_state`、`sync_run_log`、`dataset_pipeline_mode`、`std_*_rule`
3. foundation 元数据：`dataset_source_status`、`dataset_resolution_policy`

### 3.4 biz / frontend

1. Biz 查询叠加：`src/biz/queries/quote_query_service.py` 对 `EquityFactorPro` 的 MACD/KDJ 读取
2. 前端 ops 展示：`frontend/src/shared/ops-display.ts`（资源文案与键值映射）
3. 前端测试：`frontend/src/pages/ops-v21-task-manual-tab.test.tsx` 相关 spec key 用例

---

## 4. 总体方案（V2 优先 + 无冻结阶段）

### 阶段 A：清场（直接 drop + 状态清理）

1. 不设冻结阶段，直接执行迁移清理脚本。
2. 删除目标数据表（raw + serving）。
3. 删除该数据集在 ops/foundation 的执行残留、快照残留、状态残留、规则残留。
4. 清理策略采用“链路迁移模板”实现，参考已存在 drop-chain 迁移模式。

### 阶段 B：V2 契约重建

1. 在 `sync_v2.registry` 新增 `stk_factor_pro` 合同定义。
2. 明确 `input_schema`、`planning_spec`、`source_spec`、`normalization_spec`、`write_spec`、`observe_spec`。
3. 统一字段语义：建立“上游字段 -> DB 字段”映射字典与类型规则，禁止隐式别名散落。
4. 接入 contract lint 与 validator 校验门禁。

### 阶段 C：执行链接线与开关切换

1. 保留 ops 现有 spec key，不改调用入口。
2. 使用 `USE_SYNC_V2_DATASETS=stk_factor_pro` 切该数据集到 V2。
3. 保留快速回切能力（开关移除即退回 V1 路由，作为应急兜底）。

### 阶段 D：回灌与验证

1. 先跑区间回补，后接日增量。
2. 验证 raw/serving 行数、一致性、幂等重复跑稳定性。
3. 验证业务接口能正确叠加 MACD/KDJ，且无异常压缩/缺值。
4. 验证 ops 页面状态与执行细节可读、可解释。

### 阶段 E：收口与清理

1. V2 稳定后清理 `stk_factor_pro` V1 专属实现与冗余测试分支。
2. 更新数据集开发文档，明确该数据集主链路为 V2。

---

## 5. 详细设计

### 5.1 数据模型与字段策略

1. 主键维持：`(ts_code, trade_date)`。
2. 目标表维持：`core_serving.equity_factor_pro`。
3. 字段处理策略：
   - 保留外部接口字段全集；
   - 通过显式映射表管理字段别名；
   - 类型转换规则集中在 normalizer，不允许写入层做隐式推断。
4. 质量门禁：
   - 必填键缺失直接 reject；
   - 类型不合法写入结构化错误；
   - rejected 统计进入事件与进度摘要。

### 5.2 V2 Contract 设计要点（`stk_factor_pro`）

1. `run_profiles_supported`：`point_incremental`、`range_rebuild`。
2. 输入参数：
   - 增量：`trade_date` 必填，`ts_code` 可选；
   - 区间：`start_date/end_date` 必填，`ts_code` 可选；
   - 分页：支持 `offset/limit`。
3. planner：
   - 交易日区间扇开；
   - 单日模式直接生成单 unit；
   - 区间模式按交易日生成 unit 列表。
4. writer：
   - raw + serving 双写幂等 upsert；
   - 记录 `rows_fetched/rows_written/rows_rejected`。
5. observer：
   - unit 级进度；
   - 结构化错误码；
   - 执行摘要可投影到 ops 状态页。

### 5.3 Ops 控制面与状态治理

1. 保留现有 job/workflow key，避免上层配置和前端联动破坏。
2. 清理与重建以下状态对象：
   - 执行链：`job_execution/job_execution_step/job_execution_event/job_execution_unit`
   - 快照链：`dataset_layer_snapshot_current/history`、`dataset_status_snapshot`
   - 运行态：`sync_job_state`、`sync_run_log`
   - 治理规则：`std_mapping_rule`、`std_cleansing_rule`
   - 数据源态：`dataset_source_status`、`dataset_resolution_policy`
3. 清理完成后，首轮回灌执行必须重新生成完整快照，禁止沿用旧快照。

### 5.4 Biz 与前端配合策略

1. Biz 查询接口保持不变，仅保证 `equity_factor_pro` 数据完备性与时间范围覆盖。
2. 前端以“最小变更”原则：
   - 保留资源 key 与展示名；
   - 仅修正因旧链路遗留导致的错误文案或状态映射。
3. 对外口径稳定，不新增页面级功能需求。

---

## 6. 执行步骤（实施顺序）

1. 提交“drop + 状态清理”迁移脚本。
2. 部署迁移并执行清场。
3. 提交 `stk_factor_pro` V2 contract 与接线。
4. 打开 `USE_SYNC_V2_DATASETS=stk_factor_pro`。
5. 执行历史回补（区间）并核验。
6. 接入日增量任务并核验。
7. 通过验收后移除 V1 专属实现。

---

## 7. 验收标准（必须全部满足）

1. 功能验收：
   - `sync_daily/sync_history/backfill_by_trade_date.stk_factor_pro` 全部可执行；
   - MACD/KDJ 叠加读取链路可用。
2. 数据验收：
   - raw 与 serving 主键冲突策略正确；
   - 重复回放无脏重复；
   - 关键字段缺失率在可接受范围内并可追踪原因。
3. 运维验收：
   - ops 执行详情可见 unit 级进度；
   - dataset freshness 与 layer snapshot 更新正常。
4. 质量验收：
   - contract lint 通过；
   - 单测/集成测试通过；
   - 关键回归用例（quote kline + ops catalog）通过。

---

## 8. 风险与应对

1. 风险：清场后到回灌完成前，指标查询可能短时间为空。
   - 应对：安排低峰窗口，按“清场即回灌”连续执行。
2. 风险：V2 合同初版字段映射遗漏。
   - 应对：上线前跑字段覆盖比对脚本，缺失即阻断发布。
3. 风险：ops 旧快照误导。
   - 应对：清场迁移中强制删除该数据集快照并重建。

---

## 9. 里程碑建议

1. M1（P0）：完成清场迁移脚本与评审。
2. M2（P0）：完成 `stk_factor_pro` V2 contract 与路由接线。
3. M3（P1）：完成全量回灌与验收。
4. M4（P1）：完成 V1 收口与文档更新。

---

## 10. 交付物清单

1. 技术方案文档（本文）。
2. 数据清场迁移脚本（alembic）。
3. `stk_factor_pro` V2 contract 与同步实现代码。
4. 回归与验收报告（数据一致性 + ops + quote）。

