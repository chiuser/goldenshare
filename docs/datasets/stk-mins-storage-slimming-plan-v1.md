# 股票历史分钟行情存储瘦身与滚动冷热治理方案 v1

- 版本：v1
- 状态：2026-10-02 P0 物理迁移与即时验收完成，1～6 月 12 个对象已在 HDD，四项服务已恢复；schedule #25 仍 paused，正式页面恢复及下一次自然运行观察待完成；7～8 月未迁移
- 更新时间：2026-10-02（容量复审 19:30～19:35；迁移/恢复证据至 20:17，Asia/Shanghai）
- 数据集：`stk_mins`
- 物理父表：`raw_tushare.stk_mins`
- 服务入口：`core_serving.equity_minute_bar`
- P0 目标：将 2026-01～2026-06 已关闭月份的 6 个叶分区和 6 个物理主键索引从 `pg_default` 迁至 `gs_raw_cold_hdd`

权威边界：当前代码、PostgreSQL 16 官方语义、生产 catalog 和同一时点只读运行证据决定现状。本文固定 P0 执行契约和后续滚动规则，但不构成暂停任务、执行 DDL、修改排程或创建备份的授权。2026-04-27 的空表 drop/recreate 方案已经完成其历史使命，禁止再次用于当前非空生产表。

§2.2～2.3 保留 2026-08-23 历史证据，容量复审见 §2.5，授权后的执行预检见 §2.6。P0 第一阶段仍只限 1～6 月十二个对象；7～8 月列为第二阶段候选，须单独确认执行范围。两个月热窗口是治理目标，不是已运行的自动滚动任务。管理员此前已接受无备份条件下的剩余风险，随后于 2026-10-02 授权按本方案推进 P0；该授权覆盖本方案对象、服务暂停/恢复及紧急取消，不自动扩围。

---

## 1. 2026-10-02 再评估结论

### 1.1 总结

`ALTER TABLE/INDEX ... SET TABLESPACE` 仍是本目标下最短、最少改动的正确路径；无需改 ORM、Definition、writer、DAO、API 或前端，也不需要新 Alembic migration。

本轮实际执行结果见 §2.8；以下仍是每次执行前必须核验的原则，不是重复执行已完成 P0 的授权：

1. **恢复风险没有消失，但不再把备份缺失列为绝对禁止条件。** 本次仍未发现主机可见的有效 PostgreSQL 备份，外部备份未知，WAL 归档关闭。按管理员已接受的风险口径准备；极端故障下不能承诺恢复，事务回滚不等于独立备份。
2. **容量改善不等于执行门禁通过。** 容量复审时开放 TaskRun 为 0，但 schedule/probe/worker/scheduler 尚未隔离；后续按 §2.8 完成冻结、执行和服务恢复。任何新窗口都须重新核验版本、权限、挂载健康、锁、负载与代表性查询基线。
3. **原验收方式过重。** 六个月迁移前后各做一次全量 `count(*)` 会额外扫描大量记录，并污染缓存、增加根盘和 HDD I/O；行数相同也不能证明字段内容完全相同。历史约 2.63 亿行是当时全表估算，不能误作六个月准确行数。P0 依赖 PostgreSQL 单关系事务原子性，并用 OID、main fork 原始字节、tablespace、filepath、索引有效性和确定性索引样本做前后对账。全量逻辑扫描不再是迁移门禁。
4. **运行隔离必须落到真实执行车道。** `stk_mins` 已有独立的 `goldenshare-ops-stk-mins-worker.service`，通用 worker 不会领取该数据集。正式维护窗口应先通过 Ops 暂停 schedule、确认 probe rule 已删除、等待开放任务清零，再停止分钟线专用 worker；为避免其它大任务争用根盘/WAL/I/O，还应临时停止 scheduler、通用 worker 和 index-mins worker。Web/API 保持在线。
5. **迁移没有原生百分比进度。** PostgreSQL 16 的 progress views 不覆盖 `ALTER ... SET TABLESPACE`。执行时只能通过独立观察会话监控后台 PID、运行时长、等待事件、WAL LSN、`pg_wal` 和两个文件系统水位；页面或 SQL 不得伪造“已完成百分比”。

未发现需要推翻物理迁移路径的证据。容量复审时根盘可用空间从历史约 5.5 GiB 增至 29.79 GiB，HDD 可用约 256.00 GiB。P0 已在独立授权、实时门禁和 2 月先导闭环后完成物理迁移；最终根盘可用约 57.71 GiB。已测吞吐和 WAL 峰值只代表本次维护窗口，不是其它月份或未来迁移的 SLA；排程恢复/自然运行待办仍需完成。

### 1.2 复审依据

1. 前轮 CodeGraph 复审记录了 `RawStkMins` 调用方、DAO 注册和测试，直接 raw ORM 业务消费者为成交额快照物化服务，按目标交易日半开区间和频率查询，主要访问近期分区。本轮 CodeGraph 与当前代码读取仅补充模型/存储合同核验，不宣称重做了全量消费者审计；生产执行前须补齐影响面复核。
2. PostgreSQL 16 官方契约确认：单表 `SET TABLESPACE` 移动表数据文件但不移动索引；索引必须单独移动；相关 `ALTER TABLE/INDEX` 默认取得 `ACCESS EXCLUSIVE` 锁。
3. 当前 `wal_level=replica`。官方文档只对 `wal_level=minimal` 承诺 relation rewrite 的最小 WAL 优化，因此本机迁移必须按 WAL 密集操作规划，不能把 `max_wal_size=1GB` 当作硬上限。
4. 同一生产实例曾在 2026-06-01 将约 32 GiB 的 `cyq_chips` heap 和索引迁入相同 HDD tablespace，实际耗时约 6 分钟。该记录只能证明路径可行，不能作为本次 12 个关系的 SLA；本次真实速度和 WAL 峰值必须由 2026-02 先导批次重新测量。

