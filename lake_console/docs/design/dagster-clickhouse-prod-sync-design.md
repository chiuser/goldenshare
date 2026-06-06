# Dagster ClickHouse Prod 同步设计

更新时间：2026-06-06

## 1. 背景与目标

本机 ClickHouse 已作为本地 serving 副本层接入 Dagster。当前第一张 serving 表是：

```text
goldenshare_serving.share_fact_market_breadth_daily
```

本机每日流程是：

```text
gold_market_breadth_daily[trade_date]
gold_stock_return_distribution[trade_date]
        ↓
ch_share_fact_market_breadth_daily[trade_date]
        ↓
本机 ClickHouse serving 表
```

新的目标是：在 prod 服务器上安装官方 Linux stable ClickHouse，并由本机 Dagster 在本机 ClickHouse 更新完成后，把对应分区同步到 prod ClickHouse。prod ClickHouse 作为 prod 环境下对外服务的正式数据服务副本。

本方案只讨论 ClickHouse 同步链路，不修改现有 gold 资产口径，不改变 Parquet 数据湖作为事实源的定位。

## 2. 核心结论

采用 Dagster asset 管理 prod 同步，而不是把本机 ClickHouse 和 prod ClickHouse 组成复制集群。

第一版链路：

```text
本机 gold parquet
        ↓
本机 ch_share_fact_market_breadth_daily[trade_date]
        ↓
本机 ClickHouse: goldenshare_serving.share_fact_market_breadth_daily
        ↓
prod_ch_share_fact_market_breadth_daily[trade_date]
        ↓
prod ClickHouse: goldenshare_serving.share_fact_market_breadth_daily
```

关键原则：

1. prod ClickHouse 是 prod serving 副本，不是 raw / silver / gold 的事实源。
2. 本机 Dagster 是第一版同步控制面。
3. prod ClickHouse 连接注册为独立 Dagster resource，resource key 为 `prod_clickhouse`。
4. `prod_clickhouse` 只负责连接 prod ClickHouse，不负责创建、维护或恢复 SSH tunnel。
5. SSH tunnel 是运行环境前置条件；如果 tunnel 没起来，prod sync asset 应失败并暴露清晰错误。
6. prod 表结构由 Flyway migration 管理，不能由 asset 代码临时建表或改表。
7. 同一 `trade_date` 的 prod 写入必须使用同步 replace 语义，避免重复行或旧数据短暂可见。
8. 日常单日同步和历史全量 / 范围同步使用同一个 prod sync asset，不新增独立 range sync job 或 repair sensor。
9. 历史全量 / 范围 backfill 必须通过 Dagster `BackfillPolicy.multi_run(max_partitions_per_run=250)` 合批执行，禁止继续按 3000 多个交易日拆成 3000 多个 run。
10. prod sync checks 名称和 blocking 语义保持不变，但实现必须支持同一 run 内多个 `partition_keys` 的批量校验。

## 3. 为什么不做 ClickHouse 集群复制

不采用 `ReplicatedMergeTree` / ClickHouse Keeper 作为第一版方案。

原因：

1. 当前场景是“本机生产完成后推送 prod serving 副本”，不是两台服务器共同组成高可用 ClickHouse 集群。
2. 本机电脑会关机、断网、切换网络，不适合作为 ClickHouse 复制集群中的稳定 replica。
3. `ReplicatedMergeTree` 需要 ClickHouse Keeper / ZooKeeper、replica path、replica identity、集群运维与恢复策略，复杂度明显超过当前目标。
4. prod 对外服务应依赖 prod ClickHouse 本地数据，而不是在请求时依赖本机在线。

不采用 `Distributed` 表作为第一版主同步方案。

原因：

1. `Distributed` 更适合集群查询和集群写入路由，不适合表达“本机经 Dagster 审批后推送 prod serving 分区”。
2. 它会引入后台发送、分布式队列、远端连接配置等额外运维面。
3. 我们需要每个 `trade_date` 的 Dagster materialization / checks / retry 可观测性，显式 prod sync asset 更清楚。

`remote` / `remoteSecure` 表函数可以作为临时排查或迁移辅助，但不作为第一版正式同步主路径。

## 4. Prod ClickHouse 安装方案

