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

Daily quote automation now treats raw and silver readiness as separate
production boundaries for the chains that have been repaired. `stock_daily`
uses `raw_stock_daily_update_job` / `silver_stock_daily_update_job`, and
`suspend_d` uses `raw_suspend_d_update_job` / `silver_suspend_d_update_job`.
Silver sensors must wait for the corresponding raw latest materialization and
blocking checks before submitting silver runs.

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

Before changing Dagster definitions or formal Dagster design documents, read:

- [AGENTS.md](/Users/congming/github/goldenshare/AGENTS.md)
- [lake_console/AGENTS.md](/Users/congming/github/goldenshare/lake_console/AGENTS.md)
- [orchestrator/AGENTS.md](/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md)
- [CODING_STANDARDS.md](/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md)
- [Dagster data system architecture](/Users/congming/github/goldenshare/lake_console/docs/architecture/dagster-data-system-architecture.html)
- [Dagster run contract governance](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-run-contract-governance.html)
- [Dagster asset/job topology](/Users/congming/github/goldenshare/lake_console/docs/architecture/dagster-asset-job-topology.html)
- [Dagster asset schema contract](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-asset-schema-contract-design.md)
- [Dagster silver raw readiness registry](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-silver-raw-readiness-registry.html)
- [Dagster bootstrap legacy links](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-bootstrap-legacy-links.md)

## Execution Gate

The local Dagster instance is a formal environment, not a test sandbox.
Static inspection and queries of existing formal facts follow the standing
read-only authorization in the root AGENTS; do not initialize an instance,
migrate storage, write probes, or trigger evaluations under that authorization.

Tests use an approved isolated validation plan, not formal Lake files, databases,
tokens, or active tasks. Formal jobs, checks/evaluations, backfills, events,
partition registration, and sensor/schedule state changes require stage-specific
approval with the command, working directory, DAGSTER_HOME, read/write scope,
impact, recovery approach, and reason. Inspect import/resource side effects
before treating a command such as `dg check defs` as read-only.

The detailed authority and environment rules live in [AGENTS.md](AGENTS.md).

## Common Static Checks

For Python changes, after verifying the existing environment and test isolation,
run from this directory. Use the approved protected test launcher when a task
provides one; do not bypass it with a direct pytest command.

```bash
.venv/bin/python3 -B -m pytest -q tests/<target_test_file.py>
.venv/bin/ruff check --no-cache --select E9,F63,F7,F82 src tests
.venv/bin/ruff check --no-cache <changed Python files>
```

Do not add `PYTHONPATH=src` to work around import failures. The project is
installed as an editable package in its own `.venv`; use that environment's
interpreter. Missing dependencies must be reported; do not run `uv sync`,
implicitly download dependencies, or rebuild the environment without installation
approval. Documentation-only changes do not require business tests or Dagster execution.

The repository-wide Ruff command is the current critical-error baseline. Run
the default Ruff rules against every Python file changed by the task; broader
pre-existing style debt is not silently attributed to the current change.

From the repository root:

```bash
python3 scripts/check_docs_integrity.py
git diff --check
git status --short
```

The docs script checks the root `docs/` surface, not `lake_console/docs/**` HTML.
For those documents also check local links and structure; see the
[onboarding template validation section](../docs/templates/dagster-dataset-onboarding-template.html#acceptance).
Report static checks, read-only audits, isolated tests, and approved formal
execution separately; none substitutes for another.
