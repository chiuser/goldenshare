# Dagster ClickHouse Serving 接入设计

更新时间：2026-05-28

## 1. 背景与目标

本地 ClickHouse 已完成基础安装、Flyway migration、Dagster resource 接入、第一张 serving asset 定义、serving checks / job 接入、serving automation 入口定义、历史补齐和小范围运行验收。当前代码已经安装 `dagster-clickhouse==0.29.6`，并把官方 `ClickhouseResource` 注册为 Dagster resource；serving automation sensor 默认 `STOPPED`，是否长期启用由运营验证后决定。

本设计目标是：让 Dagster 把已经生成的 Parquet gold 资产同步到本地 ClickHouse serving 表，并用 Dagster assets、jobs、checks 和 automation 管理 ClickHouse 表的数据状态。

第一版只做本地 serving：

1. 不涉及生产 ClickHouse。
2. 不涉及 prod 发布。
3. 不改变 Parquet 数据湖作为事实源的地位。
4. 不让 ClickHouse 反向成为 raw / silver / gold 的事实来源。

## 2. 本轮依据与当前事实

### 2.1 已阅读规范

本方案落档前已按门禁阅读：

1. 仓库根 `AGENTS.md`。
2. `lake_console/AGENTS.md`。
3. `lake_console/orchestrator/AGENTS.md`。
4. `lake_console/orchestrator/CODING_STANDARDS.md`。

本方案遵守以下关键规则：

1. 不乱建目录，新设计文档继续放在 `lake_console/docs/design/`。
2. Dagster job 只做 asset selection，不写业务 SQL、不连 ClickHouse。
3. Resource 只负责外部系统连接。
4. Asset 负责资产如何生成。
5. Checks 负责资产是否合格。
6. 表结构变更必须有版本管理，不能散落在 asset 代码中。
7. 未经确认不执行正式 Dagster run、job、sensor、backfill 或 materialize。

### 2.2 当前代码事实

当前 `lake_console/orchestrator/pyproject.toml` 依赖包含：

```text
dagster==1.13.6
dagster-clickhouse==0.29.6
dagster-postgres>=0.29.6
duckdb>=1.5.2
psycopg2-binary>=2.9.12
tushare>=1.4.20
```

当前 ClickHouse runtime 依赖会额外安装：

```text
clickhouse-driver
tzlocal
```

当前已接入：

```text
ClickhouseResource
ClickHouse migration
ClickHouse serving 数据库
ClickHouse serving 表契约
ClickHouse serving asset
ClickHouse serving checks
ClickHouse serving job
ClickHouse serving automation sensor
ClickHouse serving 单日、小范围 backfill 与历史补齐验收
```

当前尚未默认长期启用：

```text
ClickHouse serving 默认长期自动化
```

当前已存在的直接上游 gold assets：

```text
gold_market_breadth_daily[trade_date]
gold_stock_return_distribution[trade_date]
```

这两个资产都直接依赖 `silver_stock_daily[trade_date]`，并且已经通过各自 gold checks 管理数据质量。

重构后当前代码对照：

```text
defs/assets/market_breadth.py
  gold_market_breadth_daily
  automation_condition = eager() & all_deps_blocking_checks_passed()

defs/assets/stock_return_distribution.py
  gold_stock_return_distribution
  automation_condition = eager() & all_deps_blocking_checks_passed()

defs/jobs/daily_market_breadth.py
  daily_market_breadth_job
  只选择 gold_market_breadth_daily + 对应 checks

defs/jobs/stock_return_distribution_daily.py
  stock_return_distribution_daily_job
  只选择 gold_stock_return_distribution + 对应 checks

defs/sensors/market_breadth_automation_sensor.py
  market_breadth_automation_sensor
  只 target gold_market_breadth_daily，默认 STOPPED

defs/sensors/stock_return_distribution_automation_sensor.py
  stock_return_distribution_automation_sensor
  只 target gold_stock_return_distribution，默认 STOPPED
```

因此 ClickHouse serving 设计必须把这两个 gold assets 当作直接上游，不能回到旧的“普通 sensor 手写文件探测”或“下游补上游”的口径。

### 2.3 本地 ClickHouse 事实

当前本机 ClickHouse：

```text
binary: /Users/congming/.goldenshare/clickhouse/bin/clickhouse
version: 26.6.1.141
config: /Users/congming/.goldenshare/clickhouse/config/config.xml
data: /Users/congming/.goldenshare/clickhouse/data/
```

当前配置：

