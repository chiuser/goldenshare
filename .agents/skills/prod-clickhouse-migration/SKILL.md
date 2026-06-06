---
name: prod-clickhouse-migration
description: Use for Goldenshare prod ClickHouse schema migrations, Flyway upgrades, migration validation, prod ClickHouse table schema changes, and recovering from schema mismatch during Dagster prod sync. 适用于生产 ClickHouse 表结构升级、Flyway V1/V2/V3 执行与校验、prod CH schema drift 排查、Dagster prod ClickHouse sync 因缺列或表结构不一致失败的修复。
---

# Prod ClickHouse Migration

Use this skill when changing or validating Goldenshare prod ClickHouse schema. This is a production operation: do not improvise, do not run Dagster sync while schemas differ, and do not use the low-privilege sync user for DDL.

## Required Context

1. Read `AGENTS.md`, `lake_console/AGENTS.md`, and `lake_console/orchestrator/AGENTS.md`.
2. Read the relevant design docs before executing:
   - `lake_console/docs/design/dagster-clickhouse-serving-design.md`
   - `lake_console/docs/design/dagster-clickhouse-prod-sync-design.md`
3. Also use `clickhouse-best-practices` for ClickHouse schema/query safety. At minimum apply:
   - `agent-connect-mcp`: use configured CLI/tunnel credentials, never ask for secrets in chat.
   - `agent-discovery-schema`: discover databases, tables, columns, and sort keys before writing DDL.
   - `schema-types-native-types`: schema columns must keep native ClickHouse types.
   - `insert-mutation-avoid-update`: do not repair historical values with `ALTER TABLE UPDATE`.

## Approval Gate

Before any production command, state and get explicit approval for:

1. target host and connection path
2. exact Flyway or ClickHouse commands
3. migration file versions expected to run
4. write scope: schema history table and/or target table DDL
5. data row impact: whether any business rows are inserted, deleted, or updated
6. rollback posture and what to do if the command fails

Do not run `flyway clean`, `flyway repair`, `ALTER TABLE UPDATE`, hand-written historical inserts, or Dagster prod sync as part of schema migration unless the user explicitly approves that separate action.

## Correct Connection Model

There are two separate prod ClickHouse paths:

- Native tunnel for Dagster/clickhouse-client:
  - `lake_console/bin/lake-prod-clickhouse-tunnel`
  - local `127.0.0.1:19000` -> prod `127.0.0.1:9000`
- HTTP tunnel for Flyway JDBC:
  - local `127.0.0.1:18123` -> prod `127.0.0.1:8123`
  - create manually:

```bash
ssh -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 18123:127.0.0.1:8123 \
  goldenshare-prod
```

Never use the native `19000` tunnel for Flyway; Flyway needs HTTP/JDBC.

## Permission Rule

`PROD_CLICKHOUSE_USER` / `goldenshare_sync_writer` is for Dagster prod sync writes, not schema migration. It may not have privileges to:

- see `default.flyway_schema_history`
- create Flyway history tables
- create databases
- rename or add columns

If Flyway `info` with `PROD_CLICKHOUSE_USER` says the schema history table does not exist, do not assume history is absent. Recheck with the prod ClickHouse management account.

Use the prod local ClickHouse `default` management account for Flyway migration unless the design doc or user supplies another migration-specific admin account:

```bash
flyway \
  -configFiles=clickhouse_migrations/flyway.conf \
  -url=jdbc:clickhouse://127.0.0.1:18123/default \
  -user=default \
  -password= \
  info
```

## Migration Workflow

Run from:

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
```

1. Stop or confirm stopped any automation that writes the target prod table.
2. Start the HTTP tunnel `18123 -> prod 8123`.
3. Inspect Flyway state with the migration account:

```bash
flyway \
  -configFiles=clickhouse_migrations/flyway.conf \
  -url=jdbc:clickhouse://127.0.0.1:18123/default \
  -user=default \
  -password= \
  info
