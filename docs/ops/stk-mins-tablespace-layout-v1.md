# 股票历史分钟行情 tablespace 冷热分层执行记录 v1

状态：历史执行记录；2026-04-26 快照；年度 rollover 规则已于 2026-08-23 被两个月滚动热窗口取代
执行日期：2026-04-26  
适用对象：远程生产库 `goldenshare`，表 `raw_tushare.stk_mins` 及其月分区。  
操作性质：生产数据库物理存储布局调整，非业务表结构变更。

> 权威边界：本记录只证明 2026-04-26 当时执行了什么。PostgreSQL catalog tablespace 后于 2026-06-01 改名为 `gs_raw_cold_hdd`，物理目录仍为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`。本文的年度冷热规则和第 7 节 SQL 仅用于复现历史口径，不再是当前合规检查；当前 P0 与后续月度规则统一以[股票历史分钟行情存储瘦身与滚动冷热治理方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-storage-slimming-plan-v1.md)为准。

---

## 1. 背景

`raw_tushare.stk_mins` 是股票历史分钟行情数据集，数据量远大于普通日频数据集。为降低 SSD 容量压力，同时保留近期数据查询性能，本次采用 PostgreSQL tablespace 对该分区表做冷热分层：

1. 当前年份数据保留在默认 tablespace（旧盘，SSD）。
2. `2025` 年及以前历史数据放到新挂载磁盘（HDD）。
3. 该策略仅适用于 `raw_tushare.stk_mins`，不扩散到其他表。

---

## 2. 目标规则（2026-04-26 执行口径）

| 数据范围 | 存储位置 | tablespace |
|---|---|---|
| `stk_mins_2025_12` 及以前月分区 | 新挂载 HDD | `gs_stk_mins_hdd` |
| `stk_mins_2026_01` 及以后月分区 | 原 SSD | `pg_default` |
| `stk_mins_default` | 原 SSD | `pg_default` |

说明：

1. `stk_mins_default` 不是明确年份分区，本次不迁移。
2. 分区表和对应索引必须放在同一冷热层，避免容量与性能判断混乱。
3. 当时曾计划以后按年度 rollover；该计划已于 2026-08-23 明确废止，不能继续据此安排未来迁移。

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

## 4. PostgreSQL tablespace（当前名称与遗留注释）

tablespace 名称：

```text
gs_raw_cold_hdd
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

2026-08-23 只读复验确认，catalog 仍保留以下历史注释：

```text
Goldenshare stk_mins cold partitions <=2025 on HDD; 2026+ stay on pg_default SSD.
```

该注释已经失真，只能作为遗留事实记录，不能作为当前分层策略。P0 验收阶段应在单独授权下把它改成通用冷存储说明，并指向数据集各自的 placement 规则。

当前授权对象：

```sql
GRANT CREATE ON TABLESPACE gs_raw_cold_hdd TO goldenshare_user;
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

## 6. 执行时验证结果（2026-04-26 快照）

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

## 7. 历史审计 SQL（仅复现 2026-04-26 口径）

以下 SQL 按“2025 及以前 HDD、2026 及以后 SSD”的旧规则编写。它可以复现当时验收，但会把当前应迁入 HDD 的 2026-01～06 误判为必须留在 SSD，因此禁止用作 2026-08-23 之后的合规门禁。当前审计必须按“两个月滚动热窗口”动态计算边界。

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
WHERE year <= 2025 AND table_ts <> 'gs_raw_cold_hdd'
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
WHERE year <= 2025 AND index_ts <> 'gs_raw_cold_hdd'
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

## 8. 当前维护规则的替代关系

### 8.1 年度 rollover 已废止

“当前年份在 SSD、历史年份在 HDD”的规则在 2026-08 已导致 1～8 月约 38 GiB 同时堆积于根盘，不能继续作为长期策略。当前规则为：

1. 当前自然月和上一个自然月留在 `pg_default`。
2. `M-2` 及以前关闭月份进入 `gs_raw_cold_hdd` 候选。
3. 每月只处理明确月份白名单，逐 heap/索引执行和验收；不自动执行 DDL。
4. 详细门禁、顺序、失败处理和验收见当前 `stk_mins` 滚动冷热治理方案。

### 8.2 新分区规则

当前迁移已经预创建到 2036 年。未来新增分区能力时：

1. 必须按创建时的两个月热窗口选择 tablespace，不能硬编码年份。
2. 补建关闭月份必须创建在 `gs_raw_cold_hdd`。
3. heap/TOAST 和全部物理索引必须最终位于同一层。
4. `gs_raw_cold_hdd` 不存在时必须 fail-closed，禁止静默回退默认 SSD。

### 8.3 运维检查

同步、回补或迁移大规模 `stk_mins` 前，至少检查真实挂载、tablespace、SSD/HDD、WAL、开放 TaskRun、长事务、锁和动态月边界。旧第 7 节 SQL不能代替这些门禁。

```bash
ssh goldenshare-prod 'sudo -n df -hT / /data/disk'
```

当前审计 SQL 和执行白名单由滚动冷热治理方案提供，并且每次生产执行前重新从 catalog 生成。

---

## 9. 注意事项

1. 本文只记录 `raw_tushare.stk_mins` 的物理存储布局，不代表其他数据集也采用冷热分盘。
2. PostgreSQL tablespace 目录必须纳入备份、迁移和监控。
3. 如果 `/data/disk` 未挂载，PostgreSQL 访问历史分区会失败，严重时可能影响数据库启动或对象访问。
4. 迁移已有大分区时会产生 IO 和锁风险；本次执行时 `stk_mins` 基本为空，因此迁移成本很低。
5. 不允许手工移动 tablespace 目录下的 PostgreSQL 文件；所有迁移必须通过 PostgreSQL DDL 完成。