### 4.1 版本口径

prod ClickHouse 不复用本机 macOS binary。prod 必须安装符合 Linux 架构的官方 stable ClickHouse 包。

当前实际安装结果：

```text
prod version: 26.5.1.882
package source: packages.clickhouse.com/deb stable
architecture: Linux amd64
```

原因：

1. 本机 `/Users/congming/.goldenshare/clickhouse/bin/clickhouse` 是 macOS binary，不能复制到 Linux prod 执行。
2. prod 以 Linux official stable 包为准，保证系统服务、依赖和 native client 行为符合服务器环境。
3. 本机和 prod 的兼容边界不靠“二进制完全相同”，而靠 Flyway 表结构契约、Dagster checks、单日 replace 验收和 prod sync checks 保证。

验收命令：

```bash
clickhouse client \
  --host 127.0.0.1 \
  --port 9000 \
  --query 'SELECT version()'
```

期望返回：

```text
26.5.1.882
```

### 4.2 Prod 安装目录建议

prod 不应复用本机 `/Users/congming/.goldenshare/clickhouse` 路径。推荐：

```text
/opt/goldenshare/clickhouse/
  bin/
  config/
  data/
  logs/
  tmp/
  user_files/
  format_schemas/
  clickhouse.pid
```

目录职责与本机一致：

```text
config/
  config.xml
  users.xml

data/
  ClickHouse 服务数据目录

logs/
  ClickHouse server 日志

tmp/
  ClickHouse 临时文件目录

user_files/
  ClickHouse 本地文件访问目录

format_schemas/
  ClickHouse format schema 目录
```

### 4.3 Prod 网络监听

第一版推荐 prod ClickHouse 只监听本机：

```text
listen_host = 127.0.0.1
http_port = 8123
tcp_port = 9000
interserver_http_port = 9009
```

不把 `9000` 暴露到公网。

原因：

1. `9000` 是 ClickHouse native 数据库端口，不应直接暴露给公网扫描。
2. 第一版本机 Dagster 通过 SSH tunnel 访问 prod `127.0.0.1:9000`，不需要公网监听。
3. 后续如果改为 VPN / Tailscale / WireGuard，可再把监听范围收敛到私网地址。

当前实际实现：ClickHouse binary 由官方 deb 安装到 `/usr/bin/clickhouse`；prod 服务使用 `/opt/goldenshare/clickhouse/config`、`data`、`logs`、`tmp` 等运行目录，并由 `goldenshare-clickhouse.service` 以 `goldenshare` 用户启动。

### 4.4 Prod 用户与权限

prod 不使用 `default` 作为同步用户。新增专用用户：

```text
goldenshare_sync_writer
```

权限最小化原则：

1. 允许连接 `goldenshare_serving`。
2. 允许读取目标表，用于同步前后校验。
3. 允许向目标表插入数据。
4. 允许按 `trade_date` 删除目标表旧行，因为 replace 需要先删后插。
5. 不授予无关库表权限。
6. 不授予管理用户、修改系统配置等权限。

当前实际授权：

```sql
GRANT SELECT, INSERT, ALTER UPDATE, ALTER DELETE
ON goldenshare_serving.share_fact_market_breadth_daily
TO goldenshare_sync_writer
```

说明：ClickHouse `DELETE FROM` 在当前版本下需要改写 `_row_exists`，仅授予 `ALTER DELETE` 不够，服务端会要求 `ALTER UPDATE(_row_exists)` 权限。因此第一版同步用户补充 `ALTER UPDATE`，但仍只限定在目标表上。

### 4.5 Prod Flyway migration

prod 必须使用与本机相同的 ClickHouse migration 文件创建库表。

当前本机 migration 目录：

```text
lake_console/orchestrator/clickhouse_migrations/
```

已执行：

```text
V1__create_goldenshare_serving_database.sql
V2__create_share_fact_market_breadth_daily.sql
```

prod 执行方式：

```bash
cd /path/to/goldenshare/lake_console/orchestrator
flyway -configFiles=clickhouse_migrations/flyway.conf info
flyway -configFiles=clickhouse_migrations/flyway.conf migrate
flyway -configFiles=clickhouse_migrations/flyway.conf validate
```

