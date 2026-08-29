# 生产 PostgreSQL 存储空间优化治理专项 v2

- 版本：v2
- 状态：P1-B0、P1-B1 与 P1-B2 已结案；`P1-B3-stk_auction_o` 已结案，`P1-B3-stk_auction_c-M0/M1/M2/M3a` 已通过并完成生产切换；M3b 待自然观察，下一开发项为 `moneyflow_ths` M0
- 更新时间：2026-08-29
- 范围：生产 PostgreSQL 小对象 SSD→HDD 迁移，以及无业务转换的 raw/core_serving 重复物理存储收口
- 不在范围：`stk_mins` 大分区迁移、删除 raw 源事实、修改 Tushare 请求语义、自动执行生产 DDL

## 0. 文档权威边界

1. 本文只承载 2026-08-23 起的新一轮审计、决策和执行计划，不向 v1 追加新批次。
2. [生产 PostgreSQL 存储空间优化治理专项 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v1.md)继续保留既有迁移和历史验收证据；v2 不修改或覆盖这些历史事实。
3. 一期全量候选的生产大小、任务和磁盘水位基线来自 2026-08-23；P1-B0 另记录 2026-08-24 的生产执行证据。任何后续批次都必须重新核验，不能复用旧快照作为执行授权。
4. 当前代码、测试、Alembic、生产 catalog 和有界生产对账决定现状。表名、Definition 中的 `layer_plan` 或历史文档不能单独证明两层数据等价。
5. 本文是专项方案，不是生产 DDL 授权。没有明确阶段授权时，不暂停任务、不改 schedule、不迁 relation、不删除物理表。

## 1. 结论

### 1.1 当前容量事实

2026-08-23 本轮最后一次只读复核：

| 文件系统 | 总容量 | 已用 | 可用 | 使用率 |
| --- | ---: | ---: | ---: | ---: |
| 根盘 `/dev/vda2`，挂载 `/` | 232,385,470,464 B | 218,692,431,872 B | 4,120,686,592 B，约 3.84 GiB | 99% |
| HDD `/dev/vdb`，挂载 `/data/disk` | 422,549,692,416 B | 61,247,283,200 B | 339,810,795,520 B，约 316.47 GiB | 16% |

同一时点没有超过 10 分钟的活动事务，但这是瞬时事实；执行前仍须重新检查开放 TaskRun、schedule、数据库锁、活动事务和文件系统水位。

2026-08-24 P1-B0 维护窗口开始前根盘精确可用空间为 4,801,044,480 B，验收后为 4,695,298,048 B。发布依赖、WAL 和运行噪声使文件系统净值减少 105,746,432 B；因此本专项只以 PostgreSQL catalog 证明本次 serving 物理 relation 释放 237,568 B，不把短时 `df` 差额当作净收益。

2026-08-24 P1-B1 首项 `moneyflow_ind_ths` 维护窗口开始前根盘可用 4,461,560 KiB，验收后 4,485,480 KiB；同样只以 PostgreSQL catalog 证明原 serving heap/index 合计释放 9,756,672 B，不把 `df` 瞬时变化当作精确收益。第二项 `moneyflow_cnt_ths` 的原 serving 物理基线为 43,958,272 B，切换后 view 为 0 B。2026-08-26 `margin` M3a 再释放原 serving 物理 relation 344,064 B；四项累计已释放 54,296,576 B。部署依赖、WAL 和运行噪声仍会使 `df` 瞬时变化与 catalog 毛释放量不一致。

2026-08-24 运营为缓解根盘容量压力，将 Prod SSD 名义容量扩充到 270 GB；18:07+08 只读复核的实际文件系统容量如下：

| 文件系统 | 总容量 | 已用 | 可用 | 使用率 |
| --- | ---: | ---: | ---: | ---: |
| 根盘 `/dev/vda2`，挂载 `/` | 285,230,424,064 B，约 265.66 GiB | 218,025,771,008 B | 55,484,956,672 B，约 51.68 GiB | 80% |
| HDD `/dev/vdb`，挂载 `/data/disk` | 422,549,692,416 B，约 393.53 GiB | 61,256,343,552 B | 339,801,735,168 B，约 316.46 GiB | 16% |

本次扩容是应急容量缓冲，不是本专项迁移收益，也不改变逐表独立维护窗口、完整对账和停止条件。新增成本约人民币 1,000 元为运营反馈口径，不是数据库可审计指标；后续仍须优先消除重复物理存储，避免把扩容当作治理完成。

2026-08-26 `P1-GATE-SSE-M1` 开始前再次只读复核：根盘约 266 GiB 总量、206 GiB 已用、50 GiB 可用、81%，HDD 约 394 GiB 总量、62 GiB 已用、312 GiB 可用、17%；生产与本地 Alembic head 均为 `20260825_000151`，没有 queued/running/canceling TaskRun。`margin` raw/serving 仍是两张 `pg_default` 物理表，大小分别为 360,448 B/344,064 B，均为 1,149 行和 1,149 个唯一身份，9 个业务字段全量双向差集为 0。该快照只用于 M1 上下文校准，不授权生产切换。

2026-08-27 `moneyflow_ind_dc` M0 时再次只读复核：根盘总量 285,230,424,064 B、可用 52,376,059,904 B（48.78 GiB）、使用率 81%；HDD 可用 334,694,993,920 B（311.71 GiB）、使用率 17%。该快照证明当前有充足的小表 migration 缓冲，但仍不替代 M3a 的实时任务、锁、WAL 与水位门禁。

2026-08-29 `stk_auction_c` M3a 维护前后根盘可用空间分别为 51,424,526,336 B 与 51,782,873,088 B，使用率均为 82%。依赖安装、WAL 与运行噪声会影响 `df`，本项只以 PostgreSQL catalog 确认原 Serving 物理 relation 的 390,266,880 B 已释放。连同此前八项，一期已确认的 catalog 毛释放量累计为 **1,299,185,664 B（1,239.00 MiB）**。

### 1.2 本轮应拆成两条独立执行线

1. **Track A：小对象 tablespace 迁移。** 不改数据模型和查询契约，只把独立、较小、当前位于 `pg_default` 的物理对象迁入 `gs_raw_cold_hdd`。在 raw 直出一期口径固定后，原六张 dormant raw 候选中只有 `fund_adj`、`ths_daily` 仍保留为后续候选；`stk_auction_o/stk_auction_c/moneyflow_ths/stk_limit` 已进入 raw 直出一期，raw 必须继续留 SSD，不能重复计算为 Track A 收益。
2. **Track B：raw-backed serving view 去重。** 对确实没有业务转换、行过滤、聚合或版本选择的 raw/core_serving 双写数据集，只保留 raw 物理表，把原 core_serving 同名物理表替换为读取 raw 的普通 view。26 组严格静态候选的 core/serving 物理表当前合计约 **13.95 GiB**，但这只是毛收益，不是已批准删除量。

两条执行线不能混为一次操作：

- Track A 改变物理介质，不改变 relation 类型；主要风险是 `ACCESS EXCLUSIVE` 锁、WAL 和 HDD 性能。
- Track B 改变 Definition 写入契约和 relation 类型；主要风险是数据漂移、旁路写入、索引退化、依赖对象和发布顺序。
- 某个 raw 表如果将来成为 serving view 的直接底座，是否仍适合放 HDD 必须重新评估。不能先把 raw 迁 HDD，再默认其用户查询延迟没有变化。

### 1.3 当前最合理的先后顺序

1. 本轮优先推进 Track B raw 直出一期；`moneyflow_mkt_dc` 契约试点已完成生产验收，证明小表的 Definition、迁移、拒写、连接池回收、真实查询和 TaskRun 闭环可行。该试点释放空间很小，主要价值是验证改造链路。
2. 后续严格按第 4.5 节固定批次推进；每个数据集仍是独立 revision、独立维护窗口和独立验收，不允许按内部批次一次性 drop 多表。夜间自然任务统一登记、集中按目标节点验收；尚未触发或尚未核验不是失败，不阻塞后项 M1/M2/M3a，只有已发现且未解决的共享运行链异常才形成生产切换门禁。
3. 一期 12 张 raw 物理表全部继续位于 SSD，避免普通业务查询和 Lake 导出直接转为机械盘 I/O。
4. Track A 暂缓。若一期释放空间仍不足，再单独评审 `equity_daily_bar_light_p1990` 微迁移、`p1991`～`p1999` 以及未进入一期的 `fund_adj/ths_daily`；不得把一期 raw 表重新纳入 Track A。
5. 禁止直接从 4 GiB 级 `daily_basic` 或 `dc_member` 开始。

## 2. 审计方法与代码事实

### 2.1 当前双写和 raw 直出契约

当前 `raw_core_upsert` 路径会把同一 `NormalizedBatch` 分别按 raw DAO 和 core DAO 的模型进行日期类型归一化，然后在同一业务事务中分别 `bulk_upsert`：

- `src/foundation/ingestion/writer.py::DatasetWriter.write`
- `src/foundation/ingestion/writer.py::DatasetWriter._write_raw_and_core`

这证明“新同步批次的输入来源相同”，但不能证明生产历史数据始终完全相同，原因包括：

1. 两层可能采用不同主键、唯一键、空值约束或冲突策略；
2. 历史迁移、修复脚本或旁路写入可能只改其中一层；
3. 两层索引可能不同；
4. 老数据可能在当前 Definition 建立前已经发生漂移；
5. core/serving 可能保留派生列、行筛选、来源选择或冲突消解结果。

仓库已有的正确 raw 直出模式是：

```text
source
  -> raw_tushare.<dataset>                 # 唯一物理事实表，writer 只写这里
  -> core_serving.<existing_contract_name> # 普通只读 view，不复制数据
```

Definition 固定为：

- `write_path=raw_only_upsert`
- `delivery_mode=raw_with_serving_view`
- `layer_plan=raw->serving_view`
- `target_table=raw_tushare.<dataset>`
- `raw_table=raw_tushare.<dataset>`
- `serving_table=core_serving.<existing_name>`
- `core_dao_name=raw_dao_name`，writer 不再解析或写 serving DAO

既有可复用证据：

- `DatasetWriter._write_raw_only_upsert()`；
- `tests/test_dataset_writer_raw_serving_views.py`；
- `alembic/versions/20260803_000124_make_cyq_perf_nineturn_raw_views.py`；
- `cyq_perf`、`stk_nineturn`、`cyq_chips`、`stk_factor_pro`、`idx_factor_pro` 等当前 raw-backed view 数据集。

### 2.2 CodeGraph 与消费者审计范围

本轮使用仓库根 CodeGraph 当前索引审计：

1. `DatasetWriter` 及 `raw_core_upsert/raw_only_upsert` 分支；
2. `DAOFactory` raw/core DAO 注册；
3. 26 个严格静态候选的 ORM 模型；
4. `src/biz`、`src/ops`、`qtf`、`lake_console` 的直接模型和 relation 消费者；
5. 代表性高影响对象 `EquityDailyBasic`、`DcMember`、`IndexWeight`、`MoneyflowDc`；
6. 迁移和契约测试消费者。

关键发现：

1. 保留原 core_serving relation 名并替换为 view，可以让大多数只读 ORM/API 消费者保持 SQL 合同不变；不能让业务层直接改查 `raw_tushare`。
2. `daily_basic` 的物理表被 `dm.equity_daily_snapshot` materialized view 依赖，不能套用普通 `DROP TABLE` + `CREATE VIEW` 迁移；必须单独设计依赖重建和刷新门禁。
3. `stock_st` 的 `StockStMissingDateRepairService` 会直接 `session.add_all(raw_rows)` 和 `session.add_all(core_rows)`，属于旁路双写；在该服务改为只写 raw 或正式退场前，`stock_st` 不得改为 raw 直出。
4. `ServingPublishService` 仍具备向部分 target DAO 执行 `upsert_many()` 的通用能力。虽然当前没有发现对本轮多数候选的生产调用，实施时仍必须按每个 dataset_key 清零所有直接写消费者，不能只改主 writer。

### 2.3 生产只读审计范围

本轮生产数据库只读核验只访问：

- `pg_catalog.pg_class/pg_namespace/pg_tablespace/pg_index/pg_depend/pg_rewrite`；
- `pg_stat_activity`；
- `ops.task_run`；
- `ops.schedule`；
- 12 组一期 raw/serving 表的 relation、字段、索引、owner/ACL、依赖、trigger/RLS、精确行数、大小与任务/schedule；
- 2026-08-23 初始审计时仅 `moneyflow_mkt_dc`、`margin` 完成全部业务字段集合对账；2026-08-24 P1-B1-M0 又完成 `moneyflow_ind_ths`、`moneyflow_cnt_ths` 的逐月全字段对账。

以上描述的是 2026-08-23 的初始只读审计：当时没有执行生产 DDL、DML、migration、TaskRun、Tushare 请求或无界全量大表 hash。精确 `count(*)` 只证明行数一致，不把它当作内容等价证据；其余大表仍只使用 catalog 估算行数和 relation 原始字节。

### 2.4 P1-B0 生产验收增量事实

2026-08-24 经独立授权，P1-B0 已完成生产只读预检、维护窗口、部署、migration、连接池回收、真实查询与最小 TaskRun 验收：

1. 最终切换前 raw/serving 均为 812 行、812 个唯一交易日，15 个业务字段双向 `EXCEPT ALL` 为 0；无开放 TaskRun、schedule、目标锁、长事务或 catalog 依赖阻塞；
2. migration 首次因生产最小权限角色不能设置 `temp_file_limit` 而在 DDL 前安全失败。最终实现取消特权参数，改用持锁后两层各 5,000 行硬上限和 `work_mem=16MB`，并在非超级用户隔离实例验证 812 行成功、5,001 行原子拒绝；
3. revision `20260824_000146` 已应用，`core_serving.market_moneyflow_dc` 为普通 view 且物理大小 0；raw 保持物理表和有效索引，raw/view 结果与审计时间投影一致；
4. owner、既有 raw SELECT 权限和 comment 状态保持不变；serving INSERT/UPDATE/DELETE 均以 SQLSTATE `55000` 拒绝；
5. 点查、最大日期和 90 日范围查询均下推 raw 等价索引，生产两个实际 Biz 查询服务中位数分别为 3.998 ms 和 12.153 ms，均无查询异常；
6. TaskRun `9210` 以 1 个日期 unit 完成：读取 1、归一化 1、写入 1、拒绝 0、raw/view 各 1，view 即时可见；全部服务恢复 active，无 schedule 被创建或重建；
7. 生产部署代码为 `11dbe4c6`，最小权限迁移修正为 `e15483a4`；P1-B0 catalog 毛释放量为 237,568 B。

### 2.5 P1-B1 M0 与行业/概念 M1/M2 增量事实

2026-08-24 P1-B1 三项生产只读审计确认：