```text
listen_host = 127.0.0.1
http_port = 8123
tcp_port = 9000
interserver_http_port = 9009
```

只读核验结果：

1. HTTP `8123` 可用，`SELECT version()` 返回 `26.6.1.141`。
2. native `9000` 正在监听 `127.0.0.1:9000`。
3. 在 Codex 沙箱内直接连 native `9000` 可能报 `Operation not permitted` 或 I/O error，这是沙箱网络限制，不代表 ClickHouse 配置失败。
4. 经批准在沙箱外执行 native client，`SELECT version(), currentDatabase()` 返回 `26.6.1.141 default`。
5. Slice CH-1 已通过 Flyway 创建 `goldenshare_serving` 数据库和 `goldenshare_serving.share_fact_market_breadth_daily` 空表；Slice CH-2 已接入 Dagster resource；Slice CH-3 已接入 serving asset；Slice CH-4 已接入 serving checks 和 job；Slice CH-5 已定义 automation 入口，默认 `STOPPED`；Slice CH-6 的单日 checks 验收、小范围 backfill 验收和历史补齐已由用户完成。

本地已知坑：

1. native `9000` 真实可用，但 Codex 默认沙箱内可能无法直接验证；涉及 native 连通性验证时，需要用户批准正式命令或由用户在本机执行。
2. 日志历史中曾出现 `Cannot resolve host (bogon)`；当前配置已包含 `disable_internal_dns_cache=1`，本方案不把它视为阻塞。
3. ClickHouse 数据目录位于本机固定磁盘，不在移动 SSD；这符合之前“大火箭”安装口径。

## 3. 总体架构结论

ClickHouse 是本地 serving 副本层，不是事实源。

```text
Parquet 数据湖
  raw / silver / gold 事实源

ClickHouse
  serving 副本，用于本地 API 调试和查询加速

Dagster
  负责从 gold Parquet 装载到 ClickHouse，并管理状态、检查、回填和自动化
```

本轮采用组合方案：

```text
dagster-clickhouse
  提供官方 ClickhouseResource
  使用 native 9000
  负责连接 ClickHouse 与执行 SQL

Goldenshare 自己的 Dagster 资产代码
  负责业务语义
  负责读取 gold parquet
  负责合并字段
  负责 replace 写入
  负责 materialization metadata
  负责 serving checks

ClickHouse migration
  负责数据库和表结构版本管理
```

不用 `clickhouse-connect`，不走 HTTP `8123` 作为第一版 Python 接入主路径。

原因：

1. `dagster-clickhouse==0.29.6` 与当前 `dagster==1.13.6` 对齐。
2. `dagster-clickhouse` 官方包已经封装 `ClickhouseResource`，没有必要再自造一层基础连接 resource。
3. 当前本地 native `9000` 已真实可用。
4. 后续 ClickHouse serving 资产会越来越多，优先贴近 Dagster 官方维护集成更利于长期维护。

## 4. IO Manager 边界

### 4.1 IO Manager 用人话解释

IO Manager 是 Dagster 的“自动存取数据管家”。

当一个 asset 直接返回 DataFrame 或表状对象时，IO Manager 可以自动把这个返回值落到外部存储中，例如 ClickHouse 表。

适合它的场景：

```text
一个 asset
  产物本身就是目标表
  一对一写入 ClickHouse
  字段不需要复杂重组
  表结构和写入方式高度统一
```

不适合它的场景：

```text
多个 asset 合并成一张 serving 表
需要按 trade_date replace
需要字段取舍和一致性校验
表结构必须由 migration 控制
写入前后需要定制 checks
```

### 4.2 第一版不用 ClickHouse IO Manager

第一版不使用 `dagster-clickhouse-pandas` 的 IO Manager 自动落表。

原因：

1. 我们的第一张 serving 表不是一个 gold asset 一对一落库，而是两个 gold assets 合并。
2. 表结构必须由 migration 管理，不能由 DataFrame dtype 推断。
3. `dagster-clickhouse-pandas` 的 type handler 会按 DataFrame 自动 `CREATE TABLE IF NOT EXISTS`，这与“表结构必须走契约和 migration”的口径冲突。
4. serving asset 的 replace 语义、字段一致性校验、checks 都需要显式表达。

第一版使用：

```text
dagster_clickhouse.ClickhouseResource
```

第一版不使用：

```text
dagster_clickhouse_pandas.ClickhousePandasIOManager
clickhouse_pandas_io_manager
```

未来如果出现“一张 gold asset 直接对应一张 ClickHouse 表”的标准型落库场景，可以单独评估 IO Manager。

