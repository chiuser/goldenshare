# Ops 多源综合运维契约 v2

更新时间：2026-04-14
适用范围：`src/ops/*`、`src/operations/*`、`src/platform/*`（Ops 相关）
上游依赖：Foundation 多源升级方案 v1
变更说明：在 v1 基础上，根据 UI 设计评审结论补充「数据集详情页」、调整 IA 结构、细化融合策略中心四 Tab 设计、明确导航与跳转契约；并在 v2.1 增补“基础能力优先”约束（逻辑层 resolution、发布对象拆分、append-only 快照、统一 ctx 契约等）。

---

## 1. 文档目标

本契约用于定义"多源 + 多层（raw/std/resolution/serving）"时代，Ops 平台必须遵守的统一规则：

1. 页面信息架构（IA）与能力边界。
2. 数据与指标口径（避免同名指标多套定义）。
3. API 契约（Foundation 提供给 Ops 的数据契约）。
4. 运行与发布契约（重跑、发布、审计、回滚）。

---

## 2. 设计原则

1. **单一事实来源**：同一指标只在一处定义，页面只消费，不自行计算。
2. **对象分层**：按"数据集 / 数据源 / 策略 / 运行发布"组织能力，而不是功能堆砌。
3. **全链路可观测**：覆盖 `raw → std → resolution → serving`，并覆盖上游源与下游服务。
4. **配置可回滚**：任何策略与配置变更必须版本化。
5. **诊断闭环**：从总览发现问题 → 详情页诊断 → 运维中心操作，全程不需要跨页手动重选上下文。
6. **工作流可感知**：融合策略中心四个阶段的工作流状态持久可见，用户随时知道当前在哪一步。

---

## 2.1 v2.1 基础能力优先约束（新增）

为保证平滑迁移，先补基础模型与契约，再迁移页面交互。以下约束优先级高于原型展示细节：

1. **resolution 先定义为逻辑层**：先观测“融合决策过程与指标”，不强制先落地物化 `resolution_*` 中间表。
2. **策略对象与发布对象拆分**：策略负责“声明”，发布负责“流程与结果”（预览、进度、回滚、审计）。
3. **快照采用 append-only 历史 + 当前视图**：保留当前快照读模型，同时新增历史明细，支持回溯与趋势诊断。
4. **执行对象补齐上下文**：`dataset_key/source_key/stage/policy_version/run_scope` 必须结构化落库，不再只依赖 `spec_key/params_json`。
5. **Probe 独立对象**：不复用 `job_schedule`，使用 `ops.probe_rule` 与独立执行记录。
6. **std 与融合规则先支持声明式白名单能力**：转换函数、清洗动作、冲突策略先限定可选集合，禁止任意脚本执行。
7. **导航上下文统一为 `ctx`**：页面跳转优先透传统一上下文对象，避免 URL 参数碎片化与扩展困难。

---

## 3. 页面信息架构（五页）

### v2 相对 v1 的核心调整

| 调整项 | v1 | v2 | 原因 |
|---|---|---|---|
| 新增数据集详情页 | 无 | 有 | 数据集卡片点击需要诊断上下文，跨页成本高 |
| Probe 规则位置 | 数据源管理 | 运维与发布中心 → 任务中心 → 调度管理 | Probe 是调度触发器，非监控配置 |
| 今日运行 | 独立 Tab | 合并入任务记录（默认 filter=今日） | 冗余，两套 UI 维护成本高 |
| 数据源管理职责 | 含 Probe 配置 | 纯监控（上游健康 + 下游健康 + 关联关系） | 职责收窄，页面更清晰 |
| 融合策略中心结构 | 单页版本列表 | 四 Tab：std规则 / 融合策略 / 发布管理 / 运行洞察 | 覆盖 std 生产层，工作流完整 |

---

### 3.1 数据状态总览

**定位**：扫描全量数据集风险，快速识别异常，一键进入详情或操作。

**必须展示**：
- 数据集基础信息：`dataset_key`、中文名称（副标题形式，非 badge）、分组标签、是否停用。
- 三层状态：`raw / std / serving` 各层最近成功时间、最近失败、延迟。
- 风险分级：`正常 / 关注 / 风险 / 阻断`（左侧色条）。
- Source 状态角标：每个数据集卡片右上角展示该 dataset 关联的所有 source 健康状态（带 source 名称缩写 + 颜色点 + hover tooltip）。
- 自动任务覆盖状态。
- 顶部汇总 metric：总数、正常数、关注数、风险/阻断数。

