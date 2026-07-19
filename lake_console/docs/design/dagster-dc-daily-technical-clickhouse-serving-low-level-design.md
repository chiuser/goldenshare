# `gold_dc_daily_technical` ClickHouse Serving 与 Prod 回写 LLD

更新时间：2026-07-17

关联方案：[`dagster-dc-daily-technical-clickhouse-serving-plan.md`](dagster-dc-daily-technical-clickhouse-serving-plan.md)

状态：P5B-4 `ch_dc_daily_technical` Dagster materialization/check event 已补齐；P5B-5 sensor 运行观察尚未执行。本 LLD 不再安排新的物理数据或事件补录。

已确认口径：采用本地 ClickHouse serving -> Prod ClickHouse sync 两阶段架构；目标表名冻结为 `goldenshare_serving.board_fact_technical_daily`；serving 表增加 `updated_at`；历史 materialization 全量补齐，check event 只保留最近 20 个交易日。

## 1. 基线与硬约束

### 1.0 P0 只读核验结果（2026-07-16）

- Prod ClickHouse `26.5.1.882`，数据库 `goldenshare_serving`，时区 `Asia/Shanghai`。
- Flyway schema history head 为 `V3`，V1-V3 已安装且只读 `validate` 通过。
- 目标表在 P0 时不存在；P5B-3 已由 local/Prod 两端 Flyway V3 baseline + V4 migrate 建立并完成 schema/空表核验。
- `goldenshare_sync_writer` 在 P0 时没有目标表建表权限；P5B-3 后只拥有正式目标 `SELECT, INSERT, ALTER DELETE`，以及本次动态 staging 的 `SELECT, INSERT`，DDL 和换表仍由 admin 执行。
- 仓库内没有目标表的现有查询消费者，因此 `ORDER BY (trade_date, category, ts_code)` 保持冻结。

P0 结论已完成；P5B-3 的正式 DDL 和业务数据写入、P5B-4 的 Dagster 事件补录均已通过验收。

### 1.1 已核对的代码事实

| 事实 | 当前实现 |
| --- | --- |
| Gold asset | `defs/assets/dc_daily_technical_asset.py` |
| Gold writer | `defs/assets/dc_daily_technical.py` |
| Gold schema | `defs/run_contracts/asset_column_schemas.py:GOLD_DC_DAILY_TECHNICAL_SCHEMA` |
| Gold partition set | `cn_a_dc_daily_trade_days` |
| Gold core check | `defs/checks/dc_daily_technical_checks.py` |
| Gold readiness | `defs/asset_guards/dc_daily_technical_lake_readiness.py` |
| ClickHouse resource | `defs/resources.py:prod_clickhouse` |
| Serving reference | `defs/assets/clickhouse_serving.py` |
| Existing Prod job | `defs/jobs/prod_clickhouse_share_fact_market_breadth_sync.py` |
| Migration | `clickhouse_migrations/sql/V1..V3` |

### 1.2 Hard constraints

1. Gold Parquet remains the fact source; ClickHouse is a serving copy.
2. Table structure is managed by Flyway, never created by an asset.
3. Normal assets process exactly one trade date per run.
4. Local and Prod checks are explicitly partitioned and single-partition attributable.
5. Sensors inspect only the latest 10 expected dates and never scan Dagster event history.
6. Historical Bootstrap does not launch 611 Dagster runs and does not enable sensors.
7. A healthy existing target may be skipped idempotently; an existing unhealthy target stops rather than being silently overwritten.
8. DDL, business-row writes and Dagster event writes are separate approval gates.
9. Gold formulas, Parquet layout and existing Gold repair semantics are unchanged.

## 2. File and module boundaries