## 5. 第一个 Serving Asset

### 5.1 目标资产

第一版优先接入市场宽度 serving 表。

两个 gold 资产共同组成一个 ClickHouse serving asset：

```text
gold_market_breadth_daily[trade_date]
gold_stock_return_distribution[trade_date]
        ↓
ch_share_fact_market_breadth_daily[trade_date]
```

原因：

1. 这两个 gold 都服务“市场宽度 / 涨跌分布”类查询。
2. 本地 API 查询时更适合从一张 ClickHouse serving 表读取。
3. ClickHouse 表是查询副本，不是新的业务口径来源。
4. 业务计算仍在 gold Parquet assets 中完成。

### 5.2 Dagster asset 命名

```text
ch_share_fact_market_breadth_daily
```

含义：

```text
ch_
  ClickHouse serving asset

share_fact_
  行情事实类 serving 表

market_breadth_daily
  市场宽度日频表
```

分区：

```text
cn_a_stock_trade_days
```

上游：

```text
gold_market_breadth_daily[trade_date]
gold_stock_return_distribution[trade_date]
```

### 5.3 ClickHouse 表名

```text
goldenshare_serving.share_fact_market_breadth_daily
```

说明：

1. `goldenshare_serving` 是本地 serving 业务库。
2. `share_fact_` 是业务分类前缀。
3. 不使用三段式 `goldenshare_serving.share.fact.market_breadth_daily`。
4. ClickHouse 常规命名空间是 `database.table`，业务分类进入表名更清晰。

命名规则：

```text
goldenshare_serving.<business_domain>_<table_kind>_<subject>_<grain>
```

当前第一张表：

```text
business_domain = share
table_kind = fact
subject = market_breadth
grain = daily
```

未来可扩展：

```text
goldenshare_serving.share_analysis_*
goldenshare_serving.share_alert_*
goldenshare_serving.index_fact_*
```

## 6. 表结构契约

第一版字段来自两个 gold assets。

```text
trade_date Date

-- from gold_market_breadth_daily
up_count UInt32
down_count UInt32
flat_count UInt32
total_count UInt32
red_rate Float64

-- from gold_stock_return_distribution
down_gt_7_count UInt32
down_5_7_count UInt32
down_3_5_count UInt32
down_0_3_count UInt32
up_0_3_count UInt32
up_3_5_count UInt32
up_5_7_count UInt32
up_gt_7_count UInt32

-- serving metadata
updated_at DateTime
```

注意：

1. `flat_count` 已来自 `gold_market_breadth_daily`，不重复保存一份。
2. `total_count` 以 `gold_market_breadth_daily.total_count` 为主。
3. `gold_stock_return_distribution.total_count` 必须通过 check 与 `gold_market_breadth_daily.total_count` 一致。
4. `gold_stock_return_distribution.flat_count` 不进入 ClickHouse 表，但必须通过 check 与 `gold_market_breadth_daily.flat_count` 一致；否则说明两个 gold 资产对同一天的“平盘数量”口径或数据源出现偏差。
5. ClickHouse serving 表不重新计算这些字段，只保存 gold 结果的 serving 副本。

表引擎草案：

```sql
CREATE TABLE IF NOT EXISTS goldenshare_serving.share_fact_market_breadth_daily
(
    trade_date Date,
    up_count UInt32,
    down_count UInt32,
    flat_count UInt32,
    total_count UInt32,
    red_rate Float64,
    down_gt_7_count UInt32,
    down_5_7_count UInt32,
    down_3_5_count UInt32,
    down_0_3_count UInt32,
    up_0_3_count UInt32,
    up_3_5_count UInt32,
    up_5_7_count UInt32,
    up_gt_7_count UInt32,
    updated_at DateTime
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY trade_date
```

## 7. Migration 管理

ClickHouse 表结构需要版本化管理，不能把 DDL 散落在 asset 代码中。

采用 Flyway 管理 ClickHouse schema migration，不混入仓库根 PostgreSQL Alembic 主链。

推荐目录：

```text
lake_console/orchestrator/clickhouse_migrations/
  flyway.conf
  sql/
    V1__create_goldenshare_serving_database.sql
    V2__create_share_fact_market_breadth_daily.sql
```

原则：

1. 不使用 autogenerate。
2. migration 文件必须显式写 SQL。
3. asset 代码禁止偷偷 `CREATE TABLE` 或 `ALTER TABLE`。
4. 表结构变化必须新增 migration。
5. 已经执行成功的 migration 文件禁止修改；后续变化新增 `V3` / `V4`。
6. 不复用根目录 PostgreSQL Alembic 配置。