1. 行业 42,030 行、概念 181,560 行、margin 1,146 行，raw/serving 行数和主键身份数逐项一致；行业与概念覆盖 `2024-09-10..2026-08-21`，margin 覆盖 `2025-01-02..2026-08-21`；
2. 行业与概念按 24 个自然月比较全部业务字段，每个窗口双向差集均为 0；margin 全量双向差集为 0；
3. 三张 serving 表均无 inheritance、外键、用户 trigger、列 ACL、RLS、依赖 view/function、rewrite rule、扩展统计、security label 或 publication；raw 的等价索引均 valid、ready 且位于 `pg_default`；
4. `moneyflow_mkt_dc`、`moneyflow_ind_ths` 和 `moneyflow_cnt_ths` 均由 active 的 `daily_moneyflow_maintenance` 工作流覆盖；`margin` 保留 active 的 `09:00..09:30` 固定源端 probe。B0 当时只确认“没有创建或重建 schedule”，却误写成该数据集没有自动入口；后续必须从 workflow step 反查真实覆盖关系；
5. 单月最大行数实测为行业 2,070、概念 9,070、margin 69；对应 migration 上限分别固定为 5,000/月、20,000/月和 5,000/全表，禁止直接复用 B0 的全表小表口径；
6. 首项行业 revision `20260824_000147` 已完成 M1 编码和离线验证，只修改行业 Definition storage、raw ORM 索引 metadata、独立 migration 与测试；它复用 B0 的稳定数据库拒写函数，但不新增共享 Python 框架；
7. M2 已在仅 Unix socket 可访问的 PostgreSQL 18.4 隔离实例，以非超级用户从 revision 146 成功升到 147。42,030 行受控样本的 raw/view 行数、身份、12 个业务字段与审计时间投影完全一致，view 物理大小为 0；owner、comments、PUBLIC/普通/带授权选项 SELECT 和 raw reader 权限完整恢复；
8. 三类 serving DML 均以 SQLSTATE `55000` 拒绝；正式 writer 连续写入只命中 raw，view 同事务即时可见且回滚后恢复。三类代表查询均下推 raw 等价索引，buffer 未出现数量级变化；隔离时延不替代生产 M3 门禁；
9. 单月 5,001 行在 DDL 前 fail-closed，revision、OID、旧表与数据不变；切换中于 DROP 后注入故障也完整恢复旧表 OID、42,030 行、索引、权限和注释。隔离实例已经停止并移入废纸篓；本阶段未连接 Prod、调用 Tushare、创建 TaskRun 或修改 schedule。
10. 第二项 `moneyflow_cnt_ths` M1 已完成：Definition 仅切换 storage 为 raw-only/view，raw ORM 补齐两个既有索引 metadata，独立 revision `20260824_000148` 连接真实 head 147；迁移按自然月、每层 20,000 行上限进行完整字段对账，复用既有拒写函数并创建概念 view 的独立 trigger。离线 SQL、Definition/planner/filter、writer、ORM、freshness、ServingPublish 旁路和 migration 正反向测试通过；未连接 PostgreSQL、未部署、未应用 migration。
11. `moneyflow_cnt_ths` M2 已在仅 Unix socket 可访问的 PostgreSQL 18.4 隔离实例，以非超级用户从 revision 147 成功升到 148。181,560 行受控样本的 raw/view 行数、身份、12 个业务字段和审计时间投影完全一致；owner、comments、PUBLIC/普通/带授权选项 SELECT 和 raw reader 权限完整恢复，三类 serving DML 均以 SQLSTATE `55000` 拒绝；
12. 正式 writer 只写 raw 且 view 同事务即时可见，回滚无残留；三类代表查询继续下推 raw 的日期、实体日期和主键索引。单月 20,001 行在 DDL 前 fail-closed，旧版本、OID、表和数据不变；DROP 后注入故障也完整恢复 181,560 行旧表、索引、权限和注释。隔离实例已停止并可恢复地移入废纸篓；本阶段未连接 Prod、调用 Tushare、部署或创建任务。

### 2.6 P1-B1 首项 `moneyflow_ind_ths` M3a 增量事实

2026-08-24 经独立授权，行业资金流已完成生产只读预检、维护窗口、部署、revision 147、连接池回收、真实查询计划与最小 TaskRun 验收：

1. 最终切换前 raw/serving 均为 42,030 行和 42,030 个唯一身份，日期范围 `2024-09-10..2026-08-21`、单月最大 2,070 行，12 个业务字段全量双向差集为 0；无开放 TaskRun、长事务、目标锁或 catalog 阻塞；
2. `daily_moneyflow_maintenance` schedule #4 通过正式服务暂停，scheduler 与 generic worker 停止后才部署。commit `60f2ce28` 只安装后端、应用 migration，不构建前端、不 seed、不提前启动执行服务；
3. migration `20260824_000146 -> 20260824_000147` 一次成功；raw 保持 `pg_default` 物理表与 3 个有效索引，`core_serving.industry_moneyflow_ths` 变为 0 B 普通 view，catalog 证明释放原 serving heap/index 9,756,672 B；
4. raw/view 仍为 42,030 行，业务字段和 `fetched_at -> created_at/updated_at` 投影差异均为 0；owner、原无 serving 非 owner grant/comment 的状态保持不变。view 的 INSERT/UPDATE/DELETE 均以 SQLSTATE `55000` 拒绝且 raw 行数不变；
5. 日期点查、行业代码区间、最大日期均下推 raw 等价索引，切换前后执行时间分别为 `0.244/0.234 ms`、`0.880/0.959 ms`、`0.028/0.024 ms`，没有超过 20% 阻断线；
6. TaskRun `9217` 对 `2026-08-21` 执行 1 个 unit：1 页读取 90、归一化 90、写入 90、拒绝 0、去重 0、短页结束且 0 重试。写后该日 raw/view 均为 90 行，全表仍为 42,030 行，90 行均由本次任务刷新；
7. Web 与相关 Ops 连接池已回收，全部服务恢复 active；schedule #4 原样恢复为 active，下一次仍为 `2026-08-24 20:00+08`，pause/resume 均保留配置审计记录，最终开放 TaskRun 为 0。该时点首个正常工作流尚未到触发时间，因此 `P1-B1-industry-M3b` 已登记到一期 LLD 的统一夜间验收台账；待核验本身不阻塞 `moneyflow_cnt_ths` 的 M1/M2/M3a。

### 2.7 P1-B1 第二项 `moneyflow_cnt_ths` M3a 增量事实

2026-08-24 经独立授权，概念资金流已完成生产切换后的静态合同、真实查询、连接池、最小 TaskRun 与恢复验收；同时发现并如实保留一项发布顺序偏差：运营使用标准部署后，revision 148 已在正式暂停 schedule/worker 之前自动应用。本轮没有重复 migration，也不能补造切换前门禁证据。后续 M3a 必须先暂停自动入口与执行 worker，再使用不自动迁移的部署模式安装代码，并在维护窗口内显式应用 migration。

1. 部署 commit 为 `7450423c`，发现时 Alembic 已为 `20260824_000148`；无开放 TaskRun、长事务和目标锁后，schedule #4 通过正式服务暂停，scheduler 与 generic worker 停止，后续验收在受控窗口内完成。
2. raw 保持 `pg_default` 物理表和三个有效索引，serving 为 0 B 普通 view；raw/view 均为 181,560 行、181,560 个唯一身份，日期范围 `2024-09-10..2026-08-21`、单月最大 9,070 行，12 个业务字段与审计时间投影差异均为 0。
3. owner、raw reader 权限和原有 serving metadata 状态保持不变；拒写函数与概念独立 trigger 符合契约，INSERT/UPDATE/DELETE 均以 SQLSTATE `55000` 失败且事务回滚后数据不变。
4. 日期点查、概念代码日期范围和最大日期查询分别下推 raw 日期索引、`(ts_code, trade_date)` 索引和主键，执行时间为 `0.182/1.069/0.036 ms`，没有顺序扫描或临时文件。
5. Web、date-completeness 和 task-completion 连接池完成回收，健康端点均为 200；最小 TaskRun `9224` 对 `2026-08-21` 执行 1 个 point unit，1 页读取/保存 387、短页结束、0 重试、0 reject、0 去重、0 issue。写后 raw/view 该日均为 387 行且字段一致，全表仍为 181,560 行。
6. schedule #4 原样恢复 active，cron `0 20 * * 1-5`、时区 `Asia/Shanghai`、下一次仍为 `2026-08-24 20:00+08`，config revision 97/98 记录 pause/resume；最终相关服务 active、健康端点 200、开放 TaskRun 0。行业与概念 M3b 均进入一期 LLD 的统一夜间验收台账，待验收本身不阻塞 `margin` 的独立 M1/M2。

### 2.8 2026-08-24 当日暂停点只读复核

18:07+08 对生产进行了有界只读复核；本次没有执行 migration、DDL、DML、部署、TaskRun 创建或 Tushare 请求。当前事实为：

| 数据集 | raw relation | serving relation | raw/view 行数与身份数 | 日期范围 | 阶段状态 |
| --- | --- | --- | ---: | --- | --- |
| `moneyflow_mkt_dc` | 物理表，`pg_default`，262,144 B | 普通 view，0 B，直接读取 raw | 812 / 812 | `2023-04-17..2026-08-21` | P1-B0-M3 已完成 |
| `moneyflow_ind_ths` | 物理表，`pg_default`，10,657,792 B | 普通 view，0 B，直接读取 raw | 42,030 / 42,030 | `2024-09-10..2026-08-21` | P1-B1-industry-M3a/M3b 已完成 |
| `moneyflow_cnt_ths` | 物理表，`pg_default`，47,153,152 B | 普通 view，0 B，直接读取 raw | 181,560 / 181,560 | `2024-09-10..2026-08-21` | P1-B1-concept-M3a/M3b 已完成 |
| `margin` | 物理表，`pg_default`，352,256 B | 物理表，`pg_default`，335,872 B | 1,146 / 1,146 | `2025-01-02..2026-08-21` | 仅 M0 等价审计完成；尚未完成 M1 |

三张已切换 view 的定义均为显式字段投影并直接读取对应 raw 表；各 view 当前行数、业务身份数和日期范围与 raw 一致，且分别存在 enabled 的 `INSTEAD OF INSERT/UPDATE/DELETE` 拒写 trigger。生产 Alembic 仍为 `20260824_000148`，生产代码检出为 `bbcff0e7`，二者覆盖市场、行业和概念三项已完成切换。

当时 schedule #4 仍为 active，下一次触发为 `2026-08-24 20:00+08`，当天尚无该 schedule 创建的 TaskRun，因此行业与概念 M3b 只能标记为“尚未到触发时刻”，不能提前标完成或失败。生产另有两个与本专项无关的开放任务：TaskRun `9229`（`stk_mins`，17,368/29,450 unit）和 `9230`（`index_mins`，2,200/2,650 unit），均为 running；所以当日不再进入任何生产维护窗口。

本地 `dev-interface` 已提交 pure-probe 时间字段收口 commit `6221f5d9`，对应 migration `20260824_000150`，但尚未推送或部署；其前面还有未在生产应用的 revision `20260824_000149`。因此生产 schedule #33 仍保留历史 `cron_expr/next_run_at` 字段，运行时仍按 probe rule 工作。该事实不属于 `margin` raw 直出 M1 完成项；未来任何生产 migration 前必须重新核对“生产 148、本地 150+”的累计 revision 链，禁止把 149/150 与 margin relation 切换无审计地捆绑自动应用。

### 2.9 2026-08-24 夜间自然工作流验收与迁移锁事件

18:07 暂停点是历史快照。随后生产完成 revision `20260824_000149/000150`，当前 Alembic 为 `20260824_000150`，schedule #33 的 pure-probe 时间字段已归一化，检查约束有效。20:00 的 `daily_moneyflow_maintenance` 因本次部署迁移锁等待，在 scheduler 恢复后于 `20:07:29+08` 创建 schedule #4 TaskRun `9244`；父任务于 `20:08:25` 开始、`20:08:56` 结束，状态 `success`，7/7 workflow step 完成、0 失败、读取/保存 18,267、reject 0、去重 0。

本轮验收只查询既有 TaskRun、节点和目标日期数据，没有创建任务、额外请求 Tushare 或写数据库。三个已直出节点的结果如下：

| 完整阶段编号 | 数据集/node | 时间输入 | 读取/保存 | reject/去重 | 分页 | raw/view 与内容对账 | 结论 |
| --- | --- | --- | ---: | ---: | --- | --- | --- |
| `P1-B0-market-M3b` | `moneyflow_mkt_dc` | point `2026-08-24` | 1 / 1 | 0 / 0 | 1 页、短页结束、0 重试、未截断 | 1/1 行、1/1 身份；15 个业务字段双向差集 0；审计时间投影差异 0 | 补充自然运行数据链通过 |
| `P1-B1-industry-M3b` | `moneyflow_ind_ths` | point `2026-08-24` | 90 / 90 | 0 / 0 | 1 页、短页结束、0 重试、未截断 | 90/90 行、90/90 身份；12 个业务字段双向差集 0；空 `ts_code` 与审计时间投影差异均为 0 | 通过 |
| `P1-B1-concept-M3b` | `moneyflow_cnt_ths` | point `2026-08-24` | 387 / 387 | 0 / 0 | 1 页、短页结束、0 重试、未截断 | 387/387 行、387/387 身份；12 个业务字段双向差集 0；空 `ts_code` 与审计时间投影差异均为 0 | 通过 |

该证据证明 `schedule -> workflow -> source -> raw-only writer -> serving view` 的真实运行链路正常。TaskRun 原定 20:00，但实际在 20:07 创建，因此本轮不能作为 scheduler 准点性证据；延迟由部署事件导致，不归因为三个数据集的直出契约。

部署卡顿的直接阻塞者是 Web 的 `/api/v1/ops/schedules/stream` SSE：它在无限流生命周期内复用同一 SQLAlchemy Session，每两秒查询一次 schedule/task 状态，却不结束事务。数据库 PID `37355` 从 `19:45:59` 起 `idle in transaction` 并持有 `ops.schedule` 的 `AccessShareLock`；migration PID `38772` 在添加 pure-probe check constraint 时等待 `AccessExclusiveLock`，scheduler PID `37410` 又排在 migration 后。生产 `lock_timeout` 与 `idle_in_transaction_session_timeout` 均为 0，所以连接若不释放会无限等待。连接结束后 migration 正常提交，服务和健康端点恢复。

这是已观察的共享运行链问题。2026-08-26 已完成 `P1-GATE-SSE-M1`：SSE 鉴权事务在返回流前结束，每轮轮询改用独立短会话并在输出/休眠前回滚关闭；PostgreSQL 在线 Alembic migration 在 migration transaction 内统一设置 `SET LOCAL lock_timeout='15s'`，且不修改全局数据库参数。定向自动化测试已覆盖事务成功/失败、会话隔离、event/ping 兼容和 online/offline Alembic 分支。

本段记录 M1 完成时的阶段边界：当时 M1 只证明代码合同且尚未部署，仍须隔离 PostgreSQL M2 与生产 M3；后续第 2.10、2.11 节已经记录两项门禁的实际闭环证据，不能再把这段历史边界误读为当前状态。

### 2.10 2026-08-26 `P1-GATE-SSE-M2` 隔离验收

M2 在仅 Unix socket 可访问的 PostgreSQL 18.4 临时实例，以非超级用户和独立 env 完成；数据库、用户、server address、端口、data directory 与 HDD tablespace 六项身份均已核对，没有连接 Prod、请求 Tushare、创建 TaskRun、部署服务或修改生产 schedule。

真实 HTTP SSE 跨越多个 2 秒周期返回 2 个数据事件和 2 个 ping；216 次数据库采样只捕获 1 次 0.997ms 的查询结束到 rollback 瞬时窗口，连续采样 1 次，没有 idle relation lock，流结束后 `idle in transaction=0`。独立连接持有 `ops.schedule AccessShareLock` 时，revision 150 于 15.815 秒 lock timeout 失败；revision 149、legacy probe 字段、物理表类型和约束不存在状态全部原子保留。释放锁后 migration 成功，probe 字段归一化、约束 validated，违规写入以 SQLSTATE `23514` 拒绝并回滚，新会话 `lock_timeout=0`。最终升级到当前 head 151 成功，167 项回归通过。

M2 据此通过；当时共享生产门禁只剩独立授权的 M3。生产结论见下述 M3 证据。

