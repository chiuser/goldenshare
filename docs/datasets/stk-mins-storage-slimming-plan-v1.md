# 股票历史分钟行情存储瘦身与滚动冷热治理方案 v1

- 版本：v1
- 状态：表结构瘦身已实施；P0 生产物理迁移方案已完成第二轮安全复审，但当前仍为 **No-Go**，须先关闭可恢复性门禁并另行获得生产执行授权
- 更新时间：2026-08-23
- 数据集：`stk_mins`
- 物理父表：`raw_tushare.stk_mins`
- 服务入口：`core_serving.equity_minute_bar`
- P0 目标：将 2026-01～2026-06 已关闭月份的 6 个叶分区和 6 个物理主键索引从 `pg_default` 迁至 `gs_raw_cold_hdd`

权威边界：当前代码、PostgreSQL 16 官方语义、生产 catalog 和同一时点只读运行证据决定现状。本文固定 P0 执行契约和后续滚动规则，但不构成暂停任务、执行 DDL、修改排程或创建备份的授权。2026-04-27 的空表 drop/recreate 方案已经完成其历史使命，禁止再次用于当前非空生产表。

---

## 1. 第二轮安全复审结论

### 1.1 总结

`ALTER TABLE/INDEX ... SET TABLESPACE` 仍是本目标下最短、最少改动的正确路径；无需改 ORM、Definition、writer、DAO、API 或前端，也不需要新 Alembic migration。

但当前不能直接进入生产迁移，原因如下：

1. **可恢复性证据尚未闭环。** 生产主机安装了 `pg_basebackup@.service/.timer` 模板，但没有启用实例、没有运行中的 base backup，也未在 `/var/backups` 发现 PostgreSQL 备份；`archive_mode=off`，因此本机没有可见的 PITR 链。外部云盘快照或异地备份是否存在，当前只读审计无法证明。在确认一个可恢复、覆盖 PGDATA 和全部 tablespace 的独立备份前，P0 必须保持 No-Go。
2. **当前不是维护窗口。** 审计时有运行和排队中的普通 TaskRun，并存在超过 1 小时的数据库事务；`stk_mins` 自动任务 `stk_mins.maintain` 仍为 active，对应 `ops.probe_rule` 也仍为 active。它们不是方案缺陷，但说明不能沿用当前状态直接执行。
3. **原验收方式过重。** 六个月迁移前后各做一次全量 `count(*)` 会额外扫描约 2.63 亿行，并污染缓存、增加根盘和 HDD I/O；行数相同也不能证明字段内容完全相同。P0 改为依赖 PostgreSQL 单关系事务原子性，并用 OID、main fork 原始字节、tablespace、filepath、索引有效性和确定性索引样本做前后对账。全量逻辑扫描不再是迁移门禁。
4. **运行隔离必须落到真实执行车道。** `stk_mins` 已有独立的 `goldenshare-ops-stk-mins-worker.service`，通用 worker 不会领取该数据集。正式维护窗口应先通过 Ops 暂停 schedule、确认 probe rule 已删除、等待开放任务清零，再停止分钟线专用 worker；为避免其它大任务争用根盘/WAL/I/O，还应临时停止 scheduler、通用 worker 和 index-mins worker。Web/API 保持在线。
5. **迁移没有原生百分比进度。** PostgreSQL 16 的 progress views 不覆盖 `ALTER ... SET TABLESPACE`。执行时只能通过独立观察会话监控后台 PID、运行时长、等待事件、WAL LSN、`pg_wal` 和两个文件系统水位；页面或 SQL 不得伪造“已完成百分比”。

除可恢复性门禁外，没有发现新的代码或表结构阻塞项。备份证据闭环、维护窗口清空且本次生产授权明确包含服务暂停和紧急 `pg_cancel_backend` 后，才可进入 P0。

### 1.2 复审依据

1. CodeGraph 已核验 `RawStkMins` 的当前调用方、DAO 注册和测试；当前直接 raw ORM 业务消费者为成交额快照物化服务，它按目标交易日半开区间和频率查询，主要访问近期分区。
2. PostgreSQL 16 官方契约确认：单表 `SET TABLESPACE` 移动表数据文件但不移动索引；索引必须单独移动；相关 `ALTER TABLE/INDEX` 默认取得 `ACCESS EXCLUSIVE` 锁。
3. 当前 `wal_level=replica`。官方文档只对 `wal_level=minimal` 承诺 relation rewrite 的最小 WAL 优化，因此本机迁移必须按 WAL 密集操作规划，不能把 `max_wal_size=1GB` 当作硬上限。
4. 同一生产实例曾在 2026-06-01 将约 32 GiB 的 `cyq_chips` heap 和索引迁入相同 HDD tablespace，实际耗时约 6 分钟。该记录只能证明路径可行，不能作为本次 12 个关系的 SLA；本次真实速度和 WAL 峰值必须由 2026-02 先导批次重新测量。