Flyway 的作用：

```text
读取 sql/ 下的 V*.sql 文件
按版本号顺序执行
在 ClickHouse 中维护 schema history 表
记录 version / script / checksum / installed_on / success
阻止已经执行过的 migration 文件被偷偷修改
```

本地执行方式：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
flyway -configFiles=clickhouse_migrations/flyway.conf info
flyway -configFiles=clickhouse_migrations/flyway.conf migrate
flyway -configFiles=clickhouse_migrations/flyway.conf validate
```

Flyway 通过 JDBC 连接 ClickHouse，第一版 migration 使用 HTTP `8123`；Dagster 运行时仍通过 `dagster-clickhouse` 使用 native `9000`。

这两个协议用途不同，不冲突：

```text
Flyway migration
  JDBC / 8123
  负责建库、建表、改表结构

Dagster runtime
  dagster-clickhouse / native 9000
  负责写 serving 数据、查 serving checks
```

`V1` / `V2` 规则：

```text
当前 V1 / V2 已经通过 flyway migrate 成功执行，已经成为历史事实，不能再回头改。
后续如果要加字段或改结构，必须新增 V3 / V4。
```

禁止使用 `flyway repair` 作为日常修复手段；只有在明确知道 schema history 需要修正、且经过用户确认后，才允许执行。

## 8. 写入语义

第一版采用按 `trade_date` replace 的写入语义。

执行 `ch_share_fact_market_breadth_daily[trade_date]` 时：

1. 读取 `gold_market_breadth_daily[trade_date]` parquet。
2. 读取 `gold_stock_return_distribution[trade_date]` parquet。
3. 校验两个 gold 文件都存在。
4. 校验两边 `trade_date` 一致。
5. 校验两边 `total_count` 一致。
6. 校验两边 `flat_count` 一致。
7. 在同一 ClickHouse 连接中执行 `SET lightweight_deletes_sync = 1`。
8. 删除 ClickHouse 目标表中同一 `trade_date` 的旧数据。
9. 删除后立即查询该日期行数，必须为 `0`，否则失败且不插入。
10. 插入合并后的 1 行 serving 数据。
11. 插入后立即查询该日期行数，必须为 `1`，否则失败。
12. 返回 materialization metadata。

伪流程：

```text
ch_share_fact_market_breadth_daily[date]
  read gold_market_breadth_daily parquet
  read gold_stock_return_distribution parquet
  validate same trade_date
  validate same total_count
  validate same flat_count
  SET lightweight_deletes_sync = 1
  DELETE FROM goldenshare_serving.share_fact_market_breadth_daily WHERE trade_date = date
  assert count(date) = 0
  INSERT INTO goldenshare_serving.share_fact_market_breadth_daily VALUES (...)
  assert count(date) = 1
  emit metadata
```

第一版不做 merge，不做 ClickHouse materialized view，不做异步队列。

同步语义说明：

1. `DELETE FROM` 在 ClickHouse MergeTree 中属于 lightweight delete；默认实现会标记删除，物理清理由后续 merge 完成。
2. CH-3 明确设置 `lightweight_deletes_sync = 1`，要求 delete 标记同步完成后再继续。
3. CH-3 在 delete 后立即执行同日 `count()` 断言，避免同一天重跑时旧行仍可见或重复插入。
4. 如果 delete 成功但 insert 失败，ClickHouse 当日 serving 副本可能暂时缺失；由于 ClickHouse 是副本层，重新运行同一分区即可恢复。

## 9. Checks 设计

`ch_share_fact_market_breadth_daily` 必须有自己的 checks，不能只依赖 gold checks。

第一版 checks：

```text
ch_share_fact_market_breadth_row_count_is_one
  ClickHouse 中当前 trade_date 只能有 1 行。

ch_share_fact_market_breadth_date_matches_partition
  ClickHouse 中 trade_date 必须等于 partition key。

ch_share_fact_market_breadth_total_count_matches_gold
  ClickHouse total_count 必须等于两个 gold asset 的 total_count。

ch_share_fact_market_breadth_flat_count_matches_gold
  ClickHouse flat_count 必须等于两个 gold asset 的 flat_count。

ch_share_fact_market_breadth_breadth_fields_match_gold
  up_count / down_count / flat_count / red_rate 必须等于 gold_market_breadth_daily。

ch_share_fact_market_breadth_distribution_fields_match_gold
  8 个非 flat 的收益率分桶必须等于 gold_stock_return_distribution。