**交互要求**：
- **点击卡片主体** → 跳转数据集详情页（诊断上下文）。
- **点击"去处理"按钮** → 带 `dataset_key + source_key + 推荐操作` 跳转运维与发布中心 → 发布中心 → 分层重跑，相关字段预填。
- Source 角标 hover → tooltip 显示 `source_key: 状态 + 最近错误`。

**Source 角标设计规则**：
- 展示格式：`tu ●  bi ●`（source 名称缩写 + 状态色点），不能只展示色点（无法区分哪个 source）。
- 颜色：绿=正常、橙=关注、红=失败。

---

### 3.2 数据集详情页

**定位**：以 `dataset_key` 为中心的诊断页，聚合现在分散在三个页面的信息，做到"打开这一页就能完成诊断 → 判断 → 操作"全流程。

**入口**：数据状态总览卡片点击。
**面包屑**：数据状态总览 › `dataset_key`。

**必须展示**：

1. **页眉**
   - `dataset_key`（大字 + monospace）
   - 中文名称 · 分组（副标题）
   - 风险等级 badge
   - 关键异常摘要（如"raw 层失败 · 09:31"）
   - 快捷操作按钮：去处理 / 手动执行 / 分层重跑（均携带 `dataset_key` 上下文）

2. **Summary Metrics**（4格）
   - serving 版本 + 时间
   - 今日写入行数
   - serving lag
   - 今日执行次数（成功/失败）

3. **全链路层级状态**（横向四列流）
   - 按 `raw → std → resolution → serving` 排列
   - v2.1 约束：`resolution` 在第一阶段为“逻辑层状态”（决策耗时/冲突量/覆盖率/错误），不是强制物化中间表
   - 每列顶部色条 = 状态（绿/橙/红）
   - 每列展示：最近成功时间、最近失败时间、rows_in、rows_out、lag、错误信息

4. **数据来源状态**（每个 source 一张卡）
   - source 名称 + 角色（primary / fallback）+ 当前状态
   - 若 fallback 已接管：显示"接管中" badge + 说明
   - 若 fallback 接管但有数据缺失风险：显示警告条
   - 指标：成功率、失败次数、P95 延迟

5. **调度覆盖**
   - 该 dataset 被哪些 cron / probe 规则覆盖
   - 今日触发状态
   - 快捷跳转：查看调度 / 查看规则

6. **近期执行记录**（表格）
   - 字段：execution_id、trigger_mode、source_key、stage、状态、耗时、rows_in、rows_out、错误摘要

7. **当前生效融合策略**
   - 版本号 + 模式
   - 关键字段内联展示（mode、primary_source、fallback_source、freshness_window 等）
   - 快捷跳转：查看策略详情

---

### 3.3 数据源管理

**定位**：纯监控页，管理上游 source 健康和下游 Biz API 健康。Probe 规则已移出本页。

**必须展示**：

1. **上游数据源**（每个 source 一张卡）
   - 指标：QPS、成功率、失败率、P95 延迟、可用率、今日失败次数、积分/配额余额
   - 最近错误摘要（monospace 错误条）
   - 优先级标注（P1 主源 / P2 兜底）

2. **下游 Biz API 健康**
   - 汇总指标：API QPS、错误率、P95 延迟、当前服务数据版本
   - 按接口路径聚合表格

3. **Source → Dataset 关联关系**
   - 表格：source_key、dataset_key、角色（primary/fallback）、当前状态
   - 用途：故障时快速评估影响面；策略变更前估算波及范围

---

### 3.4 融合策略中心

**定位**：衔接 std 与 serving 的桥梁。管理 std 标准化规则（每个源的字段 mapping/类型统一/清洗）和融合策略（多源 std 行聚合为唯一 serving 行的规则），并提供发布管理与运行洞察。

**持久化工作流状态条**（始终显示，不随 Tab 切换消失）：

```
[std标准化规则 已生效] › [融合策略 draft编辑中] › [发布管理 待预览] › [运行洞察 v3运行中]
```

- 每个步骤可点击，直接跳转对应 Tab。
- 右侧显示当前数据集 + 上次发布时间。

#### Tab ① — std 标准化规则

**选择器设计**：三列导航（非串联下拉）：
- 左列：source 列表（带健康状态色点）
- 中列：该 source 下的 dataset 列表（带配置状态 badge：已配 / 待确认 / 未配）
- 右列：对应的字段映射规则与清洗规则

