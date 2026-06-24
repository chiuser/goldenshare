# Dagster Asset Check 增量治理低层设计

对应方案文档：[`dagster-asset-check-incremental-governance-plan.md`](./dagster-asset-check-incremental-governance-plan.md)

更新时间：2026-06-24

## 1. 目标与边界

本 LLD 用于指导专项落地。P0.1 已完成治理矩阵与静态门禁开发；后续阶段仍按本文逐段推进。本文不授权执行 Dagster、删除 Dagster DB event 或触碰数据湖文件。

本专项要解决的是 Dagster asset check 增量膨胀问题：分钟线历史 event 已经通过 keep20 retention 降低了存量，但非分钟线资产仍有大量 ordinary asset check 持续写入 Dagster DB。后续如果不治理新增 check event 的写入模型，Asset 页面 Status 查询慢的问题还会复发。

目标：

1. 按当前代码逐项确认 check 的真实用途。
2. 把 check 分成“继续写 Dagster DB”“合并后继续写”“迁移到 DuckDB lake readiness”“迁移到 materialization metadata”“迁移到离线审计报告”“只做 retention”几类。
3. 给出代码级修改方案，细到文件、helper、readiness spec、job selection、测试和静态门禁。
4. 梳理后续推进阶段，保证每一阶段都有明确验收和 stop condition。

硬边界：

- 不新增持久化 readiness asset、summary asset、manifest、数据库表或 Dagster definition。
- 不把 sensor 热路径重新接回 Dagster event/check 深扫。
- 不删除 repair/status/completion 状态账本。
- 不用文档或命名猜测替代当前代码审计。
- 不长期保留新旧 check 双轨；迁移阶段可以短期并存，最终旧口径必须清零。

## 2. 当前代码审计

### 2.1 Catalog 与 readiness 主入口

资产 catalog 主入口：

- `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/lake_assets.py`

关键导出：

- `LAKE_ASSET_CATALOG`
- `list_lake_asset_catalog_entries()`
- `list_lake_asset_keys()`
- `get_lake_asset_catalog_entry(...)`

Sensor/readiness 主入口：

- `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py`

关键实现：

- `AssetReadinessSpec(asset_key, blocking_check_names)`
- `partition_dataset_readiness_status_from_latest_checks(...)`
- `asset_readiness_status(...)`
- `dataset_readiness_status(...)`

当前 readiness 的核心行为是：根据 `AssetReadinessSpec.blocking_check_names` 构造 `AssetCheckKey`，再从 Dagster event log storage 读取 latest check execution。结论是：

1. 只要 check name 仍在 readiness spec 里，就不能直接删除或改名。
2. 合并 check 后必须同步修改 readiness spec。
3. 如果 sensor 仍调用 `partition_dataset_readiness_status_from_latest_checks(...)`，就仍有 Dagster DB 查询成本。

### 2.2 已有 DuckDB lake readiness helper

当前仓库已经有多处 lake readiness helper，后续应优先复用，而不是再发明一套状态模型。

股票分钟线：

- `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_lake_readiness.py`
  - `batch_raw_stk_mins_lake_readiness(...)`
  - `batch_silver_stk_mins_lake_readiness(...)`
  - `batch_gold_stk_mins_qfq_lake_readiness(...)`

复权因子：

- `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/asset_guards/adj_factor_lake_readiness.py`
  - `batch_raw_adj_factor_lake_readiness(...)`
  - `batch_silver_adj_factor_lake_readiness(...)`
  - `batch_adj_factor_lake_readiness(...)`

指数与主要指数：

- `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/asset_guards/market_major_indices_lake_readiness.py`
  - `batch_market_major_indices_lake_readiness(...)`
  - `silver_index_daily_lake_readiness_for_trade_date(...)`
  - `silver_index_basic_lake_readiness(...)`

市场宽度与分布：

