# Local Lake DuckDB Compute M0.5 基线样本 Benchmark 报告

日期：2026-05-16

关联方案：

- [Local Lake DuckDB 计算执行壳与受控发布方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-large-compute-foundation-design-v1.html)
- [stk_mins clean_next 前复权候选层重建与两阶段发布方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-clean-next-qfq-candidate-publish-plan-v1.html)

## 1. 本轮目标

本轮只做 M0.5：

1. 把 DuckDB 大计算相关配置接入 `lake_console/config.local.toml` 配置模型与 `config.local.example.toml`。
2. 增加只读 benchmark 命令，验证 DuckDB 能读取 `clean_next`、`adj_factor`、`security_identity_map` 并执行 qfq 风格 join。
3. 用 2026-03 样本月跑一次真实 Lake 只读 benchmark，记录吞吐、因子覆盖与风险。

本轮不做：

1. 不生成 qfq candidate。
2. 不替换 `research/stk_mins_by_date_clean_next`。
3. 不更新 gate、queue、derived、by-month、indicator。
4. 不改正式数据。

## 2. 已接入配置

新增配置字段：

```toml
duckdb_threads = 4
duckdb_memory_limit = "24GB"
duckdb_temp_directory = "_tmp/duckdb"
compute_bucket_count = 32
compute_max_active_writers = 1
compute_progress_interval_seconds = 2
compute_stale_heartbeat_seconds = 1800
compute_max_unit_retries = 1
```

说明：

- 这些字段是 DuckDB 大计算执行壳的配置事实源。
- 默认值已进入 `LakeConsoleSettings` 和 `lake_console/config.local.example.toml`。
- `duckdb_temp_directory` 必须位于 Lake Root 内，避免 DuckDB spill 写到本机系统盘。

## 3. 新增只读命令

命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli benchmark-duckdb-compute \
  --sample-month 2026-03 \
  --freqs 1,5,15,30,60
```

命令行为：

1. 读取 `research/stk_mins_by_date_clean_next/freq=*/trade_date=2026-03-*`。
2. 读取 `raw_tushare/adj_factor/trade_date=2026-03-*`。
3. 读取最新一日 `raw_tushare/adj_factor` 作为最新复权因子。
4. 读取 `manifest/security_identity/security_identity_map.parquet`。
5. 在 DuckDB 内执行 qfq 风格 join 和 checksum。
6. 输出 JSON benchmark 结果。

这个命令是只读命令。除 DuckDB 可能使用 `lake_root/_tmp/duckdb` 作为临时目录外，不写任何正式数据路径。

## 4. 真实样本结果

样本：

```text
sample_month = 2026-03
freqs = 1,5,15,30,60
duckdb_threads = 4
duckdb_memory_limit = 24GB
```

### 4.1 首次 benchmark

```text
clean_file_count = 110
clean_total_bytes = 652,172,917
adj_factor_file_count = 22
adj_factor_total_bytes = 1,174,910
row_count = 38,713,994
security_count = 5,493
elapsed_seconds = 0.589
rows_per_second = 65,722,122.23
identity_row_count = 6,089
identity_count = 5,837
identity_source_code_count = 6,089
missing_adj_factor_rows = 1,605
missing_latest_adj_factor_rows = 0
non_positive_factor_rows = 0
```

单频 `freq=30` 样本：

```text
row_count = 1,085,436
elapsed_seconds = 0.230
rows_per_second = 4,712,690.03
missing_adj_factor_rows = 45
missing_latest_adj_factor_rows = 0
non_positive_factor_rows = 0
```

首次 benchmark 暴露出 2026-03 样本月存在上市日当日 `adj_factor` 缺失。

缺失明细：

```text
920188.BJ 2026-03-30 freq=1/5/15/30/60
001257.SZ 2026-03-31 freq=1/5/15/30/60
688813.SH 2026-03-31 freq=1/5/15/30/60
920055.BJ 2026-03-31 freq=1/5/15/30/60
920188.BJ 2026-03-31 freq=1/5/15/30/60
```

### 4.2 缺口复核与修正

复核结论：

1. Tushare 源站当前存在上述新股上市日或次日的 `adj_factor`，因子值为 `1.0`。
2. 远程 prod DB 与本地 Lake 当时都缺少这些行，因此不是 DuckDB benchmark 读取口径问题。
3. 本地 Lake 已重新从 Tushare 源补齐 `raw_tushare/adj_factor` 对应分区。

补齐后，本地 Lake 分区行数：

```text
2026-03-30 rows = 5,496
2026-03-31 rows = 5,499
2026-04-01 rows = 5,500
```

### 4.3 复跑 benchmark

```text
clean_file_count = 110
clean_total_bytes = 652,172,917
adj_factor_file_count = 22
adj_factor_total_bytes = 1,174,872
row_count = 38,713,994
security_count = 5,493
elapsed_seconds = 0.754
rows_per_second = 51,341,607.99
identity_row_count = 6,089
identity_count = 5,837
identity_source_code_count = 6,089
missing_adj_factor_rows = 0
missing_latest_adj_factor_rows = 0
non_positive_factor_rows = 0
qfq_close_checksum = 1,098,611,244.2048426
```

## 5. M0.5 结论

M0.5 当前结论：通过。

依据：

1. DuckDB 能读取 `clean_next`、`adj_factor`、`security_identity_map` 并完成 qfq 风格 join。
2. 2026-03 样本月全频率 benchmark 中，`missing_adj_factor_rows = 0`。
3. `missing_latest_adj_factor_rows = 0`。
4. `non_positive_factor_rows = 0`。
5. 样本吞吐显示核心计算本身不是当前瓶颈。

## 6. 对主线的影响

1. DuckDB 计算能力本身可用，样本吞吐没有显示性能阻塞。
2. 配置入口已具备进入 M1 的基础。
3. qfq 正式计算仍必须保留 `adj_factor` 覆盖门禁；任何缺失、重复或非正数因子都不能静默 fallback。

## 7. 下一步

进入 M1：实现大计算执行壳模型与 dry-run，不生成 qfq candidate，不替换正式 `clean_next`。
