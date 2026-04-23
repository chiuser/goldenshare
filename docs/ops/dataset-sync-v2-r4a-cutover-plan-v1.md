# 数据同步 V2 R4-A 切换方案 v1（`dividend` / `stk_holdernumber` / `index_weight`）

- 版本：v1.0
- 日期：2026-04-22
- 状态：已完成（代码+门禁+对账）
- 范围：仅 Tushare，且仅 3 个数据集
- 关联文档：
  - [数据同步 V2 切换运行手册 v1](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-cutover-runbook-v1.md)
  - [Tushare 全量数据集请求执行口径 v1（仅 Tushare）](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)
  - [Sync V2 Registry 开发指南 v1](/Users/congming/github/goldenshare/docs/architecture/sync-v2-registry-development-guide-v1.md)

---

## 1. 本轮目标

本轮只做 1 件事：为 `dividend`、`stk_holdernumber`、`index_weight` 制定可执行的 V2 contract + 切换方案，并明确门禁、对账、回滚。

本轮不做：

1. 不处理 Biying 数据集。
2. 不处理 `stock_basic` / `stk_factor_pro` / `index_weekly` / `index_monthly`。
3. 不改上层 biz API 契约。

---

## 2. 现状审计（代码基线）

### 2.1 当前未迁移事实

截至当前代码基线，这 3 个数据集均未进入 `SYNC_V2_CONTRACTS`：

1. `dividend`
2. `stk_holdernumber`
3. `index_weight`

运行手册中的未迁移清单与代码一致（`47/56` 已覆盖）。

### 2.2 V1 现状差距（本轮要解决）

1. `dividend`  
现有参数构造仅透传 `ts_code/ann_date`，未覆盖文档中的 `record_date/ex_date/imp_ann_date`，且缺少显式分页策略。

2. `stk_holdernumber`  
沿用 `dividend` 的旧参数构造函数，和文档中的 `start_date/end_date` 主能力不完全对齐；分页策略未显式化。

3. `index_weight`  
V1 已做“按 `index_code` 扇开 + 月窗口”能力，但尚未 contract 化到 V2；且该数据集当前不在 `sync_daily` 资源集内，不能按 `sync_daily` 路径验证。

4. 对账门禁  
`reconcile-dataset` 当前不支持这 3 个数据集，导致“切后可验”链路不完整。

---

## 3. 目标请求口径（本轮拍板口径）

先明确：以下口径严格以源文档“输入参数”表为准，不把内部执行锚点当作接口输入参数。

| 数据集 | 接口 | 文档分页上限 | 时间锚点口径 | 默认请求方式 |
| --- | --- | --- | --- | --- |
| `dividend` | `dividend` | `6000`（工程口径） | `natural_date_range`（自然日 -> `ann_date`） | 上层传 `start_date/end_date`，按自然日展开并逐日映射为 `ann_date` 请求；分页闭环 |
| `stk_holdernumber` | `stk_holdernumber` | `3000`（文档） | `natural_date_range`（自然日 -> `ann_date`） | 与 `dividend` 同口径：上层 `start_date/end_date` 自然日展开，逐日映射 `ann_date` 请求；分页闭环 |
| `index_weight` | `index_weight` | `6000`（工程口径） | `month_range_natural`（自然月窗口） | 以 `index_code + start/end` 为核心；按指数池扇开 + 分页闭环 |

说明：

1. `index_weight` 的“月度口径”按文档原文执行：建议使用当月自然日首尾，不使用“月末交易日锚点”。
2. 本轮不引入新的通用 provider 抽象；指数池扇开在数据集策略函数内实现。
3. `dividend/stk_holdernumber` 的源接口都不接受 `trade_date`；`start_date/end_date` 是上层执行参数，由策略层转换为逐日 `ann_date` 请求。

---

## 4. 目标落位（文件级）

### 4.1 Contract 落位

1. `dividend` -> `src/foundation/services/sync_v2/registry_parts/contracts/low_frequency.py`
2. `stk_holdernumber` -> `src/foundation/services/sync_v2/registry_parts/contracts/low_frequency.py`
3. `index_weight` -> `src/foundation/services/sync_v2/registry_parts/contracts/index_series.py`

### 4.2 策略函数落位

