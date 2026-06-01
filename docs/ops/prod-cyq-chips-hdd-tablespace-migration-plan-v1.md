# Prod `raw_tushare.cyq_chips` HDD Tablespace 迁移方案 v1

状态：已执行。

执行时间：2026-06-01 08:10 ~ 08:16 CST。

执行结果：

1. 已将 PostgreSQL catalog tablespace 从 `gs_stk_mins_hdd` 改名为 `gs_raw_cold_hdd`。
2. 已将 `raw_tushare.cyq_chips` 表 heap 迁移到 `gs_raw_cold_hdd`。
3. 已将 `raw_tushare.cyq_chips_pkey`、`raw_tushare.idx_raw_tushare_cyq_chips_ts_code_trade_date`、`raw_tushare.idx_raw_tushare_cyq_chips_trade_date` 三个索引迁移到 `gs_raw_cold_hdd`。
4. 未清表、未删表、未重建表、未修改业务代码、未迁移其他表。
5. 迁移后最小读查询正常。

## 1. 目标

将生产库中占用 SSD 空间最大的 `raw_tushare.cyq_chips` 迁移到机械盘 tablespace，先只处理这一张表及其索引，释放 SSD 空间，避免继续扩大本轮改动范围。

本方案只设计 PostgreSQL tablespace 迁移，不改业务代码、不改表结构、不清表、不删数据。

## 2. 远程环境只读审计

审计时间：2026-06-01。

### 2.1 磁盘与挂载

| 项 | 当前事实 |
| --- | --- |
| SSD 根分区 | `/dev/vda2` 挂载到 `/` |
| SSD 容量 | 217G |
| SSD 已用 | 195G |
| SSD 可用 | 13G |
| SSD 使用率 | 94% |
| 机械盘分区 | `/dev/vdb` |
| 机械盘挂载点 | `/data/disk` |
| 机械盘容量 | 394G |
| 机械盘可用 | 374G |
| 机械盘使用率 | 1% |
| 挂载持久化 | `/etc/fstab` 已使用 UUID 挂载 `/data/disk` |

`/data/disk` 当前是稳定挂载点，适合承载 PostgreSQL tablespace。

### 2.2 PostgreSQL 当前状态

| 项 | 当前事实 |
| --- | --- |
| PostgreSQL 版本 | 16.13 |
| 主服务 | `postgresql@16-main.service` active/running |
| 当前数据库 | `goldenshare` |
| 当前默认 tablespace | `pg_default` |
| 已存在 HDD tablespace | `gs_stk_mins_hdd` |
| 已存在 HDD tablespace 路径 | `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd` |
| `gs_stk_mins_hdd` 当前承载数据 | 约 3MB，基本为空 |
| 当前连接用户 | `goldenshare_user` |
| `goldenshare_user` 是否 superuser | 否 |
| `goldenshare_user` 是否拥有 `raw_tushare.cyq_chips` | 是 |
| `goldenshare_user` 是否可使用 `gs_stk_mins_hdd` | 是 |

说明：当前 DB 连接账号没有权限查看 `data_directory`，也没有超级用户权限。因此如果要新建语义正确的 tablespace，需要一次 `postgres` 超级用户操作；如果要完全使用当前 DB 账号，则只能复用已有 `gs_stk_mins_hdd`。

### 2.3 `raw_tushare.cyq_chips` 当前体积

| 对象 | 类型 | 当前 tablespace | 估算行数 | 大小 |
| --- | --- | --- | ---: | ---: |
| `raw_tushare.cyq_chips` | table heap | `database_default` | 196,509,984 | 14 GB |
| `raw_tushare.cyq_chips_pkey` | index | `database_default` | 196,509,984 | 14 GB |
| `raw_tushare.idx_raw_tushare_cyq_chips_ts_code_trade_date` | index | `database_default` | 196,509,984 | 2480 MB |
| `raw_tushare.idx_raw_tushare_cyq_chips_trade_date` | index | `database_default` | 196,509,984 | 1292 MB |

`raw_tushare.cyq_chips` 总体积约 32GB，其中表 heap 约 14GB，索引约 18GB。若只迁移表 heap，只能释放约 14GB SSD；若表和索引一起迁移，才能接近释放 32GB SSD。

## 3. 迁移策略

### 3.1 已拍板策略

从查询/写入性能角度看，复用现有 HDD tablespace 与新建独立 HDD tablespace 没有本质差异。真正决定性能的是底层 `/dev/vdb` 机械盘、ext4 文件系统、I/O 队列，以及表和索引是否迁到 HDD。

因此本轮拍板为：

```text
复用现有 HDD tablespace: gs_stk_mins_hdd
先 rename 为:              gs_raw_cold_hdd
底层路径保持:              /data/disk/postgresql/tablespaces/gs_stk_mins_hdd
```

理由：

