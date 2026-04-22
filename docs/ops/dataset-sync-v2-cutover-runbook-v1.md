# 数据同步 V2 切换运行手册 v1（Runbook）

- 版本：v1.2
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

## 1.1 本轮前期准备锁定（2026-04-22）

本小节用于锁定“anchor_type 落地 + registry/cli 治理”这一轮的执行边界与回滚基线。

### A. 锁定范围

1. 本轮只做：`anchor_type` 契约落地 + `sync_v2/registry.py` 结构治理 + `src/cli.py` 薄入口治理。  
2. 本轮禁止：任何数据集切换、`USE_SYNC_V2_DATASETS` 扩面、远程同步批次推进。  

### B. 锁定基线（可回滚提交点）

1. 代码基线提交：`7a7fdbe63b96db640f7c5bdd6a89c51c29687eca`（短 SHA：`7a7fdbe`）。  
2. 失败回退时，代码回到该提交点再重启服务验证。  

### C. 锁定门禁（本轮必须通过）

本轮改动完成后，至少通过以下门禁：

1. `pytest -q tests/test_sync_v2_validator.py`
2. `pytest -q tests/test_sync_v2_planner.py`
3. `pytest -q tests/test_sync_v2_registry_routing.py`
4. `pytest -q tests/test_cli_sync_v2_commands.py`
5. `pytest -q tests/test_cli_sync_v2_param_filtering.py`
6. `pytest -q tests/test_cli_sync_daily.py`
7. `pytest -q tests/architecture/test_subsystem_dependency_matrix.py`
8. `python3 -m src.app.web.run --help`
9. `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts`

### D. 锁定开关（远程现值记录）

远程环境文件：`/etc/goldenshare/web.env`

1. `USE_SYNC_V2_DATASETS`（已配置）当前值：
   - `trade_cal,daily_basic,stk_limit,suspend_d,margin,moneyflow_ind_dc,cyq_perf,moneyflow_ths,moneyflow_dc,moneyflow_cnt_ths,moneyflow_ind_ths,moneyflow_mkt_dc,moneyflow,limit_step,limit_cpt_list,top_list,block_trade,stock_st,stk_nineturn,dc_member,daily,fund_daily,dc_index,index_daily_basic,index_daily,limit_list_d,limit_list_ths,adj_factor,fund_adj,index_basic,etf_basic,etf_index,hk_basic,us_basic,ths_index,kpl_list,kpl_concept_cons,broker_recommend`
2. `SYNC_V2_STRICT_CONTRACT`（未在远程 env 显式配置）：
   - 运行时生效值依赖代码默认值，当前为 `true`（见 [settings.py](/Users/congming/github/goldenshare/src/foundation/config/settings.py):50）。

### E. 锁定回滚（失败动作）

1. 代码回滚：
   - 回退到基线提交 `7a7fdbe`，重新发版并重启 `web/worker/scheduler`。  
2. 开关回滚：
   - 本轮不应改动 `USE_SYNC_V2_DATASETS`；若误改，恢复到本节 D 中记录值并重启三服务。  
   - 若误改 `SYNC_V2_STRICT_CONTRACT`，回退到“未显式配置（或显式 `true`）”并重启三服务。  
3. 回滚后校验：
   - `systemctl is-active` 三服务均 `active`
   - `/api/health` 与 `/api/v1/health` 返回 `ok`

---

## 2. 本轮可切数据集（已落地 V2 contract）

当前代码中已注册 V2 contract 的数据集（共 38 个）：

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
21. `daily`
22. `fund_daily`
23. `dc_index`
24. `index_daily_basic`
25. `index_daily`
26. `limit_list_d`
27. `limit_list_ths`
28. `adj_factor`
29. `fund_adj`
30. `index_basic`
31. `etf_basic`
32. `etf_index`
33. `hk_basic`
34. `us_basic`
35. `ths_index`
36. `kpl_list`
37. `kpl_concept_cons`
38. `broker_recommend`

说明：

