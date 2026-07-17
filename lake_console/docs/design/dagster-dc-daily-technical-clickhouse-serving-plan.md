# `gold_dc_daily_technical` ClickHouse Serving 与 Prod 回写技术方案

更新时间：2026-07-17

状态：P5B-3 正式 DDL、Prod writer 最小权限、local/Prod 全量 Bootstrap 与三方对账已完成；P5B-4 `ch_dc_daily_technical` Dagster materialization/check event 已补齐，P5B-5 sensor 运行观察尚未执行。本方案继续冻结架构、表契约、Bootstrap、事件和自动化边界。

已确认口径：采用本地 ClickHouse serving -> Prod ClickHouse sync 两阶段架构；目标表名冻结为 `goldenshare_serving.board_fact_technical_daily`；serving 表增加 `updated_at`；历史 materialization 全量补齐，check event 只保留最近 20 个交易日。

## 1. 背景与目标

`gold_dc_daily_technical` 已经在数据湖中生成板块日线技术指标，字段包括 MA、KDJ、MACD、BOLL 和指标版本信息。下一步需要把这份 Gold 数据映射到 Prod ClickHouse，供生产查询和展示使用。

本方案的目标是：

1. 为 `gold_dc_daily_technical` 建立 ClickHouse serving 表。
2. 保持 Parquet Gold 为唯一事实源，ClickHouse 只作为查询副本。
3. 复用当前已经验证的“本地 ClickHouse serving -> Prod ClickHouse sync”架构。
4. 支持历史全量 Bootstrap 和后续单交易日自动更新。
5. 保持指标的 NULL 预热语义，不把无效指标转换成 0。
6. 不通过 611 个历史 Dagster run 执行全量回灌，不在 sensor 热路径扫描历史事件。

当前阶段明确不做：

- 不从 ClickHouse 反向生成 Gold 或 Silver。
- 不修改 `gold_dc_daily_technical` 指标公式、字段和湖文件布局。
- 不把 Prod ClickHouse 建表逻辑写进 asset。
- 不执行 P5B-5 的 sensor 启用和连续交易日运行观察。

## 2. 现状审计

### 2.1 Gold 湖事实

当前正式湖文件只读审计结果：

| 项目 | 当前事实 |
| --- | ---: |
| 文件数 | 611 |
| 行数 | 596,200 |
| 日期范围 | 2024-01-02 至 2026-07-14 |
| 板块分类 | 行业、概念、地域 |
| 序列数 | 1,065 个 `(ts_code, category)` |
| 日行数 | 940 至 1,024，平均约 976 |
| 业务主键重复 | 0 |
| 湖文件大小 | 约 80 MB |

Gold 物理布局为：

```text
gold/board/dc_daily_technical/trade_date=YYYY-MM-DD/part-000.parquet
```

当前 NULL 事实：`ma_250`、BOLL 和其它 MA 预热字段存在 NULL；KDJ/MACD 当前样本没有 NULL。因此 ClickHouse 目标表必须保留 MA/BOLL 的 Nullable 语义，不能用 0 填充预热期。

### 2.2 当前 Gold 代码链路

当前代码已经具备：

- `gold_dc_daily_technical` 分区 Gold asset。
- `cn_a_dc_daily_trade_days` 分区集。
- DuckDB set-based 指标计算。
- Gold 核心 blocking check：`gold_dc_daily_technical_core_check`。
- Gold normal update job、sensor 和 bounded repair job/sensor。
- Gold 文件对账和 Dagster event 验收能力。

当前没有：

- 本地 ClickHouse `dc_daily_technical` serving 表。
- Prod ClickHouse `dc_daily_technical` 表。
- `ch_dc_daily_technical` 本地 serving asset。
- `prod_ch_dc_daily_technical` Prod sync asset。
- 对应 ClickHouse checks、jobs、sensors。

### 2.3 既有 serving 参考实现

现有 `ch_share_fact_market_breadth_daily` 和 `prod_ch_share_fact_market_breadth_daily` 已验证以下模式：

```text
Gold Parquet
    -> 本地 ClickHouse serving asset
    -> 本地 ClickHouse
    -> Prod ClickHouse sync asset
    -> Prod ClickHouse
```

Prod sync 使用独立 `prod_clickhouse` resource，并按单个 `trade_date` 做同步 replace。表结构由 ClickHouse Flyway migration 管理，不由 Dagster asset 临时创建。

本专项沿用该模式，不新增第二种 Prod 写回架构。

## 3. 总体架构

### 3.0 P0 只读核验结果（2026-07-16）