1. 性能上，复用和新建都落在同一块 `/dev/vdb` 上，没有可见收益差异。
2. `gs_stk_mins_hdd` 当前只承载约 3MB 数据，基本为空，复用风险低。
3. 直接 rename 后，PostgreSQL 内部 tablespace 名称变为通用冷 raw 语义，不再误导后续判断。
4. rename 只改 PostgreSQL catalog 名称，不移动文件系统目录，风险低、速度快。
5. 不为了目录名额外移动底层目录；路径名不影响查询或写入性能。

### 3.2 本轮迁移对象

本轮建议迁移以下 4 个对象：

1. `raw_tushare.cyq_chips`
2. `raw_tushare.cyq_chips_pkey`
3. `raw_tushare.idx_raw_tushare_cyq_chips_ts_code_trade_date`
4. `raw_tushare.idx_raw_tushare_cyq_chips_trade_date`

如果只迁移 heap，不迁移索引，SSD 释放不足一半；本轮目标是缓解磁盘紧张，所以已拍板表和全部索引一起迁移。

## 4. 业务影响

`core_serving.equity_cyq_chips` 是 view，直接读取 `raw_tushare.cyq_chips`。tablespace 迁移不会改变表名、schema、主键、索引名、view 定义和业务 SQL。

主要影响来自迁移过程的锁：

1. `ALTER TABLE ... SET TABLESPACE` 会移动表文件，期间需要排他锁。
2. `ALTER INDEX ... SET TABLESPACE` 会移动索引文件，期间会影响依赖该索引的读写。
3. 迁移窗口内不要运行 `cyq_chips` 同步任务，也不要做依赖该表的大查询。
4. 迁移结束后，业务入口无需改代码。

建议预留 1 到 2 小时维护窗口。真实耗时取决于 SSD 读、HDD 写和当时系统 I/O。

## 5. 执行步骤

以下命令已在 2026-06-01 执行完成。

### 5.1 迁移前只读确认

确认磁盘：

```bash
ssh goldenshare-prod df -hT / /data/disk
```

确认当前 tablespace：

```bash
bash scripts/psql-remote.sh -c "select spcname, pg_tablespace_location(oid) from pg_tablespace order by spcname;"
```

确认 `cyq_chips` 当前位置：

```sql
with objects as (
  select 'table' as object_type, c.oid as object_oid, n.nspname as schema_name, c.relname as object_name, c.reltablespace
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'raw_tushare' and c.relname = 'cyq_chips'
  union all
  select 'index' as object_type, i.indexrelid as object_oid, ni.nspname as schema_name, ci.relname as object_name, ci.reltablespace
  from pg_index i
  join pg_class ct on ct.oid = i.indrelid
  join pg_namespace nt on nt.oid = ct.relnamespace
  join pg_class ci on ci.oid = i.indexrelid
  join pg_namespace ni on ni.oid = ci.relnamespace
  where nt.nspname = 'raw_tushare' and ct.relname = 'cyq_chips'
)
select
  object_type,
  schema_name,
  object_name,
  coalesce(ts.spcname, 'database_default') as tablespace,
  pg_size_pretty(pg_relation_size(object_oid)) as relation_size,
  pg_relation_filepath(object_oid) as relation_filepath
from objects
left join pg_tablespace ts on ts.oid = objects.reltablespace
order by object_type desc, object_name;
```

### 5.2 rename 现有 HDD tablespace

本轮不新建 tablespace，改为复用并 rename 现有 `gs_stk_mins_hdd`。

```sql
alter tablespace gs_stk_mins_hdd rename to gs_raw_cold_hdd;
```

执行入口：

```bash
ssh goldenshare-prod 'sudo -n -u postgres psql -d goldenshare -c "ALTER TABLESPACE gs_stk_mins_hdd RENAME TO gs_raw_cold_hdd;"'
```

说明：

1. rename 只修改 PostgreSQL catalog 中的 tablespace 名称。
2. 底层目录仍是 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`。
3. 不建议为了目录名再移动底层目录，因为那不会提升性能，只会增加操作风险。

### 5.3 暂停相关写入

迁移窗口内必须确保没有 `cyq_chips` 同步任务运行或排队执行。本次执行前通过 `ops.task_run` 确认：

1. 没有 `queued`、`running`、`canceling` 状态的 `cyq_chips` 任务。
2. 未停止 ops worker。
3. 迁移期间未发起新的 `cyq_chips` 手动任务。

### 5.4 迁移表与索引

推荐逐个对象执行，便于观察耗时和失败位置。

```sql
alter table raw_tushare.cyq_chips set tablespace gs_raw_cold_hdd;
alter index raw_tushare.cyq_chips_pkey set tablespace gs_raw_cold_hdd;
alter index raw_tushare.idx_raw_tushare_cyq_chips_ts_code_trade_date set tablespace gs_raw_cold_hdd;
alter index raw_tushare.idx_raw_tushare_cyq_chips_trade_date set tablespace gs_raw_cold_hdd;
```

执行入口仍优先使用：

```bash
bash scripts/psql-remote.sh -c "<上面的单条 SQL>"
```

说明：当前 `goldenshare_user` 是表 owner，且对现有 HDD tablespace 有 CREATE 权限。rename 后权限随 tablespace 保留，可以继续执行这些迁移 SQL。

### 5.5 迁移后验证

验证对象 tablespace：

```sql
with objects as (
  select 'table' as object_type, c.oid as object_oid, n.nspname as schema_name, c.relname as object_name, c.reltablespace
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'raw_tushare' and c.relname = 'cyq_chips'
  union all
  select 'index' as object_type, i.indexrelid as object_oid, ni.nspname as schema_name, ci.relname as object_name, ci.reltablespace
  from pg_index i
  join pg_class ct on ct.oid = i.indrelid
  join pg_namespace nt on nt.oid = ct.relnamespace
  join pg_class ci on ci.oid = i.indexrelid
  join pg_namespace ni on ni.oid = ci.relnamespace
  where nt.nspname = 'raw_tushare' and ct.relname = 'cyq_chips'
)
select
  object_type,
  schema_name,
  object_name,
  coalesce(ts.spcname, 'database_default') as tablespace,
  pg_size_pretty(pg_relation_size(object_oid)) as relation_size
