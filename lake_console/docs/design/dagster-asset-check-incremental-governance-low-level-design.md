# Dagster Asset Check 增量治理低层设计

对应方案文档：[`dagster-asset-check-incremental-governance-plan.md`](./dagster-asset-check-incremental-governance-plan.md)

更新时间：2026-06-25

> **QFQ/MACD-KDJ 状态校正（2026-07-15）：** 本文中 M6/P6 的旧 formula check 描述和事件量是历史设计记录，不能作为当前定义依据。现行 production check 集合由 `defs/checks/stk_mins_checks.py`、`defs/checks/stk_mins_qfq_macd_kdj_checks.py` 与 QFQ validation LLD 共同固定：QFQ native/derived 各 4 条、indicator 2 条、state 2 条；公式正确性在受保护金样本测试中验证。

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

- `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py`

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

基于 2026-06-24 正式 Dagster Postgres 的只读历史统计，当时 check event 压力主要来自非分钟线资产；下表的 check names 不是当前 active check 清单。

| family | 历史 check rows | assets | 历史 check names | null partition rows | 当时 last 7d rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| other | 256,058 | 18 | 127 | 180,188 | 543 |
| market_breadth | 111,799 | 4 | 24 | 111,779 | 122 |
| index_daily | 45,358 | 2 | 10 | 45,318 | 70 |
| raw_stk_mins | 1,372 | 5 | 7 | 1,372 | 140 |
| gold_qfq | 1,330 | 7 | 12 | 840 | 763 |
| silver_stk_mins | 1,000 | 5 | 10 | 800 | 200 |
| MACD/KDJ indicator | 861 | 7 | 5 | 168 | 357 |
| MACD/KDJ state | 469 | 7 | 3 | 84 | 189 |

该历史快照中的最大资产来源：

| asset_key | 历史 check rows | 历史 check names | null partition rows |
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

### 2.7 当前代码对账清单

本 LLD 的代码事实按以下入口审计，不以后续开发计划、旧文档或 check
命名印象替代当前实现。

| 审计对象 | 当前代码入口 | LLD 约束 |
| --- | --- | --- |
| active asset 与 blocking checks | `defs/catalog/lake_assets.py` | 所有治理矩阵、retention 白名单、check 合并目标必须从 `LAKE_ASSET_CATALOG` 对账。 |
| readiness 消费 | `defs/sensors/readiness.py`、`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py` | 仍在 `AssetReadinessSpec` 中出现的 check 不得直接删除；合并后必须同步 readiness specs。 |
| check definition | `defs/checks/**` | 旧细粒度函数可保留为内部 rule/helper，但不得继续注册为正式 Dagster check。 |
| lake readiness | `defs/asset_guards/*_lake_readiness.py` | sensor 热路径应优先使用 DuckDB/lake readiness；不得回流逐日 Dagster event/check history 深扫。 |
| runless/bootstrap | `defs/bootstrap/*_events.py`、`defs/bootstrap/*_history.py` | 历史事件补录和数量估算必须引用正式 check 常量，禁止写回旧 check name。 |
| jobs/checks-only jobs | `defs/jobs/**` | 普通 update job 可继续 `assets | checks_for_assets`；`*_check_refresh_job` 必须只选 checks。 |
| 静态门禁 | `tests/test_asset_check_incremental_governance.py`、`tests/test_run_contract_static_gates.py` | 新增 active blocking check 必须先声明治理分类、readiness 参与状态和 retention 口径。 |

当前已核对的关键常量：

- `defs/catalog/lake_assets.py` 与 `tests/test_asset_check_incremental_governance.py`
  均已登记 P2-P6 合并后的正式 check names。
- `defs/sensors/readiness.py` 中 daily、suspend、adj factor、index daily、分钟线 qfq
  等 readiness specs 已使用合并后的 check names。
- `defs/checks/stk_mins_qfq_macd_kdj_checks.py` 中 MACD/KDJ indicator 当前为
  `contract/source_coverage` 两个 production check；`formula_sample` 已退出正式
  Dagster check，公式正确性由受保护金样本测试承担。state checks 仍保持两个。
- `defs/checks/wealth_market_turnover_checks.py` 当前正式 check 为
  `gold_wealth_market_turnover_integrity_check`，已纳入治理矩阵，暂不进入合并优先级。

后续任何阶段若发现 catalog、readiness、check definition、runless/bootstrap
之间的正式 check names 不一致，应先修代码事实和测试，再更新本文档；不得让
文档继续描述一个不存在或已退役的 check 集合。

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

状态：dry-run 工具、本地测试与正式 Dagster Postgres 只读 dry-run 均已完成。

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

#### 正式 dry-run 结果

执行时间：2026-06-25。

报告路径：

- `/private/tmp/asset_check_event_retention_dry_run_20260625_p7b.json`

关键结论：

- `should_stop=false`
- `running_or_queued_run_count=0`
- safety assertions 全部通过，失败断言为空
- protected check 候选为空
- keep windows 均为最近 20 个交易日，窗口为 `2026-05-27` 到 `2026-06-24`
- `prod_ch_share_fact_market_breadth_daily`、`lake_root_health` 被明确排除，不进入候选

候选规模：

| candidate type | count |
| --- | ---: |
| check executions | 75,875 |
| check evaluation events | 75,875 |
| check event tags | 0 |
| materialization events | 42,310 |
| materialization event tags | 33,877 |

主要候选来源：

| asset | check candidates | materialization candidates |
| --- | ---: | ---: |
| `silver_adj_factor` | 42,150 | 4,222 |
| `raw_tushare_adj_factor` | 33,720 | 4,222 |
| `gold_market_major_indices_daily` | 0 | 6,393 |
| `silver_index_daily` | 0 | 6,393 |
| `ch_share_fact_market_breadth_daily` | 0 | 3,011 |
| `gold_market_breadth_daily` | 0 | 3,011 |
| `gold_stock_return_distribution` | 0 | 3,011 |

当前表规模：

- `event_logs`: 3,819,311 rows，约 11 GB
- `asset_check_executions`: 418,513 rows，约 3,298 MB
- `asset_event_tags`: 42,775 rows，约 32 MB

结论：P7B 只读候选验证通过，可以进入非分钟线 sample-delete 执行器开发；正式删除仍属于 P7C，必须在备份、pre dry-run 和单独批准后才能执行。

#### P7B sample-delete 执行器

状态：已完成代码与本地测试，尚未执行正式删除。

新增文件：

- `lake_console/orchestrator/src/orchestrator/defs/bootstrap/asset_check_event_retention_sample_delete.py`
- `lake_console/orchestrator/src/orchestrator/defs/bootstrap/asset_check_event_retention_sample_delete_cli.py`

安全口径：

- CLI 只有 `sample-delete` 子命令，没有 dry-run 伪装、批量 apply 或默认资产。
- `--sample-asset` 必填；一次只允许一个资产。
- 必须显式传 `--confirm-sample-delete`，否则拒绝写入。
- 资产必须在非分钟线 retention 白名单中，且必须绑定 keep partition set；snapshot 资产如 `raw_tushare_stock_basic` 不允许进入 sample-delete。
- 候选 CTE 复用 P1 dry-run 的资产 scope、keep window、latest materialization、protected check 排除语义。
- 删除顺序固定为 check tags、check events、check executions、materialization tags、materialization events。
- 删除事务提交前重新跑 safety assertions，包含 active runs、keep20、latest state、protected checks、partition key 和 check event type 校验。
- 任一 safety assertion 失败即 rollback。
- 不删除 `runs`、`run_tags`、`dynamic_partitions`、`instigators`、planned events 或数据湖文件。

