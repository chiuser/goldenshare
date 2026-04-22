# Phase 4：迁移切换与兼容收口（P1/P2）

- 版本：v1.0
- 日期：2026-04-21
- 状态：执行中（切换阶段持续推进）
- 关联文档：
  - [V2 主方案](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [Phase 1：执行域与事件模型](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-1-execution-domain.md)
  - [Phase 2：引擎与契约层](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-2-engine-contracts.md)
  - [Phase 3：工作流、Probe 与状态投影](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-3-workflow-probe-projection.md)

---

## 1. 本期目标与范围

### 1.1 本期目标

1. 在不中断现有能力前提下，将数据集同步链路从 V1 平稳迁移至 V2。  
2. 建立“可回滚”的切换策略（数据集级开关、双写窗口、读切窗口）。  
3. 收口不再需要的兼容代码与文档入口，避免长期双轨维护。  

### 1.2 本期范围（只做这些）

1. 迁移编排方案、灰度规则、回滚预案。  
2. 数据与状态一致性对账机制。  
3. 兼容层清理顺序与删除门禁。  

### 1.3 本期不做

1. 不在本期新增数据集业务能力。  
2. 不重构业务 API。  
3. 不进行无审计的一次性大清理。  

---

## 2. 迁移阶段拆解（按可回滚窗口）

## 2.1 阶段 M0：基线冻结

目标：

1. 冻结 V1 同步链路行为（仅修 bug，不扩功能）。  
2. 建立 V1 基线统计（请求次数、rows_fetched/written、失败率、耗时）。  

产物：

1. `baseline_metrics_{dataset}.json`
2. 数据集迁移白名单（初始为空）

## 2.2 阶段 M1：双链路并行（不切读）

目标：

1. V2 链路可运行，但 ops/biz 读取仍走现有稳定链。  
2. 同一数据集同一窗口执行 V1/V2 对账。  

规则：

1. 仅允许低风险数据集进入 M1（先 `trade_cal/stk_limit/margin`）。  
2. 执行顺序：V1 -> V2（避免相互覆盖影响）。  

门禁：

1. `rows_written` 偏差 <= 0.1%。  
2. 请求次数不高于 V1 基线 + 5%。  
3. 失败率不高于 V1 基线。  

## 2.3 阶段 M2：数据集级读切

目标：

1. 单个数据集将运行执行切到 V2。  
2. 若发生异常，可秒级回切到 V1。  

机制：

1. 开关：`USE_SYNC_V2_DATASETS`（集合）  
2. 回切：从集合移除 dataset_key 即可。  

门禁：

1. 连续 3 个交易日运行稳定。  
2. 无 P0/P1 级错误。  

## 2.4 阶段 M3：批量扩面

目标：

1. 按领域批量迁移（行情、资金流向、板块、低频事件）。  
2. 迁移中持续对账并记录偏差。  

规则：

1. 每批不超过 5 个数据集。  
2. 每批必须有至少 1 个“复杂策略数据集”做验证。  

## 2.5 阶段 M4：兼容层收口

目标：

1. 删除不再使用的 V1 兼容链路。  
2. 文档、运维脚本、测试入口全部对齐 V2。  

删除前硬门禁：

1. 引用审计清零（`src/tests/scripts/docs`）。  
2. 回归通过。  
3. 回滚方案演练通过。  

---

## 3. 模块级改造清单（迁移实施视角）

## 3.1 foundation（数据面）

| 模块 | 当前状态 | Phase 4 动作 |
|---|---|---|
| `src/foundation/services/sync/*.py` | V1 主链 | 按数据集逐步退场或转壳 |
| `src/foundation/services/sync_v2/*` | 新增 | 变为主链路 |
| `src/foundation/services/sync/registry.py` | V1 注册中心 | 增加路由层，后续仅保留兼容路由 |

## 3.2 ops（控制面）

| 模块 | 当前状态 | Phase 4 动作 |
|---|---|---|
| `ops/runtime/dispatcher.py` | V1+V2 过渡 | 切主语义为 run_profile + unit |
| `ops/services/*snapshot*` | 当前主投影 | 切到 V2 字段语义，保留兼容映射 |
| `ops/queries/*` | 前端读取入口 | 保持兼容字段，逐步启用新字段 |

## 3.3 app/biz（消费面）

| 模块 | 当前状态 | Phase 4 动作 |
|---|---|---|
| `biz` 查询与接口 | 稳定 | 不改契约，仅接入新增可观测字段 |
| `app` 入口 | 稳定 | 不承接迁移逻辑，仅路由装配 |

---

## 4. 数据与状态迁移清单（字段级）

字段说明口径说明：

1. 执行域表（`job_execution/job_execution_step/job_execution_event/job_execution_unit`）的“旧字段+新增字段”全量字典，统一以 [Phase 1 文档](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-1-execution-domain.md) 为准。  
2. 工作流/Probe/状态投影相关表（`probe_rule/probe_run_log/dataset_layer_snapshot_* /dataset_status_snapshot`）的“旧字段+新增字段”全量字典，统一以 [Phase 3 文档](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-3-workflow-probe-projection.md) 为准。  
3. Phase 4 不重复拆字段语义，专注切换顺序、门禁与回滚。  

## 4.1 执行域表迁移（Phase 1 产物落地后）

涉及表：

1. `ops.job_execution`
2. `ops.job_execution_step`
3. `ops.job_execution_unit`（新增）
4. `ops.job_execution_event`

迁移动作：

1. DDL 升级（新增字段/表/索引）。
2. 旧执行记录补默认值（如 `run_profile=point_incremental`）。
3. 查询层兼容旧记录空字段。

## 4.2 状态域表迁移（Phase 3 产物落地后）

涉及表：

1. `ops.dataset_layer_snapshot_current`
2. `ops.dataset_layer_snapshot_history`
3. `ops.dataset_status_snapshot`
4. `ops.probe_rule`
5. `ops.probe_run_log`

迁移动作：

1. 新字段先可空上线。  
2. 投影服务双写旧字段 + 新字段。  
3. 完成验证后再将关键字段升级为非空（若需要）。  

---

## 5. 对账与巡检机制（迁移期强制）

## 5.1 数据对账

每次迁移批次必须产出：

1. `only_v1`
2. `only_v2`
3. `common_diff`
4. `summary_counts`

建议命令（示意）：

1. `goldenshare reconcile-dataset --dataset <dataset_key> --start-date ... --end-date ...`

## 5.2 状态对账

必须核对：

1. execution 终态数量一致（按天）。  
2. snapshot freshness 状态一致（按 dataset）。  
3. probe 命中率变化在预期区间。  

## 5.3 巡检失败处理

1. 若出现 P0 差异：立即回切该数据集到 V1。  
2. 若出现 P1 差异：冻结扩面，仅保留试点集合。  

---

## 6. 测试与发布门禁（每批次）

## 6.1 自动化门禁

1. 架构边界测试：`tests/architecture/test_subsystem_dependency_matrix.py`  
2. 同步链路集成测试（按迁移数据集集）。  
3. ops 查询与页面最小冒烟。  

## 6.2 手工验收门禁

1. 手动同步（单数据集）可跑通。  
2. 自动任务（schedule + probe）可触发且可追踪。  
3. 数据状态页显示不回退、不空白。  

## 6.3 发布顺序

1. 先发只包含 DDL 与兼容读取。  
2. 再发写链路切换开关。  
3. 最后开 dataset 级路由。  

---

## 7. 回滚剧本（必须演练）

## 7.1 运行级回滚

1. 将 `dataset_key` 从 `USE_SYNC_V2_DATASETS` 移除。  
2. scheduler 保持运行，但新任务回到 V1。  

## 7.2 状态级回滚

1. snapshot 投影异常时可退回旧映射逻辑。  
2. 不删除历史记录，仅切换读取规则。  

## 7.3 数据级回滚

1. 若 V2 写入出现异常，不回滚历史数据，采用重跑修正。  
2. 回滚窗口内禁止 destructive SQL。  

---

## 8. 兼容层清理顺序（最终收口）

清理顺序建议：

1. 先删“无引用且无运行入口影响”的 shim。  
2. 再删 `foundation/services/sync` 内已迁移数据集壳。  
3. 最后清理 legacy 文档与脚本入口。  

必须后置项：

1. 运行入口相关兼容壳（若仍有外部依赖）。  
2. 高风险专项（`history_backfill_service`、`market_mood_walkforward_validation_service`）。  

---

## 9. 里程碑与验收标准

## 9.1 里程碑定义

1. `M1_READY`：V2 试点可运行且可对账。  
2. `M2_READY`：可按数据集级读切。  
3. `M3_READY`：批量扩面稳定。  
4. `M4_DONE`：兼容层收口完成。  

## 9.2 最终验收标准

1. 无数据集依赖“隐式参数拼装”逻辑。  
2. 错误语义统一可追踪到 `error_code + phase + unit_id`。  
3. 工作流、probe、状态投影语义一致。  
4. docs 与代码结构一致，无误导性历史信息。  
