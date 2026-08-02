# 生产 PostgreSQL 存储空间优化治理专项 v1

状态：一期与新闻快讯整表下沉均已执行并验收；重复 core 物理表收口第一批待实施
更新时间：2026-08-03
范围：生产 PostgreSQL `goldenshare` 的 SSD/HDD 存储分层与重复物理存储治理。
不在范围：删除、清空 raw 业务数据；改变数据集请求语义；修改 API 或前端业务行为。

---

## 1. 专项目标

在不改变下游访问方式的前提下，缓解生产 SSD 容量压力：

1. 将确认属于冷数据的 PostgreSQL 关系迁移到现有 HDD tablespace `gs_raw_cold_hdd`。
2. 对 HDD 迁移，保持 schema、表名、索引名、view 定义、DAO、API 和数据集写入契约不变。
3. 对重复 core 收口，保持 `core_serving` 查询名称、ORM、DAO、API 和数据集外部契约不变；允许删除其重复物理表和索引，并改为同名 view。
4. 当前年份持续读写的数据留在 SSD；不能为了释放空间而把热数据整体降到 HDD。
5. 每次迁移只处理明确白名单中的表和索引，先验证，再进入下一批。
6. 对仅复制 raw 业务字段的 serving 物理表，可改为 raw-backed serving view，删除重复写入和重复物理表；下游仍只读取原 `core_serving` 名称。

这里的“下游透明”只表示 SQL 与应用契约不变。历史数据迁到 HDD 后，访问该历史数据的 I/O 延迟可能升高；这属于预期性能取舍，不能被表名不变掩盖。

## 2. 固定原则

1. 优先迁移已按年份分区且不再写入的历史分区。
2. 未分区表若仍包含 2026 热数据，不允许以“迁冷数据”为名整表下沉。
3. 只有同时满足“当前无 Biz API 直接查询路径、低活跃、无持续高频维护”的整表数据集，才进入整表候选。
4. 表 heap 与该表全部索引必须迁到同一 tablespace；禁止只迁 heap 或遗漏索引。
5. 迁移前必须确认没有相关 `TaskRun` 运行、排队或取消中，也没有长事务访问目标关系。
6. 不使用清表、复制后删除、表重建或自定义兼容 view 作为一期手段。
7. 生产 DDL 必须逐对象执行、逐对象验收；不得批量盲跑。

## 3. 一期审计事实

审计时间：2026-08-02。所有审计均通过 `bash scripts/psql-remote.sh` 与 `ssh goldenshare-prod` 只读执行。