本地验证：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_asset_check_event_retention.py \
  tests/test_run_contract_static_gates.py
```

结果：`70 passed`。

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

状态：P5 已落地。P5A `calendar/index_basic` 已落地；P5B
`stock basic/lifecycle/namechange/identity map` 已落地；P5C
`lake_root_health` 已落地。

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

P5A 已落地：

- `raw_tushare_trade_calendar`：
  - `raw_trade_calendar_contract_check`
  - 旧 `file_exists/required_columns/contains_required_exchange` 函数只作为
    helper，不再注册为 Dagster check。
- `silver_trade_calendar`：
  - 暂保留 `silver_trade_calendar_required_columns_non_null`
  - 暂保留 `silver_trade_calendar_unique_exchange_trade_date`
  - 这两个 check 已经是核心 contract/key 语义，P5A 不强行合并。
- `raw_tushare_index_basic`：
  - `raw_index_basic_contract_check`
  - `raw_index_basic_key_integrity_check`
  - `raw_index_basic_date_domain_check`
- `silver_index_basic`：
  - `silver_index_basic_contract_check`
  - `silver_index_basic_key_integrity_check`
  - `silver_index_basic_lifecycle_domain_check`
- `market_major_indices_lake_readiness.py` 仍保留原完整 readiness SQL 语义；
  只把失败 check name 映射为新的粗粒度名称。

P5B 已落地：

- `raw_tushare_stock_basic`：
  - `raw_stock_basic_contract_check`
  - `raw_stock_basic_key_integrity_check`
- `silver_stock_basic`：
  - `silver_stock_basic_contract_check`
  - `silver_stock_basic_key_integrity_check`
  - `silver_stock_basic_current_listed_domain_check`
- `silver_stock_lifecycle`：
  - `silver_stock_lifecycle_contract_check`
  - `silver_stock_lifecycle_key_integrity_check`
  - `silver_stock_lifecycle_domain_check`
- `raw_tushare_namechange`：
  - `raw_namechange_contract_check`
  - `raw_namechange_key_integrity_check`
  - `raw_namechange_date_domain_check`
  - 旧 raw namechange observed checks 不再注册为 Dagster checks；
    函数保留为 offline audit/helper。
- `silver_namechange`：
  - `silver_namechange_contract_check`
  - `silver_namechange_key_integrity_check`
  - `silver_namechange_interval_domain_check`
- `silver_stock_identity_map`：
  - `silver_stock_identity_map_contract_check`
  - `silver_stock_identity_map_key_integrity_check`
  - `silver_stock_identity_map_reference_domain_check`
- `readiness.py` 和 `lake_assets.py` 已同步为 P5B 粗粒度 check names；
  sensor 语义不变，只减少 Dagster check event 粒度。

P5C 已落地：

- `lake_root_health` 正式 Dagster checks 从 4 个收敛为 1 个：
  - `lake_root_health_ready`
- 旧 `lake_root_required_paths_ready`、`lake_root_read_write_ready`、
  `lake_root_disk_space_ready`、`duckdb_temp_directory_ready` 函数保留为
  helper，不再注册为 Dagster checks。
- 新 check 只调用一次 `evaluate_lake_root_health(...)`，metadata 中保留
  `rule_passed` 和 `failed_rule_names`，继续能定位 required paths、read/write、
  disk space、DuckDB temp directory 哪个子规则失败。
- `lake_root_health` 仍不进入普通 retention 候选。

### P6 股票分钟线剩余治理

状态：P6A-P6D 已按当前代码落地。后续不再把 P6 视为待开发阶段；
只允许做回归、文档对账和正式 retention / vacuum 审批。

#### 改动文件

- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_qfq_macd_kdj_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_lake_readiness.py`
- 股票分钟线相关 sensors/tests/retention 工具。

#### 修改方式

- 不动 protected repair/status/completion checks。
- 普通分钟线 checks 继续 keep20。
- P6A 先收敛 `raw_stk_mins`：
  - `RAW_STK_MINS_CHECK_NAMES` 从旧 7 个普通 check 改为
    `raw_stk_mins_contract_check`、`raw_stk_mins_key_integrity_check`、
    `raw_stk_mins_value_domain_check`。
  - `raw_stk_mins_contract_check` 聚合文件存在/行数、schema、freq、partition date。
  - `raw_stk_mins_key_integrity_check` 聚合 `(ts_code, trade_time)` 唯一性和
    `cn_a_stock_mins_trade_days` partition registered。
  - `raw_stk_mins_value_domain_check` 保留原 price/volume/null/negative value sanity。
  - 旧细粒度 evaluator 继续作为内部 helper 或历史反例使用，不再注册为正式
    Dagster asset check。
  - `batch_raw_stk_mins_lake_readiness(...)` 不新增查询，只把原 metrics 映射到
    3 个新 failed check names。
  - `stk_mins_migration` 的 raw runless/bootstrap audit 也只输出 3 个新 check 名称。
- P6B 收敛 `silver_stk_mins`：
  - `SILVER_STK_MINS_CHECK_NAMES` 从旧 10 个普通 check 改为
    `silver_stk_mins_contract_check`、`silver_stk_mins_key_integrity_check`、
    `silver_stk_mins_value_domain_check`、`silver_stk_mins_reference_coverage_check`。
  - `contract` 聚合文件存在/行数、schema、freq/date/path。
  - `key_integrity` 聚合 `(ts_code, trade_time)` 唯一性。
  - `value_domain` 聚合 price、volume/amount、exchange suffix。
  - `reference_coverage` 聚合 stock daily code 覆盖、suspend structural rows、
    `silver_stock_lifecycle` 生命周期覆盖，并保留 `silver_stock_lifecycle` 依赖。
  - `batch_silver_stk_mins_lake_readiness(...)` 不新增查询，只把现有 metrics 映射到
    4 个新 failed check names。
  - `stk_mins_silver_history` 和 `stk_mins_silver_bootstrap_events` 的事件数量估算和
    runless 输出同步改用新 `SILVER_STK_MINS_CHECK_NAMES`。
  - `silver_stk_mins_name_timeline_covered` 只保留在旧 000638 dry-run helper 的历史
    审计语境，不再是当前正式 silver readiness check。
- P6C 收敛 `gold_stk_mins_qfq`：
  - `GOLD_STK_MINS_QFQ_NATIVE_CHECK_NAMES` 从旧 8 个普通 check 改为
    `gold_stk_mins_qfq_contract_check`、
    `gold_stk_mins_qfq_key_integrity_check`、
    `gold_stk_mins_qfq_value_domain_check`、
    `gold_stk_mins_qfq_source_coverage_check`。
  - `GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES` 从旧 8 个普通 check 改为
    `gold_stk_mins_qfq_contract_check`、
    `gold_stk_mins_qfq_key_integrity_check`、
    `gold_stk_mins_qfq_value_domain_check`、
    `gold_stk_mins_qfq_derived_source_coverage_check`。
  - native `contract` 聚合文件存在/行数、schema、freq/date/path；
    `key_integrity` 聚合 `(ts_code, trade_time)` 唯一性；`value_domain` 保留价格 sanity；
    `source_coverage` 聚合 silver row count 与 adj factor coverage。
  - derived `contract` 聚合文件存在/行数、schema、freq/date/path；
    `key_integrity` 聚合 `(ts_code, trade_time)` 唯一性；`value_domain` 保留价格 sanity；
    `derived_source_coverage` 聚合 source ready、source window、derived row count。
  - native QFQ 与 derived QFQ 的业务公式不再注册为 Dagster check：它们由受保护的
    金样本测试验证。derived source window 仍是 production lineage 事实。
  - `_gold_qfq_check_results(...)` 和 `_gold_qfq_derived_check_results(...)` 继续保留旧细粒度
    rule 名称作为 `failed_rule_names` metadata，供人工定位具体失败原因；这些旧名称不再进入
    `LAKE_ASSET_CATALOG`、`readiness.py` 或 Dagster official check set。
  - `batch_gold_stk_mins_qfq_lake_readiness(...)` 不新增 DuckDB 查询，只把现有 metrics 映射到
    native/derived 各 4 个正式 failed check names；缺文件或目标日 0 行都归入 `contract` 且
    `materialized=False`。
  - `stk_mins_qfq_history`、`stk_mins_qfq_derived_history` 与 qfq bootstrap event 工具的事件数量
    估算必须引用正式 `GOLD_STK_MINS_QFQ_*_CHECK_NAMES` 长度，禁止继续硬编码旧 8 个 check。
  - qfq factor repair plan/status、MACD/KDJ repair completion 等 protected checks 不属于 P6C，
    不改名称、不进入合并。
