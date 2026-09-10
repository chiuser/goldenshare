# 生产 PostgreSQL HDD 历史迁移记录

状态：历史记录，不是当前运行快照或迁移操作手册。整理日期：2026-09-10。

本文合并股票分钟线与筹码分布的两次历史迁移记录。下面的容量、对象数量、权限和验收结果均来自原记录，未在本轮重新连接生产复验。旧操作命令、年度审计 SQL 和重复施工步骤退出当前文档，全文可从 Git 历史追溯。

## 1. 时间线与适用边界

| 时间 | 记录内容 | 不能据此推导的结论 |
| --- | --- | --- |
| 2026-04-26 | `stk_mins` 按年度进行历史分区和索引迁移，当时表基本为空 | 不能用当时对象数量、容量或迁移速度判断今天的大表 |
| 2026-04-27 | 后续存储瘦身 migration 重建空表并改变列、主键和索引布局 | 不能将 4 月 26 日的 576 个索引视为后续现行数量，也不能重跑历史空表重建 |
| 2026-06-01 | 表空间 catalog 改名，`cyq_chips` heap 与三个索引迁入 HDD | 不能证明其他表已迁移，或后续分钟线 P0 已完成 |
| 2026-08-23 | 后续方案废止年度规则，采用两个月滚动热窗口；当次 P0 复审记录为 No-Go | 这是带日期的方案与状态记录，不证明今天生产布局或恢复证据仍相同 |

现行维护规则与后续执行边界分别见[存储空间优化治理专项](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v1.md)和[分钟线存储瘦身与滚动冷热治理方案](/Users/congming/github/goldenshare/docs/datasets/stk-mins-storage-slimming-plan-v1.md)。本轮不修改其 P0 白名单、可恢复性门禁或授权要求，不重新启动 P0。

<a id="stk-mins-20260426"></a>

## 2. 股票分钟线：2026-04-26

当时处理生产库 `goldenshare` 的 `raw_tushare.stk_mins` 月分区：

- 将 `stk_mins_2010_01`～`stk_mins_2025_12` 的 192 个叶分区及 576 个分区索引放到当时名为 `gs_stk_mins_hdd` 的表空间。
- 2026-01 及以后分区、对应索引和 `stk_mins_default` 保留默认盘。
- 当次四项年度位置校验均为 0 违规：历史表、历史索引未迁入 HDD，以及未来表、未来索引误入 HDD。
- 当时空间记录：HDD 192 个分区约 6 MB，默认盘 132 个分区约 4 MB；表基本为空，因此迁移成本很低。这些数字不是当前数据量或性能基准。

后续 [20260427_000080 瘦身 migration](/Users/congming/github/goldenshare/alembic/versions/20260427_000080_slim_stk_mins_storage.py)在升级前检查目标表为空，再重建结构与月分区，仅建立主键索引；分区按 `trade_time`，主键变为 `(ts_code, freq, trade_time)`。历史 576 个索引仍应作为原事件证据保留，不能改成后来的数量。该 migration 不是当前非空表的维护工具。

旧“2025 及以前 HDD、2026 及以后 SSD”校验 SQL 已移除：年度规则已废止，原文 SQL 又混入后来的表空间新名称，不应再作为复现当时现场或当前合规的快捷入口。

<a id="cyq-chips-20260601"></a>

## 3. 筹码分布：2026-06-01

原记录执行时间：08:10～08:16 CST。该次复用并改名现有表空间，不新建表空间，不移动其底层目录；只迁移下列四个对象，未清表、删表、重建表或修改业务代码及 Serving view。

| 对象 | 类型 | 当时迁移后表空间 | 当时大小 |
| --- | --- | --- | ---: |
| `raw_tushare.cyq_chips` | heap | `gs_raw_cold_hdd` | 14 GB |
| `raw_tushare.cyq_chips_pkey` | 主键索引 | `gs_raw_cold_hdd` | 14 GB |
| `raw_tushare.idx_raw_tushare_cyq_chips_ts_code_trade_date` | 索引 | `gs_raw_cold_hdd` | 2480 MB |
| `raw_tushare.idx_raw_tushare_cyq_chips_trade_date` | 索引 | `gs_raw_cold_hdd` | 1292 MB |

验收记录：

- 根盘可用空间从执行前约 14G 增至 46G，HDD 可用空间从 374G 降至 342G，约释放 32G 根盘空间；较早预审记录的根盘可用值为 13G，两者不是同一次采样。
- 对 `ts_code='000001.SZ'`、`trade_date >= 2026-05-01` 的原始表计数返回 1890，证明当时该最小读路径可用，不是全表一致性或完整性能验收。
- 原记录说明执行前没有该数据集 queued/running/canceling 任务、未停止 Ops worker、期间未发起新的手动任务。这只是当次做法，不作为后续大表迁移的通用写入隔离保证。
- 约 6 分钟的耗时只能作为同实例历史参考，不能成为分钟线 P0 或其他关系的耗时承诺。

## 4. 表空间名称与物理目录

以下映射来自 6 月迁移记录及 8 月复核记录，不代替新的 catalog、挂载和权限核验：

| 项目 | 历史记录 |
| --- | --- |
| catalog 名称 | `gs_stk_mins_hdd` 于 2026-06-01 改为 `gs_raw_cold_hdd` |
| 物理目录 | 保持 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`，未随 catalog 改名 |
| 挂载 | `/dev/vdb`、ext4、`/data/disk`；当时 fstab 按 UUID 持久化 |
| 权限 | tablespace owner 为 `postgres`；目录 `postgres:postgres`、700；应用角色有该表空间 CREATE 权限 |
| 遗留注释 | 2026-08-23 记录仍有“2025 及以前冷、2026 及以后热”的旧注释；后续方案要求单独授权修正，本文不声称已修正 |

最初目录曾从 `/root/data/disk` 调整到 `/data/disk`，用于避免 `/root` 访问权限限制。不得因为物理路径仍含旧名字，就把 catalog 改回旧名或手工重命名数据库目录。

## 5. 不随合并丢失的安全边界

1. 历史成功记录不授予再次执行迁移、回迁、GRANT、修改注释、暂停服务或重建表的权限。新的执行必须核实当时的对象白名单、部署版本、挂载、空间、WAL、锁和写入隔离条件。
2. 后续分钟线方案按当前月和上月保热、关闭月份逐月评估，不自动执行 DDL。详细算法、对象顺序和验收只在现行方案维护，本文不复制第二套规则。
3. 旧瘦身 migration 仍硬编码旧表空间名与 `year <= 2025`，表空间不存在时回落默认盘。后续方案要求的新环境 fail-closed 是已登记的治理差距，不是该历史 migration 已实现的能力；本轮不改已应用 revision。
4. 不手工移动 PostgreSQL 数据文件。表空间是 cluster 的一部分，可恢复性覆盖 PGDATA、全部 tablespace 和恢复所需 WAL，不能只复制 HDD 目录。
5. 性能回迁与介质故障恢复分开处理。正常回迁也需重新评估 HDD 健康、根盘容量和维护窗口并获授权；HDD 丢失或不可访问不能依赖旧“迁回默认盘”命令解决。具体失败处理见[后续方案 §8](/Users/congming/github/goldenshare/docs/datasets/stk-mins-storage-slimming-plan-v1.md#8-失败部分完成与恢复)。

原两份文档已合并并移除，完整操作过程可从提交 `c6bb2ec4` 中的原文件追溯；路径与去向记于[文档整合记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-hdd-history-consolidation-20260910)。本轮没有执行生产查询、数据库命令、备份或物理数据修改。