- Prod ClickHouse 版本为 `26.5.1.882`，数据库为 `goldenshare_serving`，时区为 `Asia/Shanghai`。
- Prod Flyway schema history 当前 head 为 `V3`；`V1`、`V2`、`V3` 均已成功安装，`flyway validate` 通过。
- `goldenshare_serving.board_fact_technical_daily` 在 P0 时不存在；P5B-3 已由两端 Flyway V4 建立为空表。
- `goldenshare_sync_writer` 在 P0 时仅拥有现有 `share_fact_market_breadth_daily` 的查询、插入和数据变更权限，没有建表 DDL 权限；P5B-3 已补齐新目标和隔离 staging 的最小权限。
- 仓库内未发现新 serving 表的 API 或前端查询消费者；当前排序键建议仍为 `(trade_date, category, ts_code)`。

结论：P0 只读冻结通过，可以进入 P1。本阶段只新增本地 V4 migration 和 contract 测试，不执行 Prod DDL。

### 3.1 正常日常链路

```text
silver_dc_daily[trade_date]
    -> gold_dc_daily_technical[trade_date]
    -> ch_dc_daily_technical[trade_date]
    -> prod_ch_dc_daily_technical[trade_date]
```

其中：

- Gold Parquet 是指标事实源。
- 本地 ClickHouse 是本机查询副本。
- Prod ClickHouse 是生产查询副本。
- Dagster 只负责生成、校验、同步和观测，不把 ClickHouse 数据再写回湖。

### 3.2 为什么不直接 Gold -> Prod

直接 Gold -> Prod 的代码量较少，但会绕开当前已经存在的本地 serving 校验和链路，形成第二套不同的同步模式。正常运行采用两段 serving；历史 Bootstrap 可以使用独立批量加载器分别填充本地和 Prod，但必须使用同一份 Gold 输入、同一份校验规则和同一份批次报告。

## 4. ClickHouse 表契约

目标表名已按现有命名规则冻结为：

```text
goldenshare_serving.board_fact_technical_daily
```

### 4.1 业务字段

业务字段与 Gold schema 一一对应：

```text
ts_code trade_date category close
ma_5 ma_10 ma_15 ma_20 ma_30 ma_60 ma_120 ma_250
kdj_k kdj_d kdj_j macd_dif macd_dea macd
boll_mid boll_upper boll_lower observation_count
params_key indicator_version
```

### 4.2 ClickHouse 类型建议

```text
ts_code            LowCardinality(String)
trade_date         Date
category           LowCardinality(String)
close              Float64
ma_5..ma_250       Nullable(Float64)
kdj_k..macd        Float64
boll_mid..lower    Nullable(Float64)
observation_count  UInt32
params_key         LowCardinality(String)
indicator_version  LowCardinality(String)
updated_at         DateTime
```

`updated_at` 是 serving 审计字段，不属于 Gold 业务事实；时区语义与现有 serving 表保持一致，最终以 Prod ClickHouse 只读核验结果冻结。

建议 DDL：

```sql
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY (trade_date, category, ts_code)
```