1. `moneyflow`（主资金流，`raw -> std -> serving` 多源发布链）V2 contract 与 writer（`std + publish`）已在代码中落地并完成远程部署。  
2. `daily/fund_daily/dc_index/index_daily_basic/index_daily/limit_list_d/limit_list_ths/adj_factor` 已完成 R0+R1 扩展并通过门禁。  
3. 当前线上 `USE_SYNC_V2_DATASETS` 已与这 38 个 contract 覆盖口径对齐。  

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
13. `moneyflow`
14. `limit_step`
15. `limit_cpt_list`
16. `top_list`
17. `block_trade`
18. `stock_st`
19. `stk_nineturn`
20. `dc_member`
21. `daily`
22. `fund_daily`
23. `dc_index`
24. `index_daily_basic`
25. `index_daily`
26. `limit_list_d`
27. `limit_list_ths`
28. `adj_factor`
29. `fund_adj`
30. `index_basic`
31. `etf_basic`
32. `etf_index`
33. `hk_basic`
34. `us_basic`
35. `ths_index`
36. `kpl_list`
37. `kpl_concept_cons`
38. `broker_recommend`

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

## 6. 本轮执行状态（38 个数据集，已完成 38 个）

## 6.1 已完成批次（共 38 项）

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
21. 批次 21：`daily`
22. 批次 22：`fund_daily`
23. 批次 23：`dc_index`
24. 批次 24：`index_daily_basic`
25. 批次 25：`index_daily`
26. 批次 26：`limit_list_d`
27. 批次 27：`limit_list_ths`
28. 批次 28：`adj_factor`
29. 批次 29：`fund_adj`
30. 批次 30：`index_basic`
31. 批次 31：`etf_basic`
32. 批次 32：`etf_index`
33. 批次 33：`hk_basic`
34. 批次 34：`us_basic`
35. 批次 35：`ths_index`
36. 批次 36：`kpl_list`
37. 批次 37：`kpl_concept_cons`
38. 批次 38：`broker_recommend`

## 6.2 每批固定动作

1. 切换开关（只新增当前数据集）。
2. 跑一次增量 + 一次短区间历史（最近 3~7 个交易日）。
3. 执行 `reconcile-dataset` 门禁（阈值 0）。
4. 通过后再进入下一批。

## 6.3 当前已落地状态（2026-04-21）

1. 生产环境 `USE_SYNC_V2_DATASETS` 当前为：
   - `trade_cal,daily_basic,stk_limit,suspend_d,margin,moneyflow_ind_dc,cyq_perf,moneyflow_ths,moneyflow_dc,moneyflow_cnt_ths,moneyflow_ind_ths,moneyflow_mkt_dc,moneyflow,limit_step,limit_cpt_list,top_list,block_trade,stock_st,stk_nineturn,dc_member,daily,fund_daily,dc_index,index_daily_basic,index_daily,limit_list_d,limit_list_ths,adj_factor,fund_adj,index_basic,etf_basic,etf_index,hk_basic,us_basic,ths_index,kpl_list,kpl_concept_cons,broker_recommend`
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
17. Batch-3（R0+R1）与 Batch-4（R2）均已完成，当前 runbook 进入 Batch-5（R3）计划阶段。

---

## 8. 下一批（Batch-5）审计与编排（R3 可执行计划）

### 8.1 Batch-5 目标范围（V2 未覆盖资源）

截至当前，`sync` 资源总数为 56 个，V2 contract 已覆盖 38 个，尚未覆盖 18 个：

1. `biying_equity_daily`
2. `biying_moneyflow`
3. `dc_daily`
4. `dc_hot`
5. `dividend`
6. `index_monthly`
7. `index_weekly`
8. `index_weight`
9. `stk_factor_pro`
10. `stk_holdernumber`
11. `stk_period_bar_adj_month`
12. `stk_period_bar_adj_week`
13. `stk_period_bar_month`
14. `stk_period_bar_week`
15. `stock_basic`
16. `ths_daily`
17. `ths_hot`
18. `ths_member`

