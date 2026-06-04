---
name: tushare-contract-validation
description: Use for Tushare parameters, fields, pagination, date semantics, DatasetDefinition, request builders, ingestion plans, source contracts, or field contract changes. 适用于 Tushare 接口、字段、分页、日期语义、数据集定义、请求参数和契约验证。
---

# Tushare Contract Validation

Use this skill whenever implementation depends on Tushare behavior.

## Required Evidence Order

1. Inspect current code and all consumers first.
2. Read the matching local source document under `docs/sources/tushare/**`.
3. Use `tushareMcp` for real behavior verification when it is visible.
4. Use `tushare-data` only for interface family understanding and research context; it never replaces current code, local docs, or `tushareMcp` facts.

## Field And Parameter Checks

For each relevant Tushare API, verify:

1. required parameters
2. optional parameters
3. pagination parameters and limits
4. date filtering semantics
5. no-time, object-only, point-time, range-time, and paginated behavior when applicable
6. default returned fields
7. explicitly requested documented fields
8. explicitly requested business-critical fields

Business-critical fields include identity, primary key, Redis key, idempotency, grouping, frequency, market, time, and filtering fields such as `freq`, `category`, `type`, `market`, `hot_type`, `is_new`, `time`, and `trade_time`.

## Contract Rules

1. Optional source parameters are not automatically operator inputs.
2. A source date parameter does not automatically mean the dataset is date-driven.
3. If omitting date can fetch the full dataset and date filters lose history, prefer a no-time snapshot model.
4. Changes to `DatasetDefinition.date_model`, `input_shape`, `observed_field`, request builders, or ingestion plans require full consumer audit.
5. If code, local docs, and `tushareMcp` disagree, record the difference and calibrate implementation from current code plus measured behavior.

## Delivery Gate

Report code files audited, source docs read, `tushareMcp` calls or reason unavailable, field/parameter samples, conflicts found, contract consumers, changed files, and tests.

