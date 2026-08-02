# 生产 PostgreSQL 存储空间优化治理专项 v1

状态：一期已执行并验收；第二期首项“新闻快讯冷热分层”代码开发完成，待生产执行授权
更新时间：2026-08-02
范围：生产 PostgreSQL `goldenshare` 的 SSD/HDD 存储分层。
不在范围：删除、清空业务数据；改变数据集请求语义；修改 API 或前端业务行为。第二期允许为单表冷热分层重建表结构，但必须以完整数据复制、最终切换和逐项验收为前提。

---

## 1. 专项目标

在不改变下游访问方式的前提下，缓解生产 SSD 容量压力：

1. 将确认属于冷数据的 PostgreSQL 关系迁移到现有 HDD tablespace `gs_raw_cold_hdd`。
2. 保持 schema、表名、索引名、view 定义、DAO、API 和数据集写入契约不变。
3. 当前年份持续读写的数据留在 SSD；不能为了释放空间而把热数据整体降到 HDD。
4. 每次迁移只处理明确白名单中的表和索引，先验证，再进入下一批。

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

### 第二期：高收益未分区表的冷热分层设计

目标是对 `index_mins`、新闻、日线、资金流等未分区大表，单独设计年份分区与迁移方案，使 2026 数据继续留在 SSD、历史数据迁入 HDD。每张表必须先完成：

1. 当前读写路径与 Biz API 消费者审计。
2. 分区键、唯一键、索引、view、外键与写入冲突策略审计。
3. 无业务数据删除的迁移方式、锁窗口、回滚空间和最终验收设计。
4. 单表 LLD、测试与生产维护窗口评审。

第二期不允许复用一期的“直接整表迁移”手段。

### 6.1 第二期首项：新闻快讯 `raw_tushare.news` 冷热分层

状态：方案与代码开发完成；待生产执行授权。
目标：只将新闻快讯 2026 年前的历史数据下沉到 `gs_raw_cold_hdd`；2026 年及以后持续写入 SSD。`core_serving_light.news`、财富端市场新闻和个股新闻 API 的表名、字段与查询方式保持不变。

#### 6.1.1 审计事实

审计时间：2026-08-02。审计方式：CodeGraph、当前代码、`bash scripts/psql-remote.sh` 只读查询。

| 项目 | 事实 |
| --- | --- |
| 当前表 | `raw_tushare.news`，单表、未分区，位于 `pg_default` |
| 当前规模 | 8,565,019 行，约 6.92GiB，包含 heap、Toast 与索引 |
| 时间范围 | 2022-01-01 至 2026-08-02 |
| 历史规模 | 2022 至 2025 年共 7,276,479 行，占约 84.96%；按当前总量比例估算可释放约 5.88GiB SSD |
| 当前维护频率 | `news.maintain` 每 30 分钟成功执行一次，不能直接整表下沉 |
| 业务消费 | `core_serving_light.news` 直出 `raw_tushare.news`；财富端市场新闻、个股新闻查询均按 `news_time` 读取该 view |
| 当前幂等键 | `row_key_hash`；其生成内容包含 `src`、`news_time`、标题、正文、频道和评分 |
| 无业务依赖字段 | 当前 `id` 仅为 raw 表代理主键；代码、view、Biz 查询和外键审计均未发现业务消费者 |

同一新闻分组不一起迁移：`raw_tushare.major_news` 当前全部为 2026 数据且每小时维护；`raw_tushare.cctv_news` 仅约 59MB，收益不足。

#### 6.1.2 最终结构与写入口径

`raw_tushare.news` 改为按 `news_time` 的年度 RANGE 分区父表：

| 分区 | tablespace | 作用 |
| --- | --- | --- |
| `news_p2022` 至 `news_p2025` | `gs_raw_cold_hdd` | 已冻结历史新闻 |
| `news_p2026` | `pg_default` | 当前热数据与 30 分钟维护写入 |
| `news_p2027` 至 `news_p2030` | `pg_default` | 未来热分区，避免跨年无分区可写 |

最终业务行标识为 `(news_time, row_key_hash)`：

1. `row_key_hash` 的当前生成规则已包含 `news_time`，因此重复获取同一源站记录仍落入同一分区、同一冲突键。
2. 当前逻辑中，源站修订正文、标题、频道或评分会产生新 hash；新结构保持该现有行为，不额外合并或删除新闻版本。
3. PostgreSQL 分区表的唯一键必须包含分区键，不能保留旧的全局 `UNIQUE(row_key_hash)`；写入冲突目标同步收口为 `(news_time, row_key_hash)`。
4. 删除没有业务消费者的代理列 `id`，不保留无意义的全局主键。所有 view 和 Biz DTO 本来只使用 `row_key_hash`、时间与新闻字段。

保留每个叶分区的两组访问索引：`(news_time DESC)` 服务时间窗口与最新时间查询，`(src, news_time DESC)` 服务来源过滤。历史分区的 heap 与全部索引必须一并位于 HDD；热分区整体保留 SSD。

#### 6.1.3 开发范围