```

说明：

1. ClickHouse serving 表是副本，checks 的核心是“副本是否与 gold 一致”。
2. 不在 ClickHouse checks 中重新定义涨跌幅业务口径。
3. 如果 CH 与 gold 不一致，CH asset check fail。

## 10. Job 与自动化

### 10.1 Job

新增 job：

```text
clickhouse_share_fact_market_breadth_update_job
```

selection：

```text
ch_share_fact_market_breadth_daily
checks_for_assets(ch_share_fact_market_breadth_daily)
```

禁止 selection：

```text
gold_market_breadth_daily
gold_stock_return_distribution
silver_stock_daily
raw_tushare_stock_daily
```

原因：

ClickHouse job 只负责 serving 同步，不负责补上游。

### 10.2 自动化

自动化是 ClickHouse serving 接入设计的一部分，不能省略。

第一阶段可以不默认开启，但必须实现和验证自动化入口。

正式自动化目标：

```text
ch_share_fact_market_breadth_daily automation:
  gold_market_breadth_daily[trade_date] materialized
  gold_market_breadth_daily blocking checks passed
  gold_stock_return_distribution[trade_date] materialized
  gold_stock_return_distribution blocking checks passed
  direct upstream gold assets updated
```

建议实现：

```text
ch_share_fact_market_breadth_daily
  automation_condition =
    eager()
    AND all_deps_blocking_checks_passed()

clickhouse_share_fact_market_breadth_automation_sensor
  target = ch_share_fact_market_breadth_daily
  default_status = STOPPED
  minimum_interval_seconds = 600
```

边界：

1. 不补上游。
2. 不调用 Tushare。
3. 不触发 `daily_market_breadth_job` 或 `stock_return_distribution_daily_job`。
4. 不默认处理全历史。
5. 不使用普通 sensor 手写重 IO readiness 逻辑。

验收：

1. 先保持 sensor `STOPPED`。
2. 手动确认某个交易日两个 gold 上游都已 materialized 且 checks 通过。
3. 短暂开启 sensor 一个 tick。
4. 期望只请求对应日期的 `ch_share_fact_market_breadth_daily`。
5. run 中不得出现 raw / silver / Tushare / gold 上游 materialization。
6. 验证后关闭，或经确认后长期启用。

如果 Dagster 当前版本对双上游 `eager() + all_deps_blocking_checks_passed()` 行为与预期不一致，必须停下讨论后备方案，不允许退化成“只看文件存在”的普通 sensor。

## 11. 代码组织

### 11.1 依赖

新增 orchestrator 依赖：

```text
dagster-clickhouse==0.29.6
```

原因：

1. 与当前 `dagster==1.13.6` 对齐。
2. 官方包依赖 `clickhouse-driver`，走 native `9000`。
3. 不需要新增 `clickhouse-connect`。

第一版不新增：

```text
dagster-clickhouse-pandas
clickhouse-connect
```

ClickHouse schema migration 依赖：

```text
flyway CLI
```

说明：

1. Flyway 是本机开发工具，不是 orchestrator Python runtime dependency。
2. 不写入 `pyproject.toml`。
3. 推荐通过 Homebrew 或 Flyway standalone CLI 安装。
4. Flyway 只在执行 schema migration 时使用，不参与 Dagster asset run。

### 11.2 Resource

使用官方类：

```text
dagster_clickhouse.ClickhouseResource
```

resource key：

```text
clickhouse
```

注册位置：

```text
lake_console/orchestrator/src/orchestrator/defs/resources.py
```

说明：

1. 第一版已直接在现有 `resources.py` 注册，保持与 `LakeRootResource`、`DuckDBResource`、`TushareResource` 同级。
2. 如果后续 ClickHouse resource 配置、封装方法、测试替身明显变复杂，再按职责拆到 `orchestrator/clickhouse/`，但这不是第一版动作。
3. `dg dev` / definitions 加载时不能因为 ClickHouse 未启动而崩溃；只有 asset 实际运行时才连接。

### 11.3 Assets

```text
lake_console/orchestrator/src/orchestrator/defs/assets/clickhouse_serving.py
  ch_share_fact_market_breadth_daily
```

第一版只有一张 serving 表，先用 `clickhouse_serving.py`，不按未来想象提前拆多个文件。

### 11.4 Checks

```text
lake_console/orchestrator/src/orchestrator/defs/checks/clickhouse_serving_checks.py
```

### 11.5 Jobs

```text
lake_console/orchestrator/src/orchestrator/defs/jobs/clickhouse_share_fact_market_breadth_update.py
  clickhouse_share_fact_market_breadth_update_job