prod JDBC URL 使用 prod 本机 HTTP：

```text
jdbc:clickhouse://127.0.0.1:8123/default
```

说明：

1. Flyway 使用 HTTP `8123` 是 migration 工具协议。
2. Dagster runtime 使用 native `9000` 是 `dagster-clickhouse` resource 协议。
3. 已执行过的 V1/V2 不允许修改；后续表结构变化新增 V3/V4。

## 5. 第一版连接方案

### 5.1 推荐方式：SSH tunnel

第一版推荐使用 SSH tunnel：

```bash
lake_console/bin/lake-prod-clickhouse-tunnel
```

含义：

```text
本机 127.0.0.1:19000
        ↓ SSH tunnel
prod 127.0.0.1:9000
        ↓
prod ClickHouse native port
```

本机 Dagster 连接 prod ClickHouse 时看到的是：

```text
host = 127.0.0.1
port = 19000
```

这个方案的优点：

1. prod ClickHouse 不需要公网开放 `9000`。
2. 本机无需 VPN 就能完成第一版同步。
3. 出问题时边界清楚：tunnel 没起来就是连接失败，Dagster sync asset 失败。
4. tunnel 可以先手动启动，稳定后再用 `autossh`、`launchd` 或运维脚本托管。

当前脚本会显式打开 SSH keepalive：

```text
ExitOnForwardFailure=yes
ServerAliveInterval=30
ServerAliveCountMax=3
```

如果 tunnel 断开，prod sync asset 会连接失败并暴露错误；resource 不负责自动恢复 tunnel。

### 5.2 Resource 不管理 tunnel

明确原则：

```text
Dagster Resource 只负责连接 prod CH，不负责自己创建 SSH tunnel。
```

原因：

1. SSH tunnel 是运行环境能力，不是数据资产生成逻辑。
2. 如果 Python resource 偷偷拉起 SSH，会把系统连接管理、密钥、重连、日志和进程生命周期混入 Dagster asset 代码。
3. tunnel 不可用时，prod sync asset 应清晰失败，提醒运营先恢复连接。
4. 后续从 SSH tunnel 迁移到 VPN 时，只需要改环境变量，不需要改 asset 逻辑。

### 5.3 长期演进

第一版：

```text
手动或脚本启动 SSH tunnel
PROD_CLICKHOUSE_HOST=127.0.0.1
PROD_CLICKHOUSE_PORT=19000
```

稳定后：

```text
autossh / launchd 托管 tunnel
```

更长期：

```text
Tailscale / WireGuard / 内网专线
PROD_CLICKHOUSE_HOST=<prod-private-ip>
PROD_CLICKHOUSE_PORT=9000
```

无论哪一种，Dagster resource 口径不变：只连接，不创建网络通道。

## 6. Dagster Resource 设计

当前本机 resource：

```text
clickhouse
```

含义：连接本机 ClickHouse。

新增 prod resource：

```text
prod_clickhouse
```

含义：连接 prod ClickHouse。

配置全部走环境变量，不在代码里写默认值：

```text
PROD_CLICKHOUSE_HOST=127.0.0.1
PROD_CLICKHOUSE_PORT=19000
PROD_CLICKHOUSE_USER=goldenshare_sync_writer
PROD_CLICKHOUSE_PASSWORD=<secret>
PROD_CLICKHOUSE_DATABASE=goldenshare_serving
```

本机 ClickHouse 保持现有变量：

```text
CLICKHOUSE_HOST=127.0.0.1
CLICKHOUSE_PORT=9000
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
CLICKHOUSE_DATABASE=goldenshare_serving
```

代码结构建议：

```text
lake_console/orchestrator/src/orchestrator/defs/resources.py
  clickhouse       # 本机 CH
  prod_clickhouse  # prod CH via tunnel / private network
```

`dg dev` / definitions 加载阶段不主动连接 prod ClickHouse。只有运行 prod sync asset 时才连接。

## 7. Dagster Asset 设计

### 7.1 新增资产

新增 prod sync asset：

```text
prod_ch_share_fact_market_breadth_daily[trade_date]
```

分区：

```text
cn_a_stock_trade_days
```

直接上游：

```text
ch_share_fact_market_breadth_daily[trade_date]
```

group：