### 2.1 当前已落地文件与后续文件

    orchestrator/src/orchestrator/defs/run_contracts/dc_daily_technical_serving.py
    orchestrator/src/orchestrator/defs/assets/dc_daily_technical_serving.py
    orchestrator/src/orchestrator/defs/checks/dc_daily_technical_serving_checks.py
    orchestrator/src/orchestrator/defs/asset_guards/dc_daily_technical_clickhouse_readiness.py
    orchestrator/src/orchestrator/defs/jobs/dc_daily_technical_serving.py
    orchestrator/src/orchestrator/defs/sensors/dc_daily_technical_serving_sensor.py
    orchestrator/src/orchestrator/defs/sensors/prod_dc_daily_technical_sensor.py
    orchestrator/tests/test_dc_daily_technical_serving.py
    orchestrator/tests/test_dc_daily_technical_clickhouse_readiness.py
    orchestrator/tests/test_dc_daily_technical_serving_definitions.py
    orchestrator/tests/test_dc_daily_technical_prod_sensor.py
    orchestrator/src/orchestrator/defs/bootstrap/dc_daily_technical_clickhouse_bootstrap.py
    orchestrator/src/orchestrator/defs/bootstrap/dc_daily_technical_clickhouse_bootstrap_cli.py
    orchestrator/tests/test_dc_daily_technical_clickhouse_bootstrap.py

P4 已新增只读 Bootstrap planner、`dry-run`/`audit` CLI 和隔离 `sample` staging 入口。P5B-1 guarded apply、P5B-2 本地隔离 sample、P5B-3 正式目标/Prod 全量 Bootstrap 和 P5B-4 事件补录均已完成。

P4 本地验证结果：专项回归 139 个测试、70 个子测试通过；`dg check defs` 和 `git diff --check` 通过。未执行 ClickHouse sample、Prod DDL、正式数据写入或事件写入。

### 2.1.1 P5A 正式 lake dry-run 结果

首次 dry-run 发现交易日历含历史和未来日期，范围为 `1990-12-19` 至 `2026-12-31`，共 `8,797` 个 SSE 开市日；Gold 实际覆盖为 `2024-01-02` 至 `2026-07-14`，共 `611` 个文件。planner 已改为默认使用 Gold dataset history start 和现有 Gold 最新分区日期，显式超出 Gold 覆盖的日期仍 fail-closed。

修正后的只读报告为：

    /private/tmp/dc_daily_technical_clickhouse_p5a_dry_run_20260716_v2.json

结果：`611` 个 expected dates、`611` 个文件、`596,200` 行、`82,447,853` 字节、`12` 个批次、失败日期 `0`、`should_stop=false`。本阶段没有 ClickHouse DDL、INSERT、Dagster 事件或 sensor 写入。

### 2.2 Files that remain unchanged

- `defs/assets/dc_daily_technical.py`: Gold formula、输出合同和 repair 语义保持不变；其历史
  Silver 输入装载使用有界文件批次，避免一次打开全部 Parquet。
- `defs/assets/dc_daily_technical_asset.py`: Gold asset name and partition set.
- `defs/checks/dc_daily_technical_checks.py`: Gold core check; no formula check is added.
- `defs/assets/clickhouse_serving.py`: Existing market-breadth implementation is not overloaded with a different table contract.
- ClickHouse V1/V2/V3 migrations.

## 3. Serving contract

### 3.1 Contract constants

`run_contracts/dc_daily_technical_serving.py` defines:

    DC_DAILY_TECHNICAL_SERVING_TABLE = "goldenshare_serving.board_fact_technical_daily"
    DC_DAILY_TECHNICAL_SERVING_PARTITION_SET = "cn_a_dc_daily_trade_days"
    DC_DAILY_TECHNICAL_SERVING_WINDOW_LIMIT = 10
    DC_DAILY_TECHNICAL_SERVING_COLUMNS = (...)
    DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS = (...)

The business-column order must mechanically match `GOLD_DC_DAILY_TECHNICAL_SCHEMA`. Asset, check and Bootstrap may not each maintain their own column order. `updated_at` exists only in the ClickHouse serving contract.

### 3.2 Key and physical layout

Business key: `(ts_code, trade_date, category)`.

Dagster partition key: `trade_date`.

ClickHouse layout:

    PARTITION BY toYYYYMM(trade_date)
    ORDER BY (trade_date, category, ts_code)

The final ORDER BY remains subject to a read-only consumer-query audit before DDL is frozen.

### 3.3 Null mapping

- MA warmup NULL is stored as `Nullable(Float64)`.
- BOLL warmup NULL is stored as `Nullable(Float64)`.
- Current KDJ/MACD contract is non-null and is stored as `Float64`.
- No NULL is converted to 0, an empty string or a default value.

## 4. Migration LLD

### 4.1 Migration file

