# 股票历史分钟行情存储瘦身与滚动冷热治理方案 v1

- 版本：v1
- 状态：表结构瘦身已实施；2026-08-23 P0 滚动冷热迁移方案已完成审计，生产 DDL 尚未执行、仍需单独授权
- 更新时间：2026-08-23
- 数据集：`stk_mins`
- 物理表：`raw_tushare.stk_mins`
- 服务入口：`core_serving.equity_minute_bar`
- 当前目标：将 2026-01～2026-06 已关闭月份的叶分区和全部物理索引从 `pg_default` 迁至 `gs_raw_cold_hdd`

权威边界：当前代码、迁移、生产 catalog 和只读运行证据决定现状；本文固定本次 P0 方案和后续滚动规则，但不是生产迁移授权。2026-04-27 的空表 drop/recreate 方案已经完成其历史使命，不得再次用于当前非空生产表。

---

## 1. 结论

当前最合理的 P0 处理是：

1. 保留当前自然月和上一个自然月的 `stk_mins` 月分区在 SSD。
2. 将更早且已关闭的月份迁入 HDD。
3. 以 2026-08-23 为执行基准，白名单仅为 `2026-01`～`2026-06`；`2026-07`、`2026-08` 和 default 分区继续留在 SSD。
4. 六个月预计释放约 28.3 GiB SSD，使根盘可用空间由约 5.5 GiB 提升到约 33.7 GiB，使用率预计由 98% 降至约 84%。实际值必须逐对象复验。
5. 本次只执行 PostgreSQL 原生 `ALTER TABLE/INDEX ... SET TABLESPACE`。不删表、不重建表、不复制或改写业务行、不请求 Tushare、不修改 Definition、ORM、DAO、API、前端或 TaskRun 语义。
6. WAL 继续位于 PostgreSQL 根盘；tablespace 只改变业务 relation 的物理位置，不改变实例级 WAL。

P0 完成后必须停止继续迁移并观察。只有容量仍不足，才按[生产 PostgreSQL 存储空间优化治理专项 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v1.md)重新授权 P1。

## 2. 已核验的当前事实

### 2.1 当前代码契约

当前实现已经完成原方案的表结构瘦身：

1. `RawStkMins` 只有 `ts_code/freq/trade_time/open/close/high/low/vol/amount` 九列。
2. 主键为 `(ts_code, freq, trade_time)`；`vol` 的当前 ORM 类型为 `BIGINT`，不能继续沿用旧文档中的 `INTEGER`。
3. `freq` 在请求和任务输入中使用 `1min/5min/15min/30min/60min`，在 row transform 中归一化为 `1/5/15/30/60` 后存储。
4. `DatasetDefinition` 当前为 `raw_only_upsert`，目标为 `raw_tushare.stk_mins`，观察字段为 `trade_time`，每个 unit 幂等 upsert。
5. `core_serving.equity_minute_bar` 是普通 view，`trade_date` 由 `trade_time::date` 派生，不复制业务数据。
6. 当前代码中发现的直接 raw 消费者是成交额快照物化服务；它按目标交易日的半开时间范围和频率查询，主要访问近期分区。
7. 当前 ORM 只声明主键；生产迁移前仍必须从 `pg_index` 动态枚举实际物理索引，不能用文档猜索引名或数量。

代码证据：

- `src/foundation/models/raw/raw_stk_mins.py`
- `src/foundation/ingestion/row_transforms.py::_stk_mins_row_transform`
- `src/foundation/datasets/definitions/market_equity.py` 中 `stk_mins` Definition
- `src/biz/services/wealth/market/turnover/turnover_snapshot_materialize_service.py`
- `alembic/versions/20260427_000080_slim_stk_mins_storage.py`
- `alembic/versions/20260427_000081_widen_stk_mins_vol_to_bigint.py`

### 2.2 当前生产物理事实

2026-08-23 只读审计结果：