- P6D 当前代码事实与后续治理目标：
  - `GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES` 当前为
    `gold_stk_mins_qfq_macd_kdj_contract_check`、
    `gold_stk_mins_qfq_macd_kdj_source_coverage_check`。
  - `contract` 复用 `_indicator_file_exists_and_schema_result(...)`，覆盖 indicator 文件存在、
    目标日行数和 schema。
  - `source_coverage` 合并原 `_indicator_source_ready_result(...)` 与
    `_indicator_row_count_matches_qfq_result(...)`，一次性判断 qfq source 是否存在以及
    indicator row count 是否与 qfq source 对齐；旧细粒度名称只作为 `failed_rule_names`
    metadata。
  - MACD/KDJ 公式自洽已由受保护金样本测试承担；正式 production check 集合只保留
    `contract` 和 `source_coverage`。
  - `GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES` 暂不合并，继续保留
    `state_file_exists_and_schema_check` 和 `state_latest_coverage_check`；state readiness 直接影响
    daily exact previous state gate 和 repair gate，不能隐藏为单一普通 check。
  - `LAKE_ASSET_CATALOG`、daily/repair readiness specs、baseline runless audit 和
    `gold_stk_mins_qfq_macd_kdj_check_refresh_job` 自动继承新 check set。
  - `stk_mins_qfq_macd_kdj_history` 的 `GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_COUNT_PER_FREQ_PARTITION`
    必须由 indicator/state check 常量长度计算，不得继续硬编码旧 6 个 check。
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

当前已存在的非分钟线只读工具：

- `asset_check_event_retention.py`
- `asset_check_event_retention_cli.py`

当前不存在、也不得在 dry-run 阶段假设存在的正式删除工具：

- `asset_check_event_retention_sample_delete.py`
- `asset_check_event_retention_sample_delete_cli.py`

如果后续进入正式删除阶段，必须先单独设计并开发上述 sample-delete
执行器，且不得复用分钟线 sample-delete 的资产白名单或 keep window。正式删除
执行器必须在单资产或小批次事务内工作，必须有 `--confirm-*` 显式确认参数，
并必须通过 pre/post dry-run 对账。

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

1. P0.1：治理矩阵与静态门禁，已完成。
2. P1：非分钟线 retention dry-run 工具、正式 Postgres 只读 dry-run 均已完成。
3. P2：Index Daily 与 Major Indices check 合并和 lake readiness 对账，已完成。
4. P3：Stock Daily / Suspend / Adj Factor check 合并和 lifecycle 口径收敛，已完成。
5. P4：Market Breadth / Return Distribution / Serving check 精简与 offline audit，已完成。
6. P5：Snapshot / Basic Facts check 合并，已完成。
7. P6：股票分钟线剩余普通 check 治理，已完成。
8. P7A：本地最终回归和静态审计。
9. P7B：正式非分钟线 retention dry-run 与必要的 sample-delete 工具设计。
10. P7C：正式 retention / 标准 vacuum / 文档对账。P7C 涉及正式 Dagster
    Postgres 写入，必须单独审批，且 active runs 必须为 0。

### 7.1 P7A 本地最终回归

状态：已完成本地验收。

P7A 只做本地代码和文档验收，不读取正式 Dagster instance，不写正式 DB，不触碰
正式 lake。

执行步骤：

1. `git status --short` 确认工作区只包含本专项文档或本地测试修复。
2. 静态审计正式 check names：
   - `LAKE_ASSET_CATALOG`
   - `tests/test_asset_check_incremental_governance.py`
   - `defs/sensors/readiness.py`
   - `defs/bootstrap/*_events.py`
3. 跑目标测试：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_asset_check_incremental_governance.py \
  tests/test_asset_check_event_retention.py \
  tests/test_run_contract_static_gates.py
```

4. 跑完整本地回归：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest tests
```

验收：

- `tests/test_asset_check_incremental_governance.py`
  `tests/test_asset_check_event_retention.py`
  `tests/test_run_contract_static_gates.py` 通过：`66 passed`。
- orchestrator 全量本地回归通过：`887 passed`。
- `adj_factor_raw_bootstrap_events.py` /
  `adj_factor_silver_bootstrap_events.py` 已从旧细粒度 runless check
  event 写入改为当前正式合并 check names；底层细粒度 audit 只保留为
  rule metadata，避免 bootstrap 补录后 readiness 仍按旧/新 check name
  不一致而误判。
- 新旧 check name 没有正式路径冲突。
- dry-run 工具仍无写路径。
- checks-only job 仍只选择 checks。

### 7.2 P7B 正式 dry-run 与删除执行器设计

状态：正式只读 dry-run 已完成并通过；sample-delete 执行器已完成代码和本地测试，尚未执行正式删除。

P7B 不直接删除。它先只读验证当前正式 Postgres 候选，只有 dry-run 安全报告通过后，
才允许开发非分钟线 sample-delete 执行器。

执行步骤：

1. 停止或确认 Dagster daemon/webserver 不会提交新 run。
2. 只读确认 `runs` 中没有 `QUEUED/STARTING/STARTED/CANCELING`。
3. 执行 P1 已有只读 dry-run：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . python -m orchestrator.defs.bootstrap.asset_check_event_retention_cli dry-run \
  --postgres-url postgresql://congming@localhost:5432/goldenshare_dagster \
  --output /private/tmp/asset_check_event_retention_dry_run_<timestamp>.json