### 2.11 2026-08-26 `P1-GATE-SSE-M3` 生产验收

M3 于 `2026-08-26 11:07..11:14+08` 完成。执行前生产 Alembic 为 `20260825_000151`，开放 TaskRun、长期事务、锁等待和目标 idle relation lock 均为 0；schedule #33 与 probe rule #12 保持既有 pure-probe 契约，根盘约 51 GiB 可用，相关服务均为 active。

本轮只把包含 SSE/Alembic 修复的 `origin/dev-interface` commit `99e1148f` 部署到 Web，未执行数据库升级、前端构建、seed、unit 同步、worker/scheduler 重启、TaskRun、schedule/probe 修改或 Tushare 请求。真实生产 SSE 返回 HTTP 200、1 个 schedule event 和 3 个 ping；302 次数据库采样中，目标 SSE `idle in transaction`、跨采样事务、idle relation lock 和锁等待均为 0，断流后也无残留。

生产已经位于 head，因此没有倒退 revision 或重放业务 DDL。运行时配置先证明连接的是 `/etc/goldenshare/web.env` 指向的正式库；真实 `alembic upgrade head` no-op 前后均为 revision 151。独立 advisory transaction lock 冲突下，`SET LOCAL lock_timeout='15s'` 的竞争会话于 15.11 秒明确失败，释放持锁会话后残留 advisory lock、长事务和锁等待均为 0。生产 M3 验证有界等待，revision 150 的真实 migration 失败原子回滚继续以 M2 证据为准，不为重复证明在生产制造降级或临时 revision。

部署现场另确认：`goldenshare` 运行用户缺少标准 `--platform-only` 所要求的无密码 `systemctl` 权限。标准入口会在拉代码前失败，因此本轮由该用户在部署锁内完成拉取和安装，再由现有管理账号只重启 Web。最终远端工作区干净、全部相关服务 active、健康端点正常、开放 TaskRun 和数据库异常状态均为 0。该权限边界需保留为发布工具事实，但不影响本轮最小发布和运行合同结论。

`P1-GATE-SSE-M3` 据此通过，共享生产门禁解除；后续数据集仍须逐项完成自己的 M1/M2/M3a/M3b，不能把共享 gate 通过解释为自动授权生产切换。

### 2.12 2026-08-26 `P1-B1-margin-M1` 编码事实

`margin` 已完成独立 M1。Definition 仅把写入合同从 raw/core 双写改为 `raw_tushare.margin` 的 `raw_only_upsert`，原 `core_serving.equity_margin` 名称由后续 migration 切换为 raw-backed view；9 个 source fields、交易日 point/range、SSE/SZSE/BSE 三交易所 fan-out、4,000 行分页、发布时机和固定源端 probe 均未改变。

独立 revision `20260826_000152` 接编码时真实 head `20260825_000151`，只处理 margin。它在持有 raw/serving `SHARE` 锁时，对不超过 5,000 行的两层全表执行 9 个业务字段双向差集和复合身份唯一性核对；raw heap、主键与两个二级索引必须继续位于 `pg_default`。通过后才把 serving 物理表原子替换为显式列 view，恢复 owner、SELECT grants 和 comments，并复用现有拒写函数挂 margin 独立 trigger。migration 使用 15 秒锁等待、120 秒语句上限和 16 MB `work_mem`，禁止 `temp_file_limit`、`CASCADE`、raw 删除、共享函数重建和自动 downgrade。

M1 自动化测试覆盖 Definition/plan/filter、source fields/分页、raw-only writer、freshness、ORM/索引、ServingPublish 无旁路、migration 有界资源/原子顺序/显式投影/共享函数前置和离线 SQL 渲染；Ops Catalog、固定 probe、schedule capability、definition lint 与 runtime registry 回归通过。M1 没有连接数据库、请求 Tushare、部署、应用 migration、创建 TaskRun 或修改 schedule/probe。生产 relation 仍保持 M0 时的两张物理表；下一阶段是另行授权的隔离 PostgreSQL M2，而不是直接生产切换。

### 2.13 2026-08-26 `P1-B1-margin-M2` 隔离验证事实

M2 已在本轮创建的仅 Unix socket PostgreSQL 18.4 隔离实例完成，migration 用户为非超级用户。Alembic 在同一进程内先校验独立 env、数据库、用户、socket、端口、网络监听、恢复状态和超级用户属性；错误数据库名的负向门禁在 DDL 前失败，revision 保持 151。整个阶段未连接 Prod、请求 Tushare、部署、创建 TaskRun 或修改 schedule/probe。

成功路径把 raw/serving 各 1,149 行、1,149 个唯一身份从 revision 151 升至 152；9 个业务字段、日期范围和审计时间投影一致。raw OID、主键、两个二级索引及 `pg_default` placement 不变，serving 从 311,296 B 物理表变为 0 B 普通 view；owner、comments、PUBLIC/普通/带授权选项 SELECT 和共享拒写函数权限合同完整恢复。三类 serving DML 均以 SQLSTATE `55000` 拒绝，raw 的三类 DML 与正式 `DatasetWriter` upsert 均能由 view 在同一事务即时反映，回滚后无残留。

日期点查、交易所日期范围、最大日期和交易所复合索引查询的结果与成本前后一致并下推 raw 索引，临时块为 0。5,001 行验证库在 DDL 前以 `cap=5000` fail-closed，revision、relation 和 trigger 不变；在真实 switch SQL 完成后注入失败的验证库，事务回滚后 revision、两表 OID/类型、六个索引、ACL、comments、行数与 trigger 状态均与执行前一致。临时实例的 HDD tablespace 只用于验证边界，margin 目标对象均未落入 HDD，WAL 保持实例默认目录；三个库结束前无未结束业务事务，隔离实例随后停止并移入本机废纸篓。

M2 已关闭 margin 的隔离数据库门禁，但不改变生产 relation。下一阶段只能是单独授权的 `P1-B1-margin-M3a`；必须实时复核 Prod 身份、head、任务、锁、磁盘、schedule #33/probe rule 和服务状态后，才能进入维护窗口。自然 probe 数据链继续作为独立的 `P1-B1-margin-M3b` 备案验收。

### 2.14 2026-08-26 `P1-B1-margin-M3a` 生产事实

M3a 于 `13:33..13:45+08` 完成。切换前生产为 PostgreSQL 16.13、revision 151、远端 commit `99e1148f`；开放任务、目标等待锁和超过 5 分钟事务均为 0。raw/serving 都是 `pg_default` 物理表，各 1,152 行和 1,152 个唯一身份，日期范围 `2025-01-02..2026-08-25`，9 个业务字段双向差异为 0；raw/serving 大小分别为 360,448 B/344,064 B。

schedule #33 原为 active pure-probe，rule #12 保持固定 `09:00..09:30` 合同。通过正式服务暂停后 rule 被删除、config revision `103` 记录 paused；开放任务为 0 后只停止通用 worker，并在维护窗口再次完成同一组全字段对账。远端只通过 `--maintenance-migration` 快进到 commit `03803f43`、安装后端并应用 revision 152；构建、seed、unit 同步和服务重启均未混入 migration。

切换后 raw OID 不变、heap/主键/二级索引继续位于 `pg_default`，serving 成为 0 B 普通 view；raw/view 仍为 1,152 行，业务差异与 `fetched_at -> created_at/updated_at` 投影差异均为 0。owner/ACL、raw `lake_raw_reader` 权限和共享拒写函数合同不变；三类 view DML 均以 SQLSTATE `55000` 拒绝。三组结果 hash 前后一致，四类代表查询下推 raw 等价索引，total cost 变化均低于 4%，没有不可解释的 buffer 或排序放大。

Web、scheduler、date-completeness 和 task-completion 连接池按实际消费面回收；QTF、Biz、DG 和分钟 worker未发现该 relation 直接消费，不做无关重启。通用 worker启动后，正式 TaskRun `9468` 对 `2026-08-25` 执行 SSE/SZSE/BSE 三个 unit：`3/3/0`，3 页均短页结束，读取/归一化/保存 `3/3/3`、重试/reject/去重/issue 均为 0。目标日 raw/view 各 3 行，全表仍为 1,152 行，3 行刷新时间命中本次任务，业务与审计投影差异为 0。

任务完成后通过正式服务恢复 schedule #33，config revision `104` 记录 resumed，生成唯一 active rule #14；其 source、窗口、间隔、每日上限、condition 和 action 与固定合同一致，`cron_expr/next_run_at` 继续为空。最终 commit `03803f43`、revision 152、所有相关服务 active、健康端点正常，开放任务、长事务和等待锁均为 0。catalog 精确释放 344,064 B；根盘 `df` 因部署/WAL 从 54,220,095,488 B 可用变为 54,199,353,344 B，不作为净收益计算。

M3a 已通过；在该阶段结束时，M3b 登记为下一有效 `2026-08-27 09:00..09:30+08` 自然 probe 只读验收。本阶段没有额外触发 probe 或重复源端请求；该待验收项已由下节记录的自然 TaskRun `9573` 关闭。

### 2.15 2026-08-27 `P1-B1-margin-M3b` 自然 probe 结案事实

本轮只读审计没有人工触发 probe、创建 TaskRun 或重复请求 Tushare。schedule #33 保持 active pure-probe，`cron_expr/next_run_at` 均为空；唯一 active rule #14 保持 `09:00..09:30+08`、间隔 300 秒、每日最多 1 次、condition `remote_margin_ready` 和 action `margin.maintain` 固定合同。

probe log `3674` 于 `09:00:01+08` 自然命中 `2026-08-26`，3 次有界源端样本分别命中 SSE/SZSE/BSE、无缺失交易所，创建唯一 TaskRun `9573`。当日该 schedule 只有 1 条 probe log、1 次命中和 1 个 TaskRun。任务 success、unit `3/3/0`，读取/归一化/保存/reject/去重为 `3/3/3/0/0`；node `15322` 的分页为 3 unit、3 页、0 重试、3 个短页、最大 1 页/unit、未截断，reject reason 与 issue 均为空。

目标日 raw/view 各 3 行和 SSE/SZSE/BSE 三个身份，全字段双向差异为 0；3 条 raw 行的 `fetched_at` 均命中任务执行窗口。全表 raw/view 各 1,155 行和 1,155 个唯一身份，日期范围更新为 `2025-01-02..2026-08-26`；raw 仍是 360,448 B 物理表，serving 仍是 0 B 普通 view。生产 revision 仍为 `20260826_000152`，正式服务 active、开放 TaskRun 为 0。

`margin` 的 M0/M1/M2/M3a/M3b 据此全部完成，P1-B1 整批结案。本轮没有发现会阻塞后续批次的共享运行链问题；下一步按固定顺序进入 `P1-B2-moneyflow_ind_dc-M0`，只读重新冻结其对象、消费者、workflow/readiness、分块等价、容量、查询与停止门禁。

### 2.16 2026-08-27 `P1-B2-moneyflow_ind_dc-M0` 只读复审事实

本阶段没有改代码或生产配置，没有部署、migration、任务创建、schedule 暂停或 Tushare 请求。当前生产为 commit `f732f8bd`、revision `20260826_000152`；相关服务和健康端点正常，开放 TaskRun、超过 5 分钟事务与目标锁均为 0。根盘可用 52,376,059,904 B，HDD 可用 334,694,993,920 B。

1. 当前 Definition 显式请求并保存 18 个 source fields；一个交易日默认展开 `行业/概念/地域` 三个 unit，每 unit 使用 5,000 行 offset/limit 分页。最近自然 TaskRun `9506` 的 node `15226` 为三页短页、`31/504/496` 行、总读取/保存 1,031、0 retry/reject/dedupe；本轮没有重复请求源端；
2. raw/serving 都是 `pg_default` 物理表，主键 `(trade_date, content_type, name)`，并都有 `trade_date` 与 `(content_type, trade_date)` 两个等价索引。owner、ACL、空 comments 一致；无 inheritance、外键、trigger、RLS、外部 view/function、rewrite、扩展统计、security label 或 publication；
3. raw/serving 各 339,268 行，范围 `2023-09-12..2026-08-26`，地域/概念/行业分别为 `11,377/167,894/159,997`；空 `ts_code` 和非空 `(trade_date, content_type, ts_code)` 重复组均为 0。36 个自然月全部 18 业务字段双向差集为 0，全表复核仍为 0；
4. 单类单日峰值 509、全分类单日峰值 1,031、月峰值 23,541。M1 migration 固定使用 30,000 行/月上限和 16 MiB work_mem，30,001 行必须在 DDL 前 fail-closed；不在锁内追加无界全表差集；
5. raw 大小 94,789,632 B，serving 大小 88,358,912 B；当前预计可释放 84.27 MiB SSD，不新增 raw 索引。raw `fetched_at` 与 serving `updated_at` 全部一致，但有 10,191 行历史 `created_at` 不同；已登记消费者不读审计列，切换后仍按统一合同投影 `fetched_at AS created_at/updated_at`；
6. serving 直接消费者是 Wealth 板块概览与 Heat source query；Wealth 前端只消费 API。Lake Console 已直接读 raw；未发现 QTF/DG 直接读该 serving relation。最大日期、同日概念聚合和 10 日 Heat 查询均使用 raw 等价索引；热缓存 10 日查询 raw/serving 为 `19.275/18.355 ms`，约 5.0% 差异，没有结构性退化；
7. M0 发现独立异常：schedule #4 在 20:00 成功，但 Heat readiness 只接受 21:00 后的资金 workflow；`2026-08-20/21/24/25/26` 的 Heat 自动任务均在 00:30 超时。它不阻塞本数据集 M1/M2，却明确阻塞未来 M3a；必须另行拍板是调整资金 workflow 时间还是 readiness 口径，并先恢复自然 Heat 成功基线。

M0 据此通过 Definition、物理对象、全字段等价、容量和查询的 M1/M2 准入。M0 不授权任何生产修改，也不允许把 Heat 时间冲突混入 raw 直出 migration。

2026-08-27 已完成 `P1-B2-moneyflow_ind_dc-M1`：Definition 仅切换为 `raw_only_upsert + raw_with_serving_view`，raw ORM 只补生产既存的两个索引 metadata；新增独立 revision `20260827_000153`，接唯一真实 head 152，按自然月以 30,000 行上限比较全部 18 个业务字段，并在任何 serving DDL 前检查三列身份、两边物理合同、未知依赖和数据差异。view 继续显式投影原 20 列、动态恢复 owner/SELECT ACL/comments，并以既有共享函数和本 relation 独立 trigger 拒绝三类 DML；禁止 `CASCADE`、自动 downgrade、共享函数重建和 raw DDL。专项、registry、writer、date-completeness、Wealth/Heat、架构与 Definition lint 回归均通过。

M1 结束时没有连接数据库、部署、迁移、创建任务或请求 Tushare，生产仍为 revision 152。当时的下一步只能另行授权 `P1-B2-moneyflow_ind_dc-M2`，在隔离 PostgreSQL 真实应用 revision 153 并验证容量、差异、身份、依赖、ACL、拒写、回滚、即时可见和查询计划；M2 结果不能被静态测试替代。

2026-08-27 已完成 `P1-B2-moneyflow_ind_dc-M2`。本轮在只监听私有 Unix socket 的 PostgreSQL 18.4 临时实例中，以非超级用户和独立 env 文件执行；错误数据库名会在 `alembic_version` 创建前被身份门禁拒绝，没有连接 Prod、请求 Tushare、部署、创建 TaskRun 或修改 schedule/Heat 配置。