- `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/asset_guards/market_breadth_lake_readiness.py`
  - `batch_gold_market_breadth_lake_readiness(...)`
  - `batch_gold_stock_return_distribution_lake_readiness(...)`
  - `batch_clickhouse_market_breadth_readiness(...)`
  - `batch_prod_clickhouse_market_breadth_readiness(...)`

财富市场成交额：

- `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/asset_guards/wealth_market_turnover_lake_readiness.py`
  - `batch_gold_wealth_market_turnover_lake_readiness(...)`

设计结论：

- sensor 热路径优先接入这些 bounded lake readiness。
- check 合并或退出前，必须先证明 lake readiness 覆盖旧 blocking check 语义。
- 性能测试必须记录文件数、分区数、SQL 耗时，不允许用“理论更快”替代实测。

### 2.3 Job selection 现状

当前大多数 job selection 使用：

```python
dg.AssetSelection.assets(asset) | dg.AssetSelection.checks_for_assets(asset)
```

典型文件：

- `jobs/stock_daily_update.py`
- `jobs/stock_mins_raw_update.py`
- `jobs/stock_mins_silver_update.py`
- `jobs/stock_mins_qfq_daily_update.py`
- `jobs/gold_stk_mins_qfq_macd_kdj_daily_update.py`
- `jobs/index_daily_update.py`
- `jobs/silver_index_daily_update.py`
- `jobs/market_major_indices_daily_update.py`
- `jobs/stock_adj_factor_update.py`
- `jobs/market_breadth.py`
- `jobs/clickhouse_share_fact_market_breadth.py`
- `jobs/prod_clickhouse_share_fact_market_breadth_sync.py`
- `jobs/gold_wealth_market_turnover_update.py`

这意味着：check definition 数量会直接决定每次 materialization 后写入 Dagster DB 的 check event 数量。后续合并 check 后，很多 job selection 不需要逐个改；但如果新增 checks-only job，必须显式保证 selection 只包含 checks，不包含 assets。

### 2.4 股票分钟线 retention 工具现状

已有专用工具：

- `defs/bootstrap/stk_mins_event_history_retention.py`
- `defs/bootstrap/stk_mins_event_history_retention_cli.py`
- `defs/bootstrap/stk_mins_event_history_retention_sample_delete.py`
- `defs/bootstrap/stk_mins_event_history_retention_sample_delete_cli.py`

关键口径：

- keep window 来自 `cn_a_stock_mins_trade_days` 最近 20 个交易日。
- protected checks 包含 qfq factor repair plan/status、MACD/KDJ repair completion 等状态账本。
- 禁删 latest materialization。
- 禁删 latest materialization 绑定 checks。
- 禁删 keep20 内事件。

这些工具不能直接复用到非分钟线资产，因为非分钟线有不同 partition set、不同 protected check、不同 latest state 口径。后续需要新增通用但白名单化的 asset-check retention 工具。

### 2.5 高基数来源

基于 2026-06-24 正式 Dagster Postgres 只读统计，当前 check event 压力主要来自非分钟线资产。

| family | check rows | assets | check names | null partition rows | last 7d rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| other | 256,058 | 18 | 127 | 180,188 | 543 |
| market_breadth | 111,799 | 4 | 24 | 111,779 | 122 |
| index_daily | 45,358 | 2 | 10 | 45,318 | 70 |
| raw_stk_mins | 1,372 | 5 | 7 | 1,372 | 140 |
| gold_qfq | 1,330 | 7 | 12 | 840 | 763 |
| silver_stk_mins | 1,000 | 5 | 10 | 800 | 200 |
| MACD/KDJ indicator | 861 | 7 | 5 | 168 | 357 |
| MACD/KDJ state | 469 | 7 | 3 | 84 | 189 |

最大资产来源：

