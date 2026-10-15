# 指数与股票技术因子全量迁至 HDD 方案 v1

- 日期：2026-10-15。
- 状态：方案待用户确认；未执行迁移，未执行本方案性能验收。
- 环境：生产 PostgreSQL 16，数据库 `goldenshare`。
- 本轮交付：迁移方案、影响范围及验收步骤；不编写或执行生产迁移脚本。

## 1. 用户已确定的范围

采用方案 1：指数、股票技术因子数据集全部迁至现有 HDD，包括已有数据，以及以后新增、补录和更新的数据。采用整表表空间迁移，不按日期分区。

| 硬口径 | 本方案落点 |
| --- | --- |
| 只处理两个数据集 | §2 的两张 Raw 表及所属索引、TOAST |
| 全量放 HDD，保持当前数据与接口 | §3、§5，仅改变物理存储位置 |
| 先确认方案，暂不迁移 | 当前只修改文档；§5 是未来获准后的执行步骤 |
| 不做迁移前性能验收 | §4 仅做迁移安全与正确性准备，不发起 300/2000 性能请求 |
| 性能验收放在迁移完成后 | 两张表、全部索引及 TOAST 迁移验收完成后，才进入 §6 |
| 性能只测 300/2000 查询 | §6 四组现有 K 线 API 请求，不测其他业务 |

不修改业务源码、`DatasetDefinition`、ORM、DAO、writer、API、前端或配置项，不新增 Alembic revision，不部署应用。不开启历史回补，不发起同步任务，不测试股票复权历史重刷，不扩大为全站性能测试。数据库 WAL 和其它数据集继续使用原有存储位置。

原[存储治理 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v1.md)记录了热数据留 SSD、技术因子另行设计的原决定。本次用户明确选择两数据集全量 HDD，并接受性能取舍；这项新决定仅适用于本文白名单。原历史记录保留，新方案回链到[存储治理 v2](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v2.md)，不改变其他数据集的冷热规则。

## 2. 迁移对象与已有证据

### 2.1 页面入口和真正的存储对象

| 对外读取入口 | 关系类型 | 实际物理表 |
| --- | --- | --- |
| `core_serving.index_factor_pro` | 普通视图 | `raw_tushare.idx_factor_pro` |
| `core_serving.equity_factor_pro` | 普通视图 | `raw_tushare.stk_factor_pro` |

两个视图没有独立行情文件，不对视图执行迁移，也不重建视图。实际迁移白名单和执行顺序如下：

| 顺序 | 对象 | 类别 |
| --- | --- | --- |
| 1 | `raw_tushare.idx_factor_pro` | 表，连同所属 TOAST 存储 |
| 2 | `raw_tushare.pk_raw_tushare_idx_factor_pro` | 主键索引 |
| 3 | `raw_tushare.idx_raw_tushare_idx_factor_pro_trade_date` | 日期索引 |
| 4 | `raw_tushare.stk_factor_pro` | 表，连同所属 TOAST 存储 |
| 5 | `raw_tushare.pk_stk_factor_pro` | 主键索引 |
| 6 | `raw_tushare.idx_raw_tushare_stk_factor_pro_trade_date` | 日期索引 |
| 7 | `raw_tushare.idx_raw_tushare_stk_factor_pro_ts_code_trade_date` | 代码、日期索引 |

TOAST 表及其索引由所属 Raw 表的 `reltoastrelid` 和 `pg_index` 精确解析，纳入迁移前后位置核验，不按名称通配迁移其它对象。业务表的五个索引需要单独迁移，不能认为迁表就已迁完索引。

