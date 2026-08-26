# 生产 PostgreSQL 存储空间优化治理专项 v2

- 版本：v2
- 状态：P1-B0 市场资金与 P1-B1 行业/概念资金的自然工作流数据链验收已通过；`P1-GATE-SSE-M1/M2` 已完成，生产 M3 尚未授权；`margin` 仍未进入 M1，后续生产 M3a 继续受共享门禁约束
- 更新时间：2026-08-26
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

2026-08-24 P1-B1 首项 `moneyflow_ind_ths` 维护窗口开始前根盘可用 4,461,560 KiB，验收后 4,485,480 KiB；同样只以 PostgreSQL catalog 证明原 serving heap/index 合计释放 9,756,672 B，不把 `df` 瞬时变化当作精确收益。第二项 `moneyflow_cnt_ths` 的原 serving 物理基线为 43,958,272 B，切换后 view 为 0 B。三项累计已释放 serving 物理 relation 53,952,512 B；概念 M3a 验收时根盘仍为 98%，因此不能把 catalog 毛释放量等同于操作系统即时可用空间增长。

2026-08-24 运营为缓解根盘容量压力，将 Prod SSD 名义容量扩充到 270 GB；18:07+08 只读复核的实际文件系统容量如下：

| 文件系统 | 总容量 | 已用 | 可用 | 使用率 |
| --- | ---: | ---: | ---: | ---: |
| 根盘 `/dev/vda2`，挂载 `/` | 285,230,424,064 B，约 265.66 GiB | 218,025,771,008 B | 55,484,956,672 B，约 51.68 GiB | 80% |
| HDD `/dev/vdb`，挂载 `/data/disk` | 422,549,692,416 B，约 393.53 GiB | 61,256,343,552 B | 339,801,735,168 B，约 316.46 GiB | 16% |

本次扩容是应急容量缓冲，不是本专项迁移收益，也不改变逐表独立维护窗口、完整对账和停止条件。新增成本约人民币 1,000 元为运营反馈口径，不是数据库可审计指标；后续仍须优先消除重复物理存储，避免把扩容当作治理完成。

2026-08-26 `P1-GATE-SSE-M1` 开始前再次只读复核：根盘约 266 GiB 总量、206 GiB 已用、50 GiB 可用、81%，HDD 约 394 GiB 总量、62 GiB 已用、312 GiB 可用、17%；生产与本地 Alembic head 均为 `20260825_000151`，没有 queued/running/canceling TaskRun。`margin` raw/serving 仍是两张 `pg_default` 物理表，大小分别为 360,448 B/344,064 B，均为 1,149 行和 1,149 个唯一身份，9 个业务字段全量双向差集为 0。该快照只用于 M1 上下文校准，不授权生产切换。

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
| `moneyflow_ind_ths` | 物理表，`pg_default`，10,657,792 B | 普通 view，0 B，直接读取 raw | 42,030 / 42,030 | `2024-09-10..2026-08-21` | P1-B1-industry-M3a 已完成；M3b 待 20:00 后核验 |
| `moneyflow_cnt_ths` | 物理表，`pg_default`，47,153,152 B | 普通 view，0 B，直接读取 raw | 181,560 / 181,560 | `2024-09-10..2026-08-21` | P1-B1-concept-M3a 已完成；M3b 待 20:00 后核验 |
| `margin` | 物理表，`pg_default`，352,256 B | 物理表，`pg_default`，335,872 B | 1,146 / 1,146 | `2025-01-02..2026-08-21` | 仅 M0 等价审计完成；尚未进入 M1 |

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

M1 只证明代码合同，尚未部署。隔离 PostgreSQL M2 与生产 M3 均未授权；因此它不阻塞 `margin` M1/M2 的开发和隔离验证，但在真实 SSE 长连接与锁冲突验收闭环前，仍阻塞任何后续生产 M3a。禁止把 M1 完成解释为发布流程已经安全。

### 2.10 2026-08-26 `P1-GATE-SSE-M2` 隔离验收

