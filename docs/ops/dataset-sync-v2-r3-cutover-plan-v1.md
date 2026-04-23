# 数据同步 V2 R3 切换方案 v1（板块/热榜/周期栏）

- 版本：v1.0
- 日期：2026-04-22
- 状态：已执行（归档）
- 适用环境：远程生产（`goldenshare-prod`）
- 前置依赖：
  - [数据同步 V2 切换运行手册 v1](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-cutover-runbook-v1.md)
  - [数据同步 V2 重设计方案（含平稳迁移）](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [Tushare 全量数据集参数审计 v1](/Users/congming/github/goldenshare/docs/ops/tushare-full-dataset-parameter-audit-v1.md)

---

## 1. 目标与决策基线（历史）

本方案用于准备并执行 Batch-5（R3）切换，严格按“先门禁、后切换，单数据集串行”的原则执行。

本轮已确认决策：

1. `index_weekly`、`index_monthly` 不进入 R3，改入 R4 专项。
2. R3 只覆盖 9 个数据集，优先完成板块/热榜/周期栏的 contract 化与可回滚切换。

该决策依据（代码事实）：

1. `index_weekly/index_monthly` 现有链路包含“API 拉取 + 日线派生补缺（`derived_daily`）+ period_start 去重写入”复合写入策略，见：
   - [index_series.py](/Users/congming/github/goldenshare/src/foundation/services/sync_v2/registry_parts/contracts/index_series.py)
2. 当前 V2 writer 仅有通用 `raw_core_upsert`、资金流专项 `raw_std_publish_moneyflow`、快照 `raw_core_snapshot_insert_by_trade_date` 三种路径，尚无“指数周月派生补缺”专用 write_path，见：
   - [writer.py](/Users/congming/github/goldenshare/src/foundation/services/sync_v2/writer.py)

---

## 2. R3 范围（9 个，已全部纳入 V2 contract）

## 2.1 在范围内

1. `ths_member`
2. `ths_daily`
3. `dc_daily`
4. `ths_hot`
5. `dc_hot`
6. `stk_period_bar_week`
7. `stk_period_bar_adj_week`
8. `stk_period_bar_month`
9. `stk_period_bar_adj_month`

## 2.2 不在范围内（明确后置）

1. `index_weekly`（移入 R4）
2. `index_monthly`（移入 R4）

---

## 3. R3 技术任务包

## 3.1 R3-WP-01：对账门禁先行

目标：让上述 9 个数据集具备“切后可验”能力。

实现要求：

1. 扩充 `reconcile-dataset` 的 `SUPPORTED_DATASETS` 至 9 个目标集。
2. 按数据集类型定义对账口径：
   - `ths_member`：`snapshot` 口径（`ts_code + con_code`）。
   - `ths_daily`、`dc_daily`、`ths_hot`、`dc_hot`：`daily` 口径（按 `trade_date`）。
   - `stk_period_bar_*`、`stk_period_bar_adj_*`：`daily` 口径（按 `trade_date`，主键包含 `freq`）。
3. 输出至少包含：
   - 总行数差异
   - 日级差异（适用于 daily）
   - 主键样本差异（适用于 snapshot）

门禁命令（按资源逐个执行）：

```bash
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare reconcile-dataset \
  --dataset <dataset_key> \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  --sample-limit 30 \
  --abs-diff-threshold 0
```

## 3.2 R3-WP-02：V2 contract 落地（9 个）

目标：补齐 V2 contract 并通过 lint。

契约建议（按当前实现语义）：

1. `ths_member`
   - `anchor_type=none`
   - `window_policy=none`
   - `universe_policy=ths_index_board_codes`
2. `ths_daily` / `dc_daily`
   - `anchor_type=trade_date`
   - `window_policy=point_or_range`
   - `universe_policy=<board_pool>`（基于板块池扇开）
3. `ths_hot` / `dc_hot`
   - `anchor_type=trade_date`
   - `window_policy=point_or_range`
   - 含枚举扇开（`market/hot_type/is_new`）
4. `stk_period_bar_week` / `stk_period_bar_adj_week`
   - `anchor_type=week_end_trade_date`
   - `window_policy=point_or_range`
5. `stk_period_bar_month` / `stk_period_bar_adj_month`
   - `anchor_type=month_end_trade_date`
   - `window_policy=point_or_range`

门禁命令：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts
```

## 3.3 R3-WP-03：命令面与严格契约回归

目标：确保 `SYNC_V2_STRICT_CONTRACT=true` 下 CLI 无未知参数报错。

固定回归：

1. `sync-history`：每个数据集 3~7 个交易日窗口。
2. `sync-daily`：最新交易日单点。
3. 不允许出现：
   - `unknown_params`
   - `missing_anchor_fields`
   - `invalid_window_for_profile`

## 3.4 R3-WP-04：远程串行切换

执行顺序（建议）：

1. `ths_member`
2. `ths_daily`
3. `dc_daily`
4. `ths_hot`
5. `dc_hot`
6. `stk_period_bar_week`
7. `stk_period_bar_adj_week`
8. `stk_period_bar_month`
9. `stk_period_bar_adj_month`

每个数据集固定动作：

1. 加入 `USE_SYNC_V2_DATASETS`
2. 重启 `web/worker/scheduler`
3. `sync-history`（3~7 日）
4. `sync-daily`（最新交易日）
5. `reconcile-dataset --abs-diff-threshold 0`
6. 通过后再进入下一个

---

## 4. 冻结与回滚

冻结条件（任一触发即停）：

1. 对账不通过（`abs_diff > 0`）
2. 服务健康检查失败（`/api/health` 或 `/api/v1/health` 非 `ok`）
3. 同步命令出现结构化错误，且重试后仍失败

回滚步骤：

1. 从 `USE_SYNC_V2_DATASETS` 移除当前 `dataset_key`
2. 重启三服务
3. 复跑当前数据集一次（确认 V1 可用）
4. 记录并冻结 R3 后续波次

---

## 5. R3 完成判定

同时满足以下条件，R3 判定完成：

1. 9 个目标集全部纳入 V2 contract 并 lint 通过。
2. 9 个目标集全部完成“切换 + 对账 = 0 差异”。
3. 三服务稳定运行，健康检查持续 `ok`。
4. runbook 执行记录完整，可回放。

执行结果（代码口径）：

1. 上述 9 个数据集已全部进入 `SYNC_V2_CONTRACTS`。
2. R3 切换后，当前未迁移集已收敛到 9 个（转入 R4）。
3. 当前全局覆盖从 `38/56` 提升到 `47/56`。

---

## 6. R4 预告（专项）

R4 将承接：

1. `index_weekly` / `index_monthly`（指数周月“API + derived_daily”复合写入专项）
2. 其他高复杂项（`stock_basic`、`biying_*`、`index_weight`、`stk_factor_pro`、`dividend`、`stk_holdernumber`）

R4 启动前置：

1. 明确 `index_weekly/index_monthly` 的 V2 专用 write_path 设计（含派生补缺语义）。
2. 补齐相应对账口径（API 行 + derived 行可观测）。