1. `build_dividend_units` -> `src/foundation/services/sync_v2/dataset_strategies/dividend.py`
2. `build_stk_holdernumber_units` -> `src/foundation/services/sync_v2/dataset_strategies/stk_holdernumber.py`
3. `build_index_weight_units` -> `src/foundation/services/sync_v2/dataset_strategies/index_weight.py`
4. 注册到 `src/foundation/services/sync_v2/dataset_strategies/__init__.py`

### 4.3 参数/转换函数落位

复用或新增最小函数于：

1. `src/foundation/services/sync_v2/registry_parts/common/param_policies.py`
2. `src/foundation/services/sync_v2/registry_parts/common/row_transforms.py`（如需要）

---

## 5. 三个数据集的 V2 契约设计

## 5.1 `dividend`

### 合同建议

1. `run_profiles_supported`：`("range_rebuild", "snapshot_refresh")`
2. `anchor_type`：`natural_date_range`
3. `window_policy`：`range`
4. `pagination_policy`：`offset_limit`
5. `page_limit`：`6000`
6. `universe_policy`：`none`

### 输入参数（最小必需）

1. 上层执行参数：`start_date/end_date`（自然日区间）
2. 源接口过滤参数：`ts_code/ann_date/record_date/ex_date/imp_ann_date`
3. 不接受：`trade_date`

### 请求编排（策略函数）

1. `range_rebuild`（主路径）：  
上层 `start_date/end_date` 按自然日（含首尾）展开；每个自然日生成一个单元，请求参数为 `ann_date=YYYYMMDD`。
2. 显式过滤叠加：  
若用户还传了 `ts_code/record_date/ex_date/imp_ann_date`，与 `ann_date` 组合透传。
3. `snapshot_refresh`：  
仅允许显式过滤（如 `ts_code` 或事件日期字段）；禁止空参数全市场扫描。
4. 分页：  
`offset += 6000`，直到返回 `< 6000`。

### 归一化与写入

1. 复用 V1 现有字段集与 `row_key_hash/event_key_hash` 生成逻辑。
2. 保留 `ex_date` 自动补齐逻辑与缺失主键字段跳过逻辑。
3. `write_path`：`raw_core_upsert`（保持不变）。

## 5.2 `stk_holdernumber`

### 合同建议

1. `run_profiles_supported`：`("range_rebuild", "snapshot_refresh")`
2. `anchor_type`：`natural_date_range`
3. `window_policy`：`range`
4. `pagination_policy`：`offset_limit`
5. `page_limit`：`3000`
6. `universe_policy`：`none`

### 输入参数（最小必需）

1. 上层执行参数：`start_date/end_date`（自然日区间）
2. 源接口过滤参数：`ts_code/ann_date/enddate`
3. 不接受：`trade_date`

### 请求编排（策略函数）

1. `range_rebuild`（主路径）：  
上层 `start_date/end_date` 按自然日（含首尾）展开；每个自然日生成一个单元，请求参数为 `ann_date=YYYYMMDD`。
2. 显式过滤叠加：  
若用户还传 `ts_code/enddate`，与 `ann_date` 组合透传。
3. `snapshot_refresh`：  
仅允许带显式过滤（如 `ts_code`），不允许空参数全量快照。
4. 分页：  
`offset += 3000`，直到返回 `< 3000`。

### 归一化与写入

1. 复用 V1 字段归一化与 `row_key_hash/event_key_hash`。
2. 保持 `required_fields=("ts_code","end_date")` 的写入约束。
3. `write_path`：`raw_core_upsert`（保持不变）。

## 5.3 `index_weight`

### 合同建议

1. `run_profiles_supported`：`("range_rebuild",)`
2. `anchor_type`：`month_range_natural`
3. `window_policy`：`range`
4. `pagination_policy`：`offset_limit`
5. `page_limit`：`6000`
6. `universe_policy`：`none`（指数池扇开在策略函数内实现）

### 输入参数（最小必需）

1. 时间：`trade_date/start_date/end_date`
2. 过滤：`index_code`

### 请求编排（策略函数）

1. `range_rebuild`：  
直接透传 `start_date/end_date`。
2. 指数池：  
优先使用用户显式 `index_code`；未传时从活跃指数池加载并逐指数扇开。
3. 分页：  
每个 `index_code + 时间窗` 独立分页，`offset += 6000`，直到返回 `< 6000`。

### 归一化与写入

1. 复用现有主键：`(index_code, trade_date, con_code)`。
2. `write_path`：`raw_core_upsert`（保持不变）。

---