| asset_key | check rows | check names | null partition rows |
| --- | ---: | ---: | ---: |
| `gold_market_major_indices_daily` | 66,370 | 11 | 66,370 |
| `silver_stock_daily` | 61,560 | 14 | 61,560 |
| `silver_index_daily` | 45,316 | 8 | 45,316 |
| `silver_adj_factor` | 42,430 | 10 | 280 |
| `ch_share_fact_market_breadth_daily` | 39,656 | 6 | 39,656 |
| `raw_tushare_adj_factor` | 33,952 | 8 | 232 |
| `gold_market_breadth_daily` | 30,851 | 8 | 30,851 |
| `prod_ch_share_fact_market_breadth_daily` | 23,100 | 4 | 23,080 |
| `raw_tushare_stock_daily` | 20,665 | 8 | 20,665 |
| `raw_tushare_suspend_d` | 20,534 | 5 | 20,534 |
| `gold_stock_return_distribution` | 18,192 | 6 | 18,192 |
| `silver_stock_suspend_daily` | 10,278 | 3 | 10,278 |

结论：

1. 当前最大增量治理收益不在分钟线，而在非分钟线 ordinary checks。
2. 大量历史 check event 的 `partition` 为空，后续新实现必须避免继续写出不可归属的 partitioned check event。
3. `prod_ch_share_fact_market_breadth_daily` 已知存在 historical latest check 归属问题，不得直接放入大批量删除白名单。

### 2.6 额外发现：gold wealth turnover

代码中存在：

- `jobs/gold_wealth_market_turnover_update.py`
- `asset_guards/wealth_market_turnover_lake_readiness.py`

P0.1 已确认：

- 它已经进入 `LAKE_ASSET_CATALOG`，属于 active asset。
- 它已有正式 asset/check definition，blocking check 为 `gold_wealth_market_turnover_integrity_check`。
- 它已进入专项治理矩阵，当前分类为 `KEEP_BLOCKING_DAGSTER`，阶段为 `P0.1`。

因此它不能因为当前 DB rows 较少被排除在治理矩阵之外。

## 3. Check 分类模型

每个 check 必须归入一个治理类别。

### 3.1 KEEP_BLOCKING_DAGSTER

继续写 Dagster DB，并作为 blocking check 保留。

适用：

- sensor、repair、completion 或 run-status 必须直接消费。
- 表达状态账本，而不是普通数据质量证明。
- UI 需要展示当前资产健康摘要。

例子：

- qfq factor repair plan/status。
- MACD/KDJ repair completion。
- 少数 latest contract check。

### 3.2 MERGE_BLOCKING_DAGSTER

继续写 Dagster DB，但多个细粒度 check 合并成少数 coarse check。

适用：

- 多个 check 来自同一次文件读取或同一类 SQL 规则。
- 分开写入对调度没有额外价值。
- 失败明细可放 metadata。

命名建议：

- `*_contract_check`
- `*_key_integrity_check`
- `*_value_domain_check`
- `*_coverage_check`

### 3.3 MOVE_TO_SENSOR_LAKE_READINESS

不再依赖 Dagster check event 做 sensor 判断，改用 DuckDB/lake readiness。

适用：

- 文件存在、行数、schema、日期、唯一键、覆盖率、公式等语义。
- 可以从 lake 文件直接 bounded 查询。
- sensor 只需要最近 N 天或 selected date。

要求：

- 先实现 lake readiness。
- 再替换 sensor/readiness。
- 最后退休旧 check 或从 blocking spec 移除。

### 3.4 MOVE_TO_METADATA

不再写独立 check event，改为 asset materialization metadata。

适用：

- row count、source file count、sample rows、selected codes count。
- 只解释本次 materialization，不参与调度。

### 3.5 MOVE_TO_OFFLINE_AUDIT

不再每次 materialization 写 Dagster check，改为离线审计报告。

适用：

- 重算成本高。
- 不是每日链路阻断条件。
- 适合按周、按月或人工触发。

### 3.6 RETENTION_ONLY

暂不改 check definition，但对历史 event 做 bounded retention。

适用：

- 短期改代码风险高。
- check 仍有当前 UI/人工价值。
- 先用 retention 控制存量。

## 4. 代码级推进方案

### P0.1 治理矩阵与静态门禁

状态：已完成。