M2 在仅 Unix socket 可访问的 PostgreSQL 18.4 临时实例，以非超级用户和独立 env 完成；数据库、用户、server address、端口、data directory 与 HDD tablespace 六项身份均已核对，没有连接 Prod、请求 Tushare、创建 TaskRun、部署服务或修改生产 schedule。

真实 HTTP SSE 跨越多个 2 秒周期返回 2 个数据事件和 2 个 ping；216 次数据库采样只捕获 1 次 0.997ms 的查询结束到 rollback 瞬时窗口，连续采样 1 次，没有 idle relation lock，流结束后 `idle in transaction=0`。独立连接持有 `ops.schedule AccessShareLock` 时，revision 150 于 15.815 秒 lock timeout 失败；revision 149、legacy probe 字段、物理表类型和约束不存在状态全部原子保留。释放锁后 migration 成功，probe 字段归一化、约束 validated，违规写入以 SQLSTATE `23514` 拒绝并回滚，新会话 `lock_timeout=0`。最终升级到当前 head 151 成功，167 项回归通过。

M2 据此通过；共享生产门禁只剩独立授权的 M3。M3 未完成前，不得把隔离证据外推为生产已安全，也不得进入任何后续数据集生产 M3a。

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
| 2 | `raw_tushare.stk_auction_o` | 389.1 MiB | raw 直出 P1-B3 | raw 必须留 SSD；从 Track A 移除 |
| 3 | `raw_tushare.stk_auction_c` | 397.3 MiB | raw 直出 P1-B3 | raw 必须留 SSD；从 Track A 移除 |
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
| `dc_daily` | 154.0 MiB | 待证明 | 是 | 可作为中等批次候选 |
| `dc_index` | 76.4 MiB | 待证明 | 否，缺 2 组 | 业务和 unit planner 消费者较多 |
| `dc_member` | 4.52 GiB | 待分块证明 | 否，缺 2 组 | Wealth、Ops、QTF、DG source probe 直接读取；需性能专项 |
| `etf_basic` | 3.6 MiB | **已证** | 否，缺 4 组 | Ops ETF 池和行情查询依赖 |
| `etf_index` | 1.1 MiB | **已证** | 否，缺 2 组 | 当前消费者少，但先补索引 |
| `hk_basic` | 2.3 MiB | **已证** | 否，缺 3 组 | 当前消费者少，但先补索引 |
| `index_daily_basic` | 1.0 MiB | **已证** | 否，缺 1 组 | 当前有 1 个 active schedule |
| `index_weight` | 951.6 MiB | 待分块证明 | 否，缺 2 组 | Wealth 指数详情读取；当前有 1 个 active schedule |
| `margin` | 0.3 MiB | **已证** | 是 | 当前有 1 个 active schedule |
| `moneyflow_cnt_ths` | 41.9 MiB | **已证** | 是 | **P1-B1-concept-M3a/M3b 通过；已切换为 raw-backed view** |
| `moneyflow_dc` | 1.05 GiB | 待分块证明 | 是 | 高收益候选；先核验历史漂移 |
| `moneyflow_ind_dc` | 83.5 MiB | 待证明 | 是 | Wealth 板块查询直接读取 |
| `moneyflow_ind_ths` | 9.3 MiB | **已证** | 是 | **P1-B1-industry-M3a/M3b 通过；已切换为 raw-backed view** |
| `moneyflow_mkt_dc` | 0.2 MiB | **已证** | 是 | **P1-B0-M3 通过；补充自然工作流数据链通过** |
| `moneyflow_ths` | 460.9 MiB | 待分块证明 | 是 | 一期 P1-B3；raw 固定留 SSD |
| `stk_auction_c` | 364.1 MiB | 待分块证明 | 是 | 一期 P1-B3；raw 固定留 SSD |
| `stk_auction_o` | 361.9 MiB | 待分块证明 | 是 | 一期 P1-B3；raw 固定留 SSD |
| `stk_limit` | 623.5 MiB | 待分块证明 | 是 | 一期 P1-B4；raw 固定留 SSD |
| `stock_st` | 71.0 MiB | 待证明 | 是 | **旁路修复服务仍双写，当前禁止改造** |
| `suspend_d` | 211.9 MiB | 待分块证明 | 是 | 多个 Wealth 查询消费者 |
| `ths_daily` | 511.6 MiB | 待分块证明 | 否，缺 1 组 | 一期外；后续在 Track A 与 raw 直出之间重新评审 |
| `ths_index` | 0.9 MiB | **已证** | 否，缺 2 组 | unit planner 与 Ops review 使用 |
| `ths_member` | 122.0 MiB | 待证明 | 否，缺 2 组 | Wealth/Ops 查询消费者较多 |
| `us_basic` | 6.2 MiB | **已证** | 否，缺 3 组 | 当前消费者少，但先补索引 |