```

4. 审计报告：
   - `should_stop=false`
   - active runs 为 0
   - protected checks 候选为 0
   - latest materialization collision 为 0
   - latest-bound check collision 为 0
   - keep window collision 为 0
   - `prod_ch_share_fact_market_breadth_daily`、`lake_root_health` 等排除资产不进入候选

2026-06-25 正式 dry-run 结果：

- 报告：`/private/tmp/asset_check_event_retention_dry_run_20260625_p7b.json`
- `should_stop=false`
- `running_or_queued_run_count=0`
- safety assertions 全部通过
- 候选：75,875 条 check execution / check event、42,310 条 materialization event、33,877 条 materialization event tags
- keep windows：`2026-05-27` 到 `2026-06-24`
- protected check 候选为空
- `prod_ch_share_fact_market_breadth_daily`、`lake_root_health` 仍按排除资产处理

5. 若需要正式删除，另行开发非分钟线 sample-delete：
   - 单资产或小批次白名单。
   - 单事务删除。
   - 删除前后都调用同一 dry-run 对账。
   - 不删除 `runs/run_tags/dynamic_partitions/instigators/planned events`。
   - 不删除 `partition is null` 且无 materialization 绑定的 check。

P7B 已落地的 sample-delete 执行器约束：

- 工具：`asset_check_event_retention_sample_delete_cli.py sample-delete`
- 必填参数：`--postgres-url`、`--sample-asset`、`--confirm-sample-delete`
- 仅允许单资产；多资产输入直接拒绝。
- 仅允许非分钟线 retention 白名单内且有 keep partition set 的资产；无分区 snapshot 资产直接拒绝。
- 正式执行仍属于 P7C，必须先备份、pre dry-run，再由用户单独批准。

### 7.3 P7C 正式 retention 与标准 vacuum

状态：P7C-A 小样本删除已完成并通过；更大范围 P7C-B 删除和标准 vacuum
仍待单独 review 与批准。

P7C 是正式 DB 写入阶段，不属于普通代码开发。每一批必须独立备份、pre
dry-run、删除、post dry-run，不允许跳过中间验收直接扩大范围。

正式删除前置：

1. 用户明确批准正式 Dagster Postgres 写入。
2. active runs 为 0。
3. 完整备份 Postgres，且 `pg_restore --list` 可读。
4. pre dry-run 报告通过。
5. sample-delete 小范围验证通过。
6. 删除安全前提必须逐资产成立：候选 event 删除不得影响该资产族后续自动触发、
   不得影响数据湖 Parquet 更新、不得破坏数据安全或恢复能力。若无法证明某个资产的
   sensor/readiness/update path 不依赖将被删除的旧历史 event，该资产不得进入正式删除。
7. 对每个待删除资产，pre dry-run 或专项审计必须明确说明：
   - 日常自动触发依赖的是 latest / keep window / dynamic partitions / lake 文件事实，
     还是依赖全历史 Dagster materialization/check event。
   - 若存在全历史 Dagster event 依赖，必须先改造触发/readiness 口径或将该资产排除。
   - 删除不会影响正式数据湖写入路径、run key、run config、partition set 或 source
     file selection。

删除后维护：

1. 只执行标准 `VACUUM (VERBOSE, ANALYZE)` / `ANALYZE`。
2. 不执行 `VACUUM FULL`、`REINDEX`、`pg_repack`，除非另开维护窗口并获得批准。
3. post dry-run 和 Asset UI 抽查通过后，才把 P7C 标记完成。

#### 2026-06-25 P7C-A 小样本执行结果

本批只处理 `gold_wealth_market_turnover`，用于验证非分钟线
sample-delete 执行器在正式 Dagster Postgres 上的事务删除、安全断言与
post dry-run 对账。

执行前置：

- active runs：0。
- 备份：
  `/private/tmp/goldenshare_dagster_asset_check_retention_p7ca_backup_20260625.dump`
- 备份大小：`364M`。
- `pg_restore --list`：通过。
- pre dry-run：
  `/private/tmp/asset_check_event_retention_p7ca_pre_dry_run_20260625.json`
- pre dry-run 结果：
  - `should_stop=false`
  - `running_or_queued_run_count=0`
  - safety assertions 全部通过
  - 全局候选：75,875 条 check execution / check event、42,310 条
    materialization event、33,877 条 materialization event tags
  - keep windows：`2026-05-27` 到 `2026-06-24`
  - `gold_wealth_market_turnover` 候选：1 条 check event / execution、1 条
    materialization event、0 条 event tags

正式删除：

- 工具：
  `asset_check_event_retention_sample_delete_cli.py sample-delete`
- 资产：`gold_wealth_market_turnover`
- 报告：
  `/private/tmp/asset_check_event_retention_p7ca_gold_wealth_market_turnover_delete_20260625.json`
- 事务结果：`committed=true`
- 删除量：
  - old check event tags：0
  - old `ASSET_CHECK_EVALUATION` event：1
  - old `asset_check_executions` row：1
  - old materialization event tags：0
  - old `ASSET_MATERIALIZATION` event：1
- 删除事务内 safety assertions 全部通过。

post dry-run：

- 报告：
  `/private/tmp/asset_check_event_retention_p7ca_post_dry_run_20260625.json`
- `should_stop=false`
- `running_or_queued_run_count=0`
- safety assertions 全部通过
- `gold_wealth_market_turnover` 候选归零
- 全局候选变为：75,874 条 check execution / check event、42,309 条
  materialization event、33,877 条 materialization event tags
- protected checks 仍为空候选；`prod_ch_share_fact_market_breadth_daily` 与
  `lake_root_health` 仍保持排除。

本批未执行：

- 未运行 `dg`、job、sensor、backfill、asset check 或 materialization。
- 未写数据湖 Parquet。
- 未删除 `runs`、`run_tags`、`dynamic_partitions`、`instigators` 或 planned
  events。
- 未执行 `VACUUM`、`VACUUM FULL`、`REINDEX`、`pg_repack`。

下一步：

- P7C-B 若继续推进，应先选择下一批小范围资产，重新做 active runs 确认、
  备份、pre dry-run，并单独获得正式删除批准。
- 标准 vacuum 只能在删除批次完成并通过 post dry-run 后单独执行。

#### 2026-06-25 P7C-B 第二个小样本执行结果

本批只处理 `raw_index_daily`，继续验证非分钟线 sample-delete 执行器在
另一个 partition set（`cn_a_index_trade_days`）上的 keep20/latest/protected
保护是否成立。本批不进入 `adj_factor` 大候选资产，也不执行标准 vacuum。

执行前置：

- active runs：0。
- 备份：
  `/private/tmp/goldenshare_dagster_asset_check_retention_p7cb_raw_index_daily_backup_20260625.dump`
- 备份大小：`364M`。
- `pg_restore --list`：通过。
- pre dry-run：
  `/private/tmp/asset_check_event_retention_p7cb_raw_index_daily_pre_dry_run_20260625.json`
- pre dry-run 结果：
  - `should_stop=false`
  - `running_or_queued_run_count=0`
  - safety assertions 全部通过
  - 全局候选：75,874 条 check execution / check event、42,309 条
    materialization event、33,877 条 materialization event tags
  - keep windows：`2026-05-27` 到 `2026-06-24`
  - `raw_index_daily` 候选：4 条 check event / execution、2 条
    materialization event、0 条 event tags
  - `raw_index_daily` latest partition：`2026-06-24`
  - `raw_index_daily` latest check count：2，全部 succeeded

正式删除：

- 工具：
  `asset_check_event_retention_sample_delete_cli.py sample-delete`
- 资产：`raw_index_daily`
- 报告：
  `/private/tmp/asset_check_event_retention_p7cb_raw_index_daily_delete_20260625.json`
- 事务结果：`committed=true`
- 删除量：
  - old check event tags：0
  - old `ASSET_CHECK_EVALUATION` event：4
  - old `asset_check_executions` row：4
  - old materialization event tags：0
  - old `ASSET_MATERIALIZATION` event：2
- 删除事务内 safety assertions 全部通过。

post dry-run：

- 报告：
  `/private/tmp/asset_check_event_retention_p7cb_raw_index_daily_post_dry_run_20260625.json`
- `should_stop=false`
- `running_or_queued_run_count=0`
- safety assertions 全部通过
- `raw_index_daily` 候选归零
- `gold_wealth_market_turnover` 候选保持归零
- 全局候选变为：75,870 条 check execution / check event、42,307 条
  materialization event、33,877 条 materialization event tags
- protected checks 仍为空候选；`prod_ch_share_fact_market_breadth_daily` 与
  `lake_root_health` 仍保持排除。

环境观察：

- P7C-B post dry-run 的表计数显示期间新增了 1 个 Dagster run。
- 只读审计确认该 run 为 `lake_root_health_check_job_schedule` 触发的
  `lake_root_health` 成功 run，run id 为
  `22e67865-e6ca-4cb5-9114-ab2f000aa55c`。
- `lake_root_health` 是 retention 排除资产；本批 safety assertions 仍全部通过，
  且 `raw_index_daily` latest/keep20/protected 均未被触碰。
- 但这说明当前环境并未完全冻结。后续任何更大范围删除前，必须先确保
  daemon/schedule/webserver 不会提交新 run；不能只依赖删除前瞬时 active
  runs 为 0。

本批未执行：

- 未运行 `dg`、业务 job、sensor、backfill、asset check 或 materialization。
- 未写数据湖 Parquet。
- 未删除 `runs`、`run_tags`、`dynamic_partitions`、`instigators` 或 planned
  events。
- 未执行 `VACUUM`、`VACUUM FULL`、`REINDEX`、`pg_repack`。

下一步：

- 暂停继续扩大 P7C 删除范围，直到确认 Dagster daemon/schedule/webserver 已完全停止
  或不会提交新 run。
- 下一批如果继续，应重新 active-runs 确认、重新备份、重新 pre dry-run，并单独获得
  正式删除批准。

#### 2026-06-25 P7C-C `gold_stock_return_distribution` 删除前安全审计

本节只记录删除前安全审计结论，尚未执行正式 DB 删除。由于 P7C-B 期间观察到
`lake_root_health_check_job_schedule` 新增 run，P7C-C 不能复用 P7C-B 的冻结状态；
若进入正式删除，必须重新确认 daemon/schedule/webserver 不会提交新 run，并重新执行
active-runs 检查、备份与 pre dry-run。

P7C-B post dry-run 中该资产候选：

- 资产：`gold_stock_return_distribution`
- family：`return_distribution`
- check event / execution 候选：0
- materialization 候选：3,011
- materialization event tag 候选：3,011
- latest materialization id：`6630459`
- latest partition：`2026-06-24`
- latest check count：6，latest non-succeeded check count：0
- keep partition set：`cn_a_stock_trade_days`
- keep20：`2026-05-27` 到 `2026-06-24`

代码审计结论：

- 日常自动触发入口是
  `stock_return_distribution_continuity_sensor`。它按
  `load_expected_trade_date_window(...)` 读取最近窗口 expected trade dates，
  通过 `build_registered_gap_status(...)` 检查 `cn_a_stock_trade_days` 注册缺口，
  再用 `batch_gold_stock_return_distribution_lake_readiness(...)` 从 lake 文件事实判断
  first-not-ready。它不读取 `gold_stock_return_distribution` 自身的全历史
  Dagster materialization/check event。
- 该 sensor 只有在 selected date 的 gold return distribution lake status 为
  `materialized=False` 时，才额外查询 selected date 的
  `stock_daily_ready_for_trade_date(...)`。这个上游门禁依赖的是
  `silver_stock_daily` 的目标日期状态，不依赖将被删除的
  `gold_stock_return_distribution` 旧历史 event。
- `batch_gold_stock_return_distribution_lake_readiness(...)` 只按 expected dates
  检查 `gold_stock_return_distribution_path(...)`、schema、row count、partition date、
  bucket sum 与 `silver_stock_daily_path(...)` 重算结果；不访问 Dagster instance、
  event log 或 check history。
- `gold_stock_return_distribution` asset 写入函数只读取 selected partition 的
  `silver_stock_daily_path(...)`，再写
  `gold_stock_return_distribution_path(...)`；不会读取自身旧 materialization/check event
  来决定 source file、run config、partition key 或写入范围。
- 下游 serving 入口 `clickhouse_market_breadth_continuity_sensor` 对
  `gold_stock_return_distribution` 的依赖同样通过
  `batch_gold_stock_return_distribution_lake_readiness(...)` 读取 lake 文件事实；
  `ch_share_fact_market_breadth_daily` 写入函数读取
  `gold_stock_return_distribution_path(...)`，不读取被删除的旧历史 event。

安全结论：

- 删除该资产 keep20 之外、latest state 之外的 old materialization event，不会改变
  `gold_stock_return_distribution` 的自动触发目标选择、run key、run config、
  partition set、source file selection 或 lake 写入路径。
- 删除该资产 old materialization event 不会影响
  `ch_share_fact_market_breadth_daily` 对它的上游 readiness 判断；下游仍以 lake 文件事实为准。
- 由于候选中 check event 为 0，本批不涉及删除该资产的历史 check event；若正式 pre dry-run
  出现 check 候选，必须重新审计后再决定。

正式执行前仍必须满足：

1. active runs 为 0，且确认 daemon/schedule/webserver 不会在执行期间提交新 run。
2. 对正式 Postgres 重新做完整备份，且 `pg_restore --list` 可读。
3. 重新执行 P7C-C pre dry-run；`should_stop=false`，安全断言全绿，候选仍只包含
   `gold_stock_return_distribution` 的 keep20/latest 之外 old state。
4. 获得用户对正式 DB 删除动作的单独批准。

本次审计未执行：

- 未删除 Dagster DB event。
- 未运行 `dg`、job、sensor、backfill、asset check 或 materialization。
- 未写数据湖 Parquet。
- 未执行 `VACUUM`、`VACUUM FULL`、`REINDEX`、`pg_repack`。

P7C-C 当前 preflight：

- 进程冻结检查：未发现 `dagster` / `dg dev` / `dagster-webserver` /
  `dagster-daemon` / `code-server` / `orchestrator` 匹配进程。
- active runs：0。
- pre dry-run：
  `/private/tmp/asset_check_event_retention_p7cc_gold_stock_return_distribution_pre_dry_run_20260625.json`
- pre dry-run 结果：
  - `should_stop=false`
  - `running_or_queued_run_count=0`
  - safety assertions 全部通过
  - `gold_stock_return_distribution` 候选仍为 0 条 check event / execution、3,011
    条 materialization event、3,011 条 materialization event tags
  - latest partition 仍为 `2026-06-24`，latest check count 仍为 6 且全部 succeeded
  - keep windows 仍为 `2026-05-27` 到 `2026-06-24`
- 备份：
  `/private/tmp/goldenshare_dagster_asset_check_retention_p7cc_gold_stock_return_distribution_backup_20260625.dump`
- 备份大小：`364M`。
- `pg_restore --list`：通过。

P7C-C 正式 sample-delete 已按上述范围执行完成：

- 工具：
  `asset_check_event_retention_sample_delete_cli.py sample-delete`
- 资产：`gold_stock_return_distribution`
- 报告：
  `/private/tmp/asset_check_event_retention_p7cc_gold_stock_return_distribution_delete_20260625.json`
- 事务结果：`committed=true`
- 删除量：
  - old check event tags：0
  - old `ASSET_CHECK_EVALUATION` event：0
  - old `asset_check_executions` row：0
  - old materialization event tags：3,011
  - old `ASSET_MATERIALIZATION` event：3,011
- 删除事务内 safety assertions 全部通过。

post dry-run：

- 报告：
  `/private/tmp/asset_check_event_retention_p7cc_gold_stock_return_distribution_post_dry_run_20260625.json`
- `should_stop=false`
- `running_or_queued_run_count=0`
- safety assertions 全部通过
- `gold_stock_return_distribution` 候选归零
- latest materialization id 仍为 `6630459`
- latest partition 仍为 `2026-06-24`
- latest check count 仍为 6，latest non-succeeded check count 仍为 0
- 全局候选变为：75,870 条 check execution / check event、39,296 条
  materialization event、30,866 条 materialization event tags

本批未执行：

- 未运行 `dg`、job、sensor、backfill、asset check 或 materialization。
- 未写数据湖 Parquet。
- 未删除 `runs`、`run_tags`、`dynamic_partitions`、`instigators` 或 planned
  events。
- 未执行 `VACUUM`、`VACUUM FULL`、`REINDEX`、`pg_repack`。

P7C-D 已在下一节单独审计、备份并执行；后续批次不得复用 P7C-C 的备份或
pre dry-run 作为依据。

#### 2026-06-25 P7C-D `gold_market_breadth_daily` 执行结果

P7C-D 选择 `gold_market_breadth_daily` 作为下一批小范围资产。选择原因是该资产
在 P7C-C post dry-run 中只剩 old materialization event 候选，check event 候选为 0；
同时它与已完成的 `gold_stock_return_distribution` 同属市场广度下游 serving 链路，
但自动触发与下游消费均已切换为 lake readiness，不依赖被删除的旧历史
materialization event。

P7C-C post dry-run 中该资产候选：

- 资产：`gold_market_breadth_daily`
- family：`market_breadth`
- check event / execution 候选：0
- materialization 候选：3,011
- materialization event tag 候选：3,011
- latest materialization id：`6630849`
- latest partition：`2026-06-24`
- latest check count：8，latest non-succeeded check count：0
- keep partition set：`cn_a_stock_trade_days`
- keep20：`2026-05-27` 到 `2026-06-24`

代码审计结论：

- 日常自动触发入口是 `market_breadth_continuity_sensor`。它按
  `load_expected_trade_date_window(...)` 读取 bounded expected trade dates，通过
  `build_registered_gap_status(...)` 检查 `cn_a_stock_trade_days` 注册缺口，再用
  `batch_gold_market_breadth_lake_readiness(...)` 从 lake 文件事实判断 first-not-ready。
  它不读取 `gold_market_breadth_daily` 自身的全历史 Dagster
  materialization/check event。
- 该 sensor 只有在 selected date 的 gold market breadth lake status 为
  `materialized=False` 时，才额外查询 selected date 的
  `stock_daily_ready_for_trade_date(...)`。这个上游门禁依赖 `silver_stock_daily`
  的目标日期状态，不依赖将被删除的 `gold_market_breadth_daily` 旧历史 event。
- `batch_gold_market_breadth_lake_readiness(...)` 只按 expected dates 检查
  `gold_market_breadth_daily_path(...)`、schema、row count、partition date、上涨/下跌
  计数、红盘率和值域，并用 `silver_stock_daily_path(...)` 重算对账；不访问 Dagster
  instance、event log 或 check history。
- `gold_market_breadth_daily` asset 写入函数只读取 selected partition 的
  `silver_stock_daily_path(...)`，再写 `gold_market_breadth_daily_path(...)`；
  不会读取自身旧 materialization/check event 来决定 source file、run config、
  partition key 或写入范围。
- 下游 serving 入口 `clickhouse_market_breadth_continuity_sensor` 对
  `gold_market_breadth_daily` 的依赖同样通过
  `batch_gold_market_breadth_lake_readiness(...)` 读取 lake 文件事实；
  `ch_share_fact_market_breadth_daily` 写入函数读取
  `gold_market_breadth_daily_path(...)`，不读取被删除的旧历史 event。

安全结论：

- 删除该资产 keep20 之外、latest state 之外的 old materialization event，不会改变
  `gold_market_breadth_daily` 的自动触发目标选择、run key、run config、partition set、
  source file selection 或 lake 写入路径。
- 删除该资产 old materialization event 不会影响
  `ch_share_fact_market_breadth_daily` 对它的上游 readiness 判断；下游仍以 lake 文件事实
  为准。
- 由于候选中 check event 为 0，本批不涉及删除该资产的历史 check event。

P7C-D preflight：

- 进程冻结检查：未发现 `dagster` / `dg dev` / `dagster-webserver` /
  `dagster-daemon` / `code-server` / `orchestrator` 匹配进程。
- active runs：0。
- pre dry-run：
  `/private/tmp/asset_check_event_retention_p7cd_gold_market_breadth_daily_pre_dry_run_20260625.json`
- pre dry-run 结果：
  - `should_stop=false`
  - `running_or_queued_run_count=0`
  - safety assertions 全部通过
  - `gold_market_breadth_daily` 候选仍为 0 条 check event / execution、3,011
    条 materialization event、3,011 条 materialization event tags
  - latest materialization id 仍为 `6630849`
  - latest partition 仍为 `2026-06-24`
  - latest check count 仍为 8，latest non-succeeded check count 仍为 0
  - keep windows 仍为 `2026-05-27` 到 `2026-06-24`
- 备份：
  `/private/tmp/goldenshare_dagster_asset_check_retention_p7cd_gold_market_breadth_daily_backup_20260625.dump`
- 备份大小：`363M`。
- `pg_restore --list`：通过。

P7C-D 正式 sample-delete 已按上述范围执行完成：

- 工具：
  `asset_check_event_retention_sample_delete_cli.py sample-delete`
- 资产：`gold_market_breadth_daily`
- 报告：
  `/private/tmp/asset_check_event_retention_p7cd_gold_market_breadth_daily_delete_20260625.json`
- 事务结果：`committed=true`
- 删除量：
  - old check event tags：0
  - old `ASSET_CHECK_EVALUATION` event：0
  - old `asset_check_executions` row：0
  - old materialization event tags：3,011
  - old `ASSET_MATERIALIZATION` event：3,011
- 删除事务内 safety assertions 全部通过。

post dry-run：

- 报告：
  `/private/tmp/asset_check_event_retention_p7cd_gold_market_breadth_daily_post_dry_run_20260625.json`
- `should_stop=false`
- `running_or_queued_run_count=0`
- safety assertions 全部通过
- `gold_market_breadth_daily` 候选归零
- latest materialization id 仍为 `6630849`
- latest partition 仍为 `2026-06-24`
- latest check count 仍为 8，latest non-succeeded check count 仍为 0
- 全局候选变为：75,870 条 check execution / check event、36,285 条
  materialization event、27,855 条 materialization event tags
- table counts：
  - `event_logs`：3,813,334
  - `asset_check_executions`：418,510
  - `asset_event_tags`：36,756
  - `dynamic_partitions`：30,572
  - `runs`：46,473
  - `run_tags`：316,447

本批未执行：

- 未运行 `dg`、job、sensor、backfill、asset check 或 materialization。
- 未写数据湖 Parquet。
- 未删除 `runs`、`run_tags`、`dynamic_partitions`、`instigators` 或 planned
  events。
- 未执行 `VACUUM`、`VACUUM FULL`、`REINDEX`、`pg_repack`。

P7C-E 已在下一节单独审计、备份并停在正式删除批准前；后续不得复用 P7C-D 的
备份或 pre dry-run 作为依据。

#### 2026-06-25 P7C-E `ch_share_fact_market_breadth_daily` 执行结果

P7C-E 选择 `ch_share_fact_market_breadth_daily` 作为下一批候选，是因为它是
`gold_market_breadth_daily` 与 `gold_stock_return_distribution` 下游本机 ClickHouse
serving 资产；P7C-D post dry-run 中该资产只剩 old materialization event 候选，
check event 候选为 0。该资产在完成删除前安全审计、pre dry-run、专属备份和
用户单独批准后，已执行正式 sample-delete。

P7C-D post dry-run 中该资产候选：

- 资产：`ch_share_fact_market_breadth_daily`
- family：`clickhouse_serving`
- check event / execution 候选：0
- materialization 候选：3,011
- materialization event tag 候选：3,011
- latest materialization id：`6630945`
- latest partition：`2026-06-24`
- latest check count：6，latest non-succeeded check count：0
- keep partition set：`cn_a_stock_trade_days`
- keep20：`2026-05-27` 到 `2026-06-24`

代码审计结论：

- 正式自动触发入口是 `clickhouse_market_breadth_continuity_sensor`。它按
  `load_expected_trade_date_window(...)` 读取 bounded expected trade dates，通过
  `build_registered_gap_status(...)` 检查 `cn_a_stock_trade_days` 注册缺口，再用
  `batch_clickhouse_market_breadth_readiness(...)` 从本机 ClickHouse 当前数据和
  lake gold 文件事实判断 first-not-ready。它不读取
  `ch_share_fact_market_breadth_daily` 自身的全历史 Dagster materialization/check event。
- 该 sensor 还会在同一窗口内调用
  `batch_gold_market_breadth_lake_readiness(...)` 与
  `batch_gold_stock_return_distribution_lake_readiness(...)` 作为上游门禁。两个上游
  readiness 都读取 lake 文件事实，不读取被删除的本机 ClickHouse serving 旧历史 event。
- `batch_clickhouse_market_breadth_readiness(...)` 一次读取目标窗口内的 ClickHouse
  分区行，再用 `gold_market_breadth_daily_path(...)` 和
  `gold_stock_return_distribution_path(...)` 计算期望行并做对账；不访问 Dagster
  instance、event log 或 check history。
- `ch_share_fact_market_breadth_daily` asset 写入函数只读取 selected partition 的
  `gold_market_breadth_daily_path(...)` 与
  `gold_stock_return_distribution_path(...)`，然后用同步 delete-then-insert 语义替换
  ClickHouse 单日分区；不会读取自身旧 materialization/check event 来决定 source file、
  run config、partition key 或写入范围。
- 下游 `prod_ch_share_fact_market_breadth_daily` 的显式 bounded sensor 以本机
  ClickHouse serving 当前行和 lake-derived readiness 作为上游门禁，不依赖
  `ch_share_fact_market_breadth_daily` 的全历史 old materialization event。

安全结论：

- 删除该资产 keep20 之外、latest state 之外的 old materialization event，不会改变
  `ch_share_fact_market_breadth_daily` 的自动触发目标选择、run key、run config、
  partition set、source file selection、ClickHouse 写入路径或下游 prod sync 门禁。
- 删除该资产 old materialization event 不会影响本机 ClickHouse serving 当前数据；
  数据事实仍在 ClickHouse 表与上游 lake gold parquet 中。
- 由于候选中 check event 为 0，本批不涉及删除该资产的历史 check event。

P7C-E preflight：

- 进程冻结检查：未发现 `dagster` / `dg dev` / `dagster-webserver` /
  `dagster-daemon` / `code-server` / `orchestrator` 匹配进程。
- active runs：0。
- pre dry-run：
  `/private/tmp/asset_check_event_retention_p7ce_ch_share_fact_market_breadth_daily_pre_dry_run_20260625.json`
- pre dry-run 结果：
  - `should_stop=false`
  - `running_or_queued_run_count=0`
  - safety assertions 全部通过
  - `ch_share_fact_market_breadth_daily` 候选仍为 0 条 check event / execution、
    3,011 条 materialization event、3,011 条 materialization event tags
  - latest materialization id 仍为 `6630945`
  - latest partition 仍为 `2026-06-24`
  - latest check count 仍为 6，latest non-succeeded check count 仍为 0
  - keep windows 仍为 `2026-05-27` 到 `2026-06-24`
- 备份：
  `/private/tmp/goldenshare_dagster_asset_check_retention_p7ce_ch_share_fact_market_breadth_daily_backup_20260625.dump`
- 备份大小：`362M`。
- `pg_restore --list`：通过。

P7C-E 正式 sample-delete 已按上述范围执行完成：

- 工具：
  `asset_check_event_retention_sample_delete_cli.py sample-delete`
- 资产：`ch_share_fact_market_breadth_daily`
- 报告：
  `/private/tmp/asset_check_event_retention_p7ce_ch_share_fact_market_breadth_daily_delete_20260625.json`
- 事务结果：`committed=true`
- 删除量：
  - old check event tags：0
  - old `ASSET_CHECK_EVALUATION` event：0
  - old `asset_check_executions` row：0
  - old materialization event tags：3,011
  - old `ASSET_MATERIALIZATION` event：3,011
- 删除事务内 safety assertions 全部通过。

post dry-run：

- 报告：
  `/private/tmp/asset_check_event_retention_p7ce_ch_share_fact_market_breadth_daily_post_dry_run_20260625.json`
- `should_stop=false`
- `running_or_queued_run_count=0`
- safety assertions 全部通过
- `ch_share_fact_market_breadth_daily` 候选归零
- latest materialization id 仍为 `6630945`
- latest partition 仍为 `2026-06-24`
- latest check count 仍为 6，latest non-succeeded check count 仍为 0
- 全局候选变为：75,870 条 check execution / check event、33,274 条
  materialization event、24,844 条 materialization event tags
- table counts：
  - `event_logs`：3,810,491
  - `asset_check_executions`：418,510
  - `asset_event_tags`：33,757
  - `dynamic_partitions`：30,572
  - `runs`：46,485
  - `run_tags`：316,459

环境观察：

- P7C-E pre dry-run 与 post dry-run 之间，正式 Dagster DB 新增了 12 个成功
  `__ASSET_JOB` run。
- 只读审计确认这 12 个 run 均 materialize `prod_core_wealth_market_turnover`，
  partitions 为 `2026-06-05`、`2026-06-08`、`2026-06-09`、`2026-06-10`、
  `2026-06-11`、`2026-06-12`、`2026-06-15`、`2026-06-16`、`2026-06-17`、
  `2026-06-18`、`2026-06-22`、`2026-06-23`。
- 这些新增 run 与本批删除资产无关；P7C-E 删除事务和 post dry-run 的 safety
  assertions 均通过，`ch_share_fact_market_breadth_daily` latest/keep20/protected
  状态未被触碰。
- 但这再次说明当前环境不能仅凭历史 preflight 认定长期静止；P7C-F 若继续推进，
  必须重新确认 active runs 为 0，并要求执行窗口内不再有其它 Dagster 写入活动。

本批未执行：

- 未删除本批范围外 Dagster DB event。
- 未删除任何 `ASSET_CHECK_EVALUATION` event 或 `asset_check_executions` row。
- 未运行 `dg`、job、sensor、backfill、asset check 或 materialization。
- 未写数据湖 Parquet。
- 未删除 `runs`、`run_tags`、`dynamic_partitions`、`instigators` 或 planned
  events。
- 未执行 `VACUUM`、`VACUUM FULL`、`REINDEX`、`pg_repack`。

#### 2026-06-25 P7C-F `gold_market_major_indices_daily` 执行结果

P7C-F 选择 `gold_market_major_indices_daily` 作为下一批候选，是因为它在
P7C-E post dry-run 后只剩 old materialization event 候选，check event 候选为 0；
同时它是主要指数 gold 资产，正式 sensor 已完成 bounded continuity / lake-derived
readiness 改造。该资产在完成删除前安全审计、pre dry-run、专属备份和用户单独批准后，
已执行正式 sample-delete。

P7C-E post dry-run 中该资产候选：

- 资产：`gold_market_major_indices_daily`
- family：`major_indices`
- check event / execution 候选：0
- materialization 候选：6,393
- materialization event tag 候选：6,393
- latest materialization id：`6631768`
- latest partition：`2026-06-24`
- latest check count：10，latest non-succeeded check count：0
- keep partition set：`cn_a_index_trade_days`
- keep20：`2026-05-27` 到 `2026-06-24`

代码审计结论：

- 正式自动触发入口是 `market_major_indices_daily_sensor`。它读取
  `cn_a_index_trade_days` / `cn_a_index_ts_codes` dynamic partitions，并通过
  `load_expected_trade_date_window(...)` 构造 bounded expected index date window；
  缺注册日期时先停在 `build_registered_gap_status(...)`，不会越过缺口。
- 无注册缺口后，sensor 使用 `batch_market_major_indices_lake_readiness(...)`
  计算 `gold_market_major_indices_daily` 的 lake-derived readiness，再用
  `select_first_not_ready_trade_date(...)` 选择 first not-ready。这个判断基于 lake
  文件事实与 seed / index code 门禁，不读取该资产的全历史 Dagster materialization
  event。
- selected date 上，sensor 只额外检查 `silver_index_daily_lake_readiness_for_trade_date(...)`、
  `silver_index_basic_lake_readiness(...)` 和
  `check_market_major_indices_inputs_for_trade_date(...)`。这些门禁读取 lake 文件事实、
  seed 与 dynamic partitions，不依赖 `gold_market_major_indices_daily` 旧历史 event。
- `gold_market_major_indices_daily` asset 写入函数按 selected partition 读取
  `silver_index_daily_path(...)`，校验 seed 覆盖后写
  `gold_market_major_indices_daily_path(...)`；不从自身历史 materialization/check event
  推导 source file、partition key、run config 或写入范围。
- 下游 serving 链路通过 `ch_share_fact_market_breadth_daily` 读取
  `gold_market_breadth_daily_path(...)` 与
  `gold_stock_return_distribution_path(...)`；本批不涉及下游 source file 事实。

安全结论：

- 删除该资产 keep20 之外、latest state 之外的 old materialization event，不会改变
  `market_major_indices_daily_sensor` 的目标选择、run key、run config、partition set、
  source file selection 或 lake 写入路径。
- 删除该资产 old materialization event 不会删除 lake Parquet，也不会影响主要指数 gold
  当前文件事实；后续更新仍以 dynamic partitions、expected window 和 lake-derived
  readiness 为准。
- 由于候选中 check event 为 0，本批不涉及删除该资产的历史 check event。

P7C-F preflight：

- 进程冻结检查：未发现 `dagster` / `dg dev` / `dagster-webserver` /
  `dagster-daemon` / `code-server` / `orchestrator` 匹配进程。
- active runs：0。
- pre dry-run：
  `/private/tmp/asset_check_event_retention_p7cf_gold_market_major_indices_daily_pre_dry_run_20260625.json`
- pre dry-run 结果：
  - `should_stop=false`
  - `running_or_queued_run_count=0`
  - safety assertions 全部通过
  - `gold_market_major_indices_daily` 候选仍为 0 条 check event / execution、
    6,393 条 materialization event、6,393 条 materialization event tags
  - latest materialization id 仍为 `6631768`
  - latest partition 仍为 `2026-06-24`
  - latest check count 仍为 10，latest non-succeeded check count 仍为 0
  - keep windows 仍为 `2026-05-27` 到 `2026-06-24`
- 备份：
  `/private/tmp/goldenshare_dagster_asset_check_retention_p7cf_gold_market_major_indices_daily_backup_20260625.dump`
- 备份大小：`361M`。
- `pg_restore --list`：通过。

正式删除前追加确认：

- 进程冻结检查：未发现 `dagster` / `dg dev` / `dagster-webserver` /
  `dagster-daemon` / `code-server` / `orchestrator` 匹配进程。
- active runs：0。
- pre-delete dry-run：
  `/private/tmp/asset_check_event_retention_p7cf_gold_market_major_indices_daily_pre_delete_dry_run_20260625.json`
- pre-delete dry-run 结果：
  - `should_stop=false`
  - `running_or_queued_run_count=0`
  - safety assertions 全部通过
  - `gold_market_major_indices_daily` 候选仍为 0 条 check event / execution、
    6,393 条 materialization event、6,393 条 materialization event tags
  - latest materialization id 仍为 `6631768`
  - latest partition 仍为 `2026-06-24`
  - latest check count 仍为 10，latest non-succeeded check count 仍为 0
- 写入前 active runs 复查：0。

P7C-F 正式 sample-delete 已按上述范围执行完成：

- 工具：
  `asset_check_event_retention_sample_delete_cli.py sample-delete`
- 资产：`gold_market_major_indices_daily`
- 报告：
  `/private/tmp/asset_check_event_retention_p7cf_gold_market_major_indices_daily_delete_20260625.json`
- 事务结果：`committed=true`
- 删除量：
  - old check event tags：0
  - old `ASSET_CHECK_EVALUATION` event：0
  - old `asset_check_executions` row：0
  - old materialization event tags：6,393
  - old `ASSET_MATERIALIZATION` event：6,393
- 删除事务内 safety assertions 全部通过。

post dry-run：

- 报告：
  `/private/tmp/asset_check_event_retention_p7cf_gold_market_major_indices_daily_post_dry_run_20260625.json`
- `should_stop=false`
- `running_or_queued_run_count=0`
- safety assertions 全部通过
- `gold_market_major_indices_daily` 候选归零
- latest materialization id 仍为 `6631768`
- latest partition 仍为 `2026-06-24`
- latest check count 仍为 10，latest non-succeeded check count 仍为 0
- 全局候选变为：75,870 条 check execution / check event、26,881 条
  materialization event、18,451 条 materialization event tags
- table counts：
  - `event_logs`：3,804,098
  - `asset_check_executions`：418,510
  - `asset_event_tags`：27,364
  - `dynamic_partitions`：30,572
  - `runs`：46,485
  - `run_tags`：316,459

本批未执行：

- 未删除本批范围外 Dagster DB event。
- 未删除任何 `ASSET_CHECK_EVALUATION` event 或 `asset_check_executions` row。
- 未运行 `dg`、job、sensor、backfill、asset check 或 materialization。
- 未写数据湖 Parquet。
- 未删除 `runs`、`run_tags`、`dynamic_partitions`、`instigators` 或 planned
  events。
- 未执行 `VACUUM`、`VACUUM FULL`、`REINDEX`、`pg_repack`。

P7C-F 到此收口。下一批候选不得复用 P7C-F 的备份、pre dry-run 或 post dry-run
作为依据；若继续推进，必须重新选择资产、重新确认 active runs 为 0、重新备份、
重新 pre dry-run，并单独获得正式删除批准。

## 8. Stop Conditions

以下情况必须停止：

- 无法证明某个 check 是否参与 sensor/readiness。
- 无法证明候选 event 删除不会影响自动触发、数据湖更新或数据安全。
- 待删除资产的 sensor/readiness/update path 仍依赖将被删除的全历史 Dagster
  materialization/check event。
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