#### 改动文件

新增：

- `lake_console/orchestrator/tests/test_asset_check_incremental_governance.py`

修改：

- `lake_console/orchestrator/tests/test_run_contract_static_gates.py`
- `lake_console/docs/design/dagster-asset-check-incremental-governance-plan.md`

#### 代码要求

1. 从 `LAKE_ASSET_CATALOG`、check definitions、readiness specs 生成治理矩阵。
2. 每个 check 必须声明：
   - `asset_key`
   - `check_name`
   - `governance_category`
   - 是否 blocking
   - 是否参与 sensor readiness
   - 是否允许 retention 删除旧 event
   - protected reason
3. 测试必须在以下情况失败：
   - 新增 check 未分类。
   - 新增 blocking check 未说明 readiness 用途。
   - 新增 check 未声明 retention 口径。
   - 新增 check 进入 sensor 热路径但无 lake readiness 替代方案。
   - 新增 checks-only job selection 包含 `AssetSelection.assets(...)`。

#### 已落地事实

1. 新增 `tests/test_asset_check_incremental_governance.py`，覆盖 56 个 catalog active assets 的 blocking checks。
2. 治理矩阵显式声明每个 check 的分类、阶段、是否参与 sensor readiness、是否允许 retention 删除旧 event。
3. `STK_MINS_RETENTION_PROTECTED_CHECK_NAMES` 中的 repair/status/completion check 被纳入保护矩阵，且 `retention_allowed=False`。
4. readiness specs 与治理矩阵保持强一致；如果某个 check 仍被 sensor/readiness 消费，矩阵必须标记 `participates_in_sensor_readiness=True`。
5. checks-only 维护 job 门禁限定在 `*_check_refresh_job`，禁止这类 job 使用 `AssetSelection.assets(...)`。
6. `test_run_contract_static_gates.py` 增加治理矩阵存在性和危险写路径防回流检查。

#### 验证

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_asset_check_incremental_governance.py \
  tests/test_run_contract_static_gates.py
```

P0.1 验证结果：`56 passed`。

### P1 非分钟线 event retention dry-run

状态：dry-run 工具与本地测试已完成；正式 Dagster Postgres dry-run 尚未执行。

#### 改动文件

新增：

- `lake_console/orchestrator/src/orchestrator/defs/bootstrap/asset_check_event_retention.py`
- `lake_console/orchestrator/src/orchestrator/defs/bootstrap/asset_check_event_retention_cli.py`
- `lake_console/orchestrator/tests/test_asset_check_event_retention.py`

修改：

- `lake_console/orchestrator/tests/test_run_contract_static_gates.py`

#### 代码要求

实现只读 dry-run，不实现删除。

核心常量：

```python
ASSET_CHECK_RETENTION_KEEP_TRADE_DAY_COUNT = 20
ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES = frozenset({...})
ASSET_CHECK_RETENTION_ASSET_FAMILY_BY_KEY = {...}
```

报告字段：

- `should_stop`
- `running_or_queued_run_count`
- `keep_windows`
- `candidate_event_count_by_asset`
- `candidate_event_count_by_check`
- `protected_check_candidate_count`
- `latest_materialization_collision_count`
- `latest_bound_check_collision_count`
- `keep_window_collision_count`
- `excluded_asset_samples`

删除候选只读 SQL 必须显式排除：

- latest materialization。
- latest materialization 绑定 check。
- protected checks。
- keep window 内 event。
- 无 materialization 绑定的 null partition check，除非该资产族另行拍板。

已落地：

1. `asset_check_event_retention.py` 只提供 `collect_asset_check_event_retention_dry_run(...)`，所有 SQL 都通过 `_assert_select_only_sql(...)` 做只读检查。
2. 默认 scope 排除股票分钟线 31 个资产，覆盖非分钟线 active assets；`prod_ch_share_fact_market_breadth_daily` 和 `lake_root_health` 不进入候选，写入 `excluded_asset_samples` 说明原因。
3. keep window 按资产实际 partition set 分组计算：`cn_a_stock_trade_days`、`cn_a_stock_current_trade_days`、`cn_a_index_trade_days`、`cn_a_stock_mins_silver_trade_days`。
4. 候选只包含有 partition 的 ordinary historical check/materialization event；null partition event 不进入候选。
5. protected repair/status/completion checks 继续使用 `ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES` 防误删。
6. CLI 只有 `dry-run` 子命令，没有 `apply/delete/confirm` 写入口。
7. 静态门禁已检查 P1 工具不可包含 `DELETE/INSERT/UPDATE/VACUUM/ANALYZE` 等写路径。

#### 正式 dry-run 命令

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . python -m orchestrator.defs.bootstrap.asset_check_event_retention_cli dry-run \
  --postgres-url postgresql://congming@localhost:5432/goldenshare_dagster \
  --output /private/tmp/asset_check_event_retention_dry_run_<timestamp>.json
```