```

Job 文件只写 asset selection，不写 SQL、不连 ClickHouse。

### 11.6 Automation Sensor

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/clickhouse_share_fact_market_breadth_automation_sensor.py
  clickhouse_share_fact_market_breadth_automation_sensor
```

该 sensor 是 `AutomationConditionSensorDefinition`，不是普通 `@sensor`。

## 12. 配置审计表

| 配置名 | 本地约定值 | 来源 | 消费者 | 是否敏感 | 说明 |
|---|---:|---|---|---|---|
| `CLICKHOUSE_HOST` | `127.0.0.1` | 环境变量 | `ClickhouseResource` | 否 | 本地 ClickHouse host |
| `CLICKHOUSE_PORT` | `9000` | 环境变量 | `ClickhouseResource` | 否 | native TCP 端口 |
| `CLICKHOUSE_USER` | `default` | 环境变量 | `ClickhouseResource` | 否 | `dagster-clickhouse` 字段名是 `user` |
| `CLICKHOUSE_PASSWORD` | 空 | 环境变量 | `ClickhouseResource` | 是 | 当前本地为空，未来如设置密码必须走环境变量 |
| `CLICKHOUSE_DATABASE` | `goldenshare_serving` | 环境变量 | `ClickhouseResource` | 否 | serving 业务库 |
| `CLICKHOUSE_FLYWAY_URL` | `jdbc:clickhouse://127.0.0.1:8123/default` | `flyway.conf` 或环境变量 | Flyway CLI | 否 | 只用于 schema migration |

门禁：

1. 不新增散落 env 文件。
2. 不把密码写入代码、文档、Dagster metadata 或日志。
3. ClickHouse runtime 连接配置统一走环境变量，不做“一半环境变量、一半代码默认”的混搭；表中的“本地约定值”是本机应该配置成什么，不是 Python 代码里的 fallback。
4. `CLICKHOUSE_PORT` 在 Python 中必须通过 `dg.EnvVar.int("CLICKHOUSE_PORT")` 传给 `ClickhouseResource`；当前已核验可表达“env 注入 + int 转换 + definitions 加载不连接”，禁止硬编码端口或自造临时配置。
5. Flyway migration 可以使用独立 JDBC URL，但 host / port / user / password / database 口径必须与本地 ClickHouse 配置一致。
6. Flyway 使用 HTTP `8123`，Dagster runtime 使用 native `9000`；这是工具协议差异，不代表业务配置分裂。
7. `flyway repair` 禁止作为日常命令；需要用户明确批准。
8. `dg dev` / definitions 加载时不应因为 ClickHouse 未启动而失败。
9. 只有实际运行 ClickHouse serving asset 时，才检查连接可用性。

## 13. 落地步骤

### Slice CH-1：ClickHouse migration 基础

状态：已完成。

当前执行结果：

```text
Flyway CLI: 12.6.2
Flyway ClickHouse plugin: 10.24.0
ClickHouse JDBC driver: clickhouse-jdbc-0.9.8-all.jar
JDBC URL: jdbc:clickhouse://127.0.0.1:8123/default
Schema history table: default.flyway_schema_history
已执行 migration: V1 / V2
```

本地注意事项：

1. Homebrew 安装的 Flyway 12.6.2 已自带 ClickHouse database plugin。
2. Flyway CLI 不自带 ClickHouse JDBC driver，需要把 `clickhouse-jdbc-0.9.8-all.jar` 放入 `clickhouse_migrations/drivers/`。
3. 本地 ClickHouse `default` 用户为空密码，但 Flyway 必须显式传 `-password=`；只传 `-user=default` 会触发 `REQUIRED_PASSWORD`。
4. Codex 沙箱内 Java/Flyway 连接本机 ClickHouse 会遇到 `SocketException: Operation not permitted`，执行 Flyway 连接和迁移命令需要在沙箱外运行。

目标：

1. 安装或确认本机 Flyway CLI 可用。
2. 确认 Flyway 能识别 ClickHouse JDBC 连接，必要时明确 ClickHouse JDBC driver / plugin 的安装方式。
3. 新增独立 ClickHouse Flyway migration 环境。
4. 新增 `flyway.conf` 和 `sql/` 目录。
5. 新增 `V1__create_goldenshare_serving_database.sql`。
6. 新增 `V2__create_share_fact_market_breadth_daily.sql`。
7. 执行 `flyway info` / `flyway migrate` / `flyway validate`。
8. 提供明确执行命令。

