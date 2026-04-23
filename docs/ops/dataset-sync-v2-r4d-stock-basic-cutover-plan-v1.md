# 数据同步 V2 R4-D 切换方案 v1（`stock_basic`）

- 版本：v1.0
- 日期：2026-04-23
- 状态：评审通过，进入执行
- 范围：仅 `stock_basic`（最后一个未切 V2 的数据集）
- 关联文档：
  - [数据同步 V2 切换运行手册 v1](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-cutover-runbook-v1.md)
  - [Sync V2 数据集策略简化方案 v1](/Users/congming/github/goldenshare/docs/architecture/sync-v2-dataset-strategy-simplification-plan-v1.md)
  - [Tushare 全量数据集请求执行口径 v1](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)

---

## 1. 背景与目标

当前 `USE_SYNC_V2_DATASETS` 已覆盖除 `stock_basic` 外的全部数据集，`stock_basic` 仍走 V1 `SyncStockBasicService`。

本轮目标：

1. 先新增 `sync-snapshot` 命令，作为“无时间锚点/快照类”数据集专用入口。
2. 以 `sync-snapshot` 完成 `stock_basic` 的 V2 切换。
3. `stock_basic` 稳定后，将 `hk_basic/us_basic/index_basic/etf_basic/ths_index/ths_member` 迁移到 `sync-snapshot` 入口。
4. `dividend/stk_holdernumber` 本轮不调整（暂时保留现状）。
5. 保持现有业务语义不变（尤其 `source_key=tushare|biying|all` 行为）。
6. 切换后可通过现有门禁对账与快速回滚。

本轮不做：

1. 不调整 `stock_basic` 的业务字段口径。
2. 不调整多源融合策略（`ResolutionPolicy`）语义。
3. 不改上层 biz API。

---

## 1.1 执行顺序（已拍板）

1. `sync-snapshot` 命令落地（不夹带数据集迁移）。
2. `stock_basic` contract + strategy + writer/worker 最小改造。
3. 远程切换 `stock_basic` 到 V2（入口使用 `sync-snapshot`）。
4. 将 `hk_basic/us_basic/index_basic/etf_basic/ths_index/ths_member` 从“`sync-history` 主入口”迁移到“`sync-snapshot` 主入口”。
5. 最后收口 `sync-daily` 的资源语义（快照类不再作为 daily 入口目标）。

---

## 2. 现状审计（代码事实）

### 2.1 V1 `stock_basic` 当前行为

文件：`src/foundation/services/sync/sync_stock_basic_service.py`

1. `source_key=tushare`：
   - 拉 Tushare `stock_basic(list_status=L,D,P,G)`。
   - 写 `raw_tushare.stock_basic`。
   - 标准化后写 `core_multi.security_std`（`source_key=tushare`）。
   - 直接 upsert `core_serving.security_serving`。
2. `source_key=biying`：
   - 拉 Biying `stock_basic`。
   - 写 `raw_biying.stock_basic`。
   - 标准化后写 `core_multi.security_std`（`source_key=biying`）。
   - 仅补入 serving 里不存在的 `ts_code`。
3. `source_key=all`：
   - 顺序执行 tushare + biying。
   - 两源 std 写完后按 `ServingPublishService.publish_dataset(dataset_key="stock_basic")` 发布。

### 2.2 V2 迁移阻塞点（必须先解）

当前 `SyncV2WorkerClient` 取 adapter 使用 `contract.source_adapter_key`，未使用 `PlanUnit.source_key`。  
这会导致 `stock_basic` 无法在一次执行中同时跑 tushare+biying（`source_key=all`）。

---

## 3. 目标设计

## 3.1 Contract（新增）

位置：`src/foundation/services/sync_v2/registry_parts/contracts/reference_master.py`

新增 `stock_basic` contract，核心约束：

1. `dataset_key="stock_basic"`
2. `source_adapter_key="tushare"`（默认源）
3. `run_profiles_supported=("snapshot_refresh",)`
4. 输入参数：
   - `source_key`（enum：`tushare|biying|all`）
   - `ts_code,name,market,list_status,exchange,is_hs`（可选）
5. `write_path`：新增 `raw_std_publish_stock_basic`
6. `target_table="core_serving.security_serving"`

说明：

1. 仍以 `snapshot_refresh` 为主语义（与 `sync_history.stock_basic` 一致）。
2. 不再为 `stock_basic` 保留 `sync-daily` 时间锚点兼容；快照类统一使用 `sync-snapshot`。

## 3.2 Strategy（新增）

位置：`src/foundation/services/sync_v2/dataset_strategies/stock_basic.py`

策略规则：