11 组已完成生产全量等价验证：

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

这 11 组在初始审计时的 core/serving 物理表毛量约 68.6 MiB，其中 P1-B0 的 237,568 B、P1-B1 行业的 9,756,672 B 与概念的 43,958,272 B 已释放，累计 53,952,512 B。它们适合验证契约和发布链路，但不能单靠这些小表解决容量告警。

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
| P1-B1 | 4 | `margin` | `raw_tushare.margin` → `core_serving.equity_margin` | 0.3 MiB | 1,149 / 1,149 | 全字段等价已证；固定 probe；共享 gate M1 已完成，margin M1 尚未开始 |
| P1-B2 | 5 | `moneyflow_ind_dc` | `raw_tushare.moneyflow_ind_dc` → `core_serving.board_moneyflow_dc` | 83.5 MiB | 336,175 / 336,175 | Wealth 直接消费；全字段等价待证 |
| P1-B2 | 6 | `dc_daily` | `raw_tushare.dc_daily` → `core_serving.dc_daily` | 154.0 MiB | 629,993 / 629,993 | Wealth/QTF/DG 直接消费；全字段等价待证 |
| P1-B2 | 7 | `suspend_d` | `raw_tushare.suspend_d` → `core_serving.equity_suspend_d` | 211.9 MiB | 640,481 / 640,481 | 多个 Wealth 消费者；必须核对 `id`；全字段等价待证 |
| P1-B3 | 8 | `stk_auction_o` | `raw_tushare.stk_auction_o` → `core_serving.equity_auction_open` | 361.9 MiB | 2,161,633 / 2,161,633 | 当前直接消费者少；全字段等价待证 |
| P1-B3 | 9 | `stk_auction_c` | `raw_tushare.stk_auction_c` → `core_serving.equity_auction_close` | 364.1 MiB | 2,227,843 / 2,227,843 | 当前直接消费者少；全字段等价待证 |
| P1-B3 | 10 | `moneyflow_ths` | `raw_tushare.moneyflow_ths` → `core_serving.equity_moneyflow_ths` | 460.9 MiB | 2,050,984 / 2,050,984 | 全字段等价待证 |
| P1-B4 | 11 | `moneyflow_dc` | `raw_tushare.moneyflow_dc` → `core_serving.equity_moneyflow_dc` | 1,072.8 MiB | 4,120,988 / 4,120,988 | 一期最高单表收益；全字段等价待证 |
| P1-B4 | 12 | `stk_limit` | `raw_tushare.stk_limit` → `core_serving.equity_stk_limit` | 623.5 MiB | 4,569,303 / 4,569,303 | 市场情绪消费者；全字段等价待证，最后执行 |
|  |  | **合计** |  | **3,548,766,208 B，约 3.305 GiB** |  |  |