## 2. 当前事实

### 2.1 代码与业务契约

1. `RawStkMins` 当前只有 `ts_code/freq/trade_time/open/close/high/low/vol/amount` 九列。
2. 主键为 `(ts_code, freq, trade_time)`；`vol` 为 `BIGINT`。
3. `freq` 在请求和任务输入中使用 `1min/5min/15min/30min/60min`，由 `_stk_mins_row_transform` 归一化为 `1/5/15/30/60` 后写入。
4. `DatasetDefinition` 为 `raw_only_upsert`，目标为 `raw_tushare.stk_mins`，观察字段为 `trade_time`，每个 planned unit 独立提交。
5. `core_serving.equity_minute_bar` 是普通 view，`trade_date` 由 `trade_time::date` 派生，不复制业务数据。
6. 成交额快照物化服务直接查询 `RawStkMins`，使用目标交易日半开区间和频率过滤。迁移不改变其 SQL 契约；2026-07、2026-08 两个热月继续留在 SSD。
7. 专用 worker 只领取 `task_type=dataset_action AND resource_key=stk_mins`；通用 worker 和 `index_mins` worker 不会越权领取该任务。

代码证据：

- `src/foundation/models/raw/raw_stk_mins.py`
- `src/foundation/ingestion/row_transforms.py::_stk_mins_row_transform`
- `src/foundation/datasets/definitions/market_equity.py` 中 `stk_mins` Definition
- `src/biz/services/wealth/market/turnover/turnover_snapshot_materialize_service.py`
- `src/ops/runtime/worker_lane.py`
- `src/app/runtime/ops_worker_factory.py`
- `scripts/goldenshare-ops-stk-mins-worker.service`
- `alembic/versions/20260427_000080_slim_stk_mins_storage.py`
- `alembic/versions/20260427_000081_widen_stk_mins_vol_to_bigint.py`

### 2.2 2026-08-23 生产物理快照