**字段映射表**：
- 列：源字段、→、标准字段、源类型、标准类型、转换函数、血缘保留（是否注入 source_key + std_at）、状态

**基础清洗规则表**：
- 列：规则类型、作用字段、条件、处置方式（丢弃/标记/保留最新）、今日触发量

**操作**：
- 保存草稿
- 下一步：配置融合策略 →（引导至 Tab ②）
- v2.1 约束：转换函数与清洗动作仅允许白名单枚举值（声明式），不支持任意脚本

#### Tab ② — 融合策略

**左侧**：版本列表（draft 草稿 + 历史版本，draft 用虚线边框区分）

**右侧 - 草稿编辑器**（点击 draft 时显示可编辑表单）：
- 选择数据集 + 聚合主键
- 融合模式（三张模式卡片选一）：
  - `primary_fallback`：主源优先，主源缺失时整行回退兜底源
  - `field_merge`：按字段配置各自来源
  - `freshness_first`：哪个源数据最新用哪个
- 来源配置：primary_source / fallback_source / freshness_window
- 字段级策略配置（逐字段：冲突策略 + 来源覆盖 + 备注）
- 底部引导条：提示"保存草稿后在③发布管理预览影响面"

**右侧 - 只读视图**（点击历史版本时显示）：
- 基础配置（key-value 网格）
- 字段级策略表
- 与上一版本的字段级 diff（红删绿增）
- 回滚按钮

**操作**：
- 新建草稿 / 从当前版本复制草稿
- 保存并去发布 →（引导至 Tab ③）
- 历史版本：回滚到指定版本
- v2.1 约束：策略对象只表达“应该如何融合”，不承载发布流程状态

#### Tab ③ — 发布管理

**发布流水（四步）**：
1. std 标准化（已生效 / 未配置）
2. 策略草稿（已保存 / 待编辑）
3. 预览 & 发布（当前步骤：影响面预览 + 确认发布）
4. serving 产出（重算完成后自动切换）

**影响面预览**：
- 受影响数据集列表（变更类型：mode 变更 / 无变化）
- 重算成本估算：影响行数、预计耗时、serving 停服窗口

**发布进度面板**（点击"确认发布为 vN"后展开）：
- 按"数据集 × 层级（raw / std / resolution / serving）"展示实时进度
- 状态：✓ 完成 / ◌ 运行中 / 等待 / ✗ 失败 / ✓ 跳过（无变化）
- 整体回滚按钮
- 链接至运维与发布中心 → 发布流水（完整日志）

**发布历史表**：版本 / 影响数据集数 / 发布时间 / 状态 / 回滚操作
- v2.1 约束：发布历史来自独立发布对象，不回写覆盖策略定义

#### Tab ④ — 运行洞察

**筛选器**：数据集 × 时间窗口 × 策略版本

**Summary Metrics**（4格）：
- 处理总行数（分 source 细分）
- 冲突总数
- 未决冲突数
- 兜底命中率

**字段级覆盖分布表**：
- 列：字段 / 主源行数 / fallback 行数 / 覆盖率 / 冲突策略

**serving 行血缘溯源（样本）**：
- 用途：业务方质疑某行数据时，可追溯该行 serving 数据的每个字段来自哪个 source、触发了哪种策略、使用了哪个版本
- 展示：主键（stock_code + trade_date）/ source chip（primary/fallback/override）/ 策略说明

**告警区**：
- 覆盖率超阈值告警（附跨 Tab 跳转按钮，如"去 Tab① 检查 std 规则"）

---

### 3.5 运维与发布中心

**定位**：融合任务执行与发布流水，扩展分层重跑与审计能力。

#### 一级 Tab A — 任务中心

**子 Tab：手动执行**
- 表单字段：数据集、数据来源（source_key）、执行层级（stage）、起始/结束日期、复权方式、策略版本
- 操作：立即执行

**子 Tab：调度管理**（含 cron + probe，并列显示）
- 表格：名称 / 类型（cron/probe，不同颜色 badge）/ 数据集 / 触发配置 / 状态 / 启停
- 操作：新建 Cron / 新建 Probe（分开入口，视觉区分）

Probe 规则最小字段：
- `dataset_key` / `source_key` / `window_start` / `window_end` / `probe_interval_seconds`
- `probe_condition`（如：最新交易日数据已出现且行数 >= 阈值）
- `on_success_action`（触发 job/workflow）
- `max_triggers_per_day`

