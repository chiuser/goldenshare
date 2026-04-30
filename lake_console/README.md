# Goldenshare Local Lake Console

`lake_console` is a local-only console for managing Tushare Parquet data on a removable disk.

It is intentionally isolated from the production Goldenshare app:

- It does not read or write the remote `goldenshare-db`.
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

Environment variables are still supported and override `config.local.toml`:

```bash
export GOLDENSHARE_LAKE_ROOT=/Volumes/TushareData/goldenshare-tushare-lake
export TUSHARE_TOKEN=...
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

Generate local 90/120 minute derived bars from existing 30/60 minute by-date partitions:

```bash
lake-console derive-stk-mins \
  --trade-date 2026-04-24 \
  --targets 90,120
```

Rebuild the research layout for long single-symbol or small-basket queries:

```bash
lake-console rebuild-stk-mins-research \
  --freq 30 \
  --trade-month 2026-04
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

Minute bars by date:

```text
raw_tushare/stk_mins_by_date/freq=*/trade_date=*/*.parquet
```
