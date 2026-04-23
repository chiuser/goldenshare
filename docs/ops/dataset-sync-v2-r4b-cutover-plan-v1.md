# 数据同步 V2 R4-B 切换方案 v1（`index_weekly` / `index_monthly`）

> 状态：历史执行记录（归档）。  
> 说明：本文用于追溯 R4-B 批次切换过程，不作为当前运行手册。

- 版本：v1.0
- 日期：2026-04-23
- 状态：已完成（远程切换与对账通过）
- 范围：仅 Tushare，且仅 2 个数据集（`index_weekly` / `index_monthly`）
- 关联文档：
  - [数据同步 V2 切换运行手册 v1](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-cutover-runbook-v1.md)
  - [数据同步 V2 重设计方案（含平稳迁移）](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [Tushare 全量数据集请求执行口径 v1（仅 Tushare）](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)

---

## 1. 本轮目标

本轮只做 1 件事：为 `index_weekly` 与 `index_monthly` 制定可执行的 V2 contract 化与切换方案，确保切换后行为与当前生产语义保持一致。

本轮不做：

1. 不处理 `stock_basic` / `stk_factor_pro` / `biying_equity_daily` / `biying_moneyflow`。
2. 不改上层 biz API 契约。
3. 不并行切换其他数据集。

## 1.1 执行结果（2026-04-23）

远程 `goldenshare-prod` 已按批次顺序完成：

1. `index_weekly`：
   - `sync-history --start-date 2026-04-17 --end-date 2026-04-17` -> `fetched=1986 written=560`
   - `sync-daily --trade-date 2026-04-17` -> `fetched=1986 written=1130`
   - `reconcile-dataset --dataset index_weekly --start-date 2026-04-17 --end-date 2026-04-17 --abs-diff-threshold 0` -> `abs_diff=0`
2. `index_monthly`：
   - `sync-history --start-date 2026-03-31 --end-date 2026-03-31` -> `fetched=13983 written=560`
   - `sync-daily --trade-date 2026-03-31` -> `fetched=13983 written=1130`
   - `reconcile-dataset --dataset index_monthly --start-date 2026-03-31 --end-date 2026-03-31 --abs-diff-threshold 0` -> `abs_diff=0`

执行后（历史），`USE_SYNC_V2_DATASETS` 已包含 `index_weekly,index_monthly`。

---

## 2. 代码现状审计（作为方案基线）

### 2.1 当前未迁移事实

`index_weekly` / `index_monthly` 仍未进入 `SYNC_V2_CONTRACTS`，当前走 V1 服务实现：

1. `src/foundation/services/sync/sync_index_weekly_service.py`
2. `src/foundation/services/sync/sync_index_monthly_service.py`

### 2.2 V1 当前关键语义（本轮必须保留）

1. **指数池来源**：优先用 `ops.index_series_active(resource='index_daily')`，为空时回退 `index_basic` 激活列表。
2. **分页闭环**：`limit=1000`，`offset` 递增直到返回 `< limit`。
3. **过滤策略**：如果未指定 `ts_code`，按指数池逐代码请求并写入。
4. **缺失补齐**：在 `point_incremental` 且未指定 `ts_code` 时，对 API 未返回的活跃指数，基于 `core_serving.index_daily_serving` 聚合补一条 `source='derived_daily'` 周/月记录。
5. **服务层写入字段要求**：`core_serving.index_weekly_serving` / `core_serving.index_monthly_serving` 需要 `period_start_date`。

上述 5 点是本轮设计的强约束，不能在迁移时丢失。

---

## 3. 源文档口径（本轮请求契约依据）

来源：

1. `docs/sources/tushare/指数专题/0171_指数周线行情.md`
2. `docs/sources/tushare/指数专题/0172_指数月线行情.md`

统一口径：

1. 输入参数均支持：`ts_code, trade_date, start_date, end_date, limit, offset`
2. 单次上限：`1000`
3. 时间锚点：
   - `index_weekly`：`week_end_trade_date`
   - `index_monthly`：`month_end_trade_date`

---

## 4. R4-B 目标契约设计

## 4.1 `index_weekly`

1. `run_profiles_supported`：`("point_incremental", "range_rebuild")`
2. `anchor_type`：`week_end_trade_date`
3. `window_policy`：`point_or_range`
4. `pagination_policy`：`offset_limit`
5. `page_limit`：`1000`
6. `source_spec`：
   - `api_name="index_weekly"`
   - `unit_params_builder` 仅透传文档参数（`ts_code/trade_date/start_date/end_date`）
7. `normalization_spec`：
   - `date_fields=("trade_date",)`
   - `decimal_fields=("open","high","low","close","pre_close","change","pct_chg","vol","amount")`
   - `required_fields=("ts_code","trade_date")`
   - `row_transform` 增加 `change_amount=change`
8. `write_spec`：
   - `raw_dao_name="raw_index_weekly_bar"`
   - `core_dao_name="index_weekly_serving"`
   - `target_table="core_serving.index_weekly_serving"`
   - `write_path="raw_index_period_serving_upsert"`（新增，见第 5 节）

## 4.2 `index_monthly`

1. `run_profiles_supported`：`("point_incremental", "range_rebuild")`
2. `anchor_type`：`month_end_trade_date`
3. `window_policy`：`point_or_range`
4. `pagination_policy`：`offset_limit`
5. `page_limit`：`1000`
6. `source_spec`：
   - `api_name="index_monthly"`
   - `unit_params_builder` 仅透传文档参数（`ts_code/trade_date/start_date/end_date`）
7. `normalization_spec`：
   - 与 `index_weekly` 相同
8. `write_spec`：
   - `raw_dao_name="raw_index_monthly_bar"`
   - `core_dao_name="index_monthly_serving"`
   - `target_table="core_serving.index_monthly_serving"`
   - `write_path="raw_index_period_serving_upsert"`（新增，见第 5 节）

---

## 5. V2 引擎最小扩展（为保留 V1 语义）

为避免行为回退，本轮需要在 writer 层新增一个最小专用写路径：

`write_path = "raw_index_period_serving_upsert"`

能力边界：

1. 原始层：`raw_*` 常规 upsert。
2. 服务层：写入前计算 `period_start_date`（按周/月自然周期窗口内的首个开市日）。
3. 去重与覆盖：按 `(ts_code, period_start_date)` 作为周期唯一键覆盖。
4. 保留补齐：在 `point_incremental + 未指定 ts_code` 时，执行缺失指数的 `derived_daily` 补齐。
5. 不改变外部模型字段，不改表结构，不动 serving 构建器语义。

说明：

1. 不把 `period_start_date` 退化成“自然周一/自然月1日”写死值。
2. 不删除 `derived_daily` 逻辑，先以行为一致优先。

---

## 6. 数据集策略函数落位

新增两个策略函数文件：

1. `src/foundation/services/sync_v2/dataset_strategies/index_weekly.py`
2. `src/foundation/services/sync_v2/dataset_strategies/index_monthly.py`

统一策略：

1. `ts_code` 显式传入时按显式代码执行。
2. 未传 `ts_code` 时，按 `index_daily` 活跃池扇开（为空则回退 `index_basic`）。
3. `range_rebuild` 使用锚点压缩后的交易日序列：
   - 周线：每周最后交易日
   - 月线：每月最后交易日
4. 每个 `anchor × ts_code` 生成一个计划单元；分页由 engine 统一闭环。

---

## 7. 对账与门禁

## 7.1 对账补齐

在 `operations_dataset_reconcile_service` 增加：

1. `index_weekly`（`raw_tushare.index_weekly_bar` vs `core_serving.index_weekly_serving`）
2. `index_monthly`（`raw_tushare.index_monthly_bar` vs `core_serving.index_monthly_serving`）

默认口径：

1. 时间字段：`trade_date -> trade_date`
2. 对账窗口：按小范围交易日窗（切换阶段先小窗）

## 7.2 本轮门禁

每次实现后必须通过：

1. `tests/architecture/test_sync_v2_registry_guardrails.py`
2. `tests/test_sync_v2_validator.py`
3. `tests/test_sync_v2_planner.py`
4. `tests/test_sync_v2_linter.py`
5. `tests/test_sync_v2_registry_routing.py`
6. `tests/test_dataset_reconcile_service.py`
7. 本轮新增策略函数测试（`index_weekly/index_monthly`）
8. `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts`

---

## 8. 切换步骤（R4-B 执行顺序）

固定顺序：

1. `index_weekly`
2. `index_monthly`

每个数据集固定流程：

1. （历史执行）更新 `USE_SYNC_V2_DATASETS`（只加当前数据集）
2. 重启 `web/worker/scheduler`
3. 执行小窗口 `sync-history`（优先指定单 `ts_code` 缩短验证时间）
4. 执行单日 `sync-daily --trade-date`
5. 执行 `reconcile-dataset`（同窗口，`abs_diff=0`）
6. 通过后才进入下一数据集

---

## 9. 回滚方案（单数据集粒度）

任一门禁失败即回滚：

1. （历史执行）从 `USE_SYNC_V2_DATASETS` 移除当前数据集。
2. 重启三服务。
3. 复跑一次该数据集同步，确认 V1 路径恢复。
4. 记录失败原因并冻结 R4-B。

---

## 10. R4-B 完成后的剩余项

R4-B 完成后，Runbook 未迁移项预期收敛为 4 个：

1. `stock_basic`
2. `stk_factor_pro`
3. `biying_equity_daily`
4. `biying_moneyflow`

后续进入 R4-C（高复杂专项）时再单独出方案。
