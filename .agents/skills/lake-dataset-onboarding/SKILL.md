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
4. For formal dataset onboarding, use `lake_console/docs/templates/dagster-dataset-onboarding-template.html`, including section 7A, and `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`. Retired Console templates are not development references.

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
4. Use run-scoped candidates under `/Volumes/datasource/data_lake_staging`, full candidate validation, same-filesystem per-file atomic replace and checkpoints for safe resume. Never use the old lake or Kopia. Preserve current Raw/Silver contracts; do not impose blanket field inheritance.
5. For historical audits, prefer set differences and aggregate counts. Do not deep-scan every partition when partition count exceeds 100 or `partition_count * blocking_check_count` exceeds 1000.
6. For full snapshot or shared assets, document unique writer, repeat trigger behavior, and concurrency protection.

## Direct Lake Bootstrap + Runless Event Backfill

Use this pattern, also called `直写补录模式`, for historical lake initialization or large migration when Dagster backfill would be too slow or too fragmented.

Definition:

- First write or migrate the physical lake Parquet files with a controlled helper or CLI.
- Then report runless asset materialization and asset check events so Dagster UI/readiness recognizes those file facts.
- This is not a Dagster backfill and must not replace the daily asset job / sensor path.

Required plan shape:

1. State why direct write is allowed instead of Dagster backfill.
2. List affected assets, partitions, expected files, expected rows, expected runless events, and target paths.
3. Split execution into file generation and event backfill.
4. For each stage, provide dry-run, sample, full/batched execution, final audit, and rollback or correction posture.
5. Use aggregate audits and batch dimensions such as `freq/year`, date range, or asset group. Avoid per-partition deep loops when the operation is large.

File generation stage:

1. Dry-run: inspect source files, target conflicts, selected partitions, expected row counts, expected output files, and disk space.
2. Sample: write a tiny approved sample, then audit schema, row counts, partition values, key uniqueness, and representative data.
3. Full/batched write: process stable batches. Prefer DuckDB SQL / `COPY ... TO parquet`; Python may only plan batches and summarize results.
4. Final file audit: compare source/target partition sets, file counts, row counts, schema, and failure samples. Stop before event backfill if any file check fails.

Runless event backfill stage:

1. Dry-run: count existing materializations/checks, expected new events, missing files, failed checks, and already-ready partitions.
2. Sample: report materialization/check events for a few partitions and verify sample readiness.
3. Full/batched report: write only green materialization/check facts. If a batch fails a check, stop and fix file facts before continuing.
4. Final audit: use aggregate event counts and a small readiness sample. Do not use full per-partition readiness as the primary audit for large histories.

Hard prohibitions:

- Do not use this mode for daily incremental production.
- Do not report green events for files that have not passed the same blocking check semantics as the formal asset.
- Do not write large Parquet data with Python row loops or `executemany`-style row insertion.
- Do not perform database-level deletion rollback of runless events by default; if correction is needed, design it separately.
- Do not describe this mode as Dagster backfill in docs or runbooks.

## Delivery Gate

Report the performance table, sample or dry-run result, whether the rejection strategy fired, whether full execution was entered, changed files, validation, and residual manual checks.