1. revision 153 在 36,000 行 raw/serving 等价样本上成功；36,000 个三列身份、18 字段双向差异、审计时间投影差异均为 0，月峰值 9,300；raw OID 与三个索引 OID/定义/有效状态保持不变且仍在 `pg_default`，serving 成为 0 B 普通 view；
2. owner、relation/column comment、PUBLIC SELECT、普通 SELECT 和 `WITH GRANT OPTION` 全部恢复；共享拒写函数合同不变，独立 trigger enabled，view 的 INSERT/UPDATE/DELETE 均返回 SQLSTATE `55000`；
3. 正式 `DatasetWriter` 两次 upsert 只写 raw，view 同事务返回更新值，回滚后无残留；raw INSERT/UPDATE/DELETE 同样即时反映并完整回滚；
4. 最大日期、同日概念点查和概念最近 10 日查询结果 hash 切换前后相同，计划从 serving 等价索引下推 raw 索引，最终复跑 total cost 分别为 `0.83/0.90`、`8.32/8.32`、`128.08/128.08`，临时块均为 0；隔离微秒值不替代生产 M3a 的时延验收；
5. 30,001 行月容量、单字段差异、主键合同漂移和未知依赖四类验证均在 DDL 前 fail-closed，revision 仍为 152、旧 relation/行数/metadata 完整；合法主键下的同身份重复由 PostgreSQL 以 `23505` 物理拒绝，没有误写成 migration 自身发现重复；
6. 在 `DROP TABLE -> CREATE VIEW -> trigger` 后注入异常可完整回滚，revision、两张物理表 OID、36,000 行、索引、ACL/comment 和零用户 trigger 全部恢复。六套验证库结束时开放事务为 0，临时实例和数据目录已删除。

M2 据此通过且不需要修改 revision 153 或业务代码。生产仍为 revision 152、两张物理表；下一阶段只能是单独授权的 M3a，并继续受第 2.16 节 Heat 时间契约异常阻塞。

完整部署随后在未暂停 schedule/worker 的情况下自动应用 revision 153，形成与概念数据集相同类别的发布顺序偏差。切换后生产只读验收确认 raw/view 各 339,268 行和 339,268 个唯一身份，serving 为 0 B raw-backed view，原 raw 索引、owner、SELECT ACL、拒写 trigger、20 列投影和三类代表查询均正常；原 serving 88,358,912 B 已实际释放。该结果不允许倒推为维护窗口前门禁通过，也不替代自然工作流验收。

Heat 根因已按独立双门槛合同修复：收盘工作流保持 `21:00`，资金流工作流采用与 schedule #4 一致的 `20:00`；旧的全局 `21:00` 单值合同已从代码和现行 LLD 清零。`2026-08-27 18:47+08` 已在开放 TaskRun 为 0 的窗口发布 commit `6c16ac31`，跳过 migration、构建、seed 和业务 worker 重启，仅重启 Ops scheduler；Alembic 保持 revision 153，schedule #4/#36 未改。后续只以自然 schedule 验收，不额外请求 Tushare。

2026-08-28 已对 `2026-08-27` 的自然运行完成生产只读验收。schedule #4 创建的 TaskRun `9633` 于 20:00 后成功完成，`moneyflow_ind_dc` 节点读取/保存 `1,031/1,031` 行、拒绝与去重均为 0；schedule #2 创建的收盘 TaskRun `9644` 中 Heat 要求的 `daily/dc_index/dc_member/dc_daily/limit_list/suspend_d` 节点均成功且目标日一致。schedule #36 随后仅创建一个 Heat TaskRun `9645`，readiness 为 `HEAT_READY`，明确引用 `9633/9644`，最终写出 504 个板块事实，其中 476 个 `VALID`、28 个按业务契约保留的 `INVALID`（12 个 `HISTORY_INSUFFICIENT`、16 个 `MEMBER_COUNT_LOW`），不存在 ingestion 源行拒绝。

同一验收窗口内，`raw_tushare.moneyflow_ind_dc` 与 raw-backed view `core_serving.board_moneyflow_dc` 均为 1,031 行、1,031 个身份，20 列显式投影双向 `EXCEPT ALL` 为 0；Heat 表只有一个 `calculated_at`，readiness/task 的 config/source/plan/content hash 一致。21:15 首次触发后连续 scheduler tick 均未重复建任务，证明同日去重生效。由此 `P1-B2-moneyflow_ind_dc-M3b` 通过，先前失败、提前 migration 和维护窗口顺序偏差继续作为历史事实保留；下一步仅可在独立授权后进入 `P1-B2-dc_daily-M0`。

### 2.17 2026-08-28 `P1-B2-dc_daily-M0/M1/M2/M3a`

M0 以生产只读证据重新冻结本数据集，而没有请求 Tushare、创建任务、部署、迁移或修改 schedule。raw/serving 各 634,116 行，日期范围 `2024-01-02..2026-08-27`；32 个自然月的 13 个业务字段双向 `EXCEPT ALL` 均为 0，月峰值 23,537。两层主键均为 `(ts_code, trade_date, category)`，并各自具备 `trade_date` 与 `(trade_date, category)` 等价索引；serving 当前占 161,710,080 B（154.22 MiB）。Wealth、QTF、DG source probe 的完整消费者查询基线没有出现结构性退化，单独子查询的差异只保留为诊断。

自动入口审计发现 `dc_daily` 同时由 schedule #24 的 18:30 workflow 与 schedule #2 的 21:02 收盘 workflow 写入；最近同目标日两次自然执行分别读取 1,026 与 1,030 行。未来 M3a 必须把两个入口作为同一维护窗口合同暂停和恢复，不能复制前项只处理单 schedule 的步骤。57,367 行旧 serving `created_at` 与 raw `fetched_at` 不同，但 `updated_at` 全部一致；已登记消费者不读取审计列，继续按一期统一口径投影 `fetched_at AS created_at/updated_at`。

M1 只修改 `dc_daily` 自身 Definition storage contract、raw ORM 索引 metadata，新增接唯一真实 head 153 的 revision `20260828_000154`，并补专项与既有参数化测试。source fields、日期/filter、无 filter 单 unit、2,000 行分页、5,000 unit 上限、request builder、resolver、writer 共享实现、两条 workflow 与所有消费者均未改变。migration 在 serving DDL 前验证两层物理合同、owner、raw SSD tablespace、主键/索引、未知依赖和按月 13 字段等价；固定 30,000 行/月上限，恢复 owner/SELECT ACL/comments，以显式 view 和独立 trigger 拒绝三类 DML，禁止 `CASCADE`、raw DDL、共享函数重建和自动 downgrade。

M0/M1 据此通过，但结论仅覆盖只读生产基线、代码和静态 migration 合同。生产仍处于 revision 153、两张物理表；下一阶段只能另行授权 `P1-B2-dc_daily-M2`，在隔离 PostgreSQL 真实验证 revision 154、30,001 行 fail-closed、字段/身份/依赖差异、ACL、三类 DML、事务回滚、view 即时可见、正式 writer 和代表查询计划。

2026-08-28 已完成 `P1-B2-dc_daily-M2`。本轮使用只监听独立 Unix socket 的 PostgreSQL 18.4 临时实例，应用角色为非超级用户；每次 Alembic 调用前同时核验数据库、用户、socket、无 TCP 监听、非恢复模式和管理员读取的 `data_directory`，并以不存在的独立 env 文件阻断仓库本地配置覆盖。本轮没有连接 Prod、请求 Tushare、部署、创建 TaskRun 或修改 schedule/workflow。

1. revision 154 在 36,000 行等价样本上成功，其中首月恰好 30,000 行、次月 6,000 行；raw OID 和三个索引 OID/定义/有效状态保持且继续位于 `pg_default`，serving 从 8,028,160 B 物理表变为 0 B view，HDD tablespace 中目标对象为 0；
2. 13 字段、三列身份、owner、relation/column comment、PUBLIC/普通/带授权选项 SELECT、raw reader 权限全部保持；view 三类 DML 均以 `55000` 拒绝；raw 三类 DML、正式 writer 和 view 即时可见均在 rollback 后无残留；
3. 交易日点查、分类范围和最大日期三类结果不变，计划下推 raw 等价索引；总成本分别为 `214.70→212.94`、`9.25→9.20`、`0.49→0.54`，没有结构性退化；
4. 单月 30,001 行、业务字段差异、身份值差异、主键顺序漂移和未知 view 依赖均在 serving DDL 前失败；各库保持 revision 153、原 OID、两张物理表和零用户 trigger；
5. 在真实 `DROP TABLE → CREATE VIEW → trigger` 后注入异常可完整回滚到 revision 153、两张原物理表、原索引和数据。所有场景独立建库，实例结束后已停止。

M2 据此通过，生产仍为 revision 153 和两张物理表。下一阶段只能单独授权 M3a，并在生产实时预检后同时暂停 schedule #24 与 schedule #2，禁止把本轮隔离验证外推为生产 migration 授权。

2026-08-28 `10:02..10:10+08` 已完成 `P1-B2-dc_daily-M3a`。预检再次确认生产 revision 153、两层各 634,116 行、32 个月 13 字段双向差异为 0、月峰值 23,537、开放 TaskRun/目标锁/长事务均为 0。commit `fa5fcf8c` 同步后，通过正式服务同时暂停 schedule #2/#24，再停止通用 worker；`--maintenance-migration` 只安装后端并应用 revision 154，没有构建、seed、创建任务或隐式恢复服务。

切换后 raw OID `545332` 与三个索引保持不变，serving 成为 0 B 普通 view；owner、`lake_raw_reader` SELECT、comments 和独立拒写 trigger 均通过，三类 serving DML 全部返回 SQLSTATE `55000`。raw/view 各 634,116 行和 634,116 个身份，全量双向差异为 0；原 serving 161,710,080 B 物理 relation 已释放。Web、QTF、日期完整性 worker 和 scheduler 均完成连接池/进程回收，通用 worker 在查询合同通过后恢复。

DG 单日、Wealth 同日概念、QTF 有界历史三类代表查询分别返回 1,030、503、5,376 行，raw/view hash 完全一致，执行计划均下推 raw 等价索引。正式 TaskRun `9704` 对 `2026-08-27` 执行一个 unit：1 页短页结束、0 重试、未截断，读取/归一化/保存均为 1,030，拒绝与去重均为 0；目标日 raw/view 都是 1,030 行和 1,030 个身份，全表总量不变。任务完成后 schedule #2/#24 以原 cron、时区和 `last_triggered_at` 恢复 active，开放任务为 0，全部相关服务 active，健康端点正常。

M3a 据此通过。`P1-B2-dc_daily-M3b` 已于 2026-08-29 依据 schedule #24/#2 的 TaskRun `9747/9773` 关闭：两个 `dc_daily` 节点均成功处理 `2026-08-28`，各读取/保存 `1,031/1,031`，1 页短页结束，reject、去重、重试均为 0；最终 Raw/view 各 1,031 行和唯一身份，逐字段双向差异为 0，第二轮通过原位更新完成幂等。M0/M1/M2/M3a/M3b 全部通过，本数据集结案。

### 2.18 2026-08-28 `P1-B2-suspend_d-M0`

M0 严格限于当前代码、CodeGraph 和生产只读证据，没有请求 Tushare、创建任务、部署、migration 或 schedule 修改。raw/serving 都是 `pg_default` 普通物理表，各 640,504 行和 640,504 个唯一 `id/row_key_hash`，日期范围 `2000-01-04..2026-08-27`；320 个自然月按 `id, row_key_hash, ts_code, trade_date, suspend_timing, suspend_type` 做双向 `EXCEPT ALL`，所有月份两个方向差异均为 0，逐 hash 的 `id` 和内容差异也均为 0。月峰值是 `2015-07` 的 17,074 行，后续独立 migration 的 fail-closed 容量门禁固定为 20,000 行/月。serving 当前占 222,199,808 B（211.91 MiB），是本项可释放毛量；raw 的等价索引和 `lake_raw_reader` 权限继续保留在 SSD。

已知 serving 消费者覆盖 Wealth 指数、板块、连板、有效股票池、Sector Heat、市场情绪与 walk-forward；Lake Console 已读取 raw，DG 正式资产走独立源链。停牌点查、`BK0596.DC` 板块成员及 120 个开市日市场情绪 join 的 raw/serving 结果均一致；两层点查和范围停复牌子查询都使用各自等价的 `trade_date` 索引。范围计划真实消费连接结果，样本为 660,861 根日线、355 个连接命中；单次冷缓存耗时只记基线，不作为 raw/view 快慢结论。

自动入口为 `daily_market_close_maintenance` 的 schedule #24（18:30）和 #2（21:02），不是独立 schedule；最近同一目标日的两个 `suspend_d` node 都是 1 unit、1 页短页、读取/保存 4 行、0 reject/去重/重试。未来 M3a 必须同时暂停和恢复两个入口。M0 时生产为 revision 154、开放 TaskRun/目标锁/超过 30 秒事务均为 0，根盘可用 52,380,954,624 B。

M0 同时发现现有手动 filter 契约缺陷：Ops 将 `suspend_type` 暴露为多选，执行策略文档要求枚举 fan-out，但 Definition 未配置 `enum_fanout_fields`，request builder 会把列表转换成 `"['S']"` 或 `"['S', 'R']"` 发送；旧数据集文档又写成单选。自动 workflow 不带 filter，故不影响已有自然任务。随后独立验证确认：`20260827` 无过滤返回 4 行，`S/R` 分别为 3/1 行且并集一致，错误列表字面量由源端以 `50101` 拒绝。当前代码已保留多选并按合法 `S/R` 单值 fan-out，request builder 对未展开列表 fail-closed；point/range 正反向测试和两份现行文档已同步。存储直出的 M0 与前置 filter 修复均已通过，具备 `P1-B2-suspend_d-M1` 编码准入；生产仍需部署后才获得该修复。

### 2.19 2026-08-28 `P1-B2-suspend_d-M1`

M1 已按一期 LLD 完成编码与静态验收，没有连接任何数据库、调用 Tushare、部署、创建任务或修改 schedule。Definition 只把 storage 收敛为 `raw_suspend_d/raw_tushare.suspend_d/raw_only_upsert/raw_with_serving_view`；四个 source fields、SSE point/range、`ts_code`、`S/R` fan-out、5,000 行分页和 Ops 能力没有变化。`RawSuspendD` 原本已经完整声明生产三组索引，因此未修改 ORM 或创建索引。

独立 revision `20260828_000155` 只接真实 head 154，先验证两层 relation/owner/SSD/列/主键/三组索引/ACL/依赖，再在 `SHARE` 锁内按自然月比较六个业务字段及 `id/row_key_hash` 双身份；月容量上限为 20,000 行。通过后才以 `ACCESS EXCLUSIVE` 把 serving 替换为显式 8 列 raw-backed view，恢复 owner、SELECT ACL 和 comments，并创建独立三类拒写 trigger；禁止 `CASCADE`、raw DDL、共享函数重建和自动 downgrade。

专项测试同时证明 raw-only writer 只写 raw、冲突键仍是 `row_key_hash`，并覆盖 Definition、fan-out、ORM、ServingPublish 无旁路、20,001 行超限、字段/身份/约束/依赖 fail-closed、显式投影和离线 PostgreSQL SQL。M1 只关闭代码门禁；生产仍为 revision 154 和两张物理表，下一步只能在另行授权后进入隔离 PostgreSQL M2。

### 2.20 2026-08-28 `P1-B2-suspend_d-M2`

M2 已在仅监听私有 Unix socket 的 PostgreSQL 18.4 临时实例完成。应用 migration 的非超级用户通过独立 env 文件连接；每次 Alembic 调用前分别用应用连接和临时管理员只读确认 URL、数据库、用户、无 TCP 地址、恢复状态、socket、端口及 `data_directory`。本阶段没有连接 Prod、请求 Tushare、部署、创建 TaskRun 或修改 schedule/workflow。

