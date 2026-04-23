# 数据同步 V2 R4-C 切换方案 v1（`biying_equity_daily` / `biying_moneyflow`）

- 版本：v1.0
- 日期：2026-04-23
- 状态：已完成（代码与本地冒烟）
- 范围：仅 BIYING 双数据集（`biying_equity_daily`、`biying_moneyflow`）
- 关联文档：
  - [数据同步 V2 切换运行手册 v1](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-cutover-runbook-v1.md)
  - [Sync V2 数据集策略简化方案 v1](/Users/congming/github/goldenshare/docs/architecture/sync-v2-dataset-strategy-simplification-plan-v1.md)
  - [BIYING 股票日线数据集开发说明](/Users/congming/github/goldenshare/docs/datasets/biying-equity-daily-dataset-development.md)
  - [BIYING 资金流向数据集开发说明](/Users/congming/github/goldenshare/docs/datasets/biying-moneyflow-dataset-development.md)

---

## 1. 本轮目标

本轮只做 1 件事：将 `biying_equity_daily` 与 `biying_moneyflow` 一起迁移到 Sync V2 contract + dataset strategy 路径，保持现有业务行为不变。

不做：

1. 不处理 `stock_basic`。
2. 不改上层 biz API 契约。
3. 不改融合策略中心语义。
4. 不扩展到 Tushare 数据集。

---

## 2. 当前实现基线（代码事实）

### 2.1 路由现状

1. `SYNC_SERVICE_REGISTRY` 总资源 `56`。
2. `SYNC_V2_CONTRACTS` 当前覆盖 `55`。
3. 未迁移仅剩 `1`：`stock_basic`。

### 2.2 当前 V1 行为（必须保留）

#### `biying_equity_daily`

1. 股票池来自 `raw_biying.stock_basic(dm, mc)`。
2. 按 `dm × adj_type(n/f/b) × 日期窗口(3000天)` 扇出请求。
3. 请求参数：`dm,freq=d,adj_type,st,et,lt=5000`。
4. 只写 `raw_biying.equity_daily_bar`。

#### `biying_moneyflow`

1. 股票池来自 `raw_biying.stock_basic(dm, mc)`。
2. 按 `dm × 日期窗口(100天)` 扇出请求。
3. 请求参数：`dm,st,et`（当前不传 `lt`）。
4. 写路径为：
   - `raw_biying.moneyflow`（raw）
   - `core_multi.moneyflow_std`（标准层，`source_key=biying`）
   - `core_serving.equity_moneyflow`（通过发布器）

### 2.3 连接器与限速事实

1. `BiyingSourceConnector` 已支持 `equity_daily_bar` 与 `moneyflow`。
2. 全局限速器：`BIYING_MAX_CALLS_PER_MINUTE`，默认 `280`（低于上游 300/min）。
3. `{"error":"数据不存在"}` 已按空结果处理，不抛错。
4. BIYING 接口无 `offset` 分页语义，只有 `lt`（最新条数）。

---

## 3. 迁移设计决策（本轮拍板）

1. 两个数据集必须同批迁移（共享证券池 + 共享限速约束 + 共享 BIYING 适配器）。
2. 执行层保持 V2（engine/validator/worker/observer）不变。
3. 请求编排使用“每数据集一个策略函数”，不新增抽象层。
4. 写入语义保持与 V1 一致，不做业务语义调整：
   - `biying_equity_daily`：raw-only
   - `biying_moneyflow`：raw + std + serving 发布

---

## 4. 目标 Contract 设计

## 4.1 `biying_equity_daily`

1. `run_profiles_supported`：`("point_incremental", "range_rebuild")`
2. `input_schema`（最小必需）：
   - `trade_date`（可选，点式）
   - `start_date/end_date`（可选，区间）
   - `ts_code`（可选，支持单值或逗号多值；内部映射为 `dm`）
   - `adj_type`（可选，`n/f/b`；未传默认全量）
3. `planning_spec`：
   - `anchor_type="natural_date_range"`
   - `window_policy="point_or_range"`
   - `universe_policy="none"`（证券池 fanout 在策略函数内实现）
   - `pagination_policy="none"`
4. `source_spec`：
   - `source_adapter_key="biying"`
   - `api_name="equity_daily_bar"`
5. `normalization_spec`：
   - 将 BIYING 响应字段标准化为 raw 表字段：
     `dm,trade_date,adj_type,mc,quote_time,open,high,low,close,pre_close,vol,amount,suspend_flag,raw_payload`
6. `write_spec`：
   - `raw_dao_name="raw_biying_equity_daily_bar"`
   - `core_dao_name="raw_biying_equity_daily_bar"`（占位，不新增虚假 serving）
   - `target_table="raw_biying.equity_daily_bar"`
   - `write_path="raw_only_upsert"`（新增）

## 4.2 `biying_moneyflow`

1. `run_profiles_supported`：`("point_incremental", "range_rebuild")`
2. `input_schema`（最小必需）：
   - `trade_date`（可选，点式）
   - `start_date/end_date`（可选，区间）
   - `ts_code`（可选，支持单值或逗号多值；内部映射为 `dm`）
3. `planning_spec`：
   - `anchor_type="natural_date_range"`
   - `window_policy="point_or_range"`
   - `universe_policy="none"`（证券池 fanout 在策略函数内实现）
   - `pagination_policy="none"`
4. `source_spec`：
   - `source_adapter_key="biying"`
   - `api_name="moneyflow"`
5. `normalization_spec`：
   - 标准化为 `raw_biying.moneyflow` 所需字段（含 `raw_payload`）。
6. `write_spec`：
   - `raw_dao_name="raw_biying_moneyflow"`
   - `core_dao_name="moneyflow_std"`
   - `target_table="core_serving.equity_moneyflow"`
   - `write_path="raw_std_publish_moneyflow_biying"`（新增）

