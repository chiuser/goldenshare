# 指数与股票技术因子全量迁至 HDD 方案 v1

- 日期：2026-10-15 设计；2026-10-16 执行更新。
- 状态：两数据集物理迁移及排程恢复已完成；性能验收按用户最新要求延期，尚未执行。最新证据见 §10；§9 保留上次受阻窗口。
- 环境：生产 PostgreSQL 16，数据库 `goldenshare`。
- 本轮交付：原迁移方案、逐对象迁移及正确性证据、排程恢复记录；不将性能未验收写成全部结案。

## 1. 用户已确定的范围

采用方案 1：指数、股票技术因子数据集全部迁至现有 HDD，包括已有数据，以及以后新增、补录和更新的数据。采用整表表空间迁移，不按日期分区。

| 硬口径 | 本方案落点 |
| --- | --- |
| 只处理两个数据集 | §2 的两张 Raw 表及所属索引、TOAST |
| 全量放 HDD，保持当前数据与接口 | §3、§5，仅改变物理存储位置 |
| 先确认方案，再明确授权执行 | 原设计阶段不操作生产；本次已获明确执行授权，最新执行结果见 §10 |
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

维护窗口内只隔离会写这两张 Raw 表的人工同步、工作流、探测及外部写入入口。获准的详细计划只通过正式入口暂停 #2、#24、#32，保持 scheduler、通用 worker 及其它服务运行，不扩大停服。只恢复本次确实暂停且原本启用的入口。

不改变子系统边界、依赖矩阵、字段、主键、索引定义、view 定义、权限和 API 合同。表、视图和索引的 OID 应保持不变；物理文件路径按迁移预期改变。

## 4. 正式执行前的必要准备，不做性能测试

以下步骤仅在方案和生产维护窗口获准后执行；本次获准后的实际结果见 §10。

1. 只读刷新两表、五个索引、所属 TOAST 的 OID、类型、表空间、物理路径、各 fork 字节、索引有效性、主键和 view 定义。确认白名单与 §2 一致；有新增索引或结构漂移就先更新清单，不能自动扩展 DDL。
2. 确认目标表空间已存在、目录确实位于 `/data/disk` 挂载、权限可用；确认 HDD 能容纳全部待迁对象及余量，根盘能容纳迁移 WAL。记录现有实例恢复保障及其覆盖范围；未知不得写成已具备，不在本专项内自行新建备份工程。
3. 通过正常管理员会话的正式 pause API 暂停 #2、#24、#32，核验 #32 的绑定探测规则随正式流程移除；不人工提交两数据集任务。保持各服务运行，等待相关 queued/running/canceling TaskRun 排空，确认目标写入会话、长事务、阻塞锁清零。每 10 秒检查、最长 20 分钟；不能隔离则恢复本次已暂停入口并退出，不强制取消任务或杀其它连接。
4. 隔离完成后冻结正确性基线：对象 OID/定义、各 fork 大小，以及 `000001.SH`、`000001.SZ` 各最早和最近 3 行的固定字段样本。指数投影 `ts_code/trade_date/open/close/ma_bfq_5/macd_bfq`；股票投影 `ts_code/trade_date/open/close_qfq/ma_qfq_5/macd_qfq`。后续按相同键读回比较。这是小样本正确性检查，不计时，不调用性能测试接口。
5. 执行清单保存到 `/private/tmp/factor-pro-full-hdd-<执行时间>/`，记录每个对象的初始位置和已提交状态，不向 Ops 状态表新增记录。执行记录不得包含密码、token 或连接串凭据。

不运行迁移前 300/2000 请求、不采集迁移前延迟、不做迁移前 `EXPLAIN ANALYZE`，不清数据库或操作系统缓存，不做全表 `count(*)`、全表 hash 或全量导出。

## 5. 获准后的具体迁移步骤

### 5.1 执行方式

通过现有生产数据库连接执行，只使用明确对象的 PostgreSQL 原生 DDL。以下七条已在本次获准窗口逐条执行，提交记录见 §10；此处不是再次执行指令：

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