revision 155 在单月精确 20,000 行、总计 24,000 行的正向库成功应用，raw table/索引 OID 保持，serving 成为 0 B 普通 view；全行、`id`、`row_key_hash` 与双向差集一致。owner、带授权选项的 SELECT、raw reader 权限、relation/column comments 和拒写 trigger 全部恢复，三类 DML 均返回 `55000`。raw DML 与正式 `DatasetWriter` 都证明 view 同事务即时可见；冲突更新后 raw/view 同为新 `id=24001`，回滚后恢复原 `id=1`，无数据残留。

20,001 行单月、业务字段差异、`id` 差异、`row_key_hash` 差异和未知 view 依赖五类负向库都在 serving DDL 前失败，revision、对象/index OID、relkind 和行数快照不变；切换后注入事务错误的独立库也完整恢复两张物理表和 revision 154。交易日点查、代码日期点查、最大日期三类结果 hash 不变，计划从 serving 索引下推 raw 等价索引，总成本为 `494.56→572.75`、`8.31→8.31`、`0.38→0.39`，没有临时块读写。第一项成本增加 15.8%，低于 20% 隔离门禁；生产真实消费者时延仍须由 M3a 交错重复测量。

M2 据此通过且无需修改 revision 155 或业务代码。生产仍为 revision 154 和两张物理表；下一阶段只能是单独授权的 M3a，并须实时重做生产身份、任务、锁、磁盘、全量差异及两个 workflow schedule 的维护窗口门禁。

### 2.21 2026-08-28 `P1-B2-suspend_d-M3a`

M3a 于 `13:08..13:21+08` 完成。维护窗口先证明生产 revision 154、两层各 640,504 行、320 月六字段及 `id/row_key_hash` 双身份差异为 0、月峰值 17,074，且开放任务、锁、长事务和未知依赖均为 0。schedule #2/#24 通过正式 service 逐个暂停，通用 worker停止后再次通过相同门禁；生产随后用维护迁移模式部署精确 commit `9d32b266` 并应用 revision 155，没有构建、seed、unit 同步或服务自动重启。

切换后 raw 保持 `pg_default` 物理表，serving 成为 0 B 普通 view；两层仍为 640,504 行和 640,504 个唯一 `id/row_key_hash`，六字段差异为 0。三类 DML 均返回 `55000`。点查、板块成员和市场情绪范围 join 的 raw/view 校验值一致，三轮交错中位耗时为 `0.131/0.125 ms`、`30.837/32.712 ms`、`2415.554/1589.289 ms`，全部使用 raw 等价索引且无临时块；唯一正向退化为 6.1%，低于 20% 门禁。

正式 TaskRun `9717` 对 `2026-08-27` 执行 1 个 unit、1 页短页：读取/保存 4/4，reject/去重 0，目标日 raw/view 各 4 行和 4 个身份，全表仍为 640,504 行。TaskRun 完成后 schedule #2/#24 通过 config revision 111/112 原样恢复 active，所有相关服务 active、健康端点正常，开放任务、目标锁和长事务均为 0。原 serving relation 释放 222,199,808 B（211.91 MiB）；根盘可用量从维护前 52,420,927,488 B 增至 52,642,947,072 B，但仍以 catalog 大小作为精确收益。

M3a 据此通过。`P1-B2-suspend_d-M3b` 已于 2026-08-29 依据同一 TaskRun `9747/9773` 关闭：两个 `suspend_d` 节点均成功处理 `2026-08-28`，各读取/保存 `7/7`，1 页短页结束，reject、去重、重试均为 0；最终 Raw/view 各 7 行，`row_key_hash` 与四字段源事实均唯一，包含 `id/row_key_hash` 的六字段双向差异为 0，第二轮通过原位更新完成幂等。M0/M1/M2/M3a/M3b 全部通过，本数据集结案。

### 2.22 2026-08-28 `P1-B3-stk_auction_o-M0`

M0 严格限于当前代码、CodeGraph 与生产只读证据，没有请求 Tushare、创建 TaskRun、部署、migration、暂停 schedule 或修改业务数据。当前 Definition 显式请求九字段，按开市日生成单日 unit，保留 `limit/offset` 和 `page_limit=10000`；两层继续由 `raw_core_upsert` 写入同一归一化批次。未发现 serving 专属转换、冲突消解、ServingPublish、serving DML 旁路或 Biz/QTF/DG/frontend/Lake 直接读取；Ops Catalog、freshness、日期完整性和 TaskRun 观测属于已知消费者。

生产 raw/serving 都是 `pg_default` 普通物理表，各 2,183,621 行和 2,183,621 个唯一 `(ts_code, trade_date)`，日期范围 `2025-01-02..2026-08-27`。20 个自然月逐月比较 `ts_code, trade_date, close, open, high, low, vol, amount, vwap`，双向 `EXCEPT ALL` 全部为 0；月峰值是 `2026-07` 的 126,364 行，后续 migration 月容量门禁固定为 160,000 行/层，M2 必须证明 160,001 行在 serving DDL 前失败。raw 当前 411,148,288 B（392.10 MiB），serving 当前 382,353,408 B（364.64 MiB）；后者只是待切换毛收益，尚未计入已释放空间。M0 快照时开放 TaskRun、开放目标 node、等待目标锁和超过 30 秒事务均为 0，根盘/HDD 可用空间分别为 52,590,292,992 B/320,990,502,912 B。

最大日期、单日全字段、单股全历史和五个交易日全市场四类 raw/serving 查询结果校验值一致，三轮交错中位耗时分别为 `0.112/0.135 ms`、`11.551/11.129 ms`、`1.475/1.293 ms`、`54.081/53.961 ms`，均无临时块且相对退化低于 20%。日期完整性查询同样返回一致的 81 个日期，但 raw/serving 为 `75.683/54.636 ms`，raw 慢 38.5%；两层都使用日期索引，差异来自 raw all-visible page 仅 80.18%、heap fetch 456,208，而 serving 为 92.91%/188,095。默认 autovacuum 阈值高于当前约 9.9 万 dead tuple，这个门禁不会被短期自动维护可靠关闭。

自动入口是 `daily_market_close_maintenance` 的 schedule #24（18:30）与 #2（21:02）。最近自然节点中，18:30 返回 0 行短页，21:02 返回约 5,500 行单页短页且 reject/去重/重试为 0；未来 M3a 必须同时暂停和恢复两个入口。M0 结论为**条件通过**：可另行授权 M1/M2，但 M3a 暂不放行。生产切换前须在停止写入后执行经授权的普通 `VACUUM (ANALYZE) raw_tushare.stk_auction_o` 并重跑三轮日期完整性基准；结果仍慢于 serving 超过 20% 或出现结果/计划异常时，必须在 migration 前停止。普通 vacuum 不是 Alembic 步骤，也不计入释放量。

### 2.23 2026-08-28 `P1-B3-stk_auction_o-M1`

M1 只修改 `stk_auction_o` 自身 Definition storage contract，新增独立 revision `20260828_000156`、专项/参数化测试并同步文档；没有修改 ORM/DAO、共享 writer、source fields、request builder、日期/unit、分页、workflow/freshness、Ops、Biz/QTF/DG/Lake/frontend，也没有连接数据库、请求 Tushare、部署、migration、TaskRun、schedule 或 vacuum。

Definition 现在通过既有 `raw_only_upsert` 只写 `raw_tushare.stk_auction_o`，原 `core_serving.equity_auction_open` 名称由 revision 156 切换为显式 11 列 raw-backed view。migration 接真实 head 155，先验证两张物理表的 owner、raw SSD、列、主键、单列日期索引、ACL 与未知依赖，再按自然月对九字段做双向 `EXCEPT ALL`；每层每月固定 160,000 行上限，160,001 行、身份/字段差异或未知合同必须在 serving DDL 前失败。切换禁止 `CASCADE`、raw DDL/DML、共享函数重建和自动 downgrade；owner、SELECT ACL、comments 被恢复，serving 三类 DML 由既有受控函数和独立 trigger 拒绝。

专项测试证明 Definition/plan/filter/source fields/分页保持不变、正式 writer 只写 raw、两层 ORM 业务合同和日期索引一致、ServingPublish 无旁路、migration 资源/依赖/锁顺序/显式投影/拒写/离线 SQL 合同成立；相关 registry、resolver、workflow/freshness 与架构回归继续通过。M1 结论为**通过**，但生产仍是 revision 155 和两张物理表；下一阶段只能另行授权隔离 PostgreSQL M2。M0 的日期完整性性能门禁继续阻塞未来 M3a，不能因为 M1 静态验证通过而跳过 vacuum 后复测。

### 2.24 2026-08-28 `P1-B3-stk_auction_o-M2`

M2 在仅 Unix socket 可达的 PostgreSQL 18.4 隔离实例完成。每次 Alembic 前都验证最终配置 URL、数据库、用户、socket、端口、data directory 和 `inet_server_addr=NULL`；没有连接生产、请求 Tushare、部署、TaskRun、schedule 或生产 vacuum。全部场景完成后临时实例停止，成功数据目录删除。

160,000 行/月正向库成功从 revision 155 应用 156。Raw OID 和两个索引 OID 保持不变，heap/PK/date index 继续位于 `pg_default` 且 valid/ready；Serving 从物理表切为 0 B view。Raw/view 均为 160,000 行和身份，九字段、审计投影差异为 0；owner、SELECT ACL/grant option、comments 和独立 trigger 恢复。三类 Serving DML 均以 `55000` 拒绝，Raw DML 即时可见并可完整回滚，正式 writer 只写 Raw 且回滚后原值恢复。

160,001 行容量、业务字段差异、身份差异和未知 view 依赖均在 Serving DDL 前失败，revision/relation/index/行数/comments/trigger 快照不变；切换后故障注入也证明 PostgreSQL 事务能恢复 revision 155 的两张物理表及全部对象。单日、单股、最大日期和 10 日完整性查询结果 hash 一致、下推 Raw 等价索引、无临时块，最大正向退化约 5.4%。M2 据此通过且 revision 156 无需修改；生产仍为 revision 155。下一阶段只能另行授权 M3a，并先在停止写入的维护窗口对 Raw 做普通 vacuum、重测并关闭 20% 性能门禁。

### 2.25 2026-08-28 `P1-B3-stk_auction_o-M3a`

M3a 于 `14:56..15:05+08` 完成。开始预检时发现标准完整部署已在正式暂停 schedule/worker 前拉取 commit `bbb3befc`、自动应用 revision 156，并重启 Web、scheduler 与 worker；该顺序违反一期维护合同，不能补造迁移前门禁，本轮也没有重复 migration。发现时远端代码已包含 raw-only Definition，Serving 已为 0 B view，开放任务、目标 node、等待锁和长事务均为 0，未观察到旧双写代码写 view。

schedule #2/#24 随后通过正式 service 暂停，config revision `113/114` 记录 `paused`；通用 worker 停止后重新关闭任务/锁/事务门禁。普通 `VACUUM (ANALYZE)` 把 Raw all-visible page 从 80.18% 提升到 100%，dead tuple 统计归零，未使用 `VACUUM FULL`、未改 Raw OID/索引/表空间。M0 旧物理 Serving 日期完整性中位数为 `54.636 ms`，vacuum 后 Raw 为 `50.751 ms`，约快 7.1%；当前 Raw/view 五类查询校验值一致、计划下推 Raw 日期索引或 PK、临时块为 0。Serving 已提前成为 view，因此这里明确使用 M0 旧物理基线作跨时点对照，不把它伪装成同一时点切换前复测。

Serving `INSERT/UPDATE/DELETE` 均以 SQLSTATE `55000` 拒绝；owner、Raw `lake_raw_reader SELECT`、Serving ACL 和显式 11 列投影正确。相关连接池回收后，正式 TaskRun `9726` 仅请求 `2026-08-27` 一个 point unit：1 页短页读取/保存 `5,512/5,512`，reject、去重、重试为 0，目标日 5,512 行全部在任务窗口刷新；Raw/view 当日及全表 9 字段/唯一身份一致，全表均为 2,183,621 行。schedule #2/#24 通过 config revision `115/116` 原样恢复，全部相关服务 active，开放任务、目标锁和长事务为 0。

M3a 据此通过，但保留“标准部署提前应用 migration”的发布顺序偏差。原 Serving relation 的 `382,353,408 B（364.64 MiB）` 已释放，Raw 继续位于 SSD。

### 2.26 2026-08-29 三项自然 M3b 结案与独立 `anns_d` TODO

schedule #24 的 TaskRun `9747` 与 schedule #2 的 TaskRun `9773` 均成功，29 个 workflow step 全部完成。`dc_daily` 与 `suspend_d` 的两轮节点分别稳定为 `1,031/1,031` 与 `7/7` 读取/保存，最终 `fetched_at` 均来自第二轮原位更新，Raw/view 行数、身份及全部业务字段一致。`stk_auction_o` 的 18:30 节点为 `0/0` 空短页、21:02 节点为 `5,508/5,508`，证明该源端在前一窗口尚未就绪、后一窗口正常就绪；最终 Raw/view 各 5,508 行和身份，九字段差异为 0。其相同非空数据重跑幂等已由 M3a 的生产 TaskRun `9726` 证明。三个目标节点的 reject、去重、重试均为 0，三项 M3b 据此通过并结案。

两个父 workflow 的 reject 分别为 69 与 184 行，全部来自范围外的 `anns_d` 节点，reason code 为 `write.duplicate_conflict_key_in_batch:row_key_hash`。`anns_d` 的哈希身份由 `ann_date, ts_code, title, url, rec_time` 计算而不包含 source field `name`，因此当前不能把这些冲突直接写成“六字段完全重复”。本专项另列只读数据质量审计 TODO：对照 rejection sample 与目标行的全部六个 source fields，判定是完全重复、仅 `name` 差异还是其它归一化身份问题，再另行评审去重或身份合同；该 TODO 不重新打开上述三项结案状态，也不授权请求 Tushare、修改代码或生产数据。

### 2.27 2026-08-29 `P1-B3-stk_auction_c-M0` 只读复审事实

本轮没有修改代码、请求 Tushare、创建 TaskRun、部署、migration、暂停 schedule 或写生产数据库。CodeGraph 与精确引用审计覆盖 Definition、resolver/request builder、writer、raw/serving ORM 与 DAO、Ops workflow/freshness/date completeness、ServingPublish、Biz/QTF/DG/frontend/Lake 和测试。当前 Definition 仍为 9 个显式 source fields、交易日 point/range、每个开市日一个 unit、10,000 行 `limit/offset` 分页、可选 `ts_code` 和 `raw_core_upsert`；不存在额外 serving 冲突消解。

生产 Alembic 为 `20260828_000156`。Raw/Serving 均为 `pg_default` 物理表，分别为 424,484,864 B 与 390,266,880 B；两边各 2,255,593 行、2,255,593 个唯一 `(ts_code, trade_date)`，日期范围均为 `2025-01-02..2026-08-28`。20 个自然月的全部 9 个业务字段双向 `EXCEPT ALL` 均为 0，月峰值 132,619；列、非空、主键、索引和依赖审计无阻塞。`fetched_at -> updated_at` 全表一致，但 93,769 行的 serving `created_at != updated_at`，未来 view 会按既定透明边界把两个审计列都投影为 Raw `fetched_at`。

