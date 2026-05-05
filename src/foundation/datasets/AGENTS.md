# AGENTS.md — `src/foundation/datasets/` rules

## Scope

This directory owns the dataset single-source model. It defines dataset identity and stable facts, not UI labels assembled in Ops or execution branches hidden in old implementations.

## Current Source Of Truth

1. `DatasetDefinition` is the canonical dataset fact model.
2. Dataset key, Chinese display name, source scope, table mapping, date model, filters, and user-facing grouping must converge here.
3. Derived registries must be DatasetDefinition-shaped facts and must not read legacy execution contracts.

## Constraints

1. Keep this layer foundation-only. Do not import `src.ops`, `src.biz`, `src.app`, `src.platform`, or `src.operations`.
2. Define what a dataset is, not how Ops schedules or displays it.
3. New user-facing facts must converge here; do not create parallel display-name, date-model, or input-schema maps in Ops or frontend.
4. Do not hardcode execution branches such as legacy daily/backfill/history paths.
5. Do not expose internal route keys, `job_name`, or legacy route names as user-facing dataset identity.
6. Do not infer the dataset time model from source parameter names alone. Optional source parameters such as `start_date`, `end_date`, `ann_date`, or `trade_date` are not automatically user-facing time inputs.
7. Before adding or changing a DatasetDefinition, prove the source API behavior with real requests: no business params, object-only filter, point date, range date, and pagination. If no-param pagination is the only complete path, model the dataset as no-time snapshot.
8. Every new dataset must have a written row-count proof before completion: fetched rows, normalized rows, written rows, rejected rows, reject reason codes, and target table count. Large rejects without a code-level explanation block completion.

## Minimum Gates

1. Dataset registry tests must cover all DatasetDefinition entries.
2. Architecture dependency tests must remain green.
3. Run `pytest -q tests/test_dataset_definition_registry.py` for registry changes.
4. For new datasets or date_model changes, add resolver/request-builder tests proving the exact source params generated for every supported time mode, including no-date snapshot if supported.
5. For new datasets, run at least one real sample through normalizer/writer or a documented dry-run equivalent before marking the dataset complete.