**子 Tab：任务记录**（合并原"今日运行"，默认 filter=今日）
- 表格：execution_id / 数据集 / source_key / stage / trigger_mode / 状态 / 耗时 / rows_in / rows_out / 错误摘要
- 时间过滤：今日 / 近3天 / 近7天
- 支持点击查看执行详情（含每层 rows 与错误）

#### 一级 Tab B — 发布中心

**子 Tab：分层重跑**
- 表单：数据集 / source_key / 重跑层级（raw/std/resolution/serving 可选范围）/ 策略版本 / 日期区间
- 警告条：重跑完成后需手动确认或自动策略发布到 serving
- 操作：预估影响 / 开始重跑

**子 Tab：发布流水**
- 按发布任务展示（rel-id / 数据集 / source / 策略版本 / 各层状态 pill / 时间 / 回滚）

**子 Tab：审计日志**
- 事件类型（来自契约定义的六种）：
  - `source_config_changed`
  - `policy_published`
  - `policy_rolled_back`
  - `stage_rebuild_triggered`
  - `serving_release_switched`
  - `probe_rule_triggered`
- 展示：时间 / 事件类型 / 关键参数（dataset/source/stage/version）/ operator / 结果

---

## 4. 导航与跳转契约

| 触发点 | 跳转目标 | 携带上下文 |
|---|---|---|
| 总览卡片点击（主体） | 数据集详情页 | `ctx={dataset_key}` |
| 总览卡片"去处理"按钮 | 运维中心 → 发布中心 → 分层重跑 | `ctx={dataset_key, source_key, recommended_stage}` |
| 详情页"手动执行" | 运维中心 → 任务中心 → 手动执行 | `ctx={dataset_key}` |
| 详情页"分层重跑" | 运维中心 → 发布中心 → 分层重跑 | `ctx={dataset_key}` |
| 详情页"查看调度" | 运维中心 → 任务中心 → 调度管理 | `ctx={dataset_key}` |
| 详情页"查看策略详情" | 融合策略中心 → Tab② | `ctx={dataset_key}` |
| 融合策略 Tab① "下一步" | 融合策略中心 → Tab② | — |
| 融合策略 Tab② "保存并去发布" | 融合策略中心 → Tab③ | — |
| 发布进度"完整日志" | 运维中心 → 发布中心 → 发布流水 | `rel_id` |
| 洞察告警"去 Tab① 检查" | 融合策略中心 → Tab① | `ctx={dataset_key, source_key}` |
| 工作流状态条各步骤 | 融合策略中心对应 Tab | — |

`ctx` 建议使用统一 JSON 编码透传（query 中 base64url 或服务端 session context id），避免页面间字段不一致。

---

## 5. Ops 核心对象模型（契约级）

### 5.1 核心维度

- `dataset_key`：数据集标识（如 `equity_daily_bar`）
- `source_key`：数据来源标识（如 `tushare`、`biying`）
- `stage`：`raw / std / resolution / serving`
- `policy_version`：融合策略版本
- `run_scope`：`full / range / single / probe_triggered`
- `execution_id`：运行实例

### 5.2 运行对象扩展

现有执行对象需扩展以下字段：
- `dataset_key`
- `source_key`（可空，表示全来源）
- `stage`（可空，表示全链路）
- `policy_version`（发布/重算时记录）
- `run_scope`（区分全量、区间、单点、probe 触发）
- `trigger_mode`：`manual / schedule / probe / system`

### 5.3 std 标准化规则对象（新增）

```
std_mapping_rule:
  dataset_key
  source_key
  src_field
  std_field
  src_type
  std_type
  transform_fn        # 转换函数标识
  lineage_preserved   # bool，是否注入 source_key + std_at
  status              # active / draft / deprecated

std_cleansing_rule:
  dataset_key
  source_key
  rule_type           # null_filter / range_check / dedup / lineage_inject
  target_fields
  condition
  action              # drop / flag / keep_latest / inject
```

### 5.4 融合策略对象（v2 扩展）

```
resolution_policy:
  policy_id
  dataset_key
  version             # 整数，单调递增
  mode                # primary_fallback / field_merge / freshness_first
  primary_source
  fallback_source
  freshness_window_seconds
  auto_recompute      # bool
  aggregate_key       # 如 stock_code + trade_date
  status              # draft / active / archived

resolution_policy_field_rule:
  policy_id
  field_name
  conflict_strategy   # primary_wins / freshness_first / field_merge / compute
  source_override     # 可空，指定该字段来自哪个 source
  note
```