Add:

    clickhouse_migrations/sql/V4__create_dc_daily_technical.sql

DDL draft:

    CREATE TABLE IF NOT EXISTS goldenshare_serving.board_fact_technical_daily
    (
        ts_code LowCardinality(String),
        trade_date Date,
        category LowCardinality(String),
        close Float64,
        ma_5 Nullable(Float64),
        ma_10 Nullable(Float64),
        ma_15 Nullable(Float64),
        ma_20 Nullable(Float64),
        ma_30 Nullable(Float64),
        ma_60 Nullable(Float64),
        ma_120 Nullable(Float64),
        ma_250 Nullable(Float64),
        kdj_k Float64,
        kdj_d Float64,
        kdj_j Float64,
        macd_dif Float64,
        macd_dea Float64,
        macd Float64,
        boll_mid Nullable(Float64),
        boll_upper Nullable(Float64),
        boll_lower Nullable(Float64),
        observation_count UInt32,
        params_key LowCardinality(String),
        indicator_version LowCardinality(String),
        updated_at DateTime
    )
    ENGINE = MergeTree
    PARTITION BY toYYYYMM(trade_date)
    ORDER BY (trade_date, category, ts_code);

Before implementation, read-only verify:

1. Prod ClickHouse version supports the proposed types.
2. `DateTime` timezone behavior matches the existing serving table.
3. Live Flyway head and schema-history table name.
4. Whether the target table already exists and the conflict policy.

Migration gate:

1. Run Flyway info/schema-history read-only with an admin-capable path.
2. Connect the new migration to the real head.
3. Validate and smoke-test locally.
4. Obtain explicit approval for Prod DDL.
5. Run Prod migration with the DDL-capable account.
6. Verify the resulting schema and writer-account permissions read-only.

The business writer account never runs CREATE/ALTER/DROP.

## 5. Local serving asset

### 5.1 Definition

File: `defs/assets/dc_daily_technical_serving.py`.

    @dg.asset(
        name="ch_dc_daily_technical",
        deps=["gold_dc_daily_technical"],
        partitions_def=cn_a_dc_daily_trade_days,
    )

Resources: `lake_root`, `duckdb` and `clickhouse`.

The asset:

1. validates `context.partition_key`;
2. reads only explicit Gold columns for that date;
3. performs set-based DuckDB schema/date/key/row-count checks;
4. builds explicit ClickHouse rows;
5. calls a parameterized single-date replace helper;
6. emits small materialization metadata.

It does not create tables, access Prod ClickHouse, scan Dagster history or load all historical Gold files.

### 5.2 Single-date replace

Reuse the existing serving replace semantics with a parameterized table and explicit columns:

    SET lightweight_deletes_sync = 1
    DELETE FROM target WHERE trade_date = :partition_key
    assert target count for date = 0
    INSERT INTO target (explicit_columns) VALUES rows
    assert target count for date = expected_count

If insert fails after delete, fail immediately and do not advance the sensor. Recovery is a bounded manual rerun of the same date. Do not use ALTER TABLE UPDATE or OPTIMIZE FINAL.

## 6. Prod sync asset

### 6.1 Definition

Recommended in the same module:

    @dg.asset(
        name="prod_ch_dc_daily_technical",
        deps=["ch_dc_daily_technical"],
        partitions_def=cn_a_dc_daily_trade_days,
        backfill_policy=dg.BackfillPolicy.multi_run(max_partitions_per_run=1),
    )

Resources: `clickhouse` and `prod_clickhouse`.

Run steps:

1. read explicit columns from local ClickHouse;
2. validate local date, key and row count;
3. inspect Prod target state;
4. replace only the target Prod date;
5. verify Prod equals local;
6. emit Prod sync metadata.

A multi-partition context fails closed. It cannot produce one aggregated check event.

### 6.2 Tunnel boundary

`prod_clickhouse` only connects. SSH tunnel/VPN is an environment prerequisite. Asset and sensor code never starts a tunnel and never turns tunnel state into business data state.

## 7. Checks

File: `defs/checks/dc_daily_technical_serving_checks.py`.

Names:

    ch_dc_daily_technical_core_check
    prod_ch_dc_daily_technical_core_check

Both checks use:

    partitions_def=cn_a_dc_daily_trade_days
    blocking=True