```text
serving
```

asset layer：

```text
serving
```

语义：

```text
把本机 ClickHouse 中已经验收完成的 market_breadth_daily serving 行同步到 prod ClickHouse。
```

### 7.2 不读取 gold parquet

prod sync asset 不重新读取 gold parquet，不重新组合字段。

原因：

1. 本机 `ch_share_fact_market_breadth_daily` 已经完成 gold 合并、replace 写入和本机 serving checks。
2. prod sync asset 的职责是复制本机 serving 副本到 prod serving 副本。
3. 如果 prod sync asset 又重新读 gold 并组装字段，会重复业务逻辑，容易和本机 CH serving asset 发生口径分叉。

第一版日常单日读取：

```text
本机 ClickHouse: goldenshare_serving.share_fact_market_breadth_daily WHERE trade_date = partition_key
```

PCH-7 批量 backfill 读取：

```text
本机 ClickHouse: goldenshare_serving.share_fact_market_breadth_daily
WHERE trade_date IN selected_partition_keys
ORDER BY trade_date
```

单日写入：

```text
prod ClickHouse: goldenshare_serving.share_fact_market_breadth_daily WHERE trade_date = partition_key
```

PCH-7 批量 backfill 写入：

```text
prod ClickHouse: goldenshare_serving.share_fact_market_breadth_daily
WHERE trade_date IN selected_partition_keys
```

收益率分桶 schema 变更后仍保持该边界：

1. `prod_ch_share_fact_market_breadth_daily` 不计算 `pct_chg` 分桶，不读取 `gold_stock_return_distribution` parquet。
2. 本机 `ch_share_fact_market_breadth_daily` 必须已经按十一段收益率区间口径重建，并通过本机 serving checks。
3. prod sync 只读取本机 ClickHouse 中目标 `trade_date` 的完整新 schema 行，再 replace 到 prod ClickHouse。
4. 本机 CH 与 prod CH 必须先执行同一份 Flyway migration，例如新增的 `V3__split_market_breadth_return_distribution_buckets.sql`；两边 schema 不一致时禁止同步。

### 7.3 写入语义

prod 写入必须使用同步 replace。单日运行时：

```text
SET lightweight_deletes_sync = 1
DELETE FROM goldenshare_serving.share_fact_market_breadth_daily WHERE trade_date = <partition_date>
确认 prod 当日 row_count = 0
INSERT 该 trade_date 的完整新 schema 行
确认 prod 当日 row_count = 1
```

PCH-7 批量 backfill 运行时：

```text
selected_partition_keys = context.partition_keys
batch_size <= 250

从本机 CH 一次读取 selected_partition_keys 的完整行
确认 local row_count = selected partition count
确认 local uniqExact(trade_date) = selected partition count

SET lightweight_deletes_sync = 1
DELETE FROM goldenshare_serving.share_fact_market_breadth_daily
WHERE trade_date IN selected_partition_keys
确认 prod selected row_count = 0

INSERT selected_partition_keys 的完整新 schema 行
确认 prod selected row_count = selected partition count
确认 prod selected uniqExact(trade_date) = selected partition count
```

批量 replace 仍然是“按目标 trade_date 删除旧行，再插入本机 CH 完整新行”，不是补列、不是 UPDATE、不是从 gold parquet 重新计算。

如果 delete 成功但 insert 失败，prod 对应日期集合的 serving 行可能暂时缺失。由于 prod ClickHouse 是副本层，重新运行同一批或同一分区即可恢复。

并发同一分区写入第一版不单独处理；后续如果自动化长期启用，需要评估 Dagster concurrency / run queue 限制。

刷新历史数据时，prod 同日期旧行必须先删除，再插入本机 CH 已重建后的完整新行；禁止只补新增列、禁止对 prod 旧行做 `ALTER TABLE UPDATE` mutation，也禁止绕过 Dagster 用手写脚本直接灌 prod。

不使用 `ALTER TABLE ... DROP PARTITION` 作为 PCH-7 主路径。原因是 backfill 选择的是交易日集合，不一定完整覆盖 ClickHouse 月分区；按月 drop partition 容易误删不在本次目标集合内的日期。