不做：

1. 不注册 Dagster resource。
2. 不写 asset。
3. 不写数据。
4. 不执行 Dagster 命令。

验收：

1. Flyway CLI 可执行。
2. Flyway 的 ClickHouse JDBC 连接能力已被验证，不把“CLI 存在”误判成“ClickHouse migration 可用”。
3. ClickHouse 中能看到数据库和表。
4. 表结构与契约一致。
5. Flyway schema history 可查询。
6. `flyway validate` 通过。

### Slice CH-2：dagster-clickhouse Resource

状态：已完成。

当前实现结果：

```text
dagster-clickhouse==0.29.6
resource key: clickhouse
runtime protocol: native TCP 9000
database: goldenshare_serving
```

配置来源：

```text
~/.bash_profile
  CLICKHOUSE_HOST
  CLICKHOUSE_PORT
  CLICKHOUSE_USER
  CLICKHOUSE_PASSWORD
  CLICKHOUSE_DATABASE
```

目标：

1. 安装 `dagster-clickhouse==0.29.6`。
2. 注册官方 `ClickhouseResource`，resource key 为 `clickhouse`。
3. 使用 native `9000`。
4. 完成 resource 配置审计。
5. 明确 `CLICKHOUSE_HOST`、`CLICKHOUSE_PORT`、`CLICKHOUSE_USER`、`CLICKHOUSE_PASSWORD`、`CLICKHOUSE_DATABASE` 的 env 注入方式和缺失行为。

不做：

1. 不创建表。
2. 不写 serving asset。
3. 不引入 IO Manager。

验收：

1. `dg check defs` 不因 ClickHouse 未启动而失败。
2. resource 只有在实际调用时才连接 ClickHouse。
3. 本地连接错误清晰暴露。
4. 沙箱内 native 连接限制不误判为 ClickHouse 配置失败。
5. 不出现硬编码 host / port / user / database 的代码 fallback。

### Slice CH-3：`ch_share_fact_market_breadth_daily` asset

状态：已完成。

当前实现结果：

```text
asset key: ch_share_fact_market_breadth_daily
group: serving
partition: cn_a_stock_trade_days
direct deps:
  gold_market_breadth_daily
  gold_stock_return_distribution
write target:
  goldenshare_serving.share_fact_market_breadth_daily
replace mode:
  SET lightweight_deletes_sync = 1
  DELETE by trade_date
  assert zero rows
  INSERT one row
  assert one row
```

目标：

1. 新增 `ch_share_fact_market_breadth_daily[trade_date]`。
2. 读取两个 gold parquet。
3. 通过 `ClickhouseResource` 执行 replace 写入。
4. 输出 materialization metadata。

不做：

1. 不自动触发。
2. 不补 gold。
3. 不调用 Tushare。

验收：

1. 单日手动运行成功。
2. ClickHouse 中出现对应 `trade_date` 1 行。
3. 重跑同一天不会重复插入。
4. run 中不 materialize 上游 raw / silver / gold。
5. 已完成 `2026-05-28` 单日写入与重跑验证，确认 replace 写入不会产生重复行。

### Slice CH-4：Checks 与 job

状态：已完成。

当前实现结果：

```text
checks:
  ch_share_fact_market_breadth_row_count_is_one
  ch_share_fact_market_breadth_date_matches_partition
  ch_share_fact_market_breadth_total_count_matches_gold
  ch_share_fact_market_breadth_flat_count_matches_gold
  ch_share_fact_market_breadth_breadth_fields_match_gold
  ch_share_fact_market_breadth_distribution_fields_match_gold

job:
  clickhouse_share_fact_market_breadth_update_job

selection:
  ch_share_fact_market_breadth_daily
  checks_for_assets(ch_share_fact_market_breadth_daily)
```

目标：

1. 新增 ClickHouse serving checks。
2. 新增 `clickhouse_share_fact_market_breadth_update_job`。
3. 确认 job 只 selection ClickHouse serving asset 和 checks。

验收：

1. 单日 run checks 全部通过。
2. ClickHouse 行数、日期、字段值与两个 gold assets 一致。
3. run 中不 materialize 上游 gold / silver / raw。
4. 已完成单日 serving checks 验证，6 个 ClickHouse checks 均通过。

### Slice CH-5：自动化入口

状态：已完成。

当前实现结果：