| 项目 | 当前事实 |
| --- | --- |
| PostgreSQL | 16.13，`fsync=on`、`synchronous_commit=on`、`full_page_writes=on`、`data_checksums=off` |
| 父表 | `raw_tushare.stk_mins`，按 `trade_time` 月分区 |
| 叶分区 | 2010-01～2036-12 加 default，共 325 个 |
| 2025 及以前 | 192 个月分区位于 `gs_raw_cold_hdd`；当前实际数据接近空，不是本次释放来源 |
| 2026 | 1～8 月承载数据并位于 `pg_default`；9～12 月及 default 为空或接近空 |
| 估算行数 | 约 263,462,994 行，主要集中于 2026-01～08 |
| P0 物理对象 | 每月 1 个 heap + 1 个物理主键索引，共 12 个；六个月 `reltoastrelid=0`，当前没有 TOAST relation |
| 约束 | 父表和六个目标叶分区仅有主键约束，无外键、用户 trigger、RLS policy 或 publication |
| 直接数据库依赖 | `core_serving.equity_minute_bar` 普通 view |
| HDD tablespace | `gs_raw_cold_hdd`，owner 为 `postgres`，路径 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`；应用角色拥有 `CREATE` 权限 |
| 根盘 | `/dev/vda2` 挂载 `/`，可用约 5.5 GiB，使用率 98%，inode 充足 |
| HDD | `/dev/vdb` 挂载 `/data/disk`，可用约 316 GiB，使用率 16%，inode 充足；UUID fstab 校验通过 |
| WAL | 位于根盘；审计时 `pg_wal` 约 240 MiB，`wal_level=replica`、`archive_mode=off`、无 replication slot、`max_wal_size=1GB`、`checkpoint_timeout=5min`、`wal_compression=off` |
| 备份 | 仅发现未启用的系统 `pg_basebackup` 模板；没有主机可见的 PostgreSQL base backup/PITR 运行证据；外部备份状态未知 |
| 介质边界 | 虚拟机内 `/dev/vda`、`/dev/vdb` 均报告 `ROTA=1`，不能据此证明云底层物理介质；本文沿用运营上的“根盘 SSD、`/data/disk` HDD”称呼 |

2026 月分区关系大小：

| 月份 | heap | 主键索引 | 合计 | P0 处理 |
| --- | ---: | ---: | ---: | --- |
| 2026-01 | 2,966,855,680 B | 2,480,381,952 B | 5,448,073,216 B | 迁 HDD |
| 2026-02 | 2,080,423,936 B | 1,717,166,080 B | 3,798,179,840 B | 迁 HDD，先导批次 |
| 2026-03 | 3,293,978,624 B | 2,092,998,656 B | 5,387,894,784 B | 迁 HDD |
| 2026-04 | 3,150,528,512 B | 2,134,581,248 B | 5,285,986,304 B | 迁 HDD |
| 2026-05 | 2,696,372,224 B | 2,140,536,832 B | 4,837,662,720 B | 迁 HDD |
| 2026-06 | 3,156,983,808 B | 2,425,012,224 B | 5,582,880,768 B | 迁 HDD |
| 2026-07 | 3,448,913,920 B | 2,697,879,552 B | 6,147,768,320 B | 保留 SSD |
| 2026-08 | 2,254,086,144 B | 1,722,646,528 B | 3,977,371,648 B | 保留 SSD |

P0 六个月合计 30,340,677,632 bytes，约 28.3 GiB。执行时必须重新读取原始字节，不能只使用本表或 `pg_size_pretty` 的格式化值。

### 2.3 当前任务快照与正确判断方式

1. 2026-08-23 审计时有普通 TaskRun 运行/排队，并存在长事务，因此当前时点不满足维护门禁。
2. `stk_mins.maintain` schedule 当前为 active，`trigger_mode=probe`；其 `next_run_at` 为历史值，但对应 active probe rule 仍在持续探测并创建 `stk_mins` TaskRun。
3. 因此不能用 `next_run_at` 是否过期判断 probe 是否停止。暂停成功必须同时证明：schedule 为 `paused`、该 schedule 对应的 `ops.probe_rule` 数量为 0、没有开放 `stk_mins` TaskRun。
4. 最近的 `stk_mins` 任务集中在当前交易日；旧月仍允许人工补录，所以“月份关闭”不是禁止写入。迁移后补录会正常写入 HDD 叶分区。

### 2.4 已纠正的旧结论

| 旧结论 | 当前纠正 |
| --- | --- |
| 生产表为空，可以 drop/recreate | 当前约 2.63 亿行，禁止 drop、truncate、recreate 或复制切换 |
| `vol` 为 `INTEGER` | 当前为 `BIGINT` |
| HDD tablespace 为 `gs_stk_mins_hdd` | catalog 名称为 `gs_raw_cold_hdd`；旧名称只存在于历史迁移和物理目录名 |
| 2026 及以后全部留 SSD | 已被容量证明不可持续；改为两个月滚动热窗口 |
| 每年 rollover 一次 | 改为每月评估并迁移 `M-2` 关闭月份；不自动执行 DDL |
| 六个月有多组物理索引 | 当前每个目标叶分区只有 1 个物理主键索引；仍须执行时从 `pg_index` 重新枚举 |
| 必须全量 `count(*)` 才能证明搬迁完整 | `SET TABLESPACE` 是单关系事务文件搬迁；全量计数扫描成本高且证明力有限，改用物理原始字节 + catalog + 确定性索引样本对账 |
| 暂停 schedule 即可隔离写入 | probe schedule 还必须验证 probe rule 删除；正式窗口还要停止独立 `stk_mins` worker，并阻止其它 worker/scheduler 制造 I/O 竞争 |

## 3. 目标存储规则

### 3.1 逻辑结构保持不变

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

P0 不修改表结构、分区边界、约束或 view。

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
| 当前月 `M` | `pg_default` |
| 上一个月 `M-1` | `pg_default` |
| `M-2` 及以前关闭月份 | `gs_raw_cold_hdd` |
| `stk_mins_default` | `pg_default`，不得长期承载历史数据 |

规则：

1. “关闭月份”只表示自然月已结束，不表示源端永不修订；后续补录允许写入 HDD。
2. 一个自然月是最小业务批次。当前每月对象为 1 个 heap 和 1 个主键索引，最终必须同处 HDD。
3. 当前六个月没有 TOAST；执行时若任一目标叶分区出现非零 `reltoastrelid`，说明 schema/数据特征已漂移，必须停止并重新评审，不能沿用当前 12 对象白名单。
4. 父级 partitioned relation 和父级 partitioned index 不承载目标数据块，不移动。
5. 当前预创建分区覆盖到 2036 年。未来分区治理必须按创建时热窗口选择 tablespace，不能继续硬编码“年份 <= 2025”。
6. 历史 migration 在 tablespace 不存在时会回退默认盘；这是后续 bootstrap 治理缺口，不修改已应用 revision。本项不阻塞 P0，但未来新环境必须 fail-closed。

## 4. P0 边界

### 4.1 唯一白名单

```text
raw_tushare.stk_mins_2026_01 ... raw_tushare.stk_mins_2026_06
以及执行时通过 pg_index 关联上述六个叶分区枚举出的全部物理索引
```

当前预期为 6 个 heap + 6 个主键索引，共 12 个对象。对象数、OID、边界或索引数与预期不一致即停止。

### 4.2 明确禁止

1. 不处理 2026-07、2026-08、default、父表、父级 partitioned index 或其它数据集。
2. 不执行 `DROP/TRUNCATE/DELETE/CREATE TABLE AS/INSERT ... SELECT/REINDEX/VACUUM FULL`。
3. 不使用 `ALTER ... ALL IN TABLESPACE`。
4. 不手工移动 tablespace 目录文件，不移动 WAL，不改 PostgreSQL 全局配置。
5. 不发起 Tushare 请求，不用源端重拉代替物理验收。
6. 不把六个月或一个月对象放在同一个长事务中。
7. 不自动终止业务会话，不使用 `pg_terminate_backend`。
8. 不因本次迁移新增自动 rollover schedule。

## 5. PostgreSQL 执行语义

1. `ALTER TABLE <leaf> SET TABLESPACE ...` 移动该叶表的数据文件；不会移动它的索引。
2. `ALTER INDEX <leaf-index> SET TABLESPACE ...` 单独移动索引文件。
3. 两类命令默认使用 `ACCESS EXCLUSIVE` 锁。`lock_timeout=15s` 只能限制“等待取得锁”的时间；一旦 DDL 取得锁，随后访问该关系的新查询仍可能排队到 DDL 完成。因此必须选择低峰维护窗口，不能把 15 秒误解为最多阻塞 15 秒。
4. 每条 DDL 是一个独立事务。提交前源 relation 保持有效；命令报错、连接中断或 statement timeout 会回滚当前对象，不影响已完成的其它对象。
5. 当前 `wal_level=replica`，迁移会产生 WAL；`max_wal_size` 是 checkpoint 目标，不是 WAL 目录硬上限。根盘水位必须实时观测。
6. PostgreSQL 16 没有 `SET TABLESPACE` 的原生进度百分比。只能观察后台 PID、query age、wait event、LSN 和文件系统水位。
7. tablespace 是整个 PostgreSQL cluster 的组成部分，不能把 HDD 目录单独挂到另一套 cluster，也不能只备份该目录。可恢复性必须覆盖 PGDATA、tablespace 和所需 WAL。
8. tablespace owner 是 `postgres`。应用角色可以移动自己拥有的表和索引，但不能修改 tablespace comment；comment 更新必须由 `postgres` 单独执行和验收。

## 6. Go/No-Go 门禁

以下全部为 Go 才能开始第一条 DDL；任何一项为 No-Go 都必须停止。

| 门禁 | Go 标准 | 当前状态 |
| --- | --- | --- |
| 授权 | 明确授权 12 个关系、服务暂停、DDL 及紧急 `pg_cancel_backend`；不包含其它表 | 未授权执行 |
| 可恢复性 | 有迁移前完成、异地或独立故障域、覆盖 PGDATA + 全部 tablespace 的成功备份；记录 backup ID、完成时间、范围、校验和恢复验证 | **No-Go：本机未发现有效证据，外部状态未知** |
| 挂载 | `/data/disk` 的 source/UUID/fstype 与 fstab 一致，tablespace symlink 指向真实挂载 | 当前只读检查通过，执行时重验 |
| 容量 | HDD 剩余不少于待迁剩余字节 120% 且不少于 64 GiB；根盘满足第 7.2 节逐关系门禁 | 当前估算通过，执行时重验 |
| 对象 | 6 个目标叶、6 个物理索引、无 TOAST；OID、边界、owner、位置与白名单一致 | 当前通过，执行时重验 |
| 数据库依赖 | 无新增 trigger/FK/RLS/publication；唯一已知 view 仍为 `core_serving.equity_minute_bar` | 当前通过，执行时重验 |
| 任务隔离 | schedule paused、probe rule=0、开放 TaskRun=0；指定 worker/scheduler 已停止 | 当前不通过 |
| 会话与锁 | 无超过 30 秒非 idle 事务、无目标关系锁、无 base backup、无其它大维护 | 当前不通过 |
| 持久性配置 | `fsync=on`、`synchronous_commit=on`；不得为加速临时关闭 | 当前通过，执行时重验 |
| 观察会话 | 已准备独立 observer，能记录 PID、LSN、WAL、根盘/HDD 每 5 秒水位 | 待执行窗口准备 |

### 6.1 可接受的备份证据

推荐顺序：

1. **首选：异地 `pg_basebackup` 或等价物理备份。** 必须包含主数据目录和所有 tablespace，并包含恢复所需 WAL；备份结束时间晚于最后一次目标表写入。至少在隔离环境完成目录结构、tablespace 映射和 PostgreSQL 启动验证。
2. **次选：云厂商应用一致性的多磁盘快照。** 必须在同一一致性点覆盖 `/dev/vda2` 和 `/dev/vdb`；单独快照根盘或 HDD 都不合格。需要有可验证的 snapshot ID、完成状态和恢复演练记录。
3. **逻辑备份只能作为补充。** 若使用 `pg_dump`，必须明确包含 `raw_tushare.stk_mins`，输出不能放在根盘或同一 `/data/disk` 故障域，并需证明可在隔离库恢复主键和样本数据。由于数据量约 2.63 亿行，不推荐把它作为本次最短前置路径。

系统自带但未启用的 `pg_basebackup@.timer`、同机 `/var/backups` 目录、Tushare 可重拉能力都不能作为备份证据。

## 7. P0 详细执行步骤

### P0-0：版本、授权与记录载体冻结

1. 冻结远程 Git revision、Alembic head、PostgreSQL 启动时间、审计时间和执行人。
2. 建立逐对象执行记录，至少包含：月份、对象类型、schema/name/OID、分区边界、index parent/constraint、迁移前 tablespace/filepath/main bytes、开始/结束时间、后台 PID、起止 LSN、WAL 增量、根盘/HDD 峰值、结果和异常。
3. 确认授权只覆盖 P0；备份、暂停排程、停止服务和紧急取消应分别留有操作记录。
4. 若代码、表结构、分区或索引在 2026-08-23 后变化，停止并重新做 CodeGraph 与 catalog 审计。

### P0-1：冻结恢复方式

1. 在暂停任何任务前，先确定采用第 6.1 节哪一种恢复方式、异地目标容量、执行人、恢复入口和预计 RTO。
2. 核验该方式能够同时覆盖 root PGDATA、当前已存在的 `gs_raw_cold_hdd` tablespace 和恢复所需 WAL；不能等到目标写入已冻结后才临时寻找备份位置。
3. 取得该备份方式最近一次成功恢复演练或至少隔离启动验证的证据。只有“有备份文件”、没有验证恢复结构，不算 Go。
4. 本步骤只冻结方法和恢复能力；本次迁移的最终 recovery point 必须在 P0-3 冻结 `stk_mins` 写入后创建，不能用仍可能有后续写入的旧备份冒充本次迁移备份。

### P0-2：挂载、容量与 WAL 预检

1. 用 `findmnt`、fstab UUID、`pg_tablespace_location()` 和 `pg_tblspc/31284` symlink 四重核验 `/data/disk`。
2. 核验目录 owner/mode，应用角色仍拥有目标 tablespace `CREATE` 权限。
3. HDD 可用空间必须同时满足：大于剩余目标原始字节的 120%，且不低于 64 GiB。
4. 根盘开始 P0 时不得低于 4 GiB。每个关系开始前还必须满足：`root_free >= current_relation_main_bytes + 2 GiB`。这是为 `wal_level=replica` 下未知 WAL 峰值设置的保守门禁，不表示 PostgreSQL 会在 root 再复制一份 relation。
5. 记录 `pg_wal` 字节、当前 LSN、`pg_stat_wal`、checkpoint 配置、replication slot、basebackup 进度和两个文件系统水位。
6. `fsync` 或 `synchronous_commit` 不是 `on`、HDD 变为只读、inode 异常或 kernel 出现新 I/O/ext4 错误时立即 No-Go。

### P0-3：建立真正的任务与写入隔离

按顺序执行，不能跳步：

1. 通过 Ops API/UI 暂停 `target_key=stk_mins.maintain` 的自动任务；禁止直接更新 `ops.schedule`。
2. 只读验证 schedule 为 `paused`，且该 schedule 对应的 `ops.probe_rule` 已被删除。`next_run_at` 不作为暂停证据。
3. 等待 `stk_mins` 的 `queued/running/canceling` TaskRun 清零，然后停止 `goldenshare-ops-stk-mins-worker.service`。通用 worker 不会领取该数据集，停止后即形成目标表写入冻结。
4. 在目标写入已冻结的状态下创建本次迁移的最终 recovery point；验证 backup/snapshot 完成时间晚于最后一次 `stk_mins` 成功 TaskRun，且早于第一条 DDL。再次确认其覆盖 PGDATA、全部 tablespace 和所需 WAL，并记录 backup/snapshot ID。
5. 等待所有其它 `queued/running/canceling` TaskRun 清零，并确认没有日期完整性、回补、迁移或大规模分页任务。
6. 停止 `goldenshare-ops-scheduler.service`，防止维护窗口产生新自动任务。
7. 停止 `goldenshare-ops-worker.service` 和 `goldenshare-ops-index-mins-worker.service`，防止普通或指数分钟线任务争用 PostgreSQL/WAL/I/O。Web/API 和 PostgreSQL 保持在线。
8. 再次查询 TaskRun。若维护窗口中有人提交手工任务，即使 worker 已停、任务只会 queued，也必须暂停 P0 并先协调处理。
9. 核验目标关系无锁；数据库不存在超过 30 秒的非 idle 事务或大查询。不能终止现有会话来强行获得维护窗口。

停止服务前必须先等当前任务自然结束。禁止通过 stop 服务中断正在提交业务事务。

### P0-4：生成不可变白名单和基线

1. 从 `pg_inherits/pg_class/pg_index/pg_constraint` 动态生成 12 个对象白名单；禁止按名称猜索引。
2. 记录六个叶分区的 OID、边界、owner、tablespace、`pg_relation_filepath()`、main fork 原始字节、`reltoastrelid`。
3. 记录六个索引的 OID、parent index、constraint、tablespace、filepath、main fork 字节、`indisprimary/indisunique/indisvalid/indisready`。
4. 同时记录 2026-07、2026-08、default 和父级逻辑对象的位置，作为负向白名单基线。
5. 为每个月从主键索引首端和末端各选 1 个 `(ts_code,freq)` 组合；对这 2 个组合记录：行数、最早/最晚 `trade_time`、按主键顺序串联九个字段所得的确定性摘要，以及 raw/view 相同过滤条件下的代表性结果。
6. 不执行六个月全量 `count(*)`、全表 hash 或全表 min/max。它们会制造大量额外扫描，却不能增强文件搬迁事务本身的原子性证明。

基线输出只能写到本地审计记录或独立安全位置，不能写入生产业务表、root 临时大文件或 `/data/disk` tablespace 目录。

### P0-5：启动独立 observer

在第一条 DDL 前启动独立观察会话，每 5 秒记录：

1. `/` 和 `/data/disk` 可用字节、使用率和 inode。
2. `/var/lib/postgresql/16/main/pg_wal` 当前字节。
3. `pg_stat_activity` 中 `application_name LIKE 'stk_mins_ts_%'` 的 PID、query age、state、wait event。
4. 当前 WAL LSN；每个对象完成后用 `pg_wal_lsn_diff(end_lsn,start_lsn)` 记录实际 WAL 量。
5. PostgreSQL 和 Web 健康；worker/scheduler 必须保持预期 stopped 状态。

PostgreSQL 不提供本命令的真实百分比，observer 只报告“等待锁/正在执行/已提交/已回滚”和客观水位。

紧急停止条件：

1. 根盘可用空间低于 3 GiB且仍在下降。
2. HDD 可用空间低于 64 GiB、挂载消失、文件系统只读或出现新 I/O 错误。
3. PostgreSQL 报错、Web 健康失败、DDL 超过 60 分钟、出现未预期 TaskRun/锁或白名单漂移。

若触发，使用事先授权的 `pg_cancel_backend(<本次 migration pid>)` 取消当前 DDL；禁止 `pg_terminate_backend`。等待当前事务完成回滚、磁盘水位稳定后停止本轮，不自动重试。

### P0-6：2026-02 先导批次

2026-02 是最小完整月。对象顺序固定为：

1. `stk_mins_2026_02_pkey`，约 1.60 GiB。
2. `stk_mins_2026_02` heap，约 1.94 GiB。

每个对象使用独立连接、独立事务。示意：

```bash
PGAPPNAME=stk_mins_ts_202602_pkey \
bash scripts/psql-remote.sh -c "
BEGIN;
SET LOCAL lock_timeout = '15s';
SET LOCAL statement_timeout = '60min';
ALTER INDEX raw_tushare.stk_mins_2026_02_pkey
  SET TABLESPACE gs_raw_cold_hdd;
