# Ops 多源综合运维契约 v1

更新时间：2026-04-12  
适用范围：`src/ops/*`、`src/operations/*`、`src/platform/*`（Ops 相关）  
上游依赖：[Foundation 多源升级方案 v1](/Users/congming/github/goldenshare/docs/architecture/foundation-multi-source-upgrade-and-migration-v1.md)  
测试清单依赖：[Foundation 多源测试清单 v1](/Users/congming/github/goldenshare/docs/architecture/foundation-multi-source-test-refactor-checklist-v1.md)

---

## 1. 文档目标

本契约用于定义“多源 + 多层（raw/std/serving）”时代，Ops 平台必须遵守的统一规则：

1. 页面信息架构（IA）与能力边界。  
2. 数据与指标口径（避免同名指标多套定义）。  
3. API 契约（Foundation 提供给 Ops 的数据契约）。  
4. 运行与发布契约（重跑、发布、审计、回滚）。  

本版先定义契约，不直接约束 UI 视觉细节。

---

## 2. 设计原则

1. 单一事实来源：同一指标只在一处定义，页面只消费，不自行计算。  
2. 对象分层：按“数据集 / 数据源 / 策略 / 运行发布”组织能力，而不是功能堆砌。  
3. 全链路可观测：覆盖 `raw -> std -> serving`，并覆盖上游源与下游服务。  
4. 配置可回滚：任何策略与配置变更必须版本化。  
5. 运维先于交互：先把契约和数据模型定稳，再打磨 UI。

---

## 3. 页面信息架构（目标四页）

## 3.1 数据状态总览

定位：
- 按 `dataset_key` 观察三层状态：`raw/std/serving`。
- 一眼识别风险等级与影响范围。

必须展示：
- 数据集基础信息：名称、分组、是否停用。  
- 三层状态：最近成功时间、最近失败、延迟、覆盖范围。  
- 风险分级：`正常/关注/风险/阻断`。  
- 自动任务覆盖状态：是否被自动任务或工作流覆盖。  

交互要求：
- “去处理”携带上下文跳转运维与发布中心（预选数据集 + 推荐操作）。  

## 3.2 数据源管理

定位：
- 管“上游数据源接口健康 + 下游对外服务健康”。

必须展示：
- 上游（source）健康：吞吐、失败率、P95 延迟、可用率、最近错误。  
- 下游（Biz API）健康：调用量、失败率、P95 延迟、错误分布。  
- 关联关系：某 source 影响了哪些数据集。  

新增能力（探测触发）：
- 定义“探测策略”并自动触发任务，不写死时间逻辑。

探测策略最小字段：
- `dataset_key`
- `source_key`
- `window_start` / `window_end`（例：15:30-16:30）
- `probe_interval_seconds`（例：300）
- `probe_condition`（例：最新交易日数据已出现且行数 >= 阈值）
- `on_success_action`（触发 `job/workflow`）
- `max_triggers_per_day`

## 3.3 融合策略中心

定位：
- 管理多源融合策略（可视化编辑 + 版本治理）。

必须展示：
- 当前生效版本。  
- 版本差异（字段级 diff）。  
- 生效范围（影响哪些数据集）。  
- 一键回滚（切换到上一版本）。  

策略模式（v1）：
- `primary_fallback`
- `field_merge`
- `freshness_first`

## 3.4 运维与发布中心

定位：
- 融合现有“今日运行/自动运行/手动运行/任务记录”，并扩展分层重跑与发布流水。

推荐二级 Tab：

1. 运行中心  
- 今日运行  
- 自动运行  
- 手动运行  
- 任务记录  

2. 发布中心  
- 分层重跑（raw/std/resolution/serving）  
- 发布流水  
- 审计日志  

必须能力：
- 按层重跑、按 source 重跑、按数据集重跑、按时间区间重跑。  
- 发布原子切换与回滚。  
- 全链路审计（谁在何时做了什么）。

---

## 4. Ops 核心对象模型（契约级）

## 4.1 核心维度

- `dataset_key`：数据集标识（如 `equity_daily_bar`）  
- `source_key`：数据来源标识（如 `tushare`、`biying`）  
- `stage`：`raw/std/resolution/serving`  
- `policy_version`：策略版本  
- `execution_id`：运行实例  

## 4.2 运行对象扩展

