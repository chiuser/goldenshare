# 数据同步 V2 切换运行手册 v1（Runbook）

- 版本：v1.5
- 日期：2026-04-23
- 状态：执行中（R0+R1+R2+R3+R4 全部完成，进入稳定化阶段）
- 适用环境：远程生产（`goldenshare-prod`）
- 关联设计：
  - [数据同步 V2 重设计方案（含平稳迁移）](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [Phase 4：迁移切换与兼容收口](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-4-cutover-migration.md)
  - [数据同步 V2 分期可执行编码任务包（执行版）](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-implementation-work-packages.md)
  - [数据同步 V2 R3 切换方案 v1](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-r3-cutover-plan-v1.md)

---

## 1. 目标与原则

本 Runbook 的目标是：在不影响现网稳定性的前提下，按数据集粒度稳定运行并持续校验 V2 同步链路。

执行原则：

1. 单次只切一个数据集（禁止一次切整批）。
2. 切换前必须做门禁检查（`init-db`、`sync-v2-lint-contracts`）。
3. 切换后必须做对账（`reconcile-dataset`）。
4. 任一门禁失败，立即回切并冻结当前批次。

---

## 2. 当前实现快照（以代码为准）

当前注册规模（代码事实）：

1. `SYNC_SERVICE_REGISTRY` 总资源：`56`
2. `SYNC_V2_CONTRACTS` 已覆盖：`56`
3. 未迁移（仍走 V1）：`0`

当前 V2 contract 覆盖的 56 个数据集：

1. `adj_factor`
2. `block_trade`
3. `broker_recommend`
4. `cyq_perf`
5. `daily`
6. `daily_basic`
7. `dc_daily`
8. `dc_hot`
9. `dc_index`
10. `dc_member`
11. `etf_basic`
12. `etf_index`
13. `fund_adj`
14. `fund_daily`
15. `hk_basic`
16. `index_basic`
17. `index_daily`
18. `index_daily_basic`
19. `kpl_concept_cons`
20. `kpl_list`
21. `limit_cpt_list`
22. `limit_list_d`
23. `limit_list_ths`
24. `limit_step`
25. `margin`
26. `moneyflow`
27. `moneyflow_cnt_ths`
28. `moneyflow_dc`
29. `moneyflow_ind_dc`
30. `moneyflow_ind_ths`
31. `moneyflow_mkt_dc`
32. `moneyflow_ths`
33. `stk_limit`
34. `stk_nineturn`
35. `stk_period_bar_adj_month`
36. `stk_period_bar_adj_week`
37. `stk_period_bar_month`
38. `stk_period_bar_week`
39. `stock_st`
40. `suspend_d`
41. `ths_daily`
42. `ths_hot`
43. `ths_index`
44. `ths_member`
45. `top_list`
46. `trade_cal`
47. `us_basic`
48. `dividend`
49. `stk_holdernumber`
50. `index_weight`
51. `biying_equity_daily`
52. `biying_moneyflow`
53. `stk_factor_pro`
54. `stock_basic`
55. `index_monthly`
56. `index_weekly`

说明：

1. `R3` 目标集（`ths_* / dc_* / stk_period_bar_*`）已纳入 V2 contract。
2. 当前运行链路为 V2-only（不再依赖 `USE_SYNC_V2_DATASETS` 路由开关）。

---

## 3. 前置门禁（每次切换前都要过）

远程环境信息：

1. SSH：`goldenshare-prod`
2. 代码目录：`/opt/goldenshare/goldenshare`
3. 环境文件：`/etc/goldenshare/web.env`

前置门禁命令：

```bash
cd /opt/goldenshare/goldenshare
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare init-db
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare sync-v2-lint-contracts
```

通过标准：

1. `init-db` 无报错（Alembic 升级到 `head`）。
2. `sync-v2-lint-contracts: passed`。

---

## 4. 单数据集验证步骤（标准流程）

以下步骤中的 `<dataset_key>` 为本次要切的数据集。

### 4.1 重启服务（确保使用当前部署代码）

```bash
sudo -n systemctl restart goldenshare-ops-worker.service
sudo -n systemctl restart goldenshare-ops-scheduler.service
sudo -n systemctl restart goldenshare-web.service
```

### 4.2 运行验证命令

按数据集入口语义执行：

1. 快照类（`stock_basic/hk_basic/us_basic/index_basic/etf_basic/ths_index/ths_member`）：

```bash
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare sync-snapshot -r <dataset_key>
```

2. 交易日增量类：

```bash
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare sync-daily -r <dataset_key> --trade-date YYYY-MM-DD
```

3. 区间回补类：

```bash
GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env .venv/bin/goldenshare sync-history -r <dataset_key> --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

### 4.3 对账门禁（必须）

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
3. 无异常样本差异。

### 4.4 运行状态核验

```bash
systemctl is-active goldenshare-web.service
systemctl is-active goldenshare-ops-worker.service
systemctl is-active goldenshare-ops-scheduler.service
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/v1/health
```

---

## 5. 回滚步骤（代码级）

触发条件（任一满足即回滚）：

1. 对账不通过。
2. 同步任务异常率显著上升。
3. 运行服务不稳定。

回滚动作：

1. 回退到上一稳定提交（`git revert` 或切换到已验证 tag/commit）。
2. 重新执行发版并重启 `web/worker/scheduler`。
3. 重新执行一次该数据集同步与对账，确认恢复。
4. 记录异常并冻结下一批。

---

## 6. 历史执行快照（归档）

以下信息是 `2026-04-21` 的历史执行快照，保留用于追溯，不作为当前代码规模依据：

1. R0+R1+R2 阶段曾按 38 个数据集批次执行并通过门禁。
2. 当时尚未纳入 V2 的 R3 目标（`ths_* / dc_* / stk_period_bar_*`）已在后续代码中补齐 contract。

历史批次中涉及 `USE_SYNC_V2_DATASETS` 的描述仅用于追溯；当前已不再使用该开关。

---

## 7. 当前下一步计划（稳定化）

当前迁移主线已完成，后续聚焦稳定化：

1. 持续巡检 `SYNC_V2_CONTRACTS` 与运行结果是否漂移。
2. 按数据集入口语义（`sync-snapshot/sync-daily/sync-history`）固化门禁。
3. 新增数据集默认走 V2 contract 开发与切换，不再新增 V1 旁路。

---

## 8. 执行记录模板（每批必填）

```text
批次：
dataset_key：
增量同步命令：
历史同步命令：
对账窗口：
对账结果（abs_diff）：
服务状态：
是否回滚：
备注：
```
