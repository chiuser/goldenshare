# AGENTS.md — `src/foundation/ingestion/` rules

## Scope

This directory owns long-term ingestion concepts: action requests, execution plans, and plan projections. It is the boundary that turns a dataset action such as `maintain` into executable units without exposing legacy daily/backfill/history branches.

## Current Source Of Truth

1. `DatasetActionRequest` describes the requested dataset action.
2. `DatasetExecutionPlan` is the canonical execution-plan projection.
3. Resolver output is what Ops TaskRun execution should consume; callers should not infer execution branches themselves.

## Constraints

1. Keep this layer foundation-only. Do not import `src.ops`, `src.biz`, `src.app`, `src.platform`, or `src.operations`.
2. Do not reintroduce legacy daily/backfill/history execution terms as domain concepts.
3. Resolver code may project existing Sync V2 contracts during migration, but it must output `DatasetExecutionPlan`.
4. Do not add checkpoint/acquire/replay semantics unless explicitly planned.
5. Do not put Ops TaskRun persistence, scheduling, or UI display decisions in this layer.

## Minimum Gates

1. Plan resolver tests must cover point, range, month, and no-time datasets.
2. Architecture dependency tests must remain green.
3. Run `pytest -q tests/test_dataset_action_resolver.py` for resolver changes.
