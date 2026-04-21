# 数据同步 V2 切换运行手册 v1（Runbook）

- 版本：v1.0
- 日期：2026-04-21
- 状态：可执行
- 适用环境：远程生产（`goldenshare-prod`）
- 关联设计：
  - [数据同步 V2 重设计方案（含平稳迁移）](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [Phase 4：迁移切换与兼容收口](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-4-cutover-migration.md)
  - [数据同步 V2 分期可执行编码任务包（执行版）](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-implementation-work-packages.md)

---

## 1. 目标与原则

本 Runbook 的目标是：在不影响现网稳定性的前提下，按数据集粒度将同步链路从 V1 平稳切到 V2。

执行原则：

1. 单次只切一个数据集（禁止一次切整批）。
2. 切换前必须做门禁检查（DB migration、contract lint）。
3. 切换后必须做对账（raw vs serving 行数与按日差异）。
4. 任一门禁失败，立即回切并停止扩面。

---

## 2. 本轮可切数据集（已落地 V2 contract）

当前代码中已注册 V2 contract 的数据集：

1. `trade_cal`
2. `daily_basic`
3. `cyq_perf`
4. `stk_limit`
5. `suspend_d`
6. `margin`
7. `moneyflow_ths`
8. `moneyflow_dc`
9. `moneyflow_cnt_ths`
10. `moneyflow_ind_ths`
11. `moneyflow_ind_dc`
12. `moneyflow_mkt_dc`
13. `moneyflow`
14. `limit_step`
15. `limit_cpt_list`
16. `top_list`
17. `block_trade`
18. `stock_st`
19. `stk_nineturn`
20. `dc_member`

说明：

1. `moneyflow`（主资金流，`raw -> std -> serving` 多源发布链）V2 contract 与 writer（`std + publish`）已在代码中落地并完成远程部署。  
2. 已按 runbook 完成 `sync-history + sync-daily + reconcile-dataset` 门禁对账（`abs_diff=0`）。  
3. `limit_step` / `limit_cpt_list` 已完成远程切换与门禁对账（`abs_diff=0`）。  

建议切换顺序（低风险到高风险）：

1. `trade_cal`
2. `daily_basic`
3. `cyq_perf`
4. `stk_limit`
5. `suspend_d`
6. `margin`
7. `moneyflow_ths`
8. `moneyflow_dc`
9. `moneyflow_cnt_ths`
10. `moneyflow_ind_ths`
11. `moneyflow_ind_dc`
12. `moneyflow_mkt_dc`
13. `limit_step`
14. `limit_cpt_list`
15. `top_list`
16. `block_trade`
17. `stock_st`
18. `stk_nineturn`
19. `dc_member`

---

## 3. 前置条件（每次切换前都要过）

## 3.1 远程环境信息

1. SSH：`goldenshare-prod`
2. 代码目录：`/opt/goldenshare/goldenshare`
3. 环境文件：`/etc/goldenshare/web.env`

## 3.2 前置门禁命令

在远程执行：

```bash
cd /opt/goldenshare/goldenshare
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare init-db
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare sync-v2-lint-contracts
```

通过标准：

1. `init-db` 无报错（Alembic 升级到 `head`）。
2. `sync-v2-lint-contracts: passed`。

---

## 4. 单数据集切换步骤（标准流程）

以下步骤中的 `<dataset_key>` 为本次要切的数据集。

## 4.1 审计当前开关值

```bash
grep -n '^USE_SYNC_V2_DATASETS=' /etc/goldenshare/web.env
```

## 4.2 更新环境开关

将 `<dataset_key>` 加入 `USE_SYNC_V2_DATASETS`（逗号分隔集合）。

示例（从空值切 `trade_cal`）：

```bash
sudo -n sed -i 's/^USE_SYNC_V2_DATASETS=.*/USE_SYNC_V2_DATASETS=trade_cal/' /etc/goldenshare/web.env
```

示例（已有值再追加）：

```bash
# 示例：原值 stk_limit,margin，追加 trade_cal
sudo -n sed -i 's/^USE_SYNC_V2_DATASETS=.*/USE_SYNC_V2_DATASETS=stk_limit,margin,trade_cal/' /etc/goldenshare/web.env
```

## 4.3 重启服务使配置生效

```bash
sudo -n systemctl restart goldenshare-ops-worker.service
sudo -n systemctl restart goldenshare-ops-scheduler.service
sudo -n systemctl restart goldenshare-web.service
```

## 4.4 运行一次同步（驱动切换链路）

增量（示例）：

```bash
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare sync-daily -r <dataset_key> --trade-date YYYY-MM-DD
```

历史（示例）：

```bash
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare sync-history -r <dataset_key> --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

当前执行口径（2026-04-21 更新）：

1. `sync-daily` / `sync-history` 在 V2 数据集下已按 contract 自动过滤无关参数，`SYNC_V2_STRICT_CONTRACT=true` 可直接使用。  
2. 切换验证建议：先跑 `sync-history`（可控时间窗口）再跑 `sync-daily`（增量），两者都做 `reconcile-dataset` 门禁。  
3. 若切换到较老版本（未包含上述过滤修复），请回退到“仅 `sync-history` 作为验证命令”的策略。  

## 4.5 对账门禁（必须）

```bash
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare reconcile-dataset \
  --dataset <dataset_key> \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  --sample-limit 30 \
  --abs-diff-threshold 0
```

通过标准：

1. 命令返回 0。
2. `abs_diff=0`。
3. 无异常 `daily_diff` 样本。

## 4.6 运行状态核验

```bash
systemctl is-active goldenshare-web.service
systemctl is-active goldenshare-ops-worker.service
systemctl is-active goldenshare-ops-scheduler.service
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/v1/health
```

---

## 5. 回滚步骤（秒级）

触发条件（任一满足即回滚）：

1. 对账不通过。
2. 同步任务异常率显著上升。
3. 运行服务不稳定。

回滚动作：

1. 从 `USE_SYNC_V2_DATASETS` 移除该 `dataset_key`。
2. 重启 worker/scheduler/web。
3. 重新执行一次对应数据集同步，确认 V1 路径恢复。
4. 记录异常并冻结下一批切换。

---

## 6. 本轮执行建议（20 个数据集，已完成 20 个）

## 6.1 批次计划

1. 批次 1：`trade_cal`
2. 批次 2：`daily_basic`
3. 批次 3：`cyq_perf`
4. 批次 4：`stk_limit`
5. 批次 5：`suspend_d`
6. 批次 6：`margin`
7. 批次 7：`moneyflow_ths`
8. 批次 8：`moneyflow_dc`
9. 批次 9：`moneyflow_cnt_ths`
10. 批次 10：`moneyflow_ind_ths`
11. 批次 11：`moneyflow_ind_dc`
12. 批次 12：`moneyflow_mkt_dc`
13. 批次 13：`moneyflow`
14. 批次 14：`limit_step`
15. 批次 15：`limit_cpt_list`
16. 批次 16：`top_list`
17. 批次 17：`block_trade`
18. 批次 18：`stock_st`
19. 批次 19：`stk_nineturn`
20. 批次 20：`dc_member`

## 6.2 每批固定动作

1. 切换开关（只新增当前数据集）。
2. 跑一次增量 + 一次短区间历史（最近 3~7 个交易日）。
3. 执行 `reconcile-dataset` 门禁（阈值 0）。
4. 通过后再进入下一批。

## 6.3 当前已落地状态（2026-04-21）

1. 生产环境 `USE_SYNC_V2_DATASETS` 当前为：
   - `trade_cal,daily_basic,stk_limit,suspend_d,margin,moneyflow_ind_dc,cyq_perf,moneyflow_ths,moneyflow_dc,moneyflow_cnt_ths,moneyflow_ind_ths,moneyflow_mkt_dc,moneyflow,limit_step,limit_cpt_list,top_list,block_trade,stock_st,stk_nineturn,dc_member`
2. `cyq_perf` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `abs_diff=0`
3. `moneyflow_ths` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `abs_diff=0`
4. `moneyflow_dc` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `abs_diff=0`
5. `moneyflow_cnt_ths` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `abs_diff=0`
6. `moneyflow_ind_ths` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `abs_diff=0`
7. `moneyflow_ind_dc` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `abs_diff=0`
8. `moneyflow_mkt_dc` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `abs_diff=0`
9. `moneyflow` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `abs_diff=0`
10. `limit_step` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `raw_rows=43`
   - `serving_rows=43`
   - `abs_diff=0`
11. `limit_cpt_list` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `raw_rows=60`
   - `serving_rows=60`
   - `abs_diff=0`
12. `top_list` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `raw_rows=213`
   - `serving_rows=213`
   - `abs_diff=0`
13. `block_trade` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `raw_rows=312`
   - `serving_rows=312`
   - `abs_diff=0`
14. `stock_st` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `raw_rows=538`
   - `serving_rows=538`
   - `abs_diff=0`
15. `stk_nineturn` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `raw_rows=16488`
   - `serving_rows=16488`
   - `abs_diff=0`
16. `dc_member` 已完成切换后门禁对账：
   - 窗口 `2026-04-15~2026-04-17`
   - `raw_rows=260215`
   - `serving_rows=260215`
   - `abs_diff=0`
17. Batch-2 已全部完成，当前 runbook 进入 Batch-3 准备阶段（先审计、后分批切换）。

---

## 8. 下一批（Batch-3）审计与编排（先审计、后分批切换）

### 8.1 Batch-3 目标范围（V2 未覆盖资源）

截至当前，`sync` 资源总数为 56 个，V2 contract 已覆盖 20 个，尚未覆盖 36 个：

1. `adj_factor`
2. `biying_equity_daily`
3. `biying_moneyflow`
4. `broker_recommend`
5. `daily`
6. `dc_daily`
7. `dc_hot`
8. `dc_index`
9. `dividend`
10. `etf_basic`
11. `etf_index`
12. `fund_adj`
13. `fund_daily`
14. `hk_basic`
15. `index_basic`
16. `index_daily`
17. `index_daily_basic`
18. `index_monthly`
19. `index_weekly`
20. `index_weight`
21. `kpl_concept_cons`
22. `kpl_list`
23. `limit_list_d`
24. `limit_list_ths`
25. `stk_factor_pro`
26. `stk_holdernumber`
27. `stk_period_bar_adj_month`
28. `stk_period_bar_adj_week`
29. `stk_period_bar_month`
30. `stk_period_bar_week`
31. `stock_basic`
32. `ths_daily`
33. `ths_hot`
34. `ths_index`
35. `ths_member`
36. `us_basic`

### 8.2 Batch-3-A（低歧义日频）建议候选

建议优先进入 Batch-3-A 的数据集：

1. `daily`
2. `index_daily`
3. `fund_daily`
4. `ths_daily`
5. `dc_daily`
6. `dc_index`

选择原则：

1. 交易日锚点清晰（`trade_date`）。
2. 写入路径可沿用 `raw_core_upsert` 模式。
3. 对账口径易建立（按 `trade_date` 做 `raw vs serving`）。

### 8.3 Batch-3 执行门禁（固定）

1. 每次只切 1 个数据集，不并行。
2. 先实现 contract + reconcile 支持，再切生产开关。
3. 切换后固定执行：
   - `sync-history`（近 3~7 个交易日）
   - `sync-daily`（最新交易日）
   - `reconcile-dataset --abs-diff-threshold 0`
4. 任一门禁失败，立即回切并冻结扩面。

---

## 7. 执行记录模板（每批必填）

```text
批次：
dataset_key：
切换前 USE_SYNC_V2_DATASETS：
切换后 USE_SYNC_V2_DATASETS：
增量同步命令：
历史同步命令：
对账窗口：
对账结果（abs_diff）：
服务状态：
是否回滚：
备注：
```