Core rules:

- target date exists and is non-empty;
- schema is correct;
- physical/data trade date matches the partition;
- business key is non-null and unique;
- row count equals Gold/local serving;
- `params_key` and `indicator_version` match;
- MA/BOLL warmup NULL semantics are preserved;
- Prod business rows match local serving.

The check does not split by indicator, recompute the formulas, write per-row events, scan historical dates or treat row count alone as readiness. Formula correctness remains covered by independent Gold fixtures.

## 8. Readiness and sensors

### 8.1 Batch readiness

File: `defs/asset_guards/dc_daily_technical_clickhouse_readiness.py`.

Input: latest 10 expected dates, registered partitions, lake root and local/Prod ClickHouse clients. Each system performs one bounded batch query, with no per-date Dagster readiness or event-history call.

States:

- missing table/partition: `materialized=False`, eligible target;
- existing but core semantics failed: `materialized=True, checks_passed=False`, skip and require manual handling;
- existing and valid: `ready=True`;
- connection/query failure: ASCII `scan_error` and fail closed.

### 8.2 Local sensor

Name: `ch_dc_daily_technical_continuity_sensor`.

Order: runtime gate -> expected/registered dates -> Gold and local ClickHouse batch readiness -> earliest not-ready date -> skip on upstream-not-ready or materialized check failure -> at most one RunRequest.

### 8.3 Prod sensor

Name: `prod_ch_dc_daily_technical_continuity_sensor`.

Order: local same-date ready -> local/Prod batch status -> earliest Prod not-ready date -> skip on unhealthy existing target -> at most one RunRequest.

Cursor is limited to schema version, evaluated time, decision, target, reason code, frontiers, expected/registered counts and elapsed summaries. It must not contain full rows, paths, date lists, SQL results or code lists.

## 9. Jobs and run keys

File: `defs/jobs/dc_daily_technical_serving.py`.

Add:

    ch_dc_daily_technical_update_job
    prod_ch_dc_daily_technical_sync_job

Jobs only define asset/check selection. They do not contain SQL, create tables or parse run keys.

Use the unified run-request/run-key builders. The intended subjects are:

    ch_dc_daily_technical_update:{trade_date}
    prod_ch_dc_daily_technical_sync:{trade_date}

The exact implementation must follow the repository builders, not a new hand-written format.

## 10. Bootstrap CLI

### 10.1 Modules and commands

    defs/bootstrap/dc_daily_technical_clickhouse_bootstrap.py
    defs/bootstrap/dc_daily_technical_clickhouse_bootstrap_cli.py

Current commands: `dry-run`, `audit`, `sample` and guarded `apply`.

The `apply` subcommand is a separate P5 guarded path. It requires an approved target (`local|prod|both`), expected plan fingerprint, bounded batch size, explicit write confirmation and an empty/backup confirmation before establishing a formal writer connection.

### 10.2 Dry-run

DuckDB explicitly scans the selected Gold partition files, projects contract columns, aggregates rows/date/key/NULL/params/version, inspects source coverage and emits a plan fingerprint plus a JSON report under `/private/tmp`. With no explicit end date, the planner uses the latest existing Gold partition, not the latest future date in the calendar. It does not access Dagster instance or write lake, ClickHouse or events.

### 10.3 Sample

Use one to three explicitly selected dates in an isolated ClickHouse database/table or unique `tmp_`/`staging_` table. The CLI requires `--start-date`, `--end-date`, `--staging-table` and `--confirm-sample-write`; it re-reads the staging row count after bounded inserts. Never touch the Prod final table.

### 10.4 Guarded apply (P5B)

P5B 的 apply 实现分为 writer 和 admin 两条连接，且不把 admin 连接装入 Dagster runtime resource：

- writer 只执行 50,000 行批量 `INSERT`；
- admin 负责 `CREATE TABLE ... AS target`、`RENAME TABLE` 和成功后的 staging/backup 清理；
- apply 只接受 `local|prod|both`，必须同时提供 P5A plan fingerprint、`--confirm-clickhouse-write`、`--confirm-target-empty` 和显式 staging 表名；
- apply 在参数、fingerprint、目标表存在且为空、staging schema 通过前，不建立 writer 写连接；
- writer 不执行任何 DDL。当前 Prod writer 的权限事实已经证明不能承担 staging 建表或 rename；
- native `9000` 隧道不能直接当作 Flyway JDBC HTTP 连接，Flyway 管理连接必须单独核验。