源表空间为 `pg_default`。目标表空间为已存在的 `gs_raw_cold_hdd`，物理目录为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`，挂载 `/dev/vdb` → `/data/disk`。不新建或重命名表空间，不手工移动数据库文件。SSD/HDD 是项目的运营称呼，虚拟机内的 `ROTA` 不能单独证明云底层介质。

### 2.2 本会话已经完成的只读快照

以下来自 2026-10-15 本会话前几轮的生产 catalog 和服务器挂载读取，不是迁移前性能测试；正式执行时需刷新，不以旧快照代替执行条件。

| 对象 | 表及 TOAST | 业务索引 | 合计 | 当前结构 |
| --- | ---: | ---: | ---: | --- |
| `idx_factor_pro` | 2379 MiB | 149 MiB | 2,650,734,592 B，约 2.47 GiB | 普通表，无分区 |
| `stk_factor_pro` | 7375 MiB | 265 MiB | 8,011,546,624 B，约 7.46 GiB | 普通表，无分区 |

两表合计约 9.93 GiB；当时 SSD 根盘可用约 46.18 GiB，HDD 可用约 226.80 GiB。这只覆盖当前已存数据，不能作为以后补齐全历史的容量承诺。迁移预计释放对应关系的 SSD 占用，实际 `df` 差额还受 WAL 和其它运行活动影响，不承诺精确释放 9.93 GiB。

## 3. 影响范围

### 3.1 代码与消费者

本方案使用仓库根 CodeGraph 的 `codegraph_explore`，并核对当前源文件，确认以下链路：

| 链路 | 当前代码依据 | 迁移影响 |
| --- | --- | --- |
| Raw 写入 | [writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)、[BaseDAO](/Users/congming/github/goldenshare/src/foundation/dao/base_dao.py) | 仍按同一 `(ts_code, trade_date)` upsert；后续写入落在迁后的表及索引上 |
| 指数 K 线、行情取值 | [IndexDetailQuery](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/index_detail/index_detail_query.py) | 仍读同名 Serving 视图 |
| 股票 K 线、最新因子取值 | [StockDetailQuery](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/stock_detail/stock_detail_query.py) | 仍读同名 Serving 视图 |
| 指数、股票九转查询 | [指数查询](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/index_nine_turn/index_nine_turn_query.py)、[股票查询](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/stock_nine_turn/stock_nine_turn_query.py) | 同样依赖因子视图，可能受锁等待和 HDD I/O 影响；不纳入本次性能测试 |
| 指数日线徐小明数据读取 | [source](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/index_detail_xxm/source.py) | 可能受锁等待和 HDD I/O 影响；不纳入本次性能测试 |
| 股票已有历史更新规划 | [unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) | 仍使用同一 Raw 表，不改逻辑，不触发重刷验收 |

这些是影响告知，不增加验收项目。代码外的人工 SQL、临时导出或外部直连由执行前的会话、锁核验确认；当前代码审计不代表不存在仓库外消费者。

### 3.2 维护窗口与边界

`SET TABLESPACE` 会获取排他锁；对应表的查询和写入可能等待，必须安排维护窗口。Web 不需要为此部署或重启，但不能承诺两个详情页在搬表期间完全无感。共享 HDD 和根盘 WAL 也会承受迁移 I/O。

维护窗口内只隔离会写这两张 Raw 表的人工同步、工作流、探测及外部写入入口。若它们由共享 scheduler/worker 承载，确需临时暂停共享进程时，应在执行前列明实际服务名、原状态和连带暂停范围；不扩大为全站停服。只恢复本次确实暂停且原本启用的入口。

不改变子系统边界、依赖矩阵、字段、主键、索引定义、view 定义、权限和 API 合同。表、视图和索引的 OID 应保持不变；物理文件路径按迁移预期改变。

## 4. 正式执行前的必要准备，不做性能测试

以下步骤仅在方案和生产维护窗口获准后执行。本轮不暂停任何服务或任务。

1. 只读刷新两表、五个索引、所属 TOAST 的 OID、类型、表空间、物理路径、各 fork 字节、索引有效性、主键和 view 定义。确认白名单与 §2 一致；有新增索引或结构漂移就先更新清单，不能自动扩展 DDL。
2. 确认目标表空间已存在、目录确实位于 `/data/disk` 挂载、权限可用；确认 HDD 能容纳全部待迁对象及余量，根盘能容纳迁移 WAL。记录现有实例恢复保障及其覆盖范围；未知不得写成已具备，不在本专项内自行新建备份工程。
3. 先冻结上述入口的新任务提交和自动触发，让已有 worker 完成相关 queued/running/canceling TaskRun；排空后，再按实际需要暂停写入进程，确认目标长事务、锁等待清零。不能先停 worker 再等待队列自行排空；不强制取消未知任务，不杀其它业务连接。不能确认隔离就不执行 DDL。
4. 隔离完成后冻结正确性基线：对象 OID/定义、各 fork 大小，以及 `000001.SH`、`000001.SZ` 各最早和最近 3 行的固定字段样本。指数投影 `ts_code/trade_date/open/close/ma_bfq_5/macd_bfq`；股票投影 `ts_code/trade_date/open/close_qfq/ma_qfq_5/macd_qfq`。后续按相同键读回比较。这是小样本正确性检查，不计时，不调用性能测试接口。
5. 执行清单保存到 `/private/tmp/factor-pro-full-hdd-<执行时间>/`，记录每个对象的初始位置和已提交状态，不向 Ops 状态表新增记录。执行记录不得包含密码、token 或连接串凭据。

不运行迁移前 300/2000 请求、不采集迁移前延迟、不做迁移前 `EXPLAIN ANALYZE`，不清数据库或操作系统缓存，不做全表 `count(*)`、全表 hash 或全量导出。

## 5. 获准后的具体迁移步骤

### 5.1 执行方式

通过现有生产数据库连接执行，只使用明确对象的 PostgreSQL 原生 DDL。以下七条是待批准的命令清单，现在不执行：

```sql
ALTER TABLE raw_tushare.idx_factor_pro SET TABLESPACE gs_raw_cold_hdd;
ALTER INDEX raw_tushare.pk_raw_tushare_idx_factor_pro SET TABLESPACE gs_raw_cold_hdd;
ALTER INDEX raw_tushare.idx_raw_tushare_idx_factor_pro_trade_date SET TABLESPACE gs_raw_cold_hdd;