## 2. 代码合同与历史基线

### 2.1 代码与业务契约

1. `RawStkMins` 当前只有 `ts_code/freq/trade_time/open/close/high/low/vol/amount` 九列。
2. 主键为 `(ts_code, freq, trade_time)`；`vol` 为 `BIGINT`。
3. `freq` 在请求和任务输入中使用 `1min/5min/15min/30min/60min`，由 `_stk_mins_row_transform` 归一化为 `1/5/15/30/60` 后写入。
4. `DatasetDefinition` 为 `raw_only_upsert`，目标为 `raw_tushare.stk_mins`，观察字段为 `trade_time`，每个 planned unit 独立提交。
5. `core_serving.equity_minute_bar` 是普通 view，`trade_date` 由 `trade_time::date` 派生，不复制业务数据。
6. 成交额快照物化服务直接查询 `RawStkMins`，使用目标交易日半开区间和频率过滤。迁移不改变其 SQL 契约；按 2026-10 热窗口，9～10 月继续留 SSD，7～8 月暂不纳入 P0。读取入口透明不代表延迟透明：DDL 期间查询可能等待锁，历史查询迁 HDD 后可能变慢，须做前后性能验收。
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

| 项目 | 2026-08-23 事实 |
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

### 2.3 2026-08-23 任务快照与判断方式

1. 2026-08-23 审计时有普通 TaskRun 运行/排队，并存在长事务，因此当时不满足维护门禁。
2. 当时 `stk_mins.maintain` schedule 为 active，`trigger_mode=probe`；其 `next_run_at` 为历史值，但对应 active probe rule 仍在持续探测并创建 `stk_mins` TaskRun。最新字段状态见 §2.5，不沿用该残留字段结论。
3. 因此不能用 `next_run_at` 是否过期判断 probe 是否停止。暂停成功必须同时证明：schedule 为 `paused`、该 schedule 对应的 `ops.probe_rule` 数量为 0、没有开放 `stk_mins` TaskRun。
4. 最近的 `stk_mins` 任务集中在当前交易日；旧月仍允许人工补录，所以“月份关闭”不是禁止写入。迁移后补录会正常写入 HDD 叶分区。

### 2.4 已纠正的旧结论

| 旧结论 | 当前纠正 |
| --- | --- |
| 生产表为空，可以 drop/recreate | 已有大规模真实数据，禁止 drop、truncate、recreate 或复制切换；历史估算不能替代当前行数 |
| `vol` 为 `INTEGER` | 当前为 `BIGINT` |
| HDD tablespace 为 `gs_stk_mins_hdd` | catalog 名称为 `gs_raw_cold_hdd`；旧名称只存在于历史迁移和物理目录名 |
| 2026 及以后全部留 SSD | 已被容量证明不可持续；改为两个月滚动热窗口 |
| 每年 rollover 一次 | 改为每月评估并迁移 `M-2` 关闭月份；不自动执行 DDL |
| 六个月有多组物理索引 | 当前每个目标叶分区只有 1 个物理主键索引；仍须执行时从 `pg_index` 重新枚举 |
| 必须全量 `count(*)` 才能证明搬迁完整 | `SET TABLESPACE` 是单关系事务文件搬迁；全量计数扫描成本高且证明力有限，改用物理原始字节 + catalog + 确定性索引样本对账 |
| 暂停 schedule 即可隔离写入 | probe schedule 还必须验证 probe rule 删除；正式窗口还要停止独立 `stk_mins` worker，并阻止其它 worker/scheduler 制造 I/O 竞争 |

### 2.5 2026-10-02 最新只读证据与变化

核验窗口为 19:30～19:35（Asia/Shanghai），经现有 SSH 入口读取 PostgreSQL catalog、有限 TaskRun/schedule/probe 投影与主机状态。数据库查询使用只读事务及 20 秒超时；未全表扫描、未请求 Tushare、未执行备份/DDL/停服。下列事实只代表该窗口，不替代执行前预检。

