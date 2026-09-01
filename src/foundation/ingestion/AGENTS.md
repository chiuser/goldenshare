# AGENTS.md — `src/foundation/ingestion/` rules

## Scope

This directory owns long-term ingestion concepts: action requests, execution plans, and plan projections. It is the boundary that turns a dataset action such as `maintain` into executable units without exposing legacy daily/backfill/history branches.

## Current Source Of Truth

1. `DatasetActionRequest` describes the requested dataset action.
2. `DatasetExecutionPlan` is the canonical execution-plan projection.
3. Resolver output is what Ops TaskRun execution should consume; callers should not infer execution branches themselves.
4. Resolver is the single place that normalizes user or schedule intent into execution dates, month windows, and plan units.

## Constraints

1. Keep this layer foundation-only. Do not import `src.ops`, `src.biz`, `src.app`, `src.platform`, or `src.operations`.
2. Do not reintroduce legacy daily/backfill/history execution terms as domain concepts.
3. Resolver code must read `DatasetDefinition` facts and output `DatasetExecutionPlan`; it must not project legacy execution contracts.
4. Do not add ad hoc checkpoint/acquire/replay semantics or a second task state machine. When the root long-task gate applies, the execution plan must explicitly define durable unit boundaries and resume semantics; a dedicated checkpoint store is allowed only after requirement-specific review.
5. Do not put Ops TaskRun persistence, scheduling, or UI display decisions in this layer.
6. Do not move date-model expansion into Ops, UI, or request builders. Request builders may format normalized plan values for source APIs, but must not decide business date semantics.
7. When adding or changing structured `error_code` / `reason_code` values, update `src/foundation/ingestion/codebook.py` in the same change. Missing codebook entries are not allowed.
8. Long tasks must keep memory proportional to the configured batch, not the full execution range. A completed durable unit is the minimum recoverable boundary; process-local state is never a resume source.
9. Cancellation must be checked before and after each unit or page. Do not start another unit after cancellation, and do not report a partially processed unit as complete.
10. Changes to `DatasetDefinition`, `DatasetExecutionPlan`, pagination, commit, or page-processing contracts must also update `docs/templates/dataset-development-template.md` in the same change.

## Minimum Gates

1. Plan resolver tests must cover point, range, month, and no-time datasets.
2. Architecture dependency tests must remain green.
3. Run `pytest -q tests/test_dataset_action_resolver.py` for resolver changes.
4. Run `pytest -q tests/architecture/test_dataset_codebook_guardrails.py` when structured error or reason codes change.
5. When the long-task gate applies, tests must cover mid-run cancellation, process restart/resume, idempotent replay, bounded batches, and no partial-unit completion.