---

## 5. 请求编排策略（按数据集单文件）

## 5.1 `biying_equity_daily` 策略

文件：`src/foundation/services/sync_v2/dataset_strategies/biying_equity_daily.py`

策略规则：

1. 点式：
   - 入参 `trade_date` -> 窗口 `[trade_date, trade_date]`
2. 区间：
   - 入参 `start_date/end_date` -> 自然日窗口拆分（窗口大小 `3000` 天）
3. 证券池：
   - 若传 `ts_code`，仅对显式代码执行（`normalize_dm_to_ts_code` 逆映射规则）
   - 未传时读取 `raw_biying.stock_basic` 全量 `dm`
4. 复权类型：
   - 显式 `adj_type` 仅执行指定值
   - 未传默认 `n,f,b` 全量扇出
5. 单元参数：
   - `dm,freq=d,adj_type,st,et,lt=5000`

## 5.2 `biying_moneyflow` 策略

文件：`src/foundation/services/sync_v2/dataset_strategies/biying_moneyflow.py`

策略规则：

1. 点式：
   - 入参 `trade_date` -> 窗口 `[trade_date, trade_date]`
2. 区间：
   - 入参 `start_date/end_date` -> 自然日窗口拆分（窗口大小 `100` 天）
3. 证券池：
   - 显式 `ts_code` 时仅执行指定代码
   - 未传时读取 `raw_biying.stock_basic` 全量 `dm`
4. 单元参数：
   - `dm,st,et`（默认不传 `lt`，保持 V1 行为）

---

## 6. 引擎与写入层最小扩展

## 6.1 新增写路径 `raw_only_upsert`

用于 raw-only 数据集（本轮仅 `biying_equity_daily`）：

1. 仅执行 raw upsert。
2. `rows_written` 返回 raw upsert 行数。
3. 不执行 core/serving 写入。

## 6.2 新增写路径 `raw_std_publish_moneyflow_biying`

用于 `biying_moneyflow`：

1. raw upsert 到 `raw_biying.moneyflow`。
2. 调用 `NormalizeMoneyflowService.to_std_from_biying_raw` 转为 std 行。
3. upsert 到 `core_multi.moneyflow_std`。
4. 调用 `publish_moneyflow_serving_for_keys` 发布到 `core_serving.equity_moneyflow`。

## 6.3 Linter/门禁同步

`sync_v2/linter.py` 允许写路径新增：

1. `raw_only_upsert`
2. `raw_std_publish_moneyflow_biying`

---

## 7. 测试与门禁

本轮门禁必须全绿：

1. `pytest -q tests/architecture/test_sync_v2_registry_guardrails.py`
2. `pytest -q tests/test_sync_v2_validator.py`
3. `pytest -q tests/test_sync_v2_planner.py`
4. `pytest -q tests/test_sync_v2_worker_client.py`
5. `pytest -q tests/test_sync_v2_linter.py`
6. `pytest -q tests/test_sync_v2_registry_routing.py`
7. `pytest -q tests/test_sync_v2_writer.py`
8. 新增：`tests/test_sync_v2_dataset_strategies_r4c_biying.py`
9. `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts`

新增测试要点：

1. `biying_equity_daily`：证券池扇出、adj_type 扇出、窗口拆分。
2. `biying_moneyflow`：证券池扇出、窗口拆分。
3. writer 新写路径行为断言。

---

## 8. 切换与验证计划（远程）

切换顺序固定：

1. `biying_equity_daily`
2. `biying_moneyflow`

每个数据集执行：

1. （历史执行）加入 `USE_SYNC_V2_DATASETS`。
2. 重启 `web/worker/scheduler`。
3. 执行小窗口 `sync-history`（优先 `1~3` 天 + 单代码）。
4. 执行 `sync-daily --trade-date`。
5. 验证执行结果与写入：
   - `biying_equity_daily`：检查 raw 行数增长 + `adj_type` 覆盖。
   - `biying_moneyflow`：检查 raw 行数增长、`moneyflow_std(source_key=biying)` 行数增长、serving 发布有写入。

说明：这两个数据集当前不使用 `reconcile-dataset` 作为主门禁（无直接同构 raw/serving 对账口径），采用“执行成功 + 分层写入校验 + 样本 SQL”三层门禁。

---

## 9. 回滚方案

任一失败立即按数据集粒度回滚：

1. （历史执行）从 `USE_SYNC_V2_DATASETS` 移除当前数据集。
2. 重启三服务。
3. 复跑同窗口 `sync-history/sync-daily` 验证 V1 恢复。
4. 记录失败点，冻结 R4-C。

---

## 10. 风险清单与控制

1. 证券池为空（`raw_biying.stock_basic` 无数据）
   - 控制：切换前先 SQL 预检库存。
2. BIYING 限速导致任务慢
   - 控制：保持 280/min，切换验证阶段缩小窗口与证券范围。
3. `dm -> ts_code` 映射异常影响 `moneyflow_std`
   - 控制：切换阶段强制抽样校验 `dm/ts_code/trade_date` 三元组。
4. 新写路径引发通用 writer 回归
   - 控制：writer 单测覆盖新旧路径并跑全门禁。

---

## 11. 执行工作包（仅 R4-C）

1. `R4C-WP-01`：新增双数据集 contract（registry_parts）+ guardrails 同步。
2. `R4C-WP-02`：新增双策略文件 + strategy 注册。
3. `R4C-WP-03`：writer 新写路径（raw_only / biying_moneyflow 发布路径）。
4. `R4C-WP-04`：补测试（strategy + writer + guardrails + lint）。
5. `R4C-WP-05`：远程按顺序切换与校验（先 equity_daily 后 moneyflow）。