| 项目 | 最新事实及边界 |
| --- | --- |
| 根盘 | 总容量 285,230,424,064 B，可用 31,985,737,728 B（29.79 GiB），使用率 89% |
| HDD | 总容量 422,549,692,416 B，可用 274,875,346,944 B（256.00 GiB），使用率 32%；`/dev/vdb`、ext4、rw |
| tablespace | `gs_raw_cold_hdd` 路径与 `pg_tblspc/31284` 软链接一致，指向 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`；owner 为 postgres；执行前仍须复核 fstab/UUID、应用权限、inode 和 kernel I/O 错误 |
| 分区 | 共 325 个叶分区；192 个旧月叶分区在 HDD，总关系大小约 1.5 MiB；133 个叶分区在默认盘，总关系大小 47,910,535,168 B |
| 2026 月份 | 1～9 月仍在默认盘承载数据；10～12 月及 default 无 heap 数据；1～9 月各 1 个 valid/ready 主键索引、无 TOAST |
| P0 | 1～6 月表和索引大小与历史记录一致，合计 30,340,677,632 B（28.26 GiB），尚未迁移 |
| WAL/持久性 | WAL 位于 SSD；51 个文件、855,638,016 B（816 MiB）；无 replication slot；archive_mode=off、wal_level=replica、max_wal_size=1GB、checkpoint_timeout=5min；fsync/synchronous_commit/full_page_writes=on，checksums=off |
| 任务 | queued/running/canceling TaskRun 查询结果为 0；最近分钟线 TaskRun #13953 成功，29,565/29,565 unit，2026-09-30 17:15:31～18:30:44 |
| 自动任务 | schedule #25 active、trigger_mode=probe、cron_expr/next_run_at 为空；probe rule #3 active，17:00～19:00；分钟线 worker 与 scheduler active，不能视为已隔离 |
| 会话 | 检查时未发现超过 30 秒的活动事务；未完成执行窗口目标锁验收 |
| 备份 | 活跃 timer 清单未发现 PostgreSQL 备份任务；`/var/backups` 抽查为系统包管理备份；未发现已验证独立 PostgreSQL 备份，外部状态未知，不能断言不存在所有外部备份 |
| 备份规模参考 | 主 PGDATA 目录占用约 162.41 GiB，不包含独立 tablespace；goldenshare 与 stockdb 的数据库大小合计约 272.28 GiB。这不是压缩备份大小，但 SSD 扩容不代表已具备独立整库备份条件 |
| 服务入口 | `core_serving.equity_minute_bar` 仍为 raw-backed view；Definition 仍为 raw_only_upsert；没有新增双份分钟线存储 |

新增月份大小（1～6 月继续使用 §2.2 相同字节基线）：

| 月份 | heap | 主键索引 | 合计 | 2026-10 处理口径 |
| --- | ---: | ---: | ---: | --- |
| 2026-07 | 3,448,913,920 B | 2,697,879,552 B | 6,147,768,320 B | 第二阶段候选，P0 不动 |
| 2026-08 | 3,188,244,480 B | 2,464,440,320 B | 5,653,577,728 B | 第二阶段候选，P0 不动 |
| 2026-09 | 3,293,282,304 B | 2,473,295,872 B | 5,767,495,680 B | 热月，留 SSD |
| 2026-10 | 0 B | 8,192 B | 8,192 B | 当前月，留 SSD |

1～8 月共 42,142,023,680 B（39.25 GiB）；7～8 月可追加释放 11,801,346,048 B（10.99 GiB）。均是关系大小，不保证 `df` 净释放量完全相等；WAL、并发写入和文件系统空间计量须分别解释。

本轮未重做全部消费者、数据库依赖和权限验收。当前 Definition 与历史 migration 已重新读取；历史 migration 仍按 `year <= 2025` 放置 HDD，并非自动滚动程序，不修改已应用 revision。执行前需确认远程版本与被审计版本一致并补齐完整对象/依赖基线。

### 2.6 2026-10-02 P0 授权后预检记录（尚未迁移）

管理员授权后于 19:43 起执行只读预检；未执行 schedule 写入、停服、DDL、备份或 Tushare 请求。当前停在 P0-3 的正式暂停入口：浏览器控制工具两次读取超时，未取得可用管理员登录会话完成 API/UI 暂停。禁止用直接 SQL、伪造管理员 token 或任意 actor ID 调用内部 service 绕过正式入口。后续由运营通过正式页面暂停 schedule #25，或恢复可用的已认证 API/UI 入口；再重新实时预检，不直接复用这次空队列状态。

| 检查 | 本轮结果与边界 |
| --- | --- |
| 版本 | 本地与远程 HEAD 均为 `1ceeef5d2a0763874fdd045378531251ff867d5c`；远程 Git 工作区无改动；生产 Alembic 为 `20261002_000182`；PostgreSQL 启动时间 2026-08-24 17:30:40+08 |
| 对象 | 6 个目标 heap + 6 个有效/ready 主键索引；无 TOAST；边界为 1～6 月准确自然月；owner 均为 goldenshare_user；目标当前都在默认盘，字节与 §2.2 一致 |
| OID 清单 | heap：01=33972、02=33977、03=33982、04=33987、05=33992、06=33997；对应索引：33975、33980、33985、33990、33995、34000；父表=32815 |
| 权限/依赖 | 应用 owner 有 gs_raw_cold_hdd CREATE 权限；父表/目标叶仅主键，无新增用户 trigger、RLS 或 publication；父表直接依赖 view 仅 core_serving.equity_minute_bar；索引父级关系保持存在 |
| 挂载/健康 | source 为 /dev/vdb，ext4、rw；UUID `cf9c2a7f-2811-424e-b6ac-b8c9717381bf` 与 fstab 一致；tablespace 软链接一致；根盘/HDD inode 使用率分别 5%/1%；最近 24 小时指定 I/O/ext4 错误模式未命中，不等于介质全面诊断通过 |
| 空间 | 19:43 根盘可用 32,043,302,912 B，HDD 可用 274,875,346,944 B；满足现有容量估算门禁 |
| 任务/锁 | 此次 queued/running/canceling=0，无目标锁，无超过 30 秒的活动事务、无 basebackup；schedule #25 与 probe rule #3 仍 active，尚未形成隔离窗口 |
| 即将到期排程 | 19:50 idx_factor_pro；19:55 stk_nineturn；20:00 起有 daily_moneyflow_maintenance、reference_data_refresh、新闻等多项排程。仅记录到期时间，不断言它们必定创建任务；不得在未完成隔离时抢时间开始搬迁 |
| 查询基线 | 000001.SZ、freq=1、2026-02-02 半开日窗口，241 行；使用 2 月主键 Index Scan；本次热缓存执行 0.154 ms、规划 3.944 ms，不能作为 HDD 冷读 SLA；Raw/view 双向 EXCEPT ALL 差异=0 |
| 尚需完成 | 正式暂停 #25 并验证 rule 删除；按方案冻结全部写入入口与服务，复核旁路/其它运行车道负载；冻结负向白名单及 raw/view/热月查询基线；启动独立 observer；隔离后重读以下样本，再执行 2 月先导 |

六个月首末主键组合的有限样本（未冻结写入，执行时须重取）：

| 月份 | 000001.SZ / freq=1：行数 / 九字段摘要 | 920992.BJ / freq=60：行数 / 九字段摘要 |
| --- | --- | --- |
| 01 | 4,820 / `84236b4d211a6ba9780c8cca098b9431` | 100 / `2b884a67e2ba505fbdfee6f2e308762f` |
| 02 | 3,374 / `f678e0e1bdc3a00e3da803aad2942bff` | 70 / `4a2140435ef1ac29a269ca9b5ee20436` |
| 03 | 5,302 / `bf4fdbb936c39d8b56d2f54e13d3af92` | 110 / `5044537ec59f337dad01e44ecfeb1137` |
| 04 | 5,061 / `35b75ac8ceec21ea634ef45700062cb7` | 105 / `f21ec393276a4027b0f830d022083ca1` |
| 05 | 4,338 / `3128a924d92786bdf439d83c50647f89` | 90 / `c5ecdc9baac7cabfb097c6ad1f36ef79` |
| 06 | 5,061 / `13b0ebdcbac79121d0c8cc02097ad63f` | 105 / `6a7cb37b2150c950adbf56708b3e4f37` |

摘要使用同一 SQL 会话格式，按 trade_time 排序，将九个 source 字段的 row 文本串联后计算 MD5；它是确定性样本对账，不是全表完整性证明。预检 SQL 保存于本机临时文件 `/private/tmp/stk_mins_p0_preflight_20261002.sql` 与 `/private/tmp/stk_mins_p0_samples_20261002.sql`，不把临时文件当作长期唯一证据，以上结果在本文留档。

### 2.7 2026-10-02 暂停确认后的维护窗口中止记录

1. 管理员通过正式 Ops 页面暂停股票分钟自动任务后，于 19:52:49 复验：schedule #25 为 paused、绑定 probe rule=0；开放 TaskRun=0，目标锁=0，无长活动事务；对象/权限/依赖仍符合 §2.6。
2. 四项原本 active 的服务按 P0-3 顺序停止：`goldenshare-ops-stk-mins-worker.service`、`goldenshare-ops-scheduler.service`、`goldenshare-ops-worker.service`、`goldenshare-ops-index-mins-worker.service`。确认均 inactive；Web、PostgreSQL 保持 active，Web 健康端点返回 ok。
3. 隔离后再次检查发现 TaskRun #14203：`dataset_action / stk_period_bar_week`，trigger_source=manual，requested_at=`2026-10-02 19:53:33.250141+08`，status=queued。这不是分钟线 probe 残留；停止 scheduler/worker 不能阻止 Web 继续接受手动提交。
4. 按 P0-3 第 8 项立即停止本轮，没有执行任何 ALTER/COMMENT、没有搬迁对象或发起 Tushare 请求，不取消/删除/修改 #14203。
5. 当时四项服务保持 stopped，schedule #25 保持 paused，等待管理员明确协调；没有自动启动通用 worker 消费未确认的新 queued 任务。随后管理员取消 #14203 并授权继续，执行与恢复结果见 §2.8；这条中止记录不是最终服务状态。
6. 尚未完成最终样本冻结与独立 observer，不能记为先导通过。若管理员另行决定让 #14203 留 queued 并继续迁移，必须先明确变更“开放 TaskRun=0”门禁及恢复消费安排，不能静默忽略。

### 2.8 2026-10-02 P0 继续执行记录

管理员取消 #14203 并明确继续推进后，复验其状态为 canceled、开放 TaskRun=0、#25 paused、probe rule=0、目标锁=0，四项服务仍 inactive。未修改队列门禁或任务状态，沿用既有授权范围继续。

执行使用本机临时脚本 `/private/tmp/stk_mins_p0_execute_20261002.py`，通过现有 SSH/psql 入口连接固定 goldenshare 库；每个关系独立连接/事务，DDL 使用 SET LOCAL ROLE goldenshare_user、15 秒锁超时与 60 分钟语句超时。只修改明确白名单内的 tablespace，不改表结构或业务记录；证据在本机临时目录留存，长期关键结论同步本文。

首次运行在任何 DDL 之前因 catalog OID 的 JSON 值为文本而被类型断言拦停，未写生产；改为 SQL 显式 bigint 投影后重新冻结基线，无放宽门禁。独立观察查询每轮间隔等待 5 秒，含 SSH/查询开销实际约 6～7 秒；记录 PID/等待事件、WAL LSN/目录字节、挂载、Web 健康、服务、任务和外部目标锁，并可取消当前迁移 PID，不终止业务会话。

| 对象 | OID | main 字节 | 提交后路径 | 从启动到验收耗时 | 对象窗口内实例 WAL LSN 增量 |
| --- | ---: | ---: | --- | ---: | ---: |
| stk_mins_2026_02_pkey | 33980 | 1,717,166,080 | pg_tblspc/31284/PG_16_202307071/16779/2486879 | 22.866 秒 | 1,734,008,976 B |
| stk_mins_2026_02 | 33977 | 2,080,423,936 | pg_tblspc/31284/PG_16_202307071/16779/2486880 | 23.639 秒 | 2,101,419,184 B |

2 月两对象 OID/main 字节/owner/边界/索引有效性/父级关系保持不变，位置变为 gs_raw_cold_hdd；迁移前后首末股票频率样本摘要相等，000001.SZ/freq=1 月窗口 Raw/view 双向差异=0；其它所有分钟线关系目录基线未变。两对象于 20:02 完成，至少 5 分钟观察至 20:08 通过后，才开始剩余月份。窗口 LSN 是整个实例的增量，不宣称仅由本对象产生。

先导证据目录 `/private/tmp/stk-mins-p0-vf2g5v3t` 包含冻结目录、样本、逐对象日志/receipt 与 observer.jsonl；剩余月份证据目录为 `/private/tmp/stk-mins-p0-9szjujxj`。临时证据不作为长期唯一事实源，关键数据在下文留档；7～8 月仍未处理。

剩余对象按 05 → 04 → 03 → 01 → 06 顺序串行完成，20:15 全部验收通过：

| 对象 | OID | main 字节 | 最终 relfilenode | 从启动到验收耗时 | 对象窗口内实例 WAL LSN 增量 |
| --- | ---: | ---: | ---: | ---: | ---: |
| stk_mins_2026_05_pkey | 33995 | 2,140,536,832 | 2486881 | 28.553 秒 | 2,161,525,840 B |
| stk_mins_2026_05 | 33992 | 2,696,372,224 | 2486882 | 28.829 秒 | 2,723,567,352 B |
| stk_mins_2026_04_pkey | 33990 | 2,134,581,248 | 2486883 | 24.033 秒 | 2,155,512,304 B |
| stk_mins_2026_04 | 33987 | 3,150,528,512 | 2486884 | 30.109 秒 | 3,182,296,744 B |
| stk_mins_2026_03_pkey | 33985 | 2,092,998,656 | 2486885 | 22.871 秒 | 2,113,522,632 B |
| stk_mins_2026_03 | 33982 | 3,293,978,624 | 2486886 | 34.850 秒 | 3,327,194,496 B |
| stk_mins_2026_01_pkey | 33975 | 2,480,381,952 | 2486887 | 28.754 秒 | 2,504,699,120 B |
| stk_mins_2026_01 | 33972 | 2,966,855,680 | 2486888 | 29.836 秒 | 2,996,784,056 B |
| stk_mins_2026_06_pkey | 34000 | 2,425,012,224 | 2486889 | 28.994 秒 | 2,448,788,888 B |
| stk_mins_2026_06 | 33997 | 3,156,983,808 | 2486890 | 28.769 秒 | 3,188,823,960 B |

全部最终文件路径为 `pg_tblspc/31284/PG_16_202307071/16779/<relfilenode>`。12 个对象 main fork 总字节为 30,335,819,776；六个月含索引/FSM/VM 总关系大小为 30,340,677,632 B（28.26 GiB），与迁移前总量相同。两者相差 4,857,856 B，是 FSM/VM 辅助文件，不是丢失记录；§2.2/2.5 表中 heap/索引列为 main fork，合计列含辅助文件，不应直接用前两列相加代替合计。

最终验收与恢复：

1. 12/12 对象位于 gs_raw_cold_hdd，OID、main 字节、边界、owner、主键和索引父级关系不变，invalid/非 ready 索引=0；逐对象样本摘要与月窗口 Raw/view 双向差异均为 0。无需扫描全表重数全部业务记录。
2. 白名单外所有分钟线关系目录基线未变；7～12 月、default、父表及父级索引仍在原位置。当前表/view/Definition/DAO/请求合同均未修改，无 Alembic revision 变更。
3. 2 月单股单日 view 查询仍为主键 Index Scan，241 行，2.736 ms（shared hit=3/read=8）；迁移前热缓存为 0.154 ms（hit=11），缓存条件不同，不作同口径冷盘性能对比或 SLA。
4. 9 月 30 日/freq=1 的真实成交额聚合只读验收通过，扫描只落热月 9 月，过滤后 1,353,292 行，执行 12,345.391 ms，distinct 排序临时文件约 55,720 kB；仍是既有 Parallel Seq Scan 路径。没有相同参数的迁移前耗时基线，不能声称性能改善或回退；本轮不增索引、ANALYZE 或改业务 SQL。9 月单股热日 view 样本仍为 241 行，时间边界不变。
5. 对象窗口 LSN 增量合计 30,638,143,552 B（约 28.53 GiB），并非 WAL 目录驻留大小；观测目录峰值为 1,073,741,824 B（1 GiB），SSD 最低可用 31,644,835,840 B（约 29.47 GiB）。未触发取消门禁、未见指定 kernel I/O 错误或数据页错误。
6. 20:17:13 文件系统复验：SSD 可用 61,966,233,600 B（57.71 GiB）、使用率 78%；HDD 可用 244,534,538,240 B（227.74 GiB）、使用率 40%。以第一条 DDL 前 monitor 的 SSD 31,764,627,456 B 为基线，净增加 30,201,606,144 B（28.13 GiB）；HDD 可用减少 30,340,808,704 B。文件系统净变化与关系大小量级一致，WAL驻留、其它进程写入/清理和文件系统计量会影响差值，不把差值擅自归为数据缺失或全部归因于 WAL。
7. tablespace comment 已由 postgres 更新；最初使用 obj_description 读取共享 catalog 得到空值，改用 shobj_description 后验证内容正确，未重复写注释或回滚业务 relation。
8. 恢复前队列为空；依次恢复通用 worker、index-mins worker、stk-mins worker、scheduler，四项均 active；Web/数据库保持 active，健康端点 ok。随后 scheduler 正常创建 #14205～#14210 等 scheduled 任务，这是维护完成后的正常恢复，不是迁移期间出现的未预期任务，未重跑或取消它们。
9. schedule #25 仍 paused、绑定 probe rule=0；正式 Ops 页面恢复及下一次自然 probe/TaskRun 观察为唯一未完成的 P0 恢复/观测待办。浏览器入口此前不可用，未伪造身份或直接修改 schedule。7～8 月迁移仍是独立授权的后续阶段。

临时脚本正向 guard 与 13 个负向门禁样本均通过，包括低容量、新任务、未暂停/残留 rule、长事务/锁/basebackup、服务启动、Web/数据库异常、I/O 错误及只读挂载；这只是操作门禁验证，不等于磁盘故障恢复演练。没有额外创建业务 TaskRun 或请求 Tushare，也没有部署、安装、删除或重建业务数据。

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

1. P0 不处理 2026-07～12、default、父表、父级 partitioned index 或其它数据集；7～8 月候选须遵守 §4.3 独立授权边界。
2. 不执行 `DROP/TRUNCATE/DELETE/CREATE TABLE AS/INSERT ... SELECT/REINDEX/VACUUM FULL`。
3. 不使用 `ALTER ... ALL IN TABLESPACE`。
4. 不手工移动 tablespace 目录文件，不移动 WAL，不改 PostgreSQL 全局配置。
5. 不发起 Tushare 请求，不用源端重拉代替物理验收。
6. 不把六个月或一个月对象放在同一个长事务中。
7. 不自动终止业务会话，不使用 `pg_terminate_backend`。
8. 不因本次迁移新增自动 rollover schedule。

### 4.3 分阶段推进与第二阶段边界

| 阶段 | 对象及顺序 | 验收与授权边界 |
| --- | --- | --- |
| P0 第一阶段先导 | 2026-02，先主键索引、后 heap | 每个对象独立提交/验收；两对象通过后观察至少 5 分钟；冻结真实耗时、WAL、磁盘峰值和查询延迟 |
| P0 第一阶段其余月份 | 2026-05 → 04 → 03 → 01 → 06，各月先索引后 heap | 先导闭环后按现有门禁逐月串行；合计释放目标 28.26 GiB；任何失败停止后续对象 |
| 第二阶段候选（非 P0） | 2026-08 → 07，各月先索引后 heap；预期 4 个对象 | P0 闭环后单独确认范围并授权；追加约 10.99 GiB；重新冻结 OID/边界/权限/样本/负向白名单，不能拿 P0 授权自动扩围 |

第二阶段若获授权，复用已验收的逐对象事务、观察、取消、续跑及恢复服务流程；不能把原 P0 六个月的数量、字节或负向白名单照搬成第二阶段验收。9～10 月、default、父级逻辑对象和其它数据集在第二阶段仍不处理。若实际执行月份推迟，重新评估热窗口，但不得自动增加月份。

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

| 门禁 | Go 标准 | 2026-10-02 第一条 DDL 前最终状态（历史执行证据；后续迁移全部重验） |
| --- | --- | --- |
| 授权 | 明确授权 12 个关系、服务暂停、DDL 及紧急 `pg_cancel_backend`；不包含其它表 | 已获 P0 授权，不包含 7～8 月 |
| 风险口径 | 记录管理员已接受无已验证独立备份的剩余风险，并在本次执行记录写清恢复保障缺口；若改选备份模式，则先通过 §6.1 的备份门禁 | 风险已接受，继续按无已验证独立备份口径；不保证极端故障恢复 |
| 挂载 | `/data/disk` 的 source/UUID/fstype 与 fstab 一致，tablespace symlink 指向真实挂载 | source/fstype/rw/路径、fstab/UUID、inode 和指定 kernel 错误检查通过，执行时重验 |
| 容量 | HDD 剩余不少于待迁剩余字节 120% 且不少于 64 GiB；根盘满足 P0-2 逐关系门禁 | SSD 29.79 GiB、HDD 256.00 GiB，容量估算通过，执行时重验 |
| 对象 | 6 个目标叶、6 个物理索引、无 TOAST；OID、边界、owner、位置与白名单一致 | 正向及负向目录、隔离后的样本基线均已冻结并通过 |
| 数据库依赖 | 无新增 trigger/FK/RLS/publication；唯一已知 view 仍为 `core_serving.equity_minute_bar` | 本次目录核验通过，执行时重验 |
| 任务隔离 | schedule paused、probe rule=0、开放 TaskRun=0；指定 worker/scheduler 已停止 | #14203 canceled 后队列清零，schedule paused/rule=0/四项服务停止；迁移期间保持通过，完成后服务已恢复 |
| 会话与锁 | 无超过 30 秒非 idle 事务、无目标关系锁、无 base backup、无其它大维护 | 第一条 DDL 前与迁移期间均通过；不代表后续执行可免检 |
| 持久性配置 | `fsync=on`、`synchronous_commit=on`；不得为加速临时关闭 | 当前通过，执行时重验 |
| 观察会话 | 已准备独立 observer，能记录 PID、LSN、WAL、根盘/HDD 每 5 秒水位 | 已执行并留档；5秒等待加查询开销实际约6～7秒，不提供虚假迁移百分比 |

### 6.1 恢复保障与无备份执行口径

管理员此前明确接受“没有备份条件，承担有风险的一次迁移”。当前采用该口径：缺少独立备份不再单独阻塞准备，但必须保留其它 Go/No-Go 门禁；没有恢复演练或可靠 recovery point，就不得承诺 RTO、PITR 或磁盘故障后可恢复。不得以事务可回滚、旧 DG 数据或 Tushare 可重拉冒充已验证备份。

本方案不会自行创建备份。以后若管理员改选备份模式，须单独授权；可接受证据的推荐顺序如下：

1. **首选：异地 `pg_basebackup` 或等价物理备份。** 必须包含主数据目录和所有 tablespace，并包含恢复所需 WAL；备份结束时间晚于最后一次目标表写入。至少在隔离环境完成目录结构、tablespace 映射和 PostgreSQL 启动验证。
2. **次选：云厂商应用一致性的多磁盘快照。** 必须在同一一致性点覆盖 `/dev/vda2` 和 `/dev/vdb`；单独快照根盘或 HDD 都不合格。需要有可验证的 snapshot ID、完成状态和恢复演练记录。
3. **逻辑备份只能作为补充。** 若使用 `pg_dump`，必须明确包含 `raw_tushare.stk_mins`，输出不能放在根盘或同一 `/data/disk` 故障域，并需证明可在隔离库恢复主键和样本数据。由于数据量大，不推荐把它作为本次最短前置路径。

系统自带但未启用的 `pg_basebackup@.timer`、同机 `/var/backups` 目录、Tushare 可重拉能力都不能作为备份证据。

## 7. P0 详细执行步骤

### P0-0：版本、授权与记录载体冻结

1. 冻结远程 Git revision、Alembic head、PostgreSQL 启动时间、审计时间和执行人。
2. 建立逐对象执行记录，至少包含：月份、对象类型、schema/name/OID、分区边界、index parent/constraint、迁移前 tablespace/filepath/main bytes、开始/结束时间、后台 PID、起止 LSN、WAL 增量、根盘/HDD 峰值、结果和异常。
3. 确认生产授权只覆盖 P0，明确无已验证独立备份的执行口径；暂停排程、停止服务和紧急取消应分别留有操作记录。第二阶段不在 P0 授权内；备份若另获授权，单独记录。
4. 比较执行时远程版本与本次审计基线；代码、表结构、分区或索引发生影响合同的变化时，停止并重新做 CodeGraph 与 catalog 审计。不能把 §2.5 的容量审计视为所有依赖已验收。

### P0-1：冻结风险口径与异常处置方式

1. 在暂停任务前记录：本轮按已接受的无已验证独立备份风险口径执行，不保证极端故障恢复；记录执行人、故障联系与服务恢复清单。
2. 普通 SQL 错误或取消依靠当前对象事务回滚；已提交对象保留，从冻结的逐对象记录继续。HDD 丢失、数据页损坏或 cluster 故障不属于普通事务回滚，立即停止迁移并升级人工处置，禁止自动删表重拉。
3. 不把“未来可购买备份”或同机剩余空间写成现有恢复保障。不承诺无证据的 RTO，不以执行计划生成成功替代恢复能力。
4. 如果管理员在执行前改选 §6.1 备份模式，先核验独立故障域、范围、tablespace 映射、恢复验证，再在 P0-3 写入冻结后生成最终 recovery point；未通过则不得按备份模式执行，也不能擅自降级为无备份模式。

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
3. 等待 `stk_mins` 的 `queued/running/canceling` TaskRun 清零，然后停止 `goldenshare-ops-stk-mins-worker.service`。这只冻结已核实的调度/worker 入口，不是数据库级拒写。另核验人工直调 `DatasetMaintainService`、脚本、直接 SQL 等入口没有写目标，并协调维护窗口内不得触发；入口无法确认时 No-Go。本轮未断言存在正在运行的旁路写入。
4. 确认上述全部目标写入入口已冻结后，记录最后已提交写入与无备份风险口径，不创建未经授权的备份。若另获授权并改选备份模式，则在冻结期间创建最终 recovery point，覆盖 PGDATA、全部 tablespace 和所需 WAL，完成于第一条 DDL 前；不能只比较“最后成功 TaskRun”，失败或取消任务也可能已提交 unit。
5. 等待所有其它 `queued/running/canceling` TaskRun 清零，并确认没有日期完整性、回补、迁移或大规模分页任务。
6. 停止 `goldenshare-ops-scheduler.service`，防止维护窗口产生新自动任务。
7. 按授权停止 `goldenshare-ops-worker.service` 和 `goldenshare-ops-index-mins-worker.service`。这是原窗口的服务清单，不是全实例 I/O 隔离证明；当前代码还存在 QTF 车道及其他可能运行的进程，须按执行时实际负载核验。若需新增停服对象，先补授权和恢复清单，不自行扩大停服范围。Web/API 和 PostgreSQL 保持在线。
8. 再次查询 TaskRun。若维护窗口中有人提交手工任务，即使 worker 已停、任务只会 queued，也必须暂停 P0 并先协调处理。
9. 核验目标关系无锁；数据库不存在超过 30 秒的非 idle 事务或大查询。不能终止现有会话来强行获得维护窗口。

停止服务前必须先等当前任务自然结束。禁止通过 stop 服务中断正在提交业务事务。

职责依据：[worker_lane](/Users/congming/github/goldenshare/src/ops/runtime/worker_lane.py)限制 TaskRun 领取；[DatasetMaintainService](/Users/congming/github/goldenshare/src/foundation/ingestion/service.py)可被直接调用，不以车道是否停止作为业务写入锁。

### P0-4：生成不可变白名单和基线

1. 从 `pg_inherits/pg_class/pg_index/pg_constraint` 动态生成 12 个对象白名单；禁止按名称猜索引。
2. 记录六个叶分区的 OID、边界、owner、tablespace、`pg_relation_filepath()`、main fork 原始字节、`reltoastrelid`。
3. 记录六个索引的 OID、parent index、constraint、tablespace、filepath、main fork 字节、`indisprimary/indisunique/indisvalid/indisready`。
4. 同时记录 2026-07～12、default 和父级逻辑对象的位置，作为负向白名单基线；第二阶段候选在 P0 中仍是不允许修改的对象。
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
3. 2026-07～12、default、父表和父级 partitioned index 仍位于原位置；白名单外对象无变化。
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
2. 依次启动通用 worker、index-mins worker、stk-mins worker，确认各服务 active 且没有错误循环；若另获批准暂停其他进程，按同轮冻结的恢复清单逐项恢复，不遗漏也不启动原本停止的服务。
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
7. **HDD 丢失或 tablespace 不可访问。** 这不是 `SET TABLESPACE pg_default` 能解决的普通回滚。立即停止本轮，按事先批准的故障处置流程决定是否停 PostgreSQL；无独立备份时不能保证恢复，也不能承诺仅损失某个月份。有已验证备份时才按其流程恢复整个 cluster 和 tablespace。禁止把 tablespace 目录单独接到另一 cluster，不擅自删除文件、重建表或请求 Tushare 重拉。
8. **任务恢复异常。** 业务 relation 已提交不因 Ops 状态失败回滚；保持相关 worker/schedule paused，单独修复任务链路。

## 9. 后续滚动治理

1. 进入新月份 `M` 后，新增候选是 `M-2`；未处理旧月仍保留在积压清单。2026-10 时冷月候选为 1～8 月，9～10 月留 SSD；P0 完成后仍有 7～8 月待单独授权，不会自动迁移。
2. 前两次月度 rollover 继续人工执行，复用本方案的风险口径、任务隔离、WAL、对象白名单和验收门禁；无备份执行不代表新月份自动获得授权。
3. 每次只迁 1 个月，单关系串行；不把物理 DDL放入 DatasetDefinition、worker、普通 schedule 或部署 Alembic。
4. 若以后建设存储治理命令，默认只能只读生成计划；显式 execute 才能按白名单逐关系运行，并必须带任务、挂载、恢复保障/风险接受、容量、锁、WAL和断点记录。该建设属于独立开发范围，不在本次顺带开发。
5. 根盘达到 90% 预警，95% 停止新的大规模回补并启动 Top 20 审计；不再等到 98% 才处理。
6. 后续新增分区必须在目标 tablespace 缺失时 fail-closed，禁止静默回退默认盘。

## 10. 风险矩阵

| 风险 | 等级 | 防护 |
| --- | --- | --- |
| 无已验证独立备份，HDD/cluster 故障可能无法恢复 | 很高，管理员已接受的剩余风险 | 写清保障缺口；保留所有其它门禁；不能保证极端故障恢复；以后改选备份模式须独立故障域、完整范围及恢复验证 |
| SSD 可用 29.79 GiB，但 WAL 峰值尚无本次实测 | 中高，较历史 5.5 GiB 明显改善 | 不降低既有门禁；逐关系空间检查、最小索引先导、5秒 observer、3 GiB紧急取消阈值、每对象提交 |
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
2. [HDD 历史迁移记录：股票分钟线（2026-04-26 快照）](/Users/congming/github/goldenshare/docs/ops/prod-postgresql-hdd-migration-history-v1.md#stk-mins-20260426)
3. [分钟线任务执行隔离与运维说明](/Users/congming/github/goldenshare/docs/ops/ops-stk-mins-dedicated-worker-execution-lane-plan-v1.md)
4. [股票历史分钟行情数据集开发说明](/Users/congming/github/goldenshare/docs/datasets/stk-mins-dataset-development.md)
5. [HDD 历史迁移记录：筹码分布（同实例 2026-06-01 执行证据）](/Users/congming/github/goldenshare/docs/ops/prod-postgresql-hdd-migration-history-v1.md#cyq-chips-20260601)
6. [PostgreSQL 16 `ALTER TABLE`](https://www.postgresql.org/docs/16/sql-altertable.html)
7. [PostgreSQL 16 `ALTER INDEX`](https://www.postgresql.org/docs/16/sql-alterindex.html)
8. [PostgreSQL 16 Tablespaces](https://www.postgresql.org/docs/16/manage-ag-tablespaces.html)
9. [PostgreSQL 16 WAL settings](https://www.postgresql.org/docs/16/runtime-config-wal.html)
10. [PostgreSQL 16 `pg_basebackup`](https://www.postgresql.org/docs/16/app-pgbasebackup.html)