| 项目 | 当前事实 |
| --- | --- |
| 父表 | `raw_tushare.stk_mins`，按 `trade_time` 月分区 |
| 叶分区 | 2010-01～2036-12 加 default，共 325 个 |
| 2025 及以前 | 192 个历史月分区位于 `gs_raw_cold_hdd`；当前实际数据量接近空，不是本次主要释放来源 |
| 2026 | 1～8 月实际承载数据并位于 `pg_default`；9～12 月及 default 当前为空或接近空 |
| 估算行数 | 约 263,462,994 行，主要集中于 2026-01～08 |
| 总关系大小 | 约 38 GiB，其中 heap 约 21 GiB、索引约 16 GiB |
| HDD tablespace | `gs_raw_cold_hdd` -> `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd` |
| 根盘 | 可用约 5.5 GiB，使用率 98% |
| HDD | 可用约 316 GiB，使用率 16% |
| WAL | `pg_wal` 约 417 MiB，仍在根盘；无 replication slot，归档关闭 |

2026 月分区实际体积：

| 月份 | heap | 索引 | 合计 | P0 处理 |
| --- | ---: | ---: | ---: | --- |
| 2026-01 | 约 2.76 GiB | 约 2.31 GiB | 约 5.07 GiB | 迁 HDD |
| 2026-02 | 约 1.94 GiB | 约 1.60 GiB | 约 3.54 GiB | 迁 HDD，先导批次 |
| 2026-03 | 约 3.07 GiB | 约 1.95 GiB | 约 5.02 GiB | 迁 HDD |
| 2026-04 | 约 2.93 GiB | 约 1.99 GiB | 约 4.92 GiB | 迁 HDD |
| 2026-05 | 约 2.51 GiB | 约 1.99 GiB | 约 4.50 GiB | 迁 HDD |
| 2026-06 | 约 2.94 GiB | 约 2.26 GiB | 约 5.20 GiB | 迁 HDD |
| 2026-07 | 约 3.21 GiB | 约 2.51 GiB | 约 5.73 GiB | 保留 SSD |
| 2026-08 | 约 2.10 GiB | 约 1.60 GiB | 约 3.70 GiB | 保留 SSD |

PostgreSQL `pg_size_pretty` 和文件系统展示存在取整差异；P0 六个月的 catalog 原始字节合计为 30,340,677,632 bytes，即约 28.3 GiB，执行时应保存原始字节而不是只记录格式化值。

### 2.3 已纠正的旧结论

| 旧结论 | 当前纠正 |
| --- | --- |
| 文档状态“待评审” | 表结构瘦身早已实施；当前待执行的是独立的 P0 物理迁移 |
| 生产表为空，可以 drop/recreate | 当前约 2.63 亿行，禁止 drop、truncate、recreate 或复制切换 |
| `vol` 为 `INTEGER` | 当前 ORM/迁移已扩为 `BIGINT` |
| HDD tablespace 为 `gs_stk_mins_hdd` | 当前 catalog 名称为 `gs_raw_cold_hdd`；旧名称只存在于历史迁移和物理目录名 |
| 2026 及以后全部留 SSD | 已被实际容量证明不可持续；改为两个月滚动热窗口 |
| 每年 rollover 一次 | 改为每月评估并迁移 `M-2` 月份；仍需逐次维护授权 |
| P0 需要重做 schema/ORM/Definition | 不需要；P0 只移动既有叶分区和索引的 tablespace |

## 3. 当前表结构与长期存储规则

### 3.1 表结构

当前逻辑结构固定为：

```sql
CREATE TABLE raw_tushare.stk_mins (
    ts_code varchar(16) NOT NULL,
    freq smallint NOT NULL,
    trade_time timestamp without time zone NOT NULL,
    open real,
    close real,
    high real,
    low real,
    vol bigint,
    amount real,
    CONSTRAINT pk_raw_tushare_stk_mins
        PRIMARY KEY (ts_code, freq, trade_time)
) PARTITION BY RANGE (trade_time);
```