ALTER TABLE raw_tushare.stk_factor_pro SET TABLESPACE gs_raw_cold_hdd;
ALTER INDEX raw_tushare.pk_stk_factor_pro SET TABLESPACE gs_raw_cold_hdd;
ALTER INDEX raw_tushare.idx_raw_tushare_stk_factor_pro_trade_date SET TABLESPACE gs_raw_cold_hdd;
ALTER INDEX raw_tushare.idx_raw_tushare_stk_factor_pro_ts_code_trade_date SET TABLESPACE gs_raw_cold_hdd;
```

每条 DDL 单独一个事务，设置本次会话的 `lock_timeout='5s'`、`statement_timeout='15min'`；这是维护命令的等待/执行上限，不是新增应用配置，也不是耗时预估。每条成功提交后立即核验并保存结果；锁超时、语句超时或校验失败就停止，不自动重试或调大上限。

先完成指数表及两个索引的物理与正确性检查，再迁股票表及三个索引。不把七条 DDL 放在覆盖两表的长事务里，不用 `ALL IN TABLESPACE` 或通配对象执行。

### 5.2 每条及每张表的检查

每条提交后确认目标对象 OID 不变、表空间为 `gs_raw_cold_hdd`、文件路径映射至目标挂载、大小符合隔离时基线，索引仍有效。搬表时同步核验其 TOAST 表及索引的位置，不能只看 Raw 表的 `reltablespace`。

每张表完成后确认该表及其全部附属对象位置一致、主键/索引/view 定义和权限不变，固定样本读回一致。表和索引分条提交会短暂出现跨盘状态，须在该表批次内闭环，不把中间态标成迁移完成。

逐对象观察根盘、HDD 和 WAL 水位，不在空间不足或异常增长时继续下一条。没有实测吞吐，当前不承诺搬迁分钟数。

### 5.3 失败、中断与回迁

- 当前 DDL 失败：回滚当前事务，重新读取 catalog 判断真实位置；已经提交的前序对象保留，不假定全部自动退回 SSD。
- 连接断开：先查本次后台 PID 和对象状态，确认命令已结束后再决定是否续跑，不能重复提交仍在执行的迁移。
- 中间态可安全继续时，按已核验清单只补未完成对象；存在数据、索引、磁盘或锁异常时停止并报告，不跳过异常继续后续表。
- 若决定回迁，按实际已迁对象逐个 `SET TABLESPACE pg_default`，仍需容量、锁和维护窗口；回迁不是瞬时撤销，不因查询变慢自动触发。
- 实例或磁盘故障按已有实例恢复保障处理；SQL 事务回滚不等于介质故障恢复。

故障处置不得使用删表、清表、表重建、手工搬文件或重新从 Tushare 拉全量数据来替代迁移恢复。

## 6. 两个数据集迁移完成后的唯一性能验收

前提：§5 两张表、全部索引和 TOAST 都已迁到 HDD，物理检查及样本一致性通过。此时才发起下列测试；没有迁移前性能基线，不做 SSD/HDD 延迟对比。

使用当前生产 Web 的正常认证和既有 K 线接口，截止日固定为 `2026-10-14`。测试过程中保持参数和请求路径一致，不借用 mock 或本机 Lake 数据。

| 用例 | API 路径 | 参数 |
| --- | --- | --- |
| 指数 300 | `/api/v1/wealth/market/index-detail/kline` | `tsCode=000001.SH&period=day&endDate=2026-10-14&limit=300` |
| 指数 2000 | 同上 | 同上，仅 `limit=2000` |
| 股票 300 | `/api/v1/wealth/market/stock-detail/kline` | `tsCode=000001.SZ&period=day&adjustment=forward&endDate=2026-10-14&limit=300` |
| 股票 2000 | 同上 | 同上，仅 `limit=2000` |

每组串行 20 次，共 80 次；测量从请求发出到完整响应体接收的耗时，记录 HTTP 状态、错误、实际根数、首尾日期、首次耗时、后 19 次的中位数和 20 次的最大值。保持普通连接复用，不重启服务，不清缓存，不把首次请求宣称为真正冷盘测试。

用户已接受性能取舍，本方案不新增毫秒或倍数门槛；如实报告迁移后的耗时。请求报错、超时、业务返回异常或同组固定参数的 K 线业务字段出现不可解释变化时，记录失败，不以“接受变慢”掩盖读取错误；不自动改 SQL、加缓存、改索引或回迁。

2026-10-15 前几轮实测中，截止 `2026-10-14` 的指数 2000 上限实际返回 913 根、股票实际返回 429 根。正式验收记录实际数量，不补写数据来凑 2000 根，不把短结果误称为真实 2000 根 payload 验证；也不因此扩大到其它代码、日期或回补任务。

不增加 page-init、九转、徐小明、复权历史重刷、同步写入、并发压力、其它日期窗口或浏览器拖拽测试。迁移不修复页面固定加载 300 根、没有拖拽补载的现状。

## 7. 收尾及交付证据

1. 保存两表、五个业务索引及 TOAST 的最终位置、OID、大小、定义/权限、索引有效性和固定样本核验结果。
2. 保存四组、每组 20 次的迁移后接口性能结果；明确实际根数、错误数和耗时，不填写迁移前性能结果。
3. 恢复本次暂停且原本启用的写入入口，核对恢复状态；不额外发起同步、历史重刷或其它业务任务作为验收。
4. 报告已完成对象、未完成对象、异常处置和最终磁盘水位。恢复入口或任一物理/正确性检查未完成时，不标记全部结案。

确认方案与授权执行生产维护窗口是两个步骤。本文当前只请求用户确认方案，不代表已获准执行 DDL、暂停任务或开展迁移后测试。

## 8. 依据

- 本会话用户决定：两数据集全部 HDD；仅迁移后做 300/2000 查询性能验收；当前只整理方案。
- [存储治理 v2](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v2.md)、[历史 HDD 记录](/Users/congming/github/goldenshare/docs/ops/prod-postgresql-hdd-migration-history-v1.md)。历史批次不是此次迁移授权。
- [指数数据集说明](/Users/congming/github/goldenshare/docs/datasets/idx-factor-pro-dataset-development.md)、[股票数据集说明](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-dataset-development.md)。
- [PostgreSQL 16 ALTER TABLE](https://www.postgresql.org/docs/16/sql-altertable.html)、[ALTER INDEX](https://www.postgresql.org/docs/16/sql-alterindex.html)、[Tablespaces](https://www.postgresql.org/docs/16/manage-ag-tablespaces.html)：原生迁移、索引单独移动、锁及恢复边界。