现有执行对象需扩展以下字段：
- `dataset_key`
- `source_key`（可空，表示全来源）
- `stage`（可空，表示全链路）
- `policy_version`（发布/重算时记录）
- `trigger_mode`（manual/schedule/probe/system）

## 4.3 审计对象扩展

新增审计事件分类：
- `source_config_changed`
- `policy_published`
- `policy_rolled_back`
- `stage_rebuild_triggered`
- `serving_release_switched`
- `probe_rule_triggered`

---

## 5. 指标口径字典（统一定义）

## 5.1 上游数据源指标（source_health）

- `source_qps`：每秒请求数  
- `source_success_rate`：请求成功率  
- `source_error_rate`：请求失败率  
- `source_p95_latency_ms`：P95 延迟  
- `source_availability`：可用率（窗口内成功探测比例）  
- `source_last_error_message`：最近错误摘要  

## 5.2 数据层指标（dataset_layer_health）

按 `dataset_key + stage (+ source_key)` 统计：

- `rows_in`：输入行数  
- `rows_out`：输出行数  
- `error_count`：失败行/失败批次数  
- `success_rate`：本层处理成功率  
- `last_success_at`：最近成功时间  
- `last_failure_at`：最近失败时间  
- `lag_seconds`：相对目标业务时间的延迟  

## 5.3 融合层指标（resolution_health）

- `conflict_total`：冲突总数  
- `conflict_unresolved`：未决冲突数  
- `fallback_ratio`：兜底命中比例  
- `field_override_ratio`：字段级覆盖比例  

## 5.4 下游服务指标（serving_health）

- `api_qps`：Biz API 请求速率  
- `api_error_rate`：Biz API 错误率  
- `api_p95_latency_ms`：Biz API P95 延迟  
- `serving_release_version`：当前服务数据版本  
- `serving_last_release_at`：最近发布时间  

---

## 6. Foundation -> Ops 数据契约（最小集合）

Ops 至少需要以下读取契约（不要求一次性实现全部接口，可分批）：

## 6.1 数据集状态契约

输入：
- `dataset_key`（可选）
- `source_key`（可选）
- `stage`（可选）
- `window`（统计窗口）

输出最小字段：
- `dataset_key`
- `source_key`
- `stage`
- `status`
- `rows_in`
- `rows_out`
- `error_count`
- `last_success_at`
- `last_failure_at`
- `lag_seconds`

## 6.2 策略契约

读取：
- 当前生效策略（含版本）
- 历史版本列表
- 版本 diff

写入：
- 发布新策略版本
- 回滚到指定版本

## 6.3 探测触发契约

写入：
- 创建/更新/停用探测规则

运行：
- 探测成功后触发指定任务或工作流

输出：
- 每次探测记录与触发记录

## 6.4 服务监控契约

读取：
- Biz API 运行健康指标（QPS、错误率、延迟）
- 按接口路径聚合的调用情况

---

## 7. 关键流程契约

## 7.1 探测触发流程（示例：日线盘后）

1. 到达探测窗口（例如 15:30-16:30）。  
2. 按频率执行 probe（例如每 5 分钟）。  
3. 若满足条件（最新交易日数据已更新且行数达阈值），触发目标任务。  
4. 同日达到最大触发次数后停止。  
5. 记录完整审计链路。

## 7.2 分层重跑流程

1. 选择数据集 + 来源 + 层级 + 时间范围。  
2. 生成 execution（标记 `stage` 与 `source_key`）。  
3. 执行并记录每层 `rows_in/out` 与错误。  
4. 可选发布到 serving（手动确认或自动策略）。  
5. 失败可回滚到上一次 serving 版本。

## 7.3 策略发布流程

1. 草稿编辑。  
2. 预览影响面（受影响数据集/字段）。  
3. 发布新版本（`version+1`）。  
4. 自动触发重算或延后重算（按策略设置）。  
5. 异常时一键回滚。

---

## 8. 现有能力映射（旧五页 -> 新四页）