生产代表查询结果/hash 一致，Raw 的单日、单股票、5 日范围和日期完整性中位数相对 Serving 分别为 +4.30%、-5.99%、+3.43% 和 +12.55%，均未触发 20% 停止门禁；计划使用对应 Raw 索引，临时块为 0。M1 容量门禁独立固定为每层每月 160,000 行，并要求 M2 验证 160,000 通过、160,001 在任何 serving DDL 前拒绝。已知自动入口为 `daily_market_close_maintenance` schedule #24（18:30）与 #2（21:02）；后续 M3a/M3b 必须分别覆盖两个入口及其“前者可能空、后者就绪”的源端时序。

M0 据此通过。下一阶段仅可在另行授权后进入本数据集 M1；生产仍为两张物理表与双写 Definition，尚未释放 390,266,880 B。仓库外 SQL/BI/人工脚本和 relation catalog 工具仍须运营登记。

### 2.28 2026-08-29 `P1-B3-stk_auction_c-M1` 编码事实

M1 开工前重新核验迁移链：ETF active pool 退场 revision 已把本地唯一 Alembic head 从 M0 快照时的 156 推进到 `20260829_000157`。本项据此新增独立 revision `20260829_000158` 并明确接 157，新增后 `alembic heads` 仍只有 158；没有复用旧编号、猜测 `down_revision` 或形成并行 head。

Definition 仅把 `stk_auction_c` storage 收敛为 `raw_stk_auction_c + raw_tushare.stk_auction_c + raw_with_serving_view + raw->serving_view + raw_only_upsert`，原 `core_serving.equity_auction_close` 名称继续作为 serving view 合同。九字段、请求 builder、日期/filters、10,000 行分页、planner/unit、工作流与 schedule 均未改变。Raw ORM 和 DAO 已完整声明生产主键及日期索引，M1 没有修改 ORM、DAO factory、writer、resolver、Ops、前端、QTF、DG 或 Lake。

revision 158 在任何 Serving DDL 前验证 relation/owner/raw SSD/列/主键/索引/约束/ACL/依赖及既有拒写函数，以 15 秒锁超时、120 秒语句超时和 16 MiB `work_mem` 按自然月比较九字段双向 `EXCEPT ALL` 与身份唯一性；每层每月最多 160,000 行。随后无 `CASCADE` 创建显式 11 列 Raw-backed view，恢复 owner、SELECT ACL/grant option 和注释，并创建本 relation 独立 DML 拒绝 trigger。migration 不修改 Raw、不创建共享函数且禁止自动 downgrade。

专项与回归测试覆盖 Definition/plan、filter、分页、ORM/索引、Raw-only writer、freshness/date-completeness、ServingPublish 旁路、revision 158→157、容量/差异/依赖 fail-closed、锁和 DDL 顺序、权限/注释、三类 DML、禁止 downgrade及 PostgreSQL offline SQL 渲染。M1 没有连接数据库、请求 Tushare、部署、执行 migration、创建 TaskRun 或修改 schedule；生产仍为两张物理表和已部署双写代码。下一阶段只能是另行授权的 M2。

### 2.29 2026-08-29 `P1-B3-stk_auction_c-M2` 隔离验收事实

M2 在 `listen_addresses=''`、仅随机 Unix socket 可达的 PostgreSQL 18.4 一次性实例执行。每个数据库在 Alembic 前均核对最终应用配置 URL、数据库、用户、socket、端口与 data directory，避免配置优先级误连其它数据库；全程未连接 Prod、请求 Tushare、部署、创建 TaskRun、修改 schedule 或执行生产 DDL。实例已停止且数据目录已删除，报告留存在 `/private/tmp/goldenshare_stk_auction_c_m2_report.json`。

160,000 行/月正向库从 revision 157 成功应用 158：Raw relation 与两个索引 OID 保持不变，索引 valid/ready 且位于 `pg_default`；Serving 从物理表切为 0 B view。Raw/view 行数、唯一身份、九字段双向差集和审计时间投影全部一致；owner、Raw/Serving SELECT ACL、grant option、relation/column comments 与独立拒写 trigger 均恢复。Serving 三类 DML 全部返回 SQLSTATE `55000`；Raw DML 与正式 `DatasetWriter` 的结果立即在 view 可见，事务回滚后无残留且 writer 目标明确为 `raw_tushare.stk_auction_c`。

160,001 行、业务字段差异、身份差异和外部 view 依赖四个场景均在 Serving DDL 前失败，revision/relation/index/rows/comments/trigger 快照保持不变；另一个数据库在完成 `DROP TABLE -> CREATE VIEW -> trigger` 后注入故障，整个 migration transaction 回滚到 revision 157 及原两张物理表。四类代表查询的结果 hash 一致，计划下推 Raw PK/日期索引且无临时块；批量查询耗时为单日 `2.653 -> 2.577 ms`、日期完整性 `8.419 -> 8.757 ms`，两个亚毫秒点查询只作为计划证据。

M2 据此通过，revision 158 无需修改。生产仍为 revision 156、两张物理表和已部署双写代码，390,266,880 B 尚未释放；下一阶段只能另行授权生产 M3a，并重新执行任务、锁、worker、schedule、磁盘和代表查询实时门禁。

### 2.30 2026-08-29 `P1-B3-stk_auction_c-M3a` 生产切换事实

M3a 于 `16:26..16:32+08` 按维护合同完成。生产预检时 revision 为 157，Raw/Serving 各 2,255,593 行和唯一身份，20 个月九字段双向差异全为 0、月峰值 132,619；开放任务、目标 node、锁、长事务和 catalog 依赖均无阻塞。五类查询 hash 一致、命中等价索引、临时块为 0，Raw 最大正向退化约 7.14%，95.21% all-visible 已满足门禁，因此没有机械复制 `stk_auction_o` 的 vacuum。

schedule #2/#24 经正式服务暂停，scheduler 与 generic worker 停止后再次完成全量对账。`--maintenance-migration` 只安装 commit `3030524987a15740333240c4bf4edf49df4ff383` 并应用 revision 157→158，没有构建、seed、unit 同步、任务创建或隐式服务重启。Raw OID `808835` 及两个索引保持不变且继续位于 SSD；Serving 成为 OID `2038214`、0 B 普通 view。owner、Raw `lake_raw_reader SELECT`、Serving ACL 和拒写 trigger 正确，三类 DML 均以 SQLSTATE `55000` 拒绝。

连接池回收后，Raw/view 五类查询继续 hash 一致并下推 Raw 索引，无临时块。正式 TaskRun `10111` 请求 `2026-08-28` 一个 point unit，1 页短页读取/保存 `5,551/5,551`，reject、去重、重试为 0；目标日 5,551 行全部在任务窗口刷新，Raw/view 当日行数、身份和九字段一致，全表最终仍各为 2,255,593 行及同数唯一身份。两个 schedule 随后由 config revision `125/126` 按原 cron、时区和 timing 恢复 active，相关服务及健康端点正常，开放任务、锁和长事务为 0。

M3a 据此通过，原 Serving 390,266,880 B 已释放。`P1-B3-stk_auction_c-M3b` 只待 schedule #24（18:30）与 #2（21:02）的下一次自然工作流并已登记统一台账；不创建额外任务、不重复请求源端，也不阻塞 `moneyflow_ths` 的独立 M0。

## 3. Track A：独立小对象 SSD→HDD 迁移

### 3.1 A0：历史日线轻量叶分区

`core_serving_light.equity_daily_bar_light` 当前 `p2000`～`p2025` 已位于 HDD，`p2026` 必须继续留 SSD。本轮新发现 `p1990`～`p1999` 仍在 `pg_default`：

| 分区 | 当前总大小 |
| --- | ---: |
| `equity_daily_bar_light_p1990` | 57,344 B |
| `equity_daily_bar_light_p1991` | 696,320 B |
| `equity_daily_bar_light_p1992` | 1,826,816 B |
| `equity_daily_bar_light_p1993` | 6,078,464 B |
| `equity_daily_bar_light_p1994` | 14,876,672 B |
| `equity_daily_bar_light_p1995` | 16,547,840 B |
| `equity_daily_bar_light_p1996` | 21,364,736 B |
| `equity_daily_bar_light_p1997` | 34,914,304 B |
| `equity_daily_bar_light_p1998` | 43,507,712 B |
| `equity_daily_bar_light_p1999` | 47,079,424 B |
| **合计** | **186,949,632 B，约 178.3 MiB** |

生产 catalog 证据：

1. 每个叶分区有 1 个 heap 和 3 个有效、ready 的物理索引，共 40 个 relation；
2. 没有 TOAST relation、用户 trigger、RLS policy 或当前锁；
3. `n_tup_upd=0`、`n_tup_del=0`，属于关闭历史数据；
4. 业务仍通过父表 `EquityDailyBarLight` 查询，迁移不会改变 schema、表名或分区路由；极早年份查询可能受 HDD 延迟影响。

执行顺序：

1. 只授权 `p1990` 作为先导；其 3 个索引逐个迁移并验收，再迁 heap；每条 DDL 单独事务。
2. 确认根盘、HDD、WAL、锁和查询样本正常后，依次推进 `p1991`～`p1999`。
3. 每个分区完成后核验 OID、tablespace、filepath、原始字节、索引 `indisvalid/indisready` 和确定性查询样本。
4. `p2026`、父分区表和白名单外分区不得改变。

### 3.2 A1：原六张 dormant raw 候选的去向

raw 直出一期口径固定后，原 A1 不能再作为六表迁移批次执行：其中四张 raw 会直接承载 serving 查询，迁 HDD 会把用户查询从 SSD 转到机械盘。

| 原顺序 | raw 表 | 当前总大小 | 当前去向 | 结论 |
| ---: | --- | ---: | --- | --- |
| 1 | `raw_tushare.fund_adj` | 315.3 MiB | Track A 后置候选 | 未进入 raw 直出一期；一期完成后再独立评估 HDD 写入/Lake 导出延迟 |
| 2 | `raw_tushare.stk_auction_o` | 392.10 MiB | raw 直出 P1-B3 | 2026-08-28 M0 当前值；raw 必须留 SSD；从 Track A 移除 |
| 3 | `raw_tushare.stk_auction_c` | 405.54 MiB | raw 直出 P1-B3 | 2026-08-29 M3a 最终值 `425,238,528 B`；raw 必须留 SSD；从 Track A 移除 |
| 4 | `raw_tushare.moneyflow_ths` | 487.3 MiB | raw 直出 P1-B3 | raw 必须留 SSD；从 Track A 移除 |
| 5 | `raw_tushare.ths_daily` | 513.6 MiB | Track A 后置候选 | 未进入 raw 直出一期；一期完成后还要重新评估是否进入后续 raw 直出，不先搬迁 |
| 6 | `raw_tushare.stk_limit` | 623.9 MiB | raw 直出 P1-B4 | raw 必须留 SSD；从 Track A 移除 |

当前 Track A 后置 raw 候选只有 `fund_adj`、`ths_daily`，合计约 828.9 MiB；加上 `p1990`～`p1999` 约 178.3 MiB，理论上限约 1,007.2 MiB。该数值只是后置候选毛收益，不是当前授权或一期收益。

本轮 catalog 事实：

1. 原六张表都位于 `pg_default`，索引有效且 ready；
2. 没有外键、数据库 view 依赖、用户 trigger、RLS policy 或当前锁；
3. 没有开放 TaskRun，也没有对应 schedule；
4. TOAST heap 当前为空，但存在 TOAST relation 和索引，执行时必须逐个记录并验收实际 tablespace；
5. 只有 `fund_adj/ths_daily` 在未来独立评审通过后才可能执行 Track A；一期四张 raw 底表禁止迁移。

### 3.3 Track A 通用执行门禁

每个 relation 的授权和事务必须独立：

1. 执行前重新读取对象 OID、owner、heap/index/TOAST 原始字节、tablespace 和 filepath；
2. 验证 `gs_raw_cold_hdd` 的真实挂载、可用空间、owner 和应用角色 `CREATE` 权限；
3. 确认没有目标 TaskRun、schedule 即将触发、目标锁和长事务；
4. 暂停 scheduler 和会写目标对象的 worker，避免维护窗口内产生新写入；
5. `lock_timeout=15s`，单 relation 迁移设置有界 `statement_timeout`；锁超时直接失败，不等待堆积；
6. 普通表索引不会随 heap 自动迁移，必须从 `pg_index` 枚举后逐个 `ALTER INDEX ... SET TABLESPACE`；
7. 每完成一个物理对象立即核验，不把多张表放入一个大事务；
8. 观察会话持续记录根盘、HDD、`pg_wal`、后台 PID、等待事件和运行时长；
9. 任一对象核验失败、根盘低于 3 GiB、出现未知写入或锁等待即停止后续批次；
10. 不做全表 `count(*)`/hash，不请求 Tushare，不删除、清表或重建业务数据。

无整库备份条件下仍存在磁盘或实例级极端故障残余风险。小对象、单 relation 事务和逐项停止门禁只能降低操作风险，不能提供灾难恢复能力。

## 4. Track B：raw/core_serving 重复物理存储审计

### 4.1 准入标准

只有同时满足以下条件的数据集，才能进入 raw-backed view 改造：

1. writer 的两层输入都来自同一 `NormalizedBatch`；
2. raw 与 serving 的全部业务列名称、类型和空值语义一致；审计列可通过 `fetched_at AS created_at/updated_at`、固定 `source` 等无状态投影得到；
3. 行身份和冲突键等价，不存在 serving 专属去重、版本选择或优先级策略；
4. 不存在行过滤、对象池过滤、聚合、派生日期、字段重命名、业务补算或多源融合；
5. 生产全量业务字段集合双向差集为 0，并且两层行数一致；大表必须按索引日期/键分块对账，不能用 catalog `reltuples` 代替；
6. 所有 serving 直接写消费者清零，只保留 raw writer；
7. raw 拥有 serving 查询所需的等价索引，或先补索引并通过代表性 `EXPLAIN (ANALYZE, BUFFERS)`；
8. 数据库 view/materialized view、函数、外键和外部 SQL 依赖已盘清；
9. 同名 serving view 能提供现有 ORM/API 需要的完整列和类型；
10. 改造后的 freshness、Ops Catalog、TaskRun `target_table` 和 Lake/export 路径均有明确契约测试。

任何一项不满足即 fail-closed，不删除 core/serving 物理表。

### 4.2 严格静态候选：26 组

以下 26 组满足“业务字段名称、类型、空值约束一致，且当前 `serving_conflict_resolution_policy=none`”的静态条件。目标物理表合计约 14,979,858,432 B，即 **13.95 GiB 毛收益**。

“生产等价已证”表示 2026-08-23 在只读事务和 30 秒 statement timeout 下，对该小表投影掉两层审计字段后完成全量行数及双向 `EXCEPT ALL`，结果均为 0。其余对象尚未进行全量数据证明。