## 6. 对账门禁设计（本轮必须补齐）

在 `operations_dataset_reconcile_service` 新增 3 项配置：

1. `index_weight`：`mode=daily`，日期字段 `trade_date -> trade_date`
2. `dividend`：`mode=daily`，日期字段 `ann_date -> ann_date`
3. `stk_holdernumber`：`mode=daily`，日期字段 `ann_date -> ann_date`

说明：

1. 对于 `ann_date` 为空的低频记录，差异观察以样本抽检补充；本轮先确保“可切后对账”闭环成立。
2. 若评审认为需更严格，可在后续补一个 `event_snapshot` 模式（本轮不扩范围）。

---

## 7. 实施任务包（R4-A）

1. `R4A-WP-01`：补 3 个 contract（`low_frequency.py` + `index_series.py`），严格按源文档输入参数建模。
2. `R4A-WP-02`：补 3 个 dataset strategy 文件并注册到策略注册表。
3. `R4A-WP-03`：补参数构造函数与必要 row_transform（最小新增）。
4. `R4A-WP-04`：补 `reconcile-dataset` 的 3 个数据集支持。
5. `R4A-WP-05`：修正 `ops/specs/registry.py` 的 `sync_history` 参数暴露，确保与文档参数一致（至少覆盖 `dividend/stk_holdernumber` 的事件/区间参数）。
6. `R4A-WP-06`：更新门禁测试与 registry guardrails 矩阵。
7. `R4A-WP-07`：按单数据集串行执行远程切换与对账（先 `stk_holdernumber`，再 `dividend`，最后 `index_weight`）。

---

## 8. 本轮门禁（全部通过才允许切换）

1. `pytest -q tests/architecture/test_sync_v2_registry_guardrails.py`
2. `pytest -q tests/test_sync_v2_registry_routing.py`
3. `pytest -q tests/test_sync_v2_validator.py tests/test_sync_v2_planner.py tests/test_sync_v2_linter.py`
4. `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts`
5. 每个数据集执行最小窗口冒烟 + 对账：
  - `sync-history`（小时间窗）
  - `reconcile-dataset`（同窗，`abs_diff=0`）

---

## 9. 远程切换执行建议（评审后执行）

固定顺序（风险从低到高）：

1. `stk_holdernumber`
2. `dividend`
3. `index_weight`

每个数据集固定流程：

1. （历史执行）加入 `USE_SYNC_V2_DATASETS`
2. 重启 `web/worker/scheduler`
3. 跑 `sync-history` 小窗口验证
4. 跑 `reconcile-dataset` 对账
5. 通过后进入下一个数据集

---

## 10. 回滚方案（单数据集粒度）

任一数据集失败即回滚，不影响其他数据集：

1. （历史执行）从 `USE_SYNC_V2_DATASETS` 移除当前数据集。
2. 重启三服务。

---

## 11. 本轮执行结果（2026-04-22）

代码结果：

1. 已补齐 V2 contract：`dividend`、`stk_holdernumber`、`index_weight`。
2. 已补齐 3 个策略函数与参数构造：
  - `build_dividend_units`
  - `build_stk_holdernumber_units`
  - `build_index_weight_units`
3. 已补齐 `reconcile-dataset` 三数据集支持。
4. 已补齐 ops `sync_history` 参数暴露（`dividend/stk_holdernumber` 事件过滤字段）。
5. 已补齐门禁测试（registry guardrails / validator / strategy / ops specs / reconcile）。

门禁结果：

1. `pytest` 门禁集合：`64 passed`。
2. `goldenshare sync-v2-lint-contracts`：`passed`。

最小窗口冒烟 + 对账结果：

1. `dividend`：`sync-history fetched=0 written=0`；对账 `abs_diff=0`。
2. `stk_holdernumber`：`sync-history fetched=0 written=0`；对账 `abs_diff=0`。
3. `index_weight`：`sync-history fetched=300 written=300`；对账 `abs_diff=0`。
3. 复跑该数据集一次，确认 V1 路径恢复。
4. 记录失败原因并冻结后续波次。

---

## 11. 完成判定

本轮判定完成需同时满足：

1. 3 个数据集全部纳入 V2 contract 且 lint 通过。
2. 3 个数据集均可执行最小窗口同步并通过对账。
3. 服务健康检查持续正常（`/api/health`、`/api/v1/health`）。
4. runbook 记录可回放、可回滚。
