---
name: audit-dg-datasets-by-date
description: Audit physical completeness for specified dates across Goldenshare DG datasets, including daily Lake and serving data, stock weekly/monthly Raw and Silver updates, and natural-day announcements. Use when asked which DG datasets are missing or not updated on a date. Distinguish physical data, update dates, task results, and snapshots.
---

# Audit DG Datasets By Date

Use this skill for a read-only audit of physical data and whether the required date is covered. Dagster materializations and checks do not replace file or serving-table facts.

## Required coverage

- Discover assets from the current `LAKE_ASSET_CATALOG` and classify them using `PARTITION_MODEL_DEFINITIONS`, current paths, schemas and producer code. Do not maintain a replacement catalog or classify all non-trade-date models as irrelevant.
- Audit all trade-date Lake assets and date-driven serving assets covered by the bundled script, including local/prod ClickHouse market breadth and DC technical indicators, plus prod PostgreSQL wealth turnover and stock/index daily nine-turn.
- **Stock weekly and monthly data are mandatory:** `raw_tushare_stk_period_bar_adj_week`, `raw_tushare_stk_period_bar_adj_month`, `silver_stock_weekly`, `silver_stock_monthly`. Their files are partitioned by week/month but are updated daily. They must not remain in the excluded list or be described as snapshots. Check both physical data and the observed update date.
- Include `raw_tushare_anns_d` for the requested natural date. It is an announcement-date dataset, not a snapshot; a day with genuinely no announcements can be valid. Do not require positive rows without checking its empty-result contract.
- Raw and Silver trade calendars are excluded as audit targets. Use the existing Silver SSE calendar only as the date reference needed for weekly/monthly updates; do not produce calendar audit results or compare Raw and Silver calendars.
- True full snapshots and Lake health are outside daily-row completeness. List their exact identities and reasons separately; exclusion does not mean obsolete, healthy, fresh, or previously audited. Do not infer a historical snapshot from the current file.
- An unknown model or unsupported path must be reported as unverified. Merely placing an asset in an excluded list does not establish that its exclusion is appropriate.

Read the [automatic-script change plan](references/automatic-audit-script-plan.md) and [LLD](references/scope-and-low-level-design.md) for the exact period, announcement and exclusion rules. These documents were refined on 2026-10-31; implementation and isolated acceptance are still pending. Do not describe the proposed automatic coverage as implemented.

## Procedure

1. Read applicable `AGENTS.md` files, current catalog/model definitions, path helpers and relevant producer contracts. Follow the repository's read-only and data-reading approval boundaries.
2. Use the existing orchestrator environment. The invocation below identifies the existing entrypoint. Until the planned implementation is accepted, first check its read scope: the old annual summary still reads nonessential code/time statistics, ClickHouse still performs unnecessary code/category statistics, and error totals need correction. Do not mechanically run those extra reads under count-only authorization. The five supplements and the existing correct count/error semantics remain required:

   ```bash
   cd /Users/congming/github/goldenshare/lake_console/orchestrator
   .venv/bin/python3 -B \
     /Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py \
     --date 2026-10-29
   ```

   Repeat `--date` for multiple dates. Do not use dependency synchronization or install packages as part of auditing.

3. **The current bundled script only implements the former trade-date/serving scope. It still excludes the four stock period assets and announcements. Its output alone is insufficient.** Perform a bounded read-only supplement for those five assets following the linked design. Reuse dated evidence that actually covers the requested date; otherwise mark the specific check unverified. Do not claim the script has been enhanced when only these instructions have changed.
4. Keep the original JSON unchanged. Save the supplement and report combined coverage without counting the five assets twice. Remove an asset from combined exclusions only after it has a real result. Report file missing, zero rows, update date behind, pending source window, source/backend unavailable, and unverified checks separately.
5. For an audit of today, state the observation time and respect the actual dataset's publication window. For historical dates, current newer period data may show that coverage has advanced; it cannot prove that the update succeeded on the historical day or recreate that day's snapshot.
6. If reasons are requested, or supplemental physical dates are behind and the cause must be established, read only the relevant run, sensor or delivery metadata. Do not open the instance merely to reproduce the old physical-count report. Report task status separately from physical results.

## Output and safety

- Default evidence directory: `/private/tmp`. Link the original JSON and supplementary evidence.
- Show the catalog total, actual scope, excluded scope and unverified scope. List weekly/monthly Raw and Silver individually with their period, expected update date, observed physical-date evidence and result.
- Every current catalog entry must have a justified audited, excluded or unverified classification. `catalog_classification_complete=false` is an audit failure; `true` alone is not an acceptance result.
- `catalog_classification_complete=true` from the former script proves only that every asset received some classification. It does not validate the exclusions or prove complete audit coverage.
- The current plan adds four stock period assets and one announcement asset to the former 159-asset scope: 164 audited and 16 excluded out of the existing 180 catalog entries. The exclusions are two calendars, thirteen full snapshots and one health asset. Derive counts from the actual catalog on future runs; do not treat exclusions as obsolete, healthy or fresh.
- Counts and bounded date predicates are preferred. Development and isolated acceptance must not trigger a formal catalog-wide audit. For a later explicit date audit, establish the necessary scope and reuse applicable evidence; run a complete catalog audit only when the request actually requires it. No full-history market scans, source-wide comparisons, source downloads, repeated global audits or unapproved global detail reads. Do not automatically execute the original job or checks.
- Keep date-filtered ClickHouse queries read-only with the existing scan/result/time limits. Prod PostgreSQL reads must use the existing resource's forced-read-only transaction, even if its account has write grants. A missing connection or tunnel is `backend_unavailable`, never a silent exclusion or physical gap.
- No jobs, sensor evaluation, sensor/cursor changes, materialization, dynamic partitions, runless events, database writes, Lake writes or repairs. Use existing read-only resources; do not initialize or upgrade an instance.
- A dataset audit must not modify repository files or rewrite historical audit evidence.

## Interpretation

`missing_file` means the expected file is absent; `empty_file` is a zero-byte file. `missing_date_rows` means the requested date has no rows in the audited annual-file family. `missing_rows` means a date-driven serving table has no rows for that date. A readable file with zero records is a separate observation; whether zero is allowed depends on its producer contract. `backend_unavailable` and unverified scope are not missing data.

A period file containing rows is not enough to say its daily update completed. Report its observation date separately. Physical presence, freshness, source coverage, native checks and task success are distinct conclusions; claim only what the evidence establishes.

Missing, zero-byte and readable zero-row period files have no observed update date; they are not evidence of a valid older update. Follow LLD section 5.1 for pending/gap and null/zero fields. Missing columns, wrong types and read failures make that item unverified while other normal items continue. Count unverified assets from `assessment_status`, not merely from `update_status`.