本次 P0 不修改上述结构。生产真实列、约束、分区边界和索引仍需在 DDL 前从 catalog 复验。

### 3.2 服务查询规则

`core_serving.equity_minute_bar` 继续从 raw 表派生 `trade_date`。任何按日查询必须使用 `trade_time` 半开区间：

```sql
trade_time >= :trade_date::date
AND trade_time < (:trade_date::date + interval '1 day')
```

禁止在大表过滤条件中使用 `trade_time::date = :trade_date`。P0 不改变 view 或调用方 SQL。

### 3.3 两个月滚动热窗口

设执行时当前自然月为 `M`：

| 数据范围 | 目标位置 |
| --- | --- |
| 当前月 `M` | `pg_default`（SSD） |
| 上一个月 `M-1` | `pg_default`（SSD） |
| `M-2` 及以前的关闭月份 | `gs_raw_cold_hdd`（HDD） |
| `stk_mins_default` | `pg_default`，不得作为历史数据长期承载区 |

规则说明：

1. “关闭月份”表示该自然月边界已结束，不表示源端永不再修订；后续补录仍允许通过父表正常 upsert 到 HDD 叶分区，只接受相对较慢的写入。
2. 迁移以整个月叶分区为最小业务批次。一个月的 heap/TOAST 和全部物理索引最终必须同处 HDD。
3. 父级 partitioned relation 没有业务数据块，不用它的 tablespace 代替叶对象验收。
4. 当前预创建分区已覆盖到 2036 年。未来新增分区时，应先按当时热窗口选择 tablespace，不能继续照抄历史 migration 中的“年份 <= 2025”常量。
5. 2026-04 的 migration 使用旧 catalog 名称并在 tablespace 不存在时回退默认盘，这是不可修改的历史 revision；新环境 bootstrap 和未来分区治理必须另行增加基于 `gs_raw_cold_hdd` 的 fail-closed 校验，不能修改已应用 migration 冒充修复。本项不阻塞当前 P0，但属于后续代码治理项。

## 4. P0 范围与明确禁止项

### 4.1 唯一白名单

只允许处理：

```text
raw_tushare.stk_mins_2026_01
raw_tushare.stk_mins_2026_02
raw_tushare.stk_mins_2026_03
raw_tushare.stk_mins_2026_04
raw_tushare.stk_mins_2026_05
raw_tushare.stk_mins_2026_06
以及执行时从 pg_index 枚举出的上述六个叶分区的全部物理索引
```

### 4.2 禁止处理

1. `stk_mins_2026_07`、`stk_mins_2026_08`。
2. `stk_mins_default`、父表、父级 partitioned index。
3. 其它年份、其它 schema、其它数据集。
4. 任何 `DROP/TRUNCATE/DELETE/CREATE TABLE AS/INSERT ... SELECT`。
5. 手工移动 PostgreSQL tablespace 目录中的文件。
6. 修改 WAL 目录、PostgreSQL 全局配置、Definition、任务计划、源请求或业务查询。
7. 发起 Tushare 请求或用源端重拉代替物理迁移验收。

## 5. 执行载体与事务边界

P0 是容量和运行状态敏感的生产物理维护，不放入普通部署 Alembic：

1. Alembic 应描述可随版本部署的确定性 schema 变化；P0 需要实时检查任务、锁、挂载、根盘、WAL 和逐对象空间，不适合隐藏在应用部署升级里。
2. 通过既有生产数据库入口执行显式白名单 DDL；每条 `ALTER TABLE` 或 `ALTER INDEX` 使用独立连接、独立事务并自动提交。
3. 每条 DDL 先设置 `lock_timeout='15s'`。拿不到锁立即失败，不等待、不终止业务会话。
4. `statement_timeout` 应在维护窗口按单关系大小设置；本方案建议单条上限 60 分钟。超时由 PostgreSQL 回滚当前单条关系，不继续后续对象。
5. 不使用 `ALTER ... ALL IN TABLESPACE`，避免把白名单外对象带入迁移。
6. 不把六个月或一个月的全部对象包在一个长事务中。