不使用 `ALTER TABLE ... DELETE`。当前 replace 继续使用 ClickHouse lightweight `DELETE FROM`，并把原来的 3000 多次单日 delete 合并为最多约 13 次批量 delete。

### 7.4 Metadata

materialization metadata 必须记录：

```text
uri = clickhouse://prod/goldenshare_serving.share_fact_market_breadth_daily?trade_date=...
row_count = 1
goldenshare/observed_columns = <表字段列表>
partition_key
source_table = goldenshare_serving.share_fact_market_breadth_daily
target_table = goldenshare_serving.share_fact_market_breadth_daily
sync_mode = sync_delete_then_insert
```

不得记录 prod 密码、SSH 命令、私钥路径或敏感连接串。

PCH-7 批量 backfill 落地后，单日运行仍记录单个 `partition_key`；多分区运行必须记录：

```text
uri = clickhouse://prod/goldenshare_serving.share_fact_market_breadth_daily?trade_date_in=...
row_count = selected partition count
goldenshare/observed_columns = <表字段列表>
partition_keys = <selected partition keys>
partition_count
source_table = goldenshare_serving.share_fact_market_breadth_daily
target_table = goldenshare_serving.share_fact_market_breadth_daily
sync_mode = sync_delete_then_insert_batch
batch_size_limit = 250
```

metadata 只记录批次摘要和少量样本，不记录 250 行完整明细，避免 Dagster event metadata 膨胀。

## 8. Checks 设计

prod sync checks 绑定：

```text
prod_ch_share_fact_market_breadth_daily
```

全部 blocking。

PCH-5 第一版 checks 名称如下。PCH-7 批量 backfill 优化后，名称不变、blocking 不变，但每个 check 必须支持 `context.partition_keys`。

1. `prod_ch_share_fact_market_breadth_row_count_is_one`
   - prod 每个目标日期必须只有 1 行。
   - 防止漏写或重复写。
   - 批量实现按 `trade_date` group by，一次返回 selected dates 的 row_count，metadata 记录 missing / duplicate partition samples。

2. `prod_ch_share_fact_market_breadth_date_matches_partition`
   - prod 行内 `trade_date` 必须等于 Dagster selected partition key 集合。
   - 防止写错日期。
   - 批量实现比较 selected partition set 与 prod 返回的 trade_date set。

3. `prod_ch_share_fact_market_breadth_matches_local`
   - prod 每个目标日期整行必须与本机 ClickHouse 同日期整行一致。
   - 防止 prod serving 副本和本机 serving 副本分叉。
   - 批量实现分别读取本机 CH / prod CH selected dates，按 `trade_date` 对齐后逐字段比较，metadata 记录 mismatched partition / field samples。

4. `prod_ch_share_fact_market_breadth_updated_at_not_older_than_local`
   - prod 每个目标日期的 `updated_at` 不应早于本机同日期行的 `updated_at`。
   - 如果采用整行复制，本 check 应天然通过。
   - 批量实现按 `trade_date` 对齐比较，metadata 记录 failed partition samples。

说明：

1. prod checks 不从 silver 重新计算。
2. prod checks 不重新读取 gold parquet。
3. gold 业务口径仍由 gold checks 和本机 CH serving checks 负责。
4. prod checks 只回答“prod 副本是否等于本机 CH 副本”。

## 9. Job 与 Automation

### 9.1 Job

新增 job：

```text
prod_clickhouse_share_fact_market_breadth_sync_job
```

selection：

```text
prod_ch_share_fact_market_breadth_daily
+ checks_for_assets(prod_ch_share_fact_market_breadth_daily)
```

job 只做 asset selection，不写 SQL、不管理 SSH tunnel。

PCH-7 批量 backfill 口径：

```python
@dg.asset(
    partitions_def=cn_a_stock_trade_days,
    backfill_policy=dg.BackfillPolicy.multi_run(max_partitions_per_run=250),
    ...
)
def prod_ch_share_fact_market_breadth_daily(...):
    partition_keys = tuple(sorted(set(context.partition_keys)))
```

要求：