| 数据集 | core/serving 物理表大小 | 生产数据等价 | raw 覆盖 serving 索引 | 当前阻塞或备注 |
| --- | ---: | --- | --- | --- |
| `broker_recommend` | 1.8 MiB | **已证** | 否，缺 3 组 | 先补索引与查询验收 |
| `daily_basic` | 4.42 GiB | 待分块证明 | 否，缺 3 组 | `dm.equity_daily_snapshot` materialized view 依赖；必须独立方案 |
| `dc_daily` | 154.22 MiB | **32 月及全表 13 字段双向差异为 0** | 是 | **M0/M1/M2/M3a/M3b 通过并结案；生产已切为 0 B raw-backed view** |
| `dc_index` | 76.4 MiB | 待证明 | 否，缺 2 组 | 业务和 unit planner 消费者较多 |
| `dc_member` | 4.52 GiB | 待分块证明 | 否，缺 2 组 | Wealth、Ops、QTF、DG source probe 直接读取；需性能专项 |
| `etf_basic` | 3.6 MiB | **已证** | 否，缺 4 组 | Ops ETF 池和行情查询依赖 |
| `etf_index` | 1.1 MiB | **已证** | 否，缺 2 组 | 当前消费者少，但先补索引 |
| `hk_basic` | 2.3 MiB | **已证** | 否，缺 3 组 | 当前消费者少，但先补索引 |
| `index_daily_basic` | 1.0 MiB | **已证** | 否，缺 1 组 | 当前有 1 个 active schedule |
| `index_weight` | 951.6 MiB | 待分块证明 | 否，缺 2 组 | Wealth 指数详情读取；当前有 1 个 active schedule |
| `margin` | 0.3 MiB | **已证** | 是 | **P1-B1-margin-M3a/M3b 通过；已切换为 raw-backed view，固定 probe 保持 active** |
| `moneyflow_cnt_ths` | 41.9 MiB | **已证** | 是 | **P1-B1-concept-M3a/M3b 通过；已切换为 raw-backed view** |
| `moneyflow_dc` | 1.05 GiB | 待分块证明 | 是 | 高收益候选；先核验历史漂移 |
| `moneyflow_ind_dc` | 84.27 MiB | **36 月及全表 18 字段双向差异为 0** | 是 | Wealth 板块概览与 Heat 直接读取；Lake 读取 raw |
| `moneyflow_ind_ths` | 9.3 MiB | **已证** | 是 | **P1-B1-industry-M3a/M3b 通过；已切换为 raw-backed view** |
| `moneyflow_mkt_dc` | 0.2 MiB | **已证** | 是 | **P1-B0-M3 通过；补充自然工作流数据链通过** |
| `moneyflow_ths` | 460.9 MiB | 待分块证明 | 是 | 一期 P1-B3；raw 固定留 SSD |
| `stk_auction_c` | 372.19 MiB | **20 月、2,255,593 行、9 业务字段双向差异为 0** | 是 | **M0/M1/M2/M3a 通过；生产 revision 158、0 B raw-backed view，已释放 390,266,880 B；M3b 待自然观察** |
| `stk_auction_o` | 364.64 MiB | **20 月、2,183,621 行、9 业务字段双向差异为 0** | 是 | **M0/M1/M2/M3a/M3b 通过并结案；生产已为 0 B raw-backed view，已释放 382,353,408 B** |
| `stk_limit` | 623.5 MiB | 待分块证明 | 是 | 一期 P1-B4；raw 固定留 SSD |
| `stock_st` | 71.0 MiB | 待证明 | 是 | **旁路修复服务仍双写，当前禁止改造** |
| `suspend_d` | 211.91 MiB | **320 月、640,504 行、6 业务字段双向差异为 0** | 是 | 多个 Wealth 查询消费者；`id` 逐行一致；M0/M1/M2/M3a/M3b 和 filter 修复完成并结案 |
| `ths_daily` | 511.6 MiB | 待分块证明 | 否，缺 1 组 | 一期外；后续在 Track A 与 raw 直出之间重新评审 |
| `ths_index` | 0.9 MiB | **已证** | 否，缺 2 组 | unit planner 与 Ops review 使用 |
| `ths_member` | 122.0 MiB | 待证明 | 否，缺 2 组 | Wealth/Ops 查询消费者较多 |
| `us_basic` | 6.2 MiB | **已证** | 否，缺 3 组 | 当前消费者少，但先补索引 |

2026-08-23 初始审计有 11 组完成生产全量等价验证：

| 数据集 | raw 行数 | serving 行数 | raw-serving 差集 | serving-raw 差集 |
| --- | ---: | ---: | ---: | ---: |
| `broker_recommend` | 7,449 | 7,449 | 0 | 0 |
| `etf_basic` | 3,395 | 3,395 | 0 | 0 |
| `etf_index` | 1,524 | 1,524 | 0 | 0 |
| `hk_basic` | 2,792 | 2,792 | 0 | 0 |
| `index_daily_basic` | 4,426 | 4,426 | 0 | 0 |
| `margin` | 1,149 | 1,149 | 0 | 0 |
| `moneyflow_cnt_ths` | 181,560 | 181,560 | 0 | 0 |
| `moneyflow_ind_ths` | 42,030 | 42,030 | 0 | 0 |
| `moneyflow_mkt_dc` | 812 | 812 | 0 | 0 |
| `ths_index` | 2,722 | 2,722 | 0 | 0 |
| `us_basic` | 21,475 | 21,475 | 0 | 0 |

2026-08-27 又完成 `moneyflow_ind_dc` 当前 339,268 行、36 个自然月和全表 18 字段的双向差集；2026-08-28 完成 `dc_daily` 当前 634,116 行、32 个自然月和全表 13 字段，`suspend_d` 当前 640,504 行、320 个自然月和包含 `id/row_key_hash` 的 6 个业务字段，以及 `stk_auction_o` 当前 2,183,621 行、20 个自然月和全部 9 个业务字段的双向差集；2026-08-29 又完成 `stk_auction_c` 当前 2,255,593 行、20 个自然月和全部 9 个业务字段的双向差集，差异均为 0。因此已有全量等价证据的严格候选共 16 组，但各次证据属于不同生产时点，不能伪装成同一快照求和。

初始 11 组的 core/serving 物理表毛量约 68.6 MiB；P1-B0 的 237,568 B、P1-B1 行业的 9,756,672 B、概念的 43,958,272 B、margin 的 344,064 B、`moneyflow_ind_dc` 的 88,358,912 B、`dc_daily` 的 161,710,080 B、`suspend_d` 的 222,199,808 B、`stk_auction_o` 的 382,353,408 B 与 `stk_auction_c` 的 390,266,880 B 已释放，累计 **1,299,185,664 B（1,239.00 MiB）**。该数字只表示已删除 relation 的确定性 catalog 字节，不用瞬时 `df` 差值替代；普通 vacuum 不计入释放量。

### 4.3 B 类：11 组投影或约束存在差异，暂不纳入严格名单

| 数据集 | 差异类型 | 当前结论 |
| --- | --- | --- |
| `adj_factor` | raw/target 空值约束存在差异 | 需单独证明并审计 `core` 消费者 |
| `fund_adj` | raw/target 空值约束存在差异 | 保留 Track A 迁 HDD 候选，不先做 raw 直出 |
| `index_basic` | 同名业务列类型存在差异 | 不能称为无差异 |
| `dc_hot` | target 保留 `raw_payload` 投影 | 需明确审计列合同和索引 |
| `kpl_concept_cons` | target 保留 `raw_payload` 投影 | 需单独设计 view 投影 |
| `kpl_list` | target 保留 `raw_payload` 投影 | 需单独设计 view 投影 |
| `limit_cpt_list` | target 保留 `raw_payload` 投影 | 需单独设计 view 投影 |
| `limit_list_d` | `limit`→`limit_type` 字段语义映射 | 不属于严格同构 |
| `limit_list_ths` | target 保留 `raw_payload` 投影 | 需单独设计 view 投影 |
| `limit_step` | target 保留 `raw_payload` 投影 | 需单独设计 view 投影 |
| `ths_hot` | target 保留 `raw_payload` 投影 | 需单独设计 view 投影 |

这些对象的 core/serving 物理表合计约 3.77 GiB。它们可能仍能通过显式 view 投影收口，但不属于用户本轮提出的“raw 与 core_serving 没有任何差异”集合，不进入首轮实施。

### 4.4 C 类：7 组存在明确业务语义，不允许按同构表处理

| 数据集/共享表 | 明确差异 | 结论 |
| --- | --- | --- |
| `daily` | `change`→`change_amount`，serving 还有 `source` | 需独立行情主链评审 |
| `dividend` | serving 使用 `event_key_hash` 等身份语义 | 保留事实表语义 |
| `stk_holdernumber` | serving 使用 `event_key_hash` | 保留事实表语义 |
| `stk_period_bar` 周/月共享 | 字段映射且同一 serving 表承载多个 Definition | 不能机械转换 |
| `stk_period_bar_adj` 周/月共享 | 字段映射且同一 serving 表承载多个 Definition | 不能机械转换 |
| `top_list` | `top_list_variant_resolution_v1` 冲突消解、variant 元数据 | **禁止 raw 直出替代已选择事实** |
| `trade_cal` | `cal_date`→`trade_date` 且为全系统日历基础 | 必须保留独立契约评审 |

### 4.5 raw 直出一期固定名单与内部批次

一期固定为以下 12 个数据集。顺序基于“先验证契约，再逐步增加消费者复杂度与释放收益”；生产精确行数和 serving 大小基线采样于 2026-08-23，`margin` 行数已于 2026-08-26 刷新。执行前必须刷新目标数据集，但名单和顺序不得在实施过程中临时扩大。

| 批次 | 顺序 | 数据集 | raw → serving | serving 大小 | raw/serving 精确行数 | 当前状态 |
| --- | ---: | --- | --- | ---: | ---: | --- |
| P1-B0 | 1 | `moneyflow_mkt_dc` | `raw_tushare.moneyflow_mkt_dc` → `core_serving.market_moneyflow_dc` | 0.2 MiB | 812 / 812 | **M3 生产验收及补充自然工作流数据链通过；已释放物理 serving 237,568 B** |
| P1-B1 | 2 | `moneyflow_ind_ths` | `raw_tushare.moneyflow_ind_ths` → `core_serving.industry_moneyflow_ths` | 9.3 MiB | 42,030 / 42,030 | **M3a/M3b 通过；已释放 9,756,672 B** |
| P1-B1 | 3 | `moneyflow_cnt_ths` | `raw_tushare.moneyflow_cnt_ths` → `core_serving.concept_moneyflow_ths` | 41.9 MiB | 181,560 / 181,560 | **M3a/M3b 通过；已释放 43,958,272 B** |
| P1-B1 | 4 | `margin` | `raw_tushare.margin` → `core_serving.equity_margin` | 0.3 MiB | 1,155 / 1,155 | **M3a/M3b 通过并结案；已释放 344,064 B** |
| P1-B2 | 5 | `moneyflow_ind_dc` | `raw_tushare.moneyflow_ind_dc` → `core_serving.board_moneyflow_dc` | 84.27 MiB | 339,268 / 339,268 | **M0/M1/M2/M3a/M3b 全部通过并结案；已释放 88,358,912 B** |
| P1-B2 | 6 | `dc_daily` | `raw_tushare.dc_daily` → `core_serving.dc_daily` | 154.22 MiB | 634,116 / 634,116 | **M0/M1/M2/M3a/M3b 全部通过并结案；已释放 161,710,080 B** |
| P1-B2 | 7 | `suspend_d` | `raw_tushare.suspend_d` → `core_serving.equity_suspend_d` | 211.91 MiB | 640,504 / 640,504 | **M0/M1/M2/M3a/M3b、消费者复审及 filter 前置修复完成并结案；已释放 222,199,808 B** |
| P1-B3 | 8 | `stk_auction_o` | `raw_tushare.stk_auction_o` → `core_serving.equity_auction_open` | 364.64 MiB | 2,183,621 / 2,183,621 | **M0/M1/M2/M3a/M3b 全部通过并结案；已释放 382,353,408 B** |
| P1-B3 | 9 | `stk_auction_c` | `raw_tushare.stk_auction_c` → `core_serving.equity_auction_close` | 372.19 MiB | 2,255,593 / 2,255,593 | **M0/M1/M2/M3a 通过；生产 revision 158、0 B Serving view，已释放 390,266,880 B；M3b 待自然观察** |
| P1-B3 | 10 | `moneyflow_ths` | `raw_tushare.moneyflow_ths` → `core_serving.equity_moneyflow_ths` | 460.9 MiB | 2,050,984 / 2,050,984 | 全字段等价待证 |
| P1-B4 | 11 | `moneyflow_dc` | `raw_tushare.moneyflow_dc` → `core_serving.equity_moneyflow_dc` | 1,072.8 MiB | 4,120,988 / 4,120,988 | 一期最高单表收益；全字段等价待证 |
| P1-B4 | 12 | `stk_limit` | `raw_tushare.stk_limit` → `core_serving.equity_stk_limit` | 623.5 MiB | 4,569,303 / 4,569,303 | 市场情绪消费者；全字段等价待证，最后执行 |
|  |  | **合计** |  | **3,548,766,208 B，约 3.305 GiB** |  |  |

内部批次大小仍以 2026-08-23 全名单同一时点基线统计：P1-B0 237,568 B；P1-B1 54,050,816 B（约 51.55 MiB）；P1-B2 471,261,184 B（约 449.43 MiB）；P1-B3 1,244,495,872 B（约 1.159 GiB）；P1-B4 1,778,720,768 B（约 1.657 GiB）。`moneyflow_ind_dc`、`dc_daily`、`suspend_d`、`stk_auction_o` 与 `stk_auction_c` 的各自 M0 当前 serving 值已分别刷新为 88,358,912 B、161,710,080 B、222,199,808 B、382,353,408 B 与 390,266,880 B；不同 M0 时点不混合重算批次合计。

批次不是数据库变更单元。每个数据集必须独立编码、独立 Alembic revision、独立维护窗口、独立生产授权和独立验收；任何时刻最多一个数据集进入生产 M3a。夜间 M3b 按一期 LLD 的统一台账集中核验，待触发或待核验不阻塞下一次生产切换；若已观察到共享 schedule/runtime/writer 异常且尚未解决，后续 M3a 必须停止。一期 12 张 raw 表全部保留在 SSD。

## 5. Track B 实施方案

### 5.1 每个数据集的开发改动

通过全部准入门禁后，每个数据集只允许以下最小改动：

1. 修改自身 `DatasetDefinition.storage` 为 raw-only + serving view 契约；
2. 保留 raw ORM/DAO，writer 只调用 raw DAO；
3. 保留原 core_serving ORM 作为只读 view 映射，确保 Biz/Ops/QTF 查询合同不变；
4. DAOFactory 中不得再把 serving DAO 暴露给 ingestion 写入路径；若只读查询 DAO 仍需要，必须明确只读用途；
5. freshness 和 TaskRun 的写入目标改为 raw 表，展示层继续表达“原始数据直出”；
6. Lake prod-raw-db 导出继续读取 raw，不因 serving view 改造改变源表；
7. 不修改源接口、fields、分页、date model、planner、unit 数或自动任务时间策略。

这不是共享 writer 重构。现有 `raw_only_upsert` 已经足够；每个数据集独立修改 Definition、迁移和测试，避免一次改动牵连全部 DatasetDefinition。

### 5.2 全量数据等价门禁

大表不做一次性无界全表 hash。应利用业务主键和已有日期索引分块：

1. 冻结对应 schedule 和 worker，确认开放 TaskRun 为 0；
2. 固定业务字段投影，显式排除 `api_name/fetched_at/raw_payload/created_at/updated_at/source` 等已审计的内部列；
3. 按交易日、公告日期或主键前缀分块，逐块比较 `count(*)`、身份键唯一数和双向 `EXCEPT ALL`；
4. 每块设置 statement timeout，记录首尾边界、行数和差异样本；
5. 全范围不得有缺口、重叠、raw-only 行或 serving-only 行；
6. 若发现差异，停止改造，先判断哪一层是正确事实。禁止为了通过门禁删除差异行或用 core 覆盖 raw；
7. 先在事务外完成有界分块预对账；migration 的同一个 DDL 事务必须按 raw → serving 获取 `SHARE` 锁以阻断两层 DML，并在锁内重复全范围分块双向差集；差异为 0 后才把 serving 锁升级为 `ACCESS EXCLUSIVE` 并切换 relation；
8. 锁内最终对账不得拆成多个可被写入穿插的事务。锁、读 I/O 或临时文件超出维护窗口预算时停止，不得降级为只比行数或抽样。