示意执行方式：

```sql
SET lock_timeout = '15s';
SET statement_timeout = '60min';
ALTER INDEX raw_tushare.<本次枚举出的单个索引>
    SET TABLESPACE gs_raw_cold_hdd;
```

```sql
SET lock_timeout = '15s';
SET statement_timeout = '60min';
ALTER TABLE raw_tushare.<本次白名单中的单个叶分区>
    SET TABLESPACE gs_raw_cold_hdd;
```

`ALTER TABLE` 移动叶分区 heap/TOAST，但不会替代全部索引迁移；索引必须逐个执行和验收。

## 6. P0 详细步骤

### P0-0：授权与版本冻结

1. 确认本次授权只包含六个月 tablespace 迁移，不包含 P1、代码修改、部署、源端同步或自动滚动任务。
2. 记录远程 Git revision、Alembic head、PostgreSQL 启动时间和审计时间。
3. 重新确认本文目标表结构、Definition 和消费者没有在审计后发生变化；变化即停止并重新评审。

### P0-1：磁盘、tablespace 与 WAL 门禁

必须在同一维护窗口重新确认：

1. `/data/disk` 由 `findmnt` 证明是实际挂载，不是未挂载时落在根盘的普通目录。
2. `gs_raw_cold_hdd` 存在，实际路径仍为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`，执行角色具有 `CREATE` 权限。
3. HDD 可用空间不低于“剩余待迁关系大小的 120%”，且绝对值不低于 64 GiB。
4. 每个关系执行前，根盘可用空间必须同时满足：不少于 4 GiB，且不少于该关系大小加 2 GiB 安全余量。
5. 记录 `pg_wal` 当前大小、归档、replication slot、长事务和 checkpoint 配置；不能因 `max_wal_size=1GB` 就假设 WAL 绝不会超过 1 GiB。
6. 根盘或 HDD 水位在执行过程中恶化、不再满足门禁时，停止后续关系。

### P0-2：任务、写入与锁门禁

1. `ops.task_run` 中不得存在 `stk_mins` 的 `queued/running/canceling` 任务。
2. 为避免同盘 I/O 竞争，维护窗口内不得有其它大规模回补、迁移或长分页写入任务；执行前应等待当前开放 TaskRun 清空。
3. 暂停 `stk_mins` 自动任务，并通过运营流程保证维护窗口内不能创建新的手工 `stk_mins` 任务；记录暂停前配置，迁移验收前不恢复。
4. `pg_stat_activity` 不得有目标分区相关长查询或超过 30 秒的非 idle 事务。
5. `pg_locks` 不得有目标分区或其索引的已授予/等待冲突锁。
6. 不主动终止业务会话；发现占用即停止本轮。

### P0-3：生成不可变执行白名单

执行时必须从 catalog 重新生成并保存：

1. 六个叶分区的 OID、分区边界、heap/TOAST/索引原始字节数和当前 tablespace。
2. 每个叶分区实际关联的全部索引名称、`indisvalid`、`indisready` 和 tablespace。
3. 白名单外 2026-07、2026-08、default、父表和父级索引的基线位置。
4. 每月精确 `count(*)`、`min(trade_time)`、`max(trade_time)`；任务暂停后这些值构成迁移前逻辑基线。

示意 catalog 查询：

```sql
WITH target(relname) AS (
    VALUES
        ('stk_mins_2026_01'), ('stk_mins_2026_02'),
        ('stk_mins_2026_03'), ('stk_mins_2026_04'),
        ('stk_mins_2026_05'), ('stk_mins_2026_06')
)
SELECT
    n.nspname,
    c.relname,
    c.oid,
    pg_get_expr(c.relpartbound, c.oid) AS partition_bound,
    COALESCE(ts.spcname, 'pg_default') AS tablespace,
    pg_relation_size(c.oid) AS heap_bytes,
    pg_total_relation_size(c.oid) AS total_bytes