1. 日常单日 materialize 时 `partition_keys` 长度为 1，行为与当前单日 prod sync 一致。
2. 历史全量 / 范围 backfill 时，每个 run 最多处理 250 个交易日。
3. `prod_clickhouse_share_fact_market_breadth_sync_job` 仍然只选择 `prod_ch_share_fact_market_breadth_daily + checks_for_assets(...)`。
4. 不新增独立 `range_sync_job`、repair sensor、summary asset、数据库表或配置项。
5. job 文件仍只定义 asset selection，不承接 SQL 或批量逻辑。

### 9.2 Automation

新增 automation sensor：

```text
prod_clickhouse_share_fact_market_breadth_automation_sensor
```

默认：

```text
STOPPED
```

target：

```text
prod_ch_share_fact_market_breadth_daily
```

condition：

```python
dg.AutomationCondition.eager()
& dg.AutomationCondition.all_deps_blocking_checks_passed()
```

含义：

1. 本机 CH serving asset 更新后，prod sync asset 可跟进。
2. 只检查直接上游 `ch_share_fact_market_breadth_daily` 的 blocking checks。
3. 不触发 gold / silver / raw。
4. 不负责恢复 SSH tunnel。

第一版启用前必须先做请求范围评估，避免历史缺失分区被一次性请求。

## 10. 落地步骤

### Slice PCH-1：prod ClickHouse 安装

状态：已完成。

已落地：

1. prod 安装官方 Linux stable ClickHouse `26.5.1.882`。
2. 使用 `/opt/goldenshare/clickhouse/config`、`data`、`logs`、`tmp` 等运行目录。
3. `goldenshare-clickhouse.service` 以 `goldenshare` 用户运行。
4. `8123`、`9000`、`9009` 只监听 `127.0.0.1`。
5. `timezone()` 返回 `Asia/Shanghai`。

验收：

```text
SELECT version() = 26.5.1.882
ClickHouse server 重启后可恢复
9000 不暴露公网
```

### Slice PCH-2：prod migration

状态：已完成。

已落地：

1. 通过本机 Flyway + 临时 SSH HTTP tunnel 执行 ClickHouse Flyway migration。
2. 创建 `goldenshare_serving`。
3. 创建 `goldenshare_serving.share_fact_market_breadth_daily`。
4. 创建并授权 `goldenshare_sync_writer`。

验收：

```text
flyway validate 通过
DESCRIBE TABLE 与本机一致
专用用户权限可完成 SELECT / INSERT / DELETE
测试日期写入后已清理干净
```

### Slice PCH-3：SSH tunnel 运行入口

状态：已完成。

已落地：

1. 新增本机脚本 `lake_console/bin/lake-prod-clickhouse-tunnel`。
2. 不把 tunnel 管理放进 Dagster resource。
3. 验证本机 `127.0.0.1:19000` 可访问 prod ClickHouse。
4. 已补 SSH keepalive，避免短时间无流量导致 tunnel 断开。

验收：

```bash
/Users/congming/.goldenshare/clickhouse/bin/clickhouse client \
  --host 127.0.0.1 \
  --port 19000 \
  --user goldenshare_sync_writer \
  --password '<secret>' \
  --query 'SELECT version(), currentDatabase()'
```

### Slice PCH-4：Dagster prod_clickhouse resource

状态：已完成。

已落地：

1. 注册 `prod_clickhouse` resource。
2. 全部配置走 `PROD_CLICKHOUSE_*` 环境变量。
3. definitions 加载阶段不主动连接 prod。

验收：

```text
dg check defs 通过
prod tunnel 未启动时 definitions 仍可加载
```

### Slice PCH-5：prod sync asset + checks + job

状态：已完成。

已落地：

1. 新增 `prod_ch_share_fact_market_breadth_daily[trade_date]`。
2. 新增 prod sync checks。
3. 新增 `prod_clickhouse_share_fact_market_breadth_sync_job`。
4. 单日验证 prod replace 写入和 checks。

验收：

```text
本机 CH 该日期 1 行
prod CH 该日期 1 行
prod 行与本机行完全一致
重跑同一天不重复
```

当前已用 `2026-05-28` 完成单日验收：

```text
prod row count = 1
up_count = 3018
down_count = 2365
flat_count = 123
total_count = 5506
red_rate = 54.81
updated_at = 2026-05-28 22:09:21
```

重跑同一分区后 prod 仍为 1 行，replace 幂等通过。

