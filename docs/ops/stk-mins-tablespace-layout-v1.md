# 股票历史分钟行情 tablespace 冷热分层记录 v1

状态：当前生效  
执行日期：2026-04-26  
适用对象：远程生产库 `goldenshare`，表 `raw_tushare.stk_mins` 及其月分区。  
操作性质：生产数据库物理存储布局调整，非业务表结构变更。

---

## 1. 背景

`raw_tushare.stk_mins` 是股票历史分钟行情数据集，数据量远大于普通日频数据集。为降低 SSD 容量压力，同时保留近期数据查询性能，本次采用 PostgreSQL tablespace 对该分区表做冷热分层：

1. 当前年份数据保留在默认 tablespace（旧盘，SSD）。
2. `2025` 年及以前历史数据放到新挂载磁盘（HDD）。
3. 该策略仅适用于 `raw_tushare.stk_mins`，不扩散到其他表。

---

## 2. 目标规则

| 数据范围 | 存储位置 | tablespace |
|---|---|---|
| `stk_mins_2025_12` 及以前月分区 | 新挂载 HDD | `gs_stk_mins_hdd` |
| `stk_mins_2026_01` 及以后月分区 | 原 SSD | `pg_default` |
| `stk_mins_default` | 原 SSD | `pg_default` |

说明：

1. `stk_mins_default` 不是明确年份分区，本次不迁移。
2. 分区表和对应索引必须放在同一冷热层，避免容量与性能判断混乱。
3. 以后进入新年份时，如继续执行“今年 SSD、去年及以前 HDD”策略，需要做年度 rollover，把上一年的月分区迁入 `gs_stk_mins_hdd`。

---

## 3. 磁盘与挂载信息

新磁盘：

| 项 | 值 |
|---|---|
| 设备 | `/dev/vdb` |
| 文件系统 | `ext4` |
| UUID | `cf9c2a7f-2811-424e-b6ac-b8c9717381bf` |
| 挂载点 | `/data/disk` |
| 容量 | 约 `394G` |

`/etc/fstab` 当前规则：

```text
UUID=cf9c2a7f-2811-424e-b6ac-b8c9717381bf /data/disk ext4 defaults 0 0
```

本次曾将初始挂载点从 `/root/data/disk` 调整为 `/data/disk`。原因是 `/root` 权限为 `700`，不适合作为 PostgreSQL tablespace 的长期路径。

配置变更后已执行：

```bash
sudo -n systemctl daemon-reload
sudo -n findmnt --verify --verbose /data/disk
```

验证结果：`/data/disk` 挂载校验无错误。

---

## 4. PostgreSQL tablespace

tablespace 名称：

```text
gs_stk_mins_hdd
```

目录：

```text
/data/disk/postgresql/tablespaces/gs_stk_mins_hdd
```

目录权限：

```text
postgres:postgres
700
```

tablespace 注释：

```text
Goldenshare stk_mins cold partitions <=2025 on HDD; 2026+ stay on pg_default SSD.
```

授权：

```sql
GRANT CREATE ON TABLESPACE gs_stk_mins_hdd TO goldenshare_user;
```

---

## 5. 已执行迁移

迁移对象：

1. `raw_tushare.stk_mins_2010_01` 到 `raw_tushare.stk_mins_2025_12`
2. 上述每个月分区对应的索引

迁移结果：

| 对象类型 | 数量 |
|---|---:|
| 月分区表 | `192` |
| 分区索引 | `576` |

保留在默认 tablespace 的对象：

1. `raw_tushare.stk_mins_2026_01` 及以后月分区
2. 上述分区索引
3. `raw_tushare.stk_mins_default`

---

## 6. 当前验证结果

执行后校验结果：

| 检查项 | 违规数 |
|---|---:|
| `2025` 及以前分区表未在 `gs_stk_mins_hdd` | `0` |
| `2025` 及以前分区索引未在 `gs_stk_mins_hdd` | `0` |
| `2026` 及以后分区表误在 `gs_stk_mins_hdd` | `0` |
| `2026` 及以后分区索引误在 `gs_stk_mins_hdd` | `0` |

样例：

| 对象 | tablespace |
|---|---|
| `stk_mins_2025_12` | `gs_stk_mins_hdd` |
| `stk_mins_2026_01` | `pg_default` |
| `stk_mins_default` | `pg_default` |

当前空间分布（表分区维度）：

| tablespace | 分区数 | 当前占用 |
|---|---:|---:|
| `gs_stk_mins_hdd` | `192` | 约 `6 MB` |
| `pg_default` | `132` | 约 `4 MB` |

