---
name: lake-dataset-onboarding
description: Use for Goldenshare Lake Console, Sync Center, Dagster lake assets, DuckDB, Parquet, full-market sync, historical backfill, lake data writes, lake dataset onboarding, and performance-sensitive lake work. 适用于 Lake Console、数据湖、同步、导出、全市场、历史批量和性能门禁任务。
---

# Lake Dataset Onboarding

Use this skill for Lake Console and new lake asset work.

## Required Context

1. Read `lake_console/AGENTS.md`.
2. If the task touches Dagster, assets, checks, sensors, jobs, resources, partitions, or new lake topology, also read `lake_console/orchestrator/AGENTS.md`.
3. Read the relevant design document before implementation. If no design exists for a high-risk lake change, stop and ask for a design decision.

## Performance Gate

Before coding, write a performance measurement table covering:

1. object count, date count, partition count, enum expansion count
2. request count, page count, expected source rows, expected written rows, expected files
3. DuckDB scan, join, write volume, spill risk, temp directory
4. commit or atomic replace granularity and retry cost
5. estimated duration, disk space, Tushare or database quota impact
6. unacceptable threshold, rejection strategy, dry-run or sample validation method

If the scale cannot be measured, has no real sample, has no upper bound, or exceeds the threshold, stop and redesign before coding.

## Implementation Rules

1. Default to dry-run, small sample, or aggregate audit before full execution.
2. Use DuckDB SQL, `COPY ... TO parquet`, or equivalent columnar/vectorized execution for large Parquet compute and writes.
3. Keep Python on large paths limited to orchestration, validation, path discovery, batch planning, sampling, and summaries.
4. Use `_tmp -> validate -> atomic replace` for writes.
5. For historical audits, prefer set differences and aggregate counts. Do not deep-scan every partition when partition count exceeds 100 or `partition_count * blocking_check_count` exceeds 1000.
6. For full snapshot or shared assets, document unique writer, repeat trigger behavior, and concurrency protection.

## Delivery Gate

Report the performance table, sample or dry-run result, whether the rejection strategy fired, whether full execution was entered, changed files, validation, and residual manual checks.

