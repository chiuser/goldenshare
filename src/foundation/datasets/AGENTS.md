# AGENTS.md — `src/foundation/datasets/` rules

## Scope

This directory owns the dataset single-source model. It defines dataset identity and stable facts, not UI labels assembled in Ops or execution branches hidden in Sync V2.

## Current Source Of Truth

1. `DatasetDefinition` is the canonical dataset fact model.
2. Dataset key, Chinese display name, source scope, table mapping, date model, filters, and user-facing grouping must converge here.
3. Derived registries may read existing Sync V2 contracts during migration, but the output must be DatasetDefinition-shaped facts.

## Constraints

1. Keep this layer foundation-only. Do not import `src.ops`, `src.biz`, `src.app`, `src.platform`, or `src.operations`.
2. Define what a dataset is, not how Ops schedules or displays it.
3. Derived registries may read existing Sync V2 contracts during migration, but new user-facing facts should converge here.
4. Do not hardcode execution branches such as legacy daily/backfill/history paths.
5. Do not expose `spec_key`, `job_name`, or legacy route names as user-facing dataset identity.

## Minimum Gates

1. Dataset registry tests must cover all Sync V2 contracts.
2. Architecture dependency tests must remain green.
3. Run `pytest -q tests/test_dataset_definition_registry.py` for registry changes.