切换边界：

1. Freeze the 611-date plan and fingerprint.
2. Confirm target exists and is empty, with explicit approved state.
3. Admin creates a unique staging table using the target schema.
4. Read Gold through DuckDB in batches of about 50,000 rows.
5. Insert using explicit columns.
6. Record rows, elapsed time, failures and retries per batch.
7. Audit staging schema/count/date/key before any rename.
8. Admin performs a controlled atomic table switch after audit passes.
9. Read-only verify the final table; retain a named backup until post-switch verification completes.
10. Emit batch, audit and reconciliation reports; backup cleanup is a separate explicit admin action.

A non-empty target stops by default; no `--overwrite` bypass is allowed.

## 11. Event boundary

Physical loading and Dagster event writing are separate:

1. complete Gold -> local CH -> Prod CH reconciliation;
2. plan serving materialization/check events separately;
3. materialization may be backfilled for all historical dates;
4. checks default to the latest 20 dates to avoid recreating high-cardinality history;
5. every event must carry the correct partition.

Event failure does not roll back reconciled ClickHouse business rows; it becomes a separate maintenance report.

## 12. Test matrix

### 12.1 Contract/static

- table name, column order, types, partition and order key fixed;
- business key includes `category`;
- NULL is not converted to zero;
- local/Prod assets use `cn_a_dc_daily_trade_days`;
- checks are partitioned and single-partition guarded;
- jobs do not create tables or contain business SQL;
- sensors do not call `get_event_records`;
- Bootstrap does not call the Dagster instance.

### 12.2 Serving writer

- normal single-date Gold read;
- invalid target date, duplicate Gold key, date mismatch and schema mismatch fail closed;
- MA/BOLL NULL reaches ClickHouse unchanged;
- local/Prod count mismatch fails;
- healthy existing date can be idempotently skipped;
- unhealthy existing date is not automatically overwritten.

### 12.3 Bootstrap

- dry-run performs no ClickHouse write;
- `apply` requires explicit target, plan fingerprint, writer/admin prefixes and both confirmation flags;
- sample requires an explicitly bounded date range and isolated staging table;
- fingerprint mismatch rejects apply;
- staging failure cannot switch the final table;
- staging row count is re-read after insert and must equal the inserted count;
- batch statistics for approximately 50,000 rows are correct;
- failed apply preserves an auditable staging report and does not delete the old table;
- 611 dates, 596,200 rows and zero duplicate keys reconcile with Gold;
- no 611 Dagster runs are generated.

### 12.4 Performance

Record DuckDB scan, ClickHouse insert, staging audit, final audit, batch count, rows per batch, peak memory, staging size, 10-day sensor elapsed time and query count. Dagster event-history calls must be zero.

Reject: unbounded globbing, full Python row loops, 611 launches, 611 single-row inserts, sensor RPC overrun or failed writes that overwrite old targets.

## 13. Execution steps and approval gates

### P0: read-only audit

- read Prod Flyway head, target database and table permissions;
- audit production query consumers;
- confirm no same-name target conflict.

### P1: DDL

- add V4 migration;
- local validate/smoke;
- execute Prod migration only after separate approval.

### P2: serving code

- 2026-07-16 已完成本地 serving contract、asset、单一 blocking check、job、batch readiness 和默认 STOPPED sensor；已通过 fake ClickHouse/临时 Gold Parquet 测试及静态门禁。
- P2 不包含 Prod sync；Prod sync 单独作为下一阶段 P3 实现，避免在本地 serving 未闭环前扩大写入边界。
- 测试只使用 fake/临时目标，不连接 Prod ClickHouse。

### P3: Prod sync code