1. `source_key=tushare`：产出 1 个 unit（source=tushare）。
2. `source_key=biying`：产出 1 个 unit（source=biying）。
3. `source_key=all`：产出 2 个 unit（先 tushare，后 biying）。

请求参数规则：

1. tushare：
   - 默认 `list_status=L,D,P,G`
   - `limit=6000` 分页，`offset` 递增
   - 可选筛选参数按文档透传：`ts_code,name,market,list_status,exchange,is_hs`
   - 多值枚举（`market/list_status/exchange/is_hs`）支持组合扇出，且“全选值折叠为不传”
2. biying：
   - API 无过滤参数，固定快照拉取 + 分页闭环（若返回支持）。

## 3.3 Worker 适配器选择（最小扩展）

位置：`src/foundation/services/sync_v2/worker_client.py`

规则改为：

1. 若 `unit.source_key` 对应已注册 adapter（`tushare`/`biying`），优先用 `unit.source_key`。
2. 否则回退到 `contract.source_adapter_key`。

影响面：

1. 对现有已迁移数据集行为不变（默认 `unit.source_key` 与 `contract.source_adapter_key` 同值）。
2. 为 `stock_basic source_key=all` 提供必要能力。

## 3.4 Writer 写入路径（新增）

位置：`src/foundation/services/sync_v2/writer.py`

新增 `write_path="raw_std_publish_stock_basic"`，行为按 V1 对齐：

1. raw 写入：
   - 按 `unit.source_key` 路由到 `raw_tushare.stock_basic` 或 `raw_biying.stock_basic`。
2. std 写入：
   - 使用 `NormalizeSecurityService.to_std(..., source_key=unit.source_key)` 后 upsert 到 `core_multi.security_std`。
3. serving 发布：
   - `source_key=tushare`：直接用 tushare 标准行 upsert serving（与 V1 一致）。
   - `source_key=biying`：仅补 serving 中缺失代码（与 V1 一致）。
   - `source_key=all`：按“本次触达 `ts_code`”从 `security_std` 读取两源候选，调用 `ServingPublishService.publish_dataset("stock_basic")` 做策略发布。

---

## 4. 测试门禁

本轮必须通过：

1. `tests/test_sync_v2_validator.py`
2. `tests/test_sync_v2_worker_client.py`（补 unit.source_key 选 adapter 用例）
3. `tests/test_sync_v2_linter.py`（新增 write_path 白名单校验）
4. `tests/architecture/test_sync_v2_registry_guardrails.py`（补 `stock_basic` 所属域矩阵）
5. 新增：
   - `tests/test_sync_v2_dataset_strategies_stock_basic.py`
   - `tests/test_sync_v2_writer_stock_basic.py`
6. `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts`

切换前后运行门禁：

1. `sync-snapshot -r stock_basic --source-key all`（小窗口冒烟）
2. `reconcile-stock-basic`（阈值门禁）

---

## 5. 切换步骤（远程）

1. 前置检查
   - `goldenshare init-db`
   - `goldenshare sync-v2-lint-contracts`
2. 切换开关
   - 将 `stock_basic` 加入 `USE_SYNC_V2_DATASETS`
   - 重启 `web/worker/scheduler`
3. 切换验证
   - `goldenshare sync-snapshot -r stock_basic --source-key all`
   - `goldenshare reconcile-stock-basic --sample-limit 20 ...`
4. 服务健康
   - `systemctl is-active` 三服务
   - `/api/health` 与 `/api/v1/health`

---

## 6. 回滚方案

若门禁失败，立即回滚：

1. 从 `USE_SYNC_V2_DATASETS` 移除 `stock_basic`
2. 重启 `web/worker/scheduler`
3. 重跑 `sync-snapshot -r stock_basic --source-key all` 验证 V1 恢复

---

## 7. 风险与控制

1. 风险：`unit.source_key` 选 adapter 的改动影响全局 worker。
   - 控制：仅在 source_key 命中已注册 adapter 时生效；否则回退旧逻辑。
2. 风险：`source_key=all` 发布时两源候选不全导致策略偏差。
   - 控制：all 模式发布前从 `security_std` 回读触达代码的双源候选，再发布。
3. 风险：切换后仍使用 `sync-daily -r stock_basic` 会报 run_profile 不支持。
   - 控制：文档与 runbook 统一为 `sync-snapshot` 入口；CLI 迁移后补明确提示。

---

## 8. 评审点（请拍板）

1. `stock_basic` 本轮是否继续保持 `source_key=tushare|biying|all` 三模式完整兼容（方案默认：是）。
2. 快照类入口统一收敛到 `sync-snapshot`（`stock_basic` 先落地，其余 `hk_basic/us_basic/index_basic/etf_basic/ths_index/ths_member` 后续跟进；`dividend/stk_holdernumber` 暂不动）。