from objects
left join pg_tablespace ts on ts.oid = objects.reltablespace
order by object_type desc, object_name;
```

验证磁盘释放：

```bash
ssh goldenshare-prod df -hT / /data/disk
```

验证最小读路径：

```sql
select count(*)
from raw_tushare.cyq_chips
where ts_code = '000001.SZ'
  and trade_date >= date '2026-05-01';
```

## 6. 回滚方案

若迁移后性能不可接受，或发现 HDD tablespace 不稳定，可以迁回默认 tablespace：

```sql
alter table raw_tushare.cyq_chips set tablespace pg_default;
alter index raw_tushare.cyq_chips_pkey set tablespace pg_default;
alter index raw_tushare.idx_raw_tushare_cyq_chips_ts_code_trade_date set tablespace pg_default;
alter index raw_tushare.idx_raw_tushare_cyq_chips_trade_date set tablespace pg_default;
```

回滚同样需要维护窗口，因为仍然会移动大文件并持有锁。

## 6.1 执行后验收记录

### 6.1.1 Tablespace

| tablespace | owner | location |
| --- | --- | --- |
| `gs_raw_cold_hdd` | `postgres` | `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd` |

说明：catalog 名称已改为 `gs_raw_cold_hdd`，物理目录名按计划保持不变。

### 6.1.2 对象位置

| 对象 | 类型 | tablespace | 大小 |
| --- | --- | --- | ---: |
| `raw_tushare.cyq_chips` | table heap | `gs_raw_cold_hdd` | 14 GB |
| `raw_tushare.cyq_chips_pkey` | index | `gs_raw_cold_hdd` | 14 GB |
| `raw_tushare.idx_raw_tushare_cyq_chips_ts_code_trade_date` | index | `gs_raw_cold_hdd` | 2480 MB |
| `raw_tushare.idx_raw_tushare_cyq_chips_trade_date` | index | `gs_raw_cold_hdd` | 1292 MB |

### 6.1.3 磁盘空间

| 挂载点 | 执行前可用 | 执行后可用 | 变化 |
| --- | ---: | ---: | ---: |
| `/` | 14G | 46G | 释放约 32G |
| `/data/disk` | 374G | 342G | 增加约 32G |

### 6.1.4 最小读验证

执行：

```sql
select count(*)
from raw_tushare.cyq_chips
where ts_code = '000001.SZ'
  and trade_date >= date '2026-05-01';
```

结果：`1890`。读路径正常。

## 7. 风险与边界

1. 本方案不删除、不清空、不重建 `raw_tushare.cyq_chips`。
2. 本方案不修改 `core_serving.equity_cyq_chips` view。
3. 迁移期间会阻塞 `cyq_chips` 相关读写，必须选择低峰窗口。
4. 机械盘查询延迟高于 SSD，迁移后 `cyq_chips` 大查询会变慢。
5. 备份恢复流程必须包含 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`。虽然 PostgreSQL catalog 名称会改为 `gs_raw_cold_hdd`，但底层目录名仍是 `gs_stk_mins_hdd`。
6. 如果未来把更多 raw 表迁移到 HDD，必须逐表评估访问热度，不允许把所有业务表粗暴迁移。

## 8. 待拍板项

| 编号 | 问题 | 建议 |
| --- | --- | --- |
| D1 | 是否新建 `gs_raw_cold_hdd` tablespace | 已拍板：不新建，复用 `gs_stk_mins_hdd` 并 rename 为 `gs_raw_cold_hdd`。 |
| D2 | 是否表和索引一起迁移 | 已拍板：表和全部索引一起迁移，释放约 32GB SSD。 |
| D3 | 是否允许迁移期间短暂停止 ops worker | 已执行：执行前确认没有 `cyq_chips` 运行或排队任务，本次未停止 ops worker。 |
| D4 | 迁移窗口 | 已执行：2026-06-01 08:10 ~ 08:16 CST。 |