确认方案与授权执行生产维护窗口是两个步骤。本次用户以“PLEASE IMPLEMENT THIS PLAN”明确授权执行所附详细计划；授权不等于执行完成，最新执行结果见 §10。

## 8. 依据

- 本会话用户决定：两数据集全部 HDD；仅迁移后做 300/2000 查询性能验收。原设计阶段只整理方案，后续明确授权执行；2026-10-16 又明确要求性能验收稍后继续，详见 §9、§10。
- [存储治理 v2](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v2.md)、[历史 HDD 记录](/Users/congming/github/goldenshare/docs/ops/prod-postgresql-hdd-migration-history-v1.md)。历史批次不是此次迁移授权。
- [指数数据集说明](/Users/congming/github/goldenshare/docs/datasets/idx-factor-pro-dataset-development.md)、[股票数据集说明](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-dataset-development.md)。
- [PostgreSQL 16 ALTER TABLE](https://www.postgresql.org/docs/16/sql-altertable.html)、[ALTER INDEX](https://www.postgresql.org/docs/16/sql-alterindex.html)、[Tablespaces](https://www.postgresql.org/docs/16/manage-ag-tablespaces.html)：原生迁移、索引单独移动、锁及恢复边界。

## 9. 历史窗口：2026-10-15 获准后在 DDL 前停止

### 9.1 本次确认的具体执行约束

用户批准所附详细执行计划，接受独立备份未验证的风险，不增加备份建设。执行白名单和顺序仍为 §2.1 的七个对象，每条独立事务；`lock_timeout='5s'`、`statement_timeout='15min'`，超时停止，不自动重试或提高上限。

开始前根盘可用至少 20 GiB，HDD 可用至少为全部待迁对象加 10 GiB；过程中任一盘低于 10 GiB 停止后续语句，必要时只取消本次 DDL。只通过正常管理员会话的正式 pause/resume API 暂停、恢复 #2、#24、#32，核验 #32 绑定探测规则随正式流程删除、重建；只恢复本次从 active 改为 paused 的排程。保持其它服务运行，相关任务及写入会话排空每 10 秒检查一次、最长 20 分钟，不能排空则恢复入口并退出。

隔离完成后才冻结定义、权限、OID 及两个固定标的最早/最近各 3 行的正确性样本；本次尚未进入这一步。指数表、两个索引、TOAST 及样本检查通过后才能开始股票表。两数据集全部迁移、物理及数据检查通过后，才按 §6 四组各 20 次、每次 30 秒请求上限进行唯一性能验收；此上限不是速度达标线。失败保留已提交对象，不自动回迁、不扩大停服或验收范围。

### 9.2 实际预检与停止原因

- 执行目录：`/private/tmp/factor-pro-full-hdd-20261015_234454/`，包含 `host-preflight.txt`、`preflight.sql`、`preflight.json`、`final-no-ddl.json`、`host-final.txt` 和 `execution-report.md`。
- 23:46:54+08 主机预检：根盘可用 49,591,898,112 B（约 46.19 GiB），HDD 可用 243,526,631,424 B（约 226.80 GiB）；HDD 挂载及目录权限正常，目标表空间仍指向 §2.1 的现有目录，空间门槛通过。Web、scheduler、通用 worker 均运行。`pg_wal` 为 603,979,776 B；`archive_mode=off`，独立备份仍未验证。
- 23:48:55+08 catalog 预检：两表、五个业务索引、两张 TOAST 表及两个 TOAST 索引共 11 个存储对象均在 `pg_default`；另核验两个普通 Serving view。七个索引均 valid/ready，OID、列、约束、索引和视图定义、owner、ACL 已保存。未查询 K 线 API、未做查询计时或 `EXPLAIN ANALYZE`。
- 生产后台显示正常 `admin` 管理员会话，但浏览器标签页操作连接反复超时；原生界面虽可读取自动运行页，点击指定排程后选中对象没有变化，截图也无法提供可用画面。无法可靠调用指定排程的正式暂停流程，按计划停止，不改数据库排程状态、不制造 token、不调用内部 service 绕过。
- 23:53:55+08 再次只读核验：全部 13 个对象的 catalog 记录与预检完全一致；#2、#24、#32 均 active，#32 的绑定探测 #16 仍 active。本次没有成功暂停任何排程，无需恢复；七条 DDL 均未执行，正确性样本及 80 次性能请求均未执行。
- 23:53:53+08 最终水位：根盘可用 49,616,953,344 B，HDD 可用 243,526,631,424 B。两数据集仍在原位置，迁移未完成。

该窗口当时要求恢复正式管理员操作通道后刷新预检，不能跳过隔离和正确性基线。2026-10-16 用户通过正常后台协助暂停、恢复排程后的实际续行结果见 §10；本节不再代表当前未迁移状态。

## 10. 2026-10-16 实际执行：物理迁移及排程恢复完成，性能延期

### 10.1 隔离与基线

用户确认通过生产后台暂停三条排程。00:15:49+08 只读确认 #2、#24、#32 均 paused，原 #16 探测已由正式流程移除；00:16:20+08 相关直接任务、工作流、目标锁及长事务均为空，无需等待、强制取消或停服务。00:19:31+08 进入股票批次前再次核验仍为空。

重新核验的对象清单与上次一致；根盘可用 49,607,462,912 B，HDD 可用 243,526,631,424 B。两表及附属对象合计 10,662,281,216 B，开始前根盘 20 GiB、HDD 待迁对象加 10 GiB 的门槛通过。目标表空间 OID 为 31284，目录及挂载正常。隔离后保存完整定义和 12 行固定字段样本，未调用任何性能接口。

### 10.2 七条独立事务及实物位置

| 步骤 | 后台 PID | 开始时间（+08） | 提交时间（+08） |
| ---: | ---: | --- | --- |
| 1 | 1849298 | 00:17:28.160243 | 00:17:46.698746 |
| 2 | 1849690 | 00:18:40.727795 | 00:18:41.52954 |
| 3 | 1849886 | 00:19:08.507804 | 00:19:08.764909 |
| 4 | 1850599 | 00:21:42.680777 | 00:22:35.20214 |
| 5 | 1851137 | 00:23:01.338255 | 00:23:02.097341 |
| 6 | 1851278 | 00:23:19.969281 | 00:23:20.175389 |
| 7 | 1851392 | 00:23:35.890671 | 00:23:36.55297 |

每条均保持 `lock_timeout='5s'`、`statement_timeout='15min'`。指数批次完成并核对样本后才进入股票批次；每次提交后读取 catalog 检查再执行下一条。没有 DDL 失败、锁超时、语句超时、自动提高上限或回迁。

股票表首次启动请求遭工具自动审批处理超时，未创建数据库会话；只读确认无该命令后台会话且表仍在原位置后，按工具允许重试一次并成功。该事件不是数据库 DDL 超时，没有重复执行已启动的 DDL。预检曾因连接角色无 `pg_read_all_settings` 权限而无法读取非必要的 `data_directory` 设置，随后省去该字段，不修改数据库权限。

以下 11 个对象的实际文件均位于 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd/PG_16_202307071/16779/`，表空间均为 `gs_raw_cold_hdd`。表中列出主文件名；指数表 3 个、股票表 8 个 main 分段均检查真实文件大小之和，其余对象各一个 main 文件。空 TOAST 表也已迁移。

| 对象 | OID | HDD 文件名 | main 字节 | 结果 |
| --- | ---: | --- | ---: | --- |
| `raw_tushare.idx_factor_pro` | 1754246 | `2633907` | 2,493,825,024 | 已迁移、核验通过 |
| `raw_tushare.pk_raw_tushare_idx_factor_pro` | 1754253 | `2633910` | 132,620,288 | 已迁移、核验通过 |
| `raw_tushare.idx_raw_tushare_idx_factor_pro_trade_date` | 1754255 | `2633911` | 23,576,576 | 已迁移、核验通过 |
| `raw_tushare.stk_factor_pro` | 23762 | `2633912` | 7,731,232,768 | 已迁移、核验通过 |
| `raw_tushare.pk_stk_factor_pro` | 23769 | `2633915` | 124,862,464 | 已迁移、核验通过 |
| `raw_tushare.idx_raw_tushare_stk_factor_pro_trade_date` | 23771 | `2633916` | 30,081,024 | 已迁移、核验通过 |
| `raw_tushare.idx_raw_tushare_stk_factor_pro_ts_code_trade_date` | 23772 | `2633917` | 123,183,104 | 已迁移、核验通过 |
| `pg_toast.pg_toast_1754246` | 1754251 | `2633908` | 0 | 已迁移、核验通过 |
| `pg_toast.pg_toast_1754246_index` | 1754252 | `2633909` | 8,192 | 已迁移、核验通过 |
| `pg_toast.pg_toast_23762` | 23767 | `2633913` | 0 | 已迁移、核验通过 |
| `pg_toast.pg_toast_23762_index` | 23768 | `2633914` | 8,192 | 已迁移、核验通过 |

00:23:55+08 完成 catalog 统一核验，并通过 SSH 只读解析每个文件的真实路径、分段及大小。两表、五个业务索引、两个 TOAST 表和两个 TOAST 索引共 11 个对象全部在 HDD，两个普通 Serving view 无独立文件，不执行搬迁。

### 10.3 定义、权限和数据检查

- 13 个对象的 OID、owner、ACL、列、约束、索引/视图定义与隔离后基线一致；11 个存储对象的 main/fsm/vm 及总大小完全一致。七个索引均 valid/ready。
- 两个固定标的各最早、最近 3 行，共 12 行的计划字段与基线完全一致。指数批次和两表全部完成后分别读回检查，未以全表扫描、全量 hash 或全量导出代替计划样本。
- Raw 写入表及 Serving view 同名保留；未改业务源码、配置、DatasetDefinition、主键或索引定义，未部署、分区、回补或额外触发同步。不改变子系统边界和依赖矩阵。

### 10.4 性能状态与入口恢复

生产正式配置 `QUOTE_API_AUTH_REQUIRED=true`。浏览器正常登录会话的操作连接仍超时，无法可靠复用。已准备只访问四组计划参数的浏览器脚本 `post-migration-performance.js`，通过 `node --check` 语法检查，未运行；不制造 token、不关闭认证、不绕过正常入口。

用户随后明确选择“先恢复排程，性能验收稍后继续”。因此本轮不再尝试查询，下表不是性能失败记录，更不是验收通过。

| 计划迁后用例，截止 2026-10-14 | 本轮请求数 | 实际根数、日期、耗时、业务稳定性 |
| --- | ---: | --- |
| 指数 000001.SH，day，limit=300 | 0/20 | 未测 |
| 指数 000001.SH，day，limit=2000 | 0/20 | 未测 |
| 股票 000001.SZ，day，forward，limit=300 | 0/20 | 未测 |
| 股票 000001.SZ，day，forward，limit=2000 | 0/20 | 未测 |

用户通过正式后台恢复本次暂停的三条排程。00:27:16+08 只读确认 #2、#24、#32 均 active，#32 的绑定探测已重建为 #17（旧 ID 为 #16）。Web、scheduler、通用 worker 全程未因本次维护停止，最终均 active；未额外提交同步或自然运行观察任务。

### 10.5 最终水位、证据和剩余风险

00:27:16+08 根盘可用 59,727,851,520 B（约 55.63 GiB），HDD 可用 232,864,305,152 B（约 216.87 GiB），`pg_wal` 1,073,741,824 B；维护观察点均高于两盘 10 GiB 停止线。`df` 同时受 WAL 和其它运行活动影响，不用其短时差额宣称精确释放量。

本次证据目录为 `/private/tmp/factor-pro-full-hdd-20261016_001532/`：`baseline.json`、`samples-before.json`、七组 `step-N.sql/log`、`after-step-N.json`、`verified-step-N.json`、`samples-after-index.json`、`samples-after-all.json`、`physical-file-check.json`、`final-restored.json`、空间监控文本及 `execution-report.md`。记录不含密码、token 或连接串。

物理迁移、定义与样本检查、入口恢复已完成；唯一剩余验收为用户明确延期的四组共 80 次正常认证查询。独立备份依然未验证，极端磁盘或实例故障可能无法恢复的风险仍保留，本次未建设备份。本次文档提交记录上述执行事实，不把物理迁移写成性能验收已完成。