| 现有能力 | 新页面归属 | 备注 |
|---|---|---|
| 数据状态 | 数据状态总览 | 扩展为 raw/std/serving 三层 |
| 今日运行 | 运维与发布中心 -> 运行中心 | 保留 |
| 自动运行 | 运维与发布中心 -> 运行中心 | 保留 |
| 手动同步 | 运维与发布中心 -> 运行中心 | 保留，增加 stage/source 维度 |
| 任务记录/详情 | 运维与发布中心 -> 运行中心 | 保留，执行模型扩展 |
| 融合策略（新增） | 融合策略中心 | 新增 |
| 数据源健康（新增） | 数据源管理 | 新增 |
| 发布流水/审计（增强） | 运维与发布中心 -> 发布中心 | 增强 |

---

## 9. 权限与审计契约

v1 建议保持管理员口径不变，但细分审计事件：

- 所有策略发布/回滚动作必须记录 `operator + before + after + reason`。  
- 所有分层重跑必须记录 `dataset/source/stage/range`。  
- 所有探测规则变更必须记录版本与生效时间。  

---

## 10. 非功能要求（Ops 侧）

1. 性能
- 总览页首屏目标：2 秒内返回。
- 分页列表 API：P95 < 500ms。

2. 可用性
- Ops 页面失败不应中断后台任务执行。
- 发布操作必须支持幂等重试。

3. 一致性
- 页面展示与任务日志口径一致，不允许“页面与日志数字冲突”。

---

## 11. 分期落地建议

## P1（Foundation 联调前必须完成）

1. 四页 IA 与对象模型定稿（本文件）。  
2. 指标字典定稿。  
3. Foundation -> Ops 最小数据契约字段定稿。  

## P2（Foundation 开发并行）

1. 新执行模型扩展（stage/source/policy_version）。  
2. 数据状态总览改为三层观测。  
3. 运行中心支持按层重跑参数。  

## P3（Foundation 切换后）

1. 数据源管理页与探测触发上线。  
2. 融合策略中心上线。  
3. 发布中心上线（流水 + 回滚 + 审计）。

---

## 12. 开发前检查清单（Ops 契约）

1. 指标口径是否唯一且有定义。  
2. 每个页面是否明确“对象与责任边界”。  
3. 探测触发是否已配置化（非写死时间）。  
4. 是否支持单源可服务场景（仅 biying）。  
5. 任务执行模型是否包含 `stage/source/policy_version`。  
6. 是否有策略版本回滚路径。  

---

## 13. 结论

Ops 在多源时代不再只是“任务执行面板”，而是“数据生产控制台”：

- 对上游：监控源健康并智能触发。  
- 对中游：管理 raw/std/serving 全链路质量。  
- 对下游：监控对外服务并保障发布可回滚。  

本契约作为后续编码与测试的统一依据，任何实现偏离都应先回到本契约评审。

---

## 14. 现状代码差距基线（Gap Matrix）

本节基于当前代码审查，用于避免后续实施时出现“意外遗漏”。

## 14.1 核心结论

当前 Ops 能力在“单源 + 单层同步”模型下是成熟的，但与目标多源模型存在四类结构性差距：

1. 执行模型缺少 `stage/source/policy_version`。  
2. 数据状态缺少 `raw/std/serving` 三层视图。  
3. 调度体系缺少“探测触发（probe）”原生对象。  
4. 策略中心缺少版本化发布与回滚的独立对象模型。  

## 14.2 差距明细