### 5.6 发布对象（v2.1 新增）

```
resolution_release:
  release_id
  dataset_key
  target_policy_version
  status              # previewing / running / succeeded / failed / rolled_back
  triggered_by
  triggered_at
  finished_at
  rollback_to_release_id

resolution_release_stage_status:
  release_id
  dataset_key
  source_key          # 可空
  stage               # raw/std/resolution/serving
  status              # pending/running/succeeded/failed/skipped
  rows_in
  rows_out
  message
  updated_at
```

### 5.7 快照历史对象（v2.1 新增）

```
dataset_layer_snapshot_history:
  id
  snapshot_date
  dataset_key
  source_key          # 可空
  stage
  status
  rows_in
  rows_out
  error_count
  last_success_at
  last_failure_at
  lag_seconds
  calculated_at
```

说明：`ops.dataset_status_snapshot` 继续作为“当前视图”，`dataset_layer_snapshot_history` 用于趋势与回溯。

### 5.5 审计对象扩展

新增审计事件分类：
- `source_config_changed`
- `policy_published`
- `policy_rolled_back`
- `stage_rebuild_triggered`
- `serving_release_switched`
- `probe_rule_triggered`

审计记录必须包含：`operator + event_type + before + after + reason + timestamp`

---

## 6. 指标口径字典（统一定义）

### 6.1 上游数据源指标（source_health）

- `source_qps`：每秒请求数
- `source_success_rate`：请求成功率
- `source_error_rate`：请求失败率
- `source_p95_latency_ms`：P95 延迟
- `source_availability`：可用率（窗口内成功探测比例）
- `source_last_error_message`：最近错误摘要

### 6.2 数据层指标（dataset_layer_health）

按 `dataset_key + stage (+ source_key)` 统计：

- `rows_in`：输入行数
- `rows_out`：输出行数
- `error_count`：失败行/失败批次数
- `success_rate`：本层处理成功率
- `last_success_at`：最近成功时间
- `last_failure_at`：最近失败时间
- `lag_seconds`：相对目标业务时间的延迟

### 6.3 融合层指标（resolution_health）

- `conflict_total`：冲突总数
- `conflict_unresolved`：未决冲突数
- `fallback_ratio`：兜底命中比例
- `field_override_ratio`：字段级覆盖比例（按字段）

### 6.4 下游服务指标（serving_health）

- `api_qps`：Biz API 请求速率
- `api_error_rate`：Biz API 错误率
- `api_p95_latency_ms`：Biz API P95 延迟
- `serving_release_version`：当前服务数据版本
- `serving_last_release_at`：最近发布时间

---

## 7. Foundation → Ops 数据契约（最小集合）

### 7.1 数据集状态契约

输入：`dataset_key（可选）/ source_key（可选）/ stage（可选）/ window（统计窗口）`

输出最小字段：`dataset_key / source_key / stage / status / rows_in / rows_out / error_count / last_success_at / last_failure_at / lag_seconds`

### 7.2 策略契约

读取：当前生效策略（含版本）/ 历史版本列表 / 版本 diff（字段级）

写入：发布新策略版本 / 回滚到指定版本

### 7.3 std 规则契约（v2 新增）

读取：指定 source_key + dataset_key 的字段映射规则列表 / 清洗规则列表

写入：创建/更新/停用映射规则 / 清洗规则

### 7.4 探测触发契约

写入：创建/更新/停用 probe_rule

运行：探测成功后触发指定任务或工作流

输出：每次探测记录与触发记录

### 7.5 血缘溯源契约（v2 新增）

输入：`dataset_key / trade_date / stock_code（或其他主键）`

输出：该行 serving 数据每个字段的 source_key / policy_version / trigger_time / fallback_reason

### 7.6 服务监控契约

读取：Biz API 运行健康指标（QPS、错误率、延迟）/ 按接口路径聚合的调用情况

### 7.7 统一跳转上下文契约（v2.1 新增）

输入：`ctx`

最小字段：
- `dataset_key`
- `source_key`（可选）
- `stage`（可选）
- `policy_version`（可选）
- `recommended_stage`（可选）

要求：所有跨页跳转与“去处理”入口优先使用 `ctx`，不得新增散落 query 字段作为长期契约。

---

## 8. 关键流程契约

### 8.1 探测触发流程