- 已实现 Prod sync asset、合并 core check、job、双端 bounded readiness 和默认 `STOPPED` sensor。
- Prod asset 只接受单分区，读取本机 ClickHouse 显式列后复用同步 replace helper；不在 asset 内建表或读取 Dagster event history。
- Prod check 对比 local/Prod 业务行集合、字段、日期、主键、参数版本和 `updated_at`；check event 通过 `partitions_def=cn_a_dc_daily_trade_days` 归属到单一交易日。
- Prod sensor 每 tick 最多一个 RunRequest，最近 10 日最多执行一次本机批量查询和一次 Prod 批量查询；local 未 ready 或既有目标 check 失败时均不自动提交。
- 已通过 P3 针对性测试、治理矩阵、静态门禁和 `dg check defs`；P3 代码阶段未执行 Prod DDL、业务写入、事件写入或 sensor 启用。

### P4: Bootstrap planner and sample staging

- implement source-only `dry-run` and `audit`;
- implement bounded one-to-three-date sample staging with explicit isolated table;
- run local unit/static tests and inspect the generated report shape;
- do not connect the formal target or Prod ClickHouse in this phase.

### P5: full Bootstrap

- P5B-1 已实现独立的 guarded `apply` path：CLI 先校验 source plan/fingerprint 和显式确认，再由 admin 连接完成目标空表与 staging 预检，最后才建立 writer 连接并执行批量 INSERT。
- `target=both` 按 local -> prod 串行执行，Prod 需要独立的 writer/admin 环境前缀；任一目标失败即停止，不做补偿性删除。
- P5B-2 sample 使用 `goldenshare_serving.staging_dc_daily_technical_p5b2_20260716`，覆盖 2024-01-02 至 2024-01-04，2,820 行逐字段源湖对账一致，重复主键为 0；报告保存在 `/private/tmp/dc_daily_technical_clickhouse_p5b2_sample_20260716.json` 和 `/private/tmp/dc_daily_technical_clickhouse_p5b2_audit_20260716.json`。
- P5B-3 已完成正式 DDL：local/Prod 均使用 Flyway V3 baseline + V4 migrate，schema、目标空表和 migration head=V4 已核验。
- P5B-3 已完成权限隔离：Prod writer 对目标为 `SELECT, INSERT, ALTER DELETE`，对本次 staging 为 `SELECT, INSERT`；CREATE、RENAME、DROP 仍只由 admin 执行。
- P5B-3 local 全量 apply 报告：`/private/tmp/dc_daily_technical_clickhouse_p5b3_local_apply_20260716.json`；Prod 全量 apply 报告：`/private/tmp/dc_daily_technical_clickhouse_p5b3_prod_apply_20260716.json`。
- P5B-3 三方全量对账报告：`/private/tmp/dc_daily_technical_clickhouse_p5b3_full_reconciliation_20260716.json`。Gold、local、Prod 均为 611 个交易日、596,200 行、596,200 个唯一业务键；local/Prod 逐日业务值哈希无差异。
- 两端旧空目标均保留为 `board_fact_technical_daily__prebootstrap_dc_daily_technical_full_20260716_{local|prod}`，未执行清理。
- P5B-4 `ch_dc_daily_technical` 事件补录已完成：历史 611 个 materialization、最近 20 个 `ch_dc_daily_technical_core_check`；只读预检报告为 `/private/tmp/ch_dc_daily_technical_event_backfill_preflight_20260717.json`，正式补录及 post 验收报告为 `/private/tmp/ch_dc_daily_technical_event_backfill_apply_20260717.json`。
- P5B-4 验收结果：611/611 materialization、20/20 partitioned check，未分区 check=0、check 绑定错误=0、失败 check=0、目标 materialization 不匹配=0；ClickHouse 业务表前后均为 611 个交易日、596,200 行；active runs=0，`prod_ch_dc_daily_technical` 未被触碰。
- P5B-3 已按上述顺序完成：重用已冻结的 P5A fingerprint，完成两端空目标确认、staging 批量加载、全量审计和 admin controlled switch。

### P6: daily automation

- event backfill was completed after P5B-3 physical data passed;
- observe single-date operation;
- keep sensors enabled only after at least 3 real trading days of observation.

Every step stops on failure; no range expansion or phase skipping.

## 14. Remaining approval

Remaining approval:

1. Approve Prod DDL separately from code development.

Confirmed: table name `goldenshare_serving.board_fact_technical_daily`; use the two-stage local ClickHouse -> Prod ClickHouse serving architecture; accept the serving-only `updated_at` column; backfill all materializations but retain only the latest 20 days of checks.