| 编号 | 目标能力 | 现状代码位置 | 当前情况 | 风险级别 | 收敛建议 |
|---|---|---|---|---|---|
| G1 | 执行模型支持 `stage/source/policy_version` | [job_execution.py](/Users/congming/github/goldenshare/src/ops/models/ops/job_execution.py) | 仅有 `spec_type/spec_key/params_json/trigger_source` | 高 | 为 execution 与 step 增加结构化维度字段 |
| G2 | 步骤层可表达分层执行（raw/std/resolution/serving） | [job_execution_step.py](/Users/congming/github/goldenshare/src/ops/models/ops/job_execution_step.py) | `step_key/display_name` 为通用字段，缺少层级语义 | 高 | 新增 `stage` 字段并标准化步骤命名 |
| G3 | 数据状态页展示三层健康度 | [freshness_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py) | 当前主要围绕单个 `target_table` 与业务日期新鲜度 | 高 | 新增 layer/source 统计模型与查询器 |
| G4 | Snapshot 可存储三层结果 | [dataset_status_snapshot.py](/Users/congming/github/goldenshare/src/ops/models/ops/dataset_status_snapshot.py) 与 [dataset_status_snapshot_service.py](/Users/congming/github/goldenshare/src/operations/services/dataset_status_snapshot_service.py) | 当前按 dataset_key 单行快照 | 高 | 扩展为 dataset+source+stage（或拆分子表） |
| G5 | 调度支持探测触发（probe） | [job_schedule.py](/Users/congming/github/goldenshare/src/ops/models/ops/job_schedule.py) 与 [schedule_service.py](/Users/congming/github/goldenshare/src/operations/services/schedule_service.py) | 仅支持 `once/cron` | 高 | 新增 `probe_rule` 模型与执行器 |
| G6 | 策略中心（版本发布/回滚） | [config_revision.py](/Users/congming/github/goldenshare/src/ops/models/ops/config_revision.py) | 有通用 revision，但没有“策略对象”与发布语义 | 高 | 新增 `resolution_policy_revision` 或策略对象表 |
| G7 | 上游 source 健康监控 | 现有 ops API 无对应端点 | 未提供 source 维度吞吐/失败/延迟 | 中 | 增加 `source_health` 查询与 API |
| G8 | 下游 Biz 服务监控 | 现有 ops API 无对应端点 | 未纳入 Ops 页面统一视图 | 中 | 增加 `serving_api_health` 聚合查询 |
| G9 | 运行中心 + 发布中心双 Tab | [shell.tsx](/Users/congming/github/goldenshare/frontend/src/app/shell.tsx) 及现有五页 | 当前是五页单源结构 | 中 | 重组导航为新四页结构，保留已有功能入口 |
| G10 | 自动调度 SSE 刷新稳定性 | [schedules.py](/Users/congming/github/goldenshare/src/ops/api/schedules.py) | 已有 SSE，2 秒轮询签名 | 低 | 可复用于 probe/rule 变更广播 |

## 14.3 已有可复用资产（减少返工）

1. 执行链路完整（创建/重试/取消/事件/步骤）可直接扩展，不必重写。  
   - [execution_service.py](/Users/congming/github/goldenshare/src/operations/services/execution_service.py)
   - [dispatcher.py](/Users/congming/github/goldenshare/src/operations/runtime/dispatcher.py)
   - [worker.py](/Users/congming/github/goldenshare/src/operations/runtime/worker.py)

2. 配置变更审计已具备基础能力（`config_revision`）。  
   - 可作为策略发布审计底座扩展。

3. 现有调度预览、SSE 刷新、自动任务前端交互成熟。  
   - [ops-automation-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-automation-page.tsx)

## 14.4 已定稿的三个架构决策

1. 快照模型采用方案 B（已定）
- 保留总览表：`ops.dataset_status_snapshot`（单 `dataset_key` 粒度）
- 新增明细表：`ops.dataset_layer_snapshot`（`dataset_key + source_key + stage` 粒度）
- 结论：总览与明细解耦，兼容现有页面查询，同时支持多源多层观测。

2. Probe 对象采用独立模型（已定）
- 新增：`ops.probe_rule`
- 不复用 `job_schedule`，避免“定时触发”和“条件触发”语义混杂。
- 触发方式：probe 命中后走现有 execution 创建链路（不迁移旧 schedule 逻辑）。

3. 策略发布对象采用“策略对象 + revision”（已定）
- 新增策略对象表（如 `ops.resolution_policy`）与版本表（如 `ops.resolution_policy_revision`）。
- `config_revision` 继续保留为通用审计底座。

以上三项已定稿，可据此进入代码级 TODO 与编码阶段。

## 14.5 决策落地影响（编码前说明）

1. 对现有 API 的影响
- `/api/v1/ops/freshness`：继续返回总览口径，后续新增扩展字段或独立详情接口读取 layer 明细。
- 调度相关 API：不破坏现有 `/ops/schedules/*`；probe 走新增 `/ops/probe-rules/*`。

2. 对现有数据模型的影响
- `job_schedule`：不改语义，不承载 probe 条件字段。
- `job_execution` / `job_execution_step`：后续按计划增加 `stage/source/policy_version` 维度字段。

3. 对迁移复杂度的影响
- 低风险增量：新增表为主，旧表保持可用。
- 不进行“旧 schedule -> probe_rule”数据迁移；probe 为新能力独立接入。