COMMIT;"
```

```bash
PGAPPNAME=stk_mins_ts_202602_heap \
bash scripts/psql-remote.sh -c "
BEGIN;
SET LOCAL lock_timeout = '15s';
SET LOCAL statement_timeout = '60min';
ALTER TABLE raw_tushare.stk_mins_2026_02
  SET TABLESPACE gs_raw_cold_hdd;
COMMIT;"
```

每个对象提交后必须先完成：

1. OID 与迁移前相同；tablespace 为 `gs_raw_cold_hdd`；filepath 转入 `pg_tblspc/31284/...`。
2. main fork 原始字节与迁移前完全一致。
3. 索引仍 `indisvalid=true/indisready=true`，constraint 和 parent index 关系不变。
4. 确定性索引样本摘要与 raw/view 结果一致。
5. 记录真实耗时、WAL LSN 增量、root/HDD 最低/最高水位和锁等待。

两个对象都通过后，停止至少 5 分钟观察 checkpoint、WAL 回落和服务健康。只有先导批次闭环且根盘/HDD门禁仍满足，才允许继续。先导数据只允许收紧后续门禁；不得未经复审放宽 4 GiB/3 GiB/64 GiB 阈值。

### P0-7：其余月份串行迁移

按总大小从小到大：

```text
2026-05 -> 2026-04 -> 2026-03 -> 2026-01 -> 2026-06
```

每月均先移动当前唯一物理主键索引，再移动 heap。每个关系重复 P0-2、P0-4、P0-5 和 P0-6 的对象级门禁与验收；一个月未完整闭环，不得开始下一个月，不得并行 DDL。

若执行时某月出现新增索引或 TOAST，该月及后续月份立即停止并重新评审；不能把新增对象自动加入已授权白名单。

### P0-8：最终验收

必须同时满足：

1. 2026-01～06 的 6 个 heap 和执行时枚举的 6 个物理索引均位于 `gs_raw_cold_hdd`，main fork 字节分别与迁移前一致。
2. 六个表/索引 OID、分区边界、主键约束、index parent、有效性不变。
3. 2026-07、2026-08、default、父表和父级 partitioned index 仍位于原位置；白名单外对象无变化。
4. 每月确定性样本、raw 表和 `core_serving.equity_minute_bar` 结果与迁移前一致。
5. 当前热月成交额快照代表性只读查询可用；不为了迁移验收触发业务写入或 Tushare 请求。
6. SSD 释放量与 30,340,677,632 bytes 量级相符，HDD 增量相符；差异按 WAL、并发系统写入和文件系统保留空间解释，不能只看单次 `df`。
7. PostgreSQL/Web 正常；observer 没有记录 I/O、只读文件系统或数据页错误。
8. 使用 `postgres` 权限单独修正 tablespace 遗留 comment，并再次读取验证：

   ```sql
   COMMENT ON TABLESPACE gs_raw_cold_hdd IS
     'Goldenshare PostgreSQL cold-storage tablespace on /data/disk; dataset placement follows each current LLD; stk_mins keeps current and previous calendar months on pg_default';
   ```

comment 更新失败不回滚已完成的数据 relation；记录为独立元数据故障并修复，不能冒充应用角色有权限执行。

### P0-9：恢复服务和排程

1. 先检查维护窗口内是否产生新的 queued TaskRun。存在则保持 worker stopped，逐项确认，不自动消费。
2. 依次启动通用 worker、index-mins worker、stk-mins worker，确认各服务 active 且没有错误循环。
3. 启动 scheduler。
4. 通过 Ops API/UI 恢复 `stk_mins.maintain` schedule；验证 schedule active 且只重建 1 条 active probe rule。
5. 观察下一次正常 probe/TaskRun。它应只写当前热月；本步骤不授权人工创建一次额外同步，也不重复请求 Tushare。
6. 将实际对象清单、耗时、WAL、磁盘水位和验收结果回写本文与存储治理总文档。

## 8. 失败、部分完成与恢复

1. **锁超时。** 当前单对象事务回滚；停止本轮，不主动清理 relation 文件，不自动重试。
2. **statement timeout/紧急取消。** 等待 PostgreSQL 完成回滚并确认源对象仍在原 tablespace、OID/字节/索引有效性正常；空间稳定前不继续。
3. **一个月中间态。** 若索引已在 HDD、heap 仍在 SSD，保留已成功对象并记录；修复门禁后从未完成对象继续。不得为了整齐自动回迁。
4. **前月已完成、后月失败。** 已验收月份保留，未开始月份不动；不把六个月当成一个原子批次。
5. **逻辑/物理验收不一致。** 立即停止，保持 worker/scheduler stopped，升级数据库故障审计；禁止删除、重建、重拉或手工拷贝数据文件。
6. **性能不可接受。** 先记录具体查询、参数、时间范围和前后延迟。只有 HDD 健康且 root 有足够目标关系大小和 WAL 余量时，才能另行授权逐对象回迁 `pg_default`。
7. **HDD 丢失或 tablespace 不可访问。** 这不是 `SET TABLESPACE pg_default` 能解决的普通回滚。停止 PostgreSQL，按已验证备份恢复整个 cluster 和 tablespace；禁止把 tablespace 目录单独接到另一 cluster。
8. **任务恢复异常。** 业务 relation 已提交不因 Ops 状态失败回滚；保持相关 worker/schedule paused，单独修复任务链路。

## 9. 后续滚动治理

1. 进入新月份 `M` 后，唯一新增候选是 `M-2`。例如进入 2026-09 后，候选为 2026-07；2026-08 和 2026-09 留 SSD。
2. 前两次月度 rollover 继续人工执行，复用本方案的备份、任务隔离、WAL、对象白名单和验收门禁。
3. 每次只迁 1 个月，单关系串行；不把物理 DDL放入 DatasetDefinition、worker、普通 schedule 或部署 Alembic。
4. 若以后建设存储治理命令，默认只能只读生成计划；显式 execute 才能按白名单逐关系运行，并必须带任务、挂载、备份、容量、锁、WAL和断点记录。该建设属于独立开发范围。
5. 根盘达到 90% 预警，95% 停止新的大规模回补并启动 Top 20 审计；不再等到 98% 才处理。
6. 后续新增分区必须在目标 tablespace 缺失时 fail-closed，禁止静默回退默认盘。

## 10. 风险矩阵

| 风险 | 等级 | 防护 |
| --- | --- | --- |
| 无可验证备份，HDD 故障导致 cluster 不可恢复 | **阻塞** | 异地物理备份或一致性多盘快照，覆盖 PGDATA + 全部 tablespace，并做恢复验证 |
| 根盘仅剩约 5.5 GiB，WAL 瞬时增长 | 很高 | 逐关系空间门禁、最小索引先导、5秒 observer、3 GiB紧急取消阈值、每对象提交 |
| `ACCESS EXCLUSIVE` 阻塞历史读取或写入 | 高 | 低峰窗口、暂停 probe、停止执行车道、15秒取锁超时、单对象串行 |
| 误以为 lock timeout 限制整个阻塞时长 | 高 | 明确它只限制取锁；DDL执行期依靠维护窗口和60分钟 statement timeout |
| 没有原生迁移百分比 | 中 | 只报告 PID/状态/时长/水位，不伪造百分比 |
| schedule paused 但 probe 仍活跃 | 高 | 通过正式 Ops pause 删除绑定 rule，并同时验证 schedule + probe_rule |
| 只迁 heap 或遗漏索引 | 高 | 从 `pg_index` 枚举；当前预期每月恰好1个；对象数漂移即停止 |
| 新增 TOAST/索引导致白名单失效 | 高 | 执行时动态核验，任何漂移重新授权 |
| 全量验收扫描反而造成 I/O 风险 | 中高 | 不做全表 count/hash；用事务原子性、main fork字节、OID、filepath、索引状态和确定性样本 |
| HDD 未真实挂载或变为只读 | 很高 | findmnt/fstab/symlink 四重核验，kernel日志与文件系统状态门禁 |
| 部分对象已迁、批次中断 | 中 | 接受可恢复中间态，逐对象记录，从断点继续，不自动回迁 |
| 历史查询延迟升高 | 中 | 仅迁关闭月份；记录代表性查询，性能回迁需另授权 |
| tablespace comment 用应用角色执行失败 | 低 | 明确由 owner `postgres` 单独执行，失败不影响业务 relation |

## 11. 本轮不做

1. 不迁移 `index_mins`、技术因子、日线、资金流或 P1/P2/P3 表。
2. 不修改 `stk_mins` 请求、分页、对象池、并发、任务进度或 freshness。
3. 不新增、删除、重建分区或索引。
4. 不实现分钟级完整性审计。
5. 不迁移 WAL，不临时降低 `wal_level/fsync/synchronous_commit/full_page_writes`。
6. 不创建自动 tablespace rollover schedule。
7. 本轮文档复审不执行备份、暂停服务、修改 schedule、生产 DDL 或任何业务写入。

## 12. 相关文档

1. [生产 PostgreSQL 存储空间优化治理专项 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v1.md)
2. [股票历史分钟行情 tablespace 冷热分层执行记录 v1（2026-04-26 历史快照）](/Users/congming/github/goldenshare/docs/ops/stk-mins-tablespace-layout-v1.md)
3. [分钟线数据集独立执行车道 LLD v1](/Users/congming/github/goldenshare/docs/ops/ops-minute-datasets-dedicated-worker-execution-lane-lld-v1.md)
4. [股票历史分钟行情数据集开发说明](/Users/congming/github/goldenshare/docs/datasets/stk-mins-dataset-development.md)
5. [Prod 每日筹码分布 HDD Tablespace 迁移方案 v1（同实例历史执行证据）](/Users/congming/github/goldenshare/docs/ops/prod-cyq-chips-hdd-tablespace-migration-plan-v1.md)
6. [PostgreSQL 16 `ALTER TABLE`](https://www.postgresql.org/docs/16/sql-altertable.html)
7. [PostgreSQL 16 `ALTER INDEX`](https://www.postgresql.org/docs/16/sql-alterindex.html)
8. [PostgreSQL 16 Tablespaces](https://www.postgresql.org/docs/16/manage-ag-tablespaces.html)
9. [PostgreSQL 16 WAL settings](https://www.postgresql.org/docs/16/runtime-config-wal.html)
10. [PostgreSQL 16 `pg_basebackup`](https://www.postgresql.org/docs/16/app-pgbasebackup.html)