```text
asset condition:
  ch_share_fact_market_breadth_daily
    eager() & all_deps_blocking_checks_passed()

automation sensor:
  clickhouse_share_fact_market_breadth_automation_sensor
    target = ch_share_fact_market_breadth_daily
    default_status = STOPPED
    minimum_interval_seconds = 600
    emit_backfills = true
    use_user_code_server = false
```

目标：

1. 为 `ch_share_fact_market_breadth_daily` 添加 automation condition。
2. 新增专用 `clickhouse_share_fact_market_breadth_automation_sensor`。
3. sensor 默认 `STOPPED`。
4. 自动化入口已定义，长期启用仍需按运营节奏决定。

不做：

1. 不默认长期开启。
2. 不做全历史大范围同步。
3. 不用普通 sensor 写重 IO readiness。

验收：

1. 只有两个 gold 直接上游 ready 时才请求 ClickHouse serving asset。
2. 不触发 gold 上游 job。
3. 不触发 raw / silver / Tushare。
4. 启用前必须先做请求范围评估，避免历史缺失分区被一次性请求。
5. 当前默认保持 `STOPPED`；是否长期打开不作为第一版表开发完成的阻塞条件。

### Slice CH-6：小范围 backfill 与文档收口

状态：已完成第一轮验收。

已完成：

1. 小范围 backfill 最近若干交易日。
2. 单日 serving checks 验收。
3. 验证 `clickhouse_share_fact_market_breadth_update_job` 可用于人工分区运行和小范围 backfill。
4. 验证 ClickHouse 中同一 `trade_date` 只有 1 行，不因重跑产生重复。

仍保留的运营决策：

1. 是否长期启用 `clickhouse_share_fact_market_breadth_automation_sensor`。
2. 是否做更大范围历史 backfill。
3. 是否把本地 API 查询切到 ClickHouse serving 表。

不做：

1. 不做全历史大规模同步。
2. 不接 prod。

## 14. 风险与边界

### 14.1 ClickHouse 不是事实源

如果 ClickHouse 与 gold parquet 不一致，以 gold parquet 为准。

修复方式：

```text
重跑 ch_share_fact_market_breadth_daily[trade_date]
```

而不是手工改 ClickHouse 表。

### 14.2 表结构变更必须走 migration

任何新增字段、改类型、换引擎、改 ORDER BY / PARTITION BY，都必须新增 ClickHouse migration。

禁止在 asset 里偷偷 `ALTER TABLE`。

### 14.3 Serving asset 不补上游

`ch_share_fact_market_breadth_daily` 只消费已经准备好的 gold。

如果上游 gold 缺失或 checks 不通过：

```text
ch asset fail 或 automation 不请求
```

不能在 ClickHouse asset 中触发 `daily_market_breadth_job` 或 `stock_return_distribution_daily_job`。

### 14.4 不混用 PostgreSQL Alembic 主链

ClickHouse migrations 必须由 Flyway 独立管理。

当前根 Alembic 仍服务主应用 PostgreSQL。

ClickHouse 不使用根 Alembic，也不新增 ClickHouse Alembic 分支。

### 14.5 不提交本机 ClickHouse 配置

本机 ClickHouse 配置和数据目录仍在：

```text
/Users/congming/.goldenshare/clickhouse/
```

不进入仓库。

### 14.6 不让 IO Manager 管第一张 serving 表

第一张 serving 表是两个 gold assets 的组合结果，不是一对一落库。

因此第一版不让 IO Manager 自动建表或自动落表。

## 15. 第一版完成定义

第一版已满足：

1. `goldenshare_serving.share_fact_market_breadth_daily` 由 migration 创建。
2. `dagster-clickhouse==0.29.6` 已安装。
3. 官方 `ClickhouseResource` 已注册为 `clickhouse`。
4. `ch_share_fact_market_breadth_daily[trade_date]` 可单日运行。
5. ClickHouse 表中该日数据与两个 gold assets 完全一致。
6. `clickhouse_share_fact_market_breadth_update_job` 只负责 ClickHouse serving asset。
7. `clickhouse_share_fact_market_breadth_automation_sensor` 已定义，默认 `STOPPED`。
8. 所有 serving checks 通过。
9. 已完成小范围 backfill 验收。
10. 已完成历史补齐验收，`gold_market_breadth_daily` 与 `gold_stock_return_distribution` 共同进入 ClickHouse serving 表的链路已收口。
11. 文档同步到 design / architecture 相关文档。

当前边界：

1. ClickHouse serving 表是副本层，不是 raw / silver / gold 的事实源。
2. automation sensor 仍默认 `STOPPED`；长期启用属于运营策略，不影响第一版开发收口。