1. 到达探测窗口（如 15:30–16:30）。
2. 按频率执行 probe（如每 5 分钟）。
3. 若满足条件（最新交易日数据已更新且行数达阈值），触发目标任务。
4. 同日达到最大触发次数后停止。
5. 记录完整审计链路。

### 8.2 分层重跑流程

1. 选择数据集 + 来源 + 层级 + 时间范围 + 策略版本。
2. 生成 execution（标记 `stage` 与 `source_key`）。
3. 执行并记录每层 `rows_in/out` 与错误。
4. 可选发布到 serving（手动确认或自动策略）。
5. 失败可回滚到上一次 serving 版本。

### 8.3 策略发布流程

1. 在 Tab① 配置 std 规则（字段映射 + 清洗）。
2. 在 Tab② 编辑策略草稿（mode + 来源 + 字段级规则）。
3. 在 Tab③ 预览影响面（受影响数据集 + 重算成本）。
4. 确认发布为新版本（version+1）。
5. 发布进度面板实时展示各数据集各层状态。
6. 异常时整体回滚，发布日志同步至运维中心 → 发布流水。

### 8.4 故障诊断流程（v2 新增）

1. 数据状态总览发现数据集风险（色条 + source 角标异常）。
2. 点击卡片进入数据集详情页。
3. 查看全链路层级状态（哪层断了）。
4. 查看 Source 关联卡片（哪个 source 失败，fallback 是否接管）。
5. 查看近期执行记录（具体错误信息）。
6. 点击"去处理"直接跳转分层重跑，dataset_key 已预填。

---

## 9. 现有能力映射（旧五页 → 新五页）

| 现有能力 | 新页面归属 | 备注 |
|---|---|---|
| 数据状态 | 数据状态总览 | 扩展三层视图 + source 角标 |
| 今日运行 | 运维中心 → 任务中心 → 任务记录（默认今日过滤） | 合并冗余 Tab |
| 自动运行 | 运维中心 → 任务中心 → 调度管理 | 保留，含 cron + probe |
| 手动同步 | 运维中心 → 任务中心 → 手动执行 | 增加 stage/source 维度 |
| 任务记录/详情 | 运维中心 → 任务中心 → 任务记录 | 执行模型扩展 |
| 数据源健康（新增） | 数据源管理 | 纯监控，移出 probe |
| 数据集诊断（新增） | 数据集详情页 | 从总览卡片进入 |
| 融合策略 std 规则（新增） | 融合策略中心 → Tab① | 新增 std 层管理 |
| 融合策略版本（已有扩展） | 融合策略中心 → Tab② | 增加草稿编辑器 |
| 发布管理（新增） | 融合策略中心 → Tab③ | 含进度追踪 |
| 运行洞察（新增） | 融合策略中心 → Tab④ | 含血缘溯源 |
| 发布流水/审计（增强） | 运维中心 → 发布中心 | 增强层级粒度 |

---

## 10. 权限与审计契约

v1 建议保持管理员口径不变，细分审计事件：

- 所有策略发布/回滚动作必须记录 `operator + before + after + reason`。
- 所有分层重跑必须记录 `dataset/source/stage/range/policy_version`。
- 所有探测规则变更必须记录版本与生效时间。
- 所有 std 规则变更必须记录 `operator + src_field + std_field + transform_fn + before + after`。

---

## 11. 非功能要求（Ops 侧）

1. **性能**
   - 总览页首屏目标：2 秒内返回。
   - 数据集详情页首屏目标：1.5 秒内返回。
   - 分页列表 API：P95 < 500ms。

2. **可用性**
   - Ops 页面失败不应中断后台任务执行。
   - 发布操作必须支持幂等重试。

3. **一致性**
   - 页面展示与任务日志口径一致，不允许"页面与日志数字冲突"。
   - 数据集详情页指标与总览页卡片指标必须来自同一数据源。

---

## 12. 分期落地建议

### P1（Foundation 联调前必须完成）

1. 五页 IA 与对象模型定稿（本文件）。
2. 指标字典定稿。
3. Foundation → Ops 最小数据契约字段定稿（含血缘溯源契约）。

### P2（Foundation 开发并行）

1. 新执行模型扩展（stage/source/policy_version）。
2. 数据状态总览改为三层观测 + source 角标。
3. 数据集详情页上线（聚合现有数据）。
4. 运行中心支持按层重跑参数。

### P3（Foundation 切换后）