| 项目 | 审计结果 |
| --- | --- |
| SSD 根分区 `/` | 217GB，总已用 202GB，可用约 6.1GB，使用率 98% |
| HDD `/data/disk` | 394GB，已用 36GB，可用约 338GB，使用率 10% |
| HDD tablespace | `gs_raw_cold_hdd`，路径 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd` |
| 已迁对象 | `raw_tushare.cyq_chips` 及其 3 个索引，总计约 55GB，已位于 HDD |
| 统计口径 | `pg_total_relation_size`，包含 heap、Toast 与索引；`pg_stat_user_tables` 为数据库累计统计，`stats_reset` 为空 |
| 执行资源 | 一期目标表均由 `goldenshare_user` 持有，该用户具备 `gs_raw_cold_hdd` 的 `CREATE` 权限 |
| WAL 约束 | `max_wal_size=1GB`、`checkpoint_timeout=5min`、未启用归档；迁移必须逐对象自动提交并立即复验，禁止把一期对象放入一个长事务 |

### 3.1 已排除的高占用对象

| 对象 | 大小 | 审计结论 | 不进入一期的原因 |
| --- | ---: | --- | --- |
| `raw_tushare.index_mins` | 16GB | 高活跃 | 约 7250 万次索引扫描、6486 万次写入；整表下沉会同时拖慢 2026 数据 |
| `raw_tushare.news` | 7.1GB | 高活跃 | 业务新闻查询链路直接消费，且持续更新 |
| `raw_tushare.stk_factor_pro` | 6.5GB | 高活跃 | 复权因子变化会触发历史重刷 |
| `raw_tushare.etf_sh_cons` | 1.2GB | 持续维护 | 2026-08-01 仍有自动分析/写入迹象 |
| `raw_tushare.major_news` | 2.4GB | 持续维护 | 近期持续更新，不是冷数据 |
| `core_serving` 主行情、日线、资金流表 | 多张 3GB 以上 | 服务层热数据 | 业务查询或主计算链路仍直接使用 |

这些对象若要做到“仅迁非 2026 数据”，必须先单独设计按年份分区改造；该改造不属于一期。

## 4. 一期迁移白名单

### 4.1 A 组：历史轻量日线分区

| 父表 | 迁移对象 | 数据范围 | 当前 SSD 占用 | 判断 |
| --- | --- | --- | ---: | --- |
| `core_serving_light.equity_daily_bar_light` | `p2000` 至 `p2025` 共 26 个叶分区及各自索引 | 2025 年及以前 | 约 5.60GiB | 已按年份分区，历史分区不再承接当年写入，优先级最高 |

`p2026` 保留在 `pg_default`。当前生产 catalog 没有该父表的默认分区。该组迁移后，应用仍通过父表查询，无需改代码。

### 4.2 B 组：确认可整表下沉的冷 raw 数据集

下列三张 raw 表均有 `core_serving_light` 普通 view，当前代码审计未发现 `src/biz/**` 的直接 ORM 查询路径；统计上也未显示近期高频更新。

| raw 表 | serving 对象 | 审计时 SSD 占用 | 读写活跃度摘要 | 一期结论 |
| --- | --- | ---: | --- | --- |
| `raw_tushare.research_report` | `core_serving_light.research_report` view | 655MB | 约 24 万次索引扫描、1 万次更新；最后自动分析 2026-05-14 | 已迁移 |
| `raw_tushare.irm_qa_sz` | `core_serving_light.irm_qa_sz` view | 620MB | 约 78 万次索引扫描、156 次更新；最后自动分析 2026-05-14 | 已迁移 |
| `raw_tushare.irm_qa_sh` | `core_serving_light.irm_qa_sh` view | 292MB | 约 35 万次索引扫描、1.5 万次更新；最后自动分析 2026-07-20 | 已迁移 |

B 组不包含 `raw_tushare.anns_d`。它虽没有确认的 Biz 直接查询路径，但约 1.9 百万次索引扫描，先保留在 SSD，待 A/B 组真实迁移验收后再单独评估。

### 4.3 一期收益

| 组别 | 预计释放 SSD |
| --- | ---: |
| A 组历史轻量日线分区 | 约 5.60GiB |
| B 组整表冷数据集 | 约 1.53GiB |
| 一期合计 | **约 7.13GiB** |

以审计时 SSD 可用约 6.1GB 计算，一期完成后理论可用空间约 13GB。文件系统保留空间、并发写入和迁移期间临时 I/O 会影响实际数值，因此只把该值作为容量目标，不作为保证值。

## 5. 一期执行方案

### 5.1 迁移前门禁

以下检查必须在每一组迁移前重新执行；任一项不满足即停止，不允许边写入边迁移。

1. 确认 SSD/HDD 空间仍满足目标对象大小。
2. 确认 `gs_raw_cold_hdd` 存在且可用。
3. 确认本组关联数据集不存在 `queued`、`running`、`canceling` 的 TaskRun。
4. 确认没有长事务或长查询占用目标表。
5. 枚举目标表的真实索引清单，生成本次人工执行白名单；不得根据历史文档猜索引名。
6. 每条 `ALTER TABLE` 或 `ALTER INDEX` 单独执行并自动提交；执行后先复查对象 tablespace、SSD/HDD 空间和锁状态，确认正常后再处理下一个对象。
7. 每条迁移语句使用 `lock_timeout='15s'`；15 秒内拿不到锁立即停止本轮，不等待、不终止业务会话。

示例只读检查：

```bash
ssh goldenshare-prod 'df -hT / /data/disk'
bash scripts/psql-remote.sh -c "
select id, resource_key, status
from ops.task_run
where resource_key in ('research_report', 'irm_qa_sz', 'irm_qa_sh')
  and status in ('queued', 'running', 'canceling')
order by requested_at desc;"
```

### 5.2 A 组执行步骤

1. 在维护窗口内逐个迁移 `core_serving_light.equity_daily_bar_light_p2000` 至 `..._p2025`。
2. 对每个分区，读取 `pg_index` 枚举其索引后逐个迁移索引。
3. 每完成一个分区，立即核验表和全部索引均为 `gs_raw_cold_hdd`，再进入下一个分区。
4. `p2026` 不得执行迁移。

示意 DDL，实际执行前必须以本次 catalog 结果替换对象名：

```sql
ALTER TABLE core_serving_light.equity_daily_bar_light_p2025
  SET TABLESPACE gs_raw_cold_hdd;

ALTER INDEX core_serving_light.<p2025 的真实索引名>
  SET TABLESPACE gs_raw_cold_hdd;
```

### 5.3 B 组执行步骤

按以下顺序逐表完成，避免同时锁多张表：

1. `raw_tushare.research_report`
2. `raw_tushare.irm_qa_sz`
3. `raw_tushare.irm_qa_sh`

每张表的步骤相同：

1. 再次确认该数据集没有运行中 TaskRun。
2. 执行 `ALTER TABLE ... SET TABLESPACE gs_raw_cold_hdd`。
3. 从 `pg_index` 读取该表当前全部索引，逐个执行 `ALTER INDEX ... SET TABLESPACE gs_raw_cold_hdd`。
4. 查询 raw 表和 `core_serving_light` view 的最小样本，确认 view 可读。
5. 记录迁移耗时、迁移前后磁盘空间、对象 tablespace 与读查询结果。

示意 DDL：

```sql
ALTER TABLE raw_tushare.research_report
  SET TABLESPACE gs_raw_cold_hdd;

ALTER INDEX raw_tushare.<research_report 的真实索引名>
  SET TABLESPACE gs_raw_cold_hdd;
```

### 5.4 验收

每组完成后必须同时满足：

1. 白名单中的表 heap 和全部索引都位于 `gs_raw_cold_hdd`。
2. 白名单外对象仍保留原 tablespace，尤其是 `p2026`。
3. 对应 `core_serving_light` view 可正常做最小只读查询。
4. 相关数据集可继续被 Ops 查询和维护；没有新建 TaskRun 失败。
5. SSD 可用空间达到或接近本组收益目标，HDD 增量与迁移对象总量相符。

### 5.5 回滚

出现不可接受的性能问题时，可按同一对象白名单反向执行：

```sql
ALTER TABLE <目标表> SET TABLESPACE pg_default;
ALTER INDEX <目标索引> SET TABLESPACE pg_default;
```

回滚前必须重新确认 SSD 剩余空间足以承载目标对象。不得通过删除数据、重建表或关闭约束来“腾出回滚空间”。

### 5.6 A 组执行记录

执行日期：2026-08-02。

1. 已逐对象迁移 `core_serving_light.equity_daily_bar_light_p2000` 至 `..._p2025` 的 26 个历史分区及其 78 个索引。
2. 迁移后 104 个对象均位于 `gs_raw_cold_hdd`；`p2026` 经 catalog 确认仍位于 `pg_default`。
3. 已对最早历史分区读取 `000001.SZ / 2000-01-04`，对最新迁移分区读取 `000001.SZ / 2025-12-31`，读查询正常。
4. 迁移前没有运行、排队或取消中的 TaskRun，也没有目标对象锁；执行后同样未发现运行中 TaskRun。
5. SSD 可用空间从约 6.4GB 增至约 12GB，HDD 可用空间从约 338GB 变为约 333GB。该值受文件系统展示粒度影响；A 组 catalog 原始统计为 6,014,181,376 bytes，即约 5.60GiB。
6. B 组执行结果见下一节。

### 5.7 B 组执行记录

执行日期：2026-08-02。

1. 已逐对象迁移 `raw_tushare.research_report`、`raw_tushare.irm_qa_sz`、`raw_tushare.irm_qa_sh` 及其 17 个索引，共 20 个对象。
2. 迁移后 20 个对象均位于 `gs_raw_cold_hdd`；对应 raw 表和三个 `core_serving_light` view 的最小读取均正常。
3. 每张表开始前均确认没有关联运行中 TaskRun 和目标锁；执行完成后也没有运行、排队或取消中的 TaskRun。
4. 一期完成后 SSD 可用空间约 13GB、使用率 94%，HDD 可用空间约 331GB。文件系统可用空间会受并发写入与展示粒度影响；一期 catalog 预估收益仍以约 7.13GiB 作为存储对象总量。

## 6. 后续阶段

### 第二期：高收益未分区表的存储方案

目标是对 `index_mins`、新闻、日线、资金流等未分区大表，按读写活跃度选择分区或整表迁移方案。每张表必须先完成：

1. 当前读写路径与 Biz API 消费者审计。
2. 分区键、唯一键、索引、view、外键与写入冲突策略审计。
3. 无业务数据删除的迁移方式、锁窗口、回滚空间和最终验收设计。
4. 单表 LLD、测试与生产维护窗口评审。

### 6.1 新闻快讯 `raw_tushare.news`：整表下沉到 HDD

状态：已执行并验收。

#### 6.1.1 已确认事实与固定边界

1. 分区方案已撤回。生产只保留原单表 `raw_tushare.news`：`id` 是主键，`row_key_hash` 是全局唯一幂等键；`core_serving_light.news`、财富端市场新闻和个股新闻 API 继续读取同一张表。
2. 生产当前有 8,565,264 行新闻，关系总量为 7,432,847,360 bytes（约 7,089 MB），全部位于 SSD `pg_default`。其中有 1 个表 heap 和 4 个索引：`news_pkey`、`uq_raw_tushare_news_row_key_hash`、`idx_raw_tushare_news_time`、`idx_raw_tushare_news_src_time`。
3. 目标 tablespace 是现有 `gs_raw_cold_hdd`；执行用户 `goldenshare_user` 同时拥有新闻表所有权和该 tablespace 的 `CREATE` 权限。审计时 SSD 可用约 14GB，HDD 可用约 331GB。
4. 当前新闻自动任务 `ops.schedule.id=19` 为 `paused`，没有 `queued`、`running` 或 `canceling` 的新闻 TaskRun，也没有持有新闻表的锁。这只是本次审计事实；执行前必须重新检查，不能沿用。
5. 本期只移动 PostgreSQL 关系文件位置。不创建新表，不复制、删除或重写新闻数据，不改变 ORM、DAO、DatasetDefinition、view、API、写入事务或自动任务语义。
6. 整表下沉包含 2026 年新闻，属于已确认的性能取舍：表名和 SQL 契约不变，但新闻查询与写入将读取 HDD，延迟可能上升。

#### 6.1.2 为什么采用整表迁移

1. 新闻表未分区，无法只移动非 2026 数据而不引入新的分区、复制与切换链路。
2. 之前的分区 stage 始终为 0 行。其失败根因是新闻时间使用 `Asia/Shanghai`，而分区边界误用 UTC；该路线已删除，不再修补。
3. PostgreSQL 原生 `ALTER TABLE ... SET TABLESPACE` 只移动表 heap，不会自动移动索引；因此必须明确移动 1 个表和全部 4 个索引。这样保持现有表名、主键、唯一键、view 与下游查询全部不变，是本目标下最短且不引入新架构的路径。

#### 6.1.3 执行前门禁

以下项目必须在同一个维护窗口、DDL 前重新通过；任一项失败则本轮停止，不等待锁、不终止其他会话、不改配置：

1. 确认 `/` 与 `/data/disk` 的可用空间仍分别不低于审计值，并确认 `gs_raw_cold_hdd` 存在。
2. 确认自动任务仍是 paused，且没有新闻相关的 `queued`、`running`、`canceling` TaskRun；维护窗口内不得从页面手动创建新闻任务。
3. 确认 `raw_tushare.news` 没有已授予或等待中的关系锁，也没有超过 30 秒的活动查询。
4. 从 `pg_index` 重新枚举新闻表索引。只有索引清单仍恰为本节列出的 4 个对象时才执行；出现新增或缺失索引必须停止并重新评估。
5. 确认 `raw_tushare.news`、`core_serving_light.news` 存在，且 stage 表不存在；本次不接触任何 stage 或旧分区对象。

#### 6.1.4 生产执行步骤

1. 对每条 DDL 单独执行 `SET lock_timeout = '15s'` 后的一个 `ALTER`。15 秒内无法取得锁即失败退出；不使用 `ALTER ... ALL IN TABLESPACE`，避免扩大锁范围。
2. 先移动 heap：

```sql
ALTER TABLE raw_tushare.news SET TABLESPACE gs_raw_cold_hdd;
```

3. 立即确认 heap 位于 `gs_raw_cold_hdd`、行数与迁移前一致、view 可读，再按以下顺序逐个移动索引：

```sql
ALTER INDEX raw_tushare.news_pkey
  SET TABLESPACE gs_raw_cold_hdd;
ALTER INDEX raw_tushare.uq_raw_tushare_news_row_key_hash
  SET TABLESPACE gs_raw_cold_hdd;
ALTER INDEX raw_tushare.idx_raw_tushare_news_time
  SET TABLESPACE gs_raw_cold_hdd;
ALTER INDEX raw_tushare.idx_raw_tushare_news_src_time
  SET TABLESPACE gs_raw_cold_hdd;
```

4. 每个对象移动后都重新检查其 tablespace、磁盘空间和锁状态。任一 DDL 失败时立刻停止，不自动继续、不自动回迁、不尝试重建。
5. 全部 5 个对象验收通过后，恢复新闻自动任务，再由运营发起一次小窗口 `news.maintain`，验证真实 upsert 与 view/API 查询。恢复排程和真实写入验收必须在迁移 DDL 成功后单独确认执行。

#### 6.1.5 验收与异常处置

验收必须同时满足：

1. 表 heap 与全部 4 个索引均位于 `gs_raw_cold_hdd`；表名、索引名、行数、`core_serving_light.news` 定义均不变。
2. 市场新闻和个股新闻 API 的最小只读请求可用；Ops 任务详情和数据集卡片可正常读取新闻状态。
3. 真实小窗口 `news.maintain` 成功，写入与 view 查询正常，未出现新增 reject 或约束错误。
4. SSD 释放量与 7,089 MB 量级相符，HDD 使用量对应增加；数值受 WAL、并发写入和文件系统展示粒度影响，不以单次 `df` 精确差值作为唯一标准。

若 heap 或任何索引迁移后出现不可接受的性能问题，只能在再次确认 SSD 空间足够后，按已完成对象反向单独执行 `SET TABLESPACE pg_default`。不得通过删除、清空、重建或复制切换处理异常。

#### 6.1.6 执行记录

执行日期：2026-08-02。

1. DDL 前确认新闻自动任务仍为 paused、没有运行中新闻 TaskRun、没有新闻表锁；所有 5 个对象都位于 `pg_default`。
2. 已按本节顺序逐对象执行 1 次 `ALTER TABLE` 和 4 次 `ALTER INDEX`，每条 DDL 均成功完成；没有复制、删除、清空、重建或切换任何业务数据。
3. 执行后表 heap 与全部 4 个索引均位于 `gs_raw_cold_hdd`。新闻行数仍为 8,565,264，最早和最新新闻时间仍分别为 `2022-01-01 00:00:47+08` 与 `2026-08-02 19:59:39+08`。
4. `core_serving_light.news` 的 view 定义未变；新闻快讯当天的 100 条最小样本可读，其中公司新闻 5 条、市场新闻 95 条。Web、Ops worker、Ops scheduler 健康检查均正常。
5. SSD 可用空间从执行前约 14GB 增至约 21GB，HDD 可用空间从约 331GB 降至约 324GB；该差异与 7,089 MB 新闻关系迁移相符。
6. 新闻自动任务继续保持 paused。本轮未恢复排程，也未发起真实 `news.maintain` 写入验收；恢复排程和一次小窗口写入验证需由运营单独确认后执行。

### 6.2 重复 core 物理表收口第一批：`cyq_perf` 与 `stk_nineturn`

状态：待实施。

#### 6.2.1 目标与固定边界

本批不是 HDD 迁移，而是删除无业务转换的重复 core 存储。只处理下列两个数据集：

| 数据集 | raw 表 | 当前 core 物理表 | 当前 core 占用 | 结论 |
| --- | --- | --- | ---: | --- |
| `cyq_perf` 每日筹码及胜率 | `raw_tushare.cyq_perf` | `core_serving.equity_cyq_perf` | 约 2.0GiB | 第一批实施 |
| `stk_nineturn` 神奇九转 | `raw_tushare.stk_nineturn` | `core_serving.equity_nineturn` | 约 0.8GiB | 第一批实施 |

预计释放约 2.8GiB SSD。该收益来自删除两张 core 物理表及其重复索引，不移动 raw 表、不迁移到 HDD、不清空任何 raw 数据。

固定边界：

1. 只修改 `cyq_perf` 与 `stk_nineturn` 的 `DatasetDefinition` 存储事实、对应 Alembic、Ops 交付模式展示和定向测试；不顺手处理其它结构候选。
2. 两个数据集改为 `raw_only_upsert`、`raw->serving_view` 与 `raw_with_serving_view`；`target_table` 指向 raw 表，写入只落 raw。
3. 原 `core_serving` 名称必须保留为普通 view。业务、Ops、数据湖和 ORM 查询继续使用原名称，不允许改为直接查询 raw。
4. view 只投影当前 serving ORM 的业务字段；`fetched_at` 映射为 `created_at`、`updated_at`，满足 `TimestampMixin` 查询契约。
5. `core_dao_name` 改为同一 raw DAO，沿用现有 `cyq_chips` 的 raw-only 写入模式；不修改共享 `DatasetWriter`，不新增兼容写入。
6. core ORM 查询模型可以保留，表示 `core_serving` view 契约；必须删除的是 core 物理表、其索引和对它的写入，不是下游查询名称。

#### 6.2.2 已完成审计

1. 两组 raw/core 的业务字段、字段类型和主键完全一致。core 仅额外保存 `created_at`、`updated_at`。
2. 两组 raw 表已有与 core 等价的主键和二级索引：
   - `cyq_perf`：`(ts_code, trade_date)` 主键、`trade_date`、`(ts_code, trade_date)` 索引。
   - `stk_nineturn`：`(ts_code, trade_date)` 主键、`trade_date` 索引。
3. 代码与生产 catalog 审计均未发现这两张 core 表的 Biz 直接查询、数据库 view 依赖或外键依赖。数据湖的对应同步策略已经直接读取 raw。
4. `raw_with_serving_view` 是现有正式交付模式，已用于 `cyq_chips` 与 `etf_sh_cons`，不是临时兼容设计。
5. 当前 Ops 的 `delivery_mode_label()` 尚未映射 `raw_with_serving_view`，会返回“未定义”。本批必须将其收口为“原始数据直出”，并补后端投影测试；这是保证 Ops 展示事实正确的必要改动，不新增页面功能。

#### 6.2.3 实施顺序

1. **代码与测试先行**：将两个 Definition 切到 raw-only/view 口径，增加 writer 测试，证明写入只调用 raw DAO；补 view ORM 字段、Ops 投影和既有 raw 查询链路回归。
2. **迁移前门禁**：确认真实 Alembic head；确认两数据集无 `queued`、`running`、`canceling` TaskRun，无长事务或目标关系锁；确认 raw/core 行数与业务字段在受控维护窗口内全量一致。任一差异立即停止，不以 view 切换掩盖历史数据差异。
3. **同一发布窗口切换**：停止相关旧 worker 写入入口后，部署包含代码与迁移的同一版本。迁移按每个关系执行：先删除同名 core 物理表及其索引，再创建同名 raw-backed view。不得出现旧 worker 向 view 执行 upsert 的中间窗口。
4. **发布后验收**：确认两个 `core_serving` 对象的 `relkind='v'`；确认 raw 表仍在、索引不变、view 可按日期和代码读取；确认 Ops 卡片展示“原始数据直出”；通过一次后续正常维护验证 raw 写入、view 查询和 TaskRun 结果均正常。
5. **异常处理**：任一迁移、校验或正常维护失败时立即停止，不删除 raw 数据、不自动重建 core 表。只有在明确确认原因和 SSD 空间后，才允许以单独变更恢复物理 core 表。

#### 6.2.4 验收标准

1. `raw_tushare.cyq_perf` 与 `raw_tushare.stk_nineturn` 是唯一写入目标；执行期间没有 core DAO `bulk_upsert`。
2. `core_serving.equity_cyq_perf` 与 `core_serving.equity_nineturn` 均为 view，字段、主键查询语义和原表名保持可用。
3. 迁移前后的受控全量一致性校验无差异；raw 索引定义不退化。
4. Ops、数据湖 raw 导出和两数据集维护任务均通过定向回归；SSD 可用空间增加接近 2.8GiB。
5. 不产生业务数据删除、清空、复制搬运、HDD tablespace 变更或 API 路由变化。

### 第三期：持续治理

1. 每季度复查 SSD/HDD 容量、tablespace 分布和数据集读写活跃度。
2. 对新增的大体量数据集，在接入文档中明确存储增长、冷热属性和未来分区策略。
3. 对已分区表，在每年切换后评估上一年的分区是否可以下沉 HDD；只在确认不再属于热数据后执行。

## 7. 本专项的边界

1. 本文档不是对任何表的自动迁移授权；每次生产 DDL 仍需要用户明确确认。
2. HDD 一期不修改 `DatasetDefinition`、ingestion、writer、DAO、Ops、Biz、API 或前端；第 6.2 节仅允许按其白名单修改对应 Definition、迁移、Ops 交付模式投影和测试。
3. 一期不迁移任何 `core_serving` 主服务表，不迁移当前年份的 `stk_mins` 分区。
4. 一期不删除、清空、重建、归档或导出任何业务表数据。

## 8. 相关文档

1. [Prod 每日筹码分布 HDD Tablespace 迁移方案 v1（已执行）](/Users/congming/github/goldenshare/docs/ops/prod-cyq-chips-hdd-tablespace-migration-plan-v1.md)
2. [股票历史分钟行情 tablespace 冷热分层记录 v1](/Users/congming/github/goldenshare/docs/ops/stk-mins-tablespace-layout-v1.md)
3. [文档维护基线 v1](/Users/congming/github/goldenshare/docs/governance/docs-maintenance-baseline-v1.md)
