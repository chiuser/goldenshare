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
3. `stk_limit`
4. `margin`
5. `moneyflow_ind_dc`

建议切换顺序（低风险到高风险）：

1. `trade_cal`
2. `daily_basic`
3. `stk_limit`
4. `margin`
5. `moneyflow_ind_dc`

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
source /etc/goldenshare/web.env
goldenshare init-db
goldenshare sync-v2-lint-contracts
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
source /etc/goldenshare/web.env
goldenshare sync-daily -r <dataset_key> --trade-date YYYY-MM-DD
```

历史（示例）：

```bash
source /etc/goldenshare/web.env
goldenshare sync-history -r <dataset_key> --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

当前执行口径（2026-04-21 更新）：

1. `sync-daily` / `sync-history` 在 V2 数据集下已按 contract 自动过滤无关参数，`SYNC_V2_STRICT_CONTRACT=true` 可直接使用。  
2. 切换验证建议：先跑 `sync-history`（可控时间窗口）再跑 `sync-daily`（增量），两者都做 `reconcile-dataset` 门禁。  
3. 若切换到较老版本（未包含上述过滤修复），请回退到“仅 `sync-history` 作为验证命令”的策略。  

## 4.5 对账门禁（必须）

```bash
source /etc/goldenshare/web.env
goldenshare reconcile-dataset \
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

## 6. 本轮执行建议（5 个数据集）

## 6.1 批次计划

1. 批次 1：`trade_cal`
2. 批次 2：`daily_basic`
3. 批次 3：`stk_limit`
4. 批次 4：`margin`
5. 批次 5：`moneyflow_ind_dc`

## 6.2 每批固定动作

1. 切换开关（只新增当前数据集）。
2. 跑一次增量 + 一次短区间历史（最近 3~7 个交易日）。
3. 执行 `reconcile-dataset` 门禁（阈值 0）。
4. 通过后再进入下一批。

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