1. 数据源管理页上线（纯监控）。
2. 融合策略中心四 Tab 上线（std规则 + 策略编辑 + 发布管理 + 运行洞察）。
3. 发布中心上线（流水 + 进度追踪 + 回滚 + 审计）。
4. 血缘溯源 API 接入洞察 Tab。

---

## 13. 开发前检查清单（v2 补充）

1. 指标口径是否唯一且有定义。
2. 每个页面是否明确"对象与责任边界"。
3. 数据集详情页所需的聚合 API 是否已设计（7 块内容的数据来源）。
4. Source 角标展示是否包含 source 名称（不能只有色点）。
5. 总览"去处理"跳转是否携带 dataset_key + source_key + 推荐 stage。
6. 融合策略 std 规则是否支持字段级版本化。
7. 探测触发是否已配置化（非写死时间），probe 对象独立于 job_schedule。
8. 发布进度面板是否支持实时推送（SSE 或轮询）。
9. 任务记录是否包含 stage/source/policy_version 三个维度字段。
10. 是否有策略版本回滚路径（含 std 规则回滚）。
11. 血缘溯源数据是否在 serving 产出时同步写入。

---

## 14. 现状代码差距基线（Gap Matrix）

### 14.1 核心结论（v2 更新）

当前 Ops 能力在"单源 + 单层同步"模型下是成熟的，与目标多源模型存在五类结构性差距（v1 四类基础上新增 std 规则层）：

1. 执行模型缺少 `stage/source/policy_version`。
2. 数据状态缺少 `raw/std/serving` 三层视图。
3. 调度体系缺少"探测触发（probe）"原生对象。
4. 策略中心缺少版本化发布与回滚的独立对象模型。
5. **std 标准化规则缺少独立对象模型**（v2 新增）。

### 14.2 差距明细（继承 v1，新增 G11）

| 编号 | 目标能力 | 当前情况 | 风险级别 | 收敛建议 |
|---|---|---|---|---|
| G1 | 执行模型支持 stage/source/policy_version | 仅有 spec_type/spec_key/params_json | 高 | 增加结构化维度字段 |
| G2 | 步骤层可表达分层执行 | step_key 为通用字段，缺少层级语义 | 高 | 新增 stage 字段 |
| G3 | 数据状态页展示三层健康度 | 主要围绕单 target_table 新鲜度 | 高 | 新增 layer/source 统计模型 |
| G4 | Snapshot 可存储三层结果 | 当前按 dataset_key 单行快照 | 高 | 扩展为 dataset+source+stage 子表 |
| G5 | 调度支持探测触发（probe） | 仅支持 once/cron | 高 | 新增 probe_rule 模型与执行器 |
| G6 | 策略中心版本发布/回滚 | 有通用 revision，无策略对象 | 高 | 新增 resolution_policy_revision |
| G7 | 上游 source 健康监控 | 无对应端点 | 中 | 增加 source_health 查询 |
| G8 | 下游 Biz 服务监控 | 无对应端点 | 中 | 增加 serving_api_health 聚合查询 |
| G9 | 运行中心 + 发布中心双 Tab | 当前五页单源结构 | 中 | 重组导航为新五页结构 |
| G10 | 自动调度 SSE 刷新稳定性 | 已有 SSE，2秒轮询 | 低 | 可复用于 probe/发布进度广播 |
| G11 | **std 标准化规则独立对象** | 无 std_mapping_rule / std_cleansing_rule 表 | 高 | 新增两张规则表，支持版本化 |
| G12 | `resolution` 语义不清（逻辑层/物化层） | 页面目标已含四层，后端尚无明确边界 | 高 | v2.1 先定义为逻辑层观测，后续按触发条件再物化 |
| G13 | 发布与策略耦合 | 当前仅策略对象，无独立发布对象 | 高 | 新增 release/release_stage_status 对象 |
| G14 | 快照缺历史序列 | 仅当前快照，难以追趋势和回放 | 中 | 新增 append-only history 表 |
| G15 | 跳转参数碎片化风险 | 页面间透传字段不统一 | 中 | 引入统一 `ctx` 契约 |

### 14.3 已定稿的架构决策（继承 v1）