新盘使用情况：

```text
/dev/vdb ext4 394G，当前已用约 6.1M，可用约 374G，挂载 /data/disk
```

---

## 7. 日常审计 SQL

### 7.1 检查分区表是否放错 tablespace

```sql
WITH parts AS (
    SELECT
        c.oid,
        c.relname,
        split_part(c.relname, '_', 3)::int AS year,
        CASE WHEN c.reltablespace = 0 THEN 'pg_default' ELSE ts.spcname END AS table_ts
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_tablespace ts ON ts.oid = c.reltablespace
    WHERE n.nspname = 'raw_tushare'
      AND c.relkind = 'r'
      AND c.relname ~ '^stk_mins_[0-9]{4}_[0-9]{2}$'
)
SELECT 'history_table_not_hdd' AS check_name, count(*) AS violations
FROM parts
WHERE year <= 2025 AND table_ts <> 'gs_stk_mins_hdd'
UNION ALL
SELECT 'current_future_table_not_default', count(*)
FROM parts
WHERE year >= 2026 AND table_ts <> 'pg_default';
```

### 7.2 检查分区索引是否放错 tablespace

```sql
WITH idx AS (
    SELECT
        c.relname AS partition_name,
        split_part(c.relname, '_', 3)::int AS year,
        ic.relname AS index_name,
        CASE WHEN ic.reltablespace = 0 THEN 'pg_default' ELSE ts.spcname END AS index_ts
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_index ix ON ix.indrelid = c.oid
    JOIN pg_class ic ON ic.oid = ix.indexrelid
    LEFT JOIN pg_tablespace ts ON ts.oid = ic.reltablespace
    WHERE n.nspname = 'raw_tushare'
      AND c.relkind = 'r'
      AND c.relname ~ '^stk_mins_[0-9]{4}_[0-9]{2}$'
)
SELECT 'history_index_not_hdd' AS check_name, count(*) AS violations
FROM idx
WHERE year <= 2025 AND index_ts <> 'gs_stk_mins_hdd'
UNION ALL
SELECT 'current_future_index_not_default', count(*)
FROM idx
WHERE year >= 2026 AND index_ts <> 'pg_default';
```

### 7.3 查看 tablespace 分布

```sql
SELECT
    CASE WHEN c.reltablespace = 0 THEN 'pg_default' ELSE ts.spcname END AS table_ts,
    count(*) AS partitions,
    pg_size_pretty(sum(pg_total_relation_size(c.oid))) AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_tablespace ts ON ts.oid = c.reltablespace
WHERE n.nspname = 'raw_tushare'
  AND c.relkind = 'r'
  AND c.relname ~ '^stk_mins_[0-9]{4}_[0-9]{2}$'
GROUP BY table_ts
ORDER BY table_ts;
```

---

## 8. 未来维护要求

### 8.1 年度 rollover

如果继续使用“当前年份在 SSD、历史年份在 HDD”的规则，每年进入新年份后需要执行一次 rollover：

1. 确认上一年份已经不再属于当前热数据。
2. 将上一年份的 `stk_mins_YYYY_01` 到 `stk_mins_YYYY_12` 分区表迁到 `gs_stk_mins_hdd`。
3. 将上述分区索引迁到 `gs_stk_mins_hdd`。
4. 执行第 7 章审计 SQL，确认违规数为 `0`。

### 8.2 新分区创建规则

后续如果新增自动建分区能力，必须遵守：

1. 当前年份分区默认创建在 `pg_default`。
2. 历史年份补建分区必须创建在 `gs_stk_mins_hdd`。
3. 表分区和索引必须同步指定 tablespace。

### 8.3 运维检查

同步或回补大规模 `stk_mins` 前，至少检查：

```bash
ssh goldenshare-prod 'sudo -n df -hT / /data/disk'
```

并执行第 7 章 SQL，确认 tablespace 规则没有漂移。

---

## 9. 注意事项

1. 本文只记录 `raw_tushare.stk_mins` 的物理存储布局，不代表其他数据集也采用冷热分盘。
2. PostgreSQL tablespace 目录必须纳入备份、迁移和监控。
3. 如果 `/data/disk` 未挂载，PostgreSQL 访问历史分区会失败，严重时可能影响数据库启动或对象访问。
4. 迁移已有大分区时会产生 IO 和锁风险；本次执行时 `stk_mins` 基本为空，因此迁移成本很低。
5. 不允许手工移动 tablespace 目录下的 PostgreSQL 文件；所有迁移必须通过 PostgreSQL DDL 完成。