本地验证：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_asset_check_event_retention.py \
  tests/test_asset_check_incremental_governance.py \
  tests/test_run_contract_static_gates.py
```

结果：`64 passed`。

### P2 Index Daily 与 Major Indices

状态：已落地。P2 将 `silver_index_daily` 与
`gold_market_major_indices_daily` 的正式 Dagster blocking check 收敛为
4 个粗粒度 check，同时保持内部规则 SQL 语义；sensor 热路径继续走
DuckDB lake readiness，不回到 Dagster check history 深扫。

#### 改动文件

- `lake_console/orchestrator/src/orchestrator/defs/checks/index_daily_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/market_major_indices_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/market_major_indices_lake_readiness.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/silver_index_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/market_major_indices_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py`
- 对应 tests。

#### 修改方式

`silver_index_daily`：

- 合并为最多 4 个 Dagster checks：
  - `silver_index_daily_contract_check`
  - `silver_index_daily_key_integrity_check`
  - `silver_index_daily_value_domain_check`
  - `silver_index_daily_registered_code_coverage_check`
- 失败明细写 metadata：
  - `rule_passed`
  - `failed_rule_names`
- 旧细粒度规则保留为内部 helper，不再注册为 Dagster check。
- `silver_index_daily_sensor` 使用
  `batch_silver_index_daily_lake_readiness(...)` +
  `select_first_not_ready_trade_date(...)`，不再调用
  `select_first_not_ready_silver_index_daily_partition(...)` 或 Dagster
  latest-check selector。

`gold_market_major_indices_daily`：

- 合并为最多 4 个 Dagster checks：
  - `gold_market_major_indices_daily_contract_check`
  - `gold_market_major_indices_daily_value_domain_check`
  - `gold_market_major_indices_daily_seed_coverage_check`
  - `gold_market_major_indices_daily_ranking_consistency_check`
- 如果 ranking consistency 不影响每日调度，优先迁到 offline audit。
- `market_major_indices_daily_sensor` 继续使用 `batch_market_major_indices_lake_readiness(...)`。
- `market_major_indices_lake_readiness.py` 的 failed/missing check name
  同步映射到 4 个粗粒度 check，cursor 不再暴露旧 check name 作为正式
  blocking check。

`readiness.py`：

- `SILVER_INDEX_DAILY_BLOCKING_CHECKS` 与
  `GOLD_MARKET_MAJOR_INDICES_DAILY_BLOCKING_CHECKS` 只保留新 check name。
- sensor 热路径禁止调用 `partition_dataset_readiness_status_from_latest_checks(...)`。

#### 测试

- 新 check 正负样本。
- 旧 check name 清零。
- sensor 不调用 `partition_dataset_readiness_status_from_latest_checks(...)`。
- P2 本地验证：
  `tests/test_index_daily_checks.py`、
  `tests/test_market_major_indices_checks.py`、
  `tests/test_market_major_indices_lake_readiness.py`、
  `tests/test_market_major_indices_daily_sensor.py`、
  `tests/test_silver_index_daily_sensor.py`、
  `tests/test_asset_check_incremental_governance.py`、
  `tests/test_asset_governance_contracts.py`、
  `tests/test_run_contract_static_gates.py`。

### P3 Stock Daily / Suspend / Adj Factor

状态：已完成。P3A `adj_factor`、P3B `stock_daily`、P3C `suspend`
均已落地。

#### 改动文件

- `lake_console/orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/suspend_d_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/adj_factor_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stock_partition_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/adj_factor_lake_readiness.py`
- 新增或扩展 `asset_guards/stock_daily_lake_readiness.py`
- 新增或扩展 `asset_guards/suspend_lake_readiness.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/suspend_d_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_adj_factor_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py`
- 对应 tests。

#### 修改方式

`silver_stock_daily`：

- P3B 已落地。
- raw Dagster checks 合并为：
  - `raw_stock_daily_contract_check`
  - `raw_stock_daily_key_integrity_check`
  - `raw_stock_daily_tradable_universe_check`
  - `raw_stock_daily_partition_allowed_check`
- silver Dagster checks 合并为：
  - `silver_stock_daily_contract_check`
  - `silver_stock_daily_key_integrity_check`
  - `silver_stock_daily_value_domain_check`
  - `silver_stock_daily_lifecycle_coverage_check`
  - `silver_stock_daily_tradable_universe_check`
  - `silver_stock_daily_partition_allowed_check`
- lifecycle 事实源必须使用 `silver_stock_lifecycle`。
- 不允许下游绕回 `raw_stock_basic` 或 current-listed-only `silver_stock_basic`。
- 旧细粒度函数保留为内部 helper；catalog、readiness spec 与治理矩阵只保留
  新 check name。

`suspend`：

- P3C 已落地。
- `raw_tushare_suspend_d` 正式 Dagster checks 收敛为：
  - `raw_suspend_d_contract_check`
  - `raw_suspend_d_partition_allowed_check`
- `silver_stock_suspend_daily` 正式 Dagster checks 收敛为：
  - `silver_suspend_d_key_integrity_check`
  - `silver_suspend_d_suspend_type_domain_check`
  - `silver_suspend_d_partition_allowed_check`
- 旧细粒度 suspend 函数只作为内部 helper；catalog、readiness spec 与治理
  矩阵只保留新 check name。

`adj_factor`：

- P3A 已落地。
- 复用 `adj_factor_lake_readiness.py`，不改 sensor 热路径。
- raw Dagster checks 合并为：
  - `raw_adj_factor_contract_check`
  - `raw_adj_factor_key_value_integrity_check`
  - `raw_adj_factor_partition_allowed_check`
- silver Dagster checks 合并为：
  - `silver_adj_factor_contract_check`
  - `silver_adj_factor_key_value_integrity_check`
  - `silver_adj_factor_lifecycle_coverage_check`
  - `silver_adj_factor_partition_allowed_check`
- 旧细粒度函数保留为内部 helper；catalog、readiness spec 与治理矩阵只保留
  新 check name。

#### 性能门禁

- DuckDB 查询必须 set-based。
- 不允许 Python 行循环扫描全量股票日线。
- 不允许 sensor 读取 Dagster check history 判断最近窗口。

### P4 Market Breadth / Return Distribution / Serving

状态：已完成。P4 合并 gold/local ClickHouse 普通 check；prod ClickHouse
serving 保持 P2R 后的 single-partition attributable check 口径，不做
合并。

#### 改动文件

- `lake_console/orchestrator/src/orchestrator/defs/checks/market_breadth_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stock_return_distribution_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/clickhouse_serving_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/prod_clickhouse_serving_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/market_breadth_lake_readiness.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/market_breadth_continuity_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_return_distribution_continuity_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/clickhouse_market_breadth_continuity_sensor.py`
- 对应 jobs/tests。

#### 修改方式

`gold_market_breadth_daily`：

- 正式 Dagster checks 收敛为：
  - `gold_market_breadth_contract_check`
  - `gold_market_breadth_value_domain_check`
  - `gold_market_breadth_silver_reconciliation_check`
  - `gold_market_breadth_partition_allowed_check`
- 旧细粒度函数只作为内部 helper；batch lake readiness 仍执行 row count、
  bucket 加和、red rate、silver row count、silver recompute 等完整语义，
  失败时映射到新粗粒度 check name。

`gold_stock_return_distribution`：

- 正式 Dagster checks 收敛为：
  - `gold_stock_return_distribution_contract_check`
  - `gold_stock_return_distribution_value_domain_check`
  - `gold_stock_return_distribution_silver_reconciliation_check`
  - `gold_stock_return_distribution_partition_allowed_check`
- 旧细粒度函数只作为内部 helper；batch lake readiness 仍执行 row count、
  partition date、bucket 加和、silver row count、silver recompute 等完整语义，
  失败时映射到新粗粒度 check name。

`ch_share_fact_market_breadth_daily`：

- 正式 Dagster checks 收敛为：
  - `ch_share_fact_market_breadth_contract_check`
  - `ch_share_fact_market_breadth_gold_reconciliation_check`
- local ClickHouse batch readiness 仍执行 row count、date、total/flat、
  breadth fields、distribution fields 对账完整语义，失败时映射到新粗粒度
  check name。

`prod_ch_share_fact_market_breadth_daily`：

- 已知 historical check 归属问题，不进入大批量删除白名单。
- 日常路径必须保持 single-partition attributable。
- P4 不合并 prod checks，继续保留
  `prod_ch_share_fact_market_breadth_row_count_is_one`、
  `prod_ch_share_fact_market_breadth_date_matches_partition`、
  `prod_ch_share_fact_market_breadth_row_matches_local`、
  `prod_ch_share_fact_market_breadth_updated_at_not_older_than_local`。

#### 性能门禁

- `BreadthFactQuery.load_many(...)` 必须保持 bounded。
- 不允许恢复 multi-partition 一条 check event 的写法。
- offline audit 输出报告，不写海量 Dagster check events。

### P5 Snapshot / Basic Facts

#### 改动文件

- `lake_console/orchestrator/src/orchestrator/defs/checks/calendar_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stock_basic_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stock_lifecycle_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/namechange_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stock_identity_map_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/index_basic_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/lake_root_health_checks.py`
- 对应 jobs/tests。

#### 修改方式

每个 snapshot asset 最多保留：

- contract check
- key integrity check
- domain / lifecycle coverage check

以下迁到 metadata：

- row count
- source file path
- source snapshot date
- sample rows

历史全量一致性证明迁到 offline audit。

`silver_stock_lifecycle` 是正式生命周期事实源，下游不得自行回读 `raw_stock_basic` 重新推生命周期。

### P6 股票分钟线剩余治理

#### 改动文件

- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_qfq_macd_kdj_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_lake_readiness.py`
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_qfq_effective_readiness.py`
- 股票分钟线相关 sensors/tests/retention 工具。

#### 修改方式

- 不动 protected repair/status/completion checks。
- 普通分钟线 checks 继续 keep20。
- 若进一步合并 MACD/KDJ indicator/state checks，必须同步：
  - checks-only refresh job
  - daily job selection
  - readiness specs
  - retention protected/allowed sets

#### 性能门禁

- 不恢复 60 日窗口。
- 不用文件存在冒充完整 readiness。
- 不允许 sensor 中出现无界 DuckDB 文件扫描或 Dagster event 深扫。

## 5. Retention 低层设计

### 5.1 新工具边界

通用工具不复用 `stk_mins_event_history_retention_*`，避免混用分钟线 keep window 和 protected checks。

新增：

- `asset_check_event_retention.py`
- `asset_check_event_retention_cli.py`
- `asset_check_event_retention_sample_delete.py`
- `asset_check_event_retention_sample_delete_cli.py`

### 5.2 候选事件范围

只允许候选：

- `asset_check_executions`
- `event_logs` 中 `ASSET_CHECK_EVALUATION`
- `event_logs` 中 `ASSET_MATERIALIZATION`
- 对应 `asset_event_tags`

禁止候选：

- `runs`
- `run_tags`
- `dynamic_partitions`
- `instigators`
- planned events
- latest materialization
- latest-bound checks
- protected checks
- keep window 内事件

### 5.3 Null partition 处理

大量历史 check event 的 partition 为空。删除判断不能只靠 partition。

规则：

1. 优先通过 `asset_check_executions.materialization_event_storage_id` 绑定 materialization。
2. 无 materialization 绑定的 null partition check 默认不删。
3. 不用 event timestamp 冒充 partition；timestamp 只能作为额外保护条件。

### 5.4 正式删除流程

每个正式删除阶段必须：

1. active runs = 0。
2. 完整备份 Dagster Postgres。
3. pre dry-run。
4. 单资产或小批次事务删除。
5. 提交前 safety assertions。
6. post dry-run。
7. 标准 `VACUUM (VERBOSE, ANALYZE)` 单独阶段执行。

## 6. 测试与验证

### 6.1 单元与静态测试

新增或扩展：

- `tests/test_asset_check_incremental_governance.py`
- `tests/test_asset_check_event_retention.py`
- `tests/test_run_contract_static_gates.py`

覆盖：

- 每个 check 必须分类。
- 未分类 check 失败。
- protected check 不能进入 retention。
- old check name 迁移后清零。
- sensor 热路径不能回流 Dagster event 深扫。
- checks-only job 不包含 `AssetSelection.assets(...)`。

### 6.2 性能测试

每个资产族改动前必须做只读性能样本：

- 当前 Dagster check 查询耗时。
- 新 lake readiness 查询耗时。
- 20 日窗口耗时。
- 文件数、分区数、SQL 行数。
- 是否存在 Python 行循环。

性能报告写 `/private/tmp`，结论摘要写回方案文档。

### 6.3 静态审计命令

```bash
rg -n "partition_dataset_readiness_status_from_latest_checks|asset_readiness_status|dataset_readiness_status" \
  /Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/sensors

