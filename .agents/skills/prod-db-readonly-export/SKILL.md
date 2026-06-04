---
name: prod-db-readonly-export
description: Use for Goldenshare production database read-only audits, prod-raw-db or prod-core-db exports, remote DB sampling, table size checks, whitelist validation, and bounded SQL verification. 适用于生产库只读审计、远程 DB 样本核验、prod-db 导出和白名单字段投影。
---

# Prod DB Readonly Export

Use this skill for any task that reads production or remote database data.

## Execution Rule

Do not repeatedly test network or database access inside the sandbox. Use the local command line and approved command prefixes when the task requires DB, SSH, localhost services, or network access. If approval is required, request it directly with a clear read-only purpose.

## Required Read-Only Plan

Before running a DB command, state:

1. target environment and connection path
2. whitelist schema and table
3. field projection
4. filters, partition key, date range, or limit
5. expected row count or estimation method
6. batch size when exporting
7. output path if a report is produced
8. reason this is read-only and bounded

## Hard Blocks

1. No write SQL, DDL, migrations, truncate, delete, update, insert, vacuum full, or reindex.
2. No unbounded `select *`.
3. No secret values in commands, docs, code, logs, reports, or metadata.
4. No production table scans just to discover scale. Estimate with catalog stats, counts on indexed filters, or small bounded samples first.
5. No export without schema/table whitelist and field projection.

## Delivery Gate

Report exact read-only scope, command category used, tables and fields touched, row/sample counts, output files, whether any limit or batch boundary applied, changed files, validation, and residual risk.