内部批次大小：P1-B0 237,568 B；P1-B1 54,050,816 B（约 51.55 MiB）；P1-B2 471,261,184 B（约 449.43 MiB）；P1-B3 1,244,495,872 B（约 1.159 GiB）；P1-B4 1,778,720,768 B（约 1.657 GiB）。

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
| P1-GATE-SSE | schedule SSE 与在线 Alembic | 消除长事务并使锁等待有界 | **M1/M2 完成；生产 M3 尚未授权，生产门禁未解除** |
| P1-B1 | `moneyflow_ind_ths` → `moneyflow_cnt_ths` → `margin` | 小表逐项验证；margin 最后处理 probe | **行业与概念 M3a/M3b 通过；margin 尚未进入 M1；共享 gate M3 阻塞后续生产 M3a** |
| P1-B2 | `moneyflow_ind_dc` → `dc_daily` → `suspend_d` | 验证 Wealth/QTF/DG 直接消费者与特殊身份键 | B1 全部验收后逐项授权 |
| P1-B3 | `stk_auction_o` → `stk_auction_c` → `moneyflow_ths` | 验证百万行级数据等价、切换和查询性能 | B2 全部验收后逐项授权 |
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
2. P1-B1 三项 M0 已完成，行业与概念 M3a/M3b 已通过；`P1-GATE-SSE-M1/M2` 已完成，生产 M3 尚未授权；下一项数据集开发仍是 `margin` 的独立 M1。margin 必须按 probe 契约独立执行，禁止因同属 B1 合并 migration、维护窗口或自动化处理口径；margin M1/M2 可准备，但共享 gate 的 M3 闭环前生产 M3a 继续暂停；
3. 仓库外 SQL、BI、人工脚本和 catalog 工具仍需由运营持续登记；P1-B0 未发现仓库内异常消费者不能证明仓库外消费者不存在；
4. Track A 与一期外 `daily_basic/dc_member` 是否推进，继续后置，不由本 LLD 自动授权。

## 9. 本轮未完成事项与残余不确定性

1. 一期 12 组已完成精确行数核对；`moneyflow_mkt_dc`、`moneyflow_ind_ths`、`moneyflow_cnt_ths`、`margin` 完成全部业务字段双向差集，其余 8 组内容等价待有界分块证明。行数一致不能证明内容一致。
2. P1-B0 已完成 M3，并补充通过 schedule #4 的市场资金节点自然运行数据链；P1-B1 行业与概念均已完成 M1/M2/M3a/M3b；margin 尚未编码。本次 M3b TaskRun 因部署锁等待于 20:07 而非 20:00 创建，不能作为准点性证据。概念 M3a 的自动 migration 偏差和 SSE 长事务阻塞 migration 150 均已记录；共享问题已完成 M1 代码收口和 M2 隔离真实验收，但仍须生产 M3 才能进入后续生产切换。
3. 未核验所有仓库外 SQL 消费者；这是 P1-B0 的残余运营风险，也是每个后续数据集的独立准入门禁。
4. 没有整库可恢复备份条件时，极端磁盘/实例故障风险仍存在；本文只能通过小对象、单事务和 fail-closed 降低人为操作风险。
5. SSD 扩容后的 51.68 GiB 可用空间只是 2026-08-24 18:07+08 快照；当前磁盘、任务和锁状态都会漂移，任何未来执行必须重新采样，不能因名义容量升至 270 GB 而跳过容量门禁。
6. 2026-08-26 只读复核时生产 Alembic 已升至 revision 151，历史版本差异已消除；`P1-GATE-SSE-M1` 代码尚未部署，M2 仅形成隔离验证证据。后续生产 M3a 的剩余共享门禁是“生产 M3 证明 SSE 无跨轮询长期事务、锁等待 15 秒 fail-fast 且完整回滚，以及维护窗口顺序回归”。

## 10. 相关基线

1. [Core Serving + Serving Light 分层设计 v1](/Users/congming/github/goldenshare/docs/architecture/core-serving-light-design-v1.md)
2. [数据集发布治理规范 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)
3. [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
4. [股票历史分钟行情存储瘦身与滚动冷热治理方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-storage-slimming-plan-v1.md)
5. [生产 PostgreSQL raw 直出一期低层设计 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md)
6. [PostgreSQL 16 `ALTER TABLE`](https://www.postgresql.org/docs/16/sql-altertable.html)
7. [PostgreSQL 16 `ALTER INDEX`](https://www.postgresql.org/docs/16/sql-alterindex.html)
8. [PostgreSQL 16 Tablespaces](https://www.postgresql.org/docs/16/manage-ag-tablespaces.html)