### 5.3 索引与查询性能门禁

当前 26 组中只有以下 13 组的 raw 索引签名已覆盖 serving 索引：

`dc_daily`、`margin`、`moneyflow_cnt_ths`、`moneyflow_dc`、`moneyflow_ind_dc`、`moneyflow_ind_ths`、`moneyflow_mkt_dc`、`moneyflow_ths`、`stk_auction_c`、`stk_auction_o`、`stk_limit`、`stock_st`、`suspend_d`。

其中 `stock_st` 仍因旁路写入被阻断。其余缺索引对象必须：

1. 从实际 Biz/Ops/QTF/DG SQL 提取过滤、join 和 order by；
2. 把 serving 独有且仍有业务价值的索引等价建立在 raw；
3. 新增索引占用要从“删除 serving 表”的毛收益中扣除；
4. 对代表性冷热查询分别记录迁移前后执行计划、耗时、shared hit/read 和返回行数；
5. 任何关键查询明显退化即停止 relation 替换，不用应用层补丁绕过。

### 5.4 migration 与发布顺序

每个数据集使用独立 Alembic revision；新增 migration 前必须重新读取真实 head。

维护窗口顺序固定为：

1. 暂停对应 schedule，停止会领取该数据集的 worker；Web 可以保持读取，relation 切换时应有短时维护预期；
2. 确认无开放 TaskRun、无旁路写入、无目标锁和长事务；
3. 完成事务外数据等价预对账、列合同、索引、依赖对象和查询样本基线；
4. 使用 `scripts/deploy-systemd.sh <branch> --maintenance-migration` 部署含 raw-only Definition 的同一版本；该模式的变更动作只包括拉代码、安装后端和执行 migration，另运行只读资源加载自检，不构建、不 seed、不同步 unit、不重启服务，worker 在 migration 完成前继续保持停止；
5. migration 先 fail-closed 验证 raw 为物理表、serving 为物理表、字段和依赖白名单完全匹配；
6. 同一 DDL 事务按 raw → serving 获取 `SHARE` 锁，在锁内重复全范围业务字段双向差集，0 差异后升级 serving 锁；
7. `DROP TABLE core_serving.<target>`，禁止 `CASCADE`，随后 `CREATE VIEW` 恢复完全相同的 serving relation 名和列合同；
8. 恢复 owner、SELECT grants、comments 和数据库拒写 trigger；读取 view 与 raw 的行数、确定性样本和代表性查询；确认 ORM/API 返回合同不变；
9. 回收直接消费者长连接池，避免旧 relation OID/缓存计划跨越切换窗口；
10. 启动 worker，执行一次受控最小同步，证明只写 raw、view 立即可见、TaskRun 行数与 freshness 正确；
11. 恢复 schedule 后把 M3b 写入一期 LLD 的统一夜间验收台账，在后续只读窗口集中查看首个有效自动任务和业务查询延迟；workflow 必须核对父 TaskRun 和目标 node，且不能把父任务的 step unit 当成目标数据集 source unit；probe 必须核对 probe/触发链。待触发或待核验不阻塞后续 M1/M2/M3a，只有已发现且未解决的共享运行链异常才阻塞下一次生产切换。

不能先改 Definition 并恢复 worker、过一段时间再迁移，否则 raw 会继续更新而旧 serving 物理表停止更新；也不能先把 serving 表换成 view 后继续运行旧双写代码，否则旧 writer 会尝试写只读 view。

自动 downgrade 禁止盲目重建空的 core/serving 表。DDL 事务提交前失败由 PostgreSQL 原子回滚；提交后的回退必须单独授权，从 raw 明确重建物理表并完成全量核对。

### 5.5 `daily_basic` 特殊门禁

`core_serving.equity_daily_basic` 被 `dm.equity_daily_snapshot` materialized view 依赖，因此：

1. 不得使用 `DROP ... CASCADE`；
2. 必须先审计 materialized view 定义、索引、刷新入口、刷新频率和 API 消费者；
3. 必须设计在同一维护窗口内重建依赖对象、恢复索引并完成 refresh 的明确方案；
4. 其 4.42 GiB 毛收益很高，但复杂度和业务影响也最高，不进入首批。

### 5.6 一期读取透明性边界

一期目标是让当前已知只读消费者在业务合同上无感，而不是让 relation 的物理身份无变化：

1. 原 `core_serving` 名称、业务列名、业务列类型和查询结果保持不变，Biz/ORM、QTF 和 DG 继续执行原 schema-qualified SQL；
2. Lake Console 一期 10 个已接入数据集本来就从 `raw_tushare` 读取，不切换数据源；`stk_auction_o/stk_auction_c` 当前未进入其 prod-raw 白名单，本专项不新增 Lake 能力；
3. relation 会从物理表变为普通 view，因此 OID、`relkind`、view 自身约束/索引和 catalog nullability 不是透明合同；查询依赖 raw 索引下推，必须做前后计划与时延验收；
4. serving 的 `created_at/updated_at` 将由 raw `fetched_at` 投影。当前已知 Biz/QTF/Lake/DG 消费者不读取这两个字段，但不承诺其历史值与旧 serving 表逐行相同；
5. serving view 必须由数据库拒写 trigger 阻断 `INSERT/UPDATE/DELETE`，不能只依赖 Definition 防止误写；
6. 仓库外 SQL、BI、人工脚本若依赖 OID、relkind、约束、审计时间或向 serving 写数据，必须在对应数据集实施前登记，否则该消费者不能宣称无感。

所以“读取透明”是每个数据集必须通过的验收结论，不是 migration 可以预设的事实。详细实现门禁见[生产 PostgreSQL raw 直出一期低层设计 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md)。

## 6. Milestone 与批次

| Milestone | 范围 | 目标 | 当前状态 |
| --- | --- | --- | --- |
| V2-M0 | 本文、代码/生产只读审计、一期 LLD | 固定一期名单、批次、透明性边界和实施门禁 | **本轮完成** |
| P1-B0 | `moneyflow_mkt_dc` | raw-backed serving view 契约试点 | **M3 生产验收及 schedule #4 补充自然运行数据链通过** |
| P1-GATE-SSE | schedule SSE 与在线 Alembic | 消除长事务并使锁等待有界 | **M1/M2/M3 通过；共享生产门禁已解除** |
| P1-B1 | `moneyflow_ind_ths` → `moneyflow_cnt_ths` → `margin` | 小表逐项验证；margin 最后处理 probe | **三项 M1/M2/M3a/M3b 全部通过并结案** |
| P1-B2 | `moneyflow_ind_dc` → `dc_daily` → `suspend_d` | 验证 Wealth/QTF/DG 直接消费者与特殊身份键 | **三项 M0/M1/M2/M3a/M3b 全部通过并结案** |
| P1-B3 | `stk_auction_o` → `stk_auction_c` → `moneyflow_ths` | 验证百万行级数据等价、切换和查询性能 | `stk_auction_o` 已结案；`stk_auction_c-M0/M1/M2/M3a` 已通过并完成生产切换，M3b 待自然观察；下一开发项为 `moneyflow_ths` M0 |
| P1-B4 | `moneyflow_dc` → `stk_limit` | 释放一期主要空间并验收市场情绪消费者 | B3 全部验收后逐项授权 |
| V2-A0 | `equity_daily_bar_light_p1990` | tablespace 微迁移先导 | Track B 后置，需单独授权 |
| V2-A1 | `p1991`～`p1999` | 释放约 178.3 MiB | A0 通过后授权 |
| V2-A2 | `fund_adj/ths_daily` | 后置 HDD 候选，理论约 828.9 MiB | 一期完成后重新评审 |
| V2-BX | `daily_basic/dc_member` 等一期外对象 | 独立依赖、索引和性能专项 | 不属于一期 |

`stock_st` 在旁路修复服务收口前不进入 raw 直出排序；`daily_basic/dc_member` 不因体积大而提前。一期之外的数据集不得在本 LLD 实施过程中顺手加入。

## 7. 验收与停止条件

### 7.1 Track A 验收

1. 迁移对象 OID 不变；
2. heap、全部物理索引及实际存在的 TOAST 对象均位于目标 tablespace；
3. 原始 relation 字节、索引有效性和确定性样本符合迁移前基线；
4. 白名单外对象未改变；
5. 根盘实际释放、HDD 实际增加与对象大小在文件系统误差范围内一致；
6. WAL 和文件系统水位稳定后才进入下一对象。

### 7.2 Track B 验收

1. raw 是唯一物理业务事实表；
2. 原 core_serving relation 为普通 view，不存在同名物理表；
3. Definition、writer、DAO、freshness 和 catalog 均投影 raw-only 事实；
4. 源端读取、归一化、raw 写入、reject、raw/view 行数五段一致；
5. 重复执行幂等，view 立即反映 raw 更新；
6. API/Ops/QTF/DG 代表性查询字段、行数、排序和延迟通过验收；
7. 没有运行代码继续尝试写 serving view；
8. 实际 SSD 释放量扣除新增 raw 索引后符合预估。

### 7.3 立即停止条件

出现任一情况即停止当前和后续批次：

1. 数据双向差集非 0、身份键不一致或发现未知旁路写入；
2. `DROP TABLE` 需要 `CASCADE` 才能执行；
3. raw 缺少关键索引且查询计划退化；
4. 有开放 TaskRun、目标锁、长事务或 schedule 无法暂停；
5. root 可用空间低于 3 GiB，WAL 异常增长或 HDD 路径/权限不符合预期；
6. migration、view、ORM 或 freshness 契约无法在同一发布窗口闭环；
7. 任一业务读取合同或返回行数发生不可解释变化。

## 8. 风险与待拍板项

### 8.1 已固定的设计口径

1. 新工作只进入 v2，不再扩写 v1。
2. raw 直出不是让业务代码直接查询 raw schema，而是保留原 serving 名称并改为普通 view。
3. 只有完成严格等价证明的单源事实表才能去重；B/C 类不混入首批。
4. 每个数据集独立 Definition、migration、测试和生产授权，不做一次性共享重构或批量 drop。
5. Track A 与 Track B 分开执行，不在一个维护窗口同时搬表和替换 relation。
6. 当前优先 raw 直出一期；名单和顺序固定为第 4.5 节 12 项及 P1-B0～P1-B4。
7. 一期 12 张 raw 表全部留 SSD，不再纳入 Track A。
8. 对当前已知普通只读业务与 Lake/DG 查询，目标是代码无感；不承诺 OID、relkind、约束 catalog 和历史 `created_at/updated_at` 值透明。

### 8.2 后续执行前需要单独拍板

1. P1-B0 已按“业务读取合同透明、物理 relation 身份和历史审计时间不透明”的边界完成生产验收；后续数据集继续沿用该边界，但不得复用 B0 的行数上限或性能结论；
2. P1-B1 三项 M0/M1/M2/M3a/M3b、`P1-GATE-SSE-M1/M2/M3` 与 `P1-B2-moneyflow_ind_dc` 的 M0/M1/M2/M3a/M3b 均已完成；`moneyflow_ind_dc` 的维护窗口顺序偏差仍保留为历史教训，但不再是开放门禁。后续不得复制 margin 的 probe、THS 的 5,000/20,000 行上限或小表性能结论；
3. `moneyflow_ind_dc` 的 Heat 时间口径已固定为“收盘 21:00、资金流 20:00”，并已由 `2026-08-27` 自然运行证明；`dc_daily` 与 `suspend_d` 均已完成独立 M0/M1/M2/M3a/M3b 并结案；`suspend_d` 的 `suspend_type` 前置修复也已随生产 commit `9d32b266` 生效；
4. 仓库外 SQL、BI、人工脚本和 catalog 工具仍需由运营持续登记；P1-B0 未发现仓库内异常消费者不能证明仓库外消费者不存在；
5. Track A 与一期外 `daily_basic/dc_member` 是否推进，继续后置，不由本 LLD 自动授权。

## 9. 本轮未完成事项与残余不确定性

1. 一期 12 组已完成精确行数核对；`moneyflow_mkt_dc`、`moneyflow_ind_ths`、`moneyflow_cnt_ths`、`margin`、`moneyflow_ind_dc`、`dc_daily`、`suspend_d`、`stk_auction_o`、`stk_auction_c` 完成全部业务字段双向差集，其余 3 组内容等价待有界分块证明。行数一致不能证明内容一致。
2. P1-B0 已完成 M3，并补充通过 schedule #4 的市场资金节点自然运行数据链；P1-B1 行业、概念和 margin 均已完成 M1/M2/M3a/M3b。margin 的自然 TaskRun `9573` 于固定窗口成功处理 `2026-08-26`，当日只触发 1 次。本次历史工作流 M3b TaskRun 因部署锁等待于 20:07 而非 20:00 创建，不能作为准点性证据。概念 M3a 的自动 migration 偏差和 SSE 长事务阻塞 migration 150 均已记录；共享问题现已完成 M1 代码收口、M2 隔离真实 migration 验收和 M3 生产 SSE/有界锁等待验收。
3. 未核验所有仓库外 SQL 消费者；这是 P1-B0 的残余运营风险，也是每个后续数据集的独立准入门禁。
4. 没有整库可恢复备份条件时，极端磁盘/实例故障风险仍存在；本文只能通过小对象、单事务和 fail-closed 降低人为操作风险。
5. SSD 扩容后的 51.68 GiB 是 2026-08-24 快照；`moneyflow_ind_dc` M0 时为 48.78 GiB。磁盘、任务和锁状态会持续漂移，任何未来执行必须重新采样，不能因名义容量升至 270 GB 而跳过容量门禁。
6. 2026-08-26 SSE/有界锁等待 M3 已关闭共享迁移基础设施问题；2026-08-27 `moneyflow_ind_dc` revision 153 又被完整部署在未暂停 schedule/worker 时提前应用。切换后没有观察到数据或查询损坏，但该流程偏差必须保留，并再次证明“完整部署”不能承担维护窗口前的代码安装动作。
7. Heat 上游时间合同已由 schedule #4/#36 在 `2026-08-27` 的自然成功链闭环；`moneyflow_ind_dc` 不再有开放验收项。`dc_daily`、`suspend_d` 与 `stk_auction_o` 的 M0/M1/M2/M3a/M3b 均已完成并结案；`stk_auction_o` 的标准部署提前迁移偏差继续保留。`stk_auction_c-M0/M1/M2/M3a` 已通过并完成生产 revision 158 切换，M3b 已登记自然观察；下一开发阶段是 `P1-B3-moneyflow_ths-M0`，需另行授权。
8. 两个 `2026-08-28` 父 workflow 中的 `anns_d` 节点出现 69/184 行 `write.duplicate_conflict_key_in_batch:row_key_hash`，已另列独立只读数据质量审计 TODO；尚未证明六个 source fields 完全相同，不能直接按完全重复结案。

## 10. 相关基线

1. [Core Serving + Serving Light 分层设计 v1](/Users/congming/github/goldenshare/docs/architecture/core-serving-light-design-v1.md)
2. [数据集发布治理规范 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)
3. [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
4. [股票历史分钟行情存储瘦身与滚动冷热治理方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-storage-slimming-plan-v1.md)
5. [生产 PostgreSQL raw 直出一期低层设计 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md)
6. [PostgreSQL 16 `ALTER TABLE`](https://www.postgresql.org/docs/16/sql-altertable.html)
7. [PostgreSQL 16 `ALTER INDEX`](https://www.postgresql.org/docs/16/sql-alterindex.html)
8. [PostgreSQL 16 Tablespaces](https://www.postgresql.org/docs/16/manage-ag-tablespaces.html)
