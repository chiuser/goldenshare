# Goldenshare Local Lake Console

> M5 清退边界（2026-09-05）：本目录仍包含待 M6 原子删除的旧 Console frontend/backend，下面旧启动/配置章节暂留为冻结实现说明，不是当前 DG 操作指引，禁止运行 Kopia。现行开发从 [orchestrator](orchestrator/README.md)、[正式接入模板](docs/templates/dagster-dataset-onboarding-template.html) 和 [性能规范](docs/design/dagster-data-pipeline-performance-governance.md) 进入；保留 reports 与 ClickHouse 工具，不动物理数据。

`lake_console` is a local-only console for managing Tushare Parquet data on a removable disk.

It is intentionally isolated from the production Goldenshare app:

- It does not write the remote `goldenshare-db`.
- It only reads the remote `goldenshare-db` for explicit `prod-raw-db`
  commands, and those commands are limited to whitelisted `raw_tushare`
  tables and field projections.
- It does not use production Ops TaskRun, scheduler, worker, or status snapshots.
- It does not mount routes into `src/app/web`.
- It does not import production frontend code.

## Required Environment

Local config file is preferred to avoid polluting other Goldenshare environments:

```bash
cp lake_console/config.local.example.toml lake_console/config.local.toml
```

Then fill:

```toml
lake_root = "/Volumes/TushareData/goldenshare-tushare-lake"
tushare_token = "..."
```

`lake_console/config.local.toml` is ignored by git and must not be committed.

Optional prod raw export commands require a read-only database URL:

```toml
prod_raw_db_url = "postgresql://readonly-user:...@host:5432/goldenshare"
```

`index_daily` 是当前唯一的 `prod-core-db` 例外项，需要额外配置一个只读 core URL。通常它与 `prod_raw_db_url` 指向同一库，但语义上单独命名，便于门禁和审查：

```toml
prod_core_db_url = "postgresql://readonly-user:...@host:5432/goldenshare"
```

Recovery 页面通过 backend 调用 `kopia` CLI 读取 snapshot inventory。若要让页面非交互显示 Kopia 数据，需要补齐 Kopia 配置路径；若 repository 密码没有持久保存在 Keychain，还需要补 `kopia_password`：

```toml
kopia_config_path = "/Users/your-name/Library/Application Support/kopia/repository.config"
kopia_password = "..."
```

Environment variables are still supported and override `config.local.toml`:

```bash
export GOLDENSHARE_LAKE_ROOT=/Volumes/TushareData/goldenshare-tushare-lake
export TUSHARE_TOKEN=...
export GOLDENSHARE_PROD_RAW_DB_URL=postgresql://readonly-user:...@host:5432/goldenshare
export KOPIA_CONFIG_PATH="$HOME/Library/Application Support/kopia/repository.config"
export KOPIA_PASSWORD=...
```

The local Tushare client is rate-limited globally. The default is 500 requests per minute:

```toml
tushare_request_limit_per_minute = 500
```

Minute range sync requests one symbol/frequency per date window, then writes rows
back to daily partitions. The default window is roughly one natural month:

```toml
stk_mins_request_window_days = 31
```

## Local Backend

Install local backend dependencies:

```bash
python3 -m pip install -r lake_console/backend/requirements.txt
```

Optional short command setup:

```bash
export PATH="$PWD/lake_console/bin:$PATH"
lake-console --help
```

Run health API:

```bash
python3 -m lake_console.backend.app.main
```

Run stock basic sync:

```bash
lake-console sync-stock-basic
```

Run trade calendar sync:

```bash
lake-console sync-trade-cal
```

Run trade calendar sync for an explicit range:

```bash
lake-console sync-trade-cal \
  --start-date 2026-04-01 \
  --end-date 2026-04-30
```

Run single-symbol minute sync:

```bash
lake-console sync-stk-mins \
  --ts-code 600000.SH \
  --freq 30 \
  --trade-date 2026-04-24
```

Run all-market minute sync from the local stock universe:

```bash
lake-console sync-stk-mins \
  --all-market \
  --freqs 1,5,15,30,60 \
  --trade-date 2026-04-24
```

Run all-market minute sync by local open trading days:

```bash
lake-console sync-stk-mins-range \
  --all-market \
  --freqs 1,5,15,30,60 \
  --start-date 2026-04-01 \
  --end-date 2026-04-30
```

This command downloads by `ts_code + freq + date window`, paginates each Tushare
request, then writes the returned rows into `freq=*/trade_date=*` Parquet
partitions. The terminal progress bar shows the current window, symbol, freq,
page and offset without printing one line per request.

Run single-symbol minute range sync, for example when backfilling an old code
after a security code switch:

```bash
lake-console sync-stk-mins-range \
  --ts-code 300114.SZ \
  --freqs 1,5,15,30,60 \
  --start-date 2010-08-27 \
  --end-date 2025-02-16
```

Single-symbol range sync also uses freq-based date windows. It merges rows by
`ts_code` inside each `freq/trade_date` partition, so it does not remove other
symbols already present in the same partition.

Preview and export `daily` from the production raw table instead of Tushare:

```bash
lake-console plan-sync daily --from prod-raw-db --trade-date 2026-04-24
lake-console sync-dataset daily --from prod-raw-db --trade-date 2026-04-24
```

R2 首批日频样例：

```bash
lake-console sync-dataset adj_factor --from prod-raw-db --trade-date 2026-04-30
lake-console sync-dataset daily_basic --from prod-raw-db --trade-date 2026-04-30
lake-console sync-dataset index_daily_basic --from prod-raw-db --trade-date 2026-04-30
lake-console sync-dataset index_daily --from prod-core-db --trade-date 2026-04-30
```

Range export uses the local trading calendar and exports one open day at a time:

```bash
lake-console sync-dataset daily \
  --from prod-raw-db \
  --start-date 2026-04-01 \
  --end-date 2026-04-30
```

The legacy backend commands that generated 90/120 minute bars were removed on
2026-08-07. Formal 90/120 minute bars are written only by the Dagster
orchestrator under the shared auction-anchor contract; do not recreate a local
backend writer.

Rebuild the research layout for long single-symbol or small-basket queries:

```bash
lake-console rebuild-stk-mins-research \
  --freq 30 \
  --trade-month 2026-04
```

Rebuild the research layout for a historical month range and multiple freqs:

```bash
lake-console rebuild-stk-mins-research-range \
  --start-month 2024-01 \
  --end-month 2026-04 \
  --freqs 1,5,15,30,60,90,120
```

Start the local backend and frontend together:

```bash
bash scripts/local-lake-console.sh
```

Inspect and clean temporary write directories:

```bash
lake-console clean-tmp --dry-run
lake-console clean-tmp --older-than-hours 24
```

## Data Layout

Official stock basic dataset:

```text
raw_tushare/stock_basic/current/part-000.parquet
```

Local stock universe for execution:

```text
manifest/security_universe/tushare_stock_basic.parquet
```

Local trading calendar for range sync:

```text
manifest/trading_calendar/tushare_trade_cal.parquet
```

Minute bars by date:

```text
raw_tushare/stk_mins_by_date/freq=*/trade_date=*/*.parquet
```