FROM target t
JOIN pg_class c ON c.relname = t.relname
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_tablespace ts ON ts.oid = c.reltablespace
WHERE n.nspname = 'raw_tushare'
ORDER BY c.relname;
```

索引必须通过 `pg_index` 与叶分区 OID 关联枚举，禁止按名称规则拼接。

### P0-4：2026-02 先导批次

`2026-02` 是当前六个月中最小的完整月，合计约 3.54 GiB，先用于验证锁、耗时、WAL 和空间释放：

1. 按实际 `pg_relation_size` 从小到大移动该月物理索引；每个索引完成后立即核验 tablespace、`indisvalid/indisready`、根盘/HDD和锁。
2. 移动 `stk_mins_2026_02` 叶分区 heap/TOAST。
3. 确认该月 heap 和全部物理索引最终均为 `gs_raw_cold_hdd`。
4. 重新执行精确行数、最早/最晚时间、父表和 view 最小读取；与迁移前基线一致。
5. 记录每个对象耗时、WAL 前后大小和文件系统水位。
6. 只有先导批次全部通过，才进入其余月份。

### P0-5：其余月份逐月执行

按当前体积从小到大执行，顺序固定为：

```text
2026-05 -> 2026-04 -> 2026-03 -> 2026-01 -> 2026-06
```

每个月重复 P0-4 的完整流程。上一个月未闭环时，不得开始下一个月；不得并行移动关系。

### P0-6：最终验收

必须同时满足：

1. 2026-01～06 六个 heap/TOAST 和执行时枚举出的全部物理索引位于 `gs_raw_cold_hdd`。
2. 2026-07、2026-08、default 分区及其索引仍位于 `pg_default`；白名单外对象没有变化。
3. 六个月逐月精确行数、最早/最晚时间与迁移前一致；索引全部 `indisvalid=true`、`indisready=true`。
4. 通过父表和 `core_serving.equity_minute_bar` 分别读取每个月的代表性股票、频率和时间范围，结果与迁移前一致。
5. 当前热月的成交额快照物化查询保持可用；至少对当前月做一条只读代表性查询，证明没有误迁热分区。
6. SSD 释放与 28.3 GiB 量级相符，HDD 增量相符；差异必须解释 WAL、并发写入和文件系统保留块，不以单次 `df` 作为唯一证据。
7. PostgreSQL、Web、worker、scheduler 健康；没有因迁移产生失败 TaskRun。
8. 六个月验收完成后，更新 tablespace 的遗留 catalog comment，清除“2026+ 永久 SSD”错误口径：

   ```sql
   COMMENT ON TABLESPACE gs_raw_cold_hdd IS
     'Goldenshare PostgreSQL cold-storage tablespace on /data/disk; dataset placement follows each current LLD; stk_mins keeps current and previous calendar months on pg_default';
   ```

9. 完成上述物理和元数据验收后再恢复原 `stk_mins` 自动任务配置，并观察首次正常任务；恢复任务不是迁移 DDL 的隐式步骤。

## 7. 失败、部分完成与回滚

1. 锁超时或 statement timeout：当前单条 DDL 由 PostgreSQL 回滚；停止后续对象，不自动重试。
2. 一个索引已经迁入 HDD、后续对象失败：保留已成功关系，记录部分状态；不为追求“看起来整齐”自动搬回 SSD。修复门禁后从未完成对象继续。
3. 一个完整月份已验收、后续月份失败：已完成月份保留，未完成月份不动；不得回滚已释放容量。
4. 逻辑基线、索引有效性、view 查询或白名单边界任一不一致：立即停止并升级为数据库故障审计，不执行删除、重建或源端重拉。
5. 迁移后历史查询变慢属于预期取舍；先记录代表性查询前后耗时。只有达到不可接受标准并重新确认 SSD 容量足够时，才可另行授权逐对象迁回 `pg_default`。
6. 回迁同样是大文件移动和强锁操作，不能把它当作无成本自动回滚。
7. `/data/disk` 未挂载或 tablespace 不可访问属于生产事故；不得在未挂载目录上继续 PostgreSQL 操作。

## 8. 后续每月滚动治理

P0 完成只解决当前告警。长期规则为：

1. 当进入新月份 `M` 后，唯一新增候选是 `M-2` 月分区。例如进入 2026-09 后，候选为 2026-07；2026-08 和 2026-09 保留 SSD。
2. 前两次月度 rollover 继续人工执行并记录真实耗时、锁等待、WAL、SSD/HDD水位和查询延迟；在证据稳定前不自动化生产 DDL。
3. 若后续开发自动化，只能建设受控存储治理命令：默认只读生成计划和白名单，显式 `execute` 才逐关系运行，带任务/锁/容量门禁和断点记录。不得把迁移逻辑塞进 DatasetDefinition、worker 或普通 schedule。
4. 每次 rollover 都需要独立生产授权；本文不授权未来月份自动执行。
5. 根盘 90% 进入预警，95% 停止新的大规模回补并重新做 Top 20 审计；不要等到 98% 才处理。
6. P0 最终验收必须同步修正 tablespace catalog comment，使其表达通用冷存储和 `stk_mins` 两个月滚动热窗口，不再保留“2026+ 永久 SSD”的误导文字。

## 9. 风险矩阵

| 风险 | 等级 | 防护 |
| --- | --- | --- |
| 根盘仅剩约 5.5 GiB，迁移过程中空间进一步下降 | 高 | 从最小 2026-02 关系开始；每关系校验“关系大小 + 2 GiB”和4 GiB绝对余量 |
| `ALTER TABLE/INDEX SET TABLESPACE` 强锁影响读写 | 高 | 暂停任务、检查长事务/锁、15秒 lock timeout、逐关系串行 |
| WAL 仍写根盘 | 中高 | 记录 `pg_wal`、逐关系提交、根盘水位门禁；不把 `max_wal_size` 当硬上限 |
| 索引遗漏或只迁 heap | 高 | 每次从 `pg_index` 枚举；最终按叶分区核验全部物理索引 |
| 白名单外热分区误迁 | 高 | 显式六个月 VALUES 白名单；复验 07/08/default 保持 `pg_default` |
| HDD 未真实挂载 | 很高 | `findmnt` 和 `pg_tablespace_location` 双重验证；异常立即停止 |
| 历史查询延迟升高 | 中 | 迁移前后代表性查询；仅关闭月份进入 HDD，热两月保留 SSD |
| 部分对象已迁、批次中断 | 中 | 接受可恢复中间态，记录完成清单并从断点继续，不自动回迁 |
| 旧 migration 在新环境回退默认盘 | 中 | 不修改历史 revision；后续单独增加当前 tablespace 的 fail-closed bootstrap 治理 |

## 10. 本轮不做

1. 不迁移 `index_mins`、技术因子、日线、资金流或任何 P1/P2/P3 表。
2. 不修改 `stk_mins` 请求、分页、对象池、并发、任务进度或 freshness。
3. 不新增、删除或重建任何分区和索引。
4. 不实现分钟级完整性审计。
5. 不迁移 PostgreSQL WAL。
6. 不创建自动 tablespace rollover schedule。
7. 不执行生产 DDL，直到用户对 P0 执行阶段另行明确授权。

## 11. 相关文档

1. [生产 PostgreSQL 存储空间优化治理专项 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v1.md)
2. [股票历史分钟行情 tablespace 冷热分层执行记录 v1（2026-04-26 历史快照）](/Users/congming/github/goldenshare/docs/ops/stk-mins-tablespace-layout-v1.md)
3. [股票历史分钟行情数据集开发说明](/Users/congming/github/goldenshare/docs/datasets/stk-mins-dataset-development.md)
4. [Core Serving + Serving Light 分层设计 v1](/Users/congming/github/goldenshare/docs/architecture/core-serving-light-design-v1.md)
