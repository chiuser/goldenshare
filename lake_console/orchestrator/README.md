# Goldenshare Dagster Orchestrator

`lake_console/orchestrator` is the local Dagster project for the Goldenshare
Parquet lake. It is a formal data orchestration project, not a scaffold or
scratch Dagster tutorial.

## Current Scope

The active code location is loaded from `src/orchestrator/defs` and currently
contains lake assets, asset checks, asset jobs, sensors, schedules,
run-contract helpers, the read-only lake asset catalog registry, Feishu
run-status notifications, ClickHouse serving sync definitions, and shared
resources.

Current resource keys are:

- `lake_root`
- `duckdb`
- `tushare`
- `prod_postgres`
- `clickhouse`
- `prod_clickhouse`
- `feishu`

Sensitive values are read from environment variables. Do not write tokens,
webhook URLs, or secrets into code, docs, metadata, logs, `dagster.yaml`, or
local env files committed to the repo.

## Required Reading

Before changing Dagster definitions, read:

- [AGENTS.md](/Users/congming/github/goldenshare/AGENTS.md)
- [lake_console/AGENTS.md](/Users/congming/github/goldenshare/lake_console/AGENTS.md)
- [orchestrator/AGENTS.md](/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md)
- [CODING_STANDARDS.md](/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md)
- [Dagster run contract governance](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-run-contract-governance.html)
- [Dagster asset/job topology](/Users/congming/github/goldenshare/lake_console/docs/architecture/dagster-asset-job-topology.html)

## Execution Gate

The local Dagster instance is treated as a formal environment. Do not casually
run `dg`, Dagster jobs, sensors, backfills, materializations, automation
evaluations, or scripts that read the formal Dagster instance.

Any Dagster execution must first list the exact command, working directory,
`DAGSTER_HOME`, read/write scope, expected impact, and rollback plan, then wait
for explicit approval.

Static code and documentation checks are allowed.

## Common Static Checks

From this directory:

```bash
.venv/bin/python -B -m unittest discover -s tests
ruff check tests
```

From the repository root:

```bash
python3 scripts/check_docs_integrity.py
git diff --check
git status --short
```

These checks do not replace Dagster runtime validation. They are the safe
default for code/documentation governance work.