全量同步口径：

1. 若需要把本机 ClickHouse 现有全部 `share_fact_market_breadth_daily` 分区同步到 prod，不新增临时脚本，不绕过 Dagster。
2. 表结构变化先在本机 CH 和 prod CH 执行同一份 Flyway migration，并通过 `flyway validate`。
3. 先对目标日期集合重跑 `stock_return_distribution_daily_job`，生成十一段收益率区间的 gold parquet。
4. 再对同一目标日期集合重跑 `clickhouse_share_fact_market_breadth_update_job`，把本机 CH serving 行逐日 replace 成新 schema / 新口径。
5. 启动 `lake_console/bin/lake-prod-clickhouse-tunnel`，确认本机 `127.0.0.1:19000` 可访问 prod ClickHouse。
6. 在 Dagster UI 对 `prod_clickhouse_share_fact_market_breadth_sync_job` 发起分区 backfill，选择同一批 `trade_date` 分区集合。
7. PCH-7 落地后，backfill 由 `BackfillPolicy.multi_run(max_partitions_per_run=250)` 合并成多分区 run；每个 run 最多处理 250 个交易日。
8. 每个 run 由 `prod_ch_share_fact_market_breadth_daily[selected_partition_keys]` 批量读取本机 CH 行，使用同步 delete-then-insert replace 语义写入 prod CH，再执行同名批量 prod checks。
9. PCH-7 落地前，不建议再用当前逐日 backfill 跑 3000 多个交易日；这种方式可观测但性能不可接受，只适合单日或小范围修复。
10. 如果 tunnel 中断或 prod 不可达，对应批次 run 失败并暴露连接错误；修复 tunnel 后对 failed / missing partitions 重新 backfill。
11. 不直接用 `clickhouse-client INSERT SELECT` 或手写脚本批量灌 prod，因为那会绕过 Dagster asset/check/event 可观测性。

### Slice PCH-6：prod sync automation

状态：已完成，默认 `STOPPED`。

已落地：

1. 新增 `prod_clickhouse_share_fact_market_breadth_automation_sensor`。
2. 默认 `STOPPED`。
3. 小范围评估后再短暂开启。

验收：

```text
只请求 prod sync asset
不触发 gold / silver / raw
SSH tunnel 未启动时 run 失败清晰可见
```

### Slice PCH-7：prod sync 全量 backfill 性能优化

状态：已拍板，待开发。

已确认口径：

1. 批大小固定为 250 个交易日一组。
2. 保留当前 4 个 prod sync check 名称，只把实现改为批量实现。
3. 全量同步入口继续使用 `prod_clickhouse_share_fact_market_breadth_sync_job` 的 asset/job backfill policy，不新增独立 range sync job。
4. 日常 automation sensor 不变，仍围绕 `prod_ch_share_fact_market_breadth_daily`。
5. 不新增 repair sensor、summary asset、数据库表或配置项。

当前性能问题：

```text
3019 个交易日逐日 backfill
≈ 3019 个 Dagster run
≈ 每日 3 次本机 CH 查询 + 9 次 prod CH 查询
≈ 3.6 万次 CH round trip
≈ 1.5 万个 asset/check step 事件
```

PCH-7 目标：

```text
3019 个交易日
batch size = 250
预计 run 数 <= ceil(3019 / 250) = 13
本机 CH 查询、prod delete、prod insert、prod checks 全部按 selected_partition_keys 批量执行
```

性能预算与验证门槛：

1. 250 个交易日样本批次，单个 prod sync run 目标耗时不超过 90 秒；超过则停止扩大范围，先定位是 tunnel、CH delete、insert、check 还是 Dagster event 写入开销。
2. 约 3000 个交易日全量 backfill，目标耗时不超过 15 分钟；超过则不得继续把逐日链路作为全量维护入口。
3. 批量 insert 必须一次插入 selected rows，禁止在 batch 内退化为逐日 `INSERT` 循环。
4. 批量 checks 必须用集合查询、group by、按 `trade_date` 对账；禁止在 check 内对 250 个日期循环打开连接或循环查询。
5. 性能验证必须先经用户批准，列出命令、`DAGSTER_HOME`、目标日期范围、读写范围、影响和回滚方式；不得未经批准直接运行正式 Dagster backfill。
6. 验证结果必须记录：partition_count、run_count、local query count、prod query count、insert batch row_count、总耗时、失败样本。