rg -n "AssetSelection\.checks_for_assets|AssetSelection\.assets" \
  /Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/jobs

rg -n "AssetCheckResult|asset_check|blocking" \
  /Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/checks
```

## 7. 推进顺序

1. P0.1：治理矩阵与静态门禁。
2. P1：非分钟线 retention dry-run，只读报告。
3. P2：Index Daily 与 Major Indices check 合并和 lake readiness 对账。
4. P3：Stock Daily / Suspend / Adj Factor check 合并和 lifecycle 口径收敛。
5. P4：Market Breadth / Return Distribution / Serving check 精简与 offline audit。
6. P5：Snapshot / Basic Facts check 合并。
7. P6：股票分钟线剩余普通 check 治理。
8. P7：最终 retention、标准 vacuum、文档对账。

## 8. Stop Conditions

以下情况必须停止：

- 无法证明某个 check 是否参与 sensor/readiness。
- 新 lake readiness 不能覆盖旧 blocking check 语义。
- 性能测试显示新方案比旧方案更慢或接近超时。
- 需要正式 Dagster 写入才能完成代码阶段判断。
- 删除候选包含 latest state、keep window 或 protected checks。
- active runs 非 0 时试图进入删除阶段。
- 发现计划与当前代码冲突，且需要扩大范围才能解决。

## 9. 最终验收标准

专项完成后必须满足：

1. 所有 active asset check 都有治理分类。
2. sensor 热路径不依赖高基数 Dagster check history 深扫。
3. 非分钟线高基数 check 数量明显下降。
4. 普通历史 check event 有 keep20/latest/protected retention 口径。
5. repair/status/completion 状态账本不被删除、不被降级。
6. Asset UI Status 查询压力下降。
7. 新增数据集或新增 check 时，静态门禁会要求先声明分类、保留期限和性能预算。