### 8.2 下一阶段执行节奏（R3 -> R4）

执行总原则：

1. 先补门禁能力，再切换数据集。
2. 每次只切 1 个数据集，不并行。
3. 任一门禁失败立即回切并冻结当前批次。

R3（扇出/周期语义）目标集：

1. `ths_daily`
2. `dc_daily`
3. `ths_member`
4. `ths_hot`
5. `dc_hot`
6. `index_weekly`
7. `index_monthly`
8. `stk_period_bar_week`
9. `stk_period_bar_month`
10. `stk_period_bar_adj_week`
11. `stk_period_bar_adj_month`

R4（高复杂专项）目标集：

1. `stock_basic`
2. `biying_equity_daily`
3. `biying_moneyflow`
4. `stk_factor_pro`
5. `index_weight`
6. `dividend`
7. `stk_holdernumber`

### 8.3 Batch-5（R3）固定任务包

R3-WP-01（门禁先行）：

1. 扩充 `reconcile-dataset` 到 R3 目标集。
2. 对板块/成分与周期栏资源补充“业务口径对账”（锚点日 + 主键去重 + 样本键差异），保证“切后可验”。

R3-WP-02（contract 落地）：

1. 为 R3 目标集补齐 V2 contract。
2. 通过 `sync-v2-lint-contracts`。

R3-WP-03（命令面回归）：

1. 在 `SYNC_V2_STRICT_CONTRACT=true` 下执行 `sync-history`/`sync-daily` 回归。
2. 禁止出现 `unknown_params`。

R3-WP-04（远程切换）：

1. 按 R3 列表顺序单数据集串行切换。
2. 每个数据集固定执行：
   - `sync-history`（3~7 交易日窗口）
   - `sync-daily`（最新交易日）
   - `reconcile-dataset --abs-diff-threshold 0`
### 8.4 R3 冻结与回滚规则（固定）

触发冻结（任一满足）：

1. 对账不通过（`abs_diff > 0`）。
2. 同步命令报结构化错误（contract/planner/writer）。
3. 服务状态异常或健康检查失败。

回滚动作：

1. 从 `USE_SYNC_V2_DATASETS` 移除当前数据集。
2. 重启 `web/worker/scheduler`。
3. 重新执行一次对应数据集同步，确认 V1 恢复。
4. 在执行记录模板中标记 `是否回滚=是`，并暂停后续波次。
### 8.5 R0+R1+R2 执行结果（2026-04-21）

1. R0 出口条件已全部满足：
   - `sync-v2-lint-contracts: passed`
   - `reconcile-dataset` 已覆盖 `daily/fund_daily/dc_index/index_daily_basic/index_daily/limit_list_d/limit_list_ths/adj_factor`
   - `SYNC_V2_STRICT_CONTRACT=true` 下命令面可正常执行
2. R1-A 已完成且门禁通过（`abs_diff=0`）：
   - `daily`
   - `fund_daily`
   - `dc_index`
   - `index_daily_basic`
3. R1-B 已完成且门禁通过（`abs_diff=0`）：
   - `index_daily`
   - `limit_list_d`
   - `limit_list_ths`
   - `adj_factor`
4. 当前生产 `USE_SYNC_V2_DATASETS` 已包含以上 8 个 R1 目标集，且 `web/worker/scheduler` 服务状态均为 `active`。
5. R2 已全部完成并通过门禁（`abs_diff=0`）：
   - `fund_adj`（daily 对账）
   - `index_basic`（snapshot 对账）
   - `etf_basic`（snapshot 对账）
   - `etf_index`（snapshot 对账）
   - `hk_basic`（snapshot 对账）
   - `us_basic`（snapshot 对账）
   - `ths_index`（snapshot 对账）
   - `kpl_list`（daily 对账）
   - `kpl_concept_cons`（daily 对账）
   - `broker_recommend`（snapshot 对账）
6. 线上已启用的 V2 数据集总数为 38，服务健康检查通过：
   - `/api/health -> ok`
   - `/api/v1/health -> ok`

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