开发验收：

1. 静态测试确认 `prod_ch_share_fact_market_breadth_daily` 配置 `BackfillPolicy.multi_run(max_partitions_per_run=250)`。
2. 单元测试确认 asset 在单 partition 和多 partition 上都使用 `context.partition_keys`。
3. 单元测试确认批量 replace 只打开本机 / prod 连接各一次，并使用批量 local select、批量 prod delete、批量 insert。
4. 单元测试确认 4 个 prod checks 在多 partition 上按集合校验，且名称不变、blocking 不变。
5. 回归测试确认 `prod_clickhouse_share_fact_market_breadth_sync_job` selection 不变。
6. 回归测试确认 `prod_clickhouse_share_fact_market_breadth_automation_sensor` 不新增范围触发逻辑。

## 11. 风险与处理

### 11.1 本机到 prod 网络中断

表现：

```text
prod sync asset 连接 prod_clickhouse 失败
```

处理：

1. 恢复 SSH tunnel。
2. 重跑失败 partition。

不做：

1. 不在 resource 内自动拉起 SSH。
2. 不把失败吞掉。

### 11.2 prod delete 成功但 insert 失败

表现：

```text
prod 某个 trade_date 或某个 selected_partition_keys 批次暂时缺行
```

处理：

1. 修复失败原因。
2. 单日运行失败时重跑同一 partition；PCH-7 批量 backfill 失败时重跑同一批次或对应 failed / missing partitions。

原因：

prod 是副本层，可通过本机 CH 重新同步恢复。

### 11.3 版本不一致

表现：

```text
migration / settings / delete / driver 行为与本机不同
```

处理：

1. prod 不使用本机 macOS binary，使用 Linux official stable 包。
2. 升级必须通过 Flyway validate、单日 prod sync、prod checks 和重跑幂等验收。
3. 如果未来 ClickHouse SQL 或 settings 行为变化，必须新增设计记录，不允许静默升级。

### 11.4 prod 表被手工修改

表现：

```text
prod checks 与本机 CH 不一致
```

处理：

1. 禁止手工修 prod CH。
2. 以本机 CH / gold parquet 为准，重跑 prod sync。

## 12. 当前不做

第一版不做：

1. 不做 ClickHouse 集群复制。
2. 不做 prod ClickHouse 对公网开放 `9000`。
3. 不在 Dagster resource 内创建 SSH tunnel。
4. 不让 prod ClickHouse 参与 raw / silver / gold 计算。
5. 不从 prod ClickHouse 回写本机。
6. 不让 prod API 直接读取本机 ClickHouse。
7. 不把 prod sync 自动化默认打开。
8. PCH-7 不新增独立 range sync job。
9. PCH-7 不新增 repair sensor、summary asset、数据库表或配置项。
10. PCH-7 不用手写脚本、`clickhouse-client INSERT SELECT`、`ALTER TABLE UPDATE` 或 `ALTER TABLE ... DROP PARTITION` 承接正式全量同步。

## 13. 已拍板口径

1. prod ClickHouse 使用官方 Linux stable deb 包安装，当前版本 `26.5.1.882`。
2. prod 运行目录使用 `/opt/goldenshare/clickhouse/`，systemd unit 为 `goldenshare-clickhouse.service`。
3. SSH tunnel 第一版使用手动脚本 `lake_console/bin/lake-prod-clickhouse-tunnel`。
4. `goldenshare_sync_writer` 密码只写入本机 `~/.bash_profile` 的 `PROD_CLICKHOUSE_PASSWORD`，不入仓库、不入文档、不入 metadata。
5. prod sync automation 已定义但默认 `STOPPED`，长期启用需要单独确认。
6. PCH-7 prod sync 全量 backfill 批大小固定为 250 个交易日一组。
7. PCH-7 保留当前 4 个 prod sync check 名称，只把实现改为批量实现。
8. PCH-7 全量同步入口继续使用 `prod_clickhouse_share_fact_market_breadth_sync_job` 的 asset/job backfill policy，不新增独立 range sync job。