1. **快照模型采用方案 B**：保留总览表（单 dataset_key 粒度）+ 新增明细表（dataset_key + source_key + stage 粒度）。
2. **Probe 对象采用独立模型**：新增 `ops.probe_rule`，不复用 `job_schedule`。
3. **策略发布对象采用"策略对象 + revision"**：新增 `ops.resolution_policy` 与 `ops.resolution_policy_revision`。
4. **（v2 新增）std 规则采用独立对象**：新增 `ops.std_mapping_rule` 与 `ops.std_cleansing_rule`，支持 source_key + dataset_key 粒度管理。
5. **（v2.1 新增）resolution 先逻辑层**：先做可观测决策层，不强制先建物化 `resolution_*` 表。
6. **（v2.1 新增）发布对象独立**：新增 `ops.resolution_release` 与 `ops.resolution_release_stage_status`。
7. **（v2.1 新增）统一上下文契约**：跨页跳转统一透传 `ctx`。

---

## 15. 结论

Ops 在多源时代是"数据生产控制台"：

- **对上游**：监控源健康，智能触发（probe）。
- **对中游**：管理 std 标准化规则与多源融合策略，raw → std → resolution → serving 全链路可观测。
- **对下游**：监控对外服务，保障发布可回滚，提供字段级血缘溯源。
- **对运维**：任何异常从总览 → 详情 → 操作一步到位，不需要跨页手动重选上下文。

本契约作为后续编码与测试的统一依据，任何实现偏离都应先回到本契约评审。

---

## 16. v2.1 后端基础能力落实（2026-04-14）

以下能力已落地为可调用 API（作为新版 Ops UI 的后端底座）：

1. 探测规则（Probe）
   - `GET /api/v1/ops/probes`
   - `POST /api/v1/ops/probes`
   - `PATCH /api/v1/ops/probes/{probe_rule_id}`
   - `POST /api/v1/ops/probes/{probe_rule_id}/pause`
   - `POST /api/v1/ops/probes/{probe_rule_id}/resume`
   - `DELETE /api/v1/ops/probes/{probe_rule_id}`
   - `GET /api/v1/ops/probes/runs`
   - `GET /api/v1/ops/probes/{probe_rule_id}/runs`

2. 发布对象（Resolution Release）
   - `GET /api/v1/ops/releases`
   - `POST /api/v1/ops/releases`
   - `GET /api/v1/ops/releases/{release_id}`
   - `PATCH /api/v1/ops/releases/{release_id}/status`
   - `GET /api/v1/ops/releases/{release_id}/stages`
   - `PUT /api/v1/ops/releases/{release_id}/stages`

3. 标准化规则（Std Rule）
   - Mapping：
     - `GET /api/v1/ops/std-rules/mapping`
     - `POST /api/v1/ops/std-rules/mapping`
     - `PATCH /api/v1/ops/std-rules/mapping/{rule_id}`
     - `POST /api/v1/ops/std-rules/mapping/{rule_id}/disable`
     - `POST /api/v1/ops/std-rules/mapping/{rule_id}/enable`
   - Cleansing：
     - `GET /api/v1/ops/std-rules/cleansing`
     - `POST /api/v1/ops/std-rules/cleansing`
     - `PATCH /api/v1/ops/std-rules/cleansing/{rule_id}`
     - `POST /api/v1/ops/std-rules/cleansing/{rule_id}/disable`
     - `POST /api/v1/ops/std-rules/cleansing/{rule_id}/enable`

4. 分层快照历史查询（Layer Snapshot）
   - `GET /api/v1/ops/layer-snapshots/history`
   - `GET /api/v1/ops/layer-snapshots/latest`

5. 执行上下文扩展（Execution Context）
   - `ops.job_execution` 已新增并落库字段：
     - `dataset_key`
     - `source_key`
     - `stage`
     - `policy_version`
     - `run_scope`
   - 执行列表接口已支持过滤：
     - `dataset_key`
     - `source_key`
     - `stage`
     - `run_scope`

6. 测试覆盖（当前分支）
   - 已新增/更新 API 与模型测试，ops 相关回归通过：
     - `python -m pytest tests/web/test_ops_*.py tests/test_ops_*.py tests/test_dataset_status_snapshot_service.py -q`
     - 结果：`78 passed`

7. 桥接契约文档（过渡期）
   - 见：[ops-source-management-bridge-v1.md](./ops-source-management-bridge-v1.md)
   - 定位：仅用于旧页面迁移期的数据聚合读取，不作为长期稳定对外契约。

8. 页面迁移策略（已确认）
   - 采用“双菜单并行短过渡”：`V2.1` 与 `旧版（过渡）` 同时存在一段时间。
   - 旧版页面冻结，不再承接新需求。
   - `V2.1` 可用后切默认入口，再删除旧版与桥接。