```

4. If the expected previous version is present and the new migration is `Pending`, run:

```bash
flyway \
  -configFiles=clickhouse_migrations/flyway.conf \
  -url=jdbc:clickhouse://127.0.0.1:18123/default \
  -user=default \
  -password= \
  migrate
```

5. Validate:

```bash
flyway \
  -configFiles=clickhouse_migrations/flyway.conf \
  -url=jdbc:clickhouse://127.0.0.1:18123/default \
  -user=default \
  -password= \
  validate
```

6. Check final Flyway state:

```bash
flyway \
  -configFiles=clickhouse_migrations/flyway.conf \
  -url=jdbc:clickhouse://127.0.0.1:18123/default \
  -user=default \
  -password= \
  info
```

7. Verify prod schema through the same user Dagster sync uses, not only through admin:

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home \
PYTHONPATH=src \
.venv/bin/python - <<'PY'
import os
from clickhouse_driver import Client

client = Client(
    host=os.environ["PROD_CLICKHOUSE_HOST"],
    port=int(os.environ["PROD_CLICKHOUSE_PORT"]),
    user=os.environ["PROD_CLICKHOUSE_USER"],
    password=os.environ["PROD_CLICKHOUSE_PASSWORD"],
    database=os.environ["PROD_CLICKHOUSE_DATABASE"],
    connect_timeout=10,
    send_receive_timeout=30,
)

for row in client.execute("""
    SELECT name, type
    FROM system.columns
    WHERE database = currentDatabase()
      AND table = 'share_fact_market_breadth_daily'
    ORDER BY position
"""):
    print(row[0], row[1])
PY
```

8. Stop the temporary HTTP tunnel when migration validation is complete.

## Decision Points

If `info` shows V1/V2 success and V3 pending:

- run `migrate`, then `validate`, then schema checks.

If `info` appears empty under `PROD_CLICKHOUSE_USER`:

- do not baseline or migrate with that user.
- check `default.flyway_schema_history` with prod local management account.

If `default` database or `default.flyway_schema_history` is invisible to the sync user:

- treat it as a permissions issue, not proof of missing history.

If Flyway cannot create history or run DDL because of privileges:

- stop.
- switch to the prod local ClickHouse management account or ask for an approved migration account.

If the target table already exists with the expected previous schema but Flyway history is genuinely absent under the migration account:

- stop and ask for approval before `baseline`.
- record why the existing schema equals the baseline version.

## Post-Migration Data Rule

Schema migration does not repair data rows. For market breadth bucket changes:

1. V3 only renames old 7% columns and adds 10% columns.
2. Old rows may have default `0` in new columns until Dagster sync rewrites them.
3. Restore data through the formal Dagster job:
   - first ensure local `ch_share_fact_market_breadth_daily` is fully rebuilt and validated.
   - then run `prod_clickhouse_share_fact_market_breadth_sync_job` over the approved partition range.
4. Do not manually insert historical rows into prod and do not use `ALTER TABLE UPDATE` to patch bucket values.

## Failure Handling

If Dagster prod sync failed before migration because insert columns did not exist:

1. Query failed partition range from Dagster run/backfill logs.
2. Assume any failed partition may have been deleted first if the asset uses delete-then-insert replace.
3. After schema migration, rerun the formal prod sync job for at least the failed range; prefer the full approved range when historical rows also need new bucket values.

If migration fails mid-command:

1. Stop all downstream sync.
2. Capture Flyway output and `flyway info`.
3. Query `system.columns` for the target table.
4. Do not run `repair` until the user explicitly approves a repair plan.

## Delivery Gate

Report:

1. migration path used: tunnel, URL, user category, and working directory
2. Flyway `info` before and after
3. `migrate` and `validate` results
4. schema columns visible to the Dagster prod sync user
5. whether any business rows were changed
6. whether a follow-up Dagster prod sync is still required
7. any temporary tunnel started and whether it was closed