当前主要查询应是某交易日的板块指标，月分区约 31 个，不会产生 611 个小分区。ClickHouse 官方建议按高频过滤条件设计排序键，并把分区主要用于生命周期管理。[主键与排序键建议](https://clickhouse.com/docs/best-practices/choosing-a-primary-key) [分区键建议](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)

仓库内暂未发现该表的既有 API 查询消费者，因此正式建表前必须完成一次消费者查询审计。若生产查询以单板块长时间序列为绝对主场景，需要在 DDL 冻结前重新评估 `ORDER BY`。

## 5. Schema migration

新增：

```text
lake_console/orchestrator/clickhouse_migrations/sql/V4__create_dc_daily_technical.sql
```

要求：

1. 先只读核对 Prod Flyway 当前 head，不能凭仓库文件名假定线上版本。
2. `V4` 必须接真实 Flyway head。
3. migration 只负责创建数据库表，不负责装载业务数据。
4. 不修改 V1/V2/V3。
5. 不在 Dagster asset 内执行 `CREATE TABLE`、`ALTER TABLE` 或 `DROP TABLE`。
6. 正式 Flyway 使用具备 DDL 权限的管理账号；`prod_clickhouse` writer 账号只负责数据写入。
7. DDL 之前必须审批目标主机、Flyway head、表名、字段、分区、排序键和回滚方式。

## 6. 历史全量 Bootstrap

Bootstrap 使用独立的非 Dagster CLI/runner，不启动 611 个 Dagster run，不启用 sensor，不在 Bootstrap 中写 Dagster event。输入只来自 Gold Parquet，不访问 Tushare、Prod DB 或 Dagster event history。

```text
Gold Parquet
    -> DuckDB set-based schema/date/key/row audit
    -> bounded batch scan
    -> ClickHouse staging table
    -> staging 全量审计
    -> 受控切换为正式表
```

当前 596,200 行建议以约 50,000 行为一个 insert batch，预计约 12 个批次。ClickHouse 官方建议按场景使用批量插入策略。[插入策略建议](https://clickhouse.com/docs/best-practices/selecting-an-insert-strategy)

安全规则：

- 使用显式列清单，不使用 `SELECT *`。
- staging 校验通过前，正式表不切换。
- 校验失败不覆盖既有表，保留有限错误样本和报告。
- 不使用 mutation 做全量修正。[Mutation 建议](https://clickhouse.com/docs/best-practices/avoid-mutations)
- 切换使用同库受控 `RENAME TABLE` 或等价方案，具体语义需在目标版本验证。[RENAME TABLE 说明](https://clickhouse.com/docs/sql-reference/statements/rename)

## 7. 日常同步与自动化

### 7.1 本地 serving

新增 `ch_dc_daily_technical` asset、一个合并核心 check、`ch_dc_daily_technical_update_job` 和 bounded continuity sensor。使用 `cn_a_dc_daily_trade_days`，每次只处理一个日期，从 Gold Parquet 读取显式列，执行幂等单日 replace。

### 7.2 Prod sync

新增 `prod_ch_dc_daily_technical` asset、一个合并核心 check、`prod_ch_dc_daily_technical_sync_job` 和 bounded continuity sensor。使用现有 `prod_clickhouse` resource，上游必须是本地 serving 同日 ready，每次只处理一个日期。目标已存在但核心 check 失败时不自动覆盖。

## 8. Check 与 readiness

本地 serving 和 Prod sync 各保留一个合并核心 blocking check，不按每个指标拆 check。

核心语义：

1. 目标日期数据存在且行数大于 0。
2. schema 与表契约一致。
3. `trade_date` 与分区一致。
4. `(ts_code, trade_date, category)` 非空且唯一。
5. 行数与 Gold 同日事实一致。
6. `params_key`、`indicator_version` 一致。
7. MA/BOLL 预热 NULL 语义保持不变。
8. Prod sync 行集合和业务字段与本地 serving 一致。

公式正确性由 Gold 独立 fixture 和 Gold check 体系负责；Serving check 不再次计算指标公式。

Readiness 只读最近 10 个 expected dates，使用 ClickHouse 分区查询和 Gold 文件事实，不逐日读取 Dagster event history。

## 9. 性能预算

| 路径 | 预算和硬门禁 |
| --- | --- |
| 历史 Gold scan | 一次 DuckDB set-based 扫描，显式投影，不逐行 Python 计算 |
| 历史 ClickHouse load | 596,200 行，建议约 50,000 行/批，约 12 批 |
| 日常本地同步 | 单日约 940-1,024 行，单分区 replace |
| 日常 Prod sync | 单日约 940-1,024 行，单分区 replace |
| sensor readiness | 最近 10 个日期，每个系统一次批量查询 |
| Dagster event history | 热路径 0 次 |
| 不可接受 | 611 个 Dagster run、611 次小 INSERT、全历史 event 扫描、无界 Parquet glob |

必须记录 DuckDB scan、ClickHouse insert、审计、批次数、峰值内存、staging 大小和 sensor 查询次数。超过预算时 fail closed，不通过调高 RPC timeout 掩盖。

## 10. 推进阶段

### P0：只读冻结

- 读取 Prod Flyway head、目标数据库和表权限。
- 审计生产查询消费者和实际过滤条件。
- 冻结表名、字段、NULL、`PARTITION BY`、`ORDER BY`。

### P1：Migration

- 新增 `V4__create_dc_daily_technical.sql`。
- 本地 migration 验证。
- 经单独批准后执行 Prod DDL。

### P2：本地 Serving

- 新增本地 serving asset/check/job/sensor/readiness。
- 2026-07-16 已完成源码和本地 fake/临时 Parquet 联调；本地 serving asset、单一 partitioned blocking check、job、最近 10 日 batch readiness 和默认 STOPPED sensor 已落地。
- P2 测试与静态门禁通过；未连接 Prod ClickHouse、未执行 DDL、未启用 sensor。

### P3：Prod Sync

- 已新增 `prod_ch_dc_daily_technical` Prod sync asset、`prod_ch_dc_daily_technical_core_check` 合并 blocking check、`prod_ch_dc_daily_technical_sync_job` 和默认 `STOPPED` 的 `prod_ch_dc_daily_technical_continuity_sensor`。
- Prod asset 只读取本机 ClickHouse serving 的同日显式列，复用单分区 delete-then-insert helper 写入 Prod；多分区上下文 fail closed。
- Prod check 比较本机/Prod 的业务主键、业务字段、参数版本和 `updated_at` 新鲜度，使用同一分区定义，不拆出高基数指标 checks。
- Prod readiness 对最近 10 个 expected dates 做一次本机查询和一次 Prod 查询；本机未 ready 时不提交 Prod run，已 materialize 但 check 失败时不自动覆盖。
- P3 本地测试、治理矩阵、静态门禁和 `dg check defs` 已通过；代码阶段仍不执行 Prod DDL、业务数据写入、事件写入或 sensor 启用。

### P4：历史 Bootstrap

- 已新增独立只读计划器和 CLI：
  `defs/bootstrap/dc_daily_technical_clickhouse_bootstrap.py`、
  `defs/bootstrap/dc_daily_technical_clickhouse_bootstrap_cli.py`。
- 当前 CLI 开放 `dry-run`、`audit`、`sample` 和受显式确认保护的 `apply` 子命令；apply 仍不访问 Dagster instance、不写 Dagster event。
- `dry-run/audit` 使用一次 DuckDB 批量 Gold 审计，生成日期计划、行数、文件数、字节数、批次数和稳定 fingerprint。
- `sample` 必须显式指定起止日期，最多 3 个交易日，且必须指定 `tmp_`/`staging_` 隔离表和确认参数；写入后重新读取 staging 行数对账，禁止触碰正式 serving 表。
- P4 专项回归已通过：139 个测试、70 个子测试；`dg check defs` 成功，`git diff --check` 成功。
- P4 代码阶段尚未执行本地 ClickHouse sample，也未连接 Prod ClickHouse；后续 P5B-2/P5B-3 已完成相应操作。
- 正式 DDL、正式 Bootstrap 和表切换另列为 P5，仍需单独批准目标状态、DDL 权限、空表/备份确认和批次写入。

### P5A：正式 Bootstrap 前只读审计

- 首次正式 lake dry-run 发现交易日历包含 `1990-12-19` 至 `2026-12-31` 的 `8,797` 个 SSE 开市日，而 Gold 实际只有 `2024-01-02` 至 `2026-07-14` 的 `611` 个文件；旧 planner 因此正确 fail-closed，但 expected-date 选择实现过宽。
- 已修正 planner：默认起点使用 `DC_DAILY_TECHNICAL_HISTORY_START_DATE`，默认终点使用 Gold 现有分区文件最新日期；显式指定超出 Gold 覆盖的终点仍会因缺文件停止。
- 修正后的正式 lake dry-run 报告：
  `/private/tmp/dc_daily_technical_clickhouse_p5a_dry_run_20260716_v2.json`
- 报告结果：`611` 日期、`611` 文件、`596,200` 行、`82,447,853` 字节、`12` 批、失败日期 `0`、`should_stop=false`。
- 只读 ClickHouse 审计仍确认：本机和 Prod 目标表均不存在；Prod writer 只有目标既有表的 SELECT/INSERT/数据变更权限，没有 DDL 权限；两端版本和时区符合冻结口径。
- Prod writer 当前没有新目标或动态 staging 表的权限。正式 DDL 不能只创建表：管理员必须按最小权限授予目标表的日常同步权限，并为本次 staging 表授予 `SELECT`/`INSERT`；apply 在读取 Gold 前会通过 staging 的 schema/访问预检尽早 fail-closed。

### P5B：正式 DDL、Bootstrap、事件与自动化

- 正式 Bootstrap 的 apply 必须区分两个 ClickHouse 身份：writer 只执行批量 INSERT，admin 执行 staging 建表、原子 rename 和最终清理；不能让 writer 在加载中途才发现没有 DDL 权限。
- apply 必须显式传入 `local|prod|both`、P5A 报告 fingerprint、空目标确认、写入确认和隔离 staging 表；缺少任一项时不得建立 writer 写连接。
- staging 只允许使用同库、ASCII、唯一的 `staging_`/`tmp_` 表名；staging schema、逐日行数和业务主键审计通过后，才允许 admin 原子切换。
- 正式 DDL 由 Flyway 管理账号执行，writer 账号不执行 `CREATE`、`RENAME`、`DROP`；当前 native 隧道不直接作为 Flyway JDBC URL，需使用已验证的管理连接方式。
- P5B-1 guarded apply 代码已完成：参数/fingerprint/空目标/staging 预检、writer/admin 分离、50,000 行批量 INSERT、staging 对账和 admin 原子切换均已落到独立 CLI；`both` 会按 local -> prod 串行执行，并要求两套身份前缀。
- P5B-1 本地测试已通过；未执行正式 apply、DDL、Prod ClickHouse 表写入或 Dagster 事件写入。
- P5B-2 本地隔离 sample 已完成：staging 表 `goldenshare_serving.staging_dc_daily_technical_p5b2_20260716` 写入 2024-01-02 至 2024-01-04 共 2,820 行，逐字段源湖对账一致，重复主键为 0；当时正式目标表仍不存在。报告：`/private/tmp/dc_daily_technical_clickhouse_p5b2_sample_20260716.json`、`/private/tmp/dc_daily_technical_clickhouse_p5b2_audit_20260716.json`。
- P5B-3 已完成正式落地：local/Prod 均通过 Flyway 以 V3 baseline + V4 migrate 建表，目标 schema 与 contract 一致，空目标预检通过。
- Prod `goldenshare_sync_writer` 已获得 `board_fact_technical_daily` 的 `SELECT, INSERT, ALTER DELETE`，以及本次隔离 staging 的 `SELECT, INSERT`；没有授予 `CREATE`、`RENAME` 或 `DROP`。
- local 全量 Bootstrap 成功：611 个交易日、596,200 行、12 批；Prod 全量 Bootstrap 成功：611 个交易日、596,200 行、12 批。两端均通过 staging 审计、目标审计和唯一键审计，旧空目标保留为 `__prebootstrap_...` 备份表。
- 三方全量对账通过：Gold Parquet、local ClickHouse、Prod ClickHouse 的日期集合、逐日行数、逐日业务主键数一致；local/Prod 逐日业务值哈希无差异。报告：`/private/tmp/dc_daily_technical_clickhouse_p5b3_full_reconciliation_20260716.json`。
- apply 报告：`/private/tmp/dc_daily_technical_clickhouse_p5b3_local_apply_20260716.json`、`/private/tmp/dc_daily_technical_clickhouse_p5b3_prod_apply_20260716.json`。
- 物理数据验收已通过；P5B-4 事件补录和 P5B-5 sensor 运行验收分开执行。
- P5B-4 `ch_dc_daily_technical` 事件补录已完成：历史 611 个 materialization 全量存在，最近 20 个交易日的 20 个 `ch_dc_daily_technical_core_check` 全量存在；只读预检报告为 `/private/tmp/ch_dc_daily_technical_event_backfill_preflight_20260717.json`，正式补录及 post 验收报告为 `/private/tmp/ch_dc_daily_technical_event_backfill_apply_20260717.json`。
- P5B-4 验收结果：611/611 materialization、20/20 partitioned check，未分区 check=0、check 绑定错误=0、失败 check=0、目标 materialization 不匹配=0；ClickHouse 业务表前后均为 611 个交易日、596,200 行；active runs=0，`prod_ch_dc_daily_technical` 未被触碰。
- P5B-5 才执行 sensor 启用和至少 3 个真实交易日的运行观察。

## 11. 验收标准

- 表结构与 Gold contract 一致。
- 611 个日期和 596,200 行全量对账一致；Gold、local、Prod 三方逐日行数和唯一键一致，local/Prod 业务值哈希一致。
- 主键重复为 0。
- 本地/Prod 行数一致。
- MA/BOLL NULL 预热语义一致。
- staging 无未解释残留。
- 日常单日 replace 幂等。
- sensor 不读取 Dagster event history。
- 历史 materialization/check event 归属正确，最近 20 日 check 全部绑定最新 materialization。
- 写入失败不覆盖旧目标。
- Prod writer 账号不具备 DDL 权限；仅拥有新目标的 `SELECT, INSERT, ALTER DELETE` 和本次 staging 的 `SELECT, INSERT`。
- 不修改 Gold 湖文件。

P5B-3 和 P5B-4 已按 LLD 完成。下一阶段只处理 sensor 启用与运行观察，不改变 ClickHouse 数据、表结构或历史事件。

## 12. 当前待确认

1. P5B-5 是否单独批准并启用 sensor，观察至少 3 个真实交易日。

已确认：表名 `goldenshare_serving.board_fact_technical_daily`、两阶段 serving 架构、`updated_at` serving 字段、materialization 全历史补齐与 check event 最近 20 日保留口径。