| 层 | 必须修改 | 不修改 |
| --- | --- | --- |
| Foundation model | `RawNews` 的最终复合行标识与分区事实 | `RawMajorNews`、`RawCctvNews` |
| DatasetDefinition / writer | `news` 的 raw conflict key 改为 `(news_time, row_key_hash)`；保留 `raw_only_upsert` | 请求参数、unit、分页、事务边界、新闻来源扇出 |
| Alembic | 只预建空分区父表与年度分区；不复制数据、不切换 view | 其他业务表、Ops 表、数据集表 |
| Biz / API | 不改查询接口；用现有 view 名称获得分区裁剪 | DTO、路由、前端 |
| 测试 | model、DAO upsert、writer conflict key、view 查询和迁移后历史/当年读取 | 无关数据集测试 |

#### 6.1.4 生产切换步骤

1. **开发与本地验证**：先完成 model、Definition、DAO/writer、受控迁移 CLI 和仅预建空 stage 的 Alembic；用空库验证分区、冲突写入、view 查询和索引结构。不得先修改生产表。
2. **生产预建与历史复制**：创建独立的分区目标表和 2022 至 2030 年分区；历史数据按年份复制到对应分区。复制期间线上仍读写旧 `raw_tushare.news`，不引入双写或兼容代码。
3. **最终切换门禁**：暂停 `news.maintain` 的自动触发与人工新建；确认没有 `queued`、`running`、`canceling` 的 `news` TaskRun，且没有长事务访问旧表。
4. **短暂停写切换**：锁定旧表，复制最后增量，核对旧表与新分区表的总行数、按年行数、时间范围、hash 集合抽样和索引；随后原子替换为最终表名，并重建 `core_serving_light.news` 指向新表。此时财富端读请求可能短暂等待锁，但恢复后仍使用原 API 和 view。
5. **恢复写入与真实验证**：完成原子切换后再重启新写入冲突键的 worker，恢复 `news.maintain`；运行一次最小新闻快讯维护，确认源端、归一化、写入、分区归属、view 读取和财富端 API 都一致。
6. **旧表退场**：仅在数据核对、真实维护和 API 验收全部通过后，在同一变更闭环删除旧 relation；不得长期保留旧表、双写或兼容 view。执行删除前必须获得该次生产操作的明确授权。

#### 6.1.5 硬门禁与验收

1. 不允许 `ALTER TABLE raw_tushare.news SET TABLESPACE ...`；这会把 2026 热数据一起迁往 HDD。
2. 不允许以“复制后删除”替代数据核对；旧 relation 删除前必须完成总行数、年度行数、时间边界、hash 抽样、索引和 view/API 读取验收。
3. 生产切换前必须有可用 SSD 空间容纳 2026 热分区与切换阶段临时对象，HDD 空间容纳约 5.88GiB 历史数据及索引；实际容量以执行前 catalog 复核为准。
4. 只暂停新闻快讯写入，不停止其他数据集任务；Ops 状态写入不得影响新闻业务数据事务。
5. 验收后，2022 至 2025 分区及其全部索引位于 `gs_raw_cold_hdd`，2026 至 2030 年分区及其全部索引位于 `pg_default`，`core_serving_light.news` 和财富端两个新闻 API 继续可读。

#### 6.1.6 需要的生产授权

本节只记录方案，不是执行授权。开始生产实施前必须单独确认：

1. 允许在维护窗口内短暂停止 `news.maintain` 写入并短暂阻塞新闻读取，以完成最后增量复制与表名切换。
2. 允许在全部核验通过后删除旧的未分区 `raw_tushare.news` relation；不保留长期备份表或兼容链路。

### 第三期：持续治理

1. 每季度复查 SSD/HDD 容量、tablespace 分布和数据集读写活跃度。
2. 对新增的大体量数据集，在接入文档中明确存储增长、冷热属性和未来分区策略。
3. 对已分区表，在每年切换后评估上一年的分区是否可以下沉 HDD；只在确认不再属于热数据后执行。

## 7. 本专项的边界

1. 本文档不是对任何表的自动迁移授权；每次生产 DDL 仍需要用户明确确认。
2. 一期不修改 `DatasetDefinition`、ingestion、writer、DAO、Ops、Biz、API 或前端。
3. 一期不迁移任何 `core_serving` 主服务表，不迁移当前年份的 `stk_mins` 分区。
4. 一期不删除、清空、重建、归档或导出任何业务表数据。

## 8. 相关文档

1. [Prod 每日筹码分布 HDD Tablespace 迁移方案 v1（已执行）](/Users/congming/github/goldenshare/docs/ops/prod-cyq-chips-hdd-tablespace-migration-plan-v1.md)
2. [股票历史分钟行情 tablespace 冷热分层记录 v1](/Users/congming/github/goldenshare/docs/ops/stk-mins-tablespace-layout-v1.md)
3. [文档维护基线 v1](/Users/congming/github/goldenshare/docs/governance/docs-maintenance-baseline-v1.md)
4. [新闻快讯冷热分层 LLD v1](/Users/congming/github/goldenshare/docs/governance/prod-news-cold-storage-partition-lld-v1.md)
