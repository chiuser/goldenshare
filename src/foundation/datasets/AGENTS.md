# AGENTS.md — `src/foundation/datasets/` rules

## Scope

This directory owns the dataset single-source model.

## Constraints

1. Keep this layer foundation-only. Do not import `src.ops`, `src.biz`, `src.app`, `src.platform`, or `src.operations`.
2. Define what a dataset is, not how Ops schedules or displays it.
3. Derived registries may read existing Sync V2 contracts during migration, but new user-facing facts should converge here.
4. Do not hardcode execution branches such as legacy daily/backfill/history paths.

## Minimum Gates

1. Dataset registry tests must cover all Sync V2 contracts.
2. Architecture dependency tests must remain green.
