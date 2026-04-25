# AGENTS.md — `src/foundation/ingestion/` rules

## Scope

This directory owns long-term ingestion concepts: action requests, execution plans, and plan projections.

## Constraints

1. Keep this layer foundation-only. Do not import `src.ops`, `src.biz`, `src.app`, `src.platform`, or `src.operations`.
2. Do not reintroduce legacy daily/backfill/history execution terms as domain concepts.
3. Resolver code may project existing Sync V2 contracts during migration, but it must output `DatasetExecutionPlan`.
4. Do not add checkpoint/acquire/replay semantics unless explicitly planned.

## Minimum Gates

1. Plan resolver tests must cover point, range, month, and no-time datasets.
2. Architecture dependency tests must remain green.
